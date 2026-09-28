"""見えている範囲に応じて、存在・不在・不明を区別する。"""

from collections.abc import Callable as _Callable
from dataclasses import dataclass as _dataclass

from .clock import precedes as _precedes
from .ids import Ref as _Ref, _check_type
from .records import BODY_KIND as _BODY_KIND, Coverage as _Coverage, Record as _Record


def _check_records(records: tuple[_Record, ...]) -> None:
    _check_type("records", records, tuple)
    for record in records:
        _check_type("records item", record, _Record)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Found:
    records: tuple[_Record, ...]
    complete: bool

    def __post_init__(self) -> None:
        _check_records(self.records)
        _check_type("complete", self.complete, bool)
        if not self.records:
            raise ValueError("records: expected at least one Record, got ()")


@_dataclass(frozen=True, slots=True, kw_only=True)
class Absent:
    """全部見えている範囲の中には無い。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class Unknown:
    reason: str

    def __post_init__(self) -> None:
        _check_type("reason", self.reason, str)


Lookup = Found | Absent | Unknown


@_dataclass(frozen=True, slots=True, kw_only=True)
class Snapshot:
    records: tuple[_Record, ...]
    coverage: _Coverage

    def __post_init__(self) -> None:
        _check_records(self.records)
        _check_type("coverage", self.coverage, _Coverage)
        seen = set()
        for record in self.records:
            if record.id in seen:
                raise ValueError(f"records.id: expected unique IDs, got duplicate {record.id}")
            seen.add(record.id)
            if _precedes(self.coverage.as_of, record.at):
                raise ValueError(f"record.at: expected <= {self.coverage.as_of!r}, got {record.at!r}")

    def find(self, body_type: type, where: _Callable[[_Record], bool] = lambda r: True) -> Lookup:
        """種類と条件で順序を保って探し、範囲に応じて不在と不明を分ける。"""
        if not isinstance(body_type, type) or body_type not in _BODY_KIND:
            raise ValueError(f"body_type: expected a body type, got {body_type!r}")
        records = tuple(r for r in self.records if type(r.body) is body_type and where(r))
        complete = body_type in self.coverage.complete
        if records:
            return Found(records=records, complete=complete)
        return self._missing(body_type)

    def resolve(self, ref: _Ref) -> Lookup:
        """記録の ID を引き、範囲の外については不明と答える。"""
        _check_type("ref", ref, _Ref)
        body_type = next((t for t, kind in _BODY_KIND.items() if kind is ref.kind), None)
        if body_type is None:
            raise ValueError(f"ref: expected a record ref, got {ref}")
        for record in self.records:
            if record.id == ref:
                return Found(records=(record,), complete=True)
        return self._missing(body_type)

    def unresolved(self) -> frozenset[_Ref]:
        """参照された記録のうち、この範囲に入っていない ID を返す。"""
        present = {record.id for record in self.records}
        return frozenset(
            ref for record in self.records for ref in record.refs()
            if ref.kind in _BODY_KIND.values() and ref not in present
        )

    def _missing(self, body_type: type) -> Absent | Unknown:
        if body_type in self.coverage.complete:
            return Absent()
        return Unknown(reason=(
            f"{body_type.__name__} is not fully covered as of "
            f"{self.coverage.ledger}@{self.coverage.through}"
        ))
