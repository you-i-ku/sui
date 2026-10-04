"""§6-3(iii): integer-record public boundary, independent fixtures and persistence.

Bridge B numbers are the frozen independent §6-2 reference. All other assertions
below use elementary Beta updates, a known law, or fact/replay identity, never
expectations produced by joint code. Core mathematical mutation fixtures remain
in test_joint/test_progress/test_joint_lookahead/test_progress_lookahead.
"""
from dataclasses import replace
from fractions import Fraction as F
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import numpy as np
import pytest

from sui.agent import Agent, plan, read, replay_decision, ModelFalsified, RebuildMismatch
from sui.model import GenerativeModel, ProgressModel, model_json, model_from_json, model_ref
from sui.progress import CompletionSpec
from sui.quantity import BaseSpec, DurationPrior, IntegrationIncomplete
from sui.records import Payload, Observed, Record, Role, Producer, Preference, Decided
from sui.ids import RefKind as K
from sui.s1_contracts import OUTCOME
from sui.s4d_contracts import PREFERENCE
from sui.s4b1c_contracts import BELIEF, DECISION, DECLARATIONS
from sui.lookahead import OutsideEvaluationType, NoAdmissibleCandidate
from sui.preference import resolve, current
from sui import lookahead
from worlds import HandHistory, ManualHost, ScriptDrive, GatedHand, _storage
from test_lookahead import _rig, _table

NS = 1_000_000_000
ROUND = 4e-14


def _prior(points, masses, alpha):
    return DurationPrior(alpha, BaseSpec("atoms", "1", {"points": [[p, m] for p, m in zip(points, masses)]}))


def _exact(weights=(1.,)):
    return {"share": "all_actions", "candidates": [
        {"name": "exact", "version": "1", "params": {}, "weight": w} for w in weights]}


def _model(*, speeds=None, weights=(F(1),), work=None, measure=None, measures=None, learned=True):
    spec = CompletionSpec(name="progress", version="1", actions=("a", "b"), states=("0", "1"),
        work_unit="ns", time_unit="ns", speed_unit="ns/ns", share="all_actions",
        candidates=(((1, 1), (1, 1)),) if speeds is None else speeds, weights=weights,
        max_speed=max(r for c in ((((1, 1), (1, 1)),) if speeds is None else speeds) for row in c for r in row))
    return ProgressModel(states=("0", "1"), outcomes=("0", "1"), actions=("a", "b"),
        a={"a": np.ones((2, 2)) if learned else np.eye(2), "b": np.eye(2)},
        learnable=frozenset({"a"}) if learned else frozenset(), D=np.array([1., 0.]),
        Q=np.array([[-math.log(2), 0.], [math.log(2), 0.]]), log_C=np.log([.5, .5]), gamma=1.,
        completion=spec, work_priors={"a": _prior((NS, 2*NS), (.5, .5), 2.),
                                     "b": _prior((NS,), (1.,), 3.)} if work is None else work,
        measure=_exact() if measure is None else measure,
        measures={"a": "report", "b": "report"} if measures is None else measures)


def _view(r, now=0, observed=None, check=None):
    return r.agent.view(now_ns=now, observed_ns=now if observed is None else observed,
        check_events=({"fact": str(r.h.records[-1].id if check is None else check.id)},))


def _append_check(h, seconds):
    from sui.contracts import ContractRef
    return h.add(Observed(route="membrane", contract=ContractRef("test.joint.check", "1"),
                          content=Payload.json({}), received_ns=round(seconds*NS)), seconds)


def _inside(box, value):
    assert box[0]-ROUND <= value <= box[1]+ROUND


def _same_state(r):
    return tuple(r.ledger.entries()), r.agent.frontier, r.agent.revision, r.agent._belief


def test_public_bridge_b_fixed_root_scores_intervals_and_midpoint_policy():
    r = _rig(model=_model(), H=2*NS)
    before = _same_state(r)
    draft = plan(_view(r), ("b", "a", "a"), u=.5)
    data = draft.content.as_json()
    assert _same_state(r) == before
    assert draft.contract == DECISION and data["chosen"] == "b"
    for box, expected in zip(data["J_bounds"], (-.6004777099601217, -1.0417864504639565)):
        _inside(box, expected)
    _inside(data["q_pi_bounds"][0], .39142916681104983)
    assert data["candidates"] == ["a", "b"]
    for c, i, j, cb, ib in zip(data["expected_cost"], data["information"], data["J"],
                              data["expected_cost_bounds"], data["information_bounds"]):
        assert c == sum(cb)/2 and i == sum(ib)/2 and j == c-i
    expected_q = 1/(1+math.exp(data["J"][0]-data["J"][1]))
    assert data["q_pi"][0] == pytest.approx(expected_q, abs=ROUND)
    assert data["root"] == {"belief": str(r.agent._belief.id), "parents": sorted(r.agent.frontier)}
    assert data["algorithm"] == {"name": "joint_stage1", "version": "1", "stage": "1"}


