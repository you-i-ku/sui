"""Stage-1 recursion: independent fixed formulas and full terminal enumeration.

The bridge B oracle below uses elementary path probabilities / Polya updates,
not sui's posterior, branches, root potential, or recursive evaluator.
"""

from dataclasses import replace
from fractions import Fraction as F
from itertools import product
import math

import numpy as np
import pytest
from scipy.special import betaln, digamma

from sui.inference import NumericalRange
from sui.joint import Attempt, Completed, JointBelief, JointModel, NameSpec, NotArrived, WorkPrior
from sui.joint_lookahead import (Context, Interval, branches, evaluate,
                                  one_step_components, policy_bounds, _mix_policy, ActionValue)
from sui.lookahead import NoAdmissibleCandidate, _policy
from sui.progress import CompletionSpec, INFINITE_WORK
from sui.quantity import IntegrationIncomplete
from sui.values import InformationBounds, MeasureSpec


NS = 1_000_000_000
ROUND = 3e-14  # Floating arithmetic, separate from certified truncation error.


def _spec(actions, states):
    return CompletionSpec(name="progress", version="1", actions=actions, states=states,
                          work_unit="ns", time_unit="ns", speed_unit="ns/ns",
                          candidates=(tuple(tuple(F(1) for _ in states) for _ in actions),),
                          weights=(F(1),), share="all_actions", max_speed=F(1))


def _bridge(*, names_learned=True, work_beta=(1, 1)):
    rate = math.log(2)
    a, b = map(F, work_beta)
    names = NameSpec(((1, 1), (1, 1)), True, "report") if names_learned else NameSpec(((1, 0), (0, 1)), False, "report")
    return JointModel(completion=_spec(("a", "b"), ("0", "1")),
                      work={"a": WorkPrior(a+b, ((NS, a/(a+b)), (2*NS, b/(a+b)))),
                            "b": WorkPrior(F(3), ((NS, F(1)),))},
                      names={"a": names, "b": NameSpec(((1, 0), (0, 1)), False, "report")},
                      outcomes=("0", "1"), initial=(F(1), F(0)),
                      Q=np.array([[-rate, 0.], [rate, 0.]]),
                      measure=MeasureSpec("exact", "1", {}), w_star_ns=NS)


def _belief(model, *, attempts=(), facts=(), now=0):
    return JointBelief(model=model, attempts=tuple(attempts), facts=tuple(facts),
                       origin_ns=0, observed_ns=now, transition_tolerance=1e-16)


def _eval(root, *, candidates=None, deadline=2*NS, cost=lambda eta: 0., bound=0.,
          gamma=1., u=.5, tolerance=1e-9, node_budget=20000, refinement_budget=5, unread=()):
    return evaluate(root, candidates=root.model.completion.actions if candidates is None else candidates,
                    deadline_ns=deadline, gamma=gamma, u=u, terminal_cost=cost, cost_bound=bound,
                    tolerance=tolerance, series_budget=500, node_budget=node_budget,
                    refinement_budget=refinement_budget, unread=unread)


def _one(root, action, *, deadline=2*NS, cost=lambda eta: 0., bound=0.):
    return one_step_components(root, action, deadline_ns=deadline, terminal_cost=cost,
                               cost_bound=bound, tolerance=1e-9, series_budget=500, node_budget=20000)


def _enclosed(interval, value, rounding=ROUND):
    assert interval.lower-rounding <= value <= interval.upper+rounding


def _kl_beta(a, b, c=1, d=1):
    return float(betaln(c, d)-betaln(a, b)+(a-c)*digamma(a)+(b-d)*digamma(b)
                 +(c+d-a-b)*digamma(a+b))


def _binary_entropy(p):
    return -p*math.log(p)-(1-p)*math.log1p(-p) if 0 < p < 1 else 0.


def _expected_beta_entropy(a, b):
    return float(digamma(a+b+1)-(a*digamma(a+1)+b*digamma(b+1))/(a+b))


