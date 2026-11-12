"""信念の更新の流れ (紙 F-b §6-2・§6-4・§6-10 J1〜J6・K2〜K9・K13、段 3 の最初の輪 = Z41)。

δ (`sui.fb.saved_segment_update/1`) 1 つにつき更新の計画を 1 つ持つ。口の route_config と時計の source の
保存の後に法則 law と読み方 reading を作り、保存した原 Claim の結びつき B ごとに義務を 1 つ持つ (J1)。
義務ごとに、更新要求 Q* → 仕事 Wu → 終わりの記録 T → 結果 R* → 結果の取得 → 採用 A* か Stale を
1 点ずつ保存する。同じ系列では、前の義務の採用の判断の保存が確認されるまで次の Q* を作らない (K13)。
本体が終わりの知らせを出さずに止まった義務は、それを結末として次へ進む (K15。記録は足さない)。

使用の門 (紙 §2-5-19-6・§2-5-19-10・FB3-R01-R2、段 3 の残り (イ)): 義務が結論として頼る記録 (自分の原報告と、前の採用の
系列をさかのぼった全部の原報告) に食い違った鍵の原報告があれば、まだ作っていない記録 (Q*・R*・結果の取得・採用) を
作らない。作った記録は消さず、準備済みの記録の保存と診断の T は続ける。判定は毎回の settle で受け付けた配送から導く。
止めるまでで、戻し方は S5、本人が選ぶ口は S10。

最初の輪の 1 周目は正常な道だけ。★ 1 周の後: ホストの監視の記録と入力の取得 (K4・K5)、失敗の後の目的の表示 (J9-c)。
"""

import hashlib as _hashlib
from dataclasses import dataclass as _dataclass, field as _field

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from . import f_contracts as _fc
from ._fb_bind import clashed_reports as _clashed_reports
from ._fb_boot import Step as _Step, _clock_source, _front, _record, advance as _advance, \
    fixed_view as _fixed_view
from ._fb_wire import dumps as _dumps, encode as _encode
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Prediction as _Prediction, Role as _Role


@_dataclass
class Obligation:
    """義務 (J1): 保存した原 Claim 1 つにつき 1 つ。steps は 1 点ずつ保存する記録、final はこの更新の結末。"""
    report: str
    binding: str
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    desc: object = None          # Wu の Desc (Q* の Publish で固定)
    done: bool = False           # Wu の終わりを処理した
    final: str | None = None     # adopted / stale / rejected / insufficient / failure / unknown / stopped / conflicted / issued:*
    acquired_ns: int | None = None   # 結果 R* を実際に取得した時の M の読み (最初の 1 回で固定、入り直しで取り直さない)


@_dataclass
class UpdatePlan:
    boot: object                 # BootPlan
    initial: object              # InitialProcess
    slot: str                    # initial の宣言の位置
    args: dict                   # δ の args (K2)
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    obligations: dict = _field(default_factory=dict)   # 原報告の Point → Obligation (見つけた順)
    chain: list = _field(default_factory=list)         # 保存を確認した採用 A* の Point (採用した順)。最後が系列の頭


class _Pair:
    """`_fb_boot.advance` に渡す (計画, 義務) の組。steps・points は義務の側。"""

    def __init__(self, plan, ob):
        self.plan, self.ob = plan, ob
        self.steps, self.points = ob.steps, ob.points

    def __iter__(self):
        return iter((self.plan, self.ob))


def _hold(plan, reason) -> None:
    if reason not in plan.missing:
        plan.missing.append(reason)


def _plain(value):
    """凍った写し (mappingproxy・tuple) を JSON の値へ。"""
    if hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _check_args(boot, args):
    """δ の args の形 (K2)。合わなければ理由。法則の値の意味 (正規化・channel の対応) は U が検査する。"""
    if not hasattr(args, "items") or set(args) != {"route", "law", "claims", "generation"}:
        return "delta:args"
    slots = {r.slot for r in boot.declaration.routes}
    if args["route"] not in slots:
        return "delta:route"
    law = args["law"]
    if not hasattr(law, "items") or set(law) != {"carrier_by_state", "channels", "rows"} or not law["channels"]:
        return "delta:law"
    for channel in law["channels"]:
        if set(channel) != {"id", "route_slots", "domain"} or not set(channel["route_slots"]) <= slots:
            return "delta:law"
    if not args["claims"] or any(set(e) != {"meaning", "channel"} for e in args["claims"]):
        return "delta:claims"
    if not hasattr(args["generation"], "items") or set(args["generation"]) != {"scope"}:
        return "delta:generation"
    return None


