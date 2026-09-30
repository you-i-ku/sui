"""S4c v0.5。M13〜M14・F1〜F3・E1〜E6・I1〜I3・P1〜P3・J7〜J15。

表の定数は仕様書の値。前向きの表は別の状態の道の総当たりとも照合する。
"""

from dataclasses import FrozenInstanceError, replace
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from sui.agent import Agent, ModelFalsified, View, plan_s4c as plan, read, _derive_reading, _filtered, replay_decision
from sui.contracts import ContractBook, ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.inference import (ModelViolation, remaining, _hand_efe, _hand_joint_log,
                           _log_A, _log_predict, _log_probability)
from sui.ledger import Ledger, SequentialSalts
from sui.loop import boot, run_step
from sui.model import model_json, model_from_json, model_ref, _duration_ns
from sui.records import AttemptStarted, JobOpened, Payload, Producer, Role
from sui.runtime import Think, Tick, Done, Reconsider, Window, _perform
from sui.s1_contracts import ACTION
from sui.s4d_contracts import DECISION as S4D_DECISION, DECLARATIONS as S4D_DECLARATIONS
from sui.s4_contracts import (BELIEF, DECISION, DECLARATIONS, HAND_BELIEF, HAND_DECISION,
                             HAND_DECLARATIONS)
from worlds import (_hand_model, _time_model, _close, _hand_path_efe, HandHistory,
                    ManualHost, GatedHand, ScriptDrive, ScriptedWorld)


NS = 1_000_000_000
LN3 = 1.0986122886681098
TABLE = {
    "A": (0.4054651091387413, 0.9411764703600107),
    "P1": (0.9583681969531193, 0.6366784226214939),
    "B": (0.8466604350233013, 0.7325908375713851),
    "B_report": (0.9553517906740111, 0.6394648022125252),
    "C": (0.8291680471895662, 0.7460730642998146),
    "C2": (0.8464004196977535, 0.732794537847708),
}
B_ANCHOR = (0.12934428710554718, 0.8706557128944529)
B_NOW = (0.3636433834733862, 0.6363566165266138)


def _view(model, records, now, observed=None):
    return View(model=model, frontier=frozenset(), belief=Ref(K.PREDICTION, "belief"),
        reading=read(model, records), now_ns=round(now * NS),
        observed_ns=round((now if observed is None else observed) * NS))


def _data(model, records, now, observed=None, candidates=("look", "wait")):
    return plan(_view(model, records, now, observed), candidates, u=.5).content.as_json()


def _scene(name, *, late=False):
    h = HandHistory()
    h.boot()
    if name == "A":
        model = _hand_model(world="WP2")
        pending = h.start("ask")
        return model, h, pending, 0
    if name == "P1":
        model = _hand_model(measure="start", duration=((0., .5), (2., .5)))
        first = h.start()
        h.observe(first, "o0", 0)
        return model, h, h.start(seconds=1), 1
    if name in ("B", "B_report"):
        model = (_hand_model(measure="start", duration=((.5, .5), (5., .5)))
                 if name == "B" else _time_model())
        first = h.start()
        if not late:
            h.observe(first, "o0", .5)
        pending = h.start(seconds=1)
        last = h.start(seconds=2)
        h.observe(last, "o1", 2.1 if name == "B_report" else 2.5)
        if late:
            h.observe(first, "o0", 3)
        return model, h, pending, 3
    model = _hand_model()
    first = h.start()
    h.observe(first, "o0", 1)
    return model, h, h.start(seconds=1.5), 3 if name == "C" else 2


def _check_table(data, name, atol=1e-12):
    g, probability = TABLE[name]
    _close(data["G"], [g, LN3], atol)
    _close(data["q_pi"], [probability, 1 - probability], atol)
    _close(data["G"], np.array(data["risk"]) + data["ambiguity"] - np.array(data["novelty"]), atol)
    _close(np.sum(data["q_o"], axis=1), [1., 1.], atol)


