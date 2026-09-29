from dataclasses import replace
import hashlib
import json

import numpy as np
import pytest

from sui.agent import Agent
from sui.clock import ClockError, FakeClock, Instant
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds, derive
from sui.ledger import (Ledger, MemoryContents, SequentialSalts, RandomSalts,
    Relation, MissingParent, DerivedParent, CorruptEntry, UnknownEntry, seal,
    encode_header, decode_record)
from sui.loop import run_step
from sui.model import model_ref
from sui.records import (Observed, Decided, JobOpened, AttemptStarted, Prediction,
    Interpretation, Intention, IntentionStatus, Payload, Producer, Record, Role,
    StateRef, SchemaMismatch, IdConflict)
from sui.s1_contracts import OUTCOME
from test_agent import _setup, _start, _observed, _observe, _decide, _binary_model
from worlds import _close, _exact_posterior, _model, ScriptedWorld
from worlds import _storage


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_s2b_ledger_store_substitution(tmp_path, backend):
    with _storage(tmp_path, backend) as store:
        ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        parent = ledger.accept(_record())
        child = ledger.accept(_record("child", 8))
        assert child.parents == frozenset({parent.cid})
        assert ledger.heads() == frozenset({child.cid})
        assert ledger.accept(_record()) == parent
        assert ledger.relation(parent.cid, child.cid) is Relation.BEFORE
        ledger.verify()
        restored = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        assert restored.entries() == ledger.entries()
        assert restored.snapshot(restored.heads()) == ledger.snapshot(ledger.heads())


F1 = "sha256:f781b457f1344b913984a8884673e21fcb23329ebf3888ea557084b49421a7de"
ZERO, FF = "sha256:" + "0" * 64, "sha256:" + "f" * 64
F2 = b'{"at":{"mono_ns":0,"run":"run:r1","run_index":0,"seq":4,"wall_ns":1790000000000000000},"body":{"caused_by":"attempt:a1","contract":{"name":"sui.s1.outcome","version":"2"},"received_ns":null,"route":"executor","source_id":null,"source_time_ns":null,"type":"Observed"},"id":"observation:o1","parents":[],"producer":{"code_version":"s2a","component":"sui.membrane","state":null},"schema":3,"seal":"sha256:f781b457f1344b913984a8884673e21fcb23329ebf3888ea557084b49421a7de","writer":"membrane"}'


def _f4():
    return _binary_model({"look": np.array([[2., 1.], [1., 2.]])}, learnable=frozenset({"look"}))


def _record(name="o1", seq=4, *, run="r1", body=None, **changes):
    if body is None:
        body = Observed(route="executor", content=Payload.json({"outcome": "o1"}),
                        contract=OUTCOME, caused_by=Ref(K.ATTEMPT, "a1"))
    kinds = {Observed: K.OBSERVATION, Decided: K.DECISION, JobOpened: K.JOB,
             AttemptStarted: K.ATTEMPT, Prediction: K.PREDICTION,
             Interpretation: K.INTERPRETATION, Intention: K.INTENTION}
    values = dict(id=Ref(kinds[type(body)], name),
        at=Instant(run=Ref(K.RUN, run), run_index=0, seq=seq, mono_ns=0,
                   wall_ns=1_790_000_000_000_000_000),
        writer=Role.MEMBRANE if type(body) in (Observed, AttemptStarted) else Role.MODEL,
        producer=Producer(component="sui.membrane", code_version="s2a"), body=body)
    values.update(changes)
    return Record(**values)


def _leaf(name="leaf", seq=9):
    return _record(name, seq, body=Prediction(target="belief", about=(), basis=(),
                   content=Payload.json({}), contract=ContractRef("sui.test", "1")))


def _copy(source):
    result = Ledger(salts=SequentialSalts())
    result.merge(source)
    return result


def _content(rig):
    return rig.agent._belief.body.content.as_json()


def test_g1_seal_fixed_values_and_sources():
    content = Payload.json({"outcome": "o1"})
    assert seal(content, bytes(range(16))) == F1
    assert seal(content, bytes(range(1, 17))) == "sha256:655f98773f8bfccfef3fa7586967131b0700922b3285c3f21d40779f376f78ed"
    for salt in (bytes(15), bytes(17), "0" * 16, bytearray(16)):
        with pytest.raises(ValueError):
            seal(content, salt)
    salts = SequentialSalts()
    assert [salts.new() for _ in range(3)] == [k.to_bytes(16, "big") for k in (1, 2, 3)]
    assert isinstance(RandomSalts().new(), bytes)
    assert len(RandomSalts().new()) == 16


