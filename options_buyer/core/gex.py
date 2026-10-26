"""§3.1 结构层：GEX 墙体 / Zero Gamma / Max Pain / VW-GEX。

输入为按行权价汇总的 gamma 敞口（可由 OI×gamma×乘数×符号 预计算后传入）。
盘中每 10–60 秒由调用方重算后传入本模块做墙体判定。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrikeGex:
    strike: float
    call_gex: float = 0.0  # 正值通常抑制上行
    put_gex: float = 0.0  # 负值常放大下行
    call_oi: int = 0
    put_oi: int = 0
    call_volume: int = 0
    put_volume: int = 0

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex

    @property
    def abs_gex(self) -> float:
        return abs(self.call_gex) + abs(self.put_gex)


@dataclass
class GexStructure:
    spot: float
    call_wall: float | None = None
    put_wall: float | None = None
    zero_gamma: float | None = None
    max_gamma_strike: float | None = None
    max_pain: float | None = None
    net_gex_total: float = 0.0
    positive_gex: bool = False
    active_walls: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def wall_active(self, name: str) -> bool:
        return name in self.active_walls

    def price_vs_zero_gamma(self) -> str:
        if self.zero_gamma is None:
            return "unknown"
        if self.spot > self.zero_gamma:
            return "above"
        if self.spot < self.zero_gamma:
            return "below"
        return "at"


def vw_gex_weight(volume: int, oi: int) -> float:
    """VW-GEX：过滤僵尸 Gamma，只保留当日仍在交易的活跃墙体。"""
    if oi <= 0:
        return 0.0
    voi = volume / oi
    # V/OI≥1 全权；否则按比例衰减，最低保留 10% 以免完全抹掉
    return max(0.10, min(1.0, voi))


def weighted_strikes(rows: list[StrikeGex], *, use_vw: bool = True) -> list[StrikeGex]:
    out: list[StrikeGex] = []
    for r in rows:
        if not use_vw:
            out.append(r)
            continue
        wc = vw_gex_weight(r.call_volume, r.call_oi)
        wp = vw_gex_weight(r.put_volume, r.put_oi)
        out.append(
            StrikeGex(
                strike=r.strike,
                call_gex=r.call_gex * wc,
                put_gex=r.put_gex * wp,
                call_oi=r.call_oi,
                put_oi=r.put_oi,
                call_volume=r.call_volume,
                put_volume=r.put_volume,
            )
        )
    return out


def find_call_wall(rows: list[StrikeGex], *, spot: float) -> float | None:
    """正 GEX 最集中上方行权价。"""
    above = [r for r in rows if r.strike >= spot and r.call_gex > 0]
    if not above:
        return None
    return max(above, key=lambda r: r.call_gex).strike


def find_put_wall(rows: list[StrikeGex], *, spot: float) -> float | None:
    """负 GEX（put 侧）最集中下方行权价。"""
    below = [r for r in rows if r.strike <= spot]
    if not below:
        return None
    # put_gex 通常为负；取绝对值最大
    return min(below, key=lambda r: r.put_gex).strike


def find_zero_gamma(rows: list[StrikeGex], *, spot: float) -> float | None:
    """总 GEX 符号翻转的标的价位（按 strike 排序后找变号）。"""
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda r: r.strike)
    # 累积净 GEX 从低到高，找穿越 0 的区间
    cum = 0.0
    prev_strike = ordered[0].strike
    prev_cum = 0.0
    for r in ordered:
        cum += r.net_gex
        if prev_cum == 0 and cum == 0:
            prev_strike = r.strike
            prev_cum = cum
            continue
        if prev_cum * cum < 0 or (prev_cum == 0 and cum != 0):
            # 线性插值
            if cum == prev_cum:
                return r.strike
            t = abs(prev_cum) / (abs(prev_cum) + abs(cum))
            return prev_strike + (r.strike - prev_strike) * t
        prev_strike = r.strike
        prev_cum = cum
    # 回退：距现价最近且净 GEX 绝对值最小的 strike
    return min(ordered, key=lambda r: (abs(r.net_gex), abs(r.strike - spot))).strike


def find_max_gamma_strike(rows: list[StrikeGex]) -> float | None:
    if not rows:
        return None
    return max(rows, key=lambda r: r.abs_gex).strike


def estimate_max_pain(rows: list[StrikeGex]) -> float | None:
    """简化 Max Pain：使 call+put 内在价值支付最小的 strike（仅指数/ETF 参考）。"""
    if not rows:
        return None
    strikes = [r.strike for r in rows]

    def pain_at(s: float) -> float:
        total = 0.0
        for r in rows:
            total += max(0.0, s - r.strike) * r.call_oi
            total += max(0.0, r.strike - s) * r.put_oi
        return total

    return min(strikes, key=pain_at)


def build_structure(
    rows: list[StrikeGex],
    *,
    spot: float,
    use_vw: bool = True,
    include_max_pain: bool = True,
    previous: GexStructure | None = None,
) -> GexStructure:
    wrows = weighted_strikes(rows, use_vw=use_vw)
    net = sum(r.net_gex for r in wrows)
    call_wall = find_call_wall(wrows, spot=spot)
    put_wall = find_put_wall(wrows, spot=spot)
    zg = find_zero_gamma(wrows, spot=spot)
    mgs = find_max_gamma_strike(wrows)
    mp = estimate_max_pain(wrows) if include_max_pain else None

    active: dict[str, float] = {}
    notes: list[str] = []
    if call_wall is not None:
        active["call_wall"] = call_wall
    if put_wall is not None:
        active["put_wall"] = put_wall
    if zg is not None:
        active["zero_gamma"] = zg
    if mgs is not None:
        active["max_gamma_strike"] = mgs

    # 墙体消失：相对上一快照
    if previous is not None:
        for name, prev_k in previous.active_walls.items():
            if name not in active:
                notes.append(f"结构失效：{name}@{prev_k} 在重算中消失")
            elif abs(active[name] - prev_k) / max(prev_k, 1e-9) > 0.02:
                notes.append(f"{name} 从 {prev_k} 漂移至 {active[name]}")

    return GexStructure(
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        zero_gamma=zg,
        max_gamma_strike=mgs,
        max_pain=mp,
        net_gex_total=net,
        positive_gex=net >= 0,
        active_walls=active,
        notes=notes,
    )


def structure_invalidated(current: GexStructure, *, required: str = "call_wall") -> bool:
    """墙体在盘中重算中消失 → 相关信号放弃。"""
    return required not in current.active_walls or any("消失" in n for n in current.notes)


def shift_toward_atm(
    target_strike: float,
    *,
    spot: float,
    steps: int = 1,
    step_width: float = 1.0,
) -> float:
    """流动性不达标时向平值偏离 1–2 档；不得向虚值偏离。"""
    if target_strike >= spot:
        # call 侧墙体：向 ATM 下移
        return max(spot, target_strike - steps * step_width)
    # put 侧：向 ATM 上移
    return min(spot, target_strike + steps * step_width)


def deviation_crosses_structure(
    original: float,
    shifted: float,
    *,
    call_wall: float | None,
    zero_gamma: float | None,
) -> bool:
    """偏离后结构含义改变（跨过 Call Wall / Zero Gamma）→ 放弃。"""
    for barrier in (call_wall, zero_gamma):
        if barrier is None:
            continue
        if (original - barrier) * (shifted - barrier) < 0:
            return True
    return False
