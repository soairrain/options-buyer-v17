"""第十一章开仓检查清单（结构化结果）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChecklistItem:
    key: str
    label: str
    ok: bool
    note: str = ""


@dataclass
class PreTradeChecklist:
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    def failures(self) -> list[ChecklistItem]:
        return [i for i in self.items if not i.ok]


def build_checklist(
    *,
    gex_regime_ok: bool,
    structure_active: bool,
    charm_ok: bool,
    flow_ok: bool,
    iv_branch_ok: bool,
    delta_dte_ok: bool,
    spread_params_ok: bool,
    liquidity_ok: bool,
    iv_crush_ok: bool,
    r_defined: bool,
    structure_target_ok: bool,
    size_ok: bool,
    day_budget_ok: bool,
    greeks_ok: bool,
    correlation_ok: bool,
    halt_clear: bool,
    pdt_clear: bool,
) -> PreTradeChecklist:
    items = [
        ChecklistItem("gex", "GEX 体制与 Zero Gamma 位置可交易", gex_regime_ok),
        ChecklistItem("structure", "结构位盘中仍活跃", structure_active),
        ChecklistItem("charm", "Charm 窗口不冲突或已减仓", charm_ok),
        ChecklistItem("flow", "BTO 净 Delta + V/OI≥1 且无 STO 抵消", flow_ok),
        ChecklistItem("iv", "IV Rank 分支正确", iv_branch_ok),
        ChecklistItem("delta_dte", "Delta/DTE 符合策略类型", delta_dte_ok),
        ChecklistItem("spread", "价差宽度/净支/净收满足 4.2/4.3", spread_params_ok),
        ChecklistItem("liq", "流动性硬过滤达标", liquidity_ok),
        ChecklistItem("crush", "IV Crush 净贡献 ≥20%", iv_crush_ok),
        ChecklistItem("r", "已按初始止损金额定义 R", r_defined),
        ChecklistItem("target", "结构目标 ≥1.5R / 信用 ≥1R", structure_target_ok),
        ChecklistItem("size", "张数按 0.5% 且 ≥1 张", size_ok),
        ChecklistItem("day", "日亏+新仓权利金 ≤2%", day_budget_ok),
        ChecklistItem("greeks", "组合 Greeks 不超限", greeks_ok),
        ChecklistItem("corr", "同方向高相关合计 ≤2%", correlation_ok),
        ChecklistItem("halt", "未触发连续止损/日亏熔断", halt_clear),
        ChecklistItem("pdt", "PDT 未触发", pdt_clear),
    ]
    return PreTradeChecklist(items=items)
