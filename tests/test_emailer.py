from __future__ import annotations

import base64
import unittest
from email import policy
from email.parser import BytesParser

from healthos.config import GMAIL_SEND_SCOPE, Settings
from healthos.emailer import EmailSender, GMAIL_SEND_URL
from healthos.google_health import TokenResponse


class EmailSenderTests(unittest.TestCase):
    def test_send_uses_gmail_api_with_base64url_mime_message(self) -> None:
        http = FakeHttp()
        oauth = FakeOAuth()
        settings = _settings()

        delivered = EmailSender(settings, http=http, oauth=oauth).send(
            subject="HealthOS 晨間健康摘要 - 2026-09-07",
            body="plain body",
            html_body="<html><body>html body</body></html>",
        )

        self.assertTrue(delivered)
        self.assertEqual(oauth.refresh_tokens, ["refresh"])
        self.assertEqual(oauth.scopes, [(GMAIL_SEND_SCOPE,)])
        self.assertEqual(len(http.calls), 1)
        call = http.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], GMAIL_SEND_URL)
        self.assertEqual(call["headers"]["Authorization"], "Bearer access-token")

        raw = call["json_body"]["raw"]
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
        self.assertTrue(message.is_multipart())
        self.assertEqual(message["From"], "from@example.com")
        self.assertEqual(message["To"], "to@example.com")
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().strip(), "plain body")
        self.assertEqual(
            message.get_body(preferencelist=("html",)).get_content().strip(),
            "<html><body>html body</body></html>",
        )


class FakeHttp:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return {"id": "gmail-message-id"}


class FakeOAuth:
    def __init__(self) -> None:
        self.refresh_tokens = []
        self.scopes = []

    def refresh_access_token(self, refresh_token, scopes=None):
        self.refresh_tokens.append(refresh_token)
        self.scopes.append(scopes)
        return TokenResponse(access_token="access-token")


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
    )


if __name__ == "__main__":
    unittest.main()