@pytest.mark.parametrize("duration", [(), ((-1., 1.),), ((math.nan, 1.),),
    ((math.inf, 1.),), ((1e308, 1.),), ((0., .5), (1e-10, .5)),
    ((1., 0.),), ((1., -1.),), ((1., math.nan),), ((1., math.inf),), ((1., .8),),
    ((1., .6), (2., .6)), ((True, 1.),), ((1.,),), None])
def test_m13_invalid_duration(duration):
    """秒・確率・nsの重複・あふれを構築時に拒む。"""
    with pytest.raises(ValueError):
        _hand_model(duration=duration)


@pytest.mark.parametrize("changes", [
    {"durations": {"look": ((1., 1.),)}},
    {"measures": {"look": "start"}},
    {"measures": {"look": "now", "wait": "report"}},
    {"durations": {}}, {"durations": {"extra": ((1., 1.),)}},
])
def test_m13_complete_actions_and_measurement_rules(changes):
    with pytest.raises(ValueError):
        _hand_model(**changes)


def test_m13_model_is_frozen_sorted_and_rounds_ties_to_even():
    model = _hand_model(duration=((4., .5), (1., .5)))
    assert model.durations["look"] == ((1., .5), (4., .5))
    assert [_duration_ns(d) for d in (0., 1e-10, .5e-9, 1.5e-9, 2.5e-9)] == [0, 0, 0, 2, 2]
    assert _hand_model(duration=((1e-10, 1.),)).durations["look"] == ((1e-10, 1.),)
    with pytest.raises(TypeError):
        model.durations["look"] = ()
    with pytest.raises(TypeError):
        model.measures["look"] = "start"
    with pytest.raises(FrozenInstanceError):
        model.durations = {}
    source = {"look": ((1., 1.),), "wait": ((0., 1.),)}
    measures = {"look": "start", "wait": "report"}
    copied = _hand_model(durations=source, measures=measures)
    source.clear()
    measures.clear()
    assert copied.durations["look"] == ((1., 1.),) and copied.measures["look"] == "start"
    with pytest.raises(ValueError, match="S4b"):
        _hand_model(learnable=frozenset({"look"}))
    assert _hand_model(Q=None, learnable=frozenset({"look"})).learnable == {"look"}


def test_m14_canonical_encoding_and_both_contract_versions():
    from test_ledger import _f4
    static = _f4()
    assert model_ref(static) == "sha256:568c5dd475ebe1518c227944556166aaf647328d2f86507dd696f82a06824fb2"
    for old in (static, _time_model()):
        assert model_json(old) == model_json(replace(old, durations={}, measures={}))
        assert model_ref(old) == model_ref(model_from_json(model_json(old)))
    for changing in (True, False):
        model = _hand_model(Q=_time_model().Q if changing else None)
        encoded = model_json(model)
        assert json.loads(encoded)["scheme"] == "sui.model.3"
        assert model_json(model_from_json(encoded)) == encoded
        bad = json.loads(encoded)
        bad["durations"]["look"].reverse()
        with pytest.raises(ValueError, match="canonical"):
            model_from_json(json.dumps(bad, sort_keys=True, separators=(",", ":")).encode())
        with pytest.raises(ValueError):
            model_from_json(encoded + b"\n")
    assert {(c.ref.name, c.ref.version) for c in HAND_DECLARATIONS} == {
        ("sui.s4.belief", "2"), ("sui.s4.decision", "2")}
    book = ContractBook()
    for declaration in DECLARATIONS + HAND_DECLARATIONS:
        book.register(declaration)
        assert book.get(declaration.ref) == declaration
    assert HAND_BELIEF == ContractRef("sui.s4.belief", "2")
    assert HAND_DECISION == ContractRef("sui.s4.decision", "2")


