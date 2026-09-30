"""S4a v0.7の約束と識別力。

clock/Record/admit/codec: J1・V1〜V5 / model: M10〜M12
timeline/to_axis: T1〜T10・T8b・T10b・J6 / read/filter_log: Q2〜Q10・Q12・Q13
plan: Q1・Q3・Q6・Q11 / arrival: H1〜H11 / restore: Q7・M12・V2
Window/Pledges/host: T4・T9・Q5・R10〜R13・J1〜J5
表1〜6は仕様書の固定値。実装から期待値を作らない。
"""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from sui.agent import Agent, ModelFalsified, RebuildMismatch, View, plan_s4c as plan, read, _derive_reading
from sui.clock import FakeClock, Instant, SystemClock
from sui.contracts import ContractBook, ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.inference import (transition, reachable, filter_log, arrival_posterior,
    arrival_within, _log_A)
from sui.ledger import (Ledger, SequentialSalts, encode_header, decode_record,
    entry_from_header, seal)
from sui.loop import boot, run_step
from sui.model import ArrivalPrior, model_json, model_from_json, model_ref
from sui.records import (Observed, AttemptStarted, JobOpened, Prediction, Decided,
    Payload, Producer, Record, Role, Category, Admission, IdConflict, admit)
from sui.runtime import (Boot, Listen, Envelope, Reconsider, Abandon, Arrived, Done, Failed, Tick,
    Thought, Think, Act, Window, Pledges, ThreadHost)
from sui.s1_contracts import ACTION, ATTEMPT, OUTCOME
from sui.s3_contracts import ENDED
from sui.s4_contracts import BOOT, LISTEN, BELIEF, DECISION, DECLARATIONS
from sui.store import SqliteStore, StorageFull
from sui.timeline import timeline, TimelineError, ArrivalStats, _facts
from worlds import (_time_model, _close, ManualHost, GatedHand,
    ScriptDrive, ScriptedWorld, FlakyContents)


NS = 1_000_000_000
TABLE1 = [
    (0, .8181818181818181, .9196116365063846, .6717261576384556),
    (1, .6170525494636407, .8329165591953, .7432220052427373),
    (10, .5000144454321972, .8232156702031204, .7505572449752611),
]
TABLE2 = [.11803074685386795, .8819692531461321]
TABLE3 = [(30, .488), (50, .370262390670554), (80, .271)]
TABLE4 = [.19046502070263197, .7209053683510709, .08862961094629708]
TABLE5 = [5.814566888608951e-241, 1.0]
TABLE6 = [.5661470870985407, .3922211098545785, .95836819695311925,
          1.0986122886681097, .63667842262149375]


class History:
    """受信と記録を別に指定できる事実のfixture。名札とseqも独立。"""

    def __init__(self, run="r1", index=0, wall=100):
        self.run, self.index, self.wall = Ref(K.RUN, run), index, wall
        self.seq = 0
        self.records = []

    def add(self, body, seconds=0, name=None):
        self.seq += 1
        kind = {Observed: K.OBSERVATION, JobOpened: K.JOB, AttemptStarted: K.ATTEMPT,
                Prediction: K.PREDICTION, Decided: K.DECISION}[type(body)]
        record = Record(id=Ref(kind, name or f"{self.run.value}_{self.seq:06d}"),
            at=Instant(run=self.run, run_index=self.index, seq=self.seq,
                       mono_ns=int(seconds * NS), wall_ns=int((self.wall + seconds) * NS)),
            writer=Role.MEMBRANE if type(body) in (Observed, AttemptStarted) else Role.MODEL,
            producer=Producer(component="test.time", code_version="1"), body=body)
        self.records.append(record)
        return record

    def observe(self, seconds=0, *, route="membrane", contract=BOOT, content=None,
                received=None, name=None, caused_by=None, source_id=None):
        return self.add(Observed(route=route, contract=contract,
            content=Payload.json({} if content is None else content), caused_by=caused_by,
            source_id=source_id, received_ns=int((seconds if received is None else received) * NS)),
            seconds, name)

    def listen(self, seconds, open, route="letter", **kwargs):
        return self.observe(seconds, contract=LISTEN, content={"route": route, "open": open}, **kwargs)

    def arrival(self, seconds, route="letter", **kwargs):
        return self.observe(seconds, route=route, contract=ContractRef("unreadable", "42"),
                            content={"letter": "same"}, source_id="same", **kwargs)

    def attempt(self, action="look", seconds=0):
        job = self.add(JobOpened(decision=Ref(K.DECISION, "decision"), step=0,
            content=Payload.json({"action": action}), contract=ACTION), seconds)
        return self.add(AttemptStarted(job=job.id, content=Payload.json({}), contract=ATTEMPT), seconds)

    def outcome(self, outcome, seconds=0, *, received=None, action="look"):
        attempt = self.attempt(action, seconds)
        return self.observe(seconds, route="executor", contract=OUTCOME,
            content={"outcome": outcome}, caused_by=attempt.id, received=received)


def _q(model, records):
    reading = read(model, records)
    return _derive_reading(model, reading)[0]


def _plan(model, records, seconds):
    return plan(View(model=model, frontier=frozenset(), belief=Ref(K.PREDICTION, "belief"),
        reading=read(model, records), now_ns=int(seconds * NS)), model.actions, u=.5).content.as_json()


def _arrival_model(**changes):
    return _time_model(changing=False, arrivals={"letter": ArrivalPrior(alpha=1., beta_s=10.)}, **changes)


@pytest.mark.parametrize("Q", [np.zeros((2, 2)), np.eye(2), np.ones((2, 3)),
    np.array([[-.5, -.1], [.5, .1]]), np.array([[np.nan, .5], [.5, -.5]]),
    np.array([[-.5, np.inf], [.5, -.5]]), np.array([[-.4, .5], [.5, -.5]])])
def test_m10_invalid_generators(Q):
    with pytest.raises(ValueError):
        _time_model(Q=Q)


def test_m10_model_boundaries_and_readonly_copies():
    with pytest.raises(ValueError, match="S4b"):
        _time_model(learnable=frozenset({"look"}))
    with pytest.raises(ValueError):
        _time_model(arrivals={"membrane": ArrivalPrior(alpha=1., beta_s=10.)})
    with pytest.raises(ValueError):
        _time_model(arrivals={"": ArrivalPrior(alpha=1., beta_s=10.)})
    for bad in (0., -1., math.inf, math.nan):
        with pytest.raises(ValueError):
            ArrivalPrior(alpha=bad, beta_s=10.)
        with pytest.raises(ValueError):
            ArrivalPrior(alpha=1., beta_s=bad)
    for bad in (True, 1, "1"):
        with pytest.raises(TypeError):
            ArrivalPrior(alpha=bad, beta_s=10.)
    Q = np.array([[-.5, .5], [.5, -.5]])
    arrivals = {"letter": ArrivalPrior(alpha=1., beta_s=10.)}
    model = _time_model(Q=Q, arrivals=arrivals)
    Q[:] = 0
    arrivals.clear()
    assert model.Q[0, 0] == -.5 and "letter" in model.arrivals
    with pytest.raises(ValueError):
        model.Q[0, 0] = 0
    with pytest.raises(TypeError):
        model.arrivals["other"] = model.arrivals["letter"]
    with pytest.raises(FrozenInstanceError):
        model.arrivals["letter"].alpha = 2.


