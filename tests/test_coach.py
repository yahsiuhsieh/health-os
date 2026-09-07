from __future__ import annotations

import unittest
from datetime import date

from healthos.coach import assess_report_quality, build_prompt_payload, email_subject, parse_coach_draft, payload_hash


class CoachTests(unittest.TestCase):
    def test_payload_excludes_email_state(self) -> None:
        payload = build_prompt_payload(
            "morning",
            {
                "metric_date": "2026-06-02",
                "sleep_minutes_asleep": 420,
                "morning_email_sent_at": "already",
                "morning_data_hash": "secret",
                "morning_ai_provider": "openrouter",
                "morning_ai_model": "openrouter/free",
                "raw_json": {"should": "not be sent"},
            },
        )

        self.assertEqual(payload["mode"], "morning")
        self.assertNotIn("morning_email_sent_at", payload["metric"])
        self.assertNotIn("morning_data_hash", payload["metric"])
        self.assertNotIn("morning_ai_provider", payload["metric"])
        self.assertNotIn("morning_ai_model", payload["metric"])
        self.assertNotIn("raw_json", payload["metric"])
        self.assertIn("report_quality", payload)
        self.assertEqual(payload_hash(payload), payload_hash(payload))

    def test_short_sleep_is_low_confidence_data(self) -> None:
        quality = assess_report_quality(
            "morning",
            {
                "sleep_minutes_asleep": 84,
                "data_quality": {"has_sleep": True, "has_recovery": False, "has_activity": True},
            },
        )

        self.assertEqual(quality["overall"], "low_confidence")
        self.assertEqual(quality["sleep"]["status"], "low_confidence")
        self.assertEqual(quality["recovery"]["status"], "missing")

    def test_parse_coach_draft_fills_required_quality_cautions(self) -> None:
        payload = build_prompt_payload(
            "morning",
            {
                "metric_date": "2026-09-07",
                "sleep_minutes_asleep": 84,
                "data_quality": {"has_sleep": True, "has_recovery": False, "has_activity": True},
            },
        )

        draft = parse_coach_draft(
            '{"summary":"短睡眠紀錄需保守看待。","signals":["睡眠偏短"],"coach_notes":["先確認資料。"]}',
            payload,
        )

        self.assertEqual(draft.summary, "短睡眠紀錄需保守看待。")
        self.assertIn("少於 180 分鐘", "\n".join(draft.cautions))

    def test_subject_is_mode_specific(self) -> None:
        self.assertEqual(
            email_subject("evening", date(2026, 6, 2)),
            "HealthOS Evening Wrap-Up - 2026-06-02",
        )


if __name__ == "__main__":
    unittest.main()
