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

取りに行きの δ (`sui.fb.saved_acquisition_update/1`、紙 F-b K28・K28-a): 物語の対応の記録 → 読み方 reading の順に保存し、
家の人が acquire で残した取りに行きの Frame の B ごとに義務を 1 つ持つ。番号 i + 1 の Q* は、i の義務が今採用されていて
その採用の判断の保存が確認済みで、0〜i + 1 の Frame と原文が保存済みの時だけ作る (順を飛ばさない。採用以外の結末なら
先は待つ。札の系列の K13「非採用でも次へ」はこの列に当てない)。待ちと結末は `statuses` で FStatus.updates に出す (B1)。

行った一歩の結果 (紙 F-b K36 決定 5・12・13): δ の args が行う一歩の宣言 (execution) を名指す時、家の人が残した一歩の結果の
メモ (観測 {result, source_called}) ごとに義務を 1 つ置き、その節の核と宣言のセルの 1 回分の核で見立てへ通す。受け身の
取りに行きとの順はホストの時計の読みで決める: 取りに行きの区間が一歩の入場より前に終われば前、一歩の結果の記録より後に
始まれば後。重なる時は、世界の宣言 (source_overlap・actor_overlap) が述べていて、実際に読んだセルの行列どうしが両方の
順で同じ時だけ進める。それ以外は「順が分からない」で、その系列の採用が止まり続ける (待っても解けない)。一歩の結果が
まだ保存されていない間・源を読みに行っている取りに行きがある間は、順の来る採用を待つ (これは解ける)。読むセルの無い
例外も、その系列の採用を止める (決定 13)。

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
from .contracts import ContractRef as _ContractRef

_VALUE_ONLY = _ContractRef("sui.f.value_only", "1")   # 取りに行きの読み方の時間の射影 (K28-a (カ))


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
    seq: int | None = None       # 取りに行きの列の番号 (取りに行きの δ だけ)
    reading: str | None = None   # Q* の入力の 0〜seq を K26 の読み口で読んだ段 (read / model_zero / unreadable、表示用)
    reasons: tuple = ()          # U の不適合・不足の理由の語 (閉じた一覧、表示用)
    fields: tuple = ()           # U の不適合・不足の欄 (表示用)
    kind: str = "frame"          # frame (取りに行きの Frame / 札) / execution (行った一歩の結果、K36)
    interval: tuple | None = None   # ホストの時計の (始め, 終わり) の読み (順の判定、K36 決定 12)
    result: object = None        # 一歩の結果のメモ (ExecutionReport、execution の時だけ)


