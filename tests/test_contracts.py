from dataclasses import replace

import pytest

from sui.contracts import Contract, ContractBook, ContractMismatch, ContractRef as CR, UnknownContract, require


@pytest.fixture
def contract():
    return Contract(ref=CR("sui.test.embed", "1"), meaning="分布", unit="nat", state_owner="gm",
                    persistence="undecided: S2", failure="拒否", cancel="none", redelivery="同じ宣言")


def test_k1_exact_match():
    assert require(CR("sui.test.embed", "1"), CR("sui.test.embed", "1")) is None


def test_k2_version_mismatch_reason():
    with pytest.raises(ContractMismatch) as error:
        require(CR("sui.test.embed", "1"), CR("sui.test.embed", "2"))
    assert error.value.reasons == ("version of 'sui.test.embed': expected one of ['1'], got '2'",)
    assert str(error.value) == "; ".join(error.value.reasons)


def test_k3_name_mismatch_reason():
    with pytest.raises(ContractMismatch) as error:
        require(CR("sui.a", "1"), CR("sui.b", "1"))
    assert error.value.reasons == ("name: expected one of ['sui.a'], got 'sui.b'",)


def test_k4_multiple_accepted_pairs():
    accepted = [CR("sui.x", "3"), CR("sui.x", "1")]
    for version in ("1", "3"):
        assert require(accepted, CR("sui.x", version)) is None
    assert require(iter(accepted), CR("sui.x", "3")) is None
    with pytest.raises(ContractMismatch) as error:
        require(accepted, CR("sui.x", "2"))
    assert error.value.reasons == ("version of 'sui.x': expected one of ['1', '3'], got '2'",)
    with pytest.raises(ContractMismatch) as error:
        require([CR("sui.a", "1"), CR("sui.b", "2")], CR("sui.a", "2"))
    assert error.value.reasons == ("version of 'sui.a': expected one of ['1'], got '2'",)


@pytest.mark.parametrize("version", ["1.1", "01"])
def test_k5_no_inferred_compatibility(version):
    with pytest.raises(ContractMismatch):
        require(CR("sui.x", "1"), CR("sui.x", version))


def test_k6_book_preserves_original(contract):
    book = ContractBook()
    assert book.register(contract) is None
    assert book.register(replace(contract)) is None
    with pytest.raises(ContractMismatch) as error:
        book.register(replace(contract, unit="bit"))
    assert error.value.reasons == ("unit: registered 'nat', got 'bit'",)
    assert book.get(contract.ref) is contract
    with pytest.raises(UnknownContract):
        book.get(CR("sui.missing", "1"))


def test_k6_multiple_changes_follow_declaration_order(contract):
    book = ContractBook()
    book.register(contract)
    with pytest.raises(ContractMismatch) as error:
        book.register(replace(contract, redelivery="拒否", unit="bit", meaning="別の分布"))
    assert error.value.reasons == (
        "meaning: registered '分布', got '別の分布'",
        "unit: registered 'nat', got 'bit'",
        "redelivery: registered '同じ宣言', got '拒否'",
    )
    assert str(error.value) == "; ".join(error.value.reasons)
    assert book.get(contract.ref) is contract


@pytest.mark.parametrize("name, version", [("Sui.X", "1"), ("sui.x", ""), ("sui.x", " 1"), ("sui.x", "1 ")])
def test_k7_invalid_contract_ref(name, version):
    with pytest.raises(ValueError):
        CR(name, version)


@pytest.mark.parametrize("field", ["meaning", "unit", "state_owner", "persistence", "failure", "cancel", "redelivery"])
def test_k7_declaration_requires_nonempty_strings(contract, field):
    with pytest.raises(ValueError):
        replace(contract, **{field: ""})
    with pytest.raises(TypeError):
        replace(contract, **{field: 1})


def test_k7_ref_types(contract):
    with pytest.raises(TypeError):
        replace(contract, ref="sui.test.embed:1")
    with pytest.raises(TypeError):
        CR("sui.x", 1)
