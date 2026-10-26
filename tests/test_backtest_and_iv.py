"""回测引擎 / IV Rank / Moomoo stub。"""

from __future__ import annotations

import pytest

from options_buyer.backtest import BacktestEngine, BarQuote
from options_buyer.data.iv_rank import iv_percentile, iv_rank
from options_buyer.execution.moomoo_stub import MoomooBrokerStub


def test_iv_rank_percentile():
    assert iv_rank(20, 10, 30) == pytest.approx(50.0)
    assert iv_percentile(20, [10, 15, 20, 25, 30]) == pytest.approx(40.0)


def test_backtest_long_stop():
    # ask 开仓 2.0；之后 bid 到 1.0 → 约 -1R 止损
    bars = [
        BarQuote(0, bid=1.95, ask=2.0, dte=30, iv=20),
        BarQuote(1, bid=1.0, ask=1.05, dte=29, iv=20),
    ]
    res = BacktestEngine().run(bars)
    assert any(f.side == "close" for f in res.fills)
    assert res.day_pnl < 0


def test_moomoo_stub_refuses_live():
    b = MoomooBrokerStub()
    with pytest.raises(NotImplementedError):
        b.connect()
    with pytest.raises(NotImplementedError):
        b.open_long(symbol="SPY")
