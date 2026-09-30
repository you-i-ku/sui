"""見えている範囲に応じて、存在・不在・不明を区別する。"""

from collections.abc import Callable as _Callable
from dataclasses import dataclass as _dataclass

from .clock import Instant as _Instant
from .ids import Ref as _Ref, RefKind as _RefKind, expect as _expect, _check_type
from .records import (BODY_KIND as _BODY_KIND, CATEGORY as _CATEGORY,
                      Category as _Category, Record as _Record, Preference as _Preference)


def _check_records(records: tuple[_Record, ...]) -> None:
    _check_type("records", records, tuple)
    for record in records:
        _check_type("records item", record, _Record)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Found:
    records: tuple[_Record, ...]

    def __post_init__(self) -> None:
        _check_records(self.records)
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
class UnreadPreference:
    """本文を補わず、好みの名札・時刻・読めない理由を残す (C2b)。"""

    id: _Ref
    at: _Instant
    reason: str

    def __post_init__(self) -> None:
        _expect(self.id, _RefKind.PREFERENCE)
        _check_type("at", self.at, _Instant)
        _check_type("reason", self.reason, str)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Snapshot:
    records: tuple[_Record, ...]
    frontier: frozenset[str]
    unread_preferences: tuple[UnreadPreference, ...] = ()

    def __post_init__(self) -> None:
        _check_records(self.records)
        _check_type("frontier", self.frontier, frozenset)
        _check_type("unread_preferences", self.unread_preferences, tuple)
        for point in self.unread_preferences:
            _check_type("unread_preferences item", point, UnreadPreference)
        seen = set()
        for record in self.records:
            if record.id in seen:
                raise ValueError(f"records.id: expected unique IDs, got duplicate {record.id}")
            seen.add(record.id)

    def find(self, body_type: type, where: _Callable[[_Record], bool] = lambda r: True) -> Lookup:
        """種類と条件で順序を保って探し、範囲に応じて不在と不明を分ける。"""
        if not isinstance(body_type, type) or body_type not in _BODY_KIND:
            raise ValueError(f"body_type: expected a body type, got {body_type!r}")
        if self._derived(body_type):
            return self._unknown()
        known = {record.id for record in self.records}
        unread = tuple(point for point in self.unread_preferences if point.id not in known)
        if body_type is _Preference and unread:
            return Unknown(reason="preference content unreadable: " + "; ".join(
                f"{point.id}: {point.reason}" for point in unread))
        records = tuple(r for r in self.records if type(r.body) is body_type and where(r))
        if records:
            return Found(records=records)
        return Absent()

    def resolve(self, ref: _Ref) -> Lookup:
        """記録の ID を引き、範囲の外については不明と答える。"""
        _check_type("ref", ref, _Ref)
        body_type = next((t for t, kind in _BODY_KIND.items() if kind is ref.kind), None)
        if body_type is None:
            raise ValueError(f"ref: expected a record ref, got {ref}")
        if self._derived(body_type):
            return self._unknown()
        for record in self.records:
            if record.id == ref:
                return Found(records=(record,))
        for point in self.unread_preferences:
            if point.id == ref:
                return Unknown(reason=f"{point.id}: {point.reason}")
        return Absent()

    def unresolved(self) -> frozenset[_Ref]:
        """参照された記録のうち、この範囲に入っていない ID を返す。"""
        present = {record.id for record in self.records} | {
            point.id for point in self.unread_preferences}
        return frozenset(
            ref for record in self.records for ref in record.refs()
            if ref.kind in _BODY_KIND.values() and ref not in present
        )

    @staticmethod
    def _derived(body_type: type) -> bool:
        return _CATEGORY[body_type] not in (
            _Category.FACT, _Category.INTENTION, _Category.PREFERENCE)

    @staticmethod
    def _unknown() -> Unknown:
        return Unknown(reason="derived records are not part of a snapshot; rebuild them from the model and the facts")