@pytest.mark.parametrize("beta,py,chosen", [((3, 1), F(9, 16), "b"), ((1, 3), F(11, 16), "a")])
def test_bridge_a_single_step_cost_information_J_and_q(beta, py, chosen):
    """Drops ignored duration learning, Q=0, lost cost, or argmax instead of softmax."""
    root = _belief(_bridge(names_learned=False, work_beta=beta))
    cost = lambda eta: -math.log(.8 if eta.O[-1][-1] == "1" else .2)
    values = [_one(root, a, cost=cost, bound=-math.log(.2)) for a in ("a", "b")]
    actual_py = sum(c.branch.probability for c in values[0].children if c.branch.E[-1][-1] == "1")
    assert float(actual_py) == pytest.approx(float(py), abs=ROUND)
    p = beta[0]/sum(beta)
    expected_c = -float(py)*math.log(.8)-(1-float(py))*math.log(.2)
    expected_i = _binary_entropy(p)-_expected_beta_entropy(*beta) + p*math.log(2)+(1-p)*_binary_entropy(.75)
    _enclosed(values[0].expected_cost, expected_c)
    _enclosed(values[0].information, expected_i)
    _enclosed(values[0].J_bounds, expected_c-expected_i)
    _enclosed(values[1].J_bounds, -(.5*math.log(.8)+.5*math.log(.2))-math.log(2))
    q = tuple(_policy([v.J for v in values], 1.))
    qb = policy_bounds(tuple(v.J_bounds for v in values), 1.)
    qa = 1/(1+math.exp((expected_c-expected_i)-(-(.5*math.log(.8)+.5*math.log(.2))-math.log(2))))
    _enclosed(qb[0], qa)
    assert q[0] == pytest.approx(qa, abs=1e-12)
    assert ("a" if .55 < q[0] else "b") == chosen
    assert q[0] not in (0, 1)


# A separate bridge B world: explicit Fraction path masses and conjugate updates.
_B_PRIOR = (((0, 0), (1, 1), ((1, 1), (1, 1)), F(1, 4)),
            ((0, 1), (1, 1), ((1, 1), (1, 1)), F(1, 4)),
            ((1, 1), (1, 1), ((1, 1), (1, 1)), F(1, 2)))


def _B_state(path, t):
    return 0 if t == 0 else path[t-1]


def _B_step(belief, action, t):
    groups = {}
    conditional_entropy = 0.
    for path, beta, names, weight in belief:
        if action == "b":
            options = [(1, F(1), beta)]
        else:
            a, b = beta
            options = [(1, F(a, a+b), (a+1, b)), (2, F(b, a+b), (a, b+1))]
            conditional_entropy += float(weight)*_expected_beta_entropy(a, b)
        for duration, p, nbeta in options:
            end = t+duration
            if end > 2:
                reports = [(None, F(1), names)]
                end = None
            elif action == "b":
                reports = [(str(_B_state(path, end)), F(1), names)]
            else:
                s = _B_state(path, end)
                al, be = names[s]
                conditional_entropy += float(weight*p)*_expected_beta_entropy(al, be)
                reports = []
                for y in (0, 1):
                    nn = list(names)
                    nn[s] = (al+y, be+1-y)
                    reports.append((str(y), F(al if y else be, al+be), tuple(nn)))
            for y, py, nn in reports:
                key = (end, y)
                groups.setdefault(key, []).append((path, nbeta, nn, weight*p*py))
    children = []
    for key, rows in groups.items():
        mass = sum(row[3] for row in rows)
        children.append((key, mass, tuple((*row[:3], row[3]/mass) for row in rows)))
    entropy = -sum(float(p)*math.log(float(p)) for _, p, _ in children)
    return entropy-conditional_entropy, children


def _B_V(belief, t):
    if t is None or t >= 2:
        return 0., None
    scores = []
    for action in ("a", "b"):
        info, children = _B_step(belief, action, t)
        scores.append(-info + sum(float(p)*_B_V(b, key[0])[0] for key, p, b in children))
    weights = [math.exp(-j+min(scores)) for j in scores]
    q = tuple(p/sum(weights) for p in weights)
    return sum(p*j for p, j in zip(q, scores)), (scores, q)


def _B_terminal_kl(belief):
    # One Beta product per full state path. These PATH states are in X*,
    # whereas work allocations and latent mixture-component labels are not.
    return sum(float(p)*(math.log(float(p/prior)) + _kl_beta(*beta)
                         + sum(_kl_beta(*n) for n in names))
               for path, beta, names, p in belief
               for original, _, _, prior in _B_PRIOR if original == path)


