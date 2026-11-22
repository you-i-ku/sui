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
    kind: str = "frame"          # frame (取りに行きの Frame / 札) / execution (行った一歩の結果、K36) / rebuild (K37)
    interval: tuple | None = None   # ホストの時計の (始め, 終わり) の読み (順の判定、K36 決定 12)
    result: object = None        # 一歩の結果のメモ (ExecutionReport、execution の時だけ)
    pool: object = None          # この Q* が読む候補の並び (`_fb_pool.Pool`。Q* の Publish で固定、作り直しは作った時)
    evidence: tuple = ()         # U の不適合・不足が名指した Point (名指しの公開、K37)
    superseded: bool = False     # 止まった結末だが、候補を足した後の作り直しが読み直した (系列を止めない、K37 決定 4)
    relist: list | None = None   # 作り直し (rebuild) が読み直す観測の義務の列 (Q* の Publish で固定)


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
    # 系列の採用が止まった (理由の語, 観測の Point, 名指しの Point の列, その並びの model)。待っても解けない (K36 決定 12・13)。
    # 止まりはその並びの下でだけ効く (候補を足した後は新しい並びで導き直す、K37 決定 4)
    stopped: tuple | None = None
    initial: object = None       # 最初の並び (起動の宣言の 1 枚、`_fb_pool.initial_pool`)
    current: object = None       # 今の境目 (置き場の頭) で効いている候補の並び (解けなければ None、K37 決定 3)
    applied: list = _field(default_factory=list)   # 系列の頭の数値に読んだ観測の義務 (順に。作り直しで並び直す、K37 決定 4)


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


# --- 法則と読み方 (K3: Boot・時計・route の保存 → law → reading の順)。どれも解いた並び (`_fb_pool.Pool`) から作る (K37) ---

def _reading_name(base, pool):
    """並び pool の読み方の記録の歩の名前 (最初の並びは名前のまま、足した並びは並びのモデルを添える)。"""
    return base if pool.initial else base + ":" + pool.model


def _reading_steps(plan, pool):
    """並び pool の読み方の記録の歩 (K37: 並びごとの読み方は、その並びの解決から作る)。区間の札は法則 → 読み方、取りに行きは
    (最初の並びの物語の対応 →) 読み方と、行った一歩の読み方。"""
    if plan.kind == "segment":
        return [_law_step(pool), _reading_step(pool)]
    steps = ([_correspondence_step(pool)] if pool.initial else []) + [_acquisition_reading_step(pool)]
    if "execution" in plan.args:
        steps.append(_execution_reading_step(pool))
    return steps


def _law_step(pool):
    def build(state, plan):
        from ._fb_core import Slot
        source = _clock_source(state)
        law = plan.args["law"]
        names = [name for ch in law["channels"] for name in ch["route_slots"]]
        configs = [plan.boot.points.get("route_config:" + name) for name in names]
        if source is None or None in configs:
            return None
        d, routes = plan.boot.d, {r.slot: r.value for r in plan.boot.declaration.routes}
        channels = [{"id": ch["id"],
                     "process": _encode(_fb.BootSlot(declaration=d, slot=routes[ch["route_slots"][0]].process_slot)),
                     "route_configs": sorted(plan.boot.points["route_config:" + n] for n in ch["route_slots"]),
                     "domain": {"clock": _f._encode(state.clock.run), **ch["domain"]}} for ch in law["channels"]]
        content = {"model": pool.model, "extends": None, "carrier_by_state": law["carrier_by_state"],
                   "channels": channels, "rows": law["rows"], "frame_relation": "independent_given_carrier"}
        ledger = state.ledger
        uses = (pool.model, d, *sorted(set(configs)), source)
        body = _Prediction(target="count_law", about=(ledger.record(pool.model).id,),
                           basis=tuple(ledger.record(p).id for p in uses),
                           content=_Payload.json(content), contract=_c.FINITE_JOINT_COUNT_LAW)
        return Slot(contract=_c.FINITE_JOINT_COUNT_LAW, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {d, *configs, source}))
    return _Step(name=_reading_name("law", pool), build=build)