@_dataclass
class UpdatePlan:
    boot: object                 # BootPlan
    perception: object           # Perception (感じる側、K36 新しい決定 2)
    slot: str                    # 感じる側の宣言の位置
    args: dict                   # δ の args (K2)
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    obligations: dict = _field(default_factory=dict)   # 原報告の Point → Obligation (見つけた順)
    chain: list = _field(default_factory=list)         # 保存を確認した採用 A* の Point (採用した順)。最後が系列の頭
    kind: str = "segment"        # δ の方法: segment (区間の札、saved_segment_update/1) / acquisition (取りに行き)
    stopped: tuple | None = None   # 系列の採用が止まった (理由の語, 一歩の結果の Point)。待っても解けない (K36 決定 12・13)


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
        content = {"model": plan.perception.model, "extends": None, "carrier_by_state": law["carrier_by_state"],
                   "channels": channels, "rows": law["rows"], "frame_relation": "independent_given_carrier"}
        ledger = state.ledger
        uses = (plan.perception.model, d, *sorted(set(configs)), source)
        body = _Prediction(target="count_law", about=(ledger.record(plan.perception.model).id,),
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
        content = {"model": plan.perception.model,
                   "projection": {"contract": _f._encode(_c.FINITE_SEGMENT_PROJECTION),
                                  "args": {"frame": None, "claims": claims,
                                           "time_projection": {"contract": _f._encode(_c.SEGMENT_VALUE_ONLY),
                                                               "args": {}}}},
                   "generation": {"contract": _f._encode(_c.BOOTSTRAP_GENERATION), "args": plan.args["generation"]}}
        ledger = state.ledger
        law_slot = next(s.slot for s in plan.steps if s.name == "law")
        body = _Prediction(target="observation_plan", about=(ledger.record(plan.perception.model).id,),
                           basis=(ledger.record(plan.perception.model).id, ledger.record(law).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=law_slot.parents)
    return _Step(name="reading", build=build)


def _plan(state, boot):
    """δ の方法の名前と版で計画を選ぶ (P9)。読めない方法も計画を置いて不足を示す (計画を作らずに黙らない、K28 の B1)。"""
    perception_slot = boot.declaration.perception
    perception = perception_slot.value
    method = perception.derivation.method
    plan = UpdatePlan(boot=boot, perception=perception, slot=perception_slot.slot, args=_plain(method.args))
    if method.contract == _c.SAVED_SEGMENT_UPDATE:
        reason = _check_args(boot, plan.args)
        steps = [_law_step(), _reading_step()]
    elif method.contract == _c.SAVED_ACQUISITION_UPDATE:
        plan.kind = "acquisition"
        reason = _check_acquisition_args(boot, plan.args)
        steps = [_correspondence_step(), _acquisition_reading_step()]
        if reason is None and "execution" in plan.args:
            steps.append(_execution_reading_step())
    else:
        reason, steps = "delta:method", []
    if reason is not None:
        _hold(plan, reason)
    else:
        plan.steps = steps
    return plan


# --- 取りに行きの δ: 物語の対応と読み方 (K28 (2)(a)〜(c)・K28-a (ア)) ---

def _check_acquisition_args(boot, args):
    """取りに行きの δ の args の形: {route, observation_model, correspondence: {pairs}}。対応の中身 (1 対 1・target) と
    宣言どうしの一致は U が検査する。ここは計画を置けるかだけ (口・観測モデル・取りに行き方を名指せるか)。"""
    if not hasattr(args, "items") or set(args) - {"execution"} != {"route", "observation_model", "correspondence"} \
            or not isinstance(args["route"], str) or not isinstance(args["observation_model"], str):
        return "delta:args"
    # 行った一歩の結果も読む時は、同じ起動の行う一歩の宣言の位置を名指す (K36 決定 5)
    if "execution" in args and (boot.declaration.execution is None or args["execution"] != boot.declaration.execution.slot):
        return "delta:execution"
    routes = {r.slot: r.value for r in boot.declaration.routes}
    route = routes.get(args["route"])
    if route is None:
        return "delta:route"
    if route.reading_contract != _c.ACQUISITION_SEQUENCE_PROJECTION:
        return "delta:reading_contract"
    if route.repeat.contract != _c.ACQUISITION_REPEAT_WHEN_DONE or _plain(route.repeat.args) != {}:
        return "delta:repeat"   # この本で読める取りに行き方は「済んだら次」だけ (K28 新しい決定 9)
    models = {m.slot: m.value for m in boot.declaration.observation_models}
    model = models.get(args["observation_model"])
    if model is None or getattr(model, "route_slot", None) != args["route"]:
        return "delta:observation_model"
    correspondence = args["correspondence"]
    if not hasattr(correspondence, "items") or set(correspondence) != {"pairs"} \
            or not isinstance(correspondence["pairs"], list) \
            or any(not isinstance(p, list) or len(p) != 2 or not all(isinstance(x, str) for x in p)
                   for p in correspondence["pairs"]):
        return "delta:correspondence"
    return None


def _correspondence_step():
    """物語の対応の記録 (`sui.fb.state_correspondence/1`、Prediction / MODEL): 見立てのモデルの Point と、その口の観測モデルの
    記録の Point を解いて、起動の宣言の pairs と一緒に保存する (K28-a (ア))。読み方より先。"""
    def build(state, plan):
        from ._fb_core import Slot
        observation = plan.boot.points.get("observation_model:" + plan.args["observation_model"])
        if observation is None or plan.boot.points.get("origin") is None:
            return None
        ledger = state.ledger
        content = {"model": plan.perception.model, "observation_model": observation,
                   "pairs": plan.args["correspondence"]["pairs"]}
        body = _Prediction(target="state_correspondence", about=(ledger.record(plan.perception.model).id,),
                           basis=(ledger.record(plan.perception.model).id, ledger.record(observation).id),
                           content=_Payload.json(content), contract=_c.STATE_CORRESPONDENCE)
        return Slot(contract=_c.STATE_CORRESPONDENCE, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.boot.d}))
    return _Step(name="correspondence", build=build)


def _acquisition_reading_step():
    """読み方 (`sui.f.observation_plan/2`): projection = `acquisition_sequence_projection/1` {observation_model, correspondence,
    time_projection}、generation = `acquisition_generation/1` {}。"""
    def build(state, plan):
        from ._fb_core import Slot
        observation = plan.boot.points["observation_model:" + plan.args["observation_model"]]
        correspondence = plan.points["correspondence"]
        content = {"model": plan.perception.model,
                   "projection": {"contract": _f._encode(_c.ACQUISITION_SEQUENCE_PROJECTION),
                                  "args": {"observation_model": observation, "correspondence": correspondence,
                                           "time_projection": {"contract": _f._encode(_VALUE_ONLY), "args": {}}}},
                   "generation": {"contract": _f._encode(_c.ACQUISITION_GENERATION), "args": {}}}
        ledger = state.ledger
        body = _Prediction(target="observation_plan", about=(ledger.record(plan.perception.model).id,),
                           basis=(ledger.record(plan.perception.model).id, ledger.record(observation).id,
                                  ledger.record(correspondence).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.boot.d}))
    return _Step(name="reading", build=build)


def _execution_reading_step():
    """行った一歩の読み方 (`sui.f.observation_plan/2`、K36 決定 5): projection = `execution_step_projection/1`
    {execution_declaration} (その一歩の節の核と、行う一歩の宣言のセル)、generation = `execute_step/1` {}。"""
    def build(state, plan):
        from ._fb_core import Slot
        declaration = plan.boot.points.get("execution")
        if declaration is None:
            return None
        content = {"model": plan.perception.model,
                   "projection": {"contract": _f._encode(_c.EXECUTION_STEP_PROJECTION),
                                  "args": {"execution_declaration": declaration}},
                   "generation": {"contract": _f._encode(_c.EXECUTE_STEP), "args": {}}}
        ledger = state.ledger
        body = _Prediction(target="observation_plan", about=(ledger.record(plan.perception.model).id,),
                           basis=(ledger.record(plan.perception.model).id, ledger.record(declaration).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.boot.d}))
    return _Step(name="execution_reading", build=build)


