"""F-b 段 3 の構造と性質の検査 — 分母は紙 §6-11 の機械可読の表 (生成物 `sui._fb_rules`)、期待値は実装から取らない
(紙 F-b v0.32 Z17〜Z24、開発フローの紙 ①-b「紙の表を写さない道具」・④)。

レビューの系統 A (派生物・印・名札を信じた) と B (列挙漏れ) を、反例を 1 つずつ足すのでなく、表の **規則 ID × 欄 ×
入口 × 壊し方** を機械で回して落とす。表はこの file で写さず `_fb_rules` を読む。表をたどる読み手 (`walk`・`required`)
はこの file の中の独立の実装で、`sui._fb_uses` の閉包は使わない (同じ生成器から期待値を作らない)。K1〜K8 は公開の入口だけを
叩く。K7-b・K8 (今の Q* だけ)・K9・K10 は規則の読み手と門を直接呼ぶ部品の検査で、公開の入口の試験とは別に数える (レビュー 7 通目の判定)。
fixture は `tests/test_fb_stage3.py` (試験の係が書く) のものを借りる。

- K1 必須閉包 (T-A2 × 欄): 表から導いた各 Point を 1 つだけ I から外す → unresolved_reference。宣言した X を I に入れない → 拒む
- K1b 欄ごとの参照の差し替え (T-REF の U/UE の欄 × 別の契約の実在の記録): 型違い・対応違いを拒む (FB3-TEST-R6)
- K2 操作と出発点 (T-G6 × 適用方式): 全部の対象別・同時の行が、合法な 1 日の中で表の契約・用途で門を通る (spy) + 継続の門の出発点
- K3 実行の証拠 (T-A1 の系列の項目): 前の系列の独立の観測を 1 つずつ落とす → insufficient。確定した未入場は不適合 (CLASS-R7)
- K4 無関係な記録は結果を変えない (REF-3・E-06)
- K5 固定像の候補集合は Xuse から (G5)
- K6 失敗の分類 (A4)
- K7 ロックの配置 (G6 の最後の行、LOCK-R6)
- K8 A1 の集約 (T-A1 × 段階): Q* ごとに当たる項目が全部印を持つ (印を 1 つ外すと不足)
- K9 表の読み手の読み方 (表の係 2026-10-21 の判定 2-2・2-4、未宣言の枝): ここだけ `sui._fb_uses` の読み手を直接呼ぶ (下の注)
- K10 同時の適用方式 (T-G6「継続を開く」): 主語が 1 つ欠けたら Unresolved (残りで出発点を作らない)

K7-b・K8 (今の Q* だけ)・K9・K10 は誤実装の表 v3 (2026-10-22) で生き残った Z17×3・Z20・Z21・Z22 の行から: どれも公開の
入口では他の守り (A2 の I の検査・台帳の親の検査・同じ settle の保存で進む台帳の版・前の系列の集約) に覆われて見えない
ので、規則の読み手 (`obligations`・`starts_of`・`gate`) と集約の場所をそのまま検査する。
"""

import json
import re
from dataclasses import replace

import pytest

from sui import f, fb_contracts as c, f_contracts as fc
from sui import f_update2 as u
from sui import _fb_rules as rules
from sui import f_facts as ff

from test_fb_stage3 import (   # noqa: F401  (make_rig は fixture)
    make_rig, direct_first, direct_update, save_request, save_copy, fixed_view, result_for, assert_update,
    prepare_adoption, adoption_prepare_inputs, assert_incomplete_preparation, current_evidence, first_claim,
    PublicReader, FIRST, SECOND, ORIGIN, CG, plain,
)
from test_fb_skeleton import contract
from test_fb_stage1 import received


# ---------------------------------------------------------------- 読む道具 (公開の台帳だけ)

def _content(rig, point):
    return rig.read_stored(point)[2].body.content.as_json()


def _record(rig, point):
    return rig.read_stored(point)[2]


def _by_id(rig):
    """記録の識別子 (Ref) → Point。重複があれば試験の前提が崩れているので止める。"""
    out = {}
    for entry in rig.ledger.entries():
        ref = _record(rig, entry.cid).id
        assert ref not in out, f"ref {ref} resolves to more than one point"
        out[ref] = entry.cid
    return out


def _name(contract_ref) -> str:
    return f"{contract_ref.name}/{contract_ref.version}"


def _document(rig, point, by_id):
    """紙 §6-11 の文書: 本文 + 外側の欄 (parents・inputs・basis・about・target) を Point に解決したもの。"""
    header, _salt, record = rig.read_stored(point)
    body = record.body
    document = dict(body.content.as_json())
    from sui.ledger import entry_from_header
    document["parents"] = sorted(entry_from_header(point, header).parents)
    for outer in ("inputs", "basis", "about"):
        refs = getattr(body, outer, None)
        if refs is not None:
            document[outer] = [by_id[ref] for ref in refs]
    if getattr(body, "target", None) is not None:
        document["target"] = body.target
    return _name(body.contract), document


_SEGMENT = re.compile(r"^([^\[\]?]+)(?:\[kind=([^\]]+)\])?(\?)?$")


def walk(document, field, element=None):
    """表の欄 (JSON Pointer: `/*`・`[kind=枝]`・`?`) の実例 [(経路, 値)]。この file の独立の実装。"""
    out = [("", document)]
    segments = field.split("/")[1:]
    last_star = max((i for i, s in enumerate(segments) if s == "*"), default=None)
    for index, segment in enumerate(segments):
        nxt = []
        if segment == "*":
            for path, value in out:
                assert isinstance(value, list), (field, path)
                for i, item in enumerate(value):
                    if element is not None and index == last_star and any(
                            walk(item, rel)[0][1] != expected for rel, expected in element.items()):
                        continue
                    nxt.append((f"{path}/{i}", item))
        else:
            name, kind, optional = _SEGMENT.match(segment).groups()
            for path, value in out:
                assert isinstance(value, dict) and name in value, (field, path, name)
                value = value[name]
                if value is None and optional:
                    continue
                if kind is not None:
                    assert isinstance(value, dict) and "kind" in value, (field, path)
                    if value["kind"] != kind:
                        continue
                nxt.append((f"{path}/{name}", value))
        out = nxt
    return out


def _as_point(rig, value, by_id):
    """欄の値を記録の参照として読む (Point か、記録の Ref)。run・individual の Ref と値は None。"""
    if not isinstance(value, str):
        return None
    if value.startswith("sha256:"):
        return value
    if ":" in value:
        kind, name = value.split(":", 1)
        from sui.ids import Ref, RefKind
        try:
            ref = Ref(RefKind(kind), name)
        except ValueError:
            return None
        if ref.kind in (RefKind.RUN, RefKind.INDIVIDUAL):
            return None
        return by_id.get(ref)
    return None


def _field_kind(contract, field):
    types = getattr(rules, "FIELD_TYPES", {})
    return types.get((contract, field)) or types.get((contract, re.sub(r"\[kind=[^\]]+\]", "", field).replace("?", ""))) or "unknown"


def _condition_ok(row, document, context, rig, by_id, target=None):
    condition = row["condition"]
    if condition is True:
        return True
    if condition == "未確定":
        return False
    for key, expected in condition.items():
        if key == "nonnull" and walk(document, expected)[0][1] is None:
            return False
        if key == "is_null" and walk(document, expected)[0][1] is not None:
            return False
        if key in ("method", "method_not"):
            method = walk(document, "/desc/method")[0][1]
            if (f"{method['name']}/{method['version']}" == expected) != (key == "method"):
                return False
        if key in ("generation", "support_required"):
            assert context is not None and key in context, (row["id"], "context needed")
            if context[key] != expected:
                return False
        if key == "target_contract" and target is not None and _name(_record(rig, target).body.contract) != expected:
            return False
        if key == "item_kind" and target is not None and _content(rig, target)["item"]["kind"] != expected:
            return False
    return True


def _reading_context(rig, reading):
    generation = _content(rig, reading)["generation"]["contract"]
    name = f"{generation['name']}/{generation['version']}"
    return {"generation": name, "support_required": name == "sui.fb.bootstrap_generation/1"}


def _observation_contexts(rig, document):
    out = {}
    try:
        uses = document["desc"]["args"]["observations"]
    except (KeyError, TypeError):
        return out
    for i, use in enumerate(uses):
        out[use["binding"]] = _reading_context(rig, use["reading"])
    return out


