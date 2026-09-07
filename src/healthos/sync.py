from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, timedelta

from healthos.config import Settings
from healthos.google_health import (
    LIST_DATA_TYPES,
    ROLLUP_DATA_TYPES,
    GoogleHealthClient,
    GoogleOAuthClient,
    data_point_to_record,
    rollup_point_to_record,
)
from healthos.http_client import HttpError
from healthos.models import Account, DailyMetric, HealthRecord
from healthos.rollup import RollupBuilder
from healthos.storage import SupabaseStorage
from healthos.utils import utc_now


@dataclass
class SyncResult:
    account: Account
    records: list[HealthRecord]
    metrics: list[DailyMetric]
    start_date: date
    end_date: date


class HealthSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        oauth: GoogleOAuthClient,
        health: GoogleHealthClient,
        storage: SupabaseStorage,
    ) -> None:
        self.settings = settings
        self.oauth = oauth
        self.health = health
        self.storage = storage

    def sync_recent_days(self, days: int) -> SyncResult:
        self.settings.validate_sync()
        self.storage.mark_sync_started(self.settings.account_key)
        account: Account | None = None
        try:
            token = self.oauth.refresh_access_token(
                self.settings.google_refresh_token,
                scopes=self.settings.health_scopes,
            )
            identity = self.health.get_identity(token.access_token)
            account = self.storage.upsert_account(identity)
            start_date, end_date = self._date_range(days)
            records = self._fetch_records(token.access_token, start_date, end_date)
            self.storage.upsert_health_records(account.id, records)

            dates = [
                start_date + timedelta(days=offset)
                for offset in range((end_date - start_date).days)
            ]
            metrics = RollupBuilder().build_for_dates(records, dates)
            for metric in metrics:
                self.storage.upsert_daily_metric(account.id, metric)
            self.storage.mark_sync_completed(account.id, "ok")
            return SyncResult(account, records, metrics, start_date, end_date)
        except Exception as exc:
            if account:
                self.storage.mark_sync_completed(account.id, "error", str(exc))
            else:
                self.storage.mark_sync_failed(self.settings.account_key, str(exc))
            raise

    def _fetch_records(self, access_token: str, start_date: date, end_date: date) -> list[HealthRecord]:
        records: list[HealthRecord] = []
        for data_type in LIST_DATA_TYPES:
            try:
                points = self.health.list_data_points(access_token, data_type, start_date, end_date)
            except HttpError as exc:
                if self.settings.strict_data_types:
                    raise
                print(f"Skipping {data_type}: {exc}", file=sys.stderr)
                continue
            records.extend(data_point_to_record(data_type, point) for point in points)
        for data_type in ROLLUP_DATA_TYPES:
            try:
                points = self.health.daily_rollup(access_token, data_type, start_date, end_date)
            except HttpError as exc:
                if self.settings.strict_data_types:
                    raise
                print(f"Skipping {data_type}: {exc}", file=sys.stderr)
                continue
            records.extend(rollup_point_to_record(data_type, point) for point in points)
        return records

    def _date_range(self, days: int) -> tuple[date, date]:
        today = utc_now().astimezone(self.settings.timezone).date()
        return today - timedelta(days=days - 1), today + timedelta(days=1)