def _reading_step(pool):
    def build(state, plan):
        from ._fb_core import Slot
        law = plan.points[_reading_name("law", pool)]
        claims = [{"meaning": e["meaning"], "law": law, "channel": e["channel"]} for e in plan.args["claims"]]
        content = {"model": pool.model,
                   "projection": {"contract": _f._encode(_c.FINITE_SEGMENT_PROJECTION),
                                  "args": {"frame": None, "claims": claims,
                                           "time_projection": {"contract": _f._encode(_c.SEGMENT_VALUE_ONLY),
                                                               "args": {}}}},
                   "generation": {"contract": _f._encode(_c.BOOTSTRAP_GENERATION), "args": plan.args["generation"]}}
        ledger = state.ledger
        law_slot = next(s.slot for s in plan.steps if s.name == _reading_name("law", pool))
        body = _Prediction(target="observation_plan", about=(ledger.record(pool.model).id,),
                           basis=(ledger.record(pool.model).id, ledger.record(law).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=law_slot.parents)
    return _Step(name=_reading_name("reading", pool), build=build)


def _plan(state, boot):
    """δ の方法の名前と版で計画を選ぶ (P9)。読めない方法も計画を置いて不足を示す (計画を作らずに黙らない、K28 の B1)。
    読み方の記録は最初の並び (起動の宣言の 1 枚、`_fb_pool.initial_pool`) から作る。"""
    from ._fb_pool import initial_pool
    perception_slot = boot.declaration.perception
    perception = perception_slot.value
    method = perception.derivation.method
    plan = UpdatePlan(boot=boot, perception=perception, slot=perception_slot.slot, args=_plain(method.args))
    plan.initial = plan.current = initial_pool(state, boot)
    if method.contract == _c.SAVED_SEGMENT_UPDATE:
        reason = _check_args(boot, plan.args)
    elif method.contract == _c.SAVED_ACQUISITION_UPDATE:
        plan.kind = "acquisition"
        reason = _check_acquisition_args(boot, plan.args)
    else:
        reason = "delta:method"
    if reason is not None:
        _hold(plan, reason)
    else:
        plan.steps = _reading_steps(plan, plan.initial)
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


def _correspondence_step(pool):
    """物語の対応の記録 (`sui.fb.state_correspondence/1`、Prediction / MODEL): 最初の並びのモデルの Point と、その口の観測モデル
    の記録の Point を解いて、起動の宣言の pairs と一緒に保存する (K28-a (ア))。読み方より先。足した並びの候補ごとの対応は
    並びの記録が持つ (K37)。"""
    member, = pool.members

    def build(state, plan):
        from ._fb_core import Slot
        observation = plan.boot.points.get("observation_model:" + plan.args["observation_model"])
        if observation is None:
            return None
        ledger = state.ledger
        content = {"model": pool.model, "observation_model": observation, "pairs": member["pairs"]}
        body = _Prediction(target="state_correspondence", about=(ledger.record(pool.model).id,),
                           basis=(ledger.record(pool.model).id, ledger.record(observation).id),
                           content=_Payload.json(content), contract=_c.STATE_CORRESPONDENCE)
        return Slot(contract=_c.STATE_CORRESPONDENCE, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.boot.d}))
    return _Step(name="correspondence", build=build)


def _acquisition_reading_step(pool):
    """読み方 (`sui.f.observation_plan/2`): projection = `acquisition_sequence_projection/1`、generation =
    `acquisition_generation/1` {}。最初の並びは {observation_model, correspondence, time_projection}、足した並びは
    {pool, observation_model, time_projection} (各候補の観測モデルと物語の対応は並びの記録が持ち、observation_model は
    取りに行きの列を読む口の宣言 = 起動の観測モデルの記録、K37 決定 6)。"""
    def build(state, plan):
        from ._fb_core import Slot
        observation = plan.boot.points["observation_model:" + plan.args["observation_model"]]
        time_projection = {"contract": _f._encode(_VALUE_ONLY), "args": {}}
        ledger = state.ledger
        if pool.initial:
            correspondence = plan.points["correspondence"]
            args = {"observation_model": observation, "correspondence": correspondence,
                    "time_projection": time_projection}
            basis = (pool.model, observation, correspondence)
        else:
            args = {"pool": pool.point, "observation_model": observation, "time_projection": time_projection}
            basis = (pool.model, pool.point, observation)
        content = {"model": pool.model,
                   "projection": {"contract": _f._encode(_c.ACQUISITION_SEQUENCE_PROJECTION), "args": args},
                   "generation": {"contract": _f._encode(_c.ACQUISITION_GENERATION), "args": {}}}
        body = _Prediction(target="observation_plan", about=(ledger.record(pool.model).id,),
                           basis=tuple(ledger.record(p).id for p in basis),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {pool.decision or plan.boot.d}))
    return _Step(name=_reading_name("reading", pool), build=build)