_REF_BY_ID = {r["id"]: r for r in rules.T_REF}
_A2 = {}
for _row in rules.T_A2:
    _A2.setdefault((_row["group"], _row["contract"], _row["purpose"]), []).append(_row)
_GROUPS = tuple(dict.fromkeys(r["group"] for r in rules.T_A2))
_PURPOSES = {}
for _row in rules.T_REF:
    _PURPOSES.setdefault(_row["contract"], set()).add(_row["purpose"])


def _target_purpose(rig, ref_row, target):
    if ref_row["target_purpose"] != "-":
        return ref_row["target_purpose"]
    contract = _name(_record(rig, target).body.contract)
    purposes = _PURPOSES.get(contract, set())
    if len(purposes) == 1:
        return next(iter(purposes))
    if contract == "sui.fb.segment_report/1":
        kind = _content(rig, target)["item"]["kind"]
        return "boundary" if kind in ("started", "ended", "route_applied") else "claim"
    return None


def table_required(rig, q, by_id):
    """T-A2 を q から独立にたどる: Local・History は q に、前の C・前の I は前の Q* に (系列の全部)。返すのは
    {Point: {規則 ID}} (どの行が要ったか)。E の展開は「その Point が要る」まで (先は U/UE の道で)。"""
    out = {}
    queue = [(q, "sui.fb.work_requested/1", "update", None, ("Local", "History"))]
    seen = set()
    while queue:
        point, contract, purpose, context, groups = queue.pop()
        _c, document = _document(rig, point, by_id)
        contexts = _observation_contexts(rig, document)
        for group in groups:
            for row in _A2.get((group, contract, purpose), ()):
                ref = _REF_BY_ID.get(row["expansion"]) if row["expansion"] != "-" else None
                element = ref["condition"].get("element") if ref is not None and isinstance(ref["condition"], dict) else None
                for path, value in walk(document, row["field"], element):
                    found_context = contexts.get(value, context) if isinstance(value, str) else context
                    if ref is None or not _condition_ok(ref, document, found_context, rig, by_id):
                        continue
                    target = _as_point(rig, value, by_id)
                    if isinstance(ref["condition"], dict) and ref["condition"].get("resolve") == "clock_declaration_for_run":
                        sources = [e.cid for e in rig.ledger.entries()
                                   if _name(_record(rig, e.cid).body.contract) == "sui.clock.source/1"
                                   and _content(rig, e.cid).get("run") == value]
                        assert len(sources) == 1
                        target = sources[0]
                    if target is None or not _condition_ok(ref, document, found_context, rig, by_id, target):
                        continue
                    out.setdefault(target, set()).add(row["id"])
                    if ref["role"] not in ("U", "UE"):
                        continue
                    target_purpose = _target_purpose(rig, ref, target)
                    target_contract = _name(_record(rig, target).body.contract)
                    if target_purpose is None or (target, target_purpose) in seen:
                        continue
                    if any((g, target_contract, target_purpose) in _A2 for g in _GROUPS):
                        seen.add((target, target_purpose))
                        queue.append((target, target_contract, target_purpose, found_context, _GROUPS))
    out.pop(q, None)
    return out


def _legal_updates(rig):
    """合法な Q* の列 (prior 無し → 有り) と、その証拠・期待の結果。"""
    first, a1, evidence1 = direct_first(rig)
    rig.claim(2)
    rig.drive(lambda: len(rig.requests("belief_update")) == 2)
    second, a2 = rig.adopt(2)
    assert_update(rig, second, a2, SECOND, a1.cid)
    evidence2 = current_evidence(rig)
    return [(first, evidence1, FIRST), (second, evidence2, SECOND)]


# ---------------------------------------------------------------- K1: 必須閉包 (T-A2 × 欄)

@pytest.mark.parametrize("which", ("first", "second"))
def test_K1_every_table_required_record_is_in_I_and_removing_any_one_is_rejected(make_rig, which):
    """K1 (T-A2 の全行 × 欄の全実例、紙 :2781〜2789・:3607・:3614)。

    表から導いた各 Point x について、x の Ref を 1 つだけ I から外した Q' は unresolved_reference で拒まれる。
    誤実装: Local(q) の欄を 1 つ読み忘れる (FB3-R02-R4)・再帰で C を引き継がない・B の生成の境界を読まない (13 通目)。
    表の要素が元の I に無ければ、作る側が表の閉包を作っていない (C ⊆ I の違反) のでそこで落とす。
    """
    rig = make_rig()
    updates = _legal_updates(rig)
    work, evidence, expected = updates[0 if which == "first" else 1]
    by_id = _by_id(rig)
    required = table_required(rig, work.request, by_id)
    assert len(required) >= 12, f"the table walk found too few required records: {len(required)}"
    old = _record(rig, work.request).body.inputs
    refs = {point: _record(rig, point).id for point in required}
    missing_from_I = sorted((p, sorted(required[p])) for p, ref in refs.items() if ref not in old)
    assert not missing_from_I, f"legal Q* omits table-required records from I: {missing_from_I}"
    control = direct_update(rig, work.request, evidence)
    assert isinstance(control, u.IssuedUpdate) and plain(control.result) == expected
    survived = []
    for point in sorted(required):
        inputs = tuple(r for r in old if r != refs[point])
        q = save_request(rig, work, inputs=inputs)
        ret = direct_update(rig, q, evidence)
        if not (isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues)):
            survived.append((sorted(required[point]), _record(rig, point).body.contract, type(ret).__name__))
    assert not survived, f"removing a table-required record was not rejected: {survived}"


@pytest.mark.parametrize("which", ("first", "second"))
@pytest.mark.parametrize("declared_in_I", (False, True), ids=("declared_point_absent_from_I", "declared_point_in_I"))
def test_K1_a_point_declared_in_input_points_must_be_in_I(make_rig, which, declared_in_I):
    """K1 の 2 つ目の生成器 (A2-INPUT-POINTS、紙 :3607・:3614、FB3-R02-R4 の反例)。"""
    rig = make_rig()
    updates = _legal_updates(rig)
    work, evidence, expected = updates[0 if which == "first" else 1]
    # 足す記録は origin 以外 (origin の写しは台帳から導く origin の候補を 2 つにして、別の原子が先に止める。正本 v1.3.9
    # ledger_origin_binding)。受信の記録は像のどの導出の候補にもならない
    rig.host.post(received(b"K1 unrelated input"))
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    x = rig.facts(c.RECEIVED)[-1].cid
    desc = work.desc
    boundary = frozenset(desc.numerical_view.boundary) | {x}
    changed = replace(desc, input_points=frozenset(desc.input_points) | {x},
                      numerical_view=fixed_view(rig, boundary))
    old = _record(rig, work.request).body.inputs
    inputs = old + ((_record(rig, x).id,) if declared_in_I else ())
    q = save_request(rig, work, desc=changed, inputs=inputs)
    ret = direct_update(rig, q, evidence)
    if declared_in_I:
        assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected, getattr(ret, "issues", ret)
    else:
        assert isinstance(ret, u.Rejected) and any(i.code == "unresolved_reference" for i in ret.issues), \
            (type(ret).__name__, getattr(ret, "issues", None))


# ---------------------------------------------------------------- K1b: 欄ごとの参照の差し替え (T-REF の Q* の U/UE の欄)

def _q_reference_rows():
    return [r for r in rules.T_REF if r["contract"] == "sui.fb.work_requested/1" and r["purpose"] == "update"
            and r["role"] in ("U", "UE") and r["field"].startswith("/desc/")]


