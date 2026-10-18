"""FBT のデータの自己点検だけ。一覧が正しいことの証明ではない。

紙の解釈の正しさ、全対象の意味上の網羅、F-a/F-b の動作は検証しない。
参照先の存在、記載した不足、対応漏れ、固定前後の混入だけを点検する。
模型、既存試験、src、仕様ファイルを import/実行/再読しない。

PowerShell:
  $env:PYTHONDONTWRITEBYTECODE='1'
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
  ./.venv/Scripts/python.exe -B -m pytest --noconftest -p no:cacheprovider tests/test_fb_targets.py
"""

from collections import Counter
import ast
import hashlib
from fractions import Fraction
from itertools import combinations, product
import re
import importlib.util
import json
from pathlib import Path


_path = Path(__file__).with_name("fb_targets.py")
_spec = importlib.util.spec_from_file_location("independent_fb_targets", _path)
data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(data)

REQUIRED_COLUMNS = {
    "id", "kind", "subject", "body", "contract", "branch", "field", "role",
    "domain", "run", "owner", "presence", "edges", "use", "evidence",
    "consumer", "rules", "entries", "negative", "nearest_legal",
    "not_applicable_reason", "sources", "status", "issues", "execution",
}
KINDS = {"body", "contract", "branch", "field", "relation"}
STATUSES = {"整理済み", "未対応", "未決", "未採用"}
CHECK_KINDS = {"F-aの実物の値", "固定値", "golden", "変異", "新しい試験"}
EXPECTED_COUNTS = {"scene_b": 107, "mutant_outside": 7, "structural_a": 79}
EXPECTED_OUTSIDE_MUTANTS = {
    "INV-7.b", "INV-9.b", "INV-12.a", "INV-14.a", "INV-14.b",
    "INV-16.a", "INV-16.b",
}


def _unpin_v22(value):
    if isinstance(value, dict):
        result = {k: _unpin_v22(v) for k, v in value.items()}
        if result.get("path") == data.FB22:
            result["path"] = data.FB
        return result
    if isinstance(value, tuple):
        return tuple(_unpin_v22(v) for v in value)
    if isinstance(value, list):
        return [_unpin_v22(v) for v in value]
    return value


def _assert_source(ref):
    assert ref["path"] and ref["read_scope"]
    assert isinstance(ref["first"], int) and ref["first"] > 0
    assert isinstance(ref["last"], int) and ref["last"] >= ref["first"]
    if ref["path"] == data.FB:
        assert ref["last"] <= data.PROVENANCE["spec_lines"]


def test_target_ids_and_required_columns():
    assert len(data.TARGETS) == len(data.TARGET_BY_ID)
    for row in data.TARGETS:
        assert REQUIRED_COLUMNS <= row.keys(), row["id"]
        assert row["kind"] in KINDS
        assert row["status"] in STATUSES
        for key in REQUIRED_COLUMNS - {"issues"}:
            assert row[key] is not None and row[key] != "", (row["id"], key)
            if isinstance(row[key], str):
                assert row[key].strip(), (row["id"], key)
        assert row["rules"] and row["entries"] and row["sources"], row["id"]
        if row["kind"] == "field":
            assert row["field"] != data.NA
        if row["kind"] == "branch":
            assert row["branch"] != data.NA


def test_not_applicable_and_unresolved_cells_are_explicit():
    for row in data.TARGETS:
        for key in ("body", "contract", "branch", "field", "role", "domain",
                    "run", "owner", "presence", "edges", "consumer"):
            value = row[key]
            assert value not in ("?", "TODO", "TBD", "N/A", "-"), (row["id"], key)
            if value == data.NA:
                assert value.startswith("適用外:"), (row["id"], key)
            if value.startswith(("未決:", "未対応:")):
                assert row["status"] in {"未決", "未対応", "未採用"}, row["id"]
        if row["status"] in {"未決", "未対応"}:
            assert row["issues"], row["id"]
        assert set(row["issues"]) <= data.GAPS.keys()
    # 未決/未対応は削除されず、整理済みとは別に数える。
    counts = Counter(row["status"] for row in data.TARGETS)
    assert counts["未決"] > 0 and counts["未対応"] > 0
    assert sum(counts.values()) == len(data.TARGETS)


def test_rule_entry_and_target_references_exist():
    for row in data.TARGETS:
        assert set(row["rules"]) <= data.RULES.keys(), row["id"]
        assert set(row["entries"]) <= data.ENTRY_POINTS.keys(), row["id"]
        assert set(row.get("related_targets", ())) <= data.TARGET_BY_ID.keys(), row["id"]
        for ref in row["sources"]:
            _assert_source(ref)
    for registry in (data.RULES, data.ENTRY_POINTS):
        for key, row in registry.items():
            assert row["id"] == key
            assert row["sources"]
            for ref in row["sources"]:
                _assert_source(ref)
    assert len(data.COMPLETION_CONDITIONS) == 51
    assert set(data.COMPLETION_CONDITIONS) <= data.RULES.keys()


def test_paper_source_units_have_dispositions():
    units = data.SOURCE_ENUMERATION
    assert len(units) == 168
    assert len({unit["id"] for unit in units}) == len(units)
    for unit in units:
        _assert_source(unit["source"])
        assert unit["disposition"] and unit["reason"]
        assert unit["targets"]
        assert set(unit["targets"]) <= data.TARGET_BY_ID.keys(), unit["id"]
    assert {s["section"] for s in data.SECTION_DISPOSITIONS} == {
        "§1", "§2-1", "§2-4-7", "§2-4-8", "§2-4-11", "§3", "§4",
    }
    assert len(data.VOCABULARY) == 36
    assert {r["id"] for r in data.EXTERNAL_ROWS} == {f"R{i}" for i in range(1, 11)}
    assert {r["id"] for r in data.USAGE_ROWS} == {f"B{i}" for i in range(1, 8)}


def test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap():
    criteria = {c["id"]: c for c in data.ACCEPTANCE}
    expected = {f"AC-{prefix}-{i:02}" for prefix in ("FB", "FA") for i in range(1, 6)}
    expected |= {f"AC-SPINE-{i}" for i in range(1, 6)} | {"AC-STAR-01", "AC-STAR-02"}
    assert criteria.keys() == expected
    links = data.ACCEPTANCE_LINKS
    for link in links:
        assert link["acceptance"] in criteria
        assert link["target"] in criteria[link["acceptance"]]["targets"]
        target = data.TARGET_BY_ID[link["target"]]
        assert link["rule"] in target["rules"] and link["rule"] in data.RULES
        assert link["entry"] in target["entries"] and link["entry"] in data.ENTRY_POINTS
        assert link["use"] and link["sources"]
        assert link["execution"] == "not_run"
    for id, criterion in criteria.items():
        associated = [link for link in links if link["acceptance"] == id]
        assert associated or criterion["unconnected"], id
        assert {link["target"] for link in associated} == set(criterion["targets"]), id
        if criterion["unconnected"]:
            assert "紙に規則が無い" in criterion["unconnected"]
            assert criterion["issue"] in data.GAPS
    # 第一稿の未接続5件を記録から消さず、D7の根拠でのみ現在化する。
    assert {c["id"] for c in data.DRAFT1_DENOMINATOR["ACCEPTANCE"] if c["unconnected"]} == {
        "AC-FB-01", "AC-FB-03", "AC-FA-01", "AC-FA-03", "AC-STAR-01",
    }
    assert not any(c["unconnected"] or c["issue"] == "G-03" for c in data.ACCEPTANCE)
    for criterion in data.ACCEPTANCE:
        assert criterion["count_as_pass"] is False
        assert criterion["automated_disposition"]
    star = criteria["AC-STAR-01"]
    assert star["verification_kind"] == "実装後の観察"
    assert "試験の対象外" in star["automated_disposition"]
    assert any(s["path"] == data.FB22 and s["first"] == 22 for s in star["sources"])
    assert all(x["count_as_pass"] is False for x in links)


