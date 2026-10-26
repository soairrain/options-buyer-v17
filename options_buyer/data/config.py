"""行情源配置形状与校验（无网络副作用）。"""

from __future__ import annotations

from dataclasses import dataclass, field


class MarketDataConfigError(ValueError):
    """行情配置非法。"""


@dataclass
class MarketDataConfig:
    """通用行情配置。

    provider:
      - ``fake``：内存假源（测试）
      - ``opra``：需注入实现了 ``MarketDataFeed`` 的 OPRA/供应商客户端
      - ``custom``：任意注入 feed
      - ``yahoo``：公开 Chart OHLC（见 ``data.yahoo`` / ``public-backtest``；无期权链历史）
    """

    provider: str = "fake"
    api_key: str | None = None
    base_url: str | None = None
    underlyings: list[str] = field(default_factory=lambda: ["SPY"])
    poll_interval_sec: float = 30.0
    timeout_sec: float = 10.0
    require_api_key: bool = False

    def validate(self) -> None:
        p = (self.provider or "").strip().lower()
        if p not in ("fake", "opra", "custom", "yahoo"):
            raise MarketDataConfigError(
                f"未知 provider={self.provider!r}；允许: fake | opra | custom | yahoo"
            )
        self.provider = p
        if not self.underlyings:
            raise MarketDataConfigError("underlyings 不能为空")
        cleaned = [u.strip().upper() for u in self.underlyings if u and str(u).strip()]
        if not cleaned:
            raise MarketDataConfigError("underlyings 无有效标的")
        self.underlyings = cleaned
        if self.poll_interval_sec <= 0:
            raise MarketDataConfigError("poll_interval_sec 必须 > 0")
        if self.timeout_sec <= 0:
            raise MarketDataConfigError("timeout_sec 必须 > 0")
        if self.provider == "opra" and self.require_api_key and not self.api_key:
            raise MarketDataConfigError("opra provider 需要 api_key")
        if self.provider == "opra" and not self.base_url:
            raise MarketDataConfigError("opra provider 需要 base_url")
