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
    "compute_finite_update", "update_response", "draw_guarantee",
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
    # K36: 一歩を行う方法 (実行は本体の係 fb.StepExecutor と家の人の perform) と、その結果を読む読み方
    rows2 = (("method", c.EXECUTE_STEP, empty, c.EXECUTE_STEP_REQUESTED, c.EXECUTION_RESULT),
             ("projection", c.EXECUTION_STEP_PROJECTION, ContractRef("sui.fb.args.execution_step_projection", "1"),
              c.EXECUTION_RESULT, c.EXECUTION_DECLARATION))
    declarations += tuple(CapabilityDeclaration(kind=kind, ref=ref, args_contract=args, input_contract=inp,
                                                output_contract=out, dependencies=(), conditions=())
                          for kind, ref, args, inp, out in rows2)
    implementations += tuple(CapabilityImplementation(kind=kind, ref=ref, implementation=_ExecutedByEntrance(),
                                                      identity="sui.fb.first_loop/1:" + ref.name + "/" + ref.version)
                             for kind, ref, *_ in rows2)
    # K36-a (ア): 必要量 = 仕事 1 つが走る間に席 1 つ (seats/1 の意味から導ける値。bootstrap の札・差し替えの口)
    declarations += (CapabilityDeclaration(kind="method", ref=c.ONE_SEAT_PER_WORK, args_contract=empty,
                                           input_contract=c.NEED_INPUT, output_contract=c.QUANTITY_VALUE,
                                           dependencies=(), conditions=()),)
    implementations += (CapabilityImplementation(
        kind="method", ref=c.ONE_SEAT_PER_WORK, implementation=_OneSeatPerWork(),
        identity="sui.fb.first_loop/1:" + c.ONE_SEAT_PER_WORK.name + "/" + c.ONE_SEAT_PER_WORK.version),)
    # K31: 最初の並べ方 (H9) の手順。F-a が候補の宣言を読む時に呼び直す (Z58 (2))。受け取った入力をそのまま返す
    candidate_input = ContractRef("sui.f.schema.candidate_input", "1")
    declarations += (CapabilityDeclaration(kind="generator", ref=c.MODEL_OPERATIONS, args_contract=empty,
                                           input_contract=candidate_input, output_contract=candidate_input,
                                           dependencies=(), conditions=()),)
    implementations += (CapabilityImplementation(
        kind="generator", ref=c.MODEL_OPERATIONS, implementation=_ModelOperations(),
        identity="sui.fb.first_loop/1:" + c.MODEL_OPERATIONS.name + "/" + c.MODEL_OPERATIONS.version),)
    # K35: 選択のくじの生成器 (H4)。実行は本体の係 fb.UniformDraw (能力の呼出しの規約からは呼ばない)。保証の範囲を
    # conditions に書く (黙って誤選択の確率を足さない)。1 回に読むビットの数は fb_contracts の 1 か所から読む
    declarations += (CapabilityDeclaration(kind="generator", ref=c.OS_UNIFORM_BITS, args_contract=empty,
                                           input_contract=c.DRAW_REQUESTED, output_contract=c.DRAW_REPORT,
                                           dependencies=(), conditions=(draw_guarantee(),)),)
    implementations += (CapabilityImplementation(
        kind="generator", ref=c.OS_UNIFORM_BITS, implementation=_ExecutedByEntrance(),
        identity="sui.fb.first_loop/1:" + c.OS_UNIFORM_BITS.name + "/" + c.OS_UNIFORM_BITS.version),)
    return make_f_registry(declarations=old.declarations + declarations,
                           implementations=old.implementations + implementations)


def draw_guarantee() -> ContractValue:
    """くじの生成器 `sui.fb.os_uniform_bits/1` の保証の範囲 (紙 F-b K35 決定 11、H4、Z60-a)。法則 uniform_bits/1 の
    くじ U の続きのかたまりを、OS の暗号用の乱数から B ビットずつ返す。選び方は区間全体の認証で、固定のけた数で
    候補を外さない。実際の OS について保証しないこと・止まり方は別に書く (「ゼロだと分かった」とは書かない)。"""
    return ContractValue(contract=_c().DRAW_GUARANTEE, value={
        "law": {"name": "uniform_bits", "version": "1"}, "source": "os_cryptographic_random",
        "block_bits": _c().OS_UNIFORM_BITS_BLOCK,
        "selection": "when the requested bits are independent fair bits given the past and the fixed problem and the "
                     "required certified enclosures converge, candidate i is selected with probability q_i; no "
                     "candidate is excluded by a fixed finite number of digits",
        "not_guaranteed": "for the actual operating system source: an independent fair infinite sequence, that each "
                          "individual candidate can occur, agreement of very small probabilities, or a numeric bound "
                          "on probability deviation caused by the operating system",
        "completion": "rates of stopping, failure and NoDecision, and the selection distribution conditioned on "
                      "completion, are separate and not stated here"})


class _ModelOperations:
    """並べ方 `sui.fb.model_operations/1` の手順 (紙 F-b H9・K31 決定 6)。受け取った候補の入力をそのまま返す。
    並べる中身は本体の係 `fb.CandidateGenerator` が持つ。args が空でない・入力の欄が違う時は FInputError (shape)。"""

    def __call__(self, *, args, input, context):
        if not hasattr(args, "keys") or dict(args) != {}:
            raise FInputError("shape", "model_operations takes no arguments", "/args")
        if not hasattr(input, "keys") or set(input) != {"actions", "basis", "draws"}:
            raise FInputError("shape", "not a candidate input", "/input")
        return input


class _OneSeatPerWork:
    """必要量 `sui.fb.one_seat_per_work/1` (紙 F-b K36-a (ア)): どの仕事も、走る間に席 1 つ。args は空。"""

    def __call__(self, *, args, input, context):
        if not hasattr(args, "keys") or dict(args) != {}:
            raise FInputError("shape", "one_seat_per_work takes no arguments", "/args")
        return {"contract": {"name": "sui.fb.seats", "version": "1"}, "value": 1}


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
    return _compute(request, reader, registry, _c().FINITE_UPDATE_COMPUTE)


def compute_timed_update(
    request: Point, *, reader: FReader, registry: FRegistry,
    evidence: TargetEvidence,
) -> UpdateReturn:
    """入口 U の時刻を読む版 `sui.fb.timed_update_compute/1` (紙 F-b K38)。同じ作り直し (`_replay`) で、取りに行きの列を
    宣言した件数の法則・取得区間の測定核・経過時間込みで 1 つの共同の法則に条件づけ、採用する信念を「法則と原記録から
    作り直せる正本」(`sui.fb.timed_update_result/1`) として発行する。旧い有限の系列は読まない (版を混ぜない)。"""
    return _compute(request, reader, registry, _c().TIMED_UPDATE_COMPUTE)


