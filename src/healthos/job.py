from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

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
from healthos.rollup import attach_baselines, should_send_email
from healthos.storage import SupabaseStorage
from healthos.sync import HealthSyncService

SummaryMode = Literal["morning", "evening"]


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

    def run(self, *, mode: str = "auto", days: int | None = None, force: bool = False) -> str:
        self.settings.validate_ai()
        self.settings.validate_email()
        resolved_mode = infer_summary_mode(datetime.now(self.settings.timezone)) if mode == "auto" else mode
        if resolved_mode not in {"morning", "evening"}:
            raise ValueError("mode must be auto, morning, or evening")
        sync_days = days if days is not None else (3 if resolved_mode == "morning" else 2)
        result = self.sync_service.sync_recent_days(
            sync_days,
            include_partial=resolved_mode == "evening",
        )
        target_date = self._target_date(resolved_mode, result.end_date)
        current_row = self.storage.get_daily_metric(result.account.id, target_date)
        if current_row is None:
            raise RuntimeError(f"No daily metrics found for {target_date.isoformat()}")

        history = self.storage.list_daily_metrics(
            result.account.id,
            target_date - timedelta(days=28),
            target_date - timedelta(days=1),
        )
        metric = DailyMetric.from_row(current_row)
        attach_baselines(metric, history)
        metric_row = metric.to_row(result.account.id)
        self.storage.upsert_daily_metric_row(metric_row)

        payload = build_prompt_payload(resolved_mode, metric_row)
        data_hash = payload_hash(payload)
        refreshed_row = self.storage.get_daily_metric(result.account.id, target_date)
        if not should_send_email(refreshed_row, resolved_mode, data_hash, force=force):
            return f"Skipped {resolved_mode} email for {target_date.isoformat()}; already sent."

        generation = self.ai.generate_draft(payload, instructions=COACH_INSTRUCTIONS)
        report = render_email_report(
            mode=resolved_mode,
            metric_date=target_date,
            metric_row=metric_row,
            draft=generation.draft,
        )
        self.emailer.send(
            subject=report.subject,
            body=report.text_body,
            html_body=report.html_body,
        )
        self.storage.mark_email_sent(
            result.account.id,
            target_date,
            resolved_mode,
            data_hash,
            ai_provider=generation.provider,
            ai_model=generation.model,
        )
        return f"Sent {resolved_mode} email for {target_date.isoformat()}."

    def sync_only(self, *, days: int) -> str:
        result = self.sync_service.sync_recent_days(days, include_partial=False)
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

    def _target_date(self, mode: str, end_date: date) -> date:
        today = end_date - timedelta(days=1)
        if mode == "morning":
            return today
        return datetime.now(self.settings.timezone).date()


def infer_summary_mode(now_local: datetime) -> SummaryMode:
    if now_local.hour >= 17 or now_local.hour < 4:
        return "evening"
    return "morning"
