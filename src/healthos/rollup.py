from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from statistics import mean
from typing import Any

from healthos.models import DailyMetric, HealthRecord
from healthos.utils import first_number, minutes_between, number, recursive_numeric_sum


BASELINE_FIELDS = (
    "sleep_minutes_asleep",
    "sleep_efficiency",
    "hrv_rmssd_ms",
    "resting_hr_bpm",
    "respiratory_rate_bpm",
    "spo2_avg_pct",
    "steps",
    "active_zone_minutes",
    "exercise_minutes",
    "sedentary_minutes",
)


class RollupBuilder:
    def build_for_dates(
        self,
        records: list[HealthRecord],
        dates: list[date],
        *,
        partial_day_as_of: datetime | None = None,
    ) -> list[DailyMetric]:
        by_date: dict[date, list[HealthRecord]] = defaultdict(list)
        for record in records:
            if record.metric_date:
                by_date[record.metric_date].append(record)

        metrics = []
        for metric_date in dates:
            metric = DailyMetric(metric_date=metric_date)
            for record in by_date.get(metric_date, []):
                self.apply_record(metric, record)
            if partial_day_as_of and metric_date == partial_day_as_of.date():
                metric.partial_day_as_of = partial_day_as_of
            metric.data_quality = self.data_quality(metric)
            metric.readiness_score = self.readiness_score(metric)
            metric.strain_score = self.strain_score(metric)
            metrics.append(metric)
        return metrics

    def apply_record(self, metric: DailyMetric, record: HealthRecord) -> None:
        value = record.value_json
        if record.data_type == "sleep":
            self._apply_sleep(metric, value, record)
        elif record.data_type == "daily-heart-rate-variability":
            metric.hrv_rmssd_ms = first_number(
                value,
                (
                    "averageHeartRateVariabilityMilliseconds",
                    "rmssdMilliseconds",
                    "heartRateVariabilityMilliseconds",
                    "value",
                ),
            )
        elif record.data_type == "daily-resting-heart-rate":
            metric.resting_hr_bpm = first_number(
                value,
                ("beatsPerMinute", "restingHeartRateBpm", "bpm", "value"),
            )
        elif record.data_type == "daily-respiratory-rate":
            metric.respiratory_rate_bpm = first_number(
                value,
                ("breathsPerMinute", "respiratoryRate", "value"),
            )
        elif record.data_type == "daily-oxygen-saturation":
            metric.spo2_avg_pct = first_number(
                value,
                ("averageOxygenSaturationPercentage", "oxygenSaturationPercentage", "percentage", "value"),
            )
        elif record.data_type == "daily-sleep-temperature-derivations":
            metric.sleep_temp_delta_c = first_number(
                value,
                ("temperatureDeltaCelsius", "deltaCelsius", "skinTemperatureDeltaCelsius", "value"),
            )
        elif record.data_type == "daily-vo2-max":
            metric.vo2_max = first_number(value, ("vo2Max", "value"))
        elif record.data_type == "weight":
            metric.weight_kg = _weight_kg(value)
        elif record.data_type == "steps":
            steps = first_number(value, ("countSum", "count_sum", "count", "value"))
            if steps is not None:
                metric.steps = int(round(steps))
        elif record.data_type == "active-zone-minutes":
            metric.active_zone_minutes = _active_zone_minutes(value)
        elif record.data_type == "active-minutes":
            self._apply_active_minutes(metric, value)
        elif record.data_type == "sedentary-period":
            metric.sedentary_minutes = _duration_minutes(value) or _sum_minutes(value)
        elif record.data_type == "exercise":
            exercise_minutes = self._exercise_minutes(value, record)
            if exercise_minutes is not None:
                metric.exercise_minutes = (metric.exercise_minutes or 0) + exercise_minutes

    def _apply_sleep(self, metric: DailyMetric, value: dict[str, Any], record: HealthRecord) -> None:
        interval = value.get("interval") or {}
        if record.observed_start_at:
            metric.sleep_start_at = record.observed_start_at
        if record.observed_end_at:
            metric.sleep_end_at = record.observed_end_at
        if metric.sleep_minutes_total is None:
            metric.sleep_minutes_total = minutes_between(record.observed_start_at, record.observed_end_at)

        summary = value.get("summary") or value.get("sleepSummary") or {}
        metric.sleep_minutes_asleep = first_number(
            summary,
            ("minutesAsleep", "asleepMinutes", "sleepMinutes", "totalMinutesAsleep"),
        )
        metric.sleep_minutes_awake = first_number(
            summary,
            ("minutesAwake", "awakeMinutes", "wakeMinutes", "totalMinutesAwake"),
        )
        metric.sleep_minutes_light = _stage_minutes(summary, ("LIGHT", "light"))
        metric.sleep_minutes_deep = _stage_minutes(summary, ("DEEP", "deep"))
        metric.sleep_minutes_rem = _stage_minutes(summary, ("REM", "rem"))

        if metric.sleep_minutes_asleep is None:
            stage_total = sum(
                value
                for value in (
                    metric.sleep_minutes_light,
                    metric.sleep_minutes_deep,
                    metric.sleep_minutes_rem,
                )
                if value is not None
            )
            metric.sleep_minutes_asleep = stage_total or None
        if metric.sleep_minutes_total is None:
            metric.sleep_minutes_total = first_number(summary, ("timeInBedMinutes", "totalMinutes"))
        if metric.sleep_minutes_total and metric.sleep_minutes_asleep is not None:
            metric.sleep_efficiency = round(metric.sleep_minutes_asleep / metric.sleep_minutes_total, 4)
        if not metric.sleep_start_at:
            metric.sleep_start_at = _parse_interval_datetime(interval, "startTime")
        if not metric.sleep_end_at:
            metric.sleep_end_at = _parse_interval_datetime(interval, "endTime")

    def _apply_active_minutes(self, metric: DailyMetric, value: dict[str, Any]) -> None:
        metric.active_minutes_total = _sum_minutes(value)
        metric.active_minutes_light = _sum_keys(value, ("light", "LIGHT"))
        metric.active_minutes_moderate = _sum_keys(value, ("moderate", "MODERATE"))
        metric.active_minutes_vigorous = _sum_keys(value, ("vigorous", "VIGOROUS"))

    def _exercise_minutes(self, value: dict[str, Any], record: HealthRecord) -> float | None:
        summary = value.get("metricsSummary") or value.get("summary") or {}
        explicit = first_number(
            summary,
            (
                "activeDurationSeconds",
                "activeDuration",
                "durationSeconds",
                "duration",
                "activeMinutes",
            ),
        )
        if explicit is not None:
            if explicit > 1000:
                return explicit / 60.0
            return explicit
        return minutes_between(record.observed_start_at, record.observed_end_at)

    def data_quality(self, metric: DailyMetric) -> dict[str, Any]:
        return {
            "has_sleep": metric.sleep_minutes_asleep is not None or metric.sleep_minutes_total is not None,
            "has_recovery": any(
                value is not None
                for value in (
                    metric.hrv_rmssd_ms,
                    metric.resting_hr_bpm,
                    metric.respiratory_rate_bpm,
                    metric.spo2_avg_pct,
                )
            ),
            "has_activity": any(
                value is not None
                for value in (
                    metric.steps,
                    metric.active_zone_minutes,
                    metric.active_minutes_total,
                    metric.exercise_minutes,
                )
            ),
            "partial_day": metric.partial_day_as_of is not None,
        }

    def readiness_score(self, metric: DailyMetric) -> float | None:
        score = 70.0
        if metric.sleep_minutes_asleep is not None:
            if metric.sleep_minutes_asleep >= 420:
                score += 10
            elif metric.sleep_minutes_asleep < 360:
                score -= 15
        if metric.sleep_efficiency is not None:
            if metric.sleep_efficiency >= 0.88:
                score += 5
            elif metric.sleep_efficiency < 0.80:
                score -= 10
        if metric.hrv_rmssd_ms is not None and metric.hrv_rmssd_ms > 0:
            score += 5
        if metric.resting_hr_bpm is not None and metric.resting_hr_bpm > 75:
            score -= 5
        if not metric.data_quality.get("has_sleep"):
            return None
        return max(0.0, min(100.0, round(score, 1)))

    def strain_score(self, metric: DailyMetric) -> float | None:
        if not metric.data_quality.get("has_activity"):
            return None
        score = 0.0
        score += min((metric.steps or 0) / 1000.0, 10)
        score += min((metric.active_zone_minutes or 0) / 5.0, 10)
        score += min((metric.exercise_minutes or 0) / 10.0, 8)
        return max(0.0, min(100.0, round(score * 4, 1)))


