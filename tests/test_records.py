from dataclasses import FrozenInstanceError, fields, replace

import pytest

from sui import records as r
from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind as K, SequentialIds, WrongKind, derive
from sui.snapshot import Found, Snapshot


TEXT = r.Payload.text("この実験を終わらせる")
C_TEXT = ContractRef("sui.test.text", "1")
C_EMPTY = ContractRef("sui.test.empty", "1")

# 仕様書の期待値を手で書く。実装の表から生成しない。
KINDS = {
    r.Observed: K.OBSERVATION, r.Decided: K.DECISION, r.JobOpened: K.JOB,
    r.AttemptStarted: K.ATTEMPT, r.Prediction: K.PREDICTION,
    r.Interpretation: K.INTERPRETATION, r.Preference: K.PREFERENCE, r.Intention: K.INTENTION,
}
WRITERS = {
    r.Observed: frozenset({r.Role.MEMBRANE}), r.AttemptStarted: frozenset({r.Role.MEMBRANE}),
    r.Decided: frozenset({r.Role.MODEL}), r.JobOpened: frozenset({r.Role.MODEL}),
    r.Intention: frozenset({r.Role.MODEL}), r.Prediction: frozenset({r.Role.MODEL}),
    r.Interpretation: frozenset({r.Role.MODEL, r.Role.INTERPRETER}), r.Preference: None,
}


@pytest.fixture
def clk():
    return FakeClock(run=Ref(K.RUN, "r1"))


@pytest.fixture
def make_body(clk):
    coverage = r.Coverage(as_of=clk.now(), ledger="test", through=0, complete=frozenset())
    defaults = {
        r.Observed: dict(route="channel:letter"),
        r.Decided: dict(basis=coverage, inputs=()),
        r.JobOpened: dict(decision=Ref(K.DECISION, "d1"), step=0),
        r.AttemptStarted: dict(job=Ref(K.JOB, "j1"), content=r.Payload.json({}), contract=C_EMPTY),
        r.Prediction: dict(target="next_letter_text", about=(), basis=()),
        r.Interpretation: dict(about=(), basis=()),
        r.Preference: dict(basis=()),
        r.Intention: dict(target=Ref(K.RUN, "exp1"), operation="end",
                          status=r.IntentionStatus.CONFIRMED, decided_in=Ref(K.DECISION, "d1")),
    }

    def make(body_type, **changes):
        values = dict(content=TEXT, contract=C_TEXT)
        values.update(defaults[body_type])
        values.update(changes)
        return body_type(**values)

    return make


@pytest.fixture
def make_record(clk, make_body):
    ids = SequentialIds()
    producers = {
        r.Role.MEMBRANE: r.Producer(component="receiver", code_version="0.1"),
        r.Role.MODEL: r.Producer(component="gm", code_version="0.1",
                               state=r.StateRef(lineage="l1", revision=0)),
        r.Role.INTERPRETER: r.Producer(component="llm", code_version="0.1"),
    }

    def make(body_type, *, body=None, **changes):
        if body is None:
            body = make_body(body_type)
        role = r.Role.MEMBRANE if body_type in (r.Observed, r.AttemptStarted) else r.Role.MODEL
        values = dict(id=ids.new(KINDS[body_type]), at=clk.now(), writer=role,
                      producer=producers[role], body=body)
        values.update(changes)
        return r.Record(**values)

    return make


