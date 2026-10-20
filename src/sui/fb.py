"""関所 F の F-b: 縦の 1 本の公開の入口 (紙 `specs/関所F_Fb_今の約束.md` v0.25)。

段 0 の骨組み (§5-2): 公開の形だけを固定し、本体は段 1〜3 で書く。形の正本は紙の
§2-4-7 (入口の外形)・§2-4-11 (M1〜M4)・§2-5 (保存の形)・§6 (v0.25 で置き換えた所、§6-6 が
段 0 の形の直し。ゆうの決定 D8「意味を守る。形は根拠をつけて変えてよい」)。旧 `runtime.Window`・
`Drive`・`Think`・`Act` は変えない。F-a の値の型 (区間・測定 ID・時計の読み・Gap など)
は意味を変えずに使い回す。
"""

from collections.abc import Callable as _Callable
from dataclasses import dataclass as _dataclass
from typing import Literal as _Literal, Protocol as _Protocol, TypeAlias as _TypeAlias

from .clock import Clock as _Clock
from .clock_contracts import ClockSource
from .contracts import ContractRef
from .f import (
    ClockReading, ContractValue, CoverageClaim, CoverageUnproved, DrawRequest,
    FFactsRequest, FMathArtifact, FRegistry, Gap, ImmutableJSON, MeasurementFrame,
    MeasurementInterval, MeasurementUnavailable, Point, RouteConfig,
    Unavailable,
)
from .f_update2 import IssuedUpdate, LaunchResult, TargetEvidence
from .ids import Ref
from .ledger import Ledger as _Ledger
from .runtime import Envelope

__all__ = [
    "FbInputError", "FbHostFault", "MethodCall", "QuantityValue", "SlotValue", "SlottedMethod",
    "BootSlot", "FixedView", "ResourceScope", "Allocation", "BootstrapRoute",
    "InitialProcess", "Environment", "BootDeclaration", "ReadingClock",
    "ReadingEvidence", "GenerationPair", "FailureInfo", "UnknownInfo",
    "WorkOutputs", "WorkFailure", "WorkUnknown", "WorkOutcome", "DrawValue",
    "DrawFailure", "DrawUnknown", "DrawOutcome", "SegmentBoundary", "RouteAppliedItem",
    "SegmentItem", "Boot", "ClockDeclared", "Received", "SegmentReport",
    "WorkFinished", "DrawReturned", "FEvent", "Stage", "Trigger", "SegmentArgs",
    "Ongoing", "CandidateArgs", "UpdateArgs", "EvaluationPrepareArgs", "DrawArgs", "EvaluationArgs",
    "WorkArgs", "Desc", "MeasureSegment", "Compute", "Draw", "FWork",
    "Unsaved", "Held", "StatusBasis", "SlotStatus", "ReceiptStatus", "WorkStatus",
    "ReadingStatus", "PendingStatus", "CellStatus", "SegmentStatus",
    "PurposeStatus", "FStatus", "FWorkContext", "FWorkers", "LaunchResult", "FLauncher", "FWindow",
    "FThreadHost", "Envelope",
]


class FbInputError(ValueError):
    """外側の形の誤りだけ (§2-4-7)。記録も預かりも作らず、ホストは同じ封筒を持ったまま上げる。

    reason は "shape" だけ。field は誤った欄の JSON Pointer。中身の bytes・送り手の主張・
    報告の値の正しさ・知らない要求や区間への言及では上げない (P1: 事実は先に残す)。
    """

    def __init__(self, *, reason: _Literal["shape"], field: str) -> None:
        super().__init__(f"{reason}: {field}")
        self.reason = reason
        self.field = field


class FbHostFault(RuntimeError):
    """ホストの故障 (§2-4-7): 同じ番号の封筒の中身や r の食い違い、ホストの時計の逆転 (r > s)、
    別の run の時計。入力の外側の誤り (FbInputError) とも、失効した窓口 (RuntimeError) とも分ける。
    記録も預かりも作らない。"""


