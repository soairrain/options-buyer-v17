"""执行层抽象接口。实盘适配器须实现本协议；默认仅纸面。"""

from __future__ import annotations

from typing import Protocol

from options_buyer.core.types import OptionQuote, Position, StrategyCategory, StrategyType
from options_buyer.execution.paper import Fill


class Broker(Protocol):
    def open_long(
        self,
        *,
        symbol: str,
        premium: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        strategy: StrategyType = StrategyType.LONG,
    ) -> Position | None: ...

    def open_debit(
        self,
        *,
        symbol: str,
        net_debit: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        width: float = 0.0,
    ) -> Position | None: ...

    def open_credit(
        self,
        *,
        symbol: str,
        width: float,
        credit: float,
        margin: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        contracts: int = 1,
    ) -> Position | None: ...

    def mark_exit(self, position_id: str, *, mark: float, dte: int) -> Fill | None: ...

    def get_chain(self, underlying: str) -> list[OptionQuote]: ...
