"""部品の約束の宣言と完全一致による照合。"""

from collections.abc import Iterable as _Iterable
from dataclasses import dataclass as _dataclass, fields as _fields

from .ids import _check_text, _check_type


@_dataclass(frozen=True, slots=True)
class ContractRef:
    name: str
    version: str

    def __post_init__(self) -> None:
        _check_text("name", self.name, r"[a-z0-9_.-]{1,128}")
        _check_text("version", self.version)
        if self.version != self.version.strip():
            raise ValueError(f"version: expected no surrounding whitespace, got {self.version!r}")


@_dataclass(frozen=True, slots=True, kw_only=True)
class Contract:
    ref: ContractRef
    meaning: str
    unit: str
    state_owner: str
    persistence: str
    failure: str
    cancel: str
    redelivery: str

    def __post_init__(self) -> None:
        _check_type("ref", self.ref, ContractRef)
        for field in _fields(self)[1:]:
            _check_text(field.name, getattr(self, field.name))


class ContractMismatch(ValueError):
    """約束が一致しない理由を定義順に持つ。"""

    reasons: tuple[str, ...]

    def __init__(self, reasons: tuple[str, ...]) -> None:
        _check_type("reasons", reasons, tuple)
        if not reasons:
            raise ValueError("reasons: expected at least one str, got ()")
        for reason in reasons:
            _check_type("reasons item", reason, str)
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class UnknownContract(KeyError):
    """参照された約束が未登録。"""


def require(accepted: ContractRef | _Iterable[ContractRef], actual: ContractRef) -> None:
    """名前と版の組が完全一致しなければ、理由つきで拒む。"""
    _check_type("actual", actual, ContractRef)
    choices = (accepted,) if isinstance(accepted, ContractRef) else tuple(accepted)
    for choice in choices:
        _check_type("accepted item", choice, ContractRef)
    if actual in choices:
        return
    names = {choice.name for choice in choices}
    if actual.name not in names:
        reason = f"name: expected one of {sorted(names)!r}, got {actual.name!r}"
    else:
        versions = {choice.version for choice in choices if choice.name == actual.name}
        reason = f"version of {actual.name!r}: expected one of {sorted(versions)!r}, got {actual.version!r}"
    raise ContractMismatch((reason,))


class ContractBook:
    """同じ参照への異なる宣言を上書きしない登録簿。"""

    def __init__(self) -> None:
        self._contracts: dict[ContractRef, Contract] = {}

    def register(self, contract: Contract) -> None:
        """新しい宣言を登録し、再登録の違いを欄ごとに報告する。"""
        _check_type("contract", contract, Contract)
        old = self._contracts.get(contract.ref)
        if old is None:
            self._contracts[contract.ref] = contract
            return
        reasons = tuple(
            f"{field.name}: registered {getattr(old, field.name)!r}, got {getattr(contract, field.name)!r}"
            for field in _fields(Contract)
            if getattr(old, field.name) != getattr(contract, field.name)
        )
        if reasons:
            raise ContractMismatch(reasons)

    def get(self, ref: ContractRef) -> Contract:
        """登録された宣言を返し、無ければ UnknownContract。"""
        _check_type("ref", ref, ContractRef)
        try:
            return self._contracts[ref]
        except KeyError:
            raise UnknownContract(f"contract: expected registered ref, got {ref!r}") from None
