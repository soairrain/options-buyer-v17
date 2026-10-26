"""§十 盘前 / 盘中 / 盘后 SOP 自动化（结构化检查，不拉外部数据）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.extreme import extreme_paused
from options_buyer.core.gex import GexStructure
from options_buyer.core.regime import RegimeDecision
from options_buyer.core.types import AccountState
from options_buyer.risk.elimination import EliminationResult, TradeResult, evaluate_elimination
from options_buyer.risk.greeks import PortfolioGreeks
from options_buyer.signals.checklist import PreTradeChecklist, build_checklist


@dataclass
class PreMarketBrief:
    structure: GexStructure
    iv_rank: float
    iv_percentile: float | None
    event_window: bool
    is_expiry_day: bool
    charm_window_hours: tuple[float, float]
    pdt_clear: bool
    greeks_ok: bool
    notes: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.structure.active_walls) and self.pdt_clear and self.greeks_ok


def run_pre_market(
    *,
    structure: GexStructure,
    iv_rank: float,
    iv_percentile: float | None = None,
    event_window: bool = False,
    is_expiry_day: bool = False,
    account: AccountState,
    greeks: PortfolioGreeks | None = None,
    iv_rank_distorted: bool = False,
) -> PreMarketBrief:
    notes: list[str] = []
    if iv_rank_distorted:
        notes.append("IV Rank 可能失真：改用 IV Percentile 或 20 日 IV 相对中位数")
    if is_expiry_day:
        notes.append("到期日：标记 Charm 窗口 14:00–16:00 ET")
    if event_window:
        notes.append("事件窗口：禁止新开裸买")
    for n in structure.notes:
        notes.append(n)

    from options_buyer.core.types import PDT_DAY_TRADES_LIMIT, PDT_EQUITY_THRESHOLD

    pdt_clear = not (
        account.equity < PDT_EQUITY_THRESHOLD
        and account.day_trades_used_5d >= PDT_DAY_TRADES_LIMIT
    )
    g_ok = True if greeks is None else greeks.ok
    return PreMarketBrief(
        structure=structure,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        event_window=event_window,
        is_expiry_day=is_expiry_day,
        charm_window_hours=(14.0, 16.0),
        pdt_clear=pdt_clear,
        greeks_ok=g_ok,
        notes=notes,
    )


@dataclass
class IntradayGate:
    allow: bool
    checklist: PreTradeChecklist
    extreme: bool
    halted: bool
    reasons: list[str] = field(default_factory=list)


def run_intraday_gate(
    *,
    account: AccountState,
    regime: RegimeDecision,
    structure_active: bool,
    flow_ok: bool,
    iv_branch_ok: bool,
    delta_dte_ok: bool,
    spread_params_ok: bool,
    liquidity_ok: bool,
    iv_crush_ok: bool,
    r_defined: bool,
    structure_target_ok_flag: bool,
    size_ok: bool,
    day_budget_ok: bool,
    greeks_ok: bool,
    correlation_ok: bool,
    now: float | None = None,
) -> IntradayGate:
    extreme = extreme_paused(account, now=now)
    checklist = build_checklist(
        gex_regime_ok=regime.allow_new or regime.size_multiplier < 1.0,
        structure_active=structure_active,
        charm_ok=not regime.charm_adverse or regime.size_multiplier <= 0.5,
        flow_ok=flow_ok,
        iv_branch_ok=iv_branch_ok,
        delta_dte_ok=delta_dte_ok,
        spread_params_ok=spread_params_ok,
        liquidity_ok=liquidity_ok,
        iv_crush_ok=iv_crush_ok,
        r_defined=r_defined,
        structure_target_ok=structure_target_ok_flag,
        size_ok=size_ok,
        day_budget_ok=day_budget_ok,
        greeks_ok=greeks_ok,
        correlation_ok=correlation_ok,
        halt_clear=not account.halted,
        pdt_clear=True,  # 细项由 veto/paper 再卡；SOP 层用账户态
    )
    reasons = [i.label for i in checklist.failures()]
    if extreme:
        reasons.append("极端行情暂停中")
    if account.halted:
        reasons.append(account.halt_reason or "已停机")
    allow = checklist.passed and not extreme and not account.halted
    return IntradayGate(
        allow=allow, checklist=checklist, extreme=extreme, halted=account.halted, reasons=reasons
    )


@dataclass
class PostMarketReport:
    trades: list[TradeResult]
    elimination: EliminationResult
    notes: list[str] = field(default_factory=list)


def run_post_market(
    trades: list[TradeResult],
    *,
    rule_violations: list[str] | None = None,
) -> PostMarketReport:
    elim = evaluate_elimination(trades)
    notes = list(rule_violations or [])
    if elim.eliminate:
        notes.append(elim.reason)
    notes.append(f"滚动期望 {elim.expectancy_r:.3f}R | 回撤 {elim.max_drawdown:.1%} | n={elim.n}")
    return PostMarketReport(trades=trades, elimination=elim, notes=notes)
