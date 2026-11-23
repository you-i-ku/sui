"""Boot から起動の計画を作る (紙 F-b §2-4-0・§2-5-9・§2-5-10・§6-5 G1〜G5、段 1)。

保存した boot_declaration d から、観測モデルの記録 (observation_models の各項、§6-10 K26-a (ア)) と行う一歩の宣言の
記録 (execution、K36) → 測る口の実適用 (route_config) → 続けて測る要求 k、感じる側 perception があれば knowledge_origin、
考える側 initial があれば最初の候補の生成の要求 Qgen を、1 点ずつ保存する (K36 新しい決定 2: 感じる側と考える側を分ける)。
各記録は最初に作った時に固定し (保存の再試行・窓口の作り直しで作り直さない)、後の記録が
前の記録の Point を要る時だけ、その保存の後に作る。前提が足りない枝は対象つきの未完として
持ち、正常な枝の完了と分ける。仕事の行は要求の保存の後に置く (FWork.request は Point)。
"""

import hashlib as _hashlib
from fractions import Fraction as _Fraction
from dataclasses import dataclass as _dataclass, field as _field

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from ._fb_wire import dumps as _dumps, encode as _encode
from .clock_contracts import SOURCE as _CLOCK_SOURCE
from .contracts import ContractRef as _ContractRef
from .f_contracts import KNOWLEDGE_ORIGIN as _KNOWLEDGE_ORIGIN, MODEL_SOURCE as _MODEL_SOURCE, ROUTE_CONFIG as _ROUTE_CONFIG
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Prediction as _Prediction, Record as _Record, Role as _Role

_EMPTY_ARGS = _ContractRef("sui.f.args.empty", "1")


@_dataclass
class Step:
    """計画の 1 記録。slot は build が返した時に固定する。"""
    name: str
    build: object                # (state, plan) -> Slot | None (None は前提がまだ保存されていない)
    on_prepared: object = None   # (state, plan, cid) -> None: Publish と同じ歩で仕事の行を置く
    slot: object = None


@_dataclass
class BootPlan:
    """1 つの Boot の起動の計画 (P.units の義務の持ち主)。missing は対象つきの未完。"""
    declaration: object          # BootDeclaration
    d: str                       # 保存した boot_declaration の Point
    steps: list = _field(default_factory=list)
    points: dict = _field(default_factory=dict)
    missing: list = _field(default_factory=list)
    applied: dict = _field(default_factory=dict)   # route の slot → 実適用の M の読み (ns、G2・§6-8 B6)


def _quantity(value) -> bool:
    return (isinstance(value, _fb.QuantityValue) and value.contract == _c.SEATS
            and type(value.value) is int and value.value >= 0)


def _declared(state, kind, ref) -> bool:
    return any(d.kind == kind and d.ref == ref for d in state.registry.declarations)


def _work_id(d, position, purpose, stage_slot) -> str:
    """G3: 論理の鍵 (宣言の Point・宣言の位置・用途・stage_slot) の名前空間つきの正準符号化の hash。
    要求自身の CID は使わない (自己参照になる)。同一性の証明は Desc の全内容の照合で行う。"""
    key = {"domain": "sui.fb.work_id/1", "boot": d, "position": position,
           "purpose": purpose, "stage_slot": stage_slot}
    return "work:" + _hashlib.sha256(_dumps(key)).hexdigest()


