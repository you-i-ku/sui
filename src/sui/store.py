"""単一の書き手のための、点・本文・モデルの置き場。"""

import hashlib as _hashlib
import os as _os
import sqlite3 as _sqlite3
from contextlib import contextmanager as _contextmanager
from pathlib import Path as _Path
from typing import Protocol as _Protocol

from .contracts import Contract as _Contract, ContractRef as _ContractRef
from .model import (GenerativeModel as _GenerativeModel, model_json as _model_json,
                    model_from_json as _model_from_json)
from .records import Payload as _Payload


class StorageFull(OSError):
    """失敗した書き込みは確定していない。"""


class ReadOnlyStore(PermissionError):
    """読むだけの置き場への書き込み。"""


class StoreFormatMismatch(ValueError):
    """ファイルの形式または役割が違う。"""


class ScrubIncomplete(OSError):
    """削除は確定したが、WAL の掃除が失敗した。"""


class CorruptModel(ValueError):
    """モデルの参照と保存された中身が一致しない。"""


class EntryStore(_Protocol):
    writable: bool
    def add(self, cid: str, header: bytes) -> None: ...
    def load(self) -> tuple[tuple[str, bytes], ...]: ...


class Models(_Protocol):
    writable: bool
    def put(self, model: _GenerativeModel) -> str: ...
    def get(self, ref: str) -> _GenerativeModel: ...
    def refs(self) -> frozenset[str]: ...


def _digest(data: bytes) -> str:
    return "sha256:" + _hashlib.sha256(data).hexdigest()


def _read_model(ref: str, body: bytes) -> _GenerativeModel:
    if _digest(body) != ref:
        raise CorruptModel(f"{ref}: model digest differs")
    return _model_from_json(body)


class MemoryEntries:
    writable = True

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def add(self, cid: str, header: bytes) -> None:
        if cid in self._items and self._items[cid] != header:
            raise ValueError(f"{cid}: different header already stored")
        self._items[cid] = header

    def load(self) -> tuple[tuple[str, bytes], ...]:
        return tuple(sorted(self._items.items()))


class MemoryModels:
    writable = True

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def put(self, model: _GenerativeModel) -> str:
        body = _model_json(model)
        ref = _digest(body)
        if ref in self._items and self._items[ref] != body:
            raise ValueError(f"{ref}: different model already stored")
        self._items[ref] = body
        return ref

    def get(self, ref: str) -> _GenerativeModel:
        return _read_model(ref, self._items[ref])

    def refs(self) -> frozenset[str]:
        return frozenset(self._items)


@_contextmanager
def _transaction(connection):
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.execute("COMMIT")
    except BaseException as original:
        if connection.in_transaction:
            try:
                connection.execute("ROLLBACK")
            except BaseException as rollback:
                # 元の失敗を保ち、掃除の失敗も追跡できるようにする。
                rollback.__context__ = None
                original.__context__ = rollback
        if (isinstance(original, _sqlite3.OperationalError)
                and getattr(original, "sqlite_errorname", None) == "SQLITE_FULL"):
            raise StorageFull(str(original)) from original
        raise


class _Table:
    def __init__(self, store, role):
        self._store, self._role = store, role

    @property
    def writable(self):
        return not self._store.readonly

    @property
    def _connection(self):
        return self._store._connections[self._role]

    def _check_write(self):
        if not self.writable:
            raise ReadOnlyStore("store is read-only")

    def _put(self, table, key_column, key, columns, values):
        self._check_write()
        connection = self._connection
        with _transaction(connection):
            row = connection.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {key_column} = ?",
                (key,),
            ).fetchone()
            if row is not None:
                if row != values:
                    raise ValueError(f"{key}: different {table} already stored")
            else:
                placeholders = ', '.join('?' for _ in range(1 + len(values)))
                connection.execute(f"INSERT INTO {table} VALUES ({placeholders})", (key, *values))


class _SqliteEntries(_Table):
    def add(self, cid: str, header: bytes) -> None:
        self._put("entries", "cid", cid, ("header",), (header,))

    def load(self) -> tuple[tuple[str, bytes], ...]:
        return tuple(self._connection.execute("SELECT cid, header FROM entries ORDER BY cid").fetchall())


class _SqliteContents(_Table):
    def put(self, seal: str, salt: bytes, content: _Payload) -> None:
        self._check_write()
        self._put("contents", "seal", seal, ("salt", "media_type", "data"),
                  (salt, content.media_type, content.data))

    def get(self, seal: str) -> tuple[bytes, _Payload]:
        row = self._connection.execute(
            "SELECT salt, media_type, data FROM contents WHERE seal = ?", (seal,)).fetchone()
        if row is None:
            raise KeyError(seal)
        return row[0], _Payload(media_type=row[1], data=row[2])

    def seals(self) -> frozenset[str]:
        return frozenset(row[0] for row in self._connection.execute("SELECT seal FROM contents").fetchall())

    def discard(self, seal: str) -> bool:
        self._check_write()
        connection = self._connection
        with _transaction(connection):
            connection.execute("DELETE FROM contents WHERE seal = ?", (seal,))
        try:
            timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            try:
                connection.execute("PRAGMA busy_timeout=200")
                busy = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
            finally:
                connection.execute(f"PRAGMA busy_timeout={timeout}")
        except Exception as exc:
            raise ScrubIncomplete(f"{seal}: deleted, but checkpoint failed") from exc
        return busy == 0


