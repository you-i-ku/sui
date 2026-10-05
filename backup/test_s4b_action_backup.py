"""§6-3 backup integration, outside tests/ so the core does not depend on backup."""
from pathlib import Path


def test_model8_backup_preserves_facts_model_and_replay(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "tests"))
    monkeypatch.syspath_prepend(str(root / "backup"))
    from test_s4b_action_integration import host_fixture, run_host, assert_record_chain, records, model_json
    from s4b_action_cases import encoded
    from sui.agent import Agent, replay_decision
    from sui.ledger import Ledger, SequentialSalts
    from sui.model import model_json as serialize_model
    from sui.records import Decided
    from sui.store import SqliteStore
    from sui_backup import sync, SyncReport

    f = host_fixture(monkeypatch)
    run_host(f)
    assert_record_chain(f)
    r = f.r
    belief = r.agent.belief_record(clock=r.clock, ids=r.ids, ledger=r.ledger)
    belief_cid = r.ledger.entries_of(belief.id)[0].cid
    decision, = records(r, Decided)
    decision_cid = r.ledger.entries_of(decision.id)[0].cid
    source, target = tmp_path / "source", tmp_path / "backup"
    expected = {entry.cid: entry.header for entry in r.ledger.entries()}
    with SqliteStore.open(source, create=True) as store:
        ref = store.models.put(r.model)
        for entry in r.ledger.entries():
            salt, payload = r.ledger.contents.get(entry.seal)
            store.contents.put(entry.seal, salt, payload)
            store.entries.add(entry.cid, entry.header)
    assert sync(source, target) == SyncReport(len(expected), 1)
    assert sync(source, target) == SyncReport(0, 0)
    for path in (source, target):
        with SqliteStore.open(path, readonly=True) as store:
            ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
            ledger.verify()
            assert {entry.cid: entry.header for entry in ledger.entries()} == expected
            model = store.models.get(ref)
            assert serialize_model(model) == encoded(model_json())
            for entry in ledger.entries():
                assert ledger.contents.get(entry.seal) == r.ledger.contents.get(entry.seal)
            restored = Agent.restore(model=model, lineage="backup", ledger=ledger, belief=belief_cid)
            assert restored.q.tolist() == [0., 1.]
            assert replay_decision(model=model, ledger=ledger, decision=decision_cid).content == decision.body.content
    assert f.hand.calls == ["a"]  # restore/replay/sync do not dispatch