# --- 義務 (J1) と系列の頭 (K9・K13) ---

def _discover(state, plan) -> None:
    """保存した B のうち、δ の口の原 Claim に義務を置く (J1)。扱えない枝は意味の不足として示す。"""
    if plan.kind == "acquisition":
        _discover_acquisitions(state, plan)
        return
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


def _epoch(plan):
    return next(r.value.config.route_epoch for r in plan.boot.declaration.routes if r.slot == plan.args["route"])


def _frame_value(state, report):
    """保存した原報告の Frame (MeasurementFrame)。Frame でなければ None。"""
    item = state.ledger.record(report).body.content.as_json()["item"]
    return _f._decode(item["value"], _f.MeasurementFrame) if item["kind"] == "frame" else None


def _received(frame):
    """取れた (taken) 回の原文の名札 (Ref)。空・取れなかった回は None。"""
    from .ids import Ref
    result = frame.value["result"]
    return _f._decode(result["received"], Ref) if result["kind"] == "taken" else None


def _discover_acquisitions(state, plan) -> None:
    """保存した B のうち、δ の口の取りに行きの Frame (この run・この口の route_epoch、家の人の acquire が作ったもの) に
    義務を 1 つ置く (K28 新しい決定 5)。何も主張しない札 (CoverageUnproved) は義務にしない。"""
    route = plan.boot.points.get("route_config:" + plan.args["route"])
    reading, epoch = _f._encode(_c.ACQUISITION_SEQUENCE_PROJECTION), _epoch(plan)
    for slot in state.bindings.values():
        if slot.entry is None:
            continue
        b = slot.record.body.content.as_json()
        if b["route"] != route or b["report"] in plan.obligations:
            continue
        frame = _frame_value(state, b["report"])
        if frame is None:
            continue
        mid = frame.measurement_id
        if mid.component != "source_acquisition" or mid.origin != state.clock.run or mid.route_epoch != epoch \
                or b["reading_contract"] != reading:
            _hold(plan, "delta:frame")
            continue
        if any(ob.seq == mid.sample_seq for ob in plan.obligations.values()):
            _hold(plan, "delta:sample_seq")   # 同じ番号の別の Frame (今の入口では作られない)
            continue
        interval = frame.measurement_interval
        ob = Obligation(report=b["report"], binding=slot.entry.cid, seq=mid.sample_seq,
                        interval=(interval.start_ns, interval.end_ns))
        ob.steps = [_q_step(ob)]
        plan.obligations[b["report"]] = ob
    if "execution" in plan.args and "execution_reading" in plan.points:
        _discover_executions(state, plan)


def _discover_executions(state, plan) -> None:
    """家の人が残した一歩の結果のメモのうち、観測として残ったもの (observed) に義務を 1 つ置く (K36 決定 5)。宣言した
    無作用・未接続・行っていない一歩は観測ではない (K36-a (エ))。"""
    from ._fb_act import result_of
    for act in state.acting.values():
        if act.boot is not plan.boot:
            continue
        for intention in act.intentions:
            for execution in intention.executions:
                receipt, point = result_of(state, execution)
                if point is None or point in plan.obligations or receipt.envelope.event.outcome != "observed":
                    continue
                report = receipt.envelope.event
                ob = Obligation(report=point, binding=point, kind="execution", result=report,
                                interval=(report.entered.reading.time_ns, report.finished.reading.time_ns))
                ob.steps = [_q_step(ob)]
                plan.obligations[point] = ob


def _raw_saved(state, report) -> bool:
    """取れた (taken) 回の原文が保存済みか。空・取れなかった回は原文が無い。"""
    received = _received(_frame_value(state, report))
    return received is None or len(state.ledger.entries_of(received)) == 1


def _next_acquisition(plan, state):
    """次に Q* を作る義務 (K28 新しい決定 5・K36 決定 12): 受け身の取りに行きは番号 i = 採用を確認した取りに行きの数の
    Frame (0〜i - 1 は採用されて確認済み、原文も保存済みの時だけ)、行った一歩は入場の順の最初の未採用。両方あれば時計の
    読みの前後で決め、重なりは宣言とセルの行列の交換で決める (決まらなければ系列を止める)。採用以外の結末・進行中・
    確認待ち・順の来る観測の保存待ちがあれば待つ。印でなく状態で決める。"""
    if plan.stopped is not None or _pending_clash(state, plan) or _head(plan) == "wait" \
            or any(ob.final not in (None, "adopted") for ob in plan.obligations.values()):
        return None
    passive_done = sum(1 for ob in plan.obligations.values() if ob.kind == "frame" and ob.final == "adopted")
    frame = next((ob for ob in plan.obligations.values() if ob.kind == "frame" and ob.seq == passive_done), None)
    if frame is not None and (frame.desc is not None or not _raw_saved(state, frame.report)):
        return None
    pending = sorted((ob for ob in plan.obligations.values() if ob.kind == "execution" and ob.final is None),
                     key=lambda ob: ob.interval)
    step = pending[0] if pending else None
    if step is not None and step.desc is not None:
        return None
    if step is None:
        if frame is not None and _unsaved_step_before(state, plan, frame):
            return None   # まだ保存されていない一歩の結果との順が決まらない (結果が保存されれば解ける)
        return None if frame is None or _applied_clash(state, plan, frame) else frame
    if frame is None:
        # まだ義務になっていない取りに行き (公開済み・源を読みに行っている途中) が、一歩より前か重なりうるなら待つ
        if _passive_open_before(state, plan, passive_done, step):
            return None
        step = _readable(state, plan, step)
        return None if step is None or _applied_clash(state, plan, step) else step
    if frame.interval[1] < step.interval[0]:
        return None if _applied_clash(state, plan, frame) else frame
    if frame.interval[0] > step.interval[1]:
        step = _readable(state, plan, step)
        return None if step is None or _applied_clash(state, plan, step) else step
    # 区間が重なる (決定 12): ここに来る時は、この関数の頭の _pending_clash が、この 2 つ (どちらもそれぞれの種類の先頭で、
    # 両方より前の未採用の観測は無い) が交換すると確かめている (交換しない・読むセルの無い例外なら、そこで止まっている)。
    # 交換するので、どちらを先にしても答えは同じ。受け身を先にする
    return frame


