"""第三轮详细对照：E11–E26 回归。"""

from options_buyer.core.branch import choose_branch
from options_buyer.core.exits import (
    ExitAction,
    ExitReason,
    credit_spread_exit,
    iv_path_override,
    long_or_debit_exit,
)
from options_buyer.core.sizing import can_open_premium, signal_add_ok
from options_buyer.core.types import AccountState, StrategyCategory, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.greeks import LegGreeks, PortfolioGreeks, aggregate
from options_buyer.risk.halt import apply_realized_pnl, record_stop, record_win


def test_e11_gap_to_2r_closes_all_before_half():
    d = long_or_debit_exit(
        dte=20, pnl_r=2.0, structure_target_r=2.0, remaining_fraction=1.0
    )
    assert d.action == ExitAction.CLOSE_ALL
    assert d.reason == ExitReason.TAKE_PROFIT


def test_e12_odd_lot_half_releases_by_fraction():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    # $1 → floor(250/100)=2 张；再开一笔凑不成 3，直接用 3 需更小权利金
    # $0.80 → floor(250/80)=3
    p = broker.open_long(
        symbol="SPY",
        premium=0.80,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p and p.contracts == 3
    # 1.5R：r=0.40，mark=0.80+0.60=1.40
    fill = broker.mark_exit(p.position_id, mark=1.40, dte=20)
    assert fill is not None
    assert fill.side == "sell_half"
    assert fill.contracts == 1  # 3//2
    rem = broker.positions[p.position_id]
    assert rem.contracts == 2
    assert abs(rem.remaining_fraction - 2 / 3) < 1e-9
    # 权利金释放 1/3
    assert abs(a.open_premium_total - 2 * 0.80 * 100) < 1e-6


def test_e13_theta_positive_blocks_buyer_not_credit():
    legs = [
        LegGreeks(delta=0.1, vega=0.01, theta=0.05, contracts=1, spot=100),
    ]
    g = aggregate(legs, equity=50_000)
    assert g.ok
    assert g.block_new_buyer

    a = AccountState(equity=50_000)
    broker = PaperBroker(a, portfolio_greeks=g)
    assert (
        broker.open_long(
            symbol="SPY",
            premium=2.0,
            category=StrategyCategory.BREAKOUT,
            dte=30,
            structure_target_r=2.0,
        )
        is None
    )
    assert (
        broker.open_credit(
            symbol="SPX",
            width=15.0,
            credit=7.5,
            margin=1_500,
            category=StrategyCategory.MEAN_REVERSION,
            dte=30,
            structure_target_r=1.0,
        )
        is not None
    )


def test_e14_ivr50_breakout_debit_not_naked():
    b = choose_branch(
        iv_rank=50,
        positive_gex=False,
        event_window=False,
        category=StrategyCategory.BREAKOUT,
    )
    assert b.strategy == StrategyType.DEBIT_SPREAD
    assert not b.allow_naked


def test_e15_day_loss_freezes_stop_counter():
    a = AccountState(equity=50_000, consecutive_stops=2)
    apply_realized_pnl(a, -1_000)
    assert a.halted
    assert "日亏" in (a.halt_reason or "")
    record_win(a)
    assert a.consecutive_stops == 2  # 不因盈利归 0
    record_stop(a)
    assert a.consecutive_stops == 2  # 不再 +1


def test_e16_iv_rise_must_not_block_time_stop():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_debit(
        symbol="SPY",
        net_debit=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p
    fill = broker.mark_exit(
        p.position_id,
        mark=2.5,  # +0.5R
        dte=5,
        iv_entry=20.0,
        iv_now=35.0,
        at_structure_target=True,
    )
    assert fill is not None
    assert p.position_id not in broker.positions


def test_e17_iv_rise_allows_take_half():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_long(
        symbol="SPY",
        premium=0.5,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p and p.contracts >= 2
    # 1.5R：r=0.25 → mark=0.875
    fill = broker.mark_exit(
        p.position_id,
        mark=0.875,
        dte=20,
        iv_entry=20.0,
        iv_now=35.0,
        at_structure_target=True,
    )
    assert fill is not None
    assert fill.side == "sell_half"
    rem = broker.positions[p.position_id]
    assert rem.remaining_fraction < 1.0


def test_e17_iv_rise_holds_remainder_after_half():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_long(
        symbol="SPY",
        premium=0.5,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert p
    broker.mark_exit(p.position_id, mark=0.875, dte=20)  # half
    # 剩余到 2R：mark = 0.5 + 2*0.25 = 1.0；IV 上升应继续持有剩余
    fill = broker.mark_exit(
        p.position_id,
        mark=1.0,
        dte=18,
        iv_entry=20.0,
        iv_now=35.0,
        at_structure_target=True,
    )
    assert fill is None
    assert p.position_id in broker.positions


def test_e19_add_rejects_over_one_percent():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    # 已有 $400 + 加仓 $200 = $600 > 1%
    p = broker.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
        is_add=True,
        existing_premium=400.0,
        first_leg_profitable=True,
    )
    assert p is None


def test_e19_add_requires_first_leg_profit():
    ok, reason = signal_add_ok(
        AccountState(equity=50_000),
        category=StrategyCategory.BREAKOUT,
        existing_premium=200.0,
        add_premium=200.0,
        first_leg_profitable=False,
    )
    assert not ok
    assert "首仓" in reason


def test_e20_debit_dte10_at_1_5r_halves_not_full():
    d = long_or_debit_exit(
        dte=10,
        pnl_r=1.5,
        structure_target_r=2.0,
        strategy=StrategyType.DEBIT_SPREAD,
    )
    assert d.action == ExitAction.CLOSE_HALF


def test_e20_long_dte10_at_1_5r_still_full():
    d = long_or_debit_exit(
        dte=10,
        pnl_r=1.5,
        structure_target_r=2.0,
        strategy=StrategyType.LONG,
    )
    assert d.action == ExitAction.CLOSE_ALL


def test_e22_no_new_long_dte_lt7():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    assert (
        broker.open_long(
            symbol="SPY",
            premium=2.0,
            category=StrategyCategory.BREAKOUT,
            dte=5,
            structure_target_r=2.0,
        )
        is None
    )


def test_e23_open_deep_itm_tags_strategy():
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_deep_itm(
        symbol="SPY",
        premium=8.0,  # floor(250/800)=0 → need cheaper: use half? 50k*0.5%=250, $2.5→1
        category=StrategyCategory.BREAKOUT,
        dte=45,
        structure_target_r=2.0,
    )
    # $8 → 0 张；改用可成交权利金
    p = broker.open_deep_itm(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=45,
        structure_target_r=2.0,
    )
    assert p is not None
    assert p.strategy == StrategyType.DEEP_ITM


def test_e24_credit_day_loss_plus_max_loss_cap():
    a = AccountState(equity=50_000, day_realized_pnl=-900)  # 1.8%
    ok, reason = can_open_premium(
        a,
        new_premium=0.0,
        category=StrategyCategory.MEAN_REVERSION,
        strategy=StrategyType.CREDIT_SPREAD,
        margin=1_500,
        max_loss=1_500,
    )
    assert not ok
    assert "最大亏损" in reason


def test_e25_credit_dte_lt7_missing_atr_closes():
    d = credit_spread_exit(dte=5, pnl_r=0.0, short_leg_distance_atr=None)
    assert d.action == ExitAction.CLOSE_ALL
    assert d.reason == ExitReason.TIME_STOP


def test_e26_iv_relative_drop_at_exactly_20pct():
    d = iv_path_override(iv_entry=25.0, iv_now=20.0, at_structure_target=True)
    assert d is not None
    assert d.action == ExitAction.CLOSE_ALL
    assert d.reason == ExitReason.IV_CRUSH_EXIT
