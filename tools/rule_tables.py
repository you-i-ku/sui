"""Read the deliberately restricted Markdown table language in F-b §6-11.

No dependencies; the block/row parser below is a parser for pipe tables, not a
str.split('|') reader. Machine cells must be plain text (the paper forbids
Markdown markup and pipes). No natural-language rule is synthesized.

check emits Markdown followed by a JSON document; --format json is available.
An explicit paper declares `表の一覧: T-X(任意の種類) ...` and `表の版: v...`.
Columns use `列名【型】`, or a `#### 列の型 (機械可読)` table with 表/列/型.
Only undeclared F-b v1 papers use the five legacy default tables. Structural
DTO adapters are the F-b profile; generic declarations still validate all IDs,
column types and cross-table ID references, and generate/diff every table.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERSION = "2.4"
ROOT = Path(__file__).resolve().parents[1]
DERIVATION = ROOT / "specs/関所F_Fb_今の約束.md"   # 導出の紙 (旧 G6 の操作名の表はここ。無ければ照合を省く)
PAPER = ROOT / "src/sui/fb_rules.md"   # 規則の正本 (ゆう 2026-10-22 決定 C: 本体の中。紙 §6-11 は参照)
OUTPUT = ROOT / "src/sui/_fb_rules.py"
PENDING = "未確定"

# F-b v1's default declaration. Used only when the paper has no declaration.
# Other papers declare their own table IDs and typed column labels.
FB_V1_COLUMNS = {
    "T-REF": ("ID", "出発の契約", "出発の用途", "欄", "到達先の契約 (決まっていれば)",
              "到達先の用途 (契約が決めるなら -)", "役割", "条件", "紙の行"),
    "T-A2": ("ID", "区分 (Local / History / 前のC / 前のI)", "出発の契約", "出発の用途", "欄",
             "展開 (さらにたどる T-REF の ID、無ければ -)", "紙の行"),
    "T-G4": ("ID", "契約", "用途", "鍵の形 (item / life / terminal / …)", "鍵の欄", "排他の単位",
             "比較の bytes", "紙の行"),
    "T-G6": ("ID", "操作", "段階 (作成 / 入場 / 取得 / 採用 / 継続 / 評価の頭 / …)",
             "使う候補または記録", "出発の用途", "門の時点 (公開の前 / 入場の前 / 実取得の前 / …)", "適用方式", "紙の行"),
    "T-A1": ("ID", "項目", "適用段階 (更新の再構成 / 結果の生成 / 取得 / 採用 / 評価の頭)",
             "対象 (全Q* / 頭のA* / …)", "照合関係 (何と何を)", "必要証拠 (EW / EH / EA / EI / 台帳)",
             "失敗分類 (不足 / 不適合 / 使用の禁止)", "紙の行"),
}
FB_V1_KEYS = {
    "T-REF": ("id", "contract", "purpose", "field", "target_contract", "target_purpose", "role", "condition", "source"),
    "T-A2": ("id", "group", "contract", "purpose", "field", "expansion", "source"),
    "T-G4": ("id", "contract", "purpose", "key_shape", "key_fields", "exclusion", "compare_bytes", "source"),
    "T-G6": ("id", "operation", "stage", "contract", "purpose", "gate", "application", "source"),
    "T-A1": ("id", "item", "stages", "subject", "relation", "evidence", "failure", "source"),
}
CONTRACT = re.compile(r"sui\.(?:[a-z][a-z0-9_]*\.)*[a-z][a-z0-9_]*/[1-9][0-9]*\Z")
WORD = re.compile(r"[a-z][a-z0-9_]*\Z")
RULE_ID = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\Z")
ATOM_ID = re.compile(r"[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)*\Z")
SEGMENT = re.compile(r"(?:\*|(?:[^\x00-\x20/\[\]?*~]|~[01])+)(?:\[(?:kind=[a-z][a-z0-9_]*|id=[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)*)\])*\Z")
ROLES = {"U", "UE", "E", "leaf", "ignored", "unsupported"}
CONDITION_KEYS = {"nonnull", "is_null", "target_contract", "item_kind", "method", "method_not", "generation", "support_required", "resolve", "element", "count", "assert", "lookup"}
RELATION_VOCABULARY = ("present", "absent", "equal", "not_equal", "unique", "le", "lt", "member_of", "subset_of")
UNARY_RELATIONS = {"present", "absent", "unique"}
FAILURES = {"不足", "不適合", "使用の禁止"}
MISMATCH_CODES = {"schema", "shape", "noncanonical", "rational", "unit", "unknown_version", "normalization",
                  "unresolved_reference", "reference_kind", "observation_binding_mismatch", "measurement_conflict",
                  "clock_unaligned", "missing_contract", "model_falsified", "outside_evaluation_type",
                  "result_mismatch", "proof_mismatch"}
# Entry parents are Points; saved Body links are Refs (F-b:2056-2057).
OUTER_FIELD_TYPES = {"/parents/*": "point", "/inputs/*": "ref", "/basis/*": "ref", "/about/*": "ref"}
EVIDENCE_COLLECTIONS = {"executions": ("EW", "EH"), "uses": ("EW",),
                        "intervals": ("EI",), "acquisitions": ("EA",)}
RULE_DECLARATIONS = {"SCOPES", "DERIVATIONS", "EFFECTS", "MODEL_WALKS", "ENUMERATIONS",
                     "ENUMERATION_PROTOCOL", "ENUMERATION_SOURCES", "EVENT_SOURCES",
                     "VERSIONED_CLOCK_EXTENSIONS", "DERIVATION_ENUMERATION_INVENTORY",
                     "DERIVED_FIELD_ORIGINS", "DERIVATION_SOURCE_NOTES", "ATOM_PROTOCOL",
                     "ENUMERATION_CALL_PRELUDE", "COMPONENT_INSTANCE_SOURCES", "ENUMERATION_ID_MAP"}
GENERATOR_EXPORTS = {"ATOM_ORIGINS"}
FB_V1_TYPES = {
    "T-REF": ("ID", "契約", "用途", "欄", "契約", "用途", "役割", "JSON", "紙の行"),
    "T-A2": ("ID", "文", "契約", "用途", "欄", "ID参照:T-REF", "紙の行"),
    "T-G4": ("ID", "契約", "用途", "文", "JSON", "JSON", "JSON", "紙の行"),
    "T-G6": ("ID", "文", "文", "契約", "用途", "文", "文", "紙の行"),
    "T-A1": ("ID", "文", "JSON", "JSON", "JSON", "JSON", "文", "紙の行"),
}
FB_V1_KINDS = dict(zip(FB_V1_COLUMNS, ("参照", "必須入力", "鍵", "操作", "認証")))
TABLE_ID = re.compile(r"T-[A-Z0-9]+(?:-[A-Z0-9]+)*\Z")
CELL_TYPES = {"契約", "用途", "欄", "役割", "JSON", "文", "ID", "紙の行"}


def default_schema():
    return {t: {"kind": FB_V1_KINDS[t], "columns": [
        {"name": n, "key": k, "type": typ}
        for n, k, typ in zip(names, FB_V1_KEYS[t], FB_V1_TYPES[t])]}
        for t, names in FB_V1_COLUMNS.items()}


def valid_type(typ):
    return typ in CELL_TYPES or (typ.startswith("ID参照:") and TABLE_ID.fullmatch(typ[5:]))


class TableError(ValueError):
    """Unreadable or invalid source; CLI exit 2."""


@dataclass(frozen=True)
class Block:
    kind: str
    line: int
    text: str = ""
    rows: tuple = ()


def row_cells(text: str, line: int) -> tuple[str, ...]:
    """Lex a table row, tracking escapes/code spans and delimiter positions."""
    s = text.strip()
    if not s.startswith("|") or not s.endswith("|"):
        raise TableError(f"line {line}: table row needs leading/trailing pipes")
    cells, chars = [], []
    i, code = 1, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            chars.extend((c, s[i + 1]))
            i += 2
            continue
        if c == "`":
            end = i
            while end < len(s) and s[end] == "`":
                end += 1
            run = end - i
            code = 0 if code == run else (run if not code else code)
            chars.extend(s[i:end])
            i = end
            continue
        if c == "|" and not code:
            cells.append("".join(chars).strip())
            chars = []
        else:
            chars.append(c)
        i += 1
    if code or chars:
        raise TableError(f"line {line}: unclosed code span or row")
    return tuple(cells)


def blocks(text: str) -> list[Block]:
    """Parse headings, fenced code, paragraphs and strict pipe-table blocks."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        s, line = lines[i].strip(), i + 1
        if not s:
            i += 1
            continue
        fence = re.match(r"^(`{3,}|~{3,})", s)
        if fence:
            marker = fence[1]
            start = i + 1
            i += 1
            while i < len(lines) and not re.fullmatch(re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*", lines[i].strip()):
                i += 1
            content = "\n".join(lines[start:i])
            i += 1
            out.append(Block("code", line, content))
            continue
        if re.match(r"^#{1,6} ", s):
            out.append(Block("heading", line, s))
        elif s.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*", lines[i + 1]):
            rows = [(line, row_cells(s, line))]
            delimiter = row_cells(lines[i + 1], line + 1)
            if len(delimiter) != len(rows[0][1]):
                raise TableError(f"line {line + 1}: separator width differs from header")
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append((i + 1, row_cells(lines[i], i + 1)))
                i += 1
            out.append(Block("table", line, rows=tuple(rows)))
            continue
        else:
            out.append(Block("text", line, s))
        i += 1
    return out


def pointer(value: str) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    # '?' qualifies the whole nullable field, never an intermediate segment.
    raw = value[:-1] if value.endswith("?") else value
    return "?" not in raw and all(SEGMENT.fullmatch(p) and not re.search(r"~(?![01])", p) for p in raw[1:].split("/"))


def strict_json(value: str):
    def obj(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"duplicate JSON key {k}")
            result[k] = v
        return result
    return json.loads(value, object_pairs_hook=obj,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"invalid JSON {s}")))


def validate_cell(key: str, value: str, table: str):
    if (not value or any(c in value for c in "`|\r\n") or "<br" in value.lower()
            or "**" in value or "__" in value
            or re.fullmatch(r"(?:\*[^*\n]+\*|_[^_\n]+_|\[[^]]+\]\([^)]*\))", value)):
        raise ValueError("empty or decorated cell")
    if value == PENDING:
        if key not in {"field", "role", "condition", "key_shape", "key_fields", "exclusion", "compare_bytes", "relation"}:
            raise ValueError("未確定 not allowed in this column")
        return value
    if key == "id":
        if not RULE_ID.fullmatch(value) or not value.startswith(table[2:] + "-"):
            raise ValueError("invalid ID / table namespace")
    elif key in {"contract", "target_contract"}:
        if not CONTRACT.fullmatch(value) and not (value == "-" and (key == "target_contract" or table == "T-G6")):
            raise ValueError("expected versioned sui contract")
    elif key in {"purpose", "target_purpose"}:
        if not WORD.fullmatch(value) and not (value == "-" and (key == "target_purpose" or table == "T-G6")):
            raise ValueError("expected purpose word")
    elif key == "field":
        if table == "T-REF" and value.startswith("{"):
            data = strict_json(value)
            if (isinstance(data, dict) and set(data) == {"via", "path"}
                    and isinstance(data["via"], str) and RULE_ID.fullmatch(data["via"])
                    and pointer(data["path"])):
                return data
            if (isinstance(data, dict) and set(data) == {"walk", "root", "select"}
                    and isinstance(data["walk"], str) and pointer(data["root"])
                    and data["select"] in {"positive", "negative_query"}):
                return data
            raise ValueError("invalid via/walk field")
        if not pointer(value):
            raise ValueError("invalid JSON Pointer extension")
    elif key == "role":
        if value not in ROLES:
            raise ValueError("unknown role")
    elif key == "group":
        if value not in {"Local", "History", "前のC", "前のI"}:
            raise ValueError("unknown input group")
    elif key == "key_shape":
        if not WORD.fullmatch(value):
            raise ValueError("expected key-shape word")
    elif key == "expansion":
        if value != "-" and not re.fullmatch(r"REF-[A-Z0-9]+(?:-[A-Z0-9]+)*", value):
            raise ValueError("expected one T-REF ID or -")
    elif key == "subject":
        return strict_json(value) if value.startswith("{") else value
    elif key in {"condition", "key_fields", "exclusion", "compare_bytes", "stages", "relation", "evidence"}:
        data = strict_json(value)
        expected = {"key_fields": list, "exclusion": dict, "stages": list, "evidence": list}
        if key in expected and not isinstance(data, expected[key]):
            raise ValueError(f"expected JSON {expected[key].__name__}")
        if isinstance(data, (dict, list)) and not data:
            raise ValueError("empty JSON obligation")
        if key == "relation" and not isinstance(data, (dict, list)):
            raise ValueError("expected nonempty atom array (legacy object is unclassified)")
        if key == "compare_bytes" and not isinstance(data, (list, dict)):
            raise ValueError("expected JSON array/object")
        if key == "condition":
            if data is not True and not (isinstance(data, dict) and data and set(data) <= CONDITION_KEYS):
                raise ValueError("expected true or a declared condition object")
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in {"nonnull", "is_null"}:
                        valid = pointer(v)
                    elif k in {"target_contract", "method", "method_not", "generation"}:
                        valid = isinstance(v, str) and CONTRACT.fullmatch(v)
                    elif k == "support_required":
                        valid = type(v) is bool
                    elif k == "resolve":
                        valid = v == "clock_declaration_for_run"
                    elif k == "element":
                        # 欄の最も近い * の要素から相対の Pointer と期待する JSON 値の一致 (表記規約、表の係 3 通目)
                        valid = isinstance(v, dict) and bool(v) and all(pointer(rel) for rel in v)
                    elif k == "count":
                        valid = type(v) is int and v >= 0
                    elif k == "assert":
                        valid = isinstance(v, list) and bool(v)
                    elif k == "lookup":
                        valid = v == "fact_present/1"
                    else:
                        valid = isinstance(v, str) and WORD.fullmatch(v)
                    if not valid:
                        raise ValueError(f"invalid condition {k}")
        if key in {"stages", "evidence"}:
            allowed = ({"更新の再構成", "結果の生成", "取得", "採用", "評価の頭"} if key == "stages"
                       else {"EW", "EH", "EA", "EI", "台帳"})
            if not data or any(not isinstance(x, str) or x not in allowed for x in data) or len(set(data)) != len(data):
                raise ValueError(f"invalid {key} array")
        if key in {"key_fields", "compare_bytes"}:
            def paths(x):
                if isinstance(x, str) and x.startswith("/") and not pointer(x):
                    raise ValueError("invalid embedded Pointer")
                if isinstance(x, list):
                    for a in x:
                        paths(a)
                if isinstance(x, dict):
                    for a in x.values():
                        paths(a)
            paths(data)
        if key == "key_fields" or (key == "compare_bytes" and isinstance(data, list)):
            for part in data:
                if isinstance(part, str):
                    if not pointer(part):
                        raise ValueError("key/byte list member must be a Pointer")
                elif isinstance(part, dict):
                    if set(part) == {"literal"} or set(part) == {"derived"}:
                        if not isinstance(next(iter(part.values())), str) or not next(iter(part.values())):
                            raise ValueError("literal/derived must be a nonempty string")
                    elif "via" in part and set(part) <= {"via", "path", "compare"}:
                        if not isinstance(part["via"], str) or not part["via"]:
                            raise ValueError("invalid via")
                        if "path" in part and not pointer(part["path"]):
                            raise ValueError("invalid via Pointer")
                        if "compare" in part and not isinstance(part["compare"], str):
                            raise ValueError("invalid compare")
                    else:
                        raise ValueError("unknown key/byte expression")
                else:
                    raise ValueError("invalid key/byte expression")
        return data
    elif key == "application":
        if value not in {"同時", "対象別", "共通"}:
            raise ValueError("unknown application mode")
    elif key == "failure":
        if value not in {"不足", "不適合", "使用の禁止"}:
            raise ValueError("unknown failure class")
    return value


def typed_cell(typ, value):
    """The reusable cell grammar. F-b's additional constraints are a profile."""
    if not value or any(c in value for c in "`|\r\n") or "**" in value or "__" in value:
        raise ValueError("empty or decorated cell")
    if value == PENDING:
        if typ not in {"欄", "役割", "JSON", "文"}:
            raise ValueError("未確定 not allowed for this type")
        return value
    if typ == "契約" and value != "-" and not CONTRACT.fullmatch(value):
        raise ValueError("expected versioned sui contract")
    if typ == "用途" and value != "-" and not WORD.fullmatch(value):
        raise ValueError("expected purpose word")
    if typ == "欄" and not pointer(value):
        raise ValueError("invalid JSON Pointer extension")
    if typ == "役割" and value not in ROLES:
        raise ValueError("unknown role")
    if (typ == "ID" or typ.startswith("ID参照:")) and not (typ != "ID" and value == "-") and not RULE_ID.fullmatch(value):
        raise ValueError("invalid ID")
    return strict_json(value) if typ == "JSON" else value


def paper_declaration(doc, name):
    declarations = [b for b in doc if b.kind == "text" and b.text.startswith("表の一覧:")]
    if not declarations:
        return default_schema(), "F-b v1 の既定の宣言"
    if len(declarations) != 1:
        raise TableError(f"{name}: duplicate 表の一覧 declaration")
    schema = {}
    for token in declarations[0].text[len("表の一覧:"):].split():
        match = re.fullmatch(r"(T-[A-Z0-9]+(?:-[A-Z0-9]+)*)\(([^()\s]+)\)", token)
        if not match or match[1] in schema:
            raise TableError(f"{name}:{declarations[0].line}: invalid/duplicate table declaration {token}")
        schema[match[1]] = {"kind": match[2], "columns": []}
    if not schema:
        raise TableError(f"{name}: empty 表の一覧")
    return schema, "紙の明示宣言"


def read_rule_declarations(doc, name):
    """The explicitly introduced fenced JSON is data, never executable prose."""
    found = [b for b in doc if b.kind == "code" and b.text.lstrip().startswith("{")
             and re.search(r'"SCOPES"\s*:', b.text)]
    if not found:
        return {}, {}
    if len(found) != 1:
        raise TableError(f"{name}: duplicate closed rule declaration")
    block = found[0]
    try:
        declarations = strict_json(block.text)
    except ValueError as exc:
        raise TableError(f"{name}:{block.line + getattr(exc, 'lineno', 1)}: rule JSON: {exc}") from exc
    if (not isinstance(declarations, dict) or set(declarations) - declaration_names(declarations)
            or not {"SCOPES", "DERIVATIONS", "EFFECTS", "MODEL_WALKS"} <= set(declarations)):
        raise TableError(f"{name}:{block.line}: unknown/missing rule declaration names")
    locations = {"root": block.line + 1}
    for offset, line in enumerate(block.text.splitlines(), 1):
        # Locations are diagnostics only. Semantic identity always uses names/IDs.
        key = re.match(r'^\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*:', line)
        if key:
            locations.setdefault(key[1], block.line + offset)
        item = re.search(r'"id"\s*:\s*"([A-Z][A-Z0-9_-]*)"', line)
        if item:
            locations.setdefault(item[1], block.line + offset)
    return declarations, locations


