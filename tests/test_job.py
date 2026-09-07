from __future__ import annotations

import unittest
from datetime import date

from healthos.coach import CoachDraft
from healthos.config import GMAIL_SEND_SCOPE, Settings
from healthos.job import HealthOSJob
from healthos.models import Account
from healthos.openai_client import DraftGenerationResult
from healthos.sync import SyncResult


class HealthOSJobTests(unittest.TestCase):
    def test_successful_email_is_marked_sent(self) -> None:
        storage = FakeRunStorage()
        emailer = FakeEmailer()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=storage,
            ai=FakeAI(),
            emailer=emailer,
        )

        result = job.run(mode="morning", force=True)

        self.assertEqual(result, "Sent morning email for 2026-09-06.")
        self.assertEqual(len(emailer.sent), 1)
        self.assertIn("<!doctype html>", emailer.sent[0]["html_body"])
        self.assertTrue(storage.mark_email_sent_called)

    def test_failed_email_is_not_marked_sent(self) -> None:
        storage = FakeRunStorage()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=storage,
            ai=FakeAI(),
            emailer=FailingEmailer(),
        )

        with self.assertRaises(RuntimeError):
            job.run(mode="morning", force=True)

        self.assertFalse(storage.mark_email_sent_called)

    def test_cleanup_raw_records_uses_raw_retention_storage_method(self) -> None:
        storage = FakeCleanupStorage()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=storage,
            ai=FakeAI(),
            emailer=FakeEmailer(),
        )

        result = job.cleanup_raw_records(raw_days=30)

        self.assertIn("Deleted 3 raw health records before", result)
        self.assertIn("daily metrics were not changed", result)
        self.assertEqual(storage.deleted_account_id, "account-id")


class FakeSyncService:
    def sync_recent_days(self, days, *, include_partial=False):
        return SyncResult(
            account=Account(id="account-id", account_key="personal"),
            records=[],
            metrics=[],
            start_date=date(2026, 9, 4),
            end_date=date(2026, 9, 7),
        )


class FakeRunStorage:
    def __init__(self) -> None:
        self.mark_email_sent_called = False

    def get_daily_metric(self, account_id, metric_date):
        return {
            "account_id": account_id,
            "metric_date": metric_date.isoformat(),
            "sleep_minutes_asleep": 420,
            "sleep_efficiency": 0.91,
            "data_quality": {"has_sleep": True, "has_recovery": False, "has_activity": False},
        }

    def list_daily_metrics(self, account_id, start_date, end_date):
        return []

    def upsert_daily_metric_row(self, row):
        self.upserted_row = row

    def mark_email_sent(self, *args, **kwargs):
        self.mark_email_sent_called = True


class FakeCleanupStorage:
    def __init__(self) -> None:
        self.deleted_account_id = None

    def get_account_by_key(self, account_key):
        return Account(id="account-id", account_key=account_key)

    def delete_health_records_before(self, account_id, cutoff_date):
        self.deleted_account_id = account_id
        self.cutoff_date = cutoff_date
        return 3


class FakeAI:
    def generate_draft(self, payload, *, instructions):
        return DraftGenerationResult(
            draft=CoachDraft(
                summary="今天資料大致可用。",
                signals=("睡眠接近近期平均。",),
                coach_notes=("先保守起步。",),
                cautions=(),
            ),
            provider="rule_based",
            model="rule-based",
        )


class FakeEmailer:
    def __init__(self) -> None:
        self.sent = []

    def send(self, *, subject, body, html_body=None):
        self.sent.append({"subject": subject, "body": body, "html_body": html_body})
        return True


class FailingEmailer:
    def send(self, *, subject, body, html_body=None):
        raise RuntimeError("gmail send failed")


def _settings() -> Settings:
    return Settings(
        google_client_id="client",
        google_client_secret="secret",
        google_refresh_token="refresh",
        google_scopes=("scope", GMAIL_SEND_SCOPE),
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        account_key="personal",
        openai_api_key="openai",
        openai_model="gpt-5-mini",
        ai_max_output_tokens=700,
        gmail_from_email="from@example.com",
        summary_recipient_email="to@example.com",
        timezone_name="America/Chicago",
        strict_data_types=False,
        ai_provider="rule_based",
    )


if __name__ == "__main__":
    unittest.main()