@pytest.mark.parametrize("rule", [r["id"] for r in _q_reference_rows()])
def test_K1b_replacing_one_declared_reference_of_Q_with_a_record_of_another_contract_is_rejected(make_rig, rule):
    """K1b (T-REF の Q* の U/UE の各欄、FB3-TEST-R6「欄ごとの参照の差し替え・型違い・対応違い」)。

    合法な Q* の写しで、表の 1 つの欄だけを別の契約の実在の記録 (origin の写し) に差し替え、固定像・I はその記録を
    含むように直す。期待: 拒む (reference_kind / 形 / 対応の不一致のどれか) で、発行しない。
    誤実装: 欄を読まずに Point の実在だけ見る。
    """
    rig = make_rig()
    (work, evidence, _expected), *_ = _legal_updates(rig)
    row = _REF_BY_ID[rule]
    by_id = _by_id(rig)
    _c, document = _document(rig, work.request, by_id)
    instances = walk(document, row["field"])
    if not instances:
        pytest.skip(f"{rule}: the legal Q* has no instance of {row['field']} (未検証)")
    decoy = save_copy(rig, rig.one(ORIGIN).cid)
    desc = json.loads(json.dumps(document["desc"]))
    path, _value = instances[0]
    segments = path.split("/")[2:]   # /desc/...
    holder = desc
    for segment in segments[:-1]:
        holder = holder[int(segment)] if isinstance(holder, list) else holder[segment]
    last = segments[-1]
    if isinstance(holder, list):
        holder[int(last)] = decoy
    else:
        holder[last] = decoy
    # Desc は和型の args を持つので F-a の復号では戻せない: JSON のまま公開の台帳に書く (save_copy)
    boundary = frozenset(work.desc.numerical_view.boundary) | {decoy}
    view = fixed_view(rig, boundary)
    desc["numerical_view"] = {"boundary": sorted(boundary), "environment": {
        "reader_view_key": view.reader_view_key, "registry_key": view.registry_key}}
    inputs = tuple(dict.fromkeys((*_record(rig, work.request).body.inputs, _record(rig, decoy).id)))
    q = save_copy(rig, work.request, value={"desc": desc}, inputs=inputs)
    ret = direct_update(rig, q, evidence)
    assert not isinstance(ret, u.IssuedUpdate), (rule, path, "issued with a wrong-contract reference")


# ---------------------------------------------------------------- K2: 操作と出発点 (T-G6 × 適用方式)

def _rig_full_day(rig):
    """合法な 1 日: 最初の考える過程 (Wg → CG → EQ → PR → D → DF → Ee → EV → S)・更新 2 回・継続の過程まで。"""
    first_claim(rig)
    w1, a1 = rig.adopt(1)
    rig.drive(lambda: len(rig.requests("evaluation_prepare")) >= 2)
    rig.run_stage("evaluation_prepare")
    rig.run_stage("selection_draw")
    rig.run_stage("evaluation")
    rig.drive(lambda: len(rig.facts(c.SELECTION)) >= 2)


def test_K2_every_table_operation_is_consulted_with_its_contract_and_use_in_a_legal_day(make_rig, monkeypatch):
    """K2 (T-G6 の全行 × 適用方式、紙 G6 の表 :3580〜3591、FB3-R01-R5・TEST-R6「全入口の生成器」)。

    `starts_of` を spy で包み、合法な 1 日で実際に導いた (操作, 契約, 用途) の組を集める。期待: 適用方式が
    対象別・同時の全行が、表の契約・用途で少なくとも 1 回通る (呼出し元の無い行はここで見える)。
    誤実装: 歩を 1 つ門に通さない (D の入場・Ee の作成など)。
    """
    from sui import _fb_uses
    recorded = []
    original = _fb_uses.starts_of

    def spy(operation, subjects, **kw):
        starts = original(operation, subjects, **kw)
        for s in starts:
            if isinstance(s, _fb_uses.Candidate):
                recorded.append((operation, _fb_uses.contract_name(s.contract), s.use))
            else:
                recorded.append((operation, None, s[1]))
        return starts

    monkeypatch.setattr(_fb_uses, "starts_of", spy)
    rig = make_rig(continuation=True)
    _rig_full_day(rig)
    seen = {(op, purpose) for op, _c, purpose in recorded}
    # 出どころの行 (門の比較候補を確定する) は出発点でなく比較候補の分類 (`_check_use`、K5 で見る)
    not_consulted = [r["id"] for r in rules.T_G6 if r["application"] in ("対象別", "同時") and r["stage"] != "出どころ"
                     and (r["operation"], r["purpose"]) not in seen]
    known_without_caller = {"G6-NEXT-CONCLUSION"}   # 紙 Z20: 選択した結論を次に使う呼出し元はこの版に無い (★)
    assert set(not_consulted) <= known_without_caller, f"T-G6 rows never consulted in a legal day: {not_consulted}"
    assert not (known_without_caller - set(not_consulted)), "a row listed as caller-less is now consulted: update Z20"


def test_K2_continuation_gate_starts_from_every_object_the_continuation_contract_uses(make_rig, monkeypatch):
    """K2 (T-G6「継続を開く」の同時の 3 行、FB3-R01-R4a)。門の出発点を spy で取り、A*・CG・宣言の全部から閉包を
    取ることを要求する。誤実装: A* だけを渡す。"""
    from sui import _fb_update
    rig = make_rig(continuation=True)
    first_claim(rig)
    recorded = []
    original = _fb_update.gate

    def spy(state, starts):
        recorded.append(tuple(starts))
        return original(state, starts)

    monkeypatch.setattr(_fb_update, "gate", spy)
    work, a = rig.adopt()
    rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)
    cg = rig.one(CG).cid
    d = rig.one(contract("sui.fb.boot_declaration")).cid
    pairs = [{(s[0], s[1]) for s in starts if isinstance(s, tuple)} for starts in recorded]
    rows = [r for r in rules.T_G6 if r["operation"] == "継続を開く"]
    subjects = {"sui.fb.belief_adopted/1": a.cid, "sui.f.candidate_declaration/1": cg, "sui.fb.boot_declaration/1": d}
    expected = {(subjects[r["contract"]], r["purpose"]) for r in rows}
    continuation_gates = [s for s in pairs if (a.cid, "continuation") in s]
    assert continuation_gates, f"no gate was consulted with the adoption in the continuation use: {pairs[-3:]}"
    lacking = [s for s in continuation_gates if not expected <= s]
    assert not lacking, f"continuation gate starts lack {expected}: {lacking[:2]}"


# ---------------------------------------------------------------- K3: 実行の証拠の表 (T-A1 の系列の項目)

def _wu_report_point(rig, work_id):
    reports = [r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == work_id]
    assert len(reports) == 1
    return reports[0].cid


def evidence_variants(rig, first, second, evidence):
    """T-A1 の系列の項目 (A1-HISTORY-ENTER / RETURN / ACQUIRE / ACQUIRE-BEFORE-USE / ACQUIRE-BEFORE-ADOPT) の
    独立の観測を 1 つずつ落とす。どれも保存された R1・G1・A1 の本文は正しいまま。"""
    wu1 = first.desc.work_id
    r1 = result_for(rig, first.request).cid
    origin = second.desc.reader
    terminal = _wu_report_point(rig, wu1)
    rows = {x.work_id: x for x in evidence.executions}
    assert wu1 in rows and rows[wu1].entered >= 1 and any(r.point == terminal for r in rows[wu1].reports)
    acquired_r1 = [a for a in evidence.acquisitions if a.origin == origin and r1 in a.contents]
    assert acquired_r1, "the legal evidence must hold the origin's acquisition of R1"
    uses_wu2 = [x.used_ns for x in evidence.uses if x.work_id == second.desc.work_id]
    assert uses_wu2, "Wu2 must have read something"

    def executions(fn):
        return tuple(fn(x) if x.work_id == wu1 else x for x in evidence.executions)

    yield "A1-HISTORY-ENTER:row_missing", replace(evidence, executions=tuple(
        x for x in evidence.executions if x.work_id != wu1))
    yield "A1-HISTORY-ENTER:not_entered", replace(evidence, executions=executions(lambda x: replace(x, entered=0)))
    yield "A1-HISTORY-RETURN:not_from_its_port", replace(evidence, executions=executions(
        lambda x: replace(x, reports=tuple(r for r in x.reports if r.point != terminal))))
    yield "A1-HISTORY-ACQUIRE:missing", replace(evidence, acquisitions=tuple(
        a for a in evidence.acquisitions if not (a.origin == origin and r1 in a.contents)))
    yield "A1-HISTORY-ACQUIRE-BEFORE-USE:after_Wu2_use", replace(evidence, acquisitions=tuple(
        replace(a, acquired_ns=max(uses_wu2) + 1) if (a.origin == origin and r1 in a.contents) else a
        for a in evidence.acquisitions))
    a1_at = rig.ledger.entry(rig.facts(c.BELIEF_ADOPTED)[0].cid).at.mono_ns
    yield "A1-HISTORY-ACQUIRE-BEFORE-ADOPT:after_adoption", replace(evidence, acquisitions=tuple(
        replace(a, acquired_ns=a1_at + 1) if (a.origin == origin and r1 in a.contents) else a
        for a in evidence.acquisitions))