def test_f1_start_measurements_and_report_control_have_distinct_anchors():
    for name, anchor, now_q, stamp in (
        ("B", B_ANCHOR, B_NOW, 2 * NS),
        ("B_report", (.1393074145500926, .8606925854499073),
         (.35335333826267423, .6466466617373259), 2_100_000_000)):
        model, h, _, now = _scene(name)
        reading = read(model, h.records)
        _close(_derive_reading(model, reading)[0], anchor)
        assert reading.sequence[-1][0] == stamp
        _close(_log_probability(_log_predict(_filtered(model, reading), model.Q,
                                             (now * NS - stamp) / NS)), now_q)
        _check_table(_data(model, h.records, now), name)


def test_f2_late_old_measurement_is_reordered_and_smoothed():
    model, h, _, now = _scene("B", late=True)
    for records in (h.records, h.records[::-1], h.records[2:] + h.records[:2]):
        reading = read(model, records)
        _close(_derive_reading(model, reading)[0], B_ANCHOR)
        assert [row[0] for row in reading.sequence] == [0, 2 * NS]
        _check_table(_data(model, records, now), "B")


@pytest.mark.parametrize("learnable", [frozenset(), frozenset({"look"})])
def test_f3_static_start_without_clock_counts_like_model_without_durations(learnable):
    """Q なしは測定時刻不明でも回数から q・帳面を作り、Q ありだけ拒む。"""
    h = HandHistory()
    attempted = h.start()
    newer = HandHistory("r2", 1, wall=103)
    newer.boot()
    observed = newer.observe(attempted, "o0", 0)
    records = h.records + newer.records
    model = _hand_model(Q=None, measure="start", learnable=learnable)
    old = replace(model, durations={}, measures={})
    reading = read(model, records)
    old_reading = read(old, records)
    assert observed.id not in reading.unread
    assert reading.n["look"].tolist() == [1, 0, 0]
    q, a = _derive_reading(model, reading)
    old_q, old_a = _derive_reading(old, old_reading)
    assert np.array_equal(q, old_q)
    assert not np.array_equal(q, model.D)
    for action in model.actions:
        assert np.array_equal(reading.n[action], old_reading.n[action])
        assert np.array_equal(a[action], old_a[action])
    if learnable:
        assert not np.array_equal(a["look"], model.a["look"])
    changing = read(_hand_model(measure="start"), records)
    assert changing.unread[observed.id] == "no_clock"
    assert changing.n["look"].tolist() == [0, 0, 0]


@pytest.mark.parametrize("name", ["A", "P1", "B", "C", "C2"])
def test_i1_i2_i3_e1_p1_fixed_values(name):
    model, h, pending, now = _scene(name)
    candidates = ("peek", "wait") if name == "A" else ("look", "wait")
    before = tuple(h.records)
    data = _data(model, h.records, now, candidates=candidates)
    _check_table(data, name, atol=1e-15 if name == "P1" else 1e-12)
    assert tuple(h.records) == before
    assert data["novelty"] == [0., 0.]
    assert data["pending"] == [{"job": str(pending.body.job),
                                "action": "ask" if name == "A" else "look"}]
    assert data["time"]["measures"] == "model" and "pending_measures" not in data["time"]
    assert data["time"]["start_is"] == "attempt_record"
    assert data["time"]["candidate_start"] == data["time"]["queued_start"] == "now"
    if name == "A":
        _close(LN3 - data["G"][0], .6931471795293684)
        old = replace(model, durations={}, measures={})
        prior = _data(old, h.records, now, candidates=candidates)
        _close(prior["G"], [LN3, LN3])
        _close(prior["q_pi"], [.5, .5])


def test_e1_e4_remaining_is_normalized_inclusive_and_returns_total_duration():
    points = ((NS, .5), (4 * NS, .5))
    assert remaining(points, 1_500_000_000) == ((4 * NS, 1.),)
    assert remaining(points, NS) == points
    assert remaining(points, 4 * NS) == ((4 * NS, 1.),)
    assert remaining(((0, 1.),), 0) == ((0, 1.),)
    with pytest.raises(ModelViolation):
        remaining(points, 4 * NS + 1)