def plan_boot(state, declaration, d) -> BootPlan:
    """宣言の意味の照合 (§2-5-3・G5) と計画の組み立て。負の量や割当の超過を丸めて合法にしない。"""
    plan = BootPlan(declaration=declaration, d=d)
    scope = declaration.scope.value
    if not _quantity(declaration.capacity):
        plan.missing.append("capacity")
        return plan
    # 宣言の位置は宣言の中で一意に解決できること。曖昧な slot を名前や並び順で選ばない (:2112、R08)
    initial, perception, execution = declaration.initial, declaration.perception, declaration.execution
    positions = [declaration.scope.slot, declaration.environment.slot,
                 *(name for r in declaration.routes
                   for name in (r.slot, r.value.allocation.slot, r.value.process_slot)),
                 *((perception.slot, perception.value.allocation.slot, perception.value.process_slot,
                    perception.value.reader_slot, perception.value.derivation.slot) if perception is not None else ()),
                 *((initial.slot, initial.value.allocation.slot, initial.value.process_slot)
                   if initial is not None else ()),
                 *((execution.slot, execution.value.allocation.slot)
                   if execution is not None and isinstance(execution.value, _fb.ExecutionDeclaration) else ()),
                 *(m.slot for m in declaration.observation_models)]
    ambiguous = sorted({p for p in positions if positions.count(p) > 1})
    if ambiguous:
        plan.missing += [f"slot:ambiguous:{p}" for p in ambiguous]
        return plan
    # 入れ子の値の型は外側の契約が決める。契約名を使う境界で照合する (:2113、R10)
    if not (declaration.scope.contract == _c.RESOURCE_SCOPE and isinstance(scope, _fb.ResourceScope)
            and scope.quantity_contract == _c.SEATS):
        plan.missing.append("scope")
        return plan
    if declaration.environment.contract != _c.ENVIRONMENT:
        plan.missing.append("environment")
        return plan
    state.capacity[d] = declaration.capacity
    # 観測モデルは宣言の保存だけ (中身の検査は読み口の側。正しいことの証明にしない)。initial の有無に結び付けない
    route_slots = {r.slot for r in declaration.routes}
    for model_slot in declaration.observation_models:
        if _OBSERVATION_MODELS.get(model_slot.contract) is not type(model_slot.value):
            plan.missing.append(f"observation_model:{model_slot.slot}:contract")
        elif model_slot.value.route_slot not in route_slots:
            plan.missing.append(f"observation_model:{model_slot.slot}:route")
        else:
            plan.steps.append(_model_step(model_slot))
    def allocation_ok(slot_value):
        a = slot_value.value
        return (slot_value.contract == _c.ALLOCATION and isinstance(a, _fb.Allocation)
                and a.scope_slot == declaration.scope.slot
                and _quantity(a.amount) and a.amount.value <= declaration.capacity.value)

    for route_slot in declaration.routes:
        route = route_slot.value
        config = route.config
        if route_slot.contract != _c.BOOTSTRAP_ROUTE:
            plan.missing.append(f"route:{route_slot.slot}:contract")
            continue
        if not allocation_ok(route.allocation):
            plan.missing.append(f"route:{route_slot.slot}:allocation")
            continue
        if not (_declared(state, "measurement", config.sampling_contract)
                and _declared(state, "clock", config.clock_contract)
                and _declared(state, "measurement", config.loss_contract)
                # 取りに行き方の契約が宣言されていること (§6-10 K27 新しい決定 2)。扱えるかは見張り役が決める
                and _declared(state, "measurement", route.repeat.contract)):
            plan.missing.append(f"route:{route_slot.slot}:missing_contract")
            continue
        state.allocations[_fb.BootSlot(declaration=d, slot=route.allocation.slot)] = route.allocation.value.amount
        plan.steps += _route_steps(route_slot)

    # 感じる側 (K36 新しい決定 2): モデル・読み手 (origin)・割当を自分で持つ。考える側が無くても見立ては直る
    sensing = False
    if execution is not None:
        if _EXECUTIONS.get(execution.contract) is not type(execution.value):
            plan.missing.append("execution:contract")
        elif execution_reading_fault(declaration) is not None:
            # 時刻を読む信念と一緒に通す一歩は、源の件数を読まず変えないと確かめられるものだけ (K38 決定 9)
            plan.missing.append("execution:source_reading")
        elif not allocation_ok(execution.value.allocation):
            # 行う割当は宣言で明示する。省略・不正を追加の席で補わない (K36-c ①・K36-c-a ④ (a))
            plan.missing.append("execution:allocation")
        else:
            a = execution.value.allocation
            state.allocations[_fb.BootSlot(declaration=d, slot=a.slot)] = a.value.amount
            plan.steps.append(_execution_step(execution))
    if perception is not None:
        value = perception.value
        if perception.contract != _c.PERCEPTION or not isinstance(value, _fb.Perception):
            plan.missing.append("perception:contract")
        elif not allocation_ok(value.allocation):
            plan.missing.append("perception:allocation")
        else:
            from ._fb_pool import boot_shortfall
            try:
                state.ledger.entry(value.model)
            except KeyError:
                plan.missing.append("perception:model")
            else:
                # 最初の候補を候補の解決で解く。読めない宣言は起動の計画の不足 (考える・更新・一歩より先、K39-b R1)
                member, missing = boot_shortfall(state.ledger, d)
                if missing is not None:
                    plan.missing.append(missing)
                else:
                    state.allocations[_fb.BootSlot(declaration=d, slot=value.allocation.slot)] = \
                        value.allocation.value.amount
                    if member["document"] is not member["base"]:   # (z, S) に展開した派生のモデル (K39 決定 8)。読み手より先
                        plan.steps.append(_derived_model_step(member["document"]))
                    plan.steps.append(_origin_step(perception))
                    sensing = True
    if initial is not None:
        value = initial.value
        if initial.contract != _c.INITIAL_PROCESS or not isinstance(value, _fb.InitialProcess):
            plan.missing.append("initial:contract")
        elif perception is None or value.perception_slot != perception.slot:
            # 考える側は感じる側の origin とモデルを参照する。感じる側の無い考える側は名指しの不足 (K36-a (オ))
            plan.missing.append("initial:perception")
        elif not allocation_ok(value.allocation):
            plan.missing.append("initial:allocation")
        elif not _declared(state, "generator", value.generator.contract):
            plan.missing.append("initial:missing_contract")
        elif value.continuation is not None and (value.continuation.contract != _c.REUSE_CANDIDATES
                                                 or dict(value.continuation.args) != {}):
            # 継続の方法は reuse_candidates/3 だけ (旧 /2 を黙って別の意味で読まない、P1・K36-c-b (エ))
            plan.missing.append("initial:continuation")
        elif sensing:
            state.allocations[_fb.BootSlot(declaration=d, slot=value.allocation.slot)] = value.allocation.value.amount
            # 最初の活動の入口 (K36-c-a ②): 容量を確かめて入場させ、その活動の中で Wg を 1 回起動する。この時はほかの
            # 活動が無いので、確かめるのは考える割当が 1 席以上あること (0 なら最初の活動も入場しない = Qgen を置かない)
            if value.allocation.value.amount.value >= 1:
                plan.steps.append(_qgen_step(state, initial))
    return plan


