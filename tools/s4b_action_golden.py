"""S4b v0.19 §6-1: model.7 pre-implementation compatibility capture.

Capture must import sui from the clean 2a5a6b6 worktree through PYTHONPATH.
--check uses the caller's PYTHONPATH and never updates a golden. Every success
passes prepare/commit, SQLite save/reopen, public restore and replay. Existing
1a/1b/1c golden files are only hashed, never regenerated. This is a regression
baseline, not an independent mathematical oracle. No source bodies are read.
"""
from __future__ import annotations

import argparse
from fractions import Fraction as F
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = Path("C:/Users/you11/Desktop/iku/sui_base_2a5a6b6")
COMMIT = "2a5a6b681b0f1bc64154d176b2ebe797ce41fdcc"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={BASE.as_posix()}",
                                    "-C", str(BASE), *args]).decode().strip()


def provenance():
    files = [Path(__file__), ROOT / "tests/worlds.py", ROOT / "tests/test_lookahead.py",
             ROOT / "pyproject.toml", ROOT / "specs/S4b_行動が状態を変える.md"]
    frozen = [ROOT / f"tests/golden_s4b1{x}.json" for x in "abc"]
    tracked = git("ls-files", "src").splitlines()
    return {"base_commit": COMMIT, "base_source": str(BASE / "src"),
            "python": platform.python_version(),
            "dependencies": {name: importlib.metadata.version(name)
                             for name in ("numpy", "scipy", "pytest")},
            "script_and_input_files_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes())
                                               for p in files},
            "existing_golden_sha256": {str(p.relative_to(ROOT)): digest(p.read_bytes())
                                       for p in frozen},
            "base_src_sha256": {p: digest((BASE / p).read_bytes()) for p in tracked}}


