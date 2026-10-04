"""Independent one-jump ruler fixtures; expectations do not call the new kernel.

The oracle integrates exponential jump time T, rather than report time R.
Fixed references come from tools/s4b1c_fixed_values.py / spec v0.24 §6-2.
"""

from dataclasses import replace
from fractions import Fraction as F
import math

import pytest
from scipy.integrate import quad

from sui.inference import ModelViolation, NumericalRange
from sui.joint import NameSpec
from sui.joint_stage2 import (ExactCompletion, NoCompletion, OneJumpKernel,
                             OneJumpModel, branches, condition, information)
from sui.progress import (CompletionSpec, INFINITE_WORK, ProgressSegment,
                          completion_kernel)
from sui.quantity import IntegrationIncomplete
from sui.values import MeasureSpec


def _spec(pairs, weights, *, unit="work", time="second"):
    return CompletionSpec(name="progress", version="1", actions=("a",), states=("0", "1"),
                          work_unit=unit, time_unit=time, speed_unit=f"{unit}/{time}",
                          candidates=tuple((tuple(p),) for p in pairs), weights=tuple(weights),
                          share="all_actions", max_speed=max(c for p in pairs for c in p))


def _model(pairs=((1, 1), (1, 2)), weights=(F(1, 2), F(1, 2)), *, work=1, q=math.log(2)):
    return OneJumpModel(completion=_spec(pairs, weights), q=q, work=work,
                        measure=MeasureSpec("exact", "1", {}),
                        names=NameSpec(((1,), (1,)), False, "report"),
                        initial_state="0", pending=(), max_reports=1)


def _oracle_parts(pairs, weights, w, q, r, *, atom):
    """Direct Bayes sum, deliberately separate from all new code."""
    joint = {}
    for i, ((c0, c1), p) in enumerate(zip(pairs, weights)):
        t0, t1 = F(w)/c0, F(w)/c1
        if atom:
            likelihood = (math.exp(-q*float(t0)), -math.expm1(-q*float(t0)) if c0 == c1 else 0) if r == t0 else (0, 0)
        elif c0 != c1 and min(t0, t1) < r < max(t0, t1):
            slope = 1 - F(c0)/c1
            likelihood = (0, q*math.exp(-q*float((r-t1)/slope))/abs(float(slope)))
        else:
            likelihood = (0, 0)
        for s, k in enumerate(likelihood):
            joint[i, s] = float(p)*k
    mass = sum(joint.values())
    posterior = {key: value/mass for key, value in joint.items()}
    speed = [posterior[i, 0] + posterior[i, 1] for i in range(len(pairs))]
    law = sum(p*math.log(p/float(prior)) for p, prior in zip(speed, weights) if p)
    root = (math.exp(-q*float(r)), -math.expm1(-q*float(r)))
    state = sum(p*math.log(p/(speed[i]*root[s])) for (i, s), p in posterior.items() if p)
    return mass, law, state, posterior


