"""期权历史报价纸面回测：按盘口买卖、显式滑点与 IV Crush 字段。

不接券商；输入由调用方提供 bid/ask 序列。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.r import compute_r
from options_buyer.core.types import AccountState, StrategyCategory, StrategyType
from options_buyer.execution.paper import Fill, PaperBroker
from options_buyer.risk.elimination import TradeResult
from options_buyer.risk.halt import reset_day


@dataclass
class BarQuote:
    ts: float
    bid: float
    ask: float
    iv: float | None = None
    underlying: float | None = None
    dte: int = 30

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass
class BacktestResult:
    fills: list[Fill]
    trade_results: list[TradeResult]
    ending_equity: float
    day_pnl: float
    notes: list[str] = field(default_factory=list)


@dataclass
class BacktestEngine:
    """简化长仓/借方回测：开仓吃 ask，平仓吃 bid。"""

    equity: float = 50_000.0
    category: StrategyCategory = StrategyCategory.BREAKOUT
    structure_target_r: float = 2.0
    strategy: StrategyType = StrategyType.LONG

    def run(self, bars: list[BarQuote], *, open_idx: int = 0) -> BacktestResult:
        if not bars or open_idx >= len(bars):
            return BacktestResult([], [], self.equity, 0.0, notes=["无行情"])

        acct = AccountState(equity=self.equity)
        broker = PaperBroker(acct)
        entry = bars[open_idx]
        slip_note = f"开仓滑点半价差={(entry.ask - entry.bid) / 2:.4f}"

        if self.strategy == StrategyType.CREDIT_SPREAD:
            width = 5.0
            credit = entry.bid
            margin = (width - credit) * 100
            pos = broker.open_credit(
                symbol="BACKTEST",
                width=width,
                credit=credit,
                margin=margin,
                category=self.category,
                dte=entry.dte,
                structure_target_r=1.0,
            )
            r_dollars = (
                compute_r(
                    StrategyType.CREDIT_SPREAD,
                    width=width,
                    credit=credit,
                    contracts=pos.contracts if pos else 1,
                ).r_dollars
                if pos
                else 1.0
            )
        elif self.strategy == StrategyType.DEBIT_SPREAD:
            pos = broker.open_debit(
                symbol="BACKTEST",
                net_debit=entry.ask,
                category=self.category,
                dte=entry.dte,
                structure_target_r=self.structure_target_r,
            )
            r_dollars = (
                compute_r(
                    StrategyType.DEBIT_SPREAD,
                    debit=entry.ask,
                    contracts=pos.contracts if pos else 1,
                ).r_dollars
                if pos
                else 1.0
            )
        else:
            pos = broker.open_long(
                symbol="BACKTEST",
                premium=entry.ask,
                category=self.category,
                dte=entry.dte,
                structure_target_r=self.structure_target_r,
                strategy=self.strategy,
            )
            r_dollars = (
                compute_r(
                    self.strategy,
                    premium=entry.ask,
                    contracts=pos.contracts if pos else 1,
                ).r_dollars
                if pos
                else 1.0
            )

        notes = [slip_note]
        if pos is None:
            return BacktestResult(
                broker.fills, [], acct.equity, acct.day_realized_pnl, notes=["开仓被拒"]
            )

        entry_iv = entry.iv
        closed = False
        for bar in bars[open_idx + 1 :]:
            mark = bar.ask if self.strategy == StrategyType.CREDIT_SPREAD else bar.bid
            fill = broker.mark_exit(
                pos.position_id,
                mark=mark,
                dte=bar.dte,
                iv_entry=entry_iv,
                iv_now=bar.iv,
                at_structure_target=False,
            )
            if fill is not None and fill.side == "close":
                closed = True
                break
            # 半仓后继续
            if pos.position_id not in broker.positions:
                closed = True
                break

        if not closed and pos.position_id in broker.positions:
            last = bars[-1]
            mark = last.ask if self.strategy == StrategyType.CREDIT_SPREAD else last.bid
            broker.force_close(
                pos.position_id, mark=mark, reason="回测期末强平"
            )
            notes.append("期末强平")

        trades: list[TradeResult] = []
        r_basis = max(abs(r_dollars), 1e-9)
        for f in broker.fills:
            if f.side in ("close", "sell_half"):
                trades.append(
                    TradeResult(
                        pnl_r=f.pnl / r_basis,
                        pnl_pct_equity=f.pnl / self.equity,
                    )
                )

        day_pnl = acct.day_realized_pnl
        ending = self.equity + day_pnl
        reset_day(acct)
        return BacktestResult(broker.fills, trades, ending, day_pnl, notes)