def test_K3_control_chain_is_accepted_by_U_and_prepare(make_rig):
    rig = make_rig()
    (first, _e1, _), (second, evidence, expected) = _legal_updates(rig)
    ret = direct_update(rig, second.request, evidence)
    assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    prepared = prepare_adoption(rig, a2.cid, result_for(rig, second.request).cid, evidence=evidence)
    assert isinstance(prepared.value, f.FProblem)


@pytest.mark.parametrize("name", ("A1-HISTORY-ENTER:row_missing",
                                  "A1-HISTORY-RETURN:not_from_its_port", "A1-HISTORY-ACQUIRE:missing"))
def test_K3_dropping_one_required_observation_of_the_previous_chain_is_insufficient(make_rig, name):
    """K3 (T-A1 の系列の項目、紙 :3610〜3611・:2093〜2102・§19-7、v0.31 の決定、FB3-R04-R5)。

    誤実装: 前の R1 の生成・取得を、保存された R1・G1 の本文と数値の計算し直しで代用する / 取得の上限を使う側の
    Wu だけにして採用自身との前後を見ない。期待: 入口 U (Q2) も評価の頭 (A2) も insufficient (prerequisite_unavailable)。
    """
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    changed = dict(evidence_variants(rig, first, second, evidence))[name]
    ret = direct_update(rig, second.request, changed)
    assert isinstance(ret, u.Insufficient), (name, type(ret).__name__, getattr(ret, "issues", None))
    assert any(i.code == "prerequisite_unavailable" for i in ret.issues), (name, ret.issues)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    prepared = prepare_adoption(rig, a2.cid, result_for(rig, second.request).cid, evidence=changed)
    assert_incomplete_preparation(prepared, "prerequisite_unavailable")


@pytest.mark.parametrize("name,row", (("A1-HISTORY-ACQUIRE-BEFORE-USE:after_Wu2_use", "A1-HISTORY-ACQUIRE-BEFORE-USE"),
                                      ("A1-HISTORY-ACQUIRE-BEFORE-ADOPT:after_adoption", "A1-HISTORY-ACQUIRE-BEFORE-ADOPT")))
def test_K3_an_acquisition_observed_out_of_order_is_a_confirmed_reversal_not_a_shortage(make_rig, name, row):
    """K3 (表 A1-HISTORY-ACQUIRE-BEFORE-USE-ORDER・BEFORE-ADOPT-ACQUIRED: le、on_fail 不適合。A4: 観測はあるが順が逆 =
    確定した不一致)。旧の手書きは不足にしていた (2026-10-22 に機械の評価で分類が表どおりになった)。"""
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    changed = dict(evidence_variants(rig, first, second, evidence))[name]
    ret = direct_update(rig, second.request, changed)
    assert isinstance(ret, u.Rejected) and row in ret.issues[0].message, ret
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    with pytest.raises(f.FInputError, match=row):
        prepare_adoption(rig, a2.cid, result_for(rig, second.request).cid, evidence=changed)


def test_K3_a_confirmed_non_entry_of_the_previous_chain_is_a_mismatch_not_a_shortage(make_rig):
    """K3 の分類 (T-A1 `A1-HISTORY-ENTER-MISMATCH` = 不適合、紙 :2094「起動失敗の未入場確認」は EW の独立観測、
    A4 証拠の欠落と確定した不一致は別分類。FB3-CLASS-R7: 前は K3 も実装も不足にしていた = Claude の読み違い)。
    EW がその Wu の実行を観測していて入場 0 回 = 確定した未入場 → U は Rejected(proof_mismatch)、評価の頭は
    型つきの不適合 (FInputError)。観測の行そのものが無い (`row_missing`) だけが不足。
    誤実装: 未入場の確定を不足に潰す (証拠を待てば通るかのように見せる)。"""
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    changed = dict(evidence_variants(rig, first, second, evidence))["A1-HISTORY-ENTER:not_entered"]
    ret = direct_update(rig, second.request, changed)
    assert isinstance(ret, u.Rejected) and any(i.code == "proof_mismatch" for i in ret.issues),         (type(ret).__name__, getattr(ret, "issues", None))
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    with pytest.raises(f.FInputError, match="proof_mismatch"):
        prepare_adoption(rig, a2.cid, result_for(rig, second.request).cid, evidence=changed)


# ---------------------------------------------------------------- K8: A1 の集約 (T-A1 × 段階)

def _per_q_rows():
    process = set(u.A1_PROCESS)
    pending = {p["id"] for p in rules.METADATA["pending"] if p["table"] == "T-A1"}
    return [r for r in rules.T_A1 if r["id"] not in process and r["id"] not in pending]


def _chain_row(row) -> bool:
    """前の採用の Q* にだけ当たる項目: 表の対象列の scope が history (使う前の採用系列と頭の A*) か results (過去の
    A*.request / result の対応。SCOPES results「今の Q* の再構成に未来の自分の R* を足さない」)。実装の定数は読まない。"""
    subject = row["subject"]
    return hasattr(subject, "items") and subject["scope"] in ("history", "results")


def test_K8_every_table_authentication_item_is_marked_for_each_authenticated_request(make_rig, monkeypatch):
    """K8 (T-A1 の全行 × 対象: 再構成用途で届いた全 Q*、紙 A1 :3593〜3615)。

    `_Replay.done` を spy で包み、合法な Q2 の入口 U で、今の Q2 と前の Q1 にどの項目の印が付いたかを集める。
    期待: Q2 (更新の再構成) には過程ごとでも未確定でもない全項目のうち系列の項目を除く全部、Q1 (前の系列) には
    系列の項目も含む全部。表の行が実装の分母 (印の無い項目は実装の穴)。
    """
    rig = make_rig()
    (first, _e1, _), (second, evidence, expected) = _legal_updates(rig)
    marks = {}
    original = u._Replay.done

    def spy(self, point, *ids):
        marks.setdefault(point, set()).update(ids)
        return original(self, point, *ids)

    monkeypatch.setattr(u._Replay, "done", spy)
    ret = direct_update(rig, second.request, evidence)
    assert isinstance(ret, u.IssuedUpdate) and plain(ret.result) == expected
    for_current = {r["id"] for r in _per_q_rows() if not _chain_row(r)}
    for_previous = {r["id"] for r in _per_q_rows()}
    assert for_current <= marks.get(second.request, set()), \
        f"Q2 lacks marks: {sorted(for_current - marks.get(second.request, set()))}"
    assert for_previous <= marks.get(first.request, set()), \
        f"Q1 lacks marks: {sorted(for_previous - marks.get(first.request, set()))}"
    assert set(u.A1_PROCESS) | {r["id"] for r in _per_q_rows()} | \
        {p["id"] for p in rules.METADATA["pending"] if p["table"] == "T-A1"} == {r["id"] for r in rules.T_A1}


@pytest.mark.parametrize("rule", [r["id"] for r in _per_q_rows()])
def test_K8_suppressing_one_mark_makes_the_authentication_insufficient(make_rig, monkeypatch, rule):
    """K8 の識別力: 項目を 1 つ、印を付けない (検査を飛ばした) 誤実装は、集約が不足 (algorithm_unavailable) で止める。"""
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    original = u._Replay.done

    def skipping(self, point, *ids):
        return original(self, point, *(i for i in ids if i != rule))

    monkeypatch.setattr(u._Replay, "done", skipping)
    ret = direct_update(rig, second.request, evidence)
    assert isinstance(ret, u.Insufficient) and any(i.code == "algorithm_unavailable" and rule in i.message
                                                   for i in ret.issues), (rule, type(ret).__name__, getattr(ret, "issues", None))


# ---------------------------------------------------------------- K4: 無関係な記録は結果を変えない (紙 REF-3・E-06)

def _event_copy_outside_root(rig):
    """固定根の外の出来事 1 件: 時計の読みの写し (Observed、is_event)。根の祖先ではないので見える範囲の外。"""
    reading = rig.facts(contract("sui.f.clock_reading"))[-1]
    now = rig.clock.mono_ns()
    return save_copy(rig, reading.cid, received_ns=now)