def test_denominator_was_not_changed_by_the_model_bridge():
    # 元のハッシュも検査する。紙の改訂を模型から分母を作り直す口実にしない。
    old = json.dumps(data.DRAFT1_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(old).hexdigest() == data.DRAFT1_DENOMINATOR_SHA256
    assert data.DRAFT1_DENOMINATOR_SHA256 == "4cbabdea70d8f841f889af9f3e36de3c1d714d415531378994355e1162a71b9e"
    second = json.dumps(data.DRAFT2_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(second).hexdigest() == data.DRAFT2_DENOMINATOR_SHA256
    assert data.DRAFT2_DENOMINATOR_SHA256 == "619d6f73934f39ca71a66fce5187dbc3c133a55b8657c3ffd3ee3b6ab47b85a2"
    third = json.dumps(data.DRAFT3_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(third).hexdigest() == data.DRAFT3_DENOMINATOR_SHA256
    assert data.DRAFT3_DENOMINATOR_SHA256 == "b5dd539a66d405caf89342a68e647a65e979ca5b7a9aa91cb4437e1bcc48cf46"
    fourth = json.dumps(data.DRAFT4_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(fourth).hexdigest() == data.DRAFT4_DENOMINATOR_SHA256
    assert data.DRAFT4_DENOMINATOR_SHA256 == "dddb95fbb0a676110b23202fb407c22792a962a4cfd10cba0f3ffce8f8fc30fd"
    payload = {key: getattr(data, key) for key in data.DENOMINATOR_KEYS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == data.DENOMINATOR_SHA256


def test_bridge_source_universe_independent_counts_and_selectors():
    items = data.BRIDGE_SOURCE_ITEMS
    assert len({(x["group"], x["id"]) for x in items}) == len(items)
    counts = Counter(x["group"] for x in items)
    for group, expected in EXPECTED_COUNTS.items():
        assert counts[group] == expected
        assert data.BRIDGE_EXTRACTION["differences"][group] == 0
    assert {x["id"] for x in items if x["group"] == "mutant_outside"} == EXPECTED_OUTSIDE_MUTANTS
    for x in items:
        _assert_source(x["source"])
        if x["group"] in {"scene_b", "nested_scene_b"}:
            assert x["scope_class"] == "b"
        if x["group"] == "structural_a":
            assert x["scope_class"] == "a"
            assert x["implementation_scope"] == (data.STRUCTURAL_NUMERIC_REMAINDER,)


def test_every_bridge_item_has_exactly_one_disposition():
    expected = {(x["group"], x["id"]) for x in data.BRIDGE_SOURCE_ITEMS}
    actual = Counter((b["group"], b["source_id"]) for b in data.BRIDGES)
    assert set(actual) == expected
    assert set(actual.values()) == {1}
    assert len({b["id"] for b in data.BRIDGES}) == len(data.BRIDGES)
    for bridge in data.BRIDGES:
        assert bridge["disposition"] in {"対応先あり", "消えた"}
        if bridge["disposition"] == "対応先あり":
            assert bridge["targets"] and bridge["verification_kinds"]
            assert set(bridge["targets"]) <= data.TARGET_BY_ID.keys()
            assert set(bridge["verification_kinds"]) <= CHECK_KINDS
            assert bridge["recipes"] and set(bridge["recipes"]) <= data.BRIDGE_RECIPES.keys()
        else:
            assert bridge["disappearance_reason"]
            assert not bridge["disappearance_reason"].startswith("適用外")
        assert bridge["scope_to_preserve"] and bridge["branch_constraint"]
        assert bridge["execution"] == "not_run"
        assert bridge["readiness"] in {"未接続", "未採用"}
        assert set(bridge["prerequisite_issues"]) <= data.GAPS.keys()


def test_numeric_remainders_and_unadopted_branches_not_promoted():
    for bridge in data.BRIDGES:
        if bridge["group"] == "structural_a":
            assert bridge["scope_to_preserve"] == (data.STRUCTURAL_NUMERIC_REMAINDER,)
        if "generation_draw" in bridge["recipes"]:
            assert bridge["readiness"] == "未採用"
            assert "T.external.R10" in bridge["targets"]
        if bridge["group"] == "mutant_outside":
            assert "変異" in bridge["verification_kinds"]
    for recipe in data.BRIDGE_RECIPES.values():
        assert set(recipe["targets"]) <= data.TARGET_BY_ID.keys()
        assert set(recipe["checks"]) <= CHECK_KINDS and recipe["method"]


def test_supplemental_scope_holes_remain_separate_from_107_7_79():
    extra = {x["id"] for x in data.BRIDGE_SOURCE_ITEMS if x["group"] not in EXPECTED_COUNTS}
    assert extra == {"SC-04-publish-PR-D", "SC-04-publish-DF-Ee",
                     "SC-14-M3-Hung-D-cap1", "SC-14-M3-Hung-D-cap2"}


def test_disagreement_is_reported_without_choosing_an_expected_type():
    assert any(d["id"] == "D-01" and d["subject"] == "Instant.wall_ns" for d in data.DRAFT1_DENOMINATOR["MISMATCHES"])
    assert not any(t["field"] == "wall_ns" for t in data.DRAFT1_DENOMINATOR["TARGETS"])
    assert not data.MISMATCHES
    assert {x["id"] for x in data.RESOLVED_MISMATCHES} == {"D-01"}
    wall = data.TARGET_BY_ID["T.wire.type.Instant.field.wall_ns"]
    assert wall["declared_type"] == "int" and wall["status"] == "整理済み"
    assert "非null" in wall["presence"] and wall["domain"] == "U"
    assert any(s["path"] == data.FA and s["first"] == 28 for s in wall["sources"])
    assert any(s["path"] == "src/sui/clock.py" and s["first"] == 18 for s in wall["sources"])
    assert len(data.TRANSFERRED_TEST_NAMES) == 36
    assert sum(not t["targets"] for t in data.TRANSFERRED_TEST_NAMES) == 3
    for item in data.TRANSFERRED_TEST_NAMES:
        assert set(item["targets"]) <= data.TARGET_BY_ID.keys()
        assert item["reason"] and item["status"]


def test_data_module_has_no_model_or_implementation_import():
    tree = ast.parse(_path.read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert len(imports) == 1
    assert isinstance(imports[0], ast.ImportFrom) and imports[0].module == "collections"
    assert all(t["execution"] == "not_run" for t in data.TARGETS)


def test_revision_accounts_for_every_original_affected_row_and_reports_unclosed():
    old = {x["id"]: x for x in data.DRAFT1_DENOMINATOR["TARGETS"]}
    expected = {id for id, row in old.items() if set(row["issues"]) & {"G-02", "G-05", "D-01"}}
    assert len(expected) == 179
    assert set(old) <= data.TARGET_BY_ID.keys()
    actual = {x["target"]: x for x in data.FBT01B_RESOLUTIONS}
    assert set(actual) == expected and len(actual) == len(data.FBT01B_RESOLUTIONS)
    reported = {t for finding in data.V23_FINDINGS for t in finding.get("targets", ())}
    for id, resolution in actual.items():
        current = data.TARGET_BY_ID[id]
        assert resolution["before_status"] == old[id]["status"]
        assert resolution["before_issues"] == tuple(old[id]["issues"])
        assert resolution["after_status"] == current["status"]
        assert set(resolution["remaining_issues"]) == set(current["issues"])
        assert resolution["reason"] and resolution["sources"]
        assert set(resolution["targets"]) <= data.TARGET_BY_ID.keys()
        if current["status"] in {"未決", "未対応"}:
            assert current["issues"]
            assert all(issue in data.GAPS and data.GAPS[issue]["sources"] for issue in current["issues"])
            if set(current["issues"]) <= {"G-02", "G-05", "D-01"}:
                assert id in data.FBT01B_UNCLOSED and id in reported
        else:
            assert resolution["targets"]
            assert not set(current["issues"]) & {"G-02", "G-05", "D-01"}
    # 自己点検通過をFBT-01b完了と取り違えない。残件は消さず報告に出す。
    assert set(data.DRAFT2_FBT01B_UNCLOSED) == {
        "T.old_style", "T.missing.RateBudget", "T.missing.RateBudget.未列挙の欄と枝",
        "T.capability_implementation",
    } | {"T.missing." + name + suffix
         for name in ("Selected", "NoDecision", "FEvaluation", "PredicateWork")
         for suffix in ("", ".未列挙の欄と枝")}
    assert not any("G-02" in r["issues"] for r in data.TARGETS)
    assert not data.FBT01B_UNCLOSED
    assert {id for id in data.DRAFT2_FBT01B_UNCLOSED
            if data.DRAFT3_TARGET_BY_ID[id]["status"] != "整理済み"} == {"T.old_style"}
    assert "T.old_style" in {t for f in data.REVISION3_FINDINGS for t in f.get("targets", ())}
    assert all(data.TARGET_BY_ID[id]["status"] == "整理済み" for id in data.DRAFT2_FBT01B_UNCLOSED)
    assert "T.old_style" not in reported


def test_wire_contract_universe_is_counted_from_paper_and_every_declaration_has_target():
    declared = {(x["category"], x["contract"]) for x in data.WIRE_DECLARED_SOURCE}
    actual = {(x["category"], x["name"] + "/" + x["version"]) for x in data.WIRE_DECLARATIONS}
    assert len(declared) == len(data.WIRE_DECLARED_SOURCE) == 34
    assert actual == declared and len(actual) == len(data.WIRE_DECLARATIONS)
    assert Counter(x["category"] for x in data.WIRE_DECLARED_SOURCE) == {"ledger": 22, "value": 10, "external": 2}
    for declaration in data.WIRE_DECLARATIONS:
        target = data.TARGET_BY_ID[declaration["target"]]
        assert target["contract"] == declaration["name"] + "/" + declaration["version"]
        _assert_source(declaration["source"])
        if declaration["category"] == "ledger":
            assert declaration["body"] in {"Observed", "Decided"}
            assert declaration["role_category"] in {"MEMBRANE / FACT", "MODEL / FACT"}
            assert declaration["parents"] != data.NA
        elif declaration["category"] == "value":
            assert declaration["body"] == declaration["parents"] == data.NA
        else:
            assert target["status"] == "未採用" and target["issues"] == ("G-04",)
    assert len(data.EXISTING_COPIES) == 14
    assert len({x["contract"] for x in data.EXISTING_COPIES}) == 14
    for copy in data.EXISTING_COPIES:
        assert copy["target"] in data.TARGET_BY_ID
        assert copy["payload"] in data.WIRE_TYPES
    bodies = {t["id"] for t in data.TARGETS if t["kind"] == "body"}
    assert len(bodies) == 8
    assert set(data.TARGET_BY_ID[data.FBT04_DISPOSITIONS["no_ninth_body_target"]]["related_targets"]) == bodies


def test_wire_nested_fields_nullable_and_union_branches_are_all_addressable():
    for name, declaration in data.WIRE_TYPES.items():
        prefix = "T.wire.type." + name
        assert declaration["target"] == prefix
        assert len(declaration["field_targets"]) == len(declaration["fields"])
        assert len(declaration["branch_targets"]) == len(declaration["branches"])
        for field, annotation in declaration["fields"]:
            row = data.TARGET_BY_ID[prefix + ".field." + field]
            assert row["declared_type"] == annotation and row["sources"]
            if annotation.startswith("?"):
                assert prefix + ".field." + field + ".branch.null" in data.TARGET_BY_ID
                assert prefix + ".field." + field + ".branch.value" in data.TARGET_BY_ID
        for branch, payload in declaration["branches"]:
            row = data.TARGET_BY_ID[prefix + ".branch." + branch]
            assert row["declared_type"] == payload
            if payload == "◆G-01":
                assert row["status"] == "未決" and row["issues"] == ("G-01",)
        assert set(declaration["type_references"]) <= data.TARGET_BY_ID.keys()
    assert len(data.WIRE_TYPES["Desc<Args>"]["fields"]) == 13
    assert len(data.WIRE_TYPES["SegmentItem"]["branches"]) == 8
    assert len(data.WIRE_TYPES["WaitingPayload"]["fields"]) == 7
    assert len(data.WIRE_TYPES["SegmentBinding"]["fields"]) == 8
    assert {b for b, _ in data.WIRE_TYPES["DrawOutcome"]["branches"]} == {"value", "failure", "unknown"}
    assert dict(data.WIRE_TYPES["Gap"]["fields"])["sequence_range"] == "[first:int,stop:int]"
    assert tuple(f for f, _ in data.WIRE_TYPES["Verification"]["fields"]) == ("request", "report")
    assert tuple(f for f, _ in data.WIRE_TYPES["Selection"]["fields"]) == ("evaluated",)
    assert len(data.WORK_PURPOSE_ARGS) == 8


def test_all_91_logical_rows_and_entire_wire_section_have_dispositions():
    assert len(data.LOGICAL_MAPPING) == 91
    assert Counter(x["group"] for x in data.LOGICAL_MAPPING) == {"E0": 8, "REFERENCE": 39, "CMP": 24, "PATH": 20}
    expected_lines = set(range(2367, 2375)) | set(range(2382, 2421)) | set(range(2428, 2452)) | set(range(2461, 2481))
    assert {x["source"]["first"] for x in data.LOGICAL_MAPPING} == expected_lines
    assert len({x["id"] for x in data.LOGICAL_MAPPING}) == 91
    for mapping in data.LOGICAL_MAPPING:
        assert mapping["target"] in data.TARGET_BY_ID
        assert mapping["targets"] and set(mapping["targets"]) <= data.TARGET_BY_ID.keys()
        assert mapping["disposition"]
    assert {x["line"] for x in data.WIRE_SOURCE_COVERAGE} == set(data.WIRE_SECTION_LINES) == set(range(2005, 2598))
    for unit in data.WIRE_SOURCE_COVERAGE:
        assert unit["reason"]
        assert unit["targets"] or unit["reason"].startswith("適用外:")
        assert set(unit["targets"]) <= data.TARGET_BY_ID.keys()


def test_public_class_declarations_expand_fields_literals_unions_and_keep_unknown_types():
    assert len(data.PUBLIC_CLASS_DECLARATIONS) == data.REVISION2_SPEC["public_classes"] == 134
    assert sum(len(x["fields"]) for x in data.PUBLIC_CLASS_DECLARATIONS) == data.REVISION2_SPEC["public_fields"] == 548
    for declaration in data.PUBLIC_CLASS_DECLARATIONS:
        prefix = "T.public." + declaration["name"]
        assert prefix in data.TARGET_BY_ID
        assert not declaration["name"].startswith("_")
        assert declaration["docstring"]
        root = data.TARGET_BY_ID[prefix]
        assert tuple(root["unresolved_type_closure"]) == data.PUBLIC_CLOSURE_GAPS[declaration["name"]]
        if root["unresolved_type_closure"]:
            assert root["status"] == "未対応" and root["issues"] == ("G-05",)
        for field in declaration["fields"]:
            id = prefix + ".field." + field["name"]
            row = data.TARGET_BY_ID[id]
            assert row["declared_type"] == field["type"]
            assert row["sources"][0]["first"] == field["line"]
            unknown = set(field["references"]) & set(data.PUBLIC_UNRESOLVED_NAMES)
            assert set(row["unresolved_type_references"]) == unknown
            if unknown:
                assert row["status"] == "未対応" and row["issues"] == ("G-05",)
            for index, value in enumerate(field["literal_values"]):
                assert data.TARGET_BY_ID[id + ".literal." + str(index)]["branch"] == repr(value)
    for name, field, unions in data.PUBLIC_ANNOTATION_UNIONS:
        for index, (path, member) in enumerate(unions):
            row = data.TARGET_BY_ID["T.public." + name + ".field." + field + ".union." + str(index)]
            assert row["branch"] == member and path in row["use"]
    for comparison in data.WIRE_PUBLIC_FIELD_COMPARISONS:
        assert comparison["paper_fields"] == comparison["public_fields"], comparison["name"]


def test_d7_connections_are_conditions_and_observation_not_automatic_success():
    criteria = {c["id"]: c for c in data.ACCEPTANCE}
    for id in ("AC-FB-01", "AC-FA-01", "AC-SPINE-1"):
        assert "T.d7.perception" in criteria[id]["targets"]
    for id in ("AC-FB-03", "AC-FA-03", "AC-SPINE-2", "AC-SPINE-3"):
        assert "T.d7.two_starts" in criteria[id]["targets"]
    assert "T.d7.display" in criteria["AC-STAR-01"]["targets"]
    assert {"L-DERIVE", "背骨①"} <= set(data.TARGET_BY_ID["T.d7.perception"]["rules"])
    assert {"INV-2.e", "背骨②"} <= set(data.TARGET_BY_ID["T.d7.two_starts"]["rules"])
    assert data.TARGET_BY_ID["T.d7.display"]["count_as_pass"] is False


def _restore_original_source_positions(value):
    value = _unpin_v22(value)
    if isinstance(value, dict):
        restored = {k: _restore_original_source_positions(v) for k, v in value.items()
                    if k not in {"original_version", "original_first", "original_last", "version"}}
        if value.get("path") == data.FB and "original_first" in value:
            restored["first"], restored["last"] = value["original_first"], value["original_last"]
        return restored
    if isinstance(value, (tuple, list)):
        return tuple(_restore_original_source_positions(x) for x in value)
    return value


def test_revision_preserves_all_bridge_sources_targets_checks_and_remainders():
    assert _restore_original_source_positions(data.BRIDGE_SOURCE_ITEMS) == _restore_original_source_positions(data.DRAFT1_SOURCE_ITEMS)
    assert len(data.BRIDGES) == len(data.DRAFT1_BRIDGES) == 197
    for before, after in zip(data.DRAFT1_BRIDGES, data.BRIDGES):
        assert tuple(before["prerequisite_issues"]) == after["previous_prerequisite_issues"]
        for key in before.keys() - {"prerequisite_issues"}:
            assert _restore_original_source_positions(before[key]) == _restore_original_source_positions(after[key]), (before["id"], key)
        assert after["execution"] == "not_run"


# 追補の点検もデータの自己点検。宣言資料や抽出器の正しさを証明しない。
def _compact_ast_dump(node):
    # 第二稿の指紋はPython 3.14のast.dump（空のoptional欄は省略）で保存。
    # pytestのPython 3.12でも同じ表記へ正規化。検査文の値・順番は落とさない。
    if isinstance(node, ast.AST):
        fields = []
        for name, value in ast.iter_fields(node):
            if value == [] or (value is None and not (isinstance(node, ast.Constant) and name == "value")):
                continue
            fields.append(name + "=" + _compact_ast_dump(value))
        return type(node).__name__ + "(" + ", ".join(fields) + ")"
    if isinstance(node, list):
        return "[" + ", ".join(_compact_ast_dump(item) for item in node) + "]"
    return repr(node)


def test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines():
    functions = {name: ast.parse(text).body[0] for name, text in data.DRAFT4_TEST_SOURCE.items()}
    amended = {"test_denominator_was_not_changed_by_the_model_bridge",
               "test_revision_accounts_for_every_original_affected_row_and_reports_unclosed"}
    assert len(data.DRAFT2_TEST_CHECKS) == 19
    assert data.DRAFT2_TEST_CHECKS.keys() <= functions.keys()
    for name, digest in data.DRAFT2_TEST_CHECKS.items():
        if name not in amended:
            current = _compact_ast_dump(functions[name]).encode()
            assert hashlib.sha256(current).hexdigest() == digest, name
    # 上の2件は旧断言を削らず第二稿へ適用し、現在の閉じる条件の断言を追加。
    assert len(data.DRAFT2_DENOMINATOR["TARGETS"]) == 3047
    assert set(data.DRAFT2_DENOMINATOR) == set(data.DRAFT2_DENOMINATOR_KEYS)
    assert Counter(r["status"] for r in data.DRAFT2_DENOMINATOR["TARGETS"]) == {
        "整理済み": 2728, "未決": 56, "未対応": 147, "未採用": 116,
    }
    assert _unpin_v22(data.ACCEPTANCE) == data.DRAFT2_DENOMINATOR["ACCEPTANCE"]
    assert _unpin_v22(data.ACCEPTANCE_LINKS) == data.DRAFT2_DENOMINATOR["ACCEPTANCE_LINKS"]
    assert len(data.BRIDGES) == len(data.DRAFT2_BRIDGES) == 197
    for before, after in zip(data.DRAFT2_BRIDGES, data.BRIDGES):
        for key in before.keys() - {"prerequisite_issues"}:
            assert before[key] == _unpin_v22(after[key]), (before["id"], key)
        assert "G-05" not in after["prerequisite_issues"]


def test_supplemental_alias_graph_matches_saved_declarations_and_declaration_time_binding():
    nodes = data.SUPPLEMENTAL_NODE_BY_KEY
    assert len(nodes) == len(data.SUPPLEMENTAL_DECLARATION_NODES) == 45
    assert Counter(n["kind"] for n in nodes.values()) == {"class": 29, "alias": 12, "literal": 4}
    for key, node in nodes.items():
        assert key == node["key"]
        raw = data.DECLARATION_EXCERPTS[node["line"]].split(": ", 1)[1]
        assert data.SUPPLEMENTAL_NODE_TARGETS[key] in data.TARGET_BY_ID
        if node["kind"] == "class":
            assert raw == node["header"]
            assert node["name"] in data.PUBLIC_CLASS_BY_NAME
            assert data.PUBLIC_CLASS_BY_NAME[node["name"]]["line"] == node["upstream_line"]
            continue
        declaration = ast.parse(raw).body[0]
        rhs = declaration.value
        assert ast.dump(rhs) == ast.dump(ast.parse(node["rhs"], mode="eval").body)
        root = data.TARGET_BY_ID[data.SUPPLEMENTAL_NODE_TARGETS[key]]
        assert root["declared_type"] == node["rhs"]
        if node["kind"] == "literal":
            assert isinstance(rhs, ast.Subscript) and rhs.value.id == "_Literal"
            values = rhs.slice.elts if isinstance(rhs.slice, ast.Tuple) else [rhs.slice]
            assert tuple(ast.literal_eval(value) for value in values) == node["values"]
            assert not node["references"]
        else:
            names = [n.id for n in ast.walk(rhs) if isinstance(n, ast.Name)]
            # AST walkの順番でなく、各参照名の直前の宣言で固定する。
            expected = set()
            for name in names:
                prior = [n for n in nodes.values() if n["name"] == name and n["line"] < node["line"]]
                assert prior, (key, name)
                expected.add(max(prior, key=lambda n: n["line"])["key"])
            assert set(node["references"]) == expected, key
        leaves = data.SUPPLEMENTAL_ALIAS_BRANCHES[key]
        assert leaves
        actual_leaves = Counter((leaf["kind"], leaf["value"]) for leaf in leaves)
        if node["kind"] == "literal":
            expected_leaves = Counter(("literal", value) for value in node["values"])
        else:
            expected_leaves = Counter()
            for ref in node["references"]:
                child = nodes[ref]
                if child["kind"] == "class":
                    expected_leaves[("class", child["name"])] += 1
                else:
                    expected_leaves.update((leaf["kind"], leaf["value"])
                                           for leaf in data.SUPPLEMENTAL_ALIAS_BRANCHES[ref])
        assert actual_leaves == expected_leaves, key
        for index, leaf in enumerate(leaves):
            bid = data.SUPPLEMENTAL_NODE_TARGETS[key] + ".branch." + str(index)
            branch = data.TARGET_BY_ID[bid]
            assert bid in root["related_targets"]
            assert leaf["path"][0] == key and leaf["path"][-1] == leaf["declaration"]
            for parent, child in zip(leaf["path"], leaf["path"][1:]):
                assert child in nodes[parent]["references"]
            terminal = nodes[leaf["declaration"]]
            if leaf["kind"] == "class":
                assert terminal["kind"] == "class" and leaf["value"] == terminal["name"]
                assert leaf["target"] in branch["related_targets"]
            else:
                assert leaf["value"] in terminal["values"]
            assert branch["declared_type"] == leaf["value"]
            assert {s["first"] for s in branch["sources"] if s["path"] == data.DECLARATIONS_PATH} == {
                nodes[p]["line"] for p in leaf["path"]}
    counts = {name: len(data.SUPPLEMENTAL_ALIAS_BRANCHES[key]) for name, key in data.SUPPLEMENTAL_ALIAS_EXPORTS.items()}
    assert counts == {"NoDecisionReason": 19, "CapabilityKind": 16, "FMathInputV1": 3, "FMathInputV2": 4,
                      "FMathCallArgsV1": 10, "FMathCallArgsV2": 11, "FMathCallV1": 1,
                      "FMathClaimV1": 10, "FMathClaimV2": 12, "FMathOpV1": 14, "FMathOpV2": 16, "FMathOp": 16}
    assert sum(len(v) for v in data.SUPPLEMENTAL_ALIAS_BRANCHES.values()) == 169
    exports = {name: {leaf["value"] for leaf in data.SUPPLEMENTAL_ALIAS_BRANCHES[key]}
               for name, key in data.SUPPLEMENTAL_ALIAS_EXPORTS.items()}
    assert exports["FMathOpV2"] - exports["FMathOpV1"] == {"legacy_bridge_prepare", "legacy_bridge"}
    assert exports["FMathCallArgsV1"] - exports["FMathCallArgsV2"] == {"FPreflightCallArgs"}
    assert exports["FMathCallArgsV2"] - exports["FMathCallArgsV1"] == {"FPreflightFactsCallArgs", "FLegacyBridgeCallArgs"}
    assert exports["FMathCallV1"] == {"FMathCall"}


def test_rate_declarations_and_all_14_previously_missing_names_have_concrete_targets():
    expected = {"RationalInterval": {"lower": "_Fraction", "upper": "_Fraction"},
                "RateBudget": {"tolerance": "_Fraction", "max_cells": "int", "max_terms": "int", "max_refinements": "int"}}
    assert len(data.SUPPLEMENTAL_CLASSES) == 2
    assert set(data.SUPPLEMENTAL_TYPE_RESOLUTIONS) == set(data.DRAFT2_PUBLIC_UNRESOLVED_NAMES)
    assert len(data.SUPPLEMENTAL_TYPE_RESOLUTIONS) == 14 and not data.PUBLIC_UNRESOLVED_NAMES
    assert any(i["line"] == 1763 and i["declaration"] == "from fractions import Fraction as _Fraction"
               for i in data.SUPPLEMENTAL_IMPORT_DECLARATIONS)
    for declaration in data.SUPPLEMENTAL_CLASSES:
        name = declaration["name"]
        assert {f["name"]: f["type"] for f in declaration["fields"]} == expected[name]
        resolution = data.SUPPLEMENTAL_TYPE_RESOLUTIONS[name]
        root = data.TARGET_BY_ID[resolution["target"]]
        assert tuple(root["related_targets"]) == resolution["fields"]
        assert len(resolution["fields"]) == len(expected[name])
        for field in declaration["fields"]:
            text = data.DECLARATION_EXCERPTS[field["line"]].strip()
            assert text == field["name"] + ": " + field["type"]
            target = data.TARGET_BY_ID[resolution["target"] + ".field." + field["name"]]
            assert target["declared_type"] == field["type"]
            assert target["sources"][0] == data.source(data.DECLARATIONS_PATH, field["line"])
    for name, resolution in data.SUPPLEMENTAL_TYPE_RESOLUTIONS.items():
        assert resolution["target"] in data.TARGET_BY_ID
        assert resolution["fields"] or resolution["branches"]
        assert set(resolution["fields"] + resolution["branches"]) <= data.TARGET_BY_ID.keys()
        assert data.TARGET_BY_ID[resolution["target"]]["status"] == "整理済み"
    for name, formerly_missing in data.DRAFT2_DENOMINATOR["PUBLIC_CLOSURE_GAPS"].items():
        root = data.TARGET_BY_ID["T.public." + name]
        assert not root["unresolved_type_closure"]
        for missing in formerly_missing:
            assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[missing]["target"] in root["related_targets"]
    for old in data.DRAFT2_DENOMINATOR["TARGETS"]:
        for missing in old.get("unresolved_type_references", ()):
            assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[missing]["target"] in data.TARGET_BY_ID[old["id"]]["related_targets"]


def test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved():
    old = {row["id"]: row for row in data.DRAFT2_DENOMINATOR["TARGETS"]}
    expected = {id for id, row in old.items() if "G-05" in row["issues"]}
    assert len(expected) == 110 and expected == set(data.DRAFT2_G05_IDS)
    resolutions = {r["target"]: r for r in data.G05_RESOLUTIONS}
    assert len(resolutions) == len(data.G05_RESOLUTIONS) == 110 and set(resolutions) == expected
    assert not any("G-05" in row["issues"] for row in data.TARGETS)
    assert sum(data.DRAFT3_TARGET_BY_ID[id]["status"] == "整理済み" for id in expected) == 109
    assert {id for id in expected if data.DRAFT3_TARGET_BY_ID[id]["status"] != "整理済み"} == {"T.old_style"}
    assert sum(data.TARGET_BY_ID[id]["status"] == "整理済み" for id in expected) == 110
    for id, resolution in resolutions.items():
        row = data.TARGET_BY_ID[id]
        assert resolution["before_status"] == old[id]["status"] == "未対応"
        assert resolution["before_issues"] == old[id]["issues"]
        assert resolution["after_status"] == row["status"]
        assert resolution["remaining_issues"] == row["issues"]
        assert resolution["sources"] and resolution["reason"] and resolution["targets"]
        assert resolution["execution"] == "not_run" and resolution["count_as_pass"] is False
        assert any(s["path"] == data.DECLARATIONS_PATH for s in resolution["sources"])
        if id != "T.old_style":
            assert resolution["resolved_names"]
            for name in resolution["resolved_names"]:
                assert data.SUPPLEMENTAL_TYPE_RESOLUTIONS[name]["target"] in resolution["targets"]
    remaining = data.DRAFT3_TARGET_BY_ID["T.old_style"]
    assert remaining["status"] == "未対応" and remaining["issues"] == ("G-LEGACY-STYLE",)
    assert "資料で未確認" in remaining["use"]
    assert data.LEGACY_STYLE_DISPOSITION["count_as_pass"] is False
    assert any(s["path"] == data.FA and s["first"] == 82 for s in remaining["sources"])
    assert any(s["path"] == data.DECLARATIONS_PATH and s["first"] == 759 and s["last"] == 769
               for s in remaining["sources"])
    assert any(f["id"] == "G-LEGACY-STYLE" and f["targets"] == ("T.old_style",) for f in data.REVISION3_FINDINGS)
    assert not any(t["id"].startswith("T.old_style.") for t in data.DRAFT3_DENOMINATOR["TARGETS"])
    assert data.TARGET_BY_ID["T.old_style"]["status"] == "整理済み"
    assert not data.TARGET_BY_ID["T.old_style"]["issues"]
    assert {id for id in old if id not in expected} <= data.TARGET_BY_ID.keys()
    for id in old.keys() - expected:
        assert old[id] == data.DRAFT4_TARGET_BY_ID[id], id



def test_legacy_style_matches_contract_shape_and_keeps_import_semantics_separate():
    schema = data.LEGACY_STYLE_SCHEMA
    assert schema["contract_name"] == "sui.s4d.preference" and schema["version"] == "1"
    assert schema["body"] == "Preference" and schema["branch"] == "style"
    assert 'PREFERENCE = _ContractRef("sui.s4d.preference", "1")' in data.LEGACY_CONTRACT_EXCERPTS[7]
    assert "style={kind,H_ns,gamma}" in data.LEGACY_CONTRACT_EXCERPTS[18]
    assert "H_nsは非負整数nsかnull、gammaは有限の非負数" in data.LEGACY_CONTRACT_EXCERPTS[19]
    assert {f["name"]: f["type"] for f in schema["fields"]} == {
        "kind": "Literal['style']", "H_ns": "非負整数ns | null", "gamma": "有限の非負JSON数"}
    assert len(schema["field_targets"]) == len(schema["branch_targets"]) == 3
    assert len(schema["relation_targets"]) == 2
    root = data.TARGET_BY_ID["T.old_style"]
    assert root["status"] == "整理済み" and not root["issues"]
    assert root["body"] == "Preference" and root["contract"] == "sui.s4d.preference/1"
    assert root["owner"] == "sui.agent" and root["branch"] == "style"
    assert root["execution"] == "not_run" and root["count_as_pass"] is False
    assert set(root["related_targets"]) == set(schema["field_targets"] + schema["branch_targets"] + schema["relation_targets"])
    for field in schema["fields"]:
        row = data.TARGET_BY_ID["T.old_style.field." + field["name"]]
        assert row["declared_type"] == field["type"]
        assert row["presence"] == field["presence"] and "必須" in row["presence"]
        assert field["source"] in row["sources"]
        assert row["rules"] == root["rules"] and row["entries"] == root["entries"]
    assert "null可" in data.TARGET_BY_ID["T.old_style.field.H_ns"]["presence"]
    assert "非null" in data.TARGET_BY_ID["T.old_style.field.gamma"]["presence"]
    imports = {item["field"]: item for item in data.LEGACY_STYLE_IMPORTS}
    assert imports["H_ns"]["expected"] == "one_step" and imports["H_ns"]["source"] == data.source(data.FA, 16)
    assert "binary floatの正確な有理数" in imports["gamma"]["expected"]
    assert imports["gamma"]["source"] == data.source(data.FA, 27)
    for item in imports.values():
        row = data.TARGET_BY_ID[item["id"]]
        assert item["source"] in row["sources"] and item["expected"] in row["use"]
        assert row["negative"] == item["negative"] and row["nearest_legal"] == item["nearest_legal"]
    assert "scope" not in {f["name"] for f in schema["fields"]}
    assert "旧gammaを新FStyle.gammaのR配列と同一視しない" in schema["independent_of_new_style"]
    assert data.GAPS["G-LEGACY-STYLE"]["status"] == "解消"
    assert not any("G-LEGACY-STYLE" in row["issues"] for row in data.TARGETS)
    assert not any(f["id"] == "G-LEGACY-STYLE" for f in data.REVISION4_FINDINGS)


def test_revision4_preserves_23_checks_and_changes_only_old_style_and_its_children():
    functions = {name: ast.parse(text).body[0] for name, text in data.DRAFT4_TEST_SOURCE.items()}
    amended = {"test_denominator_was_not_changed_by_the_model_bridge",
               "test_revision_accounts_for_every_original_affected_row_and_reports_unclosed",
               "test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved"}
    assert len(data.DRAFT3_TEST_CHECKS) == 23 and data.DRAFT3_TEST_CHECKS.keys() <= functions.keys()
    for name, digest in data.DRAFT3_TEST_CHECKS.items():
        if name not in amended:
            assert hashlib.sha256(_compact_ast_dump(functions[name]).encode()).hexdigest() == digest, name
    assert len(data.DRAFT3_DENOMINATOR["TARGETS"]) == 3240
    for id, old in data.DRAFT3_TARGET_BY_ID.items():
        if id != "T.old_style":
            assert data.DRAFT4_TARGET_BY_ID[id] == old, id
    added = set(data.DRAFT4_TARGET_BY_ID) - data.DRAFT3_TARGET_BY_ID.keys()
    assert added == set(data.LEGACY_STYLE_SCHEMA["field_targets"] + data.LEGACY_STYLE_SCHEMA["branch_targets"]
                        + data.LEGACY_STYLE_SCHEMA["relation_targets"])
    assert len(added) == 8
    assert Counter(data.DRAFT4_TARGET_BY_ID[id]["kind"] for id in added) == {"field": 3, "branch": 3, "relation": 2}
    for key in ("ACCEPTANCE", "ACCEPTANCE_LINKS", "RULES", "ENTRY_POINTS", "MISMATCHES"):
        assert data.DRAFT4_DENOMINATOR[key] == data.DRAFT3_DENOMINATOR[key]
    assert data.DRAFT4_BRIDGES == data.DRAFT3_BRIDGES
    before = Counter(r["status"] for r in data.DRAFT3_DENOMINATOR["TARGETS"])
    after = Counter(r["status"] for r in data.DRAFT4_DENOMINATOR["TARGETS"])
    assert after["整理済み"] == before["整理済み"] + 9
    assert after["未対応"] == before["未対応"] - 1
    assert after["未決"] == before["未決"] and after["未採用"] == before["未採用"]



def test_v23_accounts_for_all_90_g01_rows_and_does_not_promote_execution():
    before = data.DRAFT4_TARGET_BY_ID
    expected = {id for id, row in before.items() if any(i.startswith("G-01") for i in row["issues"])}
    assert len(expected) == 90 and expected == set(data.DRAFT4_G01_IDS)
    assert Counter(before[id]["status"] for id in expected) == {"未決": 55, "未対応": 35}
    resolved = {r["target"]: r for r in data.V23_G01_RESOLUTIONS}
    assert len(resolved) == len(data.V23_G01_RESOLUTIONS) == 90 and set(resolved) == expected
    for id, resolution in resolved.items():
        row = data.TARGET_BY_ID[id]
        assert resolution["before_status"] == before[id]["status"]
        assert resolution["before_issues"] == before[id]["issues"]
        assert resolution["after_status"] == row["status"] == "整理済み"
        assert resolution["remaining_issues"] == row["issues"] == ()
        assert resolution["targets"] and set(resolution["targets"]) <= data.TARGET_BY_ID.keys()
        assert resolution["sources"] and all(s["path"] == data.FB for s in resolution["sources"])
        assert resolution["execution"] == "not_run" and resolution["count_as_pass"] is False
        assert row["execution"] == "not_run" and row["count_as_pass"] is False
    assert not any(any(i.startswith("G-01") for i in row["issues"]) for row in data.TARGETS)
    assert data.GAPS["G-01"]["status"] == "解消"
    assert data.TARGET_BY_ID["T.finite_update2"]["body"] == data.NA
    assert data.TARGET_BY_ID["T.artifact_preflight.model"]["declared_type"] == "Point | None"
    assert "null可" in data.TARGET_BY_ID["T.artifact_preflight.model"]["presence"]
    assert "T.public.FLimitFactsRequest.field.declaration" in data.TARGET_BY_ID["T.artifact_limit.declaration"]["related_targets"]


def test_v23_contracts_are_counted_from_the_paper_excerpt_not_existing_registry():
    pattern = r"sui\.(?:f|fb)\.[a-z_]+/[12]"
    stated = set(re.findall(pattern, "\n".join(data.V23_SECTION_LINES.values())))
    actual = {d["name"] + "/" + d["version"] for d in data.V23_CONTRACT_DECLARATIONS}
    assert stated == actual and len(actual) == len(data.V23_CONTRACT_DECLARATIONS) == 13
    assert sum(d["new"] for d in data.V23_CONTRACT_DECLARATIONS) == 12
    assert {d["name"] for d in data.V23_CONTRACT_DECLARATIONS if not d["new"]} == {"sui.f.finite_update_result"}
    for declaration in data.V23_CONTRACT_DECLARATIONS:
        target = data.TARGET_BY_ID[declaration["target"]]
        assert target["contract"] == declaration["name"] + "/" + declaration["version"]
        assert target["contract"] in data.V23_SECTION_LINES[declaration["line"]]
        assert declaration["payload_target"] in target["related_targets"]
        if declaration["category"] == "prediction":
            assert target["body"] == "Prediction" and target["role"] == "MODEL / PREDICTION"
            assert declaration["parents"] != data.NA
    assert len({t["id"] for t in data.TARGETS if t["kind"] == "body"}) == 8


def test_v23_named_types_fields_union_payloads_and_literals_are_addressable():
    named_in_code = set(re.findall(r"^([A-Z][A-Za-z0-9]+) =", "\n".join(data.V23_SECTION_LINES.values()), re.M))
    named = {d["name"] for d in data.V23_TYPE_DECLARATIONS if d["paper_named"]}
    assert named == named_in_code | {"ClaimKey", "VerifiedFiniteUpdate"}
    assert len(named) == 23 and len(data.V23_TYPE_DECLARATIONS) == 43
    assert sum(len(d["fields"]) for d in data.V23_TYPE_DECLARATIONS) == 116
    assert sum(len(d["branches"]) for d in data.V23_TYPE_DECLARATIONS) == 10
    for declaration in data.V23_TYPE_DECLARATIONS:
        root = data.TARGET_BY_ID[declaration["target"]]
        assert tuple(root["related_targets"]) == declaration["children"]
        for field in declaration["fields"]:
            row = data.TARGET_BY_ID[declaration["target"] + ".field." + field["name"]]
            assert row["declared_type"] == field["type"] and row["field"] == field["name"]
            assert row["sources"][0]["first"] == field["line"]
            if declaration["name"] == "ClaimKey":
                assert "(segment,item_slot)" in data.V23_SECTION_LINES[field["line"]]
            else:
                assert field["name"] + ":" in data.V23_SECTION_LINES[field["line"]]
            if field["type"].startswith("?"):
                assert "null可" in row["presence"]
                for tag in ("null", "value"):
                    assert row["id"] + ".branch." + tag in data.TARGET_BY_ID
            if "/" in field["type"] and not field["type"].startswith("sui."):
                assert {data.TARGET_BY_ID[row["id"] + ".branch." + t]["branch"] for t in field["type"].split("/")} == set(field["type"].split("/"))
        for branch in declaration["branches"]:
            assert "kind: " + branch["tag"] in data.V23_SECTION_LINES[branch["line"]]
            row = data.TARGET_BY_ID[declaration["target"] + ".branch." + branch["tag"]]
            assert row["declared_type"] == branch["payload"]
            assert data.V23_TYPE_TARGETS[branch["payload"]] in row["related_targets"]
            for field in ("kind", "value"):
                assert row["id"] + ".field." + field in data.TARGET_BY_ID
    assert len(data.V23_TYPE_BY_NAME["RejectedIssue"]["fields"][0]["type"].split("/")) == 17
    assert len(data.V23_TYPE_BY_NAME["InsufficientIssue"]["fields"][0]["type"].split("/")) == 5
    assert {f["name"] for f in data.V23_TYPE_BY_NAME["FiniteUpdateResult1"]["fields"]} == {"joint", "evidence_mass"}
    public_result = data.V23_PUBLIC_RESULT_DECLARATION
    assert public_result["name"] == "FiniteUpdateResult"
    assert {f["name"]: f["type"] for f in public_result["fields"]} == {
        "joint": "tuple[_Fraction, ...]", "evidence_mass": "_Fraction"}
    for field in public_result["fields"]:
        assert public_result["excerpt"][field["line"]].strip() == field["name"] + ": " + field["type"]
        assert field["source"] == data.source(data.DECLARATIONS_PATH, field["line"])
    assert {f["name"] for f in data.V23_TYPE_BY_NAME["ClaimState"]["fields"]} == {"law", "predicates"}
    assert not data.V23_TYPE_BY_NAME["VerifiedFiniteUpdate"]["fields"]
    for tag, payload in data.WIRE_TYPES["VerificationResponse"]["branches"]:
        assert payload == next(b["payload"] for b in data.V23_TYPE_BY_NAME["VerificationResponse"]["branches"] if b["tag"] == tag)
        assert data.TARGET_BY_ID["T.wire.type.VerificationResponse.branch." + tag + ".field.value"]["declared_type"] == payload


def test_v23_all_497_lines_74_closing_items_and_10_failures_have_dispositions():
    assert set(data.V23_SECTION_LINES) == set(range(2582, 3090))
    coverage = {item["line"]: item for item in data.V23_SOURCE_COVERAGE}
    assert set(coverage) == set(data.V23_SECTION_LINES) and len(coverage) == 508
    for item in coverage.values():
        assert item["targets"] or item["reason"].startswith("適用外:")
        assert set(item["targets"]) <= data.TARGET_BY_ID.keys()
    closing_lines = {n for n, text in data.V23_SECTION_LINES.items() if text.startswith("**閉じる条件。**")}
    assert len(closing_lines) == 10 and {i["line"] for i in data.V23_CLOSING_ITEMS} == closing_lines
    assert Counter(i["section"] for i in data.V23_CLOSING_ITEMS) == {1:13, 2:7, 3:6, 4:6, 5:6, 6:7, 7:6, 8:4, 9:12, 10:7}
    assert len({i["id"] for i in data.V23_CLOSING_ITEMS}) == 74
    for item in data.V23_CLOSING_ITEMS:
        row = data.TARGET_BY_ID[item["target"]]
        assert item["item"] in row["use"] and row["negative"] and row["nearest_legal"]
        assert item["rules"] and set(item["rules"]) <= data.RULES.keys()
        assert item["entries"] and set(item["entries"]) <= data.ENTRY_POINTS.keys()
        assert any(s["path"] == data.FB and s["first"] == item["line"] for s in row["sources"])
    assert len(data.V23_FAILURE_CLASSIFICATION) == 10
    for failure in data.V23_FAILURE_CLASSIFICATION:
        raw = data.V23_SECTION_LINES[failure["line"]]
        assert failure["condition"] in raw and failure["expected"] in raw
        assert failure["target"] in data.TARGET_BY_ID
    assert {d["line"] for d in data.V23_CHANGED_DISPOSITIONS} == set(data.V23_CHANGED_LINES)
    assert data.TARGET_BY_ID["T.v23.changed.3110"]["status"] == "未採用"


def _posterior_from_weights(weights):
    mass = sum(weights, Fraction(0))
    return tuple(w / mass for w in weights), mass


def test_v23_ce1_recomputes_all_three_paper_results_from_the_eight_row_law():
    example = data.V23_EXAMPLE_DATA["CE1"]
    prior = tuple(map(Fraction, example["prior"]))
    rows = [(tuple(map(int, bits)), (Fraction(a), Fraction(b))) for bits, a, b in example["rows"]]
    assert tuple(sum(masses[c] for _, masses in rows) for c in (0, 1)) == (1, 1)
    first = tuple(sum(m[c] for bits, m in rows if bits[0] == bits[1] == 0) for c in (0, 1))
    later = tuple(sum(m[c] for bits, m in rows if bits[1] == bits[2] == 0) for c in (0, 1))
    both = tuple(sum(m[c] for bits, m in rows if bits == (0, 0, 0)) for c in (0, 1))
    assert first == tuple(map(Fraction, example["paper_Z_first"]))
    assert both == tuple(map(Fraction, example["paper_Z_conjunction"]))
    assert tuple(b / a for a, b in zip(first, both)) == tuple(map(Fraction, example["paper_increment"]))
    results = {}
    for variant, likelihood in (("correct", both), ("double", tuple(a*b for a,b in zip(first,later))), ("discard", first)):
        weights = tuple(p*l for p,l in zip(prior,likelihood))
        joint, mass = _posterior_from_weights(weights)
        expected = example["expected"][variant]
        assert weights == tuple(map(Fraction, expected["weights"]))
        assert joint == tuple(map(Fraction, expected["joint"])) and mass == Fraction(expected["evidence_mass"])
        results[variant] = joint, mass
    assert len(set(results.values())) == 3
    for variant, line in (("correct",2908),("double",2909),("discard",2910)):
        for number in example["expected"][variant]["joint"] + (example["expected"][variant]["evidence_mass"],):
            assert number in data.V23_SECTION_LINES[line]


def test_v23_m07_recomputes_different_posteriors_for_the_same_atom_set():
    ex = data.V23_EXAMPLE_DATA["M07"]
    rows = [(tuple(bits), (Fraction(a), Fraction(b))) for bits,a,b in ex["rows"]]
    prior = tuple(map(Fraction, ex["prior"]))
    assert tuple(sum(m[c] for _,m in rows) for c in (0,1)) == (1,1)
    results = []
    for total, expected in zip((1,0),ex["paper_joint"]):
        likelihood = tuple(sum(m[c] for bits,m in rows if sum(bits)==total) for c in (0,1))
        joint, mass = _posterior_from_weights(tuple(p*l for p,l in zip(prior,likelihood)))
        assert joint == tuple(map(Fraction,expected))
        results.append((joint,mass))
    assert results[0][0] != results[1][0] and ex["same_atoms"] == ("I1","I2")


def test_v23_overlapping_outcomes_recompute_three_halves_and_a_legal_partition():
    ex = data.V23_EXAMPLE_DATA["overlap"]
    prior = tuple(map(Fraction,ex["prior"]))
    outcomes = {"u":tuple(map(Fraction,ex["diagonal_u"])),"v":tuple(map(Fraction,ex["diagonal_v"]))}
    def cell_mass(cell):
        return sum(prior[c]*sum(outcomes[o][c] for o in cell) for c in (0,1))
    masses = tuple(cell_mass(ex["cells"][name]) for name in ("a","b"))
    assert masses == tuple(map(Fraction,ex["paper_probabilities"]))
    assert sum(masses) == Fraction(ex["paper_sum"]) == Fraction(3,2)
    assert cell_mass(("u",))+cell_mass(("v",)) == 1
    assert set(ex["cells"]["a"]) & set(ex["cells"]["b"])


def test_v23_uv_numbers_are_only_reverse_arithmetic_not_a_replayed_unspecified_law():
    ex = data.V23_EXAMPLE_DATA["FB23-R04"]
    weights = []
    for key, derived in (("before","derived_weights_before"),("after","derived_weights_after")):
        joint = tuple(map(Fraction,ex[key]["joint"]))
        assert sum(joint) == 1
        w = tuple(p*Fraction(ex[key]["evidence_mass"]) for p in joint)
        assert w == tuple(map(Fraction,ex[derived]))
        weights.append(w)
    assert tuple(b/a for a,b in zip(*weights)) == tuple(map(Fraction,ex["derived_ratio"]))
    # 逆算だけだった時点の不足は履歴に残す。現行の一次入力は下の第六稿試験で検査。
    old_ex = data.DRAFT5_DENOMINATOR["V23_EXAMPLE_DATA"]["FB23-R04"]
    assert "資料不足" in old_ex["primary_input_status"] and "原入力からの再計算ではない" in old_ex["arithmetic_scope"]
    assert data.DRAFT5_TARGET_BY_ID["T.v23.example.FB23-R04"]["status"] == "未対応"
    assert any(r["id"] == "G-EXAMPLE-UV" for r in data.DRAFT5_FINDINGS)
    assert next(r for r in data.DRAFT5_DENOMINATOR["V23_EXAMPLES"] if r["name"] == "FB23-R04")["calculation"] == "partial"


def test_v23_equal_model_row_sets_do_not_replace_logical_predicates():
    ex = data.V23_EXAMPLE_DATA["digest_logic"]
    law = [(tuple(state),Fraction(mass)) for state,mass in ex["law_rows"]]
    n1zero = {s for s,_ in law if s[0]==0}
    n2zero = {s for s,_ in law if s[1]==0}
    assert n1zero == n2zero == set(ex["same_model_row_set"])
    # N1=0 and N1=1は整数の等号だけで矛盾。後者には(1,0)という法則外の論理的な証人がある。
    witness = ex["second_logical_witness"]
    assert witness[0]==1 and witness[1]==0
    assert not any(x==0 and x==1 for x in (0,1))
    assert sum(m for s,m in law if s[0]==1 and s[1]==0) == 0
    assert ex["expected"] == ("論理的矛盾","model_falsified")


def test_v23_pairwise_witnesses_do_not_make_the_three_way_conjunction_consistent():
    ex = data.V23_EXAMPLE_DATA["triple"]
    predicates = (lambda x,y:x==0, lambda x,y:y==0, lambda x,y:x+y==1)
    assert {pair for pair,_ in ex["pair_witnesses"]} == set(combinations(range(3),2))
    for pair,witness in ex["pair_witnesses"]:
        assert all(p(*witness) for p in (predicates[i] for i in pair))
    # 非負整数とx+y=1から候補は(0,1),(1,0)に限られる。
    assert not any(all(p(x,y) for p in predicates) for x,y in product((0,1), repeat=2))
    assert ex["all_conjunction"] == "矛盾"


def test_v23_keeps_all_25_prior_checks_and_the_bridge_universe_and_old_citations():
    functions = {node.name:node for node in ast.parse(Path(__file__).read_text(encoding="utf-8")).body
                 if isinstance(node,ast.FunctionDef) and node.name.startswith("test_")}
    assert len(data.DRAFT4_TEST_SOURCE) == 25
    assert data.DRAFT4_TEST_SOURCE.keys() <= functions.keys()
    # 旧25件の断言を削って数だけ残すことを防ぐ。版依存の対象は履歴に保持し、現在を上の新試験でも検査。
    for name, text in data.DRAFT4_TEST_SOURCE.items():
        old_asserts = sum(isinstance(n,ast.Assert) for n in ast.walk(ast.parse(text)))
        new_asserts = sum(isinstance(n,ast.Assert) for n in ast.walk(functions[name]))
        assert new_asserts >= old_asserts, name
    # 個数だけでなく旧検査文を比較する。許す差分は引用版、解消報告、
    # 版ごとの履歴に対する検査、第四稿の固定ハッシュの追加だけ。
    historical_functions = (
        "functions = {node.name: node for node in ast.parse(Path(__file__).read_text(encoding='utf-8')).body "
        "if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')}",
        "functions = {name: ast.parse(text).body[0] for name, text in data.DRAFT4_TEST_SOURCE.items()}",
    )
    amendments = {
        "test_acceptance_has_targets_rules_uses_and_entries_or_reported_gap": (
            ("s['path'] == data.FB", "s['path'] == data.FB22"),),
        "test_denominator_was_not_changed_by_the_model_bridge": (
            ("    payload =", "    fourth = json.dumps(data.DRAFT4_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()\n"
             "    assert hashlib.sha256(fourth).hexdigest() == data.DRAFT4_DENOMINATOR_SHA256\n"
             "    assert data.DRAFT4_DENOMINATOR_SHA256 == 'dddb95fbb0a676110b23202fb407c22792a962a4cfd10cba0f3ffce8f8fc30fd'\n"
             "    payload ="),),
        "test_revision_accounts_for_every_original_affected_row_and_reports_unclosed": (
            ("data.REVISION4_FINDINGS", "data.V23_FINDINGS"),),
        "test_revision3_retains_all_19_previous_checks_and_their_fixed_baselines": (
            historical_functions,
            ("assert data.ACCEPTANCE ==", "assert _unpin_v22(data.ACCEPTANCE) =="),
            ("assert data.ACCEPTANCE_LINKS ==", "assert _unpin_v22(data.ACCEPTANCE_LINKS) =="),
            ("before[key] == after[key]", "before[key] == _unpin_v22(after[key])"),),
        "test_all_110_g05_rows_are_conserved_and_legacy_style_is_not_counted_as_resolved": (
            ("assert old[id] == data.TARGET_BY_ID[id]", "assert old[id] == data.DRAFT4_TARGET_BY_ID[id]"),),
        "test_revision4_preserves_23_checks_and_changes_only_old_style_and_its_children": (
            historical_functions,
            ("data.TARGET_BY_ID", "data.DRAFT4_TARGET_BY_ID"),
            ("getattr(data, key)", "data.DRAFT4_DENOMINATOR[key]"),
            ("data.BRIDGES", "data.DRAFT4_BRIDGES"),
            ("data.TARGETS", "data.DRAFT4_DENOMINATOR['TARGETS']"),),
    }
    for name, text in data.DRAFT4_TEST_SOURCE.items():
        expected = ast.unparse(ast.parse(text))
        for old, replacement in amendments.get(name, ()):
            assert old in expected, (name, old)
            expected = expected.replace(old, replacement)
        assert ast.dump(ast.parse(expected).body[0]) == ast.dump(functions[name]), name
    for id,old in data.DRAFT4_TARGET_BY_ID.items():
        if id not in data.DRAFT4_G01_IDS:
            assert _unpin_v22(data.TARGET_BY_ID[id]) == old, id
    assert len(data.BRIDGES) == len(data.DRAFT4_BRIDGES) == 197
    for old,current in zip(data.DRAFT4_BRIDGES,data.BRIDGES):
        for key in old.keys()-{"prerequisite_issues"}:
            assert _unpin_v22(current[key]) == old[key], (old["id"],key)
        assert current["prerequisite_issues"] == tuple(i for i in old["prerequisite_issues"] if not i.startswith("G-01"))
        assert current["execution"] == "not_run"
    for key in ("ACCEPTANCE","ACCEPTANCE_LINKS","RULES","ENTRY_POINTS","MISMATCHES"):
        assert _unpin_v22(getattr(data,key)) == data.DRAFT4_DENOMINATOR[key]
    for id,old in data.DRAFT4_TARGET_BY_ID.items():
        current = data.TARGET_BY_ID[id]
        for ref in old["sources"]:
            archived = dict(ref,path=data.FB22) if ref["path"]==data.FB else ref
            assert archived in current["sources"], (id,ref)
    assert data.V23_PROVENANCE["archive_sha256_lf"] == "72bfe382a80675166772eb91c4c816503bce5472c0c47639cd4c233e3151b5a9"
    assert all(r["execution"] == "not_run" for r in data.V23_EXAMPLES)


def test_revision6_uv_recomputes_from_the_declared_prior_and_joint_table_and_stops_at_shape():
    ex = data.V23_EXAMPLE_DATA["FB23-R04"]
    prior = tuple(map(Fraction, ex["prior"]))
    assert prior == (Fraction(1, 2), Fraction(1, 2))
    assert "事前 (1/2,1/2)" in data.V23_SECTION_LINES[2914]
    rows = tuple((counts, (Fraction(a), Fraction(b))) for counts, a, b in ex["rows"])
    assert {counts for counts, _ in rows} == set(product((0, 1), repeat=2))
    assert len(rows) == len(ex["row_lines"]) == 4
    for (counts, masses), line in zip(rows, ex["row_lines"]):
        cells = tuple(c.strip() for c in data.V23_SECTION_LINES[line].split("|")[1:-1])
        assert cells[0] == "(" + ",".join(map(str, counts)) + ")"
        assert tuple(map(Fraction, cells[1:])) == masses
        assert all(m >= 0 for m in masses)
    assert tuple(sum(masses[s] for _, masses in rows) for s in range(2)) == (1, 1)
    first = tuple(sum(masses[s] for counts, masses in rows if counts[0] == 0) for s in range(2))
    conjunction = tuple(sum(masses[s] for counts, masses in rows if counts == (0, 0)) for s in range(2))
    assert first == tuple(map(Fraction, ex["paper_Z_first"]))
    assert conjunction == tuple(map(Fraction, ex["paper_Z_conjunction"]))
    weights_first = tuple(p * z for p, z in zip(prior, first))
    weights_both = tuple(p * z for p, z in zip(prior, conjunction))
    for key, weights in (("before", weights_first), ("after", weights_both)):
        assert _posterior_from_weights(weights) == (
            tuple(map(Fraction, ex[key]["joint"])), Fraction(ex[key]["evidence_mass"]))
    increment = tuple(b / a for a, b in zip(first, conjunction))
    assert increment == tuple(map(Fraction, ex["derived_ratio"]))
    assert tuple(w * l for w, l in zip(weights_first, increment)) == weights_both
    raw = data.V23_SECTION_LINES[2923]
    assert "(3/4,1/4；1/2)" in raw and "(9/10,1/10；5/16)" in raw
    assert "(9/16,1/16)" in raw and "shape で止まる (二重適用まで進まない)" in raw
    assert ex["same_channel_identity"] == ("process", "route_configs", "domain")
    assert all(name in data.V23_SECTION_LINES[2914] for name in ex["same_channel_identity"])
    assert ex["channels"] == ("u", "v") and ex["interval"] == "(0,1]"
    assert ex["expected_stop_stage"] == "shape" and ex["numerical_application_permitted"] is False
    target = data.TARGET_BY_ID["T.v23.example.FB23-R04"]
    assert target["status"] == "整理済み" and target["issues"] == ()
    assert data.source(data.FB, 2914, 2923) in target["sources"]
    assert "shape" in target["negative"] and "no-op" in target["nearest_legal"]
    assert target["count_as_pass"] is False and target["execution"] == "not_run"
    example = next(r for r in data.V23_EXAMPLES if r["name"] == "FB23-R04")
    assert example["calculation"] == "checked" and example["count_as_pass"] is False


def test_revision6_closes_the_two_reported_issues_and_pins_both_paper_hash_forms():
    assert data.V23_FINDINGS == ()
    resolutions = {r["id"]: r for r in data.REVISION6_RESOLUTIONS}
    assert set(resolutions) == {"G-EXAMPLE-UV", "V23-REVIEW-LABEL"}
    assert data.GAPS["G-EXAMPLE-UV"]["status"] == "解消"
    for row in resolutions.values():
        assert row["status"] == "解消" and row["sources"]
        assert set(row["targets"]) <= data.TARGET_BY_ID.keys()
        assert row["count_as_pass"] is False and row["execution"] == "not_run"
    for line in (3, 2562, 2584):
        text = data.REVISION6_PAPER_UPDATES[line]
        assert "pass" in text and "独立の点検は未" not in text
    assert data.TARGET_BY_ID["T.v23.changed.2562"]["use"] == data.REVISION6_PAPER_UPDATES[2562]
    assert data.TARGET_BY_ID["T.v23.clause.2584"]["use"] == data.REVISION6_PAPER_UPDATES[2584]
    assert data.V23_PROVENANCE["lines"] == data.PROVENANCE["spec_lines"] == 3216
    assert data.V23_PROVENANCE["sha256_bytes"] == data.REVISION6_PAPER_SHA256 == "b8faf0a738cc741f7d3483c31933a8837e387d44a55e8b2beb1e9d0851e7fa8a"
    assert data.V23_PROVENANCE["sha256_lf"] == data.REVISION6_PAPER_SHA256_LF == "b4fc4b82c2765221d42c5b1c5330ddc54b0f073bbfebbbb09e597a3a0a2c197e"
    payload = json.dumps(data.DRAFT5_DENOMINATOR, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(payload).hexdigest() == data.DRAFT5_DENOMINATOR_SHA256 == "4dd991ceac8933a8afe20ce8f1ed0edac1b1f843d3120c29fa82f2a225f774ed"


def test_revision6_preserves_all_36_checks_rows_and_the_bridge_and_only_moves_citations():
    functions = {n.name: n for n in ast.parse(Path(__file__).read_text(encoding="utf-8")).body
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}
    assert len(data.DRAFT5_TEST_CHECKS) == 36 and data.DRAFT5_TEST_CHECKS.keys() <= functions.keys()
    for name, digest in data.DRAFT5_TEST_CHECKS.items():
        if name not in data.DRAFT5_AMENDED_TEST_SOURCE:
            assert hashlib.sha256(_compact_ast_dump(functions[name]).encode()).hexdigest() == digest, name
    for name, text in data.DRAFT5_AMENDED_TEST_SOURCE.items():
        if name == "test_v23_all_497_lines_74_closing_items_and_10_failures_have_dispositions":
            expected = text.replace("range(2582, 3079)", "range(2582, 3090)").replace("len(coverage) == 497", "len(coverage) == 508")
        else:
            assert name == "test_v23_uv_numbers_are_only_reverse_arithmetic_not_a_replayed_unspecified_law"
            expected = text.replace('    assert "資料不足" in ex',
                '    old_ex = data.DRAFT5_DENOMINATOR["V23_EXAMPLE_DATA"]["FB23-R04"]\n    assert "資料不足" in old_ex')
            expected = expected.replace('in ex["arithmetic_scope"]', 'in old_ex["arithmetic_scope"]')
            expected = expected.replace("data.TARGET_BY_ID", "data.DRAFT5_TARGET_BY_ID").replace("data.V23_FINDINGS", "data.DRAFT5_FINDINGS")
            expected = expected.replace("data.V23_EXAMPLES", 'data.DRAFT5_DENOMINATOR["V23_EXAMPLES"]')
        assert ast.dump(ast.parse(expected).body[0]) == ast.dump(functions[name]), name
    def move_sources(value):
        if isinstance(value, dict):
            result = {k: move_sources(v) for k, v in value.items()}
            if result.get("path") == data.FB:
                for key in ("first", "last"):
                    if result[key] >= 2914:
                        result[key] += 11
            return result
        if isinstance(value, tuple):
            return tuple(move_sources(v) for v in value)
        if isinstance(value, list):
            return [move_sources(v) for v in value]
        return value
    assert data.TARGET_BY_ID.keys() == data.DRAFT5_TARGET_BY_ID.keys()
    for id, old in data.DRAFT5_TARGET_BY_ID.items():
        expected = move_sources(old)
        if id in ("T.v23.changed.2562", "T.v23.clause.2584", "T.v23.clause.2757"):
            expected["use"] = data.REVISION6_PAPER_UPDATES[int(id.rsplit(".", 1)[1])]
        elif id == "T.v23.example.FB23-R04":
            for key in ("status", "issues", "use", "negative", "nearest_legal", "sources"):
                expected[key] = data.TARGET_BY_ID[id][key]  # 個々の値は上の一次入力試験で検査
        assert data.TARGET_BY_ID[id] == expected, id
    assert data.BRIDGES == data.DRAFT5_BRIDGES and len(data.BRIDGES) == 197
    before = Counter(r["status"] for r in data.DRAFT5_DENOMINATOR["TARGETS"])
    after = Counter(r["status"] for r in data.TARGETS)
    assert after["整理済み"] == before["整理済み"] + 1
    assert after["未対応"] == before["未対応"] - 1
    assert after["未決"] == before["未決"] and after["未採用"] == before["未採用"]
    coverage = {r["line"]: r for r in data.V23_SOURCE_COVERAGE}
    assert all(coverage[n]["targets"] == ("T.v23.example.FB23-R04",) for n in range(2914, 2925))
