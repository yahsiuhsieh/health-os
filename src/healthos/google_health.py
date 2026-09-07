from __future__ import annotations

import http.server
import socketserver
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

from healthos.http_client import JsonHttpClient
from healthos.models import HealthRecord
from healthos.utils import (
    civil_datetime_to_date,
    google_civil_datetime,
    parse_datetime,
    stable_hash,
)


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_HEALTH_BASE_URL = "https://health.googleapis.com/v4"

DATA_TYPE_FIELD = {
    "sleep": "sleep",
    "exercise": "exercise",
    "steps": "steps",
    "active-zone-minutes": "activeZoneMinutes",
    "active-minutes": "activeMinutes",
    "sedentary-period": "sedentaryPeriod",
    "daily-resting-heart-rate": "dailyRestingHeartRate",
    "daily-heart-rate-variability": "dailyHeartRateVariability",
    "daily-respiratory-rate": "dailyRespiratoryRate",
    "daily-oxygen-saturation": "dailyOxygenSaturation",
    "daily-sleep-temperature-derivations": "dailySleepTemperatureDerivations",
    "daily-vo2-max": "dailyVo2Max",
    "weight": "weight",
}

LIST_DATA_TYPES = (
    "sleep",
    "exercise",
    "daily-resting-heart-rate",
    "daily-heart-rate-variability",
    "daily-respiratory-rate",
    "daily-oxygen-saturation",
    "daily-sleep-temperature-derivations",
    "daily-vo2-max",
    "weight",
)

ROLLUP_DATA_TYPES = (
    "steps",
    "active-zone-minutes",
    "active-minutes",
    "sedentary-period",
)


@dataclass
class TokenResponse:
    access_token: str
    expires_in: int | None = None
    scope: str | None = None


