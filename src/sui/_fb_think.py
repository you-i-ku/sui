"""考える過程 (紙 F-b §5-2 の段 2・§6-9 H1〜H10・§2-4-3・§2-4-10 (5)・§2-4-11 M3/M4・§2-5)。

段 1 で保存した Qgen の仕事 Wg から、候補の宣言 CG → 文脈 (o・j) → 評価の要求 EQ → 準備 Ep
→ 準備の結果と PR → くじ D → DF (または DU) → 評価 Ee → 評価の結果と EV → 選ぶ S を進める。
各仕事の論理の終わりは、その仕事の口から来た終わりの知らせのうち Post の順 (r, receipt_seq) で
最初のもの (INV-15)。終わりの記録 T を残し、枝ごとに許された後続だけを計画する。記録は
起動の計画と同じく最初に作った時に固定し、1 点ずつ保存する (`_fb_boot.advance`)。
"""

import json as _json
from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from . import f_contracts as _fc
from ._fb_boot import Step as _Step, _front, _record, _work_id, fixed_view as _fixed_view
from ._fb_wire import dumps as _dumps, encode as _encode, reading as _reading
from .contracts import ContractRef as _ContractRef
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Prediction as _Prediction, Role as _Role

_UNIFORM_UNIT = _ContractRef("uniform_unit", "1")
_COUNTING = _f.CandidateMeasureRef(name="counting", version="1", args={})
_FINITE_EVALUATION = _ContractRef("sui.f.finite_evaluation", "1")
# 白紙の評価の範囲 (約束の紙 §5-0 の 2026-10-07〜08、F-a P-04、§6-9 H2)
_BLANK_SCOPE = _f.EvaluationScope(name="unbounded_total", version="1", H_ns=None, source=None)


@_dataclass
class ThinkPlan:
    """1 つの Qgen から始まる考える過程の計画 (P.units の持ち主)。steps は `_fb_boot.advance` が
    1 点ずつ保存する記録の列で、各仕事の終わりが決まった時に後続を足す。missing は対象つきの不足、
    unmet は元の「候補を作って比べる」処理の未達 (pG、M3) の理由。"""
    boot: object                 # BootPlan
    initial: object              # InitialProcess
    slot: str                    # initial の宣言の位置
    qgen: str                    # Qgen の Point
    wg: str                      # Wg の WorkId
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    unmet: list = _field(default_factory=list)
    done: set = _field(default_factory=set)       # 終わりを処理した WorkId
    responses: dict = _field(default_factory=dict)  # 段 → 確定返答の種類 (意味 3)
    descs: dict = _field(default_factory=dict)      # 後続の仕事の Desc (Publish で行を置く)
    prepared: object = None      # Ep の生きた発行物 (保存しない、§2-5-2)
    problem: object = None       # その FProblem
    round: str = ""              # 採用の後の継続の識別 (§6-10 K10)。最初の過程は ""


def open_continuation(state, boot, adopted) -> bool:
    """採用 A* を受けた継続 (§6-10 J6・K10、`reuse_candidates/1`): 最初の過程の CG を使い回して、A* をきっかけに
    o・j・文脈・EQ から同じ流れを作る。CG がまだ無ければ False (後で試す)。"""
    first = next((p for p in state.thinking.values() if p.boot is boot and not p.round), None)
    if first is None or "cg" not in first.points:
        return False
    plan = ThinkPlan(boot=boot, initial=first.initial, slot=first.slot, qgen=first.qgen, wg=first.wg,
                     round=":after:" + adopted, done={first.wg},
                     points={"cg": first.points["cg"], "cause": adopted})
    plan.steps = _context_steps(state, plan)
    state.thinking[first.wg + plan.round] = plan
    return True


def open_plan(state, boot, initial_slot, qgen) -> None:
    """Qgen の Publish と同じ歩で、考える過程の計画を置く (M3: Qgen の保存の前から Wg の義務を持つ)。"""
    desc = boot.points["desc:qgen"]
    state.thinking[desc.work_id] = ThinkPlan(boot=boot, initial=initial_slot.value, slot=initial_slot.slot,
                                             qgen=qgen, wg=desc.work_id)


# --- 最初の終わりと終わりの記録 T (§2-4-10 (5)、INV-15) ---

def _ends(state, row):
    """その仕事の口から来て受け付けた終わりの知らせ [(r, 番号, receipt)]。Compute は WorkFinished、
    D は DrawReturned だけ (D を名乗る WorkFinished は D の終わりにしない、M4)。"""
    kind = _fb.DrawReturned if isinstance(row.work, _fb.Draw) else _fb.WorkFinished
    out = []
    for number, r in row.reports:
        receipt = state.receipts.get(number)
        if receipt is None:
            continue
        event = receipt.envelope.event
        if type(event) is kind and event.work == row.work.desc.work_id:
            out.append((r, number, receipt))
    return out


def _clash(ends, *, unconfirmed=False) -> bool:
    """同じ仕事の、保存済みの両立しない終わりの知らせ (§2-4-10 (5) の X、§2-4-3 の Reports(X) は保存済みの受信)。
    不明と値の組だけでは食い違いにしない。unconfirmed=True は、受け付けた (P.receipts にある) 報告を保存の段に
    関わらず数える: 許可の判定 (開始・入場・後続) で保存の確認待ち・未保存を「無い」にしない (§2-4-3「記録が
    まだ無いことを安全の根拠にしない」、review FB2-R01-R3)。受け付けた報告はいずれ保存される (L-RECEIPT) ので、
    止める判定が後で外れることは無い。"""
    def counted(receipt):
        return unconfirmed or receipt.slots[0].entry is not None
    known = {_dumps(_encode(receipt.envelope.event)) for _r, _n, receipt in ends
             if counted(receipt) and not isinstance(receipt.envelope.event.outcome, (_fb.WorkUnknown, _fb.DrawUnknown))}
    return len(known) > 1


