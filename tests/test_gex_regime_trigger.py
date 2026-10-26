"""§3.1–3.3 GEX / 体制 / 触发。"""

from __future__ import annotations

from options_buyer.core.gex import StrikeGex, build_structure, deviation_crosses_structure, shift_toward_atm
from options_buyer.core.regime import RegimeBias, evaluate_regime
from options_buyer.core.trigger import FlowPrint, FlowSide, evaluate_trigger


def _sample_rows(spot: float = 100.0) -> list[StrikeGex]:
    return [
        StrikeGex(95, call_gex=10, put_gex=-80, call_oi=1000, put_oi=2000, call_volume=500, put_volume=800),
        StrikeGex(100, call_gex=40, put_gex=-40, call_oi=2000, put_oi=2000, call_volume=2000, put_volume=2000),
        StrikeGex(105, call_gex=120, put_gex=-10, call_oi=3000, put_oi=500, call_volume=1500, put_volume=100),
        StrikeGex(110, call_gex=60, put_gex=-5, call_oi=800, put_oi=200, call_volume=50, put_volume=10),
    ]


def test_build_structure_walls():
    s = build_structure(_sample_rows(), spot=100.0)
    assert s.call_wall == 105
    # VW-GEX：95 档 put V/OI=0.4 衰减后，put_wall 落在更活跃的 100
    assert s.put_wall == 100
    raw = build_structure(_sample_rows(), spot=100.0, use_vw=False)
    assert raw.put_wall == 95
    assert s.max_gamma_strike is not None
    assert "call_wall" in s.active_walls


def test_wall_disappears_notes():
    prev = build_structure(_sample_rows(), spot=100.0)
    thin = [StrikeGex(100, call_gex=1, put_gex=-1, call_oi=10, put_oi=10, call_volume=0, put_volume=0)]
    cur = build_structure(thin, spot=100.0, previous=prev)
    # 可能仍有墙，但相对 prev 可能漂移/消失
    assert isinstance(cur.notes, list)


def test_shift_toward_atm_no_otm():
    assert shift_toward_atm(110, spot=100, steps=2, step_width=1) == 108
    assert shift_toward_atm(90, spot=100, steps=2, step_width=1) == 92
    assert deviation_crosses_structure(110, 99, call_wall=105, zero_gamma=100)


def test_regime_positive_prefers_spread():
    s = build_structure(_sample_rows(), spot=100.0)
    # force positive
    s.positive_gex = True
    d = evaluate_regime(s, charm_adverse=False)
    assert d.prefer_spread
    assert d.naked_delta_lo == 0.40


def test_regime_rr_veto():
    s = build_structure(_sample_rows(), spot=100.0)
    s.positive_gex = True
    d = evaluate_regime(s, risk_reversal_sign=-1.0, gex_implies_long=True)
    assert d.bias == RegimeBias.NO_TRADE
    assert d.allow_new is False
    # Charm 不得翻回 allow_new
    d2 = evaluate_regime(
        s, risk_reversal_sign=-1.0, gex_implies_long=True, charm_adverse=True
    )
    assert d2.allow_new is False


def test_trigger_bto_flow():
    prints = [
        FlowPrint(105, FlowSide.BTO_CALL, 20, 0.45, volume=600, oi=500),
        FlowPrint(105, FlowSide.STO_CALL, 2, 0.45, volume=50, oi=500),
    ]
    d = evaluate_trigger(
        direction="long_underlying",
        structure_active=True,
        near_structure=True,
        prints=prints,
        target_strike=105,
        min_net_delta=5.0,
        price_held=True,
        negative_gex=True,
    )
    assert d.fired
    assert d.max_voi >= 1.0