def declaration_names(declarations):
    """v3 names are introduced by its closed declaration_sections, not prose."""
    protocol = declarations.get("ATOM_PROTOCOL", {}) if isinstance(declarations, dict) else {}
    sections = protocol.get("declaration_sections", {}) if isinstance(protocol, dict) else {}
    if (not isinstance(sections, dict) or any(not isinstance(k, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", k) is None or k in RULE_DECLARATIONS | GENERATOR_EXPORTS
            or not isinstance(v, str) or not v for k, v in sections.items())):
        raise TableError("ATOM_PROTOCOL: invalid declaration_sections")
    return RULE_DECLARATIONS | set(sections)


class RuleGrammar:
    """Closed syntax/reference validation, independent of runtime evaluation."""

    def __init__(self, data, name="<rules>"):
        self.data, self.name = data, name
        self.d = data.get("rule_declarations", {})
        self.locations = data.get("declaration_locations", {})
        self.refs = {r["id"] for r in data["tables"]["T-REF"]}
        self.a1 = {r["id"] for r in data["tables"]["T-A1"]}
        self.atom_ids, self.enum_ids = set(), set()

    def require(self, valid, where, reason):
        if not valid:
            line = where if isinstance(where, int) else self.locations.get(where, self.locations.get("root", 1))
            raise TableError(f"{self.name}:{line}: {where}: {reason}")

    def keys(self, obj, required, optional, where):
        self.require(isinstance(obj, dict) and required <= set(obj)
                     and set(obj) <= required | optional, where, "unknown/missing object keys")

    def names(self, values, known, where, *, empty=False):
        self.require(isinstance(values, list) and (empty or bool(values))
                     and all(isinstance(v, str) and v in known for v in values)
                     and len(set(values)) == len(values), where, "unknown/duplicate names")

    def independent(self, where, fn):
        return fn()

    def operand(self, value, records, evidence, where):
        if isinstance(value, str):
            rec, sep, path = value.partition(":")
            self.require(bool(sep) and rec in records | evidence
                         and (path == "" or pointer(path)), where, f"unbound record/invalid operand {value!r}")
            return
        self.require(isinstance(value, dict), where, "operand must be record/binding/derive/literal")
        if "literal" in value:
            self.keys(value, {"literal"}, set(), where)
        elif "derive" in value:
            self.keys(value, {"derive", "args"}, {"path"}, where)
            name, args = value["derive"], value["args"]
            self.require(isinstance(name, str) and name in self.d.get("DERIVATIONS", {})
                         and isinstance(args, list), where, f"unknown derive/invalid args: {name!r}")
            for arg in args:
                self.operand(arg, records, evidence, where)
            if "path" in value:
                self.require(value["path"] == "" or pointer(value["path"]), where, "invalid derived path")
            domains = {"effect": self.d.get("EFFECTS", {}), "via": self.refs,
                       "enumeration_source": self.d.get("ENUMERATION_SOURCES", {})}
            if name in domains:
                self.require(bool(args) and isinstance(args[0], dict) and set(args[0]) == {"literal"}
                             and isinstance(args[0]["literal"], str) and args[0]["literal"] in domains[name],
                             where, f"unknown {name} literal name")
            if name == "enumeration_arguments":
                self.require(not args, where, "enumeration_arguments takes no arguments")
            if name == "enumeration_source" and args[0]["literal"] in {"event_reading", "event_route"}:
                event_ids = {x["id"] for x in self.d.get("EVENT_SOURCES", [])}
                self.require(len(args) > 1 and isinstance(args[1], dict) and set(args[1]) == {"literal"}
                             and args[1]["literal"] in event_ids, where, "unknown event source id")
        elif "from" in value:
            self.keys(value, {"from", "where", "select", "path"}, set(), where)
            collection = value["from"]
            self.require(isinstance(collection, str), where, "invalid evidence collection")
            sources = ((collection,) if collection in {"EW", "EH"}
                       else EVIDENCE_COLLECTIONS.get(collection, ()))
            self.require(bool(set(sources) & evidence), where, f"unknown/unavailable evidence collection {collection!r}")
            self.require(value["select"] in {"one", "all", "any"}
                         and isinstance(value["where"], dict)
                         and (value["path"] == "" or pointer(value["path"])), where, "invalid evidence binding")
            for path, operand in value["where"].items():
                self.require(pointer(path), where, "invalid evidence where Pointer")
                # Bare JSON literals are permitted in where by the convention.
                if isinstance(operand, dict) or isinstance(operand, str) and ":" in operand:
                    self.operand(operand, records, evidence, where)
        else:
            self.require(False, where, "unknown operand form")

    def condition(self, value, records, evidence, where, *, enumeration=False):
        if value is True:
            return
        allowed = (set(self.d.get("ENUMERATION_PROTOCOL", {}).get("condition_keys", [])) if enumeration
                   else CONDITION_KEYS - {"count", "assert", "lookup"})
        self.require(isinstance(value, dict) and bool(value) and set(value) <= allowed,
                     where, "unknown/empty when condition")
        for key, v in value.items():
            if key in {"nonnull", "is_null"}:
                self.operand(v, records, evidence, where)
            elif key == "argument":
                self.keys(v, {"index", "equal"}, set(), where)
                self.require(type(v["index"]) is int and v["index"] >= 0, where, "invalid argument index")
            elif key == "stage":
                stages = {r["stage"] for r in self.data["tables"]["T-G6"]}
                stages |= {s for r in self.data["tables"]["T-A1"] for s in r["stages"]}
                self.require(isinstance(v, str) and v in stages, where, "unknown stage")
            elif key == "provenance":
                self.require(v in {"confirmed_related", "confirmed_unrelated", "unconfirmed"}, where, "unknown provenance")
            else:
                # Shared closed T-REF scalar condition grammar.
                try:
                    validate_cell("condition", json.dumps({key: v}), "T-REF")
                except (ValueError, TypeError) as exc:
                    self.require(False, where, str(exc))

    def atom(self, atom, records, evidence, where, *, enumeration=False):
        self.keys(atom, {"id", "left", "rel", "on_fail"}, {"right", "when", "code"}, where)
        aid, rel = atom["id"], atom["rel"]
        self.require(isinstance(aid, str) and ATOM_ID.fullmatch(aid) and aid not in self.atom_ids,
                     where, f"invalid/duplicate atom id {aid!r}")
        self.atom_ids.add(aid)
        self.require(isinstance(rel, str) and rel in RELATION_VOCABULARY, where, f"unknown rel {rel!r}")
        self.require(("right" in atom) == (rel not in UNARY_RELATIONS), where, "unary/binary relation arity")
        self.require(atom["on_fail"] in FAILURES, where, "unknown on_fail")
        if "code" in atom:
            self.require(atom["on_fail"] == "不適合" and isinstance(atom["code"], str)
                         and atom["code"] in MISMATCH_CODES, where, "code requires on_fail=不適合 and a declared mismatch code")
        self.operand(atom["left"], records, evidence, where)
        if "right" in atom:
            self.operand(atom["right"], records, evidence, where)
        if "when" in atom:
            self.condition(atom["when"], records, evidence, where, enumeration=enumeration)

    def template(self, value, records, evidence, where):
        if isinstance(value, dict) and not ({"literal", "derive", "from"} & set(value)):
            self.require(bool(value), where, "empty template")
            for child in value.values():
                self.template(child, records, evidence, where)
        elif isinstance(value, list):
            self.require(bool(value), where, "empty template array; use literal for a value")
            for child in value:
                self.template(child, records, evidence, where)
        else:
            self.operand(value, records, evidence, where)

    def subject(self, row):
        subject = row["subject"]
        if row["id"] == "A1-I-UNIQUE" and subject == "再構成用途で届いた全Q*":
            subject = {"scope": "requests", "records": ["Q*"]}
        self.keys(subject, {"scope", "records"}, set(), row["line"])
        scope = self.d.get("SCOPES", {}).get(subject["scope"])
        self.require(isinstance(scope, dict), row["line"], "unknown subject scope")
        self.names(subject["records"], set(scope["records"]), row["line"], empty=True)
        return subject, set(subject["records"]) | set(scope["records"])

    def declarations(self):
        if not self.d:
            return
        for name in ("SCOPES", "DERIVATIONS", "EFFECTS", "MODEL_WALKS"):
            self.require(isinstance(self.d[name], dict), name, "expected declaration object")
        for name, scope in self.d["SCOPES"].items():
            self.keys(scope, {"records", "meaning"}, set(), "SCOPES")
            self.names(scope["records"], set(scope["records"]) if isinstance(scope["records"], list) else set(), "SCOPES", empty=True)
            self.require(isinstance(scope["meaning"], str) and bool(scope["meaning"]), "SCOPES", "empty scope meaning")
        for group in ("DERIVATIONS", "EFFECTS", "DERIVED_FIELD_ORIGINS", "DERIVATION_SOURCE_NOTES"):
            values = self.d.get(group, {})
            self.require(isinstance(values, dict) and all(isinstance(k, str) and WORD.fullmatch(k)
                         and isinstance(v, str) and bool(v) for k, v in values.items()), group, "invalid named declaration")
        for name, walk in self.d["MODEL_WALKS"].items():
            self.keys(walk, {"document_contract", "roots", "recurse", "positive", "negative_query", "leaves",
                             "other_typed_children", "unknown"}, set(), "MODEL_WALKS")
            paths = [walk["document_contract"], *walk["roots"], *walk["recurse"].values()]
            paths += [p for ps in walk["positive"].values() for p in ps]
            paths += [p for obj in walk["negative_query"].values() for p in obj.values()]
            self.require(all(pointer(p) for p in paths) and walk["unknown"] == "missing_contract"
                         and walk["other_typed_children"] == "versioned_contract_schema", "MODEL_WALKS", "invalid model walk")
        for name, source in self.d.get("ENUMERATION_SOURCES", {}).items():
            self.keys(source, {"shape", "origin", "source"}, set(), "ENUMERATION_SOURCES")
            self.require(all(isinstance(v, str) and bool(v) for v in source.values()), "ENUMERATION_SOURCES", "invalid source description")
        protocol = self.d.get("ENUMERATION_PROTOCOL")
        if protocol is not None:
            self.keys(protocol, {"version", "modes", "condition_keys", "coverage", "source_policy", "recursive_guard",
                                 "table_links", "result_policy", "status_policy", "conditions", "outputs"}, set(), "ENUMERATION_PROTOCOL")
            self.require(type(protocol["version"]) is int and protocol["version"] == 1, "ENUMERATION_PROTOCOL", "unknown protocol version")
            self.names(protocol["modes"], {"pairs", "obligations", "record", "records", "relations", "cases", "values", "union",
                                          "components", "event_kinds", "dimensions", "component_schema"}, "ENUMERATION_PROTOCOL")
            self.names(protocol["condition_keys"], {"nonnull", "is_null", "item_kind", "generation", "support_required",
                                                   "method", "stage", "argument", "provenance"}, "ENUMERATION_PROTOCOL")
            self.require(set(protocol["outputs"]) == set(protocol["modes"])
                         and set(protocol["conditions"]) == {"true", *protocol["condition_keys"]}, "ENUMERATION_PROTOCOL", "protocol vocabulary links broken")
            self.require(all(isinstance(v, str) and bool(v) for v in [*protocol["outputs"].values(),
                         *protocol["conditions"].values(), *(protocol[k] for k in ("source_policy", "recursive_guard", "table_links", "result_policy", "status_policy"))]),
                         "ENUMERATION_PROTOCOL", "missing protocol description")
            coverage_keys = {"declaration_ids", "instance_ids", "actual", "comparison", "on_missing_declaration_or_adapter",
                             "on_missing_returned_id_or_field", "on_duplicate_or_extra_id", "on_missing_primary_evidence",
                             "on_unknown_condition", "inactive", "empty", "test_operations", "test_expected"}
            coverage = protocol["coverage"]
            self.keys(coverage, coverage_keys, set(), "ENUMERATION_PROTOCOL")
            self.require(all(isinstance(v, str) and bool(v) for k, v in coverage.items() if k != "test_operations"),
                         "ENUMERATION_PROTOCOL", "invalid coverage policy")
            operations = {"drop_case", "drop_instance", "drop_component", "duplicate_instance", "alter_value"}
            self.names(coverage["test_operations"], operations, "ENUMERATION_PROTOCOL")
            self.require(set(coverage["test_operations"]) == operations and all(coverage[k] in FAILURES
                         for k in coverage_keys if k.startswith("on_")), "ENUMERATION_PROTOCOL", "incomplete mutation/failure vocabulary")
        self.enumerations()
        self.independent("DERIVATION_ENUMERATION_INVENTORY", self.derivation_inventory)
        for name in self.d.get("DERIVED_FIELD_ORIGINS", {}):
            self.require(name in self.d["DERIVATIONS"], "DERIVED_FIELD_ORIGINS", "unknown origin consumer")
        if "DERIVED_FIELDS" in self.d.get("ENUMERATIONS", {}):
            self.require(set(self.d.get("DERIVED_FIELD_ORIGINS", {})) == set(self.d["ENUMERATIONS"]["DERIVED_FIELDS"]["consumers"]),
                         "DERIVED_FIELD_ORIGINS", "component origin/consumer mapping broken")
        event_ids = set()
        for event in self.d.get("EVENT_SOURCES", []):
            self.keys(event, {"id", "record", "evidence", "source", "refs"}, set(), "EVENT_SOURCES")
            self.require(isinstance(event["id"], str) and event["id"] not in event_ids, "EVENT_SOURCES", "duplicate event id")
            event_ids.add(event["id"])
            self.names(event["evidence"], {"EW", "EH", "EA", "EI", "台帳"}, "EVENT_SOURCES")
        extension_ids = set()
        for extension in self.d.get("VERSIONED_CLOCK_EXTENSIONS", []):
            self.keys(extension, {"id", "generation", "projection", "time_projection", "extra_pairs", "source"}, set(), "VERSIONED_CLOCK_EXTENSIONS")
            self.require(extension["id"] not in extension_ids and all(isinstance(extension[k], str) and CONTRACT.fullmatch(extension[k])
                         for k in ("generation", "projection", "time_projection")), "VERSIONED_CLOCK_EXTENSIONS", "invalid/duplicate versioned extension")
            extension_ids.add(extension["id"])
            records = set().union(*(set(s["records"]) for s in self.d["SCOPES"].values()))
            self.require(isinstance(extension["extra_pairs"], list), "VERSIONED_CLOCK_EXTENSIONS", "invalid extra_pairs")
            for pair in extension["extra_pairs"]:
                self.keys(pair, {"id", "kind", "left", "right", "when"}, set(), "VERSIONED_CLOCK_EXTENSIONS")
                self.operand(pair["left"], records, {"EW", "EH", "EA", "EI"}, "VERSIONED_CLOCK_EXTENSIONS")
                self.operand(pair["right"], records, {"EW", "EH", "EA", "EI"}, "VERSIONED_CLOCK_EXTENSIONS")
                self.condition(pair["when"], records, {"EW", "EH", "EA", "EI"}, "VERSIONED_CLOCK_EXTENSIONS", enumeration=True)

    def derivation_inventory(self):
        inventory = self.d.get("DERIVATION_ENUMERATION_INVENTORY")
        if inventory is None:
            return
        where = "DERIVATION_ENUMERATION_INVENTORY"
        self.keys(inventory, {"reviewed", "entries", "added_helpers"}, set(), where)
        entries, helpers = inventory["entries"], inventory["added_helpers"]
        self.require(isinstance(entries, dict), where, "entries must be an object")
        self.independent(where, lambda: self.require(type(inventory["reviewed"]) is int
                         and inventory["reviewed"] == len(entries), where, "reviewed count mismatch"))
        self.names(helpers, set(self.d["DERIVATIONS"]), where, empty=True)
        self.independent(where, lambda: self.require(
            set(entries).isdisjoint(helpers) and set(entries) | set(helpers) == set(self.d["DERIVATIONS"]), where,
            "derivation classification is incomplete; unclassified="
            + repr(sorted(set(self.d["DERIVATIONS"]) - set(entries) - set(helpers)))
            + "; undeclared=" + repr(sorted((set(entries) | set(helpers)) - set(self.d["DERIVATIONS"])))))
        for name, entry in entries.items():
            def unit():
                cls = entry.get("class") if isinstance(entry, dict) else None
                self.keys(entry, {"class", "blocks"} if cls == "ア" else {"class", "reason"},
                          {"reason"} if cls == "ア" else set(), name)
                self.require(cls in {"ア", "イ"}, name, "unknown inventory class")
                if "reason" in entry:
                    self.require(isinstance(entry["reason"], str) and bool(entry["reason"]), name, "missing classification reason")
                if cls == "ア":
                    self.names(entry["blocks"], set(self.d.get("ENUMERATIONS", {})), name)
                    expected = {b for b, block in self.d.get("ENUMERATIONS", {}).items() if name in block["consumers"]}
                    self.require(set(entry["blocks"]) == expected, name, "consumer/block mapping broken")
            self.independent(name, unit)

    def enumerations(self):
        required = {"consumers", "scopes", "mode", "items", "source"}
        optional = {"adapter", "binding", "capture", "classification", "clock_alignment", "combine_with", "contracts", "each", "empty",
                    "forbid", "frames", "normalization", "order", "output_fields", "output_instance_key", "per_record", "preserve_fields",
                    "preserve_reasons", "preserve_unprojected", "recursive_parent", "select", "sides", "status", "supported_kinds", "transform",
                    "unit", "unknown_boundary_contract", "unknown_case", "unknown_contract", "unknown_event", "when", "witness"}
        item_optional = {"absent", "assert", "budget", "case", "charge", "classification", "code", "consumer", "default", "domains", "each", "empty", "enum", "enum_from",
                         "each_scope", "independent", "independent_when", "kind", "left", "legal_absence", "mapping", "meaning", "on_fail",
                         "outcome", "path", "rel", "relations", "required", "right", "role", "scopes", "source", "stored", "template", "type", "unit", "value"}
        for name, block in self.d.get("ENUMERATIONS", {}).items():
            reserved = RULE_DECLARATIONS | {"METADATA", "FIELD_TYPES", "A1_RELATIONS", "A1_SUBJECTS", "RELATION_VOCABULARY", "EVIDENCE_COLLECTIONS"}
            reserved |= {t.replace("-", "_") for t in self.data["tables"]}
            self.require(re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is not None and name not in reserved, name, "invalid/reserved enumeration name")
            self.keys(block, required, optional, name)
            self.names(block["consumers"], set(self.d["DERIVATIONS"]), name)
            self.names(block["scopes"], set(self.d["SCOPES"]), name)
            self.require(block["mode"] in self.d.get("ENUMERATION_PROTOCOL", {}).get("modes", [])
                         and isinstance(block["items"], list) and bool(block["items"])
                         and isinstance(block["source"], str) and bool(block["source"]), name, "invalid enumeration mode/items/source")
            records = set().union(*(set(self.d["SCOPES"][s]["records"]) for s in block["scopes"]))
            evidence = {"EW", "EH", "EA", "EI"}  # enumeration consumers bind these evidence operands explicitly
            for key in ("each", "classification"):
                if isinstance(block.get(key), dict):
                    self.operand(block[key], records, evidence, name)
            if "when" in block:
                self.condition(block["when"], records, evidence, name, enumeration=True)
            for item in block["items"]:
                self.keys(item, {"id", "when"}, item_optional, name)
                iid = item["id"]
                self.require(isinstance(iid, str) and ATOM_ID.fullmatch(iid) and iid not in self.enum_ids, name, f"invalid/duplicate enumeration id {iid!r}")
                self.enum_ids.add(iid)
                where = iid
                item_records = records
                if "scopes" in item:
                    self.names(item["scopes"], set(block["scopes"]), where)
                    item_records = set().union(*(set(self.d["SCOPES"][s]["records"]) for s in item["scopes"]))
                if "consumer" in item:
                    self.require(item["consumer"] in block["consumers"], where, "unknown item consumer")
                self.condition(item["when"], item_records, evidence, where, enumeration=True)
                if "independent_when" in item:
                    self.condition(item["independent_when"], item_records, evidence, where, enumeration=True)
                for key in ("value", "left", "right", "stored", "independent", "each", "budget"):
                    if key in item:
                        self.operand(item[key], item_records, evidence, where)
                if "path" in item:
                    self.require(pointer(item["path"]), where, "invalid enumeration output path")
                if "empty" in item:
                    self.require(isinstance(item["empty"], str) and bool(item["empty"]), where, "empty policy must be a nonempty description")
                if {"enum", "enum_from"} & set(item):
                    self.require(block["mode"] == "component_schema", where, "enum constraints belong to component_schema items")
                if "enum" in item:
                    values = item["enum"]
                    self.require(isinstance(values, list) and bool(values), where, "enum must be a nonempty JSON value array")
                    identities = [json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) for v in values]
                    self.require(len(identities) == len(set(identities)), where, "duplicate enum value")
                if "enum_from" in item:
                    ref = item["enum_from"]
                    match = re.fullmatch(r"ENUMERATIONS\.([A-Z][A-Z0-9_]*)\.items\.id", ref) if isinstance(ref, str) else None
                    self.require(match is not None and match[1] in self.d.get("ENUMERATIONS", {}), where, "unresolved/invalid enum_from; expected ENUMERATIONS.<block>.items.id")
                if "template" in item:
                    self.require(isinstance(item["template"], dict) and bool(item["template"]), where, "invalid template")
                    self.template(item["template"], item_records, evidence, where)
                if "relations" in item:
                    self.names(item["relations"], self.a1, where)
                if "assert" in item:
                    self.require(isinstance(item["assert"], list) and bool(item["assert"]), where, "invalid assertion array")
                    for atom in item["assert"]:
                        self.atom(atom, item_records, evidence, where, enumeration=True)
                mode = block["mode"]
                self.require("code" not in item or mode == "relations", where, "code belongs to a relation atom")
                if mode == "relations":
                    self.atom({k: v for k, v in item.items() if k != "each_scope"}, item_records, evidence, where, enumeration=True)
                if mode == "pairs":
                    self.require({"kind", "left", "right"} <= set(item), where, "pair needs kind/left/right")
                    if isinstance(item["kind"], dict):
                        self.operand(item["kind"], item_records, evidence, where)
                    else:
                        self.require(item["kind"] in {"equal", "le"}, where, "unknown pair relation")
                if mode in {"record", "records", "components", "component_schema"}:
                    self.require({"path", "value"} <= set(item), where, "component needs path/value")
                if mode in {"values", "union"}:
                    self.require("value" in item, where, "value missing")
                if mode == "obligations":
                    self.require("stored" in item and bool({"independent", "relations", "assert"} & set(item)), where, "obligation has no independent relation")
                if mode == "event_kinds":
                    self.require(isinstance(item.get("kind"), str) and type(item.get("unit")) is int and item["unit"] > 0, where, "invalid event kind/unit")
                if mode == "dimensions":
                    self.require({"path", "type", "role", "default", "charge"} <= set(item)
                                 and item["role"] in {"accuracy", "limit"} and type(item["charge"]) is bool, where, "invalid budget dimension")

    def validate(self):
        if "ATOM_PROTOCOL" in self.d:
            return AtomCompiler(self.data, self.name).validate()
        if {"ENUMERATION_CALL_PRELUDE", "COMPONENT_INSTANCE_SOURCES", "ENUMERATION_ID_MAP"} & set(self.d):
            raise AtomSyntaxError([{"id": "ATOM_PROTOCOL", "line": self.locations.get("root", 1),
                                    "reason": f"{self.name}: new atomic declarations require ATOM_PROTOCOL"}])
        self.declarations()
        unatomized, subjects, relations = [], {}, {}
        atom_count = 0
        for row in self.data["tables"]["T-A1"]:
            atoms = row["relation"]
            if atoms == PENDING:
                continue
            if isinstance(atoms, dict):
                unatomized.append({"id": row["id"], "line": row["line"], "reason": "relation remains a legacy object"})
                continue
            self.require(isinstance(atoms, list) and bool(atoms), row["line"], "relation must be a nonempty atom array")
            subject, records = self.subject(row)
            subjects[row["id"]], relations[row["id"]] = subject, atoms
            for atom in atoms:
                self.atom(atom, records, set(row["evidence"]), row["line"])
                atom_count += 1
        for row in self.data["tables"]["T-REF"]:
            field, condition, where = row["field"], row["condition"], row["line"]
            if isinstance(field, dict):
                if "via" in field:
                    self.require(field["via"] in self.refs, where, "unresolved via T-REF ID")
                else:
                    self.require(field["walk"] in self.d.get("MODEL_WALKS", {}), where, "unknown walk")
                    self.require(field["select"] in self.d["MODEL_WALKS"][field["walk"]], where, "unknown walk selector")
            if isinstance(condition, dict) and "assert" in condition:
                for atom in condition["assert"]:
                    self.atom(atom, {"SELF", "TARGET"}, {"EW", "EH", "EA", "EI"}, where)
            if isinstance(condition, dict) and "lookup" in condition:
                self.require(isinstance(field, dict) and "walk" in field and field["select"] == "negative_query"
                             and condition["lookup"] in self.d["MODEL_WALKS"][field["walk"]]["negative_query"],
                             where, "lookup is not declared by the negative query walk")
        for row in self.data["tables"]["T-G4"]:
            exclusion = row["exclusion"]
            if not isinstance(exclusion, dict):
                continue
            if "rule" in exclusion:
                rule = exclusion["rule"]
                self.require(isinstance(rule, str) or isinstance(rule, list) and bool(rule)
                             and all(isinstance(v, str) for v in rule), row["line"], "invalid exclusion rule")
            if "stage_mapping" in exclusion:
                mapping = exclusion["stage_mapping"]
                self.require(isinstance(mapping, dict) and bool(mapping) and isinstance(exclusion.get("via"), str)
                             and exclusion["via"] in self.refs and all(isinstance(k, str) and WORD.fullmatch(k)
                             and isinstance(v, str) and WORD.fullmatch(v) for k, v in mapping.items()), row["line"], "invalid stage_mapping/via")
        return {"unatomized_a1": unatomized, "a1_subjects": subjects, "a1_relations": relations,
                "atom_count": atom_count, "enumeration_count": len(self.d.get("ENUMERATIONS", {})),
                "enumeration_item_count": len(self.enum_ids)}