def _rows(state, plan):
    """その考える過程の、要求が解決した仕事の行 (Wg と、Publish した EQ・D・Ee の行)。"""
    for wid in (plan.wg, *(desc.work_id for desc in plan.descs.values())):
        row = state.works.get(wid)
        if row is not None and isinstance(row.work, (_fb.Compute, _fb.Draw)):
            yield row


def conflicts(state, plan, *, unconfirmed=False) -> list:
    """その考える過程の食い違いの用途。印を見ず、その都度、保存済みの終わりの報告から導く (§2-4-3「食い違いの
    判定は状態の関数。記録がまだ無いことを安全の根拠にしない」、review FB2-R01-R2 の 4 点)。unconfirmed=True は
    確認待ちの報告も数える (許可の判定用、FB2-R01-R3)。"""
    return [row.work.desc.purpose for row in _rows(state, plan)
            if _clash(_ends(state, row), unconfirmed=unconfirmed)]


def unmet(state, plan) -> list:
    """元の「候補を作って比べる」処理の未達 pG の理由。確定返答・使用条件の不足 (plan.unmet) と、保存済みの
    報告から導いた食い違い (初めでも後着でも、M3 :1971、review FB2-R07)。"""
    return list(plan.unmet) + [purpose + ":conflict" for purpose in conflicts(state, plan)]


def first_end(state, row):
    """論理の終わり: (r, receipt_seq) が最小の終わりの知らせ。receipt_seq は Post のロックの下で押した
    封筒の番号 (受付の順を流用しない)。その受信の記録が保存済みで、それより前の Post が全部受付済みの
    時だけ決める (§2-4-10 (5) の順序の表)。"""
    ends = _ends(state, row)
    if not ends:
        return None
    r, number, receipt = min(ends, key=lambda e: (e[0], e[1]))
    if any(queued.number < number for queued in state.queue):
        return None
    if receipt.slots[0].entry is None:
        return None
    return number, receipt


def _terminal_step(state, plan, row, number, receipt):
    """T (`sui.fb.work_terminal/1`、8 欄)。親は {request, first_receipt}。r は窓口が成立を確かめた時の M。"""
    event = receipt.envelope.event
    outcome = event.outcome
    first = receipt.slots[0].entry.cid
    if isinstance(outcome, _fb.WorkOutputs):
        kind, returned = "outputs", {"kind": "output", "value": _encode(outcome.outputs)}
    elif isinstance(outcome, _fb.DrawValue):
        kind, returned = "value", {"kind": "draw_value", "value": _encode(outcome.value)}
    elif isinstance(outcome, (_fb.WorkFailure, _fb.DrawFailure)):
        kind, returned = "failure", None
    else:
        kind, returned = "unknown", None
    generation = None
    if isinstance(event, _fb.WorkFinished):
        generation = {"started": _reading(event.started), "finished": _reading(event.finished)}
    basis = {"generation": generation,
             "failure": _encode(outcome.failure) if kind == "failure" else None,
             "unknown": _encode(outcome.unknown) if kind == "unknown" else None}
    request = row.work.request

    def build(state, plan):
        from ._fb_core import Slot, mono_ns
        view = _fixed_view(state, frozenset({request, first}))
        content = {"work": row.work.desc.work_id, "request": request, "stage": row.work.desc.purpose,
                   "first_receipt": first, "terminal_kind": kind, "returned": returned, "basis": basis,
                   "view": _encode(view)}
        body = _Observed(route="fb", content=_Payload.json(content), contract=_c.WORK_TERMINAL,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=_c.WORK_TERMINAL, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=frozenset({request, first}))

    return _Step(name="T:" + row.work.desc.work_id, build=build)


# --- 仕事の行を置く後続の要求 ---

