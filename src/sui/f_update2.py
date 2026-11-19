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

from .ids import Ref
from .f import ContractValue, FInputError, FReader, FRegistry, ImmutableJSON, MeasurementInterval, Point, \
    _FactoryHandle

__all__ = [
    "fb_registry_v1", "FixedViewValue", "VerificationNeed", "RejectedIssue",
    "InsufficientIssue", "IssuedUpdate", "Rejected", "Insufficient", "UpdateReturn",
    "LaunchResult", "ReportObservation", "ExecutionObservation", "UseObservation", "IntervalObservation",
    "AcquisitionObservation", "SourceObservation", "TargetEvidence",
    "compute_finite_update", "update_response",
]


def fb_registry_v1() -> FRegistry:
    """旧の宣言の集合と実装の識別をそのまま含み、`finite_update/2` と入口 U ほか §2-5-19・§6-3 の能力を
    足した別の不変の registry (§2-4-8 の 2)。registry_key は全部の宣言と実装の識別から求まる。

    最初の輪 (Z41) で足すのは、δ・入口 U・継続の方法と、U が読む読み方・法則・意味の契約。これらの意味は
    窓口と入口 U の版で閉じていて、能力の呼出しの規約からは呼ばない (呼ばれたら algorithm_unavailable)。
    宣言と実装の識別の対として registry_key に結ぶ。段 2 の生成・実行の能力は試験・ホストの側が明示に足す
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
        ("generation", c.FINITE_JOINT_COUNT_LAW, empty, c.SEGMENT_REQUESTED, c.FINITE_JOINT_COUNT_LAW),
        ("generation", c.BOOTSTRAP_GENERATION, ContractRef("sui.fb.args.bootstrap_generation", "1"),
         c.SEGMENT_BINDING, c.SEGMENT_BINDING),
        ("clock", c.SEGMENT_VALUE_ONLY, empty, c.SEGMENT_REPORT, c.SEGMENT_REPORT),
        # K25: ホストが仲立ちした 1 回の取得の結果を 1 標本とする測り方。Frame はホストが acquire の中で出す
        # (能力の呼出しの規約からは呼ばない)
        ("measurement", c.ACQUISITION_RESULT_SAMPLING, empty, c.SEGMENT_REQUESTED, c.SEGMENT_REPORT),
        # K27: 取りに行き方「済んだら次」。実行は本体の SourceMeasurer (能力の呼出しの規約からは呼ばない)
        ("measurement", c.ACQUISITION_REPEAT_WHEN_DONE, empty, c.SEGMENT_REQUESTED, c.SEGMENT_REPORT),
        # K28: 取りに行きの列を見立てへ通す δ・読み方・生成。意味は窓口と入口 U の版にある
        ("method", c.SAVED_ACQUISITION_UPDATE, ContractRef("sui.fb.args.saved_acquisition_update", "1"),
         c.SEGMENT_BINDING, c.WORK_REQUESTED),
        ("projection", c.ACQUISITION_SEQUENCE_PROJECTION,
         ContractRef("sui.fb.args.acquisition_sequence_projection", "1"), c.SEGMENT_REPORT,
         c.ACQUISITION_OBSERVATION_MODEL),
        ("generation", c.ACQUISITION_GENERATION, empty, c.SEGMENT_REQUESTED, c.SEGMENT_REPORT),
    )
    declarations = tuple(CapabilityDeclaration(kind=kind, ref=ref, args_contract=args, input_contract=inp,
                                               output_contract=out, dependencies=(), conditions=())
                         for kind, ref, args, inp, out in rows)
    implementations = tuple(CapabilityImplementation(kind=kind, ref=ref, implementation=_ExecutedByEntrance(),
                                                     identity="sui.fb.first_loop/1:" + ref.name + "/" + ref.version)
                            for kind, ref, *_ in rows)
    # K31: 最初の並べ方 (H9) の手順。F-a が候補の宣言を読む時に呼び直す (Z58 (2))。受け取った入力をそのまま返す
    candidate_input = ContractRef("sui.f.schema.candidate_input", "1")
    declarations += (CapabilityDeclaration(kind="generator", ref=c.MODEL_OPERATIONS, args_contract=empty,
                                           input_contract=candidate_input, output_contract=candidate_input,
                                           dependencies=(), conditions=()),)
    implementations += (CapabilityImplementation(
        kind="generator", ref=c.MODEL_OPERATIONS, implementation=_ModelOperations(),
        identity="sui.fb.first_loop/1:" + c.MODEL_OPERATIONS.name + "/" + c.MODEL_OPERATIONS.version),)
    return make_f_registry(declarations=old.declarations + declarations,
                           implementations=old.implementations + implementations)


class _ModelOperations:
    """並べ方 `sui.fb.model_operations/1` の手順 (紙 F-b H9・K31 決定 6)。受け取った候補の入力をそのまま返す。
    並べる中身は本体の係 `fb.CandidateGenerator` が持つ。args が空でない・入力の欄が違う時は FInputError (shape)。"""

    def __call__(self, *, args, input, context):
        if not hasattr(args, "keys") or dict(args) != {}:
            raise FInputError("shape", "model_operations takes no arguments", "/args")
        if not hasattr(input, "keys") or set(input) != {"actions", "basis", "draws"}:
            raise FInputError("shape", "not a candidate input", "/input")
        return input


class _ExecutedByEntrance:
    """最初の輪の契約の意味は窓口と入口 U の版にある。能力の呼出しの規約から呼ばれたら不足として示す。"""

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
class ReportObservation:
    """EH: ホストが受け取った 1 つの封筒と、そこから保存した原報告の対応 (F-b §2-5-2: 封筒との対応は
    台帳だけでは復元しない)。point は原報告の保存を照合できた時だけ実在の Point、まだなら None。"""
    envelope: int
    received_ns: int
    point: Point | None


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


@_dataclass(frozen=True, slots=True, kw_only=True)
class UseObservation:
    """EW: 仕事の本体が実際に読んだ入力 (FWorkContext.read) と、その時のホストの run の M の読み。
    Desc.input_points の申告や必須閉包の正解とは別の、実使用の観測。"""
    work_id: str
    point: Point
    used_ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class IntervalObservation:
    """EI: 係が `FWorkContext.monitored` に渡した区間の控え (ホストは区間を確かめない。取りに行きの道は使わない、
    K28 の B3')。固定像の中の証拠
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


@_dataclass(frozen=True, slots=True, kw_only=True)
class SourceObservation:
    """ES: 測る仕事の口 (FWorkContext.acquire) で、ホストがその口の源から取りに行った 1 回の操作の観測
    (F-b §6-10 K23・K25)。before_ns・after_ns は操作の直前と、取得の終端のホストの run の M の読み (after は
    原文と Frame の受信の時刻と同じ 1 つの読み)。cursor は源の番号 (taken の時だけ進む)、sample_seq は取得の
    操作の番号 ((run, route_epoch) ごと、empty・unavailable でも進む)。outcome は taken / empty / unavailable、
    source_called は源を実際に読んだか (源が差されていない時 False)、clock_source はその回で握った時計の
    出どころ。envelope は taken の時にホストが原文を入れた封筒の番号、received はその保存を照合できた時だけ
    実在の Point、received_id は原文に使った名札 (Record.id)。frame_envelope はホストが出した取得の Frame の
    封筒の番号、frame はその保存を照合できた時だけ実在の Point。実際の取得の時にホストが作る (係の申告・
    保存された Frame の写しから作らない)。"""
    work_id: str
    route_epoch: str
    cursor: int
    before_ns: int
    after_ns: int
    outcome: _Literal["taken", "empty", "unavailable"]
    envelope: int | None
    received: Point | None
    sample_seq: int
    source_called: bool
    clock_source: Point
    frame_envelope: int
    frame: Point | None
    received_id: Ref | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class TargetEvidence:
    """入口 U に渡す同じプロセスの中の独立の証拠 (F-b §2-5-2 の EW・EH・EI・EA、§6-3、K23 の ES)。ホストが
    自分で行った操作の時に自分で読んだもので、台帳の自己申告や窓口の印・原報告の写しから作らない。同じプロセスの中の窓口の作り直しまでで、再起動をまたがない (★S5)。"""
    executions: tuple[ExecutionObservation, ...]
    uses: tuple[UseObservation, ...]
    intervals: tuple[IntervalObservation, ...]
    acquisitions: tuple[AcquisitionObservation, ...]
    sources: tuple[SourceObservation, ...] = ()


def compute_finite_update(
    request: Point, *, reader: FReader, registry: FRegistry,
    evidence: TargetEvidence,
) -> UpdateReturn:
    """入口 U `sui.f.finite_update_compute/1` (紙 v0.25 §6-3)。保存済みの更新要求 Q* から読み手・
    モデル・固定根・前の採用・観測の並びを解決し、保存した一次事実と境目の実観測だけを読んで、
    宣言の解決・生成の対応・入力の実取得と実使用・固定根・適用の履歴を確かめ、§2-5-19 の数学で
    計算して発行する。F-b から完成した joint を受け取る引数は無い。固定の上限の引数も無い (紙 F-b
    Z41 (a)、Z32 (え): 計算は有理数の厳密な算術で、終わるまで続ける)。入口で要求を構成できない不正や
    物理的な欠落は例外 (三枝に無理に写さない)。

    最初の輪の 1 周目 (Z41) で確かめるのは、要求と記録の対応 (契約・モデル・読み方・法則・channel・
    前の採用の系列) と数学まで。evidence (実取得・実使用・監視の独立の観測) との照合と、能力の宣言の
    照合は ★ 1 周の後 (この版は evidence を読まない)。入口が自分で上げる入力の誤りは `UpdateEntranceError`
    (FInputError) で、係はその理由の語と欄だけを失敗の中身に残す (`_failure_content`、K28-a (ウ))。"""
    c = _c()
    try:
        record = reader.record(request)
    except KeyError:
        raise UpdateEntranceError("unresolved_reference", "the update request is outside the reader", "/request") from None
    if record.body.contract != c.WORK_REQUESTED:
        raise UpdateEntranceError("shape", "not a work request", "/request")
    desc = record.body.content.as_json().get("desc")
    if not hasattr(desc, "items") or desc.get("purpose") != "belief_update" \
            or desc.get("method") != _enc(c.FINITE_UPDATE_COMPUTE):
        raise UpdateEntranceError("shape", "not a belief update request", "/request/desc")
    try:
        state = _replay(reader, request)
    except _Issue as issue:
        if issue.kind == "rejected":
            return Rejected(request=request, issues=(RejectedIssue(
                code=issue.code, fields=issue.fields, evidence=issue.evidence, message=issue.message),))
        return Insufficient(request=request, issues=(InsufficientIssue(
            code=issue.code, fields=issue.fields, missing=issue.missing, evidence=issue.evidence,
            message=issue.message),))
    from ._f_handles import issue as _issue_handle
    from ._f_world import registry_view_key
    from .f import _freeze, _handle
    view = desc["numerical_view"]
    return _issue_handle(_handle(
        IssuedUpdate, request=request, result=_freeze(_encode_result(state)),
        application_digest=state.digest(desc["args"]["model"], desc["reader"]),
        numerical_view=FixedViewValue(boundary=frozenset(view["boundary"]),
                                      reader_view_key=view["environment"]["reader_view_key"],
                                      registry_key=view["environment"]["registry_key"]),
        registry_key=registry_view_key(registry)))


def adopted_belief(compiler):
    """F-a の評価の準備 (`sui.f.prepare_world/3`) が、固定根の中の読み手の F-b の採用 A* を読む口 (§6-10 J7・K12)。
    A* が無ければ None (旧の道のまま)。あれば系列の頭を 1 つに決め (2 つなら競合で不完全)、入口 U と同じ作り直しで
    頭の A* までの joint を一次事実から求め、頭が指す保存した R* と全比較して (R* の Ref, joint) を返す。
    確定した不一致は FInputError、頭が決まらない不足は FIncomplete。"""
    from .f import FIncomplete, FInputError
    c = _c()
    adoptions = {}
    for entry in compiler.image.entries():
        # 探すだけの読みは像から (依存に数えない。A* の無い入力の world を 1 バイトも変えない)
        if not entry.is_event or entry.cid not in compiler.visible_cids \
                or compiler.image.record(entry.cid).body.contract != c.BELIEF_ADOPTED:
            continue
        value = compiler.point(entry.cid).body.content.as_json()
        if value["origin"] == compiler.origin_point:
            adoptions[entry.cid] = value
    if not adoptions:
        return None
    heads = set(adoptions) - {a["previous"] for a in adoptions.values()}
    if len(heads) != 1:
        raise FIncomplete("certificate_incomplete", "competing F-b adoptions", "/adoption")
    head = adoptions[next(iter(heads))]
    if head["model"] != compiler.source:
        raise FInputError("proof_mismatch", "F-b adoption of another model", "/adoption/model")
    reader = _CompilerReader(compiler)
    try:
        state = _replay(reader, head["request"])
        saved = _content(reader, head["result"], c.UPDATE_RESULT)
        desc = _update_desc(reader, head["request"])
    except _Issue as issue:
        raise FInputError(issue.code, issue.message, "/adoption") from None
    if saved["request"] != head["request"] or saved["result"] != _encode_result(state) \
            or saved["application_digest"] != state.digest(head["model"], desc["reader"]):
        raise FInputError("result_mismatch", "the adopted result differs from its recomputation", "/adoption/result")
    return compiler.point(head["result"]).id, state.joint


class _CompilerReader:
    """compiler の見える範囲だけの読み手。読みは compiler の point を通す (見える範囲と依存の記録は F-a の規則のまま)。"""

    def __init__(self, compiler):
        self._compiler = compiler

    def record(self, cid):
        from .f import FInputError
        try:
            return self._compiler.point(cid)
        except FInputError as exc:
            if exc.reason == "unresolved_reference":
                raise KeyError(cid) from None
            raise


class UpdateEntranceError(FInputError):
    """入口 U が自分で上げた入力の誤り (要求を構成できない)。下の部品から上がった FInputError と見分けるための型で、
    同じ理由の語・欄を持つ下の部品の例外をこれと取り違えない (K28-a (ウ))。"""


# U の入口が上げる入力の誤りの閉じた一覧 (理由の語, 欄)。係の失敗の中身に残してよいのはこれだけ (B9)
_ENTRANCE_ERRORS = frozenset((reason, field) for reason in ("unresolved_reference", "shape")
                             for field in ("/request", "/request/desc"))


def _failure_content(error: BaseException) -> dict:
    """係 (`fb.FiniteUpdater`) の失敗の中身 (紙 F-b K24 (2)・K28 新しい決定 11 の B9・K28-a (ウ))。例外の型の名前だけ。
    ただし入口 U が自分で上げた FInputError で、(理由の語, 欄) が閉じた一覧にある時だけ、その 2 つを足す。下の部品から
    上がった例外・一覧に無い値・外の実装の例外は型の名前だけ。例外の自由な文は載せない。"""
    content = {"error_type": type(error).__name__}
    if isinstance(error, UpdateEntranceError) and (error.reason, error.field) in _ENTRANCE_ERRORS:
        content.update(reason=error.reason, field=error.field)
    return content


def update_response(returned: UpdateReturn) -> ContractValue:
    """入口 U の返答を、仕事 Wu が返す `sui.fb.update_response/1` の値にする。三枝は
    {kind: issued, value: finite_update_result/1 の値} / {kind: rejected, value: {issues}} /
    {kind: insufficient, value: {issues}}。発行物そのもの (IssuedUpdate) は値に入らないので、
    仕事は報告と一緒に口へ渡す (FWorkContext.post の issued)。"""
    if isinstance(returned, IssuedUpdate):
        value = {"kind": "issued", "value": returned.result}
    elif isinstance(returned, Rejected):
        value = {"kind": "rejected", "value": {"issues": [_enc(i) for i in returned.issues]}}
    elif isinstance(returned, Insufficient):
        value = {"kind": "insufficient", "value": {"issues": [_enc(i) for i in returned.issues]}}
    else:
        raise TypeError("UpdateReturn expected")
    return ContractValue(contract=_c().UPDATE_RESPONSE, value=value)


# --- 入口 U の中身 (一次事実からの再計算、§2-5-19-1・19-3・19-8) ---

class _Issue(Exception):
    """U が正常に判定した不適合 (rejected) か不足 (insufficient)。三枝の返答に写す。"""

    def __init__(self, kind, code, message, *, fields=(), evidence=(), missing=()):
        super().__init__(message)
        self.kind, self.code, self.message = kind, code, message
        self.fields, self.evidence, self.missing = tuple(fields), frozenset(evidence), tuple(missing)


def _c():
    from . import fb_contracts
    return fb_contracts


def _value_only():
    from .contracts import ContractRef
    return ContractRef("sui.f.value_only", "1")


def _enc(value):
    from .f import _encode
    return _encode(value)


def _content(reader, point, contract):
    """読み手の像の中の記録の本文 (JSON)。像に無い・契約が違うは不適合。"""
    try:
        record = reader.record(point)
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", f"{point} is outside the reader") from None
    if record.body.contract != contract:
        raise _Issue("rejected", "reference_kind", f"{point} is not {contract.name}/{contract.version}",
                     evidence=(point,))
    return record.body.content.as_json()


def _meanings():
    """初回に意味を定めた Claim の契約 → (kind, lower, upper) (§19-1 の表)。最初の輪は到着なしだけ。
    `count_exactly_one/1` ほかは ★ 件数を返す測定の口をつなぐ時 (段は置かない = 紙 F-b Z45 の仕分け。仮の行き先は
    外付けの行・S7)。未知の kind をこれへ寄せない。"""
    c = _c()
    return {(c.NO_ARRIVAL.name, c.NO_ARRIVAL.version): ("no_arrival", 0, 0)}


class _State:
    """一次事実から導いた適用済みの状態 (§19-1 の Claim の部分)。呼出し側の申告ではない。"""

    def __init__(self, joint, states=()):
        from fractions import Fraction
        self.joint, self.mass = tuple(joint), Fraction(1)
        self.states = tuple(states)   # モデルの状態 ({id, target} の列、joint の並び)
        self.kind = None              # 系列が読む観測の種類: "claim" (区間の札) / "acquisition" (取りに行き)。混ぜない
        self.carrier_by_state, self.law_point, self.law = None, None, None
        self.applied = {}   # ClaimKey (segment, item_slot) → Predicate
        self.frames = []    # 取りに行きの順序つきの適用 [MeasurementId の値, 意味] (K28 新しい決定 6)
        self.seen = {}      # MeasurementId の正準 bytes → 意味 (同じ MID は 1 回だけ学ぶ)

    def digest(self, model, origin) -> str:
        """application_digest (§19-1): モデル・origin・法則と、今の連言が表す行の集合 (連言を満たす正準 marks)。
        配送の分割・B の番号・含意される述語の有無で変わらない。取りに行きの系列は、順序を保った取りに行きの適用
        (MID と意味) の列を別の名前空間で結ぶ (K28 (2)(f)。札の行の集合の意味とは分ける)。"""
        from .f import _digest
        from . import _f_count as count
        if self.kind == "acquisition":
            return _digest({"domain": "sui.fb.acquisition_application/1", "model": model, "origin": origin,
                            "applied": [list(pair) for pair in self.frames]})
        rows = [] if self.law is None else [list(map(list, marks)) for marks, _mass in self.law.rows
                                            if all(count.holds(marks, p) for p in self.applied.values())]
        return _digest({"domain": "sui.fb.application/1", "model": model, "origin": origin,
                        "law": self.law_point, "rows": rows})


def _encode_result(state):
    """再計算した状態の finite_update_result/1 の値 {joint, evidence_mass}。"""
    from .f import FiniteUpdateResult, _encode
    return _encode(FiniteUpdateResult(joint=state.joint, evidence_mass=state.mass))


def _span(value):
    from . import _f_count as count
    from .f import _dumps
    return count.Span(clock=_dumps(value["clock"]).decode("utf-8"), start_ns=value["start_ns"],
                      end_ns=value["end_ns"], closure=value["closure"])


def _update_desc(reader, point):
    """保存した更新要求 Q* の Desc (JSON)。別の用途・別の方法の要求は不適合。"""
    c = _c()
    desc = _content(reader, point, c.WORK_REQUESTED).get("desc")
    if not hasattr(desc, "items") or desc.get("purpose") != "belief_update" \
            or desc.get("method") != _enc(c.FINITE_UPDATE_COMPUTE):
        raise _Issue("rejected", "reference_kind", f"{point} is not a belief update request", evidence=(point,))
    return desc


def _series(reader, request):
    """採用の系列を前の採用 A* でさかのぼった更新要求の列 (古い順)。各項は (Q* の Point, Desc, その Q* を採用した A* の
    本文 | None)。A* は同じ model のもので、A*.previous がその要求の prior と一致する (§19-3)。"""
    c = _c()
    out, point, adopted = [], request, None
    first = _update_desc(reader, request)
    model, origin = first["args"]["model"], first["reader"]
    while True:
        desc = _update_desc(reader, point)
        if desc["args"]["model"] != model:
            raise _Issue("rejected", "observation_binding_mismatch", "the adoption series changes its model",
                         fields=("/args/prior",), evidence=(point,))
        # 系列の読み手 (origin) は 1 つ: 各 Q* の reader・各 A* の origin が今回の要求の reader と同じ (K28 新しい決定 4)
        if desc["reader"] != origin or adopted is not None and adopted["origin"] != origin:
            raise _Issue("rejected", "observation_binding_mismatch", "the adoption series changes its origin",
                         fields=("/reader",), evidence=(point,))
        if adopted is not None and adopted["previous"] != desc["args"]["prior"]:
            raise _Issue("rejected", "result_mismatch", "an adoption does not continue its request's prior",
                         fields=("/args/prior",), evidence=(point,))
        out.append((point, desc, adopted))
        prior = desc["args"]["prior"]
        if prior is None:
            return out[::-1]
        adopted = _content(reader, prior, c.BELIEF_ADOPTED)
        if adopted["model"] != model:
            raise _Issue("rejected", "observation_binding_mismatch", "the previous adoption is of another model",
                         fields=("/args/prior",), evidence=(prior,))
        point = adopted["request"]


def _replay(reader, request) -> _State:
    """モデルの最初の joint から、採用の系列の全部の観測を一次事実から順に条件づけ直す (P1: 保存した結果の値から
    続きを計算しない)。前の採用が指す保存した結果 R* は、作り直した値と全比較する (§19-8)。"""
    from .f import _Fraction, _decode
    c = _c()
    series = _series(reader, request)
    model = series[-1][1]["args"]["model"]
    try:
        content = reader.record(model).body.content.as_json()
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", f"{model} is outside the reader") from None
    document = content.get("document") if hasattr(content, "items") else None
    if not hasattr(document, "items") or "initial" not in document:
        raise _Issue("rejected", "reference_kind", f"{model} is not a model with an initial state",
                     fields=("/args/model",), evidence=(model,))
    state = _State(_decode(document["initial"], tuple[_Fraction, ...]), document.get("states", ()))
    for point, desc, adopted in series:
        for use in desc["args"]["observations"]:
            _apply(reader, state, model, use["binding"], use["reading"], desc)
        if adopted is not None:
            saved = _content(reader, adopted["result"], c.UPDATE_RESULT)
            if saved["request"] != point or saved["result"] != _encode_result(state) \
                    or saved["application_digest"] != state.digest(model, desc["reader"]):
                raise _Issue("rejected", "result_mismatch", "a saved result differs from its recomputation",
                             evidence=(adopted["result"],))
    return state


def _apply(reader, state, model, binding, reading, desc) -> None:
    """観測 1 つ (結びつき B と読み方) を、一次事実から読んで条件づける (§19-1)。読み方の契約で、区間の札の道と
    取りに行きの道 (K28) に分ける。同じ系列 (前の採用をさかのぼった全部) に 2 つの種類を混ぜない (K28 新しい決定 7)。"""
    from . import _f_count as count
    from .f import CoverageClaim, FInputError, _Fraction, _decode
    c = _c()
    b = _content(reader, binding, c.SEGMENT_BINDING)
    plan = _content(reader, reading, c.OBSERVATION_PLAN_2)
    if plan["model"] != model:
        raise _Issue("rejected", "observation_binding_mismatch", "reading of another model", evidence=(reading,))
    projection, generation = plan["projection"], plan["generation"]
    kind = "acquisition" if projection["contract"] == _enc(c.ACQUISITION_SEQUENCE_PROJECTION) else "claim"
    if state.kind not in (None, kind):
        raise _Issue("rejected", "missing_contract", "acquisition frames and interval claims in one series",
                     evidence=(binding, reading))
    state.kind = kind
    if kind == "acquisition":
        _apply_acquisition(reader, state, model, binding, reading, b, plan, desc)
        return
    if projection["contract"] != _enc(c.FINITE_SEGMENT_PROJECTION) or b["reading_contract"] != projection["contract"]:
        raise _Issue("rejected", "missing_contract", "projection", evidence=(reading, binding))
    pargs = projection["args"]
    if pargs.get("frame") is not None or pargs.get("time_projection") != {
            "contract": _enc(c.SEGMENT_VALUE_ONLY), "args": {}}:
        raise _Issue("rejected", "missing_contract", "frame or time projection", evidence=(reading,))
    if generation != {"contract": _enc(c.BOOTSTRAP_GENERATION), "args": {"scope": "whole_window"}}:
        raise _Issue("rejected", "missing_contract", "generation", evidence=(reading,))
    report = _content(reader, b["report"], c.SEGMENT_REPORT)
    item = report["item"]
    if item["kind"] != "claim":
        raise _Issue("rejected", "missing_contract", "only claims are read", evidence=(b["report"],))
    claim = _decode(item["value"], CoverageClaim)
    meaning = _meanings().get((claim.contract.name, claim.contract.version))
    entries = [e for e in pargs["claims"] if e["meaning"] == _enc(claim.contract)]
    if meaning is None or meaning[0] != claim.kind or len(entries) != 1:
        raise _Issue("rejected", "missing_contract", "claim meaning", evidence=(b["report"], reading))
    entry = entries[0]
    law_point = entry["law"]
    if state.law_point is not None and state.law_point != law_point:
        raise _Issue("rejected", "missing_contract", "one count-law series (extends is not read)",
                     evidence=(law_point,))
    law = _content(reader, law_point, c.FINITE_JOINT_COUNT_LAW)
    if law["model"] != model or law["extends"] is not None or law["frame_relation"] != "independent_given_carrier":
        raise _Issue("rejected", "missing_contract", "count law", evidence=(law_point,))
    k = _content(reader, b["segment"], c.SEGMENT_REQUESTED)["desc"]
    # 原 Claim から channel への対応は一意 (§19-1): 過程・route が合う channel が法則にちょうど 1 つ
    matching = [ch for ch in law["channels"] if b["route"] in ch["route_configs"] and k["process"] == ch["process"]]
    if len(matching) != 1:
        raise _Issue("rejected", "shape", "claim channel is not unique in the law", evidence=(law_point,))
    if matching[0]["id"] != entry["channel"]:
        raise _Issue("rejected", "observation_binding_mismatch", "channel route or process",
                     evidence=(binding, law_point))
    try:
        if state.law is None:
            if len(law["carrier_by_state"]) != len(state.joint):
                raise FInputError("shape", "carrier_by_state length", "/carrier_by_state")
            state.law = count.check_law(
                law["carrier_by_state"], {ch["id"]: _span(ch["domain"]) for ch in law["channels"]},
                [([(m["channel"], m["time_ns"], m["count"]) for m in row["marks"]],
                  [_decode(q, _Fraction) for q in row["mass"]]) for row in law["rows"]])
            state.carrier_by_state, state.law_point = tuple(law["carrier_by_state"]), law_point
        predicate = count.Predicate(channel=entry["channel"], span=_span(_enc(claim.interval)),
                                    lower=meaning[1], upper=meaning[2])
        key = (b["segment"], report["item_slot"])
        known = state.applied.get(key)
        if known is not None:
            if known != predicate:   # 同じ原 Claim を別の命題として足さない (CL-APPLY)
                raise _Issue("rejected", "measurement_conflict", "same claim read differently",
                             evidence=(b["report"],))
            return   # 同じ原 Claim は 1 つの導出系列で 1 つの出来事 (再配送・別の B は数値の no-op)
        state.joint, state.mass = count.condition(state.joint, state.mass, state.carrier_by_state,
                                                  state.law, tuple(state.applied.values()), predicate)
        state.applied[key] = predicate
    except FInputError as exc:
        raise _Issue("rejected", exc.reason if exc.reason in _REJECT_CODES else "shape", str(exc),
                     evidence=(binding,)) from None


# K26 の読み口の「読めない」の理由 → U の不適合の語 (K28 新しい決定 9・10: 宣言の食い違いは読めない)
_UNREADABLE = {"missing_record": "unresolved_reference", "missing_declaration": "missing_contract", "shape": "shape",
               "conflict": "measurement_conflict", "control_ambiguous": "missing_contract",
               "control_independence_unproved": "missing_contract", "time_projection_unproved": "missing_contract"}


def _json(value):
    """凍った写し (mappingproxy・tuple) を比べられる JSON の値へ。"""
    if hasattr(value, "items"):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _apply_acquisition(reader, state, model, binding, reading, b, plan, desc) -> None:
    """取りに行き 1 回 (家の人が acquire で残した Frame の B) を、1 回分の核で今の joint に掛ける (紙 F-b K28 新しい
    決定 1〜10)。宣言を解き (読み方・生成・物語の対応・取りに行き方・K26-d (ク))、K26 の読み口で 0〜i の接頭部を
    読んで確かめ、i 番目のセルの行列の和 Mᵢ を対応で見立ての状態へ並べ替えて、qᵢ = Mᵢ qᵢ₋₁ / zᵢ・質量 × zᵢ。
    K26 の L (初期の状態ごとの尤度) を今の joint に掛けない。同じ MID の同じ意味は据え置き、違う意味は食い違い。
    新しい MID は前の適用の続きの番号だけ (並べ替えない・飛ばさない)。zᵢ = 0 は model_falsified。"""
    from fractions import Fraction
    from . import _fb_read
    from .contracts import ContractRef
    from .f import ClockReading, FInputError, MeasurementFrame, _decode, _dumps
    from .f_contracts import ROUTE_CONFIG
    from .f_entry import RouteApplied
    c = _c()
    projection = plan["projection"]
    pargs = projection["args"]
    if b["reading_contract"] != projection["contract"] or not hasattr(pargs, "keys") \
            or set(pargs.keys()) != {"observation_model", "correspondence", "time_projection"} \
            or _json(pargs["time_projection"]) != {"contract": _enc(_value_only()), "args": {}}:
        raise _Issue("rejected", "missing_contract", "acquisition projection", fields=("/projection",),
                     evidence=(reading, binding))
    if _json(plan["generation"]) != {"contract": _enc(c.ACQUISITION_GENERATION), "args": {}}:
        raise _Issue("rejected", "missing_contract", "acquisition generation", fields=("/generation",),
                     evidence=(reading,))
    report = _content(reader, b["report"], c.SEGMENT_REPORT)
    if report["item"]["kind"] != "frame":
        raise _Issue("rejected", "missing_contract", "only acquisition frames are read here", evidence=(b["report"],))
    try:
        frame = _decode(report["item"]["value"], MeasurementFrame)
    except (FInputError, KeyError, TypeError, ValueError):
        raise _Issue("rejected", "shape", "acquisition frame", evidence=(b["report"],)) from None
    mid = frame.measurement_id
    if mid.component != _fb_read._SAMPLING_COMPONENT:
        raise _Issue("rejected", "missing_contract", "not an acquisition frame", evidence=(b["report"],))
    # 生成 (acquisition_generation/1): 記録どうしの一致だけ。B の segment は測る要求 k、B の route はその k の route、
    # Frame の run と route_epoch は適用中の route config (Z55 の入口があるので独立の控えは読まない)
    k = _content(reader, b["segment"], c.SEGMENT_REQUESTED)["desc"]
    try:
        applied = _decode(_content(reader, b["route"], ROUTE_CONFIG), RouteApplied)
        sampling = _decode(k["method"], ContractRef)
    except (FInputError, KeyError, TypeError, ValueError):
        raise _Issue("rejected", "shape", "route config or measuring request", evidence=(b["route"],)) from None
    if report["segment"] != b["segment"] or k["args"]["route"] != b["route"] \
            or applied.config.route_epoch != mid.route_epoch or frame.route_epoch != mid.route_epoch \
            or not isinstance(applied.effective_from, ClockReading) or applied.effective_from.run != mid.origin:
        raise _Issue("rejected", "observation_binding_mismatch", "acquisition generation",
                     evidence=(binding, b["route"], b["segment"]))
    # 物語の対応の記録 (state_correspondence/1)
    point = pargs["correspondence"]
    corr = _content(reader, point, c.STATE_CORRESPONDENCE)
    if not hasattr(corr, "keys") or set(corr.keys()) != {"model", "observation_model", "pairs"} \
            or corr["model"] != model or corr["observation_model"] != pargs["observation_model"]:
        raise _Issue("rejected", "observation_binding_mismatch", "state correspondence", evidence=(point, reading))
    # K26 の読み口で 0〜i を読む。読む範囲は、その要求 Q* が申告した入力 (と観測モデル) の一次記録だけ。B が指す Frame が
    # その中に無ければ読まない (同じ MID の別の記録で計算しない。中にあれば、同じ MID の中身の違う記録は K26 の食い違い)
    if b["report"] not in desc["input_points"]:
        raise _Issue("rejected", "observation_binding_mismatch", "the bound frame is not an input of the request",
                     evidence=(binding, b["report"]))
    records = {}
    for p in sorted({*desc["input_points"], pargs["observation_model"]}):
        try:
            records[p] = reader.record(p)
        except KeyError:
            raise _Issue("rejected", "unresolved_reference", f"{p} is outside the reader", evidence=(p,)) from None
    read = _fb_read.read(records, model=pargs["observation_model"], run=mid.origin, route_epoch=mid.route_epoch,
                         through_seq=mid.sample_seq)
    if read.kind == "unreadable":
        raise _Issue("rejected", _UNREADABLE[read.reason], "the acquisition sequence is unreadable: " + read.reason,
                     fields=("/args/observations",), evidence=(binding,))
    declaration, boot = _fb_read._declaration(records, pargs["observation_model"], [], [])
    observation = read.observations[mid.sample_seq]
    if observation.measurement_id != mid:
        raise _Issue("rejected", "measurement_conflict", "the read sequence differs at this MID", evidence=(binding,))
    # 取りに行き方の照らし (決定 9): 起動の宣言の route の repeat と測る要求の repeat、u の id、制御の表、重み
    routes = [r for r in _content(reader, boot, c.BOOT_DECLARATION)["routes"] if r["slot"] == declaration.route_slot]
    repeat = _json(routes[0]["declaration"]["value"]["repeat"]) if len(routes) == 1 else None
    u_id = c.ACQUISITION_REPEAT_WHEN_DONE.name + "/" + c.ACQUISITION_REPEAT_WHEN_DONE.version
    symbols = sorted(set(_fb_read._SYMBOLS.values()))
    if repeat != {"contract": _enc(c.ACQUISITION_REPEAT_WHEN_DONE), "args": {}} \
            or _json(k["args"]["repeat"]) != repeat \
            or [u.id for u in declaration.controls] != [u_id] \
            or _json(declaration.control_rule.args) != {"first": [u_id], "after": {s: [u_id] for s in symbols}} \
            or _weights(declaration.independence.args) != ((Fraction(1),),) * len(declaration.states):
        raise _Issue("rejected", "missing_contract", "acquisition repeat or control declaration",
                     fields=("/observation_model",), evidence=(pargs["observation_model"],))
    control, = declaration.controls
    outcomes = {o.id: o for o in control.kernel.outcomes}
    # K26-d (ク): セルの観測値と、そのセルの outcome の evidence (kind・測る契約・射影した観測値) が一致する
    for cell in control.cells:
        for name in cell.outcomes:
            emission = outcomes[name].evidence
            if emission is None or emission.kind != "measurement" or emission.measurement_contract != sampling \
                    or cell.observation.kind != "measurement" \
                    or _json(emission.value) != _json(cell.observation.value):
                raise _Issue("rejected", "missing_contract", "outcome evidence differs from its observation cell",
                             fields=("/observation_model",), evidence=(pargs["observation_model"],))
    # 物語の対応 (決定 3): 最初は 1 対 1 だけ (恒等も明示)。target を横切らない
    ids = [s["id"] for s in state.states]
    targets = [s["target"] for s in state.states]
    pairs = _json(corr["pairs"])
    if not isinstance(pairs, list) or any(not isinstance(pair, list) or len(pair) != 2 for pair in pairs) \
            or len(pairs) != len(ids) or sorted(a for a, _m in pairs) != sorted(declaration.states) \
            or sorted(m for _a, m in pairs) != sorted(ids):
        raise _Issue("rejected", "shape", "the correspondence is not one to one", fields=("/pairs",), evidence=(point,))
    phi = [ids.index(dict(pairs)[a]) for a in declaration.states]   # 観測モデルの状態の番号 → 見立ての状態の番号
    n = len(ids)
    for o in outcomes.values():
        for i in range(n):
            for j in range(n):
                if o.matrix[i][j] and targets[phi[i]] != targets[phi[j]]:
                    raise _Issue("rejected", "shape", "the kernel crosses a target", fields=("/pairs",),
                                 evidence=(point,))
    symbol = _fb_read._SYMBOLS[(observation.result, observation.source_called)]
    cell = next((x for x in control.cells if _fb_read._symbol(x.observation) == symbol), None)
    members = set(cell.outcomes) if cell is not None else set()   # セルが無い観測は、モデルが出さない観測 (質量 0)
    m = [[Fraction(0)] * n for _ in range(n)]
    for o in outcomes.values():
        if o.id in members:
            for i in range(n):
                for j in range(n):
                    m[phi[i]][phi[j]] += o.matrix[i][j]
    # 意味 = 読み方の版と、宣言した観測モデルの値の全部 (状態・制御・核・セルの分け方・制御の表・重み) と、物語の対応の
    # 正準な組と、この回のセル (決定 6: 核・セル・対応・読み方の版のどれかが違えば別の読み方)。欄を選んで足さず、宣言の値を
    # まるごと入れる (この回の行列がたまたま同じでも、宣言が違えば同じ意味にしない。レビュー K28-R1・R1-remains)
    meaning = {"projection": projection["contract"],
               "observation_model": _json(records[pargs["observation_model"]].body.content.as_json()["value"]),
               "pairs": sorted(pairs), "cell": symbol}
    key = _dumps(_enc(mid))
    known = state.seen.get(key)
    if known is not None:
        # 照合は正準 JSON の bytes で (digest と同じ同一性。Python の == は true と 1 を同じにする = R14、レビュー K28-R4)
        if _dumps(known) != _dumps(meaning):   # 同じ取りに行きを別の読み方で読み直さない
            raise _Issue("rejected", "measurement_conflict", "the same acquisition read differently", evidence=(binding,))
        return                 # 同じ取りに行きの同じ意味の再提示は据え置き (2 回学ばない)
    if mid.sample_seq != len(state.frames) or state.frames and (
            state.frames[-1][0]["origin"], state.frames[-1][0]["route_epoch"]) != (_enc(mid.origin), mid.route_epoch):
        raise _Issue("rejected", "observation_binding_mismatch",
                     "acquisitions must continue the applied prefix in order", evidence=(binding,))
    z = sum((m[i][j] * state.joint[j] for i in range(n) for j in range(n)), Fraction(0))
    if z == 0:
        raise _Issue("rejected", "model_falsified", "the model gives this acquisition no mass on the current support",
                     evidence=(binding,))
    state.joint = tuple(sum((m[i][j] * state.joint[j] for j in range(n)), Fraction(0)) / z for i in range(n))
    state.mass *= z
    state.frames.append((_enc(mid), meaning))
    state.seen[key] = meaning


def _weights(args):
    """独立の重みの行 (初期の状態ごと)。読めなければ None。"""
    from fractions import Fraction
    from .f import FInputError, _decode
    try:
        return _decode(args["weights_by_initial_state"], tuple[tuple[Fraction, ...], ...])
    except (FInputError, KeyError, TypeError, ValueError):
        return None


_REJECT_CODES = {"schema", "shape", "noncanonical", "rational", "unit", "unknown_version", "normalization",
                 "unresolved_reference", "reference_kind", "observation_binding_mismatch",
                 "measurement_conflict", "clock_unaligned", "missing_contract", "model_falsified"}
