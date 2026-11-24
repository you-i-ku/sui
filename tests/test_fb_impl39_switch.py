"""実装の係の小さい確かめ (K39 スイッチ式と p)。試験の係の試験 (test_fb_switch_belief) ではない。紙 F-b K39 の定規の一部と、
実装で決めた理由の語を、K38 の試験の足場 (test_fb_time_belief の TimeRig) の上で確かめる。"""

from dataclasses import replace
from fractions import Fraction as Q

import pytest

from sui import fb, f_update2 as u2
from test_fb_time_belief import (TimeRig, script, E, T, assert_contains, rat, plus, times, divide, expneg, time_api,
                                 budget)


class SwitchRig(TimeRig):
    def __init__(self, plan, *, parts=(), role="mood", a=Q(1), b=Q(1), **kwargs):
        self.parts, self.role, self.a, self.b = tuple(parts), role, a, b
        super().__init__(plan, **kwargs)

    def law(self, *, rates=None, prior=None):
        return fb.PoissonLaw(run=self.clock.run, states=("A", "B"), prior=prior or self.time_prior,
                             rates=self.rates if rates is None else rates, origin_ns=self.origin,
                             initial_count=self.initial_count, time_unit=self.unit, family="f",
                             parts=self.parts, a=self.a, b=self.b, state_role=self.role)

    def sq(self, kind, *, candidate=None, **kwargs):
        quantity = fb.SwitchQuantity(kind=kind, candidate=candidate or self.pool().members[0].id, family="f", **kwargs)
        expression = self.expression()
        value = self.host.query_switch_belief(belief=expression, quantity=quantity, budget=budget())
        assert self.host.verify_belief_value(belief=expression, value=value)
        return value


def mood(multipliers=(Q(1), Q(2)), name="c"):
    return fb.SwitchPart(id=name, kind="mood", multipliers=tuple(multipliers))


@pytest.fixture
def rig():
    made = []

    def make(plan, *, plain=False, **kwargs):
        time_api()
        r = TimeRig(plan, **kwargs) if plain else SwitchRig(plan, **kwargs)
        made.append(r)
        return r
    yield make
    for r in reversed(made):
        r.close()


def test_impl39_k1_ruler_mixture_and_unsupported_cdf(rig):
    r = rig(script((1, 1, E)), rates=(Q(1), Q(1)), parts=(mood(),)).direct()
    r.observe(0)
    r.update()
    x = expneg(1)
    w = divide(plus(rat(1), x), plus(rat(3), x))
    assert_contains(r.sq("switch", on=("c",)), w)
    assert_contains(r.sq("p_mean"), divide(plus(rat(1), w), rat(3)))
    assert_contains(r.sq("p_moment", order=2), divide(plus(rat(2), times(rat(4), w)), rat(12)))
    mixture = r.host.p_distribution(belief=r.expression(), candidate=r.pool().members[0].id, family="f",
                                    budget=budget())
    assert [(c.a, c.b) for c in mixture.components] == [(1, 2), (2, 1)]
    assert_contains(mixture.components[1].weight, w)
    assert r.host.verify_p_distribution(belief=r.expression(), distribution=mixture)
    with pytest.raises(fb.TimeBeliefError) as error:
        r.sq("p_cdf", point=Q(1, 2))
    assert error.value.kind == "unsupported" and "f" in error.value.targets