def _execution_reading_step(pool):
    """行った一歩の読み方 (`sui.f.observation_plan/2`、K36 決定 5): projection = `execution_step_projection/1`
    {execution_declaration} (その一歩の節の核と、行う一歩の宣言のセル)、generation = `execute_step/1` {}。モデルは並びのモデル
    (足した並びでは、各候補をその候補の核で読む、K37 決定 6)。"""
    def build(state, plan):
        from ._fb_core import Slot
        declaration = plan.boot.points.get("execution")
        if declaration is None:
            return None
        content = {"model": pool.model,
                   "projection": {"contract": _f._encode(_c.EXECUTION_STEP_PROJECTION),
                                  "args": {"execution_declaration": declaration}},
                   "generation": {"contract": _f._encode(_c.EXECUTE_STEP), "args": {}}}
        ledger = state.ledger
        body = _Prediction(target="observation_plan", about=(ledger.record(pool.model).id,),
                           basis=(ledger.record(pool.model).id, ledger.record(declaration).id),
                           content=_Payload.json(content), contract=_c.OBSERVATION_PLAN_2)
        return Slot(contract=_c.OBSERVATION_PLAN_2, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {pool.decision or plan.boot.d}))
    return _Step(name=_reading_name("execution_reading", pool), build=build)


# --- 候補の並び (紙 F-b K37 決定 1〜8) ---

def _reading_point(plan, pool, kind):
    """並び pool で観測の種類 (frame / execution) を読む読み方の記録の Point。まだ保存していなければ None。"""
    return plan.points.get(_reading_name("execution_reading" if kind == "execution" else "reading", pool))


def _pool_of(plan, ob):
    """その義務が読む並び: Q* を作った時の並び、まだなら今の並び (解けなければ最後に解けた最初の並び、表示用)。"""
    if ob.pool is not None:
        return ob.pool
    return plan.current if plan.current is not None else plan.initial


def _model_of(plan, ob):
    return _pool_of(plan, ob).model


def _origin_of(plan, ob):
    return _pool_of(plan, ob).origin


def _stop(plan, reason, binding, targets=()) -> None:
    """系列の採用を止める (待っても解けない)。止まりは今の並びの下でだけ効く。"""
    plan.stopped = (reason, binding, tuple(dict.fromkeys(targets)), plan.current.model)


def _resolve(state, plan) -> None:
    """今の境目 (置き場の頭) で効いている並びを解く (K37 決定 3。解くのは `_fb_pool.resolve` の 1 か所)。新しい並びなら、
    その読み方の記録の歩を足す (並びの解決から作る)。前の並びの下で止まった系列は、新しい並びで導き直す。解けなければ
    (比べられない足し・読めない記録) 新しい要求を作らない (前の並びへ黙って戻らない)。"""
    from ._fb_pool import resolve
    try:
        pool = resolve(state, plan.boot, state.ledger.heads())
    except _fb.CandidatePoolError:
        plan.current = None
        return
    plan.current = pool
    if plan.stopped is not None and plan.stopped[3] != pool.model:
        plan.stopped = None
    names = {s.name for s in plan.steps}
    plan.steps += [step for step in _reading_steps(plan, pool) if step.name not in names]


def _head_model(plan):
    """系列の頭 (最後に採用を確かめた A*) の並びの model。採用がまだなら最初の並びのモデル。"""
    for ob in plan.obligations.values():
        if plan.chain and ob.points.get("A") == plan.chain[-1]:
            return _model_of(plan, ob)
    return plan.initial.model


def _relist(plan) -> list:
    """作り直しが読み直す観測 (K37 決定 4): 系列の頭の数値に読んだ観測 (順に) と、止まった結末の観測 (前の並びで質量 0
    などで止まったもの。新しい並びで読めれば読む)。まだ要求を作っていない観測は、作り直しの後にふつうに読む。"""
    stuck = [o for o in plan.obligations.values() if o.kind != "rebuild" and o.final not in (None, "adopted")
             and o not in plan.applied]
    stuck.sort(key=lambda o: (o.interval[0], o.seq if o.seq is not None else 0))
    return [*plan.applied, *stuck]


def _need_rebuild(plan) -> None:
    """今の並びが系列の頭の並びと違えば、足した決定をきっかけに作り直しの義務を 1 つ置く (K37 決定 4: 足したこと自体は
    観測に数えない、観測の無い要求)。まだ要求を作っていない、追い越された並びの作り直しは置かない (記録は無い)。"""
    pool = plan.current
    if pool is None or pool.model == _head_model(plan):
        return
    for key, ob in list(plan.obligations.items()):
        if ob.kind == "rebuild" and ob.desc is None and ob.pool.model != pool.model:
            del plan.obligations[key]
    if pool.decision not in plan.obligations:
        ob = Obligation(report=pool.decision, binding=pool.decision, kind="rebuild", pool=pool, interval=(0, 0))
        ob.steps = [_q_step(ob)]
        plan.obligations[pool.decision] = ob