def _oracle_information(pairs, weights, w, q, h):
    """Sum atoms + integrate T + separately condition R>H; scipy only in oracle."""
    law, state = 0.0, 0.0
    for r in sorted({F(w)/p[0] for p in pairs if F(w)/p[0] <= h}):
        mass, bl, bs, _ = _oracle_parts(pairs, weights, w, q, r, atom=True)
        law += mass*bl
        state += mass*bs
    misses = []
    report_cuts = {F(w)/c for pair in pairs for c in pair} | {F(h)}
    for (c0, c1), p in zip(pairs, weights):
        t0, t1, slope = F(w)/c0, F(w)/c1, 1-F(c0)/c1
        if not slope:
            misses.append(float(p) if t0 > h else 0.0)
            continue
        cuts = sorted({F(0), t0} | {t for r in report_cuts if 0 < (t := (r-t1)/slope) < t0})
        seen = 0.0
        for a, b in zip(cuts, cuts[1:]):
            if t1 + slope*(a+b)/2 > h:
                continue
            seen += math.exp(-q*float(a)) - math.exp(-q*float(b))
            def integrand(t, part):
                r = float(t1) + float(slope)*t
                return float(p)*q*math.exp(-q*t)*_oracle_parts(pairs, weights, w, q, r, atom=False)[part]
            law += quad(integrand, float(a), float(b), args=(1,), epsabs=2e-13, epsrel=2e-13)[0]
            state += quad(integrand, float(a), float(b), args=(2,), epsabs=2e-13, epsrel=2e-13)[0]
        atom_seen = math.exp(-q*float(t0)) if t0 <= h else 0.0
        misses.append(float(p)*max(0.0, 1-seen-atom_seen))
    pmiss = sum(misses)
    bmiss = sum(v/pmiss*math.log(v/(pmiss*float(p))) for v, p in zip(misses, weights) if v) if pmiss else 0
    return law + pmiss*bmiss, state, pmiss, bmiss


def _contains(interval, expected, *, roundoff=3e-15):
    # InformationBounds excludes floating roundoff. This separate allowance is
    # for arithmetic/independent oracle roundoff, not quadrature truncation.
    assert interval.lower-roundoff <= expected <= interval.upper+roundoff


@pytest.mark.parametrize("speeds,atom_mass,continuous", [
    ((1, 2), .5, .5),
    ((2, 1), .7071067811865476, .2928932188134524),
    ((1, 1), 1., 0.),
])
def test_kernel_atoms_density_and_normalization(speeds, atom_mass, continuous):
    # Drops missing/negative Jacobian, merging atom with density, or lost mass.
    k = OneJumpKernel(q=math.log(2), work=1, speeds=speeds)
    window = k.window(1)
    assert math.exp(window.atoms[0].log_mass) == pytest.approx(atom_mass, abs=2e-15)
    assert window.continuous_mass == pytest.approx(continuous, abs=2e-15)
    assert window.not_arrived_mass == 0
    assert window.mass == pytest.approx(1, abs=2e-15)
    if speeds[0] != speeds[1]:
        direct = quad(k.density, .5, 1, epsabs=1e-13)[0]
        assert direct == pytest.approx(continuous, abs=2e-14)
        assert k.density(F(3, 4)) == pytest.approx(math.log(2)*math.sqrt(2) if speeds == (1, 2)
                                                    else math.log(2)*2**(-.25), abs=2e-15)
    else:
        assert window.atoms[0].state_mass == pytest.approx((.5, .5), abs=2e-15)
        assert k.density(1) == 0


def test_equal_speed_completion_keeps_both_states_and_has_zero_information():
    # A deterministic completion time does not fix S_R=0 or reveal jump time.
    m = _model(((1, 1),), (F(1),))
    child = condition(m, ExactCompletion(1))
    assert child.target_marginal() == pytest.approx({((F(1), F(1)), 0): .5,
                                                   ((F(1), F(1)), 1): .5})
    assert child.root_potential().total == pytest.approx(0, abs=2e-15)
    result = information(m, 1, tolerance=1e-12, node_budget=0)
    _contains(result.total, 0)
    assert result.nodes == result.pieces == 0


def test_correlated_speed_state_posterior_drops_independent_one_ninth():
    m = _model()
    child = condition(m, ExactCompletion(1))
    joint = child.target_marginal()
    assert tuple(joint.values()) == pytest.approx((1/3, 1/3, 1/3, 0), abs=2e-15)
    wrong = child.speed_marginal()[m.pairs[1]] * sum(v for (_, s), v in joint.items() if s == 1)
    assert wrong == pytest.approx(1/9)
    assert joint[m.pairs[1], 1] == 0
    _, laws, state, _ = _oracle_parts(((1, 1), (1, 2)), (F(1, 2), F(1, 2)), 1,
                                      math.log(2), F(1), atom=True)
    assert child.root_potential().laws == pytest.approx(laws, abs=2e-15)
    assert child.root_potential().state == pytest.approx(state, abs=2e-15)


