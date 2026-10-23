"""F-b の窓口とホストの本体 (段 1)。公開の形は fb.py、紙は F-b v0.25 §2-4・§2-5・§6。

H (ホスト) と P (預かり) は FThreadHost が持ち、窓口 FWindow は作り直しで捨ててよい
索引だけを持つ (§2-4-1)。受付は 1 封筒 → 記録の slot の計画で、書き込みをしない。
保存は settle の中で 1 点ずつ: 準備 (PreparedEntry を固定) → 書き込み。応答の喪失の後は
同じ準備で書き直す (§2-4-2)。
"""

from collections.abc import Mapping as _Mapping
from types import MappingProxyType as _MappingProxyType
from dataclasses import dataclass as _dataclass, field as _field, fields as _fields,     is_dataclass as _is_dataclass
from threading import RLock as _RLock

from . import fb as _fb
from . import fb_contracts as _c
from ._fb_shape import check_event as _check_event
from ._fb_wire import dumps as _dumps, encode as _encode
from .contracts import ContractRef as _ContractRef
from .ids import RandomIds as _RandomIds, RefKind as _RefKind
from .ledger import Entry as _Entry, PreparedEntry as _PreparedEntry
from .records import Observed as _Observed, Payload as _Payload, Producer as _Producer, \
    Record as _Record, Role as _Role
from .s4_contracts import BOOT as _S4_BOOT

PRODUCER = _Producer(component="sui.fb", code_version="1", state=None)


@_dataclass
class Slot:
    """1 つの記録の計画。record は受付で固定 (s = Record.at)、prepared は最初の準備で固定。"""
    contract: object
    record: _Record
    parents: frozenset
    prepared: _PreparedEntry | None = None
    entry: _Entry | None = None
    attempted: bool = False


@_dataclass
class Receipt:
    envelope: _fb.Envelope
    slots: list = _field(default_factory=list)
    index: int = 0   # 受付の順 (同じ論理の報告の代表を選ぶ、R18)


class State:
    """H と P。ホストが持ち、窓口を作り直しても残る。"""

    def __init__(self, *, ledger, clock, workers, registry, launcher):
        self.lock = _RLock()
        self.ledger = ledger
        self.clock = clock
        self.workers = workers
        self.registry = registry
        self.launcher = launcher
        self.ids = _RandomIds()
        self.queue: list = []          # H: Post 済み・Accept 前の封筒
        self.number = 0                # H: 次の封筒の番号の元
        self.receipts: dict = {}       # P.receipts: 番号 → Receipt
        self.order: list = []          # 受付の順
        self.works: dict = {}          # P.work: WorkId → WorkRow (挿入の順を保つ)
        self.acquisitions: list = []   # EA: 実取得の観測 (段 3)
        # 工場の捕捉 (正本 v1.3.7 transport_types): (Boot の Point, route の slot) → route の実適用の控え、監視の控えの列
        self.route_applications: dict = {}
        self.host_monitors: list = []
        self.capacity: dict = {}       # Boot の宣言の Point → 容量 (QuantityValue)
        self.allocations: dict = {}    # BootSlot (宣言の Point と割当の slot) → QuantityValue (R15)
        self.plans: dict = {}          # P.units: Boot の封筒の番号 → 起動の計画 (_fb_boot.BootPlan)
        self.bindings: dict = {}       # P.units: 結びつきの論理の鍵 → B の Slot (§6-8 B2)
        self.binding_missing: dict = {}  # 原報告の Point → 今の判断の不足 (PendingStatus の材料)
        self.work_conflicts: list = []   # 同じ WorkId を名乗った違う仕事 (上書きしない、R08)
        self.routes: dict = {}         # 実適用した受け口: route_epoch → (RouteConfig, M の読み) (G2・R01)
        self.thinking: dict = {}       # P.units: Qgen の WorkId → 考える過程の計画 (_fb_think.ThinkPlan)
        self.clock_sources: dict = {}  # P.units: 時計の知らせの Point → 発行する sui.clock.source/1 の Slot (K1)
        self.updates: dict = {}        # P.units: Boot の封筒の番号 → 信念の更新の計画 (_fb_update.UpdatePlan、§6-10)
        # 門の重い計算 (閉包・索引・配送の比較) をロックの外で行うための版 (紙 G6 の最後の行、LOCK-R5):
        # delivery_version は Post・Accept・口の報告の追加で、ledger_version は台帳への保存で進む。gate_cache は
        # settle の前にロックの外で計算した結果で、版が合う時だけ使う (条件が変われば古い許可を使わず計算し直す)
        self.delivery_version = 0
        self.ledger_version = 0
        self.gate_cache = None
        self.gate_stale = False   # ロックの中の門が版の不一致で使用を保留した (settle が外で計算し直してもう一度通す)


