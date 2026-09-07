from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from healthos.utils import stable_hash


LOW_CONFIDENCE_SLEEP_MINUTES = 180
RECOVERY_FIELDS = ("hrv_rmssd_ms", "resting_hr_bpm", "respiratory_rate_bpm")
ACTIVITY_FIELDS = ("steps", "active_zone_minutes", "active_minutes_total", "exercise_minutes")


@dataclass(frozen=True)
class CoachDraft:
    summary: str
    signals: tuple[str, ...]
    coach_notes: tuple[str, ...]
    cautions: tuple[str, ...] = ()


COACH_INSTRUCTIONS = """You are a conservative personal health coach.
Return only a valid JSON object in Traditional Chinese with these keys:
- summary: one sentence with the most important insight.
- signals: an array of 1-4 short metric observations.
- coach_notes: an array of 1-3 actionable suggestions.
- cautions: an array of 0-3 data-quality or safety caveats.
Use the user's own 7-day and 28-day baselines when available.
Do not diagnose disease, prescribe treatment, or overstate certainty.
If sleep_minutes_asleep is below 180, treat sleep as possible incomplete data.
If HRV, resting heart rate, or respiratory rate are missing, say recovery confidence is limited.
Do not include markdown, HTML, or explanatory text outside the JSON object."""


def build_prompt_payload(mode: str, metric_row: dict[str, Any]) -> dict[str, Any]:
    visible_fields = {
        key: value
        for key, value in metric_row.items()
        if key
        not in {
            "id",
            "account_id",
            "created_at",
            "updated_at",
            "morning_email_sent_at",
            "evening_email_sent_at",
            "morning_data_hash",
            "evening_data_hash",
            "morning_ai_provider",
            "morning_ai_model",
            "evening_ai_provider",
            "evening_ai_model",
            "source_record_id",
            "source_record_hash",
            "value_json",
            "raw_json",
        }
        and value is not None
    }
    return {
        "mode": mode,
        "goal": "morning recovery brief" if mode == "morning" else "evening day wrap-up",
        "metric": visible_fields,
        "report_quality": assess_report_quality(mode, visible_fields),
        "required_sections": (
            ["Recovery", "Coach note", "Data quality"]
            if mode == "morning"
            else ["Activity", "Coach note", "Data quality"]
        ),
        "constraints": {
            "max_coach_notes": 3,
            "no_medical_diagnosis": True,
            "do_not_mention_vendor_unless_needed": True,
        },
    }


def assess_report_quality(mode: str, metric: dict[str, Any]) -> dict[str, Any]:
    data_quality = metric.get("data_quality") if isinstance(metric.get("data_quality"), dict) else {}
    sleep_minutes = _number(metric.get("sleep_minutes_asleep"))
    has_sleep = bool(data_quality.get("has_sleep")) or sleep_minutes is not None or metric.get("sleep_minutes_total") is not None
    if not has_sleep:
        sleep_status = "missing"
        sleep_label = "缺資料"
        sleep_reason = "沒有可用睡眠紀錄。"
    elif sleep_minutes is not None and sleep_minutes < LOW_CONFIDENCE_SLEEP_MINUTES:
        sleep_status = "low_confidence"
        sleep_label = "低信心"
        sleep_reason = "睡眠少於 180 分鐘，可能是同步或穿戴紀錄不完整。"
    else:
        sleep_status = "ok"
        sleep_label = "可用"
        sleep_reason = "睡眠資料可用。"

    recovery_count = sum(1 for field in RECOVERY_FIELDS if metric.get(field) is not None)
    if recovery_count == 0:
        recovery_status = "missing"
        recovery_label = "缺資料"
        recovery_reason = "HRV、靜息心率與呼吸率都缺少，恢復判斷信心不足。"
    elif recovery_count < len(RECOVERY_FIELDS):
        recovery_status = "incomplete"
        recovery_label = "部分資料"
        recovery_reason = "HRV、靜息心率或呼吸率有缺項，恢復判斷需保守。"
    else:
        recovery_status = "ok"
        recovery_label = "可用"
        recovery_reason = "主要恢復指標可用。"

    has_activity = bool(data_quality.get("has_activity")) or any(metric.get(field) is not None for field in ACTIVITY_FIELDS)
    activity_status = "ok" if has_activity else "missing"
    activity_label = "可用" if has_activity else "缺資料"
    activity_reason = "活動資料可用。" if has_activity else "沒有可用活動紀錄。"

    partial_day = bool(data_quality.get("partial_day")) or metric.get("partial_day_as_of") is not None
    partial_allowed = mode == "evening"
    if partial_day and partial_allowed:
        partial_status = "expected"
        partial_label = "部分日"
        partial_reason = "晚間報告可能包含尚未結束的一日資料。"
    elif partial_day:
        partial_status = "unexpected"
        partial_label = "低信心"
        partial_reason = "早晨報告不應使用部分日資料，請確認同步日期。"
    else:
        partial_status = "none"
        partial_label = "完整日"
        partial_reason = "資料日期不是部分日。"

    if sleep_status == "low_confidence" or recovery_status == "missing" or partial_status == "unexpected":
        overall = "low_confidence"
        badge = "低信心"
    elif sleep_status == "missing" or recovery_status == "incomplete" or activity_status == "missing" or partial_day:
        overall = "partial"
        badge = "部分資料"
    else:
        overall = "complete"
        badge = "資料完整"

    return {
        "overall": overall,
        "badge": badge,
        "sleep": {"status": sleep_status, "label": sleep_label, "reason": sleep_reason},
        "recovery": {"status": recovery_status, "label": recovery_label, "reason": recovery_reason},
        "activity": {"status": activity_status, "label": activity_label, "reason": activity_reason},
        "partial_day": {"status": partial_status, "label": partial_label, "reason": partial_reason},
    }