def test_g2_canonical_header_and_cid_fixed_values():
    record = _record()
    assert encode_header(record, F1, frozenset()) == F2
    for parents, expected in [
        ([], "7f3bd8513bb63144c3981ad979a68e966cf7b753f2c5eceb42aa6ca1dd592381"),
        ([ZERO], "41e894214e31a48a301909bef5706bff85f6f941bd74a2cdc67fad9c7413a528"),
        ([ZERO, FF], "d96a415667766149665a21daba1211cb839aa888df14b2e0924bf29f140e627f"),
        ([FF, ZERO], "d96a415667766149665a21daba1211cb839aa888df14b2e0924bf29f140e627f"),
    ]:
        assert hashlib.sha256(encode_header(record, F1, frozenset(parents))).hexdigest() == expected
    class FixedSalt:
        def new(self):
            return bytes(range(16))
    ledger = Ledger(salts=FixedSalt())
    entry = ledger.accept(record)
    assert entry.cid == "sha256:7f3bd8513bb63144c3981ad979a68e966cf7b753f2c5eceb42aa6ca1dd592381"
    assert entry.header == F2
    assert ledger.record(entry.cid) == record


@pytest.mark.parametrize("full", [False, True])
@pytest.mark.parametrize("kind", [Observed, Decided, JobOpened, AttemptStarted, Prediction, Interpretation, Intention])
def test_g3_all_bodies_round_trip(kind, full):
    observation, decision, attempt = Ref(K.OBSERVATION, "o"), Ref(K.DECISION, "d"), Ref(K.ATTEMPT, "t")
    values = {
        Observed: dict(route="経路", **(dict(caused_by=attempt, source_id="元", source_time_ns=-10) if full else {})),
        Decided: dict(inputs=(observation,) if full else ()),
        JobOpened: dict(decision=decision, step=2), AttemptStarted: dict(job=Ref(K.JOB, "j")),
        Prediction: dict(target="予測", about=(observation,) if full else (), basis=(decision, attempt) if full else ()),
        Interpretation: dict(about=(observation,) if full else (), basis=(decision,) if full else ()),
        Intention: dict(target=Ref(K.RUN, "r"), operation="操作", decided_in=decision,
                       status=IntentionStatus.EXECUTED if full else IntentionStatus.CONFIRMED,
                       **(dict(supersedes=Ref(K.INTENTION, "old"), via=attempt) if full else {})),
    }[kind]
    body = kind(content=Payload("application/octet-stream", b"\x00\xff"), contract=ContractRef("sui.test", "1"), **values)
    producer = Producer(component="部品", code_version="2", state=StateRef(lineage="x", revision=3) if full else None)
    record = _record(body=body, producer=producer)
    header = encode_header(record, F1, frozenset({ZERO, FF}))
    assert decode_record(header, body.content) == record
    for schema in (1, 4):
        data = json.loads(header)
        data["schema"] = schema
        with pytest.raises(SchemaMismatch):
            decode_record(Payload.json(data).data, body.content)
    data = json.loads(header)
    del data["producer"]
    with pytest.raises(CorruptEntry):
        decode_record(Payload.json(data).data, body.content)


def test_g4_model_reference_fixed_value_and_sensitivity():
    model = _f4()
    expected = "sha256:568c5dd475ebe1518c227944556166aaf647328d2f86507dd696f82a06824fb2"
    assert model_ref(model) == expected
    for changes in (dict(D=np.array([.5000000000000001, .4999999999999999])),
                    dict(gamma=63.0), dict(learnable=frozenset())):
        assert model_ref(replace(model, **changes)) != expected


def test_g5_g6_late_decision_does_not_change_past_snapshot():
    ledger = Ledger(salts=SequentialSalts())
    first = ledger.accept(_record("first", 1))
    decision = _record("d", 5, body=Decided(inputs=(), content=Payload.json({}), contract=ContractRef("sui.test", "1")))
    obs = ledger.accept(_record("o", 7))
    before = ledger.snapshot({obs.cid})
    dec = ledger.append(decision, {first.cid})
    assert ledger.snapshot({obs.cid}).records == before.records
    assert decision not in before.records
    assert ledger.relation(dec.cid, obs.cid) is Relation.CONCURRENT
    assert ledger.heads() == {dec.cid, obs.cid}
    next_obs = ledger.accept(_record("next", 8))
    assert next_obs.parents == {dec.cid, obs.cid}


