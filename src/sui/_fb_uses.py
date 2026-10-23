"""使用の依存 UseDeps・論理の鍵・食い違いの判定・操作の出発点・必須入力 — 規則は紙の表から (紙 F-b §6-11、段 3)。

規則の正本は紙 §6-11 の機械可読の表 5 枚で、`tools/rule_tables.py generate` が `_fb_rules.py` に写す。ここは
その表を**読む**だけで、契約ごとの辺・鍵・出発点・必須入力を手で列挙しない (開発フローの紙 ①-b「紙の表を
写さない道具」)。表に無い行は「表に無い」と現れる (Unsupported / pending)。空欄を辺なしと見なす既定値は置かない。

- T-REF: 参照義務 `Obligation` (規則 ID・出発・欄・到達・用途・役割)。Point の集合には潰さず、照合の後で
  UseDeps (U/UE の最小不動点、G3) や C (A2) に射影する
- T-G4: 節点から導く論理の鍵と比較の bytes (`keys_of`)。窓口の配送 (`delivery`) と固定像の再読
  (`saved_delivery`) も同じ行から
- T-G6: 操作と出発点 (`starts_of`)。公開・入場・取得の共通の操作が「使う候補と契約」を受けて出発点を導く
- T-A2: 必須入力 (`required`)。Local / History / 前の C / 前の I の行を T-REF の展開でたどる

節点は (対象, 用途)。対象は保存した Point か、まだ作っていない後続の候補 (Candidate、仮の CID を作らない、G1)。
読み手は窓口 (台帳)・入口 U (Q* の部分像)・評価の準備 (compiler の見える範囲) のどれでもよく、同じ規則で閉じる。
欄は復号した本文に、記録の外側の欄 (/parents・/inputs・/basis・/about・/target) を足した文書に当てる (§6-11 表記規約)。
"""

import re as _re
from dataclasses import dataclass as _dataclass, field as _field

from . import _fb_rules as _R
from ._fb_wire import dumps as _dumps


class Unsupported(Exception):
    """契約・用途・枝に要る規則が表に無い、またはこの版の未対応 (G2: missing_contract)。"""


class Undetermined(Unsupported):
    """閉包が未確定の規則 (表の停止マーカー) か、この版で未対応の鍵の形に届いた: 必要な依存が未解決のまま許可に
    射影しない (表記規約「未確定は推測しなかった停止マーカー」、FB3-R01-R6)。rules はその規則 ID。"""

    def __init__(self, rules):
        self.rules = tuple(rules)
        super().__init__("undetermined dependencies: " + ", ".join(self.rules))


class Unresolved(Exception):
    """要る参照が読み手の中に無い、または 1 つの Point に解決しない (G1: 欠けた辺を消して使用可にしない)。"""


class Malformed(Exception):
    """記録の本文が表の欄の形でない (欄が無い・配列でない・和型でない)。"""


class Mismatch(Exception):
    """T-REF の条件 `assert` の原子が確定した不一致で落ちた (使用の義務の失敗。辺を落として許可にしない)。"""


LEDGER_READ_ERRORS = (LookupError, OSError)   # 台帳の読みの故障 (本文がまだ無い・保存の確認待ち・store の故障) = 門は wait


EXTERNAL = "external"   # 表に行の無い契約へ届いた節点の用途 (F-a の版つき契約へ接続、leaf にしない)
UNDECIDED = "undecided"  # E の参照で、到達先の契約が用途を 1 つに決めない (必須入力としては Point だけ要る)
_PENDING = "未確定"
_REPORTS = ("sui.fb.segment_report/1", "sui.fb.work_report/1", "sui.fb.draw_report/1")


def contract_name(contract) -> str:
    """ContractRef か JSON の {name, version} か文字列を、表の契約の表記 `name/version` に。"""
    if isinstance(contract, str):
        return contract
    if hasattr(contract, "items"):
        return f"{contract['name']}/{contract['version']}"
    return f"{contract.name}/{contract.version}"


@_dataclass(frozen=True)
class Candidate:
    """まだ作っていない後続 (G1)。保存予定の契約・内容・参照 (basis・about の Point) を持つ。"""
    contract: object
    content: object
    use: str
    basis: tuple = _field(default=())
    about: tuple = _field(default=())
    target: object = None   # Prediction の外側の target (保存予定の値)
    contexts: tuple = _field(default=())   # ((到達先の Point, 条件の文脈), …): 候補の辺が届く B の読み方との対
    parents: tuple = _field(default=())    # 保存予定の実親 (決まっていれば。仮の CID は作らない)


@_dataclass(frozen=True)
class Obligation:
    """参照義務 (T-REF の 1 行を 1 つの欄の実例に当てたもの)。target は到達先の Point (値の欄なら None)。"""
    rule: str
    start: object           # Point か Candidate
    contract: str
    purpose: str
    field: str              # 表の欄 (JSON Pointer の型)
    path: str               # 実例の経路 (配列の添字つき)
    value: object
    target: object
    target_contract: str    # 到達先の契約の表記 ('-' = 値の欄)
    target_purpose: str     # 到達先の用途 (EXTERNAL = 表に行が無い契約)
    role: str               # U / UE / E / leaf / ignored / unsupported / 未確定
    assumed: bool = False   # (使わない: 文脈の無い条件は仮定せず止める。互換のため残す)


# ---------------------------------------------------------------- 表の索引

def _index(rows, key):
    out = {}
    for row in rows:
        out.setdefault(key(row), []).append(row)
    return {k: tuple(v) for k, v in out.items()}


_REF = _index(_R.T_REF, lambda r: (r["contract"], r["purpose"]))
_PURPOSES = {c: frozenset(p for (cc, p) in _REF if cc == c) for (c, _p) in _REF}
_REF_BY_ID = {r["id"]: r for r in _R.T_REF}
_G4 = _index(_R.T_G4, lambda r: r["contract"])
_A2 = _index(_R.T_A2, lambda r: (r["group"], r["contract"], r["purpose"]))
_G6 = _index(_R.T_G6, lambda r: r["operation"])
A2_GROUPS = tuple(dict.fromkeys(r["group"] for r in _R.T_A2))   # Local / History / 前のC / 前のI (表の順)
PENDING_RULES = tuple(p["id"] for p in _R.METADATA["pending"])


# ---------------------------------------------------------------- 欄 (JSON Pointer) の解決

_SEGMENT = _re.compile(r"^([^\[\]?]+)(?:\[kind=([^\]]+)\])?(\?)?$")


def _element_matches(item, element):
    """element 条件: 配列の要素から相対の欄が期待の JSON 値と一致 (型を変えて比べない)。欄が無い・型が違えば Malformed。"""
    for relative, expected in element.items():
        if _single(item, relative) != expected:
            return False
    return True


