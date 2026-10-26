"""§3.2 体制层：顺风 / 逆风判定。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from options_buyer.core.gex import GexStructure


class RegimeBias(str, Enum):
    MEAN_REVERT = "mean_revert"  # 正 GEX：抑制波动
    MOMENTUM = "momentum"  # 负 GEX：放大波动
    MIXED = "mixed"
    NO_TRADE = "no_trade"


@dataclass(frozen=True)
class RegimeDecision:
    bias: RegimeBias
    positive_gex: bool
    price_vs_zg: str
    charm_adverse: bool
    size_multiplier: float
    prefer_spread: bool
    naked_delta_lo: float
    naked_delta_hi: float
    naked_dte_lo: int
    naked_dte_hi: int
    reasons: tuple[str, ...]
    allow_new: bool


def in_charm_window(*, us_eastern_hour: float, is_expiry_day: bool) -> bool:
    """到期日午后美东 14:00–16:00 Charm 可能压过 Gamma。"""
    return is_expiry_day and 14.0 <= us_eastern_hour < 16.0


def evaluate_regime(
    structure: GexStructure,
    *,
    risk_reversal_sign: float | None = None,
    # RR：正=偏多（call 贵/put 便宜），负=偏空；与 GEX 矛盾时以 RR 为准作否决
    gex_implies_long: bool | None = None,
    charm_adverse: bool = False,
    us_eastern_hour: float | None = None,
    is_expiry_day: bool = False,
    put_skew_steep: bool = False,
) -> RegimeDecision:
    reasons: list[str] = []
    pos = structure.positive_gex
    vs = structure.price_vs_zero_gamma()

    if us_eastern_hour is not None and in_charm_window(
        us_eastern_hour=us_eastern_hour, is_expiry_day=is_expiry_day
    ):
        charm_adverse = True
        reasons.append("到期日午后 Charm 窗口")

    # RR 否决层
    rr_veto = False
    if risk_reversal_sign is not None and gex_implies_long is not None:
        rr_long = risk_reversal_sign > 0
        if rr_long != gex_implies_long:
            rr_veto = True
            reasons.append("RR 与 GEX 矛盾，以 RR 为准 → 否决/降级")

    if pos:
        bias = RegimeBias.MEAN_REVERT
        prefer_spread = True
        # 正 GEX：裸买降低目标 Delta 0.40–0.50，DTE 30–45；或改价差
        d_lo, d_hi, t_lo, t_hi = 0.40, 0.50, 30, 45
        reasons.append("正 GEX：结构位可信但权利金涨幅受抑 → 优先价差/实值")
    else:
        bias = RegimeBias.MOMENTUM
        prefer_spread = False
        d_lo, d_hi, t_lo, t_hi = 0.30, 0.50, 21, 45
        reasons.append("负 GEX：结构位变加速触发，动量买方优先")

    size_mult = 1.0
    if charm_adverse:
        size_mult = 0.5
        reasons.append("Charm 逆流：不新开或仓位减半（size×0.5）")

    if rr_veto:
        bias = RegimeBias.NO_TRADE
        allow_new = False  # RR 硬否决，不可被 Charm 减半路径翻回
    else:
        # Charm：允许以减半仓新开；无 Charm 则正常开
        allow_new = True

    if put_skew_steep:
        reasons.append("Put Skew 陡峭：买 Put 需更严价格过滤")

    if vs == "above" and not pos:
        reasons.append("价格在 Zero Gamma 上方但净 GEX 仍偏负 → 混合体制")
        if bias != RegimeBias.NO_TRADE:
            bias = RegimeBias.MIXED

    return RegimeDecision(
        bias=bias,
        positive_gex=pos,
        price_vs_zg=vs,
        charm_adverse=charm_adverse,
        size_multiplier=size_mult,
        prefer_spread=prefer_spread,
        naked_delta_lo=d_lo,
        naked_delta_hi=d_hi,
        naked_dte_lo=t_lo,
        naked_dte_hi=t_hi,
        reasons=tuple(reasons),
        allow_new=allow_new,
    )
