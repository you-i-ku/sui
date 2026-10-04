"""Stage-2 mathematical recursion; independent jump-time integrals/formulas.

No expected value is made by the new recursion. The existing test_progress
oracle is also independent: it integrates exponential jump time, not kernels.
Continuous starts remain expressions, not ExactCompletion/mono_ns records.
"""

from dataclasses import replace
from fractions import Fraction as F
import math

import pytest
from scipy.integrate import quad

from sui.inference import NumericalRange
from sui.joint import NameSpec
from sui.joint_lookahead import (KnownContinuation, RulerNode, RulerStart,
                                  evaluate_stage2)
from sui.joint_stage2 import OneJumpModel
from sui.lookahead import _policy
from sui.progress import CompletionSpec
from sui.quantity import IntegrationIncomplete
from sui.values import MeasureSpec
from test_progress import _oracle_information


LN2 = math.log(2)
IA = .6270419274355707
ROUND = 3e-14  # Arithmetic allowance, separate from certified truncation error.


def _model(action, pairs, weights, *, work=1, q=LN2):
    spec = CompletionSpec(name="progress", version="1", actions=(action,), states=("0", "1"),
                          work_unit="work", time_unit="second", speed_unit="work/second",
                          candidates=tuple((tuple(p),) for p in pairs), weights=tuple(weights),
                          share="all_actions", max_speed=max(c for pair in pairs for c in pair))
    return OneJumpModel(completion=spec, q=q, work=work, measure=MeasureSpec("exact", "1", {}),
                        names=NameSpec(((1,), (1,)), False, "report"),
                        initial_state="0", pending=(), max_reports=1)


def _models(pairs=((1, 1), (1, 2)), weights=(F(1, 2), F(1, 2))):
    return {"a": _model("a", pairs, weights), "b": _model("b", ((1, 1),), (F(1),))}


def _eval(models=None, *, horizon=1, continuations=(),
          slope=0, offsets=None, bound=None, gamma=1, u=.5, tolerance=1e-9,
          node_budget=100000, refinement_budget=5):
    models = _models() if models is None else models
    if offsets is None:
        offsets = {a: 0 for a in models}
        offsets.update({a.action: 0 for a in continuations if isinstance(a, KnownContinuation)})
    if bound is None:
        bound = float(slope)*float(horizon)+max(offsets.values())
    return evaluate_stage2(models, horizon_s=horizon, continuations=continuations,
                           cost_slope=slope, terminal_offsets=offsets, cost_bound=bound,
                           gamma=gamma, u=u, tolerance=tolerance, node_budget=node_budget,
                           refinement_budget=refinement_budget)


def _contains(box, value):
    assert box.lower-ROUND <= value <= box.upper+ROUND


def _walk(node):
    yield node
    if isinstance(node, RulerNode):
        for a in node.actions:
            yield from _walk(a.child)


def _assert_root(result, expected_costs, expected_information, gamma=1):
    scores = []
    for a, c, i in zip(result.root.actions, expected_costs, expected_information):
        _contains(a.expected_cost, c)
        _contains(a.information, i)
        _contains(a.increment, i)
        _contains(a.J_bounds, c-i)
        assert a.J == a.expected_cost.midpoint-a.information.midpoint
        scores.append(c-i)
    expected_q = _policy(scores, gamma)
    for q, bound in zip(expected_q, result.root.q_bounds):
        _contains(bound, q)
    # Exact reproduction of the §3-10 representative, including future policy.
    assert result.root.q == tuple(_policy([a.J for a in result.root.actions], gamma))


def test_progress_ruler_reaches_root_J_q_and_choice_with_certified_bounds():
    """Drops missing state/law information or treating timing as MI at fixed H."""
    r = _eval(u=.65)
    _assert_root(r, (0., 0.), (IA, 0.))
    _contains(r.root.q_bounds[0], .6518184260214424)
    assert r.chosen == "a"
    assert _eval(u=.66).chosen == "b"
    assert r.max_depth == 2  # Continuous completion is followed by a real choice.
    assert r.integration_nodes > 0
    for a in r.root.actions:
        for b in (a.expected_cost, a.information, a.J_bounds):
            assert b.upper-b.lower <= 1e-9
    assert all(q.upper-q.lower <= 1e-9 for q in r.root.q_bounds)


def test_atom_posterior_stays_joint_not_independent_and_density_is_separate():
    """At R=1 the impossible (fast,1) is 0, not the product 1/9."""
    r = _eval()
    atom, = (e for e in r.root.actions[0].children if e.basis == "atom")
    continuous, = (e for e in r.root.actions[0].children if e.basis == "density")
    assert atom.probability == pytest.approx(.75, abs=ROUND)
    assert continuous.probability == pytest.approx(.25, abs=ROUND)
    post = atom.potential.belief.target_marginal()
    assert post[((F(1), F(2)), 1)] == 0
    assert all(post[k] == pytest.approx(1/3, abs=ROUND) for k in post if k[1] == 0 or k[0] == (F(1), F(1)))
    wrong = sum(p for (rho, _), p in post.items() if rho == (F(1), F(2))) * sum(p for (_, s), p in post.items() if s == 1)
    assert wrong == pytest.approx(1/9, abs=ROUND)
    _contains(r.root.actions[0].information, IA)