def _walk(document, field, *, loose=False, element=None):
    """欄の実例 [(経路, 値)]。配列は `/*`、和型は `[kind=枝]` で選ぶ (枝が違えば実例なし)、`?` の null は実例なし。
    loose=True は枝の選択を無視し、null と無い欄を実例なしにする (どの行も扱わない実例の検出用)。
    element は最も近い `*` の要素に先に当てる条件 (合う要素だけを先へたどる。表記規約の element 条件)。"""
    out = [("", document)]
    segments = field.split("/")[1:]
    last_star = max((i for i, segment in enumerate(segments) if segment.startswith("*")), default=None)
    for index, segment in enumerate(segments):
        if segment == "*" or segment.startswith("*["):
            # `*[kind=x]`・`*[id=y]`・複数の選択子 (全一致): 配列の要素を宣言した識別子で選ぶ (導出の結果の列、表記規約 31 行)
            selectors = _re.findall(r"\[(\w+)=([^\]]+)\]", segment[1:]) if segment != "*" else []
            if segment != "*" and ("".join(f"[{k}={v}]" for k, v in selectors) != segment[1:] or not selectors):
                raise Unsupported(f"unreadable array selector {segment}")
            nxt = []
            for path, value in out:
                if not isinstance(value, list):
                    if loose and value is None:
                        continue
                    raise Malformed(f"{field}: {path} is not an array")
                for i, item in enumerate(value):
                    if element is not None and index == last_star and not _element_matches(item, element):
                        continue
                    if selectors and not (hasattr(item, "items") and all(item.get(k) == v for k, v in selectors)):
                        continue
                    nxt.append((f"{path}/{i}", item))
            out = nxt
            continue
        if segment.isdigit():   # 実例の経路 (配列の添字) を欄として読む
            out = [(f"{path}/{segment}", value[int(segment)]) for path, value in out
                   if isinstance(value, list) and int(segment) < len(value)]
            continue
        match = _SEGMENT.match(segment)
        if match is None:
            raise Unsupported(f"unreadable field {field}")
        name, kind, optional = match.groups()
        nxt = []
        for path, value in out:
            if hasattr(value, "reason") and not hasattr(value, "items"):
                nxt.append((path, value))   # 評価器の Missing (読めなかった値): 下りずにそのまま運ぶ (理由を失わない)
                continue
            if not hasattr(value, "items") or name not in value:
                if loose:
                    continue
                raise Malformed(f"{field}: {path} has no {name}")
            value = value[name]
            if value is None and (optional or loose):
                continue
            if kind is not None and not loose:
                if not (hasattr(value, "items") and "kind" in value):
                    raise Malformed(f"{field}: {path}/{name} is not a union")
                if value["kind"] != kind:
                    continue
            nxt.append((f"{path}/{name}", value))
        out = nxt
    return out


def _template(field) -> str:
    return _re.sub(r"\[kind=[^\]]+\]", "", field).replace("?", "")


def _single(document, pointer):
    found = _walk(document, pointer)
    if len(found) != 1:
        raise Malformed(f"{pointer} is not a single field")
    return found[0][1]


# ---------------------------------------------------------------- 読み手

class Reader:
    """閉包を取る読み手の口。像は台帳・固定像の閉包・compiler の見える範囲のどれでもよい。
    Ref → Point の索引は記録の header の識別子 (entry.id) から作り本文を読まない (許された範囲の外の本文の
    欠落で落ちない、FB3-SCOPE-R6)。本文は document() / body() で初めて読む (そこで範囲の検査が当たる)。"""

    def __init__(self, image, evidence=None):
        self._image = image
        self.evidence = evidence   # 独立の観測 (TargetEvidence) があれば T-REF の assert の EW:/EH: がこれを読む
        self._by_ref = None
        self._requests = None

    def _entries(self):
        return getattr(self._image, "all_entries", self._image.entries)()

    def _peek(self, point):
        try:
            return getattr(self._image, "peek", self._image.record)(point)
        except LookupError:   # KeyError (台帳に無い)・FReplayUnavailable (像の外・本文が読めない)
            raise Unresolved(point) from None

    def point(self, ref):
        if isinstance(ref, str):   # 文書の外側の欄は保存した Ref を文字列 (`kind:name`) で持つ
            parsed = as_ref(ref)
            if parsed is None:
                raise Unresolved(f"{ref} is not a record reference")
            ref = parsed
        if self._by_ref is None:
            by_ref = {}
            for entry in self._entries():
                by_ref.setdefault(entry.id, []).append(entry.cid)
            self._by_ref = by_ref
        found = self._by_ref.get(ref, ())
        if len(found) != 1:   # 複数の CID を辞書順で 1 つに選ばない (F-a :150〜153)
            raise Unresolved(f"{ref} does not resolve to one point")
        return found[0]

    def contract_of(self, point) -> str:
        return contract_name(self._peek(point).body.contract)

    def document(self, point):
        """(契約の表記, 文書)。文書 = 本文の JSON + 外側の欄 (parents = 実親の Point、inputs = Decided の外側 inputs の保存した
        Ref、basis・about = Prediction の外側の欄の保存した Ref、target)。Ref は解決せずそのまま (表記規約 15 行、表の係 17 通目:
        解決は `points` や導出 resolved_refs が像に対して明示に行い、元の Ref の列との対応を保つ)。"""
        try:
            record = self._image.record(point)
        except LookupError:   # KeyError (台帳に無い)・FReplayUnavailable (像の外・本文が読めない)
            raise Unresolved(point) from None
        body = record.body
        content = body.content.as_json() if getattr(body, "content", None) is not None else None
        document = dict(content) if hasattr(content, "items") else {"value": content}
        try:
            document["parents"] = sorted(self._image.entry(point).parents)
        except (KeyError, AttributeError):
            document["parents"] = []
        for outer in ("inputs", "basis", "about"):
            refs = getattr(body, outer, None)
            if refs is not None:
                document[outer] = [str(ref) for ref in refs]
        if getattr(body, "target", None) is not None:
            document["target"] = body.target
        return contract_name(body.contract), document

    def points(self, refs):
        """保存した Ref の列を像の中の Point の列に解決する (1 つに解決しない Ref は Unresolved)。"""
        return tuple(self.point(ref) for ref in refs)

    def body(self, point):
        """(契約 (ContractRef のまま), 本文の JSON, basis の Point の列, about の Point の列)。旧の口。"""
        _name, document = self.document(point)
        body = self._image.record(point).body
        return body.contract, body.content.as_json(), self.points(document.get("basis", ())), self.points(document.get("about", ()))

    def clock_source(self, run):
        """run の保存時計宣言 (T-REF の条件 resolve=clock_declaration_for_run、§19-4)。1 つでなければ Unresolved。"""
        found = []
        for entry in self._entries():
            body = self._peek(entry.cid).body
            if contract_name(body.contract) == "sui.clock.source/1" and body.content.as_json().get("run") == run:
                found.append(entry.cid)
        if len(found) != 1:
            raise Unresolved(f"clock declaration for run {run!r} does not resolve to one point")
        return found[0]

    def request_of(self, work_id):
        """WorkId の要求の記録 (T-G4 の via=authenticated_request)。1 つでなければ Unresolved。"""
        if self._requests is None:
            found = {}
            for entry in self._entries():
                body = self._peek(entry.cid).body
                content = body.content.as_json() if getattr(body, "content", None) is not None else None
                desc = content.get("desc") if hasattr(content, "items") else None
                if hasattr(desc, "items") and "work_id" in desc:
                    found.setdefault(desc["work_id"], []).append(entry.cid)
            self._requests = found
        points = self._requests.get(work_id, ())
        if len(points) != 1:
            raise Unresolved(f"request of {work_id!r} does not resolve to one point")
        return points[0]


