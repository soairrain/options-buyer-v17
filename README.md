# 期权买方订单流交易体系 v1.7（Python）

基于定稿版 v1.7 的规则引擎与纸面交易模拟器。  
**不构成投资建议。** 期权买方存在权利金全损风险。

## 范围

本包实现文档中的**可计算规则**（纯 Python，无券商依赖）：

| 模块 | 对应文档 |
| --- | --- |
| `core.r` | 第二节 R 定义 |
| `core.sizing` | 3.4.4 张数换算、仓位上限 |
| `core.exits` | 3.5.2 止盈/止损/滚动 |
| `core.iv_crush` | 3.4.2 IV Crush 期望 |
| `core.liquidity` | 3.4.3 流动性硬过滤 |
| `core.branch` | 3.4.0 / 4.1 策略分支 |
| `risk.halt` | 连续 3 笔止损状态机、2% 日亏 |
| `risk.veto` | 第九章否决条件（可计算子集） |
| `risk.greeks` | 第七章组合 Greeks 上限 |
| `signals.checklist` | 第十一章开仓检查清单 |
| `execution.paper` | 纸面账户与开平仓流程 |

执行层（Moomoo OpenSecTradeContext）预留接口，未接实盘。

## 安装 / 运行

```bash
python -m pip install -e ".[dev]"   # 或直接 PYTHONPATH=. 运行
PYTHONPATH=. python -m options_buyer.cli demo
PYTHONPATH=. python -m pytest tests -q
```

## 示例

```bash
PYTHONPATH=. python examples/paper_day.py
```
