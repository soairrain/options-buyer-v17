"""§5.3 均值回归——信用价差或标的，不裸买。"""

from __future__ import annotations

from options_buyer.core.branch import choose_branch
from options_buyer.core.gex import GexStructure
from options_buyer.core.liquidity import check_liquidity
from options_buyer.core.r import structure_target_ok
from options_buyer.core.spreads import validate_credit_spread
from options_buyer.core.types import OptionQuote, StrategyCategory, StrategyType
from options_buyer.strategies.types import StrategyPlan, StrategyStepResult


def run_mean_reversion(
    *,
    structure: GexStructure,
    price_between_walls: bool,
    side: str,  # "bear_call" | "bull_put"
    short_strike: float,
    wall_strike: float,
    short_outside_wall_steps: int,
    step_width: float,
    target_price: float,
    width: float,
    credit: float,
    short_quote: OptionQuote | None,
    protect_quote: OptionQuote | None,
    iv_rank: float,
    event_window: bool,
    structure_target_r: float = 1.0,
) -> StrategyPlan:
    steps: list[StrategyStepResult] = []
    veto: list[str] = []

    steps.append(
        StrategyStepResult(
            "regime",
            structure.positive_gex and price_between_walls,
            "正 GEX + 价格在 Call/Put Wall 之间"
            if structure.positive_gex and price_between_walls
            else "体制不符",
        )
    )

    # 短腿在墙体外侧 1–2 档
    if side == "bear_call":
        outside = short_strike >= wall_strike + 1 * step_width
        target_inside = target_price < short_strike
    else:
        outside = short_strike <= wall_strike - 1 * step_width
        target_inside = target_price > short_strike

    steps.append(
        StrategyStepResult(
            "short_placement",
            outside and 1 <= short_outside_wall_steps <= 2,
            f"短腿墙体外侧 {short_outside_wall_steps} 档",
        )
    )
    steps.append(
        StrategyStepResult(
            "target_inside",
            target_inside,
            "目标在短腿内侧" if target_inside else "目标在短腿外侧 → 改更远短腿或放弃",
        )
    )

    branch = choose_branch(
        iv_rank=iv_rank,
        positive_gex=True,
        event_window=event_window,
        category=StrategyCategory.MEAN_REVERSION,
    )
    assert branch.strategy == StrategyType.CREDIT_SPREAD
    steps.append(StrategyStepResult("no_naked", True, "均值回归不裸买 → 信用价差"))

    if short_quote is not None and protect_quote is not None:
        build = validate_credit_spread(
            short_delta=short_quote.delta,
            protect_delta=protect_quote.delta,
            width=width,
            net_credit=credit,
        )
        steps.append(StrategyStepResult("credit_build", build.ok, build.reason))
        liq_s = check_liquidity(short_quote)
        steps.append(StrategyStepResult("liq_short", liq_s.ok, liq_s.reason))
        delta_ok = 0.20 <= abs(short_quote.delta) <= 0.30
        dte_ok = 14 <= short_quote.dte <= 45
        steps.append(
            StrategyStepResult(
                "delta_dte",
                delta_ok and dte_ok,
                f"短腿 δ={short_quote.delta} dte={short_quote.dte}",
            )
        )
        liq_p = check_liquidity(protect_quote, protect_leg=True)
        steps.append(StrategyStepResult("liq_protect", liq_p.ok, liq_p.reason))
    else:
        steps.append(StrategyStepResult("credit_build", False, "缺短腿/保护腿报价"))
        steps.append(StrategyStepResult("liq_short", False, "缺短腿报价"))
        steps.append(StrategyStepResult("liq_protect", False, "缺保护腿报价"))

    tgt_ok = structure_target_ok(structure_target_r, StrategyType.CREDIT_SPREAD)
    steps.append(StrategyStepResult("target_r", tgt_ok, f"结构目标 {structure_target_r}R（信用≥1）"))

    allowed = all(s.ok for s in steps) and not veto
    return StrategyPlan(
        category=StrategyCategory.MEAN_REVERSION,
        allowed=allowed,
        strategy=StrategyType.CREDIT_SPREAD if allowed else None,
        branch=branch,
        structure_target_r=structure_target_r,
        steps=steps,
        veto_reasons=veto,
    )