def _run_boot(state):
    """この run の原点の起動 (`sui.s4.boot/1`) の保存済みの Point。最初に受け付けたもの (既存の原点の規則)。"""
    from .s4_contracts import BOOT
    for number in state.order:
        receipt = state.receipts[number]
        if isinstance(receipt.envelope.event, _fb.Boot):
            slot = next(s for s in receipt.slots if s.contract == BOOT)
            if slot.entry is not None and slot.record.at.run == state.clock.run:
                return slot.entry.cid
    return None


def clock_sources(state) -> None:
    """時計の知らせ R と同じ run の起動 B の両方が保存されたら、既存 `sui.clock.source/1` S を発行する
    (§6-9 K1)。親 Front({B, R})、本文は照合した原宣言、r は成立を確かめた時の M (U2)。届く順はどちらでもよい。
    別の run の宣言は発行しない。各知らせに 1 つ (宣言の食い違いを最初の 1 件で隠さない)。"""
    from ._fb_core import Slot, mono_ns, save
    boot = _run_boot(state)
    if boot is None:
        return
    for number in state.order:
        receipt = state.receipts[number]
        event = receipt.envelope.event
        if not isinstance(event, _fb.ClockDeclared) or receipt.slots[0].entry is None:
            continue
        notice = receipt.slots[0].entry.cid
        if notice in state.clock_sources or event.declaration.run != state.clock.run:
            continue
        body = _Observed(route="membrane", content=_Payload.json(event.declaration.as_json()), contract=_CLOCK_SOURCE,
                         received_ns=mono_ns(state.clock))
        slot = Slot(contract=_CLOCK_SOURCE, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {boot, notice}))
        slot.prepared = state.ledger.prepare(slot.record, slot.parents)
        state.clock_sources[notice] = slot
    for slot in state.clock_sources.values():
        save(state, slot)