# --- 法則と読み方 (K3: Boot・時計・route の保存 → law → reading の順) ---

def _law_step():
    def build(state, plan):
        from ._fb_core import Slot
        source = _clock_source(state)
        law = plan.args["law"]
        names = [name for ch in law["channels"] for name in ch["route_slots"]]
        configs = [plan.boot.points.get("route_config:" + name) for name in names]
        if source is None or plan.boot.points.get("origin") is None or None in configs:
            return None
        d, routes = plan.boot.d, {r.slot: r.value for r in plan.boot.declaration.routes}
        channels = [{"id": ch["id"],
                     "process": _encode(_fb.BootSlot(declaration=d, slot=routes[ch["route_slots"][0]].process_slot)),
                     "route_configs": sorted(plan.boot.points["route_config:" + n] for n in ch["route_slots"]),
                     "domain": {"clock": _f._encode(state.clock.run), **ch["domain"]}} for ch in law["channels"]]
        content = {"model": plan.initial.model, "extends": None, "carrier_by_state": law["carrier_by_state"],
                   "channels": channels, "rows": law["rows"], "frame_relation": "independent_given_carrier"}
        ledger = state.ledger
        uses = (plan.initial.model, d, *sorted(set(configs)), source)
        body = _Prediction(target="count_law", about=(ledger.record(plan.initial.model).id,),
                           basis=tuple(ledger.record(p).id for p in uses),
                           content=_Payload.json(content), contract=_c.FINITE_JOINT_COUNT_LAW)
        return Slot(contract=_c.FINITE_JOINT_COUNT_LAW, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {d, *configs, source}))
    return _Step(name="law", build=build)