def _matrix_of(state, plan, ob):
    return step_matrix(state, plan, ob) if ob.kind == "execution" else frame_matrix(state, plan, ob)


def _applied_clash(state, plan, ob) -> bool:
    """もう採用した別の種類の観測 (取りに行き ↔ 行った一歩) と ob の区間が重なり、宣言が述べていないか、セルの行列が
    両方の順で同じでない (K36 決定 12)。そうなら系列の採用を「順が分からない」で止める (待っても解けない。名指しは一歩)。
    入口 U の順の確かめと同じ規則 (区間の端の読みが同じなら重なり)。"""
    from ._fb_act import declaration
    decl = declaration(plan.boot)
    for other in plan.obligations.values():
        if other.kind == ob.kind or other.final != "adopted":
            continue
        if other.interval[0] > ob.interval[1]:
            # もう採用した観測が、この観測の終わりより後に始まっている = 順を飛ばす (入口 U と同じ規則、レビュー R6)
            plan.stopped = ("observation_order_unknown", ob.binding if ob.kind == "execution" else other.binding)
            return True
        if other.interval[1] < ob.interval[0]:
            continue
        a, b = _matrix_of(state, plan, ob), _matrix_of(state, plan, other)
        if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap) or _product(a, b) != _product(b, a):
            plan.stopped = ("observation_order_unknown", ob.binding if ob.kind == "execution" else other.binding)
            return True
    return False


def _strictly_before(a, b) -> bool:
    """未採用の観測 a が b より確かに前 (K36 決定 12): 受け身の取りに行きどうしは番号の順、一歩どうしは行った順 (家の人は
    同時に 1 歩しか入場させず、次の一歩は前の結果を保存してから入場する = 端の読みが同じでも前、レビュー R10)、種類が
    違えば a の終わりが b の始まりより前 (端の読みが同じなら前ではない)。"""
    if a.kind == b.kind == "frame":
        return a.seq < b.seq
    if a.kind == b.kind == "execution":
        return a.interval[1] <= b.interval[0]
    return a.interval[1] < b.interval[0]


def _pending_clash(state, plan) -> bool:
    """順の決まらない組が、未採用の観測の列の先頭に来ているか (K36 決定 12、K36-b (セ)(ソ))。まだ採用していない一歩の結果と
    まだ採用していない取りに行き (更新を頼んだものも含む) が重なり、世界の宣言が述べていないか、実際に読んだセルの行列が
    両方の順で同じでない組 (読むセルの無い例外との重なりも) について、その組の両方より確かに前の未採用の観測が無い時だけ、
    その観測と後に続く採用を「順が分からない」で止める (頼んだ更新の採用の判断も作らない。待っても解けない)。前に確かな
    観測があれば、それを先に採用し、次の回にもう一度見る (後の組を理由に前の採用を止めない、レビュー R9)。"""
    pending = [ob for ob in plan.obligations.values() if ob.final is None]
    for step in (ob for ob in pending if ob.kind == "execution"):
        unreadable = step_matrix(state, plan, step) is None
        for frame in (ob for ob in pending if ob.kind == "frame"):
            if frame.interval[1] < step.interval[0] or frame.interval[0] > step.interval[1]:
                continue
            if not unreadable and _commute(state, plan, frame, step):
                continue
            if any(_strictly_before(o, frame) and _strictly_before(o, step) for o in pending
                   if o is not frame and o is not step):
                continue   # この組より前の観測がまだ採用されていない: 先に進める
            plan.stopped = ("exception_reading_missing" if unreadable else "observation_order_unknown", step.binding)
            return True
    return False


def _readable(state, plan, step):
    """読むセルの無い一歩の結果 (例外の読み方が無い) は、その系列の採用を止める (K36 決定 13、待っても解けない)。"""
    m = step_matrix(state, plan, step)
    if m is None:
        plan.stopped = ("exception_reading_missing", step.binding)
        return None
    if not any(x for row in m for x in row):
        # 読めるセルの行列が 0: どの見立てでも質量 0 (U は model_falsified で断る)。系列はここで止まる
        plan.stopped = ("model_zero", step.binding)
        return None
    return step


