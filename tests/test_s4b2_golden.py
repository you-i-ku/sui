"""Golden input, import-isolation and public rejection regression checks.

These validate the ten recipes, their raw records, and --source selection.
Public rejection tests adopt/plan/decide and check the unchanged ledger.
All five existing baselines are checked, including save/restore/replay, without
collecting or changing a baseline.
Temporary fake packages are under pytest's external --basetemp.
"""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType

import pytest

from sui.model import model_from_json, model_json
from sui.records import AttemptStarted, JobOpened, Observed, Preference
from sui.s4_contracts import BOOT


SCRIPT = Path(__file__).resolve().parents[1]/"tools"/"s4b2_golden.py"
spec = importlib.util.spec_from_file_location("s4b2_golden_inputs", SCRIPT)
golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(golden)


def test_ten_builtin_scenarios_have_the_required_distinct_inputs():
    rows = {row["name"]: row for row in golden.scenarios()}
    assert tuple(rows) == ("known_laws", "learned_B_Theta", "reservation", "incomplete",
        "unexplained", "outside_evaluation", "all_forbidden", "noncanonical",
        "unknown_version", "synchronous_refusal")
    assert [name for name, row in rows.items() if not row["expected_errors"]] == [
        "known_laws", "learned_B_Theta", "reservation"]
    known, learned = rows["known_laws"]["model"], rows["learned_B_Theta"]["model"]
    assert known["effects"]["a"]["B"]["kind"] == "known" and known["learnable"] == []
    assert learned["effects"]["a"]["B"] == {
        "kind": "dirichlet", "values": [[[1, 1], [1, 1]], [[1, 1], [1, 1]]]}
    assert learned["learnable"] == ["a"]
    assert learned["a"]["a"] == [[[1, 1], [1, 1]], [[1, 1], [1, 1]]]
    assert rows["reservation"]["model"]["choices"]["a"]["reservation"] == {
        "kind": "offset", "offset_ns": golden.NS//4}
    assert rows["incomplete"]["model"]["effects"]["a"]["family"] == {
        "name": "response-wait", "version": "1"}
    assert rows["unexplained"]["impossible_report"] is True
    assert rows["outside_evaluation"]["H_ns"] == golden.NS
    assert rows["outside_evaluation"]["model"]["work"]["a"]["points"] == [[0, [1, 1]]]
    assert rows["all_forbidden"]["items"][0]["args"] == {
        "feature": {"name": "outcome_multiset", "version": "1"},
        "probs": [[[["a", "1"]], 1.0]]}
    assert rows["synchronous_refusal"]["operation"] == "decide"


REJECTIONS = {
    "incomplete": ("ActionIncomplete", "continuous_branches"),
    "unexplained": ("ActionModelFalsified", "zero_evidence"),
    "outside_evaluation": ("ActionOutsideEvaluationType", "certain_zero_repetition"),
    "all_forbidden": ("ActionNoAdmissibleCandidate", "all_forbidden"),
    "noncanonical": ("ActionInputError", "noncanonical"),
    "unknown_version": ("ActionInputError", "unknown_version"),
    "synchronous_refusal": ("ActionIncomplete", "algorithm_unavailable"),
}


def test_mappingproxy_canonical_encoding_preserves_nested_content():
    original = {"inputs": [MappingProxyType({"after": ("cid",), "reading": 0})]}
    assert golden.canonical(original) == b'{"inputs":[{"after":["cid"],"reading":0}]}'
    with pytest.raises(TypeError):
        golden.canonical({"unsupported": object()})


@pytest.mark.parametrize("name", REJECTIONS)
def test_public_failure_category_and_reason_are_exact_and_ledger_is_unchanged(name):
    from sui import action_types
    from sui.agent import plan
    from sui.lookahead import OutsideEvaluationType
    recipe = next(r for r in golden.scenarios() if r["name"] == name)
    error_name, reason = REJECTIONS[name]
    assert recipe["expected_errors"] == [error_name]
    assert recipe["expected_reasons"] == [reason]
    expected = getattr(action_types, error_name)
    if name == "outside_evaluation":
        assert issubclass(expected, OutsideEvaluationType)
    raw = golden.canonical(recipe["model"])
    if recipe["operation"] == "load":
        with pytest.raises(expected) as caught:
            model_from_json(b" "+raw if name == "noncanonical" else raw)
    else:
        model = model_from_json(raw)
        agent, view, ledger, clock, ids = golden.build_root(recipe, model)
        before = golden.ledger_bytes(ledger)
        with pytest.raises(expected) as caught:
            if recipe["operation"] == "decide":
                agent.decide(recipe["candidates"], u=recipe["u"], clock=clock, ids=ids,
                    ledger=ledger, now_mono_ns=clock.mono_ns(),
                    observed_mono_ns=view.observed_ns, check_events=view.check_events)
            else:
                plan(view, recipe["candidates"], u=recipe["u"])
        assert golden.ledger_bytes(ledger) == before
    assert type(caught.value) is expected and caught.value.reason == reason
    assert golden.rejection(recipe, caught.value)["reason"] == reason


@pytest.mark.parametrize("name", ("outside_evaluation", "all_forbidden"))
def test_corrected_failure_inputs_have_successful_positive_controls(name):
    from sui.agent import plan
    recipe = deepcopy(next(r for r in golden.scenarios() if r["name"] == name))
    if name == "outside_evaluation":
        recipe["model"]["work"]["a"]["points"] = [[golden.NS, [1, 1]]]
    else:
        # Now the sole observed multiset is the row which the table permits.
        recipe["model"]["a"]["a"] = golden.table([[0, 0], [1, 1]])
    _, view, ledger, _, _ = golden.build_root(recipe, model_from_json(golden.canonical(recipe["model"])))
    before = golden.ledger_bytes(ledger)
    draft = plan(view, recipe["candidates"], u=recipe["u"])
    assert draft.contract.name == "sui.s4b.action_decision"
    assert draft.content.as_json()["intent"]["choice"] == "a"
    assert golden.ledger_bytes(ledger) == before


@pytest.mark.parametrize("recipe", golden.scenarios(), ids=lambda row: row["name"])
def test_builtin_model_and_raw_records_construct_without_evaluation(recipe):
    raw = golden.canonical(recipe["model"])
    if recipe["name"] == "noncanonical":
        raw = b" "+raw
    if recipe["operation"] == "load":
        with pytest.raises(ValueError) as caught:
            model_from_json(raw)
        result = golden.rejection(recipe, caught.value)
        assert result["reason"] == {"noncanonical": "noncanonical",
                                    "unknown_version": "unknown_version"}[recipe["name"]]
        return
    model = model_from_json(raw)
    assert model_json(model) == raw
    ledger, clock, _, witness = golden.build_inputs(recipe, model)
    records = tuple(ledger.record(entry.cid) for entry in ledger.entries())
    assert len({record.id for record in records}) == len(records)
    assert records[0].body.contract == BOOT
    assert records[0].body.content.as_json() == {}
    preferences = tuple(r.body.content.as_json() for r in records if isinstance(r.body, Preference))
    assert preferences == (*recipe["items"], {"kind": "style", "H_ns": recipe["H_ns"], "gamma": 1.0})
    if recipe["impossible_report"]:
        job, = (r for r in records if isinstance(r.body, JobOpened))
        attempt, = (r for r in records if isinstance(r.body, AttemptStarted))
        assert attempt.body.job == job.id and witness.body.caused_by == attempt.id
        assert witness.body.content.as_json() == {"outcome": "1", "effect_notice": None,
            "measurement_reading_ns": golden.NS, "completion_reading_ns": golden.NS}
        assert witness.body.source_id == "impossible-1"
        assert clock.mono_ns() == golden.NS
    else:
        assert tuple(r for r in records if isinstance(r.body, Observed)) == (witness,)
        assert clock.mono_ns() == 0


def test_source_isolation_imports_selected_package_and_writes_no_bytecode(tmp_path):
    source = tmp_path/"isolated"/"src"
    package = source/"sui"
    package.mkdir(parents=True)
    (package/"__init__.py").write_text("", encoding="utf-8")
    (package/"model.py").write_text("SENTINEL = 'isolated-source'\n", encoding="utf-8")
    assert golden.select_source(source.parent, capture=True) == source.resolve()
    before = golden.source_manifest(source)
    # A fresh interpreter avoids already imported project modules. No capture
    # entry is invoked, and the substitute source has no numerical implementation.
    code = "\n".join([
        "import sys; from pathlib import Path",
        "sys.path.insert(0, sys.argv[1])",
        "import s4b2_golden as golden",
        "golden.load_source(Path(sys.argv[2]))",
        "import sui.model",
        "assert sui.model.SENTINEL == 'isolated-source'",
        "golden.assert_source(Path(sys.argv[2]))",
    ])
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", code,
        str(SCRIPT.parent), str(source)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert golden.source_manifest(source) == before
    assert not list(source.rglob("*.pyc"))
    with pytest.raises(RuntimeError, match="mixed sui source"):
        golden.assert_source(source)  # This test process has the real source loaded.


def test_capture_source_must_be_outside_working_tree():
    with pytest.raises(ValueError, match="isolated pre-change source"):
        golden.select_source(SCRIPT.parents[1], capture=True)
    assert golden.select_source(SCRIPT.parents[1], capture=False) == SCRIPT.parents[1]/"src"


@pytest.mark.parametrize("name", ["s4b1a", "s4b1b", "s4b1c", "s4b_action", "s4b2"])
def test_R07_M36_all_five_legacy_golden_checks(name):
    """Existing captured bytes and midpoint decisions must remain unchanged."""
    script = SCRIPT.with_name(name+"_golden.py")
    args = [sys.executable, "-B", str(script), "--check",
            str(SCRIPT.parents[1]/"tests"/("golden_"+name+".json"))]
    if name == "s4b1c":
        # Markdown is not distributed. Compare all captured scene bytes and
        # implemented postconditions through the public API; provenance and
        # dependency-file hashes remain the separate tool CLI's responsibility.
        code = "\n".join([
            "import json, sys; from pathlib import Path",
            "sys.path.insert(0, sys.argv[1])",
            "from s4b1c_golden import build_scenes, compare",
            "baseline = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))",
            "compare(baseline, build_scenes(), implemented=True)",
        ])
        args = [sys.executable, "-B", "-c", code, str(SCRIPT.parent), args[-1]]
    if name == "s4b2":
        args.extend(["--source", str(SCRIPT.parents[1]/"src")])
    env = {**os.environ, "PYTHONPATH": str(SCRIPT.parents[1]/"src"), "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(args, env=env, cwd=SCRIPT.parents[1],
        capture_output=True, text=True, encoding="utf-8", check=False)
    assert completed.returncode == 0, completed.stdout+completed.stderr