class _WorkRequest:
    """窓口の配送の読み手: 要求の解決はその仕事の行の request (札を取った口の仕事) に限り、本文は台帳の読み手で
    (T-G4 の via=authenticated_request。WorkId の名乗りから台帳を走査しない)。"""

    def __init__(self, work, reader):
        self._work, self._reader = work, reader

    def request_of(self, work_id):
        if work_id != self._work.desc.work_id:
            raise Unresolved(f"request of {work_id!r} is not this work")
        return self._work.request

    def document(self, point):
        return self._reader.document(point)


# ---------------------------------------------------------------- T-REF: 参照義務

def _at(document, pointer, path):
    """条件の欄 (pointer、`*` を含みうる) を、実例の経路 path の同じ深さの祖先で読む (実例ごとの条件)。"""
    depth = len(pointer.split("/"))
    return _single(document, "/".join(path.split("/")[:depth]))


def _condition(row, document, context, path=None):
    """出発の側の条件。真なら (適用, 文脈なしで仮定したか)、偽なら None。到達の側の条件は _target_ok で。
    path=None は欄をたどる前 (配列を含まない条件だけ)、path ありは実例ごと (配列を含む条件も)。"""
    condition = row["condition"]
    if condition is True or condition == _PENDING:
        return True, False
    assumed = False
    for key, expected in condition.items():
        if key in ("target_contract", "item_kind", "resolve", "count", "assert", "lookup"):
            continue   # 到達の側・件数・原子・不存在照会は _row_obligations が扱う
        if key == "element":
            # 欄の最も近い `*` の要素から相対の欄と値の一致 (表の係 3 通目に頼んだ形、sui-20261021-2135)
            if path is None:
                continue   # 実例ごとに見る
            segments = row["field"].split("/")
            depth = max(i for i, segment in enumerate(segments) if segment == "*") + 1
            element = "/".join(path.split("/")[:depth])
            for relative, value in expected.items():
                if _single(document, element + relative) != value:
                    return None
            continue
        if key in ("nonnull", "is_null"):
            if "*" in expected and path is None:
                continue   # 実例ごとに見る
            value = _at(document, expected, path) if "*" in expected else _single(document, expected)
            if (value is None) != (key == "is_null"):
                return None
        elif key in ("method", "method_not"):
            method = contract_name(_single(document, "/desc/method"))
            if (method == expected) != (key == "method"):
                return None
        elif key in ("generation", "support_required"):
            if context is None or key not in context:
                # 文脈 (読み方との対) が無い: 真と仮定せず、意味が決まるまで使用を止める (表の係 2026-10-21 2-4)
                raise Unsupported(f"{row['id']}: the condition {key} is undetermined without the reading context")
            if context[key] != expected:
                return None
        else:
            raise Unsupported(f"{row['id']}: unknown condition {key}")
    return True, assumed


def _target_ok(row, reader, target):
    condition = row["condition"]
    if condition is True or condition == _PENDING:
        return True
    if "target_contract" in condition and reader.contract_of(target) != condition["target_contract"]:
        return False
    if "item_kind" in condition:
        _c, document = reader.document(target)
        if document["item"]["kind"] != condition["item_kind"]:
            return False
    return True


def _decided_purpose(reader, target, row):
    """到達先の用途: 行が決めていればそれ、'-' なら到達先の契約が決める (T-REF にその契約の用途が 1 つだけある時)。
    行の無い契約は EXTERNAL (F-a の版つき契約へ接続、leaf にしない)。"""
    if row["target_purpose"] != "-":
        purpose = row["target_purpose"]
        contract = row["target_contract"] if row["target_contract"] != "-" else reader.contract_of(target)
        return contract, (purpose if contract in _PURPOSES else EXTERNAL)
    contract = reader.contract_of(target)
    purposes = _PURPOSES.get(contract)
    if purposes is None:
        return contract, EXTERNAL
    if len(purposes) == 1:
        return contract, next(iter(purposes))
    if any(_row_branch(r) is not None for r in _G4.get(contract, ())):   # 原報告: 用途は本文の枝が決める (T-G4)
        _c, document = reader.document(target)
        return contract, report_purpose(contract, document)
    raise Unsupported(f"{row['id']}: the purpose of {contract} is not decided by its contract")


def as_ref(value):
    """値が記録の識別子 Ref (`kind:name`、F-a の DTO の参照) ならその Ref、Point (`sha256:…`) や他の値なら None。
    Point と Ref を区別し、Ref は読み手の中で 1 つの Point に解決する (A1-REF-RESOLUTION)。"""
    from .ids import Ref, RefKind
    if not isinstance(value, str) or ":" not in value:
        return None
    kind, name = value.split(":", 1)
    try:
        ref = Ref(RefKind(kind), name)
    except ValueError:
        return None
    # run と individual の Ref は記録の識別子ではない (時計の run・個体の同一性。`ids.RefKind`)。記録を指すのは
    # 記録の種類 (observation・prediction・decision・intention・preference・interpretation・job・attempt) だけ
    return None if ref.kind in (RefKind.RUN, RefKind.INDIVIDUAL) else ref


_FIELD_TYPES = getattr(_R, "FIELD_TYPES", {})   # (契約, 欄) → point / ref / value / union / unknown (契約の構造宣言から生成)


def field_type(contract, field) -> str:
    """欄の型 (生成物 FIELD_TYPES、契約の DTO から)。表の欄の表記 (`?`・`[kind=枝]`・`/*`) をそのまま鍵に。"""
    found = _FIELD_TYPES.get((contract, field))   # 外側の欄 (/parents 等) は生成器 1.6 が規約どおり point に (道具の係 7 通目)
    if found is None:
        found = _FIELD_TYPES.get((contract, _template(field)))
    return found or "unknown"


def reference(reader, contract, field, value, path):
    """欄の値を記録の参照として解く: 型が point ならそのまま、ref なら読み手の中で 1 つの Point に、value なら None
    (値の欄。Point を捏造しない)。型が unknown (構造宣言の無い契約の欄、★ 段 0 (a) の DTO 化まで) と union は値の形
    (`kind:name` の Ref / `sha256:` の Point) で読む。"""
    kind = field_type(contract, field)
    if kind == "value":
        return None
    if not isinstance(value, str):
        if kind in ("point", "ref"):
            raise Malformed(f"{contract} {path}: not a {kind}")
        return None
    if kind == "ref":
        if value.startswith("sha256:"):
            return value   # 記録の外側の欄 (basis・about・inputs) は文書に Point で入れてある (Reader.document)
        ref = as_ref(value)
        if ref is None:
            if ":" in value and value.split(":", 1)[0] in ("run", "individual"):
                return None   # run・individual の Ref は記録の識別子ではない (`ids.RefKind`)
            raise Malformed(f"{contract} {path}: not a Ref")
        return reader.point(ref)
    if kind == "point":
        return value
    ref = as_ref(value)   # unknown / union: 値の形で (暫定)
    if ref is not None:
        return reader.point(ref)
    name = path.rsplit("/", 1)[-1]
    if value.startswith("sha256:") and not (name.endswith("_key") or name.endswith("_digest")):
        return value
    return None