def parse_prompt_payload(input_text: str) -> dict[str, Any]:
    parsed = json.loads(input_text)
    if not isinstance(parsed, dict):
        raise ValueError("Prompt payload must be a JSON object.")
    return parsed


def parse_coach_draft(text: str, payload: dict[str, Any]) -> CoachDraft:
    data = _extract_json_object(text)
    fallback = rule_based_coach_draft(payload)
    summary = _clean_string(data.get("summary")) or fallback.summary
    signals = _clean_string_list(data.get("signals"), limit=4) or fallback.signals
    coach_notes = _clean_string_list(data.get("coach_notes"), limit=3) or fallback.coach_notes
    cautions = _clean_string_list(data.get("cautions"), limit=3)
    cautions = _merge_cautions(cautions, _required_cautions(payload))
    return CoachDraft(
        summary=summary,
        signals=tuple(signals),
        coach_notes=tuple(coach_notes),
        cautions=tuple(cautions),
    )


def rule_based_coach_draft(payload: dict[str, Any]) -> CoachDraft:
    mode = str(payload.get("mode") or "morning")
    metric = payload.get("metric") if isinstance(payload.get("metric"), dict) else {}
    quality = _payload_quality(payload, mode, metric)
    signals = tuple(_rule_based_signals(mode, metric, quality))
    coach_notes = tuple(_rule_based_notes(mode, metric, quality))
    return CoachDraft(
        summary=_rule_based_summary(mode, metric, quality),
        signals=signals,
        coach_notes=coach_notes,
        cautions=tuple(_required_cautions(payload)),
    )


def prompt_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def payload_hash(payload: dict[str, Any]) -> str:
    return stable_hash(payload)


def email_subject(mode: str, metric_date: date) -> str:
    label = "Morning Recovery" if mode == "morning" else "Evening Wrap-Up"
    return f"HealthOS {label} - {metric_date.isoformat()}"


def _payload_quality(payload: dict[str, Any], mode: str, metric: dict[str, Any]) -> dict[str, Any]:
    quality = payload.get("report_quality")
    if isinstance(quality, dict):
        return quality
    return assess_report_quality(mode, metric)


def _rule_based_summary(mode: str, metric: dict[str, Any], quality: dict[str, Any]) -> str:
    sleep_status = _status(quality, "sleep")
    recovery_status = _status(quality, "recovery")
    sleep_minutes = _number(metric.get("sleep_minutes_asleep"))
    if sleep_status == "low_confidence" and recovery_status == "missing":
        return "今天睡眠資料看起來不完整，恢復指標也不足；先把這封信當成低信心提醒。"
    if sleep_status == "low_confidence":
        return "今天睡眠紀錄偏短，可能是資料不完整；先確認紀錄，再保守安排身體負荷。"
    if recovery_status == "missing":
        return "今天缺少主要恢復指標，恢復判斷信心不足，建議用主觀精神狀態輔助判斷。"
    if mode == "morning" and sleep_minutes is not None and sleep_minutes < 360:
        return "睡眠低於理想範圍，今天適合保守安排訓練與高專注工作。"
    if mode == "evening":
        return "今天的活動與恢復資料已整理，晚間重點是降低刺激並準備明天恢復。"
    return "今天資料大致可用，可以用趨勢與主觀狀態一起安排節奏。"