def test_m11_model_encoding_and_contracts():
    from test_ledger import _f4
    static = _f4()
    assert model_ref(static) == "sha256:568c5dd475ebe1518c227944556166aaf647328d2f86507dd696f82a06824fb2"
    assert json.loads(model_json(static))["scheme"] == "sui.model.1"
    for model in (_time_model(), _arrival_model(), _time_model(world="W3")):
        encoded = model_json(model)
        assert json.loads(encoded)["scheme"] == "sui.model.2"
        assert model_json(model_from_json(encoded)) == encoded
        with pytest.raises(ValueError):
            model_from_json(encoded + b"\n")
    book = ContractBook()
    assert tuple(c.ref for c in DECLARATIONS) == (BOOT, LISTEN, BELIEF, DECISION)
    for declaration in DECLARATIONS:
        book.register(declaration)
        assert book.get(declaration.ref) == declaration


def test_t1_t6_t7_t9_axis_receipt_order_missing_and_extra_boot():
    h = History()
    origin = h.observe(5, received=0)
    obs = h.outcome("o0", 9, received=1)
    extra = h.observe(10)
    bad = h.observe(11, content={"bad": True})
    legacy = replace(h.outcome("o1", 12), schema=2,
                     body=replace(h.records[-1].body, received_ns=None))
    h.records[-1] = legacy
    other = History("r2", 1)
    no_clock = other.outcome("o1", 20)
    records = h.records + other.records
    for facts in (records, records[::-1], records[::2] + records[1::2]):
        axis = timeline(facts)
        assert axis.origin == origin.id
        assert axis.received_ns[obs.id] == NS
        assert axis.to_axis(h.run, 9 * NS) == 9 * NS
        assert any(i["kind"] == "extra_boot" and i["id"] == str(extra.id) for i in axis.clock_issues)
        with pytest.raises(KeyError):
            axis.to_axis(other.run, 0)
        reading = read(_time_model(), facts)
        assert reading.unread[bad.id] == "content"
        assert reading.unread[legacy.id] == "no_receipt_time"
        assert reading.unread[no_clock.id] == "no_clock"
        assert reading.sequence[0][0] == NS
    malformed = History()
    only_bad = malformed.observe(content={"bad": True})
    assert read(_time_model(), malformed.records).unread[only_bad.id] == "content"
    with pytest.raises(TypeError):
        axis.received_ns[obs.id] = 0


@pytest.mark.parametrize("wall, expected, gap", [(200, 100, None), (90, 0, -10)])
def test_t2_t8_t8b_between_runs_corrects_delay_before_clamping(wall, expected, gap):
    a, b = History(), History("r2", 1, wall)
    a.observe()
    b_boot = b.observe(9, received=0)
    axis = timeline(a.records + b.records)
    assert axis.received_ns[b_boot.id] == expected * NS
    assert axis.to_axis(b.run, NS) == (expected + 1) * NS
    if gap is None:
        assert not axis.clock_issues
    else:
        assert dict(axis.clock_issues[0]) == {"kind": "negative_wall_gap", "run": "run:r2", "gap_ns": gap * NS}
    data = _plan(_time_model(), a.records + b.records, expected + 1)
    assert data["time"]["dt_s"] == float(expected + 1)


def test_t3_concurrent_runs_are_unexplainable():
    a, b = History(), History("other", 0)
    a.observe()
    b.observe()
    with pytest.raises(TimelineError):
        timeline(a.records + b.records)
    reading = read(_time_model(), a.records + b.records)
    assert _derive_reading(_time_model(), reading)[0] is None
    assert reading._clock_issues[0]["kind"] == "concurrent_runs"


def test_t5_q6_require_boot_now_and_forward_time():
    model, h = _time_model(), History()
    view = View(model=model, frontier=frozenset(), belief=Ref(K.PREDICTION, "b"), reading=read(model, ()))
    with pytest.raises(ValueError):
        plan(replace(view, now_ns=0), model.actions, u=.5)
    h.observe()
    h.outcome("o0", 2)
    view = replace(view, reading=read(model, h.records))
    for now in (None, 0, True):
        with pytest.raises(ValueError):
            plan(replace(view, now_ns=now), model.actions, u=.5)
    later = History("r2", 1, wall=110)
    later.observe(5)
    last = h.add(Prediction(target="irrelevant", about=(), basis=(), contract=BELIEF,
                            content=Payload.json({})), 8)
    # 葉で壁時計が戻っても、軸へ渡すのは出来事だけ。
    h.records[-1] = replace(last, at=replace(last.at, wall_ns=90 * NS))
    events = [r for r in h.records + later.records
              if r.category in (Category.FACT, Category.INTENTION)]
    axis = timeline(events)
    data = _plan(model, events, axis.to_axis(later.run, 7 * NS) / NS)
    # L=軸2・壁102、K=単調5・壁115。起動は2+(115-102)=15、今は17。
    assert axis.to_axis(later.run, 5 * NS) == 15 * NS
    assert data["time"]["now_ns"] == 17 * NS
    assert data["time"]["dt_s"] == 15.  # (2-2)+(115-102)+(7-5)


def test_t10_legacy_duplicates_keep_axis_and_belief_independent_of_input_order():
    model, h = _time_model(), History()
    h.observe()
    h.outcome("o0")
    original = h.outcome("o1", 2)
    early = replace(original, schema=2, body=replace(original.body, received_ns=None))
    h.records[-1] = early
    late = replace(early, at=replace(early.at, seq=early.at.seq + 1,
                                    mono_ns=20 * NS, wall_ns=100 * NS))
    next_run = History("r2", 1, wall=110)
    born = next_run.observe()
    next_run.outcome("o1")
    records = h.records + [late] + next_run.records
    expected = timeline(h.records + next_run.records)
    # 早い記録L=軸2・壁102から、次の起動は2+(110-102)=10。遅い方なら30。
    assert expected.received_ns[born.id] == 10 * NS
    contents = []
    for ordered in (records, records[::-1]):
        assert timeline(ordered) == expected
        reading = read(model, ordered)
        assert reading.timeline == expected
        assert reading.unread == {early.id: "no_receipt_time"}
        q, a = _derive_reading(model, reading)
        contents.append(Payload.json(Agent(model=model, lineage="time")._content(reading, q, a)))
    assert contents[0] == contents[1]


@pytest.mark.parametrize("changes", [
    {"run_index": 1, "seq": 1, "mono_ns": 0, "wall_ns": 0, "run": Ref(K.RUN, "r0")},
    {"seq": 11, "mono_ns": 0, "wall_ns": 0, "run": Ref(K.RUN, "r0")},
    {"mono_ns": 11, "wall_ns": 0, "run": Ref(K.RUN, "r0")},
    {"wall_ns": 101, "run": Ref(K.RUN, "r0")},
    {"run": Ref(K.RUN, "r2")},
])
def test_t10_legacy_representative_uses_time_tuple_priority(changes):
    record = History().observe()
    early = replace(record, schema=2, at=replace(record.at, seq=10, mono_ns=10, wall_ns=100),
                    body=replace(record.body, received_ns=None))
    late = replace(early, at=replace(early.at, **changes))
    assert _facts((early, late)) == _facts((late, early)) == (early,)