def _next_rebuild(state, plan):
    """作り直しの要求を作れるか (K37 決定 4・K36 決定 12): 読み直す観測が今の並びの各候補で読め、区間の重なる別の種類の
    観測どうしが、宣言と各候補のかたまりの交換で順に依らない時だけ。そうでなければ名指して止める。"""
    rebuild = plan.obligations.get(plan.current.decision)
    if rebuild is None or rebuild.desc is not None or rebuild.final is not None:
        return None
    relist = _relist(plan)
    for ob in relist:
        blocks = _blocks(state, plan, ob)
        if isinstance(blocks, _Unread):
            _stop(plan, blocks.reason, ob.binding, blocks.targets)
            return None
    decl = _declaration_of(plan)
    for i, a in enumerate(relist):
        for b in relist[i + 1:]:
            if a.kind == b.kind or a.interval[1] < b.interval[0]:
                continue
            step = a if a.kind == "execution" else b
            bad = _noncommuting(plan.current, _blocks(state, plan, a), _blocks(state, plan, b))
            if a.interval[0] > b.interval[1] or decl is None \
                    or "undeclared" in (decl.source_overlap, decl.actor_overlap) or bad:
                _stop(plan, "observation_order_unknown", step.binding, bad)
                return None
    rebuild.relist = relist
    return rebuild


def pool_head(plan, pool, seen):
    """境目 seen に見える、その並びの最新の採用 A* (保存を確かめたもの)。無ければ None。"""
    models = {ob.points["A"]: _model_of(plan, ob) for ob in plan.obligations.values() if "A" in ob.points}
    return next((a for a in reversed(plan.chain) if models.get(a) == pool.model and a in seen), None)


def pool_stop(state, plan, pool, seen):
    """その並びの系列が、境目 seen に見える観測で止まっているか (待っても解けない、K37 決定 3・4)。止まっていれば
    (理由の語, 名指しの Point の列)。系列の止まり (順が分からない・読めない・質量 0) と、U の不適合・不足・依存の食い違い
    などの結末。候補を足した後の作り直しが読み直した結末は数えない。"""
    if plan.stopped is not None and plan.stopped[3] == pool.model and plan.stopped[1] in seen:
        return plan.stopped[0], tuple(dict.fromkeys((*plan.stopped[2], plan.stopped[1])))
    bad = _clashed_reports(state)
    for ob in plan.obligations.values():
        own = ob.pool if ob.pool is not None else plan.current
        if ob.superseded or ob.final in (None, "adopted") or own is None or own.model != pool.model \
                or ob.report not in seen:
            continue
        if ob.final == "conflicted":
            uses = ob.desc.input_points if ob.desc is not None else frozenset(o.report for o in _covered(plan, ob))
            targets = tuple(sorted(bad & uses)) or (ob.report,)
        else:
            targets = ob.evidence or (ob.points.get("Q") or ob.report,)
        return (ob.reasons[0] if ob.reasons else ob.final), tuple(targets)
    return None


def _covered(plan, ob) -> list:
    """その義務が読む観測の義務 (作り直しは読み直す列、ほかは自分)。"""
    if ob.kind != "rebuild":
        return [ob]
    return ob.relist if ob.relist is not None else _relist(plan)


# --- 今の並びで観測を読むセルの行列 (候補ごとのかたまり。入口 U と同じ関数で作る、K37 決定 6) ---

class _Unread:
    """今の並びで読めない観測の名指し (理由の語, 名指しの Point の列)。"""

    def __init__(self, reason, targets=()):
        self.reason, self.targets = reason, tuple(targets)


def _declaration_of(plan):
    from ._fb_act import declaration
    return declaration(plan.boot)


def _sampling(plan):
    route = next(r.value for r in plan.boot.declaration.routes if r.slot == plan.args["route"])
    return route.config.sampling_contract


def _frame_blocks(state, plan, symbol):
    """受け身の取りに行き 1 回 (観測の語 symbol) の、候補ごとのかたまり (各候補の状態の順、正規化する前のセルの和)。"""
    from . import f_update2 as u2
    try:
        out = []
        for m in plan.current.members:
            ev = (m["model"],)
            control, phi = u2.member_reading(m, route=plan.current.route, evidence_model=ev, evidence_pairs=ev)
            out.append(u2.passive_block(control, phi, symbol, sampling=_sampling(plan), evidence=ev))
        return out
    except u2._Issue as issue:
        return _Unread(issue.code, issue.evidence)