def mono_ns(clock) -> int:
    reader = getattr(clock, "mono_ns", None)
    return reader() if reader is not None else clock.now().mono_ns


# 既存の契約の原報告は既存の外側の route を保つ (§2-5-1「既存契約の route を新しい共通値に一括変更しない」)。
# F-a の起動の不変は route='membrane' を要る (_f_invariants の 'BOOT' の literals)
_EXISTING_ROUTE = {_S4_BOOT: "membrane"}


def _observed(state, contract, content, received_ns, at):
    body = _Observed(route=_EXISTING_ROUTE.get(contract, "fb"), content=_Payload.json(content), contract=contract,
                     caused_by=None, source_id=None, source_time_ns=None, received_ns=received_ns)
    return _Record(id=state.ids.new(_RefKind.OBSERVATION), at=at, writer=_Role.MEMBRANE,
                   producer=PRODUCER, body=body, schema=3)


def _raw_slots(state, event, r, at) -> list:
    """封筒が作る原報告の slot (§2-5-9・§2-5-10)。親はどれも空。"""
    if isinstance(event, _fb.Boot):
        pairs = ((_S4_BOOT, {}), (_c.BOOT_DECLARATION, _encode(event.declaration)))
    elif isinstance(event, _fb.ClockDeclared):
        pairs = ((_c.CLOCK_NOTICE, event.declaration.as_json()),)   # §6-9 K1
    elif isinstance(event, _fb.Received):
        pairs = ((_c.RECEIVED, _encode(event)),)
    elif isinstance(event, _fb.SegmentReport):
        pairs = ((_c.SEGMENT_REPORT, _encode(event)),)
    elif isinstance(event, _fb.WorkFinished):
        pairs = ((_c.WORK_REPORT, _encode(event)),)
    else:
        pairs = ((_c.DRAW_REPORT, _encode(event)),)
    return [Slot(contract=contract, record=_observed(state, contract, content, r, at), parents=frozenset())
            for contract, content in pairs]


def freeze(value):
    """外から来た値の凍った写し。dict は読み取り専用の写しに、list は tuple にする。ホストの中の値は
    外と可変の入れ物を共有せず、外へ渡す値 (drain・仕事) も中を変えられない (R02・R13)。"""
    if _is_dataclass(value) and not isinstance(value, type):
        return type(value)(**{f.name: freeze(getattr(value, f.name)) for f in _fields(value) if f.init})
    if isinstance(value, _Mapping):
        return _MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(freeze(item) for item in value)
    return value


def wire(value) -> bytes:
    """中身の照合は正準 JSON の bytes で。Python の == は True と 1 を同じにする (R14)。"""
    if isinstance(value, _fb.Envelope):
        return _dumps([value.number, value.received_ns, type(value.event).__name__,
                       _dumps(_event_value(value.event)).decode("utf-8")])
    return _dumps(_encode(value))


def _event_value(event):
    if isinstance(event, _fb.ClockDeclared):
        return event.declaration.as_json()
    return _encode(event)