def _desc(plan, purpose, stage_slot, trigger, reader, method, output, args, inputs, view):
    """段 2 の後続の Desc (§6-9 H8)。work_id は G3 と同じ論理の鍵。process・allocation は initial の宣言。"""
    d = plan.boot.d
    initial = plan.initial
    return _fb.Desc(
        work_id=_work_id(d, plan.slot, purpose, stage_slot + plan.round),
        process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
        trigger=frozenset({trigger}), purpose=purpose, stage_slot=stage_slot + plan.round, reader=reader,
        method=method, output_contract=output, args=args, input_points=frozenset(inputs),
        numerical_view=view, allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
        permissions=frozenset({_fb.BootSlot(declaration=d, slot=plan.slot),
                               _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))


def _promise(purpose, prefix):
    """PR / DF の Publish と同じ歩で、要求がまだ未解決の後続の仕事の行を置く (紙 O-11・O-12・INV-2.b・INV-5、
    review FB2-R04)。要求を準備した時に同じ行が本物の仕事に解決される。"""
    def on_prepared(state, plan, cid):
        from ._fb_core import plan_work
        plan_work(state, _work_id(plan.boot.d, plan.slot, purpose, prefix + plan.slot + plan.round), purpose,
                  plan.boot.declaration.scope.value)
    return on_prepared


def _uses(desc) -> set:
    """要求の外側 inputs に写す実使用の参照 (§2-5-9「各仕事要求では BootSlot の宣言 Point、reader、trigger、
    input_points、用途別 args の宣言された使用参照を照合」、review FB2-R03)。"""
    out = set(desc.input_points) | {t.point for t in desc.trigger}
    out |= {slot.declaration for slot in (desc.process, desc.allocation, *desc.permissions)}
    if desc.reader is not None:
        out.add(desc.reader)
    args = desc.args
    if isinstance(args, _fb.EvaluationPrepareArgs):
        # 固定根 fixed_parents は数値の像の境界 (本文に書く証拠 E) で、この決定の外側 inputs にしない。
        # F-a A-03 は Decided の inputs がその記録の祖先にあることを要り、EQ の親の式 (§2-5-9) は固定根を含まない
        request = args.input
        out |= {request.model, request.candidates, request.context, *request.preferences}
    elif isinstance(args, _fb.DrawArgs):
        out.add(args.prepared)
    elif isinstance(args, _fb.EvaluationArgs):
        out |= {args.evaluation_request, args.prepared, args.draw}
    return out


_CREATE = {"EQ": "評価要求を作る", "D": "抽選要求を作る", "Ee": "くじ後の評価要求を作る"}
_ENTER = {"evaluation_prepare": "評価の準備へ入る", "selection_draw": "抽選の仕事へ入る", "evaluation": "くじ後の評価へ入る"}
_REQUEST_CONTRACT = {"evaluation_prepare": _c.EVALUATION_REQUESTED, "selection_draw": _c.DRAW_REQUESTED,
                     "evaluation": _c.WORK_REQUESTED}


def _request_step(name, contract, kind, desc_of, parents_of):
    """要求の記録 (Decided / MODEL) と、Publish と同じ歩で置く仕事の行 (INV-2)。作成の門 (G6) は保存予定の
    Desc を持つ候補から。"""

    def uses(state, plan):
        from ._fb_uses import Candidate, contract_name, starts_of
        desc = desc_of(state, plan)
        if desc is None:
            return None
        candidate = Candidate(contract=contract, content={"desc": _encode(desc)}, use="")
        return starts_of(_CREATE[name], {contract_name(contract): candidate})

    def build(state, plan):
        from ._fb_core import Slot
        desc = desc_of(state, plan)
        if desc is None:
            return None
        plan.descs[name] = desc
        ledger = state.ledger
        inputs = tuple(ledger.record(p).id for p in sorted(_uses(desc)))
        body = _Decided(inputs=inputs, content=_Payload.json({"desc": _encode(desc)}), contract=contract)
        return Slot(contract=contract, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, parents_of(plan, desc)))

    def prepared(state, plan, cid):
        from ._fb_core import add_work
        add_work(state, kind(request=cid, desc=plan.descs[name]), plan.boot.declaration.scope.value)

    return _Step(name=name, build=build, on_prepared=prepared, uses=uses)


# --- Wg の返答 → CG (H6・H9) ---

def _model_operations(state, model):
    document = state.ledger.record(model).body.content.as_json()["document"]
    return tuple(op["id"] for op in document["operations"])


def _candidates(state, plan, row, outcome):
    """Wg の出力を Qgen・Desc と全照合した候補の宣言。NoCandidates は "none"、照合できなければ
    理由を返す (CG を作らない)。Qgen に input_order は無いので、その欄と比べない (H6)。"""
    desc = row.work.desc
    outputs = outcome.outputs
    if outputs.contract != desc.output_contract:
        return "cg:output_contract"
    value = outputs.value
    if not isinstance(value, _Mapping) or set(value) != {"kind", "value"}:
        return "cg:shape"
    if value["kind"] == "no_candidates":
        return "none" if isinstance(value["value"], _Mapping) and not value["value"] else "cg:shape"
    if value["kind"] != "candidates":
        return "cg:shape"
    try:
        declaration = _f._decode(value["value"], _f.FCandidateDeclaration)
    except (_f.FInputError, TypeError, KeyError, ValueError):
        return "cg:shape"
    args = desc.args
    generation = declaration.generation
    if declaration.model != args.model:
        return "cg:model"
    if generation.generator != desc.method:
        return "cg:generator"
    if _dumps(_f._encode(generation.args)) != _dumps(_f._encode(args.generator_args)):
        return "cg:args"
    if tuple(generation.basis) != tuple(args.basis):
        return "cg:basis"
    if generation.draws:
        return "cg:draws"   # D6: 生成用のくじを要しない方法だけ
    order = declaration.input_order
    if not order or len(set(order)) != len(order):
        return "cg:input_order"
    # 生成方法の契約 (H9)。意味を知らない方法の出力は信じない
    if desc.method != _c.MODEL_OPERATIONS:
        return "cg:method_semantics"
    if order != _model_operations(state, args.model) or declaration.measure != _COUNTING \
            or tuple(a.candidate for a in declaration.continuation.after) != order \
            or any(a.policy is not None for a in declaration.continuation.after):
        return "cg:method_semantics"
    return declaration


def _cg_step(row, first, declaration):
    def build(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        qgen, model = row.work.request, row.work.desc.args.model
        basis = tuple(dict.fromkeys((ledger.record(qgen).id, ledger.record(model).id,
                                     *(ledger.record(p).id for p in declaration.generation.basis))))
        body = _Prediction(target="candidate_declaration", about=(ledger.record(qgen).id,), basis=basis,
                           content=_Payload.json(_f._encode(declaration)), contract=_fc.CANDIDATE_DECLARATION)
        return Slot(contract=_fc.CANDIDATE_DECLARATION, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {qgen, first, *declaration.generation.basis}))
    return _Step(name="cg", build=build)


# --- 文脈 o・j と EQ (H1・H2・H3・H8) ---

