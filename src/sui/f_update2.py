"""F-a の新しい registry と `finite_update/2` の公開の入口 (紙 F-b v0.24 §2-4-8・§2-5-19)。

段 0 の骨組み: 型と署名だけ。本体は段 3。旧 `builtin_f_registry()`・`/1`・旧 artifact の
読み直しは変えない (新しい能力を旧 `_BUILTIN_DECLARATIONS` に足さない)。
"""

from dataclasses import dataclass as _dataclass
from typing import Literal as _Literal, TypeAlias as _TypeAlias

from .f import FReader, FRegistry, ImmutableJSON, MeasurementInterval, Point, ProofRef, _FactoryHandle
from .rate import RateBudget

__all__ = [
    "fb_registry_v1", "FixedViewValue", "Target", "CallBinding", "CheckedProof",
    "UpdateCertificateDescription", "VerificationNeed", "RejectedIssue",
    "InsufficientIssue", "Verified", "Rejected", "Insufficient",
    "VerificationResponse", "VerifiedFiniteUpdate", "TargetVerificationReturn",
    "LaunchResult", "ReportObservation", "ExecutionObservation", "UseObservation", "IntervalObservation",
    "AcquisitionObservation", "TargetEvidence",
    "finite_update_target_check",
]


def fb_registry_v1() -> FRegistry:
    """旧の宣言の集合と実装の識別をそのまま含み、`finite_update/2` ほか §2-5-19 の能力を
    足した別の不変の registry (§2-4-8 の 2)。registry_key は全部の宣言と実装の識別から求まる。"""
    raise NotImplementedError("段 3")


@_dataclass(frozen=True, slots=True, kw_only=True)
class FixedViewValue:
    """保存できる固定像の値 (F-b §2-5-1 の FixedView と同じ欄)。"""
    boundary: frozenset[Point]
    reader_view_key: str
    registry_key: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class Target:
    """一つの認証物が対象にする Q/R/全 P/Cq (§19-9)。"""
    request: Point
    result: Point
    proofs: frozenset[Point]
    completion: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class CallBinding:
    """保存済みの Wv 要求・解決した宣言と全引数・対象・実際の環境・budget を結ぶ。
    将来の自分の返答・V・認証物を入力に含めない。"""
    work_request: Point
    budget: RateBudget
    call_digest: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class CheckedProof:
    proof: Point
    checker: ProofRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class UpdateCertificateDescription:
    """`sui.f.target_update_certificate/1` の保存できる説明値。生きた発行物の代わりにしない。
    replay_mode は検査が不在に依存したかから導き、呼出し側が選ぶ欄ではない。"""
    call: CallBinding
    target: Target
    model: Point
    origin: Point
    numerical_view: FixedViewValue
    check_view: FixedViewValue
    registry_key: str
    verifier: ProofRef
    checked_proofs: tuple[CheckedProof, ...]
    target_digest: str
    request_input_digest: str
    closure_digest: str
    result_digest: str
    application_digest: str
    acquisition_digest: str
    replay_mode: _Literal["positive_dependencies", "exact_environment"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class VerificationNeed:
    """不足の対象。kind ごとに value の欄が決まる (§19-9):
    capability = {contract, purpose: reading/generation/clock/replay/proof/authentication}、
    evidence = {target: Point, purpose: generation/clock/support/acquisition/adoption_chain, contract: ?ContractRef}、
    budget = {phase: reader/authentication/projection/replay/proof}。存在しない Point を捏造しない。"""
    kind: _Literal["capability", "evidence", "budget"]
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class RejectedIssue:
    code: _Literal[
        "schema", "shape", "noncanonical", "rational", "unit", "unknown_version",
        "normalization", "unresolved_reference", "reference_kind", "proof_mismatch",
        "observation_binding_mismatch", "measurement_conflict", "clock_unaligned",
        "missing_contract", "model_falsified", "outside_evaluation_type", "result_mismatch",
    ]
    fields: tuple[str, ...]
    evidence: frozenset[Point]
    message: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class InsufficientIssue:
    code: _Literal[
        "algorithm_unavailable", "certificate_incomplete", "budget_exhausted",
        "prerequisite_unavailable", "clock_unaligned",
    ]
    fields: tuple[str, ...]
    missing: tuple[VerificationNeed, ...]
    evidence: frozenset[Point]
    message: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class Verified:
    value: UpdateCertificateDescription


@_dataclass(frozen=True, slots=True, kw_only=True)
class Rejected:
    call: CallBinding
    issues: tuple[RejectedIssue, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class Insufficient:
    call: CallBinding
    issues: tuple[InsufficientIssue, ...]


VerificationResponse: _TypeAlias = Verified | Rejected | Insufficient
"""確定返答の三枝 (§19-9)。仕事の実行の Failure/Unknown は外側の層。issues は空にしない。"""


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class VerifiedFiniteUpdate(_FactoryHandle):
    """factory が実際の検査の成功から発行した生きた認証物。保存できる説明値から復元しない。
    直接の構築は TypeError (F-a の factory 専用ハンドルと同じ、§3-10-13-1)。段 3 で発行の口だけから作る。"""
    description: UpdateCertificateDescription


@_dataclass(frozen=True, slots=True, kw_only=True)
class TargetVerificationReturn:
    """issued は verified の枝でだけ非 None。"""
    response: VerificationResponse
    issued: VerifiedFiniteUpdate | None


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
    認証は対象の原報告の Point がここにあるかで、その仕事から来たかを照合する)。要求の保存・
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
    取得と Wr の使用の前後は UseObservation.used_ns と比べる (G の保存の時刻と比べない)。"""
    origin: Point
    contents: frozenset[Point]
    acquired_ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class TargetEvidence:
    """認証に渡す同じプロセスの中の独立の証拠 (F-b §2-5-2 の EW・EH・EI・EA)。台帳の
    自己申告や窓口の印から作らない。同じプロセスの中の窓口の作り直しまでで、再起動をまたがない (★S5)。"""
    executions: tuple[ExecutionObservation, ...]
    uses: tuple[UseObservation, ...]
    intervals: tuple[IntervalObservation, ...]
    acquisitions: tuple[AcquisitionObservation, ...]


def finite_update_target_check(
    work_request: Point, *, reader: FReader, registry: FRegistry,
    evidence: TargetEvidence, budget: RateBudget,
) -> TargetVerificationReturn:
    """`sui.f.finite_update_target_check/1` (§19-9)。保存済みの Wv 要求の Desc/VerificationArgs
    から対象・origin・Xnum・check_view・checker・acquisitions を解決し、一つの Q/R/全 P/Cq を
    認証する。入口で対象を構成できない不正や物理的な欠落は例外 (三枝に無理に写さない)。"""
    raise NotImplementedError("段 3")

