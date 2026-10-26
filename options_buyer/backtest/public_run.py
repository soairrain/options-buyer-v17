"""公开行情 → 纸面期权回测。

免费 API（Yahoo Chart）只给标的 OHLC，不含历史期权链。
本模块用固定 Delta 近似把现货变动映射为权利金 mid，再加半价差得到 bid/ask，
喂入 ``BacktestEngine``（开仓吃 ask、平仓吃 bid）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from options_buyer.backtest.engine import BacktestEngine, BacktestResult, BarQuote
from options_buyer.core.types import StrategyCategory, StrategyType
from options_buyer.data.yahoo import (
    OhlcBar,
    YahooChartClient,
    YahooConfig,
    YahooDataError,
    load_fixture,
)


@dataclass
class PublicBacktestParams:
    symbol: str = "SPY"
    lookback_days: int = 60
    entry_premium: float = 2.0
    delta: float = 0.45  # ATM/稍实值买方近似
    half_spread: float = 0.05  # 绝对半价差（美元权利金）
    start_dte: int = 45
    equity: float = 50_000.0
    category: StrategyCategory = StrategyCategory.BREAKOUT
    structure_target_r: float = 2.0
    # 数据源：fixture 路径优先；否则 live Yahoo
    fixture_path: str | None = None
    live: bool = False

    def validate(self) -> None:
        if self.entry_premium <= 0:
            raise ValueError("entry_premium 必须 > 0")
        if not (0.05 <= self.delta <= 0.95):
            raise ValueError("delta 应在 0.05–0.95")
        if self.half_spread < 0:
            raise ValueError("half_spread 不能为负")
        if self.start_dte < 7:
            raise ValueError("start_dte 建议 ≥7（与 NO_NEW_LONG_DTE 对齐）")
        if self.fixture_path is None and not self.live:
            raise ValueError("须提供 fixture_path，或设 live=True 拉 Yahoo")


@dataclass
class PublicBacktestReport:
    symbol: str
    source: str
    n_underlying_bars: int
    n_option_bars: int
    result: BacktestResult
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "n_underlying_bars": self.n_underlying_bars,
            "n_option_bars": self.n_option_bars,
            "day_pnl": self.result.day_pnl,
            "ending_equity": self.result.ending_equity,
            "fills": len(self.result.fills),
            "trades": len(self.result.trade_results),
            "engine_notes": self.result.notes,
            "notes": self.notes,
            "fill_reasons": [f.reason for f in self.result.fills if f.side == "close"],
        }


def ohlc_to_option_bars(
    ohlc: list[OhlcBar],
    *,
    entry_premium: float,
    delta: float,
    half_spread: float,
    start_dte: int,
) -> list[BarQuote]:
    """标的收盘价序列 → 合成权利金 bid/ask。

    mid_t = max(floor, mid_{t-1} + delta * (S_t - S_{t-1}))
    bid/ask = mid ∓ half_spread（ask 至少高于 bid）。
    """
    if len(ohlc) < 2:
        raise ValueError("至少需要 2 根 OHLC")
    bars: list[BarQuote] = []
    mid = float(entry_premium)
    floor = max(0.05, half_spread * 2 + 0.01)
    prev_s = ohlc[0].close
    for i, row in enumerate(ohlc):
        if i > 0:
            mid = max(floor, mid + delta * (row.close - prev_s))
        prev_s = row.close
        bid = max(0.01, mid - half_spread)
        ask = max(bid + 0.01, mid + half_spread)
        dte = max(0, start_dte - i)
        bars.append(
            BarQuote(
                ts=float(row.ts),
                bid=round(bid, 4),
                ask=round(ask, 4),
                iv=None,
                underlying=row.close,
                dte=dte,
            )
        )
    return bars


def load_ohlc(params: PublicBacktestParams) -> tuple[list[OhlcBar], str]:
    params.validate()
    if params.fixture_path:
        bars = load_fixture(params.fixture_path)
        return bars, f"fixture:{params.fixture_path}"
    cfg = YahooConfig(
        symbol=params.symbol,
        lookback_days=params.lookback_days,
    )
    cfg.validate()
    period2 = int(time.time())
    period1 = period2 - int(params.lookback_days) * 86400
    client = YahooChartClient(timeout_sec=cfg.timeout_sec)
    bars = client.fetch_daily(cfg.symbol, period1=period1, period2=period2)
    return bars, "yahoo_chart_v8_live"


def run_public_backtest(params: PublicBacktestParams) -> PublicBacktestReport:
    ohlc, source = load_ohlc(params)
    notes = [
        "Yahoo/公开 API 无历史期权链；权利金由 Delta 近似自标的 OHLC 合成。",
        f"delta={params.delta} entry_premium={params.entry_premium} half_spread={params.half_spread}",
    ]
    opt_bars = ohlc_to_option_bars(
        ohlc,
        entry_premium=params.entry_premium,
        delta=params.delta,
        half_spread=params.half_spread,
        start_dte=params.start_dte,
    )
    engine = BacktestEngine(
        equity=params.equity,
        category=params.category,
        structure_target_r=params.structure_target_r,
        strategy=StrategyType.LONG,
    )
    result = engine.run(opt_bars, open_idx=0)
    return PublicBacktestReport(
        symbol=params.symbol.upper(),
        source=source,
        n_underlying_bars=len(ohlc),
        n_option_bars=len(opt_bars),
        result=result,
        notes=notes,
    )


def default_fixture_path() -> Path:
    """仓库内 CI fixture（相对包根的 tests/fixtures）。"""
    # options_buyer/backtest/ -> repo root
    root = Path(__file__).resolve().parents[2]
    return root / "tests" / "fixtures" / "yahoo_spy_daily.json"
