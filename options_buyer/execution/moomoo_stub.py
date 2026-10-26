"""Moomoo / OpenSecTradeContext 实盘适配器占位。

本包为纸面规则引擎：不发起实盘连接、不下单。
接入时实现 `connect` / `place_limit` / `get_chain`，并由上层用 PaperBroker
规则先过门禁再委托。
"""

from __future__ import annotations

from dataclasses import dataclass

from options_buyer.core.types import OptionQuote, Position, StrategyCategory, StrategyType
from options_buyer.execution.paper import Fill


@dataclass
class MoomooConfig:
    host: str = "127.0.0.1"
    port: int = 11111
    trading_env: str = "SIMULATE"  # SIMULATE | REAL — 默认模拟
    unlock_password: str | None = None


class MoomooBrokerStub:
    """未接实盘：所有写操作拒绝；读操作返回空。"""

    def __init__(self, config: MoomooConfig | None = None) -> None:
        self.config = config or MoomooConfig()
        self.connected = False

    def connect(self) -> None:
        raise NotImplementedError(
            "Moomoo 实盘未接入。请使用 PaperBroker；接入时实现 OpenSecTradeContext。"
        )

    def get_chain(self, underlying: str) -> list[OptionQuote]:
        del underlying
        if not self.connected:
            return []
        raise NotImplementedError("未实现期权链拉取")

    def open_long(self, **kwargs) -> Position | None:
        del kwargs
        raise NotImplementedError("拒绝实盘下单：使用 PaperBroker")

    def open_debit(self, **kwargs) -> Position | None:
        del kwargs
        raise NotImplementedError("拒绝实盘下单：使用 PaperBroker")

    def open_credit(self, **kwargs) -> Position | None:
        del kwargs
        raise NotImplementedError("拒绝实盘下单：使用 PaperBroker")

    def mark_exit(self, position_id: str, **kwargs) -> Fill | None:
        del position_id, kwargs
        raise NotImplementedError("拒绝实盘下单：使用 PaperBroker")
