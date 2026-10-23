"""F-a の新しい registry と、信念の更新を計算して発行する新しい版の入口 U (紙 F-b v0.25 §6-3・
§2-4-8・§2-5-19)。

段 0 の骨組み: 型と署名だけ。本体は段 3。v0.25 (ゆうの決定 D10) で、結果・証明・認証を別の仕事に
する形 (Target・CallBinding・CheckedProof・UpdateCertificateDescription・Verified・
VerifiedFiniteUpdate・TargetVerificationReturn) をやめ、U が一次事実から自分で計算して IssuedUpdate を
発行する形にした。旧 `builtin_f_registry()`・`/1`・旧 artifact の
読み直しは変えない (新しい能力を旧 `_BUILTIN_DECLARATIONS` に足さない)。
"""

from dataclasses import dataclass as _dataclass
from typing import Literal as _Literal, TypeAlias as _TypeAlias

from .f import ContractValue, FReader, FRegistry, ImmutableJSON, MeasurementInterval, Point, _FactoryHandle
from .contracts import ContractRef as _ContractRef
from .rate import RateBudget

__all__ = [
    "fb_registry_v1", "FixedViewValue", "VerificationNeed", "RejectedIssue",
    "InsufficientIssue", "IssuedUpdate", "Rejected", "Insufficient", "UpdateReturn",
    "LaunchResult", "ReportObservation", "ExecutionObservation", "UseObservation", "IntervalObservation",
    "AcquisitionObservation", "TargetEvidence", "UpdateBudget", "OperationHandle", "ExecutionHandle",
    "RouteApplicationObservation", "HostMonitorObservation",
    "compute_finite_update", "update_response", "prepare_fb_from_facts",
]


def fb_registry_v1() -> FRegistry:
    """旧の宣言の集合と実装の識別をそのまま含み、`finite_update/2` と入口 U ほか §2-5-19・§6-3 の能力を
    足した別の不変の registry (§2-4-8 の 2)。registry_key は全部の宣言と実装の識別から求まる。

    段 3 で足すのは、δ・入口 U・継続の方法と、U が読む読み方・法則・意味の契約 (§6-10 K1〜K12)。これらの意味は
    窓口と入口 U の版で閉じていて、能力の呼出しの規約からは呼ばない (呼ばれたら algorithm_unavailable)。宣言と
    実装の識別の対として registry_key に結ぶ。段 2 の生成・実行の能力は試験・ホストの側が明示に足す
    (旧 `_BUILTIN_DECLARATIONS` は増やさない)。"""
    from .f import CapabilityDeclaration, CapabilityImplementation, builtin_f_registry, make_f_registry
    from .contracts import ContractRef
    c = _c()
    old = builtin_f_registry()
    empty = ContractRef("sui.f.args.empty", "1")
    rows = (
        ("method", c.SAVED_SEGMENT_UPDATE, ContractRef("sui.fb.args.saved_segment_update", "1"),
         c.SEGMENT_BINDING, c.WORK_REQUESTED),
        ("method", c.FINITE_UPDATE_COMPUTE, empty, c.WORK_REQUESTED, c.UPDATE_RESPONSE),
        ("method", c.REUSE_CANDIDATES, empty, c.BELIEF_ADOPTED, c.EVALUATION_REQUESTED),
        ("method", c.OBSERVATION_PLAN_2, empty, c.SEGMENT_BINDING, c.FINITE_SEGMENT_PROJECTION),
        ("projection", c.FINITE_SEGMENT_PROJECTION, ContractRef("sui.fb.args.finite_segment_projection", "1"),
         c.SEGMENT_REPORT, c.FINITE_JOINT_COUNT_LAW),
        ("projection", c.NO_ARRIVAL, empty, c.SEGMENT_REPORT, c.FINITE_JOINT_COUNT_LAW),
        ("projection", c.COUNT_EXACTLY_ONE, empty, c.SEGMENT_REPORT, c.FINITE_JOINT_COUNT_LAW),
        ("generation", c.FINITE_JOINT_COUNT_LAW, empty, c.SEGMENT_REQUESTED, c.FINITE_JOINT_COUNT_LAW),
        ("generation", c.BOOTSTRAP_GENERATION, ContractRef("sui.fb.args.bootstrap_generation", "1"),
         c.SEGMENT_BINDING, c.MONITOR_SPAN),
        ("clock", c.SEGMENT_VALUE_ONLY, empty, c.SEGMENT_REPORT, c.SEGMENT_REPORT),
    )
    declarations = tuple(CapabilityDeclaration(kind=kind, ref=ref, args_contract=args, input_contract=inp,
                                               output_contract=out, dependencies=(), conditions=())
                         for kind, ref, args, inp, out in rows)
    implementations = tuple(CapabilityImplementation(kind=kind, ref=ref, implementation=_ExecutedByEntrance(),
                                                     identity="sui.fb.stage3/1:" + ref.name + "/" + ref.version)
                            for kind, ref, *_ in rows)
    return make_f_registry(declarations=old.declarations + declarations,
                           implementations=old.implementations + implementations)


class _ExecutedByEntrance:
    """段 3 の契約の意味は窓口と入口 U の版にある。能力の呼出しの規約から呼ばれたら不足として示す。"""

    def __call__(self, *, args, input, context):
        from .f import FIncomplete
        raise FIncomplete("algorithm_unavailable", "executed by the F-b window and entrance U, not as a capability")