def test_K4_a_wider_reader_with_an_unrelated_event_outside_the_root_gives_the_same_value(make_rig):
    """K4 (紙 REF-3 :1081、F-a A-02/A-03・E-06 :149〜150・:493、FB3-SCOPE-R5)。

    同じ固定根・同じ対象・同じ観測で、根の外の無関係な出来事を 1 件含む広い読み手に替えても、評価の準備の
    値 (FProblem と K.belief) は同じ。誤実装: Ref の索引を作る読みが読み手の全件の本文を範囲つきで読み、
    根の外の出来事で unresolved_reference になる。
    """
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    r2 = result_for(rig, second.request).cid
    reader, kwargs = adoption_prepare_inputs(rig, a2.cid, r2)
    narrow = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    assert isinstance(narrow.value, f.FProblem)
    extra = _event_copy_outside_root(rig)
    assert extra not in reader.points
    wide = PublicReader(rig.ledger, points=reader.points | {extra})
    prepared = u.prepare_fb_from_facts(wide, evidence=evidence, **kwargs)
    assert isinstance(prepared.value, f.FProblem), getattr(prepared.value, "reason", prepared.value)
    assert json.loads(prepared.canonical_bytes)["claim"] == json.loads(narrow.canonical_bytes)["claim"]


# ---------------------------------------------------------------- K5: 固定像の候補集合は Xuse から (紙 G5)

@pytest.mark.parametrize("conflict", (False, True), ids=("same_value_copy", "incompatible_copy"))
def test_K5_a_related_saved_report_without_provenance_in_the_fixed_view_is_insufficient(make_rig, conflict):
    """K5 (紙 G5 :3579「出どころを確かめられない配送を…関係する候補で判定できなければ不足」、FB3-R01-R4b)。

    固定根に、頭の A* が依る原 Claim と同じ鍵 (item, k, slot) の保存済みの報告をもう 1 件足す (ホストを通さず
    台帳に直接。独立の観測 EH には載らない)。渡す観測は後着より前のまま。期待は出どころ不明の不足で、
    成功の信念でも use_conflict でもない。誤実装: 候補を EH に載った報告から逆算し、観測行があれば「関連なし」。
    """
    rig = make_rig()
    work, a, _ = direct_first(rig)
    evidence = current_evidence(rig)
    report = rig.one(c.SEGMENT_BINDING).value["report"]
    value = json.loads(json.dumps(_content(rig, report)))
    if conflict:
        value["item"]["kind"] = "count_exactly_one"
        value["item"]["contract"] = plain(c.COUNT_EXACTLY_ONE)
    copy = save_copy(rig, report, value=value, received_ns=rig.clock.mono_ns())
    assert not any(r.point == copy for e in evidence.executions for r in e.reports)
    r = result_for(rig, work.request)
    control = prepare_adoption(rig, a.cid, r.cid, sole_adoption=True, evidence=evidence)
    assert isinstance(control.value, f.FProblem)
    prepared = prepare_adoption(rig, a.cid, r.cid, sole_adoption=True, additional_roots=(copy,), evidence=evidence)
    assert_incomplete_preparation(prepared, "prerequisite_unavailable")


# ---------------------------------------------------------------- K6: 失敗の分類 (紙 A4)

