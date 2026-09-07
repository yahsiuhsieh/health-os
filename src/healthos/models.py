from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from healthos.utils import iso_or_none, parse_datetime, stable_hash


@dataclass
class Account:
    id: str
    account_key: str
    google_health_user_id: str | None = None
    google_legacy_user_id: str | None = None


@dataclass
class HealthRecord:
    data_type: str
    source_record_id: str
    value_json: dict[str, Any]
    raw_json: dict[str, Any]
    metric_date: date | None = None
    observed_start_at: datetime | None = None
    observed_end_at: datetime | None = None

    @property
    def source_record_hash(self) -> str:
        return stable_hash(
            {
                "data_type": self.data_type,
                "source_record_id": self.source_record_id,
                "value_json": self.value_json,
                "raw_json": self.raw_json,
            }
        )

    def to_row(self, account_id: str) -> dict[str, Any]:
        return {
            "account_id": account_id,
            "data_type": self.data_type,
            "source_record_id": self.source_record_id,
            "source_record_hash": self.source_record_hash,
            "metric_date": self.metric_date.isoformat() if self.metric_date else None,
            "observed_start_at": iso_or_none(self.observed_start_at),
            "observed_end_at": iso_or_none(self.observed_end_at),
            "value_json": self.value_json,
            "raw_json": self.raw_json,
        }


@dataclass
class DailyMetric:
    metric_date: date
    sleep_start_at: datetime | None = None
    sleep_end_at: datetime | None = None
    sleep_minutes_total: float | None = None
    sleep_minutes_asleep: float | None = None
    sleep_minutes_awake: float | None = None
    sleep_minutes_light: float | None = None
    sleep_minutes_deep: float | None = None
    sleep_minutes_rem: float | None = None
    sleep_efficiency: float | None = None
    hrv_rmssd_ms: float | None = None
    resting_hr_bpm: float | None = None
    respiratory_rate_bpm: float | None = None
    spo2_avg_pct: float | None = None
    sleep_temp_delta_c: float | None = None
    vo2_max: float | None = None
    weight_kg: float | None = None
    steps: int | None = None
    active_zone_minutes: float | None = None
    active_minutes_total: float | None = None
    active_minutes_light: float | None = None
    active_minutes_moderate: float | None = None
    active_minutes_vigorous: float | None = None
    exercise_minutes: float | None = None
    sedentary_minutes: float | None = None
    readiness_score: float | None = None
    strain_score: float | None = None
    data_quality: dict[str, Any] = field(default_factory=dict)
    baseline_7d: dict[str, Any] = field(default_factory=dict)
    baseline_28d: dict[str, Any] = field(default_factory=dict)

    def to_row(self, account_id: str) -> dict[str, Any]:
        result = {
            "account_id": account_id,
            "metric_date": self.metric_date.isoformat(),
            "sleep_start_at": iso_or_none(self.sleep_start_at),
            "sleep_end_at": iso_or_none(self.sleep_end_at),
            "sleep_minutes_total": self.sleep_minutes_total,
            "sleep_minutes_asleep": self.sleep_minutes_asleep,
            "sleep_minutes_awake": self.sleep_minutes_awake,
            "sleep_minutes_light": self.sleep_minutes_light,
            "sleep_minutes_deep": self.sleep_minutes_deep,
            "sleep_minutes_rem": self.sleep_minutes_rem,
            "sleep_efficiency": self.sleep_efficiency,
            "hrv_rmssd_ms": self.hrv_rmssd_ms,
            "resting_hr_bpm": self.resting_hr_bpm,
            "respiratory_rate_bpm": self.respiratory_rate_bpm,
            "spo2_avg_pct": self.spo2_avg_pct,
            "sleep_temp_delta_c": self.sleep_temp_delta_c,
            "vo2_max": self.vo2_max,
            "weight_kg": self.weight_kg,
            "steps": self.steps,
            "active_zone_minutes": self.active_zone_minutes,
            "active_minutes_total": self.active_minutes_total,
            "active_minutes_light": self.active_minutes_light,
            "active_minutes_moderate": self.active_minutes_moderate,
            "active_minutes_vigorous": self.active_minutes_vigorous,
            "exercise_minutes": self.exercise_minutes,
            "sedentary_minutes": self.sedentary_minutes,
            "readiness_score": self.readiness_score,
            "strain_score": self.strain_score,
            "data_quality": self.data_quality,
            "baseline_7d": self.baseline_7d,
            "baseline_28d": self.baseline_28d,
        }
        return result

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "DailyMetric":
        parsed_date = date.fromisoformat(str(row["metric_date"]))
        metric = cls(metric_date=parsed_date)
        datetime_fields = {"sleep_start_at", "sleep_end_at"}
        for key in cls.__dataclass_fields__:
            if key == "metric_date" or key not in row:
                continue
            value = row[key]
            if key in datetime_fields and isinstance(value, str):
                value = parse_datetime(value)
            setattr(metric, key, value)
        return metric
