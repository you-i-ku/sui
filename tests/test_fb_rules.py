"""Reader self-tests plus deliberately strict guards on the real paper.

The small source and DTOs below are independent fixtures, not a copy of the
production rule expectations. No persistent test artifact or basetemp is used.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fb_rule_table_tool", ROOT / "tools/rule_tables.py")
rules = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rules
spec.loader.exec_module(rules)


FIXED_ATOMS = [{"id": "EXAMPLE-BYTES", "left": "Q*:", "rel": "present", "on_fail": "不足"}]
ATOM_TEXT = json.dumps(FIXED_ATOMS, ensure_ascii=False, separators=(",", ":"))
FIXED_DECLARATIONS = {
    "SCOPES": {"requests": {"records": ["Q*"], "meaning": "the fixed request"}},
    "DERIVATIONS": {"point_of": "read the authenticated Point", "effect": "read a captured effect", "via": "follow an obligation"},
    "EFFECTS": {"actual": "captured actual value"}, "MODEL_WALKS": {},
}
EXAMPLE = """# Fixed paper
- 版: fixed/1
## §6-11. 機械可読の規則の表 (v1、fixed)
#### 表 T-REF (機械可読)
| ID | 出発の契約 | 出発の用途 | 欄 | 到達先の契約 (決まっていれば) | 到達先の用途 (契約が決めるなら -) | 役割 | 条件 | 紙の行 |
|---|---|---|---|---|---|---|---|---|
| REF-LEFT | sui.fb.example/1 | update | /left? | sui.fb.example/1 | update | UE | true | fixed:1 |
| REF-RIGHT | sui.fb.example/1 | update | /right? | sui.fb.example/1 | update | UE | true | fixed:1 |
| REF-CLOCK-KIND | sui.fb.example/1 | update | /readings/*[kind=clock]/kind | - | - | E | true | fixed:2 |
| REF-CLOCK-SOURCE | sui.fb.example/1 | update | /readings/*[kind=clock]/value/source | - | - | E | true | fixed:2 |
| REF-CLOCK-VALUE | sui.fb.example/1 | update | /readings/*[kind=clock]/value/reading | - | - | E | true | fixed:2 |
| REF-UNAVAILABLE-REASON | sui.fb.example/1 | update | /readings/*[kind=unavailable]/value/reason | - | - | E | true | fixed:2 |
| REF-UNAVAILABLE-KIND | sui.fb.example/1 | update | /readings/*[kind=unavailable]/kind | - | - | E | true | fixed:2 |
| REF-UNAVAILABLE-BASIS | sui.fb.example/1 | update | /readings/*[kind=unavailable]/value/basis/* | - | - | E | true | fixed:2 |
#### 表 T-A2 (機械可読)
| ID | 区分 (Local / History / 前のC / 前のI) | 出発の契約 | 出発の用途 | 欄 | 展開 (さらにたどる T-REF の ID、無ければ -) | 紙の行 |
|---|---|---|---|---|---|---|
| A2-LEFT | Local | sui.fb.example/1 | update | /left? | REF-LEFT | fixed:3 |
#### 表 T-G4 (機械可読)
| ID | 契約 | 用途 | 鍵の形 (item / life / terminal / …) | 鍵の欄 | 排他の単位 | 比較の bytes | 紙の行 |
|---|---|---|---|---|---|---|---|
| G4-EXAMPLE | sui.fb.example/1 | update | terminal | ["/left?"] | {"rule":"CL-SAME"} | ["/right?"] | fixed:4 |
#### 表 T-G6 (機械可読)
| ID | 操作 | 段階 (作成 / 入場 / 取得 / 採用 / 継続 / 評価の頭 / …) | 使う候補または記録 | 出発の用途 | 門の時点 (公開の前 / 入場の前 / 実取得の前 / …) | 紙の行 |
|---|---|---|---|---|---|---|
| G6-EXAMPLE | 試す | 作成 | sui.fb.example/1 | update | 公開の前 | fixed:5 |
#### 表 T-A1 (機械可読)
| ID | 項目 | 適用段階 (更新の再構成 / 結果の生成 / 取得 / 採用 / 評価の頭) | 対象 (全Q* / 頭のA* / …) | 照合関係 (何と何を) | 必要証拠 (EW / EH / EA / EI / 台帳) | 失敗分類 (不足 / 不適合 / 使用の禁止) | 紙の行 |
|---|---|---|---|---|---|---|---|
| A1-EXAMPLE | 同一性 | ["更新の再構成"] | {"scope":"requests","records":["Q*"]} | {ATOMS} | ["台帳"] | 不適合 | fixed:6 |

| 操作 | 出発点 |
|---|---|
| 試す | 記録の候補 |
""".replace("{ATOMS}", ATOM_TEXT)
EXAMPLE += "\n```json\n" + json.dumps(FIXED_DECLARATIONS, ensure_ascii=False) + "\n```\n"

DTO_EXAMPLE = """
class ReadingClock:
    source: str
    reading: int
class Unavailable:
    reason: str
    basis: tuple[str, ...]
ReadingEvidence: TypeAlias = ReadingClock | Unavailable
class Example:
    left: str | None
    right: str | None
    readings: tuple[ReadingEvidence, ...]
"""


class MemoryFile:
    """Exercise the file API without creating a fourth workspace file."""
    def __init__(self, text=""):
        self.text = text

    def read_text(self, **kwargs):
        return self.text

    def write_text(self, text, **kwargs):
        self.text = text

    def __str__(self):
        return "<in-memory generated module>"


def fixture_structures():
    reader = rules.Structures.__new__(rules.Structures)
    tree = ast.parse(DTO_EXAMPLE)
    reader.nodes = {("fb", n.name): n for n in tree.body if isinstance(n, ast.ClassDef)}
    reader.aliases = {("fb", n.target.id): n.value for n in tree.body if isinstance(n, ast.AnnAssign)}
    reader.f_tags = {}
    reader.segment_tags = {}
    reader.outcome_tags = {}
    reader.overrides = {
        ("reading", "ReadingClock"): ast.parse('{"kind":"clock", "value":{"source":value.source,"reading":encode(value.reading)}}', mode="eval").body,
        ("reading", "Unavailable"): ast.parse('{"kind":"unavailable", "value":encode(value)}', mode="eval").body,
    }
    return reader


def test_fixed_markdown_and_structure_cover_arrays_branches_and_null(monkeypatch):
    data = rules.parse_paper(EXAMPLE)
    reader = fixture_structures()
    monkeypatch.setattr(rules, "Structures", lambda root: reader)
    monkeypatch.setattr(rules, "DTO_BINDINGS", {"sui.fb.example/1": ("fb", "Example")})
    result = rules.check(data, EXAMPLE)
    assert result["ok"], result
    assert result["a1_ids"] == ["A1-EXAMPLE"]
    paths = {x["field"] for x in result["contracts"][0]["fields"]}
    assert paths == {
        "/readings/*[kind=clock]/kind", "/readings/*[kind=unavailable]/kind",
        "/left?", "/right?", "/readings/*[kind=clock]/value/source",
        "/readings/*[kind=clock]/value/reading", "/readings/*[kind=unavailable]/value/reason",
        "/readings/*[kind=unavailable]/value/basis/*",
    }
    data["tables"]["T-REF"] = [r for r in data["tables"]["T-REF"] if r["id"] != "REF-UNAVAILABLE-BASIS"]
    result = rules.check(data, EXAMPLE)
    assert [x["field"] for x in result["unclassified"]] == ["/readings/*[kind=unavailable]/value/basis/*"]


@pytest.mark.parametrize("old,new", [
    ("紙の行", "未知の列"),
    ("REF-RIGHT", "REF-LEFT"),
    ("sui.fb.example/1", "sui.fb.example"),
    ("/left?", "/left?/child"),
    ("/left?", "/left~2"),
    ("| UE |", "| unknown |"),
    ("| update |", "| update() |"),
    ("| true |", '| {"unknown":true} |'),
    ("| true |", '| {"nonnull":"bad"} |'),
    ("| true |", '| {"nonnull":"/left","nonnull":"/right"} |'),
    ("| true |", "| false |"),
    ('["台帳"]', "[]"),
    ('["台帳"]', '["unknown"]'),
    ('["更新の再構成"]', '["未来"]'),
    ("| 同一性 |", "| **同一性** |"),
    ("| 同一性 |", "| *同一性* |"),
    ("| 同一性 |", "| |"),
    ("| REF-LEFT | fixed:3 |", "| REF-MISSING | fixed:3 |"),
    ('["/left?"]', '[{"via":"REF-MISSING","compare":"all_bytes"}]'),
])
def test_reader_stops_on_bad_cells_columns_ids_and_references(old, new):
    with pytest.raises(rules.TableError):
        rules.parse_paper(EXAMPLE.replace(old, new, 1))


@pytest.mark.parametrize("role", sorted(rules.ROLES))
def test_all_six_roles_are_preserved(role):
    data = rules.parse_paper(EXAMPLE.replace("| UE |", f"| {role} |", 1))
    assert data["tables"]["T-REF"][0]["role"] == role


def test_heading_requires_the_immediately_following_table():
    bad = EXAMPLE.replace("#### 表 T-REF (機械可読)", "#### 表 T-REF (機械可読)\nintervening paragraph")
    with pytest.raises(rules.TableError, match="immediately"):
        rules.parse_paper(bad)


def test_fenced_fake_table_is_not_a_machine_table():
    with pytest.raises(rules.TableError, match="missing tables"):
        rules.parse_paper(EXAMPLE[:EXAMPLE.index("#### 表 T-REF")] + "\n```md\n" + EXAMPLE[EXAMPLE.index("#### 表 T-REF"):] + "\n```\n")


def test_pipe_inside_code_or_escape_is_not_a_column_boundary():
    assert rules.row_cells(r"| one | `two|three` | four\|five |", 3) == ("one", "`two|three`", r"four\|five")
    with pytest.raises(rules.TableError):
        rules.parse_paper(EXAMPLE.replace("| 同一性 |", r"| one\|two |", 1))


def test_two_fields_to_the_same_point_survive_generation():
    data = rules.parse_paper(EXAMPLE)
    file = MemoryFile()
    rules.generate(data, file)
    generated = rules.load_generated(file)
    references = generated["tables"]["T-REF"][:2]
    record = {"left": "same-point", "right": "same-point"}
    obligations = [(r["id"], r["field"], record[r["field"][1:-1]]) for r in references]
    assert obligations == [("REF-LEFT", "/left?", "same-point"), ("REF-RIGHT", "/right?", "same-point")]


def test_nullable_container_needs_its_own_treatment():
    shape = rules.Shape("union", (rules.Shape("null"), rules.Shape("object", (("child", rules.ATOM),))))
    fields = rules.enumerate_fields(shape, "/container")
    assert {f["field"] for f in fields} == {"/container?", "/container/child"}
    rows = [{"field": "/container/child", "role": "E"}]
    assert not rules.field_covered(fields[0], rows)
    assert rules.field_covered(fields[1], rows)


def test_nullable_value_needs_null_and_nonnull_cases():
    shape = rules.Shape("union", (rules.Shape("null"), rules.ATOM))
    field = rules.enumerate_fields(shape, "/value")[0]
    nonnull = {"field": "/value?", "role": "E", "condition": {"nonnull": "/value"}}
    null = {"field": "/value?", "role": "E", "condition": {"is_null": "/value"}}
    assert not rules.field_covered(field, [nonnull])
    assert not rules.field_covered(field, [null])
    assert rules.field_covered(field, [nonnull, null])


def coverage_rows(markdown):
    """Parse the short fixed rows using the same cell grammar as the paper."""
    text = EXAMPLE.replace("#### 表 T-A2 (機械可読)", markdown + "\n#### 表 T-A2 (機械可読)", 1)
    return [r for r in rules.parse_paper(text)["tables"]["T-REF"] if r["id"].startswith("REF-COVER-")]


@pytest.mark.parametrize("role", ["E", "leaf", "ignored", "unsupported"])
def test_parent_value_row_covers_all_leaves(role):
    rows = coverage_rows("""| REF-COVER-PARENT | sui.fb.example/1 | update | /box | - | - | E | true | fixed:7 |""".replace("| E |", f"| {role} |"))
    shape = rules.Shape("object", (
        ("nested", rules.Shape("object", (("leaf", rules.ATOM),))),
        ("items", rules.Shape("array", (rules.Shape("tagged", (("clock", rules.ATOM),)),))),
        ("optional", rules.Shape("union", (rules.Shape("null"), rules.ATOM))),
    ))
    fields = rules.enumerate_fields(shape, "/box")
    assert {f["field"] for f in fields} == {
        "/box/nested/leaf", "/box/items/*[kind=clock]/kind",
        "/box/items/*[kind=clock]/value", "/box/optional?",
    }
    assert all(rules.field_covered(f, rows) for f in fields)
    assert not rules.field_covered({"field": "/boxes/leaf", "kind": "value"}, rows)


@pytest.mark.parametrize("role", ["U", "UE"])
def test_parent_reference_row_does_not_cover_descendants(role):
    rows = coverage_rows("""| REF-COVER-PARENT | sui.fb.example/1 | update | /box | sui.fb.example/1 | update | U | true | fixed:7 |""".replace("| U |", f"| {role} |"))
    assert rules.field_covered({"field": "/box", "kind": "value"}, rows)
    assert not rules.field_covered({"field": "/box/child", "kind": "value"}, rows)
    assert not rules.field_covered({"field": "/box/items/*/child?", "kind": "nullable"}, rows)


@pytest.mark.parametrize("role", ["U", "UE"])
def test_more_specific_reference_row_overrides_parent_value_row(role):
    rows = coverage_rows("""| REF-COVER-PARENT | sui.fb.example/1 | update | /box | - | - | E | true | fixed:7 |
| REF-COVER-CHILD | sui.fb.example/1 | update | /box/link | sui.fb.example/1 | update | U | true | fixed:8 |""".replace("| U |", f"| {role} |"))
    for ordered in (rows, list(reversed(rows))):
        assert rules.field_covered({"field": "/box/other/leaf", "kind": "value"}, ordered)
        assert rules.field_covered({"field": "/box/link", "kind": "value"}, ordered)
        assert not rules.field_covered({"field": "/box/link/child", "kind": "value"}, ordered)


def test_more_specific_value_row_and_unresolved_row_take_priority():
    rows = coverage_rows("""| REF-COVER-PARENT | sui.fb.example/1 | update | /box | sui.fb.example/1 | update | U | true | fixed:7 |
| REF-COVER-CHILD | sui.fb.example/1 | update | /box/closed | - | - | E | true | fixed:8 |
| REF-COVER-PENDING | sui.fb.example/1 | update | /box/closed/link | - | - | 未確定 | true | fixed:9 |""")
    assert rules.field_covered({"field": "/box/closed/value", "kind": "value"}, rows)
    assert not rules.field_covered({"field": "/box/closed/link", "kind": "value"}, rows)
    assert not rules.field_covered({"field": "/box/closed/link/value", "kind": "value"}, rows)


@pytest.mark.parametrize("branch,kind", [
    ("/item[kind=started]", "wire_tag"),
    ("/outcome[kind=failure]/value/readings/*[kind=clock]", "wire_tag"),
    ("/direct[kind=clock]", "literal"),
])
def test_selected_branch_covers_its_discriminator_only(branch, kind):
    rows = coverage_rows("""| REF-COVER-BRANCH | sui.fb.example/1 | update | /BRANCH/value/source | sui.fb.example/1 | update | UE | true | fixed:7 |""".replace("/BRANCH", branch))
    field = {"field": branch + "/kind", "kind": kind}
    assert rules.field_covered(field, rows)
    assert not rules.field_covered(field, rows, branch_identifiers=False)
    assert not rules.field_covered({"field": branch + "/value/other", "kind": "value"}, rows)
    sibling = branch[:branch.rindex("[kind=")] + "[kind=other]/kind"
    assert not rules.field_covered({"field": sibling, "kind": kind}, rows)


