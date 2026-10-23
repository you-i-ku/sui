"""規則の原子の評価器 — 表の 1 比較を機械が実行する (規則の正本 `src/sui/fb_rules.md` の表記規約、紙 F-b v0.35 Z25・Z28)。

T-A1 の照合関係と T-REF の `assert` は、原子 `{id, left, rel, right?, on_fail, when?}` の配列。被演算子は 3 種:
記録の欄 `"REC:/pointer"`、証拠の束縛 `{from, where, select, path}`、導出 `{derive, args, path?}` (葉に `{literal}`)。
関係語は 9 つ (present / absent / equal / not_equal / unique / le / lt / member_of / subset_of)。ここはその文法**だけ**を読む
(ゆう 2026-10-22 11:08「本質的に同じ仕組みならいい」: 評価器 1 つ・壊す生成器 1 つ。一覧表の規約を読む 2 つ目の通訳は作らない)。

- 値を作る (導出・効果) と、比べて分類する (関係語・on_fail) を分ける。導出は値を返すだけで落とさない。読めなかった値は
  `Missing` (例外でなく値。present が落ちる形)。独立に確かめた不在だけが `ABSENT`
- 比較の前提が読めなければその比較は blocked (成功の印を付けない。分類は対になる *-PRESENT の原子が持つ)
- 導出の名前は生成物 `DERIVATIONS` の 75 名に閉じる。実装の辞書 `DERIVATIONS` に無い名前は「未接続 = 不足」で、成功や空集合に
  落とさない。効果 `effect(name, record)` は実行の場所で捕捉した実値 (`Env.effects`) だけを返す (表の期待値から作らない)
"""

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction

from . import _fb_rules as _R
from ._fb_wire import dumps as _dumps

SHORTAGE, MISMATCH, FORBIDDEN = "不足", "不適合", "使用の禁止"   # on_fail の 3 語 (表記規約)
RELATIONS = frozenset(_R.RELATION_VOCABULARY)
# 証拠の略記 → TargetEvidence の集合 (表記規約: EW: は executions、EH: は executions の reports の側、EI: は intervals、
# EA: は acquisitions。生成物 EVIDENCE_COLLECTIONS と同じ対応。uses は束縛の from="uses" で選ぶ)
_EVIDENCE = {"EW": "executions", "EH": "executions", "EI": "intervals", "EA": "acquisitions"}
assert all(prefix in _R.EVIDENCE_COLLECTIONS[collection] for prefix, collection in _EVIDENCE.items())


class Missing:
    """読めなかった値 (必要な読取りが成立しない)。例外にしない: present が落ちる形で関係語に渡る。
    code / need は不足の返し方の手がかり (A4 の写像: capability の不足 = algorithm_unavailable、証拠の不足 = prerequisite_unavailable)。
    導出が分かる時だけ付ける。無ければ評価器の既定。"""
    __slots__ = ("reason", "code", "need")

    def __init__(self, reason, code=None, need=None):
        self.reason, self.code, self.need = reason, code, need

    def __repr__(self):
        return f"Missing({self.reason!r})"


class Mismatch(Missing):
    """導出が確かめた不適合 (読めた記録が求めた種類・枝でない、など)。不足に落とさない。code は理由の語 (無ければ原子の code)。"""


class Multiple(Mismatch):
    """select=one がちょうど 1 件でない (複数): 確定した不適合。辞書順や最初の 1 件へ縮めない。"""


class _Absent:
    __slots__ = ()

    def __repr__(self):
        return "ABSENT"


ABSENT = _Absent()   # 独立に確認した不在 (absent を満たす唯一の値)


@_dataclass(frozen=True)
class Quantified:
    """証拠の束縛 select=all / any の結果。関係語は要素ごとに当て、all は全称、any は存在量化 (空は成功にしない)。"""
    kind: str
    values: tuple


class Instances(list):
    """`/*` を含む欄の実例の列 (配列の要素ごとの値、順を保つ)。値としての配列 (有理数の [分子, 分母] など) と区別するための型:
    2 項の関係語は実例の列には要素ごとに当てる (「同じ配列の兄弟欄は同じ要素で対応する」、表記規約)。"""


class Unknown(Exception):
    """原子の文法の外 (未知の関係語・被演算子の形・when の条件)。真/偽と仮定せず止める。"""


