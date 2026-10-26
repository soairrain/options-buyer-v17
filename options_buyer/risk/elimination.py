"""策略淘汰：滚动 20 笔期望 ≤0 且回撤 >3%。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import ELIMINATION_LOOKBACK, ELIMINATION_MAX_DRAWDOWN


@dataclass(frozen=True)
class TradeResult:
    pnl_r: float
    pnl_pct_equity: float  # 相对账户权益的盈亏比例（可为负）


@dataclass(frozen=True)
class EliminationResult:
    eliminate: bool
    expectancy_r: float
    max_drawdown: float
    n: int
    reason: str = ""


def rolling_expectancy(trades: list[TradeResult], *, lookback: int = ELIMINATION_LOOKBACK) -> float:
    window = trades[-lookback:]
    if not window:
        return 0.0
    return sum(t.pnl_r for t in window) / len(window)


def max_drawdown_pct(trades: list[TradeResult], *, lookback: int = ELIMINATION_LOOKBACK) -> float:
    """按权益百分比累计曲线的最大回撤（正数）。"""
    window = trades[-lookback:]
    if not window:
        return 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in window:
        equity *= 1.0 + t.pnl_pct_equity
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def evaluate_elimination(
    trades: list[TradeResult],
    *,
    lookback: int = ELIMINATION_LOOKBACK,
    max_dd: float = ELIMINATION_MAX_DRAWDOWN,
) -> EliminationResult:
    window = trades[-lookback:]
    n = len(window)
    if n < lookback:
        return EliminationResult(
            False, 0.0, 0.0, n, reason=f"样本不足 {n}/{lookback}"
        )
    exp = rolling_expectancy(trades, lookback=lookback)
    dd = max_drawdown_pct(trades, lookback=lookback)
    if exp <= 0 and dd > max_dd:
        return EliminationResult(
            True,
            exp,
            dd,
            n,
            reason=f"滚动{lookback}笔期望 {exp:.3f}R≤0 且回撤 {dd:.1%}>{max_dd:.0%}",
        )
    return EliminationResult(False, exp, dd, n, reason="未触发淘汰")
