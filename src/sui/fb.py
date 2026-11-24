"""関所 F の F-b: 縦の 1 本の公開の入口 (紙 `specs/関所F_Fb_今の約束.md` v0.25)。

段 0 の骨組み (§5-2): 公開の形だけを固定し、本体は段 1〜3 で書く。形の正本は紙の
§2-4-7 (入口の外形)・§2-4-11 (M1〜M4)・§2-5 (保存の形)・§6 (v0.25 で置き換えた所、§6-6 が
段 0 の形の直し。ゆうの決定 D8「意味を守る。形は根拠をつけて変えてよい」)。旧 `runtime.Window`・
`Drive`・`Think`・`Act` は変えない。F-a の値の型 (区間・測定 ID・時計の読み・Gap など)
は意味を変えずに使い回す。
"""

import secrets as _secrets
from collections.abc import Callable as _Callable, Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from typing import Literal as _Literal, Protocol as _Protocol, TypeAlias as _TypeAlias

from .clock import Clock as _Clock
from .clock_contracts import ClockSource
from .contracts import ContractRef
from .f import (
    ClockReading, ContractValue, CoverageClaim, CoverageUnproved, DrawRequest,
    FFactsRequest, FiniteKernel, FMathArtifact, FReader, FRegistry, Gap, ImmutableJSON, MeasurementFrame,
    MeasurementId, MeasurementInterval, MeasurementUnavailable, ObservationCell, Point, RouteConfig,
    Unavailable, ActionSpec, KernelRef, PolicyRef,
)
from .f_update2 import IssuedUpdate, LaunchResult, TargetEvidence
from .ids import Ref
from .records import Record
from .ledger import Ledger as _Ledger
from .rate import RateBudget, RationalInterval
from .runtime import Envelope

