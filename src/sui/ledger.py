"""塩つきの本文の封と、出来事の因果の網。S2a は単一スレッド。"""

import base64 as _base64
import hashlib as _hashlib
import heapq as _heapq
import json as _json
import re as _re
import secrets as _secrets
from collections.abc import Iterable as _Iterable
from dataclasses import dataclass as _dataclass, fields as _fields
from enum import StrEnum as _StrEnum
from typing import Protocol as _Protocol

from .clock import ClockError as _ClockError, Instant as _Instant, precedes as _precedes
from .contracts import Contract as _Contract, ContractRef as _ContractRef
from .ids import Ref as _Ref, RefKind as _RefKind
from .records import (
    BODY_KIND as _BODY_KIND, CATEGORY as _CATEGORY, Category as _Category,
    IntentionStatus as _IntentionStatus, Payload as _Payload, Producer as _Producer,
    Record as _Record, Role as _Role, SchemaMismatch as _SchemaMismatch,
    StateRef as _StateRef, Undecided as _Undecided, admit as _admit,
)
from .snapshot import Snapshot as _Snapshot


def _canon(value: object) -> bytes:
    return _json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return "sha256:" + _hashlib.sha256(data).hexdigest()


def _check_cid(value: str) -> None:
    if not isinstance(value, str):
        raise TypeError("cid: expected str")
    if _re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"cid: expected sha256 and 64 lowercase hex digits, got {value!r}")


class SaltSource(_Protocol):
    def new(self) -> bytes: ...


class RandomSalts:
    def new(self) -> bytes:
        return _secrets.token_bytes(16)


class SequentialSalts:
    def __init__(self) -> None:
        self._n = 0

    def new(self) -> bytes:
        salt = (self._n + 1).to_bytes(16, "big")
        self._n += 1
        return salt


def seal(content: _Payload, salt: bytes) -> str:
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError("salt: expected 16 bytes")
    return _digest(_canon({
        "scheme": "sui.seal.1", "salt": salt.hex(), "media_type": content.media_type,
        "data": _base64.b64encode(content.data).decode("ascii"),
    }))


class Contents(_Protocol):
    def put(self, seal: str, salt: bytes, content: _Payload) -> None: ...
    def get(self, seal: str) -> tuple[bytes, _Payload]: ...


class MemoryContents:
    def __init__(self) -> None:
        self._items: dict[str, tuple[bytes, _Payload]] = {}

    def put(self, seal: str, salt: bytes, content: _Payload) -> None:
        item = salt, content
        if seal in self._items and self._items[seal] != item:
            raise ValueError(f"{seal}: different contents already stored")
        self._items[seal] = item

    def get(self, seal: str) -> tuple[bytes, _Payload]:
        return self._items[seal]


class MissingParent(ValueError):
    """親が台帳に無い。"""


class DerivedParent(ValueError):
    """派生物は親・出来事の先端になれない。"""


class CorruptEntry(ValueError):
    """点・骨組み・封・本文が一致しない。"""


class UnknownEntry(KeyError):
    """指定された点が台帳に無い。"""


class Relation(_StrEnum):
    SAME = "same"
    BEFORE = "before"
    AFTER = "after"
    CONCURRENT = "concurrent"


@_dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    cid: str
    header: bytes
    id: _Ref
    body_type: type
    at: _Instant
    writer: _Role
    parents: frozenset[str]
    seal: str

    @property
    def category(self) -> _Category:
        return _CATEGORY[self.body_type]

    @property
    def is_event(self) -> bool:
        return self.category in (_Category.FACT, _Category.INTENTION)


def _encode(value):
    if isinstance(value, _Ref):
        return str(value)
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, _ContractRef):
        return {"name": value.name, "version": value.version}
    if isinstance(value, _StrEnum):
        return value.value
    return value


def encode_header(record: _Record, seal: str, parents: frozenset[str]) -> bytes:
    state = record.producer.state
    return _canon({
        "schema": record.schema, "id": str(record.id),
        "at": {field.name: _encode(getattr(record.at, field.name))
               for field in _fields(record.at)},
        "writer": record.writer.value,
        "producer": {"component": record.producer.component,
                     "code_version": record.producer.code_version,
                     "state": None if state is None else
                     {"lineage": state.lineage, "revision": state.revision}},
        "body": {"type": type(record.body).__name__, **{
            field.name: _encode(getattr(record.body, field.name))
            for field in _fields(record.body) if field.name != "content"}},
        "seal": seal, "parents": sorted(parents),
    })


def _ref(value: str) -> _Ref:
    kind, name = value.split(":", 1)
    return _Ref(_RefKind(kind), name)