def _clock_source(state):
    """時計を使う所 (route の実効・結びつき・o/j) が指す、発行した sui.clock.source/1 の Point (K1)。
    まだ無い、または発行した宣言どうしが食い違う時は None (最初の 1 件で選ばない)。"""
    saved = [slot for slot in state.clock_sources.values() if slot.entry is not None]
    if not saved or len({slot.record.body.content.data for slot in saved}) != 1:
        return None
    return saved[0].entry.cid


def _events(ledger, points) -> frozenset:
    """Ev: 派生物 (Prediction など) を直接の出来事の親にせず、その出来事の来歴へ展開する (§2-5-1・G4)。"""
    out, pending = set(), list(points)
    while pending:
        entry = ledger.entry(pending.pop())
        if entry.is_event:
            out.add(entry.cid)
        else:
            pending.extend(entry.parents)
    return frozenset(out)


def _front(ledger, points) -> frozenset:
    """Front(Ev(...)): 出来事へ展開してから、ほかの祖先になっているものを除く。"""
    return ledger.maximal(_events(ledger, points))


def _record(state, body, kind, writer):
    from ._fb_core import PRODUCER
    return _Record(id=state.ids.new(kind), at=state.clock.now(), writer=writer,
                   producer=PRODUCER, body=body, schema=3)


# 起動の宣言の値の契約 → 値の型 (契約名を使う境界で照合する、R10)。時刻を読む版は K38
_OBSERVATION_MODELS = {_c.ACQUISITION_OBSERVATION_MODEL: _fb.AcquisitionObservationModel,
                       _c.TIMED_ACQUISITION_MODEL: _fb.TimedAcquisitionModel}
_EXECUTIONS = {_c.EXECUTION_DECLARATION: _fb.ExecutionDeclaration,
               _c.TIMED_EXECUTION_DECLARATION: _fb.TimedExecutionDeclaration}


def execution_reading_fault(declaration):
    """行う一歩の宣言と感じる側の読み方の組み合わせの不足 (K38 決定 9)。時刻を読む感じる側が一歩の結果も読むなら、宣言は
    源の件数の読みつき (timed_execution_declaration) で、読みの全部が E_y(s) ⊗ I_N の形と確かめられること。返すのは
    (理由の語, 欄)。合っていれば None。誕生の入口 `start` と起動の計画が同じこの判定を使う。"""
    from ._fb_time import step_reading_fault
    execution, perception = declaration.execution, declaration.perception
    if execution is None:
        return None
    value = execution.value
    timed_reading = perception is not None and perception.value.derivation.method.contract         == _c.SAVED_TIMED_ACQUISITION_UPDATE and "execution" in perception.value.derivation.method.args
    if isinstance(value, _fb.TimedExecutionDeclaration):
        # 行える一歩 (相手を宣言した核) と、読みを宣言した核の全部を、実行の前と同じ判定で照らす
        for kid in sorted({*value.actors, *value.source_readings}):
            if step_reading_fault(value, kid) is not None:
                return "source_reading", "/declaration/execution/value/source_readings/" + kid
        return None
    return ("source_reading", "/declaration/execution/contract") if timed_reading else None