def test_r1_same_text_keeps_distinct_meanings(clk, make_body, make_record):
    obs = make_record(r.Observed, id=derive(K.OBSERVATION, "channel:letter", "m-1"),
                      body=make_body(r.Observed, source_id="m-1"))
    pred = make_record(r.Prediction, body=make_body(r.Prediction, basis=(obs.id,)))
    interp = make_record(r.Interpretation, writer=r.Role.INTERPRETER,
                         producer=r.Producer(component="llm", code_version="0.1"),
                         body=make_body(r.Interpretation, about=(obs.id,)))
    basis = r.Coverage(as_of=clk.now(), ledger="test", through=3,
                       complete=frozenset({r.Observed, r.Prediction, r.Interpretation}))
    dec = make_record(r.Decided, body=make_body(r.Decided, basis=basis, inputs=(obs.id, pred.id, interp.id)))
    will = make_record(r.Intention, body=make_body(r.Intention, decided_in=dec.id))
    records = (obs, pred, interp, dec, will)
    snapshot = Snapshot(records=records, coverage=r.Coverage(
        as_of=clk.now(), ledger="test", through=5, complete=frozenset(KINDS)))
    assert all(record.body.content.data == TEXT.data for record in records)
    assert [record.category for record in records] == [
        r.Category.FACT, r.Category.PREDICTION, r.Category.INTERPRETATION, r.Category.FACT, r.Category.INTENTION,
    ]
    assert snapshot.find(r.Intention, lambda rec: rec.body.status is r.IntentionStatus.CONFIRMED
                         and rec.body.target == Ref(K.RUN, "exp1")) == Found(records=(will,), complete=True)
    assert snapshot.find(r.Observed) == Found(records=(obs,), complete=True)
    assert snapshot.find(r.Prediction) == Found(records=(pred,), complete=True)


@pytest.mark.parametrize("body_type, allowed", list(WRITERS.items()))
@pytest.mark.parametrize("writer", [r.Role.MEMBRANE, r.Role.MODEL, r.Role.INTERPRETER])
def test_r2_writer_matrix(make_record, body_type, allowed, writer):
    if allowed is None:
        with pytest.raises(r.Undecided) as error:
            make_record(body_type, writer=writer)
        assert error.value.gate == "undecided: 関所 B・S10"
    elif writer in allowed:
        assert make_record(body_type, writer=writer).writer is writer
    else:
        with pytest.raises(r.WriterNotAllowed) as error:
            make_record(body_type, writer=writer)
        assert str(error.value) == f"{writer} cannot write {body_type.__name__}"


@pytest.mark.parametrize("kind", [K.OBSERVATION, K.INTERPRETATION])
def test_r3_text_or_interpretation_cannot_decide_intention(make_body, kind):
    with pytest.raises(WrongKind):
        make_body(r.Intention, decided_in=Ref(kind, "x"))


@pytest.mark.parametrize("writer", [r.Role.INTERPRETER, r.Role.MEMBRANE])
def test_r3_only_model_writes_intention(make_record, writer):
    with pytest.raises(r.WriterNotAllowed):
        make_record(r.Intention, writer=writer)


@pytest.mark.parametrize("body_type, changes", [
    (r.Observed, {"caused_by": Ref(K.JOB, "j1")}),
    (r.JobOpened, {"decision": Ref(K.JOB, "j1")}),
    (r.AttemptStarted, {"job": Ref(K.ATTEMPT, "a1")}),
    (r.Intention, {"supersedes": Ref(K.DECISION, "d1")}),
    (r.Intention, {"status": r.IntentionStatus.EXECUTED, "supersedes": Ref(K.INTENTION, "i1"),
                   "via": Ref(K.JOB, "j1")}),
])
def test_r4_reference_kinds(make_body, body_type, changes):
    with pytest.raises(WrongKind):
        make_body(body_type, **changes)


def test_r4_observed_can_reference_attempt(make_body):
    attempt = Ref(K.ATTEMPT, "a1")
    assert make_body(r.Observed, caused_by=attempt).caused_by == attempt


@pytest.mark.parametrize("changes", [
    {"status": r.IntentionStatus.WITHDRAWN},
    {"status": r.IntentionStatus.EXECUTED, "supersedes": Ref(K.INTENTION, "i1")},
    {"status": r.IntentionStatus.EXECUTED, "via": Ref(K.ATTEMPT, "a1")},
    {"status": r.IntentionStatus.CONFIRMED, "via": Ref(K.ATTEMPT, "a1")},
    {"status": r.IntentionStatus.WITHDRAWN, "supersedes": Ref(K.INTENTION, "i1"),
     "via": Ref(K.ATTEMPT, "a1")},
])
def test_r5_invalid_intention_status_shape(make_body, changes):
    with pytest.raises(ValueError):
        make_body(r.Intention, **changes)