def compute_baseline(metric_date: date, rows: list[dict[str, Any]], days: int) -> dict[str, Any]:
    start_ordinal = metric_date.toordinal() - days
    end_ordinal = metric_date.toordinal() - 1
    included = [
        row
        for row in rows
        if start_ordinal <= date.fromisoformat(str(row["metric_date"])).toordinal() <= end_ordinal
    ]
    result: dict[str, Any] = {"sample_count": len(included), "days": days, "averages": {}}
    for field in BASELINE_FIELDS:
        values = [number(row.get(field)) for row in included]
        clean = [value for value in values if value is not None]
        if clean:
            result["averages"][field] = round(mean(clean), 3)
    return result


def attach_baselines(metric: DailyMetric, history_rows: list[dict[str, Any]]) -> DailyMetric:
    metric.baseline_7d = compute_baseline(metric.metric_date, history_rows, 7)
    metric.baseline_28d = compute_baseline(metric.metric_date, history_rows, 28)
    return metric


def should_send_email(row: dict[str, Any] | None, mode: str, data_hash: str, *, force: bool = False) -> bool:
    if force:
        return True
    if not row:
        return True
    sent_at = row.get(f"{mode}_email_sent_at")
    sent_hash = row.get(f"{mode}_data_hash")
    if sent_at and sent_hash == data_hash:
        return False
    if sent_at:
        return False
    return True


