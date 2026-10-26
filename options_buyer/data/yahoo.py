"""Yahoo Finance 公开 Chart API（无需 API Key）。

端点：``https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}``

仅提供标的 OHLC 历史；**无历史期权链 / OPRA**。纸面回测通过
``backtest.public_run`` 用 Delta 近似把标的收益映射为权利金 bid/ask。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooDataError(RuntimeError):
    """Yahoo 拉取或解析失败。"""


@dataclass(frozen=True)
class OhlcBar:
    ts: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class YahooChartClient:
    """公开 Chart 客户端；可注入 ``opener`` 便于单测。"""

    user_agent: str = "Mozilla/5.0 (compatible; options-buyer-v17/1.7.2)"
    timeout_sec: float = 20.0
    # 可选：自定义 urlopen(request, timeout=...) → bytes
    opener: Any | None = None

    def fetch_daily(
        self,
        symbol: str,
        *,
        period1: int,
        period2: int,
    ) -> list[OhlcBar]:
        sym = symbol.strip().upper()
        if not sym:
            raise YahooDataError("symbol 不能为空")
        if period1 >= period2:
            raise YahooDataError("period1 必须 < period2")
        params = urllib.parse.urlencode(
            {
                "period1": int(period1),
                "period2": int(period2),
                "interval": "1d",
                "events": "history",
                "includeAdjustedClose": "true",
            }
        )
        url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(sym)) + f"?{params}"
        raw = self._get(url)
        return parse_chart_json(raw, symbol=sym)

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            if self.opener is not None:
                return self.opener(req, timeout=self.timeout_sec)
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise YahooDataError(f"HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise YahooDataError(f"网络错误: {e.reason}") from e


def parse_chart_json(raw: bytes | str | dict, *, symbol: str = "") -> list[OhlcBar]:
    """解析 Yahoo chart JSON 或本仓 fixture（含 ``bars`` 列表）。"""
    if isinstance(raw, dict):
        data = raw
    else:
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = raw
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise YahooDataError(f"JSON 无效: {e}") from e

    # Offline fixture shape
    if "bars" in data and isinstance(data["bars"], list):
        out: list[OhlcBar] = []
        for row in data["bars"]:
            out.append(
                OhlcBar(
                    ts=int(row["t"]),
                    open=float(row["o"]),
                    high=float(row["h"]),
                    low=float(row["l"]),
                    close=float(row["c"]),
                    volume=float(row.get("v") or 0.0),
                )
            )
        if not out:
            raise YahooDataError("fixture bars 为空")
        return out

    chart = data.get("chart") or {}
    err = chart.get("error")
    if err:
        raise YahooDataError(f"Yahoo chart error: {err}")
    results = chart.get("result") or []
    if not results:
        raise YahooDataError(f"无 chart result（symbol={symbol}）")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators") or {}).get("quote") or [{}]
    q0 = quote[0] if quote else {}
    opens = q0.get("open") or []
    highs = q0.get("high") or []
    lows = q0.get("low") or []
    closes = q0.get("close") or []
    volumes = q0.get("volume") or []
    bars: list[OhlcBar] = []
    for i, ts in enumerate(timestamps):
        c = closes[i] if i < len(closes) else None
        if c is None:
            continue
        o = opens[i] if i < len(opens) and opens[i] is not None else c
        h = highs[i] if i < len(highs) and highs[i] is not None else c
        l = lows[i] if i < len(lows) and lows[i] is not None else c
        v = volumes[i] if i < len(volumes) and volumes[i] is not None else 0.0
        bars.append(
            OhlcBar(
                ts=int(ts),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=float(v),
            )
        )
    if not bars:
        raise YahooDataError("解析后无有效 OHLC 行")
    return bars


def load_fixture(path: str | Path) -> list[OhlcBar]:
    p = Path(path)
    if not p.is_file():
        raise YahooDataError(f"fixture 不存在: {p}")
    return parse_chart_json(p.read_text(encoding="utf-8"))


@dataclass
class YahooConfig:
    """Yahoo 拉取配置（无密钥）。"""

    symbol: str = "SPY"
    lookback_days: int = 60
    timeout_sec: float = 20.0

    def validate(self) -> None:
        if not self.symbol.strip():
            raise YahooDataError("symbol 不能为空")
        if self.lookback_days < 2:
            raise YahooDataError("lookback_days 至少为 2")
        if self.timeout_sec <= 0:
            raise YahooDataError("timeout_sec 必须 > 0")