@pytest.mark.parametrize("changing", [True, False])
def test_e3_overdue_hand_prevents_thought_even_without_Q(changing):
    model = _hand_model(duration=((1., 1.),), Q=_time_model().Q if changing else None)
    h = HandHistory()
    h.boot()
    h.start()
    work = Think(work="think:1", view=_view(model, h.records, 2),
                 candidates=("look", "wait"), u=.5)
    with pytest.raises(ModelFalsified, match="the hand's time model cannot explain the facts"):
        plan(work.view, work.candidates, u=work.u)
    result = _perform(work, None)
    assert result.error == "ModelFalsified" and result.draft is None


def test_e5_unseen_time_does_not_change_belief_or_counts():
    model, h, _, _ = _scene("C")
    r = _rig(model, h)
    r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    beliefs, decisions = [], []
    for seconds in (2, 3):
        r.clock.advance(seconds * NS - r.clock.mono_ns())
        view = r.agent.view(now_ns=seconds * NS, observed_ns=seconds * NS)
        decisions.append(plan(view, ("look", "wait"), u=.5).content.as_json())
        beliefs.append(r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger).body.content)
    assert decisions[0]["G"] != decisions[1]["G"]
    assert beliefs[0] == beliefs[1]
    assert r.agent._reading.n["look"].tolist() == [1, 0, 0]


@pytest.mark.parametrize("learnable", [frozenset(), frozenset({"look"})])
def test_p2_static_model_uses_exact_S3_components_with_pending(learnable):
    model = _hand_model(Q=None, learnable=learnable, measure="start")
    h = HandHistory()
    h.boot()
    first = h.start()
    h.observe(first, "o0", .5)
    h.start(seconds=1)
    old = replace(model, durations={}, measures={})
    for before, after in zip(_derive_reading(old, read(old, h.records)),
                             _derive_reading(model, read(model, h.records))):
        if isinstance(before, dict):
            for action in before:
                assert np.array_equal(before[action], after[action])
        else:
            assert np.array_equal(before, after)
    old_data, new_data = _data(old, h.records, 2), _data(model, h.records, 2)
    time = new_data.pop("time")
    assert Payload.json(old_data) == Payload.json(new_data)
    assert time["anchor_ns"] == 0 and time["anchor"] == str(h.records[0].id)
    if learnable:
        assert new_data["novelty"][0] > 0


def _rig(model=None, history=None):
    model = _hand_model() if model is None else model
    h = HandHistory() if history is None else history
    ledger = Ledger(salts=SequentialSalts())
    for record in h.records:
        ledger.append(record, ledger.heads())
    r = SimpleNamespace(model=model, agent=Agent(model=model, lineage="hand_time"),
        ledger=ledger, clock=h.clock, ids=SequentialIds(prefix="runtime"), drive=ScriptDrive(),
        membrane=Producer(component="test.hand_time", code_version="1"),
        hand=GatedHand({a: set() for a in model.actions}, {a: ["none"] for a in model.actions}))
    r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger)
    def make(pledges):
        return Window(agent=r.agent, ledger=r.ledger, clock=r.clock, ids=r.ids,
            membrane=r.membrane, route="executor", hand=r.hand, drive=r.drive,
            capacity={"think": 1}, pledges=pledges)
    r.make = make
    r.host = ManualHost(make, clock=r.clock)
    return r


def _request(r, candidates=("look", "wait")):
    tick = Tick(mono_ns=r.clock.mono_ns())
    r.drive.rules += (lambda status, event: [Reconsider(candidates=candidates, u=.5)]
                     if event is tick else [],)
    r.host.post(tick)
    r.host.step()
    return next(reversed(r.host.pledges.thinking.values()))


def test_b_tick_and_j9_started_survive_window_rebuild():
    model, h, pending, now = _scene("B")
    r = _rig(model, h)
    r.host.step()
    r.clock.advance(round(now * NS) - r.clock.mono_ns())
    work = _request(r)
    _check_table(plan(work.view, work.candidates, u=work.u).content.as_json(), "B")
    assert work.view.reading.started[pending.body.job] == (NS,)
    r.host.window = r.make(r.host.pledges)
    r.host.window.settle()
    assert r.agent._reading.started[pending.body.job] == (NS,)
    with pytest.raises(TypeError):
        work.view.reading.started[pending.body.job] = ()