@pytest.mark.parametrize("status, supersedes, via", [
    (r.IntentionStatus.CONFIRMED, None, None),
    (r.IntentionStatus.CONFIRMED, Ref(K.INTENTION, "i1"), None),
    (r.IntentionStatus.WITHDRAWN, Ref(K.INTENTION, "i1"), None),
    (r.IntentionStatus.EXECUTED, Ref(K.INTENTION, "i1"), Ref(K.ATTEMPT, "a1")),
])
def test_r5_valid_intention_status_shape(make_body, status, supersedes, via):
    body = make_body(r.Intention, status=status, supersedes=supersedes, via=via)
    assert (body.status, body.supersedes, body.via) == (status, supersedes, via)


def test_r6_record_id_matches_body(make_record):
    with pytest.raises(WrongKind):
        make_record(r.Observed, id=Ref(K.DECISION, "d1"))


def test_r7_record_schema(make_record):
    with pytest.raises(r.SchemaMismatch) as error:
        make_record(r.Observed, schema=2)
    assert str(error.value) == "schema: expected 1, got 2"


def test_r8_payload_encoding_and_media_type():
    payload = r.Payload.json({"b": 1, "a": [1, 2]})
    assert payload == r.Payload.json({"a": [1, 2], "b": 1})
    assert payload.data == b'{"a":[1,2],"b":1}'
    assert payload.as_json() == {"a": [1, 2], "b": 1}
    assert r.Payload.json({"名": "ゆう"}).data == '{"名":"ゆう"}'.encode("utf-8")
    assert r.Payload.text("ゆう").as_text() == "ゆう"
    assert r.Payload.text("ゆう").data == "ゆう".encode("utf-8")
    with pytest.raises(ValueError):
        r.Payload.text("x").as_json()
    with pytest.raises(ValueError):
        payload.as_text()
    assert r.Payload("application/octet-stream", b"\x00\xff").data == b"\x00\xff"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_r8_json_rejects_nonfinite_numbers(value):
    with pytest.raises(ValueError):
        r.Payload.json(value)


def test_r9_record_is_immutable(make_record, make_body, clk):
    rec = make_record(r.Observed)
    with pytest.raises(FrozenInstanceError):
        rec.body = make_body(r.Observed)
    with pytest.raises(FrozenInstanceError):
        rec.at = clk.now()


def test_r10_redelivery_ignores_receipt_metadata(make_record, clk):
    obs1 = make_record(r.Observed)
    obs2 = replace(obs1, at=clk.now(), producer=r.Producer(component="receiver", code_version="0.2"))
    original_at, original_producer = obs1.at, obs1.producer
    assert r.admit(None, obs1) is r.Admission.NEW
    assert r.admit(obs1, obs2) is r.Admission.DUPLICATE
    assert obs1.at is original_at and obs1.producer is original_producer


def test_r10_separately_constructed_identical_prediction_is_duplicate(make_record):
    pred1 = make_record(r.Prediction)
    pred2 = replace(pred1, body=replace(pred1.body), producer=replace(pred1.producer), at=replace(pred1.at))
    assert pred1 is not pred2 and pred1.body is not pred2.body
    assert r.admit(pred1, pred2) is r.Admission.DUPLICATE


@pytest.mark.parametrize("changes, expected", [
    ({"content": r.Payload.text("この実験を続ける")}, ("body.content",)),
    ({"contract": ContractRef("sui.test.text", "2")}, ("body.contract",)),
    ({"caused_by": Ref(K.ATTEMPT, "a1")}, ("body.caused_by",)),
    ({"content": r.Payload.text("この実験を続ける"), "caused_by": Ref(K.ATTEMPT, "a1")},
     ("body.content", "body.caused_by")),
    ({"route": "channel:other"}, ("body.route",)),
    ({"source_id": "m-2"}, ("body.source_id",)),
    ({"source_time_ns": 1}, ("body.source_time_ns",)),
])
def test_r11_observation_conflict_fields(make_record, changes, expected):
    old = make_record(r.Observed)
    incoming = replace(old, body=replace(old.body, **changes))
    with pytest.raises(r.IdConflict) as error:
        r.admit(old, incoming)
    assert error.value.id == old.id
    assert error.value.fields == expected