def test_direct_lookahead_and_plan_are_identical():
    r = _rig(model=_model(), H=2*NS)
    view = _view(r)
    resolved = resolve(current(view.preferences), view)
    assert lookahead.evaluate(view, ("a", "b"), resolved, u=.25) == plan(view, ("a", "b"), u=.25)


def test_native_fact_posterior_and_restore_use_joint_state_not_independent_counts():
    h = HandHistory()
    h.boot()
    attempt = h.start("a", 0)
    h.observe(attempt, "1", 1)
    r = _rig(model=_model(learned=False), history=h, H=NS)
    data = r.agent._belief.body.content.as_json()
    assert r.agent._belief.body.contract == BELIEF
    assert data["joint"]["status"] == "complete"
    assert data["q"] == pytest.approx([0., 1.], abs=ROUND)
    # Observing W=1 updates Beta(1,1) to Beta(2,1).
    assert data["joint"]["work_mean"]["a"] == pytest.approx([2/3, 1/3], abs=ROUND)
    cid = r.ledger.entries_of(r.agent._belief.id)[0].cid
    restored = Agent.restore(model=r.model, lineage="restore", ledger=r.ledger, belief=cid)
    assert restored._belief.body.content == r.agent._belief.body.content
    with pytest.raises(ValueError, match="no single ledger"):
        restored.counts("a")


def test_fact_set_and_batch_adoption_reconstruct_same_content():
    h = HandHistory()
    h.boot()
    attempt = h.start("a", 0)
    h.observe(attempt, "1", 1)
    model = _model()
    whole = _rig(model=model, history=h, H=NS)
    from sui.ledger import Ledger, SequentialSalts
    from sui.ids import SequentialIds
    ledger, ids = Ledger(salts=SequentialSalts()), SequentialIds(prefix="batch")
    subject = Agent(model=model, lineage="batch")
    for record in h.records:
        ledger.append(record, ledger.heads())
        subject.adopt(ledger, clock=h.clock, ids=ids)
    assert subject._belief.body.content == whole.agent._belief.body.content


def test_pending_nonarrival_retains_original_work_in_public_lookahead():
    h = HandHistory()
    h.boot()
    attempt = h.start("a", 0)
    check = _append_check(h, 1)
    r = _rig(model=_model(learned=False), history=h, H=NS)
    from sui.joint_entry import rebuild
    root, _ = rebuild(r.model, r.agent._reading, now_ns=NS, observed_ns=NS,
                      check_events=({"fact": str(check.id)},), fact_ancestors=r.agent._fact_ancestors)
    from sui.progress import INFINITE_WORK
    assert root.pending_work(str(attempt.id)) == {NS: F(1, 2), 2*NS: F(1, 2)}
    # Root >= permits the un-ingested equal-time atom; strict > wrongly gives {2s:1}.
    # The same original work draw survives; a future batch will consume the equal-time atom.
    result = plan(_view(r, NS, check=check), ["b"], u=.5).content.as_json()
    assert result["time"]["deadline_ns"] == 2*NS


def test_pending_gap_is_incomplete_not_an_invented_check():
    h = HandHistory()
    boot = h.boot()
    h.start("a", 0)
    r = _rig(model=_model(), history=h, H=NS)
    before = _same_state(r)
    with pytest.raises(IntegrationIncomplete, match="nonarrival at evaluation time"):
        plan(_view(r, NS, observed=0, check=boot), ["b"], u=.5)
    assert _same_state(r) == before


