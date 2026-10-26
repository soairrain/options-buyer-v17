"""纸面账户：开平仓走完整风控路径。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from options_buyer.core.correlation import CorrelationBook
from options_buyer.core.exits import (
    ExitAction,
    ExitDecision,
    credit_spread_exit,
    iv_path_override,
    long_or_debit_exit,
    pnl_in_r,
)
from options_buyer.core.expiry import ExpiryAction, manage_expiry
from options_buyer.core.extreme import extreme_paused
from options_buyer.core.r import compute_r, structure_target_ok
from options_buyer.core.sizing import (
    can_open_premium,
    cap_contracts_by_notional,
    signal_add_ok,
    size_long_or_debit,
)
from options_buyer.core.types import (
    MULTIPLIER,
    NO_NEW_LONG_DTE,
    PDT_DAY_TRADES_LIMIT,
    PDT_EQUITY_THRESHOLD,
    AccountState,
    ExitReason,
    Position,
    StrategyCategory,
    StrategyType,
)
from options_buyer.risk import halt as halt_mod
from options_buyer.risk.greeks import PortfolioGreeks
from options_buyer.risk.veto import VetoContext, evaluate_vetoes


@dataclass
class Fill:
    position_id: str
    side: str
    contracts: int
    price: float
    pnl: float = 0.0
    reason: str = ""


@dataclass
class PaperBroker:
    account: AccountState
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    # 可选：最近一次组合 Greeks；未提供则跳过 Greeks 门禁
    portfolio_greeks: PortfolioGreeks | None = None
    # 可选时钟（回测/单测注入）；None 则用 wall clock
    now: float | None = None
    # 可选：相关性账本 / 否决上下文工厂
    correlation: CorrelationBook | None = None
    event_window: bool = False
    enforce_soft_overtrade: bool = True
    # 开仓方向（相关合计）；默认看多
    default_direction: int = 1

    def _hard_gates(
        self,
        strategy: StrategyType,
        *,
        dte: int,
        veto_ctx: VetoContext | None = None,
        symbol: str | None = None,
        premium_usd: float = 0.0,
        direction: int | None = None,
    ) -> bool:
        """开仓硬门禁：停机 / 极端 / PDT / 软停手 / 事件窗口 / 相关 / 否决 / Greeks。"""
        a = self.account
        if a.halted:
            return False
        if extreme_paused(a, now=self.now):
            return False
        if self.enforce_soft_overtrade and halt_mod.soft_overtrade_stop(a):
            return False
        if (
            a.equity < PDT_EQUITY_THRESHOLD
            and a.day_trades_used_5d >= PDT_DAY_TRADES_LIMIT
        ):
            return False
        if strategy in (StrategyType.LONG, StrategyType.DEEP_ITM) and dte < NO_NEW_LONG_DTE:
            return False
        if self.event_window and strategy in (StrategyType.LONG, StrategyType.DEEP_ITM):
            return False
        g = self.portfolio_greeks
        if g is not None:
            if not g.ok:
                return False
            if g.block_new_buyer and strategy != StrategyType.CREDIT_SPREAD:
                return False
        if self.correlation is not None and symbol is not None and premium_usd > 0:
            ok, _ = self.correlation.allows(
                equity=a.equity,
                symbol=symbol,
                direction=direction if direction is not None else self.default_direction,
                new_premium=premium_usd,
            )
            if not ok:
                return False
        if veto_ctx is not None:
            # 注入账户相关字段
            if g is not None:
                veto_ctx.greeks_ok = g.ok
                veto_ctx.block_new_buyer = g.block_new_buyer
            veto_ctx.strategy = strategy
            veto_ctx.dte = dte
            if self.event_window:
                veto_ctx.event_window = True
            if extreme_paused(a, now=self.now):
                veto_ctx.extreme_halt = True
            vr = evaluate_vetoes(a, veto_ctx)
            if vr.blocked:
                return False
        return True

    def _reserve_premium(self, pos: Position, amount: float) -> None:
        """买方/借方：占用权利金预算。"""
        pos.premium_reserved = amount
        self.account.open_premium_total += amount
        cat = pos.category.value
        self.account.open_premium_by_category[cat] = (
            self.account.open_premium_by_category.get(cat, 0.0) + amount
        )

    def _release_premium(self, pos: Position, fraction: float = 1.0) -> float:
        amount = pos.premium_reserved * fraction
        self.account.open_premium_total = max(0.0, self.account.open_premium_total - amount)
        cat = pos.category.value
        self.account.open_premium_by_category[cat] = max(
            0.0, self.account.open_premium_by_category.get(cat, 0.0) - amount
        )
        pos.premium_reserved = max(0.0, pos.premium_reserved - amount)
        return amount

    def _reserve_credit_margin(self, pos: Position, margin: float) -> None:
        """信用价差：只占用保证金，不计入权利金预算（§4.3）。"""
        pos.margin = margin
        pos.premium_reserved = 0.0
        self.account.open_credit_margin_total += margin

    def _release_credit_margin(self, pos: Position) -> float:
        m = pos.margin
        self.account.open_credit_margin_total = max(
            0.0, self.account.open_credit_margin_total - m
        )
        pos.margin = 0.0
        return m

    def _track_corr_open(self, pos: Position, premium_usd: float, direction: int) -> None:
        if self.correlation is None:
            return
        from options_buyer.core.correlation import OpenRiskLeg

        self.correlation.legs.append(
            OpenRiskLeg(
                symbol=pos.symbol,
                direction=direction,
                premium_usd=premium_usd,
                category=pos.category.value,
                position_id=pos.position_id,
            )
        )

    def _track_corr_close(self, pos: Position) -> None:
        if self.correlation is None:
            return
        self.correlation.legs = [
            leg for leg in self.correlation.legs if leg.position_id != pos.position_id
        ]

    def open_long(
        self,
        *,
        symbol: str,
        premium: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        half_size: bool = False,
        is_add: bool = False,
        spot: float | None = None,
        existing_premium: float = 0.0,
        first_leg_profitable: bool = False,
        already_added: bool = False,
        strategy: StrategyType = StrategyType.LONG,
        veto_ctx: VetoContext | None = None,
        direction: int = 1,
    ) -> Position | None:
        if strategy not in (StrategyType.LONG, StrategyType.DEEP_ITM):
            return None
        psych = halt_mod.size_multiplier_psychology(self.account) < 1.0
        decision = size_long_or_debit(
            self.account.equity, premium, half_size=half_size or psych
        )
        if not decision.ok:
            return None
        contracts = decision.contracts
        if spot is not None:
            contracts = cap_contracts_by_notional(self.account.equity, spot, contracts)
            if contracts < 1:
                return None
        premium_cost = contracts * premium * MULTIPLIER

        if not self._hard_gates(
            strategy,
            dte=dte,
            veto_ctx=veto_ctx,
            symbol=symbol,
            premium_usd=premium_cost,
            direction=direction,
        ):
            return None

        if is_add:
            ok, _ = signal_add_ok(
                self.account,
                category=category,
                existing_premium=existing_premium,
                add_premium=premium_cost,
                strategy=strategy,
                first_leg_profitable=first_leg_profitable,
                already_added=already_added,
            )
            if not ok:
                return None
        else:
            ok, _ = can_open_premium(
                self.account,
                new_premium=premium_cost,
                category=category,
                strategy=strategy,
            )
            if not ok:
                return None
        if not structure_target_ok(structure_target_r, strategy):
            return None

        rspec = compute_r(strategy, premium=premium, contracts=contracts)
        pid = str(uuid.uuid4())[:8]
        pos = Position(
            position_id=pid,
            strategy=strategy,
            category=category,
            symbol=symbol,
            contracts=contracts,
            entry_premium=premium,
            r_dollars=rspec.r_dollars,
            r_per_contract=rspec.r_per_contract,
            dte_at_entry=dte,
            structure_target_r=structure_target_r,
            is_add=is_add,
            added_once=is_add,
        )
        self._reserve_premium(pos, premium_cost)
        self._track_corr_open(pos, premium_cost, direction)
        self.positions[pid] = pos
        self.account.opens_today += 1
        self.fills.append(Fill(pid, "buy", contracts, premium))
        return pos

    def open_deep_itm(
        self,
        *,
        symbol: str,
        premium: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        half_size: bool = False,
        spot: float | None = None,
        veto_ctx: VetoContext | None = None,
    ) -> Position | None:
        """IVR>50 仍想裸买 → Deep ITM（§3.4.0 / §5.1）。"""
        return self.open_long(
            symbol=symbol,
            premium=premium,
            category=category,
            dte=dte,
            structure_target_r=structure_target_r,
            half_size=half_size,
            spot=spot,
            strategy=StrategyType.DEEP_ITM,
            veto_ctx=veto_ctx,
        )

    def open_debit(
        self,
        *,
        symbol: str,
        net_debit: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        width: float = 0.0,
        half_size: bool = False,
        spot: float | None = None,
        is_add: bool = False,
        existing_premium: float = 0.0,
        first_leg_profitable: bool = False,
        already_added: bool = False,
        veto_ctx: VetoContext | None = None,
        direction: int = 1,
    ) -> Position | None:
        psych = halt_mod.size_multiplier_psychology(self.account) < 1.0
        decision = size_long_or_debit(
            self.account.equity, net_debit, half_size=half_size or psych
        )
        if not decision.ok:
            return None
        contracts = decision.contracts
        if spot is not None:
            contracts = cap_contracts_by_notional(self.account.equity, spot, contracts)
            if contracts < 1:
                return None
        premium_cost = contracts * net_debit * MULTIPLIER

        if not self._hard_gates(
            StrategyType.DEBIT_SPREAD,
            dte=dte,
            veto_ctx=veto_ctx,
            symbol=symbol,
            premium_usd=premium_cost,
            direction=direction,
        ):
            return None

        if is_add:
            ok, _ = signal_add_ok(
                self.account,
                category=category,
                existing_premium=existing_premium,
                add_premium=premium_cost,
                strategy=StrategyType.DEBIT_SPREAD,
                first_leg_profitable=first_leg_profitable,
                already_added=already_added,
            )
            if not ok:
                return None
        else:
            ok, _ = can_open_premium(
                self.account,
                new_premium=premium_cost,
                category=category,
                strategy=StrategyType.DEBIT_SPREAD,
            )
            if not ok:
                return None
        if not structure_target_ok(structure_target_r, StrategyType.DEBIT_SPREAD):
            return None

        rspec = compute_r(
            StrategyType.DEBIT_SPREAD, debit=net_debit, contracts=contracts
        )
        pid = str(uuid.uuid4())[:8]
        pos = Position(
            position_id=pid,
            strategy=StrategyType.DEBIT_SPREAD,
            category=category,
            symbol=symbol,
            contracts=contracts,
            entry_premium=net_debit,
            width=width,
            r_dollars=rspec.r_dollars,
            r_per_contract=rspec.r_per_contract,
            dte_at_entry=dte,
            structure_target_r=structure_target_r,
            is_add=is_add,
            added_once=is_add,
        )
        self._reserve_premium(pos, premium_cost)
        self._track_corr_open(pos, premium_cost, direction)
        self.positions[pid] = pos
        self.account.opens_today += 1
        self.fills.append(Fill(pid, "buy_debit", contracts, net_debit))
        return pos

    def open_credit(
        self,
        *,
        symbol: str,
        width: float,
        credit: float,
        margin: float,
        category: StrategyCategory,
        dte: int,
        structure_target_r: float,
        contracts: int = 1,
        veto_ctx: VetoContext | None = None,
        direction: int = -1,
        half_size: bool = False,
    ) -> Position | None:
        # 心理减半：信用按张数减半（至少 1）
        if half_size or halt_mod.size_multiplier_psychology(self.account) < 1.0:
            contracts = max(1, contracts // 2)
        max_loss = (width - credit) * MULTIPLIER * contracts
        if not self._hard_gates(
            StrategyType.CREDIT_SPREAD,
            dte=dte,
            veto_ctx=veto_ctx,
            symbol=symbol,
            premium_usd=0.0,  # 信用相关按保证金近似跟踪
            direction=direction,
        ):
            return None
        # 相关：用 max_loss 作为风险占用近似
        if self.correlation is not None:
            ok, _ = self.correlation.allows(
                equity=self.account.equity,
                symbol=symbol,
                direction=direction,
                new_premium=max_loss,
            )
            if not ok:
                return None
        ok, _ = can_open_premium(
            self.account,
            new_premium=0.0,
            category=category,
            strategy=StrategyType.CREDIT_SPREAD,
            margin=margin,
            max_loss=max_loss,
        )
        if not ok:
            return None
        if not structure_target_ok(structure_target_r, StrategyType.CREDIT_SPREAD):
            return None

        rspec = compute_r(
            StrategyType.CREDIT_SPREAD,
            width=width,
            credit=credit,
            contracts=contracts,
        )
        pid = str(uuid.uuid4())[:8]
        pos = Position(
            position_id=pid,
            strategy=StrategyType.CREDIT_SPREAD,
            category=category,
            symbol=symbol,
            contracts=contracts,
            entry_premium=credit,
            width=width,
            credit=credit,
            r_dollars=rspec.r_dollars,
            r_per_contract=rspec.r_per_contract,
            dte_at_entry=dte,
            structure_target_r=structure_target_r,
            margin=margin,
        )
        self._reserve_credit_margin(pos, margin)
        self._track_corr_open(pos, max_loss, direction)
        self.positions[pid] = pos
        self.account.opens_today += 1
        self.fills.append(Fill(pid, "sell_credit", contracts, credit))
        return pos

    def _apply_full_close_counters(self, decision: ExitDecision, pnl: float) -> None:
        """全平后的止损/盈利计数。SHORT_DELTA：盈利计 win，亏损计 stop。"""
        if decision.reason == ExitReason.STOP_1R:
            halt_mod.record_stop(self.account)
        elif decision.reason == ExitReason.SHORT_DELTA:
            if pnl > 0:
                halt_mod.record_win(self.account)
            else:
                halt_mod.record_stop(self.account)
        elif decision.reason in (
            ExitReason.TAKE_PROFIT,
            ExitReason.TAKE_HALF,
        ) or pnl > 0:
            halt_mod.record_win(self.account)
        else:
            halt_mod.record_flat_or_loss_non_stop(self.account)

    def mark_exit(
        self,
        position_id: str,
        *,
        mark: float,
        dte: int,
        short_leg_distance_atr: float | None = None,
        short_delta: float | None = None,
        iv_entry: float | None = None,
        iv_now: float | None = None,
        at_structure_target: bool = False,
        structure_gone: bool = False,
        assigned: bool = False,
        force_expiry: bool = False,
        long_itm: bool = False,
        short_itm: bool = False,
        american: bool = True,
        days_to_ex_div: int | None = None,
        charm_force_close: bool = False,
    ) -> Fill | None:
        pos = self.positions.get(position_id)
        if not pos:
            return None

        # 结构/到期/指派/Charm 强制退出（优先于常规止盈止损表）
        forced: ExitDecision | None = None
        if assigned:
            forced = ExitDecision(
                ExitAction.CLOSE_ALL, ExitReason.ASSIGNMENT, "被指派应急平仓"
            )
        elif structure_gone:
            forced = ExitDecision(
                ExitAction.CLOSE_ALL, ExitReason.WALL_GONE, "结构墙体消失 → 平仓"
            )
        elif charm_force_close:
            forced = ExitDecision(
                ExitAction.CLOSE_ALL, ExitReason.CHARM_ADVERSE, "Charm 逆流强制减/平"
            )
        elif force_expiry:
            exp = manage_expiry(
                pos.strategy,
                dte=dte,
                long_itm=long_itm,
                short_itm=short_itm,
                american=american,
                short_distance_atr=short_leg_distance_atr,
                short_delta=short_delta,
                days_to_ex_div=days_to_ex_div,
                assigned=False,
            )
            if exp.action != ExpiryAction.HOLD:
                forced = ExitDecision(
                    ExitAction.CLOSE_ALL, exp.reason or ExitReason.EXPIRY, exp.detail
                )
                if exp.halt_day:
                    self.account.halted = True
                    self.account.halt_reason = exp.detail
        else:
            # 自动跑到期规则（不 force 也检查）
            exp = manage_expiry(
                pos.strategy,
                dte=dte,
                long_itm=long_itm,
                short_itm=short_itm,
                american=american,
                short_distance_atr=short_leg_distance_atr,
                short_delta=short_delta,
                days_to_ex_div=days_to_ex_div,
            )
            if exp.action != ExpiryAction.HOLD:
                forced = ExitDecision(
                    ExitAction.CLOSE_ALL, exp.reason or ExitReason.EXPIRY, exp.detail
                )
                if exp.halt_day:
                    self.account.halted = True
                    self.account.halt_reason = exp.detail

        pr = pnl_in_r(
            pos.strategy,
            entry=pos.entry_premium,
            mark=mark,
            r_per_contract=pos.r_per_contract,
            width=pos.width,
            credit=pos.credit,
        )

        if forced is not None:
            decision = forced
        elif pos.strategy == StrategyType.CREDIT_SPREAD:
            decision = credit_spread_exit(
                dte=dte,
                pnl_r=pr,
                short_leg_distance_atr=short_leg_distance_atr,
                short_delta=short_delta,
            )
        else:
            decision = long_or_debit_exit(
                dte=dte,
                pnl_r=pr,
                structure_target_r=pos.structure_target_r,
                remaining_fraction=pos.remaining_fraction,
                strategy=pos.strategy,
            )

        # IV 路径覆盖（标的到目标时）：
        # - 不得覆盖 STOP_1R / TIME_STOP / 强制结构退出
        # - 「继续持有剩余」仅打断已减半后的止盈全平，不打断 1.5R 减半本身
        protected = {
            ExitReason.STOP_1R,
            ExitReason.TIME_STOP,
            ExitReason.SHORT_DELTA,
            ExitReason.WALL_GONE,
            ExitReason.ASSIGNMENT,
            ExitReason.EXPIRY,
            ExitReason.CHARM_ADVERSE,
        }
        if (
            forced is None
            and iv_entry is not None
            and iv_now is not None
            and decision.reason not in protected
        ):
            iv_dec = iv_path_override(
                iv_entry=iv_entry,
                iv_now=iv_now,
                at_structure_target=at_structure_target,
            )
            if iv_dec is not None:
                if (
                    iv_dec.action == ExitAction.HOLD
                    and "上升" in iv_dec.detail
                    and decision.action == ExitAction.CLOSE_ALL
                    and pos.remaining_fraction < 0.999
                ):
                    decision = iv_dec
                elif iv_dec.action == ExitAction.CLOSE_ALL:
                    decision = iv_dec

        if decision.action == ExitAction.HOLD:
            return None

        if decision.action == ExitAction.CLOSE_HALF and pos.contracts <= 1:
            decision = ExitDecision(
                ExitAction.CLOSE_ALL, decision.reason, "单张无法减半，1.5R 全平"
            )

        if decision.action == ExitAction.CLOSE_HALF:
            orig = pos.contracts
            closed = orig // 2
            if closed < 1:
                decision = ExitDecision(
                    ExitAction.CLOSE_ALL, decision.reason, "无法减半，改为全平"
                )
            else:
                frac = closed / orig
                pnl = (mark - pos.entry_premium) * MULTIPLIER * closed
                self._release_premium(pos, frac)
                pos.remaining_fraction = (orig - closed) / orig
                pos.contracts = orig - closed
                halt_mod.apply_realized_pnl(self.account, pnl)
                # 减半不记 win/stop：整笔结构只在最终全平时计 1 次
                fill = Fill(
                    pos.position_id,
                    "sell_half",
                    closed,
                    mark,
                    pnl=pnl,
                    reason=decision.detail,
                )
                self.fills.append(fill)
                return fill
            # fall through if converted to CLOSE_ALL

        # CLOSE_ALL
        if pos.strategy == StrategyType.CREDIT_SPREAD:
            pnl = (pos.credit - mark) * MULTIPLIER * pos.contracts
            self._release_credit_margin(pos)
        else:
            pnl = (mark - pos.entry_premium) * MULTIPLIER * pos.contracts
            self._release_premium(pos, 1.0)

        halt_mod.apply_realized_pnl(self.account, pnl)
        self._apply_full_close_counters(decision, pnl)
        self._track_corr_close(pos)

        fill = Fill(
            pos.position_id,
            "close",
            pos.contracts,
            mark,
            pnl=pnl,
            reason=decision.detail or (decision.reason.value if decision.reason else ""),
        )
        self.fills.append(fill)
        del self.positions[position_id]
        return fill