def test_g6_decision_uses_agent_frontier():
    rig = _setup()
    run_step(rig.agent, ScriptedWorld({"look1": ["o1"]}), ["look1"], u=.5,
             clock=rig.clock, ids=rig.ids, ledger=rig.ledger, membrane=rig.membrane)
    rig.ledger.accept(_observed(rig))
    assert rig.agent.frontier != rig.ledger.heads()
    dec, _ = _decide(rig)
    assert rig.ledger.entries_of(dec.id)[0].parents == rig.agent.frontier


def test_g7_derived_leaves_never_become_parents_or_heads():
    ledger = Ledger(salts=SequentialSalts())
    event = ledger.accept(_record())
    leaf = ledger.append(_leaf(), {event.cid})
    before = ledger.entries()
    assert ledger.heads() == {event.cid}
    with pytest.raises(DerivedParent):
        ledger.append(_record("bad", 10), {leaf.cid})
    assert ledger.entries() == before
    assert ledger.accept(_record("next", 11)).parents == {event.cid}


@pytest.mark.parametrize("failure", ["missing", "clock", "conflict", "writer", "unicode", "type", "cid"])
def test_g8_validation_is_atomic_before_salt(failure):
    salts = SequentialSalts()
    ledger = Ledger(salts=salts)
    record = _record()
    parent = ledger.accept(record)
    before = ledger.entries(), ledger.heads(), dict(ledger.contents._items)
    if failure == "missing":
        call, error = lambda: ledger.append(_record("next", 5), {ZERO}), MissingParent
    elif failure == "clock":
        call, error = lambda: ledger.append(_record("next", 3), {parent.cid}), ClockError
    elif failure == "conflict":
        call = lambda: ledger.accept(replace(record, body=replace(record.body, route="other")))
        error = IdConflict
    elif failure == "writer":
        call, error = lambda: ledger.accept(_leaf()), ValueError
    elif failure == "unicode":
        broken = _record("next", 5, producer=Producer(component="\ud800", code_version="s2a"))
        call, error = lambda: ledger.accept(broken), ValueError
    elif failure == "type":
        call, error = lambda: ledger.append(object(), ()), TypeError
    else:
        call, error = lambda: ledger.append(_record("next", 5), {"bad"}), ValueError
    with pytest.raises(error) as exc:
        call()
    if failure == "conflict":
        assert exc.value.fields == ("body.route",)
    assert (ledger.entries(), ledger.heads(), ledger.contents._items) == before
    assert salts.new() == (2).to_bytes(16, "big")


def test_g8_storage_failure_does_not_add_entry():
    class FailingContents(MemoryContents):
        def put(self, *args):
            raise RuntimeError("put failed")
    ledger = Ledger(salts=SequentialSalts(), contents=FailingContents())
    with pytest.raises(RuntimeError, match="put failed"):
        ledger.accept(_record())
    assert ledger.entries() == () and ledger.heads() == frozenset()


def test_g9_redelivery_checks_metadata_but_ignores_new_parents():
    ledger = Ledger(salts=SequentialSalts())
    record = _record()
    first = ledger.accept(record)
    later = replace(record, at=replace(record.at, seq=9), producer=Producer(component="other", code_version="2"))
    with pytest.raises(IdConflict):
        ledger.accept(later)
    assert ledger.append(record, {ZERO}) is first
    assert ledger.entries() == (first,)


def test_g10_causal_order_between_maximal_and_all_relations():
    ledger = Ledger(salts=SequentialSalts())
    a = ledger.append(_record("a", 1), ())
    b = ledger.append(_record("b", 2), {a.cid})
    c = ledger.append(_record("c", 3), {a.cid})
    d = ledger.append(_record("d", 4), {b.cid, c.cid})
    middle = tuple(sorted((b, c), key=lambda e: e.cid))
    assert ledger.entries() == (a, *middle, d)
    assert ledger.between({a.cid}, {d.cid}) == (*middle, d)
    assert ledger.between({b.cid}, {d.cid}) == (c, d)
    assert ledger.between({d.cid}, {d.cid}) == ()
    assert ledger.between((), {b.cid}) == (a, b)
    assert ledger.ancestors({d.cid}) == {a.cid, b.cid, c.cid, d.cid}
    assert ledger.maximal({a.cid, b.cid, c.cid}) == {b.cid, c.cid}
    assert ledger.relation(a.cid, d.cid) is Relation.BEFORE
    assert ledger.relation(d.cid, a.cid) is Relation.AFTER
    assert ledger.relation(b.cid, c.cid) is Relation.CONCURRENT
    assert ledger.relation(a.cid, a.cid) is Relation.SAME
    assert ledger.entries_of(Ref(K.OBSERVATION, "missing")) == ()
    with pytest.raises(UnknownEntry):
        ledger.entry(ZERO)
    # run_index は別の run の順を決めない。
    cross = ledger.append(_record("cross", 1, run="r2"), {d.cid})
    assert ledger.relation(d.cid, cross.cid) is Relation.BEFORE