def _resolve_target(row, reader, document, value, path, *, contract=None, field=None):
    condition = row["condition"]
    if hasattr(condition, "items") and condition.get("resolve") == "clock_declaration_for_run":
        return reader.clock_source(value)
    target = reference(reader, contract or row["contract"], field or row["field"], value, path)
    if target is None and (row["role"] in ("U", "UE") or row["target_contract"] != "-"):
        raise Malformed(f"{row['id']}: {path} is not a record reference")
    return target


def _via_target(reader, via_id, start, document, context):
    """`via` (T-REF の行 ID): 同じ出発の文書でその行を当て、一意な認証済みの到達先 (Point) を返す。0 件は Unresolved、
    複数は Malformed (辞書順で 1 つに縛らない)。行の条件 (count・assert) もここで効く (「未処理行を名前だけで呼ばない」)。"""
    row = _REF_BY_ID.get(via_id)
    if row is None:
        raise Unsupported(f"via {via_id!r} is not a T-REF row")
    targets = [ob.target for ob in _row_obligations(reader, row, start, document, context) if ob.target is not None]
    if len(targets) == 0:
        raise Unresolved(f"{via_id}: no target to follow")
    if len(targets) > 1:
        raise Malformed(f"{via_id}: {len(targets)} targets, not one")
    return targets[0]


def _model_walk(document, spec, select):
    """MODEL_WALKS: 文書の根 (operations の start/termination) から述語の木を再帰し、select=positive なら正の参照の欄
    (interval_compare の key・provenance) の実例、negative_query なら不存在照会 (fact_present の fact・history) の実例を返す。
    短絡で子を飛ばさない。葉 (constant・policy_end) は何も生まない。未知の述語は missing_contract (空集合にしない)。"""
    out = []
    roots = [(path, value) for root in spec["roots"] for path, value in _walk(document, root)]
    seen = set()
    while roots:
        path, node = roots.pop()
        if path in seen:
            continue
        seen.add(path)
        if not (hasattr(node, "items") and "name" in node and "version" in node):
            raise Malformed(f"{path} is not a predicate reference")
        name = f"{node['name']}/{node['version']}"
        if name in spec["recurse"]:
            roots += [(path + sub, child) for sub, child in _walk(node, spec["recurse"][name])]
        elif name in spec["positive"]:
            if select == "positive":
                out += [(path + sub, child) for pointer in spec["positive"][name] for sub, child in _walk(node, pointer)]
        elif name in spec["negative_query"]:
            if select == "negative_query":
                out += [(path + pointer, _single(node, pointer)) for pointer in spec["negative_query"][name].values()]
        elif name in spec["leaves"]:
            continue
        else:
            raise Unsupported(f"{path}: predicate {name} is not in MODEL_WALKS ({spec['unknown']})")
    return out


def _lookup(reader, row, path, value):
    """不存在照会 (lookup=fact_present/1、F-a :299〜309): Ref が読み手の中で 1 つの Point に解決すれば E の実体辺、
    0 件なら不在の証拠 (辺は作らない、義務は残す)、複数なら Unresolved。history (E/K) は照会の付帯の値で実体辺ではない。"""
    if path.endswith("/history"):
        return None
    ref = as_ref(value)
    if ref is None:
        raise Malformed(f"{row['id']}: {path} is not a Ref")
    try:
        return reader.point(ref)
    except Unresolved:
        if len(reader._by_ref.get(ref, ())) > 1:
            raise
        return None   # 0 Entry = 確認した不在


def _assert(reader, row, start, document, target, atoms):
    """T-REF の条件 assert: 原子を SELF (出発) と TARGET (到達) で評価する。不適合は Mismatch、不足は Unresolved。"""
    from . import _fb_a1 as a1
    _c, target_document = reader.document(target)
    env = a1.Env({"SELF": (None if isinstance(start, Candidate) else start, document),
                  "TARGET": (target, target_document)}, evidence=getattr(reader, "evidence", None), reader=reader)
    try:
        a1.check(atoms, env)
    except a1.AtomFailure as exc:
        if exc.outcome.classification == a1.MISMATCH:
            raise Mismatch(f"{row['id']}: {exc.outcome.id} {exc.outcome.detail}") from None
        raise Unresolved(f"{row['id']}: {exc.outcome.id} {exc.outcome.detail}") from None
    except a1.Unknown as exc:
        raise Unsupported(f"{row['id']}: {exc}") from None


def _field_instances(reader, row, start, document, context):
    """行の欄の実例 [(経路, 値, 欄を読んだ文書, 欄の型を引く契約, 欄の表記)]。欄は JSON Pointer、{"via", "path"} (via の到達先の
    文書から)、{"walk", "root", "select"} (MODEL_WALKS。契約 '-' = 値は参照の形でなければならない)。"""
    field = row["field"]
    element = row["condition"].get("element") if hasattr(row["condition"], "items") else None
    if isinstance(field, str):
        return [(path, value, document, row["contract"], field) for path, value in _walk(document, field, element=element)]
    if "via" in field:
        base = _via_target(reader, field["via"], start, document, context)
        contract, base_document = reader.document(base)
        return [(path, value, base_document, contract, field["path"]) for path, value in _walk(base_document, field["path"])]
    if "walk" in field:
        spec = _R.MODEL_WALKS.get(field["walk"])
        if spec is None:
            raise Unsupported(f"{row['id']}: walk {field['walk']!r} is not in MODEL_WALKS")
        root = _single(document, field["root"])
        return [(field["root"] + path, value, document, "-", "-") for path, value in _model_walk(root, spec, field["select"])]
    raise Unsupported(f"{row['id']}: unreadable field {dict(field)!r}")