class _SqliteModels(_Table):
    def put(self, model: _GenerativeModel) -> str:
        self._check_write()
        body = _model_json(model)
        ref = _digest(body)
        self._put("models", "ref", ref, ("body",), (body,))
        return ref

    def get(self, ref: str) -> _GenerativeModel:
        row = self._connection.execute("SELECT body FROM models WHERE ref = ?", (ref,)).fetchone()
        if row is None:
            raise KeyError(ref)
        return _read_model(ref, row[0])

    def refs(self) -> frozenset[str]:
        return frozenset(row[0] for row in self._connection.execute("SELECT ref FROM models").fetchall())


_META_SQL = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT"
_TABLES = {
    "ledger": (
        "CREATE TABLE entries (cid TEXT PRIMARY KEY, header BLOB NOT NULL) STRICT",
        "CREATE TABLE models (ref TEXT PRIMARY KEY, body BLOB NOT NULL) STRICT",
    ),
    "contents": (
        "CREATE TABLE contents (seal TEXT PRIMARY KEY, salt BLOB NOT NULL, media_type TEXT NOT NULL, data BLOB NOT NULL) STRICT",
    ),
}


class SqliteStore:
    @classmethod
    def open(cls, directory: str | _os.PathLike, *, create: bool = False,
             readonly: bool = False) -> "SqliteStore":
        if create and readonly:
            raise ValueError("create and readonly are mutually exclusive")
        directory = _Path(directory)
        paths = {role: directory / f"{role}.sqlite" for role in _TABLES}
        if not create or any(path.exists() for path in paths.values()):
            for path in paths.values():
                if not path.is_file():
                    raise FileNotFoundError(path)
        else:
            directory.mkdir(parents=True, exist_ok=True)
        store = cls()
        store.readonly = readonly
        store._connections = {}
        try:
            for role, path in paths.items():
                new = not path.exists()
                if readonly:
                    connection = _sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                                                  uri=True, isolation_level=None)
                else:
                    connection = _sqlite3.connect(path, isolation_level=None)
                store._connections[role] = connection
                if not readonly:
                    if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                        raise OSError(f"{path}: WAL unavailable")
                    connection.execute("PRAGMA synchronous=FULL")
                    connection.execute("PRAGMA secure_delete=ON")
                if new:
                    with _transaction(connection):
                        for sql in (_META_SQL, *_TABLES[role]):
                            connection.execute(sql)
                        connection.executemany("INSERT INTO meta VALUES (?, ?)",
                                               (("format", "sui.store.1"), ("role", role)))
                try:
                    meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
                except _sqlite3.DatabaseError as exc:
                    raise StoreFormatMismatch(f"{path}: missing or invalid meta") from exc
                if meta.get("format") != "sui.store.1" or meta.get("role") != role:
                    raise StoreFormatMismatch(f"{path}: incompatible format or role")
            store.entries = _SqliteEntries(store, "ledger")
            store.contents = _SqliteContents(store, "contents")
            store.models = _SqliteModels(store, "ledger")
            return store
        except BaseException:
            store.close()
            raise

    def close(self) -> None:
        try:
            connection = self._connections.get("contents")
            if connection is not None:
                connection.close()
        finally:
            connection = self._connections.get("ledger")
            if connection is not None:
                connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


STORE_SCHEMA = _Contract(
    ref=_ContractRef("sui.store", "1"),
    meaning='台帳の永続の置き場。ledger.sqlite は点 (cid と骨組みの正準 JSON) とモデル (参照と正準 JSON) で本文を含まない。contents.sqlite は封で引く本文と塩。STRICT 表: '
            + _META_SQL + '; ' + '; '.join(sql for tables in _TABLES.values() for sql in tables)
            + '。各ファイルの meta は format=sui.store.1 と role=ledger / contents',
    unit='cid・封・参照は sha256: + 16進64桁、塩は16バイト、本文は media_type とバイト列',
    state_owner='書く接続1つ (単一の書き手)。読むだけの接続はいくつでも',
    persistence='WAL・synchronous=FULL・secure_delete=ON。書く操作は1つずつ確定してから戻る。書く順は本文 → 点、親 → 子',
    failure='満杯は StorageFull、失敗した取引は何も書かず元の誤りは __cause__。形式の違いは StoreFormatMismatch。読むだけなら ReadOnlyStore (台帳は塩を引く前に拒む)。故障後は親で閉じた点の集合と孤児だけ。append の孤児・merge の確定済み部分は残る。モデルは参照する最初の記録より先に置く (呼ぶ側の約束)',
    cancel='discard はその封の行の本文と塩を消し、空いた領域と WAL の掃除の完了を返す。同じ本文の別の行・派生物・複製は範囲外 (意味は S8)。削除確定後の掃除の例外は ScrubIncomplete。点とモデルは消さない',
    redelivery='同じ cid・骨組み、同じ封・塩・本文、同じ参照・モデルは何もしない。同じ名前で違う中身は ValueError',
)
