from __future__ import annotations

import unittest
from datetime import date

from healthos.config import Settings
from healthos.storage import SupabaseStorage


class SupabaseStorageTests(unittest.TestCase):
    def test_delete_health_records_before_only_targets_raw_records(self) -> None:
        http = FakeHttp([{"id": "record-1"}, {"id": "record-2"}])
        storage = SupabaseStorage(_settings(), http)

        deleted = storage.delete_health_records_before("account-id", date(2026, 8, 8))

        self.assertEqual(deleted, 2)
        call = http.calls[0]
        self.assertEqual(call["method"], "DELETE")
        self.assertIn("/rest/v1/health_records?", call["url"])
        self.assertIn("account_id=eq.account-id", call["url"])
        self.assertIn("metric_date=lt.2026-08-08", call["url"])
        self.assertEqual(call["headers"]["Prefer"], "return=representation")

    def test_mark_morning_email_sent_records_ai_provider_and_model(self) -> None:
        http = FakeHttp({})
        storage = SupabaseStorage(_settings(), http)

        storage.mark_morning_email_sent(
            "account-id",
            date(2026, 9, 6),
            "hash",
            ai_provider="openrouter",
            ai_model="openrouter/free",
        )

        body = http.calls[0]["json_body"]
        self.assertEqual(body["morning_data_hash"], "hash")
        self.assertEqual(body["morning_ai_provider"], "openrouter")
        self.assertEqual(body["morning_ai_model"], "openrouter/free")


class FakeHttp:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def _settings() -> Settings:
    return Settings(
        google_client_id="client",
        google_client_secret="secret",
        google_refresh_token="refresh",
        google_scopes=("scope",),
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
    )


if __name__ == "__main__":
    unittest.main()
