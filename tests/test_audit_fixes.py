"""审计修复回归：E1–E3 及价差校验。"""

from options_buyer.core.branch import choose_branch
from options_buyer.core.exits import ExitAction, ExitReason, credit_spread_exit, long_or_debit_exit
from options_buyer.core.spreads import validate_credit_spread, validate_debit_spread
from options_buyer.core.types import AccountState, StrategyCategory, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.core.sizing import can_open_premium


def test_e1_credit_not_blocked_by_half_percent_premium():
    """信用价差不以 max_loss 卡 0.5% 权利金。"""
    a = AccountState(equity=50_000)
    # max_loss $1500 = 3% equity，远超 0.5%
    ok, reason = can_open_premium(
        a,
        new_premium=0.0,
        category=StrategyCategory.MEAN_REVERSION,
        strategy=StrategyType.CREDIT_SPREAD,
        margin=1_500,
        max_loss=1_500,
    )
    assert ok, reason

    broker = PaperBroker(a)
    pos = broker.open_credit(
        symbol="SPX",
        width=15.0,
        credit=7.5,
        margin=1_500,
        category=StrategyCategory.MEAN_REVERSION,
        dte=30,
        structure_target_r=1.0,
    )
    assert pos is not None


def test_e2_debit_dte_lt7_force_close_below_1_5r():
    d = long_or_debit_exit(
        dte=5,
        pnl_r=0.5,
        structure_target_r=2.0,
        strategy=StrategyType.DEBIT_SPREAD,
    )
    assert d.action == ExitAction.CLOSE_ALL
    assert d.reason == ExitReason.TIME_STOP


def test_e2_long_dte_lt7_still_hold_below_1r_profit():
    d = long_or_debit_exit(
        dte=5,
        pnl_r=0.5,
        structure_target_r=2.0,
        strategy=StrategyType.LONG,
    )
    assert d.action == ExitAction.HOLD


def test_e3_absorption_allows_naked_in_positive_gex():
    b = choose_branch(
        iv_rank=40,
        positive_gex=True,
        event_window=False,
        category=StrategyCategory.ABSORPTION_3A,
    )
    assert b.strategy == StrategyType.LONG
    assert b.allow_naked


def test_e3_absorption_strong_suppress_to_debit():
    b = choose_branch(
        iv_rank=40,
        positive_gex=True,
        event_window=False,
        category=StrategyCategory.ABSORPTION_3A,
        strong_gex_suppress=True,
    )
    assert b.strategy == StrategyType.DEBIT_SPREAD


def test_credit_short_delta_stop():
    d = credit_spread_exit(dte=20, pnl_r=0.0, short_delta=0.55)
    assert d.action == ExitAction.CLOSE_ALL


def test_spread_builders():
    assert validate_debit_spread(
        long_delta=0.55, short_delta=0.30, width=5.0, net_debit=1.5
    ).ok
    assert not validate_debit_spread(
        long_delta=0.55, short_delta=0.30, width=5.0, net_debit=2.5
    ).ok
    assert validate_credit_spread(
        short_delta=0.25, protect_delta=0.10, width=5.0, net_credit=2.5
    ).ok
    assert not validate_credit_spread(
        short_delta=0.25, protect_delta=0.10, width=5.0, net_credit=2.0
    ).ok


def test_e9_credit_margin_does_not_block_long_premium_budget():
    """信用保证金不得占用权利金合计 3% 预算。"""
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    c = broker.open_credit(
        symbol="SPX",
        width=15.0,
        credit=7.5,
        margin=1_500,
        category=StrategyCategory.MEAN_REVERSION,
        dte=30,
        structure_target_r=1.0,
    )
    assert c is not None
    assert a.open_premium_total == 0.0
    assert a.open_credit_margin_total == 1_500
    # 仍可开满单笔 0.5% 裸买（$2 → 1 张 = $200）
    p = broker.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p is not None
    assert a.open_premium_total == 200.0


def test_e10_iv_rise_must_not_block_stop_loss():
    """IV 绝对上升不得覆盖 1R 止损。"""
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p
    fill = broker.mark_exit(
        p.position_id,
        mark=1.0,  # -1R
        dte=25,
        iv_entry=20.0,
        iv_now=35.0,  # 绝对上升 15 点
        at_structure_target=True,
    )
    assert fill is not None
    assert a.consecutive_stops == 1