def _model_step(model_slot):
    """観測モデルの記録 (§6-10 K26-a (ア)・K26-b (ア)): Boot の 1 項から独立した Prediction / MODEL を作る。出どころは
    bootstrap の札と BootSlot (Boot の Point と slot)、about・basis は Boot。親は Boot だけ (Prediction を因果の親にしない)。"""
    name = model_slot.slot

    def build(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        boot = ledger.record(plan.d).id
        content = {"origin": "bootstrap", "declared_at": _encode(_fb.BootSlot(declaration=plan.d, slot=name)),
                   "value": _encode(model_slot.value)}
        body = _Prediction(target="acquisition_observation_model", about=(boot,), basis=(boot,),
                           content=_Payload.json(content), contract=model_slot.contract)
        return Slot(contract=model_slot.contract,
                    record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.d}))

    return Step(name="observation_model:" + name, build=build)


def _execution_step(execution_slot):
    """行う一歩の宣言の記録 (`sui.fb.execution_declaration/2`、K36・K36-c ①): Boot の 1 項から独立した Prediction / MODEL。出どころは
    bootstrap の札と BootSlot。行う一歩の固定の像 E の reading はこの記録を指す (宣言を正しいことの証明にしない)。"""
    name = execution_slot.slot

    def build(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        boot = ledger.record(plan.d).id
        content = {"origin": "bootstrap", "declared_at": _encode(_fb.BootSlot(declaration=plan.d, slot=name)),
                   "value": _encode(execution_slot.value)}
        body = _Prediction(target="execution_declaration", about=(boot,), basis=(boot,),
                           content=_Payload.json(content), contract=execution_slot.contract)
        return Slot(contract=execution_slot.contract, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(ledger, {plan.d}))

    return Step(name="execution", build=build)


def _route_steps(route_slot):
    route = route_slot.value
    name = route_slot.slot

    def build_route_config(state, plan):
        # G2: ホストが受け口の設定を実際に適用し、その境目で M を読む (受信・保存の時刻ではない)。
        source = _clock_source(state)
        if source is None:
            return None
        from ._fb_core import Slot, mono_ns
        epoch = route.config.route_epoch
        active = state.routes.get(epoch)
        # 照合は正準 JSON の bytes で (True と 1 を同じにしない、R14)
        if active is not None and _dumps(_f._encode(active[0])) != _dumps(_f._encode(route.config)):
            if f"route:{name}:epoch_conflict" not in plan.missing:
                plan.missing.append(f"route:{name}:epoch_conflict")
            return None
        # 実適用: ホストの受け口の表に設定を入れる。以後この route_epoch の報告はこの設定で
        # 照合される (結びつきの route の照合、R01・R03)。その境目で M を読む
        applied_ns = mono_ns(state.clock)
        state.routes[epoch] = (route.config, applied_ns)
        plan.applied[name] = applied_ns
        reading = _f.ClockReading(run=state.clock.run, time_ns=applied_ns)
        ledger = state.ledger
        # 既存の契約の DTO で符号化する (effective_from は ClockReading | Unavailable の和型、F-a A:29)
        from .f_entry import RouteApplied
        content = _f._encode(RouteApplied(config=route.config, effective_from=reading, execution=None,
                                          evidence=(ledger.record(plan.d).id, ledger.record(source).id)))
        body = _Observed(route="fb", content=_Payload.json(content), contract=_ROUTE_CONFIG,
                         received_ns=applied_ns)
        return Slot(contract=_ROUTE_CONFIG, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=frozenset({plan.d, source}))

    def build_k(state, plan):
        from ._fb_core import Slot
        d, route_point = plan.d, plan.points["route_config:" + name]
        desc = _fb.Desc(
            work_id=_work_id(d, name, "measure_segment", "route:" + name),
            process=_fb.BootSlot(declaration=d, slot=route.process_slot),
            trigger=frozenset({_fb.Trigger(point=d, slot=name)}),
            purpose="measure_segment", stage_slot="route:" + name, reader=None,
            method=route.config.sampling_contract, output_contract=_c.SEGMENT_REPORT,
            # G1: 続けて測る。終わりを先に数にしない (§6-5)
            args=_fb.SegmentArgs(route=route_point, requested=_fb.Ongoing(clock=state.clock.run),
                                 start_reason="bootstrap", repeat=route.repeat),   # K27: 起動の時に固定
            input_points=frozenset({d, route_point}), numerical_view=None,
            allocation=_fb.BootSlot(declaration=d, slot=route.allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=name),
                                   _fb.BootSlot(declaration=d, slot=route.allocation.slot)}))
        plan.points["desc:" + name] = desc
        ledger = state.ledger
        body = _Decided(inputs=(ledger.record(d).id, ledger.record(route_point).id),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.SEGMENT_REQUESTED)
        return Slot(contract=_c.SEGMENT_REQUESTED, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, {d, route_point}))

    def k_prepared(state, plan, cid):
        from ._fb_core import add_work
        add_work(state, _fb.MeasureSegment(request=cid, desc=plan.points["desc:" + name]),
                 plan.declaration.scope.value)

    return [Step(name="route_config:" + name, build=build_route_config),
            Step(name="k:" + name, build=build_k, on_prepared=k_prepared)]


