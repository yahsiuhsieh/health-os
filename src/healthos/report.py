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
    delta: str
    status_label: str
    status: str


def render_email_report(
    *,
    mode: str,
    metric_date: date,
    metric_row: dict[str, Any],
    draft: CoachDraft,
) -> EmailReport:
    subject = email_subject(mode, metric_date)
    quality = assess_report_quality(mode, metric_row)
    cards = _metric_cards(metric_row, quality)
    return EmailReport(
        subject=subject,
        text_body=_render_text(subject, draft, cards, quality),
        html_body=_render_html(mode, metric_date, draft, cards, quality),
    )


def _render_text(
    subject: str,
    draft: CoachDraft,
    cards: list[MetricCard],
    quality: dict[str, Any],
) -> str:
    lines = [
        subject,
        "",
        "Top insight",
        draft.summary,
    ]
    if draft.signals:
        lines.extend(["", "Signals"])
        for signal in draft.signals[:3]:
            lines.append(f"- {signal}")
    lines.extend(["", "Key metrics"])
    for card in cards:
        lines.append(f"- {card.label}: {card.value} ({card.status_label}; {card.delta})")
    lines.extend(["", "Coach notes"])
    for index, note in enumerate(draft.coach_notes[:3], start=1):
        lines.append(f"{index}. {note}")
    if draft.cautions:
        lines.extend(["", "Cautions"])
        for caution in draft.cautions[:3]:
            lines.append(f"- {caution}")
    lines.extend(["", "Data quality"])
    for label, item in _quality_items(quality):
        lines.append(f"- {label}: {item['label']} - {item['reason']}")
    lines.extend(["", "This is not medical advice."])
    return "\n".join(lines)


def _render_html(
    mode: str,
    metric_date: date,
    draft: CoachDraft,
    cards: list[MetricCard],
    quality: dict[str, Any],
) -> str:
    title = "Morning Recovery" if mode == "morning" else "Evening Wrap-Up"
    badge_style = _badge_style(str(quality.get("overall") or "partial"))
    signals_html = _signals_html(draft.signals)
    cards_html = "\n".join(_metric_card_html(card) for card in cards)
    notes_html = "\n".join(
        f"<li style=\"margin:0 0 10px 0;\">{escape(note)}</li>" for note in draft.coach_notes[:3]
    )
    cautions_html = _cautions_html(draft.cautions)
    quality_html = "\n".join(_quality_row_html(label, item) for label, item in _quality_items(quality))

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
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
                <div style="font-size:30px;line-height:36px;color:#1d1d1f;font-weight:700;letter-spacing:0;margin-top:4px;">{escape(title)}</div>
                <div style="font-size:15px;line-height:22px;color:#6e6e73;margin-top:4px;">{metric_date.isoformat()}</div>
              </td>
              <td align="right" valign="top" style="padding:8px 0 18px 12px;">
                <span style="{badge_style}">{escape(str(quality.get("badge") or "部分資料"))}</span>
              </td>
            </tr>
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:22px 22px 20px 22px;">
                <div style="font-size:13px;line-height:18px;color:#6e6e73;font-weight:700;text-transform:uppercase;letter-spacing:0;">Top insight</div>
                <div style="font-size:22px;line-height:30px;color:#1d1d1f;font-weight:650;letter-spacing:0;margin-top:8px;">{escape(draft.summary)}</div>
                {signals_html}
              </td>
            </tr>
            <tr><td colspan="2" style="height:14px;line-height:14px;">&nbsp;</td></tr>
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 18px 8px 18px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;margin-bottom:10px;">Key metrics</div>
                {cards_html}
              </td>
            </tr>
            <tr><td colspan="2" style="height:14px;line-height:14px;">&nbsp;</td></tr>
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 22px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;margin-bottom:10px;">Coach notes</div>
                <ol style="margin:0;padding-left:20px;color:#1d1d1f;font-size:15px;line-height:22px;">{notes_html}</ol>
                {cautions_html}
              </td>
            </tr>
            <tr><td colspan="2" style="height:14px;line-height:14px;">&nbsp;</td></tr>
            <tr>
              <td colspan="2" style="background:#ffffff;border:1px solid #e5e5ea;border-radius:8px;padding:18px 22px;">
                <div style="font-size:17px;line-height:24px;color:#1d1d1f;font-weight:700;margin-bottom:10px;">Data quality</div>
                {quality_html}
              </td>
            </tr>
            <tr>
              <td colspan="2" style="padding:18px 2px 0 2px;color:#86868b;font-size:12px;line-height:18px;">
                This is not medical advice.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _metric_cards(metric: dict[str, Any], quality: dict[str, Any]) -> list[MetricCard]:
    sleep_quality = _quality_part(quality, "sleep")
    recovery_quality = _quality_part(quality, "recovery")
    activity_quality = _quality_part(quality, "activity")
    return [
        MetricCard(
            label="睡眠",
            value=_duration(metric.get("sleep_minutes_asleep")),
            delta=_delta(metric, "sleep_minutes_asleep", "分鐘", precision=0),
            status_label=str(sleep_quality.get("label") or "缺資料"),
            status=str(sleep_quality.get("status") or "missing"),
        ),
        MetricCard(
            label="HRV",
            value=_metric_number(metric.get("hrv_rmssd_ms"), "ms"),
            delta=_delta(metric, "hrv_rmssd_ms", "ms", precision=1),
            status_label=_field_status_label(metric.get("hrv_rmssd_ms"), recovery_quality),
            status=_field_status(metric.get("hrv_rmssd_ms"), recovery_quality),
        ),
        MetricCard(
            label="靜息心率",
            value=_metric_number(metric.get("resting_hr_bpm"), "bpm"),
            delta=_delta(metric, "resting_hr_bpm", "bpm", precision=1),
            status_label=_field_status_label(metric.get("resting_hr_bpm"), recovery_quality),
            status=_field_status(metric.get("resting_hr_bpm"), recovery_quality),
        ),
        MetricCard(
            label="活動量",
            value=_activity_value(metric),
            delta=_activity_delta(metric),
            status_label=str(activity_quality.get("label") or "缺資料"),
            status=str(activity_quality.get("status") or "missing"),
        ),
    ]


