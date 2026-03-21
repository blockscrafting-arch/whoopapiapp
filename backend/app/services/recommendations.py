"""Простые рекомендации по порогам (без AI)."""

from typing import Any, Optional


def build_recommendations(
    *,
    recovery_score: Optional[float],
    recovery_state: Optional[str],
    sleep_hours: Optional[float],
    sleep_state: Optional[str],
    strain: Optional[float],
    strain_state: Optional[str],
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []

    if recovery_state == "SCORED" and recovery_score is not None:
        if recovery_score < 40:
            recs.append(
                {
                    "type": "recovery",
                    "level": "warning",
                    "text": "Рекомендуется отдых или лёгкая нагрузка",
                }
            )
        elif recovery_score >= 70:
            recs.append(
                {
                    "type": "recovery",
                    "level": "ok",
                    "text": "Хорошее восстановление — можно тренироваться",
                }
            )

    if sleep_state == "SCORED" and sleep_hours is not None and sleep_hours < 6:
        recs.append(
            {
                "type": "sleep",
                "level": "warning",
                "text": "Недостаток сна, рекомендуется восстановление",
            }
        )

    if strain_state == "SCORED" and strain is not None and strain >= 14:
        recs.append(
            {
                "type": "strain",
                "level": "warning",
                "text": "Высокая нагрузка, снизьте активность",
            }
        )

    return recs


def sleep_hours_from_record(record: dict[str, Any]) -> tuple[Optional[float], str]:
    state = record.get("score_state") or "UNKNOWN"
    if state != "SCORED":
        return None, state
    score = record.get("score") or {}
    st = score.get("stage_summary") or {}
    ms = (
        int(st.get("total_light_sleep_time_milli") or 0)
        + int(st.get("total_slow_wave_sleep_time_milli") or 0)
        + int(st.get("total_rem_sleep_time_milli") or 0)
    )
    return round(ms / 3_600_000.0, 2), state


def recovery_from_record(record: dict[str, Any]) -> tuple[Optional[float], str]:
    state = record.get("score_state") or "UNKNOWN"
    if state != "SCORED":
        return None, state
    score = record.get("score") or {}
    val = score.get("recovery_score")
    if val is None:
        return None, state
    return float(val), state


def strain_from_record(record: dict[str, Any]) -> tuple[Optional[float], str]:
    state = record.get("score_state") or "UNKNOWN"
    if state != "SCORED":
        return None, state
    score = record.get("score") or {}
    val = score.get("strain")
    if val is None:
        return None, state
    return float(val), state
