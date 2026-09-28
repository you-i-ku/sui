"""種類つきの ID と発行元。"""

import json as _json
import re as _re
import uuid as _uuid
from dataclasses import dataclass as _dataclass
from enum import StrEnum as _StrEnum
from typing import Protocol as _Protocol


def _check_type(name: str, value: object, expected: type) -> None:
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise TypeError(f"{name}: expected {expected.__name__}, got {value!r}")


def _check_text(name: str, value: str, pattern: str | None = None) -> None:
    _check_type(name, value, str)
    if not value or (pattern is not None and _re.fullmatch(pattern, value) is None):
        raise ValueError(f"{name}: expected {pattern or 'nonempty str'}, got {value!r}")


def _check_int(name: str, value: int, minimum: int | None = None) -> None:
    _check_type(name, value, int)
    if minimum is not None and value < minimum:
        raise ValueError(f"{name}: expected >= {minimum}, got {value!r}")


class RefKind(_StrEnum):
    INDIVIDUAL = "individual"
    RUN = "run"
    DECISION = "decision"
    JOB = "job"
    ATTEMPT = "attempt"
    OBSERVATION = "observation"
    PREDICTION = "prediction"
    INTERPRETATION = "interpretation"
    PREFERENCE = "preference"
    INTENTION = "intention"


@_dataclass(frozen=True, slots=True)
class Ref:
    kind: RefKind
    value: str

    def __post_init__(self) -> None:
        _check_type("kind", self.kind, RefKind)
        _check_text("value", self.value, r"[0-9a-z_-]{1,64}")

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.value}"


class WrongKind(ValueError):
    """参照の種類が期待と違う。"""


def expect(ref: Ref, *kinds: RefKind) -> Ref:
    """期待した種類の参照をそのまま返し、違えば WrongKind。"""
    _check_type("ref", ref, Ref)
    if not kinds:
        raise TypeError("kinds: expected at least one RefKind, got ()")
    for kind in kinds:
        _check_type("kinds item", kind, RefKind)
    if ref.kind not in kinds:
        raise WrongKind(f"ref.kind: expected one of {[k.value for k in kinds]!r}, got {ref.kind.value!r}")
    return ref


class IdSource(_Protocol):
    def new(self, kind: RefKind) -> Ref: ...


class RandomIds:
    """UUID4 による本番用の ID 発行元。"""

    def new(self, kind: RefKind) -> Ref:
        """指定された種類の ID を発行する。"""
        _check_type("kind", kind, RefKind)
        return Ref(kind, _uuid.uuid4().hex)


class SequentialIds:
    """種類をまたいで連番を振る、単一スレッド用の発行元。"""

    def __init__(self, prefix: str = "t") -> None:
        _check_type("prefix", prefix, str)
        self._prefix = prefix
        self._n = 0

    def new(self, kind: RefKind) -> Ref:
        """指定された種類で、次の連番の ID を発行する。"""
        ref = Ref(kind, f"{self._prefix}{self._n + 1:06d}")
        self._n += 1
        return ref


SUI_ID_NAMESPACE = _uuid.UUID("5eb0830a-84f8-5141-9713-78574b8bb75a")


def derive(kind: RefKind, *parts: str) -> Ref:
    """種類と文字列の列から、再送・再生で同じになる ID を作る。"""
    _check_type("kind", kind, RefKind)
    if not parts:
        raise ValueError("parts: expected at least one str, got ()")
    for part in parts:
        _check_type("parts item", part, str)
    material = _json.dumps([kind.value, *parts], ensure_ascii=False, separators=(",", ":"))
    return Ref(kind, _uuid.uuid5(SUI_ID_NAMESPACE, material).hex)
