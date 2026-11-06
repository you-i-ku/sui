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

__all__ = [
    "fb_registry_v1", "FixedViewValue", "VerificationNeed", "RejectedIssue",
    "InsufficientIssue", "IssuedUpdate", "Rejected", "Insufficient", "UpdateReturn",
    "LaunchResult", "ReportObservation", "ExecutionObservation", "UseObservation", "IntervalObservation",
    "AcquisitionObservation", "TargetEvidence",
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
    )
    declarations = tuple(CapabilityDeclaration(kind=kind, ref=ref, args_contract=args, input_contract=inp,
                                               output_contract=out, dependencies=(), conditions=())
                         for kind, ref, args, inp, out in rows)
    implementations = tuple(CapabilityImplementation(kind=kind, ref=ref, implementation=_ExecutedByEntrance(),
                                                     identity="sui.fb.first_loop/1:" + ref.name + "/" + ref.version)
                            for kind, ref, *_ in rows)
    return make_f_registry(declarations=old.declarations + declarations,
                           implementations=old.implementations + implementations)


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


@_dataclass(frozen=True, slots=True, kw_only=True)
class TargetEvidence:
    """入口 U に渡す同じプロセスの中の独立の証拠 (F-b §2-5-2 の EW・EH・EI・EA、§6-3)。ホストが
    自分で行った操作の時に自分で読んだもので、台帳の自己申告や窓口の印・原報告の写しから作らない。同じプロセスの中の窓口の作り直しまでで、再起動をまたがない (★S5)。"""
    executions: tuple[ExecutionObservation, ...]
    uses: tuple[UseObservation, ...]
    intervals: tuple[IntervalObservation, ...]
    acquisitions: tuple[AcquisitionObservation, ...]


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
    照合は ★ 1 周の後 (この版は evidence を読まない)。"""
    from .f import FInputError
    c = _c()
    try:
        record = reader.record(request)
    except KeyError:
        raise FInputError("unresolved_reference", "the update request is outside the reader", "/request") from None
    if record.body.contract != c.WORK_REQUESTED:
        raise FInputError("shape", "not a work request", "/request")
    desc = record.body.content.as_json().get("desc")
    if not hasattr(desc, "items") or desc.get("purpose") != "belief_update" \
            or desc.get("method") != _enc(c.FINITE_UPDATE_COMPUTE):
        raise FInputError("shape", "not a belief update request", "/request/desc")
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
    `count_exactly_one/1` ほかは ★ 段 3 の広げ (未知の kind をこれへ寄せない)。"""
    c = _c()
    return {(c.NO_ARRIVAL.name, c.NO_ARRIVAL.version): ("no_arrival", 0, 0)}


class _State:
    """一次事実から導いた適用済みの状態 (§19-1 の Claim の部分)。呼出し側の申告ではない。"""

    def __init__(self, joint):
        from fractions import Fraction
        self.joint, self.mass = tuple(joint), Fraction(1)
        self.carrier_by_state, self.law_point, self.law = None, None, None
        self.applied = {}   # ClaimKey (segment, item_slot) → Predicate

    def digest(self, model, origin) -> str:
        """application_digest (§19-1): モデル・origin・法則と、今の連言が表す行の集合 (連言を満たす正準 marks)。
        配送の分割・B の番号・含意される述語の有無で変わらない。"""
        from .f import _digest
        from . import _f_count as count
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
    model = _update_desc(reader, request)["args"]["model"]
    while True:
        desc = _update_desc(reader, point)
        if desc["args"]["model"] != model:
            raise _Issue("rejected", "observation_binding_mismatch", "the adoption series changes its model",
                         fields=("/args/prior",), evidence=(point,))
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
    state = _State(_decode(document["initial"], tuple[_Fraction, ...]))
    for point, desc, adopted in series:
        for use in desc["args"]["observations"]:
            _apply(reader, state, model, use["binding"], use["reading"])
        if adopted is not None:
            saved = _content(reader, adopted["result"], c.UPDATE_RESULT)
            if saved["request"] != point or saved["result"] != _encode_result(state) \
                    or saved["application_digest"] != state.digest(model, desc["reader"]):
                raise _Issue("rejected", "result_mismatch", "a saved result differs from its recomputation",
                             evidence=(adopted["result"],))
    return state


def _apply(reader, state, model, binding, reading) -> None:
    """観測 1 つ (結びつき B と読み方) を、一次事実から述語に読んで条件づける (§19-1)。"""
    from . import _f_count as count
    from .f import CoverageClaim, FInputError, _Fraction, _decode
    c = _c()
    b = _content(reader, binding, c.SEGMENT_BINDING)
    plan = _content(reader, reading, c.OBSERVATION_PLAN_2)
    if plan["model"] != model:
        raise _Issue("rejected", "observation_binding_mismatch", "reading of another model", evidence=(reading,))
    projection, generation = plan["projection"], plan["generation"]
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


_REJECT_CODES = {"schema", "shape", "noncanonical", "rational", "unit", "unknown_version", "normalization",
                 "unresolved_reference", "reference_kind", "observation_binding_mismatch",
                 "measurement_conflict", "clock_unaligned", "missing_contract", "model_falsified"}