def _decode_v2(data: dict, content: _Payload) -> _Record:
    at = dict(data["at"])
    at["run"] = _ref(at["run"])
    producer = dict(data["producer"])
    if producer["state"] is not None:
        producer["state"] = _StateRef(**producer["state"])
    body = dict(data["body"])
    body_type = {kind.__name__: kind for kind in _BODY_KIND}[body.pop("type")]
    for key, value in body.items():
        if key == "contract":
            body[key] = _ContractRef(**value)
        elif key in ("inputs", "about", "basis"):
            if not isinstance(value, list):
                raise ValueError(f"{key}: expected list")
            body[key] = tuple(_ref(ref) for ref in value)
        elif key in ("caused_by", "decision", "job", "decided_in", "supersedes", "via"):
            body[key] = None if value is None else _ref(value)
        elif key == "target" and body_type.__name__ == "Intention":
            body[key] = _ref(value)
        elif key == "status":
            body[key] = _IntentionStatus(value)
    return _Record(id=_ref(data["id"]), at=_Instant(**at), writer=_Role(data["writer"]),
                   producer=_Producer(**producer), body=body_type(content=content, **body),
                   schema=data["schema"])


_DECODERS = {2: _decode_v2}


def decode_record(header: bytes, content: _Payload) -> _Record:
    try:
        if not isinstance(header, bytes):
            raise TypeError("header: expected bytes")
        data = _json.loads(header)
        if not isinstance(data, dict) or type(data.get("schema")) is not int:
            raise ValueError("schema: expected int")
        if data["schema"] not in _DECODERS:
            raise _SchemaMismatch(f"schema: unsupported version {data['schema']}")
        _check_cid(data["seal"])
        if not isinstance(data["parents"], list):
            raise ValueError("parents: expected list")
        for parent in data["parents"]:
            _check_cid(parent)
        record = _DECODERS[data["schema"]](data, content)
        if encode_header(record, data["seal"], frozenset(data["parents"])) != header:
            raise ValueError("header: expected complete canonical encoding")
        return record
    except _SchemaMismatch:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, _Undecided) as exc:
        raise CorruptEntry(f"invalid header: {exc}") from exc


