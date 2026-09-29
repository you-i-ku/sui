"""S3 v0.5 §6 の実行可能な約束。

read: P1・P2・P9 / plan: P3〜P9 / prepare・commit: P10・W12・K4
accept: W7〜W10・K8・K11 / settle・Pledges: W1〜W6・K1〜K14
drain: K3・K9・K13b・K14
窓口と同期の一致 (ManualHost 経由): R1
ThreadHost 本体: R2・R4〜R8・本体版 K9/K14 (test_k9_thread…・test_k14_thread…)
SQLite の接続スレッド制約: R3 / 手動ホストの封筒再配送: K11
全 rig の終了時に P8 (決定と ABANDON の再現) も検査する。
"""

import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, replace
import inspect
import sqlite3
from threading import Event, Thread, get_ident

import numpy as np
import pytest

from sui.agent import Agent, Reading, View, plan, read
from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.loop import run_step
from sui.records import AttemptStarted, Decided, JobOpened, Observed, Payload, Producer, Record, Role
from sui.runtime import (
    Abandon, Act, Arrived, Commit, Done, Envelope, Failed, Observe, Pledges,
    Reconsider, Start, Think, Thought, ThreadHost, Tick, Window,
)
from sui.s1_contracts import ACTION, ATTEMPT, DECISION, OUTCOME
from sui.s3_contracts import ABANDON, ENDED
from sui.store import StorageFull
from worlds import (
    CountingContents, CountingEntries, FlakyContents, FlakyEntries, GatedHand,
    ManualHost, ScriptDrive, ScriptedWorld, WriteCounts, _close, _model,
    _naive_conditional_G, _storage, _stored_rig,
)


CANDIDATES = ("look1", "look2", "wait")
TABLE1 = [
    ((), [1.012819438524806100, 1.018029641320821302, 1.098612288668109691],
     [.5812026171032507, .4164000495227957, .002397333373953704]),
    (("look2",), [1.016341271386427598, 1.028366149762041651, 1.098612288668109691],
     [.68102748161051, .31545323440966655, .0035192839798234158]),
    (("look1",), [1.029248518610511039, 1.021551474182442800, 1.098612288668109691],
     [.3775881881945581, .6179546024335422, .004457209371899682]),
    (("look2", "look2"), [1.019890403533181300, 1.036750089079967246, 1.098612288668109691],
     [.7427136400131825, .2524695594851749, .004816800501642504]),
    (("look1", "look2"), [1.031994337585916559, 1.031915281908795352, 1.098612288668109691],
     [.495259215950607270, .497771361141107448, .006969422908285281]),
]
TABLE2 = [
    ((), [.522073378901079435, .851522102653057252, 2.302585092994045684]),
    (("look1",), [.538502458986784374, .855043935514678750, 2.302585092994045684]),
    (("look2",), [.525595211762700934, .853202573608088595, 2.302585092994045684]),
]


def _reconsider(candidates=CANDIDATES, u=.40):
    return Reconsider(candidates=candidates, u=u)


def _on_tick(status, event):
    return (_reconsider(),) if isinstance(event, Tick) else ()


def _records(rig, kind, contract=None):
    records = [rig.ledger.record(e.cid) for e in rig.ledger.entries() if e.body_type is kind]
    return [r for r in records if contract is None or r.body.contract == contract]


def _entry(rig, record):
    return rig.ledger.entries_of(record.id)[0]


def _p8(rig):
    for record in _records(rig, Decided):
        entry = _entry(rig, record)
        facts = rig.ledger.snapshot(entry.parents).records
        if record.body.contract == DECISION:
            data = record.body.content.as_json()
            view = View(model=rig.model, frontier=entry.parents, belief=record.body.inputs[0],
                        reading=read(rig.model, facts))
            assert plan(view, data["candidates"], u=data["u"]).content == record.body.content
        elif record.body.contract == ABANDON:
            assert record.body.content.as_json() == {"job": str(record.body.inputs[0])}
            assert any(r.id == record.body.inputs[0] and isinstance(r.body, JobOpened) for r in facts)
    rig.ledger.verify()


@pytest.fixture
def rig_factory(tmp_path):
    rigs = []
    with ExitStack() as stack:
        def make(*, shared=False, capacity=None, drive=None, hand=None, threaded=False,
                 backend="memory", model=None):
            store = stack.enter_context(_storage(tmp_path / str(len(rigs)), backend))
            counts = WriteCounts()
            contents = FlakyContents(CountingContents(store.contents, counts))
            entries = FlakyEntries(CountingEntries(store.entries, counts))
            ledger = Ledger(salts=SequentialSalts(), contents=contents, entries=entries)
            rig = _stored_rig(store, ledger=ledger, model=model)
            rig.contents, rig.entries, rig.writes = contents, entries, counts
            names = {"look1": {"eye" if shared else "eye1"},
                     "look2": {"eye" if shared else "eye2"}, "wait": set()}
            rig.hand = hand if hand is not None else GatedHand(
                names, {"look1": ["o0"] * 20, "look2": ["o1"] * 20, "wait": ["none"] * 20})
            rig.drive = ScriptDrive(_on_tick) if drive is None else drive
            rig.capacity = ({"think": 1, **({"eye": 1} if shared else {"eye1": 1, "eye2": 1})}
                            if capacity is None else capacity)
            rig.windows = []

            def make_window(pledges):
                window = Window(agent=rig.agent, ledger=rig.ledger, clock=rig.clock, ids=rig.ids,
                                membrane=rig.membrane, route="executor", hand=rig.hand,
                                drive=rig.drive, capacity=rig.capacity, pledges=pledges)
                rig.windows.append(window)
                return window

            rig.make_window = make_window
            rig.host = ThreadHost(make_window) if threaded else ManualHost(make_window)
            rigs.append(rig)
            return rig

        yield make
        for rig in rigs:
            _p8(rig)


def _work(rig, kind):
    return [work for work, _ in rig.host.work if isinstance(work, kind)]


def _kick(rig):
    rig.host.advance(1)
    rig.host.step()
    return _work(rig, Think)[-1]


def _finish(rig, work):
    event = rig.host.finish(work)
    rig.host.step()
    return event


def _start_one(rig):
    _finish(rig, _kick(rig))
    return _work(rig, Act)[-1]


def _job(rig, act):
    return rig.ledger.record(rig.ledger.entries_of(act.attempt)[0].cid).body.job


def _status(rig):
    return rig.host.window.status()


def _counts(rig, action):
    return rig.agent.view().reading.n[action].tolist()


def _view(rig, pending, *, n=None):
    view = rig.agent.view()
    return replace(view, reading=Reading(
        n=view.reading.n if n is None else n, unread={},
        pending={Ref(K.JOB, f"p{i}"): action for i, action in enumerate(pending)}))


def _fact(rig, kind, body, *, model=False):
    return Record(id=rig.ids.new(kind), at=rig.clock.now(),
                  writer=Role.MODEL if model else Role.MEMBRANE,
                  producer=rig.agent.producer if model else rig.membrane, body=body)


def _raw_job(rig, action):
    return _fact(rig, K.JOB, JobOpened(decision=Ref(K.DECISION, "raw"), step=0,
                                     contract=ACTION, content=Payload.json({"action": action})), model=True)


def _raw_attempt(rig, job):
    return _fact(rig, K.ATTEMPT, AttemptStarted(job=job.id, contract=ATTEMPT, content=Payload.json({})))


def _raw_observed(rig, attempt, contract=OUTCOME):
    return _fact(rig, K.OBSERVATION, Observed(route="test", caused_by=attempt.id,
                 contract=contract, content=Payload.json(
                     {"error": "RuntimeError"} if contract == ENDED else {"outcome": "o0"})))