def accept(state, envelope) -> None:
    """Accept: 全欄を比べ、受信の記録の計画と受付の責務を P.receipts に一度に置く (§2-4-2)。"""
    if not isinstance(envelope, _fb.Envelope) or type(envelope.number) is not int \
            or type(envelope.received_ns) is not int:
        raise _fb.FbInputError(reason="shape", field="/envelope")
    _check_event(envelope.event)
    # 呼出し元が持つ可変の JSON (claims・args など) を受付の時点の値で写す。後から変えられても
    # 保存・計画・同じ番号の照合は受け付けた中身で行う (R02)
    envelope = freeze(envelope)
    with state.lock:
        known = state.receipts.get(envelope.number)
        if known is not None:
            if wire(known.envelope) != wire(envelope):
                raise _fb.FbHostFault(f"envelope {envelope.number}: different content or r for the same number")
            return
        # H が Post で押した原本があれば、最初の受付もその原本と同じ bytes でなければならない (R21)
        if any(wire(queued) != wire(envelope) for queued in state.queue if queued.number == envelope.number):
            raise _fb.FbHostFault(f"envelope {envelope.number}: different content or r from the posted envelope")
        at = state.clock.now()
        if at.run != state.clock.run:
            raise _fb.FbHostFault("host clock run changed")
        if envelope.received_ns > at.mono_ns:
            raise _fb.FbHostFault(f"envelope {envelope.number}: r={envelope.received_ns} after s={at.mono_ns}")
        receipt = Receipt(envelope=envelope, slots=_raw_slots(state, envelope.event, envelope.received_ns, at),
                          index=len(state.order))
        state.receipts[envelope.number] = receipt
        state.order.append(envelope.number)
        state.queue = [queued for queued in state.queue if queued.number != envelope.number]
        state.delivery_version += 1


def save(state, slot) -> None:
    """PrepareOne → PutBody/AddEntry/ConfirmWrite。I/O の失敗は準備を残して上げる。"""
    if slot.entry is not None:
        return
    if slot.prepared is None:
        slot.prepared = state.ledger.prepare(slot.record, slot.parents)
    slot.attempted = True
    # 書き込みを試みたら台帳の版を進める (失敗しても進める: 確認が失われた書き込みは台帳に入っていることがあり、
    # 前の版で作った閉包や Ref の索引を使い続けると、入ったはずの記録が「無い」ことになる)
    state.ledger_version += 1
    slot.entry = state.ledger.write(slot.prepared)


def settle(state) -> None:
    """原報告を 1 点ずつ保存し、保存した Boot から起動の計画を置いて進め、考える過程を進める。
    Need はロックの外で固定した入力で呼ぶ (§6-9 H10: 差し替えられる方法が戻らない時に Post を止めない)。"""
    from . import _fb_bind, _fb_boot, _fb_think, _fb_update
    # 門の重い計算 (閉包・索引・配送の比較) はロックの外で固定した入力から (G6 の最後の行、LOCK-R5・R6)。
    # ロックの中の門は版が合う時だけ結果を使い、版が違えば (途中で書き込みか配送が進んだ) その使用を保留して
    # stale を立てる。保留があれば、ロックの外で計算し直してから同じ settle でもう一度通す (古い許可は使わない)
    try:
        for _attempt in range(4):
            _fb_update.precompute(state)
            with state.lock:
                state.gate_stale = False
                for number in list(state.order):
                    receipt = state.receipts[number]
                    for slot in receipt.slots:
                        save(state, slot)
                    if isinstance(receipt.envelope.event, _fb.Boot) and number not in state.plans:
                        declaration = next(s for s in receipt.slots if s.contract == _c.BOOT_DECLARATION)
                        state.plans[number] = _fb_boot.plan_boot(state, receipt.envelope.event.declaration,
                                                                 declaration.entry.cid)
                _fb_boot.clock_sources(state)
                for plan in state.plans.values():
                    _fb_boot.advance(state, plan)
                _fb_think.advance(state)
                _fb_bind.bind(state)
                _fb_update.advance(state)
                stale = state.gate_stale
            if not stale:
                break
    finally:
        # この settle で置いた行・計画の門の材料を外で先に計算しておく (次の settle の前の drain・開始・入場が、
        # ロックの中で閉包を計算せずに済むように)。保存の故障で途中から抜けた時も同じ (読むだけ)
        try:
            _fb_update.precompute(state)
        except Exception:   # noqa: BLE001 — 門の材料の先読みの失敗は、その歩の門が wait/stale で受ける
            pass
        # 保存の故障で途中から例外を上げる時も、置いた行の Need は求めておく (行と義務は残る)
        with state.lock:
            pending = [row for row in state.works.values() if row.retry]
        for row in pending:
            resolve_need(state, row)


@_dataclass(frozen=True)
class PlannedDesc:
    work_id: str
    purpose: str


