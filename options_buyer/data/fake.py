"""内存假行情源：单测与本地编排无需网络。"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.gex import StrikeGex
from options_buyer.core.trigger import FlowPrint
from options_buyer.core.types import OptionQuote
from options_buyer.data.config import MarketDataConfig, MarketDataConfigError
from options_buyer.data.ports import IvStats, UnderlyingSnapshot


@dataclass
class FakeMarketDataFeed:
    """可预置 snapshot；connect 后可读。"""

    config: MarketDataConfig = field(default_factory=MarketDataConfig)
    snapshots: dict[str, UnderlyingSnapshot] = field(default_factory=dict)
    _connected: bool = False
    fail_connect: bool = False

    def __post_init__(self) -> None:
        self.config.validate()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self.fail_connect:
            raise ConnectionError("FakeMarketDataFeed: 模拟连接失败")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def _require(self) -> None:
        if not self._connected:
            raise RuntimeError("行情未连接：先调用 connect()")

    def seed(self, snap: UnderlyingSnapshot) -> None:
        self.snapshots[snap.symbol.upper()] = snap

    def get_snapshot(self, underlying: str) -> UnderlyingSnapshot:
        self._require()
        key = underlying.upper()
        if key not in self.snapshots:
            raise KeyError(f"无假行情: {key}")
        return self.snapshots[key]

    def get_spot(self, underlying: str) -> float:
        return self.get_snapshot(underlying).spot

    def get_option_chain(self, underlying: str) -> list[OptionQuote]:
        return list(self.get_snapshot(underlying).chain)

    def get_gex_rows(self, underlying: str) -> list[StrikeGex]:
        return list(self.get_snapshot(underlying).gex_rows)

    def get_iv_stats(self, underlying: str) -> IvStats:
        iv = self.get_snapshot(underlying).iv
        if iv is None:
            raise KeyError(f"无 IV 统计: {underlying}")
        return iv


def build_feed(config: MarketDataConfig) -> FakeMarketDataFeed:
    """仅构建 fake；opra/custom 见 ``opra_adapter.build_feed``。"""
    config.validate()
    if config.provider != "fake":
        raise MarketDataConfigError(
            f"build_feed(fake) 不支持 provider={config.provider}"
        )
    return FakeMarketDataFeed(config=config)
