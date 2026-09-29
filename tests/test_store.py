"""S2b: 同一性・永続・故障の境目・消去の範囲を確かめる。"""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from sui.agent import Agent, read
from sui.clock import FakeClock
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import (Ledger, MemoryContents, SequentialSalts, CorruptEntry,
                        entry_from_header, seal)
from sui.model import GenerativeModel, model_json, model_from_json, model_ref
from sui.records import Payload, IdConflict, Observed, Prediction, AttemptStarted, SchemaMismatch, Role
from sui.store import (SqliteStore, MemoryEntries, MemoryModels, StorageFull,
                       ReadOnlyStore, StoreFormatMismatch, ScrubIncomplete, CorruptModel,
                       STORE_SCHEMA)
from test_agent import _full_state, _assert_record_reproducible
from test_ledger import _record, _f4
from worlds import _model, _storage, _stored_rig, _stored_step


def open_ledger(store, salts=None):
    return Ledger(salts=SequentialSalts() if salts is None else salts,
                  entries=store.entries, contents=store.contents)


def rows(store):
    return (store.entries.load(), tuple(sorted(
        (key, store.contents.get(key)) for key in store.contents.seals())),
        tuple(sorted((ref, model_json(store.models.get(ref))) for ref in store.models.refs())))


def graph(ledger):
    return {entry.cid: entry.header for entry in ledger.entries()}


def restore(store, ledger, cid):
    ref = ledger.record(cid).body.content.as_json()["model"]
    return Agent.restore(model=store.models.get(ref), lineage="line1", ledger=ledger, belief=cid)


def test_p1_same_graph_reopen_restore_and_continue(tmp_path):
    with _storage(tmp_path / "memory", "memory") as mem, _storage(tmp_path / "sql") as sql:
        a, b = _stored_rig(mem), _stored_rig(sql)
        for _ in range(8):
            assert _stored_step(a) == _stored_step(b)
        expected = graph(a.ledger)
        assert graph(b.ledger) == expected
        assert a.ledger.heads() == b.ledger.heads()
        assert a.agent._belief.body.content == b.agent._belief.body.content
        cid = b.ledger.entries_of(b.agent._belief.id)[0].cid
    with SqliteStore.open(tmp_path / "sql") as sql:
        b.ledger = open_ledger(sql, b.ledger._salts)
        assert graph(b.ledger) == expected
        b.ledger.verify()
        b.agent = restore(sql, b.ledger, cid)
        assert _full_state(a.agent) == _full_state(b.agent)
        assert _stored_step(a) == _stored_step(b)
        assert graph(a.ledger) == graph(b.ledger)
        assert _full_state(a.agent) == _full_state(b.agent)


def model_cases():
    return [_f4(), _model(), _model(a={k: v.astype(np.int64) for k, v in _model().a.items()}),
            GenerativeModel(states=("s",), outcomes=("o",), actions=("a",),
                a={"a": np.array([[1.]])}, learnable=frozenset(), D=np.array([1.]),
                log_C=np.array([-0.0]), gamma=1.0)]


def assert_model_bits(a, b):
    assert model_ref(a) == model_ref(b)
    assert a.states == b.states and a.actions == b.actions and a.outcomes == b.outcomes
    assert a.learnable == b.learnable
    assert type(b.gamma) is float and a.gamma == b.gamma
    for x, y in [(a.D, b.D), (a.log_C, b.log_C), *[(a.a[k], b.a[k]) for k in a.actions]]:
        assert x.dtype == y.dtype
        assert x.tobytes() == y.tobytes()


def test_p2_model_roundtrips_and_corruption(tmp_path):
    models = model_cases()
    assert "sha256:" + hashlib.sha256(model_json(models[0])).hexdigest() == (
        "sha256:568c5dd475ebe1518c227944556166aaf647328d2f86507dd696f82a06824fb2")
    with SqliteStore.open(tmp_path, create=True) as store:
        for model in models:
            assert_model_bits(model, model_from_json(model_json(model)))
            assert store.models.put(model) == model_ref(model)
    with SqliteStore.open(tmp_path) as store:
        assert store.models.refs() == frozenset(map(model_ref, models))
        for model in models:
            assert_model_bits(model, store.models.get(model_ref(model)))
        with pytest.raises(KeyError):
            store.models.get("absent")
        original = model_json(models[0])
        corrupt = original.replace(b'2.0', b'3.0', 1)
        assert corrupt != original and len(corrupt) == len(original)
        store._connections["ledger"].execute("UPDATE models SET body=? WHERE ref=?",
                                            (corrupt, model_ref(models[0])))
        with pytest.raises(CorruptModel, match=model_ref(models[0])):
            store.models.get(model_ref(models[0]))


