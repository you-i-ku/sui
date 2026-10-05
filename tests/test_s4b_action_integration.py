"""S4b v0.22 §3-0-20, §3-10-6..8, §6-3: public integration.

Expectations are declared here, never sampled from production output. Tests use
public factories, value fields, Window/ThreadHost and a real WaitDispatcher.
No real hand, wall-clock precision assumption, private runtime entry or source
inspection. Thread gates have bounded cleanup even when an assertion fails.
"""
from fractions import Fraction as F
import json
import math
from threading import Event
from types import SimpleNamespace

import pytest

from s4b_action_cases import NS, I, api, declaration, delay, encoded, load_model, rig, view_of


COMMAND_KEYS = {"action", "choice", "run", "not_before_ns", "reservation_rule",
                "dispatch", "effect", "late", "causal_stage", "causal_position"}
PAYLOAD_KEYS = {
    "action_job": {"action", "choice", "reservation_rule", "dispatch", "effect"},
    "action_attempt": {"command", "decision_reading"},
    "reservation": {"command", "decision_reading"},
    "receipt": {"command", "run", "reading_ns"},
    "dispatch": {"command", "run", "reading_ns", "point"},
    "action_report": {"outcome", "effect_notice", "measurement_reading_ns", "completion_reading_ns"},
}


def model_json():
    d = declaration(confirmations=True)
    d["choices"]["a"]["reservation"] = {"kind": "offset", "offset_ns": 3}
    d["execution"]["think"] = delay(F(7, NS))
    return d


def records(r, kind=None, contract=None):
    result = [r.ledger.record(e.cid) for e in r.ledger.entries()]
    if kind is not None:
        result = [x for x in result if isinstance(x.body, kind)]
    if contract is not None:
        result = [x for x in result if x.body.contract.name == contract]
    return result


def named(r, name):
    return records(r, contract="sui.s4b." + name)


def assert_same_reading(actual, expected):
    # Reading.n contains numpy arrays; dataclass == is not an array comparison.
    assert {k: v.tolist() for k, v in actual.n.items()} == {
        k: v.tolist() for k, v in expected.n.items()}
    for field in ("unread", "pending", "sequence", "started", "preferences", "unread_preferences"):
        assert getattr(actual, field) == getattr(expected, field), field


def window(r, pledges, hand, drive, *, capacity=1, thinkers=1):
    from sui.records import Producer
    from sui.runtime import Window
    return Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
        membrane=Producer(component="test.action.integration", code_version="1"),
        route="executor", hand=hand, drive=drive,
        capacity={"think": thinkers, "arm": capacity}, pledges=pledges)


class SimulatedHand:
    def __init__(self, clock, *, fail=None, null_readings=False):
        self.clock, self.fail, self.null_readings = clock, fail, null_readings
        self.calls = []
        self.readings = []

    def resources(self, action):
        return frozenset({"arm"})

    def send(self, action, *, on_dispatched):
        self.calls.append(action)
        self.readings.append(self.clock.mono_ns())
        if self.fail == "before":
            raise OSError("simulated failure before confirmation")
        on_dispatched(self.clock.mono_ns())
        if self.fail == "after":
            raise OSError("simulated failure after confirmation")
        self.clock.advance(NS)
        reading = None if self.null_readings else self.clock.mono_ns()
        return api("dispatch").ActionResult(outcome="1", effect_notice=None,
            measurement_reading_ns=reading, completion_reading_ns=reading)

    def execute(self, action):
        raise AssertionError("model.8 reached the legacy Hand.execute path")


