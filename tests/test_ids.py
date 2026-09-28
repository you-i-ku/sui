import re
import uuid

import pytest

from sui.ids import Ref, RefKind as K, RandomIds, SequentialIds, WrongKind, derive, expect


def test_i1_kind_is_part_of_identity():
    decision, job = Ref(K.DECISION, "a"), Ref(K.JOB, "a")
    assert decision != job
    assert len({decision, job}) == 2
    assert decision == Ref(K.DECISION, "a")
    assert str(job) == "job:a"


def test_i2_expect_preserves_identity_and_reports_kinds():
    ref = Ref(K.JOB, "a")
    assert expect(ref, K.JOB) is ref
    assert expect(ref, K.ATTEMPT, K.JOB) is ref
    with pytest.raises(WrongKind) as error:
        expect(Ref(K.DECISION, "a"), K.JOB, K.ATTEMPT)
    assert all(word in str(error.value) for word in ("decision", "job", "attempt"))
    with pytest.raises(TypeError):
        expect(ref)
    with pytest.raises(TypeError):
        expect("job:a", K.JOB)
    with pytest.raises(TypeError):
        expect(ref, "job")


@pytest.mark.parametrize("value", ["", "A", "a" * 65, "a b", "a\n"])
def test_i3_invalid_value(value):
    with pytest.raises(ValueError):
        Ref(K.JOB, value)


def test_i3_types_and_valid_boundary():
    assert Ref(K.JOB, "a" * 64).value == "a" * 64
    assert Ref(K.JOB, "a_0-z").value == "a_0-z"
    with pytest.raises(TypeError):
        Ref("job", "a")
    with pytest.raises(TypeError):
        Ref(K.JOB, 1)


@pytest.mark.parametrize("source_id, expected", [
    ("m-1", "c129d0d984645a29ba917f2b76a20e78"),
    ("ゆう", "2877572c6fd65fe88373c71ce9247220"),
])
def test_i4_derive_fixed_values(source_id, expected):
    first = derive(K.OBSERVATION, "channel:letter", source_id)
    assert first.value == expected
    assert first.kind is K.OBSERVATION
    assert derive(K.OBSERVATION, "channel:letter", source_id) == first


def test_i5_derive_delimiters_and_kind():
    left = derive(K.OBSERVATION, "a|b", "c")
    right = derive(K.OBSERVATION, "a", "b|c")
    job = derive(K.JOB, "channel:letter", "m-1")
    assert left.value == "f644a9741dcf5ee1a4b9393ae45d6461"
    assert right.value == "0bf087d7b53855bba3ad860c18dcf801"
    assert left.value != right.value
    assert job.value == "b07de834da5d53ef92ea1464cf875d79"
    assert job.value != derive(K.OBSERVATION, "channel:letter", "m-1").value


def test_i6_derive_arguments():
    with pytest.raises(ValueError):
        derive(K.JOB)
    with pytest.raises(TypeError):
        derive(K.JOB, 1)
    with pytest.raises(TypeError):
        derive("job", "a")


def test_i7_sequential_and_random_ids():
    ids = SequentialIds()
    kinds = (K.JOB, K.ATTEMPT, K.JOB)
    refs = [ids.new(kind) for kind in kinds]
    assert [ref.value for ref in refs] == ["t000001", "t000002", "t000003"]
    assert tuple(ref.kind for ref in refs) == kinds
    assert SequentialIds("x_").new(K.JOB).value == "x_000001"
    random = RandomIds()
    refs = [random.new(K.JOB) for _ in range(200)]
    assert len(set(refs)) == 200
    assert all(ref.kind is K.JOB and re.fullmatch(r"[0-9a-f]{32}", ref.value) for ref in refs)
    assert all(uuid.UUID(hex=ref.value).version == 4 for ref in refs)