def _compute(request, reader, registry, method):
    c = _c()
    try:
        record = reader.record(request)
    except KeyError:
        raise UpdateEntranceError("unresolved_reference", "the update request is outside the reader", "/request") from None
    if record.body.contract != c.WORK_REQUESTED:
        raise UpdateEntranceError("shape", "not a work request", "/request")
    desc = record.body.content.as_json().get("desc")
    if not hasattr(desc, "items") or desc.get("purpose") != "belief_update" or desc.get("method") != _enc(method):
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
    model, origin = desc["args"]["model"], desc["reader"]
    return _issue_handle(_handle(
        IssuedUpdate, request=request, result=_freeze(_encode_result(state, model, origin)),
        application_digest=state.digest(model, origin),
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
        return _prior_belief(compiler)
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
    if not saved_matches(saved, head["request"], state, head["model"], desc["reader"]):
        raise FInputError("result_mismatch", "the adopted result differs from its recomputation", "/adoption/result")
    if state.mode == "timed":   # 時刻を読む信念は、正本から作った厳密な確率の比をそのまま渡す (K38)
        from . import _fb_time
        # 評価の根は判断の時刻 j (文脈の judgment_reading、K41 決定 6): 遷移のある調子は採用済みの終端から j まで無観測で
        # 進める。遷移の無い信念は j でも同じ値
        context = getattr(compiler, "context", None)
        return compiler.point(head["result"]).id, _fb_time.joint(state.timed, None if context is None else context.now_ns)
    return compiler.point(head["result"]).id, state.joint


def _prior_belief(compiler):
    """最初の採用より前の、考える側の出発点 (紙 F-b K41 決定 6、レビュー R3)。起動の候補を入口 U と同じ読み方 (候補の解決
    `initial_candidate`・観測の読み方 `member_reading`・観測の時刻の窓 `_timed_window`) で読み、遷移のある候補なら、その事前を
    法則の起点から判断の時刻 j まで無観測で進めた信念を返す (採用の根は無いので根は None)。遷移の無い候補は None (今の道 =
    モデルの事前のまま。静的な調子は j でも同じ値)。U の読み方で読めない宣言は、U と同じ理由で名指して止まる (レビュー R3-P)。
    起動の宣言は knowledge origin の親 (`_fb_boot._origin_step`)。"""
    from types import SimpleNamespace
    from . import _fb_time
    from .f import FInputError, _Fraction, _decode
    context, origin = getattr(compiler, "context", None), getattr(compiler, "origin_point", None)
    boots = [] if context is None or origin is None else [
        p for p in compiler.image.entry(origin).parents
        if compiler.image.record(p).body.contract == _c().BOOT_DECLARATION]   # 探すだけの読みは像から
    if len(boots) != 1:
        return None
    boot = boots[0]
    try:
        member = initial_candidate(_CompilerReader(compiler), boot)
        if member.get("transitions") is None:
            return None
        member["phi"] = member_reading(member, route=member["observation"].route_slot, evidence_model=(boot,),
                                       evidence_pairs=(boot,))[1]
        _timed_window([member], _enc(context.run), context.now_ns, boot)
    except Unresolved:
        return None   # 解決できない起動は起動の計画が止めている (評価の道へは来ない)
    except _Issue as issue:
        raise FInputError(issue.code, issue.message, issue.fields[0] if issue.fields else "/declaration") from None
    start = SimpleNamespace(joint=_decode(member["document"]["initial"], tuple[_Fraction, ...]))
    spec = {"units": _timed_units(start, [member], [(boot,)]), "entries": [],
            "terminal_ns": member["observation"].law.origin_ns}
    return None, _fb_time.joint(spec, context.now_ns)


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
        self.frames = []    # 取りに行きと行った一歩の順序つきの適用 [MeasurementId の値 | 一歩の鍵, 意味] (K28 新しい決定 6・K36)
        self.seen = {}      # MeasurementId (か一歩の E) の正準 bytes → 意味 (同じ測定は 1 回だけ学ぶ)
        self.passive = []   # 適用した取りに行きの MeasurementId の値 (順に。番号の続きを確かめる)
        self.history = []   # 適用した観測の (種類, 始め, 終わり, 行列, 重なりの宣言) (順の確かめ、K36 決定 12)
        # 取りに行きの系列の数の版 (K38): "finite" (有限の核を joint に掛ける) / "timed" (時刻を読む正本に積む)。混ぜない
        self.mode = None
        # 時刻を読む正本 (K38 決定 5): units (状態ごとの件数の法則と事前、最初の取りに行きで決まる)・entries (適用の順)
        self.timed = {"units": None, "entries": [], "terminal_ns": None}
        self.observations = []   # 適用した原記録の Point (取りに行きの Frame・一歩の結果のメモ、順に)

    def digest(self, model, origin) -> str:
        """application_digest (§19-1): モデル・origin・法則と、今の連言が表す行の集合 (連言を満たす正準 marks)。
        配送の分割・B の番号・含意される述語の有無で変わらない。取りに行きの系列は、順序を保った取りに行きの適用
        (MID と意味) の列を別の名前空間で結ぶ (K28 (2)(f)。札の行の集合の意味とは分ける)。"""
        from .f import _digest
        from . import _f_count as count
        if self.mode == "timed":
            from . import _fb_time
            return _digest({"domain": "sui.fb.timed_application/1", "model": model, "origin": origin,
                            "applied": [list(pair) for pair in self.frames],
                            "derivation": _json(_fb_time.encode_spec(self.timed))})
        if self.kind == "acquisition":
            return _digest({"domain": "sui.fb.acquisition_application/1", "model": model, "origin": origin,
                            "applied": [list(pair) for pair in self.frames]})
        rows = [] if self.law is None else [list(map(list, marks)) for marks, _mass in self.law.rows
                                            if all(count.holds(marks, p) for p in self.applied.values())]
        return _digest({"domain": "sui.fb.application/1", "model": model, "origin": origin,
                        "law": self.law_point, "rows": rows})


def _encode_result(state, model, origin):
    """再計算した状態の結果の値。有限の系列は finite_update_result/1 の {joint, evidence_mass}、時刻を読む系列は作り直せる
    正本 (`sui.fb.timed_update_result/1`、K38 決定 5)。"""
    from .f import FiniteUpdateResult, _encode
    if state.mode == "timed":
        from . import _fb_time
        return _fb_time.result(state.timed, state.digest(model, origin), state.observations)
    return _encode(FiniteUpdateResult(joint=state.joint, evidence_mass=state.mass))


def saved_matches(saved, request, state, model, origin) -> bool:
    """保存した結果 R* の本文が、その要求 request の作り直し state と同じか (§19-8・K38-b R5)。照合は正準 JSON の bytes
    (Python の == は true と 1 を同じにする、K28-a (チ))。入口 U の系列の再生・考える側の採用の読み・時刻を読む信念の照会の
    認証が、同じこの照合を使う。"""
    from .f import _dumps
    try:
        return _dumps(saved["request"]) == _dumps(request)             and _dumps(saved["result"]) == _dumps(_encode_result(state, model, origin))             and _dumps(saved["application_digest"]) == _dumps(state.digest(model, origin))
    except (KeyError, TypeError):
        return False


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
            or desc.get("method") not in (_enc(c.FINITE_UPDATE_COMPUTE), _enc(c.TIMED_UPDATE_COMPUTE)):
        raise _Issue("rejected", "reference_kind", f"{point} is not a belief update request", evidence=(point,))
    return desc


def _series(reader, request):
    """採用の系列を前の採用 A* でさかのぼった更新要求の列 (古い順)。各項は (Q* の Point, Desc, その Q* を採用した A* の
    本文 | None)。A* はその要求と同じ model・同じ読み手のもので、A*.previous がその要求の prior と一致する (§19-3)。
    系列の中で model と読み手が替わってよいかは `_replay` が並びの記録で確かめる (紙 F-b K37 決定 4)。"""
    c = _c()
    out, point, adopted = [], request, None
    while True:
        desc = _update_desc(reader, point)
        if adopted is not None:
            if adopted["previous"] != desc["args"]["prior"]:
                raise _Issue("rejected", "result_mismatch", "an adoption does not continue its request's prior",
                             fields=("/args/prior",), evidence=(point,))
            if adopted["model"] != desc["args"]["model"] or adopted["origin"] != desc["reader"]:
                raise _Issue("rejected", "observation_binding_mismatch",
                             "an adoption differs from its request's model or reader", fields=("/args/prior",),
                             evidence=(point,))
        out.append((point, desc, adopted))
        prior = desc["args"]["prior"]
        if prior is None:
            return out[::-1]
        adopted = _content(reader, prior, c.BELIEF_ADOPTED)
        point = adopted["request"]


def _replay(reader, request) -> _State:
    """モデルの最初の joint から、採用の系列の全部の観測を一次事実から順に条件づけ直す (P1: 保存した結果の値から
    続きを計算しない)。前の採用が指す保存した結果 R* は、作り直した値と全比較する (§19-8)。

    候補を足した後 (紙 F-b K37 決定 4): 系列の中で model が替わるのは、新しい model がその要求の入力にある並びの記録の
    直和のモデルで、前の model をその並びの来歴に持つ時だけ (前の並びへ戻らない)。替わった所で数値は新しい並びの事前から
    作り直し、その要求は前の区間で読んだ原記録を全部、同じ順で先頭に読み直す (来歴は前の採用を指したまま、数値の根と
    分ける)。読み手はその並びの読み手 (knowledge_origin) に替わる。"""
    c = _c()
    series = _series(reader, request)
    pools = _Pools(reader, series[-1][1])
    state, model, origin, applied = None, None, None, []
    for point, desc, adopted in series:
        if desc["args"]["model"] != model:
            if model is not None:
                _check_change(reader, pools, model, applied, desc, point)
            model, origin, applied = desc["args"]["model"], desc["reader"], []
            state = _initial(reader, model)
        elif desc["reader"] != origin:
            raise _Issue("rejected", "observation_binding_mismatch", "the adoption series changes its origin",
                         fields=("/reader",), evidence=(point,))
        for use in desc["args"]["observations"]:
            _apply(reader, state, model, use["binding"], use["reading"], desc, pools)
            if use["binding"] not in applied:
                applied.append(use["binding"])
        # 要求の方法と、読んだ系列の数の版の一致 (K38): 時刻を読む入口の要求は時刻を読む系列だけ、有限の入口の要求は
        # それ以外。系列の全部の要求で、入口 U・考える側の採用の読み・照会の認証が同じこの作り直しで確かめる
        if (desc["method"] == _enc(c.TIMED_UPDATE_COMPUTE)) != (state.mode == "timed"):
            raise _Issue("rejected", "missing_contract", "the update method does not read this series",
                         fields=("/method",), evidence=(point,))
        if adopted is not None:
            saved = _content(reader, adopted["result"], c.UPDATE_RESULT)
            if not saved_matches(saved, point, state, model, desc["reader"]):
                raise _Issue("rejected", "result_mismatch", "a saved result differs from its recomputation",
                             evidence=(adopted["result"],))
    return state


def _initial(reader, model) -> _State:
    from .f import _Fraction, _decode
    document = _model_document(reader, model, evidence=(model,))
    if "initial" not in document:
        raise _Issue("rejected", "reference_kind", f"{model} is not a model with an initial state",
                     fields=("/args/model",), evidence=(model,))
    return _State(_decode(document["initial"], tuple[_Fraction, ...]), document.get("states", ()))


def _model_document(reader, model, *, evidence):
    """モデルの宣言の document (JSON)。読めなければ不適合。"""
    try:
        content = reader.record(model).body.content.as_json()
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", f"{model} is outside the reader", evidence=evidence) from None
    document = content.get("document") if hasattr(content, "items") else None
    if not hasattr(document, "items"):
        raise _Issue("rejected", "reference_kind", f"{model} is not a model", fields=("/args/model",),
                     evidence=evidence)
    return _json(document)


def _correspondence(reader, pargs, model, reading):
    """読み方が名指す物語の対応の記録 (state_correspondence/1) が、この model とその読み方の観測モデルのものであること。"""
    c = _c()
    point = pargs["correspondence"]
    corr = _content(reader, point, c.STATE_CORRESPONDENCE)
    if not hasattr(corr, "keys") or set(corr.keys()) != {"model", "observation_model", "pairs"} \
            or corr["model"] != model or corr["observation_model"] != pargs["observation_model"]:
        raise _Issue("rejected", "observation_binding_mismatch", "state correspondence", evidence=(point, reading))
    return corr


def _initial_member(reader, model, declaration, boot, pairs, evidence):
    """最初の並び (起動の宣言の 1 枚) の候補 (K37・K38-b R6・K39 決定 8): ホストの `_fb_pool.initial_pool` と同じ候補の解決
    (`initial_candidate`) で、起動の宣言の名前・モデルと、読み方が名指す観測モデルの記録 (declaration) と物語の対応の記録
    (pairs) から作り、要求のモデル model (保存した派生のモデル) の document が解決の document と同じことを照らす。解決の不足は
    evidence (読み方が名指した観測モデルと対応の記録) を名指した不適合。"""
    from .f import _dumps
    try:
        member = initial_candidate(reader, boot, named=(declaration, _json(pairs)))
    except Unresolved as exc:
        raise _Issue("rejected", exc.code, "the candidate is unresolvable: " + exc.reason, fields=(exc.field,),
                     evidence=evidence) from None
    if _dumps(member["document"]) != _dumps(_model_document(reader, model, evidence=(model,))):
        raise _Issue("rejected", "result_mismatch", "the model differs from the resolved initial candidate",
                     fields=("/args/model",), evidence=(model, boot))
    return member


def _check_change(reader, pools, previous, applied, desc, point) -> None:
    """系列の model の替わり目 (紙 F-b K37 決定 2・4): 新しい model が並びの直和のモデルで、前の model をその来歴に持ち、
    その要求が前の区間の原記録を全部同じ順で先頭に読み直し、読み手がその並びのモデルの読み手であること。"""
    c = _c()
    model = desc["args"]["model"]
    pool = pools.get(model)
    if pool is None or previous not in pool["lineage"]:
        raise _Issue("rejected", "observation_binding_mismatch", "the adoption series changes its model",
                     fields=("/args/prior",), evidence=(point,))
    listed = list(dict.fromkeys(use["binding"] for use in desc["args"]["observations"]))
    if listed[:len(applied)] != applied:
        raise _Issue("rejected", "observation_binding_mismatch",
                     "the new pool does not re-read the series from its origin", fields=("/args/observations",),
                     evidence=(point, pool["point"]))
    if _content(reader, desc["reader"], _knowledge_origin()).get("model") != model:
        raise _Issue("rejected", "observation_binding_mismatch", "the reader is not of the pool model",
                     fields=("/reader",), evidence=(point, desc["reader"]))


def _knowledge_origin():
    from .f_contracts import KNOWLEDGE_ORIGIN
    return KNOWLEDGE_ORIGIN


# --- 候補の並び (紙 F-b K37 決定 1・3・5・6・8) ---

def candidate_law(document, observation, pairs) -> str:
    """候補の予測の法則の識別 (知る対象に含める、K37 決定 1)。宣言 (モデルの document・観測モデル・物語の対応) の正準な
    要約で、同じ宣言なら同じ法則 (別名)。一般の法則の同値は判定しない。"""
    from .f import _digest
    return _digest({"domain": "sui.fb.candidate_law/1", "document": _json(document),
                    "observation_model": _json(_enc(observation)), "pairs": _json(pairs)})


def direct_sum(members) -> dict:
    """候補の並びの直和のモデルの document (K37 決定 1・3)。members は {id, document, weight, law} の列 (並びの順)。
    隠れた状態 = 「候補の番号:候補の中の状態」、知る対象 = 「法則の識別/元の知る対象」(同じ法則の別名は同じ知る対象)、
    事前 = 候補の重み × 候補の中の事前。核は全部の候補が宣言している核だけで、outcome は id ごとに各候補のかたまりを
    対角に並べる (その outcome の無い候補は 0 のかたまり。候補の間の移り変わりは構造の 0)。操作と方策は全部の候補が同じに
    宣言しているものだけ (共通部分)。表せない時は ValueError (理由の語)。"""
    from fractions import Fraction
    from .f import _Fraction, _decode, _dumps
    docs = [_json(m["document"]) for m in members]
    first = docs[0]
    for doc in docs[1:]:
        if any(_dumps(doc.get(k)) != _dumps(first.get(k))
               for k in ("scheme", "contract", "units", "certificate_capabilities")):
            raise ValueError("model_scheme")
    states, targets, initial, offsets = [], [], [], []
    for m, doc in zip(members, docs):
        offsets.append(len(states))
        states += [{"id": m["id"] + ":" + s["id"], "target": m["law"] + "/" + s["target"]} for s in doc["states"]]
        targets += [m["law"] + "/" + t for t in doc["targets"]]
        initial += [m["weight"] * q for q in _decode(doc["initial"], tuple[_Fraction, ...])]
    if len({s["id"] for s in states}) != len(states):
        raise ValueError("state_names")
    n = len(states)
    kernels = []
    for kernel in first["kernels"]:
        found = [next((k for k in doc["kernels"] if k["id"] == kernel["id"]), None) for doc in docs]
        if None in found:
            continue
        outcomes = {}
        for offset, k in zip(offsets, found):
            for o in k["outcomes"]:
                attrs = {key: value for key, value in o.items() if key not in ("id", "matrix")}
                if o["id"] not in outcomes:
                    outcomes[o["id"]] = (attrs, [[Fraction(0)] * n for _ in range(n)])
                elif _dumps(outcomes[o["id"]][0]) != _dumps(attrs):
                    raise ValueError("outcome_attributes")
                matrix = outcomes[o["id"]][1]
                for i, row in enumerate(o["matrix"]):
                    for j, x in enumerate(row):
                        matrix[offset + i][offset + j] = Fraction(*x) if isinstance(x, list) else Fraction(x)
        kernels.append({"id": kernel["id"], "outcomes": [
            {"id": oid, **attrs, "matrix": _enc(tuple(tuple(row) for row in matrix))}
            for oid, (attrs, matrix) in outcomes.items()]})

    def common(key):
        return [item for item in first[key] if all(any(_dumps(x) == _dumps(item) for x in doc[key]) for doc in docs[1:])]

    def ref(value):
        try:
            return value["args"]["id"]
        except (KeyError, TypeError):
            return None
    operations, policies = common("operations"), common("policies")
    kids = {k["id"] for k in kernels}
    while True:   # 欠けた核を使う方策・欠けた方策や核を使う操作を、閉じるまで外す
        oids = {o["id"] for o in operations}
        kept = [p for p in policies if all(node.get("kernel") in kids if node.get("kind") == "execute"
                                           else set(node.get("operations", ())) <= oids for node in p["nodes"])]
        pids = {p["id"] for p in kept}
        used = [o for o in operations if ref(o.get("policy")) in pids and ref(o.get("prediction")) in kids]
        if len(kept) == len(policies) and len(used) == len(operations):
            break
        policies, operations = kept, used
    if not kernels or not operations or not policies:
        raise ValueError("no_common_operation")
    return {"scheme": first["scheme"], "contract": first["contract"], "units": first["units"],
            "targets": list(dict.fromkeys(targets)), "states": states, "initial": _enc(tuple(initial)),
            "kernels": kernels, "operations": operations, "policies": policies,
            "certificate_capabilities": first["certificate_capabilities"]}


# --- 候補の解決 (紙 F-b K39 決定 8、★ (b)) ---
# 最初の並び・足した並び・スイッチの族の候補を、保存した宣言と参照先だけを読む副作用の無いこの 1 か所で作る。ホスト
# (`_fb_pool`) は結果を並び (Pool) に包み、入口 U は要求の入力に見える記録だけから同じ解決を呼んで、保存した派生のモデルと
# 照らす。候補の間の法則の一致は、ここが返す計算の種類 (computation) と測定の条件 (measurement) で確かめる (Python の型で
# 確かめない)。

_PART_KINDS = ("mood", "inert", "clock")   # この本が読める部品の種類 (倍率が何を読むか: 調子 S / 何も読まない / 時計の位置、K39 決定 1・K40 決定 1)


def _rising(x, n):
    """上昇階乗 (x)_n = x (x+1) … (x+n−1)。"""
    out = 1
    for i in range(n):
        out *= x + i
    return out


class Unresolved(Exception):
    """候補の解決の名指しの不足 (K39 決定 8・K39-b R1): この本で読めない候補。reason は理由の語、named は名指し (候補の名前と
    部品の名前)、field は宣言の欄、code は入口 U の不適合の語 (missing_contract / shape)。解決は正準な記述か、これのどちらかだけ
    を返す (不足を抱えた記述を返さない)。"""

    def __init__(self, reason, named, field, code):
        super().__init__(reason)
        self.reason, self.named, self.field, self.code = reason, tuple(named), field, code


def describe_candidate(*, id, model, document, observation, pairs, weight) -> dict:
    """候補 1 つの正準な記述 (K39 決定 8)。入力は宣言の値だけ (名前 id・候補のモデルの Point model とその document・観測の
    見込み observation・物語の対応 pairs・並びの起点での重み weight) で、何も書かない。この本で読めない候補は `Unresolved`。

    返す記述: id・model・base (宣言したモデルの document)・document (展開した状態と事前の document。スイッチの族が部品を
    持つ時は (z, S) に展開した直和 (`direct_sum`) で、知る対象は「解決した率の表の識別 / 元の知る対象」、部品 0 個なら base の
    まま = K38)・observation・pairs・phi (観測モデルの状態の番号 → base の状態の番号。対応はここ 1 か所で確かめる、K39-b R4)・
    weight・law (候補の法則の識別、`candidate_law`)・computation (計算の種類: "finite_kernel" (K26 の有限の核) / "poisson"
    (固定の Poisson 源とスイッチの族) / "finite_count" (有限の法則の時刻つきの例) / None (観測の見込みを読まない候補))・
    measurement (時刻を読む候補の測定の条件)・family (族の名前・a・b・部品の辞書)・branches (スイッチの列 z ごとの事前 P(z)・
    法則の状態ごとの率・率の表の識別、展開の順。時計の部品のオンの z は周期の候補ごとの枝に分かれ、事前は P(z)·π_T、時計の形
    clock を持つ。オフの枝の clock は None、K40)・size (展開した状態の数)・references (要る参照: 候補のモデル。宣言の記録は
    読む側が足す)。

    法則の形は 1 つ (決定 1・K39-b R2): PoissonLaw の family が None なら部品 0 個・p を宣言しない族 (K38)。"""
    from fractions import Fraction
    from .fb import AcquisitionObservationModel, FiniteCountLaw, PoissonLaw, TimedAcquisitionModel
    states = document.get("states") if hasattr(document, "get") else None
    out = {"id": id, "model": model, "base": document, "document": document, "observation": observation,
           "pairs": pairs, "phi": None, "weight": weight, "law": candidate_law(document, observation, pairs),
           "computation": None, "measurement": None, "family": None, "branches": None, "transitions": None,
           "size": len(states) if isinstance(states, list) else 0, "references": frozenset({model})}
    if observation is None:   # 観測の見込みを読まない候補 (区間の札の δ。取りに行きの δ の形の不足は更新の計画が名指す)
        return out
    if isinstance(observation, AcquisitionObservationModel):
        out["computation"], observed = "finite_kernel", observation.states
    elif not isinstance(observation, TimedAcquisitionModel):
        raise Unresolved("observation_unsupported", (id,), "/observation_model", "missing_contract")
    elif isinstance(observation.law, (PoissonLaw, FiniteCountLaw)):
        out["computation"] = "poisson" if isinstance(observation.law, PoissonLaw) else "finite_count"
        if out["computation"] == "poisson":
            # 調子の過程 (K41 決定 1): R = 0 は宣言の無い静的な法則と同じに解く (識別・測定の条件・計算の道も同じ)
            R = _state_process(id, observation.law)
            if R is None and observation.law.state_process is not None:
                from dataclasses import replace
                observation = replace(observation, law=replace(observation.law, state_process=None))
                out["observation"], out["law"] = observation, candidate_law(document, observation, pairs)
            out["transitions"] = R
        out["measurement"] = _json(_enc((observation.decision_time, observation.conditioning)))
        observed = observation.law.states
    else:
        raise Unresolved("law_unsupported", (id,), "/observation_model/law", "missing_contract")
    out["phi"] = _phi(id, pairs, observed, states)
    if out["computation"] != "poisson":
        return out
    law = observation.law
    parts, role = law.parts, law.state_role
    # 受け付ける部品 (K39 決定 1・2): 調子の部品 (S を読む倍率、族に高々 1 つ、S 全体が調子の役で遷移なしと宣言 + 基準の率が
    # S によらない、を法則から確かめる) と倍率 1 の部品だけ。ほかは名指して対応していない
    unknown = tuple(x.id for x in parts if x.kind not in _PART_KINDS)
    moods = tuple(x.id for x in parts if x.kind == "mood")
    if unknown:
        raise Unresolved("part_kind", (id, *unknown), "/observation_model/law/parts", "missing_contract")
    if role not in (None, "mood"):
        raise Unresolved("state_role", (id, role), "/observation_model/law/state_role", "missing_contract")
    if len(moods) > 1:
        raise Unresolved("mood_parts", (id, *moods), "/observation_model/law/parts", "missing_contract")
    if moods and role is None:
        raise Unresolved("mood_role", (id, *moods), "/observation_model/law/state_role", "missing_contract")
    if moods and len(set(law.rates)) > 1:
        raise Unresolved("mood_base_rate", (id, *moods, "rates"), "/observation_model/law/rates", "missing_contract")
    # 時計の部品 (K40 決定 1): 族に高々 1 つ。S を読まない。オンの枝は周期の候補ごとに分かれる (区切りの数・周期の候補は
    # k や |z| に足さない、決定 5)
    clocks = tuple(x for x in parts if x.kind == "clock")
    if len(clocks) > 1:
        raise Unresolved("clock_parts", (id, *(x.id for x in clocks)), "/observation_model/law/parts", "missing_contract")
    choices, material = _clock_choices(id, clocks[0]) if clocks else ((), None)
    on = parts.index(clocks[0]) if clocks else None
    from itertools import product
    from .f import _digest
    k = len(parts)
    branches = []
    for z in product((0, 1), repeat=k):
        m = sum(z)
        rates = tuple(rate * _multiplier(parts, z, i) for i, rate in enumerate(law.rates))
        pz = _rising(law.a, m) * _rising(law.b, k - m) / _rising(law.a + law.b, k) if k else Fraction(1)
        for weight, clock, suffix in (choices if on is not None and z[on] else ((1, None, ""),)):
            # 知る対象 (決定 8): 時計とスイッチを当てた後の、時刻と状態ごとの率の関数。時計の形は正準な形で比べ、効かない時計
            # (f = w) は時計の無い法則と同じ識別になる
            shape = None if clock is None else _clock_law(clock)
            # 遷移のある調子は R も識別に入れる (状態の名前で、正の率の辺だけ。K41 決定 7)
            R = out["transitions"]
            moves = None if R is None else sorted([law.states[i], law.states[j], _enc(r)]
                                                  for i, row in enumerate(R) for j, r in enumerate(row) if r)
            table = _digest({"domain": "sui.fb.rate_table/1",
                             "rates": [[s, _enc(r)] for s, r in sorted(zip(law.states, rates))],
                             **({} if shape is None else {"clock": _enc(shape)}),
                             **({} if moves is None else {"transitions": moves})})
            branches.append({"z": z, "label": "z=" + "".join(map(str, z)) + suffix,
                             "prior": pz * weight, "rates": rates, "clock": clock, "table": table})
    out["branches"] = branches
    if law.family is not None:
        out["family"] = {"name": law.family, "a": law.a, "b": law.b, "parts": [[x.id, x.kind] for x in parts]}
        if clocks:   # 時計の照会の材料 (K40 決定 15): 周期・区切りの数の宣言の候補と事前 (時計のオフの枝にも潜在として在る)
            out["family"]["clock"] = material
    # (z, S) に展開: 枝ごとに宣言のモデルの写しを、事前 P(z) と率の表の識別で直和に並べる (状態を変えない核は I_z ⊗ K)。
    # 遷移のある調子は部品 0 個でも展開し、知る対象を「解決した法則 (R を含む) の識別 / 元の知る対象」にする (K41 決定 7)
    if k or out["transitions"] is not None:
        try:
            out["document"] = direct_sum([{"id": x["label"], "document": document, "weight": x["prior"], "law": x["table"]}
                                          for x in branches])
        except (ValueError, KeyError, TypeError):
            raise Unresolved("model_shape", (id,), "/args/model", "shape") from None
        out["size"] = len(out["document"]["states"])
    return out


def step_time_reading(members, document, kid, cells, reading):
    """核 kid の一歩を、並び (members = 候補の記述の列、並びの順。document はその並びのモデル) の下で時刻つきに読めない理由の
    語、読めれば None (紙 F-b K41 決定 6)。遷移のある候補が無ければ None。ある時は、候補ごとに入口 U と同じ読み方
    (`step_kernel` を候補の document と同じセルで、K37 決定 6) で、入場の時点を読む所要 0 の状態を変えない観測の一歩でなければ
    `measurement_unsupported` (合わない性質まで名指す)、そうなら記録の時刻の根拠と読む時刻の宣言を `step_time_fault` で
    確かめる。読む時刻を省けるかは、比べる世界 (F-a) と U のどちらが区別する観測でも変わらないこと = いちばん細かい観測の
    類 (`instant_classes`、U のセルはその和) で確かめる (レビュー 6 通目)。並びができる時の確かめ (`pool_time_fault`) と入口 U が
    同じこの判定を使う (レビュー R4・R4-C・R4-E)。cells はセルの JSON の列。"""
    if not any(m.get("transitions") is not None for m in members):
        return None
    try:
        for m in members:
            step_kernel(m["document"], kid, cells, evidence=())
    except _Issue as issue:   # 合わない性質まで名指す (所要・観測・行列・セル)
        return "measurement_unsupported" + "".join(":" + f.rsplit("/", 1)[-1] for f in issue.fields)
    return step_time_fault(members, reading, instant_classes(document, kid)[1])


def pool_time_fault(members, document, execution):
    """遷移のある並び (members = 候補の記述の列、並びの順。document はその並びのモデル) で、時刻つきに読めない一歩
    "<核>:<理由の語>"、読めれば None (紙 F-b K41 決定 6・K41-i・K41-j)。見る核は、比べる世界の核 (並びのモデルの操作から
    届く核 = 操作の予測の核と、操作の方策の execute の節の核。F-a が比べる世界を組む時に解く核。外へ出せない核も比べる世界には
    入る) と、宣言した一歩の読みの全部 (宣言した無作用の核は除く。前の並びで選んだ一歩も、宣言した核ならこの並びで外へ出る)。
    宣言した読みは入口 U と同じ読み方 (`step_time_reading`)、比べるだけの核は判断の時刻 j に直ちに読めるか
    (`compared_time_reading`) で見る。並びが変わるのは起動の最初の候補と候補を足す時だけなので、その 2 か所が呼ぶ。"""
    from itertools import accumulate
    from .fb import TimedExecutionDeclaration
    if not any(m.get("transitions") is not None for m in members):
        return None
    timed = execution if isinstance(execution, TimedExecutionDeclaration) else None
    declared = set() if timed is None else {*timed.actors, *timed.source_readings} - set(timed.no_effect)
    policies = {p["id"]: p for p in document["policies"]}
    compared = {op["prediction"]["args"]["id"] for op in document["operations"]} | {
        node["kernel"] for op in document["operations"] for node in policies[op["policy"]["args"]["id"]]["nodes"]
        if node["kind"] == "execute"}
    # 並びの中の位置は並びの順と大きさだけで決まる (入口 U が並びの記録を読む `pool_candidates` と同じ)
    members = [{**m, "offset": o} for m, o in zip(members, accumulate((m["size"] for m in members), initial=0))]
    for kid in sorted(compared | declared):
        fault = step_time_reading(members, document, kid, [_json(_enc(c)) for c in timed.cells.get(kid, ())],
                                  timed.source_readings.get(kid)) if kid in declared             else compared_time_reading(members, document, kid)
        if fault is not None:
            return kid + ":" + fault
    return None


def compared_time_reading(members, document, kid):
    """比べるだけの核 kid (読む時刻の宣言が無い) を、遷移のある並びの評価が判断の時刻 j に直ちに読めない理由の語、読めれば
    None (紙 F-b K41 決定 6 の「読む時刻の宣言が無い一歩は、許された遷移で E_y が変わらないと証明できる範囲だけ読む」)。
    所要 0 の状態を変えない観測でなければ名指し (`instant_classes`)、そうなら観測の類の核が遷移で変わらないこと
    (`read_instant_fault`)。"""
    fault, diagonals = instant_classes(document, kid)
    return fault or read_instant_fault(members, None, diagonals)


def instant_classes(document, kid):
    """並びのモデル document の核 kid を F-a と同じ復号 (`FiniteKernel`、有理数の対の 0 を正と取り違えない) で読み、
    (不足の語, 観測の類ごとの対角)。観測の類は F-a と同じく観測 (evidence) の等しい正の質量の結果の和 (いちばん細かい類。U の
    セルは同じ観測値の類の和なので、この類で変わらなければセルでも変わらない)。読む時刻を省いて判断の時刻・入場の時刻に直ちに
    読めるのは、所要 0 の状態を変えない (対角の) 観測だけ: 正の質量の結果に所要があれば `measurement_unsupported:elapsed_ns`、
    非対角の成分があれば `measurement_unsupported:matrix` (所要・状態を変える一歩の共同のモデルは ⑦ と S6)。"""
    from .f import FiniteKernel, _decode, _dumps
    kernel = _decode(next(k for k in document["kernels"] if k["id"] == kid), FiniteKernel)
    n = len(document["states"])
    positive = [o for o in kernel.outcomes if any(q for row in o.matrix for q in row)]
    classes = {}
    for o in positive:
        classes.setdefault(_dumps(_enc(o.evidence)), []).append(o)
    diagonals = [[sum(o.matrix[i][i] for o in group) for i in range(n)] for group in classes.values()]
    if any(o.elapsed_ns != 0 for o in positive):
        return "measurement_unsupported:elapsed_ns", diagonals
    if any(o.matrix[i][j] for o in positive for i in range(n) for j in range(n) if i != j):
        return "measurement_unsupported:matrix", diagonals
    return None, diagonals


def step_time_fault(members, reading, diagonals):
    """一歩の時刻の読みの不足の理由の語 (紙 F-b K41 決定 6)、または None。members は解いた並びの候補 (offset・phi・branches・
    transitions)、reading は一歩の源の件数の読み (`fb.SourceCountReading`)、diagonals は観測の類 (観測 (evidence) の等しい
    結果の和 = `instant_classes`。U のセルはその和) ごとの、並びの展開した状態の上の結果の核の対角。遷移のある候補が無ければ不足は無い (静的な調子は時刻を条件にしない)。ある時は、記録の時刻を
    条件にしてよい根拠 (`time_basis`: 時刻を決めた材料が全部記録されている / 時刻の出どころが独立と認証されている、K26 の形) が
    要り、読む時刻の宣言 (`measurement`: 入場の時点の S を読む所要 0 の観測) は、どの候補・枝でも正の率の遷移の両端で結果の核が
    同じ (遷移で結果が変わらない) 時だけ省ける (`read_instant_fault`)。宣言した一歩の読み (`step_time_reading`) が使う。"""
    c = _c()
    chained = [m for m in members if m.get("transitions") is not None]
    if not chained:
        return None
    basis = getattr(reading, "time_basis", None)
    if basis is None or basis.contract not in (c.RECORDED_TIMING_INPUTS, c.INDEPENDENT_TIMING_SOURCE):
        return "time_basis_missing"
    return read_instant_fault(members, getattr(reading, "measurement", None), diagonals)


def read_instant_fault(members, measurement, diagonals):
    """読む時刻の不足の理由の語、または None (紙 F-b K41 決定 6)。読む時刻の宣言 measurement は「入場の時点の S を読む」
    (`sui.fb.instantaneous_entry_observation/1`) だけを通す。宣言が無ければ、どの候補・枝でも正の率の遷移の両端で観測の類の
    核の対角 (diagonals、並びの展開した状態の上) が同じ時だけ通す。宣言した一歩 (`step_time_fault`) と比べるだけの核
    (`compared_time_reading`) が同じこの判定を使う。"""
    c = _c()
    if measurement is not None:
        return None if measurement.contract == c.INSTANTANEOUS_ENTRY_OBSERVATION else "measurement_unsupported"
    for m in members:
        if m.get("transitions") is None:
            continue
        n, phi, R = len(m["base"]["states"]), m["phi"], m["transitions"]
        for b in range(len(m["branches"] or (None,))):
            at = [m["offset"] + b * n + phi[a] for a in range(len(R))]
            if any(r and d[at[a]] != d[at[a2]] for d in diagonals for a, row in enumerate(R) for a2, r in enumerate(row)):
                return "measurement_missing"
    return None


def _state_process(id, law):
    """調子の過程の宣言 (K41 決定 1) を、宣言の状態の順の生成行列の非対角 R (R[i][j] は i → j の率) に解く。R がすべて 0・宣言が
    無ければ None (静的な法則)。読めるのは調子の役を宣言した法則の固定の生成行列 (`sui.fb.fixed_state_generator/1`、行 = 出る
    状態、非対角は非負の有理数、対角は出る率の和の負) だけ。役の無い法則・知らない過程・有理数の対でない数 (K38 決定 1) は対応
    していない (missing_contract)、行列の形・符号・対角の誤りは shape。名指しは候補と欄の名前。"""
    from fractions import Fraction
    process = law.state_process
    if process is None:
        return None
    if law.state_role != "mood":   # 遷移の宣言は調子の役の状態のもの (R = 0 の明示も、役の宣言の不足。レビュー R7)
        raise Unresolved("state_process_role", (id, "state_role"), "/observation_model/law/state_role", "missing_contract")
    named, field = (id, "state_process"), "/observation_model/law/state_process"
    if process.contract != _c().FIXED_STATE_GENERATOR:
        raise Unresolved("state_process", named, field, "missing_contract")
    n = len(law.states)

    def entry(x):   # 有理数の対 [分子, 分母] (分母は正)。数そのもの (小数など) は別の表し方 → None
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            return None
        if not isinstance(x, (list, tuple)) or len(x) != 2 or any(type(y) is not int for y in x) or x[1] <= 0:
            raise ValueError
        return Fraction(x[0], x[1])
    try:
        rows = process.args["matrix"]
        if set(process.args.keys()) != {"matrix"} or len(rows) != n or any(len(row) != n for row in rows):
            raise ValueError
        M = [[entry(x) for x in row] for row in rows]
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Unresolved("state_process", named, field, "shape") from None
    if any(x is None for row in M for x in row):
        raise Unresolved("state_process_number", named, field, "missing_contract")
    off = [(i, j) for i in range(n) for j in range(n) if i != j]
    if any(M[i][j] < 0 for i, j in off) or any(M[i][i] != -sum(M[i][j] for j in range(n) if j != i) for i in range(n)):
        raise Unresolved("state_process", named, field, "shape")
    R = tuple(tuple(M[i][j] if i != j else Fraction(0) for j in range(n)) for i in range(n))
    return R if any(any(row) for row in R) else None


def _phi(name, pairs, observed, states):
    """物語の対応の確かめ (K39-b R4、K28 新しい決定 3 の 1 対 1): pairs が [観測モデルの状態, 宣言のモデルの状態] の組の列で、
    両側の状態の集合とちょうど 1 対 1。観測モデルの状態の番号 → 宣言のモデルの状態の番号 を返す。外れたら名指しの不足。"""
    ids = [s.get("id") for s in states] if isinstance(states, list) and all(isinstance(s, dict) for s in states) else None
    pairs = _json(pairs)
    # 両側が文字列の状態名の列だと確かめてから 1 対 1 を作る (K39 レビュー 3 通目 R1: 壊れたモデルの名前で集合を作ると TypeError)
    if ids is None or not all(isinstance(x, str) for x in ids) or not all(isinstance(x, str) for x in observed) \
            or not pairs_shape(pairs):
        raise Unresolved("correspondence", (name,), "/pairs", "shape")
    # 重ならない名前どうしの 1 対 1 を作れた時だけ返す (K39 レビュー 2 通目 R1: 両側の名前が重なると dict が上書きして
    # 1 対 1 でない対応を成功として返していた)
    forward, backward = dict(pairs), {m: a for a, m in pairs}
    if len(forward) != len(pairs) or len(backward) != len(pairs) or len(set(observed)) != len(observed) \
            or len(set(ids)) != len(ids) or set(forward) != set(observed) or set(backward) != set(ids):
        raise Unresolved("correspondence", (name,), "/pairs", "shape")
    return [ids.index(forward[a]) for a in observed]


def pairs_shape(pairs) -> bool:
    """物語の対応の形 (組 [観測モデルの状態, 宣言のモデルの状態] の列、どちらも文字列) だけを見る 1 か所 (K39 レビュー 2 通目
    R2)。形の誤りは起動の δ の hold (`delta:correspondence`) が名指し、中身 (1 対 1) は候補の解決 (`_phi`) が名指す。"""
    return isinstance(pairs, list) and all(
        isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) for y in x) for x in pairs)


