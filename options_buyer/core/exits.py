"""3.5.2 分场景止盈 / 止损 / IV 变化规则。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from options_buyer.core.types import ExitReason, StrategyType, TIME_STOP_DTE


class ExitAction(str, Enum):
    HOLD = "hold"
    CLOSE_ALL = "close_all"
    CLOSE_HALF = "close_half"


# 权利金浮点噪声：1.5R 常见差 1e-16
_R_EPS = 1e-9


@dataclass(frozen=True)
class ExitDecision:
    action: ExitAction
    reason: ExitReason | None
    detail: str = ""


def pnl_in_r(
    strategy: StrategyType,
    *,
    entry: float,
    mark: float,
    r_per_contract: float,
    width: float = 0.0,
    credit: float = 0.0,
) -> float:
    """按 R 倍数计算当前盈亏（正为盈利）。

    裸买/借方：盈亏 = (mark - entry) / r_per_contract（多头）
    信用：盈利朝向净收收窄；简化用已实现权利金回吐。
      开仓收 C，现价买回 mark（组合净价）；pnl = C - mark；1R = (W-C)/2
    """
    if r_per_contract <= 0:
        raise ValueError("r_per_contract must be positive")

    if strategy == StrategyType.CREDIT_SPREAD:
        pnl = credit - mark
        return pnl / r_per_contract

    # long / deep_itm / debit：多头
    pnl = mark - entry
    return pnl / r_per_contract


def long_or_debit_exit(
    *,
    dte: int,
    pnl_r: float,
    structure_target_r: float,
    remaining_fraction: float = 1.0,
    strategy: StrategyType = StrategyType.LONG,
) -> ExitDecision:
    """裸买 / 借方价差止盈止损。"""
    if pnl_r <= -1.0 + _R_EPS:
        return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.STOP_1R, "亏损达 1R")

    if dte < TIME_STOP_DTE:
        if strategy == StrategyType.DEBIT_SPREAD:
            # §4.2 / §3.5.2：剩余 DTE <7 且未达 1.5R → 平仓，不滚动
            if pnl_r < 1.5 - _R_EPS:
                return ExitDecision(
                    ExitAction.CLOSE_ALL,
                    ExitReason.TIME_STOP,
                    "借方 DTE<7 未达 1.5R → 平仓",
                )
            return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "借方 DTE<7 已达 1.5R 全平")
        # 裸买：不新开；已有仓位盈利 1R 即平；亏损仍按止损 1R
        if pnl_r >= 1.0 - _R_EPS:
            return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "DTE<7 盈利 1R 即平")
        return ExitDecision(ExitAction.HOLD, None, "DTE<7 未达盈利 1R，等待止损/时间")

    # 结构目标 <2R → 1.5R 全平
    full_at_1_5 = structure_target_r < 2.0

    # 借方：§4.2 仅「1.5R 减半 / 2R 全平」，无裸买 7–14 全平档
    # 裸买/Deep ITM：7–14 → 1.5R 全平（不减半）；≥14 → 1.5R 减半
    if strategy != StrategyType.DEBIT_SPREAD and dte < 14:
        if pnl_r >= 1.5 - _R_EPS:
            return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "7–14DTE 1.5R 全平")
        return ExitDecision(ExitAction.HOLD, None)

    # ≥14 裸买，或借方任意 DTE≥7：1.5R 减半；剩余最低 2R 全平（若目标≥2R）
    # 若尚未减半但已跳空至 ≥2R → 直接全平（避免只减半留下已达 2R 的剩余）
    if remaining_fraction >= 0.999:
        if full_at_1_5:
            if pnl_r >= 1.5 - _R_EPS:
                return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "目标<2R → 1.5R 全平")
        else:
            if pnl_r >= 2.0 - _R_EPS:
                return ExitDecision(
                    ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "未减半已达 2R（跳空）全平"
                )
            if pnl_r >= 1.5 - _R_EPS:
                return ExitDecision(ExitAction.CLOSE_HALF, ExitReason.TAKE_HALF, "1.5R 减半")
    else:
        if pnl_r >= 2.0 - _R_EPS:
            return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "剩余 2R 全平")

    return ExitDecision(ExitAction.HOLD, None)


def credit_spread_exit(
    *,
    dte: int,
    pnl_r: float,
    short_leg_distance_atr: float | None = None,
    short_delta: float | None = None,
) -> ExitDecision:
    """信用价差：止盈 = 1R；止损 = 1R；短腿 Delta >0.50 平仓。"""
    if short_delta is not None and abs(short_delta) > 0.50:
        return ExitDecision(
            ExitAction.CLOSE_ALL, ExitReason.STOP_1R, "短腿 Delta >0.50 平仓"
        )
    if pnl_r <= -1.0 + _R_EPS:
        return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.STOP_1R, "信用价差亏损 1R")
    if pnl_r >= 1.0 - _R_EPS:
        return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.TAKE_PROFIT, "信用价差盈利 1R")

    if dte < TIME_STOP_DTE and pnl_r < 1.0 - _R_EPS:
        if short_leg_distance_atr is None:
            # 缺 ATR 不可假设「够远」——保守平仓（§3.5.2）
            return ExitDecision(
                ExitAction.CLOSE_ALL,
                ExitReason.TIME_STOP,
                "DTE<7 未达 1R 且未提供短腿距 ATR → 保守平仓",
            )
        if short_leg_distance_atr < 1.0:
            return ExitDecision(
                ExitAction.CLOSE_ALL,
                ExitReason.TIME_STOP,
                "DTE<7 未达 1R 且短腿距标的 <1 ATR",
            )
        return ExitDecision(ExitAction.HOLD, None, "DTE<7 未达 1R，短腿够远可持有到期")

    return ExitDecision(ExitAction.HOLD, None)


def iv_path_override(
    *,
    iv_entry: float,
    iv_now: float,
    at_structure_target: bool,
) -> ExitDecision | None:
    """标的到目标但 IV 变化。

    - IV 绝对上升 >10 个波动率点 → 继续持有剩余
    - IV 相对下降 >20% → 全平
    """
    if not at_structure_target:
        return None
    abs_up = iv_now - iv_entry
    if abs_up > 10.0:
        return ExitDecision(ExitAction.HOLD, None, "IV 绝对上升 >10 点，继续持有剩余")
    if iv_entry > 0 and (iv_entry - iv_now) / iv_entry >= 0.20:
        return ExitDecision(ExitAction.CLOSE_ALL, ExitReason.IV_CRUSH_EXIT, "IV 相对下降 ≥20% 全平")
    return None


def roll_cost_ok(new_net_debit: float, old_residual: float, original_premium: float) -> bool:
    """滚动成本 = 新净支出 − 旧残值；< 原始权利金 30% 才滚动。"""
    cost = new_net_debit - old_residual
    return cost < original_premium * 0.30
