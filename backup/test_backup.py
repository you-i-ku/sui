from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from sui.agent import Agent
from sui.clock import FakeClock
from sui.ids import Ref, RefKind as K, SequentialIds
from sui.ledger import CorruptEntry
from sui.model import model_ref
from sui.records import Observed, Payload, Prediction
from sui.store import SqliteStore
from sui_backup import sync, SyncReport
from test_agent import _full_state
from test_store import (open_ledger, graph, restore, rows, file_bytes,
                        WriteCounter, Crash, wrap)
from worlds import _storage, _stored_rig, _stored_step, _model


def all_rows(path):
    result = {}
    for role in ("ledger", "contents"):
        connection = sqlite3.connect((Path(path) / (role + ".sqlite")).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result[role] = {table: tuple(connection.execute(f"SELECT * FROM {table} ORDER BY 1")) for table in tables}
        finally:
            connection.close()
    return result


def assert_belief_models(store):
    ledger = open_ledger(store)
    ledger.verify()
    for entry in ledger.entries():
        if entry.body_type is Prediction:
            ref = ledger.record(entry.cid).body.content.as_json()["model"]
            assert model_ref(store.models.get(ref)) == ref
    return ledger


def test_b1_b2_copy_restore_accumulate_and_keep_discarded_content(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    with _storage(source) as src:
        rig = _stored_rig(src)
        for _ in range(5):
            step = _stored_step(rig)
        assert sync(source, target) == SyncReport(len(rig.ledger.entries()), 1)
        with SqliteStore.open(target, readonly=True) as dst:
            ledger = open_ledger(dst)
            ledger.verify()
            assert graph(ledger) == graph(rig.ledger)
            assert rows(src) == rows(dst)
            cid = ledger.entries_of(step.belief.id)[0].cid
            assert _full_state(restore(dst, ledger, cid)) == _full_state(rig.agent)
        before = len(rig.ledger.entries())
        for _ in range(3):
            _stored_step(rig)
        assert sync(source, target) == SyncReport(len(rig.ledger.entries()) - before, 0)
        removed = rig.ledger.entries_of(step.observed.id)[0].seal
        original = src.contents.get(removed)
        assert src.contents.discard(removed)
        assert sync(source, target) == SyncReport(0, 0)
        assert sync(source, target) == SyncReport(0, 0)
        with SqliteStore.open(target, readonly=True) as dst:
            ledger = assert_belief_models(dst)
            assert graph(ledger) == graph(rig.ledger)
            assert dst.contents.get(removed) == original


def test_b3_source_is_readonly_and_unchanged(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    with _storage(source) as src:
        rig = _stored_rig(src)
        _stored_step(rig)
        before = all_rows(source)
        sync(source, target)
        assert all_rows(source) == before
    before_bytes = file_bytes(source)
    original = SqliteStore.open
    opened = []
    def tracked(directory, **kwargs):
        opened.append((Path(directory), kwargs))
        return original(directory, **kwargs)
    monkeypatch.setattr(SqliteStore, "open", tracked)
    sync(source, target)
    assert opened[0] == (source, {"readonly": True})
    assert all_rows(source) == before
    assert file_bytes(source) == before_bytes


def test_b4_sync_between_steps_does_not_change_subject(tmp_path):
    source, control, target = (tmp_path / name for name in ("source", "control", "target"))
    with _storage(source) as a, _storage(control) as b:
        rig, reference = _stored_rig(a), _stored_rig(b)
        for _ in range(10):
            assert _stored_step(rig) == _stored_step(reference)
            sync(source, target)
        assert _full_state(rig.agent) == _full_state(reference.agent)
        assert all_rows(source) == all_rows(control)


class AfterLoad:
    def __init__(self, delegate, callback):
        self.delegate, self.callback = delegate, callback

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def load(self):
        result = self.delegate.load()
        self.callback()
        return result


class AfterRefs:
    def __init__(self, delegate, callback):
        self.delegate, self.callback = delegate, callback

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def refs(self):
        result = self.delegate.refs()
        self.callback()
        return result


@pytest.mark.parametrize("boundary", ["load", "refs"])
def test_b6_graph_is_fixed_before_models_are_enumerated(tmp_path, monkeypatch, boundary):
    source, target = tmp_path / "source", tmp_path / "target"
    original = SqliteStore.open
    with _storage(source) as writer:
        rig = _stored_rig(writer)
        _stored_step(rig)
        injected = []
        def insert_new_model_and_belief():
            if injected:
                return
            model = _model(gamma=32.0)
            writer.models.put(model)
            subject = Agent(model=model, lineage="new-model")
            record = subject.belief_record(clock=FakeClock(run=Ref(K.RUN, "new-model")),
                                           ids=SequentialIds("new-model"), ledger=rig.ledger)
            injected.append(rig.ledger.entries_of(record.id)[0].cid)
        def hooked(directory, **kwargs):
            store = original(directory, **kwargs)
            if Path(directory) == source:
                assert kwargs == {"readonly": True}
                if boundary == "load":
                    store.entries = AfterLoad(store.entries, insert_new_model_and_belief)
                else:
                    store.models = AfterRefs(store.models, insert_new_model_and_belief)
            return store
        monkeypatch.setattr(SqliteStore, "open", hooked)
        sync(source, target)
        assert len(injected) == 1
        with original(target, readonly=True) as dst:
            ledger = assert_belief_models(dst)
            assert injected[0] not in graph(ledger)
        sync(source, target)
        with original(target, readonly=True) as dst:
            ledger = assert_belief_models(dst)
            assert injected[0] in graph(ledger)


def test_b6_every_target_write_boundary_keeps_models_before_beliefs(tmp_path, monkeypatch):
    source = tmp_path / "source"
    with _storage(source) as src:
        rig = _stored_rig(src)
        for _ in range(2):
            _stored_step(rig)
    original = SqliteStore.open
    active = WriteCounter()
    def hooked(directory, **kwargs):
        store = original(directory, **kwargs)
        if Path(directory) != source:
            wrapped = wrap(store, active)
            store.entries, store.contents, store.models = wrapped.entries, wrapped.contents, wrapped.models
        return store
    monkeypatch.setattr(SqliteStore, "open", hooked)
    sync(source, tmp_path / "baseline")
    total = len(active.calls)
    assert total == 23  # 1 model + 11 records * (put + add)
    for after in (False, True):
        for k in range(1, total + 1):
            active = WriteCounter(k, after)
            target = tmp_path / f"crash-{after}-{k}"
            with pytest.raises(Crash):
                sync(source, target)
            with original(target, readonly=True) as dst:
                assert_belief_models(dst)


def test_b7_corrupt_later_content_does_not_copy_earlier_points(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    with _storage(source) as src:
        rig = _stored_rig(src)
        for _ in range(2):
            _stored_step(rig)
        observations = [e for e in rig.ledger.entries() if e.body_type is Observed]
        assert len(observations) == 2
        later = observations[-1]
    connection = sqlite3.connect(source / "contents.sqlite")
    try:
        connection.execute("UPDATE contents SET data=? WHERE seal=?",
                           (Payload.json({"outcome": "tampered"}).data, later.seal))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(CorruptEntry, match=later.cid):
        sync(source, target)
    with SqliteStore.open(target, readonly=True) as dst:
        assert dst.entries.load() == ()
        assert dst.contents.seals() == frozenset()