@_dataclass(frozen=True)
class PlannedWork:
    """要求がまだ未解決の仕事の行 (紙 INV-5「Publish の時は全後続の仕事の行を同時に置き、行の計画の中には
    未解決の PlanRef を許すが実在の Point として使わない」)。request は預かりの識別 Unsaved で、開始できない。
    要求を準備した時に add_work が同じ行を本物の仕事に解決する (review FB2-R04)。"""
    desc: PlannedDesc
    request: object   # fb.Unsaved


def plan_work(state, work_id, purpose, scope) -> None:
    """Publish と同じ歩で、要求が未解決の後続の仕事の行を置く (PR → D、DF → Ee)。"""
    if work_id not in state.works:
        state.works[work_id] = WorkRow(work=PlannedWork(desc=PlannedDesc(work_id=work_id, purpose=purpose),
                                                        request=_fb.Unsaved(plan=work_id)), need=None, scope=scope)


def add_work(state, work, scope) -> None:
    """Publish と同じ歩で仕事の行を置き、Need を解決する (G5)。同じ WorkId に違う仕事が
    来たら上書きせず食い違いとして持つ (R08)。要求が未解決の行 (PlannedWork) は同じ行のまま解決する。"""
    known = state.works.get(work.desc.work_id)
    if known is not None and isinstance(known.work, PlannedWork) \
            and known.work.desc.purpose == work.desc.purpose:
        known.work, known.scope, known.retry = work, scope, True
        return
    if known is not None:
        if wire(known.work) != wire(work):
            state.work_conflicts.append(work)
        return
    # Need は settle の最後にロックの外で求める (§6-9 H10)。それまでは開始できない
    row = WorkRow(work=work, need=None, scope=scope, retry=True)
    state.works[work.desc.work_id] = row


def resolve_need(state, row) -> None:
    """Need は固定した Desc と資源範囲で、F-a の能力の呼出しの規約 (args/input/output の構造検査)
    を通して呼び、返値を行に持つ。解決できなければ need=None (開始できない・対象つきの missing)。
    既定値で埋めない。実装の一時の例外は行を消さずに持ち、次の settle で試し直す (R07)。
    ロックの外で呼ぶ (入力の Desc と資源範囲は不変)。結果の書き込みだけロックの下で。"""
    from . import f as _f
    work, scope = row.work, row.scope
    need, missing = None, None
    try:
        raw = _f._call_capability("method", scope.need.contract, args=scope.need.args,
                                  input={"work": _encode(work.desc), "scope": _encode(scope)},
                                  registry=state.registry)
        value = _fb.QuantityValue(contract=_ContractRef(name=raw["contract"]["name"],
                                                        version=raw["contract"]["version"]),
                                  value=raw["value"])
        if value.contract == scope.quantity_contract:
            need = value
        else:
            missing = "need:quantity_contract"
    except (_f.FSpecificationMissing, _f.FIncomplete, _f.FInputError) as exc:
        missing = f"need:{exc.reason}"
    except Exception as exc:   # 実装の一時の失敗。行と義務は残し、settle で試し直す
        with state.lock:
            row.need, row.missing, row.retry = None, f"need:error:{type(exc).__name__}", True
        return
    with state.lock:
        row.need, row.missing, row.retry = need, missing, False


def _slot_status(slot):
    basis = _fb.StatusBasis(view=None, basis=())
    if slot.entry is not None:
        return _fb.SlotStatus(contract=slot.contract, state="saved", target=slot.entry.cid,
                              evidence=_fb.StatusBasis(view=None, basis=(slot.entry.cid,)))
    target = _fb.Unsaved(plan=str(slot.record.id))
    state = "awaiting_confirmation" if slot.attempted else "accepted"
    return _fb.SlotStatus(contract=slot.contract, state=state, target=target, evidence=basis)


def status(state):
    with state.lock:
        receipts = []
        for envelope in state.queue:
            receipts.append(_fb.ReceiptStatus(envelope=envelope.number, received_ns=envelope.received_ns,
                                              state="received", slots=()))
        for number in state.order:
            receipt = state.receipts[number]
            receipts.append(_fb.ReceiptStatus(
                envelope=number, received_ns=receipt.envelope.received_ns, state="accepted",
                slots=tuple(_slot_status(slot) for slot in receipt.slots)))
        from . import _fb_think, _fb_update
        return _fb.FStatus(receipts=tuple(receipts), works=work_statuses(state),
                           readings=_fb_think.reading_statuses(state) + _fb_update.reading_statuses(state),
                           pending=pending_statuses(state) + _fb_update.pending_statuses(state),
                           segments=segment_statuses(state),
                           purposes=_fb_think.purpose_statuses(state) + _fb_update.purpose_statuses(state))