def _reading_step():
    def build(state, plan):
        from ._fb_core import Slot
        law = plan.points["law"]
        claims = [{"meaning": e["meaning"], "law": law, "channel": e["channel"]} for e in plan.args["claims"]]
        content = {"model": plan.initial.model,
                   "projection": {"contract": _f._encode(_c.FINITE_SEGMENT_PROJECTION),
                                  "args": {"frame": None, "claims": claims,
                                           "time_projection": {"contract": _f._encode(_c.SEGMENT_VALUE_ONLY),
                                                               "args": {}}}},
                   "generation": {"contract": _f._encode(_c.BOOTSTRAP_GENERATION), "args": plan.args["generation"]}}
        ledger = state.ledger
        law_slot = next(s.slot for s in plan.steps if s.name == "law")
        body = _Prediction(target="observation_plan", about=(ledger.record(plan.initial.model).id,),
                           basis=(ledger.record(plan.initial.model).id, ledger.record(law).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=law_slot.parents)
    return _Step(name="reading", build=build)


def _plan(state, boot):
    initial_slot = boot.declaration.initial
    initial = initial_slot.value
    method = initial.derivation.method
    if method.contract != _c.SAVED_SEGMENT_UPDATE:
        return None
    plan = UpdatePlan(boot=boot, initial=initial, slot=initial_slot.slot, args=_plain(method.args))
    reason = _check_args(boot, plan.args)
    if reason is not None:
        _hold(plan, reason)
    else:
        plan.steps = [_law_step(), _reading_step()]
    return plan


# --- 義務 (J1) と系列の頭 (K9・K13) ---

def _discover(state, plan) -> None:
    """保存した B のうち、δ の口の原 Claim に義務を置く (J1)。扱えない枝は意味の不足として示す。"""
    route = plan.boot.points.get("route_config:" + plan.args["route"])
    meanings = {(e["meaning"]["name"], e["meaning"]["version"]) for e in plan.args["claims"]}
    for slot in state.bindings.values():
        if slot.entry is None:
            continue
        b = slot.record.body.content.as_json()
        if b["route"] != route or b["report"] in plan.obligations:
            continue
        item = state.ledger.record(b["report"]).body.content.as_json()["item"]
        if item["kind"] != "claim":
            _hold(plan, "delta:branch:" + item["kind"])
            continue
        contract = item["value"]["contract"]
        if (contract["name"], contract["version"]) not in meanings:
            _hold(plan, "delta:claim_meaning")
            continue
        ob = Obligation(report=b["report"], binding=slot.entry.cid)
        ob.steps = [_q_step(ob)]
        plan.obligations[b["report"]] = ob


def _receipt_order(state, report):
    """原報告をホストが実際に受け取った順 (受信の M の読みと封筒の番号)。分からなければ None (CID の順で代えない)。"""
    for number, receipt in state.receipts.items():
        if any(slot.entry is not None and slot.entry.cid == report for slot in receipt.slots):
            return (receipt.envelope.received_ns, number)
    return None


def _undecided(ob) -> bool:
    """その義務の採用の判断を公開したが、保存の確認がまだ (K9: 確認待ちを「無い」にしない)。"""
    step = next((s for s in ob.steps if s.name == "decide"), None)
    return step is not None and step.slot is not None and step.slot.entry is None


def _head(plan):
    """前の採用 (K9・K13): 系列 (Q* を作った義務) の結末が全部出ていて、採用の判断が全部保存を確認済みなら、
    最後に採用した A* (無ければ None)。進行中・確認待ちがあれば "wait" (無いことを許可にしない)。終わりの知らせの
    無い停止 (K15) は結末の 1 つで、待たない。"""
    for ob in plan.obligations.values():
        if ob.desc is not None and (ob.final is None or _undecided(ob)):
            return "wait"
    return plan.chain[-1] if plan.chain else None


def _silent_stop(state, row) -> bool:
    """終わりの知らせの無い停止 (K15): 入場した本体の実際の停止をホストが観測し、その口から受け取った封筒が
    全部受付済みで、その中に終わりの知らせが無い。印を持たず、その都度 P.work から導く。形がおかしくて断った封筒
    (K17) は済んだものに数え、終わりの知らせには数えない。"""
    from ._fb_think import _ends
    return bool(row.entered and row.stopped and all(number in state.receipts or number in state.rejected for number, _r in row.reports)
                and not _ends(state, row))


def _next(state, plan):
    """次に Q* を作る義務: まだ要求の無い義務のうち、ホストが原報告を受け取った順で最初の 1 つ。
    受け取った順の分からない義務があれば選ばない。食い違いで止まった義務 (結末 conflicted) は、後ろを待たせない。"""
    waiting = [ob for ob in plan.obligations.values() if ob.desc is None and ob.final is None]
    orders = [(_receipt_order(state, ob.report), ob) for ob in waiting]
    if not orders:
        return None
    if any(order is None for order, _ob in orders):
        _hold(plan, "delta:receipt_order")
        return None
    return min(orders, key=lambda pair: pair[0])[1]


# --- 使用の門: 依存の食い違い (紙 §2-5-19-6・§2-5-19-10、FB3-R01-R2) ---

def uses_of(state, adopted) -> frozenset:
    """採用 A* が結論として頼る記録: その更新要求 Q* が読む全部 (原報告を含む、系列をさかのぼった閉包)。A* を作った
    義務が無ければ上げる (無いことを「頼っていない」にしない)。"""
    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.points.get("A") == adopted:
                return ob.desc.input_points
    raise KeyError(adopted)


def _conflicted(state, plan, ob, bad) -> bool:
    """依存の食い違い: その義務が結論として頼る記録に、食い違った鍵の原報告 bad がある。頼る記録は Q* が読む全部
    (`_inputs`)。Q* を作る前は、自分の原報告と、今の系列の頭が頼る記録で数える (頭が進めば頼る記録は増えるだけ)。"""
    if not bad:
        return False
    if ob.desc is not None:
        return not bad.isdisjoint(ob.desc.input_points)
    return ob.report in bad or bool(plan.chain) and not bad.isdisjoint(uses_of(state, plan.chain[-1]))


def belief_conflicted(state, boot, boundary, bad) -> bool:
    """boundary (保存済みの点の集合) に見える、その Boot の採用 A* のどれかが、食い違った鍵の原報告 bad に頼っている。
    評価は boundary に見える採用の頭を読み、頭が頼る記録は前の採用のそれを含むので、どれか 1 つで足りる。採用の記録は、
    保存の確認待ちでも置き場にあれば見える (準備した CID で数える)。"""
    seen = None
    for plan in state.updates.values():
        if plan.boot is not boot:
            continue
        for ob in plan.obligations.values():
            step = next((s for s in ob.steps if s.name == "decide"), None)
            if ob.points.get("decision") != "A" or step is None or step.slot is None \
                    or bad.isdisjoint(ob.desc.input_points):
                continue
            if seen is None:
                seen = state.ledger.ancestors(boundary)
            if step.slot.prepared.cid in seen:
                return True
    return False


def blocked(state, row) -> bool:
    """row がまだ本体に入っていない更新の仕事 Wu で、その要求 Q* の依存に食い違いが見えている (開始・入場の判定も
    同じ関数。保存の前の受け付けた配送も数える)。"""
    if row.ticket_used or row.work.desc.purpose != "belief_update":
        return False
    for plan in state.updates.values():
        for ob in plan.obligations.values():
            if ob.desc is not None and ob.desc.work_id == row.work.desc.work_id:
                return _conflicted(state, plan, ob, _clashed_reports(state))
    return False


def conflicts(state, plan, *, unconfirmed=False) -> list:
    """食い違いに頼る更新の対象 (表示用、その都度導く): 採用済みなら A*、止まった義務は Q* (まだ無ければ原報告)。
    別の結末 (stale・rejected・failure など) が出た義務は、その結末のまま。"""
    bad = _clashed_reports(state, unconfirmed=unconfirmed)
    return [ob.points.get("A") or ob.points.get("Q") or ob.report for ob in plan.obligations.values()
            if ob.final in (None, "conflicted", "adopted") and _conflicted(state, plan, ob, bad)]


# --- 更新要求 Q* (K6) ---

def _names(plan, ob):
    """Wu の stage_slot と WorkId (J4): δ の宣言の位置・用途・義務 (原報告) の名前空間つきの hash。Q* の CID・
    前の採用・B の CID は入れない。"""
    d = plan.boot.d
    key = {"delta": {"declaration": d, "slot": plan.initial.derivation.slot},
           "delta_contract": _encode(_c.SAVED_SEGMENT_UPDATE),
           "process": {"declaration": d, "slot": plan.initial.process_slot},
           "origin": plan.boot.points["origin"], "raw_report": ob.report, "role": "trigger",
           "purpose": "belief_update"}
    stage = "update:" + _hashlib.sha256(_dumps({"domain": "sui.fb.delta_stage/1", **key})).hexdigest()
    work = "sui.fb.work:" + _hashlib.sha256(_dumps({"domain": "sui.fb.delta_work/1", **key,
                                                    "stage_slot": stage})).hexdigest()
    return stage, work


def _inputs(state, plan, ob, prior) -> frozenset:
    """Q* が読む記録 (U が一次事実から作り直すのに要る全部): この観測の B・原報告・測る要求・読み方・法則・モデルと、
    前の採用があればその A*・R*・Q* と、その Q* が読んだ全部 (系列をさかのぼった閉包)。"""
    ledger = state.ledger
    b = ledger.record(ob.binding).body.content.as_json()
    out = {plan.boot.d, plan.boot.points["origin"], plan.initial.model, plan.points["law"], plan.points["reading"],
           ob.binding, ob.report, b["segment"], b["route"]}
    if prior is not None:
        adopted = ledger.record(prior).body.content.as_json()
        previous = ledger.record(adopted["request"]).body.content.as_json()["desc"]
        out |= {prior, adopted["result"], adopted["request"], adopted["acquisition"], *previous["input_points"]}
    return frozenset(out)


def _q_step(ob):
    drafted = {}   # build が作った Desc。準備が通った時 (prepared) に義務へ置く

    def build(state, plan_ob):
        from ._fb_core import Slot
        plan, ob = plan_ob
        if "reading" not in plan.points or _next(state, plan) is not ob:
            return None
        prior = _head(plan)
        if prior == "wait":
            return None
        d, initial, origin = plan.boot.d, plan.initial, plan.boot.points["origin"]
        stage, work_id = _names(plan, ob)
        inputs = _inputs(state, plan, ob, prior)
        desc = _fb.Desc(
            work_id=work_id,
            process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
            trigger=frozenset({_fb.Trigger(point=ob.report, slot="trigger")}),
            purpose="belief_update", stage_slot=stage, reader=origin,
            method=_c.FINITE_UPDATE_COMPUTE, output_contract=_c.UPDATE_RESPONSE,
            args=_fb.UpdateArgs(model=initial.model, prior=prior, observations=(
                _fb.ObservationUse(binding=ob.binding, reading=plan.points["reading"]),)),
            input_points=inputs, numerical_view=_fixed_view(state, inputs),
            allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=initial.derivation.slot),
                                   _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))
        # Desc を義務に置く (= 要求を作った印) のは、記録の準備が通った後 (紙 §2-4 :323「『済み』の印だけ先に
        # 置かない」)。ここで置くと、下の読みや準備が失敗した時に、入り直しで同じ義務の Q* を作り直せなくなる
        drafted["desc"] = desc
        ledger = state.ledger
        body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(inputs)),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.WORK_REQUESTED)
        return Slot(contract=_c.WORK_REQUESTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, inputs))

    def prepared(state, plan_ob, cid):
        from ._fb_core import add_work
        plan, ob = plan_ob
        ob.desc = drafted["desc"]
        add_work(state, _fb.Compute(request=cid, desc=ob.desc), plan.boot.declaration.scope.value)

    return _Step(name="Q", build=build, on_prepared=prepared)


