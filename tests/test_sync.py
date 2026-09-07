from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from datetime import date
from io import StringIO

from healthos.config import GMAIL_SEND_SCOPE, Settings
from healthos.http_client import HttpError
from healthos.sync import HealthSyncService


class FakeHealth:
    def list_data_points(self, access_token, data_type, start_date, end_date):
        if data_type == "daily-vo2-max":
            raise HttpError(403, "not authorized", "https://health.googleapis.com")
        return []

    def daily_rollup(self, access_token, data_type, start_date, end_date):
        return []


class FailingOAuth:
    def refresh_access_token(self, refresh_token, scopes=None):
        raise RuntimeError("invalid refresh token")


class TrackingOAuth:
    def __init__(self) -> None:
        self.scopes = []

    def refresh_access_token(self, refresh_token, scopes=None):
        self.scopes.append(scopes)
        raise RuntimeError("stop after token request")


class TrackingStorage:
    def __init__(self) -> None:
        self.started_keys = []
        self.failed = []

    def mark_sync_started(self, account_key):
        self.started_keys.append(account_key)

    def mark_sync_failed(self, account_key, error):
        self.failed.append((account_key, error))


class SyncFetchTests(unittest.TestCase):
    def test_optional_data_type_error_is_skipped_by_default(self) -> None:
        service = HealthSyncService(
            settings=_settings(strict=False),
            oauth=None,
            health=FakeHealth(),
            storage=None,
        )

        with redirect_stderr(StringIO()):
            records = service._fetch_records("token", date(2026, 6, 1), date(2026, 6, 2))

        self.assertEqual(records, [])

    def test_strict_data_type_error_raises(self) -> None:
        service = HealthSyncService(
            settings=_settings(strict=True),
            oauth=None,
            health=FakeHealth(),
            storage=None,
        )

        with self.assertRaises(HttpError):
            service._fetch_records("token", date(2026, 6, 1), date(2026, 6, 2))

    def test_oauth_failure_marks_sync_failed_by_account_key(self) -> None:
        storage = TrackingStorage()
        service = HealthSyncService(
            settings=_settings(strict=False),
            oauth=FailingOAuth(),
            health=FakeHealth(),
            storage=storage,
        )

        with self.assertRaises(RuntimeError):
            service.sync_recent_days(3)

        self.assertEqual(storage.started_keys, ["personal"])
        self.assertEqual(len(storage.failed), 1)
        self.assertEqual(storage.failed[0][0], "personal")
        self.assertIn("invalid refresh token", storage.failed[0][1])

    def test_sync_refreshes_health_access_token_without_gmail_scope(self) -> None:
        oauth = TrackingOAuth()
        storage = TrackingStorage()
        settings = _settings(strict=False)
        service = HealthSyncService(
            settings=settings,
            oauth=oauth,
            health=FakeHealth(),
            storage=storage,
        )

        with self.assertRaises(RuntimeError):
            service.sync_recent_days(3)

        self.assertEqual(oauth.scopes, [("scope",)])


def _settings(strict: bool) -> Settings:
    return Settings(
        google_client_id="client",
        google_client_secret="secret",
        google_refresh_token="refresh",
        google_scopes=("scope", GMAIL_SEND_SCOPE),
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="key",
        account_key="personal",
        openai_api_key="openai",
        openai_model="gpt-5-mini",
        ai_max_output_tokens=700,
        gmail_from_email="from@example.com",
        summary_recipient_email="to@example.com",
        timezone_name="America/Chicago",
        strict_data_types=strict,
    )


if __name__ == "__main__":
    unittest.main()
