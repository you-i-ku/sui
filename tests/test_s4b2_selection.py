"""S4b-2 v0.9, phase 3: independent information and public choice contracts.

T07/T08 use the §6-4 G/T integrals and rational log/exp remainders.
T09/T10 distinguish M11/M14-M17/M22/M23/M26 at the public selector.
M12/M13 also have finite mathematical counterexamples: those are not a claim
of public certification outside C1, or of production mutations being KILLED.
Certificate structure/trace checks cannot replace phase-4 replay verification.
"""
from dataclasses import replace
from fractions import Fraction as F
from functools import lru_cache

import pytest

from sui import rate, rate_entry
from sui.contracts import ContractRef
from s4b2_fixtures import s4b2_independent_information
from s4b2_worlds import (
    CANDIDATES, NS, Q_READ, Q_WITHOUT_ARRIVALS, STANDARD_BUDGET, U,
    boundary_evaluation, c1_world, evaluation_root, four_rate_declaration,
    independent_arrival_declaration, tick_declaration,
)
from test_s4b2_contract import _entropy_bounds, _exp_bounds, _log_bounds
from test_s4b2_learning import future_moment_mass, root_moment_mass


ZERO = rate.RationalInterval(F(0), F(0))
ONE = rate.RationalInterval(F(1), F(1))


