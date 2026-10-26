"""3.4.2 IV Crush 事前期望值估算。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import IV_CRUSH_MIN_RATIO, MULTIPLIER


@dataclass(frozen=True)
class IVCrushEstimate:
    delta_contrib: float
    vega_contrib: float
    theta_contrib: float
    slip_commission: float
    net: float
    premium_total: float
    ok: bool
    reason: str = ""


def estimate_iv_crush(
    *,
    expected_underlying_move: float,
    delta: float,
    expected_iv_change_points: float,
    vega: float,
    hold_days: float,
    daily_theta: float,
    half_spread: float,
    commission: float,
    contracts: int,
    premium_quote: float,
    spot: float | None = None,
    gamma: float = 0.0,
    apply_gamma_correction: bool = False,
    expected_move_pct: float | None = None,
) -> IVCrushEstimate:
    """净期望 = Delta + Vega + Theta(负) + 滑点佣金(负)。

    净期望 < 权利金 20% → 放弃。
    Vega 贡献为负且 |Vega| > 30% × Delta → 否决裸买（由调用方处理）。
    """
    n = contracts * MULTIPLIER
    premium_total = premium_quote * n

    if apply_gamma_correction and spot is not None and expected_move_pct is not None:
        # 非线性 Delta ≈ ΔS × Delta + 0.5 × Γ × (S × Δ%)² × 100（文档公式）
        # 这里对整仓：乘张数；文档写 ×100 已体现在乘数语义中
        ds = expected_underlying_move
        nonlinear = ds * delta + 0.5 * gamma * (spot * expected_move_pct) ** 2
        delta_contrib = nonlinear * n
    else:
        delta_contrib = expected_underlying_move * delta * n
        # 未做 Gamma 修正 → 净期望打 20% 安全折扣（在 net 上处理）

    vega_contrib = expected_iv_change_points * vega * n
    theta_contrib = hold_days * daily_theta * n  # theta 通常为负
    slip = half_spread * n * 2 + commission  # 往返
    slip_commission = -abs(slip)

    net = delta_contrib + vega_contrib + theta_contrib + slip_commission
    if not apply_gamma_correction:
        net *= 0.80

    ok = net >= premium_total * IV_CRUSH_MIN_RATIO
    reason = "ok" if ok else f"净期望 {net:.2f} < 权利金 20% ({premium_total * IV_CRUSH_MIN_RATIO:.2f})"

    # Vega 否决提示
    if vega_contrib < 0 and abs(vega_contrib) > 0.30 * max(delta_contrib, 1e-9):
        reason = "Vega 逆风超过 Delta 贡献 30%，不用裸买，改价差或 Deep ITM"
        ok = False

    return IVCrushEstimate(
        delta_contrib=delta_contrib,
        vega_contrib=vega_contrib,
        theta_contrib=theta_contrib,
        slip_commission=slip_commission,
        net=net,
        premium_total=premium_total,
        ok=ok,
        reason=reason,
    )