def test_atom_inside_other_support_never_adds_continuous_density():
    # R=.75 is an atom of (4/3,4/3), inside the support of (1,2).
    m = _model(((F(4, 3), F(4, 3)), (1, 2)), (F(1, 2), F(1, 2)))
    child = condition(m, ExactCompletion(F(3, 4)))
    assert child.basis == "atom"
    assert math.exp(child.log_evidence) == pytest.approx(.5, abs=2e-15)
    assert child.speed_marginal()[m.pairs[1]] == 0
    assert child.root_potential().laws == pytest.approx(math.log(2), abs=2e-15)
    assert child.root_potential().state == pytest.approx(0, abs=2e-15)
    tree = branches(m, 1)
    assert [a.time_s for a in tree.atoms] == [F(3, 4), F(1)]
    assert [(p.lower_s, p.upper_s) for p in tree.continuous] == [(F(1, 2), F(3, 4)), (F(3, 4), F(1))]
    assert tree.normalization == pytest.approx(1, abs=2e-15)
    assert tree.normalization_bounds.lower == tree.normalization_bounds.upper == F(1)


def test_density_potential_uses_same_report_time_root_forecast():
    # Root state 1 probability at R=.75, not at T=.5, H=1, or start=0.
    m = _model()
    child = condition(m, ExactCompletion(F(3, 4)))
    assert child.basis == "density"
    assert child.target_marginal()[m.pairs[1], 1] == pytest.approx(1)
    expected_state = -math.log(1-2**(-.75))
    assert child.root_potential().state == pytest.approx(expected_state, abs=2e-15)
    assert child.root_potential().laws == pytest.approx(math.log(2), abs=2e-15)
    assert abs(expected_state-math.log(2)) > .2


def test_not_arrived_law_information_fixed_values_and_no_state_target():
    m = _model()
    child = condition(m, NoCompletion(F(3, 4)))
    assert math.exp(child.log_evidence) == pytest.approx(.8535533905932737, abs=2e-15)
    assert child.speed_marginal()[m.pairs[1]] == pytest.approx(.4142135623730951, abs=2e-15)
    # Exact independent formula; the fixed script prints only ten decimals.
    r = math.sqrt(2)-1
    expected_b = r*math.log(2*r) + (1-r)*math.log(2*(1-r))
    assert expected_b == pytest.approx(.0147917024, abs=5e-11)
    assert child.root_potential().laws == pytest.approx(expected_b, abs=3e-15)
    assert child.root_potential().state == 0
    assert all(s is None for _, s in child.target_marginal())
    result = information(m, F(3, 4), tolerance=1e-10, node_budget=20000)
    expected_weighted = (.5+.5*2**(-.5))*expected_b
    assert expected_weighted == pytest.approx(.0126255077, abs=5e-11)
    assert result.not_arrived_probability*result.not_arrived_potential == pytest.approx(expected_weighted, abs=3e-15)
    law, state, _, _ = _oracle_information(((1, 1), (1, 2)), (F(1, 2), F(1, 2)), 1,
                                          math.log(2), F(3, 4))
    _contains(result.laws, law)
    _contains(result.state, state)
    assert result.laws.lower > .1  # Missing nonarrival's law term misses the oracle.


def test_nonarrival_filters_state_but_adds_no_state_reward():
    m = _model(((1, 2),), (F(1),))
    child = condition(m, NoCompletion(F(3, 4)))
    state = child.current_state_given_nonarrival()
    assert state[1] == pytest.approx(.1591035847462855, abs=2e-15)
    wrong_name_only = 1-2**(-.75)
    assert wrong_name_only == pytest.approx(.4053964424986395)
    assert abs(state[1]-wrong_name_only) > .2
    assert child.root_potential().total == 0