def test_p1_pending_is_a_set_function_including_jobs_without_attempts(rig_factory):
    r = rig_factory()
    jobs = [_raw_job(r, "look1") for _ in range(5)]
    attempts = [_raw_attempt(r, job) for job in jobs[1:]]
    facts = jobs + attempts + [_raw_job(r, "unknown")]
    facts += [_raw_observed(r, attempts[1]), _raw_observed(r, attempts[2], ENDED)]
    facts.append(_fact(r, K.DECISION, Decided(inputs=(jobs[4].id,), contract=ABANDON,
                      content=Payload.json({"job": str(jobs[4].id)})), model=True))
    # 形の違う ABANDON は先頭二つの進行中を消さない。
    facts.append(_fact(r, K.DECISION, Decided(inputs=(jobs[0].id,), contract=ABANDON,
                      content=Payload.json({"job": str(jobs[1].id)})), model=True))
    expected = {j.id: "look1" for j in jobs[:2]}
    for ordering in (facts, list(reversed(facts)), facts[::2] + facts[1::2]):
        assert dict(read(r.model, ordering).pending) == expected


def test_p2_unknown_observation_contract_still_ends_pending(rig_factory):
    r = rig_factory()
    j = _raw_job(r, "look1")
    t = _raw_attempt(r, j)
    o = _raw_observed(r, t, ContractRef("sui.s1.outcome", "unknown"))
    reading = read(r.model, [j, t, o])
    assert reading.pending == {}
    assert reading.unread == {o.id: "contract"}


@pytest.mark.parametrize("pending,G,q_pi", TABLE1)
def test_p3_table1(rig_factory, pending, G, q_pi):
    r = rig_factory()
    result = plan(_view(r, pending), CANDIDATES, u=.4).content.as_json()
    _close(result["G"], G)
    _close(result["q_pi"], q_pi)


@pytest.mark.parametrize("pending,G", TABLE2)
def test_p3_table2(rig_factory, pending, G):
    r = rig_factory(model=_model(learnable=frozenset({"look1"}), log_C=np.log([.6, .3, .1])))
    _close(plan(_view(r, pending), CANDIDATES, u=.4).content.as_json()["G"], G)


@pytest.mark.parametrize("action,outcome,G", [
    ("look1", 0, [1.036156698818779126, 1.031092660704761348, 1.098612288668109691]),
    ("look1", 1, [.986812554474007079, .962941328402486007, 1.098612288668109691]),
    ("look2", 0, [1.045615160886388285, 1.049290096156208627, 1.098612288668109691]),
    ("look2", 1, [.991404254404979606, 1.010542047278121634, 1.098612288668109691]),
])
def test_p3_table1b_after_one_observation(rig_factory, action, outcome, G):
    r = rig_factory()
    n = {name: counts.copy() for name, counts in r.agent.view().reading.n.items()}
    n[action][outcome] += 1
    _close(plan(_view(r, (), n=n), CANDIDATES, u=.4).content.as_json()["G"], G)


def test_p3b_each_component_is_averaged_separately(rig_factory):
    r = rig_factory()
    data = plan(_view(r, ("look1",)), CANDIDATES, u=.4).content.as_json()
    _close(data["risk"], [.710077883689876119, .412190363071331689, 1.098612288668109691])
    _close(data["ambiguity"], [.358328700875754082, .656340759843095602, 0])
    _close(data["novelty"], [.039158065955119161, .046979648731984491, 0])
    _close(data["q_o"], [[.86, .14, 0], [.46, .54, 0], [0, 0, 1]])


# Claude が S2b (864d5f3)、Python 3.12.10 で採取した content。
# 期待値は現在の plan/decide から生成せず、採取された数値をそのまま固定する。
@pytest.mark.parametrize("learnable,prior_actions,log_C,expected", [
    pytest.param(
        frozenset({"look1", "look2"}), (), None,
        {
            "G": [1.0128194385248064, 1.0180296413208214, 1.0986122886681098],
            "ambiguity": [0.361889394108298, 0.6563407598430956, 0.0],
            "candidates": ["look1", "look2", "wait"],
            "chosen": "look1", "gamma": 64.0,
            "novelty": [0.042718759187662596, 0.04697964873198439, 0.0],
            "q_o": [[0.8599999999999999, 0.14, 0.0],
                    [0.45999999999999996, 0.54, 0.0], [0.0, 0.0, 1.0]],
            "q_pi": [0.5812026171032576, 0.4164000495227888, 0.0023973333739536304],
            "risk": [0.6936488036041709, 0.4086685302097103, 1.0986122886681098],
            "u": 0.5,
        },
        id="both_learnable_n0_u05",
    ),
    pytest.param(
        frozenset({"look1", "look2"}), ("look1", "look2"), None,
        {
            "G": [1.021649444768642, 1.0266123498788098, 1.0986122886681098],
            "ambiguity": [0.34307341146198017, 0.6505719243639165, 0.0],
            "candidates": ["look1", "look2", "wait"],
            "chosen": "look1", "gamma": 64.0,
            "novelty": [0.038867062255630906, 0.04287351166550364, 0.0],
            "q_o": [[0.8727272727272727, 0.1272727272727273, 0.0],
                    [0.41818181818181815, 0.5818181818181818, 0.0], [0.0, 0.0, 1.0]],
            "q_pi": [0.5763246216416366, 0.41949229311147807, 0.004183085246885305],
            "risk": [0.7174430955622926, 0.4189139371803968, 1.0986122886681098],
            "u": 0.4,
        },
        id="both_learnable_after_look1_look2_u040",
    ),
    pytest.param(
        frozenset({"look1"}), ("look1",), np.log(np.array([.6, .3, .1])),
        {
            "G": [0.5260376883980071, 0.8532018902107547, 2.3025850929940455],
            "ambiguity": [0.3269833729961812, 0.6717480987478234, 0.0],
            "candidates": ["look1", "look2", "wait"],
            "chosen": "look1", "gamma": 64.0,
            "novelty": [0.03865742246092826, 0.0, 0.0],
            "q_o": [[0.8879492600422833, 0.11205073995771671, 0.0],
                    [0.47674418604651164, 0.5232558139534884, 0.0], [0.0, 0.0, 1.0]],
            "q_pi": [0.9999999991936546, 8.063454100107001e-10, 4.179621761443591e-50],
            "risk": [0.2377117378627542, 0.18145379146293128, 2.3025850929940455],
            "u": 0.9,
        },
        id="look1_learnable_nonuniformC_after_look1_u090",
    ),
])
def test_p4_no_pending_decision_content_matches_s2b_exactly(learnable, prior_actions, log_C, expected):
    model = _model(learnable=learnable, **({} if log_C is None else {"log_C": log_C}))
    subject = Agent(model=model, lineage="p4")
    clock = FakeClock(run=Ref(K.RUN, "p4"))
    ids = SequentialIds()
    ledger = Ledger(salts=SequentialSalts())
    membrane = Producer(component="p4.executor", code_version="1")
    world = ScriptedWorld({"look1": ["o0", "o1"], "look2": ["o1", "o0"], "wait": ["none"] * 3})
    subject.belief_record(clock=clock, ids=ids, ledger=ledger)
    for action in prior_actions:
        run_step(subject, world, [action], u=.5, clock=clock, ids=ids,
                 ledger=ledger, membrane=membrane)
    decided, _ = subject.decide(["wait", "look2", "look1"], u=expected["u"],
                                clock=clock, ids=ids, ledger=ledger)
    content = decided.body.content.as_json()
    assert content.pop("pending") == []
    assert content == expected


def test_p5_pending_ref_order_does_not_change_G(rig_factory):
    r = rig_factory()
    a = plan(_view(r, ("look1", "look2")), CANDIDATES, u=.4).content.as_json()
    b = plan(_view(r, ("look2", "look1")), CANDIDATES, u=.4).content.as_json()
    _close(a["G"], b["G"])
    assert a["pending"] != b["pending"]


@pytest.mark.parametrize("variant", [1, 2])
@pytest.mark.parametrize("pending", [("look1",), ("look2",), ("look2", "look2"),
                                    ("look1", "look2"), ("look1", "look2", "look2")])
