"""4.2 / 4.3 价差构建参数校验。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadBuildResult:
    ok: bool
    reason: str = ""


def validate_debit_spread(
    *,
    long_delta: float,
    short_delta: float,
    width: float,
    net_debit: float,
    accept_1_5_rr: bool = False,
) -> SpreadBuildResult:
    """借方价差：长腿 0.50–0.60，短腿 0.25–0.35；净支出 ≤33.3%（或 40%@1.5:1）。"""
    if not (0.50 <= abs(long_delta) <= 0.60):
        return SpreadBuildResult(False, "长腿 Delta 应在 0.50–0.60")
    if not (0.25 <= abs(short_delta) <= 0.35):
        return SpreadBuildResult(False, "短腿 Delta 应在 0.25–0.35")
    if width <= 0:
        return SpreadBuildResult(False, "宽度必须 > 0")
    max_pct = 0.40 if accept_1_5_rr else 1 / 3
    if net_debit / width > max_pct + 1e-12:
        return SpreadBuildResult(
            False, f"净支出 > 宽度 {max_pct:.1%}，放弃"
        )
    return SpreadBuildResult(True, "ok")


def validate_credit_spread(
    *,
    short_delta: float,
    protect_delta: float,
    width: float,
    net_credit: float,
) -> SpreadBuildResult:
    """信用价差：短腿 0.20–0.30，保护腿 0.05–0.15；净收 ≥ 宽度 1/2。"""
    if not (0.20 <= abs(short_delta) <= 0.30):
        return SpreadBuildResult(False, "短腿 Delta 应在 0.20–0.30")
    if not (0.05 <= abs(protect_delta) <= 0.15):
        return SpreadBuildResult(False, "保护腿 Delta 应在 0.05–0.15")
    if width <= 0:
        return SpreadBuildResult(False, "宽度必须 > 0")
    if net_credit < width / 2 - 1e-12:
        return SpreadBuildResult(False, "净收 < 宽度 1/2，禁止")
    return SpreadBuildResult(True, "ok")
