from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from healthos.models import HealthRecord
from healthos.rollup import RollupBuilder, attach_baselines


class RollupTests(unittest.TestCase):
    def test_builds_sleep_recovery_and_activity_metric(self) -> None:
        metric_date = date(2026, 6, 2)
        records = [
            HealthRecord(
                data_type="sleep",
                source_record_id="sleep-1",
                metric_date=metric_date,
                observed_start_at=datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc),
                observed_end_at=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
                value_json={
                    "summary": {
                        "minutesAsleep": 420,
                        "minutesAwake": 60,
                        "stageSummary": [
                            {"stage": "LIGHT", "minutes": 240},
                            {"stage": "DEEP", "minutes": 90},
                            {"stage": "REM", "minutes": 90},
                        ],
                    }
                },
                raw_json={},
            ),
            HealthRecord(
                data_type="daily-heart-rate-variability",
                source_record_id="hrv-1",
                metric_date=metric_date,
                value_json={"averageHeartRateVariabilityMilliseconds": 48},
                raw_json={},
            ),
            HealthRecord(
                data_type="daily-resting-heart-rate",
                source_record_id="rhr-1",
                metric_date=metric_date,
                value_json={"beatsPerMinute": 58},
                raw_json={},
            ),
            HealthRecord(
                data_type="steps",
                source_record_id="steps-1",
                metric_date=metric_date,
                value_json={"countSum": "8400"},
                raw_json={},
            ),
            HealthRecord(
                data_type="exercise",
                source_record_id="exercise-1",
                metric_date=metric_date,
                observed_start_at=datetime(2026, 6, 2, 22, 0, tzinfo=timezone.utc),
                observed_end_at=datetime(2026, 6, 2, 22, 45, tzinfo=timezone.utc),
                value_json={"metricsSummary": {}},
                raw_json={},
            ),
        ]

        metric = RollupBuilder().build_for_dates(records, [metric_date])[0]

        self.assertEqual(metric.sleep_minutes_asleep, 420)
        self.assertEqual(metric.sleep_minutes_deep, 90)
        self.assertEqual(metric.hrv_rmssd_ms, 48)
        self.assertEqual(metric.resting_hr_bpm, 58)
        self.assertEqual(metric.steps, 8400)
        self.assertEqual(metric.exercise_minutes, 45)
        self.assertAlmostEqual(metric.sleep_efficiency or 0, 0.875)

    def test_attach_baselines_uses_prior_days_only(self) -> None:
        metric_date = date(2026, 6, 10)
        metric = RollupBuilder().build_for_dates([], [metric_date])[0]
        history = [
            {"metric_date": "2026-06-09", "steps": 10000, "sleep_minutes_asleep": 400},
            {"metric_date": "2026-06-10", "steps": 50000, "sleep_minutes_asleep": 100},
        ]

        attach_baselines(metric, history)

        self.assertEqual(metric.baseline_7d["sample_count"], 1)
        self.assertEqual(metric.baseline_7d["averages"]["steps"], 10000)

    def test_google_sleep_stage_and_weight_shapes_roll_up(self) -> None:
        metric_date = date(2026, 8, 9)
        records = [
            HealthRecord(
                data_type="sleep",
                source_record_id="sleep-1",
                metric_date=metric_date,
                observed_start_at=datetime(2026, 8, 9, 5, 26, tzinfo=timezone.utc),
                observed_end_at=datetime(2026, 8, 9, 14, 16, tzinfo=timezone.utc),
                value_json={
                    "summary": {
                        "minutesAsleep": 420,
                        "minutesAwake": 50,
                        "stagesSummary": [
                            {"type": "LIGHT", "minutes": 210},
                            {"type": "DEEP", "minutes": 95},
                            {"type": "REM", "minutes": 115},
                        ],
                    }
                },
                raw_json={},
            ),
            HealthRecord(
                data_type="weight",
                source_record_id="weight-1",
                metric_date=metric_date,
                value_json={"weightGrams": 72500},
                raw_json={},
            ),
        ]

        metric = RollupBuilder().build_for_dates(records, [metric_date])[0]

        self.assertEqual(metric.sleep_minutes_light, 210)
        self.assertEqual(metric.sleep_minutes_deep, 95)
        self.assertEqual(metric.sleep_minutes_rem, 115)
        self.assertEqual(metric.weight_kg, 72.5)

    def test_google_active_zone_rollup_shape_rolls_up(self) -> None:
        metric_date = date(2026, 8, 9)
        records = [
            HealthRecord(
                data_type="active-zone-minutes",
                source_record_id="azm-1",
                metric_date=metric_date,
                value_json={
                    "sumInPeakHeartZone": "30",
                    "sumInCardioHeartZone": "116",
                    "sumInFatBurnHeartZone": "31",
                },
                raw_json={},
            )
        ]

        metric = RollupBuilder().build_for_dates(records, [metric_date])[0]

        self.assertEqual(metric.active_zone_minutes, 177)

    def test_missing_sleep_marks_data_quality_without_score(self) -> None:
        metric_date = date(2026, 6, 2)

        metric = RollupBuilder().build_for_dates([], [metric_date])[0]

        self.assertFalse(metric.data_quality["has_sleep"])
        self.assertIsNone(metric.readiness_score)

    def test_partial_day_rollup_sets_as_of(self) -> None:
        metric_date = date(2026, 6, 2)
        as_of = datetime(2026, 6, 2, 21, 30, tzinfo=timezone.utc)

        metric = RollupBuilder().build_for_dates([], [metric_date], partial_day_as_of=as_of)[0]

        self.assertEqual(metric.partial_day_as_of, as_of)
        self.assertTrue(metric.data_quality["partial_day"])


if __name__ == "__main__":
    unittest.main()