def _B_direct_total(belief, t, first=None):
    if t is None or t >= 2:
        return _B_terminal_kl(belief)
    q = _B_V(belief, t)[1][1] if first is None else tuple(int(a == first) for a in ("a", "b"))
    return sum(pa*float(p)*_B_direct_total(child, key[0]) for a, pa in zip(("a", "b"), q)
               for key, p, child in _B_step(belief, a, t)[1])


def _actual_terminal_expectation(value):
    def walk(child):
        if not hasattr(child, "actions"):
            return child.potential.midpoint
        return sum(p*_actual_terminal_expectation(a) for p, a in zip(child.q, child.actions) if p)
    return sum(float(c.branch.probability)*walk(c.child) for c in value.children)


def test_bridge_b_root_children_and_all_terminal_total_KL():
    """Drops reset root reference, component bonus, missing F/Theta/Q, or argmax."""
    result = _eval(_belief(_bridge()))
    expected = (-.6004777099601217, -1.0417864504639565)
    _, (direct_J, direct_q) = _B_V(_B_PRIOR, 0)
    for a, score, reference in zip(result.root.actions, expected, direct_J):
        assert reference == pytest.approx(score, abs=2e-14)
        _enclosed(a.J_bounds, reference)
        _enclosed(a.information, _B_direct_total(_B_PRIOR, 0, a.action))
        assert -_actual_terminal_expectation(a) == pytest.approx(a.J, abs=2e-12)
        assert a.J == a.expected_cost.midpoint-a.information.midpoint
    _enclosed(result.root.q_bounds[0], direct_q[0])
    assert result.root.q[0] == pytest.approx(.3914291668110499, abs=2e-12)
    expected_children = {
        ("a", "1"): (-.4283666977, .4211358999),
        ("b", "0"): (-.5315791849, .4004893872),
        ("b", "1"): (-.1656993549, .5719277716),
    }
    for action in result.root.actions:
        for c in action.children:
            if c.branch.t_end != NS:
                continue
            y = c.branch.E[-1][-1]
            key = action.action, y
            if key not in expected_children:
                key = ("a", "1")  # Name symmetry of the initially uniform priors.
            ev, eq = expected_children[key]
            assert c.child.V == pytest.approx(ev, abs=5e-11)
            assert c.child.q[0] == pytest.approx(eq, abs=5e-11)
    assert result.max_depth == 3  # Correct deadline choice; erroneous terminal gives 2.


def test_beta_root_potentials_and_conditional_information_fixed_values():
    model = JointModel(completion=_spec(("coin",), ("s",)),
                       work={"coin": WorkPrior(F(3), ((NS, F(1)),))},
                       names={"coin": NameSpec(((1, 1),), True, "report")}, outcomes=("0", "1"),
                       initial=(F(1),), Q=np.zeros((1, 1)), measure=MeasureSpec("exact", "1", {}), w_star_ns=NS)
    root = _belief(model, attempts=(Attempt("old", "coin", 0),), facts=(Completed("old", NS, "1"),), now=NS)
    actual = _one(root, "coin")
    expected = {"1": .0721317747748311, "0": .2652789553347764}
    for c in actual.children:
        _enclosed(c.child.potential, expected[c.branch.E[-1][-1]])
    _enclosed(actual.increment, .1365141682948128)
    _enclosed(actual.information, _binary_entropy(2/3)-.5)


def _scalar_model(*, deterministic_names=False, points=((NS, F(1)),), actions=("a",), alpha=F(2)):
    column = ((1, 0),) if deterministic_names else ((1, 1),)
    return JointModel(completion=_spec(actions, ("s",)),
                      work={a: WorkPrior(alpha, tuple(points)) for a in actions},
                      names={a: NameSpec(column, not deterministic_names, "report") for a in actions},
                      outcomes=("0", "1"), initial=(F(1),), Q=np.zeros((1, 1)),
                      measure=MeasureSpec("exact", "1", {}), w_star_ns=min(w for w, _ in points if w is not INFINITE_WORK))


def test_latent_work_component_labels_are_not_information():
    """Half Beta(2,1)+half Beta(1,2)=uniform; not the false .193147 bonus."""
    m = _scalar_model(deterministic_names=True, points=((2*NS, F(1, 2)), (INFINITE_WORK, F(1, 2))))
    result = _eval(_belief(m), deadline=NS)
    action, = result.root.actions
    assert len(action.children) == 1
    assert action.children[0].branch.E == ()
    assert action.information.lower == action.information.upper == 0
    assert action.J == 0
    assert math.log(2)-.5 > action.information.upper