def _step_blocks(state, plan, u, value):
    """行った一歩 (核 u、観測 value) の、候補ごとのかたまり。各候補はその候補が宣言したその操作の核で読む。足した並びでは、
    読めない候補の宣言 (観測モデル・物語の対応) もここで名指す (入口 U と同じ)。読むセルが無ければ exception_reading_missing。"""
    from . import f_update2 as u2
    cells = [u2._json(_f._encode(cell)) for cell in _declaration_of(plan).cells.get(u, ())]
    try:
        kernels = []
        for m in plan.current.members:
            ev = (m["model"],)
            if not plan.current.initial:
                u2.member_reading(m, route=plan.current.route, evidence_model=ev, evidence_pairs=ev)
            kernels.append((m, u2.step_kernel(m["document"], u, cells, evidence=ev)[1]))
    except u2._Issue as issue:
        return _Unread(issue.code, issue.evidence)
    found = [cell for cell in cells if cell["observation"]["value"] == u2._json(value)]
    if len(found) != 1:
        return _Unread("exception_reading_missing")
    return [u2.cell_sum(matrices, found[0]["outcomes"], m["size"]) for m, matrices in kernels]


def _blocks(state, plan, ob):
    """観測の義務 ob を今の並びで読むセルの、候補ごとのかたまり。読めなければ _Unread。"""
    from . import _fb_read
    if ob.kind == "execution":
        return _step_blocks(state, plan, ob.result.execution.u, ob.result.value)
    frame = _frame_value(state, ob.report)
    return _frame_blocks(state, plan, _fb_read._SYMBOLS[(frame.value["result"]["kind"], bool(frame.value["source_called"]))])


def _noncommuting(pool, a, b) -> list:
    """2 つの観測のかたまりが両方の順で同じでない候補のモデル (どちらかが読めなければ全部の候補)。"""
    if isinstance(a, _Unread) or isinstance(b, _Unread):
        return [m["model"] for m in pool.members]
    return [m["model"] for m, x, y in zip(pool.members, a, b) if _product(x, y) != _product(y, x)]


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
    """次に Q* を作る義務 (K28 新しい決定 5・K36 決定 12): 受け身の取りに行きは番号 i = 系列の頭の数値に読んだ取りに行きの数の
    Frame (0〜i - 1 は採用されて確認済み、原文も保存済みの時だけ)、行った一歩は入場の順の最初の未採用。両方あれば時計の
    読みの前後で決め、重なりは宣言とセルの行列の交換で決める (決まらなければ系列を止める)。採用以外の結末・進行中・
    確認待ち・順の来る観測の保存待ちがあれば待つ。印でなく状態で決める。今の並びが系列の頭の並びと違えば、先に作り直し
    (K37 決定 4)。"""
    if plan.current is None or plan.stopped is not None or _pending_clash(state, plan) or _head(plan) == "wait":
        return None
    if _head_model(plan) != plan.current.model:
        return _next_rebuild(state, plan)
    if any(ob.final not in (None, "adopted") and not ob.superseded for ob in plan.obligations.values()):
        return None
    passive_done = sum(1 for ob in plan.applied if ob.kind == "frame")
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


