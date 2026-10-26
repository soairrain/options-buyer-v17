"""命令行入口。"""

from __future__ import annotations

import argparse
import json

from options_buyer import PLAYBOOK_VERSION, __version__
from options_buyer.backtest import BacktestEngine, BarQuote
from options_buyer.backtest.public_run import (
    PublicBacktestParams,
    default_fixture_path,
    run_public_backtest,
)
from options_buyer.core.branch import choose_branch
from options_buyer.core.gex import StrikeGex
from options_buyer.core.r import compute_r
from options_buyer.core.sizing import floor_contracts, size_long_or_debit
from options_buyer.core.trigger import FlowPrint, FlowSide
from options_buyer.core.types import AccountState, OptionQuote, StrategyCategory, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.pipeline import TradingPipeline


def cmd_demo(_: argparse.Namespace) -> int:
    equity = 50_000.0
    print(f"options-buyer {__version__} / playbook {PLAYBOOK_VERSION}")
    print(f"账户权益: ${equity:,.0f}\n")

    # 文档例：权利金 $3 → 0 张；$2 → 1 张
    for p in (3.0, 2.0):
        n = floor_contracts(equity, p)
        print(f"权利金 ${p:.2f} → 张数 {n}")

    branch = choose_branch(
        iv_rank=25,
        positive_gex=False,
        event_window=False,
        category=StrategyCategory.BREAKOUT,
    )
    print(f"\n分支: {branch.strategy.value} | {branch.reason}")
    print(f"Delta {branch.delta_lo}-{branch.delta_hi} | DTE {branch.dte_lo}-{branch.dte_hi}")

    r = compute_r(StrategyType.LONG, premium=2.0, contracts=1)
    print(f"\n1R/张 = ${r.r_per_contract:.2f} | 1R 美元 = ${r.r_dollars:.2f}")

    acct = AccountState(equity=equity)
    broker = PaperBroker(acct)
    pos = broker.open_long(
        symbol="SPY",
        premium=2.0,
        category=StrategyCategory.BREAKOUT,
        dte=30,
        structure_target_r=2.0,
    )
    assert pos is not None
    print(f"\n开仓 {pos.position_id}: {pos.contracts} 张 @ ${pos.entry_premium}")

    # 亏到 1R：权利金从 2.0 → 1.0
    fill = broker.mark_exit(pos.position_id, mark=1.0, dte=28)
    print(f"止损平仓: pnl=${fill.pnl:.2f} | 连续止损={acct.consecutive_stops} | halted={acct.halted}")

    # 再亏两笔触发熔断
    for i in range(2):
        p = broker.open_long(
            symbol="SPY",
            premium=2.0,
            category=StrategyCategory.BREAKOUT,
            dte=30,
            structure_target_r=2.0,
        )
        if not p:
            print("无法开仓", acct.halt_reason)
            break
        broker.mark_exit(p.position_id, mark=1.0, dte=28)
        print(f"止损#{i+2}: consecutive={acct.consecutive_stops} halted={acct.halted} ({acct.halt_reason})")

    return 0


def cmd_size(args: argparse.Namespace) -> int:
    d = size_long_or_debit(args.equity, args.premium, half_size=args.half)
    print(json.dumps(d.__dict__, ensure_ascii=False, indent=2))
    return 0 if d.ok else 1


