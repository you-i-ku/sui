from dataclasses import replace

import pytest

from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.records import Coverage, Intention, IntentionStatus, Observed, Payload, Prediction, Producer, Record, Role
from sui.snapshot import Absent, Found, Snapshot, Unknown


@pytest.fixture
def clk():
    return FakeClock(run=Ref(K.RUN, "r1"))


@pytest.fixture
def make_record(clk):
    ids = SequentialIds()
    contract = ContractRef("sui.test.text", "1")
    content = Payload.text("この実験を終わらせる")

    def make(body_type=Observed, **changes):
        if body_type is Observed:
            values = dict(route="channel:letter", content=content, contract=contract)
            kind, writer = K.OBSERVATION, Role.MEMBRANE
        elif body_type is Prediction:
            values = dict(target="next_letter_text", about=(), basis=(), content=content, contract=contract)
            kind, writer = K.PREDICTION, Role.MODEL
        else:
            assert body_type is Intention
            values = dict(target=Ref(K.RUN, "exp1"), operation="end", status=IntentionStatus.CONFIRMED,
                          decided_in=Ref(K.DECISION, "d1"), content=content, contract=contract)
            kind, writer = K.INTENTION, Role.MODEL
        values.update(changes)
        return Record(id=ids.new(kind), at=clk.now(), writer=writer,
                      producer=Producer(component="test", code_version="0.1"), body=body_type(**values))

    return make


@pytest.fixture
def make_snapshot(clk):
    def make(records=(), complete=frozenset(), **coverage_changes):
        values = dict(as_of=clk.now(), ledger="test", through=len(records), complete=complete)
        values.update(coverage_changes)
        return Snapshot(records=records, coverage=Coverage(**values))

    return make


def test_s1_partial_snapshot_does_not_claim_absence(make_record, make_snapshot):
    obs = make_record()
    snapshot = make_snapshot((obs,), frozenset({Observed}))
    unknown = snapshot.find(Intention)
    assert isinstance(unknown, Unknown)
    assert "Intention" in unknown.reason
    assert snapshot.find(Observed, lambda rec: rec.body.route == "channel:other") == Absent()


def test_s2_complete_kind_can_be_absent(make_snapshot):
    assert make_snapshot(complete=frozenset({Intention})).find(Intention) == Absent()


@pytest.mark.parametrize("complete, expected", [(frozenset(), False), (frozenset({Observed}), True)])
def test_s3_found_completeness_depends_on_coverage(make_record, make_snapshot, complete, expected):
    obs = make_record()
    snapshot = make_snapshot((obs,), complete)
    assert snapshot.find(Observed) == Found(records=(obs,), complete=expected)


def test_s4_resolve_exact_id_and_missing_kinds(make_record, make_snapshot):
    obs = make_record()
    snapshot = make_snapshot((obs,), frozenset({Observed}))
    assert snapshot.resolve(obs.id) == Found(records=(obs,), complete=True)
    assert snapshot.resolve(Ref(K.OBSERVATION, "missing")) == Absent()
    assert isinstance(snapshot.resolve(Ref(K.INTENTION, "missing")), Unknown)
    partial = make_snapshot((obs,))
    assert partial.resolve(obs.id) == Found(records=(obs,), complete=True)
    for kind in (K.RUN, K.INDIVIDUAL):
        with pytest.raises(ValueError):
            snapshot.resolve(Ref(kind, "r1"))


def test_s5_unresolved_excludes_runs_individuals_and_present_records(make_record, make_snapshot):
    obs_ref, job_ref, dec_ref = Ref(K.OBSERVATION, "o1"), Ref(K.JOB, "j1"), Ref(K.DECISION, "d1")
    pred = make_record(Prediction, basis=(obs_ref,), about=(job_ref, Ref(K.INDIVIDUAL, "self")))
    will = make_record(Intention, decided_in=dec_ref)
    snapshot = make_snapshot((pred, will))
    assert snapshot.unresolved() == frozenset({obs_ref, job_ref, dec_ref})
    obs = replace(make_record(), id=obs_ref)
    assert make_snapshot((obs, pred, will)).unresolved() == frozenset({job_ref, dec_ref})


def test_s6_duplicate_ids_are_rejected(make_record, make_snapshot):
    obs = make_record()
    with pytest.raises(ValueError):
        make_snapshot((obs, replace(obs)))


def test_s6_future_record_is_rejected(clk, make_record, make_snapshot):
    as_of = clk.now()
    obs = make_record()
    with pytest.raises(ValueError):
        make_snapshot((obs,), as_of=as_of)
    assert make_snapshot((obs,), as_of=obs.at).records == (obs,)


def test_s6_snapshot_and_lookup_types(make_record, make_snapshot):
    obs = make_record()
    with pytest.raises(TypeError):
        make_snapshot([obs])
    with pytest.raises(TypeError):
        make_snapshot(("text",))
    with pytest.raises(TypeError):
        Snapshot(records=(), coverage=None)
    with pytest.raises(ValueError):
        Found(records=(), complete=True)
    with pytest.raises(TypeError):
        Found(records=[obs], complete=True)
    with pytest.raises(TypeError):
        Found(records=(obs,), complete=1)
    with pytest.raises(TypeError):
        Unknown(reason=1)
    with pytest.raises(TypeError):
        Unknown("reason")
    with pytest.raises(TypeError):
        Found((obs,), True)


@pytest.mark.parametrize("changes, error", [
    ({"complete": frozenset({str})}, ValueError), ({"complete": {Observed}}, TypeError),
    ({"through": -1}, ValueError), ({"through": True}, TypeError),
    ({"ledger": ""}, ValueError), ({"ledger": "Book"}, ValueError),
    ({"ledger": "x" * 129}, ValueError), ({"as_of": 1}, TypeError),
])
def test_s7_coverage_validation(clk, changes, error):
    values = dict(as_of=clk.now(), ledger="test", through=0, complete=frozenset())
    values.update(changes)
    with pytest.raises(error):
        Coverage(**values)


def test_s8_find_preserves_snapshot_order_and_applies_filter(make_record, make_snapshot):
    first, second, third = make_record(), make_record(route="channel:other"), make_record()
    pred = make_record(Prediction)
    snapshot = make_snapshot((third, pred, first, second), frozenset({Observed}))
    assert snapshot.find(Observed) == Found(records=(third, first, second), complete=True)
    assert snapshot.find(Observed, lambda rec: rec.body.route == "channel:letter") == Found(
        records=(third, first), complete=True)
    with pytest.raises(ValueError):
        snapshot.find(str)


def test_s9_unknown_reason_includes_ledger_position(make_snapshot):
    snapshot = make_snapshot(ledger="book", through=3)
    expected = Unknown(reason="Intention is not fully covered as of book@3")
    assert snapshot.find(Intention) == expected
    assert snapshot.resolve(Ref(K.INTENTION, "missing")) == expected