def test_p6_joint_information_formula_is_an_independent_path(rig_factory, variant, pending):
    model = (_model(learnable=frozenset({"look1", "look2"})) if variant == 1 else
             _model(learnable=frozenset({"look1"}), log_C=np.log([.6, .3, .1])))
    r = rig_factory(model=model)
    actual = plan(_view(r, pending), CANDIDATES, u=.4).content.as_json()["G"]
    _close(actual, _naive_conditional_G(model, pending))


def test_p7_weights_are_predictive_not_uniform(rig_factory):
    r = rig_factory()
    wrong = []
    for outcome in (0, 1):
        n = {name: counts.copy() for name, counts in r.agent.view().reading.n.items()}
        n["look2"][outcome] += 1
        wrong.append(plan(_view(r, (), n=n), CANDIDATES, u=.4).content.as_json()["G"])
    actual = plan(_view(r, ("look2",)), CANDIDATES, u=.4).content.as_json()["G"]
    assert np.max(np.abs(np.mean(wrong, axis=0) - actual)) > 1e-6


def test_p9_immutable_reading_view_draft_and_status(rig_factory):
    r = rig_factory()
    view = _view(r, ("look1",))
    with pytest.raises(TypeError):
        view.reading.pending[Ref(K.JOB, "new")] = "look2"
    with pytest.raises(FrozenInstanceError):
        view.reading = read(r.model, ())
    draft = plan(view, CANDIDATES, u=.4)
    with pytest.raises(FrozenInstanceError):
        draft.content.data = b"changed"
    copy = draft.content.as_json()
    copy["pending"].clear()
    assert len(draft.content.as_json()["pending"]) == 1
    r.host.step()
    status = _status(r)
    with pytest.raises(TypeError):
        status.used["think"] = 100
    with pytest.raises(TypeError):
        status.capacity["think"] = 100
    assert not hasattr(status, "mono_ns")


def test_p10_prepare_commit_validation_and_idempotence(rig_factory):
    r = rig_factory()
    draft = plan(r.agent.view(), CANDIDATES, u=.4)
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    before = r.ledger.entries()
    leaf = _entry(r, r.belief).cid
    for parents in (frozenset({"sha256:" + "0" * 64}), frozenset({leaf})):
        with pytest.raises(ValueError):
            r.agent.commit(replace(prepared, parents=parents), ledger=r.ledger)
        assert r.ledger.entries() == before
    extra = _raw_job(r, "look1")
    r.ledger.append(extra, ())
    before = r.ledger.entries()
    with pytest.raises(ValueError):
        r.agent.commit(replace(prepared, parents=r.ledger.heads()), ledger=r.ledger)
    assert r.ledger.entries() == before
    state = (r.agent.frontier, r.agent._belief)
    r.agent.commit(prepared, ledger=r.ledger)
    committed = r.ledger.entries()
    r.agent.commit(prepared, ledger=r.ledger)
    assert r.ledger.entries() == committed
    assert (r.agent.frontier, r.agent._belief) == state


