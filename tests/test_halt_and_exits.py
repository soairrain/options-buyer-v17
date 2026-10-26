from options_buyer.core.exits import ExitAction, long_or_debit_exit, pnl_in_r
from options_buyer.core.types import AccountState, StrategyCategory, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.halt import record_stop, record_win, reset_day
from options_buyer.risk.veto import VetoContext, evaluate_vetoes


def test_consecutive_stops_halt():
    a = AccountState(equity=50_000)
    record_stop(a)
    record_stop(a)
    assert not a.halted
    record_stop(a)
    assert a.halted
    assert "连续 3" in (a.halt_reason or "")


def test_win_resets_consecutive():
    a = AccountState(equity=50_000)
    record_stop(a)
    record_stop(a)
    record_win(a)
    assert a.consecutive_stops == 0
    record_stop(a)
    assert a.consecutive_stops == 1
    assert not a.halted


def test_add_loss_2r_counts_one_stop_via_paper():
    """加仓后整笔亏 2R 仍只记 1 笔止损（不因加仓多计）。"""
    a = AccountState(equity=50_000)
    broker = PaperBroker(a)
    p = broker.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
        is_add=True,
        existing_premium=200.0,
        first_leg_profitable=True,
    )
    assert p and p.is_add
    # 亏 2R：r=1.0，mark=0 → pnl_r = -2
    fill = broker.mark_exit(p.position_id, mark=0.0, dte=25)
    assert fill is not None
    assert a.consecutive_stops == 1


def test_dte_lt7_profit_1r():
    # entry 2, r=1 → 盈利 1R mark=3
    pr = pnl_in_r(StrategyType.LONG, entry=2.0, mark=3.0, r_per_contract=1.0)
    assert abs(pr - 1.0) < 1e-9
    d = long_or_debit_exit(dte=5, pnl_r=pr, structure_target_r=2.0)
    assert d.action == ExitAction.CLOSE_ALL


def test_pdt_veto():
    a = AccountState(equity=20_000, day_trades_used_5d=3)
    res = evaluate_vetoes(a, VetoContext(structure_target_r=2.0))
    assert res.blocked
    assert any("PDT" in r for r in res.reasons)


def test_reset_day():
    a = AccountState(equity=50_000, halted=True, halt_reason="连续 3 笔止损", consecutive_stops=3)
    reset_day(a)
    assert not a.halted
    assert a.consecutive_stops == 0
