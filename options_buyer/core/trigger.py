"""§3.3 触发层：客户流 + 价格确认（不能单独使用）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FlowSide(str, Enum):
    BTO_CALL = "bto_call"
    STO_CALL = "sto_call"
    BTO_PUT = "bto_put"
    STO_PUT = "sto_put"
    OTHER = "other"


@dataclass(frozen=True)
class FlowPrint:
    strike: float
    side: FlowSide
    contracts: int
    delta: float
    volume: int
    oi: int

    @property
    def voi(self) -> float:
        return self.volume / self.oi if self.oi > 0 else 0.0

    @property
    def signed_delta(self) -> float:
        """聚合净 Delta：BTO Call / STO Put 为正（偏多期权流）。"""
        d = abs(self.delta) * self.contracts
        if self.side in (FlowSide.BTO_CALL, FlowSide.STO_PUT):
            return d
        if self.side in (FlowSide.STO_CALL, FlowSide.BTO_PUT):
            return -d
        return 0.0


@dataclass
class TriggerDecision:
    fired: bool
    degraded: bool = False
    reasons: list[str] = field(default_factory=list)
    net_bto_delta: float = 0.0
    max_voi: float = 0.0


def aggregate_flow(
    prints: list[FlowPrint],
    *,
    target_strike: float,
    strike_band: float = 2.0,
) -> tuple[float, float, float, float]:
    """返回 (net_delta, bto_call_delta, sto_call_delta, max_voi)。"""
    net = bto = sto = 0.0
    max_voi = 0.0
    for p in prints:
        if abs(p.strike - target_strike) > strike_band:
            continue
        max_voi = max(max_voi, p.voi)
        sd = p.signed_delta
        net += sd
        if p.side == FlowSide.BTO_CALL:
            bto += abs(p.delta) * p.contracts
        elif p.side == FlowSide.STO_CALL:
            sto += abs(p.delta) * p.contracts
    return net, bto, sto, max_voi


def evaluate_trigger(
    *,
    direction: str,  # "long_underlying" | "short_underlying"
    structure_active: bool,
    near_structure: bool,
    prints: list[FlowPrint],
    target_strike: float,
    strike_band: float = 2.0,
    min_net_delta: float = 50.0,
    price_held: bool = True,
    flow_flipped: bool = False,
    negative_gex: bool = True,
) -> TriggerDecision:
    """做多标的买 Call 为例的触发条件。"""
    reasons: list[str] = []
    if not structure_active:
        return TriggerDecision(False, reasons=["结构位不活跃"])
    if not near_structure:
        return TriggerDecision(False, reasons=["标的未接近结构位"])

    net, bto, sto, max_voi = aggregate_flow(
        prints, target_strike=target_strike, strike_band=strike_band
    )

    # 同窗口大规模 STO Call 抵消 BTO
    degraded = False
    if sto > 0 and bto > 0 and sto >= 0.5 * bto:
        degraded = True
        reasons.append("同窗口 STO Call 抵消 BTO → 降级")

    if max_voi < 1.0:
        return TriggerDecision(
            False, degraded=degraded, reasons=reasons + ["V/OI < 1"], net_bto_delta=net, max_voi=max_voi
        )

    if direction == "long_underlying":
        flow_ok = net >= min_net_delta
        if not flow_ok:
            return TriggerDecision(
                False,
                degraded=degraded,
                reasons=reasons + [f"BTO 净 Delta {net:.1f} < {min_net_delta}"],
                net_bto_delta=net,
                max_voi=max_voi,
            )
    else:
        flow_ok = net <= -min_net_delta
        if not flow_ok:
            return TriggerDecision(
                False,
                degraded=degraded,
                reasons=reasons + [f"空头侧净 Delta {net:.1f} 不足"],
                net_bto_delta=net,
                max_voi=max_voi,
            )

    if not price_held:
        return TriggerDecision(
            False,
            degraded=degraded,
            reasons=reasons + ["价格未守住结构位内侧"],
            net_bto_delta=net,
            max_voi=max_voi,
        )

    if flow_flipped:
        return TriggerDecision(
            False,
            degraded=True,
            reasons=reasons + ["期权侧 BTO 流转为 STO Call / BTO Put"],
            net_bto_delta=net,
            max_voi=max_voi,
        )

    # 关键原则：正 Gamma 环境同样 BTO 可能抑制上行
    if not negative_gex:
        reasons.append("正 GEX 环境：触发层不可单独使用，需体制层确认")
        # 仍可 fired，但 degraded
        degraded = True

    if degraded:
        reasons.append("信号降级：可减小仓位或改价差")

    reasons.append("触发条件满足")
    return TriggerDecision(
        fired=True, degraded=degraded, reasons=reasons, net_bto_delta=net, max_voi=max_voi
    )