@pytest.mark.parametrize("field", ["header", "body_type", "id", "at", "writer", "parents", "seal", "content", "missing_content"])
def test_g11_verify_detects_every_redundant_field_and_payload(field):
    ledger = Ledger(salts=SequentialSalts())
    entry = ledger.accept(_record())
    assert ledger.verify() is None
    replacements = dict(header=entry.header[:-1] + b" ", body_type=Decided,
        id=Ref(K.OBSERVATION, "other"), at=replace(entry.at, seq=100),
        writer=Role.MODEL, parents=frozenset({ZERO}), seal=ZERO)
    if field == "content":
        salt, _ = ledger.contents._items[entry.seal]
        ledger.contents._items[entry.seal] = salt, Payload.json({"outcome": "o0"})
    elif field == "missing_content":
        del ledger.contents._items[entry.seal]
    else:
        ledger._entries[entry.cid] = replace(entry, **{field: replacements[field]})
    with pytest.raises(CorruptEntry, match=entry.cid):
        ledger.verify()


def test_g12_merge_counts_union_of_fact_ids():
    rig = _setup(_model(learnable=frozenset({"look1"})))
    for _ in range(5):
        _observe(rig, _observed(rig, _start(rig), "o1"))
    other = _copy(rig.ledger)
    branch = Agent.restore(model=rig.model, lineage="branch", ledger=other,
                           belief=rig.ledger.entries_of(rig.agent._belief.id)[0].cid)
    for agent, ledger, prefix in [(rig.agent, rig.ledger, "left"), (branch, other, "right")]:
        run_step(agent, ScriptedWorld({"look1": ["o1"]}), ["look1"], u=.5,
                 clock=FakeClock(run=Ref(K.RUN, prefix)), ids=SequentialIds(prefix), ledger=ledger,
                 membrane=rig.membrane)
    rig.ledger.merge(other)
    subject = Agent(model=rig.model, lineage="union")
    belief = subject.adopt(rig.ledger, clock=FakeClock(run=Ref(K.RUN, "union")), ids=SequentialIds("union"))
    data = belief.body.content.as_json()
    assert data["n"] == {"look1": [0, 7, 0], "look2": [0, 0, 0], "wait": [0, 0, 0]}
    q, tally = _exact_posterior(rig.model.D, rig.model.a, rig.model.learnable, [("look1", 1)] * 7)
    _close(data["q"], q)
    for action in rig.model.actions:
        expected = np.where(rig.model.a[action] > 0, rig.model.a[action] + tally[action][:, None], 0) if action == "look1" else rig.model.a[action]
        np.testing.assert_array_equal(data["a"][action], expected)
    # 合わせた二つの道と、同じ七件を一か所で読んだ道はビット単位でも同じ。
    sequential = _setup(rig.model)
    for _ in range(7):
        _observe(sequential, _observed(sequential, _start(sequential), "o1"))
    for key in ("q", "a", "n", "unread"):
        assert data[key] == _content(sequential)[key]


def test_g13_same_fact_has_two_cids_but_is_read_once():
    rig = _setup(_f4())
    attempt = _start(rig, "look")
    other = _copy(rig.ledger)
    external = _observed(rig)
    other.accept(external)
    obs = replace(_observed(rig, attempt), id=derive(K.OBSERVATION, "same-fact"))
    left, right = rig.ledger.accept(obs), other.accept(obs)
    assert left.cid != right.cid
    rig.ledger.merge(other)
    assert tuple(e.cid for e in rig.ledger.entries_of(obs.id)) == tuple(sorted((left.cid, right.cid)))
    assert rig.ledger.accept(obs).cid == min(left.cid, right.cid)
    rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    assert _content(rig)["n"]["look"] == [0, 1]
    assert obs.id not in dict(rig.agent.unread)


