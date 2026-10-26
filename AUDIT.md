# v1.7 文稿 vs 代码审计

审计时间：Asia/Shanghai 2026-10-26（缺口补全轮）

## 总评

| 维度 | 结论 |
| --- | --- |
| 可计算规则 + 信号/SOP/回测骨架 | **已补全**（见下） |
| 编排门禁（墙体 / 清单） | **已按真实输入计算**（不再硬编码 True） |
| 行情 / Moomoo 适配 | **可插拔端口 + Fake 校验**；真下单/真 HTTP 需调用方注入凭证与客户端 |
| 已实现规则正确性 | 核心 E1–E26 已修；缺口补全有单测覆盖 |

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
| §12 回测 / 执行层 | `backtest/engine.py`；`execution/moomoo_stub.py`（可插拔） |
| 相关性 / 策略淘汰 | `core/correlation.py` / `risk/elimination.py` |
| 行情端口 | `data/ports.py` / `fake.py` / `opra_adapter.py` |

---

## 二、历史偏差 E1–E26

见本文件前几版记录：均已修复（信用保证金、借方时间止损、3A 分支、IV 路径、跳空 2R、Theta 买方门禁等）。

缺口补全轮另修：`pipeline` 墙外均值回归误开、清单硬编码 True、`PaperBroker.get_chain`、回测私有 API、CLI 主路径、LICENSE。

---

## 三、仍需外部系统（凭证 / 真连接）

- 实时 OPRA / GEX 供应商账号与 Transport 实现
- Moomoo OpenD 真连与多腿下单映射
- 长期历史期权 tick 存储与完整组合回测平台

端口、配置校验与 Fake 已就绪；接入说明见 `docs/plugging-in.md`。

## 四、验证

`PYTHONPATH=. python3 -m pytest tests -q` → **75 passed**（含编排墙体/清单、Broker 协议、行情与 Moomoo Fake 适配器回归）。
