"""§5.1 突破/趋势买方步骤机。"""

from __future__ import annotations

from options_buyer.core.branch import choose_branch
from options_buyer.core.gex import GexStructure
from options_buyer.core.liquidity import check_liquidity
from options_buyer.core.r import structure_target_ok
from options_buyer.core.trigger import TriggerDecision
from options_buyer.core.types import OptionQuote, StrategyCategory, StrategyType
from options_buyer.strategies.types import StrategyPlan, StrategyStepResult


def run_breakout(
    *,
    structure: GexStructure,
    negative_gex_or_below_zg: bool,
    broke_5m_close: bool,
    trigger: TriggerDecision,
    iv_rank: float,
    event_window: bool,
    quote: OptionQuote | None,
    structure_target_r: float,
    chase_without_close: bool = False,
) -> StrategyPlan:
    steps: list[StrategyStepResult] = []
    veto: list[str] = []

    steps.append(
        StrategyStepResult(
            "regime",
            negative_gex_or_below_zg,
            "负 GEX 或已穿越 Zero Gamma 进入负 Gamma 区"
            if negative_gex_or_below_zg
            else "体制不符：突破买方需负 GEX/负 Gamma 区",
        )
    )
    steps.append(
        StrategyStepResult(
            "levels",
            structure.call_wall is not None or structure.put_wall is not None,
            "已标记 Call/Put Wall / Zero Gamma",
        )
    )
    steps.append(
        StrategyStepResult(
            "break_5m",
            broke_5m_close and not chase_without_close,
            "5 分钟收盘突破"
            if broke_5m_close and not chase_without_close
            else "禁止：突破未收盘追买",
        )
    )
    steps.append(
        StrategyStepResult(
            "trigger",
            trigger.fired and not trigger.degraded,
            "BTO 净 Delta + V/OI≥1"
            if trigger.fired and not trigger.degraded
            else f"触发失败/降级: {'; '.join(trigger.reasons)}",
        )
    )

    branch = choose_branch(
        iv_rank=iv_rank,
        positive_gex=structure.positive_gex,
        event_window=event_window,
        category=StrategyCategory.BREAKOUT,
    )
    # 禁止 IVR>50 裸买虚值
    if iv_rank > 50 and branch.strategy == StrategyType.LONG:
        veto.append("禁止：IV Rank >50 裸买虚值")
        branch = choose_branch(
            iv_rank=iv_rank,
            positive_gex=False,
            event_window=event_window,
            category=StrategyCategory.BREAKOUT,
            want_naked_despite_high_iv=False,
        )

    steps.append(
        StrategyStepResult(
            "branch",
            True,
            f"{branch.strategy.value}: {branch.reason}",
        )
    )

    if quote is not None:
        liq = check_liquidity(quote, deep_itm=branch.strategy == StrategyType.DEEP_ITM)
        steps.append(StrategyStepResult("liquidity", liq.ok, liq.reason))
        delta_ok = branch.delta_lo <= abs(quote.delta) <= branch.delta_hi
        dte_ok = branch.dte_lo <= quote.dte <= branch.dte_hi
        steps.append(
            StrategyStepResult(
                "delta_dte",
                delta_ok and dte_ok,
                f"delta={quote.delta:.2f} dte={quote.dte}",
            )
        )
        if quote.dte < 7 and branch.strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
            steps.append(
                StrategyStepResult("dte7", False, "禁止：到期 <7 天新开裸买")
            )
    else:
        steps.append(StrategyStepResult("liquidity", False, "未提供合约报价"))

    tgt_ok = structure_target_ok(structure_target_r, branch.strategy)
    steps.append(
        StrategyStepResult(
            "target",
            tgt_ok,
            f"结构目标 {structure_target_r}R" + ("" if tgt_ok else " 不足"),
        )
    )

    allowed = all(s.ok for s in steps) and not veto
    return StrategyPlan(
        category=StrategyCategory.BREAKOUT,
        allowed=allowed,
        strategy=branch.strategy if allowed else None,
        branch=branch,
        structure_target_r=structure_target_r,
        size_multiplier=0.5 if trigger.degraded else 1.0,
        steps=steps,
        veto_reasons=veto,
    )