def _row_obligations(reader, row, start, document, context):
    """T-REF の 1 行を 1 つの節点の文書に当てた参照義務 (条件・count・assert つき)。到達先の用途はまだ決めない。"""
    if _condition(row, document, context) is None:
        return []
    condition = row["condition"] if hasattr(row["condition"], "items") else {}
    field = row["field"]
    field_text = field if isinstance(field, str) else _dumps(dict(field)).decode()
    out = []
    for path, value, read_document, read_contract, template in _field_instances(reader, row, start, document, context):
        applies = _condition(row, document, context, path if isinstance(field, str) else None)
        if applies is None:
            continue
        _ok, assumed = applies
        if "lookup" in condition:
            target = _lookup(reader, row, path, value)
        elif read_contract == "-":
            target = value if isinstance(value, str) and value.startswith("sha256:") else None
            if target is None:
                ref = as_ref(value)
                if ref is None:
                    raise Unsupported(f"{row['id']}: {path} is not a record reference (walk)")
                target = reader.point(ref)
        else:
            target = _resolve_target(row, reader, read_document, value, path, contract=read_contract, field=template)
        if target is not None and not _target_ok(row, reader, target):
            continue
        out.append(Obligation(row["id"], start, row["contract"], row["purpose"], field_text, path, value, target,
                              row["target_contract"], row["target_purpose"], row["role"], assumed))
    if "count" in condition:
        found = [ob for ob in out if ob.target is not None]
        if len(found) < condition["count"]:
            raise Unresolved(f"{row['id']}: {len(found)} of {condition['count']} targets")
        if len(found) > condition["count"]:
            raise Malformed(f"{row['id']}: {len(found)} targets, not {condition['count']}")
    if "assert" in condition:
        for ob in out:
            if ob.target is not None:
                _assert(reader, row, start, document, ob.target, condition["assert"])
    return out


def obligations(reader, start, contract, purpose, document, context=None):
    """1 つの節点 (contract, purpose, 文書) の参照義務 (T-REF の該当の全行を、欄の全実例に当てる)。
    どの行も扱わない実例があれば Unsupported (未宣言の枝を空集合として通さない)。"""
    if purpose == EXTERNAL:
        return ()
    rows = _REF.get((contract, purpose))
    if rows is None:
        raise Unsupported(f"{contract} has no rule for the use {purpose}")
    out, covered = [], set()
    for row in rows:
        if row["field"] == _PENDING:
            out.append(Obligation(row["id"], start, contract, purpose, row["field"], "", None, None, "-", "-", _PENDING))
            continue
        for ob in _row_obligations(reader, row, start, document, context):
            if isinstance(row["field"], str):
                covered.add(ob.path)
            role = ob.role
            if role == "ignored":
                continue
            if role == "unsupported":
                raise Unsupported(f"{row['id']}: {ob.path} is not supported in this version")
            target_contract, target_purpose = ob.target_contract, ob.target_purpose
            if ob.target is not None and role in ("U", "UE", "E", "leaf"):
                try:
                    target_contract, target_purpose = _decided_purpose(reader, ob.target, row)
                except Unsupported:
                    if role in ("U", "UE"):
                        raise
                    # E・leaf の参照は先をたどらないので、到達先の用途が契約から 1 つに決まらなくてよい (実在・内容の検査だけ)
                    target_contract, target_purpose = reader.contract_of(ob.target), UNDECIDED
            out.append(Obligation(ob.rule, start, contract, purpose, ob.field, ob.path, ob.value, ob.target,
                                  target_contract, target_purpose, role, ob.assumed))
    # どの行も扱わない実例: 覆う行が自分にも、上の容器にも、下の子にも無い経路 (枝の中の欄を扱う行は、その容器を
    # 扱っている。容器を E/leaf で扱う行は、その中の欄を扱っている)。via・walk の欄は文書の欄でないので分母に入れない
    for template in {_template(r["field"]) for r in rows if isinstance(r["field"], str) and r["field"] != _PENDING}:
        for path, _value in _walk(document, template, loose=True):
            if not any(p == path or p.startswith(path + "/") or path.startswith(p + "/") for p in covered):
                raise Unsupported(f"{contract} [{purpose}]: no rule applies to {path}")
    return tuple(out)


def _observation_context(reader, document):
    """Q* の観測の対 (binding, reading) ごとの文脈: 読み方の生成の契約と、Support の要否 (§19-5 whole_window)。"""
    out = {}
    try:
        uses = document["desc"]["args"]["observations"]
    except (KeyError, TypeError):
        return out
    for i, use in enumerate(uses):
        try:
            _c, plan = reader.document(use["reading"])
            generation = contract_name(plan["generation"]["contract"])
        except (Unresolved, Malformed, KeyError, TypeError):
            continue
        out[f"/desc/args/observations/{i}/binding"] = {
            "generation": generation, "support_required": generation == "sui.fb.bootstrap_generation/1"}
    return out


def _candidate_document(candidate):
    """候補の文書: 本文 + basis・about の Point。parents・inputs はまだ無い (保存の時に計算する) ので空。"""
    document = dict(candidate.content)
    document.setdefault("basis", list(candidate.basis))
    document.setdefault("about", list(candidate.about))
    if candidate.target is not None:
        document.setdefault("target", candidate.target)
    document.setdefault("parents", sorted(candidate.parents))
    document.setdefault("inputs", [])
    return document


@_dataclass
class Closure:
    """G3 の結果。keys = UseKeys、nodes = 届いた (Point, 用途) → 契約、obligations = 通った参照義務の全部、
    pending = 未確定の規則 ID、external = 表に行の無い契約へ届いた Point、assumed = 文脈なしで仮定した義務、
    unsupported_keys = 鍵の導出が未対応の T-G4 の行。"""
    keys: frozenset
    nodes: dict
    obligations: tuple
    pending: tuple
    external: frozenset
    assumed: tuple
    unsupported_keys: tuple


def closure(reader, starts, *, follow=("U", "UE")) -> Closure:
    """G3: 出発点 (Point と用途の組か Candidate) から U/UE の直の辺だけで取った最小不動点。訪問は (Point, 用途)。
    E だけの辺では進めない。"""
    keys, nodes, obs, pending, external, assumed, unsupported_keys = set(), {}, [], [], set(), [], []
    queue = []
    for start in starts:
        if isinstance(start, Candidate):
            queue.append((start, contract_name(start.contract), start.use, _candidate_document(start), None))
        else:
            queue.append((start[0], None, start[1], None, start[2] if len(start) > 2 else None))
    while queue:
        start, contract, purpose, document, context = queue.pop()
        candidate_contexts = dict(start.contexts) if isinstance(start, Candidate) else {}
        if not isinstance(start, Candidate):
            if purpose is None:
                purpose = decided_use(reader, start)   # 出発点の用途を到達先の契約が決める (配列の欄の取得など)
            if (start, purpose) in nodes:
                continue
            contract, document = reader.document(start)
            nodes[start, purpose] = contract
            if purpose == EXTERNAL:
                external.add(start)
                continue
        found_keys, found_unsupported = keys_of(contract, purpose, document, reader)
        keys |= found_keys
        unsupported_keys += found_unsupported
        contexts = _observation_context(reader, document)
        for ob in obligations(reader, start, contract, purpose, document, context):
            obs.append(ob)
            if ob.role == _PENDING:
                pending.append(ob.rule)
                continue
            if ob.assumed:
                assumed.append(ob)
            if ob.target is not None and ob.role in follow:
                queue.append((ob.target, None, ob.target_purpose, None,
                              contexts.get(ob.path) or candidate_contexts.get(ob.target) or context))
    return Closure(frozenset(keys), nodes, tuple(obs), tuple(dict.fromkeys(pending)), frozenset(external),
                   tuple(assumed), tuple(dict.fromkeys(unsupported_keys)))


