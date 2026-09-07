from __future__ import annotations

import unittest
from datetime import date

from healthos.coach import (
    assess_report_quality,
    build_prompt_payload,
    email_subject,
    parse_coach_draft,
    payload_hash,
)


class CoachTests(unittest.TestCase):
    def test_payload_separates_dates_and_excludes_email_state(self) -> None:
        payload = build_prompt_payload(
            date(2026, 9, 7),
            {
                "metric_date": "2026-09-07",
                "sleep_minutes_asleep": 420,
                "steps": 123,
                "morning_email_sent_at": "already",
                "morning_data_hash": "secret",
                "morning_ai_provider": "openrouter",
                "morning_ai_model": "openrouter/free",
                "raw_json": {"should": "not be sent"},
            },
            {
                "metric_date": "2026-09-06",
                "steps": 9000,
                "sleep_minutes_asleep": 300,
                "value_json": {"should": "not be sent"},
            },
        )

        self.assertEqual(payload["report_date"], "2026-09-07")
        self.assertEqual(payload["sleep_recovery"]["metric_date"], "2026-09-07")
        self.assertEqual(payload["previous_day_activity"]["metric_date"], "2026-09-06")
        self.assertNotIn("morning_email_sent_at", payload["sleep_recovery"])
        self.assertNotIn("morning_data_hash", payload["sleep_recovery"])
        self.assertNotIn("morning_ai_provider", payload["sleep_recovery"])
        self.assertNotIn("morning_ai_model", payload["sleep_recovery"])
        self.assertNotIn("raw_json", payload["sleep_recovery"])
        self.assertNotIn("steps", payload["sleep_recovery"])
        self.assertNotIn("value_json", payload["previous_day_activity"])
        self.assertNotIn("sleep_minutes_asleep", payload["previous_day_activity"])
        self.assertIn("report_quality", payload)
        self.assertEqual(payload_hash(payload), payload_hash(payload))

    def test_short_sleep_and_missing_recovery_are_low_confidence(self) -> None:
        quality = assess_report_quality(
            {
                "sleep_minutes_asleep": 84,
                "data_quality": {"has_sleep": True, "has_recovery": False},
            },
            {
                "steps": 9000,
                "data_quality": {"has_activity": True},
            },
        )

        self.assertEqual(quality["overall"], "low_confidence")
        self.assertEqual(quality["sleep"]["status"], "low_confidence")
        self.assertEqual(quality["recovery"]["status"], "missing")
        self.assertEqual(quality["activity"]["status"], "ok")

    def test_parse_coach_draft_fills_sections_and_required_cautions(self) -> None:
        payload = build_prompt_payload(
            date(2026, 9, 7),
            {
                "metric_date": "2026-09-07",
                "sleep_minutes_asleep": 84,
                "data_quality": {"has_sleep": True, "has_recovery": False},
            },
            {
                "metric_date": "2026-09-06",
                "steps": 9000,
                "data_quality": {"has_activity": True},
            },
        )

        draft = parse_coach_draft(
            '{"summary":"短睡眠紀錄需保守看待。","today_actions":["先確認資料。"]}',
            payload,
        )

        self.assertEqual(draft.summary, "短睡眠紀錄需保守看待。")
        self.assertTrue(draft.sleep_insight)
        self.assertTrue(draft.activity_insight)
        self.assertTrue(draft.recovery_insight)
        self.assertEqual(draft.today_actions, ("先確認資料。",))
        self.assertIn("少於 180 分鐘", "\n".join(draft.cautions))

    def test_sleep_interval_without_asleep_minutes_is_partial(self) -> None:
        quality = assess_report_quality(
            {
                "sleep_minutes_total": 480,
                "hrv_rmssd_ms": 90,
                "resting_hr_bpm": 58,
                "respiratory_rate_bpm": 14.5,
                "data_quality": {"has_sleep": True, "has_recovery": True},
            },
            {"steps": 9000, "data_quality": {"has_activity": True}},
        )

        self.assertEqual(quality["overall"], "partial")
        self.assertEqual(quality["sleep"]["status"], "incomplete")

    def test_subject_uses_report_date(self) -> None:
        self.assertEqual(
            email_subject(date(2026, 9, 7)),
            "HealthOS 晨間健康摘要 - 2026-09-07",
        )


if __name__ == "__main__":
    unittest.main()