def _unsaved_step_before(state, plan, frame) -> bool:
    """入場した観測の一歩のうち、結果がまだ保存されていない (行っている途中・保存待ち) もので、この取りに行き frame との
    順が今は決まらないものがあるか (K36 決定 12)。frame が一歩の入場より前に終わっていれば前 (待たない)。結果の記録の読みが
    分かっていて frame がそれより後に始まれば一歩が前 (結果の保存を待つ)。それ以外は重なりで、世界の宣言が述べていて、
    frame の行列が一歩の結果の読みうるどのセルの行列とも両方の順で同じ時だけ待たない (どの結果でも順で答えが変わらない)。
    観測でない一歩 (宣言した無作用・未接続) は順に関わらない。"""
    from ._fb_act import classify, declaration, result_of
    for act in state.acting.values():
        if act.boot is not plan.boot:
            continue
        for intention in act.intentions:
            for execution in intention.executions:
                row = state.works.get(execution.work_id) if execution.work_id is not None else None
                if row is None or not row.ticket_used or row.entered_ns is None:
                    continue
                receipt, point = result_of(state, execution)
                if point is not None or frame.interval[1] < row.entered_ns:
                    continue
                E = execution.args
                if classify(state, plan.boot, E.model, E.u)[0] != "observe":
                    continue
                if receipt not in (None, "published") and frame.interval[0] > receipt.envelope.event.finished.reading.time_ns:
                    return True
                decl = declaration(plan.boot)
                if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap):
                    return True
                a = frame_matrix(state, plan, frame)
                if any(_product(a, b) != _product(b, a) for b in _cell_matrices(state, plan.boot, E)):
                    return True
    return False


def _cell_matrices(state, boot, E):
    """一歩 E の節の核の、宣言のセルごとの行列 (モデルの状態の順、正規化する前の和)。"""
    from fractions import Fraction
    from . import _fb_act
    k = _fb_act.kernel(state, E.model, E.u)
    outcomes = {o["id"]: _fb_act._matrix(o) for o in k["outcomes"]}
    out = []
    for cell in _fb_act.declaration(boot).cells.get(E.u, ()):
        n = len(next(iter(outcomes.values())))
        m = [[Fraction(0)] * n for _ in range(n)]
        for name in cell.outcomes:
            for i, row in enumerate(outcomes[name]):
                for j, x in enumerate(row):
                    m[i][j] += x
        out.append(m)
    return out


def _passive_open_before(state, plan, passive_done, step) -> bool:
    """受け身の取りに行きで、まだ義務になっていないもののうち、一歩 step との順が今は決まらないものがあるか (K36 決定 12)。
    公開して保存待ちのもので、始まりが一歩の終わり以前のものは待つ (義務になれば区間で比べられる)。源を読みに行っている
    途中のものは、始まりが一歩の終わり以前なら重なり (終わりは一歩の後)、世界の宣言が述べていて、一歩のセルの行列が
    その取りに行きの読みうるどのセルの行列とも両方の順で同じ時だけ待たない。"""
    from ._fb_act import declaration
    end_ns = step.interval[1]
    route = plan.boot.points.get("route_config:" + plan.args["route"])
    for row in state.works.values():
        if isinstance(row.work, _fb.MeasureSegment) and row.work.desc.args.route == route:
            for take in row.takes:
                if take.sample_seq >= passive_done and take.before_ns <= end_ns \
                        and not any(ob.kind == "frame" and ob.seq == take.sample_seq for ob in plan.obligations.values()):
                    return True
    started = state.inflight.get(_epoch(plan))
    if started is None or started > end_ns:
        return False
    decl = declaration(plan.boot)
    if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap):
        return True
    b = step_matrix(state, plan, step)
    return b is None or any(_product(a, b) != _product(b, a) for a in _passive_cell_matrices(state, plan))


def _passive_cell_matrices(state, plan):
    """受け身の観測モデルの、セルごとの行列 (見立ての状態の順に並べ替えた、正規化する前の和)。"""
    from fractions import Fraction
    model = next(m.value for m in plan.boot.declaration.observation_models if m.slot == plan.args["observation_model"])
    control, = model.controls
    states = [s["id"] for s in state.ledger.record(plan.perception.model).body.content.as_json()["document"]["states"]]
    pairs = dict(plan.args["correspondence"]["pairs"])
    phi = [states.index(pairs[a]) for a in model.states]
    n = len(states)
    out = []
    for cell in control.cells:
        m = [[Fraction(0)] * n for _ in range(n)]
        for o in control.kernel.outcomes:
            if o.id in cell.outcomes:
                for i in range(n):
                    for j in range(n):
                        m[phi[i]][phi[j]] += o.matrix[i][j]
        out.append(m)
    return out


def frame_matrix(state, plan, ob):
    """受け身の取りに行き ob の、その回のセルの行列 (見立ての状態の順に並べ替えた、正規化する前の和)。"""
    from fractions import Fraction
    model = next(m.value for m in plan.boot.declaration.observation_models if m.slot == plan.args["observation_model"])
    control, = model.controls
    frame = _frame_value(state, ob.report)
    called = bool(frame.value["source_called"])
    result = frame.value["result"]["kind"]
    from . import _fb_read
    symbol = _fb_read._SYMBOLS[(result, called)]
    cell = next((x for x in control.cells if _fb_read._symbol(x.observation) == symbol), None)
    members = set(cell.outcomes) if cell is not None else set()
    states = [s["id"] for s in state.ledger.record(plan.perception.model).body.content.as_json()["document"]["states"]]
    pairs = dict(plan.args["correspondence"]["pairs"])
    phi = [states.index(pairs[a]) for a in model.states]
    n = len(states)
    m = [[Fraction(0)] * n for _ in range(n)]
    for o in control.kernel.outcomes:
        if o.id in members:
            for i in range(n):
                for j in range(n):
                    m[phi[i]][phi[j]] += o.matrix[i][j]
    return m