class AtomSyntaxError(TableError):
    """All independent v2 syntax obligations found in one validation pass."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__("\n".join(x["reason"] for x in issues))


class AtomCompiler(RuleGrammar):
    """Compile the paper's closed v2/v3 schemas; never evaluate a derivation."""

    def __init__(self, data, name="<rules>"):
        super().__init__(data, name)
        self.p = self.d["ATOM_PROTOCOL"]
        self.phased = self.p.get("version") == 3
        self.origins = {}
        self.issues, self.compiled, self.relations = [], deepcopy(self.d), {}
        self.source_tables = data.get("source_tables", data["tables"])
        self.tables = deepcopy(self.source_tables)
        self.rows = {r["id"]: r for r in self.source_tables["T-A1"]}
        self.locations = dict(self.locations)
        for row in self.rows.values():
            self.locations.setdefault(row["id"], row["line"])
            if isinstance(row["relation"], list):
                for atom in row["relation"]:
                    if isinstance(atom, dict) and isinstance(atom.get("id"), str):
                        self.locations.setdefault(atom["id"], row["line"])
        self.direct_count = self.reused_count = 0

    def attempt(self, where, fn):
        try:
            return fn()
        except (TableError, KeyError, TypeError, ValueError, AttributeError) as exc:
            issue = {"id": str(where), "line": where if type(where) is int else self.locations.get(str(where), self.locations.get("root", 1)),
                     "reason": str(exc)}
            diagnostic = re.search(r":([0-9]+): ([^:]+): ", str(exc))
            if diagnostic:
                issue.update(line=int(diagnostic[1]), id=diagnostic[2])
            if issue not in self.issues:
                self.issues.append(issue)
            return None

    def independent(self, where, fn):
        return self.attempt(where, fn)

    def schema(self, value, spec, where, prefix=""):
        required, optional = spec[prefix + "required"], spec.get(prefix + "optional", [])
        self.require(isinstance(required, list) and isinstance(optional, list)
                     and all(isinstance(k, str) for k in required + optional)
                     and len(set(required + optional)) == len(required + optional)
                     and spec.get("additional_keys") is False, where, "invalid closed schema declaration")
        self.keys(value, set(required), set(optional), where)

    def protocol(self):
        supported = {"version", "atom", "operand", "predicate", "each", "group", "reuse", "environment", "evaluation",
                     "capture", "coverage", "tests", "legacy_atom_when", "table_boundary", "source", "component_instances",
                     "source_policy", "migration_map", "helper_signatures", "new_source_signatures"}
        if self.phased:
            supported |= {"phase", "runtime_capture", "declaration_sections"}
        self.keys(self.p, {"version", "atom", "operand", "predicate", "each", "group", "reuse", "environment",
                             "capture", "component_instances", "migration_map"}, supported, "ATOM_PROTOCOL")
        self.require(type(self.p["version"]) is int and self.p["version"] in {2, 3}, "ATOM_PROTOCOL", "unsupported protocol version")
        self.require("ENUMERATION_PROTOCOL" not in self.d, "ATOM_PROTOCOL", "legacy modes cannot accompany ATOM_PROTOCOL")
        self.require(all(isinstance(self.d.get(k), dict) for k in ("ENUMERATIONS", "COMPONENT_INSTANCE_SOURCES", "ENUMERATION_ID_MAP"))
                     and isinstance(self.d.get("ENUMERATION_CALL_PRELUDE"), list), "ATOM_PROTOCOL", "missing/invalid atomic declaration blocks")
        for section in ("atom", "predicate", "each", "reuse", "component_instances", "migration_map"):
            spec = self.p[section]
            self.require(isinstance(spec, dict) and spec.get("additional_keys") is False
                         and isinstance(spec.get("required"), list), "ATOM_PROTOCOL", f"invalid {section} schema")
        self.unary, self.binary = set(self.p["atom"]["unary"]), set(self.p["atom"]["binary"])
        self.require(bool(self.unary) and bool(self.binary) and self.unary.isdisjoint(self.binary), "ATOM_PROTOCOL", "invalid relation arities")
        self.require(self.p["reuse"].get("expansion" if self.phased else "phase") == "compile_time_only"
                     and self.p["reuse"].get("id_template") == "<item-id>::<referenced-atom-id>"
                     and self.p["reuse"].get("expand_all") is True
                     and self.p["each"].get("shadowing") == "forbidden", "ATOM_PROTOCOL", "unsupported reuse/binding semantics")
        for group, domain in (("helper_signatures", self.d["DERIVATIONS"]), ("new_source_signatures", self.d.get("ENUMERATION_SOURCES", {}))):
            for name, signature in self.p.get(group, {}).items():
                self.require(name in domain, "ATOM_PROTOCOL", f"unknown signature name {name}")
                arities = signature.get("arities") if isinstance(signature, dict) else [signature]
                self.require(isinstance(arities, list) and bool(arities) and all(type(x) is int and x >= 0 for x in arities),
                             "ATOM_PROTOCOL", f"invalid arity for {name}")
        if self.phased:
            phase = self.p["phase"]
            self.names(phase["values"], {"runtime", "test"}, "ATOM_PROTOCOL")
            self.require(set(phase["values"]) == {"runtime", "test"}
                         and phase["flatten_before_filter"] is True
                         and phase["default"] == "runtime for legacy T-A1 and T-REF assert atoms; block/item declarations are explicit",
                         "ATOM_PROTOCOL", "unsupported phase/default/filter semantics")
            self.require(self.p["capture"]["phase"] == self.p["coverage"]["phase"] == "test"
                         and self.p["runtime_capture"]["phase"] == "runtime"
                         and self.p["runtime_capture"]["construction_capture_required"] is False,
                         "ATOM_PROTOCOL", "construction capture must remain test-only")
            sections = declaration_names(self.d) - RULE_DECLARATIONS
            self.require(sections <= set(self.d), "ATOM_PROTOCOL", "missing declared sections")

    def phase(self, value, where, parent=("runtime", None)):
        """Resolve defaults for direct atoms; a use supplies its source default."""
        if not self.phased:
            return parent
        phase = value.get("phase", parent[0])
        reason = value.get("phase_reason", parent[1])
        self.require(isinstance(phase, str) and phase in self.p["phase"]["values"], where, "unknown phase")
        if "phase_reason" in value:
            self.require(isinstance(reason, str) and reason in self.p["phase"]["reason_values"], where, "unknown phase_reason")
        if "data_phase" in value:
            self.require(value["data_phase"] in self.p["phase"]["data_phase_values"], where, "unknown data_phase")
        return phase, reason

    def runtime_dependencies(self, values, where):
        """Reject explicit construction-capture/manifest dependencies, including guards."""
        for obj in self.objects(values):
            name, args = obj.get("derive"), obj.get("args", [])
            self.require(name not in {"expected_instances", "captured_instances"}, where,
                         "runtime depends on test capture/coverage")
            if name == "effect":
                self.require(args[:1] != [{"literal": self.p["capture"]["effect"]}], where,
                             "runtime depends on test capture/coverage")
            if name == "rule_data" and args and isinstance(args[0], dict):
                path = args[0].get("literal", "")
                self.require(isinstance(path, str) and path.split(".")[0] not in {
                    "ENUMERATION_ID_MAP", "ENUMERATION_CALL_PRELUDE", "PHASE_MIGRATION"}, where,
                    "runtime depends on test manifest")

    def operand(self, value, records, evidence, where):
        if isinstance(value, dict) and "literal" in value:
            self.schema(value, self.p["operand"]["literal"], where)
            return
        if isinstance(value, dict) and "derive" in value:
            self.schema(value, self.p["operand"]["derivation"], where)
        super().operand(value, records, evidence, where)
        if not isinstance(value, dict) or "derive" not in value:
            return
        name, args = value["derive"], value["args"]
        signature = self.p.get("helper_signatures", {}).get(name)
        if signature is not None:
            self.require(len(args) in signature["arities"], where, f"invalid declared arity for {name}")
        if name == "enumeration_source":
            arity = self.p.get("new_source_signatures", {}).get(args[0]["literal"])
            if arity is not None:
                self.require(len(args) == arity + 1, where, "invalid declared source arity")
        if name == "project" and len(args) == 3:
            selector = args[1].get("literal") if isinstance(args[1], dict) else None
            self.schema(selector, self.p["capture"]["projection_selector"], where)
            capture = args[0]
            self.require(isinstance(capture, dict) and capture.get("derive") == "effect"
                         and capture.get("args") == [{"literal": self.p["capture"]["effect"]}, "CALL:"]
                         and capture.get("path", "") == "" and args[2] == "BINDINGS:",
                         where, "capture projection requires the actual CALL return and lexical BINDINGS")
            block, case = selector["block"], selector["case"]
            self.require(isinstance(block, str) and block in self.d["ENUMERATIONS"]
                         and isinstance(case, str) and case in {x["id"] for x in self.d["ENUMERATIONS"][block]["items"]}
                         and isinstance(selector["component"], str), where, "unresolved capture selector")
        if name in {"rule_data", "declaration_instances", "source_instances"}:
            target = args[0].get("literal") if args and isinstance(args[0], dict) else None
            self.require(isinstance(target, str), where, f"{name} requires a declared literal name")
            if name == "rule_data":
                values = [self.d]
                for key in target.split("."):
                    following = []
                    for v in values:
                        for obj in v if isinstance(v, list) else [v]:
                            self.require(isinstance(obj, dict) and key in obj, where, f"unresolved rule_data path {target}")
                            following.append(obj[key])
                    values = following
            else:
                domain = self.d["ENUMERATIONS"] if name == "declaration_instances" else self.d["COMPONENT_INSTANCE_SOURCES"]
                self.require(target in domain, where, f"unknown {name} target")

    def relation(self, value, records, evidence, where):
        rel = value["rel"]
        self.require(isinstance(rel, str) and rel in self.unary | self.binary, where, f"unknown rel {rel!r}")
        self.require(("right" in value) == (rel in self.binary), where, "unary/binary relation arity")
        self.operand(value["left"], records, evidence, where)
        if "right" in value:
            self.operand(value["right"], records, evidence, where)

    def predicates(self, values, records, evidence, where, *, legacy=False):
        if legacy and isinstance(values, dict):
            templates = self.p.get("legacy_atom_when", {})
            self.require(bool(values) and templates.get("expansion" if self.phased else "phase") == "compile_time_only", where, "invalid legacy when")
            def substitute(v, parameter):
                if isinstance(v, dict):
                    if set(v) == {"parameter"}:
                        self.require(v["parameter"] == "value", where, "unknown template parameter")
                        return deepcopy(parameter)
                    return {k: substitute(x, parameter) for k, x in v.items()}
                if isinstance(v, list):
                    return [substitute(x, parameter) for x in v]
                return v
            result = []
            for key, parameter in values.items():
                self.require(isinstance(templates.get(key), dict), where, f"unknown legacy when key {key}")
                result.append(substitute(templates[key], parameter))
            values = result
        self.require(isinstance(values, list), where, "when must be a predicate array")
        for predicate in values:
            self.schema(predicate, self.p["predicate"], where)
            self.relation(predicate, records, evidence, where)
        return deepcopy(values)

    def each(self, entries, records, evidence, where, consumers=()):
        self.require(isinstance(entries, list), where, "each must be an array")
        bound = set(records)
        for entry in entries:
            self.schema(entry, self.p["each"], where)
            name = entry["bind"]
            self.require(isinstance(name, str) and name in self.p["environment"]["lexical"] and name not in bound | evidence,
                         where, "unknown/shadowed lexical binding")
            self.require(entry["select"] in self.p["each"]["select"], where, "unknown each selection")
            self.operand(entry["in"], bound, evidence, where)
            self.require(not any(v.get("derive") in consumers or
                                 v.get("derive") == "effect" and v.get("args", [])[:1] == [{"literal": self.p["capture"]["effect"]}]
                                 for v in self.objects(entry["in"])),
                         where, "each source invokes its owning consumer")
            bound.add(name)
        return bound

    @staticmethod
    def objects(value):
        """Walk executable declarations, preserving literal/data JSON as opaque."""
        if isinstance(value, dict):
            yield value
            for key, child in value.items():
                if key not in {"literal", "data"}:
                    yield from AtomCompiler.objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from AtomCompiler.objects(child)

    def compile_atom(self, value, records, evidence, where, *, inherited=(), aid=None,
                     phase_parent=("runtime", None), outer_each=()):
        self.schema(value, self.p["atom"], where)
        result = deepcopy(value)
        original = value["id"]
        self.require(isinstance(original, str) and ATOM_ID.fullmatch(original), where, "invalid atom id")
        result["id"] = aid or original
        self.require(result["id"] not in self.atom_ids, where, f"duplicate atom id {result['id']}")
        self.atom_ids.add(result["id"])
        bound = self.each(value.get("each", []), records, evidence, where)
        self.relation(value, bound, evidence, where)
        self.require(value["on_fail"] in self.p["atom"]["on_fail"], where, "unknown on_fail")
        required = value["on_fail"] == self.p["atom"]["code_required_when"]
        self.require(not required or "code" in value, where, "mismatch atom requires a declared code")
        if "code" in value:
            self.require(value["on_fail"] not in self.p["atom"]["code_forbidden_when"]
                         and isinstance(value["code"], str) and value["code"] in self.p["atom"]["codes"], where, "invalid/forbidden code")
        when = self.predicates(value.get("when", []), bound, evidence, where, legacy=True)
        if inherited or "when" in value:
            result["when"] = [*deepcopy(inherited), *when]
        if self.phased:
            phase, reason = self.phase(value, where, phase_parent)
            result["phase"] = phase
            if reason is not None:
                result["phase_reason"] = reason
            if phase == "runtime":
                self.runtime_dependencies([result, *outer_each], where)
        return result

    def sequence(self, values, owner, records, evidence, where, inherited=(),
                 phase_parent=("runtime", None), outer_each=()):
        self.require(isinstance(values, list), where, "prelude/atoms must be an array")
        result = []
        for value in values:
            if isinstance(value, dict) and "use" in value:
                def expand():
                    self.schema(value, self.p["reuse"], where)
                    ref = value["use"]
                    self.require(isinstance(ref, str) and ref in self.rows, where, f"unresolved use {ref!r}")
                    self.require(self.subject(self.rows[ref])[0]["scope"] in self.block_scopes,
                                 where, "use crosses authenticated scopes")
                    sources = self.rows[ref]["relation"]
                    self.require(isinstance(sources, list) and bool(sources), where, "use requires an atomic T-A1 row")
                    # The target is exclusively a T-A1 row. Nested use cannot form a cycle.
                    # Diagnose each sibling even if another source atom failed. Any
                    # collected issue still prevents emitting the whole module.
                    for source in sources:
                        def expand_atom():
                            self.require(isinstance(source, dict) and isinstance(source.get("id"), str), where, "invalid reused atom")
                            aid = self.p["reuse"]["id_template"].replace("<item-id>", owner).replace("<referenced-atom-id>", source["id"])
                            if self.phased:
                                row = self.rows[ref]
                                subject, source_records = self.subject(row)
                                lexical = set(self.p["environment"]["lexical"]) | {k for k, v in self.p["environment"].items() if isinstance(v, dict)}
                                atom = self.compile_atom(source, source_records | (records & lexical), set(row["evidence"]), where,
                                                         inherited=inherited, aid=aid, outer_each=outer_each)
                                self.origins[aid] = {"row_id": ref, "atom_id": source["id"], "subject": deepcopy(subject),
                                                     "stages": deepcopy(row["stages"]), "evidence": deepcopy(row["evidence"])}
                                return atom
                            return self.compile_atom(source, records, evidence, where, inherited=inherited, aid=aid)
                        atom = self.attempt(where, expand_atom)
                        if atom is not None:
                            result.append(atom)
                            self.reused_count += 1
                self.attempt(where, expand)
            else:
                location = value["id"] if isinstance(value, dict) and isinstance(value.get("id"), str) else where
                atom = self.attempt(location, lambda: self.compile_atom(value, records, evidence, location,
                    inherited=inherited if self.phased else (), phase_parent=phase_parent, outer_each=outer_each))
                if atom is not None:
                    result.append(atom)
                    self.direct_count += 1
        return result

    def enumerations(self):
        compiled = {}
        for name, block in self.d.get("ENUMERATIONS", {}).items():
            def compile_block():
                reserved = declaration_names(self.d) | GENERATOR_EXPORTS | {"METADATA", "FIELD_TYPES", "A1_RELATIONS", "A1_SUBJECTS", "RELATION_VOCABULARY", "EVIDENCE_COLLECTIONS"}
                reserved |= {t.replace("-", "_") for t in self.data["tables"]}
                self.require(re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is not None and name not in reserved,
                             name, "invalid/reserved enumeration name")
                self.schema(block, self.p["group"], name, "block_")
                block_phase = self.phase(block, name)
                self.names(block["consumers"], set(self.d["DERIVATIONS"]), name)
                self.names(block["scopes"], set(self.d["SCOPES"]), name)
                self.block_scopes = set(block["scopes"])
                records = set().union(*(set(self.d["SCOPES"][s]["records"]) for s in block["scopes"]))
                records |= {k for k, v in self.p["environment"].items() if isinstance(v, dict)}
                evidence = set().union(*(set(v) for v in EVIDENCE_COLLECTIONS.values()))
                bound = self.each(block.get("each", []), records, evidence, name, block["consumers"])
                guards = self.predicates(block.get("when", []), bound, evidence, name)
                output = deepcopy(block)
                block_each = block.get("each", [])
                output["prelude"] = self.sequence(block["prelude"], name, bound, evidence, name, guards,
                                                    block_phase, block_each)
                self.require(isinstance(block["items"], list), name, "items must be an array")
                output["items"] = []
                for item in block["items"]:
                    where = item["id"] if isinstance(item, dict) and isinstance(item.get("id"), str) else name
                    def compile_item():
                        self.schema(item, self.p["group"], where, "item_")
                        item_phase = self.phase(item, where, block_phase)
                        iid = item["id"]
                        self.require(isinstance(iid, str) and ATOM_ID.fullmatch(iid) and iid not in self.enum_ids,
                                     where, "invalid/duplicate enumeration id")
                        self.enum_ids.add(iid)
                        inner = self.each(item.get("each", []), bound, evidence, where, block["consumers"])
                        when = self.predicates(item["when"], inner, evidence, where)
                        result = deepcopy(item)
                        enclosing_each = [*block_each, *item.get("each", [])]
                        result["prelude"] = self.sequence(item["prelude"], iid, inner, evidence, where, [*guards, *when], item_phase, enclosing_each)
                        result["atoms"] = self.sequence(item["atoms"], iid, inner, evidence, where, [*guards, *when], item_phase, enclosing_each)
                        return result
                    result = self.attempt(where, compile_item)
                    if result is not None:
                        output["items"].append(result)
                compiled[name] = output
            self.attempt(name, compile_block)
        self.compiled["ENUMERATIONS"] = compiled

    def condition(self, value, records, evidence, where, *, enumeration=False):
        if enumeration:
            return self.predicates(value, records, evidence, where)
        return super().condition(value, records, evidence, where)

    @staticmethod
    def block_atoms(block):
        return [a for seq in [block["prelude"], *(s for item in block["items"]
                for s in (item["prelude"], item["atoms"]))] for a in seq]

    def phase_migration(self):
        """Check declared IDs/locations; this does not certify runtime execution."""
        migration = self.d["PHASE_MIGRATION"]
        self.keys(migration, {"groups", "ta1", "data_phase", "status", "derived_fields"}, set(), "PHASE_MIGRATION")
        self.phase(migration, "PHASE_MIGRATION")
        groups = migration["groups"]
        self.require(isinstance(groups, dict) and set(groups) == set(self.d["ENUMERATIONS"]),
                     "PHASE_MIGRATION", "group migration denominator mismatch")
        a1_atoms = {a["id"]: a for atoms in self.relations.values() for a in atoms}

        def location(target, where):
            if target in self.relations:
                self.require(any(a["phase"] == "runtime" for a in self.relations[target]), where,
                             f"runtime location has only test atoms: {target}")
            elif target in a1_atoms:
                self.require(a1_atoms[target]["phase"] == "runtime", where, f"runtime location is test: {target}")
            else:
                self.require(isinstance(target, str) and "." in target, where, f"unknown runtime location: {target}")
                root, name = target.split(".", 1)
                self.require(root in {"ENUMERATIONS", "ENUMERATION_SOURCES", "DERIVATIONS"}
                             and name in self.d.get(root, {}), where, f"unknown runtime location: {target}")
                if root == "ENUMERATIONS":
                    self.require(any(a["phase"] == "runtime" for a in self.block_atoms(self.compiled[root][name])),
                                 where, f"runtime location has only test atoms: {target}")

        for name, group in groups.items():
            def unit():
                self.schema(group, self.p["phase"]["migration_map_schema"], name, "group_")
                direct = [a for a in self.block_atoms(self.compiled["ENUMERATIONS"][name]) if a["id"] not in self.origins]
                for phase in self.p["phase"]["values"]:
                    expected = {a["id"] for a in direct if a["phase"] == phase}
                    self.names(group[phase + "_atoms"], expected, name, empty=True)
                    self.require(set(group[phase + "_atoms"]) == expected, name, f"{phase} migration atom denominator mismatch")
                self.require(isinstance(group["obligation"], str) and bool(group["obligation"])
                             and isinstance(group["source"], str) and bool(group["source"]), name, "missing migration reason/source")
                self.names(group["runtime_rows"], set(group["runtime_rows"]), name)
                for target in group["runtime_rows"]:
                    location(target, name)
            self.attempt(name, unit)
        self.require(isinstance(migration["ta1"], list), "PHASE_MIGRATION", "ta1 migration must be an array")
        seen = set()
        for entry in migration["ta1"]:
            where = entry.get("id", "PHASE_MIGRATION") if isinstance(entry, dict) else "PHASE_MIGRATION"
            def unit():
                self.schema(entry, self.p["phase"]["ta1_migration_schema"], where)
                aid = entry["id"]
                self.require(aid in a1_atoms and aid not in seen, where, "unknown/duplicate migrated T-A1 atom")
                seen.add(aid)
                self.require(entry["destination"] == a1_atoms[aid]["phase"] == "test", where, "migration destination differs from atom phase")
                self.require(isinstance(entry["reason"], str) and bool(entry["reason"]), where, "missing migration reason")
                self.names(entry["runtime_locations"], set(entry["runtime_locations"]), where)
                for target in entry["runtime_locations"]:
                    location(target, where)
            self.attempt(where, unit)
        self.attempt("PHASE_MIGRATION", lambda: self.require(seen == {a for a, v in a1_atoms.items() if v["phase"] == "test"},
                     "PHASE_MIGRATION", "test T-A1 migration denominator mismatch"))
        for names, targets in migration["derived_fields"].items():
            def unit():
                self.require(set(names.split("/")) <= set(self.d["DERIVATIONS"]), "PHASE_MIGRATION", "unknown migrated derived field")
                self.names(targets, set(targets), "PHASE_MIGRATION")
                for target in targets:
                    location(target, "PHASE_MIGRATION")
            self.attempt("PHASE_MIGRATION", unit)

    def primary_declarations(self):
        # These are declared JSON data, not operands or new evaluation modes.
        # Only explicitly self-declared schemas and cross-references are checked.
        for name in self.p["declaration_sections"]:
            if name == "PHASE_MIGRATION":
                continue
            def unit():
                value = self.d[name]
                self.require(isinstance(value, dict) and value.get("phase") == "runtime", name,
                             "primary declaration must be runtime data")
                if name == "REFERENCE_OBLIGATION_PROTOCOL":
                    self.require(isinstance(value.get("required"), list) and value.get("additional_keys") is False
                                 and set(value["required"]) == set(value["fields"]), name, "reference obligation field/schema mismatch")
                    for example in value["examples"]:
                        self.require(example["rule"] in self.refs and pointer(example["path"]), name, "unknown direct reference example")
                elif name == "CONTRACT_STRUCTURE_BINDINGS":
                    StructureGrammar(self, value).validate()
                elif name == "PERMISSION_BINDINGS" and "notation" in value:
                    self.permission_bindings(value)
            self.attempt(name, unit)

    def permission_bindings(self, declaration):
        """PB locations/checks are declaration data, not executable A1 atoms."""
        for index, binding in enumerate(declaration["bindings"]):
            where = f"PERMISSION_BINDINGS.bindings/{index}"
            self.locations.setdefault(where, self.locations.get("PERMISSION_BINDINGS", 1))
            records = set(binding["bind"]) | {record for s in self.d["SCOPES"].values() for record in s["records"]}
            pending = binding["pending_bindings"]
            def walk(value, where=where):
                if isinstance(value, dict):
                    if "literal" in value:
                        self.keys(value, {"literal"}, {"source"}, where)
                        return  # literal JSON is never reinterpreted as a PB location/check.
                    if "record" in value:
                        self.require(value["record"] in records, where, "unbound permission record")
                        if "pointer" in value:
                            self.keys(value, {"record", "pointer"}, set(), where)
                            path = value["pointer"]
                            self.require(isinstance(path, str) and (path == "" or pointer(path)), where, "invalid permission Pointer")
                            holes = re.findall(r"\{([^{}]*)\}", path)
                            self.require(set(holes) <= {"p", "t", "o", "r"}
                                         and not re.search(r"[{}]", re.sub(r"\{[ptor]\}", "", path)),
                                         where, "unknown permission occurrence placeholder")
                        else:
                            self.keys(value, {"record", "value"}, set(), where)
                            self.require(value["value"] == "authenticated Point", where, "unknown permission record value")
                    if "rel" in value:
                        self.keys(value, {"left", "rel", "right"}, {"note"}, where)
                        self.require(value["rel"] in self.unary | self.binary, where, "unknown permission relation")
                        self.require(value["rel"] in self.binary, where, "permission binary check has unary relation")
                    if "pending" in value:
                        references = value["pending"] if isinstance(value["pending"], list) else [value["pending"]]
                        self.names(references, set(pending), where, empty=True)
                    for key, child in value.items():
                        child_path = where + "/" + key
                        self.locations.setdefault(child_path, self.locations[where])
                        self.attempt(child_path, lambda child=child, child_path=child_path: walk(child, child_path))
                elif isinstance(value, list):
                    for i, child in enumerate(value):
                        child_path = where + "/" + str(i)
                        self.locations.setdefault(child_path, self.locations[where])
                        self.attempt(child_path, lambda child=child, child_path=child_path: walk(child, child_path))
            self.attempt(where, lambda: walk(binding))

    def validate(self):
        self.attempt("ATOM_PROTOCOL", self.protocol)
        if self.issues:
            raise AtomSyntaxError(self.issues)
        subjects, unatomized = {}, []
        for row in self.tables["T-A1"]:
            def compile_row():
                atoms = row["relation"]
                if atoms == PENDING:
                    return
                if isinstance(atoms, dict):
                    unatomized.append({"id": row["id"], "line": row["line"], "reason": "relation remains a legacy object"})
                    return
                self.require(isinstance(atoms, list) and bool(atoms), row["line"], "relation must be a nonempty atom array")
                subject, records = self.subject(row)
                subjects[row["id"]] = subject
                result = []
                for value in atoms:
                    where = value["id"] if isinstance(value, dict) and isinstance(value.get("id"), str) else row["id"]
                    atom = self.attempt(where, lambda: self.compile_atom(value, records, set(row["evidence"]), where))
                    if atom is not None:
                        result.append(atom)
                row["relation"] = result
                if len(result) == len(atoms):
                    self.relations[row["id"]] = result
            self.attempt(row["line"], compile_row)
        self.attempt("declarations", self.declarations)
        records = {k for k, v in self.p["environment"].items() if isinstance(v, dict)}
        evidence = {"EW", "EH", "EA", "EI"}
        prelude = self.d.get("ENUMERATION_CALL_PRELUDE", [])
        call_atoms = []
        for atom in prelude:
            def compile_call():
                result = self.compile_atom(atom, records, evidence, "ENUMERATION_CALL_PRELUDE",
                                           phase_parent=(self.p["capture"].get("phase", "runtime"), None))
                self.require(not self.phased or result["phase"] == self.p["capture"]["phase"],
                             "ENUMERATION_CALL_PRELUDE", "call prelude must remain test-only")
                return result
            result = self.attempt("ENUMERATION_CALL_PRELUDE", compile_call)
            if result is not None:
                call_atoms.append(result)
        self.compiled["ENUMERATION_CALL_PRELUDE"] = call_atoms
        sources = self.d.get("COMPONENT_INSTANCE_SOURCES", {})
        expected = set(self.d.get("ENUMERATIONS", {}).get("DERIVED_FIELDS", {}).get("consumers", []))
        self.attempt("COMPONENT_INSTANCE_SOURCES", lambda: self.require(set(sources) == expected,
                     "COMPONENT_INSTANCE_SOURCES", "component source/consumer denominator mismatch"))
        for name, source in sources.items():
            def source_unit():
                self.schema(source, self.p["component_instances"], name)
                bound = self.each(source["each"], records, evidence, name, {name})
                self.predicates(source["when"], bound, evidence, name)
                self.require(isinstance(source["source"], str) and bool(source["source"]), name, "missing primary source description")
            self.attempt(name, source_unit)
        migration = self.d.get("ENUMERATION_ID_MAP", {})
        self.attempt("ENUMERATION_ID_MAP", lambda: self.require(set(migration) == self.enum_ids, "ENUMERATION_ID_MAP", "item ID migration denominator mismatch"))
        for name, entry in migration.items():
            def map_unit():
                self.schema(entry, self.p["migration_map"], name)
                block = self.compiled["ENUMERATIONS"].get(entry["block"], {})
                item = next((x for x in block.get("items", []) if x["id"] == name), None)
                self.require(item is not None, name, "unresolved migration item/block")
                expected_ids = [a["id"] for a in [*item["prelude"], *item["atoms"]]]
                self.require(entry["atoms"] == expected_ids, name, "migration atom IDs/order differ from complete expansion")
            self.attempt(name, map_unit)
        if self.phased:
            self.attempt("PHASE_MIGRATION", self.phase_migration)
            self.primary_declarations()
        # The existing table traversal checks are independent of enumeration compilation.
        traversal_data = {**self.data, "rule_declarations": {k: v for k, v in self.d.items() if k not in {
                              "ATOM_PROTOCOL", "ENUMERATION_CALL_PRELUDE", "COMPONENT_INSTANCE_SOURCES", "ENUMERATION_ID_MAP"}},
                          "tables": {**self.tables, "T-A1": []}}
        traversal = RuleGrammar(traversal_data, self.name)
        traversal.declarations = lambda: None
        traversal.atom_ids = self.atom_ids
        self.attempt("T-REF/T-G4", traversal.validate)
        if self.issues:
            raise AtomSyntaxError(self.issues)
        enum_atoms = [a for b in self.compiled["ENUMERATIONS"].values()
                      for seq in [b["prelude"], *(s for item in b["items"] for s in (item["prelude"], item["atoms"]))] for a in seq]
        phases = {}
        if self.phased:
            phases["atom_origins"] = self.origins
            for prefix, atoms in (("a1", [a for rows in self.relations.values() for a in rows]),
                                  ("enumeration", [*enum_atoms, *call_atoms])):
                for phase in self.p["phase"]["values"]:
                    selected = [a for a in atoms if a["phase"] == phase]
                    phases[prefix + "_" + phase + "_atom_count"] = len(selected)
                    phases[prefix + "_" + phase + "_coded_atoms"] = sum("code" in a for a in selected)
        return {**phases, "source_tables": self.source_tables, "tables": self.tables, "compiled_rule_declarations": self.compiled,
                "unatomized_a1": unatomized, "a1_subjects": subjects, "a1_relations": self.relations,
                "atom_count": sum(len(v) for v in self.relations.values()), "enumeration_count": len(self.compiled["ENUMERATIONS"]),
                "enumeration_item_count": len(self.enum_ids), "enumeration_direct_atom_count": self.direct_count + len(call_atoms),
                "enumeration_reused_atom_count": self.reused_count, "enumeration_call_prelude_atom_count": len(call_atoms),
                "enumeration_block_atom_count": len(enum_atoms),
                "enumeration_atom_count": len(enum_atoms) + len(call_atoms),
                "enumeration_coded_atoms": sum("code" in a for a in [*enum_atoms, *call_atoms])}