def test_known_duration_model5_is_not_replaced_by_finite_alpha_dp():
    model = GenerativeModel(states=("0", "1"), outcomes=("constant",), actions=("a",),
        a={"a": np.ones((1, 2))}, learnable=frozenset({"a"}), D=np.array([1., 0.]),
        Q=np.array([[-math.log(2), 0.], [math.log(2), 0.]]), log_C=np.array([0.]), gamma=1.,
        durations={"a": ((1., .5), (3., .5))}, measures={"a": "report"})
    r = _rig(model=model, H=NS)
    data = plan(_view(r), ["a"], u=.5).content.as_json()
    assert data["information"] == pytest.approx([0.], abs=ROUND)
    # Treating known (.5,.5) as a DP would award log(2)-1/2 > 0 for timing.
    assert math.log(2)-.5 > .19


@pytest.mark.parametrize("weights", [(1.,), (.5, .5), (.25, .25, .5)])
def test_exact_clock_candidate_cloning_does_not_award_label_information(weights):
    r = _rig(model=_model(measure=_exact(weights)), H=NS)
    result = plan(_view(r), ["a"], u=.5).content.as_json()
    # Timing I=log2-1/2. The learned-name report arrives with probability 1/2,
    # adding I((state,theta); Bernoulli(theta_state))=log2-1/2 on that branch.
    expected = 1.5*(math.log(2)-.5)
    _inside(result["information_bounds"][0], expected)
    assert r.agent._belief.body.content.as_json()["joint"]["measure_weights"] == list(weights)