def step_matrix(state, plan, ob):
    """行った一歩 ob の、その回のセルの行列 (モデルの状態の順、正規化する前の和)。読むセルが無ければ None。"""
    from fractions import Fraction
    from . import _fb_act
    E = ob.result.execution
    names = _fb_act.cell_outcomes(plan.boot, E.u, ob.result.value)
    if names is None:
        return None
    k = _fb_act.kernel(state, E.model, E.u)
    n = len(state.ledger.record(E.model).body.content.as_json()["document"]["states"])
    m = [[Fraction(0)] * n for _ in range(n)]
    for o in k["outcomes"]:
        if o["id"] in names:
            for i, row in enumerate(_fb_act._matrix(o)):
                for j, x in enumerate(row):
                    m[i][j] += x
    return m


def _product(a, b):
    from fractions import Fraction
    n = len(a)
    return [[sum((a[i][k] * b[k][j] for k in range(n)), Fraction(0)) for j in range(n)] for i in range(n)]


def _commute(state, plan, frame, step) -> bool:
    """重なりの適用条件 (K36 決定 12): 宣言が両方の相手について「途中も状態を変えない」か「1 回ずつの前後で表せる」と
    述べ、実際に読んだセルの行列どうしが両方の順で同じ。"""
    from ._fb_act import declaration
    decl = declaration(plan.boot)
    if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap):
        return False
    a, b = frame_matrix(state, plan, frame), step_matrix(state, plan, step)
    return b is not None and _product(a, b) == _product(b, a)


def execution_reading(state, boot, point, report):
    """一歩の結果 (observed) の見立てへの到達 (表示用、K36 決定 12・13): (outcome, reason, retryable)。"""
    from ._fb_act import cell_outcomes
    plan = next((p for p in state.updates.values() if p.boot is boot and "execution" in p.args), None)
    if cell_outcomes(boot, report.execution.u, report.value) is None:
        return "observed", "exception_reading_missing", False
    if plan is None:
        return "observed", "not_read", False
    if plan.stopped is not None and plan.stopped[1] == point:
        if plan.stopped[0] == "model_zero":
            return "model_zero", "model_zero", False
        return "order_unknown", plan.stopped[0], False
    ob = plan.obligations.get(point)
    if ob is None:
        return "observed", "waiting_binding", True
    if ob.final == "adopted":
        return "observed", "adopted", False
    if ob.final is not None:
        if "model_falsified" in ob.reasons:
            return "model_zero", "model_zero", False
        return "observed", ob.final, False
    return "observed", "waiting_update" if ob.desc is not None else "waiting_order", True


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


def silent_stop(state, row) -> bool:
    """終わりの知らせの無い停止 (K15): 入場した本体の実際の停止をホストが観測し、その口から受け取った封筒が
    全部受付済みで、その中に終わりの知らせが無い。印を持たず、その都度 P.work から導く。形がおかしくて断った封筒
    (K17) は済んだものに数え、終わりの知らせには数えない。見立ての更新の仕事と考える過程の仕事 (活動の実停止、
    `_fb_think._stopped`) が同じ判定を使う (レビュー K36-c R9・R11)。"""
    from ._fb_think import _ends
    return bool(row.entered and row.stopped and all(number in state.receipts or number in state.rejected for number, _r in row.reports)
                and not _ends(state, row))


def _next(state, plan):
    """次に Q* を作る義務: まだ要求の無い義務のうち、ホストが原報告を受け取った順で最初の 1 つ。
    受け取った順の分からない義務があれば選ばない。食い違いで止まった義務 (結末 conflicted) は、後ろを待たせない。
    取りに行きの δ は番号の順で、前が採用されて確認されるまで次を選ばない (`_next_acquisition`)。"""
    if plan.kind == "acquisition":
        return _next_acquisition(plan, state)
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


def adoptions(state, boot) -> list:
    """その Boot の採用の並び = 採用を決めた順そのもの: 保存を確かめた鎖 plan.chain と、その末尾に続く保存の確認待ちの
    採用 (準備した CID。置き場にあれば境界に見える)。採用の判断は前の判断の保存の確認を待つ (`_undecided`) ので、確認
    待ちは高々 1 つで、その前の採用 (previous) は鎖の最後。義務を見つけた順は採用の順ではないので使わない (レビュー
    K36-c R6)。考える側の根・評価に渡した境界・引受けの比べ方はこの並びで数える (K36-c ③⑤、R2)。"""
    out = []
    for plan in state.updates.values():
        if plan.boot is not boot:
            continue
        out.extend(plan.chain)
        for ob in plan.obligations.values():
            step = next((s for s in ob.steps if s.name == "decide"), None)
            if ob.points.get("decision") == "A" and _undecided(ob) and step.slot.prepared.cid not in plan.chain:
                out.append(step.slot.prepared.cid)
    return out


def visible_root(state, boot, boundary):
    """boundary (o で固めた境界) に実際に見える、いちばん後の採用 (無ければ None = 事前)。"""
    seen = None
    for cid in reversed(adoptions(state, boot)):
        if seen is None:
            seen = state.ledger.ancestors(boundary) | frozenset(boundary)
        if cid in seen:
            return cid
    return None


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