@pytest.mark.parametrize("reverse", [False, True])
def test_t10b_merge_adopt_and_restore_use_the_same_legacy_representative(reverse):
    model, h = _time_model(), History()
    h.observe()
    h.outcome("o0")
    original = h.outcome("o1", 2)
    early = replace(original, schema=2, body=replace(original.body, received_ns=None))
    late = replace(early, at=replace(early.at, seq=early.at.seq + 1,
                                    mono_ns=20 * NS, wall_ns=100 * NS))
    branches = []
    for legacy in (early, late):
        ledger = Ledger(salts=SequentialSalts())
        for record in [*h.records[:-1], legacy]:
            ledger.append(record, ledger.heads())
        ledger.verify()
        branches.append(ledger)
    # 因果上の位置が同じ候補で、cidの順は代表の時刻の順と逆にする。
    assert branches[1].entries_of(late.id)[0].cid < branches[0].entries_of(early.id)[0].cid
    merged, other = branches[::-1] if reverse else branches
    merged.merge(other)
    merged.verify()
    copies = [merged.record(e.cid) for e in merged.between((), merged.heads()) if e.id == early.id]
    assert copies == [late, early]
    later = History("r2", 1, wall=110)
    born = later.observe()
    result = later.outcome("o1")
    for record in later.records:
        merged.append(record, merged.heads())
    merged.verify()
    candidates = [*h.records[:-1], early, late, *later.records]
    expected_axis = timeline(candidates)
    # L=単調2・壁102、K=単調0・壁110なので、起動の軸は2+(110-102)=10。
    assert expected_axis.received_ns[born.id] == expected_axis.received_ns[result.id] == 10 * NS
    direct = read(model, candidates)
    q, a = _derive_reading(model, direct)
    # o0@0で9/11、10秒進めてp、o1の尤度(.1,.8)でp/(8-7p)。
    p = .5 + (9 / 11 - .5) * math.exp(-10)
    expected_q0 = p / (8 - 7 * p)
    subject = Agent(model=model, lineage="merged")
    expected_content = Payload.json(subject._content(direct, q, a))
    belief = subject.adopt(merged, clock=FakeClock(run=Ref(K.RUN, "reader"), run_index=2),
                           ids=SequentialIds("reader"))
    assert subject._reading.timeline == expected_axis
    assert subject._belief.body.content == expected_content
    data = belief.body.content.as_json()
    assert data["q"] == pytest.approx([expected_q0, 1 - expected_q0], rel=1e-12, abs=0)
    assert data["n"] == {"look": [1, 1, 0], "wait": [0, 0, 0]}
    assert data["time"] == {"anchor": str(result.id), "anchor_ns": 10 * NS, "clock_issues": []}
    assert data["unread"] == [{"id": str(early.id), "reason": "no_receipt_time"}]
    snapshot = merged.snapshot(subject.frontier)
    assert next(r for r in snapshot.records if r.id == early.id) == early
    assert len(merged.entries_of(early.id)) == 2  # 代表を読むだけで、元の点は消さない。
    restored = Agent.restore(model=model, lineage="restored", ledger=merged,
                             belief=merged.entries_of(belief.id)[0].cid)
    assert restored._reading.timeline == expected_axis
    assert restored._belief.body.content == expected_content
    merged.verify()


@pytest.mark.parametrize("seconds,q0,G,p", TABLE1)
def test_q1_time_changes_q_and_policy(seconds, q0, G, p):
    h = History()
    h.observe()
    h.outcome("o0")
    model = _time_model()
    q = transition(model.Q, float(seconds)) @ _q(model, h.records)
    _close(q, [q0, 1 - q0])
    data = _plan(model, h.records, seconds)
    _close(data["G"], [G, 1.0986122886681098])
    _close(data["q_pi"][0], p)
    static = _time_model(changing=False)
    static_data = _plan(static, h.records[1:], seconds)
    assert "time" not in static_data
    _close(static_data["G"], [.9196116365063846, 1.0986122886681098])
    _close(static_data["q_pi"][0], .6717261576384556)


def test_transition_semigroup_zero_and_bad_exponential(monkeypatch):
    Q = _time_model().Q
    assert np.array_equal(transition(Q, 0.), np.eye(2))
    _close(transition(Q, 5.), np.linalg.matrix_power(transition(Q, 1.), 5), atol=1e-15)
    for bad in (-1., math.inf, math.nan):
        with pytest.raises(ValueError):
            transition(Q, bad)
    with pytest.raises(TypeError):
        transition(Q, 1)
    monkeypatch.setattr("sui.inference._expm", lambda x: np.array([[1., -1e-13], [0., 1.]]))
    assert np.array_equal(transition(Q, 1.), np.eye(2))
    monkeypatch.setattr("sui.inference._expm", lambda x: np.array([[1., -1e-11], [0., 1.]]))
    with pytest.raises(FloatingPointError):
        transition(Q, 1.)


def test_q2_q3_subdivision_and_same_time_static_limit():
    h = History()
    h.observe()
    for outcome in ("o0", "o0", "o1"):
        h.outcome(outcome)
    changing, static = _time_model(), _time_model(changing=False)
    _close(_q(changing, h.records), [.7168141592920354, .2831858407079647], atol=1e-15)
    static_records = h.records[1:]
    _close(_q(changing, h.records), _q(static, static_records), atol=1e-15)
    a, b = _plan(changing, h.records, 0), _plan(static, static_records, 0)
    for key in ("G", "q_pi", "risk", "ambiguity", "novelty", "q_o"):
        _close(a[key], b[key], atol=1e-15)
    reordered = History()
    reordered.observe()
    for outcome in ("o1", "o0", "o0"):
        reordered.outcome(outcome)
    _close(_q(changing, reordered.records), _q(changing, h.records), atol=1e-15)
    _close(_plan(changing, reordered.records, 0)["G"], a["G"], atol=1e-15)
    h.outcome("o0", 2)
    before = _q(changing, h.records)
    for i in range(20):
        h.add(Prediction(target="irrelevant", about=(), basis=(), contract=BELIEF,
                         content=Payload.json({})), i / 10)
        h.add(Decided(inputs=(), contract=DECISION, content=Payload.json({})), i / 10)
    _close(_q(changing, h.records), before, atol=1e-15)
    _, counts_a = _derive_reading(changing, read(changing, h.records))
    _, counts_b = _derive_reading(static, read(static, h.records[1:]))
    for action in changing.actions:
        assert np.array_equal(counts_a[action], counts_b[action])


@pytest.mark.parametrize("world, observations, expected", [
    ("W2", [("o0", 0), ("o0", 2), ("o1", 5)], TABLE2),
    ("W2", [("o1", 0), ("o0", 2), ("o0", 5)], [.826464303355500240, 1-.826464303355500240]),
    ("W3", [("o1", 0), ("o0", 1.5), ("o1", 4)], TABLE4),
])
def test_q4_q4b_sequential_filter_fixed_tables(world, observations, expected):
    h = History()
    h.observe()
    for outcome, seconds in observations:
        h.outcome(outcome, seconds)
    model = _time_model(world=world)
    _close(_q(model, h.records), expected)
    _close(_q(model, h.records[::-1]), expected)


def test_q8_q9_q13_reachability_is_transitive_but_not_time_specific():
    Q = np.array([[-1., 0., 0.], [1., -1., 0.], [0., 1., 0.]])
    a = {"look": np.eye(3), "wait": np.array([[0., 0., 0.], [0., 0., 0.], [1., 1., 1.]])}
    model = _time_model(world="W3", Q=Q, D=np.array([1., 0., 0.]), a=a)
    assert reachable(model.D, Q).tolist() == [True, True, True]
    for seconds in (0, 1):
        h = History()
        h.observe()
        obs = h.outcome("none", seconds)
        assert obs.id not in read(model, h.records).unread
        if seconds:
            _close(_q(model, h.records), [0., 0., 1.])
        else:
            assert _q(model, h.records) is None
            with pytest.raises(ModelFalsified):
                _plan(model, h.records, 0)
    disconnected = replace(model, Q=np.array([[-1., 0., 0.], [1., 0., 0.], [0., 0., 0.]]))
    assert read(disconnected, h.records).unread[obs.id] == "impossible"
    h = History()
    h.observe()
    obs = h.outcome("o1", 1)
    wp = _time_model(world="WP", D=np.array([1., 0.]))
    _close(_q(wp, h.records), [0., 1.])
    assert read(replace(wp, Q=None), h.records).unread[obs.id] == "impossible"


