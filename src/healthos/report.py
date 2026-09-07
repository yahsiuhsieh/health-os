from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any

from healthos.coach import CoachDraft, assess_report_quality, email_subject
from healthos.utils import number


@dataclass(frozen=True)
class EmailReport:
    subject: str
    text_body: str
    html_body: str


@dataclass(frozen=True)
class MetricCard:
    label: str
    value: str
    trend: str
    status_label: str
    status: str


def render_email_report(
    *,
    report_date: date,
    sleep_recovery_row: dict[str, Any],
    activity_row: dict[str, Any],
    draft: CoachDraft,
) -> EmailReport:
    subject = email_subject(report_date)
    quality = assess_report_quality(sleep_recovery_row, activity_row)
    sleep_cards = _sleep_cards(sleep_recovery_row, quality)
    activity_cards = _activity_cards(activity_row, quality)
    recovery_cards = _recovery_cards(sleep_recovery_row, quality)
    return EmailReport(
        subject=subject,
        text_body=_render_text(
            subject,
            sleep_recovery_row,
            activity_row,
            draft,
            sleep_cards,
            activity_cards,
            recovery_cards,
            quality,
        ),
        html_body=_render_html(
            report_date,
            sleep_recovery_row,
            activity_row,
            draft,
            sleep_cards,
            activity_cards,
            recovery_cards,
            quality,
        ),
    )


def _render_text(
    subject: str,
    sleep_recovery: dict[str, Any],
    activity: dict[str, Any],
    draft: CoachDraft,
    sleep_cards: list[MetricCard],
    activity_cards: list[MetricCard],
    recovery_cards: list[MetricCard],
    quality: dict[str, Any],
) -> str:
    lines = [subject, "", "今日重點", draft.summary]
    _append_text_section(
        lines,
        "昨晚睡眠",
        str(sleep_recovery.get("metric_date") or "日期未知"),
        draft.sleep_insight,
        sleep_cards,
    )
    _append_text_section(
        lines,
        "昨日活動",
        str(activity.get("metric_date") or "日期未知"),
        draft.activity_insight,
        activity_cards,
    )
    _append_text_section(
        lines,
        "恢復訊號",
        str(sleep_recovery.get("metric_date") or "日期未知"),
        draft.recovery_insight,
        recovery_cards,
    )
    lines.extend(["", "今日建議"])
    for index, action in enumerate(draft.today_actions[:3], start=1):
        lines.append(f"{index}. {action}")
    lines.extend(["", "資料品質"])
    for label, item in _quality_items(quality):
        lines.append(f"- {label}: {item['label']} - {item['reason']}")
    if draft.cautions:
        lines.append("注意事項")
        for caution in draft.cautions[:3]:
            lines.append(f"- {caution}")
    lines.extend(["", "本摘要僅供健康管理參考，不構成醫療建議。"])
    return "\n".join(lines)


def _append_text_section(
    lines: list[str],
    title: str,
    metric_date: str,
    insight: str,
    cards: list[MetricCard],
) -> None:
    lines.extend(["", f"{title} ({metric_date})", insight])
    for card in cards:
        lines.append(f"- {card.label}: {card.value} ({card.status_label}; {card.trend})")