def _clock_choices(id, part):
    """時計の部品の宣言 (`fb.SwitchPart` の clock = `fb.ClockPrior`) を確かめ、時計のオンの枝の (事前の重み π_T · π_m, 時計の形,
    枝の名前の添え字) の列と、時計の照会の材料 (部品の名前・周期と区切りの数の候補と事前、K40 決定 15) に解く (K40 決定 1・2・4)。
    周期の候補 × 区切りの数 m ごとに、ρ・w・f が全部点の事前なら点の形 {"period", "starts", "multipliers"}
    (`_fb_clock.point_shape`)、どれかが連続の事前なら連続の形 {"period", "segments", "rotation" (None は一様),
    "widths"・"width_concentration", "shares"・"share_concentration"} (θ は正本の積分で読む、決定 5・7)。値の誤りは invalid
    (shape)、この本が読めない宣言 (状態を読む時計・因子の積の外の依存・知らない形の種類) は unsupported (missing_contract)。
    名指しは候補と部品の名前。"""
    from collections.abc import Mapping
    from fractions import Fraction
    from ._fb_clock import point_shape
    prior, named, field = part.clock, (id, part.id), "/observation_model/law/parts"

    def fail(reason, code="shape"):
        raise Unresolved(reason, named, field, code)

    def number(x, positive=True):
        return type(x) is Fraction and (x > 0 if positive else x >= 0)

    def candidates(pairs, admissible):   # ((値, 事前の重み), …): 値は異なり、重みは正で和 1
        if type(pairs) is not tuple or not pairs or any(
                type(p) is not tuple or len(p) != 2 or not admissible(p[0]) or not number(p[1]) for p in pairs) \
                or len({p[0] for p in pairs}) != len(pairs) or sum(p[1] for p in pairs) != 1:
            fail("clock_candidates")
        return pairs

    def declared(value, kinds):   # 形の宣言 {"kind", 欄}: 知らない種類は対応していない
        if not isinstance(value, Mapping) or value.get("kind") not in kinds:
            fail("clock_shape_kind", "missing_contract")
        if set(value) != {"kind", *kinds[value["kind"]]}:
            fail("clock_shape")
        return value["kind"], next((value[k] for k in kinds[value["kind"]]), None)

    def simplex(value, continuous):   # 点 → ({m: (値, …)}, None)、連続 → (None, 集中度)
        kind, x = declared(value, {"point": ("values",), continuous: ("concentration",)})
        if kind != "point":
            if not number(x):
                fail("clock_concentration")
            return None, x
        if type(x) is not tuple or any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not int for p in x) \
                or len(dict(x)) != len(x) or set(dict(x)) != set(counts) or any(
                type(v) is not tuple or len(v) != m or not all(number(y) for y in v) or sum(v) != 1 for m, v in x):
            fail("clock_point")
        return dict(x), None
    if part.multipliers:   # 時計の部品は状態 S を読まない (決定 1)
        fail("clock_reads_state", "missing_contract")
    if prior.couplings:    # 共同の事前は宣言した因子の積だけ (決定 4)
        fail("clock_coupling", "missing_contract")
    if type(prior.max_segments) is not int or prior.max_segments < 2:
        fail("clock_segments")
    periods = candidates(prior.periods, number)
    segments = candidates(prior.segments, lambda m: type(m) is int and 2 <= m <= prior.max_segments)
    counts = [m for m, _w in segments]
    kind, rho = declared(prior.phase, {"uniform": (), "point": ("value",)})
    if kind == "point" and not (number(rho, positive=False) and rho < 1):
        fail("clock_phase")
    widths, kw = simplex(prior.widths, "symmetric_dirichlet")
    shares, kf = simplex(prior.fractions, "conditional_dirichlet")
    choices = []
    for t, (period, pt) in enumerate(periods):
        for m, pm in segments:
            w, f = (None if x is None else x[m] for x in (widths, shares))
            shape = point_shape(period, rho, w, f) if rho is not None and w is not None and f is not None else {
                "period": period, "segments": m, "rotation": rho, "widths": None if w is None else list(w),
                "width_concentration": kw, "shares": None if f is None else list(f), "share_concentration": kf}
            choices.append((pt * pm, shape, ";T=" + str(t) + ";m=" + str(m)))
    return tuple(choices), {"part": part.id, "periods": [p for p, _w in periods],
                            "period_weights": [w for _p, w in periods], "segments": counts,
                            "segment_weights": [w for _m, w in segments]}