@pytest.mark.parametrize("case", ["no_role", "base_rate", "two_moods", "unknown_kind", "unknown_role", "pairs"])
def test_impl39_unresolvable_boot_candidate_is_a_boot_shortfall_before_thinking(rig, case):
    """K39-b R1・R4: 起動の宣言の候補が解けなければ、起動の計画の不足として示し、考える・更新・一歩へ進まない。"""
    rates = (Q(1), Q(2)) if case == "base_rate" else (Q(1), Q(1))
    parts = {"two_moods": (mood(), mood((Q(1), Q(3)), name="d")),
             "unknown_kind": (fb.SwitchPart(id="weather", kind="weather", multipliers=(Q(1), Q(1))),)}.get(case, (mood(),))
    role = {"no_role": None, "unknown_role": "weather"}.get(case, "mood")
    r = rig(script((1, 1, E)), rates=rates, parts=parts, role=role, thinking=True)
    if case == "pairs":
        declaration = r.boot_input.declaration
        method = declaration.perception.value.derivation.method
        args = dict(method.args, correspondence={"pairs": [["X", "A"], ["B", "B"]]})
        r.boot_input = replace(r.boot_input, declaration=replace(declaration, perception=replace(
            declaration.perception, value=replace(declaration.perception.value, derivation=replace(
                declaration.perception.value.derivation, method=replace(method, args=args))))))
    r.direct()
    for _ in range(4):
        r.host.run_until(lambda _state: True, timeout=5)
    reason = {"no_role": "mood_role", "base_rate": "mood_base_rate", "two_moods": "mood_parts",
              "unknown_kind": "part_kind", "unknown_role": "state_role", "pairs": "correspondence"}[case]
    pending = [p.reason for p in r.host.window.status().pending]
    assert any(x.startswith("perception:candidate:" + reason + ":") for x in pending), pending
    assert not r.requests("candidate_generation") and not r.requests("belief_update")
    with pytest.raises(fb.TimeBeliefError) as resolved:
        fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry)
    assert resolved.value.reason == reason and r.boot_input.declaration.perception.slot in resolved.value.targets


def test_impl39_added_unresolvable_candidate_is_refused_by_name(rig):
    r = rig(script((1, 1, E)), rates=(Q(1), Q(1)), parts=(mood(),)).direct()
    r.observe(0)
    r.update()
    r.role = None
    with pytest.raises(fb.TimeBeliefError) as error:
        r.add_time_candidate(rates=(Q(3), Q(3)), prior=(Q(3, 4), Q(1, 4)))
    assert error.value.kind == "unsupported" and error.value.reason == "mood_role"
    assert error.value.targets == ("later", "c")
    assert len(r.pool().members) == 1   # 何も保存しない


def test_impl39_state_query_naming_a_candidate_is_invalid(rig):
    r = rig(script((1, 1, E)), plain=True).direct()
    r.observe(0)
    r.update()
    with pytest.raises(fb.TimeBeliefError) as error:
        r.query("state", state="A", candidate=r.pool().members[0].id)
    assert error.value.kind == "invalid" and error.value.field == "candidate"


def test_impl39_host_and_U_resolve_the_same_initial_candidate(rig):
    r = rig(script((1, 1, E)), rates=(Q(1), Q(1)), parts=(mood(),)).direct()
    r.observe(0)
    expression = r.update()
    host = r.host._state.initial_pools[r.boot()].members[0]
    again = u2.initial_candidate(r.ledger, r.boot())
    assert u2._dumps_enc(host["document"]) == u2._dumps_enc(again["document"])
    assert expression.model != r.boot_input.declaration.perception.value.model   # 派生のモデル (展開)
    assert len(r.pool().states) == 4


def test_impl39_step_before_first_acquisition_resolves_the_same_switch_law(rig):
    r = rig(script((3, 3, E)), rates=(Q(1), Q(1)), parts=(mood(),), thinking=True, start_ns=1002).start()
    selected = r.think()
    r.enter_step(selection=selected.cid)
    r.finish_step(0, T)
    first = r.update()
    assert r.sq("switch", on=("c",)).exact == Q(1, 2)   # 一歩は S だけに依る (I_z)
    assert r.query("state", state="A").exact == Q(2, 3)
    r.clock.set(r.origin + 3)
    r.observe(0)
    final = r.update()
    y = expneg(3)
    assert_contains(r.sq("switch", on=("c",)), divide(plus(rat(2), y), plus(rat(5), y)))
    assert final.model == first.model


def test_impl39_K38_law_is_the_zero_part_family_without_p(rig):
    plain = rig(script((1, 1, E)), plain=True).direct()
    plain.observe(0)
    plain.update()
    r = rig(script((1, 1, E))).direct()
    r.observe(0)
    r.update()
    assert r.expression().model == plain.expression().model   # 部品 0 個は展開しない (K38 のモデルのまま)
    assert r.sq("p_mean").exact == Q(1, 2)
    with pytest.raises(fb.TimeBeliefError) as error:
        plain.host.query_switch_belief(belief=plain.expression(), quantity=fb.SwitchQuantity(
            kind="p_mean", candidate=plain.pool().members[0].id, family="f"), budget=budget())
    assert error.value.kind == "invalid" and error.value.field == "family"