@pytest.mark.parametrize("change", ["scheme", "extra", "missing", "spacing", "invalid", "axis"])
def test_p2_invalid_model_encoding(change):
    data = json.loads(model_json(_model()))
    if change == "scheme":
        data["scheme"] = "sui.model.2"
    elif change == "extra":
        data["extra"] = 1
    elif change == "missing":
        del data["D"]
    elif change == "axis":
        data["states"] = []
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if change == "spacing":
        raw += b" "
    elif change == "invalid":
        raw = b"[]"
    with pytest.raises(ValueError):
        model_from_json(raw)


def independent_read(directory):
    # P3: 独立の式と固定の表定義だけを使う。この関数は sui を参照しない。
    import base64
    import hashlib
    import json
    import sqlite3
    from pathlib import Path

    definitions = {
        "ledger": {
            "meta": "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT",
            "entries": "CREATE TABLE entries (cid TEXT PRIMARY KEY, header BLOB NOT NULL) STRICT",
            "models": "CREATE TABLE models (ref TEXT PRIMARY KEY, body BLOB NOT NULL) STRICT"},
        "contents": {
            "meta": "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT",
            "contents": "CREATE TABLE contents (seal TEXT PRIMARY KEY, salt BLOB NOT NULL, media_type TEXT NOT NULL, data BLOB NOT NULL) STRICT"},
    }
    values = {}
    for role in definitions:
        connection = sqlite3.connect((Path(directory) / (role + ".sqlite")).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            assert dict(connection.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")) == definitions[role]
            assert dict(connection.execute("SELECT * FROM meta")) == {"format": "sui.store.1", "role": role}
            values[role] = list(connection.execute("SELECT * FROM " + ("entries" if role == "ledger" else "contents")))
        finally:
            connection.close()
    seals = set()
    for sealed, salt, media_type, data in values["contents"]:
        material = {"scheme": "sui.seal.1", "salt": salt.hex(), "media_type": media_type,
                    "data": base64.b64encode(data).decode("ascii")}
        raw = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        assert sealed == "sha256:" + hashlib.sha256(raw).hexdigest()
        seals.add(sealed)
    for cid, header in values["ledger"]:
        assert cid == "sha256:" + hashlib.sha256(header).hexdigest()
        assert json.loads(header)["seal"] in seals
    return len(values["ledger"])


def test_p3_independent_reader(tmp_path):
    with _storage(tmp_path) as store:
        rig = _stored_rig(store)
        for _ in range(8):
            _stored_step(rig)
        assert independent_read(tmp_path) == len(rig.ledger.entries())
    assert STORE_SCHEMA.ref.name == "sui.store" and STORE_SCHEMA.ref.version == "1"


def test_p4_reopened_redelivery_and_conflict(tmp_path):
    with _storage(tmp_path) as store:
        rig = _stored_rig(store)
        for _ in range(8):
            step = _stored_step(rig)
        cid = rig.ledger.entries_of(step.observed.id)[0].cid
    with SqliteStore.open(tmp_path) as store:
        ledger = open_ledger(store)
        before = rows(store)
        assert ledger.accept(step.observed).cid == cid
        assert rows(store) == before
        changed = replace(step.observed, body=replace(step.observed.body, content=Payload.json({"outcome": "different"})))
        with pytest.raises(IdConflict):
            ledger.accept(changed)
        assert rows(store) == before


def file_bytes(path):
    # 呼ぶのはすべての接続を閉じた時だけ。
    return {p.name: p.read_bytes() for p in Path(path).glob("*.sqlite")}


def test_p5_readonly_and_no_salt_consumption(tmp_path):
    with _storage(tmp_path) as store:
        ledger = open_ledger(store)
        first = ledger.accept(_record())
    before = file_bytes(tmp_path)
    with SqliteStore.open(tmp_path, readonly=True) as store:
        salts = SequentialSalts()
        ledger = open_ledger(store, salts)
        ledger.verify()
        assert ledger.record(first.cid) == _record()
        assert ledger.accept(_record()) == first
        for write in (lambda: ledger.accept(_record("new", 8)),
                      lambda: ledger.append(_record("new", 8), ledger.heads()),
                      lambda: store.entries.add("x", b"x"),
                      lambda: store.contents.put("x", bytes(16), Payload.text("x")),
                      lambda: store.contents.discard("absent"), lambda: store.models.put(_model())):
            with pytest.raises(ReadOnlyStore):
                write()
        assert salts.new() == (1).to_bytes(16, "big")
        other = Ledger(salts=SequentialSalts())
        other.accept(_record())
        ledger.merge(other)
        other.accept(_record("new", 8))
        with pytest.raises(ReadOnlyStore):
            ledger.merge(other)
        assert len(ledger.entries()) == 1
        for connection in store._connections.values():
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("UPDATE meta SET value='bad'")
    assert file_bytes(tmp_path) == before


def test_p5_reader_snapshot_does_not_block_writer(tmp_path):
    with _storage(tmp_path) as writer, SqliteStore.open(tmp_path, readonly=True) as reader:
        ledger = open_ledger(writer)
        connection = reader._connections["ledger"]
        connection.execute("BEGIN")
        assert reader.entries.load() == ()
        ledger.accept(_record())
        assert reader.entries.load() == ()
        connection.execute("COMMIT")
        assert len(reader.entries.load()) == 1


def test_p6_open_modes_meta_and_paths(tmp_path):
    path = tmp_path / "置き場 1"
    with pytest.raises(FileNotFoundError):
        SqliteStore.open(path)
    with pytest.raises(ValueError):
        SqliteStore.open(path, create=True, readonly=True)
    with SqliteStore.open(path, create=True):
        pass
    with SqliteStore.open(path, readonly=True):
        pass
    ledger, contents = path / "ledger.sqlite", path / "contents.sqlite"
    temporary = path / "swap"
    ledger.rename(temporary)
    contents.rename(ledger)
    temporary.rename(contents)
    with pytest.raises(StoreFormatMismatch):
        SqliteStore.open(path)
    ledger.rename(temporary)
    contents.rename(ledger)
    temporary.rename(contents)
    connection = sqlite3.connect(ledger)
    try:
        connection.execute("UPDATE meta SET value='sui.store.2' WHERE key='format'")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreFormatMismatch):
        SqliteStore.open(path)


@pytest.mark.parametrize("corruption", ["header", "parent", "content"])
def test_p7_open_checks_headers_and_parents_but_not_contents(tmp_path, corruption):
    with _storage(tmp_path) as store:
        ledger = open_ledger(store)
        parent = ledger.accept(_record())
        child = ledger.accept(_record("child", 8))
        if corruption == "header":
            altered = child.header.replace(b'"seq":8', b'"seq":9')
            assert json.loads(altered)["at"]["seq"] == 9
            store._connections["ledger"].execute("UPDATE entries SET header=? WHERE cid=?", (altered, child.cid))
        elif corruption == "parent":
            store._connections["ledger"].execute("DELETE FROM entries WHERE cid=?", (parent.cid,))
        else:
            store.contents.discard(child.seal)
    with SqliteStore.open(tmp_path) as store:
        if corruption != "content":
            with pytest.raises(CorruptEntry, match=child.cid):
                open_ledger(store)
        else:
            ledger = open_ledger(store)
            with pytest.raises(CorruptEntry, match=child.cid):
                ledger.verify()


@pytest.mark.parametrize("missing_role", ["contents", "ledger"])
def test_p6_partial_store_is_rejected_before_connecting(tmp_path, monkeypatch, missing_role):
    with _storage(tmp_path) as store:
        rig = _stored_rig(store)
        _stored_step(rig)
    missing = tmp_path / f"{missing_role}.sqlite"
    missing.unlink()
    before = {path.name: path.read_bytes() for path in tmp_path.glob("*.sqlite*")}
    assert before

    def unexpected_connect(*args, **kwargs):
        raise AssertionError("partial store must be rejected before connecting")

    monkeypatch.setattr(sqlite3, "connect", unexpected_connect)
    with pytest.raises(FileNotFoundError) as caught:
        SqliteStore.open(tmp_path, create=True)
    assert str(missing) in str(caught.value)
    assert not missing.exists()
    assert {path.name: path.read_bytes() for path in tmp_path.glob("*.sqlite*")} == before


def test_p7_header_reader_schema_and_shape():
    ledger = Ledger(salts=SequentialSalts())
    entry = ledger.accept(_record())
    assert entry_from_header(entry.cid, entry.header) == entry
    for data, error in [(dict(json.loads(entry.header), schema=4), SchemaMismatch),
                        (dict(json.loads(entry.header), parents="bad"), CorruptEntry)]:
        header = Payload.json(data).data
        with pytest.raises(error):
            entry_from_header("sha256:" + hashlib.sha256(header).hexdigest(), header)


def test_p8_sqlite_settings(tmp_path):
    with _storage(tmp_path) as store:
        for connection in store._connections.values():
            assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
            assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
            assert connection.execute("PRAGMA secure_delete").fetchone() == (1,)


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_p9_idempotence_and_collision(tmp_path, backend):
    with _storage(tmp_path, backend) as store:
        content, salt = Payload.text("original"), bytes(range(16))
        sealed = seal(content, salt)
        for _ in range(2):
            store.contents.put(sealed, salt, content)
            store.entries.add("cid", b"header")
            store.models.put(_model())
        assert len(store.contents.seals()) == len(store.entries.load()) == len(store.models.refs()) == 1
        before = rows(store)
        for write in (lambda: store.contents.put(sealed, salt, Payload.text("different")),
                      lambda: store.contents.put(sealed, bytes(16), content),
                      lambda: store.entries.add("cid", b"different")):
            with pytest.raises(ValueError):
                write()
            assert rows(store) == before
        ref = model_ref(_model())
        if backend == "sqlite":
            store._connections["ledger"].execute("UPDATE models SET body=? WHERE ref=?", (b"wrong", ref))
        else:
            store.models._items[ref] = b"wrong"
        with pytest.raises(ValueError):
            store.models.put(_model())
        if backend == "sqlite":
            assert store._connections["ledger"].execute("SELECT body FROM models WHERE ref=?", (ref,)).fetchone() == (b"wrong",)
        else:
            assert store.models._items[ref] == b"wrong"


@pytest.mark.parametrize("corruption", ["content", "header"])
def test_p10_merge_validates_all_pending_before_writing(corruption):
    source, target = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    source.accept(_record())
    later = source.accept(_record("later", 8))
    if corruption == "content":
        salt, _ = source.contents.get(later.seal)
        source.contents._items[later.seal] = salt, Payload.json({"outcome": "o0"})
    else:
        source._entries[later.cid] = replace(later, header=later.header.replace(b'"seq":8', b'"seq":9'))
    with pytest.raises(CorruptEntry, match=later.cid):
        target.merge(source)
    assert target.entries() == () and target.contents.seals() == frozenset()


def test_p10_already_present_content_is_not_revalidated():
    source, target = Ledger(salts=SequentialSalts()), Ledger(salts=SequentialSalts())
    first = source.accept(_record())
    target.merge(source)
    salt, _ = source.contents.get(first.seal)
    source.contents._items[first.seal] = salt, Payload.text("tampered")
    source.accept(_record("later", 8))
    target.merge(source)
    target.verify()
    assert len(target.entries()) == 2


@pytest.mark.parametrize("field", ["parents", "seal", "id", "body_type", "at", "writer"])
@pytest.mark.parametrize("events_only", [False, True])
def test_p10_entry_fields_must_match_header_before_any_write(field, events_only):
    source = reversed_cid_pair()
    parent, child = source.entries()
    assert child.cid < parent.cid
    # 別の封にも同じ本文を用意する。封と本文の照合だけでは検出できない。
    salt, content = source.contents.get(child.seal)
    other_salt = bytes(range(16))
    assert other_salt != salt
    other_seal = seal(content, other_salt)
    source.contents.put(other_seal, other_salt, content)
    changes = {"parents": frozenset(), "seal": other_seal,
               "id": Ref(K.OBSERVATION, "different-id"), "body_type": Prediction,
               "at": replace(child.at, seq=child.at.seq + 1), "writer": Role.MODEL}
    source._entries[child.cid] = replace(child, **{field: changes[field]})
    assert source._entries[child.cid].header == child.header
    target = Ledger(salts=SequentialSalts())
    target.accept(_record("existing", run="target"))
    before = graph(target), target.contents.seals()
    with pytest.raises(CorruptEntry, match=child.cid):
        target.merge(source, events_only=events_only)
    assert (graph(target), target.contents.seals()) == before


class Crash(RuntimeError):
    pass


class WriteCounter:
    def __init__(self, k=None, after=False, error=Crash, kind=None):
        self.k, self.after, self.error, self.kind = k, after, error, kind
        self.calls = []
        self.failure = None

    def call(self, kind, operation, *args):
        self.calls.append((kind, args))
        count = sum(self.kind is None or name == self.kind for name, _ in self.calls)
        fail = (self.kind is None or kind == self.kind) and count == self.k
        if fail:
            self.failure = kind, args
        if fail and not self.after:
            raise self.error("before commit")
        result = operation(*args)
        if fail:
            raise self.error("after commit")
        return result


class CrashingEntries:
    def __init__(self, delegate, counter):
        self.delegate, self.counter = delegate, counter

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def add(self, *args):
        return self.counter.call("add", self.delegate.add, *args)


class CrashingContents:
    def __init__(self, delegate, counter):
        self.delegate, self.counter = delegate, counter

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def put(self, *args):
        return self.counter.call("put", self.delegate.put, *args)


class CrashingModels:
    def __init__(self, delegate, counter):
        self.delegate, self.counter = delegate, counter

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def put(self, *args):
        return self.counter.call("model", self.delegate.put, *args)


class FullAt(WriteCounter):
    def __init__(self, kind, n):
        super().__init__(n, error=StorageFull, kind=kind)


def wrap(store, counter):
    return SimpleNamespace(entries=CrashingEntries(store.entries, counter),
        contents=CrashingContents(store.contents, counter), models=CrashingModels(store.models, counter))


def reversed_cid_pair():
    for n in range(1000):
        other = Ledger(salts=SequentialSalts())
        parent = other.accept(_record(f"merge-parent-{n}", run="other"))
        child = other.accept(_record(f"merge-child-{n}", 8, run="other"))
        if child.cid < parent.cid:
            assert child.parents == frozenset({parent.cid})
            return other
    raise AssertionError("could not find child cid < parent cid")


class ReturningLedger(Ledger):
    def __init__(self, *args, returned, **kwargs):
        super().__init__(*args, **kwargs)
        self.returned = returned

    def append(self, *args, **kwargs):
        entry = super().append(*args, **kwargs)
        self.returned.add(entry.cid)
        return entry


class RecordingExecutor:
    def __init__(self, ledger, calls):
        self.ledger, self.calls = ledger, calls

    def execute(self, action):
        attempt = [e for e in self.ledger.entries() if e.body_type is AttemptStarted][-1]
        self.calls.append((action, attempt.cid))
        return "none" if action == "wait" else "o1"


def crash_work(store, counter, other, returned, effects):
    wrapped = wrap(store, counter)
    ledger = ReturningLedger(salts=SequentialSalts(), entries=wrapped.entries,
                             contents=wrapped.contents, returned=returned)
    rig = _stored_rig(wrapped, ledger=ledger)
    rig.world = RecordingExecutor(ledger, effects)
    for _ in range(3):
        _stored_step(rig)
    ledger.merge(other)
    return ledger


def check_rebuild(store, ledger):
    beliefs = [e for e in ledger.entries() if e.body_type is Prediction]
    if not beliefs:
        assert ledger.entries() == ()
        return
    last = max(beliefs, key=lambda e: ledger.record(e.cid).producer.state.revision)
    subject = restore(store, ledger, last.cid)
    model = store.models.get(subject.model_ref)
    # 実ファイルの網を変えず、同じ確定済みの事実をメモリに写して採用する。
    copy = Ledger(salts=SequentialSalts())
    copy.merge(ledger)
    subject.adopt(copy, clock=FakeClock(run=Ref(K.RUN, "rebuild")), ids=SequentialIds(prefix="rebuild"))
    expected = read(model, ledger.snapshot(ledger.heads()).records)
    assert subject.frontier == ledger.heads()
    assert dict(subject.unread) == expected.unread
    for action in model.actions:
        assert subject._reading.n[action].tobytes() == expected.n[action].tobytes()
    _assert_record_reproducible(model, subject._belief)


def test_k1_every_write_boundary(tmp_path, record_property):
    other = reversed_cid_pair()
    counter = WriteCounter()
    with _storage(tmp_path / "baseline") as store:
        full = graph(crash_work(store, counter, other, set(), []))
    total = len(counter.calls)
    record_property("K1_N", total)
    assert total == 37  # model + (initial belief + 3 * 5 step records + 2 merged) * 2
    merge_start = total - 2 * len(other.entries()) + 1
    for after in (False, True):
        for k in range(1, total + 1):
            path = tmp_path / f"crash-{after}-{k}"
            returned, effects = set(), []
            failure = WriteCounter(k, after)
            with _storage(path) as store:
                with pytest.raises(Crash):
                    crash_work(store, failure, other, returned, effects)
            with SqliteStore.open(path) as store:
                ledger = open_ledger(store)
                ledger.verify()
                saved = graph(ledger)
                assert returned <= saved.keys() <= full.keys(), (after, k)
                assert all(full[cid] == header for cid, header in saved.items())
                kind, args = failure.failure
                if kind == "put" and after:
                    orphan = args[0]
                elif kind == "add" and not after:
                    orphan = json.loads(args[1])["seal"]
                else:
                    orphan = None
                assert ledger.orphans() == (frozenset() if orphan is None else frozenset({orphan})), (after, k)
                assert all(cid in saved for _, cid in effects)
                check_rebuild(store, ledger)
                if k >= merge_start:
                    ledger.merge(other)
                    assert graph(ledger) == full
                    assert ledger.orphans() == frozenset()


KILL_CHILD = r'''
import sys
from sui.store import SqliteStore
from worlds import _stored_rig, _stored_step
with SqliteStore.open(sys.argv[1], create=True) as store:
    rig = _stored_rig(store)
    print("READY", flush=True)
    while True:
        step = _stored_step(rig)
        print(rig.ledger.entries_of(step.belief.id)[0].cid, flush=True)
'''


@pytest.mark.parametrize("delay", [.05, .1, .2, .4, .8])
def test_k2_killed_process_retains_acknowledged_commits(tmp_path, delay):
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(root / "tests"), env.get("PYTHONPATH", "")))
    with subprocess.Popen([sys.executable, "-W", "error", "-u", "-c", KILL_CHILD, str(tmp_path)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) as child:
        lines = []
        ready, first = threading.Event(), threading.Event()
        def receive():
            for line in child.stdout:
                value = line.strip()
                if value == "READY":
                    ready.set()
                else:
                    lines.append(value)
                    first.set()
        receiver = threading.Thread(target=receive)
        receiver.start()
        try:
            assert ready.wait(20), "child did not initialize"
            assert first.wait(20), "child did not commit a step"
            time.sleep(delay)
        finally:
            child.kill()
            child.wait(timeout=20)
            receiver.join(timeout=20)
        assert not receiver.is_alive()
        assert child.stderr.read() == ""
    assert lines and all(line.startswith("sha256:") for line in lines)
    with SqliteStore.open(tmp_path) as store:
        ledger = open_ledger(store)
        ledger.verify()
        assert set(lines) <= graph(ledger).keys()


@pytest.mark.parametrize("role", ["contents", "ledger"])
def test_f0_real_sqlite_full_preserves_original_failure(tmp_path, role):
    with _storage(tmp_path) as store:
        connection = store._connections[role]
        assert connection.execute("PRAGMA freelist_count").fetchone() == (0,)
        maximum = connection.execute("PRAGMA max_page_count").fetchone()[0]
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={pages}")
        before = rows(store)
        def write():
            if role == "contents":
                store.contents.put("large", bytes(16), Payload("application/octet-stream", b"x" * 9000))
            else:
                store.entries.add("large", b"x" * 9000)
        with pytest.raises(StorageFull) as caught:
            write()
        assert type(caught.value) is StorageFull
        assert caught.value.__cause__.sqlite_errorname == "SQLITE_FULL"
        assert caught.value.__cause__.__context__ is None
        assert not connection.in_transaction
        assert rows(store) == before
        connection.execute(f"PRAGMA max_page_count={maximum}")
        write()


@pytest.mark.parametrize("nth", [1, 3, 4])
def test_f1_f3_full_during_step(tmp_path, nth):
    with _storage(tmp_path) as store, _storage(tmp_path / "control", "memory") as memory:
        rig, control = _stored_rig(store), _stored_rig(memory)
        for _ in range(2):
            _stored_step(rig)
            _stored_step(control)
        before, heads, state = rows(store), rig.ledger.heads(), _full_state(rig.agent)
        calls = len(rig.world.calls)
        contents = rig.ledger.contents
        rig.ledger.contents = CrashingContents(contents, FullAt("put", nth))
        with pytest.raises(StorageFull):
            _stored_step(rig)
        assert len(rig.world.calls) == calls + (1 if nth == 4 else 0)
        assert _full_state(rig.agent) == state
        assert rig.ledger.orphans() == frozenset()
        added = [e for e in rig.ledger.entries() if e.cid not in dict(before[0])]
        assert len(added) == nth - 1
        assert sum(e.body_type is AttemptStarted for e in added) == (1 if nth == 4 else 0)
        assert all(e.body_type is not Observed for e in added)
        if nth == 1:
            assert rows(store) == before and rig.ledger.heads() == heads
            rig.ledger.contents = contents
            retry, normal = _stored_step(rig), _stored_step(control)
            assert retry.job.body.content == normal.job.body.content
            assert retry.belief.body.content == normal.belief.body.content


def test_f2_entry_failure_does_not_change_memory_and_orphan_is_visible(tmp_path):
    with _storage(tmp_path) as store:
        rig = _stored_rig(store)
        _stored_step(rig)
        before, heads = graph(rig.ledger), rig.ledger.heads()
        counter = FullAt("add", 1)
        rig.ledger._entry_store = CrashingEntries(store.entries, counter)
        with pytest.raises(StorageFull):
            rig.ledger.accept(_record("failed", run="other"))
        orphan = json.loads(counter.failure[1][1])["seal"]
        assert rig.ledger.orphans() == frozenset({orphan})
        assert graph(rig.ledger) == before and rig.ledger.heads() == heads
        rig.ledger._entry_store = store.entries
        _stored_step(rig)
    with SqliteStore.open(tmp_path) as store:
        ledger = open_ledger(store)
        ledger.verify()
        assert ledger.orphans() == frozenset({orphan})


SCAN_CHILD = r'''
import json, sys
from pathlib import Path
directory, pattern, *needles = sys.argv[1:]
needles = [bytes.fromhex(value) for value in needles]
found = []
for path in Path(directory).glob(pattern):
    if path.is_file():
        data = path.read_bytes()
        if any(needle in data for needle in needles):
            found.append(path.name)
print(json.dumps(found))
'''


def scan(path, needles, pattern="*"):
    result = subprocess.run([sys.executable, "-c", SCAN_CHILD, str(path), pattern,
                             *(needle.hex() for needle in needles)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("size,offset", [(100, 0), (20000, 10000), (20000, 19976)])
def test_e1_discard_scrubs_live_files_and_overflow_pages(tmp_path, size, offset):
    rng = random.Random(781)
    mark, salt = rng.randbytes(24), rng.randbytes(16)
    data = b"x" * offset + mark + b"x" * (size - offset - len(mark))
    content = Payload("application/octet-stream", data)
    sealed = seal(content, salt)
    with _storage(tmp_path) as store:
        neighbours = []
        for index in range(7):
            if index == 3:
                store.contents.put(sealed, salt, content)
            else:
                other_salt = rng.randbytes(16)
                other = Payload("application/octet-stream", rng.randbytes(8000))
                assert mark not in other.data and salt not in other.data and salt != other_salt
                other_seal = seal(other, other_salt)
                neighbours.append((other_seal, other_salt, other))
                store.contents.put(other_seal, other_salt, other)
        # 元の本文を本ファイルにも載せる。close による掃除には頼らない。
        store._connections["contents"].execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert scan(tmp_path, [mark]) and scan(tmp_path, [salt])
        assert store.contents.discard(sealed) is True
        assert sealed not in store.contents.seals()
        with pytest.raises(KeyError):
            store.contents.get(sealed)
        assert scan(tmp_path, [mark, salt]) == []
        for key, other_salt, other in neighbours:
            assert store.contents.get(key) == (other_salt, other)
        assert store.contents.discard(sealed) is True
    assert scan(tmp_path, [mark, salt]) == []


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_e1_other_seal_with_same_content_survives(tmp_path, backend):
    with _storage(tmp_path, backend) as store:
        content = Payload.text("same content")
        salts = [bytes(range(16)), bytes(range(1, 17))]
        seals = [seal(content, salt) for salt in salts]
        for key, salt in zip(seals, salts):
            store.contents.put(key, salt, content)
        assert store.contents.discard(seals[0]) is True
        assert store.contents.get(seals[1]) == (salts[1], content)
        assert store.contents.discard(seals[0]) is True


class BrokenCheckpoint:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args):
        if sql == "PRAGMA wal_checkpoint(TRUNCATE)":
            raise sqlite3.OperationalError("checkpoint failed")
        return self.connection.execute(sql, *args)


def test_e1_checkpoint_exception_reports_committed_deletion(tmp_path):
    with _storage(tmp_path) as store:
        store.contents.put("key", bytes(16), Payload.text("body"))
        connection = store._connections["contents"]
        timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        store._connections["contents"] = BrokenCheckpoint(connection)
        with pytest.raises(ScrubIncomplete) as caught:
            store.contents.discard("key")
        assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
        with pytest.raises(KeyError):
            store.contents.get("key")
        assert connection.execute("PRAGMA busy_timeout").fetchone() == timeout
        store._connections["contents"] = connection
        assert store.contents.discard("key") is True


def test_e2_reader_prevents_scrub_until_transaction_ends(tmp_path):
    rng = random.Random(451)
    mark, salt = rng.randbytes(24), rng.randbytes(16)
    content = Payload("application/octet-stream", mark * 100)
    sealed = seal(content, salt)
    with _storage(tmp_path) as writer, SqliteStore.open(tmp_path, readonly=True) as reader:
        writer.contents.put(sealed, salt, content)
        writer._connections["contents"].execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection = reader._connections["contents"]
        connection.execute("BEGIN")
        assert reader.contents.get(sealed) == (salt, content)
        timeout = writer._connections["contents"].execute("PRAGMA busy_timeout").fetchone()
        start = time.monotonic()
        assert writer.contents.discard(sealed) is False
        assert time.monotonic() - start < 2
        assert writer._connections["contents"].execute("PRAGMA busy_timeout").fetchone() == timeout
        with pytest.raises(KeyError):
            writer.contents.get(sealed)
        assert reader.contents.get(sealed) == (salt, content)
        assert scan(tmp_path, [mark, salt])
        connection.execute("COMMIT")
        assert writer.contents.discard(sealed) is True
        assert scan(tmp_path, [mark, salt]) == []


def test_e3_ledger_files_never_contain_content_or_salt(tmp_path):
    with _storage(tmp_path) as store:
        class MarkerSalts:
            def __init__(self):
                self.rng = random.Random(2357)

            def new(self):
                return self.rng.randbytes(16)
        rig = _stored_rig(store, ledger=open_ledger(store, MarkerSalts()))
        for _ in range(8):
            _stored_step(rig)
        content = Payload.json({"outcome": "o1", "mark": "ba7780f1032ee6f419dc107a"})
        record = _record("marked", run="outside")
        entry = rig.ledger.accept(replace(record, body=replace(record.body, content=content)))
        salt, _ = store.contents.get(entry.seal)
        for filename in ("ledger.sqlite", "ledger.sqlite-wal"):
            assert scan(tmp_path, [content.data, salt], filename) == []
        for entry in rig.ledger.entries():
            row_salt, payload = store.contents.get(entry.seal)
            # {} は短すぎてモデルの空辞書などと偶然重なる。目印の観測は上で別に縛る。
            if len(payload.data) > 2:
                for filename in ("ledger.sqlite", "ledger.sqlite-wal"):
                    assert scan(tmp_path, [payload.data, row_salt], filename) == []


@pytest.mark.parametrize("readonly_role", ["entries", "contents"])
def test_p5_either_readonly_store_rejects_before_salt(tmp_path, readonly_role):
    with _storage(tmp_path) as writer, SqliteStore.open(tmp_path, readonly=True) as reader:
        salts = SequentialSalts()
        ledger = Ledger(salts=salts,
            entries=reader.entries if readonly_role == "entries" else writer.entries,
            contents=reader.contents if readonly_role == "contents" else writer.contents)
        with pytest.raises(ReadOnlyStore):
            ledger.accept(_record())
        assert salts.new() == (1).to_bytes(16, "big")
        assert writer.entries.load() == () and writer.contents.seals() == frozenset()


def test_p2_memory_models_check_digest_and_missing_reference():
    models = MemoryModels()
    model = _f4()
    ref = models.put(model)
    assert_model_bits(model, models.get(ref))
    assert models.refs() == frozenset({ref})
    with pytest.raises(KeyError):
        models.get("absent")
    models._items[ref] = models._items[ref].replace(b'2.0', b'3.0', 1)
    with pytest.raises(CorruptModel):
        models.get(ref)


@pytest.mark.parametrize("full", [False, True])
def test_f0_rollback_failure_does_not_hide_original_exception(tmp_path, full):
    with _storage(tmp_path) as store:
        connection = store._connections["ledger"]
        original = sqlite3.OperationalError("injected write failure")
        original.sqlite_errorname = "SQLITE_FULL" if full else "SQLITE_IOERR"
        rollback_error = sqlite3.OperationalError("injected rollback failure")
        class BrokenWrite:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *args):
                if sql.startswith("INSERT"):
                    raise original
                result = connection.execute(sql, *args)
                if sql == "ROLLBACK":
                    raise rollback_error
                return result
        store._connections["ledger"] = BrokenWrite()
        try:
            with pytest.raises(StorageFull if full else sqlite3.OperationalError) as caught:
                store.entries.add("key", b"header")
            actual = caught.value.__cause__ if full else caught.value
            assert actual is original
            assert actual.__context__ is rollback_error
            assert store.entries.load() == ()
            assert not connection.in_transaction
        finally:
            store._connections["ledger"] = connection
