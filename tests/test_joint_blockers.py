"""Review B1--B4: independent likelihoods, boundary values and public entries."""
from dataclasses import replace
from fractions import Fraction as F
import math
import json
from scipy.integrate import quad

import numpy as np
import pytest

from sui.agent import plan
from sui.contracts import ContractRef
from sui.joint import Attempt, Completed
from sui.joint_entry import rebuild
from sui.joint_lookahead import RulerNode
from sui.model import GenerativeModel, model_json, evaluation_timing
from sui.records import Observed, Payload
from sui.s1_contracts import OUTCOME
from sui.quantity import IntegrationIncomplete
from test_joint_entry import _model, _prior, _exact, _view, _append_check, _inside
from test_joint_lookahead import _batch_model, _batch_cost, _belief, _eval, _scalar_model
from test_progress_lookahead import _eval as _ruler, _models, LN2
from test_lookahead import _rig
from worlds import HandHistory

NS = 1_000_000_000


def _constant_model(work=None):
    return replace(_model(learned=False, work=work), D=np.array([0., 1.]),
                   a={a: np.array([[1., 1.], [0., 0.]]) for a in ("a", "b")})


def test_history_root_external_check_includes_equal_time_atom():
    h = HandHistory()
    h.boot()
    old = h.start("a", 0)
    check = _append_check(h, 1)
    model = _constant_model({a: _prior((NS,), (1.,), 2.) for a in ("a", "b")})
    r = _rig(model=model, history=h, H=0)
    root, _ = rebuild(model, r.agent._reading, now_ns=NS, observed_ns=NS,
                      check_events=({"fact": str(check.id)},), fact_ancestors=r.agent._fact_ancestors)
    assert root.target_marginal().evidence == F(1)  # Wrong strict >: 0 / ModelFalsified.
    assert root.pending_work(str(old.id)) == {NS: F(1)}
    assert plan(_view(r, NS, check=check), ("b",), u=.5).content.as_json()["information"] == pytest.approx([0.], abs=3e-14)


@pytest.mark.parametrize("both", [False, True])
def test_history_sequential_tie_K_stays_inside_work_sum(both):
    h = HandHistory()
    h.boot()
    first, second = h.start("a", 0), h.start("a", 0)
    receipt = h.observe(first, "0", 1)
    if both:
        receipt = h.observe(second, "0", 1)
    model = _constant_model()
    r = _rig(model=model, history=h, H=0)
    root, _ = rebuild(model, r.agent._reading, now_ns=NS, observed_ns=NS,
                      check_events=({"fact": str(receipt.id)},), fact_ancestors=r.agent._fact_ancestors)
    if both:
        # integral p^2/2 dp = 1/6. Wrong >= without K gives 1/3, > gives 0.
        assert root.target_marginal().evidence == F(1, 6)
    else:
        # L(p)=p(1-p)+p^2/2. Integral=1/3, integral pL=5/24.
        assert root.target_marginal().evidence == F(1, 3)
        new = Attempt("fresh", "a", NS)
        prediction = root.predictive(new, until_ns=2*NS).probabilities
        assert prediction[(2*NS, "0")] == F(5, 8)
        assert prediction[(2*NS, "0")] not in (F(1, 2), F(2, 3))
        assert root.pending_work(str(second.id)) == {NS: F(1, 2), 2*NS: F(1, 2)}
        assert root.predictive(next(a for a in root.attempts if a.label == str(second.id)),
                               until_ns=NS).probabilities[(NS, "0")] == F(1, 2)
        # Wrong > predicts 0; >= without K predicts 2/3 for the old draw.


def test_deadline_choice_charges_two_starts_in_stage1():
    result = _eval(_belief(_scalar_model(deterministic_names=True)), deadline=NS,
                   cost=lambda eta: len(eta.A), bound=2)
    assert result.root.actions[0].expected_cost.midpoint == 2
    assert result.max_depth == 2  # Wrong >= terminal: cost=1, depth=1.
    last = result.root.actions[0].children[0].child.actions[0].children[0]
    assert last.branch.attempt.start_ns == NS and last.branch.E == ()