def _context_steps(state, plan):
    from ._fb_boot import _clock_source
    source_holder = {}

    def reading_step(name):
        def build(state, plan):
            from ._fb_core import Slot, mono_ns
            source = _clock_source(state)
            if source is None:
                return None
            # 文脈は宣言した時計の契約で o・j を認証する (F-a A-17)。名乗らない時計では作らない
            if state.ledger.record(source).body.content.as_json().get("measurement") is None:
                _short(plan, "context:clock_contract")
                return None
            if name == "o":
                # o: その時の保存済みの点の境界 X を固定する (H1)
                plan.points["X"] = frozenset(state.ledger.heads())
            source_holder["source"] = source
            ns = mono_ns(state.clock)
            value = _f.FClockReadingFact(source=source, reading=_f.ClockReading(run=state.clock.run, time_ns=ns))
            body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CLOCK_READING,
                             received_ns=ns)
            # 親 (§6-9 H1): o = 時計の宣言と、読むきっかけの CG の来歴 / j = 時計の宣言と o (j は o の後に読んだ)
            cause = plan.points.get("cause", plan.points["cg"]) if name == "o" else plan.points["o"]
            return Slot(contract=_fc.CLOCK_READING, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                        parents=_front(state.ledger, {source, cause}))
        return _Step(name=name, build=build)

    def build_context(state, plan):
        from ._fb_core import Slot, mono_ns
        origin = plan.boot.points["origin"]
        # 段 2 の道で行う確認は無い (行った確認は順に残す、§6-9 H1)
        value = _f.FContextObserved(knowledge_origin=origin, observation_reading=plan.points["o"],
                                    judgment_reading=plan.points["j"], check_events=())
        body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CONTEXT_OBSERVED,
                         received_ns=mono_ns(state.clock))
        # 親は origin と o・j (行った確認があればその来歴も)。境界 X を機械的に親へ足さない (§6-9 H1)
        return Slot(contract=_fc.CONTEXT_OBSERVED, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {origin, plan.points["o"], plan.points["j"]}))

    def eq_desc(state, plan):
        initial = plan.initial
        if initial.method.contract != _FINITE_EVALUATION or initial.method.args != {}:
            _short(plan, "eq:method")
            return None
        if _preferences(state, plan):
            _short(plan, "eq:preferences")   # 好みの記録があるのに白紙として扱わない (§6-9 H2)
            return None
        origin, context, cg = plan.boot.points["origin"], plan.points["context"], plan.points["cg"]
        # 固定根は出来事の境界 (o の時点の X と文脈)。モデル・CG は FFactsRequest の型つき参照から辿る (F-a の
        # read_draw は selection のくじの祖先に固定根を要るので、Prediction を固定根に入れると必ず破れる)
        fixed = tuple(sorted(state.ledger.maximal(frozenset({context, *plan.points["X"]}))))
        request = _f.FFactsRequest(fixed_parents=fixed, model=initial.model, candidates=cg, preferences=(),
                                   scope=_BLANK_SCOPE, context=context, method=initial.method.contract)
        # Xnum の像の境界には型つき参照で読む Prediction (モデル・CG) を直接足す。台帳の heads と出来事の
        # 祖先は Prediction を含まない (§6-9 H5「実祖先 + 宣言した追加の閉包」)
        # 固定根の祖先の記録が型つきで指す Prediction (段 3 の law・reading・R* など) も直接足す (§6-10 K12)
        from ._fb_update import referenced_predictions
        view = _fixed_view(state, frozenset(fixed) | {initial.model, cg} | referenced_predictions(state, fixed))
        plan.points["Xnum"] = view
        trigger = _fb.Trigger(point=plan.points["cause"], slot="adopted") if plan.round             else _fb.Trigger(point=cg, slot="candidates")
        return _desc(plan, "evaluation_prepare", "prepare:" + plan.slot, trigger,
                     origin, _c.EVALUATION_PREPARE, _fc.MATH_ARTIFACT_V2,
                     _fb.EvaluationPrepareArgs(input=request, compiler=_fc.PREPARE_FACTS,
                                               budget=initial.prepare_budget,
                                               replay_logical_limit=initial.prepare_replay_logical_limit),
                     {context, initial.model, cg, origin}, view)

    def eq_parents(plan, desc):
        return {plan.boot.points["origin"], plan.points["context"], plan.points["cg"], plan.initial.model}

    return [reading_step("o"), reading_step("j"), _Step(name="context", build=build_context),
            _request_step("EQ", _c.EVALUATION_REQUESTED, _fb.Compute, eq_desc, eq_parents)]


def _preferences(state, plan) -> bool:
    """境界 X の中に好みの記録があるか。段 2 は好みの記録の無い白紙だけを通す (§6-9 H2)。"""
    from .records import Preference
    points = state.ledger.ancestors(plan.points["X"])
    return any(isinstance(state.ledger.record(p).body, Preference) for p in points)


def _hold(plan, reason) -> None:
    if reason not in plan.missing:
        plan.missing.append(reason)


def _short(plan, reason) -> None:
    """CG の後に分かった使用条件の不足: 対象つきの不足を持ち、元の「候補を作って比べる」処理の未達 pG にも
    残す (紙 :1970「EndKnown 後、CG か EQ の使用の条件の不足」、review FB2-R05)。"""
    _hold(plan, reason)
    if "evaluation:" + reason not in plan.unmet:
        plan.unmet.append("evaluation:" + reason)


# --- 発行物の照合 (H5・H8) ---

def _artifact_claim(issued, row, outcome):
    """仕事が返した出力と生きた発行物を、要求と全照合する。合えば (artifact の正準 JSON, 値) を返し、
    合わなければ理由。Ep は入力・予算・registry・像、Ee はそれに加えて prepared の calls と同じ DF。"""
    from ._f_handles import require_issued
    if issued is None:
        return "artifact:missing"
    try:
        require_issued(issued, _f.FMathArtifact)
    except (TypeError, _f.FInputError):
        return "artifact:not_issued"
    desc = row.work.desc
    if outcome.outputs.contract != desc.output_contract:
        return "artifact:output_contract"
    raw = _json.loads(issued.canonical_bytes)
    # 照合は正準 JSON の bytes で (True と 1 を同じにしない、R14)
    if _dumps(_encode(outcome.outputs.value)) != _dumps(raw):
        return "artifact:output"
    return raw, issued.value