# --- 共通値と Boot の入れ子 (§2-5-3) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class MethodCall:
    """方法と全引数。args の意味・参照経路はその版つき方法の宣言で閉じる (B:1007、U4)。"""
    contract: ContractRef
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class QuantityValue:
    """資源の量。この版の contract は `sui.fb.seats/1` だけ、value は非負整数 (bool は不可)。
    負の量を 0 へ丸めて合法にしない (U3)。"""
    contract: ContractRef
    value: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class SlotValue:
    """Boot 内の版つき宣言値 (独立 Record ではない、T1)。declaration は {contract, value}。
    value の型は contract が決める (ResourceScope・BootstrapRoute など)。"""
    slot: str
    contract: ContractRef
    value: object


@_dataclass(frozen=True, slots=True, kw_only=True)
class SlottedMethod:
    """Boot 内の δ の宣言位置 (独立 Record ではない)。"""
    slot: str
    method: MethodCall


@_dataclass(frozen=True, slots=True, kw_only=True)
class BootSlot:
    """保存した boot_declaration の Point と、その中の宣言位置 (Q2・U4)。名札で同一性の証明ではない。"""
    declaration: Point
    slot: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FixedView:
    """保存済み Point の境界と読み手の像 (§2-5-1)。registry_key=None は registry を
    使わない操作の枝だけ。reader_view_key は knowledge_origin の Point とは別。"""
    boundary: frozenset[Point]
    reader_view_key: str
    registry_key: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ResourceScope:
    """`sui.fb.resource_scope/1`: 量の契約と、固定した仕事記述から必要量を求める方法 (U3、B:836)。"""
    quantity_contract: ContractRef
    need: MethodCall


@_dataclass(frozen=True, slots=True, kw_only=True)
class Allocation:
    """`sui.fb.allocation/1`: 同じ Boot の資源範囲 (scope_slot) と量。capacity と同じ量の契約で照合。"""
    scope_slot: str
    amount: QuantityValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class BootstrapRoute:
    """`sui.fb.bootstrap_route/1`: 設定全文・測る過程・初期割当。initial=None でも残る (Q2)。
    reading_contract は区間の報告の結びつき B が写す読み方の契約 (§6-8 B1)。None は読み方を
    宣言しない口で、測定と原報告は続くが B は作らない。"""
    config: RouteConfig
    process_slot: str
    allocation: SlotValue
    reading_contract: ContractRef | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class InitialProcess:
    """`sui.fb.initial_process/1`: 最初の過程・読み手・モデル・生成方法・評価方法・割当・
    更新の導出方法 (δ)。δ は保存済みの事実 (受信・区間の報告・Claim など) をきっかけに更新要求 Q* を
    導く差し替えられる方法 (紙 §6-4、TRACE-02)。契約の名前と入力の形は段 3 で決める (§2-5-4 の
    `sui.fb.received_update/1` は受信だけを火種にしていた)。"""
    process_slot: str
    reader_slot: str
    model: Point
    generator: MethodCall
    method: MethodCall
    allocation: SlotValue
    derivation: SlottedMethod


@_dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """`sui.fb.environment/1`: ホストが渡した起動環境の原文。中の文字列を Point や
    registry の識別へ読み替えない (P1、T5)。"""
    data: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class BootDeclaration:
    """起動の宣言 (§2-5-3)。資源範囲 1 つ・量の契約 1 つ・bootstrap の口と測る過程 1 つが
    この版の合法な縦の 1 本。capacity の実値は宣言で受け取り、既定値を置かない。"""
    capacity: QuantityValue
    scope: SlotValue
    routes: tuple[SlotValue, ...]
    initial: SlotValue | None
    environment: SlotValue


# --- 原報告・返答・終わりの入れ子 (§2-5-6) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class ReadingClock:
    """ReadingEvidence の clock 枝。source は以前に保存した clock.source の Point (Q3)。"""
    source: Point
    reading: ClockReading


ReadingEvidence: _TypeAlias = ReadingClock | Unavailable


@_dataclass(frozen=True, slots=True, kw_only=True)
class GenerationPair:
    """生成 e の始めと終わりの読み。r・s と別 (B:1008)。"""
    started: ReadingEvidence
    finished: ReadingEvidence