@_dataclass(frozen=True)
class Outcome:
    """原子 1 つの結果。state は pass / fail / blocked / skipped。classification は fail の分類 (on_fail、Multiple は不適合)。
    hint は不足の返し方の手がかり (code, need) か None (導出が Missing に付けたもの)。"""
    id: str
    state: str
    classification: str | None
    detail: str
    hint: tuple | None = None
    code: str | None = None   # 原子が持つ理由の語 (公開の語彙、紙 A4。表の係 11 通目: 原子に明記、既定値で埋めない)


class AtomFailure(Exception):
    """`check` が最初に落ちた原子で上げる。classification は 不足 / 不適合 / 使用の禁止。"""

    def __init__(self, outcome: Outcome):
        self.outcome = outcome
        super().__init__(f"{outcome.id}: {outcome.state} ({outcome.classification}) {outcome.detail}")


DERIVATIONS: dict = {}   # 名前 → callable(env, *resolved_args) → 値 | Missing。名前は生成物 DERIVATIONS に閉じる (§3-1)
RUNTIME = "runtime"      # 原子の phase (ATOM_PROTOCOL v3): runtime だけを本番で実行する。test は試験の側
LEXICAL = frozenset(_R.ATOM_PROTOCOL["environment"]["lexical"]) | {"CALL", "BINDINGS"}   # 照合の字句の名前 (保存の欄ではない)


def derivation(name):
    """導出の実装を登録する飾り。名前は生成物の 75 名のどれか (それ以外は登録できない: 表に無い名前を実装が増やさない)。"""
    if name not in _R.DERIVATIONS:
        raise KeyError(f"{name} is not a derivation of the rule table")

    def register(fn):
        DERIVATIONS[name] = fn
        return fn
    return register


class Env:
    """1 回の評価の主語: 記録名 → (Point か None, 文書)、独立の観測 (TargetEvidence か None)、読み手、捕捉した効果。
    文書は `_fb_uses.Reader.document` の形 (本文 + 外側の欄)。effects は (名前, Point) → 実値 (実行の場所で置く)。"""

    def __init__(self, records, *, evidence=None, reader=None, effects=None, stages=(), registry=None, compiler=None,
                 replays=None, use_view=None):
        _load()
        self.records = dict(records)
        self.evidence = evidence
        self.reader = reader
        self.effects = effects if effects is not None else {}
        self.stages = tuple(stages)       # 今の認証の段階 (T-A1 の適用段階の語。when の stage が見る)
        self.registry = registry          # 実行の registry (導出 registry が保存 key と突き合わせる)
        self.compiler = compiler          # 評価の頭の compiler (compiler_field の source)。入口 U では None
        self.replays = replays if replays is not None else {}   # Q* の Point → 一次事実からの再計算 (導出 replay_result の値)
        self.use_view = use_view          # 当該操作の固定根 Xuse (入口 U は今の Q* の数値の像、評価の準備は compiler の見える範囲)
        self._memo = {}

    def document(self, name):
        found = self.records.get(name)
        return None if found is None else found[1]

    def point(self, name):
        found = self.records.get(name)
        return None if found is None else found[0]

    def point_of(self, value):
        """束縛された記録の文書 (同じ object) から元の Point。Point の文字列ならそれ。対応が無ければ None。"""
        if isinstance(value, str) and value.startswith("sha256:"):
            return value
        for point, document in self.records.values():
            if document is value:
                return point
        return None


def _load():
    """導出の実装 (`_fb_derivations`) を 1 度だけ読み込んで DERIVATIONS に登録させる。"""
    if not DERIVATIONS:
        from . import _fb_derivations  # noqa: F401 — 登録の副作用のため


# ---------------------------------------------------------------- 被演算子

def _json(value):
    """観測の DTO (dataclass) を JSON の形に。すでに JSON ならそのまま。"""
    if isinstance(value, Missing):
        return value   # 読めなかった値は値のまま運ぶ (理由を失わない。present が拾う)
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "items"):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (frozenset, set)):
        return sorted(_json(v) for v in value)
    if isinstance(value, _Fraction):
        return [value.numerator, value.denominator]
    from .f import _encode
    from .f_update2 import _Handle
    if isinstance(value, _Handle):
        return repr(value)   # 工場の識別: 同じ物かどうかだけを表す印 (発行の番号つき、名札の文字列で作れない)
    try:
        return _encode(value)
    except Exception:   # noqa: BLE001
        from dataclasses import fields, is_dataclass
        if is_dataclass(value):   # 工場の識別を含む観測: 欄ごとに (工場の印 seal は運ばない)
            return {f.name: _json(getattr(value, f.name)) for f in fields(value) if f.name != "seal"}
        return repr(value)   # 符号化できない値は文字列で (比較には使わない)