@pytest.mark.parametrize("kind", ["speed", "tick", "units", "continuous"])
def test_valid_unrecognized_model_is_incomplete_and_decide_does_not_write(kind):
    changes = {}
    if kind == "speed":
        changes.update(speeds=(((1, 1), (1, 1)), ((1, 2), (1, 1))), weights=(F(1, 2), F(1, 2)))
    if kind == "tick":
        changes["measure"] = {"share": "all_actions", "candidates": [{"name": "tick", "version": "1",
            "params": {"width_ns": NS, "phase": "uniform", "check": "uniform_in_tick"}, "weight": 1.}]}
    if kind == "continuous":
        prior = DurationPrior(2., BaseSpec("piecewise", "1", {"edges_ns": [0, NS], "masses": [1.],
            "tail": {"kind": "pareto", "kappa": 1., "mass": 0.}, "p_inf": 0.}))
        changes["work"] = {"a": prior, "b": _prior((NS,), (1.,), 3.)}
    model = _model(**changes)
    if kind == "units":
        model = replace(model, completion=replace(model.completion, work_unit="byte", speed_unit="byte/ns"))
    encoded = model_json(model)
    assert model_json(model_from_json(encoded)) == encoded
    # Valid declaration and explicit pre-boot prior, even when evaluation is uncertified.
    empty = Agent(model=model, lineage="prior")
    assert empty._q == pytest.approx(model.D)
    r = _rig(model=model, H=NS)
    before = _same_state(r)
    with pytest.raises(IntegrationIncomplete):
        r.agent.decide(["a", "b"], u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    assert _same_state(r) == before
    assert not any(e.body_type is Decided for e in r.ledger.entries())


def test_unrecognized_candidate_is_not_dropped_before_policy():
    model = _model(speeds=(((1, 1), (1, 2)),), learned=False)
    r = _rig(model=model, H=NS)
    with pytest.raises(IntegrationIncomplete, match="stage1_speed"):
        plan(_view(r), ["a", "b"], u=.5)


@pytest.mark.parametrize("horizon", [0, NS])
def test_uniform_tick_zero_window_is_certified_and_positive_window_is_incomplete(horizon):
    model = _model(measure={"share": "all_actions", "candidates": [{"name": "tick", "version": "1",
        "params": {"width_ns": NS, "phase": "uniform", "check": "uniform_in_tick"}, "weight": 1.}]})
    r = _rig(model=model, H=horizon)
    if horizon:
        with pytest.raises(IntegrationIncomplete, match="hidden_time"):
            plan(_view(r), ["a", "b"], u=.5)
    else:
        data = plan(_view(r), ["a", "b"], u=.5).content.as_json()
        assert data["information"] == [0., 0.] and data["q_pi"] == [.5, .5]
        assert data["algorithm"]["name"] == "constant_empty_window"


@pytest.mark.parametrize("kind", ["infinite_work", "zero_speed"])
def test_one_step_checks_completion_law_permanent_nonarrival(kind):
    model = _model(work={"a": _prior((NS, None), (.5, .5), 2.), "b": _prior((NS,), (1.,), 3.)}) if kind == "infinite_work" else _model(speeds=(((0, 0), (1, 1)),))
    r = _rig(model=model, H=None)
    with pytest.raises(OutsideEvaluationType, match="every candidate"):
        plan(_view(r), ["a", "b"], u=.5)


def test_native_one_step_finite_exact_fixed_value():
    model = _model(learned=False)
    r = _rig(model=model, H=None)
    data = plan(_view(r), ["a"], u=.5).content.as_json()
    # R=1/2 equiprobable, I(F;R)=log2-1/2; state at own R has
    # entropy .5 H(.5)+.5 H(.75), and is exactly reported.
    H = lambda p: -p*math.log(p)-(1-p)*math.log1p(-p)
    expected = math.log(2)-.5 + .5*H(.5)+.5*H(.75)
    _inside(data["information_bounds"][0], expected)
    assert data["evaluation"] == "one_step" and data["H_ns"] is None


def test_zero_cost_informationless_is_softmax_not_argmax():
    r = _rig(model=_model(), H=0)
    data = plan(_view(r), ["a", "b"], u=.75).content.as_json()
    assert data["chosen"] == "b" and data["q_pi"] == [.5, .5]


@pytest.mark.parametrize("field", ["q", "n", "joint", "time"])
def test_restore_compares_every_summary_field_and_does_not_learn_from_it(field):
    r = _rig(model=_model(), H=NS)
    original = r.agent._belief
    data = original.body.content.as_json()
    if field == "q":
        data[field] = [.5, .5]
    elif field == "n":
        data[field]["a"][0] = 1
    elif field == "joint":
        data[field]["work_mean"]["a"] = [.75, .25]
    else:
        data[field]["anchor_ns"] = 1
    modified = replace(original, id=r.ids.new(K.PREDICTION), at=r.clock.now(),
                       body=replace(original.body, content=Payload.json(data)))
    entry = r.ledger.append(modified, r.agent.frontier)
    with pytest.raises((RebuildMismatch, ValueError)):
        Agent.restore(model=r.model, lineage="tampered", ledger=r.ledger, belief=entry.cid)


@pytest.mark.parametrize("field", ["expected_cost_bounds", "information_bounds", "J_bounds", "q_pi_bounds", "root", "algorithm", "u"])
def test_replay_checks_new_decision_fields(field):
    r = _rig(model=_model(), H=NS)
    prepared = r.agent.prepare(plan(_view(r), ["a", "b"], u=.5), clock=r.clock, ids=r.ids)
    data = prepared.decided.body.content.as_json()
    if field in ("root", "algorithm"):
        data[field]["wrong"] = True
    elif field == "u":
        data[field] = 0.
    else:
        data[field][0][0] += .01
    tampered = replace(prepared.decided, body=replace(prepared.decided.body, content=Payload.json(data)))
    entry = r.ledger.append(tampered, prepared.parents)
    with pytest.raises(RebuildMismatch):
        replay_decision(model=r.model, ledger=r.ledger, decision=entry.cid)


def test_prepare_commit_restore_and_replay_all_fields():
    r = _rig(model=_model(), H=2*NS)
    draft = plan(_view(r), ["a", "b"], u=.55)
    before = tuple(r.ledger.entries())
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    assert tuple(r.ledger.entries()) == before
    r.agent.commit(prepared, ledger=r.ledger)
    r.agent.commit(prepared, ledger=r.ledger)
    cid = r.ledger.entries_of(prepared.decided.id)[0].cid
    assert replay_decision(model=r.model, ledger=r.ledger, decision=cid) == draft
    r.ledger.verify()


def test_native_sqlite_save_reopen(tmp_path):
    r = _rig(model=_model(), H=NS)
    prepared = r.agent.prepare(plan(_view(r), ["a", "b"], u=.5), clock=r.clock, ids=r.ids)
    r.agent.commit(prepared, ledger=r.ledger)
    source = tmp_path/"source"
    from sui.ledger import Ledger, SequentialSalts
    with _storage(source) as store:
        ref = store.models.put(r.model)
        for entry in r.ledger.entries():
            salt, payload = r.ledger.contents.get(entry.seal)
            store.contents.put(entry.seal, salt, payload)
            store.entries.add(entry.cid, entry.header)
        ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        decision = ledger.entries_of(prepared.decided.id)[0].cid
        belief = ledger.entries_of(r.agent._belief.id)[0].cid
        assert model_ref(store.models.get(ref)) == ref
    from sui.store import SqliteStore
    with SqliteStore.open(source, readonly=True) as store:
        ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        restored_model = store.models.get(ref)
        subject = Agent.restore(model=restored_model, lineage="backup", ledger=ledger, belief=belief)
        assert subject._belief.body.content == r.agent._belief.body.content
        assert replay_decision(model=restored_model, ledger=ledger, decision=decision).content == prepared.decided.body.content


@pytest.mark.parametrize("unsupported", [False, True])
def test_fakeclock_think_provenance_success_and_incomplete_preserve_facts(unsupported):
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    model = _model(speeds=(((1, 2), (1, 1)),)) if unsupported else _model()
    r = _rig(model=model, H=NS)
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=("a", "b"), u=.5)] if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        hand=GatedHand({"a": set(), "b": set()}, {}), route="test", drive=drive,
        membrane=Producer(component="test.joint", code_version="1"), capacity={"think": 1}, pledges=pledges), clock=r.clock)
    host.advance(0)
    host.step()
    work = next(w for w, _ in host.work if isinstance(w, Think))
    assert work.view.check_events[0]["unrecorded"]["kind"] == "tick"
    assert list(work.view.check_events[0]["unrecorded"]["after"]) == sorted(work.view.frontier)
    event = host.finish(work)
    assert isinstance(event, Thought)
    if unsupported:
        assert event.error == "IntegrationIncomplete" and event.draft is None
    else:
        assert event.error is None and event.draft.contract == DECISION
    host.step()
    decisions = [e for e in r.ledger.entries() if e.body_type is Decided]
    assert bool(decisions) != unsupported
    if decisions:
        replay_decision(model=model, ledger=r.ledger, decision=decisions[0].cid)
    assert any(isinstance(e, Thought) for _, e in drive.calls)