def _clock_law(clock):
    """時計の形の正準な形 (K40 決定 8): 区切りの番号・回転の取り方・同じ高さの隣の区切り・短い周期を長い周期で書いた別名で
    変わらない、起点からの経過時間の関数の表し方。最小の周期 P と、[0, P) の中の高さの変わり目 (時刻, 倍率) の列。全部の区切りで
    倍率 1 (f = w) なら None (時計の無い法則と同じ)。連続の事前の枝 (θ を積分する) は、周期・区切りの数・事前の宣言そのものを
    識別にする (知る対象は θ の関数で、考える側への写像は決定 8・12。率の表の識別はこの枝の族を名指すだけ)。"""
    from fractions import Fraction
    if "segments" in clock:
        return {"family": clock}
    pairs = list(zip(clock["starts"], clock["multipliers"]))
    changes = [p for i, p in enumerate(pairs) if p[1] != pairs[i - 1][1]]   # 円の上で前と同じ高さの始まりは境目でない
    if not changes:   # 1 つの高さ: 平均が 1 なので倍率 1 (決定 3)
        return None
    n, period = len(changes), clock["period"]
    k = max(k for k in range(1, n + 1)
            if n % k == 0 and sorted(((s + Fraction(1, k)) % 1, r) for s, r in changes) == sorted(changes))
    least = period / k
    return {"period": least, "changes": sorted({((s * period) % least, r) for s, r in changes})}


