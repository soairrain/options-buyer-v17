# v1.7 文稿 vs 代码审计

审计时间：Asia/Shanghai 2026-10-26（补全轮）

## 总评

| 维度 | 结论 |
| --- | --- |
| 可计算规则 + 信号/SOP/回测骨架 | **已补全**（见下） |
| 实盘数据 / Moomoo 真连接 | **未接**（仅 stub；纸面默认） |
| 已实现规则正确性 | 核心 E1–E26 已修；新增模块有单测覆盖 |

---

## 一、已落地模块对照

| 文稿 | 代码 |
| --- | --- |
| §3.1 结构层 GEX | `core/gex.py` |
| §3.2 体制层 | `core/regime.py` |
| §3.3 触发层 | `core/trigger.py` |
| §3.4.0–3.4.4 合约/流动性/IV Crush/张数 | `branch` / `liquidity` / `iv_crush` / `sizing` / `data/iv_rank` |
| §3.5 / 3.5.2 执行风控与止盈 | `execution/paper.py` / `core/exits.py` |
| §3.4.3 极端行情 3×ATR | `core/extreme.py` + Paper 硬门禁 |
| §4 价差构建 | `core/spreads.py` |
| §5 三大策略步骤机 | `strategies/` |
| §6 风控熔断 | `risk/halt.py` |
| §7 Greeks | `risk/greeks.py` |
| §8 到期/指派 | `core/expiry.py` |
| §9 否决 | `risk/veto.py` |
| §10 SOP | `sop/daily.py` |
| §11 检查清单 | `signals/checklist.py` |
| §12 回测 / 执行层 | `backtest/engine.py`；`execution/moomoo_stub.py`（不接实盘） |
| 相关性 / 策略淘汰 | `core/correlation.py` / `risk/elimination.py` |

---

## 二、历史偏差 E1–E26

见本文件前几版记录：均已修复（信用保证金、借方时间止损、3A 分支、IV 路径、跳空 2R、Theta 买方门禁等）。

---

## 三、仍非本包职责（需外部系统）

- 实时 OPRA / GEX 数据源与 10–60s 重算调度
- Moomoo OpenSecTradeContext 真连与下单
- 长期历史期权 tick 存储与完整组合回测平台

调用方注入行情与链数据后，本包规则与步骤机可直接判定。

## 四、验证

`PYTHONPATH=. python3 -m pytest tests -q` → **56 passed**
