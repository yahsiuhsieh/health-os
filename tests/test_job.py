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
    def test_successful_email_uses_latest_sleep_and_previous_day_activity(self) -> None:
        storage = FakeRunStorage()
        sync_service = FakeSyncService()
        ai = FakeAI()
        emailer = FakeEmailer()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=sync_service,
            storage=storage,
            ai=ai,
            emailer=emailer,
        )

        result = job.run(force=True)

        self.assertEqual(result, "Sent morning email for 2026-09-07.")
        self.assertEqual(sync_service.calls, [{"days": 3}])
        self.assertEqual(ai.payload["sleep_recovery"]["metric_date"], "2026-09-07")
        self.assertEqual(ai.payload["previous_day_activity"]["metric_date"], "2026-09-06")
        self.assertEqual(storage.marked_date, date(2026, 9, 7))
        self.assertEqual(len(emailer.sent), 1)
        self.assertIn("<!doctype html>", emailer.sent[0]["html_body"])

    def test_missing_health_data_still_sends_a_cautioned_report(self) -> None:
        storage = FakeRunStorage(missing_data=True)
        emailer = FakeEmailer()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=storage,
            ai=FakeAI(use_rule_based=True),
            emailer=emailer,
        )

        result = job.run(force=True)

        self.assertEqual(result, "Sent morning email for 2026-09-07.")
        self.assertIn("缺資料", emailer.sent[0]["body"])

    def test_existing_report_marker_skips_duplicate_email(self) -> None:
        storage = FakeRunStorage(already_sent=True)
        ai = FakeAI()
        emailer = FakeEmailer()
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=storage,
            ai=ai,
            emailer=emailer,
        )

        result = job.run()

        self.assertEqual(result, "Skipped morning email for 2026-09-07; already sent.")
        self.assertIsNone(ai.payload)
        self.assertEqual(emailer.sent, [])

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
            job.run(force=True)

        self.assertIsNone(storage.marked_date)

    def test_report_requires_at_least_two_sync_days(self) -> None:
        job = HealthOSJob(
            settings=_settings(),
            sync_service=FakeSyncService(),
            storage=FakeRunStorage(),
            ai=FakeAI(),
            emailer=FakeEmailer(),
        )

        with self.assertRaisesRegex(ValueError, "at least 2"):
            job.run(days=1)

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
    def __init__(self) -> None:
        self.calls = []

    def sync_recent_days(self, days):
        self.calls.append({"days": days})
        return SyncResult(
            account=Account(id="account-id", account_key="personal"),
            records=[],
            metrics=[],
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 8),
        )


class FakeRunStorage:
    def __init__(self, *, missing_data: bool = False, already_sent: bool = False) -> None:
        self.missing_data = missing_data
        self.already_sent = already_sent
        self.rows = {}
        self.marked_date = None

    def get_daily_metric(self, account_id, metric_date):
        if metric_date in self.rows:
            return self.rows[metric_date]
        if self.missing_data:
            row = {
                "account_id": account_id,
                "metric_date": metric_date.isoformat(),
                "data_quality": {"has_sleep": False, "has_recovery": False, "has_activity": False},
            }
        elif metric_date == date(2026, 9, 7):
            row = {
                "account_id": account_id,
                "metric_date": metric_date.isoformat(),
                "sleep_minutes_asleep": 420,
                "sleep_efficiency": 0.91,
                "hrv_rmssd_ms": 95,
                "resting_hr_bpm": 57,
                "respiratory_rate_bpm": 14.5,
                "data_quality": {"has_sleep": True, "has_recovery": True, "has_activity": False},
            }
            if self.already_sent:
                row["morning_email_sent_at"] = "2026-09-07T14:05:00Z"
                row["morning_data_hash"] = "previous-hash"
        else:
            row = {
                "account_id": account_id,
                "metric_date": metric_date.isoformat(),
                "steps": 8400,
                "exercise_minutes": 45,
                "active_minutes_total": 72,
                "data_quality": {"has_sleep": False, "has_recovery": False, "has_activity": True},
            }
        self.rows[metric_date] = row
        return row

    def list_daily_metrics(self, account_id, start_date, end_date):
        return []

    def upsert_daily_metric_row(self, row):
        metric_date = date.fromisoformat(row["metric_date"])
        self.rows[metric_date] = {**self.rows.get(metric_date, {}), **row}

    def mark_morning_email_sent(self, account_id, metric_date, data_hash, **kwargs):
        self.marked_date = metric_date


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
    def __init__(self, *, use_rule_based: bool = False) -> None:
        self.use_rule_based = use_rule_based
        self.payload = None

    def generate_draft(self, payload, *, instructions):
        from healthos.coach import rule_based_coach_draft

        self.payload = payload
        draft = rule_based_coach_draft(payload) if self.use_rule_based else CoachDraft(
            summary="今天資料大致可用。",
            sleep_insight="昨晚睡眠接近近期平均。",
            activity_insight="昨天活動量穩定。",
            recovery_insight="恢復指標接近近期範圍。",
            today_actions=("先保守起步。",),
            cautions=(),
        )
        return DraftGenerationResult(
            draft=draft,
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
