"""缺口补全：编排墙体/清单、Broker 协议、行情与 Moomoo 适配器。"""

from __future__ import annotations

import pytest

from options_buyer.core.gex import StrikeGex
from options_buyer.core.trigger import FlowPrint, FlowSide
from options_buyer.core.types import AccountState, OptionQuote, StrategyCategory
from options_buyer.data import (
    FakeMarketDataFeed,
    IvStats,
    MarketDataConfig,
    MarketDataConfigError,
    OpraAdapterError,
    OpraMarketDataFeed,
    UnderlyingSnapshot,
    build_feed,
)
from options_buyer.execution import (
    Broker,
    FakeMoomooClient,
    MoomooBrokerStub,
    MoomooConfig,
    MoomooConfigError,
    MoomooNotConnectedError,
    PaperBroker,
)
from options_buyer.pipeline import TradingPipeline, price_between_walls
from options_buyer.core.gex import build_structure


def _mr_rows():
    return [
        StrikeGex(95, 10, -100, 2000, 3000, 1000, 1000),
        StrikeGex(100, 40, -40, 2000, 2000, 1000, 1000),
        StrikeGex(105, 100, -10, 3000, 500, 1000, 100),
    ]


def _quote(**kw) -> OptionQuote:
    base = dict(
        symbol="SPY",
        strike=107,
        dte=30,
        right="C",
        bid=1.0,
        ask=1.05,
        mid=1.02,
        delta=0.25,
        oi=1000,
        volume=500,
    )
    base.update(kw)
    return OptionQuote(**base)


def test_price_between_walls_helper():
    s = build_structure(_mr_rows(), spot=100)
    assert price_between_walls(100, s) is True
    assert price_between_walls(120, s) is False
    assert price_between_walls(90, s) is False


def test_pipeline_mean_reversion_rejects_outside_walls():
    """墙外现价不得因硬编码而开仓。"""
    acct = AccountState(equity=50_000)
    pipe = TradingPipeline(acct, PaperBroker(acct))
    short = _quote()
    prot = _quote(strike=110, delta=0.10, bid=0.30, ask=0.35, mid=0.32)
    res = pipe.evaluate_and_maybe_open(
        category=StrategyCategory.MEAN_REVERSION,
        gex_rows=_mr_rows(),
        spot=120,
        quote=short,
        iv_rank=20,
        protect_quote=prot,
        short_strike=107,
        wall_strike=105,
        width=5,
        credit=2.5,
        margin=250,
        structure_target_r=1.0,
        mr_side="bear_call",
        target_price=100,
    )
    assert res.allowed is False
    assert res.position is None
    assert res.plan is not None
    assert res.plan.allowed is False
    failed = {s.step for s in res.plan.failed_steps}
    assert "regime" in failed


def test_pipeline_mean_reversion_allows_between_walls():
    acct = AccountState(equity=50_000)
    pipe = TradingPipeline(acct, PaperBroker(acct))
    short = _quote()
    prot = _quote(strike=110, delta=0.10, bid=0.30, ask=0.35, mid=0.32)
    res = pipe.evaluate_and_maybe_open(
        category=StrategyCategory.MEAN_REVERSION,
        gex_rows=_mr_rows(),
        spot=100,
        quote=short,
        iv_rank=20,
        protect_quote=prot,
        short_strike=107,
        wall_strike=105,
        width=5,
        credit=2.5,
        margin=250,
        structure_target_r=1.0,
        mr_side="bear_call",
        target_price=100,
    )
    assert res.allowed is True
    assert res.position is not None
    assert res.checklist is not None and res.checklist.passed


def test_checklist_gates_are_real_not_hardcoded():
    """权利金过高 → size 不足，清单不得整表 True 放行。"""
    acct = AccountState(equity=10_000)  # 0.5% = $50 → 权利金 2 也不足 1 张
    pipe = TradingPipeline(acct, PaperBroker(acct))
    rows = [
        StrikeGex(100, 10, -80, 1000, 1000, 1000, 1000),
        StrikeGex(105, 20, -10, 2000, 200, 1000, 100),
    ]
    q = OptionQuote(
        symbol="SPY",
        strike=105,
        dte=30,
        right="C",
        bid=4.9,
        ask=5.0,
        mid=4.95,
        delta=0.40,
        oi=1000,
        volume=500,
    )
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
    assert res.allowed is False
    assert res.checklist is not None
    size_item = next(i for i in res.checklist.items if i.key == "size")
    assert size_item.ok is False


