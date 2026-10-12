"""関所 F v0.11 §3-10-12〜14 の公開値型・例外・F-a の数学。

DTO は frozen コンストラクターで欄を受ける。factory ハンドルは手組み不可。
F-a で検査する: 型・単位・版・参照・保証・Mapping の再帰的凍結と発行元。
構造復号は認証しない。手作り・復号だけの同名欄を評価・保存の認証にしない。
F-a は不変の認証世界から評価する。F-b の実ホスト接続は F-b で作る (写し: Desktop/sui_fb_material_20261012)。
匿名要素の Python 名は §3-10-13-1・補で採用済み。

§3-10-12-9 の例外 / reason 対応:
FInputError: schema (JSON不能/重複キー), shape (欄/型/bool整数), noncanonical,
rational (既約R/正の分母), unit (負の所要/単位), normalization (質量),
unknown_version, unresolved_reference, measurement_conflict。
FSpecificationMissing: missing_contract (構造はあるが意味なし)。
FModelFalsified: zero_evidence。FOutsideEvaluationType: 対応する型外の理由。
FNumericalRange: NumericalRange。
FIncomplete: budget_exhausted, selection_boundary, certificate_incomplete,
cost_certificate, c1_closure_unproved。
FReplayUnavailable: missing_input / method_unavailable。
FReplayMismatch: result_mismatch。field は JSON Pointer (根は空文字)、
Python 引数の拒否では引数名を先頭に置く。fields は重複なしの辞書順を F-a で検査。
低水準は例外、高水準 evaluate_f は意味不足・反証を rejected、
能力/予算/境界を incomplete、数値範囲を failed にする。形の不正と予期しない
Python/I/O 例外は数学の NoDecision に変換しない。
"""

from __future__ import annotations

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from typing import Literal as _Literal, TypeAlias as _TypeAlias, Protocol as _Protocol

from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch
from .contracts import ContractRef as _ContractRef
from .f_model import FModel
from .ids import Ref as _Ref
from .records import Record as _Record
from .inference import NumericalRange as _NumericalRange
from .lookahead import OutsideEvaluationType as _OutsideEvaluationType
from .quantity import IntegrationIncomplete as _IntegrationIncomplete
from .rate import RateBudget, RationalInterval
from .rate_model import RateModel


# §3-10-12-2 で採用した不変 JSON 表現。生の有限 float と保証Rは別物。
ImmutableJSON: _TypeAlias = (
    str | int | float | bool | None | tuple["ImmutableJSON", ...]
    | _Mapping[str, "ImmutableJSON"]
)
NoDecisionReason: _TypeAlias = _Literal[
    "NoAdmissibleCandidate", "NumericalRange", "budget_exhausted",
    "selection_boundary", "algorithm_unavailable", "proof_incomplete",
    "runtime_unverified", "candidate_measure_missing", "normalization_unproved",
    "OutsideEvaluationType", "certificate_incomplete", "information_divergent",
    "undefined_infinite_difference", "clock_unaligned", "prerequisite_unavailable",
    "cost_certificate", "missing_contract", "model_falsified", "c1_closure_unproved",
]
ComputationState: _TypeAlias = _Literal[
    "queued", "running", "paused_runtime", "suspended", "selected",
    "superseded", "stopped", "failed",
]


class _JSONDTO:
    """Freeze JSON-bearing DTO fields at construction, including nested arrays."""
    __slots__ = ()

    def __post_init__(self):
        from dataclasses import fields
        from types import MappingProxyType
        def freeze(value):
            if isinstance(value, _Mapping):
                return MappingProxyType({k: freeze(v) for k, v in value.items()})
            if isinstance(value, (tuple, list)):
                return tuple(freeze(v) for v in value)
            return value
        for field in fields(self):
            if field.name in ("args", "value", "computation", "enclosures", "state_payload"):
                object.__setattr__(self, field.name, freeze(getattr(self, field.name)))


class _FErrorMixin:
    def __init__(self, reason: str, detail: str = "", field: str | None = None) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail, self.field = reason, detail, field


class FInputError(_FErrorMixin, ValueError):
    """不正入力。schema・shape・normalization・衝突等をreasonで区別。"""


class FSpecificationMissing(_FErrorMixin, ValueError):
    """宣言の意味・必要な契約が不足。認証能力の不足とは区別する。"""


class FIncomplete(_FErrorMixin, _IntegrationIncomplete):
    """低水準の未完了。計算失敗だけから発散を主張しない。"""


class FOutsideEvaluationType(_FErrorMixin, _OutsideEvaluationType):
    """宣言した評価型の外。高水準evaluate_fはNoDecisionにする。"""


class FModelFalsified(_FErrorMixin, _ModelFalsified):
    """証拠質量0など証明されたモデルの反証。"""


class FNumericalRange(_FErrorMixin, _NumericalRange):
    """計算の数値範囲。数学の無限大と混同しない。"""


class FReplayUnavailable(_FErrorMixin, LookupError):
    """原記録・版・根拠を読めず保存済み証明を再現できない。"""


class FReplayMismatch(_RebuildMismatch):
    """復元値・参照・証明の不一致。署名は §3-10-13-1 で採用済み。
    fields は正しい JSON Pointer の重複なし辞書順 tuple として検査する。
    field が None でなければ fields に含める。不正な fields は FInputError(shape)。"""
    def __init__(self, reason: str, detail: str = "", field: str | None = None, *,
                 fields: tuple[str, ...] = ()) -> None:
        if not isinstance(fields, tuple):
            raise FInputError("shape", "fields は tuple", "fields")
        for pointer in fields + (() if field is None else (field,)):
            if (not isinstance(pointer, str)
                    or (pointer != "" and not pointer.startswith("/"))
                    or any(not part or part[0] not in "01"
                           for part in pointer.split("~")[1:])):
                raise FInputError("shape", "不正な JSON Pointer", "fields" if pointer in fields else "field")
        if any(left >= right for left, right in zip(fields, fields[1:])):
            raise FInputError("shape", "fields は重複なし辞書順", "fields")
        if field is not None and field not in fields:
            fields = tuple(sorted((*fields, field)))
        # 今の約束 A-21: a mismatch names a concrete column; with only fields
        # given, the first of them is the primary pointer.
        if field is None and fields:
            field = fields[0]
        super().__init__(fields=fields)
        self.args = (f"{reason}: {detail}" if detail else reason,)
        self.reason, self.detail, self.field = reason, detail, field


class _FactoryHandle:
    """factory 専用。構造復号を発行元・proof・資源の認証として扱わない。"""
    __slots__ = ("_authority",)

    def __init__(self) -> None:
        """§3-10-13-1 に従い直接構築を TypeError で拒否する。公開 ctor は持たない。"""
        raise TypeError("factory が返すハンドルです")


