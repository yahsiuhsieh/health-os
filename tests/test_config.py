from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from healthos.config import GMAIL_SEND_SCOPE, Settings, load_local_env


class LocalEnvTests(unittest.TestCase):
    def test_loads_local_env_without_overriding_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.local").write_text(
                "\n".join(
                    [
                        "GOOGLE_CLIENT_ID=local-client",
                        "SUPABASE_URL=https://local.supabase.co # local project",
                        "OPENAI_MODEL='gpt-5-mini'",
                    ]
                ),
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "\n".join(
                    [
                        "GOOGLE_CLIENT_ID=env-client",
                        "GOOGLE_CLIENT_SECRET=env-secret",
                    ]
                ),
                encoding="utf-8",
            )

            previous = _stash_env(
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "SUPABASE_URL",
                "OPENAI_MODEL",
            )
            os.environ["GOOGLE_CLIENT_ID"] = "shell-client"
            try:
                load_local_env(root)

                self.assertEqual(os.environ["GOOGLE_CLIENT_ID"], "shell-client")
                self.assertEqual(os.environ["GOOGLE_CLIENT_SECRET"], "env-secret")
                self.assertEqual(os.environ["SUPABASE_URL"], "https://local.supabase.co")
                self.assertEqual(os.environ["OPENAI_MODEL"], "gpt-5-mini")
            finally:
                _restore_env(previous)

    def test_ai_defaults_to_openrouter_free_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous_env = _stash_env(
                "AI_PROVIDER",
                "GOOGLE_HEALTH_SCOPES",
                "GOOGLE_OAUTH_SCOPES",
                "OPENROUTER_MODEL",
                "AI_MAX_OUTPUT_TOKENS",
                "HEALTHOS_ACCOUNT_KEY",
                "SMTP_HOST",
                "HEALTHOS_SEND_DRY_RUN",
            )
            previous_cwd = os.getcwd()
            try:
                os.chdir(directory)
                os.environ["GOOGLE_HEALTH_SCOPES"] = "legacy-scope"
                os.environ["AI_MAX_OUTPUT_TOKENS"] = "9999"
                os.environ["HEALTHOS_ACCOUNT_KEY"] = "other-account"
                os.environ["SMTP_HOST"] = "smtp.example.com"
                os.environ["HEALTHOS_SEND_DRY_RUN"] = "true"
                settings = Settings.from_env()
            finally:
                os.chdir(previous_cwd)
                _restore_env(previous_env)

        self.assertEqual(settings.ai_provider, "openrouter")
        self.assertEqual(settings.openrouter_model, "openrouter/free")
        self.assertEqual(settings.ai_max_output_tokens, 700)
        self.assertEqual(settings.account_key, "personal")
        self.assertIn(GMAIL_SEND_SCOPE, settings.google_scopes)
        self.assertNotIn("legacy-scope", settings.google_scopes)
        self.assertFalse(hasattr(settings, "smtp_host"))
        self.assertFalse(hasattr(settings, "send_dry_run"))

    def test_google_oauth_scopes_append_gmail_send_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous_env = _stash_env(
                "GOOGLE_HEALTH_SCOPES",
                "GOOGLE_OAUTH_SCOPES",
            )
            previous_cwd = os.getcwd()
            try:
                os.chdir(directory)
                os.environ["GOOGLE_OAUTH_SCOPES"] = "scope-a scope-b"
                settings = Settings.from_env()
            finally:
                os.chdir(previous_cwd)
                _restore_env(previous_env)

        self.assertEqual(settings.google_scopes, ("scope-a", "scope-b", GMAIL_SEND_SCOPE))

    def test_gmail_api_email_validation_requires_gmail_settings(self) -> None:
        settings = Settings(
            google_client_id="client",
            google_client_secret="secret",
            google_refresh_token="refresh",
            google_scopes=(GMAIL_SEND_SCOPE,),
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="service-role",
            account_key="personal",
            openai_api_key="openai",
            openai_model="gpt-5-mini",
            ai_max_output_tokens=700,
            gmail_from_email="",
            summary_recipient_email="",
            timezone_name="America/Chicago",
            strict_data_types=False,
        )

        with self.assertRaisesRegex(ValueError, "GMAIL_FROM_EMAIL"):
            settings.validate_email()


def _stash_env(*names: str) -> dict[str, str | None]:
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