# --- Wu の終わり → T・R*・結果の取得・採用 (K7〜K9) ---

def _issued_result(outputs):
    """issued の返答 (update_response/1) が運ぶ finite_update_result/1 の値。形が合わなければ None。"""
    value = outputs.value
    if outputs.contract != _c.UPDATE_RESPONSE or not hasattr(value, "items") or set(value) != {"kind", "value"}:
        return None
    return value["value"] if value["kind"] == "issued" else None


def _check_issued(state, ob, row, number, outcome):
    """K7: 発行物が入口 U の発行で、request・result・像・registry が要求と返答に全部合うか。合わなければ理由の語。"""
    from ._f_handles import require_issued
    from ._f_world import registry_view_key
    from .f_update2 import IssuedUpdate
    issued = next((item for n, item in row.issued if n == number), None)
    if issued is None:
        return "update:issued:missing"
    try:
        require_issued(issued, IssuedUpdate)
    except (TypeError, _f.FInputError, _f.FReplayMismatch):
        return "update:issued:not_issued"
    view = ob.desc.numerical_view
    if issued.request != ob.points["Q"] \
            or _dumps(_f._encode(issued.result)) != _dumps(_encode(_issued_result(outcome.outputs))):
        return "update:issued:target"
    if issued.numerical_view.boundary != view.boundary or issued.numerical_view.reader_view_key != view.reader_view_key \
            or issued.numerical_view.registry_key != view.registry_key \
            or issued.registry_key != registry_view_key(state.registry):
        return "update:issued:view"
    return issued