def _walk(document, pointer):
    from ._fb_uses import Malformed, _walk as walk
    try:
        return walk(document, pointer)
    except Malformed as exc:
        return Missing(str(exc))


def _instances(found, pointer):
    """欄の実例の列を値に: `*` を含む欄は列 (順を保つ)、含まなければ 1 つ (無ければ Missing)。"""
    if isinstance(found, Missing):
        return found
    if "*" in pointer:
        return Instances(value for _path, value in found)
    if len(found) == 0 and pointer.endswith("?"):
        return None   # 宣言した nullable の欄の合法な null (値として存在する。表記規約)
    if len(found) != 1:
        return Missing(f"{pointer}: {len(found)} instances")
    return found[0][1]


def _evidence_root(env, prefix):
    """観測の集合を JSON の列に。EH: は各実行の reports を、その実行の work_id を添えて平らにした列。"""
    if env.evidence is None:
        return Missing(f"{prefix}: no independent observations are held")
    collection = _EVIDENCE.get(prefix)
    if collection is None:
        return Missing(f"{prefix}: not an evidence collection")
    items = _json(list(getattr(env.evidence, collection)))
    if prefix == "EH":
        items = [{**report, "work_id": item["work_id"]} for item in items for report in item.get("reports", ())]
    return items


def _at(value, path):
    """導出の結果や観測の 1 件から path の欄。`/*` で始まる path は列の各要素 (結果が列の時)。"""
    document = _json(value)
    if path.startswith("/*"):
        return _instances(_walk({"items": document}, "/items" + path), path)
    return _instances(_walk(document, path), path)


def resolve(env, operand):
    """被演算子を値に。記録の欄 → 文書の欄 (空の Pointer は本文全体、`EW:` 等の空は観測の集合)、証拠の束縛 → 選んだ観測の欄、
    導出 → DERIVATIONS[name](env, *args)、literal → その値。読めなければ Missing (例外で落とさない)。"""
    if isinstance(operand, str):
        if ":" not in operand:
            raise Unknown(f"operand {operand!r} is not REC:pointer")
        name, pointer = operand.split(":", 1)
        if name in _EVIDENCE:
            root = _evidence_root(env, name)
            if isinstance(root, Missing) or pointer == "":
                return root
            return _at(root, "/*" + pointer)
        document = env.document(name)
        if document is None:
            return Missing(f"{name}: record is not bound")
        if pointer == "":
            return document
        return _instances(_walk(document, pointer), pointer)
    if not hasattr(operand, "items"):
        raise Unknown(f"operand {operand!r} has no known form")
    if "literal" in operand:
        return _json(operand["literal"])
    if "derive" in operand:
        return _derive(env, operand)
    if "from" in operand:
        return _bind(env, operand)
    raise Unknown(f"operand {dict(operand)!r} has no known form")


def _derive(env, operand):
    name = operand["derive"]
    fn = DERIVATIONS.get(name)
    if fn is None:
        if name not in _R.DERIVATIONS:
            raise Unknown(f"derivation {name!r} is not in the rule table")
        return Missing(f"derivation {name} is not connected")
    args = [resolve(env, a) for a in operand.get("args", ())]
    for a in args:
        if isinstance(a, Missing):
            return a
    try:
        key = (name, _dumps(_json(args)))
    except Exception:   # noqa: BLE001 — 符号化できない引数はメモ化しない
        key = None
    if key is not None and key in env._memo:
        value = env._memo[key]
    else:
        value = fn(env, *args)
        if key is not None:
            env._memo[key] = value
        _run_consumer_blocks(env, name, args)
    path = operand.get("path")
    if path and not isinstance(value, Missing):
        if isinstance(value, str) and value.startswith("sha256:"):
            # 導出が記録の Point を返した (via・point_of・first_report): path はその記録の文書の欄 (読み手で読む)
            if env.reader is None:
                return Missing(f"{name}: no reader to read {value}")
            _contract, value = env.reader.document(value)
        value = _at(value, path)
    return value