def pending_statuses(state) -> tuple:
    """意味 4: 起動の計画・仕事の行・結びつきの、対象つきの不足と食い違い (G5・§6-8)。"""
    def item(kind, target, contract, reason):
        basis = (target,) if isinstance(target, str) else ()
        return _fb.PendingStatus(kind=kind, target=target, contract=contract, reason=reason,
                                 evidence=_fb.StatusBasis(view=None, basis=basis))
    out = []
    for plan in state.plans.values():
        for reason in plan.missing:
            kind = "awaiting_evidence" if reason == "initial:model" else "missing_contract"
            out.append(item(kind, plan.d, _c.BOOT_DECLARATION, reason))
    for row in state.works.values():
        if row.missing is not None:
            out.append(item("missing_contract", row.work.request, None, row.missing))
    for report, hold in state.binding_missing.items():
        out.append(item(hold.kind, report, _c.SEGMENT_BINDING, hold.reason))
    for work in state.work_conflicts:
        out.append(item("conflict", work.request, None, f"work_id:{work.desc.work_id}"))
    from ._fb_think import conflicts
    for plan in state.thinking.values():
        # 食い違いは印でなく、その都度、保存済みの報告から導く (FB2-R01-R2)。保存の確認待ちを含む食い違いは
        # 未確認 (M1: 確認できない時は保存していないとも成功したとも言わない、FB2-R01-R3)
        confirmed = conflicts(state, plan)
        for purpose in confirmed:
            out.append(item("conflict", plan.qgen, None, "conflict:" + purpose))
        for purpose in conflicts(state, plan, unconfirmed=True):
            if purpose not in confirmed:
                out.append(item("unchecked", plan.qgen, None, "conflict:unconfirmed:" + purpose))
        for reason in plan.missing:
            if reason in ("eq:method", "eq:preferences", "cg:method_semantics", "context:clock_contract"):
                kind = "missing_contract"
            else:
                kind = "awaiting_evidence"
            out.append(item(kind, plan.qgen, None, reason))
    return tuple(out)


_CELL_TAGS = {"MeasurementFrame": ("frame", "measurement_interval"), "Gap": ("gap", "interval"),
              "MeasurementUnavailable": ("measurement_unavailable", "requested_interval"),
              "CoverageClaim": ("claim", "interval"), "CoverageUnproved": ("coverage_unproved", "interval")}


def segment_statuses(state) -> tuple:
    """意味 5。測る仕事の口 (FWorkContext.post) から来た報告だけを、その仕事の区間に数える。
    同じ WorkId を名乗る別の道の報告は原報告のまま (結びつけない)。ended は ended の報告が
    保存されたことで、実際の停止ではない。セルは報告の有限の区間ごと、無報告を 0 や Gap にしない。"""
    out = []
    for row in state.works.values():
        work = row.work
        if not isinstance(work, _fb.MeasureSegment):
            continue
        ended, cells, basis = False, {}, []
        for number, _r in row.reports:
            receipt = state.receipts.get(number)
            if receipt is None or not receipt.slots:
                continue
            event, slot = receipt.envelope.event, receipt.slots[0]
            if not isinstance(event, _fb.SegmentReport) or event.segment != work.request:
                continue
            held = slot.entry.cid if slot.entry is not None else _fb.Unsaved(plan=str(slot.record.id))
            item = event.item
            if isinstance(item, _fb.SegmentBoundary):
                if item.kind == "ended" and item.work == work.desc.work_id and slot.entry is not None:
                    ended = True
                    basis.append(held)
                continue
            tag = _CELL_TAGS.get(type(item).__name__)
            if tag is None:
                continue
            interval = getattr(item, tag[1])
            tags, held_list = cells.setdefault(_encode_key(interval), (interval, [], []))[1:]
            tags.append(tag[0])
            held_list.append(held)
        out.append(_fb.SegmentStatus(
            segment=work.request, ended=ended,
            cells=tuple(_fb.CellStatus(interval=interval, reports=tuple(tags), certified=False,
                                       evidence=_fb.StatusBasis(view=None, basis=tuple(held)))
                        for interval, tags, held in cells.values()),
            evidence=_fb.StatusBasis(view=None, basis=(work.request, *basis))))
    return tuple(out)