class StructureGrammar:
    """Parse CSB declaration nodes, not saved values or a runtime authenticator.

    The notation supplies primitive names and entry keys. The node productions
    implement its explicitly described syntax; unresolved meanings stay data.
    Recursive local/contract references are checked by identity, never unfolded.
    """

    def __init__(self, compiler, declaration):
        self.c, self.d = compiler, declaration
        self.structures = declaration.get("structures", {})
        self.pending = declaration.get("pending_declarations", {})
        self.contracts = set()
        self.root = "CONTRACT_STRUCTURE_BINDINGS"

    def where(self, path, anchor=None):
        self.c.locations.setdefault(path, self.c.locations.get(anchor, self.c.locations.get(self.root, 1)))
        return path

    def require(self, condition, path, reason):
        self.c.require(condition, self.where(path), reason)

    def contract(self, value, path):
        self.c.keys(value, {"name", "version"}, set(), path)
        self.require(all(isinstance(v, str) and bool(v) for v in value.values()), path, "contract requires exact string name/version")
        return value["name"], value["version"]

    def reference(self, node, path):
        if isinstance(node, dict) and set(node) == {"local"}:
            self.require(isinstance(node["local"], str) and node["local"] in self.structures, path, "unresolved local structure")
        elif isinstance(node, dict) and set(node) == {"contract"}:
            self.require(self.contract(node["contract"], path) in self.contracts, path, "unresolved versioned structure contract")
        else:
            self.require(False, path, "expected local/contract structure reference")

    def node(self, node, path, *, fragment=False):
        self.where(path)
        notation = self.d["structure_notation"]
        if isinstance(node, str):
            self.require(node in notation["primitives"], path, "unknown structure primitive")
            return
        if isinstance(node, dict) and ("local" in node or "contract" in node):
            self.reference(node, path)
            return
        productions = {
            "object": ({"fields", "additional_fields"}, set(), "object"),
            "object_fragment": ({"fields", "unlisted_fields"}, set(), "object_fragment"),
            "nullable": ({"value"}, set(), "nullable"),
            "array": ({"items"}, {"min_items", "unique", "collection", "canonical_order_pending", "canonical_order"}, "array"),
            "string_map": ({"values"}, set(), "string_map"),
            "tuple": ({"items"}, {"meaning"}, "tuple"),
            "enum": ({"values"}, set(), "enum_literal"),
            "literal": ({"value"}, set(), "enum_literal"),
            "string": (set(), {"min_length", "pattern"}, "string_integer"),
            "integer": (set(), {"minimum", "maximum"}, "string_integer"),
            "rational": (set(), {"minimum", "exclusive_minimum", "unit"}, "rational"),
            "semantic": ({"base", "meaning"}, {"unit"}, "semantic"),
            "tagged_union": ({"tag", "payload", "branches", "additional_fields"}, set(), "tagged_union"),
            "contract_value": ({"selector", "syntax", "usage"}, {"selector_base"}, "contract_value_args"),
            "contract_args": ({"selector", "syntax", "usage"}, {"selector_base", "reference_form"}, "contract_value_args"),
            "pending": ({"id", "known_structure"}, set(), "pending"),
            "selected_structure": ({"selector", "selector_base", "cases"}, {"fallback", "on_unmatched"}, "selected_structure"),
        }
        kind = node.get("kind") if isinstance(node, dict) else None
        self.require(isinstance(kind, str) and kind in productions, path, f"unknown structure node kind {kind!r}")
        required, optional, section = productions[kind]
        self.require(section in notation, path, f"structure syntax is not declared: {section}")
        self.c.keys(node, {"kind", *required}, optional | {"checks"}, path)
        children = []
        if "checks" in node:
            self.require("checks" in notation and isinstance(node["checks"], list), path, "invalid structure checks")
            for check in node["checks"]:
                self.c.keys(check, {"kind", "rule", "source"}, set(), path)
                self.require(check["kind"] in self.d["shape_of_reading"]["kind_mapping"]
                             and isinstance(check["rule"], str) and bool(check["rule"]), path, "unknown structure check kind/rule")
        if kind in {"object", "object_fragment"}:
            self.require(isinstance(node["fields"], dict), path, "fields must be an object")
            if kind == "object":
                self.require(node["additional_fields"] is False, path, "object must reject additional fields")
            else:
                self.require(fragment and isinstance(node["unlisted_fields"], str), path, "object_fragment is only allowed in pending.known_structure")
            children = [(f"fields/{k}", v) for k, v in node["fields"].items()]
        elif kind == "nullable":
            children = [("value", node["value"])]
        elif kind == "array":
            children = [("items", node["items"])]
            if "min_items" in node:
                self.require(type(node["min_items"]) is int and node["min_items"] >= 0, path, "invalid array min_items")
            if "unique" in node:
                self.require(type(node["unique"]) is bool, path, "unique must be boolean")
            if "collection" in node:
                self.require(node["collection"] == "set", path, "unknown array collection")
            if "canonical_order_pending" in node:
                self.require(node.get("collection") == "set" and node["canonical_order_pending"] in self.pending,
                             path, "unresolved canonical_order_pending")
            if "canonical_order" in node:
                name = node["canonical_order"]
                self.require("canonical_order" in notation and isinstance(name, str)
                             and name in self.d.get("canonical_comparators", {}), path, "undeclared canonical comparator")
                self.require("canonical_order_pending" not in node, path, "canonical order cannot be both declared and pending")
        elif kind == "string_map":
            children = [("values", node["values"])]
        elif kind == "tuple":
            self.require(isinstance(node["items"], list), path, "tuple items must be an array")
            children = [(f"items/{i}", v) for i, v in enumerate(node["items"])]
        elif kind == "enum":
            values = node["values"]
            self.require(isinstance(values, list) and bool(values), path, "enum must be nonempty")
            encoded = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in values]
            self.require(len(encoded) == len(set(encoded)), path, "duplicate enum value")
        elif kind == "string":
            if "min_length" in node:
                self.require(type(node["min_length"]) is int and node["min_length"] >= 0, path, "invalid string min_length")
            if "pattern" in node:
                self.require(isinstance(node["pattern"], str), path, "pattern must be a string")
                try:
                    re.compile(node["pattern"])
                except re.error as exc:
                    self.require(False, path, f"invalid string pattern: {exc}")
        elif kind == "integer":
            self.require(all(type(node[k]) is int for k in ("minimum", "maximum") if k in node), path, "integer bounds exclude bool")
            self.require(not {"minimum", "maximum"} <= set(node) or node["minimum"] <= node["maximum"], path, "reversed integer bounds")
        elif kind == "rational":
            if "minimum" in node:
                v = node["minimum"]
                self.require(isinstance(v, list) and len(v) == 2 and all(type(x) is int for x in v)
                             and v[1] > 0 and math.gcd(*v) == 1, path, "invalid rational minimum")
            if "exclusive_minimum" in node:
                self.require("minimum" in node and type(node["exclusive_minimum"]) is bool, path, "invalid rational exclusive_minimum")
        elif kind == "semantic":
            self.require(isinstance(node["meaning"], str) and bool(node["meaning"]), path, "empty semantic meaning")
            children = [("base", node["base"])]
        elif kind == "tagged_union":
            self.require(all(isinstance(node[k], str) and bool(node[k]) for k in ("tag", "payload"))
                         and node["tag"] != node["payload"] and node["additional_fields"] is False, path, "invalid tagged union envelope")
            self.require(isinstance(node["branches"], dict) and bool(node["branches"]), path, "empty tagged union branches")
            children = [(f"branches/{k}", v) for k, v in node["branches"].items()]
        elif kind in {"contract_value", "contract_args", "selected_structure"}:
            self.require(isinstance(node["selector"], str) and (node["selector"] == "" or pointer(node["selector"])), path, "invalid structure selector Pointer")
            allowed = {"container", "value"} if kind == "selected_structure" else {"container", "content"}
            self.require(node.get("selector_base", "container") in allowed, path, "unknown structure selector_base")
            if kind == "selected_structure":
                self.require(isinstance(node["cases"], dict) and bool(node["cases"]), path, "selected_structure requires cases")
                self.require(("fallback" in node) != ("on_unmatched" in node)
                             and node.get("on_unmatched", "shape") == "shape", path, "selected_structure requires one explicit unmatched policy")
                children = [(f"cases/{k}", v) for k, v in node["cases"].items()]
                if "fallback" in node:
                    children.append(("fallback", node["fallback"]))
            else:
                self.require(node["syntax"] == "JSON" and isinstance(node["usage"], str) and bool(node["usage"]), path, "invalid dynamic contract envelope/usage")
                if "reference_form" in node:
                    self.require(node["reference_form"] == "name_version_args" and node["selector"] == "", path, "invalid argument reference_form")
        elif kind == "pending":
            self.require(node["id"] in self.pending, path, "unresolved structure pending ID")
            children = [("known_structure", node["known_structure"])]
        if "unit" in node:
            self.require(isinstance(node["unit"], str) and bool(node["unit"]), path, "unit must be a declared string")
        for key, child in children:
            child_path = self.where(path + "/" + key, path)
            self.c.attempt(child_path, lambda child=child, child_path=child_path: self.node(child, child_path,
                           fragment=fragment or kind == "pending"))

    def coverage(self, expected):
        d, c, root = self.d, self.c, self.root
        if "record_coverage" not in d:  # v1.3.1 framework without transcribed entries.
            c.names(d["pending_record_contracts_from_T_REF"], expected, root, empty=True)
            self.require(set(d["pending_record_contracts_from_T_REF"]) == expected, root, "T-REF pending structure denominator mismatch")
            return
        c.names(d["record_contracts_from_T_REF"], expected, root, empty=True)
        self.require(set(d["record_contracts_from_T_REF"]) == expected, root, "T-REF seed denominator mismatch")
        declared = {name + "/" + version for name, version in self.contracts}
        records = expected
        if "record_contracts" in d:
            c.names(d["record_contracts"], declared, root, empty=True)
            c.names(d["additional_record_contracts"], declared, root, empty=True)
            records, additional = set(d["record_contracts"]), set(d["additional_record_contracts"])
            self.require(expected.isdisjoint(additional) and records == expected | additional,
                         root, "record inventory must be the disjoint union of T-REF seeds and declared additions")
            count = d["denominator"]["record_contract_count"]
            self.require(type(count) is int and count == len(records), root, "record contract count mismatch")
        self.require(records == set(d["record_coverage"]), root, "record structure coverage denominator mismatch")
        self.require(records <= declared, root, "record coverage has no structure entry")
        complete, partial = set(), set()
        for name, entry in d["record_coverage"].items():
            def unit():
                c.keys(entry, {"outer", "content", "pending_ids", "dynamic_contract_closure"}, set(), root)
                self.require(entry["outer"] == "transcribed" and entry["content"] in {"transcribed", "partial"}, root, f"unknown coverage status: {name}")
                c.names(entry["pending_ids"], set(self.pending), root, empty=True)
                self.require(bool(entry["pending_ids"]) == (entry["content"] == "partial"), root, f"pending/content status mismatch: {name}")
                self.require(entry["dynamic_contract_closure"] in {"required_by_usage", "none_in_content"}, root, "unknown dynamic contract closure")
                (complete if entry["content"] == "transcribed" else partial).add(name)
            c.attempt(root, unit)
        for key, names in (("content_transcribed_record_contracts_from_T_REF", complete), ("pending_record_contracts_from_T_REF", partial)):
            c.names(d[key], expected, root, empty=True)
            self.require(set(d[key]) == names & expected, root, f"{key} differs from T-REF seed coverage")
        if "record_contracts" in d:
            for key, names in (("content_transcribed_record_contracts", complete), ("pending_record_contracts", partial)):
                c.names(d[key], records, root, empty=True)
                self.require(set(d[key]) == names, root, f"{key} differs from complete record coverage")

    def comparators(self):
        """Check declared comparator descriptors; never execute their text."""
        comparators = self.d.get("canonical_comparators", {})
        self.require(isinstance(comparators, dict), self.root, "canonical_comparators must be an object")
        for name, comparator in comparators.items():
            path = self.where(f"{self.root}.canonical_comparators/{name}", "canonical_comparators")
            def unit():
                self.c.keys(comparator, {"order", "source"}, {"key", "key_paths", "json", "duplicates", "scope", "excluded"}, path)
                self.require(("key" in comparator) != ("key_paths" in comparator), path, "comparator requires one key definition")
                self.require(all(isinstance(comparator[k], str) and bool(comparator[k])
                             for k in ("order", "key", "json", "duplicates", "excluded") if k in comparator), path, "invalid comparator description")
                if "key_paths" in comparator:
                    paths = comparator["key_paths"]
                    self.require(isinstance(paths, list) and bool(paths)
                                 and all(isinstance(p, str) and (p == "" or pointer(p)) for p in paths)
                                 and len(paths) == len(set(paths)), path, "invalid comparator key Pointer list")
                if "scope" in comparator:
                    self.c.names(comparator["scope"], set(comparator["scope"]), path)
            self.c.attempt(path, unit)

    def validate(self):
        c, d, root = self.c, self.d, self.root
        self.require(isinstance(d["entries"], list), root, "entries must be an array")
        for i, entry in enumerate(d["entries"]):
            path = self.where(f"{root}.entries/{i}")
            def unit():
                c.schema(entry, d["entry_schema"], path)
                identity = self.contract(entry["contract"], path)
                self.require(identity not in self.contracts, path, "duplicate structure contract entry")
                self.contracts.add(identity)
            c.attempt(path, unit)
        expected = {row["contract"] for row in c.source_tables["T-REF"] if CONTRACT.fullmatch(row["contract"])}
        c.attempt(root, lambda: self.coverage(expected))
        if "structure_notation" not in d:
            return
        self.require(isinstance(d["structure_notation"]["primitives"], dict), root, "invalid primitive declaration")
        c.attempt(root, self.comparators)
        for name, value in self.structures.items():
            path = self.where(f"{root}.structures/{name}", name)
            def unit():
                c.keys(value, {"structure", "source"}, set(), path)
                self.node(value["structure"], path)
            c.attempt(path, unit)
        for i, entry in enumerate(d["entries"]):
            path = self.where(f"{root}.entries/{i}")
            c.attempt(path, lambda: self.node(entry["content_structure"], path))
            for reference in entry.get("nested_structures", []):
                c.attempt(path, lambda: self.reference(reference, path))
        seen = set()
        for i, binding in enumerate(d.get("argument_bindings", [])):
            path = self.where(f"{root}.argument_bindings/{i}")
            def unit():
                c.keys(binding, {"contract", "usage", "structure", "nested_structures", "source"}, set(), path)
                identity = (*self.contract(binding["contract"], path), binding["usage"])
                self.require(binding["usage"] == "args" and identity not in seen, path, "duplicate/invalid argument binding")
                seen.add(identity)
                self.node(binding["structure"], path)
                for reference in binding["nested_structures"]:
                    c.attempt(path, lambda: self.reference(reference, path))
            c.attempt(path, unit)
        outer = d.get("outer_structure", {})
        if "record" in outer:
            c.attempt(root, lambda: self.node(outer["record"], root))
        for name, constraints in outer.get("outer_constraints", {}).items():
            for key, node in constraints.get("fields", {}).items():
                path = self.where(f"{root}.outer_constraints/{name}/{key}")
                c.attempt(path, lambda: self.node(node, path))
        for field in d.get("q_star_structure_binding", {}).get("field_obligations", []):
            c.attempt(root, lambda: self.node(field["structure"], root))


def parse_paper(text: str, name: str = "<markdown>") -> dict:
    doc = blocks(text)
    rule_declarations, declaration_locations = read_rule_declarations(doc, name)
    versions = [b.text for b in doc if b.kind == "text" and b.text.startswith("- 版:")]
    schema, declaration_source = paper_declaration(doc, name)
    fallback = declaration_source != "紙の明示宣言"
    table_versions = [b.text for b in doc if b.kind == "text" and b.text.startswith("表の版:")]
    if not table_versions:
        table_versions = [b.text for b in doc if b.kind == "heading" and re.search(r"§6-11\..*\(v[0-9]+", b.text)]
    if len(versions) != 1 or len(table_versions) != 1:
        raise TableError(f"{name}: need one '- 版:' line and one table version (表の版:)")
    declared_types = {}
    for i, b in enumerate(doc):
        if b.kind == "heading" and b.text == "#### 列の型 (機械可読)":
            if i + 1 >= len(doc) or doc[i + 1].kind != "table" or doc[i + 1].rows[0][1] != ("表", "列", "型"):
                raise TableError(f"{name}:{b.line}: 列の型 requires 表/列/型 table")
            for line, cells in doc[i + 1].rows[1:]:
                if len(cells) != 3 or cells[0] not in schema or not valid_type(cells[2]) or (cells[0], cells[1]) in declared_types:
                    raise TableError(f"{name}:{line}: invalid/duplicate column type declaration")
                declared_types[cells[0], cells[1]] = cells[2]
    if fallback and declared_types:
        raise TableError(f"{name}: 列の型 requires explicit 表の一覧")
    tables, ids, used_types = {}, {}, set()
    for i, block in enumerate(doc):
        if block.kind != "heading":
            continue
        match = re.fullmatch(r"#### 表 (T-[A-Z0-9]+(?:-[A-Z0-9]+)*) \(機械可読\)", block.text)
        if not match:
            if block.text.startswith("#### 表 T-"):
                raise TableError(f"{name}:{block.line}: malformed machine table heading")
            continue
        table = match[1]
        if table not in schema or table in tables:
            raise TableError(f"{name}:{block.line}: unknown or duplicate table {table}")
        if i + 1 >= len(doc) or doc[i + 1].kind != "table":
            raise TableError(f"{name}:{block.line}: heading must be followed immediately by its table")
        source = doc[i + 1]
        if fallback:
            labels = source.rows[0][1]
            expected = FB_V1_COLUMNS[table]
            if table == "T-G6":
                # Optional in legacy papers, explicit and closed when present.
                expected = tuple(c for c in expected if c != "適用方式")
                actual = tuple(c for c in labels if c != "適用方式")
                valid = actual == expected and labels.count("適用方式") <= 1
            else:
                valid = labels == expected
            if not valid:
                raise TableError(f"{name}:{source.line}: {table}: unknown, missing or reordered columns")
            by_name = {c["name"]: c for c in schema[table]["columns"]}
            input_columns = [by_name[label] for label in labels]
        else:
            columns = []
            for label in source.rows[0][1]:
                typed = re.fullmatch(r"(.+)【([^【】]+)】", label)
                column, typ = typed.groups() if typed else (label, declared_types.get((table, label)))
                if (table, column) in declared_types:
                    used_types.add((table, column))
                    if typed and declared_types[table, column] != typ:
                        raise TableError(f"{name}:{source.line}: conflicting type for {column}")
                if not typ or not valid_type(typ):
                    raise TableError(f"{name}:{source.line}: unknown/untyped column {label}")
                key = "id" if typ == "ID" else "source" if typ == "紙の行" else column
                if key == "line" or (key in {"id", "source"} and typ not in {"ID", "紙の行"}) or any(c['key'] == key for c in columns):
                    raise TableError(f"{name}:{source.line}: duplicate/reserved column {column}")
                columns.append({"name": column, "key": key, "type": typ})
            if sum(c["type"] == "ID" for c in columns) != 1:
                raise TableError(f"{name}:{source.line}: need exactly one ID column")
            schema[table]["columns"] = columns
        rows = []
        for line, cells in source.rows[1:]:
            columns = input_columns if fallback else schema[table]["columns"]
            if len(cells) != len(columns):
                raise TableError(f"{name}:{line}: {table}: row width {len(cells)}")
            row = {"line": line}
            if fallback and table == "T-G6":
                row["application"] = None
            for col, cell in zip(columns, cells):
                try:
                    row[col["key"]] = (validate_cell(col["key"], cell, table) if fallback
                                       else typed_cell(col["type"], cell))
                except (ValueError, TypeError) as exc:
                    raise TableError(f"{name}:{line}: {table} {col['name']}: {exc}") from exc
            if row["id"] in ids:
                raise TableError(f"{name}:{line}: duplicate ID {row['id']} (first at {ids[row['id']]})")
            ids[row["id"]] = line
            rows.append(row)
        if not rows:
            raise TableError(f"{name}:{source.line}: empty table {table}")
        tables[table] = rows
    if set(tables) != set(schema):
        raise TableError(f"{name}: missing tables: {sorted(set(schema) - set(tables))}")
    if set(declared_types) != used_types:
        raise TableError(f"{name}: unused column declarations: {sorted(set(declared_types) - used_types)}")
    for table, definition in schema.items():
        for col in definition["columns"]:
            if col["type"].startswith("ID参照:"):
                target = col["type"][5:]
                if target not in tables:
                    raise TableError(f"{name}: unresolved target table {target}")
                target_ids = {r["id"] for r in tables[target]}
                for r in tables[table]:
                    if r[col["key"]] != "-" and r[col["key"]] not in target_ids:
                        raise TableError(f"{name}:{r['line']}: unresolved {target} ID {r[col['key']]}")
    if fallback:
        refs = {r["id"]: r for r in tables["T-REF"]}
        for row in tables["T-A2"]:
            target = row["expansion"]
            if target != "-" and any(row[k] != refs[target][k] for k in ("contract", "purpose", "field")):
                raise TableError(f"{name}:{row['line']}: expansion {target} has a different origin/field")
        def resolve(x, line):
            if isinstance(x, dict):
                v = x.get("via")
                if isinstance(v, str) and v.startswith("REF-") and v not in refs:
                    raise TableError(f"{name}:{line}: unresolved via {v}")
                for v in x.values():
                    resolve(v, line)
            elif isinstance(x, list):
                for v in x:
                    resolve(v, line)
        for row in tables["T-G4"]:
            resolve(row, row["line"])
    pending = [{"table": t, "id": r["id"], "line": r["line"],
                "columns": [k for k, v in r.items() if v == PENDING]}
               for t, rows in tables.items() for r in rows if PENDING in r.values()]
    result = {"paper_version": versions[0], "table_version": table_versions[0], "table_schema": schema,
            "declaration_source": declaration_source, "tables": tables, "pending": pending, "complete": not pending,
            "operation_aliases": operation_aliases(doc, tables, name) if fallback else [],
            "math_delegation": has_math_delegation(doc), "rule_declarations": rule_declarations,
            "declaration_locations": declaration_locations}
    if fallback:
        try:
            result.update(RuleGrammar(result, name).validate())
        except (TypeError, KeyError, AttributeError) as exc:
            raise TableError(f"{name}:{declaration_locations.get('root', 1)}: malformed rule declaration: {exc}") from exc
        result["complete"] &= not result["unatomized_a1"]
    return result