def test_q10_recover_after_probability_underflow_in_receipt_order():
    h = History()
    h.observe()
    for outcome in ["o0"] * 600 + ["o1"] * 700:
        h.outcome(outcome)
    q = _q(_time_model(), h.records[::-1])
    assert q[0] > 0 and q[1] == TABLE5[1]
    assert abs(math.log(q[0]) - math.log(TABLE5[0])) < 1e-9
    sequence = read(_time_model(), h.records[::-1]).sequence
    assert all(item[-1] == "o0" for item in sequence[:600])
    assert all(item[-1] == "o1" for item in sequence[600:])


def test_q12_direct_log_counts_do_not_round_rare_observation_to_zero():
    model = _time_model(D=np.array([.9, .1]), a={
        "look": np.array([[1e-300, 1e-300], [1e300, 1e300], [0., 0.]]),
        "wait": np.array([[0., 0.], [0., 0.], [1., 1.]])})
    h = History()
    h.observe()
    observation = h.outcome("o0")
    assert observation.id not in read(model, h.records).unread
    _close(_log_A(model.a["look"])[0], [-1381.5510557964274] * 2)
    _close(_q(model, h.records), model.D, atol=1e-15)


def test_q11_pending_measures_now_fixed_table6():
    h = History()
    h.observe()
    h.outcome("o0")
    h.attempt()
    data = _plan(_time_model(), h.records, 1)
    _close([data["risk"][0], data["ambiguity"][0], *data["G"], data["q_pi"][0]], TABLE6)
    assert data["time"]["pending_measures"] == "now"
    assert data["novelty"] == [0., 0.]


def test_h1_h2_h5_h6_h7_arrival_statistics_and_subdivision():
    model = _arrival_model()
    h = History()
    origin = h.observe()
    h.listen(0, True)
    first = h.arrival(5)
    second = h.arrival(12)
    h.listen(30, False)
    outside = h.arrival(31)
    reading = read(model, h.records + [first])
    stats = reading.arrivals["letter"]
    assert stats == ArrivalStats(N=2, T_ns=30 * NS, outside=(outside.id,))
    assert first.id != second.id and first.body.content == second.body.content
    assert first.id not in reading.unread and second.id not in reading.unread
    assert origin.id not in reading.unread
    assert arrival_posterior(model.arrivals["letter"], stats) == (3., 40.)
    _close(arrival_within(3., 40., 10.), .488)
    split = History()
    split.observe()
    for start in range(0, 30, 3):
        split.listen(start, True)
        split.listen(start + 3, False)
    split.arrival(5)
    split.arrival(12)
    assert read(model, split.records).arrivals["letter"] == ArrivalStats(N=2, T_ns=30 * NS)


def test_h3_h4_h9_runs_and_crash_tail_are_not_silence():
    a, b = History(), History("r2", 1, wall=1100)
    a.observe()
    a.listen(0, True)
    a.listen(30, False)
    b.observe()
    b.listen(0, True)
    b.arrival(20)
    model = _arrival_model()
    assert read(model, a.records + b.records).arrivals["letter"].T_ns == 50 * NS
    crash = History()
    crash.observe()
    crash.listen(0, True)
    crash.arrival(25)
    crash.add(Prediction(target="belief", about=(), basis=(), contract=BELIEF,
                         content=Payload.json({})), 28)
    stats = read(model, crash.records).arrivals["letter"]
    assert stats.T_ns == 25 * NS
    static = read(_time_model(changing=False), crash.records)
    assert static.timeline is None and not static.arrivals
    assert set(static.unread.values()) == {"no_attempt"}


def test_h6_same_record_on_different_parents_counts_once_after_merge():
    h = History()
    h.observe()
    h.listen(0, True)
    base = Ledger(salts=SequentialSalts())
    for record in h.records:
        base.accept(record)
    left_parent = h.arrival(3, route="other", name="left")
    right_parent = h.arrival(3, route="other", name="right")
    shared = h.arrival(5, name="shared")
    ledgers = []
    for parent in (left_parent, right_parent):
        ledger = Ledger(salts=SequentialSalts())
        ledger.merge(base)
        ledger.accept(parent)
        ledger.accept(shared)
        ledgers.append(ledger)
    ledgers[0].merge(ledgers[1])
    assert len(ledgers[0].entries_of(shared.id)) == 2
    stats = read(_arrival_model(), ledgers[0].snapshot(ledgers[0].heads()).records).arrivals["letter"]
    assert stats == ArrivalStats(N=1, T_ns=5 * NS)
    separate = h.arrival(5, name="separate")
    assert separate.body == shared.body
    ledgers[0].accept(separate)
    assert read(_arrival_model(), ledgers[0].snapshot(ledgers[0].heads()).records).arrivals["letter"].N == 2


def test_h10_multiple_routes_ties_and_repeated_changes():
    model = _time_model(changing=False, arrivals={r: ArrivalPrior(alpha=1., beta_s=10.) for r in ("a", "b")})
    h = History()
    h.observe()
    h.listen(5, True, "a", name="z_open")
    h.listen(5, False, "a", name="a_close")
    h.listen(0, True, "b")
    h.listen(3, True, "b")
    h.arrival(6, route="a")
    h.arrival(6, route="b")
    h.listen(8, False, "b")
    h.listen(9, False, "b")
    bad = h.observe(10, contract=LISTEN, content={"route": "b", "open": 1})
    reading = read(model, h.records[::-1])
    assert reading.arrivals["a"].T_ns == 0 and reading.arrivals["a"].N == 0
    assert reading.arrivals["b"].T_ns == 8 * NS and reading.arrivals["b"].N == 1
    assert reading.unread[bad.id] == "content"


@pytest.mark.parametrize("seconds,expected", TABLE3)
def test_h11_table3_and_small_horizon(seconds, expected):
    alpha, beta = arrival_posterior(ArrivalPrior(alpha=1., beta_s=10.), ArrivalStats(N=2, T_ns=seconds * NS))
    _close(arrival_within(alpha, beta, 10.), expected)
    assert arrival_within(alpha, beta, 0.) == 0.
    assert abs(arrival_within(alpha, beta, 1e-12) / (alpha * 1e-12 / beta) - 1) < 1e-9
    for bad in (-1., math.nan, math.inf):
        with pytest.raises(ValueError):
            arrival_within(alpha, beta, bad)
    for bad in (1, True, "1"):
        with pytest.raises(TypeError):
            arrival_within(alpha, beta, bad)


def test_h11b_arrival_within_avoids_ratio_overflow():
    assert arrival_within(1e-4, 1e-305, 1e5) == pytest.approx(
        0.06889212453216966, rel=1e-12, abs=0)


def test_v3_v4_v5_receipt_validation_and_symmetric_admission():
    h = History()
    record = h.observe()
    with pytest.raises(TypeError):
        replace(record.body, received_ns=True)
    with pytest.raises(ValueError):
        replace(record, body=replace(record.body, received_ns=1))
    later = replace(record, at=replace(record.at, seq=2, run=Ref(K.RUN, "other")))
    for a, b in ((record, later), (later, record)):
        with pytest.raises(IdConflict):
            admit(a, b)
    legacy = replace(record, schema=2, body=replace(record.body, received_ns=None))
    legacy_later = replace(legacy, at=later.at)
    assert admit(legacy, legacy_later) == admit(legacy_later, legacy) == Admission.DUPLICATE
    for a, b in ((legacy, record), (record, legacy)):
        with pytest.raises(IdConflict):
            admit(a, b)
    current_without_receipt = replace(legacy, schema=3)
    for a, b in ((legacy, current_without_receipt), (current_without_receipt, legacy)):
        with pytest.raises(IdConflict) as exc:
            admit(a, b)
        assert exc.value.fields == ("schema",)
    assert admit(record, replace(record)) == Admission.DUPLICATE


