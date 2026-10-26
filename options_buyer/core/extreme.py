"""§3.4.3 极端行情熔断：3×ATR 或盘口过薄 → 暂停 15 分钟。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from options_buyer.core.types import (
    EXTREME_ATR_MULT,
    EXTREME_BOOK_MIN_SIZE,
    EXTREME_PAUSE_SECONDS,
    AccountState,
)


@dataclass(frozen=True)
class ExtremeCheck:
    halted: bool
    reason: str = ""
    pause_until: float | None = None


def atr_from_bars(ranges: list[float]) -> float:
    """14 周期 5 分钟 ATR 简化：传入 14 个 high-low 振幅。"""
    if not ranges:
        return 0.0
    n = min(14, len(ranges))
    return sum(ranges[-n:]) / n


def check_extreme(
    *,
    one_min_range: float,
    atr_5m_14: float,
    book_bid_size: int,
    book_ask_size: int,
    now: float | None = None,
) -> ExtremeCheck:
    now = time.time() if now is None else now
    if atr_5m_14 > 0 and one_min_range > EXTREME_ATR_MULT * atr_5m_14:
        until = now + EXTREME_PAUSE_SECONDS
        return ExtremeCheck(
            True,
            reason=f"1分钟波动 {one_min_range:.4f} > {EXTREME_ATR_MULT}×ATR({atr_5m_14:.4f})",
            pause_until=until,
        )
    book = min(book_bid_size, book_ask_size)
    if book < EXTREME_BOOK_MIN_SIZE:
        until = now + EXTREME_PAUSE_SECONDS
        return ExtremeCheck(
            True,
            reason=f"盘口买卖量 {book} < {EXTREME_BOOK_MIN_SIZE} 张",
            pause_until=until,
        )
    return ExtremeCheck(False)


def apply_extreme_pause(account: AccountState, check: ExtremeCheck) -> AccountState:
    if check.halted and check.pause_until is not None:
        prev = account.extreme_pause_until or 0.0
        account.extreme_pause_until = max(prev, check.pause_until)
    return account


def extreme_paused(account: AccountState, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    until = account.extreme_pause_until
    if until is None:
        return False
    if now >= until:
        account.extreme_pause_until = None
        return False
    return True