def has_math_delegation(doc):
    return any(b.kind == "text" and b.text.startswith(
        "- v1.1 の math_artifact は、本文の各最上位欄を E として sui.f.math_artifact/2 の verify_f_math_result") for b in doc)


def operation_aliases(doc, tables, name):
    """Read only the explicitly introduced old-name => T-G6 IDs code block."""
    aliases, seen = [], set()
    headers = [i for i, b in enumerate(doc) if b.kind == "text" and b.text.startswith("- 旧 G6 の操作名 → T-G6 の ID の対応")]
    if len(headers) > 1:
        raise TableError(f"{name}: duplicate G6 alias declaration")
    known = {r["id"] for r in tables["T-G6"]}
    for i in headers:
        if i + 1 >= len(doc) or doc[i + 1].kind != "code":
            raise TableError(f"{name}:{doc[i].line}: G6 aliases require an immediate code block")
        block = doc[i + 1]
        for offset, line in enumerate(block.text.splitlines(), 1):
            match = re.fullmatch(r"(.+?) => (G6-[A-Z0-9]+(?:-[A-Z0-9]+)*(?:,G6-[A-Z0-9]+(?:-[A-Z0-9]+)*)*)", line)
            if not match:
                raise TableError(f"{name}:{block.line + offset}: invalid G6 alias")
            old, ids = match[1], match[2].split(",")
            if old in seen or len(ids) != len(set(ids)) or not set(ids) <= known:
                raise TableError(f"{name}:{block.line + offset}: duplicate G6 alias or unresolved T-G6 ID")
            seen.add(old)
            aliases.append({"old": old, "ids": ids, "line": block.line + offset})
        if not aliases:
            raise TableError(f"{name}:{block.line}: empty G6 aliases")
    old_tables = [b for b in doc if b.kind == "table" and b.rows[0][1] == ("操作", "出発点")]
    if not old_tables and DERIVATION.exists():
        # 正本が本体の中 (決定 C) に移り、旧 G6 の操作の表は導出の紙 (§6-10) に残った: そちらと照合する
        old_tables = [b for b in blocks(DERIVATION.read_text(encoding="utf-8-sig"))
                      if b.kind == "table" and b.rows[0][1] == ("操作", "出発点")]
    if len(old_tables) > 1:
        raise TableError(f"{name}: ambiguous old G6 table")
    labels = {re.sub(r"\\([*])", r"\1", cells[0]) for b in old_tables for _, cells in b.rows[1:]}
    if seen - labels:
        raise TableError(f"{name}: G6 alias has no old operation: {sorted(seen - labels)}")
    direct = {r["operation"] for r in tables["T-G6"]}
    if labels - direct - seen:
        raise TableError(f"{name}: old G6 operations without mapping: {sorted(labels - direct - seen)}")
    return aliases


def read_paper(path: Path = PAPER) -> dict:
    try:
        return parse_paper(path.read_text(encoding="utf-8-sig"), str(path))
    except (OSError, UnicodeError) as exc:
        raise TableError(f"紙が無い、または読めない: {path}: {exc}") from exc


def semantic(data: dict) -> dict:
    # Locations and prose evidence are provenance, never rule identity/meaning.
    return {t: {r["id"]: {k: v for k, v in r.items() if k not in {"id", "line", "source"}}
                for r in rows} for t, rows in data["tables"].items()}


def generated_extras(data):
    if data.get("declaration_source") == "紙の明示宣言":
        return {}
    declarations = data.get("compiled_rule_declarations", data.get("rule_declarations", {}))
    relations, subjects = {}, {}
    for row in data["tables"]["T-A1"]:
        if isinstance(row["relation"], list):
            relations[row["id"]] = row["relation"]
            subject = row["subject"]
            subjects[row["id"]] = ({"scope": "requests", "records": ["Q*"]}
                                    if row["id"] == "A1-I-UNIQUE" and isinstance(subject, str) else subject)
    return {**declarations, **declarations.get("ENUMERATIONS", {}),
            **({"ATOM_ORIGINS": data["atom_origins"]} if "atom_origins" in data else {}),
            "A1_RELATIONS": relations, "A1_SUBJECTS": subjects,
            "RELATION_VOCABULARY": (declarations["ATOM_PROTOCOL"]["atom"]["unary"] + declarations["ATOM_PROTOCOL"]["atom"]["binary"]
                                    if "ATOM_PROTOCOL" in declarations else list(RELATION_VOCABULARY)),
            "EVIDENCE_COLLECTIONS": {k: list(v) for k, v in EVIDENCE_COLLECTIONS.items()}}


def a1_code_metadata(data):
    """Use the same T-A1 denominator as atom_count; never add a default code."""
    if data.get("declaration_source") == "紙の明示宣言":
        return {"coded_atoms": 0, "uncoded_mismatch_atoms": []}
    atoms = [atom for row in data["tables"].get("T-A1", []) if isinstance(row["relation"], list)
             for atom in row["relation"]]
    return {"coded_atoms": sum("code" in atom for atom in atoms),
            "uncoded_mismatch_atoms": [atom["id"] for atom in atoms
                                      if atom["on_fail"] == "不適合" and "code" not in atom]}


def frozen_expression(value):
    """Emit deeply immutable JSON using one standard-library import, no code."""
    if isinstance(value, dict):
        return "_MP({" + ", ".join(repr(k) + ": " + frozen_expression(v) for k, v in value.items()) + "})"
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(frozen_expression(v) for v in value) + ("," if len(value) == 1 else "") + ")"
    return repr(value)


def read_data_expression(node, mapping_proxy_imported):
    class Literals(ast.NodeTransformer):
        def visit_Call(self, call):
            if (not mapping_proxy_imported or not isinstance(call.func, ast.Name) or call.func.id != "_MP"
                    or len(call.args) != 1 or call.keywords or not isinstance(call.args[0], ast.Dict)):
                raise ValueError("only MappingProxyType(dict literal) is allowed")
            return self.visit(call.args[0])
    return ast.literal_eval(Literals().visit(node))