def test_explicit_discriminator_row_takes_priority_over_branch_selection():
    rows = coverage_rows("""| REF-COVER-BRANCH | sui.fb.example/1 | update | /item[kind=started]/value/source | - | - | E | true | fixed:7 |
| REF-COVER-KIND | sui.fb.example/1 | update | /item[kind=started]/kind | - | - | 未確定 | true | fixed:8 |""")
    assert not rules.field_covered({"field": "/item[kind=started]/kind", "kind": "wire_tag"}, rows)


def test_nullable_pointer_also_treats_the_nonnull_constructor_branch():
    row = {"field": "/started?", "role": "UE", "condition": {"nonnull": "/started"}}
    assert rules.field_covered({"field": "/started", "kind": "value"}, [row])
    assert not rules.field_covered({"field": "/started?", "kind": "nullable"}, [row])
    assert not rules.field_covered({"field": "/started", "kind": "value"},
                                   [dict(row, condition={"is_null": "/started"})])


ALIASES = """- 旧 G6 の操作名 → T-G6 の ID の対応（固定例）
```text
旧い操作 => G6-EXAMPLE,G6-SECOND
```
"""


def alias_example():
    text = EXAMPLE.replace("#### 表 T-REF", ALIASES + "\n#### 表 T-REF", 1)
    text = text.replace("| 試す | 記録の候補 |", "| 旧い操作 | 記録の候補 |")
    line = next(s for s in text.splitlines() if s.startswith("| G6-EXAMPLE |"))
    return text.replace(line, line + "\n" + line.replace("G6-EXAMPLE", "G6-SECOND").replace("試す", "続ける"))


def test_explicit_old_operation_aliases_preserve_all_ids_and_roundtrip():
    text = alias_example()
    data = rules.parse_paper(text)
    found = rules.operation_coverage(text, data)
    assert found["missing"] == []
    assert found["paper_operations"][0]["rule_ids"] == ["G6-EXAMPLE", "G6-SECOND"]
    assert text.splitlines()[found["paper_operations"][0]["mapping_line"] - 1].startswith("旧い操作 =>")
    file = MemoryFile()
    rules.generate(data, file)
    assert rules.diff(data, rules.load_generated(file))["matches"]
    changed = deepcopy(data)
    changed["operation_aliases"][0]["ids"].pop()
    result = rules.diff(data, changed)
    assert result["changes"][0]["table"] == "G6 aliases"
    assert "operation_aliases" in rules.human(result, "diff")


@pytest.mark.parametrize("old,new", [
    ("G6-SECOND\n```", "G6-MISSING\n```"),
    ("旧い操作 =>", "存在しない旧名 =>"),
    ("旧い操作 =>", "旧い操作 ->"),
    ("G6-EXAMPLE,G6-SECOND\n```", "G6-EXAMPLE,G6-EXAMPLE\n```"),
    ("旧い操作 => G6-EXAMPLE,G6-SECOND", "旧い操作 => G6-EXAMPLE\n旧い操作 => G6-SECOND"),
    (ALIASES, ""),
])
def test_aliases_fail_on_missing_names_ids_and_malformed_lines(old, new):
    with pytest.raises(rules.TableError):
        rules.parse_paper(alias_example().replace(old, new, 1))


def test_generate_diff_roundtrip_and_literal_only_module():
    data = rules.parse_paper(EXAMPLE)
    file = MemoryFile()
    rules.generate(data, file)
    assert all(isinstance(n, (ast.Assign, ast.ImportFrom)) for n in ast.parse(file.text).body)
    assert rules.diff(data, rules.load_generated(file))["matches"]


@pytest.mark.parametrize("mutation,expected", [
    ("role", "modified"), ("target_contract", "modified"), ("remove", "added"), ("add", "removed"),
])
def test_semantic_diff_reports_role_target_and_row_changes(mutation, expected):
    data = rules.parse_paper(EXAMPLE)
    old = deepcopy(data)
    old["generator_version"] = rules.VERSION
    if mutation == "remove":
        old["tables"]["T-REF"].pop()
    elif mutation == "add":
        row = dict(old["tables"]["T-REF"][-1], id="REF-EXTRA")
        old["tables"]["T-REF"].append(row)
    else:
        old["tables"]["T-REF"][0][mutation] = "E" if mutation == "role" else "sui.fb.other/1"
    result = rules.diff(data, old)
    assert not result["matches"]
    assert result["changes"][0]["change"] == expected
    if mutation in {"role", "target_contract"}:
        assert mutation in result["changes"][0]["fields"]


def test_moving_source_lines_does_not_change_identity_or_meaning():
    data = rules.parse_paper(EXAMPLE)
    old = rules.parse_paper("\n\n" + EXAMPLE)
    old["generator_version"] = rules.VERSION
    result = rules.diff(data, old)
    assert not result["changes"]
    assert result["provenance_changes"]
    assert [x["id"] for x in old["tables"]["T-REF"]] == [x["id"] for x in data["tables"]["T-REF"]]


def test_pending_is_preserved_and_never_claims_complete():
    data = rules.parse_paper(EXAMPLE.replace("| " + ATOM_TEXT + " |", "| 未確定 |"))
    assert not data["complete"]
    file = MemoryFile()
    rules.generate(data, file)
    assert rules.load_generated(file)["complete"] is False
    assert rules.load_generated(file)["pending"][0]["id"] == "A1-EXAMPLE"


def test_untrusted_generated_code_is_never_executed():
    with pytest.raises(rules.TableError):
        rules.load_generated(MemoryFile('raise RuntimeError("must not execute")'))


def test_missing_paper_fails_explicitly():
    class MissingPaper(MemoryFile):
        def read_text(self, **kwargs):
            raise FileNotFoundError("fixture missing")
    with pytest.raises(rules.TableError, match="紙が無い"):
        rules.read_paper(MissingPaper())


def test_cli_exit_codes_generate_diff_and_unreadable(monkeypatch, capsys):
    data = rules.parse_paper(EXAMPLE)
    monkeypatch.setattr(rules, "read_paper", lambda path: data)
    file = MemoryFile()
    monkeypatch.setattr(rules, "OUTPUT", file)
    assert rules.main(["generate", "--format", "json"]) == 0
    assert rules.main(["diff", "--format", "json"]) == 0
    file.text = file.text.replace("'role': 'UE'", "'role': 'E'", 1)
    assert rules.main(["diff", "--format", "json"]) == 1
    def unreadable(path):
        raise rules.TableError("紙が無い")
    monkeypatch.setattr(rules, "read_paper", unreadable)
    assert rules.main(["check", "--format", "json"]) == 2
    assert "紙が無い" in capsys.readouterr().out


DECLARED = """# A different paper
- 版: S5-example/1
表の版: v7
表の一覧: T-LINK(参照) T-EXTRA(新しい種類)
#### 表 T-LINK (機械可読)
| 番号【ID】 | 対象【契約】 | 用い方【用途】 | 位置【欄】 | 処遇【役割】 | 補足【JSON】 |
|---|---|---|---|---|---|
| LINK-A | sui.fb.example/1 | update | /many/*[kind=clock]/value/source? | UE | {"allow":true} |
#### 表 T-EXTRA (機械可読)
| 説明【文】 | 参照番号【ID参照:T-LINK】 | 根拠【紙の行】 | 番号【ID】 |
|---|---|---|---|
| 任意の列名と表の種類 | LINK-A | S5:12 | EXTRA-A |
"""

DECLARED_TYPES = """# Typed declaration table
- 版: S5-example/2
表の版: v2
表の一覧: T-ONLY(任意の種類)
#### 列の型 (機械可読)
| 表 | 列 | 型 |
|---|---|---|
| T-ONLY | 識別 | ID |
| T-ONLY | 自由な列 | JSON |
#### 表 T-ONLY (機械可読)
| 自由な列 | 識別 |
|---|---|
| [] | ONLY-A |
"""


@pytest.mark.parametrize("text,expected", [(DECLARED, {"T-LINK", "T-EXTRA"}), (DECLARED_TYPES, {"T-ONLY"})])
def test_explicit_tables_columns_and_kinds_override_fb_defaults(text, expected):
    data = rules.parse_paper(text)
    assert set(data["tables"]) == expected
    assert data["declaration_source"] == "紙の明示宣言"
    file = MemoryFile()
    rules.generate(data, file)
    assert rules.diff(data, rules.load_generated(file))["matches"]
    result = rules.check(data, text)
    assert result["syntax_ok"]
    assert not result["ok"]
    assert result["structural_check"].startswith("not_run")


@pytest.mark.parametrize("old,new", [
    ("T-LINK(参照)", "T-LINK(参照) T-MISSING(別の種類)"),
    ("T-EXTRA(新しい種類)", "T-UNKNOWN(新しい種類)"),
    ("対象【契約】", "対象【未定義の型】"),
    ("対象【契約】", "型の無い列"),
    ("LINK-A | S5:12", "LINK-MISSING | S5:12"),
    ("ID参照:T-LINK", "ID参照:T-MISSING"),
    ("EXTRA-A |", "LINK-A |"),
    ("| UE |", "| missing |"),
    ("sui.fb.example/1", "example/1"),
    ("/many/*[kind=clock]/value/source?", "/many?/child"),
    ("| update |", "| invalid-use |"),
    ("{\"allow\":true}", "{\"allow\":NaN}"),
])
def test_explicit_declaration_still_fails_closed(old, new):
    with pytest.raises(rules.TableError):
        rules.parse_paper(DECLARED.replace(old, new, 1))


def test_unused_and_conflicting_type_declarations_fail():
    with pytest.raises(rules.TableError, match="unused"):
        rules.parse_paper(DECLARED_TYPES.replace("| T-ONLY | 自由な列 | JSON |", "| T-ONLY | 自由な列 | JSON |\n| T-ONLY | 存在しない列 | JSON |"))
    with pytest.raises(rules.TableError, match="conflicting"):
        rules.parse_paper(DECLARED_TYPES.replace("| 自由な列 | 識別 |", "| 自由な列【文】 | 識別 |"))


def test_column_type_changes_are_a_semantic_schema_diff():
    old = rules.parse_paper(DECLARED.replace("説明【文】", "説明【紙の行】").replace("根拠【紙の行】", "根拠【文】"))
    new = rules.parse_paper(DECLARED)
    old["generator_version"] = rules.VERSION
    result = rules.diff(new, old)
    assert result["schema_changes"]
    assert not result["matches"]


def test_out_option_is_used_by_generate_and_diff(monkeypatch, capsys):
    data = rules.parse_paper(DECLARED)
    file = MemoryFile()
    rules.generate(data, file)
    generated = rules.load_generated(file)
    calls = []
    monkeypatch.setattr(rules, "read_paper", lambda path: data)
    monkeypatch.setattr(rules, "generate", lambda data, output: calls.append(("generate", output)))
    def load(path):
        calls.append(("diff", path))
        return generated
    monkeypatch.setattr(rules, "load_generated", load)
    target = "src/sui/_other_rules.py"
    assert rules.main(["generate", "--out", target, "--format", "json"]) == 0
    assert rules.main(["diff", "--out", target, "--format", "json"]) == 0
    assert calls == [("generate", Path(target)), ("diff", Path(target))]
    capsys.readouterr()


@pytest.fixture(scope="module")
def structures():
    return rules.Structures()


@pytest.mark.parametrize("contract,purpose,required,absent", [
    ("sui.fb.work_requested/1", "update", "/desc/args/prior?", "/desc/args/evaluation_request"),
    ("sui.fb.work_requested/1", "evaluate", "/desc/args/evaluation_request", "/desc/args/prior?"),
    ("sui.fb.evaluation_requested/1", "prepare", "/desc/args/input/fixed_parents/*", "/desc/args/prior?"),
    ("sui.fb.draw_requested/1", "draw", "/desc/args/request/law", "/desc/args/prior?"),
    ("sui.fb.segment_requested/1", "measurement", "/desc/args/route", "/desc/args/prior?"),
    ("sui.fb.candidate_request/1", "generated_by", "/desc/args/generator_args", "/desc/args/prior?"),
])
def test_request_args_follow_each_declared_dto_branch(structures, contract, purpose, required, absent):
    fields = rules.enumerate_fields(structures.contract_body(contract, purpose))
    paths = {x["field"] for x in fields}
    assert required in paths
    assert absent not in paths


def test_boot_slot_values_use_the_declared_concrete_types(structures):
    fields = rules.enumerate_fields(structures.contract_body("sui.fb.boot_declaration/1", "declaration"))
    assert not [x for x in fields if x["kind"] == "opaque"]
    paths = {x["field"] for x in fields}
    assert "/scope/declaration/value/quantity_contract" in paths
    assert "/routes/*/declaration/value/config/clock_contract" in paths
    assert "/initial/declaration/value/model" in paths
    assert "/environment/declaration/value/data" in paths


def test_common_header_and_outer_paths_are_enumerated(structures):
    prediction = {x["field"] for x in structures.outer_fields("sui.fb.update_result/1")}
    assert prediction == {"/parents/*", "/target", "/about/*", "/basis/*"}
    decided = {x["field"] for x in structures.outer_fields("sui.fb.work_requested/1")}
    assert decided == {"/parents/*", "/inputs/*"}
    header = {x["field"] for x in structures.common_fields("sui.fb.work_requested/1")}
    assert {"/header/schema", "/header/at/run", "/header/writer", "/header/body/type", "/header/body/contract", "/header/seal"} <= header


def test_new_dto_field_is_discovered_without_a_table_edit(structures, monkeypatch):
    dto = deepcopy(structures.nodes["fb", "UpdateArgs"])
    dto.body.append(ast.parse("new_field: Point").body[0])
    monkeypatch.setitem(structures.nodes, ("fb", "UpdateArgs"), dto)
    paths = {x["field"] for x in rules.enumerate_fields(structures.contract_body("sui.fb.work_requested/1", "update"))}
    assert "/desc/args/new_field" in paths


def test_new_saved_dictionary_key_is_discovered(structures, monkeypatch):
    tree = deepcopy(structures.trees["_fb_update"])
    monkeypatch.setitem(structures.trees, "_fb_update", tree)
    function = structures.function("_fb_update", ("_monitor_step", "build"))
    content = next(n.value for n in ast.walk(function) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "content" for t in n.targets))
    content.keys.append(ast.Constant(value="added_field"))
    content.values.append(ast.copy_location(ast.Constant(value=7), content))
    paths = {x["field"] for x in rules.enumerate_fields(structures.contract_body("sui.fb.monitor_span/1", "support"))}
    assert "/added_field" in paths


def test_f_wire_variants_follow_the_encoder_field_sets(structures):
    shape = structures.dto("f", "ExactReal")
    assert shape.kind == "wire_variants"
    variants = {tag: {name for name, _ in value.children} for selector, tag, value in shape.children}
    assert variants["rational"] == {"op", "value"}
    assert variants["log"] == {"op", "arg"}
    assert variants["div"] == {"op", "numerator", "denominator"}


def test_update_result_type_follows_the_issued_factory(structures):
    fields = rules.enumerate_fields(structures.contract_body("sui.fb.update_result/1", "generation"))
    paths = {x["field"] for x in fields}
    assert {"/result/joint/*", "/result/evidence_mass"} <= paths
    assert "/numerical_view/environment/registry_key?" in paths


def test_dictionary_body_is_bound_to_its_contract_branch(structures):
    fields = rules.enumerate_fields(structures.contract_body("sui.fb.belief_adopted/1", "adopt"))
    paths = {x["field"] for x in fields}
    assert {"/origin", "/model", "/request", "/result", "/acquisition", "/previous?"} <= paths
    assert "/actual_previous?" not in paths
    assert "/expected_previous" not in paths


def test_non_string_mapping_keys_follow_f_wire_arrays(structures):
    fields = rules.enumerate_fields(structures.annotation(ast.parse("Mapping[tuple[str, int], str]", mode="eval").body, "f"), "/mapping")
    assert {x["field"] for x in fields} == {"/mapping/*/key/0", "/mapping/*/key/1", "/mapping/*/value"}