def test_continuous_starts_are_shared_expressions_not_quadrature_facts():
    """C includes the deadline atom; materialized grid times lose variable r."""
    r = _eval(slope=1)
    edges = [e for e in r.root.actions[0].children if e.basis == "density"]
    assert [(e.lower_s, e.upper_s) for e in edges] == [(F(1, 2), F(1))]
    assert len(edges) < r.integration_nodes
    for e in edges:
        assert e.start == RulerStart("R:a", F(0))
        assert e.potential.belief is None
        for child in _walk(e.child):
            assert child.start.variable == e.start.variable
            assert child.potential is e.potential
            with pytest.raises(IntegrationIncomplete, match="record"):
                int(child.start)
            with pytest.raises(IntegrationIncomplete, match="facts"):
                float(child.start)
    expected = .75+1/(8*LN2)
    _contains(r.root.actions[0].expected_cost, expected)
    wrong = .25*.75  # Density-midpoint cost, with the old missing deadline start.
    assert abs(expected-wrong) > .7


def test_nonarrival_law_information_survives_to_root_J_q():
    """Drops the p_bot*B_bot contribution, or adds the missed state to target."""
    h = F(3, 4)
    r = _eval(horizon=h)
    a = r.root.actions[0]
    miss, = (e for e in a.children if e.basis == "not_arrived")
    p = .5+.5*2**(-.5)
    fast = math.sqrt(2)-1
    B = fast*math.log(2*fast)+(1-fast)*math.log(2*(1-fast))
    assert miss.probability == pytest.approx(.8535533905932737, abs=ROUND)
    assert miss.potential.value_at(None).laws == pytest.approx(B, abs=ROUND)
    assert miss.potential.value_at(None).state == 0
    assert miss.probability*B == pytest.approx(.0126255077, abs=5e-11)
    # Independent integration over jump time T; report r=(1+T)/2.
    seen = .5*(1-2**(-.5))
    law = seen*LN2+p*B
    state = .5*quad(lambda t: LN2*2**(-t)*-math.log1p(-2**(-(1+t)/2)), 0, .5,
                    epsabs=2e-13, epsrel=2e-13)[0]
    _assert_root(r, (0, 0), (law+state, 0))
    assert a.information.midpoint-(seen*LN2+state) > .0126
    assert miss.child.start.offset_s == 0  # Miss means no next start at H.


def test_slowing_ruler_and_later_reports_keep_the_original_root_potential():
    """The root atom permits a second informative a; filtering it falsely succeeds."""
    models = _models(((2, 1),), (F(1),))
    with pytest.raises(IntegrationIncomplete, match="candidate a may yield another informative report"):
        _eval(models)
    # Independent original-kernel reference remains tested in test_progress.
    # At R=1/2 the state is 0, so another a can finish at H=1 if no jump.
    assert 2**(-.5) > 0
    wrong_success_information = .5*LN2*2**(-.5)+quad(
        lambda t: LN2*2**(-t)*-math.log1p(-2**(-(1-t))), 0, .5)[0]
    assert wrong_success_information == pytest.approx(.5106087339294864, abs=3e-13)
    # A smaller window certifies EVERY suffix candidate outside, preserving
    # the same ruler atom/density/posterior and fixed-root potential tests.
    r = _eval(models, horizon=F(3, 4))
    atom, = (e for e in r.root.actions[0].children if e.basis == "atom")
    assert atom.probability == pytest.approx(2**(-.5), abs=ROUND)
    for child in _walk(atom.child):
        assert child.potential is atom.potential
        assert child.potential.value_at(None).total == pytest.approx(LN2/2, abs=ROUND)
    law, state, _, _ = _oracle_information(((2, 1),), (F(1),), 1, LN2, F(3, 4))
    _assert_root(r, (0, 0), (law+state, 0))


