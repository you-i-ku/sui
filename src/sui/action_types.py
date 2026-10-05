"""Immutable public values and failures for S4b action contracts, v0.22."""
from dataclasses import dataclass, field
from fractions import Fraction
from collections.abc import Mapping
from types import MappingProxyType
import math

from .ids import Ref, RefKind, expect
from .contracts import ContractRef
from .quantity import IntegrationIncomplete
from .lookahead import OutsideEvaluationType, NoAdmissibleCandidate
from .inference import NumericalRange
from .agent import ModelFalsified
from .values import _freeze


class _ActionFailure:
    def __init__(self, *, reason: str, detail: str, field: str | None = None):
        self.reason, self.detail, self.field = reason, detail, field
        super().__init__(f"{reason}: {detail}" + (f" ({field})" if field else ""))


class ActionInputError(_ActionFailure, ValueError): pass
class ActionSpecificationMissing(_ActionFailure, ValueError): pass
class ActionIncomplete(_ActionFailure, IntegrationIncomplete): pass
class ActionIncompatible(_ActionFailure, OutsideEvaluationType): pass
class ActionOutsideEvaluationType(_ActionFailure, OutsideEvaluationType): pass
class ActionModelFalsified(_ActionFailure, ModelFalsified): pass
class ActionNumericalRange(_ActionFailure, NumericalRange): pass
class ActionNoAdmissibleCandidate(_ActionFailure, NoAdmissibleCandidate): pass
class ActionRuntimeUnverified(_ActionFailure, RuntimeError): pass


