from __future__ import annotations

from datetime import datetime, timedelta

from healthos.coach import (
    COACH_INSTRUCTIONS,
    build_prompt_payload,
    payload_hash,
)
from healthos.config import Settings
from healthos.emailer import EmailSender
from healthos.google_health import GoogleHealthClient, GoogleOAuthClient
from healthos.http_client import JsonHttpClient
from healthos.models import DailyMetric
from healthos.openai_client import AIClient
from healthos.report import render_email_report
from healthos.rollup import attach_baselines, should_send_morning_email
from healthos.storage import SupabaseStorage
from healthos.sync import HealthSyncService


class HealthOSJob:
    def __init__(
        self,
        *,
        settings: Settings,
        sync_service: HealthSyncService,
        storage: SupabaseStorage,
        ai: AIClient,
        emailer: EmailSender,
    ) -> None:
        self.settings = settings
        self.sync_service = sync_service
        self.storage = storage
        self.ai = ai
        self.emailer = emailer

    @classmethod
    def from_settings(cls, settings: Settings) -> "HealthOSJob":
        http = JsonHttpClient()
        oauth = GoogleOAuthClient(http, settings.google_client_id, settings.google_client_secret)
        health = GoogleHealthClient(http)
        storage = SupabaseStorage(settings, http)
        sync_service = HealthSyncService(
            settings=settings,
            oauth=oauth,
            health=health,
            storage=storage,
        )
        return cls(
            settings=settings,
            sync_service=sync_service,
            storage=storage,
            ai=AIClient(settings, http),
            emailer=EmailSender(settings, http=http, oauth=oauth),
        )

    def run(self, *, days: int | None = None, force: bool = False) -> str:
        self.settings.validate_ai()
        self.settings.validate_email()
        sync_days = days if days is not None else 3
        if sync_days < 2:
            raise ValueError("days must be at least 2 for the morning report")
        result = self.sync_service.sync_recent_days(sync_days)
        report_date = result.end_date - timedelta(days=1)
        activity_date = report_date - timedelta(days=1)
        sleep_recovery_row = self.storage.get_daily_metric(result.account.id, report_date)
        activity_row = self.storage.get_daily_metric(result.account.id, activity_date)
        if sleep_recovery_row is None:
            raise RuntimeError(f"No daily metrics found for {report_date.isoformat()}")
        if activity_row is None:
            raise RuntimeError(f"No daily metrics found for {activity_date.isoformat()}")

        history = self.storage.list_daily_metrics(
            result.account.id,
            report_date - timedelta(days=29),
            report_date - timedelta(days=1),
        )
        sleep_recovery_metric = attach_baselines(DailyMetric.from_row(sleep_recovery_row), history)
        activity_metric = attach_baselines(DailyMetric.from_row(activity_row), history)
        sleep_recovery_row = sleep_recovery_metric.to_row(result.account.id)
        activity_row = activity_metric.to_row(result.account.id)
        self.storage.upsert_daily_metric_row(sleep_recovery_row)
        self.storage.upsert_daily_metric_row(activity_row)

        payload = build_prompt_payload(report_date, sleep_recovery_row, activity_row)
        data_hash = payload_hash(payload)
        refreshed_row = self.storage.get_daily_metric(result.account.id, report_date)
        if not should_send_morning_email(refreshed_row, data_hash, force=force):
            return f"Skipped morning email for {report_date.isoformat()}; already sent."

        generation = self.ai.generate_draft(payload, instructions=COACH_INSTRUCTIONS)
        report = render_email_report(
            report_date=report_date,
            sleep_recovery_row=sleep_recovery_row,
            activity_row=activity_row,
            draft=generation.draft,
        )
        self.emailer.send(
            subject=report.subject,
            body=report.text_body,
            html_body=report.html_body,
        )
        self.storage.mark_morning_email_sent(
            result.account.id,
            report_date,
            data_hash,
            ai_provider=generation.provider,
            ai_model=generation.model,
        )
        return f"Sent morning email for {report_date.isoformat()}."

    def sync_only(self, *, days: int) -> str:
        result = self.sync_service.sync_recent_days(days)
        return (
            f"Synced {len(result.records)} records and {len(result.metrics)} daily metrics "
            f"from {result.start_date.isoformat()} to {result.end_date.isoformat()}."
        )

    def cleanup_raw_records(self, *, raw_days: int = 30) -> str:
        if raw_days < 1:
            raise ValueError("raw-days must be at least 1")
        self.settings.validate_storage()
        account = self.storage.get_account_by_key(self.settings.account_key)
        if account is None:
            return f"No health account found for {self.settings.account_key}; no raw records deleted."

        today = datetime.now(self.settings.timezone).date()
        cutoff_date = today - timedelta(days=raw_days)
        deleted = self.storage.delete_health_records_before(account.id, cutoff_date)
        return (
            f"Deleted {deleted} raw health records before {cutoff_date.isoformat()}; "
            "daily metrics were not changed."
        )