def decided_use(reader, point) -> str:
    """Point の用途を契約が決める: T-REF にその契約の用途が 1 つだけならそれ、原報告は枝 (T-G4) から、
    行の無い契約は EXTERNAL。複数の用途を持つ契約は決められない (Unsupported)。"""
    contract = reader.contract_of(point)
    purposes = _PURPOSES.get(contract)
    if purposes is None:
        return EXTERNAL
    if len(purposes) == 1:
        return next(iter(purposes))
    if contract in _G4:
        _c, document = reader.document(point)
        return report_purpose(contract, document)
    raise Unsupported(f"the use of {contract} is not decided by its contract")


def use_keys(reader, starts) -> frozenset:
    """G3 の UseKeys (閉包の鍵)。閉包が表の未確定の規則 (停止マーカー) に届いていれば鍵を返さず Undetermined
    (未解決の必要依存を落として許可しない、FB3-R01-R6)。
    鍵を導けない T-G4 の行 (`Closure.unsupported_keys`) は 2 種あり、止めるかは表の行が決める: key_shape=unsupported で
    欄が実在する行 (Frame) は `keys_of(strict=True)` が Unsupported を上げる (この版で使えない)。derived だけの行
    (G4-CLAIM-CONJUNCTION) は表が `witness: finite_report_set` と書く = 排他は記録ごとの鍵でなく報告の集合の証人で見る
    (CL-APPLY は入口 U の `_apply` が同じ原 Claim の別の読みを拒む)。鍵が無いことは依存が無いことではないので一覧に残す。"""
    found = closure(reader, starts)
    if found.pending:
        raise Undetermined(found.pending)
    return found.keys


# ---------------------------------------------------------------- T-G4: 論理の鍵

def _union_kind(document, pointer):
    try:
        value = _single(document, pointer)
    except Malformed:
        return None
    return value.get("kind") if hasattr(value, "items") else None


def _row_branch(row):
    """行が当たる和型の枝: exclusion.branch、または life の行の literal (★ 表の係に LIFE 行へ branch の列を頼む)。"""
    exclusion = row["exclusion"]
    if hasattr(exclusion, "items") and "branch" in exclusion:
        return exclusion["branch"]
    if row["key_shape"] == "life" and isinstance(row["key_fields"], list):
        literals = [f["literal"] for f in row["key_fields"] if hasattr(f, "items") and "literal" in f]
        if literals:
            return literals[0]
    pointers = [f for f in (row["key_fields"] if isinstance(row["key_fields"], list) else []) if isinstance(f, str)]
    pointers += _compare_pointers(row)
    selected = {m.group(1) for p in pointers for m in _re.finditer(r"\[kind=([^\]]+)\]", p)}
    return next(iter(selected)) if len(selected) == 1 else None


def _compare_pointers(row):
    compare = row["compare_bytes"]
    return [p for p in compare if isinstance(p, str)] if isinstance(compare, list) else []


def _branch_matches(row, document):
    """行の枝が文書の枝と一致するか: exclusion.branch は比較の欄の和型の kind と、literal (life) も同じく、
    `[kind=x]` の選択を持つ行はその選択が実例を持つ時。枝の無い行はいつも。"""
    branch = _row_branch(row)
    if branch is None:
        return True
    pointers = _compare_pointers(row)
    if not pointers:
        return False
    if "[kind=" in pointers[0]:
        try:
            return bool(_walk(document, pointers[0]))
        except Malformed:
            return False
    return _union_kind(document, pointers[0]) == branch


def _key_row_applies(row, document):
    """鍵の導出に行が当たるか。exclusion.branch で枝を分ける行 (同じ族の 4 枝、FAMILY-UNNAMED) は、鍵が枝に
    依らない共通の族の鍵なので、文書の枝が宣言外でも当たる (枝名で別族にしない。枝の違いは比較で見る)。
    literal や `[kind=x]` の選択で枝を持つ行は、その枝の時だけ。"""
    exclusion = row["exclusion"]
    literals = [f for f in row["key_fields"] if hasattr(f, "items") and "literal" in f]         if isinstance(row["key_fields"], list) else []
    if hasattr(exclusion, "items") and "branch" in exclusion and not literals:
        return True   # 同じ鍵の欄を持つ枝の族 (ITEM の 4 行)
    # 枝を literal で鍵に入れる行 (LIFE の 3 行) は、その枝の時だけ (別の枝の鍵を足さない。試験の係 14 通目の赤 2 件)
    return _branch_matches(row, document)


def _scalar(value):
    return value if isinstance(value, (str, int, bool)) or value is None else _dumps(value).decode()


def _key_value(element, document, reader):
    """鍵の 1 成分: 欄の値 / literal / via (T-REF の行の一意な到達先。path があればその文書の欄、無ければ到達先の Point)。"""
    if isinstance(element, str):
        return _scalar(_single(document, element))
    if "literal" in element:
        return element["literal"]
    if "via" in element:
        if reader is None:
            raise Unresolved(f"{element['via']} is not readable here")
        target = _via_target(reader, element["via"], None, document, None)
        if "path" not in element:
            return target
        _contract, body = reader.document(target)
        return _scalar(_single(body, element["path"]))
    raise Unsupported(f"unreadable key element {element}")


def _stage_mapping(row, document, reader):
    """T-G4 の exclusion.stage_mapping: 認証した via の要求の desc.purpose を閉じた対応で結果の段へ写し、鍵の literal と
    一致することを確かめる (G4-CANDIDATE-RESULT: candidate_generation → result_stage)。対応に無い purpose は missing_contract。"""
    exclusion = row["exclusion"]
    if not (hasattr(exclusion, "items") and "stage_mapping" in exclusion):
        return
    if reader is None:
        raise Unresolved(f"{row['id']}: the via request is not readable here")
    target = _via_target(reader, exclusion["via"], None, document, None)
    _contract, body = reader.document(target)
    purpose = _single(body, "/desc/purpose")
    stage = exclusion["stage_mapping"].get(purpose)
    if stage is None:
        raise Unsupported(f"{row['id']}: purpose {purpose!r} is not in stage_mapping")
    literals = [f["literal"] for f in row["key_fields"] if hasattr(f, "items") and "literal" in f]
    if stage not in literals:
        raise Unsupported(f"{row['id']}: stage_mapping gives {stage!r} but the key names {literals}")


