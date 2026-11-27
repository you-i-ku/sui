"""K41 decisions 7, 9 and 10. Compare through adoption and actual evaluation."""

from dataclasses import replace
from fractions import Fraction as Q

import pytest

from test_fb_clock_belief import ReleasedClockSource, clock_prior
from test_fb_cycle import E
from test_fb_time_belief import TimeRig, assert_contains, script
from k41_world import (
    FAIR, HALF, ONE, ONE_WAY, X, ZERO, adopt, at_entry, complement, divide, entropy, expneg,
    generator, logarithm, minus, observation_document, plus, rat, scaled, selection, times, worlds,
)


@pytest.mark.parametrize("kind", ["state-rates", "mood", "inert-clock", "point-clock", "continuous-clock"])
@pytest.mark.parametrize("process", [None, ZERO], ids=["omitted", "declared-zero"])
def test_zero_process_and_omission_return_the_static_quantities(worlds, kind, process):
    # At half a turn, a point rotation changes the hazard. Uniform rotation
    # has integrated hazard uniformly distributed from R/4 to 3R/4.
    mood = kind in ("mood", "inert-clock")
    clock = None
    if kind == "inert-clock":
        clock = clock_prior(fractions=(HALF, HALF))
    elif kind in ("point-clock", "continuous-clock"):
        clock = clock_prior(phase=Q(0) if kind == "point-clock" else None)
    r = worlds(process=process, prior=FAIR, rates=(1, 1) if mood else (1, 2),
               family=None if kind == "state-rates" else "family",
               state_role=None if kind == "state-rates" and process is None else "mood",
               mood=mood, clock=clock, unit=HALF, thinking=True).start()
    expression = adopt(r)
    if mood:
        a = scaled(Q(1, 4), plus(ONE, expneg(HALF)))
        b = scaled(HALF, expneg(HALF))
    else:
        def weight(rate):
            off = expneg(rate*HALF)
            if clock is None:
                return scaled(HALF, off)
            on = expneg(rate*Q(3, 4))
            if kind == "continuous-clock":
                on = scaled(Q(2, rate), times(expneg(Q(rate, 4)), complement(off)))
            return scaled(Q(1, 4), plus(off, on))
        a, b = weight(1), weight(2)
    z = plus(a, b)
    p = divide(a, z)
    assert_contains(r.query("mass", tolerance=Q(1, 2048)), z)
    assert_contains(r.query("state", state="A", tolerance=Q(1, 2048)), p)
    assert_contains(r.query("state", state="B", tolerance=Q(1, 2048)), complement(p))
    selection(r, r.think(), expression, entropy(p))


def test_ce1_stays_on_the_finite_law_for_first_and_second():
    r = TimeRig(script((20, 20, E), (30, 30, E)), unit=Q(1, 10), finite=True, thinking=True)
    try:
        r.passive = ReleasedClockSource(r)
        r.direct()
        r.think()
        for i, (p, z) in enumerate([(Q(4, 5), Q(5, 32)), (Q(8, 9), Q(9, 128))]):
            expression = adopt(r, i)
            assert r.query("state", state="A").exact == p
            assert r.query("state", state="B").exact == 1-p
            assert r.query("mass").exact == z
            r.check_selection(r.think(), rat(p), expression)
    finally:
        r.close()


def candidate_targets(r):
    resolved = r.resolved(r.pool().point)
    assert len(resolved.candidates) == 2
    return tuple(set(c.knowledge_targets) for c in resolved.candidates)


@pytest.mark.parametrize("moving_first", [False, True])
def test_candidate_order_separates_laws_with_equal_evidence_but_distinct_predictions(worlds, moving_first):
    # Both assign probability one to empty. With a constant original target,
    # Y distinguishes only the two resolved laws. The information is positive.
    r = worlds(process=ONE_WAY if moving_first else None, rates=(0, 0), thinking=True,
               targets=("same", "same"), measurement=at_entry()).start()
    first = adopt(r)
    selection(r, r.think(), first, rat(0), rat(HALF))
    other = replace(r.law(), state_process=None if moving_first else generator(ONE_WAY))
    r.add_law(other)
    expression = r.update()
    before, after = candidate_targets(r)
    assert before.isdisjoint(after)
    p = complement(X)
    assert_contains(r.query("state", state="B"), scaled(HALF, p))
    assert_contains(r.query("candidate", candidate="later"), rat(HALF))
    assert_contains(r.query("mass"), ONE)
    info = minus(entropy(scaled(HALF, p)), scaled(HALF, entropy(p)))
    selection(r, r.think(), expression, info)