def _encode_key(value) -> bytes:
    from ._fb_wire import dumps
    return dumps(_encode(value))


def post(state, event) -> None:
    with state.lock:
        used = max([state.number, *state.receipts, *(e.number for e in state.queue)], default=0)
        state.number = used + 1
        # Post の時点で凍らせる: Accept の前に呼出し元が中身を変えても、受信の r と中身が対応する (R13)
        state.queue.append(_fb.Envelope(number=state.number, event=freeze(event), received_ns=mono_ns(state.clock)))
        state.delivery_version += 1


def _fits(state, row) -> bool:
    """Fit (B:840): 同じ割当の占有の和 + 必要量 ≤ 割当、全体の占有の和 + 必要量 ≤ 容量。"""
    slot = row.work.desc.allocation   # BootSlot: 宣言の Point と割当の slot の組で照合する (R15)
    capacity = state.capacity.get(slot.declaration)
    allocation = state.allocations.get(slot)
    if row.need is None or capacity is None or allocation is None:
        return False
    held = [r.held.value for r in state.works.values()
            if r.held is not None and r.work.desc.allocation.declaration == slot.declaration]
    same = [r.held.value for r in state.works.values()
            if r.held is not None and r.work.desc.allocation == slot]
    return sum(same) + row.need.value <= allocation.value and sum(held) + row.need.value <= capacity.value


def _saved(state, cid) -> bool:
    """台帳に点があるか (自分の書き込みの応答を失っても、置き場の側で確かめる)。"""
    try:
        state.ledger.entry(cid)
    except KeyError:
        return False
    return True


def startable(state, row) -> bool:
    """開始は要求の保存の後 (FB5-01)。占有と容量が合う時だけ。上の段の食い違いが見えている考える過程の
    仕事は開始しない (紙 :864)。"""
    from ._fb_think import blocked
    if isinstance(row.work, PlannedWork):
        return False   # 要求が未解決の行は開始できない
    return row.phase == "pending" and _saved(state, row.work.request) and _fits(state, row) \
        and not blocked(state, row, "開始")


def drain(state) -> tuple:
    """開始できる仕事の列挙。取り除かず、開始の札も占有も使わない。"""
    with state.lock:
        return tuple(row.work for row in state.works.values() if startable(state, row))


class ThreadLauncher:
    """本番の起動係: OS のスレッドで body を走らせる。start の成否で launched / not_started。"""

    def launch(self, work_id, body):
        import threading
        thread = threading.Thread(target=body, name=f"sui-fb-{work_id}", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            return "not_started"
        return "launched"


def run_until(host, done, timeout) -> bool:
    """受付・settle・仕事の開始・停止の観測を回す。timeout は合否の物差しではない (F8)。"""
    import time
    deadline = time.monotonic() + timeout
    state = host._state
    while True:
        with state.lock:
            queued = list(state.queue)
        for envelope in queued:
            host.window.accept(envelope)
        host.window.settle()
        start_works(state)
        if done(host.window.status()):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)