def _metric_card_html(card: MetricCard) -> str:
    return f"""
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-top:1px solid #f0f0f2;">
                  <tr>
                    <td style="padding:13px 4px 13px 0;">
                      <div style="font-size:14px;line-height:20px;color:#6e6e73;font-weight:650;">{escape(card.label)}</div>
                      <div style="font-size:13px;line-height:19px;color:#86868b;margin-top:2px;">{escape(card.delta)}</div>
                    </td>
                    <td align="right" style="padding:13px 0 13px 8px;">
                      <div style="font-size:22px;line-height:28px;color:#1d1d1f;font-weight:700;letter-spacing:0;">{escape(card.value)}</div>
                      <div style="font-size:12px;line-height:18px;margin-top:4px;">
                        <span style="{_badge_style(card.status)}">{escape(card.status_label)}</span>
                      </div>
                    </td>
                  </tr>
                </table>"""


def _signals_html(signals: tuple[str, ...]) -> str:
    if not signals:
        return ""
    items = "\n".join(
        f"<li style=\"margin:0 0 6px 0;\">{escape(signal)}</li>" for signal in signals[:3]
    )
    return f"""
                <ul style="margin:14px 0 0 0;padding-left:18px;color:#6e6e73;font-size:14px;line-height:21px;">{items}</ul>"""


def _quality_row_html(label: str, item: dict[str, Any]) -> str:
    status = str(item.get("status") or "partial")
    return f"""
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;border-top:1px solid #f0f0f2;">
                  <tr>
                    <td style="padding:11px 4px 11px 0;color:#1d1d1f;font-size:14px;line-height:20px;font-weight:650;">{escape(label)}</td>
                    <td align="right" style="padding:11px 0 11px 8px;"><span style="{_badge_style(status)}">{escape(str(item.get("label") or "部分資料"))}</span></td>
                  </tr>
                  <tr>
                    <td colspan="2" style="padding:0 0 11px 0;color:#6e6e73;font-size:13px;line-height:19px;">{escape(str(item.get("reason") or ""))}</td>
                  </tr>
                </table>"""