@_dataclass(frozen=True, slots=True, kw_only=True)
class FixedViewValue:
    """保存できる固定像の値 (F-b §2-5-1 の FixedView と同じ欄)。"""
    boundary: frozenset[Point]
    reader_view_key: str
    registry_key: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class VerificationNeed:
    """U が足りなかったものの対象 (§19-9 の形を §6-3 に合わせた)。kind ごとに value の欄が決まる:
    capability = {contract, purpose: reading/generation/clock/replay/computation}、
    evidence = {target: Point, purpose: generation/clock/support/acquisition/adoption_chain, contract: ?ContractRef}、
    budget = {phase: reader/projection/replay/computation}。存在しない Point を捏造しない。"""
    kind: _Literal["capability", "evidence", "budget"]
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class RejectedIssue:
    code: _Literal[
        "schema", "shape", "noncanonical", "rational", "unit", "unknown_version",
        "normalization", "unresolved_reference", "reference_kind",
        "observation_binding_mismatch", "measurement_conflict", "clock_unaligned",
        "missing_contract", "model_falsified", "outside_evaluation_type", "result_mismatch",
        "proof_mismatch",
    ]
    fields: tuple[str, ...]
    evidence: frozenset[Point]
    message: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class InsufficientIssue:
    code: _Literal[
        "algorithm_unavailable", "budget_exhausted",
        "prerequisite_unavailable", "clock_unaligned",
    ]
    fields: tuple[str, ...]
    missing: tuple[VerificationNeed, ...]
    evidence: frozenset[Point]
    message: str


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class IssuedUpdate(_FactoryHandle):
    """入口 U が一次事実から計算して発行した更新の結果 (紙 v0.25 §6-2・§6-3)。factory 専用:
    直接の構築は TypeError で、保存した説明値や仕事が返した joint から作れない。
    request は更新要求 Q*。result は `sui.f.finite_update_result/1` の値 {joint, evidence_mass}
    (§2-5-19-8) の正準 JSON で、窓口は保存した R* の本文とこれを全比較する。結果の二欄だけでは
    適用済みの状態を見分けられないので、application_digest (適用済みの主張の述語の連言、§2-5-19-1)
    と、計算に使った固定根・registry も結ぶ (C7・C8)。"""
    request: Point
    result: ImmutableJSON
    application_digest: str
    numerical_view: FixedViewValue
    registry_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class Rejected:
    """U が正常に判定して不適合だった。仕事の実行の障害 (WorkFailure・WorkUnknown) とは別。"""
    request: Point
    issues: tuple[RejectedIssue, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class Insufficient:
    """U が正常に判定して、能力・証拠・予算が足りなかった。不足を成功や 0 件に置き換えない (C10)。"""
    request: Point
    issues: tuple[InsufficientIssue, ...]


UpdateReturn: _TypeAlias = IssuedUpdate | Rejected | Insufficient
"""U の確定の返答の三枝。issues は空にしない。仕事の実行の Failure/Unknown は外側の層。"""


LaunchResult: _TypeAlias = _Literal["launched", "not_started", "unknown"]
"""起動の結果 (F-b §2-4-2 の Launch)。launched = OS の起動が済んだ (本体に入ったかは別)、
not_started = 確かに起動していない、unknown = 起動したか分からない。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class UpdateBudget:
    """`sui.fb.update_budget/1` (紙 F-b Z34 (a) = C): 信念の更新の 1 回に渡す予算。論理の仕事 logical_work/1 の上限
    logical_limit (10 種の出来事を各 1 で数える) と、読み手の像・数値計算の予算 numerical (RateBudget、S4 の意味のまま) を
    分ける。固定の上限は F-c で外す施工中の仮の形 (Z32)。既定値を持たない。"""
    contract: _ContractRef
    logical_limit: int
    numerical: RateBudget

    def __post_init__(self):
        from .f import FInputError
        if _enc(self.contract) != _enc(_c().UPDATE_BUDGET):
            raise FInputError("unknown_version", "sui.fb.update_budget/1 required", "/contract")
        if type(self.logical_limit) is not int or self.logical_limit < 0:
            raise FInputError("shape", "logical_limit: non-negative int required", "/logical_limit")
        if not isinstance(self.numerical, RateBudget):
            raise FInputError("shape", "RateBudget required", "/numerical")


# --- ホストの工場だけが作る観測 (正本 v1.3.7 PERMISSION_BINDINGS の transport_types・execution_observation_extension) ---

_SEAL = object()   # 工場の印。保存 JSON・同じ文字列・試験の外の組み立てから観測を作らせない (捏造を構造で塞ぐ)


class _Handle:
    """ホストの工場が実際の操作・実行ごとに発行する不透明な識別。等しさは同じ物であること (名札の文字列で代用しない、
    紙 :2171)。保存しない。"""
    __slots__ = ("_kind", "_number")
    _count = 0

    def __init__(self, kind, seal):
        if seal is not _SEAL:
            raise TypeError(f"{kind} handles are minted by the host factory only")
        type(self)._count += 1
        self._kind, self._number = kind, type(self)._count

    def __repr__(self):
        return f"<{self._kind} #{self._number}>"


class OperationHandle(_Handle):
    """ホストの実際の操作 (受け口への route の適用・監視の記録) の識別。"""


class ExecutionHandle(_Handle):
    """ホストの仕事表の 1 行の実行の識別 (WorkId は不透明な名札で同一性の証明ではない、紙 :2171)。"""


def _mint(kind):
    return (OperationHandle if kind == "operation" else ExecutionHandle)(kind, _SEAL)


@_dataclass(frozen=True, slots=True, kw_only=True)
class RouteApplicationObservation:
    """ホストが受け口に route の設定を実際に適用した操作 (紙 G2 :3382、正本 transport_types v2)。applied_config は
    その時に入れた設定の全文、reading はその境目の M の読み (読めなければ型つきの Unavailable)。保存した route_config
    の復号から作らない。publication は同じ操作から保存を確かめた route_config の Point (まだなら None)。"""
    operation: OperationHandle
    boot: Point
    route_slot: str
    applied_config: object                 # f.RouteConfig
    reading: object                        # f.ClockReading | f.Unavailable
    clock_source: Point | None
    evidence_inputs: tuple                 # ((Point, Ref), ...) 実際に使った入力の出現の順
    execution: object                      # Ref | None (bootstrap は None)
    publication: Point | None
    seal: object

    def __post_init__(self):
        if self.seal is not _SEAL:
            raise TypeError("RouteApplicationObservation is captured by the host factory only")


@_dataclass(frozen=True, slots=True, kw_only=True)
class HostMonitorObservation:
    """ホストが監視の記録を作る時の実観測 (紙 K4 :3498、正本 transport_types v2・HOST_MONITOR_BINDING)。M を読み、
    同じ実行が入場済みで停止していないことを同じ歩で確かめる。segment・route は仕事表と保持した適用の操作から取り、
    保存した B・monitor_span・Claim から写さない。入場の時刻は EW の entered_ns[entry_index] (ここに二重に持たない)。"""
    operation: OperationHandle
    execution_occurrence: ExecutionHandle
    entry_index: int
    segment: Point
    work: str
    route_operation: OperationHandle
    route: Point
    clock_source: Point
    observed_reading: object               # f.ClockReading
    observed_state: _Literal["entered_not_stopped"]
    publication: Point | None
    seal: object

    def __post_init__(self):
        if self.seal is not _SEAL:
            raise TypeError("HostMonitorObservation is captured by the host factory only")


class RouteCapture:
    """工場の控え: 受け口への route の実適用を、その操作の時に 1 回だけ捕捉する (再試行は同じ控えを使い、M を読み直さない)。
    publication は同じ操作から作った route_config の Point を、保存の計画が固まった歩で結ぶ。"""

    def __init__(self, *, boot, route_slot, applied_config, reading, clock_source, evidence_inputs, execution):
        self.operation = _mint("operation")
        self.boot, self.route_slot, self.applied_config = boot, route_slot, applied_config
        self.reading, self.clock_source = reading, clock_source
        self.evidence_inputs, self.execution = tuple(evidence_inputs), execution
        self.publication = None

    def observation(self):
        return RouteApplicationObservation(
            operation=self.operation, boot=self.boot, route_slot=self.route_slot, applied_config=self.applied_config,
            reading=self.reading, clock_source=self.clock_source, evidence_inputs=self.evidence_inputs,
            execution=self.execution, publication=self.publication, seal=_SEAL)


class MonitorCapture:
    """工場の控え: 監視の記録を作る時の実観測 (M の読みと、同じ歩での入場済み・未停止の確認)。"""

    def __init__(self, *, execution_occurrence, entry_index, segment, work, route_operation, route, clock_source,
                 observed_reading):
        self.operation = _mint("operation")
        self.execution_occurrence, self.entry_index = execution_occurrence, entry_index
        self.segment, self.work, self.route_operation, self.route = segment, work, route_operation, route
        self.clock_source, self.observed_reading = clock_source, observed_reading
        self.publication = None

    def observation(self):
        return HostMonitorObservation(
            operation=self.operation, execution_occurrence=self.execution_occurrence, entry_index=self.entry_index,
            segment=self.segment, work=self.work, route_operation=self.route_operation, route=self.route,
            clock_source=self.clock_source, observed_reading=self.observed_reading,
            observed_state="entered_not_stopped", publication=self.publication, seal=_SEAL)


@_dataclass(frozen=True, slots=True, kw_only=True)
class ReportObservation:
    """EH: ホストが受け取った 1 つの封筒と、そこから保存した原報告の対応 (F-b §2-5-2: 封筒との対応は
    台帳だけでは復元しない)。point は原報告の保存を照合できた時だけ実在の Point、まだなら None。"""
    envelope: int
    received_ns: int
    point: Point | None
    run: str | None = None   # received_ns を読んだホストの時計の run (時計系。無ければ時刻の比較は MISSING、表 EVENT_SOURCES)


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionObservation:
    """EW と EH: ホストと起動の包みが独立に観測した、一つの WorkId の実行 (F-b §2-5-2)。
    launches は起動の試みの結果の列、entered は本体への入場の回数 (開始の札を使えた回数)、
    stopped は実際の停止 (係の戻り) を観測したか。reports はこの仕事の口 (FWorkContext.post) から
    ホストが受け取った封筒と、その保存した原報告の Point の列 (同じ WorkId を名乗る別経路の報告と分ける。
    U と窓口は対象の原報告の Point がここにあるかで、その仕事から来たかを照合する)。要求の保存・
    WorkId・phase の印・Ended・T からは作らない。"""
    work_id: str
    launches: tuple[LaunchResult, ...]
    entered: int
    stopped: bool
    reports: tuple[ReportObservation, ...]
    entered_ns: tuple[int, ...] = ()   # 各入場の時のホストの M の読み (EVENT_SOURCES work_entered。回数 entered とは別)
    run: str | None = None             # それを読んだホストの時計の run
    # 正本 v1.3.7 execution_observation_extension (既定値なし): 実行の識別・実際の要求・測る実行が使った route の
    # 実適用の操作 (測らない仕事は None)・entered_ns / run を読んだ時計の源
    execution_occurrence: ExecutionHandle
    request: Point | None
    route_operation: OperationHandle | None
    clock_source: Point | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class UseObservation:
    """EW: 仕事の本体が実際に読んだ入力 (FWorkContext.read) と、その時のホストの run の M の読み。
    Desc.input_points の申告や必須閉包の正解とは別の、実使用の観測。"""
    work_id: str
    point: Point
    used_ns: int
    run: str | None = None   # used_ns を読んだホストの時計の run (無ければ時刻の比較は MISSING)


@_dataclass(frozen=True, slots=True, kw_only=True)
class IntervalObservation:
    """EI: 測る仕事が実際に見張った区間 (FWorkContext.monitored)。固定像の中の証拠
    (Started・Ended・Claim など) が実際の出来事を表すかの照合だけに使い、像の外の監視履歴を
    Support の追加証拠に混ぜない (F-b :752〜756)。原報告の区間を写して作らない。"""
    work_id: str
    interval: MeasurementInterval


@_dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionObservation:
    """EA: origin が対象の内容を実際に取得したこと (取得 a の M の読み)。通知 G の r・s と別。
    取得と Wu の使用の前後は UseObservation.used_ns と比べる (G の保存の時刻と比べない)。"""
    origin: Point
    contents: frozenset[Point]
    acquired_ns: int
    run: str | None = None   # acquired_ns を読んだホストの時計の run


@_dataclass(frozen=True, slots=True, kw_only=True)
class TargetEvidence:
    """入口 U に渡す同じプロセスの中の独立の証拠 (F-b §2-5-2 の EW・EH・EI・EA、§6-3)。ホストが
    自分で行った操作の時に自分で読んだもので、台帳の自己申告や窓口の印・原報告の写しから作らない。同じプロセスの中の窓口の作り直しまでで、再起動をまたがない (★S5)。"""
    executions: tuple[ExecutionObservation, ...]
    uses: tuple[UseObservation, ...]
    intervals: tuple[IntervalObservation, ...]
    acquisitions: tuple[AcquisitionObservation, ...]
    # 正本 v1.3.7 target_evidence_extension (既定値なし。捕捉の欠落を空列で証明しない)
    route_applications: tuple[RouteApplicationObservation, ...]
    host_monitors: tuple[HostMonitorObservation, ...]


def compute_finite_update(
    request: Point, *, reader: FReader, registry: FRegistry,
    evidence: TargetEvidence, budget: UpdateBudget,
) -> UpdateReturn:
    """入口 U `sui.f.finite_update_compute/1` (紙 v0.25 §6-3)。保存済みの更新要求 Q* から読み手・
    モデル・固定根・前の採用・観測の並びを解決し、保存した一次事実と境目の実観測だけを読んで、
    宣言の解決・生成の対応・入力の実取得と実使用・固定根・適用の履歴を確かめ、§2-5-19 の数学で
    計算して発行する。F-b から完成した joint を受け取る引数は無い。入口で要求を構成できない不正や
    物理的な欠落は例外 (三枝に無理に写さない)。

    この版で読める観測は、宣言した route の no_arrival / count_exactly_one の原 Claim を
    `finite_segment_projection/1` (frame なし・`segment_value_only/1`)・`bootstrap_generation/1`
    (whole_window) で読むものだけ (§6-10 J1・K2〜K4)。認証は今の Q* にも、prior からたどった前の系列の各 Q* にも
    同じ `_Replay.authenticate` を当てる (§6-10 A1〜A3)。この入口だけの検査は、呼出しの予算が Q* に保存した予算と
    同じことと、この Wu が実際に入場したこと。"""
    from ._f_world import capture_reader, registry_view_key
    from .f import FIncomplete, FInputError
    try:
        image = capture_reader(reader, budget.numerical)
    except FIncomplete as exc:   # 読み手の像を取る予算の不足は不足の返答 (R07)
        return _insufficient(request, exc, "reader")
    try:
        record = image.record(request)
    except KeyError:
        raise FInputError("unresolved_reference", "request outside the reader", "/request") from None
    desc = record.body.content.as_json().get("desc") if record.body.contract == _c().WORK_REQUESTED else None
    if desc is None or desc["purpose"] != "belief_update" or desc["method"] != _enc(_c().FINITE_UPDATE_COMPUTE) \
            or desc["output_contract"] != _enc(_c().UPDATE_RESPONSE):
        raise FInputError("shape", "not a belief_update request for this entrance", "/request/desc")
    replay = _Replay(registry, evidence, budget)
    try:
        from .f import _dumps
        # 呼出しの予算は Q* に保存した値と同じ (A3・R07-R2: 呼出し側で上書きさせない)
        if _dumps(_enc(budget)) != _dumps(desc["args"]["budget"]):
            raise _Issue("rejected", "observation_binding_mismatch", "budget differs from the one fixed in Q*",
                         fields=("/args/budget",), evidence=(request,))
        auth = replay.authenticate(request, image)
        replay._frame_return(request, auth)
        _check_entered(desc, evidence)
    except FIncomplete as exc:
        return _insufficient(request, exc, "computation")
    except _Issue as issue:
        if issue.kind == "rejected":
            return Rejected(request=request, issues=(RejectedIssue(
                code=issue.code, fields=issue.fields, evidence=issue.evidence, message=issue.message),))
        return Insufficient(request=request, issues=(InsufficientIssue(
            code=issue.code, fields=issue.fields, missing=issue.missing, evidence=issue.evidence,
            message=issue.message),))
    state = auth.state
    view = desc["numerical_view"]
    from ._f_handles import issue as _issue_handle
    from .f import FiniteUpdateResult, _encode, _handle
    return _issue_handle(_handle(
        IssuedUpdate, authority=registry, request=request,
        result=_encode(FiniteUpdateResult(joint=state.joint, evidence_mass=state.mass)),
        application_digest=state.digest(desc["args"]["model"], desc["reader"]),
        numerical_view=FixedViewValue(boundary=frozenset(view["boundary"]),
                                      reader_view_key=view["environment"]["reader_view_key"],
                                      registry_key=view["environment"]["registry_key"]),
        registry_key=registry_view_key(registry)))


# --- 入口 U と評価の準備に共通の認証 (§6-3・§2-5-19・§6-10 A1〜A4、段 3) ---

class _Sub:
    """親の像を固定根の境界の祖先の閉包に限る (`_fb_boot._Closure` と同じ範囲、R02)。親は最初の読み手か、
    直上の Q* の部分像 (A1: 前の Q* の部分像は直上の部分像からだけ作る)。"""

    def __init__(self, image, boundary):
        self._image = image
        self._points = image.ancestors(boundary)

    def entries(self):
        source = getattr(self._image, "all_entries", self._image.entries)
        return tuple(e for e in source() if e.cid in self._points)

    def ancestors(self, frontier):
        return frozenset(self._image.ancestors(frontier)) & self._points

    def entry(self, cid):
        if cid not in self._points:
            raise KeyError(cid)
        return self._image.entry(cid)

    def record(self, cid):
        return self._image.record(self.entry(cid).cid)

    def sealed_content(self, cid):
        return self._image.sealed_content(self.entry(cid).cid)


def _insufficient(request, exc, phase):
    return Insufficient(request=request, issues=(InsufficientIssue(
        code="budget_exhausted" if exc.reason == "budget_exhausted" else "algorithm_unavailable",
        fields=(), missing=(VerificationNeed(kind="budget", value={"phase": phase}),), evidence=frozenset(),
        message=str(exc)),))


def _check_entered(desc, evidence):
    """入口だけの検査: この Wu が実際に入場している (EW)。自分の完了や未来の R*・A* は前提にしない (REF-7)。"""
    own = next((e for e in evidence.executions if e.work_id == desc["work_id"]), None)
    if own is None or own.entered < 1:
        raise _Issue("insufficient", "prerequisite_unavailable", "the update work was not observed entering",
                     missing=(VerificationNeed(kind="evidence", value={
                         "target": desc["work_id"], "purpose": "generation", "contract": None}),))


class _Issue(Exception):
    """U が正常に判定した不適合 (rejected) か不足 (insufficient)。三枝の返答に写す。"""

    def __init__(self, kind, code, message, *, fields=(), evidence=(), missing=()):
        super().__init__(message)
        self.kind, self.code, self.message = kind, code, message
        self.fields, self.evidence, self.missing = tuple(fields), frozenset(evidence), tuple(missing)


def _c():
    from . import fb_contracts
    return fb_contracts


def _enc(value):
    from .f import _encode
    return _encode(value)


def _content(image, point, contract, used=None):
    """reader の像の中の記録の本文 (JSON)。契約が違えば不適合。used は必須閉包 (読んだ記録) を集める。"""
    if used is not None:
        used.add(point)
    try:
        record = image.record(point)
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", f"{point} is outside the reader",
                     evidence=()) from None
    if record.body.contract != contract:
        raise _Issue("rejected", "reference_kind", f"{point} is not {contract.name}/{contract.version}",
                     evidence=(point,))
    return record.body.content.as_json()


# 初回に意味を定めた Claim の契約と kind、その (lower, upper) (§19-1 の表)
def _meanings():
    c = _c()
    return {(c.NO_ARRIVAL.name, c.NO_ARRIVAL.version): ("no_arrival", 0, 0),
            (c.COUNT_EXACTLY_ONE.name, c.COUNT_EXACTLY_ONE.version): ("count_exactly_one", 1, 1)}


_REJECT_CODES = {"schema", "shape", "noncanonical", "rational", "unit", "unknown_version", "normalization",
                 "unresolved_reference", "reference_kind", "observation_binding_mismatch",
                 "measurement_conflict", "clock_unaligned", "missing_contract", "model_falsified"}


class _State:
    """一次事実から導いた適用済みの状態 (§19-1 の Claim の部分)。呼出し側の申告ではない。"""

    def __init__(self, joint):
        from fractions import Fraction
        self.joint, self.mass = tuple(joint), Fraction(1)
        self.carrier_by_state, self.law_point, self.law = None, None, None
        self.applied = {}   # ClaimKey (segment, item_slot) → Predicate

    def copy(self):
        out = _State(self.joint)
        out.mass, out.carrier_by_state, out.law_point, out.law = self.mass, self.carrier_by_state, \
            self.law_point, self.law
        out.applied = dict(self.applied)
        return out

    def digest(self, model, origin) -> str:
        """application_digest (§19-1): モデル・origin・法則と、今の連言が表す行の集合 (連言を満たす正準 marks)。
        配送の分割・B の番号・含意される述語の有無で変わらない (R09)。元の述語は論理の検査のために別に持つ。"""
        from .f import _digest
        from . import _f_count as count
        rows = [] if self.law is None else [list(map(list, marks)) for marks, _mass in self.law.rows
                                            if all(count.holds(marks, p) for p in self.applied.values())]
        return _digest({"domain": "sui.fb.application/1", "model": model, "origin": origin,
                        "law": self.law_point, "rows": rows})


def _encode_result(state):
    """再計算した状態の finite_update_result/1 の値 (保存した R* の result 欄と同じ形)。"""
    from .f import FiniteUpdateResult, _encode
    return _encode(FiniteUpdateResult(joint=state.joint, evidence_mass=state.mass))


def _span(value):
    from . import _f_count as count
    from .f import _dumps
    return count.Span(clock=_dumps(value["clock"]).decode("utf-8"), start_ns=value["start_ns"],
                      end_ns=value["end_ns"], closure=value["closure"])


def mandatory(image, point, document) -> frozenset:
    return _uses_points(mandatory_obligations(image, point, document))


def _uses_points(obligations):
    from . import _fb_uses as uses
    return uses.points_of(obligations)


def mandatory_obligations(image, point, document) -> tuple:
    """A2 の C の型つきの部分を紙の表 T-A2 から (`_fb_uses.required`): Local(q) と、prior があれば History (A*・Q*・R*・G と
    その生成・取得の証拠)・前の C の型つきの部分・前の I を、前の系列の全部についてたどる。q 自身の /inputs/* は
    要らない (それが I)。Support の証拠は X の中から選ぶので別 (`_Replay._support`)。作る側 (窓口の Q*) と認証する側
    (U) が同じこの関数で導く。"""
    from . import _fb_uses as uses
    reader = uses.Reader(image)
    try:
        found = uses.required(reader, point, uses.contract_name(_c().WORK_REQUESTED), "update", document,
                              groups=uses.A2_GROUPS, start_groups=("Local", "History"))
    except uses.Unresolved as exc:
        raise _Issue("rejected", "unresolved_reference", f"{exc} is not resolvable", evidence=()) from None
    except uses.Unsupported as exc:
        raise _Issue("rejected", "missing_contract", str(exc), evidence=()) from None
    except uses.Malformed as exc:
        raise _Issue("rejected", "shape", str(exc), evidence=()) from None
    return found


class _Auth:
    """1 つの Q* の認証の結果 (frame が親へ返す値): 観測を適用した後の状態、その部分像、独立に導いた必須閉包 C、解決した I
    (Point の集合と I の順の {point, ref, bytes, causal})、認証済みの参照 (T-A2 の義務を用途・位置ごと保った列)。"""

    def __init__(self, state, sub, desc, required, inputs, resolved_inputs=(), authenticated_refs=()):
        self.state, self.sub, self.desc, self.required, self.inputs = state, sub, desc, required, inputs
        self.resolved_inputs, self.authenticated_refs = list(resolved_inputs), list(authenticated_refs)


_STAGE_CURRENT, _STAGE_RESULT, _STAGE_ACQUIRE, _STAGE_ADOPT, _STAGE_HEAD = "更新の再構成", "結果の生成", "取得", "採用", "評価の頭"
_PRIOR_STAGES = (_STAGE_CURRENT, _STAGE_RESULT, _STAGE_ACQUIRE, _STAGE_ADOPT)
_CHAIN_SCOPE = "history"   # 系列の項目 (使う前の採用系列と頭の A*) の対象の scope (表 T-A1 の対象列 = SCOPES)
_RESULTS_SCOPE = "results"  # 結果の項目 (過去の A*.request / result の対応) の scope
# 過程ごと (Q* ごとでない) の T-A1 の項目: ID → 検査の場所。構造の検査が T-A1 の全行と突き合わせる (Q* ごとの項目は
# `_Replay.done` の印で集約し、印の無い項目があれば成功にしない)
A1_PROCESS = {
    "A1-LIVE-WU-ENTER": "compute_finite_update → _check_entered",
    "A1-BUDGET-CALL": "compute_finite_update (呼出しの予算 = Q* の保存した予算)",
    "A1-ISSUED-RESULT": "_fb_update._check_issued (窓口: factory の発行物と要求・返答の全照合)",
    "A1-RESULT-ACQUIRE-ORDER": "_fb_update._acquire_steps (取得の門が実取得と EA より前、取得と採用は別の歩)",
    "A1-ADOPTION-PREVIOUS": "_fb_update._head (前の採用の保存の確認待ちは wait)",
    "A1-BUDGET-EVALUATION": "adopted_belief (全体の予算は compiler の予算、頭の再生は保存した予算)",
    "A1-CLASS-INSUFFICIENT": "compute_finite_update / adopted_belief (A4 の写像)",
    "A1-CLASS-MISMATCH": "compute_finite_update / adopted_belief (A4 の写像、理由の語を保つ)",
    "A1-CLASS-CONFLICT": "_check_use (use_conflict)",
    "A1-SCOPE": "_check_use (Xuse = 評価の固定根)・_fb_uses.Reader.point (header の識別子からの索引)",
    "A1-PROVENANCE-MISSING": "_check_use (当該口 = 比較、別の口と確定 = 除外、判定できない = 不足)",
}


# 表の行のうち機械の評価器 (`_fb_a1`) が原子を 1 つずつ比べる行 (①-c、紙 v0.35 Z28)。ここに無い Q* ごとの行は、まだ手書きの
# 検査が `done` の印を置く (行ごとに移していく。移し終わるまでの一覧 = A1_HANDWRITTEN、構造の検査が数える)
# ★ 不適合の理由の語 (RejectedIssue.code の公開の語彙、紙 A4)。表の係 11 通目: 語は原子が `code` として持つ (紙 F-a A-20/A-21
# の対応から、既定値で埋めない)。原子に無い間だけの暫定の対応 (表の係 12 通目で原子に書かれたら消す): 要求の形・契約 = shape、他 = proof_mismatch
A1_REASON_CODES = {"A1-REQUEST": "shape", "A1-FIXED-VIEW": "observation_binding_mismatch",
                   "A1-NESTED-VIEW": "observation_binding_mismatch", "A1-VIEW-KEY": "observation_binding_mismatch"}
# 対象 = requests (Q* ごとに 1 回、authenticate の終わり)。A1-REQUEST と A1-REGISTRY は authenticate の途中の同じ位置で (順が要る)
A1_EVALUATED = ("A1-DECLARATION", "A1-BUDGET-TOTAL", "A1-BUDGET-UNIT", "A1-ORIGIN-MODEL", "A1-REQUEST", "A1-REGISTRY", "A1-ACQUIRE-USE", "A1-ACQUIRE-USE-MISSING",
                "A1-FIXED-VIEW", "A1-NESTED-VIEW", "A1-VIEW-KEY", "A1-I-UNIQUE", "A1-I-ALL", "A1-C", "A1-DIRECT-REFS", "A1-REF-RESOLUTION", "A1-BUDGET-SAVED",
                "A1-CAPABILITY-DECLARATION",
                "A1-CAPABILITY-IMPLEMENTATION")
# A1-ACQUIRE-USE: 取得を要する入力は観測の 5 種 (原 Claim・B・監視の記録・law・読み方、K5 :3497。表の係 10・11 通目で宣言を
# 書き直した)。旧の手書き `_check_acquired` は 3 種しか見ていなかった (紙より狭い) ので消した
# 対象 = observations (Q* の観測の対ごとに 1 回)。A1-CLOCK は 2026-10-22 11:5x に機械が表の項目 CLK-ROUTE-WINDOW-START の
# 誤り (左が和型のまま) を見つけ、表の係 9 通目 (12:0x) が正本を直してから機械に移した (R02 の 6 周目を閉じる行)
A1_EVALUATED_PER_OBSERVATION = ("A1-CLOCK", "A1-CLOCK-MISSING", "A1-OBSERVATION", "A1-CHANNEL", "A1-RAW-PROVENANCE",
                                # 生成の独立の観測と Support (Z33 ①、正本 v1.3.7: ホストの工場の捕捉と照らす)
                                "A1-GENERATION-APPLIED", "A1-GENERATION-STARTED", "A1-GENERATION-ENDED",
                                "A1-GENERATION-EVIDENCE", "A1-SUPPORT")
# 対象 = history (前の採用系列と頭の A*: A*・Q*・R*・G、`adopted` で 1 回)
A1_EVALUATED_HISTORY = ("A1-HISTORY-ENTER", "A1-HISTORY-ENTER-MISMATCH", "A1-HISTORY-RETURN-MISSING",
                        "A1-HISTORY-ACQUIRE", "A1-HISTORY-ACQUIRE-MISSING", "A1-HISTORY-ACQUIRE-BEFORE-USE",
                        "A1-HISTORY-ACQUIRE-BEFORE-ADOPT", "A1-CHAIN", "A1-HISTORY-RETURN")
# 対象 = evaluation_head (A*・Q*、評価の頭だけ)
A1_EVALUATED_HEAD = ()
# 対象 = requests、frame の戻り値を呼び出した側が受け取った後 (`_Replay._frame_return`、今の Q* は入口 U、前の Q* は親の frame)
A1_EVALUATED_RETURN = ("A1-C-HISTORY", "A1-BUDGET-CACHE")
# 対象 = results (前の採用の Q* とその R*、check_adoption で 1 回。今の Q* には当たらない)
A1_EVALUATED_RESULTS = ("A1-RESULT-ALL", "A1-NUMERICAL-REPLAY")
# 対象 = records (Q* の認証で読む各 record = 型つき必要閉包 C と全 I と Q* 自身、記録ごとに 1 回。本文の読取り → 同一性の順)
A1_EVALUATED_RECORDS = ("A1-BODY-MISSING", "A1-IDENTITY", "A1-SHAPE")


def _a1_rows():
    from . import _fb_rules as rules
    return rules.T_A1


def a1_handwritten() -> frozenset:
    """まだ機械で評価していない Q* ごとの T-A1 の行 (手書きの検査が印を置く)。0 になるのが P-R02 の閉じる条件。"""
    return frozenset(row["id"] for row in _a1_rows()) - set(A1_PROCESS) - set(A1_EVALUATED) \
        - set(A1_EVALUATED_PER_OBSERVATION) - set(A1_EVALUATED_HISTORY) - set(A1_EVALUATED_HEAD)         - set(A1_EVALUATED_RECORDS) - set(A1_EVALUATED_RESULTS) - set(A1_EVALUATED_RETURN) - a1_pending()


def a1_pending():
    from . import _fb_rules as rules
    return frozenset(p["id"] for p in rules.METADATA["pending"] if p["table"] == "T-A1")


def _subject_scope(row):
    """T-A1 の対象列の scope (JSON `{"scope", "records"}`。A1-I-UNIQUE だけ旧の表記 = requests、表記規約)。"""
    subject = row["subject"]
    return subject["scope"] if hasattr(subject, "items") else "requests"


def a1_applicable(stages, *, chain) -> frozenset:
    """Q* 1 つに当てる T-A1 の項目: 過程ごとの項目と未確定を除き、段階が重なる行。系列の項目 (使う前の採用系列)
    と結果の項目 (Q*・R* の対応) は前の採用の Q* にだけ (今の Q* に未来の自分の R* を要求しない、SCOPES results)。"""
    out = set()
    for row in _a1_rows():
        if row["id"] in A1_PROCESS or row["id"] in a1_pending():
            continue
        if _subject_scope(row) in (_CHAIN_SCOPE, _RESULTS_SCOPE) and not chain:
            continue
        if any(stage in stages for stage in row["stages"]):
            out.add(row["id"])
    return frozenset(out)


class _Replay:
    """1 回の検証 (入口 U 1 回、または評価の準備の A* の読み 1 回)。authenticate は今の Q* にも前の系列の各 Q* にも
    評価の頭の Q* にも同じ全項目を当てる (§6-10 A1)。予算は 2 層 (A3): 各 Q* の再生はその Q* に保存した予算、
    その外に今回の検証全体の予算。計数は子の再生を含めて親と全体へ累積し、戻さない。
    A1 の項目は紙の表 T-A1 から: 各検査が `done(point, ID)` の印を置き、Q* ごとに当たる項目 (`a1_applicable`) に
    印の無いものが 1 つでもあれば成功にしない (未処理の義務、開発フローの紙 ①-b)。"""

    # 計算法 `sui.f.finite_update_compute/1` が宣言する計数の単位 logical_work/1 (紙 :3616 の技術の選択、ゆう 2026-10-22 09:22
    # で採用、正本の表記規約 40 行)。各出来事の仕事量はここが決め、表 (BUDGET_EVENT_KINDS) が独立に同じ単位を持つ =
    # A1-BUDGET-UNIT が両方を比べる (表から期待値を作らない)
    COUNTING_UNIT = "logical_work/1"
    UNITS = {"header_read": 1, "body_read": 1, "reference_compare": 1, "projection_input": 1, "integer_extension": 1,
             "exact_add": 1, "exact_subtract": 1, "exact_multiply": 1, "exact_divide": 1, "exact_compare": 1}

    def __init__(self, registry, evidence, budget):
        self.registry, self.evidence = registry, evidence
        self.global_budget = budget          # 外側の検証に実際に渡した UpdateBudget (入口 U の呼出し / 評価の準備の枠、案 B)
        self.total = [budget.logical_limit, 0]   # outer_global の /logical_limit
        self.frame_ids = []                  # 認証中の Q* の Point (frames と同じ並び = 実 active の親鎖)
        self.frame_budgets = []              # 各 frame の Q* が保存した UpdateBudget (再生に実際に渡した値)
        self.all_events = []                 # outer_global の窓: 外側の検証の開始からの全出来事 (戻さない)
        self.frames = []      # 認証中の Q* ごとの [保存した予算の上限, 計数]
        self.used = [set()]   # 認証中の Q* ごとの、型つき参照で実際に読んだ記録 (必須閉包 C の材料)
        self.active = set()   # 認証中の Q* (循環を成功で打ち切らない、REF-7)
        self.checked = {}     # Q* の Point → 当てた A1 の項目の ID
        self.atoms = {}       # Q* の Point → 機械で通った原子の ID (表の行の評価の結果。印は実行の結果であって代用ではない)
        self.events = []      # 認証中の Q* ごとの仕事の出来事 [(kind, unit)] (全 active frame と外側に同じ消費を累積)
        self.parents = {}     # Q* の Point → それが見える親の像 (Q* 自身の本文はここで読む。自分の部分像には無い)
        self.compiler = None  # 評価の頭の compiler (adopted_belief が置く。compiler_field の source)
        self.stages = {}      # Q* の Point → この認証の段階 (when の stage が見る)
        self.effects = {}     # (効果の名前, Q* の Point) → 実行の場所で捕捉した実値 (表の EFFECTS。期待値から作らない)
        self.root = None      # 当該操作の固定根 Xuse (use_view の値): 入口 U は今の Q* の数値の像 (最初の authenticate が置く)、
        # 評価の準備は compiler の見える範囲 (adopted_belief が置く)。前の系列の Q* の像では代用しない
        self.replays = {}     # Q* の Point → 一次事実 (モデル・順の観測・保存した予算・prior の再帰) から再計算した結果

    def done(self, point, *ids):
        self.checked.setdefault(point, set()).update(ids)

    def work(self, kind, domain=None):
        """論理の仕事の出来事 1 つ (logical_work/1)。実行の順と反復を保ち、認証中の全部の Q* の列に足す。domain は厳密な
        算術の出来事の値域 (integer / rational、演算の場所で被演算子の型から。規則の表 BUDGET_EVENT_KINDS の domains)。"""
        unit = self.UNITS[kind]   # 未知の種類は実装の故障 (表に無い出来事を数えない)
        for events in self.events:
            events.append((kind, unit, domain))
        self.all_events.append((kind, unit, domain))
        # 実課金 (Z34 (a)): 発生した出来事を、その時の全 active frame と全体へ 1 回ずつ累積する (子の終了で戻さない、
        # 複製した列を後で合算しない)。上限を超えたらそこで不足 (成功・部分結果を作らない)
        for frame in (*self.frames, self.total):
            frame[1] += unit
            if frame[1] > frame[0]:
                raise _Issue("insufficient", "budget_exhausted", "computation", missing=(
                    VerificationNeed(kind="budget", value={"phase": "computation"}),))

    def evaluate(self, point, env, *row_ids):
        """表 T-A1 の行を機械で評価する (`_fb_a1.check`): 落ちた原子は on_fail で _Issue に写す (不足 → insufficient、
        不適合 → rejected/proof_mismatch、使用の禁止 → insufficient/use_conflict)。通った行に印、通った原子は atoms に。"""
        from . import _fb_a1 as a1, _fb_rules as rules
        for row_id in row_ids:
            try:
                passed = a1.check(rules.A1_RELATIONS[row_id], env)
            except a1.AtomFailure as exc:
                outcome = exc.outcome
                # 行の ID も残す (落ちた原子は行の原子か、その行が呼んだ導出の一覧の本番の原子)
                message = f"{outcome.id}: {outcome.detail}" if outcome.id.startswith(row_id)                     else f"{row_id}: {outcome.id}: {outcome.detail}"
                if outcome.classification == a1.MISMATCH:
                    code = outcome.code or A1_REASON_CODES.get(row_id, "proof_mismatch")
                    raise _Issue("rejected", code, message, evidence=(point,)) from None
                if outcome.classification == a1.FORBIDDEN:
                    raise _Issue("insufficient", "use_conflict", message, evidence=(point,)) from None
                hint_code, hint_need = outcome.hint or (None, None)
                code = hint_code or ("algorithm_unavailable" if "not connected" in outcome.detail
                                     or "not captured" in outcome.detail else "prerequisite_unavailable")
                need = VerificationNeed(**hint_need) if hint_need else VerificationNeed(
                    kind="capability" if code == "algorithm_unavailable" else "evidence",
                    value={"contract": _enc(_c().FINITE_UPDATE_COMPUTE), "purpose": "authentication"}
                    if code == "algorithm_unavailable" else {"target": point, "purpose": "authentication", "contract": None})
                raise _Issue("insufficient", code, message, evidence=(point,), missing=(need,)) from None
            except a1.Unknown as exc:
                raise _Issue("rejected", "missing_contract", f"{row_id}: {exc}", evidence=(point,)) from None
            self.atoms.setdefault(point, set()).update(passed)
            self.done(point, row_id)

    def content(self, image, point, contract):
        self.work("header_read")
        self.work("body_read")
        return _content(image, point, contract, self.used[-1])

    def authenticate(self, point, parent, *, stages=(_STAGE_CURRENT,), chain=False):
        """Q* (point) を、それが見える親の像 parent の中で認証する (A1 の表の全項目)。親の像は最初の読み手か、
        直上の Q* の部分像。stages はこの Q* に当てる段階 (今の Q* は更新の再構成だけ、前の系列の Q* は結果の生成・
        取得・採用も、評価の頭は評価の頭も)。返すのは `_Auth`。"""
        from ._f_world import capture_reader, registry_view_key
        from .f import FIncomplete, FReplayUnavailable
        c = _c()
        if point in self.active:
            raise _Issue("rejected", "shape", "the update chain refers back to itself", evidence=(point,))
        self.work("header_read")
        self.work("body_read")
        try:
            record = parent.record(point)   # 点の同一性と本文の一致 (CID・header・seal・bytes) は像の読みが確かめる
        except KeyError:
            raise _Issue("rejected", "unresolved_reference", "request outside the reader", evidence=(point,)) from None
        except FReplayUnavailable as exc:
            raise _Issue("insufficient", "missing_input", f"request body is not readable: {exc}", evidence=(point,),
                         missing=(VerificationNeed(kind="evidence", value={"target": point, "purpose": "body",
                                                                          "contract": None}),)) from None
        if record.body.contract != c.WORK_REQUESTED:
            raise _Issue("rejected", "reference_kind", "not a work request", evidence=(point,))
        desc = record.body.content.as_json()["desc"]
        args = desc.get("args")
        self.parents[point], self.stages[point] = parent, stages
        if not hasattr(desc, "items"):
            raise _Issue("rejected", "shape", "request without a desc", fields=("/desc",), evidence=(point,))
        # 要求の意味 (A1-REQUEST: 用途・方法と版・返答の契約・args の形) は表の行を機械で (今・前・頭の別で省かない)
        self.evaluate(point, self._env(parent, parent, point, desc), "A1-REQUEST")
        # 形 (A1-SHAPE) は表の行が読んだ各記録に当てる (A1_EVALUATED_RECORDS)。ここでは Q* 自身の形を同じ検査
        # (`_fb_shapes`) で先に確かめ、壊れた要求を後の読みで例外にしない (印は置かない)
        self._check_shape(point, record)
        stored = _decode_budget(args["budget"])
        # 能力 (A1-CAPABILITY-DECLARATION / IMPLEMENTATION) は表の行で: 使う契約を一次本文から導いて registry と比べる
        view = desc["numerical_view"]
        try:
            sub = capture_reader(_Sub(parent, frozenset(view["boundary"])), stored.numerical)
        except (KeyError, FReplayUnavailable):
            raise _Issue("rejected", "unresolved_reference", "numerical view outside the reader",
                         evidence=(point,)) from None
        except FIncomplete:
            raise _Issue("insufficient", "budget_exhausted", "reader", evidence=(point,), missing=(
                VerificationNeed(kind="budget", value={"phase": "reader"}),)) from None
        if self.root is None:
            self.root = sub   # 入口 U の固定根 = 今の Q* の数値の像 (前の系列の Q* はこの中から作る)
        # 固定像・部分像・像の鍵 (A1-FIXED-VIEW・NESTED-VIEW・VIEW-KEY) は表の行を機械で (authenticate の終わり、
        # 実際に読んだ Point = numerical_reads の効果が揃ってから)
        # registry (A1-REGISTRY): 実際に使う registry の identity を効果として捕捉し、表の行が保存 key と突き合わせる
        # (未知の registry_key を今の registry に置き換えない、§19-10)
        self.effects["registry_key", point] = registry_view_key(self.registry)
        self.evaluate(point, self._env(parent, sub, point, desc), "A1-REGISTRY")
        # この Q* の再生に実際に渡した予算 (A1-BUDGET-SAVED の表の行が保存した予算と比べる。キャッシュを置かないことは
        # A1-BUDGET-CACHE の表の行で)
        self.effects["replay_budget", point] = _enc(stored)
        self.active.add(point)
        self.frames.append([stored.logical_limit, 0])
        self.frame_ids.append(point)
        self.frame_budgets.append(stored)
        self.used.append(set())
        self.events.append([])
        self.effects["counting_rule", point] = {"method": _enc(c.FINITE_UPDATE_COMPUTE), "unit": self.COUNTING_UNIT}
        try:
            obligations = mandatory_obligations(sub, point, {"desc": desc, "inputs": list(record.body.inputs)})
            required = set(_uses_points(obligations))
            for _ in required:
                self.work("reference_compare")   # 参照候補 1 件の照合
            self._direct_references(sub, point)
            model, origin, prior = args["model"], desc["reader"], args["prior"]
            if prior is None:
                state = self._initial(sub, model)
            else:
                previous = self.adopted(prior, sub, origin=origin, model=model, consumer=desc["work_id"])
                state = previous.state.copy()
                required |= previous.required | previous.inputs
            # A1-C-HISTORY・A1-CHAIN は機械の行 (frame の戻り値・系列の評価) で印を得る。ここで印を置かない (印で通さない)
            applied = []
            for use in args["observations"]:
                self.work("projection_input")   # 観測射影の 1 入力
                self._apply(sub, state, model, use["binding"], use["reading"], point)
                applied.append(use)
            self.effects["observation_sequence", point] = applied   # 実際に数値へ適用した観測の順の列 (A1-I-ALL)
            required |= self.used[-1]
            inputs, resolved_inputs = _check_inputs(sub, point, record.body.inputs, required)
            # 予算の合計 (A1-BUDGET-TOTAL、Z34 (a) C): この Q* の区切りでの実 active の親鎖と outer_global の枠、各枠の窓の
            # 出来事、計装の計数を、同じ区切りで捕捉する (表の行が窓の出来事から独立に数え直して計数と比べる)
            self.effects["budget_frames", point] = [
                *({"identity": fid, "budget": _enc(fb)} for fid, fb in zip(self.frame_ids, self.frame_budgets)),
                {"identity": "outer_global", "budget": _enc(self.global_budget)}]
            self.effects["frame_events", point] = {
                **{fid: [kind for kind, _u, _d in events] for fid, events in zip(self.frame_ids, self.events)},
                "outer_global": [kind for kind, _u, _d in self.all_events]}
            self.effects["charges", point] = [
                *({"frame": fid, "dimension": "/logical_limit", "used": used, "limit": limit}
                  for fid, (limit, used) in zip(self.frame_ids, self.frames)),
                {"frame": "outer_global", "dimension": "/logical_limit", "used": self.total[1], "limit": self.total[0]}]
            self.effects["global_budget", point] = _enc(self.global_budget)
            # 今の Q* の R*・G・A* との対応は、この Q* が前の系列として使われる時に当たる (未来を要求しない、REF-7。
            # a1_applicable が今の Q* には results・history の行を当てない)
            # 表の行を機械で評価する (①-c、紙 v0.35 Z28)。実効果は上で実行の場所に捕捉したもの
            events = self.events[-1]
            self.effects["work_events", point] = [{"kind": kind} if domain is None else {"kind": kind, "domain": domain}
                                                  for kind, _unit, domain in events]
            self.effects["unit_charges", point] = [unit for _kind, unit, _domain in events]
            self.effects["numerical_view", point] = sub                      # 実際に数値の再構成に渡した像
            self.effects["numerical_reads", point] = sorted(self.used[-1])   # その再構成で実際に読んだ Point
            self.replays[point] = {"result": _encode_result(state),
                                   "application_digest": state.digest(args["model"], desc["reader"])}
            # この frame が親へ返す実値は、親 (呼び出した側) が受け取った所で効果 recursive_return に捕捉する (`_frame_return`)
            self.evaluate(point, self._env(parent, sub, point, desc), *A1_EVALUATED)
            if _STAGE_HEAD in stages:
                self.evaluate(point, self._env(parent, sub, point, desc), *A1_EVALUATED_HEAD)
            # 記録の同一性 (A1-BODY-MISSING・IDENTITY) は読んだ各 record に (Q* は親の像、他は数値の像で読む)
            for record_point in sorted({point} | required | inputs):
                image = parent if record_point == point else sub
                self.evaluate(point, self._records_env(image, record_point, parent, point), *A1_EVALUATED_RECORDS)
        finally:
            self.used.pop()
            self.frames.pop()
            self.frame_ids.pop()
            self.frame_budgets.pop()
            self.events.pop()
            self.active.discard(point)
        # 系列の項目 (使う前の採用系列) は adopted() が R*・G・A* との対応を当てた後に集約する。frame の戻り値の行は
        # 呼び出した側が受け取った後に (`_frame_return`)
        missing = a1_applicable(stages, chain=False) - self.checked.get(point, set()) - set(A1_EVALUATED_RETURN)
        if missing:
            raise _Issue("insufficient", "algorithm_unavailable",
                         "A1 obligations without a check: " + ", ".join(sorted(missing)), evidence=(point,),
                         missing=(VerificationNeed(kind="capability", value={
                             "contract": _enc(c.FINITE_UPDATE_COMPUTE), "purpose": "authentication"}),))
        from ._fb_derivations import obligation_record
        return _Auth(state, sub, desc, required, inputs, resolved_inputs,
                     [obligation_record(ob, ob.contract) for ob in obligations])

    def _frame_return(self, point, auth):
        """呼び出した側が frame の戻り値を受け取った所: 実際に受け取った値を効果 recursive_return に捕捉し (期待値から作らない、
        EFFECTS.recursive_return)、frame の戻り値の行 (A1-C-HISTORY・A1-BUDGET-CACHE) を当てる。比べる相手は一次の事実からの
        再計算 (replay_result = その Q* を認証した時の計算)・独立に導いた閉包・解決した I・認証済みの参照。"""
        c = _c()
        desc = auth.desc
        self.effects["recursive_return", point] = {
            "result": _encode_result(auth.state), "application_digest": auth.state.digest(desc["args"]["model"], desc["reader"]),
            "closure": sorted(auth.required), "resolved_inputs": auth.resolved_inputs,
            "authenticated_refs": auth.authenticated_refs}
        self.evaluate(point, self._env(self.parents[point], auth.sub, point, desc), *A1_EVALUATED_RETURN)
        missing = (a1_applicable(self.stages.get(point, ()), chain=False) & set(A1_EVALUATED_RETURN)) \
            - self.checked.get(point, set())
        if missing:
            raise _Issue("insufficient", "algorithm_unavailable",
                         "A1 obligations without a check: " + ", ".join(sorted(missing)), evidence=(point,),
                         missing=(VerificationNeed(kind="capability", value={
                             "contract": _enc(c.FINITE_UPDATE_COMPUTE), "purpose": "authentication"}),))

    def _direct_references(self, sub, point):
        """Q* の直の参照義務 (T-REF の行を Q* の本文に直接当てたもの) を処理し、実際に処理した義務を効果として捕捉する
        (A1-DIRECT-REFS の左。同じ Point を指す別の欄も別の義務、Point の集合に潰さない)。到達先は部分像の中で読めること。"""
        from . import _fb_uses as uses
        from ._fb_derivations import direct_obligations
        reader = uses.Reader(sub)
        try:
            _contract, document = uses.Reader(self.parents[point]).document(point)
            processed = []
            for obligation in direct_obligations(reader, point, document):
                target = obligation["reference"] if obligation["reference_kind"] == "Point" else None
                if target is not None and isinstance(target, str):
                    sub.entry(target)   # 到達先が部分像の中に在る (無ければ KeyError = 解決できない)
                processed.append(obligation)
        except (uses.Unresolved, KeyError) as exc:
            raise _Issue("rejected", "unresolved_reference", f"direct reference outside the view: {exc}",
                         evidence=(point,)) from None
        except uses.Unsupported as exc:
            raise _Issue("rejected", "missing_contract", str(exc), evidence=(point,)) from None
        except uses.Malformed as exc:
            raise _Issue("rejected", "shape", str(exc), evidence=(point,)) from None
        self.effects["reference_obligations", point] = processed

    def _history_env(self, image, adopted, a):
        """系列の行の評価の主語 (scope history): A* とその request (Q*)・result (R*)・acquisition (G)、独立の観測。"""
        from . import _fb_a1 as a1, _fb_uses as uses
        reader = uses.Reader(image, self.evidence)
        records = {}
        for name, point in (("A*", adopted), ("Q*", a["request"]), ("R*", a["result"]), ("G", a["acquisition"])):
            try:
                records[name] = (point, reader.document(point)[1])
            except uses.Unresolved:
                pass   # 読めなければ束縛しない (その記録を使う原子は不足で落ちる)
        return a1.Env(records, evidence=self.evidence, reader=reader, effects=self.effects,
                      stages=self.stages.get(a["request"], ()), registry=self.registry, compiler=self.compiler,
                      replays=self.replays, use_view=self.root)

    def _results_env(self, image, q, result):
        """結果の行の主語 (scope results): Q* (親の像で読む) と R* (A* の像で読む)。"""
        from . import _fb_a1 as a1, _fb_uses as uses
        reader = uses.Reader(self.parents[q], self.evidence)
        records = {"Q*": (q, reader.document(q)[1]), "R*": (result, uses.Reader(image, self.evidence).document(result)[1])}
        return a1.Env(records, evidence=self.evidence, reader=reader, effects=self.effects,
                      stages=self.stages.get(q, ()), registry=self.registry, compiler=self.compiler,
                      replays=self.replays, use_view=self.root)

    def _records_env(self, image, record_point, parent, point):
        """記録の同一性の行の主語 (scope records): Record = 読んだ record 1 つ (像 image で読む)、Q* = 認証中の要求。
        Record が読めなければ束縛しない (A1-BODY-MISSING の present が不足で落とす。対象から消さない)。"""
        from . import _fb_a1 as a1, _fb_uses as uses
        reader = uses.Reader(image, self.evidence)
        records = {"Q*": (point, uses.Reader(parent, self.evidence).document(point)[1])}
        try:
            records["Record"] = (record_point, reader.document(record_point)[1])
        except uses.Unresolved:
            pass
        return a1.Env(records, evidence=self.evidence, reader=reader, effects=self.effects,
                      stages=self.stages.get(point, ()), registry=self.registry, compiler=self.compiler,
                      replays=self.replays, use_view=self.root)

    def _env(self, parent, sub, point, desc):
        """表の行の評価の主語 (`_fb_a1.Env`): Q* (親の像で読む) と Origin (部分像の knowledge_origin)、独立の観測、捕捉した効果。"""
        from . import _fb_a1 as a1, _fb_uses as uses
        reader = uses.Reader(parent, self.evidence)
        try:
            _contract, q_document = reader.document(point)
        except uses.Unresolved as exc:
            # 外側の inputs (Ref) が像の中で 1 つの Point に解決しない = 要求の参照が解決できない (§19-2、旧 _check_inputs と同じ分類)
            raise _Issue("rejected", "unresolved_reference", f"Q* names a record outside its reader: {exc}",
                         fields=("/inputs",), evidence=(point,)) from None
        records = {"Q*": (point, q_document)}
        origin = desc.get("reader")
        if origin is not None:
            try:
                _c_, origin_document = uses.Reader(sub, self.evidence).document(origin)
                records["Origin"] = (origin, origin_document)
            except uses.Unresolved:
                pass   # 読めなければ束縛しない (Origin を使う原子は不足で落ちる)
        return a1.Env(records, evidence=self.evidence, reader=reader, effects=self.effects,
                      stages=self.stages.get(point, ()), registry=self.registry, compiler=self.compiler,
                      replays=self.replays, use_view=self.root)

    def _observation_env(self, image, q, binding, reading, b, law_point):
        """観測の対の評価の主語 (`_fb_a1.Env`、scope observations)。Started/Ended は B.generation の非 null のものだけ束縛する
        (無ければ when nonnull が偽で原子は非適用)。"""
        from . import _fb_a1 as a1, _fb_uses as uses
        reader = uses.Reader(image, self.evidence)
        records = {"Q*": (q, uses.Reader(self.parents[q], self.evidence).document(q)[1])}
        for name, point in (("B", binding), ("Reading", reading), ("Law", law_point), ("Claim", b["report"]),
                            ("K", b["segment"]), ("Route", b["route"]), ("Started", b["generation"].get("started")),
                            ("Ended", b["generation"].get("ended"))):
            if point is not None:
                records[name] = (point, reader.document(point)[1])
        return a1.Env(records, evidence=self.evidence, reader=reader, effects=self.effects,
                      stages=self.stages.get(q, ()), registry=self.registry, compiler=self.compiler,
                      replays=self.replays, use_view=self.root)

    def _check_shape(self, point, record):
        """Q* の記録の形 (`_fb_shapes.shape_of_record`、紙 F-b Z33 ③ (c))。違反は rejected (その kind)。"""
        from ._fb_shapes import shape_of_record
        violations = shape_of_record("sui.fb.work_requested/1", record, record.body.content.as_json())
        if violations:
            first = violations[0]
            raise _Issue("rejected", first["kind"] if first["kind"] in _REJECT_CODES else "shape",
                         f"request is not a work request of this version: {first['detail']}",
                         fields=(first["field"] or "/",), evidence=(point,))

    def adopted(self, adopted, image, *, origin, model, consumer=None, head=False):
        """前の採用 A* (像 image の中) とその系列: A* の origin・model、A*.request の Q* の認証 (同じ全項目、段階は
        結果の生成・取得・採用も)、A*.previous = Q*.prior、R* と G の全照合 (§19-3・§19-10・R04)。consumer は A* を
        使う側の仕事の WorkId (入口 U の prior。評価の頭では None)、head は評価の頭。返すのは Q* の `_Auth`。"""
        c = _c()
        a = self.content(image, adopted, c.BELIEF_ADOPTED)
        if a["origin"] != origin or a["model"] != model:
            raise _Issue("rejected", "proof_mismatch", "adoption of another origin or model", evidence=(adopted,))
        stages = (*_PRIOR_STAGES, _STAGE_HEAD) if head else _PRIOR_STAGES
        auth = self.authenticate(a["request"], image, stages=stages, chain=True)
        self._frame_return(a["request"], auth)
        desc = auth.desc
        if desc["args"]["prior"] != a["previous"] or desc["reader"] != origin or desc["args"]["model"] != model:
            raise _Issue("rejected", "proof_mismatch", "adoption does not follow its request", evidence=(adopted,))
        self.check_adoption(image, a, desc, auth.state)
        self._check_chain_evidence(image, adopted, a, desc, consumer)
        q = a["request"]
        missing = a1_applicable(stages, chain=True) - self.checked.get(q, set())
        if missing:
            raise _Issue("insufficient", "algorithm_unavailable",
                         "A1 obligations without a check: " + ", ".join(sorted(missing)), evidence=(q,),
                         missing=(VerificationNeed(kind="capability", value={
                             "contract": _enc(c.FINITE_UPDATE_COMPUTE), "purpose": "authentication"}),))
        return auth

    def _check_chain_evidence(self, image, adopted, a, desc, consumer):
        """A1「実取得・実使用」「採用した結果との対応」の独立の観測の側 (紙 v0.31 の読みの決定、FB3-R04-R4、
        A1-HISTORY-*): 保存された R*・G の本文が正しいだけでは足りず、(1) その Q* の仕事 Wu が実際に入場し (EW)、
        R* の値を載せた終わり (R*.basis の最初の終わり) がその Wu の口から実際に返った (EH)、(2) origin が R* を
        実際に取得した (EA)、(3) 生成 g ≤ 取得 a ≤ A* 自身の時刻で、G は A* の実祖先 (評価の頭でも省かない、
        FB3-R04-R5)、(4) 使う側の仕事 (consumer) があれば、その取得が使う側の A*/R* の実使用より前。
        台帳の自己申告 (R* の request・G の contents・終わりの名乗り) はこの確かめの代わりにしない。無ければ不足。"""
        q = a["request"]
        # 系列の行のうち機械で評価する分 (A1-HISTORY-ENTER / ENTER-MISMATCH / RETURN-MISSING / ACQUIRE / ACQUIRE-MISSING、
        # 対象 = history: A*・Q*・R*・G と独立の観測)。手書きの同じ検査は消した (①-c、紙 v0.35 Z28)
        self.evaluate(q, self._history_env(image, adopted, a), *A1_EVALUATED_HISTORY)
        # R* の値を載せた終わり (最初の報告) がこの Wu の口から返り、その issued の値が R* の result と同じ (A1-HISTORY-RETURN)
        # も上の表の行で。(3) 生成 g ≤ 取得 a ≤ A*.at、G は A* の実祖先 (A1-HISTORY-ACQUIRE-BEFORE-ADOPT) は表の原子で (上の evaluate)

    def check_adoption(self, image, a, desc, state):
        """R* の要求・結果・application_digest・像・registry、R* の生成の根拠 (basis = {Q*, 最初の終わり} で、その終わりが
        Q* の仕事の issued の返答で値が R* と同じ、K8)、A* の取得 G が同じ origin の R* の取得であること (A1 の「採用した
        結果との対応」)。R* の数値は一次事実から計算し直して比べるので、R* の値・生成の観測を正解にしない。"""
        from .f import ContractValue, _dumps
        from .f_contracts import CONTENT_ACQUIRED
        from ._fb_wire import encode
        c = _c()
        q = a["request"]
        result = self.content(image, a["result"], c.UPDATE_RESULT)
        if result["request"] != q:
            raise _Issue("rejected", "result_mismatch", "stored result is for another request",
                         fields=("/args/prior",), evidence=(a["result"],))
        # R* の値・application_digest・像・registry と一次事実からの再計算の対応 (A1-RESULT-ALL・NUMERICAL-REPLAY) は表の行で
        self.evaluate(q, self._results_env(image, q, a["result"]), *A1_EVALUATED_RESULTS)
        basis = _basis(image, a["result"])
        first = [p for p in basis if p != q]
        if len(basis) != 2 or q not in basis or len(first) != 1:
            raise _Issue("rejected", "proof_mismatch", "result basis is not its request and first end",
                         evidence=(a["result"],))
        report = self.content(image, first[0], c.WORK_REPORT)
        issued = encode(ContractValue(contract=c.UPDATE_RESPONSE, value={"kind": "issued", "value": result["result"]}))
        if report["work"] != desc["work_id"] or report["outcome"].get("kind") != "outputs" \
                or _dumps(report["outcome"]["value"]) != _dumps(issued):
            raise _Issue("rejected", "proof_mismatch", "result not generated by its update work", evidence=(first[0],))
        acquired = self.content(image, a["acquisition"], CONTENT_ACQUIRED)
        if acquired["origin"] != a["origin"] or a["result"] not in acquired["contents"]:
            raise _Issue("rejected", "proof_mismatch", "adoption without the origin's acquisition of R*",
                         fields=("/args/prior",), evidence=(a["acquisition"],))

    def _initial(self, image, model):
        from .f import _Fraction, _decode
        self.used[-1].add(model)
        try:
            content = image.record(model).body.content.as_json()
        except KeyError:
            raise _Issue("rejected", "unresolved_reference", f"{model} is outside the reader", evidence=()) from None
        # 型の違う記録を model と名指した Q* は例外で外へ出さず不適合に (K1b REF-Q-MODEL)
        document = content.get("document") if hasattr(content, "items") else None
        if not hasattr(document, "items") or "initial" not in document:
            raise _Issue("rejected", "reference_kind", f"{model} is not a model with an initial state",
                         fields=("/args/model",), evidence=(model,))
        return _State(_decode(document["initial"], tuple[_Fraction, ...]))

    def _apply(self, image, state, model, binding, reading, q):
        from . import _f_count as count
        from .f import CoverageClaim, FInputError as _Err, FModelFalsified, _Fraction, _decode
        c = _c()
        b = self.content(image, binding, c.SEGMENT_BINDING)
        plan = self.content(image, reading, c.OBSERVATION_PLAN_2)
        if plan["model"] != model:
            raise _Issue("rejected", "observation_binding_mismatch", "reading of another model", evidence=(reading,))
        projection, generation = plan["projection"], plan["generation"]
        if projection["contract"] != _enc(c.FINITE_SEGMENT_PROJECTION) \
                or b["reading_contract"] != projection["contract"]:
            raise _Issue("rejected", "missing_contract", "projection", evidence=(reading, binding))
        pargs = projection["args"]
        if pargs.get("frame") is not None or pargs.get("time_projection") != {
                "contract": _enc(c.SEGMENT_VALUE_ONLY), "args": {}}:
            raise _Issue("rejected", "missing_contract", "frame or time projection", evidence=(reading,))
        if generation != {"contract": _enc(c.BOOTSTRAP_GENERATION), "args": {"scope": "whole_window"}}:
            raise _Issue("rejected", "missing_contract", "generation", evidence=(reading,))
        report = self.content(image, b["report"], c.SEGMENT_REPORT)
        item = report["item"]
        if item["kind"] != "claim":
            raise _Issue("rejected", "missing_contract", "only claims are read", evidence=(b["report"],))
        claim = _decode(item["value"], CoverageClaim)
        # 実際に使う Claim の意味の能力は A1-CAPABILITY-* の表の行が一次本文から導いて registry と比べる (R02-R2b)
        meaning = _meanings().get((claim.contract.name, claim.contract.version))
        entries = [e for e in pargs["claims"] if e["meaning"] == _enc(claim.contract)]
        if meaning is None or meaning[0] != claim.kind or len(entries) != 1:
            raise _Issue("rejected", "missing_contract", "claim meaning", evidence=(b["report"], reading))
        entry = entries[0]
        law_point = entry["law"]
        if state.law_point is not None and state.law_point != law_point:
            raise _Issue("rejected", "missing_contract", "one count-law series (extends is not read)",
                         evidence=(law_point,))
        law = self.content(image, law_point, c.FINITE_JOINT_COUNT_LAW)
        if law["model"] != model or law["extends"] is not None \
                or law["frame_relation"] != "independent_given_carrier":
            raise _Issue("rejected", "missing_contract", "count law", evidence=(law_point,))
        k = self.content(image, b["segment"], c.SEGMENT_REQUESTED)["desc"]
        # 原 Claim から channel への対応は一意 (§19-1 FB23-R04・R06): 過程・route が合う channel が法則に
        # 2 つ以上あれば、その法則はこの原 Claim の読み方に使えない (reading が指す id で先に絞らない)
        matching = [ch for ch in law["channels"] if b["route"] in ch["route_configs"] and k["process"] == ch["process"]]
        if len(matching) != 1:
            raise _Issue("rejected", "shape", "claim channel is not unique in the law", evidence=(law_point,))
        if matching[0]["id"] != entry["channel"]:
            raise _Issue("rejected", "observation_binding_mismatch", "channel route or process",
                         evidence=(binding, law_point))
        self.content(image, b["route"], _route_contract())
        for name in ("started", "ended"):   # 生成の境界の記録も実際に読んだ記録 (必須閉包の材料)
            if b["generation"].get(name) is not None:
                self.content(image, b["generation"][name], c.SEGMENT_REPORT)
        for source in b["clock"]:
            self.used[-1].add(source)
        # K の実行の札 (効果 execution_occurrence): ホストの工場が仕事表の行を置いた時に、その行の保存した要求 (K) と結んで
        # 発行した札を、運んだ観測の要求の対応から取る (正本 EFFECTS.execution_occurrence)。2 つ以上なら札を選ばない
        owners = [e.execution_occurrence for e in self.evidence.executions if e.request == b["segment"]]
        if len(owners) == 1:
            self.effects["execution_occurrence", b["segment"]] = owners[0]
        elif owners:
            raise _Issue("rejected", "observation_binding_mismatch", "several executions claim the measuring request",
                         evidence=(b["segment"],))
        # 観測の対ごとの表の行を機械で評価する (対象 = observations: Q*・B・Reading・Law・Claim・K・Route・Started・Ended)
        self.evaluate(q, self._observation_env(image, q, binding, reading, b, law_point), *A1_EVALUATED_PER_OBSERVATION)
        try:
            if state.law is None:
                if len(law["carrier_by_state"]) != len(state.joint):
                    raise _Err("shape", "carrier_by_state length", "/carrier_by_state")
                state.law = count.check_law(
                    law["carrier_by_state"], {ch["id"]: _span(ch["domain"]) for ch in law["channels"]},
                    [([(m["channel"], m["time_ns"], m["count"]) for m in row["marks"]],
                      [_decode(q_, _Fraction) for q_ in row["mass"]]) for row in law["rows"]])
                state.carrier_by_state, state.law_point = tuple(law["carrier_by_state"]), law_point
            predicate = count.Predicate(channel=entry["channel"], span=_span(_enc(claim.interval)),
                                        lower=meaning[1], upper=meaning[2])
            count.check_predicate(state.law, predicate)
            self._support_read(image, q, binding, reading, b, law_point)
            key = (b["segment"], report["item_slot"])
            known = state.applied.get(key)
            if known is not None:
                if known != predicate:   # 同じ原 Claim を別の命題として足さない (CL-APPLY)
                    raise _Issue("rejected", "measurement_conflict", "same claim read differently",
                                 evidence=(b["report"],))
                return   # 同じ原 Claim は 1 つの導出系列で 1 つの出来事 (再配送・別の B は no-op)
            # 仕事は出来事ごとに work() が数える (旧の一括式の課金はしない = 二重に数えない、Z34 (a))
            state.joint, state.mass = count.condition(state.joint, state.mass, state.carrier_by_state,
                                                      state.law, tuple(state.applied.values()), predicate,
                                                      work=self.work)
            state.applied[key] = predicate
        except _Err as exc:
            raise _Issue("rejected", exc.reason if exc.reason in _REJECT_CODES else "shape", str(exc),
                         evidence=(binding,)) from None
        except FModelFalsified as exc:
            raise _Issue("rejected", "model_falsified", str(exc), evidence=(binding,)) from None

    def _support_read(self, image, q, binding, reading, b, law_point):
        """Support の証人 (固定像の中で Claim の窓を覆う monitor_span) を実際に読んだ記録に足す (必須閉包の材料)。照合は
        A1-SUPPORT の表の行 (ホストの監視の実観測と、`_fb_derivations.support`)。"""
        from ._fb_derivations import _support_witness
        env = self._observation_env(image, q, binding, reading, b, law_point)
        witness = _support_witness(env, b, env.document("Claim"))
        if isinstance(witness, tuple):
            self.content(image, witness[0], _c().MONITOR_SPAN)


def _basis(image, point) -> tuple:
    """Prediction の外側の basis を像の中の Point に解決する (Ref の解決が一意でなければ不適合)。"""
    from ._fb_uses import Reader, Unresolved
    reader = Reader(image)
    try:
        _contract, document = reader.document(point)
        return reader.points(document.get("basis", ()))   # 外側の basis は保存した Ref。ここで像の中の Point に解く
    except Unresolved as exc:
        raise _Issue("rejected", "unresolved_reference", f"{exc} is not resolvable", evidence=()) from None


def _decode_budget(value):
    from .f import _decode
    return _decode(value, UpdateBudget)


def _check_inputs(sub, request, inputs, required):
    """§19-2: Q* の外側 inputs I は重複なし (集合にする前に拒む)、全項が Q* の固定像の中で 1 つの Point に解決し、
    独立に導いた必須閉包 C が I に全部入る (C ⊆ I、Point で比べる)。余分でも実在する I は通す。返すのは解決した I の
    Point の集合と、I の順の解決 [{point, ref, bytes, causal}] (保存した全 bytes と実親、親へ返す frame の値)。"""
    from ._fb_derivations import _payload_json
    refs = tuple(inputs)   # 重複は表の行 A1-I-UNIQUE が落とす (unique)
    present = {}
    for entry in sub.entries():
        present.setdefault(sub.record(entry.cid).id, []).append(entry.cid)
    resolved, ordered = set(), []
    for ref in refs:
        found = present.get(ref, ())
        if len(found) != 1:
            raise _Issue("rejected", "unresolved_reference", "Q* inputs name a record outside its fixed view",
                         fields=("/inputs",), evidence=(request,))
        resolved.add(found[0])
        _salt, payload = sub.sealed_content(found[0])
        ordered.append({"point": found[0], "ref": str(ref), "bytes": _payload_json(payload),
                        "causal": sorted(sub.entry(found[0]).parents)})
    missing = sorted(p for p in required - {request} if p not in resolved)
    if missing:
        raise _Issue("rejected", "unresolved_reference", "Q* inputs omit a required record",
                     fields=("/inputs",), evidence=missing)
    return frozenset(resolved), ordered


def _route_contract():
    from .f_contracts import ROUTE_CONFIG
    return ROUTE_CONFIG


def update_response(ret: UpdateReturn) -> ContractValue:
    """Wu の係が U の返答を `WorkOutputs.outputs` の値に包む (§6-10 K7): `sui.fb.update_response/1` =
    {kind: issued, value: finite_update_result/1 の値} / {kind: rejected | insufficient, value: [issue]}。
    issued の時は係が同じ IssuedUpdate を post の issued に添える (値だけでは成功にならない)。"""
    from .fb_contracts import UPDATE_RESPONSE
    if isinstance(ret, IssuedUpdate):
        return ContractValue(contract=UPDATE_RESPONSE, value={"kind": "issued", "value": ret.result})
    if isinstance(ret, (Rejected, Insufficient)):
        return ContractValue(contract=UPDATE_RESPONSE, value={
            "kind": "rejected" if isinstance(ret, Rejected) else "insufficient",
            "value": [_issue(issue) for issue in ret.issues]})
    raise TypeError("UpdateReturn expected")


def _issue(issue) -> ImmutableJSON:
    out = {"code": issue.code, "fields": list(issue.fields), "evidence": sorted(issue.evidence),
           "message": issue.message}
    if isinstance(issue, InsufficientIssue):
        from ._fb_wire import encode
        out["missing"] = [{"kind": need.kind, "value": encode(need.value)} for need in issue.missing]
    return out


def prepare_fb_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point,
    candidate_ref: Point, preference_refs: tuple[Point, ...], scope_request, context_ref: Point,
    registry: FRegistry, method, budget: RateBudget, replay_logical_limit: int, evidence: TargetEvidence,
):
    """F-b の評価の準備の入口 (§6-10 J7・Z8)。F-a の `prepare_f_from_facts` と同じ引数・同じ compiler
    (`sui.f.prepare_world/3`)・同じ発行物で、加えて同じプロセスの中の独立の観測 evidence (`TargetEvidence`) を
    compiler に運ぶ。固定根の中に読み手の F-b の採用 A* があれば、`adopted_belief` がその観測で出どころと今の
    食い違いを確かめる。A* が無い入力では evidence を読まず、F-a の入口と同じ結果。F-a の公開の入口の形は変えない
    (F-a の入口で A* を読むと、観測が無いので不足の NoDecision)。evidence は発行物に保存しない。"""
    from .f import FInputError
    from .f_facts import _prepare_facts
    if not isinstance(evidence, TargetEvidence):
        raise FInputError("shape", "TargetEvidence expected", "/evidence")
    # 採用の系列を作り直す全体の枠 = この呼出しに実際に渡した論理の上限と数値計算の予算 (Z34 (a) 案 B、正本 v1.3.6)。
    # 頭の Q* や各 Q* の保存予算から補わない
    replay_budget = UpdateBudget(contract=_c().UPDATE_BUDGET, logical_limit=replay_logical_limit, numerical=budget)
    return _prepare_facts(reader, fixed_parents=fixed_parents, model_ref=model_ref, candidate_ref=candidate_ref,
                          preference_refs=preference_refs, scope_request=scope_request, context_ref=context_ref,
                          registry=registry, method=method, budget=budget, fb_evidence=evidence,
                          fb_replay_budget=replay_budget)


# 読み直し (replay) の印: 発行物からの再生は独立の観測を運べない (f_facts の再生がこれを渡す)
EVIDENCE_NOT_CARRIED = object()


def adopted_belief(compiler):
    """F-a の評価の準備 (`sui.f.prepare_world/3`) が、固定根の中の読み手の F-b の採用 A* を読む口 (§6-10 J7・K12・
    「評価の準備は保存台帳だけでは同じ判定にならない」)。A* が無ければ None (旧の道のまま)。あれば系列の頭を 1 つに
    決め (2 つなら競合で不完全)、頭の A* から入口 U と同じ認証 (`_Replay.adopted`) を当て、今の食い違いを評価の
    固定根を Xuse として、入口から運んだ独立の観測 (compiler.fb_evidence) で出どころを確かめた原報告で検査して、
    (R* の Ref, joint) を返す。失敗の分類は保つ (A4): 不足・使用の禁止 → FIncomplete (NoDecision)、意味の不足 →
    FSpecificationMissing、モデルの反証 → FModelFalsified、確定した不一致 → FInputError (理由の語のまま)。"""
    from .f import FIncomplete, FInputError as _Err, FModelFalsified, FSpecificationMissing
    c = _c()
    view = _Visible(compiler)
    adoptions = {}
    for entry in view.entries():
        # 探すだけの読みは像から (依存に数えない。A* の無い入力の world を 1 バイトも変えない)
        if view.peek(entry.cid).body.contract != c.BELIEF_ADOPTED:
            continue
        value = view.record(entry.cid).body.content.as_json()
        if value["origin"] == compiler.origin_point:
            adoptions[entry.cid] = value
    if not adoptions:
        return None
    heads = set(adoptions) - {a["previous"] for a in adoptions.values()}
    if len(heads) != 1:
        raise FIncomplete("certificate_incomplete", "competing F-b adoptions", "/adoption")
    head = next(iter(heads))
    evidence = getattr(compiler, "fb_evidence", None)
    if evidence is EVIDENCE_NOT_CARRIED:
        # 発行物の bytes からの読み直し (f_facts の再生) は独立の観測を運べない。再確認できないことと確定した改変は
        # 別 (A4): 再生の不足として返し、結果の不一致に倒さない (FB3-DIAG-R5)
        from .f import FReplayUnavailable
        raise FReplayUnavailable("prerequisite_unavailable",
                                 "independent observations of the F-b adoption are not carried by the artifact",
                                 "/adoption")
    if evidence is None:
        # 封筒との対応・入場は台帳だけで確かめられない (紙 :2089〜2092)。保存 JSON から復元しない
        raise FIncomplete("prerequisite_unavailable", "independent observations of the F-b adoption are not held",
                          "/adoption")
    replay_budget = getattr(compiler, "fb_replay_budget", None)
    if replay_budget is None:
        # 観測を運んだ入口なのに作り直しの枠が無いのは入口の故障 (枠を評価の準備の RateBudget から補わない)
        raise FIncomplete("prerequisite_unavailable", "the replay budget of the F-b entrance is not held", "/adoption")
    replay = _Replay(compiler.registry, evidence, replay_budget)
    replay.compiler = compiler
    try:
        replay.root = view
        auth = replay.adopted(head, view, origin=compiler.origin_point, model=compiler.source, head=True)
        _check_use(view, compiler, head, evidence)
    except _Issue as issue:
        if issue.kind == "insufficient":
            raise FIncomplete(issue.code, issue.message, "/adoption") from None
        if issue.code == "missing_contract":
            raise FSpecificationMissing("missing_contract", issue.message, "/adoption") from None
        if issue.code == "model_falsified":
            raise FModelFalsified("model_falsified", issue.message, "/adoption") from None
        raise _Err(issue.code, issue.message, "/adoption") from None
    return view.record(adoptions[head]["result"]).id, auth.state.joint


def _check_use(view, compiler, head, evidence):
    """評価の準備で信念を採る使用 (G6): 頭の A* から信念の用途で UseKeys を取り、評価の固定根 (Xuse) の中の
    保存済みの原報告のうち、独立の観測でその仕事の口から来たと確かめたものの Clashes と照合する (G5)。鍵の仕事の
    観測が無い (出どころの証拠を失った) なら「関係する報告なし」にせず不足。使用の禁止は不足の枝の use_conflict
    (A4: 保存済みの正しい数値があることと、今使えることを別の結果に持つ)。"""
    from . import _fb_uses as uses
    c = _c()
    reader = uses.Reader(view)
    try:
        keys = uses.use_keys(reader, uses.starts_of("評価の準備で信念を採る", {uses.contract_name(c.BELIEF_ADOPTED): head}))
    except uses.Undetermined as exc:
        # 閉包が表の未確定の規則に届いた: 必要な依存が未解決 (不足の枝、FB3-R01-R6)。辺なしにして通さない
        raise _Issue("insufficient", "algorithm_unavailable", str(exc), missing=(VerificationNeed(
            kind="capability", value={"contract": None, "purpose": "reading"}),)) from None
    except uses.Unsupported as exc:
        raise _Issue("rejected", "missing_contract", str(exc)) from None
    except uses.Unresolved as exc:
        raise _Issue("rejected", "unresolved_reference", str(exc)) from None

    def segment_work(segment):
        try:
            contract, content = reader.document(segment)
        except uses.Unresolved:
            return None
        return content["desc"]["work_id"] if contract == uses.contract_name(c.SEGMENT_REQUESTED) else None

    # 原報告の鍵 (item・life・terminal) の仕事: 区間の鍵はその測る仕事、終わりの鍵はその WorkId
    report_keys = {key for key in keys if key[0] in ("item", "life", "terminal")}
    works = {segment_work(key[1]) if key[0] in ("item", "life") else key[1] for key in report_keys}
    observed = {e.work_id: e for e in evidence.executions}
    if any(w is None or w not in observed for w in works):
        raise _Issue("insufficient", "prerequisite_unavailable", "provenance of the adoption's reports is not held",
                     missing=(VerificationNeed(kind="evidence", value={
                         "target": head, "purpose": "adoption_chain", "contract": None}),))
    # 関連の候補は Xuse (評価の固定根) の中の保存済みの原報告を鍵で先に集め (探すだけの読み)、その各候補の
    # 出どころを独立の観測 (EH) で照合する。EH に載った報告から逆算しない (G5、FB3-R01-R4b)。照合できない候補が
    # あれば「関係する報告なし」にせず不足
    confirmed = {r.point: e.work_id for e in evidence.executions for r in e.reports if r.point is not None}
    deliveries, unconfirmed = [], []
    for entry in view.entries():
        peeked = view.peek(entry.cid).body
        if uses.contract_name(peeked.contract) not in uses._REPORTS:
            continue
        content = peeked.content.as_json()
        try:
            found_keys, _unsupported = uses.keys_of(uses.contract_name(peeked.contract), None, content, reader,
                                                    strict=False)
        except uses.Unsupported as exc:
            raise _Issue("rejected", "missing_contract", str(exc)) from None
        if not (found_keys & report_keys):
            continue
        # 出どころの 3 分類 (T-G6 の「門の比較候補を確定する」、A1-PROVENANCE-MISSING、FB3-PROV-R6): EH でその鍵の仕事の口から
        # 来たと確定 = 比較 / EH で別の口から来たと確定 = 除外 (不足にしない) / どの口か判定できない = 不足
        work = confirmed.get(entry.cid)
        if work is None:
            unconfirmed.append(entry.cid)
            continue
        contract, document = reader.document(entry.cid)
        found = uses.saved_delivery(contract, document, work, segment_work, reader)
        if found is not None:
            deliveries.append(found)
    if unconfirmed:
        raise _Issue("insufficient", "prerequisite_unavailable",
                     "provenance of a related saved report in the fixed view is not held",
                     evidence=tuple(sorted(unconfirmed)), missing=(VerificationNeed(kind="evidence", value={
                         "target": head, "purpose": "adoption_chain", "contract": None}),))
    if keys & uses.clashes(deliveries):
        raise _Issue("insufficient", "use_conflict", "a report the adoption depends on is contradicted",
                     evidence=(head,))


class _Visible:
    """compiler の見える範囲だけの読み手 (出来事は固定根の祖先、派生物は親が見えるもの)。読みは compiler の
    point を通す (見える範囲と依存の記録は F-a の規則のまま)。`_Sub` の土台にもなる。"""

    def __init__(self, compiler):
        self._compiler = compiler

    def ancestors(self, boundary):
        return self._compiler.image.ancestors(boundary)

    def entry(self, cid):
        return self._compiler.image.entry(cid)

    def sealed_content(self, cid):
        return self._compiler.image.sealed_content(cid)

    def all_entries(self):
        return self._compiler.image.entries()

    def entries(self):
        """見える出来事だけ。旧の compiler は見える出来事の本文をもともと全部読む (`histories` の始め) ので、
        ここで読む本文は増えない (R05: どこからも参照されない派生物の本文に触れない)。"""
        visible = self._compiler.visible_cids
        return tuple(e for e in self._compiler.image.entries() if e.is_event and e.cid in visible)

    def record(self, cid):
        return self._compiler.point(cid)

    def peek(self, cid):
        return self._compiler.image.record(cid)