def start_works(state) -> None:
    """ClaimStart (占有を確保) → Launch。launched でも本体に入ったかは enter で別に決まる。
    not_started は開始待ちに戻す。unknown と例外は占有を持ったまま出し直さない (§2-4-2)。"""
    with state.lock:
        rows = []
        for row in state.works.values():
            if startable(state, row):   # 前の行の確保を含めた今の占有で照合する (R05)
                ctx = WorkContext(state, row)
                row.phase, row.held, row.claim = "starting", row.need, ctx
                rows.append((row, ctx))
    for row, ctx in rows:

        def body(row=row, ctx=ctx):
            with state.lock:
                if ctx.invoked:   # 同じ本体の 2 度目の呼出しは走らせない (R12)
                    return
                ctx.invoked = True
            try:
                state.workers.run(row.work, ctx)
            finally:
                with state.lock:
                    if ctx.entered:
                        # 開始札を取った本体の実際の終わり。ここで初めて占有を解放する
                        row.stopped, row.phase, row.held, row.claim = True, "stopped", None, None
                    elif row.claim is ctx and not row.ticket_used:
                        # 今の占有を持つ起動が入場せずに終わった: 開始していないので開始待ちに戻す
                        row.phase, row.held, row.claim = "pending", None, None
                    # ほかの起動の終わりは、今の占有の持ち主を変えない (R06・R12)

        try:
            result = state.launcher.launch(row.work.desc.work_id, body)
        except Exception:
            result = "unknown"
        if result not in ("launched", "not_started", "unknown"):
            result = "unknown"
        with state.lock:
            row.launches.append(result)
            if result == "not_started" and row.claim is ctx and not row.ticket_used and not row.stopped:
                row.phase, row.held, row.claim = "pending", None, None


def work_statuses(state) -> tuple:
    out = []
    for row in state.works.values():
        desc = row.work.desc
        out.append(_fb.WorkStatus(
            work_id=desc.work_id, request=row.work.request, purpose=desc.purpose, phase=row.phase,
            startable=startable(state, row), blocked_by=(), knowledge=row.knowledge,
            stop_confirmed=row.stopped, held=row.held,
            evidence=_fb.StatusBasis(view=None, basis=(row.work.request,))))
    return tuple(out)


# --- 仕事表 P.work (§2-4-1・§2-4-2) ---

@_dataclass
class WorkRow:
    """仕事表の 1 行。未開始は phase="pending" の見え方で、別の入れ物に移さない。
    実行の段 (phase) と結果の知識 (knowledge) は別の軸。占有 held は実際の停止を
    確かめるまで解放しない (Unknown・Ended は停止ではない)。"""
    work: object
    need: object                 # QuantityValue (Need の能力の返値)。None は未解決
    missing: str | None = None   # Need が解決できない時の対象つきの理由
    scope: object = None         # Need を求める資源範囲 (ResourceScope)
    retry: bool = False          # Need の実装の一時の失敗。settle で試し直す
    claim: object = None         # 今の占有を確保した起動の口 (WorkContext)
    phase: str = "pending"       # pending / starting / running / stopped
    knowledge: str = "none"
    ticket_used: bool = False
    launches: list = _field(default_factory=list)
    entered: int = 0
    entered_ns: int | None = None  # 最初の入場の M の読み (ホストの実際の観測、§6-8 B6)
    entries: list = _field(default_factory=list)   # 全部の入場の M の読み (EW.entered_ns、重複の入場も落とさない)
    execution: object = _field(default_factory=lambda: _mint_execution())   # 実行の識別 (工場が行ごとに発行)
    route_operation: object = None  # 測る実行が使った route の実適用の操作 (測らない仕事は None)
    stopped: bool = False
    held: object = None
    reports: list = _field(default_factory=list)   # (封筒の番号, r)
    issued: list = _field(default_factory=list)    # 生きた発行物 (保存しない)
    uses: list = _field(default_factory=list)      # (Point, M の読み)
    intervals: list = _field(default_factory=list)  # 実際に見張った区間


