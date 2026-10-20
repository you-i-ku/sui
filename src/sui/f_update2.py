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

from .f import FReader, FRegistry, ImmutableJSON, MeasurementInterval, Point, _FactoryHandle
from .rate import RateBudget

__all__ = [
    "fb_registry_v1", "FixedViewValue", "VerificationNeed", "RejectedIssue",
    "InsufficientIssue", "IssuedUpdate", "Rejected", "Insufficient", "UpdateReturn",
    "LaunchResult", "ReportObservation", "ExecutionObservation", "UseObservation", "IntervalObservation",
    "AcquisitionObservation", "TargetEvidence",
    "compute_finite_update",
]


def fb_registry_v1() -> FRegistry:
    """旧の宣言の集合と実装の識別をそのまま含み、`finite_update/2` と入口 U ほか §2-5-19・§6-3 の能力を
    足した別の不変の registry (§2-4-8 の 2)。registry_key は全部の宣言と実装の識別から求まる。"""
    raise NotImplementedError("段 3")


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
    evidence: TargetEvidence, budget: RateBudget,
) -> UpdateReturn:
    """入口 U `sui.f.finite_update_compute/1` (紙 v0.25 §6-3)。保存済みの更新要求 Q* から読み手・
    モデル・固定根・前の採用・観測の並びを解決し、保存した一次事実と境目の実観測だけを読んで、
    宣言の解決・生成の対応・入力の実取得と実使用・固定根・適用の履歴を確かめ、§2-5-19 の数学で
    計算して発行する。F-b から完成した joint を受け取る引数は無い。入口で要求を構成できない不正や
    物理的な欠落は例外 (三枝に無理に写さない)。"""
    raise NotImplementedError("段 3")