def host_fixture(monkeypatch, *, fail=None, null_readings=False, gated=False):
    from sui import agent, runtime
    from sui.contracts import ContractRef
    from test_lookahead import _rig
    from worlds import HandHistory, ScriptDrive
    # Let ThreadHost produce BOOT, rather than pre-inserting a second BOOT.
    r = _rig(model=load_model(model_json()), history=HandHistory(), H=NS+10, items=())
    hand = SimulatedHand(r.clock, fail=fail, null_readings=null_readings)
    plans, thoughts, waits = [], [], []
    gate, entered = Event(), Event()
    if not gated:
        gate.set()
    original_plan = agent.plan

    def timed_plan(view, candidates, *, u):
        plans.append(view)
        result = original_plan(view, candidates, u=u)
        r.clock.advance(7)  # computation finishes at r_d=7, not frozen View time=0
        return result

    # runtime.plan is an existing public imported callable; no private worker patch.
    monkeypatch.setattr(runtime, "plan", timed_plan)

    def rule(status, event):
        if isinstance(event, runtime.Thought):
            thoughts.append(event)
        return (runtime.Reconsider(candidates=("a",), u=.25),) if isinstance(event, runtime.Tick) else ()

    def wait(seconds):
        waits.append(seconds)
        entered.set()
        assert gate.wait(2), "test gate was not released"
        assert len(waits) <= 3, "bounded fake wakeups exhausted"
        r.clock.advance(1)

    dispatcher = api("dispatch").WaitDispatcher(clock=r.clock, wait=wait,
        point=ContractRef("test.physical-send", "1"))
    source = api("clock_contracts").ClockSource(run=r.clock.run, provider="test.FakeClock",
        implementation="explicit advance", python_version="test", resolution_s=F(1, NS),
        monotonic=True, adjustable=False, measurement=None)
    drive = ScriptDrive(rule)
    host = runtime.ThreadHost(lambda p: window(r, p, hand, drive), clock=r.clock,
                             dispatcher=dispatcher, clock_source=source)
    return SimpleNamespace(r=r, host=host, hand=hand, plans=plans, thoughts=thoughts,
        waits=waits, gate=gate, entered=entered, source=source)


def run_host(f):
    from sui.runtime import Tick
    f.host.post(Tick(mono_ns=0))
    assert f.host.run_until(lambda s: bool(f.thoughts) and not s.thinking and not s.awaiting,
                           timeout=3), "host did not finish the bounded simulated work"


def assert_command(data, run):
    assert set(data) == COMMAND_KEYS
    assert data == {"action": "a", "choice": "a", "run": str(run),
        "not_before_ns": 10, "reservation_rule": {"kind": "offset", "offset_ns": 3},
        "dispatch": {"name": "wait-dispatch", "version": "1"},
        "effect": {"name": "start-impulse", "version": "2"},
        "late": "send_when_ready", "causal_stage": data["causal_stage"],
        "causal_position": data["causal_position"]}
    assert type(data["causal_stage"]) is type(data["causal_position"]) is int
    assert data["causal_stage"] >= 0 and data["causal_position"] >= 0


def assert_record_chain(f):
    from sui.records import JobOpened, AttemptStarted, Observed
    r = f.r
    chain = {name: named(r, name) for name in PAYLOAD_KEYS}
    assert all(len(rows) == 1 for rows in chain.values()), {k: len(v) for k, v in chain.items()}
    chain = {k: v[0] for k, v in chain.items()}
    assert isinstance(chain["action_job"].body, JobOpened)
    assert isinstance(chain["action_attempt"].body, AttemptStarted)
    assert chain["action_attempt"].body.job == chain["action_job"].id
    for name, record in chain.items():
        assert record.body.contract.version == "1"
        data = record.body.content.as_json()
        assert set(data) == PAYLOAD_KEYS[name]
        if "command" in data:
            assert_command(data["command"], r.clock.run)
        if "decision_reading" in data:
            assert data["decision_reading"] == {"run": str(r.clock.run), "reading_ns": 7,
                "work": f.thoughts[0].work, "parents": sorted(f.plans[0].frontier)}
        if name not in ("action_job", "action_attempt"):
            assert isinstance(record.body, Observed)
            assert record.body.caused_by == chain["action_attempt"].id
    assert len({r.id for r in chain.values()}) == len(chain)
    intent = chain["action_job"].body.content.as_json()
    assert intent == {k: chain["action_attempt"].body.content.as_json()["command"][k]
                      for k in PAYLOAD_KEYS["action_job"]}
    for name, reading in (("receipt", 7), ("dispatch", 10)):
        data = chain[name].body.content.as_json()
        assert data["run"] == str(r.clock.run) and data["reading_ns"] == reading
        assert chain[name].body.received_ns >= reading
        assert chain[name].at.mono_ns >= chain[name].body.received_ns
    assert chain["dispatch"].body.content.as_json()["point"] == {"name": "test.physical-send", "version": "1"}
    return chain