def keys_of(contract, purpose, document, reader=None, *, shapes=None, strict=True):
    """節点の論理の鍵 (T-G4)。purpose=None は配送 (用途は本文の枝が決める、`report_purpose`)。返すのは
    (鍵の集合, 未対応の行の ID)。鍵 = (形, 各欄の値か literal)。derived だけの行・未確定の行は未対応として残す
    (G4-CLAIM-CONJUNCTION・G4-CANDIDATE-RESULT)。unsupported の形で欄が実在すれば Unsupported (Frame、FB3-R08)。"""
    if contract not in _G4:
        return frozenset(), []
    if purpose is None and shapes is None:
        purpose = report_purpose(contract, document)
    keys, unsupported = set(), []
    for row in _G4.get(contract, ()):
        if purpose is not None and row["purpose"] != purpose:
            continue
        if shapes is not None and row["key_shape"] not in shapes:
            continue
        fields, exclusion = row["key_fields"], row["exclusion"]
        if hasattr(exclusion, "items") and "action" in exclusion:
            continue   # 比較候補の出どころの分類の行 (G6-PROV-*)。鍵の行ではない
        if row["key_shape"] == _PENDING or fields == _PENDING \
                or any(hasattr(f, "items") and "derived" in f for f in fields):
            unsupported.append(row["id"])
            continue
        if not _key_row_applies(row, document):
            continue
        if any(hasattr(f, "items") and f.get("via") == "authenticated_request" for f in fields):
            # 報告の鍵は、認証した要求 (その仕事の行の request) の同じ形の鍵そのもの (G4-DRAW-REPORT: DrawRecord.id)
            if reader is None:
                raise Unresolved("the authenticated request is not readable here")
            request = reader.request_of(_single(document, "/work"))
            contract_of_request, body = reader.document(request)
            found, _unsupported = keys_of(contract_of_request, None, body, reader, shapes=(row["key_shape"],))
            keys |= found
            continue
        try:
            values = tuple(_key_value(f, document, reader) for f in fields)
        except Malformed:
            continue   # 欄が無い枝 (例: claim の報告に frame の欄は無い)
        _stage_mapping(row, document, reader)
        if row["key_shape"] == "unsupported":
            if strict:   # 使う側の閉包: 鍵を導けない記録は使えない (Frame、FB3-R08 の持ち越し)
                raise Unsupported(f"{row['id']}: {exclusion.get('rule')} is not supported in this version")
            unsupported.append(row["id"])   # 届いただけの配送: 比較に入れず、未対応として残す
            continue
        keys.add((row["key_shape"], *values))
    return frozenset(keys), unsupported


def report_purpose(contract, document) -> str:
    """配送や保存済みの原報告の用途は、T-G4 の枝 (branch / literal) が本文の枝と一致する行の用途 (1 つに決まる時)。
    枝の行が無い契約は、その契約の行の用途が 1 つなら それ。"""
    rows = _G4.get(contract, ())
    matched = {r["purpose"] for r in rows if _row_branch(r) is not None and _branch_matches(r, document)}
    if not matched:
        matched = {r["purpose"] for r in rows if _row_branch(r) is None}
    if len(matched) != 1:
        raise Unsupported(f"{contract}: the use of this report is not decided by T-G4 ({sorted(matched)})")
    return next(iter(matched))


def compare_bytes(contract, document) -> bytes:
    """配送の比較の bytes (T-G4 の compare_bytes の欄の全部、CMP の全欄)。"""
    purpose = report_purpose(contract, document)
    pointers = []
    for row in _G4.get(contract, ()):
        if row["purpose"] == purpose and _key_row_applies(row, document):
            pointers += _compare_pointers(row)
    pointers = list(dict.fromkeys(pointers))
    if not pointers:
        raise Unsupported(f"{contract}: no comparison fields in T-G4")
    return _dumps([_single(document, p) for p in pointers])


def delivery(event, work, reader) -> tuple | None:
    """その仕事の口からホストが受け取った配送 1 つの (論理の鍵の集合, 比較の bytes, 不明か)。出どころが合わない配送
    (別の区間を名乗る区間の報告・別の仕事を名乗る終わり) はその口の報告にしない。"""
    from . import fb as _fb
    from ._fb_wire import encode
    desc = work.desc
    if isinstance(event, _fb.SegmentReport):
        if not isinstance(work, _fb.MeasureSegment) or event.segment != work.request:
            return None
        contract, unknown = "sui.fb.segment_report/1", False
    elif isinstance(event, (_fb.WorkFinished, _fb.DrawReturned)) and event.work == desc.work_id:
        contract = "sui.fb.work_report/1" if isinstance(event, _fb.WorkFinished) else "sui.fb.draw_report/1"
        unknown = isinstance(event.outcome, (_fb.WorkUnknown, _fb.DrawUnknown))
    else:
        return None
    document = encode(event)
    keys, _unsupported = keys_of(contract, None, document, _WorkRequest(work, reader), strict=False)
    return keys, compare_bytes(contract, document), unknown


def saved_delivery(contract, document, work_id, segment_work, reader=None) -> tuple | None:
    """固定像の再読 (G5): 像の中の保存済みの原報告 1 つを、独立の観測でその仕事の口から来たと確かめた時の配送。
    segment_work は区間 k → その測る仕事の WorkId。"""
    name = contract_name(contract)
    if name == "sui.fb.segment_report/1":
        if segment_work(document["segment"]) != work_id:
            return None
        unknown = False
    elif name in ("sui.fb.work_report/1", "sui.fb.draw_report/1"):
        if document["work"] != work_id:
            return None
        unknown = document["outcome"]["kind"] == "unknown"
    else:
        return None
    keys, _unsupported = keys_of(name, None, document, reader, strict=False)
    return keys, compare_bytes(name, document), unknown


def clashes(deliveries) -> frozenset:
    """G4: 同じ鍵に両立しない配送があれば、その鍵 (affected)。同じ値の再配送は 1 つ、不明と値の組は食い違いに
    しない。配送を先に 1 件へ潰さず、全部の比較の bytes を見る。配送の鍵は集合 (1 つの報告が複数の鍵を持ちうる)。"""
    values = {}
    for keys, value, unknown in deliveries:
        if unknown:
            continue
        for key in (keys if isinstance(keys, (set, frozenset)) else {keys}):
            values.setdefault(key, set()).add(value)
    return frozenset(key for key, found in values.items() if len(found) > 1)


# ---------------------------------------------------------------- T-G6: 操作と出発点

_DESC_USE = {"belief_update": "update", "evaluation": "evaluate"}   # Desc.purpose ↔ 要求の使用の用途 (A1-REQUEST)


def _request_use(subject, reader):
    """同じ契約に複数の用途の行がある操作 (work_requested の update / evaluate) は、要求の本文の purpose で選ぶ。"""
    if isinstance(subject, Candidate):
        document = subject.content
    elif reader is not None:
        _c, document = reader.document(subject)
    else:
        return None
    desc = document.get("desc") if hasattr(document, "items") else None
    return _DESC_USE.get(desc.get("purpose")) if hasattr(desc, "items") else None


def reading_context(reader, reading):
    """観測の読み方 (observation_plan) から、B に当てる条件の文脈 (生成の契約・Support の要否)。"""
    _c, plan = reader.document(reading)
    generation = contract_name(plan["generation"]["contract"])
    return {"generation": generation, "support_required": generation == "sui.fb.bootstrap_generation/1"}