def _render_html(
    report_date: date,
    sleep_recovery: dict[str, Any],
    activity: dict[str, Any],
    draft: CoachDraft,
    sleep_cards: list[MetricCard],
    activity_cards: list[MetricCard],
    recovery_cards: list[MetricCard],
    quality: dict[str, Any],
) -> str:
    badge_style = _badge_style(str(quality.get("overall") or "partial"))
    sleep_html = _metric_section_html(
        "昨晚睡眠",
        str(sleep_recovery.get("metric_date") or "日期未知"),
        draft.sleep_insight,
        sleep_cards,
    )
    activity_html = _metric_section_html(
        "昨日活動",
        str(activity.get("metric_date") or "日期未知"),
        draft.activity_insight,
        activity_cards,
    )
    recovery_html = _metric_section_html(
        "恢復訊號",
        str(sleep_recovery.get("metric_date") or "日期未知"),
        draft.recovery_insight,
        recovery_cards,
    )
    actions_html = "\n".join(
        f'<li style="margin:0 0 10px 0;">{escape(action)}</li>'
        for action in draft.today_actions[:3]
    )
    quality_html = "\n".join(_quality_row_html(label, item) for label, item in _quality_items(quality))
    cautions_html = _cautions_html(draft.cautions)

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>HealthOS 晨間健康摘要</title>
  </head>
  <body style="margin:0;background:#f5f5f7;color:#1d1d1f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;">{escape(draft.summary)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f5f7;border-collapse:collapse;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;border-collapse:collapse;">
            <tr>
              <td style="padding:4px 0 18px 0;">
                <div style="font-size:13px;line-height:18px;color:#6e6e73;font-weight:600;letter-spacing:0;">HealthOS</div>
                <div style="font-size:30px;line-height:36px;color:#1d1d1f;font-weight:700;letter-spacing:0;margin-top:4px;">晨間健康摘要</div>
                <div style="font-size:15px;line-height:22px;color:#6e6e73;margin-top:4px;">{report_date.isoformat()}</div>
              </td>
              <td align="right" valign="top" style="padding:8px 0 18px 12px;">
                <span style="{badge_style}">{escape(str(quality.get('badge') or '部分資料'))}</span>
              </td>
            </tr>
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:22px;">
                <div style="font-size:13px;line-height:18px;color:#6e6e73;font-weight:700;letter-spacing:0;">今日重點</div>
                <div style="font-size:22px;line-height:30px;color:#1d1d1f;font-weight:650;letter-spacing:0;margin-top:8px;">{escape(draft.summary)}</div>
              </td>
            </tr>
            {_spacer_html()}
            {sleep_html}
            {_spacer_html()}
            {activity_html}
            {_spacer_html()}
            {recovery_html}
            {_spacer_html()}
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 22px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;margin-bottom:10px;">今日建議</div>
                <ol style="margin:0;padding-left:20px;color:#1d1d1f;font-size:15px;line-height:22px;">{actions_html}</ol>
              </td>
            </tr>
            {_spacer_html()}
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 22px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;margin-bottom:10px;">資料品質</div>
                {quality_html}
                {cautions_html}
              </td>
            </tr>
            <tr>
              <td colspan="2" style="padding:18px 2px 0 2px;color:#86868b;font-size:12px;line-height:18px;">
                本摘要僅供健康管理參考，不構成醫療建議。
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _metric_section_html(title: str, metric_date: str, insight: str, cards: list[MetricCard]) -> str:
    cards_html = "\n".join(_metric_card_html(card) for card in cards)
    return f"""<tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 18px 8px 18px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;">{escape(title)}</div>
                <div style="font-size:13px;line-height:19px;color:#86868b;margin-top:2px;">{escape(metric_date)}</div>
                <div style="font-size:15px;line-height:22px;color:#3a3a3c;margin:10px 4px 12px 0;">{escape(insight)}</div>
                {cards_html}
              </td>
            </tr>"""


def _spacer_html() -> str:
    return '<tr><td colspan="2" style="height:14px;line-height:14px;">&nbsp;</td></tr>'


def _sleep_cards(metric: dict[str, Any], quality: dict[str, Any]) -> list[MetricCard]:
    status_label, status = _quality_status(quality, "sleep")
    return [
        _card(metric, "睡眠時間", "sleep_minutes_asleep", _duration, "分鐘", 0, status_label, status),
        _card(metric, "睡眠效率", "sleep_efficiency", _percent, "百分點", 1, status_label, status, scale=100),
        _card(metric, "深睡", "sleep_minutes_deep", _duration, "分鐘", 0, status_label, status),
        _card(metric, "REM", "sleep_minutes_rem", _duration, "分鐘", 0, status_label, status),
    ]


def _activity_cards(metric: dict[str, Any], quality: dict[str, Any]) -> list[MetricCard]:
    status_label, status = _quality_status(quality, "activity")
    return [
        _card(metric, "步數", "steps", _steps, "步", 0, status_label, status),
        _card(metric, "運動時間", "exercise_minutes", _duration, "分鐘", 0, status_label, status),
        _card(metric, "活動時間", "active_minutes_total", _duration, "分鐘", 0, status_label, status),
        _card(metric, "心率區間時間", "active_zone_minutes", _duration, "分鐘", 0, status_label, status),
        _card(metric, "久坐時間", "sedentary_minutes", _duration, "分鐘", 0, status_label, status),
    ]


def _recovery_cards(metric: dict[str, Any], quality: dict[str, Any]) -> list[MetricCard]:
    recovery_quality = _quality_part(quality, "recovery")
    cards = [
        _recovery_card(metric, recovery_quality, "HRV", "hrv_rmssd_ms", "ms"),
        _recovery_card(metric, recovery_quality, "靜息心率", "resting_hr_bpm", "bpm"),
        _recovery_card(metric, recovery_quality, "呼吸率", "respiratory_rate_bpm", "bpm"),
    ]
    if metric.get("spo2_avg_pct") is not None:
        cards.append(_recovery_card(metric, recovery_quality, "血氧", "spo2_avg_pct", "%"))
    if metric.get("sleep_temp_delta_c") is not None:
        cards.append(_recovery_card(metric, recovery_quality, "睡眠體溫偏差", "sleep_temp_delta_c", "°C"))
    return cards


def _card(
    metric: dict[str, Any],
    label: str,
    key: str,
    formatter: Any,
    trend_unit: str,
    precision: int,
    status_label: str,
    status: str,
    *,
    scale: float = 1,
) -> MetricCard:
    return MetricCard(
        label=label,
        value=formatter(metric.get(key)),
        trend=_trend(metric, key, trend_unit, precision=precision, scale=scale),
        status_label=status_label if metric.get(key) is not None else "缺資料",
        status=status if metric.get(key) is not None else "missing",
    )


def _recovery_card(
    metric: dict[str, Any],
    recovery_quality: dict[str, Any],
    label: str,
    key: str,
    unit: str,
) -> MetricCard:
    value = metric.get(key)
    status = str(recovery_quality.get("status") or "missing") if value is not None else "missing"
    status_label = str(recovery_quality.get("label") or "缺資料") if value is not None else "缺資料"
    return MetricCard(
        label=label,
        value=_metric_number(value, unit),
        trend=_trend(metric, key, unit, precision=1),
        status_label=status_label,
        status=status,
    )


def _metric_card_html(card: MetricCard) -> str:
    return f"""
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-top:1px solid #f0f0f2;">
                  <tr>
                    <td style="padding:13px 4px 13px 0;">
                      <div style="font-size:14px;line-height:20px;color:#6e6e73;font-weight:650;">{escape(card.label)}</div>
                      <div style="font-size:13px;line-height:19px;color:#86868b;margin-top:2px;">{escape(card.trend)}</div>
                    </td>
                    <td align="right" style="padding:13px 0 13px 8px;">
                      <div style="font-size:22px;line-height:28px;color:#1d1d1f;font-weight:700;letter-spacing:0;">{escape(card.value)}</div>
                      <div style="font-size:12px;line-height:18px;margin-top:4px;">
                        <span style="{_badge_style(card.status)}">{escape(card.status_label)}</span>
                      </div>
                    </td>
                  </tr>
                </table>"""


def _quality_row_html(label: str, item: dict[str, Any]) -> str:
    status = str(item.get("status") or "partial")
    return f"""
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-top:1px solid #f0f0f2;">
                  <tr>
                    <td style="padding:11px 4px 11px 0;color:#1d1d1f;font-size:14px;line-height:20px;font-weight:650;">{escape(label)}</td>
                    <td align="right" style="padding:11px 0 11px 8px;"><span style="{_badge_style(status)}">{escape(str(item.get('label') or '部分資料'))}</span></td>
                  </tr>
                  <tr>
                    <td colspan="2" style="padding:0 0 11px 0;color:#6e6e73;font-size:13px;line-height:19px;">{escape(str(item.get('reason') or ''))}</td>
                  </tr>
                </table>"""


def _cautions_html(cautions: tuple[str, ...]) -> str:
    if not cautions:
        return ""
    items = "\n".join(
        f'<li style="margin:0 0 8px 0;">{escape(caution)}</li>' for caution in cautions[:3]
    )
    return f"""
                <div style="margin-top:14px;padding-top:14px;border-top:1px solid #f0f0f2;">
                  <div style="font-size:13px;line-height:18px;color:#6e6e73;font-weight:700;margin-bottom:8px;">注意事項</div>
                  <ul style="margin:0;padding-left:18px;color:#6e6e73;font-size:14px;line-height:21px;">{items}</ul>
                </div>"""


def _quality_items(quality: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("睡眠", _quality_part(quality, "sleep")),
        ("恢復", _quality_part(quality, "recovery")),
        ("活動", _quality_part(quality, "activity")),
    ]


def _quality_part(quality: dict[str, Any], key: str) -> dict[str, Any]:
    item = quality.get(key)
    return item if isinstance(item, dict) else {}


def _quality_status(quality: dict[str, Any], key: str) -> tuple[str, str]:
    item = _quality_part(quality, key)
    return str(item.get("label") or "缺資料"), str(item.get("status") or "missing")


def _trend(
    metric: dict[str, Any],
    key: str,
    unit: str,
    *,
    precision: int,
    scale: float = 1,
) -> str:
    current = number(metric.get(key))
    if current is None:
        return "目前缺資料"
    parts = []
    for baseline_key, label in (("baseline_7d", "7 天"), ("baseline_28d", "28 天")):
        averages = _baseline_averages(metric, baseline_key)
        baseline = number(averages.get(key))
        if baseline is None:
            continue
        diff = (current - baseline) * scale
        formatted = f"{diff:+.{precision}f}" if precision > 0 else f"{diff:+.0f}"
        parts.append(f"較 {label}平均 {formatted} {unit}")
    return "；".join(parts) if parts else "尚無 7/28 天基準"


def _baseline_averages(metric: dict[str, Any], baseline_key: str) -> dict[str, Any]:
    baseline = metric.get(baseline_key)
    if not isinstance(baseline, dict):
        return {}
    averages = baseline.get("averages")
    return averages if isinstance(averages, dict) else {}


def _duration(value: Any) -> str:
    minutes = number(value)
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
    parsed = number(value)
    if parsed is None:
        return "沒有資料"
    if parsed <= 1:
        parsed *= 100
    return f"{parsed:.1f}%"


def _steps(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "沒有資料"
    return f"{parsed:,.0f} 步"


def _metric_number(value: Any, unit: str) -> str:
    parsed = number(value)
    if parsed is None:
        return "沒有資料"
    return f"{parsed:.1f} {unit}"


def _badge_style(status: str) -> str:
    background, color = {
        "complete": ("#eaf7ee", "#1d7f3a"),
        "ok": ("#eaf7ee", "#1d7f3a"),
        "partial": ("#fff4de", "#8a5b00"),
        "incomplete": ("#fff4de", "#8a5b00"),
        "low_confidence": ("#fff0f0", "#b42318"),
        "missing": ("#f2f2f7", "#6e6e73"),
    }.get(status, ("#f2f2f7", "#6e6e73"))
    return (
        f"display:inline-block;background:{background};color:{color};"
        "border-radius:8px;padding:4px 8px;font-size:12px;line-height:16px;font-weight:700;"
    )