def test_public_model8_threadhost_record_chain_rebuild_restore_replay(monkeypatch, tmp_path):
    from sui.agent import Agent, read, replay_decision
    from sui.ledger import Ledger, SequentialSalts
    from sui.model import model_json as serialize_model
    from sui.records import Decided
    from sui.store import SqliteStore
    f = host_fixture(monkeypatch)
    run_host(f)
    chain = assert_record_chain(f)
    assert f.hand.calls == ["a"] and f.hand.readings == [10]
    assert f.waits == pytest.approx([3/NS, 2/NS, 1/NS])
    assert len(f.plans) == len(f.thoughts) == 1
    assert f.plans[0].now_ns == 0
    assert f.thoughts[0].decision_reading.reading_ns == 7
    assert chain["action_report"].body.content.as_json() == {"outcome": "1", "effect_notice": None,
        "measurement_reading_ns": NS+10, "completion_reading_ns": NS+10}
    r = f.r
    decision = records(r, Decided)[0]
    data = decision.body.content.as_json()
    assert data["information"] == pytest.approx([math.log(2)], abs=1e-9)
    assert data["J"] == pytest.approx([-math.log(2)], abs=1e-9)
    assert data["q_pi"] == [1.]
    assert "command" not in data and "decision_reading" not in data
    assert_same_reading(read(r.model, tuple(records(r))), r.agent.view().reading)
    saved = r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger)
    summary = saved.body.content.as_json()
    assert saved.body.contract.name == "sui.s4b.action_belief"
    assert summary["status"] == "complete" and summary["q"] == [0., 1.]
    assert summary["pending"] == [] and summary["unread"] == []
    belief_cid = r.ledger.entries_of(saved.id)[0].cid
    decision_cid = r.ledger.entries_of(decision.id)[0].cid
    expected_headers = {e.cid: e.header for e in r.ledger.entries()}
    with SqliteStore.open(tmp_path/"saved", create=True) as store:
        ref = store.models.put(r.model)
        for entry in r.ledger.entries():
            salt, payload = r.ledger.contents.get(entry.seal)
            store.contents.put(entry.seal, salt, payload)
            store.entries.add(entry.cid, entry.header)
    with SqliteStore.open(tmp_path/"saved", readonly=True) as store:
        ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        model = store.models.get(ref)
        assert serialize_model(model) == encoded(model_json())
        assert {e.cid: e.header for e in ledger.entries()} == expected_headers
        ledger.verify()
        restored = Agent.restore(model=model, lineage="restored", ledger=ledger, belief=belief_cid)
        assert restored.q.tolist() == [0., 1.]
        assert_same_reading(restored.view().reading, read(model, tuple(ledger.record(e.cid) for e in ledger.entries())))
        assert replay_decision(model=model, ledger=ledger, decision=decision_cid).content == decision.body.content
        assert len(f.hand.calls) == 1


def test_public_prepare_commit_is_idempotent_and_replay_ignores_later_clock():
    from sui.agent import plan, replay_decision
    from sui.records import Decided, JobOpened
    r = rig(model_json(), H=NS+10)
    view = view_of(r)
    draft = plan(view, ("a",), u=.25)
    before = tuple(r.ledger.entries())
    prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
    assert tuple(r.ledger.entries()) == before
    r.agent.commit(prepared, ledger=r.ledger)
    saved = tuple(r.ledger.entries())
    r.agent.commit(prepared, ledger=r.ledger)
    assert tuple(r.ledger.entries()) == saved
    assert len(records(r, Decided)) == len(records(r, JobOpened)) == 1
    r.clock.advance(100*NS)
    cid = r.ledger.entries_of(prepared.decided.id)[0].cid
    assert replay_decision(model=r.model, ledger=r.ledger, decision=cid).content == draft.content


