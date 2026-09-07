from __future__ import annotations

import base64
from email.message import EmailMessage

from healthos.config import Settings
from healthos.google_health import GoogleOAuthClient
from healthos.http_client import HttpError, JsonHttpClient


GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class EmailSender:
    def __init__(
        self,
        settings: Settings,
        http: JsonHttpClient | None = None,
        oauth: GoogleOAuthClient | None = None,
    ) -> None:
        self.settings = settings
        self.http = http or JsonHttpClient()
        self.oauth = oauth or GoogleOAuthClient(
            self.http,
            settings.google_client_id,
            settings.google_client_secret,
        )

    def send(self, *, subject: str, body: str, html_body: str | None = None) -> bool:
        message = self._message(subject=subject, body=body, html_body=html_body)
        self._send_gmail_api(message)
        return True

    def _message(self, *, subject: str, body: str, html_body: str | None = None) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.email_from
        message["To"] = self.settings.summary_recipient_email
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
        return message

    def _send_gmail_api(self, message: EmailMessage) -> None:
        token = self.oauth.refresh_access_token(
            self.settings.google_refresh_token,
            scopes=self.settings.gmail_scopes,
        )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        try:
            self.http.request(
                "POST",
                GMAIL_SEND_URL,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json_body={"raw": raw},
            )
        except HttpError as exc:
            if exc.status_code in {401, 403}:
                raise RuntimeError(
                    "Gmail API send failed. Re-run auth-local after adding the gmail.send scope "
                    "and replace GOOGLE_REFRESH_TOKEN with the new refresh token."
                ) from exc
            raise
