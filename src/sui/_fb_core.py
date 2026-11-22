"""F-b の窓口とホストの本体 (段 1)。公開の形は fb.py、紙は F-b v0.25 §2-4・§2-5・§6。

H (ホスト) と P (預かり) は FThreadHost が持ち、窓口 FWindow は作り直しで捨ててよい
索引だけを持つ (§2-4-1)。受付は 1 封筒 → 記録の slot の計画で、書き込みをしない。
保存は settle の中で 1 点ずつ: 準備 (PreparedEntry を固定) → 書き込み。応答の喪失の後は
同じ準備で書き直す (§2-4-2)。
"""

from collections.abc import Mapping as _Mapping
from types import MappingProxyType as _MappingProxyType
from dataclasses import dataclass as _dataclass, field as _field, fields as _fields,     is_dataclass as _is_dataclass
from threading import RLock as _RLock, local as _local
import sqlite3 as _sqlite3

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


class _WatchedStore:
    """台帳とその本文の置き場を包む (§6-10 K16)。ホストが行った置き場の操作が OSError か sqlite3.Error を上げたら、
    その操作の名前と例外を State に残して、例外はそのまま上げる。回す役は、上がってきた例外がこの観測と同じ物かで
    「置き場の操作の失敗 (同じ準備のまま入り直せる)」を決める。例外の型だけでは決めない。"""
    __slots__ = ("_target", "_state", "_prefix")

    def __init__(self, target, state, prefix=""):
        self._target, self._state, self._prefix = target, state, prefix

    def __getattr__(self, name):
        value = getattr(self._target, name)
        if name == "contents":
            return _WatchedStore(value, self._state, "contents.")
        if not callable(value) or isinstance(value, type):
            return value
        state, operation = self._state, self._prefix + name

        def call(*args, **kwargs):
            try:
                return value(*args, **kwargs)
            except (OSError, _sqlite3.Error) as exc:
                state.store_failures.last = (operation, exc)
                raise
        return call


class State:
    """H と P。ホストが持ち、窓口を作り直しても残る。"""

    def __init__(self, *, ledger, clock, workers, registry, launcher, sources=None, actors=None):
        self.lock = _RLock()
        self.sources = dict(sources or {})   # 口の源: route_epoch → FSource (K23。外から差す部品)
        self.actors = dict(actors or {})     # 環境の相手: 名前 → FActor (K36。外から差す部品)
        self.inflight: dict = {}       # route_epoch → 源を読みに行っている取りに行きの before の M の読み (K36 決定 12 の順)
        self.cursors: dict = {}        # route_epoch → 源の次に取り出す番号 (この run の中、0 から。taken の時だけ進む)
        self.samples: dict = {}        # route_epoch → 次の取得の操作の番号 (この run の中、0 から。公開まで進んだ取得の数、K25)
        self.raw_ids: dict = {}        # 封筒の番号 → 取得の前に用意した原文の名札 (Record.id、K25 (d))。受付で使って外す
        self.acquired: dict = {}       # 家の人が acquire で作った取りに行きの Frame の封筒: 番号 → 正準 bytes (Z55。受付の後も持つ)
        self.source_lock = _RLock()    # 源の読みを 1 つずつにする (受付の鍵とは別。源を読む間も受付は止まらない)
        self.ledger = _WatchedStore(ledger, self)
        # 置き場の操作の失敗の観測 (操作の名前, 例外)。呼び出したスレッドごとに持つ: 回す役が見るのは自分の呼び出しの
        # 所で観測した失敗だけで、仕事の口 (別のスレッド) の失敗では変わらない (K16 (3)(a))
        self.store_failures = _local()
        self.halted = None             # 止まった理由の Interruption (K16 (3)(c)、紙 Z42)。None は動いている
        self.interruptions: list = []  # 回す役まで上がった中断 (Interruption、同じプロセスの中だけ)
        self.round_clean = True        # 前の周が中断なしで通った (続けて同じ中断をまとめる境目)
        self.rejected: set = set()     # 形がおかしくて断った封筒の番号 (K17。記録も預かりも無い)
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
        self.capacity: dict = {}       # Boot の宣言の Point → 容量 (QuantityValue)
        self.allocations: dict = {}    # BootSlot (宣言の Point と割当の slot) → QuantityValue (R15)
        self.plans: dict = {}          # P.units: Boot の封筒の番号 → 起動の計画 (_fb_boot.BootPlan)
        self.bindings: dict = {}       # P.units: 結びつきの論理の鍵 → B の Slot (§6-8 B2)
        self.binding_missing: dict = {}  # 原報告の Point → 今の判断の不足 (PendingStatus の材料)
        self.work_conflicts: list = []   # 同じ WorkId を名乗った違う仕事 (上書きしない、R08)
        self.routes: dict = {}         # 実適用した受け口: route_epoch → (RouteConfig, M の読み) (G2・R01)
        self.thinking: dict = {}       # P.units: Qgen の WorkId → 考える過程の計画 (_fb_think.ThinkPlan)
        self.updates: dict = {}        # P.units: Boot の封筒の番号 → 信念の更新の計画 (_fb_update.UpdatePlan)
        self.clock_sources: dict = {}  # P.units: 時計の知らせの Point → 発行する sui.clock.source/1 の Slot (K1)
        self.acting: dict = {}         # P.units: Boot の封筒の番号 → 引受けと一歩の計画 (_fb_act.ActPlan、K36)
        self.handed: dict = {}         # Boot の Point → 評価に渡した根の境界 (採用の系列の位置、戻さない。K36-c ③ (a))
        self.admitted: dict = {}       # Boot の Point → 入場させた評価の活動の数 (活動の識別の番号、K36-c-a ④ (c))
        self.additions: list = []      # 候補を足した決定: (起動の宣言の Point, 足した決定の Point) の列 (K37。並びは記録から解く)
        self.initial_pools: dict = {}  # 起動の宣言の Point → 最初の並び (_fb_pool.Pool、不変の値。K37)


