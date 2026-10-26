"""§5 策略机 / §8 到期 / §10 SOP / 淘汰 / 相关性 / 极端行情。"""

from __future__ import annotations

from options_buyer.core.correlation import CorrelationBook
from options_buyer.core.expiry import ExpiryAction, manage_expiry
from options_buyer.core.extreme import apply_extreme_pause, check_extreme, extreme_paused
from options_buyer.core.gex import StrikeGex, build_structure
from options_buyer.core.regime import evaluate_regime
from options_buyer.core.trigger import FlowPrint, FlowSide, TriggerDecision, evaluate_trigger
from options_buyer.core.types import AccountState, OptionQuote, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.elimination import TradeResult, evaluate_elimination
from options_buyer.sop.daily import run_intraday_gate, run_post_market, run_pre_market
from options_buyer.strategies import run_absorption_3a, run_breakout, run_mean_reversion


def _quote(**kw) -> OptionQuote:
    base = dict(
        symbol="SPY",
        strike=100,
        dte=30,
        right="C",
        bid=1.95,
        ask=2.05,
        mid=2.0,
        delta=0.40,
        oi=1000,
        volume=500,
    )
    base.update(kw)
    return OptionQuote(**base)


def test_breakout_plan_allows():
    rows = [
        StrikeGex(100, 50, -50, 1000, 1000, 1000, 1000),
        StrikeGex(105, 80, -10, 2000, 200, 1000, 50),
    ]
    structure = build_structure(rows, spot=100)
    structure.positive_gex = False
    prints = [FlowPrint(105, FlowSide.BTO_CALL, 30, 0.4, 800, 500)]
    trig = evaluate_trigger(
        direction="long_underlying",
        structure_active=True,
        near_structure=True,
        prints=prints,
        target_strike=105,
        min_net_delta=5,
        negative_gex=True,
    )
    plan = run_breakout(
        structure=structure,
        negative_gex_or_below_zg=True,
        broke_5m_close=True,
        trigger=trig,
        iv_rank=25,
        event_window=False,
        quote=_quote(delta=0.40, dte=30),
        structure_target_r=2.0,
    )
    assert plan.allowed
    assert plan.strategy == StrategyType.LONG


def test_absorption_rejects_negative_gex():
    structure = build_structure(
        [StrikeGex(100, 10, -80, 1000, 1000, 500, 500)], spot=100
    )
    structure.positive_gex = False
    plan = run_absorption_3a(
        structure=structure,
        near_positive_gamma_level=True,
        charm_adverse=False,
        put_flow_fading_or_sto=True,
        structure_still_active=True,
        iv_rank=20,
        event_window=False,
        strong_gex_suppress=False,
        quote=_quote(delta=0.55, dte=21),
        structure_target_r=2.0,
        negative_gex=True,
    )
    assert not plan.allowed


def test_mean_reversion_credit():
    structure = build_structure(
        [
            StrikeGex(95, 10, -100, 2000, 3000, 1000, 1000),
            StrikeGex(100, 40, -40, 2000, 2000, 1000, 1000),
            StrikeGex(105, 100, -10, 3000, 500, 1000, 100),
        ],
        spot=100,
    )
    structure.positive_gex = True
    short = _quote(strike=107, delta=0.25, dte=30, bid=1.0, ask=1.05, mid=1.02)
    prot = _quote(strike=110, delta=0.10, dte=30, bid=0.30, ask=0.35, mid=0.32)
    plan = run_mean_reversion(
        structure=structure,
        price_between_walls=True,
        side="bear_call",
        short_strike=107,
        wall_strike=105,
        short_outside_wall_steps=2,
        step_width=1.0,
        target_price=100,
        width=3.0,
        credit=1.6,
        short_quote=short,
        protect_quote=prot,
        iv_rank=55,
        event_window=False,
    )
    assert plan.allowed
    assert plan.strategy == StrategyType.CREDIT_SPREAD


def test_expiry_naked_and_assignment():
    d = manage_expiry(StrategyType.LONG, dte=1)
    assert d.action == ExpiryAction.CLOSE
    a = manage_expiry(StrategyType.CREDIT_SPREAD, dte=5, assigned=True)
    assert a.halt_day and a.action == ExpiryAction.CLOSE_PROTECT_OR_ASSIGNED


def test_extreme_pause_blocks_open():
    chk = check_extreme(
        one_min_range=3.0, atr_5m_14=0.5, book_bid_size=100, book_ask_size=100, now=1_000.0
    )
    assert chk.halted
    acct = AccountState(equity=50_000)
    apply_extreme_pause(acct, chk)
    assert extreme_paused(acct, now=1_001.0)
    broker = PaperBroker(acct, now=1_001.0)
    assert (
        broker.open_long(
            symbol="SPY",
            premium=2.0,
            category=__import__(
                "options_buyer.core.types", fromlist=["StrategyCategory"]
            ).StrategyCategory.BREAKOUT,
            dte=30,
            structure_target_r=2.0,
        )
        is None
    )
    assert not extreme_paused(acct, now=1_000.0 + 15 * 60 + 1)


def test_correlation_cap():
    book = CorrelationBook()
    book.set_corr("SPY", "QQQ", 0.9)
    book.legs.append(
        __import__("options_buyer.core.correlation", fromlist=["OpenRiskLeg"]).OpenRiskLeg(
            "SPY", 1, 800.0
        )
    )
    ok, pct = book.allows(equity=50_000, symbol="QQQ", direction=1, new_premium=400.0)
    assert not ok
    assert pct > 0.02


def test_elimination_and_sop():
    trades = [TradeResult(-0.5, -0.005) for _ in range(20)]
    elim = evaluate_elimination(trades)
    assert elim.eliminate
    post = run_post_market(trades)
    assert post.elimination.eliminate

    structure = build_structure(
        [StrikeGex(100, 50, -20, 1000, 1000, 500, 500)], spot=100
    )
    acct = AccountState(equity=50_000)
    brief = run_pre_market(structure=structure, iv_rank=30, account=acct)
    assert brief.ready

    regime = evaluate_regime(structure)
    gate = run_intraday_gate(
        account=acct,
        regime=regime,
        structure_active=True,
        flow_ok=True,
        iv_branch_ok=True,
        delta_dte_ok=True,
        spread_params_ok=True,
        liquidity_ok=True,
        iv_crush_ok=True,
        r_defined=True,
        structure_target_ok_flag=True,
        size_ok=True,
        day_budget_ok=True,
        greeks_ok=True,
        correlation_ok=True,
    )
    assert gate.allow