def test_e6_queued_result_keeps_past_report_time_not_now_plus_remaining():
    model = _hand_model(world="WP2", duration=((1.5, 1.),))
    h = HandHistory()
    h.boot()
    pending = h.start()
    known = h.start(seconds=1)
    h.observe(known, "o0", 1)
    r = _rig(model, h)
    r.host.step()
    tick = Tick(mono_ns=NS)
    r.drive.rules = (lambda status, event: [Reconsider(candidates=("peek", "wait"), u=.5)]
                    if event is tick else [],)
    r.host.post(tick)  # 1秒の封筒が先。
    r.clock.advance(500_000_000)
    r.host.post(Done(attempt=pending.id, outcome="o1"))  # 1.5秒の結果は列で待つ。
    # 別の取り込み済みの出来事を2秒に記録。受信は1秒。
    record = h.observe(known, "none", 1, recorded=2)
    r.ledger.accept(record)
    r.host.step()
    work, = r.host.pledges.thinking.values()
    assert work.now_ns == 2 * NS and work.observed_ns == NS
    assert len(r.host.queue) == 1 and r.host.queue[0].event.attempt == pending.id
    data = plan(work.view, work.candidates, u=work.u).content.as_json()
    _close(data["G"], [.5127839210742786, LN3])
    _close(data["q_pi"], [.9124012770456497, 1 - .9124012770456497])
    assert data["time"]["observed_ns"] == NS


@pytest.mark.parametrize("timed", [True, False])
def test_j7_j10_j13_evaluation_includes_attempt_but_not_leaf_or_fresh_clock(timed):
    model = _hand_model(duration=((5., 1.),)) if timed else _time_model()
    r = _rig(model)
    r.host.step()
    r.clock.advance(NS)
    tick = Tick(mono_ns=NS)
    r.drive.rules = (lambda status, event: [Reconsider(candidates=("look", "wait"), u=.5)]
                    if event is tick else [],)
    r.host.post(tick)
    r.clock.advance(100_000_000)
    from sui.records import Record
    job = Record(id=r.ids.new(K.JOB), at=r.clock.now(), writer=Role.MODEL, producer=r.agent.producer,
        body=JobOpened(decision=Ref(K.DECISION, "previous"), step=0, contract=ACTION,
                       content=Payload.json({"action": "look"})))
    r.ledger.append(job, r.ledger.heads())
    original = r.agent.adopt
    def delayed_leaf(*args, **kwargs):
        # 試みを始めた後の採用だけ葉を3秒に書く。評価に混ぜない。
        if any(e.body_type is AttemptStarted for e in r.ledger.entries()):
            r.clock.advance(3 * NS - r.clock.mono_ns())
        return original(*args, **kwargs)
    r.agent.adopt = delayed_leaf
    r.host.step()
    work, = r.host.pledges.thinking.values()
    expected = 1_100_000_000 if timed else NS
    assert work.now_ns == work.view.now_ns == expected
    assert work.observed_ns == work.view.observed_ns == (NS if timed else None)
    assert r.agent._belief.at.mono_ns == 3 * NS
    r.clock.advance(2 * NS)
    r.host.window = r.make(r.host.pledges)
    r.host.window.settle()
    assert r.host.pledges.thinking[work.work] is work
    assert work.now_ns == expected
    assert plan(work.view, work.candidates, u=work.u).content.as_json()["time"]["now_ns"] == expected


