from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_date_range(days: int, tz: ZoneInfo) -> tuple[date, date]:
    today = datetime.now(tz).date()
    return today.fromordinal(today.toordinal() - days + 1), today.fromordinal(today.toordinal() + 1)


def parse_google_date(value: dict[str, Any] | None) -> date | None:
    if not value:
        return None
    year = value.get("year")
    month = value.get("month")
    day = value.get("day")
    if not year or not month or not day:
        return None
    return date(int(year), int(month), int(day))


def google_date(value: date) -> dict[str, int]:
    return {"year": value.year, "month": value.month, "day": value.day}


def google_civil_datetime(value: date, at: time | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"date": google_date(value)}
    if at is not None:
        result["time"] = {
            "hours": at.hour,
            "minutes": at.minute,
            "seconds": at.second,
            "nanos": at.microsecond * 1000,
        }
    return result


def civil_datetime_to_date(value: dict[str, Any] | None) -> date | None:
    if not value:
        return None
    return parse_google_date(value.get("date"))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def first_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _deep_get(payload, key)
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def _deep_get(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def recursive_numeric_sum(payload: Any, key_pattern: str) -> float:
    pattern = re.compile(key_pattern, re.IGNORECASE)
    total = 0.0
    if isinstance(payload, dict):
        for key, value in payload.items():
            if pattern.search(key):
                parsed = number(value)
                if parsed is not None:
                    total += parsed
            total += recursive_numeric_sum(value, key_pattern)
    elif isinstance(payload, list):
        for item in payload:
            total += recursive_numeric_sum(item, key_pattern)
    return total


def minutes_between(start_at: datetime | None, end_at: datetime | None) -> float | None:
    if start_at is None or end_at is None:
        return None
    seconds = (end_at - start_at).total_seconds()
    if seconds < 0:
        return None
    return seconds / 60.0