@pytest.mark.parametrize("changed, expected", [
    (("at",), ("at",)), (("producer",), ("producer",)),
    (("at", "producer"), ("at", "producer")),
])
def test_r11_internal_record_conflict_fields(make_record, clk, changed, expected):
    old = make_record(r.Prediction)
    values = {"at": clk.now(), "producer": replace(old.producer, code_version="0.2")}
    incoming = replace(old, **{key: values[key] for key in changed})
    with pytest.raises(r.IdConflict) as error:
        r.admit(old, incoming)
    assert error.value.id == old.id
    assert error.value.fields == expected


def test_r11_intention_status_conflict(make_body, make_record):
    body = make_body(r.Intention, status=r.IntentionStatus.CONFIRMED,
                     supersedes=Ref(K.INTENTION, "i1"))
    old = make_record(r.Intention, body=body)
    incoming = replace(old, body=replace(old.body, status=r.IntentionStatus.WITHDRAWN))
    with pytest.raises(r.IdConflict) as error:
        r.admit(old, incoming)
    assert error.value.id == old.id
    assert error.value.fields == ("body.status",)


def test_r11_different_ids_are_not_redelivery(make_record):
    with pytest.raises(ValueError) as error:
        r.admit(make_record(r.Observed), make_record(r.Observed))
    assert type(error.value) is ValueError


def test_r12_schema_fields_are_fixed():
    # 事実の札は経路・行動 (と S2 で保存の場所) だけ。
    # 『自分か外か』『重み』『活性』の欄を足さない (約束 1・素案 §5.1・§8.4)。
    # 欄を変える時は仕様書を先に直す。これは欄の変更の検知で、
    # route や content に固定の分類を埋め込む誤りは落とせない。
    assert {field.name for field in fields(r.Observed)} == {
        "route", "content", "contract", "caused_by", "source_id", "source_time_ns",
    }
    assert {field.name for field in fields(r.Record)} == {"id", "at", "writer", "producer", "body", "schema"}


def test_r13_job_has_distinct_attempts(make_body, make_record):
    job = Ref(K.JOB, "j1")
    first = make_record(r.AttemptStarted, body=make_body(r.AttemptStarted, job=job))
    second = make_record(r.AttemptStarted, body=make_body(r.AttemptStarted, job=job))
    assert first.id != second.id
    assert first.body.job == second.body.job == job


@pytest.mark.parametrize("field", ["component", "code_version"])
def test_r14_producer_nonempty_fields(field):
    producer = r.Producer(component="receiver", code_version="0.1")
    with pytest.raises(ValueError):
        replace(producer, **{field: ""})


@pytest.mark.parametrize("lineage, revision, error", [
    ("l1", -1, ValueError), ("l1", True, TypeError), ("L 1", 0, ValueError),
])
def test_r14_state_reference_validation(lineage, revision, error):
    with pytest.raises(error):
        r.StateRef(lineage=lineage, revision=revision)


def test_r15_category_and_kind_tables():
    assert r.BODY_KIND == KINDS
    assert r.CATEGORY == {
        r.Observed: r.Category.FACT, r.Decided: r.Category.FACT,
        r.JobOpened: r.Category.FACT, r.AttemptStarted: r.Category.FACT,
        r.Prediction: r.Category.PREDICTION, r.Interpretation: r.Category.INTERPRETATION,
        r.Preference: r.Category.PREFERENCE, r.Intention: r.Category.INTENTION,
    }


def test_r16_decision_basis_cannot_be_in_future(clk, make_body, make_record):
    as_of = clk.now()
    basis = r.Coverage(as_of=as_of, ledger="test", through=0, complete=frozenset())
    clk.advance(10)
    at = clk.now()
    body = make_body(r.Decided, basis=basis)
    assert make_record(r.Decided, body=body, at=at).body is body
    assert make_record(r.Decided, body=body, at=as_of).body is body
    future = replace(basis, as_of=at)
    with pytest.raises(ValueError):
        make_record(r.Decided, body=replace(body, basis=future), at=as_of)


