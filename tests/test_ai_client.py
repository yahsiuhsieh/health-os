from __future__ import annotations

import json
import unittest

from healthos.coach import COACH_INSTRUCTIONS, build_prompt_payload
from healthos.config import Settings
from healthos.http_client import HttpError
from healthos.openai_client import AIClient


class AIClientTests(unittest.TestCase):
    def test_openrouter_uses_default_free_model_and_parses_structured_response(self) -> None:
        http = FakeHttp(_openrouter_response())
        client = AIClient(_settings(ai_provider="openrouter"), http)

        result = client.generate_draft(_payload(), instructions=COACH_INSTRUCTIONS)

        self.assertEqual(result.draft.summary, "恢復資料可用，今天維持穩定節奏。")
        self.assertEqual(result.draft.coach_notes, ("先保守起步。",))
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "openrouter/free")
        self.assertEqual(http.calls[0]["method"], "POST")
        self.assertEqual(http.calls[0]["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(http.calls[0]["json_body"]["model"], "openrouter/free")
        self.assertIn("report_quality", http.calls[0]["json_body"]["messages"][1]["content"])

    def test_openrouter_error_falls_back_to_rule_based_draft(self) -> None:
        http = FakeHttp(error=HttpError(429, "rate limited", "https://openrouter.ai"))
        client = AIClient(_settings(ai_provider="openrouter"), http)

        result = client.generate_draft(_payload(), instructions=COACH_INSTRUCTIONS)

        self.assertEqual(result.provider, "rule_based")
        self.assertEqual(result.model, "rule-based")
        self.assertIn("資料", result.draft.summary)
        self.assertGreaterEqual(len(result.draft.coach_notes), 1)

    def test_openrouter_invalid_json_falls_back_to_rule_based_draft(self) -> None:
        http = FakeHttp({"choices": [{"message": {"content": "not json"}}]})
        client = AIClient(_settings(ai_provider="openrouter"), http)

        result = client.generate_draft(_payload(), instructions=COACH_INSTRUCTIONS)

        self.assertEqual(result.provider, "rule_based")
        self.assertGreaterEqual(len(result.draft.signals), 1)

    def test_rule_based_provider_does_not_require_api_key_or_http(self) -> None:
        http = FakeHttp(_openrouter_response())
        client = AIClient(_settings(ai_provider="rule_based", openrouter_api_key="", openai_api_key=""), http)

        result = client.generate_draft(_payload(), instructions=COACH_INSTRUCTIONS)

        self.assertEqual(result.provider, "rule_based")
        self.assertEqual(http.calls, [])
        self.assertGreaterEqual(len(result.draft.coach_notes), 1)

    def test_openai_provider_keeps_responses_api_and_parses_structured_response(self) -> None:
        http = FakeHttp(
            {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": _draft_json(summary="OpenAI summary"),
                            }
                        ]
                    }
                ]
            }
        )
        client = AIClient(_settings(ai_provider="openai"), http)

        result = client.generate_draft(_payload(), instructions=COACH_INSTRUCTIONS)

        self.assertEqual(result.draft.summary, "OpenAI summary")
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.model, "gpt-5-mini")
        self.assertEqual(http.calls[0]["url"], "https://api.openai.com/v1/responses")
        self.assertFalse(http.calls[0]["json_body"]["store"])

class FakeHttp:
    def __init__(self, response=None, *, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error:
            raise self.error
        return self.response


def _openrouter_response() -> dict:
    return {"choices": [{"message": {"content": _draft_json()}}]}


def _draft_json(*, summary: str = "恢復資料可用，今天維持穩定節奏。") -> str:
    return json.dumps(
        {
            "summary": summary,
            "signals": ["睡眠接近近期平均。"],
            "coach_notes": ["先保守起步。"],
            "cautions": [],
        },
        ensure_ascii=False,
    )


def _payload() -> dict:
    return build_prompt_payload(
        "morning",
        {
            "metric_date": "2026-09-06",
            "sleep_minutes_asleep": 390,
            "sleep_efficiency": 0.91,
            "resting_hr_bpm": 57,
            "hrv_rmssd_ms": 104.4,
            "respiratory_rate_bpm": 14.2,
            "baseline_7d": {
                "averages": {
                    "sleep_minutes_asleep": 420,
                    "resting_hr_bpm": 59,
                    "hrv_rmssd_ms": 91.3,
                }
            },
            "data_quality": {
                "has_sleep": True,
                "has_recovery": True,
                "has_activity": True,
                "partial_day": False,
            },
        },
    )


def _settings(
    *,
    ai_provider: str,
    openrouter_api_key: str = "openrouter-key",
    openai_api_key: str = "openai-key",
) -> Settings:
    return Settings(
        google_client_id="client",
        google_client_secret="secret",
        google_refresh_token="refresh",
        google_scopes=("scope",),
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        account_key="personal",
        openai_api_key=openai_api_key,
        openai_model="gpt-5-mini",
        ai_max_output_tokens=700,
        gmail_from_email="from@example.com",
        summary_recipient_email="to@example.com",
        timezone_name="America/Chicago",
        strict_data_types=False,
        ai_provider=ai_provider,
        openrouter_api_key=openrouter_api_key,
        openrouter_model="openrouter/free",
    )


if __name__ == "__main__":
    unittest.main()