def test_static_fair_state_reported_twice_has_only_one_log_two():
    """Resetting to an unconditioned root each turn incorrectly counts 2 log 2."""
    m = JointModel(completion=_spec(("read",), ("0", "1")),
                   work={"read": WorkPrior(F(2), ((NS, F(1)),))},
                   names={"read": NameSpec(((1, 0), (0, 1)), False, "report")},
                   outcomes=("0", "1"), initial=(F(1, 2), F(1, 2)), Q=np.zeros((2, 2)),
                   measure=MeasureSpec("exact", "1", {}), w_star_ns=NS)
    result = _eval(_belief(m))
    a, = result.root.actions
    _enclosed(a.information, math.log(2))
    assert abs(a.information.midpoint-2*math.log(2)) > .6
    for c in a.children:
        assert c.child.actions[0].increment.upper < 1e-13


def test_softmax_box_bounds_and_nonmonotone_boltzmann_mean():
    """At J=(0,2), increasing J_b can decrease V; corner monotonicity fails."""
    def action(name, j, radius):
        # C=constant, information=constant-j, with symmetric uncertainty.
        return ActionValue(name, Interval(3., 3.), InformationBounds(3-j-radius, 3-j+radius),
                           InformationBounds(0, 0), Interval(j-radius, j+radius), (), None)
    values = (action("a", 0, .02), action("b", 2, .02))
    q, qb, _, _, vb, V = _mix_policy(values, 1.)
    assert V == pytest.approx(.2384058440442351, abs=2e-15)
    for x, y in product(np.linspace(-.02, .02, 11), np.linspace(1.98, 2.02, 11)):
        weights = _policy([x, y], 1.)
        _enclosed(vb, float(weights @ [x, y]))
        for i in (0, 1):
            _enclosed(qb[i], weights[i])
    plus = _policy([0, 2.02], 1.) @ [0, 2.02]
    assert plus < V
    assert tuple(q) != tuple(b.midpoint for b in qb)


def test_midpoint_J_softmax_and_requested_root_width():
    result = _eval(_belief(_bridge()), tolerance=1e-10)
    expected_q = _policy([a.expected_cost.midpoint-a.information.midpoint for a in result.root.actions], 1.)
    assert result.root.q == tuple(expected_q)
    for a in result.root.actions:
        for b in (a.expected_cost, a.information, a.J_bounds):
            assert b.upper-b.lower <= 1e-10
    for b in result.root.q_bounds:
        assert b.upper-b.lower <= 1e-10


def _batch_model():
    actions = ("blind", "good0", "good1", "sensor")
    return JointModel(completion=_spec(actions, ("0", "1")),
                      work={a: WorkPrior(F(2), ((NS, F(1)),)) for a in actions},
                      names={a: NameSpec(((1, 0), (0, 1)) if a == "sensor" else ((1, 0), (1, 0)), False, "report") for a in actions},
                      outcomes=("0", "1"), initial=(F(1, 2), F(1, 2)), Q=np.zeros((2, 2)),
                      measure=MeasureSpec("exact", "1", {}), w_star_ns=NS)


def _batch_cost(eta):
    action = eta.A[-1][-1]
    if action == "blind":
        return math.inf
    state = next((y for _, _, a, y in eta.O if a == "sensor"), None)
    return -math.log(.5 if state is None else (.8 if action == "good"+state else .2))


def test_simultaneous_reports_all_conditioned_before_next_softmax():
    """Correct next matching choice .8; deciding halfway through the batch gives .5."""
    root = _belief(_batch_model(), attempts=(Attempt("sensor-job", "sensor", 0),))
    result = _eval(root, candidates=("blind", "good0", "good1"), cost=_batch_cost, bound=-math.log(.2), deadline=2*NS-1)
    first = result.root.actions[0]
    for c in first.children:
        assert c.branch.t_end == NS
        assert len(c.branch.E) == 2
        assert {e[2] for e in c.branch.E} == {"sensor", "blind"}
        y = next(e[-1] for e in c.branch.E if e[2] == "sensor")
        assert c.child.q[1+int(y)] == pytest.approx(.8, abs=2e-14)
        assert c.child.q[0] == 0
    _enclosed(first.information, math.log(2))
    _enclosed(first.expected_cost, -.8*math.log(.8)-.2*math.log(.2))


