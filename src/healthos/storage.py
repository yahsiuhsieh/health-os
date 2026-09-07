from __future__ import annotations

import urllib.parse
from datetime import date
from typing import Any

from healthos.config import Settings
from healthos.http_client import HttpError, JsonHttpClient
from healthos.models import Account, DailyMetric, HealthRecord
from healthos.utils import iso_or_none, utc_now


class SupabaseStorage:
    def __init__(self, settings: Settings, http: JsonHttpClient) -> None:
        self.settings = settings
        self.http = http

    def upsert_account(self, identity: dict[str, Any]) -> Account:
        row = {
            "account_key": self.settings.account_key,
            "google_health_user_id": identity.get("healthUserId"),
            "google_legacy_user_id": identity.get("legacyUserId"),
            "authorized_scopes": list(self.settings.google_scopes),
            "refresh_token_ref": "GOOGLE_REFRESH_TOKEN",
        }
        result = self._request(
            "POST",
            "health_accounts",
            params={"on_conflict": "account_key"},
            json_body=[row],
            prefer="resolution=merge-duplicates,return=representation",
        )
        saved = result[0]
        return Account(
            id=saved["id"],
            account_key=saved["account_key"],
            google_health_user_id=saved.get("google_health_user_id"),
            google_legacy_user_id=saved.get("google_legacy_user_id"),
        )

    def get_account_by_key(self, account_key: str) -> Account | None:
        rows = self._request(
            "GET",
            "health_accounts",
            query=(
                f"account_key=eq.{urllib.parse.quote(account_key, safe='')}"
                "&select=id,account_key,google_health_user_id,google_legacy_user_id"
            ),
        )
        if not rows:
            return None
        row = rows[0]
        return Account(
            id=row["id"],
            account_key=row["account_key"],
            google_health_user_id=row.get("google_health_user_id"),
            google_legacy_user_id=row.get("google_legacy_user_id"),
        )

    def mark_sync_started(self, account_key: str) -> None:
        self._request(
            "PATCH",
            "health_accounts",
            query=f"account_key=eq.{urllib.parse.quote(account_key, safe='')}",
            json_body={
                "last_sync_started_at": iso_or_none(utc_now()),
                "last_sync_status": "running",
                "last_sync_error": None,
            },
            prefer="return=minimal",
        )

    def mark_sync_completed(self, account_id: str, status: str, error: str | None = None) -> None:
        self._request(
            "PATCH",
            "health_accounts",
            query=f"id=eq.{account_id}",
            json_body={
                "last_sync_completed_at": iso_or_none(utc_now()),
                "last_sync_status": status,
                "last_sync_error": error,
            },
            prefer="return=minimal",
        )

    def mark_sync_failed(self, account_key: str, error: str) -> None:
        self._request(
            "PATCH",
            "health_accounts",
            query=f"account_key=eq.{urllib.parse.quote(account_key, safe='')}",
            json_body={
                "last_sync_completed_at": iso_or_none(utc_now()),
                "last_sync_status": "error",
                "last_sync_error": error,
            },
            prefer="return=minimal",
        )

    def upsert_health_records(self, account_id: str, records: list[HealthRecord]) -> None:
        if not records:
            return
        rows = [record.to_row(account_id) for record in records]
        for chunk in _chunks(rows, 500):
            self._request(
                "POST",
                "health_records",
                params={"on_conflict": "account_id,source_record_id"},
                json_body=chunk,
                prefer="resolution=merge-duplicates,return=minimal",
            )

    def upsert_daily_metric(self, account_id: str, metric: DailyMetric) -> None:
        self.upsert_daily_metric_row(metric.to_row(account_id))

    def upsert_daily_metric_row(self, row: dict[str, Any]) -> None:
        self._request(
            "POST",
            "daily_health_metrics",
            params={"on_conflict": "account_id,metric_date"},
            json_body=[row],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def get_daily_metric(self, account_id: str, metric_date: date) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "daily_health_metrics",
            query=f"account_id=eq.{account_id}&metric_date=eq.{metric_date.isoformat()}&select=*",
        )
        return rows[0] if rows else None

    def list_daily_metrics(self, account_id: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
        query = (
            f"account_id=eq.{account_id}"
            f"&metric_date=gte.{start_date.isoformat()}"
            f"&metric_date=lte.{end_date.isoformat()}"
            "&select=*"
            "&order=metric_date.asc"
        )
        return self._request("GET", "daily_health_metrics", query=query)

    def delete_health_records_before(self, account_id: str, cutoff_date: date) -> int:
        rows = self._request(
            "DELETE",
            "health_records",
            query=f"account_id=eq.{account_id}&metric_date=lt.{cutoff_date.isoformat()}",
            prefer="return=representation",
        )
        return len(rows) if isinstance(rows, list) else 0

    def mark_email_sent(
        self,
        account_id: str,
        metric_date: date,
        mode: str,
        data_hash: str,
        *,
        ai_provider: str | None = None,
        ai_model: str | None = None,
    ) -> None:
        if mode not in {"morning", "evening"}:
            raise ValueError(f"Unsupported email mode: {mode}")
        body = {
            f"{mode}_email_sent_at": iso_or_none(utc_now()),
            f"{mode}_data_hash": data_hash,
        }
        if ai_provider is not None:
            body[f"{mode}_ai_provider"] = ai_provider
        if ai_model is not None:
            body[f"{mode}_ai_model"] = ai_model

        try:
            self._request(
                "PATCH",
                "daily_health_metrics",
                query=f"account_id=eq.{account_id}&metric_date=eq.{metric_date.isoformat()}",
                json_body=body,
                prefer="return=minimal",
            )
        except HttpError as exc:
            if not (ai_provider or ai_model) or "schema cache" not in exc.body.lower():
                raise
            self._request(
                "PATCH",
                "daily_health_metrics",
                query=f"account_id=eq.{account_id}&metric_date=eq.{metric_date.isoformat()}",
                json_body={
                    f"{mode}_email_sent_at": body[f"{mode}_email_sent_at"],
                    f"{mode}_data_hash": data_hash,
                },
                prefer="return=minimal",
            )

    def _request(
        self,
        method: str,
        table: str,
        *,
        query: str = "",
        params: dict[str, str] | None = None,
        json_body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        url = f"{self.settings.supabase_url}/rest/v1/{table}"
        if query:
            url = f"{url}?{query}"
        headers = {
            "apikey": self.settings.supabase_service_role_key,
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return self.http.request(method, url, headers=headers, params=params, json_body=json_body)


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]