def _r_step(issued, first):
    def build(state, plan_ob):
        from ._fb_core import Slot
        plan, ob = plan_ob
        ledger, q, view = state.ledger, ob.points["Q"], issued.numerical_view
        content = {"request": q, "result": _f._encode(issued.result), "application_digest": issued.application_digest,
                   "numerical_view": {"boundary": sorted(view.boundary), "environment": {
                       "reader_view_key": view.reader_view_key, "registry_key": view.registry_key}},
                   "registry_key": issued.registry_key}
        # basis は要求と最初の終わりの原報告 (段 2 の math_artifact と同じ形)
        body = _Prediction(target="belief_update", about=(ledger.record(q).id,),
                           basis=(ledger.record(q).id, ledger.record(first).id),
                           content=_Payload.json(content), contract=_c.UPDATE_RESULT)
        return Slot(contract=_c.UPDATE_RESULT, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {q, first}))
    return _Step(name="R", build=build)


def _acquire_steps():
    """結果の取得 (§6-2 の 4、K5 の形): ホストが origin について R* の本文を台帳から実際に読み、その時の M の読み a を
    EA に残し、clock_reading と content_acquired を保存する。読みは最初に作った時に固定する (再試行で読み直さない)。"""
    def build_reading(state, plan_ob):
        from ._fb_core import Slot, mono_ns
        from .f_update2 import AcquisitionObservation
        plan, ob = plan_ob
        source = _clock_source(state)
        if source is None:
            return None
        r = ob.points["R"]
        if ob.acquired_ns is None:
            state.ledger.record(r)   # 本文を実際に読む
            a = mono_ns(state.clock)
            state.acquisitions.append(AcquisitionObservation(origin=plan.boot.points["origin"],
                                                             contents=frozenset({r}), acquired_ns=a))
            ob.acquired_ns = a   # 済んだ実際の取得は 1 回。この後で記録の準備に失敗しても、同じ取得のまま入り直す
        a = ob.acquired_ns
        value =_f.FClockReadingFact(source=source, reading=_f.ClockReading(run=state.clock.run, time_ns=a))
        body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CLOCK_READING,
                         received_ns=a)
        return Slot(contract=_fc.CLOCK_READING, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {source, r}))

    def build_acquired(state, plan_ob):
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        origin, r, clock = plan.boot.points["origin"], ob.points["R"], ob.points["a"]
        value = _f.ContentAcquired(origin=origin, contents=(r,), clock=clock)
        body = _Observed(route="fb", content=_Payload.json(_f._encode(value)), contract=_fc.CONTENT_ACQUIRED,
                         received_ns=mono_ns(state.clock))
        return Slot(contract=_fc.CONTENT_ACQUIRED, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {origin, r, clock}))

    return [_Step(name="a", build=build_reading), _Step(name="G", build=build_acquired)]


