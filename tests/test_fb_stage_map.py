"""FBS0-01 structural checks; policy bookkeeping is not row-level execution."""

from copy import deepcopy

import pytest

from fb_targets import TARGETS
from fb_stage_map import STAGE_MAP, STAGE_BY_ID, STAGES, WORK_USES, SOURCE_ID_SHA256, audit, allocate, EXACT_POLICY


def test_original_ids_exactly_once():
    from hashlib import sha256
    assert len(TARGETS) == len(STAGE_MAP) == len(STAGE_BY_ID) == 3729
    assert sha256("\n".join(r["id"] for r in TARGETS).encode()).hexdigest() == SOURCE_ID_SHA256
    assert {r["id"] for r in TARGETS} == set(STAGE_BY_ID)
    assert audit(STAGE_MAP) == []


def test_eight_uses_and_six_entries_are_not_collapsed():
    row = STAGE_BY_ID["T.descriptor"]
    uses = {u["use"]: u["stages"] for u in row["required_uses"]}
    assert set(WORK_USES) <= uses.keys()
    assert {"I-1", "I-2", "I-3", "I-6", "I-7", "I-8"} <= uses.keys()
    for use, stage in WORK_USES.items():
        assert stage in uses[use]


def test_stage1_owns_origin_and_qgen_not_only_wg_row():
    for rid in ("T.origin", "T.qgen", "T.initial"):
        row = STAGE_BY_ID[rid]
        assert row["owner_stage"] == "1"
        assert "1" in row["required_stages"]
        assert "2" in row["required_stages"]


def test_contract_na_does_not_imply_outside_scope():
    candidates = [r for r in TARGETS if r["contract"].startswith("適用外")]
    assert candidates
    assert any(STAGE_BY_ID[r["id"]]["owner_stage"] != "範囲外" for r in candidates)
    assert STAGE_BY_ID["T.fwork"]["owner_stage"] == "1"


@pytest.mark.parametrize("mutation,expected", [
    ("missing", "missing:"), ("duplicate", "duplicate:"), ("unknown", "unknown:"),
    ("missing_use", "missing-use:"), ("missing_stage", "stages:"),
    ("destination", "destination:"), ("outside_basis", "basis:"),
    ("verification", "verification:"), ("contrast", "contrast:"),
    ("early_close", "close:"), ("duplicate_use", "duplicate-use:"),
    ("unknown_stage", "stages:"), ("unknown_policy", "unknown-policy:"),
    ("owner_policy", "owner-policy:"), ("original_obligation", "original-obligation:"),
    ("deferred", "deferred:"), ("unknown_use", "unknown-use:"),
    ("stage1_binding", "stage1-connection:"), ("stage1_focus", "stage1-focus:"),
])
def test_audit_detects_fault_and_accepts_nearest_legal(mutation, expected):
    assert audit(STAGE_MAP) == []
    rows = deepcopy(STAGE_MAP)
    if mutation == "missing":
        rows = rows[1:]
    elif mutation == "duplicate":
        rows += (deepcopy(rows[0]),)
    elif mutation == "unknown":
        rows[0]["id"] = "T.not_in_denominator"
    elif mutation == "missing_use":
        rows[0]["required_uses"] = rows[0]["required_uses"][1:]
    elif mutation == "missing_stage":
        rows[0]["required_stages"] = ("1",)
    elif mutation == "destination":
        next(r for r in rows if r["owner_stage"] == "範囲外")["destination"] = None
    elif mutation == "outside_basis":
        next(r for r in rows if r["owner_stage"] == "範囲外")["scope_basis"] = ()
    elif mutation == "verification":
        rows[0]["verification_refs"] = ()
    elif mutation == "contrast":
        rows[0]["required_uses"][0]["negative"] = ""
    elif mutation == "early_close":
        rows[0]["close_stage"] = "1"
    elif mutation == "duplicate_use":
        rows[0]["required_uses"] += (deepcopy(rows[0]["required_uses"][0]),)
    elif mutation == "unknown_stage":
        rows[0]["required_uses"][0]["stages"] += ("unknown",)
    elif mutation == "unknown_policy":
        rows[0]["policy"] = "unknown"
    elif mutation == "owner_policy":
        rows[0]["owner_stage"] = "2"
    elif mutation == "original_obligation":
        rows[0]["required_uses"][0]["negative"] = "a different obligation"
    elif mutation == "deferred":
        next(r for r in rows if r["policy"] == "predicate_extension")["deferred_obligation"] = None
    elif mutation == "unknown_use":
        extra = deepcopy(rows[0]["required_uses"][0])
        extra["use"] = "not_a_declared_use"
        rows[0]["required_uses"] += (extra,)
    elif mutation == "stage1_binding":
        rows[0]["stage1_binding"] = None
    elif mutation == "stage1_focus":
        rows[0]["stage1_binding"]["negative"] = "different focus"
    assert any(error.startswith(expected) for error in audit(rows))


def test_each_assignment_has_one_owner_and_a_close_stage():
    for row in STAGE_MAP:
        assert isinstance(row["owner_stage"], str) and row["owner_stage"] in STAGES
        assert row["close_stage"] in row["required_stages"]
        assert row["verification_refs"]
        assert row["original_sources"]