def _check_prepare(state, plan, raw, desc):
    args = desc.args
    if raw["compiler"] != _f._encode(args.compiler) or raw["input"] != {"kind": "facts", "value": _f._encode(args.input)}:
        return "artifact:input"
    view = desc.numerical_view
    if raw["environment"] != {"reader_view_key": view.reader_view_key, "registry_key": view.registry_key}:
        return "artifact:environment"
    if raw["calls"][0]["args"] != {"budget": _f._encode(args.budget)}:
        return "artifact:budget"
    return None


def _check_evaluate(state, plan, raw, desc):
    args = desc.args
    view = _fixed_view(state, frozenset(desc.numerical_view.boundary | desc.input_points))
    if raw["environment"] != {"reader_view_key": view.reader_view_key, "registry_key": view.registry_key}:
        return "artifact:environment"   # くじの事実を足した像 (Xnum と分ける、H8)
    prepared = _json.loads(plan.prepared.canonical_bytes)
    calls = raw["calls"]
    if raw["input"] != prepared["input"] or calls[:len(prepared["calls"])] != prepared["calls"]:
        return "artifact:prepared"
    rest = calls[len(prepared["calls"]):]
    budget = _f._encode(args.budget)
    if not rest or rest[0]["op"] != "bind_draw" or rest[0]["args"].get("draw") != args.draw \
            or rest[0]["args"].get("budget") != budget:
        return "artifact:draw"
    if any(call["args"].get("budget") not in (None, budget) for call in rest):
        return "artifact:budget"
    return None


def _product_steps(row, first, raw, value, name, contract):
    """artifact (P) を保存してから、それを指す PR / EV (O) を保存する。T はそれらの前提にしない。"""
    request = row.work.request

    def build_artifact(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        inputs = sorted(row.work.desc.input_points)
        # 親の必要入力 (§2-5-10 math_artifact/2) には固定根も入る。これで PR → D → DF が問題の固定根の
        # 子孫になる (F-a の read_draw は selection のくじの祖先に問題の親を要る)
        args = row.work.desc.args
        needed = tuple(args.input.fixed_parents) if isinstance(args, _fb.EvaluationPrepareArgs) else ()
        body = _Prediction(target="math_artifact", about=(ledger.record(request).id,),
                           basis=tuple(ledger.record(p).id for p in (request, *inputs)),
                           content=_Payload.json(raw), contract=_fc.MATH_ARTIFACT_V2)
        return Slot(contract=_fc.MATH_ARTIFACT_V2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {request, first, *inputs, *needed}))

    def build_logical(state, plan):
        from ._fb_core import Slot, mono_ns
        artifact = plan.points["artifact:" + name]
        content = {"request": request, "report": first, "artifact": artifact}
        body = _Observed(route="fb", content=_Payload.json(content), contract=contract,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=contract, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {request, first, artifact}))

    def uses_logical(state, plan):
        """PR / EV の作成の門 (G6-PR-CREATE・G6-EV-CREATE): request・report・artifact を使う候補から。"""
        from ._fb_uses import Candidate, contract_name, starts_of
        artifact = plan.points.get("artifact:" + name)
        if artifact is None:
            return None
        candidate = Candidate(contract=contract, content={"request": request, "report": first, "artifact": artifact}, use="")
        return starts_of("準備の結果を作る" if name == "PR" else "評価の結果を作る", {contract_name(contract): candidate})

    return [_Step(name="artifact:" + name, build=build_artifact), _Step(name=name, build=build_logical, uses=uses_logical)]


# --- くじ (H4・M4) ---

def _stream_id(plan) -> str:
    import hashlib
    key = {"domain": "sui.fb.stream_id/1", "boot": plan.boot.d, "position": plan.slot, "purpose": "selection"}
    return "stream:" + hashlib.sha256(_dumps(key)).hexdigest()


def _draw_steps(state, plan):
    def d_desc(state, plan):
        pr = plan.points["PR"]
        # 同じ問題への別の発火 (採用の後の継続) は新しい ordinal (§6-10 J6)。保存の再試行では作り直さない
        ordinal = sum(1 for other in state.thinking.values() if other is not plan and other.problem is not None
                      and other.problem.problem_key == plan.problem.problem_key and "D" in other.descs)
        request = _f.DrawRequest(purpose="selection", context_key=plan.problem.problem_key, ordinal=ordinal,
                                 law=_UNIFORM_UNIT, args={})
        return _desc(plan, "selection_draw", "draw:" + plan.slot, _fb.Trigger(point=pr, slot="prepared"),
                     plan.boot.points["origin"], plan.initial.draw.contract, _c.DRAW_REPORT,
                     _fb.DrawArgs(prepared=pr, stream_id=_stream_id(plan), request=request),
                     {pr}, plan.points["Xnum"])

    return [_request_step("D", _c.DRAW_REQUESTED, _fb.Draw, d_desc, lambda plan, desc: {plan.points["PR"]})]


def _draw_value(outcome):
    """selection の値 {u}、0 ≤ u < 1 (F-a `_validate_draw`)。合わなければ None。"""
    value = outcome.value
    try:
        if not isinstance(value, _Mapping) or set(value) != {"u"}:
            return None
        u = _f._decode(value["u"], _f._Fraction)
    except (_f.FInputError, TypeError, ValueError):
        return None
    return value if 0 <= u < 1 else None