def mono_ns(clock) -> int:
    reader = getattr(clock, "mono_ns", None)
    return reader() if reader is not None else clock.now().mono_ns


# 既存の契約の原報告は既存の外側の route を保つ (§2-5-1「既存契約の route を新しい共通値に一括変更しない」)。
# F-a の起動の不変は route='membrane' を要る (_f_invariants の 'BOOT' の literals)
_EXISTING_ROUTE = {_S4_BOOT: "membrane"}


def _observed(state, contract, content, received_ns, at, record_id=None):
    body = _Observed(route=_EXISTING_ROUTE.get(contract, "fb"), content=_Payload.json(content), contract=contract,
                     caused_by=None, source_id=None, source_time_ns=None, received_ns=received_ns)
    return _Record(id=record_id if record_id is not None else state.ids.new(_RefKind.OBSERVATION), at=at,
                   writer=_Role.MEMBRANE, producer=PRODUCER, body=body, schema=3)


def _raw_slots(state, event, r, at, record_id=None) -> list:
    """封筒が作る原報告の slot (§2-5-9・§2-5-10)。親はどれも空。record_id は取得の前にホストが用意した
    原文の名札 (K25 (d)。取得の原文 = Received の 1 slot だけに渡る)。"""
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
    elif isinstance(event, _fb.ExecutionReport):
        pairs = ((_c.EXECUTION_RESULT, _encode(event)),)   # 家の人が残す一歩の結果 (K36、Z55)
    else:
        pairs = ((_c.DRAW_REPORT, _encode(event)),)
    return [Slot(contract=contract, record=_observed(state, contract, content, r, at, record_id), parents=frozenset())
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


def require_running(state) -> None:
    """止まったホスト (K16 (3)(c)) は受付・settle・仕事の開始を進めない。"""
    if state.halted is not None:
        raise _fb.FHalted(f"the host halted at {state.halted.operation}: "
                          f"{state.halted.error_type}: {state.halted.message}")


# 係の口から受け付けない報告の中身 (紙 F-b K28 新しい決定 4・Z55 ②・Z56 ①)。取りに行きの Frame を帳面に入れるのは家の人の
# acquire だけで、区間の札 3 種は誰からも入らない (本体に出す者が居ない)。CoverageUnproved・境界・終わりの知らせは今のまま
_PRODUCER_CLOSED = (_fb.MeasurementFrame, _fb.CoverageClaim, _fb.Gap, _fb.MeasurementUnavailable)
_INTERVAL_EVIDENCE = (_fb.CoverageClaim, _fb.Gap, _fb.MeasurementUnavailable)


def _item(event):
    return event.item if isinstance(event, _fb.SegmentReport) else None


def accept(state, envelope) -> None:
    """Accept: 全欄を比べ、受信の記録の計画と受付の責務を P.receipts に一度に置く (§2-4-2)。取りに行きの Frame を運ぶ
    封筒は、家の人が acquire で作った封筒と同じ番号・同じ bytes の時だけ受け付ける (受信の列に残っているかは条件に
    しない = 受付済みの同じ封筒の再試行は今のまま成功)。区間の札 3 種を運ぶ封筒は受け付けない (K28 新しい決定 4)。"""
    require_running(state)
    if not isinstance(envelope, _fb.Envelope) or type(envelope.number) is not int \
            or type(envelope.received_ns) is not int:
        raise _fb.FbInputError(reason="shape", field="/envelope")
    # 呼出し元が持つ可変の JSON (claims・args など) を受付の時点の値で写し、その写しを確かめる。後から変えられても
    # 形の検査・保存・計画・同じ番号の照合は受け付けた同じ中身で行う (R02、K25-b ★ ④ = review K25-R4)
    envelope = freeze(envelope)
    if isinstance(envelope.event, _fb.ExecutionReport):
        # 一歩の結果のメモは家の人の perform が作った封筒と同じ番号・同じ bytes の時だけ (K36 決定 3・Z55)
        with state.lock:
            if state.acquired.get(envelope.number) != wire(envelope):
                raise _fb.FbInputError(reason="shape", field="/event")
    else:
        _check_event(envelope.event)
    item = _item(envelope.event)
    if isinstance(item, _INTERVAL_EVIDENCE):
        raise _fb.FbInputError(reason="shape", field="/event/item")
    with state.lock:
        if isinstance(item, _fb.MeasurementFrame) and state.acquired.get(envelope.number) != wire(envelope):
            raise _fb.FbInputError(reason="shape", field="/event/item")
        known = state.receipts.get(envelope.number)
        if known is not None:
            if wire(known.envelope) != wire(envelope):
                raise _fb.FbHostFault(f"envelope {envelope.number}: different content or r for the same number")
            return
        if envelope.number in state.rejected:
            # 断った封筒の番号は使ったまま (K17 (2))。形を直した中身でも、同じ番号では受け付けない
            raise _fb.FbHostFault(f"envelope {envelope.number}: the number of a rejected envelope is not reused")
        # H が Post で押した原本があれば、最初の受付もその原本と同じ bytes でなければならない (R21)
        if any(wire(queued) != wire(envelope) for queued in state.queue if queued.number == envelope.number):
            raise _fb.FbHostFault(f"envelope {envelope.number}: different content or r from the posted envelope")
        at = state.clock.now()
        if at.run != state.clock.run:
            raise _fb.FbHostFault("host clock run changed")
        if envelope.received_ns > at.mono_ns:
            raise _fb.FbHostFault(f"envelope {envelope.number}: r={envelope.received_ns} after s={at.mono_ns}")
        receipt = Receipt(envelope=envelope, slots=_raw_slots(state, envelope.event, envelope.received_ns, at,
                                                              state.raw_ids.get(envelope.number)),
                          index=len(state.order))
        state.receipts[envelope.number] = receipt
        state.order.append(envelope.number)
        state.raw_ids.pop(envelope.number, None)
        state.queue = [queued for queued in state.queue if queued.number != envelope.number]


def save(state, slot) -> None:
    """PrepareOne → PutBody/AddEntry/ConfirmWrite。I/O の失敗は準備を残して上げる。"""
    if slot.entry is not None:
        return
    if slot.prepared is None:
        slot.prepared = state.ledger.prepare(slot.record, slot.parents)
    slot.attempted = True
    slot.entry = state.ledger.write(slot.prepared)


def settle(state) -> None:
    """原報告を 1 点ずつ保存し、保存した Boot から起動の計画を置いて進め、考える過程を進める。
    Need はロックの外で固定した入力で呼ぶ (§6-9 H10: 差し替えられる方法が戻らない時に Post を止めない)。"""
    from . import _fb_act, _fb_bind, _fb_boot, _fb_think, _fb_update
    require_running(state)
    try:
        with state.lock:
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
            _fb_act.advance(state)
    finally:
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
        from . import _fb_act, _fb_think, _fb_update
        return _fb.FStatus(receipts=tuple(receipts), works=work_statuses(state),
                           readings=_fb_think.reading_statuses(state), pending=pending_statuses(state),
                           segments=segment_statuses(state), purposes=_fb_think.purpose_statuses(state),
                           updates=_fb_update.statuses(state), policies=_fb_act.policy_statuses(state),
                           intentions=_fb_act.intention_statuses(state),
                           executions=_fb_act.execution_statuses(state),
                           evaluations=_fb_think.evaluation_statuses(state),
                           thinking_materials=_fb_think.material_statuses(state))


def pending_statuses(state) -> tuple:
    """意味 4: 起動の計画・仕事の行・結びつきの、対象つきの不足と食い違い (G5・§6-8)。"""
    def item(kind, target, contract, reason):
        basis = (target,) if isinstance(target, str) else ()
        return _fb.PendingStatus(kind=kind, target=target, contract=contract, reason=reason,
                                 evidence=_fb.StatusBasis(view=None, basis=basis))
    out = []
    for plan in state.plans.values():
        for reason in plan.missing:
            kind = "awaiting_evidence" if reason == "perception:model" else "missing_contract"
            out.append(item(kind, plan.d, _c.BOOT_DECLARATION, reason))
    for row in state.works.values():
        if row.missing is not None:
            out.append(item("missing_contract", row.work.request, None, row.missing))
    for report, hold in state.binding_missing.items():
        out.append(item(hold.kind, report, _c.SEGMENT_BINDING, hold.reason))
    for work in state.work_conflicts:
        out.append(item("conflict", work.request, None, f"work_id:{work.desc.work_id}"))
    from . import _fb_update
    for plan in state.updates.values():
        # δ の計画の不足 (読めない方法・args・扱えない枝・返答の形・発行物の不一致、K28 の B1)。対象は起動の宣言
        for reason in plan.missing:
            kind = "conflict" if reason.startswith("update:") else "missing_contract"
            out.append(item(kind, plan.boot.d, _c.BOOT_DECLARATION, reason))
        # 食い違った原報告に頼る採用 A* と、それで止まった更新 (紙 Z3)。保存の確認待ちの配送を含む食い違いは未確認
        for ob in plan.obligations.values():
            # 更新の仕事 Wu の後着の両立しない終わりの報告 (K36-b (チ))。確認待ちを含むものは未確認
            if ob.desc is None or not _fb_update.terminal_clash(state, ob):
                continue
            target = ob.points.get("A") or ob.points.get("Q") or ob.report
            if _fb_update.terminal_clash(state, ob, unconfirmed=False):
                out.append(item("conflict", target, None, "update:terminal_conflict"))
            else:
                out.append(item("unchecked", target, None, "update:terminal_conflict:unconfirmed"))
        confirmed = _fb_update.conflicts(state, plan)
        for target in confirmed:
            out.append(item("conflict", target, None, "update:conflict"))
        for target in _fb_update.conflicts(state, plan, unconfirmed=True):
            if target not in confirmed:
                out.append(item("unchecked", target, None, "update:conflict:unconfirmed"))
    for act in state.acting.values():
        # 比べられない根・同じ根の別の選択 (K36 決定 7・K36-a (ウ))。到着順で勝者を作らない
        for selection, why in act.conflicts:
            out.append(item("conflict", selection, _c.INTENTION, "intention:" + why))
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


def _envelopes(state, events, r) -> list:
    """続きの番号と受信の r で封筒を組み立てる (共有の状態は変えない)。ロックの中で呼ぶ。
    Post の時点で凍らせる: Accept の前に呼出し元が中身を変えても、受信の r と中身が対応する (R13)。"""
    used = max([state.number, *state.receipts, *(e.number for e in state.queue)], default=0)
    return [_fb.Envelope(number=used + i, event=freeze(event), received_ns=r) for i, event in enumerate(events, 1)]


def _publish(state, envelopes) -> None:
    """組み上がった封筒を受信の列へ入れ、番号の管理の値を公開した最後の番号へ進める。ロックの中で呼ぶ。"""
    state.queue.extend(envelopes)
    state.number = envelopes[-1].number


def post(state, event) -> None:
    """Post (係の口 FWorkContext.post とホストの FThreadHost.post)。取りに行きの Frame と区間の札 3 種を運ぶ報告は
    TypeError で断り、何も公開しない (K28 新しい決定 4)。家の人の acquire はこの口を通らない。"""
    if isinstance(_item(event), _PRODUCER_CLOSED):
        raise TypeError("acquisition frames come only from the host's acquire; interval evidence is not accepted")
    if isinstance(event, _fb.ExecutionReport):
        # 一歩の結果のメモは家の人だけが書く (K36 決定 3・Z55)。係の口からもホストの post からも受け付けない
        raise _fb.FbInputError(reason="shape", field="/event")
    with state.lock:
        _publish(state, _envelopes(state, (event,), mono_ns(state.clock)))


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
    仕事は開始しない (紙 :864)。食い違った原報告に頼る更新の仕事も開始しない。"""
    if isinstance(row.work, PlannedWork):
        return False   # 要求が未解決の行は開始できない
    return row.phase == "pending" and _saved(state, row.work.request) and _fits(state, row) \
        and not _blocked(state, row)


def _blocked(state, row) -> bool:
    """開始・入場の門: 考える過程の仕事 (上の段の食い違い・きっかけの採用の依存の食い違い) と、更新の仕事 (依存の
    食い違い)。"""
    from . import _fb_act, _fb_think, _fb_update
    return _fb_think.blocked(state, row) or _fb_update.blocked(state, row) or _fb_act.blocked(state, row)


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


def _interrupt(state, kind, operation, exc):
    """回す役まで上がった中断を、ホストの観測として残す (K16 (4))。続けて同じ中断は 1 つにまとめる。"""
    try:
        now = mono_ns(state.clock)
    except Exception:
        now = None
    key = (kind, operation, type(exc).__name__, str(exc))
    with state.lock:
        last = state.interruptions[-1] if state.interruptions else None
        same = last is not None and (last.kind, last.operation, last.error_type, last.message) == key
        if same and not state.round_clean:
            item = _fb.Interruption(kind=kind, operation=operation, error_type=key[2], message=key[3],
                                    first_ns=last.first_ns, last_ns=now, count=last.count + 1)
            state.interruptions[-1] = item
        else:
            item = _fb.Interruption(kind=kind, operation=operation, error_type=key[2], message=key[3],
                                    first_ns=now, last_ns=now, count=1)
            state.interruptions.append(item)
        state.round_clean = False
    return item


def _reject(state, envelope, exc) -> None:
    """形のおかしい封筒を断る (§6-10 K17): 列から外し、番号を「断った」に置き、ホストの観測に 1 件残す。
    受信の記録も預かりも作らない。中身は持ち続けない。"""
    try:
        now = mono_ns(state.clock)
    except Exception:
        now = None
    number = getattr(envelope, "number", None)
    with state.lock:
        state.queue = [queued for queued in state.queue if queued is not envelope]
        state.rejected.add(number)
        state.interruptions.append(_fb.Interruption(
            kind="rejected", operation="accept", error_type=type(exc).__name__,
            message=f"envelope {number}: {exc}", first_ns=now, last_ns=now, count=1))


def keep_running(host, done, timeout) -> bool:
    """もう一度回す役 (§6-10 K16、紙 Z42)。run_until と同じ 1 周を回し、ホストが行った置き場の操作の失敗では同じ
    準備のまま次の周で入り直す。それ以外の例外ではホストを止めて FHalted を上げる (頭の中が信じられない時は回り続け
    ない)。期限は入口で 1 回だけ決める。done と status の例外は呼び出し側のものとしてそのまま上げる。"""
    import time
    deadline = time.monotonic() + timeout
    state = host._state

    def receive():
        with state.lock:
            queued = list(state.queue)
        for envelope in queued:
            try:
                host.window.accept(envelope)
            except _fb.FbInputError as exc:
                _reject(state, envelope, exc)   # 外側の形の誤りだけ断って、後ろの封筒へ進む (K17)

    stages = (("accept", receive), ("settle", lambda: host.window.settle()), ("start", lambda: start_works(state)))
    while True:
        require_running(state)
        clean = True
        for name, stage in stages:
            state.store_failures.last = None
            try:
                stage()
            except Exception as exc:
                failure = state.store_failures.last
                if failure is not None and failure[1] is exc:
                    # 置き場の操作の失敗: 窓口の状態はそのまま。次の段 (仕事の開始) は進め、次の周で入り直す
                    _interrupt(state, "store", failure[0], exc)
                    clean = False
                    continue
                state.halted = _interrupt(state, "halted", name, exc)
                raise _fb.FHalted(f"the host halted at {name}: {type(exc).__name__}: {exc}") from exc
        if clean:
            state.round_clean = True
        if done(host.window.status()):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)


def start_works(state) -> None:
    """ClaimStart (占有を確保) → Launch。launched でも本体に入ったかは enter で別に決まる。
    not_started は開始待ちに戻す。unknown と例外は占有を持ったまま出し直さない (§2-4-2)。"""
    require_running(state)
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
                        # 開始札を取った本体の実際の終わり。ここで初めて占有を解放する。この口は以後、控えを足さない (K29)
                        row.stopped, row.phase, row.held, row.claim = True, "stopped", None, None
                        ctx.returned = True
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


def _seat_holders(state, row) -> tuple:
    """row と同じ割当の席を今持っている仕事の要求 (席が足りずに待っている仕事が、何を待っているかの名指し)。"""
    slot = row.work.desc.allocation
    return tuple(r.work.request for r in state.works.values()
                 if r is not row and r.held is not None and r.work.desc.allocation == slot)


def _blocked_by(state, row) -> tuple:
    """開始待ちの仕事が何を待っているか: 一歩の門 (置き換えた引受け・食い違い・ほかの一歩。起動済みで未入場も) / 席が
    足りない時は同じ割当の席を持っている仕事。"""
    from ._fb_act import blocking
    if row.ticket_used or row.phase not in ("pending", "starting"):
        return ()
    held = blocking(state, row)
    if held:
        return held
    if row.phase == "pending" and not isinstance(row.work, PlannedWork) and _saved(state, row.work.request) \
            and not _fits(state, row) and row.need is not None:
        return _seat_holders(state, row)
    return ()


def work_statuses(state) -> tuple:
    out = []
    for row in state.works.values():
        desc = row.work.desc
        out.append(_fb.WorkStatus(
            work_id=desc.work_id, request=row.work.request, purpose=desc.purpose, phase=row.phase,
            startable=startable(state, row), blocked_by=_blocked_by(state, row), knowledge=row.knowledge,
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
    stopped: bool = False
    held: object = None
    reports: list = _field(default_factory=list)   # (封筒の番号, r)
    issued: list = _field(default_factory=list)    # 生きた発行物 (保存しない)
    uses: list = _field(default_factory=list)      # (Point, M の読み)
    intervals: list = _field(default_factory=list)  # 係が monitored に渡した区間の控え (K28 の B3')
    takes: list = _field(default_factory=list)      # 源へ取りに行った操作の控え (K25 の Take。公開まで進んだ回だけ)


@_dataclass(frozen=True)
class Take:
    """ホストが源へ取りに行った 1 回の操作の控え (K25 (e))。実際の取得の時に作る (保存された Frame から作らない)。"""
    route_epoch: str
    cursor: int
    before_ns: int
    after_ns: int
    outcome: str
    envelope: int | None      # taken の原文の封筒の番号
    sample_seq: int
    source_called: bool
    clock_source: object      # その回で握った時計の出どころの Point
    frame_envelope: int
    received_id: object       # taken の原文に使った名札 (Ref)


class WorkContext:
    """FWorkContext の実装。1 つの仕事の行に結んだ口。"""

    def __init__(self, state, row):
        self._state, self._row = state, row
        self.entered = False   # この口が開始札を取ったか
        self.invoked = False   # この口の本体が呼ばれたか
        self.returned = False  # 入場した本体が戻ったのをホストが観測したか (K29)
        self.performed = False  # この口で一歩を行った (同じ一歩を二度始めない、K36)

    def enter(self) -> bool:
        with self._state.lock:
            row = self._row
            # 開始の札を取れるのは、今の占有を確保した起動の口だけ (R20)。起動の後・入場の前に上の段の
            # 食い違いが見えたら入場させない (紙 :864、review FB2-R01)。入場していないので開始待ちに戻る
            if row.ticket_used or row.claim is not self or _blocked(self._state, row):
                return False
            row.ticket_used = self.entered = True
            row.entered += 1
            row.entered_ns = mono_ns(self._state.clock)
            row.phase = "running"
            return True

    def post(self, event, issued=None) -> None:
        state = self._state
        with state.lock:
            post(state, event)
            if not self.entered:
                return   # 開始の札を取っていない口の報告は原報告として残るだけで、仕事に結ばない (B6)
            envelope = state.queue[-1]
            self._row.reports.append((envelope.number, envelope.received_ns))
            if issued is not None:
                self._row.issued.append((envelope.number, issued))

    def _require_entered(self) -> None:
        """開始の札を取っていない口は、実使用・実監視の証拠を残せない (§6-10 J8・K11)。ロックの中で呼ぶ。"""
        if not self.entered:
            raise RuntimeError("this work port has not entered: it cannot record evidence")

    def _require_live(self) -> None:
        """入場していて、本体がまだ戻っていない口だけが、ホストの控え (使用・区間・取りに行き) を足せる (K29)。
        戻った後の口は入場していない口と同じに断る (§6-10 J8 の「失効した口」)。ロックの中で呼ぶ。"""
        self._require_entered()
        if self.returned:
            raise RuntimeError("this work port's body has returned: it cannot record evidence")

    def read(self, point) -> bytes:
        state = self._state
        with state.lock:
            self._require_live()
        record = state.ledger.record(point)
        with state.lock:
            self._require_live()   # 台帳を読んでいる間に本体が戻ったら、使用を足さず本文も返さない (K29 決定 4)
            self._row.uses.append((point, mono_ns(state.clock)))
        return record.body.content.data

    def monitored(self, interval) -> None:
        with self._state.lock:
            self._require_live()
            self._row.intervals.append(interval)

    def evidence(self):
        return evidence(self._state)

    def _reading(self, source=None):
        """今の M の読みと、発行済みの時計の出どころの Point (K23)。ロックの中で呼ぶ。
        source を渡した時は選び直さず、その Point のまま M だけ読む (取り出しの後の読み: 源を読んでいる間に
        時計の宣言が食い違っても、もう起きた取り出しの記録を落とさない。食い違いで保留するのは結びつきの門)。"""
        from . import f as _f
        from ._fb_boot import _clock_source
        state = self._state
        if source is None:
            source = _clock_source(state)
        if source is None:
            raise RuntimeError("no clock source has been issued for this run")
        return _fb.ReadingClock(source=source, reading=_f.ClockReading(run=state.clock.run, time_ns=mono_ns(state.clock)))

    def _reading_at(self, ns):
        """入場の時の M の読み ns を、発行済みの時計の出どころと組にする (K36 決定 12 の一歩の始まり)。ロックの中で呼ぶ。"""
        from . import f as _f
        from ._fb_boot import _clock_source
        source = _clock_source(self._state)
        if source is None:
            raise RuntimeError("no clock source has been issued for this run")
        return _fb.ReadingClock(source=source, reading=_f.ClockReading(run=self._state.clock.run, time_ns=ns))

    def now(self):
        with self._state.lock:
            self._require_entered()
            return self._reading()

    def perform(self, execution):
        """一歩を行う仕事の口だけ (K36 決定 3)。中身は `_fb_act.perform`。"""
        from . import _fb_act
        return _fb_act.perform(self._state, self, self._row, execution)

    def acquire(self):
        """この測る仕事の口の源から次の番号の 1 件を取りに行き、その結果をホスト自身が預ける (K23・K25)。
        準備 (時計の出どころを握る → before → 原文の名札を用意。共有の状態は変えない) → 源を読む (受付の鍵の外) →
        確定 (受付の鍵の下で 1 回: M を 1 回読む = after = 原文と取得の Frame の受信の時刻 → 封筒と控えを組み立て
        終える → 公開)。源の読みの鍵は準備の頭から確定の終わりまで持つ。源を読んだ後・公開の前の例外では何も
        公開しない (片方だけ預けない・番号だけ進めない)。その回の結果と時刻は残らない (損失、★S5・紙 Z49)。
        ホストが止まっていたら、始める時に 1 回だけ確かめて FHalted (RuntimeError、何も起きていない。K27 新しい決定 6)。
        源を読んでいる間に止まった回は公開されうるが、止まったホストは受付・settle を進めないので台帳に入らない。"""
        from ._fb_bind import _route
        state, row = self._state, self._row
        with state.lock:
            self._require_entered()   # 止まった後かどうかは、下の準備の境目だけで見る (K29 決定 4・K29-a)
            require_running(state)
            if not isinstance(row.work, _fb.MeasureSegment):
                raise RuntimeError("only a measuring work port can acquire from its source")
            route, _applied = _route(state, row.work.desc.args.route)
            if route is None:
                raise RuntimeError("the route of this measuring work is not applied")
            epoch = route.config.route_epoch
        with state.source_lock:
            with state.lock:   # 準備: ここで例外なら、まだ源を読んでいない (何も起きていない)
                # 源の読みの鍵を待つ間に本体が戻っていたら、ここで断る (K29 の境目)。通った回は公開まで進む
                self._require_live()
                cursor = state.cursors.get(epoch, 0)
                source = state.sources.get(epoch)
                before = self._reading()
                raw_id = state.ids.new(_RefKind.OBSERVATION)   # 原文の名札 (空・取れなかった時は使わないまま)
                # 源を読みに行っている間の始まり (K36 決定 12: 行う一歩との前後を決めるまで、その一歩の結果の採用を待つ)
                state.inflight[epoch] = before.reading.time_ns
            try:
                return self._take(state, row, epoch, cursor, source, before, raw_id)
            finally:
                with state.lock:
                    state.inflight.pop(epoch, None)

    def _take(self, state, row, epoch, cursor, source, before, raw_id):
        """acquire の源を読む所から公開まで (源の読みの鍵の中で呼ぶ)。"""
        item, raw, outcome, reason = None, None, "unavailable", "no source is attached to this route"
        if source is not None:
            try:
                item = source.read(cursor)
            except Exception as exc:   # 源の故障を「空」に丸めない。理由を残して返す (ふつうの結果)
                item, reason = None, f"{type(exc).__name__}: {exc}"
            else:
                if item is None:
                    outcome, reason = "empty", ""
                elif type(item) is not _fb.SourceItem:   # 形の合わない戻り値 = ふつうの結果 (K23-a (オ))
                    item, reason = None, "the source returned a value that cannot be saved as received: not a SourceItem"
                else:
                    # 組み立て (K25 (d2) ②): 凍らせた値を、受付と同じ 1 つの検査で確かめ、その値を預ける (源の持つ
                    # 可変の claims が後から変わっても、確かめた中身と預ける中身がずれない)。「取れなかった」に
                    # するのは、形が合わないと確かめた時 (FbInputError) だけ。凍らせる・確かめるを終えられなかった
                    # 例外 (資源の不足・想定外の例外) は源の結果ではないので、何も公開せずに上げる (その回は損失、
                    # K25 (d2)・Z42 (c)・Z49。ふつうの Post・回す役 K17 と同じ線)
                    raw = freeze(_fb.Received(route_epoch=epoch, media_type=item.media_type, data=item.data,
                                              claims=item.claims))
                    try:
                        _check_event(raw)
                    except _fb.FbInputError as exc:
                        item, raw = None, None
                        reason = f"the source returned a value that cannot be saved as received: {exc}"
                    else:
                        outcome, reason = "taken", ""
        with state.lock:
            # 確定 ①: この 1 つの読みが after であり、原文と Frame の受信の時刻 (鍵を放さずに公開まで)
            after = self._reading(before.source)
            r, seq, called = after.reading.time_ns, state.samples.get(epoch, 0), source is not None
            # ② 組み立て終える (共有の状態はまだ変えない)
            result: dict = {"kind": outcome}
            if outcome == "taken":
                result["received"] = str(raw_id)
            elif outcome == "unavailable":
                result["reason"] = reason
            frame = _fb.SegmentReport(segment=row.work.request, item_slot=f"frame:{seq}", item=_fb.MeasurementFrame(
                route_epoch=epoch, sample_seq=seq,
                measurement_id=_fb.MeasurementId(origin=after.reading.run, route_epoch=epoch, sample_seq=seq,
                                                 component="source_acquisition"),
                measurement_interval=_fb.MeasurementInterval(clock=after.reading.run, start_ns=before.reading.time_ns,
                                                             end_ns=r, closure="[start,end]"),
                actual_time=after.reading,
                value={"cursor": cursor, "source_called": called, "clock_source": before.source, "result": result},
                quality=_fb.ContractValue(contract=_ContractRef("sui.f.measured_quality", "1"), value="measured"),
                gap=None,
                source_cursor=_fb.ContractValue(contract=_ContractRef("sui.f.sequence_cursor", "1"), value=seq)))
            _check_event(frame)
            envelopes = _envelopes(state, (raw, frame) if outcome == "taken" else (frame,), r)
            take = Take(route_epoch=epoch, cursor=cursor, before_ns=before.reading.time_ns, after_ns=r,
                        outcome=outcome, envelope=envelopes[0].number if outcome == "taken" else None,
                        sample_seq=seq, source_called=called, clock_source=before.source,
                        frame_envelope=envelopes[-1].number, received_id=raw_id if outcome == "taken" else None)
            # ③ 公開: 組み上がった値を入れるだけ。原文の保存もホストの責務 (この仕事の口からの封筒)
            if outcome == "taken":
                state.raw_ids[envelopes[0].number] = raw_id
                state.cursors[epoch] = cursor + 1
            state.acquired[envelopes[-1].number] = wire(envelopes[-1])   # 窓口が acquire の封筒と見分ける (Z55)
            _publish(state, envelopes)
            row.reports.extend((e.number, e.received_ns) for e in envelopes)
            state.samples[epoch] = seq + 1
            row.takes.append(take)
        return _fb.Acquisition(route_epoch=epoch, cursor=cursor, before=before, after=after, outcome=outcome,
                               reason=reason, item=item)

    def reader(self):
        """その仕事の Desc の numerical_view の境界と input_points の閉包だけの読み手 (§6-9 H5)。
        信念の更新 Wu では、その閉包に要求 Q* 自身を足す (入口 U は Q* を読む。Q* を固定根 Xnum には
        入れない、§6-10 J2)。"""
        from ._fb_boot import _Closure
        desc = self._row.work.desc
        boundary = set(desc.input_points)
        if desc.numerical_view is not None:
            boundary |= desc.numerical_view.boundary
        if desc.purpose == "belief_update":
            boundary.add(self._row.work.request)
        return _Closure(self._state.ledger, frozenset(boundary)) if boundary else None

    def prepared(self):
        """Ee の args.prepared と照合した Ep の生きた発行物。ほかの仕事は None (§6-9 H5)。"""
        from . import _fb_think
        with self._state.lock:
            return _fb_think.prepared_for(self._state, self._row)


def _saved_point(state, number):
    """その封筒の原報告の保存を照合できた時だけ実在の Point (まだ・断った時は None)。ロックの中で呼ぶ。"""
    receipt = state.receipts.get(number) if number is not None else None
    return receipt.slots[0].entry.cid if receipt and receipt.slots and receipt.slots[0].entry else None


def evidence(state):
    from . import f_update2 as _u
    with state.lock:
        executions, uses, intervals, sources = [], [], [], []
        for row in state.works.values():
            wid = row.work.desc.work_id
            reports = []
            for number, r in row.reports:
                reports.append(_u.ReportObservation(envelope=number, received_ns=r, point=_saved_point(state, number)))
            executions.append(_u.ExecutionObservation(work_id=wid, launches=tuple(row.launches),
                entered=row.entered, stopped=row.stopped, reports=tuple(reports)))
            uses += [_u.UseObservation(work_id=wid, point=p, used_ns=ns) for p, ns in row.uses]
            intervals += [_u.IntervalObservation(work_id=wid, interval=i) for i in row.intervals]
            for take in row.takes:
                sources.append(_u.SourceObservation(
                    work_id=wid, route_epoch=take.route_epoch, cursor=take.cursor, before_ns=take.before_ns,
                    after_ns=take.after_ns, outcome=take.outcome, envelope=take.envelope,
                    received=_saved_point(state, take.envelope), sample_seq=take.sample_seq,
                    source_called=take.source_called, clock_source=take.clock_source,
                    frame_envelope=take.frame_envelope, frame=_saved_point(state, take.frame_envelope),
                    received_id=take.received_id))
        return _u.TargetEvidence(executions=tuple(executions), uses=tuple(uses),
                                 intervals=tuple(intervals), acquisitions=tuple(state.acquisitions),
                                 sources=tuple(sources))