def test_w1_a_waits_while_b_completes_a_whole_cycle(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    assert a.action == "look1"
    assert _status(r).awaiting == (a.attempt,)
    b = _start_one(r)
    assert b.action == "look2"
    assert set(_status(r).awaiting) == {a.attempt, b.attempt}
    decisions = _records(r, Decided, DECISION)
    first, second = decisions
    assert first.body.content.as_json()["pending"] == []
    assert second.body.content.as_json()["pending"] == [{"job": str(_job(r, a)), "action": "look1"}]
    assert r.ledger.entries_of(a.attempt)[0].cid in r.ledger.ancestors(_entry(r, second).parents)
    _finish(r, b)
    assert _counts(r, "look2") == [0, 1, 0]
    assert _counts(r, "look1") == [0, 0, 0]
    assert _status(r).awaiting == (a.attempt,)
    _finish(r, a)
    assert _counts(r, "look1") == [1, 0, 0]
    assert _counts(r, "look2") == [0, 1, 0]
    assert _status(r).awaiting == ()


def test_w1_main_scenario_does_not_bypass_the_drive():
    tree = ast.parse(inspect.getsource(test_w1_a_waits_while_b_completes_a_whole_cycle))
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not {getattr(call, "id", getattr(call, "attr", None)) for call in calls} & {
        "decide", "plan", "prepare", "commit"}


@pytest.mark.parametrize("slots", [1, 2])
def test_w2_think_capacity_and_exact_drive_notice_count(rig_factory, slots):
    drive = ScriptDrive(lambda s, e: [_reconsider()] * 3 if isinstance(e, Tick) else ())
    r = rig_factory(drive=drive, capacity={"think": slots, "eye1": 3, "eye2": 3})
    _kick(r)
    maximum = _status(r).thinking
    assert maximum == slots and _status(r).waiting == 3 - slots
    while _work(r, Think):
        _finish(r, _work(r, Think)[0])
        maximum = max(maximum, _status(r).thinking)
    assert maximum == slots and _status(r).waiting == 0
    assert len(drive.calls) == 4  # Tick と三つの有効な Thought だけ。
    assert len(_records(r, Decided, DECISION)) == 3


def test_w3_no_limit_of_two_decisions(rig_factory):
    def rule(s, e):
        return [_reconsider()] if (isinstance(e, Tick) or
                isinstance(e, Thought) and len(s.awaiting) < 3) else []
    r = rig_factory(drive=ScriptDrive(rule), capacity={"think": 1, "eye1": 3, "eye2": 3})
    _kick(r)
    for _ in range(3):
        _finish(r, _work(r, Think)[0])
    assert len(_status(r).awaiting) == 3
    assert len(_work(r, Act)) == 3 and not _work(r, Think)


def test_w4_hand_capacity_queues_until_actual_result(rig_factory):
    r = rig_factory(shared=True)
    a = _start_one(r)
    _finish(r, _kick(r))
    bjob = _status(r).queued[0]
    assert len(_records(r, AttemptStarted)) == 1
    assert _status(r).used["eye"] == 1
    _finish(r, a)
    b = _work(r, Act)[0]
    assert _job(r, b) == bjob and b.action == "look2"
    assert _status(r).used["eye"] == 1 and not _status(r).queued
    _finish(r, b)
    assert _status(r).used["eye"] == 0
    assert max(s.used["eye"] for s, _ in r.drive.calls) == 1


def test_w4b_scan_past_blocked_queue_head(rig_factory):
    script = iter([("look1",), ("look1",), ("look2",)])
    drive = ScriptDrive(lambda s, e: [_reconsider(next(script))] if isinstance(e, Tick) else ())
    r = rig_factory(drive=drive)
    a = _start_one(r)
    _finish(r, _kick(r))
    blocked = _status(r).queued
    _finish(r, _kick(r))
    assert _status(r).queued == blocked
    assert [w.action for w in _work(r, Act)] == ["look1", "look2"]
    assert a.attempt in _status(r).awaiting


def test_w4c_only_one_of_two_queued_jobs_starts_when_shared_resource_is_freed(rig_factory):
    script = iter([("look1",), ("look2",), ("look1",)])
    drive = ScriptDrive(lambda s, e: [_reconsider(next(script))] if isinstance(e, Tick) else ())
    r = rig_factory(shared=True, drive=drive)
    a = _start_one(r)
    assert a.action == "look1"
    _finish(r, _kick(r))
    bjob = _status(r).queued[0]
    _finish(r, _kick(r))
    b_queued, cjob = _status(r).queued
    assert b_queued == bjob
    assert _status(r).awaiting == (a.attempt,) and _status(r).used["eye"] == 1
    assert _work(r, Act) == [a] and len(_records(r, AttemptStarted)) == 1

    _finish(r, a)
    assert len(_work(r, Act)) == 1
    b = _work(r, Act)[0]
    assert _job(r, b) == bjob and b.action == "look2"
    assert _status(r).queued == (cjob,)
    assert _status(r).awaiting == (b.attempt,) and _status(r).used["eye"] == 1
    assert len(_records(r, AttemptStarted)) == 2

    _finish(r, b)
    assert len(_work(r, Act)) == 1
    c = _work(r, Act)[0]
    assert _job(r, c) == cjob and c.action == "look1"
    assert _status(r).queued == ()
    assert _status(r).awaiting == (c.attempt,) and _status(r).used["eye"] == 1
    assert len(_records(r, AttemptStarted)) == 3
    _finish(r, c)
    assert not _work(r, Act) and not _status(r).awaiting
    assert _status(r).used["eye"] == 0
    assert max(status.used["eye"] for status, _ in drive.calls) == 1
    assert r.hand.calls == ["look1", "look2", "look1"]


def test_w5_queued_pending_and_late_thought_keep_original_decisions(rig_factory):
    r = rig_factory(shared=True)
    a = _start_one(r)
    _finish(r, _kick(r))
    bjob = _status(r).queued[0]
    c = _kick(r)  # C はまだ確定しない。V29 を識別する順番。
    assert dict(c.view.reading.pending) == {_job(r, a): "look1", bjob: "look2"}
    _finish(r, a)
    b = _work(r, Act)[0]
    assert b.action == "look2" and _job(r, b) == bjob
    observation = _records(r, Observed)[0]
    bdecision = next(d for d in _records(r, Decided, DECISION)
                     if d.id == r.ledger.record(r.ledger.entries_of(bjob)[0].cid).body.decision)
    assert _entry(r, observation).cid not in r.ledger.ancestors(_entry(r, bdecision).parents)
    _finish(r, c)
    decision = next(d for d in _records(r, Decided, DECISION) if d.body.inputs == (c.view.belief,))
    assert _entry(r, decision).parents == c.view.frontier
    assert len(decision.body.content.as_json()["pending"]) == 2
    _close(decision.body.content.as_json()["G"], TABLE1[-1][1])


def test_w6_abandon_releases_prediction_but_not_the_hand(rig_factory):
    r = rig_factory(shared=True)
    r.hand._script["look1"] = ["o1"] * 20
    a = _start_one(r)
    ajob = _job(r, a)
    r.drive.rules = (lambda s, e: [Abandon(job=ajob), _reconsider()] if isinstance(e, Tick) else (),)
    thinking = _kick(r)
    assert ajob not in _status(r).pending and a.attempt in _status(r).awaiting
    assert _status(r).used["eye"] == 1
    assert thinking.view.reading.pending == {}
    _finish(r, thinking)
    second = _records(r, Decided, DECISION)[-1]
    _close(second.body.content.as_json()["G"], TABLE1[0][1])
    assert _status(r).queued and len(_work(r, Act)) == 1
    _finish(r, a)
    assert _counts(r, "look1") == [0, 1, 0]
    assert len(_work(r, Act)) == 1 and _status(r).used["eye"] == 1


def test_w6b_abandon_immediately_after_start_adopts_first(rig_factory):
    def rule(s, e):
        if isinstance(e, Tick):
            return [_reconsider()]
        return [Abandon(job=s.pending[0])] if isinstance(e, Thought) else []
    r = rig_factory(drive=ScriptDrive(rule))
    a = _start_one(r)
    assert len(_records(r, Decided, ABANDON)) == 1
    assert _status(r).pending == () and _status(r).awaiting == (a.attempt,)


def test_w6c_abandoned_queued_job_still_starts(rig_factory):
    r = rig_factory(shared=True)
    a = _start_one(r)
    _finish(r, _kick(r))
    bjob = _status(r).queued[0]
    r.drive.rules = (lambda s, e: [Abandon(job=bjob)] if isinstance(e, Tick) else (),)
    r.host.advance(1)
    r.host.step()
    assert bjob not in _status(r).pending and bjob in _status(r).queued
    _finish(r, a)
    assert _job(r, _work(r, Act)[0]) == bjob


def test_w7_failed_hand_records_ended_without_learning(rig_factory):
    r = rig_factory()
    r.hand._script["look1"] = [RuntimeError("do not store this message")]
    a = _start_one(r)
    event = _finish(r, a)
    assert event == Failed(attempt=a.attempt, error="RuntimeError")
    ended = _records(r, Observed, ENDED)[0]
    assert ended.body.content.as_json() == {"error": "RuntimeError"}
    assert ended.body.caused_by == a.attempt and ended.body.route == "executor"
    assert dict(r.agent.unread) == {ended.id: "contract"}
    assert not _status(r).pending and not _status(r).awaiting
    assert _status(r).used["eye1"] == 0
    assert _counts(r, "look1") == [0, 0, 0]


def test_w8_duplicate_and_unknown_worker_results_do_not_notify_drive(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider()]
                                    if isinstance(e, (Tick, Done)) else []))
    thought = _finish(r, _kick(r))
    a = _work(r, Act)[0]
    calls = len(r.drive.calls)
    r.host.post(thought)
    r.host.post(Thought(work="think:unknown", error="ValueError"))
    r.host.post(Done(attempt=Ref(K.ATTEMPT, "unknown"), outcome="o0"))
    for _ in range(3):
        r.host.step()
    assert len(r.drive.calls) == calls
    assert len(_records(r, Decided, DECISION)) == len(_records(r, JobOpened)) == 1
    assert len(_records(r, AttemptStarted)) == len(_work(r, Act)) == 1
    _finish(r, a)
    issued, calls = r.host.pledges.issued, len(r.drive.calls)
    r.host.post(Done(attempt=a.attempt, outcome="o1"))
    r.host.post(Failed(attempt=a.attempt, error="RuntimeError"))
    r.host.step()
    r.host.step()
    assert len(_records(r, Observed)) == 1
    assert _records(r, Observed)[0].body.content.as_json() == {"outcome": "o0"}
    assert r.host.pledges.issued == issued and len(r.drive.calls) == calls


def test_w8_abandon_twice_only_writes_once(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    r.drive.rules = (lambda s, e: [Abandon(job=_job(r, a))] * 2 if isinstance(e, Tick) else [],)
    r.host.advance(1)
    r.host.step()
    assert len(_records(r, Decided, ABANDON)) == 1


def test_w9_arrived_never_becomes_an_awaited_result(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    event = Arrived(route="external", content=Payload.json({"outcome": "o1"}),
                    contract=OUTCOME, source_id="source1")
    r.host.post(event)
    r.host.step()
    observed = _records(r, Observed)[0]
    assert observed.body.caused_by is None and observed.body.source_id == "source1"
    assert observed.body.route == "external"
    assert dict(r.agent.unread) == {observed.id: "no_attempt"}
    assert _counts(r, "look1") == [0, 0, 0]
    assert a.attempt in _status(r).awaiting and _job(r, a) in _status(r).pending


def test_w10_failed_thought_returns_slot_and_payload_is_exclusive(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider(("unknown",))]
                                    if isinstance(e, Tick) else []))
    thought = _finish(r, _kick(r))
    assert thought.error == "ValueError" and thought.draft is None
    assert _status(r).thinking == 0 and not _records(r, Decided)
    with pytest.raises(ValueError):
        Thought(work="x")
    with pytest.raises(ValueError):
        Thought(work="x", draft=plan(r.agent.view(), CANDIDATES, u=.4), error="ValueError")