@pytest.mark.parametrize("variant", ["alias", "permutation", "unreachable-rate"])
def test_alias_and_unproved_partition_keep_information_and_policy(worlds, variant):
    unreachable = variant == "unreachable-rate"
    matrix = ((0, 0), (1, -1)) if unreachable else ONE_WAY
    r = worlds(process=matrix, thinking=True, measurement=at_entry()).start()
    first = adopt(r)
    info = rat(0) if unreachable else logarithm(rat(2))
    chance = rat(HALF if unreachable else Q(2, 3))
    selection(r, r.think(), first, info, chance)
    other = r.law()
    if unreachable:
        other = replace(other, state_process=generator(((0, 0), (2, -2))))
    if variant == "permutation":
        other = replace(other, states=("B", "A"), rates=(Q(1), Q(0)), prior=(Q(0), Q(1)),
                        state_process=generator(((0, 0), (1, -1))))
    r.add_law(other, alpha=Q(1, 3))
    expression = r.update()
    original, added = candidate_targets(r)
    if unreachable:
        assert original.isdisjoint(added)
    else:
        assert original == added
    assert_contains(r.query("candidate", candidate="later"), rat(Q(1, 3)))
    assert_contains(r.query("mass"), ONE if unreachable else scaled(2, X))
    selection(r, r.think(), expression, info, chance)


def test_three_states_unproved_split_preserves_nonzero_information(worlds):
    r = worlds(thinking=True, measurement=at_entry())
    r.labels = r.targets = ("A", "B", "C")
    r.sensor = (Q(0), Q(1), Q(1))
    prior = (Q(1), Q(0), Q(0))
    matrix = ((-1, 1, 0), (0, 0, 0), (1, 0, -1))
    law = replace(r.law(), states=r.labels, prior=prior, rates=(Q(0), Q(1), Q(1)),
                  state_process=generator(matrix))
    r.replace_model(observation_document(prior, r.sensor, r.targets, r.labels))
    decl = r.boot_input.declaration
    slot, = decl.observation_models
    control_independence = replace(slot.value.control_independence,
        args={"weights_by_initial_state": [[[1, 1]] for _ in law.states]})
    observation = replace(slot.value, law=law, control_independence=control_independence)
    per = decl.perception
    derivation = per.value.derivation
    args = dict(derivation.method.args)
    args["correspondence"] = {"pairs": [[s, s] for s in law.states]}
    r.boot_input = replace(r.boot_input, declaration=replace(decl,
        observation_models=(replace(slot, value=observation),),
        perception=replace(per, value=replace(per.value, derivation=replace(derivation,
            method=replace(derivation.method, args=args))))))
    r.start()
    first = adopt(r)
    selection(r, r.think(), first, logarithm(rat(2)), rat(Q(2, 3)))
    r.add_law(replace(law, state_process=generator((*matrix[:2], (2, 0, -2)))))
    combined = r.update()
    original, added = candidate_targets(r)
    assert original.isdisjoint(added)
    assert_contains(r.query("state", state="C"), rat(0))
    selection(r, r.think(), combined, logarithm(rat(2)), rat(Q(2, 3)))


def test_declared_zero_resolves_to_the_omitted_process_in_one_pool(worlds):
    r = worlds(prior=FAIR, process=None, thinking=True).start()
    first = adopt(r)
    p = divide(ONE, plus(ONE, X))
    selection(r, r.think(), first, entropy(p))
    r.add_law(replace(r.law(), state_process=generator(ZERO)))
    combined = r.update()
    original, added = candidate_targets(r)
    assert original == added
    assert_contains(r.query("mass"), scaled(HALF, plus(ONE, X)))
    selection(r, r.think(), combined, entropy(p))


def test_replaying_one_record_and_observing_another_keep_distinct_roots(worlds):
    r = worlds(script((1, 1, E), (1, 1, E))).start()
    first = adopt(r)
    value = r.query("mass")
    second = adopt(r, 1)
    assert first.root != second.root and not r.host.same_belief(left=first, right=second)
    assert second.observations[:1] == first.observations and len(set(second.observations)) == 2
    assert not r.host.verify_belief_value(belief=second, value=value)
    assert_contains(r.query("mass"), scaled(2, X))
    r.host.rebuild_window()
    rebuilt = r.expression()
    assert rebuilt.root == second.root and rebuilt.observations == second.observations
    assert r.host.same_belief(left=second, right=rebuilt)
    assert r.passive.calls == [0, 0]