def _df_step(row, first, value):
    args = row.work.desc.args
    fact = _f.FDrawFact(generator=row.work.desc.method, stream_id=args.stream_id, request=args.request, value=value)

    def build(state, plan):
        from ._fb_core import Slot, mono_ns
        body = _Observed(route="fb", content=_Payload.json(_f._encode(fact)), contract=_fc.DRAW_FACT,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=_fc.DRAW_FACT, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=frozenset({row.work.request, first}))

    def uses(state, plan):
        """DF の作成の門 (G6-DF-CREATE)。DF の D への論理辺は実親 (D の要求・最初の受け取り) から (REF-DF-LOGICAL-LINK・
        REF-DF-PREPARED-LINK・REF-DF-FIRST-RECEIPT、紙 v0.34 Z26)。候補は保存予定の実親を持って門を通る。"""
        from ._fb_uses import Candidate, starts_of
        return starts_of("くじの事実を作る", {"sui.f.draw_fact/1": Candidate(
            contract=_fc.DRAW_FACT, content=_f._encode(fact), use="", parents=(row.work.request, first))})

    return _Step(name="DF", build=build, uses=uses)


def _du_step(row, first, unknown):
    def build(state, plan):
        from ._fb_core import Slot, mono_ns
        view = _fixed_view(state, frozenset({row.work.request, first}))
        content = {"draw_request": row.work.request, "first_receipt": first, "unknown_basis": _encode(unknown),
                   "view": _encode(view)}
        body = _Observed(route="fb", content=_Payload.json(content), contract=_c.DRAW_UNKNOWN,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=_c.DRAW_UNKNOWN, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=frozenset({row.work.request, first}))
    return _Step(name="DU", build=build)


def _ee_steps(state, plan):
    def ee_desc(state, plan):
        eq, pr, df = plan.points["EQ"], plan.points["PR"], plan.points["DF"]
        return _desc(plan, "evaluation", "evaluate:" + plan.slot, _fb.Trigger(point=df, slot="draw"),
                     plan.boot.points["origin"], _c.EVALUATE_FROM_DRAW, _fc.MATH_ARTIFACT_V2,
                     _fb.EvaluationArgs(evaluation_request=eq, prepared=pr, draw=df,
                                        budget=plan.initial.evaluate_budget),
                     {eq, pr, df, plan.points["artifact:PR"]}, plan.points["Xnum"])

    def parents(plan, desc):
        return {plan.points["EQ"], plan.points["PR"], plan.points["DF"]}

    return [_request_step("Ee", _c.WORK_REQUESTED, _fb.Compute, ee_desc, parents)]