def test_r16_actual_inputs_and_ledger_position(make_body, make_record):
    o1, o2 = Ref(K.OBSERVATION, "o1"), Ref(K.OBSERVATION, "o2")
    body1 = make_body(r.Decided, inputs=(o1,))
    body2 = replace(body1, inputs=(o2,))
    assert body1 != body2
    assert make_record(r.Decided, body=body1).refs() == (o1,)
    assert make_record(r.Decided, body=body2).refs() == (o2,)
    assert body1.basis != replace(body1.basis, through=body1.basis.through + 1)
    for kind in (K.RUN, K.INDIVIDUAL):
        with pytest.raises(ValueError):
            replace(body1, inputs=(Ref(kind, "r1"),))


def test_r17_refs_follow_field_order_and_remove_duplicates(make_body, make_record):
    target, decision = Ref(K.RUN, "exp1"), Ref(K.DECISION, "d1")
    previous, via = Ref(K.INTENTION, "i1"), Ref(K.ATTEMPT, "a1")
    body = make_body(r.Intention, target=target, decided_in=decision, supersedes=previous,
                     via=via, status=r.IntentionStatus.EXECUTED)
    assert make_record(r.Intention, body=body).refs() == (target, decision, previous, via)
    job, obs = Ref(K.JOB, "j1"), Ref(K.OBSERVATION, "o1")
    pred = make_body(r.Prediction, about=(job,), basis=(obs, obs))
    assert make_record(r.Prediction, body=pred).refs() == (job, obs)
    assert make_record(r.Observed, body=make_body(r.Observed, caused_by=via)).refs() == (via,)
    assert make_record(r.JobOpened).refs() == (decision,)
    assert make_record(r.AttemptStarted).refs() == (job,)
    assert make_record(r.Observed).refs() == ()


@pytest.mark.parametrize("changes", [
    {"writer": "model"}, {"schema": True}, {"body": "text"}, {"id": "prediction:x"},
    {"at": 1}, {"producer": "gm"},
])
def test_r18_record_field_types(make_record, changes):
    # MODEL の有効な本文を使い、文字列だけを理由に TypeError になることを確かめる。
    with pytest.raises(TypeError):
        make_record(r.Prediction, **changes)


@pytest.mark.parametrize("data", [bytearray(b"a"), memoryview(b"a"), "a"])
def test_r18_payload_requires_exact_bytes(data):
    with pytest.raises(TypeError):
        r.Payload("x", data)


@pytest.mark.parametrize("body_type, changes", [
    (r.Intention, {"status": "confirmed"}),
    (r.Prediction, {"about": [Ref(K.JOB, "j1")]}),
    (r.Prediction, {"about": ("x",)}),
    (r.Prediction, {"basis": [Ref(K.OBSERVATION, "o1")]}),
    (r.JobOpened, {"step": True}), (r.Observed, {"source_time_ns": True}),
    (r.Observed, {"content": b"x"}), (r.Observed, {"contract": "sui.test.text:1"}),
    (r.Observed, {"source_id": 1}), (r.Observed, {"caused_by": "attempt:a1"}),
    (r.Decided, {"basis": ()}), (r.Decided, {"inputs": [Ref(K.OBSERVATION, "o1")]}),
    (r.Interpretation, {"basis": (1,)}), (r.Preference, {"basis": []}),
    (r.Intention, {"target": "run:r1"}),
])
def test_r18_body_field_types(make_body, body_type, changes):
    with pytest.raises(TypeError):
        make_body(body_type, **changes)


def test_r18_record_validation_priority(make_record):
    with pytest.raises(TypeError):
        make_record(r.Preference, writer="model", schema=2, id=Ref(K.JOB, "j1"))
    with pytest.raises(r.SchemaMismatch):
        make_record(r.Preference, schema=2, id=Ref(K.JOB, "j1"))
    with pytest.raises(WrongKind):
        make_record(r.Preference, id=Ref(K.JOB, "j1"))
    with pytest.raises(r.Undecided):
        make_record(r.Preference, writer=r.Role.INTERPRETER)


def test_r19_state_lineage_distinguishes_producers(make_record):
    first = r.Producer(component="gm", code_version="0.1", state=r.StateRef(lineage="l1", revision=0))
    second = replace(first, state=r.StateRef(lineage="l2", revision=0))
    assert first != second
    old = make_record(r.Prediction, producer=first)
    with pytest.raises(r.IdConflict) as error:
        r.admit(old, replace(old, producer=second))
    assert error.value.fields == ("producer",)