@pytest.mark.parametrize("changing", [True, False])
def test_j10_direct_read_ignores_late_belief_leaf(changing):
    """葉を直接渡しても読みと評価時刻は出来事だけで決まる (J10・X61)。"""
    from sui.agent import _evaluation_ns
    model, h, pending, _ = _scene("C")
    model = replace(model, Q=model.Q if changing else None)
    facts = tuple(h.records)
    r = _rig(model, h)
    h.at(3)
    leaf = r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    assert leaf.at.mono_ns == 3 * NS
    baseline = read(model, facts)
    with_leaf = read(model, (*facts, leaf))
    assert baseline._event_ns == {h.clock.run: 1_500_000_000}
    assert baseline.started == {pending.body.job: (1_500_000_000,)}
    assert baseline.sequence
    assert with_leaf._event_ns == baseline._event_ns
    assert with_leaf.started == baseline.started
    assert with_leaf.sequence == baseline.sequence
    assert with_leaf.pending == baseline.pending
    assert with_leaf.unread == baseline.unread
    for action in model.actions:
        assert np.array_equal(with_leaf.n[action], baseline.n[action])
    contents = []
    for reading in (baseline, with_leaf):
        observed = reading.timeline.to_axis(h.clock.run, NS)
        now = _evaluation_ns(reading, h.clock.run, observed)
        view = View(model=model, frontier=frozenset(), belief=leaf.id, reading=reading,
                    now_ns=now, observed_ns=observed)
        content = plan(view, ("look", "wait"), u=.5).content
        assert content.as_json()["time"]["now_ns"] == 1_500_000_000
        contents.append(content)
    assert contents[0] == contents[1]


@pytest.mark.parametrize("changing", [True, False])
def test_j8_static_duration_model_also_requires_boot_and_time(changing):
    model = _hand_model(Q=_time_model().Q if changing else None)
    r = _rig(model)
    with pytest.raises(ValueError, match="boot"):
        r.agent.decide_s4c(model.actions, u=.5, clock=r.clock, ids=r.ids, ledger=r.ledger, now_mono_ns=0)
    r.host.step()
    work = _request(r)
    assert work.now_ns == work.observed_ns == 0
    assert _perform(work, r.hand).draft is not None
    for changes in ({"now_ns": None}, {"observed_ns": None}, {"observed_ns": 1}):
        with pytest.raises(ValueError):
            plan(replace(work.view, **changes), model.actions, u=.5)


@pytest.mark.parametrize("requested_now,expected_now", [(0, 1_500_000_000), (2 * NS, 2 * NS)])
def test_j11_synchronous_default_observed_and_validation(requested_now, expected_now):
    model, h, _, _ = _scene("C")
    r = _rig(model, h)
    r.agent.adopt(r.ledger, clock=r.clock, ids=r.ids)
    r.clock.advance(500_000_000)
    decided, _ = r.agent.decide_s4c(("look", "wait"), u=.5, clock=r.clock, ids=r.ids,
                                ledger=r.ledger, now_mono_ns=requested_now)
    time = decided.body.content.as_json()["time"]
    assert time["observed_ns"] == NS and time["now_ns"] == expected_now
    assert decided.body.contract == HAND_DECISION
    before = r.ledger.entries()
    with pytest.raises(ValueError, match="observed"):
        r.agent.decide_s4c(("look", "wait"), u=.5, clock=r.clock, ids=r.ids,
            ledger=r.ledger, now_mono_ns=2 * NS, observed_mono_ns=3 * NS)
    assert r.ledger.entries() == before
    fresh = _rig(_hand_model())
    boot(fresh.agent, clock=fresh.clock, ids=fresh.ids, ledger=fresh.ledger, membrane=fresh.membrane)
    fresh.clock.advance(2 * NS)
    decided, _ = fresh.agent.decide_s4c(("look",), u=.5, clock=fresh.clock, ids=fresh.ids,
        ledger=fresh.ledger, now_mono_ns=2 * NS)
    assert decided.body.content.as_json()["time"]["observed_ns"] == 0


