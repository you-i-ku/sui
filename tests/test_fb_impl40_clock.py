"""実装の係の小さい確かめ (K40 時計の部品、回転・幅・配分が点の事前の場合)。試験の係の試験 (test_fb_clock_belief) ではない。
紙 F-b K40 の定規のうち点の事前で書けるもの (決定 10 の ① ② ③・区切りの境目をまたぐ取得・1 周の終わりでは形が見えない・p と
共同・平均の不変・別名) と、この本が名指して止める宣言を、K38・K39 の試験の足場の上で確かめる。宣言の形は試験の係が決めた
公開の形 (`fb.ClockPrior` の periods・segments・phase・widths・fractions)。"""

from dataclasses import replace
from fractions import Fraction as Q
from types import SimpleNamespace

import pytest

from sui import fb, f_update2 as u2, _fb_time as ft
from test_fb_time_belief import script, E, T, assert_contains, rat, plus, minus, times, divide, expneg, budget
from test_fb_impl39_switch import mood, rig  # noqa: F401  (rig は fixture)


def prior(*, periods=(Q(1),), widths=(Q(1, 2), Q(1, 2)), shares=(Q(3, 4), Q(1, 4)), rotation=Q(0), segments=None,
          kw=None, kf=None):
    """時計の最初の見込み。widths・shares は点 (None なら連続の Dirichlet で集中度 kw・kf)、rotation None は一様、周期の候補は
    同じ重み、segments は ((m, 重み), …) (None は点の長さの m だけ)。"""
    m = len(widths or shares or (0, 0))
    counts = segments or ((m, Q(1)),)

    def simplex(values, kind, concentration):
        return {"kind": kind, "concentration": concentration} if values is None else \
            {"kind": "point", "values": ((m, tuple(values)),)}
    return fb.ClockPrior(periods=tuple((p, Q(1, len(periods))) for p in periods), max_segments=max(c for c, _w in counts),
                         segments=counts, phase={"kind": "uniform"} if rotation is None else {"kind": "point", "value": rotation},
                         widths=simplex(widths, "symmetric_dirichlet", kw),
                         fractions=simplex(shares, "conditional_dirichlet", kf))


def clock(*, name="clk", **kwargs):
    return fb.SwitchPart(id=name, kind="clock", multipliers=(), clock=prior(**kwargs))


def ratio(top, bottom):
    """2 つの照会の答えの比を、区間の割り算で包む (分母は正)。"""
    values = (top.lower / bottom.lower, top.lower / bottom.upper, top.upper / bottom.lower, top.upper / bottom.upper)
    return SimpleNamespace(lower=min(values), upper=max(values))


def only_clock(r_rig, plan, **kwargs):
    return r_rig(plan, rates=(Q(1), Q(1)), role=None, unit=Q(1, 4), **kwargs)


def test_impl40_point_clock_is_the_fixed_piecewise_rate_and_a_full_turn_hides_the_shape(rig):
    """決定 10 ③ (点検係 1 通目の例): T = 1・ρ = 0・w = (1/2, 1/2)・f = (3/4, 1/4)・R = 1 で、時刻 1/4 の点の empty の尤度は
    exp(−3/8)。時刻 1 (1 周の終わり) では exp(−1) で、時計のオンとオフを見分けない (どの一定率でも両方には合わない)。"""
    r = only_clock(rig, script((1, 1, E)), parts=(clock(),)).direct()
    r.observe(0)
    r.update()
    assert_contains(r.sq("switch", on=("clk",)), divide(expneg(Q(3, 8)), plus(expneg(Q(1, 4)), expneg(Q(3, 8)))))
    assert_contains(r.query("mass"), divide(plus(expneg(Q(1, 4)), expneg(Q(3, 8))), rat(2)))
    full = only_clock(rig, script((4, 4, E)), parts=(clock(),)).direct()
    full.observe(0)
    full.update()
    assert full.sq("switch", on=("clk",)).exact == Q(1, 2)
    assert_contains(full.query("mass"), expneg(1))


