from __future__ import annotations

import unittest
from datetime import date

from healthos.coach import CoachDraft
from healthos.report import render_email_report


class EmailReportTests(unittest.TestCase):
    def test_render_report_outputs_html_and_plain_text(self) -> None:
        report = render_email_report(
            mode="morning",
            metric_date=date(2026, 9, 7),
            metric_row=_metric_row(sleep_minutes=390),
            draft=CoachDraft(
                summary="今天資料大致可用。",
                signals=("睡眠接近近期平均。",),
                coach_notes=("先保守起步。",),
                cautions=(),
            ),
        )

        self.assertEqual(report.subject, "HealthOS Morning Recovery - 2026-09-07")
        self.assertIn("<!doctype html>", report.html_body)
        self.assertIn("Top insight", report.html_body)
        self.assertIn("Key metrics", report.html_body)
        self.assertIn("Coach notes", report.html_body)
        self.assertIn("Data quality", report.html_body)
        self.assertIn("今天資料大致可用。", report.text_body)
        self.assertIn("睡眠接近近期平均。", report.html_body)
        self.assertIn("Signals", report.text_body)
        self.assertIn("This is not medical advice.", report.text_body)

    def test_low_confidence_sleep_is_visible_in_html_and_text(self) -> None:
        report = render_email_report(
            mode="morning",
            metric_date=date(2026, 9, 7),
            metric_row=_metric_row(sleep_minutes=84, recovery=False),
            draft=CoachDraft(
                summary="今天睡眠資料看起來不完整，恢復指標也不足。",
                signals=("睡眠只有 84 分鐘。",),
                coach_notes=("先確認資料。",),
                cautions=("睡眠少於 180 分鐘，可能是同步或穿戴紀錄不完整。",),
            ),
        )

        self.assertIn("低信心", report.html_body)
        self.assertIn("低信心", report.text_body)
        self.assertIn("睡眠少於 180 分鐘", report.text_body)
        self.assertIn("恢復: 缺資料", report.text_body)

    def test_provider_metadata_is_not_rendered_in_customer_facing_email(self) -> None:
        report = render_email_report(
            mode="morning",
            metric_date=date(2026, 9, 7),
            metric_row={
                **_metric_row(sleep_minutes=390),
                "morning_ai_provider": "openrouter",
                "morning_ai_model": "google/gemma-4-31b-it:free",
            },
            draft=CoachDraft(
                summary="今天資料大致可用。",
                signals=("睡眠接近近期平均。",),
                coach_notes=("先保守起步。",),
                cautions=(),
            ),
        )

        self.assertNotIn("openrouter", report.html_body)
        self.assertNotIn("google/gemma", report.html_body)
        self.assertNotIn("openrouter", report.text_body)


def _metric_row(*, sleep_minutes: int, recovery: bool = True) -> dict:
    row = {
        "metric_date": "2026-09-07",
        "sleep_minutes_asleep": sleep_minutes,
        "sleep_efficiency": 0.923,
        "steps": 3200,
        "active_minutes_total": 45,
        "baseline_7d": {
            "averages": {
                "sleep_minutes_asleep": 329,
                "steps": 3000,
                "hrv_rmssd_ms": 90,
                "resting_hr_bpm": 58,
            }
        },
        "data_quality": {"has_sleep": True, "has_recovery": recovery, "has_activity": True},
    }
    if recovery:
        row.update({"hrv_rmssd_ms": 95.2, "resting_hr_bpm": 57, "respiratory_rate_bpm": 14.8})
    return row


if __name__ == "__main__":
    unittest.main()
