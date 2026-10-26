# 期权买方订单流交易体系 v1.7（Python）

基于定稿版 v1.7 的**完整可计算规则引擎**与纸面交易/回测骨架。  
**不构成投资建议。** 期权买方存在权利金全损风险。

## 范围

| 模块 | 对应文档 |
| --- | --- |
| `core.gex` / `regime` / `trigger` | §3.1–3.3 结构 / 体制 / 触发 |
| `core.r` / `sizing` / `exits` | R、张数、止盈止损 |
| `core.iv_crush` / `liquidity` / `branch` / `spreads` | §3.4 / §4 |
| `core.extreme` / `correlation` / `expiry` | 极端熔断、相关性、到期管理 |
| `strategies.*` | §5 突破 / 3A / 均值回归步骤机 |
| `risk.*` | §6–7、§9、策略淘汰 |
| `signals.checklist` / `sop.daily` | §11 / §10 |
| `execution.paper` | 纸面开平仓（含 `get_chain` / `force_close`） |
| `execution.moomoo_stub` | Moomoo 可插拔适配器（默认拒绝真下单） |
| `data.*` | IV 公式 + `MarketDataFeed` / OPRA 适配骨架 |
| `backtest.engine` | §12 bid/ask 纸面回测 |
| `pipeline` | 端到端编排（墙体/清单门禁为真实计算） |

执行层（Moomoo OpenSecTradeContext）**默认不真下单**；请用 `PaperBroker`，接入步骤见 [`docs/plugging-in.md`](docs/plugging-in.md)。

## 安装 / 运行

```bash
python -m pip install -e ".[dev]"
PYTHONPATH=. python -m options_buyer.cli demo
PYTHONPATH=. python -m options_buyer.cli pipeline
PYTHONPATH=. python -m options_buyer.cli backtest
PYTHONPATH=. python -m pytest tests -q
```

## 示例

```bash
PYTHONPATH=. python examples/paper_day.py
```

## 审计

详见 [`AUDIT.md`](AUDIT.md)。许可见 [`LICENSE`](LICENSE)（Proprietary）。
