"""市场数据：IV 公式 + 可注入行情端口（fake / OPRA 适配骨架）。"""

from options_buyer.data.config import MarketDataConfig, MarketDataConfigError
from options_buyer.data.fake import FakeMarketDataFeed
from options_buyer.data.iv_rank import iv_percentile, iv_rank
from options_buyer.data.opra_adapter import OpraAdapterError, OpraMarketDataFeed, build_feed
from options_buyer.data.ports import IvStats, MarketDataFeed, UnderlyingSnapshot

__all__ = [
    "iv_rank",
    "iv_percentile",
    "MarketDataConfig",
    "MarketDataConfigError",
    "MarketDataFeed",
    "IvStats",
    "UnderlyingSnapshot",
    "FakeMarketDataFeed",
    "OpraMarketDataFeed",
    "OpraAdapterError",
    "build_feed",
]