def test_public_thought_keeps_frozen_view_when_a_fact_arrives_during_computation():
    from sui.agent import plan, replay_decision
    from sui.contracts import ContractRef
    from sui.records import Payload, Decided, Observed
    from sui.runtime import Pledges, Envelope, Tick, Thought, Reconsider, Arrived
    from worlds import ScriptDrive
    r = rig(model_json(), H=NS+10)
    drive = ScriptDrive(lambda s, e: (Reconsider(candidates=("a",), u=.25),) if isinstance(e, Tick) else ())
    w = window(r, Pledges(), SimulatedHand(r.clock), drive)
    w.accept(Envelope(number=1, event=Tick(mono_ns=0), received_ns=0))
    w.settle()
    work, = w.drain()
    draft = plan(work.view, work.candidates, u=work.u)
    parents = work.view.frontier
    r.clock.advance(1)
    contract = ContractRef("test.external-note", "1")
    w.accept(Envelope(number=2, event=Arrived(route="outside", contract=contract,
        content=Payload.json({"note": "arrived during computation"})), received_ns=1))
    w.settle()
    fact, = records(r, Observed, contract.name)
    assert r.ledger.entries_of(fact.id)[0].cid not in parents
    r.clock.advance(6)
    rd = api("action_types").DecisionReading(run=r.clock.run, reading_ns=7,
        work=work.work, parents=parents)
    w.accept(Envelope(number=3, event=Thought(work=work.work, draft=draft, decision_reading=rd), received_ns=7))
    w.settle()
    decision, = records(r, Decided)
    assert decision.body.content == draft.content
    assert decision.body.content.as_json()["root"]["parents"] == sorted(parents)
    attempt, = named(r, "action_attempt")
    assert attempt.body.content.as_json()["decision_reading"]["parents"] == sorted(parents)
    assert_command(attempt.body.content.as_json()["command"], r.clock.run)
    cid = r.ledger.entries_of(decision.id)[0].cid
    assert replay_decision(model=r.model, ledger=r.ledger, decision=cid).content == draft.content