def _stage_minutes(summary: dict[str, Any], names: tuple[str, ...]) -> float | None:
    stage_summaries = (
        summary.get("stageSummary")
        or summary.get("stageSummaries")
        or summary.get("stagesSummary")
        or []
    )
    if isinstance(stage_summaries, dict):
        stage_summaries = list(stage_summaries.values())
    for stage in stage_summaries:
        if not isinstance(stage, dict):
            continue
        stage_type = str(stage.get("stage") or stage.get("type") or stage.get("sleepStageType") or "")
        if any(name.lower() in stage_type.lower() for name in names):
            minutes = first_number(stage, ("minutes", "durationMinutes", "totalMinutes"))
            if minutes is not None:
                return minutes
            seconds = first_number(stage, ("durationSeconds", "duration"))
            if seconds is not None:
                return seconds / 60.0
    for name in names:
        direct = first_number(summary, (f"{name.lower()}Minutes", f"minutes{name.title()}"))
        if direct is not None:
            return direct
    return None


def _weight_kg(value: dict[str, Any]) -> float | None:
    kilograms = first_number(value, ("weight.kilograms", "kilograms", "value"))
    if kilograms is not None:
        return kilograms
    grams = first_number(value, ("weightGrams", "grams"))
    if grams is None:
        return None
    return round(grams / 1000.0, 3)


def _sum_minutes(value: dict[str, Any]) -> float | None:
    total = recursive_numeric_sum(value, r"(minutes|minute).*?(sum|total)?$")
    if total:
        return round(total, 3)
    seconds = recursive_numeric_sum(value, r"(seconds|duration).*?(sum|total)?$")
    if seconds:
        return round(seconds / 60.0, 3)
    return None


def _active_zone_minutes(value: dict[str, Any]) -> float | None:
    zone_total = recursive_numeric_sum(value, r"^sumIn.*HeartZone$")
    if zone_total:
        return round(zone_total, 3)
    return _sum_minutes(value)


def _duration_minutes(value: dict[str, Any]) -> float | None:
    explicit = first_number(value, ("durationMinutes", "minutes", "durationSeconds", "duration"))
    if explicit is None:
        return None
    if explicit > 1000:
        return explicit / 60.0
    return explicit


def _sum_keys(value: Any, keys: tuple[str, ...]) -> float | None:
    total = 0.0
    if isinstance(value, dict):
        for key, item in value.items():
            if any(target.lower() in key.lower() for target in keys):
                direct = number(item)
                if direct is not None:
                    total += direct
                elif isinstance(item, dict):
                    nested = _sum_minutes(item)
                    total += nested or 0
            nested = _sum_keys(item, keys)
            total += nested or 0
    elif isinstance(value, list):
        for item in value:
            nested = _sum_keys(item, keys)
            total += nested or 0
    return round(total, 3) if total else None


def _parse_interval_datetime(interval: dict[str, Any], key: str) -> datetime | None:
    from healthos.utils import parse_datetime

    return parse_datetime(interval.get(key))