def json_structure(value):
    if isinstance(value, dict):
        return {k: json_structure(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_structure(v) for v in value]
    return value


def generate(data: dict, output: Path = OUTPUT) -> None:
    metadata = {k: data[k] for k in ("paper_version", "table_version", "complete", "pending")}
    metadata.update(table_schema=data["table_schema"], declaration_source=data["declaration_source"],
                    operation_aliases=data.get("operation_aliases", []))
    extras = generated_extras(data)
    metadata.update(derivation_names=sorted(data.get("rule_declarations", {}).get("DERIVATIONS", {})),
                    effect_names=sorted(data.get("rule_declarations", {}).get("EFFECTS", {})),
                    atom_count=data.get("atom_count", 0), unatomized_a1=data.get("unatomized_a1", []),
                    generated_names=sorted(extras), completeness_scope="table syntax and atomization only; not structural coverage or runtime evaluation")
    metadata.update(generator_version=VERSION, generated_at=datetime.now(timezone.utc).isoformat())
    metadata.update(a1_code_metadata(data))
    metadata.update({k: v for k, v in data.items() if k.startswith(("enumeration_", "a1_")) and k.endswith(("count", "atoms"))})
    lines = ["# 生成物、手で直さない。tools/rule_tables.py generate で生成。",
             "# 元: " + data["paper_version"], "# 表の版: " + data["table_version"],
             "# 生成器の版: " + VERSION, "# 生成の日時: " + metadata["generated_at"],
             "# complete は表の未確定・未原子化の有無。構造網羅・実装接続・実行検査の完了印ではない。",
             "# 各定数は列名付きの行 tuple。参照義務を Point 集合へ射影しない。",
             "METADATA = " + repr(metadata), ""]
    if extras:
        lines.extend(("from types import MappingProxyType as _MP", ""))
    for table in data["tables"]:
        lines.append(table.replace("-", "_") + " = (")
        lines.extend("    " + repr(r) + "," for r in data["tables"][table])
        lines.extend((")", ""))
    lines.append("# 宣言型の索引。部分列挙は宣言済みの外側Point/Ref欄を除きunknown。値の文字列から型を推測しない。")
    lines.append("FIELD_TYPES = {")
    lines.extend("    " + repr(key) + ": " + repr(value) + ","
                 for key, value in sorted(field_types(data).items()))
    lines.extend(("}", ""))
    for name, value in extras.items():
        lines.extend((name + " = " + frozen_expression(value), ""))
    output.write_text("\n".join(lines), encoding="utf-8")


def load_generated(path: Path) -> dict:
    """Read literals/MappingProxy wrappers; never execute a module during diff."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values = {}
        mapping_proxy_imported = False
        for n in tree.body:
            if isinstance(n, ast.ImportFrom) and n.module == "types" and n.level == 0 and len(n.names) == 1 and n.names[0].name == "MappingProxyType" and n.names[0].asname == "_MP" and not mapping_proxy_imported:
                mapping_proxy_imported = True
                continue
            if not isinstance(n, ast.Assign) or len(n.targets) != 1 or not isinstance(n.targets[0], ast.Name):
                raise ValueError("expected data assignments only")
            key = n.targets[0].id
            if key in values:
                raise ValueError("duplicate assignment")
            values[key] = read_data_expression(n.value, mapping_proxy_imported)
        schema = values.get("METADATA", {}).get("table_schema", default_schema())
        expected = {"METADATA", *(t.replace("-", "_") for t in schema)}
        extra_names = values.get("METADATA", {}).get("generated_names", [])
        enum_names = set(values.get("ENUMERATIONS", {}))
        allowed = declaration_names(values) | GENERATOR_EXPORTS | enum_names | {"A1_RELATIONS", "A1_SUBJECTS", "RELATION_VOCABULARY", "EVIDENCE_COLLECTIONS"}
        if not isinstance(extra_names, list) or any(not isinstance(k, str) or k not in allowed for k in extra_names):
            raise ValueError("unknown generated declaration names")
        expected |= set(extra_names)
        if set(values) not in (expected, expected | {"FIELD_TYPES"}):
            raise ValueError("unexpected generated constants")
        types = values.get("FIELD_TYPES", {})
        if not isinstance(types, dict) or any(
                not isinstance(k, tuple) or len(k) != 2
                or not isinstance(k[0], str) or not CONTRACT.fullmatch(k[0])
                or not isinstance(k[1], str) or not (k[1] == "/" or pointer(k[1]))
                or not isinstance(v, str) or v not in FIELD_TYPE_NAMES for k, v in types.items()):
            raise ValueError("malformed FIELD_TYPES")
        tables = {}
        for t in schema:
            rows = values[t.replace("-", "_")]
            keys = {c["key"] for c in schema[t]["columns"]}
            if not isinstance(rows, tuple) or any(not isinstance(r, dict) or set(r) != {*keys, "line"} for r in rows):
                raise ValueError(f"malformed {t} rows")
            if len({r['id'] for r in rows}) != len(rows):
                raise ValueError(f"duplicate {t} IDs")
            tables[t] = rows
        extras = {k: json_structure(values[k]) for k in extra_names}
        for name, block in extras.get("ENUMERATIONS", {}).items():
            if extras.get(name) != block:
                raise ValueError(f"enumeration constant differs from ENUMERATIONS: {name}")
        return {"table_schema": schema, "tables": tables, **values["METADATA"], "field_types": types,
                "generated_extras": extras}
    except (OSError, ValueError, SyntaxError, TypeError, KeyError) as exc:
        raise TableError(f"generated data unreadable: {path}: {exc}") from exc


def diff(data: dict, current: dict) -> dict:
    old, new, changes = semantic(current), semantic(data), []
    for table in sorted(set(old) | set(new)):
        for rid in sorted(set(old.get(table, {})) | set(new.get(table, {}))):
            a, b = old.get(table, {}).get(rid), new.get(table, {}).get(rid)
            if a is None or b is None:
                changes.append({"table": table, "id": rid, "change": "added" if a is None else "removed", "old": a, "new": b})
            elif a != b:
                changes.append({"table": table, "id": rid, "change": "modified",
                                "fields": {k: {"old": a.get(k), "new": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}})
    provenance = []
    old_aliases = {r["old"]: r["ids"] for r in current.get("operation_aliases", [])}
    new_aliases = {r["old"]: r["ids"] for r in data.get("operation_aliases", [])}
    if old_aliases != new_aliases:
        changes.append({"table": "G6 aliases", "id": "operation_aliases", "change": "modified",
                        "fields": {"mapping": {"old": old_aliases, "new": new_aliases}}})
    schema_changes = []
    if current.get("table_schema", default_schema()) != data["table_schema"]:
        schema_changes.append({"old": current.get("table_schema", default_schema()), "new": data["table_schema"]})
    for key in ("paper_version", "table_version", "declaration_source"):
        if current.get(key) != data[key]:
            provenance.append({"field": key, "old": current.get(key), "new": data[key]})
    if current.get("generator_version") != VERSION:
        provenance.append({"field": "generator_version", "old": current.get("generator_version"), "new": VERSION})
    for key in ("complete", "pending"):
        if current.get(key) != data[key]:
            provenance.append({"field": key, "old": current.get(key), "new": data[key]})
    for key in {k for k in {*current, *data} if k.startswith(("enumeration_", "a1_")) and k.endswith(("count", "atoms"))}:
        if current.get(key) != data.get(key):
            provenance.append({"field": key, "old": current.get(key), "new": data.get(key)})
    for key, value in a1_code_metadata(data).items():
        if current.get(key) != value:
            provenance.append({"field": key, "old": current.get(key), "new": value})
    for table in data["tables"]:
        old_rows = {r["id"]: r for r in current["tables"].get(table, [])}
        for row in data["tables"][table]:
            if row["id"] in old_rows:
                a = old_rows[row["id"]]
                if (a["line"], a.get("source")) != (row["line"], row.get("source")):
                    provenance.append({"table": table, "id": row["id"], "field": "location/source"})
    before, after = current.get("field_types", {}), field_types(data)
    type_changes = [{"contract": key[0], "field": key[1],
                     "change": "added" if key not in before else "removed" if key not in after else "modified",
                     "old": before.get(key), "new": after.get(key)}
                    for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    old_extras, new_extras = current.get("generated_extras", {}), generated_extras(data)
    declaration_changes = [{"name": key, "change": "added" if key not in old_extras else "removed" if key not in new_extras else "modified",
                            "old": old_extras.get(key), "new": new_extras.get(key)}
                           for key in sorted(set(old_extras) | set(new_extras)) if old_extras.get(key) != new_extras.get(key)]
    return {"changes": changes, "schema_changes": schema_changes, "provenance_changes": provenance,
            "field_type_changes": type_changes, "declaration_changes": declaration_changes,
            "matches": not changes and not schema_changes and not provenance and not type_changes and not declaration_changes}


# Shape adapters bind existing DTOs to their body contracts. They describe
# storage structure only; they contain no reference roles or rule expectations.
# Supported saved-field reads may use explicit CSB types; unsupported AST
# expressions and unresolved versioned structures stay unknown.
DTO_BINDINGS = {
    "sui.fb.boot_declaration/1": ("fb", "BootDeclaration"),
    "sui.fb.received/1": ("fb", "Received"),
    "sui.fb.segment_report/1": ("fb", "SegmentReport"),
    "sui.fb.work_report/1": ("fb", "WorkFinished"),
    "sui.fb.draw_report/1": ("fb", "DrawReturned"),
    "sui.f.knowledge_origin/1": ("f", "KnowledgeOrigin"),
    "sui.f.content_acquired/1": ("f", "ContentAcquired"),
    "sui.f.clock_reading/1": ("f", "FClockReadingFact"),
    "sui.f.context_observed/1": ("f", "FContextObserved"),
    "sui.f.candidate_declaration/1": ("f", "FCandidateDeclaration"),
    "sui.f.draw_fact/1": ("f", "FDrawFact"),
    "sui.f.route_config/1": ("f_entry", "RouteApplied"),
    "sui.f.math_artifact/2": ("f", "FMathArtifactJSONV2"),
    "sui.f.model_source/1": ("f", "FModelSource"),
    "sui.clock.source/1": ("clock_contracts", "ClockSource"),
    "sui.fb.clock_notice/1": ("clock_contracts", "ClockSource"),
}

# Storage adapters select declarations/constructor expressions, never T-REF
# fields or roles. A missing/dynamic expression is reported, not filled in.
REQUEST_BINDINGS = {
    "sui.fb.work_requested/1": {"update": "UpdateArgs", "evaluate": "EvaluationArgs"},
    "sui.fb.evaluation_requested/1": {"prepare": "EvaluationPrepareArgs"},
    "sui.fb.draw_requested/1": {"draw": "DrawArgs"},
    "sui.fb.segment_requested/1": {"measurement": "SegmentArgs"},
    "sui.fb.candidate_request/1": {"generated_by": "CandidateArgs"},
}
DICT_BINDINGS = {
    "sui.fb.update_result/1": ("_fb_update", ("_r_step", "build")),
    "sui.fb.belief_adopted/1": ("_fb_update", ("_adopt_step", "build")),
    "sui.fb.monitor_span/1": ("_fb_update", ("_monitor_step", "build")),
    "sui.fb.finite_joint_count_law/1": ("_fb_update", ("_law_step", "build")),
    "sui.f.observation_plan/2": ("_fb_update", ("_reading_step", "build")),
    "sui.fb.segment_binding/1": ("_fb_bind", ("_plan",)),
    "sui.fb.prepared/1": ("_fb_think", ("_product_steps", "build_logical")),
    "sui.fb.evaluated/1": ("_fb_think", ("_product_steps", "build_logical")),
    "sui.fb.selection/1": ("_fb_think", ("_selection_step", "build")),
}
BODY_BINDINGS = {
    **{c: "Decided" for c in REQUEST_BINDINGS},
    **{c: "Observed" for c in ("sui.clock.source/1", "sui.fb.clock_notice/1", "sui.fb.boot_declaration/1",
        "sui.fb.segment_report/1", "sui.fb.work_report/1", "sui.fb.draw_report/1", "sui.fb.segment_binding/1",
        "sui.fb.monitor_span/1", "sui.fb.prepared/1", "sui.fb.evaluated/1", "sui.f.knowledge_origin/1",
        "sui.f.content_acquired/1", "sui.f.clock_reading/1", "sui.f.context_observed/1", "sui.f.draw_fact/1",
        "sui.f.route_config/1")},
    **{c: "Prediction" for c in ("sui.fb.update_result/1", "sui.fb.finite_joint_count_law/1",
        "sui.f.observation_plan/2", "sui.f.math_artifact/2", "sui.f.candidate_declaration/1", "sui.f.model_source/1")},
    "sui.fb.belief_adopted/1": "Decided", "sui.fb.selection/1": "Decided",
}


@dataclass(frozen=True)
class Shape:
    kind: str
    children: tuple = ()
    source: str = ""
    identity: str = ""
    field_type: str = "value"
    projection: str = ""  # supported AST read/spread, eligible for a declared storage type


ATOM = Shape("value")
FIELD_TYPE_NAMES = {"point", "ref", "value", "union", "unknown"}


class Structures:
    """AST and declared storage-shape reader; no implementation imports.

    Closed values named in §6-11 remain values. Unbound dynamic object/JSON
    fields stay opaque; supported reads use CSB types, never T-REF expectations.
    The wire adapter's isinstance returns and tag dictionaries are interpreted
    structurally; no production values, edges or closure functions are called.
    """

    CLOSED = {"str", "int", "float", "bool", "bytes", "Point", "Ref", "_Ref", "ContractRef", "_ContractRef",
              "RateBudget", "MeasurementInterval", "ClockReading", "Fraction", "_Fraction", "ImmutableJSON"}

    def __init__(self, root: Path = ROOT):
        self.nodes, self.aliases, self.trees, self.imports = {}, {}, {}, {}
        modules = ("fb", "fb_contracts", "_fb_wire", "f_contracts", "f", "clock", "clock_contracts",
                   "f_entry", "records", "ledger", "_fb_shape", "_fb_update", "_fb_bind", "_fb_think", "f_update2",
                   "_fb_boot", "_fb_core")
        for module in modules:
            path = root / "src/sui" / (module + ".py")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            self.trees[module] = tree
            for n in tree.body:
                if isinstance(n, ast.ClassDef):
                    self.nodes[module, n.name] = n
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
                    self.aliases[module, n.target.id] = n.value
                elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.BinOp):
                    self.aliases[module, n.targets[0].id] = n.value
                elif isinstance(n, ast.ImportFrom) and n.module in modules:
                    for alias in n.names:
                        self.imports[module, alias.asname or alias.name] = (n.module, alias.name)
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and n.module in modules:
                    for alias in n.names:
                        self.imports[module, alias.asname or alias.name] = (n.module, alias.name)
        self.slot_types = {}
        for n in self.trees["_fb_shape"].body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict):
                for k, v in zip(n.value.keys, n.value.values):
                    if isinstance(k, ast.Tuple) and isinstance(v, ast.Attribute):
                        self.slot_types[ast.literal_eval(k)] = v.attr
        self.handle_fields = {}
        self.contract_constants = {}
        for module in ("fb_contracts", "f_contracts"):
            for node in self.trees[module].body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and len(node.value.args) == 2:
                    args = node.value.args
                    if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                self.contract_constants.setdefault(target.id, set()).add(args[0].value + "/" + args[1].value)
        for node in ast.walk(self.trees["f_update2"]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_handle" and node.args and isinstance(node.args[0], ast.Name):
                for kw in node.keywords:
                    value = kw.value
                    if isinstance(value, ast.Call) and ast.unparse(value.func) == "_encode" and value.args:
                        value = value.args[0]
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                        target_module, target_name = self.resolve_name("f_update2", value.func.id)
                        if (target_module, target_name) in self.nodes:
                            self.handle_fields["f_update2", node.args[0].id, kw.arg] = (target_module, target_name)
        self.overrides, self.wire_locals = {}, {}
        for function in self.trees["_fb_wire"].body:
            if isinstance(function, ast.FunctionDef) and function.name in {"encode", "reading", "segment_item"}:
                for n in function.body:
                    if isinstance(n, ast.If) and isinstance(n.test, ast.Call) and isinstance(n.test.func, ast.Name) and n.test.func.id == "isinstance":
                        typ = n.test.args[1]
                        returns = [x for x in n.body if isinstance(x, ast.Return)]
                        if isinstance(typ, ast.Attribute) and returns:
                            self.overrides[function.name, typ.attr] = returns[0].value
                            self.wire_locals[function.name, typ.attr] = {
                                t.id: a.value for a in n.body if isinstance(a, ast.Assign)
                                and a.lineno < returns[0].lineno for t in a.targets if isinstance(t, ast.Name)}
        self.segment_tags, self.outcome_tags = {}, {}
        for n in self.trees["_fb_wire"].body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict):
                if any(isinstance(x, ast.Name) and x.id in {"_SEGMENT_TAGS", "_OUTCOME_TAGS"} for x in n.targets):
                    for key, value in zip(n.value.keys, n.value.values):
                        target = self.segment_tags if isinstance(value, ast.Constant) else self.outcome_tags
                        target[key.attr] = ast.literal_eval(value)
        self.f_tags = {}
        self.f_variants = {}
        for n in ast.walk(self.trees["f"]):
            if isinstance(n, ast.FunctionDef) and n.name == "_tag":
                for a in n.body:
                    if isinstance(a, ast.Assign) and isinstance(a.value, ast.Dict):
                        self.f_tags = {k.id: ast.literal_eval(v) for k, v in zip(a.value.keys, a.value.values)}
            if isinstance(n, ast.FunctionDef) and n.name == "_encode":
                for case in n.body:
                    if not (isinstance(case, ast.If) and isinstance(case.test, ast.Call)
                            and ast.unparse(case.test.func) == "isinstance" and len(case.test.args) == 2
                            and isinstance(case.test.args[1], ast.Name)):
                        continue
                    maps = [x.value for x in case.body if isinstance(x, ast.Assign) and isinstance(x.value, ast.Dict)
                            and all(isinstance(v, ast.Tuple) for v in x.value.values)]
                    returns = [x.value for x in case.body if isinstance(x, ast.Return) and isinstance(x.value, ast.Dict)]
                    if len(maps) == 1 and len(returns) == 1 and isinstance(returns[0].keys[0], ast.Constant):
                        self.f_variants[case.test.args[1].id] = (ast.literal_eval(returns[0].keys[0]), ast.literal_eval(maps[0]))

    def bind_declarations(self, data):
        """Bind explicit saved-contract types, independently of reference roles.

        This is a storage-type projection, not a proof that a builder produces a
        valid value. Unsupported expressions and unresolved selectors stay opaque.
        """
        self.structure_declaration = data.get("rule_declarations", {}).get("CONTRACT_STRUCTURE_BINDINGS", {})
        self.structure_entries = {x["contract"]["name"] + "/" + x["contract"]["version"]: x
                                  for x in self.structure_declaration.get("entries", [])}
        self.argument_entries = {x["contract"]["name"] + "/" + x["contract"]["version"]: x
                                 for x in self.structure_declaration.get("argument_bindings", [])}

    def declared_shape(self, node, actual=None, container=None, stack=(), location="content_structure"):
        """Read CSB nodes as types; never run checks, selectors or comparators."""
        source = "CONTRACT_STRUCTURE_BINDINGS." + location
        def unknown(reason):
            return Shape("opaque", source=source + ": " + reason)
        def read(value, part, value_actual=None, parent=None, trail=stack):
            return self.declared_shape(value, value_actual, parent, trail, location + "." + part)
        if isinstance(node, str):
            if node in {"Point", "Ref"}:
                return Shape("value", source=source, field_type="point" if node == "Point" else "ref")
            primitives = self.structure_declaration.get("structure_notation", {}).get("primitives", [])
            # A literal JSON primitive is explicitly free data. Dynamic
            # contract_args below still require their selected versioned type.
            return Shape("value", source=source) if node in primitives else unknown("unknown primitive " + node)
        if not isinstance(node, dict):
            return unknown("unsupported node")
        if "local" in node:
            name = node["local"]
            declaration = self.structure_declaration.get("structures", {}).get(name)
            if declaration is None or ("local", name) in stack:
                return unknown("unresolved/recursive local " + name)
            expanded = self.declared_shape(declaration["structure"], actual, container,
                                           stack + (("local", name),), "structures." + name + ".structure")
            if (name in self.CLOSED and (actual is None or actual.kind != "object")
                    and not any(f["kind"] == "opaque" for f in enumerate_fields(expanded))):
                return Shape("value", source=source)
            return expanded
        if "contract" in node:
            ref = node["contract"]
            name = ref["name"] + "/" + ref["version"]
            entry = getattr(self, "structure_entries", {}).get(name)
            if entry is None or ("contract", name) in stack:
                return unknown("unresolved/recursive contract " + name)
            return self.declared_shape(entry["content_structure"], actual, container,
                                       stack + (("contract", name),), "entries[" + name + "].content_structure")
        kind = node.get("kind")
        if kind == "pending":
            return unknown("pending " + node["id"])
        if kind in {"contract_args", "contract_value"}:
            selector = node.get("selector", "")
            selected = container
            if node.get("selector_base", "container") != "container":
                return unknown("unresolved selector base " + node["selector_base"])
            for part in selector.split("/")[1:] if selector else ():
                selected = dict(selected.children).get(part) if selected is not None and selected.kind == "object" else None
            name = selected.identity[9:] if selected is not None and selected.identity.startswith("contract:") else None
            entry = (getattr(self, "argument_entries", {}) if kind == "contract_args"
                     else getattr(self, "structure_entries", {})).get(name)
            if entry is None:
                return unknown("unresolved versioned " + kind + " selector " + selector)
            key = "structure" if kind == "contract_args" else "content_structure"
            marker = (kind, name)
            if marker in stack:
                return unknown("recursive " + kind + " " + name)
            return read(entry[key], "selected[" + name + "]", actual, container, stack + (marker,))
        if kind == "object":
            children = dict(actual.children) if actual is not None and actual.kind == "object" else {}
            return Shape("object", tuple((k, read(v, "fields." + k, children.get(k), actual))
                                         for k, v in node["fields"].items()), source)
        if kind in {"array", "string_map"}:
            part = "items" if kind == "array" else "values"
            child = actual.children[0] if actual is not None and actual.kind in {"array", "mapping"} else None
            return Shape("array" if kind == "array" else "mapping", (read(node[part], part, child),), source)
        if kind == "tuple":
            return Shape("indexed", tuple(read(v, "items." + str(i)) for i, v in enumerate(node["items"])), source)
        if kind == "nullable":
            return Shape("union", (Shape("null"), read(node["value"], "value", actual)), source)
        if kind == "semantic":
            return read(node["base"], "base", actual)
        if kind in {"integer", "string", "rational", "enum", "literal"}:
            value = node.get("value")
            identity = ("contract:" + value["name"] + "/" + value["version"]
                        if kind == "literal" and isinstance(value, dict) and set(value) == {"name", "version"} else "")
            return Shape("null" if kind == "literal" and value is None else "value", source=source, identity=identity)
        if kind == "tagged_union" and node.get("tag") == "kind" and node.get("payload") == "value":
            return Shape("tagged", tuple((tag, read(v, "branches." + tag)) for tag, v in node["branches"].items()), source)
        if kind == "selected_structure":
            selector = node["selector"].rsplit("/", 1)[-1]
            branches = [(selector, tag, read(v, "cases." + tag)) for tag, v in node["cases"].items()]
            if "fallback" in node:
                branches.append((selector, "<fallback>", read(node["fallback"], "fallback")))
            return Shape("wire_variants", tuple(branches), source)
        return unknown("unsupported node kind " + str(kind))

    def project_declared_type(self, actual, declared):
        """Connect supported AST reads/spreads at their exact saved-field slots.

        Literal AST keys are retained even when absent from CSB. We do not repair
        unknown calls, missing declarations, or a computed dict key by expectation.
        """
        if actual.kind == "opaque":
            return declared if actual.projection == "access" and declared.kind != "opaque" else actual
        if actual.kind == declared.kind == "object":
            expected, result = dict(declared.children), []
            explicit = {k for k, _ in actual.children if k != "*"}
            for key, value in actual.children:
                if key == "*" and value.projection == "spread":
                    result.extend((k, v) for k, v in declared.children if k not in explicit)
                else:
                    result.append((key, self.project_declared_type(value, expected[key]) if key in expected else value))
            return Shape("object", self.saved_keys(result), actual.source, actual.identity, actual.field_type)
        if actual.kind == declared.kind and actual.kind in {"array", "mapping"}:
            return Shape(actual.kind, (self.project_declared_type(actual.children[0], declared.children[0]),),
                         actual.source, actual.identity, actual.field_type)
        return actual

    @staticmethod
    def static_access(expr):
        if isinstance(expr, ast.Name):
            return True
        if isinstance(expr, ast.Attribute):
            return Structures.static_access(expr.value)
        return (isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant)
                and isinstance(expr.slice.value, str) and Structures.static_access(expr.value))

    @staticmethod
    def saved_keys(children):
        # A literal saved key has Python's last-assignment semantics. Unknown
        # spreads are independent obligations, never a duplicate '*' to erase.
        result = []
        for key, value in children:
            if key != "*":
                result = [(k, v) for k, v in result if k != key]
            result.append((key, value))
        return tuple(result)

    def locate(self, module, name):
        if (module, name) in self.nodes or (module, name) in self.aliases:
            return module
        if ("f", name) in self.nodes or ("f", name) in self.aliases:
            return "f"
        return module

    def resolve_name(self, module, name):
        if (module, name) in getattr(self, "imports", {}):
            return self.imports[module, name]
        return self.locate(module, name), name

    def fields(self, module, name):
        n = self.nodes[module, name]
        return {x.target.id: x.annotation for x in n.body if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name)}

    def annotation(self, node, module, stack=()):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = {"_fb": "fb", "_f": "f"}.get(node.value.id)
            if owner:
                return self.annotation(ast.Name(id=node.attr), owner, stack)
        if isinstance(node, ast.Constant):
            return Shape("null") if node.value is None else self.annotation(ast.parse(node.value, mode="eval").body, module, stack)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            parts = self.annotation(node.left, module, stack), self.annotation(node.right, module, stack)
            return Shape("union", tuple(c for p in parts for c in (p.children if p.kind == "union" else (p,))))
        if isinstance(node, ast.Subscript):
            name = ast.unparse(node.value)
            args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            if name in {"_Literal", "Literal"}:
                return Shape("literal", tuple(ast.literal_eval(x) for x in args))
            if name in {"tuple", "list", "set", "frozenset"}:
                if name == "tuple" and len(args) > 1 and not (isinstance(args[-1], ast.Constant) and args[-1].value is Ellipsis):
                    return Shape("indexed", tuple(self.annotation(a, module, stack) for a in args))
                return Shape("array", (self.annotation(args[0], module, stack),))
            if name in {"dict", "_Mapping", "Mapping"}:
                if isinstance(args[0], ast.Subscript) or (isinstance(args[0], ast.Name) and args[0].id in {"int", "float", "bool", "Ref", "_Ref", "ContractRef", "_ContractRef"}):
                    # f._encode writes non-string-key mappings as key/value
                    # arrays, not objects with invented string keys.
                    return Shape("array", (Shape("object", (("key", self.annotation(args[0], module, stack)),
                                                             ("value", self.annotation(args[-1], module, stack)))),))
                if not isinstance(args[0], ast.Name) or args[0].id not in {"str", "Point"}:
                    return Shape("opaque", source=f"{module}: unresolved mapping key wire type {ast.unparse(args[0])}")
                return Shape("mapping", (self.annotation(args[-1], module, stack),))
            return Shape("opaque", source=f"{module}: {ast.unparse(node)}")
        if not isinstance(node, ast.Name):
            return Shape("opaque", source=f"{module}: {ast.unparse(node)}")
        name = node.id
        if name in self.CLOSED:
            return Shape("value", field_type="point" if name == "Point" else
                         "ref" if name in {"Ref", "_Ref"} else "value")
        if name in {"object", "Any"}:
            return Shape("opaque", source=f"{module}: {name}")
        module, name = self.resolve_name(module, name)
        if name in self.CLOSED:
            return self.annotation(ast.Name(id=name), module, stack)
        if (module, name) in self.aliases:
            if (module, name) in stack:
                return Shape("opaque", source=f"recursive {module}.{name}")
            if module == "fb" and name in {"ReadingEvidence", "SegmentItem", "WorkOutcome", "DrawOutcome"}:
                return self.tagged(name, stack)
            return self.annotation(self.aliases[module, name], module, stack + ((module, name),))
        return self.dto(module, name, stack)

    def dto(self, module, name, stack=(), raw=False, field_types=None):
        if (module, name) not in self.nodes or (module, name) in stack:
            return Shape("opaque", source=f"unknown/recursive {module}.{name}")
        fields = {**self.fields(module, name), **(field_types or {})}
        new_stack = stack + ((module, name),)
        n = self.nodes[module, name]
        source = f"src/sui/{module}.py:{n.lineno}"
        identity = f"{module}.{name}"
        if module == "f" and not raw and name in getattr(self, "f_variants", {}):
            selector, variants = self.f_variants[name]
            return Shape("wire_variants", tuple((selector, tag, Shape("object", tuple(
                [(selector, ATOM)] + [(k, self.annotation(fields[k], module, new_stack)) for k in keys]), source))
                for tag, keys in variants.items()), source, identity)
        if module == "fb" and not raw and ("encode", name) in self.overrides:
            shape = self.wire(self.overrides["encode", name], module, fields, new_stack,
                              getattr(self, "wire_locals", {}).get(("encode", name), {}))
            return Shape(shape.kind, shape.children, source, identity, shape.field_type)
        result = []
        for k, v in fields.items():
            shape = self.annotation(v, module, new_stack)
            handle_type = getattr(self, "handle_fields", {}).get((module, name, k))
            if handle_type:
                shape = self.dto(*handle_type, stack=new_stack)
            slot_type = getattr(self, "slot_types", {}).get((name, k))
            if slot_type:
                shape = self.specialize_slot(shape, self.dto("fb", slot_type, new_stack))
            # f._encode:2710 wraps unions containing Unavailable in kind/value.
            def union_types(expr):
                if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
                    return union_types(expr.left) + union_types(expr.right)
                return [expr]
            parts = union_types(v)
            named_parts = {x.id for x in parts if isinstance(x, ast.Name)}
            tagged_union = ("Unavailable" in named_parts or {"At", "When"} <= named_parts
                            or {"Selected", "NoDecision"} <= named_parts)
            if module in {"f", "f_entry"} and tagged_union:
                branches = []
                for x in parts:
                    if not isinstance(x, ast.Name):
                        shape = Shape("opaque", source=f"unsupported f wire union {ast.unparse(v)}")
                        break
                    tag = self.f_tags.get(x.id, "available")
                    if name == "MeasurementFrame" and k == "value" and x.id != "Unavailable":
                        tag = "value"  # explicit wire case f.py:2708-2709
                    branches.append((tag, self.annotation(x, module, new_stack)))
                else:
                    shape = Shape("tagged", tuple(branches))
            result.append((k, shape))
        if not result:
            if any("Enum" in ast.unparse(b) for b in n.bases):
                return Shape("value", source=source)
            return Shape("opaque", source=f"{source}: no data fields / factory or protocol")
        return Shape("object", tuple(result), source, identity)

    def specialize_slot(self, shape, value):
        if shape.kind == "object":
            fields = dict(shape.children)
            if set(fields) == {"slot", "declaration"}:
                declaration = dict(fields["declaration"].children)
                declaration["value"] = value
                fields["declaration"] = Shape("object", tuple(declaration.items()))
                return Shape("object", tuple(fields.items()), shape.source)
            return Shape("object", tuple((k, self.specialize_slot(v, value)) for k, v in shape.children), shape.source)
        if shape.kind in {"union", "array"}:
            return Shape(shape.kind, tuple(self.specialize_slot(v, value) for v in shape.children), shape.source)
        return shape

    def function(self, module, names):
        body = self.trees[module].body
        for name in names:
            found = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
            if len(found) != 1:
                raise TableError(f"src/sui/{module}.py: cannot locate structural function {'.'.join(names)}")
            node = found[0]
            body = node.body
        return node

    def expression(self, expr, module, env, stack=()):
        """Read explicit constructor shape. Unknown dynamic values stay opaque."""
        source = f"src/sui/{module}.py:{expr.lineno}"
        constraint = env.get(ast.unparse(expr))
        if isinstance(constraint, Shape):
            return constraint
        if isinstance(expr, ast.Dict):
            children = []
            for k, v in zip(expr.keys, expr.values):
                if k is None:
                    spread = self.expression(v, module, env, stack)
                    if spread.kind == "object":
                        children.extend(spread.children)
                    else:
                        children.append(("*", Shape("opaque", source=source + ": dynamic ** " + ast.unparse(v),
                                                    projection="spread" if self.static_access(v) else "")))
                else:
                    if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                        return Shape("opaque", source=source + ": dynamic/non-string dictionary key " + ast.unparse(k))
                    children.append((ast.literal_eval(k), self.expression(v, module, env, stack)))
            return Shape("object", self.saved_keys(children), source)
        if isinstance(expr, ast.Constant):
            return Shape("null" if expr.value is None else "value", source=source)
        if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            parts = [self.expression(v, module, env, stack) for v in expr.elts if not isinstance(v, ast.Starred)]
            return Shape("array", (Shape("union", tuple(parts)) if parts else ATOM,), source)
        if isinstance(expr, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            local = dict(env)
            for gen in expr.generators:
                shape = self.expression(gen.iter, module, local, stack)
                if isinstance(gen.target, ast.Name) and shape.kind in {"array", "mapping"}:
                    local[gen.target.id] = shape.children[0]
            return Shape("array", (self.expression(expr.elt, module, local, stack),), source)
        if isinstance(expr, ast.Subscript):
            owner = self.expression(expr.value, module, env, stack)
            if isinstance(expr.slice, ast.Constant):
                key = expr.slice.value
                if owner.kind == "object" and key in dict(owner.children):
                    return dict(owner.children)[key]
                if owner.kind == "indexed" and isinstance(key, int) and key < len(owner.children):
                    return owner.children[key]
            if owner.kind in {"array", "mapping"}:
                return owner.children[0]
        if isinstance(expr, ast.Name) and expr.id in env and expr.id not in stack:
            if isinstance(env[expr.id], Shape):
                return env[expr.id]
            if isinstance(env[expr.id], tuple):
                values = tuple(self.expression(v, module, env, stack + (expr.id,)) for v in env[expr.id])
                return values[0] if len(values) == 1 else Shape("union", values, source)
            return self.expression(env[expr.id], module, env, stack + (expr.id,))
        if isinstance(expr, ast.Attribute):
            if isinstance(expr.value, ast.Name) and expr.value.id in {"_c", "_fc"} and expr.attr in self.contract_constants:
                contracts = self.contract_constants[expr.attr]
                return Shape("value", identity="contract:" + next(iter(contracts)) if len(contracts) == 1 else "")
            owner = self.expression(expr.value, module, env, stack)
            if owner.kind == "object" and expr.attr in dict(owner.children):
                return dict(owner.children)[expr.attr]
        if isinstance(expr, ast.Call):
            fun = ast.unparse(expr.func)
            if fun in {"_encode", "_f._encode", "_f.f_to_json", "_Payload.json"}:
                return self.expression(expr.args[0], module, env, stack)
            if isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Name) and expr.func.value.id in {"_fb", "_f"}:
                owner = "fb" if expr.func.value.id == "_fb" else "f"
                if (owner, expr.func.attr) in self.nodes:
                    return self.dto(owner, expr.func.attr)
            if fun in {"sorted", "tuple", "list", "frozenset"}:
                inner = self.expression(expr.args[0], module, env, stack) if expr.args else Shape("array", (ATOM,))
                return inner if inner.kind == "array" else Shape("array", (Shape("opaque", source=source + ": dynamic elements: " + ast.unparse(expr)),))
            if isinstance(expr.func, ast.Name):
                owner, name = getattr(self, "imports", {}).get((module, fun), (module, fun))
                for n in getattr(self, "trees", {}).get(owner, ast.Module(body=[])).body:
                    if isinstance(n, ast.FunctionDef) and n.name == name and n.returns is not None:
                        return self.annotation(n.returns, owner)
        if isinstance(expr, ast.IfExp):
            return Shape("union", (self.expression(expr.body, module, env, stack), self.expression(expr.orelse, module, env, stack)), source)
        return Shape("opaque", source=source + ": " + ast.unparse(expr),
                     projection="access" if isinstance(expr, (ast.Attribute, ast.Subscript)) and self.static_access(expr) else "")

    def scalar_constraints(self, function, env):
        """Propagate ledger.record's declared cid:str requirement backwards.

        Only explicit arguments, assignments and collection elements are used.
        This is a constructor precondition, not evidence from a rule table.
        Unknown calls/dict lookups retain their expression when unconstrained.
        """
        record = next(n for n in self.nodes["ledger", "Ledger"].body
                      if isinstance(n, ast.FunctionDef) and n.name == "record")
        arg = next(a for a in record.args.args if a.arg == "cid")
        required = self.annotation(arg.annotation, "ledger")
        # cid:str closes a scalar's structure, but does not declare Point/Ref.
        required = Shape(required.kind, required.children, required.source,
                         required.identity, "unknown")
        generators = [g for n in ast.walk(function) if isinstance(n, (ast.GeneratorExp, ast.ListComp, ast.SetComp)) for g in n.generators]
        active = set()
        def constrain(expr, elements=False):
            if isinstance(expr, ast.Constant) and expr.value is None:
                return  # never erase a constructor's explicit null alternative
            if isinstance(expr, ast.IfExp):
                constrain(expr.body, elements)
                constrain(expr.orelse, elements)
                return
            key = ast.unparse(expr)
            if (key, elements) in active:
                return
            active.add((key, elements))
            previous = env.get(key)
            if isinstance(expr, ast.Name):
                if previous is not None and not isinstance(previous, Shape):
                    for v in previous if isinstance(previous, tuple) else (previous,):
                        constrain(v, elements)
                for gen in generators:
                    if isinstance(gen.target, ast.Name) and gen.target.id == expr.id:
                        constrain(gen.iter, True)
            if elements:
                if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
                    for v in expr.elts:
                        constrain(v.value if isinstance(v, ast.Starred) else v, isinstance(v, ast.Starred))
                elif isinstance(expr, ast.BinOp):
                    constrain(expr.left, True)
                    constrain(expr.right, True)
                elif isinstance(expr, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
                    constrain(expr.elt)
                elif isinstance(expr, ast.Call) and ast.unparse(expr.func) in {"sorted", "tuple", "list", "set", "frozenset"} and expr.args:
                    constrain(expr.args[0], True)
                elif isinstance(expr, ast.IfExp):
                    constrain(expr.body, True)
                    constrain(expr.orelse, True)
            if not (isinstance(expr, ast.Name) and previous is not None and not isinstance(previous, Shape)):
                env[key] = Shape("array", (required,)) if elements else required
        for n in ast.walk(function):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and ast.unparse(n.func.value) in {"ledger", "state.ledger"} and n.func.attr == "record" and n.args:
                constrain(n.args[0])
            if isinstance(n, ast.Call) and ast.unparse(n.func) == "_front" and len(n.args) == 2:
                # _fb_boot._front -> _events -> ledger.entry(cid: str).
                # Follow the actual helper, not its name alone.
                front = self.function("_fb_boot", ("_front",))
                events = self.function("_fb_boot", ("_events",))
                if (any(isinstance(c, ast.Call) and ast.unparse(c.func) == "_events" for c in ast.walk(front))
                        and any(isinstance(c, ast.Call) and ast.unparse(c.func) == "ledger.entry" for c in ast.walk(events))):
                    constrain(n.args[1], True)
        return env

    def dictionary_body(self, contract):
        module, names = DICT_BINDINGS[contract]
        function = self.function(module, names)
        calls = [n for n in ast.walk(function) if isinstance(n, ast.Call) and ast.unparse(n.func) in {"_Observed", "_Decided", "_Prediction"}]
        expected = {k for k, values in self.contract_constants.items() if contract in values}
        candidates = []
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            ref = kw.get("contract")
            if isinstance(ref, ast.Attribute) and ref.attr in expected or (isinstance(ref, ast.Name) and ref.id == "contract"):
                candidates.append((call, kw.get("content")))
        if len(candidates) != 1:
            return Shape("opaque", source=f"src/sui/{module}.py:{function.lineno}: ambiguous contract constructor")
        call, payload = candidates[0]
        env = {}
        def bind(target, value):
            if isinstance(target, ast.Name):
                env[target.id] = (*env.get(target.id, ()), value)
            elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
                for t, v in zip(target.elts, value.elts):
                    bind(t, v)
        enclosing = self.function(module, names[:1])
        # Enclosing factory assignments are lexical inputs to nested builders.
        assignments = [n for n in enclosing.body if isinstance(n, ast.Assign)] if len(names) > 1 else []
        assignments += [n for n in ast.walk(function) if isinstance(n, ast.Assign)]
        for n in sorted(assignments, key=lambda x: getattr(x, "lineno", 0)):
            if getattr(n, "lineno", call.lineno) >= call.lineno:
                continue
            if isinstance(n, ast.Assign):
                for target in n.targets:
                    bind(target, n.value)
        if contract == "sui.fb.update_result/1":
            # _fb_update._issued requires IssuedUpdate before _r_step; its
            # factory's _handle(...result=_encode(FiniteUpdateResult(...)))
            # supplies the result type, not an expectation from T-REF.
            env["issued"] = self.dto("f_update2", "IssuedUpdate")
        self.scalar_constraints(function, env)
        expr = payload.args[0] if isinstance(payload, ast.Call) and ast.unparse(payload.func) == "_Payload.json" else None
        if isinstance(expr, ast.Name) and expr.id in env:
            # The assignment reaching this particular contract constructor;
            # never take the Stale sibling's dictionary as BeliefAdopted.
            choices = env[expr.id]
            expr = choices[-1] if isinstance(choices, tuple) else choices
        if expr is None:
            return Shape("opaque", source=f"src/sui/{module}.py:{function.lineno}: content expression not located")
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            return self.dictionary_call(expr, module, env, names, contract)
        return self.expression(expr, module, env)

    def dictionary_call(self, call, module, caller_env, names, contract):
        """Resolve a lexical helper returning a literal dict; never execute it.

        Only straight-line helpers with one return are interpreted. Module
        functions cannot capture caller locals; sibling helpers capture their
        enclosing factory, not the builder's locals.
        """
        frames = [(self.trees[module], ())]
        frames += [(self.function(module, names[:i]), names[:i])
                   for i in range(1, len(names) + 1)]
        found = None
        for scope, prefix in reversed(frames):
            definitions = [n for n in scope.body if isinstance(n, ast.FunctionDef)
                           and n.name == call.func.id]
            # A local binding shadows an outer function; do not guess through it.
            bound = any(isinstance(n, (ast.Assign, ast.AnnAssign)) and any(
                isinstance(t, ast.Name) and t.id == call.func.id
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))
                for n in scope.body)
            args = getattr(scope, "args", None)
            bound |= bool(args and call.func.id in {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)})
            if bound or len(definitions) > 1:
                break
            if definitions:
                found = definitions[0], scope, prefix
                break
        source = f"src/sui/{module}.py:{call.lineno}: unresolved dictionary helper {ast.unparse(call)}"
        if found is None:
            return Shape("opaque", source=source)
        helper, scope, prefix = found
        permitted = (ast.Assign, ast.AnnAssign, ast.Return, ast.FunctionDef)
        statements = [n for n in helper.body if not (isinstance(n, ast.Expr)
                      and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
        returns = [n for n in statements if isinstance(n, ast.Return)]
        if (len(returns) != 1 or statements[-1] is not returns[0]
                or not isinstance(returns[0].value, ast.Dict)
                or any(not isinstance(n, permitted) for n in statements)
                or helper.args.vararg or helper.args.kwarg
                or any(isinstance(a, ast.Starred) for a in call.args)
                or any(k.arg is None for k in call.keywords)):
            return Shape("opaque", source=source)
        # Build only the lexical environment visible at the definition.
        local = {}
        for frame, frame_names in frames:
            if len(frame_names) > len(prefix):
                break
            if isinstance(frame, ast.FunctionDef):
                for arg in (*frame.args.posonlyargs, *frame.args.args, *frame.args.kwonlyargs):
                    if arg.annotation:
                        local[arg.arg] = self.annotation(arg.annotation, module)
            for n in frame.body:
                if n.lineno >= helper.lineno:
                    break
                if isinstance(n, ast.Assign):
                    for target in n.targets:
                        if isinstance(target, ast.Name):
                            local[target.id] = n.value
        if scope is frames[-1][0]:
            local.update(caller_env)
        elif contract == "sui.fb.update_result/1" and prefix == ("_r_step",):
            local["issued"] = self.dto("f_update2", "IssuedUpdate")
        positional = [*helper.args.posonlyargs, *helper.args.args]
        params = {a.arg: a for a in (*positional, *helper.args.kwonlyargs)}
        supplied = dict(zip((a.arg for a in positional), call.args))
        if len(call.args) > len(positional):
            return Shape("opaque", source=source)
        for keyword in call.keywords:
            if keyword.arg not in params or keyword.arg in supplied or keyword.arg in {a.arg for a in helper.args.posonlyargs}:
                return Shape("opaque", source=source)
            supplied[keyword.arg] = keyword.value
        defaults = dict(zip((a.arg for a in positional[-len(helper.args.defaults):]), helper.args.defaults)) if helper.args.defaults else {}
        defaults.update({a.arg: v for a, v in zip(helper.args.kwonlyargs, helper.args.kw_defaults) if v is not None})
        for name, arg in params.items():
            if name not in supplied and name not in defaults:
                return Shape("opaque", source=source)
            value = (self.expression(supplied[name], module, caller_env) if name in supplied
                     else self.expression(defaults[name], module, local))
            local[name] = self.annotation(arg.annotation, module) if arg.annotation else value
        for n in statements[:-1]:
            if isinstance(n, (ast.Assign, ast.AnnAssign)):
                value = (self.annotation(n.annotation, module) if isinstance(n, ast.AnnAssign)
                         else self.expression(n.value, module, local))
                for target in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    if isinstance(target, ast.Name):
                        local[target.id] = value
        return self.expression(returns[0].value, module, local)

    def contract_body(self, contract, purpose):
        if contract in REQUEST_BINDINGS:
            typ = REQUEST_BINDINGS[contract].get(purpose)
            if typ is None:
                return Shape("opaque", source=f"unsupported Desc purpose binding: {contract} [{purpose}]")
            desc = self.dto("fb", "Desc", field_types={"args": ast.Name(id=typ)})
            return Shape("object", (("desc", desc),), desc.source)
        if contract in DTO_BINDINGS:
            actual = self.dto(*DTO_BINDINGS[contract])
            if contract == "sui.f.model_source/1":
                entry = getattr(self, "structure_entries", {}).get(contract)
                if entry is None:
                    return Shape("opaque", source=actual.source + ": model document requires CONTRACT_STRUCTURE_BINDINGS")
                declared = self.declared_shape(entry["content_structure"], actual,
                                               location="entries[" + contract + "].content_structure")
                # FModelSource.document is free JSON in the DTO; the explicit
                # versioned document adapter supplies its branches, including
                # the declared pending fallback. Never drop that fallback.
                if actual.kind != "object" or declared.kind != "object" or "document" not in dict(declared.children):
                    return Shape("opaque", source=actual.source + ": unresolved model document declaration")
                expected = dict(declared.children)
                return Shape("object", tuple((k, expected[k] if k == "document" else v)
                                             for k, v in actual.children), actual.source, actual.identity)
            return actual
        if contract in DICT_BINDINGS:
            actual = self.dictionary_body(contract)
            entry = getattr(self, "structure_entries", {}).get(contract)
            if entry is not None:
                declared = self.declared_shape(entry["content_structure"], actual,
                                               location="entries[" + contract + "].content_structure")
                return self.project_declared_type(actual, declared)
            return actual
        return Shape("opaque", source="unsupported contract-body binding")

    def outer_fields(self, contract):
        """Project only the paper's five outer paths to the body root.

        The actual header remains a separate namespace; no virtual content link
        or fabricated reference field is inserted into any stored DTO.
        """
        body_name = BODY_BINDINGS.get(contract)
        if not body_name:
            return []
        fields = self.fields("records", body_name)
        projected = {"inputs", "target", "about", "basis"}
        result = []
        for name in projected & fields.keys():
            result += enumerate_fields(self.annotation(fields[name], "records"), "/" + name)
        result += enumerate_fields(self.annotation(self.fields("ledger", "Entry")["parents"], "ledger"), "/parents")
        return [{**x, **({"field_type": OUTER_FIELD_TYPES[x["field"]]} if x["field"] in OUTER_FIELD_TYPES else {}),
                 "scope": "outer", "source": f"src/sui/records.py:{self.nodes['records',body_name].lineno}; src/sui/ledger.py:{self.nodes['ledger','Entry'].lineno}"} for x in result]

    def common_fields(self, contract):
        if contract not in BODY_BINDINGS:
            return []
        record = self.fields("records", "Record")
        fields = []
        for k, typ in record.items():
            if k != "body":
                fields += enumerate_fields(self.annotation(typ, "records"), "/header/" + k)
        fields += [{"field": "/header/body/type", "kind": "value"}]
        for k, typ in self.fields("records", BODY_BINDINGS[contract]).items():
            if k not in {"content", "inputs", "target", "about", "basis"}:
                fields += enumerate_fields(self.annotation(typ, "records"), "/header/body/" + k)
        fields += [{"field": "/header/seal", "kind": "value"}, {"field": "/entry/cid", "kind": "value"}]
        fields += enumerate_fields(self.dto("records", "Payload"), "/body/content")
        fields += [{"field": "/entry/header", "kind": "value"}]
        return [{**x, "scope": "common", "source": "src/sui/ledger.py:168; src/sui/records.py:309"} for x in fields]

    def wire_discriminator(self, expr, module, fields, stack, bindings):
        """Correlate a literal kind conditional with its tested DTO union.

        Only the actual isinstance(value.field, Type) / encode(value.field)
        pair is accepted. Other conditionals are not guessed from CSB tags.
        """
        values = {k.value: v for k, v in zip(expr.keys, expr.values) if isinstance(k, ast.Constant)}
        if set(values) != {"kind", "value"} or len(expr.keys) != 2:
            return None
        tag = values["kind"]
        if isinstance(tag, ast.Name):
            tag = bindings.get(tag.id)
        if not isinstance(tag, ast.IfExp):
            return None
        test, payload = tag.test, values["value"]
        if (not isinstance(test, ast.Call) or ast.unparse(test.func) != "isinstance"
                or len(test.args) != 2 or test.keywords or not isinstance(test.args[0], ast.Attribute)
                or not isinstance(test.args[0].value, ast.Name) or test.args[0].value.id != "value"
                or not isinstance(payload, ast.Call) or ast.unparse(payload.func) not in {"encode", "_f._encode"}
                or len(payload.args) != 1 or payload.keywords or ast.dump(payload.args[0]) != ast.dump(test.args[0])
                or not all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in (tag.body, tag.orelse))
                or tag.body.value == tag.orelse.value):
            return None
        typ = test.args[1]
        owner = module
        if isinstance(typ, ast.Attribute) and isinstance(typ.value, ast.Name) and typ.value.id in {"_fb", "_f"}:
            owner, name = ("fb" if typ.value.id == "_fb" else "f"), typ.attr
        elif isinstance(typ, ast.Name):
            owner, name = self.resolve_name(module, typ.id)
        else:
            return None
        def parts(node):
            return parts(node.left) + parts(node.right) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) else [node]
        annotation = fields.get(test.args[0].attr)
        alternatives = parts(annotation) if annotation is not None else []
        selected = [x for x in alternatives if isinstance(x, ast.Name) and self.resolve_name(module, x.id) == (owner, name)]
        remaining = [x for x in alternatives if x not in selected]
        if len(selected) != 1 or not remaining:
            return None
        shape = lambda xs: self.annotation(xs[0], module, stack) if len(xs) == 1 else Shape(
            "union", tuple(self.annotation(x, module, stack) for x in xs))
        return Shape("tagged", ((tag.body.value, shape(selected)), (tag.orelse.value, shape(remaining))))

    def wire(self, expr, module, fields, stack, bindings=None):
        bindings = bindings or {}
        if isinstance(expr, ast.Name) and expr.id == "value":
            return Shape("object", tuple((k, self.annotation(v, module, stack)) for k, v in fields.items()))
        if isinstance(expr, ast.Dict):
            if any(not isinstance(k, ast.Constant) or not isinstance(k.value, str) for k in expr.keys):
                return Shape("opaque", source="wire expression: dynamic dictionary keys/spread")
            tagged = self.wire_discriminator(expr, module, fields, stack, bindings)
            if tagged is not None:
                return tagged
            return Shape("object", tuple((ast.literal_eval(k), self.wire(v, module, fields, stack, bindings)) for k, v in zip(expr.keys, expr.values)))
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == "value":
            return self.annotation(fields[expr.attr], module, stack)
        if isinstance(expr, ast.Call):
            func = ast.unparse(expr.func)
            if func in {"reading", "segment_item"}:
                return self.tagged("ReadingEvidence" if func == "reading" else "SegmentItem", stack)
            if func in {"encode", "_f._encode"}:
                return self.wire(expr.args[0], module, fields, stack, bindings)
        if isinstance(expr, ast.ListComp) and isinstance(expr.elt, ast.Call) and ast.unparse(expr.elt.func) == "reading":
            return Shape("array", (self.tagged("ReadingEvidence", stack),))
        if isinstance(expr, ast.Constant):
            return ATOM
        return Shape("opaque", source=f"wire expression: {ast.unparse(expr)}")

    def tagged(self, name, stack):
        alias = self.aliases["fb", name]
        def types(n):
            if isinstance(n, ast.BinOp):
                return types(n.left) + types(n.right)
            return [n.id]
        branches = []
        for typ in types(alias):
            module = self.locate("fb", typ)
            fields = self.fields(module, typ)
            function = "reading" if name == "ReadingEvidence" else "segment_item"
            if name in {"WorkOutcome", "DrawOutcome"}:
                tag, attr = self.outcome_tags[typ]
                value = self.annotation(fields[attr], module, stack)
                branches.append((tag, value))
                continue
            expr = self.overrides.get((function, typ))
            if expr is not None:
                # Wrapper kind is supplied by a constant or Literal discriminator.
                values = dict(zip((ast.literal_eval(k) for k in expr.keys), expr.values))
                tag_expr = values["kind"]
                tags = (ast.literal_eval(tag_expr),) if isinstance(tag_expr, ast.Constant) else self.annotation(fields[tag_expr.attr], module, stack).children
                val = self.wire(values["value"], module, fields, stack)
            else:
                tags = (self.segment_tags[typ],)
                val = self.dto(module, typ, stack, raw=True)
            branches.extend((tag, val) for tag in tags)
        return Shape("tagged", tuple(branches))


def enumerate_fields(shape: Shape, path="") -> list[dict]:
    """Enumerate terminal value slots, collection slots, nullable containers and
    all explicit union branches. Containers are not hidden by a sample value.
    """
    if shape.kind == "object":
        if not shape.children:
            return [{"field": path or "/", "kind": "value", "field_type": "value"}]
        return [x for k, v in shape.children for x in enumerate_fields(v, path + "/" + k)]
    if shape.kind == "indexed":
        return [x for i, v in enumerate(shape.children) for x in enumerate_fields(v, path + "/" + str(i))]
    if shape.kind in {"array", "mapping"}:
        return enumerate_fields(shape.children[0], path + "/*")
    if shape.kind == "tagged":
        return [x for k, v in shape.children for x in
                ([{"field": path + "[kind=" + k + "]/kind", "kind": "wire_tag", "field_type": "value"}]
                 + enumerate_fields(v, path + "[kind=" + k + "]/value"))]
    if shape.kind == "wire_variants":
        return [dict(x, branches=[f"{selector}={tag}", *x.get("branches", [])])
                for selector, tag, v in shape.children
                for x in enumerate_fields(v, path + (f"[kind={tag}]" if selector == "kind" else ""))]
    if shape.kind == "null":
        return [{"field": path + "?", "kind": "nullable", "literal_null": True, "field_type": "value"}]
    if shape.kind == "union":
        nullable = any(p.kind == "null" for p in shape.children)
        result = ([{"field": path + "?", "kind": "nullable", "field_type": "union"}] if nullable else [])
        parts = [p for p in shape.children if p.kind != "null"]
        for i, p in enumerate(parts):
            if p.kind != "null":
                discriminator = dict(p.children).get("kind") if p.kind == "object" else None
                tags = discriminator.children if discriminator and discriminator.kind == "literal" and len(parts) > 1 else (None,)
                items = [item for tag in tags for item in enumerate_fields(p, path + (f"[kind={tag}]" if tag is not None else ""))]
                for item in items:
                    item = dict(item)
                    if nullable and item["field"] == path:
                        item["field"] += "?"
                        result[0]["nonnull_value"] = True
                    if len(parts) > 1:
                        item["branches"] = [p.identity or f"variant-{i}", *item.get("branches", [])]
                    existing = next((x for x in result if (x["field"], x.get("branches")) ==
                                     (item["field"], item.get("branches"))), None)
                    if existing is None:
                        result.append(item)
                    else:
                        existing["field_type"] = merge_field_type(existing["field_type"], item["field_type"])
        return result
    return [{"field": path or "/", "kind": shape.kind,
             "field_type": "unknown" if shape.kind == "opaque" else shape.field_type,
             **({"detail": shape.source} if shape.kind == "opaque" else {})}]


def merge_field_type(a, b):
    return "unknown" if "unknown" in {a, b} else a if a == b else "union"


def field_types(data, root=ROOT):
    """Use check's declaration denominator; partial interiors remain unknown.

    The explicit math delegation only waives completeness: opaque interiors
    retain type unknown. Generic papers have no structural semantic adapter.
    """
    if data.get("declaration_source") == "紙の明示宣言":
        return {}
    refs, result = data["tables"]["T-REF"], {}
    contracts = sorted({r[k] for rows in data["tables"].values() for r in rows
                        for k in ("contract", "target_contract") if k in r and r[k] != "-"})
    structures = Structures(root)
    if hasattr(structures, "bind_declarations"):
        structures.bind_declarations(data)
    for contract in contracts:
        purposes = sorted({r["purpose"] for r in refs if r["contract"] == contract}
                          | {r["target_purpose"] for r in refs if r["target_contract"] == contract
                             and r["target_purpose"] != "-" and r["role"] in {"U", "UE"}})
        local, partial, outer_types = {}, False, {}
        for purpose in purposes:
            shape = structures.contract_body(contract, purpose)
            fields = (enumerate_fields(shape) + structures.outer_fields(contract)
                      + structures.common_fields(contract))
            rows = [r for r in refs if r["contract"] == contract and r["purpose"] == purpose]
            for field in fields:
                path, typ = field["field"], field.get("field_type", "value")
                if field.get("scope") == "outer" and path in OUTER_FIELD_TYPES:
                    outer_types[path] = OUTER_FIELD_TYPES[path]
                local[path] = merge_field_type(local[path], typ) if path in local else typ
                if field["kind"] == "opaque":
                    delegated = (contract == "sui.f.math_artifact/2" and purpose in {"prepare", "evaluate"}
                                 and data.get("math_delegation", False) and field_covered(field,
                                     [r if r["role"] == "E" else {**r, "role": PENDING} for r in rows],
                                     branch_identifiers=False))
                    partial |= not delegated
        result.update({(contract, path): outer_types.get(path, "unknown" if partial else typ)
                       for path, typ in local.items()})
    return result


def field_covered(field: dict, rows: list[dict], *, branch_identifiers=True) -> bool:
    """Apply §6-11:3703/3705 without inventing reference obligations.

    The nearest declared field wins, including an unresolved child treatment.
    Value roles cover its descendants; U/UE only treat the declared field.
    A selected union branch also treats its discriminator, not sibling branches
    or payload fields. The switch permits a separate audit of that second rule.
    """
    p = field["field"]
    candidates = []
    for row in rows:
        q = row["field"]
        if not isinstance(q, str) or q == PENDING:
            continue
        base = q.removesuffix("?")
        if p == q or p == base or p.startswith(base + "/") or p.startswith(base + "[kind="):
            candidates.append(row)
    if candidates:
        specificity = max(len(r["field"].removesuffix("?")) for r in candidates)
        nearest = [r for r in candidates if len(r["field"].removesuffix("?")) == specificity]
        exact = [r for r in nearest if r["field"] == p or r["field"].removesuffix("?") == p]
        if exact:
            null_done = value_done = False
            for row in exact:
                if row["role"] == PENDING:
                    continue
                if field["kind"] != "nullable":
                    if isinstance(row.get("condition"), dict) and row["condition"].get("is_null") == p:
                        continue
                    return True
                condition = row.get("condition", True)
                base = p.removesuffix("?")
                null_done |= not (isinstance(condition, dict) and condition.get("nonnull") == base)
                value_done |= not (isinstance(condition, dict) and condition.get("is_null") == base)
            return null_done and (value_done or not field.get("nonnull_value"))
        if any(r["role"] in {"E", "leaf", "ignored", "unsupported"} for r in nearest):
            return True
    if branch_identifiers and re.fullmatch(r".+\[kind=[a-z][a-z0-9_]*\]/kind", p):
        branch = p.removesuffix("/kind")
        return any(isinstance(r["field"], str) and r["role"] != PENDING and
                   (r["field"] == branch or r["field"].startswith(branch + "/"))
                   for r in rows)
    return False


def operation_coverage(text: str, data: dict) -> dict:
    """Use exact labels or the paper's explicit ID correspondence; no inference."""
    doc = blocks(text)
    candidates = [b for b in doc if b.kind == "table" and b.rows[0][1] == ("操作", "出発点")]
    if not candidates and DERIVATION.exists():
        # 正本が本体の中 (決定 C) に移り、旧 G6 の操作の表は導出の紙 (§6-10) に残った
        candidates = [b for b in blocks(DERIVATION.read_text(encoding="utf-8-sig"))
                      if b.kind == "table" and b.rows[0][1] == ("操作", "出発点")]
    if len(candidates) != 1:
        raise TableError("need exactly one paper G6 操作/出発点 table")
    operations = []
    for line, cells in candidates[0].rows[1:]:
        if len(cells) != 2:
            raise TableError(f"line {line}: malformed G6 operation")
        label = re.sub(r"\\([*])", r"\1", cells[0])
        alias = next((a for a in data.get("operation_aliases", []) if a["old"] == label), None)
        matches = alias["ids"] if alias else [r["id"] for r in data["tables"]["T-G6"] if r["operation"] == label]
        if not matches:
            raise TableError(f"line {line}: old G6 operation without mapping: {label}")
        candidates = []
        for row in data["tables"]["T-G6"]:
            # Only Fb citations refer to this paper; trailing prose is not parsed.
            source = row["source"]
            if source.startswith("Fb:"):
                for part in source[3:].split(";"):
                    m = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", part)
                    if m and int(m[1]) <= line <= int(m[2] or m[1]):
                        candidates.append(row["id"])
                        break
        operations.append({"paper_line": line, "operation": label, "rule_ids": matches,
                           "mapping_line": alias["line"] if alias else None,
                           "citation_candidates_unverified": candidates})
    return {"paper_operations": operations, "missing": [x for x in operations if not x["rule_ids"]],
            "registered_operations": [{k: r[k] for k in ("id", "operation", "stage", "contract", "purpose", "application", "line")} for r in data["tables"]["T-G6"]],
             "method": "exact operation labels or explicit old-name => T-G6 IDs; numeric citations remain diagnostic only"}


def check(data: dict, text: str, root: Path = ROOT) -> dict:
    if data.get("declaration_source") == "紙の明示宣言":
        return {"profile": "宣言型の読取・ID参照検査", "ok": False, "syntax_ok": not data["pending"],
                "table_counts": {t: len(rows) for t, rows in data["tables"].items()},
                "table_schema": data["table_schema"], "pending": data["pending"],
                "structural_check": "not_run: this declaration has no contract/column semantic adapter profile; only syntax and typed ID references were checked"}
    grammar = RuleGrammar(data).validate()
    structures = Structures(root)
    if hasattr(structures, "bind_declarations"):
        structures.bind_declarations(data)
    refs = data["tables"]["T-REF"]
    contracts = sorted({r[k] for rows in data["tables"].values() for r in rows for k in ("contract", "target_contract") if k in r and r[k] != "-"})
    inventory, unavailable, unclassified, opaque, delegated = [], [], [], [], []
    math_delegation = has_math_delegation(blocks(text))
    for contract in contracts:
        purposes = sorted({r["purpose"] for r in refs if r["contract"] == contract}
                          | {r["target_purpose"] for r in refs if r["target_contract"] == contract
                             and r["target_purpose"] != "-" and r["role"] in {"U", "UE"}})
        all_fields, contract_opaque, contract_delegated = [], [], []
        module, name = DTO_BINDINGS.get(contract, ("", "constructor/Desc"))
        entry = {"contract": contract, "dto": module + "." + name, "purposes": purposes}
        inventory.append(entry)
        for purpose in purposes:
            if hasattr(structures, "contract_body"):
                shape = structures.contract_body(contract, purpose)
            else:
                shape = structures.dto(module, name)
            fields = enumerate_fields(shape)
            outer = structures.outer_fields(contract) if hasattr(structures, "outer_fields") else []
            common = structures.common_fields(contract) if hasattr(structures, "common_fields") else []
            entry["source"] = shape.source
            rows = [r for r in refs if r["contract"] == contract and r["purpose"] == purpose]
            for field in fields + outer + common:
                # A contract with multiple uses/args branches has a single
                # denominator of locations plus a separate use-by-use check.
                if field not in all_fields:
                    all_fields.append(field)
                item = {"contract": contract, "purpose": purpose, **field, "source": field.get("source", shape.source)}
                if field.get("scope") == "common":
                    auth_ids = {r["id"] for r in data["tables"]["T-A1"]}
                    item["auth_ids"] = [x for x in ("A1-IDENTITY", "A1-SHAPE") if x in auth_ids]
                    covered = len(item["auth_ids"]) == 2  # paper §6-11:3704, not a synthesized T-REF role
                else:
                    covered = field_covered(field, rows)
                if field["kind"] != "opaque" and not covered:
                    unclassified.append(item)
                if field["kind"] == "opaque":
                    delegate_e = (contract == "sui.f.math_artifact/2" and purpose in {"prepare", "evaluate"}
                                  and math_delegation and covered and field_covered(field,
                                      [r if r["role"] == "E" else {**r, "role": PENDING} for r in rows],
                                      branch_identifiers=False))
                    if delegate_e:
                        delegated.append(item)
                        contract_delegated.append(item)
                    else:
                        opaque.append(item)
                        contract_opaque.append(item)
        entry.update(field_count=len({x["field"] for x in all_fields}), branch_field_count=len(all_fields),
                     fields=all_fields, complete=not contract_opaque, delegated=bool(contract_delegated))
        if contract_opaque:
            unavailable.append({"contract": contract, "reason": "partial: unresolved AST expressions or declared pending/dynamic versioned structures prevent closed enumeration",
                                "fields": sorted({x["field"] for x in contract_opaque})})
    unclassified.extend({"contract": "T-A1", "purpose": "authentication", "field": row["id"] + ".relation",
                         "kind": "unatomized", "source": f"{PAPER}:{row['line']}", "reason": row["reason"]}
                        for row in grammar["unatomized_a1"])
    case_count = len(unclassified)
    grouped = {}
    for item in unclassified:
        key = item["contract"], item["purpose"], item["field"]
        case = {k: v for k, v in item.items() if k not in {"contract", "purpose", "field"}}
        if key not in grouped:
            grouped[key] = {**item, "branch_cases": []}
        if case not in grouped[key]["branch_cases"]:
            grouped[key]["branch_cases"].append(case)
    unclassified = list(grouped.values())
    operations = operation_coverage(text, data)
    return {"paper_version": data["paper_version"], "table_version": data["table_version"],
            "table_counts": {t: len(rows) for t, rows in data["tables"].items()},
             "enumeration_method": "AST DTOs, purpose-specific Desc args, _fb_shape slot value declarations, wire wrappers and their literal isinstance discriminators, lexical constructor assignments, typed helper returns, ledger cid preconditions, Record/Entry/header and projected outer paths. Supported static reads and dictionary spreads are projected to their exact saved-field CONTRACT_STRUCTURE_BINDINGS types; unknown calls/selectors remain opaque. Model documents follow declared version branches with pending fallbacks retained. Common metadata uses §6-11:3704. Only E-covered math_artifact prepare/evaluate interiors with the explicit v1.1 statement are delegated to verify_f_math_result; other dynamic/recursive interiors remain explicitly incomplete.",
            "contracts": inventory, "contract_count": len(inventory), "field_count": sum(c["field_count"] for c in inventory),
            "branch_field_count": sum(c["branch_field_count"] for c in inventory),
            "complete_contract_count": sum(c["complete"] for c in inventory),
             "fully_enumerated_contract_count": sum(c["complete"] and not c["delegated"] for c in inventory),
             "delegated_contract_count": sum(c["delegated"] for c in inventory),
             "delegated_fields": delegated,
            "unavailable_contracts": unavailable, "opaque_fields": opaque,
            "unclassified_count": len(unclassified), "unclassified": unclassified,
            "unclassified_case_count": case_count,
            "operations": operations, "a1_ids": [r["id"] for r in data["tables"]["T-A1"]],
            "pending": data["pending"],
            "atom_count": grammar["atom_count"], "unatomized_a1": grammar["unatomized_a1"],
            **a1_code_metadata(data),
            "enumeration_count": grammar["enumeration_count"], "enumeration_item_count": grammar["enumeration_item_count"],
            **{k: v for k, v in grammar.items() if k.startswith(("enumeration_", "a1_")) and k.endswith(("count", "atoms"))},
            "derivation_names": sorted(data.get("rule_declarations", {}).get("DERIVATIONS", {})),
            "effect_names": sorted(data.get("rule_declarations", {}).get("EFFECTS", {})),
            "ok": not (unclassified or unavailable or opaque or operations["missing"] or data["pending"])}


@dataclass
class SourceOwner:
    contract: str
    expression: str = ""


@dataclass
class SourceField:
    owner: SourceOwner
    field: str


class ImplementationReader:
    """Restricted AST inventory, never imports/runs the inspected implementation.

    It tracks literal paths, aliases and collection comprehensions. Unknown
    guards retain both syntactic branches; no runtime condition is certified.
    A dynamic body read acquires a contract only from an explicit rejecting
    contract guard. Everything else is exported as unreadable, not an absence.
    """

    def __init__(self, constants):
        self.constants = constants
        self.unknown = object()
        self.items, self.unreadable = [], []

    def problem(self, node):
        item = {"line": node.lineno, "expression": ast.unparse(node)}
        if item not in self.unreadable:
            self.unreadable.append(item)
        return self.unknown

    def values(self, value):
        if isinstance(value, SourceField):
            return [SourceField(value.owner, value.field + "/*")]
        return value if isinstance(value, (list, tuple)) else []

    def bind(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (list, tuple)):
            for t, v in zip(target.elts, value):
                self.bind(t, v, env)

    def value(self, n, env):
        u = self.unknown
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            return env.get(n.id, u)
        if isinstance(n, ast.Attribute):
            value = self.value(n.value, env)
            if isinstance(value, dict):
                return value.get(n.attr, u)
            if isinstance(value, SourceField):
                return SourceField(value.owner, value.field + "/" + n.attr)
            return u
        if isinstance(n, ast.Subscript):
            value, key = self.value(n.value, env), self.value(n.slice, env)
            if isinstance(value, SourceField) and isinstance(key, (str, int)):
                return SourceField(value.owner, value.field + "/" + str(key))
            if isinstance(value, dict) and isinstance(key, str):
                return value.get(key, u)
            return self.problem(n)
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            result = []
            for x in n.elts:
                result.extend(self.values(self.value(x.value, env)) if isinstance(x, ast.Starred) else [self.value(x, env)])
            return tuple(result) if isinstance(n, ast.Tuple) else result
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            contexts = [dict(env)]
            for gen in n.generators:
                expanded = []
                for local in contexts:
                    for element in self.values(self.value(gen.iter, local)):
                        child = dict(local)
                        self.bind(gen.target, element, child)
                        expanded.append(child)
                contexts = expanded
            return [self.value(n.elt, local) for local in contexts]
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.BitOr)):
            a, b = self.value(n.left, env), self.value(n.right, env)
            if isinstance(a, str) and isinstance(b, str) and isinstance(n.op, ast.Add):
                return a + b
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                return [*a, *b]
            return u
        if isinstance(n, ast.Call):
            name = ast.unparse(n.func)
            if name == "isinstance" and len(n.args) == 2 and env.get("__args_type__"):
                if isinstance(n.args[0], ast.Name) and n.args[0].id == "args" and isinstance(n.args[1], ast.Attribute):
                    return env["__args_type__"] == n.args[1].attr
            if name == "_c":
                return self.constants["_c"]
            if name in {"set", "frozenset", "tuple", "list", "sorted"}:
                return self.values(self.value(n.args[0], env)) if n.args else []
            if isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args:
                owner, key = self.value(n.func.value, env), self.value(n.args[0], env)
                if isinstance(owner, SourceField) and isinstance(key, str):
                    return SourceField(owner.owner, owner.field + "/" + key)
            if name == "body" and n.args:
                owner = SourceOwner("", ast.unparse(n))
                return (owner, SourceField(owner, ""), SourceField(owner, "/basis"), SourceField(owner, "/about"))
            return self.problem(n)
        if isinstance(n, ast.Compare) and len(n.ops) == 1:
            a, b = self.value(n.left, env), self.value(n.comparators[0], env)
            if isinstance(a, (SourceField, SourceOwner)) or isinstance(b, (SourceField, SourceOwner)) or a is u or b is u:
                return u
            if isinstance(n.ops[0], (ast.Eq, ast.Is)):
                return a == b
            if isinstance(n.ops[0], (ast.NotEq, ast.IsNot)):
                return a != b
            if isinstance(n.ops[0], (ast.In, ast.NotIn)) and isinstance(b, (list, tuple, str)):
                return (a in b) == isinstance(n.ops[0], ast.In)
            return u
        if isinstance(n, ast.BoolOp):
            values = [self.value(v, env) for v in n.values]
            if isinstance(n.op, ast.And):
                return False if any(v is False for v in values) else True if all(v is True for v in values) else u
            return True if any(v is True for v in values) else False if all(v is False for v in values) else u
        if isinstance(n, ast.IfExp):
            test = self.value(n.test, env)
            if test is True or test is False:
                return self.value(n.body if test else n.orelse, env)
            return [*self.values(self.value(n.body, env)), *self.values(self.value(n.orelse, env))]
        return self.problem(n)

    def emit(self, value, n, mode):
        def fields(v):
            if isinstance(v, SourceField):
                yield v
            elif isinstance(v, (list, tuple)):
                for item in v:
                    yield from fields(item)
        if mode == "edges":
            for pair in value if isinstance(value, list) else []:
                if isinstance(pair, tuple) and len(pair) == 2 and isinstance(pair[0], SourceField):
                    self.items.append((pair[0], pair[1], n.lineno, ast.unparse(n)))
        elif mode == "keys":
            for key in value if isinstance(value, list) else []:
                if isinstance(key, tuple) and key and isinstance(key[0], str):
                    for f in fields(key[1:]):
                        self.items.append((f, key[0], n.lineno, ast.unparse(n)))
        else:
            for f in fields(value):
                self.items.append((f, None, n.lineno, ast.unparse(n)))

    def statements(self, nodes, env, mode):
        for n in nodes:
            if isinstance(n, ast.Assign):
                value = self.value(n.value, env)
                for target in n.targets:
                    self.bind(target, value, env)
                    if isinstance(target, ast.Name) and target.id == "out":
                        self.emit(value, n, mode)
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id == "out":
                self.emit(self.value(n.value, env), n, mode)
            elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and ast.unparse(n.value.func.value) == "out":
                value = self.value(n.value.args[0], env) if n.value.args else []
                self.emit([value] if n.value.func.attr in {"add", "append"} else value, n, mode)
            elif isinstance(n, ast.If):
                # A rejecting contract guard fixes the type of a decoded body.
                if (isinstance(n.test, ast.Compare) and len(n.test.ops) == 1 and isinstance(n.test.ops[0], ast.NotEq)
                        and any(isinstance(x, ast.Raise) for x in n.body)):
                    left, right = self.value(n.test.left, env), self.value(n.test.comparators[0], env)
                    if isinstance(left, SourceOwner) and isinstance(right, str):
                        left.contract = right
                        continue
                test = self.value(n.test, env)
                if test is True or test is False:
                    if self.statements(n.body if test else n.orelse, env, mode):
                        return True
                else:
                    self.statements(n.body, dict(env), mode)
                    self.statements(n.orelse, dict(env), mode)
            elif isinstance(n, ast.For):
                for element in self.values(self.value(n.iter, env)):
                    child = dict(env)
                    self.bind(n.target, element, child)
                    self.statements(n.body, child, mode)
            elif isinstance(n, ast.Return):
                if n.value is not None and not (isinstance(n.value, ast.Name) and n.value.id == "out"):
                    self.emit(self.value(n.value, env), n, mode)
                return True
            elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                continue  # a docstring is not an unreadable implementation item
            elif not isinstance(n, (ast.Raise, ast.Import, ast.ImportFrom, ast.Pass)):
                self.problem(n)
        return False

    def read(self, function, contract, purpose, mode, args_type=None):
        owner = SourceOwner(contract)
        env = {**self.constants, "_LEAF": "leaf", "contract": contract, "use": purpose,
               "content": SourceField(owner, ""), "basis": SourceField(owner, "/basis"),
               "about": SourceField(owner, "/about"), "desc": SourceField(owner, "/desc"),
               "adopted": SourceField(SourceOwner("", "argument adopted"), "")}
        env["__args_type__"] = args_type
        self.statements(function.body, env, mode)
        result = []
        for f, target, line, expression in self.items:
            item = {"contract": f.owner.contract, "purpose": purpose if f.owner.contract == contract else "読めない", "field": f.field or "/",
                    "target_use_or_key": target if isinstance(target, (str, type(None))) else "読めない",
                    "line": line, "expression": expression, "owner_expression": f.owner.expression}
            if item not in result:
                result.append(item)
        return {"items": result, "unreadable": self.unreadable}