@pytest.mark.parametrize("speeds,h,miss,state1", [
    ((1, 2), F(1, 4), 1., 1-2**(-.25)),
    ((1, 2), F(1, 2), 1., 1-2**(-.5)),
    ((1, 2), F(3, 4), 2**(-.5), 1-2**(-.25)),
    ((2, 1), F(1, 2), 1-2**(-.5), 1.),
    ((2, 1), F(3, 4), 1-2**(-.25), 1.),
    ((1, 1), F(3, 4), 1., 1-2**(-.75)),
])
def test_nonarrival_both_slopes_and_closed_deadline(speeds, h, miss, state1):
    k = OneJumpKernel(q=math.log(2), work=1, speeds=speeds)
    assert k.window(h).mass == pytest.approx(1, abs=2e-15)
    assert k.window(h).not_arrived_mass == pytest.approx(miss, abs=2e-15)
    child = condition(_model((speeds,), (F(1),)), NoCompletion(h))
    assert child.current_state_given_nonarrival()[1] == pytest.approx(state1, abs=2e-15)
    assert k.window(1).not_arrived_mass == 0


def test_fixed_total_information_series_and_choice_bounds():
    # Independent positive series, whose certified tail is from the spec.
    g80 = .5*math.log(2) + math.fsum(2/(n*(n+2))*(2**(-n/2)-2**(-n-1)) for n in range(1, 81))
    tail = 2**(-81/2)/(2*81*(1-2**(-.5)))
    result = information(_model(), 1, tolerance=1e-11, node_budget=30000)
    law = .2157615543388357
    _contains(result.laws, law)
    _contains(result.state, .5*g80)
    _contains(result.state, .5*(g80+tail))
    _contains(result.total, .6270419274355707)
    assert result.total.upper-result.total.lower <= 1e-11
    # Reference q for a vs zero information / zero cost; no public planner.
    logistic = lambda x: 1/(1+math.exp(-x))
    assert logistic(result.total.lower)-3e-15 <= .6518184260214424 <= logistic(result.total.upper)+3e-15
    assert logistic(result.total.midpoint) == pytest.approx(.6518184260214424, abs=1e-12)
    assert result.nodes > 0
    assert result.pieces == 1


@pytest.mark.parametrize("h", [F(2, 5), F(4, 5), F(2)])
def test_arbitrary_speed_mixture_matches_direct_jump_time_integral(h):
    # Several overlapping supports, reverse slope, same-speed atom, unequal priors.
    pairs, weights = ((1, 3), (2, 1), (F(4, 3), F(4, 3))), (F(1, 5), F(1, 2), F(3, 10))
    q = .9
    result = information(_model(pairs, weights, q=q), h, tolerance=2e-9, node_budget=60000)
    law, state, pmiss, bmiss = _oracle_information(pairs, weights, 1, q, h)
    _contains(result.laws, law, roundoff=2e-14)
    _contains(result.state, state, roundoff=2e-14)
    _contains(result.total, law+state, roundoff=2e-14)
    assert result.total.upper-result.total.lower <= 2e-9
    assert result.not_arrived_probability == pytest.approx(pmiss, abs=3e-15)
    assert result.not_arrived_potential == pytest.approx(bmiss, abs=3e-15)
    assert result.normalization == pytest.approx(1, abs=3e-15)


def test_duplicate_speed_labels_and_work_speed_scaling_are_invariant():
    # Clone labels are marginalized; simultaneous (w,c)->(3w,3c) preserves time.
    original = _model()
    duplicate = _model(((1, 1), (1, 2), (1, 2)), (F(1, 2), F(1, 6), F(1, 3)))
    scaled = _model(((3, 3), (3, 6)), (F(1, 2), F(1, 2)), work=3)
    assert duplicate.pairs == original.pairs
    for obs in (ExactCompletion(1), ExactCompletion(F(3, 4)), NoCompletion(F(3, 4))):
        assert condition(duplicate, obs).target_marginal() == condition(original, obs).target_marginal()
        assert condition(scaled, obs).root_potential().total == pytest.approx(condition(original, obs).root_potential().total, abs=2e-15)
    results = [information(m, 1, tolerance=1e-9, node_budget=10000) for m in (original, duplicate, scaled)]
    assert results[0] == results[1] == results[2]