def _multiplier(parts, z, i):
    """スイッチの列 z の下で、法則の状態 i の基準の率に掛かる倍率 Π_{z_j = 1} r_j(S_i) (倍率 1 の部品は 1)。"""
    out = 1
    for part, bit in zip(parts, z):
        if bit and part.kind == "mood":
            out *= part.multipliers[i]
    return out


def initial_candidate(reader, boot, *, named=None) -> dict:
    """最初の並び (起動の宣言の 1 枚) の候補の記述 (K39 決定 8): 保存した起動の宣言の感じる側 (名前 = perception.slot、モデル、
    δ の args が名指す観測モデルの位置と物語の対応) と、そのモデルの document を読み、`describe_candidate` で解く。δ の args の
    形が違えば (観測モデルを名指せない・対応が組の列でない) 観測の見込みを読まない候補として記述する (δ の形の不足を示すのは
    更新の計画)。宣言の中身が読めなければ `Unresolved` (起動の計画の不足として示す、K39-b R1)。
    named = (観測モデル, 対応の pairs) は、読み方が名指した記録から読んだ宣言 (入口 U。K28 決定 6: 読み方が名指す宣言で読む)。
    名前とモデルは起動の宣言のまま。"""
    from fractions import Fraction
    from .f import FInputError, _decode
    from .fb import AcquisitionObservationModel, TimedAcquisitionModel
    c = _c()
    content = _json(_content(reader, boot, c.BOOT_DECLARATION))
    try:
        perception = content["perception"]
        name, value = perception["slot"], perception["declaration"]["value"]
        model, args = value["model"], value["derivation"]["method"]["args"]
    except (KeyError, TypeError):
        raise _Issue("rejected", "shape", "the boot declaration names no perception", evidence=(boot,)) from None
    args = args if isinstance(args, dict) else {}
    kinds = {_dumps_enc(c.ACQUISITION_OBSERVATION_MODEL): AcquisitionObservationModel,
             _dumps_enc(c.TIMED_ACQUISITION_MODEL): TimedAcquisitionModel}
    observation = None
    for item in content.get("observation_models") or ():
        if not isinstance(item, dict) or item.get("slot") != args.get("observation_model"):
            continue
        try:
            typ = kinds.get(_dumps_enc(item["declaration"]["contract"]))
            observation = None if typ is None else _decode(item["declaration"]["value"], typ)
        except (FInputError, KeyError, TypeError, ValueError):
            # 名指した観測モデルの記録が読めない時は、観測を読まない候補 (区間の札の δ) とまとめずに名指しの不足
            # (K39 試験の係 123 通目 CG: 読めないことと宣言しないことは別の意味)
            raise Unresolved("correspondence", (name,), "/observation_model", "shape") from None   # 対応の片側の名前が読めない
    correspondence = args.get("correspondence")
    pairs = correspondence.get("pairs") if isinstance(correspondence, dict) else None
    if not pairs_shape(_json(pairs)):   # δ の args の形の不足は更新の計画が名指す (候補は観測の見込みを読まない)
        observation = None
    if named is not None:
        observation, pairs = named
    member = describe_candidate(id=name, model=model, document=_model_document(reader, model, evidence=(boot, model)),
                                observation=observation, pairs=pairs, weight=Fraction(1))
    member["offset"], member["references"] = 0, member["references"] | {boot}
    return member


def _dumps_enc(value):
    from .f import _dumps
    return _dumps(value if isinstance(value, dict) else _enc(value))


def pool_candidates(reader, point):
    """足した並びの記録 (`sui.fb.belief_pool/1`) の候補の記述の列 (K39 決定 8): 記録の各候補の宣言 (モデル・観測モデル・物語の
    対応・重み) を読み、`describe_candidate` で解き、並びの順に offset を付ける。記録した法則の識別が解決と違えば不適合
    (派生物を信じない)。(並びの記録の本文, 候補の記述の列) を返す。"""
    from .f import FInputError, _Fraction, _decode
    from .fb import AcquisitionObservationModel, TimedAcquisitionModel
    content = _json(_content(reader, point, _c().BELIEF_POOL))
    members, offset = [], 0
    for value in content.get("members", ()):
        ev = (point, value.get("model"))
        document = _model_document(reader, value.get("model"), evidence=ev)
        try:
            observation = _decode(value["observation_model"], AcquisitionObservationModel | TimedAcquisitionModel)
            weight = _decode(value["prior_weight"], _Fraction)
            pairs = value["correspondence"]["pairs"]
        except (FInputError, KeyError, TypeError, ValueError):
            raise _Issue("rejected", "shape", "a pool member is unreadable", evidence=ev) from None
        try:
            member = describe_candidate(id=value["id"], model=value["model"], document=document,
                                        observation=observation, pairs=pairs, weight=weight)
        except Unresolved as exc:
            raise _Issue("rejected", exc.code, "a pool member is unresolvable: " + exc.reason, fields=(exc.field,),
                         evidence=ev) from None
        if value.get("law") != member["law"]:
            raise _Issue("rejected", "result_mismatch", "a pool member's law differs from its declaration", evidence=ev)
        member["offset"], member["references"] = offset, member["references"] | {point}
        offset += member["size"]
        members.append(member)
    return content, members


class _Pools:
    """系列の頭の要求の入力にある並びの記録を、要る所 (取りに行き・行った一歩を読む所と、model の替わり目) で初めて
    読む (区間の札の系列は並びを読まない)。get(model) はその model を直和のモデルに持つ並び、無ければ None。"""

    def __init__(self, reader, desc):
        self._reader, self._desc, self._found = reader, desc, None

    def get(self, model):
        if self._found is None:
            self._found = _pools(self._reader, self._desc)
        return self._found.get(model)


def _pools(reader, desc) -> dict:
    """要求の入力にある並びの記録 (`sui.fb.belief_pool/1`) を、その直和のモデルの Point ごとに読む (K37 決定 1・3)。同じ
    model の並びが 2 つあれば読めない。記録した候補から法則と直和のモデルを作り直し、保存した直和のモデルと全比較する
    (派生物を信じない)。"""
    from .f import _dumps
    c = _c()
    out = {}
    for p in sorted(desc["input_points"]):
        try:
            record = reader.record(p)
        except KeyError:
            continue   # 読めない入力は、それを使う所で名指す
        if record.body.contract != c.BELIEF_POOL:
            continue
        content = _json(record.body.content.as_json())
        if content.get("model") in out:
            raise _Issue("rejected", "shape", "two pools of one model", evidence=(out[content["model"]]["point"], p))
        content, members = pool_candidates(reader, p)   # ホストの `_fb_pool.resolve` と同じ候補の解決 (K39 決定 8)
        try:
            expected = direct_sum(members) if members else None
        except ValueError:
            expected = None
        if expected is None or _dumps(expected) != _dumps(_model_document(reader, content["model"], evidence=(p,))):
            raise _Issue("rejected", "result_mismatch", "the pool model differs from the direct sum of its candidates",
                         evidence=(p, content.get("model")))
        out[content["model"]] = {"point": p, "model": content["model"], "route": content.get("route"),
                                 "lineage": tuple(content["lineage"]), "members": members}
    return out


def _diag(blocks):
    """候補ごとのかたまりを対角に並べた行列 (並びの状態の順)。"""
    from fractions import Fraction
    n = sum(len(b) for b in blocks)
    out, offset = [[Fraction(0)] * n for _ in range(n)], 0
    for b in blocks:
        for i, row in enumerate(b):
            for j, x in enumerate(row):
                out[offset + i][offset + j] = x
        offset += len(b)
    return out


