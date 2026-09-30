"""S4dの好み。C1・C2・C2b・C3・C8の因果の読みと本文欠損。"""

from dataclasses import FrozenInstanceError, replace
from itertools import permutations
import json
import math
from types import SimpleNamespace

import pytest

from sui.clock import FakeClock, Instant
from sui.contracts import ContractBook, ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.preference import (AmbiguousPreference, PreferenceUnreadable,
                            PreferenceView, current, from_ledger, resolve, cost, EvaluationInput, Feature)
from sui import preference as preference_module
from sui.records import (Observed, Preference, Payload, Producer, Record, Role,
                         WriterNotAllowed, Decided)
from sui.s4_contracts import BOOT
from sui.s4d_contracts import PREFERENCE, DECLARATIONS
from sui.snapshot import Absent, Found, Unknown, UnreadPreference
from sui.timeline import timeline, TimelineError


NS = 1_000_000_000
ITEM = {"kind": "item", "rule": {"name": "table", "version": "1"},
        "args": {"feature": {"name": "constant", "version": "1"}, "probs": [[None, 1.]]}}
STYLE = {"kind": "style", "H_ns": None, "gamma": 1.}


def _record(name, data=ITEM, *, at=None, contract=PREFERENCE, writer=Role.MODEL):
    return Record(id=Ref(K.PREFERENCE, name),
        at=at or Instant(run=Ref(K.RUN, name), run_index=0, seq=1, mono_ns=0, wall_ns=0),
        writer=writer, producer=Producer(component="test.preference", code_version="1"),
        body=Preference(basis=(), contract=contract,
                        content=data if isinstance(data, Payload) else Payload.json(data)))


def _ledger(*records):
    ledger = Ledger(salts=SequentialSalts())
    for record in records:
        ledger.append(record, ledger.heads())
    return ledger


def _current(ledger):
    return current(from_ledger(ledger, ledger.heads()))


def _observation(name="fact", *, at=None, received=None):
    return Record(id=Ref(K.OBSERVATION, name),
        at=at or Instant(run=Ref(K.RUN, name), run_index=0, seq=1, mono_ns=0, wall_ns=0),
        writer=Role.MEMBRANE, producer=Producer(component="test.preference", code_version="1"),
        body=Observed(route="membrane", contract=BOOT, content=Payload.json({}),
                      received_ns=received))


@pytest.mark.parametrize("role", list(Role))
def test_c1_only_model_writes_preferences(role):
    """MODELは書け、ほかは未決でなくWriterNotAllowed。"""
    if role is Role.MODEL:
        assert _record("p", writer=role).writer is Role.MODEL
    else:
        with pytest.raises(WriterNotAllowed):
            _record("p", writer=role)


def test_c1_preference_contract_is_declared():
    book = ContractBook()
    for declaration in DECLARATIONS:
        book.register(declaration)
    assert PREFERENCE == ContractRef("sui.s4d.preference", "1")
    assert next(d for d in DECLARATIONS if d.ref == PREFERENCE).state_owner == "sui.agent"


@pytest.mark.parametrize("horizon", [None, 0, 1, 10**30])
@pytest.mark.parametrize("gamma", [0, 1e-6, 1, 20.])
def test_c1_style_domain(horizon, gamma):
    record = _record("paper", {"kind": "style", "H_ns": horizon, "gamma": gamma})
    result = _current(_ledger(record))
    result.check()
    assert result.style == record and result.items == ()


@pytest.mark.parametrize("data", [
    {}, [], None, {"kind": "other"},
    {"kind": "item", "rule": {"name": "table"}, "args": {}},
    {"kind": "item", "rule": {"name": "table", "version": 1}, "args": {}},
    {**ITEM, "args": []}, {**ITEM, "extra": 0},
    {"kind": "withdraw", "items": "preference:p"},
    {"kind": "withdraw", "items": ["observation:p"]},
    {"kind": "withdraw", "items": [3]},
    {"kind": "withdraw", "items": ["preference:"]},
    *[{**STYLE, "H_ns": value} for value in [-1, True, 1.5, "1"]],
    *[{**STYLE, "gamma": value} for value in [-1, True, None, "1"]],
    {"kind": "style", "H_ns": 1},
    *[Payload("application/json", json.dumps({**STYLE, "gamma": value}).encode())
      for value in [float("nan"), float("inf"), -float("inf")]],
    Payload("application/json", b"{"), Payload("application/json", b"\xff"),
    Payload.text("not json"),
])
def test_c1_bad_envelope_is_a_mark_until_evaluation(data):
    result = _current(_ledger(_record("bad", data)))
    assert result.unread and result.unread[0][0] == Ref(K.PREFERENCE, "bad")
    with pytest.raises(PreferenceUnreadable):
        result.check()


@pytest.mark.parametrize("contract", [ContractRef("unknown", "1"), ContractRef("sui.s4d.preference", "2")])
def test_c1_unknown_contract_is_not_blank(contract):
    result = _current(_ledger(_record("p", contract=contract)))
    with pytest.raises(PreferenceUnreadable):
        result.check()


def test_c2_blank_and_causal_snapshot():
    empty = _current(_ledger())
    empty.check()
    assert empty.items == () and empty.style is None and not empty.ambiguous
    p, s = _record("p"), _record("s", STYLE)
    ledger = _ledger(p, s)
    assert all(e.is_event for e in ledger.between((), ledger.heads()))
    assert ledger.heads() == {ledger.entries_of(s.id)[0].cid}
    snapshot = ledger.snapshot(ledger.heads())
    assert snapshot.records == (p, s)
    assert snapshot.find(Preference) == Found(records=(p, s))
    assert snapshot.find(Preference, lambda r: r.id == p.id) == Found(records=(p,))
    assert snapshot.resolve(p.id) == Found(records=(p,))
    assert snapshot.resolve(Ref(K.PREFERENCE, "absent")) == Absent()
    assert _ledger().snapshot(()).find(Preference) == Absent()


@pytest.mark.parametrize("reverse", [False, True])
def test_c2_withdraw_crosses_observation_and_keeps_concurrent_item(reverse):
    p, q = _record("p"), _record("q")
    w = _record("w", {"kind": "withdraw", "items": [str(p.id)]})
    left, right = _ledger(p, _observation(), w), _ledger(q)
    merged = _ledger()
    for part in (right, left) if reverse else (left, right):
        merged.merge(part)
    result = _current(merged)
    result.check()
    assert result.items == (q,)
    assert {r.id for r in merged.snapshot(merged.heads()).records} == {p.id, q.id, w.id, Ref(K.OBSERVATION, "fact")}


@pytest.mark.parametrize("target", ["concurrent", "absent", "style", "self"])
def test_c2_withdraw_requires_actual_ancestor_item(target):
    p = _record("p", STYLE if target == "style" else ITEM)
    w = _record("w", {"kind": "withdraw", "items": [str(Ref(K.PREFERENCE,
                       "missing" if target == "absent" else "w" if target == "self" else "p"))]})
    ledger = _ledger(p, w) if target == "style" else _ledger(w)
    if target == "concurrent":
        ledger.merge(_ledger(p))
    result = _current(ledger)
    with pytest.raises(PreferenceUnreadable):
        result.check()


def test_c2_withdraw_does_not_stitch_paths_between_record_copies():
    p, bridge = _record("p"), _record("bridge", STYLE)
    w = _record("w", {"kind": "withdraw", "items": [str(p.id)]})
    ledger = _ledger(p, bridge)
    ledger.merge(_ledger(bridge, w))
    view = from_ledger(ledger, ledger.heads())
    assert (p.id, bridge.id) in view.before and (bridge.id, w.id) in view.before
    assert (p.id, w.id) not in view.before
    with pytest.raises(PreferenceUnreadable):
        current(view).check()


def test_c2_same_record_twice_is_one_item_but_same_content_twice_is_two():
    p, q = _record("p"), _record("q")
    ledger = _ledger(p)
    ledger.merge(_ledger(_observation(), p))
    ledger.merge(_ledger(q))
    assert len(ledger.entries_of(p.id)) == 2
    assert _current(ledger).items == (p, q)


