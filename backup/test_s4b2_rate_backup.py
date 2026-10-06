"""S4b2 T14 backup roundtrip, outside tests/ to preserve C3 independence."""
from pathlib import Path


def test_T14_store_and_backup_preserve_model_bytes_facts_posterior_and_replay(tmp_path, monkeypatch):
    # backup/conftest.py makes the public test helpers available.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/"backup"))
    from test_s4b2_integration import INJECTED, ledger_image, posterior, saved, verify
    from s4b2_worlds import NS
    from sui.agent import Agent
    from sui.ledger import Ledger, SequentialSalts
    from sui.model import model_json, model_ref
    from sui.store import MemoryModels, SqliteStore
    from sui_backup import SyncReport, sync

    f = saved()
    w = f.w
    expected, original = ledger_image(w.ledger), posterior(f)
    memory = MemoryModels()
    assert memory.put(f.model) == model_ref(f.model)
    assert model_json(memory.get(model_ref(f.model))) == w.declaration
    source, target = tmp_path/"source", tmp_path/"backup"
    with SqliteStore.open(source, create=True) as store:
        ref = store.models.put(f.model)
        for entry in w.ledger.entries():
            salt, payload = w.ledger.contents.get(entry.seal)
            store.contents.put(entry.seal, salt, payload)
            store.entries.add(entry.cid, entry.header)
    assert sync(source, target) == SyncReport(len(expected), 1)
    assert sync(source, target) == SyncReport(0, 0)
    for path in (source, target):
        with SqliteStore.open(path, readonly=True) as store:
            ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
            ledger.verify()
            assert ledger_image(ledger) == expected
            model = store.models.get(ref)
            assert model_json(model) == w.declaration and model_ref(model) == model_ref(f.model)
            restored = Agent.restore(model=model, lineage="backup", ledger=ledger,
                belief=ledger.entries_of(f.belief.id)[0].cid, rate_budget=INJECTED)
            view = restored.view(now_ns=NS, observed_ns=NS, check_events=f.view.check_events)
            assert posterior(f, view.reading) == original
            assert verify(f, ledger=ledger) == f.draft
