# 如何接入行情与券商

本包默认**纸面**运行。行情与实盘通过可注入端口接入；CI 使用 Fake，不发起网络请求。

## 行情（Market data）

1. 实现或使用现成 `MarketDataFeed`（见 `options_buyer.data.ports`）。
2. 配置 `MarketDataConfig` 并 `validate()`：
   - `provider="fake"` → `FakeMarketDataFeed`（测试）
   - `provider="opra"` → `OpraMarketDataFeed` + 你的 `OpraTransport.fetch_snapshot`
3. 工厂：`from options_buyer.data import build_feed`

```python
from options_buyer.data import MarketDataConfig, build_feed, IvStats, UnderlyingSnapshot
from options_buyer.core.gex import StrikeGex
from options_buyer.core.types import OptionQuote

cfg = MarketDataConfig(provider="fake", underlyings=["SPY"])
feed = build_feed(cfg)
feed.seed(
    UnderlyingSnapshot(
        symbol="SPY",
        spot=100.0,
        iv=IvStats(0.18, 0.10, 0.40),
        gex_rows=(StrikeGex(100, 10, -80, 1000, 1000, 1000, 1000),),
        chain=(OptionQuote("SPY", 105, 30, "C", 1.95, 2.0, 1.975, 0.4, oi=1000, volume=500),),
    )
)
feed.connect()
snap = feed.get_snapshot("SPY")
# 将 snap.gex_rows / chain / iv 传入 TradingPipeline.evaluate_and_maybe_open(...)
```

真实 OPRA 供应商：实现 `OpraTransport.fetch_snapshot`，用官方 SDK/REST 填 `UnderlyingSnapshot`，再：

```python
cfg = MarketDataConfig(
    provider="opra",
    base_url="https://your-vendor.example",
    api_key="...",           # 勿提交密钥；用环境变量注入
    require_api_key=True,
    underlyings=["SPY"],
    poll_interval_sec=30,
)
feed = build_feed(cfg, transport=YourTransport(cfg))
feed.connect()
```

建议盘中每 `poll_interval_sec`（文档建议 10–60s）重算 GEX 行后调用 `build_structure` / pipeline。

## 券商（Moomoo / OpenD）

1. 实现 `MoomooClientPort`（`connect` / `disconnect` / `get_option_chain` / `place_order`），或单测用 `FakeMoomooClient`。
2. `MoomooConfig.validate()`：`SIMULATE` 默认；`REAL` 必须 `allow_live_orders=True`。
3. **先过规则门禁与 `PaperBroker` 试算，再转发实盘。**

```python
from options_buyer.execution import MoomooBrokerStub, MoomooConfig, FakeMoomooClient

cfg = MoomooConfig(host="127.0.0.1", port=11111, trading_env="SIMULATE", allow_live_orders=True)
client = FakeMoomooClient()  # 或你的 OpenD 封装
broker = MoomooBrokerStub(cfg, client=client)
broker.connect()
chain = broker.get_chain("SPY")
```

未注入 client 时 `connect()` 抛 `NotImplementedError`；未开 `allow_live_orders` 时写操作拒绝。

## 纸面链

`PaperBroker.set_chain(underlying, quotes)` / `get_chain` 满足 `Broker` Protocol，便于本地联调。

## 公开 API 纸面回测（Yahoo Chart，无 Key）

**选型**：Yahoo Finance 公开 Chart API  
`https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}`  
- 无需注册 / API Key（stdlib `urllib`）
- 提供标的日频 OHLC
- **免费层做不到**：历史期权链、OPRA tick、真实 GEX；权利金由固定 Delta 近似合成

曾评估 Stooq（现有 JS 挑战挡自动化）、Alpha Vantage / Polygon / Finnhub（需 Key 且免费额度紧、期权历史仍稀缺）。对本仓库 `BacktestEngine`（bid/ask 序列）而言，Yahoo OHLC + Delta 代理是零密钥下的最佳拟合。

### 离线（CI / 默认）

```bash
PYTHONPATH=. python -m options_buyer.cli public-backtest
# 或
PYTHONPATH=. python examples/public_backtest.py
```

默认读取 `tests/fixtures/yahoo_spy_daily.json`（录制的 Yahoo 日线），**不联网**。

### 联网（本机可选）

```bash
PYTHONPATH=. python -m options_buyer.cli public-backtest --live --symbol SPY --days 60
```

参数：`--premium` / `--delta` / `--half-spread` / `--dte` 控制合成权利金路径。  
实现：`options_buyer.data.yahoo` + `options_buyer.backtest.public_run`。