@pytest.mark.parametrize("size", [2, 3])
def test_c2_style_cycles_keep_sink_component_in_every_merge_order(size):
    """相互辺だけの検査・全紙を消す・最後の取り込みを優先する誤りを落とす。"""
    papers = tuple(_record(f"paper{i}", {**STYLE, "gamma": i}) for i in range(size))
    parts = tuple(_ledger(papers[i], papers[(i + 1) % size]) for i in range(size))
    for order in permutations(parts):
        ledger = _ledger()
        for part in order:
            ledger.merge(part)
        result = _current(ledger)
        assert result.ambiguous == tuple(r.id for r in papers)
        assert result.style is None
        with pytest.raises(AmbiguousPreference):
            result.check()
        newer = _record("newer", {**STYLE, "H_ns": 1})
        ledger.append(newer, ledger.heads())
        assert _current(ledger).style == newer
        _current(ledger).check()


def test_c2_style_chain_and_concurrent_papers():
    x, y, z = (_record(name, STYLE) for name in ("x", "y", "z"))
    ledger = _ledger(x, y, z)
    assert _current(ledger).style == z
    other = _record("other", STYLE)
    ledger.merge(_ledger(other))
    assert _current(ledger).ambiguous == (other.id, z.id)


def test_c3_target_and_frozen_view_do_not_follow_heads():
    p, q = _record("p"), _record("q")
    ledger = _ledger(p)
    target = ledger.heads()
    view = from_ledger(ledger, target)
    ledger.append(q, ledger.heads())
    assert from_ledger(ledger, target) == view
    assert current(view).items == (p,)
    assert _current(ledger).items == (p, q)
    assert view.frontier == target
    with pytest.raises(FrozenInstanceError):
        view.before = frozenset()
    with pytest.raises(FrozenInstanceError):
        view.points[0].unread = "changed"
    points, before, frontier = list(view.points), set(view.before), set(view.frontier)
    copy = PreferenceView(points=points, before=before, frontier=frontier)
    points.clear()
    before.add((q.id, p.id))
    frontier.clear()
    assert copy == view


def test_c2_missing_preference_is_unknown_without_fabricated_record():
    p, q = _record("p"), _record("q")
    ledger = _ledger(p, q)
    entry = ledger.entries_of(p.id)[0]
    ledger.contents.discard(entry.seal)
    snapshot = ledger.snapshot(ledger.heads())
    assert snapshot.records == (q,)
    assert snapshot.unread_preferences == (UnreadPreference(id=p.id, at=p.at, reason="missing content"),)
    assert isinstance(snapshot.find(Preference), Unknown)
    assert isinstance(snapshot.find(Preference, lambda r: r.id == q.id), Unknown)
    assert isinstance(snapshot.resolve(p.id), Unknown) and snapshot.resolve(p.id).reason
    assert snapshot.resolve(q.id) == Found(records=(q,))
    assert snapshot.resolve(Ref(K.PREFERENCE, "absent")) == Absent()
    view = from_ledger(ledger, ledger.heads())
    point = next(point for point in view.points if point.id == p.id)
    assert point.record is None and point.at == p.at and point.unread
    with pytest.raises(PreferenceUnreadable):
        current(view).check()
    decision = Record(id=Ref(K.DECISION, "d"), at=FakeClock(run=Ref(K.RUN, "decision")).now(),
        writer=Role.MODEL, producer=p.producer,
        body=Decided(inputs=(p.id,), content=Payload.json({}), contract=ContractRef("test", "1")))
    ledger.append(decision, ledger.heads())
    assert p.id not in ledger.snapshot(ledger.heads()).unresolved()


def test_c2_missing_other_body_keeps_old_error():
    ledger = _ledger(_observation())
    entry = ledger.entry(next(iter(ledger.heads())))
    ledger.contents.discard(entry.seal)
    with pytest.raises(KeyError):
        ledger.snapshot(ledger.heads())


def test_c2_readable_copy_resolves_id_but_keeps_unread_point():
    p = _record("p")
    ledger = _ledger(p)
    discarded = ledger.entries_of(p.id)[0]
    ledger.merge(_ledger(_observation(), p))
    ledger.contents.discard(discarded.seal)
    snapshot = ledger.snapshot(ledger.heads())
    assert snapshot.resolve(p.id) == Found(records=(p,))
    assert snapshot.find(Preference) == Found(records=(p,))
    assert snapshot.unread_preferences[0].id == p.id
    with pytest.raises(PreferenceUnreadable):
        _current(ledger).check()


def _clock_scene():
    # 前のrunの末尾はmono=2、wall=3。次のbootはwall=4。
    # 紙が無ければ次の原点4、あれば3。観測の終端はどちらも1。
    first = Ref(K.RUN, "first")
    def at(seq, mono, wall):
        return Instant(run=first, run_index=0, seq=seq, mono_ns=mono * NS, wall_ns=wall * NS)
    boot = _observation("boot", at=at(1, 0, 0), received=0)
    receipt = _observation("receipt", at=at(2, 1, 1), received=NS)
    paper = _record("paper", STYLE, at=at(3, 2, 3))
    next_boot = _observation("next_boot", at=Instant(run=Ref(K.RUN, "second"),
        run_index=1, seq=1, mono_ns=0, wall_ns=4 * NS), received=0)
    return boot, receipt, paper, next_boot


@pytest.mark.parametrize("missing", [False, True])
def test_c2b_preference_moves_axis_not_receipt_boundary(missing):
    boot, receipt, paper, next_boot = _clock_scene()
    old = timeline((boot, receipt, next_boot))
    ledger = _ledger(boot, receipt, paper, next_boot)
    if missing:
        ledger.contents.discard(ledger.entries_of(paper.id)[0].seal)
    snapshot = ledger.snapshot(ledger.heads())
    axis = timeline(snapshot.records, unread_preferences=snapshot.unread_preferences)
    assert old.to_axis(next_boot.at.run, 0) == 4 * NS
    assert axis.to_axis(next_boot.at.run, 0) == 3 * NS
    assert axis.run_end_ns[boot.at.run] == old.run_end_ns[boot.at.run] == NS
    assert set(axis.received_ns) == {boot.id, receipt.id, next_boot.id}
    assert axis.received_ns[next_boot.id] == axis.run_end_ns[next_boot.at.run] == 3 * NS


def test_c2b_metadata_keeps_run_conflicts_and_is_preference_only():
    boot = _observation("boot", received=0)
    p = _record("p")
    point = UnreadPreference(id=p.id, at=p.at, reason="missing content")
    with pytest.raises(TimelineError):
        timeline((boot,), unread_preferences=(point,))
    with pytest.raises(TypeError):
        timeline((), unread_preferences=(p,))
    with pytest.raises(ValueError):
        UnreadPreference(id=boot.id, at=boot.at, reason="missing content")


def test_c8_agent_adopt_restore_and_merge_freeze_same_target():
    from sui.agent import Agent
    from worlds import _model
    model, clock, ids = _model(), FakeClock(run=Ref(K.RUN, "agent")), SequentialIds()
    p, q = _record("p"), _record("q")
    ledger = _ledger(p)
    target = ledger.heads()
    ledger.append(q, ledger.heads())
    agent = Agent(model=model, lineage="line")
    belief = agent.adopt(ledger, clock=clock, ids=ids, through=target)
    view = agent.view()
    assert view.reading.preferences == (p,)
    assert current(view.preferences).items == (p,)
    assert view.frontier == view.preferences.frontier == target
    agent.adopt(ledger, clock=clock, ids=ids)
    assert current(agent.view().preferences).items == (p, q)
    assert current(view.preferences).items == (p,)
    merged = _ledger()
    merged.merge(ledger)
    restored = Agent.restore(model=model, lineage="line", ledger=merged,
                              belief=merged.entries_of(belief.id)[0].cid)
    assert restored.view().preferences == view.preferences
    assert restored.belief_record(clock=clock, ids=ids, ledger=merged).body.content == belief.body.content