def _cautions_html(cautions: tuple[str, ...]) -> str:
    if not cautions:
        return ""
    items = "\n".join(f"<li style=\"margin:0 0 8px 0;\">{escape(caution)}</li>" for caution in cautions[:3])
    return f"""
                <div style="margin-top:14px;padding-top:14px;border-top:1px solid #f0f0f2;">
                  <div style="font-size:13px;line-height:18px;color:#6e6e73;font-weight:700;text-transform:uppercase;letter-spacing:0;margin-bottom:8px;">Cautions</div>
                  <ul style="margin:0;padding-left:18px;color:#6e6e73;font-size:14px;line-height:21px;">{items}</ul>
                </div>"""


def _quality_items(quality: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result = [
        ("睡眠", _quality_part(quality, "sleep")),
        ("恢復", _quality_part(quality, "recovery")),
        ("活動", _quality_part(quality, "activity")),
    ]
    partial_day = _quality_part(quality, "partial_day")
    if partial_day.get("status") != "none":
        result.append(("日期完整度", partial_day))
    return result


def _quality_part(quality: dict[str, Any], key: str) -> dict[str, Any]:
    item = quality.get(key)
    return item if isinstance(item, dict) else {}


def _field_status_label(value: Any, recovery_quality: dict[str, Any]) -> str:
    if value is None:
        return "缺資料"
    if recovery_quality.get("status") == "incomplete":
        return "部分資料"
    return "可用"


def _field_status(value: Any, recovery_quality: dict[str, Any]) -> str:
    if value is None:
        return "missing"
    return str(recovery_quality.get("status") or "ok")


def _activity_value(metric: dict[str, Any]) -> str:
    steps = number(metric.get("steps"))
    if steps is not None:
        return f"{steps:,.0f} 步"
    active_minutes = number(metric.get("active_minutes_total"))
    if active_minutes is not None:
        return _duration(active_minutes)
    zone_minutes = number(metric.get("active_zone_minutes"))
    if zone_minutes is not None:
        return _duration(zone_minutes)
    return "沒有資料"


def _activity_delta(metric: dict[str, Any]) -> str:
    if number(metric.get("steps")) is not None:
        return _delta(metric, "steps", "步", precision=0)
    if number(metric.get("active_minutes_total")) is not None:
        return _delta(metric, "active_minutes_total", "分鐘", precision=0)
    if number(metric.get("active_zone_minutes")) is not None:
        return _delta(metric, "active_zone_minutes", "分鐘", precision=0)
    return "尚無 7 天基準"


def _delta(metric: dict[str, Any], key: str, unit: str, *, precision: int) -> str:
    current = number(metric.get(key))
    averages = _baseline_averages(metric)
    baseline = number(averages.get(key)) if averages else None
    if current is None:
        return "目前缺資料"
    if baseline is None:
        return "尚無 7 天基準"
    diff = current - baseline
    formatted = f"{diff:+.{precision}f}" if precision > 0 else f"{diff:+.0f}"
    return f"{formatted} {unit} vs 7 天平均"


def _baseline_averages(metric: dict[str, Any]) -> dict[str, Any]:
    baseline = metric.get("baseline_7d")
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


def _metric_number(value: Any, unit: str) -> str:
    parsed = number(value)
    if parsed is None:
        return "沒有資料"
    return f"{parsed:.1f} {unit}"


def _badge_style(status: str) -> str:
    background, color = {
        "complete": ("#eaf7ee", "#1d7f3a"),
        "ok": ("#eaf7ee", "#1d7f3a"),
        "expected": ("#edf4ff", "#1f62b7"),
        "partial": ("#fff4de", "#8a5b00"),
        "incomplete": ("#fff4de", "#8a5b00"),
        "low_confidence": ("#fff0f0", "#b42318"),
        "missing": ("#f2f2f7", "#6e6e73"),
        "unexpected": ("#fff0f0", "#b42318"),
    }.get(status, ("#f2f2f7", "#6e6e73"))
    return (
        f"display:inline-block;background:{background};color:{color};"
        "border-radius:8px;padding:4px 8px;font-size:12px;line-height:16px;font-weight:700;"
    )