def test_w11_all_writes_are_serial_on_window_thread(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    b = _start_one(r)
    _finish(r, b)
    _finish(r, a)
    assert set(r.writes.threads) == {get_ident()} and r.writes.maximum == 1


def test_w12_late_commit_parents_are_the_think_frontier(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    b = _kick(r)
    _finish(r, a)
    observed = _records(r, Observed)[0]
    assert _entry(r, observed).cid in r.ledger.ancestors(r.agent.frontier)
    _finish(r, b)
    decision = next(d for d in _records(r, Decided, DECISION) if d.body.inputs == (b.view.belief,))
    assert _entry(r, decision).parents == b.view.frontier
    assert _entry(r, observed).cid not in r.ledger.ancestors(_entry(r, decision).parents)


class DriveFailure(RuntimeError):
    pass


def _fail_once(event_type, *, replies=()):
    failed = False

    def rule(status, event):
        nonlocal failed
        if isinstance(event, event_type):
            yield from replies
            if not failed:
                failed = True
                raise DriveFailure("injected drive failure")
    return rule


def _shared_pair(rig_factory, **kwargs):
    r = rig_factory(shared=True, **kwargs)
    a = _start_one(r)
    _finish(r, _kick(r))
    assert len(_status(r).queued) == 1
    return r, a, _status(r).queued[0]


def _assert_saved(r, record):
    entries = r.ledger.entries_of(record.id)
    assert len(entries) == 1
    assert r.ledger.record(entries[0].cid) == record


def _successes(r, kind):
    return [item for item in r.drive.successes if isinstance(item[1], kind)]


def test_k1_partial_drive_reply_is_not_accepted(rig_factory):
    r = rig_factory(drive=ScriptDrive(_fail_once(Tick, replies=(_reconsider(),))))
    r.host.advance(1)
    with pytest.raises(DriveFailure):
        r.host.step()
    assert r.host.window is None
    assert not r.host.pledges.requests and not r.host.pledges.waiting
    assert r.host.current is None and len(r.host.pledges.notices) == 1
    r.host.step()
    assert len(r.windows) == 2
    assert len(_work(r, Think)) == 1
    assert len(_successes(r, Tick)) == 1 and len(r.drive.calls) == 2
    assert len(_successes(r, Tick)[0][2]) == 1


@pytest.mark.parametrize("store_name", ["contents", "entries"])
def test_k2_recovered_observation_frees_resource_in_same_settle(rig_factory, store_name):
    r, a, bjob = _shared_pair(rig_factory)
    getattr(r, store_name).fail_next()
    r.host.finish(a)
    with pytest.raises(StorageFull):
        r.host.step()
    item = r.host.pledges.items[0]
    assert isinstance(item, Observe)
    saved = item.record
    assert not r.ledger.entries_of(saved.id)
    r.host.step()
    _assert_saved(r, saved)
    assert len(_records(r, Observed)) == 1
    assert _job(r, _work(r, Act)[0]) == bjob
    assert _status(r).used["eye"] == 1 and not _status(r).queued
    assert len(_successes(r, Done)) == 1


def test_k2b_recovered_start_borrows_resource_and_sends_act_once(rig_factory):
    r, a, bjob = _shared_pair(rig_factory)
    r.entries.fail_next(3)  # 観測・信念の後の B の試み。
    r.host.finish(a)
    with pytest.raises(StorageFull):
        r.host.step()
    item = r.host.pledges.items[0]
    assert isinstance(item, Start) and item.job == bjob
    r.host.step()
    _assert_saved(r, item.attempt)
    assert len([w for w in r.host.started if isinstance(w, Act) and w.attempt == item.act.attempt]) == 1
    assert _status(r).used["eye"] == 1
    assert len(_records(r, AttemptStarted)) == 2


def test_k3_failure_after_start_preserves_act_and_original_commit(rig_factory):
    r = rig_factory(drive=ScriptDrive(_on_tick, _fail_once(Thought)))
    think = _kick(r)
    r.host.finish(think)
    with pytest.raises(DriveFailure):
        r.host.step()
    assert r.host.window is None and len(_work(r, Act)) == 1
    before = [r_.id for kind in (Decided, JobOpened, AttemptStarted) for r_ in _records(r, kind)]
    r.host.step()
    assert [r_.id for kind in (Decided, JobOpened, AttemptStarted) for r_ in _records(r, kind)] == before
    assert len(_work(r, Act)) == 1 and len(_successes(r, Thought)) == 1


class CountingIds:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []
        self.fail_kind = None

    def new(self, kind):
        self.calls.append(kind)
        if kind == self.fail_kind:
            self.fail_kind = None
            raise RuntimeError("injected ID failure")
        return self.delegate.new(kind)


def test_k4_half_written_commit_reuses_both_records(rig_factory):
    r = rig_factory()
    r.ids = CountingIds(r.ids)
    think = _kick(r)
    r.entries.fail_next(2)
    r.host.finish(think)
    with pytest.raises(StorageFull):
        r.host.step()
    item = r.host.pledges.items[0]
    assert isinstance(item, Commit)
    _assert_saved(r, item.commit.decided)
    assert not r.ledger.entries_of(item.commit.job.id)
    assert think.work in r.host.pledges.thinking
    r.host.step()
    _assert_saved(r, item.commit.decided)
    _assert_saved(r, item.commit.job)
    assert r.ids.calls.count(K.DECISION) == r.ids.calls.count(K.JOB) == 1
    assert len(_records(r, Decided, DECISION)) == len(_records(r, JobOpened)) == 1
    assert len(_work(r, Act)) == 1


def test_k5_observation_written_adoption_failed_notice_gets_new_frontier(rig_factory):
    r, a, bjob = _shared_pair(rig_factory)
    r.contents.fail_next(2)
    r.host.finish(a)
    with pytest.raises(StorageFull):
        r.host.step()
    observation = _records(r, Observed)[0]
    assert _entry(r, observation).cid not in r.ledger.ancestors(r.agent.frontier)
    assert not r.host.pledges.items and len(r.host.pledges.notices) == 1
    r.host.step()
    assert _job(r, _work(r, Act)[0]) == bjob
    notices = _successes(r, Done)
    assert len(notices) == 1
    assert _entry(r, observation).cid in r.ledger.ancestors(notices[0][0].frontier)
    assert _counts(r, "look1") == [1, 0, 0]


def test_k6_waiting_reconsider_requests_survive_reconstruction(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider()] * 3 if isinstance(e, Tick) else []),
                    capacity={"think": 1, "eye1": 3, "eye2": 3})
    first = _kick(r)
    assert _status(r).waiting == 2
    r.drive.rules = (_fail_once(Tick),)
    r.host.advance(1)
    with pytest.raises(DriveFailure):
        r.host.step()
    p = r.host.pledges
    r.host.step()
    assert r.host.pledges is p and _status(r).waiting == 2
    _finish(r, first)
    assert _status(r).waiting == 1
    _finish(r, _work(r, Think)[0])
    assert _status(r).waiting == 0 and _status(r).thinking == 1
    _finish(r, _work(r, Think)[0])
    assert len(_records(r, Decided, DECISION)) == 3


def test_k6b_waiting_head_is_retained_when_adoption_before_think_fails(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider()] * 2 if isinstance(e, Tick) else []))
    think = _kick(r)
    r.entries.fail_next(4)  # 決定・仕事・試みの後、次の Think の前の信念。
    r.host.finish(think)
    with pytest.raises(StorageFull):
        r.host.step()
    assert len(r.host.pledges.waiting) == 1 and r.host.pledges.issued == 1
    r.host.step()
    assert len(_work(r, Think)) == 1 and _work(r, Think)[0].work == "think:2"
    assert not r.host.pledges.waiting