def implementation_inventory(data: dict, root: Path = ROOT) -> dict:
    """Mechanical source inventory for the requested replacement map."""
    trees = {m: ast.parse((root / "src/sui" / (m + ".py")).read_text(encoding="utf-8"))
             for m in ("fb_contracts", "f_contracts", "_fb_uses", "f_update2", "_fb_think", "_fb_update")}
    constants = {}
    for alias, module in (("_c", "fb_contracts"), ("_fc", "f_contracts")):
        values = {}
        for n in trees[module].body:
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and len(n.value.args) == 2:
                if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in n.value.args):
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            values[t.id] = "/".join(a.value for a in n.value.args)
        constants[alias] = values
    output = {}
    for function, mode, table in (("_edges", "edges", "T-REF"), ("_keys", "keys", "T-G4")):
        node = next(n for n in trees["_fb_uses"].body if isinstance(n, ast.FunctionDef) and n.name == function)
        rows = data["tables"][table]
        pairs = {(r["contract"], r["purpose"]) for r in rows}
        source_contracts = {constants[n.value.id][n.attr] for n in ast.walk(node)
                            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                            and n.value.id in constants and n.attr in constants[n.value.id]}
        source_uses = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "use":
                for value in n.comparators:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        source_uses.add(value.value)
                    elif isinstance(value, (ast.Tuple, ast.List)):
                        source_uses.update(x.value for x in value.elts if isinstance(x, ast.Constant) and isinstance(x.value, str))
        pairs |= {(c, u) for c in source_contracts for u in source_uses}
        pairs = sorted(pairs)
        result, unreadable = [], []
        for contract, purpose in pairs:
            got = ImplementationReader(constants).read(node, contract, purpose, mode)
            result.extend(got["items"])
            unreadable.extend({**x, "contract": contract, "purpose": purpose} for x in got["unreadable"])
        output[function] = {"items": result, "unreadable": unreadable, "line": node.lineno}
    for name in ("local_refs", "history_refs"):
        node = next(n for n in trees["f_update2"].body if isinstance(n, ast.FunctionDef) and n.name == name)
        output[name] = ImplementationReader(constants).read(node, "sui.fb.work_requested/1" if name == "local_refs" else "",
                                                           "update" if name == "local_refs" else "History", "fields")
        output[name]["line"] = node.lineno
    # Stable A1 IDs are absent from authenticate: keep its calls/literal fields
    # as source inventory and do not assign prose obligations by similarity.
    replay = next(n for n in trees["f_update2"].body if isinstance(n, ast.ClassDef) and n.name == "_Replay")
    auth = next(n for n in replay.body if isinstance(n, ast.FunctionDef) and n.name == "authenticate")
    output["authenticate"] = {"line": auth.lineno,
        "guards": [{"line": n.lineno, "expression": ast.unparse(n.test)} for n in ast.walk(auth) if isinstance(n, ast.If)],
        "issues": [{"line": n.lineno, "expression": ast.unparse(n)} for n in ast.walk(auth)
                   if isinstance(n, ast.Call) and ast.unparse(n.func) == "_Issue"],
        "calls": [{"line": n.lineno, "expression": ast.unparse(n)} for n in ast.walk(auth)
                  if isinstance(n, ast.Call) and (ast.unparse(n.func).startswith("self.") or ast.unparse(n.func) in {"local_refs", "history_refs", "_check_inputs", "_check_capability"})],
        "literal_fields": sorted({n.value for n in ast.walk(auth) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/")}),
        "explicit_a1_ids": sorted({n.value for n in ast.walk(auth) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("A1-")})}
    steps, starts = [], []
    def visit(nodes, module, scope=()):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                visit(n.body, module, (*scope, n.name))
                continue
            for call in ast.walk(n):
                if isinstance(call, ast.Call) and ast.unparse(call.func) == "_Step":
                    kw = {k.arg: k.value for k in call.keywords}
                    callback = kw.get("uses")
                    definition = None
                    if isinstance(callback, ast.Name):
                        body = trees[module].body
                        for name in scope:
                            body = next(x for x in body if isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x.name == name).body
                        definition = next((x for x in body if isinstance(x, ast.FunctionDef) and x.name == callback.id), None)
                    elif isinstance(callback, ast.Lambda):
                        definition = callback
                    pairs = [{"line": x.lineno, "point_expression": ast.unparse(x.elts[0]),
                              "purpose": x.elts[1].value} for x in ast.walk(definition) if isinstance(x, ast.Tuple)
                             and len(x.elts) == 2 and isinstance(x.elts[1], ast.Constant)
                             and (x.elts[1].value is None or isinstance(x.elts[1].value, str))] if definition is not None else []
                    steps.append({"module": module, "scope": ".".join(scope), "line": call.lineno,
                                  "name": ast.unparse(kw["name"]) if "name" in kw else "読めない",
                                  "uses": ast.unparse(kw["uses"]) if "uses" in kw else "未指定",
                                  "uses_definition": ast.unparse(definition) if definition is not None else None,
                                  "untyped_point_starts": pairs})
    for module in ("_fb_think", "_fb_update"):
        visit(trees[module].body, module)
        for node in ast.walk(trees[module]):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "Candidate":
                kw = {k.arg: k.value for k in node.keywords}
                c, use = kw.get("contract"), kw.get("use")
                contract = constants.get(c.value.id, {}).get(c.attr) if isinstance(c, ast.Attribute) and isinstance(c.value, ast.Name) else None
                starts.append({"module": module, "line": node.lineno, "contract": contract or "読めない",
                               "purpose": ast.literal_eval(use) if isinstance(use, ast.Constant) else "読めない",
                               "field": "/", "expression": ast.unparse(node)})
    root_blocked = next(n for n in trees["_fb_think"].body if isinstance(n, ast.FunctionDef) and n.name == "_root_blocked")
    output["steps"] = steps
    inputs = next(n for n in trees["_fb_think"].body if isinstance(n, ast.FunctionDef) and n.name == "_uses")
    input_items, input_unreadable = [], []
    for contract, uses in REQUEST_BINDINGS.items():
        for use, typ in uses.items():
            if typ not in {"EvaluationPrepareArgs", "DrawArgs", "EvaluationArgs"}:
                continue
            got = ImplementationReader(constants).read(inputs, contract, use, "fields", typ)
            input_items.extend(got["items"])
            input_unreadable.extend(got["unreadable"])
    output["request_inputs"] = {"line": inputs.lineno, "items": input_items, "unreadable": input_unreadable}
    output["explicit_candidate_starts"] = starts
    output["root_blocked"] = {"line": root_blocked.lineno, "expression": ast.unparse(root_blocked),
                              "status": "読めない: plan.points のキーから記録の契約を推測しない"}
    return output


def human(result: dict, command: str) -> str:
    lines = [f"{command}: " + ("一致" if result.get("matches") else "OK" if result.get("ok") else "要確認")]
    if "grammar_errors" in result:
        return "\n".join(lines + [f"文法の未分類: {result['unclassified_count']}", "| 行 | ID | 理由 |", "|---:|---|---|"] +
                         [f"| {x['line']} | {x['id']} | {x['reason'].replace('|', '&#124;')} |" for x in result["grammar_errors"]])
    if command == "check":
        if "enumeration_atom_count" in result:
            lines.append(f"列挙原子: 直書き {result['enumeration_direct_atom_count']}（うち呼出前置 {result['enumeration_call_prelude_atom_count']}）"
                         f" + use展開 {result['enumeration_reused_atom_count']} = {result['enumeration_atom_count']}。"
                         f"codeあり: {result['enumeration_coded_atoms']}。")
        if "a1_runtime_atom_count" in result:
            lines += [f"T-A1 phase: runtime {result['a1_runtime_atom_count']} / test {result['a1_test_atom_count']}。",
                      f"列挙 phase（呼出前置を含む）: runtime {result['enumeration_runtime_atom_count']} / test {result['enumeration_test_atom_count']}。"]
        if "profile" in result:
            return "\n".join(lines + [result["profile"], result["structural_check"], "| 表 | 行数 |", "|---|---:|"] +
                             [f"| {t} | {n} |" for t, n in result["table_counts"].items()])
        lines += ["", "| 表 | 行数 |", "|---|---:|", *[f"| {t} | {n} |" for t, n in result["table_counts"].items()],
                  "", f"構造を列挙: {result['contract_count']} 契約 / {result['field_count']} 欄。未分類: {result['unclassified_count']}。",
                  f"原子関係: {result['atom_count']} / 列挙: {result['enumeration_count']} ブロック・{result['enumeration_item_count']} 項目 / 未原子化: {len(result['unatomized_a1'])} 行。",
                  f"T-A1のcodeあり: {result['coded_atoms']} 原子 / 不適合でcodeなし: {len(result['uncoded_mismatch_atoms'])} 原子。",
                  f"完全列挙: {result['fully_enumerated_contract_count']} 契約 / 紙に従って委ねた: {result['delegated_contract_count']} 契約 / 部分列挙: {len(result['unavailable_contracts'])} 契約。",
                  "", "| 契約 | 用途 | 未分類の欄 |", "|---|---|---|",
                  *[f"| {x['contract']} | {x['purpose']} | {x['field']} |" for x in result["unclassified"]],
                  "", "| 列挙できなかった契約 | 理由 |", "|---|---|",
                  *[f"| {x['contract']} | {x['reason']} |" for x in result["unavailable_contracts"]],
                  "", "| 列挙未完了の契約 | 用途 | 欄 | 式・出典 |", "|---|---|---|---|",
                  *[f"| {x['contract']} | {x['purpose']} | {x['field']} | {x.get('detail', '').replace('|', '&#124;')} |" for x in result["opaque_fields"]],
                  "", "| 紙 G6 の操作 | 行 | T-G6 ID |", "|---|---:|---|",
                  *[f"| {x['operation']} | {x['paper_line']} | {', '.join(x['rule_ids']) or '対応未確定'} |" for x in result["operations"]["paper_operations"]],
                  "", "| T-G6 ID | 操作 | 段階 | 契約 | 用途 | 適用方式 |", "|---|---|---|---|---|---|",
                  *[f"| {x['id']} | {x['operation']} | {x['stage']} | {x['contract']} | {x['purpose']} | {x['application']} |" for x in result["operations"]["registered_operations"]],
                  "", "T-A1 項目 ID: " + ", ".join(result["a1_ids"]),
                  "未確定: " + ", ".join(x["id"] for x in result["pending"])]
    elif command == "generate":
        lines += ["出力: " + result["output"],
                  "表の未確定・未原子化なし: " + ("はい" if result["complete"] else "いいえ"),
                  "構造網羅・実装接続・実行検査の完了はこの印に含めない。",
                  "未確定: " + ", ".join(x["id"] for x in result["pending"])]
    elif command == "diff":
        lines += ["", "| 表 | ID | 変更 | 詳細 |", "|---|---|---|---|",
                  *[f"| {x['table']} | {x['id']} | {x['change']} | {json.dumps(x.get('fields', {}), ensure_ascii=False)} |" for x in result["changes"]],
                  "", "| 契約 | 欄 | 型の変更 | 以前 | 現在 |", "|---|---|---|---|---|",
                  *[f"| {x['contract']} | {x['field']} | {x['change']} | {x['old']} | {x['new']} |" for x in result["field_type_changes"]],
                  "", "| 関係・列挙宣言 | 意味の変更 |", "|---|---|",
                  *[f"| {x['name']} | {x['change']} |" for x in result["declaration_changes"]],
                  f"行の意味の変更 {len(result['changes'])} / 関係・列挙宣言の変更 {len(result['declaration_changes'])} / 欄の型の変更 {len(result['field_type_changes'])} / 表の宣言の変更 {len(result['schema_changes'])} / 出典・版の変更 {len(result['provenance_changes'])}"]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "generate", "diff"))
    parser.add_argument("--paper", type=Path, default=PAPER)
    parser.add_argument("--out", type=Path, default=OUTPUT, help="generated module path (generate/diff)")
    parser.add_argument("--format", choices=("both", "json", "human"), default="both")
    args = parser.parse_args(argv)
    try:
        data = read_paper(args.paper)
        if args.command == "check":
            result = check(data, args.paper.read_text(encoding="utf-8-sig"))
            code = 0 if result["ok"] else 1
        elif args.command == "generate":
            generate(data, args.out)
            result = {"ok": True, "output": str(args.out), "complete": data["complete"], "pending": data["pending"]}
            code = 0
        else:
            result = diff(data, load_generated(args.out))
            code = 0 if result["matches"] else 1
    except AtomSyntaxError as exc:
        result = {"ok": False, "error": str(exc), "unclassified_count": len(exc.issues), "grammar_errors": exc.issues}
        code = 1 if args.command == "check" else 2
    except (TableError, OSError, UnicodeError, SyntaxError) as exc:
        result, code = {"error": str(exc)}, 2
    if args.format != "json":
        print(human(result, args.command) if code != 2 else result["error"])
    if args.format != "human":
        if args.format == "both":
            print("\nJSON:")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
