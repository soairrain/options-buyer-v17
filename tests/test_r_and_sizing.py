from options_buyer.core.r import compute_r
from options_buyer.core.sizing import floor_contracts, size_long_or_debit
from options_buyer.core.types import StrategyType


def test_doc_example_contracts():
    # 账户 $50,000，单笔 0.5%，权利金 $3 → 0 张；$2 → 1 张
    assert floor_contracts(50_000, 3.0) == 0
    assert floor_contracts(50_000, 2.0) == 1
    assert not size_long_or_debit(50_000, 3.0).ok
    assert size_long_or_debit(50_000, 2.0).contracts == 1


def test_long_r():
    r = compute_r(StrategyType.LONG, premium=2.0, contracts=1)
    assert r.r_per_contract == 1.0
    assert r.r_dollars == 100.0
    assert r.min_structure_target_r == 1.5


def test_credit_r_half_width():
    # C = W/2 → R = W/4 = C/2 → 1R 等于净收 50%
    r = compute_r(StrategyType.CREDIT_SPREAD, width=10.0, credit=5.0, contracts=1)
    assert r.r_per_contract == 2.5
    assert abs(r.r_per_contract - 5.0 * 0.5) < 1e-9


def test_credit_rejects_below_half():
    try:
        compute_r(StrategyType.CREDIT_SPREAD, width=10.0, credit=3.0, contracts=1)
        assert False, "should reject"
    except ValueError as e:
        assert "width/2" in str(e)