@pytest.mark.parametrize("unread_content", [None, "0", "1"])
def test_unread_O0_is_information_without_root_content_preconditioning(unread_content):
    # The explicit unread input asserts not-yet-ingested, independently of
    # Completed(None). Metadata locates the old REPORT at 1s, root now=2s. Static
    # state means it fully teaches the same state even before root time.
    root = _belief(_batch_model(), attempts=(Attempt("old", "sensor", 0),),
                   facts=(Completed("old", NS, None),), now=2*NS)
    O0 = ((-NS, "old", "sensor", unread_content),)
    result = _eval(root, candidates=("good0", "good1"), deadline=2*NS,
                   cost=_batch_cost, bound=-math.log(.2), unread=O0)
    # Choosing BEFORE reading O0 has equal costs: -log(.8*.2)/2.
    assert result.root.q == pytest.approx((.5, .5), abs=3e-14)
    assert result.root.q != pytest.approx((.8, .2))  # Wrong early content use.
    for a in result.root.actions:
        assert a.information.midpoint == pytest.approx(LN2, abs=3e-14)
        assert {b.branch.E[0][-1] for b in a.children} == {"0", "1"}
        assert all(b.branch.E[0][0] == -NS for b in a.children)
    zero = _eval(root, candidates=("good0",), deadline=2*NS, unread=O0)
    assert zero.root.actions[0].J == pytest.approx(-LN2, abs=3e-14)
    assert zero.root.actions[0].J != 0  # Dropping O0 information.


@pytest.mark.parametrize("reason,content", [("contract", "0"), ("contract", "1"), ("content", None)])
def test_public_ingested_unreadable_name_is_not_O0(reason, content):
    h = HandHistory()
    h.boot()
    old = h.start("a", 0)
    unread = h.add(Observed(route="executor", contract=ContractRef("test.unread", "1") if reason == "contract" else OUTCOME,
                  content=Payload.json({"outcome": content}), caused_by=old.id, received_ns=NS), 1)
    model = replace(_model(learned=False), D=np.array([.5, .5]), measures={"a": "start", "b": "report"})
    r = _rig(model=model, history=h, H=0)
    assert r.agent._reading.unread[unread.id] == reason
    root, _ = rebuild(model, r.agent._reading, now_ns=NS, observed_ns=NS,
                      check_events=({"fact": str(unread.id)},), fact_ancestors=r.agent._fact_ancestors)
    assert Completed(str(old.id), NS, None) in root.facts
    assert root.pending_work(str(old.id)) == {NS: F(1)}  # Its timing is still learned.
    # W_a~DP(2; 1/2 at 1,2) becomes Beta(2,1): next W_a=1 has mass 2/3.
    future = root.predictive(Attempt("fresh", "a", NS), until_ns=2*NS).probabilities
    assert sum(p for (t, _), p in future.items() if t == 2*NS) == F(2, 3)
    data = plan(_view(r, NS, check=unread), ("b",), u=.5).content.as_json()
    _inside(data["information_bounds"][0], 0.)
    _inside(data["J_bounds"][0], 0.)
    assert data["information"][0] == pytest.approx(0., abs=3e-14)
    assert data["J"][0] == pytest.approx(0., abs=3e-14)
    assert abs(data["information"][0]-LN2) > .69  # Wrong automatic O0: ln2 / -ln2.


def test_public_not_ingested_report_enters_first_E_at_root_check():
    h = HandHistory()
    h.boot()
    old = h.start("a", 0)
    check = _append_check(h, 1)  # No report has been ingested.
    model = replace(_model(learned=False, work={a: _prior((NS,), (1.,), 2.) for a in ("a", "b")}),
                    D=np.array([.5, .5]), measures={"a": "start", "b": "report"})
    r = _rig(model=model, history=h, H=0)
    root, _ = rebuild(model, r.agent._reading, now_ns=NS, observed_ns=NS,
                      check_events=({"fact": str(check.id)},), fact_ancestors=r.agent._fact_ancestors)
    assert all(not isinstance(f, Completed) for f in root.facts)
    assert root.pending_work(str(old.id)) == {NS: F(1)}
    data = plan(_view(r, NS, check=check), ("b",), u=.5).content.as_json()
    _inside(data["information_bounds"][0], LN2)
    _inside(data["J_bounds"][0], -LN2)
    assert data["information"][0] == pytest.approx(LN2, abs=3e-14)
    assert abs(data["information"][0]) > .69  # Wrong omission of pending O0: 0.
    result = _eval(root, candidates=("b",), deadline=NS)
    first_E = {b.branch.E: b.branch for b in result.root.actions[0].children}
    assert set(first_E) == {((0, str(old.id), "a", y),) for y in ("0", "1")}
    for branch in first_E.values():
        assert branch.probability_bounds.lower <= F(1, 2) <= branch.probability_bounds.upper
        assert float(branch.probability) == pytest.approx(.5, abs=3e-14)
    assert sum(b.probability for b in first_E.values()) == F(1)
    assert all(b.branch.attempt.start_ns == NS for b in result.root.actions[0].children)


