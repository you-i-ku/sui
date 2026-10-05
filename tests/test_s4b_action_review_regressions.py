"""S4b v0.22 review B1--B4/T1: specification-derived public-path rulers.

No implementation inspection or private entry points. In particular, T1 uses
model.8/action APIs, not progress.completion. All times are exact clock readings
with BOOT at zero unless the test explicitly shifts its origin.
"""
from fractions import Fraction as F
import math

import pytest

from s4b_action_cases import (FLIP, I, NS, api, assert_bounds,
    assert_distribution, budget, declaration, load_model)
from s4b_action_time_cases import FactWorld, marginal, potential, targets
from test_s4b_action_stage3 import scenario


def fixed_state(belief, time):
    label = api("action_types").FixedLabel(time_s=F(time), causal_stage=0,
        causal_position=0, side="post")
    return api("action_joint").target_marginal(belief, (label,), budget=budget())


def test_b1_actual_attempt_unrecorded_tick_conditions_on_nonarrival():
    """R=1+U; R>3/2 iff U=1, so posterior=1 and log evidence=-ln2."""
    from test_lookahead import _rig
    d = declaration(kernels={"a": I}, observed=False)
    d["work"]["a"]["points"] = [[2*NS, [1, 1]]]
    d["completion"]["candidates"] = [[[[2, 1], [1, 1]]]]
    d["completion"]["max_speed"] = [2, 1]
    w = FactWorld(d)
    _, attempt = w.start("a", 0)
    r = _rig(model=w.model, history=w.h, H=3*NS, items=())
    before = tuple(r.ledger.entries())
    assert r.ledger.entries_of(attempt.id)
    check = {"unrecorded": {"kind": "tick", "reading": 3*NS//2,
                             "after": sorted(r.agent.frontier)}}
    view = r.agent.view(now_ns=3*NS//2, observed_ns=3*NS//2, check_events=(check,))
    context = api("action_types").ActionTimeContext(run=r.clock.run,
        now_ns=view.now_ns, observed_ns=view.observed_ns, check_events=view.check_events,
        fact_ancestors=view.fact_ancestors, clock_source=None)
    belief = api("action_entry").rebuild_action_belief(w.model, view.reading,
        context=context, budget=budget())
    assert belief.evidence_kind == "mass"
    assert_bounds(belief.log_evidence, math.log(.5))
    assert_distribution(fixed_state(belief, F(3, 2)), {("1",): F(1)})
    assert tuple(r.ledger.entries()) == before  # no predicted report became a fact


def noninterference_case(threshold):
    from sui.preference import current, resolve
    from test_lookahead import _rig
    d, H, _ = scenario(22)
    d["choices"]["act"]["reservation"]["not_before_ns"] = threshold
    w = FactWorld(d)
    w.start("first", 0)
    root = w.belief()
    r = _rig(model=w.model, history=w.h, H=H, items=())
    view = r.agent.view(now_ns=0, observed_ns=0,
        check_events=({"fact": str(w.records[0].id)},))
    resolved = resolve(current(view.preferences), view)
    entry = api("action_entry")
    cert = entry.certify_action_scope(view, ("act",), resolved, budget=budget())
    if cert.status != "certified":
        entry.public_evaluate(view, ("act",), resolved, u=.25, budget=budget())
        pytest.fail("uncertified scope returned an evaluation")
    first = next(r for r in w.records
        if getattr(getattr(r.body, "contract", None), "name", None) == "sui.s4b.action_attempt")
    report = w.report(first, 2*NS)
    parent = w.node(registered=targets(report))
    parent_value = potential(root, parent, cert)
    assert_bounds(parent_value, math.log(2))
    cmd, _ = w.start("act", 2*NS, stage=1)
    measure = api("action_lookahead").branches(parent, cmd, deadline_ns=H,
        certificate=cert, budget=budget())
    assert_bounds(measure.total_mass, F(1))
    assert len(measure.atoms) == 1
    atom, = measure.atoms
    assert_bounds(atom.probability, F(1))
    child_value = potential(root, atom.child, cert)
    return parent_value, child_value


def test_b2_unsafe_reservation_stops_before_certifying_negative_increment():
    """Root U=0 dispatches at 5/4<old fixed S(2); old marginal is changed."""
    types = api("action_types")
    with pytest.raises((types.ActionIncomplete, types.ActionIncompatible)) as caught:
        noninterference_case(0)
    error = caught.value
    if isinstance(error, types.ActionIncomplete):
        assert error.reason == "noninterference_unproved"
    else:
        assert error.reason == "negative_increment_counterexample"


def test_b2_safe_reservation_still_has_zero_increment():
    parent, child = noninterference_case(9*NS//4)
    assert_bounds(child, math.log(2))
    assert child.lower-parent.upper <= 0 <= child.upper-parent.lower
    assert child.upper-parent.lower - (child.lower-parent.upper) <= 2e-9


@pytest.mark.parametrize("boot_reading", (0, NS))
def test_b3_boot_reading_is_origin_not_elapsed_physical_time(boot_reading):
    """D is at true t=0; an absolute BOOT reading cannot evolve D for 1s."""
    from sui.agent import read
    from worlds import HandHistory
    d = declaration(kernels={"a": I}, initial=(1, 0), observed=False)
    q = math.log(2)
    d["activity"]["Q_by_mode"]["idle"] = [[-q, 0.], [q, 0.]]
    model = load_model(d)
    h = HandHistory(run=f"boot-origin-{boot_reading}")
    boot = h.boot(F(boot_reading, NS))
    context = api("action_types").ActionTimeContext(run=h.clock.run,
        now_ns=boot_reading, observed_ns=boot_reading,
        check_events=({"fact": str(boot.id)},),
        fact_ancestors={str(boot.id): frozenset()}, clock_source=None)
    belief = api("action_entry").rebuild_action_belief(model, read(model, tuple(h.records)),
        context=context, budget=budget())
    assert_bounds(belief.log_evidence, 0.)
    assert_distribution(fixed_state(belief, 0), {("0",): F(1)}, exact=False)
    # Check the current belief too, not only an explicitly queried past label.
    from test_lookahead import _rig
    r = _rig(model=model, history=h, H=2*NS, items=())
    saved = r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger)
    data = saved.body.content.as_json()
    assert data["status"] in {"prior", "complete"}
    assert data["q"] == pytest.approx([1., 0.], abs=1e-9)


def test_b4_threadhost_nonzero_first_tick_rebuilds_completed_belief(monkeypatch):
    """Root=10, think=7, offset=3 => r_d=17, dispatch=20, report=NS+20."""
    from sui.agent import Agent
    from sui.records import Observed
    from sui.runtime import Tick
    from sui.s4_contracts import BOOT
    from test_s4b_action_integration import host_fixture, named, records
    f = host_fixture(monkeypatch)
    assert f.host.run_until(lambda s: bool(records(f.r, Observed, "sui.clock.source")), timeout=1)
    boots = [r for r in records(f.r, Observed) if r.body.contract == BOOT]
    source, = records(f.r, Observed, "sui.clock.source")
    assert len(boots) == 1 and boots[0].at.mono_ns == source.at.mono_ns == 0
    f.r.clock.advance(10)
    f.host.post(Tick(mono_ns=10))
    assert f.host.run_until(lambda s: bool(f.thoughts) and not s.thinking and not s.awaiting,
        timeout=3), "host did not finish the bounded simulated work"
    assert len(f.plans) == len(f.thoughts) == 1
    assert f.plans[0].now_ns == 10
    assert f.thoughts[0].decision_reading.reading_ns == 17
    attempt, = named(f.r, "action_attempt")
    assert attempt.body.content.as_json()["command"]["not_before_ns"] == 20
    assert f.hand.calls == ["a"] and f.hand.readings == [20]
    report, = named(f.r, "action_report")
    assert report.body.content.as_json()["completion_reading_ns"] == NS+20
    saved = f.r.agent.belief_record(clock=f.r.clock, ids=f.r.ids, ledger=f.r.ledger)
    summary = saved.body.content.as_json()
    assert summary["status"] == "complete", summary
    assert summary["q"] == [0., 1.]
    assert summary["pending"] == summary["unread"] == []
    cid = f.r.ledger.entries_of(saved.id)[0].cid
    restored = Agent.restore(model=f.r.model, lineage="review-b4", ledger=f.r.ledger, belief=cid)
    assert restored.q.tolist() == [0., 1.]
    rebuilt = restored.belief_record(clock=f.r.clock, ids=f.r.ids, ledger=f.r.ledger)
    assert rebuilt.body.content.as_json()["status"] == "complete"
    assert rebuilt.body.content.as_json()["q"] == [0., 1.]


def test_t1a_action_branches_recompute_running_work_after_another_impulse():
    """At .5, consumed=.5; remaining=1.5 at speed2 => R=1.25, not2."""
    d = declaration(("work", "boost"), kernels={"work": I, "boost": [[0, 0], [1, 1]]},
        initial=(1, 0), observed=False)
    d["work"]["work"]["points"] = [[2*NS, [1, 1]]]
    d["work"]["boost"]["points"] = [[100*NS, [1, 1]]]
    d["completion"]["candidates"] = [[[[1, 1], [2, 1]], [[1, 1], [1, 1]]]]
    d["completion"]["max_speed"] = [2, 1]
    d["choices"]["boost"]["reservation"]["not_before_ns"] = NS//2
    w = FactWorld(d)
    _, attempt = w.start("work", 0)
    root, cert = w.root(2*NS, candidates=("boost",))
    node = api("action_types").ActionNode(belief=root, controls=(), targets=(),
        terminal=False, trigger=None)
    decision = api("action_types").DecisionReading(run=w.h.clock.run, reading_ns=0,
        work="review-t1a", parents=frozenset(w.ledger.heads()))
    cmd = api("dispatch").build_command(model=w.model, choice="boost", decision=decision,
        causal_stage=0, causal_position=1)
    measure = api("action_lookahead").branches(node, cmd, deadline_ns=2*NS,
        certificate=cert, budget=budget())
    assert_bounds(measure.total_mass, F(1))
    assert len(measure.atoms) == 1
    atom, = measure.atoms
    assert_bounds(atom.probability, F(1))
    reports = [r for r in atom.records if getattr(getattr(r.body, "contract", None),
        "name", None) == "sui.s4b.action_report"]
    assert len(reports) == 1
    report, = reports
    assert report.body.caused_by == attempt.id
    assert report.body.received_ns == 5*NS//4
    assert report.body.content.as_json()["completion_reading_ns"] == 5*NS//4
    assert_distribution(marginal(atom.child, targets(report)), {("1", "1"): F(1)})


@pytest.mark.parametrize("time", (F(1, 2), F(1)))
def test_t1b_response_wait_uses_state_at_response_not_dispatch(time):
    """Natural 0->1 and independent response each have rate q=ln2.

    Response flips once; then natural evolution continues. P0(t) equals
    e^(-2qt) + integral_0^t q e^(-qs)(1-e^(-qs))e^(-q(t-s)) ds
    = 2e^(-2qt)+(qt-1)e^(-qt). Using B's dispatch-state column instead
    makes every response go to1 and wrongly gives P0(t)=e^(-2qt).
    Work=100s begins at dispatch, so no report is due at either query time.
    """
    d = declaration(kernels={"a": FLIP}, initial=(1, 0), observed=False)
    q = math.log(2)
    d["activity"]["Q_by_mode"]["idle"] = [[-q, 0.], [q, 0.]]
    d["work"]["a"]["points"] = [[100*NS, [1, 1]]]
    d["effects"]["a"].update(family={"name": "response-wait", "version": "1"},
        response_rate_s=[q, q], progress_start="dispatch")
    w = FactWorld(d)
    w.start("a", 0)
    belief = w.belief(now_ns=int(time*NS))
    p0 = 2*math.exp(-2*q*float(time))+(q*float(time)-1)*math.exp(-q*float(time))
    assert_bounds(belief.log_evidence, 0.)
    assert_distribution(fixed_state(belief, time), {("0",): p0, ("1",): 1-p0}, exact=False)
