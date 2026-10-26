"""共享类型与常量（v1.7）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StrategyType(str, Enum):
    LONG = "long"  # 裸买
    DEBIT_SPREAD = "debit_spread"
    CREDIT_SPREAD = "credit_spread"
    DEEP_ITM = "deep_itm"


class StrategyCategory(str, Enum):
    BREAKOUT = "breakout"
    ABSORPTION_3A = "absorption_3a"
    MEAN_REVERSION = "mean_reversion"


class ExitReason(str, Enum):
    STOP_1R = "stop_1r"
    TAKE_PROFIT = "take_profit"
    TAKE_HALF = "take_half"
    TIME_STOP = "time_stop"
    STRUCTURE_INVALID = "structure_invalid"
    IV_CRUSH_EXIT = "iv_crush_exit"
    DAY_HALT = "day_halt"
    MANUAL = "manual"
    EXPIRY = "expiry"


# 仓位与风控常量（账户百分比）
SINGLE_PREMIUM_MAX = 0.005  # 单笔权利金 ≤ 0.5%
SIGNAL_PREMIUM_MAX = 0.01  # 单信号加仓后 ≤ 1%
CATEGORY_PREMIUM_MAX = 0.02  # 单策略类别 ≤ 2%
TOTAL_PREMIUM_MAX = 0.03  # 合计权利金 ≤ 3%
CREDIT_MARGIN_MAX = 0.03  # 单笔信用保证金 ≤ 3%
DAY_LOSS_HARD_CAP = 0.02  # 日亏硬上限 2%
R_FRACTION = 0.5  # R = 初始风险 × 50%

# 连续止损熔断
CONSECUTIVE_STOP_HALT = 3

# Greeks 上限
NET_DELTA_MAX = 0.10  # 账户 10%
NET_VEGA_MAX = 0.005  # 账户 0.5% / IV 点
NET_THETA_WARN = 0.001  # 账户 0.1%/天

# 结构目标
STRUCTURE_TARGET_LONG = 1.5
STRUCTURE_TARGET_CREDIT = 1.0

# 时间
TIME_STOP_DTE = 7
NO_NEW_LONG_DTE = 7

# IV Crush
IV_CRUSH_MIN_RATIO = 0.20

# PDT
PDT_EQUITY_THRESHOLD = 25_000.0
PDT_DAY_TRADES_LIMIT = 3
PDT_LOOKBACK_DAYS = 5

MULTIPLIER = 100


@dataclass
class OptionQuote:
    symbol: str
    strike: float
    dte: int
    right: str  # "C" | "P"
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    iv: float = 0.0
    oi: int = 0
    volume: int = 0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 1.0
        return self.spread / self.mid


@dataclass
class Position:
    position_id: str
    strategy: StrategyType
    category: StrategyCategory
    symbol: str
    contracts: int
    entry_premium: float  # 单张报价（权利金或净支出；信用为净收）
    width: float = 0.0  # 价差宽度（信用/借方）
    credit: float = 0.0  # 信用净收 C
    r_dollars: float = 0.0  # 1R 美元（账户口径，含乘数与张数）
    r_per_contract: float = 0.0  # 单张 1R（报价单位）
    remaining_fraction: float = 1.0
    added_once: bool = False
    is_add: bool = False  # 本笔是否为加仓腿；整笔止损仍计 1 笔，不因加仓多计
    dte_at_entry: int = 30
    structure_target_r: float = 1.5
    margin: float = 0.0  # 信用价差保证金美元
    premium_reserved: float = 0.0  # 开仓时占用的权利金/风险预算（美元）


@dataclass
class AccountState:
    equity: float
    day_realized_pnl: float = 0.0
    open_premium_by_category: dict[str, float] = field(default_factory=dict)
    open_premium_total: float = 0.0
    # 信用价差保证金占用（与权利金预算独立，§4.3 / §六）
    open_credit_margin_total: float = 0.0
    consecutive_stops: int = 0
    halted: bool = False
    halt_reason: Optional[str] = None
    day_trades_used_5d: int = 0
    opens_today: int = 0
    wins_today: int = 0
    consecutive_wins: int = 0
    extreme_pause_until: Optional[float] = None  # epoch seconds