def _bind(env, operand):
    """証拠の束縛: from の観測から where (全一致) で絞り、select で 1 件 / 全部 / いずれか、path でその欄。"""
    source = operand["from"]
    prefix = {"executions": "EW", "uses": "EW", "intervals": "EI", "acquisitions": "EA"}.get(source, source)
    if source in ("EW", "EH"):
        prefix = source
    root = _evidence_root(env, prefix)
    if isinstance(root, Missing):
        return root
    if source == "uses":
        root = _json(list(env.evidence.uses))
    chosen = []
    for item in root:
        ok = True
        for pointer, expected in operand.get("where", {}).items():
            want = resolve(env, expected) if isinstance(expected, str) and ":" in expected and not expected.startswith("/") \
                else (resolve(env, expected) if hasattr(expected, "items") else expected)
            if isinstance(want, Missing):
                return want
            have = _instances(_walk(item, pointer), pointer)
            if isinstance(have, Missing) or _dumps(_json(have)) != _dumps(_json(want)):
                ok = False
                break
        if ok:
            chosen.append(item)
    select, path = operand.get("select", "one"), operand.get("path", "")

    def project(item):
        return item if path == "" else _at(item, path)
    if select == "one":
        if len(chosen) == 0:
            return Missing(f"{source} {dict(operand.get('where', {}))}: no observation")
        if len(chosen) > 1:
            return Multiple(f"{source}: {len(chosen)} observations match")
        return project(chosen[0])
    if select in ("all", "any"):
        return Quantified(select, tuple(project(item) for item in chosen))
    raise Unknown(f"select {select!r}")


# ---------------------------------------------------------------- 関係語

def _canon(value):
    return _dumps(_json(value))


def _has_missing(value):
    if isinstance(value, Missing):
        return True
    if isinstance(value, Quantified):
        return any(_has_missing(v) for v in value.values)
    if isinstance(value, (list, tuple)):
        return any(_has_missing(v) for v in value)
    return False


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, _Fraction)):
        if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value):
            return _Fraction(value[0], value[1])   # 有理数の保存形 [分子, 分母]
        return None
    return value


def _compare(rel, left, right):
    """2 項の関係語を値に当てる。返すのは True / False / Missing (比較の前提が読めない = blocked)。
    実例の列 (Instances) は要素ごと: 両側が列なら同じ長さで対応する要素どうし、片側だけなら各要素とその値。"""
    if _has_missing(left) or _has_missing(right):
        return Missing("operand not readable")
    if rel in ("equal", "not_equal", "le", "lt"):
        if isinstance(left, Instances) and isinstance(right, Instances):
            if len(left) != len(right):
                return False
            return all(_compare(rel, a, b) for a, b in zip(left, right))
        if isinstance(left, Instances):
            return all(_compare(rel, a, right) for a in left)
        if isinstance(right, Instances):
            return all(_compare(rel, left, b) for b in right)
    if rel in ("equal", "not_equal"):
        same = _canon(left) == _canon(right)
        return same if rel == "equal" else not same
    if rel in ("le", "lt"):
        a, b = _number(left), _number(right)
        if a is None or b is None:
            return False   # 同じ尺度の既知数値でなければ成立しない (整数の前後だけで比べない)
        return a <= b if rel == "le" else a < b
    if rel == "member_of":
        if not isinstance(right, (list, tuple)):
            return False
        return _canon(left) in {_canon(v) for v in right}
    if rel == "subset_of":
        if _is_interval_set(left) or _is_interval_set(right):
            return _interval_covers(right, left)
        if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
            return False
        pool = {_canon(v) for v in right}
        return all(_canon(v) in pool for v in left)
    raise Unknown(f"relation {rel!r}")


def _is_interval_set(value):
    return hasattr(value, "items") and set(value) == {"interval_set"}


def _interval_covers(outer, inner):
    """区間集合の包含 (導出 interval_set の値どうし): 同じ時計で、端点の開閉を含めて inner の全点が outer に入る。"""
    from ._f_count import Span
    if not (_is_interval_set(outer) and _is_interval_set(inner)):
        return False

    def span(value):
        v = value["interval_set"]
        return Span(clock=_canon(v["clock"]).decode("utf-8"), start_ns=v["start_ns"], end_ns=v["end_ns"],
                    closure=v["closure"])
    return span(outer).covers(span(inner))


