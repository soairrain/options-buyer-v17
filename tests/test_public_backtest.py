"""Yahoo 公开 OHLC 适配 + fixture 纸面回测（离线，不联网）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from options_buyer.backtest.public_run import (
    PublicBacktestParams,
    default_fixture_path,
    ohlc_to_option_bars,
    run_public_backtest,
)
from options_buyer.data.yahoo import (
    OhlcBar,
    YahooChartClient,
    YahooConfig,
    YahooDataError,
    load_fixture,
    parse_chart_json,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yahoo_spy_daily.json"


def test_default_fixture_exists():
    assert FIXTURE.is_file()
    assert default_fixture_path() == FIXTURE


def test_parse_fixture_and_yahoo_shaped_json():
    bars = load_fixture(FIXTURE)
    assert len(bars) >= 2
    assert bars[0].close > 0

    shaped = {
        "chart": {
            "result": [
                {
                    "timestamp": [1, 2, 3],
                    "indicators": {
                        "quote": [
                            {
                                "open": [10.0, 11.0, None],
                                "high": [10.5, 11.5, None],
                                "low": [9.5, 10.5, None],
                                "close": [10.0, 11.0, None],
                                "volume": [100, 200, None],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    parsed = parse_chart_json(shaped, symbol="TEST")
    assert len(parsed) == 2
    assert parsed[1].close == 11.0


def test_yahoo_config_validate():
    with pytest.raises(YahooDataError):
        YahooConfig(symbol="  ", lookback_days=10).validate()
    with pytest.raises(YahooDataError):
        YahooConfig(lookback_days=1).validate()


def test_yahoo_client_uses_injected_opener_no_network():
    payload = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [10, 20],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, 101.0],
                                    "high": [101.0, 102.0],
                                    "low": [99.0, 100.0],
                                    "close": [100.5, 101.5],
                                    "volume": [1, 2],
                                }
                            ]
                        },
                    }
                ]
            }
        }
    ).encode()

    def opener(req, timeout=20):
        assert "SPY" in req.full_url
        assert timeout == 5
        return payload

    client = YahooChartClient(timeout_sec=5, opener=opener)
    bars = client.fetch_daily("spy", period1=1, period2=100)
    assert len(bars) == 2
    assert bars[-1].close == 101.5


def test_ohlc_to_option_bars_moves_with_spot():
    ohlc = [
        OhlcBar(1, 100, 101, 99, 100),
        OhlcBar(2, 100, 105, 100, 104),  # +4
    ]
    bars = ohlc_to_option_bars(
        ohlc, entry_premium=2.0, delta=0.5, half_spread=0.05, start_dte=30
    )
    assert len(bars) == 2
    # mid ≈ 2 + 0.5*4 = 4
    assert bars[1].mid == pytest.approx(4.0, abs=0.02)
    assert bars[1].ask > bars[1].bid
    assert bars[1].dte == 29


def test_run_public_backtest_offline_fixture():
    report = run_public_backtest(
        PublicBacktestParams(
            symbol="SPY",
            fixture_path=str(FIXTURE),
            entry_premium=2.0,
            delta=0.45,
            half_spread=0.05,
            start_dte=45,
            equity=50_000,
        )
    )
    assert report.n_underlying_bars >= 2
    assert report.n_option_bars == report.n_underlying_bars
    assert report.source.startswith("fixture:")
    assert report.result.fills  # 至少有开仓
    d = report.as_dict()
    assert "day_pnl" in d
    assert "Yahoo" in report.notes[0] or "公开" in report.notes[0]


def test_params_require_fixture_or_live():
    with pytest.raises(ValueError):
        PublicBacktestParams(live=False, fixture_path=None).validate()