@pytest.mark.parametrize("contract,purpose", [
    ("sui.fb.belief_adopted/1", "adopt"),
    ("sui.fb.update_result/1", "generation"),
    ("sui.fb.prepared/1", "prepare"),
    ("sui.fb.evaluated/1", "evaluate"),
    ("sui.fb.selection/1", "selection"),
])
def test_typed_point_constructor_requirements_close_scalar_products(structures, contract, purpose):
    fields = rules.enumerate_fields(structures.contract_body(contract, purpose))
    assert not [f for f in fields if f["kind"] == "opaque"], fields


def test_declared_helper_return_uses_the_wire_form(structures):
    fields = rules.enumerate_fields(structures.contract_body("sui.fb.segment_binding/1", "measurement"))
    paths = {f["field"] for f in fields}
    assert {"/view/boundary/*", "/view/environment/reader_view_key", "/view/environment/registry_key?"} <= paths
    assert "/view/reader_view_key" not in paths


def test_untyped_dynamic_dict_stays_explicitly_unreadable(structures):
    expr = ast.parse("untyped['value']", mode="eval").body
    shape = structures.expression(expr, "_fb_update", {})
    assert shape.kind == "opaque"
    assert "untyped['value']" in shape.source


def helper_reader(monkeypatch, source):
    reader = fixture_structures()
    reader.trees = {"fixed": ast.parse(source)}
    reader.contract_constants = {"EXAMPLE": {"sui.fb.helper/1"}}
    reader.scalar_constraints = lambda function, env: env
    monkeypatch.setitem(rules.DICT_BINDINGS, "sui.fb.helper/1", ("fixed", ("factory", "build")))
    return reader


@pytest.mark.parametrize("location", ["nested", "module"])
@pytest.mark.parametrize("arguments", ['"opaque", count=4', '"opaque"'])
def test_dictionary_payload_follows_literal_return_helpers(monkeypatch, location, arguments):
    helper = 'def content_of(q: Point, *, count: int = 3):\n    return {"request": q, "count": count}\n'
    nested = "\n".join("    " + line for line in helper.splitlines()) + "\n"
    source = (helper if location == "module" else "") + 'def factory():\n'
    source += nested if location == "nested" else ""
    source += ('    def build():\n        return _Observed(contract=_c.EXAMPLE, '
               'content=_Payload.json(content_of(' + arguments + ')))\n')
    fields = rules.enumerate_fields(helper_reader(monkeypatch, source).dictionary_body("sui.fb.helper/1"))
    assert {f["field"]: f["field_type"] for f in fields} == {"/request": "point", "/count": "value"}


def test_nested_helper_captures_factory_but_not_builder_locals(monkeypatch):
    source = '''def factory(captured: Point):
    def content_of():
        return {"request": captured}
    def build():
        captured = 5
        return _Observed(contract=_c.EXAMPLE, content=_Payload.json(content_of()))
'''
    fields = rules.enumerate_fields(helper_reader(monkeypatch, source).dictionary_body("sui.fb.helper/1"))
    assert fields[0]["field_type"] == "point"


@pytest.mark.parametrize("helper,extra", [
    ('def content_of():\n    return {"request": captured}\n', ""),
    ('def content_of():\n    return dynamic\n', ""),
    ('def content_of():\n    if flag:\n        return {"a": 1}\n    return {"b": 2}\n', ""),
    ('def content_of():\n    return {"a": 1}\n', "        content_of = dynamic\n"),
    ('def content_of():\n    raise RuntimeError("never execute")\n    return {"a": 1}\n', ""),
])
def test_dictionary_helpers_do_not_guess_or_execute(monkeypatch, helper, extra):
    source = helper + '''def factory():
    def build():
        captured = "sha256:caller-local"
''' + extra + '''        return _Observed(contract=_c.EXAMPLE, content=_Payload.json(content_of()))
'''
    fields = rules.enumerate_fields(helper_reader(monkeypatch, source).dictionary_body("sui.fb.helper/1"))
    assert any(f["kind"] == "opaque" for f in fields)


def with_application(mode, position=6):
    lines = EXAMPLE.splitlines()
    start = lines.index("#### 表 T-G6 (機械可読)")
    for offset, value in ((1, "適用方式"), (2, "---"), (3, mode)):
        cells = list(rules.row_cells(lines[start + offset], start + offset + 1))
        cells.insert(position, value)
        lines[start + offset] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines)


@pytest.mark.parametrize("mode", ["同時", "対象別", "共通"])
@pytest.mark.parametrize("position", [1, 6, 7])
def test_application_modes_are_explicit_and_survive_generation(mode, position):
    data = rules.parse_paper(with_application(mode, position))
    assert data["tables"]["T-G6"][0]["application"] == mode
    file = MemoryFile()
    rules.generate(data, file)
    current = rules.load_generated(file)
    assert current["tables"]["T-G6"][0]["application"] == mode
    assert rules.diff(data, current)["matches"]


@pytest.mark.parametrize("mode", ["全部", "-", "未確定"])
def test_application_vocabulary_is_closed(mode):
    with pytest.raises(rules.TableError):
        rules.parse_paper(with_application(mode))


def test_legacy_g6_has_an_explicit_none_application():
    data = rules.parse_paper(EXAMPLE)
    assert data["tables"]["T-G6"][0]["application"] is None
    file = MemoryFile()
    rules.generate(data, file)
    assert rules.load_generated(file)["tables"]["T-G6"][0]["application"] is None


def typed_fixture(monkeypatch, annotation="Point"):
    reader = fixture_structures()
    tree = ast.parse('''class Example:
    left: ''' + annotation + '''
    right: Ref
    value: ContractRef
    items: tuple[Point, ...]
    nullable: Point | None
    scalar_union: Point | Ref
    readings: tuple[ReadingEvidence, ...]
''')
    reader.nodes["fb", "Example"] = tree.body[0]
    monkeypatch.setattr(rules, "Structures", lambda root: reader)
    monkeypatch.setitem(rules.DTO_BINDINGS, "sui.fb.example/1", ("fb", "Example"))
    return reader


def test_field_types_use_declarations_arrays_union_and_wire_branches(monkeypatch):
    typed_fixture(monkeypatch)
    data = rules.parse_paper(EXAMPLE)
    types = rules.field_types(data)
    at = lambda path: types["sui.fb.example/1", path]
    assert at("/left") == "point"
    assert at("/right") == "ref"
    assert at("/value") == "value"  # ContractRef is a closed value, not Record Ref.
    assert at("/items/*") == "point"
    assert at("/nullable?") == at("/scalar_union") == "union"
    assert at("/readings/*[kind=clock]/kind") == "value"
    assert at("/readings/*[kind=clock]/value/source") == "value"
    assert len(types) == rules.check(data, EXAMPLE)["field_count"]


def test_field_type_aliases_keep_the_declared_reference_kind():
    reader = fixture_structures()
    reader.imports = {("fb", "RenamedRef"): ("ids", "Ref")}
    reader.aliases["fb", "PointAlias"] = ast.Name(id="Point")
    for annotation, expected in (("RenamedRef", "ref"), ("PointAlias", "point"), ("str", "value")):
        shape = reader.annotation(ast.Name(id=annotation), "fb")
        assert rules.enumerate_fields(shape)[0]["field_type"] == expected


def test_partial_contracts_have_no_guessed_field_types(monkeypatch):
    typed_fixture(monkeypatch, "object")
    types = rules.field_types(rules.parse_paper(EXAMPLE))
    assert types and set(types.values()) == {"unknown"}


def test_field_types_never_guess_from_hash_or_ref_looking_strings():
    reader = fixture_structures()
    for value in ("sha256:deadbeef", "observation:someone"):
        field = rules.enumerate_fields(reader.expression(ast.parse(repr(value), mode="eval").body, "fb", {}))[0]
        assert field["field_type"] == "value"


def test_field_type_change_is_a_semantic_diff_without_table_changes(monkeypatch):
    reader = typed_fixture(monkeypatch)
    data, file = rules.parse_paper(EXAMPLE), MemoryFile()
    rules.generate(data, file)
    current = rules.load_generated(file)
    assert rules.diff(data, current)["matches"]
    reader.nodes["fb", "Example"].body[0].annotation = ast.Name(id="Ref")
    result = rules.diff(data, current)
    assert not result["matches"] and not result["changes"]
    assert result["field_type_changes"] == [{"contract": "sui.fb.example/1", "field": "/left",
                                             "change": "modified", "old": "point", "new": "ref"}]
    assert "/left" in rules.human(result, "diff")


def test_old_generated_module_without_field_types_is_readable_but_differs(monkeypatch):
    typed_fixture(monkeypatch)
    data, file = rules.parse_paper(EXAMPLE), MemoryFile()
    rules.generate(data, file)
    replace_generated_assignment(file, "FIELD_TYPES", "")
    current = rules.load_generated(file)
    assert current["field_types"] == {}
    assert rules.diff(data, current)["field_type_changes"]


@pytest.mark.parametrize("literal", ['{("bad", "/left"): "point"}',
                                      '{("sui.fb.example/1", "left"): "point"}',
                                      '{("sui.fb.example/1", "/left"): "str"}'])
def test_generated_field_types_fail_closed(literal):
    file = MemoryFile()
    rules.generate(rules.parse_paper(EXAMPLE), file)
    replace_generated_assignment(file, "FIELD_TYPES", "FIELD_TYPES = " + literal)
    with pytest.raises(rules.TableError, match="FIELD_TYPES"):
        rules.load_generated(file)


def replace_generated_assignment(file, name, replacement):
    node = next(n for n in ast.parse(file.text).body if isinstance(n, ast.Assign) and n.targets[0].id == name)
    lines = file.text.splitlines()
    file.text = "\n".join([*lines[:node.lineno - 1], replacement, *lines[node.end_lineno:]])


def atomic_example(atoms=None, declarations=None):
    text = EXAMPLE.replace(ATOM_TEXT, json.dumps(FIXED_ATOMS if atoms is None else atoms, ensure_ascii=False))
    if declarations is not None:
        text = text.replace(json.dumps(FIXED_DECLARATIONS, ensure_ascii=False), json.dumps(declarations, ensure_ascii=False))
    return text


@pytest.mark.parametrize("case", ["rel", "derive", "record", "duplicate", "unary_right", "binary_missing",
                                  "when", "on_fail", "effect", "from", "unavailable_evidence", "via", "empty"])
def test_atomic_relations_fail_closed_with_row_diagnostics(case):
    atoms = deepcopy(FIXED_ATOMS)
    if case == "rel": atoms[0]["rel"] = "approximately_equal"
    if case == "derive": atoms[0]["left"] = {"derive": "not_declared", "args": []}
    if case == "record": atoms[0]["left"] = "Other:/field"
    if case == "duplicate": atoms *= 2
    if case == "unary_right": atoms[0]["right"] = {"literal": 1}
    if case == "binary_missing": atoms[0]["rel"] = "equal"
    if case == "when": atoms[0]["when"] = {"unknown": True}
    if case == "on_fail": atoms[0]["on_fail"] = "成功"
    if case == "effect": atoms[0]["left"] = {"derive": "effect", "args": [{"literal": "invented"}]}
    if case == "from": atoms[0]["left"] = {"from": "invented", "where": {}, "select": "one", "path": ""}
    if case == "unavailable_evidence": atoms[0]["left"] = {"from": "uses", "where": {}, "select": "one", "path": ""}
    if case == "via": atoms[0]["left"] = {"derive": "via", "args": [{"literal": "REF-ABSENT"}, "Q*:"]}
    if case == "empty": atoms = []
    with pytest.raises(rules.TableError, match=r":\d+:.*"):
        rules.parse_paper(atomic_example(atoms))


@pytest.mark.parametrize("rel", rules.RELATION_VOCABULARY)
def test_all_nine_atomic_relations_have_the_declared_arity(rel):
    atom = {"id": "FIXED-REL", "left": "Q*:", "rel": rel, "on_fail": "不適合"}
    if rel not in rules.UNARY_RELATIONS:
        atom["right"] = {"literal": [None, 1, "literal text"]}
    assert rules.parse_paper(atomic_example([atom]))["atom_count"] == 1


PUBLIC_MISMATCH_CODES = (
    "schema", "shape", "noncanonical", "rational", "unit", "unknown_version", "normalization",
    "unresolved_reference", "reference_kind", "observation_binding_mismatch", "measurement_conflict",
    "clock_unaligned", "missing_contract", "model_falsified", "outside_evaluation_type",
    "result_mismatch", "proof_mismatch",
)


@pytest.mark.parametrize("code", PUBLIC_MISMATCH_CODES)
def test_all_public_mismatch_codes_are_preserved_without_defaults(code):
    atom = {"id": "CODED", "left": "Q*:", "rel": "present", "on_fail": "不適合", "code": code}
    uncoded = {"id": "UNCODED", "left": "Q*:", "rel": "present", "on_fail": "不適合"}
    data, file = rules.parse_paper(atomic_example([atom, uncoded])), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["generated_extras"]["A1_RELATIONS"]["A1-EXAMPLE"] == [atom, uncoded]
    assert "code" not in loaded["tables"]["T-A1"][0]["relation"][1]
    assert loaded["coded_atoms"] == 1
    assert loaded["uncoded_mismatch_atoms"] == ["UNCODED"]
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("code", ["invented", "", None, 17, [], {}])
def test_unknown_or_non_string_mismatch_code_fails_with_row_diagnostic(code):
    atom = {"id": "BAD-CODE", "left": "Q*:", "rel": "present", "on_fail": "不適合", "code": code}
    with pytest.raises(rules.TableError, match=r":\d+:.*code"):
        rules.parse_paper(atomic_example([atom]))


@pytest.mark.parametrize("on_fail", ["不足", "使用の禁止"])
def test_code_is_forbidden_on_non_mismatch_atoms(on_fail):
    atom = {"id": "BAD-FAILURE", "left": "Q*:", "rel": "present", "on_fail": on_fail, "code": "shape"}
    with pytest.raises(rules.TableError, match="code"):
        rules.parse_paper(atomic_example([atom]))


def test_mismatch_code_metadata_is_checked_by_diff():
    atom = {"id": "UNCODED", "left": "Q*:", "rel": "present", "on_fail": "不適合"}
    data, file = rules.parse_paper(atomic_example([atom])), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    loaded["coded_atoms"] = 999
    loaded["uncoded_mismatch_atoms"] = []
    result = rules.diff(data, loaded)
    assert not result["matches"]
    assert {x["field"] for x in result["provenance_changes"]} == {"coded_atoms", "uncoded_mismatch_atoms"}


def test_code_grammar_is_shared_by_ref_assertions_and_enumeration_atoms():
    atom = {"id": "SHARED-CODE", "left": "SELF:", "rel": "present", "on_fail": "不適合", "code": "shape"}
    condition = json.dumps({"assert": [atom]}, ensure_ascii=False)
    text = EXAMPLE.replace("| E | true | fixed:2 |", "| E | " + condition + " | fixed:2 |", 1)
    assert rules.parse_paper(text)["tables"]["T-REF"][2]["condition"]["assert"][0] == atom
    with pytest.raises(rules.TableError, match="code"):
        rules.parse_paper(text.replace('"code": "shape"', '"code": "invented"'))
    declarations = enumeration_example()
    block = declarations["ENUMERATIONS"]["SMALL_ENUM"]
    block["mode"] = "relations"
    block["items"] = [{**atom, "left": "Q*:", "when": True}]
    assert rules.parse_paper(atomic_example(declarations=declarations))["enumeration_item_count"] == 1
    block["items"][0]["code"] = "invented"
    with pytest.raises(rules.TableError, match="code"):
        rules.parse_paper(atomic_example(declarations=declarations))


