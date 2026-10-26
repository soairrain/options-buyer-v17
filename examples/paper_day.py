"""模拟一日：开仓 → 止损/止盈 → 熔断。"""

from __future__ import annotations

from options_buyer.core.types import AccountState, StrategyCategory
from options_buyer.execution.paper import PaperBroker
from options_buyer.risk.halt import reset_day


def main() -> None:
    acct = AccountState(equity=50_000)
    broker = PaperBroker(acct)

    # 盈利一笔 → 连续止损归 0
    p = broker.open_long(
        symbol="QQQ",
        premium=1.50,
        category=StrategyCategory.ABSORPTION_3A,
        dte=21,
        structure_target_r=2.0,
    )
    assert p
    # 权利金 1.5，1R=0.75；涨到 1.5+1.5*1.5=3.75 为 2R… 简化：涨到使 pnl_r>=1.5
    # entry=1.5, r=0.75 → 1.5R mark = 1.5 + 1.125 = 2.625
    fill = broker.mark_exit(p.position_id, mark=2.625, dte=20)
    print("减半/止盈:", fill)
    print("consecutive_stops after win path:", acct.consecutive_stops)

    # 三连止损
    for i in range(3):
        p = broker.open_long(
            symbol="SPY",
            premium=2.0,
            category=StrategyCategory.BREAKOUT,
            dte=30,
            structure_target_r=2.0,
        )
        if not p:
            print("blocked:", acct.halt_reason)
            break
        broker.mark_exit(p.position_id, mark=1.0, dte=25)
        print(f"stop {i+1}: consecutive={acct.consecutive_stops} halted={acct.halted}")

    print("日盈亏:", round(acct.day_realized_pnl, 2))
    reset_day(acct)
    print("次日重置 halted=", acct.halted)


if __name__ == "__main__":
    main()