def _relation(atom, left, right):
    rel = atom["rel"]
    if rel not in RELATIONS:
        raise Unknown(f"relation {rel!r}")
    if rel == "present":
        if isinstance(left, Quantified):
            return bool(left.values) and not _has_missing(left)
        return not _has_missing(left) and left is not ABSENT
    if rel == "absent":
        return left is ABSENT
    if rel == "unique":
        if _has_missing(left):
            return Missing("operand not readable")
        if not isinstance(left, (list, tuple)):
            return False
        seen = [_canon(v) for v in left]
        return len(seen) == len(set(seen))
    if isinstance(left, Quantified):
        results = [_compare(rel, v, right) for v in left.values]
    elif isinstance(right, Quantified):
        results = [_compare(rel, left, v) for v in right.values]
    else:
        return _compare(rel, left, right)
    if not results:
        return False   # 量化の空列は成功にしない (必須の 1 件を空列で全称成功へ逃がさない)
    if any(isinstance(r, Missing) for r in results):
        return Missing("operand not readable")
    kind = left.kind if isinstance(left, Quantified) else right.kind
    return all(results) if kind == "all" else any(results)


# ---------------------------------------------------------------- when

def _applies(env, when):
    """when の条件。ATOM_PROTOCOL v3 = 述語 {left, rel, right?} の配列 (全部が真で適用、空は真、偽は非適用、読めなければ
    `Missing` を返す = blocked、未知の構文は止める)。旧の辞書の形 (nonnull / is_null / generation / stage / claim_kind) も読む。"""
    if when is None or when is True:
        return True
    if isinstance(when, (list, tuple)):
        for predicate in when:
            if not hasattr(predicate, "items") or set(predicate) - {"left", "rel", "right"}:
                raise Unknown(f"when predicate {predicate!r}")
            left = resolve(env, predicate["left"])
            right = resolve(env, predicate["right"]) if "right" in predicate else None
            result = _relation(predicate, left, right)
            if isinstance(result, Missing):
                return Missing(f"when {predicate['rel']}: {result.reason}")
            if not result:
                return False
        return True
    for key, expected in when.items():
        if key in ("nonnull", "is_null"):
            value = resolve(env, expected)
            if isinstance(value, Missing):
                raise Unknown(f"when {key}: {expected} is not readable ({value.reason})")
            if (value is None) == (key == "nonnull"):
                return False
        elif key == "generation":
            from ._fb_uses import contract_name
            value = resolve(env, "Reading:/generation/contract")
            if isinstance(value, Missing):
                raise Unknown(f"when generation: the reading is not bound ({value.reason})")
            if contract_name(value) != expected:
                return False
        elif key == "stage":   # 一覧表の stage: 実操作の段階 (T-A1 の適用段階の語) と一致する時だけ
            if expected not in env.stages:
                return False
        elif key == "claim_kind":   # 一覧表の item_kind (B.report の報告の枝 = Claim の item.kind、表記規約)
            value = resolve(env, "Claim:/item/kind")
            if isinstance(value, Missing):
                raise Unknown(f"when item_kind: the claim is not bound ({value.reason})")
            if value != expected:
                return False
        else:
            raise Unknown(f"when {key!r}")
    return True


# ---------------------------------------------------------------- 一覧の本番の原子 (導出の呼出しごと)

_CONSUMERS = None   # 導出の名前 → それを consumers に持つ一覧ブロックの名前の列 (生成物から 1 度だけ)
_SCOPE_ALIASES = {"Q": "Q*", "A": "A*", "R": "R*"}   # 導出の宣言の引数名 → SCOPES の記録名 (表記規約の略記)


def _parameters(consumer):
    """導出の宣言 `(Q,Xnum)→…` の引数名の列 (宣言に無ければ空)。"""
    import re
    found = re.match(r"\(([^)]*)\)", _R.DERIVATIONS.get(consumer, ""))
    return [p.strip() for p in found.group(1).split(",")] if found else []