@_dataclass(frozen=True, slots=True, kw_only=True)
class FailureInfo:
    """失敗の種類・内容・読み・知った根拠 (B:174、339、1144)。"""
    failure_kind: str
    content: ImmutableJSON
    readings: tuple[ReadingEvidence, ...]
    basis: tuple[Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class UnknownInfo:
    """結果不明を知った根拠。Unknown と後着の値だけで Conflict にしない (B:797)。"""
    reason: str
    basis: tuple[Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class WorkOutputs:
    """Compute の出力。outputs.contract は要求の output_contract と照合する (Q4)。"""
    outputs: ContractValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class WorkFailure:
    failure: FailureInfo


@_dataclass(frozen=True, slots=True, kw_only=True)
class WorkUnknown:
    unknown: UnknownInfo


WorkOutcome: _TypeAlias = WorkOutputs | WorkFailure | WorkUnknown


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawValue:
    """くじの値だけ。要求は WorkId から対応する D 要求へ解決する (Q4)。"""
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawFailure:
    """生成器の確定した断りは failure_kind='rejected' (U6)。4 つ目の枝は足さない。"""
    failure: FailureInfo


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawUnknown:
    unknown: UnknownInfo


DrawOutcome: _TypeAlias = DrawValue | DrawFailure | DrawUnknown


# --- 区間の八枝 (§2-5-7) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class SegmentBoundary:
    """started / ended の枝 (同じ四欄)。kind で区別する。ended は停止・解放の独立証拠ではない。"""
    kind: _Literal["started", "ended"]
    work: str
    reading: ReadingEvidence
    reason: str
    evidence: tuple[Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class RouteAppliedItem:
    """route_applied の枝: 設定の実効 e。旧 RouteApplied DTO は変えない。"""
    config: Point
    reading: ReadingEvidence
    reason: str
    evidence: tuple[Ref, ...]


SegmentItem: _TypeAlias = (
    SegmentBoundary | RouteAppliedItem | MeasurementFrame | Gap
    | MeasurementUnavailable | CoverageClaim | CoverageUnproved
)
"""八枝: started・ended (SegmentBoundary)・route_applied・frame・gap・
measurement_unavailable・claim・coverage_unproved。F-a の DTO はそのまま使う。"""


# --- 出来事 6 つ (§2-4-7) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class Boot:
    """I-6。知らせは `sui.s4.boot/1` と `sui.fb.boot_declaration/1` の 2 slot。"""
    declaration: BootDeclaration


@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockDeclared:
    """I-7 (M2)。1 通知 → `sui.clock.source/1` の受信の記録 1 つ。実測の精度の認証ではない。"""
    declaration: ClockSource


@_dataclass(frozen=True, slots=True, kw_only=True)
class Received:
    """I-1 → `sui.fb.received/1`。届いた bytes と、モデルが読める観測は別 (§2-4-0)。
    claims の中の時刻・ID・契約名は送り手の主張。"""
    route_epoch: str
    media_type: str
    data: bytes
    claims: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class SegmentReport:
    """I-2 → `sui.fb.segment_report/1`。segment は区間要求 k の名指し。"""
    segment: Point
    item_slot: str
    item: SegmentItem


@_dataclass(frozen=True, slots=True, kw_only=True)
class WorkFinished:
    """I-3 → `sui.fb.work_report/1`。Compute の用途 (Wg を含む) の終わり。
    測る仕事の終わりは I-2 の ended、D の終わりは DrawReturned。"""
    work: str
    started: ReadingEvidence
    finished: ReadingEvidence
    outcome: WorkOutcome


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawReturned:
    """I-8 → `sui.fb.draw_report/1` (M4)。D の終わりはどれもこれで受ける。"""
    work: str
    outcome: DrawOutcome


FEvent: _TypeAlias = Boot | ClockDeclared | Received | SegmentReport | WorkFinished | DrawReturned


# --- 仕事の要求と Desc (§2-5-5) ---

Stage: _TypeAlias = _Literal[
    "measure_segment", "candidate_generation", "belief_update",
    "evaluation_prepare", "selection_draw", "evaluation",
]
"""仕事の用途。v0.25 で belief_result・belief_proof・verification を belief_update 1 つに (§6-2・§6-6)。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class Trigger:
    """保存済みのきっかけと、δ か初期計画が定める役割。"""
    point: Point
    slot: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class Ongoing:
    """続けて測る要求 (紙 §6-5 G1)。clock は宣言した時計 M の RUN Ref。始まりはこの仕事の Started の
    実際の読みから解決し、終わりを先に数にしない (停止・設定の変更などの実際の境目で分かる)。
    報告は 1 つずつ有限の MeasurementInterval で出し、報告ごとに Ended を出さない。
    この要求そのものを「無限の区間を測った」証拠にしない。"""
    clock: Ref


@_dataclass(frozen=True, slots=True, kw_only=True)
class SegmentArgs:
    """requested は有限の区間か、続けて測る要求 (v0.25 §6-5: 前の requested_interval は両端の
    整数を要し、測り始める前に終わりを決めさせていた)。"""
    route: Point
    requested: MeasurementInterval | Ongoing
    start_reason: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateArgs:
    """生成器は Desc.method。完成済みの候補を入力に受け取らない。"""
    model: Point
    generator_args: ImmutableJSON
    basis: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class UpdateArgs:
    """信念の更新 Q* の引数 (紙 §6-2)。Q* は仕事の要求そのもので、別の Q を二重に持たない。
    読み手は Desc.reader、固定根 Xnum は Desc.numerical_view、計算して発行する入口 U とその版は
    Desc.method、要る来歴は Desc.input_points。prior は前の採用 A* (None は採用がまだ無い =
    model.initial)。observations は適用する観測の並び。仕事が自分で作った joint は受けない (§6-3)。"""
    model: Point
    prior: Point | None
    observations: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationPrepareArgs:
    """EQ の入力全文。Desc.method は実行の操作、input.method は評価方法。"""
    input: FFactsRequest
    compiler: ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawArgs:
    prepared: Point
    stream_id: str
    request: DrawRequest


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationArgs:
    evaluation_request: Point
    prepared: Point
    draw: Point


WorkArgs: _TypeAlias = (
    SegmentArgs | CandidateArgs | UpdateArgs | EvaluationPrepareArgs | DrawArgs | EvaluationArgs
)


@_dataclass(frozen=True, slots=True, kw_only=True)
class Desc:
    """仕事の記述 (13 欄、B:1007)。reader=None は読み手を使わない測定の用途だけ、
    numerical_view=None は数値入力の像を使わない用途だけ。permissions は slot の存在だけで
    許可にしない。input_points は実入力の固定で、必須閉包の正解ではない。"""
    work_id: str
    process: BootSlot
    trigger: frozenset[Trigger]
    purpose: Stage
    stage_slot: str
    reader: Point | None
    method: ContractRef
    output_contract: ContractRef
    args: WorkArgs
    input_points: frozenset[Point]
    numerical_view: FixedView | None
    allocation: BootSlot
    permissions: frozenset[BootSlot]


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasureSegment:
    """区間要求 k の仕事。desc.purpose="measure_segment"。終わりは I-2 の ended と実際の停止。"""
    request: Point
    desc: Desc


@_dataclass(frozen=True, slots=True, kw_only=True)
class Compute:
    """計算の仕事 (候補の生成 Wg・信念の更新 Wu・評価の準備 Ep・評価 Ee)。
    Wg は 4 つ目の FWork ではなく Compute の用途。終わりは WorkFinished。"""
    request: Point
    desc: Desc


@_dataclass(frozen=True, slots=True, kw_only=True)
class Draw:
    """くじの仕事 D。終わりは DrawReturned。引き直さない。"""
    request: Point
    desc: Desc


FWork: _TypeAlias = MeasureSegment | Compute | Draw
"""保存した要求と Desc に対応する実行用の和型 (§2-5-16)。開始の札・実行ハンドルを Point にしない。"""


# --- FStatus: 6 つの意味を持つ読み取り専用の公開の像 (§2-4-11 M1、§2-5-16) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class Unsaved:
    """まだ保存していない対象の識別 (封筒の番号・計画の名札)。Point と型を分ける。"""
    plan: str


Held: _TypeAlias = Point | Unsaved
"""対象の識別: 保存済みなら実在の Point、未保存なら預かりとの対応。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class StatusBasis:
    """その項目の判定に使った像と根拠 (M1「各項目に、判定に使った像・根拠の保存済み Point か
    未保存の預かりとの対応を付ける」)。view=None は保存済みの像を使わない判定 (預かりだけ) の時。"""
    view: FixedView | None
    basis: tuple[Held, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class SlotStatus:
    """1 つの記録の slot。target は saved の時だけ実在の Point、それ以外 (accepted・
    awaiting_confirmation・unconfirmed) は預かりの識別 Unsaved。saved は本文・header・CID を照合した
    時だけ。確かめられない時は unconfirmed で、保存していないとも成功したとも言わない。"""
    contract: ContractRef
    state: _Literal["accepted", "awaiting_confirmation", "saved", "unconfirmed"]
    target: Held
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptStatus:
    """意味 1 (受信・受付・保存): 封筒と記録の slot ごと。state="received" は Post の後・Accept の前
    (ホストの受信の列か処理中) で、slots は空。state="accepted" は受信の記録と受付の責務を
    P.receipts に置いた後で、slots はその封筒が作る記録の slot 全部 (Boot は 2 つ)。"""
    envelope: int
    received_ns: int
    state: _Literal["received", "accepted"]
    slots: tuple[SlotStatus, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class WorkStatus:
    """意味 2 (仕事・開始・占有)。Unknown・終わりの保存・停止を分ける。held は持っている占有。"""
    work_id: str
    request: Held
    purpose: Stage
    phase: _Literal["pending", "starting", "running", "stopped"]
    startable: bool
    blocked_by: tuple[Held, ...]
    knowledge: _Literal["none", "success", "failure", "unknown"]
    stop_confirmed: bool
    held: QuantityValue | None
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class ReadingStatus:
    """意味 3 (読み・反映・選択): 対象と読み手ごとの到達。確定返答と実行の失敗・不明を分ける。"""
    target: Held
    reader: Point | None
    reached: _Literal["none", "generated", "acquired", "verified", "adopted"]
    response: _Literal["none", "rejected", "insufficient", "no_decision", "failure", "unknown"]
    adopted: Point | None
    stale: Point | None
    selected: Point | None
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class PendingStatus:
    """意味 4 (未判定・不足・食い違い)。不足の対象は要求された識別子で示し、実在の Point に偽装しない。"""
    kind: _Literal["unchecked", "awaiting_evidence", "missing_contract", "conflict"]
    target: Held | None
    contract: ContractRef | None
    reason: str
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class CellStatus:
    """区間の 1 セル。無報告をゼロや Gap にしない。Claim の受信と被覆の認証を分ける。"""
    interval: MeasurementInterval
    reports: tuple[_Literal["frame", "gap", "measurement_unavailable", "claim", "coverage_unproved"], ...]
    certified: bool
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class SegmentStatus:
    """意味 5 (測定の区間・部分)。ended は ended の報告が届いたことで、実際の停止ではない。"""
    segment: Held
    cells: tuple[CellStatus, ...]
    ended: bool
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class PurposeStatus:
    """意味 6 (未完の目的と引継ぎ、§2-5-8 の SavedPurpose と同じ切り方)。元の条件 (O-ID・条件の種類・
    完全な義務鍵の識別)・目的の役割・過程・読み手・対象部分を保つ。handled は局所の処理の達成
    (引継ぎを含む)、unmet は元の目的の未達で、両方が真でありうる。引受け先の表示は Owner の
    独立の証明ではない。"""
    obligation: Held
    o_id: str
    condition: _Literal["issue", "save", "run", "handle", "stop"]
    role: str
    process: BootSlot | None
    reader: Point | None
    target: Held | None
    part: MeasurementInterval | None
    handled: bool
    handed_to: Held | None
    unmet: bool
    evidence: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class FStatus:
    """窓口の公開の操作の境目でとった整合した局所の像 (M1)。正本の状態・判断の入力・
    仕事を出す命令にしない。試験の期待値の生成元にもしない。"""
    receipts: tuple[ReceiptStatus, ...]
    works: tuple[WorkStatus, ...]
    readings: tuple[ReadingStatus, ...]
    pending: tuple[PendingStatus, ...]
    segments: tuple[SegmentStatus, ...]
    purposes: tuple[PurposeStatus, ...]


# --- 窓口・仕事の係・ホスト (§2-4-1・§2-4-2・§2-4-7・M2) ---

class FWorkContext(_Protocol):
    """仕事の係に渡す口。enter() は同じ WorkId の開始の札を仕事表で 1 回だけ使い、
    True の時だけ係は本体に入る (EnterWorker)。起動の包みが 2 つできても本体には 2 回入らない。
    札を取れるのは今の占有を確保した起動の口だけ (not_started で開始待ちに戻った起動は取れない)。
    札を取っていない口の post は原報告として保存されるだけで仕事に結ばれない (B6)。
    post() は報告の出来事をホストへ渡す (受信の r はホストが押す)。issued はその仕事が得た
    生きた発行物で、その報告の封筒と同じプロセスの中で P.work に結んで持つ (保存しない、
    §2-5-2・§2-5-16): 評価の準備 Ep と評価 Ee は F-a の `FMathArtifact`、信念の更新 Wu は入口 U が
    発行した `IssuedUpdate` (§6-2)。ほかの用途・発行物の無い返答では None。発行物の中身と報告の全内容は
    窓口が照合する (発行物があることだけで成功にしない)。evidence() は入口 U に渡す
    EW・EH・EI・EA の独立の観測 (ホストが自分で行った操作の時の読み。窓口の印や台帳の自己申告から
    作らない、§6-3)。
    read(point) は保存済みの記録の本文を読む唯一の口で、ホストがその実使用 (UseObservation) を
    M の読みとともに記録する。monitored(interval) は測る仕事が実際に見張った区間を報告と別の
    道でホストに残す (IntervalObservation)。どちらも窓口の状態を変えず、記録を保存しない。"""

    def enter(self) -> bool: ...

    def read(self, point: Point) -> bytes: ...

    def monitored(self, interval: MeasurementInterval) -> None: ...

    def post(self, event: FEvent, issued: FMathArtifact | IssuedUpdate | None = None) -> None: ...

    def evidence(self) -> TargetEvidence: ...


class FWorkers(_Protocol):
    """仕事の本体を走らせる係 (段 1〜3 で試験の側が用意する)。run はホストのスレッドで呼ばれ、
    戻ったことが実際の停止の観測になる。返す前に ctx.enter() が False なら本体に入らない。"""

    def run(self, work: FWork, ctx: FWorkContext) -> None: ...


class FLauncher(_Protocol):
    """仕事の係を OS で起動する口 (§2-4-2: Launch と EnterWorker を分ける)。結果 LaunchResult
    (f_update2): launched でも本体に入ったかは enter() で別に決まる / not_started は開始待ちに
    戻してよい / unknown は同じ仕事を出し直さず占有も解放しない。body は
    ホストが包んだ係の実行 (中で workers.run と ctx.enter() を呼ぶ)。launch が例外を上げた時は
    unknown と同じに扱う。試験は起動の手前の失敗を選んで起こすために差し替える。"""

    def launch(self, work_id: str, body: _Callable[[], None]) -> LaunchResult: ...


class FWindow:
    """窓口 (§2-4-7)。正本の可変状態を持たない (H・P・C・E はホストが持つ)。
    作り直された後の旧窓口への操作は失効を示す RuntimeError (M2)。窓口はホストからだけ作る。"""

    def __init__(self, host: "FThreadHost") -> None:
        self._host = host

    def _state(self):
        host = self._host
        if host._window is not self:
            raise RuntimeError("stale FWindow: the host rebuilt its window")
        return host._state

    def accept(self, envelope: Envelope) -> None:
        """1 封筒 → 1 受信の記録を作り、預かる。成功で言えるのはそこまで (保存成功・完了・採用は言わない)。
        外側の形の誤りは FbInputError。r=envelope.received_ns、r ≤ s が破れたら時計の故障の例外。"""
        from . import _fb_core
        _fb_core.accept(self._state(), envelope)

    def settle(self) -> None:
        """預かった遷移の単位を進め、記録を 1 点ずつ保存・照合し、仕事の義務を置く。"""
        from . import _fb_core
        _fb_core.settle(self._state())

    def status(self) -> FStatus:
        """読み取り専用の像。受付・保存・開始・取得・採用・くじの消費をしない。"""
        from . import _fb_core
        return _fb_core.status(self._state())

    def drain(self) -> tuple[FWork, ...]:
        """開始できる仕事の列挙 (取り除かない)。未開始は仕事表の見え方 (§2-4-1)。"""
        from . import _fb_core
        return _fb_core.drain(self._state())


class FThreadHost:
    """F の道のホスト (旧 `ThreadHost` は変えない)。registry は Boot と要求が名指す方法を
    解決する F-a の不変の registry (`make_f_registry`、段 3 からは `fb_registry_v1()` が旧の
    宣言を含めて組む、§2-4-8)。MethodCall の contract は registry の CapabilityDeclaration の
    ref で解決する: Need・δ (各 MethodCall) = kind "method"、測る契約 =
    "measurement"、生成器 = "generator"。Need の能力は CapabilityDeclaration(kind="method",
    input_contract=fb_contracts.NEED_INPUT, output_contract=fb_contracts.QUANTITY_VALUE) で、F-a の能力の
    呼出しの規約 (args/input/output の構造検査) を通して呼ぶ (実装を直接呼ばない)。input は
    {"work": 固定した Desc, "scope": ResourceScope}、返値は QuantityValue。解決できない方法はその意味を要する境界で
    missing_contract として示し、原報告と元の義務は保つ。仕事の本体は workers が走らせる。H (run・時計の出どころ・封筒の番号・
    受信の列)・P・置き場・実行係を持ち、窓口を作り直しても保つ。Boot を自動では入れない
    (起動は Boot の出来事を post する)。容量は Boot の宣言から読み、既定値を置かない。"""

    def __init__(self, *, ledger: _Ledger, clock: _Clock, workers: FWorkers,
                 registry: FRegistry, launcher: FLauncher | None = None) -> None:
        """launcher=None は OS のスレッドで起動する本番の起動係 (threading.Thread.start の成否で
        launched / not_started、start が戻らず分からない時は unknown)。"""
        from . import _fb_core
        self._state = _fb_core.State(ledger=ledger, clock=clock, workers=workers, registry=registry,
                                     launcher=launcher if launcher is not None else _fb_core.ThreadLauncher())
        self._window = FWindow(self)

    @property
    def window(self) -> FWindow:
        """今有効な窓口。"""
        return self._window

    def post(self, event: FEvent) -> None:
        """ホストのロックの下で番号と r (ホストの run の M) を押し、封筒を受信の列へ (Post)。"""
        from . import _fb_core
        _fb_core.post(self._state, event)

    def run_until(self, done: _Callable[[FStatus], bool], *, timeout: float) -> bool:
        """受付・settle・仕事の開始・停止の観測を回し、done(status) が真になれば True、
        timeout を過ぎれば False。timeout の秒数は合否の物差しにしない (F8)。"""
        from . import _fb_core
        return _fb_core.run_until(self, done, timeout)

    def rebuild_window(self) -> FWindow:
        """同じプロセスの中で窓口を作り直して返す (M2)。H・P・C・E と動いている係はそのまま。
        Boot・Post・くじの消費・再入場・占有の解放をしない。新旧 2 つを同時に有効にしない。"""
        with self._state.lock:
            self._window = FWindow(self)
            return self._window