def capture_rows():
    import numpy as np
    from sui.agent import Agent, plan, replay_decision
    from sui.ledger import Ledger, SequentialSalts
    from sui.model import ProgressModel, model_json, model_from_json, model_ref
    from sui.progress import CompletionSpec
    from sui.quantity import BaseSpec, DurationPrior
    from sui.store import SqliteStore
    # Only allowed existing tests; helpers build public records/model inputs.
    sys.path.insert(0, str(ROOT / "tests"))
    from worlds import HandHistory
    from test_lookahead import _rig

    ns = 1_000_000_000
    completion = CompletionSpec(name="progress", version="1", actions=("a", "b"),
        states=("0", "1"), work_unit="ns", time_unit="ns", speed_unit="ns/ns",
        candidates=(((F(1), F(1)), (F(1), F(1))),), weights=(F(1),),
        share="all_actions", max_speed=F(1))

    def make_model(learned):
        return ProgressModel(states=("0", "1"), outcomes=("0", "1"), actions=("a", "b"),
            a={"a": np.ones((2, 2)) if learned else np.eye(2), "b": np.eye(2)},
            learnable=frozenset({"a"}) if learned else frozenset(), D=np.array([1., 0.]),
            Q=np.array([[-math.log(2), 0.], [math.log(2), 0.]]), log_C=np.log([.5, .5]),
            gamma=1., completion=completion,
            work_priors={"a": DurationPrior(2., BaseSpec("atoms", "1", {"points": [[ns, .5], [2*ns, .5]]})),
                         "b": DurationPrior(3., BaseSpec("atoms", "1", {"points": [[ns, 1.]]}))},
            measure={"share": "all_actions", "candidates": [
                {"name": "exact", "version": "1", "params": {}, "weight": 1.}]},
            measures={"a": "report", "b": "report"})

    def ledger_bytes(ledger):
        rows = []
        for e in ledger.entries():
            salt, payload = ledger.contents.get(e.seal)
            rows.append({"cid": e.cid, "header_hex": e.header.hex(),
                         "salt_hex": salt.hex(), "payload_hex": payload.data.hex(),
                         "payload_media_type": payload.media_type})
        return rows

    successes = {}
    for name, learned, complete, horizon in (
        ("known_empty_H1", False, False, ns),
        ("learned_empty_H2", True, False, 2*ns),
        ("known_complete_H1", False, True, ns),
    ):
        h = HandHistory(run="s4b-action-baseline", wall=100)
        h.boot()
        if complete:
            h.observe(h.start("a", 0), "1", 1)
        r = _rig(model=make_model(learned), history=h, H=horizon)
        now = ns if complete else 0
        view = r.agent.view(now_ns=now, observed_ns=now,
                            check_events=({"fact": str(h.records[-1].id)},))
        belief_entry, = r.ledger.entries_of(view.belief)
        belief_content = r.ledger.record(belief_entry.cid).body.content.data
        encoded = model_json(r.model)
        assert json.loads(encoded)["scheme"] == "sui.model.7"
        assert model_json(model_from_json(encoded)) == encoded
        inputs = {"model_json": encoded.decode(), "ledger": ledger_bytes(r.ledger),
                  "H_ns": horizon, "now_ns": now, "candidates": ["b", "a", "a"], "u": .25,
                  "check_events": [{"fact": str(h.records[-1].id)}]}
        before = ledger_bytes(r.ledger)
        draft = plan(view, ("b", "a", "a"), u=.25)
        assert ledger_bytes(r.ledger) == before
        prepared = r.agent.prepare(draft, clock=r.clock, ids=r.ids)
        assert ledger_bytes(r.ledger) == before
        r.agent.commit(prepared, ledger=r.ledger)
        committed = ledger_bytes(r.ledger)
        r.agent.commit(prepared, ledger=r.ledger)
        assert ledger_bytes(r.ledger) == committed
        decision, = r.ledger.entries_of(prepared.decided.id)
        assert replay_decision(model=r.model, ledger=r.ledger, decision=decision.cid) == draft
        # Temporary files are confined to a new tests/ directory and cleaned up.
        with tempfile.TemporaryDirectory(prefix="s4b_action_golden_", dir=ROOT / "tests") as directory:
            path = Path(directory) / "store"
            with SqliteStore.open(path, create=True) as store:
                ref = store.models.put(r.model)
                for entry in r.ledger.entries():
                    salt, payload = r.ledger.contents.get(entry.seal)
                    store.contents.put(entry.seal, salt, payload)
                    store.entries.add(entry.cid, entry.header)
            with SqliteStore.open(path, readonly=True) as store:
                ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
                model = store.models.get(ref)
                assert model_ref(model) == ref and model_json(model) == encoded
                restored = Agent.restore(model=model, lineage="baseline-restored", ledger=ledger,
                                         belief=belief_entry.cid)
                restored_id = restored.view().belief
                restored_entry, = ledger.entries_of(restored_id)
                assert ledger.record(restored_entry.cid).body.content.data == belief_content
                assert replay_decision(model=model, ledger=ledger, decision=decision.cid) == draft
                assert ledger_bytes(ledger) == committed
                ledger.verify()
        successes[name] = {"input": inputs, "input_sha256": digest(canonical(inputs)),
            "model_json": encoded.decode(), "model_ref": model_ref(r.model),
            "belief_content": belief_content.decode(),
            "decision_content": draft.content.data.decode(),
            "decision_contract": {"name": draft.contract.name, "version": draft.contract.version},
            "persisted_ledger": committed, "roundtrip": True, "restore": True, "replay": True}

    baseline_json = model_json(make_model(False))
    invalid = {}
    mutations = {
        "extra_effects": lambda d: d.update(effects={}),
        "extra_execution": lambda d: d.update(execution={}),
        "unknown_scheme": lambda d: d.update(scheme="sui.model.999"),
        "unknown_completion_version": lambda d: d["completion"].update(version="999"),
        "unknown_measure_version": lambda d: d["measure"]["candidates"][0].update(version="999"),
        "wrong_Q_shape": lambda d: d.update(Q=[[1.]]),
    }
    for name in (*mutations, "noncanonical"):
        data = json.loads(baseline_json)
        if name in mutations:
            mutations[name](data)
            raw = canonical(data)
        else:
            raw = b" " + baseline_json
        try:
            model_from_json(raw)
        except ValueError as error:
            invalid[name] = {"input": raw.decode(), "input_sha256": digest(raw),
                             "exception": type(error).__name__, "message": str(error)}
        else:
            raise AssertionError(f"old invalid model accepted: {name}")
    return {"success": successes, "invalid": invalid}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if bool(args.path) == bool(args.check):
        parser.error("give exactly one capture PATH or --check PATH")
    import sui.model as model_module
    source = Path(model_module.__file__).resolve().parent.parent
    if args.path:
        if args.path.exists():
            raise SystemExit("refusing to overwrite an existing golden")
        if source != (BASE / "src").resolve():
            raise SystemExit(f"capture requires baseline PYTHONPATH; loaded {source}")
        if git("rev-parse", "HEAD") != COMMIT or git("status", "--porcelain", "--", "src"):
            raise SystemExit("baseline commit/source is not clean 2a5a6b6")
    rows = capture_rows()
    if args.check:
        frozen = json.loads(args.check.read_bytes())
        if canonical(rows) != canonical(frozen["pre_implementation"]):
            raise SystemExit("FAIL: model.7 baseline bytes changed")
        print(f"PASS: 3 model.7 successes, 7 rejections, save/restore/replay; source={source}")
    else:
        if canonical(rows) != canonical(capture_rows()):
            raise AssertionError("baseline capture is nondeterministic")
        data = canonical({"schema": "sui.s4b.action.golden.1", "provenance": provenance(),
                          "pre_implementation": rows}) + b"\n"
        with args.path.open("xb") as stream:
            stream.write(data)
        print(f"CREATED {args.path}; sha256={digest(data)}; source={source}")


if __name__ == "__main__":
    main()