@pytest.mark.parametrize("mode", ["relations", "pairs"])
def test_ref_assert_codes_roundtrip_without_expanding_the_a1_metadata_denominator(mode):
    """Only T-A1 contributes to the counters; other obligations retain their data."""
    a1_atoms = [
        {"id": "A1-CODED", "left": "Q*:", "rel": "present", "on_fail": "不適合", "code": "shape"},
        {"id": "A1-UNCODED", "left": "Q*:", "rel": "present", "on_fail": "不適合"},
    ]
    assertions = [{**a, "id": a["id"].replace("A1-", "REF-"), "left": "SELF:"} for a in a1_atoms]
    declarations = enumeration_example()
    block = declarations["ENUMERATIONS"]["SMALL_ENUM"]
    block["mode"] = mode
    block["items"] = ([{**a, "id": a["id"].replace("A1-", "ENUM-"), "when": True} for a in a1_atoms]
                      if mode == "relations" else [{"id": "ENUM-PAIR", "kind": "equal", "left": "Q*:",
                                                      "right": {"literal": 1}, "when": True}])
    condition = {"assert": assertions}
    text = atomic_example(a1_atoms, declarations).replace(
        "| E | true | fixed:2 |", "| E | " + json.dumps(condition, ensure_ascii=False) + " | fixed:2 |", 1)
    data, file = rules.parse_paper(text), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["tables"]["T-REF"][2]["condition"] == condition
    assert loaded["generated_extras"]["SMALL_ENUM"] == block
    assert loaded["coded_atoms"] == 1
    assert loaded["uncoded_mismatch_atoms"] == ["A1-UNCODED"]
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("collection", ["executions", "uses", "intervals", "acquisitions", "EW", "EH"])
def test_nested_operands_bind_only_declared_evidence(collection):
    atom = {"id": "NESTED", "left": {"derive": "point_of", "args": [
        {"from": collection, "where": {"/work_id": "Q*:/desc/work_id"}, "select": "one", "path": ""}]},
        "rel": "equal", "right": {"derive": "effect", "args": [{"literal": "actual"}]}, "on_fail": "不適合"}
    text = atomic_example([atom]).replace('["台帳"]', '["台帳","EW","EH","EI","EA"]')
    assert rules.parse_paper(text)["a1_relations"]["A1-EXAMPLE"] == [atom]


def test_legacy_relation_object_is_unclassified_not_success(monkeypatch):
    text = EXAMPLE.replace(ATOM_TEXT, '{"compare":"all_bytes"}')
    data = rules.parse_paper(text)
    reader = fixture_structures()
    monkeypatch.setattr(rules, "Structures", lambda root: reader)
    monkeypatch.setitem(rules.DTO_BINDINGS, "sui.fb.example/1", ("fb", "Example"))
    result = rules.check(data, text)
    assert not result["ok"] and not data["complete"]
    assert result["unclassified_count"] == 1
    assert result["unclassified"][0]["field"] == "A1-EXAMPLE.relation"
    assert result["unatomized_a1"][0]["id"] == "A1-EXAMPLE"
    file = MemoryFile()
    rules.generate(data, file)
    assert rules.load_generated(file)["complete"] is False


def test_only_the_declared_legacy_subject_is_normalized():
    text = EXAMPLE.replace("A1-EXAMPLE", "A1-I-UNIQUE").replace('{"scope":"requests","records":["Q*"]}', "再構成用途で届いた全Q*")
    data = rules.parse_paper(text)
    assert data["a1_subjects"]["A1-I-UNIQUE"] == {"scope": "requests", "records": ["Q*"]}
    with pytest.raises(rules.TableError):
        rules.parse_paper(text.replace("A1-I-UNIQUE", "A1-OTHER"))


def test_generated_relations_and_nested_operands_are_immutable_and_roundtrip():
    atom = {"id": "IMMUTABLE", "left": {"derive": "point_of", "args": ["Q*:"]}, "rel": "present", "on_fail": "不足"}
    data, file = rules.parse_paper(atomic_example([atom])), MemoryFile()
    rules.generate(data, file)
    assert rules.diff(data, rules.load_generated(file))["matches"]
    namespace = {}
    exec(compile(file.text, "<generated fixed example>", "exec"), namespace)
    relations = namespace["A1_RELATIONS"]
    assert isinstance(relations["A1-EXAMPLE"], tuple)
    assert relations["A1-EXAMPLE"][0]["left"]["args"] == ("Q*:",)
    with pytest.raises(TypeError): relations["invented"] = ()
    with pytest.raises(TypeError): relations["A1-EXAMPLE"][0]["rel"] = "absent"
    with pytest.raises(TypeError): namespace["A1_SUBJECTS"]["A1-EXAMPLE"]["scope"] = "invented"


def test_mapping_proxy_loader_never_executes_other_calls():
    file = MemoryFile()
    rules.generate(rules.parse_paper(EXAMPLE), file)
    file.text = file.text.replace("_MP({", "__import__({", 1)
    with pytest.raises(rules.TableError): rules.load_generated(file)


def enumeration_example():
    d = deepcopy(FIXED_DECLARATIONS)
    d["DERIVATIONS"].update(enumeration_source="one independent source", enumeration_arguments="actual arguments", tuple="ordered values")
    d["ENUMERATION_SOURCES"] = {"item_field": {"shape": "one value", "origin": "one primary item", "source": "fixed:1"}}
    modes = ["pairs", "obligations", "record", "records", "relations", "cases", "values", "union", "components", "event_kinds", "dimensions", "component_schema"]
    conditions = ["nonnull", "is_null", "item_kind", "generation", "support_required", "method", "stage", "argument", "provenance"]
    coverage = {k: "declared coverage" for k in ("declaration_ids", "instance_ids", "actual", "comparison", "inactive", "empty", "test_expected")}
    coverage.update(on_missing_declaration_or_adapter="不足", on_missing_returned_id_or_field="不適合",
                    on_duplicate_or_extra_id="不適合", on_missing_primary_evidence="不足", on_unknown_condition="不足",
                    test_operations=["drop_case", "drop_instance", "drop_component", "duplicate_instance", "alter_value"])
    d["ENUMERATION_PROTOCOL"] = {"version": 1, "modes": modes, "condition_keys": conditions, "coverage": coverage,
        "source_policy": "primary sources", "recursive_guard": "no producer", "table_links": "actual outcomes",
        "result_policy": "unchanged shape", "status_policy": "no implicit approval",
        "conditions": {k: "declared condition" for k in ["true", *conditions]}, "outputs": {k: "declared output" for k in modes}}
    d["ENUMERATIONS"] = {"SMALL_ENUM": {"consumers": ["point_of"], "scopes": ["requests"], "mode": "values",
        "items": [{"id": "CASE-ONE", "when": True, "value": {"derive": "enumeration_source", "args": [{"literal": "item_field"}, {"literal": "/field"}]}}], "source": "fixed:1"}}
    d["DERIVATION_ENUMERATION_INVENTORY"] = {"reviewed": 3, "entries": {
        "point_of": {"class": "ア", "blocks": ["SMALL_ENUM"]}, "effect": {"class": "イ", "reason": "one value"},
        "via": {"class": "イ", "reason": "one reference"}}, "added_helpers": ["enumeration_source", "enumeration_arguments", "tuple"]}
    return d