def member_reading(member, *, route, evidence_model, evidence_pairs):
    """候補 1 つの受け身の観測の読み方 (K28 新しい決定 3・9、K37 決定 6): 観測モデルの宣言がその並びの口 route のもの
    (同じ起動の口の宣言の位置、`fb.AcquisitionObservationModel.route_slot`) で、読み口と同じ形の検査・取りに行き方の制御の
    表と重みに合い、核が物語の対応 (1 対 1 は候補の解決が確かめた phi) で知る対象を横切らないことを確かめ、(制御, 観測モデルの
    状態の番号 → 候補の宣言したモデル (base) の状態の番号) を返す。member は候補の記述 (`describe_candidate`)。読めなければ
    不適合 (名指しは evidence)。
    家の人の事前の判定と入口 U が同じこの関数を使う。"""
    from . import _fb_read
    c = _c()
    declaration = member["observation"]
    if declaration.route_slot != route:
        raise _Issue("rejected", "missing_contract", "the observation model is of another route",
                     fields=("/observation_model",), evidence=evidence_model)
    from .fb import TimedAcquisitionModel
    if isinstance(declaration, TimedAcquisitionModel):
        return None, _timed_member(member, declaration, evidence_model=evidence_model)
    try:
        if declaration.projection != c.ACQUISITION_RESULT_PROJECTION or declaration.time_projection != _value_only() \
                or declaration.control_rule.contract != c.ACQUISITION_CONTROL_TABLE \
                or declaration.independence.contract != c.STATE_INDEPENDENT_CONTROL_SELECTION:
            raise _fb_read._Unreadable("missing_declaration")
        _fb_read._check_model(declaration)
        _fb_read._time_projection(declaration)
    except _fb_read._Unreadable as exc:
        raise _Issue("rejected", _UNREADABLE[exc.reason], "the observation model is unreadable: " + exc.reason,
                     fields=("/observation_model",), evidence=evidence_model) from None
    from fractions import Fraction
    u_id = c.ACQUISITION_REPEAT_WHEN_DONE.name + "/" + c.ACQUISITION_REPEAT_WHEN_DONE.version
    symbols = sorted(set(_fb_read._SYMBOLS.values()))
    if [u.id for u in declaration.controls] != [u_id] \
            or _json(declaration.control_rule.args) != {"first": [u_id], "after": {s: [u_id] for s in symbols}} \
            or _weights(declaration.independence.args) != ((Fraction(1),),) * len(declaration.states):
        raise _Issue("rejected", "missing_contract", "acquisition repeat or control declaration",
                     fields=("/observation_model",), evidence=evidence_model)
    control, = declaration.controls
    targets = [s["target"] for s in member["base"]["states"]]
    phi = member["phi"]   # 観測モデルの状態の番号 → 見立ての状態の番号 (候補の解決が確かめた対応、K39-b R4)
    n = len(targets)
    for o in control.kernel.outcomes:
        for i in range(n):
            for j in range(n):
                if o.matrix[i][j] and targets[phi[i]] != targets[phi[j]]:
                    raise _Issue("rejected", "shape", "the kernel crosses a target", fields=("/pairs",),
                                 evidence=evidence_pairs)
    return control, phi


def _timed_member(member, declaration, *, evidence_model):
    """時刻を読む観測モデル (K38) の候補 1 つの読み方: 取りに行き方の制御の表と重みは K26 と同じ形、件数の法則とスイッチの族は
    候補の解決がこの本で読めるとしたもの (固定の Poisson 源とスイッチの族・有限の法則。読めなければ解決が名指して止める、
    K39 決定 1・2・8) で、時計の run が端点の予定と同じ、法則の事前がその候補の宣言したモデルの事前と同じ (事前を 2 か所に
    持たない)。観測モデルの状態の番号 → 候補の宣言したモデル (base) の状態の番号 (解決が確かめた対応) を返す。"""
    from fractions import Fraction
    from .f import _Fraction, _decode
    c = _c()
    u_id = c.ACQUISITION_REPEAT_WHEN_DONE.name + "/" + c.ACQUISITION_REPEAT_WHEN_DONE.version
    from . import _fb_read
    symbols = sorted(set(_fb_read._SYMBOLS.values()))
    law = declaration.law
    if declaration.control_rule.contract != c.ACQUISITION_CONTROL_TABLE \
            or declaration.control_independence.contract != c.STATE_INDEPENDENT_CONTROL_SELECTION \
            or _json(declaration.control_rule.args) != {"first": [u_id], "after": {s: [u_id] for s in symbols}} \
            or _weights(declaration.control_independence.args) != ((Fraction(1),),) * len(law.states):
        raise _Issue("rejected", "missing_contract", "acquisition repeat or control declaration",
                     fields=("/observation_model",), evidence=evidence_model)
    if law.run != declaration.conditioning.run:
        raise _Issue("rejected", "missing_contract", "the law and the schedule read different clocks",
                     fields=("/observation_model/law/run",), evidence=evidence_model)
    phi = member["phi"]   # 候補の解決が確かめた対応 (K39-b R4)
    initial = _decode(member["base"]["initial"], tuple[_Fraction, ...])
    if any(initial[phi[a]] != p for a, p in enumerate(law.prior)):
        raise _Issue("rejected", "shape", "the law's prior differs from the model's prior",
                     fields=("/observation_model/law/prior",), evidence=evidence_model)
    return phi


def passive_block(control, phi, symbol, *, sampling, evidence, size):
    """受け身の取りに行き 1 回の、候補 1 つのかたまりの行列 (候補のモデルの状態の順、正規化する前のセルの和)。sampling は
    測る契約 (K26-d (ク) の照らし。None は照らさない = 順の判定だけに使う時)。セルの無い観測は質量 0 のかたまり。
    時刻を読む取りに行き (control=None、K38) は S とスイッチを変えず源の件数だけに働く (状態ごとのかたまり)。S の上の行列では
    ないので、順の判定 (状態を変えない一歩との交換) には、候補の展開した状態の数 size (K39) の単位で表す。数は時刻を読む正本で
    計算する。"""
    from fractions import Fraction
    from . import _fb_read
    if control is None:
        return [[Fraction(int(i == j)) for j in range(size)] for i in range(size)]
    outcomes = {o.id: o for o in control.kernel.outcomes}
    if sampling is not None:
        # K26-d (ク): セルの観測値と、そのセルの outcome の evidence (kind・測る契約・射影した観測値) が一致する
        for cell in control.cells:
            for name in cell.outcomes:
                emission = outcomes[name].evidence
                if emission is None or emission.kind != "measurement" or emission.measurement_contract != sampling \
                        or cell.observation.kind != "measurement" \
                        or _json(emission.value) != _json(cell.observation.value):
                    raise _Issue("rejected", "missing_contract", "outcome evidence differs from its observation cell",
                                 fields=("/observation_model",), evidence=evidence)
    cell = next((x for x in control.cells if _fb_read._symbol(x.observation) == symbol), None)
    members = set(cell.outcomes) if cell is not None else set()   # セルが無い観測は、モデルが出さない観測 (質量 0)
    n = len(phi)
    m = [[Fraction(0)] * n for _ in range(n)]
    for o in outcomes.values():
        if o.id in members:
            for i in range(n):
                for j in range(n):
                    m[phi[i]][phi[j]] += o.matrix[i][j]
    return m


_LEGAL = {"taken": {"result": "taken", "source_called": True}, "empty": {"result": "empty", "source_called": True},
          "unavailable_called": {"result": "unavailable", "source_called": True}}


def step_kernel(document, kid, cells, *, evidence):
    """行った一歩の節の核 kid を、候補 1 つのモデルから読む (K36 決定 5、K37 決定 6)。段 4 で行える観測の一歩 (outcome の
    行列がどれも対角・所要 0・観測が呼んだ 3 つの組で、宣言のセルがその核の outcome をちょうど覆い、観測値が一致する) で
    なければ不適合。(核の JSON, outcome の id → 行列) を返す。"""
    from fractions import Fraction
    try:
        kernel, = [k for k in document["kernels"] if k["id"] == kid]
        n = len(document["states"])
    except (KeyError, TypeError, ValueError):
        raise _Issue("rejected", "missing_contract", "executed step declaration", evidence=evidence) from None

    def matrix(o):
        return [[Fraction(*x) if isinstance(x, list) else Fraction(x) for x in row] for row in o["matrix"]]
    outcomes = {o["id"]: o for o in kernel["outcomes"]}
    # 合わない最初の性質を名指す (欄 = 核の中のその性質。前の性質が後の読みを守る順に確かめる)
    checks = (("elapsed_ns", lambda: any(o["elapsed_ns"] != 0 for o in outcomes.values())),
              ("evidence", lambda: any(o["evidence"] is None or _json(o["evidence"]["value"]) not in _LEGAL.values()
                                       for o in outcomes.values())),
              ("matrix", lambda: any(matrix(o)[i][j] for o in outcomes.values() for i in range(n) for j in range(n)
                                     if i != j)),
              ("cells", lambda: sorted(x for cell in cells for x in cell["outcomes"]) != sorted(outcomes)
               or any(_json(outcomes[x]["evidence"]["value"]) != _json(cell["observation"]["value"])
                      for cell in cells for x in cell["outcomes"])))
    for name, bad in checks:
        if bad():
            raise _Issue("rejected", "missing_contract", "the step is not a state-preserving observation step",
                         fields=("/kernels/" + kid + "/" + name,), evidence=evidence)
    return kernel, {name: matrix(o) for name, o in outcomes.items()}


def cell_sum(matrices, names, n):
    """セルの outcome の行列の和。"""
    from fractions import Fraction
    m = [[Fraction(0)] * n for _ in range(n)]
    for name in names:
        for i, row in enumerate(matrices[name]):
            for j, x in enumerate(row):
                m[i][j] += x
    return m


def _apply(reader, state, model, binding, reading, desc, pools) -> None:
    """観測 1 つ (結びつき B と読み方) を、一次事実から読んで条件づける (§19-1)。読み方の契約で、区間の札の道と
    取りに行きの道 (K28) に分ける。同じ系列 (前の採用をさかのぼった全部) に 2 つの種類を混ぜない (K28 新しい決定 7)。
    取りに行き・行った一歩は、model が候補の並びの直和のモデルならその並びで読む (K37、`_Pools`)。"""
    from . import _f_count as count
    from .f import CoverageClaim, FInputError, _Fraction, _decode
    c = _c()
    plan = _content(reader, reading, c.OBSERVATION_PLAN_2)
    if plan["model"] != model:
        raise _Issue("rejected", "observation_binding_mismatch", "reading of another model", evidence=(reading,))
    projection, generation = plan["projection"], plan["generation"]
    if projection["contract"] == _enc(c.EXECUTION_STEP_PROJECTION):   # 結びつき B ではなく、一歩の結果のメモを読む
        if state.kind not in (None, "acquisition"):
            raise _Issue("rejected", "missing_contract", "executed steps and interval claims in one series",
                         evidence=(binding, reading))
        state.kind = "acquisition"   # 取りに行きと行った一歩は同じ「届いた / 届かない」の読み方の系列 (K36 決定 5)
        _apply_execution(reader, state, model, binding, reading, plan, desc, pools)
        return
    b = _content(reader, binding, c.SEGMENT_BINDING)
    kind = "acquisition" if projection["contract"] == _enc(c.ACQUISITION_SEQUENCE_PROJECTION) else "claim"
    if state.kind not in (None, kind):
        raise _Issue("rejected", "missing_contract", "acquisition frames and interval claims in one series",
                     evidence=(binding, reading))
    state.kind = kind
    if kind == "acquisition":
        _apply_acquisition(reader, state, model, binding, reading, b, plan, desc, pools)
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