def _run_consumer_blocks(env, consumer, args):
    """導出 consumer の実際の呼出し 1 回に、それを consumers に持つ一覧ブロックの本番の原子 (phase: runtime) を回す
    (ATOM_PROTOCOL v3 の evaluation: CALL と SCOPES を束ね、条件・each を一次の出どころから展開して原子を当てる)。
    戻り値の照合 (capture・coverage、phase: test) は回さない。落ちた原子は AtomFailure で上げる (その原子の on_fail で返す)。"""
    global _CONSUMERS
    if _CONSUMERS is None:
        found = {}
        for name, block in _R.ENUMERATIONS.items():
            for owner in block["consumers"]:
                found.setdefault(owner, []).append(name)
        _CONSUMERS = found
    blocks = _CONSUMERS.get(consumer)
    if not blocks:
        return
    call = {"consumer": consumer, "arguments": _json(list(args)), "stage": _call_stage(env.stages)}
    # 呼出しは 1 回ごとに別の束縛: 外の CALL・ITEM 等の字句の名前を見せず、SCOPES の記録は実引数から束ねなおす
    # (ATOM_PROTOCOL v3 の evaluation「bind actual CALL and SCOPES」。前の系列の closure_keys(前の Q) の中の Q* は前の Q)
    outer = {k: v for k, v in env.records.items() if k not in LEXICAL}
    for param, arg in zip(_parameters(consumer), args):
        name = _SCOPE_ALIASES.get(param, param)
        if name in outer and not isinstance(arg, Missing):
            if isinstance(arg, str) and arg.startswith("sha256:") and env.reader is not None:
                try:
                    outer[name] = (arg, env.reader.document(arg)[1])
                except Exception:   # noqa: BLE001 — 読めない実引数は束ねない (その記録を読む原子が不足で落ちる)
                    outer.pop(name, None)
            elif hasattr(arg, "items"):
                outer[name] = (env.point_of(arg), arg)
    base = Env(outer, evidence=env.evidence, reader=env.reader, effects=env.effects, stages=env.stages,
               registry=env.registry, compiler=env.compiler, replays=env.replays, use_view=env.use_view)
    base._memo = env._memo
    scope = _with(base, "CALL", call)
    for name in blocks:
        block = _R.ENUMERATIONS[name]
        if not _has_runtime(block.get("prelude", ())) and not any(_item_has_runtime(i) for i in block["items"]):
            continue   # 本番の原子の無いブロック (全部が施工の確認) は条件も each も展開しない
        for block_env in _expand(scope, block.get("when"), block.get("each"), name):
            _each_witness(block_env, lambda bound: _run_block_body(bound, block))


def _run_block_body(env, block):
    """1 つの束縛でのブロックの中身: ブロックの前置き → 各項目 (条件・each・前置き・原子)。"""
    check(block.get("prelude", ()), env)
    for item in block["items"]:
        if not _item_has_runtime(item):
            continue
        for item_env in _expand(env, item.get("when"), item.get("each"), item["id"]):
            _each_witness(item_env, lambda bound: check((*item.get("prelude", ()), *item["atoms"]), bound))


def _each_witness(env, run):
    """any の証人の群なら候補を順に試し 1 つでも全部通れば成功 (無ければ最初の失敗)、ふつうの束縛なら 1 回。"""
    if not isinstance(env, _AnyWitness):
        run(env)
        return
    first = None
    for candidate in env.envs:
        try:
            run(candidate)
            return
        except AtomFailure as exc:
            first = first or exc
    raise first


def _has_runtime(atoms):
    return any(atom.get("phase", RUNTIME) == RUNTIME for atom in atoms)


def _item_has_runtime(item):
    return _has_runtime((*item.get("prelude", ()), *item["atoms"]))


def _call_stage(stages):
    """CALL の stage = 実際の操作の段階 1 つ (ATOM_PROTOCOL v3 の environment.CALL.stage)。その Q* が評価の頭として認証されて
    いれば「評価の頭」、そうでなければ今の再構成の段階 (認証の段階の列の先頭)。列のまま入れない (一覧の条件
    `CALL:/stage equal 評価の頭` が列との比較で常に偽になり、評価の頭の原子が回らなかった。K11-B の評価の頭の道で見つけた)。"""
    head = "評価の頭"
    if head in stages:
        return head
    return stages[0] if stages else None


def _with(env, name, document):
    """env に字句の名前 (CALL・ITEM 等) を 1 つ束ねた写し。読み手・効果・段階・メモは共有する。影を作らない。"""
    if name in env.records:
        raise Unknown(f"lexical name {name} shadows a binding")
    out = Env({**env.records, name: (None, document)}, evidence=env.evidence, reader=env.reader, effects=env.effects,
              stages=env.stages, registry=env.registry, compiler=env.compiler, replays=env.replays, use_view=env.use_view)
    return out