def starts_of(operation, subjects, *, stage=None, reader=None, contexts=None) -> list:
    """T-G6: 操作 (表の「操作」の文字列) と、その操作が使う候補か記録 (契約の表記 → Point | Candidate | その列) から
    門の出発点 [(Point, 用途) | Candidate]。Candidate は用途を表から受け取る (呼出し元が用途を選ばない)。
    行の「適用方式」(表の列): 同時 = 全行の主語を同時に要る (無ければ Unresolved) / 対象別 = 主語の契約 (と契約が
    決める用途) に合う行だけ / 共通 = 主語を持たない行 (出発点を足さない)。主語に行の無い契約があれば Unsupported。
    contexts は Point → 条件の文脈 (B の読み方との対)。stage で段階を絞れる。"""
    rows = [r for r in _G6.get(operation, ()) if stage is None or r["stage"] == stage]
    if not rows:
        raise Unsupported(f"T-G6 has no operation {operation!r}")
    CALLED.add(operation)
    out, seen = [], set()
    for row in rows:
        contract, application = row["contract"], row.get("application")
        if application is None:
            raise Unsupported(f"{row['id']}: T-G6 has no application mode for this row")
        if application == "共通" or contract == "-":
            continue   # 共通の処理・門の対象外の行 (G6-VERSION-RECHECK・SAVE-RETRY・RAW-SAVE・DIAGNOSTIC-SAVE)
        if contract not in subjects:
            if application == "同時":
                raise Unresolved(f"{row['id']}: the operation has no {contract} to start from")
            continue
        found = subjects[contract]
        for subject in (found if isinstance(found, (list, tuple)) else (found,)):
            if sum(1 for r in rows if r["contract"] == contract) > 1:
                chosen = _request_use(subject, reader)
                if chosen != row["purpose"]:
                    continue
            seen.add(contract)
            if isinstance(subject, Candidate):
                out.append(Candidate(subject.contract, subject.content, row["purpose"], subject.basis, subject.about,
                                     subject.target, subject.contexts, subject.parents))
            elif contexts is not None and subject in contexts:
                out.append((subject, row["purpose"], contexts[subject]))   # 条件の文脈 (B の読み方との対) を添える
            else:
                out.append((subject, row["purpose"]))
    missing = set(subjects) - seen
    if missing:
        raise Unsupported(f"{operation!r}: T-G6 has no row for {sorted(missing)}")
    return out


CALLED = set()   # この実行で出発点を導いた操作 (T-G6 の全操作に呼出し元があるかの検査用)
OPERATIONS = frozenset(r["operation"] for r in _R.T_G6 if r["contract"] != "-")


# ---------------------------------------------------------------- T-A2: 必須入力

def _required_target(ref, reader, value, path=""):
    """T-A2 の展開の欄は必須入力の参照: 欄の型が point / ref なら記録の参照 (Ref は読み手の中で 1 つの Point に解決)、
    値 (方法の ContractRef など) は Point を捏造せず認証義務のまま (None)。"""
    condition = ref["condition"]
    if hasattr(condition, "items") and condition.get("resolve") == "clock_declaration_for_run":
        return reader.clock_source(value)
    return reference(reader, ref["contract"], ref["field"], value, path)


def required(reader, start, contract, purpose, document, groups=A2_GROUPS, start_groups=None, context=None):
    """T-A2: 節点の必須入力の義務。各行の欄の実例を、展開の T-REF の行で到達先まで解き、到達先の契約・用途に
    同じ区分の行があればそこもたどる (Local(q) は観測の B・K・読み方・法則・route・原報告・監視・origin まで、
    History は prior の A* から前の系列へ、前の C・前の I は前の Q* へ)。start_groups は出発の節点に当てる区分
    (既定は groups と同じ。q 自身の /inputs/* を「前の I」として要らないなら Local・History だけを渡す)。
    返すのは Obligation の列 (Point に潰さない。`points_of` で射影)。"""
    out, queue, seen = [], [(start, contract, purpose, document, context, start_groups or groups)], set()
    while queue:
        start, contract, purpose, document, context, applied = queue.pop()
        contexts = _observation_context(reader, document)
        # 同じ B に別の欄 (宣言した input_points など) から先に届いても、観測の対の文脈を失わない
        by_point = {_single(document, path): ctx for path, ctx in contexts.items()}
        covered, instances = set(), {}
        for group in applied:
            for row in _A2.get((group, contract, purpose), ()):
                expansion = row["expansion"]
                ref = _REF_BY_ID.get(expansion) if expansion != "-" else None
                element = ref["condition"].get("element") if ref is not None and hasattr(ref["condition"], "items") else None
                for path, value in _walk(document, row["field"], element=element):
                    if ref is None:
                        out.append(Obligation(row["id"], start, contract, purpose, row["field"], path, value, None,
                                              "-", "-", "E"))
                        continue
                    instances.setdefault(path, row["id"])
                    applies = _condition(ref, document, contexts.get(path, context))
                    if applies is None:
                        continue
                    target = _required_target(ref, reader, value, path)
                    target_context = contexts.get(path) or by_point.get(target) or context
                    if target is None:
                        covered.add(path)
                        out.append(Obligation(row["id"], start, contract, purpose, row["field"], path, value, None,
                                              "-", "-", ref["role"], applies[1]))
                        continue
                    if not _target_ok(ref, reader, target):
                        continue
                    covered.add(path)
                    try:
                        target_contract, target_purpose = _decided_purpose(reader, target, ref)
                    except Unsupported:
                        if ref["role"] in ("U", "UE"):
                            raise
                        # E の参照 (宣言した input_points など) は「要る Point」で足り、先はたどらない。用途は決めない
                        target_contract, target_purpose = reader.contract_of(target), UNDECIDED
                    out.append(Obligation(row["id"], start, contract, purpose, row["field"], path, value, target,
                                          target_contract, target_purpose, ref["role"], applies[1]))
                    if (target, target_purpose) in seen or target_purpose in (EXTERNAL, UNDECIDED):
                        continue
                    if ref["role"] not in ("U", "UE"):
                        continue   # E の展開 (宣言した input_points・前の I など) は「その Point が要る」まで。先は型つきの道 (U/UE) で
                    if any((g, target_contract, target_purpose) in _A2 for g in groups):
                        seen.add((target, target_purpose))
                        _c, body = reader.document(target)
                        queue.append((target, target_contract, target_purpose, body, target_context, groups))
        # 宣言した参照の実例に、どの展開の行も当たらない (到達先の契約が表の条件に合わない等): 黙って落とさない
        # (構造の検査 K1b が見つけた穴: Q* の trigger を別の契約の記録に差し替えても通っていた、2026-10-22)
        unmatched = sorted(p for p in instances if p not in covered)
        if unmatched:
            raise Unsupported(f"{contract} [{purpose}]: no T-A2 expansion applies to {unmatched[0]} ({instances[unmatched[0]]})")
    return tuple(out)


def points_of(obligations) -> frozenset:
    """義務の列を Point の集合へ射影する (照合の後で C や I に使う)。"""
    return frozenset(ob.target for ob in obligations if ob.target is not None)
