"""第二节：R 定义与结构目标检查。"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import (
    MULTIPLIER,
    R_FRACTION,
    STRUCTURE_TARGET_CREDIT,
    STRUCTURE_TARGET_LONG,
    StrategyType,
)


@dataclass(frozen=True)
class RSpec:
    strategy: StrategyType
    r_per_contract: float  # 报价单位（未乘 100）
    r_dollars: float  # 含张数与乘数的账户美元
    basis: float  # 初始权利金 / 净支出 / 最大亏损（报价）
    min_structure_target_r: float


def compute_r(
    strategy: StrategyType,
    *,
    premium: float | None = None,
    debit: float | None = None,
    width: float | None = None,
    credit: float | None = None,
    contracts: int = 1,
) -> RSpec:
    """按策略类型计算 1R。

    - 裸买 / Deep ITM：R = 初始权利金 × 50%
    - 借方价差：R = 净支出 × 50%
    - 信用价差：最大亏损 = W − C；R = (W − C) / 2
    """
    if contracts < 1:
        raise ValueError("contracts must be >= 1")

    if strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
        if premium is None or premium <= 0:
            raise ValueError("long/deep_itm requires positive premium")
        basis = premium
        r_pc = basis * R_FRACTION
        min_tgt = STRUCTURE_TARGET_LONG
    elif strategy == StrategyType.DEBIT_SPREAD:
        if debit is None or debit <= 0:
            raise ValueError("debit_spread requires positive debit")
        basis = debit
        r_pc = basis * R_FRACTION
        min_tgt = STRUCTURE_TARGET_LONG
    elif strategy == StrategyType.CREDIT_SPREAD:
        if width is None or credit is None:
            raise ValueError("credit_spread requires width and credit")
        if credit < width / 2:
            raise ValueError("credit must be >= width/2 (v1.7 forbids < 1/2)")
        max_loss = width - credit
        if max_loss <= 0:
            raise ValueError("max loss must be positive")
        basis = max_loss
        r_pc = max_loss * R_FRACTION  # = (W - C) / 2
        min_tgt = STRUCTURE_TARGET_CREDIT
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    r_dollars = r_pc * MULTIPLIER * contracts
    return RSpec(
        strategy=strategy,
        r_per_contract=r_pc,
        r_dollars=r_dollars,
        basis=basis,
        min_structure_target_r=min_tgt,
    )


def structure_target_ok(structure_target_r: float, strategy: StrategyType) -> bool:
    need = (
        STRUCTURE_TARGET_CREDIT
        if strategy == StrategyType.CREDIT_SPREAD
        else STRUCTURE_TARGET_LONG
    )
    return structure_target_r >= need