def cmd_r(args: argparse.Namespace) -> int:
    if args.strategy == "credit":
        r = compute_r(
            StrategyType.CREDIT_SPREAD,
            width=args.width,
            credit=args.credit,
            contracts=args.contracts,
        )
    elif args.strategy == "debit":
        r = compute_r(
            StrategyType.DEBIT_SPREAD,
            debit=args.premium,
            contracts=args.contracts,
        )
    else:
        r = compute_r(StrategyType.LONG, premium=args.premium, contracts=args.contracts)
    print(
        json.dumps(
            {
                "strategy": r.strategy.value,
                "r_per_contract": r.r_per_contract,
                "r_dollars": r.r_dollars,
                "basis": r.basis,
                "min_structure_target_r": r.min_structure_target_r,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_pipeline(_: argparse.Namespace) -> int:
    """合成行情走 TradingPipeline 突破开仓冒烟。"""
    rows = [
        StrikeGex(100, 10, -80, 1000, 1000, 1000, 1000),
        StrikeGex(105, 20, -10, 2000, 200, 1000, 100),
    ]
    acct = AccountState(equity=50_000)
    broker = PaperBroker(acct)
    pipe = TradingPipeline(acct, broker)
    q = OptionQuote(
        symbol="SPY",
        strike=105,
        dte=30,
        right="C",
        bid=1.95,
        ask=2.0,
        mid=1.975,
        delta=0.40,
        oi=1000,
        volume=500,
    )
    prints = [FlowPrint(105, FlowSide.BTO_CALL, 200, 0.4, 800, 500)]
    res = pipe.evaluate_and_maybe_open(
        category=StrategyCategory.BREAKOUT,
        gex_rows=rows,
        spot=100,
        quote=q,
        iv_rank=25,
        flow_prints=prints,
        target_strike=105,
        broke_5m_close=True,
        near_structure=True,
        negative_gex_override=True,
        structure_target_r=2.0,
    )
    out = {
        "allowed": res.allowed,
        "strategy": res.plan.strategy.value if res.plan and res.plan.strategy else None,
        "position_id": res.position.position_id if res.position else None,
        "veto": res.veto_reasons,
        "checklist_passed": res.checklist.passed if res.checklist else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if res.allowed else 1


def cmd_backtest(_: argparse.Namespace) -> int:
    bars = [
        BarQuote(0, bid=1.90, ask=2.00, dte=30),
        BarQuote(1, bid=1.50, ask=1.60, dte=28),
        BarQuote(2, bid=1.00, ask=1.10, dte=25),
    ]
    result = BacktestEngine(equity=50_000).run(bars)
    print(
        json.dumps(
            {
                "fills": len(result.fills),
                "day_pnl": result.day_pnl,
                "ending_equity": result.ending_equity,
                "notes": result.notes,
                "trades": len(result.trade_results),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_public_backtest(args: argparse.Namespace) -> int:
    """Yahoo 公开 OHLC（或 fixture）→ Delta 合成权利金 → 纸面回测。"""
    fixture = args.fixture
    live = bool(args.live)
    if not live and not fixture:
        fixture = str(default_fixture_path())
    params = PublicBacktestParams(
        symbol=args.symbol,
        lookback_days=args.days,
        entry_premium=args.premium,
        delta=args.delta,
        half_spread=args.half_spread,
        start_dte=args.dte,
        equity=args.equity,
        fixture_path=None if live else fixture,
        live=live,
    )
    report = run_public_backtest(params)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="期权买方 v1.7 规则引擎")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_demo = sub.add_parser("demo", help="运行纸面演示（含连续止损熔断）")
    p_demo.set_defaults(func=cmd_demo)

    p_size = sub.add_parser("size", help="计算张数")
    p_size.add_argument("--equity", type=float, default=50_000)
    p_size.add_argument("--premium", type=float, required=True)
    p_size.add_argument("--half", action="store_true")
    p_size.set_defaults(func=cmd_size)

    p_r = sub.add_parser("r", help="计算 1R")
    p_r.add_argument("--strategy", choices=["long", "debit", "credit"], default="long")
    p_r.add_argument("--premium", type=float, default=2.0)
    p_r.add_argument("--width", type=float, default=5.0)
    p_r.add_argument("--credit", type=float, default=2.5)
    p_r.add_argument("--contracts", type=int, default=1)
    p_r.set_defaults(func=cmd_r)

    p_pipe = sub.add_parser("pipeline", help="合成行情跑 TradingPipeline 冒烟")
    p_pipe.set_defaults(func=cmd_pipeline)

    p_bt = sub.add_parser("backtest", help="合成 bid/ask 跑纸面回测冒烟")
    p_bt.set_defaults(func=cmd_backtest)

    p_pub = sub.add_parser(
        "public-backtest",
        help="Yahoo 公开 OHLC（默认 fixture；--live 才联网）纸面回测",
    )
    p_pub.add_argument("--symbol", default="SPY")
    p_pub.add_argument("--days", type=int, default=60, help="live 回看日历日")
    p_pub.add_argument("--premium", type=float, default=2.0, help="合成开仓权利金")
    p_pub.add_argument("--delta", type=float, default=0.45)
    p_pub.add_argument("--half-spread", type=float, default=0.05, dest="half_spread")
    p_pub.add_argument("--dte", type=int, default=45)
    p_pub.add_argument("--equity", type=float, default=50_000)
    p_pub.add_argument(
        "--fixture",
        default=None,
        help="离线 JSON fixture 路径（默认 tests/fixtures/yahoo_spy_daily.json）",
    )
    p_pub.add_argument(
        "--live",
        action="store_true",
        help="从 Yahoo Chart API 实时拉取（无 API Key；CI 勿用）",
    )
    p_pub.set_defaults(func=cmd_public_backtest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
