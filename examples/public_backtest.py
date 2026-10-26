"""离线 Yahoo fixture → 纸面期权回测（默认不联网）。

Live（可选）::

    PYTHONPATH=. python examples/public_backtest.py --live --symbol SPY --days 60
"""

from __future__ import annotations

import argparse
import json
import sys

from options_buyer.backtest.public_run import (
    PublicBacktestParams,
    default_fixture_path,
    run_public_backtest,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Public Yahoo OHLC paper backtest")
    p.add_argument("--symbol", default="SPY")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--premium", type=float, default=2.0)
    p.add_argument("--delta", type=float, default=0.45)
    p.add_argument("--live", action="store_true")
    p.add_argument("--fixture", default=None)
    args = p.parse_args(argv)

    fixture = args.fixture
    if not args.live and not fixture:
        fixture = str(default_fixture_path())

    report = run_public_backtest(
        PublicBacktestParams(
            symbol=args.symbol,
            lookback_days=args.days,
            entry_premium=args.premium,
            delta=args.delta,
            fixture_path=None if args.live else fixture,
            live=bool(args.live),
        )
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