@pytest.mark.parametrize("changing,learnable", [(True, False), (False, False), (False, True)])
@pytest.mark.parametrize("missing", [False, True])
def test_c2b_agent_read_preserves_counts_and_missing_time(missing, changing, learnable):
    import numpy as np
    from sui.agent import read, _derive_reading
    from worlds import _hand_model, HandHistory
    model = _hand_model() if changing else _hand_model(
        Q=None, learnable=frozenset({"look"}) if learnable else frozenset())
    h = HandHistory()
    h.boot()
    attempt = h.start()
    h.observe(attempt, "o0", 1)
    old = read(model, h.records)
    at = replace(h.records[-1].at, seq=h.records[-1].at.seq + 1, mono_ns=2 * NS)
    paper = _record("paper", STYLE, at=at)
    ledger = _ledger(*h.records, paper)
    if missing:
        ledger.contents.discard(ledger.entries_of(paper.id)[0].seal)
    snapshot = ledger.snapshot(ledger.heads())
    new = read(model, snapshot.records, unread_preferences=snapshot.unread_preferences)
    assert new.timeline == old.timeline
    assert new.pending == old.pending and new.unread == old.unread
    assert new.sequence == old.sequence and new.arrivals == old.arrivals
    for action in model.actions:
        np.testing.assert_array_equal(new.n[action], old.n[action])
    q_old, a_old = _derive_reading(model, old)
    q_new, a_new = _derive_reading(model, new)
    np.testing.assert_array_equal(q_new, q_old)
    for action in model.actions:
        np.testing.assert_array_equal(a_new[action], a_old[action])
    assert new._event_ns[paper.at.run] == 2 * NS
    assert new.timeline.run_end_ns[paper.at.run] == NS
    assert new.preferences == (() if missing else (paper,))


def test_c2_missing_preference_adopt_and_status_do_not_raise():
    from sui.agent import Agent
    from sui.runtime import Window, Pledges
    from worlds import _model, GatedHand, ScriptDrive
    model = _model()
    clock, ids = FakeClock(run=Ref(K.RUN, "agent")), SequentialIds()
    p = _record("p")
    ledger = _ledger(p)
    ledger.contents.discard(ledger.entries_of(p.id)[0].seal)
    agent = Agent(model=model, lineage="line")
    belief = agent.adopt(ledger, clock=clock, ids=ids)
    assert belief is not None
    view = agent.view()
    assert view.reading.unread_preferences[0].id == p.id
    assert current(view.preferences).unread[0][0] == p.id
    restored = Agent.restore(model=model, lineage="line", ledger=ledger,
                              belief=ledger.entries_of(belief.id)[0].cid)
    assert restored.view().preferences == view.preferences
    window = Window(agent=agent, ledger=ledger, clock=clock, ids=ids,
                    membrane=p.producer, route="test", drive=ScriptDrive(),
                    hand=GatedHand({action: set() for action in model.actions}, {}),
                    capacity={"think": 1}, pledges=Pledges())
    window.status()


def _feature_args(name="candidate_outcome", **table):
    return {"feature": {"name": name, "version": "1"},
            **(table or {"probs": [["o0", .8], ["o1", .2]]})}


def _history(n=0):
    return SimpleNamespace(model=SimpleNamespace(outcomes=("o0", "o1")),
                           reading=SimpleNamespace(n={"look": [n, 2], "other": [7, 8]}))


def _resolve_args(args=None, *, rule="table", version="1", h=None, style=None):
    record = _record("item", {"kind": "item", "rule": {"name": rule, "version": version},
                              "args": _feature_args() if args is None else args})
    ledger = _ledger(record)
    if style is not None:
        ledger.append(_record("style", style), ledger.heads())
    return resolve(_current(ledger), _history() if h is None else h)


def test_c4_resolved_blank_and_style_have_no_model_preference_input():
    blank = resolve(_current(_ledger()), object())
    assert blank.items == () and blank.style is None and blank.H_ns is None and blank.gamma == 1.
    assert cost(blank, EvaluationInput(evaluation="lookahead")) == 0.
    paper = _record("paper", {"kind": "style", "H_ns": 0, "gamma": 0})
    styled = resolve(_current(_ledger(paper)), object())
    assert styled.style == paper.id and styled.H_ns == 0 and styled.gamma == 0.
    assert cost(styled, EvaluationInput(evaluation="lookahead")) == 0.


@pytest.mark.parametrize("table", [
    {"probs": [["o0", .8], ["o1", .2]]},
    {"log_probs": [["o0", -0.2231435513142097], ["o1", -1.6094379124341003]]},
])
def test_c1_table_keeps_normalized_log_probabilities_and_missing_is_forbidden(table):
    resolved = _resolve_args(_feature_args(**table))
    item = resolved.items[0]
    assert item.id == Ref(K.PREFERENCE, "item") and item.rule == ContractRef("table", "1")
    assert item.feature.ref == ContractRef("candidate_outcome", "1")
    assert item.log_probability("o0") == pytest.approx(-0.2231435513142097, abs=1e-15)
    assert item.log_probability("o1") == pytest.approx(-1.6094379124341003, abs=1e-15)
    assert item.log_probability("missing") == -math.inf
    assert cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome="missing")) == math.inf
    assert cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(0.2231435513142097, abs=1e-15)


def test_c5_tiny_log_probability_remains_finite_without_renormalization():
    resolved = _resolve_args(_feature_args(log_probs=[["o0", 0.], ["o1", -1000.]]))
    assert resolved.items[0].log_probability("o1") == -1000.
    assert cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome="o1")) == 1000.
    assert cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == 0.
    assert cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome="not_in_table")) == math.inf
    near = _resolve_args(_feature_args(log_probs=[["o0", 5e-13], ["o1", -1000.]]))
    assert near.items[0].log_probability("o0") == 5e-13


@pytest.mark.parametrize("table", [
    {}, {"probs": [], "log_probs": []}, {"probabilities": [["o0", 1.]]},
    {"probs": []}, {"log_probs": []}, {"probs": {"o0": 1.}},
    {"probs": [["o0"]]}, {"probs": [["o0", 1., 2.]]}, {"probs": ["o0"]},
    {"probs": [["o0", 0.], ["o1", 1.]]},
    *[{"probs": [["o0", value]]} for value in [-1., True, None, "1", .5, 2.]],
    *[{"log_probs": [["o0", value]]} for value in [True, None, "0", -.5, 2e-12]],
    {"probs": [["o0", .3], ["o1", .3]]},
    {"log_probs": [["o0", 0.], ["o1", 0.]]},
    {"probs": [["o0", .5], ["o0", .5]]},
    {"log_probs": [[{"a": 1, "b": 2}, -math.log(2)], [{"b": 2, "a": 1}, -math.log(2)]]},
    {"probs": [["o0", 1.]], "extra": 0},
])
def test_c1_invalid_tables_are_unreadable(table):
    with pytest.raises(PreferenceUnreadable):
        _resolve_args({"feature": {"name": "candidate_outcome", "version": "1"}, **table})


@pytest.mark.parametrize("key", ["probs", "log_probs"])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_c1_nonfinite_table_number_is_unreadable(key, number):
    payload = Payload("application/json", json.dumps({"kind": "item",
        "rule": {"name": "table", "version": "1"},
        "args": _feature_args(**{key: [["o0", number]]})}).encode())
    with pytest.raises(PreferenceUnreadable):
        resolve(_current(_ledger(_record("item", payload))), _history())


def test_c1_table_uses_canonical_json_and_detaches_caller_data():
    args = _feature_args("constant", probs=[[{"b": [1, "é"], "a": True}, .75], [None, .25]])
    _, lookup = preference_module.BUILTINS[("rule", "table", "1")](None, args, preference_module.BUILTINS)
    args["probs"][0][0]["b"].append("changed")
    args["probs"][0][1] = .1
    assert lookup({"a": True, "b": [1, "é"]}) == pytest.approx(-0.2876820724517809, abs=1e-15)
    assert lookup(None) == pytest.approx(-1.3862943611198906, abs=1e-15)
    assert lookup({"a": True, "b": [1, "é", "changed"]}) == -math.inf
    with pytest.raises(TypeError):
        lookup._values["null"] = 0.


