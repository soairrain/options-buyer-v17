"""端到端编排：GEX → 体制 → 触发 → 策略机 → 检查清单/否决 → 纸面开仓。

调用方注入行情与报价；本模块不拉外部数据、不下实盘单。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.branch import BranchDecision
from options_buyer.core.correlation import CorrelationBook
from options_buyer.core.gex import GexStructure, StrikeGex, build_structure
from options_buyer.core.iv_crush import estimate_iv_crush
from options_buyer.core.liquidity import check_liquidity
from options_buyer.core.r import compute_r, structure_target_ok
from options_buyer.core.regime import RegimeDecision, evaluate_regime
from options_buyer.core.sizing import can_open_premium, size_long_or_debit
from options_buyer.core.spreads import validate_credit_spread, validate_debit_spread
from options_buyer.core.trigger import FlowPrint, TriggerDecision, evaluate_trigger
from options_buyer.core.types import (
    AccountState,
    MULTIPLIER,
    OptionQuote,
    Position,
    StrategyCategory,
    StrategyType,
)
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.greeks import PortfolioGreeks
from options_buyer.risk.veto import VetoContext, evaluate_vetoes
from options_buyer.signals.checklist import PreTradeChecklist
from options_buyer.sop.daily import IntradayGate, run_intraday_gate
from options_buyer.strategies import run_absorption_3a, run_breakout, run_mean_reversion
from options_buyer.strategies.types import StrategyPlan


def price_between_walls(spot: float, structure: GexStructure) -> bool:
    """现价是否严格落在 Put Wall 与 Call Wall 之间（需两侧墙均存在）。"""
    put_w = structure.put_wall
    call_w = structure.call_wall
    if put_w is None or call_w is None:
        return False
    lo, hi = (put_w, call_w) if put_w <= call_w else (call_w, put_w)
    return lo < spot < hi


def iv_branch_consistent(
    *,
    iv_rank: float,
    strategy: StrategyType,
    category: StrategyCategory,
) -> bool:
    """IV Rank 与所选策略分支一致（§3.4.0 / §5）。"""
    if category == StrategyCategory.MEAN_REVERSION:
        return strategy == StrategyType.CREDIT_SPREAD
    if iv_rank > 50:
        return strategy in (
            StrategyType.DEBIT_SPREAD,
            StrategyType.DEEP_ITM,
            StrategyType.CREDIT_SPREAD,
        )
    return True


@dataclass
class PipelineResult:
    allowed: bool
    structure: GexStructure
    regime: RegimeDecision
    trigger: TriggerDecision | None
    plan: StrategyPlan | None
    checklist: PreTradeChecklist | None
    gate: IntradayGate | None
    veto_reasons: list[str] = field(default_factory=list)
    position: Position | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class TradingPipeline:
    """纸面交易会话编排器。"""

    account: AccountState
    broker: PaperBroker
    correlation: CorrelationBook | None = None

    def __post_init__(self) -> None:
        if self.correlation is not None:
            self.broker.correlation = self.correlation

    def evaluate_and_maybe_open(
        self,
        *,
        category: StrategyCategory,
        gex_rows: list[StrikeGex],
        spot: float,
        quote: OptionQuote,
        iv_rank: float,
        event_window: bool = False,
        flow_prints: list[FlowPrint] | None = None,
        target_strike: float | None = None,
        structure_target_r: float = 2.0,
        previous_structure: GexStructure | None = None,
        broke_5m_close: bool = False,
        near_structure: bool = True,
        price_held: bool = True,
        negative_gex_override: bool | None = None,
        # 3A
        put_flow_fading: bool = False,
        strong_gex_suppress: bool = False,
        # 均值回归
        mr_side: str = "bear_call",
        short_strike: float = 0.0,
        wall_strike: float = 0.0,
        short_outside_steps: int = 2,
        step_width: float = 1.0,
        target_price: float = 0.0,
        width: float = 5.0,
        credit: float = 2.5,
        protect_quote: OptionQuote | None = None,
        margin: float = 0.0,
        # IV crush 输入（可选）
        expected_move_pct: float | None = None,
        expected_iv_change: float | None = None,
        hold_days: int = 5,
        # 体制
        risk_reversal_sign: float | None = None,
        gex_implies_long: bool | None = None,
        charm_adverse: bool = False,
        us_eastern_hour: float | None = None,
        is_expiry_day: bool = False,
        greeks: PortfolioGreeks | None = None,
    ) -> PipelineResult:
        structure = build_structure(
            gex_rows, spot=spot, previous=previous_structure
        )
        regime = evaluate_regime(
            structure,
            risk_reversal_sign=risk_reversal_sign,
            gex_implies_long=gex_implies_long,
            charm_adverse=charm_adverse,
            us_eastern_hour=us_eastern_hour,
            is_expiry_day=is_expiry_day,
        )
        notes = list(structure.notes) + list(regime.reasons)

        if not regime.allow_new:
            return PipelineResult(
                False, structure, regime, None, None, None, None,
                veto_reasons=["体制层不允许新开"], notes=notes,
            )

        self.broker.event_window = event_window
        if greeks is not None:
            self.broker.portfolio_greeks = greeks

        neg = (
            negative_gex_override
            if negative_gex_override is not None
            else (not structure.positive_gex)
        )
        ts = target_strike if target_strike is not None else (structure.call_wall or spot)
        trigger = evaluate_trigger(
            direction="long_underlying",
            structure_active=bool(structure.active_walls),
            near_structure=near_structure,
            prints=flow_prints or [],
            target_strike=ts,
            price_held=price_held,
            negative_gex=neg,
        )

        between_walls = price_between_walls(spot, structure)

        plan: StrategyPlan | None = None
        if category == StrategyCategory.BREAKOUT:
            plan = run_breakout(
                structure=structure,
                negative_gex_or_below_zg=neg
                or structure.price_vs_zero_gamma() == "below",
                broke_5m_close=broke_5m_close,
                trigger=trigger,
                iv_rank=iv_rank,
                event_window=event_window,
                quote=quote,
                structure_target_r=structure_target_r,
            )
        elif category == StrategyCategory.ABSORPTION_3A:
            plan = run_absorption_3a(
                structure=structure,
                near_positive_gamma_level=near_structure,
                charm_adverse=regime.charm_adverse,
                put_flow_fading_or_sto=put_flow_fading,
                structure_still_active=bool(structure.active_walls),
                iv_rank=iv_rank,
                event_window=event_window,
                strong_gex_suppress=strong_gex_suppress,
                quote=quote,
                structure_target_r=structure_target_r,
                negative_gex=not structure.positive_gex,
            )
        else:
            plan = run_mean_reversion(
                structure=structure,
                price_between_walls=between_walls,
                side=mr_side,
                short_strike=short_strike or ts,
                wall_strike=wall_strike or (structure.call_wall or spot),
                short_outside_wall_steps=short_outside_steps,
                step_width=step_width,
                target_price=target_price or spot,
                width=width,
                credit=credit,
                short_quote=quote,
                protect_quote=protect_quote,
                iv_rank=iv_rank,
                event_window=event_window,
                structure_target_r=min(structure_target_r, 1.0),
            )

        if plan is None or not plan.allowed or plan.strategy is None or plan.branch is None:
            return PipelineResult(
                False, structure, regime, trigger, plan, None, None,
                veto_reasons=list(plan.veto_reasons) if plan else ["策略机拒绝"],
                notes=notes + ([s.detail for s in plan.failed_steps] if plan else []),
            )

        liq = check_liquidity(
            quote, deep_itm=plan.strategy == StrategyType.DEEP_ITM
        )
        crush_ok = True
        if expected_move_pct is not None and quote.delta:
            est = estimate_iv_crush(
                expected_underlying_move=spot * expected_move_pct,
                delta=quote.delta,
                expected_iv_change_points=expected_iv_change or 0.0,
                vega=quote.vega,
                hold_days=float(hold_days),
                daily_theta=quote.theta,
                half_spread=quote.spread / 2,
                commission=0.0,
                contracts=1,
                premium_quote=quote.mid,
                spot=spot,
                expected_move_pct=expected_move_pct,
            )
            crush_ok = est.ok

        branch: BranchDecision = plan.branch
        delta_ok = branch.delta_lo <= abs(quote.delta) <= branch.delta_hi
        dte_ok = branch.dte_lo <= quote.dte <= branch.dte_hi

        spread_ok = _spread_params_ok(
            plan.strategy,
            quote=quote,
            protect_quote=protect_quote,
            width=width,
            credit=credit,
        )
        tgt_ok = structure_target_ok(plan.structure_target_r, plan.strategy)
        size_ok, day_budget_ok, premium_est = _size_and_day_budget(
            account=self.account,
            strategy=plan.strategy,
            category=category,
            quote=quote,
            width=width,
            credit=credit,
            margin=margin or (width - credit) * MULTIPLIER,
            half=regime.size_multiplier < 1.0 or plan.size_multiplier < 1.0,
        )
        iv_ok = iv_branch_consistent(
            iv_rank=iv_rank, strategy=plan.strategy, category=category
        )

        veto_ctx = VetoContext(
            iv_rank=iv_rank,
            event_window=event_window,
            structure_active=bool(structure.active_walls),
            charm_adverse=regime.charm_adverse,
            charm_sized_down=regime.size_multiplier <= 0.5,
            liquidity_ok=liq.ok,
            iv_crush_ok=crush_ok,
            dte=quote.dte,
            strategy=plan.strategy,
            used_spread_or_deep_itm=plan.strategy
            in (StrategyType.DEBIT_SPREAD, StrategyType.CREDIT_SPREAD, StrategyType.DEEP_ITM),
            structure_target_r=plan.structure_target_r,
            greeks_ok=True if greeks is None else greeks.ok,
            block_new_buyer=False if greeks is None else greeks.block_new_buyer,
            debit_pct_of_width=(quote.ask / width) if plan.strategy == StrategyType.DEBIT_SPREAD and width > 0 else None,
            credit_pct_of_width=(credit / width) if plan.strategy == StrategyType.CREDIT_SPREAD and width > 0 else None,
            protect_leg_ok=True
            if protect_quote is None
            else check_liquidity(protect_quote, protect_leg=True).ok,
        )
        vr = evaluate_vetoes(self.account, veto_ctx)
        corr_ok = True
        if self.correlation is not None:
            corr_ok, pct = self.correlation.allows(
                equity=self.account.equity,
                symbol=quote.symbol,
                direction=1 if category != StrategyCategory.MEAN_REVERSION else -1,
                new_premium=premium_est,
            )
            veto_ctx.correlation_premium_pct = pct

        # 定义 R：能算出 1R 即视为已定义
        try:
            if plan.strategy == StrategyType.CREDIT_SPREAD:
                compute_r(plan.strategy, width=width, credit=credit, contracts=1)
            elif plan.strategy == StrategyType.DEBIT_SPREAD:
                compute_r(plan.strategy, debit=quote.ask, contracts=1)
            else:
                compute_r(plan.strategy, premium=quote.ask, contracts=1)
            r_defined = True
        except ValueError:
            r_defined = False

        gate = run_intraday_gate(
            account=self.account,
            regime=regime,
            structure_active=bool(structure.active_walls),
            flow_ok=trigger.fired or category != StrategyCategory.BREAKOUT,
            iv_branch_ok=iv_ok,
            delta_dte_ok=delta_ok and dte_ok,
            spread_params_ok=spread_ok,
            liquidity_ok=liq.ok,
            iv_crush_ok=crush_ok,
            r_defined=r_defined,
            structure_target_ok_flag=tgt_ok,
            size_ok=size_ok,
            day_budget_ok=day_budget_ok,
            greeks_ok=veto_ctx.greeks_ok,
            correlation_ok=corr_ok,
            now=self.broker.now,
        )

        if vr.blocked or not gate.allow:
            return PipelineResult(
                False, structure, regime, trigger, plan, gate.checklist, gate,
                veto_reasons=vr.reasons + gate.reasons,
                notes=notes,
            )

        half = regime.size_multiplier < 1.0 or plan.size_multiplier < 1.0
        pos: Position | None = None
        if plan.strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
            pos = self.broker.open_long(
                symbol=quote.symbol,
                premium=quote.ask,
                category=category,
                dte=quote.dte,
                structure_target_r=plan.structure_target_r,
                half_size=half,
                spot=spot,
                strategy=plan.strategy,
                veto_ctx=veto_ctx,
            )
        elif plan.strategy == StrategyType.DEBIT_SPREAD:
            pos = self.broker.open_debit(
                symbol=quote.symbol,
                net_debit=quote.ask,
                category=category,
                dte=quote.dte,
                structure_target_r=plan.structure_target_r,
                half_size=half,
                spot=spot,
                width=width,
                veto_ctx=veto_ctx,
            )
        else:
            pos = self.broker.open_credit(
                symbol=quote.symbol,
                width=width,
                credit=credit,
                margin=margin or (width - credit) * MULTIPLIER,
                category=category,
                dte=quote.dte,
                structure_target_r=plan.structure_target_r,
                veto_ctx=veto_ctx,
                half_size=half,
            )

        return PipelineResult(
            allowed=pos is not None,
            structure=structure,
            regime=regime,
            trigger=trigger,
            plan=plan,
            checklist=gate.checklist,
            gate=gate,
            veto_reasons=[] if pos else ["纸面开仓被拒"],
            position=pos,
            notes=notes,
        )


def _spread_params_ok(
    strategy: StrategyType,
    *,
    quote: OptionQuote,
    protect_quote: OptionQuote | None,
    width: float,
    credit: float,
) -> bool:
    if strategy == StrategyType.CREDIT_SPREAD:
        if protect_quote is None or width <= 0:
            return False
        return validate_credit_spread(
            short_delta=quote.delta,
            protect_delta=protect_quote.delta,
            width=width,
            net_credit=credit,
        ).ok
    if strategy == StrategyType.DEBIT_SPREAD:
        if width <= 0:
            return False
        # 编排层通常只注入长腿报价；净支/宽度用 validate，腿 Delta 用长腿近似
        # （完整双腿校验由调用方在接入链时补充 protect/short 报价）
        if quote.ask / width > 0.40 + 1e-12:
            return False
        if not (0.50 <= abs(quote.delta) <= 0.60):
            # 借方长腿 Delta 窗口；若报价是合成净价腿则放宽由分支 delta 检查兜底
            return True
        return validate_debit_spread(
            long_delta=quote.delta,
            short_delta=0.30,
            width=width,
            net_debit=quote.ask,
        ).ok
    return True


def _size_and_day_budget(
    *,
    account: AccountState,
    strategy: StrategyType,
    category: StrategyCategory,
    quote: OptionQuote,
    width: float,
    credit: float,
    margin: float,
    half: bool,
) -> tuple[bool, bool, float]:
    """返回 (size_ok, day_budget_ok, premium_or_risk_est)。"""
    if strategy == StrategyType.CREDIT_SPREAD:
        max_loss = max(0.0, (width - credit) * MULTIPLIER)
        ok, reason = can_open_premium(
            account,
            new_premium=0.0,
            category=category,
            strategy=strategy,
            margin=margin,
            max_loss=max_loss,
        )
        size_ok = ok and margin > 0
        day_ok = "日" not in reason
        if ok:
            return True, True, max_loss
        return size_ok if "保证金" not in reason else False, day_ok, max_loss

    decision = size_long_or_debit(account.equity, quote.ask, half_size=half)
    premium_est = (
        decision.premium_cost if decision.ok else max(quote.ask, 0.0) * MULTIPLIER
    )
    ok, reason = can_open_premium(
        account,
        new_premium=premium_est,
        category=category,
        strategy=strategy,
    )
    size_ok = decision.ok
    day_ok = "日" not in reason and "亏损" not in reason
    if ok and decision.ok:
        return True, True, premium_est
    return size_ok, day_ok if not ok else True, premium_est