def _expand(env, when, each, where):
    """条件 (偽 = 非適用、読めない = 不足) と each (bind・in・select、外から内へ) で束ねた env の列。
    select one の 0 件は不足・複数は不適合 (proof_mismatch)、any は群の全部を 1 つの証人に課す (`_AnyWitness`)。"""
    binds = {spec["bind"] for spec in each or ()}
    inner = [p for p in when or () if _names(p) & binds] if isinstance(when, (list, tuple)) else []
    outer = [p for p in when or () if not _names(p) & binds] if isinstance(when, (list, tuple)) else when
    applies = _applies(env, outer)   # 外の束縛だけの条件は each の前に (偽なら内側の出どころを読まない)
    if isinstance(applies, Missing):
        raise AtomFailure(Outcome(f"{where}:when", "blocked", SHORTAGE, applies.reason))
    if not applies:
        return []
    envs = [env]
    for spec in each or ():
        nxt = []
        for current in envs:
            source = resolve(current, spec["in"])
            if isinstance(source, Missing):
                raise AtomFailure(Outcome(f"{where}:each", "blocked", SHORTAGE, source.reason, _hint(source)))
            elements = list(source.values) if isinstance(source, Quantified) else list(source)
            if spec["select"] == "one" and len(elements) != 1:
                if not elements:
                    raise AtomFailure(Outcome(f"{where}:each", "blocked", SHORTAGE, f"{spec['bind']}: no instance"))
                raise AtomFailure(Outcome(f"{where}:each", "fail", MISMATCH,
                                          f"{spec['bind']}: {len(elements)} instances", None, "proof_mismatch"))
            if spec["select"] == "any" and not elements:
                raise AtomFailure(Outcome(f"{where}:each", "blocked", SHORTAGE, f"{spec['bind']}: no witness"))
            bound = [_with(current, spec["bind"], element) for element in elements]
            if spec["select"] == "any" and spec is not each[-1]:
                raise Unknown(f"{where}: select any must be the innermost each (one witness for the enclosed group)")
            nxt.extend([_AnyWitness(bound)] if spec["select"] == "any" else bound)
        envs = nxt
    if inner:   # 新しく束ねた名前を使う条件は、その束縛ごとに (偽ならその出現は非適用、読めなければ不足)
        kept = []
        for bound in envs:
            if isinstance(bound, _AnyWitness):
                bound.envs = [e for e in bound.envs if _inner_applies(e, inner, where)]
                kept.append(bound)
            elif _inner_applies(bound, inner, where):
                kept.append(bound)
        envs = kept
    return envs


def _inner_applies(env, predicates, where):
    applies = _applies(env, predicates)
    if isinstance(applies, Missing):
        raise AtomFailure(Outcome(f"{where}:when", "blocked", SHORTAGE, applies.reason))
    return applies