class GoogleOAuthClient:
    def __init__(self, http: JsonHttpClient, client_id: str, client_secret: str) -> None:
        self.http = http
        self.client_id = client_id
        self.client_secret = client_secret

    def authorization_url(self, redirect_uri: str, scopes: tuple[str, ...], state: str = "healthos") -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        return self.http.request(
            "POST",
            GOOGLE_TOKEN_URL,
            form_body={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    def refresh_access_token(self, refresh_token: str, scopes: tuple[str, ...] | None = None) -> TokenResponse:
        form_body = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if scopes:
            form_body["scope"] = " ".join(scopes)
        payload = self.http.request(
            "POST",
            GOOGLE_TOKEN_URL,
            form_body=form_body,
        )
        return TokenResponse(
            access_token=payload["access_token"],
            expires_in=payload.get("expires_in"),
            scope=payload.get("scope"),
        )

    def run_local_authorization(
        self,
        *,
        redirect_uri: str,
        scopes: tuple[str, ...],
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("auth-local requires a localhost redirect URI")
        port = parsed.port or 80
        path = parsed.path or "/"
        holder: dict[str, str] = {}

        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:  # noqa: N802
                callback = urllib.parse.urlparse(self.path)
                if callback.path != path:
                    self.send_response(404)
                    self.end_headers()
                    return
                values = urllib.parse.parse_qs(callback.query)
                holder["code"] = values.get("code", [""])[0]
                holder["error"] = values.get("error", [""])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"HealthOS authorization received. You can close this tab.")

        with socketserver.TCPServer((parsed.hostname or "127.0.0.1", port), CallbackHandler) as server:
            server.timeout = timeout_seconds
            thread = threading.Thread(target=server.handle_request, daemon=True)
            thread.start()
            thread.join(timeout_seconds + 2)

        if holder.get("error"):
            raise RuntimeError(f"Google OAuth returned error: {holder['error']}")
        if not holder.get("code"):
            raise TimeoutError("Timed out waiting for OAuth callback")
        return self.exchange_code(holder["code"], redirect_uri)


class GoogleHealthClient:
    def __init__(self, http: JsonHttpClient) -> None:
        self.http = http

    def get_identity(self, access_token: str) -> dict[str, Any]:
        return self.http.request(
            "GET",
            f"{GOOGLE_HEALTH_BASE_URL}/users/me/identity",
            headers=self._headers(access_token),
        )

    def list_data_points(
        self,
        access_token: str,
        data_type: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        field = DATA_TYPE_FIELD[data_type]
        params: dict[str, str | int] = {
            "filter": self._filter_for(data_type, field, start_date, end_date),
            "pageSize": 25 if data_type in {"sleep", "exercise"} else 1000,
        }
        points: list[dict[str, Any]] = []
        page_token = ""
        while True:
            if page_token:
                params["pageToken"] = page_token
            response = self.http.request(
                "GET",
                f"{GOOGLE_HEALTH_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints",
                headers=self._headers(access_token),
                params=params,
            )
            points.extend(response.get("dataPoints", []))
            page_token = response.get("nextPageToken", "")
            if not page_token:
                return points

    def daily_rollup(
        self,
        access_token: str,
        data_type: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        max_days = _max_daily_rollup_days(data_type)
        current_start = start_date
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=max_days), end_date)
            page_size = max(1, (current_end - current_start).days)
            payload = {
                "range": {
                    "start": google_civil_datetime(current_start, time.min),
                    "end": google_civil_datetime(current_end, time.min),
                },
                "windowSizeDays": 1,
                "pageSize": page_size,
                "dataSourceFamily": "users/me/dataSourceFamilies/all-sources",
            }
            response = self.http.request(
                "POST",
                f"{GOOGLE_HEALTH_BASE_URL}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
                headers=self._headers(access_token),
                json_body=payload,
            )
            points.extend(response.get("rollupDataPoints", []))
            current_start = current_end
        return points

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    def _filter_for(self, data_type: str, field: str, start_date: date, end_date: date) -> str:
        start = start_date.isoformat()
        end = end_date.isoformat()
        filter_name = data_type.replace("-", "_")
        if data_type == "sleep":
            return f'sleep.interval.civil_end_time >= "{start}" AND sleep.interval.civil_end_time < "{end}"'
        if data_type == "exercise":
            return (
                f'exercise.interval.civil_start_time >= "{start}" '
                f'AND exercise.interval.civil_start_time < "{end}"'
            )
        if data_type == "weight":
            return f'weight.sample_time.civil_time >= "{start}" AND weight.sample_time.civil_time < "{end}"'
        return f'{filter_name}.date >= "{start}" AND {filter_name}.date < "{end}"'


def data_point_to_record(data_type: str, point: dict[str, Any]) -> HealthRecord:
    field = DATA_TYPE_FIELD[data_type]
    value = point.get(field, {})
    metric_date = infer_metric_date(data_type, value)
    observed_start_at, observed_end_at = infer_observed_interval(value)
    source_record_id = point.get("name") or f"{data_type}:{stable_hash(point)}"
    return HealthRecord(
        data_type=data_type,
        source_record_id=source_record_id,
        value_json=value,
        raw_json=point,
        metric_date=metric_date,
        observed_start_at=observed_start_at,
        observed_end_at=observed_end_at,
    )


def rollup_point_to_record(data_type: str, point: dict[str, Any]) -> HealthRecord:
    field = DATA_TYPE_FIELD[data_type]
    value = point.get(field, {})
    metric_date = civil_datetime_to_date(point.get("civilStartTime"))
    source_record_id = f"{data_type}:rollup:{metric_date.isoformat() if metric_date else stable_hash(point)}"
    return HealthRecord(
        data_type=data_type,
        source_record_id=source_record_id,
        value_json=value,
        raw_json=point,
        metric_date=metric_date,
    )


def infer_metric_date(data_type: str, value: dict[str, Any]) -> date | None:
    if "date" in value:
        from healthos.utils import parse_google_date

        return parse_google_date(value.get("date"))
    interval = value.get("interval") or {}
    if data_type == "sleep":
        return civil_datetime_to_date(interval.get("civilEndTime")) or _instant_date(
            interval.get("endTime"),
            interval.get("endUtcOffset"),
        )
    if data_type == "exercise":
        return civil_datetime_to_date(interval.get("civilStartTime")) or _instant_date(
            interval.get("startTime"),
            interval.get("startUtcOffset"),
        )
    if "civilStartTime" in interval:
        return civil_datetime_to_date(interval.get("civilStartTime"))
    if "sampleTime" in value:
        return civil_datetime_to_date(value["sampleTime"].get("civilTime"))
    return None


def infer_observed_interval(value: dict[str, Any]) -> tuple[Any, Any]:
    interval = value.get("interval") or {}
    return parse_datetime(interval.get("startTime")), parse_datetime(interval.get("endTime"))


def _instant_date(value: str | None, utc_offset: str | None = None) -> date | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    offset = _utc_offset_delta(utc_offset)
    if offset is not None:
        parsed = parsed + offset
    return parsed.date()


def _utc_offset_delta(value: str | None) -> timedelta | None:
    if not value or not value.endswith("s"):
        return None
    try:
        return timedelta(seconds=int(value[:-1]))
    except ValueError:
        return None


def _max_daily_rollup_days(data_type: str) -> int:
    if data_type == "active-minutes":
        return 14
    return 90