def test_pipeline_rejects_invalid_credit_spread_params():
    """信用净收过低 → spread 清单失败。"""
    acct = AccountState(equity=50_000)
    pipe = TradingPipeline(acct, PaperBroker(acct))
    short = _quote(delta=0.25)
    prot = _quote(strike=110, delta=0.10, bid=0.30, ask=0.35, mid=0.32)
    res = pipe.evaluate_and_maybe_open(
        category=StrategyCategory.MEAN_REVERSION,
        gex_rows=_mr_rows(),
        spot=100,
        quote=short,
        iv_rank=20,
        protect_quote=prot,
        short_strike=107,
        wall_strike=105,
        width=5.0,
        credit=1.0,  # < width/2
        margin=400,
        structure_target_r=1.0,
        mr_side="bear_call",
        target_price=100,
    )
    # 策略机 validate_credit_spread 或清单均应拒绝
    assert res.allowed is False


def test_paper_broker_satisfies_broker_protocol():
    b = PaperBroker(AccountState(equity=50_000))
    assert isinstance(b, Broker)
    q = _quote()
    b.set_chain("SPY", [q])
    chain = b.get_chain("spy")
    assert len(chain) == 1
    assert chain[0].strike == q.strike
    assert b.get_chain("QQQ") == []


def test_paper_force_close_public_api():
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
    fill = b.force_close(pos.position_id, mark=1.5, reason="测试强平")
    assert fill is not None
    assert fill.reason == "测试强平"
    assert pos.position_id not in b.positions


def test_market_data_config_rejects_bad():
    with pytest.raises(MarketDataConfigError):
        MarketDataConfig(provider="nope").validate()
    with pytest.raises(MarketDataConfigError):
        MarketDataConfig(provider="fake", underlyings=[]).validate()
    with pytest.raises(MarketDataConfigError):
        MarketDataConfig(
            provider="opra", base_url=None, api_key="x", require_api_key=True
        ).validate()


def test_fake_feed_requires_connect_and_seeds():
    feed = FakeMarketDataFeed(MarketDataConfig(provider="fake"))
    with pytest.raises(RuntimeError):
        feed.get_spot("SPY")
    feed.seed(
        UnderlyingSnapshot(
            symbol="SPY",
            spot=100.0,
            iv=IvStats(0.2, 0.1, 0.4),
            gex_rows=tuple(_mr_rows()),
            chain=(_quote(),),
        )
    )
    feed.connect()
    assert feed.connected
    assert feed.get_spot("SPY") == 100.0
    assert len(feed.get_option_chain("SPY")) == 1
    feed.disconnect()
    assert not feed.connected


def test_opra_feed_validates_and_needs_transport():
    with pytest.raises(MarketDataConfigError):
        OpraMarketDataFeed(
            MarketDataConfig(provider="opra", base_url="", require_api_key=False)
        )
    cfg = MarketDataConfig(
        provider="opra",
        base_url="https://example.test",
        api_key="k",
        require_api_key=True,
    )
    feed = OpraMarketDataFeed(cfg, transport=None)
    with pytest.raises(OpraAdapterError):
        feed.connect()

    class _T:
        def fetch_snapshot(self, underlying: str) -> UnderlyingSnapshot:
            return UnderlyingSnapshot(symbol=underlying, spot=1.0)

    feed2 = build_feed(cfg, transport=_T())
    feed2.connect()
    assert feed2.get_spot("SPY") == 1.0


def test_moomoo_config_and_client_injection():
    with pytest.raises(MoomooConfigError):
        MoomooConfig(port=0).validate()
    with pytest.raises(MoomooConfigError):
        MoomooConfig(trading_env="REAL", allow_live_orders=False).validate()

    stub = MoomooBrokerStub(MoomooConfig())
    with pytest.raises(NotImplementedError):
        stub.connect()

    client = FakeMoomooClient()
    client.chains["SPY"] = [_quote()]
    live = MoomooBrokerStub(
        MoomooConfig(allow_live_orders=True, trading_env="SIMULATE"),
        client=client,
    )
    live.connect()
    assert live.get_chain("SPY")[0].symbol == "SPY"
    # 无 allow 时写拒绝
    denied = MoomooBrokerStub(
        MoomooConfig(allow_live_orders=False),
        client=client,
    )
    denied.connected = True
    denied.client = client
    with pytest.raises(NotImplementedError):
        denied.open_long(symbol="SPY", premium=2.0)

    # 未连接
    cold = MoomooBrokerStub(
        MoomooConfig(allow_live_orders=True),
        client=FakeMoomooClient(),
    )
    with pytest.raises(MoomooNotConnectedError):
        cold.open_long(symbol="SPY", premium=2.0)
