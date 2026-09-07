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
SLEEP_RECOVERY_FIELDS = {
    "sleep_start_at",
    "sleep_end_at",
    "sleep_minutes_total",
    "sleep_minutes_asleep",
    "sleep_minutes_awake",
    "sleep_minutes_light",
    "sleep_minutes_deep",
    "sleep_minutes_rem",
    "sleep_efficiency",
    "hrv_rmssd_ms",
    "resting_hr_bpm",
    "respiratory_rate_bpm",
    "spo2_avg_pct",
    "sleep_temp_delta_c",
    "readiness_score",
}
PREVIOUS_DAY_ACTIVITY_FIELDS = {
    "steps",
    "active_zone_minutes",
    "active_minutes_total",
    "active_minutes_light",
    "active_minutes_moderate",
    "active_minutes_vigorous",
    "exercise_minutes",
    "sedentary_minutes",
    "strain_score",
}


@dataclass(frozen=True)
class CoachDraft:
    summary: str
    sleep_insight: str
    activity_insight: str
    recovery_insight: str
    today_actions: tuple[str, ...]
    cautions: tuple[str, ...] = ()


COACH_INSTRUCTIONS = """You are a conservative personal health coach.
Return only a valid JSON object in Traditional Chinese with these keys:
- summary: one sentence with the most important insight for today.
- sleep_insight: one short interpretation of last night's sleep.
- activity_insight: one short interpretation of yesterday's activity and trend.
- recovery_insight: one short interpretation of the latest recovery signals.
- today_actions: an array of 1-3 specific, practical actions for today.
- cautions: an array of 0-3 data-quality or safety caveats.
The payload separates sleep_recovery from previous_day_activity. Do not mix their dates.
Use the user's own 7-day and 28-day baselines when available.
Do not diagnose disease, prescribe treatment, invent missing values, or overstate certainty.
If sleep_minutes_asleep is below 180, treat sleep as possible incomplete data.
If HRV, resting heart rate, or respiratory rate are missing, say recovery confidence is limited.
Do not include markdown, HTML, or explanatory text outside the JSON object."""


def build_prompt_payload(
    report_date: date,
    sleep_recovery_row: dict[str, Any],
    activity_row: dict[str, Any],
) -> dict[str, Any]:
    sleep_recovery = _visible_metric_fields(
        sleep_recovery_row,
        SLEEP_RECOVERY_FIELDS,
        {"has_sleep", "has_recovery"},
    )
    activity = _visible_metric_fields(
        activity_row,
        PREVIOUS_DAY_ACTIVITY_FIELDS,
        {"has_activity"},
    )
    return {
        "report_date": report_date.isoformat(),
        "goal": "daily morning personal health coaching brief",
        "sleep_recovery": sleep_recovery,
        "previous_day_activity": activity,
        "report_quality": assess_report_quality(sleep_recovery, activity),
        "required_sections": [
            "summary",
            "sleep_insight",
            "activity_insight",
            "recovery_insight",
            "today_actions",
            "cautions",
        ],
        "constraints": {
            "max_today_actions": 3,
            "no_medical_diagnosis": True,
            "do_not_mention_vendor_unless_needed": True,
        },
    }


def assess_report_quality(
    sleep_recovery: dict[str, Any],
    activity: dict[str, Any],
) -> dict[str, Any]:
    sleep_data_quality = _data_quality(sleep_recovery)
    activity_data_quality = _data_quality(activity)
    sleep_minutes = _number(sleep_recovery.get("sleep_minutes_asleep"))
    has_sleep = (
        bool(sleep_data_quality.get("has_sleep"))
        or sleep_minutes is not None
        or sleep_recovery.get("sleep_minutes_total") is not None
    )
    if not has_sleep:
        sleep_status = "missing"
        sleep_label = "缺資料"
        sleep_reason = "沒有取得昨晚的睡眠紀錄。"
    elif sleep_minutes is None:
        sleep_status = "incomplete"
        sleep_label = "部分資料"
        sleep_reason = "有睡眠時段但缺少實際睡眠分鐘，睡眠品質判斷需保守。"
    elif sleep_minutes is not None and sleep_minutes < LOW_CONFIDENCE_SLEEP_MINUTES:
        sleep_status = "low_confidence"
        sleep_label = "低信心"
        sleep_reason = "睡眠少於 180 分鐘，可能是同步或穿戴紀錄不完整。"
    else:
        sleep_status = "ok"
        sleep_label = "可用"
        sleep_reason = "昨晚睡眠資料可用。"

    recovery_count = sum(1 for field in RECOVERY_FIELDS if sleep_recovery.get(field) is not None)
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

    has_activity = bool(activity_data_quality.get("has_activity")) or any(
        activity.get(field) is not None for field in ACTIVITY_FIELDS
    )
    activity_status = "ok" if has_activity else "missing"
    activity_label = "可用" if has_activity else "缺資料"
    activity_reason = "昨天活動資料可用。" if has_activity else "沒有取得昨天的活動紀錄。"

    if sleep_status == "low_confidence" or recovery_status == "missing":
        overall = "low_confidence"
        badge = "低信心"
    elif sleep_status in {"missing", "incomplete"} or recovery_status == "incomplete" or activity_status == "missing":
        overall = "partial"
        badge = "部分資料"
    else:
        overall = "complete"
        badge = "資料完整"

    return {
        "overall": overall,
        "badge": badge,
        "sleep": {"status": sleep_status, "label": sleep_label, "reason": sleep_reason},
        "recovery": {
            "status": recovery_status,
            "label": recovery_label,
            "reason": recovery_reason,
        },
        "activity": {
            "status": activity_status,
            "label": activity_label,
            "reason": activity_reason,
        },
    }