@_dataclass(frozen=True, slots=True, kw_only=True)
class Unavailable:
    """未取得値。F-a で検査する: 理由と根拠。0・False・nullとは別。"""
    reason: str
    basis: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExactReal:
    """F-a で検査する: op 別の厳密式、log の正の引数、非零分母。
    現状の全引数を採用。無関係な引数は None のみで JSON に出さない。
    rational は Fraction を既約Rへ符号化。0 log 0 は式を作らず寄与0。"""
    op: _Literal["rational", "log", "exp", "add", "mul", "neg", "div"]
    value: _Fraction | None = None
    arg: ExactReal | None = None
    args: tuple[ExactReal, ...] | None = None
    numerator: ExactReal | None = None
    denominator: ExactReal | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ActionFamilyRef:
    """操作族の版。F-a で検査する: 名前・版と認証範囲。動機enumにしない。"""
    name: str
    version: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class PredicateRef(_JSONDTO):
    """F-a で検査する: 状態型・依存・検査法・版・認証範囲と凍結したargs。"""
    name: str
    version: str
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class KernelRef(_JSONDTO):
    """F-a で検査する: 意味の版 finite_kernel/1 と args.id の宣言内 ID。
    name を kernel ID にせず、モデルは外側の FProblem から解決する。
    """
    name: str
    version: str
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRef(_JSONDTO):
    """F-a で検査する: 意味の版 finite_policy/1 と args.id、K 可測性。
    name を policy ID にせず、実行中は受信ごとに別方針へ替えない。
    """
    name: str
    version: str
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class ProofRef(_JSONDTO):
    """F-a で検査する: 証明器の版・引数・根拠。自己申告だけでは認証しない。"""
    name: str
    version: str
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class QuantityRef:
    """F-a で検査する: 照会の宣言を識別する key と対象・根。数値を key に埋めない。"""
    key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class DependencyRef:
    """F-a で検査する: 依存先の key と出どころ basis の解決可能性。"""
    key: str
    basis: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ActionSpec(_JSONDTO):
    """操作の宣言。F-a で検査する: 全参照、開始・方針・ψ・終わり方、
    予測と実行の適合、族の正準化か検査可能な別名証明によるsemantic_key。
    表示名や発見入口をsemantic_keyへ含めず、異なる機会は区別する。
    finite_option/1.args は opportunity と path_action。path_action=null は
    内部処理と宣言した場合だけ。開始は実行前、終了は一回以上の実遷移後。
    finite_option_proof/1.args は operation。simulated_execution/1 を実機に流用しない。
    """
    id: str
    family: ActionFamilyRef
    args: ImmutableJSON
    start: PredicateRef
    policy: PolicyRef
    termination: PredicateRef
    termination_kind: _Literal["certain", "may_never"]
    prediction: KernelRef
    execution: _ContractRef
    proof: ProofRef
    semantic_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class PredicateResult:
    """F-a で検査する: 三値と根拠・不足・仕事の対応。UnknownをFalseにしない。"""
    value: _Literal["true", "false", "unknown"]
    basis: tuple[_Ref, ...]
    missing: tuple[DependencyRef, ...]
    work: PredicateWork | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class PredicateWork:
    """F-a で検査する: predicate/snapshot/missing の digest による安定した work_id。
    同じ Unknown の配送で重い仕事を増やさず、検査は窓口の外で行う。"""
    work_id: str
    predicate: PredicateRef
    snapshot: PredicateSnapshot
    missing: tuple[DependencyRef, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceEmission(_JSONDTO):
    """F-a で検査する: 宣言slot・生成契約・値。予測IDを台帳へ書かない。"""
    slot: str
    kind: _Literal["measurement", "coverage", "gap"]
    value: ImmutableJSON
    measurement_contract: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class AvailabilityChange(_JSONDTO):
    """F-a で検査する: 既存slotのreveal。計算だけで新測定を作らない。"""
    reveal: tuple[str, ...]
    computation: ImmutableJSON | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteOutcome:
    """F-a で検査する: 非負整数 ns、arrival 行/departure 列の共同行列、
    evidence/availability/completion と宣言 slot。予測を原記録にしない。"""
    id: str
    elapsed_ns: int
    evidence: EvidenceEmission | None
    available: AvailabilityChange
    completion: bool
    matrix: tuple[tuple[_Fraction, ...], ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteKernel:
    """F-a で検査する: 軸・静的対象・全outcomeの列質量和1。未知法則は共有。"""
    id: str
    outcomes: tuple[FiniteOutcome, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteNode:
    """F-a で検査する: kernel の参照と全 outcome の next 閉包。"""
    id: str
    kind: _Literal["execute"]
    kernel: str
    next: _Mapping[str, str]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ChooseNode:
    """F-a で検査する: 操作参照、rule と K 可測性。
    next は選んだ ActionSpec の方針 ψ が終了した後の戻り先。
    may_never が終了しなければ戻らず、next を重ねて実行しない。"""
    id: str
    kind: _Literal["choose"]
    operations: tuple[str, ...]
    rule: _ContractRef
    next: _Mapping[str, str]


@_dataclass(frozen=True, slots=True, kw_only=True)
class EndNode:
    """F-a で検査する: 路全体を同じ好みで一回評価する終端。"""
    id: str
    kind: _Literal["end"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FinitePolicy:
    """F-a で検査する: entry・節の一意性・参照閉包・K可測性・有限展開。
    0時間を一律禁止せず、0時間無限循環の認証は未完了にする。
    """
    id: str
    entry: str
    nodes: tuple[ExecuteNode | ChooseNode | EndNode, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateMeasureRef(_JSONDTO):
    """F-a で検査する: 測度の版と引数。最初の成功範囲はcounting/1。"""
    name: str
    version: str
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateSet:
    """F-a で検査する: 順序・別名・測度・生成根拠・draw。未認証を消さない。"""
    candidates: tuple[ActionSpec, ...]
    aliases: _Mapping[str, str]
    measure: CandidateMeasureRef | None
    generator: _ContractRef
    basis: tuple[_Ref, ...]
    draws: tuple[DrawRecord, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationScope:
    """F-a で検査する: 範囲版1、finite_horizonの非負Hと本人の紙のsource。
    unbounded_total/one_stepはH_ns=None。source=Noneは白紙か明示互換だけ。
    """
    name: _Literal["unbounded_total", "one_step", "finite_horizon"]
    version: _Literal["1"]
    H_ns: int | None
    source: _Ref | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateExclusion:
    """F-a で検査する: 開始不能/許容不能の検査可能な証明。未認証候補を除かない。"""
    candidate: str
    reason: str
    proof: ProofRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class NormalizationCertificate:
    """F-a で検査する: 同じ問題の測度・許容候補・除外証明と0<Z<∞の保証。"""
    problem_key: str
    measure: CandidateMeasureRef
    admissible: tuple[str, ...]
    excluded: tuple[CandidateExclusion, ...]
    Z: RationalInterval
    proof: ProofRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementId:
    """F-a で検査する: origin・経路世代・連番・component。本文一致と別物。"""
    origin: _Ref
    route_epoch: str
    sample_seq: int
    component: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceLink:
    """F-a で検査する: 原記録・生成元・派生元・契約。同じ機会と独立機会を区別。"""
    measurement: MeasurementId
    records: tuple[_Ref, ...]
    generated_by: tuple[_Ref, ...]
    derived_from: tuple[MeasurementId, ...]
    contract: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceHistory:
    """build_histories が原記録から構築する E の DTO。
    F-a で検査する: 全配送の出どころ・生成関係。手組みの内容は未検査。"""
    key: str
    links: tuple[EvidenceLink, ...]
    coverage: tuple[CoverageClaim, ...]
    gaps: tuple[Gap, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeHistory:
    """build_histories が構築する K の DTO。F-a で検査する: E と証明の解決。
    available と incorporated を分け、未計算を反映済みとせず手組みを信用しない。"""
    key: str
    available: tuple[MeasurementId, ...]
    incorporated: tuple[MeasurementId, ...]
    belief: _Ref | None
    kernel_basis: tuple[_Ref, ...]
    normalization_proofs: tuple[_Ref, ...]
    query_proofs: tuple[_Ref, ...]
    pending: tuple[DependencyRef, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FContext:
    """F-a で検査する: 同 run の整数 ns・時計契約・検査時機。
    fact_ancestors は CID -> その時点で読める FactRecord の Ref 文字列集合。
    レコードIDを CID と取り違えず、別 run を自動整列しない。"""
    run: _Ref
    now_ns: int
    observed_ns: int
    clock_contract: _ContractRef
    check_events: tuple[ImmutableJSON, ...]
    fact_ancestors: _Mapping[str, frozenset[str]]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FRoot(_FactoryHandle):
    """freeze_root / restore_f_root が返す検査済みハンドル。
    F-a で検査する: 問題・資源・continuation・selection draw の全欄の結合。
    一度の発火は同根/uを再使用し、別発火は帳面が別 ordinal を受付する。
    手組み・構造復号だけを認証せず、後着事実を根に取り込まない。"""
    contract: _ContractRef
    problem_key: str
    root_key: str
    world_key: str
    world_manifest: "FWorldManifest3"
    model_ref: str
    parents: frozenset[str]
    facts: tuple[_Ref, ...]
    E: EvidenceHistory
    K: KnowledgeHistory
    context: FContext
    preferences: tuple[_Ref, ...]
    style: _Ref | None
    scope: EvaluationScope
    gamma: _Fraction
    candidates: CandidateSet
    continuation: FContinuation
    measurement_contracts: tuple[_ContractRef, ...]
    execution_contracts: tuple[_ContractRef, ...]
    method: _ContractRef
    selection_draw: DrawRecord
    # 今の約束 E-05 root/3: the draw's Point and record digest (null for root/2).
    draw_point: str | None
    draw_record_digest: str | None

    @property
    def world(self) -> FCertifiedWorld:
        from ._f_handles import attached_world
        return attached_world(self)

@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawRecord(_JSONDTO):
    """F-a で検査する: request と purpose/context_key/ordinal の一致、生成器・stream・値域。
    request.law は分布、generator は供給実装で別契約。
    id は正準 JSON {domain:"sui.f.draw/1",generator,stream_id,purpose,context_key,ordinal}
    の SHA-256 に sha256: を付ける。value を ID に含めず同 ID の値衝突を検出する。"""
    id: str
    purpose: _Literal["candidate_generation", "selection", "reservation", "algorithm"]
    generator: _ContractRef
    stream_id: str
    request: DrawRequest
    context_key: str
    ordinal: int
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantity:
    """F-a で検査する: 構造的0・有限式と保証・証明済み∞・未認証の区別。"""
    status: _Literal["finite", "positive_infinity", "uncertified"]
    exact: ExactReal | None
    bounds: RationalInterval | None
    proof: ProofRef | None
    reason: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityDefinition:
    """Kind-specific DTO; wire encoding includes exactly the selected variant."""
    kind: _Literal["evaluation", "rational_constant"]
    root_key: str | None = None
    field: _Literal["expected_cost", "already_received", "additional", "total_information", "G", "J", "q_star", "Z"] | None = None
    candidate: str | None = None
    value: _Fraction | None = None
    unit: _Literal["nat", "dimensionless"] | None = None
    provenance: tuple[_Ref, ...] | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class TailCertificate:
    """F-a で検査する: prefix 表の digest、I_n、情報の残り、独立の費用保証。
    zero は情報と費用の残りが厳密0。residual_mass が正でも永久未着を区別できる。
    analytic は厳密式を保持、bounded は非零を捨てず、未証明は unproved。"""
    problem_key: str
    candidate: str
    prefix: TailPrefix
    information_prefix: FQuantity
    information_remaining: FQuantity
    cost_total: FQuantity
    residual_mass: FQuantity
    closure: _Literal["zero", "analytic", "bounded", "unproved"]
    proof: ProofRef | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class InformationParts:
    """F-a で検査する: total=already_received+additional。O0を一度数える。"""
    already_received: FQuantity
    additional: FQuantity
    total_information: FQuantity


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCertificate:
    """F-a で検査する: 根・方法・arithmetic・予算・trace・保証・残りの一致。
    toleranceは診断幅であり情報の尾を捨てるεでも誤選択確率でもない。
    """
    problem_key: str
    root_key: str
    method: _ContractRef
    arithmetic: _ContractRef
    budget: RateBudget
    trace: tuple[ContractValue, ...]
    enclosures: ImmutableJSON
    residuals: tuple[ImmutableJSON, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FEvaluation:
    """F-a で検査する: 候補順と各値の軸、Z、尾と累積候補数+1。
    正規化を認証した時だけ末尾1。中点や表示値で選ばない。
    """
    root: FRoot
    candidates: tuple[str, ...]
    expected_cost: tuple[FQuantity, ...]
    information: tuple[InformationParts, ...]
    G: tuple[FQuantity, ...]
    J: tuple[FQuantity, ...]
    q_star: tuple[FQuantity, ...]
    cumulative: tuple[RationalInterval, ...]
    normalization: NormalizationCertificate | None
    tails: tuple[TailCertificate, ...]
    certificate: FCertificate


@_dataclass(frozen=True, slots=True, kw_only=True)
class Selected:
    """F-a で検査する: 根・評価・index・操作・uと保証。静けさも本物の選択。
    previous.upper<=u<current.lowerまたは認証した境界等値を要する。
    """
    root: FRoot
    evaluation: FEvaluation
    index: int
    choice: ActionSpec
    u: _Fraction
    previous: RationalInterval
    current: RationalInterval
    certificate: FCertificate

    @property
    def chosen(self) -> ActionSpec:
        """Readable operation alias; canonical wire field remains choice."""
        return self.choice


@_dataclass(frozen=True, slots=True, kw_only=True)
class NoDecision:
    """F-a で検査する: 未完了・拒否・故障の理由と証明・進捗・再開の対応。
    Suspend・静けさ・取消の選択ではない。不正入力や改ざんをここへ薄めない。
    """
    attempt_id: str | None
    root_key: str | None
    outcome: _Literal["incomplete", "rejected", "failed"]
    reason: NoDecisionReason
    detail: str
    field: str | None
    proof: ProofRef | None
    progress: FEvaluation | None
    resume: ResumePoint | None


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FiniteBelief(_FactoryHandle):
    """initial_finite_belief / apply_f_observation が返すハンドル。
    F-a で検査する: 宣言順の共同信念・質量・適用済み遷移と入力 digest。
    手作り・構造復号を検査済みとせず、同じ遷移は一回だけ反映する。"""
    model_ref: str
    evidence_key: str
    joint: tuple[_Fraction, ...]
    evidence_mass: _Fraction
    applied: tuple[AppliedTransition, ...]

@_dataclass(frozen=True, slots=True, kw_only=True)
class PredicateSnapshot:
    """F-a で検査する: モデル参照、取得済み E/K/数量/依存/位置と同じ資源束。
    model_ref=None はモデルを読まない述語だけ。policy_end はモデル内の節 kind を読む。
    quantities の JSON は正準 key bytes 順の key/value 配列。取得中に重い推論なし。"""
    model_ref: str | None
    E: EvidenceHistory
    K: KnowledgeHistory
    quantities: _Mapping[QuantityRef, FQuantity]
    dependencies: tuple[DependencyRef, ...]
    policy_position: PredicatePosition | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationSpec:
    """F-a で検査する: 条件付ける全入力・計算法の版・用途別 draw と出力契約。"""
    method: _ContractRef
    input_measurements: tuple[MeasurementId, ...]
    input_records: tuple[_Ref, ...]
    algorithm_draws: tuple[DrawRecord, ...]
    output_contract: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class FScope:
    """F-a で検査する: 認証・未完了・意味不足・型の外・実行未認証の区別。
    conditions は ContractValue の列。登録名だけを証明にしない。"""
    status: _Literal["certified", "incomplete", "missing_spec", "outside_evaluation", "runtime_unverified"]
    method: _ContractRef | None
    reason: str | None
    conditions: tuple[ContractValue, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPathRow:
    """F-a で検査する: 候補軸、路と対象の共同質量、実際に見える E/K の履歴。
    joint_target の和は probability。隠れた outcome を別観測として分けない。"""
    candidate: str
    probability: ExactReal
    joint_target: tuple[ExactReal, ...]
    E_trace: tuple[EvidenceHistory, ...]
    K_trace: tuple[KnowledgeHistory, ...]
    actions: tuple[ActionSpec, ...]
    terminal: FPathTerminal

@_dataclass(frozen=True, slots=True, kw_only=True)
class FPathTable:
    """F-a で検査する: 根、候補別の終端・未展開質量の和1と共同状態の保持。
    complete は frontier が空、residual が候補ごとに厳密0。prefix を全路と呼ばない。
    steps は展開の深さであり評価範囲 H ではない。"""
    problem_key: str
    root_key: str
    kind: _Literal["complete", "prefix"]
    steps: int | None
    candidates: tuple[str, ...]
    rows: tuple[FPathRow, ...]
    frontier: tuple[FFrontierRow, ...]
    residual: tuple[FPathResidual, ...]
    nodes: tuple[FNodeValue, ...]

@_dataclass(frozen=True, slots=True, kw_only=True)
class LegacyComparison:
    """F-a で検査する: 対象・候補対応・所要・測定時刻・範囲・好み・O0 の橋。
    assumptions は ContractValue の列。旧 float を新しい保証値へ格上げしない。"""
    legacy_contract: _ContractRef
    assumptions: tuple[ContractValue, ...]
    old_information: tuple[float, ...]
    reconstructed_information: tuple[FQuantity, ...]
    old_J: tuple[float, ...]
    new_J: tuple[FQuantity, ...]
    old_probabilities: tuple[float, ...]
    new_probabilities: tuple[FQuantity, ...]
    old_choice: str
    new_choice: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class ResumePoint:
    """F-a で検査する: 同根・方法・arithmetic・trace・状態 digest と前証明。
    外形は採用済み。stage の版・payload の内部 schema は F-c 前に決める。"""
    root_key: str
    method: _ContractRef
    arithmetic: _ContractRef
    stage: str
    trace_prefix: tuple[ImmutableJSON, ...]
    state_digest: str
    state_payload: ImmutableJSON
    previous_certificate: FCertificate | None


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class C1CountFrame(_FactoryHandle):
    """read_c1_frames が原記録から返すハンドル。
    F-a で検査する: run・原点・実窓・因果・被覆・実計数0/1/2と p 測定。
    同名欄を手で埋めても検査済みにならず、窓途中の無配送を count=0 にしない。"""
    measurement_id: MeasurementId
    source_record: _Ref
    delivery_records: tuple[_Ref, ...]
    run: _Ref
    origin_ns: int
    start_ns: int
    end_ns: int
    count: int
    probe: C1Probe | None
    generated_by: tuple[_Ref, ...]

@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class C1Summary(_FactoryHandle):
    """initial_c1_summary / update_c1_summary が返すハンドル。
    F-a で検査する: model.9 の限定閉包、実窓と p の帳面。T_s は秒の Fraction。
    probe_counts は宣言ラベル順の二整数。四量だけを全履歴とせず手作りを信用しない。"""
    model_ref: str
    run: _Ref
    origin_ns: int
    measurement_ids: tuple[MeasurementId, ...]
    source_records: tuple[_Ref, ...]
    end_ns: int
    N: int
    T_s: _Fraction
    A0: _Fraction
    A1: _Fraction
    probe_measurements: tuple[MeasurementId, ...]
    probe_counts: _Mapping[str, tuple[int, int]]

@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockReading:
    """F-a で検査する: RUN Ref の時計領域と整数 ns。既存 Instant へ暗黙変換しない。"""
    run: _Ref
    time_ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementInterval:
    """F-a で検査する: RUN Ref の時計と整数 ns・宣言通りの端点開閉。
    時計契約は RouteConfig.clock_contract から解決。C1 は (start,end]。"""
    clock: _Ref
    start_ns: int
    end_ns: int
    closure: _Literal["[start,end)", "(start,end]", "[start,end]", "(start,end)"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ContractValue:
    """F-a で検査する: 契約の版と不変 JSON 値の対応。自己申告を認証としない。"""
    contract: _ContractRef
    value: ImmutableJSON

    def __post_init__(self):
        # Builtin declarations are constructed before the private codec below.
        from types import MappingProxyType
        def freeze(value):
            if isinstance(value, _Mapping):
                return MappingProxyType({k: freeze(v) for k, v in value.items()})
            if isinstance(value, (list, tuple)):
                return tuple(freeze(v) for v in value)
            return value
        object.__setattr__(self, "value", freeze(self.value))


@_dataclass(frozen=True, slots=True, kw_only=True)
class Gap:
    """F-a で検査する: 経路、区間、根拠。sequence_range は二整数 [first,stop] だが
    意味は first <= seq < stop。閉区間を無到着の観測にしない。"""
    route_epoch: str
    sequence_range: tuple[int, int]
    interval: MeasurementInterval
    reason: str
    evidence: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementUnavailable:
    """F-a で検査する: 実際に測れなかった区間と根拠。測って0とは区別。"""
    route_epoch: str
    requested_interval: MeasurementInterval
    reason: str
    evidence: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class CoverageUnproved:
    """F-a で検査する: 完全性未証明と欠測を区別し不足契約と根拠を保持。"""
    route_epoch: str
    interval: MeasurementInterval
    missing_contracts: tuple[_ContractRef, ...]
    evidence: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class CoverageClaim:
    """F-a で検査する: kind・区間・契約・根拠。見張り生存を実測の完全性にしない。"""
    route_epoch: str
    interval: MeasurementInterval
    kind: str
    contract: _ContractRef
    evidence: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementFrame:
    """F-a で検査する: 実測 ID/区間/時計/実値と quality/cursor/欠け。
    measured_quality/1 の値は文字列 measured、sequence_cursor/1 は sample_seq と同じ非負整数。
    bool を整数とせず、Unavailable を実値へ射影しない。実測時刻を受信時刻で置換しない。
    simulated_clock/1 は同 RUN の ns・開閉・所属を検査するが実機適合の認証ではない。"""
    route_epoch: str
    sample_seq: int
    measurement_id: MeasurementId
    measurement_interval: MeasurementInterval
    actual_time: ClockReading | Unavailable
    value: ImmutableJSON | Unavailable
    quality: ContractValue
    gap: Gap | None
    source_cursor: ContractValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class RouteConfig:
    """F-a で検査する: bootstrapのnullとselectedの意思/実行参照。
    F-bで実際の有効化時刻を別に保持し、測る・運ぶ・検査する契約を分ける。
    """
    route_epoch: str
    origin: _Literal["bootstrap", "selected"]
    version: str
    sampling_contract: _ContractRef
    clock_contract: _ContractRef
    loss_contract: _ContractRef
    args: ImmutableJSON
    decision: _Ref | None
    execution: _Ref | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class Run:
    """F-b の未確定 DTO。RunException の名は採用済みだが columns の全数列/定数列の札、
    空列・count・欠番は F-b 着手前に確定する。F-a で未知 columns を検査済み Run として
    serializer の受理対象にしない。差分/等差は別版、時計の RUN Ref と別型。"""
    contract: _ContractRef
    route_epoch: str
    first_seq: int
    count: int
    encoding: str
    columns: _Mapping[str, ImmutableJSON]
    exceptions: tuple[RunException, ...]

@_dataclass(frozen=True, slots=True, kw_only=True)
class At:
    """F-a で検査する: 同runの整数nsと期限のsource。F-bで予約に接続。"""
    run: _Ref
    time_ns: int
    source: _Ref


@_dataclass(frozen=True, slots=True, kw_only=True)
class When:
    """F-a で検査する: 三値述語。F-bで世代内の初めて認証された発火に接続。"""
    predicate: PredicateRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    """F-a で検査する: 選ばれた操作・根・trigger・用途別draw。
    F-bで保存→送出→確認を接続。選択後に時刻だけ替えて証明を流用しない。
    """
    id: str
    policy_generation: str
    selected: _Ref
    root_key: str
    trigger: At | When
    operation: ActionSpec
    reservation_draw: DrawRecord | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ReservationDue:
    """F-a で検査する: 予定・検出・実行と根拠。F-bで同発火IDを保持。
    実行後は新記録を足し、先のDueを上書きしない。別runはclock_unaligned。
    """
    reservation_id: str
    firing_id: str
    due: ClockReading | Unavailable
    detected: ClockReading
    execution: ClockReading | None
    evidence: tuple[_Ref, ...]


# §3-10-13-3 の能力表にある全 kind。
CapabilityKind: _TypeAlias = _Literal[
    "action", "predicate", "kernel", "policy", "execution", "proof", "method",
    "arithmetic", "choice", "measurement", "projection", "generation", "clock",
    "quality", "cursor", "generator",
]


@_dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityDeclaration:
    """F-a で検査する: 能力の意味・入出力・引数・依存・条件。登録だけで認証しない。"""
    kind: CapabilityKind
    ref: _ContractRef
    args_contract: _ContractRef
    input_contract: _ContractRef
    output_contract: _ContractRef
    dependencies: tuple[_ContractRef, ...]
    conditions: tuple[ContractValue, ...]


@_dataclass(frozen=True, slots=True)
class CapabilityImplementation:
    """Python 側だけの対応。F-a で検査する: 同 kind/ref の重複と対応宣言。
    implementation は CapabilityCallable。args/input/output の直の JSON を構造検査し、
    proof の真偽の検査と分ける。JSON に関数を保存しない。
    identity は明示した不変の版・内容識別子 (今の約束 V-11・E-05)。組込みは
    "sui.f.native/1"。中身の違う実装に同じ identity を使い回さない。"""
    kind: CapabilityKind
    ref: _ContractRef
    implementation: CapabilityCallable
    identity: str


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FRegistry(_FactoryHandle):
    """make_f_registry が返す不変ハンドル。保持欄と factory 専用扱いは採用済み。
    F-a で検査する: 宣言と実装の対応。宣言だけの能力は登録可能。
    手組み・構造復号・登録だけを能力や proof の認証にしない。JSON にしない。"""
    declarations: tuple[CapabilityDeclaration, ...]
    implementations: tuple[CapabilityImplementation, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationCell:
    """Plan.cells の匿名要素。F-a で検査する: 観測セルと隠れた outcome 群。"""
    id: str
    observation: ObservationValue
    outcomes: tuple[str, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationValue(_JSONDTO):
    """Plan の観測射影。F-a で検査する: kind と原値・測定契約の対応。"""
    kind: _Literal["measurement", "coverage", "gap"]
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationSlot:
    """Binding.slots の匿名要素。F-a で検査する: 生成 slot と実測機会。"""
    slot: str
    measurement: MeasurementId


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationPlan:
    """F-a で検査する: 予測宣言・測定/時刻射影・生成契約と raw の観測セル。
    cells は記録を生成する全 outcome の kind/value 射影を覆う。
    evidence=None の outcome を閉区間や無到着の記録に変換せず別に保持する。
    value_only は捨てる時刻/quality が追加情報を持たない場合だけ認証する。"""
    model_ref: str
    route_epoch: str
    measurement_contract: _ContractRef
    kernel: KernelRef
    cells: tuple[ObservationCell, ...]
    time_projection: _ContractRef
    generation_contract: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationBinding:
    """F-a で検査する: plan・原記録・生成機会/step/slot と測定 ID の一致。
    opportunity_step_slot/1 の transition_key は正準 {plan:Ref,opportunity:Ref,step:int}
    の digest。配送 Record.id・スタック深さ・包装名を測定の識別に混ぜない。"""
    plan: _Ref
    records: tuple[_Ref, ...]
    opportunity: _Ref
    step: int
    cell: str
    slots: tuple[ObservationSlot, ...]
    generated_by: tuple[_Ref, ...]
    derived_from: tuple[MeasurementId, ...]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FiniteObservation(_FactoryHandle):
    """read_f_observations が返すハンドル。F-a で検査する: 原記録と Plan/Binding。
    同じ観測へ写る outcome の核を和にして一回適用する。手作りを信用しない。"""
    model_ref: str
    transition_key: str
    kernel: str
    outcomes: tuple[str, ...]
    measurements: tuple[MeasurementId, ...]
    records: tuple[_Ref, ...]
    binding: _Ref


@_dataclass(frozen=True, slots=True, kw_only=True)
class AppliedTransition:
    """F-a で検査する: 同じ遷移キーの入力一致。測定なしの遷移も冪等にする。"""
    transition_key: str
    input_digest: str
    measurements: tuple[MeasurementId, ...]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FResources(_FactoryHandle):
    """make_f_resources が返す非 JSON の不変ハンドル。保持欄と factory 専用扱いは採用済み。
    F-a で検査する: 固定モデル digest・原記録参照・版と検査器の解決。
    latest を読まず、時計・乱数源・可変主体・台帳書き手を資源として持たない。"""
    models: tuple[FModel | RateModel, ...]
    records: tuple[_Record, ...]
    registry: FRegistry
    preference_ledger: object | None  # Verified immutable reader, not a Ledger writer.


@_dataclass(frozen=True, slots=True, kw_only=True)
class StyleScope:
    """FStyle.scope の匿名値。F-a で検査する: 範囲と H。source は持たない。"""
    name: _Literal["unbounded_total", "one_step", "finite_horizon"]
    version: _Literal["1"]
    H_ns: int | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FStyle:
    """F-a で検査する: F の style 宣言と gamma。source は保存レコードから得る。"""
    kind: _Literal["style"]
    scope: StyleScope
    gamma: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FResolved(_FactoryHandle):
    """resolve_f_preferences が返す factory 専用ハンドル。欄・扱いは採用済み。
    F-a で検査する: 因果的取消と好みの解決。白紙は unbounded_total/gamma=1。
    手組み・構造復号を費用の認証にせず、一般の無限路への延長を仮定しない。"""
    items: tuple[_Ref, ...]
    style: _Ref | None
    scope: EvaluationScope
    gamma: _Fraction
    item_contracts: tuple[_ContractRef, ...]
    proofs: tuple[ProofRef, ...]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FProblem(_FactoryHandle):
    """prepare_f_problem が返す検査済みハンドル。F-a で検査する: draw を除く凍結問題。
    continuation.after は正準候補と同じ順/件数で一候補一項。問題 digest に含める。
    scope は resolved に一本化。予算・再開・表示を含めず手組みを認証しない。"""
    contract: _ContractRef
    problem_key: str
    world_key: str
    world_manifest: "FWorldManifest3"
    model_ref: str
    parents: frozenset[str]
    facts: tuple[_Ref, ...]
    E: EvidenceHistory
    K: KnowledgeHistory
    context: FContext
    preferences: tuple[_Ref, ...]
    style: _Ref | None
    scope: EvaluationScope
    gamma: _Fraction
    candidates: CandidateSet
    continuation: FContinuation
    measurement_contracts: tuple[_ContractRef, ...]
    execution_contracts: tuple[_ContractRef, ...]
    method: _ContractRef

    @property
    def world(self) -> FCertifiedWorld:
        from ._f_handles import attached_world
        return attached_world(self)


@_dataclass(frozen=True, slots=True, kw_only=True)
class PredicatePosition:
    """PredicateSnapshot.policy_position の二欄の匿名値。
    F-a で検査する: policy_end/1 の対象。全路の PolicyPosition とは欄が異なる。"""
    policy: str
    node: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class PolicyReturn:
    """F-a で検査する: 呼出元の policy/return_node と終了を追跡する operation。"""
    policy: str
    return_node: str
    operation: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class PolicyPosition:
    """F-a で検査する: 方針節・現在 operation・初手の完了・スタック・整数経過 ns。
    operation=None は初手終了後の外側方針。子 W の終了だけで複合 C を完了にしない。
    choose.next は子の ψ 成立後の戻り先。包装の制御を測定や Thought にしない。"""
    policy: str
    node: str
    operation: str | None
    first_completed: bool
    stack: tuple[PolicyReturn, ...]
    elapsed_ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPathTerminal:
    """FPathRow.terminal の匿名値。F-a で検査する: 終了と範囲打切りを区別。"""
    kind: _Literal["ended", "horizon"]
    position: PolicyPosition


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPathResidual:
    """FPathTable.residual の匿名要素。F-a で検査する: 候補別未展開質量。"""
    candidate: str
    mass: FQuantity


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFrontierRow:
    """F-a で検査する: 未展開の共同状態・位置・E/K・路全体費用の履歴。
    残余質量だけに潰さず、joint_state の和は probability。"""
    candidate: str
    probability: ExactReal
    joint_state: tuple[ExactReal, ...]
    E: EvidenceHistory
    K: KnowledgeHistory
    actions: tuple[ActionSpec, ...]
    position: PolicyPosition


@_dataclass(frozen=True, slots=True, kw_only=True)
class FNodeValue:
    """F-a で検査する: 選択節の候補軸と J/q/V。V は後続 J の softmax 平均。"""
    key: str
    candidate: str
    position: PolicyPosition
    knowledge_key: str
    alternatives: tuple[str, ...]
    J: tuple[FQuantity, ...]
    q_star: tuple[FQuantity, ...]
    V: FQuantity


@_dataclass(frozen=True, slots=True, kw_only=True)
class TailPrefix:
    """TailCertificate.prefix の匿名値。F-a で検査する: 表 digest と対象候補。"""
    table_digest: str
    kind: _Literal["complete", "prefix"]
    steps: int | None
    candidate: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasureCell:
    """F-a で検査する: 一様区間の非空有限セル。原子と連続部分を別成分として保つ。"""
    component: str
    lower: _Fraction
    upper: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurePartition:
    """F-a で検査する: 原子と連続成分の完全・互いに交わらない分割。"""
    atoms: tuple[str, ...]
    cells: tuple[MeasureCell, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class AtomMass:
    """MeasureCheck.atom_masses の匿名要素。F-a で検査する: 原子 ID と質量。"""
    id: str
    mass: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasureCheck:
    """F-a で検査する: 混合測度 ν の厳密質量。任意の J の積分や Z を認証しない。"""
    measure: CandidateMeasureRef
    partition: MeasurePartition
    atom_masses: tuple[AtomMass, ...]
    cell_masses: tuple[_Fraction, ...]
    total: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitProcess:
    """FLimitProblem.process と費用 law の匿名宣言。F-a で検査する: 独立公平ビット。"""
    name: _Literal["iid_fair_bits"]
    version: _Literal["1"]
    args: LimitProcessArgs


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitProcessArgs:
    """LimitProcess.args の匿名値。F-a で検査する: bool を整数0としない。"""
    index_origin: _Literal[0]


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitObservations:
    """FLimitProblem.observations の匿名値。F-a で検査する: args は空 object のみ。"""
    name: _Literal["reveal_next_bit"]
    version: _Literal["1"]
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class BlankLimitCost:
    """空白費用の和型。F-a で検査する: 追加キーなし、費用0。"""
    kind: _Literal["blank"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class PrefixLogLoss:
    """有限 prefix の log-loss 宣言。F-a で検査する: 宣言法則との一致。"""
    kind: _Literal["prefix_log_loss"]
    law: LimitProcess


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitScope:
    """負の極限診断の範囲。F-a で検査する: H_ns=null のみ。"""
    name: _Literal["unbounded_total"]
    version: _Literal["1"]
    H_ns: None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLimitProblem:
    """F-a で検査する: 負の診断だけの数学宣言。model.10 や選択・作用の入口にしない。"""
    process: LimitProcess
    observations: LimitObservations
    information_target: _Literal["entire_sequence"]
    cost: BlankLimitCost | PrefixLogLoss
    scope: LimitScope
    proof: ProofRef | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class LinearSequenceArgs:
    """ExactSequence.args の匿名値。F-a で検査する: 厳密な線形列の係数。"""
    slope: ExactReal
    intercept: ExactReal


@_dataclass(frozen=True, slots=True, kw_only=True)
class ExactSequence:
    """F-a で検査する: prefix の厳密な線形列。有限 prefix だけから発散を断定しない。"""
    name: _Literal["linear"]
    version: _Literal["1"]
    args: LinearSequenceArgs


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitInformation:
    """LimitCertificate.information の匿名値。F-a で検査する: 発散の証明。"""
    prefix: ExactSequence
    bound: _Literal["diverges"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitCost:
    """LimitCertificate.cost の匿名値。F-a で検査する: 費用の極限を別に証明。"""
    prefix: ExactSequence
    bound: _Literal["zero", "diverges"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitCertificate:
    """F-a で検査する: iid_bits_limit/1 の問題 digest と列の傾き。
    発散と証明不足を区別し、無限の差を相殺して Selected を作らない。"""
    problem_key: str
    checker: _ContractRef
    information: LimitInformation
    cost: LimitCost
    conclusion: _Literal["information_divergent", "undefined_infinite_difference"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class C1Probe:
    """C1CountFrame.probe の匿名値。F-a で検査する: p の独立測定と宣言ラベル。"""
    measurement_id: MeasurementId
    variable: str
    label: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class C1Read:
    """F-a で検査する: 検査済み実窓、不足、未使用記録の区別。時計だけなら frames は空。"""
    frames: tuple[C1CountFrame, ...]
    pending: tuple[DependencyRef, ...]
    untouched_records: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class VerifiedResult(_FactoryHandle):
    """検査係の factory が返すハンドル。F-a で検査する: 内容・入力 digest と方法の結合。
    f_from_json の構造復号・手作り DTO を検査済みとして評価・保存へ受け入れない。"""
    kind: _Literal["evaluation", "derive", "records"]
    input_key: str
    root_key: str | None
    input_digest: str
    method: _ContractRef
    result_digest: str
    certificate: ContractValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class FBeliefContent:
    """F-a で検査する: BELIEF の全保存欄、共同核・反映範囲・認証と未完了を区別。"""
    model_ref: str
    E: EvidenceHistory
    K: KnowledgeHistory
    kernel: ContractValue
    incorporated: tuple[MeasurementId, ...]
    normalization_proofs: tuple[_Ref, ...]
    query_proofs: tuple[_Ref, ...]
    pending: tuple[DependencyRef, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class RunException:
    """Run.exceptions の匿名要素。F-b で検査する: index と Frame 全欄との対応。"""
    index: int
    fields: _Mapping[str, ImmutableJSON]


class CapabilityCallable(_Protocol):
    """全能力共通の呼出規約。実装名から任意コードを import しない。"""

    def __call__(self, *, args: ImmutableJSON, input: ImmutableJSON,
                 context: CapabilityContext) -> ImmutableJSON:
        """F-a で args/input/output の直の JSON を各契約で検査する。
        proof の真偽は別検査。述語は budget=None で cache の読取りのみ。
        FInputError/FSpecificationMissing/FIncomplete/FOutsideEvaluationType/
        FModelFalsified/FNumericalRange を区別し、予期しない Python 例外は元のまま。
        """
        raise NotImplementedError("F-a")


@_dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityContext:
    """非 JSON の読み取り専用依存。F-a で検査する: 解決元と対象・予算。
    時計・乱数源・台帳書き手・可変主体を渡さない。"""
    registry: FRegistry | None
    resources: object | None
    model_ref: str | None
    budget: RateBudget | None
    numeric_work: object | None = None
    cached_quantities: object | None = None
    numeric_input: object | None = None
    certified_input: object | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ModelInput:
    """F-a で検査する: 固定モデル参照。"""
    model_ref: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class TailInput:
    """F-a で検査する: 同根・候補・prefix の結合。"""
    root: FRoot
    candidate: str
    prefix: FPathTable


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationInput:
    """F-a で検査する: 検査済み根と同根の再開。"""
    root: FRoot
    resume: ResumePoint | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationInput:
    """F-a で検査する: 根と条件付ける全計算入力。"""
    root: FRoot
    computation: ComputationSpec


@_dataclass(frozen=True, slots=True, kw_only=True)
class EnclosureInput:
    """F-a で検査する: 厳密式の形と定義域。"""
    expression: ExactReal


@_dataclass(frozen=True, slots=True, kw_only=True)
class ChoiceInput:
    """F-a で検査する: 同候補軸の J と有限非負質量・gamma。"""
    J: tuple[FQuantity, ...]
    masses: tuple[_Fraction, ...]
    gamma: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class ChoiceOutput:
    """F-a で検査する: 全候補軸の soft choice と正規化保証。"""
    q_star: tuple[FQuantity, ...]
    cumulative: tuple[RationalInterval, ...]
    Z: FQuantity


@_dataclass(frozen=True, slots=True, kw_only=True)
class ProofCheck:
    """F-a で検査する: 不成立と未完了の区別。条件名だけを証明にしない。"""
    status: _Literal["proved", "incomplete", "disproved"]
    reason: str | None
    evidence: tuple[ContractValue, ...]
    missing: tuple[DependencyRef, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class SimulationBinding:
    """F-a で検査する: 数学用の operation/policy/prediction。実機への適合としない。"""
    operation: str
    policy: PolicyRef
    prediction: KernelRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class ObservationInput:
    """F-a で検査する: plan/binding が指す raw は context.resources で読む。"""
    plan: ObservationPlan
    binding: ObservationBinding


@_dataclass(frozen=True, slots=True, kw_only=True)
class GenerationInput:
    """F-a で検査する: 機会/step/slot の生成関係。"""
    plan: ObservationPlan
    binding: ObservationBinding


@_dataclass(frozen=True, slots=True, kw_only=True)
class GenerationOutput:
    """F-a で検査する: 正準生成位置 digest と原記録からの測定 ID。"""
    transition_key: str
    slots: tuple[ObservationSlot, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class ClockInput:
    """F-a で検査する: 同 RUN の時計・区間開閉と実時刻の所属。"""
    reading: ClockReading
    interval: MeasurementInterval


@_dataclass(frozen=True, slots=True, kw_only=True)
class CursorInput:
    """F-a で検査する: sequence_cursor/1 の非負整数が sample_seq と一致。bool は拒否。"""
    cursor: ContractValue
    sample_seq: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class CandidateInput:
    """F-a で検査する: 候補生成の明示された固定入力。"""
    actions: tuple[ActionSpec, ...]
    basis: tuple[_Ref, ...]
    draws: tuple[DrawRecord, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class DrawRequest(_JSONDTO):
    """F-a で検査する: 用途・問題キー・ordinal と値の法則。selection は uniform_unit/1、args={}。
    §3-10-13-補で採用した配置: f.py で定義する。"""
    purpose: _Literal["candidate_generation", "selection", "reservation", "algorithm"]
    context_key: str
    ordinal: int
    law: _ContractRef
    args: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class RequiredCapability:
    """FPreflight.required_capabilities の要素。名前は §3-10-13-補で採用済み。
    F-a で検査する: 意味と必要な実装を分け、bool を数値としない。"""
    kind: CapabilityKind
    ref: _ContractRef
    implementation_required: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflight:
    """F-a で検査する: 前提検査だけの明示入力。prepare_f_problem 全体の失敗を認証しない。
    不足の主理由はモデル、Ref 辞書順、能力 kind/name/version 順。不足全件は検査証明へ。"""
    parents: frozenset[str]
    model_ref: str | None
    required_records: tuple[_Ref, ...]
    required_capabilities: tuple[RequiredCapability, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreflightReady:
    """F-a で検査する: 検査器が固定 resources から求めた前提 input_key。
    成功しても根・Selected・外部作用を作らない。"""
    input_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class ContinuationAfter:
    """FContinuation.after の要素。名前は §3-10-13-補で採用済み。
    F-a で検査する: 正準候補ごとに一項。policy=None は宣言した追加操作がない意味。"""
    candidate: str
    policy: PolicyRef | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FContinuation:
    """F-a で検査する: 候補と同順・同件数の初手終了後の明示方針。
    one_step は起動せず、unbounded_total/finite_horizon は初手終了後に一度入る。
    終わらない枝は移らない。null でも既存経路/残りの測定を切らず未認証尾を保持する。"""
    after: tuple[ContinuationAfter, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FModelDependency:
    ref: str
    present: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class FRecordDependency:
    ref: _Ref
    digest: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCapabilityDependency:
    kind: CapabilityKind
    ref: _ContractRef
    declaration: CapabilityDeclaration | None
    implemented: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class FResourceSnapshot:
    models: tuple[FModelDependency, ...]
    records: tuple[FRecordDependency, ...]
    capabilities: tuple[FCapabilityDependency, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreferencePoint:
    """A visible ledger point; CID and record ID are distinct identities."""
    cid: str
    record: _Ref


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreferenceCausality:
    """Canonical receipt of the relation derived by preference.from_ledger."""
    points: tuple[FPreferencePoint, ...]
    before: tuple[tuple[_Ref, _Ref], ...]


# 今の約束 E-05: the facts compiler's dependency image, keyed by Point (P7).
@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsPointDependency:
    point: str
    entry_present: bool
    body_present: bool
    record: _Ref | None
    record_digest: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsModelDependency:
    point: str
    model_ref: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsCapabilityDependency:
    kind: CapabilityKind
    ref: _ContractRef
    declaration: CapabilityDeclaration | None
    implemented: bool
    implementation_id: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsRefLookup:
    ref: _Ref
    points: tuple[str, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsAbsenceEnvironment:
    reader_view_key: str
    registry_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsDependencies:
    points: tuple[FFactsPointDependency, ...]
    models: tuple[FFactsModelDependency, ...]
    capabilities: tuple[FFactsCapabilityDependency, ...]
    ref_lookups: tuple[FFactsRefLookup, ...]
    absence_environment: FFactsAbsenceEnvironment | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FWorldManifest3:
    contract: _ContractRef
    compiler: _ContractRef
    request: "FMathFactsInput | FMathLegacyBridgeInput"
    dependencies: FFactsDependencies
    preference_causality: FPreferenceCausality


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FCertifiedWorld(_FactoryHandle):
    """Only the compiler issues this non-JSON, immutable world handle."""
    world_key: str
    manifest: "FWorldManifest3"
    model_ref: str
    scope: EvaluationScope
    candidates: CandidateSet
    continuation: FContinuation
    E: EvidenceHistory
    K: KnowledgeHistory


@_dataclass(frozen=True, slots=True, kw_only=True)
class C1MeasurementContent:
    model_ref: str
    measurement_id: MeasurementId
    run: _Ref
    origin_ns: int
    start_ns: int
    end_ns: int
    count: int
    generated_by: tuple[_Ref, ...]



# §3-10-13-3・補 の七欄。S(T) は採用された snake(T) の名前で具体化する。
# S/A は wire schema であり能力として再帰登録しない。条件名だけを認証しない。
_BUILTIN_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        kind="action",
        ref=_ContractRef("finite_option", "1"),
        args_contract=_ContractRef("sui.f.args.finite_option", "1"),
        input_contract=_ContractRef("sui.f.schema.action_spec", "1"),
        output_contract=_ContractRef("sui.f.schema.action_spec", "1"),
        dependencies=(_ContractRef("finite_policy", "1"), _ContractRef("finite_kernel", "1")),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="kernel",
        ref=_ContractRef("finite_kernel", "1"),
        args_contract=_ContractRef("sui.f.args.id", "1"),
        input_contract=_ContractRef("sui.f.schema.model_input", "1"),
        output_contract=_ContractRef("sui.f.schema.finite_kernel", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("declared_reference",)}),),
    ),
    CapabilityDeclaration(
        kind="policy",
        ref=_ContractRef("finite_policy", "1"),
        args_contract=_ContractRef("sui.f.args.id", "1"),
        input_contract=_ContractRef("sui.f.schema.model_input", "1"),
        output_contract=_ContractRef("sui.f.schema.finite_policy", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("declared_reference",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("constant", "1"),
        args_contract=_ContractRef("sui.f.args.constant", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("fact_present", "1"),
        args_contract=_ContractRef("sui.f.args.fact_present", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("interval_compare", "1"),
        args_contract=_ContractRef("sui.f.args.interval_compare", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("and", "1"),
        args_contract=_ContractRef("sui.f.args.terms", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("or", "1"),
        args_contract=_ContractRef("sui.f.args.terms", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("not", "1"),
        args_contract=_ContractRef("sui.f.args.term", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only",)}),),
    ),
    CapabilityDeclaration(
        kind="predicate",
        ref=_ContractRef("policy_end", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.predicate_snapshot", "1"),
        output_contract=_ContractRef("sui.f.schema.predicate_result", "1"),
        dependencies=(_ContractRef("finite_policy", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("cached_only", "declared_reference")}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("finite_option_proof", "1"),
        args_contract=_ContractRef("sui.f.args.operation", "1"),
        input_contract=_ContractRef("sui.f.schema.model_input", "1"),
        output_contract=_ContractRef("sui.f.schema.proof_check", "1"),
        dependencies=(_ContractRef("finite_policy", "1"), _ContractRef("finite_kernel", "1")),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("declared_reference",)}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("finite_tree", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.f_root", "2"),
        output_contract=_ContractRef("sui.f.schema.proof_check", "1"),
        dependencies=(_ContractRef("finite_option_proof", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("finite_tree",)}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("fixed_policy_tail", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.tail_input", "2"),
        output_contract=_ContractRef("sui.f.schema.proof_check", "1"),
        dependencies=(_ContractRef("finite_option_proof", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("fixed_continuation",)}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("static_target_entropy_bound", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.f_root", "2"),
        output_contract=_ContractRef("sui.f.schema.proof_check", "1"),
        dependencies=(_ContractRef("finite_kernel", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("static_finite_target",)}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("finite_terminal_cost", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.f_root", "2"),
        output_contract=_ContractRef("sui.f.schema.proof_check", "1"),
        dependencies=(_ContractRef("finite_tree", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("finite_terminal_cost",)}),),
    ),
    CapabilityDeclaration(
        kind="proof",
        ref=_ContractRef("iid_bits_limit", "1"),
        args_contract=_ContractRef("sui.f.args.iid_bits_limit", "1"),
        input_contract=_ContractRef("sui.f.schema.f_limit_problem", "1"),
        output_contract=_ContractRef("sui.f.schema.limit_certificate", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("iid_fair_bits",)}),),
    ),
    CapabilityDeclaration(
        kind="method",
        ref=_ContractRef("sui.f.finite_evaluation", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.evaluation_input", "2"),
        output_contract=_ContractRef("sui.f.schema.f_evaluation", "2"),
        dependencies=(_ContractRef("finite_tree", "1"), _ContractRef("fixed_policy_tail", "1"), _ContractRef("static_target_entropy_bound", "1"), _ContractRef("finite_terminal_cost", "1"), _ContractRef("sui.f.exact_expression", "1"), _ContractRef("sui.f.soft_choice", "1")),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("static_finite_target",)}),),
    ),
    CapabilityDeclaration(
        kind="method",
        ref=_ContractRef("sui.f.computation_information", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.computation_input", "2"),
        output_contract=_ContractRef("sui.f.schema.information_parts", "1"),
        dependencies=(_ContractRef("sui.f.exact_expression", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("full_input_conditioning",)}),),
    ),
    CapabilityDeclaration(
        kind="arithmetic",
        ref=_ContractRef("sui.f.exact_expression", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.enclosure_input", "1"),
        output_contract=_ContractRef("sui.f.schema.f_quantity", "1"),
        dependencies=(),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="choice",
        ref=_ContractRef("sui.f.soft_choice", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.choice_input", "1"),
        output_contract=_ContractRef("sui.f.schema.choice_output", "1"),
        dependencies=(_ContractRef("sui.f.exact_expression", "1"),),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="execution",
        ref=_ContractRef("sui.f.simulated_execution", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.action_spec", "1"),
        output_contract=_ContractRef("sui.f.schema.simulation_binding", "1"),
        dependencies=(_ContractRef("finite_option_proof", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("simulation_only",)}),),
    ),
    CapabilityDeclaration(
        kind="measurement",
        ref=_ContractRef("sui.f.finite_measurement", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.observation_input", "1"),
        output_contract=_ContractRef("sui.f.schema.observation_value", "1"),
        dependencies=(_ContractRef("sui.f.measured_quality", "1"), _ContractRef("sui.f.sequence_cursor", "1")),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="projection",
        ref=_ContractRef("sui.f.value_only", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.observation_input", "1"),
        output_contract=_ContractRef("sui.f.schema.observation_value", "1"),
        dependencies=(_ContractRef("sui.f.finite_measurement", "1"),),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("value_only",)}),),
    ),
    CapabilityDeclaration(
        kind="generation",
        ref=_ContractRef("sui.f.opportunity_step_slot", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.generation_input", "1"),
        output_contract=_ContractRef("sui.f.schema.generation_output", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("recorded_generation",)}),),
    ),
    CapabilityDeclaration(
        kind="clock",
        ref=_ContractRef("sui.f.simulated_clock", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.clock_input", "1"),
        output_contract=_ContractRef("sui.f.schema.clock_reading", "1"),
        dependencies=(),
        conditions=(ContractValue(contract=_ContractRef("sui.f.capability_conditions", "1"), value={"checks": ("same_run", "simulation_only")}),),
    ),
    CapabilityDeclaration(
        kind="quality",
        ref=_ContractRef("sui.f.measured_quality", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.contract_value", "1"),
        output_contract=_ContractRef("sui.f.schema.contract_value", "1"),
        dependencies=(),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="cursor",
        ref=_ContractRef("sui.f.sequence_cursor", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.cursor_input", "1"),
        output_contract=_ContractRef("sui.f.schema.contract_value", "1"),
        dependencies=(),
        conditions=(),
    ),
    CapabilityDeclaration(
        kind="generator",
        ref=_ContractRef("sui.f.explicit_candidates", "1"),
        args_contract=_ContractRef("sui.f.args.empty", "1"),
        input_contract=_ContractRef("sui.f.schema.candidate_input", "1"),
        output_contract=_ContractRef("sui.f.schema.candidate_input", "1"),
        dependencies=(),
        conditions=(),
    ),
)


def _builtin_capability(*, args: ImmutableJSON, input: ImmutableJSON,
                        context: CapabilityContext) -> ImmutableJSON:
    """組み込み共通の空実装。共通呼出規約だけを固定し計算を行わない。"""
    raise NotImplementedError("F-a")


NATIVE_IMPLEMENTATION = "sui.f.native/1"

_BUILTIN_IMPLEMENTATIONS: tuple[CapabilityImplementation, ...] = (
    CapabilityImplementation(kind="action", ref=_ContractRef("finite_option", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="kernel", ref=_ContractRef("finite_kernel", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="policy", ref=_ContractRef("finite_policy", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("constant", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("fact_present", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("interval_compare", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("and", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("or", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("not", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="predicate", ref=_ContractRef("policy_end", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("finite_option_proof", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("finite_tree", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("fixed_policy_tail", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("static_target_entropy_bound", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("finite_terminal_cost", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="proof", ref=_ContractRef("iid_bits_limit", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="method", ref=_ContractRef("sui.f.finite_evaluation", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="method", ref=_ContractRef("sui.f.computation_information", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="arithmetic", ref=_ContractRef("sui.f.exact_expression", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="choice", ref=_ContractRef("sui.f.soft_choice", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="execution", ref=_ContractRef("sui.f.simulated_execution", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="measurement", ref=_ContractRef("sui.f.finite_measurement", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="projection", ref=_ContractRef("sui.f.value_only", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="generation", ref=_ContractRef("sui.f.opportunity_step_slot", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="clock", ref=_ContractRef("sui.f.simulated_clock", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="quality", ref=_ContractRef("sui.f.measured_quality", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="cursor", ref=_ContractRef("sui.f.sequence_cursor", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
    CapabilityImplementation(kind="generator", ref=_ContractRef("sui.f.explicit_candidates", "1"),
        implementation=_builtin_capability, identity=NATIVE_IMPLEMENTATION),
)


# f_entry.FPublicValue の JSON 値。Python の実装・資源ハンドルは含めない。
_FValue: _TypeAlias = (
    Unavailable | ExactReal | ActionFamilyRef | PredicateRef | KernelRef | PolicyRef
    | ProofRef | QuantityRef | DependencyRef | ActionSpec | PredicateResult
    | PredicateWork | EvidenceEmission | AvailabilityChange | FiniteOutcome
    | FiniteKernel | ExecuteNode | ChooseNode | EndNode | FinitePolicy
    | CandidateMeasureRef | CandidateSet | EvaluationScope | CandidateExclusion
    | NormalizationCertificate | MeasurementId | EvidenceLink | EvidenceHistory
    | KnowledgeHistory | FContext | FRoot | DrawRecord | FQuantity | FQuantityDefinition | TailCertificate
    | InformationParts | FCertificate | FEvaluation | Selected | NoDecision
    | FiniteBelief | PredicateSnapshot | ComputationSpec | FScope | FPathRow
    | FPathTable | LegacyComparison | ResumePoint | C1CountFrame | C1Summary
    | ClockReading | MeasurementInterval | ContractValue | Gap
    | MeasurementUnavailable | CoverageUnproved | CoverageClaim | MeasurementFrame
    | RouteConfig | At | When | Reservation | ReservationDue
    | CapabilityDeclaration | ObservationCell | ObservationValue | ObservationSlot | ObservationPlan
    | ObservationBinding | FiniteObservation | AppliedTransition | StyleScope | FStyle | FResolved
    | FProblem | PredicatePosition | PolicyReturn | PolicyPosition | FPathTerminal | FPathResidual
    | FFrontierRow | FNodeValue | TailPrefix | MeasureCell | MeasurePartition | AtomMass | MeasureCheck
    | LimitProcess | LimitProcessArgs | LimitObservations | BlankLimitCost | PrefixLogLoss | LimitScope
    | FLimitProblem | LinearSequenceArgs | ExactSequence | LimitInformation | LimitCost
    | LimitCertificate | C1Probe | C1Read | VerifiedResult | FBeliefContent
    | C1MeasurementContent | FModelDependency | FRecordDependency | FCapabilityDependency | FResourceSnapshot | FPreferencePoint | FPreferenceCausality
    | ModelInput | TailInput | EvaluationInput | ComputationInput | EnclosureInput | ChoiceInput | ChoiceOutput | ProofCheck | SimulationBinding | ObservationInput | GenerationInput | GenerationOutput | ClockInput | CursorInput | CandidateInput | DrawRequest | RequiredCapability | FPreflight | PreflightReady | ContinuationAfter | FContinuation
)


def canonical_candidates(actions: tuple[ActionSpec, ...], *,
                         measure: CandidateMeasureRef | None,
                         generator: _ContractRef, basis: tuple[_Ref, ...],
                         draws: tuple[DrawRecord, ...], registry: FRegistry) -> CandidateSet:
    """F-a で registry を使って族を正準化し入力の最初の代表順を保持する。
    表示別名で質量を増やさず、候補/測度が未認証でも消さない。
    モデル参照や操作全体の評価可能性は prepare_f_problem が検査する。
    宣言欠落 FSpecificationMissing(missing_contract)、実装欠落 FIncomplete(algorithm_unavailable)、
    不正入力/衝突 FInputError。正準化だけを認証とせず、selection を隠れて引かない。"""
    _require(registry, FRegistry)
    if type(actions) is not tuple:
        raise FInputError("shape", field="actions")
    _unique(tuple(a.id for a in actions), "actions", nonempty=True)
    representatives, aliases, keys = [], {}, {}
    for action in actions:
        action = canonical_action(action, registry=registry)
        if action.semantic_key in keys:
            aliases[action.id] = keys[action.semantic_key]
        else:
            representatives.append(action)
            keys[action.semantic_key] = action.id
    return _decode(_encode(CandidateSet(candidates=tuple(representatives),
        aliases=_MappingProxyType(aliases), measure=measure, generator=generator,
        basis=basis, draws=draws)), CandidateSet)


def check_predicate(predicate: PredicateRef, *,
                    snapshot: PredicateSnapshot, resources: FResources) -> PredicateResult:
    """F-a で同じ resources と取得済み snapshot のみから三値を返す。
    policy_end は同モデル policies[policy].nodes[node].kind を読み、節名から推測しない。
    未宣言参照 FInputError(unresolved_reference)、宣言済み入力の欠落 FReplayUnavailable(missing_input)。
    未取得位置は unknown と不足依存。AND/OR/NOT の子にも同資源を渡す。
    宣言欠落 FSpecificationMissing(missing_contract)、実装欠落 FIncomplete(algorithm_unavailable)。
    重い検査は Unknown と同一 PredicateWork にし、budget=None で cached_only を守る。"""
    _require(resources, FResources)
    predicate = _decode(_encode(predicate), PredicateRef)
    from ._f_quantity import checked_snapshot, checked_resources
    snapshot = checked_snapshot(snapshot)
    checked_resources(snapshot,resources)
    result = _call_capability("predicate", _ContractRef(predicate.name, predicate.version),
        args=predicate.args, input=_encode(snapshot), resources=resources,
        registry=resources.registry, model_ref=snapshot.model_ref, budget=None,
        cached_quantities=snapshot.quantities)
    result = _decode(result, PredicateResult)
    if result.value != "unknown":
        if result.missing or result.work is not None:
            raise FInputError("capability_output_shape", "known predicate has pending work")
        return result
    work = PredicateWork(work_id=_digest({"predicate": predicate, "snapshot": snapshot,
        "missing": result.missing}), predicate=predicate, snapshot=snapshot, missing=result.missing)
    return _replace(result, work=work)


def update_finite_belief(model: FModel, belief: FiniteBelief, *,
                         kernel: str, outcome: str,
                         measurement: MeasurementId | None, transition_key: str) -> FiniteBelief:
    """F-a で宣言順の共同信念を一 outcome 更新する低水準入口。
    transition_key は必須で measurement=None でも同キー・入力の再適用は no-op。
    異なる入力の再利用は FInputError(measurement_conflict)。手作りハンドルを信用しない。
    質量0 FModelFalsified(zero_evidence)、形/参照 FInputError、能力不足 FIncomplete、
    型の外 FOutsideEvaluationType。raw の照合は read_f_observations/apply_f_observation。"""
    measurements = () if measurement is None else (measurement,)
    return _update_joint(model, belief, kernel=kernel, outcomes=(outcome,),
                         measurements=measurements, transition_key=transition_key)


def initial_finite_belief(model: FModel | FFiniteUpdateModel) -> FiniteBelief:
    """F-aで宣言の共同事前からハンドルを作る。不正入力FInputError。
    認証未対応はFIncomplete、評価型の外FOutsideEvaluationType。
    数表を外から注入するfactoryではない。
    v0.14のFFiniteUpdateModelは発行元のモデルPointへ照合する。FModel互換計算は保持。
    """
    if isinstance(model, FFiniteUpdateModel):
        from ._f_handles import require_issued
        model = require_issued(model, FFiniteUpdateModel).model
    from .f_model import _checked, _model_ref as f_model_ref
    data = _checked(model)
    return _handle(FiniteBelief, authority=model, model_ref=f_model_ref(model),
        evidence_key=_digest(()), joint=_decode(data["initial"], tuple[_Fraction, ...]),
        evidence_mass=_Fraction(1), applied=())


def finite_marginal(belief: FiniteBelief, *, target: str) -> _Fraction:
    """F-a で検査済みハンドルに結合したモデル軸の対象周辺確率を返す。
    未知対象/軸 FInputError、未認証 FIncomplete、数値範囲 FNumericalRange。
    手作り・構造復号を検査済みの共同信念としない。"""
    from .f_model import _checked
    model = _require(belief, FiniteBelief)
    data = _checked(model)
    if target not in data["targets"]:
        raise FInputError("unresolved_reference", field="target")
    return sum((q for q, s in zip(belief.joint, data["states"]) if s["target"] == target), _Fraction(0))


def certify_f_scope(root: FRoot, *, budget: RateBudget) -> FScope:
    from ._f_eval import certify_f_scope as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,budget=budget),'scope',inputs={'root_step':root},args={'budget':budget})


def enumerate_f_paths(root: FRoot, *, budget: RateBudget) -> FPathTable:
    from ._f_eval import enumerate_f_paths as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,budget=budget),'enumerate',inputs={'root_step':root},args={'budget':budget})


def evaluate_f_enumerated(root: FRoot, paths: FPathTable, *,
                          budget: RateBudget) -> FEvaluation:
    from ._f_eval import evaluate_f_enumerated as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,paths,budget=budget),'enumerated',inputs={'root_step':root,'paths_step':paths},args={'budget':budget})


def evaluate_f_recursive(root: FRoot, *, budget: RateBudget) -> FEvaluation:
    from ._f_eval import evaluate_f_recursive as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,budget=budget),'recursive',inputs={'root_step':root},args={'budget':budget})




def evaluate_f_prefix(root: FRoot, *, steps: int,
                      budget: RateBudget) -> FEvaluation:
    from ._f_eval import evaluate_f_prefix as invoke
    from ._f_handles import trace_math, has_math
    if not has_math(root):
        return invoke(root,steps=steps,budget=budget)
    prefix=enumerate_f_prefix(root,steps=steps,budget=budget)
    return trace_math(invoke(root,steps=steps,budget=budget),'prefix_evaluation',
        inputs={'root_step':root,'prefix_step':prefix},args={'budget':budget})


def certify_f_tail(root: FRoot, *, candidate: str,
                    prefix: FPathTable, budget: RateBudget) -> TailCertificate:
    from ._f_eval import certify_f_tail as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,candidate=candidate,prefix=prefix,budget=budget),'tail',
        inputs={'root_step':root,'prefix_step':prefix},args={'candidate':candidate,'budget':budget})


def certify_f_choice(evaluation: FEvaluation, *,
                      u: _Fraction | float) -> Selected | NoDecision:
    from ._f_eval import certify_f_choice as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(evaluation,u=u),'choice',inputs={'evaluation_step':evaluation},args={})


def evaluate_f(root: FRoot, *, budget: RateBudget,
                resume: ResumePoint | None = None) -> Selected | NoDecision:
    from ._f_eval import evaluate_f as invoke
    from ._f_handles import trace_math,has_math,math_source
    if has_math(root) and resume is not None:math_source(resume)
    inputs={'root_step':root}
    args={'budget':budget,'resume_step':None}
    if resume is not None:
        inputs['resume_step']=resume
        args.pop('resume_step')
    return trace_math(invoke(root,budget=budget,resume=resume),'evaluate',inputs=inputs,args=args)


def computation_information(root: FRoot, *,
                              computation: ComputationSpec,
                              budget: RateBudget) -> InformationParts:
    from ._f_eval import computation_information as invoke
    return invoke(root, computation=computation, budget=budget)


def legacy_information(parts: InformationParts) -> FQuantity:
    """F-aでalready_received+additionalから旧Gに必要な総情報を復元。
    H=0の公平な完全O0はln2を一度保持。未認証はuncertifiedを保持する。
    不正な対応FInputError、証明不一致FReplayMismatch。費用の共通項を消さない。
    """
    if parts.already_received.status != "finite" or parts.additional.status != "finite":
        return FQuantity(status="uncertified", exact=None, bounds=None, proof=None, reason="certificate_incomplete")
    if parts.already_received.exact is not None and parts.additional.exact is not None:
        exact = _add(parts.already_received.exact, parts.additional.exact)
    else:
        exact = None
    return FQuantity(status="finite", exact=exact, bounds=_iadd(parts.already_received.bounds, parts.additional.bounds), proof=None, reason=None)


def initial_c1_summary(model: RateModel, *, run: _Ref, origin_ns: int) -> C1Summary:
    """F-a で限定 model.9 を検査し run/origin_ns に結合したハンドルを返す。
    初期 end_ns=origin_ns、(N,T_s,A0,A1)=(0,0,4,0)、p 帳面は宣言順 [0,0]。
    閉包未証明 FIncomplete(c1_closure_unproved)、不正宣言 FInputError、型外 FOutsideEvaluationType。"""
    cfg = _c1_checked_config(model)
    if not isinstance(run, _Ref) or run.kind != _RefKind.RUN or type(origin_ns) is not int:
        raise FInputError("shape", "run and integer origin required")
    from .rate_model import rate_model_ref
    variable = cfg["_probability"]["id"]
    from ._f_handles import issue
    return issue(_handle(C1Summary, authority=(cfg, _MappingProxyType({})),
        model_ref=rate_model_ref(model), run=run, origin_ns=origin_ns,
        measurement_ids=(), source_records=(), end_ns=origin_ns, N=0,
        T_s=_Fraction(0), A0=_Fraction(4), A1=_Fraction(0),
        probe_measurements=(), probe_counts=_MappingProxyType({variable: (0, 0)})))


def update_c1_summary(summary: C1Summary, *, frame: C1CountFrame) -> C1Summary:
    """F-a で read_c1_frames の検査済み窓だけを共同密度と p 帳面へ反映する。
    同 ID 同内容は計数を変えず配送来歴だけを追加。衝突 FInputError(measurement_conflict)。
    手作り・内容変更後のハンドルを信用しない。
    飽和3以上・隙間・一般率・順序不明は FIncomplete(c1_closure_unproved)。
    窓途中を count=0 にせず、T_s=(end_ns-origin_ns)/10^9 を秒 Fraction で保つ。
    原記録を保持、不正入力 FInputError、質量0 FModelFalsified(zero_evidence)。"""
    from ._f_handles import issue, require_issued
    cfg, seen = require_issued(summary, C1Summary)
    frame_model = require_issued(frame, C1CountFrame)
    if frame_model != summary.model_ref or frame.run != summary.run or frame.origin_ns != summary.origin_ns:
        raise FInputError("measurement_conflict", "summary and frame domains differ")
    digest = _digest(_c1_measurement_content(frame, frame_model))
    probe_digest = None if frame.probe is None else _digest({"model_ref":frame_model,"probe":frame.probe,"generated_by":frame.generated_by})
    if frame.probe is not None and frame.probe.measurement_id in seen and seen[frame.probe.measurement_id] != probe_digest:
        raise FInputError("measurement_conflict", "probe contents differ")
    counts = dict(summary.probe_counts)
    probes = summary.probe_measurements
    new_seen = dict(seen)
    if frame.probe is not None:
        probe = frame.probe
        labels = cfg["_probability"]["domain"]["labels"]
        if probe.variable not in counts or probe.label not in labels or probe.measurement_id == frame.measurement_id:
            raise FInputError("measurement_conflict", "invalid independent probe")
        if probe.measurement_id not in seen:
            previous = counts[probe.variable]
            counts[probe.variable] = tuple(c + (i == labels.index(probe.label)) for i, c in enumerate(previous))
            probes += (probe.measurement_id,)
            new_seen[probe.measurement_id] = probe_digest
    if frame.measurement_id in seen:
        if seen[frame.measurement_id] != digest:
            raise FInputError("measurement_conflict", "same measurement has different contents")
        deliveries = tuple(dict.fromkeys(summary.source_records + frame.delivery_records))
        if deliveries == summary.source_records and probes == summary.probe_measurements:
            return summary
        values = {f.name:getattr(summary,f.name) for f in _fields(C1Summary)}
        values.update(source_records=deliveries, probe_measurements=probes, probe_counts=_MappingProxyType(counts))
        return issue(_handle(C1Summary, authority=(cfg,_MappingProxyType(new_seen)), **values))
    if frame.start_ns != summary.end_ns or frame.end_ns <= frame.start_ns or type(frame.count) is not int or frame.count not in (0, 1, 2):
        raise FIncomplete("c1_closure_unproved", "only contiguous exact windows with counts 0/1/2 are closed")
    delta = _Fraction(frame.end_ns - frame.start_ns, 10**9)
    n = frame.count
    d0 = delta**n / _math.factorial(n)
    d1 = 2**n * d0
    v = delta**(n+1) * (2**(n+1)-1) / _math.factorial(n+1)
    values = {f.name: getattr(summary, f.name) for f in _fields(C1Summary)}
    values.update(measurement_ids=summary.measurement_ids+(frame.measurement_id,),
        source_records=tuple(dict.fromkeys(summary.source_records+frame.delivery_records)), end_ns=frame.end_ns,
        N=summary.N+n, T_s=_Fraction(frame.end_ns-summary.origin_ns, 10**9),
        A0=d0*summary.A0, A1=v*summary.A0+d1*summary.A1,
        probe_measurements=probes, probe_counts=_MappingProxyType(counts))
    new_seen[frame.measurement_id] = digest
    return issue(_handle(C1Summary, authority=(cfg, _MappingProxyType(new_seen)), **values))


def c1_state_marginal(summary: C1Summary) -> tuple[_Fraction, _Fraction]:
    """F-aで共同密度の状態重みを正規化する。rを平均へ置き換えない。
    未証明閉包FIncomplete、質量0FModelFalsified、不正入力FInputError。
    """
    from ._f_handles import require_issued
    require_issued(summary, C1Summary)
    denominator = 2+2*summary.T_s
    w0 = summary.A0 * _math.factorial(summary.N+1) / denominator**(summary.N+2)
    w1 = summary.A1 * _math.factorial(summary.N+2) / denominator**(summary.N+3)
    total = w0+w1
    if total <= 0:
        raise FModelFalsified("zero_evidence")
    return _Fraction(w0/total), _Fraction(w1/total)


def _c1_checked_config(model):
    from .rate import _c1_config, RateIncomplete, RateInputError, RateOutsideEvaluationType
    if not isinstance(model, RateModel):
        raise FOutsideEvaluationType("OutsideEvaluationType", "C1 requires model.9")
    try:
        return _c1_config(model)
    except RateIncomplete as exc:
        raise FIncomplete("c1_closure_unproved", exc.detail, exc.field) from exc
    except RateInputError as exc:
        raise FInputError(exc.reason, exc.detail, exc.field) from exc
    except RateOutsideEvaluationType as exc:
        raise FOutsideEvaluationType("OutsideEvaluationType", exc.detail, exc.field) from exc



def make_f_registry(*, declarations: tuple[CapabilityDeclaration, ...],
                    implementations: tuple[CapabilityImplementation, ...]) -> FRegistry:
    """F-a で不変 registry を作る。対応宣言なし・同 kind/ref 二重登録は FInputError。
    宣言のみは登録可能。使用時に意味不足 FSpecificationMissing / 能力不足 FIncomplete。
    グローバル登録や JSON から任意関数を import せず、登録だけで認証しない。"""
    if type(declarations) is not tuple or type(implementations) is not tuple:
        raise FInputError("shape", "tuples required")
    declarations = tuple(_decode(_encode(d), CapabilityDeclaration) for d in declarations)
    keys = tuple((d.kind, d.ref) for d in declarations)
    _unique(keys, "declarations")
    impl_keys = []
    for impl in implementations:
        if (type(impl) is not CapabilityImplementation or not callable(impl.implementation)
                or type(impl.identity) is not str or not impl.identity):
            raise FInputError("shape", field="implementations")
        key = (impl.kind, impl.ref)
        if key not in keys:
            raise FInputError("unresolved_reference", "implementation has no declaration")
        impl_keys.append(key)
    _unique(impl_keys, "implementations")
    return _handle(FRegistry, declarations=declarations, implementations=implementations)


def builtin_f_registry() -> FRegistry:
    """F-a で §3-10-13-3 の28行の七欄と共通 CapabilityCallable を不変 registry にする。
    元データは同モジュールの _BUILTIN_DECLARATIONS/_BUILTIN_IMPLEMENTATIONS。
    S(T) は sui.f.schema. + snake(T)。既存 ContractRef の制約に従う。
    S/A は wire schema であり能力として再帰登録しない。条件名や登録だけを認証にしない。
    意味宣言欠落 FSpecificationMissing(missing_contract)、実装欠落 FIncomplete(algorithm_unavailable)、
    返り値不正 FInputError(capability_output_shape)。method と proof を分ける。"""
    return make_f_registry(declarations=_BUILTIN_DECLARATIONS,
        implementations=tuple(_replace(i, implementation=_builtin_dispatch(i.kind, i.ref))
                              for i in _BUILTIN_IMPLEMENTATIONS))


def canonical_action(action: ActionSpec, *, registry: FRegistry) -> ActionSpec:
    """F-a で族の正準化・別名証明を検査し semantic_key を確定する。
    sha256 対象は family,args,start,policy,termination,termination_kind,prediction,execution。
    id・semantic_key 自身・proof は含めない。誤った自己申告は FInputError(semantic_key_mismatch)。
    意味不足 FSpecificationMissing、証明能力不足 FIncomplete。"""
    _require(registry, FRegistry)
    if type(action) is not ActionSpec:
        raise FInputError("shape", field="action")
    action = _decode(_encode(action), ActionSpec)
    output = _call_capability("action", _ContractRef(action.family.name, action.family.version),
        args=action.args, input=_encode(action), registry=registry)
    output = _decode(output, ActionSpec)
    material = {f.name: getattr(output, f.name) for f in _fields(ActionSpec)
                if f.name not in ("id", "semantic_key", "proof")}
    key = _digest(material)
    if action.semantic_key != key:
        raise FInputError("semantic_key_mismatch", field="action/semantic_key")
    return _replace(output, semantic_key=key)


def apply_f_observation(model: FModel | FFiniteUpdateModel, belief: FiniteBelief, *,
                        observation: FiniteObservation) -> FiniteBelief:
    """F-a で raw から検査した観測の outcome 核の和を一回だけ適用する。
    同 transition_key と入力 digest は no-op、異なる入力は FInputError(measurement_conflict)。
    手作りハンドルを信用しない。不一致 FInputError(observation_binding_mismatch)、
    意味不足 FSpecificationMissing、能力不足 FIncomplete、質量0 FModelFalsified(zero_evidence)。
    v0.14のFFiniteUpdateModelは発行元のモデルPointへ照合する。FModel互換計算は保持。
    新経路でも同じ証拠セルの核を合算して一度だけ条件づける契約。
    """
    if isinstance(model, FFiniteUpdateModel):
        from ._f_handles import require_issued
        authority = require_issued(model, FFiniteUpdateModel)
        observation_resources = require_issued(observation, FiniteObservation)
        from ._f_identity import point
        own = point(authority.resources.preference_ledger,authority.source)[2]
        try:
            other = point(observation_resources.preference_ledger,authority.source)[2]
        except FReplayUnavailable as exc:
            raise FInputError('observation_binding_mismatch') from exc
        if own != other:
            raise FInputError('observation_binding_mismatch')
        model = authority.model
    from ._f_handles import require_issued
    resources = require_issued(observation, FiniteObservation)
    if observation.model_ref != belief.model_ref:
        raise FInputError("observation_binding_mismatch")
    from .f_entry import f_from_json, read_f_observations
    from .f_contracts import OBSERVATION_BINDING
    record = next(r for r in resources.records if r.id == observation.binding)
    binding = f_from_json(record.body.content.data, contract=OBSERVATION_BINDING)
    if binding.derived_from:
        incorporated = {m for a in belief.applied for m in a.measurements}
        if not set(binding.derived_from) <= incorporated:
            originals = read_f_observations(model, resources.records, resources=resources)
            for original in originals:
                if original.binding != observation.binding and set(original.measurements) & set(binding.derived_from):
                    source_record = next(r for r in resources.records if r.id == original.binding)
                    source_binding = f_from_json(source_record.body.content.data, contract=OBSERVATION_BINDING)
                    if source_binding.derived_from:
                        raise FIncomplete("certificate_incomplete", "derived chain needs a provenance proof")
                    belief = apply_f_observation(model, belief, observation=original)
            incorporated = {m for a in belief.applied for m in a.measurements}
            if not set(binding.derived_from) <= incorporated:
                raise FIncomplete("certificate_incomplete", "derived measurement has no verified original")
        return belief
    return _update_joint(model, belief, kernel=observation.kernel, outcomes=observation.outcomes,
        measurements=observation.measurements, transition_key=observation.transition_key)


def enumerate_f_prefix(root: FRoot, *, steps: int, budget: RateBudget) -> FPathTable:
    from ._f_eval import enumerate_f_prefix as invoke
    from ._f_handles import trace_math
    return trace_math(invoke(root,steps=steps,budget=budget),'prefix',inputs={'root_step':root},args={'steps':steps,'budget':budget})


def check_f_measure_partition(measure: CandidateMeasureRef, *,
                              partition: MeasurePartition) -> MeasureCheck:
    """F-a で counting/混合測度の原子・一様区間セルを厳密 Fraction で積分する。
    完全で交わらない分割、非負有限質量を検査。不正入力 FInputError、
    意味不足 FSpecificationMissing、能力不足 FIncomplete。任意 J の Z や連続選択は認証しない。"""
    measure = _decode(_encode(measure), CandidateMeasureRef)
    partition = _decode(_encode(partition), MeasurePartition)
    if measure.version != "1":
        raise FInputError("unknown_version")
    if measure.name == "counting":
        _keys(measure.args, ())
        _unique(partition.atoms)
        if partition.cells:
            raise FInputError("shape", "counting measure has no continuous cells")
        return MeasureCheck(measure=measure, partition=partition,
            atom_masses=tuple(AtomMass(id=name, mass=_Fraction(1)) for name in partition.atoms),
            cell_masses=(), total=_Fraction(len(partition.atoms)))
    if measure.name != "mixed":
        raise FIncomplete("certificate_incomplete", "partition needs an explicit mixed measure")
    _keys(measure.args, ("atoms", "continuous"))
    atoms, continuous = {}, {}
    for atom in measure.args["atoms"]:
        _keys(atom, ("id", "mass"))
        mass = _decode(atom["mass"], _Fraction)
        if atom["id"] in atoms or mass < 0:
            raise FInputError("shape", "invalid atom")
        atoms[atom["id"]] = mass
    for component in measure.args["continuous"]:
        _keys(component, ("id", "variable", "unit", "distribution", "mass", "prediction"))
        distribution = component["distribution"]
        _keys(distribution, ("name", "version", "args"))
        if distribution["name"] != "uniform_interval" or distribution["version"] != "1":
            raise FSpecificationMissing("missing_contract")
        _keys(distribution["args"], ("lower", "upper"))
        low, high = (_decode(distribution["args"][k], _Fraction) for k in ("lower", "upper"))
        mass = _decode(component["mass"], _Fraction)
        _decode(component["prediction"], KernelRef)
        if component["id"] in continuous or component["id"] in atoms or low >= high or mass < 0:
            raise FInputError("shape", "invalid continuous component")
        continuous[component["id"]] = low, high, mass
    _unique(partition.atoms)
    if set(partition.atoms) != set(atoms):
        raise FInputError("shape", "atom partition incomplete")
    cell_masses = []
    for cell in partition.cells:
        if cell.component not in continuous or cell.lower >= cell.upper:
            raise FInputError("shape", "invalid cell")
        low, high, mass = continuous[cell.component]
        if not low <= cell.lower < cell.upper <= high:
            raise FInputError("shape", "cell outside distribution")
        cell_masses.append(mass * (cell.upper-cell.lower)/(high-low))
    for name, (low, high, _) in continuous.items():
        cells = sorted((c for c in partition.cells if c.component == name), key=lambda c: c.lower)
        if not cells or cells[0].lower != low or cells[-1].upper != high or any(a.upper != b.lower for a, b in zip(cells, cells[1:])):
            raise FInputError("shape", "cell partition overlaps or has gaps")
    atom_masses = tuple(AtomMass(id=name, mass=atoms[name]) for name in partition.atoms)
    return MeasureCheck(measure=measure, partition=partition, atom_masses=atom_masses,
        cell_masses=tuple(cell_masses), total=sum(atoms.values()) + sum(cell_masses))


def limit_problem_from_json(data: bytes) -> FLimitProblem:
    """F-a で負の極限診断の正準宣言を構造検査して返す。
    schema/shape/noncanonical/rational/unknown_version は FInputError。
    proof の真偽は certify_f_limit で検査。型の外は FOutsideEvaluationType。
    §3-10-13-1 により f.py で定義し f_entry でも同一関数を再公開する。
    """
    raw = _load_json(data)
    _keys(raw,(f.name for f in _fields(FLimitProblem)))
    for key in ("process","observations","scope"):
        if isinstance(raw[key],_Mapping) and type(raw[key].get("version")) is str and raw[key]["version"] != "1":
            raise FInputError("unknown_version",field="/"+key+"/version")
    problem = _decode(raw, FLimitProblem)
    if problem.observations.args:
        raise FInputError("shape", field="/observations/args")
    if isinstance(problem.cost, PrefixLogLoss) and problem.cost.law != problem.process:
        raise FInputError("proof_mismatch", "cost law differs from process", "/cost/law")
    return problem


def certify_f_limit(problem: FLimitProblem, *, budget: RateBudget) -> LimitCertificate:
    """F-a で iid_bits_limit/1 の独立公平ビットと情報/費用の極限を別々に検査する。
    成功は負の診断の証明であり Selected ではない。誤証明 FInputError(proof_mismatch)、
    proof=None/検査器不足 FIncomplete(certificate_incomplete)、予算切れ FIncomplete(budget_exhausted)。"""
    problem = limit_problem_from_json(_dumps(problem))
    proof = problem.proof
    if proof is None or (proof.name, proof.version) != ("iid_bits_limit", "1"):
        raise FIncomplete("certificate_incomplete", "independent fair-bit limit checker unavailable")
    _keys(proof.args, ("process_digest", "information_slope", "cost_slope"), "/proof/args")
    ln2, zero = _log(_Fraction(2)), _r(0)
    cost_slope = ln2 if isinstance(problem.cost, PrefixLogLoss) else zero
    expected = {"process_digest": limit_process_digest(problem.process),
        "information_slope": _encode(ln2), "cost_slope": _encode(cost_slope)}
    if _dumps(proof.args) != _dumps(expected):
        raise FInputError("proof_mismatch", "process or prefix slopes do not match the declared law")
    _quantity(ln2, budget)
    key = _digest({f.name: getattr(problem, f.name) for f in _fields(FLimitProblem) if f.name != "proof"})
    return LimitCertificate(problem_key=key, checker=_ContractRef(proof.name, proof.version),
        information=LimitInformation(prefix=ExactSequence(name="linear", version="1", args=LinearSequenceArgs(slope=ln2, intercept=zero)), bound="diverges"),
        cost=LimitCost(prefix=ExactSequence(name="linear", version="1", args=LinearSequenceArgs(slope=cost_slope, intercept=zero)),
                      bound="diverges" if isinstance(problem.cost, PrefixLogLoss) else "zero"),
        conclusion="undefined_infinite_difference" if isinstance(problem.cost, PrefixLogLoss) else "information_divergent")


def diagnose_f_limit(problem: FLimitProblem, *, budget: RateBudget) -> NoDecision:
    """F-a で負の極限を NoDecision(attempt_id=None) として返す。
    情報発散は information_divergent、無限差は undefined_infinite_difference。
    証明不足は incomplete/certificate_incomplete。誤証明・形不正は FInputError のまま。
    §3-10-5 により発散診断の outcome は rejected とする。"""
    try:
        certificate = certify_f_limit(problem, budget=budget)
    except FIncomplete as exc:
        return NoDecision(attempt_id=None, root_key=None, outcome="incomplete", reason=exc.reason,
            detail=exc.detail, field=exc.field, proof=None, progress=None, resume=None)
    return NoDecision(attempt_id=None, root_key=None, outcome="rejected", reason=certificate.conclusion,
        detail="", field=None, proof=problem.proof, progress=None, resume=None)



def check_f_preflight(request: FPreflight, *,
                      resources: FResources) -> PreflightReady | NoDecision:
    """F-a で固定 resources のモデル/記録/能力の存在・実装を検査する。
    未取得は incomplete/prerequisite_unavailable、宣言なし rejected/missing_contract、
    実装なし incomplete/algorithm_unavailable。成功は PreflightReady、根や Selected は作らない。
    主理由はモデル、Ref 辞書順、kind/name/version 順、不足全件を証明へ残す。
    形不正 FInputError。任意ホスト故障を数学理由へ変換しない。"""
    return _preflight_result(_preflight_input(request, resources))


def limit_process_digest(process: LimitProcess) -> str:
    """F-a で process の name/version/args だけの正準 UTF-8 JSON を SHA-256 にする。
    ensure_ascii=False、キー整列、空白なし、allow_nan=False。sha256: + 小文字16進。
    公平ビットの対象 bytes は {"args":{"index_origin":0},"name":"iid_fair_bits","version":"1"}。
    VALUE/proof/cost/改行/BOM を含めない。形不正 FInputError(shape)。
    一致しても観測/費用/範囲の検査を省かず、proof の不一致は FInputError(proof_mismatch)。"""
    process = _decode(_encode(process), LimitProcess)
    return _digest(process)


def _preflight_input(request, resources):
    from .f_entry import PreflightInput, PreflightAvailability, RecordAvailability, CapabilityAvailability
    models = _require(resources, FResources)
    request = _decode(_encode(request), FPreflight)
    _unique(request.required_records, "required_records")
    _unique(tuple((c.kind, c.ref) for c in request.required_capabilities), "required_capabilities")
    present = {r.id for r in resources.records}
    from ._f_identity import resource_bindings
    resource_bindings(resources,tuple(ref for ref in request.required_records if ref in present))
    declared = {(d.kind, d.ref) for d in resources.registry.declarations}
    implemented = {(i.kind, i.ref) for i in resources.registry.implementations}
    return PreflightInput(request=request, availability=PreflightAvailability(
        model_present=None if request.model_ref is None else request.model_ref in models,
        records=tuple(RecordAvailability(ref=r, present=r in present) for r in sorted(request.required_records, key=str)),
        capabilities=tuple(CapabilityAvailability(kind=c.kind, ref=c.ref, declared=(c.kind,c.ref) in declared,
            implemented=(c.kind,c.ref) in implemented) for c in sorted(request.required_capabilities, key=lambda c:(c.kind,c.ref.name,c.ref.version)))))


def _preflight_result(input):
    availability, request = input.availability, input.request
    failures = []
    if availability.model_present is False:
        failures.append(("incomplete", "prerequisite_unavailable", "/model_ref"))
    failures.extend(("incomplete", "prerequisite_unavailable", "/required_records") for r in availability.records if not r.present)
    required = {(c.kind,c.ref):c.implementation_required for c in request.required_capabilities}
    for cap in availability.capabilities:
        if not cap.declared:
            failures.append(("rejected", "missing_contract", "/required_capabilities"))
        elif required[cap.kind,cap.ref] and not cap.implemented:
            failures.append(("incomplete", "algorithm_unavailable", "/required_capabilities"))
    if not failures:
        return PreflightReady(input_key=_digest(input))
    outcome, reason, field = failures[0]
    return NoDecision(attempt_id=None, root_key=None, outcome=outcome, reason=reason,
        detail="", field=field, proof=None, progress=None, resume=None)


# Private structural layer. It never imports a class named by input JSON.
import hashlib as _hashlib
import json as _json
import math as _math
import types as _types
import typing as _typing
from dataclasses import fields as _fields, is_dataclass as _is_dataclass, replace as _replace
from types import MappingProxyType as _MappingProxyType
from .ids import RefKind as _RefKind

_ISSUER = object()


def _handle(cls, *, authority=None, **values):
    obj = object.__new__(cls)
    for field in _fields(cls):
        object.__setattr__(obj, field.name, values[field.name])
    object.__setattr__(obj, "_authority", (_ISSUER, authority))
    return obj


def _require(obj, cls):
    if type(obj) is not cls or getattr(obj, "_authority", (None,))[0] is not _ISSUER:
        raise FInputError("shape", "factory-issued " + cls.__name__ + " required")
    return obj._authority[1]


def _keys(value, names, field=""):
    names = tuple(names)
    if not isinstance(value, _Mapping) or set(value) != set(names):
        # 今の約束 A-20/A-21: point at the first missing or extra key.
        odd = sorted(set(value) ^ set(names)) if isinstance(value, _Mapping) else ()
        key = str(odd[0]).replace("~", "~0").replace("/", "~1") if odd else None
        raise FInputError("shape", "expected keys " + ",".join(names),
                          field if key is None else field + "/" + key)


def _array(value, field=""):
    if not isinstance(value, (list, tuple)):
        raise FInputError("shape", "array required", field)


def _unique(values, field="", *, nonempty=False):
    if len(set(values)) != len(values) or (nonempty and not values) or any(type(v) is str and not v for v in values):
        raise FInputError("shape", "nonempty unique values required", field)


def _freeze(value):
    if isinstance(value, _Mapping):
        if any(type(k) is not str for k in value):
            raise FInputError("shape", "JSON keys must be strings")
        return _MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and _math.isfinite(value):
        return value
    raise FInputError("shape", "finite immutable JSON required")


def _load_json(data):
    if type(data) is not bytes:
        raise FInputError("shape", "bytes required")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise FInputError("schema", "duplicate key", "/" + k)
            result[k] = v
        return result
    def invalid(_):
        raise FInputError("schema", "nonfinite JSON")
    try:
        value = _json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, FInputError):
            raise
        raise FInputError("schema", str(exc)) from exc
    if _dumps(value) != data:
        raise FInputError("noncanonical", "canonical UTF-8 JSON required")
    return value


def _tag(value):
    tags = {ClockReading: "clock", Unavailable: "unavailable", At: "at", When: "when",
            Selected: "selected", NoDecision: "no_decision", CoverageClaim: "claim",
            Gap: "gap", MeasurementUnavailable: "measurement_unavailable",
            CoverageUnproved: "coverage_unproved", FRoot: "root", FPreflight: "preflight",
            FLimitProblem: "limit"}
    return tags.get(type(value), "available")


def _encode(value):
    from enum import Enum
    from .records import Record
    if isinstance(value, Enum):
        return value.value
    if type(value) is bytes:
        return list(value)
    if isinstance(value, _Ref):
        return str(value)
    if isinstance(value, _Fraction):
        return [value.numerator, value.denominator]
    if isinstance(value, FQuantityDefinition):
        names = {"evaluation": ("root_key", "field", "candidate"),
                 "rational_constant": ("value", "unit", "provenance")}
        if value.kind not in names:
            raise FInputError("shape", field="/kind")
        used = names[value.kind]
        if any(getattr(value, f.name) is not None for f in _fields(value) if f.name not in ("kind", *used)):
            raise FInputError("quantity_binding_conflict", "extraneous definition field")
        return {"kind":value.kind, **{k:_encode(getattr(value,k)) for k in used}}
    if isinstance(value, ExactReal):
        fields = {"rational": ("value",), "log": ("arg",), "exp": ("arg",),
                  "neg": ("arg",), "add": ("args",), "mul": ("args",),
                  "div": ("numerator", "denominator")}
        if value.op not in fields:
            raise FInputError("shape", "unknown ExactReal op")
        used = fields[value.op]
        if any(getattr(value, k) is not None for k in ("value", "arg", "args", "numerator", "denominator") if k not in used):
            raise FInputError("shape", "extraneous ExactReal argument")
        return {"op": value.op, **{k: _encode(getattr(value, k)) for k in used}}
    if _is_dataclass(value):
        if isinstance(value, Run):
            raise FIncomplete("certificate_incomplete", "Run columns contract is deferred to F-b")
        result = {f.name: _encode(getattr(value, f.name)) for f in _fields(value)}
        if isinstance(value, Record):
            result["body"] = {"type": type(value.body).__name__, "value": _encode(value.body)}
        hints = _typing.get_type_hints(type(value))
        for field in _fields(value):
            item, hint = getattr(value, field.name), hints[field.name]
            if _typing.get_origin(hint) in (dict, _Mapping) and not isinstance(item, _Mapping):
                raise FInputError("shape", "Mapping required", field.name)
            if _typing.get_origin(hint) in (dict, _Mapping) and _typing.get_args(hint)[0] is not str and not item:
                result[field.name] = []
            types = _typing.get_args(hint)
            if item is None:
                continue
            if type(value) is MeasurementFrame and field.name == "value":
                result[field.name] = {"kind": "unavailable" if isinstance(item, Unavailable) else "value", "value": _encode(item)}
            elif (Unavailable in types and len(types) > 1) or (At in types and When in types) or (Selected in types and NoDecision in types):
                result[field.name] = {"kind": _tag(item), "value": _encode(item)}
        return result
    if isinstance(value, _Mapping):
        if any(not isinstance(k, str) for k in value):
            return [{"key": _encode(k), "value": _encode(v)} for k, v in sorted(value.items(), key=lambda p: _dumps(p[0]))]
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_encode(v) for v in value), key=_dumps)
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if value is None or type(value) in (str, int, bool) or (type(value) is float and _math.isfinite(value)):
        return value
    raise FInputError("shape", "unsupported JSON value")


def _dumps(value):
    try:
        return _json.dumps(_encode(value), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        if isinstance(exc, FInputError):
            raise
        raise FInputError("schema", str(exc)) from exc


def _digest(value):
    return "sha256:" + _hashlib.sha256(_dumps(value)).hexdigest()


def _decode(value, typ, field=""):
    from enum import Enum
    from .records import Record, BODY_KIND
    if typ is FQuantityDefinition:
        if not isinstance(value, _Mapping) or value.get("kind") not in ("evaluation", "rational_constant"):
            raise FInputError("shape", field=field)
        types = {"root_key":str,"field":_Literal["expected_cost","already_received","additional","total_information","G","J","q_star","Z"],
            "candidate":str | None,"value":_Fraction,"unit":_Literal["nat","dimensionless"],"provenance":tuple[_Ref,...]}
        names = ("root_key","field","candidate") if value["kind"] == "evaluation" else ("value","unit","provenance")
        _keys(value,("kind",*names),field)
        return FQuantityDefinition(kind=value["kind"],**{k:_decode(value[k],types[k],field+"/"+k) for k in names})
    if isinstance(typ, type) and issubclass(typ, Enum):
        if type(value) is not str:
            raise FInputError("shape", field=field)
        try:
            return typ(value)
        except ValueError as exc:
            raise FInputError("shape", "unknown enum value", field) from exc
    if typ is bytes:
        _array(value, field)
        if any(type(v) is not int or not 0 <= v <= 255 for v in value):
            raise FInputError("shape", "byte array required", field)
        return bytes(value)
    if typ == ImmutableJSON:
        return _freeze(value)
    origin, args = _typing.get_origin(typ), _typing.get_args(typ)
    if origin in (_typing.Union, _types.UnionType) and {str, int, float, bool, type(None)} <= set(args) and not any(_is_dataclass(t) for t in args):
        return _freeze(value)
    if typ is type(None):
        if value is not None:
            raise FInputError("shape", "null required", field)
        return None
    if origin is _Literal:
        if value not in args or type(value) not in {type(a) for a in args}:
            raise FInputError("shape", "unknown discriminator", field)
        return value
    if origin in (_typing.Union, _types.UnionType):
        if value is None and type(None) in args:
            return None
        # A non-null continuation policy has exactly one alternative. Preserve
        # its diagnostic instead of masking unknown_version as a union shape.
        if set(args) == {PolicyRef, type(None)}:
            return _decode(value, PolicyRef, field)
        tag_union = (Unavailable in args and len(args) > 1) or (At in args and When in args) or (Selected in args and NoDecision in args) or (FRoot in args and FPreflight in args)
        if tag_union:
            _keys(value, ("kind", "value"), field)
            tag = value["kind"]
            for t in args:
                if t is type(None):
                    continue
                expected = {ClockReading: "clock", Unavailable: "unavailable", At: "at", When: "when", Selected: "selected", NoDecision: "no_decision", FRoot: "root", FPreflight: "preflight", FLimitProblem: "limit"}.get(t, "available")
                if tag == expected:
                    return _decode(value["value"], t, field + "/value")
            raise FInputError("shape", "unknown union tag", field)
        for t in args:
            if _is_dataclass(t) and isinstance(value, _Mapping):
                literal = _typing.get_type_hints(t).get("kind")
                if _typing.get_origin(literal) is _Literal and value.get("kind") in _typing.get_args(literal):
                    return _decode(value, t, field)
        for t in args:
            try:
                return _decode(value, t, field)
            except FInputError:
                pass
        raise FInputError("shape", "no union alternative", field)
    if typ is _Fraction:
        _array(value, field)
        if len(value) != 2 or any(type(v) is not int for v in value):
            raise FInputError("shape", "R needs two integers", field)
        n, d = value
        if d <= 0 or _math.gcd(n, d) != 1:
            raise FInputError("rational", "reduced R with positive denominator required", field)
        return _Fraction(n, d)
    if typ is _Ref:
        if type(value) is not str or ":" not in value:
            raise FInputError("shape", "Ref required", field)
        kind, text = value.split(":", 1)
        try:
            return _Ref(_RefKind(kind), text)
        except (ValueError, TypeError) as exc:
            raise FInputError("shape", str(exc), field) from exc
    if typ in (str, int, float, bool):
        if type(value) is not typ or (typ is float and not _math.isfinite(value)):
            raise FInputError("shape", typ.__name__ + " required", field)
        return value
    if origin in (tuple, frozenset):
        _array(value, field)
        if len(args) == 2 and args[1] is Ellipsis:
            types = [args[0]] * len(value)
        elif origin is frozenset:
            types = [args[0]] * len(value)
        else:
            if len(args) != len(value):
                raise FInputError("shape", "tuple length", field)
            types = args
        items = tuple(_decode(v, t, field + "/" + str(i)) for i, (v, t) in enumerate(zip(value, types)))
        if origin is frozenset:
            _unique(items, field)
            if list(value) != sorted(value, key=_dumps):
                raise FInputError("noncanonical", "set order", field)
            return frozenset(items)
        return items
    if origin in (dict, _Mapping):
        kt, vt = args
        if kt is str:
            if not isinstance(value, _Mapping):
                raise FInputError("shape", "mapping required", field)
            return _MappingProxyType({k: _decode(v, vt, field + "/" + k) for k, v in value.items()})
        _array(value, field)
        result, previous = {}, None
        for i, pair in enumerate(value):
            _keys(pair, ("key", "value"), field)
            k = _decode(pair["key"], kt, field + f"/{i}/key")
            encoded = _dumps(k)
            if previous is not None and encoded <= previous:
                raise FInputError("shape", "mapping keys must be unique and sorted", field)
            result[k] = _decode(pair["value"], vt, field + f"/{i}/value")
            previous = encoded
        return _MappingProxyType(result)
    if typ is ExactReal:
        if not isinstance(value, _Mapping) or "op" not in value:
            raise FInputError("shape", field=field)
        op = value["op"]
        names = {"rational": ("value",), "log": ("arg",), "exp": ("arg",), "neg": ("arg",), "add": ("args",), "mul": ("args",), "div": ("numerator", "denominator")}
        if op not in names:
            raise FInputError("shape", field=field)
        _keys(value, ("op",) + names[op], field)
        hints = _typing.get_type_hints(ExactReal)
        out = ExactReal(op=op, **{k: _decode(value[k], _typing.get_args(hints[k])[0], field + "/" + k) for k in names[op]})
        if op in ("add", "mul") and not out.args:
            raise FInputError("shape", "nonempty expression", field)
        if op == "log" and out.arg.op == "rational" and out.arg.value <= 0:
            raise FInputError("shape", "log requires a positive argument", field)
        if op == "div" and out.denominator.op == "rational" and out.denominator.value == 0:
            raise FInputError("shape", "zero denominator", field)
        return out
    if _is_dataclass(typ):
        _keys(value, (f.name for f in _fields(typ)), field)
        hints = _typing.get_type_hints(typ)
        values = {}
        for fld in _fields(typ):
            raw = value[fld.name]
            if typ is Record and fld.name == "body":
                _keys(raw, ("type", "value"), field + "/body")
                bodies = {t.__name__:t for t in BODY_KIND}
                if raw["type"] not in bodies:
                    raise FInputError("shape", "unknown record body", field + "/body")
                values[fld.name] = _decode(raw["value"], bodies[raw["type"]], field + "/body/value")
            elif typ is MeasurementFrame and fld.name == "value":
                _keys(raw, ("kind", "value"), field + "/value")
                if raw["kind"] not in ("value", "unavailable"):
                    raise FInputError("shape", field=field + "/value")
                values[fld.name] = _decode(raw["value"], Unavailable if raw["kind"] == "unavailable" else ImmutableJSON, field + "/value/value")
            else:
                values[fld.name] = _decode(raw, hints[fld.name], field + "/" + fld.name)
        try:
            if issubclass(typ, _FactoryHandle):
                obj = object.__new__(typ)
                for k, v in values.items():
                    object.__setattr__(obj, k, v)
            else:
                obj = typ(**values)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, FInputError):
                raise
            raise FInputError("shape", str(exc), field) from exc
        _validate_structure(obj, field)
        return obj
    raise FInputError("shape", "unsupported wire type", field)


def _validate_structure(value, field=""):
    if isinstance(value, CandidateSet):
        names = tuple(a.id for a in value.candidates)
        _unique(names, field + "/candidates/id", nonempty=True)
        _unique(tuple(a.semantic_key for a in value.candidates), field + "/candidates/semantic_key")
        if set(value.aliases) & set(names) or not set(value.aliases.values()) <= set(names):
            raise FInputError("shape", "aliases must refer to distinct representatives", field + "/aliases")
    if isinstance(value, (PredicateRef, KernelRef, PolicyRef, ActionFamilyRef)) and value.name in {"finite_kernel", "finite_policy", "finite_option", "constant", "policy_end", "fact_present", "interval_compare", "and", "or", "not"} and value.version != "1":
        raise FInputError("unknown_version", field=field + "/version")
    if isinstance(value, (KernelRef, PolicyRef)) and value.name in ("finite_kernel", "finite_policy"):
        _keys(value.args, ("id",), field + "/args")
    if isinstance(value, PredicateRef):
        _predicate_args(value, field)
    for name in ("elapsed_ns", "sample_seq", "step", "ordinal", "reply_index"):
        if hasattr(value, name) and getattr(value, name) < 0:
            raise FInputError("unit" if name == "elapsed_ns" else "shape", field=field + "/" + name)
    if isinstance(value, (EvaluationScope, StyleScope, LimitScope)):
        if value.version != "1":
            raise FInputError("unknown_version", field=field + "/version")
        if (value.name == "finite_horizon" and (type(value.H_ns) is not int or value.H_ns < 0)) or (value.name != "finite_horizon" and value.H_ns is not None):
            raise FInputError("shape", field=field + "/H_ns")
    if isinstance(value, MeasurementInterval):
        if value.clock.kind is not _RefKind.RUN or value.start_ns > value.end_ns:
            raise FInputError("shape", field=field)
    if isinstance(value, ClockReading) and value.run.kind is not _RefKind.RUN:
        raise FInputError("shape", field=field + "/run")
    if isinstance(value, FQuantity):
        if value.status == "finite" and value.exact is None and value.bounds is None:
            raise FInputError("shape", field=field)
        if value.status != "finite" and (value.exact is not None or value.bounds is not None):
            raise FInputError("shape", field=field)


def _predicate_args(predicate, field="predicate"):
    shapes = {"constant": ("value",), "policy_end": (), "fact_present": ("fact", "history"),
              "interval_compare": ("left", "relation", "right", "provenance"), "and": ("terms",), "or": ("terms",), "not": ("term",)}
    if predicate.name not in shapes:
        return
    _keys(predicate.args, shapes[predicate.name], field + "/args")
    a = predicate.args
    if predicate.name == "constant":
        _decode(a["value"], bool, field)
    elif predicate.name == "fact_present":
        _decode(a["fact"], _Ref, field)
        _decode(a["history"], _Literal["E", "K"], field)
    elif predicate.name == "interval_compare":
        _decode(a["left"], QuantityRef, field)
        _decode(a["right"], QuantityRef, field)
        _decode(a["relation"], _Literal["lt", "le", "eq"], field)
        _decode(a["provenance"], tuple[_Ref, ...], field)
    elif predicate.name in ("and", "or"):
        terms = _decode(a["terms"], tuple[PredicateRef, ...], field)
        if not terms:
            raise FInputError("shape", field=field)
    elif predicate.name == "not":
        _decode(a["term"], PredicateRef, field)


def _schema_check(ref, raw):
    changed = {'sui.f.schema.' + name for name in ('f_root','f_problem','f_evaluation',
        'tail_input','evaluation_input','computation_input','selected','f_decision_content',
        'f_result_context','firing_state','c1_count_frame')}
    if ref.version != ('2' if ref.name in changed else '1'):
        raise FInputError("unknown_version")
    if ref.name.startswith("sui.f.schema."):
        import re
        from .f_entry import _wire_types
        _, types = _wire_types()
        types.update({"RateBudget": RateBudget, "RationalInterval": RationalInterval})
        for name, typ in types.items():
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
            if ref.name == "sui.f.schema." + snake:
                _decode(raw, typ)
                return
        raise FSpecificationMissing("missing_contract", "unknown schema " + ref.name)
    if ref.name.startswith("sui.f.args."):
        name = ref.name.rsplit(".", 1)[-1]
        if name == "empty":
            _keys(raw, ())
        elif name in ("id", "operation"):
            _keys(raw, (name,))
            _decode(raw[name], str)
        elif name == "finite_option":
            _keys(raw, ("opportunity", "path_action"))
            _freeze(raw["opportunity"])
            _decode(raw["path_action"], str | None)
        elif name in ("terms", "term", "constant", "fact_present", "interval_compare"):
            pred = {"terms": "and", "term": "not"}.get(name, name)
            _predicate_args(PredicateRef(name=pred, version="1", args=raw))
        elif name == "iid_bits_limit":
            _keys(raw, ("process_digest", "information_slope", "cost_slope"))
            _decode(raw["process_digest"], str)
            _decode(raw["information_slope"], ExactReal)
            _decode(raw["cost_slope"], ExactReal)
        else:
            raise FSpecificationMissing("missing_contract", "unknown args schema")
        return
    raise FSpecificationMissing("missing_contract", "wire schema not declared")


def _call_capability(kind, ref, *, args, input, registry, resources=None, model_ref=None, budget=None, cached_quantities=None):
    _require(registry, FRegistry)
    declaration = next((d for d in registry.declarations if d.kind == kind and d.ref == ref), None)
    if declaration is None:
        if any(d.kind == kind and d.ref.name == ref.name for d in registry.declarations):
            raise FInputError("unknown_version")
        raise FSpecificationMissing("missing_contract", ref.name)
    implementation = next((i for i in registry.implementations if i.kind == kind and i.ref == ref), None)
    if implementation is None:
        raise FIncomplete("algorithm_unavailable", ref.name)
    _schema_check(declaration.args_contract, args)
    _schema_check(declaration.input_contract, input)
    result = implementation.implementation(args=_freeze(args), input=_freeze(input),
        context=CapabilityContext(registry=registry, resources=resources, model_ref=model_ref, budget=budget, cached_quantities=cached_quantities))
    try:
        _schema_check(declaration.output_contract, result)
    except FInputError as exc:
        raise FInputError("capability_output_shape", exc.detail, exc.field) from exc
    return _freeze(result)


def _resource_model(resources, key):
    from .f_model import f_model_ref
    from .rate_model import rate_model_ref
    index = _require(resources, FResources)
    if isinstance(index, _Mapping):
        if key in index:
            return index[key]
        raise FReplayUnavailable("missing_input", "model " + str(key))
    for model in resources.models:
        ref = f_model_ref(model) if isinstance(model, FModel) else rate_model_ref(model)
        if ref == key:
            return model
    raise FReplayUnavailable("missing_input", "model " + str(key))


def _builtin_dispatch(kind, ref):
    def invoke(*, args, input, context):
        name = ref.name
        if kind == "action":
            return input
        if kind == "predicate":
            snapshot = _decode(input, PredicateSnapshot)
            if context.cached_quantities is not None:
                snapshot = _replace(snapshot, quantities=context.cached_quantities)
            return _encode(_builtin_predicate(name, args, snapshot, context.resources))
        if kind in ("kernel", "policy"):
            from .f_model import _parts
            model = _resource_model(context.resources, input["model_ref"])
            _, kernels, policies, _ = _parts(model)
            values = kernels if kind == "kernel" else policies
            if args["id"] not in values:
                raise FInputError("unresolved_reference")
            return _encode(values[args["id"]])
        if kind == "execution":
            action = _decode(input, ActionSpec)
            return _encode(SimulationBinding(operation=action.id, policy=action.policy, prediction=action.prediction))
        if kind == "generation":
            value = _decode(input, GenerationInput)
            binding = value.binding
            return _encode(GenerationOutput(transition_key=_digest({"plan": binding.plan,
                "opportunity": binding.opportunity, "step": binding.step}), slots=binding.slots))
        if kind == "quality":
            value = _decode(input, ContractValue)
            if value.value != "measured":
                raise FInputError("shape", "quality must be measured")
            return input
        if kind == "cursor":
            value = _decode(input, CursorInput)
            if type(value.cursor.value) is not int or value.cursor.value != value.sample_seq or value.sample_seq < 0:
                raise FInputError("shape", "cursor mismatch")
            return _encode(value.cursor)
        if kind == "clock":
            value = _decode(input, ClockInput)
            _check_clock(value.reading, value.interval)
            return _encode(value.reading)
        if kind == "generator":
            return input
        if kind in ("measurement", "projection"):
            from .f_entry import _observation_value
            value = _decode(input, ObservationInput)
            return _encode(_observation_value(value.plan, value.binding, context.resources))
        if kind == "arithmetic":
            value = context.numeric_input if context.numeric_input is not None else _decode(input, EnclosureInput)
            return _encode(_quantity(value.expression, context.budget, work=context.numeric_work))
        if kind == "choice":
            value = context.numeric_input if context.numeric_input is not None else _decode(input, ChoiceInput)
            return _encode(_soft_choice(value.J, value.masses, value.gamma, context.budget, work=context.numeric_work))
        if kind == "method":
            if context.certified_input is not None:
                value = context.certified_input
                root = value.root
                from ._f_handles import world_state
                if world_state(root) is not context.resources:
                    raise FInputError('proof_mismatch', 'different certified world')
            else:
                # M-19 / C-05: the evaluator has no raw resolver; roots arrive certified.
                raise FInputError('proof_mismatch', 'uncertified root input')
            from ._f_eval import _evaluate_recursive_math, _computation_information_math
            if name == "sui.f.computation_information":
                return _encode(_computation_information_math(root, computation=value.computation, budget=context.budget))
            if value.resume is not None and (value.resume.root_key != root.root_key or value.resume.method != root.method):
                raise FReplayMismatch("result_mismatch", fields=("/resume",))
            return _encode(_evaluate_recursive_math(root, context.budget, context.numeric_input))
        if kind == "proof" and name == "finite_option_proof":
            from .f_model import _parts
            model = _resource_model(context.resources, input["model_ref"])
            _, _, policies, operations = _parts(model)
            if args["operation"] not in operations:
                raise FInputError("unresolved_reference")
            _check_option(_types.SimpleNamespace(policies=policies, operations=operations), operations[args["operation"]])
            return _encode(ProofCheck(status="proved", reason=None,
                evidence=(ContractValue(contract=ref, value={"model_ref": input["model_ref"], "operation": args["operation"]}),), missing=()))
        if kind == "proof" and name in ("finite_tree", "fixed_policy_tail", "static_target_entropy_bound", "finite_terminal_cost"):
            if context.certified_input is not None:
                value = context.certified_input
                root = value.root if name == "fixed_policy_tail" else value
                from ._f_handles import world_state
                if world_state(root) is not context.resources:
                    raise FInputError('proof_mismatch', 'different certified world')
            else:
                raise FInputError('proof_mismatch', 'uncertified root input')
            work = _FiniteWork(root, context.budget)
            from ._f_eval import _finite_tree_unchecked
            proved, evidence = True, {"problem_key": root.problem_key}
            if name == "finite_tree":
                proved = _finite_tree_unchecked(work)
            elif name == "fixed_policy_tail":
                from ._f_eval import _certify_tail_unchecked
                tail = _certify_tail_unchecked(root, candidate=value.candidate, prefix=value.prefix, budget=context.budget)
                proved = tail.closure != "unproved"
                evidence["tail"] = _encode(tail)
            elif name == "finite_terminal_cost":
                if root.preferences:
                    if not _finite_tree_unchecked(work):
                        raise FIncomplete("cost_certificate")
                    for candidate in root.candidates.candidates:
                        work.walk(work.state(candidate), candidate.id)
                evidence["preferences"] = _encode(root.preferences)
            else:
                evidence["targets"] = work.targets
            return _encode(ProofCheck(status="proved" if proved else "incomplete",
                reason=None if proved else "certificate_incomplete",
                evidence=(ContractValue(contract=ref, value=evidence),), missing=()))
        if kind == "proof" and name == "iid_bits_limit":
            problem = _decode(input, FLimitProblem)
            problem = _replace(problem, proof=ProofRef(name=ref.name,version=ref.version,args=args))
            return _encode(certify_f_limit(problem,budget=context.budget))
        raise FIncomplete("certificate_incomplete", "checker unavailable: " + name)
    return invoke


def _builtin_predicate(name, args, snapshot, resources):
    basis, missing, value = (), (), "unknown"
    if name == "constant":
        value = "true" if args["value"] else "false"
    elif name == "fact_present":
        fact = _decode(args["fact"], _Ref)
        mids = {l.measurement for l in snapshot.E.links} if args["history"] == "E" else set(snapshot.K.available)
        present = any(fact in link.records for link in snapshot.E.links if link.measurement in mids)
        basis = (fact,) if present else ()
        if present and isinstance(resources, FResources):
            from ._f_identity import resource_bindings
            resource_bindings(resources, basis)
        value = "true" if present else "false"
    elif name == "policy_end":
        if snapshot.model_ref is None or snapshot.policy_position is None:
            missing = (DependencyRef(key="policy_position", basis=()),)
        else:
            if hasattr(resources, "policies"):
                policies = resources.policies
            else:
                from .f_model import _parts
                _, _, policies, _ = _parts(_resource_model(resources, snapshot.model_ref))
            pos = snapshot.policy_position
            if pos.policy not in policies:
                raise FInputError("unresolved_reference", field="snapshot/policy_position/policy")
            node = next((n for n in policies[pos.policy].nodes if n.id == pos.node), None)
            if node is None:
                raise FInputError("unresolved_reference", field="snapshot/policy_position/node")
            value = "true" if isinstance(node, EndNode) else "false"
    elif name == "interval_compare":
        left, right = (_decode(args[k], QuantityRef) for k in ("left", "right"))
        basis = _decode(args["provenance"], tuple[_Ref, ...])
        from ._f_quantity import readable_quantity
        checked = tuple(readable_quantity(k, snapshot) for k in (left,right))
        missing = tuple(DependencyRef(key=k.key, basis=basis) for k,v in zip((left,right),checked) if v is None)
        if not missing and checked[0][1] != checked[1][1]:
            raise FInputError("quantity_binding_conflict", "different units")
        if not missing:
            l, r = snapshot.quantities[left].bounds, snapshot.quantities[right].bounds
            rel = args["relation"]
            if rel == "lt":
                value = "true" if l.upper < r.lower else ("false" if l.lower >= r.upper else "unknown")
            elif rel == "le":
                value = "true" if l.upper <= r.lower else ("false" if l.lower > r.upper else "unknown")
            else:
                value = "true" if l.lower == l.upper == r.lower == r.upper else ("false" if l.upper < r.lower or r.upper < l.lower else "unknown")
            if value == "unknown":
                missing = tuple(DependencyRef(key=k.key, basis=basis) for k in (left, right))
    elif name in ("and", "or", "not"):
        terms = (_decode(args["term"], PredicateRef),) if name == "not" else _decode(args["terms"], tuple[PredicateRef, ...])
        results = tuple(resources.predicate(p, snapshot) if hasattr(resources, "predicate")
            else check_predicate(p, snapshot=snapshot, resources=resources) for p in terms)
        vals = tuple(r.value for r in results)
        if name == "not":
            value = {"true": "false", "false": "true", "unknown": "unknown"}[vals[0]]
        elif name == "and":
            value = "false" if "false" in vals else ("true" if all(v == "true" for v in vals) else "unknown")
        else:
            value = "true" if "true" in vals else ("false" if all(v == "false" for v in vals) else "unknown")
        basis = tuple(sorted({b for r in results for b in r.basis}, key=str))
        if value == "unknown":
            missing = tuple({d.key: d for r in results for d in r.missing}.values())
    return PredicateResult(value=value, basis=basis, missing=missing, work=None)


def _check_clock(reading, interval):
    if reading.run != interval.clock:
        raise FIncomplete("clock_unaligned")
    left = reading.time_ns >= interval.start_ns if interval.closure.startswith("[") else reading.time_ns > interval.start_ns
    right = reading.time_ns <= interval.end_ns if interval.closure.endswith("]") else reading.time_ns < interval.end_ns
    if not left or not right:
        raise FInputError("shape", "actual time outside measurement interval")


def _update_joint(model, belief, *, kernel, outcomes, measurements, transition_key):
    from .f_model import _model_ref as f_model_ref, _parts
    _require(belief, FiniteBelief)
    if belief.model_ref != f_model_ref(model):
        raise FInputError("shape", "belief/model mismatch")
    if type(transition_key) is not str or not transition_key:
        raise FInputError("shape", field="transition_key")
    measurements = _decode(_encode(measurements), tuple[MeasurementId, ...])
    digest = _digest({"kernel": kernel, "outcomes": outcomes, "measurements": measurements})
    for applied in belief.applied:
        if applied.transition_key == transition_key:
            if applied.input_digest != digest:
                raise FInputError("measurement_conflict")
            return belief
        if set(applied.measurements) & set(measurements):
            if applied.input_digest != digest:
                raise FInputError("measurement_conflict")
            return belief
    _, kernels, _, _ = _parts(model)
    if kernel not in kernels:
        raise FInputError("unresolved_reference", field="kernel")
    selected = tuple(o for o in kernels[kernel].outcomes if o.id in outcomes)
    if len(selected) != len(outcomes):
        raise FInputError("unresolved_reference", field="outcome")
    joint = tuple(sum(o.matrix[i][j] * belief.joint[j] for o in selected for j in range(len(belief.joint))) for i in range(len(belief.joint)))
    mass = sum(joint)
    if mass == 0:
        raise FModelFalsified("zero_evidence")
    applied = belief.applied + (AppliedTransition(transition_key=transition_key, input_digest=digest, measurements=measurements),)
    return _handle(FiniteBelief, authority=model, model_ref=belief.model_ref, evidence_key=_digest(applied),
        joint=tuple(v/mass for v in joint), evidence_mass=belief.evidence_mass*mass, applied=applied)


def _draw_id(generator, stream_id, request):
    return _digest(dict(domain="sui.f.draw/1", generator=generator, stream_id=stream_id,
        purpose=request.purpose, context_key=request.context_key, ordinal=request.ordinal))


def _validate_draw(draw):
    if (draw.purpose, draw.context_key, draw.ordinal) != (draw.request.purpose, draw.request.context_key, draw.request.ordinal):
        raise FInputError("shape", "draw/request mismatch")
    if draw.id != _draw_id(draw.generator, draw.stream_id, draw.request):
        raise FInputError("shape", "draw ID mismatch")
    if draw.purpose == "selection":
        if draw.request.law != _ContractRef("uniform_unit", "1") or draw.request.args != {}:
            raise FInputError("shape", "selection law")
        _keys(draw.value, ("u",))
        u = _decode(draw.value["u"], _Fraction)
        if not 0 <= u < 1:
            raise FInputError("shape", "u must be in [0,1)")


# Exact expressions and rational, outward elementary-series enclosures.
def _r(value):
    return ExactReal(op="rational", value=_Fraction(value))


def _add(*terms):
    items, coefficients, constant = [], {}, _Fraction(0)
    for term in terms:
        for item in term.args if term.op == "add" else (term,):
            if item.op == "rational":
                constant += item.value
            else:
                coefficient, base = _Fraction(1), item
                if item.op == "mul" and item.args[0].op == "rational":
                    coefficient = item.args[0].value
                    base = item.args[1] if len(item.args) == 2 else ExactReal(op="mul", args=item.args[1:])
                coefficients[base] = coefficients.get(base, _Fraction(0)) + coefficient
    items = [_mul(_r(coefficient), base) for base, coefficient in coefficients.items() if coefficient]
    if constant:
        items.append(_r(constant))
    return _r(0) if not items else items[0] if len(items) == 1 else ExactReal(op="add", args=tuple(items))


def _mul(*terms):
    items, constant = [], _Fraction(1)
    for term in terms:
        for item in term.args if term.op == "mul" else (term,):
            if item.op == "rational":
                constant *= item.value
            else:
                items.append(item)
    if constant == 0:
        return _r(0)
    if constant != 1 or not items:
        items.insert(0, _r(constant))
    return items[0] if len(items) == 1 else ExactReal(op="mul", args=tuple(items))


def _neg(term):
    if term.op == "add":
        return _add(*(_neg(t) for t in term.args))
    return _mul(_r(-1), term)


def _div(a, b):
    if b.op == "rational" and b.value == 0:
        raise FInputError("shape", "zero denominator")
    if a == b:
        # Internal callers only divide certified positive path masses/normalizers.
        return _r(1)
    if a.op == b.op == "rational":
        if b.value == 0:
            raise FInputError("shape", "zero denominator")
        return _r(a.value/b.value)
    if b.op == "rational":
        return _mul(_r(1/b.value), a)
    return ExactReal(op="div", numerator=a, denominator=b)


def _log(value):
    if value <= 0:
        raise FInputError("shape", "log needs a positive rational")
    return _r(0) if value == 1 else ExactReal(op="log", arg=_r(value))


def _entropy(probabilities):
    return _add(*(_mul(_r(-p), _log(p)) for p in probabilities if p))


def _kl(posterior, prior):
    return _add(*(_mul(_r(p), _log(p/q)) for p, q in zip(posterior, prior) if p))


class _ExpressionWork:
    def __init__(self, budget, precision=None):
        from .rate import _RateInformationWork
        if type(budget) is not RateBudget:
            raise FInputError("shape", "RateBudget required")
        from ._f_handles import charge_verification
        class CountedInformationWork(_RateInformationWork):
            def coefficients(self,kind,degree):
                charge_verification('terms',max(0,degree-getattr(self,kind+'_degree')))
                return super().coefficients(kind,degree)
        self.work = CountedInformationWork(budget)
        # This is a numerical enclosure grid, never an information-tail cutoff.
        if precision is not None:
            self.work.epsilon = self.work.number(precision)
        self.cache = {}
        self.cells = 0
        self.budget = budget

    def enclose(self, expr):
        from .rate import RateIncomplete, RateNumericalRange
        key = id(expr)
        if key in self.cache:
            return self.cache[key][1]
        from ._f_handles import charge_verification
        charge_verification()
        self.cells += 1
        if self.cells > self.budget.max_cells:
            raise FIncomplete("budget_exhausted", "expression cells")
        try:
            if expr.op == "rational":
                value = RationalInterval(expr.value, expr.value)
            elif expr.op in ("log", "exp", "neg"):
                a = self.enclose(expr.arg)
                if expr.op == "neg":
                    value = RationalInterval(-a.upper, -a.lower)
                elif expr.op == "log":
                    if a.lower <= 0:
                        raise FInputError("shape", "log argument not proved positive")
                    value = RationalInterval(self.work.public(self.work.log(a.lower)).lower,
                        self.work.public(self.work.log(a.upper)).upper)
                else:
                    value = RationalInterval(self.work.public(self.work.exp(a.lower)).lower,
                        self.work.public(self.work.exp(a.upper)).upper)
            elif expr.op in ("add", "mul"):
                value = RationalInterval(_Fraction(0 if expr.op == "add" else 1), _Fraction(0 if expr.op == "add" else 1))
                for term in expr.args:
                    a = self.enclose(term)
                    value = _iadd(value, a) if expr.op == "add" else _imul(value, a)
            elif expr.op == "div":
                a, b = self.enclose(expr.numerator), self.enclose(expr.denominator)
                if b.lower <= 0 <= b.upper:
                    raise FIncomplete("certificate_incomplete", "denominator not separated from zero")
                value = _imul(a, RationalInterval(1/b.upper, 1/b.lower))
            else:
                raise FInputError("shape", "unknown expression")
        except RateIncomplete as exc:
            raise FIncomplete("budget_exhausted", exc.detail) from exc
        except RateNumericalRange as exc:
            raise FNumericalRange("NumericalRange", exc.detail) from exc
        self.cache[key] = expr, value
        return value


def _iadd(a, b):
    return RationalInterval(a.lower+b.lower, a.upper+b.upper)


def _imul(a, b):
    values = (a.lower*b.lower, a.lower*b.upper, a.upper*b.lower, a.upper*b.upper)
    return RationalInterval(min(values), max(values))


def _quantity(expr, budget=None, *, work=None):
    if work is None:
        from .rate import default_rate_budget
        work = _ExpressionWork(budget or default_rate_budget())
    return FQuantity(status="finite", exact=expr, bounds=work.enclose(expr), proof=None, reason=None)


def _soft_choice(J, masses, gamma, budget=None, *, work=None):
    from .rate import RateIncomplete, RateNumericalRange
    if not J or len(J) != len(masses) or gamma < 0 or any(m < 0 for m in masses):
        raise FInputError("shape", "invalid choice axes")
    if any(j.status == "uncertified" for j in J):
        raise FIncomplete("certificate_incomplete")
    if work is None:
        from .rate import default_rate_budget
        work = _ExpressionWork(budget or default_rate_budget())
    weights, bounds = [], []
    same = all(j.exact is not None and j.exact == J[0].exact for j in J)
    for j, mass in zip(J, masses):
        if not mass or j.status == "positive_infinity":
            weights.append(_r(0)); bounds.append(RationalInterval(_Fraction(0), _Fraction(0)))
        elif same or gamma == 0:
            weights.append(_r(mass)); bounds.append(RationalInterval(mass, mass))
        else:
            weight = None if j.exact is None else _mul(_r(mass), ExactReal(op="exp", arg=_mul(_r(-gamma), j.exact)))
            jb = j.bounds
            try:
                low = work.work.public(work.work.exp(-gamma*jb.upper)).lower * mass
                high = work.work.public(work.work.exp(-gamma*jb.lower)).upper * mass
            except RateIncomplete as exc:
                raise FIncomplete("budget_exhausted", exc.detail) from exc
            except RateNumericalRange as exc:
                raise FNumericalRange("NumericalRange", exc.detail) from exc
            weights.append(weight); bounds.append(RationalInterval(low, high))
    Zbounds = RationalInterval(sum(b.lower for b in bounds), sum(b.upper for b in bounds))
    if Zbounds.upper == 0:
        raise FOutsideEvaluationType("NoAdmissibleCandidate")
    if Zbounds.lower <= 0:
        raise FIncomplete("normalization_unproved")
    Zexpr = _add(*weights) if all(w is not None for w in weights) else None
    probabilities, cumulative = [], [RationalInterval(_Fraction(0), _Fraction(0))]
    for i, weight in enumerate(weights):
        # Keep the normalization dependency: p_i=w_i/(w_i+sum other weights).
        other_lo = sum(b.lower for k, b in enumerate(bounds) if k != i)
        other_hi = sum(b.upper for k, b in enumerate(bounds) if k != i)
        b = bounds[i]
        low = b.lower/(b.lower+other_hi) if b.lower+other_hi else _Fraction(0)
        high = b.upper/(b.upper+other_lo) if b.upper+other_lo else _Fraction(0)
        expr = _div(weight, Zexpr) if weight is not None and Zexpr is not None else None
        probabilities.append(FQuantity(status="finite", exact=expr, bounds=RationalInterval(low, high), proof=None, reason=None))
        if i+1 == len(weights):
            cumulative.append(RationalInterval(_Fraction(1), _Fraction(1)))
        else:
            slo, shi = sum(x.lower for x in bounds[:i+1]), sum(x.upper for x in bounds[:i+1])
            olo, ohi = sum(x.lower for x in bounds[i+1:]), sum(x.upper for x in bounds[i+1:])
            cumulative.append(RationalInterval(slo/(slo+ohi), shi/(shi+olo)))
    # Equal J permits cancelling exp(-gamma J) in probabilities, but not in Z.
    if same and gamma != 0:
        factor = ExactReal(op="exp", arg=_mul(_r(-gamma), J[0].exact))
        Zexpr = _mul(Zexpr, factor)
        Zbounds = _imul(Zbounds, work.enclose(factor))
        if Zbounds.lower <= 0:
            raise FIncomplete("normalization_unproved")
    return ChoiceOutput(q_star=tuple(probabilities), cumulative=tuple(cumulative),
        Z=FQuantity(status="finite", exact=Zexpr, bounds=Zbounds, proof=None, reason=None))








def _FiniteWork(*args, **kwargs):
    from ._f_eval import _FiniteWork as invoke
    return invoke(*args, **kwargs)


def _finite_tree(work):
    from ._f_eval import _finite_tree as invoke
    return invoke(work)






def _check_control_kernel(kernel, node, *, state=None):
    """Certify execute.next from elapsed clock time and revealed values.

    Raw evidence and latent outcome IDs do not distinguish K histories. Existing
    slots have the same value before this transition; revealing them is allowed.
    Neither a raw completion flag nor an unsupported computation supplies an
    extra K distinction without an observation/availability certificate.
    """
    controls = {}
    for outcome in kernel.outcomes:
        if not any(value for row in outcome.matrix for value in row):
            continue
        if state is not None and not any(value * p for row in outcome.matrix for value, p in zip(row, state.joint)):
            continue
        revealed = tuple(sorted(set(outcome.available.reveal)))
        emission = outcome.evidence
        visible = (emission.slot, emission.measurement_contract, emission.value) if emission is not None and emission.slot in revealed else None
        if state is not None:
            # All old available values are fixed in this conditional history.
            # A repeated reveal of an already available slot changes no K.
            available = set(state.K_trace[-1].available)
            slots = dict(state.slots)
            for slot in revealed:
                if emission is not None and emission.slot == slot:
                    available.add(("new", slot))
                    continue
                mid = slots.get(slot)
                if mid is None:
                    matches = tuple(l.measurement for l in state.E_trace[-1].links if l.measurement.component == slot)
                    if matches:
                        mid = matches[-1]
                    else:
                        matches = tuple(l.measurement for l in state.E_trace[-1].links if l.measurement.component == "value")
                        if len(matches) != 1:
                            raise FIncomplete("certificate_incomplete", "unresolved control reveal slot")
                        mid = matches[0]
                available.add(mid)
            revealed = tuple(sorted(available, key=_dumps))
        key = _dumps((outcome.elapsed_ns, revealed, visible))
        controls.setdefault(key, set()).add(node.next[outcome.id])
    if any(len(values) != 1 for values in controls.values()):
        raise FIncomplete("certificate_incomplete", "execute.next is not measurable from K")


def _check_option(work, op):
    if op.policy.name != "finite_policy" or op.prediction.name != "finite_kernel":
        raise FSpecificationMissing("missing_contract")
    p = work.policies[op.policy.args["id"]]
    if op.args["path_action"] is None and any(isinstance(n, ExecuteNode) for n in p.nodes):
        raise FInputError("proof_mismatch", "transparent wrapper has a direct execute")
    if op.proof.name == "finite_option_proof" and op.proof.version == "1":
        if op.proof.args.get("operation") not in work.operations:
            raise FInputError("unresolved_reference", "option proof operation")
        declared = work.operations[op.proof.args["operation"]]
        if declared.semantic_key != op.semantic_key:
            raise FInputError("proof_mismatch", "proof belongs to another operation")
    seen = set()
    def first(policy, node):
        key = policy, node
        if key in seen:
            raise FIncomplete("certificate_incomplete", "no first execute proved")
        seen.add(key)
        n = next(n for n in work.policies[policy].nodes if n.id == node)
        if isinstance(n, ExecuteNode):
            return {n.kernel}
        if isinstance(n, EndNode):
            raise FInputError("proof_mismatch", "empty execution")
        values = set()
        for name in n.operations:
            child = work.operations[name]
            cp = work.policies[child.policy.args["id"]]
            values.update(first(cp.id, cp.entry))
        return values
    if first(p.id, p.entry) != {op.prediction.args["id"]}:
        raise FInputError("proof_mismatch", "prediction is not the first physical kernel")














def _validate_evaluation(evaluation):
    from ._f_eval import _validate_evaluation as invoke
    return invoke(evaluation)




def _c1_measurement_content(frame, model_ref):
    return C1MeasurementContent(model_ref=model_ref, **{f.name:getattr(frame,f.name)
        for f in _fields(C1MeasurementContent) if f.name != "model_ref"})


def certify_f_quantity(*, definition: FQuantityDefinition, evaluation: FEvaluation | None,
                       resources: FResources) -> tuple[QuantityRef, FQuantity]:
    from ._f_quantity import certify
    return certify(definition=definition,evaluation=evaluation,resources=resources)


# v0.13 §3-10-16 public skeleton. These declarations do not alter the
# existing evaluator/compiler, or certify caller-constructed DTOs.
from typing import Generic as _Generic, TypeVar as _TypeVar
from .ledger import Entry as _Entry
from .records import Payload as _Payload

Point: _TypeAlias = str


class FReader(_Protocol):
    """Readonly facts interface; factories must capture an immutable view.

    No append, ID source, clock or current-head fallback belongs to this API.
    A Point is an Entry CID, not a Record Ref or model content hash.
    """
    def entry(self, cid: Point) -> _Entry: ...
    def entries(self) -> tuple[_Entry, ...]: ...
    def record(self, cid: Point) -> _Record: ...
    def ancestors(self, frontier: tuple[Point, ...]) -> frozenset[Point]: ...
    def sealed_content(self, cid: Point) -> tuple[bytes, _Payload]:
        """Read original salt/Payload; missing body raises KeyError.

        Factories compare seal(payload,salt), Entry.seal and record(cid)'s body.
        A changing body for the same CID is FReplayMismatch, not an absence.
        """
        ...


class _FactsDTO:
    """Hand-constructible frozen content; freeze arrays/JSON, never certify."""
    __slots__ = ()

    def __post_init__(self):
        def freeze(value):
            if isinstance(value, _Mapping):
                return _MappingProxyType({k: freeze(v) for k, v in value.items()})
            if isinstance(value, (tuple, list)):
                return tuple(freeze(v) for v in value)
            return value
        for field in _fields(self):
            object.__setattr__(self, field.name, freeze(getattr(self, field.name)))


@_dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeOrigin(_FactsDTO):
    """Observed/MEMBRANE/FACT: declared model origin, not a checkpoint.

    model may point to C1/model.9, not only finite model.11. The C1 origin
    supplies context provenance, not counts/probes/coverage/incorporation.
    """
    model: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class ContentAcquired(_FactsDTO):
    """Observed/MEMBRANE/FACT: acquisition alone does not mean adoption."""
    origin: Point
    contents: tuple[Point, ...]
    clock: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationRequested(_FactsDTO):
    """Primary request, never an authenticated dependency inventory.

    finite_update/1: compiler independently derives C from method/origin/args;
    require C <= set(inputs), unique inputs, every Point available/authenticated,
    algorithm_draws=[]. Extra inputs are authenticated and digested, not new E/K.
    Omitted mandatory Point: FInputError(unresolved_reference, /inputs).
    Unreadable Point: FReplayUnavailable; false result/proof: proof_mismatch.
    Apply order comes from args.observations, not inputs; no future completion
    clocks/adoptions are demanded as numerical inputs when the method uses none.
    """
    origin: Point
    purpose: _Literal["belief", "query", "certificate"]
    method: _ContractRef
    args: ImmutableJSON
    inputs: tuple[Point, ...]
    algorithm_draws: tuple[Point, ...]
    output_contract: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationResult(_FactsDTO):
    """Prediction/MODEL/PREDICTION: an output claim, not new evidence."""
    request: Point
    output: ContractValue


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationProof(_FactsDTO):
    """Prediction/MODEL/PREDICTION: a checkable, unverified proof claim."""
    request: Point
    result: Point
    role: _Literal["normalization", "query"]
    statement: ContractValue
    checker: ProofRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class ComputationCompleted(_FactsDTO):
    """Observed/MEMBRANE/FACT: generated output; not acquisition/adoption."""
    request: Point
    result: Point
    proofs: tuple[Point, ...]
    started_clock: Point
    finished_clock: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeAdopted(_FactsDTO):
    """Decided/MODEL/FACT: previous must agree with the checked derivation."""
    origin: Point
    previous: Point | None
    completion: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteUpdateArgs(_FactsDTO):
    model: Point
    previous_result: Point | None
    observations: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteUpdateResult(_FactsDTO):
    joint: tuple[_Fraction, ...]
    evidence_mass: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteUpdateStatement(_FactsDTO):
    model: Point
    request: Point
    result: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class FiniteUpdateReplayArgs(_FactsDTO):
    """The deterministic finite_update_replay checker has exactly {} args."""
    pass


@_dataclass(frozen=True, slots=True, kw_only=True)
class FKnowledgeDependency(_FactsDTO):
    domain: _Literal["sui.f.knowledge_dependency/1"]
    request: Point
    stage: _Literal["result", "acquisition", "proof", "adoption"]
    required: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FClockReadingFact(_FactsDTO):
    """Observed/MEMBRANE/FACT: preserve the actual reading, not Record.at."""
    source: Point
    reading: ClockReading


@_dataclass(frozen=True, slots=True, kw_only=True)
class FContextCheckEvent(_FactsDTO):
    kind: _Literal["fact", "clock"]
    record: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class FContextObserved(_FactsDTO):
    """Observed/MEMBRANE/FACT: ordered observed checks; no implicit Tick."""
    knowledge_origin: Point
    observation_reading: Point
    judgment_reading: Point
    check_events: tuple[FContextCheckEvent, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FActionDeclaration(_FactsDTO):
    """Primary operation meaning. The compiler derives semantic_key."""
    id: str
    family: ActionFamilyRef
    args: ImmutableJSON
    start: PredicateRef
    policy: PolicyRef
    termination: PredicateRef
    termination_kind: _Literal["certain", "may_never"]
    prediction: KernelRef
    execution: _ContractRef
    proof: ProofRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCandidateGeneration(_FactsDTO):
    generator: _ContractRef
    args: ImmutableJSON
    basis: tuple[Point, ...]
    draws: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCandidateDeclaration(_FactsDTO):
    """Prediction/MODEL/PREDICTION: before canonicalization and aliasing."""
    model: Point
    input_order: tuple[str, ...]
    measure: CandidateMeasureRef | None
    generation: FCandidateGeneration
    continuation: FContinuation


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCandidateRequest(_FactsDTO):
    domain: _Literal["sui.f.candidate_request/1"]
    model: Point
    generator: _ContractRef
    args: ImmutableJSON
    basis: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FModelSource(_FactsDTO):
    """Prediction/MODEL/PREDICTION: complete original declaration JSON."""
    document: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class FDrawFact(_FactsDTO):
    """Observed/MEMBRANE/FACT: no derived id or duplicated request fields."""
    generator: _ContractRef
    stream_id: str
    request: DrawRequest
    value: ImmutableJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementRequested(_FactsDTO):
    """Decided/MODEL/FACT: observation request, without a fake Selected."""
    plan: Point
    step: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementJob(_FactsDTO):
    """JobOpened/MODEL/FACT: body.decision references the real request."""
    plan: Point
    step: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityConstantDeclaration(_FactsDTO):
    kind: _Literal["rational_constant"]
    value: _Fraction
    unit: _Literal["nat", "dimensionless"]
    provenance: tuple[Point, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityEvaluationDeclaration(_FactsDTO):
    kind: _Literal["evaluation"]
    result: Point
    field: _Literal["expected_cost", "already_received", "additional",
                    "total_information", "G", "J", "q_star", "Z"]
    candidate: str | None


FQuantityDeclaration: _TypeAlias = (
    FQuantityConstantDeclaration | FQuantityEvaluationDeclaration
)
# limit_declaration is exactly the existing FLimitProblem, without a wrapper.
FLimitDeclaration: _TypeAlias = FLimitProblem


@_dataclass(frozen=True, slots=True, kw_only=True)
class FFactsRequest(_FactsDTO):
    fixed_parents: tuple[Point, ...]
    model: Point
    candidates: Point
    preferences: tuple[Point, ...]
    scope: EvaluationScope
    context: Point
    method: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightFacts(_FactsDTO):
    fixed_parents: tuple[Point, ...]
    model: Point | None
    required_records: tuple[Point, ...]
    required_capabilities: tuple[RequiredCapability, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathFactsInput(_FactsDTO):
    kind: _Literal["facts"]
    value: FFactsRequest


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathPreflightInput(_FactsDTO):
    kind: _Literal["preflight"]
    value: FPreflightFacts


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLimitFactsRequest(_FactsDTO):
    declaration: Point


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathLimitInput(_FactsDTO):
    kind: _Literal["limit"]
    value: FLimitFactsRequest


FMathInput: _TypeAlias = FMathFactsInput | FMathPreflightInput | FMathLimitInput
FMathInputV1: _TypeAlias = FMathInput


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathEnvironment(_FactsDTO):
    reader_view_key: str
    registry_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPrepareCallArgs(_FactsDTO):
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FBindDrawCallArgs(_FactsDTO):
    problem_step: int
    draw: Point
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FRootCallArgs(_FactsDTO):
    root_step: int
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FEnumeratedCallArgs(_FactsDTO):
    root_step: int
    paths_step: int
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPrefixCallArgs(_FactsDTO):
    root_step: int
    steps: int
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPrefixEvaluationCallArgs(_FactsDTO):
    root_step: int
    prefix_step: int
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FTailCallArgs(_FactsDTO):
    root_step: int
    prefix_step: int
    candidate: str
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FChoiceCallArgs(_FactsDTO):
    evaluation_step: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class FEvaluateCallArgs(_FactsDTO):
    root_step: int
    resume_step: int | None
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightCallArgs(_FactsDTO):
    pass


FMathCallArgs: _TypeAlias = (
    FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs |
    FEnumeratedCallArgs | FPrefixCallArgs | FPrefixEvaluationCallArgs |
    FTailCallArgs | FChoiceCallArgs | FEvaluateCallArgs | FPreflightCallArgs
)
FMathOp: _TypeAlias = _Literal[
    "prepare", "bind_draw", "scope", "enumerate", "recursive", "enumerated",
    "prefix", "prefix_evaluation", "tail", "choice", "evaluate", "preflight",
    "limit_certificate", "limit"
]
FMathCallArgsV1: _TypeAlias = FMathCallArgs
FMathOpV1: _TypeAlias = FMathOp


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathCall(_FactsDTO):
    """Whole args of the named op; prior-step/type/use checks are factory work.

    prepare/limit_certificate/limit use FPrepareCallArgs;
    scope/enumerate/recursive use FRootCallArgs. choice has no caller-supplied u.
    """
    op: FMathOpV1
    args: FMathCallArgsV1


FMathCallV1 = FMathCall


@_dataclass(frozen=True, slots=True, kw_only=True)
class FProblemMathClaim(_FactsDTO):
    type: _Literal["FProblem"]
    value: FProblem


@_dataclass(frozen=True, slots=True, kw_only=True)
class FRootMathClaim(_FactsDTO):
    type: _Literal["FRoot"]
    value: FRoot


@_dataclass(frozen=True, slots=True, kw_only=True)
class FEvaluationMathClaim(_FactsDTO):
    type: _Literal["FEvaluation"]
    value: FEvaluation


@_dataclass(frozen=True, slots=True, kw_only=True)
class SelectedMathClaim(_FactsDTO):
    type: _Literal["Selected"]
    value: Selected


@_dataclass(frozen=True, slots=True, kw_only=True)
class NoDecisionMathClaim(_FactsDTO):
    type: _Literal["NoDecision"]
    value: NoDecision


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreflightReadyMathClaim(_FactsDTO):
    type: _Literal["PreflightReady"]
    value: PreflightReady


@_dataclass(frozen=True, slots=True, kw_only=True)
class LimitCertificateMathClaim(_FactsDTO):
    type: _Literal["LimitCertificate"]
    value: LimitCertificate


@_dataclass(frozen=True, slots=True, kw_only=True)
class FScopeMathClaim(_FactsDTO):
    type: _Literal["FScope"]
    value: FScope


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPathTableMathClaim(_FactsDTO):
    type: _Literal["FPathTable"]
    value: FPathTable


@_dataclass(frozen=True, slots=True, kw_only=True)
class TailCertificateMathClaim(_FactsDTO):
    type: _Literal["TailCertificate"]
    value: TailCertificate


FMathClaim: _TypeAlias = (
    FProblemMathClaim | FRootMathClaim | FEvaluationMathClaim | SelectedMathClaim | NoDecisionMathClaim | PreflightReadyMathClaim | LimitCertificateMathClaim | FScopeMathClaim | FPathTableMathClaim | TailCertificateMathClaim
)
FMathClaimV1: _TypeAlias = FMathClaim

FMathOutputValue: _TypeAlias = (
    FProblem | FRoot | FEvaluation | Selected | NoDecision | PreflightReady |
    LimitCertificate | FScope | FPathTable | TailCertificate
)


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathArtifactJSON(_FactsDTO):
    """Unverified structural envelope. Decoding it cannot issue a handle."""
    contract: _ContractRef
    compiler: _ContractRef
    input: FMathInputV1
    environment: FMathEnvironment
    calls: tuple[FMathCallV1, ...]
    output: int
    claim: FMathClaimV1


FMathArtifactJSONV1 = FMathArtifactJSON


@_dataclass(frozen=True, slots=True, kw_only=True)
class FCheckedMathCall(_FactsDTO):
    index: int
    op: FMathOp
    input_digest: str
    output_digest: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathVerificationContent(_FactsDTO):
    artifact_digest: str
    input_digest: str
    result_digest: str
    checked_calls: tuple[FCheckedMathCall, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathVerificationCertificate(_FactsDTO):
    contract: _ContractRef
    value: FMathVerificationContent


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class VerifiedMathResult(_FactoryHandle):
    """Factory-only mathematics certificate; not a ticket/storage receipt."""
    kind: _Literal["math"]
    input_key: str
    input_digest: str
    root_key: str | None
    result_digest: str
    artifact_digest: str
    method: _ContractRef
    certificate: FMathVerificationCertificate


_MathT = _TypeVar("_MathT")


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FMathArtifact(_FactoryHandle, _Generic[_MathT]):
    """Factory-only readonly value/bytes/reader; no writes or consumption."""
    value: _MathT
    canonical_bytes: bytes
    reader: FReader


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FHistoriesFromFacts(_FactoryHandle):
    """Narrow reader output. Caller-supplied derived histories are not inputs."""
    model: FFiniteUpdateModel
    E: EvidenceHistory
    K: KnowledgeHistory
    context: FContext
    observations: tuple[FiniteObservation, ...]


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FPreparedPredicate(_FactoryHandle):
    """Narrow cached-only predicate output, independent of a synthetic FRoot."""
    predicate: PredicateRef
    snapshot: PredicateSnapshot
    resources: FResources
    quantity_bindings: tuple[FPreparedQuantityBinding, ...]


# Syntax values only. FMathArtifact is not a JSON input or an issued-by-decode
# shortcut. Add new DTOs to the old structural codec without changing its math.
_FReshapeValue: _TypeAlias = (
    KnowledgeOrigin | ContentAcquired | ComputationRequested | ComputationResult |
    ComputationProof | ComputationCompleted | KnowledgeAdopted |
    FiniteUpdateArgs | FiniteUpdateResult | FiniteUpdateStatement | FiniteUpdateReplayArgs |
    FKnowledgeDependency | FClockReadingFact | FContextCheckEvent | FContextObserved |
    FActionDeclaration | FCandidateGeneration | FCandidateDeclaration | FCandidateRequest |
    FModelSource | FDrawFact | MeasurementRequested | MeasurementJob |
    FQuantityConstantDeclaration | FQuantityEvaluationDeclaration |
    FFactsRequest | FPreflightFacts | FMathFactsInput | FMathPreflightInput |
    FLimitFactsRequest | FMathLimitInput | FMathEnvironment |
    FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs |
    FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs |
    FChoiceCallArgs | FEvaluateCallArgs | FPreflightCallArgs | FMathCall |
    FProblemMathClaim | FRootMathClaim | FEvaluationMathClaim | SelectedMathClaim | NoDecisionMathClaim | PreflightReadyMathClaim | LimitCertificateMathClaim | FScopeMathClaim | FPathTableMathClaim | TailCertificateMathClaim |
    FMathArtifactJSON | FCheckedMathCall | FMathVerificationContent |
    FMathVerificationCertificate | VerifiedMathResult
)
_FValue = _FValue | _FReshapeValue


# v0.14 §3-10-16-補: public skeleton only; v1 wire types remain explicit.
@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightRecordAudit(_FactsDTO):
    point: Point
    entry_present: bool
    body_present: bool
    record_digest: str | None


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightCapabilityAudit(_FactsDTO):
    kind: CapabilityKind
    ref: _ContractRef
    declared: bool
    implemented: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightFailure(_FactsDTO):
    outcome: _Literal["incomplete", "rejected"]
    reason: str
    field: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightFactsAudit(_FactsDTO):
    """Output-only audit; constructing/decoding it never certifies availability."""
    request_digest: str
    model: FPreflightRecordAudit | None
    records: tuple[FPreflightRecordAudit, ...]
    capabilities: tuple[FPreflightCapabilityAudit, ...]
    failures: tuple[FPreflightFailure, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityFactsDependency(_FactsDTO):
    point: Point
    record_digest: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityFactsBinding(_FactsDTO):
    """Output/proof content; factory derives definition and dependencies.

    Internal key is H({domain:sui.f.quantity_point/1,declaration,record_digest}).
    ProofRef sui.f.quantity/2 args={binding:this}; decoding cannot issue proof.
    The issuer checks every quantity field, key/unit/evaluation/source binding.
    Existing sui.f.quantity/1 and its definition-key reader remain unchanged.
    """
    declaration: Point
    record_digest: str
    definition: FQuantityDefinition
    dependencies: tuple[FQuantityFactsDependency, ...]
    unit: _Literal["nat", "dimensionless"]


@_dataclass(frozen=True, slots=True, kw_only=True)
class FQuantityFactsProofArgs(_FactsDTO):
    binding: FQuantityFactsBinding


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreparedQuantityBinding(_FactsDTO):
    point: Point
    record_digest: str
    quantity: QuantityRef


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FFiniteUpdateModel(_FactoryHandle):
    """Factory-only descriptor; axes/kernels/projections/record bindings internal.

    Source is model_source CID; model_ref is document hash. Handbuilt matching
    authority_key or decoded descriptor is not an issued model. No FModel11
    inheritance or scheme rewriting. Mathematical issuance remains unimplemented.
    """
    source: Point
    model_ref: str
    compiler: _ContractRef
    authority_key: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyBridgeRequest(_FactsDTO):
    fixed_parents: tuple[Point, ...]
    model: Point
    context: Point
    preferences: tuple[Point, ...]
    candidates: tuple[str, ...]
    adapter: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True, init=False)
class FLegacyBridgeProblem(_FactoryHandle):
    """Factory-only old-bridge problem; no budget/draw in problem_key.

    Reading state and corresponding finite world are internal certified values;
    public descriptor/JSON or an equal ID cannot issue the problem.
    """
    problem_key: str
    request: FLegacyBridgeRequest
    legacy_model_ref: str
    adapter: _ContractRef


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyCandidateMap(_FactsDTO):
    legacy: str
    finite: str


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyDuration(_FactsDTO):
    candidate: str
    ns: int


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyO0(_FactsDTO):
    mode: _Literal["absent", "pending_marginalized"]
    source_attempts: tuple[Point, ...]
    averaged_before_choice: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyBridgeFactsContent(_FactsDTO):
    """Compiler output under sui.f.legacy_bridge_facts/1, not an input proof."""
    request: FLegacyBridgeRequest
    problem_key: str
    targets: tuple[str, ...]
    candidate_map: tuple[FLegacyCandidateMap, ...]
    durations: tuple[FLegacyDuration, ...]
    measurement_time: _Literal["report"]
    scope: EvaluationScope
    o0: FLegacyO0
    draw: Point
    u: _Fraction


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathLegacyBridgeInput(_FactsDTO):
    kind: _Literal["legacy_bridge"]
    value: FLegacyBridgeRequest


@_dataclass(frozen=True, slots=True, kw_only=True)
class FPreflightFactsCallArgs(_FactsDTO):
    """math_artifact/2 preflight args; v1's empty args type stays available."""
    budget: RateBudget


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyBridgeCallArgs(_FactsDTO):
    problem_step: int
    draw: Point
    budget: RateBudget


FMathInputV2: _TypeAlias = FMathInputV1 | FMathLegacyBridgeInput
FMathOpV2: _TypeAlias = _Literal[
    "prepare", "bind_draw", "scope", "enumerate", "recursive", "enumerated",
    "prefix", "prefix_evaluation", "tail", "choice", "evaluate", "preflight",
    "limit_certificate", "limit", "legacy_bridge_prepare", "legacy_bridge"
]
FMathCallArgsV2: _TypeAlias = (
    FPrepareCallArgs | FBindDrawCallArgs | FRootCallArgs | FEnumeratedCallArgs |
    FPrefixCallArgs | FPrefixEvaluationCallArgs | FTailCallArgs | FChoiceCallArgs |
    FEvaluateCallArgs | FPreflightFactsCallArgs | FLegacyBridgeCallArgs
)


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathCallV2(_FactsDTO):
    """v2 op/whole args; legacy_bridge_prepare uses FPrepareCallArgs.

    The facts factory checks op/args, prior steps and return types, then replays
    the existing mathematical functions before issuing a result.
    """
    op: FMathOpV2
    args: FMathCallArgsV2


@_dataclass(frozen=True, slots=True, kw_only=True)
class FLegacyBridgeProblemMathClaim(_FactsDTO):
    type: _Literal["FLegacyBridgeProblem"]
    value: FLegacyBridgeProblem


@_dataclass(frozen=True, slots=True, kw_only=True)
class LegacyComparisonMathClaim(_FactsDTO):
    type: _Literal["LegacyComparison"]
    value: LegacyComparison


FMathClaimV2: _TypeAlias = FMathClaimV1 | FLegacyBridgeProblemMathClaim | LegacyComparisonMathClaim


@_dataclass(frozen=True, slots=True, kw_only=True)
class FMathArtifactJSONV2(_FactsDTO):
    """Unverified math_artifact/2 envelope; v1 remains a distinct wire type."""
    contract: _ContractRef
    compiler: _ContractRef
    input: FMathInputV2
    environment: FMathEnvironment
    calls: tuple[FMathCallV2, ...]
    output: int
    claim: FMathClaimV2


# Ordinary new syntax defaults to v2; explicit v1 names preserve old decoding.
FMathInput = FMathInputV2
FMathOp = FMathOpV2
FMathCallArgs = FMathCallArgsV2
FMathCall = FMathCallV2
FMathClaim = FMathClaimV2
FMathArtifactJSON = FMathArtifactJSONV2
FMathOutputValue = FMathOutputValue | FLegacyBridgeProblem | LegacyComparison
_FReshapeV014Value: _TypeAlias = (
    FPreflightRecordAudit | FPreflightCapabilityAudit | FPreflightFailure |
    FPreflightFactsAudit | FQuantityFactsDependency | FQuantityFactsBinding |
    FQuantityFactsProofArgs | FPreparedQuantityBinding | FFiniteUpdateModel |
    FLegacyBridgeRequest | FLegacyBridgeProblem | FLegacyCandidateMap |
    FLegacyDuration | FLegacyO0 | FLegacyBridgeFactsContent | FMathLegacyBridgeInput |
    FPreflightFactsCallArgs | FLegacyBridgeCallArgs | FMathCallV2 |
    FLegacyBridgeProblemMathClaim | LegacyComparisonMathClaim | FMathArtifactJSONV2
)
_FValue = _FValue | _FReshapeV014Value


FIXTURE_BIT_ORDER = _ContractRef("fixture.f.bit_order", "1")
FIXTURE_BIT_ORDER_DECLARATION = CapabilityDeclaration(
    kind="generator", ref=FIXTURE_BIT_ORDER,
    args_contract=_ContractRef("sui.f.args.empty", "1"),
    input_contract=_ContractRef("sui.f.schema.candidate_input", "1"),
    output_contract=_ContractRef("sui.f.schema.candidate_input", "1"),
    dependencies=(), conditions=(ContractValue(contract=FIXTURE_BIT_ORDER,value={
        "args": {}, "draw_count": 1, "purpose": "candidate_generation",
        "law": {"name": "uniform_unit", "version": "1"},
        "request_args": {}, "ordinal": 0, "value_keys": ["u"],
        "u_interval": "0 <= u < 1", "boundary": [1, 2],
        "low_order": ["Q", "M"], "high_order": ["M", "Q"],
        "context_domain": "sui.f.candidate_request/1",
    }),),
)
"""Explicit fixture registration only; never added to builtin_f_registry.

The generator checks args={}, one generation draw, purpose/law/request args/
ordinal/value shape/range/context and the Q/M order; u=1/2 belongs to M,Q.
context binds model/generator/args/basis, not the generated input_order.
Mismatch is FInputError, not assert; accepted CandidateInput is returned intact.
Selection uses a later separate Point; purpose separation is not independence.
Implementation is intentionally absent in this skeleton.
"""