def _legacy_header(record, salt):
    # 版2の骨組みを試験側で直接組み立てる。版3のcodecで期待値を作らない。
    at, p, b = record.at, record.producer, record.body
    data = {"schema": 2, "id": str(record.id),
        "at": {"run": str(at.run), "run_index": at.run_index, "seq": at.seq,
               "mono_ns": at.mono_ns, "wall_ns": at.wall_ns},
        "writer": record.writer.value,
        "producer": {"component": p.component, "code_version": p.code_version, "state": None},
        "body": {"type": "Observed", "route": b.route,
            "contract": {"name": b.contract.name, "version": b.contract.version},
            "caused_by": None if b.caused_by is None else str(b.caused_by),
            "source_id": b.source_id, "source_time_ns": b.source_time_ns},
        "parents": [], "seal": seal(b.content, salt)}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def test_v1_v2_mixed_versions_sqlite_reopen_verify_merge_and_static_rebuild(tmp_path):
    h = History()
    obs = h.arrival(0)
    salt = bytes(range(16))
    header = _legacy_header(obs, salt)
    cid = "sha256:" + hashlib.sha256(header).hexdigest()
    legacy = decode_record(header, obs.body.content)
    assert legacy.schema == 2 and legacy.body.received_ns is None
    assert encode_header(legacy, seal(obs.body.content, salt), frozenset()) == header
    assert entry_from_header(cid, header).cid == cid
    with SqliteStore.open(tmp_path, create=True) as store:
        store.contents.put(seal(obs.body.content, salt), salt, obs.body.content)
        store.entries.add(cid, header)
        ledger = Ledger(salts=SequentialSalts(), contents=store.contents, entries=store.entries)
        ledger.accept(h.arrival(1))
        ids = SequentialIds(prefix="rebuild")
        # 同runのseq衝突を避け、復元用の派生物は別runから書く。
        clock = FakeClock(run=Ref(K.RUN, "restore"), run_index=1)
        agent = Agent(model=_time_model(changing=False), lineage="time")
        belief = agent.adopt(ledger, clock=clock, ids=ids)
        belief_cid = ledger.entries_of(belief.id)[0].cid
        expected = belief.body.content
        ledger.verify()
    with SqliteStore.open(tmp_path) as store:
        ledger = Ledger(salts=SequentialSalts(), contents=store.contents, entries=store.entries)
        ledger.verify()
        copy = Ledger(salts=SequentialSalts())
        copy.merge(ledger)
        copy.verify()
        restored = Agent.restore(model=_time_model(changing=False), lineage="time",
                                 ledger=copy, belief=belief_cid)
        assert restored._belief.body.content == expected
        assert copy.record(cid).schema == 2


def _rig(model=None, *, threaded=False, drive=None, clock=None):
    model = _time_model() if model is None else model
    rig = SimpleNamespace(model=model, agent=Agent(model=model, lineage="time"),
        ledger=Ledger(salts=SequentialSalts()), ids=SequentialIds(),
        clock=clock or FakeClock(run=Ref(K.RUN, "r1")),
        membrane=Producer(component="test.time", code_version="1"),
        hand=GatedHand({"look": {"eye"}, "wait": set()}, {"look": ["o0"] * 10, "wait": ["none"] * 10}),
        drive=drive or ScriptDrive(), capacity={"think": 1, "eye": 1})
    rig.agent.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
    def make(pledges):
        return Window(agent=rig.agent, ledger=rig.ledger, ids=rig.ids, clock=rig.clock,
            membrane=rig.membrane, route="executor", hand=rig.hand, drive=rig.drive,
            capacity=rig.capacity, pledges=pledges)
    rig.make = make
    rig.host = ThreadHost(make, clock=rig.clock) if threaded else ManualHost(make, clock=rig.clock)
    return rig


def _events(rig, contract=None):
    return [rig.ledger.record(e.cid) for e in rig.ledger.entries()
            if e.body_type is Observed and (contract is None or rig.ledger.record(e.cid).body.contract == contract)]


def _post(rig, event):
    rig.host.post(event)
    rig.host.step()


def _request(rig, *, u=0.):
    event = Tick(mono_ns=rig.clock.mono_ns())
    rig.drive.rules += (lambda status, arrived: (
        [Reconsider(candidates=rig.model.actions, u=u)] if arrived is event else []),)
    _post(rig, event)


def _think(rig):
    _request(rig)
    return [work for work, _ in rig.host.work if isinstance(work, Think)][-1]


def _act(rig):
    thinking = _think(rig)
    rig.host.finish(thinking)
    rig.host.step()
    return [work for work, _ in rig.host.work if isinstance(work, Act)][-1]


def test_j1_clock_read_and_both_host_envelopes_are_monotone():
    for clock in (FakeClock(run=Ref(K.RUN, "fake")), SystemClock(run=Ref(K.RUN, "system"), run_index=0)):
        before = clock.now()
        stamps = [clock.mono_ns() for _ in range(100)]
        after = clock.now()
        assert after.seq == before.seq + 1 and stamps == sorted(stamps)
    for threaded in (False, True):
        r = _rig(threaded=threaded)
        first = r.host._current if threaded else r.host.current
        assert first.number == 1 and isinstance(first.event, Boot)
        r.clock.advance(NS)
        r.host.post(Tick(mono_ns=NS))
        r.clock.advance(NS)
        r.host.post(Tick(mono_ns=2 * NS))
        envelopes = ([r.host._queue.get_nowait(), r.host._queue.get_nowait()] if threaded else list(r.host.queue))
        assert [e.number for e in envelopes] == [2, 3]
        assert [e.received_ns for e in envelopes] == [NS, 2 * NS]


