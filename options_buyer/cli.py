"""命令行入口。"""

from __future__ import annotations

import argparse
import json

from options_buyer import PLAYBOOK_VERSION, __version__
from options_buyer.core.branch import choose_branch
from options_buyer.core.r import compute_r
from options_buyer.core.sizing import floor_contracts, size_long_or_debit
from options_buyer.core.types import AccountState, StrategyCategory, StrategyType
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.halt import record_stop, record_win, reset_day


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