def test_explicit_policy_review_is_separate_from_execution():
    pending = [r["id"] for r in STAGE_MAP if r["review_required"]]
    assert not pending, (
        "FBS0-01 未完: 構造割当と用途の個別確認は別。紙/論理表/公開型の広い仮割当 "
        f"{len(pending)} 行に要行別確認が残る。先頭: {pending[:8]}"
    )
    assert {r["review_level"] for r in STAGE_MAP} == {"explicit_policy_and_exceptions"}
    assert {r["execution"] for r in STAGE_MAP} == {"not_run"}


def test_existing_measurement_contracts_are_not_external_extensions():
    for rid in ("T.measurement_requested", "T.measurement_job"):
        row = STAGE_BY_ID[rid]
        assert row["owner_stage"] == "1"
        assert set(row["required_stages"]) == {"1", "2", "3"}
        assert row["policy"] == "legacy"


def test_47_unadopted_predicate_rows_have_individual_deferred_obligations():
    rows = [r for r in STAGE_MAP if r["policy"] == "predicate_extension"]
    assert len(rows) == 47
    originals = {r["id"]: r for r in TARGETS}
    for row in rows:
        original = originals[row["id"]]
        assert original["status"] == "未採用" and original["consumer"] == "I-5"
        assert row["owner_stage"] == "範囲外"
        for field in ("subject", "field", "branch", "use", "negative", "nearest_legal"):
            assert row["deferred_obligation"][field] == original[field]
        assert row["scope_basis"] and row["destination"]


def test_run_exclusion_is_explicit_not_a_codec_pass():
    rows = [r for r in STAGE_MAP if r["policy"] == "run_extension"]
    assert len(rows) == 12
    assert all(r["owner_stage"] == "範囲外" and r["execution"] == "not_run" for r in rows)


def test_allocation_counts_after_the_47_and_12_existing_scope_decisions():
    from collections import Counter
    assert Counter(row["owner_stage"] for row in STAGE_MAP) == {
        "1": 1264, "2": 1556, "3": 777, "D7の後": 1, "範囲外": 131}
    assert sum("1" in row["required_stages"] for row in STAGE_MAP) == 1264


def test_public_declaration_dependency_review_inventory():
    """R05: aliases actually present in TARGETS; no phantom JSON/Point row."""
    aliases = [r for r in TARGETS if r["id"].startswith("T.decl.alias.")]
    stage1 = {"T.decl.alias.CapabilityKind@661", "T.decl.alias.CapabilityKind@661.branch.6",
              "T.decl.alias.CapabilityKind@661.branch.9", "T.decl.alias.CapabilityKind@661.branch.15"}
    assert {r["id"] for r in aliases if "1" in STAGE_BY_ID[r["id"]]["required_stages"]} == stage1
    # Remaining alias families describe NoDecision or FMath call/claim unions
    # consumed in stages 2/3, not Need, measurement or Qgen declaration input.
    assert {r["subject"] for r in aliases if r["id"] not in stage1} == {
        "CapabilityKind", "NoDecisionReason", "FMathInput", "FMathInputV1", "FMathCallArgs",
        "FMathOp", "FMathCallArgsV1", "FMathOpV1", "FMathCallV1", "FMathClaim", "FMathClaimV1",
        "FMathInputV2", "FMathOpV2", "FMathCallArgsV2", "FMathClaimV2"}
    for name in ("CapabilityDeclaration", "CapabilityImplementation", "CapabilityCallable", "CapabilityContext", "FRegistry"):
        rows = [r for r in TARGETS if r["id"].startswith("T.public." + name + ".") or r["id"] == "T.public." + name]
        assert rows, name
        assert all("1" in STAGE_BY_ID[r["id"]]["required_stages"] for r in rows), name
    import os
    if os.environ.get("FB_STAGE0_INVENTORY"):
        print("\nDECL_REVIEW " + repr({"added_stage1": sorted(stage1), "alias_rows_reviewed": len(aliases)}))


@pytest.mark.parametrize("rid,branch", [
    ("T.decl.alias.CapabilityKind@661", None),
    ("T.decl.alias.CapabilityKind@661.branch.6", "method"),
    ("T.decl.alias.CapabilityKind@661.branch.9", "measurement"),
    ("T.decl.alias.CapabilityKind@661.branch.15", "generator"),
    ("T.public.CapabilityDeclaration", None), ("T.public.MeasurementFrame", None),
])
def test_semantic_audit_detects_coherently_wrong_policy(monkeypatch, rid, branch):
    """R05: change allocation AND policy together; independent paper guard fires."""
    original = next(row for row in TARGETS if row["id"] == rid)
    if branch is not None:
        assert original["branch"] == repr(branch)
    assert audit(STAGE_MAP) == []
    monkeypatch.setitem(EXACT_POLICY, rid, "review_math")
    rows = tuple(allocate(row) for row in TARGETS)
    assert "1" not in next(row for row in rows if row["id"] == rid)["required_stages"]
    assert audit(rows) == ["semantic-stage1:" + rid]