def test_t4_tick_subdivision_does_not_change_facts_or_view():
    outputs = []
    for count in (1, 100):
        r = _rig()
        r.host.step()
        for _ in range(count):
            r.clock.advance(NS // count)
            _post(r, Tick(mono_ns=r.clock.mono_ns()))
        thinking = _think(r)
        outputs.append((r.ledger.entries(), thinking.view.frontier, thinking.now_ns,
                        plan(thinking.view, thinking.candidates, u=thinking.u).content))
    assert outputs[0] == outputs[1]


def test_q5_j2_j5_receipt_precedes_record_and_accept_is_atomic():
    r = _rig(_time_model(D=np.array([.9, .1])))
    r.host.step()
    work = _act(r)
    r.clock.advance(NS)
    r.host.post(Done(attempt=work.attempt, outcome="o0"))
    r.clock.advance(8 * NS)
    r.host.step()
    observation = _events(r, OUTCOME)[0]
    assert observation.body.received_ns == NS and observation.at.mono_ns == 9 * NS
    assert r.agent._reading.sequence[0][0] == NS
    reading = r.agent._belief.body.content.as_json()
    assert reading["time"]["anchor_ns"] == NS
    prior0 = .5 + .4 * math.exp(-1.)
    expected0 = .9 * prior0 / (.9 * prior0 + .2 * (1 - prior0))
    _close(r.agent.q, [expected0, 1 - expected0])
    before = r.host.pledges.latest_ns
    original = r.host.window.ids
    class Fails:
        def new(self, kind):
            raise RuntimeError("accept failed")
    r.host.window.ids = Fails()
    with pytest.raises(RuntimeError):
        r.host.window.accept(Envelope(number=100, event=Done(attempt=work.attempt, outcome="o1"), received_ns=2 * NS))
    assert r.host.pledges.latest_ns == before and not r.host.pledges.items
    r.host.window.ids = original
    r.host.window.accept(Envelope(number=100, event=Done(attempt=work.attempt, outcome="o1"), received_ns=2 * NS))
    assert r.host.pledges.latest_ns == (r.clock.run, 2 * NS)
    staged = r.host.pledges.items[0].record
    r.host.window = r.make(r.host.pledges)
    r.host.window.settle()
    assert r.ledger.record(r.ledger.entries_of(staged.id)[0].cid) == staged
    r.host.window.accept(Envelope(number=101, event=Tick(mono_ns=3 * NS), received_ns=3 * NS))
    assert r.host.pledges.latest_ns == (r.clock.run, 3 * NS)


@pytest.mark.parametrize("rebuild", [False, True])
def test_j3_waiting_request_uses_latest_receipt_and_think_survives_rebuild(rebuild):
    r = _rig()
    r.host.step()
    action = _act(r)
    first = _think(r)
    r.clock.advance(NS)
    _request(r, u=.5)
    assert len(r.host.pledges.waiting) == 1
    r.clock.advance(NS)
    _post(r, Done(attempt=action.attempt, outcome="o0"))
    if rebuild:
        r.host.window = r.make(r.host.pledges)
        assert r.host.pledges.thinking[first.work] is first
        assert first.now_ns == 0
    r.clock.advance(NS)
    r.host.finish(first)
    r.host.step()
    second = list(r.host.pledges.thinking.values())[0]
    assert second.now_ns == second.view.now_ns == 3 * NS
    data = plan(second.view, second.candidates, u=second.u).content.as_json()
    assert data["time"]["anchor_ns"] == 2 * NS
    assert data["time"]["now_ns"] >= data["time"]["anchor_ns"]


def test_j6_adopt_across_runs_uses_events_after_waiting_and_window_rebuild():
    r = _rig(clock=FakeClock(run=Ref(K.RUN, "r1"), wall_ns=100 * NS))
    r.host.step()
    r.clock.advance(NS)
    _post(r, Arrived(
        route="letter", contract=OUTCOME, content=Payload.json({"outcome": "o1"})))
    action = _act(r)
    r.clock.advance(NS)
    r.host.finish(action)
    r.host.step()
    result, = [o for o in _events(r, OUTCOME) if o.body.caused_by == action.attempt]
    assert result.body.received_ns == 2 * NS and result.at.wall_ns == 102 * NS
    r.clock.advance(6 * NS)
    r.clock.set_wall(90 * NS)
    leaf = r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger)
    assert leaf.at.mono_ns == 8 * NS and leaf.at.wall_ns == 90 * NS

    r.clock = FakeClock(run=Ref(K.RUN, "r2"), run_index=1, mono_ns=5 * NS, wall_ns=115 * NS)
    r.host = ManualHost(r.make, clock=r.clock)
    r.host.step()
    first = _think(r)
    r.clock.advance(NS)
    _request(r, u=.5)
    assert len(r.host.pledges.waiting) == 1
    assert r.host.pledges.latest_ns == (r.clock.run, 6 * NS)
    r.host.window = r.make(r.host.pledges)
    r.host.window.settle()
    assert r.host.pledges.thinking[first.work] is first
    assert len(r.host.pledges.waiting) == 1
    r.clock.advance(NS)
    r.host.finish(first)
    r.host.step()
    second, = r.host.pledges.thinking.values()
    snapshot = r.ledger.snapshot(second.view.frontier)
    events = tuple(r.ledger.record(e.cid) for e in r.ledger.entries() if e.is_event)
    assert set(snapshot.records) == set(events)
    assert leaf not in snapshot.records
    expected = timeline(events)
    assert second.view.reading.timeline == expected
    # L=軸2・壁102、K=単調5・壁115。起動は15、単調7の今は17、anchorは結果の2。
    # 葉をLに混ぜると起動は8+(115-90)=33、今は35になり、この比較が落ちる。
    assert expected.to_axis(r.clock.run, 5 * NS) == 15 * NS
    assert first.now_ns == first.view.now_ns == 15 * NS
    assert second.now_ns == second.view.now_ns == expected.to_axis(r.clock.run, 7 * NS) == 17 * NS
    data = plan(second.view, second.candidates, u=second.u).content.as_json()
    assert data["time"] == {"anchor": str(result.id), "anchor_ns": 2 * NS,
                            "now_ns": 17 * NS, "dt_s": 15., "pending_measures": "now"}


def test_r10_r11_r13_results_are_facts_and_do_not_return_another_resource():
    r = _rig()
    r.host.step()
    first = _act(r)
    _post(r, Done(attempt=first.attempt, outcome="o0"))
    second = _act(r)
    assert r.host.window.status().used["eye"] == 1
    calls = len(r.drive.calls)
    _post(r, Done(attempt=first.attempt, outcome="o1"))
    results = [o for o in _events(r, OUTCOME) if o.body.caused_by == first.attempt]
    assert len(results) == 2
    assert all(dict(r.agent.unread)[o.id] == "ambiguous_attempt" for o in results)
    assert r.host.window.status().awaiting == (second.attempt,)
    assert r.host.window.status().used["eye"] == 1
    _post(r, Failed(attempt=first.attempt, error="Error"))
    assert len(r.drive.calls) == calls + 2
    assert len(_events(r, ENDED)) == 1
    _post(r, Done(attempt=Ref(K.ATTEMPT, "unknown"), outcome="o0"))
    unknown = [o for o in _events(r, OUTCOME) if o.body.caused_by.value == "unknown"][0]
    assert dict(r.agent.unread)[unknown.id] == "unknown_attempt"
    _post(r, Done(attempt=second.attempt, outcome="o0"))
    _post(r, Failed(attempt=second.attempt, error="Error"))
    valid = [o for o in _events(r, OUTCOME) if o.body.caused_by == second.attempt][0]
    assert valid.id not in dict(r.agent.unread)


def test_r12_second_result_write_and_notice_failures_keep_each_receipt_once():
    r = _rig()
    r.host.step()
    action = _act(r)
    _post(r, Done(attempt=action.attempt, outcome="o0"))
    flaky = FlakyContents(r.ledger.contents)
    r.ledger.contents = flaky
    flaky.fail_next()
    second = Done(attempt=action.attempt, outcome="o1")
    r.host.post(second)
    with pytest.raises(StorageFull):
        r.host.step()
    staged = r.host.pledges.items[0].record
    successes = []
    failures = [True]
    def react(status, event):
        if event is second and failures:
            failures.pop()
            raise RuntimeError("notice failed")
        successes.append(event)
        return ()
    r.drive.react = react
    with pytest.raises(RuntimeError):
        r.host.step()
    assert len(_events(r, OUTCOME)) == 2
    r.host.post(Tick(mono_ns=0))
    r.host.step()
    assert sum(e is second for e in successes) == 1
    assert len(_events(r, OUTCOME)) == 2
    assert r.ledger.record(r.ledger.entries_of(staged.id)[0].cid) == staged


@pytest.mark.parametrize("threaded", [False, True])
def test_t9_boot_is_settled_before_queued_work_and_retry_does_not_duplicate(threaded):
    r = _rig(threaded=threaded, clock=FakeClock(run=Ref(K.RUN, "r1"), run_index=1))
    history = History("previous", 0)
    job = history.add(JobOpened(decision=Ref(K.DECISION, "d"), step=0,
        content=Payload.json({"action": "look"}), contract=ACTION))
    r.ledger.append(job, r.ledger.heads())
    flaky = FlakyContents(r.ledger.contents)
    r.ledger.contents = flaky
    flaky.fail_next()
    step = (lambda: r.host.run_until(lambda s: bool(s.awaiting), timeout=1.)) if threaded else r.host.step
    with pytest.raises(StorageFull):
        step()
    assert not r.hand.calls
    assert not any(e.body_type is AttemptStarted for e in r.ledger.entries())
    staged = r.host.pledges.items[0].record
    step()
    boots = _events(r, BOOT)
    assert len(boots) == 1 and boots[0] == staged
    attempt_entry = next(e for e in r.ledger.entries() if e.body_type is AttemptStarted)
    boot_entry = r.ledger.entries_of(boots[0].id)[0]
    assert boot_entry.cid in r.ledger.ancestors(attempt_entry.parents)