def test_known_report_reposted_in_first_E_once_including_no_own_report():
    """Drops O0 omission, duplicate consumption, or waiting for a later choice."""
    root = _belief(_batch_model(), attempts=(Attempt("old", "sensor", 0),),
                   facts=(Completed("old", NS, "1"),), now=NS)
    O0 = ((0, "old", "sensor", "1"),)
    result = _eval(root, candidates=("blind", "good0", "good1"), deadline=3*NS-1,
                   cost=_batch_cost, bound=-math.log(.2), unread=O0)
    for c in result.root.actions[0].children:
        assert c.branch.E[0] == O0[0]
        assert c.child.q[2] == pytest.approx(.8, abs=2e-14)
        for a in c.child.actions:
            for leaf in a.children:
                assert all(e[1] != "old" for e in leaf.branch.E)
                assert sum(e[1] == "old" for e in leaf.child.eta.O) == 1
    # With zero window, O0 still goes to E / terminal cost, not discarded.
    immediate = _eval(root, candidates=("good0", "good1"), deadline=NS,
                      cost=_batch_cost, bound=-math.log(.2), unread=O0)
    assert immediate.root.q == pytest.approx((.2, .8), abs=2e-14)
    assert all(a.children[0].branch.E == O0 for a in immediate.root.actions)


def test_pending_jobs_share_F_and_identical_record_allocations_merge():
    """E[p²]=1/3 and E[p(1-p)]=1/6, not independent predictive products .25."""
    model = _scalar_model(deterministic_names=True, points=((NS, F(1, 2)), (2*NS, F(1, 2))))
    root = _belief(model, attempts=(Attempt("old", "a", 0),))
    rows = branches(Context(0, 0, (), (), ()), root, "a", NS, times=(0, NS), branch_budget=100)
    probabilities = {}
    for b in rows.items:
        labels = {e[1] for e in b.E}
        probabilities["old" in labels, b.attempt.label in labels] = b.probability
    assert probabilities == {(True, True): F(1, 3), (True, False): F(1, 6),
                              (False, True): F(1, 6), (False, False): F(1, 3)}
    assert rows.normalization == rows.normalization_bounds.lower == rows.normalization_bounds.upper == F(1)
    assert rows.total_variation_error == 0


def test_old_pending_work_is_not_redrawn_from_updated_F():
    """Old is certainly long; fresh short has 1/3. Independence/redraw loses this."""
    model = _scalar_model(deterministic_names=True, points=((NS, F(1, 2)), (2*NS, F(1, 2))))
    root = _belief(model, attempts=(Attempt("old", "a", 0),), facts=(NotArrived("old", NS),), now=NS)
    rows = branches(Context(NS, NS, (), (), ()), root, "a", 2*NS, times=(0, NS, 2*NS), branch_budget=100)
    assert all(any(e[1] == "old" and e[0] == NS for e in b.E) for b in rows.items)
    assert sum(b.probability for b in rows.items if any(e[1] == b.attempt.label for e in b.E)) == F(1, 3)
    assert all(b.belief.pending_work("old") == {2*NS: F(1)} for b in rows.items)