def test_impl40_acquisition_across_a_boundary_is_one_decision_split_at_the_boundary(rig):
    """決定 6: 不等幅 w = (1/4, 3/4)・f = (1/2, 1/2) (倍率 2 と 2/3) で、判定時刻が [0, 1/2] の一様の最初の empty。境目 1/4 で U の
    積分を分けて足すと L = 1 + 2e^{−1/2} − 3e^{−2/3}、オフは 2(1 − e^{−1/2})。区切りごとに掛けた答え
    (e^{−1/2}·(1 − e^{−1/3})·…) や、平均の率で読んだ答え (オフと同じ) とは違う。"""
    part = clock(widths=(Q(1, 4), Q(3, 4)), shares=(Q(1, 2), Q(1, 2)))
    r = only_clock(rig, script((0, 2, E)), parts=(part,)).direct()
    r.observe(0)
    r.update()
    on = minus(plus(rat(1), times(rat(2), expneg(Q(1, 2)))), times(rat(3), expneg(Q(2, 3))))
    off = times(rat(2), minus(rat(1), expneg(Q(1, 2))))
    assert_contains(r.sq("switch", on=("clk",)), divide(on, plus(on, off)))


def test_impl40_taken_across_a_boundary_then_empty_reads_the_cumulative_rate(rig):
    """取得の列 (taken が境目をまたぐ区間、後に empty の点) を 1 つの法則で読む: L_on = e^{−1}·E[Λ(U)] = (5/12)e^{−1}、
    L_off = e^{−1}/4 で、オンの確率はちょうど 5/8 (到着の率の積分 Λ で読み、taken を到着の時刻にしない)。"""
    part = clock(widths=(Q(1, 4), Q(3, 4)), shares=(Q(1, 2), Q(1, 2)))
    r = only_clock(rig, script((0, 2, T), (4, 4, E)), parts=(part,)).direct()
    r.observe(0)
    r.update()
    r.observe(1)
    r.update()
    assert r.sq("switch", on=("clk",)).exact == Q(5, 8)


def test_impl40_ineffective_clock_marginalizes_to_the_same_K39_and_p_moves_its_bit(rig):
    """決定 10 ①: f = w の時計 (全部の区切りで倍率 1) を足しても、時計のビットを周辺化すれば同じ a, b の K39 (調子の部品だけ) の
    定規 P(S=A | h) = 2/(3+x)・P(調子オン | h) = (1+x)/(3+x)・Z = (3x+x²)/4 に一致する。知る対象は増えない (時計のオンとオフが
    同じ識別)。時計のビットのオンの確率は p を通して調子の証拠で動く: (4 + 2x)/(9 + 3x)。"""
    part = clock(widths=(Q(1, 4), Q(3, 4)), shares=(Q(1, 4), Q(3, 4)))
    r = rig(script((4, 4, E)), rates=(Q(1), Q(1)), parts=(mood(), part), unit=Q(1, 4)).direct()
    r.observe(0)
    r.update()
    x = expneg(1)
    assert_contains(r.query("state", state="A"), divide(rat(2), plus(rat(3), x)))
    assert_contains(r.sq("switch", on=("c",)), divide(plus(rat(1), x), plus(rat(3), x)))
    assert_contains(r.sq("mass"), divide(plus(times(rat(3), x), times(x, x)), rat(4)))
    assert_contains(r.sq("switch", on=("clk",)), divide(plus(rat(4), times(rat(2), x)), plus(rat(9), times(rat(3), x))))
    resolved = fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry).candidates[0]
    assert len(resolved.states) == 8 and len(set(resolved.knowledge_targets)) == 4
    effective = rig(script((4, 4, E)), rates=(Q(1), Q(1)), parts=(mood(), clock()), unit=Q(1, 4)).direct()
    assert len(set(fb.resolve_belief_candidates(effective.boot(), reader=effective.ledger,
                                                registry=effective.registry).candidates[0].knowledge_targets)) == 8


def test_impl40_conditioning_on_clock_off_is_K39_with_b_plus_one(rig):
    """決定 10 ② (K40-01): 効く時計と調子の部品、a = b = 1、時刻 t = 1/4 の最初の empty (時計が見える時刻)。時計オフに
    条件づけると P(A | h, c = 0) = 3/(5 + x)、調子オンは (1 + x)/(5 + x) で、K39 (a, b+1) と同じ (x = e^{−t})。"""
    r = rig(script((1, 1, E)), rates=(Q(1), Q(1)), parts=(mood(), clock()), unit=Q(1, 4)).direct()
    r.observe(0)
    r.update()
    x = expneg(Q(1, 4))
    off = r.sq("switch", off=("clk",))
    assert_contains(ratio(r.sq("state", off=("clk",), state="A"), off), divide(rat(3), plus(rat(5), x)))
    assert_contains(ratio(r.sq("switch", on=("c",), off=("clk",)), off), divide(plus(rat(1), x), plus(rat(5), x)))