def test_public_resource_wait_and_window_reconstruction_keep_bound_command():
    from sui.agent import plan
    from sui.runtime import Pledges, Envelope, Tick, Think, Thought, Act, Reconsider, Failed
    from worlds import ScriptDrive
    r = rig(model_json(), H=NS+10)
    hand = SimulatedHand(r.clock)
    drive = ScriptDrive(lambda s, e: (Reconsider(candidates=("a",), u=.25),)*2 if isinstance(e, Tick) else ())
    pledges = Pledges()
    w = window(r, pledges, hand, drive, thinkers=2)
    w.accept(Envelope(number=1, event=Tick(mono_ns=0), received_ns=0))
    w.settle()
    first_work, work = w.drain()
    assert isinstance(work, Think) and isinstance(first_work, Think)
    draft = plan(work.view, work.candidates, u=work.u)
    reading = api("action_types").DecisionReading(run=r.clock.run, reading_ns=7,
        work=work.work, parents=work.view.frontier)
    r.clock.advance(7)
    first_reading = api("action_types").DecisionReading(run=r.clock.run, reading_ns=7,
        work=first_work.work, parents=first_work.view.frontier)
    first_draft = plan(first_work.view, first_work.candidates, u=first_work.u)
    w.accept(Envelope(number=2, event=Thought(work=first_work.work, draft=first_draft,
        decision_reading=first_reading), received_ns=7))
    w.settle()
    blocking_act, = w.drain()
    assert isinstance(blocking_act, Act) and w.status().used["arm"] == 1
    result = Thought(work=work.work, draft=draft, decision_reading=reading)
    w.accept(Envelope(number=3, event=result, received_ns=7))
    w.settle()
    assert w.drain() == () and len(w.status().queued) == 1
    r.clock.advance(100)
    w = window(r, pledges, hand, drive, thinkers=2)
    w.settle()
    assert w.drain() == () and w.status().used["arm"] == 1
    w.accept(Envelope(number=4, event=Failed(attempt=blocking_act.attempt,
        error="simulated external worker failure"), received_ns=107))
    w.settle()
    act, = w.drain()
    assert isinstance(act, Act)
    assert act.command is not None, "model.8 Act must carry its bound command"
    assert_command(json.loads(api("dispatch").command_json(act.command)), r.clock.run)
    w.accept(Envelope(number=5, event=result, received_ns=107))  # duplicate worker delivery
    w.settle()
    assert w.drain() == ()
    rebuilt = window(r, pledges, hand, drive)
    rebuilt.settle()
    assert rebuilt.drain() == ()
    assert len(named(r, "action_attempt")) == len(named(r, "reservation")) == 2
    for record in named(r, "action_attempt") + named(r, "reservation"):
        assert_command(record.body.content.as_json()["command"], r.clock.run)
        assert record.body.content.as_json()["decision_reading"]["reading_ns"] == 7
    notices, waits = [], []
    from sui.contracts import ContractRef
    dispatcher = api("dispatch").WaitDispatcher(clock=r.clock,
        wait=lambda seconds: waits.append(seconds), point=ContractRef("test.late", "1"))
    dispatcher.execute(act, hand, emit=notices.append)
    assert waits == [] and hand.calls == ["a"] and hand.readings == [107]
    assert [n.kind for n in notices] == ["receipt", "dispatch"]
    assert all(n.command == act.command for n in notices)


@pytest.mark.parametrize("where", ("before", "after"))
def test_public_hand_exception_keeps_evidence_and_never_resends(monkeypatch, where):
    from sui.records import AttemptStarted, Observed
    from sui.runtime import Failed
    from sui.s3_contracts import ENDED
    f = host_fixture(monkeypatch, fail=where)
    run_host(f)
    r = f.r
    assert f.hand.calls == ["a"]
    assert len(named(r, "receipt")) == 1
    assert len(named(r, "dispatch")) == (where == "after")
    assert named(r, "action_report") == []
    assert len(records(r, AttemptStarted)) == 1
    ended, = records(r, Observed, ENDED.name)
    assert ended.body.content.as_json() == {"error": "OSError"}
    assert ended.body.caused_by == records(r, AttemptStarted)[0].id
    assert any(isinstance(event, Failed) for _, event in f.host.window.drive.calls)
    # Failure leaves physical result unknown. It must not assert a pre-dispatch phase.
    summaries = r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger).body.content.as_json()["pending"]
    assert summaries and all(x["phase"] in (None, "result_unknown", "dispatched", "working") for x in summaries)
    before = tuple(r.ledger.entries())
    f.host.window.settle()
    assert f.host.run_until(lambda s: True, timeout=.1)
    assert tuple(r.ledger.entries()) == before and f.hand.calls == ["a"]


def test_public_report_null_readings_are_not_filled_from_record_clock(monkeypatch):
    f = host_fixture(monkeypatch, null_readings=True)
    run_host(f)
    report, = named(f.r, "action_report")
    assert report.at.mono_ns == NS+10
    assert report.body.content.as_json() == {"outcome": "1", "effect_notice": None,
        "measurement_reading_ns": None, "completion_reading_ns": None}


def test_public_wait_worker_does_not_block_window_and_timeout_does_not_cancel(monkeypatch):
    from sui.runtime import Tick
    f = host_fixture(monkeypatch, gated=True)
    f.host.post(Tick(mono_ns=0))
    try:
        assert not f.host.run_until(lambda s: False, timeout=.05)
        assert f.entered.wait(1), "hand never reached reservation wait"
        assert len(named(f.r, "receipt")) == 1
        assert f.host.window.status().used["arm"] == 1
        assert f.hand.calls == []
    finally:
        f.gate.set()
        f.host.run_until(lambda s: bool(f.thoughts) and not s.thinking and not s.awaiting, timeout=3)
    assert f.hand.calls == ["a"]
    assert len(named(f.r, "action_report")) == 1
    assert f.host.window.status().used.get("arm", 0) == 0