def _rule_based_signals(mode: str, metric: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    signals = [
        f"睡眠：{_minutes(metric.get('sleep_minutes_asleep'))}，效率 {_percent(metric.get('sleep_efficiency'))}。",
        f"恢復：HRV {_number_text(metric.get('hrv_rmssd_ms'), 'ms')}，靜息心率 {_number_text(metric.get('resting_hr_bpm'), 'bpm')}，呼吸率 {_number_text(metric.get('respiratory_rate_bpm'), 'bpm')}。",
    ]
    if mode == "evening":
        signals.append(
            f"活動：{_integer_text(metric.get('steps'), '步')}，活動時間 {_minutes(metric.get('active_minutes_total'))}。"
        )
    else:
        activity = _integer_text(metric.get("steps"), "步")
        zone = _minutes(metric.get("active_zone_minutes"))
        signals.append(f"活動資料：步數 {activity}，心率區間時間 {zone}。")
    if quality.get("overall") != "complete":
        signals.append(f"資料品質：{quality.get('badge', '部分資料')}。")
    return signals[:4]


def _rule_based_notes(mode: str, metric: dict[str, Any], quality: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if _status(quality, "sleep") == "low_confidence":
        notes.append("先確認穿戴裝置與睡眠同步，不要只因短睡眠紀錄就做大幅度調整。")
    elif _number(metric.get("sleep_minutes_asleep")) is not None and _number(metric.get("sleep_minutes_asleep")) < 360:
        notes.append("睡眠偏短，今天把訓練與工作負荷下修一級，優先維持穩定節奏。")

    if _status(quality, "recovery") in {"missing", "incomplete"}:
        notes.append("恢復指標不足，今天避免用單一分數決定強度，搭配精神、肌肉酸痛與心率反應判斷。")

    if mode == "evening":
        if _number(metric.get("sedentary_minutes")) is not None and _number(metric.get("sedentary_minutes")) >= 600:
            notes.append("久坐時間偏高，睡前用短步行或伸展收尾，不需要補償式高強度運動。")
        else:
            notes.append("晚間把重點放在降溫、放鬆與固定睡眠時間，讓明早資料更容易判讀。")
    else:
        notes.append("先用保守起步觀察身體反應；如果精神與心率都穩定，再逐步加量。")
    return notes[:3]


def _required_cautions(payload: dict[str, Any]) -> list[str]:
    mode = str(payload.get("mode") or "morning")
    metric = payload.get("metric") if isinstance(payload.get("metric"), dict) else {}
    quality = _payload_quality(payload, mode, metric)
    cautions = []
    for key in ("sleep", "recovery", "activity", "partial_day"):
        item = quality.get(key)
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status in {"low_confidence", "missing", "incomplete", "unexpected"}:
            reason = _clean_string(item.get("reason"))
            if reason:
                cautions.append(reason)
        elif key == "partial_day" and status == "expected":
            reason = _clean_string(item.get("reason"))
            if reason:
                cautions.append(reason)
    return cautions[:3]


def _merge_cautions(primary: list[str], required: list[str]) -> list[str]:
    merged: list[str] = []
    for value in primary + required:
        if value and value not in merged:
            merged.append(value)
        if len(merged) == 3:
            break
    return merged


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidate = fence_match.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("AI response did not contain a JSON object.")
        parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI response JSON must be an object.")
    return parsed


def _clean_string(value: Any, *, max_length: int = 220) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split())
    if len(cleaned) > max_length:
        return cleaned[: max_length - 1].rstrip() + "..."
    return cleaned


def _clean_string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        cleaned = _clean_string(item)
        if cleaned:
            result.append(cleaned)
        if len(result) == limit:
            break
    return result


def _status(quality: dict[str, Any], key: str) -> str:
    item = quality.get(key)
    if not isinstance(item, dict):
        return "missing"
    status = item.get("status")
    return str(status) if status else "missing"


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _minutes(value: Any) -> str:
    minutes = _number(value)
    if minutes is None:
        return "沒有資料"
    if minutes < 90:
        return f"{minutes:.0f} 分鐘"
    hours = int(minutes // 60)
    remaining = int(round(minutes - hours * 60))
    if remaining == 60:
        hours += 1
        remaining = 0
    if remaining == 0:
        return f"{hours} 小時"
    return f"{hours} 小時 {remaining} 分鐘"


def _percent(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "沒有資料"
    if number <= 1:
        number *= 100
    return f"{number:.1f}%"


def _number_text(value: Any, unit: str) -> str:
    number = _number(value)
    if number is None:
        return "沒有資料"
    return f"{number:.1f} {unit}"


def _integer_text(value: Any, unit: str) -> str:
    number = _number(value)
    if number is None:
        return "沒有資料"
    return f"{number:.0f} {unit}"
