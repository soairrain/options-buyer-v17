"""OPRA / 供应商行情适配器骨架。

不发起真实 HTTP：注入 ``OpraTransport``（或测试 Fake）后即可使用。
接入真实供应商时只需实现 Transport，无需改编排层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from options_buyer.core.gex import StrikeGex
from options_buyer.core.types import OptionQuote
from options_buyer.data.config import MarketDataConfig, MarketDataConfigError
from options_buyer.data.ports import IvStats, MarketDataFeed, UnderlyingSnapshot


class OpraAdapterError(RuntimeError):
    """适配器运行期错误。"""


@runtime_checkable
class OpraTransport(Protocol):
    """供应商 SDK / REST 最小端口。"""

    def fetch_snapshot(self, underlying: str) -> UnderlyingSnapshot: ...


@dataclass
class OpraMarketDataFeed:
    """校验配置 + 委托 Transport；无 Transport 时 connect 失败（防静默空跑）。"""

    config: MarketDataConfig
    transport: OpraTransport | None = None
    _connected: bool = False

    def __post_init__(self) -> None:
        if self.config.provider not in ("opra", "custom"):
            raise MarketDataConfigError(
                f"OpraMarketDataFeed 需要 provider opra|custom，得到 {self.config.provider!r}"
            )
        self.config.validate()
        if self.config.provider == "opra":
            if not self.config.base_url:
                raise MarketDataConfigError("opra provider 需要 base_url")
            if self.config.require_api_key and not self.config.api_key:
                raise MarketDataConfigError("opra provider 需要 api_key")

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self.transport is None:
            raise OpraAdapterError(
                "未注入 OpraTransport。实现 fetch_snapshot 后传入，"
                "或使用 FakeMarketDataFeed；参见 docs/plugging-in.md。"
            )
        self.config.validate()
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def _require(self) -> OpraTransport:
        if not self._connected or self.transport is None:
            raise OpraAdapterError("行情未连接")
        return self.transport

    def get_snapshot(self, underlying: str) -> UnderlyingSnapshot:
        t = self._require()
        return t.fetch_snapshot(underlying.upper())

    def get_spot(self, underlying: str) -> float:
        return self.get_snapshot(underlying).spot

    def get_option_chain(self, underlying: str) -> list[OptionQuote]:
        return list(self.get_snapshot(underlying).chain)

    def get_gex_rows(self, underlying: str) -> list[StrikeGex]:
        return list(self.get_snapshot(underlying).gex_rows)

    def get_iv_stats(self, underlying: str) -> IvStats:
        iv = self.get_snapshot(underlying).iv
        if iv is None:
            raise OpraAdapterError(f"快照无 IV: {underlying}")
        return iv


def build_feed(
    config: MarketDataConfig,
    *,
    transport: OpraTransport | None = None,
) -> MarketDataFeed:
    """按 provider 构建 feed；fake 不需 transport，opra/custom 需要。"""
    from options_buyer.data.fake import FakeMarketDataFeed

    config.validate()
    if config.provider == "fake":
        return FakeMarketDataFeed(config=config)
    if config.provider in ("opra", "custom"):
        return OpraMarketDataFeed(config=config, transport=transport)
    raise MarketDataConfigError(f"不支持的 provider: {config.provider}")
