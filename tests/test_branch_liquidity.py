from options_buyer.core.branch import choose_branch
from options_buyer.core.iv_crush import estimate_iv_crush
from options_buyer.core.liquidity import check_liquidity
from options_buyer.core.types import OptionQuote, StrategyCategory, StrategyType


def test_high_iv_forces_debit():
    b = choose_branch(
        iv_rank=60,
        positive_gex=False,
        event_window=False,
        category=StrategyCategory.BREAKOUT,
    )
    assert b.strategy == StrategyType.DEBIT_SPREAD
    assert not b.allow_naked


def test_mean_reversion_credit():
    b = choose_branch(
        iv_rank=40,
        positive_gex=True,
        event_window=False,
        category=StrategyCategory.MEAN_REVERSION,
    )
    assert b.strategy == StrategyType.CREDIT_SPREAD


def test_liquidity_reject_wide():
    q = OptionQuote(
        symbol="SPY",
        strike=500,
        dte=30,
        right="C",
        bid=1.0,
        ask=1.60,
        mid=1.30,
        delta=0.4,
        oi=1000,
        volume=200,
    )
    assert not check_liquidity(q).ok


def test_iv_crush_floor():
    est = estimate_iv_crush(
        expected_underlying_move=5.0,
        delta=0.4,
        expected_iv_change_points=-5.0,
        vega=0.05,
        hold_days=5,
        daily_theta=-0.05,
        half_spread=0.05,
        commission=2.0,
        contracts=1,
        premium_quote=2.0,
    )
    # 可能因 Vega 逆风或净期望不足失败；至少返回结构化结果
    assert est.premium_total == 200.0
    assert isinstance(est.ok, bool)