def _derived_model_step(document):
    """最初の並びの派生のモデルの記録 (`sui.f.model_source/1`、Prediction / MODEL、K39 決定 8): 起動の宣言の候補を候補の解決で
    展開した document (スイッチの列 z × 状態、知る対象は率の表の識別つき)。入口 U は同じ解決で作り直して照らす。about・basis は
    起動の宣言と宣言のモデル、親は両方。"""
    from ._fb_pool import DERIVED

    def build(state, plan):
        from ._fb_core import Slot
        ledger = state.ledger
        declared = plan.declaration.perception.value.model
        body = _Prediction(target="belief_pool_model", about=(ledger.record(plan.d).id,),
                           basis=(ledger.record(plan.d).id, ledger.record(declared).id),
                           content=_Payload.json({"document": document}), contract=_MODEL_SOURCE)
        return Slot(contract=_MODEL_SOURCE, record=_record(state, body, _RefKind.PREDICTION, _Role.MODEL),
                    parents=_front(state.ledger, {plan.d, declared}))

    return Step(name=DERIVED, build=build)


def _origin_step(perception_slot):
    """knowledge_origin (感じる側の読み手の位置、K36 新しい決定 2)。モデルは最初の並びのモデル (`_fb_pool.initial_model`)。"""

    def build_origin(state, plan):
        from ._fb_core import Slot, mono_ns
        from ._fb_pool import initial_model
        model = initial_model(plan)
        # r は窓口がこの記録の成立を確かめた時の M の読み (§2-5-1 U2)。時刻なしだと F-a が文脈の
        # 境界と比べられない (chronology の unknown time)
        body = _Observed(route="fb", content=_Payload.json({"model": model}),
                         contract=_KNOWLEDGE_ORIGIN, received_ns=mono_ns(state.clock))
        return Slot(contract=_KNOWLEDGE_ORIGIN, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {plan.d, model}))

    return Step(name="origin", build=build_origin)