def _selection_step():
    def build(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        ev = plan.points["EV"]
        inputs = (ledger.record(ev).id, ledger.record(plan.points["artifact:EV"]).id, ledger.record(plan.points["DF"]).id)
        body = _Decided(inputs=inputs, content=_Payload.json({"evaluated": ev}), contract=_c.SELECTION)
        return Slot(contract=_c.SELECTION, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=frozenset({ev}))

    def uses(state, plan):
        """選択の記録の作成の門 (G6-SELECTION-CREATE)。"""
        from ._fb_uses import Candidate, starts_of
        if "EV" not in plan.points:
            return None
        candidate = Candidate(contract=_c.SELECTION, content={"evaluated": plan.points["EV"]}, use="")
        return starts_of("選択の記録を作る", {"sui.fb.selection/1": candidate})

    return _Step(name="S", build=build, uses=uses)


# --- 進め方 ---

def _finish(state, plan, row):
    """row の論理の終わりが決まっていれば、T と許された後続を計画する。"""
    wid = row.work.desc.work_id
    if wid in plan.done:
        return
    found = first_end(state, row)
    if found is None:
        return
    number, receipt = found
    plan.done.add(wid)
    outcome = receipt.envelope.event.outcome
    first = receipt.slots[0].entry.cid
    purpose = row.work.desc.purpose
    row.knowledge = ("success" if isinstance(outcome, (_fb.WorkOutputs, _fb.DrawValue))
                     else "failure" if isinstance(outcome, (_fb.WorkFailure, _fb.DrawFailure)) else "unknown")
    # T は最初の終わりから作る。全報告からの食い違いは別の判定で、見えていれば後続を作らない
    # (§2-4-10 (5)「最初の終わりの選択と、全報告集合からの Conflict は別の判定」・§2-4-3)。pG と表示は unmet と
    # conflicts がその都度導く
    plan.steps.append(_terminal_step(state, plan, row, number, receipt))
    # 食い違いが見えていても、最初の終わりの確定返答の判定 (意味 3) と不足の記録は全部やり、後続の記録を足す
    # 所だけ止める (FB2-R08: NoCandidates・NoDecision が先でも意味 3 に出す)
    clash = _clash(_ends(state, row), unconfirmed=True)

    def follow(*steps):
        if not clash:
            plan.steps.extend(steps)

    if row.knowledge != "success":
        plan.responses[purpose] = row.knowledge   # 意味 3 は最初の終わりの確定返答 (食い違いと別の欄)
        if purpose == "selection_draw" and row.knowledge == "unknown":
            follow(_du_step(row, first, outcome.unknown))
        plan.unmet.append(f"{purpose}:{row.knowledge}")
        return
    if purpose == "candidate_generation":
        declaration = _candidates(state, plan, row, outcome)
        if declaration == "none":
            plan.responses[purpose] = "no_candidates"
            plan.unmet.append("candidate_generation:no_candidates")
        elif isinstance(declaration, str):
            _hold(plan, declaration)
            plan.unmet.append("candidate_generation:" + declaration)
        else:
            follow(_cg_step(row, first, declaration), *_context_steps(state, plan))
    elif purpose in ("evaluation_prepare", "evaluation"):
        issued = next((item for n, item in row.issued if n == number), None)
        claim = _artifact_claim(issued, row, outcome)
        if not isinstance(claim, str):
            raw, value = claim
            check = (_check_prepare if purpose == "evaluation_prepare" else _check_evaluate)(state, plan, raw, row.work.desc)
            claim = check if check is not None else claim
        if isinstance(claim, str):
            _hold(plan, claim)
            plan.unmet.append(f"{purpose}:{claim}")
            return
        raw, value = claim
        allowed = (_f.FProblem, _f.NoDecision) if purpose == "evaluation_prepare" else (_f.Selected, _f.NoDecision)
        if not isinstance(value, allowed):
            # 正規に発行された途中の型 (例: くじを結んだだけの FRoot) を終わりにしない (review FB2-R02)
            _hold(plan, "artifact:type")
            plan.unmet.append(f"{purpose}:artifact:type")
            return
        name = "PR" if purpose == "evaluation_prepare" else "EV"
        steps = _product_steps(row, first, raw, value, name, _c.PREPARED if name == "PR" else _c.EVALUATED)
        if name == "PR" and isinstance(value, _f.FProblem):
            steps[1].on_prepared = _promise("selection_draw", "draw:")
        follow(*steps)
        if isinstance(value, _f.NoDecision):
            plan.responses[purpose] = "no_decision"   # 正規の返答。D・selection を作らない
            plan.unmet.append(f"{purpose}:no_decision")
        elif name == "PR" and not clash:
            plan.prepared, plan.problem = issued, value
            follow(*_draw_steps(state, plan))
        elif isinstance(value, _f.Selected):
            follow(_selection_step())
    elif purpose == "selection_draw":
        value = _draw_value(outcome)
        if value is None:
            _hold(plan, "draw:value")
            plan.unmet.append("selection_draw:draw:value")
            return
        df = _df_step(row, first, value)
        df.on_prepared = _promise("evaluation", "evaluate:")
        follow(df, *_ee_steps(state, plan))


def advance(state) -> None:
    """各考える過程の仕事の終わりを処理し、計画した記録を 1 点ずつ保存する。後から食い違いが見えたら、
    作った記録は消さず、まだ作っていない後続を作らない (§2-4-3「後着で食い違ったら…新しい使用では使えない」)。
    各歩の新しい使用は、その歩が使う記録を起点に同じ門を通る (G6、T-G6 の行。FB3-R01-R5)。"""
    from ._fb_boot import advance as _advance
    for plan in state.thinking.values():
        for name in ("wg", "EQ", "D", "Ee"):
            wid = plan.wg if name == "wg" else (plan.descs[name].work_id if name in plan.descs else None)
            row = state.works.get(wid) if wid is not None else None
            if row is None or not isinstance(row.work, (_fb.Compute, _fb.Draw)) or not _saved_request(state, row):
                continue
            _finish(state, plan, row)
        blocked = bool(conflicts(state, plan, unconfirmed=True)) or _root_blocked(state, plan)
        _advance(state, plan, build=lambda step, plan=plan, blocked=blocked: _allowed(state, plan, step, blocked))


def _allowed(state, plan, step, blocked) -> bool:
    """歩の新しい使用の門: T は診断の保存 (いつも)。過程の行の終わりの食い違いか継続のきっかけの食い違いが
    見えていれば作らない。歩が使う記録の出発点 (step.uses、T-G6) があれば同じ門で判定する。"""
    from ._fb_update import gate, hold_label
    if step.name.startswith("T:"):
        return True
    if blocked:
        return False
    if step.uses is None:
        return True
    starts = step.uses(state, plan)
    if starts is None:
        return True   # 前提がまだ無い (build が None を返して待つ)
    verdict = gate(state, starts)
    if verdict == "blocked":
        _hold(plan, step.name + ":use_conflict")
    elif hold_label(verdict) is not None:
        _hold(plan, step.name + ":uses:" + hold_label(verdict))
    return verdict == "open"


def continuation_starts(state, plan) -> list:
    """継続を開く操作の出発点 (G6-CONTINUE-A・CG・DECL): 継続の契約が使う A*・CG・宣言を表から。"""
    from ._fb_uses import starts_of
    return starts_of("継続を開く", {"sui.fb.belief_adopted/1": plan.points["cause"],
                                   "sui.f.candidate_declaration/1": plan.points["cg"],
                                   "sui.fb.boot_declaration/1": plan.boot.d})


def _root_blocked(state, plan) -> bool:
    """採用の後の継続 (§6-10 K10) の過程の全部の歩は、その過程の行 (Wg・EQ・D・Ee) の終わりに加えて、きっかけの
    A* に依存する (EQ の trigger、以後の歩は EQ の子孫)。継続の契約が使う A*・CG・宣言の閉包を、段 3 の新しい
    使用の門で毎回見る (G6「開いた後も EQ の作成・入場と次の結論の使用で毎回」)。最初の過程には無い。"""
    if not plan.round:
        return False
    from ._fb_update import gate
    return gate(state, continuation_starts(state, plan)) != "open"


def blocked(state, row, stage="入場") -> bool:
    """row がまだ本体に入っていない考える過程の仕事で、その過程に食い違いが見えている (紙 :864: Launch の後・
    入場の前に上の段の食い違いが保存されたら EnterWorker を許さない。review FB2-R01)、または、その仕事の要求を
    起点にした開始・入場の門 (G6-START-*・G6-*-ENTER) が開いていない。測る仕事は対象外。"""
    if row.ticket_used:
        return False
    wid = row.work.desc.work_id
    for plan in state.thinking.values():
        if wid == plan.wg or any(desc.work_id == wid for desc in plan.descs.values()):
            # 印でなく保存済みの報告から (FB2-R01-R2)。確認待ち・未保存の受け付けた報告も止める側に (FB2-R01-R3)
            if conflicts(state, plan, unconfirmed=True) or _root_blocked(state, plan):
                return True
            starts = enter_starts(state, row, stage)
            if starts is None:
                return False   # Wg (候補の生成) の開始・入場に T-G6 の行は無い
            from ._fb_update import gate
            return gate(state, starts) != "open"
    from ._fb_update import blocked as update_blocked
    return update_blocked(state, row, stage)


def entrance(state, row):
    """考える過程の仕事の入場の門の材料: (出発点 = 入場の行 + 継続の行, ロックの中で見る安い条件 = 行の終わりの食い違い)。
    行の無い仕事 (Wg) は出発点 None で安い条件だけ。更新の仕事は `_fb_update.entrance`。"""
    wid = row.work.desc.work_id
    for plan in state.thinking.values():
        if wid == plan.wg or any(desc.work_id == wid for desc in plan.descs.values()):
            starts = enter_starts(state, row, "入場")
            if plan.round and "cause" in plan.points and "cg" in plan.points:
                starts = list(starts or ()) + continuation_starts(state, plan)
            return starts, (lambda: bool(conflicts(state, plan, unconfirmed=True)))
    from ._fb_update import entrance as update_entrance
    return update_entrance(state, row)


def enter_starts(state, row, stage):
    """考える過程の仕事の開始・入場の門の出発点 (G6-START-EQ/D/EE・G6-EP-ENTER・G6-D-ENTER・G6-EE-ENTER)。行の無い
    仕事 (Wg) は None。"""
    purpose = row.work.desc.purpose
    if purpose not in _ENTER:
        return None
    from ._fb_uses import Reader, contract_name, starts_of
    operation = "仕事の開始を確保する" if stage == "開始" else _ENTER[purpose]
    return starts_of(operation, {contract_name(_REQUEST_CONTRACT[purpose]): row.work.request}, reader=Reader(state.ledger))


def _saved_request(state, row) -> bool:
    from ._fb_core import _saved
    return _saved(state, row.work.request)


def prepared_for(state, row):
    """Ee の args.prepared と照合した Ep の生きた発行物 (H5)。ほかの仕事は None。"""
    if not (isinstance(row.work, _fb.Compute) and row.work.desc.purpose == "evaluation"):
        return None
    for plan in state.thinking.values():
        if plan.points.get("PR") == row.work.desc.args.prepared and plan.prepared is not None:
            return plan.prepared
    return None


# --- 表示 (意味 3・6、§6-9 H7) ---

_STAGE_PRODUCT = (("candidate_generation", "cg", "generated"), ("evaluation_prepare", "PR", "generated"),
                  ("evaluation", "EV", "generated"))


def _held(state, plan, name):
    """保存済みなら実在の Point、計画だけなら預かりの識別 (Unsaved)、無ければ None。"""
    point = plan.points.get(name)
    if point is not None:
        return point
    step = next((s for s in plan.steps if s.name == name and s.slot is not None), None)
    return _fb.Unsaved(plan=str(step.slot.record.id)) if step is not None else None


def _stage_work(plan, purpose):
    """その段の仕事の WorkId (Wg は Qgen の行、ほかは Publish した要求の Desc)。"""
    if purpose == "candidate_generation":
        return plan.wg
    name = {"evaluation_prepare": "EQ", "selection_draw": "D", "evaluation": "Ee"}[purpose]
    return plan.descs[name].work_id if name in plan.descs else None


def reading_statuses(state) -> tuple:
    """意味 3: 生成・準備・評価の到達と確定返答。正規の NoDecision・NoCandidates と、実行の
    Failure/Unknown を分ける。selected は保存した selection だけ。根拠にその段の仕事の要求と
    終わりの記録 T を付ける (M1「各項目に判定に使った根拠の Point」)。"""
    out = []
    for plan in state.thinking.values():
        origin = plan.boot.points.get("origin")
        for purpose, name, reached in _STAGE_PRODUCT:
            target = _held(state, plan, name)
            response = plan.responses.get(purpose, "none")
            wid = _stage_work(plan, purpose)
            row = state.works.get(wid) if wid is not None else None
            terminal = _held(state, plan, "T:" + wid) if wid is not None else None
            if target is None and response == "none" and terminal is None:
                continue   # 最初の終わり T があれば、生成物が無くても段の到達を示す (FB2-R08)
            basis = tuple(x for x in (target, row.work.request if row is not None else None, terminal, plan.qgen)
                          if x is not None)
            out.append(_fb.ReadingStatus(
                target=target if target is not None else plan.qgen, reader=origin,
                reached=reached if isinstance(target, str) else "none", response=response,
                adopted=None, stale=None,
                selected=plan.points.get("S") if purpose == "evaluation" else None,
                evidence=_fb.StatusBasis(view=None, basis=basis)))
    return tuple(out)


def purpose_statuses(state) -> tuple:
    """意味 6: 元の「候補を作って比べる」処理の未達 pG (M3)。局所の処理 (T の計画) は済み、
    元の目的は未達のまま (handled と unmet が両方真)。"""
    out = []
    for plan in state.thinking.values():
        if not unmet(state, plan):
            continue
        initial = plan.initial
        out.append(_fb.PurposeStatus(
            obligation=plan.qgen, o_id="C-OG.run[Wg]", condition="handle", role="compare",
            process=_fb.BootSlot(declaration=plan.boot.d, slot=initial.process_slot),
            reader=plan.boot.points.get("origin"), target=plan.qgen, part=None,
            handled=True, handed_to=None, unmet=True,
            evidence=_fb.StatusBasis(view=None, basis=(plan.qgen,))))
    return tuple(out)