def terminal_clash(state, ob, *, unconfirmed=True) -> bool:
    """その義務の更新の仕事 Wu の口から、両立しない終わりの報告が届いている (保存の確認待ちも数えるのは許可の判定用)。
    採用 A* はその仕事の最初の終わりから作るので、後着の食い違いはその見立てに頼る新しい使用を止める (K36-b (チ))。"""
    from ._fb_think import _clash, _ends
    row = state.works.get(ob.desc.work_id) if ob.desc is not None else None
    return row is not None and _clash(_ends(state, row), unconfirmed=unconfirmed)


def belief_terminal_clash(state, boot, boundary) -> bool:
    """boundary に見える、その Boot の採用 A* のどれかの更新の仕事に、後着の両立しない終わりの報告がある。"""
    seen = None
    for plan in state.updates.values():
        if plan.boot is not boot:
            continue
        for ob in plan.obligations.values():
            step = next((s for s in ob.steps if s.name == "decide"), None)
            if ob.points.get("decision") != "A" or step is None or step.slot is None or not terminal_clash(state, ob):
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
    key = {"delta": {"declaration": d, "slot": plan.perception.derivation.slot},
           "delta_contract": _encode(plan.perception.derivation.method.contract),
           "process": {"declaration": d, "slot": plan.perception.process_slot},
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
    if ob.kind == "execution":
        # 行った一歩の結果 (K36 決定 5): 結果のメモ・読み方・行う一歩の宣言の記録・モデル
        out = {plan.boot.d, plan.boot.points["origin"], plan.perception.model, plan.points["execution_reading"],
               ob.binding, ob.result.execution.reading}
    elif plan.kind == "acquisition":
        # 取りに行きの列 (K28 (2)(e)): 観測モデル・物語の対応・読み方と、この回の Frame・B・取れた回の原文。0〜i - 1 の
        # Frame・B・原文は、前の採用の Q* が読んだ全部 (下の系列をさかのぼった閉包) に入っている
        out = {plan.boot.d, plan.boot.points["origin"], plan.perception.model, plan.points["correspondence"],
               plan.points["reading"], plan.boot.points["observation_model:" + plan.args["observation_model"]],
               ob.binding, ob.report, b["segment"], b["route"]}
        received = _received(_frame_value(state, ob.report))
        if received is not None:
            out.add(ledger.entries_of(received)[0].cid)
    else:
        out = {plan.boot.d, plan.boot.points["origin"], plan.perception.model, plan.points["law"], plan.points["reading"],
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
        d, initial, origin = plan.boot.d, plan.perception, plan.boot.points["origin"]
        stage, work_id = _names(plan, ob)
        inputs = _inputs(state, plan, ob, prior)
        desc = _fb.Desc(
            work_id=work_id,
            process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
            trigger=frozenset({_fb.Trigger(point=ob.report, slot="trigger")}),
            purpose="belief_update", stage_slot=stage, reader=origin,
            method=_c.FINITE_UPDATE_COMPUTE, output_contract=_c.UPDATE_RESPONSE,
            args=_fb.UpdateArgs(model=initial.model, prior=prior, observations=(
                _fb.ObservationUse(binding=ob.binding, reading=plan.points[
                    "execution_reading" if ob.kind == "execution" else "reading"]),)),
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


def _read_stage(state, plan, ob) -> str:
    """表示用 (K28 新しい決定 8 ⑤): Q* の入力の 0〜seq を K26 の読み口で読んだ段。U の判定とは別に、読みの段の 0
    (model_zero) と更新の段の 0 (U の model_falsified) を分けて見せる。"""
    from ._fb_read import read
    records = {p: state.ledger.record(p) for p in ob.desc.input_points}
    model = plan.boot.points["observation_model:" + plan.args["observation_model"]]
    return read(records, model=model, run=state.clock.run, route_epoch=_epoch(plan), through_seq=ob.seq).kind


# --- Wu の終わり → T・R*・結果の取得・採用 (K7〜K9) ---

def _issued_result(outputs):
    """issued の返答 (update_response/1) が運ぶ finite_update_result/1 の値。形が合わなければ None。"""
    value = outputs.value
    if outputs.contract != _c.UPDATE_RESPONSE or not hasattr(value, "items") or set(value) != {"kind", "value"}:
        return None
    return value["value"] if value["kind"] == "issued" else None


def _result_shape(value) -> bool:
    """issued の返答の値が finite_update_result/1 の値として読めるか (形が合わなければ issued:shape)。"""
    try:
        _f._decode(value, _f.FiniteUpdateResult)
    except (_f.FInputError, KeyError, TypeError, ValueError):
        return False
    return True


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
        if plan.stopped is not None:
            return None   # 系列の採用が止まった (順が分からない・読み方が無い・質量 0、K36 決定 12・13)
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
            content = {"origin": origin, "model": plan.perception.model, "previous": head, "request": q,
                       "result": r, "acquisition": g}
            uses = {origin, plan.perception.model, q, r, g} | ({head} if head else set())
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
            or set(value) != {"kind", "value"} or value["kind"] not in ("issued", "rejected", "insufficient") \
            or value["kind"] == "issued" and not _result_shape(value["value"]):
        ob.final = "issued:shape"
        _hold(plan, "update:response")
        return
    if value["kind"] != "issued":
        ob.final = value["kind"]   # U の正常な判定 (C10)。採用に進めない
        issues = value["value"]["issues"] if hasattr(value["value"], "items") else ()
        ob.reasons = tuple(dict.fromkeys(str(i["code"]) for i in issues))   # 表示用 (B1)。自由な文は載せない
        ob.fields = tuple(dict.fromkeys(str(f) for i in issues for f in i["fields"]))
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
        if boot.declaration.perception is not None and boot.points.get("origin") is not None \
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
        if plan.kind == "acquisition" and plan.stopped is None:
            # 採用の判断を作る前に、届いている未採用の観測どうしの順を決める (K36 決定 12、レビュー R8)
            _pending_clash(state, plan)
        for ob in plan.obligations.values():
            if plan.kind == "acquisition" and ob.kind == "frame" and ob.desc is not None and ob.reading is None:
                ob.reading = _read_stage(state, plan, ob)   # 表示用。読めなければ settle ごと抜けて次で読み直す
            if ob.desc is not None and not ob.done:
                row = state.works.get(ob.desc.work_id)
                if row is not None and isinstance(row.work, _fb.Compute) and _saved(state, row.work.request):
                    _finish(state, plan, ob, row)
                    if not ob.done:
                        ob.final = "stopped" if silent_stop(state, row) else None
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


# --- 公開の状態 (K28 新しい決定 11 の B1・K28-a (イ)) ---

def statuses(state) -> tuple:
    """取りに行きの δ ごとに、家の人が公開した取りに行きの 1 回ずつの到達と結末 (FStatus.updates)。その都度、P.work の
    取りに行きの控え・保存・義務から導く (印を持たない)。"""
    from ._fb_core import _saved_point
    out = []
    for plan in state.updates.values():
        if plan.kind != "acquisition" or not plan.steps:
            continue
        route = plan.boot.points.get("route_config:" + plan.args["route"])
        takes = sorted((take for row in state.works.values() if isinstance(row.work, _fb.MeasureSegment)
                        and row.work.desc.args.route == route for take in row.takes), key=lambda t: t.sample_seq)
        if not takes:
            continue
        saved = [_saved_point(state, t.frame_envelope) is not None
                 and (t.envelope is None or _saved_point(state, t.envelope) is not None) for t in takes]
        through = next((i - 1 for i, ok in enumerate(saved) if not ok), len(saved) - 1)
        adopted_frames = sum(1 for ob in plan.obligations.values() if ob.kind == "frame" and ob.final == "adopted")
        tails = {"published_through": takes[-1].sample_seq, "saved_through": through if through >= 0 else None,
                 # 受け身の取りに行きの採用だけを数える (一歩の結果の採用は別、レビュー R4)
                 "adopted_through": adopted_frames - 1 if adopted_frames else None}
        for take, ok in zip(takes, saved):
            frame = _saved_point(state, take.frame_envelope)
            ob = plan.obligations.get(frame) if frame is not None else None
            reasons, fields = (), ()
            if ob is not None and ob.final is not None:
                outcome, reasons, fields = ob.final, ob.reasons, ob.fields
                if ob.final == "conflicted":
                    reasons = ("update:conflict",)
            elif ob is not None and _undecided(ob):
                outcome = "waiting_confirmation"
            elif ob is not None and ob.done:
                # 仕事 Wu は終わり、結果 R*・結果の取得・採用の判断を記録している途中 (時計の出どころが無ければ待つ)
                outcome = "recording"
                reasons = ("clock",) if _clock_source(state) is None else ()
            elif ob is not None and ob.desc is not None:
                outcome = "requested"
            elif not ok:
                outcome = "waiting_storage"
            elif ob is None:
                outcome = "waiting_binding"
                hold = state.binding_missing.get(frame)
                reasons = (hold.reason,) if hold is not None else ()
            elif take.sample_seq > len(plan.chain):
                outcome = "waiting_predecessor"
            else:
                outcome = "ready"
            out.append(_fb.BeliefUpdateStatus(
                model=plan.perception.model, origin=plan.boot.points.get("origin"), route_epoch=take.route_epoch,
                sample_seq=take.sample_seq, obligation=ob.binding if ob is not None else None,
                request=ob.points.get("Q") if ob is not None else None, outcome=outcome,
                reading=ob.reading if ob is not None else None, reasons=reasons, fields=fields, **tails))
    return tuple(out)


def _continue(state, plan, ob) -> None:
    """continuation が `reuse_candidates/3` の時だけ、採用 A* を考える側の材料にする (K36-c ③: 採用ごとに評価を作らず、
    新しい評価の活動を入場させるかは `_fb_think.admit` が 1 か所で決める)。「採用したら必ず考え直す」の規則ではなく、
    宣言した差し替えられる方法 (D7)。None は材料にしない (最初の活動の後の評価を作らない)。"""
    initial = plan.boot.declaration.initial   # 考える側 (無ければ考え直す道は無い、K36 新しい決定 2)
    method = initial.value.continuation if initial is not None else None
    if method is None:
        ob.points["continued"] = "none"
        return
    if method.contract != _c.REUSE_CANDIDATES or _plain(method.args) != {} \
            or initial.value.generator.contract != _c.MODEL_OPERATIONS:
        _hold(plan, "continuation:method")
        ob.points["continued"] = "missing"
        return
    ob.points["continued"] = "material"
