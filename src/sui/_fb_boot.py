"""Boot から起動の計画を作る (紙 F-b §2-4-0・§2-5-9・§2-5-10・§6-5 G1〜G5、段 1)。

保存した boot_declaration d から、測る口の実適用 (route_config) → 続けて測る要求 k、
initial があれば knowledge_origin → 最初の候補の生成の要求 Qgen を、1 点ずつ保存する。
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
from .f_contracts import KNOWLEDGE_ORIGIN as _KNOWLEDGE_ORIGIN, ROUTE_CONFIG as _ROUTE_CONFIG
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Record as _Record, Role as _Role

_EMPTY_ARGS = _ContractRef("sui.f.args.empty", "1")


@_dataclass
class Step:
    """計画の 1 記録。slot は build が返した時に固定する。"""
    name: str
    build: object                # (state, plan) -> Slot | None (None は前提がまだ保存されていない)
    on_prepared: object = None   # (state, plan, cid) -> None: Publish と同じ歩で仕事の行を置く
    slot: object = None
    uses: object = None          # (state, plan) -> 使用の出発点の列 | None: 新しい使用の門 (段 3、§6-10 G6)


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
    initial = declaration.initial
    positions = [declaration.scope.slot, declaration.environment.slot,
                 *(name for r in declaration.routes
                   for name in (r.slot, r.value.allocation.slot, r.value.process_slot)),
                 *((initial.slot, initial.value.allocation.slot, initial.value.process_slot,
                    initial.value.reader_slot, initial.value.derivation.slot) if initial is not None else ())]
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
                and _declared(state, "measurement", config.loss_contract)):
            plan.missing.append(f"route:{route_slot.slot}:missing_contract")
            continue
        state.allocations[_fb.BootSlot(declaration=d, slot=route.allocation.slot)] = route.allocation.value.amount
        plan.steps += _route_steps(route_slot)

    if declaration.initial is not None:
        initial_slot = declaration.initial
        initial = initial_slot.value
        if initial_slot.contract != _c.INITIAL_PROCESS:
            plan.missing.append("initial:contract")
        elif not allocation_ok(initial.allocation):
            plan.missing.append("initial:allocation")
        elif not _declared(state, "generator", initial.generator.contract):
            plan.missing.append("initial:missing_contract")
        else:
            try:
                state.ledger.entry(initial.model)
            except KeyError:
                plan.missing.append("initial:model")
            else:
                state.allocations[_fb.BootSlot(declaration=d, slot=initial.allocation.slot)] = \
                    initial.allocation.value.amount
                plan.steps += _initial_steps(state, initial_slot)
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
    """Ev: 派生物 (Prediction など) を直接の出来事の親にせず、その出来事の来歴へ展開する (§2-5-1・G4)。
    派生物は実の親と宣言した basis の両方から出来事を得る (紙 :2059「A-03 に従い、その用途で必要な basis と
    実親から得る出来事」。段 3 の R* の basis の T で、実の親だけの展開が欠けていたと分かった)。"""
    out, pending, seen = set(), list(points), set()
    while pending:
        cid = pending.pop()
        if cid in seen:
            continue
        seen.add(cid)
        entry = ledger.entry(cid)
        if entry.is_event:
            out.add(entry.cid)
        else:
            pending.extend(entry.parents)
            for ref in getattr(ledger.record(cid).body, "basis", ()):
                pending.extend(e.cid for e in ledger.entries_of(ref))
    return frozenset(out)


def _front(ledger, points) -> frozenset:
    """Front(Ev(...)): 出来事へ展開してから、ほかの祖先になっているものを除く。"""
    return ledger.maximal(_events(ledger, points))


def _record(state, body, kind, writer):
    from ._fb_core import PRODUCER
    return _Record(id=state.ids.new(kind), at=state.clock.now(), writer=writer,
                   producer=PRODUCER, body=body, schema=3)


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
        # 照合される (結びつきの route の照合、R01・R03)。その境目で M を読み、工場がその操作を捕捉する
        # (RouteApplicationObservation の元。保存した route_config の復号から作らない、正本 v1.3.7)
        applied_ns = mono_ns(state.clock)
        state.routes[epoch] = (route.config, applied_ns)
        plan.applied[name] = applied_ns
        reading = _f.ClockReading(run=state.clock.run, time_ns=applied_ns)
        ledger = state.ledger
        from .f_update2 import RouteCapture
        state.route_applications[plan.d, name] = RouteCapture(
            boot=plan.d, route_slot=name, applied_config=route.config, reading=reading, clock_source=source,
            evidence_inputs=((plan.d, ledger.record(plan.d).id), (source, ledger.record(source).id)), execution=None)
        # 既存の契約の DTO で符号化する (effective_from は ClockReading | Unavailable の和型、F-a A:29)
        from .f_entry import RouteApplied
        content = _f._encode(RouteApplied(config=route.config, effective_from=reading, execution=None,
                                          evidence=(ledger.record(plan.d).id, ledger.record(source).id)))
        body = _Observed(route="fb", content=_Payload.json(content), contract=_ROUTE_CONFIG,
                         received_ns=applied_ns)
        return Slot(contract=_ROUTE_CONFIG, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=frozenset({plan.d, source}))

    def route_prepared(state, plan, cid):
        # 同じ操作から作った route_config の Point を控えに結ぶ (publication)
        state.route_applications[plan.d, name].publication = cid

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
                                 start_reason="bootstrap"),
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
        desc = plan.points["desc:" + name]
        add_work(state, _fb.MeasureSegment(request=cid, desc=desc), plan.declaration.scope.value)
        # この測る実行が使う route の実適用の操作 (EW.route_operation。K.args.route や B.route から推測しない)
        state.works[desc.work_id].route_operation = state.route_applications[plan.d, name].operation

    return [Step(name="route_config:" + name, build=build_route_config, on_prepared=route_prepared),
            Step(name="k:" + name, build=build_k, on_prepared=k_prepared)]


def _initial_steps(state, initial_slot):
    initial = initial_slot.value
    name = initial_slot.slot

    def build_origin(state, plan):
        from ._fb_core import Slot, mono_ns
        # r は窓口がこの記録の成立を確かめた時の M の読み (§2-5-1 U2)。時刻なしだと F-a が文脈の
        # 境界と比べられない (chronology の unknown time)
        body = _Observed(route="fb", content=_Payload.json({"model": initial.model}),
                         contract=_KNOWLEDGE_ORIGIN, received_ns=mono_ns(state.clock))
        return Slot(contract=_KNOWLEDGE_ORIGIN, record=_record(state, body, _RefKind.OBSERVATION, _Role.MEMBRANE),
                    parents=_front(state.ledger, {plan.d, initial.model}))

    def build_qgen(state, plan):
        from ._fb_core import Slot
        d, origin = plan.d, plan.points["origin"]
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
            args=_fb.CandidateArgs(model=initial.model, generator_args=initial.generator.args, basis=()),
            input_points=frozenset({d, origin, initial.model}),
            # Prediction のモデルは出来事の祖先に入らないので境界に直接含める (§6-9 H5)
            numerical_view=fixed_view(state, frozenset({origin, initial.model})),
            allocation=_fb.BootSlot(declaration=d, slot=initial.allocation.slot),
            permissions=frozenset({_fb.BootSlot(declaration=d, slot=name),
                                   _fb.BootSlot(declaration=d, slot=initial.allocation.slot)}))
        plan.points["desc:qgen"] = desc
        ledger = state.ledger
        body = _Decided(inputs=(ledger.record(d).id, ledger.record(origin).id, ledger.record(initial.model).id),
                        content=_Payload.json({"desc": _encode(desc)}), contract=_c.CANDIDATE_REQUEST)
        return Slot(contract=_c.CANDIDATE_REQUEST, record=_record(state, body, _RefKind.DECISION, _Role.MODEL),
                    parents=_front(ledger, {d, origin, initial.model}))

    def qgen_prepared(state, plan, cid):
        from ._fb_core import add_work
        from ._fb_think import open_plan
        add_work(state, _fb.Compute(request=cid, desc=plan.points["desc:qgen"]), plan.declaration.scope.value)
        open_plan(state, plan, initial_slot, cid)

    return [Step(name="origin", build=build_origin),
            Step(name="qgen", build=build_qgen, on_prepared=qgen_prepared)]


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

