"""Moomoo / OpenSecTradeContext 实盘适配器。

默认拒绝真下单：须注入满足 `MoomooClientPort` 的客户端，并显式
`allow_live_orders=True` 才转发委托。CI / 单测使用 `FakeMoomooClient`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from options_buyer.core.types import OptionQuote, Position, StrategyCategory, StrategyType
from options_buyer.execution.paper import Fill


class MoomooConfigError(ValueError):
    """配置校验失败。"""


class MoomooNotConnectedError(RuntimeError):
    """未连接或客户端未注入。"""


@dataclass
class MoomooConfig:
    host: str = "127.0.0.1"
    port: int = 11111
    trading_env: str = "SIMULATE"  # SIMULATE | REAL
    unlock_password: str | None = None
    # 真下单开关：即使已连接，默认仍拒绝，防止误用
    allow_live_orders: bool = False

    def validate(self) -> None:
        if not self.host or not str(self.host).strip():
            raise MoomooConfigError("host 不能为空")
        if not (1 <= int(self.port) <= 65535):
            raise MoomooConfigError(f"port 非法: {self.port}")
        env = (self.trading_env or "").upper()
        if env not in ("SIMULATE", "REAL"):
            raise MoomooConfigError("trading_env 须为 SIMULATE 或 REAL")
        self.trading_env = env
        if env == "REAL" and not self.allow_live_orders:
            raise MoomooConfigError(
                "REAL 环境必须显式 allow_live_orders=True（且仅在确认风控门禁后）"
            )


@runtime_checkable
class MoomooClientPort(Protocol):
    """可注入的 Moomoo SDK 端口（由调用方用官方 OpenD 客户端实现）。"""

    def connect(self, host: str, port: int, trading_env: str) -> None: ...

    def disconnect(self) -> None: ...

    def get_option_chain(self, underlying: str) -> list[OptionQuote]: ...

    def place_order(
        self,
        *,
        side: str,
        symbol: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> str:
        """返回 broker order id。"""
        ...


@dataclass
class FakeMoomooClient:
    """单测/本地假客户端：内存链 + 记录委托，不碰网络。"""

    chains: dict[str, list[OptionQuote]] = field(default_factory=dict)
    orders: list[dict] = field(default_factory=list)
    connected: bool = False
    fail_connect: bool = False

    def connect(self, host: str, port: int, trading_env: str) -> None:
        del host, port, trading_env
        if self.fail_connect:
            raise ConnectionError("FakeMoomooClient: 模拟连接失败")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_option_chain(self, underlying: str) -> list[OptionQuote]:
        if not self.connected:
            raise MoomooNotConnectedError("未连接")
        return list(self.chains.get(underlying.upper(), []))

    def place_order(
        self,
        *,
        side: str,
        symbol: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
    ) -> str:
        if not self.connected:
            raise MoomooNotConnectedError("未连接")
        oid = f"fake-{len(self.orders) + 1}"
        self.orders.append(
            {
                "id": oid,
                "side": side,
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
            }
        )
        return oid


class MoomooBrokerStub:
    """实盘适配器：校验配置、管理连接、在许可时转发到注入客户端。

    未注入客户端或未 `allow_live_orders` 时，所有写操作拒绝。
    名称保留 Stub 以兼容既有 import；行为已是完整可插拔适配器。
    """

    def __init__(
        self,
        config: MoomooConfig | None = None,
        *,
        client: MoomooClientPort | None = None,
    ) -> None:
        self.config = config or MoomooConfig()
        self.config.validate()
        self.client = client
        self.connected = False

    def connect(self) -> None:
        if self.client is None:
            raise NotImplementedError(
                "未注入 MoomooClientPort。请传入官方 OpenD 封装或 FakeMoomooClient；"
                "参见 docs/plugging-in.md。"
            )
        self.client.connect(
            self.config.host, self.config.port, self.config.trading_env
        )
        self.connected = True

    def disconnect(self) -> None:
        if self.client is not None and self.connected:
            self.client.disconnect()
        self.connected = False

    def _require_live(self) -> MoomooClientPort:
        if self.client is None:
            raise MoomooNotConnectedError("无客户端")
        if not self.connected:
            raise MoomooNotConnectedError("未连接：先调用 connect()")
        if not self.config.allow_live_orders:
            raise NotImplementedError(
                "拒绝实盘下单：设置 MoomooConfig(allow_live_orders=True) 并先过 Paper/规则门禁"
            )
        return self.client

    def get_chain(self, underlying: str) -> list[OptionQuote]:
        if self.client is None or not self.connected:
            return []
        return self.client.get_option_chain(underlying)

    def open_long(self, **kwargs) -> Position | None:
        client = self._require_live()
        symbol = str(kwargs.get("symbol", ""))
        premium = float(kwargs["premium"])
        # 张数由上游 sizing 决定；此处最小转发形态
        contracts = int(kwargs.get("contracts", 1))
        client.place_order(
            side="BUY", symbol=symbol, quantity=contracts, price=premium
        )
        return None  # 实盘持仓同步由调用方根据成交回报构建

    def open_debit(self, **kwargs) -> Position | None:
        del kwargs
        self._require_live()
        raise NotImplementedError(
            "借方价差需多腿下单：在注入客户端中实现 spread 下单后由此转发"
        )

    def open_credit(self, **kwargs) -> Position | None:
        del kwargs
        self._require_live()
        raise NotImplementedError(
            "信用价差需多腿下单：在注入客户端中实现 spread 下单后由此转发"
        )

    def mark_exit(self, position_id: str, **kwargs) -> Fill | None:
        del position_id, kwargs
        client = self._require_live()
        del client
        raise NotImplementedError(
            "平仓需持仓映射：由调用方根据 position_id→券商单映射后 place_order(SELL)"
        )