def test_two_step_affine_start_cost_and_next_softmax_match_independent_formula():
    """C_a=3/4+1/(8log2)+log3/4; C_b=1+log3/4, with common U."""
    r = _eval(slope=1, offsets={"a": 0, "b": math.log(3)})
    ca = .75+1/(8*LN2)+math.log(3)/4
    cb = 1+math.log(3)/4
    direct = .75*(1+math.log(3)/4)+.5*quad(
        lambda t: LN2*2**(-t)*((1+t)/2+math.log(3)/4), 0, 1,
        epsabs=2e-13, epsrel=2e-13)[0]
    assert direct == pytest.approx(ca, abs=ROUND)
    _assert_root(r, (ca, cb), (IA, 0))
    wrong = 1/(8*LN2)+math.log(3)/16
    assert abs(ca-wrong) > .9  # Old deadline leaf / replaced suffix U.
    for a in r.root.actions:
        for edge in a.children:
            assert edge.child.q == pytest.approx((.75, .25), abs=ROUND)
            assert tuple(v.action for v in edge.child.actions) == ("a", "b")
            for child in _walk(edge.child):
                assert child.potential is edge.potential


def test_deadline_partition_affine_cost_matches_full_three_step_integral():
    """Quick wait was not in root U: adding it leaves a root branch uncertified."""
    models = _models()
    models["wait"] = _model("wait", ((4, 4),), (F(1),))
    with pytest.raises(IntegrationIncomplete, match="candidate a may yield another informative report"):
        _eval(models, slope=1)
    # Wrong suffix-only wait gives this independent value, but has no valid
    # root decision for the common U containing wait.
    wrong = 1/(8*LN2)+(1-2**(-.5))/8
    assert wrong == pytest.approx(.216948532462802, abs=ROUND)
    # A fully certified three-step ruler: sole known 1/4 job, H=1/2,
    # starts 0,1/4,1/2. Correct last-start cost 1/2; old boundary gives 1/4.
    closed = {"b": _model("b", ((4, 4),), (F(1),))}
    r = _eval(closed, horizon=F(1, 2), slope=1)
    _assert_root(r, (.5,), (0,))
    assert r.max_depth == 3 and r.root.actions[0].expected_cost.midpoint != .25


def test_slowing_density_first_moment_and_atomic_next_start_match_direct_formula():
    models = _models(((2, 1),), (F(1),))
    with pytest.raises(IntegrationIncomplete, match="another informative report"):
        _eval(models, slope=1)
    wrong_old_success = 1-(1-2**(-.5))/LN2
    assert wrong_old_success == pytest.approx(.5774444057078261, abs=ROUND)
    h = F(3, 4)
    r = _eval(models, horizon=h, slope=1)
    # For T<1/4, R>H: no later start. T in [1/4,1/2] gives
    # R=1-T, while T>=1/2 gives the atom R=1/2.
    expected = .5*2**(-.5)+quad(lambda t: LN2*2**(-t)*(1-t), .25, .5,
                               epsabs=2e-13, epsrel=2e-13)[0]
    law, state, _, _ = _oracle_information(((2, 1),), (F(1),), 1, LN2, h)
    _assert_root(r, (expected, 0), (law+state, 0))
    assert abs(expected-wrong_old_success) > .1


def test_root_q_error_refines_the_whole_information_and_future_policy():
    from scipy.optimize import brentq
    h, gamma = F(3, 4), 1500
    law, state, _, _ = _oracle_information(((1, 1), (1, 2)), (F(1, 2), F(1, 2)), 1, LN2, h)
    information = law+state
    p = .5+.5*2**(-.5)
    x = brentq(lambda x: p*x+(1-p)*x*math.exp(-gamma*x)/(1+math.exp(-gamma*x))-information, 0, 1,
               xtol=1e-15)
    r = _eval(horizon=h, offsets={"a": x, "b": 0}, gamma=gamma,
              tolerance=1e-8, refinement_budget=8)
    _assert_root(r, (information, 0), (information, 0), gamma=gamma)
    assert r.refinements > 1
    assert all(q.upper-q.lower <= 1e-8 for q in r.root.q_bounds)
    # A midpoint of q's interval is not the midpoint-J softmax representative.
    assert r.root.q == tuple(_policy([a.J for a in r.root.actions], gamma))


@pytest.mark.parametrize("h", [F(2, 5), F(4, 5), F(2)])
def test_arbitrary_mixture_root_matches_independent_full_jump_time_integral(h):
    pairs = ((1, 3), (2, 1), (F(4, 3), F(4, 3)))
    weights = (F(1, 5), F(1, 2), F(3, 10))
    models = {"a": _model("a", pairs, weights, q=.9), "b": _model("b", ((1, 1),), (F(1),), q=.9)}
    if h >= F(4, 5):
        with pytest.raises(IntegrationIncomplete, match="another informative report"):
            _eval(models, horizon=h)
        # Replacing U with wait falsely returns the first-report oracle value.
        law, state, _, _ = _oracle_information(pairs, weights, 1, .9, h)
        assert law+state > 0
        return
    r = _eval(models, horizon=h)
    law, state, _, _ = _oracle_information(pairs, weights, 1, .9, h)
    _assert_root(r, (0, 0), (law+state, 0))