class WorkContext:
    """FWorkContext の実装。1 つの仕事の行に結んだ口。"""

    def __init__(self, state, row):
        self._state, self._row = state, row
        self.entered = False   # この口が開始札を取ったか
        self.invoked = False   # この口の本体が呼ばれたか

    def enter(self) -> bool:
        """開始の札を取れるのは、今の占有を確保した起動の口だけ (R20)。起動の後・入場の前に上の段の食い違いが
        見えたら入場させない (紙 :864、review FB2-R01)。入場の門 (G6-*-ENTER) の閉包と比較はロックの外で計算し、
        版が同じ時だけ同じ歩で入場する (FB3-LOCK-R6)。入場していないので開始待ちに戻る。"""
        from ._fb_think import entrance
        from ._fb_update import gate_fresh
        state, row = self._state, self._row
        with state.lock:
            if row.ticket_used or row.claim is not self:
                return False
            try:
                found = entrance(state, row)
            except Exception:   # 要求がまだ読めない: 入場しない (開始待ちに戻る)
                return False
        starts, cheap = found if found is not None else (None, lambda: False)

        def decide(verdict):
            if row.ticket_used or row.claim is not self or cheap() or verdict != "open":
                return False
            row.ticket_used = self.entered = True
            row.entered += 1
            row.entered_ns = mono_ns(state.clock)
            row.entries.append(row.entered_ns)
            row.phase = "running"
            return True

        if not starts:
            with state.lock:
                return decide("open")
        return gate_fresh(state, starts, decide) is True

    def post(self, event, issued=None) -> None:
        state = self._state
        with state.lock:
            post(state, event)
            if not self.entered:
                return   # 開始の札を取っていない口の報告は原報告として残るだけで、仕事に結ばない (B6)
            envelope = state.queue[-1]
            self._row.reports.append((envelope.number, envelope.received_ns))
            state.delivery_version += 1   # この口の配送が増えた (窓口の配送集合の入力)
            if issued is not None:
                self._row.issued.append((envelope.number, issued))

    def read(self, point) -> bytes:
        """札を取った口だけが読める (§6-10 J8・K11)。取っていない口の読みは使用の観測にしない。"""
        state = self._state
        with state.lock:   # 占有の確認・本文の読み・使用の記録を 1 つの歩に (間に停止が入らない、R10-R2)
            if not self.entered or self._row.claim is not self:   # 停止した口も拒む (review FB3-R10)
                raise RuntimeError("read outside the entered work")
            record = state.ledger.record(point)
            self._row.uses.append((point, mono_ns(state.clock)))
        return record.body.content.data

    def monitored(self, interval) -> None:
        with self._state.lock:
            if not self.entered or self._row.claim is not self:
                raise RuntimeError("monitored outside the entered work")
            self._row.intervals.append(interval)

    def evidence(self):
        return evidence(self._state)

    def reader(self):
        """その仕事の Desc の numerical_view の境界と input_points の閉包だけの読み手 (§6-9 H5)。"""
        from ._fb_boot import _Closure
        desc = self._row.work.desc
        boundary = set(desc.input_points)
        if desc.numerical_view is not None:
            boundary |= desc.numerical_view.boundary
        if desc.purpose == "belief_update":
            boundary.add(self._row.work.request)   # Wu は Q* 自身も読む (Q* を Xnum に入れない、§6-10 J2)
        return _Closure(self._state.ledger, frozenset(boundary)) if boundary else None

    def prepared(self):
        """Ee の args.prepared と照合した Ep の生きた発行物。ほかの仕事は None (§6-9 H5)。"""
        from . import _fb_think
        with self._state.lock:
            return _fb_think.prepared_for(self._state, self._row)


def _mint_execution():
    from .f_update2 import _mint
    return _mint("execution")


def evidence(state):
    from . import f_update2 as _u
    from ._fb_boot import _clock_source
    with state.lock:
        executions, uses, intervals = [], [], []
        for row in state.works.values():
            wid = row.work.desc.work_id
            reports = []
            run = getattr(state.clock, "run", None)
            for number, r in row.reports:
                receipt = state.receipts.get(number)
                point = receipt.slots[0].entry.cid if receipt and receipt.slots and receipt.slots[0].entry else None
                reports.append(_u.ReportObservation(envelope=number, received_ns=r, point=point, run=run))
            request = row.work.request if isinstance(row.work.request, str) else None   # 未保存の要求は None
            executions.append(_u.ExecutionObservation(work_id=wid, launches=tuple(row.launches),
                entered=row.entered, stopped=row.stopped, reports=tuple(reports),
                entered_ns=tuple(row.entries), run=run, execution_occurrence=row.execution, request=request,
                route_operation=row.route_operation, clock_source=_clock_source(state)))
            uses += [_u.UseObservation(work_id=wid, point=p, used_ns=ns, run=run) for p, ns in row.uses]
            intervals += [_u.IntervalObservation(work_id=wid, interval=i) for i in row.intervals]
        return _u.TargetEvidence(executions=tuple(executions), uses=tuple(uses),
                                 intervals=tuple(intervals), acquisitions=tuple(state.acquisitions),
                                 route_applications=tuple(capture.observation() for capture
                                                          in state.route_applications.values()),
                                 host_monitors=tuple(capture.observation() for capture in state.host_monitors))
