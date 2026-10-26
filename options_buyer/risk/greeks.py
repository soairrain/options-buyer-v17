"""第七章组合 Greeks 监控。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import (
    MULTIPLIER,
    NET_DELTA_MAX,
    NET_THETA_WARN,
    NET_VEGA_MAX,
    StrategyType,
)


@dataclass
class LegGreeks:
    delta: float
    vega: float
    theta: float
    gamma: float = 0.0
    contracts: int = 1
    strategy: StrategyType = StrategyType.LONG
    spot: float = 0.0


@dataclass(frozen=True)
class PortfolioGreeks:
    net_delta_usd: float
    net_vega_usd: float
    net_theta: float
    net_gamma: float
    ok: bool  # Delta/Vega 硬限；True 时仍可能 block_new_buyer
    block_new_buyer: bool  # 净 Theta>0 → 不加买方仓位（信用仍可）
    reasons: tuple[str, ...]


def _weight(strategy: StrategyType) -> float:
    # 价差仓位按 50% 折算；裸买 100%
    if strategy in (StrategyType.DEBIT_SPREAD, StrategyType.CREDIT_SPREAD):
        return 0.5
    return 1.0


def aggregate(legs: list[LegGreeks], equity: float) -> PortfolioGreeks:
    nd = nv = nt = ng = 0.0
    for leg in legs:
        w = _weight(leg.strategy)
        m = leg.contracts * MULTIPLIER * w
        nd += leg.delta * m * leg.spot
        nv += leg.vega * m
        nt += leg.theta * m
        ng += leg.gamma * m

    reasons: list[str] = []
    hard_fail = False
    block_buyer = False
    if abs(nd) > equity * NET_DELTA_MAX:
        reasons.append(f"净 Delta 美元敞口 {nd:.0f} 超过账户 10%")
        hard_fail = True
    if abs(nv) > equity * NET_VEGA_MAX:
        reasons.append(f"净 Vega {nv:.0f} 超过账户 0.5%/IV点")
        hard_fail = True
    if nt > 0:
        reasons.append("净 Theta 为正，不加买方仓位（信用价差仍可开）")
        block_buyer = True
    elif abs(nt) > equity * NET_THETA_WARN:
        reasons.append("净 Theta 负向超过账户 0.1%/天，检查过度持有")

    return PortfolioGreeks(
        nd,
        nv,
        nt,
        ng,
        ok=not hard_fail,
        block_new_buyer=block_buyer,
        reasons=tuple(reasons),
    )