def test_g14_merge_preflights_conflicts_and_obeys_set_laws():
    a, b = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    a.accept(_record("common", 1))
    b.accept(_record("new", 1, run="r2"))
    b.accept(replace(_record("common", 2, run="r2"), body=replace(_record().body, route="other")))
    before = a.entries(), dict(a.contents._items)
    with pytest.raises(IdConflict):
        a.merge(b)
    assert (a.entries(), a.contents._items) == before
    c = Ledger(salts=SequentialSalts())
    c.accept(_record("third", 1, run="r3"))
    left, right = _copy(a), _copy(c)
    left.merge(c)
    right.merge(a)
    assert {e.cid for e in left.entries()} == {e.cid for e in right.entries()}
    before = left.entries(), dict(left.contents._items)
    left.merge(c)
    assert (left.entries(), left.contents._items) == before
    assert a.entries() == (a.entries_of(Ref(K.OBSERVATION, "common"))[0],)


def test_g15_merge_retracts_ambiguous_learning_and_restores_both_states():
    rig = _setup(_f4())
    attempt = _start(rig, "look")
    other = _copy(rig.ledger)
    o1, o0 = _observed(rig, attempt, "o1"), _observed(rig, attempt, "o0")
    first = _observe(rig, o1)
    other.accept(o0)
    first_data = first.body.content.as_json()
    _close(first_data["q"], [1 / 3, 2 / 3])
    assert first_data["n"]["look"] == [0, 1]
    assert first_data["a"]["look"] == [[2, 1], [2, 3]]
    rig.ledger.merge(other)
    second = rig.agent.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    second_data = second.body.content.as_json()
    assert second_data["q"] == [.5, .5]
    assert second_data["n"]["look"] == [0, 0]
    assert second_data["a"]["look"] == [[2, 1], [1, 2]]
    assert dict(rig.agent.unread) == {o0.id: "ambiguous_attempt", o1.id: "ambiguous_attempt"}
    for record in (first, second):
        subject = Agent.restore(model=rig.model, lineage="restored", ledger=rig.ledger,
                                belief=rig.ledger.entries_of(record.id)[0].cid)
        rebuilt = subject.belief_record(clock=rig.clock, ids=rig.ids, ledger=rig.ledger)
        assert rebuilt.body.content == record.body.content
    subject = Agent(model=rig.model, lineage="fresh")
    fresh = subject.adopt(rig.ledger, clock=rig.clock, ids=rig.ids)
    assert fresh.body.content == second.body.content


def test_g16_missing_contents_raise_with_and_without_cached_record():
    errors = []
    for clear_cache in (False, True):
        ledger = Ledger(salts=SequentialSalts())
        record = _record()
        entry = ledger.accept(record)
        assert ledger.record(entry.cid) == record
        if clear_cache:
            ledger._records.clear()
        del ledger.contents._items[entry.seal]
        with pytest.raises(KeyError) as error:
            ledger.record(entry.cid)
        errors.append(error.value.args)
    assert errors[0] == errors[1]


def test_g16_replaced_contents_are_read_with_and_without_cached_record():
    replacement = Payload.json({"outcome": "o0"})
    results = []
    for clear_cache in (False, True):
        ledger = Ledger(salts=SequentialSalts())
        record = _record()
        entry = ledger.accept(record)
        cached = ledger.record(entry.cid)
        if clear_cache:
            ledger._records.clear()
        salt, _ = ledger.contents._items[entry.seal]
        ledger.contents._items[entry.seal] = salt, replacement
        rebuilt = ledger.record(entry.cid)
        assert rebuilt is not cached
        assert rebuilt == replace(record, body=replace(record.body, content=replacement))
        assert rebuilt.body.content == replacement
        assert ledger.record(entry.cid) is rebuilt
        results.append(rebuilt)
    assert results[0] == results[1]


def test_g16_equal_but_distinct_entry_invalidates_cached_record():
    ledger = Ledger(salts=SequentialSalts())
    entry = ledger.accept(_record())
    cached = ledger.record(entry.cid)
    replacement = replace(entry)
    assert replacement == entry and replacement is not entry
    ledger._entries[entry.cid] = replacement
    rebuilt = ledger.record(entry.cid)
    assert rebuilt == cached and rebuilt is not cached
    assert ledger._records[entry.cid][0] is replacement
    assert ledger.record(entry.cid) is rebuilt


def test_memory_contents_rejects_conflicting_put_and_missing_get():
    contents = MemoryContents()
    salt, content = bytes(16), Payload.json({})
    contents.put(F1, salt, content)
    contents.put(F1, salt, content)
    assert contents.get(F1) == (salt, content)
    with pytest.raises(ValueError):
        contents.put(F1, salt, Payload.json([]))
    with pytest.raises(KeyError):
        contents.get(ZERO)
