"""市场数据适配占位（GEX/IV/链）。实盘数据源由调用方注入。"""

from options_buyer.data.iv_rank import iv_percentile, iv_rank

__all__ = ["iv_rank", "iv_percentile"]
