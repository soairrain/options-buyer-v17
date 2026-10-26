"""§5.2 3A 吸收买方步骤机。"""

from __future__ import annotations

from options_buyer.core.branch import choose_branch
from options_buyer.core.gex import GexStructure
from options_buyer.core.liquidity import check_liquidity
from options_buyer.core.r import structure_target_ok
from options_buyer.core.types import OptionQuote, StrategyCategory, StrategyType
from options_buyer.strategies.types import StrategyPlan, StrategyStepResult


def run_absorption_3a(
    *,
    structure: GexStructure,
    near_positive_gamma_level: bool,
    charm_adverse: bool,
    put_flow_fading_or_sto: bool,
    structure_still_active: bool,
    iv_rank: float,
    event_window: bool,
    strong_gex_suppress: bool,
    quote: OptionQuote | None,
    structure_target_r: float,
    negative_gex: bool = False,
) -> StrategyPlan:
    steps: list[StrategyStepResult] = []
    veto: list[str] = []

    if negative_gex or not structure.positive_gex:
        steps.append(
            StrategyStepResult("regime", False, "禁止：负 GEX 做 3A 买方")
        )
    else:
        steps.append(StrategyStepResult("regime", True, "正 GEX 结构位附近"))

    steps.append(
        StrategyStepResult(
            "location",
            near_positive_gamma_level,
            "标的回落至正 Gamma 结构位" if near_positive_gamma_level else "未到结构位",
        )
    )
    steps.append(
        StrategyStepResult(
            "charm",
            not charm_adverse,
            "Charm 窗口 OK" if not charm_adverse else "避开到期日午后 Charm 逆流",
        )
    )
    steps.append(
        StrategyStepResult(
            "flow",
            put_flow_fading_or_sto,
            "BTO Put 衰减或转 STO Put" if put_flow_fading_or_sto else "Put 流未衰减",
        )
    )
    steps.append(
        StrategyStepResult(
            "structure_alive",
            structure_still_active,
            "GEX 重算正 Gamma 仍在"
            if structure_still_active
            else "禁止：结构位消失仍持有/开仓",
        )
    )

    branch = choose_branch(
        iv_rank=iv_rank,
        positive_gex=True,
        event_window=event_window,
        category=StrategyCategory.ABSORPTION_3A,
        strong_gex_suppress=strong_gex_suppress,
    )
    steps.append(StrategyStepResult("branch", True, f"{branch.strategy.value}: {branch.reason}"))

    if quote is not None:
        liq = check_liquidity(quote, deep_itm=branch.strategy == StrategyType.DEEP_ITM)
        steps.append(StrategyStepResult("liquidity", liq.ok, liq.reason))
        delta_ok = branch.delta_lo <= abs(quote.delta) <= branch.delta_hi
        dte_ok = branch.dte_lo <= quote.dte <= branch.dte_hi
        steps.append(
            StrategyStepResult("delta_dte", delta_ok and dte_ok, f"δ={quote.delta} dte={quote.dte}")
        )
    else:
        steps.append(StrategyStepResult("liquidity", False, "未提供合约报价"))

    tgt_ok = structure_target_ok(structure_target_r, branch.strategy)
    steps.append(StrategyStepResult("target", tgt_ok, f"结构目标 {structure_target_r}R"))

    allowed = all(s.ok for s in steps) and not veto
    return StrategyPlan(
        category=StrategyCategory.ABSORPTION_3A,
        allowed=allowed,
        strategy=branch.strategy if allowed else None,
        branch=branch,
        structure_target_r=structure_target_r,
        steps=steps,
        veto_reasons=veto,
    )
