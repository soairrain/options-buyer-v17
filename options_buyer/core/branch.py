"""3.4.0 / 4.1 策略分支：裸买 / 借方 / 信用 / Deep ITM。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import StrategyCategory, StrategyType


@dataclass(frozen=True)
class BranchDecision:
    strategy: StrategyType
    delta_lo: float
    delta_hi: float
    dte_lo: int
    dte_hi: int
    reason: str
    allow_naked: bool


def choose_branch(
    *,
    iv_rank: float,
    positive_gex: bool,
    event_window: bool,
    category: StrategyCategory,
    want_naked_despite_high_iv: bool = False,
    strong_gex_suppress: bool = False,
) -> BranchDecision:
    if event_window:
        return BranchDecision(
            StrategyType.DEBIT_SPREAD,
            0.50,
            0.60,
            30,
            45,
            "事件窗口禁止新开裸买 → 借方价差",
            False,
        )

    if category == StrategyCategory.MEAN_REVERSION:
        return BranchDecision(
            StrategyType.CREDIT_SPREAD,
            0.20,
            0.30,
            21,
            45,
            "均值回归 → 信用价差（不裸买）",
            False,
        )

    if iv_rank > 50:
        if want_naked_despite_high_iv:
            return BranchDecision(
                StrategyType.DEEP_ITM,
                0.70,
                0.80,
                30,
                60,
                "IVR>50 仍想裸买 → Deep ITM",
                True,
            )
        return BranchDecision(
            StrategyType.DEBIT_SPREAD,
            0.50,
            0.60,
            30,
            45,
            "IVR>50 禁止裸买平值/虚值 → 借方价差",
            False,
        )

    if positive_gex and category != StrategyCategory.ABSORPTION_3A:
        # 正 GEX 抑制：优先价差
        return BranchDecision(
            StrategyType.DEBIT_SPREAD,
            0.50,
            0.60,
            30,
            45,
            "正 GEX 抑制波动 → 借方价差",
            False,
        )

    if category == StrategyCategory.BREAKOUT:
        # §5.1：IVR<50 裸买；IVR>50 已在上方处理。IVR==50 落在 30–50 → 优先价差
        if iv_rank < 50:
            return BranchDecision(
                StrategyType.LONG,
                0.30,
                0.50,
                21,
                45,
                "突破/趋势裸买",
                True,
            )
        return BranchDecision(
            StrategyType.DEBIT_SPREAD,
            0.50,
            0.60,
            30,
            45,
            "突破但 IVR≥50 边界 → 借方价差",
            False,
        )

    if category == StrategyCategory.ABSORPTION_3A:
        # 3A 常态就在正 GEX；仅 IVR>50 或明确「强抑制」才改价差（§5.2）
        if iv_rank > 50 or strong_gex_suppress:
            return BranchDecision(
                StrategyType.DEBIT_SPREAD,
                0.50,
                0.60,
                30,
                45,
                "3A + IVR>50/强正GEX抑制 → 牛市价差",
                False,
            )
        return BranchDecision(
            StrategyType.LONG,
            0.50,
            0.70,
            14,
            30,
            "3A 吸收裸买（正 GEX 结构位，IVR≤50）",
            True,
        )

    if iv_rank < 30:
        return BranchDecision(StrategyType.LONG, 0.30, 0.50, 21, 45, "IVR<30 裸买", True)

    # 30–50
    return BranchDecision(
        StrategyType.DEBIT_SPREAD,
        0.50,
        0.60,
        30,
        45,
        "IVR 30–50 优先价差",
        False,
    )


def delta_in_range(delta: float, lo: float, hi: float) -> bool:
    return lo <= abs(delta) <= hi