def parse_prompt_payload(input_text: str) -> dict[str, Any]:
    parsed = json.loads(input_text)
    if not isinstance(parsed, dict):
        raise ValueError("Prompt payload must be a JSON object.")
    return parsed


def parse_coach_draft(text: str, payload: dict[str, Any]) -> CoachDraft:
    data = _extract_json_object(text)
    fallback = rule_based_coach_draft(payload)
    cautions = _clean_string_list(data.get("cautions"), limit=3)
    cautions = _merge_cautions(cautions, _required_cautions(payload))
    return CoachDraft(
        summary=_clean_string(data.get("summary")) or fallback.summary,
        sleep_insight=_clean_string(data.get("sleep_insight")) or fallback.sleep_insight,
        activity_insight=_clean_string(data.get("activity_insight")) or fallback.activity_insight,
        recovery_insight=_clean_string(data.get("recovery_insight")) or fallback.recovery_insight,
        today_actions=tuple(
            _clean_string_list(data.get("today_actions"), limit=3) or fallback.today_actions
        ),
        cautions=tuple(cautions),
    )


def rule_based_coach_draft(payload: dict[str, Any]) -> CoachDraft:
    sleep_recovery, activity = _payload_metrics(payload)
    quality = _payload_quality(payload, sleep_recovery, activity)
    return CoachDraft(
        summary=_rule_based_summary(sleep_recovery, quality),
        sleep_insight=_rule_based_sleep_insight(sleep_recovery, quality),
        activity_insight=_rule_based_activity_insight(activity, quality),
        recovery_insight=_rule_based_recovery_insight(sleep_recovery, quality),
        today_actions=tuple(_rule_based_actions(sleep_recovery, activity, quality)),
        cautions=tuple(_required_cautions(payload)),
    )


def prompt_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)


def payload_hash(payload: dict[str, Any]) -> str:
    return stable_hash(payload)


def email_subject(report_date: date) -> str:
    return f"HealthOS 晨間健康摘要 - {report_date.isoformat()}"


def _visible_metric_fields(
    metric_row: dict[str, Any],
    metric_fields: set[str],
    quality_fields: set[str],
) -> dict[str, Any]:
    result = {
        key: value
        for key, value in metric_row.items()
        if (key == "metric_date" or key in metric_fields) and value is not None
    }
    for baseline_key in ("baseline_7d", "baseline_28d"):
        baseline = metric_row.get(baseline_key)
        if not isinstance(baseline, dict):
            continue
        averages = baseline.get("averages")
        result[baseline_key] = {
            "sample_count": baseline.get("sample_count"),
            "days": baseline.get("days"),
            "averages": {
                key: value
                for key, value in (averages.items() if isinstance(averages, dict) else [])
                if key in metric_fields and value is not None
            },
        }
    data_quality = metric_row.get("data_quality")
    if isinstance(data_quality, dict):
        result["data_quality"] = {
            key: value for key, value in data_quality.items() if key in quality_fields
        }
    return result


def _data_quality(metric: dict[str, Any]) -> dict[str, Any]:
    value = metric.get("data_quality")
    return value if isinstance(value, dict) else {}