def _adopt_step():
    def build(state, plan_ob):
        """K9: 実際の前の採用 (系列の頭) が求まる時だけ決める。ほかの義務の判断が確認待ちなら待つ。先に Q* を
        作った義務が進行中なら待つ (止まった後で終わりの知らせが遅れて届いた義務は、後の義務より先に決める、K15 (4))。
        Q* の prior と系列の頭が同じなら A*、違えば Stale (失われた更新・二重の採用を作らない)。比較と公開は settle の
        ロックの中の 1 つの決定。"""
        from ._fb_core import Slot, mono_ns
        plan, ob = plan_ob
        for other in plan.obligations.values():
            if other is ob or other.desc is None or "Q" not in other.points:
                continue
            if _undecided(other) or (other.final is None and _earlier(plan, other, ob)):
                return None
        head = plan.chain[-1] if plan.chain else None
        ledger = state.ledger
        origin, q, r, g = plan.boot.points["origin"], ob.points["Q"], ob.points["R"], ob.points["G"]
        if ob.desc.args.prior == head:
            ob.points["decision"] = "A"
            content = {"origin": origin, "model": plan.initial.model, "previous": head, "request": q,
                       "result": r, "acquisition": g}
            uses = {origin, plan.initial.model, q, r, g} | ({head} if head else set())
            body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(uses)),
                            content=_Payload.json(content), contract=_c.BELIEF_ADOPTED)
            return Slot(contract=_c.BELIEF_ADOPTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                        parents=_front(ledger, {r, g} | ({head} if head else set())))
        ob.points["decision"] = "stale"
        content = {"origin": origin, "request": q, "result": r, "expected_previous": ob.desc.args.prior,
                   "actual_previous": head}
        body = _Observed(route="fb", content=_Payload.json(content), contract=_c.STALE, received_ns=mono_ns(state.clock))
        return Slot(contract=_c.STALE, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(ledger, {r, g}))
    return _Step(name="decide", build=build)


def _earlier(plan, other, ob) -> bool:
    """other の Q* が ob の Q* より先に作られたか (系列の順 = 義務が Q* を得た順)。"""
    order = [o for o in plan.obligations.values() if o.desc is not None]
    return order.index(other) < order.index(ob)