def integer(value, *, field, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ActionInputError(reason="schema", detail="expected integer" +
            (f" >= {minimum}" if minimum is not None else ""), field=field)
    return value


def reference(value, kind, *, field):
    if not isinstance(value, Ref) or value.kind != kind:
        raise ActionInputError(reason="schema", detail="reference has wrong type or kind", field=field)
    return value


def check_budget(budget):
    if not isinstance(budget, ActionBudget):
        raise ActionInputError(reason="invalid_budget", detail="ActionBudget required")


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionBudget:
    tolerance: float
    node_budget: int
    series_budget: int
    refinement_budget: int
    envelope_budget: int

    def __post_init__(self):
        if type(self.tolerance) not in (float, int) or not math.isfinite(self.tolerance) or self.tolerance <= 0:
            raise ActionInputError(reason="invalid_budget", detail="positive finite tolerance required")
        for key in ("node_budget", "series_budget", "refinement_budget", "envelope_budget"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ActionInputError(reason="invalid_budget", detail=f"positive integer {key} required")


def default_budget():
    # Computational resources specified in §3-10-3; no model or preference prior.
    return ActionBudget(tolerance=1e-9, node_budget=20000, series_budget=2000,
                        refinement_budget=5, envelope_budget=20000)


@dataclass(frozen=True, slots=True)
class Bounds:
    lower: float
    upper: float
    exact: Fraction | None

    def __post_init__(self):
        if type(self.lower) not in (float,int) or type(self.upper) not in (float,int) or math.isnan(self.lower) or math.isnan(self.upper) or self.lower > self.upper:
            raise ActionNumericalRange(reason="invalid_interval", detail="unordered or NaN bounds")
        if self.exact is not None and (not isinstance(self.exact, Fraction) or
                                      not self.lower <= float(self.exact) <= self.upper):
            raise ActionNumericalRange(reason="invalid_interval", detail="exact value outside bounds")


def rational_bounds(value):
    value = Fraction(value)
    try:
        number = float(value)
    except OverflowError as exc:
        raise ActionNumericalRange(reason="overflow", detail="rational cannot be represented") from exc
    if value and number == 0:
        raise ActionNumericalRange(reason="positive_underflow", detail="nonzero rational cannot be represented")
    return Bounds(number, number, value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionTimeContext:
    run: Ref
    now_ns: int
    observed_ns: int
    check_events: tuple
    fact_ancestors: Mapping[str, frozenset[str]]
    clock_source: Ref | None

    def __post_init__(self):
        reference(self.run, RefKind.RUN, field="run")
        integer(self.now_ns, field="now_ns")
        integer(self.observed_ns, field="observed_ns")
        object.__setattr__(self, "check_events", tuple(_freeze(x) for x in self.check_events))
        object.__setattr__(self, "fact_ancestors", MappingProxyType({k: frozenset(v) for k,v in self.fact_ancestors.items()}))


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionSupport:
    status: str
    stage: str | None
    reason: str | None
    method: str | None
    conditions: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "conditions", tuple(self.conditions))


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionReading:
    run: Ref
    reading_ns: int
    work: str
    parents: frozenset[str]

    def __post_init__(self):
        reference(self.run, RefKind.RUN, field="run")
        integer(self.reading_ns, field="reading_ns")
        if not isinstance(self.work, str) or not self.work:
            raise ActionInputError(reason="schema", detail="nonempty work name required")
        object.__setattr__(self, "parents", frozenset(self.parents))
        if any(type(p) is not str or not p for p in self.parents):
            raise ActionInputError(reason="schema", detail="parents must be nonempty CID strings", field="parents")


@dataclass(frozen=True, slots=True, kw_only=True)
class Command:
    action: str
    choice: str
    run: Ref
    not_before_ns: int | None
    reservation_rule: Mapping
    dispatch: ContractRef
    effect: ContractRef
    late: str | None
    causal_stage: int
    causal_position: int

    def __post_init__(self):
        reference(self.run, RefKind.RUN, field="run")
        integer(self.causal_stage, field="causal_stage", minimum=0)
        integer(self.causal_position, field="causal_position", minimum=0)
        if self.not_before_ns is not None:
            integer(self.not_before_ns, field="not_before_ns")
        object.__setattr__(self, "reservation_rule", _freeze(self.reservation_rule))


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedLabel:
    time_s: Fraction
    causal_stage: int
    causal_position: int
    side: str

    def __post_init__(self):
        if not isinstance(self.time_s, Fraction):
            raise ActionInputError(reason="unit", detail="true time must be Fraction seconds")
        integer(self.causal_stage, field="causal_stage", minimum=0)
        integer(self.causal_position, field="causal_position", minimum=0)
        if self.side not in ("pre", "post"):
            raise ActionInputError(reason="schema", detail="unknown label side")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetRef:
    attempt: str
    position: str
    side: str

    def __post_init__(self):
        if not isinstance(self.attempt, str) or not self.attempt or self.position not in ("measurement", "completion") or self.side not in ("pre", "post"):
            raise ActionInputError(reason="schema", detail="invalid target reference")


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionBelief:
    model_ref: str
    context: ActionTimeContext
    evidence_key: str
    status: str
    log_evidence: Bounds
    evidence_kind: str
    _data: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeOrigin:
    """Completion events which begin a decision node; names identify attempts.

    An empty origin denotes the evaluation root's checkpoint. Simultaneous
    reports share one origin, rather than choosing a report by its record ID.
    """
    attempts: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "attempts", tuple(self.attempts))


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionNode:
    belief: ActionBelief
    controls: tuple[Command, ...]
    targets: tuple[TargetRef, ...]
    terminal: bool
    trigger: TargetRef | None = None

    def __post_init__(self):
        object.__setattr__(self, "controls", tuple(self.controls))
        object.__setattr__(self, "targets", tuple(self.targets))
        if self.trigger is not None and (not isinstance(self.trigger, TargetRef) or self.trigger.position != "completion"):
            raise ActionInputError(reason="shape", detail="node trigger must identify a completion", field="trigger")

    @property
    def origins(self):
        known = getattr(self.belief._data, "origins", {})
        return tuple(known.get((c.causal_stage, c.causal_position)) for c in self.controls)

    def _next_origin(self):
        if self.trigger is None:
            return None
        grouped = getattr(self.belief._data, "node_origin", None)
        if grouped is not None and self.trigger.attempt in grouped.attempts:
            return grouped
        return NodeOrigin(attempts=(self.trigger.attempt,))


def planned_attempt(command):
    return f"plan:{command.causal_stage}:{command.causal_position}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceMarginal:
    root_key: str
    controls: tuple[Command, ...]
    targets: tuple[FixedLabel | TargetRef, ...]
    certificate: ActionSupport
    _data: object = field(repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self,"controls",tuple(self.controls))
        object.__setattr__(self,"targets",tuple(self.targets))


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscreteMarginal:
    targets: tuple[FixedLabel | TargetRef, ...]
    cells: tuple[tuple[tuple[str, ...], Bounds], ...]

    def __post_init__(self):
        object.__setattr__(self,"targets",tuple(self.targets))
        object.__setattr__(self,"cells",tuple((tuple(row),p) for row,p in self.cells))


@dataclass(frozen=True, slots=True, kw_only=True)
class BranchAtom:
    probability: Bounds
    records: tuple
    child: ActionNode

    def __post_init__(self):
        object.__setattr__(self,"records",tuple(self.records))


@dataclass(frozen=True, slots=True, kw_only=True)
class BranchMeasure:
    atoms: tuple[BranchAtom, ...]
    total_mass: Bounds
    certificate: ActionSupport

    def __post_init__(self):
        object.__setattr__(self,"atoms",tuple(self.atoms))


def require_certificate(certificate):
    if certificate.status == "certified":
        return
    if certificate.reason in ("certain_zero_repetition","restart_delivery_law","one_step_nonreturn","infinite_information"):
        raise ActionOutsideEvaluationType(reason=certificate.reason,detail="action is outside this evaluation type")
    classes = {"incomplete": ActionIncomplete, "incompatible": ActionIncompatible,
               "missing_spec": ActionSpecificationMissing, "runtime_unverified": ActionRuntimeUnverified}
    raise classes[certificate.status](reason=certificate.reason, detail="action scope is not certified")