def _names(node):
    """被演算子の中の記録・字句の名前 (`NAME:/pointer` の NAME) の集合。"""
    found = set()
    if isinstance(node, str):
        if ":" in node:
            found.add(node.split(":", 1)[0])
    elif hasattr(node, "items"):
        if "literal" not in node:
            for value in node.values():
                found |= _names(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            found |= _names(value)
    return found


class _AnyWitness:
    """select any: 囲む原子の群の全部を同じ証人 1 つに課す。候補を全部試し、1 つでも全部通れば成功、無ければ最初の失敗。"""

    def __init__(self, envs):
        self.envs = envs


# ---------------------------------------------------------------- 評価

MUTATE = None   # 試験の生成器 (K11) が差し込む口: (atom, left, right) → (left, right)。本番では None。関係を 1 つだけ壊して
# 「分類どおりに落ちるか」を公開の入口で見るための、評価器の中の唯一の継ぎ目 (壊すのは値、関係語の意味は壊さない)


def evaluate(atoms, env) -> list:
    """原子の配列を順に当てて、原子ごとの Outcome を返す (落ちても止めない。全部の結果が要る検査用)。"""
    out = []
    for atom in atoms:
        if atom.get("phase", RUNTIME) != RUNTIME:
            continue   # 施工の確認 (phase: test) は試験の側で回す (ゆう 2026-10-23、ATOM_PROTOCOL v3)。本番では実行しない
        if atom.get("each"):
            out.append(_evaluate_each(atom, env))
            continue
        try:
            applies = _applies(env, atom.get("when"))
            if isinstance(applies, Missing):
                out.append(Outcome(atom["id"], "blocked", None, applies.reason, None, atom.get("code")))
                continue
            if not applies:
                out.append(Outcome(atom["id"], "skipped", None, "when is false"))
                continue
            left = resolve(env, atom["left"])
            right = resolve(env, atom["right"]) if "right" in atom else None
        except AtomFailure as exc:   # 導出の呼出しで回した一覧の本番の原子が落ちた (その原子の分類で返す)
            out.append(exc.outcome)
            continue
        if MUTATE is not None:
            left, right = MUTATE(atom, left, right)
        if isinstance(left, Mismatch) or isinstance(right, Mismatch):
            which = left if isinstance(left, Mismatch) else right
            out.append(Outcome(atom["id"], "fail", MISMATCH, which.reason, None, which.code or atom.get("code")))
            continue
        result = _relation(atom, left, right)
        if isinstance(result, Missing):
            out.append(Outcome(atom["id"], "blocked", None, result.reason, _hint(left, right), atom.get("code")))
        elif result:
            out.append(Outcome(atom["id"], "pass", None, ""))
        else:
            detail = _detail(left, right) if atom["rel"] != "present" else _reason(left)
            out.append(Outcome(atom["id"], "fail", atom["on_fail"], detail, _hint(left, right), atom.get("code")))
    return out


def _evaluate_each(atom, env):
    """原子の each: 束ねた出現ごとに同じ原子を当てる (all は全部、any は 1 つの証人)。最初の落ちた出現の結果を返す。"""
    single = {k: v for k, v in atom.items() if k != "each"}
    try:
        envs = _expand(env, None, atom["each"], atom["id"])
    except AtomFailure as exc:
        return exc.outcome
    failures = []
    for bound in envs:
        candidates = bound.envs if isinstance(bound, _AnyWitness) else [bound]
        results = [evaluate([single], candidate) for candidate in candidates]
        found = [r[0] for r in results if r and r[0].state not in ("pass", "skipped")]
        if isinstance(bound, _AnyWitness):
            if not any(r and r[0].state in ("pass", "skipped") for r in results):
                failures.append(found[0] if found else Outcome(atom["id"], "blocked", SHORTAGE, "no witness"))
        elif found:
            failures.append(found[0])
    if failures:
        return failures[0]
    return Outcome(atom["id"], "pass", None, "")


def _hint(*values):
    """落ちた原子の値に Missing があれば、その (code, need) の手がかり (導出が付けたもの)。"""
    for value in values:
        found = _first_missing(value)
        if found is not None and (found.code or found.need):
            return (found.code, found.need)
    return None


def _first_missing(value):
    if isinstance(value, Missing):
        return value
    if isinstance(value, Quantified):
        value = value.values
    if isinstance(value, (list, tuple)):
        for v in value:
            found = _first_missing(v)
            if found is not None:
                return found
    return None


def _reason(value):
    if isinstance(value, Missing):
        return value.reason
    if isinstance(value, Quantified):
        inner = [v for v in value.values if isinstance(v, Missing)]
        return inner[0].reason if inner else "empty"
    if isinstance(value, (list, tuple)):
        inner = [v for v in value if isinstance(v, Missing)]
        return inner[0].reason if inner else "not present"
    return "not present"


def _detail(left, right):
    try:
        return f"{_canon(left).decode()[:120]} vs {_canon(right).decode()[:120]}"
    except Exception:   # noqa: BLE001
        return "values differ"


def check(atoms, env) -> tuple:
    """原子を順に当て、最初に落ちた原子で AtomFailure を上げる。blocked (前提が読めない) は不足として上げる。
    通れば通った原子の id の列 (印にする側はこれを使う。印は実行の結果であって代用ではない)。"""
    passed = []
    for outcome in evaluate(atoms, env):
        if outcome.state == "pass":
            passed.append(outcome.id)
        elif outcome.state == "fail":
            raise AtomFailure(outcome)
        elif outcome.state == "blocked":
            raise AtomFailure(Outcome(outcome.id, "blocked", SHORTAGE, outcome.detail, outcome.hint, outcome.code))
    return tuple(passed)