def test_k7_failed_abandon_retains_record_and_remaining_request(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    ajob = _job(r, a)
    r.drive.rules = (lambda s, e: [Abandon(job=ajob), _reconsider()] if isinstance(e, Tick) else [],)
    r.entries.fail_next(2)  # ABANDON の判定前の adopt、ABANDON。
    r.host.advance(1)
    with pytest.raises(StorageFull):
        r.host.step()
    saved = r.host.pledges.abandons[ajob]
    assert len(r.host.pledges.requests) == 2
    r.host.step()
    _assert_saved(r, saved)
    assert len(_records(r, Decided, ABANDON)) == 1 and len(_work(r, Think)) == 1
    assert r.host.pledges.issued == 2
    assert not r.host.pledges.requests and not r.host.pledges.abandons
    assert _status(r).used["eye1"] == 1


@pytest.mark.parametrize("fail_adoption", [False, True])
def test_k7b_written_abandon_is_removed_from_pledges_after_recovery(
        rig_factory, monkeypatch, fail_adoption):
    r = rig_factory()
    a = _start_one(r)
    ajob = _job(r, a)
    request = Abandon(job=ajob)
    r.drive.rules = (lambda s, e: [request] if isinstance(e, Tick) else [],)
    ordinary_append = r.ledger.append
    written = []

    def append_then_fail(record, parents):
        entry = ordinary_append(record, parents)
        if isinstance(record.body, Decided) and record.body.contract == ABANDON and not written:
            written.append(record)
            raise RuntimeError("injected after ABANDON append")
        return entry

    monkeypatch.setattr(r.ledger, "append", append_then_fail)
    r.host.advance(1)
    with pytest.raises(RuntimeError, match="injected after ABANDON append"):
        r.host.step()
    p = r.host.pledges
    saved = p.abandons[ajob]
    assert written == [saved]
    _assert_saved(r, saved)
    assert len(_records(r, Decided, ABANDON)) == 1
    assert r.host.window is None and p.requests == [request]

    if fail_adoption:
        # 復旧時の採用が失敗した場合も、預かった記録と依頼を先に外さない。
        r.contents.fail_next()
        with pytest.raises(StorageFull):
            r.host.step()
        assert r.host.window is None and r.host.pledges is p
        assert p.abandons[ajob] is saved and p.requests == [request]

    r.host.step()
    assert r.host.pledges is p
    assert not p.abandons and not p.requests
    _assert_saved(r, saved)
    assert len(_records(r, Decided, ABANDON)) == 1
    assert ajob not in _status(r).pending
    assert _status(r).awaiting == (a.attempt,) and _status(r).used["eye1"] == 1
    assert _work(r, Act) == [a] and len(_records(r, AttemptStarted)) == 1


def _external():
    return Arrived(route="outside", contract=OUTCOME, content=Payload.json({"outcome": "o1"}))


def test_k8_arrived_settled_once_per_receipt_even_after_drive_failure(rig_factory):
    r = rig_factory(drive=ScriptDrive(_fail_once(Arrived, replies=(_reconsider(),))))
    event = _external()
    r.host.post(event)
    with pytest.raises(DriveFailure):
        r.host.step()
    r.host.step()
    assert len(_records(r, Observed)) == len(_successes(r, Arrived)) == 1
    assert len(_work(r, Think)) == 1
    r.host.post(event)
    r.host.step()
    assert len(_records(r, Observed)) == len(_successes(r, Arrived)) == 2
    assert _status(r).waiting == 1  # 同じ中身でも別の受け取り。


def test_k8b_arrived_record_is_not_recreated_after_failed_write(rig_factory):
    r = rig_factory()
    r.contents.fail_next()
    r.host.post(_external())
    with pytest.raises(StorageFull):
        r.host.step()
    saved = r.host.pledges.items[0].record
    r.host.step()
    _assert_saved(r, saved)
    assert len(_records(r, Observed)) == len(_successes(r, Arrived)) == 1


def test_k9_start_failure_keeps_only_unstarted_work(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider()] * 2 if isinstance(e, Tick) else []),
                    capacity={"think": 2, "eye1": 2, "eye2": 2})
    ordinary_start = r.host.start
    attempts = []

    def start(work, hand):
        attempts.append(work.work)
        if len(attempts) == 2:
            raise RuntimeError("start failed")
        ordinary_start(work, hand)

    r.host.start = start
    r.host.advance(1)
    with pytest.raises(RuntimeError):
        r.host.step()
    window = r.host.window
    assert window is not None
    assert len(r.host.unstarted) == 1 and len(_work(r, Think)) == 1
    r.host.step()
    assert r.host.window is window
    assert attempts == ["think:1", "think:2", "think:2"]
    assert [w.work for w in _work(r, Think)] == ["think:1", "think:2"]


def test_k10_think_numbers_survive_reconstruction_and_late_duplicate(rig_factory):
    r = rig_factory(drive=ScriptDrive(lambda s, e: [_reconsider()] * 2 if isinstance(e, Tick) else []),
                    capacity={"think": 2, "eye1": 2, "eye2": 2})
    _kick(r)
    late = _finish(r, _work(r, Think)[1])
    assert set(r.host.pledges.thinking) == {"think:1"}
    r.drive.rules = (_fail_once(Tick, replies=(_reconsider(),)),)
    r.host.advance(1)
    with pytest.raises(DriveFailure):
        r.host.step()
    r.host.step()
    assert set(r.host.pledges.thinking) == {"think:1", "think:3"}
    before = r.ledger.entries(), len(r.drive.calls)
    r.host.post(late)
    r.host.step()
    assert (r.ledger.entries(), len(r.drive.calls)) == before


@pytest.mark.parametrize("phase", ["accept", "settle"])
def test_k11_failed_envelope_keeps_queue_order(rig_factory, phase):
    r = rig_factory()
    r.ids = CountingIds(r.ids)
    a = _start_one(r)
    if phase == "accept":
        r.ids.fail_kind = K.OBSERVATION
    else:
        r.contents.fail_next()
    first = r.host.finish(a)
    second = _external()
    r.host.post(second)
    with pytest.raises((RuntimeError, StorageFull)):
        r.host.step()
    assert r.host.queue[0].event is second
    if phase == "accept":
        assert r.host.current.event is first
        assert not r.host.pledges.items and not r.host.pledges.notices
    else:
        assert r.host.current is None
    r.host.step()
    r.host.step()
    observations = sorted(_records(r, Observed), key=lambda record: record.at.seq)
    assert [o.body.caused_by for o in observations] == [a.attempt, None]
    assert len(_successes(r, Done)) == len(_successes(r, Arrived)) == 1


def test_k12_reconstruction_borrows_outstanding_resources(rig_factory):
    r = rig_factory()
    a = _start_one(r)
    r.drive.rules = (_fail_once(Tick),)
    r.host.advance(1)
    with pytest.raises(DriveFailure):
        r.host.step()
    r.host.step()
    assert _status(r).awaiting == (a.attempt,) and _status(r).used["eye1"] == 1


def test_k12_capacity_overflow_is_rejected_from_ledger(rig_factory):
    r = rig_factory(shared=True, capacity={"think": 1, "eye": 2})
    _start_one(r)
    _start_one(r)
    with pytest.raises(ValueError):
        Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids, membrane=r.membrane,
               route="executor", hand=r.hand, drive=r.drive, pledges=Pledges(),
               capacity={"think": 1, "eye": 1})


def test_k13_reconstruction_can_fail_again_without_losing_observation(rig_factory):
    r, a, bjob = _shared_pair(rig_factory)
    p = r.host.pledges
    r.contents.fail_next()
    r.host.finish(a)
    with pytest.raises(StorageFull):
        r.host.step()
    saved = p.items[0].record
    r.contents.fail_next(2)  # 再試行の観測は書けるが、その後の信念を失敗させる。
    with pytest.raises(StorageFull):
        r.host.step()
    assert r.host.window is None and r.host.pledges is p
    r.host.step()
    _assert_saved(r, saved)
    assert len(_records(r, Observed)) == 1
    assert _counts(r, "look1") == [1, 0, 0]
    assert _job(r, _work(r, Act)[0]) == bjob


def test_k13b_act_from_reconstruction_survives_another_failure(rig_factory):
    r, a, bjob = _shared_pair(rig_factory)
    r.drive.rules = (_fail_once(Done),)
    r.contents.fail_next()
    r.host.finish(a)
    with pytest.raises(StorageFull):
        r.host.step()
    with pytest.raises(DriveFailure):
        r.host.step()
    assert r.host.window is None
    assert _job(r, _work(r, Act)[0]) == bjob
    r.host.step()
    assert len(_work(r, Act)) == 1
    assert len([w for w in r.host.started if isinstance(w, Act)]) == 2
    assert len(_successes(r, Done)) == 1