def test_q7_m12_h8_restore_and_old_forecast_is_fixed(tmp_path):
    model = _arrival_model(learnable=frozenset({"look"}))
    r = _rig(model)
    r.host.step()
    _post(r, Listen(route="letter", open=True))
    action = _act(r)
    _post(r, Done(attempt=action.attempt, outcome="o0"))
    old = r.agent._belief
    r.clock.advance(5 * NS)
    from sui.runtime import Arrived
    _post(r, Arrived(route="letter", content=Payload.text("opaque"), contract=ContractRef("unknown", "1")))
    data = r.agent._belief.body.content.as_json()
    assert data["arrivals"]["letter"]["N"] == 1
    assert old.body.content.as_json()["arrivals"]["letter"]["N"] == 0
    records = r.ledger.snapshot(r.agent.frontier).records
    static = replace(model, arrivals={})
    q, a = _derive_reading(static, read(static, records))
    assert r.agent.q.tobytes() == q.tobytes()
    for action in model.actions:
        assert r.agent.counts(action).tobytes() == a[action].tobytes()
    with SqliteStore.open(tmp_path, create=True) as store:
        store.models.put(model)
        ledger = Ledger(salts=SequentialSalts(), contents=store.contents, entries=store.entries)
        ledger.merge(r.ledger)
        belief = r.ledger.entries_of(r.agent._belief.id)[0].cid
        rebuilt = Agent.restore(model=model, lineage="time", ledger=ledger, belief=belief)
        assert rebuilt._belief.body.content == r.agent._belief.body.content
    assert "time" not in _plan(model, records, 5)


def test_q7_changing_belief_restore_and_rebuild_detects_tampering():
    r = _rig()
    r.host.step()
    action = _act(r)
    r.clock.advance(NS)
    _post(r, Done(attempt=action.attempt, outcome="o0"))
    entry = r.ledger.entries_of(r.agent._belief.id)[0]
    restored = Agent.restore(model=r.model, lineage="time", ledger=r.ledger, belief=entry.cid)
    assert restored.q.tobytes() == r.agent.q.tobytes()
    data = r.agent._belief.body.content.as_json()
    data["time"]["anchor_ns"] += 1
    bad = replace(r.agent._belief, id=Ref(K.PREDICTION, "tampered"),
                  body=replace(r.agent._belief.body, content=Payload.json(data)))
    bad_entry = r.ledger.append(bad, entry.parents)
    with pytest.raises(RebuildMismatch, match="time"):
        Agent.restore(model=r.model, lineage="time", ledger=r.ledger, belief=bad_entry.cid)


def test_j4_time_model_synchronous_and_window_cids_match_without_clock_advance():
    manual = _rig()
    manual.host.step()
    sync = _rig()
    boot(sync.agent, clock=sync.clock, ids=sync.ids, ledger=sync.ledger, membrane=sync.membrane)
    world = ScriptedWorld({"look": ["o0"] * 3})
    for _ in range(3):
        action = _act(manual)
        manual.host.finish(action)
        manual.host.step()
        run_step(sync.agent, world, sync.model.actions, u=0., clock=sync.clock,
                 ids=sync.ids, ledger=sync.ledger, membrane=sync.membrane)
    assert [e.cid for e in manual.ledger.entries()] == [e.cid for e in sync.ledger.entries()]


def test_filter_log_keeps_inputs_and_impossibility_in_log_space():
    model = _time_model(D=np.array([1., 0.]))
    D, Q, likelihood = model.D.copy(), model.Q.copy(), np.array([-np.inf, 0.])
    originals = [value.copy() for value in (D, Q, likelihood)]
    result = filter_log(D, Q, [(0, likelihood), (NS, np.zeros(2))])
    assert np.isneginf(result).all()
    for value, before in zip((D, Q, likelihood), originals):
        assert np.array_equal(value, before)
    assert np.array_equal(filter_log(D, Q, []), [0., -np.inf])
    for sequence, error in (
        ([(True, likelihood)], TypeError),
        ([(NS, likelihood), (0, likelihood)], ValueError),
        ([(0, [0., 0.])], TypeError),
        ([(0, np.zeros(3))], ValueError),
        ([(0, np.array([np.nan, 0.]))], ValueError),
        ([(0, np.array([np.inf, 0.]))], ValueError),
    ):
        with pytest.raises(error):
            filter_log(D, Q, sequence)


def test_t5_sync_decision_requires_current_run_boot_and_advances_birth_prior():
    r = _rig(_time_model(D=np.array([.9, .1])))
    args = dict(clock=r.clock, ids=r.ids, ledger=r.ledger)
    with pytest.raises(ValueError, match="current run boot"):
        r.agent.decide_s4c(r.model.actions, u=.5, now_mono_ns=0, **args)
    born = boot(r.agent, membrane=r.membrane, **args)
    r.clock.advance(NS)
    with pytest.raises(ValueError, match="now_mono_ns"):
        r.agent.decide_s4c(r.model.actions, u=.5, **args)
    decided, _ = r.agent.decide_s4c(r.model.actions, u=.5, now_mono_ns=NS, **args)
    data = decided.body.content.as_json()
    assert decided.body.contract == DECISION
    assert r.agent._belief.body.contract == BELIEF
    assert data["time"] == {"anchor": str(born.id), "anchor_ns": 0,
        "now_ns": NS, "dt_s": 1., "pending_measures": "now"}
    prior0 = .5 + .4 * math.exp(-1.)  # 対称2状態の独立な解析式。
    _close(data["q_o"][0], [.2 + .7 * prior0, .8 - .7 * prior0, 0.])
    next_clock = FakeClock(run=Ref(K.RUN, "r2"), run_index=1)
    with pytest.raises(ValueError, match="current run boot"):
        r.agent.decide_s4c(r.model.actions, u=.5, now_mono_ns=0,
                       clock=next_clock, ids=r.ids, ledger=r.ledger)


@pytest.mark.parametrize("threaded", [False, True])
def test_t9_j5_failed_boot_accept_keeps_envelope_and_receipt_order(threaded, monkeypatch):
    r = _rig(threaded=threaded)
    r.clock.advance(NS)
    r.host.post(Tick(mono_ns=NS))
    r.clock.advance(8 * NS)
    step = (lambda: r.host.run_until(
        lambda s: r.host.pledges.latest_ns == (r.clock.run, NS), timeout=1.)) if threaded else r.host.step
    def fail(kind):
        raise RuntimeError("boot accept failed")
    with monkeypatch.context() as patch:
        patch.setattr(r.ids, "new", fail)
        with pytest.raises(RuntimeError, match="boot accept"):
            step()
    assert r.host.pledges.latest_ns is None
    current = r.host._current if threaded else r.host.current
    assert current.number == 1 and current.received_ns == 0
    assert not _events(r)
    step()
    born, = _events(r, BOOT)
    assert born.body.received_ns == 0 and born.at.mono_ns == 9 * NS
    assert r.host.pledges.latest_ns == (r.clock.run, NS)
    assert r.agent._reading.timeline.received_ns[born.id] == 0