@pytest.mark.parametrize("case", ["derive", "source", "consumer", "scope", "when", "duplicate", "mode", "mapping", "inventory_missing", "item_key"])
def test_enumeration_templates_and_inventory_fail_closed(case):
    d = enumeration_example()
    block = d["ENUMERATIONS"]["SMALL_ENUM"]
    item = block["items"][0]
    if case == "derive": item["value"]["args"].append({"derive": "missing", "args": []})
    if case == "source": item["value"]["args"][0]["literal"] = "missing"
    if case == "consumer": block["consumers"] = ["missing"]
    if case == "scope": block["scopes"] = ["missing"]
    if case == "when": item["when"] = {"invented": True}
    if case == "duplicate": block["items"] *= 2
    if case == "mode": block["mode"] = "guess"
    if case == "mapping": d["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["point_of"]["blocks"] = ["MISSING"]
    if case == "inventory_missing": del d["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["effect"]
    if case == "item_key": item["new_operand"] = "Q*:"
    with pytest.raises(rules.TableError): rules.parse_paper(atomic_example(declarations=d))


def test_enumeration_declarations_are_named_exports_and_semantic_diff():
    data, file = rules.parse_paper(atomic_example(declarations=enumeration_example())), MemoryFile()
    rules.generate(data, file)
    current = rules.load_generated(file)
    assert current["generated_extras"]["SMALL_ENUM"] == data["rule_declarations"]["ENUMERATIONS"]["SMALL_ENUM"]
    assert rules.diff(data, current)["matches"]
    data["rule_declarations"]["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]["value"]["args"][1]["literal"] = "/other"
    result = rules.diff(data, current)
    assert not result["matches"]
    assert {x["name"] for x in result["declaration_changes"]} == {"SMALL_ENUM", "ENUMERATIONS"}


def new_enumeration_syntax_example():
    declarations = enumeration_example()
    declarations["SCOPES"]["requests"]["records"] += ["B", "Reading", "Claim"]
    declarations["DERIVATIONS"].update(clock_pairs="actual evaluated pairs with id/kind/left/right",
        future_records="four typed sets; their union equals the original set",
        support="(B,Reading,Claim,Xnum,EW,EI,Q) returns the four declared support components")
    declarations["ENUMERATION_SOURCES"].update(
        future_record={"shape": "record or ABSENT", "origin": "Q and the named role", "source": "fixed:2"},
        support_used_records={"shape": "records or MISSING", "origin": "same Q, fixed view and actual EW uses", "source": "fixed:3"})
    blocks = declarations["ENUMERATIONS"]
    blocks["CLOCK_ITEMS"] = {"consumers": ["clock_pairs"], "scopes": ["requests"], "mode": "pairs", "source": "fixed:4",
        "items": [{"id": "CLK-ENTRY-STARTED", "when": True, "kind": "le",
                   "left": {"literal": {"run": "clock:fixed", "time_ns": 1}},
                   "right": {"literal": {"run": "clock:fixed", "time_ns": 2}}}]}
    component = blocks["SMALL_ENUM"]
    component.update(consumers=["clock_pairs"], mode="component_schema", items=[
        {"id": "FIELD-ID", "when": True, "consumer": "clock_pairs", "path": "/id",
         "value": {"literal": "CLK-ENTRY-STARTED"}, "enum_from": "ENUMERATIONS.CLOCK_ITEMS.items.id"},
        {"id": "FIELD-KIND", "when": True, "consumer": "clock_pairs", "path": "/kind",
         "value": {"literal": "le"}, "enum": ["equal", "le"]}])
    blocks["FUTURE_RECORD_ROLES"] = {"consumers": ["future_records"], "scopes": ["requests"], "mode": "record",
        "source": "fixed:5", "items": [{"id": "FUTURE-" + role.upper(), "when": True, "path": "/" + role,
            "value": {"derive": "enumeration_source", "args": [{"literal": "future_record"}, "Q*:", {"literal": role}]},
            "empty": "only independently confirmed absence; preserve the role"}
            for role in ("self", "result", "acquisition", "adoption")]}
    inventory = declarations["DERIVATION_ENUMERATION_INVENTORY"]
    inventory["entries"].update(point_of={"class": "イ", "reason": "one authenticated point"},
        clock_pairs={"class": "ア", "blocks": ["SMALL_ENUM", "CLOCK_ITEMS"]},
        future_records={"class": "ア", "blocks": ["FUTURE_RECORD_ROLES"]},
        support={"class": "イ", "reason": "fixed example primitive"})
    inventory["reviewed"] = len(inventory["entries"])
    return declarations


@pytest.mark.parametrize("consumer", ["clock_pairs", "future_records"])
def test_inventory_class_a_optional_reason_roundtrip(consumer):
    declarations = new_enumeration_syntax_example()
    declarations["DERIVATION_ENUMERATION_INVENTORY"]["entries"][consumer]["reason"] = "fixed components; preserve all dynamic occurrences"
    data, file = rules.parse_paper(atomic_example(declarations=declarations)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["generated_extras"]["DERIVATION_ENUMERATION_INVENTORY"] == declarations["DERIVATION_ENUMERATION_INVENTORY"]
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("reason", ["", None, 17, [], {}])
def test_inventory_class_a_reason_requires_a_nonempty_description(reason):
    declarations = new_enumeration_syntax_example()
    declarations["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["clock_pairs"]["reason"] = reason
    with pytest.raises(rules.TableError, match="missing classification reason"):
        rules.parse_paper(atomic_example(declarations=declarations))


def test_inventory_class_a_optional_reason_does_not_open_unknown_keys():
    declarations = new_enumeration_syntax_example()
    entry = declarations["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["clock_pairs"]
    entry.update(reason="fixed components", explanation="undeclared key")
    with pytest.raises(rules.TableError, match="unknown/missing object keys"):
        rules.parse_paper(atomic_example(declarations=declarations))


@pytest.mark.parametrize("path", [
    "/*[id=CLK-ENTRY-STARTED]/left/run",
    "/*[kind=le][id=CLK-ENTRY-STARTED]/left/run",
    "/*[id=CLK-ENTRY-STARTED][kind=le]/right/run",
])
def test_id_and_multiple_selectors_roundtrip_with_code(path):
    declarations = new_enumeration_syntax_example()
    atom = {"id": "SELECTED-PAIR", "left": {"derive": "clock_pairs", "args": [], "path": path},
            "rel": "present", "on_fail": "不適合", "code": "clock_unaligned"}
    data, file = rules.parse_paper(atomic_example([atom], declarations)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["generated_extras"]["A1_RELATIONS"]["A1-EXAMPLE"] == [atom]
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("path", ["/*[code=shape]/left", "/*[id=]/left", "/*[id=CLK-STARTED/left",
                                  "/*[kind=le][other=CLK-STARTED]/left", "/*[id=CLK-STARTED]?/left"])
def test_unknown_and_malformed_selectors_still_fail(path):
    atom = {"id": "BAD-SELECTOR", "left": {"derive": "point_of", "args": ["Q*:"], "path": path},
            "rel": "present", "on_fail": "不足"}
    with pytest.raises(rules.TableError):
        rules.parse_paper(atomic_example([atom]))


def test_new_component_constraints_future_roles_and_support_arguments_roundtrip():
    declarations = new_enumeration_syntax_example()
    support_args = ["B:", "Reading:", "Claim:", {"derive": "point_of", "args": ["Q*:"]}, "EW:", "EI:", "Q*:"]
    atoms = [
        {"id": "SUPPORT-ARGS", "left": {"derive": "support", "args": support_args}, "rel": "present", "on_fail": "不足"},
        {"id": "SUPPORT-USED", "left": {"derive": "enumeration_source", "args": [
            {"literal": "support_used_records"}, "Q*:", "B:", "Reading:", "Claim:",
            {"derive": "point_of", "args": ["Q*:"]}, "EW:"]}, "rel": "present", "on_fail": "不足"},
    ]
    text = atomic_example(atoms, declarations).replace('["台帳"]', '["台帳","EW","EI"]')
    data, file = rules.parse_paper(text), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    extras = loaded["generated_extras"]
    assert extras["SMALL_ENUM"] == declarations["ENUMERATIONS"]["SMALL_ENUM"]
    assert extras["FUTURE_RECORD_ROLES"] == declarations["ENUMERATIONS"]["FUTURE_RECORD_ROLES"]
    assert extras["DERIVATIONS"]["future_records"] == declarations["DERIVATIONS"]["future_records"]
    assert extras["ENUMERATION_SOURCES"]["support_used_records"] == declarations["ENUMERATION_SOURCES"]["support_used_records"]
    assert extras["A1_RELATIONS"]["A1-EXAMPLE"] == atoms
    assert extras["A1_RELATIONS"]["A1-EXAMPLE"][0]["left"]["args"][-1] == "Q*:"
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("case", ["enum_empty", "enum_object", "enum_duplicate", "enum_from_unknown",
                                  "enum_from_path", "enum_from_type", "empty_type", "unknown_key"])
def test_new_enumeration_constraints_fail_closed(case):
    declarations = new_enumeration_syntax_example()
    fields = declarations["ENUMERATIONS"]["SMALL_ENUM"]["items"]
    if case == "enum_empty": fields[1]["enum"] = []
    if case == "enum_object": fields[1]["enum"] = {"allowed": "le"}
    if case == "enum_duplicate": fields[1]["enum"] = ["le", "le"]
    if case == "enum_from_unknown": fields[0]["enum_from"] = "ENUMERATIONS.MISSING.items.id"
    if case == "enum_from_path": fields[0]["enum_from"] = "ENUMERATIONS.CLOCK_ITEMS.items.kind"
    if case == "enum_from_type": fields[0]["enum_from"] = ["CLK-ENTRY-STARTED"]
    if case == "empty_type": declarations["ENUMERATIONS"]["FUTURE_RECORD_ROLES"]["items"][0]["empty"] = {"guess": True}
    if case == "unknown_key": fields[0]["enum_guess"] = ["CLK-ENTRY-STARTED"]
    with pytest.raises(rules.TableError):
        rules.parse_paper(atomic_example(declarations=declarations))


@pytest.mark.parametrize("case", ["consumer", "inventory"])
def test_component_consumer_and_inventory_must_agree_with_new_fields(case):
    declarations = new_enumeration_syntax_example()
    if case == "consumer":
        declarations["ENUMERATIONS"]["SMALL_ENUM"]["consumers"] = ["point_of"]
        reason = "unknown item consumer"
    else:
        declarations["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["clock_pairs"]["blocks"] = ["CLOCK_ITEMS"]
        reason = "consumer/block mapping broken"
    with pytest.raises(rules.TableError, match=reason):
        rules.parse_paper(atomic_example(declarations=declarations))


def atom_protocol_example():
    """A small declared grammar, independent of the real paper and its counts."""
    d = enumeration_example()
    d.pop("ENUMERATION_PROTOCOL")
    helpers = {"project": [2, 3], "set_from": [1], "rule_data": [1], "declared_blocks": [1],
               "expected_instances": [2], "captured_instances": [2], "source_instances": [2],
               "support_requirement": [3], "declaration_instances": [2]}
    d["DERIVATIONS"].update({name: "fixed helper" for name in [*helpers, "contract_ref"]})
    d["DERIVATION_ENUMERATION_INVENTORY"]["added_helpers"] += [*helpers, "contract_ref"]
    d["EFFECTS"]["derivation_return"] = "actual return captured for CALL"
    d["ENUMERATION_SOURCES"]["primary"] = {"shape": "one value", "origin": "actual primary argument", "source": "fixed:1"}
    d["ATOM_PROTOCOL"] = {
        "version": 2,
        "atom": {"required": ["id", "left", "rel", "on_fail"], "optional": ["right", "code", "when", "each"],
                 "unary": ["present", "absent", "unique"], "binary": ["equal", "not_equal", "le", "lt", "member_of", "subset_of"],
                 "on_fail": ["不足", "不適合", "使用の禁止"], "code_required_when": "不適合",
                 "code_forbidden_when": ["不足", "使用の禁止"], "codes": ["shape", "proof_mismatch"], "additional_keys": False},
        "operand": {"literal": {"required": ["literal"], "additional_keys": False},
                    "derivation": {"required": ["derive", "args"], "optional": ["path"], "additional_keys": False}},
        "predicate": {"required": ["left", "rel"], "optional": ["right"], "additional_keys": False},
        "each": {"required": ["bind", "in", "select"], "optional": [], "additional_keys": False,
                 "select": ["all", "any", "one"], "shadowing": "forbidden"},
        "group": {"block_required": ["consumers", "scopes", "prelude", "items", "source"],
                  "block_optional": ["when", "each", "data"], "item_required": ["id", "when", "prelude", "atoms"],
                  "item_optional": ["each", "source", "data"], "additional_keys": False},
        "reuse": {"required": ["use"], "additional_keys": False, "phase": "compile_time_only", "expand_all": True,
                  "id_template": "<item-id>::<referenced-atom-id>", "cycles": "reject"},
        "environment": {"CALL": {"origin": "actual invocation"}, "BINDINGS": {"origin": "primary expander"},
                        "lexical": ["ITEM", "FRAME", "DIMENSION", "EVENT", "BLOCK", "SOURCE"]},
        "capture": {"effect": "derivation_return", "projection_selector": {
            "required": ["block", "case", "component"], "additional_keys": False}},
        "component_instances": {"required": ["each", "when", "source"], "additional_keys": False},
        "migration_map": {"required": ["block", "atoms"], "additional_keys": False},
        "helper_signatures": {name: {"arities": arities} for name, arities in helpers.items()},
        "new_source_signatures": {"primary": 1},
        "legacy_atom_when": {"phase": "compile_time_only", "unknown_key": "syntax_error",
            "nonnull": {"left": {"parameter": "value"}, "rel": "not_equal", "right": {"literal": None}},
            "generation": {"left": "Q*:/contract", "rel": "equal",
                "right": {"derive": "contract_ref", "args": [{"literal": {"parameter": "value"}}]}}},
    }
    d["ENUMERATIONS"] = {"SMALL_ENUM": {"consumers": ["point_of"], "scopes": ["requests"], "prelude": [],
        "items": [{"id": "CASE-ONE", "when": [], "prelude": [], "atoms": [
            {"id": "CASE-ONE-CHECK", "left": "Q*:", "rel": "present", "on_fail": "不足"}], "data": {"value": 1}}], "source": "fixed:1"}}
    d["COMPONENT_INSTANCE_SOURCES"] = {}
    d["ENUMERATION_CALL_PRELUDE"] = []
    d["ENUMERATION_ID_MAP"] = {"CASE-ONE": {"block": "SMALL_ENUM", "atoms": ["CASE-ONE-CHECK"]}}
    return d


def test_declared_atom_protocol_compiles_and_roundtrips_without_a_mode():
    d = atom_protocol_example()
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["each"] = [{"bind": "ITEM", "in": {"literal": [1, 1]}, "select": "any"}]
    item["when"] = [{"left": "ITEM:", "rel": "equal", "right": {"literal": 1}}]
    item["atoms"][0]["left"] = "ITEM:"
    data, file = rules.parse_paper(atomic_example(declarations=d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["generated_extras"]["SMALL_ENUM"]["items"][0] == item
    assert loaded["enumeration_atom_count"] == 1
    assert loaded["enumeration_item_count"] == 1
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("condition", [{"nonnull": "Q*:/optional"}, {"generation": "sui.fb.example/1"}])
def test_use_expansion_compiles_all_atoms_and_declared_legacy_conditions(condition):
    d = atom_protocol_example()
    source = deepcopy(FIXED_ATOMS[0])
    source["when"] = condition
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["when"] = [{"left": {"literal": False}, "rel": "equal", "right": {"literal": True}}]
    item["prelude"] = [{"use": "A1-EXAMPLE"}]
    d["ENUMERATION_ID_MAP"]["CASE-ONE"]["atoms"].insert(0, "CASE-ONE::EXAMPLE-BYTES")
    data, file = rules.parse_paper(atomic_example([source], d)), MemoryFile()
    compiled = data["compiled_rule_declarations"]["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    assert compiled["prelude"][0]["id"] == "CASE-ONE::EXAMPLE-BYTES"
    assert compiled["prelude"][0]["when"][0] == item["when"][0]
    assert len(compiled["prelude"][0]["when"]) == 2
    assert isinstance(data["tables"]["T-A1"][0]["relation"][0]["when"], list)
    assert data["enumeration_reused_atom_count"] == 1
    rules.generate(data, file)
    assert rules.diff(data, rules.load_generated(file))["matches"]
    assert not any("use" in value for value in rules.AtomCompiler.objects(compiled))
    assert not any(set(value) == {"parameter"} for value in rules.AtomCompiler.objects(compiled))


def test_unwrapped_template_value_is_not_guessed_into_a_literal():
    d = atom_protocol_example()
    d["ATOM_PROTOCOL"]["legacy_atom_when"]["generation"]["right"]["args"] = [{"parameter": "value"}]
    source = {**FIXED_ATOMS[0], "when": {"generation": "sui.fb.example/1"}}
    with pytest.raises(rules.AtomSyntaxError, match="invalid operand"):
        rules.parse_paper(atomic_example([source], d))


def phase_protocol_example():
    """v3 defaults are declarations; no canonical inventory is repaired here."""
    d = atom_protocol_example()
    p = d["ATOM_PROTOCOL"]
    p["version"] = 3
    p["atom"]["optional"] += ["phase", "phase_reason"]
    for prefix in ("block_", "item_"):
        p["group"][prefix + "required"].append("phase")
        p["group"][prefix + "optional"] += ["phase_reason", "data_phase"]
    p["reuse"]["expansion"] = p["reuse"].pop("phase")
    p["reuse"]["phase_policy"] = "referenced atom effective phase; never inherited from the use-site parent"
    p["legacy_atom_when"]["expansion"] = p["legacy_atom_when"].pop("phase")
    p["capture"]["phase"] = "test"
    p["coverage"] = {"phase": "test"}
    p["runtime_capture"] = {"phase": "runtime", "construction_capture_required": False}
    p["phase"] = {
        "values": ["runtime", "test"],
        "default": "runtime for legacy T-A1 and T-REF assert atoms; block/item declarations are explicit",
        "reason_values": ["world_relation", "semantic_authentication", "construction_check"],
        "data_phase_values": ["runtime"], "flatten_before_filter": True,
        "migration_map_schema": {"group_required": ["test_atoms", "runtime_atoms", "runtime_rows", "obligation", "source"],
                                 "additional_keys": False},
        "ta1_migration_schema": {"required": ["id", "destination", "reason", "runtime_locations"], "additional_keys": False},
    }
    p["declaration_sections"] = {"PHASE_MIGRATION": "ID/location map", "PRIMARY_BINDINGS": "runtime declaration data"}
    d["PRIMARY_BINDINGS"] = {"phase": "runtime", "status": "fixed primary binding"}
    block = d["ENUMERATIONS"]["SMALL_ENUM"]
    block.update(phase="test", phase_reason="construction_check", data_phase="runtime")
    block["items"][0].update(phase="test", data_phase="runtime")
    d["PHASE_MIGRATION"] = {"groups": {"SMALL_ENUM": {
        "test_atoms": ["CASE-ONE-CHECK"], "runtime_atoms": [], "runtime_rows": ["A1-EXAMPLE"],
        "obligation": "primary row still executes", "source": "fixed:1"}},
        "ta1": [], "data_phase": "runtime", "status": "fixed example", "derived_fields": {}}
    return d


def test_v3_phases_and_declared_primary_data_roundtrip():
    d = phase_protocol_example()
    d["DERIVATIONS"]["supported_report_branch"] = "(Claim,Reading) -> known report branch"
    d["DERIVATION_ENUMERATION_INVENTORY"]["added_helpers"].append("supported_report_branch")
    d["ATOM_PROTOCOL"]["helper_signatures"]["supported_report_branch"] = {"arities": [2]}
    d["DERIVATIONS"]["returned_value"] = "(report,request,EW,EH) -> {result: full value}"
    d["DERIVATION_ENUMERATION_INVENTORY"]["added_helpers"].append("returned_value")
    d["EFFECTS"]["returned_value"] = "{result: actual original return}"
    atom = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]["atoms"][0]
    atom["left"] = {"derive": "supported_report_branch", "args": ["Q*:", "Q*:"]}
    data, file = rules.parse_paper(atomic_example(declarations=d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    extras = loaded["generated_extras"]
    assert extras["A1_RELATIONS"]["A1-EXAMPLE"][0]["phase"] == "runtime"
    compiled = extras["SMALL_ENUM"]["items"][0]["atoms"][0]
    assert compiled["phase"] == "test" and compiled["phase_reason"] == "construction_check"
    assert extras["SMALL_ENUM"]["items"][0]["data"] == {"value": 1}
    assert extras["SMALL_ENUM"]["items"][0]["data_phase"] == "runtime"
    assert extras["PRIMARY_BINDINGS"] == d["PRIMARY_BINDINGS"]
    assert extras["DERIVATIONS"]["returned_value"] == d["DERIVATIONS"]["returned_value"]
    assert (loaded["a1_runtime_atom_count"], loaded["a1_test_atom_count"],
            loaded["enumeration_runtime_atom_count"], loaded["enumeration_test_atom_count"]) == (1, 0, 0, 1)
    assert rules.diff(data, loaded)["matches"]
    loaded["a1_runtime_atom_count"] += 1
    assert not rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("source_phase", [None, "runtime", "test"])
@pytest.mark.parametrize("parent_phase", ["runtime", "test"])
def test_v3_use_preserves_source_phase_reason_scope_stages_evidence_and_conditions(source_phase, parent_phase):
    d = phase_protocol_example()
    source = {**FIXED_ATOMS[0], "on_fail": "不適合", "code": "proof_mismatch",
              "phase_reason": "semantic_authentication", "when": {"nonnull": "Q*:/optional"}}
    if source_phase is not None:
        source["phase"] = source_phase
    if source_phase == "test":
        d["PHASE_MIGRATION"]["ta1"] = [{"id": source["id"], "destination": "test", "reason": "fixed construction recheck",
                                      "runtime_locations": ["DERIVATIONS.point_of"]}]
        d["PHASE_MIGRATION"]["groups"]["SMALL_ENUM"]["runtime_rows"] = ["DERIVATIONS.point_of"]
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["phase"] = parent_phase
    item["atoms"][0]["phase"] = "test"
    item["prelude"] = [{"use": "A1-EXAMPLE"}]
    item["when"] = [{"left": "Q*:/active", "rel": "equal", "right": {"literal": True}}]
    d["ENUMERATION_ID_MAP"]["CASE-ONE"]["atoms"].insert(0, "CASE-ONE::EXAMPLE-BYTES")
    data, file = rules.parse_paper(atomic_example([source], d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    expanded = loaded["generated_extras"]["SMALL_ENUM"]["items"][0]["prelude"][0]
    assert expanded["phase"] == (source_phase or "runtime")
    assert expanded["phase_reason"] == source["phase_reason"]
    assert expanded["code"] == source["code"] and expanded["on_fail"] == source["on_fail"]
    assert len(expanded["when"]) == 2 and expanded["when"][0] == item["when"][0]
    row = data["tables"]["T-A1"][0]
    assert loaded["generated_extras"]["ATOM_ORIGINS"][expanded["id"]] == {
        "row_id": row["id"], "atom_id": source["id"], "subject": row["subject"],
        "stages": row["stages"], "evidence": row["evidence"]}
    assert rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("case", ["block_phase_missing", "item_phase_missing", "phase", "reason", "data_phase",
    "use_phase_override", "runtime_capture", "runtime_when_capture", "parent_when_capture", "block_when_capture",
    "runtime_each_capture", "parent_each_capture", "runtime_coverage", "runtime_manifest", "call_prelude_runtime",
    "capture_runtime", "group_map", "map_phase", "map_location", "undeclared_section", "missing_section",
    "primary_phase", "helper_arity", "inventory"])
def test_v3_invalid_phases_runtime_test_dependencies_and_migration_fail_closed(case):
    d = phase_protocol_example()
    p = d["ATOM_PROTOCOL"]
    block = d["ENUMERATIONS"]["SMALL_ENUM"]
    item, atom = block["items"][0], block["items"][0]["atoms"][0]
    capture = {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"]}
    atom["phase"] = "runtime"
    group = d["PHASE_MIGRATION"]["groups"]["SMALL_ENUM"]
    group["runtime_atoms"], group["test_atoms"] = group["test_atoms"], []
    if case == "block_phase_missing": del block["phase"]
    if case == "item_phase_missing": del item["phase"]
    if case == "phase": atom["phase"] = "both"
    if case == "reason": atom["phase_reason"] = "authorize"
    if case == "data_phase": item["data_phase"] = "test"
    if case == "use_phase_override": item["prelude"] = [{"use": "A1-EXAMPLE", "phase": "test"}]
    if case == "runtime_capture": atom["left"] = capture
    if case == "runtime_when_capture": atom["when"] = [{"left": capture, "rel": "present"}]
    if case == "parent_when_capture": item["when"] = [{"left": capture, "rel": "present"}]
    if case == "block_when_capture": block["when"] = [{"left": capture, "rel": "present"}]
    if case == "runtime_each_capture": atom["each"] = [{"bind": "ITEM", "in": capture, "select": "all"}]
    if case == "parent_each_capture": item["each"] = [{"bind": "ITEM", "in": capture, "select": "all"}]
    if case == "runtime_coverage": atom["left"] = {"derive": "expected_instances", "args": ["CALL:", "CALL:"]}
    if case == "runtime_manifest": atom["left"] = {"derive": "rule_data", "args": [{"literal": "ENUMERATION_ID_MAP"}]}
    if case == "call_prelude_runtime": d["ENUMERATION_CALL_PRELUDE"] = [dict(atom, id="CALL-PRIMARY")]
    if case == "capture_runtime": p["capture"]["phase"] = "runtime"
    if case == "group_map": group["runtime_atoms"] = []
    if case == "map_phase": group["test_atoms"], group["runtime_atoms"] = group["runtime_atoms"], []
    if case == "map_location": group["runtime_rows"] = ["ENUMERATIONS.SMALL_ENUM_missing"]
    if case == "undeclared_section": d["MADE_UP_BINDINGS"] = {"phase": "runtime"}
    if case == "missing_section": del d["PRIMARY_BINDINGS"]
    if case == "primary_phase": d["PRIMARY_BINDINGS"]["phase"] = "test"
    if case == "helper_arity": atom["left"] = {"derive": "source_instances", "args": []}
    if case == "inventory": d["DERIVATIONS"]["unclassified_helper"] = "missing classification"
    with pytest.raises(rules.TableError):
        rules.parse_paper(atomic_example(declarations=d))


def test_v3_reports_all_independent_phase_and_inventory_issues():
    d = phase_protocol_example()
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["atoms"][0]["phase"] = "unknown"
    item["atoms"].append({"id": "SECOND-PHASE-ERROR", "left": "Q*:", "rel": "present", "on_fail": "不足", "phase": "invalid"})
    d["DERIVATIONS"]["missing_classification"] = "missing inventory entry"
    inventory = d["DERIVATION_ENUMERATION_INVENTORY"]
    inventory["entries"][next(iter(inventory["entries"]))]["class"] = "unknown"
    d["PRIMARY_BINDINGS"]["phase"] = "test"
    with pytest.raises(rules.AtomSyntaxError) as got:
        rules.parse_paper(atomic_example(declarations=d))
    reasons = [issue["reason"] for issue in got.value.issues]
    assert sum("unknown phase" in reason for reason in reasons) == 2
    assert any("missing_classification" in reason for reason in reasons)
    assert any("unknown inventory class" in reason or "unknown/missing object keys" in reason for reason in reasons)
    assert any("primary declaration must be runtime" in reason for reason in reasons)


def binding_declarations_example():
    """Closed PB locations and CSB nodes, with a real partial/complete partition."""
    d = phase_protocol_example()
    d["ATOM_PROTOCOL"]["declaration_sections"].update(
        CONTRACT_STRUCTURE_BINDINGS="runtime structural declaration data",
        PERMISSION_BINDINGS="runtime pointer/source declaration data")
    entry_schema = {"required": ["contract", "body", "roles", "categories", "content_structure", "nested_structures", "source"],
                    "additional_keys": False}
    c = {"phase": "runtime", "entry_schema": entry_schema,
         "structure_notation": {"primitives": {k: "declared primitive" for k in ["str", "int", "bool", "JSON", "Point", "Ref"]},
             **{k: "declared node syntax" for k in ["object", "object_fragment", "nullable", "array", "tuple", "enum_literal",
                "string_integer", "tagged_union", "rational", "semantic", "checks", "contract_value_args", "pending", "selected_structure"]}},
         "shape_of_reading": {"kind_mapping": {"shape": "declared shape check"}},
         "structures": {}, "entries": [], "argument_bindings": [],
         "record_contracts_from_T_REF": ["sui.fb.example/1"],
         "content_transcribed_record_contracts_from_T_REF": [],
         "pending_record_contracts_from_T_REF": ["sui.fb.example/1"],
         "record_coverage": {"sui.fb.example/1": {"outer": "transcribed", "content": "partial",
             "pending_ids": ["CSB-P-EXAMPLE", "CSB-P-SET-ORDER"], "dynamic_contract_closure": "required_by_usage"}},
         "pending_declarations": {k: {"reason": "still pending", "source": "fixed:1"} for k in ["CSB-P-EXAMPLE", "CSB-P-SET-ORDER"]}}
    def local(structure):
        return {"structure": structure, "source": "fixed:1"}
    c["structures"]["Recursive"] = local({"kind": "object", "fields": {
        "next": {"kind": "nullable", "value": {"local": "Recursive"}}}, "additional_fields": False})
    c["structures"]["Args"] = local({"kind": "object", "fields": {}, "additional_fields": False})
    fields = {
        "recursive": {"local": "Recursive"}, "typed": {"contract": {"name": "sui.fb.value", "version": "1"}},
        "args": {"kind": "contract_args", "selector": "", "reference_form": "name_version_args", "syntax": "JSON", "usage": "args"},
        "content_args": {"kind": "contract_args", "selector": "/desc/method", "selector_base": "content", "syntax": "JSON", "usage": "method args"},
        "value": {"kind": "contract_value", "selector": "/contract", "syntax": "JSON", "usage": "value"},
        "selected": {"kind": "selected_structure", "selector": "/purpose", "selector_base": "container", "cases": {
            "update": {"local": "Args"}, "other": {"kind": "pending", "id": "CSB-P-EXAMPLE", "known_structure": "JSON"}}, "on_unmatched": "shape"},
        "fallback": {"kind": "selected_structure", "selector": "/kind", "selector_base": "value", "cases": {"known": "int"},
            "fallback": {"kind": "pending", "id": "CSB-P-EXAMPLE", "known_structure": "JSON"}},
        "set": {"kind": "array", "items": "Point", "collection": "set", "canonical_order_pending": "CSB-P-SET-ORDER"},
        "ordered": {"kind": "array", "items": "Ref", "min_items": 1, "unique": True},
        "fragment": {"kind": "pending", "id": "CSB-P-EXAMPLE", "known_structure": {
            "kind": "object_fragment", "fields": {"known": "str"}, "unlisted_fields": "not yet declared"}},
        "tuple": {"kind": "tuple", "items": ["int", "bool"]},
        "union": {"kind": "tagged_union", "tag": "kind", "payload": "value", "branches": {"x": "int"}, "additional_fields": False},
        "quantity": {"kind": "semantic", "base": {"kind": "rational", "minimum": [0, 1], "exclusive_minimum": True}, "meaning": "positive quantity", "unit": "s"},
        "text": {"kind": "string", "pattern": "[a-z]+", "min_length": 1},
        "integer": {"kind": "integer", "minimum": -1, "maximum": 1},
        "enum": {"kind": "enum", "values": [True, 1]},
        "literal": {"kind": "literal", "value": {"kind": "never_an_executable_node", "local": "not_a_reference"}},
    }
    c["structures"]["Root"] = local({"kind": "object", "fields": fields, "additional_fields": False,
                                     "checks": [{"kind": "shape", "rule": "whole-value condition", "source": "fixed:1"}]})
    for name, structure, body in [("sui.fb.example", {"local": "Root"}, ["Observed"]), ("sui.fb.value", "str", None)]:
        c["entries"].append({"contract": {"name": name, "version": "1"}, "body": body, "roles": ["model"] if body else [],
                             "categories": ["fact"] if body else [], "content_structure": structure,
                             "nested_structures": [structure] if isinstance(structure, dict) else [], "source": "fixed:1"})
    c["argument_bindings"] = [{"contract": {"name": "counting", "version": "1"}, "usage": "args", "structure": {"local": "Args"},
                               "nested_structures": [{"local": "Args"}], "source": "fixed:1"}]
    d["CONTRACT_STRUCTURE_BINDINGS"] = c
    d["PERMISSION_BINDINGS"] = {"phase": "runtime", "notation": {"location": "{record,pointer}", "indices": "p/t/o/r"}, "bindings": [{
        "bind": {"Boot": {"from": {"record": "Q*", "pointer": "/permissions/{p}"}, "pending": "PB-PENDING"}},
        "pending_bindings": {"PB-PENDING": {"status": "undeclared"}},
        "authentication": {"test": {"left": {"record": "Boot", "value": "authenticated Point"}, "rel": "equal",
                                    "right": {"literal": {"record": "opaque", "pointer": "opaque"}, "source": "fixed:1"}}},
        "components": {"target": {"pending": ["PB-PENDING"]}}}]}
    return d


def test_pointer_permission_and_structure_declarations_roundtrip_without_evaluating_or_resolving_pending():
    d = binding_declarations_example()
    data, file = rules.parse_paper(atomic_example(declarations=d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    for key in ["PERMISSION_BINDINGS", "CONTRACT_STRUCTURE_BINDINGS"]:
        assert loaded["generated_extras"][key] == d[key]
    assert rules.diff(data, loaded)["matches"]
    c = loaded["generated_extras"]["CONTRACT_STRUCTURE_BINDINGS"]
    assert c["pending_record_contracts_from_T_REF"] == ["sui.fb.example/1"]
    assert c["structures"]["Root"]["structure"]["fields"]["set"]["canonical_order_pending"] == "CSB-P-SET-ORDER"
    c["argument_bindings"][0]["contract"]["version"] = "2"
    assert not rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("case", ["node_kind", "node_key", "primitive", "local", "contract", "version_type", "duplicate_contract",
    "selector", "selector_base", "selector_policy", "reference_form", "pending", "canonical_order", "fragment",
    "integer_bool", "rational_bool", "rational_reduced", "array_bool", "tuple", "enum_duplicate", "object_open", "union_open",
    "pattern", "coverage_partition", "coverage_status", "coverage_pending", "missing_entry", "argument_duplicate",
    "argument_usage", "argument_local", "permission_record", "permission_pointer", "permission_key", "permission_hole",
    "permission_pending", "permission_relation"])
def test_new_binding_declarations_fail_closed_with_locations(case):
    d = binding_declarations_example()
    c = d["CONTRACT_STRUCTURE_BINDINGS"]
    fields = c["structures"]["Root"]["structure"]["fields"]
    pb = d["PERMISSION_BINDINGS"]["bindings"][0]
    if case == "node_kind": fields["integer"]["kind"] = "unlisted"
    if case == "node_key": fields["integer"]["default"] = 0
    if case == "primitive": fields["typed"] = "float"
    if case == "local": fields["recursive"]["local"] = "Missing"
    if case == "contract": fields["typed"]["contract"]["version"] = "2"
    if case == "version_type": c["entries"][1]["contract"]["version"] = 1
    if case == "duplicate_contract": c["entries"].append(deepcopy(c["entries"][0]))
    if case == "selector": fields["selected"]["selector"] = "not-a-pointer"
    if case == "selector_base": fields["selected"]["selector_base"] = "ambient"
    if case == "selector_policy": del fields["selected"]["on_unmatched"]
    if case == "reference_form": fields["args"]["reference_form"] = "python_type"
    if case == "pending": fields["fragment"]["id"] = "MISSING"
    if case == "canonical_order": fields["set"]["canonical_order_pending"] = "MISSING"
    if case == "fragment": fields["fragment"] = fields["fragment"]["known_structure"]
    if case == "integer_bool": fields["integer"]["minimum"] = True
    if case == "rational_bool": fields["quantity"]["base"]["minimum"] = [False, 1]
    if case == "rational_reduced": fields["quantity"]["base"]["minimum"] = [2, 2]
    if case == "array_bool": fields["ordered"]["min_items"] = True
    if case == "tuple": fields["tuple"]["items"] = "int"
    if case == "enum_duplicate": fields["enum"]["values"] = [1, 1]
    if case == "object_open": c["structures"]["Root"]["structure"]["additional_fields"] = True
    if case == "union_open": fields["union"]["additional_fields"] = True
    if case == "pattern": fields["text"]["pattern"] = "["
    if case == "coverage_partition": c["pending_record_contracts_from_T_REF"] = []
    if case == "coverage_status": c["record_coverage"]["sui.fb.example/1"]["content"] = "success"
    if case == "coverage_pending": c["record_coverage"]["sui.fb.example/1"]["pending_ids"] = ["MISSING"]
    if case == "missing_entry": del c["entries"][0]
    if case == "argument_duplicate": c["argument_bindings"] *= 2
    if case == "argument_usage": c["argument_bindings"][0]["usage"] = "value"
    if case == "argument_local": c["argument_bindings"][0]["structure"] = {"local": "Missing"}
    if case == "permission_record": pb["bind"]["Boot"]["from"]["record"] = "Unknown"
    if case == "permission_pointer": pb["bind"]["Boot"]["from"]["pointer"] = "not-a-pointer"
    if case == "permission_key": pb["bind"]["Boot"]["from"]["default"] = 0
    if case == "permission_hole": pb["bind"]["Boot"]["from"]["pointer"] = "/{unknown}"
    if case == "permission_pending": pb["components"]["target"]["pending"] = ["UNKNOWN"]
    if case == "permission_relation": pb["authentication"]["test"]["rel"] = "approximately_equal"
    with pytest.raises(rules.AtomSyntaxError) as got:
        rules.parse_paper(atomic_example(declarations=d))
    assert all(issue["line"] > 0 and issue["reason"] for issue in got.value.issues)


def test_binding_syntax_reports_independent_node_and_permission_errors_together():
    d = binding_declarations_example()
    fields = d["CONTRACT_STRUCTURE_BINDINGS"]["structures"]["Root"]["structure"]["fields"]
    fields["first_bad"] = {"local": "UnknownOne"}
    fields["second_bad"] = {"contract": {"name": "UnknownTwo", "version": "1"}}
    binding = d["PERMISSION_BINDINGS"]["bindings"][0]["bind"]
    binding["Boot"]["from"]["pointer"] = "bad"
    binding["Other"] = {"from": {"record": "Unknown", "pointer": "/x"}}
    with pytest.raises(rules.AtomSyntaxError) as got:
        rules.parse_paper(atomic_example(declarations=d))
    ids = [issue["id"] for issue in got.value.issues]
    assert sum("PERMISSION_BINDINGS.bindings" in key for key in ids) == 2
    assert any("first_bad" in key for key in ids) and any("second_bad" in key for key in ids)


@pytest.mark.parametrize("case", ["block_mode", "item_extra", "atom_extra", "rel", "when_dict", "predicate_code",
    "each_missing", "each_select", "each_shadow", "each_unbound", "unknown_lexical", "missing_code", "forbidden_code",
    "helper_arity", "source_arity", "derive", "binding", "use", "rule_path", "selector", "capture_identity", "map_missing", "map_block",
    "map_atoms", "component_denominator", "protocol_version", "missing_protocol"])
def test_atom_protocol_unknown_shapes_and_broken_denominators_fail_closed(case):
    d = atom_protocol_example()
    block = d["ENUMERATIONS"]["SMALL_ENUM"]
    item, atom = block["items"][0], block["items"][0]["atoms"][0]
    if case == "block_mode": block["mode"] = "values"
    if case == "item_extra": item["value"] = {"literal": 1}
    if case == "atom_extra": atom["dispatch"] = "special_case"
    if case == "rel": atom["rel"] = "approximately_equal"
    if case == "when_dict": item["when"] = {"generation": "sui.fb.example/1"}
    if case == "predicate_code": item["when"] = [{"left": "Q*:", "rel": "present", "code": "shape"}]
    if case == "each_missing": item["each"] = [{"bind": "ITEM", "select": "all"}]
    if case == "each_select": item["each"] = [{"bind": "ITEM", "in": {"literal": []}, "select": "first"}]
    if case == "each_shadow": item["each"] = [{"bind": "ITEM", "in": {"literal": []}, "select": "all"}] * 2
    if case == "each_unbound": item["each"] = [{"bind": "ITEM", "in": "ITEM:", "select": "all"}]
    if case == "unknown_lexical": item["each"] = [{"bind": "UNKNOWN", "in": {"literal": []}, "select": "all"}]
    if case == "missing_code": atom["on_fail"] = "不適合"
    if case == "forbidden_code": atom["code"] = "shape"
    if case == "helper_arity": atom["left"] = {"derive": "project", "args": ["Q*:"]}
    if case == "source_arity": atom["left"] = {"derive": "enumeration_source", "args": [{"literal": "primary"}]}
    if case == "derive": atom["left"] = {"derive": "unknown", "args": []}
    if case == "binding": atom["left"] = "ITEM:"
    if case == "use": item["prelude"] = [{"use": "CASE-ONE"}]
    if case == "rule_path": atom["left"] = {"derive": "rule_data", "args": [{"literal": "ENUMERATIONS.SMALL_ENUM.missing"}]}
    if case == "selector": atom["left"] = {"derive": "project", "args": [
        {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"]}, {"literal": {
        "block": "SMALL_ENUM", "case": "UNKNOWN", "component": "x"}}, "BINDINGS:"]}
    if case == "capture_identity": atom["left"] = {"derive": "project", "args": ["CALL:", {"literal": {
        "block": "SMALL_ENUM", "case": "CASE-ONE", "component": "x"}}, "BINDINGS:"]}
    if case == "map_missing": d["ENUMERATION_ID_MAP"] = {}
    if case == "map_block": d["ENUMERATION_ID_MAP"]["CASE-ONE"]["block"] = "UNKNOWN"
    if case == "map_atoms": d["ENUMERATION_ID_MAP"]["CASE-ONE"]["atoms"] = []
    if case == "component_denominator": d["COMPONENT_INSTANCE_SOURCES"] = {"point_of": {"each": [], "when": [], "source": "extra"}}
    if case == "protocol_version": d["ATOM_PROTOCOL"]["version"] = 99
    if case == "missing_protocol": del d["ATOM_PROTOCOL"]
    with pytest.raises(rules.AtomSyntaxError):
        rules.parse_paper(atomic_example(declarations=d))


def test_atom_protocol_collects_independent_errors_in_one_pass(monkeypatch, capsys):
    d = atom_protocol_example()
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["atoms"] += [{"id": "BAD-SECOND", "left": "Unknown:", "rel": "present", "on_fail": "不足"}]
    item["atoms"][0]["rel"] = "unknown"
    with pytest.raises(rules.AtomSyntaxError) as got:
        rules.parse_paper(atomic_example(declarations=d))
    assert {"CASE-ONE-CHECK", "BAD-SECOND"} <= {e["id"] for e in got.value.issues}
    monkeypatch.setattr(rules, "read_paper", lambda path: (_ for _ in ()).throw(got.value))
    assert rules.main(["check", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["unclassified_count"] == len(got.value.issues)


def test_use_diagnoses_sibling_expansions_when_another_source_atom_fails():
    d = atom_protocol_example()
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    item["each"] = [{"bind": "ITEM", "in": {"literal": [1]}, "select": "all"}]
    item["prelude"] = [{"use": "A1-EXAMPLE"}]
    source = [
        {"id": "FIRST", "left": "Q*:", "rel": "present", "on_fail": "不適合"},
        {"id": "SECOND", "left": "ITEM:", "rel": "present", "on_fail": "不足", "each": [
            {"bind": "ITEM", "in": {"literal": [1]}, "select": "all"}]},
    ]
    d["ENUMERATION_ID_MAP"]["CASE-ONE"]["atoms"][:0] = ["CASE-ONE::FIRST", "CASE-ONE::SECOND"]
    with pytest.raises(rules.AtomSyntaxError) as got:
        rules.parse_paper(atomic_example(source, d))
    reasons = [issue["reason"] for issue in got.value.issues]
    assert any("requires a declared code" in reason for reason in reasons)
    assert any("shadowed lexical binding" in reason for reason in reasons)


def test_atom_code_vocabulary_is_read_from_the_protocol_declaration():
    d = atom_protocol_example()
    d["ATOM_PROTOCOL"]["atom"]["codes"] = ["fixed_local_reason"]
    atom = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]["atoms"][0]
    atom.update(on_fail="不適合", code="fixed_local_reason")
    data = rules.parse_paper(atomic_example(declarations=d))
    assert data["enumeration_coded_atoms"] == 1


def test_component_primary_instances_and_call_multiset_prelude_roundtrip():
    d = atom_protocol_example()
    d["ENUMERATIONS"]["DERIVED_FIELDS"] = {
        "consumers": ["point_of"], "scopes": ["requests"], "prelude": [], "source": "fixed:2",
        "items": [{"id": "FIELD-POINT", "when": [], "prelude": [],
            "each": [{"bind": "ITEM", "in": {"derive": "source_instances", "args": [
                {"literal": "point_of"}, "CALL:/arguments"]}, "select": "all"}],
            "atoms": [{"id": "FIELD-POINT-MATCH", "left": {"derive": "project", "args": [
                {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"]},
                {"literal": {"block": "DERIVED_FIELDS", "case": "FIELD-POINT", "component": "value"}}, "BINDINGS:"]},
                "rel": "equal", "right": "ITEM:", "on_fail": "不適合", "code": "proof_mismatch"}]}]}
    d["COMPONENT_INSTANCE_SOURCES"] = {"point_of": {"each": [
        {"bind": "SOURCE", "in": {"derive": "tuple", "args": ["CALL:"]}, "select": "one"}],
        "when": [], "source": "actual primary arguments with their positions"}}
    d["DERIVED_FIELD_ORIGINS"] = {"point_of": "actual primary record"}
    d["DERIVATION_ENUMERATION_INVENTORY"]["entries"]["point_of"]["blocks"].append("DERIVED_FIELDS")
    d["ENUMERATION_ID_MAP"]["FIELD-POINT"] = {"block": "DERIVED_FIELDS", "atoms": ["FIELD-POINT-MATCH"]}
    d["ENUMERATION_CALL_PRELUDE"] = [
        {"id": "CAPTURE", "left": {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"],
            "path": "/call_identity"}, "rel": "present", "on_fail": "不足"},
        {"id": "MULTISET", "left": {"derive": "captured_instances", "args": [
            {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"]}, "BLOCK:"]},
            "rel": "equal", "right": {"derive": "expected_instances", "args": ["BLOCK:", "CALL:"]},
            "on_fail": "不適合", "code": "proof_mismatch", "each": [
                {"bind": "BLOCK", "in": {"derive": "declared_blocks", "args": ["CALL:/consumer"]}, "select": "all"}]}]
    data, file = rules.parse_paper(atomic_example(declarations=d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    extras = loaded["generated_extras"]
    for key in ("COMPONENT_INSTANCE_SOURCES", "ENUMERATION_CALL_PRELUDE", "ENUMERATION_ID_MAP"):
        assert extras[key] == d[key]
    assert loaded["enumeration_atom_count"] == 4
    assert loaded["enumeration_direct_atom_count"] == 4
    assert loaded["enumeration_block_atom_count"] == 2
    assert loaded["enumeration_call_prelude_atom_count"] == 2
    assert rules.diff(data, loaded)["matches"]
    loaded["enumeration_atom_count"] -= 1
    assert not rules.diff(data, loaded)["matches"]


@pytest.mark.parametrize("source", [
    {"derive": "point_of", "args": ["Q*:"]},
    {"derive": "effect", "args": [{"literal": "derivation_return"}, "CALL:"]},
])
def test_each_denominator_cannot_read_its_producer_or_captured_return(source):
    d = atom_protocol_example()
    d["ENUMERATIONS"]["SMALL_ENUM"]["each"] = [{"bind": "ITEM", "in": source, "select": "all"}]
    with pytest.raises(rules.AtomSyntaxError, match="owning consumer"):
        rules.parse_paper(atomic_example(declarations=d))


def test_literal_json_is_not_reinterpreted_as_calls_or_use_macros():
    d = atom_protocol_example()
    item = d["ENUMERATIONS"]["SMALL_ENUM"]["items"][0]
    values = [{"derive": "point_of", "args": []}, {"use": "A1-EXAMPLE"}, {"derive": "point_of", "args": []}]
    item["each"] = [{"bind": "ITEM", "in": {"literal": values}, "select": "all"}]
    item["atoms"][0]["left"] = "ITEM:"
    item["data"] = {"use": "annotation only"}
    data, file = rules.parse_paper(atomic_example(declarations=d)), MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["generated_extras"]["SMALL_ENUM"]["items"][0] == item
    assert data["enumeration_reused_atom_count"] == 0
    assert rules.diff(data, loaded)["matches"]


# Migration baseline: generator 1.9, production SHA-256
# 80c4fc5620b9133c651b89f6417d8dfd2d5fb7dd60de8c7bca01b9bc2a0b2420.
# Snapshot IDs only; new atom semantics remain in the paper.
LEGACY_ENUMERATION_ITEMS = {
    "CLOCK_PAIRS": ["CLK-INLINE-SAVED","CLK-ENTRY-STARTED","CLK-STARTED-RECEIVED","CLK-ENDED-RECEIVED","CLK-CLAIM-END-RECEIVED","CLK-ROUTE-WINDOW-START","CLK-VERSIONED-RELATIONS"],
    "GENERATION_EVIDENCE": ["GEN-APPLIED","GEN-STARTED","GEN-ENDED","GEN-K-ENTERED","GEN-ROUTE","GEN-CLOCK","GEN-RAW-REPORT","GEN-SCOPE","GEN-SUPPORT"],
    "MODEL_LINKS": ["MODEL-ORIGIN","MODEL-PRIOR-MODEL","MODEL-PRIOR-ORIGIN","MODEL-COMPILER-MODEL","MODEL-COMPILER-ORIGIN"],
    "ADOPTION_TIMES": ["ADOPT-G","ADOPT-A","ADOPT-R","ADOPT-AT","ADOPT-RUNS","ADOPT-EXPECTED-RUNS"],
    "RESULT_ACQUISITION_TIMES": ["ACQUIRE-GENERATED","ACQUIRE-SAVED","ACQUIRE-ACQUIRED","ACQUIRE-OBSERVED","ACQUIRE-GATE","ACQUIRE-READING","ACQUIRE-RUNS","ACQUIRE-EXPECTED-RUNS"],
    "INPUT_ACQUISITIONS": ["INPUT-ACQUIRED-ORIGIN","INPUT-USED-ORIGIN","INPUT-ACQUIRED-POINT","INPUT-USED-POINT","INPUT-ACQUIRED-RUN","INPUT-USED-RUN","INPUT-ACQUIRED-NS","INPUT-USED-NS"],
    "HISTORICAL_USES": ["HISTORY-ACQUIRED-RUN","HISTORY-USED-RUN","HISTORY-ACQUIRED-NS","HISTORY-USED-NS"],
    "SUPPORT_COMPONENTS": ["SUPPORT-POINTS","SUPPORT-COVERED","SUPPORT-SAVED-EVENTS","SUPPORT-OBSERVED-EVENTS"],
    "SUPPORT_EVENT_FIELDS": ["SUPPORT-EVENT-SEGMENT","SUPPORT-EVENT-WORK","SUPPORT-EVENT-ROUTE","SUPPORT-EVENT-CLOCK","SUPPORT-EVENT-ENTERED_NS","SUPPORT-EVENT-OBSERVED_NS"],
    "SUPPORT_CHECKS": ["SUPPORT-SEGMENT","SUPPORT-WORK","SUPPORT-ROUTE","SUPPORT-CLOCK","SUPPORT-START","SUPPORT-END","SUPPORT-EFFECTIVE"],
    "INDEPENDENT_EVENTS": ["EVENT-APPLIED","EVENT-STARTED","EVENT-ENDED"],
    "GENERATION_BOUNDARIES": ["BOUNDARY-STARTED","BOUNDARY-ENDED"],
    "DECLARATION_SLOTS": ["SLOT-PROCESS","SLOT-ALLOCATION","SLOT-PERMISSIONS"],
    "HISTORY_DEPENDENCIES": ["HISTORY-RESULT","HISTORY-ACQUISITION","HISTORY-PREVIOUS"],
    "CLOSURE_TERMS": ["C-LOCAL","C-HISTORY","C-PREVIOUS-C","C-PREVIOUS-I"],
    "FUTURE_RECORD_ROLES": ["FUTURE-SELF","FUTURE-RESULT","FUTURE-ACQUISITION","FUTURE-ADOPTION"],
    "PERMISSION_COMPONENTS": ["PERMISSION-TARGET","PERMISSION-PURPOSE","PERMISSION-METHOD","PERMISSION-SCOPE","PERMISSION-ALLOCATION"],
    "BUDGET_EVENT_KINDS": ["WORK-HEADER_READ","WORK-BODY_READ","WORK-REFERENCE_COMPARE","WORK-PROJECTION_INPUT","WORK-INTEGER_EXTENSION","WORK-EXACT_ADD","WORK-EXACT_SUBTRACT","WORK-EXACT_MULTIPLY","WORK-EXACT_DIVIDE","WORK-EXACT_COMPARE"],
    "BUDGET_RULES": ["COUNT-FINITE-UPDATE-1"],
    "BUDGET_DIMENSIONS": ["BUDGET-TOLERANCE","BUDGET-LOGICAL_LIMIT"],   # 予算 C (紙 F-b Z34 (a)、正本 v1.3.5)
    "PUBLIC_FAILURES": ["FAILURE-INSUFFICIENT","FAILURE-MISMATCH","FAILURE-FORBIDDEN"],
    "PROVENANCE_CASES": ["PROV-RELATED","PROV-UNRELATED","PROV-UNKNOWN"],
    "DERIVED_FIELDS": ["FIELD-CLAIM_SIGNATURE-KIND","FIELD-CLAIM_SIGNATURE-CONTRACT","FIELD-PROJECTION_SIGNATURE-KIND","FIELD-PROJECTION_SIGNATURE-CONTRACT","FIELD-ENTRY-PAYLOAD","FIELD-ENTRY-SEAL","FIELD-ENTRY-HEADER","FIELD-REGISTRY-DECLARATIONS","FIELD-REGISTRY-IMPLEMENTATIONS","FIELD-REPLAY_RESULT-RESULT-JOINT","FIELD-REPLAY_RESULT-RESULT-EVIDENCE_MASS","FIELD-REPLAY_RESULT-APPLICATION_DIGEST","FIELD-RESULT_VALUE-REQUEST","FIELD-RESULT_VALUE-RESULT","FIELD-RESULT_VALUE-APPLICATION_DIGEST","FIELD-RESULT_VALUE-NUMERICAL_VIEW","FIELD-RESULT_VALUE-REGISTRY_KEY","FIELD-RESOLUTION_GROUPS-CID_COUNT","FIELD-RESOLVED_REFS-POINT","FIELD-RESOLVED_REFS-REF","FIELD-RESOLVED_REFS-BYTES","FIELD-RESOLVED_REFS-CAUSAL","FIELD-BUDGET_CHARGES-FRAME","FIELD-BUDGET_CHARGES-DIMENSION","FIELD-BUDGET_CHARGES-USED","FIELD-BUDGET_CHARGES-LIMIT","FIELD-SHAPE_OF-KIND","FIELD-MODEL_LINKS-ID","FIELD-CLOCK_PAIRS-ID","FIELD-FUTURE_RECORDS-SELF","FIELD-FUTURE_RECORDS-RESULT","FIELD-FUTURE_RECORDS-ACQUISITION","FIELD-FUTURE_RECORDS-ADOPTION","FIELD-RESOLUTION_GROUPS-UNIQUE_POINT","FIELD-RESOLUTION_GROUPS-BODY_PAIRS-LEFT","FIELD-RESOLUTION_GROUPS-BODY_PAIRS-RIGHT","FIELD-ADOPTION_CHAIN-POINTS","FIELD-ADOPTION_CHAIN-TERMINAL-KIND","FIELD-ADOPTION_CHAIN-TERMINAL-POINT"],
    "RESOLUTION_SCOPE_TERMS": ["SCOPE-FIXED_PARENT_ANCESTORS","SCOPE-EXPLICIT_POINTS","SCOPE-TYPED_DEPENDENCIES","SCOPE-REQUIRED_ACTUAL_PARENTS"],
    "BUDGET_FRAMES": ["BUDGET-ACTIVE-FRAMES","BUDGET-OUTER-GLOBAL"],
}


def test_real_id_map_preserves_every_previous_item_before_replacing_mode_checks():
    """Compare all IDs, not a smaller replacement set or a fixed item count."""
    assert rules.PAPER.is_file(), f"紙が無い: {rules.PAPER}"
    doc = rules.blocks(rules.PAPER.read_text(encoding="utf-8-sig"))
    declaration = rules.strict_json(next(b.text for b in doc if b.kind == "code" and '"SCOPES"' in b.text))
    old = rules.load_generated(rules.OUTPUT)["generated_extras"]["ENUMERATIONS"]
    previous = {iid: name for name, ids in LEGACY_ENUMERATION_ITEMS.items() for iid in ids}
    assert {item["id"]: name for name, block in old.items() for item in block["items"]} == previous
    assert {iid: row["block"] for iid, row in declaration["ENUMERATION_ID_MAP"].items()} == previous
    assert {item["id"] for block in declaration["ENUMERATIONS"].values() for item in block["items"]} == set(previous)


def test_via_walk_count_assert_and_stage_mapping_preserve_their_structure():
    d = deepcopy(FIXED_DECLARATIONS)
    d["MODEL_WALKS"] = {"fixed/1": {"document_contract": "/contract", "roots": ["/root"], "recurse": {},
        "positive": {"ref/1": ["/point"]}, "negative_query": {}, "leaves": ["constant/1"],
        "other_typed_children": "versioned_contract_schema", "unknown": "missing_contract"}}
    for field in ({"via": "REF-LEFT", "path": "/nested"}, {"walk": "fixed/1", "root": "/document", "select": "positive"}):
        text = atomic_example(declarations=d).replace("| /right? |", "| " + json.dumps(field) + " |", 1)
        condition = {"count": 1, "assert": [{"id": "REF-ASSERT", "left": "SELF:", "rel": "present", "on_fail": "不足"}]}
        text = text.replace("| E | true | fixed:2 |", "| E | " + json.dumps(condition, ensure_ascii=False) + " | fixed:2 |", 1)
        exclusion = {"rule": ["CL-SAME", "CL-EXECUTION"], "via": "REF-LEFT", "stage_mapping": {"candidate_generation": "result_stage"}}
        text = text.replace('{"rule":"CL-SAME"}', json.dumps(exclusion))
        data, file = rules.parse_paper(text), MemoryFile()
        rules.generate(data, file)
        current = rules.load_generated(file)
        assert current["tables"]["T-REF"][1]["field"] == field
        assert current["tables"]["T-REF"][2]["condition"] == condition
        assert current["tables"]["T-G4"][0]["exclusion"] == exclusion
        assert rules.diff(data, current)["matches"]
    for field in ({"via": "REF-ABSENT", "path": "/nested"},
                  {"walk": "unknown/1", "root": "/document", "select": "positive"}):
        bad = atomic_example(declarations=d).replace("| /right? |", "| " + json.dumps(field) + " |", 1)
        with pytest.raises(rules.TableError): rules.parse_paper(bad)


def test_element_conditions_are_treatments_and_survive_generation():
    condition = {"element": {"/op": "bind_draw"}}
    text = EXAMPLE.replace("| E | true | fixed:2 |", '| E | ' + json.dumps(condition) + ' | fixed:2 |')
    data = rules.parse_paper(text)
    row = next(r for r in data["tables"]["T-REF"] if r["id"] == "REF-CLOCK-SOURCE")
    assert rules.field_covered({"field": row["field"], "kind": "value"}, [row])
    file = MemoryFile()
    rules.generate(data, file)
    saved = rules.load_generated(file)["tables"]["T-REF"]
    assert next(r for r in saved if r["id"] == row["id"])["condition"] == condition


def test_element_condition_rows_count_in_the_coverage_check(monkeypatch):
    data = rules.parse_paper(EXAMPLE.replace("| E | true | fixed:2 |",
                                            '| E | {"element":{"/op":"bind_draw"}} | fixed:2 |'))
    reader = fixture_structures()
    monkeypatch.setattr(rules, "Structures", lambda root: reader)
    monkeypatch.setitem(rules.DTO_BINDINGS, "sui.fb.example/1", ("fb", "Example"))
    assert rules.check(data, EXAMPLE)["unclassified_count"] == 0


@pytest.mark.parametrize("condition", [{"element": {}}, {"element": {"op": "bind_draw"}}, {"element": []}])
def test_invalid_element_conditions_fail(condition):
    with pytest.raises(rules.TableError, match="element"):
        rules.parse_paper(EXAMPLE.replace("| E | true | fixed:2 |", '| E | ' + json.dumps(condition) + ' | fixed:2 |'))


def test_implementation_inventory_tracks_aliases_arrays_and_separate_fields():
    function = ast.parse("""
def edges(contract, content, use, basis):
    if contract == 'sui.fb.example/1' and use == 'read':
        box = content['box']
        out = [(box['left'], 'reader'), (box['right'], 'reader')]
        out += [(item['source'], None) for item in content['items']]
        return out
    return []
""").body[0]
    result = rules.ImplementationReader({}).read(function, "sui.fb.example/1", "read", "edges")
    assert {(x["field"], x["target_use_or_key"]) for x in result["items"]} == {
        ("/box/left", "reader"), ("/box/right", "reader"), ("/items/*/source", None),
    }
    assert result["unreadable"] == []


def test_implementation_inventory_requires_an_explicit_decoded_contract_guard():
    function = ast.parse("""
def local_refs(body, desc):
    contract, binding, basis, about = body(desc['binding'])
    if contract != 'sui.fb.binding/1':
        raise ValueError('wrong contract')
    out = {binding['record']}
    return out
""").body[0]
    result = rules.ImplementationReader({}).read(function, "sui.fb.request/1", "read", "fields")
    assert [(x["contract"], x["purpose"], x["field"]) for x in result["items"]] == [
        ("sui.fb.binding/1", "読めない", "/record"),
    ]
    function.body = [n for n in function.body if not isinstance(n, ast.If)]
    unknown = rules.ImplementationReader({}).read(function, "sui.fb.request/1", "read", "fields")
    assert unknown["items"][0]["contract"] == ""
    assert unknown["items"][0]["owner_expression"] == "body(desc['binding'])"


def test_implementation_inventory_reports_an_unsupported_expression():
    function = ast.parse("def edges(contract, content, use, basis):\n    return hidden(content)\n").body[0]
    result = rules.ImplementationReader({}).read(function, "sui.fb.example/1", "read", "edges")
    assert result["items"] == []
    assert result["unreadable"][0]["expression"] == "hidden(content)"


def test_math_delegation_requires_the_statement_value_row_and_declared_use(monkeypatch):
    text = EXAMPLE.replace("sui.fb.example/1", "sui.f.math_artifact/2").replace("| update |", "| prepare |")
    data = rules.parse_paper(text)
    left = data["tables"]["T-REF"][0]
    left["role"] = "E"
    class Reader:
        def contract_body(self, contract, purpose):
            return rules.Shape("object", (("left", rules.Shape("object", (("dynamic", rules.Shape("opaque", source="fixed dynamic")),))),))
    monkeypatch.setattr(rules, "Structures", lambda root: Reader())
    marker = "\n- v1.1 の math_artifact は、本文の各最上位欄を E として sui.f.math_artifact/2 の verify_f_math_result へ委ねる。\n"
    assert rules.check(data, text)["unavailable_contracts"]
    delegated = rules.check(data, text + marker)
    assert delegated["delegated_contract_count"] == 1
    assert not delegated["unavailable_contracts"]
    for role in ("U", "UE", "leaf", "ignored", "unsupported"):
        left["role"] = role
        assert rules.check(data, text + marker)["unavailable_contracts"]
    wrong_use = rules.parse_paper(text.replace("| prepare |", "| diagnostic |"))
    wrong_use["tables"]["T-REF"][0]["role"] = "E"
    assert rules.check(wrong_use, text + marker)["unavailable_contracts"]


@pytest.fixture(scope="module")
def paper():
    # Absence is an explicit failure, never skip or a synthetic replacement.
    assert rules.PAPER.is_file(), f"紙が無い: {rules.PAPER}"
    return rules.read_paper(), rules.PAPER.read_text(encoding="utf-8-sig")


def test_real_paper_section_6_11_is_readable(paper):
    data, _ = paper
    assert set(data["tables"]) == {"T-REF", "T-A2", "T-G4", "T-G6", "T-A1"}


def test_canonical_atomic_rules_and_all_enumeration_blocks_roundtrip(paper):
    data, _ = paper
    expected_atom_count = sum(len(row["relation"]) for row in data["tables"]["T-A1"])
    assert data["atom_count"] == expected_atom_count
    declarations = data.get("compiled_rule_declarations", data["rule_declarations"])
    assert data["enumeration_count"] == len(declarations["ENUMERATIONS"])
    assert data["enumeration_item_count"] == sum(len(block["items"]) for block in declarations["ENUMERATIONS"].values())
    inventory = declarations["DERIVATION_ENUMERATION_INVENTORY"]
    assert inventory["reviewed"] == len(inventory["entries"])
    assert set(inventory["entries"]) | set(inventory["added_helpers"]) == set(declarations["DERIVATIONS"])
    assert not data["unatomized_a1"] and not data["pending"]
    file = MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    assert loaded["atom_count"] == expected_atom_count
    assert loaded["generator_version"] == rules.VERSION
    assert set(loaded["derivation_names"]) == set(declarations["DERIVATIONS"])
    assert set(loaded["effect_names"]) == set(declarations["EFFECTS"])
    for name, declaration in declarations.items():
        assert loaded["generated_extras"][name] == declaration
    for name, block in declarations["ENUMERATIONS"].items():
        assert loaded["generated_extras"][name] == block
    assert len(loaded["generated_extras"]["A1_RELATIONS"]) == len(data["tables"]["T-A1"])
    if "ATOM_PROTOCOL" in declarations:
        enum_atoms = [atom for block in declarations["ENUMERATIONS"].values()
                      for seq in [block["prelude"], *(s for item in block["items"] for s in (item["prelude"], item["atoms"]))]
                      for atom in seq]
        call_atoms = declarations["ENUMERATION_CALL_PRELUDE"]
        assert loaded["enumeration_atom_count"] == len(enum_atoms) + len(call_atoms)
        assert loaded["enumeration_coded_atoms"] == sum("code" in atom for atom in [*enum_atoms, *call_atoms])
        if declarations["ATOM_PROTOCOL"]["version"] == 3:
            original = [a for row in data["source_tables"]["T-A1"] for a in row["relation"]]
            for prefix, atoms in (("a1", original), ("enumeration", [*enum_atoms, *call_atoms])):
                for phase in declarations["ATOM_PROTOCOL"]["phase"]["values"]:
                    selected = [a for a in atoms if a.get("phase", "runtime") == phase]
                    assert loaded[prefix + "_" + phase + "_atom_count"] == len(selected)
                    assert loaded[prefix + "_" + phase + "_coded_atoms"] == sum("code" in a for a in selected)
            for aid, origin in loaded["generated_extras"]["ATOM_ORIGINS"].items():
                row = next(r for r in data["tables"]["T-A1"] if r["id"] == origin["row_id"])
                assert origin["subject"] == row["subject"]
                assert origin["stages"] == row["stages"] and origin["evidence"] == row["evidence"]
                original_atom = next(a for a in row["relation"] if a["id"] == origin["atom_id"])
                expanded = next(a for a in enum_atoms if a["id"] == aid)
                assert expanded["phase"] == original_atom["phase"]
                assert expanded.get("phase_reason") == original_atom.get("phase_reason")
        assert not any("use" in v for v in rules.AtomCompiler.objects(declarations["ENUMERATIONS"]))
        for name, block in declarations["ENUMERATIONS"].items():
            assert "mode" not in block
            for item in block["items"]:
                assert declarations["ENUMERATION_ID_MAP"][item["id"]] == {
                    "block": name, "atoms": [a["id"] for a in [*item["prelude"], *item["atoms"]]]}
    assert rules.diff(data, loaded)["matches"]


def test_canonical_codes_and_uncoded_mismatch_denominator_roundtrip(paper):
    data, _ = paper
    original = {atom["id"]: atom for row in data["tables"]["T-A1"] for atom in row["relation"]}
    coded = {aid: atom["code"] for aid, atom in original.items() if "code" in atom}
    uncoded = [aid for aid, atom in original.items() if atom["on_fail"] == "不適合" and "code" not in atom]
    assert coded, "正本のcode付き原子が無い"
    file = MemoryFile()
    rules.generate(data, file)
    loaded = rules.load_generated(file)
    actual = {atom["id"]: atom for atoms in loaded["generated_extras"]["A1_RELATIONS"].values() for atom in atoms}
    assert actual == original
    assert {aid: atom["code"] for aid, atom in actual.items() if "code" in atom} == coded
    assert loaded["coded_atoms"] == len(coded)
    assert loaded["uncoded_mismatch_atoms"] == uncoded
    assert rules.diff(data, loaded)["matches"]


def test_real_paper_has_zero_unclassified_fields(paper):
    data, text = paper
    result = rules.check(data, text)
    detail = "\n".join(f"{x['contract']} [{x['purpose']}] {x['field']} ({x['source']})" for x in result["unclassified"])
    assert result["unclassified_count"] == 0, f"未分類 {result['unclassified_count']} 欄:\n{detail}"


def test_real_field_types_have_the_same_denominator_and_conservative_partial_types(paper):
    data, text = paper
    result, types = rules.check(data, text), rules.field_types(data)
    expected = {(c["contract"], f["field"]) for c in result["contracts"] for f in c["fields"]}
    assert set(types) == expected
    assert len(types) == result["field_count"]
    for partial in result["unavailable_contracts"]:
        for (contract, path), typ in types.items():
            if contract == partial["contract"]:
                assert typ == {"/parents/*": "point", "/inputs/*": "ref", "/basis/*": "ref", "/about/*": "ref"}.get(path, "unknown")
    assert types["sui.fb.work_requested/1", "/desc/args/model"] == "point"
    assert types["sui.fb.update_result/1", "/about/*"] == "ref"
    assert types["sui.fb.candidate_request/1", "/desc/args/basis/*"] == "point"
    assert types["sui.f.math_artifact/2", "/calls/*/args/draw"] == "point"


@pytest.mark.parametrize("contract,expected", [
    ("sui.fb.work_requested/1", {"/parents/*": "point", "/inputs/*": "ref"}),
    ("sui.fb.update_result/1", {"/parents/*": "point", "/basis/*": "ref", "/about/*": "ref"}),
])
def test_outer_parents_are_points_and_saved_body_links_are_refs(structures, contract, expected):
    fields = {f["field"]: f["field_type"] for f in structures.outer_fields(contract)}
    assert {path: fields[path] for path in expected} == expected
    if "/target" in fields:
        assert fields["/target"] == "value"
    header_id = next(f for f in structures.common_fields(contract) if f["field"] == "/header/id")
    assert header_id["field_type"] == "ref"


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("nested_type", ["value", "point"])
def test_outer_link_types_do_not_change_nested_fields(monkeypatch, partial, nested_type):
    reader = fixture_structures()
    children = [("desc", rules.Shape("object", (("args", rules.Shape("object", (
        ("basis", rules.Shape("array", (rules.Shape("value", field_type=nested_type),))),))),)))]
    if partial:
        children.append(("dynamic", rules.Shape("opaque", source="unreadable fixed expression")))
    reader.contract_body = lambda contract, purpose: rules.Shape("object", tuple(children))
    reader.outer_fields = lambda contract: [
        {"field": p, "kind": "value", "field_type": "ref", "scope": "outer"}
        for p in ("/parents/*", "/inputs/*", "/basis/*", "/about/*")]
    reader.common_fields = lambda contract: []
    monkeypatch.setattr(rules, "Structures", lambda root: reader)
    types = rules.field_types(rules.parse_paper(EXAMPLE))
    assert types["sui.fb.example/1", "/desc/args/basis/*"] == ("unknown" if partial else nested_type)
    assert types["sui.fb.example/1", "/parents/*"] == "point"
    assert all(types["sui.fb.example/1", path] == "ref"
               for path in ("/inputs/*", "/basis/*", "/about/*"))


def test_real_paper_coverage_is_not_claimed_from_an_incomplete_denominator(paper):
    data, text = paper
    result = rules.check(data, text)
    assert result["ok"], json.dumps({
        "unavailable_contracts": result["unavailable_contracts"], "opaque_fields": result["opaque_fields"],
        "unresolved_operations": result["operations"]["missing"], "pending": result["pending"],
    }, ensure_ascii=False, indent=2)