class Ledger:
    def __init__(self, *, salts: SaltSource, contents: Contents | None = None) -> None:
        self._salts = salts
        self.contents = MemoryContents() if contents is None else contents
        self._entries: dict[str, Entry] = {}
        self._records: dict[str, tuple[Entry, _Record]] = {}

    def append(self, record: _Record, parents: _Iterable[str]) -> Entry:
        if not isinstance(record, _Record):
            raise TypeError("record: expected Record")
        parents = frozenset(parents)
        for parent in parents:
            _check_cid(parent)
        try:
            encode_header(record, "sha256:" + "0" * 64, parents)
        except UnicodeEncodeError as exc:
            raise ValueError("record: header cannot be encoded as UTF-8") from exc
        existing = self.entries_of(record.id)
        for entry in existing:
            _admit(self.record(entry.cid), record)
        if existing:
            return existing[0]
        for parent in sorted(parents):
            if parent not in self._entries:
                raise MissingParent(parent)
        for parent in sorted(parents):
            if not self.entry(parent).is_event:
                raise DerivedParent(parent)
        for parent in sorted(parents):
            at = self.entry(parent).at
            if at.run == record.at.run and not _precedes(at, record.at):
                raise _ClockError(f"{parent}: parent must precede {record.id} in the same run")
        salt = self._salts.new()
        sealed = seal(record.body.content, salt)
        header = encode_header(record, sealed, parents)
        entry = Entry(cid=_digest(header), header=header, id=record.id,
                      body_type=type(record.body), at=record.at, writer=record.writer,
                      parents=parents, seal=sealed)
        self.contents.put(sealed, salt, record.body.content)
        self._entries[entry.cid] = entry
        self._records[entry.cid] = entry, record
        return entry

    def accept(self, record: _Record) -> Entry:
        if not isinstance(record, _Record):
            raise TypeError("record: expected Record")
        if record.writer is not _Role.MEMBRANE:
            raise ValueError("accept: only membrane records can be accepted")
        return self.append(record, self.heads())

    def heads(self) -> frozenset[str]:
        events = [entry for entry in self._entries.values() if entry.is_event]
        return frozenset(entry.cid for entry in events) - frozenset(
            parent for entry in events for parent in entry.parents)

    def entry(self, cid: str) -> Entry:
        try:
            return self._entries[cid]
        except KeyError:
            raise UnknownEntry(cid) from None

    def entries_of(self, ref: _Ref) -> tuple[Entry, ...]:
        return tuple(sorted((entry for entry in self._entries.values() if entry.id == ref),
                            key=lambda entry: entry.cid))

    def record(self, cid: str) -> _Record:
        """毎回本文を取得し、点の同一性と本文の一致を確認して復元結果を再利用する。"""
        entry = self.entry(cid)
        _, content = self.contents.get(entry.seal)
        cached = self._records.get(cid)
        if (cached is not None and cached[0] is entry
                and cached[1].body.content == content):
            return cached[1]
        record = decode_record(entry.header, content)
        self._records[cid] = entry, record
        return record

    def _ordered(self, cids: _Iterable[str]) -> tuple[Entry, ...]:
        selected = frozenset(cids)
        degrees = {}
        children = {cid: [] for cid in selected}
        for cid in selected:
            parents = self.entry(cid).parents & selected
            degrees[cid] = len(parents)
            for parent in parents:
                children[parent].append(cid)
        ready = [cid for cid, degree in degrees.items() if degree == 0]
        _heapq.heapify(ready)
        result = []
        while ready:
            cid = _heapq.heappop(ready)
            result.append(self.entry(cid))
            for child in children[cid]:
                degrees[child] -= 1
                if degrees[child] == 0:
                    _heapq.heappush(ready, child)
        if len(result) != len(selected):
            raise CorruptEntry(f"cycle in entries: {sorted(selected - {e.cid for e in result})}")
        return tuple(result)

    def entries(self) -> tuple[Entry, ...]:
        return self._ordered(self._entries)

    def ancestors(self, frontier: _Iterable[str]) -> frozenset[str]:
        pending, seen = list(frontier), set()
        while pending:
            cid = pending.pop()
            if cid not in seen:
                pending.extend(self.entry(cid).parents)
                seen.add(cid)
        return frozenset(seen)

    def between(self, old: _Iterable[str], new: _Iterable[str]) -> tuple[Entry, ...]:
        return self._ordered(self.ancestors(new) - self.ancestors(old))

    def maximal(self, cids: _Iterable[str]) -> frozenset[str]:
        selected = frozenset(cids)
        ancestors = set()
        for cid in selected:
            ancestors.update(self.ancestors(self.entry(cid).parents))
        return selected - ancestors

    def relation(self, a: str, b: str) -> Relation:
        self.entry(a)
        self.entry(b)
        if a == b:
            return Relation.SAME
        if a in self.ancestors((b,)):
            return Relation.BEFORE
        if b in self.ancestors((a,)):
            return Relation.AFTER
        return Relation.CONCURRENT

    def snapshot(self, frontier: _Iterable[str]) -> _Snapshot:
        frontier = frozenset(frontier)
        for cid in frontier:
            if not self.entry(cid).is_event:
                raise DerivedParent(cid)
        records, seen = [], set()
        for entry in self.between((), frontier):
            if entry.is_event and entry.id not in seen:
                records.append(self.record(entry.cid))
                seen.add(entry.id)
        return _Snapshot(records=tuple(records), frontier=frontier)

    def merge(self, other: "Ledger", *, events_only: bool = False) -> None:
        # 衝突の全検査を、本文の put を含むすべての書き込みより前に行う。
        known: dict[_Ref, list[_Record]] = {}
        for entry in self._entries.values():
            known.setdefault(entry.id, []).append(self.record(entry.cid))
        pending = []
        for entry in other.entries():
            if (events_only and not entry.is_event) or entry.cid in self._entries:
                continue
            record = other.record(entry.cid)
            for existing in known.get(entry.id, ()):
                _admit(existing, record)
            known.setdefault(entry.id, []).append(record)
            salt, content = other.contents.get(entry.seal)
            pending.append((entry, salt, content, record))
        for entry, salt, content, record in pending:
            self.contents.put(entry.seal, salt, content)
            self._entries[entry.cid] = entry
            self._records[entry.cid] = entry, record

    def verify(self) -> None:
        for cid, entry in self._entries.items():
            try:
                if cid != entry.cid or _digest(entry.header) != cid:
                    raise ValueError("header digest differs")
                salt, content = self.contents.get(entry.seal)
                if seal(content, salt) != entry.seal:
                    raise ValueError("content seal differs")
                record = decode_record(entry.header, content)
                data = _json.loads(entry.header)
                expected = (record.id, type(record.body), record.at, record.writer,
                            frozenset(data["parents"]), data["seal"])
                actual = (entry.id, entry.body_type, entry.at, entry.writer,
                          entry.parents, entry.seal)
                if actual != expected:
                    raise ValueError("entry fields differ from header")
                for parent in entry.parents:
                    if parent not in self._entries:
                        raise ValueError(f"missing parent {parent}")
            except Exception as exc:
                raise CorruptEntry(f"{cid}: {exc}") from exc


RECORD_SCHEMA = _Contract(
    ref=_ContractRef("sui.record", "2"),
    meaning='台帳の点。cid = 骨組みの正準 JSON (UTF-8、キー昇順、空白なし) の SHA-256。親 = 書き手がその時に見ていた出来事の先端 (膜は台帳の先端、モデルは主体が取り込み済みの先端、派生物は取り込んだ先端)。本文は塩つきの封 sui.seal.1 で分け、点は封だけを持つ。出来事 (事実・意思) だけが親になれ、派生物 (予測・解釈) は葉。順番の基本は因果の順。同時の点の見え方は cid の昇順',
    unit='cid・封は sha256: + 小文字の16進64桁、時刻は Instant のナノ秒',
    state_owner='台帳 (Ledger)。点は変わらない',
    persistence='S2a はメモリ。永続化は S2b',
    failure='親が無い・派生物を親にした・同じ run の時刻が逆・同じ ID で違う中身は、台帳を変えずに拒む',
    cancel='なし (手放すは S8)',
    redelivery='同じ ID・同じ中身は新しい点を作らず既存の cid が最小の点を返す。合わせた台帳では同じ事実が複数の点になりうるので、数える時は ID の集合で',
)