def _applied_clash(state, plan, ob) -> bool:
    """系列の頭の数値に読んだ別の種類の観測 (取りに行き ↔ 行った一歩) と ob の区間が重なり、宣言が述べていないか、セルの
    かたまりが両方の順で同じでない候補がある (K36 決定 12)。そうなら系列の採用を「順が分からない」で止める (待っても
    解けない。名指しは一歩と、交換しない候補)。入口 U の順の確かめと同じ規則 (区間の端の読みが同じなら重なり)。"""
    decl = _declaration_of(plan)
    for other in plan.applied:
        if other.kind == ob.kind:
            continue
        step = ob if ob.kind == "execution" else other
        if other.interval[0] > ob.interval[1]:
            # もう採用した観測が、この観測の終わりより後に始まっている = 順を飛ばす (入口 U と同じ規則、レビュー R6)
            _stop(plan, "observation_order_unknown", step.binding)
            return True
        if other.interval[1] < ob.interval[0]:
            continue
        bad = _noncommuting(plan.current, _blocks(state, plan, ob), _blocks(state, plan, other))
        if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap) or bad:
            _stop(plan, "observation_order_unknown", step.binding, bad)
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
    観測があれば、それを先に採用し、次の回にもう一度見る (後の組を理由に前の採用を止めない、レビュー R9)。行列は今の並びの
    候補ごとのかたまり (K37)。"""
    pending = [ob for ob in plan.obligations.values() if ob.final is None and ob.kind != "rebuild"]
    for step in (ob for ob in pending if ob.kind == "execution"):
        b = _blocks(state, plan, step)
        for frame in (ob for ob in pending if ob.kind == "frame"):
            if frame.interval[1] < step.interval[0] or frame.interval[0] > step.interval[1]:
                continue
            commute, bad = _commute(state, plan, frame, b)
            if commute:
                continue
            if any(_strictly_before(o, frame) and _strictly_before(o, step) for o in pending
                   if o is not frame and o is not step):
                continue   # この組より前の観測がまだ採用されていない: 先に進める
            if isinstance(b, _Unread):
                _stop(plan, b.reason, step.binding, b.targets)
            else:
                _stop(plan, "observation_order_unknown", step.binding, bad)
            return True
    return False


def _readable(state, plan, step):
    """読むセルの無い一歩の結果 (例外の読み方が無い)・今の並びのどれかの候補で読めない一歩は、その系列の採用を止める
    (K36 決定 13・K37 決定 6、待っても解けない)。"""
    blocks = _blocks(state, plan, step)
    if isinstance(blocks, _Unread):
        _stop(plan, blocks.reason, step.binding, blocks.targets)
        return None
    if not any(x for block in blocks for row in block for x in row):
        # 読めるセルの行列が 0: どの見立てでも質量 0 (U は model_falsified で断る)。系列はここで止まる
        _stop(plan, "model_zero", step.binding)
        return None
    return step


def _unsaved_step_before(state, plan, frame) -> bool:
    """入場した観測の一歩のうち、結果がまだ保存されていない (行っている途中・保存待ち) もので、この取りに行き frame との
    順が今は決まらないものがあるか (K36 決定 12)。frame が一歩の入場より前に終わっていれば前 (待たない)。結果の記録の読みが
    分かっていて frame がそれより後に始まれば一歩が前 (結果の保存を待つ)。それ以外は重なりで、世界の宣言が述べていて、
    frame のかたまりが一歩の結果の読みうるどのセルのかたまりとも両方の順で同じ時だけ待たない (どの結果でも順で答えが
    変わらない)。観測でない一歩 (宣言した無作用・未接続) は順に関わらない。"""
    from ._fb_act import classify, result_of
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
                decl = _declaration_of(plan)
                if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap):
                    return True
                a = _blocks(state, plan, frame)
                if any(_noncommuting(plan.current, a, _step_blocks(state, plan, E.u, cell.observation.value))
                       for cell in decl.cells.get(E.u, ())):
                    return True
    return False


def _passive_open_before(state, plan, passive_done, step) -> bool:
    """受け身の取りに行きで、まだ義務になっていないもののうち、一歩 step との順が今は決まらないものがあるか (K36 決定 12)。
    公開して保存待ちのもので、始まりが一歩の終わり以前のものは待つ (義務になれば区間で比べられる)。源を読みに行っている
    途中のものは、始まりが一歩の終わり以前なら重なり (終わりは一歩の後)、世界の宣言が述べていて、一歩のかたまりが
    その取りに行きの読みうるどの観測のかたまりとも両方の順で同じ時だけ待たない。"""
    from . import _fb_read
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
    decl = _declaration_of(plan)
    if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap):
        return True
    b = _blocks(state, plan, step)
    return any(_noncommuting(plan.current, _frame_blocks(state, plan, symbol), b)
               for symbol in sorted(set(_fb_read._SYMBOLS.values())))


def _product(a, b):
    from fractions import Fraction
    n = len(a)
    return [[sum((a[i][k] * b[k][j] for k in range(n)), Fraction(0)) for j in range(n)] for i in range(n)]


def _commute(state, plan, frame, step_blocks):
    """重なりの適用条件 (K36 決定 12): 宣言が両方の相手について「途中も状態を変えない」か「1 回ずつの前後で表せる」と
    述べ、実際に読んだセルのかたまりどうしが、どの候補でも両方の順で同じ。(交換するか, 交換しない候補のモデル)。"""
    decl = _declaration_of(plan)
    if decl is None or "undeclared" in (decl.source_overlap, decl.actor_overlap) or isinstance(step_blocks, _Unread):
        return False, []
    bad = _noncommuting(plan.current, _blocks(state, plan, frame), step_blocks)
    return not bad, bad


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
    # 作り直しは読み直す観測の原報告に頼る (K22 の食い違いは並びが替わっても解除しない、K37 決定 4)
    return any(o.report in bad for o in _covered(plan, ob)) \
        or bool(plan.chain) and not bad.isdisjoint(uses_of(state, plan.chain[-1]))


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


def adopted_model(state, boot, cid):
    """その Boot の採用 A* (保存の確認待ちの準備した CID も) が採用した見立てのモデル (並びのモデル、K37)。知らなければ None。"""
    for plan in state.updates.values():
        if plan.boot is not boot:
            continue
        for ob in plan.obligations.values():
            step = next((s for s in ob.steps if s.name == "decide"), None)
            if ob.points.get("A") == cid or step is not None and step.slot is not None and step.slot.prepared.cid == cid:
                return _model_of(plan, ob)
    return None


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
           "origin": plan.initial.origin, "raw_report": ob.report, "role": "trigger",
           "purpose": "belief_update"}
    stage = "update:" + _hashlib.sha256(_dumps({"domain": "sui.fb.delta_stage/1", **key})).hexdigest()
    work = "sui.fb.work:" + _hashlib.sha256(_dumps({"domain": "sui.fb.delta_work/1", **key,
                                                    "stage_slot": stage})).hexdigest()
    return stage, work


def _inputs(state, plan, ob, prior, pool) -> frozenset:
    """Q* が読む記録 (U が一次事実から作り直すのに要る全部): この観測の B・原報告・測る要求・読み方・法則・モデルと、
    前の採用があればその A*・R*・Q* と、その Q* が読んだ全部 (系列をさかのぼった閉包)。候補を足した並びでは、並びとその
    参照の閉包 (並びの記録・来歴の並びと足した決定・候補の記録とモデル・読み手) も入れる (K37 決定 3)。作り直しは
    足した決定と、読み直す観測の全部。"""
    ledger = state.ledger
    if plan.kind == "segment":
        b = ledger.record(ob.binding).body.content.as_json()
        out = {plan.boot.d, pool.origin, pool.model, plan.points[_reading_name("law", pool)],
               _reading_point(plan, pool, "frame"), ob.binding, ob.report, b["segment"], b["route"]}
    else:
        out = {plan.boot.d, pool.origin, pool.model} | (set() if pool.initial else set(pool.records))
        if ob.kind == "rebuild":
            out.add(ob.report)
        for o in _covered(plan, ob):
            out |= _observation_inputs(state, plan, pool, o)
    if prior is not None:
        adopted = ledger.record(prior).body.content.as_json()
        previous = ledger.record(adopted["request"]).body.content.as_json()["desc"]
        out |= {prior, adopted["result"], adopted["request"], adopted["acquisition"], *previous["input_points"]}
    return frozenset(out)


def _observation_inputs(state, plan, pool, ob) -> set:
    """観測 1 つを並び pool で読むのに要る記録。"""
    ledger = state.ledger
    if ob.kind == "execution":
        # 行った一歩の結果 (K36 決定 5): 結果のメモ・読み方・行う一歩の宣言の記録 (足した並びでは E のモデルも)
        out = {_reading_point(plan, pool, "execution"), ob.binding, ob.result.execution.reading}
        return out if pool.initial else out | {ob.result.execution.model}
    # 取りに行きの列 (K28 (2)(e)): 観測モデル・物語の対応・読み方と、この回の Frame・B・取れた回の原文。0〜i - 1 の
    # Frame・B・原文は、前の採用の Q* が読んだ全部 (系列をさかのぼった閉包) に入っている
    b = ledger.record(ob.binding).body.content.as_json()
    out = {_reading_point(plan, pool, "frame"), plan.boot.points["observation_model:" + plan.args["observation_model"]],
           ob.binding, ob.report, b["segment"], b["route"]}
    if pool.initial:
        out.add(plan.points["correspondence"])
    received = _received(_frame_value(state, ob.report))
    if received is not None:
        out.add(ledger.entries_of(received)[0].cid)
    return out


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
        # 読む並び: 作り直しは足した並び、ほかは今の境目で効いている並び (解けなければ作らない)
        pool = ob.pool if ob.kind == "rebuild" else plan.current
        if pool is None:
            return None
        d, initial, origin, model = plan.boot.d, plan.perception, pool.origin, pool.model
        observations = []
        for o in _covered(plan, ob):
            reading = _reading_point(plan, pool, o.kind)
            if reading is None:
                return None   # その並びの読み方の記録の保存待ち
            observations.append(_fb.ObservationUse(binding=o.binding, reading=reading))
        stage, work_id = _names(plan, ob)
        inputs = _inputs(state, plan, ob, prior, pool)
        desc = _fb.Desc(
            work_id=work_id,
            process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
            trigger=frozenset({_fb.Trigger(point=ob.report, slot="trigger")}),
            purpose="belief_update", stage_slot=stage, reader=origin,
            method=_c.FINITE_UPDATE_COMPUTE, output_contract=_c.UPDATE_RESPONSE,
            args=_fb.UpdateArgs(model=model, prior=prior, observations=tuple(observations)),
            input_points=inputs, numerical_view=_fixed_view(state, inputs),
            allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=initial.derivation.slot),
                                   _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))
        # Desc を義務に置く (= 要求を作った印) のは、記録の準備が通った後 (紙 §2-4 :323「『済み』の印だけ先に
        # 置かない」)。ここで置くと、下の読みや準備が失敗した時に、入り直しで同じ義務の Q* を作り直せなくなる
        drafted["desc"], drafted["pool"] = desc, pool
        ledger = state.ledger
        body = _Decided(inputs=tuple(ledger.record(p).id for p in sorted(inputs)),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.WORK_REQUESTED)
        return Slot(contract=_c.WORK_REQUESTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, inputs))

    def prepared(state, plan_ob, cid):
        from ._fb_core import add_work
        plan, ob = plan_ob
        ob.desc, ob.pool = drafted["desc"], drafted["pool"]
        if ob.kind == "rebuild":
            # 作り直しが読み直した止まった結末は、もう系列を止めない (K37 決定 4)
            for other in plan.obligations.values():
                if other is not ob and other.final not in (None, "adopted"):
                    other.superseded = True
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
            state.acquisitions.append(AcquisitionObservation(origin=_origin_of(plan, ob),
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
        origin, r, clock = _origin_of(plan, ob), ob.points["R"], ob.points["a"]
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
        origin, q, r, g = _origin_of(plan, ob), ob.points["Q"], ob.points["R"], ob.points["G"]
        model = _model_of(plan, ob)
        if ob.desc.args.prior == head:
            ob.points["decision"] = "A"
            content = {"origin": origin, "model": model, "previous": head, "request": q,
                       "result": r, "acquisition": g}
            uses = {origin, model, q, r, g} | ({head} if head else set())
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
        ob.evidence = tuple(dict.fromkeys(str(e) for i in issues for e in i.get("evidence", ())))   # 名指し (K37)
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
        _resolve(state, plan)   # 今の境目で効いている並び (K37 決定 3)。新しい並びの読み方の記録もここで保存する
        if plan.current is not None and not plan.current.initial:
            _advance(state, plan)
        _discover(state, plan)
        if plan.kind == "acquisition" and plan.current is not None:
            _need_rebuild(plan)
            if plan.stopped is None:
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
                    # 系列の頭の数値に読んだ観測: 作り直しは読み直した列に並び直す (K37 決定 4)
                    if ob.kind == "rebuild":
                        plan.applied = list(ob.relist)
                    elif plan.kind == "acquisition":
                        plan.applied.append(ob)
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
        adopted_frames = sum(1 for ob in plan.applied if ob.kind == "frame")
        tails = {"published_through": takes[-1].sample_seq, "saved_through": through if through >= 0 else None,
                 # 受け身の取りに行きの採用だけを数える (一歩の結果の採用は別、レビュー R4)
                 "adopted_through": adopted_frames - 1 if adopted_frames else None}
        for take, ok in zip(takes, saved):
            frame = _saved_point(state, take.frame_envelope)
            own = plan.obligations.get(frame) if frame is not None else None
            # 候補を足した後の作り直しがこの回を読み直していれば、その結末を見せる (どの並びで読んだかは model、K37)
            covering = [o for o in plan.obligations.values()
                        if o.kind == "rebuild" and o.desc is not None and own is not None and own in o.relist]
            ob = covering[-1] if covering else own
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
                model=(_pool_of(plan, ob) if ob is not None else plan.initial).model,
                origin=(_pool_of(plan, ob) if ob is not None else plan.initial).origin,
                route_epoch=take.route_epoch, sample_seq=take.sample_seq,
                obligation=own.binding if own is not None else None,
                request=ob.points.get("Q") if ob is not None else None, outcome=outcome,
                reading=own.reading if own is not None else None, reasons=reasons, fields=fields, **tails))
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