@pytest.mark.parametrize("field", ["completion", "Q", "measure", "measures", "work_priors"])
def test_model7_roundtrip_preserves_every_world_declaration_and_unknown_versions_refuse(field):
    encoded = model_json(_model())
    value = json.loads(encoded)
    restored = model_from_json(encoded)
    assert model_json(restored) == encoded
    assert json.loads(model_json(restored))[field] == value[field]
    if field == "completion":
        value[field]["version"] = "999"
    elif field == "measure":
        value[field]["candidates"][0]["version"] = "999"
    elif field == "Q":
        value[field] = [[1.]]
    else:
        value[field] = None
    bad = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ValueError):
        model_from_json(bad)


def test_old_model6_q_json_remains_invalid_while_constructor_is_model7():
    from test_quantity import _quantity_model, _measure
    old = _quantity_model(measure=_exact())
    data = json.loads(model_json(old))
    data["Q"] = [[0.]]
    with pytest.raises(ValueError, match="outside model.6"):
        model_from_json(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    model = GenerativeModel(states=("0", "1"), outcomes=("0", "1"), actions=("a", "b"),
        a={"a": np.ones((2, 2)), "b": np.eye(2)}, learnable=frozenset({"a"}),
        D=np.array([1., 0.]), Q=np.array([[-1., 0.], [1., 0.]]), log_C=np.log([.5, .5]), gamma=1.,
        duration_priors={"a": _prior((NS, 2*NS), (.5, .5), 2.), "b": _prior((NS,), (1.,), 3.)}, measure=_exact())
    assert json.loads(model_json(model))["scheme"] == "sui.model.7"
    assert model_json(model_from_json(model_json(model))) == model_json(model)


def test_contract_registration_adds_new_meanings_without_replacing_old():
    from sui.s4b_contracts import DECLARATIONS as OLD
    from sui.contracts import ContractBook
    registry = ContractBook()
    for declaration in (*OLD, *DECLARATIONS):
        registry.register(declaration)
    for declaration in (*OLD, *DECLARATIONS):
        assert registry.get(declaration.ref) is declaration


def _static_model(*, work, states=("s",), fixed=False):
    model = _model(work=work, learned=not fixed)
    return replace(model, states=states, D=np.full(len(states), 1/len(states)), Q=None,
        a={"a": np.eye(2) if fixed else np.ones((2, 1)), "b": np.eye(2) if fixed else np.array([[1.], [0.]])},
        completion=replace(model.completion, states=states,
                           candidates=(tuple(tuple(1 for _ in states) for _ in model.actions),)))


def test_one_step_pending_z_uses_conditional_joint_information():
    h = HandHistory()
    h.boot()
    h.start("a", 0)
    check = _append_check(h, 0)
    model = _static_model(work={a: _prior((NS, 3*NS), (.5, .5), 2.) for a in ("a", "b")})
    r = _rig(model=model, history=h, H=None)
    data = plan(_view(r, check=check), ["a"], u=.5).content.as_json()
    # Future pending report updates both independent Beta(1,1) priors (F and
    # theta) once. The own report's conditional information is twice the
    # independent B_h/d_h reference .1365141682948128, not twice .19314718.
    _inside(data["information_bounds"][0], 2*.1365141682948128)


def test_one_step_pending_z_includes_reports_after_candidate_completion():
    h = HandHistory()
    h.boot()
    h.start("a", 0)
    check = _append_check(h, .5)
    model = _static_model(work={"a": _prior((3*NS,), (1.,), 2.), "b": _prior((NS,), (1.,), 3.)},
                          states=("0", "1"), fixed=True)
    r = _rig(model=model, history=h, H=None)
    data = plan(_view(r, NS//2, check=check), ["b"], u=.5).content.as_json()
    # Pending a reports the static state at 3; own b finishes at 1.5. Z already
    # determines that state even though its report is later: conditional I=0.
    assert data["information"] == pytest.approx([0.], abs=ROUND)


@pytest.mark.parametrize("H", [None, 0, NS])
def test_native_zero_work_is_safe_one_step_and_refused_only_for_lookahead(H):
    model = _static_model(work={"a": _prior((0,), (1.,), 2.), "b": _prior((NS,), (1.,), 3.)})
    r = _rig(model=model, H=H)
    if H is None:
        data = plan(_view(r), ["a"], u=.5).content.as_json()
        _inside(data["information_bounds"][0], math.log(2)-.5)
    else:
        with pytest.raises(OutsideEvaluationType, match="certain_zero_completion"):
            plan(_view(r), ["a"], u=.5)


def test_unexplained_joint_facts_do_not_keep_name_or_work_marginals():
    h = HandHistory()
    h.boot()
    a = h.start("a", 0)
    h.observe(a, "1", .5)  # Work law supports only 1 and 2 seconds.
    r = _rig(model=_model(), history=h, H=NS)
    summary = r.agent._belief.body.content.as_json()
    assert summary["q"] is None and summary["joint"]["status"] == "unexplained"
    assert summary["joint"]["theta_mean"] is None and summary["joint"]["work_mean"] is None
    assert summary["joint"]["components"] == 0
    before = _same_state(r)
    with pytest.raises(ModelFalsified):
        plan(_view(r, NS//2), ["a"], u=.5)
    assert _same_state(r) == before


def test_incomplete_belief_is_not_reported_as_zero_likelihood():
    r = _rig(model=_model(speeds=(((1, 2), (1, 1)),)), H=NS)
    assert r.agent._belief.body.content.as_json()["joint"]["status"] == "incomplete"
    with pytest.raises(IntegrationIncomplete, match="stage1_speed"):
        _ = r.agent.q


@pytest.mark.parametrize("entry", ["plan", "decide"])
def test_progress_does_not_fall_through_legacy_s4c_entry(entry):
    r = _rig(model=replace(_model(), Q=None), H=NS)
    before = _same_state(r)
    if entry == "plan":
        from sui.agent import plan_s4c
        with pytest.raises(ValueError, match="progress models"):
            plan_s4c(_view(r), ["a"], u=.5)
    else:
        with pytest.raises(ValueError, match="progress models"):
            r.agent.decide_s4c(["a"], u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    assert _same_state(r) == before


@pytest.mark.parametrize("measures", ["start", "report"])
def test_native_name_measuring_time_and_current_state_anchor_are_distinct(measures):
    h = HandHistory()
    h.boot()
    a = h.start("a", 0)
    h.observe(a, "0", 1)
    r = _rig(model=_model(learned=False, measures={"a": measures, "b": "report"}), history=h, H=NS)
    data = r.agent._belief.body.content.as_json()
    assert data["time"]["anchor_ns"] == NS
    expected = [.5, .5] if measures == "start" else [1., 0.]
    assert data["q"] == pytest.approx(expected, abs=ROUND)


def test_positive_tiny_summary_probability_raises_numerical_range():
    from sui.inference import NumericalRange
    model = _static_model(work={"a": _prior((NS,), (1.,), 2.), "b": _prior((NS,), (1.,), 3.)})
    model = replace(model, a={"a": np.array([[1e200], [1e-200]]), "b": np.array([[1.], [0.]])})
    with pytest.raises(NumericalRange, match="positive probability"):
        Agent(model=model, lineage="tiny")


def test_zero_window_positive_work_can_report_inside_the_same_tick():
    model = _model(measure={"share": "all_actions", "candidates": [{"name": "tick", "version": "1",
        "params": {"width_ns": 2*NS, "phase": "uniform", "check": "uniform_in_tick"}, "weight": 1.}]})
    r = _rig(model=model, H=0)
    with pytest.raises(IntegrationIncomplete, match="hidden_time"):
        plan(_view(r), ["a"], u=.5)
    # Independent single-attempt phase integral: for D=1 and width=2,
    # phase in [0,1) produces reading 0, with positive mass 1/2.
    assert F(2-1, 2) == F(1, 2)


def test_q_duration_tick_infinite_constructor_is_valid_but_public_lookahead_stops():
    model = GenerativeModel(states=("0", "1"), outcomes=("0", "1"), actions=("a", "b"),
        a={"a": np.ones((2, 2)), "b": np.eye(2)}, learnable=frozenset({"a"}),
        D=np.array([1., 0.]), Q=np.array([[-1., 0.], [1., 0.]]), log_C=np.log([.5, .5]), gamma=1.,
        duration_priors={"a": _prior((1, 3, None), (1/3, 1/3, 1/3), 3.),
                         "b": _prior((1, 3, None), (1/3, 1/3, 1/3), 3.)},
        measure={"share": "all_actions", "candidates": [{"name": "tick", "version": "1",
            "params": {"width_ns": 4, "phase": "uniform", "check": "uniform_in_tick"}, "weight": 1.}]})
    assert json.loads(model_json(model))["scheme"] == "sui.model.7"
    r = _rig(model=model, H=4)
    before = _same_state(r)
    with pytest.raises(IntegrationIncomplete, match="hidden_time"):
        r.agent.decide(["a", "b"], u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    assert _same_state(r) == before


def test_failed_accuracy_budget_does_not_write_a_decision(monkeypatch):
    from sui import joint_entry
    evaluate = joint_entry.evaluate
    def unfinished(*args, **kwargs):
        kwargs["node_budget"] = 1
        return evaluate(*args, **kwargs)
    monkeypatch.setattr(joint_entry, "evaluate", unfinished)
    r = _rig(model=_model(), H=2*NS)
    before = _same_state(r)
    with pytest.raises(IntegrationIncomplete):
        r.agent.decide(["a", "b"], u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    assert _same_state(r) == before


@pytest.mark.parametrize("measures", ["start", "report"])
def test_work_priors_with_explicit_name_times_use_model7_even_without_q(measures):
    from test_quantity import _quantity_model
    priors = {a: _prior((NS, 3*NS), (.5, .5), 2.) for a in ("a", "b")}
    model = _quantity_model(duration_priors=priors, measure=_exact(), measures={a: measures for a in ("a", "b")})
    assert model.Q is None and json.loads(model_json(model))["scheme"] == "sui.model.7"
    assert model_json(model_from_json(model_json(model))) == model_json(model)
    legacy = json.loads(model_json(_quantity_model(measure=_exact())))
    legacy["measures"] = {a: measures for a in ("a", "b")}
    with pytest.raises(ValueError, match="measures: durations are required"):
        model_from_json(json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode())
    r = _rig(model=model, H=None)
    result = plan(_view(r), ["a"], u=.5).content.as_json()
    _inside(result["information_bounds"][0], 2*(math.log(2)-.5))


def test_model7_declared_nonzero_q_is_preserved_without_roundtrip_self_reference():
    from sui.model import model_ref
    generator = [[-math.log(2), 0.], [math.log(2), 0.]]
    model = replace(_model(), Q=np.array(generator))
    encoded = model_json(model)
    assert json.loads(encoded)["Q"] == generator
    assert model_from_json(encoded).Q.tolist() == generator
    # Two explicitly different state laws must not receive the same reference.
    other = replace(model, Q=np.array([[-2*math.log(2), 0.], [2*math.log(2), 0.]]))
    assert model_ref(model) != model_ref(other)