def test_next_start_is_previous_exact_completion_and_leaf_cost_is_kept():
    """Same R is shared; charges the whole final path, not a missing leaf cost."""
    model = _scalar_model(deterministic_names=True, points=((NS, F(1, 2)), (2*NS, F(1, 2))))
    result = _eval(_belief(model), deadline=2*NS+NS//10, cost=lambda eta: len(eta.A), bound=3)
    a = result.root.actions[0]
    for c in a.children:
        assert c.child.eta.time_ns == c.branch.t_end
        for nxt in c.child.actions[0].children:
            assert nxt.branch.attempt.start_ns == c.branch.t_end
            assert nxt.child.eta.A[-1][0] == c.branch.t_end
    _enclosed(a.expected_cost, 7/3)
    _enclosed(a.information, math.log(2)-.5 + .5*.1365141682948128)
    short = next(c for c in a.children if c.branch.t_end == NS)
    assert sum(c.branch.probability for c in short.child.actions[0].children if c.branch.E) == F(2, 3)
    assert result.max_depth == 3


def test_leaf_cost_is_charged_once_and_softmax_can_choose_more_costly_action():
    model = _scalar_model(deterministic_names=True, actions=("a", "b"))
    constant = _eval(_belief(model), cost=lambda eta: 7., bound=7.)
    assert all(a.expected_cost.midpoint == 7 for a in constant.root.actions)
    assert all(a.J == 7 for a in constant.root.actions)
    result = _eval(_belief(model), deadline=NS, cost=lambda eta: 2.*(eta.A[0][-1] == "b"), bound=2, u=.9)
    assert result.root.q == pytest.approx((.8807970779778823, .11920292202211755), abs=2e-15)
    assert result.chosen == "b"
    assert tuple(a.J for a in result.root.actions) == (0., 2.)


def test_original_deadline_does_not_restart_at_next_report():
    """H is absolute throughout; restarting a length-2 window produces extra data."""
    model = _scalar_model(deterministic_names=True)
    result = _eval(_belief(model))
    for a in result.root.actions:
        for c in a.children:
            assert c.branch.t_end == NS
            for second in c.child.actions[0].children:
                assert second.branch.t_end == 2*NS and not second.branch.terminal
                final = second.child.actions[0].children[0]
                assert final.branch.terminal and final.branch.E == ()
                assert len(final.child.eta.A) == 3  # Wrong >= boundary gives 2.
    late_root = _belief(model, now=NS)
    only_one = _eval(late_root, deadline=2*NS)
    assert only_one.max_depth == 2  # Wrong deadline terminal gives 1.
    final = only_one.root.actions[0].children[0].child.actions[0].children[0].child
    assert len(final.eta.A) == 2


@pytest.mark.parametrize("measure", ["start", "report"])
def test_known_point_work_Q_returns_to_s4d_increment_and_full_lookahead(measure):
    """Same known durations, Q, names, no pending Z, and lookahead evaluation."""
    from sui import lookahead as old
    from test_lookahead import _rig, _root
    from worlds import _lookahead_model
    Q = np.array([[-.7, .3], [.7, -.3]])
    # Dyadic probabilities have exactly normalized Fraction columns as well as
    # the same binary floats in legacy; decimal .9/.1 do not have that property.
    A = {"a": np.array([[.875, .25], [.125, .75]]), "b": np.array([[.375, .625], [.625, .375]])}
    legacy = _lookahead_model(states=("0", "1"), outcomes=("0", "1"), actions=("a", "b"),
                             D=np.array([.4, .6]), Q=Q, a=A, log_C=np.log([.5, .5]),
                             durations={a: ((1., 1.),) for a in A}, measures={a: measure for a in A})
    rig = _rig(model=legacy, H=2*NS)
    eta, old_belief, deadline, candidates, resolved = _root(rig)
    model = JointModel(completion=_spec(("a", "b"), ("0", "1")),
                       work={a: WorkPrior(F(5), ((NS, F(1)),)) for a in A},
                       names={a: NameSpec(tuple(tuple(F(float(x)) for x in A[a][:, s]) for s in (0, 1)), False, measure) for a in A},
                       outcomes=("0", "1"), initial=(F(2, 5), F(3, 5)), Q=Q,
                       measure=MeasureSpec("exact", "1", {}), w_star_ns=NS)
    joint = _belief(model)
    result = _eval(joint)
    old_values = [old._action_value(eta, old_belief, a, deadline, candidates, resolved) for a in candidates]
    for a, old_value in zip(result.root.actions, old_values):
        d = sum(math.exp(b.log_probability)*b.belief.kl(old_belief) for b in old.branches(eta, old_belief, a.action, deadline))
        _enclosed(a.increment, d)
        _enclosed(a.information, old_value.information)
        _enclosed(a.J_bounds, old_value.J)
    assert result.root.q == pytest.approx(tuple(old._policy([v.J for v in old_values], 1.)), abs=2e-12)


def test_two_beta_observations_match_terminal_KL_not_twice_first_information():
    result = _eval(_belief(_scalar_model()))
    a = result.root.actions[0]
    _enclosed(a.information, .3296613488547581)
    assert abs(a.information.midpoint-2*(math.log(2)-.5)) > .05
    expected_terminal = 2/3*_kl_beta(3, 1) + 1/3*_kl_beta(2, 2)
    _enclosed(a.information, expected_terminal)


def test_forbidden_leaves_and_unavoidable_no_continuation_propagate():
    model = _scalar_model(deterministic_names=True, actions=("a", "b"))
    result = _eval(_belief(model), deadline=NS-1, cost=lambda eta: math.inf if eta.A[-1][-1] == "a" else 0., bound=0)
    assert result.root.q == (0., 1.)
    assert result.root.actions[0].J_bounds.lower == math.inf
    assert result.root.actions[0].reason == "forbidden_terminal"
    with pytest.raises(NoAdmissibleCandidate):
        _eval(_belief(model), cost=lambda eta: math.inf, bound=0)
    # Initial a reaches a next node where every completion is forbidden.
    # Initial b reports outside the window. At the deadline it would also
    # create a forbidden next choice, rather than the old false successful leaf.
    works = {"a": WorkPrior(F(2), ((NS, F(1)),)), "b": WorkPrior(F(2), ((3*NS, F(1)),))}
    model = replace(model, work=works)
    result = _eval(_belief(model), cost=lambda eta: math.inf if len(eta.A) > 1 else 0., bound=0)
    assert result.root.actions[0].information is None
    assert result.root.actions[0].reason == "no_admissible_continuation"
    assert result.root.q == (0., 1.)


def test_rare_positive_forbidden_branch_cannot_disappear():
    model = _scalar_model(deterministic_names=True, points=((NS, F(1)-F(1, 10**400)), (2*NS, F(1, 10**400))))
    root = _belief(model)
    # Raw branching retains the very small positive mass before float arithmetic.
    rows = branches(Context(0, 0, (), (), ()), root, "a", NS, times=(0, NS), branch_budget=100)
    rare = next(b for b in rows.items if not b.E)
    assert rare.probability == F(1, 10**400)
    assert math.isfinite(rare.log_probability)
    # The information arithmetic is outside float range: it must STOP rather
    # than discard the forbidden late branch and return a finite decision.
    with pytest.raises(NumericalRange):
        _eval(root, deadline=NS, cost=lambda eta: 0 if eta.O else math.inf, bound=0)


@pytest.mark.parametrize("change,reason", [
    ({"node_budget": 1}, "budget"),
    ({"cost": lambda eta: 1., "bound": 0}, "cost_bound"),
    ({"tolerance": 1e-18, "refinement_budget": 1}, "width|accuracy"),
])
def test_unfinished_computation_does_not_remove_candidates(change, reason):
    with pytest.raises(IntegrationIncomplete, match=reason):
        _eval(_belief(_bridge()), **change)


def test_uncertified_pending_context_and_noninteger_time_stop():
    model = _scalar_model(deterministic_names=True, points=((NS, F(1, 2)), (2*NS, F(1, 2))))
    with pytest.raises(IntegrationIncomplete, match="pending_context"):
        _eval(_belief(model, attempts=(Attempt("old", "a", 0),), now=NS))
    with pytest.raises(IntegrationIncomplete, match="integer ns"):
        _eval(_belief(model), deadline=1.5*NS)


def test_policy_gamma_zero_and_certified_J_bounds_include_all_corners():
    scores = (Interval(-2, -1), Interval(.3, 2), Interval(math.inf, math.inf))
    bounds = policy_bounds(scores, 3.)
    assert bounds[2] == Interval(0, 0)
    for x, y in product((-2., -1., -1.5), (.3, 2., 1.1)):
        q = _policy([x, y, math.inf], 3.)
        for i in range(3):
            _enclosed(bounds[i], q[i])
    assert policy_bounds(scores, 0.) == (Interval(.5, .5), Interval(.5, .5), Interval(0, 0))


@pytest.mark.parametrize("change", [
    {"cost": lambda eta: F(1, 10**400)},
    {"bound": F(1, 10**400)},
    {"gamma": F(1, 10**400)},
    {"cost": lambda eta: 10**400},
])
def test_positive_cost_and_controls_cannot_silently_round_to_zero_or_infinity(change):
    with pytest.raises(NumericalRange):
        _eval(_belief(_scalar_model(deterministic_names=True)), **change)


def test_finite_wide_interval_midpoint_is_not_a_forbidden_infinity():
    interval = Interval(-1e308, 1e308)
    assert interval.midpoint == 0.
    assert interval.radius == 1e308