def _finish(state, plan, ob, row) -> None:
    """Wu の論理の終わり (INV-15) から T と、許された後続を計画する。"""
    from ._fb_think import _terminal_step, first_end
    found = first_end(state, row)
    if found is None:
        return
    number, receipt = found
    ob.done, ob.final = True, None   # 止まった後に遅れて届いた終わりの知らせも、ふつうの最初の終わり (K15 (4))
    outcome = receipt.envelope.event.outcome
    first = receipt.slots[0].entry.cid
    row.knowledge = ("success" if isinstance(outcome, _fb.WorkOutputs)
                     else "failure" if isinstance(outcome, _fb.WorkFailure) else "unknown")
    ob.steps.append(_terminal_step(state, plan, row, number, receipt))
    if row.knowledge != "success":
        ob.final = row.knowledge
        return
    value = outcome.outputs.value
    if outcome.outputs.contract != ob.desc.output_contract or not hasattr(value, "items") \
            or set(value) != {"kind", "value"} or value["kind"] not in ("issued", "rejected", "insufficient"):
        ob.final = "issued:shape"
        _hold(plan, "update:response")
        return
    if value["kind"] != "issued":
        ob.final = value["kind"]   # U の正常な判定 (C10)。採用に進めない
        return
    issued = _check_issued(state, ob, row, number, outcome)
    if isinstance(issued, str):
        ob.final = issued
        _hold(plan, "update:issued")
        return
    ob.steps.extend([_r_step(issued, first), *_acquire_steps(), _adopt_step()])


def advance(state) -> None:
    """更新の計画を進める (settle のロックの中)。"""
    from ._fb_core import _saved
    bad = _clashed_reports(state)
    for number, boot in state.plans.items():
        if boot.declaration.initial is not None and boot.points.get("origin") is not None \
                and number not in state.updates:
            plan = _plan(state, boot)
            if plan is not None:
                state.updates[number] = plan
    for plan in state.updates.values():
        if not plan.steps:
            continue
        _advance(state, plan)
        if "reading" not in plan.points:
            continue
        _discover(state, plan)
        for ob in plan.obligations.values():
            if ob.desc is not None and not ob.done:
                row = state.works.get(ob.desc.work_id)
                if row is not None and isinstance(row.work, _fb.Compute) and _saved(state, row.work.request):
                    _finish(state, plan, ob, row)
                    if not ob.done:
                        ob.final = "stopped" if _silent_stop(state, row) else None
            # 使用の門: 依存に食い違いがあれば、まだ作っていない記録を作らない (T だけは診断の保存で通す)。採用の判断を
            # もう公開していれば、その保存と確認は続ける。止まった義務は結末の 1 つで、頼っていない次の義務を待たせない
            held = _conflicted(state, plan, ob, bad)
            if held and ob.final in (None, "stopped") and not _undecided(ob):
                ob.final = "conflicted"
            # もう起きた取得 (acquired_ns を固定済み) の記録 a・G は、起きた事実の記録なので最後まで作る (K5)
            _advance(state, _Pair(plan, ob), build=lambda step: not held or step.name.startswith("T:")
                     or step.name in ("a", "G") and ob.acquired_ns is not None)
            decision = ob.points.get("decision")
            if decision is not None and ob.final is None and ob.points.get("decide") is not None:
                ob.final = "adopted" if decision == "A" else "stale"
                ob.points[decision] = ob.points["decide"]
                if decision == "A":
                    plan.chain.append(ob.points["A"])
            if ob.final == "adopted" and not ob.points.get("continued"):
                _continue(state, plan, ob)


def _continue(state, plan, ob) -> None:
    """K10: continuation が `reuse_candidates/1` の時だけ、A* をきっかけに次の評価の過程を開く。「採用したら必ず
    考え直す」の規則ではなく、宣言した差し替えられる方法 (D7)。None は開かない。"""
    from ._fb_think import open_continuation
    method = plan.initial.continuation
    if method is None:
        ob.points["continued"] = "none"
        return
    if method.contract != _c.REUSE_CANDIDATES or _plain(method.args) != {} \
            or plan.initial.generator.contract != _c.MODEL_OPERATIONS:
        _hold(plan, "continuation:method")
        ob.points["continued"] = "missing"
        return
    if open_continuation(state, plan.boot, ob.points["A"]):
        ob.points["continued"] = "opened"