@pytest.mark.parametrize("reason", ("accuracy", "budget", "continuous_timing"))
def test_public_incomplete_worker_never_writes_decision_or_job(monkeypatch, reason):
    from sui import runtime
    from sui.records import Decided, JobOpened, Observed
    f = host_fixture(monkeypatch)
    failure = api("action_types").ActionIncomplete(reason=reason, detail="controlled public planner failure")
    def incomplete(view, candidates, *, u):
        raise failure
    monkeypatch.setattr(runtime, "plan", incomplete)
    run_host(f)
    assert records(f.r, Decided) == records(f.r, JobOpened) == []
    assert f.hand.calls == []
    assert f.thoughts[0].draft is None and f.thoughts[0].error is not None
    assert records(f.r, Observed)  # accepted BOOT/source facts remain durable


def test_public_clock_source_follows_boot_once_with_exact_payload(monkeypatch):
    from sui.records import Observed
    from sui.s4_contracts import BOOT
    f = host_fixture(monkeypatch)
    assert f.host.run_until(lambda s: bool(records(f.r, Observed, "sui.clock.source")), timeout=1)
    boots = [r for r in records(f.r, Observed) if r.body.contract == BOOT]
    source, = records(f.r, Observed, "sui.clock.source")
    assert len(boots) == 1 and boots[0].body.content.as_json() == {}
    assert boots[0].at.seq < source.at.seq and source.body.contract.version == "1"
    assert source.body.content.as_json() == {"run": str(f.r.clock.run), "provider": "test.FakeClock",
        "implementation": "explicit advance", "python_version": "test", "resolution_s": [1, NS],
        "monotonic": True, "adjustable": False, "measurement": None}
    before = tuple(f.r.ledger.entries())
    assert f.host.run_until(lambda s: True, timeout=.1)
    assert tuple(f.r.ledger.entries()) == before and not f.hand.calls


def test_public_model7_threadhost_keeps_legacy_hand_and_attempt():
    from sui.agent import replay_decision
    from sui.model import model_json as serialize_model
    from sui.records import AttemptStarted, Decided, Observed
    from sui.runtime import ThreadHost, Tick, Reconsider
    from sui.s1_contracts import ATTEMPT, OUTCOME
    from test_joint_entry import _model
    from test_lookahead import _rig
    from worlds import HandHistory, ScriptDrive
    r = _rig(model=_model(), history=HandHistory(), H=NS, items=())
    assert json.loads(serialize_model(r.model))["scheme"] == "sui.model.7"
    calls = []
    class LegacyHand:
        def resources(self, action):
            return frozenset()
        def execute(self, action):
            calls.append(action)
            r.clock.advance(NS)
            return "0"
        def send(self, *args, **kwargs):
            raise AssertionError("legacy model entered DispatchHand.send")
    drive = ScriptDrive(lambda s, e: (Reconsider(candidates=("a",), u=.25),) if isinstance(e, Tick) else ())
    host = ThreadHost(lambda p: window(r, p, LegacyHand(), drive), clock=r.clock)
    host.post(Tick(mono_ns=0))
    assert host.run_until(lambda s: bool(records(r, Observed, OUTCOME.name)) and not s.awaiting, timeout=3)
    assert calls == ["a"]
    attempt, = records(r, AttemptStarted)
    assert attempt.body.contract == ATTEMPT and attempt.body.content.as_json() == {}
    assert not named(r, "reservation") and not named(r, "action_attempt")
    decision, = records(r, Decided)
    cid = r.ledger.entries_of(decision.id)[0].cid
    assert replay_decision(model=r.model, ledger=r.ledger, decision=cid).content == decision.body.content