@pytest.mark.parametrize("name,version", [("unknown", "1"), ("table", "2")])
def test_c1_unknown_rule_or_version_is_unreadable(name, version):
    with pytest.raises(PreferenceUnreadable):
        _resolve_args(rule=name, version=version)


@pytest.mark.parametrize("descriptor", [
    "constant", {}, {"name": "constant"}, {"name": "unknown", "version": "1"},
    {"name": "constant", "version": "2"}, {"name": "constant", "version": 1},
    {"name": "constant", "version": "1", "extra": 0},
])
def test_c1_unknown_or_malformed_feature_is_unreadable(descriptor):
    with pytest.raises(PreferenceUnreadable):
        _resolve_args({**_feature_args(), "feature": descriptor})


def _experience_args():
    return {"feature": {"name": "candidate_outcome", "version": "1"},
            "experience": {"name": "observed_count", "version": "1", "action": "look", "outcome": "o0"},
            "cap": 3,
            "tables": {"0": {"probs": [["o0", .5], ["o1", .5]]},
                       "1": {"probs": [["o0", 1 / 3], ["o1", 2 / 3]]},
                       "2": {"probs": [["o0", .25], ["o1", .75]]},
                       "3": {"log_probs": [["o0", -1.6094379124341003], ["o1", -0.2231435513142097]]}}}


@pytest.mark.parametrize("n,expected", [(0, .6931471805599453), (1, 1.0986122886681098),
    (2, 1.3862943611198906), (3, 1.6094379124341003), (100, 1.6094379124341003)])
