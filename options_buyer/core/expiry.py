"""§八 到期日管理与被指派应急。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from options_buyer.core.types import ExitReason, StrategyType


class ExpiryAction(str, Enum):
    HOLD = "hold"
    CLOSE = "close"
    CLOSE_PROTECT_OR_ASSIGNED = "close_protect_or_assigned"
    HALT_DAY = "halt_day"


@dataclass(frozen=True)
class ExpiryDecision:
    action: ExpiryAction
    reason: ExitReason | None
    detail: str
    halt_day: bool = False


def manage_expiry(
    strategy: StrategyType,
    *,
    dte: int,
    long_itm: bool = False,
    short_itm: bool = False,
    american: bool = True,
    short_distance_atr: float | None = None,
    short_delta: float | None = None,
    days_to_ex_div: int | None = None,
    assigned: bool = False,
) -> ExpiryDecision:
    if assigned:
        return ExpiryDecision(
            ExpiryAction.CLOSE_PROTECT_OR_ASSIGNED,
            ExitReason.ASSIGNMENT,
            "被指派：确认持仓与保护腿 → 平保护腿或市价平被指派仓 → 当日停机",
            halt_day=True,
        )

    if strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
        if dte <= 1:
            return ExpiryDecision(
                ExpiryAction.CLOSE, ExitReason.EXPIRY, "裸买：到期日前 1 天平仓"
            )
        return ExpiryDecision(ExpiryAction.HOLD, None, "裸买未到到期前一日")

    if strategy == StrategyType.DEBIT_SPREAD:
        if long_itm and short_itm:
            return ExpiryDecision(ExpiryAction.HOLD, None, "两腿均 ITM 可持有至结算")
        if long_itm != short_itm:
            return ExpiryDecision(
                ExpiryAction.CLOSE, ExitReason.EXPIRY, "一腿 ITM 一腿 OTM → 提前平仓"
            )
        if american and short_itm and dte < 2:
            return ExpiryDecision(
                ExpiryAction.CLOSE,
                ExitReason.EXPIRY,
                "美式短腿 ITM 且距到期 <2 天 → 提前平仓",
            )
        return ExpiryDecision(ExpiryAction.HOLD, None, "借方价差到期管理：继续持有")

    # CREDIT_SPREAD
    if dte <= 0:
        if short_distance_atr is not None and short_distance_atr < 0.5:
            return ExpiryDecision(
                ExpiryAction.CLOSE,
                ExitReason.EXPIRY,
                "到期日午后短腿距标的 <0.5 ATR → 提前平仓",
            )
    if dte <= 2 and short_distance_atr is not None and short_distance_atr < 1.0:
        return ExpiryDecision(
            ExpiryAction.CLOSE,
            ExitReason.EXPIRY,
            "Charm：信用价差 DTE≤2 且短腿距标的 <1 ATR → 提前平仓",
        )
    if (
        american
        and short_delta is not None
        and abs(short_delta) > 0.40
        and days_to_ex_div is not None
        and days_to_ex_div <= 2
    ):
        return ExpiryDecision(
            ExpiryAction.CLOSE,
            ExitReason.EXPIRY,
            "美式短腿 Delta>0.40 且除息日前 2 日 → 平仓或滚动",
        )
    return ExpiryDecision(ExpiryAction.HOLD, None, "信用价差到期管理：继续持有")
