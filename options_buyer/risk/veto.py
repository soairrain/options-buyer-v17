"""第九章否决条件（可计算子集）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.types import (
    PDT_DAY_TRADES_LIMIT,
    PDT_EQUITY_THRESHOLD,
    AccountState,
    StrategyType,
)


@dataclass
class VetoContext:
    iv_rank: float = 0.0
    event_window: bool = False
    structure_active: bool = True
    charm_adverse: bool = False
    charm_sized_down: bool = False
    liquidity_ok: bool = True
    time_liquidity_ok: bool = True
    slip_gt_20pct_premium: bool = False
    rr_conflicts_gex_adverse: bool = False
    put_skew_premium_gt_30: bool = False
    used_spread_for_skew: bool = False
    iv_crush_ok: bool = True
    dte: int = 30
    in_time_stop_mgmt: bool = False
    mean_reversion_naked: bool = False
    debit_pct_of_width: float | None = None
    credit_pct_of_width: float | None = None
    protect_leg_ok: bool = True
    mr_target_inside_short: bool = True
    greeks_ok: bool = True
    block_new_buyer: bool = False  # 净 Theta>0：禁买方，信用仍可
    extreme_halt: bool = False
    correlation_premium_pct: float = 0.0
    structure_target_r: float = 1.5
    strategy: StrategyType = StrategyType.LONG
    used_spread_or_deep_itm: bool = False


@dataclass
class VetoResult:
    blocked: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_vetoes(account: AccountState, ctx: VetoContext) -> VetoResult:
    reasons: list[str] = []

    if ctx.iv_rank > 50 and ctx.strategy == StrategyType.LONG and not ctx.used_spread_or_deep_itm:
        reasons.append("1. IVR>50 未改用价差或 Deep ITM")

    if ctx.event_window and ctx.strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
        reasons.append("2. 事件窗口内新开裸买")

    if not ctx.structure_active:
        reasons.append("3. 结构墙体消失")

    if ctx.charm_adverse and not ctx.charm_sized_down:
        reasons.append("4. Charm 逆流且未减仓")

    if not ctx.liquidity_ok:
        reasons.append("5. 合约流动性不达标")

    if not ctx.time_liquidity_ok:
        reasons.append("6. 时间维度流动性不达标")

    if ctx.slip_gt_20pct_premium:
        reasons.append("7. 滑点预期 > 权利金 20%")

    if ctx.rr_conflicts_gex_adverse:
        reasons.append("8. RR 与 GEX 矛盾且 RR 不利")

    if ctx.put_skew_premium_gt_30 and not ctx.used_spread_for_skew:
        reasons.append("9. Put Skew 溢价 >30% 且未改价差")

    if not ctx.iv_crush_ok:
        reasons.append("10. IV Crush 净贡献 < 权利金 20%")

    if account.halted:
        reasons.append("11. 连续 3 笔止损或日亏 2% 已触发")

    if ctx.dte < 7 and not ctx.in_time_stop_mgmt and ctx.strategy != StrategyType.CREDIT_SPREAD:
        reasons.append("12. 到期 <7 天且未进入时间止损（禁止新开裸买）")

    if ctx.mean_reversion_naked and ctx.iv_rank > 30:
        reasons.append("13. 均值回归裸买且 IVR>30")

    if ctx.debit_pct_of_width is not None and ctx.debit_pct_of_width > 0.40:
        reasons.append("14. 借方价差净支出 > 宽度 40%")

    if ctx.credit_pct_of_width is not None and ctx.credit_pct_of_width < 0.50:
        reasons.append("14. 信用价差净收 < 宽度 1/2")

    if not ctx.protect_leg_ok:
        reasons.append("15. 信用价差保护腿流动性不达标")

    if not ctx.mr_target_inside_short:
        reasons.append("16. 均值回归信用价差目标在短腿外侧")

    if not ctx.greeks_ok:
        reasons.append("17. 组合净 Delta/Vega 超限")

    if ctx.block_new_buyer and ctx.strategy in (
        StrategyType.LONG,
        StrategyType.DEBIT_SPREAD,
        StrategyType.DEEP_ITM,
    ):
        reasons.append("17. 净 Theta 为正，不加买方仓位")

    # 18 PDT
    if (
        account.equity < PDT_EQUITY_THRESHOLD
        and account.day_trades_used_5d >= PDT_DAY_TRADES_LIMIT
    ):
        reasons.append(
            "18. PDT：账户 <$25,000 且过去 5 个交易日内已用尽 3 次日内交易"
        )

    if ctx.extreme_halt:
        reasons.append("19. 极端行情熔断")

    if ctx.correlation_premium_pct > 0.02:
        reasons.append("20. 同方向高相关仓位合计权利金 >2%")

    need = 1.0 if ctx.strategy == StrategyType.CREDIT_SPREAD else 1.5
    if ctx.structure_target_r < need:
        reasons.append("21. 结构目标不足")

    return VetoResult(blocked=bool(reasons), reasons=reasons)