def outward(lower, upper, places=24):
    """Exact rational outward rounding, never a binary float endpoint."""
    grid = 10**places
    return rate.RationalInterval(F(lower*grid // 1, grid),
                                 F(-((-upper*grid) // 1), grid))


def sigmoid(bounds):
    rounded = outward(bounds.lower, bounds.upper)
    lo, hi = rounded.lower, rounded.upper
    elo, ehi = _exp_bounds(lo)[0], _exp_bounds(hi)[1]
    return outward(elo/(1+elo), ehi/(1+ehi))


@lru_cache(maxsize=None)
def information_ruler(n):
    """I_p + I(S2;C) <= I_read <= I_p + H(C), including root overflow."""
    z = sum(root_moment_mass(n))
    joint = tuple(tuple(x/z for x in cell) for cell in future_moment_mass(n))
    hc = _entropy_bounds(tuple(map(sum, joint)))
    hs = _entropy_bounds(tuple(sum(row[s] for row in joint) for s in range(2)))
    hsc = _entropy_bounds(tuple(x for row in joint for x in row))
    lp, hp = _log_bounds(F(2))
    return outward(lp-F(1, 2)+hc[0]+hs[0]-hsc[1], hp-F(1, 2)+hc[1])


def finite(bounds, *, support="signed", certificate=None):
    return rate.CertifiedQuantity("finite", bounds, support, None, None, certificate)


def probability_evaluation(first):
    """Public selector fixture. It is not a replay-verified Certificate.

    Used to exercise inequalities independently from the numerical evaluator.
    """
    base = boundary_evaluation()
    complement = rate.RationalInterval(1-first.upper, 1-first.lower)
    return replace(base, q_star=tuple(finite(x, support="positive", certificate=base.certificate)
        for x in (first, complement)), cumulative=(ZERO, first, ONE))


def assert_selected(evaluation, u, index):
    chosen = rate.certify_choice(evaluation, u=u)
    assert (chosen.index, chosen.choice, chosen.u) == (index, evaluation.candidates[index], F(u))
    assert isinstance(chosen.u, F)
    for initial, refined in ((evaluation.cumulative[index], chosen.previous),
                             (evaluation.cumulative[index+1], chosen.current)):
        assert initial.lower <= refined.lower <= refined.upper <= initial.upper
    assert chosen.previous.upper <= chosen.u < chosen.current.lower
    return chosen


@pytest.mark.parametrize("n", range(3))
def test_T07_independent_information_and_probability_rulers_match_spec(n):
    info = information_ruler(n)
    shown = ((276612033823, 1397143202808), (266837165387, 1559379163552),
             (245126105460, 1547520546940))[n]
    assert F(shown[0], 10**12) <= info.lower <= info.upper <= F(shown[1], 10**12)
    q = sigmoid(info)
    assert Q_READ[n].lower <= q.lower <= q.upper <= Q_READ[n].upper
    assert U < q.lower


def test_T07_saturated_root_is_supported_but_its_coarse_bounds_straddle_14_over_25():
    q = sigmoid(information_ruler(3))
    assert F(1, 2) < q.lower < U < q.upper


@pytest.mark.parametrize("n", range(4))
def test_T07_T08_public_C1_joint_information_selects_without_display(n):
    world = c1_world(n)
    view, resolved = evaluation_root(world)
    before = world.ledger.entries()
    assert (resolved.items, resolved.H_ns, resolved.gamma) == ((), None, 1.0)
    scope = rate_entry.certify_rate_scope(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert scope.status == "certified" and scope.reason is None
    actual = rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert actual.candidates == CANDIDATES
    assert actual.cumulative[0] == ZERO and actual.cumulative[-1] == ONE
    ruler = information_ruler(n)
    info = actual.information[0]
    assert info.status == "finite" and info.support == "positive"
    # Permit independent outward rounding by one standard budget unit.
    # A bound that deletes C (I_p only), adds arbitrary label entropy, or
    # returns the entire real line cannot satisfy these bounds.
    slack = STANDARD_BUDGET.tolerance
    assert ruler.lower-slack <= info.bounds.lower <= info.bounds.upper <= ruler.upper+slack
    for cost in actual.expected_cost:
        assert (cost.status, cost.support, cost.bounds) == ("finite", "zero", ZERO)
    wait = actual.information[1]
    assert (wait.status, wait.support, wait.bounds) == ("finite", "zero", ZERO)
    for field in (actual.G, actual.J):
        assert field[0].bounds == rate.RationalInterval(-info.bounds.upper, -info.bounds.lower)
        assert (field[1].status, field[1].support, field[1].bounds) == ("finite", "zero", ZERO)
    q = actual.q_star[0]
    q_ruler = sigmoid(ruler)
    assert q.status == "finite" and q.support == "positive"
    assert q_ruler.lower-slack <= q.bounds.lower <= q.bounds.upper <= q_ruler.upper+slack
    other = actual.q_star[1]
    assert other.status == "finite" and other.support == "positive"
    # Separate outward calculations may tighten either complement endpoint;
    # they must admit the same normalized distribution, not identical widths.
    assert other.bounds.lower <= 1-q.bounds.lower
    assert 1-q.bounds.upper <= other.bounds.upper
    assert 1-q_ruler.upper-slack <= other.bounds.lower <= other.bounds.upper <= 1-q_ruler.lower+slack
    assert actual.cumulative[1].lower >= q.bounds.lower
    assert actual.cumulative[1].upper <= q.bounds.upper
    # RateEvaluation has no required display field. Selection receives only
    # its certified quantities, and must not demand a Draft/float vector.
    assert_selected(actual, U if n < 3 else F(1, 2), 0)
    assert world.ledger.entries() == before


@pytest.mark.parametrize("n", range(3))
def test_T08_M11_dropping_arrivals_changes_same_u_to_wait(n):
    lp, hp = _log_bounds(F(2))
    p_only = outward(lp-F(1, 2), hp-F(1, 2))
    wrong_q = sigmoid(p_only)
    assert Q_WITHOUT_ARRIVALS.lower <= wrong_q.lower <= wrong_q.upper <= Q_WITHOUT_ARRIVALS.upper
    assert wrong_q.upper < U < sigmoid(information_ruler(n)).lower
    # This is the arrival-deleted mathematical ruler, not a counterfeit
    # Certificate for the real C1 model. Its cumulative inequalities select
    # wait. The actual model, checked independently above, must select read.
    assert wrong_q.upper <= U < 1
    view, resolved = evaluation_root(c1_world(n))
    actual = rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert_selected(actual, U, 0)


@pytest.mark.parametrize("n", range(3))
def test_T08_M14_refinement_corrects_the_initial_midpoint_choice(n, s4b2_independent_information):
    view, resolved = evaluation_root(c1_world(n))
    evaluation = rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    info = evaluation.information[0].bounds
    q = evaluation.q_star[0].bounds
    u = F(13, 20)
    assert s4b2_independent_information[n][1][1] < u
    if q.lower < u < q.upper:
        # On the initial coarse envelope a midpoint J says read. A proved
        # refinement may (and must) select wait; a straddle alone is no longer
        # a reason to require RateIncomplete now that refinement is available.
        midpoint = (info.lower+info.upper)/2
        assert u < sigmoid(rate.RationalInterval(midpoint, midpoint)).lower
    assert_selected(evaluation, u, 1)


@pytest.mark.parametrize("u,index", [(F(0), 0), (F(1, 2)-F(1, 10**60), 0),
    (F(1, 2), 1), (F(1, 2)+F(1, 10**60), 1), (1-F(1, 10**60), 1)])
def test_T09_M15_M16_M26_exact_boundary_and_sub_float_neighbours(u, index):
    assert_selected(boundary_evaluation(), u, index)


@pytest.mark.parametrize("u", [F(49, 100), F(1, 2), F(1, 2)+F(1, 10**60)])
def test_T09_M17_straddling_boundary_never_falls_through_to_last(u):
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(boundary_evaluation(uncertain=True), u=u)
    assert caught.value.reason == "selection_boundary"


def test_T09_half_open_interval_allows_equality_only_at_previous_upper():
    assert_selected(boundary_evaluation(uncertain=True), F(51, 100), 1)


@pytest.mark.parametrize("u", [True, False, 1, F(1), -1, F(-1, 10**60),
    F(11, 10), float("nan"), float("inf"), -float("inf"), -0.01, 1.0, "0.56", None])
def test_T09_invalid_u_type_and_range_are_not_rounded_or_redrawn(u):
    with pytest.raises(rate.RateInputError) as caught:
        rate.certify_choice(boundary_evaluation(), u=u)
    assert caught.value.reason == "invalid_u"


def test_T09_M26_float_is_its_exact_binary_rational_not_decimal_14_over_25():
    decimal, binary = F(14, 25), F.from_float(0.56)
    assert decimal < binary
    # A rational threshold between these values would distinguish the hands.
    edge = (decimal+binary)/2
    assert decimal < edge < binary
    # Use a genuine evaluation for the public representation contract.
    # The three C1 roots intentionally select read for both nearby inputs.
    view, resolved = evaluation_root(c1_world())
    evaluation = rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert_selected(evaluation, decimal, 0)
    chosen = assert_selected(evaluation, 0.56, 0)
    assert chosen.u == F(*0.56.as_integer_ratio()) != decimal


@pytest.mark.parametrize("value", [0.0, -0.0, 0.5])
def test_T09_valid_float_endpoints_retain_binary_value(value):
    assert_selected(boundary_evaluation(), value, int(value == 0.5))


def test_T10_M26_small_positive_probability_survives_float_rounding_of_cumulative():
    view, resolved = evaluation_root(c1_world())
    actual = rate.evaluate_rate(view, CANDIDATES, replace(resolved, gamma=16.0),
                                budget=STANDARD_BUDGET)
    tiny = actual.q_star[1]
    assert (tiny.status, tiny.support) == ("finite", "positive")
    assert 0 < tiny.bounds.lower <= tiny.bounds.upper < F(1, 50)
    u = 1-F(1, 10**60)
    assert 1-u < tiny.bounds.lower
    assert u < 1 and float(u) == 1.0
    assert_selected(actual, u, 1)


def test_T10_M22_lower_zero_does_not_prove_structural_zero():
    assert_selected(boundary_evaluation(), F(0), 0)
    evaluation = probability_evaluation(rate.RationalInterval(F(0), F(1, 10**100)))
    unproved = replace(evaluation.q_star[0], status="uncertified", support="unproved",
                       reason="evidence_lower_bound")
    evaluation = replace(evaluation, q_star=(unproved, evaluation.q_star[1]))
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(evaluation, u=F(0))
    assert caught.value.reason in {"evidence_lower_bound", "proof_unavailable"}


@pytest.mark.parametrize("field", ["expected_cost", "information", "G", "J", "q_star"])
@pytest.mark.parametrize("index", [0, 1])
def test_T10_M23_any_uncertified_candidate_blocks_even_an_apparently_certain_choice(field, index):
    evaluation = boundary_evaluation()
    assert_selected(evaluation, F(0), 0)
    values = list(getattr(evaluation, field))
    values[index] = rate.CertifiedQuantity("uncertified", None, "unproved", None, "budget", None)
    evaluation = replace(evaluation, **{field: tuple(values)})
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(evaluation, u=F(0))
    assert caught.value.reason in {"budget", "proof_unavailable"}


def test_T10_proved_infinity_is_forbidden_and_all_forbidden_is_separate():
    infinite = rate.CertifiedQuantity("positive_infinity", None, "positive", None, None, None)
    evaluation = probability_evaluation(ZERO)
    zero = finite(ZERO, support="zero")
    evaluation = replace(evaluation, expected_cost=(infinite, zero), G=(infinite, zero),
        J=(infinite, zero), q_star=(zero, finite(ONE, support="positive")))
    assert_selected(evaluation, F(0), 1)
    assert_selected(evaluation, 1-F(1, 10**100), 1)
    forbidden = replace(evaluation, expected_cost=(infinite, infinite), G=(infinite, infinite),
                        J=(infinite, infinite), q_star=(zero, zero), cumulative=(ZERO, ZERO, ZERO))
    with pytest.raises(rate.RateNoAdmissibleCandidate) as caught:
        rate.certify_choice(forbidden, u=F(0))
    assert caught.value.reason == "all_forbidden"


def test_T10_M23_uncertified_with_forbidden_is_not_all_forbidden():
    evaluation = boundary_evaluation()
    infinite = rate.CertifiedQuantity("positive_infinity", None, "positive", None, None, None)
    unknown = rate.CertifiedQuantity("uncertified", None, "unproved", None, "proof_unavailable", None)
    evaluation = replace(evaluation, J=(infinite, unknown))
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(evaluation, u=F(0))
    assert caught.value.reason == "proof_unavailable"


def finite_mutual_information(cells, target, report):
    """Exact finite joint masses -> MI with the same proved log remainder."""
    tx, ry = {}, {}
    for outcome, mass in cells:
        tx[target(outcome)] = tx.get(target(outcome), F(0))+mass
        ry[report(outcome)] = ry.get(report(outcome), F(0))+mass
    joint = {}
    for outcome, mass in cells:
        key = target(outcome), report(outcome)
        joint[key] = joint.get(key, F(0))+mass
    lo = hi = F(0)
    for (x, y), mass in joint.items():
        if mass:
            lower, upper = _log_bounds(mass/(tx[x]*ry[y]))
            lo += mass*lower
            hi += mass*upper
    return outward(lo, hi)


def test_T07_M12_joint_information_is_not_sum_of_marginal_information():
    # §3-4: p~Uniform[0,1], S|p~Bernoulli(p), Y=S. E[H(S|p)]=1/2.
    lp, hp = _log_bounds(F(2))
    joint = outward(lp, hp)
    wrong = outward(2*lp-F(1, 2), 2*hp-F(1, 2))
    assert joint.upper < wrong.lower
    # Also a finite dependent example; changing target axes changes MI.
    cells = (((0, 0, 0), F(1, 2)), ((1, 1, 1), F(1, 2)))
    total = finite_mutual_information(cells, lambda row: row[:2], lambda row: row[2])
    marginals = [finite_mutual_information(cells, lambda row, j=j: row[j],
                                         lambda row: row[2]) for j in (0, 1)]
    assert total == joint
    assert total.upper < sum(x.lower for x in marginals)


def test_T07_M13_auxiliary_component_index_is_not_a_target_or_an_observation():
    # X is fixed. Two computational labels partition Y; labels are not laws.
    cells = (((0, 0, 0), F(1, 2)), ((0, 1, 1), F(1, 2)))
    correct = finite_mutual_information(cells, lambda row: row[0], lambda row: row[2])
    added_label = finite_mutual_information(cells, lambda row: row[:2], lambda row: row[2])
    constant_wait = finite_mutual_information(cells, lambda row: row[:2], lambda row: "done")
    assert correct == constant_wait == ZERO
    assert added_label.lower > 0


@pytest.mark.parametrize("factory,reason", [(four_rate_declaration, "rate_prior_scope"),
    (independent_arrival_declaration, "rate_prior_scope"), (tick_declaration, "latent_clock")])
def test_T13_public_scope_and_evaluation_preserve_unsupported_experiment(factory, reason):
    world = c1_world(declaration=factory())
    view, resolved = evaluation_root(world)
    before = world.ledger.entries()
    scope = rate_entry.certify_rate_scope(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert (scope.status, scope.reason) == ("incomplete", reason)
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert caught.value.reason == reason
    assert world.ledger.entries() == before


def test_T13_depth_scope_does_not_silently_shorten_horizon():
    view, resolved = evaluation_root(c1_world())
    accepted = replace(resolved, H_ns=NS)
    assert rate_entry.certify_rate_scope(view, CANDIDATES, accepted,
                                        budget=STANDARD_BUDGET).status == "certified"
    too_deep = replace(resolved, H_ns=2*NS)
    scope = rate_entry.certify_rate_scope(view, CANDIDATES, too_deep, budget=STANDARD_BUDGET)
    assert (scope.status, scope.reason) == ("incomplete", "depth_scope")
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.evaluate_rate(view, CANDIDATES, too_deep, budget=STANDARD_BUDGET)
    assert caught.value.reason == "depth_scope"


@pytest.mark.parametrize("candidates,expected", [(("wait", "read", "read"), CANDIDATES),
    (("read",), ("read",)), (("wait",), ("wait",))])
def test_T13_candidate_set_is_canonicalized_without_dropping_valid_members(candidates, expected):
    view, resolved = evaluation_root(c1_world())
    actual = rate.evaluate_rate(view, candidates, resolved, budget=STANDARD_BUDGET)
    assert actual.candidates == expected
    if len(expected) == 1:
        assert actual.q_star[0].bounds == ONE
        assert actual.cumulative == (ZERO, ONE)
        assert_selected(actual, 1-F(1, 10**60), 0)


@pytest.mark.parametrize("candidates", [(), ("unknown",), ("read", "unknown")])
def test_T13_empty_partial_and_wholly_unknown_candidates_are_rejected(candidates):
    view, resolved = evaluation_root(c1_world())
    with pytest.raises(rate.RateInputError) as caught:
        rate.evaluate_rate(view, candidates, resolved, budget=STANDARD_BUDGET)
    assert caught.value.reason == "unknown_candidate"


def test_T07_M25_certificate_trace_is_deterministic_and_records_rational_residuals():
    def run():
        view, resolved = evaluation_root(c1_world(2))
        return rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    first, second = run(), run()
    assert first == second
    cert = first.certificate
    assert cert.problem_key and cert.budget == STANDARD_BUDGET
    assert cert.method == ContractRef("sui.s4b.rate_c1", "1")
    assert cert.arithmetic == ContractRef("rational-series", "1")
    assert cert.trace and cert.enclosures and cert.residuals
    assert isinstance(cert.trace, tuple) and isinstance(cert.residuals, tuple)
    operations = set()
    for index, step in enumerate(cert.trace):
        assert set(step) == {"index", "operation", "cell", "dimension", "terms", "cutoff"}
        assert step["index"] == index
        assert step["operation"] in {"analytic", "series", "tail", "split", "aggregate", "select"}
        operations.add(step["operation"])
        if step["terms"] is not None:
            assert type(step["terms"]) is int and step["terms"] > 0
        if step["cutoff"] is not None:
            assert F(*step["cutoff"]) >= 0
    assert "analytic" in operations and "series" in operations
    sources = set()
    for residual in cert.residuals:
        assert set(residual) == {"quantity", "candidate", "source", "upper"}
        assert residual["quantity"]
        assert residual["candidate"] is None or residual["candidate"] in CANDIDATES
        source = residual["source"]
        assert source in {"series", "tail", "quadrature", "conditioning", "information", "rounding"}
        sources.add(source)
        upper = F(*residual["upper"])
        assert upper >= 0
        if source == "rounding":
            assert upper == 0
    assert "series" in sources
    assert_selected(first, U, 0)
    assert_selected(second, U, 0)


@pytest.mark.parametrize("changed", ["overlapping_interval", "information", "trace", "residual"])
def test_T07_certificate_recomputation_rejects_forged_enclosures_and_trace(changed):
    view, resolved = evaluation_root(c1_world())
    original = rate.evaluate_rate(view, CANDIDATES, resolved, budget=STANDARD_BUDGET)
    assert_selected(original, U, 0)
    forged = original
    if changed == "overlapping_interval":
        # A point inside the original interval is not a proof of that point.
        bounds = original.q_star[0].bounds
        midpoint = (bounds.lower+bounds.upper)/2
        point = rate.RationalInterval(midpoint, midpoint)
        assert original.q_star[0].bounds.lower < point.lower < original.q_star[0].bounds.upper
        forged = replace(original,
            q_star=(replace(original.q_star[0], bounds=point),
                    replace(original.q_star[1], bounds=rate.RationalInterval(1-midpoint, 1-midpoint))),
            cumulative=(ZERO, point, ONE))
    elif changed == "information":
        bounds = original.information[0].bounds
        midpoint = (bounds.lower+bounds.upper)/2
        point = rate.RationalInterval(midpoint, midpoint)
        assert original.information[0].bounds.lower < point.lower < original.information[0].bounds.upper
        forged = replace(original, information=(replace(original.information[0], bounds=point),
                                                original.information[1]))
    elif changed == "trace":
        steps = [dict(step) for step in original.certificate.trace]
        series = next(step for step in steps if step["operation"] == "series")
        series["terms"] += 1
        forged = replace(original, certificate=replace(original.certificate, trace=tuple(steps)))
    else:
        residuals = [dict(item) for item in original.certificate.residuals]
        positive = next(item for item in residuals if F(*item["upper"]) > 0)
        positive["upper"] = (0, 1)
        forged = replace(original, certificate=replace(original.certificate, residuals=tuple(residuals)))
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(forged, u=U)
    assert caught.value.reason == "proof_unavailable"
    # Rejecting the forgery must not invalidate the original immutable value.
    assert_selected(original, U, 0)
