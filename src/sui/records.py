"""記録の本文・作成者・参照範囲と再送の判定。"""

import json as _json
from dataclasses import dataclass as _dataclass, fields as _fields
from enum import StrEnum as _StrEnum

from .clock import Instant as _Instant
from .contracts import ContractRef as _ContractRef
from .ids import Ref as _Ref, RefKind as _RefKind, expect as _expect
from .ids import _check_int, _check_text, _check_type


@_dataclass(frozen=True, slots=True)
class Payload:
    media_type: str
    data: bytes

    def __post_init__(self) -> None:
        _check_text("media_type", self.media_type)
        if type(self.data) is not bytes:
            raise TypeError(f"data: expected bytes, got {self.data!r}")

    @classmethod
    def text(cls, s: str) -> "Payload":
        """文字列を UTF-8 の中身にする。"""
        _check_type("s", s, str)
        return cls("text/plain; charset=utf-8", s.encode("utf-8"))

    @classmethod
    def json(cls, value: object) -> "Payload":
        """鍵を整列した UTF-8 JSON にし、NaN と無限大を拒む。"""
        return cls("application/json", _json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"))

    def as_text(self) -> str:
        """テキストの種類を確認して読み出す。"""
        if self.media_type != "text/plain; charset=utf-8":
            raise ValueError(f"media_type: expected 'text/plain; charset=utf-8', got {self.media_type!r}")
        return self.data.decode("utf-8")

    def as_json(self) -> object:
        """JSON の種類を確認して読み出す。"""
        if self.media_type != "application/json":
            raise ValueError(f"media_type: expected 'application/json', got {self.media_type!r}")
        return _json.loads(self.data)


class Role(_StrEnum):
    MEMBRANE = "membrane"
    MODEL = "model"
    INTERPRETER = "interpreter"


class Category(_StrEnum):
    FACT = "fact"
    PREDICTION = "prediction"
    INTERPRETATION = "interpretation"
    PREFERENCE = "preference"
    INTENTION = "intention"


class IntentionStatus(_StrEnum):
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"
    EXECUTED = "executed"


class Admission(_StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"


@_dataclass(frozen=True, slots=True, kw_only=True)
class StateRef:
    lineage: str
    revision: int

    def __post_init__(self) -> None:
        _check_text("lineage", self.lineage, r"[0-9a-z_-]{1,64}")
        _check_int("revision", self.revision, 0)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Producer:
    component: str
    code_version: str
    state: StateRef | None = None

    def __post_init__(self) -> None:
        _check_text("component", self.component)
        _check_text("code_version", self.code_version)
        if self.state is not None:
            _check_type("state", self.state, StateRef)


def _check_content(content: Payload, contract: _ContractRef) -> None:
    _check_type("content", content, Payload)
    _check_type("contract", contract, _ContractRef)


def _check_refs(name: str, refs: tuple[_Ref, ...]) -> None:
    _check_type(name, refs, tuple)
    for ref in refs:
        _check_type(f"{name} item", ref, _Ref)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Observed:
    route: str
    content: Payload
    contract: _ContractRef
    caused_by: _Ref | None = None
    source_id: str | None = None
    source_time_ns: int | None = None

    def __post_init__(self) -> None:
        _check_text("route", self.route)
        _check_content(self.content, self.contract)
        if self.caused_by is not None:
            _expect(self.caused_by, _RefKind.ATTEMPT)
        if self.source_id is not None:
            _check_text("source_id", self.source_id)
        if self.source_time_ns is not None:
            _check_int("source_time_ns", self.source_time_ns)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Decided:
    inputs: tuple[_Ref, ...]
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _check_refs("inputs", self.inputs)
        for ref in self.inputs:
            if ref.kind not in BODY_KIND.values():
                raise ValueError(f"inputs item: expected a record ref, got {ref}")
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class JobOpened:
    decision: _Ref
    step: int
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _expect(self.decision, _RefKind.DECISION)
        _check_int("step", self.step, 0)
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class AttemptStarted:
    job: _Ref
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _expect(self.job, _RefKind.JOB)
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Prediction:
    target: str
    about: tuple[_Ref, ...]
    basis: tuple[_Ref, ...]
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _check_text("target", self.target)
        _check_refs("about", self.about)
        _check_refs("basis", self.basis)
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Interpretation:
    about: tuple[_Ref, ...]
    basis: tuple[_Ref, ...]
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _check_refs("about", self.about)
        _check_refs("basis", self.basis)
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Preference:
    basis: tuple[_Ref, ...]
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _check_refs("basis", self.basis)
        _check_content(self.content, self.contract)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Intention:
    target: _Ref
    operation: str
    status: IntentionStatus
    decided_in: _Ref
    supersedes: _Ref | None = None
    via: _Ref | None = None
    content: Payload
    contract: _ContractRef

    def __post_init__(self) -> None:
        _check_type("target", self.target, _Ref)
        _check_text("operation", self.operation)
        _check_type("status", self.status, IntentionStatus)
        _expect(self.decided_in, _RefKind.DECISION)
        if self.supersedes is not None:
            _expect(self.supersedes, _RefKind.INTENTION)
        if self.via is not None:
            _expect(self.via, _RefKind.ATTEMPT)
        _check_content(self.content, self.contract)
        if self.status in (IntentionStatus.WITHDRAWN, IntentionStatus.EXECUTED) and self.supersedes is None:
            raise ValueError(f"supersedes for {self.status}: expected intention ref, got None")
        if self.status is IntentionStatus.EXECUTED:
            if self.via is None:
                raise ValueError("via for executed: expected attempt ref, got None")
        elif self.via is not None:
            raise ValueError(f"via for {self.status}: expected None, got {self.via}")


Body = Observed | Decided | JobOpened | AttemptStarted | Prediction | Interpretation | Preference | Intention

BODY_KIND: dict[type, _RefKind] = {
    Observed: _RefKind.OBSERVATION,
    Decided: _RefKind.DECISION,
    JobOpened: _RefKind.JOB,
    AttemptStarted: _RefKind.ATTEMPT,
    Prediction: _RefKind.PREDICTION,
    Interpretation: _RefKind.INTERPRETATION,
    Preference: _RefKind.PREFERENCE,
    Intention: _RefKind.INTENTION,
}

CATEGORY: dict[type, Category] = {
    Observed: Category.FACT,
    Decided: Category.FACT,
    JobOpened: Category.FACT,
    AttemptStarted: Category.FACT,
    Prediction: Category.PREDICTION,
    Interpretation: Category.INTERPRETATION,
    Preference: Category.PREFERENCE,
    Intention: Category.INTENTION,
}

UNDECIDED = "undecided: 関所 B・S10"
WRITERS: dict[type, frozenset[Role] | str] = {
    Observed: frozenset({Role.MEMBRANE}),
    AttemptStarted: frozenset({Role.MEMBRANE}),
    Decided: frozenset({Role.MODEL}),
    JobOpened: frozenset({Role.MODEL}),
    Intention: frozenset({Role.MODEL}),
    Prediction: frozenset({Role.MODEL}),
    Interpretation: frozenset({Role.MODEL, Role.INTERPRETER}),
    Preference: UNDECIDED,
}

SCHEMA_VERSION = 2


class WriterNotAllowed(ValueError):
    """その係はこの本文を書けない。"""


class SchemaMismatch(ValueError):
    """記録のスキーマの版が違う。"""


class Undecided(Exception):
    """書き手が未決の関所・スライスを示す。"""

    gate: str

    def __init__(self, *, gate: str) -> None:
        self.gate = gate
        super().__init__(f"writer: expected a decided writer, got {gate}")


class IdConflict(ValueError):
    """同じ ID で異なる欄を定義順に示す。"""

    id: _Ref
    fields: tuple[str, ...]

    def __init__(self, id: _Ref, fields: tuple[str, ...]) -> None:
        self.id = id
        self.fields = fields
        super().__init__(f"{id}: expected identical record, got differences in {fields!r}")


@_dataclass(frozen=True, slots=True, kw_only=True)
class Record:
    id: _Ref
    at: _Instant
    writer: Role
    producer: Producer
    body: Body
    schema: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _check_type("id", self.id, _Ref)
        _check_type("at", self.at, _Instant)
        _check_type("writer", self.writer, Role)
        _check_type("producer", self.producer, Producer)
        if type(self.body) not in BODY_KIND:
            raise TypeError(f"body: expected a body type, got {self.body!r}")
        _check_int("schema", self.schema)
        if self.schema != SCHEMA_VERSION:
            raise SchemaMismatch(f"schema: expected {SCHEMA_VERSION}, got {self.schema}")
        _expect(self.id, BODY_KIND[type(self.body)])
        writers = WRITERS[type(self.body)]
        if isinstance(writers, str):
            raise Undecided(gate=writers)
        if self.writer not in writers:
            raise WriterNotAllowed(f"{self.writer} cannot write {type(self.body).__name__}")

    @property
    def category(self) -> Category:
        return CATEGORY[type(self.body)]

    def refs(self) -> tuple[_Ref, ...]:
        """本文の参照を欄順に並べ、重複は最初の一つだけ残す。"""
        refs = []
        for field in _fields(self.body):
            value = getattr(self.body, field.name)
            if isinstance(value, _Ref):
                refs.append(value)
            elif isinstance(value, tuple):
                refs.extend(ref for ref in value if isinstance(ref, _Ref))
        return tuple(dict.fromkeys(refs))


def admit(existing: Record | None, incoming: Record) -> Admission:
    """再送・再生を判定し、衝突なら異なる欄を示す。記録は変えない。"""
    _check_type("incoming", incoming, Record)
    if existing is None:
        return Admission.NEW
    _check_type("existing", existing, Record)
    if existing.id != incoming.id:
        raise ValueError(f"incoming.id: expected {existing.id}, got {incoming.id}")
    differences = []
    for field in _fields(Record):
        if isinstance(existing.body, Observed) and field.name != "body":
            continue
        old, new = getattr(existing, field.name), getattr(incoming, field.name)
        if old == new:
            continue
        if field.name == "body" and type(old) is type(new):
            differences.extend(
                f"body.{part.name}" for part in _fields(old)
                if getattr(old, part.name) != getattr(new, part.name)
            )
        else:
            differences.append(field.name)
    if differences:
        raise IdConflict(existing.id, tuple(differences))
    return Admission.DUPLICATE