def test_zero_horizon_and_impossible_report_or_nonarrival():
    m = _model()
    result = information(m, 0, tolerance=1e-12, node_budget=0)
    assert result.total.lower == result.total.upper == 0
    assert result.not_arrived_probability == 1
    assert result.normalization == 1
    for obs in (ExactCompletion(0), ExactCompletion(2), NoCompletion(1)):
        with pytest.raises(ModelViolation, match="structural zero"):
            condition(m, obs)


@pytest.mark.parametrize("changes", [
    {"initial_state": "1"}, {"pending": ("ongoing",)}, {"max_reports": 2},
    {"q": 0}, {"work": 0}, {"work": INFINITE_WORK},
    {"measure": MeasureSpec("tick", "1", {})},
    {"names": NameSpec(((1,), (1,)), True, "report")},
    {"names": NameSpec(((1, 0), (0, 1)), False, "report")},
    {"completion": _spec(((0, 1),), (F(1),))},
    {"completion": _spec(((1, 2),), (F(1),), time="ns")},
])
def test_out_of_scope_never_silently_approximates(changes):
    with pytest.raises(IntegrationIncomplete):
        replace(_model(), **changes)


@pytest.mark.parametrize("changes", [
    {"q": 0}, {"work": 0}, {"work": INFINITE_WORK},
    {"speeds": (0, 1)}, {"speeds": (1, 2, 3)},
])
def test_direct_kernel_also_stops_outside_certified_scope(changes):
    # The kernel's direct entry must stop too, not just OneJumpModel's guard.
    params = {"q": math.log(2), "work": 1, "speeds": (1, 2)} | changes
    with pytest.raises(IntegrationIncomplete):
        OneJumpKernel(**params)


def test_quadrature_budget_failure_is_not_zero_information():
    with pytest.raises(IntegrationIncomplete, match="budget"):
        information(_model(), 1, tolerance=1e-12, node_budget=4)
    with pytest.raises(IntegrationIncomplete, match="observation"):
        condition(_model(), [ExactCompletion(1), NoCompletion(1)])


def test_small_positive_mass_is_logged_or_explicitly_outside_numeric_range():
    k = OneJumpKernel(q=1000., work=1, speeds=(1, 2))
    assert k.atom().log_state_mass[0] == -1000.
    assert k.log_density(F(999, 1000)) != -math.inf
    with pytest.raises(NumericalRange, match="positive mass"):
        _ = k.atom().state_mass
    # A tiny but representable prior remains a positive posterior branch.
    m = _model(((1, 1), (1, 2)), (F(1)-F(1, 10**250), F(1, 10**250)))
    child = condition(m, ExactCompletion(1))
    assert child.log_joint[m.pairs[1], 0] != -math.inf
    assert child.target_marginal()[m.pairs[1], 0] > 0


def test_finite_work_permanently_unreachable_is_distinct_from_infinite_work():
    # This is the existing general path kernel, outside the positive-speed ruler.
    spec = _spec(((0, 0),), (F(1),))
    path = (ProgressSegment(F(1), "0"), ProgressSegment(None, "1"))
    kernel = completion_kernel(spec, "a", 0, path,
                               atoms=((F(1), F(2, 3)), (INFINITE_WORK, F(1, 3))))
    assert kernel.unreachable_work_mass == F(2, 3)
    assert kernel.infinite_work_mass == F(1, 3)
    assert kernel.atoms == kernel.densities == ()
    assert kernel.mass == 1