def test_impl40_periods_split_the_on_branch_without_adding_switches(rig):
    """決定 5: 周期の候補は時計のオンの枝を分けるだけで、k・|z|・p の Beta 成分の数に足さない。全部の候補の整数周の終わりの
    取得では周期の確信が動かず (定規「周期と位置の見分け」)、不等間隔の時刻では動く。"""
    part = clock(periods=(Q(1), Q(2)))
    r = rig(script((8, 8, E), (11, 11, E)), rates=(Q(1), Q(1)), parts=(mood(), part), unit=Q(1, 4)).direct()
    r.observe(0)
    r.update()
    resolved = fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry).candidates[0]
    assert len(resolved.states) == 2 * (1 + 2) * 2
    assert {c[0] for c in resolved.clocks if c is not None} == {Q(1), Q(2)}
    assert [c is None for c in resolved.clocks].count(True) == 4   # 時計オフの枝 2 つ × 状態 2

    def by_period():
        spec = ft._spec(r.host._state, r.expression())
        W, _Z = ft.weights(spec)
        out = {}
        for w, unit in zip(W, spec["units"]):
            if "clock" in unit["law"]:
                out[unit["law"]["clock"]["period"]] = out.get(unit["law"]["clock"]["period"], ft.Poly()) + w
        return out
    same = by_period()
    assert same[Q(1)] == same[Q(2)]
    r.observe(1)
    r.update()
    moved = by_period()   # t = 11/4: T = 1 は 2 周と 3/4 (Λ = 2 + 7/8)、T = 2 は 1 周と 3/8 (Λ = 2 + 9/8)
    assert ft.Ratio(moved[Q(1)], moved[Q(2)]) > 1
    mixture = r.host.p_distribution(belief=r.expression(), candidate=r.pool().members[0].id, family="f",
                                    budget=budget())
    assert [(c.a, c.b) for c in mixture.components] == [(1, 3), (2, 2), (2, 2), (3, 1)]
    assert r.host.verify_p_distribution(belief=r.expression(), distribution=mixture)


@pytest.mark.parametrize("case", ["coupling", "two_clocks"])
def test_impl40_unread_clock_declarations_are_named_before_thinking(rig, case):
    """この本が読まない時計の宣言は、起動の計画の不足として名指して止まる: 宣言した因子の積の外の依存 (couplings、決定 4)、時計の
    部品が 2 つ (決定 1)。連続の事前は読む (test_fb_impl40_continuous)。"""
    part = clock()
    if case == "coupling":
        part = replace(part, clock=replace(part.clock, couplings=(("period", "segments"),)))
    parts = (part, clock(name="clk2")) if case == "two_clocks" else (part,)
    r = only_clock(rig, script((1, 1, E)), parts=parts, thinking=True).direct()
    for _ in range(4):
        r.host.run_until(lambda _state: True, timeout=5)
    reason = {"coupling": "clock_coupling", "two_clocks": "clock_parts"}[case]
    pending = [p.reason for p in r.host.window.status().pending]
    assert any(x.startswith("perception:candidate:" + reason + ":") for x in pending), pending
    assert not r.requests("candidate_generation") and not r.requests("belief_update")
    with pytest.raises(fb.TimeBeliefError) as resolved:
        fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry)
    assert resolved.value.kind == "unsupported" and resolved.value.reason == reason
    assert {r.boot_input.declaration.perception.slot, "clk"} <= set(resolved.value.targets)