def test_k14_window_is_discarded_even_when_start_also_fails(rig_factory):
    r = rig_factory(drive=ScriptDrive(_on_tick, _fail_once(Thought)))
    think = _kick(r)
    ordinary_start = r.host.start
    failed = False

    def start(work, hand):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected start failure")
        ordinary_start(work, hand)

    r.host.start = start
    r.host.finish(think)
    with pytest.raises(DriveFailure) as error:
        r.host.step()
    assert isinstance(error.value.__context__, OSError)
    assert r.host.window is None and len(r.host.unstarted) == 1
    r.host.step()
    assert len(r.windows) == 2 and len(_work(r, Act)) == 1
    assert len(_successes(r, Thought)) == 1


def test_r1_three_nonoverlapping_cycles_match_run_step_cids(rig_factory):
    sync = rig_factory()
    finished = 0

    def rule(status, event):
        nonlocal finished
        if isinstance(event, Done):
            finished += 1
        if isinstance(event, Tick) or isinstance(event, Done) and finished < 3:
            return [_reconsider()]
        return []

    async_rig = rig_factory(drive=ScriptDrive(rule))
    world = ScriptedWorld({"look1": ["o0"] * 3, "look2": ["o1"] * 3, "wait": ["none"] * 3})
    for _ in range(3):
        run_step(sync.agent, world, CANDIDATES, u=.4, clock=sync.clock, ids=sync.ids,
                 ledger=sync.ledger, membrane=sync.membrane)
    _kick(async_rig)
    for _ in range(3):
        _finish(async_rig, _work(async_rig, Think)[0])
        _finish(async_rig, _work(async_rig, Act)[0])
    assert len(sync.ledger.entries()) == len(async_rig.ledger.entries()) == 16
    assert [e.cid for e in async_rig.ledger.entries()] == [e.cid for e in sync.ledger.entries()]
    assert world.calls == async_rig.hand.calls
    before = async_rig.ledger.entries()
    async_rig.host.window.settle()
    async_rig.host.window.settle()
    assert async_rig.ledger.entries() == before


def _two_in_flight(status, event):
    if isinstance(event, Tick) or isinstance(event, Thought) and len(status.awaiting) < 2:
        return [_reconsider()]
    return []


def _gated_hand(gate):
    return GatedHand({"look1": {"eye1"}, "look2": {"eye2"}, "wait": set()},
                     {"look1": ["o0"], "look2": ["o1"], "wait": ["none"]},
                     gates={"look1": gate})


def _release_and_join(hand, gate):
    gate.set()
    for thread in tuple(hand.threads.values()):
        thread.join(timeout=6)
        assert not thread.is_alive()


def test_r2_real_threads_b_finishes_while_a_is_alive_and_sqlite_has_one_writer(rig_factory):
    gate = Event()
    hand = _gated_hand(gate)
    r = rig_factory(hand=hand, drive=ScriptDrive(_two_in_flight), threaded=True, backend="sqlite")
    try:
        r.host.post(Tick(mono_ns=1))
        assert r.host.run_until(lambda s: _counts(r, "look2") == [0, 1, 0], timeout=10)
        assert hand.entered["look1"].wait(timeout=1)
        assert hand.threads["look1"].is_alive()
        assert len(r.host.window.status().awaiting) == 1
        assert _counts(r, "look1") == [0, 0, 0]
        gate.set()
        assert r.host.run_until(lambda s: _counts(r, "look1") == [1, 0, 0], timeout=10)
        assert not r.host.window.status().awaiting
        assert set(r.writes.threads) == {get_ident()} and r.writes.maximum == 1
        assert all(thread.daemon for thread in hand.threads.values())
    finally:
        _release_and_join(hand, gate)


def test_r3_sqlite_rejects_writes_from_another_thread(rig_factory):
    r = rig_factory(backend="sqlite")
    record = _raw_job(r, "look1")
    errors = []

    def write_elsewhere():
        try:
            r.ledger.append(record, ())
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=write_elsewhere, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], sqlite3.ProgrammingError)
    assert not r.ledger.entries_of(record.id)


def test_r4_abandon_does_not_stop_a_thread_or_prevent_b(rig_factory):
    gate = Event()
    hand = _gated_hand(gate)
    abandoned = False

    def rule(status, event):
        nonlocal abandoned
        if isinstance(event, Tick):
            return [_reconsider()]
        if isinstance(event, Thought) and not abandoned:
            abandoned = True
            return [Abandon(job=status.pending[0]), _reconsider(u=.9)]
        return []

    r = rig_factory(hand=hand, drive=ScriptDrive(rule), threaded=True, backend="sqlite")
    try:
        r.host.post(Tick(mono_ns=1))
        assert r.host.run_until(lambda s: _counts(r, "look2") == [0, 1, 0], timeout=10)
        assert hand.entered["look1"].wait(timeout=1)
        assert hand.threads["look1"].is_alive()
        status = r.host.window.status()
        assert status.pending == () and len(status.awaiting) == 1 and status.used["eye1"] == 1
        assert len(_records(r, Decided, ABANDON)) == 1
        gate.set()
        assert r.host.run_until(lambda s: _counts(r, "look1") == [1, 0, 0], timeout=10)
        assert not r.host.window.status().awaiting
    finally:
        _release_and_join(hand, gate)


def test_r5_thread_host_recovery_preserves_b_then_a_observations(rig_factory):
    gate = Event()
    hand = _gated_hand(gate)
    r = rig_factory(hand=hand, drive=ScriptDrive(_two_in_flight), threaded=True, backend="sqlite")
    b_posted, a_posted = Event(), Event()
    posted = []
    ordinary_post = r.host.post

    def post(event):
        ordinary_post(event)
        if isinstance(event, Done):
            posted.append(event)
            (b_posted if len(posted) == 1 else a_posted).set()

    r.host.post = post
    try:
        r.host.post(Tick(mono_ns=1))
        assert r.host.run_until(lambda s: len(s.awaiting) == 2, timeout=10)
        assert b_posted.wait(timeout=2)
        gate.set()
        assert a_posted.wait(timeout=2)
        r.contents.fail_next()
        with pytest.raises(StorageFull):
            r.host.run_until(lambda s: not s.awaiting, timeout=10)
        saved = r.host.pledges.items[0].record
        assert saved.body.caused_by == posted[0].attempt
        assert r.host.window is None
        assert r.host.run_until(lambda s: not s.awaiting, timeout=10)
        _assert_saved(r, saved)
        observations = sorted(_records(r, Observed), key=lambda o: o.at.seq)
        assert [o.body.caused_by for o in observations] == [e.attempt for e in posted]
        assert len(observations) == 2
        assert _counts(r, "look1") == [1, 0, 0] and _counts(r, "look2") == [0, 1, 0]
    finally:
        _release_and_join(hand, gate)