def _qgen_step(state, initial_slot):
    """最初の候補の生成の要求 Qgen (考える側)。読み手とモデルは最初の並びのもの (`_fb_pool.initial_pool`)。"""
    initial = initial_slot.value
    name = initial_slot.slot

    def build_qgen(state, plan):
        from ._fb_core import Slot
        from ._fb_pool import initial_pool
        first = initial_pool(state, plan)
        d, origin, model = plan.d, first.origin, first.model
        generator = next(x for x in state.registry.declarations
                         if x.kind == "generator" and x.ref == initial.generator.contract)
        # G4: basis はその生成器の版つき args 契約が決める。args の参照を持たない契約
        # (sui.f.args.empty) だけが basis 不要を明示する。それ以外は意味の不足として保留する。
        if generator.args_contract != _EMPTY_ARGS:
            if "initial:basis" not in plan.missing:
                plan.missing.append("initial:basis")
            return None
        try:   # 宣言した args 契約で実際の generator.args を検査する (F-a の構造検査、R11)
            _f._schema_check(generator.args_contract, initial.generator.args)
        except (_f.FInputError, _f.FSpecificationMissing):
            if "initial:args" not in plan.missing:
                plan.missing.append("initial:args")
            return None
        desc = _fb.Desc(
            work_id=_work_id(d, name, "candidate_generation", "initial:" + name),
            process=_fb.BootSlot(declaration=d, slot=initial.process_slot),
            trigger=frozenset({_fb.Trigger(point=d, slot=name)}),
            purpose="candidate_generation", stage_slot="initial:" + name, reader=origin,
            method=initial.generator.contract, output_contract=_c.CANDIDATE_GENERATION,
            args=_fb.CandidateArgs(model=model, generator_args=initial.generator.args, basis=()),
            input_points=frozenset({d, origin, model}),
            # Prediction のモデルは出来事の祖先に入らないので境界に直接含める (§6-9 H5)
            numerical_view=fixed_view(state, frozenset({origin, model})),
            allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=name),
                                   _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))
        plan.points["desc:qgen"] = desc
        ledger = state.ledger
        body = _Decided(inputs=(ledger.record(d).id, ledger.record(origin).id, ledger.record(model).id),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.CANDIDATE_REQUEST)
        return Slot(contract=_c.CANDIDATE_REQUEST, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, {d, origin, model}))

    def qgen_prepared(state, plan, cid):
        from ._fb_core import add_work
        from ._fb_think import open_plan
        add_work(state, _fb.Compute(request=cid, desc=plan.points["desc:qgen"]), plan.declaration.scope.value)
        open_plan(state, plan, initial_slot, cid)

    return Step(name="qgen", build=build_qgen, on_prepared=qgen_prepared)


class _Closure:
    """台帳を境界の祖先の閉包に限った読み手 (FReader の口)。境界の外の記録を像に混ぜない。"""

    def __init__(self, ledger, boundary):
        self._ledger = ledger
        self._points = ledger.ancestors(boundary)

    def entries(self):
        return tuple(e for e in self._ledger.entries() if e.cid in self._points)

    def entry(self, cid):
        if cid not in self._points:
            raise KeyError(cid)
        return self._ledger.entry(cid)

    def record(self, cid):
        return self._ledger.record(self.entry(cid).cid)

    def sealed_content(self, cid):
        return self._ledger.contents.get(self.entry(cid).seal)


def fixed_view(state, boundary) -> _fb.FixedView:
    """G4: 生成に実際に使う不変の読み手の像から F-a の既存の定義で reader_view_key を求め、
    registry_key も実際の宣言と実装の識別から求める (§2-5-1・F-a E-05)。"""
    from ._f_world import capture_reader, registry_view_key
    from .rate import RateBudget
    closure = _Closure(state.ledger, boundary)
    # 像を取るのに使う予算は読む記録の数だけ (計算の予算ではない)
    budget = RateBudget(_Fraction(1, 10**9), len(closure.entries()) + 1, 1, 1)
    image = capture_reader(closure, budget)
    return _fb.FixedView(boundary=boundary, reader_view_key=image.view_key,
                         registry_key=registry_view_key(state.registry))


def advance(state, plan, *, build=lambda step: True) -> None:
    """保存の義務を順に進める。前提がまだ無い所で止まる。I/O の失敗は準備を残して上げる。
    build(step) が偽のまだ作っていない記録の所で止まる (作った記録の保存は続ける)。"""
    from ._fb_core import save
    for step in plan.steps:
        if step.slot is None:
            if not build(step):
                return
            slot = step.build(state, plan)
            if slot is None:
                return
            # Publish: 記録を準備して固定し、同じ歩で仕事の行を置く。行の開始は要求の保存を
            # 確かめた後 (_fb_core.startable)。準備の CID は P の中の持ち手で、ほかの記録に埋めない。
            slot.prepared = state.ledger.prepare(slot.record, slot.parents)
            step.slot = slot
            if step.on_prepared is not None:
                step.on_prepared(state, plan, slot.prepared.cid)
        if step.slot.entry is None:
            save(state, step.slot)
        plan.points[step.name] = step.slot.entry.cid

