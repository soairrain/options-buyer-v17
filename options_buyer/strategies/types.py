"""策略步骤机共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field

from options_buyer.core.branch import BranchDecision
from options_buyer.core.types import StrategyCategory, StrategyType


@dataclass
class StrategyStepResult:
    step: str
    ok: bool
    detail: str = ""


@dataclass
class StrategyPlan:
    category: StrategyCategory
    allowed: bool
    strategy: StrategyType | None
    branch: BranchDecision | None
    structure_target_r: float
    size_multiplier: float = 1.0
    steps: list[StrategyStepResult] = field(default_factory=list)
    veto_reasons: list[str] = field(default_factory=list)

    @property
    def failed_steps(self) -> list[StrategyStepResult]:
        return [s for s in self.steps if not s.ok]