__all__ = [
    "FbInputError", "FbHostFault", "FHalted", "Interruption", "MethodCall", "QuantityValue", "SlotValue", "SlottedMethod",
    "BootSlot", "FixedView", "ResourceScope", "Allocation", "BootstrapRoute",
    "InitialProcess", "Environment", "BootDeclaration", "ReadingClock",
    "ReadingEvidence", "GenerationPair", "FailureInfo", "UnknownInfo",
    "WorkOutputs", "WorkFailure", "WorkUnknown", "WorkOutcome", "DrawValue",
    "DrawFailure", "DrawUnknown", "DrawOutcome", "SegmentBoundary", "RouteAppliedItem",
    "SegmentItem", "Boot", "ClockDeclared", "Received", "SegmentReport",
    "WorkFinished", "DrawReturned", "FEvent", "Stage", "Trigger", "SegmentArgs",
    "Ongoing", "CandidateArgs", "ObservationUse", "UpdateArgs", "EvaluationPrepareArgs", "DrawArgs", "EvaluationArgs",
    "WorkArgs", "Desc", "MeasureSegment", "Compute", "Draw", "FWork",
    "Unsaved", "Held", "StatusBasis", "SlotStatus", "ReceiptStatus", "WorkStatus",
    "ReadingStatus", "PendingStatus", "CellStatus", "SegmentStatus",
    "PurposeStatus", "BeliefUpdateStatus", "FStatus", "FWorkContext", "FWorkers", "LaunchResult", "FLauncher", "FWindow",
    "FThreadHost", "Envelope", "SourceItem", "FSource", "Acquisition", "SourceMeasurer", "FiniteUpdater", "CandidateGenerator", "EvaluationPreparer", "Evaluator", "UniformDraw", "WorkerBundle",
    "AcquisitionControl", "AcquisitionObservationModel", "AcquisitionReadItem", "AcquisitionReadResult",
    "read_acquisition_sequence",
    "Perception", "ExecutionDeclaration", "ExecutionArgs", "ExecuteStep", "StepExecutor", "FActor",
    "ExecutionResult", "ExecutionReport", "PolicyStatus", "IntentionStatus", "ExecutionStatus",
    "EvaluationStatus", "ThinkingMaterialStatus",
    "BeliefCandidate", "CandidateAddition", "PoolMember", "PoolState", "BeliefPool", "CandidatePosterior",
    "PoolBelief", "CandidateInputError", "CandidatePoolError",
    "SwitchPart", "ClockPrior", "ClockQuantity", "SwitchQuantity", "BetaMixture", "BetaMixtureComponent",
    "ResolvedBeliefPool", "resolve_belief_candidates",
    "PoissonLaw", "FiniteCountLaw", "UniformAcquisitionTime", "FixedAcquisitionSchedule",
    "IndependentAcquisitionFailure", "IndependentSourceDisconnection", "TimedAcquisitionModel", "SourceCountReading", "TimedExecutionDeclaration",
    "BeliefExpression", "BeliefQuantity", "BeliefValue", "SelectionValues", "TimedBeliefUpdater", "TimeBeliefError",
    "start", "RunningSui", "StartInputError",
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


class FHalted(RuntimeError):
    """ホストが止まった (§6-10 K16 (3)(c)、紙 Z42)。回す役 `keep_running` の周の中で、置き場の操作の失敗ではない
    例外が出た時、窓口の頭の中 (やりかけの計画) は信じられないので、回り続けない。止まったホストは受付・settle・
    仕事の開始を進めず、これを上げる。Post は受ける。戻るのは記録から立ち上げ直す時 (★ S5)。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class Interruption:
    """回す役まで上がった中断 (§6-10 K16 (4))。ホストが自分で観測したもので、同じプロセスの中だけに残る (台帳には
    書かない)。kind="store" は置き場の操作の失敗 (operation はその操作の名前。次の周で入り直す)、kind="halted" は
    ホストが止まった理由 (operation は周の段 accept・settle・start)、kind="rejected" は形のおかしい封筒を断ったこと
    (§6-10 K17。operation="accept"、error_type="FbInputError"、message は封筒の番号と形のおかしい欄を含む。1 通ごとに
    1 件で count=1)。続けて同じ中断は count にまとめ、途中で 1 周でも
    中断なしで通ったら別のまとまりにする。first_ns・last_ns はホストの run の M の読み (読めなければ None)。"""
    kind: _Literal["store", "halted", "rejected"]
    operation: str
    error_type: str
    message: str
    first_ns: int | None
    last_ns: int | None
    count: int


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
    """`sui.fb.bootstrap_route/2`: 設定全文・測る過程・初期割当。initial=None でも残る (Q2)。
    reading_contract は区間の報告の結びつき B が写す読み方の契約 (§6-8 B1)。None は読み方を
    宣言しない口で、測定と原報告は続くが B は作らない。repeat は次をいつ取りに行くかの取りに行き方
    (§6-10 K27 新しい決定 2。1 標本が何かの sampling_contract とは別の意味。人が置く最初の方式で差し替えの口)。"""
    config: RouteConfig
    process_slot: str
    allocation: SlotValue
    reading_contract: ContractRef | None
    repeat: MethodCall


@_dataclass(frozen=True, slots=True, kw_only=True)
class Perception:
    """`sui.fb.perception/1`: 感じる側 (紙 F-b K36 新しい決定 2)。見立てを直す過程の席 process_slot・読み手 reader_slot
    (knowledge_origin を作る位置)・見立てのモデル model・割当 allocation・更新の導出方法 δ derivation を自分で持つ。
    考える側 (InitialProcess) が無くても、受け取って・残して・見立てを直す (D7 問 1・Q5 の案 2)。人が置く bootstrap の札で、
    差し替えの口 (P9)。隠れた既定の割当や最低の持分は足さない。δ は保存済みの事実をきっかけに更新要求 Q* を導く方法
    (`sui.fb.saved_segment_update/1` か `sui.fb.saved_acquisition_update/1`)。"""
    process_slot: str
    reader_slot: str
    model: Point
    allocation: SlotValue
    derivation: SlottedMethod


@_dataclass(frozen=True, slots=True, kw_only=True)
class InitialProcess:
    """`sui.fb.initial_process/2`: 考える側 (紙 F-b K36 新しい決定 2)。最初の考える過程の席・感じる側の宣言の位置
    perception_slot (その origin とモデルを参照する)・生成方法・評価方法・くじ・予算・割当・continuation だけを持つ。
    draw は選択用のくじの生成器 (§6-9 H4。家の人は法則 uniform_bits/1 でくじの続きのかたまりを頼む、紙 F-b K35)。
    prepare_budget・evaluate_budget は評価の準備と、くじからの評価に実際に渡す計算の上限 (§6-9 H3)。予算は好み・範囲・
    費用ではなく、コードの既定値で埋めない。continuation は採用の後に考え直せる差し替えられる方法 (§6-10 J6・K1)。
    None は考え直す道を置かない。「採用したら必ず考え直す」の規則ではない (D7)。行う一歩 (K36) はこの過程に帰属する
    (選んだ方針を行うのは選んだ過程) が、席と割当は行う割当 (execution の allocation) を使う (K36-c ①)。"""
    process_slot: str
    perception_slot: str
    generator: MethodCall
    method: MethodCall
    draw: MethodCall
    prepare_budget: RateBudget
    evaluate_budget: RateBudget
    allocation: SlotValue
    continuation: MethodCall | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """`sui.fb.environment/1`: ホストが渡した起動環境の原文。中の文字列を Point や
    registry の識別へ読み替えない (P1、T5)。"""
    data: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionDeclaration:
    """`sui.fb.execution_declaration/2`: 行う一歩をどう行い、その結果をどう読むかの宣言 (紙 F-b K36 決定 3・5・12、K36-a)。
    人が置く bootstrap の読み方で、環境 (おもちゃの相手と受け身の源) について述べる。actors は核の id → 入口で受け取る環境の
    相手の名前、no_effect は宣言した無作用 (外を呼ばずに完了する) の核の id、cells は核の id → 観測セル (観測値は
    `{result, source_called}` の合法な 4 組) で、行った一歩の結果を「届いた / 届かない」で読む分け方。source_overlap・
    actor_overlap は区間が重なった時の宣言: state_preserving (区間の途中も見立ての状態を変えない) / serializable (重なった
    観測と作用を 1 回ずつの前後で表せる) / undeclared (述べない = 重なりは順が分からない)。宣言は現物の証明ではない。"""
    actors: _Mapping[str, str]
    no_effect: tuple[str, ...]
    cells: _Mapping[str, tuple[ObservationCell, ...]]
    source_overlap: _Literal["state_preserving", "serializable", "undeclared"]
    actor_overlap: _Literal["state_preserving", "serializable", "undeclared"]
    allocation: SlotValue        # 行う割当 (Allocation、同じ Boot の資源範囲。考える割当と分ける、K36-c ①)


@_dataclass(frozen=True, slots=True, kw_only=True)
class BootDeclaration:
    """起動の宣言 (§2-5-3、`sui.fb.boot_declaration/5`)。perception は感じる側、initial は考える側 (K36 新しい決定 2)。
    execution は行う一歩の宣言 (K36・K36-c、`sui.fb.execution_declaration/2`。None は行う一歩を宣言しない)。低い水準のホストは
    perception=None を許し、測って残すだけで見立てを直さない (K36-a (オ))。誕生の入口 `start` は perception を求める。資源範囲 1 つ・量の契約 1 つ・bootstrap の口と測る過程 1 つが
    この版の合法な縦の 1 本。capacity の実値は宣言で受け取り、既定値を置かない。observation_models は取得の列を読む
    観測モデル (各 SlotValue の contract = `sui.fb.acquisition_observation_model/1`、value = AcquisitionObservationModel)。
    起動の時にホストが各項から独立した Prediction / MODEL の記録を保存する (§6-10 K26-a (ア)・K26-b)。宣言しない時は
    () を明示で渡す (既定値を置かない)。initial=None でも宣言できる。保存は「宣言を保存した」だけで、正しいことや
    見立てへの採用の証明ではない (中身の検査は読み口 read_acquisition_sequence がする)。"""
    capacity: QuantityValue
    scope: SlotValue
    routes: tuple[SlotValue, ...]
    initial: SlotValue | None
    perception: SlotValue | None
    execution: SlotValue | None
    environment: SlotValue
    observation_models: tuple[SlotValue, ...]


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
    """I-6。知らせは `sui.s4.boot/1` と `sui.fb.boot_declaration/3` の 2 slot。"""
    declaration: BootDeclaration


@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockDeclared:
    """I-7 (M2)。1 通知 → 原報告 `sui.fb.clock_notice/1` の受信の記録 1 つ。窓口は同じ run の起動との対応を
    確かめてから既存 `sui.clock.source/1` を発行する (§6-9 K1)。実測の精度の認証ではない。"""
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
    "evaluation_prepare", "selection_draw", "evaluation", "execute_step",
]
"""仕事の用途。v0.25 で belief_result・belief_proof・verification を belief_update 1 つに (§6-2・§6-6)。K36 で「一歩を
行う」execute_step を足した (7 用途)。"""


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
    整数を要し、測り始める前に終わりを決めさせていた)。repeat は起動の時に route から写した取りに行き方
    (§6-10 K27 新しい決定 2、要求を自己完結に)。"""
    route: Point
    requested: MeasurementInterval | Ongoing
    start_reason: str
    repeat: MethodCall


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateArgs:
    """生成器は Desc.method。完成済みの候補を入力に受け取らない。"""
    model: Point
    generator_args: ImmutableJSON
    basis: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationUse:
    """適用する観測 1 つ (§2-5-19-1): 結びつき B (`segment_binding/1`) と、それを読む読み方
    (`observation_plan/2` の Point)。同じ B を別の読み方で読める。"""
    binding: Point
    reading: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class UpdateArgs:
    """信念の更新 Q* の引数 (紙 §6-2・§6-10 J2)。Q* は仕事の要求そのもので、別の Q を二重に持たない。
    読み手は Desc.reader、固定根 Xnum は Desc.numerical_view、計算して発行する入口 U とその版は
    Desc.method、要る来歴は Desc.input_points。prior は前の採用 A* (None は採用がまだ無い =
    model.initial)。U が prior から前の結果を解決する (二つを別々に選べる形にしない)。observations は
    適用する観測の並び。仕事が自分で作った joint は受けない (§6-3)。"""
    model: Point
    prior: Point | None
    observations: tuple[ObservationUse, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationPrepareArgs:
    """EQ の入力全文。Desc.method は実行の操作、input.method は評価方法。budget はその回に実際に
    渡す予算で、artifact の calls の予算と全照合する (§6-9 H3)。"""
    input: FFactsRequest
    compiler: ContractRef
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawArgs:
    prepared: Point
    stream_id: str
    request: DrawRequest


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationArgs:
    """budget は bind と評価に各々渡す予算 (今の F-a の意味。両方を合わせた総予算の保証ではない、§6-9 H3)。"""
    evaluation_request: Point
    prepared: Point
    draw: Point
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionArgs:
    """行う一歩の固定の像 E (紙 F-b K36 決定 4・6)。要求を Publish する時に固定し、行う係も家の人も結果の記録もこの E に
    結ぶ (結果の側から「最新の選択」を探し直さない)。selection・evaluated は選択 S と評価 EV の Point、root_key・draw は
    評価の根とくじの記録 (DF) の Point、intention は引受けの記録の Point、policy・node・occurrence は方策と節とその節の
    何回目か、action は選んだ操作、kernel・u はこの節の核と、この回の制御 (段 4 では核の id)、model・reading は見立ての
    モデルと行う一歩の宣言の記録、prior は E を作った時の見立ての系列の頭 (採用 A*。無ければ None)。u はその一歩の前までの
    履歴と、状態から独立なくじから決まる (言えるのは P(u | s, H) = P(u | H) まで)。cursor・sample_seq と兼ねない。"""
    selection: Point
    evaluated: Point
    root_key: str
    draw: Point | None
    intention: Point
    policy: PolicyRef | None
    node: str
    occurrence: int
    action: ActionSpec | None
    kernel: KernelRef
    u: str
    model: Point
    reading: Point
    prior: Point | None


WorkArgs: _TypeAlias = (
    SegmentArgs | CandidateArgs | UpdateArgs | EvaluationPrepareArgs | DrawArgs | EvaluationArgs | ExecutionArgs
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


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteStep:
    """一歩を行う仕事 (紙 F-b K36 決定 3)。desc.purpose="execute_step"、desc.args は固定の像 E。係は入場して E を家の人の
    口 `FWorkContext.perform` に渡すだけで、結果のメモは家の人が書く (Z55)。"""
    request: Point
    desc: Desc


FWork: _TypeAlias = MeasureSegment | Compute | Draw | ExecuteStep
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
    response: _Literal["none", "rejected", "insufficient", "no_decision", "no_candidates", "failure", "unknown"]
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
class BeliefUpdateStatus:
    """意味 7 (見立てへ通す、§6-10 K28 新しい決定 11 の B1・K28-a (イ)): 取りに行きの列の 1 回 (sample_seq) ごとの到達と結末。
    model・origin・route_epoch・sample_seq がどの見立てのどの回か。obligation はその回の Frame の結びつき B (まだ無ければ None)、
    request は保存した更新要求 Q* (まだ無ければ None)。outcome は 1 つの語: 待ち (waiting_storage = その回の Frame か原文の
    保存がまだ / waiting_binding = B がまだ / waiting_predecessor = 前の回が採用されて確認されていない / waiting_confirmation =
    採用の判断を公開したが保存の確認がまだ / requested = 更新の仕事が終わっていない / recording = 仕事は終わり、結果・
    結果の取得・採用の判断を記録している途中 (時計の出どころが無ければ理由 clock) / ready = 次の更新要求を作れる) か、
    結末 (adopted・stale・rejected・insufficient・failure・unknown・stopped・conflicted・issued:shape・update:issued:*)。
    adopted 以外はどれも先の回を採用へ進めない。reading はその回までを K26 の読み口で読んだ段 (read・model_zero・unreadable。まだ読んでいなければ None)。
    reasons・fields は U の不適合・不足の理由の語と欄 (閉じた一覧、自由な文は載せない) と、待ちの理由。末尾 3 つは列全体の
    公開・保存がそろった・採用を確認した最後の番号 (無ければ None。数の端に意味を持たせない)。"""
    model: Point
    origin: Point | None
    route_epoch: str
    sample_seq: int
    obligation: Held | None
    request: Held | None
    outcome: str
    reading: _Literal["read", "model_zero", "unreadable"] | None
    reasons: tuple[str, ...]
    fields: tuple[str, ...]
    published_through: int | None
    saved_through: int | None
    adopted_through: int | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class PolicyStatus:
    """意味 8 (方策の進み、紙 F-b K36 決定 8)。選択 S ごとに、方策 policy のどの節まで来たか。outcome は running (次の一歩を
    行っている・待っている) / ended (end の節に着いた) / stopped (進めない。reason に名指し: choose_unconnected・
    exception_reading_missing・next_unknown・not_performed・unconnected) / withdrawn (引受けが置き換えられた)。"""
    selection: Point
    intention: Point | None
    policy: PolicyRef | None
    node: str | None
    outcome: _Literal["running", "ended", "stopped", "withdrawn"]
    reason: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class IntentionStatus:
    """意味 9 (引受け、紙 F-b K36 決定 7)。point は引受けの記録 (`sui.fb.intention/1`) の Point、active は今の引受けか
    (同じ採用の系列で根が後に続く選択に置き換えられたら False)。replaced_by は置き換えた引受けの Point。"""
    point: Point
    selection: Point
    active: bool
    replaced_by: Point | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionStatus:
    """意味 10 (一歩の実行、紙 F-b K36 決定 3・5・12・13・K36-a (エ))。execution は固定の像 E、request はその要求の Point、
    result は家の人が残した結果の記録の Point (まだ無ければ None)。outcome は requested (まだ入場していない) / entered
    (行っている) / waiting_storage (結果の保存待ち。retryable) / observed (観測として残った) / no_effect (宣言した無作用で
    完了、外を呼んでいない) / unconnected (行う所が未接続) / not_performed (呼ぶ前の不足、行っていない) / order_unknown
    (受け身の観測との順が分からない。待っても解けない) / model_zero (読めるセルの質量が 0) / blocked (引受けが置き換え
    られて入場しない)。reason は名指しの語、retryable は待てば解けるか。source_called・result_symbol は結果の観測
    (呼んだか・4 組の語。観測でなければ None)。"""
    execution: ExecutionArgs
    request: Point
    result: Point | None
    outcome: str
    reason: str
    retryable: bool
    source_called: bool | None
    result_symbol: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationStatus:
    """評価の活動 (紙 F-b K36-c ②・K36-c-a ④ (c))。activity は入場の時から変わらない識別 (保存の再試行とくじの続きで
    変えない)。root は根の状態: undetermined (最初の活動の Wg の間) / prior (まだ採用が無い) / adopted (point に採用の
    Point)。context は文脈の記録 (o・j を含む。評価の準備の入力の context と同じ) の保存済みの Point か、未保存の Held。outcome は running / selected (選択を保存) / no_decision /
    no_candidates / failure / unknown / conflict (食い違いで新しい使用を止めた) / stopped (仕事の本体が終わりの知らせ
    無しに止まった) / short (使用の条件の不足)。residual は
    論理的に結末しても席を持っている仕事の識別 (席を返すまで考える割当の数に入る)。counted はその数に入っているか。"""
    activity: str
    allocation: BootSlot
    root: _Literal["undetermined", "prior", "adopted"]
    root_point: Point | None
    context: Point | Held | None
    outcome: str
    residual: tuple[str, ...]
    counted: bool
    basis: StatusBasis


@_dataclass(frozen=True, slots=True, kw_only=True)
class ThinkingMaterialStatus:
    """まだ評価に入場していない材料 (紙 F-b K36-c ⑦・K36-c-a ④ (d))。起動・考える側・採用の系列ごとに、最新の使える採用
    latest、評価に渡した根の境界 handed、未評価の材料があるか unevaluated、入場を妨げている活動 blocked_by (考える割当が
    埋まっている時に数えている活動の識別。根が未確定の活動がある時はその活動)。まだ存在しない評価の識別は作らない。"""
    boot: Point
    initial: BootSlot
    latest: Point | None
    handed: Point | None
    unevaluated: bool
    blocked_by: tuple[str, ...]
    basis: StatusBasis


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
    updates: tuple[BeliefUpdateStatus, ...]
    policies: tuple[PolicyStatus, ...]
    intentions: tuple[IntentionStatus, ...]
    executions: tuple[ExecutionStatus, ...]
    evaluations: tuple[EvaluationStatus, ...]
    thinking_materials: tuple[ThinkingMaterialStatus, ...]


# --- 口の源と、そこからの取り出し (§6-10 K23) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class SourceItem:
    """源が返す 1 件。中身の意味は決めない (W-02)。claims は送り手の主張。"""
    media_type: str
    data: bytes
    claims: ImmutableJSON


class FSource(_Protocol):
    """口の向こうの源 (差し替えの口)。届いたものを順番つきで持っている相手。read(cursor) は cursor 番目の
    1 件を返す (同じ cursor は同じ 1 件)。まだ無ければ None、読めなければ例外。本物の接続 (ネット・ファイル) の
    源は S7。ホストへは FThreadHost の sources (route_epoch → 源) で渡す。"""

    def read(self, cursor: int) -> SourceItem | None: ...


@_dataclass(frozen=True, slots=True, kw_only=True)
class Acquisition:
    """FWorkContext.acquire() の返値。before・after は取りに行く操作の直前と、取得の終端のホストの読み (after は
    原文と取得の Frame の受信の時刻と同じ 1 つの読み)。outcome: taken (item に 1 件。ホストが原文を受信の列へ入れ、
    cursor を進めた) / empty (源にその番号がまだ無い) / unavailable (源が差されていない・読みが例外・形の合わない
    戻り値。理由は reason)。どの結果でも、ホストが取得の結果の Frame を同じ操作の中で受信の列へ入れている (K25)。"""
    route_epoch: str
    cursor: int
    before: ReadingClock
    after: ReadingClock
    outcome: _Literal["taken", "empty", "unavailable"]
    reason: str
    item: SourceItem | None


# --- 行う一歩の相手と結果 (§6-10 K36) ---

class FActor(_Protocol):
    """環境の相手 (紙 F-b K36 決定 3、差し替えの口)。家の人が固定の像 E を渡して呼ぶ。相手は sui の操作を選ばない。返すのは
    届いた 1 件 (SourceItem) か None (何も届かなかった)。例外は「呼んだ・例外になった」として家の人が記録する (決定 13)。
    段 4 の相手はおもちゃ。本物の作用は S6。ホストへは入口 `start` / FThreadHost の actors (名前 → 相手) で渡す。"""

    def perform(self, execution: "ExecutionArgs") -> SourceItem | None: ...


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    """`FWorkContext.perform` の返値 (紙 F-b K36 決定 3・5・13、K36-a (エ))。家の人が行った結果と、それを記録したこと。
    outcome: observed (相手を呼び、「届いた / 届かない」の観測として残した) / no_effect (宣言した無作用。外を呼ばずに完了) /
    unconnected (行う所が未接続、呼んでいない) / not_performed (呼ぶ前の不足、行っていない)。source_called・result_symbol は
    observed の時だけ (taken / empty / unavailable_called)。item は届いた 1 件 (中身は見立てに使わない、Z46 ③)。"""
    outcome: _Literal["observed", "no_effect", "unconnected", "not_performed"]
    reason: str
    source_called: bool | None
    result_symbol: str | None
    item: SourceItem | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionReport:
    """家の人だけが作る、行った一歩の結果のメモ (`sui.fb.execution_result/1`、紙 F-b K36 決定 3・Z55)。係の口 post からは
    受け付けない (FbInputError)。execution は固定の像 E、value は観測 {result, source_called} (観測でない結果は None)、
    outcome・reason は ExecutionResult と同じ語、entered・finished は一歩の入場と結果の記録のホストの読み (順の判定、
    決定 12)、received は届いた中身の原文の名札、actor は呼んだ相手の名前。"""
    work: str
    execution: "ExecutionArgs"
    value: ImmutableJSON
    outcome: str = "observed"
    reason: str = ""
    entered: ReadingClock | None = None
    finished: ReadingClock | None = None
    received: Ref | None = None
    actor: str | None = None


# --- 取得の列を読む本 (§6-10 K26・K26-a・K26-b) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionControl:
    """制御 u の 1 つ。kernel は観測と状態の変化の共同の確率 (F-a の値の型。行列は arrival 行 / departure 列、
    出発の状態ごとに全 outcome の列の和が 1)。cells は観測値 (`{result, source_called}` の合法な 4 組) → outcome の
    集合で、異なるセルの outcome は互いに素、和は核の全 outcome (:2660)。FiniteObservation のハンドルは作らない。"""
    id: str
    kernel: FiniteKernel
    cells: tuple[ObservationCell, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionObservationModel:
    """`sui.fb.acquisition_observation_model/1` の値 (Boot の observation_models の項、bootstrap の札は記録の出どころで示す)。
    route_slot は同じ Boot の routes の slot。control_rule は記録された履歴 → u の候補 (`sui.fb.acquisition_control_table/1`)、
    independence は選び方が状態に依存しない根拠 (`sui.fb.state_independent_control_selection/1`。その重みは L に掛けない)。
    projection は `sui.fb.acquisition_result_projection/1`、time_projection は `sui.f.value_only/1` (同じセルの outcome が
    時刻で違わないことを宣言のモデルの中で検査する)。人が置く札つきの見込みで、正しいことの証明ではない (K26 (4))。"""
    route_slot: str
    states: tuple[str, ...]
    controls: tuple[AcquisitionControl, ...]
    control_rule: MethodCall
    independence: MethodCall
    projection: ContractRef
    time_projection: ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionReadItem:
    """取得の列の 1 項。result は taken / empty / unavailable、source_called は源を呼んだか (取れなかったの 2 種を分ける)。
    before・after は保存した Frame の区間の始めと実測の時刻 (ホストの控えからは読まない)。received_id・received は taken の
    時の原文の名札とその Point。reason の文・原文の bytes は観測に入れない。"""
    sample_seq: int
    cursor: int
    result: _Literal["taken", "empty", "unavailable"]
    source_called: bool
    before: ReadingClock
    after: ReadingClock
    received_id: Ref | None
    measurement_id: MeasurementId
    frame: Point
    received: Point | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionReadResult:
    """読み口の答え。kind="read" は likelihood = 初期の隠れた状態ごとの L(d|u,s0) (事後でも、選択を含む確率でもない。
    一部の状態の 0 は有効な 0)。"model_zero" は全部の初期状態で L=0 (likelihood は 0 の列)。"unreadable" は reason
    (missing_record・missing_declaration・shape・conflict・control_ambiguous・control_independence_unproved・
    time_projection_unproved) を持ち、likelihood は None (空・取れなかった・有効な確率で埋めない)。controls は決めた u の列、
    used_records は使った観測モデルの記録・Boot・Frame・原文の Point、contracts は使った契約。"""
    kind: _Literal["read", "unreadable", "model_zero"]
    reason: str | None
    observations: tuple[AcquisitionReadItem, ...]
    initial_states: tuple[str, ...]
    likelihood: tuple[_Fraction, ...] | None
    controls: tuple[str, ...]
    used_records: tuple[Point, ...]
    contracts: tuple[ContractRef, ...]


# --- 候補の並びと、候補を足す口 (§6-10 K37) ---

@_dataclass(frozen=True, slots=True, kw_only=True)
class BeliefCandidate:
    """足す候補 1 つ (紙 F-b K37 決定 1)。id は並びの中の名前 (並びの中で一意)、model は保存済みの見立てのモデル
    (`sui.f.model_source/1`、状態の一覧・事前・核) の Point、observation_model はその候補の取りに行きの観測の見込み、
    correspondence は物語の対応 {pairs: [[観測モデルの状態, モデルの状態], ...]}。宣言で、正しいことの証明ではない
    (候補の解決が読めない宣言 = 対応・法則・部品は、足す時に名指して断る (K39-b R1)。操作の核が無いなどの読み方の不足は、
    その候補で観測を読む時に名指して止まる)。"""
    id: str
    model: Point
    observation_model: AcquisitionObservationModel
    correspondence: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateAddition:
    """`FThreadHost.add_candidate` の返値: 保存した候補の記録・新しい並びの記録 (Prediction / MODEL)・足した決定 (Decided)。"""
    candidate: Point
    pool: Point
    decision: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class PoolMember:
    """並びの候補 1 つ。prior_weight は並びの起点での事前の重み (K37 決定 8)、law は予測の法則の識別 (知る対象に含める。
    同じ宣言なら同じ法則 = 別名。候補の名前でも記録の Point でもない、K37 決定 1)。"""
    id: str
    model: Point
    prior_weight: _Fraction
    law: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class PoolState:
    """同時の信念の 1 成分 (候補 × 候補の中の状態)。target は候補の中の元の知る対象、law はその候補の法則の識別。"""
    candidate: str
    state: str
    target: str
    law: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class BeliefPool:
    """今効いている並び (K37 決定 1・3)。point は並びの記録 (最初の並びは起動の宣言)、model はその直和のモデル (最初の並び
    は感じる側のモデル。F-a の読み口で読める model_source)、states は同時の信念の並びの順。"""
    point: Point
    model: Point
    members: tuple[PoolMember, ...]
    states: tuple[PoolState, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidatePosterior:
    """候補 1 つの事後の重みと、候補の中の条件つきの見立て (重み 0 の候補は conditional=None。作らない、K37 決定 5)。"""
    candidate: str
    weight: _Fraction
    conditional: tuple[_Fraction, ...] | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class PoolBelief:
    """境目の並びの見立て (K37 決定 3〜5)。adoption・result はその並びの最新の採用 A* と結果 R* (最初の並びでまだ採用が
    無ければ None で、joint は宣言の事前・evidence_mass は 1)。joint は states の順の同時の信念。"""
    pool: Point
    adoption: Point | None
    result: Point | None
    joint: tuple[_Fraction, ...]
    evidence_mass: _Fraction
    candidates: tuple[CandidatePosterior, ...]


class CandidateInputError(ValueError):
    """候補を足す口の入力の誤り (α の範囲外・候補の形・知らない起動や境目・直和のモデルに表せない候補)。何も保存しない。"""

    def __init__(self, *, reason: str, field: str) -> None:
        super().__init__(f"{reason}: {field}")
        self.reason = reason
        self.field = field


class CandidatePoolError(RuntimeError):
    """並びやその見立てを解けない・読めない (K37 決定 3)。reason は理由の語、targets は名指しの Point、retryable は待てば
    解けるか (足した並びの作り直しの保存待ち = True。比べられない足し・読めない記録・止まった系列 = False)。前の並びへ
    黙って戻らない。"""

    def __init__(self, *, reason: str, targets: tuple[Point, ...], retryable: bool) -> None:
        super().__init__(f"{reason}: {', '.join(targets)}")
        self.reason = reason
        self.targets = tuple(targets)
        self.retryable = retryable


# --- 時刻を読む最初の本 (§6-10 K38): 固定の Poisson 源・取得区間の測定核・作り直せる信念 ---

class TimeBeliefError(ValueError):
    """時刻を読む信念の宣言・照会が通らない (紙 F-b K38)。kind: invalid (不正な宣言: 負の率・和が 1 でない事前・0 の単位など) /
    unsupported (この本が対応していない表し方・法則・一歩) / unavailable (まだ無い・読めない) / incomplete (予算の中で精度が
    届かない。モデルの誤りではない) / model_falsified (支えの条件から質量 0 が証明された)。targets は名指し (宣言の位置・候補の
    id・記録の Point)、field は欄の名前。"""

    def __init__(self, *, kind: str, reason: str, targets: tuple[str, ...] = (), field: str | None = None) -> None:
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason, self.targets, self.field = kind, reason, tuple(targets), field


def _exact(value, field, *, positive=False, integer=False) -> None:
    """K38 決定 1 の受け付ける数: 有理数は Fraction、時刻・件数は int (bool 不可)。別の表し方は unsupported、範囲の外は invalid。"""
    kind = int if integer else _Fraction
    if type(value) is not kind:
        raise TimeBeliefError(kind="unsupported", reason=f"{field} must be an exact {kind.__name__}", field=field)
    if value < 0 or positive and value == 0:
        raise TimeBeliefError(kind="invalid", reason=f"{field} must be {'positive' if positive else 'non-negative'}",
                              field=field)


def _distribution(states, prior, field) -> None:
    if type(states) is not tuple or not states or any(type(s) is not str for s in states) or len(set(states)) != len(states):
        raise TimeBeliefError(kind="invalid", reason="states must be distinct names", field="states")
    if type(prior) is not tuple or len(prior) != len(states):
        raise TimeBeliefError(kind="invalid", reason=f"{field} needs one weight per state", field=field)
    for p in prior:
        _exact(p, field)
    if sum(prior) != 1:
        raise TimeBeliefError(kind="invalid", reason=f"{field} must sum to 1", field=field)


# 時計の部品の値の宣言の形 (K40 決定 4): 欄の名前 → 種類の名前 (str)・有理数・区切りの数ごとの点 ((m, (値, …)), …)
ClockValue: _TypeAlias = str | _Fraction | tuple[tuple[int, tuple[_Fraction, ...]], ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockPrior:
    """時計の部品の最初の見込み (紙 F-b K40 決定 1・2・4)。共同の事前は宣言した因子の積だけ: 周期 T の有限の候補 periods
    ((T, 事前の重み), …、T は正の有理数で法則の時間の単位)・区切りの数 m の候補 segments ((m, 事前の重み), …、2 ≤ m ≤
    max_segments)・回転 phase ({"kind": "uniform"} = [0, 1) の一様 / {"kind": "point", "value": 有理数} = 最初の区切りの左の
    境目)・幅 widths ({"kind": "symmetric_dirichlet", "concentration": κ_w} / {"kind": "point", "values": ((m, (w_1, …, w_m)), …)})・
    配分 fractions ({"kind": "conditional_dirichlet", "concentration": κ_f} = w が与えられた時の Dirichlet(κ_f w) / 点)。点の
    事前は宣言した区切りの数ごとに値を持つ。区切り j の上の倍率は f_j / w_j で、1 周の平均は 1。couplings は因子の積の外の依存の
    宣言 ((欄, 欄), …) で、この本では対応していない。値の正しさは候補の解決が名指して確かめる (宣言の事実は先に残す、P1)。"""
    periods: tuple[tuple[_Fraction, _Fraction], ...]
    max_segments: int
    segments: tuple[tuple[int, _Fraction], ...]
    phase: _Mapping[str, ClockValue]
    widths: _Mapping[str, ClockValue]
    fractions: _Mapping[str, ClockValue]
    couplings: tuple[tuple[str, str], ...] = ()


@_dataclass(frozen=True, slots=True, kw_only=True)
class SwitchPart:
    """スイッチの族の部品 1 つ (紙 F-b K39 決定 1・K40 決定 1)。id は族の部品の辞書の名前。部品の種類 kind は倍率が何を読むかで
    決まる: "mood" = 調子の部品 (multipliers は状態 S を読む倍率 r(S)、法則の states の順の非負の有理数)、"inert" = 何も読まない
    倍率 1 の部品 (multipliers は None か全部 1)、"clock" = 時計の部品 (倍率は時計の位置を読む。clock は最初の見込み
    `ClockPrior`、multipliers は空。状態を読む時計は候補の解決が対応していないと名指す)。ほかの kind は宣言として受け取り、この本では対応していない種類として候補の解決が名指して
    止まる (読み方の無い部品を無効果とみなさない、決定 2・11)。"""
    id: str
    kind: str
    multipliers: tuple[_Fraction, ...] | None = None
    clock: ClockPrior | None = None

    def __post_init__(self) -> None:
        if type(self.id) is not str or not self.id:
            raise TimeBeliefError(kind="invalid", reason="a part needs a name", field="id")
        if type(self.kind) is not str or not self.kind:
            raise TimeBeliefError(kind="invalid", reason="a part names what its multiplier reads", field="kind")
        if self.multipliers is not None:
            if type(self.multipliers) is not tuple:
                raise TimeBeliefError(kind="invalid", reason="multipliers must be a tuple", field="multipliers")
            for r in self.multipliers:
                _exact(r, "multipliers")
        if self.kind == "mood" and not self.multipliers:
            raise TimeBeliefError(kind="invalid", reason="a mood part reads one multiplier per state", field="multipliers")
        if self.kind == "inert" and self.multipliers is not None and any(r != 1 for r in self.multipliers):
            raise TimeBeliefError(kind="invalid", reason="an inert part has multiplier 1", field="multipliers")
        if (self.kind == "clock") != (type(self.clock) is ClockPrior):
            raise TimeBeliefError(kind="invalid", reason="a clock part reads the clock through its clock prior only",
                                  field="clock")


@_dataclass(frozen=True, slots=True, kw_only=True)
class PoissonLaw:
    """固定の Poisson 源とスイッチの族の法則 (K38 決定 1・K39 決定 1〜3。法則の形は 1 つ、K39-b R2): 静的な有限の状態 states・
    状態ごとの事前 prior・状態ごとの基準の率 rates (λ_0(S)、宣言した単位あたり)・起点 origin_ns (run の時計の ns)・起点で源に
    既にある件数 initial_count・時間の単位 time_unit (ns あたりの換算の係数、正)。経過時間は (ns − origin_ns) × time_unit で、
    段に丸めない。family は族の名前 (p の共有の範囲。None は族を宣言しない = K38 の部品 0 個の族で、parts は空・a・b は None)、
    parts は部品の辞書、a・b はスイッチの入る割合 p の事前 Beta(a, b) (族があれば正の有理数)、state_role は状態の役 ("mood" =
    S 全体が調子の役で、調子の遷移は無い)。スイッチの列 z の下の率は λ_0(S) · Π_{z_j = 1} r_j(S) で、時計の部品 (K40) が
    オンなら、さらに時計の位置 φ(t) = (t mod T)/T の倍率 c(φ) を掛ける。z の事前は (a)_m (b)_{k−m} / (a+b)_k (時計の周期の候補・
    区切りの数は k に足さない)。率は後で学べる量へ広げられる (この本では宣言の値)。"""
    run: Ref
    states: tuple[str, ...]
    prior: tuple[_Fraction, ...]
    rates: tuple[_Fraction, ...]
    origin_ns: int
    initial_count: int
    time_unit: _Fraction
    family: str | None = None
    parts: tuple[SwitchPart, ...] = ()
    a: _Fraction | None = None
    b: _Fraction | None = None
    state_role: str | None = None

    def __post_init__(self) -> None:
        if type(self.rates) is not tuple:
            raise TimeBeliefError(kind="invalid", reason="rates must be a tuple", field="rates")
        for rate in self.rates:
            _exact(rate, "rates")
        _exact(self.time_unit, "time_unit", positive=True)
        _exact(self.initial_count, "initial_count", integer=True)
        if type(self.origin_ns) is not int:
            raise TimeBeliefError(kind="invalid", reason="origin_ns must be an int of ns", field="origin_ns")
        _distribution(self.states, self.prior, "prior")
        if len(self.rates) != len(self.states):
            raise TimeBeliefError(kind="invalid", reason="rates need one rate per state", field="rates")
        if not isinstance(self.run, Ref):
            raise TimeBeliefError(kind="invalid", reason="run must be a Ref", field="run")
        if self.family is None:
            if self.parts != () or self.a is not None or self.b is not None:
                raise TimeBeliefError(kind="invalid", reason="parts and p need a declared family", field="family")
        else:
            if type(self.family) is not str or not self.family:
                raise TimeBeliefError(kind="invalid", reason="a family needs a name", field="family")
            _exact(self.a, "a", positive=True)
            _exact(self.b, "b", positive=True)
        if type(self.parts) is not tuple or any(type(x) is not SwitchPart for x in self.parts):
            raise TimeBeliefError(kind="invalid", reason="parts must be a tuple of switch parts", field="parts")
        if len({x.id for x in self.parts}) != len(self.parts):
            raise TimeBeliefError(kind="invalid", reason="part names must be distinct", field="parts")
        if any(x.multipliers and len(x.multipliers) != len(self.states) for x in self.parts):   # 空の組は状態を読まない
            raise TimeBeliefError(kind="invalid", reason="multipliers need one value per state", field="multipliers")
        if self.state_role is not None and (type(self.state_role) is not str or not self.state_role):
            raise TimeBeliefError(kind="invalid", reason="state_role must be a name", field="state_role")


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteCountLaw:
    """旧い有限の法則の時刻つきの一例 (K38 決定 7): 決まった時刻 positions_ns に高々 1 件ずつ届く。paths は各時刻に届くか
    (0/1) の組、weights_by_state は状態ごとの組の重み (和 1)。CE1 の 8 通りの表はこの形で新しい口を通る。"""
    run: Ref
    states: tuple[str, ...]
    prior: tuple[_Fraction, ...]
    origin_ns: int
    initial_count: int
    positions_ns: tuple[int, ...]
    paths: tuple[tuple[int, ...], ...]
    weights_by_state: tuple[tuple[_Fraction, ...], ...]

    def __post_init__(self) -> None:
        _exact(self.initial_count, "initial_count", integer=True)
        if type(self.origin_ns) is not int:
            raise TimeBeliefError(kind="invalid", reason="origin_ns must be an int of ns", field="origin_ns")
        _distribution(self.states, self.prior, "prior")
        if type(self.positions_ns) is not tuple or any(type(p) is not int for p in self.positions_ns) \
                or list(self.positions_ns) != sorted(set(self.positions_ns)):
            raise TimeBeliefError(kind="invalid", reason="positions must be increasing ns", field="positions_ns")
        if type(self.paths) is not tuple or not self.paths or len(set(self.paths)) != len(self.paths) or any(
                type(p) is not tuple or len(p) != len(self.positions_ns) or any(x not in (0, 1) or type(x) is not int
                                                                              for x in p) for p in self.paths):
            raise TimeBeliefError(kind="invalid", reason="paths must be distinct 0/1 rows", field="paths")
        if type(self.weights_by_state) is not tuple or len(self.weights_by_state) != len(self.states):
            raise TimeBeliefError(kind="invalid", reason="one weight row per state", field="weights_by_state")
        for row in self.weights_by_state:
            if type(row) is not tuple or len(row) != len(self.paths):
                raise TimeBeliefError(kind="invalid", reason="one weight per path", field="weights_by_state")
            for w in row:
                _exact(w, "weights_by_state")
            if sum(row) != 1:
                raise TimeBeliefError(kind="invalid", reason="path weights must sum to 1", field="weights_by_state")


@_dataclass(frozen=True, slots=True, kw_only=True)
class UniformAcquisitionTime:
    """取得区間の測定核 (K38 決定 3): 源が判定した時刻 U は記録されないので、U を [before, after] の一様分布とする (幅 0 なら
    点)。数学を閉じるための明示した測定モデルで、実機の内部時刻の事実ではない。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class FixedAcquisitionSchedule:
    """区間の端点を条件にして読む根拠 (K38 決定 3): 取得の区間 [before, after] (run の時計の ns) を前もって宣言した外から決まる
    予定。i 番目の取得の実際の区間がこの i 番目と一致する時だけ、端点を条件にして読む。"""
    run: Ref
    intervals: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        previous = None
        for item in self.intervals if type(self.intervals) is tuple else (None,):
            if type(item) is not tuple or len(item) != 2 or any(type(x) is not int for x in item) or item[0] > item[1] \
                    or previous is not None and previous > item[0]:
                raise TimeBeliefError(kind="invalid", reason="intervals must be ordered [before, after] ns pairs",
                                      field="intervals")
            previous = item[1]


@_dataclass(frozen=True, slots=True, kw_only=True)
class IndependentAcquisitionFailure:
    """状態と件数に依らない故障・接続の核 (K38 決定 2): 取得が unavailable になる確率。宣言した時だけ unavailable を読む。"""
    unavailable_probability: _Fraction

    def __post_init__(self) -> None:
        _exact(self.unavailable_probability, "unavailable_probability")
        if self.unavailable_probability > 1:
            raise TimeBeliefError(kind="invalid", reason="a probability is at most 1", field="unavailable_probability")


@_dataclass(frozen=True, slots=True, kw_only=True)
class IndependentSourceDisconnection:
    """状態と件数に依らない「つながっていない」の核 (K38-c ②・K38-d): coefficient c は 1 回の取得で源がつながっていない確率。
    取得の結果は 1 つの正規化された表 (つながっていない c / 呼んだ後の故障 (1−c)·p / taken・empty (1−c)·(1−p)·件数の核)。
    源が差されていない取得 (source_called = False) は宣言した時だけ読み、S の見立ては変えず、源の件数は after まで進める。
    呼んだ後の故障 (IndependentAcquisitionFailure) の確率は流用しない。"""
    coefficient: _Fraction

    def __post_init__(self) -> None:
        _exact(self.coefficient, "coefficient")
        if self.coefficient > 1:
            raise TimeBeliefError(kind="invalid", reason="the coefficient of a discrete observation is at most 1",
                                  field="coefficient")


@_dataclass(frozen=True, slots=True, kw_only=True)
class TimedAcquisitionModel:
    """`sui.fb.timed_acquisition_model/1` の値 (起動の宣言の observation_models の項、K38 決定 1〜3)。route_slot は同じ起動の口、
    law は件数の法則 (PoissonLaw / FiniteCountLaw。それ以外の法則の宣言は「この本では対応していない」で名指して止まる)、
    decision_time は取得区間の測定核、conditioning は端点を条件にする根拠、failure は呼んだ後の独立の故障の核 (None は
    呼んだ後の unavailable を読まない)、control_rule・control_independence は取りに行き方の制御の表と、選び方が状態に依存
    しない根拠 (K26 と同じ)、disconnection は源が差されていない時の独立の核 (None は読まない、K38-c ②)。"""
    route_slot: str
    law: PoissonLaw | FiniteCountLaw | MethodCall
    decision_time: UniformAcquisitionTime
    conditioning: FixedAcquisitionSchedule
    failure: IndependentAcquisitionFailure | None
    control_rule: MethodCall
    control_independence: MethodCall
    disconnection: IndependentSourceDisconnection | None = None

    def __post_init__(self) -> None:
        if self.disconnection is not None and type(self.disconnection) is not IndependentSourceDisconnection:
            raise TimeBeliefError(kind="invalid", reason="disconnection must be an independent disconnection law",
                                  field="disconnection")
        for name, kind in (("decision_time", UniformAcquisitionTime), ("conditioning", FixedAcquisitionSchedule)):
            if type(getattr(self, name)) is not kind:
                raise TimeBeliefError(kind="invalid", reason=f"{name} must be declared", field=name)
        if self.failure is not None and type(self.failure) is not IndependentAcquisitionFailure:
            raise TimeBeliefError(kind="invalid", reason="failure must be an independent failure law", field="failure")


@_dataclass(frozen=True, slots=True, kw_only=True)
class SourceCountReading:
    """一歩が源の件数とどう関わるかの宣言 (K38 決定 9・K38-c ③)。independent_of_count は「結果が S を条件に源の件数と
    独立」の宣言、count_shift は一歩が件数を動かす量。行列の値は持たない (結果の確率の出どころはモデルの核の 1 か所)。
    independent_of_count が真で count_shift = 0 の時だけ E_y(s) ⊗ I_N の形と宣言されている。"""
    independent_of_count: bool
    count_shift: int

    def __post_init__(self) -> None:
        if type(self.independent_of_count) is not bool:
            raise TimeBeliefError(kind="invalid", reason="independent_of_count must be a bool",
                                  field="independent_of_count")
        if type(self.count_shift) is not int:
            raise TimeBeliefError(kind="invalid", reason="count_shift must be an int", field="count_shift")


@_dataclass(frozen=True, slots=True, kw_only=True)
class TimedExecutionDeclaration(ExecutionDeclaration):
    """`sui.fb.timed_execution_declaration/1`: 行う一歩の宣言 (K36) に、核 id → 源の件数の読み (SourceCountReading) を足したもの。
    時刻を読む信念と一緒に通す一歩は、この読みが E_y(s) ⊗ I_N の形と確かめられるものだけ (K38 決定 9)。"""
    source_readings: _Mapping[str, SourceCountReading]


@_dataclass(frozen=True, slots=True, kw_only=True)
class BeliefExpression:
    """採用された時刻を読む信念の正本の名指し (K38 決定 5)。point は正本を保存した記録 (結果 R*)、root は法則・事前・測定核・
    使った原記録と適用の順から決まる正準な根 (精度に依らない)、model・pool は並びのモデルと並びの記録、adoption・result は
    採用 A* と結果 R*、observations は適用した原記録 (取得の Frame・一歩の結果のメモ) の Point の順、terminal_ns は信念の時刻。"""
    point: Point
    root: str
    model: Point
    pool: Point
    adoption: Point | None
    result: Point | None
    observations: tuple[Point, ...]
    terminal_ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class BeliefQuantity:
    """照会する量 (K38 決定 5): state = P(S=state | h) (周辺。candidate を名指すと invalid)、candidate = P(M=candidate | h)、mass = 証拠の質量 Z、count = P(N=count
    [, S=state, M=candidate] | h) (信念の時刻の源の総件数。at_least なら N ≥ count)。"""
    kind: _Literal["state", "candidate", "mass", "count"]
    state: str | None = None
    candidate: str | None = None
    count: int | None = None
    at_least: bool = False


@_dataclass(frozen=True, slots=True, kw_only=True)
class SwitchQuantity:
    """スイッチと p の照会する量 (紙 F-b K39 決定 6)。候補 candidate と族 family を名指し、候補 M に条件づけた値を返す (並び全体の
    共同の確率は BeliefQuantity の candidate の照会と掛けて作る。1 つの照会で混ぜない)。on・off は部品の名前の組で、スイッチの列の
    部分的な条件 (on は 1、off は 0)。kind: switch = P(on・off | h, M) (1 つならオンの確率、複数なら同時の確率)、state =
    P(on・off, S=state | h, M)、mass = P(h | M)、p_mean = E[p | h, M]、p_moment = E[p^order | h, M] (order は非負の整数)。
    p_cdf・p_quantile (点 point での p の累積確率・分位点) はこの本では対応していない (名指して断る)。時計の照会は
    `ClockQuantity`。"""
    kind: _Literal["switch", "state", "mass", "p_mean", "p_moment", "p_cdf", "p_quantile"]
    candidate: str
    family: str
    on: tuple[str, ...] = ()
    off: tuple[str, ...] = ()
    state: str | None = None
    order: int | None = None
    point: _Fraction | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockQuantity:
    """時計の照会する量 (紙 F-b K40 決定 15、K39 決定 6 の照会の決まりのまま): 候補 candidate・族 family・時計の部品 part を名指し、
    値は候補 M に条件づけ、分母はいつも候補 M の証拠 Z_M。kind: parameters = P(T ∈ periods, m ∈ segments, on・off | h, M)
    (periods・segments は宣言した候補の部分集合、None は全部、空の組は空の事象。on・off は分子の事象だけ。時計のオフの枝の T・m
    は潜在で事前のまま) / allocation = E[∫_[lower, upper) c_θ(φ)^{z_時計} dφ | h, M] (端は [0, 1) の有理数、lower > upper は 1 周を
    またぐ [lower, 1) ∪ [0, upper)。時計のオフの枝は区間の長さ)。回転・幅・配分の領域の確率 (kind phase・width・fraction、index は
    区切りの番号) と分母を変える条件 (condition_on・condition_off) は、この本では対応していない (名指して断る)。"""
    kind: _Literal["parameters", "allocation", "phase", "width", "fraction"]
    candidate: str
    family: str
    part: str
    periods: tuple[_Fraction, ...] | None = None
    segments: tuple[int, ...] | None = None
    index: int | None = None
    lower: _Fraction | None = None
    upper: _Fraction | None = None
    on: tuple[str, ...] = ()
    off: tuple[str, ...] = ()
    condition_on: tuple[str, ...] = ()
    condition_off: tuple[str, ...] = ()


@_dataclass(frozen=True, slots=True, kw_only=True)
class BeliefValue:
    """照会の答え (K38 決定 5・P10): 真の値を含む有理数の上下界。exact は正準な式が有理数の時のその値 (そうでなければ None)、
    proof は使った精度の控え (検査は根から作り直して行い、控えを信じない)。"""
    root: str
    quantity: BeliefQuantity | SwitchQuantity | ClockQuantity
    lower: _Fraction
    upper: _Fraction
    exact: _Fraction | None
    proof: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class BetaMixtureComponent:
    """p の混合の 1 成分 (K39 決定 6): スイッチの列 z の枝の Beta(a, b) = Beta(族の a + |z|, 族の b + k − |z|) と、その重み weight
    (= P(z | h, M) の照会の答え。quantity はその枝の on・off を名指した switch の照会)。"""
    a: _Fraction
    b: _Fraction
    weight: BeliefValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class BetaMixture:
    """候補 M に条件づけたスイッチの入る割合 p の分布の、作り直せる混合の表現 (K39 決定 6): 根 root・候補 candidate・族 family・
    部品の辞書 parts (宣言の順の名前)・事前 a, b と、スイッチの列ごとの成分 components (2^k 個、z の辞書順。同じ形の成分は
    p だけの照会ではまとめて読んでよい)。重みの数は根から作り直した照会の答えで、`FThreadHost.verify_p_distribution` は保存した
    自己申告を信じず根から確かめる。proof は控え。"""
    root: str
    candidate: str
    family: str
    parts: tuple[str, ...]
    a: _Fraction
    b: _Fraction
    components: tuple[BetaMixtureComponent, ...]
    proof: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedCandidate:
    """候補の解決 (K39 決定 8) が返す候補 1 つの正準な記述: 名前 id・展開した状態 states (スイッチの列 z × 宣言のモデルの状態。
    部品 0 個なら宣言のモデルの状態のまま)・候補の中の事前 prior (P(z) × 状態の事前、和 1)・状態ごとの率 rates (z を当てた後の
    率。Poisson の族でない法則は None)・物語の対応 correspondence・知る対象への写像 knowledge_targets (「解決した率の表の識別 /
    元の知る対象」。部品 0 個なら元の知る対象)・要る参照 references・時計 clocks (K40: 展開した状態ごとに、時計のオフは None、
    オンは (周期 T, ((区切りの始まりの位置 ∈ [0, 1), 倍率), …)) で、率はこの倍率を掛ける前の率。回転・幅・配分のどれかが連続の
    事前の枝は (周期 T, ()) で、形は θ の積分で読む (時計の照会は `ClockQuantity`)。Poisson の族でない法則は
    None)。"""
    id: str
    states: tuple[str, ...]
    prior: tuple[_Fraction, ...]
    rates: tuple[_Fraction, ...] | None
    correspondence: tuple[tuple[str, str], ...]
    knowledge_targets: tuple[str, ...]
    references: frozenset[Point]
    clocks: tuple[tuple[_Fraction, tuple[tuple[_Fraction, _Fraction], ...]] | None, ...] | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedBeliefPool:
    """`resolve_belief_candidates` の答え: 並びのモデルの document (ホストが保存した並びのモデルの document と同じ)・候補の記述の
    列 candidates (並びの順)・要る参照 references。"""
    document: ImmutableJSON
    candidates: tuple[ResolvedCandidate, ...]
    references: frozenset[Point]


def resolve_belief_candidates(declaration: Point, *, reader, registry: FRegistry) -> ResolvedBeliefPool:
    """保存した起動の宣言か並びの記録 declaration から、候補の並びを読むだけで解く (K39 決定 8)。reader は record(Point) で記録を
    返す読み手 (無ければ KeyError)。ホスト (`_fb_pool`) と入口 U が使う 1 か所の解決 (`f_update2.describe_candidate`) と同じ答え。
    何も書かない。この本で読めない候補 (対応していない部品・法則) は TimeBeliefError(unsupported、名指しは候補と部品の名前)、
    読めない記録は TimeBeliefError(unavailable / invalid)。registry は署名の互換のために受け取る (解決には使わない)。"""
    from ._fb_time import resolve_public
    return resolve_public(reader, declaration)


@_dataclass(frozen=True, slots=True, kw_only=True)
class SelectionValues:
    """選択が使った評価の値の保証つきの照会 (K38 決定 5): 候補ごとの情報量・G・方策の確率の有理数の上下界。belief_root は
    その評価が使った信念の根。"""
    belief_root: str
    candidates: tuple[str, ...]
    information: tuple[RationalInterval, ...]
    G: tuple[RationalInterval, ...]
    probabilities: tuple[RationalInterval, ...]
    proof: ImmutableJSON


def read_acquisition_sequence(records: _Mapping[Point, Record], *, model: Point, run: Ref, route_epoch: str,
                              through_seq: int) -> AcquisitionReadResult:
    """取得の列を読む口 (§6-10 K26 (2)(c)・K26-a (イ))。records は読み手の範囲の Point → Record、model は保存した観測モデルの
    記録の Point。run・route_epoch・sample_seq の 0 から through_seq までの取得の Frame (K25) を全部そろえて観測の列に読み、
    初期の状態ごとの L(d|u,s0) を Fraction で厳密に返す。純粋な関数で、台帳に何も書かず、ホストの状態を読まない。
    子の見立ては変えない (③ の仕事)。"""
    from ._fb_read import read
    return read(records, model=model, run=run, route_epoch=route_epoch, through_seq=through_seq)


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
    M の読みとともに記録する。monitored(interval) は係が渡した区間の控えを報告と別の道で
    ホストに残す (IntervalObservation。ホストは区間を確かめない。取りに行きの道はこれを使わない、K28 の B3')。どちらも窓口の状態を変えず、記録を保存しない。
    開始の札を取っていない口の read・monitored は RuntimeError で、証拠に足さない (§6-10 J8・K11)。
    係の本体が戻った後の口の read・monitored・acquire も RuntimeError で、証拠に足さない (K29。境目は read が使用を足す時、
    monitored が区間を足す時、acquire が源を読む前の準備。境目を通った acquire は結果を公開する。post・now は変えない)。
    reader() はその仕事の Desc の numerical_view の境界と input_points の閉包だけを読む不変の読み手
    (像の外を読ませない、§6-9 H5)。numerical_view も input_points も無い仕事では None。
    prepared() は評価 Ee の args.prepared (PR) と全照合した、評価の準備 Ep の生きた
    FMathArtifact[FProblem]。ほかの仕事・照合できない時は None。P の辞書や任意の発行物を取る口ではない。
    now() はホストが今の M を読み、発行済みの時計の出どころの Point とまとめて返す (K23)。acquire() は測る仕事の口だけが
    呼べ、ホストがその口の源へ次の番号の 1 件を取りに行く (K23)。取得の結果の Frame (taken・empty・unavailable の
    どれでも 1 つ、測り方 acquisition_result_sampling/1) と、取れた時の原文を、ホストが同じ操作の中で受信の列へ入れ、
    その操作の観測は evidence() の sources に残る (K25)。どちらも開始の札を取っていない口では RuntimeError。
    perform(execution) は一歩を行う仕事の口だけが呼べ (K36 決定 3)、渡す E はその仕事の要求の E と全く同じでなければ
    FbInputError (選ばれていない操作・別の選択の E では行わない)。家の人が宣言を見て、宣言した無作用なら外を呼ばずに完了を、
    行える観測の一歩なら入口で受け取った環境の相手を呼んで、結果のメモ (`sui.fb.execution_result/1`) を家の人自身が残す。
    行う所が未接続・相手が無い時は呼ばずに名指しして残す。返値は ExecutionResult。"""

    def enter(self) -> bool: ...

    def perform(self, execution: "ExecutionArgs") -> ExecutionResult: ...

    def now(self) -> ReadingClock: ...

    def acquire(self) -> Acquisition: ...

    def read(self, point: Point) -> bytes: ...

    def monitored(self, interval: MeasurementInterval) -> None: ...

    def reader(self) -> FReader | None: ...

    def prepared(self) -> FMathArtifact | None: ...

    def post(self, event: FEvent, issued: FMathArtifact | IssuedUpdate | None = None) -> None: ...

    def evidence(self) -> TargetEvidence: ...


class FWorkers(_Protocol):
    """仕事の本体を走らせる係。本体の束ね `WorkerBundle` が用途ごとの係へ振り分ける (K30。誕生の入口 `start` が本体の
    係 7 用途で組む、K36。低い水準のホストは使う側が組む)。run はホストのスレッドで呼ばれ、
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
                 registry: FRegistry, launcher: FLauncher | None = None,
                 sources: _Mapping[str, FSource] | None = None,
                 actors: _Mapping[str, FActor] | None = None) -> None:
        """launcher=None は OS のスレッドで起動する本番の起動係 (threading.Thread.start の成否で
        launched / not_started、start が戻らず分からない時は unknown)。sources は口の源 (route_epoch → FSource、K23)。
        None や、口の route_epoch が無い時、その口の acquire() は unavailable を返す。actors は環境の相手 (名前 → FActor、
        K36)。行う一歩の宣言が名指す相手が無ければ、その一歩は「行っていない」と記録される (K36-a (エ))。"""
        from . import _fb_core
        self._state = _fb_core.State(ledger=ledger, clock=clock, workers=workers, registry=registry,
                                     launcher=launcher if launcher is not None else _fb_core.ThreadLauncher(),
                                     sources=sources, actors=actors)
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

    def keep_running(self, done: _Callable[[FStatus], bool], *, timeout: float) -> bool:
        """もう一度回す役 (§6-10 K16)。run_until と同じ 1 周 (受付 → settle → 仕事の開始 → done(status)) を回す。
        周の中でホストが行った置き場の操作が失敗した時 (OSError・sqlite3.Error をその操作の所で観測) は、窓口の状態を
        そのままに、同じ準備のまま次の周で入り直す。列の封筒の外側の形がおかしい時 (受付が FbInputError(reason="shape"))
        は、その封筒を断って列から外し (記録も預かりも作らない)、止まらずに後ろの封筒へ進む (K17)。それ以外の例外ではホストを止めて FHalted を上げる (元の例外が
        原因)。KeyboardInterrupt・SystemExit、done と status の例外はそのまま上げる。期限は入口で 1 回だけ決め、
        中断で延ばさない。回数・時間の固定の上限は無い。False は期限まで done が真にならなかったことだけ
        (仕事の失敗・目的の放棄・再実行の許可ではない)。起きた中断は interruptions() に残る。"""
        from . import _fb_core
        return _fb_core.keep_running(self, done, timeout)

    def interruptions(self) -> tuple[Interruption, ...]:
        """回す役まで上がった中断の列 (古い順)。「繰り返している」は最後の中断の count が増え続けること、「戻れた」は
        その後に done が真になる・新しい記録が保存されることで見分ける。"""
        with self._state.lock:
            return tuple(self._state.interruptions)

    @property
    def halted(self) -> Interruption | None:
        """止まったホストの理由。動いている時は None。"""
        return self._state.halted

    def add_candidate(self, *, boot: Point, candidate: BeliefCandidate, alpha: _Fraction,
                      boundary: frozenset[Point] | None = None) -> CandidateAddition:
        """候補を 1 つ足す口 (紙 F-b K37 決定 2・8)。boot は起動の宣言の Point、alpha は新しい並びの起点での新しい候補の
        事前確率 (0 < α < 1、呼ぶ者が明示して渡す。前からの候補の起点の重みは一律 (1−α) 倍)、boundary は前の並びを解く
        因果の境目 (保存済みの点の集合。None は今の置き場の頭)。入力の誤りは何も保存せずに CandidateInputError、前の
        並びを解けなければ CandidatePoolError。足したことは観測に数えず、見立ての作り直しは更新の計画が行う。"""
        from . import _fb_pool
        return _fb_pool.add(self._state, boot, candidate, alpha, boundary)

    def belief_pool(self, *, boot: Point, boundary: frozenset[Point] | None = None) -> BeliefPool:
        """境目で効いている並び (K37 決定 3)。仕事を進めず、記録を足さない。"""
        from . import _fb_pool
        return _fb_pool.belief_pool(self._state, boot, boundary)

    def pool_belief(self, *, boot: Point, boundary: frozenset[Point] | None = None) -> PoolBelief:
        """境目の並びの見立て (K37 決定 3〜5)。仕事を進めず、記録を足さない。解けない・読めない・止まった時は
        CandidatePoolError (待てば解けるかは retryable)。"""
        from . import _fb_pool
        return _fb_pool.pool_belief(self._state, boot, boundary)

    def belief_expression(self, *, boot: Point, boundary: frozenset[Point] | None = None) -> BeliefExpression:
        """境目の並びの最新の採用が持つ、時刻を読む信念の正本の名指し (紙 F-b K38 決定 5)。仕事を進めず、記録を足さない。
        まだ採用が無い・系列が止まった・時刻を読む信念でない時は TimeBeliefError。"""
        from . import _fb_time
        return _fb_time.belief_expression(self._state, boot, boundary)

    def query_belief(self, *, belief: BeliefExpression, quantity: BeliefQuantity, budget: RateBudget) -> BeliefValue:
        """正本から作り直した量の、精度 budget.tolerance 以下の幅の有理数の上下界 (K38 決定 5・P10)。"""
        from . import _fb_time
        return _fb_time.query_belief(self._state, belief, quantity, budget)

    def query_switch_belief(self, *, belief: BeliefExpression, quantity: SwitchQuantity,
                            budget: RateBudget) -> BeliefValue:
        """スイッチと p の照会 (K39 決定 6): 候補 M に条件づけた値を、精度 budget.tolerance 以下の有理数の上下界で返す。"""
        from . import _fb_time
        return _fb_time.query_switch(self._state, belief, quantity, budget)

    def query_clock_belief(self, *, belief: BeliefExpression, quantity: ClockQuantity,
                           budget: RateBudget) -> BeliefValue:
        """時計の照会 (K40 決定 15): 候補 M に条件づけた値を、精度 budget.tolerance 以下の有理数の上下界で返す。"""
        from . import _fb_time
        return _fb_time.query_clock(self._state, belief, quantity, budget)

    def p_distribution(self, *, belief: BeliefExpression, candidate: str, family: str,
                       budget: RateBudget) -> BetaMixture:
        """候補 candidate の族 family のスイッチの入る割合 p の、候補に条件づけた分布の作り直せる混合の表現 (K39 決定 6)。"""
        from . import _fb_time
        return _fb_time.p_distribution(self._state, belief, candidate, family, budget)

    def verify_p_distribution(self, *, belief: BeliefExpression, distribution: BetaMixture) -> bool:
        """混合の表現が信念の根から作り直した混合と同じ成分を持ち、各重みの上下界が真の値を含むか (自己申告を信じない)。"""
        from . import _fb_time
        return _fb_time.verify_p_distribution(self._state, belief, distribution)

    def query_selection(self, *, selection: Point, budget: RateBudget) -> SelectionValues:
        """選択が使った評価の値 (情報量・G・方策の確率) の保証つきの照会 (K38 決定 5)。"""
        from . import _fb_time
        return _fb_time.query_selection(self._state, selection, budget)

    def verify_belief_value(self, *, belief: BeliefExpression, value: BeliefValue) -> bool:
        """保存した数の答えを、根から作り直して確かめる (区間の重なりでなく、真の値を含むか)。"""
        from . import _fb_time
        return _fb_time.verify_belief_value(self._state, belief, value)

    def same_belief(self, *, left: BeliefExpression, right: BeliefExpression) -> bool:
        """2 つの名指しが同じ信念か (精度に依らない正準な根で決める)。"""
        from . import _fb_time
        return _fb_time.same_belief(self._state, left, right)

    def rebuild_window(self) -> FWindow:
        """同じプロセスの中で窓口を作り直して返す (M2)。H・P・C・E と動いている係はそのまま。
        Boot・Post・くじの消費・再入場・占有の解放をしない。新旧 2 つを同時に有効にしない。"""
        with self._state.lock:
            self._window = FWindow(self)
            return self._window


class SourceMeasurer:
    """本体の測る係 (§6-10 K23・K25・K27)。測る仕事の本体で、要求の取りに行き方 (`SegmentArgs.repeat`) が
    「済んだら次」(`sui.fb.acquisition_repeat_when_done/1`、args は {}) の時、止める合図まで口の源へ取りに行きを
    くり返す。入場 → Started → [開始受付 → acquire()] をくり返す (取得の結果の Frame と原文は、仲立ちしたホストが
    acquire の中で預ける。係は Frame を出さない。結果によらず同じ取りに行き方で、待ち・周期・回数の上限を置かない)
    → 最後の回の after から止まるまでの区間は CoverageUnproved (見張っていない間を「来なかった」にしない) → Ended。

    開始受付 (K27 新しい決定 5): 係の鍵の下で止める合図が無いことを確かめてこの回を始めると決め、acquire() を
    呼ぶ前に鍵を放す (返らない read の間も stop() は合図を立てられる)。合図の後に開始受付される回は無い。始めた回は
    決着まで待ち、その結果を残す。扱えない取りに行き方は、入場して取りに行かずに Ended (unsupported_repeat) で
    終わる (断って pending へ戻すと起こし直しが続く、決定 4)。acquire() の例外 (止まったホスト・家の人の中の
    失敗) は偽りの結果にせず上げて、係はそこで止まる (決定 6・7)。測る仕事以外は TypeError
    (ほかの仕事の係と束ねるのは `WorkerBundle`)。"""

    def __init__(self) -> None:
        from threading import Lock
        self._gate = Lock()       # 開始受付の境界 (止める合図と同じ鍵)
        self._stopping = False

    def stop(self) -> None:
        with self._gate:
            self._stopping = True

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        import json
        from collections.abc import Mapping
        from . import fb_contracts as c
        if not isinstance(work, MeasureSegment):
            raise TypeError("SourceMeasurer runs measuring works only")
        if not ctx.enter():
            return

        def report(slot: str, item: "SegmentItem") -> None:
            ctx.post(SegmentReport(segment=work.request, item_slot=slot, item=item))

        def route_epoch() -> int:
            # 公開の取得が無い時: 要求の route が指す保存済みの設定を公開の read で読む (決定 4)
            return json.loads(ctx.read(work.desc.args.route))["config"]["route_epoch"]

        work_id = work.desc.work_id
        started = ctx.now()
        report("started", SegmentBoundary(kind="started", work=work_id, reading=started, reason="entered",
                                          evidence=()))
        repeat = work.desc.args.repeat
        supported = (repeat.contract == c.ACQUISITION_REPEAT_WHEN_DONE
                     and isinstance(repeat.args, Mapping) and not repeat.args)
        last, epoch = started, None
        while supported:
            with self._gate:          # 開始受付
                if self._stopping:
                    break
            taken = ctx.acquire()     # 鍵の外で (始めた回は決着まで)
            last, epoch = taken.after, taken.route_epoch
        ended = ctx.now()
        report("unproved", CoverageUnproved(
            route_epoch=route_epoch() if epoch is None else epoch,
            interval=MeasurementInterval(clock=last.reading.run, start_ns=last.reading.time_ns,
                                         end_ns=ended.reading.time_ns, closure="(start,end]"),
            missing_contracts=(c.NO_ARRIVAL,), evidence=()))
        report("ended", SegmentBoundary(kind="ended", work=work_id, reading=ended,
                                        reason="stopped" if supported else "unsupported_repeat", evidence=()))


class FiniteUpdater:
    """`FWorkers` の「見立てを直す」仕事の本体 (紙 F-b §6-10 K24、ゆうの決定 Z48)。

    ホストが出した信念の更新の仕事 (`Compute`、`desc.purpose == "belief_update"`) を受け、その口の固定の
    範囲を読み手にして入口 U (`f_update2.compute_finite_update`) を呼び、返答をその仕事の口から
    `WorkFinished` で返す。発行 (issued) の時だけ、発行物を口へ添える。不適合 (rejected)・不足 (insufficient) は
    U の返答のまま運ぶ。U の実行が例外で続けられなかった時は失敗 (`WorkFailure`) として返し、不適合・不足・発行と
    取り違えない。失敗の中身は例外の型の名前と、U の入口が自分で上げた入力の誤りの時だけその閉じた一覧の理由の語と欄
    (`f_update2._failure_content`、K28-a (ウ))。例外の自由な文は載せない。完成した joint を外から受け取らない。

    `registry` は、組み立てる側がホストへ渡したものと同じ `FRegistry` を明示して渡す (係の中で作らない)。
    見立てを直す仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。読める報告の種類はこの係では増えない。"""

    _entry = "compute_finite_update"   # 呼ぶ入口 U の版 (時刻を読む版は TimedBeliefUpdater)

    def __init__(self, *, registry: FRegistry) -> None:
        self._registry = registry

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        from . import f_update2 as _u
        if not isinstance(work, Compute) or work.desc.purpose != "belief_update":
            raise TypeError(type(self).__name__ + " runs belief_update works only")
        if not ctx.enter():
            return

        def reading() -> ReadingEvidence:
            try:
                return ctx.now()
            except RuntimeError:   # 時計の出どころを名指せない: 読みを作らず、理由を残して続ける
                return Unavailable(reason="clock_source_unavailable", basis=())

        started = reading()
        issued, error = None, None   # error は失敗の中身 (dict)
        try:
            reader = ctx.reader()
            if reader is None:
                raise RuntimeError("this work port has no fixed reader")
            returned = getattr(_u, self._entry)(work.request, reader=reader, registry=self._registry,
                                                evidence=ctx.evidence())
            outputs = _u.update_response(returned)
            issued = returned if isinstance(returned, IssuedUpdate) else None
        except Exception as exc:   # 実行の障害。U が返した不適合・不足とは別の枝で返す
            error = _u._failure_content(exc)
        finished = reading()
        if error is None:
            outcome: WorkOutcome = WorkOutputs(outputs=outputs)
        else:
            outcome = WorkFailure(failure=FailureInfo(
                failure_kind="execution_error", content=error,
                readings=(started, finished), basis=()))
        ctx.post(WorkFinished(work=work.desc.work_id, started=started, finished=finished, outcome=outcome),
                 issued=issued)


class TimedBeliefUpdater(FiniteUpdater):
    """`FWorkers` の「見立てを直す」仕事の、時刻を読む版の本体 (紙 F-b K38)。FiniteUpdater と同じ形で、入口 U の時刻を読む版
    (`f_update2.compute_timed_update`) を呼ぶ。取りに行きの列を宣言した件数の法則・取得区間の測定核・経過時間込みで条件づけ、
    作り直せる信念の正本を発行する。旧い有限の系列の要求は入口が断る (版を混ぜない)。"""

    _entry = "compute_timed_update"


class WorkerBundle:
    """係の束ね (紙 F-b §6-10 K30、Z51 ②)。用途 (`Stage`) → 係 の対応を作る時に受け取り、仕事の `desc.purpose` で
    係を 1 人選んで、同じ (work, ctx) で `run` を 1 回呼ぶ。`FWorkers` を満たす。

    作る時に用途の 7 つ (K36 で「一歩を行う」を足した) 全部がちょうどそろっていなければ ValueError (欠け・余りを名指す)、係に呼べる `run` が無ければ
    TypeError。係がその用途を扱えるかは確かめない (書き間違えると係が入場前に断り、起こし直しが続く = K30 (4))。
    同じ係を幾つの用途に書いてもよい。受け取った対応は写して持ち、作った後は変えない。束ね自身は入場せず
    (`ctx.enter()` を呼ばない)、口のどの操作も呼ばず、係の戻りと例外をそのまま通す。"""

    def __init__(self, workers: _Mapping[Stage, FWorkers]) -> None:
        from typing import get_args
        stages = get_args(Stage)
        table = dict(workers)
        missing = [s for s in stages if s not in table]
        extra = [k for k in table if k not in stages]
        if missing or extra:
            raise ValueError(f"WorkerBundle needs exactly one worker per purpose: missing {missing}, extra {extra}")
        for stage, worker in table.items():
            if not callable(getattr(worker, "run", None)):
                raise TypeError(f"WorkerBundle: the worker for {stage!r} has no callable run")
        self._workers = table

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        return self._workers[work.desc.purpose].run(work, ctx)


class CandidateGenerator:
    """`FWorkers` の「候補を並べる」仕事の本体 (紙 F-b §6-10 K31、Z51 ②・Z58)。

    ホストが出した候補の生成の仕事 (`Compute`、`desc.purpose == "candidate_generation"`) を受ける。知っている並べ方は
    `sui.fb.model_operations/1` (args は空の対応) の 1 つだけ (紙 F-b H9): モデルの記録を仕事の口の `read` で読み、
    `document.operations` の `id` をその順で候補の宣言 (`FCandidateDeclaration`、measure = counting/1、draws なし、
    continuation は全候補 policy なし) にして `WorkFinished` で返す。操作が 0 個なら no_candidates。
    知らない並べ方は `WorkFailure` (`unsupported_method`)、モデルが読めない・形が違う時は `WorkFailure` (`execution_error`、
    例外の型の名前だけ)。空の一覧や no_candidates にしない。始めと終わりの読みは別々に取る (時計の出どころを名指せない時は
    Unavailable)。候補の宣言を作り直して比べるのはホストの仕事ではない (Z58)。
    候補を並べる仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。"""

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        import json
        from . import f as _f
        from . import fb_contracts as c
        if not isinstance(work, Compute) or work.desc.purpose != "candidate_generation":
            raise TypeError("CandidateGenerator runs candidate_generation works only")
        if not ctx.enter():
            return

        def reading() -> ReadingEvidence:
            try:
                return ctx.now()
            except RuntimeError:   # 時計の出どころを名指せない: 読みを作らず、理由を残して続ける (K24 と同じ)
                return Unavailable(reason="clock_source_unavailable", basis=())

        desc, args = work.desc, work.desc.args
        started = reading()
        value, failure = None, None   # failure = (failure_kind, content)
        if desc.method != c.MODEL_OPERATIONS or not isinstance(args.generator_args, _Mapping) or args.generator_args:
            failure = ("unsupported_method", {"method": {"name": desc.method.name, "version": desc.method.version}})
        else:
            # モデルの取得・解析・宣言を作る所の例外は型を問わず失敗にする (K31-DC-02。係の run の中では本体が
            # 戻っていないので K29 の断りは起きず、read の RuntimeError は台帳や時計から来うる)
            try:
                data = ctx.read(args.model)
            except Exception as exc:   # 帳面から読めない
                failure = ("execution_error", {"error_type": type(exc).__name__})
            if failure is None:
                try:
                    operations = json.loads(data)["document"]["operations"]
                    if not isinstance(operations, list):   # {} や "" を「操作 0 個」と読まない (K31-R1)
                        raise TypeError("model operations is not a list")
                    order = tuple(op["id"] for op in operations)
                    if any(not isinstance(name, str) for name in order) or len(set(order)) != len(order):
                        raise ValueError("model operations are not distinct names")
                    value = {"kind": "no_candidates", "value": {}} if not order else {
                        "kind": "candidates", "value": _f._encode(_f.FCandidateDeclaration(
                            model=args.model, input_order=order,
                            measure=_f.CandidateMeasureRef(name="counting", version="1", args={}),
                            generation=_f.FCandidateGeneration(generator=desc.method, args=args.generator_args,
                                                               basis=args.basis, draws=()),
                            continuation=_f.FContinuation(after=tuple(
                                _f.ContinuationAfter(candidate=name, policy=None) for name in order))))}
                except Exception as exc:   # 形が違う: 偽りの一覧を作らず失敗として返す
                    failure = ("execution_error", {"error_type": type(exc).__name__})
        finished = reading()
        if failure is None:
            outcome: WorkOutcome = WorkOutputs(outputs=ContractValue(contract=desc.output_contract, value=value))
        else:
            outcome = WorkFailure(failure=FailureInfo(failure_kind=failure[0], content=failure[1],
                                                      readings=(started, finished), basis=()))
        ctx.post(WorkFinished(work=desc.work_id, started=started, finished=finished, outcome=outcome))


_STOP_REASONS = ("budget_exhausted", "selection_boundary", "certificate_incomplete", "cost_certificate",
                 "c1_closure_unproved")   # f.py の頭の説明の FIncomplete の語 (K32 決定 3)


def _run_math_work(work: "FWork", ctx: FWorkContext, purpose: str, compute) -> None:
    """数学の発行物を 1 つ作る仕事 (比べる準備・比べて選ぶ) の共通の形 (K32・K33 の決定 1〜4)。

    用途違いは入場前に TypeError。入場できなければ何もしない。始めの読み → compute(desc, ctx) → 終わりの読み →
    WorkFinished を 1 回 post (成功の時だけ発行物を issued で添える)。compute の例外は型を問わず (RecursionError も)
    `WorkFailure` (`execution_error`)。content は例外の型の名前と、F-a の閉じた一覧にある FIncomplete の理由の語と
    止まった所 (`/` から始まる時だけ) だけ。自由な文は載せない。"""
    import json
    from .f import FIncomplete as _FIncomplete
    if not isinstance(work, Compute) or work.desc.purpose != purpose:
        raise TypeError(f"this worker runs {purpose} works only")
    if not ctx.enter():
        return

    def reading() -> ReadingEvidence:
        try:
            return ctx.now()
        except RuntimeError:   # 時計の出どころを名指せない: 読みを作らず、理由を残して続ける (K24 と同じ)
            return Unavailable(reason="clock_source_unavailable", basis=())

    desc = work.desc
    started = reading()
    artifact, failure = None, None
    try:
        artifact = compute(desc, ctx)
        value = json.loads(artifact.canonical_bytes)
    except Exception as exc:   # できない: 偽りの発行物を作らず失敗として返す
        artifact, failure = None, {"error_type": type(exc).__name__}
        if isinstance(exc, _FIncomplete) and exc.reason in _STOP_REASONS:
            # F-a の閉じた理由の語と止まった所だけ残す (自由な文は載せない、K32-DC-03・DC-06)
            field = exc.field if isinstance(exc.field, str) and exc.field.startswith("/") else None
            failure.update(reason=exc.reason, field=field)
    finished = reading()
    if failure is None:
        outcome: WorkOutcome = WorkOutputs(outputs=ContractValue(contract=desc.output_contract, value=value))
    else:
        outcome = WorkFailure(failure=FailureInfo(failure_kind="execution_error", content=failure,
                                                  readings=(started, finished), basis=()))
    ctx.post(WorkFinished(work=desc.work_id, started=started, finished=finished, outcome=outcome),
             issued=artifact)


def _reader(ctx: FWorkContext) -> FReader:
    reader = ctx.reader()
    if reader is None:
        raise RuntimeError("this work port has no fixed reader")
    return reader


class EvaluationPreparer:
    """`FWorkers` の「比べる準備」の仕事の本体 (紙 F-b §6-10 K32、Z51 ②・Z57)。

    ホストが出した評価の準備の仕事 (`Compute`、`desc.purpose == "evaluation_prepare"`) を受け、仕事の口の読み手と、
    作る時に明示して渡された `registry` で `f_facts.prepare_f_from_facts` を呼ぶ。要求 (`desc.args.input`) と予算
    (`desc.args.budget`) はそのまま渡し、係が予算を変えたりやり直したりしない (上限を置くかは起動の宣言が決める、
    K32 決定 6)。発行物 (FProblem でも NoDecision でも) を `WorkFinished` の outputs と issued で返す。読み手が無い・
    準備の例外は型を問わず `WorkFailure` (`execution_error`、例外の型の名前だけ)。始めと終わりの読みは別々に取る
    (時計の出どころを名指せない時は Unavailable)。準備の仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。"""

    def __init__(self, *, registry: FRegistry) -> None:
        self._registry = registry

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        _run_math_work(work, ctx, "evaluation_prepare", self._prepare)

    def _prepare(self, desc: "Desc", ctx: FWorkContext) -> FMathArtifact:
        from . import f_facts as _ff
        request = desc.args.input
        return _ff.prepare_f_from_facts(
            _reader(ctx), fixed_parents=request.fixed_parents, model_ref=request.model,
            candidate_ref=request.candidates, preference_refs=request.preferences,
            scope_request=request.scope, context_ref=request.context, registry=self._registry,
            method=request.method, budget=desc.args.budget)


class Evaluator:
    """`FWorkers` の「比べて選ぶ」の仕事の本体 (紙 F-b §6-10 K33、Z51 ②・Z57)。

    ホストが出した評価の仕事 (`Compute`、`desc.purpose == "evaluation"`) を受け、仕事の口の読み手と準備の発行物
    (`ctx.prepared()`) で `f_facts.evaluate_f_from_draw` を呼ぶ。くじ (`desc.args.draw`) と予算 (`desc.args.budget`) は
    そのまま渡し、係が予算を変えたりやり直したりしない (K33 決定 2・6)。評価は registry を使わないので、作る時に
    何も受け取らない (決定 1)。発行物 (Selected でも NoDecision でも) を `WorkFinished` の outputs と issued で返す。
    読み手か準備の発行物が無い・評価の例外は型を問わず `WorkFailure` (`execution_error`)。評価の再帰が Python の
    再帰の限界に当たった時は `RecursionError` の名前で残る (環境が止めた、決定 5)。始めと終わりの読みは別々に取る。
    評価の仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。"""

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        _run_math_work(work, ctx, "evaluation", self._evaluate)

    @staticmethod
    def _evaluate(desc: "Desc", ctx: FWorkContext) -> FMathArtifact:
        from . import f_facts as _ff
        reader = _reader(ctx)
        prepared = ctx.prepared()
        if prepared is None:
            raise RuntimeError("this work port has no prepared artifact")
        return _ff.evaluate_f_from_draw(prepared, desc.args.draw, reader=reader, budget=desc.args.budget)


class UniformDraw:
    """`FWorkers` の「くじ」の仕事の本体 (紙 F-b §6-10 K35・K34、Z51 ②・H4)。生成器 `sui.fb.os_uniform_bits/1`。

    ホストが出した選択のくじの仕事 (`Draw`、`desc.purpose == "selection_draw"`) を受け、法則 uniform_bits/1 のくじ U の
    かたまりとして、乱数の源から B ビットの整数 k (B は `fb_contracts.OS_UNIFORM_BITS_BLOCK`) を取り、
    `{"bits": k, "length": B}` を `DrawValue` で 1 回返す。続きのかたまりも新しい B ビットを取る (独立公平な
    ビット列の仮定の下で、それが U の続きのけた)。引き直さない。乱数の源は作る時に明示して渡せる (既定は OS の暗号用の
    乱数 `secrets.randbits`)。生成器の名前が違う・要求が selection の uniform_bits/1 と args の形 {offset, after} に
    合わない時は引かずに `DrawFailure` (`rejected`、閉じた語の reason)。源の例外・範囲の外の値は `DrawFailure`
    (`execution_error`、例外の型の名前だけ)。offset と after は形のほかには読まない。時計は読まない (K34 決定 6)。
    くじの仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。"""

    def __init__(self, *, randbits: "_Callable[[int], int]" = _secrets.randbits) -> None:
        self._randbits = randbits

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        from . import f as _f
        from . import fb_contracts as _fc
        if not isinstance(work, Draw) or work.desc.purpose != "selection_draw":
            raise TypeError("UniformDraw runs selection_draw works only")
        if not ctx.enter():
            return
        desc = work.desc
        request = desc.args.request
        outcome, failure = None, None
        if desc.method != _fc.OS_UNIFORM_BITS:
            failure = ("rejected", {"reason": "unknown_generator"})
        else:
            try:
                if request.purpose != "selection" or request.law != _f.UNIFORM_BITS:
                    raise _f.FInputError("shape", "selection law")
                _f._bits_args(request)
            except _f.FInputError:
                failure = ("rejected", {"reason": "unsupported_request"})
        if failure is None:
            try:
                bits = _fc.OS_UNIFORM_BITS_BLOCK
                k = self._randbits(bits)
                if type(k) is not int or not 0 <= k < 1 << bits:
                    raise ValueError("random source returned a value outside the block")
                outcome = DrawValue(value={"bits": k, "length": bits})
            except Exception as exc:   # 引けない: 値を作らず失敗として返す
                failure = ("execution_error", {"error_type": type(exc).__name__})
        if failure is not None:
            outcome = DrawFailure(failure=FailureInfo(failure_kind=failure[0], content=failure[1],
                                                      readings=(), basis=()))
        ctx.post(DrawReturned(work=desc.work_id, outcome=outcome))


class StepExecutor:
    """`FWorkers` の「一歩を行う」仕事の本体 (紙 F-b K36 決定 3)。ホストが出した一歩の仕事 (`ExecuteStep`、
    `desc.purpose == "execute_step"`) を受け、入場して、その要求の固定の像 E を家の人の口 `perform` に渡すだけ。何をどう
    行うかは家の人が宣言から決め、結果のメモも家の人が書く (Z55: 係は結果のメモを書かない)。perform の例外 (止まった
    ホストなど) は偽りの結果にせず上げる。一歩の仕事以外を渡されたら TypeError (束ねるのは `WorkerBundle`)。"""

    def run(self, work: "FWork", ctx: FWorkContext) -> None:
        if not isinstance(work, ExecuteStep) or work.desc.purpose != "execute_step":
            raise TypeError("StepExecutor runs execute_step works only")
        if not ctx.enter():
            return
        ctx.perform(work.desc.args)


class StartInputError(ValueError):
    """誕生の入口 `start` が起動の宣言を断った (紙 F-b K36 決定 11・K36-a (ア)(エ)(オ))。何も保存せず、何も起こさない。
    reason は閉じた語: perception_missing (感じる側が無い) / finite_budget (予算に上限がある) / draw_generator (くじが
    本体の生成器でない) / draw_args (くじの args が空でない) / actor_missing (行う一歩の宣言が名指す相手が無い)。
    field は断った欄の JSON Pointer (相手は `/actors/<名前>`)。"""

    def __init__(self, *, reason: str, field: str) -> None:
        super().__init__(f"{reason}: {field}")
        self.reason = reason
        self.field = field


class RunningSui:
    """`start` が起こした sui (紙 F-b K36 決定 11)。host は起こしたホスト (回す役 `keep_running` で回す)。stop() は本体の
    測る係に止める合図を出す (始めた取りに行きは決着まで。環境の相手・源は呼ぶ側のもの)。"""

    def __init__(self, *, host: FThreadHost, measurer: SourceMeasurer) -> None:
        self._host, self._measurer = host, measurer

    @property
    def host(self) -> FThreadHost:
        return self._host

    def stop(self) -> None:
        self._measurer.stop()


def start(*, ledger: _Ledger, clock: _Clock, clock_declaration: ClockSource, boot: Boot,
          sources: _Mapping[str, FSource], actors: _Mapping[str, FActor], registry: FRegistry | None = None,
          launcher: FLauncher | None = None, randbits: "_Callable[[int], int] | None" = None) -> RunningSui:
    """誕生の入口 (紙 F-b K36 決定 11・Z51 ④⑤・K36-a (ア))。外から帳面・時計・時計の宣言・起動の宣言・環境 (受け身の源と
    行う手の相手) を受け取り、本体の係 7 用途の束ねと registry をそろえ、ホストを作って時計の宣言と起動の宣言を入れる。
    宣言を先に確かめ、合わなければ何も保存せず StartInputError で断る: 感じる側が無い・考える側の予算に上限がある・くじが
    `sui.fb.os_uniform_bits/1` でない・その args が空でない・行う一歩の宣言が名指す相手が渡されていない。上限を書いた
    宣言を試す時は FThreadHost を直接組む (Z57・K32 決定 6)。registry・launcher・randbits は試験の継ぎ目で、既定は本体の
    registry (`f_update2.fb_registry_v1()`)・OS のスレッドの起動係・OS の暗号用の乱数 (既定を変える口ではない)。
    ホストは回さない (回す役 `keep_running` は呼ぶ側)。"""
    from . import fb_contracts as _c
    from .f_update2 import fb_registry_v1
    declaration = boot.declaration
    if declaration.perception is None:
        raise StartInputError(reason="perception_missing", field="/declaration/perception")
    if declaration.initial is not None:
        initial = declaration.initial.value
        for name in ("prepare_budget", "evaluate_budget"):
            budget = getattr(initial, name)
            for limit in ("max_cells", "max_terms", "max_refinements"):
                if getattr(budget, limit) is not None:
                    raise StartInputError(reason="finite_budget",
                                          field=f"/declaration/initial/value/{name}/{limit}")
        if initial.draw.contract != _c.OS_UNIFORM_BITS:
            raise StartInputError(reason="draw_generator", field="/declaration/initial/value/draw/contract")
        if initial.draw.args:
            raise StartInputError(reason="draw_args", field="/declaration/initial/value/draw/args")
    if declaration.execution is not None:
        for name in declaration.execution.value.actors.values():
            if name not in actors:
                raise StartInputError(reason="actor_missing", field="/actors/" + name)
    from ._fb_boot import execution_reading_fault
    fault = execution_reading_fault(declaration)
    if fault is not None:   # 源の件数を読む・変える一歩を、時刻を読む信念と一緒に通さない (K38 決定 9)
        raise StartInputError(reason=fault[0], field=fault[1])
    timed = declaration.perception.value.derivation.method.contract == _c.SAVED_TIMED_ACQUISITION_UPDATE
    registry = fb_registry_v1() if registry is None else registry
    measurer = SourceMeasurer()
    workers = WorkerBundle({
        "measure_segment": measurer,
        "belief_update": (TimedBeliefUpdater if timed else FiniteUpdater)(registry=registry),
        "candidate_generation": CandidateGenerator(), "evaluation_prepare": EvaluationPreparer(registry=registry),
        "selection_draw": UniformDraw() if randbits is None else UniformDraw(randbits=randbits),
        "evaluation": Evaluator(), "execute_step": StepExecutor()})
    host = FThreadHost(ledger=ledger, clock=clock, workers=workers, registry=registry, launcher=launcher,
                       sources=sources, actors=actors)
    host.post(ClockDeclared(declaration=clock_declaration))
    host.post(boot)
    return RunningSui(host=host, measurer=measurer)