def test_r6_reconstructed_work_starts_before_waiting_for_more_events(rig_factory):
    r = rig_factory(drive=ScriptDrive(_fail_once(Tick, replies=(_reconsider(),))), threaded=True)
    r.host.post(Tick(mono_ns=1))
    with pytest.raises(DriveFailure):
        r.host.run_until(lambda s: bool(_records(r, Decided, DECISION)), timeout=10)
    # 追加の post はしない。復旧で出た Think 自身の Thought まで進む。
    assert r.host.run_until(lambda s: bool(_records(r, Decided, DECISION)), timeout=10)
    assert len(_records(r, Decided, DECISION)) == 1 and len(_successes(r, Tick)) == 1
    assert r.host.run_until(lambda s: not s.awaiting, timeout=10)
    for thread in r.hand.threads.values():
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_r7_accepted_tick_is_not_redelivered_after_settle_failure(rig_factory, monkeypatch):
    drive = ScriptDrive(_fail_once(Tick, replies=(_reconsider(),)))
    r = rig_factory(drive=drive, threaded=True, backend="memory")
    ordinary_start = Thread.start
    threads, started_thinks = [], []

    def start(thread):
        work = thread._args[0]
        ordinary_start(thread)
        threads.append(thread)
        if isinstance(work, Think):
            started_thinks.append(work)

    monkeypatch.setattr(Thread, "start", start)
    tick = Tick(mono_ns=1)
    try:
        r.host.post(tick)
        with pytest.raises(DriveFailure):
            r.host.run_until(lambda s: len(_records(r, Decided, DECISION)) == 1, timeout=10)
        assert [event for _, event in drive.calls if isinstance(event, Tick)] == [tick]
        assert not _successes(r, Tick)
        assert not _records(r, Decided, DECISION) and not started_thinks

        # 追加の post なし。同じ受け取りの知らせを復旧で一度だけ片づける。
        assert r.host.run_until(lambda s: len(_records(r, Decided, DECISION)) == 1, timeout=10)
        # 最初の決定で検査を打ち切らず、余分な Think があればその結果まで処理する。
        assert r.host.run_until(lambda s: s.thinking == s.waiting == 0 and not s.awaiting,
                                timeout=10)
        assert [event for _, event in drive.calls if isinstance(event, Tick)] == [tick, tick]
        assert len(_successes(r, Tick)) == 1
        assert len(_records(r, Decided, DECISION)) == 1
        assert r.host.pledges.issued == len(started_thinks) == 1
    finally:
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_r8_failed_accept_retains_b_done_ahead_of_a_done(rig_factory):
    gate = Event()
    hand = _gated_hand(gate)
    r = rig_factory(hand=hand, drive=ScriptDrive(_two_in_flight), threaded=True, backend="sqlite")
    r.ids = CountingIds(r.ids)
    b_posted, a_posted = Event(), Event()
    posted = []
    ordinary_post = r.host.post

    def post(event):
        ordinary_post(event)
        if isinstance(event, Done):
            posted.append(event)
            (b_posted if len(posted) == 1 else a_posted).set()

    r.host.post = post
    try:
        r.host.post(Tick(mono_ns=1))
        assert r.host.run_until(lambda s: len(s.awaiting) == 2, timeout=10)
        assert b_posted.wait(timeout=2)
        gate.set()
        assert a_posted.wait(timeout=2)
        assert [event.outcome for event in posted] == ["o1", "o0"]

        # B の Done、A の Done の順に列へ入ってから、B の accept だけを失敗させる。
        r.ids.fail_kind = K.OBSERVATION
        with pytest.raises(RuntimeError, match="injected ID failure"):
            r.host.run_until(lambda s: not s.awaiting, timeout=10)
        assert r.host.window is None
        assert r.ids.calls.count(K.OBSERVATION) == 1
        assert not _records(r, Observed)
        assert not r.host.pledges.items and not r.host.pledges.notices

        # 追加の post なし。失敗した B の封筒を、後ろの A より先に渡し直す。
        assert r.host.run_until(lambda s: not s.awaiting, timeout=10)
        observations = _records(r, Observed)
        assert len(observations) == 2
        assert [o.body.caused_by for o in observations] == [event.attempt for event in posted]
        assert [o.body.content.as_json() for o in observations] == [{"outcome": "o1"}, {"outcome": "o0"}]
        assert r.ids.calls.count(K.OBSERVATION) == 3  # 一度の失敗と二度の成功。
        assert len(_successes(r, Done)) == 2
        assert _counts(r, "look1") == [1, 0, 0] and _counts(r, "look2") == [0, 1, 0]
    finally:
        _release_and_join(hand, gate)


@pytest.mark.parametrize("capacity", [{}, {"think": 0}, {"think": True},
                                       {"think": 1.0}, {"think": 1, "eye1": 1}])
def test_window_rejects_invalid_or_missing_capacity(rig_factory, capacity):
    r = rig_factory(capacity=capacity)
    before = r.ledger.entries()
    with pytest.raises(ValueError):
        r.host.step()
    assert r.ledger.entries() == before


def test_window_requires_a_belief_without_writing(rig_factory):
    r = rig_factory()
    r.agent = Agent(model=r.model, lineage="new")
    before = r.ledger.entries()
    with pytest.raises(ValueError):
        r.host.step()
    assert r.ledger.entries() == before


def test_accept_stages_without_writing_and_deduplicates_unsettled_results(rig_factory):
    r = rig_factory()
    think = _kick(r)
    thought = r.host.finish(think)
    r.host.queue.clear()
    before = r.ledger.entries()
    window = r.host.window
    window.accept(Envelope(number=50, event=thought))
    window.accept(Envelope(number=51, event=thought))
    assert r.ledger.entries() == before
    assert len(r.host.pledges.items) == len(r.host.pledges.notices) == 1
    window.settle()
    r.host.step()
    act = _work(r, Act)[0]
    done = r.host.finish(act)
    r.host.queue.clear()
    before = r.ledger.entries()
    window.accept(Envelope(number=52, event=done))
    window.accept(Envelope(number=53, event=Failed(attempt=act.attempt, error="Error")))
    assert r.ledger.entries() == before
    assert len(r.host.pledges.items) == len(r.host.pledges.notices) == 1
    window.settle()
    assert len(_records(r, Observed)) == 1


def test_thread_host_timeout_and_numbering(rig_factory):
    r = rig_factory(threaded=True, drive=ScriptDrive())
    assert r.host.run_until(lambda s: False, timeout=.01) is False
    workers = [Thread(target=lambda: r.host.post(Tick(mono_ns=1)), daemon=True) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    envelopes = [r.host._queue.get_nowait() for _ in workers]
    assert [e.number for e in envelopes] == list(range(1, 9))


def test_k9_thread_start_failure_resumes_only_the_unstarted_work(rig_factory, monkeypatch):
    r = rig_factory(threaded=True,
                    drive=ScriptDrive(lambda s, e: [_reconsider()] * 2 if isinstance(e, Tick) else []),
                    capacity={"think": 2, "eye1": 2, "eye2": 2})
    ordinary_start = Thread.start
    attempts = []
    failed = False

    def start(thread):
        nonlocal failed
        work = thread._args[0]
        if isinstance(work, Think):
            attempts.append(work.work)
            if work.work == "think:2" and not failed:
                failed = True
                raise OSError("injected Thread.start failure")
        ordinary_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    r.host.post(Tick(mono_ns=1))
    with pytest.raises(OSError):
        r.host.run_until(lambda s: len(_records(r, Decided, DECISION)) == 2, timeout=10)
    window = r.host.window
    assert window is not None and len(r.host._unstarted) == 1
    assert r.host.run_until(lambda s: len(_records(r, Decided, DECISION)) == 2, timeout=10)
    assert r.host.window is window
    assert attempts == ["think:1", "think:2", "think:2"]
    assert r.host.run_until(lambda s: not s.awaiting, timeout=10)


def test_k14_thread_host_keeps_start_failure_as_context(rig_factory, monkeypatch):
    r = rig_factory(threaded=True, drive=ScriptDrive(_on_tick, _fail_once(Thought)))
    ordinary_start = Thread.start
    failed = False

    def start(thread):
        nonlocal failed
        if isinstance(thread._args[0], Act) and not failed:
            failed = True
            raise OSError("injected Thread.start failure")
        ordinary_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    r.host.post(Tick(mono_ns=1))
    with pytest.raises(DriveFailure) as error:
        r.host.run_until(lambda s: bool(_records(r, Observed)), timeout=10)
    assert isinstance(error.value.__context__, OSError)
    assert r.host.window is None and len(r.host._unstarted) == 1
    assert r.host.run_until(lambda s: bool(_records(r, Observed)), timeout=10)
    assert len(r.windows) == 2 and len(r.hand.calls) == 1
    assert len(_successes(r, Thought)) == 1
