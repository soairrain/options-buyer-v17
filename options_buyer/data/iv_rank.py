"""§3.4.1 IV Rank / IV Percentile。"""

from __future__ import annotations


def iv_rank(current: float, year_low: float, year_high: float) -> float:
    """IV Rank = (当前 − 52周最低) / (52周最高 − 52周最低)，0–100。"""
    span = year_high - year_low
    if span <= 0:
        return 0.0
    return max(0.0, min(100.0, (current - year_low) / span * 100.0))


def iv_percentile(current: float, history: list[float]) -> float:
    """过去样本中 IV 低于当前值的天数占比，0–100。"""
    if not history:
        return 0.0
    below = sum(1 for v in history if v < current)
    return 100.0 * below / len(history)