@pytest.mark.parametrize("api", ("restore", "verify"))
def test_K6_rereading_an_fb_artifact_without_observations_is_unavailable_not_a_mismatch(make_rig, api):
    """K6 (紙 A4 :3616、Z9(b) :3635、FB3-DIAG-R5)。

    A* を読んで正常に発行した評価の準備の bytes を、同じ reader・registry・十分な予算で読み直す。bytes は
    変えていないので、確定した改変 (FReplayMismatch) ではなく、観測を運べない再生の不足 (FReplayUnavailable)。
    """
    rig = make_rig()
    (first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    r2 = result_for(rig, second.request).cid
    reader, kwargs = adoption_prepare_inputs(rig, a2.cid, r2)
    prepared = u.prepare_fb_from_facts(reader, evidence=evidence, **kwargs)
    assert isinstance(prepared.value, f.FProblem)
    entry = ff.restore_f_math_result if api == "restore" else ff.verify_f_math_result
    with pytest.raises(f.FReplayUnavailable):
        entry(prepared.canonical_bytes, reader=reader, registry=rig.registry, budget=kwargs["budget"])


# ---------------------------------------------------------------- K7: 門のロックの配置 (紙 G6 の最後の行)

@pytest.mark.parametrize("conflict", (False, True), ids=("same_finish_arrives", "incompatible_finish_arrives"))
def test_K7_gate_computes_outside_the_lock_and_does_not_publish_on_a_stale_permission(make_rig, monkeypatch, conflict):
    """K7 (紙 G6 :3591「重い閉包の計算・再生はロックの外、最後の関連の配送・…・公開を同じ状態の 1 歩に (途中で
    条件が変われば古い許可を使わない)」、J9-d :3486、FB3-LOCK-R5)。

    門の重い計算 (配送の比較) を同期点で待たせ、(1) その間に別のスレッドの Post (測る仕事の口からの再配送) が
    完了できること = 計算がロックの外、(2) 待っている間に矛盾する再配送が届いたら、計算し直して継続を止める
    (古い許可で EQ を公開しない)、同じ中身なら続く、を要求する。
    誤実装: 門を settle のロックの中で計算する (Post が待たされる) / 外で計算した許可を再照合せず公開する。
    """
    from threading import Event, Thread
    from sui import _fb_uses
    from test_fb_stage3 import deliver_first_claim_again
    rig = make_rig(continuation=True)
    first_claim(rig)
    # 継続の文脈の書き込みを保留して、継続の過程を「開いたが EQ はまだ」で止める (公開の保存の故障の形)
    rig.ledger.hold_context_before_write = True
    work, a = rig.adopt()
    rig.settle_steps()
    assert len(rig.requests("evaluation_prepare")) == 1
    in_gate, release = Event(), Event()
    original = _fb_uses.clashes

    def hooked(deliveries):
        # 門の重い計算のうち、毎回の settle で必ず走る配送の比較を同期点にする (閉包は台帳が変わらなければ
        # 前回の結果が使われる)。最初の 1 回だけ待つ
        if not in_gate.is_set():
            in_gate.set()
            assert release.wait(5), "incomplete observation: the gate was never released"
        return original(deliveries)

    monkeypatch.setattr(_fb_uses, "clashes", hooked)
    errors = []

    def settle_once():
        try:
            rig.step()   # settle 1 回 (保留した書き込みの OSError は rig が観測として吸う)
        except BaseException as error:   # noqa: BLE001 — 観測として残す
            errors.append(error)

    # 保留を解く: 次の settle で (準備済みの) 文脈が保存され、その後に新しい記録 EQ を作るかどうかを門が決める
    rig.ledger.hold_context_before_write = False
    settling = Thread(target=settle_once, daemon=True)
    settling.start()
    assert in_gate.wait(5), "the continuation gate was not computed in this settle"
    posted = Event()

    def post_from_another_thread():
        deliver_first_claim_again(rig, conflict=conflict)   # 測る仕事の口から、ホストの Post まで
        posted.set()

    poster = Thread(target=post_from_another_thread, daemon=True)
    poster.start()
    assert posted.wait(2), "a Post could not complete while the gate was computing (the gate holds the lock)"
    release.set()
    settling.join(10)
    assert not settling.is_alive() and not errors, errors
    # 同じ settle の中の判定 (さらに settle を回す前に見る): 準備済みの文脈の保存 (再試行) は門で止めない (紙 G6)
    # が、その後の新しい記録 EQ は門が決める。待っている間に矛盾が届いたなら、この settle は計算前の許可で EQ を
    # 公開してはいけない。同じ中身なら EQ が公開される
    published = len(rig.requests("evaluation_prepare")) - 1
    assert published == (0 if conflict else 1), (
        "the continuation EQ was published on a permission computed before the clash arrived" if conflict
        else "incomplete observation: the continuation did not publish its EQ in this settle")
    rig.settle_steps()
    if conflict:
        assert len(rig.requests("evaluation_prepare")) == 1, "the continuation was published after the clash"
    else:
        rig.drive(lambda: len(rig.requests("evaluation_prepare")) == 2)


# ---------------------------------------------------------------- K7-b: 配送だけが進んだ時の比較し直し (G6、Z22)

@pytest.mark.parametrize("conflict", (False, True), ids=("same_content", "incompatible"))
def test_K7_a_delivery_that_advances_only_the_delivery_version_is_compared_again_in_the_same_step(make_rig, conflict):
    """K7-b (紙 G6「最後の関連の配送の照合を同じ状態の 1 歩に」、Z22): 門の材料 (閉包・比較) を外で先に計算した後、
    台帳は進まず配送だけが進んだ (測る口の Post だけ、保存なし) 時、門はその歩で配送を比較し直す。矛盾する再配送なら
    blocked、同じ中身なら open のまま。誤実装: 先に計算した比較 (古い配送の集合) をそのまま使う。
    (settle の中では配送の保存が台帳の版を進めて stale になるので K7 では見えない。)
    """
    from sui import _fb_update
    from test_fb_stage3 import deliver_first_claim_again
    rig = make_rig()
    first_claim(rig)
    rig.callback("belief_update")   # Q* は保存済み、仕事の本体はまだ (次の歩の出発点 (Q, update) が門に並ぶ)
    state = rig.host._state
    _fb_update.precompute(state)
    with state.lock:
        groups = _fb_update._pending_starts(state)
        before = [_fb_update.gate(state, starts) for starts in groups]
        ledger_version = state.ledger_version
    assert "open" in before, ("incomplete observation: no open gate before the delivery", before)
    deliver_first_claim_again(rig, conflict=conflict)   # 測る口の Post だけ (settle も保存もしない)
    with state.lock:
        assert state.ledger_version == ledger_version and state.gate_cache["delivery"] != state.delivery_version, \
            "incomplete observation: the Post advanced the ledger, or did not advance the delivery version"
        after = [_fb_update.gate(state, starts) for starts in groups]
    assert "stale" not in after, after
    assert ("blocked" in after) == conflict, (before, after)


# ---------------------------------------------------------------- K8 (続き): 今の Q* だけの集約 (Z21)

@pytest.mark.parametrize("rule", [r["id"] for r in _per_q_rows() if not _chain_row(r)])
def test_K8_suppressing_one_mark_of_the_current_request_alone_is_insufficient(make_rig, monkeypatch, rule):
    """K8 の識別力 (今の Q* の集約): 前の系列 Q1 には全部の印が付き、今の Q2 だけ項目を 1 つ付けない誤実装は、Q2 の
    集約 (系列の項目を除く) が不足で止める。前の系列の集約 (adopted の後の系列込みの集約) に頼らない。"""
    rig = make_rig()
    (_first, _e1, _), (second, evidence, _expected) = _legal_updates(rig)
    original = u._Replay.done

    def skipping(self, point, *ids):
        return original(self, point, *(i for i in ids if not (point == second.request and i == rule)))

    monkeypatch.setattr(u._Replay, "done", skipping)
    ret = direct_update(rig, second.request, evidence)
    assert isinstance(ret, u.Insufficient) and any(i.code == "algorithm_unavailable" and rule in i.message
                                                   for i in ret.issues), (rule, type(ret).__name__, getattr(ret, "issues", None))


# ---------------------------------------------------------------- K9: 表の読み手の読み方 (表の係の判定 2-2・2-4、未宣言の枝)
#
# ここだけは `sui._fb_uses` の読み手 (obligations) を直接呼ぶ: 3 つの読み方は他の守り (A2 の I の検査・台帳の親の検査・
# 合法な 1 日に bootstrap 以外の生成が無い) に覆われて公開の入口からは見えない (誤実装の表 v3 で Z17-COVER・Z17-E-REF・
# Z17-CTX-ASSUME が生き残った)。読み方そのものを表の行で検査する。

def _uses_reader(rig):
    from sui import _fb_uses as uses
    return uses, uses.Reader(rig.ledger)


def _legal_binding(rig, uses, reader):
    """合法な Q* の最初の観測の対 (B の Point、その読み方との対の文脈)。"""
    (work, _e, _x), *_ = _legal_updates(rig)
    _q, qdoc = reader.document(work.request)
    contexts = uses._observation_context(reader, qdoc)
    assert "/desc/args/observations/0/binding" in contexts, "incomplete observation: the legal Q* has no observation pair"
    b = qdoc["desc"]["args"]["observations"][0]["binding"]
    contract, document = reader.document(b)
    return b, contract, uses.decided_use(reader, b), document, contexts["/desc/args/observations/0/binding"]


def test_K9_an_E_field_without_a_target_contract_still_resolves_its_point_as_an_edge(make_rig):
    """K9-a (表の係の判定 2-2: 到達先の契約が `-` の E も、欄の型が point なら宣言された参照 = 辺。値欄と読まない)。
    合法な Q* の T-REF の義務のうち role E・到達先 `-`・欄の型 point / ref の全実例 (inputs・input_points・boundary …) は
    target がその Point (ref は読み手で解いた Point)。誤実装: `-` を値欄として target を None にする (実在の検査が消える)。"""
    rig = make_rig()
    (work, _evidence, _expected), *_ = _legal_updates(rig)
    uses, reader = _uses_reader(rig)
    contract, document = reader.document(work.request)
    obs = uses.obligations(reader, work.request, contract, "update", document)
    # 義務の target_contract は到達先から埋まるので、行の `-` は表で見る
    edges = [ob for ob in obs if ob.role == "E" and _REF_BY_ID[ob.rule]["target_contract"] == "-"
             and uses.field_type(contract, ob.field) in ("point", "ref")]
    assert {ob.rule for ob in edges} >= {"REF-Q-INPUTS", "REF-Q-INPUT-POINTS"}, sorted({ob.rule for ob in edges})
    for ob in edges:
        kind = uses.field_type(contract, ob.field)
        assert ob.target is not None and (kind == "ref" or ob.target == ob.value), (ob.rule, ob.path, kind, ob.target)


def test_K9_a_binding_read_without_its_reading_context_is_unsupported_not_assumed(make_rig):
    """K9-b (表の係の判定 2-4: 文脈 (読み方との対) の無い条件 generation・support_required は真と仮定せず止める)。
    合法な B を Q* の観測の対から取った文脈つきで読むと義務が出る。文脈なしで読むと Unsupported。
    誤実装: 文脈が無ければ条件を真と仮定して通す。"""
    rig = make_rig()
    uses, reader = _uses_reader(rig)
    b, contract, purpose, document, context = _legal_binding(rig, uses, reader)
    assert uses.obligations(reader, b, contract, purpose, document, context)
    with pytest.raises(uses.Unsupported, match="undetermined without the reading context"):
        uses.obligations(reader, b, contract, purpose, document)


def test_K9_a_field_instance_that_no_conditioned_row_covers_is_unsupported(make_rig):
    """K9-c (未宣言の枝を空集合として通さない): B の `/generation/applied?` を扱う行は REF-B-APPLIED (生成が bootstrap
    の時) だけ。生成が別の契約の文脈で読むと applied の実例をどの行も扱わない → Unsupported。
    誤実装: 行の無い実例を素通しする。"""
    rig = make_rig()
    uses, reader = _uses_reader(rig)
    b, contract, purpose, document, context = _legal_binding(rig, uses, reader)
    if not walk(document, "/generation/applied?"):
        pytest.skip("the legal B has no generation.applied (未検証)")
    other = {**context, "generation": "sui.fb.other_generation/1", "support_required": False}
    with pytest.raises(uses.Unsupported, match="no rule applies to /"):
        uses.obligations(reader, b, contract, purpose, document, other)


# ---------------------------------------------------------------- K10: 同時の適用方式 (T-G6、Z20)

def test_K10_a_simultaneous_operation_without_one_of_its_subjects_is_unresolved(make_rig):
    """K10 (T-G6 の適用方式「同時」: 継続を開くは A*・CG・宣言を同時に要る。1 つ欠けたら Unresolved で保留し、残りだけで
    出発点を作らない)。誤実装: 無い主語を飛ばして残りの出発点で門を通す。"""
    rig = make_rig(continuation=True)
    first_claim(rig)
    _work, adoption = rig.adopt()
    uses, reader = _uses_reader(rig)
    simultaneous = [r for r in rules.T_G6 if r.get("application") == "同時"]
    operation = simultaneous[0]["operation"]
    assert {r["operation"] for r in simultaneous} == {operation}
    subjects = {_name(c.BELIEF_ADOPTED): adoption.cid,
                _name(fc.CANDIDATE_DECLARATION): rig.one(fc.CANDIDATE_DECLARATION).cid,
                _name(c.BOOT_DECLARATION): rig.one(c.BOOT_DECLARATION).cid}
    assert set(subjects) == {r["contract"] for r in simultaneous}
    full = uses.starts_of(operation, subjects, reader=reader)
    assert {start[0] for start in full} == set(subjects.values())
    for missing in subjects:
        partial = {k: v for k, v in subjects.items() if k != missing}
        with pytest.raises(uses.Unresolved):
            uses.starts_of(operation, partial, reader=reader)


# ---------------------------------------------------------------- K11: 表の原子を 1 つずつ壊す (①-c、紙 v0.35 Z25・Z28)
# 分母 = 機械で評価する行 (`f_update2.A1_EVALUATED`) の全原子。壊し方は関係語ごとに 1 つ (値を替える。関係語の意味は替えない)。
# 公開の入口 U (`direct_update`) で、出口が原子の on_fail の分類と一致することと、壊さない合法対照が通ることを対で見る。
# 当たらなかった原子 (合法な 1 日で when が偽、または手前の原子で止まった) は通ったことにせず skip で数に出す。

def _machine_rows():
    """機械で評価する行 (対象の scope ごと): requests (Q* ごと)・observations (観測の対ごと)・history (系列、2 つ目の更新で)・
    records (読んだ記録ごと)・results (前の採用の Q* と R*、2 つ目の更新で)。"""
    return (*u.A1_EVALUATED, *u.A1_EVALUATED_PER_OBSERVATION, *u.A1_EVALUATED_HISTORY, *u.A1_EVALUATED_HEAD,
            *u.A1_EVALUATED_RECORDS, *u.A1_EVALUATED_RESULTS, *u.A1_EVALUATED_RETURN)


def _k11_cases():
    """分母 = 機械で評価する行の本番の原子 (phase: runtime)。施工の確認の原子 (phase: test) は本番で実行しないので、
    試験の側の生成器 (ATOM_PROTOCOL v3 の tests) で別に壊す (ゆう 2026-10-23、正本 v1.3.1)。"""
    return [(row_id, atom["id"]) for row_id in _machine_rows() for atom in rules.A1_RELATIONS[row_id]
            if atom.get("phase", "runtime") == "runtime"]


def _break(atom, left, right):
    """関係語ごとの壊し方: present → 読めない / absent → 在る / equal → 右を別の値 / not_equal → 右を左と同じ /
    unique → 要素を複製 / le・lt → 左を右より大きく / member_of → 左を無い値 / subset_of → 左に無い要素を足す。"""
    from sui import _fb_a1 as a1
    rel = atom["rel"]
    if rel == "present":
        return a1.Missing("K11: mutated away"), right
    if rel == "absent":
        return {"K11": "present"}, right
    if rel == "equal":
        return left, {"K11": "another value"}
    if rel == "not_equal":
        return left, left
    if rel == "unique":
        return list(left) + list(left)[:1], right
    if rel in ("le", "lt"):
        return (right if isinstance(right, int) else 0) + 1, right if isinstance(right, int) else 0
    if rel == "member_of":
        return {"K11": "outsider"}, right
    if rel == "subset_of":
        return list(left) + [{"K11": "outsider"}], right
    raise AssertionError(f"no mutation for {rel}")


@pytest.mark.parametrize("row_id,atom_id", _k11_cases(), ids=lambda v: v)
def test_K11_breaking_one_atom_of_an_evaluated_row_falls_as_its_on_fail_classifies(make_rig, monkeypatch, row_id, atom_id):
    from sui import _fb_a1 as a1
    atom = next(a for a in rules.A1_RELATIONS[row_id] if a["id"] == atom_id)
    rig = make_rig()
    if row_id in u.A1_EVALUATED_HISTORY or row_id in u.A1_EVALUATED_RESULTS:   # 系列・結果の行は前の採用のある 2 つ目の更新で当たる
        (_first, _e1, _), (work, evidence, _expected) = _legal_updates(rig)
    else:
        work, _adoption, evidence = direct_first(rig)
    assert isinstance(direct_update(rig, work.request, evidence), u.IssuedUpdate)   # 合法対照
    reached, vacuous = [], []

    def mutate(current, left, right):
        if current["id"] != atom_id:
            return left, right
        reached.append(current["id"])
        if isinstance(left, a1.Instances) and not left:
            vacuous.append(current["id"])   # 実例の列が空 (合法な空列): 要素ごとの関係は壊せない
        return _break(current, left, right)
    monkeypatch.setattr(a1, "MUTATE", mutate)
    ret = direct_update(rig, work.request, evidence)
    if not reached:
        pytest.skip(f"{atom_id} is not reached in this legal day (when is false or an earlier atom stops)")
    if vacuous:
        pytest.skip(f"{atom_id} has no instance in this legal day (an empty, legal list; nothing to break)")
    expected = atom["on_fail"]
    if expected == a1.MISMATCH:
        # 理由の語は原子の code (紙 A4、表の係 11 通目)。原子にまだ無ければ公開の語彙の中であることだけ
        assert isinstance(ret, u.Rejected) and len(ret.issues) == 1, ret
        codes = set(u.RejectedIssue.__dataclass_fields__["code"].type.__args__)
        assert ret.issues[0].code in codes, ret
        if "code" in atom:
            assert ret.issues[0].code == atom["code"], ret
    elif expected == a1.SHORTAGE:
        assert isinstance(ret, u.Insufficient) and ret.issues[0].code in ("prerequisite_unavailable", "algorithm_unavailable"), ret
    else:
        assert isinstance(ret, u.Insufficient) and ret.issues[0].code == "use_conflict", ret
    assert atom_id in ret.issues[0].message   # 落ちた原子の ID が理由に残る (印でなく実行の結果)


# ---------------------------------------------------------------- K11-B: 一覧の本番の原子を 1 つずつ壊す (ATOM_PROTOCOL v3、2026-10-23)
# 差し替えで一覧の本番の原子 (phase: runtime) が、導出の呼出しごとに本番の門として働く。その原子も T-A1 と同じ壊し方で、
# 公開の入口の出口が原子の on_fail の分類と一致するかを見る。分母 = 機械で評価する行が呼ぶ導出を consumers に持つブロック
# (推移的に) の本番の原子。2 つ目の更新 (前の採用の系列を再び認証する) で当てる。当たらない原子は skip で数に出す。

def _block_runtime_atoms():
    called = set()

    def derives(node):
        if hasattr(node, "items"):
            if "derive" in node:
                called.add(node["derive"])
            for value in node.values():
                derives(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                derives(value)
    for row_id in _machine_rows():
        for atom in rules.A1_RELATIONS[row_id]:
            if atom.get("phase", "runtime") == "runtime":
                derives(atom)
    reached, changed = set(), True
    while changed:
        changed = False
        for name, block in rules.ENUMERATIONS.items():
            if name in reached or not set(block["consumers"]) & called:
                continue
            reached.add(name)
            changed = True
            for item in block["items"]:
                for atom in (*block.get("prelude", ()), *item.get("prelude", ()), *item["atoms"]):
                    if atom.get("phase", "runtime") == "runtime":
                        derives(atom)
    out = []
    for name in sorted(reached):
        block = rules.ENUMERATIONS[name]
        atoms = list(block.get("prelude", ())) + [a for item in block["items"]
                                                 for a in (*item.get("prelude", ()), *item["atoms"])]
        out += [(name, atom["id"]) for atom in atoms if atom.get("phase", "runtime") == "runtime"]
    return out


@pytest.mark.parametrize("block,atom_id", _block_runtime_atoms(), ids=lambda v: v)
def test_K11_B_breaking_one_runtime_atom_of_a_list_block_falls_as_its_on_fail_classifies(make_rig, monkeypatch, block, atom_id):
    from sui import _fb_a1 as a1
    found = [a for item in rules.ENUMERATIONS[block]["items"]
             for a in (*rules.ENUMERATIONS[block].get("prelude", ()), *item.get("prelude", ()), *item["atoms"])
             if a["id"] == atom_id]
    atom = found[0]
    rig = make_rig()
    (_first, _e1, _), (work, evidence, _expected) = _legal_updates(rig)
    assert isinstance(direct_update(rig, work.request, evidence), u.IssuedUpdate)   # 合法対照
    reached, vacuous = [], []

    def mutate(current, left, right):
        if current["id"] != atom_id:
            return left, right
        reached.append(current["id"])
        if isinstance(left, a1.Instances) and not left:
            vacuous.append(current["id"])
        return _break(current, left, right)
    monkeypatch.setattr(a1, "MUTATE", mutate)
    ret = direct_update(rig, work.request, evidence)
    if not reached:
        pytest.skip(f"{block}/{atom_id} is not reached in this legal day (condition false or an earlier atom stops)")
    if vacuous:
        pytest.skip(f"{block}/{atom_id} has no instance in this legal day (an empty, legal list)")
    expected = atom["on_fail"]
    if expected == a1.MISMATCH:
        assert isinstance(ret, u.Rejected) and len(ret.issues) == 1, ret
        if "code" in atom:
            assert ret.issues[0].code == atom["code"], ret
    elif expected == a1.SHORTAGE:
        assert isinstance(ret, u.Insufficient) and ret.issues[0].code in ("prerequisite_unavailable", "algorithm_unavailable"), ret
    else:
        assert isinstance(ret, u.Insufficient) and ret.issues[0].code == "use_conflict", ret
    assert atom_id in ret.issues[0].message   # 落ちた一覧の原子の ID が理由に残る


# K11-B の評価の頭の道: 評価の準備 (prepare_fb_from_facts → adopted_belief) でだけ当たる本番の原子 (MODEL-COMPILER-* 等、
# 入口 U の道では条件が偽)。同じ壊し方で、準備が確定した不一致 (FInputError、理由の語 = 原子の code) か不足 (FIncomplete /
# 決められない incomplete) で止まることを見る。合法対照は FProblem を作る。

def _head_only_block_atoms():
    out = []
    for block, atom_id in _block_runtime_atoms():
        if block == "MODEL_LINKS" and atom_id.startswith("MODEL-COMPILER-"):
            out.append((block, atom_id))
    return out


@pytest.mark.parametrize("block,atom_id", _head_only_block_atoms(), ids=lambda v: v)
def test_K11_B_head_breaking_one_runtime_atom_on_the_evaluation_head_path(make_rig, monkeypatch, block, atom_id):
    from sui import _fb_a1 as a1
    from test_fb_stage3 import result_for
    found = [a for item in rules.ENUMERATIONS[block]["items"] for a in (*item.get("prelude", ()), *item["atoms"])
             if a["id"] == atom_id]
    atom = found[0]
    rig = make_rig()
    (_first, _e1, _), (second, _evidence, _expected) = _legal_updates(rig)
    adoption = next(a for a in rig.facts(c.BELIEF_ADOPTED) if a.value["request"] == second.request)
    result = result_for(rig, second.request)
    control = prepare_adoption(rig, adoption.cid, result.cid)
    assert isinstance(control.value, f.FProblem), type(control.value).__name__   # 合法対照
    reached = []

    def mutate(current, left, right):
        if current["id"] != atom_id:
            return left, right
        reached.append(current["id"])
        return _break(current, left, right)
    monkeypatch.setattr(a1, "MUTATE", mutate)
    try:
        prepared, error = prepare_adoption(rig, adoption.cid, result.cid), None
    except (f.FInputError, f.FReplayMismatch, f.FReplayUnavailable, f.FIncomplete, f.FSpecificationMissing) as exc:
        prepared, error = None, exc
    if not reached:
        pytest.skip(f"{block}/{atom_id} is not reached on the evaluation head path")
    if atom["on_fail"] == a1.MISMATCH:
        assert isinstance(error, f.FInputError) and error.reason == atom["code"], (error, prepared)
    else:
        assert isinstance(error, f.FIncomplete) or (prepared is not None and isinstance(prepared.value, f.NoDecision)), \
            (error, prepared)
    assert atom_id in str(error if error is not None else plain(prepared.value))


def test_K11_denominator_is_the_table_not_the_implementation():
    """機械で評価する行の集合は表の行の部分集合で、手書きの行・過程の行と重ならない。移し終わっていない行は数に出す。"""
    ids = {row["id"] for row in rules.T_A1}
    machine = set(_machine_rows())
    assert machine <= ids and not (machine & set(u.A1_PROCESS)) and len(_machine_rows()) == len(machine)
    handwritten = u.a1_handwritten()
    assert handwritten | machine | set(u.A1_PROCESS) | u.a1_pending() == ids
    assert len(handwritten) == 0, sorted(handwritten)   # 2026-10-23 15:5x: 手書きの行は 0 (SHAPE は Z33 ③ (c) のふつうのコード `_fb_shapes` を表の行が呼ぶ) (移すごとに減らす。増えたら移し戻し)


# ---------------------------------------------------------------- K11-R02: 時計の行の反例 (レビュー 7 通目 FB3-R02-R6、公開の入口で)
# 表の行 A1-CLOCK が機械で評価される時だけ意味を持つ (まだ手書きの印なら skip で数に出す。表の項目 CLK-ROUTE-WINDOW-START の
# 直しを表の係 9 通目に頼んだ、2026-10-22 12:0x)。反例は記録を変えず、独立の観測 (EH) だけを変える = 印を残して関係を壊す負例。

def _started_receipt(rig, work, evidence):
    """最初の更新の観測の Started の原報告と、その EH の受信 (ExecutionObservation, ReportObservation)。"""
    q = _content(rig, work.request)
    binding = _content(rig, q["desc"]["args"]["observations"][0]["binding"])
    started = binding["generation"]["started"]
    for i, execution in enumerate(evidence.executions):
        for j, report in enumerate(execution.reports):
            if report.point == started:
                return started, i, j
    raise AssertionError("the Started boundary was not received from any observed work")


def _with_receipt(evidence, i, j, **changes):
    execution = evidence.executions[i]
    reports = list(execution.reports)
    reports[j] = replace(reports[j], **changes)
    executions = list(evidence.executions)
    executions[i] = replace(execution, reports=tuple(reports))
    return replace(evidence, executions=tuple(executions))


@pytest.mark.parametrize("change", ("received_before_reading", "another_run"), ids=lambda v: v)
def test_K11_R02_a_started_boundary_received_before_its_reading_or_on_another_run_is_a_mismatch(make_rig, change):
    if "A1-CLOCK" not in u.A1_EVALUATED_PER_OBSERVATION:
        pytest.skip("A1-CLOCK is not yet evaluated by the machine (table item CLK-ROUTE-WINDOW-START awaits the table clerk)")
    rig = make_rig()
    work, _adoption, evidence = direct_first(rig)
    started, i, j = _started_receipt(rig, work, evidence)
    reading = _content(rig, started)["item"]["value"]["reading"]["value"]["reading"]
    assert isinstance(direct_update(rig, work.request, evidence), u.IssuedUpdate)   # 合法対照
    if change == "received_before_reading":
        broken = _with_receipt(evidence, i, j, received_ns=reading["time_ns"] - 1)
    else:
        broken = _with_receipt(evidence, i, j, run="run:another-host")
    ret = direct_update(rig, work.request, broken)
    assert isinstance(ret, u.Rejected) and len(ret.issues) == 1, ret
    assert "A1-CLOCK" in ret.issues[0].message


# ---------------------------------------------------------------- K13: 未確定 0 (紙 v0.35 Z25、P-R01 の閉じる条件)

def test_K13_no_pending_rule_remains_and_a_legal_day_reaches_no_undetermined_closure(make_rig):
    """生成物の未確定 (停止マーカー) が 0、T-A1 の未確定が 0、合法な 1 日の閉包が未確定に届かない (`Undetermined` が出ない)
    = 4 行が普通の行になったこと (ゆう 08:02 の決定の確認)。"""
    from sui import _fb_uses as uses
    assert rules.METADATA["pending"] == [] and u.a1_pending() == frozenset()
    rig = make_rig()
    work, adoption, _evidence = direct_first(rig)
    reader = uses.Reader(rig.ledger)
    for start in ((work.request, "update"), (adoption.cid, "belief")):
        found = uses.closure(reader, [start])
        assert found.pending == (), found.pending
    for plan in rig.host._state.updates.values():
        assert not any("undetermined" in reason for reason in plan.missing), plan.missing