def test_j12_j14_earlier_run_uses_its_own_receipt_end():
    model = _hand_model(duration=((1.5, 1.),))
    h = HandHistory()
    h.boot()
    pending = h.start()
    known = h.start(seconds=1)
    h.observe(known, "o0", 1)
    newer = HandHistory("r2", 1, wall=103)
    newer.boot()
    records = h.records + newer.records
    view = _view(model, records, 3)
    assert view.reading.started[pending.body.job] == (0,)
    assert view.reading.timeline.run_end_ns[h.clock.run] == NS
    assert view.reading.timeline.to_axis(newer.clock.run, 0) == 3 * NS
    data = plan(view, ("look", "wait"), u=.5).content.as_json()
    assert data["time"]["earlier_run_pending"] == [str(pending.body.job)]
    # 3冊目から見る2冊目の試みも単調時計0ではなく軸の3秒。
    second = newer.start()
    newest = HandHistory("r3", 2, wall=107)
    newest.boot()
    reading = read(model, h.records + newer.records + newest.records)
    assert reading.started[second.body.job] == (3 * NS,)
    data = _data(model, h.records + newer.records + newest.records, 7)
    assert data["time"]["earlier_run_pending"] == sorted([str(pending.body.job), str(second.body.job)])


@pytest.mark.parametrize("changing", [True, False])
def test_j15_multiple_attempts_are_explicitly_deferred_to_S5(changing):
    model = _hand_model(duration=((1.5, 1.),), Q=_time_model().Q if changing else None)
    h = HandHistory()
    h.boot()
    first = h.start()
    h.start(seconds=1, job=first.body.job)
    for records in (h.records, h.records[::-1]):
        view = _view(model, records, 2)
        assert view.reading.started[first.body.job] == (0, NS)
        with pytest.raises(ModelFalsified) as exc:
            plan(view, ("look", "wait"), u=.5)
        assert str(exc.value) == "a pending job with several attempts needs S5"
        old = replace(model, durations={}, measures={})
        assert _data(old, records, 2)["chosen"] in ("look", "wait")


def test_start_without_clock_is_unread_and_pending_without_clock_is_not_queued():
    model = _hand_model(measure="start")
    h = HandHistory()
    attempted = h.start()
    pending = h.start()
    newer = HandHistory("r2", 1, wall=103)
    newer.boot()
    newer.observe(attempted, "o0", 0)
    records = h.records + newer.records
    reading = read(model, records)
    assert reading.unread[newer.records[-1].id] == "no_clock"
    assert reading.n["look"].tolist() == [0, 0, 0]
    with pytest.raises(ModelFalsified, match="no clock"):
        _data(model, records, 0)
    assert pending.body.job in reading.pending


def test_queued_job_starts_now_and_unseen_before_attempt_is_zero():
    model = _hand_model(measure="start", duration=((0., 1.),))
    h = HandHistory()
    h.boot()
    pending = h.start(seconds=1)
    queued = h.records[:-1]
    reading = read(model, queued)
    assert reading.started[pending.body.job] == ()
    data = _data(model, queued, 1, observed=0)
    begun = _data(model, h.records, 1, observed=0)
    assert data == begun
    risk, amb, obs = _hand_path_efe(model, (), ((NS, "look"),), "look", NS)
    _close(data["risk"][0], risk)
    _close(data["ambiguity"][0], amb)
    _close(data["q_o"][0], obs)


def test_forward_table_matches_independent_paths_with_multiple_pending_and_nonuniform_C():
    base = _time_model(world="W3", log_C=np.log(np.array([.2, .5, .3])))
    model = replace(base, durations={"look": ((1., 1.),), "wait": ((0., 1.),)},
                    measures={"look": "report", "wait": "report"})
    facts = ((NS, "look", 0), (3 * NS, "look", 1))
    history = tuple((ns, _log_A(model.a[action])[outcome]) for ns, action, outcome in facts)
    pending = ((0, "look"), (4 * NS, "look"))
    expected = _hand_path_efe(model, facts, pending, "look", 2 * NS)
    actual = _hand_efe(model.D, model.Q, history,
        tuple((model.a[action], ((ns, 1.),)) for ns, action in pending),
        (model.a["look"], ((2 * NS, 1.),)), model.log_C)
    _close(actual[:2], expected[:2])
    _close(actual[3], expected[2])
    assert actual[2] == 0.


