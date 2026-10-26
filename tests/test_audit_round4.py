"""第四轮：硬伤修复 + 编排门禁回归。"""

from __future__ import annotations

from options_buyer.core.exits import ExitAction, credit_spread_exit
from options_buyer.core.gex import StrikeGex, build_structure, find_zero_gamma
from options_buyer.core.regime import RegimeBias, evaluate_regime
from options_buyer.core.trigger import FlowPrint, FlowSide, evaluate_trigger
from options_buyer.core.types import (
    AccountState,
    ExitReason,
    OptionQuote,
    StrategyCategory,
    StrategyType,
)
from options_buyer.execution.paper import PaperBroker
from options_buyer.pipeline import TradingPipeline
from options_buyer.risk.halt import size_multiplier_psychology


def test_zero_gamma_adjacent_flip():
    rows = [
        StrikeGex(90, call_gex=-50, put_gex=-50, call_oi=100, put_oi=100, call_volume=100, put_volume=100),
        StrikeGex(95, call_gex=-20, put_gex=-20, call_oi=100, put_oi=100, call_volume=100, put_volume=100),
        StrikeGex(100, call_gex=30, put_gex=30, call_oi=100, put_oi=100, call_volume=100, put_volume=100),
        StrikeGex(105, call_gex=40, put_gex=40, call_oi=100, put_oi=100, call_volume=100, put_volume=100),
    ]
    zg = find_zero_gamma(rows, spot=100)
    # 95(-40) → 100(+60)：插值 95 + 5*(40/100)=97
    assert zg is not None
    assert 96.0 <= zg <= 98.0


def test_rr_veto_not_overridden_by_charm():
    s = build_structure(
        [StrikeGex(100, 50, -10, 1000, 1000, 500, 500)], spot=100
    )
    s.positive_gex = True
    d = evaluate_regime(
        s, risk_reversal_sign=-1.0, gex_implies_long=True, charm_adverse=True
    )
    assert d.bias == RegimeBias.NO_TRADE
    assert d.allow_new is False
    assert d.size_multiplier == 0.5


def test_credit_short_delta_reason_and_win_count():
    d = credit_spread_exit(dte=20, pnl_r=0.2, short_delta=0.55)
    assert d.reason == ExitReason.SHORT_DELTA
    acct = AccountState(equity=50_000)
    b = PaperBroker(acct)
    pos = b.open_credit(
        symbol="SPY",
        width=10,
        credit=5,
        margin=500,
        category=StrategyCategory.MEAN_REVERSION,
        dte=30,
        structure_target_r=1.0,
    )
    assert pos
    fill = b.mark_exit(pos.position_id, mark=3.0, dte=25, short_delta=0.55)
    assert fill and fill.pnl > 0
    assert acct.consecutive_stops == 0
    assert acct.wins_today == 1


def test_half_then_full_counts_one_win():
    acct = AccountState(equity=100_000)
    b = PaperBroker(acct)
    pos = b.open_long(
        symbol="SPY",
        premium=1.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert pos and pos.contracts >= 2
    # 1R=0.5；1.5R mark=1.75
    h = b.mark_exit(pos.position_id, mark=1.75, dte=25)
    assert h and h.side == "sell_half"
    assert acct.consecutive_wins == 0  # 减半不计 win
    f = b.mark_exit(pos.position_id, mark=2.0, dte=24)
    assert f and f.side == "close"
    assert acct.consecutive_wins == 1
    assert size_multiplier_psychology(acct) == 1.0


def test_event_window_blocks_naked_on_paper():
    acct = AccountState(equity=50_000)
    b = PaperBroker(acct, event_window=True)
    pos = b.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert pos is None


def test_soft_overtrade_blocks():
    acct = AccountState(equity=50_000, opens_today=5, wins_today=0)
    b = PaperBroker(acct)
    assert (
        b.open_long(
            symbol="SPY",
            premium=2.0,
            category=StrategyCategory.BREAKOUT,
            dte=30,
            structure_target_r=2.0,
        )
        is None
    )


def test_structure_gone_exit():
    acct = AccountState(equity=50_000)
    b = PaperBroker(acct)
    pos = b.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert pos
    fill = b.mark_exit(pos.position_id, mark=2.1, dte=28, structure_gone=True)
    assert fill and "墙体" in fill.reason


def test_pipeline_breakout_open():
    rows = [
        StrikeGex(100, 10, -80, 1000, 1000, 1000, 1000),
        StrikeGex(105, 20, -10, 2000, 200, 1000, 100),
    ]
    acct = AccountState(equity=50_000)
    broker = PaperBroker(acct)
    pipe = TradingPipeline(acct, broker)
    q = OptionQuote(
        symbol="SPY",
        strike=105,
        dte=30,
        right="C",
        bid=1.95,
        ask=2.0,
        mid=1.975,
        delta=0.40,
        oi=1000,
        volume=500,
    )
    # signed_delta = 0.4 * 200 = 80 ≥ 默认 min_net_delta 50
    prints = [FlowPrint(105, FlowSide.BTO_CALL, 200, 0.4, 800, 500)]
    res = pipe.evaluate_and_maybe_open(
        category=StrategyCategory.BREAKOUT,
        gex_rows=rows,
        spot=100,
        quote=q,
        iv_rank=25,
        flow_prints=prints,
        target_strike=105,
        broke_5m_close=True,
        near_structure=True,
        negative_gex_override=True,
        structure_target_r=2.0,
    )
    assert res.allowed
    assert res.position is not None
    assert res.regime.allow_new