def _apply_acquisition(reader, state, model, binding, reading, b, plan, desc, pools) -> None:
    """取りに行き 1 回 (家の人が acquire で残した Frame の B) を、1 回分の核で今の joint に掛ける (紙 F-b K28 新しい
    決定 1〜10)。宣言を解き (読み方・生成・物語の対応・取りに行き方・K26-d (ク))、K26 の読み口で 0〜i の接頭部を
    読んで確かめ、i 番目のセルの行列の和 Mᵢ を対応で見立ての状態へ並べ替えて、qᵢ = Mᵢ qᵢ₋₁ / zᵢ・質量 × zᵢ。
    K26 の L (初期の状態ごとの尤度) を今の joint に掛けない。同じ MID の同じ意味は据え置き、違う意味は食い違い。
    新しい MID は前の適用の続きの番号だけ (並べ替えない・飛ばさない)。zᵢ = 0 は model_falsified。

    候補の並び (K37 決定 1・6): 読み方は並びを名指し ({pool, observation_model, time_projection})、Mᵢ は各候補の観測モデル
    と物語の対応で作ったかたまりを対角に並べたもの。どの候補の宣言が読めなくても、その候補を名指して止まる。"""
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
            or set(pargs.keys()) not in ({"observation_model", "correspondence", "time_projection"},
                                         {"observation_model", "pool", "time_projection"}) \
            or _json(pargs["time_projection"]) not in ({"contract": _enc(_value_only()), "args": {}},
                                                      {"contract": _enc(c.TIMED_ACQUISITION_PROJECTION), "args": {}}):
        raise _Issue("rejected", "missing_contract", "acquisition projection", fields=("/projection",),
                     evidence=(reading, binding))
    # 時間の射影が読み方の版を決める: value_only は有限の核 (K28)、timed_acquisition_projection は時刻を読む正本 (K38)
    timed = _json(pargs["time_projection"])["contract"] == _enc(c.TIMED_ACQUISITION_PROJECTION)
    pool = None
    if "pool" in pargs:   # 並びの読み方: 名指した並びが、この model を直和のモデルに持つ並びであること
        pool = pools.get(model)
        if pool is None or pargs["pool"] != pool["point"]:
            raise _Issue("rejected", "observation_binding_mismatch", "the reading names another pool",
                         fields=("/projection",), evidence=(reading, pargs["pool"]))
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
    if pool is None:
        point = pargs["correspondence"]
        corr = _correspondence(reader, pargs, model, reading)
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
    reason = None
    if timed:
        try:
            declaration, boot, observations = _fb_read.read_timed(
                records, model=pargs["observation_model"], run=mid.origin, route_epoch=mid.route_epoch,
                through_seq=mid.sample_seq)
        except _fb_read._Unreadable as exc:
            reason = exc.reason
    else:
        read = _fb_read.read(records, model=pargs["observation_model"], run=mid.origin, route_epoch=mid.route_epoch,
                             through_seq=mid.sample_seq)
        reason, observations = read.reason, read.observations
        if read.kind != "unreadable":
            declaration, boot = _fb_read._declaration(records, pargs["observation_model"], [], [])
    if reason is not None:
        raise _Issue("rejected", _UNREADABLE[reason], "the acquisition sequence is unreadable: " + reason,
                     fields=("/args/observations",), evidence=(binding,))
    observation = observations[mid.sample_seq]
    if observation.measurement_id != mid:
        raise _Issue("rejected", "measurement_conflict", "the read sequence differs at this MID", evidence=(binding,))
    # 取りに行き方の照らし (決定 9): 起動の宣言の route の repeat と測る要求の repeat
    routes = [r for r in _content(reader, boot, c.BOOT_DECLARATION)["routes"] if r["slot"] == declaration.route_slot]
    repeat = _json(routes[0]["declaration"]["value"]["repeat"]) if len(routes) == 1 else None
    if repeat != {"contract": _enc(c.ACQUISITION_REPEAT_WHEN_DONE), "args": {}} \
            or _json(k["args"]["repeat"]) != repeat:
        raise _Issue("rejected", "missing_contract", "acquisition repeat or control declaration",
                     fields=("/observation_model",), evidence=(pargs["observation_model"],))
    symbol = _fb_read._SYMBOLS[(observation.result, observation.source_called)]
    if pool is None:
        members = [_initial_member(reader, model, declaration, boot, corr["pairs"], (pargs["observation_model"], point))]
        evidence = [((pargs["observation_model"],), (point,))]
    else:
        members = pool["members"]
        evidence = [((m["model"], pool["point"]),) * 2 for m in members]
    # 並びの口 = 取りに行きの列を読んだ口の宣言の位置 (読み口が route_epoch と照らした、`_fb_read._route`)
    route = declaration.route_slot if pool is None else pool["route"]
    if route != declaration.route_slot:
        raise _Issue("rejected", "observation_binding_mismatch", "the pool reads another route",
                     fields=("/projection",), evidence=(reading, pool["point"]))
    blocks = []
    read_members = []   # 候補ごとに、読めた観測モデルの状態の番号 → 候補のモデルの状態の番号 (phi) を添える
    for member, (ev_model, ev_pairs) in zip(members, evidence):
        control, phi = member_reading(member, route=route, evidence_model=ev_model, evidence_pairs=ev_pairs)
        if (control is None) != timed:   # 時刻を読む候補と有限の核の候補を 1 つの読み方に混ぜない (K38)
            raise _Issue("rejected", "missing_contract", "a candidate reads time differently from the reading",
                         fields=("/observation_model",), evidence=ev_model)
        blocks.append(passive_block(control, phi, symbol, sampling=sampling, evidence=ev_model, size=member["size"]))
        read_members.append({**member, "phi": phi})
    m = _diag(blocks)
    n = len(m)
    # 意味 = 読み方の版と、宣言した観測モデルの値の全部 (状態・制御・核・セルの分け方・制御の表・重み) と、物語の対応の
    # 正準な組と、この回のセル (決定 6: 核・セル・対応・読み方の版のどれかが違えば別の読み方)。欄を選んで足さず、宣言の値を
    # まるごと入れる (この回の行列がたまたま同じでも、宣言が違えば同じ意味にしない。レビュー K28-R1・R1-remains)。
    # 並びでは、各候補の観測モデルと対応の組の列 (K37)
    meaning = {"projection": projection["contract"],
               "observation_model": _json(records[pargs["observation_model"]].body.content.as_json()["value"]),
               "cell": symbol}
    if pool is None:
        meaning["pairs"] = sorted(_json(corr["pairs"]))
    else:
        meaning["candidates"] = [[_json(_enc(x["observation"])), sorted(_json(x["pairs"]))] for x in members]
    key = _dumps(_enc(mid))
    known = state.seen.get(key)
    if known is not None:
        # 照合は正準 JSON の bytes で (digest と同じ同一性。Python の == は true と 1 を同じにする = R14、レビュー K28-R4)
        if _dumps(known) != _dumps(meaning):   # 同じ取りに行きを別の読み方で読み直さない
            raise _Issue("rejected", "measurement_conflict", "the same acquisition read differently", evidence=(binding,))
        return                 # 同じ取りに行きの同じ意味の再提示は据え置き (2 回学ばない)
    if mid.sample_seq != len(state.passive) or state.passive and (
            state.passive[-1]["origin"], state.passive[-1]["route_epoch"]) != (_enc(mid.origin), mid.route_epoch):
        raise _Issue("rejected", "observation_binding_mismatch",
                     "acquisitions must continue the applied prefix in order", evidence=(binding,))
    interval = frame.measurement_interval
    _check_order(state, "acquisition", interval.start_ns, interval.end_ns, m, None, binding)
    _mode(state, "timed" if timed else "finite", binding)
    if timed:
        _ensure_units(state, read_members, [e for e, _p in evidence], binding)
        _timed_acquisition(state, members, mid, interval, observation.cursor, symbol, b["report"], binding)
    else:
        z = sum((m[i][j] * state.joint[j] for i in range(n) for j in range(n)), Fraction(0))
        if z == 0:
            raise _Issue("rejected", "model_falsified",
                         "the model gives this acquisition no mass on the current support", evidence=(binding,))
        state.joint = tuple(sum((m[i][j] * state.joint[j] for j in range(n)), Fraction(0)) / z for i in range(n))
        state.mass *= z
    state.frames.append((_enc(mid), meaning))
    state.passive.append(_enc(mid))
    state.history.append(("acquisition", interval.start_ns, interval.end_ns, m, None))
    state.seen[key] = meaning


def _mode(state, mode, binding) -> None:
    """系列の数の版 (K38): 有限の核の系列と時刻を読む系列を混ぜない。"""
    if state.mode not in (None, mode):
        raise _Issue("rejected", "missing_contract", "finite and timed readings in one series", evidence=(binding,))
    state.mode = mode


def _timed_units(state, members, evidence):
    """時刻を読む正本の units (K38 決定 1・5・K39 決定 5): 並びの (候補, スイッチの列 z, 状態) ごとに、その枝の件数の法則
    (スイッチを当てた後の率) と、並びの事前 (候補の重み × P(z) × 候補の中の事前) と、独立の故障の核。スイッチの族を持つ候補の
    units は枝 z と族 (名前・a・b・部品の辞書) を持つ (p の照会の材料、決定 6)。候補の間の法則の一致は、候補の解決が返す
    計算の種類と測定の条件で確かめる (Python の型で確かめない、決定 8): 全部の候補が同じ計算の種類で、同じ測定核と端点の
    予定で読む (候補ごとに時間の条件づけ方を変えて証拠の質量を比べない、K38 決定 3)。"""
    from . import _fb_time
    first = members[0]
    units = []
    for member, ev in zip(members, evidence):
        if member["computation"] not in ("poisson", "finite_count"):
            raise _Issue("rejected", "missing_contract", "a candidate does not read time", evidence=ev)
        if member["measurement"] != first["measurement"]:
            raise _Issue("rejected", "missing_contract", "candidates read time under different conditioning",
                         fields=("/observation_model/conditioning",), evidence=ev)
        if member["computation"] != first["computation"]:
            raise _Issue("rejected", "missing_contract", "candidates' count laws are of different kinds",
                         fields=("/observation_model/law",), evidence=ev)
        declaration = member["observation"]
        phi, states = member["phi"], member["base"]["states"]
        R = member.get("transitions")
        for b, branch in enumerate(member["branches"] or (None,)):
            group = [member["offset"] + b * len(states) + phi[a] for a in range(len(declaration.law.states))]
            # 遷移のある調子 (K41 決定 3): 同じ候補・枝の状態の unit は 1 つの群 (宣言の状態の順の率・R・unit の番号)
            transitions = None if R is None else {
                "rates": list(branch["rates"] if branch is not None else declaration.law.rates),
                "R": [list(row) for row in R], "units": group}
            for a, name in enumerate(declaration.law.states):
                j = group[a]   # 展開の順: 枝ごとに宣言のモデルの状態の順 (`direct_sum`)
                unit = {"index": j, "candidate": member["id"], "state": states[phi[a]]["id"], "prior": state.joint[j],
                        "law": _fb_time.unit_law(declaration.law, name, None if branch is None else branch["rates"][a],
                                                 None if branch is None else branch["clock"], transitions),
                        "failure": None if declaration.failure is None
                        else declaration.failure.unavailable_probability,
                        "disconnection": None if declaration.disconnection is None
                        else declaration.disconnection.coefficient}
                if member["family"] is not None:
                    unit.update(branch=list(branch["z"]), family=member["family"])
                units.append(unit)
    return sorted(units, key=lambda u: u["index"])


def _ensure_units(state, members, evidence, binding) -> None:
    """時刻を読む正本の units を決める (K38-c ①: 法則・起点・起点の件数の出どころは並びの候補の観測モデル = 起動の宣言の
    1 か所。最初に読んだ観測が取りに行きでも一歩でも同じ所から解く)。既に決まっていれば、同じ解決になることを確かめる。"""
    units = _timed_units(state, members, evidence)
    if state.timed["units"] is None:
        state.timed["units"] = units
    elif state.timed["units"] != units:
        raise _Issue("rejected", "result_mismatch", "the series resolves its count laws differently", evidence=(binding,))


def _timed_step_members(reader, model, pargs, pool, reading, binding):
    """時刻を読む系列の一歩を読む時の候補 (phi つき) と名指し (K38-c ①)。並びなら並びの記録の候補、最初の並びなら一歩の
    読み方が名指す起動の観測モデルと物語の対応 (取りに行きの読み方と同じ記録)。"""
    from . import _fb_read
    c = _c()
    if pool is not None:
        evidence = [(binding, m["model"], pool["point"]) for m in pool["members"]]
        return [{**m, "phi": member_reading(m, route=pool["route"], evidence_model=ev, evidence_pairs=ev)[1]}
                for m, ev in zip(pool["members"], evidence)], evidence
    if set(pargs.keys()) != {"execution_declaration", "observation_model", "correspondence"}:
        raise _Issue("rejected", "missing_contract", "a timed step reading names its observation model",
                     fields=("/projection",), evidence=(reading,))
    corr = _correspondence(reader, pargs, model, reading)
    point = pargs["observation_model"]
    try:
        records = {point: reader.record(point)}
        declaration, boot = _fb_read._declaration(records, point, [], [], c.TIMED_ACQUISITION_MODEL)
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", f"{point} is outside the reader", evidence=(point,)) from None
    except _fb_read._Unreadable as exc:
        raise _Issue("rejected", _UNREADABLE[exc.reason], "the observation model is unreadable: " + exc.reason,
                     evidence=(point,)) from None
    member = _initial_member(reader, model, declaration, boot, corr["pairs"], (point, pargs["correspondence"]))
    ev = (point,)
    phi = member_reading(member, route=declaration.route_slot, evidence_model=ev,
                         evidence_pairs=(pargs["correspondence"],))[1]
    return [{**member, "phi": phi}], [ev]