def test_forward_table_keeps_tiny_log_mass_until_later_evidence_recovers_it():
    model = _hand_model()
    rare = np.log(np.array([.001, .999]))
    history = tuple((1, rare) for _ in range(200)) + tuple((1, rare[::-1]) for _ in range(200))
    joint = _hand_joint_log(model.D, model.Q, history, ((0, model.a["look"]),), 0)
    # 全証拠の積は両状態で同じ。途中で確率に戻すと片方が失われる。
    expected = model.a["look"] * model.D
    _close(np.exp(joint), expected)
    tiny = np.array([[1e-300, 1e-300], [1e300, 1e300]])
    joint = _hand_joint_log(model.D, model.Q, ((0, _log_A(tiny)[0]),), (), 0)
    _close(np.exp(joint[0]), [.5, .5])


@pytest.mark.parametrize("timed", [True, False])
def test_p3_belief_restore_and_decision_replay_preserve_content_and_cid(timed):
    model = _hand_model(measure="start", duration=((5., 1.),)) if timed else _time_model()
    r = _rig(model)
    boot(r.agent, clock=r.clock, ids=r.ids, ledger=r.ledger, membrane=r.membrane)
    world = ScriptedWorld({"look": ["o0"], "wait": ["none"]})
    step = run_step(r.agent, world, ("look",), u=.5, clock=r.clock, ids=r.ids,
                    ledger=r.ledger, membrane=r.membrane)
    belief_cid = r.ledger.entries_of(step.belief.id)[0].cid
    restored = Agent.restore(model=model_from_json(model_json(model)), lineage="hand_time",
                             ledger=r.ledger, belief=belief_cid)
    assert restored._belief.body.content == step.belief.body.content
    assert restored._belief.body.contract == (HAND_BELIEF if timed else BELIEF)
    decision_entry = r.ledger.entries_of(step.decided.id)[0]
    data = step.decided.body.content.as_json()
    draft = replay_decision(model=model, ledger=r.ledger, decision=decision_entry.cid)
    assert draft.content == step.decided.body.content
    rebuilt = replace(step.decided, body=replace(step.decided.body, content=draft.content))
    assert r.ledger.append(rebuilt, decision_entry.parents).cid == decision_entry.cid
    if not timed:
        assert step.decided.body.contract == S4D_DECISION
        assert set(data["time"]) == {"anchor", "anchor_ns", "now_ns", "dt_s", "pending_measures"}
    else:
        assert step.decided.body.contract == S4D_DECISION
        book = ContractBook()
        for declaration in DECLARATIONS + HAND_DECLARATIONS + S4D_DECLARATIONS:
            book.register(declaration)
        for record in (step.belief, step.decided):
            meaning = book.get(record.body.contract).meaning
            assert all(key in meaning for key in record.body.content.as_json())


def test_p2_static_learnable_belief_restores_with_hand_contract():
    model = _hand_model(Q=None, learnable=frozenset({"look"}), measure="start")
    r = _rig(model)
    origin = boot(r.agent, clock=r.clock, ids=r.ids, ledger=r.ledger, membrane=r.membrane)
    r.clock.advance(NS)
    step = run_step(r.agent, ScriptedWorld({"look": ["o0"]}), ("look",), u=.5,
                    clock=r.clock, ids=r.ids, ledger=r.ledger, membrane=r.membrane)
    assert step.belief.body.contract == HAND_BELIEF
    assert step.belief.body.content.as_json()["time"]["anchor"] == str(origin.id)
    cid = r.ledger.entries_of(step.belief.id)[0].cid
    restored = Agent.restore(model=model, lineage="hand_time", ledger=r.ledger, belief=cid)
    assert restored._belief.body.content == step.belief.body.content
    assert np.array_equal(restored.q, r.agent.q)
    assert np.array_equal(restored.counts("look"), r.agent.counts("look"))
