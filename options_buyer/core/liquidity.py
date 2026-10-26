"""3.4.3 流动性硬过滤。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import OptionQuote


@dataclass(frozen=True)
class LiquidityResult:
    ok: bool
    reason: str = ""


def check_liquidity(
    q: OptionQuote,
    *,
    deep_itm: bool = False,
    protect_leg: bool = False,
    near_open_close_15m: bool = False,
) -> LiquidityResult:
    spread = q.spread
    pct = q.spread_pct

    if deep_itm:
        if not (spread <= 0.20 or pct <= 0.10):
            return LiquidityResult(False, "Deep ITM 价差不达标")
        if q.oi < 200 or q.volume < 50:
            return LiquidityResult(False, "Deep ITM OI/成交量不达标")
        return LiquidityResult(True, "ok")

    if protect_leg:
        if not (spread <= 0.10 or pct <= 0.20):
            return LiquidityResult(False, "保护腿价差不达标")
        # 仍要求基础 OI/量
        if q.oi < 500 or q.volume < 100:
            return LiquidityResult(False, "保护腿 OI/成交量不达标")
        return LiquidityResult(True, "ok")

    # 标准腿：价差 < $0.10 或比例 < 15%；> $0.50 或 > 20% 剔除
    if spread > 0.50 or pct > 0.20:
        return LiquidityResult(False, "价差过大，剔除")
    if not (spread < 0.10 or pct < 0.15):
        return LiquidityResult(False, "价差未达硬过滤")

    if q.oi < 500 or q.volume < 100:
        return LiquidityResult(False, "OI≥500 且日成交量≥100 未满足")

    if near_open_close_15m:
        if not (pct <= 0.10 and spread <= 0.15):
            return LiquidityResult(False, "开盘/收盘前 15 分钟流动性不达标")

    return LiquidityResult(True, "ok")


def pick_best_contract(
    quotes: list[OptionQuote],
    *,
    target_delta: float,
    target_vega: float | None = None,
) -> OptionQuote | None:
    """冲突解决：价差最小 → OI 最大 → 最接近目标 Delta → Vega 最接近目标。"""
    if not quotes:
        return None

    def key(q: OptionQuote):
        vega_dist = abs(q.vega - target_vega) if target_vega is not None else 0.0
        return (q.spread, -q.oi, abs(q.delta - target_delta), vega_dist)

    return sorted(quotes, key=key)[0]