def _timed_acquisition(state, members, mid, interval, cursor, symbol, point, binding) -> None:
    """取りに行き 1 回を時刻を読む正本に積む (K38 決定 2〜4・8)。区間は宣言した端点の予定の i 番目と一致し、起点より後で、
    前の取りに行きと重ならない時だけ。unavailable は独立の故障の核を宣言した時だけ読む (empty にしない)。積んだ後の
    証拠の質量が形で 0 なら model_falsified (支えの条件から証明した 0、決定 6)。"""
    seq = mid.sample_seq
    for member in members:
        declaration = member["observation"]
        schedule, law = declaration.conditioning, declaration.law
        if schedule.run != mid.origin or seq >= len(schedule.intervals) \
                or schedule.intervals[seq] != (interval.start_ns, interval.end_ns):
            raise _Issue("rejected", "missing_contract", "the acquisition interval is not the declared schedule",
                         fields=("/observation_model/conditioning",), evidence=(binding,))
        # 呼んだ後の故障とつながっていないことは別の核 (K38-c ②)。宣言の無い方は読まない
        if symbol == "unavailable_called" and declaration.failure is None:
            raise _Issue("rejected", "missing_contract", "unavailable needs a declared independent failure law",
                         fields=("/observation_model/failure",), evidence=(binding,))
        if symbol == "unavailable_missing" and declaration.disconnection is None:
            raise _Issue("rejected", "missing_contract", "an unconnected source needs a declared disconnection law",
                         fields=("/observation_model/disconnection",), evidence=(binding,))
    _timed_window(members, _enc(mid.origin), interval.start_ns, binding)
    timed = state.timed
    entries = timed["entries"]
    if any(e["kind"] == "acquisition" and e["after_ns"] > interval.start_ns for e in entries):
        raise _Issue("rejected", "missing_contract", "overlapping acquisitions", evidence=(binding,))
    entries.append({"kind": "acquisition", "before_ns": interval.start_ns, "after_ns": interval.end_ns,
                    "cursor": cursor, "symbol": symbol, "point": point})
    _timed_close(state, interval.end_ns, point, binding)


def _timed_window(members, run, start_ns, binding) -> None:
    """観測 (取りに行き・行った一歩) の時刻が、各候補の件数の法則の時計 (run) の上で起点より後にあること (K38 決定 1、
    K38-c ① の t0 ≤ τ)。取りに行きと一歩が同じこの判定を使う。外れたら読まない (負の経過時間を確率にしない)。"""
    for member in members:
        law = member["observation"].law
        if _enc(law.run) != run:
            raise _Issue("rejected", "missing_contract", "an observation on another clock than the law's",
                         fields=("/observation_model/law/run",), evidence=(binding,))
        if start_ns < law.origin_ns:
            raise _Issue("rejected", "missing_contract", "an observation before the law's origin",
                         fields=("/observation_model/law/origin_ns",), evidence=(binding,))


def _timed_close(state, end_ns, point, binding) -> None:
    from . import _fb_time
    timed = state.timed
    timed["terminal_ns"] = end_ns if timed["terminal_ns"] is None else max(timed["terminal_ns"], end_ns)
    state.observations.append(point)
    if timed["units"] is not None and _fb_time.weights(timed)[1].zero:
        raise _Issue("rejected", "model_falsified", "the law gives these acquisitions no mass", evidence=(binding,))


_OVERLAP_DECLARED = ("state_preserving", "serializable")


def _product(a, b):
    from fractions import Fraction
    n = len(a)
    return [[sum((a[i][k] * b[k][j] for k in range(n)), Fraction(0)) for j in range(n)] for i in range(n)]


def _check_order(state, kind, start, end, matrix, overlap, binding) -> None:
    """順の確かめ (紙 F-b K36 決定 12)。前に適用した別の種類の観測 (取りに行き ↔ 行った一歩) が、この観測の終わりより後に
    始まっていれば、順を飛ばしている。区間が重なる時は、行った一歩の側の世界の宣言 (source_overlap・actor_overlap) が
    両方とも「途中も変えない」か「1 回ずつの前後で表せる」で、実際に読んだセルの行列どうしが両方の順で同じ時だけ進める。"""
    for other, o_start, o_end, o_matrix, o_overlap in state.history:
        if other == kind:
            continue
        if o_start > end:
            raise _Issue("rejected", "observation_binding_mismatch", "an earlier application started after this one",
                         evidence=(binding,))
        if o_end < start:
            continue
        declared = overlap if overlap is not None else o_overlap
        if declared is None or any(x not in _OVERLAP_DECLARED for x in declared) \
                or _product(matrix, o_matrix) != _product(o_matrix, matrix):
            raise _Issue("rejected", "observation_binding_mismatch",
                         "overlapping observations whose order is unknown", evidence=(binding,))


def _apply_execution(reader, state, model, binding, reading, plan, desc, pools) -> None:
    """行った一歩 1 つ (家の人が残した結果のメモ) を、その節の核のうち観測のセルの outcome の和で今の joint に掛ける
    (紙 F-b K36 決定 5)。宣言を解き (読み方・結果のメモ・行う一歩の宣言・モデルの核)、段 4 で行える観測の一歩 (outcome の
    行列がどれも対角・所要 0・観測が呼んだ 3 つの組で、宣言のセルと一致) かを確かめ、セルの行列の和 M で
    q = M q / z・質量 × z。同じ一歩 (同じ E) の同じ意味は据え置き、違う意味は食い違い。z = 0 は model_falsified。

    候補の並び (K37 決定 6): E は元の u と原結果のまま (E.model は並びの来歴のモデルでもよい)。各候補のかたまりは、その
    候補が宣言したその操作の核で読み、対角に並べる。核・セルの outcome が無い候補、読めない宣言 (観測モデル・物語の
    対応) の候補は、名指して止まる (0 の尤度や単位の核で埋めない)。"""
    from fractions import Fraction
    from .f import _dumps
    c = _c()
    pargs = plan["projection"]["args"]
    if not hasattr(pargs, "keys") or set(pargs.keys()) not in (
            {"execution_declaration"}, {"execution_declaration", "observation_model", "correspondence"}) \
            or _json(plan["generation"]) != {"contract": _enc(c.EXECUTE_STEP), "args": {}}:
        raise _Issue("rejected", "missing_contract", "execution projection", fields=("/projection",),
                     evidence=(reading,))
    if binding not in desc["input_points"]:
        raise _Issue("rejected", "observation_binding_mismatch", "the executed step is not an input of the request",
                     evidence=(binding,))
    report = _content(reader, binding, c.EXECUTION_RESULT)
    E = report.get("execution") if hasattr(report, "get") else None
    value = _json(report.get("value")) if hasattr(report, "get") else None
    pool = pools.get(model)
    models = (model, *(pool["lineage"] if pool is not None else ()))
    if report.get("outcome") != "observed" or value not in _LEGAL.values() or not hasattr(E, "get")             or E.get("model") not in models or E.get("reading") != pargs["execution_declaration"]:
        raise _Issue("rejected", "observation_binding_mismatch", "executed step result", evidence=(binding,))
    try:
        record = reader.record(pargs["execution_declaration"])
    except KeyError:
        raise _Issue("rejected", "unresolved_reference", "the execution declaration is outside the reader",
                     evidence=(pargs["execution_declaration"],)) from None
    timed = record.body.contract == c.TIMED_EXECUTION_DECLARATION   # 源の件数の読みつきの宣言 (K38 決定 9)
    if not timed and record.body.contract != c.EXECUTION_DECLARATION:
        raise _Issue("rejected", "reference_kind", "not an execution declaration", evidence=(pargs["execution_declaration"],))
    declared = record.body.content.as_json()
    kid = E["u"]
    if timed:
        from . import _fb_time
        from .f import FInputError, _decode
        from .fb import SourceCountReading
        try:
            source = _decode(declared["value"]["source_readings"][kid], SourceCountReading)
        except (FInputError, KeyError, TypeError, ValueError):
            source = None
        if source is None or not _fb_time.noninterfering(source):
            raise _Issue("rejected", "missing_contract", "the step is not declared to leave the source count alone",
                         fields=("/source_readings",), evidence=(binding, pargs["execution_declaration"]))
        step_members = _timed_step_members(reader, model, pargs, pool, reading, binding)
    try:
        cells = _json(declared["value"]["cells"])[kid]
        overlap = (declared["value"]["source_overlap"], declared["value"]["actor_overlap"])
        entered, finished = report["entered"]["value"]["reading"]["time_ns"], report["finished"]["value"]["reading"]["time_ns"]
    except (KeyError, TypeError, ValueError):
        raise _Issue("rejected", "missing_contract", "executed step declaration", evidence=(binding,)) from None
    if pool is None:
        members = [(_model_document(reader, model, evidence=(model,)), (binding,))]
    else:
        members = []
        for member in pool["members"]:
            ev = (binding, member["model"], pool["point"])
            member_reading(member, route=pool["route"], evidence_model=ev, evidence_pairs=ev)   # 読めない候補は止まる
            members.append((member["document"], ev))
    # 段 4 で行える観測の一歩だけ (状態を変えない・所要 0・観測のセルが宣言と一致、決定 5)
    kernels = [step_kernel(document, kid, cells, evidence=ev) for document, ev in members]
    found = [cell for cell in cells if _json(cell["observation"]["value"]) == value]
    if len(found) != 1:
        raise _Issue("rejected", "missing_contract", "no observation cell reads this result", evidence=(binding,))
    m = _diag([cell_sum(matrices, found[0]["outcomes"], len(document["states"]))
               for (document, _ev), (_kernel, matrices) in zip(members, kernels)])
    if timed:   # 遷移のある調子では一歩の時刻の読みも要る (K41 決定 6)
        fault = step_time_reading(step_members[0], _model_document(reader, model, evidence=(model,)), kid, cells, source)
        if fault is not None:
            raise _Issue("rejected", "missing_contract", f"the step {kid} reading time: {fault}",
                         fields=("/source_readings/" + kid,), evidence=(binding, pargs["execution_declaration"]))
    n = len(m)
    if pool is None:
        meaning = {"projection": _enc(c.EXECUTION_STEP_PROJECTION), "kernel": _json(kernels[0][0]), "cells": cells,
                   "value": value}
    else:
        meaning = {"projection": _enc(c.EXECUTION_STEP_PROJECTION), "kernels": [_json(k) for k, _m in kernels],
                   "cells": cells, "value": value}
    key = _dumps({"execution": _json(E)})
    known = state.seen.get(key)
    if known is not None:
        if _dumps(known) != _dumps(meaning):
            raise _Issue("rejected", "measurement_conflict", "the same step read differently", evidence=(binding,))
        return
    _check_order(state, "execution", entered, finished, m, overlap, binding)
    _mode(state, "timed" if timed else "finite", binding)
    if timed:
        # E_y(s) ⊗ I_N: 状態ごとの因子 (値はモデルの核の 1 か所から) だけを正本に積む (源の件数と取得の測定に交換する、
        # K38 決定 9・K38-c ③)。最初の取りに行きより前の一歩でも、法則は起動の宣言から解く (K38-c ①)
        _ensure_units(state, *step_members, binding)
        _timed_window(step_members[0], _json(report["entered"]["value"]["reading"]["run"]), entered, binding)
        state.timed["entries"].append({"kind": "step", "start_ns": entered, "end_ns": finished,
                                       "factors": [m[i][i] for i in range(n)], "point": binding})
        _timed_close(state, finished, binding, binding)
    else:
        z = sum((m[i][j] * state.joint[j] for i in range(n) for j in range(n)), Fraction(0))
        if z == 0:
            raise _Issue("rejected", "model_falsified",
                         "the model gives this step result no mass on the current support", evidence=(binding,))
        state.joint = tuple(sum((m[i][j] * state.joint[j] for j in range(n)), Fraction(0)) / z for i in range(n))
        state.mass *= z
    state.frames.append(({"execution": _json(E)}, meaning))
    state.history.append(("execution", entered, finished, m, overlap))
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
