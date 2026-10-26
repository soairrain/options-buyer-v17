"""行情 / GEX 数据端口。调用方注入真实 OPRA/GEX 客户端即可驱动编排。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from options_buyer.core.gex import StrikeGex
from options_buyer.core.types import OptionQuote
from options_buyer.core.trigger import FlowPrint


@dataclass(frozen=True)
class IvStats:
    """IV Rank / Percentile 输入。"""

    current_iv: float
    year_low: float
    year_high: float
    history: tuple[float, ...] = ()


@dataclass(frozen=True)
class UnderlyingSnapshot:
    symbol: str
    spot: float
    iv: IvStats | None = None
    gex_rows: tuple[StrikeGex, ...] = ()
    chain: tuple[OptionQuote, ...] = ()
    flow_prints: tuple[FlowPrint, ...] = ()


@runtime_checkable
class MarketDataFeed(Protocol):
    """可注入行情源。"""

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    @property
    def connected(self) -> bool: ...

    def get_snapshot(self, underlying: str) -> UnderlyingSnapshot: ...

    def get_spot(self, underlying: str) -> float: ...

    def get_option_chain(self, underlying: str) -> list[OptionQuote]: ...

    def get_gex_rows(self, underlying: str) -> list[StrikeGex]: ...

    def get_iv_stats(self, underlying: str) -> IvStats: ...