def test_c6_by_experience_uses_read_count_and_caps_the_table(n, expected):
    h = _history(n)
    result = _resolve_args(_experience_args(), rule="by_experience", h=h)
    assert cost(result, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(expected, abs=1e-15)
    h.reading.n["look"][0] = 1000
    assert cost(result, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(expected, abs=1e-15)
    # ほかの行動・結果の回数は足さない。窓の中の仮の観測でも表は変えない。
    O = ((0, ("new", 0), "look", "o0"),) * 10
    assert cost(result, EvaluationInput(evaluation="one_step", O=O, A=(), candidate_outcome="o0")) == pytest.approx(expected, abs=1e-15)


def test_c6_same_rule_version_selects_a_new_table_at_next_root():
    h, args = _history(0), _experience_args()
    first = _resolve_args(args, rule="by_experience", h=h)
    h.reading.n["look"][0] = 3
    second = _resolve_args(args, rule="by_experience", h=h)
    assert first.items[0].rule == second.items[0].rule == ContractRef("by_experience", "1")
    assert cost(first, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(.6931471805599453, abs=1e-15)
    assert cost(second, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(1.6094379124341003, abs=1e-15)


@pytest.mark.parametrize("field,value", [("action", "not_seen"), ("outcome", "not_seen")])
def test_c6_no_read_observation_for_named_pair_counts_zero(field, value):
    args = _experience_args()
    args["experience"][field] = value
    result = _resolve_args(args, rule="by_experience", h=_history(100))
    assert cost(result, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(.6931471805599453, abs=1e-15)


@pytest.mark.parametrize("change", [
    {"cap": 0}, {"cap": -1}, {"cap": True}, {"cap": 1.5}, {"cap": "3"},
    {"tables": {}}, {"tables": []},
    {"tables": {str(n): {"probs": [["o0", 1.]]} for n in (0, 1, 3)}},
    {"tables": {str(n): {"probs": [["o0", 1.]]} for n in range(5)}},
    {"tables": {"00": {"probs": [["o0", 1.]]},
                **{str(n): {"probs": [["o0", 1.]]} for n in (1, 2, 3)}}},
    {"experience": {"name": "unknown", "version": "1", "action": "look", "outcome": "o0"}},
    {"experience": {"name": "observed_count", "version": "2", "action": "look", "outcome": "o0"}},
    {"experience": {"name": "observed_count", "version": "1", "action": "look"}},
    {"experience": {"name": "observed_count", "version": "1", "action": "", "outcome": "o0"}},
    {"experience": {"name": "observed_count", "version": "1", "action": "look", "outcome": 1}},
    {"extra": 0},
])
def test_c1_invalid_experience_rule_is_unreadable(change):
    with pytest.raises(PreferenceUnreadable):
        _resolve_args({**_experience_args(), **change}, rule="by_experience")


def test_c1_by_experience_checks_even_unselected_tables():
    args = _experience_args()
    args["tables"]["3"] = {"probs": [["o0", .2]]}
    with pytest.raises(PreferenceUnreadable):
        _resolve_args(args, rule="by_experience", h=_history(0))


def _path():
    # 2件は同時、1件はO0。pendingの0番はこの枝では届かず、1番だけ届く。
    O = ((2, ("new", 1), "look", "o1"),
         (-3, ("pending", "look", -5, 1), "look", "o0"),
         (2, ("new", 0), "ask", "o0"),
         (4, ("new", 2), "ask", "o0"))
    A = ((2, ("new", 2), "ask"), (0, ("new", 0), "ask"), (1, ("new", 1), "look"))
    return O, A


@pytest.mark.parametrize("name,expected", [
    ("constant", None), ("candidate_outcome", "o1"),
    ("outcome_multiset", [["ask", "o0"], ["ask", "o0"], ["look", "o0"], ["look", "o1"]]),
    ("outcome_groups", [[["look", "o0"]], [["ask", "o0"], ["look", "o1"]], [["ask", "o0"]]]),
    ("started_actions", ["ask", "look", "ask"]), ("counts", [4, 3]),
    ("timed_path", {"O": [[-3, ["pending", "look", -5, 1], "look", "o0"],
                          [2, ["new", 0], "ask", "o0"], [2, ["new", 1], "look", "o1"],
                          [4, ["new", 2], "ask", "o0"]],
                    "A": [[0, ["new", 0], "ask"], [1, ["new", 1], "look"], [2, ["new", 2], "ask"]]}),
])
def test_c1_feature_json_values_include_o0_keep_ties_and_fixed_labels(name, expected):
    resolved = _resolve_args(_feature_args(name, probs=[[expected, 1.]]))
    feature = resolved.items[0].feature
    O, A = _path()
    for observations in permutations(O):
        assert feature(EvaluationInput(evaluation="one_step", O=observations, A=A, candidate_outcome="o1")) == expected
        assert Payload.json(feature(EvaluationInput(evaluation="one_step", O=observations,
            A=A, candidate_outcome="o1"))).data == Payload.json(expected).data
        assert cost(resolved, EvaluationInput(evaluation="one_step", O=observations, A=A, candidate_outcome="o1")) == 0.
    assert feature(EvaluationInput(evaluation="one_step", O=O, A=A[::-1], candidate_outcome="o1")) == expected
    with pytest.raises(FrozenInstanceError):
        feature.ref = ContractRef("constant", "1")


@pytest.mark.parametrize("name,expected", [
    ("constant", None), ("outcome_multiset", []), ("outcome_groups", []),
    ("started_actions", []), ("counts", [0, 0]), ("timed_path", {"O": [], "A": []}),
])
def test_c1_empty_path_feature_values(name, expected):
    feature = _resolve_args(_feature_args(name, probs=[[expected, 1.]])).items[0].feature
    assert feature(EvaluationInput(evaluation="lookahead")) == expected


def test_c1_candidate_outcome_requires_the_candidates_own_result():
    feature = _resolve_args().items[0].feature
    O, A = _path()
    with pytest.raises(ValueError):
        feature(EvaluationInput(evaluation="lookahead", O=O, A=A))
    assert feature(EvaluationInput(evaluation="one_step", O=O, A=A, candidate_outcome="o0")) == "o0"


@pytest.mark.parametrize("name,expected", [
    ("started_actions", ["wait", "ask"]), ("counts", [0, 2]),
    ("timed_path", {"O": [], "A": [[0, ["new", 0], "wait"], [3, ["new", 1], "ask"]]}),
])
def test_c1_actions_remain_features_when_no_result_arrives(name, expected):
    result = _resolve_args(_feature_args(name, probs=[[expected, 1.]]))
    A = ((3, ("new", 1), "ask"), (0, ("new", 0), "wait"))
    assert result.items[0].feature(EvaluationInput(evaluation="lookahead", O=(), A=A)) == expected
    assert cost(result, EvaluationInput(evaluation="lookahead", O=(), A=A)) == 0.


def test_c1_timed_path_uses_json_label_order_but_start_number_order():
    result = _resolve_args(_feature_args("timed_path", probs=[[None, 1.]]))
    O = ((0, ("new", 2), "look", "o0"), (0, ("new", 10), "look", "o1"))
    A = ((0, ("new", 10), "look"), (0, ("new", 2), "look"))
    projected = result.items[0].feature(EvaluationInput(evaluation="lookahead", O=O, A=A))
    assert [event[1][1] for event in projected["O"]] == [10, 2]
    assert [event[1][1] for event in projected["A"]] == [2, 10]


def test_c6_trial_rule_is_called_once_and_its_feature_is_frozen(monkeypatch):
    calls = []
    ref = ContractRef("test_rule", "1")
    def trial_rule(h, args, definitions):
        calls.append(h.reading.n["look"][0])
        return definitions[("rule", "table", "1")](h, args, definitions)
    monkeypatch.setattr(preference_module, "BUILTINS", {**preference_module.BUILTINS,
        ("rule", ref.name, ref.version): trial_rule})
    result = _resolve_args(rule="test_rule", h=_history(2))
    monkeypatch.setattr(preference_module, "BUILTINS", {})
    for _ in range(3):
        assert cost(result, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == pytest.approx(.2231435513142097, abs=1e-15)
    assert calls == [2]


def test_k6_evaluation_input_and_feature_declarations_are_immutable():
    """箱は4欄だけ。呼び手の列や名札を後から変えても固定した入力は変わらない。"""
    from dataclasses import fields
    O = [[-3, ["pending", "look", -5, 1], "look", "o0"]]
    A = [[0, ["new", 0], "look"]]
    value = EvaluationInput(evaluation="lookahead", O=O, A=A)
    assert {f.name for f in fields(value)} == {"evaluation", "O", "A", "candidate_outcome"}
    O[0][1][-1] = 8
    A[0][1][-1] = 9
    O.append([1, ["new", 0], "look", "o1"])
    assert value.O == ((-3, ("pending", "look", -5, 1), "look", "o0"),)
    assert value.A == ((0, ("new", 0), "look"),)
    with pytest.raises(FrozenInstanceError):
        value.evaluation = "one_step"
    with pytest.raises(TypeError):
        value.O[0][1][-1] = 0
    evaluations = {"lookahead"}
    feature = Feature(ref=ContractRef("test.input", "1"), evaluations=evaluations,
                      _project=lambda received: received)
    evaluations.add("one_step")
    assert feature.evaluations == frozenset({"lookahead"})
    assert feature(value) is value
    with pytest.raises(FrozenInstanceError):
        feature.evaluations = frozenset()


@pytest.mark.parametrize("rule", ["table", "by_experience"])
def test_k6_nested_feature_and_experience_use_the_supplied_definitions(rule):
    """外の決まりだけでなく、内の特徴と数え方も渡された同じ棚から引く。"""
    from types import MappingProxyType
    ref = ContractRef("test.shared", "1")
    seen = []
    feature = Feature(ref=ref, evaluations=frozenset({"one_step"}),
        _project=lambda value: seen.append(value) or "o1")
    def counting(h, descriptor):
        assert h.reading.n["look"][0] == 0
        assert descriptor["action"] == "look"
        return 3
    definitions = MappingProxyType({**preference_module.BUILTINS,
        ("rule", ref.name, "1"): preference_module.BUILTINS[("rule", rule, "1")],
        ("feature", ref.name, "1"): feature,
        ("experience", ref.name, "1"): counting})
    args = _feature_args() if rule == "table" else _experience_args()
    args["feature"] = {"name": ref.name, "version": "1"}
    if rule == "by_experience":
        args["experience"]["name"] = ref.name
    item = _record("item", {"kind": "item", "rule": {"name": ref.name, "version": "1"}, "args": args})
    resolved = resolve(_current(_ledger(item)), _history(), definitions=definitions)
    value = EvaluationInput(evaluation="one_step", candidate_outcome="o0")
    assert cost(resolved, value) == pytest.approx(
        1.6094379124341003 if rule == "table" else .2231435513142097, abs=1e-15)
    assert seen == [value] and seen[0] is value
    with pytest.raises(PreferenceUnreadable):
        resolve(_current(_ledger(item)), _history())


@pytest.mark.parametrize("kind,name", [
    ("rule", "by_experience"), ("feature", "candidate_outcome"), ("experience", "observed_count"),
])
def test_k6_missing_old_version_never_uses_the_latest_definition(kind, name):
    """新版を足しても旧版の参照はそのまま。旧版を失えば読めないと答える。"""
    item = _record("item", {"kind": "item", "rule": {"name": "by_experience", "version": "1"},
                            "args": _experience_args()})
    current_value, h = _current(_ledger(item)), _history()
    definitions = dict(preference_module.BUILTINS)
    def newer(*args):
        raise AssertionError("the newer definition must not be used")
    definitions[(kind, name, "2")] = newer
    value = EvaluationInput(evaluation="one_step", candidate_outcome="o0")
    assert cost(resolve(current_value, h, definitions=definitions), value) == pytest.approx(
        .6931471805599453, abs=1e-15)
    del definitions[(kind, name, "1")]
    with pytest.raises(PreferenceUnreadable):
        resolve(current_value, h, definitions=definitions)
    with pytest.raises(PreferenceUnreadable):
        resolve(current_value, h, definitions={})
    with pytest.raises(TypeError):
        preference_module.BUILTINS[(kind, name, "1")] = newer


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
@pytest.mark.parametrize("allowed", [False, True])
def test_k6_custom_feature_declaration_controls_applicability(monkeypatch, evaluation, allowed):
    """未登録だった名前でも宣言で可否が決まる。agentの名前の列挙には依らない。"""
    from sui.agent import plan
    from sui.lookahead import OutsideEvaluationType
    from worlds import HandHistory
    name = "test.extension"
    feature = Feature(ref=ContractRef(name, "1"),
        evaluations=frozenset({evaluation} if allowed else ()), _project=lambda value: None)
    monkeypatch.setattr(preference_module, "BUILTINS", {**preference_module.BUILTINS,
        ("feature", name, "1"): feature})
    h = HandHistory()
    h.boot()
    rig = _decision_setup(_binary_model(timed=True), h=h)
    _adopt_preferences(rig, _record("item", {**ITEM, "args": _feature_args(name, probs=[[None, 1.]])},
                                   at=h.clock.now()),
        _record("style", {**STYLE, "H_ns": None if evaluation == "one_step" else NS}, at=h.clock.now()))
    view = rig.agent.view(now_ns=0, observed_ns=0)
    if allowed:
        assert plan(view, rig.model.actions, u=.5).content.as_json()["evaluation"] == evaluation
    else:
        with pytest.raises(OutsideEvaluationType):
            plan(view, rig.model.actions, u=.5)


@pytest.mark.parametrize("evaluation", ["one_step", "lookahead"])
def test_k6_equivalent_definition_collection_keeps_decision_bytes(monkeypatch, evaluation):
    """同じ版の定義を別の棚に束ねても記録の欄・値・版は完全一致する。"""
    from sui.agent import plan
    from worlds import HandHistory
    from sui.s4d_contracts import DECISION
    h = HandHistory()
    h.boot()
    rig = _decision_setup(_binary_model(timed=True), h=h)
    _adopt_preferences(rig, _record("item", {**ITEM, "args": _feature_args("constant", probs=[[None, 1.]])},
                                   at=h.clock.now()),
        _record("style", {**STYLE, "H_ns": None if evaluation == "one_step" else NS}, at=h.clock.now()))
    view = rig.agent.view(now_ns=0, observed_ns=0)
    before = plan(view, rig.model.actions, u=.5)
    copied = {key: value for key, value in reversed(tuple(preference_module.BUILTINS.items()))}
    monkeypatch.setattr(preference_module, "BUILTINS", copied)
    after = plan(view, rig.model.actions, u=.5)
    assert after.content.data == before.content.data
    assert after.contract == before.contract == DECISION
    assert after.preference_inputs == before.preference_inputs


def test_c6_identical_items_strengthen_preference_and_bans_survive():
    first = _record("first", {**ITEM, "args": _feature_args()})
    second = _record("second", {**ITEM, "args": _feature_args()})
    result = resolve(_current(_ledger(first, second)), _history())
    costs = [cost(result, EvaluationInput(evaluation="one_step", candidate_outcome=name)) for name in ("o0", "o1")]
    assert costs == pytest.approx([.4462871026284194, 3.2188758248682006], abs=1e-15)
    weights = [math.exp(-value) for value in costs]
    assert weights[0] / sum(weights) == pytest.approx(16 / 17, abs=1e-15)
    ban = _record("ban", {**ITEM, "args": _feature_args(probs=[["o1", 1.]])})
    banned = resolve(_current(_ledger(first, ban)), _history())
    assert cost(banned, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == math.inf
    assert cost(banned, EvaluationInput(evaluation="one_step", candidate_outcome="o1")) == pytest.approx(1.6094379124341003, abs=1e-15)


def test_c2_c6_item_addition_follows_id_order_in_every_merge_order():
    records = [_record(name, {**ITEM, "args": _feature_args(log_probs=[
        ["o0", -amount], ["o1", 0. if amount > 100 else -0.45867514538708193]])})
        for name, amount in (("a", 1e16), ("b", 1.), ("c", 1.))]
    for order in permutations(records):
        ledger = _ledger()
        for record in order:
            ledger.merge(_ledger(record))
        result = resolve(_current(ledger), _history())
        assert tuple(item.id for item in result.items) == tuple(record.id for record in records)
        # 仕様の例: ((1e16 + 1) + 1) = 1e16。逆なら10000000000000002。
        assert cost(result, EvaluationInput(evaluation="one_step", candidate_outcome="o0")) == 1e16


def test_c6_features_do_not_merge_internal_paths_or_extend_tables():
    groups = _resolve_args(_feature_args("outcome_groups", probs=[[[[["look", "o0"]]], 1.]]))
    early = ((0, ("new", 0), "look", "o0"),)
    late = ((5, ("new", 0), "look", "o0"),)
    assert cost(groups, EvaluationInput(evaluation="lookahead", O=early)) == cost(groups, EvaluationInput(evaluation="lookahead", O=late)) == 0.
    assert early != late
    assert cost(groups, EvaluationInput(evaluation="lookahead", O=early + late)) == math.inf
    timed = _resolve_args(_feature_args("timed_path", probs=[[{
        "O": [[0, ["new", 0], "look", "o0"]], "A": []}, 1.]]))
    assert cost(timed, EvaluationInput(evaluation="lookahead", O=early)) == 0. and cost(timed, EvaluationInput(evaluation="lookahead", O=late)) == math.inf


def test_c6_withdrawn_item_is_not_resolved_and_resolve_checks_marks():
    item = _record("item", {**ITEM, "args": _feature_args("counts", probs=[[[0, 0], 1.]])})
    withdraw = _record("withdraw", {"kind": "withdraw", "items": [str(item.id)]})
    assert resolve(_current(_ledger(item, withdraw)), _history()).items == ()
    with pytest.raises(PreferenceUnreadable):
        resolve(_current(_ledger(_record("bad", Payload.text("unreadable")))), _history())
    ledger = _ledger(_record("left", STYLE))
    ledger.merge(_ledger(_record("right", STYLE)))
    with pytest.raises(AmbiguousPreference):
        resolve(_current(ledger), _history())


def _decision_setup(model, *, h=None, compatible=False):
    from sui.agent import Agent
    from worlds import _write_preferences
    clock = FakeClock(run=Ref(K.RUN, "decision")) if h is None else h.clock
    ledger = _ledger(*(h.records if h is not None else ()))
    ids = SequentialIds(prefix="decision")
    preferences = _write_preferences(model, ledger, clock, ids) if compatible else ()
    agent = Agent(model=model, lineage="decision")
    if ledger.heads():
        agent.adopt(ledger, clock=clock, ids=ids)
    else:
        agent.belief_record(clock=clock, ids=ids, ledger=ledger)
    return SimpleNamespace(model=model, agent=agent, ledger=ledger, clock=clock, ids=ids,
                           preferences=preferences)


def _binary_model(*, learnable=False, timed=False, changing=False, pending_none=False):
    import numpy as np
    from sui.model import GenerativeModel
    values = dict(states=("x",) if learnable else ("x0", "x1"), outcomes=("o0", "o1"),
        actions=("candidate", "pending"),
        a={name: np.ones((2, 1)) if learnable else np.eye(2) for name in ("candidate", "pending")},
        D=np.array([1.]) if learnable else np.array([.5, .5]),
        log_C=np.array([-.6931471805599453] * 2), gamma=1.,
        learnable=frozenset({"candidate", "pending"}) if learnable else frozenset())
    if changing:
        values["Q"] = np.array([[-.5, .5], [.5, -.5]])
    if timed:
        values.update(durations={"candidate": ((1., 1.),),
                                 "pending": ((1., .5), (None, .5)) if pending_none else ((2., 1.),)},
                      measures={"candidate": "report", "pending": "report"})
    return GenerativeModel(**values)


def test_c4_blank_one_step_keeps_parameter_information_and_ignores_model_preferences():
    import numpy as np
    from sui.agent import plan
    model = _binary_model(learnable=True)
    rig = _decision_setup(model)
    view = rig.agent.view()
    first = plan(view, model.actions, u=.5)
    data = first.content.as_json()
    assert data["evaluation"] == "one_step" and data["items"] == [] and data["style"] is None
    assert data["H_ns"] is None and data["gamma"] == 1.
    assert data["expected_cost"] == [0., 0.]
    assert data["information"] == pytest.approx([.1931471805599453] * 2, abs=1e-15)
    assert data["J"] == pytest.approx([-.1931471805599453] * 2, abs=1e-15)
    assert data["q_pi"] == [.5, .5] and "time" not in data
    changed = replace(model, log_C=np.log([.01, .99]), gamma=100.)
    assert plan(replace(view, model=changed), model.actions, u=.5).content == first.content
    class NoModelPreference:
        def __getattr__(self, name):
            if name in ("log_C", "gamma"):
                raise AssertionError("new plan read model preferences")
            return getattr(model, name)
    assert plan(replace(view, model=NoModelPreference()), model.actions, u=.5).content == first.content


@pytest.mark.parametrize("changing", [False, True])
@pytest.mark.parametrize("measure", ["start", "report"])
def test_n3_pending_none_is_half_the_information_without_counting_a_report(changing, measure):
    import numpy as np
    from sui.agent import plan
    from worlds import HandHistory
    model = replace(_binary_model(timed=True, changing=changing, pending_none=True),
                    measures={"candidate": "report", "pending": measure})
    if changing:
        # Qありの道でも同じ固定値を見るため、有限の測定は根の同時刻に置く。
        model = replace(model, durations={"candidate": ((0., 1.),), "pending": ((0., .5), (None, .5))})
    h = HandHistory()
    h.boot()
    h.start("pending")
    rig = _decision_setup(model, h=h, compatible=True)
    view = rig.agent.view(now_ns=0, observed_ns=0)
    result = plan(view, ("candidate",), u=.5).content.as_json()
    assert result["J"] == pytest.approx([.34657359027997264], abs=1e-15)
    assert result["information"] == pytest.approx([.34657359027997264], abs=1e-15)
    assert result["expected_cost"] == pytest.approx([.6931471805599453], abs=1e-15)
    assert "deadline_ns" not in result["time"]
    for counts in view.reading.n.values():
        np.testing.assert_array_equal(counts, [0, 0])
    # 根の未着を最後の有限点より後まで確かめれば、残りはNoneだけ。
    only_none = plan(replace(view, now_ns=2 * NS, observed_ns=2 * NS), ("candidate",), u=.5).content.as_json()
    assert only_none["J"] == pytest.approx([0.], abs=1e-15)
    assert only_none["information"] == pytest.approx([.6931471805599453], abs=1e-15)


def test_n3_none_candidate_rejects_whole_decision_and_compatibility_entry():
    from sui.agent import plan, plan_s4c
    from sui.lookahead import OutsideEvaluationType
    model = _binary_model(timed=True, pending_none=True)
    rig = _decision_setup(model)
    before = rig.ledger.entries()
    with pytest.raises(OutsideEvaluationType):
        plan(rig.agent.view(), model.actions, u=.5)
    with pytest.raises(ValueError, match="model.4"):
        plan_s4c(rig.agent.view(), ("candidate",), u=.5)
    assert rig.ledger.entries() == before


@pytest.mark.parametrize("kind", ["static", "learnable", "changing", "hand", "tiny"])
def test_c5_explicit_preference_matches_legacy_values_and_selection(kind):
    import numpy as np
    from sui.agent import plan, plan_s4c
    from worlds import _model, _time_model, _hand_model, HandHistory
    h, times = None, {}
    if kind in ("changing", "hand"):
        model = _time_model() if kind == "changing" else _hand_model()
        h = HandHistory()
        h.boot()
        first = h.start()
        h.observe(first, "o0", 1)
        h.start("look", seconds=1)
        times = {"now_ns": NS, "observed_ns": NS}
    elif kind == "tiny":
        model = replace(_binary_model(), log_C=np.array([0., -1000.]), gamma=2.)
    else:
        model = _model(learnable=frozenset({"look1", "look2"}) if kind == "learnable" else frozenset())
    rig = _decision_setup(model, h=h, compatible=True)
    view = rig.agent.view(**times)
    old = plan_s4c(view, model.actions, u=.4).content.as_json()
    new = plan(view, model.actions, u=.4).content.as_json()
    assert new["J"] == pytest.approx(old["G"], abs=1e-12)
    assert new["q_pi"] == pytest.approx(old["q_pi"], abs=1e-12)
    assert new["chosen"] == old["chosen"]
    assert new.get("time") == old.get("time")
    assert np.array_equal(np.array(new["J"]), np.array(new["expected_cost"]) - new["information"])


@pytest.mark.parametrize("gamma,expected", [(0., [.5, .5, 0.]),
    (1e-6, [.5000005, .4999995, 0.])])
def test_r7_zero_gamma_excludes_infinity_and_has_the_right_limit(gamma, expected):
    from sui.lookahead import _policy, NoAdmissibleCandidate
    assert _policy([0., 2., math.inf], gamma) == pytest.approx(expected, abs=1e-12)
    with pytest.raises(NoAdmissibleCandidate):
        _policy([math.inf, math.inf], gamma)


@pytest.mark.parametrize("gamma", [float("nan"), float("inf"), -float("inf"), -1., True])
def test_r7_policy_rejects_invalid_gamma(gamma):
    from sui.lookahead import _policy
    with pytest.raises(ValueError):
        _policy([0., 1.], gamma)


def test_c3_c8_commit_and_replay_keep_thinks_old_preferences():
    from sui.agent import plan, replay_decision
    from sui.s4d_contracts import DECISION
    rig = _decision_setup(_binary_model(), compatible=True)
    draft = plan(rig.agent.view(), rig.model.actions, u=.4)
    old_preferences = tuple(r.id for r in rig.preferences)
    changed = _record("changed", {**STYLE, "gamma": 0}, at=rig.clock.now())
    rig.ledger.append(changed, rig.ledger.heads())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    assert prepared.decided.body.inputs == (draft.belief, *old_preferences)
    assert prepared.decided.body.contract == DECISION
    assert prepared.decided.body.content == draft.content
    entry = rig.ledger.entries_of(prepared.decided.id)[0]
    assert entry.parents == draft.parents
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=entry.cid).content == draft.content


@pytest.mark.parametrize("legacy", [False, True])
def test_c8_replay_uses_parent_view_and_rejects_changed_decision(legacy):
    from sui.agent import plan, plan_s4c, replay_decision, RebuildMismatch
    rig = _decision_setup(_binary_model(), compatible=True)
    draft = (plan_s4c if legacy else plan)(rig.agent.view(), rig.model.actions, u=.4)
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    entry = rig.ledger.entries_of(prepared.decided.id)[0]
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=entry.cid).content == draft.content
    data = draft.content.as_json()
    data["G" if legacy else "J"][0] += .1
    wrong = replace(prepared.decided, id=rig.ids.new(K.DECISION), at=rig.clock.now(),
                     body=replace(prepared.decided.body, content=Payload.json(data)))
    wrong_entry = rig.ledger.append(wrong, entry.parents)
    with pytest.raises(RebuildMismatch):
        replay_decision(model=rig.model, ledger=rig.ledger, decision=wrong_entry.cid)


@pytest.mark.parametrize("changing,timed", [(False, False), (True, False), (False, True), (True, True)])
def test_c8_replay_rejects_legacy_contract_from_a_different_model_mode(changing, timed):
    """本文とinputsが同じでも旧約束だけのすり替えを拒む。正しい約束は再生できる。"""
    from sui.agent import plan_s4c, replay_decision, RebuildMismatch
    from sui.s1_contracts import DECISION as S1_DECISION
    from sui.s4_contracts import DECISION as TIME_DECISION
    from sui.s4_contracts import HAND_DECISION
    from worlds import HandHistory
    h = HandHistory()
    h.boot()
    rig = _decision_setup(_binary_model(timed=timed, changing=changing), h=h)
    draft = plan_s4c(rig.agent.view(now_ns=0, observed_ns=0), rig.model.actions, u=.4)
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    entry = rig.ledger.entries_of(prepared.decided.id)[0]
    expected = HAND_DECISION if timed else TIME_DECISION if changing else S1_DECISION
    assert prepared.decided.body.contract == expected
    assert replay_decision(model=rig.model, ledger=rig.ledger, decision=entry.cid).content == draft.content
    for wrong_contract in {S1_DECISION, TIME_DECISION, HAND_DECISION} - {expected}:
        wrong = replace(prepared.decided, id=rig.ids.new(K.DECISION), at=rig.clock.now(),
                        body=replace(prepared.decided.body, contract=wrong_contract))
        wrong_entry = rig.ledger.append(wrong, entry.parents)
        with pytest.raises(RebuildMismatch) as exc:
            replay_decision(model=rig.model, ledger=rig.ledger, decision=wrong_entry.cid)
        assert exc.value.fields == ("contract",)


def _deterministic_model():
    import numpy as np
    return replace(_binary_model(), a={"candidate": np.array([[1., 1.], [0., 0.]]),
                                      "pending": np.array([[0., 0.], [1., 1.]])})


def _adopt_preferences(rig, *records):
    for record in records:
        rig.ledger.append(record, rig.ledger.heads())
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)


@pytest.mark.parametrize("gamma", [0., 1.])
def test_c8_one_step_infinity_is_recorded_replayed_and_excluded(gamma):
    """禁止は候補の欄を残し、情報の未定義とは区別する。"""
    from sui.agent import plan, replay_decision, RebuildMismatch
    rig = _decision_setup(_deterministic_model())
    item = _record("item", {**ITEM, "args": _feature_args(probs=[["o0", 1.]])})
    style = _record("style", {**STYLE, "gamma": gamma})
    _adopt_preferences(rig, item, style)
    draft = plan(rig.agent.view(), rig.model.actions, u=.999)
    data = draft.content.as_json()
    assert data["J"] == data["expected_cost"] == [0., "+inf"]
    assert data["information"] == [0., 0.] and "undefined_reason" not in data
    assert data["q_pi"] == [1., 0.] and data["chosen"] == "candidate"
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    rig.agent.commit(prepared, ledger=rig.ledger)
    entry = rig.ledger.entries_of(prepared.decided.id)[0]
    replayed = replay_decision(model=rig.model, ledger=rig.ledger, decision=entry.cid)
    assert replayed == draft
    for field in ("J", "expected_cost", "information", "q_pi"):
        wrong = draft.content.as_json()
        wrong[field][1] = "infinity" if field in ("J", "expected_cost") else "+inf"
        record = replace(prepared.decided, id=rig.ids.new(K.DECISION),
            body=replace(prepared.decided.body, content=Payload.json(wrong)))
        cid = rig.ledger.append(record, entry.parents).cid
        with pytest.raises(RebuildMismatch):
            replay_decision(model=rig.model, ledger=rig.ledger, decision=cid)


@pytest.mark.parametrize("disjoint", [False, True])
def test_c6_no_admissible_candidate_with_zero_or_positive_product_normalizer(disjoint):
    """積が正規化できても、各手に禁止の結果が混ざれば決めない。"""
    from sui.agent import plan
    from sui.lookahead import NoAdmissibleCandidate
    rig = _decision_setup(_deterministic_model() if disjoint else _binary_model())
    records = [_record("o0", {**ITEM, "args": _feature_args(probs=[["o0", 1.]])})]
    if disjoint:
        records.append(_record("o1", {**ITEM, "args": _feature_args(probs=[["o1", 1.]])}))
    _adopt_preferences(rig, *records)
    before = rig.ledger.entries()
    with pytest.raises(NoAdmissibleCandidate):
        plan(rig.agent.view(), rig.model.actions, u=.5)
    assert rig.ledger.entries() == before


def test_c2_c6_merged_items_preserve_decision_bytes_and_strengthen_preference():
    """同じ付箋は再配送で増えず、別名の同じ付箋は足して16/17になる。"""
    from sui.agent import plan
    records = [_record(name, {**ITEM, "args": _feature_args()}) for name in ("a", "b")]
    baseline = None
    for order in permutations(records):
        rig = _decision_setup(_deterministic_model())
        for record in (*order, order[0]):
            rig.ledger.merge(_ledger(record))
        rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
        draft = plan(rig.agent.view(), rig.model.actions, u=.5)
        data = draft.content.as_json()
        assert data["expected_cost"] == pytest.approx([.4462871026284194, 3.2188758248682006], abs=1e-15)
        assert data["q_pi"] == pytest.approx([16 / 17, 1 / 17], abs=1e-15)
        assert draft.preference_inputs == tuple(record.id for record in records)
        if baseline is None:
            baseline = draft.content
        assert draft.content == baseline


@pytest.mark.parametrize("feature", ["outcome_multiset", "outcome_groups", "started_actions", "counts", "timed_path"])
@pytest.mark.parametrize("paper", [False, True])
def test_c4_one_step_rejects_path_features_but_withdrawn_items_do_not_select_type(feature, paper):
    """白紙とH=nullの両方で、型の検査は残った付箋だけに行う。"""
    from sui.agent import plan
    from sui.lookahead import OutsideEvaluationType
    rig = _decision_setup(_binary_model())
    item = _record("item", {**ITEM, "args": _feature_args(feature, probs=[[None, 1.]])})
    _adopt_preferences(rig, item, *([_record("style", STYLE)] if paper else []))
    with pytest.raises(OutsideEvaluationType):
        plan(rig.agent.view(), rig.model.actions, u=.5)
    _adopt_preferences(rig, _record("withdraw", {"kind": "withdraw", "items": [str(item.id)]}))
    assert plan(rig.agent.view(), rig.model.actions, u=.5).content.as_json()["items"] == []


def test_c4_lookahead_rejects_candidate_outcome_before_evaluation():
    from sui.agent import plan
    from sui.lookahead import OutsideEvaluationType
    rig = _decision_setup(_binary_model())
    _adopt_preferences(rig, _record("item", {**ITEM, "args": _feature_args()}),
                        _record("style", {**STYLE, "H_ns": NS}))
    with pytest.raises(OutsideEvaluationType):
        plan(rig.agent.view(), rig.model.actions, u=.5)


@pytest.mark.parametrize("missing", [False, True])
def test_c7_unreadable_preference_reaches_drive_as_thought_error(missing):
    """statusとadoptとThink発行は成功し、評価の失敗を駆動へ返す。"""
    from sui.runtime import Window, Tick, Reconsider, Think, Thought
    from worlds import ManualHost, ScriptDrive, GatedHand
    rig = _decision_setup(_binary_model())
    item = _record("item", ITEM if missing else Payload.text("unreadable"))
    entry = rig.ledger.append(item, rig.ledger.heads())
    if missing:
        rig.ledger.contents.discard(entry.seal)
    drive = ScriptDrive(lambda status, event: [Reconsider(candidates=rig.model.actions, u=.5)]
                        if isinstance(event, Tick) else [])
    host = ManualHost(lambda pledges: Window(agent=rig.agent, ledger=rig.ledger,
        clock=rig.clock, ids=rig.ids, hand=GatedHand({a: set() for a in rig.model.actions}, {}),
        membrane=item.producer, route="test", drive=drive, capacity={"think": 1}, pledges=pledges),
        clock=rig.clock)
    host.advance(1)
    host.step()
    assert host.window.status().thinking == 1
    work = next(work for work, _ in host.work if isinstance(work, Think))
    event = host.finish(work)
    assert isinstance(event, Thought) and event.error == "PreferenceUnreadable" and event.draft is None
    host.step()
    assert host.window.status().thinking == 0
    assert any(isinstance(event, Thought) and event.error == "PreferenceUnreadable"
               for _, event in drive.calls)
    assert not any(entry.body_type is Decided for entry in rig.ledger.entries())


def test_c4_one_step_style_gamma_zero_and_constant_keep_external_cost():
    """γ=0は有限の候補を一様にし、constantも候補の値だけに正規化し直さない。"""
    from sui.agent import plan
    rig = _decision_setup(_deterministic_model())
    _adopt_preferences(rig, _record("item", {**ITEM, "args": _feature_args()}),
        _record("constant", {**ITEM, "args": _feature_args("constant", probs=[[None, .25], ["unused", .75]])}),
        _record("style", {**STYLE, "gamma": 0.}))
    data = plan(rig.agent.view(), rig.model.actions, u=.5).content.as_json()
    assert data["J"] == pytest.approx([1.6094379124341003, 2.995732273553991], abs=1e-15)
    assert data["expected_cost"] == data["J"] and data["information"] == [0., 0.]
    assert data["q_pi"] == [.5, .5] and data["gamma"] == 0. and data["chosen"] == "pending"


@pytest.mark.parametrize("kind", ["missing", "order", "outside"])
def test_c3_preference_inputs_are_checked_before_commit_writes(kind):
    """inputsは本文の順と親の範囲に一致する。検査に失敗したら無書き込み。"""
    from sui.agent import plan
    rig = _decision_setup(_binary_model(), compatible=True)
    draft = plan(rig.agent.view(), rig.model.actions, u=.5)
    prepared = rig.agent.prepare(draft, clock=rig.clock, ids=rig.ids)
    body = prepared.decided.body
    if kind == "missing":
        body = replace(body, inputs=body.inputs[:1])
    elif kind == "order":
        body = replace(body, inputs=(body.inputs[0], *reversed(body.inputs[1:])))
    else:
        later = _record("later")
        rig.ledger.append(later, rig.ledger.heads())
        data = body.content.as_json()
        data["items"][0]["id"] = str(later.id)
        body = replace(body, inputs=(body.inputs[0], later.id, body.inputs[2]), content=Payload.json(data))
    wrong = replace(prepared, decided=replace(prepared.decided, body=body))
    before = rig.ledger.entries()
    with pytest.raises(ValueError, match="preference inputs"):
        rig.agent.commit(wrong, ledger=rig.ledger)
    assert rig.ledger.entries() == before