def test_density_overlapping_an_atom_is_not_added_to_that_atom():
    pairs, weights = ((1, 1), (F(2, 3), 2)), (F(1, 2), F(1, 2))
    with pytest.raises(IntegrationIncomplete, match="another informative report"):
        _eval(_models(pairs, weights), horizon=F(3, 2))
    r = _eval(_models(pairs, weights), horizon=F(1))
    atom = next(e for e in r.root.actions[0].children if e.basis == "atom" and e.lower_s == 1)
    assert atom.probability == pytest.approx(.5, abs=ROUND)
    assert atom.potential.belief.speed_marginal()[(F(2, 3), F(2))] == 0
    assert sum(e.probability for e in r.root.actions[0].children) == pytest.approx(1, abs=ROUND)
    law, state, _, _ = _oracle_information(pairs, weights, 1, LN2, F(1))
    _assert_root(r, (0, 0), (law+state, 0))


def test_equal_speed_early_report_and_repeated_reports_have_zero_information():
    models = {"b": _model("b", ((4, 4),), (F(1),))}
    r = _eval(models)
    assert r.max_depth == 5  # Correct deadline choice, old strict comparison gives 4.
    a, = r.root.actions
    _contains(a.information, 0.)
    _contains(a.J_bounds, 0.)
    atom, = a.children
    assert atom.potential.belief.target_marginal()[((F(4), F(4)), 1)] == pytest.approx(1-2**(-.25), abs=ROUND)


def test_duplicate_speed_laws_scaling_and_midpoint_replay_are_invariant():
    original = _eval()
    duplicate = _eval(_models(((1, 1), (1, 2), (1, 2)), (F(1, 2), F(1, 6), F(1, 3))))
    scaled = _eval({"a": _model("a", ((3, 3), (3, 6)), (F(1, 2), F(1, 2)), work=3),
                    "b": _model("b", ((3, 3),), (F(1),), work=3)})
    assert original == _eval()
    for r in (duplicate, scaled):
        assert r.root.q == original.root.q
        assert tuple(a.J_bounds for a in r.root.actions) == tuple(a.J_bounds for a in original.root.actions)


@pytest.mark.parametrize("changes,reason", [
    ({"node_budget": 1}, "budget"),
    ({"bound": 0, "slope": 1}, "cost_bound"),
    ({"horizon": F(2)}, "another informative report"),
    ({"continuations": (_model("later", ((1, 2),), (F(1),)),)}, "continuation"),
    ({"continuations": (KnownContinuation("a", F(1)),)}, "reused action"),
])
def test_uncertified_or_unfinished_stage2_query_stops_without_dropping_candidate(changes, reason):
    with pytest.raises(IntegrationIncomplete, match=reason):
        _eval(**changes)


def test_bad_root_type_common_rate_and_zero_delay_stop():
    with pytest.raises(IntegrationIncomplete, match="models"):
        _eval({"a": object()})
    models = _models()
    models["b"] = replace(models["b"], q=.9)
    with pytest.raises(IntegrationIncomplete, match="common rate"):
        _eval(models)
    with pytest.raises(IntegrationIncomplete, match="positive delay"):
        KnownContinuation("wait", 0)


@pytest.mark.parametrize("changes", [
    {"gamma": F(1, 10**400)}, {"slope": F(1, 10**400)},
    {"gamma": 1000000},
])
def test_positive_controls_or_candidate_probabilities_cannot_round_to_zero(changes):
    with pytest.raises(NumericalRange):
        _eval(**changes)


def test_positive_quadrature_error_cannot_disappear_from_float_endpoints():
    # A nonzero Simpson remainder smaller than one ulp must stop, not return
    # a zero-width information/J/q certificate. This is a numerical-range
    # failure, distinct from spending the requested work budget.
    with pytest.raises(NumericalRange, match="integration error"):
        _eval(tolerance=1e-18, refinement_budget=1)


def test_zero_window_and_gamma_zero_are_exact_and_do_not_create_reports():
    r = _eval(horizon=0, continuations=(), gamma=0)
    assert r.root.q == (.5, .5)
    assert all(a.information.lower == a.information.upper == a.J == 0 for a in r.root.actions)
    assert all(len(a.children) == 1 and a.children[0].basis == "not_arrived" for a in r.root.actions)
    assert r.integration_nodes == 0


def test_cost_bound_applies_to_actual_terminal_starts_not_horizon():
    # At H=1 the known report creates another choice: last start=1, not 0.
    model = {"b": _models()["b"]}
    r = _eval(model, slope=1, bound=1)
    assert r.root.actions[0].expected_cost.midpoint == 1
    assert r.root.actions[0].expected_cost.midpoint != 0  # Old >= terminal.
    with pytest.raises(IntegrationIncomplete, match="cost_bound"):
        _eval(model, slope=1, bound=0)

