"""同方向高相关仓位合计权利金跟踪（第九章）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.types import CORRELATED_PREMIUM_MAX, CORRELATION_THRESHOLD


@dataclass
class OpenRiskLeg:
    symbol: str
    direction: int  # +1 看多 / -1 看空
    premium_usd: float
    category: str = ""
    position_id: str = ""


@dataclass
class CorrelationBook:
    """静态相关矩阵 + 开仓腿。"""

    pairwise: dict[tuple[str, str], float] = field(default_factory=dict)
    legs: list[OpenRiskLeg] = field(default_factory=list)

    def set_corr(self, a: str, b: str, rho: float) -> None:
        if a > b:
            a, b = b, a
        self.pairwise[(a, b)] = rho

    def corr(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        if a > b:
            a, b = b, a
        return self.pairwise.get((a, b), 0.0)

    def correlated_premium_pct(
        self,
        *,
        equity: float,
        symbol: str,
        direction: int,
        new_premium: float = 0.0,
        threshold: float = CORRELATION_THRESHOLD,
    ) -> float:
        """与 symbol 同向且 |ρ|>threshold 的开仓权利金合计（含拟开新仓）/ 权益。"""
        if equity <= 0:
            return 1.0
        total = new_premium
        for leg in self.legs:
            if leg.direction != direction:
                continue
            if self.corr(symbol, leg.symbol) > threshold or leg.symbol == symbol:
                total += leg.premium_usd
        return total / equity

    def allows(
        self,
        *,
        equity: float,
        symbol: str,
        direction: int,
        new_premium: float,
        max_pct: float = CORRELATED_PREMIUM_MAX,
    ) -> tuple[bool, float]:
        pct = self.correlated_premium_pct(
            equity=equity, symbol=symbol, direction=direction, new_premium=new_premium
        )
        return pct <= max_pct + 1e-12, pct