@pytest.mark.parametrize("changed,reason,code", [
    (dict(periods=((Q(1), Q(1, 2)), (Q(1), Q(1, 2)))), "clock_candidates", "shape"),   # 同じ周期を 2 回
    (dict(segments=((3, Q(1)),)), "clock_candidates", "shape"),                         # max_segments を超える m
    (dict(widths={"kind": "point", "values": ((3, (Q(1, 3),) * 3),)}), "clock_point", "shape"),   # 宣言に無い m の点
    (dict(widths={"kind": "point", "values": ((2, (Q(1),)),)}), "clock_point", "shape"),          # m と長さが違う点
    (dict(phase={"kind": "uniform", "value": Q(0)}), "clock_shape", "shape"),           # 種類に無い欄
    (dict(widths={"kind": "symmetric_dirichlet", "concentration": 1.0}), "clock_concentration", "shape"),   # 有理数でない
    (dict(phase={"kind": "wave"}), "clock_shape_kind", "missing_contract"),             # 知らない形の種類
    (dict(fractions={"kind": "symmetric_dirichlet", "concentration": Q(1)}), "clock_shape_kind", "missing_contract"),
])
def test_impl40_clock_declaration_values_are_named_by_the_resolution(changed, reason, code):
    """宣言の値の確かめは候補の解決の 1 か所 (`f_update2._clock_choices`、宣言の事実は先に残す): 値の誤りは invalid (shape)、
    この本が読めない形は unsupported (missing_contract)。名指しは候補と部品の名前。試験の係の試験 (test_clock1_invalid_or_...)
    に無い場合だけ。"""
    part = clock()
    with pytest.raises(u2.Unresolved) as error:
        u2._clock_choices("c", replace(part, clock=replace(part.clock, **changed)))
    assert (error.value.reason, error.value.code, error.value.named) == (reason, code, ("c", "clk"))
    choices, material = u2._clock_choices("c", part)
    assert len(choices) == 1 and material["segments"] == [2]


@pytest.mark.parametrize("kwargs", [dict(kind="clock", multipliers=()),
                                    dict(kind="mood", multipliers=(Q(1), Q(2)), clock=prior())])
def test_impl40_only_a_clock_part_reads_the_clock(kwargs):
    with pytest.raises(fb.TimeBeliefError) as error:
        fb.SwitchPart(id="x", **kwargs)
    assert error.value.field == "clock"


def test_impl40_clock_shape_mean_one_and_aliases():
    """決定 3: どの点の形でも 1 周の積分は T (平均の倍率 1)。決定 8: 区切りの番号・同じ高さの隣・短い周期の 2 回くり返し・
    f = w は同じ法則として比べる。"""
    shapes = [(Q(1, 3), (Q(1, 5), Q(3, 10), Q(1, 2)), (Q(1, 2), Q(1, 6), Q(1, 3))), (Q(0), (Q(1, 2), Q(1, 2)), (Q(3, 4), Q(1, 4)))]
    for rotation, widths, shares in shapes:
        for period in (Q(1), Q(7, 3)):
            part = clock(periods=(period,), widths=widths, shares=shares, rotation=rotation)
            ((_w, shape, _suffix),), _material = u2._clock_choices("c", part)
            for turns in (1, 2, 5):
                assert ft._clock_integral(shape, period * turns) == period * turns
    base = {"period": Q(1), "starts": [Q(0), Q(1, 2)], "multipliers": [Q(3, 2), Q(1, 2)]}
    twice = {"period": Q(2), "starts": [Q(0), Q(1, 4), Q(1, 2), Q(3, 4)], "multipliers": [Q(3, 2), Q(1, 2)] * 2}
    merged = {"period": Q(1), "starts": [Q(0), Q(1, 4), Q(1, 2)], "multipliers": [Q(3, 2), Q(3, 2), Q(1, 2)]}
    shifted = {"period": Q(1), "starts": [Q(1, 4), Q(3, 4)], "multipliers": [Q(3, 2), Q(1, 2)]}
    assert u2._clock_law(base) == u2._clock_law(twice) == u2._clock_law(merged) != u2._clock_law(shifted)
    flat = {"period": Q(1), "starts": [Q(1, 3), Q(1, 2)], "multipliers": [Q(1), Q(1)]}
    assert u2._clock_law(flat) is None


def test_impl40_clock_units_round_trip_and_K39_units_keep_their_bytes(rig):
    """正本 (決定 5): 時計のオンの枝の units は時計の形を持って保存・作り直しで同じ。時計の無い枝は欄を持たない (K39 の bytes
    のまま)。"""
    r = rig(script((1, 1, E)), rates=(Q(1), Q(1)), parts=(mood(), clock()), unit=Q(1, 4)).direct()
    r.observe(0)
    r.update()
    spec = ft._spec(r.host._state, r.expression())
    assert ft.decode_spec(u2._json(ft.encode_spec(spec))) == spec
    assert sorted("clock" in u["law"] for u in spec["units"]) == [False] * 4 + [True] * 4
    resolved = fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry).candidates[0]
    assert resolved.rates == (Q(1), Q(1)) * 2 + (Q(1), Q(2)) * 2   # 枝の順 z = 00, 01, 10, 11 (調子, 時計)
    on = (Q(1), ((Q(0), Q(3, 2)), (Q(1, 2), Q(1, 2))))
    assert resolved.clocks == (None, None, on, on, None, None, on, on)