def _payload_metrics(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sleep_recovery = payload.get("sleep_recovery")
    activity = payload.get("previous_day_activity")
    return (
        sleep_recovery if isinstance(sleep_recovery, dict) else {},
        activity if isinstance(activity, dict) else {},
    )


def _payload_quality(
    payload: dict[str, Any],
    sleep_recovery: dict[str, Any],
    activity: dict[str, Any],
) -> dict[str, Any]:
    quality = payload.get("report_quality")
    if isinstance(quality, dict):
        return quality
    return assess_report_quality(sleep_recovery, activity)


def _rule_based_summary(sleep_recovery: dict[str, Any], quality: dict[str, Any]) -> str:
    sleep_status = _status(quality, "sleep")
    recovery_status = _status(quality, "recovery")
    sleep_minutes = _number(sleep_recovery.get("sleep_minutes_asleep"))
    if sleep_status == "low_confidence" and recovery_status == "missing":
        return "昨晚睡眠紀錄可能不完整，恢復指標也不足；今天先用主觀狀態保守安排節奏。"
    if sleep_status == "low_confidence":
        return "昨晚睡眠紀錄偏短且可能不完整，今天先確認資料並保守安排身體負荷。"
    if sleep_status == "missing":
        return "昨晚睡眠資料缺少，今天的建議以昨天活動與主觀精神狀態為主。"
    if recovery_status == "missing":
        return "今天缺少主要恢復指標，請搭配精神、肌肉酸痛與運動心率判斷負荷。"
    if sleep_minutes is not None and sleep_minutes < 360:
        return "昨晚睡眠低於六小時，今天適合下修訓練與高專注工作的負荷。"
    return "最新睡眠、恢復與昨天活動資料已整理，可依身體反應逐步安排今天的節奏。"


def _rule_based_sleep_insight(metric: dict[str, Any], quality: dict[str, Any]) -> str:
    if _status(quality, "sleep") == "missing":
        return "昨晚沒有可用睡眠資料，無法可靠評估睡眠品質。"
    if _status(quality, "sleep") == "incomplete":
        return "昨晚有睡眠時段紀錄，但缺少實際睡眠分鐘，暫時無法完整評估睡眠品質。"
    if _status(quality, "sleep") == "low_confidence":
        return "睡眠紀錄少於三小時，較可能是同步不完整，不宜直接視為實際睡眠。"
    return f"昨晚睡眠 {_minutes(metric.get('sleep_minutes_asleep'))}，效率 {_percent(metric.get('sleep_efficiency'))}。"


def _rule_based_activity_insight(metric: dict[str, Any], quality: dict[str, Any]) -> str:
    if _status(quality, "activity") == "missing":
        return "昨天沒有可用活動資料，無法可靠判斷活動負荷。"
    return (
        f"昨天共 {_integer_text(metric.get('steps'), '步')}，運動 {_minutes(metric.get('exercise_minutes'))}，"
        f"心率區間時間 {_minutes(metric.get('active_zone_minutes'))}。"
    )


def _rule_based_recovery_insight(metric: dict[str, Any], quality: dict[str, Any]) -> str:
    if _status(quality, "recovery") == "missing":
        return "主要恢復指標缺少，今天不要用單一分數決定訓練強度。"
    return (
        f"HRV {_number_text(metric.get('hrv_rmssd_ms'), 'ms')}，"
        f"靜息心率 {_number_text(metric.get('resting_hr_bpm'), 'bpm')}，"
        f"呼吸率 {_number_text(metric.get('respiratory_rate_bpm'), 'bpm')}。"
    )


def _rule_based_actions(
    sleep_recovery: dict[str, Any],
    activity: dict[str, Any],
    quality: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    sleep_minutes = _number(sleep_recovery.get("sleep_minutes_asleep"))
    if _status(quality, "sleep") == "low_confidence":
        actions.append("先確認穿戴裝置與睡眠同步，不要只因短睡眠紀錄就大幅調整計畫。")
    elif sleep_minutes is not None and sleep_minutes < 360:
        actions.append("睡眠偏短，今天把訓練與高專注工作的負荷下修一級。")

    if _status(quality, "recovery") in {"missing", "incomplete"}:
        actions.append("用精神、肌肉酸痛與活動時心率輔助判斷，避免用單一指標決定強度。")

    sedentary_minutes = _number(activity.get("sedentary_minutes"))
    if sedentary_minutes is not None and sedentary_minutes >= 600:
        actions.append("昨天久坐時間偏高，今天安排數次短步行或活動休息，不需要補償式高強度運動。")

    if not actions:
        actions.append("先用保守強度開始今天的活動；若精神與心率反應穩定，再逐步加量。")
    return actions[:3]


def _required_cautions(payload: dict[str, Any]) -> list[str]:
    sleep_recovery, activity = _payload_metrics(payload)
    quality = _payload_quality(payload, sleep_recovery, activity)
    cautions = []
    for key in ("sleep", "recovery", "activity"):
        item = quality.get(key)
        if not isinstance(item, dict):
            continue
        if item.get("status") in {"low_confidence", "missing", "incomplete"}:
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
    parsed = _number(value)
    if parsed is None:
        return "沒有資料"
    if parsed <= 1:
        parsed *= 100
    return f"{parsed:.1f}%"


def _number_text(value: Any, unit: str) -> str:
    parsed = _number(value)
    if parsed is None:
        return "沒有資料"
    return f"{parsed:.1f} {unit}"


def _integer_text(value: Any, unit: str) -> str:
    parsed = _number(value)
    if parsed is None:
        return "沒有資料"
    return f"{parsed:.0f} {unit}"