def test_q7_merged_entry_order_rebuilds_identical_time_belief():
    h, source = History(), Ledger(salts=SequentialSalts())
    h.observe()
    for outcome, seconds in (("o1", 0), ("o0", 1.5), ("o1", 4)):
        h.outcome(outcome, seconds)
    for record in h.records:
        source.append(record, source.heads())
    model = _time_model(world="W3")
    clock = FakeClock(run=Ref(K.RUN, "rebuild"), run_index=1)
    subject = Agent(model=model, lineage="merge")
    belief = subject.adopt(source, clock=clock, ids=SequentialIds(prefix="merge"))
    cid = source.entries_of(belief.id)[0].cid
    other = Ledger(salts=SequentialSalts())
    other.merge(SimpleNamespace(entries=lambda: tuple(reversed(source.entries())),
                               contents=source.contents, record=source.record))
    other.verify()
    restored = Agent.restore(model=model, lineage="merge", ledger=other, belief=cid)
    assert restored._content(restored._reading, restored._q, restored._a) == belief.body.content.as_json()
    _close(restored.q, TABLE4)


@pytest.mark.parametrize("key", ["N", "T_ns", "alpha", "beta_s", "outside"])
def test_q7_arrival_restore_checks_every_statistic(key):
    r = _rig(_arrival_model())
    r.host.step()
    entry = r.ledger.entries_of(r.agent._belief.id)[0]
    data = r.agent._belief.body.content.as_json()
    stats = data["arrivals"]["letter"]
    stats[key] = ["observation:outside"] if key == "outside" else stats[key] + 1
    bad = replace(r.agent._belief, id=Ref(K.PREDICTION, "tampered"),
                  body=replace(r.agent._belief.body, content=Payload.json(data)))
    bad_entry = r.ledger.append(bad, entry.parents)
    with pytest.raises(RebuildMismatch, match="arrivals"):
        Agent.restore(model=r.model, lineage="time", ledger=r.ledger, belief=bad_entry.cid)


def test_q7_clock_issue_restore_distinguishes_integer_from_bool():
    h = History("other", 0)
    r = _rig()
    r.host.step()
    r.ledger.accept(h.observe())
    belief = r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    entry = r.ledger.entries_of(belief.id)[0]
    data = belief.body.content.as_json()
    assert data["q"] is None
    assert data["time"]["clock_issues"][0]["run_index"] == 0
    data["time"]["clock_issues"][0]["run_index"] = False
    bad = replace(belief, id=Ref(K.PREDICTION, "tampered"),
                  body=replace(belief.body, content=Payload.json(data)))
    bad_entry = r.ledger.append(bad, entry.parents)
    with pytest.raises(RebuildMismatch, match="time"):
        Agent.restore(model=r.model, lineage="time", ledger=r.ledger, belief=bad_entry.cid)


def test_t7b_arrivals_do_not_require_time_for_static_learning_or_decisions():
    from sui.s1_contracts import DECISION as STATIC_DECISION
    model = _arrival_model(learnable=frozenset({"look"}))
    static = replace(model, arrivals={})
    h = History()
    legacy = h.outcome("o0")
    h.records[-1] = replace(legacy, schema=2, body=replace(legacy.body, received_ns=None))
    current = h.outcome("o1", 1)
    arrival = h.arrival(2)
    no_receipt = h.arrival(3)
    h.records[-1] = replace(no_receipt, schema=2, body=replace(no_receipt.body, received_ns=None))
    opened = h.listen(4, True)
    unrelated = h.arrival(5, route="other")
    reading = read(model, h.records)
    assert reading.unread == {arrival.id: "no_clock", no_receipt.id: "no_receipt_time",
                              opened.id: "no_clock", unrelated.id: "no_attempt"}
    assert reading.n["look"].tolist() == [1, 1, 0]
    assert legacy.id not in reading.unread and current.id not in reading.unread
    assert reading.timeline.origin is None and reading.sequence == ()
    assert reading.arrivals["letter"] == ArrivalStats(N=0, T_ns=0)
    q, a = _derive_reading(model, reading)
    static_reading = read(static, h.records)
    static_q, static_a = _derive_reading(static, static_reading)
    assert q.tobytes() == static_q.tobytes()
    for action in model.actions:
        assert a[action].tobytes() == static_a[action].tobytes()
    common = dict(frontier=frozenset(), belief=Ref(K.PREDICTION, "comparison"))
    expected = plan(View(model=static, reading=static_reading, **common), model.actions, u=.5)
    actual = plan(View(model=model, reading=reading, **common), model.actions, u=.5)
    assert actual.content == expected.content and "time" not in actual.content.as_json()
    r = _rig(model, clock=FakeClock(run=Ref(K.RUN, "reader"), run_index=1))
    for record in h.records:
        r.ledger.append(record, r.ledger.heads())
    r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    decided, _ = r.agent.decide_s4c(model.actions, u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger)
    assert decided.body.contract == STATIC_DECISION
    assert decided.body.content == expected.content
    assert r.agent._belief.body.contract == BELIEF
    # ホストを起動せず、窓口もQなしなら現在runの起動を要求しない。
    r.drive.rules = (lambda s, e: [Reconsider(candidates=model.actions, u=.5)]
                     if isinstance(e, Tick) else [],)
    window = r.make(Pledges())
    window.accept(Envelope(number=1, event=Tick(mono_ns=0), received_ns=0))
    window.settle()
    work = next(w for w in window.drain() if isinstance(w, Think))
    assert work.now_ns is None and work.view.now_ns is None
    assert "time" not in plan(work.view, work.candidates, u=work.u).content.as_json()
    assert not _events(r, BOOT)


@pytest.mark.parametrize("threaded", [False, True])
def test_p11_static_host_records_boot_and_listen_without_changing_numbers(threaded):
    r = _rig(_time_model(changing=False), threaded=threaded)
    before = r.agent._belief.body.content.as_json()
    decision = plan(r.agent.view(), r.model.actions, u=.5).content
    if threaded:
        assert r.host.run_until(lambda s: True, timeout=1.)
    else:
        r.host.step()
    born, = _events(r, BOOT)
    assert born.body.route == "membrane" and born.body.content.as_json() == {}
    assert born.body.caused_by is None and born.body.received_ns == 0
    assert r.agent._belief.body.content.as_json()["unread"] == [
        {"id": str(born.id), "reason": "no_attempt"}]
    for opened in (True, False):
        r.clock.advance(NS)
        r.host.post(Listen(route="letter", open=opened))
        if threaded:
            count = 1 if opened else 2
            assert r.host.run_until(lambda s: len(_events(r, LISTEN)) == count, timeout=1.)
        else:
            r.host.step()
    changes = sorted(_events(r, LISTEN), key=lambda record: record.at.seq)
    assert [r.body.content.as_json() for r in changes] == [
        {"route": "letter", "open": True}, {"route": "letter", "open": False}]
    assert [r.body.received_ns for r in changes] == [NS, 2 * NS]
    assert dict(r.agent.unread) == {o.id: "no_attempt" for o in [born, *changes]}
    after = r.agent._belief.body.content.as_json()
    assert Payload.json({**after, "unread": before["unread"]}) == Payload.json(before)
    assert plan(r.agent.view(), r.model.actions, u=.5).content == decision


@pytest.mark.parametrize("drive_request", [Reconsider(candidates=("look",), u=.5),
                                     Abandon(job=Ref(K.JOB, "job"))])
def test_requests_come_only_from_drive_not_host_envelopes(drive_request):
    r = _rig()
    r.host.step()
    before = r.host.pledges.latest_ns, r.ledger.entries()
    with pytest.raises(TypeError, match="host or worker event"):
        r.host.window.accept(Envelope(number=2, event=drive_request, received_ns=NS))
    assert (r.host.pledges.latest_ns, r.ledger.entries()) == before
    assert not r.host.pledges.requests and not r.host.pledges.waiting