def test_ingested_unreadable_report_does_not_register_old_target_times():
    root = _belief(_batch_model(), attempts=(Attempt("old", "sensor", NS//2),),
                   facts=(Completed("old", 3*NS//2, None),), now=2*NS)
    result = _eval(root, candidates=("good0",), deadline=2*NS)
    assert result.times == (0,)  # Wrong None inference adds the old report's 1.5s.
    assert result.root.actions[0].information.midpoint == pytest.approx(0., abs=3e-14)
    assert result.root.actions[0].children[0].branch.E == ()
    explicit = _eval(root, candidates=("good0",), deadline=2*NS,
                     unread=((-NS//2, "old", "sensor", None),))
    assert 3*NS//2 in explicit.times
    assert explicit.root.actions[0].information.midpoint == pytest.approx(LN2, abs=3e-14)
    known = root.condition((Completed("old", 3*NS//2, "1"),), observed_ns=2*NS)
    reposted = _eval(known, candidates=("good0",), deadline=2*NS,
                     unread=((-NS//2, "old", "sensor", "1"),))
    assert reposted.times == (0,)  # Known reports are cost-path metadata only.
    assert reposted.root.actions[0].information.midpoint == pytest.approx(0., abs=3e-14)
    assert reposted.root.actions[0].children[0].branch.E == ((-NS//2, "old", "sensor", "1"),)


def test_stage2_common_U_numeric_cost_and_root_policy():
    # R=(1+T)/2 under the fast law, prior 1/2. For H=.9,
    # completion mass m=(1-2^(-.8))/2. Later all U are outside the window,
    # child policy=(3/4,1/4), hence C_a=m*log3/4, C_b=log3.
    r = _ruler(horizon=F(9, 10), offsets={"a": 0, "b": math.log(3)})
    m = (1-2**(-.8))/2
    expected = m*math.log(3)/4
    _inside((r.root.actions[0].expected_cost.lower, r.root.actions[0].expected_cost.upper), expected)
    assert expected == pytest.approx(.0584531530, abs=5e-11)
    assert abs(expected-m*math.log(3)) > .17  # Wrong continuation=b: .2338126121.
    for e in r.root.actions[0].children:
        if isinstance(e.child, RulerNode):
            assert tuple(a.action for a in e.child.actions) == ("a", "b")
            assert e.child.q == pytest.approx((.75, .25), abs=3e-14)
    p = 1-m
    fast = .5*2**(-.8)/p
    law = m*LN2+p*(fast*math.log(2*fast)+(1-fast)*math.log(2*(1-fast)))
    state = .5*quad(lambda t: LN2*2**(-t)*-math.log1p(-2**(-(1+t)/2)), 0, .8,
                      epsabs=2e-13, epsrel=2e-13)[0]
    _inside((r.root.actions[0].information.lower, r.root.actions[0].information.upper), law+state)
    assert law+state == pytest.approx(.3874938565, abs=5e-11)
    assert r.root.q[0] == pytest.approx(.8065353613, abs=5e-10)
    assert abs(r.root.q[0]-.7776966302) > .028


def test_stage2_uncertified_member_cannot_be_filtered_at_later_nodes():
    # At H=2 another a can be informative on a positive-probability path.
    with pytest.raises(IntegrationIncomplete, match="candidate a may yield another informative report"):
        _ruler(horizon=2)
    # Dropping it and continuing only b wrongly returns a finite decision.


@pytest.mark.parametrize("scheme", [5, 6])
def test_released_model5_model6_public_information_independent_beta_integral(scheme):
    common = dict(states=("0", "1"), outcomes=("0", "1"), actions=("a",),
                  D=np.array([1., 0.]), log_C=np.log([.5, .5]), gamma=1.)
    if scheme == 5:
        model = GenerativeModel(**common, a={"a": np.ones((2, 2))}, learnable=frozenset({"a"}),
                    Q=np.array([[-LN2, 0.], [LN2, 0.]]), durations={"a": ((1., 1.),)},
                    measures={"a": "report"})
    else:
        model = GenerativeModel(**common, a={"a": np.array([[1., 1.], [0., 0.]])},
                    learnable=frozenset(), duration_priors={"a": _prior((NS, 2*NS), (.5, .5), 2.)},
                    measure=_exact())
    assert json.loads(model_json(model))["scheme"] == "sui.model."+str(scheme)
    r = _rig(model=model, H=NS)
    data = plan(_view(r), ("a",), u=.5).content.as_json()
    # Uniform p: H(Bernoulli(1/2))-integral[-p log p-(1-p)log(1-p)]dp
    # = log2-1/2. Model5 observes a learned name; model6 observes W<=1.
    expected = LN2-.5
    _inside(data["information_bounds"][0], expected)
    _inside(data["J_bounds"][0], -expected)
    assert data["q_pi"] == [1.] and data["information"][0] != 0
    requirement = evaluation_timing(model)
    assert requirement.needs_axis and requirement.needs_receipt_boundary
    assert requirement.needs_check_events == (scheme == 6)
