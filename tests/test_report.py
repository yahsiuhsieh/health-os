from __future__ import annotations

import unittest
from datetime import date

from healthos.coach import CoachDraft
from healthos.report import render_email_report


class EmailReportTests(unittest.TestCase):
    def test_report_contains_all_morning_sections_dates_and_trends(self) -> None:
        report = render_email_report(
            report_date=date(2026, 9, 7),
            sleep_recovery_row=_sleep_recovery_row(),
            activity_row=_activity_row(),
            draft=_draft(),
        )

        self.assertEqual(report.subject, "HealthOS 晨間健康摘要 - 2026-09-07")
        self.assertIn("<!doctype html>", report.html_body)
        for section in ("今日重點", "昨晚睡眠", "昨日活動", "恢復訊號", "今日建議", "資料品質"):
            self.assertIn(section, report.html_body)
            self.assertIn(section, report.text_body)
        self.assertIn("2026-09-07", report.html_body)
        self.assertIn("2026-09-06", report.html_body)
        self.assertIn("較 7 天平均", report.text_body)
        self.assertIn("較 28 天平均", report.text_body)
        self.assertIn("昨晚睡眠接近近期平均。", report.html_body)
        self.assertIn("本摘要僅供健康管理參考", report.text_body)

    def test_missing_sleep_and_activity_are_visible_in_html_and_text(self) -> None:
        report = render_email_report(
            report_date=date(2026, 9, 7),
            sleep_recovery_row={
                "metric_date": "2026-09-07",
                "data_quality": {"has_sleep": False, "has_recovery": False},
            },
            activity_row={
                "metric_date": "2026-09-06",
                "data_quality": {"has_activity": False},
            },
            draft=CoachDraft(
                summary="今天資料不足。",
                sleep_insight="昨晚沒有睡眠資料。",
                activity_insight="昨天沒有活動資料。",
                recovery_insight="恢復資料不足。",
                today_actions=("以主觀狀態保守安排。",),
                cautions=("沒有取得昨晚的睡眠紀錄。", "沒有取得昨天的活動紀錄。"),
            ),
        )

        self.assertIn("缺資料", report.html_body)
        self.assertIn("缺資料", report.text_body)
        self.assertIn("沒有取得昨晚的睡眠紀錄", report.text_body)
        self.assertIn("沒有取得昨天的活動紀錄", report.text_body)

    def test_provider_metadata_is_not_rendered(self) -> None:
        sleep_row = {
            **_sleep_recovery_row(),
            "morning_ai_provider": "openrouter",
            "morning_ai_model": "google/gemma-free",
        }
        report = render_email_report(
            report_date=date(2026, 9, 7),
            sleep_recovery_row=sleep_row,
            activity_row=_activity_row(),
            draft=_draft(),
        )

        self.assertNotIn("openrouter", report.html_body)
        self.assertNotIn("google/gemma", report.html_body)
        self.assertNotIn("openrouter", report.text_body)


def _draft() -> CoachDraft:
    return CoachDraft(
        summary="今天資料大致可用。",
        sleep_insight="昨晚睡眠接近近期平均。",
        activity_insight="昨天活動量高於近期平均。",
        recovery_insight="恢復訊號維持穩定。",
        today_actions=("先保守起步。",),
        cautions=(),
    )


def _sleep_recovery_row() -> dict:
    return {
        "metric_date": "2026-09-07",
        "sleep_minutes_asleep": 390,
        "sleep_efficiency": 0.923,
        "sleep_minutes_deep": 75,
        "sleep_minutes_rem": 105,
        "hrv_rmssd_ms": 95.2,
        "resting_hr_bpm": 57,
        "respiratory_rate_bpm": 14.8,
        "spo2_avg_pct": 97.1,
        "baseline_7d": {
            "averages": {
                "sleep_minutes_asleep": 380,
                "sleep_efficiency": 0.9,
                "sleep_minutes_deep": 70,
                "sleep_minutes_rem": 100,
                "hrv_rmssd_ms": 90,
                "resting_hr_bpm": 58,
                "respiratory_rate_bpm": 15,
                "spo2_avg_pct": 97,
            }
        },
        "baseline_28d": {
            "averages": {
                "sleep_minutes_asleep": 370,
                "sleep_efficiency": 0.89,
                "sleep_minutes_deep": 68,
                "sleep_minutes_rem": 98,
                "hrv_rmssd_ms": 88,
                "resting_hr_bpm": 59,
                "respiratory_rate_bpm": 15.2,
                "spo2_avg_pct": 96.8,
            }
        },
        "data_quality": {"has_sleep": True, "has_recovery": True, "has_activity": False},
    }


def _activity_row() -> dict:
    return {
        "metric_date": "2026-09-06",
        "steps": 8200,
        "exercise_minutes": 45,
        "active_minutes_total": 75,
        "active_zone_minutes": 38,
        "sedentary_minutes": 540,
        "baseline_7d": {
            "averages": {
                "steps": 7000,
                "exercise_minutes": 35,
                "active_minutes_total": 65,
                "active_zone_minutes": 30,
                "sedentary_minutes": 570,
            }
        },
        "baseline_28d": {
            "averages": {
                "steps": 6800,
                "exercise_minutes": 32,
                "active_minutes_total": 60,
                "active_zone_minutes": 28,
                "sedentary_minutes": 590,
            }
        },
        "data_quality": {"has_sleep": False, "has_recovery": False, "has_activity": True},
    }


if __name__ == "__main__":
    unittest.main()
