from dataclasses import replace

import pytest

from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import Ledger, SequentialSalts, DerivedParent
from sui.records import (Observed, Prediction, Interpretation, Preference, Intention,
                         IntentionStatus, Decided, Payload, Producer, Record, Role)
from sui.snapshot import Absent, Found, Snapshot, Unknown


@pytest.fixture
def records():
    clock, ids = FakeClock(run=Ref(K.RUN, "r1")), SequentialIds()
    def make(body_type=Observed, **changes):
        values = dict(content=Payload.text("この実験を終わらせる"), contract=ContractRef("sui.test", "1"))
        if body_type is Observed:
            values.update(route="channel:letter")
            kind, role = K.OBSERVATION, Role.MEMBRANE
        elif body_type is Prediction:
            values.update(target="next", about=(), basis=())
            kind, role = K.PREDICTION, Role.MODEL
        elif body_type is Decided:
            values.update(inputs=())
            kind, role = K.DECISION, Role.MODEL
        else:
            values.update(target=Ref(K.RUN, "exp1"), operation="end", status=IntentionStatus.CONFIRMED,
                          decided_in=Ref(K.DECISION, "missing"))
            kind, role = K.INTENTION, Role.MODEL
        values.update(changes)
        return Record(id=ids.new(kind), at=clock.now(), writer=role,
                      producer=Producer(component="test", code_version="1"), body=body_type(**values))
    return make


def snapshot_of(*records):
    ledger = Ledger(salts=SequentialSalts())
    for record in records:
        ledger.append(record, ledger.heads())
    return ledger.snapshot(ledger.heads())


@pytest.mark.parametrize("body_type,kind", [(Prediction, K.PREDICTION),
    (Interpretation, K.INTERPRETATION), (Preference, K.PREFERENCE)])
def test_s1_derived_types_are_always_unknown(records, body_type, kind):
    obs, prediction = records(), records(Prediction)
    snapshot = snapshot_of(obs, prediction)
    assert snapshot.records == (obs,)
    assert isinstance(snapshot.find(body_type), Unknown)
    assert isinstance(snapshot.resolve(Ref(kind, "missing")), Unknown)
    assert isinstance(snapshot.resolve(prediction.id), Unknown)


def test_s2_event_types_can_be_absent(records):
    snapshot = snapshot_of(records())
    assert snapshot.find(Intention) == Absent()
    assert snapshot.find(Observed, lambda r: False) == Absent()


def test_s4_resolve_exact_id_and_missing_kinds(records):
    obs = records()
    snapshot = snapshot_of(obs)
    assert snapshot.resolve(obs.id) == Found(records=(obs,))
    for kind in (K.OBSERVATION, K.INTENTION):
        assert snapshot.resolve(Ref(kind, "missing")) == Absent()
    for kind in (K.RUN, K.INDIVIDUAL):
        with pytest.raises(ValueError):
            snapshot.resolve(Ref(kind, "r1"))


def test_s5_unresolved_includes_belief_inputs_and_excludes_runs(records):
    obs = records()
    prediction = records(Prediction, basis=(obs.id,))
    dec = records(Decided, inputs=(obs.id, prediction.id))
    will = records(Intention, decided_in=dec.id)
    assert snapshot_of(obs, prediction, dec, will).unresolved() == {prediction.id}
    assert snapshot_of(records(Intention)).unresolved() == {Ref(K.DECISION, "missing")}


def test_s6_duplicate_ids_and_wrong_types_are_rejected(records):
    obs = records()
    with pytest.raises(ValueError):
        Snapshot(records=(obs, replace(obs)), frontier=frozenset())
    for values in ([obs], ("text",)):
        with pytest.raises(TypeError):
            Snapshot(records=values, frontier=frozenset())
    with pytest.raises(TypeError):
        Snapshot(records=(), frontier=None)
    with pytest.raises(ValueError):
        Found(records=())
    with pytest.raises(TypeError):
        Found(records=[obs])
    with pytest.raises(TypeError):
        Unknown(reason=1)
    with pytest.raises(TypeError):
        Found((obs,))
    with pytest.raises(TypeError):
        Unknown("reason")


def test_s8_find_preserves_causal_order_and_applies_filter(records):
    first, second, third = records(), records(route="channel:other"), records()
    first, second, third = [replace(record, id=Ref(K.OBSERVATION, name))
                            for record, name in zip((first, second, third), ("z", "a", "m"))]
    snapshot = snapshot_of(first, second, third)
    assert snapshot.records == (first, second, third)
    assert snapshot.find(Observed) == Found(records=(first, second, third))
    assert snapshot.find(Observed, lambda r: r.body.route == "channel:letter") == Found(records=(first, third))
    with pytest.raises(ValueError):
        snapshot.find(str)


def test_s9_unknown_reason_and_derived_frontier(records):
    ledger = Ledger(salts=SequentialSalts())
    leaf = ledger.append(records(Prediction), ())
    with pytest.raises(DerivedParent):
        ledger.snapshot({leaf.cid})
    expected = Unknown(reason="derived records are not part of a snapshot; rebuild them from the model and the facts")
    assert ledger.snapshot(()).find(Prediction) == expected
    assert ledger.snapshot(()).resolve(leaf.id) == expected


def test_t10b_representative_stays_inside_the_snapshot_frontier(records):
    early = replace(records(), schema=2)
    late = replace(early, at=replace(early.at, seq=early.at.seq + 1, mono_ns=20))
    left, right = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    late_entry = left.accept(late)
    early_entry = right.accept(early)
    leaf = records(Prediction)
    leaf = replace(leaf, at=replace(late.at, seq=late.at.seq + 1))
    left.append(leaf, {late_entry.cid})
    left.merge(right)
    left.verify()
    assert left.snapshot({late_entry.cid}).records == (late,)
    assert left.snapshot({early_entry.cid}).records == (early,)
    assert left.snapshot(left.heads()).records == (early,)
    assert len(left.entries_of(early.id)) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_t10b_snapshot_orders_the_chosen_record_at_its_own_position(records, reverse):
    middle = replace(records(), id=Ref(K.OBSERVATION, "m"))
    early = replace(records(), id=Ref(K.OBSERVATION, "z"), schema=2)
    late = replace(early, at=replace(early.at, seq=early.at.seq + 1, mono_ns=20))
    left, right = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    left.accept(late)
    parent = right.accept(middle)
    right.append(early, {parent.cid})
    merged, other = (right, left) if reverse else (left, right)
    merged.merge(other)
    merged.verify()
    # 選ばれない late の位置へ early を繰り上げてはいけない。
    assert tuple(merged.record(entry.cid) for entry in merged.between((), merged.heads())) == (
        late, middle, early)
    snapshot = merged.snapshot(merged.heads())
    assert snapshot.records == (middle, early)
    assert snapshot.find(Observed) == Found(records=(middle, early))
