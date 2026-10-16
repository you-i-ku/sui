"""F/F-b explicit-state model: v0.12 base plus v0.18 M3/M4.

Public subclass surface (all inputs/results are frozen values):
  enabled(View) -> tuple[Action]: operation provision (INV-2.e/11, WIN-PRE).
  accept(View, Envelope) -> Decision: SAVE-1/2, O-01, CMP-01.
  publish_unit(View, plan_id) -> Decision: O-02/03/04/06/07/08/10-13,
      atomic records + ALL work rows, REF-5, INV-2.b; only declared recipes.
  recognize(View, plan_id) -> Decision: same publication, with its prerequisites.
  recognize_terminal(View, work) -> Decision: EndKnown, T/V, O-05/07/09a/10-12,
      RIGHT-TERMINAL, INV-15; diagnostic T does not require conflict-free use.
  prepare_receipt(View, (unit,slot)) / prepare_one(View, (unit,slot)) -> Decision:
      SAVE-3, REF-5, PATH-RECEIPT, INV-4/5 (one slot, fixed preparation).
  put_body(View, key, mode) / add_entry(View, key, mode) -> Decision:
      SAVE-4/6, EP requests; mode is an ENVIRONMENT I/O outcome, not a mutant flag.
  body_response(View, key, reply) / entry_response(View, key, reply) -> Decision:
      acknowledgements of actual I/O; overridable response boundaries.
  confirm_body(View, key) / confirm_write(View, key) -> Decision: SAVE-5/7,
      actual C/E readback, INV-4; complete_write(View,key) -> Decision: SAVE-8.
  resolve_work(View, work) -> Decision: REF-5, separate one-time resolution.
  claim_start(View, work) -> Decision: START-0, O-14, HELD-N, INV-3/10.
  launch(View, work) -> Decision: START-1/2, HELD-R; host-owned launch effect.
  launch_response(View, work, reply) -> Decision: actual launch response,
      START-?, keeps known pre-entry retries distinct from uncertainty.
  enter_worker(View, wrapper) -> Decision: START-3, HELD-E, token consumption;
      rechecks permission and UseDeps immediately before entry.
  worker_step(View, work) -> Decision: START-4; requests actual program step.
  stop(View, work) / release(View, work) -> Decision: separate stop observation
      and release, O-14, B-STOP, INV-10.b. Unknown does not release anything.
  acquire(View, intent) / adopt(View, intent) -> Decision: O-08/09b,
      PATH-ACQUIRE/ADOPT, INV-9; actual acquisition is a separate environment step.
  handoff_purpose(View, CompletionKey, Owner) -> Decision: C-O01..14,
      paper 1185/1193; move the whole same-owner unmet group without achievement.
  drain(View) -> Decision: immutable enumeration, RIGHT-WORK (no removal).
  rebuild_window(View) -> Decision: only window normality, preserves H/P/C/E.

Decision carries P and effect REQUESTS, never EH/EW/EP/EU/EA/EI or E0.
Environment alone applies requests, records ACTUAL values and performs Post,
HostAck, delivery, launch failure/uncertainty, capabilities and window faults.
Environment.step is deliberately NOT an override point for window mutants.
The checker (fb_check.py) imports/calls none of this module.
Public clock/T signatures and contracts are literal data in PUBLIC_MODEL_CONTRACTS;
scene authors can read that block and the frozen types without reading bodies.

Paper limitations remain explicit: /2 numerical projection, complete artifact
closure, unspecified generation/Support contracts and parent minima cannot be
invented here. Unknown recipes stop at missing_contract, while raw receipt
storage remains available. Recipes are finite symbolic contracts, not real DTOs
or proof of F-a mathematics (H-01/03/04 still require independent review).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from hashlib import sha256
import json
from time import perf_counter
from typing import TypeAlias

from fb_check import (
    GraphObservation, Observer, PopulationDelta, StateObservation, StepObservation,
    ObservationE0, ObservationTrace, ObservationEvent, ReceiptKey, SlotKey,
    WorkKey, WorkToken, IOKey, UnitKey, IntentKey, VerificationKey,
    CompletionKey, Owner, Posted, Accepted, Reserved, WrapperEvent, BodyEntered,
    ApplicationKey,
    LaunchResponse, InputRead, Returned, UnknownObserved, Stopped, Released,
    FirstPrepared, IORequest, IOResponse, ReadBack, Published, Acquired,
    VerificationInvoked, VerificationReturned, CertificateIssued, CausalNode,
    Adopted, AdoptionReserved, CloseSave, HandoffPurpose, Applied,
    IntervalKey, IntervalUndertaken, IntervalObserved, CoverageClaimed, ArtifactValue, ArtifactIssued,
    ArtifactChecked, CompletionBinding, HostUnknownBinding, ReferenceBinding,
    IntervalBinding, AcquisitionBinding, VerificationBinding, AdoptionBinding, ReceiptSource, PurposePart,
)


@dataclass(frozen=True, slots=True)
class Object:
    """A dictionary with canonical key order. Sequence fields remain tuples."""
    items: tuple[tuple[str, object], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "items", tuple(sorted((k, freeze(v)) for k, v in self.items)))
        if len(set(k for k, _ in self.items)) != len(self.items):
            raise ValueError("duplicate dictionary field")

    def get(self, name: str, default: object = None) -> object:
        return next((v for k, v in self.items if k == name), default)


def obj(**values: object) -> Object:
    return Object(tuple(sorted((k, freeze(v)) for k, v in values.items())))


def freeze(value: object) -> object:
    if isinstance(value, dict):
        return Object(tuple(sorted((str(k), freeze(v)) for k, v in value.items())))
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(v) for v in value)
    return value


def require_frozen(value: object) -> None:
    """Refuse mutable leaves; frozen=True alone is not transitive immutability."""
    if value is None or isinstance(value, (str, bytes, int, float, bool, Enum)):
        return
    if isinstance(value, (tuple, frozenset)):
        for child in value:
            require_frozen(child)
        return
    if is_dataclass(value) and type(value).__dataclass_params__.frozen:
        for field in fields(value):
            require_frozen(getattr(value, field.name))
        return
    raise TypeError(f"mutable or undeclared value in model: {type(value).__name__}")


def _wire(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {"type": type(value).__name__,
                "fields": {f.name: _wire(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, frozenset):
        return sorted((_wire(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, tuple):
        return [_wire(v) for v in value]
    return value


def encode(value: object) -> bytes:
    # Paper 427: collision-free symbolic CID function; this deterministic encoding
    # is a MODEL encoding, not an assertion about F-a wire bytes (H-03).
    return json.dumps(_wire(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest(value: object) -> str:
    return sha256(encode(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class Contract:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class Point:
    cid: str


@dataclass(frozen=True, slots=True)
class PlanRef:
    unit: str
    slot: str


Ref: TypeAlias = Point | PlanRef


@dataclass(frozen=True, slots=True)
class Reading:
    """F-a 66 / F-b 1511, 紙に無い仮定 A-READING-NS.

    模型の整数 rank を time_ns と同一視する (time_ns = rank、run は保持)。
    Reading(run, source, rank) は模型内で保持し、source は時計源の識別名。
    実時間の精度や実物のナノ秒時計との一致は主張しない。
    """
    run: str
    source: str
    rank: int


@dataclass(frozen=True, slots=True)
class Unavailable:
    reason: str
    basis: frozenset[Point] = frozenset()


ClockValue: TypeAlias = Reading | Unavailable


@dataclass(frozen=True, slots=True)
class Interval:
    run: str
    clock: str
    start: int
    end: int
    left_closed: bool
    right_closed: bool


@dataclass(frozen=True, order=True, slots=True)
class Cell:
    """INV-12: start==end is an endpoint; start<end is an open cell."""
    start: int
    end: int


def interval_cells(interval: Interval, endpoints: tuple[int, ...]) -> frozenset[Cell]:
    # Spec 723: coordinates are fixed by declaration, not inferred from length.
    if interval.start not in endpoints or interval.end not in endpoints:
        raise ValueError("interval endpoint is outside the declared finite universe")
    if interval.start > interval.end:
        raise ValueError("interval start exceeds end")
    if interval.start == interval.end:
        return (frozenset((Cell(interval.start, interval.end),))
                if interval.left_closed and interval.right_closed else frozenset())
    result = {Cell(a, b) for a, b in zip(endpoints, endpoints[1:])
              if interval.start <= a < b <= interval.end}
    result.update(Cell(t, t) for t in endpoints
                  if (interval.start < t < interval.end
                      or t == interval.start and interval.left_closed
                      or t == interval.end and interval.right_closed))
    return frozenset(result)


class ReportKind(str, Enum):
    FRAME = "Frame"
    STARTED = "Started"
    ENDED = "Ended"
    ROUTE_APPLIED = "RouteApplied"
    GAP = "Gap"
    UNAVAILABLE = "Unavailable"
    CLAIM = "Claim"
    UNPROVED = "Unproved"


@dataclass(frozen=True, slots=True)
class Report:
    # CMP-04..09: full typed branch contents (including unknown claims) retained.
    kind: ReportKind
    segment: Ref
    item_slot: str
    route_epoch: str
    fields: Object


class OutcomeKind(str, Enum):
    RETURNED = "Success"  # receipt of a reply, NOT certification of its content
    FAILURE = "Failure"
    UNKNOWN = "Unknown"


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    content: object


@dataclass(frozen=True, slots=True)
class Generation:
    # E0-05 / Gen(w); no delivery r in these generation fields.
    work: str
    request: Ref
    stage: str
    started: ClockValue
    finished: ClockValue
    outcome: Outcome
    provenance: str


@dataclass(frozen=True, slots=True)
class Event:
    # 紙に無い仮定 A-SHAPE: Object is the symbolic envelope field container.
    # The paper gives outer names but not every concrete claims/declaration
    # nullable type (451-467). This is NOT a real DTO/wire shape validator.
    kind: str
    fields: Object


@dataclass(frozen=True, slots=True)
class Envelope:
    run: str
    number: int
    r: Reading
    receipt_seq: int
    event: Event
    source: str  # delivery provenance, not a sender's claim in event.fields

    @property
    def key(self) -> tuple[str, int]:
        return self.run, self.number


@dataclass(frozen=True, slots=True)
class ReferencePath:
    id: str
    contracts: tuple[str, ...]
    paths: tuple[str, ...]
    role: str
    use: str
    closure: str


@dataclass(frozen=True, slots=True)
class FieldRole:
    """E0-01/03: exact symbolic record/field/use/operation conversion, not a name search."""
    record_contract: Contract
    path_id: str
    path: tuple[str | int, ...]
    role: str
    use: str
    operation: str = "PrepareOne"


# Mixed-role paths cannot be assigned a single blanket role. Paper 1082/1089:
# about and fixed_parents are E; basis and actual numerical inputs are UE.
MIXED_ROLES = (
    ("PATH-R-OUTER", "about[*]", "E"), ("PATH-R-OUTER", "basis[*]", "UE"),
    ("PATH-P-OUTER", "about[*]", "E"), ("PATH-P-OUTER", "basis[*]", "UE"),
    ("PATH-ARTIFACT-INPUT", "input.value.fixed_parents[*]", "E"),
    ("PATH-ARTIFACT-INPUT", "input.value.model", "UE"),
    ("PATH-ARTIFACT-INPUT", "input.value.candidates", "UE"),
    ("PATH-ARTIFACT-INPUT", "input.value.preferences[*]", "UE"),
    ("PATH-ARTIFACT-INPUT", "input.value.context", "UE"),
)


DIAGNOSTIC_FIELD_ROLES = (
    FieldRole(Contract("sui.fb.work_terminal", "1"), "PATH-LINK-GENERATION", ("request",), "E", "terminal"),
    FieldRole(Contract("sui.fb.work_terminal", "1"), "PATH-LINK-GENERATION", ("first_receipt",), "E", "terminal"),
    FieldRole(Contract("sui.fb.verification_result", "1"), "PATH-LINK-GENERATION", ("first_receipt",), "E", "verification_response"),
)


# Explicit finite symbolic /1 mappings, paper 1076-1086. Wildcards expand only
# an explicitly named array; they never mean recursive field-name discovery.
FINITE_FIELD_ROLES = (
    # A-CLOCK-SOURCE: local model path for the Point in F-a 66, not an
    # additional canonical PATH-* claim. It records source identity with E.
    FieldRole(Contract("clock_reading", "1"), "A-CLOCK-SOURCE", ("source",), "E", "clock_source"),
    FieldRole(Contract("computation_requested", "1"), "PATH-Q0", ("origin",), "UE", "numerical"),
    FieldRole(Contract("computation_requested", "1"), "PATH-Q0", ("args", "model"), "UE", "numerical"),
    FieldRole(Contract("computation_requested", "1"), "PATH-Q0", ("inputs", "*"), "UE", "numerical"),
    FieldRole(Contract("computation_requested", "1"), "PATH-QPREV", ("args", "previous_result"), "UE", "numerical"),
    FieldRole(Contract("computation_result", "1"), "PATH-RESULT", ("request",), "UE", "generate"),
    FieldRole(Contract("computation_result", "1"), "PATH-R-OUTER", ("about", "*"), "E", "outer"),
    FieldRole(Contract("computation_result", "1"), "PATH-R-OUTER", ("basis", "*"), "UE", "outer"),
    FieldRole(Contract("computation_proof", "1"), "PATH-STATEMENT", ("request",), "UE", "proof_target"),
    FieldRole(Contract("computation_proof", "1"), "PATH-STATEMENT", ("result",), "UE", "proof_target"),
    FieldRole(Contract("computation_proof", "1"), "PATH-STATEMENT", ("statement", "value", "model"), "UE", "proof_target"),
    FieldRole(Contract("computation_proof", "1"), "PATH-STATEMENT", ("statement", "value", "request"), "UE", "proof_target"),
    FieldRole(Contract("computation_proof", "1"), "PATH-STATEMENT", ("statement", "value", "result"), "UE", "proof_target"),
    FieldRole(Contract("computation_proof", "1"), "PATH-P-OUTER", ("about", "*"), "E", "outer"),
    FieldRole(Contract("computation_proof", "1"), "PATH-P-OUTER", ("basis", "*"), "UE", "outer"),
    *(FieldRole(Contract("computation_completed", "1"), "PATH-COMPLETE", path, "UE", "generation")
      for path in (("request",), ("result",), ("proofs", "*"), ("started_clock",), ("finished_clock",))),
    *(FieldRole(Contract("content_acquired", "1"), "PATH-ACQUIRE", path, "UE", "acquire")
      for path in (("origin",), ("contents", "*"), ("clock",))),
    *(FieldRole(Contract("knowledge_adopted", "1"), "PATH-ADOPT", path, "UE", "adopt")
      for path in (("origin",), ("previous",), ("completion",))),
)


# E0-01/07, REF-1..8: never recurse by a field's spelling or CID-like strings.
# The closure column preserves missing scope even where direct edges are known.
REFERENCE_PATHS = (
    ReferencePath("A-CLOCK-SOURCE", ("clock_reading/1",), ("source",), "E", "clock_source", "declared_identity_only"),
    ReferencePath("PATH-RECEIPT", ("receipt",), ("event",), "E", "raw", "raw_only"),
    ReferencePath("PATH-RESULT", ("computation_result/1",), ("request",), "UE", "generate", "finite_update_result/1_only"),
    ReferencePath("PATH-STATEMENT", ("computation_proof/1",), ("request", "result", "statement.value.model", "statement.value.request", "statement.value.result"), "UE", "proof_target", "normalization_only"),
    ReferencePath("PATH-CHECKER", ("finite_update_replay/1",), (), "UE", "checker", "name_version_empty_args"),
    ReferencePath("PATH-Q0", ("finite_update/1",), ("origin", "args.model", "inputs[*]"), "UE", "numerical", "local_no_observations"),
    ReferencePath("PATH-QPREV", ("finite_update/1",), ("args.previous_result",), "UE", "numerical", "finite_chain_to_Q0"),
    ReferencePath("PATH-QOBS", ("finite_update/1", "finite_update/2"), ("args.observations[*]",), "U", "numerical", "not_implemented"),
    ReferencePath("PATH-R-OUTER", ("finite_update_result/1",), ("about[*]", "basis[*]"), "per_field", "outer", "not_for_2"),
    ReferencePath("PATH-P-OUTER", ("normalization",), ("about[*]", "basis[*]"), "per_field", "outer", "normalization_only"),
    ReferencePath("PATH-COMPLETE", ("computation_completed/1",), ("request", "result", "proofs[*]", "started_clock", "finished_clock"), "UE", "generation", "both_work_generations"),
    ReferencePath("PATH-ACQUIRE", ("content_acquired/1",), ("origin", "contents[*]", "clock"), "UE", "acquire", "requires_actual_ancestors"),
    ReferencePath("PATH-ADOPT", ("knowledge_adopted/1",), ("origin", "previous", "completion"), "UE", "adopt", "same_reader_chain"),
    ReferencePath("PATH-REPORT-EVIDENCE", ("report",), ("evidence[*]", "gap.evidence[*]"), "E", "report", "contract_specific_missing"),
    ReferencePath("PATH-UNAVAILABLE", ("Unavailable",), ("basis[*]",), "E", "missing", "never_measured_time"),
    ReferencePath("PATH-ARTIFACT-INPUT", ("math_artifact/2:facts",), ("input.value.fixed_parents[*]", "input.value.model", "input.value.candidates", "input.value.preferences[*]", "input.value.context"), "per_field", "math", "full_semantics_missing"),
    ReferencePath("PATH-ARTIFACT-DRAW", ("math_artifact/2:bind_draw",), ("calls[i].args.draw",), "UE", "draw", "only_op_bind_draw"),
    ReferencePath("PATH-ARTIFACT-NONPOINT", ("math_artifact/2",), (), "E", "identity", "other_calls_claims_missing"),
    ReferencePath("PATH-LINK-GENERATION", ("fb_link",), ("link.work", "link.request", "link.stage", "link.report", "link.generation"), "E", "generation", "check_actual_EH_EW"),
    ReferencePath("PATH-LINK-ACQUISITION", ("fb_link",), ("link.acquisition_intent", "link.verification", "link.acquisitions"), "UE", "acquire_adopt", "certificate_wire_missing"),
    ReferencePath("PATH-PARENTS", ("record",), ("parents[*]",), "E", "causal", "contract_parent_minima_missing"),
)


@dataclass(frozen=True, slots=True)
class ComparisonRule:
    id: str
    family: str
    key_fields: tuple[str, ...]
    compared_fields: tuple[str, ...]


# CMP-01..24, paper 1116-1139. Full contents are compared, not a result scalar.
COMPARISONS = (
    ComparisonRule("CMP-01", "receipt", ("run", "n"), ("event.kind", "event.full", "run", "n", "r", "receipt_seq", "receipt_slots")),
    ComparisonRule("CMP-02", "initial", ("declaration", "initial_slot"), ("initial.full", "generator", "method", "allocation", "reader", "model", "process", "environment")),
    ComparisonRule("CMP-03", "segment", ("route", "process", "segment_slot"), ("route_config.full", "start_reason", "measurement_contract", "clock_contract", "permission", "requested_interval")),
    ComparisonRule("CMP-04", "life", ("segment", "kind"), ("kind", "reading", "run", "reason", "request", "work_config", "evidence")),
    ComparisonRule("CMP-05", "frame", ("segment", "measurement_id"), ("route_epoch", "sample_seq", "measurement_id", "measurement_interval", "actual_time", "value", "quality", "gap.full", "source_cursor")),
    ComparisonRule("CMP-06", "FAMILY-UNNAMED", ("segment", "item_slot"), ("branch", "route_epoch", "sequence_range", "interval", "reason", "evidence")),
    ComparisonRule("CMP-07", "FAMILY-UNNAMED", ("segment", "item_slot"), ("branch", "route_epoch", "requested_interval", "reason", "evidence")),
    ComparisonRule("CMP-08", "FAMILY-UNNAMED", ("segment", "item_slot"), ("branch", "route_epoch", "interval", "kind", "contract", "evidence")),
    ComparisonRule("CMP-09", "FAMILY-UNNAMED", ("segment", "item_slot"), ("branch", "route_epoch", "interval", "missing_contracts", "evidence")),
    ComparisonRule("CMP-10", "work", ("process", "trigger", "purpose", "stage_slot"), ("Desc.full", "request_type", "delta", "trigger_slots", "Q.full")),
    ComparisonRule("CMP-11", "Wr", ("Q", "result_stage"), ("work_id", "request", "started", "finished", "output.contract", "output.value", "provenance")),
    ComparisonRule("CMP-12", "Wp", ("Q", "proof_stage"), ("work_id", "request", "result", "role", "statement.full", "checker.full", "started", "finished", "provenance")),
    ComparisonRule("CMP-13", "completed", ("Q", "completion"), ("request", "result", "proofs", "started_clock", "finished_clock", "Wr_started", "Wp_finished")),
    ComparisonRule("CMP-14", "acquire", ("origin", "intent"), ("origin", "contents", "clock", "reader", "reading")),
    ComparisonRule("CMP-15", "Wv", ("target", "check_view", "checker_version"), ("work", "QRP_all_C", "reader", "target_bytes", "target_digest", "Xnum", "closure", "view", "registry", "checker", "response", "result_reasons_missing", "certificate")),
    ComparisonRule("CMP-16", "adopt", ("origin", "intent"), ("completion", "planned_previous", "certificate", "actual_previous", "outcome")),
    ComparisonRule("CMP-17", "Ep", ("EQ", "prepared"), ("Xnum", "input.full", "operation_version", "artifact.bytes", "artifact.digest", "reply.full", "Gen")),
    ComparisonRule("CMP-18", "D", ("draw_id",), ("generator", "stream_id", "purpose", "context_key", "ordinal", "law", "args", "value")),
    ComparisonRule("CMP-19", "Ee", ("EQ", "evaluated"), ("prepared_artifact", "draw_point_request_value", "operation_version", "artifact.bytes", "artifact.digest", "Gen")),
    ComparisonRule("CMP-20", "selection", ("EV", "selection"), ("evaluated", "artifact", "root", "draw", "Selected.full")),
    ComparisonRule("CMP-21", "terminal", ("work", "terminal"), ("request", "stage", "first_receipt", "terminal_kind", "returned.full", "failure.full", "unknown_basis", "decision_view")),
    ComparisonRule("CMP-22", "execution", ("work",), ("Gen.full", "stage_output.full", "failure.full")),
    ComparisonRule("CMP-23", "binding", ("report_key",), ("segment", "report_key", "original_report", "reading_contract", "route", "generation", "clock", "cells", "evidence", "view")),
    ComparisonRule("CMP-24", "diagnostic", ("key",), ("reports_rule_affected_view", "obligation_purpose_target_missing_witness_view_owner")),
)


# RIGHT-* and CL-* are independent declarations; CL-APPLY requires a separate
# generation projection, never invented from MeasurementId or receipt counts.
RIGHTS = (
    ("RIGHT-RECEIPT", "run,n,receipt_slot"),
    ("RIGHT-WORK", "undertaking,work_id,start_token"),
    ("RIGHT-TERMINAL", "work_id,terminal"),
    ("RIGHT-COMPLETED", "Q,completion"),
    ("RIGHT-DRAW", "domain,generator,stream_id,purpose,context_key,ordinal"),
    ("RIGHT-APPLY", "reader,model,derivation_series,transition_key,input_digest"),
    ("RIGHT-ADOPT", "origin,adoption_intent"),
)
CLASH_RULES = ("CL-SAME", "CL-SEQ", "CL-MEASUREMENT", "CL-EXECUTION", "CL-DRAW", "CL-APPLY")
REF_RULES = tuple(f"REF-{i}" for i in range(1, 9))
E0_RULES = tuple(f"E0-{i:02d}" for i in range(1, 9))
START_RULES = ("START-0", "START-1", "START-2", "START-3", "START-4", "START-?")
HELD_RULES = ("HELD-N", "HELD-R", "HELD-E", "FREE-H")
SAVE_RULES = tuple(f"SAVE-{i}" for i in range(1, 9))


@dataclass(frozen=True, slots=True)
class CompletionRule:
    id: str
    occurs: str
    conclusion: str


# C-O01..14 registration (1200-1237); these are not implemented checker rows.
COMPLETION_RULES = (
    CompletionRule("C-O01.save[receipt_slot]", "Post", "Saved receipt; Boot BOTH slots"),
    CompletionRule("C-O02.issue[initial]", "Saved Boot/declaration and initial", "initial plan and all work rows"),
    CompletionRule("C-O02.save[slot]", "Publish initial", "Saved each initial slot"),
    CompletionRule("C-O03.issue[Q]", "Saved target Received under delta", "Match-delta Publish"),
    CompletionRule("C-O03.save[Q]", "Publish matching Q", "Discharge-delta"),
    CompletionRule("C-O04.save[k]", "accept interval responsibility", "Saved k"),
    CompletionRule("C-O04.run[MeasureSegment]", "Publish k", "start/report, not guaranteed"),
    CompletionRule("C-O04.handle[cells]", "accept finite interval", "each cell handled or owned"),
    CompletionRule("C-O05.run[Wr]", "Publish Q", "EndKnown Wr"),
    CompletionRule("C-O05.save[T]", "EndKnown Wr", "Saved T"),
    CompletionRule("C-O05.handle[Wr]", "EndKnown Wr", "O-06 or non-success handoff"),
    CompletionRule("C-O06.issue[R]", "corresponding first success, usable", "R plus Wp row"),
    CompletionRule("C-O06.save[R]", "Publish result", "Saved R and corresponding Wp"),
    CompletionRule("C-O07.run[Wp]", "Publish result BEFORE R saved", "EndKnown Wp"),
    CompletionRule("C-O07.save[T]", "EndKnown Wp ALL branches", "Saved T"),
    CompletionRule("C-O07.handle[Wp]", "EndKnown Wp", "branch-specific handoff"),
    CompletionRule("C-O07.issue[P,Cq]", "first corresponding proof success, usable", "P then single Cq"),
    CompletionRule("C-O07.save[P]", "Publish proof", "Saved P"),
    CompletionRule("C-O07.save[Cq]", "Publish completion", "Saved single Cq"),
    CompletionRule("C-O08.handle[intent]", "Cq saved and declared acquisition intent", "actual acquisition"),
    CompletionRule("C-O08.issue[G]", "actual acquisition", "corresponding G and Wv"),
    CompletionRule("C-O08.save[G]", "Publish G", "Saved G and Wv handoff"),
    CompletionRule("C-O09a.run[Wv]", "Publish G BEFORE G saved", "EndKnown Wv"),
    CompletionRule("C-O09a.save[T]", "EndKnown Wv", "Saved T"),
    CompletionRule("C-O09a.save[V]", "EndKnown actual definite verification reply", "Saved V, including Insufficient"),
    CompletionRule("C-O09b.handle[purpose]", "Publish G", "same purpose A/ST/reject or owned W/Xc"),
    CompletionRule("C-O09b.save[slot]", "Publish purpose processing", "Saved each processing slot, not purpose achievement"),
    CompletionRule("C-O10.run[Ep]", "Publish Ep", "EndKnown Ep"),
    CompletionRule("C-O10.save[T]", "EndKnown Ep", "Saved T"),
    CompletionRule("C-O10.issue[artifact,PR]", "corresponding issued definite artifact", "FProblem plus D OR NoDecision without D"),
    CompletionRule("C-O10.save[slot]", "Publish artifact/PR", "Saved each slot"),
    CompletionRule("C-O11.run[D]", "Publish FProblem PR BEFORE PR saved", "EndKnown D"),
    CompletionRule("C-O11.save[T]", "EndKnown D EVEN conflicted", "Saved T"),
    CompletionRule("C-O11.issue[DF/DU]", "first corresponding value/Unknown, usable", "DF plus Ee OR DU without Ee"),
    CompletionRule("C-O11.save[slot]", "Publish draw end", "Saved each required end slot"),
    CompletionRule("C-O12.run[Ee]", "Publish DF BEFORE DF saved", "EndKnown Ee"),
    CompletionRule("C-O12.save[T]", "EndKnown Ee", "Saved T"),
    CompletionRule("C-O12.handle[end]", "EndKnown Ee", "branch-specific handling"),
    CompletionRule("C-O12.issue[artifact,EV]", "corresponding definite artifact, usable", "artifact and EV"),
    CompletionRule("C-O12.issue[S]", "Saved EV, certified corresponding Selected", "S only"),
    CompletionRule("C-O12.save[slot]", "Publish artifact/EV/S", "Saved each actual slot"),
    CompletionRule("C-O13.handle[report/key/root]", "Saved reports requiring handling", "B/Xc/missing processing or handoff"),
    CompletionRule("C-O13.save[slot]", "Publish diagnostic/binding", "Saved each processing slot"),
    CompletionRule("C-O14.stop[w]", "work undertaking BEFORE reservation", "actual stop or known never-started, one release"),
    CompletionRule("C-OG.run[Wg]", "initial plan promises Wg", "EndKnown Wg"),
    CompletionRule("C-OG.save[T]", "EndKnown Wg", "Saved corresponding T"),
    CompletionRule("C-OG.handle[Wg]", "EndKnown Wg", "transfer to CG issuer or retained pG"),
    CompletionRule("C-OG.issue[CG]", "first corresponding nonempty generation, usable", "CG Publish with save CG and issue EQ custody"),
    CompletionRule("C-OG.save[CG]", "Publish CG", "Saved CG"),
    CompletionRule("C-OG.issue[EQ]", "Publish CG, independently of EQ readiness", "EQ Publish with Ep/run and original purpose custody"),
    CompletionRule("C-OG.save[EQ]", "Publish EQ", "Saved EQ"),
)


@dataclass(frozen=True, slots=True)
class ReasonRule:
    id: str
    witness: str
    effect: str


REASON_RULES = (
    ReasonRule("B-HOST", "not head/in process or awaiting acknowledgement", "receipt host order only"),
    ReasonRule("B-WINDOW", "operation owner abnormal", "that owner's service precondition only"),
    ReasonRule("B-STORE", "required put/read/add capability absent", "that storage stage only"),
    ReasonRule("B-POINT", "named required point/slot/acquisition/permission absent", "unpublished/start/handle target only"),
    ReasonRule("B-MEANING", "named contract/provenance/generation/clock missing", "meaning/purpose only"),
    ReasonRule("B-CONFLICT", "Clash in target UseDeps at Xuse", "new issue/start/use only"),
    ReasonRule("B-RESOURCE", "START-0 and max(Need-Held,0)>Free", "new reservation only"),
    ReasonRule("B-REPORT", "named real work/cells still awaiting report", "that run/cell handling only"),
    ReasonRule("B-FIRST", "earlier Post unaccepted or first receipt unsaved", "EndKnown only"),
    ReasonRule("B-STOP", "no actual stop or certain never-started", "C-O14.stop only"),
    ReasonRule("B-CHOICE", "provided operation not selected", "non-fair computation run only"),
)


@dataclass(frozen=True, slots=True)
class SpecificationLimit:
    id: str
    paper_lines: tuple[int, ...]
    scope: str
    state: str = "not_implemented"


# Keep these in E0/observations even when a local recipe does not use them.
# They are NOT silently removed from fb_check's independent scope denominator.
SPECIFICATION_LIMITS = (
    SpecificationLimit("PATH-QOBS", (1081, 1096, 1149, 1489), "generation-specific /1 observation closure and bootstrap /2 numerical projection"),
    SpecificationLimit("PATH-ARTIFACT-INPUT", (1089, 1091, 1096), "complete model/candidate/preference/context and non-facts artifact closures"),
    SpecificationLimit("PATH-REPORT-EVIDENCE", (1087, 739, 745, 752), "contract-specific report evidence and Support generation meanings"),
    SpecificationLimit("PATH-LINK-ACQUISITION", (373, 769, 1093), "real targeted issued certificate/terminal wire and F-a binding"),
    SpecificationLimit("PATH-PARENTS", (1094,), "contract-specific minimal parents and tolerance for extra parents"),
    SpecificationLimit("EVENT-WIRE", (451, 459, 463, 466, 769), "concrete new DTO field/nullable/wire declarations; symbolic container only"),
)


@dataclass(frozen=True, slots=True)
class Excuse:
    obligation_id: str
    obligation_key: object
    reason_id: str
    witness: object
    view: frozenset[Point]
    completion_conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Source:
    """E0-02/05 / PATH-COMPLETE (1001,1030-1031,1084), A-SOURCE.

    Evaluated at Publish from the named work's validated first Saved notice.
    first_receipt -> Point; generation -> worker Generation; outcome -> FULL
    Outcome; started_clock/finished_clock -> Generation.started/finished
    (Reading or Unavailable), never delivery r or record creation s.
    acquisition names the actual acquisition; numerical_view names fixed inputs.
    acquisition_clock: key = acquisition intent id; value = ActualAcquisition.reading.
    Before that actual acquisition the source is Disabled, not a predicted rank.
    outcome_kind: key = WorkId; value = the first known Outcome.kind.
    outcome_content: key = WorkId; value = the first known Outcome.content, in full.
    紙に無い仮定 A-T-UNKNOWN (769,790): use the actual entered start if known,
    otherwise Unavailable('host-start-unconfirmed'); the unconfirmed finish is
    Unavailable('host-end-unconfirmed'). These reason spellings are model names.
    terminal_basis: key = WorkId; value = the full Unknown Outcome.content;
    Failure returns its validated FirstEnd.generation; definite replies return
    None. No part of the Unknown basis or the actual Failure witness is discarded.
    terminal_view: key = WorkId; require EndKnown, then return the actual Saved
    Points in C/E at this publication root, not Generation.view or a later root.
    These five additional spellings are 紙に無い仮定 A-SOURCE (60,66,769,1044,1085).
    Clock VALUES are not Points. Declare a separate clock_reading/1 RecordPlan
    and use its PlanRef in a Point-bearing completed field. A-SOURCE is a
    紙に無い仮定: these projection names are finite model spellings.
    G.clock・Cq.started_clock/finished_clock は保存済み clock_reading/1 の Point。
    source は時計源の保存済み Point (A-CLOCK-SOURCE)、reading は対応する
    Source('acquisition_clock'|'started_clock'|'finished_clock', id) で運ぶ。
    Generation の started/finished の Unavailable は保持するが、時計の証拠は Reading が得られた時だけ clock_reading/1 を発行する。読みが無ければ Cq の時計欄と成功の後続も発行できない。
    """
    kind: str
    key: str


@dataclass(frozen=True, slots=True)
class TypedReference:
    path_id: str
    path: tuple[str | int, ...]
    ref: Ref | Source  # A-T-PLAN: Source is expanded at Publish, before REF-5.
    role: str
    use: str


@dataclass(frozen=True, slots=True)
class RecordPlan:
    slot: str
    contract: Contract
    category: str
    content: Object
    references: tuple[TypedReference, ...] = ()
    parents: frozenset[Ref | Source] = frozenset()
    at: Reading | None = None


# Public definitions are separate literal data: no implementation/evaluator
# execution is needed to obtain these signatures and named model assumptions.
PUBLIC_MODEL_CONTRACTS = (
    ("Reading", "Reading(run: str, source: str, rank: int)",
     "A-READING-NS: time_ns = rank; run is retained; Reading values stay in the model, without a physical-nanosecond claim."),
    ("clock_source_record", "clock_source_record(run: str, source: str, slot: str = 'source') -> RecordPlan",
     "A-CLOCK-SOURCE: a declared Saved Event model.clock_source/1 {run, source} identifies E0's clock; its Point is clock_reading/1.source. Publish/save it before preparing evidence."),
    ("clock_reading_record", "clock_reading_record(slot: str, source: Ref, reading: Source | Reading) -> RecordPlan",
     "F-a 66 / F-b 1511: Event clock_reading/1 {source:Point, reading:Reading}; source PlanRefs resolve separately, reading Sources use actual clock inputs; Unavailable disables publication; A-READING-NS is the only time_ns mapping."),
    ("terminal_plans", "terminal_plans(descriptors: tuple[Descriptor, ...]) -> tuple[AllowedPlan, ...]",
     "F-b 769/1044/1510: T's seven logical items use eight flat keys (request and stage are one item): work, request, stage, first_receipt, terminal_kind, returned, basis, view. Failure basis is validated Generation; Unknown basis is whole content; definite reply basis is None; V is separate."),
    ("candidate_request_content", "candidate_request_content(d: Descriptor) -> Object",
     "M3 / A-GENERATION-WIRE: full fixed Qgen input declaration; Wg args.draws=() declares no generation draws. Guard generation plus Source candidate_declaration links the whole first output to CG; Guard evaluation links Saved CG to a separately fixed EQ/Ep plan. See AllowedPlan for symbolic variant/field/guard spellings."),
    ("sui.fb.candidate_request/1 fields", "Qgen Record(contract=sui.fb.candidate_request/1, category='Event', content=Object)",
     "M3 / A-GENERATION-WIRE (name-only): Qgen.content has exactly these keys, each copied from the SAME Wg Descriptor field: "
     "process<-process, trigger<-trigger, reader<-reader, purpose<-purpose, stage_slot<-stage_slot, method<-method, "
     "output_contract<-output_contract, args<-args (whole Object; args.draws must be ()), input_points<-input_points (sorted tuple), "
     "numerical_view<-Object(points=sorted numerical_view.points, application_order=numerical_view.application_order, context=numerical_view.context), "
     "allocation<-allocation, need<-need, permissions<-permissions (sorted tuple). No request/self Point and no work_id are stored. "
     "PlanRefs stay PlanRefs in the declaration and resolve to Saved Points at preparation; the stored Record compares to the resolved Object. "
      "Actual numerical inputs also resolve the whole context, including model/generation_basis and nested typed PlanRefs, at use; the declaration stays unchanged. "
     "Wg Descriptor: stage='Wg', output_contract=sui.fb.candidate_generation/1, request=PlanRef(initial unit, Qgen slot), "
     "numerical_view.context.model=<Point|PlanRef of the model input>, numerical_view.context.generation_basis=<tuple of Point|PlanRef within the fixed input read>."),
    ("generation E0 plans", "initial O-02 plan + CG plan + EQ plan (all declared before execution)",
     "M3 / A-GENERATION-WIRE (name-only): (1) the initial O-02 plan publishes the Qgen record and the Wg Descriptor in the same unit. "
     "(2) exactly one CG plan: obligation_id='O-G', guards include Guard('generation', Wg.work_id), no works, one record "
     "RecordPlan(slot, Contract('candidate_declaration','1'), category, content=Source('candidate_declaration', Wg.work_id)). "
     "(3) exactly one EQ plan: obligation_id='O-G', guards include Guard('evaluation', Wg.work_id, PlanRef(CG unit, CG slot)) and optionally "
     "Guard('generation_context', Ref) per evaluation-use input; one record Contract('sui.fb.evaluation_request','1') whose content names "
     "candidates/reader/model/preferences/context/o/j; exactly one Ep Descriptor with request=PlanRef(EQ unit, EQ slot). "
     "Wg replies: Outcome(Success, Object(variant='Candidates', declaration=<candidate_declaration/1 Object with keys model, input_order, measure, generation{generator,args,basis,draws}, continuation{after}>)) "
     "or Outcome(Success, Object(variant='NoCandidates', basis=<whole evidence>)); Failure/Unknown as for other Compute works."),
    ("Source-expanded references", "PrepareOne: declared TypedReference -> Saved Point, compared with the same body path",
     "A-SOURCE / REF-5: a Source-expanded body may already contain the Saved Point while its reference declaration retains a PlanRef. Preparation accepts the identical declared Ref or its resolved Saved Point; a different target is rejected. Path/role/use declarations remain mandatory."),
    ("sui.fb.evaluation_request/1 fields", "EQ Record(category='Event', content=Object with exactly seven keys)",
     "M3 / A-GENERATION-WIRE (finite symbolic wire, not a F-a DTO): candidates: Ref copied from the declared CG slot; "
     "reader: Ref copied from Wg.reader; model: Ref copied from the separately declared evaluation model and matching Ep.numerical_view.context.model; "
     "preferences: Ref or nonempty tuple[Ref,...] copied from the evaluation preference declaration (tuple order retained); "
     "context: Ref copied from the evaluation context declaration and matching Ep.numerical_view.context.context; "
     "o/j: Ref or tuple[Ref,...] copied from the explicitly declared observation/judgment evidence bindings. "
     "Empty o/j tuples explicitly declare no separately modelled clock evidence; they do not certify F-a observation/judgment boundaries. "
     "Bare integers are not evidence bindings. Actual F-a boundaries refer to context_observed.observation_reading/judgment_reading Points "
     "(F-a 4453-4477); their complete clock/math closure is still unconnected. All typed refs resolve to Saved Points at EQ PUB, "
     "including every member of tuples; literal strings/integers are never guessed to be Points. All reference paths/roles must be declared."),
    ("EQ / Ep correspondence", "AllowedPlan('...', 'O-G', ..., (EQ,), (Ep,), guards)",
     "M3 1935/1937: Ep.stage='Ep', Ep.request=PlanRef(EQ unit, EQ slot), Ep.reader=Wg.reader and Ep.purpose=Wg.purpose. "
     "Ep.numerical_view.context is Object with model and context matching EQ; any mirrored preferences/o/j keys must also match EQ. "
     "Every candidates/model/preferences/context/o/j Point belongs to Ep.input_points | Ep.numerical_view.points; "
     "numerical_view.application_order is the separately fixed tuple[Ref,...] of ordered numerical reads; each target must be Saved. Never infer its order from a set. "
     "input_points and numerical_view.points may differ. Reader/process/request/permissions are also required by the Descriptor contract. "
     "EQ's request identity fixes its whole body, including o/j, even if context does not duplicate those keys. "
     "Do not copy Wg's generation view as Ep's evaluation view or insert CG into Qgen. "
     "Guard('evaluation', Wg.work_id, CG Ref) checks CG/full reply/use correspondence; "
     "Guard('saved', Ref) is an ordinary predecessor save wait and creates no pG. "
     "Guard('generation_context', Ref) explicitly declares a concrete evaluation-use shortage (model/preferences/context/o/j), "
     "not an ordinary save wait: an unresolved target seen after EndKnown(Wg) creates a target-bearing pG with the original run[Wg] origin "
     "(kept even when the target is saved before CG PUB); after CG PUB an unresolved target also keeps issue[EQ]. "
     "Later saving/EQ PUB does not clear that pG. See AllowedPlan's literal EQ declaration example."),
    ("CG single-field negative input", "CorrectWindow.publish_unit(View, plan_id) -> Decision (public subclass boundary)",
     "Keep E0's Source('candidate_declaration', work) and the actual Program reply unchanged. "
     "A test subclass can replace only a returned CG slot.plan.content field in Decision.custody, Decision.result and the matching Publish Effect payload. "
     "Run the ordinary Environment.step so EU/observer record the changed publication. This is a deliberately faulty window, not a legal alternative CG plan; "
     "a candidate-order/measure change in both Program and CG is a different legal output, not this negative control. "
     "No State/Evidence/observation-contract edit is needed; see the executable MG-05 window-owned tests."),
    ("Wg Hung / legal PR to D", "Unconnected: full Ep artifact/FProblem -> PR -> D adapter",
     "Paper 949/1932/1979: a separate bootstrap D or a Record named PR is not a legal Ep/FProblem/PR prefix. "
     "The finite artifact port does not provide the full F-a math_artifact/2/compiler/root/registry closure. "
     "Keep SC-14-M3-Hung-D-cap1/cap2 in the denominator as unconnected; do not replace them with Wg-only occupation or raw D entry."),
)


def clock_source_record(run: str, source: str, slot: str = "source") -> RecordPlan:
    """F-a 66 / F-b 1511, 紙に無い仮定 A-CLOCK-SOURCE.

    E0 の (run, clock_source) を宣言した Event model.clock_source/1 {run, source}
    を時計源の識別記録とする。場面が実行前にこの計画を置き、保存した
    Point を clock_reading/1.source が指す。初回準備前に時計源を保存する。
    source 参照は E の識別対応。実物の時計の配線・性能は保証しない。
    公開の署名と要約は PUBLIC_MODEL_CONTRACTS に独立して置く。
    """
    return RecordPlan(slot, Contract("model.clock_source", "1"), "Event", obj(run=run, source=source))


def clock_reading_record(slot: str, source: Ref, reading: Source | Reading) -> RecordPlan:
    """F-a 66 / F-b 1511: clock_reading/1 {source, reading} の模型計画。

    source は A-CLOCK-SOURCE の保存済み時計源 Point (宣言では PlanRef 可)。
    reading は実取得・実生成の Source または Reading。Reading の保持と
    time_ns の対応は Reading の A-READING-NS だけに従う。通知 r・作成 s を
    読みの代用にしない。公開の署名と要約は PUBLIC_MODEL_CONTRACTS に置く。
    Unavailable は Generation の不足値であり時計記録の reading ではない。
    Source の解決結果も発行前に検査し、Reading が無ければ発行しない。
    """
    if not isinstance(reading, (Source, Reading)):
        raise TypeError("clock_reading/1 requires Reading or a declared Source")
    return RecordPlan(slot, Contract("clock_reading", "1"), "Event", obj(source=source, reading=reading),
                      (TypedReference("A-CLOCK-SOURCE", ("source",), source, "E", "clock_source"),))


@dataclass(frozen=True, slots=True)
class NumericalView:
    points: frozenset[Ref] = frozenset()
    application_order: tuple[Ref, ...] = ()
    context: Object = Object()


@dataclass(frozen=True, slots=True)
class Descriptor:
    # E0-04: all fixed fields, including method/output VERSION, full args/order.
    work_id: str
    process: Ref
    trigger: Ref
    purpose: str
    stage_slot: str
    reader: Ref
    method: Contract
    output_contract: Contract
    args: Object
    input_points: frozenset[Ref]
    numerical_view: NumericalView
    allocation: str
    permissions: frozenset[Ref]
    request: Ref
    stage: str  # Wg / Wr / Wp / Wv / Ep / D / Ee / MeasureSegment
    need: tuple[tuple[str, int], ...]
    required: frozenset[Ref]
    use_keys: frozenset[object] = frozenset()
    semantic_limits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Guard:
    kind: str  # saved / first / outcome / acquired / initial / definite_verification
    key: object
    value: object = None


@dataclass(frozen=True, slots=True)
class AllowedPlan:
    """E0 normative recipe, authored BEFORE execution, not copied from EU.

    Public initial wiring contract, O-02 / C-O02.issue/save (1018,1201-1202):
    Boot.fields.declaration.initial must equal E0.initial in full. Saved Boot
    AND declaration permit an O-02 plan. E0.plans supplies its exact unit/key,
    ordered RecordPlans and ALL Descriptor rows; the window does not invent
    process/reader contracts or translate initial_slot into a slot by name.
    Author the initial_slot/key/slot correspondence independently in E0.
    Each RecordPlan declares slot, Contract(name,version), category, full Object
    content, concrete TypedReferences, parents, and optional creation reading.
    Every Point use needs its paper PATH/use/role and E0.field_roles conversion.

    紙に無い仮定 A-INITIAL-WIRE: model.process/1 and model.reader/1 (or other
    explicitly declared finite model contracts) are acceptable opaque records
    for initial publication/ownership slices. The paper supplies no universal
    initial-process DTO mapping. Such records do NOT establish F-a validity or
    a legal IC. PATH-Q0 additionally needs origin.model == args.model, the full
    required input closure and the declared finite_update/1 computation.

    IQ -> IC recipe surface (1026-1031,1076-1084):
    R: computation_result/1, Prediction; request -> Q (PATH-RESULT UE/generate),
       full declared output, about=(Q,), basis={Q}+Q.inputs (PATH-R-OUTER).
       Publish under O-06 with Wp at the SAME edge; Wp.required includes R.
    P: computation_proof/1, Prediction; request/result and
       statement.value.model/request/result (PATH-STATEMENT UE/proof_target),
       full versioned checker, about={Q,R}, basis={Q,R,model} (PATH-P-OUTER).
    Cq: computation_completed/1, Event; request/result/proofs and both clock
       evidence Points (PATH-COMPLETE UE/generation); prepare only after ALL P.
    Declare R/P output and statement values separately from Program's actual
    replies. Source('generation',work) and Source('first_receipt',work) retain
    actual linkage; Source('outcome',work) is an Outcome, not its content field.
    時計の証拠は clock_reading/1 {source:時計源Point, reading:Source(...)}。
    reading は開始なら Source('started_clock',Wr)、完了なら
    Source('finished_clock',Wp)、取得なら Source('acquisition_clock',意図id)。
    時計源は clock_source_record の宣言を先に保存する (A-CLOCK-SOURCE)。
    Reading と time_ns の対応は A-READING-NS の一つだけ。Slot names are local
    stable labels; all references use PlanRef(unit,slot), not predicted CIDs.
    Guard('first',work), Guard('outcome',work,(kind,variant)), and
    Guard('saved',ref) express preconditions; missing generation/closure/wire
    meanings remain in semantic_limits. A recipe is not a mathematical proof:
    even a supported finite recipe still requires H-01/H-03.

    T/V は実行前の E0.publication_plans / terminal_plans(Descriptor 群) が宣言し、ObservationE0.plans へ運ぶ (A-T-PLAN)。
    参照・親の Source は宣言だけに許す。発行時に Source を解決し、保存する Record の参照・Header/PreparedEntry の親は Point にする。

    M3 / A-GENERATION-WIRE (名前だけの仮定): Wg.output_contract is
    sui.fb.candidate_generation/1. Returned Object(variant='Candidates',
    declaration=<full candidate_declaration/1 Object>) or
    Object(variant='NoCandidates', basis=<whole evidence>) distinguishes the
    two definite replies. Qgen is sui.fb.candidate_request/1; its full content
    is candidate_request_content(Wg Descriptor). No new FWork variant.
    A CG recipe has Guard('generation', Wg.work_id), one candidate_declaration/1
    record with content=Source('candidate_declaration', Wg.work_id). Its EQ
    recipe has Guard('evaluation', Wg.work_id, PlanRef(CG unit, CG slot)), one
    sui.fb.evaluation_request/1 record, and the Ep descriptor in the same plan.
    EQ names candidates/reader/model/preferences/context/o/j, all fixed at PUB.
    Guard('generation_context', Ref) names a concrete missing evaluation-use
    input (and hence pG), unlike Guard('saved', Ref)'s predecessor-save wait.
    These field/guard/variant/contract spellings are symbolic names, not new
    mathematical claims. Full F-a generator/measure validation remains H-03.
    Wg.args.draws=() explicitly declares no generation draws for the finite
    method; absent/nonempty draws are a MissingContract, never rewritten to an
    empty draw list or a constant. numerical_view.context.generation_basis
    explicitly declares the finite method's basis correspondence, independently
    of numerical application_order; context.model names its model input.

    Literal EQ declaration fragment (A-GENERATION-WIRE, name-only wire; the
    initial/evaluation-input records and Wg/CG are declared separately in E0).
    Only frozen constructors are used; no window/checker body supplies a value::

        process = PlanRef('initial', 'process')
        reader = PlanRef('initial', 'reader')
        cg, eq = PlanRef('candidate', 'cg'), PlanRef('evaluation', 'eq')
        model, pref, ctx, o, j = (PlanRef('eval-inputs', name)
                                 for name in ('model', 'preferences', 'context', 'observation', 'judgment'))
        body = obj(candidates=cg, reader=reader, model=model,
                   preferences=pref, context=ctx, o=o, j=j)
        inputs = frozenset((cg, model, pref, ctx, o, j))
        ep = Descriptor('ep', process, cg, 'generate-and-compare', 'evaluation', reader,
            Contract('model.prepare', '1'), Contract('model.artifact', '1'), body,
            inputs, NumericalView(inputs, (model, pref, ctx, cg, o, j),
                obj(model=model, context=ctx, o=o, j=j)),
            'bootstrap', frozenset((process,)), eq, 'Ep', (('think', 1),),
            inputs | frozenset((process, reader, eq)))
        refs = tuple(TypedReference('PATH-EQ-INPUT', (key,), value, 'UE', 'math')
                     for key, value in body.items)
        record = RecordPlan('eq', Contract('sui.fb.evaluation_request', '1'), 'Event', body, refs)
        evaluation = AllowedPlan('evaluation', 'O-G', ('wg', 'evaluation'), (record,), (ep,),
            (Guard('evaluation', 'wg', cg), Guard('generation_context', ctx)))
        roles = tuple(FieldRole(record.contract, 'PATH-EQ-INPUT', ref.path, 'UE', 'math') for ref in refs)
        rule = ReferencePath('PATH-EQ-INPUT', ('sui.fb.evaluation_request/1',), (), 'UE', 'math', 'direct')

    Add evaluation/roles/rule to E0.plans/field_roles/references before I0.
    'generate-and-compare' and 'wg' must be the same purpose/work ID as Wg.
    At EQ PUB every Ref above must resolve to its own Saved input. For a plain
    predecessor save wait use Guard('saved', ctx), not generation_context.
    The finite wire checks identities/retention, not F-a mathematical validity;
    model.*, PATH-EQ-INPUT and these slot names are name-only examples.
    """
    unit: str
    obligation_id: str
    key: object
    records: tuple[RecordPlan, ...]
    works: tuple[Descriptor, ...] = ()
    guards: tuple[Guard, ...] = ()
    use_keys: frozenset[object] = frozenset()
    operation: str = "PublishUnit"
    semantic_limits: tuple[str, ...] = ()


def verification_call_id(index: int = 0) -> str:
    """PATH-LINK-ACQUISITION (1093), 紙に無い仮定 A-CALL-ID.

    仕事 w の最初の実呼出しは call/0、以降の番号の表記は call/n。
    This model enters each work body once and implements only that first call.
    All its replies/issuer outputs keep call/0; WorkerStep is not a new call.
    The paper specifies correspondence, not the spelling of this call id.
    """
    if type(index) is not int or index < 0:
        raise ValueError("call index must be a nonnegative integer")
    return f"call/{index}"


def terminal_plans(descriptors: tuple[Descriptor, ...]) -> tuple[AllowedPlan, ...]:
    """E0-04 / INV-2.b / T (769,843,1044), 紙に無い仮定 A-T-PLAN.

    Static templates, derived only from pre-run Descriptor declarations.
    terminal:<w>/T exists for every non-measurement work; verification:<w>/V
    exists for Wv and is issued only for an actual definite VerificationReply.
    Both are owned atomically by the same RecognizeTerminal edge when needed.
    F-b v0.12 (11), 1510: T has seven logical items / eight flat keys, since
    request and stage form one item. The keys are work, request, stage,
    first_receipt, terminal_kind, returned, basis, view; no extra linkage field.
    The two unit names, these finite symbolic wire fields and Source projections
    are model assumptions: the paper's real T/targeted-V wires are unfinished.
    A-T-PARENTS: T parents are request + first_receipt, V parent is first_receipt
    (1094); this choice does not establish real contract-specific parent minima.
    Failure basis retains its validated Generation including clock linkage.
    Unknown basis retains the whole original content; definite reply basis is
    None. T does not manufacture a worker Return/Stop.
    view is the actual publication-root Saved C/E set, supplied by terminal_view.
    No E0 promise is synthesized from P, EU, a reply, or a successful evaluation.
    ObservationE0.plans carries these templates under MDeclRef: Source is
    allowed only in declared RecordPlan.references[*].ref and parents.
    Publication expands Sources; PlanRefs may remain until preparation.
    Actual Record references and Header/PreparedEntry parents are Points.
    """
    result = []
    for d in descriptors:
        if d.stage == "MeasureSegment":
            continue
        oid = {"Wg": "O-G", "Wr": "O-05", "Wp": "O-07", "Wv": "O-09.a", "Ep": "O-10", "D": "O-11", "Ee": "O-12"}[d.stage]
        work, first = d.work_id, Source("first_receipt", d.work_id)
        t = RecordPlan("T", Contract("sui.fb.work_terminal", "1"), "Event",
                       obj(work=work, request=d.request, stage=d.stage,
                           first_receipt=first, terminal_kind=Source("outcome_kind", work),
                           returned=Source("outcome_content", work), basis=Source("terminal_basis", work),
                           view=Source("terminal_view", work)),
                       (TypedReference("PATH-LINK-GENERATION", ("request",), d.request, "E", "terminal"),
                        TypedReference("PATH-LINK-GENERATION", ("first_receipt",), first, "E", "terminal")),
                       frozenset((d.request, first)))
        result.append(AllowedPlan("terminal:" + work, oid, ("terminal", work), (t,),
                                  guards=(Guard("first", work),), operation="RecognizeTerminal"))
        if d.stage == "Wv":
            v = RecordPlan("V", Contract("sui.fb.verification_result", "1"), "Event",
                           obj(work=work, reply=Source("outcome_content", work), first_receipt=first,
                               view=Source("terminal_view", work)),
                           (TypedReference("PATH-LINK-GENERATION", ("first_receipt",), first, "E", "verification_response"),),
                           frozenset((first,)))
            result.append(AllowedPlan("verification:" + work, oid, ("terminal", work), (v,),
                                      guards=(Guard("first", work), Guard("definite_verification", work)),
                                      operation="RecognizeTerminal"))
    return tuple(result)


def declared_plans(e0: E0) -> tuple[AllowedPlan, ...]:
    """E0-04: user recipes plus static T/V templates; reserved names cannot collide."""
    generated = terminal_plans(tuple(w for p in e0.plans for w in p.works))
    plans = e0.plans + generated
    if len({p.unit for p in plans}) != len(plans):
        raise ValueError("duplicate/reserved declared publication unit")
    return plans


@dataclass(frozen=True, slots=True)
class DerivationContract:
    # O-03 / paper 616-620: unknown bytes are not automatically observations.
    declaration: Ref
    version: str
    process: Ref
    reader: Ref
    purpose: str
    eligible_receipts: tuple[str, ...]
    trigger_to_stage: tuple[tuple[str, str], ...]
    allowed_groups: tuple[frozenset[str], ...]
    required_inputs: frozenset[Ref]
    method: Contract
    numerical_projection: str  # 'not_implemented' for bootstrap finite_update/2


@dataclass(frozen=True, slots=True)
class Posting:
    """Actual external input occurrence; after names Saved dependencies.

    紙に無い仮定 A-POST-SOURCE (E0-02,616-620): id identifies the finite
    occurrence; source separately names Envelope.source delivery provenance.
    None preserves the original source=id spelling. It is never a payload claim.
    ReceiptSource matches source/full Event/run, not id/r/acceptance number.
    """
    id: str
    event: Event
    rank: int
    after: frozenset[Ref] = frozenset()
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ProgramPortEvent:
    """E0-05 / A-FINITE: a finite ACTUAL worker port script, not its contract.

    E0.observation_declarations holds the independent permitted relation. This
    script may return a different value; Environment transports it unchanged.
    /2, Support and F-a proof semantics are not supplied by these port outputs.
    紙に無い仮定 A-PORT-REF (1089-1093): explicit PlanRefs in this actual
    port script are read from C/E at THAT port edge, separately from the worker's
    entry inputs. Issuance resolves only its actual output; checking can read a
    Draw saved later. Never resolve ObservationE0.artifacts to generate output.
    """
    step: int
    tag: str  # Apply / CertifiedCoverage / ArtifactIssued / ArtifactChecked
    key: ApplicationKey | IntervalKey | WorkKey
    value: Applied | CoverageClaimed | ArtifactValue | ArtifactChecked


@dataclass(frozen=True, slots=True)
class CausalPort:
    """A-ANCESTRY / PATH-ADOPT (1085-1086), independent actual port program.

    紙に無い仮定 A-CAUSAL-PORT: a scene scripts which actual causal inputs its
    record-writing actor reads. This is separate from the permitted plan AND
    the window's header.parents. Without this program, no causal edges are
    asserted for that writing port; this cannot certify adoption ancestry.
    """
    slot: SlotKey
    read_roots: frozenset[Ref] = frozenset()


@dataclass(frozen=True, slots=True)
class CertificatePortEvent:
    # E0-05 / PATH-LINK-ACQUISITION (1093): actual issuer port, SEPARATE from
    # the reply. A Certificate-shaped reply is never an issuance observation.
    step: int
    certificate: Certificate


@dataclass(frozen=True, slots=True)
class ReadContents:
    """E0-05 actual port script: read bytes from C/E, not expected bytes or P.

    紙に無い仮定 A-PORT-READ: this finite program spelling requests complete
    actual target payloads at the worker/issuer port. It is not a verification.
    """
    points: frozenset[Ref]


@dataclass(frozen=True, slots=True)
class HandoffRoute:
    # A-FINITE: scene-declared destination; actual source/unmet set come from P.
    key: CompletionKey
    destination: Owner


@dataclass(frozen=True, slots=True)
class Program:
    """EW actual reply supplied by the environment; not produced by the window."""
    work: str
    replies: tuple[Outcome, ...] = ()
    stop_available: bool = True
    port_events: tuple[ProgramPortEvent, ...] = ()
    certificate_events: tuple[CertificatePortEvent, ...] = ()
    # No replies + no Stop is the ordinary Hung execution, not a window flag.


@dataclass(frozen=True, slots=True)
class AcquisitionIntent:
    id: str
    reader: Ref
    targets: frozenset[Ref]
    completion: Ref
    required_ancestors: frozenset[Ref]
    use_keys: frozenset[object] = frozenset()
    semantic_limits: tuple[str, ...] = ()
    record: Ref | None = None  # PATH-LINK-ACQUISITION: declare G before execution.


@dataclass(frozen=True, slots=True)
class AdoptionIntent:
    id: str
    reader: Ref
    completion: Ref
    result: Ref
    previous_result: Ref | None
    verification_work: str
    acquisitions: tuple[str, ...]
    plan: str
    stale_plan: str
    re_adoption: bool = False


@dataclass(frozen=True, slots=True)
class IntervalRequest:
    id: str
    point: Ref
    route_epoch: str
    work: str
    interval: Interval
    measurement_contract: Contract
    clock_contract: Contract
    cells: frozenset[Cell]


@dataclass(frozen=True, slots=True)
class SupportContract:
    # REF-6, paper 745-750: X-resident evidence separately backed by EI facts.
    contract: Contract
    kind: str
    generation_mode: str
    evidence: frozenset[Ref]
    semantic_limits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IntervalOccurrence:
    """A queued environment input, not a normative Support or claimed coverage.

    Paper 739/747: recorded only after its actual step; compare with the Point
    representing it inside fixed X. Generation meanings still require the
    declared contract/H-04; these facts alone do not certify a Claim.
    """
    id: str
    event: IntervalFact
    after: frozenset[Ref] = frozenset()
    requires_entered_work: str | None = None


@dataclass(frozen=True, slots=True)
class UnknownNotice:
    id: str
    work: str
    basis: object
    after_facts: tuple[str, ...] = ("BodyEntered",)


@dataclass(frozen=True, slots=True)
class WorkerNotice:
    """E0 delivery selector: actual Program(work).replies[reply], zero based.

    Selects the corresponding actual WorkerStep message, not an Event fabricated
    by a scene. Applies equally to WorkFinished and DrawReturned.
    """
    work: str
    reply: int = 0


@dataclass(frozen=True, slots=True)
class HostNotice:
    """E0 delivery selector: actual HostUnknown for UnknownNotice(notice)."""
    notice: str


@dataclass(frozen=True, slots=True)
class DeliveryBundle:
    """SC-15 / paper 794-801,944,1366: declared same-r first deliveries.

    紙に無い仮定 A-DELIVERY-BUNDLE: E0 fixes the ordered notice selectors
    before execution. DeliverBundle(id) waits for ALL actual messages, then
    Posts each in that order, without an intervening host clock advance, using
    the actual host reading at entry for their common r. Each Post separately
    assigns a fresh number/receipt_seq. No r/rank/receipt_seq is predicted in E0.
    This environment step groups consecutive Posts only; it neither generates
    replies nor Accepts/saves notices. Ordinary first Deliver is disabled for
    members; later redelivery follows delivery_limit and ordinary fresh Post.
    Bundles are disjoint and consumed once by actual delivery counts, not a
    window success mark. Unbundled scheduling is unchanged.

    Public scene example, given a predeclared initial plan containing Wr 'wr':
      value = WorkerNotice('wr', 0)
      unknown = HostNotice('lost-wr')
      e0 = replace(base,
          programs=(Program('wr', (Outcome(OutcomeKind.RETURNED,
                         obj(variant='Success', structure_only=True)),), False),),
          unknown_notices=(UnknownNotice('lost-wr', 'wr',
                         obj(reason='result-not-confirmed')),),
          budget=Budget(uncertain_launches=1),
          delivery_bundles=(DeliveryBundle('same-r',
                         (unknown, value) if unknown_first else (value, unknown)),))
      # Both cases are fixed before Environment(e0).initial(). After the
      # initial plan is Saved and ResolveWork('wr'), ClaimStart + Launch with
      # outcome='uncertain_after' actually enter the body and observe an unknown
      # launch response. HostUnknown('lost-wr') and WorkerStep('wr') create the
      # two actual messages. DeliverBundle('same-r') delivers the declared order.
    No numeric r or receipt number is needed in this declaration. Accept follows
    queue order; saving can overtake, and terminal recognition waits for first.
    """
    id: str
    notices: tuple[WorkerNotice | HostNotice, ...]


@dataclass(frozen=True, slots=True)
class Budget:
    window_faults: int = 0
    precommit_failures: int = 0
    lost_responses: int = 0
    launch_failures: int = 0
    duplicate_wrappers: int = 0
    uncertain_launches: int = 0


@dataclass(frozen=True, slots=True)
class E0:
    """Public finite scene declaration, fixed before execution (E0-01..08).

    State-count guide, SC-01/03/04 and paper 929,954:
    Two I0 receipts interleave Post/Accept/HostAck and each slot's saving steps;
    trace order is state data even when final C/E agree. Boot adds TWO slots.
    The 106-state SMOKE-receipt-two-same-bytes starts AFTER the first receipt
    is Saved; it is not an I0 two-receipt count (test_fb_machine receipt_prefix).
    budget adds failure location/outcome/counter products: isolate unrelated
    precommit/lost-response/launch/wrapper faults, keeping the required rebuild.
    delivery_limit repeats worker-message Post, not external Posting. More
    presentation_limit permits extra per-original Present/Accept histories;
    keep SC-01's initial acceptance plus one reacceptance.
    plans/programs/interval_occurrences/acquisitions/adoptions/handoff_routes
    add enabled actors and orderings. capacity/allocation enable concurrency.
    causal_ports fixes actual causal reads; it does not itself schedule extra
    steps, but its dependency/fresh preparation orders may distinguish states.
    Unused declaration tables do not themselves create runtime actors.
    Split unrelated products per 954, not required orderings/combinations.
    Cut/prefix boundaries are UNTESTED scopes; a reached state limit is not an
    ordinary termination. max_states belongs to Scenario and is <=200000.
    """
    # E0-01..08. Frozen independently of window and environment observations.
    run: str = "run-0"
    clock_source: str = "M"
    initial: Object | None = None
    capacity: tuple[tuple[str, int], ...] = (("think", 2), ("measure", 1))
    allocation: tuple[tuple[str, int], ...] = (("think", 2), ("measure", 1))
    postings: tuple[Posting, ...] = ()
    plans: tuple[AllowedPlan, ...] = ()
    programs: tuple[Program, ...] = ()
    derivations: tuple[DerivationContract, ...] = ()
    acquisitions: tuple[AcquisitionIntent, ...] = ()
    adoptions: tuple[AdoptionIntent, ...] = ()
    intervals: tuple[IntervalRequest, ...] = ()
    support_contracts: tuple[SupportContract, ...] = ()
    endpoints: tuple[int, ...] = (0, 1, 2, 3)
    budget: Budget = Budget()
    delivery_limit: int = 1
    interval_occurrences: tuple[IntervalOccurrence, ...] = ()
    unknown_notices: tuple[UnknownNotice, ...] = ()
    paper_version: str = "v0.12"
    references: tuple[ReferencePath, ...] = REFERENCE_PATHS
    comparisons: tuple[ComparisonRule, ...] = COMPARISONS
    completions: tuple[CompletionRule, ...] = COMPLETION_RULES
    reasons: tuple[ReasonRule, ...] = REASON_RULES
    field_roles: tuple[FieldRole, ...] = DIAGNOSTIC_FIELD_ROLES + FINITE_FIELD_ROLES
    specification_limits: tuple[SpecificationLimit, ...] = SPECIFICATION_LIMITS
    # A-FINITE: independent scene declarations, fixed before any window call.
    # Explicit bindings are not repaired from EU or from successful outcomes.
    observation_declarations: ObservationE0 | None = None
    receipt_kinds: tuple[tuple[int, str], ...] = ()
    causal_ports: tuple[CausalPort, ...] = ()
    handoff_routes: tuple[HandoffRoute, ...] = ()
    # 紙に無い仮定 A-PRESENT: exploration Cut after one presentation + one retry
    # per original. Paper 797 permits retry but gives no count bound. Enabled
    # remains complete; excluded calls are UNTESTED, never a normal termination.
    presentation_limit: int = 2
    # SC-15 / A-DELIVERY-BUNDLE: fixed transport order, independent of observations.
    delivery_bundles: tuple[DeliveryBundle, ...] = ()

    @property
    def observation_contract(self) -> ObservationE0:
        return self.observation_declarations or declare_observation_e0(self)

    @property
    def publication_plans(self) -> tuple[AllowedPlan, ...]:
        """E0-04 / A-T-PLAN: fixed recipes including T/V, before execution.

        declare_observation_e0 transports these recipes to ObservationE0.plans.
        This property reads no execution state or ledger; see terminal_plans.
        """
        return declared_plans(self)


# Actual observations (EH/EW/EP/EU/EA/EI), kept separate from E0 expectations.
@dataclass(frozen=True, slots=True)
class Fact:
    kind: str
    key: object
    value: object


@dataclass(frozen=True, slots=True)
class EH:
    originals: tuple[Envelope, ...] = ()
    presentations: frozenset[Fact] = frozenset()
    accepts: frozenset[Fact] = frozenset()
    acknowledgements: tuple[tuple[str, int], ...] = ()
    generations: frozenset[Fact] = frozenset()


@dataclass(frozen=True, slots=True)
class EW:
    events: tuple[Fact, ...] = ()
    # Records actual input reads and outputs, not P.work.phase copies.


@dataclass(frozen=True, slots=True)
class EP:
    first_preparations: frozenset[Fact] = frozenset()
    attempts: frozenset[Fact] = frozenset()
    readbacks: frozenset[Fact] = frozenset()
    # Repeated identical idempotent I/O is an explicit graph self-edge. It does
    # not create infinitely many identical facts in a vertex; edge events retain
    # EVERY invocation/outcome. Paper does not specify this finite quotient:
    # 紙に無い仮定 A-IO: identical I/O fact repetitions are represented by edges,
    # not an unbounded per-state call count. Resource/token events are NOT quotiented.


@dataclass(frozen=True, slots=True)
class EU:
    publications: frozenset[Fact] = frozenset()


@dataclass(frozen=True, slots=True)
class ActualAcquisition:
    intent: str
    reader: Point
    targets: frozenset[Point]
    contents: tuple[tuple[Point, bytes], ...]
    view: frozenset[Point]
    reading: Reading
    ancestors: frozenset[Point]


@dataclass(frozen=True, slots=True)
class VerificationCall:
    work: str
    target: object
    input_read: NumericalView
    check_view: frozenset[Point]
    arguments: Object


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    request: Ref
    result: Ref
    proofs: frozenset[Ref]
    completion: Ref


@dataclass(frozen=True, slots=True)
class Certificate:
    """Symbolic issued-port value with full bindings; NOT the unspecified wire.

    H-03: environment program must supply the issued value. This simulator never
    issues a real F-a certificate or derives issuance from a window success bit.
    """
    issuer: str
    target: UpdateTarget
    reader: Point
    target_contents: tuple[tuple[Point, bytes], ...]
    numerical_view: NumericalView
    evidence_closure: frozenset[Point]
    check_view: frozenset[Point]
    registry: str
    checker: Contract
    result_digest: str


@dataclass(frozen=True, slots=True)
class VerificationReply:
    response: str  # Success / Rejected / Insufficient, definite RETURNED contents
    target: object
    reader: Point
    target_contents: tuple[tuple[Point, bytes], ...]
    numerical_view: NumericalView
    evidence_closure: frozenset[Point]
    check_view: frozenset[Point]
    registry: str
    checker: Contract
    result: object
    reasons: tuple[object, ...]
    missing: frozenset[object]
    certificate: object | None


@dataclass(frozen=True, slots=True)
class EA:
    acquisitions: tuple[ActualAcquisition, ...] = ()
    calls: tuple[VerificationCall, ...] = ()
    replies: tuple[tuple[str, VerificationReply], ...] = ()
    adoptions: tuple[Fact, ...] = ()
    adoption_plans: frozenset[Fact] = frozenset()
    issued: tuple[tuple[str, Certificate], ...] = ()
    # A-ANCESTRY: the actor port program's performed causal reads at AddEntry.
    # Separate from a window header's requested parents and from visible X.
    causal_nodes: tuple[CausalNode, ...] = ()


@dataclass(frozen=True, slots=True)
class IntervalFact:
    # EI: actual event, not the coverage claimed by a report or a window.
    kind: str
    interval_request: str
    route_epoch: str
    reading: ClockValue
    cells: frozenset[Cell]
    evidence_point: Ref | None
    content: object


@dataclass(frozen=True, slots=True)
class EI:
    requests: tuple[IntervalRequest, ...] = ()
    events: tuple[IntervalFact, ...] = ()
    occurred: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Evidence:
    eh: EH = EH()
    ew: EW = EW()
    ep: EP = EP()
    eu: EU = EU()
    ea: EA = EA()
    ei: EI = EI()
    el: EL | None = None  # populated from actual C/E by Environment, never P
    observation_trace: ObservationTrace | None = None
    # Occurrence journal is independent of P: a deleted condition is not reborn
    # and hidden by the environment. E0 supplies keys, never the actual owner.
    condition_births: frozenset[CompletionKey] = frozenset()


@dataclass(frozen=True, slots=True)
class Record:
    name: str
    at: Reading
    contract: Contract
    category: str
    content: Object
    references: tuple[TypedReference, ...]


@dataclass(frozen=True, slots=True)
class Header:
    record: Record
    seal: str
    parents: frozenset[Point]


@dataclass(frozen=True, slots=True)
class PreparedEntry:
    record: Record
    parents: frozenset[Point]
    salt: bytes
    payload: bytes
    seal: str
    header: Header
    point: Point


@dataclass(frozen=True, slots=True)
class Body:
    seal: str
    salt: bytes
    payload: bytes


@dataclass(frozen=True, slots=True)
class Entry:
    point: Point
    header: Header


@dataclass(frozen=True, slots=True)
class EL:
    """Actual C/E values; reconstructed by Environment, never a saved flag."""
    bodies: tuple[Body, ...] = ()
    entries: tuple[Entry, ...] = ()


@dataclass(frozen=True, slots=True)
class Slot:
    plan: RecordPlan
    prepared: PreparedEntry | None = None
    body_confirmed: bool = False
    entry_confirmed: bool = False
    completed: bool = False


@dataclass(frozen=True, slots=True)
class GenerationContinuation:
    """M3: reconstructible custody before EQ; pG keeps the original run key.

    A-GENERATION-WIRE names the container only. Missing input witnesses and pG
    survive later EQ publication; D3 supplies no purpose-achievement operation.
    """
    descriptor: Descriptor
    candidate: PlanRef
    evaluation: PlanRef
    purpose: PurposePart
    shortages: tuple[Excuse, ...] = ()


@dataclass(frozen=True, slots=True)
class Unit:
    id: str
    obligation_id: str
    key: object
    slots: tuple[Slot, ...]
    works: tuple[str, ...]
    issued_view: frozenset[Point]
    generation: GenerationContinuation | None = None


@dataclass(frozen=True, slots=True)
class Receipt:
    envelope: Envelope
    unit: Unit


@dataclass(frozen=True, slots=True)
class Acceptance:
    envelope: Envelope
    unit: str
    plans: tuple[RecordPlan, ...]


@dataclass(frozen=True, slots=True)
class WorkRow:
    descriptor: Descriptor
    resolutions: tuple[tuple[PlanRef, Point], ...] = ()
    phase: str = "Pending"
    token: str | None = None
    consumed: bool = False
    held: tuple[tuple[str, int], ...] = ()
    start_unknown: bool = False
    stopped: bool = False
    released: bool = False
    knowledge: Outcome | None = None
    first: tuple[str, int] | None = None
    # Run, terminal saving, purpose handling and stopping are separate axes.
    # Unmaterialized EndKnown obligations remain owned by this very work row.
    purposes: tuple[Excuse, ...] = ()


@dataclass(frozen=True, slots=True)
class ConditionCustody:
    # C-O01..14 / paper 1185,1193. No string condition IDs or owner success bits.
    key: CompletionKey
    owner: Owner
    unmet: frozenset[CompletionKey]


@dataclass(frozen=True, slots=True)
class Custody:
    receipts: tuple[Receipt, ...] = ()
    units: tuple[Unit, ...] = ()
    work: tuple[WorkRow, ...] = ()
    adoption_reservations: tuple[tuple[Point, str], ...] = ()
    conditions: tuple[ConditionCustody, ...] = ()


@dataclass(frozen=True, slots=True)
class Host:
    run: str
    reading: Reading
    queue: tuple[Envelope, ...] = ()
    originals: tuple[Envelope, ...] = ()
    interval_requests: tuple[IntervalRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class Wrapper:
    id: str
    work: str
    token: str
    status: str = "launched"


@dataclass(frozen=True, slots=True)
class Runner:
    work: str
    token: str
    numerical_input: NumericalView
    started: Reading
    step: int = 0
    stopped: bool = False
    descriptor_read: Descriptor | None = None
    reference_read: tuple[tuple[PlanRef, Point], ...] = ()


@dataclass(frozen=True, slots=True)
class Message:
    """Actual report occurrence, distinct from its delivery provenance.

    worker 報告の封筒の source は生成の provenance。場面が ReceiptSource で報告を指す時はこの値を使う。
    id names the occurrence/Deliver action; generation.provenance names the
    actual producer, for both WorkFinished/DrawReturned and host Unknown.
    """
    id: str
    event: Event
    work: str
    generation: Generation
    deliveries: int = 0


@dataclass(frozen=True, slots=True)
class Delivery:
    """EH/EW correspondence, PATH-LINK-GENERATION / EndKnown (1092,1187).

    紙に無い仮定 A-DELIVERY-LINK: a frozen (full posted envelope, message id)
    pair spells the actual transport occurrence. It is written only by Deliver,
    not inferred from a sender's payload claim or cached by first source match.
    """
    envelope: Envelope
    message: str


@dataclass(frozen=True, slots=True)
class Network:
    posted: frozenset[str] = frozenset()
    messages: tuple[Message, ...] = ()
    deliveries: tuple[Delivery, ...] = ()


@dataclass(frozen=True, slots=True)
class Core:
    """Frozen actual state plus immutable pre-run receipt selectors.

    紙に無い仮定 A-RECEIPT-SELECTOR (616-620,1363): alias unit/slot names
    select a UNIQUE full actual Post by delivery provenance/Event/optional run.
    Selector definitions are fixed by E0; a mutable first-match alias cache is
    not part of this state, and decisions cannot replace these declarations.
    """
    # S=(H,P,C,E,Runners,Network), paper 269-280.
    h: Host
    p: Custody = Custody()
    c: tuple[Body, ...] = ()
    e: tuple[Entry, ...] = ()
    wrappers: tuple[Wrapper, ...] = ()
    runners: tuple[Runner, ...] = ()
    network: Network = Network()
    # Immutable pre-run selector declarations, never a window-written alias map.
    receipt_sources: tuple[ReceiptSource, ...] = ()


@dataclass(frozen=True, slots=True)
class Controls:
    normal_window: bool = True
    normal_host: bool = True
    normal_wrapper: bool = True
    body_put: bool = True
    body_read: bool = True
    entry_add: bool = True
    entry_read: bool = True
    budget: Budget = Budget()


@dataclass(frozen=True, slots=True)
class State:
    core: Core
    controls: Controls
    evidence: Evidence = Evidence()


@dataclass(frozen=True, slots=True)
class View:
    core: Core
    controls: Controls
    # Read-only actual observations; Decision cannot return/replace these.
    actual: Evidence


@dataclass(frozen=True, slots=True)
class Action:
    operation: str
    target: tuple[object, ...] = ()
    outcome: str = "normal"

    @property
    def fair_unit(self) -> tuple[object, ...]:
        # L-FAIR: includes e/u/slot/work; I/O outcome is NOT a new fair target.
        return (self.operation, *self.target)


@dataclass(frozen=True, slots=True)
class Effect:
    kind: str
    key: object
    value: object = None


@dataclass(frozen=True, slots=True)
class Decision:
    custody: Custody
    effects: tuple[Effect, ...] = ()
    result: object = None


@dataclass(frozen=True, slots=True)
class Step:
    state: State
    events: tuple[ObservationEvent, ...]
    result: object = None


class Disabled(Exception):
    """An attempted operation has no transition under the public contract."""


class MissingContract(Disabled):
    pass


class HostFault(Disabled):
    pass


def _find(items: tuple, predicate):
    return next((x for x in items if predicate(x)), None)


def _sorted(items: tuple) -> tuple:
    return tuple(sorted(items, key=encode))


def _replace_item(items: tuple, old: object, new: object) -> tuple:
    return tuple(new if x == old else x for x in items)


def _seal(payload: bytes, salt: bytes) -> str:
    # A-CODEC / SAVE-4..8 (paper 462). Independent of fb_check.model_seal.
    framed = (b"fb-check-seal/1\0" + len(salt).to_bytes(8, "big") + salt
              + len(payload).to_bytes(8, "big") + payload)
    return sha256(framed).hexdigest()


def _saved(core: Core, point: Point) -> bool:
    entry = _find(core.e, lambda e: e.point == point)
    if entry is None or digest(entry.header) != point.cid:
        return False
    body = _find(core.c, lambda b: b.seal == entry.header.seal)
    return (body is not None and _seal(body.payload, body.salt) == body.seal
            and body.payload == encode(entry.header.record))


def _visible(core: Core) -> frozenset[Point]:
    return frozenset(e.point for e in core.e if _saved(core, e.point))


def _units(p: Custody) -> tuple[Unit, ...]:
    return tuple(r.unit for r in p.receipts) + p.units


def _slot(p: Custody, key: tuple[str, str]) -> Slot:
    unit = _find(_units(p), lambda u: u.id == key[0])
    if unit is None:
        raise Disabled("unknown unit")
    slot = _find(unit.slots, lambda s: s.plan.slot == key[1])
    if slot is None:
        raise Disabled("unknown slot")
    return slot


def _with_slot(p: Custody, key: tuple[str, str], new: Slot) -> Custody:
    def changed(u: Unit) -> Unit:
        return replace(u, slots=tuple(new if s.plan.slot == key[1] else s for s in u.slots))
    receipts = tuple(replace(r, unit=changed(r.unit)) if r.unit.id == key[0] else r for r in p.receipts)
    units = tuple(changed(u) if u.id == key[0] else u for u in p.units)
    return replace(p, receipts=receipts, units=units)


def _work(p: Custody, work: str) -> WorkRow:
    row = _find(p.work, lambda w: w.descriptor.work_id == work)
    if row is None:
        raise Disabled("unknown work")
    return row


def _with_work(p: Custody, row: WorkRow) -> Custody:
    return replace(p, work=tuple(row if w.descriptor.work_id == row.descriptor.work_id else w for w in p.work))


def _resolve(core: Core, ref: Ref) -> Point:
    if isinstance(ref, Point):
        if not _saved(core, ref):
            raise Disabled("required Point is not saved")
        return ref
    # O-03 / E0-02 / REF-5 (616-620,1062,1363). Independent model resolution.
    # A-RECEIPT-SELECTOR is a 紙に無い仮定: logical receipt unit names select
    # full actual Posts; number/r/seq are never predicted or cached first-wins.
    aliases = tuple(a for a in core.receipt_sources if (a.unit, a.slot) == (ref.unit, ref.slot))
    if aliases:
        if len(aliases) != 1 or any(u.id == ref.unit for u in _units(core.p)):
            raise Disabled("ambiguous receipt alias declaration/unit")
        alias = aliases[0]
        originals = tuple(e for e in core.h.originals if e.source == alias.source and e.event == alias.event
                          and (alias.run is None or e.run == alias.run))
        if len(originals) != 1:
            raise Disabled("receipt alias lacks a unique actual Post")
        receipts = tuple(r for r in core.p.receipts if r.envelope == originals[0])
        if len(receipts) != 1:
            raise Disabled("receipt alias has no unique accepted original")
        slot = _slot(core.p, (receipts[0].unit.id, alias.slot))
    else:
        slot = _slot(core.p, (ref.unit, ref.slot))
    if slot.prepared is None or not _saved(core, slot.prepared.point):
        raise Disabled("required PlanRef is not saved")
    return slot.prepared.point


def _path(value: object, path: tuple[str | int, ...]) -> object:
    for part in path:
        if isinstance(part, int) and isinstance(value, tuple):
            value = value[part]
        elif isinstance(value, Object) and isinstance(part, str):
            sentinel = object()
            value = value.get(part, sentinel)
            if value is sentinel:
                raise MissingContract("declared typed path absent")
        else:
            raise MissingContract("typed path does not match shape")
    return value


def _put_path(value: object, path: tuple[str | int, ...], replacement: object) -> object:
    if not path:
        return replacement
    head, *tail = path
    if isinstance(value, Object) and isinstance(head, str):
        if not any(k == head for k, _ in value.items):
            raise MissingContract("declared typed path absent")
        return Object(tuple((k, _put_path(v, tuple(tail), replacement) if k == head else v) for k, v in value.items))
    if isinstance(value, tuple) and isinstance(head, int):
        return tuple(_put_path(v, tuple(tail), replacement) if i == head else v for i, v in enumerate(value))
    raise MissingContract("invalid declared path")


def _plan_refs(value: object) -> frozenset[PlanRef]:
    # Only to reject unresolved typed values in INTERNAL recipes; not a semantic
    # Point/CID search, and NEVER applied to raw PATH-RECEIPT contents.
    if isinstance(value, PlanRef):
        return frozenset((value,))
    if isinstance(value, Object):
        return frozenset().union(*(_plan_refs(v) for _, v in value.items))
    if isinstance(value, (tuple, frozenset)):
        return frozenset().union(*(_plan_refs(v) for v in value))
    return frozenset()


def _generation_refs(value: object) -> frozenset[Ref]:
    """Typed EQ input values only; strings are never guessed to be Points."""
    if isinstance(value, (Point, PlanRef)):
        return frozenset((value,))
    if isinstance(value, Object):
        return frozenset().union(*(_generation_refs(v) for _, v in value.items))
    if isinstance(value, (tuple, frozenset)):
        return frozenset().union(*(_generation_refs(v) for v in value))
    return frozenset()


def _descriptor_refs(d: Descriptor) -> frozenset[Ref]:
    # INV-5.b: ALL declared needed Points, not just the request/next-stage Point.
    return (d.required | d.input_points | d.permissions | d.numerical_view.points
            | frozenset(d.numerical_view.application_order)
            | frozenset((d.process, d.trigger, d.reader, d.request)))


def _resolved_numerical(core: Core, d: Descriptor) -> NumericalView:
    return NumericalView(frozenset(_resolve(core, p) for p in d.numerical_view.points),
                         tuple(_resolve(core, p) for p in d.numerical_view.application_order),
                         _env_value(core, d.numerical_view.context))


def _receipt_saved(core: Core, receipt: Receipt) -> bool:
    return all(s.prepared is not None and _saved(core, s.prepared.point)
               for s in receipt.unit.slots)


def _generation_for(core: Core, envelope: Envelope) -> Generation | None:
    # The producer provenance is carried by the delivery, not an event claim.
    links = tuple(d for d in core.network.deliveries if d.envelope == envelope)
    if len(links) != 1:
        return None
    message = _find(core.network.messages, lambda m: m.id == links[0].message)
    if (message is None or message.event != envelope.event
            or message.generation.provenance != envelope.source):
        return None
    return message.generation


@dataclass(frozen=True, slots=True)
class FirstEnd:
    envelope: Envelope
    receipt_point: Point
    generation: Generation


def _first_end(view: View, work: str) -> FirstEnd:
    # EndKnown / INV-15.a / paper 794-802,1187. Receipt storage may overtake.
    row = _work(view.core.p, work)
    notice_kind = "DrawReturned" if row.descriptor.stage == "D" else "WorkFinished"
    candidates = []
    for receipt in view.core.p.receipts:
        generation = _generation_for(view.core, receipt.envelope)
        if (generation is not None and generation.work == work
                and receipt.envelope.event.kind == notice_kind):
            candidates.append((receipt.envelope.r.rank, receipt.envelope.receipt_seq, receipt, generation))
    if not candidates:
        raise Disabled("await report")
    _, _, receipt, generation = min(candidates, key=lambda v: (v[0], v[1]))
    envelope = receipt.envelope
    if envelope.run != view.core.h.run:
        raise Disabled("terminal notification from a different run")
    accepted = {r.envelope.key for r in view.core.p.receipts}
    if any(e.receipt_seq < envelope.receipt_seq and e.key not in accepted
           for e in view.core.h.originals):
        raise Disabled("earlier Post not accepted")
    if not _receipt_saved(view.core, receipt):
        raise Disabled("first terminal receipt not saved")
    if (_resolve(view.core, row.descriptor.request) != generation.request
            or row.descriptor.stage != generation.stage):
        raise Disabled("generation does not correspond to work request/stage")
    slot = receipt.unit.slots[0]
    assert slot.prepared is not None
    return FirstEnd(envelope, slot.prepared.point, generation)


def _generation_route(e0: E0, work: str) -> tuple[AllowedPlan, AllowedPlan]:
    """A-GENERATION-WIRE: links are explicit E0 guards, never slot-name guesses."""
    cg = tuple(p for p in e0.plans if Guard("generation", work) in p.guards)
    eq = tuple(p for p in e0.plans if any(g.kind == "evaluation" and g.key == work for g in p.guards))
    if len(cg) != 1 or len(eq) != 1 or len(cg[0].records) != 1 or len(eq[0].records) != 1:
        raise MissingContract("Wg requires one declared CG and EQ route")
    candidate = PlanRef(cg[0].unit, cg[0].records[0].slot)
    if (Guard("evaluation", work, candidate) not in eq[0].guards
            or cg[0].obligation_id != "O-G" or eq[0].obligation_id != "O-G" or cg[0].works
            or cg[0].records[0].contract != Contract("candidate_declaration", "1")
            or cg[0].records[0].content != Source("candidate_declaration", work)
            or eq[0].records[0].contract != Contract("sui.fb.evaluation_request", "1")
            or len(eq[0].works) != 1 or eq[0].works[0].stage != "Ep"
            or eq[0].works[0].request != PlanRef(eq[0].unit, eq[0].records[0].slot)):
        raise MissingContract("undeclared generation/evaluation correspondence")
    return cg[0], eq[0]


def candidate_request_content(d: Descriptor) -> Object:
    """M3 / A-GENERATION-WIRE: Qgen's symbolic full fixed-input field names.

    request itself is the record being named; no circular self Point is stored.
    PlanRefs in this declaration need ordinary TypedReference paths at prepare.
    """
    return obj(process=d.process, trigger=d.trigger, reader=d.reader, purpose=d.purpose,
               stage_slot=d.stage_slot, method=d.method, output_contract=d.output_contract,
               args=d.args, input_points=_sorted(tuple(d.input_points)),
               numerical_view=obj(points=_sorted(tuple(d.numerical_view.points)),
                                  application_order=d.numerical_view.application_order,
                                  context=d.numerical_view.context),
               allocation=d.allocation, need=d.need, permissions=_sorted(tuple(d.permissions)))


def _generation_candidate(view: View, work: str) -> Object:
    """M3: compare whole output to the fixed request/input; no success flag oracle."""
    d = _work(view.core.p, work).descriptor
    first = _first_end(view, work)
    q = _find(view.core.e, lambda e: e.point == first.generation.request)
    if (d.stage != "Wg" or q is None
            or q.header.record.contract != Contract("sui.fb.candidate_request", "1")
            or q.header.record.content != _env_value(view.core, candidate_request_content(d))):
        raise Disabled("generation request does not match full descriptor")
    out = first.generation.outcome
    if out.kind != OutcomeKind.RETURNED or not isinstance(out.content, Object) or out.content.get("variant") != "Candidates":
        raise Disabled("no nonempty generation reply")
    c = out.content.get("declaration")
    if not isinstance(c, Object) or set(k for k, _ in c.items) != {"model", "input_order", "measure", "generation", "continuation"}:
        raise Disabled("incomplete candidate declaration")
    g, order = c.get("generation"), c.get("input_order")
    if (not isinstance(g, Object) or not isinstance(order, tuple) or not order
            or any(not isinstance(v, str) for v in order) or len(set(order)) != len(order)
            or not isinstance(c.get("continuation"), Object)
            or set(k for k, _ in g.items) != {"generator", "args", "basis", "draws"}):
        raise Disabled("incomplete/nonempty candidate generation")
    if d.args.get("draws") != () or g.get("draws") != ():
        raise MissingContract("R10 generation draws are not connected")
    after = c.get("continuation").get("after")
    if (set(k for k, _ in c.get("continuation").items) != {"after"} or not isinstance(after, tuple)
            or any(not isinstance(a, Object) or set(k for k, _ in a.items) != {"candidate", "policy"}
                   or a.get("candidate") not in order for a in after)):
        raise Disabled("incomplete candidate continuation")
    model = d.numerical_view.context.get("model")
    if not isinstance(model, (Point, PlanRef)):
        raise MissingContract("Wg requires an explicit model input")
    basis = d.numerical_view.context.get("generation_basis")
    if not isinstance(basis, tuple) or any(not isinstance(p, (Point, PlanRef)) for p in basis):
        raise MissingContract("Wg requires an explicit generation basis correspondence")
    basis_points = tuple(_resolve(view.core, p) for p in basis)
    if not frozenset(basis_points) <= frozenset(_resolve(view.core, p) for p in _descriptor_refs(d)):
        raise MissingContract("generation basis is outside the fixed input read")
    if (d.output_contract != Contract("sui.fb.candidate_generation", "1")
            or g.get("generator") != d.method or g.get("args") != _env_value(view.core, d.args)
            or g.get("basis") != basis_points
            or c.get("model") != _resolve(view.core, model)
            or not isinstance(first.generation.started, Reading)
            or not isinstance(first.generation.finished, Reading)
            or first.generation.started.run != view.core.h.run
            or first.generation.finished.run != view.core.h.run
            or first.generation.started.rank > first.generation.finished.rank):
        raise Disabled("generation output/input/clock correspondence differs")
    refs = _descriptor_refs(d)
    if not _permit(view, d.use_keys | {("work", work)}, refs):
        raise Disabled("generation use conflict")
    return c


@dataclass(frozen=True, slots=True)
class Clash:
    rule: str
    reports: frozenset[Point]
    affected: frozenset[object]


def _report_key(report: Report) -> object:
    if report.kind == ReportKind.FRAME:
        return ("frame", report.segment, report.fields.get("measurement_id"))
    if report.kind in (ReportKind.GAP, ReportKind.UNAVAILABLE, ReportKind.CLAIM, ReportKind.UNPROVED):
        return ("FAMILY-UNNAMED", report.segment, report.item_slot)
    return ("life", report.segment, report.kind)


def _report_content(report: Report) -> object:
    # Frame item_slot is not CMP-05 identity; named/life reports have own keys.
    return (report.kind, report.route_epoch, report.fields)


def _clashes(view: View, points: frozenset[Point]) -> tuple[Clash, ...]:
    """Window logic only. Future checker must independently implement the paper."""
    raw = []
    for receipt in view.core.p.receipts:
        slot = receipt.unit.slots[0]
        if slot.prepared is None or slot.prepared.point not in points or not _receipt_saved(view.core, receipt):
            continue
        point = slot.prepared.point
        gen = _generation_for(view.core, receipt.envelope)
        report = receipt.envelope.event.fields.get("report")
        if gen is not None:
            raw.append((point, "work", gen))
        elif isinstance(report, Report):
            # Raw unknown references remain saved, but cannot enter Reports(X).
            try:
                _resolve(view.core, report.segment)
            except Disabled:
                continue
            interval = None
            for requested in view.actual.ei.requests:
                try:
                    if _resolve(view.core, requested.point) == report.segment:
                        interval = requested
                        break
                except Disabled:
                    continue
            if interval is not None and report.route_epoch == interval.route_epoch:
                raw.append((point, "segment", report))
    result = []
    for i, (pa, family_a, a) in enumerate(raw):
        for pb, family_b, b in raw[i + 1:]:
            if family_a != family_b:
                continue
            if family_a == "work":
                assert isinstance(a, Generation) and isinstance(b, Generation)
                # Unknown+value alone is not a Clash (595 / 790 / CL-EXECUTION).
                if OutcomeKind.UNKNOWN in (a.outcome.kind, b.outcome.kind):
                    continue
                if a.work == b.work and a != b:
                    affected = frozenset((("work", a.work), ("terminal", a.work),
                                          ("stage", a.request, a.stage)))
                    result.append(Clash("CL-EXECUTION" if a.outcome.kind != b.outcome.kind else "CL-SAME",
                                        frozenset((pa, pb)), affected))
                # CL-DRAW crosses WorkIds. E0 fixes law/args and id components.
                if a.stage == b.stage == "D":
                    da = _work(view.core.p, a.work).descriptor.args
                    db = _work(view.core.p, b.work).descriptor.args
                    ida = tuple(da.get(k) for k in ("domain", "generator", "stream_id", "purpose", "context_key", "ordinal"))
                    idb = tuple(db.get(k) for k in ("domain", "generator", "stream_id", "purpose", "context_key", "ordinal"))
                    if ida == idb and (da != db or a.outcome.content != b.outcome.content):
                        result.append(Clash("CL-DRAW", frozenset((pa, pb)),
                                            frozenset((("draw", ida), ("work", a.work), ("work", b.work)))))
            else:
                assert isinstance(a, Report) and isinstance(b, Report)
                ka, kb = _report_key(a), _report_key(b)
                if ka == kb and _report_content(a) != _report_content(b):
                    result.append(Clash("CL-SAME", frozenset((pa, pb)), frozenset((ka,))))
                if a.kind == b.kind == ReportKind.FRAME:
                    ma, mb = a.fields.get("measurement_id"), b.fields.get("measurement_id")
                    sequence_a = (a.segment, a.route_epoch, a.fields.get("sample_seq"))
                    sequence_b = (b.segment, b.route_epoch, b.fields.get("sample_seq"))
                    if sequence_a == sequence_b and ma != mb:
                        result.append(Clash("CL-SEQ", frozenset((pa, pb)),
                                            frozenset((ka, kb, ("sequence", sequence_a)))))
                    if ma == mb and _report_content(a) != _report_content(b):
                        result.append(Clash("CL-MEASUREMENT", frozenset((pa, pb)),
                                            frozenset((ka, kb, ("measurement", ma)))))
    return _sorted(tuple(set(result)))


def _use_keys(view: View, direct: frozenset[object], refs: frozenset[Ref]) -> frozenset[object]:
    # REF-2/3: traverse U/UE only. No blanket expansion of evidence-only edges.
    keys = set(direct)
    queue = deque(_resolve(view.core, r) for r in refs)
    visited = set()
    while queue:
        point = queue.popleft()
        if point in visited:
            continue
        visited.add(point)
        for unit in _units(view.core.p):
            if any(s.prepared and s.prepared.point == point for s in unit.slots):
                keys.add(unit.key)
        entry = _find(view.core.e, lambda e: e.point == point)
        if entry is None:
            raise Disabled("missing use dependency")
        for ref in entry.header.record.references:
            if ref.role in ("U", "UE"):
                queue.append(_resolve(view.core, ref.ref))
    return frozenset(keys)


def _permit(view: View, keys: frozenset[object], refs: frozenset[Ref] = frozenset()) -> bool:
    dependencies = _use_keys(view, keys, refs)
    return not any(c.affected & dependencies for c in _clashes(view, _visible(view.core)))


def _actual_held(ew: EW, work: str) -> tuple[tuple[str, int], ...]:
    amounts: dict[str, int] = {}
    for fact in ew.events:
        if fact.key != work or fact.kind not in ("Reserve", "Release"):
            continue
        sign = 1 if fact.kind == "Reserve" else -1
        for resource, n in fact.value:
            amounts[resource] = amounts.get(resource, 0) + sign * n
    return tuple(sorted((a, n) for a, n in amounts.items() if n))


def receipt_unit_id(run: str, number: int) -> str:
    # A-RECEIPT / I-1..8: independently implemented injective tuple encoding.
    return "receipt/" + encode((run, number)).hex()


def declare_observation_e0(e0: E0) -> ObservationE0:
    """E0-01..08 / A-FINITE: translate declarations only, before execution.

    This never consults P, a prepared record, a returned value, or an evaluator.
    Relations requiring full port contracts must be supplied by the scene.
    PlanRefs remain declarations; no CID is predicted and no resolver is called.
    Wv args must declare target:UpdateTarget, check_view:frozenset[Ref],
    registry:str, checker:Contract. No missing argument is filled from a reply.
    VerificationBinding uses descriptor.reader/numerical_view/input_points and
    the entire args Object; input_points is the declared evidence_closure.
    A-CALL-ID fixes its key to VerificationKey(work_id, verification_call_id()).
    A-T-PLAN supplies declared_plans(e0) to ObservationE0.plans before execution.
    MDeclRef permits Source only in declared RecordPlan.references[*].ref and
    parents. Publication expands Sources; PlanRefs may remain until preparation.
    Actual Record references and Header/PreparedEntry parents must be Points.
    A missing Source input remains unavailable; no receipt id or CID is predicted.
    The V-only definite_verification guard is a
    model spelling for the actual Wv Returned VerificationReply condition (1219).
    """
    descriptors = tuple(w for p in e0.plans for w in p.works)
    completions = []
    kinds = e0.receipt_kinds
    external_kinds = {p.event.kind for p in e0.postings}
    if not kinds and len(external_kinds) == 1 and not e0.unknown_notices and not any(p.replies for p in e0.programs):
        kind = next(iter(external_kinds))
        kinds = tuple((n, kind) for n in range(len(e0.postings)))
    for number, kind in kinds:
        unit = receipt_unit_id(e0.run, number)
        slots = ("boot", "declaration") if kind == "Boot" else ("receipt",)
        for slot in slots:
            target = SlotKey(unit, slot)
            key = CompletionKey("O-01", (e0.run, number), "save", target)
            completions.append(CompletionBinding(key, "Post", ReceiptKey(e0.run, number),
                                                 (target,), Owner("H", (e0.run, number))))
    for plan in e0.plans:
        for record in plan.records:
            target = SlotKey(plan.unit, record.slot)
            key = CompletionKey(plan.obligation_id, plan.key, "save", target)
            completions.append(CompletionBinding(key, "Publish", UnitKey(plan.unit),
                                                 (target,), Owner("P.units", plan.unit)))
        for work in plan.works:
            oid = {"MeasureSegment": "O-04", "Wr": "O-05", "Wp": "O-07", "Wv": "O-09.a",
                   "Wg": "O-G", "Ep": "O-10", "D": "O-11", "Ee": "O-12"}[work.stage]
            target = WorkKey(work.work_id)
            identity = ("work", work.work_id)
            for obligation, kind in ((oid, "run"), ("O-14", "stop")):
                completions.append(CompletionBinding(CompletionKey(obligation, identity, kind, target),
                    "Publish", UnitKey(plan.unit), (), Owner("P.work", work.work_id)))
            if work.stage != "MeasureSegment":
                terminal = SlotKey("terminal:" + work.work_id, "T")
                completions.append(CompletionBinding(CompletionKey(oid, ("terminal", work.work_id), "save", terminal),
                    "EndKnown", target, (terminal,), Owner("P.work", work.work_id)))
                completions.append(CompletionBinding(CompletionKey(oid, identity, "handle", target),
                    "EndKnown", target, (), Owner("P.work", work.work_id)))
            if work.stage == "Wg":
                cg, eq = _generation_route(e0, work.work_id)
                for successor, trigger, source in ((cg, "EndKnown", target), (eq, "Publish", UnitKey(cg.unit))):
                    slot = SlotKey(successor.unit, successor.records[0].slot)
                    completions.append(CompletionBinding(
                        CompletionKey("O-G", identity, "issue", slot), trigger, source,
                        (slot,), Owner("P.work", work.work_id) if trigger == "EndKnown" else Owner("P.units", cg.unit)))
    unknowns = tuple(HostUnknownBinding(n.work, "host:" + n.id,
                                       d.request, d.stage, n.basis)
                     for n in e0.unknown_notices for d in descriptors if d.work_id == n.work)
    # E0-01 / PATH-* (1076-1086), A-REFERENCE-PATH: retain tuple-array
    # wildcard rules with their full use/role/operation; closure is still separate.
    references = tuple(ReferenceBinding(r.record_contract, r.path_id, r.path, r.role,
                                        r.use, "PrepareOne",
                                        "unsupported" if r.path_id == "PATH-QOBS" else "direct")
                       for r in e0.field_roles)
    intervals = tuple(IntervalBinding(IntervalKey(k.id, k.route_epoch, k.interval.run),
                                       k.point, k.work, k.interval, e0.endpoints,
                                       k.measurement_contract, k.clock_contract)
                       for k in e0.intervals)
    acquisitions = tuple(AcquisitionBinding(IntentKey(a.reader, a.id), a.targets,
                                             a.completion, a.required_ancestors, a.record)
                         for a in e0.acquisitions)
    verifications = tuple(VerificationBinding(VerificationKey(d.work_id, verification_call_id()),
                            d.args.get("target"), d.reader, d.numerical_view, d.input_points,
                            d.args.get("check_view"), d.args.get("registry"), d.args.get("checker"), d.args)
                          for d in descriptors if d.stage == "Wv"
                          and isinstance(d.args.get("target"), UpdateTarget)
                          and isinstance(d.args.get("check_view"), frozenset)
                          and isinstance(d.args.get("registry"), str)
                          and isinstance(d.args.get("checker"), Contract))
    adoptions = tuple(AdoptionBinding(IntentKey(a.reader, a.id), a.completion, a.result,
                                       a.previous_result, VerificationKey(a.verification_work, verification_call_id()),
                                       tuple(IntentKey(a.reader, i) for i in a.acquisitions), a.re_adoption)
                      for a in e0.adoptions)
    return ObservationE0(plans=declared_plans(e0), descriptors=descriptors,
                         capacity=e0.capacity, allocation=e0.allocation,
                         generation_sources=tuple((d.work_id, "worker:" + d.work_id) for d in descriptors),
                         host_unknowns=unknowns, completions=tuple(completions),
                         acquisitions=acquisitions, verifications=verifications, adoptions=adoptions,
                         references=references, intervals=intervals)


def _owner_exists(core: Core, owner: Owner) -> bool:
    if owner.location == "H":
        return (any(e.key == owner.key for e in core.h.queue)
                or any(k.id == owner.key for k in core.h.interval_requests))
    if owner.location == "P.receipts":
        return any(r.envelope.key == owner.key for r in core.p.receipts)
    if owner.location == "P.units":
        return any(u.id == owner.key for u in core.p.units)
    if owner.location == "P.work":
        return any(w.descriptor.work_id == owner.key for w in core.p.work)
    return False


def _move_conditions(p: Custody, source: Owner, destination: Owner,
                     obligation: str, obligation_key: object) -> tuple[Custody, tuple[Effect, ...]]:
    # 1193: preserve EVERY unmet key/target for this owner and obligation group.
    selected = tuple(c for c in p.conditions if c.owner == source and c.unmet
                     and (c.key.obligation, c.key.obligation_key) == (obligation, obligation_key))
    keys = frozenset(c.key for c in selected)
    changed = tuple(replace(c, owner=destination) if c.key in keys else c for c in p.conditions)
    effects = tuple(Effect("HandoffPurpose", c.key, destination) for c in selected)
    return replace(p, conditions=changed), effects


class CorrectWindow:
    """Stateless implementation. E0 is its immutable declaration, not an oracle."""

    def __init__(self, e0: E0):
        self.e0 = e0

    def _normal(self, view: View) -> None:
        if not view.controls.normal_window:
            raise Disabled("window unavailable")

    def _plan(self, unit: str) -> AllowedPlan:
        plan = _find(declared_plans(self.e0), lambda p: p.unit == unit)
        if plan is None:
            raise MissingContract("undeclared plan")
        return plan

    def _guards(self, view: View, plan: AllowedPlan) -> None:
        self._normal(view)
        if plan.semantic_limits:
            raise MissingContract(",".join(plan.semantic_limits))
        if plan.obligation_id == "O-02":
            # C-O02.issue is born from SAVED Boot and declaration, not E0.initial
            # alone, and never from a window-produced ready bit.
            boot = _find(view.core.p.receipts, lambda r: r.envelope.event.kind == "Boot"
                         and _receipt_saved(view.core, r))
            if boot is None or self.e0.initial is None:
                raise Disabled("initial application requires Saved Boot/declaration")
            declaration = boot.envelope.event.fields.get("declaration")
            if declaration.get("initial") != self.e0.initial:
                raise Disabled("Boot declaration differs from fixed initial declaration")
        for guard in plan.guards:
            if guard.kind in ("saved", "generation_context"):
                _resolve(view.core, guard.key)
            elif guard.kind == "generation":
                cg, _ = _generation_route(self.e0, str(guard.key))
                if plan != cg:
                    raise Disabled("different CG route")
                _generation_candidate(view, str(guard.key))
            elif guard.kind == "evaluation":
                cg, eq = _generation_route(self.e0, str(guard.key))
                if plan != eq:
                    raise Disabled("different EQ route")
                candidate_point = _resolve(view.core, guard.value)
                candidate = _find(view.core.e, lambda e: e.point == candidate_point)
                if candidate.header.record.content != _generation_candidate(view, str(guard.key)):
                    raise Disabled("saved CG differs from first generation")
                content = _env_value(view.core, self._source(view, eq.records[0].content))
                d = _work(view.core.p, str(guard.key)).descriptor
                if (not isinstance(content, Object) or {k for k, _ in content.items} !=
                        {"candidates", "reader", "model", "preferences", "context", "o", "j"}
                        or content.get("candidates") != candidate_point
                        or content.get("reader") != _resolve(view.core, d.reader)
                        or any(content.get(k) is None for k in ("model", "preferences", "context", "o", "j"))):
                    raise Disabled("incomplete evaluation request/context")
                if any(not isinstance(content.get(k), Point) for k in ("candidates", "reader", "model", "context")):
                    raise Disabled("evaluation input must be a typed reference")
                for key in ("preferences", "o", "j"):
                    value = content.get(key)
                    if (not isinstance(value, Point) and
                            (not isinstance(value, tuple) or any(not isinstance(p, Point) for p in value)
                             or key == "preferences" and not value)):
                        raise Disabled("evaluation evidence binding type differs")
                refs = frozenset(_resolve(view.core, r) for r in _generation_refs(content))
                ep = eq.works[0]
                ep_inputs = frozenset(_resolve(view.core, r) for r in _descriptor_refs(ep) if r != ep.request)
                numerical = _resolved_numerical(view.core, ep)
                input_points = frozenset(_resolve(view.core, r) for r in ep.input_points) | numerical.points
                evaluation_points = _generation_refs(obj(**{k: v for k, v in content.items if k != "reader"}))
                if (not refs <= ep_inputs or ep.purpose != d.purpose or ep.reader != d.reader
                        or not evaluation_points <= input_points
                        or not isinstance(numerical.context, Object)
                        or any(content.get(k) != numerical.context.get(k) for k in ("model", "context"))
                        or any(content.get(k) != v for k, v in numerical.context.items if k in ("preferences", "o", "j"))):
                    raise Disabled("EQ inputs differ from fixed Ep inputs")
                if not _permit(view, eq.use_keys | {("work", str(guard.key))}, refs | {candidate_point}):
                    raise Disabled("evaluation use conflict")
            elif guard.kind == "initial":
                if self.e0.initial is None:
                    raise Disabled("NoInitial")
            elif guard.kind in ("first", "outcome"):
                first = _first_end(view, str(guard.key))
                if guard.kind == "outcome":
                    content = first.generation.outcome.content
                    variant = (content.response if isinstance(content, VerificationReply)
                               else content.get("variant") if isinstance(content, Object) else None)
                    if (first.generation.outcome.kind.value, variant) != guard.value:
                        raise Disabled("different terminal branch")
            elif guard.kind == "acquired":
                if not any(a.intent == guard.key for a in view.actual.ea.acquisitions):
                    raise Disabled("no actual acquisition")
            elif guard.kind == "definite_verification":
                gen = _first_end(view, str(guard.key)).generation
                if (gen.stage != "Wv" or gen.outcome.kind != OutcomeKind.RETURNED
                        or not isinstance(gen.outcome.content, VerificationReply)):
                    raise Disabled("no actual definite verification reply")
            elif guard.kind == "interval_intent":
                if not any(k.id == guard.key for k in view.core.h.interval_requests):
                    raise Disabled("no actual interval request undertaking")
            else:
                raise MissingContract("undeclared guard semantics")
        if not _permit(view, plan.use_keys):
            raise Disabled("known upstream conflict")

    def _source(self, view: View, value: object) -> object:
        if isinstance(value, Source):
            if value.kind == "first_receipt":
                return _first_end(view, value.key).receipt_point
            if value.kind == "generation":
                generation = _first_end(view, value.key).generation
                if generation.provenance.startswith("host:"):
                    raise MissingContract("A-SOURCE: host Unknown is not a worker Generation")
                return generation
            if value.kind == "outcome":
                return _first_end(view, value.key).generation.outcome
            if value.kind == "candidate_declaration":
                return _generation_candidate(view, value.key)
            if value.kind in ("outcome_kind", "outcome_content", "terminal_basis", "terminal_view"):
                first = _first_end(view, value.key)
                if value.kind == "outcome_kind":
                    return first.generation.outcome.kind
                if value.kind == "outcome_content":
                    return first.generation.outcome.content
                if value.kind == "terminal_view":
                    return _visible(view.core)
                outcome = first.generation.outcome
                if outcome.kind == OutcomeKind.FAILURE:
                    return first.generation
                if outcome.kind != OutcomeKind.UNKNOWN:
                    return None
                return outcome.content
            if value.kind in ("started_clock", "finished_clock"):
                generation = _first_end(view, value.key).generation
                if generation.provenance.startswith("host:"):
                    raise MissingContract("A-SOURCE: host Unknown has no worker generation clock")
                return generation.started if value.kind == "started_clock" else generation.finished
            if value.kind in ("acquisition", "acquisition_clock"):
                acquisition = _find(view.actual.ea.acquisitions, lambda a: a.intent == value.key)
                if acquisition is None:
                    raise Disabled("no actual acquisition")
                return acquisition.reading if value.kind == "acquisition_clock" else acquisition
            if value.kind == "numerical_view":
                return _resolved_numerical(view.core, _work(view.core.p, value.key).descriptor)
            raise MissingContract("undeclared source")
        if isinstance(value, Object):
            return Object(tuple((k, self._source(view, v)) for k, v in value.items))
        if isinstance(value, tuple):
            return tuple(self._source(view, v) for v in value)
        if isinstance(value, frozenset):
            return frozenset(self._source(view, v) for v in value)
        return value

    def _publication_record(self, view: View, record: RecordPlan) -> RecordPlan:
        """A-SOURCE / A-T-PLAN: expand Source from actual inputs at Publish.

        first_receipt becomes its Saved Point. Published request PlanRefs may
        remain; preparation resolves them to Points in Record/Header/PreparedEntry.
        No CID or future EP fixed value is predicted.
        """
        content = self._source(view, record.content)
        # F-a 66 / P-08: a missing clock remains a Generation shortage. This
        # also guards direct RecordPlan recipes that bypass the public factory.
        # PublishUnit expands every record before adding ANY slot/successor.
        if record.contract == Contract("clock_reading", "1") and not isinstance(content.get("reading"), Reading):
            raise Disabled("clock_reading/1 requires an available Reading")
        return replace(record, content=content,
                       references=tuple(replace(r, ref=self._source(view, r.ref)) for r in record.references),
                       parents=frozenset(self._source(view, p) for p in record.parents))

    def accept(self, view: View, envelope: Envelope) -> Decision:
        self._normal(view)
        p, core = view.core.p, view.core
        original = _find(core.h.originals, lambda e: e.key == envelope.key)
        if original is None or original != envelope:
            # CMP-01 / INV-1.b: includes kind/full contents/r/seq/run.
            return Decision(p, result="host_fault")
        if not core.h.queue or core.h.queue[0].key != envelope.key:
            raise Disabled("not HostEligible")
        receipt = _find(p.receipts, lambda r: r.envelope.key == envelope.key)
        if receipt is not None:
            acceptance = Acceptance(envelope, receipt.unit.id, tuple(s.plan for s in receipt.unit.slots))
            return Decision(p, (Effect("Accept", envelope.key, acceptance),), acceptance)
        if not _well_formed(envelope.event):
            return Decision(p, result="shape_error")
        if envelope.r.run != core.h.run or envelope.r.rank > core.h.reading.rank:
            return Decision(p, result="host_clock_fault")
        layout = next(r for r in self.e0.observation_contract.receipt_layouts
                      if r.kind == envelope.event.kind)
        plans = []
        for slot, name, version in layout.slots:
            contract = Contract(name, version)
            plans.append(Slot(RecordPlan(slot, contract, "Event",
                                        obj(writer="MEMBRANE", route=layout.route, contract=contract,
                                            content=envelope.event, caused_by=None, source_id=None,
                                            source_time_ns=None, received_ns=envelope.r),
                                        parents=layout.parents, at=core.h.reading)))
        unit = Unit(receipt_unit_id(envelope.run, envelope.number), "O-01", envelope.key,
                    tuple(plans), (), _visible(core))
        receipt = Receipt(envelope, unit)
        acceptance = Acceptance(envelope, unit.id, tuple(s.plan for s in unit.slots))
        p = replace(p, receipts=p.receipts + (receipt,))
        p, handoffs = _move_conditions(p, Owner("H", envelope.key), Owner("P.receipts", envelope.key),
                                      "O-01", envelope.key)
        return Decision(p, (Effect("Accept", envelope.key, acceptance),) + handoffs, acceptance)

    def publish_unit(self, view: View, plan_id: str) -> Decision:
        # O-xx / EU / INV-2.b: SAME update owns slots and ALL successor work rows.
        plan = self._plan(plan_id)
        if plan.operation == "RecognizeTerminal":
            raise Disabled("terminal recipes require RecognizeTerminal")
        self._guards(view, plan)
        p = view.core.p
        if any(u.id == plan.unit for u in p.units):
            raise Disabled("already published")
        if len({w.work_id for w in plan.works}) != len(plan.works):
            raise Disabled("duplicate declared WorkId")
        if any(any(r.descriptor.work_id == w.work_id for r in p.work) for w in plan.works):
            raise Disabled("work already undertaken")
        if self.e0.initial is None and any(w.stage != "MeasureSegment" for w in plan.works):
            raise Disabled("NoInitial cannot issue bootstrap computation")
        records = tuple(self._publication_record(view, r) for r in plan.records)
        continuation = None
        for guard in plan.guards:
            if guard.kind not in ("generation", "evaluation"):
                continue
            d = _work(p, str(guard.key)).descriptor
            cg, eq = _generation_route(self.e0, d.work_id)
            candidate, evaluation = PlanRef(cg.unit, cg.records[0].slot), PlanRef(eq.unit, eq.records[0].slot)
            origin = CompletionKey("O-G", ("work", d.work_id), "run", WorkKey(d.work_id))
            purpose = PurposePart(origin, (d.purpose, d.process, d.reader, d.request, d.stage_slot), d.request)
            continuation = GenerationContinuation(d, candidate, evaluation, purpose, _work(p, d.work_id).purposes)
            if guard.kind == "evaluation":
                # EQ's usable inputs are fixed NOW, after CG, not backfilled into Qgen.
                records = tuple(replace(r, content=_env_value(view.core, r.content),
                    references=tuple(replace(t, ref=_env_value(view.core, t.ref)) for t in r.references),
                    parents=frozenset(_env_value(view.core, ref) for ref in r.parents)) for r in records)
        unit = Unit(plan.unit, plan.obligation_id, plan.key, tuple(Slot(r) for r in records),
                    tuple(w.work_id for w in plan.works), _visible(view.core), continuation)
        new_p = replace(p, units=p.units + (unit,),
                        work=p.work + tuple(WorkRow(w) for w in plan.works))
        # EU is observed by Environment, not written here.
        return Decision(new_p, (Effect("Publish", unit.id, (unit, plan.works)),), unit)

    def recognize(self, view: View, plan_id: str) -> Decision:
        return self.publish_unit(view, plan_id)

    def recognize_terminal(self, view: View, work: str) -> Decision:
        self._normal(view)
        row = _work(view.core.p, work)
        if row.knowledge is not None:
            raise Disabled("terminal already fixed")
        first = _first_end(view, work)
        gen = first.generation
        if gen.stage == "MeasureSegment":
            raise MissingContract("MeasureSegment uses interval reports, not this T contract")
        # T and definite Wv V are E diagnostics; no Conflict gate here (1189).
        # A-T-PLAN / INV-2.b: recipes exist before any returned value is known.
        plans = [self._plan("terminal:" + work)]
        if gen.stage == "Wv" and gen.outcome.kind == OutcomeKind.RETURNED:
            if not isinstance(gen.outcome.content, VerificationReply):
                raise MissingContract("undeclared verification reply")
            # Insufficient is a definite reply; requires BOTH T and V.
            plans.append(self._plan("verification:" + work))
        units = []
        for plan in plans:
            self._guards(view, plan)
            if any(u.id == plan.unit for u in view.core.p.units):
                raise Disabled("terminal unit already published")
            slots = tuple(Slot(self._publication_record(view, r)) for r in plan.records)
            units.append(Unit(plan.unit, plan.obligation_id, plan.key, slots, (), _visible(view.core)))
        new_row = replace(row, knowledge=gen.outcome, first=first.envelope.key)
        p = _with_work(view.core.p, new_row)
        p = replace(p, units=p.units + tuple(units))
        return Decision(p, tuple(Effect("Publish", u.id, (u, ())) for u in units), tuple(units))

    def _prepare(self, view: View, key: tuple[str, str], raw: bool) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        if slot.prepared is not None:
            raise Disabled("preparation already fixed")
        body = slot.plan.content
        resolved = []
        for ref in slot.plan.references:
            declared = _find(self.e0.references, lambda p: p.id == ref.path_id)
            if declared is None:
                raise MissingContract("undeclared reference path")
            conversion = _find(self.e0.field_roles,
                               lambda r: r.record_contract == slot.plan.contract and r.path_id == ref.path_id
                               and len(r.path) == len(ref.path)
                               and all(a == b or a == "*" and isinstance(b, int) for a, b in zip(r.path, ref.path))
                               and r.use == ref.use and r.role == ref.role)
            if conversion is None:
                raise MissingContract("E0-01/03: exact record/field/use/role conversion is undeclared")
            point = _resolve(view.core, ref.ref)
            # Source expansion may already have materialized this body field.
            # Compare against the declared target; never infer it from the body.
            if _path(body, ref.path) not in (ref.ref, point):
                raise Disabled("reference path differs from fixed plan")
            body = _put_path(body, ref.path, point)
            resolved.append(replace(ref, ref=point))
        if not raw and _plan_refs(body):
            raise MissingContract("unlisted/unresolved internal PlanRef")
        parents = frozenset(_resolve(view.core, p) for p in slot.plan.parents)
        for point in parents:
            entry = _find(view.core.e, lambda e: e.point == point)
            if entry is None or entry.header.record.category != "Event":
                raise Disabled("Prediction cannot be a causal parent")
        reading = slot.plan.at or view.core.h.reading
        if raw:
            original = _find(view.core.p.receipts, lambda r: r.unit.id == key[0])
            if original is None or reading.rank < original.envelope.r.rank:
                raise HostFault("r exceeds actual generation reading s")
        record = Record((key[0] + "/" + key[1]) if raw else f"{key[0]}:{key[1]}", reading, slot.plan.contract,
                        slot.plan.category, body, tuple(resolved))
        payload = encode(record)
        # 紙に無い仮定 A-SALT: deterministic symbolic salt(name) is a finite
        # representative of an independently allocated fresh salt. It is not
        # F-a's random salt generation and cannot establish its wire compatibility.
        salt = digest(("model-salt", record.name)).encode("ascii")
        seal = _seal(payload, salt)
        header = Header(record, seal, parents)
        prepared = PreparedEntry(record, parents, salt, payload, seal, header, Point(digest(header)))
        p = _with_slot(view.core.p, key, replace(slot, prepared=prepared))
        return Decision(p, (Effect("Prepare", key, prepared),), prepared)

    def prepare_receipt(self, view: View, key: tuple[str, str]) -> Decision:
        # PATH-RECEIPT: raw event names/claims do not require semantic resolution.
        return self._prepare(view, key, raw=True)

    def prepare_one(self, view: View, key: tuple[str, str]) -> Decision:
        return self._prepare(view, key, raw=False)

    def put_body(self, view: View, key: tuple[str, str], mode: str) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        if slot.prepared is None or slot.body_confirmed or not view.controls.body_put:
            raise Disabled("PutBody precondition")
        return Decision(view.core.p, (Effect("PutBody", key, slot.prepared),))

    def body_response(self, view: View, key: tuple[str, str], reply: str) -> Decision:
        slot = _slot(view.core.p, key)
        prepared = slot.prepared
        if prepared is None:
            raise Disabled("response without preparation")
        if reply == "normal":
            body = _find(view.core.c, lambda b: b.seal == prepared.seal)
            if body != Body(prepared.seal, prepared.salt, prepared.payload):
                raise Disabled("body response mismatch")
            return Decision(_with_slot(view.core.p, key, replace(slot, body_confirmed=True)))
        return Decision(view.core.p)

    def confirm_body(self, view: View, key: tuple[str, str]) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        if slot.prepared is None or slot.body_confirmed or not view.controls.body_read:
            raise Disabled("ConfirmBody precondition")
        prepared = slot.prepared
        body = _find(view.core.c, lambda b: b.seal == prepared.seal)
        if body != Body(prepared.seal, prepared.salt, prepared.payload):
            raise Disabled("body missing/mismatch")
        return Decision(_with_slot(view.core.p, key, replace(slot, body_confirmed=True)),
                        (Effect("ReadBody", key, body),))

    def add_entry(self, view: View, key: tuple[str, str], mode: str) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        if slot.prepared is None or not slot.body_confirmed or slot.entry_confirmed or not view.controls.entry_add:
            raise Disabled("AddEntry precondition")
        if _find(view.core.c, lambda b: b.seal == slot.prepared.seal) != Body(slot.prepared.seal, slot.prepared.salt, slot.prepared.payload):
            raise Disabled("actual body differs")
        return Decision(view.core.p, (Effect("AddEntry", key, slot.prepared),))

    def entry_response(self, view: View, key: tuple[str, str], reply: str) -> Decision:
        # SAVE-7: response is not the full C/E confirmation. ConfirmWrite is
        # explicit for normal AND lost responses, preserving its fair target.
        return Decision(view.core.p)

    def confirm_write(self, view: View, key: tuple[str, str]) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        prepared = slot.prepared
        if prepared is None or slot.entry_confirmed or not (view.controls.body_read and view.controls.entry_read):
            raise Disabled("ConfirmWrite precondition")
        if not _saved(view.core, prepared.point):
            raise Disabled("not actually saved")
        entry = _find(view.core.e, lambda e: e.point == prepared.point)
        body = _find(view.core.c, lambda b: b.seal == prepared.seal)
        if entry != Entry(prepared.point, prepared.header) or body != Body(prepared.seal, prepared.salt, prepared.payload):
            raise Disabled("full PreparedEntry readback mismatch")
        return Decision(_with_slot(view.core.p, key, replace(slot, body_confirmed=True, entry_confirmed=True)),
                        (Effect("ReadEntry", key, (body, entry)),))

    def complete_write(self, view: View, key: tuple[str, str]) -> Decision:
        self._normal(view)
        slot = _slot(view.core.p, key)
        if slot.prepared is None or not slot.entry_confirmed or slot.completed or not _saved(view.core, slot.prepared.point):
            raise Disabled("CompleteWrite precondition")
        # Retain the preparation/correspondence. No work/stop/purpose is deleted.
        p = _with_slot(view.core.p, key, replace(slot, completed=True))
        effects = []
        for planned in view.actual.ea.adoption_plans:
            if planned.value.get("unit") != key[0]:
                continue
            unit = _find(_units(p), lambda u: u.id == key[0])
            if (unit is not None and all(s.prepared and _saved(view.core, s.prepared.point)
                                         for s in unit.slots)
                    and not any(a.key == planned.key for a in view.actual.ea.adoptions)):
                p = replace(p, adoption_reservations=tuple((r, i) for r, i in p.adoption_reservations
                                                          if i != planned.key))
                effects.append(Effect("AdoptionCommit", planned.key, planned.value))
        return Decision(p, tuple(effects))

    def resolve_work(self, view: View, work: str) -> Decision:
        self._normal(view)
        row = _work(view.core.p, work)
        pairs = tuple(sorted(((r, _resolve(view.core, r)) for r in _descriptor_refs(row.descriptor)
                              if isinstance(r, PlanRef)), key=encode))
        if pairs == row.resolutions:
            raise Disabled("no unresolved work references")
        if any(pair not in pairs for pair in row.resolutions):
            raise Disabled("attempt to retarget resolved PlanRef")
        return Decision(_with_work(view.core.p, replace(row, resolutions=pairs)))

    def _start_ready(self, view: View, row: WorkRow, owner: str) -> None:
        normal = {"window": view.controls.normal_window, "host": view.controls.normal_host,
                  "wrapper": view.controls.normal_wrapper}[owner]
        if not normal or row.consumed or row.start_unknown or row.knowledge is not None or row.stopped:
            raise Disabled("StartReady false")
        if row.descriptor.semantic_limits:
            raise MissingContract(",".join(row.descriptor.semantic_limits))
        if row.descriptor.method == Contract("finite_update", "2"):
            raise MissingContract("PATH-QOBS: bootstrap finite_update/2 numerical projection")
        if row.descriptor.stage == "Wg":
            d = row.descriptor
            if d.args.get("draws") != ():
                raise MissingContract("R10 generation draws are not connected")
            request = _resolve(view.core, d.request)
            q = _find(view.core.e, lambda e: e.point == request)
            if (q.header.record.contract != Contract("sui.fb.candidate_request", "1")
                    or q.header.record.content != _env_value(view.core, candidate_request_content(d))):
                raise Disabled("generation request does not match full descriptor")
        for unit in view.core.p.units:
            if unit.generation is not None and row.descriptor.work_id in unit.works:
                _generation_candidate(view, unit.generation.descriptor.work_id)
        if row.descriptor.stage == "Wv":
            args = row.descriptor.args
            if (not isinstance(args.get("target"), UpdateTarget)
                    or not isinstance(args.get("check_view"), frozenset)
                    or not isinstance(args.get("registry"), str)
                    or not isinstance(args.get("checker"), Contract)):
                raise MissingContract("Wv target/check_view/registry/checker must be fixed explicitly")
        refs = _descriptor_refs(row.descriptor)
        for ref in refs:
            point = _resolve(view.core, ref)
            if isinstance(ref, PlanRef) and (ref, point) not in row.resolutions:
                raise Disabled("work PlanRef resolution not fixed yet")
        if not _permit(view, row.descriptor.use_keys, refs):
            raise Disabled("new entry/use blocked by conflict")
        # This slice fixes the allocation/permission declaration; withdrawal and
        # allocation changes are E0-08 exclusions, not an assumed forever-valid
        # permission in a future extended model.

    def claim_start(self, view: View, work: str) -> Decision:
        row = _work(view.core.p, work)
        self._start_ready(view, row, "window")
        if row.phase != "Pending" or row.token is not None:
            raise Disabled("not START-0")
        allocation = dict(self.e0.allocation)
        used: dict[str, int] = {}
        for fact in view.actual.ew.events:
            if fact.kind in ("Reserve", "Release"):
                sign = 1 if fact.kind == "Reserve" else -1
                for resource, n in fact.value:
                    used[resource] = used.get(resource, 0) + sign * n
        held = dict(_actual_held(view.actual.ew, work))
        if any(max(n - held.get(a, 0), 0) > allocation.get(a, 0) - used.get(a, 0)
               for a, n in row.descriptor.need):
            raise Disabled("B-RESOURCE for this work only")
        token = digest(("start-token", work))
        row = replace(row, phase="Starting", token=token, held=row.descriptor.need)
        return Decision(_with_work(view.core.p, row),
                        (Effect("Reserve", work, obj(token=token, descriptor=row.descriptor,
                                                     resources=row.descriptor.need)),))

    def launch(self, view: View, work: str) -> Decision:
        row = _work(view.core.p, work)
        self._start_ready(view, row, "host")
        if row.phase != "Starting" or row.token is None:
            raise Disabled("not START-1/2")
        live = tuple(w for w in view.core.wrappers if w.work == work and w.status == "launched")
        if live:
            raise Disabled("already launched")
        if _actual_held(view.actual.ew, work) != row.descriptor.need:
            raise Disabled("no actual held reservation")
        return Decision(view.core.p, (Effect("Launch", work, row.token),))

    def launch_response(self, view: View, work: str, reply: str) -> Decision:
        row = _work(view.core.p, work)
        if reply in ("uncertain_before", "uncertain_after"):
            return Decision(_with_work(view.core.p, replace(row, start_unknown=True)))
        # A known pre-entry failure retains the SAME token and actual holding.
        return Decision(view.core.p)

    def enter_worker(self, view: View, wrapper: str) -> Decision:
        package = _find(view.core.wrappers, lambda w: w.id == wrapper)
        if package is None or package.status != "launched":
            raise Disabled("wrapper not live")
        row = _work(view.core.p, package.work)
        self._start_ready(view, row, "wrapper")
        if row.phase != "Starting" or row.token != package.token:
            raise Disabled("wrong start token")
        row = replace(row, consumed=True, phase="Running")
        return Decision(_with_work(view.core.p, row),
                        (Effect("Enter", package.id,
                                (row.descriptor.work_id, package.token,
                                 _resolved_numerical(view.core, row.descriptor))),))

    def worker_step(self, view: View, work: str) -> Decision:
        # Runner belongs to the worker: window abnormality does not gate it.
        runner = _find(view.core.runners, lambda r: r.work == work and not r.stopped)
        program = _find(self.e0.programs, lambda p: p.work == work)
        if runner is None or program is None or runner.step >= len(program.replies):
            raise Disabled("no next actual program step (may be Hung)")
        return Decision(view.core.p, (Effect("WorkerStep", work, program.replies[runner.step]),))

    def stop(self, view: View, work: str) -> Decision:
        row = _work(view.core.p, work)
        program = _find(self.e0.programs, lambda p: p.work == work)
        runner = _find(view.core.runners, lambda r: r.work == work)
        if row.stopped or program is None or not program.stop_available:
            raise Disabled("no actual stopping confirmation available")
        if runner is not None:
            if runner.stopped or runner.step < len(program.replies):
                raise Disabled("worker still has actual steps")
        elif not row.start_unknown:
            raise Disabled("no execution or uncertain launch to examine")
        return Decision(_with_work(view.core.p, replace(row, stopped=True, phase="Stopped")),
                        (Effect("Stop", work, "stopped" if runner else "certain_never_started"),))

    def release(self, view: View, work: str) -> Decision:
        row = _work(view.core.p, work)
        if row.released or not row.held or not row.stopped:
            raise Disabled("release requires actual stop, once")
        if not any(f.kind == "Stop" and f.key == work for f in view.actual.ew.events):
            raise Disabled("missing independent stop observation")
        return Decision(_with_work(view.core.p, replace(row, held=(), released=True)),
                        (Effect("Release", work, row.held),))

    def acquire(self, view: View, intent: str) -> Decision:
        self._normal(view)
        declared = _find(self.e0.acquisitions, lambda a: a.id == intent)
        if declared is None:
            raise MissingContract("undeclared acquisition intent")
        if declared.semantic_limits:
            raise MissingContract(",".join(declared.semantic_limits))
        if any(a.intent == intent for a in view.actual.ea.acquisitions):
            raise Disabled("actual acquisition already performed")
        _resolve(view.core, declared.reader)
        _resolve(view.core, declared.completion)
        for point in declared.targets | declared.required_ancestors:
            _resolve(view.core, point)
        if not _permit(view, declared.use_keys, declared.targets):
            raise Disabled("acquisition uses conflicted generation")
        # The actual event occurs independently; a G recipe with acquired guard
        # then atomically publishes G + Wv. G is never published BEFORE this.
        return Decision(view.core.p, (Effect("Acquire", intent, declared),))

    def handoff_purpose(self, view: View, key: CompletionKey, destination: Owner) -> Decision:
        # C-O01..14 / paper 1185,1193. Overridable transition, not an oracle.
        self._normal(view)
        current = _find(view.core.p.conditions, lambda c: c.key == key)
        if current is None or not current.unmet or current.owner == destination:
            raise Disabled("condition is absent, achieved, or already held here")
        if not _owner_exists(view.core, current.owner) or not _owner_exists(view.core, destination):
            raise Disabled("handoff must have actual source and destination carriers")
        p, effects = _move_conditions(view.core.p, current.owner, destination, key.obligation, key.obligation_key)
        return Decision(p, effects)

    def adopt(self, view: View, intent: str) -> Decision:
        self._normal(view)
        declared = _find(self.e0.adoptions, lambda a: a.id == intent)
        if declared is None:
            raise MissingContract("undeclared adoption intent")
        reader = _resolve(view.core, declared.reader)
        if any(a.key == intent for a in view.actual.ea.adoptions):
            raise Disabled("adoption intent already handled")
        if any(r == reader for r, _ in view.core.p.adoption_reservations):
            raise Disabled("reader already has pending adoption unit")
        first = _first_end(view, declared.verification_work)
        reply = first.generation.outcome.content
        if first.generation.outcome.kind != OutcomeKind.RETURNED or not isinstance(reply, VerificationReply):
            raise Disabled("no definite target verification")
        if reply.response != "Success" or not isinstance(reply.certificate, Certificate):
            raise Disabled("Rejected/Insufficient/Unknown is not certification")
        # PATH-LINK-ACQUISITION's real certificate wire is not specified. A finite
        # declared recipe MAY represent the control boundary; not F-a validity.
        if reply.reader != reader:
            raise Disabled("different verification reader")
        call = _find(view.actual.ea.calls, lambda c: c.work == declared.verification_work)
        if (call is None or reply.target != call.target or reply.numerical_view != call.input_read
                or reply.check_view != call.check_view
                or reply.registry != call.arguments.get("registry")
                or reply.checker != call.arguments.get("checker")):
            raise Disabled("verification reply differs from actual fixed call")
        if (declared.verification_work, reply) not in view.actual.ea.replies:
            raise Disabled("verification response not actually observed")
        certificate = reply.certificate
        if (declared.verification_work, certificate) not in view.actual.ea.issued:
            raise Disabled("no actual issued-port value")
        if (certificate.target != reply.target or certificate.reader != reply.reader
                or certificate.target_contents != reply.target_contents
                or certificate.numerical_view != reply.numerical_view
                or certificate.evidence_closure != reply.evidence_closure
                or certificate.check_view != reply.check_view
                or certificate.registry != reply.registry or certificate.checker != reply.checker
                or certificate.result_digest != digest(reply.result)):
            raise Disabled("certificate full target/response binding differs")
        target = reply.target
        if (not isinstance(target, UpdateTarget)
                or target.completion != _resolve(view.core, declared.completion)
                or target.result != _resolve(view.core, declared.result)):
            raise Disabled("verification certifies another target")
        needed = frozenset((target.result, *target.proofs))
        acquired = frozenset()
        for acquisition in declared.acquisitions:
            actual = _find(view.actual.ea.acquisitions, lambda a: a.intent == acquisition)
            if actual is None or actual.reader != reader:
                raise Disabled("missing actual reader acquisition")
            acquired |= actual.targets
            # Acquisitions must have declared real causal ancestors. The A
            # recipe must include G as an ancestor through its fixed parent DAG.
        if not needed <= acquired:
            raise Disabled("R/all proofs not actually acquired")
        if not _permit(view, frozenset((("work", declared.verification_work),)),
                       frozenset((declared.completion, declared.result))):
            raise Disabled("adoption conflict")
        existing = [a for a in view.actual.ea.adoptions if a.value.get("reader") == reader and a.value.get("outcome") == "Adopted"]
        previous_result = existing[-1].value.get("result") if existing else None
        wanted = _resolve(view.core, declared.previous_result) if declared.previous_result else None
        stale = not declared.re_adoption and previous_result != wanted
        decision = self.publish_unit(view, declared.stale_plan if stale else declared.plan)
        reservations = decision.custody.adoption_reservations + ((reader, intent),)
        p = replace(decision.custody, adoption_reservations=reservations)
        # Commit after the A/ST slot is Saved, not at Publish; Environment checks
        # this reservation's actual completion during later CompleteWrite.
        effect = Effect("AdoptionPlan", intent,
                        obj(reader=reader, result=_resolve(view.core, declared.result),
                            completion=_resolve(view.core, declared.completion),
                            previous_result=previous_result, outcome="Stale" if stale else "Adopted",
                            unit=declared.stale_plan if stale else declared.plan))
        return Decision(p, decision.effects + (effect,), decision.result)

    def drain(self, view: View) -> Decision:
        pending = []
        for row in view.core.p.work:
            if row.phase != "Pending":
                continue
            try:
                self._start_ready(view, row, "window")
            except Disabled:
                continue
            pending.append(row.descriptor)
        return Decision(view.core.p, result=tuple(pending))

    def rebuild_window(self, view: View) -> Decision:
        if view.controls.normal_window:
            raise Disabled("window already normal")
        return Decision(view.core.p, (Effect("Rebuild", "window"),))

    def enabled(self, view: View) -> tuple[Action, ...]:
        """Enumerate ALL successful OR failing branches without POR (paper 429).

        A prerequisite failure disables an operation; an offered I/O failure
        branch remains enabled. The checker will later independently require
        missing operations from E0/EH/EW/EL; it must not infer Ready from this list.
        """
        candidates = []
        if view.core.h.queue:
            candidates.append(Action("Accept", (view.core.h.queue[0],)))
        for unit in _units(view.core.p):
            for slot in unit.slots:
                key = (unit.id, slot.plan.slot)
                operation = "PrepareReceipt" if any(r.unit.id == unit.id for r in view.core.p.receipts) else "PrepareOne"
                candidates.append(Action(operation, key))
                for op in ("PutBody", "AddEntry"):
                    candidates.append(Action(op, key))
                    if view.controls.budget.precommit_failures:
                        candidates.append(Action(op, key, "precommit_failure"))
                    if view.controls.budget.lost_responses:
                        candidates.append(Action(op, key, "lost_response"))
                candidates.extend(Action(op, key) for op in ("ConfirmBody", "ConfirmWrite", "CompleteWrite"))
        for plan in self.e0.plans:
            if plan.operation in ("PublishUnit", "Recognize"):
                candidates.append(Action(plan.operation, (plan.unit,)))
        for row in view.core.p.work:
            work = row.descriptor.work_id
            candidates.extend(Action(op, (work,)) for op in ("ResolveWork", "ClaimStart", "Launch", "WorkerStep", "Stop", "Release", "RecognizeTerminal"))
            if view.controls.budget.launch_failures:
                candidates.append(Action("Launch", (work,), "before_entry_failure"))
            if view.controls.budget.uncertain_launches:
                candidates.extend(Action("Launch", (work,), mode) for mode in ("uncertain_before", "uncertain_after"))
        candidates.extend(Action("EnterWorker", (w.id,)) for w in view.core.wrappers)
        candidates.extend(Action("Acquire", (a.id,)) for a in self.e0.acquisitions)
        candidates.extend(Action("HandoffPurpose", (r.key, r.destination)) for r in self.e0.handoff_routes)
        candidates.extend(Action("Adopt", (a.id,)) for a in self.e0.adoptions)
        candidates.append(Action("RebuildWindow"))
        # Drain/Wait have genuine self-edges. Repeated enumeration never removes.
        candidates.extend((Action("Drain"), Action("Wait")))
        enabled = []
        for action in candidates:
            try:
                self.dispatch(view, action)
            except Disabled:
                continue
            enabled.append(action)
        return _sorted(tuple(set(enabled)))

    def dispatch(self, view: View, action: Action) -> Decision:
        # Public method dispatch is dynamic: subclasses override individual walks.
        operation = action.operation
        if operation == "Wait":
            return Decision(view.core.p)
        method_name = {
            "Accept": "accept", "PublishUnit": "publish_unit", "Recognize": "recognize",
            "RecognizeTerminal": "recognize_terminal", "PrepareReceipt": "prepare_receipt",
            "PrepareOne": "prepare_one", "PutBody": "put_body", "AddEntry": "add_entry",
            "ConfirmBody": "confirm_body", "ConfirmWrite": "confirm_write", "CompleteWrite": "complete_write",
            "ResolveWork": "resolve_work", "ClaimStart": "claim_start", "Launch": "launch",
            "EnterWorker": "enter_worker", "WorkerStep": "worker_step", "Stop": "stop", "Release": "release",
            "Acquire": "acquire", "Adopt": "adopt", "Drain": "drain", "RebuildWindow": "rebuild_window",
            "HandoffPurpose": "handoff_purpose",
        }.get(operation)
        if method_name is None:
            raise Disabled("not a window operation")
        method = getattr(self, method_name)
        if operation in ("PutBody", "AddEntry"):
            return method(view, action.target, action.outcome)
        if operation in ("PrepareReceipt", "PrepareOne", "ConfirmBody", "ConfirmWrite", "CompleteWrite"):
            return method(view, action.target)
        return method(view, *action.target)


def _well_formed(event: Event) -> bool:
    # §2-4-7: reject only outer shape. Byte meaning and unknown names not rejected.
    f = event.fields
    if event.kind == "Boot":
        return tuple(k for k, _ in f.items) == ("declaration",) and isinstance(f.get("declaration"), Object)
    if event.kind == "Received":
        return (tuple(k for k, _ in f.items) == ("claims", "data", "media_type", "route_epoch")
                and isinstance(f.get("data"), bytes) and isinstance(f.get("media_type"), str)
                and isinstance(f.get("route_epoch"), str))
    if event.kind == "SegmentReport":
        return tuple(k for k, _ in f.items) == ("report",) and isinstance(f.get("report"), Report)
    if event.kind == "WorkFinished":
        return (tuple(k for k, _ in f.items) == ("finished", "outcome", "started", "work")
                and isinstance(f.get("work"), str) and isinstance(f.get("outcome"), Outcome)
                and isinstance(f.get("started"), (Reading, Unavailable))
                and isinstance(f.get("finished"), (Reading, Unavailable)))
    if event.kind == "DrawReturned":
        return (tuple(k for k, _ in f.items) == ("outcome", "work")
                and isinstance(f.get("work"), str) and isinstance(f.get("outcome"), Outcome))
    return False


def _env_value(core: Core, value: object) -> object:
    """Environment program substitution, independent of window recipe sources.

    Only explicitly typed PlanRefs are resolved; strings/bytes stay untouched.
    This is a program's actual input/output wiring, not an expected plan copied
    from what the window produced. Correctness of the program is not asserted.
    """
    if isinstance(value, PlanRef):
        return _resolve(core, value)
    if isinstance(value, Object):
        return Object(tuple((k, _env_value(core, v)) for k, v in value.items))
    if isinstance(value, tuple):
        return tuple(_env_value(core, v) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_env_value(core, v) for v in value)
    if is_dataclass(value):
        return replace(value, **{f.name: _env_value(core, getattr(value, f.name)) for f in fields(value)})
    return value


def _program_value(value: object, references: tuple[tuple[PlanRef, Point], ...],
                   core: Core | None = None) -> object:
    """Resolve program output against the worker's ACTUAL frozen entry input."""
    if isinstance(value, PlanRef):
        point = next((p for ref, p in references if ref == value), None)
        if point is None:
            raise MissingContract("program requests a PlanRef absent from its actual entry input")
        return point
    if isinstance(value, ReadContents):
        if core is None:
            raise MissingContract("actual contents port requires C/E")
        points = _program_value(value.points, references, core)
        if any(not _saved(core, p) for p in points):
            raise Disabled("actual contents port cannot read an unsaved target")
        return _sorted(tuple((p, _find(core.c, lambda b: b.seal ==
            _find(core.e, lambda e: e.point == p).header.seal).payload) for p in points))
    if isinstance(value, Object):
        return Object(tuple((k, _program_value(v, references, core)) for k, v in value.items))
    if isinstance(value, tuple):
        return tuple(_program_value(v, references, core) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_program_value(v, references, core) for v in value)
    if is_dataclass(value):
        return replace(value, **{f.name: _program_value(getattr(value, f.name), references, core) for f in fields(value)})
    return value


class Environment:
    """Only writer of actual observations; never calls a window expectation helper.

    Window decisions are requests. Store bodies/headers, reservation amounts,
    input reads, returns and actual acquisitions are recorded from the request
    actually performed and actual backing values. EU is deliberately descriptive.
    E0 remains the independently authored normative input, even for bad requests.
    """

    def __init__(self, e0: E0):
        self.e0 = e0
        self.observation_contract = e0.observation_contract
        self._edge_events: list[ObservationEvent] = []

    @staticmethod
    def _notice_message_id(notice: WorkerNotice | HostNotice) -> str:
        # A-DELIVERY-BUNDLE: translate a declared selector, never a claimed Event.
        if isinstance(notice, WorkerNotice):
            return f"report:{notice.work}:{notice.reply}"
        if isinstance(notice, HostNotice):
            return "host-unknown:" + notice.notice
        raise ValueError("unknown delivery notice selector")

    def _bundle_messages(self, state: State, bundle: DeliveryBundle) -> tuple[Message, ...]:
        messages = tuple(_find(state.core.network.messages, lambda m: m.id == self._notice_message_id(n))
                         for n in bundle.notices)
        if any(m is None or m.deliveries != 0 for m in messages):
            raise Disabled("bundle waits for all actual, not previously delivered messages")
        return messages

    def _emit(self, state: State, *events: ObservationEvent) -> State:
        """A-TAGS/A-IO: record performed port operations, never P status bits.

        Only identical I/O is omitted inside a state. Every edge call survives,
        and every EW occurrence is retained, including duplicated wrappers.
        """
        self._edge_events.extend(events)
        trace = state.evidence.observation_trace
        history = list(trace.events if trace is not None else ())
        for event in events:
            if event.tag not in ("IORequest", "IOResponse", "ReadBack") or event not in history:
                history.append(event)
        return replace(state, evidence=replace(state.evidence, observation_trace=ObservationTrace(
            tuple(history), frozenset(state.core.c), frozenset(state.core.e), state.core.h.reading)))

    def presentation_cut(self, state: State, action: Action) -> bool:
        # A-PRESENT: do NOT change Enabled or custody from an observation count.
        return (action.operation == "Accept" and
                sum(e.tag == "Present" and e.key == ReceiptKey(*action.target[0].key)
                    for e in state.evidence.observation_trace.events) >= self.e0.presentation_limit)

    def _token(self, state: State, work: str) -> WorkToken:
        # Actual reservation/runner tokens survive edits or deletion of P rows.
        runner = _find(state.core.runners, lambda r: r.work == work)
        if runner is not None:
            return WorkToken(work, runner.token)
        reserve = _find(tuple(reversed(state.evidence.observation_trace.events)),
                        lambda e: e.tag == "Reserve" and e.key.work == work)
        if reserve is None:
            raise MissingContract("actual operation has no retained reservation token")
        return reserve.key

    def _close_save(self, state: State, key: tuple[str, str]) -> State:
        # C-O01..14 (1185-1194): actual Saved conclusion, not Slot.completed.
        closed = {e.key for e in state.evidence.observation_trace.events if e.tag == "CloseSave"}
        for binding in self.observation_contract.completions:
            if (binding.key.kind != "save" or binding.key in closed
                    or SlotKey(*key) not in binding.slots):
                continue
            firsts = {e.key: e.value.prepared for e in state.evidence.observation_trace.events
                      if e.tag == "FirstPrepare"}
            if all(s in firsts and _saved(state.core, firsts[s].point) for s in binding.slots):
                state = self._emit(state, ObservationEvent("CloseSave", binding.key, CloseSave(binding.slots)))
        return state

    def _condition_occurrence_owner(self, state: State, binding: CompletionBinding) -> Owner | None:
        """1186: occurrence from actual EH/EW/EL/EU/EA/EI; NEVER binding.owner.

        P.conditions is the joint logical custody map, including the host's
        still-held originals. Owners name actual containers, not phase values.
        """
        core, trace = state.core, state.evidence.observation_trace
        try:
            source = _env_value(core, binding.source)
        except Disabled:
            return None
        if binding.trigger == "IntervalRequest":
            request = _find(state.evidence.ei.requests, lambda k: k.id == source.request)
            return Owner("H", request.id) if request is not None else None
        if binding.trigger == "EndKnown":
            try:
                _first_end(View(core, state.controls, state.evidence), source.work)
                if binding.key.obligation == "O-G" and binding.key.kind == "issue":
                    _generation_candidate(View(core, state.controls, state.evidence), source.work)
            except Disabled:
                return None
            return Owner("P.work", source.work)
        tag = {"Post": "Post", "Publish": "Publish", "Acquire": "Acquire", "Reserve": "Reserve"}[binding.trigger]
        actual = _find(trace.events, lambda e: e.tag == tag and e.key == source)
        if actual is None:
            return None
        if tag == "Post":
            key = (source.run, source.number)
            return Owner("P.receipts" if any(r.envelope.key == key for r in core.p.receipts) else "H", key)
        if tag == "Reserve":
            return Owner("P.work", source.work)
        if tag == "Publish":
            if isinstance(binding.key.target, WorkKey) and any(
                    w.work_id == binding.key.target.work for w in actual.value.plan.works):
                return Owner("P.work", binding.key.target.work)
            if isinstance(binding.key.target, IntentKey):
                candidates = tuple(w for w in actual.value.plan.works if w.stage == "Wv")
                if len(candidates) == 1:
                    return Owner("P.work", candidates[0].work_id)
            return Owner("P.units", source.unit)
        # Acquire is undertaken by the retained actual Cq/request container.
        declaration = _find(self.e0.acquisitions, lambda a: a.id == source.intent)
        if declaration is None:
            return None
        point = _resolve(core, declaration.completion)
        for unit in _units(core.p):
            if any(s.prepared and s.prepared.point == point for s in unit.slots):
                receipt = _find(core.p.receipts, lambda r: r.unit.id == unit.id)
                return Owner("P.receipts", receipt.envelope.key) if receipt else Owner("P.units", unit.id)
        return None  # no invented carrier for an unrepresented seed/foreign Point

    def _generation_custody(self, state: State) -> State:
        """M3: retain concrete pG witnesses; never infer a purpose from a wait bit.

        Ordinary receipt/CG save waits do not create pG. Explicit context-use
        shortages, Conflict and non-success do. Existing pG is never discharged.
        """
        p = state.core.p
        view = View(state.core, state.controls, state.evidence)
        for row in p.work:
            d = row.descriptor
            if d.stage != "Wg":
                continue
            try:
                first = _first_end(view, d.work_id)
            except Disabled:
                continue
            cg, eq = _generation_route(self.e0, d.work_id)
            origin = CompletionKey("O-G", ("work", d.work_id), "run", WorkKey(d.work_id))
            purpose = PurposePart(origin, (d.purpose, d.process, d.reader, d.request, d.stage_slot), d.request)
            reasons = []
            try:
                _generation_candidate(view, d.work_id)
            except Disabled as error:
                reasons.append((str(error), first.generation))
            # 1956: a declared CG/EQ use shortage seen after EndKnown enters the
            # pG branch then, even if the context is saved before CG PUB.
            for guard in cg.guards + eq.guards:
                if guard.kind == "generation_context":
                    try:
                        _resolve(state.core, guard.key)
                    except Disabled:
                        reasons.append(("evaluation context unavailable", guard.key))
            if any(e.tag == "Publish" and e.key == UnitKey(cg.unit)
                   for e in state.evidence.observation_trace.events):
                eq_content, ep = eq.records[0].content, eq.works[0]
                # M3: an unconfirmed predecessor Point is a save wait, not pG.
                if (eq_content.get("model") != ep.numerical_view.context.get("model")
                        or ep.reader != d.reader or ep.purpose != d.purpose):
                    reasons.append(("evaluation input correspondence differs", eq_content))
                if eq.semantic_limits:
                    reasons.append(("evaluation contract unavailable", eq.semantic_limits))
                if not _permit(view, eq.use_keys | {("work", d.work_id)}):
                    reasons.append(("evaluation use conflict", eq.use_keys))
            excuses = tuple(Excuse("O-G", purpose, reason, witness, _visible(state.core), ("pG",))
                            for reason, witness in reasons)
            # Keep the first witness for each reason/target; repeated drains do
            # not grow custody merely because the visible root has grown.
            additions = tuple(e for e in excuses if not any(
                (old.reason_id, old.witness) == (e.reason_id, e.witness) for old in row.purposes))
            if additions:
                p = _with_work(p, replace(row, purposes=row.purposes + additions))
        units = tuple(replace(u, generation=replace(u.generation,
                      shortages=_work(p, u.generation.descriptor.work_id).purposes))
                      if u.generation is not None else u for u in p.units)
        return replace(state, core=replace(state.core, p=replace(p, units=units)))

    def _refresh_conditions(self, state: State) -> State:
        # C-O01..14 instances: all five kinds are retained, with explicit targets.
        # The independent occurrence journal prevents repairs hiding P deletions.
        rows = state.core.p.conditions
        births = state.evidence.condition_births
        for binding in self.observation_contract.completions:
            if binding.key in births:
                continue
            owner = self._condition_occurrence_owner(state, binding)
            if owner is not None:
                births |= {binding.key}
                if not any(c.key == binding.key for c in rows):
                    rows += (ConditionCustody(binding.key, owner, frozenset((binding.key,))),)
        state = self._generation_custody(state)
        changed = []
        for row in rows:
            key, reached = row.key, False
            if key.kind == "save":
                binding = _find(self.observation_contract.completions, lambda b: b.key == key)
                try:
                    reached = binding is not None and bool(binding.slots) and all(
                        _saved(state.core, _resolve(state.core, PlanRef(s.unit, s.slot))) for s in binding.slots)
                except Disabled:
                    pass
            elif key.kind == "issue" and isinstance(key.target, SlotKey):
                reached = any(u.id == key.target.unit and any(s.plan.slot == key.target.slot for s in u.slots)
                              for u in state.core.p.units)
                if key.obligation == "O-G":
                    plan = _find(self.e0.plans, lambda p: p.unit == key.target.unit)
                    unit = _find(state.core.p.units, lambda u: u.id == key.target.unit)
                    published = any(e.tag == "Publish" and e.key == UnitKey(key.target.unit)
                                    for e in state.evidence.observation_trace.events)
                    reached = reached and published and unit.generation is not None
                    if reached:
                        reached = all(any(c.key == CompletionKey("O-10", ("work", d.work_id), "run", WorkKey(d.work_id))
                                          for c in rows) for d in plan.works)
                        if not plan.works:  # CG must simultaneously own save[CG] and issue[EQ].
                            reached = all(any(c.key == required for c in rows) for required in (
                                CompletionKey("O-G", plan.key, "save", key.target),
                                CompletionKey("O-G", key.obligation_key, "issue",
                                              SlotKey(unit.generation.evaluation.unit, unit.generation.evaluation.slot))))
            elif key.kind == "run" and isinstance(key.target, WorkKey):
                try:
                    _first_end(View(state.core, state.controls, state.evidence), key.target.work)
                    reached = True
                except Disabled:
                    pass
            elif key.kind == "stop" and isinstance(key.target, WorkKey):
                reached = (any(f.kind == "Stop" and f.key == key.target.work for f in state.evidence.ew.events)
                           and not _actual_held(state.evidence.ew, key.target.work))
            elif key.obligation == "O-G" and key.kind == "handle":
                work = _work(state.core.p, key.target.work)
                successor = _find(state.core.p.units, lambda u: u.generation is not None
                                  and u.generation.descriptor.work_id == key.target.work)
                if successor is not None:
                    row = replace(row, owner=Owner("P.units", successor.id))
                    reached = True  # Transfer to the retained generation continuation.
                else:
                    reached = bool(work.purposes)  # Same-owner acceptance of pG; no Direct(pG).
            # handle conclusions require their branch semantics; handoff alone
            # NEVER clears them. Unsupported meanings remain explicitly unmet.
            changed.append(replace(row, unmet=frozenset()) if reached and row.unmet else row)
        p = replace(state.core.p, conditions=_sorted(tuple(changed)))
        return replace(state, core=replace(state.core, p=p),
                       evidence=replace(state.evidence, condition_births=births))

    def initial(self, controls: Controls | None = None) -> State:
        require_frozen(self.e0)
        if len(set(p.id for p in self.e0.postings)) != len(self.e0.postings):
            raise ValueError("duplicate environment posting identifier")
        if len(set(p.unit for p in self.e0.plans)) != len(self.e0.plans):
            raise ValueError("duplicate E0 plan identifier")
        if self.e0.delivery_limit < 1:
            raise ValueError("delivery limit must be at least one")
        if self.e0.presentation_limit < 1:
            raise ValueError("presentation_limit must be at least one")
        # SC-15 / A-DELIVERY-BUNDLE: validate the pre-run wiring, not EW facts.
        if len({b.id for b in self.e0.delivery_bundles}) != len(self.e0.delivery_bundles):
            raise ValueError("duplicate delivery bundle identifier")
        selected = set()
        descriptors = tuple(w for p in self.e0.plans for w in p.works)
        for bundle in self.e0.delivery_bundles:
            if not bundle.id or len(bundle.notices) < 2:
                raise ValueError("a delivery bundle needs an identifier and at least two notices")
            for notice in bundle.notices:
                message_id = self._notice_message_id(notice)
                if message_id in selected:
                    raise ValueError("delivery bundles must have disjoint, unique notices")
                selected.add(message_id)
                if isinstance(notice, WorkerNotice):
                    programs = tuple(p for p in self.e0.programs if p.work == notice.work)
                    if (len(programs) != 1 or notice.reply < 0 or notice.reply >= len(programs[0].replies)
                            or sum(d.work_id == notice.work for d in descriptors) != 1):
                        raise ValueError("worker notice must select a declared Program reply and work")
                else:
                    notices = tuple(n for n in self.e0.unknown_notices if n.id == notice.notice)
                    if len(notices) != 1 or sum(d.work_id == notices[0].work for d in descriptors) != 1:
                        raise ValueError("host notice must select a declared UnknownNotice and work")
        allocation, capacity = dict(self.e0.allocation), dict(self.e0.capacity)
        if any(n < 0 or n > capacity.get(a, 0) for a, n in allocation.items()):
            raise ValueError("allocation exceeds independent capacity declaration")
        if tuple(sorted(set(self.e0.endpoints))) != self.e0.endpoints:
            raise ValueError("endpoints must be ordered and unique")
        core = Core(Host(self.e0.run, Reading(self.e0.run, self.e0.clock_source, 0)),
                    receipt_sources=self.observation_contract.receipt_sources)
        controls = controls or Controls(budget=self.e0.budget)
        # E0.intervals are intended requests, NOT already occurred EI requests.
        state = State(core, controls, Evidence(ei=EI(), el=EL(),
                                              observation_trace=ObservationTrace((), clock=core.h.reading)))
        require_frozen(state)
        return state

    def actions(self, state: State) -> tuple[Action, ...]:
        core, control = state.core, state.controls
        actions = []
        if control.normal_host:
            for request in self.e0.intervals:
                if not any(k.id == request.id for k in core.h.interval_requests):
                    actions.append(Action("RequestInterval", (request.id,)))
            for notice in self.e0.unknown_notices:
                if any(m.id == "host-unknown:" + notice.id for m in core.network.messages):
                    continue
                descriptor = _find(tuple(w for p in self.e0.plans for w in p.works), lambda w: w.work_id == notice.work)
                if descriptor is None:
                    continue
                try:
                    _resolve(core, descriptor.request)
                except Disabled:
                    continue
                if all(any(f.kind == kind and f.key == notice.work for f in state.evidence.ew.events)
                       for kind in notice.after_facts):
                    actions.append(Action("HostUnknown", (notice.id,)))
            for posting in self.e0.postings:
                if posting.id in core.network.posted:
                    continue
                try:
                    for ref in posting.after:
                        _resolve(core, ref)
                except Disabled:
                    continue
                actions.append(Action("Post", (posting.id,)))
            for message in core.network.messages:
                bundled_first = message.deliveries == 0 and any(
                    message.id == self._notice_message_id(n) for b in self.e0.delivery_bundles for n in b.notices)
                if message.deliveries < self.e0.delivery_limit and not bundled_first:
                    actions.append(Action("Deliver", (message.id,)))
            for bundle in self.e0.delivery_bundles:
                try:
                    self._bundle_messages(state, bundle)
                except Disabled:
                    continue
                actions.append(Action("DeliverBundle", (bundle.id,)))
            if core.h.queue:
                e = core.h.queue[0]
                if any(r.envelope == e for r in core.p.receipts):
                    actions.append(Action("HostAck", e.key))
                if any(f.key == e.key and f.value == "shape_error" for f in state.evidence.eh.presentations):
                    actions.append(Action("RejectHost", e.key))
        if control.normal_window and control.budget.window_faults:
            actions.append(Action("FaultWindow"))
        if not control.normal_host:
            actions.append(Action("RecoverHost"))
        if not control.normal_wrapper:
            actions.append(Action("RecoverWrapper"))
        if not (control.body_put and control.body_read and control.entry_add and control.entry_read):
            actions.append(Action("RecoverStore"))
        if control.budget.duplicate_wrappers:
            for wrapper in core.wrappers:
                if wrapper.status == "launched":
                    actions.append(Action("DuplicateWrapper", (wrapper.id,)))
        for occurrence in self.e0.interval_occurrences:
            if occurrence.id in state.evidence.ei.occurred:
                continue
            if not any(k.id == occurrence.event.interval_request for k in core.h.interval_requests):
                continue
            if occurrence.requires_entered_work is not None and not any(r.work == occurrence.requires_entered_work for r in core.runners):
                continue
            try:
                evidence_refs = (frozenset((occurrence.event.evidence_point,))
                                 if occurrence.event.evidence_point is not None else frozenset())
                for ref in occurrence.after | evidence_refs:
                    _resolve(core, ref)
            except Disabled:
                continue
            actions.append(Action("IntervalEvent", (occurrence.id,)))
        return _sorted(tuple(actions))

    def _post(self, state: State, event: Event, source: str, rank: int) -> tuple[State, Fact]:
        core, eh = state.core, state.evidence.eh
        number = len(eh.originals)
        # Same-run monotone ranks; equal r preserved and ordered by receipt_seq.
        reading = Reading(self.e0.run, self.e0.clock_source, max(rank, core.h.reading.rank))
        envelope = Envelope(self.e0.run, number, reading, number, event, source)
        h = replace(core.h, reading=reading, queue=core.h.queue + (envelope,),
                    originals=core.h.originals + (envelope,))
        eh = replace(eh, originals=eh.originals + (envelope,))
        state = replace(state, core=replace(core, h=h), evidence=replace(state.evidence, eh=eh))
        state = self._emit(state, ObservationEvent("Post", ReceiptKey(envelope.run, envelope.number), Posted(envelope)))
        return state, Fact("Post", envelope.key, envelope)

    def _tick(self, state: State) -> tuple[State, Reading]:
        # 紙に無い仮定 A-CLOCK: actual starts/returns use the next finite rank.
        # Post ties use the current rank; the order/ties of these model actions
        # are preserved. A scenario needing simultaneous generation must supply
        # a different declared clock schedule; these smoke cases do not prove it.
        reading = replace(state.core.h.reading, rank=state.core.h.reading.rank + 1)
        return replace(state, core=replace(state.core, h=replace(state.core.h, reading=reading))), reading

    def _deliver(self, state: State, message: Message) -> tuple[State, Fact]:
        # E0-05 / PATH-LINK-GENERATION (1016,1092,1187): producer facts come
        # from the actual message, never the expected source table in E0.
        state, actual = self._post(state, message.event, message.generation.provenance, state.core.h.reading.rank)
        network = replace(state.core.network, messages=_replace_item(state.core.network.messages, message,
                            replace(message, deliveries=message.deliveries + 1)),
                          deliveries=state.core.network.deliveries + (Delivery(actual.value, message.id),))
        state = replace(state, core=replace(state.core, network=network))
        notice = _find(self.e0.unknown_notices, lambda n: message.id == "host-unknown:" + n.id)
        if notice is not None:
            desc = _find(self.observation_contract.descriptors, lambda d: d.work_id == notice.work)
            witnesses = tuple(e for e in state.evidence.observation_trace.events
                              if e.tag in ("EnterBody", "LaunchResponse", "Stop") and e.key.work == notice.work)
            state = self._emit(state, ObservationEvent("HostUnknown", WorkKey(notice.work),
                UnknownObserved(actual.value, desc.request, desc.stage, notice.basis, witnesses)))
        return state, actual

    def _entered(self, state: State, wrapper: str, work: str,
                 token: str, numerical: NumericalView) -> tuple[State, tuple[Fact, ...]]:
        state, reading = self._tick(state)
        core, evidence = state.core, state.evidence
        package = _find(core.wrappers, lambda w: w.id == wrapper)
        if package is None:
            raise Disabled("actual wrapper absent")
        desc = _work(core.p, work).descriptor
        actual_desc = _env_value(core, desc)
        reference_read = tuple(sorted(((ref, _resolve(core, ref)) for ref in _descriptor_refs(desc)
                                       if isinstance(ref, PlanRef)), key=encode))
        runner = Runner(work, token, numerical, reading,
                        descriptor_read=actual_desc, reference_read=reference_read)
        core = replace(core, wrappers=_replace_item(core.wrappers, package, replace(package, status="entered")),
                       runners=core.runners + (runner,))
        facts = (Fact("TokenConsumed", work, token), Fact("BodyEntered", work, (wrapper, reading)),
                 Fact("InputRead", work, numerical), Fact("DescriptorRead", work, actual_desc))
        ew = replace(evidence.ew, events=evidence.ew.events + facts)
        ea = evidence.ea
        if desc.stage == "Wv":
            check_view = actual_desc.args.get("check_view")
            if not isinstance(check_view, frozenset):
                raise MissingContract("Wv must explicitly fix check_view in call arguments")
            call = VerificationCall(work, actual_desc.args.get("target"), numerical,
                                    check_view, actual_desc.args)
            ea = replace(ea, calls=ea.calls + (call,))
            facts += (Fact("VerificationCall", work, call),)
        state = replace(state, core=core, evidence=replace(evidence, ew=ew, ea=ea))
        key = WorkToken(work, token)
        state = self._emit(state, ObservationEvent("ConsumeToken", key, WrapperEvent(wrapper)),
                          ObservationEvent("EnterBody", key, BodyEntered(wrapper, reading)),
                          ObservationEvent("ReadInputs", key, InputRead(actual_desc, numerical, reference_read)))
        if desc.stage == "Wv":
            state = self._emit(state, ObservationEvent("VerifyCall", VerificationKey(work, verification_call_id()),
                                                       VerificationInvoked(call)))
        return state, facts

    def _effect(self, state: State, effect: Effect, action: Action,
                window: CorrectWindow) -> tuple[State, tuple[Fact, ...]]:
        core, evidence = state.core, state.evidence
        kind, key, value = effect.kind, effect.key, effect.value
        fact = Fact(kind, key, value)
        if kind == "Accept":
            eh = replace(evidence.eh, accepts=evidence.eh.accepts | {fact})
            if not any(f.key == key for f in eh.generations):
                eh = replace(eh, generations=eh.generations | {Fact("ReceiptGeneratedReading", key, core.h.reading)})
            created = _find(eh.generations, lambda f: f.key == key).value
            state = replace(state, evidence=replace(evidence, eh=eh))
            state = self._emit(state, ObservationEvent("Accept", ReceiptKey(*key),
                Accepted(value.envelope, value.unit, value.plans, created)))
            return state, (fact,)
        if kind == "Publish":
            eu = replace(evidence.eu, publications=evidence.eu.publications | {fact})
            state = replace(state, evidence=replace(evidence, eu=eu))
            unit, works = value
            declared = _find(declared_plans(self.e0), lambda p: p.unit == unit.id)
            # Retain all actual records/descriptors, including illegal promises.
            # Metadata describing the requested recipe does not make EU correct.
            actual = AllowedPlan(unit.id, unit.obligation_id, unit.key,
                                 tuple(s.plan for s in unit.slots), works,
                                 declared.guards if declared else (), declared.use_keys if declared else frozenset(),
                                 declared.operation if declared else action.operation,
                                 declared.semantic_limits if declared else ())
            state = self._emit(state, ObservationEvent("Publish", UnitKey(str(key)), Published(actual)))
            return state, (fact,)
        if kind == "Prepare":
            ep = replace(evidence.ep, first_preparations=evidence.ep.first_preparations | {fact})
            # Actual s reading is captured separately, not asserted from Record.at.
            receipt = _find(core.p.receipts, lambda r: r.unit.id == key[0])
            original_reading = (_find(evidence.eh.generations, lambda f: f.key == receipt.envelope.key)
                                if receipt is not None else None)
            clock = Fact("GenerationReading", key, original_reading.value if original_reading else core.h.reading)
            ep = replace(ep, first_preparations=ep.first_preparations | {clock})
            state = replace(state, evidence=replace(evidence, ep=ep))
            state = self._emit(state, ObservationEvent("FirstPrepare", SlotKey(*key), FirstPrepared(value)))
            return state, (fact, clock)
        if kind in ("PutBody", "AddEntry"):
            mode = action.outcome
            budget = state.controls.budget
            if mode == "precommit_failure":
                if budget.precommit_failures <= 0:
                    raise Disabled("no precommit failure budget")
                budget = replace(budget, precommit_failures=budget.precommit_failures - 1)
            elif mode == "lost_response":
                if budget.lost_responses <= 0:
                    raise Disabled("no response loss budget")
                budget = replace(budget, lost_responses=budget.lost_responses - 1)
            elif mode != "normal":
                raise Disabled("undeclared I/O result")
            prepared = value
            if not isinstance(prepared, PreparedEntry):
                raise Disabled("invalid I/O request type")
            io_key = IOKey(SlotKey(*key), kind, "write/" + mode)
            state = self._emit(state, ObservationEvent("IORequest", io_key, IORequest(prepared)))
            evidence = state.evidence
            written = None
            if mode != "precommit_failure":
                if kind == "PutBody":
                    body = Body(prepared.seal, prepared.salt, prepared.payload)
                    existing = _find(core.c, lambda b: b.seal == prepared.seal)
                    if existing is not None and existing != body:
                        raise Disabled("actual store detects seal conflict")
                    core = replace(core, c=_sorted(tuple(set(core.c + (body,)))))
                    written = body
                else:
                    entry = Entry(prepared.point, prepared.header)
                    existing = _find(core.e, lambda e: e.point == prepared.point)
                    if existing is not None and existing != entry:
                        raise Disabled("actual store detects CID conflict")
                    core = replace(core, e=_sorted(tuple(set(core.e + (entry,)))))
                    written = entry
                    # Actual writing actor's declared port program performs its
                    # causal reads. NEVER infer causes from prepared.parents or
                    # the visible ledger. First preparations are retained in EP.
                    port = _find(self.e0.causal_ports, lambda p: p.slot == SlotKey(*key))
                    roots = port.read_roots if port is not None else frozenset()
                    firsts = {e.key: e.value.prepared.point for e in evidence.observation_trace.events
                              if e.tag == "FirstPrepare"}
                    parents_read = frozenset(firsts.get(SlotKey(p.unit, p.slot)) if isinstance(p, PlanRef) else p
                                             for p in roots)
                    if any(p is None or not _saved(state.core, p) for p in parents_read):
                        raise Disabled("actual writing actor causal input is unavailable")
                    if not any(n.point == prepared.point for n in evidence.ea.causal_nodes):
                        evidence = replace(evidence, ea=replace(evidence.ea,
                            causal_nodes=evidence.ea.causal_nodes + (CausalNode(prepared.point, parents_read),)))
            attempt = Fact(kind, key, (prepared, mode))
            ep = replace(evidence.ep, attempts=evidence.ep.attempts | {attempt})
            state = replace(state, core=core, controls=replace(state.controls, budget=budget),
                            evidence=replace(evidence, ep=ep))
            reply = {"normal": "acknowledged", "precommit_failure": "rejected", "lost_response": "lost"}[mode]
            state = self._emit(state, ObservationEvent("IOResponse", io_key, IOResponse(reply, written)))
            view = View(state.core, state.controls, state.evidence)
            response = (window.body_response(view, key, mode) if kind == "PutBody"
                        else window.entry_response(view, key, mode))
            state = replace(state, core=replace(state.core, p=response.custody))
            events = (attempt,)
            for request in response.effects:
                state, actual = self._effect(state, request, action, window)
                events += actual
            return state, events
        if kind in ("ReadBody", "ReadEntry"):
            # Re-read backing C/E independently. A bad window's declared read
            # value is part of its result, not a replacement for actual bytes.
            prepared = _slot(core.p, key).prepared
            if prepared is None:
                raise Disabled("read request without prepared key")
            actual_body = _find(core.c, lambda b: b.seal == prepared.seal)
            actual_entry = _find(core.e, lambda e: e.point == prepared.point)
            actual = Fact(kind, key, actual_body if kind == "ReadBody" else (actual_body, actual_entry))
            ep = replace(evidence.ep, readbacks=evidence.ep.readbacks | {actual})
            state = replace(state, evidence=replace(evidence, ep=ep))
            # ConfirmWrite physically reads BOTH ports, even though its old
            # effect name was ReadEntry. Every port request/readback is distinct.
            reads = (("ReadBody", actual_body),) if kind == "ReadBody" else (
                ("ReadBody", actual_body), ("ReadEntry", actual_entry))
            for operation, value_read in reads:
                io_key = IOKey(SlotKey(*key), operation, "read/first")
                state = self._emit(state, ObservationEvent("IORequest", io_key, IORequest(prepared)),
                                  ObservationEvent("ReadBack", io_key, ReadBack(value_read)))
            return state, (actual,)
        if kind in ("Reserve", "Release", "Stop"):
            if kind == "Reserve":
                # Explicit request fields, never infer token/amounts from P flags.
                reservation_request = value
                value = reservation_request.get("resources")
                fact = Fact(kind, key, value)
            ew = replace(evidence.ew, events=evidence.ew.events + (fact,))
            if kind == "Reserve":
                actual_description = Fact("WorkAccepted", key, reservation_request.get("descriptor"))
                ew = replace(ew, events=ew.events + (actual_description,))
            if kind == "Stop":
                core = replace(core, runners=tuple(replace(r, stopped=True) if r.work == key else r for r in core.runners))
            state = replace(state, core=core, evidence=replace(evidence, ew=ew))
            token = (WorkToken(str(key), reservation_request.get("token")) if kind == "Reserve"
                     else self._token(state, str(key)))
            payload = (Reserved(actual_description.value, value) if kind == "Reserve" else
                       Released(value) if kind == "Release" else Stopped(value))
            state = self._emit(state, ObservationEvent(kind, token, payload))
            return state, ((fact, actual_description) if kind == "Reserve" else (fact,))
        if kind == "Launch":
            ordinal = sum(w.work == key for w in core.wrappers)
            status = "launched"
            budget = state.controls.budget
            if action.outcome == "before_entry_failure":
                if budget.launch_failures <= 0:
                    raise Disabled("no launch failure budget")
                budget = replace(budget, launch_failures=budget.launch_failures - 1)
                status = "failed_before_entry"
            elif action.outcome in ("uncertain_before", "uncertain_after"):
                if budget.uncertain_launches <= 0:
                    raise Disabled("no uncertain launch budget")
                budget = replace(budget, uncertain_launches=budget.uncertain_launches - 1)
                status = "uncertain"
            elif action.outcome != "normal":
                raise Disabled("undeclared launch result")
            wrapper = Wrapper(f"{key}:wrapper:{ordinal}", str(key), str(value), status)
            core = replace(core, wrappers=core.wrappers + (wrapper,))
            actual = Fact("Launch", key, (wrapper, action.outcome))
            ew = replace(evidence.ew, events=evidence.ew.events + (actual,))
            state = replace(state, core=core, controls=replace(state.controls, budget=budget),
                            evidence=replace(evidence, ew=ew))
            token_key = WorkToken(str(key), str(value))
            state = self._emit(state, ObservationEvent("Launch", token_key, WrapperEvent(wrapper.id)))
            events = (actual,)
            if status == "failed_before_entry":
                confirmation = Fact("NeverEntered", key, wrapper.id)
                state = replace(state, evidence=replace(state.evidence,
                                ew=replace(state.evidence.ew, events=state.evidence.ew.events + (confirmation,))))
                events += (confirmation,)
            if action.outcome == "uncertain_after":
                desc = _work(state.core.p, str(key)).descriptor
                state, actuals = self._entered(state, wrapper.id, str(key), str(value), _resolved_numerical(state.core, desc))
                events += actuals
            if action.outcome != "normal":
                state = self._emit(state, ObservationEvent("LaunchResponse", token_key,
                    LaunchResponse(wrapper.id, "not_entered" if status == "failed_before_entry" else "unknown",
                                   obj(actual_response=action.outcome, wrapper=wrapper.id))))
            response = window.launch_response(View(state.core, state.controls, state.evidence), str(key), action.outcome)
            state = replace(state, core=replace(state.core, p=response.custody))
            for effect in response.effects:
                state, actuals = self._effect(state, effect, action, window)
                events += actuals
            return state, events
        if kind == "Enter":
            work, token, numerical = value
            return self._entered(state, str(key), work, token, numerical)
        if kind == "WorkerStep":
            runner = _find(core.runners, lambda r: r.work == key and not r.stopped)
            if runner is None:
                raise Disabled("no actual runner")
            state, finished = self._tick(state)
            core, evidence = state.core, state.evidence
            # Actual generation keeps what the worker read at entry, even if a
            # bad window later edits/removes the work descriptor/resolution.
            program = _find(self.e0.programs, lambda p: p.work == key)
            if program is None or runner.step >= len(program.replies):
                raise Disabled("actual program has no response at this port step")
            # Actual environment port, not a window-provided requested answer.
            outcome = _program_value(program.replies[runner.step], runner.reference_read, core)
            desc = runner.descriptor_read
            if desc is None:
                raise Disabled("runner has no original descriptor read")
            generation = Generation(str(key), desc.request, desc.stage,
                                    runner.started, finished, outcome, f"worker:{key}")
            event = (Event("DrawReturned", obj(work=key, outcome=outcome)) if desc.stage == "D"
                     else Event("WorkFinished", obj(work=key, started=runner.started, finished=finished, outcome=outcome)))
            message = Message(f"report:{key}:{runner.step}", event, str(key), generation)
            core = replace(core, runners=_replace_item(core.runners, runner, replace(runner, step=runner.step + 1)),
                           network=replace(core.network, messages=core.network.messages + (message,)))
            actual = Fact("Returned", key, generation)
            ew = replace(evidence.ew, events=evidence.ew.events + (actual,))
            ea = evidence.ea
            has_verification_call = any(call.work == key for call in ea.calls)
            if has_verification_call and isinstance(outcome.content, VerificationReply):
                ea = replace(ea, replies=ea.replies + ((str(key), outcome.content),))
            state = replace(state, core=core, evidence=replace(evidence, ew=ew, ea=ea))
            state = self._emit(state, ObservationEvent("WorkerReturn", WorkToken(str(key), runner.token), Returned(generation)))
            verification = VerificationKey(str(key), verification_call_id())
            for issuance in program.certificate_events:
                if issuance.step == runner.step:
                    issued = _program_value(issuance.certificate, runner.reference_read, core)
                    if not isinstance(issued, Certificate):
                        raise MissingContract("actual issuer port did not return a Certificate value")
                    state = replace(state, evidence=replace(state.evidence,
                        ea=replace(state.evidence.ea, issued=state.evidence.ea.issued + ((str(key), issued),))))
                    state = self._emit(state, ObservationEvent("CertificateIssued", verification, CertificateIssued(issued)))
            if has_verification_call and isinstance(outcome.content, VerificationReply):
                state = self._emit(state, ObservationEvent("VerifyReply", verification, VerificationReturned(outcome.content)))
            # Actual method/compiler/checker port values, separately scripted
            # from the independent E0 relations. No expected value is looked up.
            # These are observations of outputs/claims, not certification oracles.
            for port in program.port_events:
                if port.step != runner.step:
                    continue
                if port.tag not in ("Apply", "CertifiedCoverage", "ArtifactIssued", "ArtifactChecked"):
                    raise MissingContract("undeclared worker observation port")
                actual_value = _env_value(core, port.value)
                actual_key = _env_value(core, port.key)
                payload = ArtifactIssued(actual_value, generation) if port.tag == "ArtifactIssued" else actual_value
                state = self._emit(state, ObservationEvent(port.tag, actual_key, payload))
            return state, (actual,)
        if kind == "Acquire":
            declared = value
            reader = _resolve(core, declared.reader)
            targets = frozenset(_resolve(core, p) for p in declared.targets)
            contents = tuple(sorted(((p, _find(core.c, lambda b: b.seal == _find(core.e, lambda e: e.point == p).header.seal).payload)
                                     for p in targets), key=encode))
            mapping = {n.point: n.parents for n in evidence.ea.causal_nodes}
            ancestors, todo = set(), list(targets | {reader, _resolve(core, declared.completion)})
            while todo:
                point = todo.pop()
                for parent in mapping.get(point, ()):
                    if parent not in ancestors:
                        ancestors.add(parent)
                        todo.append(parent)
            acquisition = ActualAcquisition(str(key), reader, targets, contents,
                                            frozenset(e.point for e in core.e), core.h.reading,
                                            frozenset(ancestors))
            ea = replace(evidence.ea, acquisitions=evidence.ea.acquisitions + (acquisition,))
            actual = Fact("Acquired", key, acquisition)
            state = replace(state, evidence=replace(evidence, ea=ea))
            state = self._emit(state, ObservationEvent("Acquire", IntentKey(acquisition.reader, acquisition.intent),
                                                       Acquired(acquisition)))
            return state, (actual,)
        if kind == "HandoffPurpose":
            prior = _find(self._before_conditions, lambda c: c.key == key)
            current = _find(state.core.p.conditions, lambda c: c.key == key)
            if prior is None or current is None:
                raise MissingContract("handoff has no actual condition snapshot")
            before = frozenset(k for c in self._before_conditions if c.owner == prior.owner
                               and (c.key.obligation, c.key.obligation_key) == (key.obligation, key.obligation_key)
                               for k in c.unmet)
            after = frozenset(k for c in state.core.p.conditions if c.owner == current.owner
                              and (c.key.obligation, c.key.obligation_key) == (key.obligation, key.obligation_key)
                              and c.key in before for k in c.unmet)
            state = self._emit(state, ObservationEvent("HandoffPurpose", key,
                              HandoffPurpose(prior.owner, current.owner, before, after)))
            return state, (fact,)
        if kind == "AdoptionPlan":
            ea = replace(evidence.ea, adoption_plans=evidence.ea.adoption_plans | {fact})
            state = replace(state, evidence=replace(evidence, ea=ea))
            state = self._emit(state, ObservationEvent("ReserveAdoption", IntentKey(value.get("reader"), str(key)),
                                                       AdoptionReserved(value.get("completion"))))
            return state, (fact,)
        if kind == "AdoptionCommit":
            # EA captures the ACTUAL saved A/ST record, not AdoptionPlan's
            # requested success/reader/result. Retain that request separately.
            unit = _find(core.p.units, lambda u: u.id == value.get("unit"))
            actual_records = tuple((s.prepared.point, _find(core.e, lambda e: e.point == s.prepared.point).header.record)
                                   for s in unit.slots if s.prepared and _saved(core, s.prepared.point)) if unit else ()
            adoption = _find(actual_records, lambda pair: pair[1].contract == Contract("knowledge_adopted", "1"))
            reader = completion = result = None
            if adoption is not None:
                reader = adoption[1].content.get("origin")
                completion = adoption[1].content.get("completion")
                completed = _find(core.e, lambda e: e.point == completion)
                if completed is not None:
                    result = completed.header.record.content.get("result")
            actual = Fact("AdoptionCommit", key,
                          obj(requested=value, records=actual_records, reader=reader,
                              completion=completion, result=result,
                              outcome="Adopted" if adoption is not None else "Stale_or_unrecognized"))
            ea = replace(evidence.ea, adoptions=evidence.ea.adoptions + (actual,))
            state = replace(state, evidence=replace(evidence, ea=ea))
            declared = _find(self.e0.adoptions, lambda a: a.id == key)
            reservation = _find(state.evidence.observation_trace.events,
                                lambda e: e.tag == "ReserveAdoption" and e.key.intent == key)
            if adoption is not None and declared is not None and reservation is not None:
                nodes = state.evidence.ea.causal_nodes
                mapping = {n.point: n.parents for n in nodes}
                ancestors, todo = set(), list(mapping.get(adoption[0], ()))
                while todo:
                    parent = todo.pop()
                    if parent not in ancestors:
                        ancestors.add(parent)
                        todo.extend(mapping.get(parent, ()))
                history = state.evidence.observation_trace.events
                previous = _find(tuple(reversed(history)), lambda e: e.tag == "Adopt" and e.key.reader == reader)
                acquisition_keys = tuple(e.key for e in history if e.tag == "Acquire"
                                         and e.key.intent in declared.acquisitions and e.key.reader == reader)
                payload = Adopted(adoption[0], completion, result,
                                  previous.value.record if previous else None,
                                  previous.value.result if previous else None,
                                  VerificationKey(declared.verification_work, verification_call_id()), acquisition_keys,
                                  frozenset(ancestors), nodes, frozenset(e.point for e in core.e))
                state = self._emit(state, ObservationEvent("Adopt", IntentKey(reader, str(key)), payload))
            if reservation is not None:
                state = self._emit(state, ObservationEvent("ReleaseAdoption", reservation.key, reservation.value))
            return state, (actual,)
        if kind == "Rebuild":
            return replace(state, controls=replace(state.controls, normal_window=True)), (fact,)
        raise MissingContract("environment effect kind is undeclared")

    def step(self, state: State, action: Action, window: CorrectWindow) -> Step:
        self._edge_events = []
        self._before_conditions = state.core.p.conditions
        events: tuple[Fact, ...] = ()
        result = None
        core, controls, evidence = state.core, state.controls, state.evidence
        operation = action.operation
        if operation == "RequestInterval":
            request = _find(self.e0.intervals, lambda k: k.id == action.target[0])
            if request is None or any(k.id == request.id for k in core.h.interval_requests):
                raise Disabled("interval already undertaken or undeclared")
            h = replace(core.h, interval_requests=core.h.interval_requests + (request,))
            ei = replace(evidence.ei, requests=evidence.ei.requests + (request,))
            state = replace(state, core=replace(core, h=h), evidence=replace(evidence, ei=ei))
            events = (Fact("IntervalRequested", request.id, request),)
            # O-04 / C-O04.save[k]/handle[cells] (paper 629,1186,1205-1207).
            # 紙に無い仮定 A-INTERVAL-STEP: RequestInterval names this model's
            # actual H custody-taking step; the paper specifies the occurrence,
            # not this operation name. E0 alone never produces the observation.
            retained = state.core.h.interval_requests[-1]
            state = self._emit(state, ObservationEvent("IntervalUndertaken",
                IntervalKey(retained.id, retained.route_epoch, retained.interval.run),
                IntervalUndertaken(retained, Owner("H", retained.id), state.core.h.reading)))
        elif operation == "IntervalEvent":
            occurrence = _find(self.e0.interval_occurrences, lambda o: o.id == action.target[0])
            if occurrence is None or occurrence.id in evidence.ei.occurred:
                raise Disabled("interval event unavailable")
            # EI / REF-5 (739,745-750): resolve the performed evidence read;
            # the pre-run script/binding keeps its PlanRef. No expectation call.
            actual = replace(occurrence.event, evidence_point=(
                _resolve(core, occurrence.event.evidence_point)
                if occurrence.event.evidence_point is not None else None))
            ei = replace(evidence.ei, events=evidence.ei.events + (actual,), occurred=evidence.ei.occurred | {occurrence.id})
            state = replace(state, evidence=replace(evidence, ei=ei))
            events = (Fact("IntervalEvent", occurrence.id, actual),)
            request = _find(self.e0.intervals, lambda k: k.id == actual.interval_request)
            if actual.kind in ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "ReportGenerated", "MeasurementEnded"):
                # EI is the actually selected environment occurrence, not an X
                # membership or Support assertion. Evidence Point is a real read.
                point = actual.evidence_point
                payload = IntervalObserved(actual.reading, request.interval, actual.cells,
                                           request.work, point, actual.content)
                state = self._emit(state, ObservationEvent(actual.kind,
                    IntervalKey(request.id, request.route_epoch, request.interval.run), payload))
        elif operation == "HostUnknown":
            notice = _find(self.e0.unknown_notices, lambda n: n.id == action.target[0])
            if notice is None or any(m.id == "host-unknown:" + notice.id for m in core.network.messages):
                raise Disabled("unknown notice unavailable")
            descriptor = _find(tuple(w for p in self.e0.plans for w in p.works), lambda w: w.work_id == notice.work)
            if descriptor is None:
                raise Disabled("unknown notice has no declared undertaking")
            runner = _find(core.runners, lambda r: r.work == notice.work)
            # A-T-UNKNOWN / EndKnown (769,790,1187): model reason spellings,
            # not a worker return or an assertion that an unknown start occurred.
            started = runner.started if runner else Unavailable("host-start-unconfirmed")
            finished = Unavailable("host-end-unconfirmed")
            outcome = Outcome(OutcomeKind.UNKNOWN, notice.basis)
            generation = Generation(notice.work, _resolve(core, descriptor.request), descriptor.stage,
                                    started, finished, outcome, "host:" + notice.id)
            event = (Event("DrawReturned", obj(work=notice.work, outcome=outcome)) if descriptor.stage == "D" else
                     Event("WorkFinished", obj(work=notice.work, started=started, finished=finished, outcome=outcome)))
            message = Message("host-unknown:" + notice.id, event, notice.work, generation)
            core = replace(core, network=replace(core.network, messages=core.network.messages + (message,)))
            actual = Fact("UnknownObserved", notice.work, generation)
            ew = replace(evidence.ew, events=evidence.ew.events + (actual,))
            state = replace(state, core=core, evidence=replace(evidence, ew=ew))
            events = (actual,)
        elif operation == "Post":
            posting = _find(self.e0.postings, lambda p: p.id == action.target[0])
            if posting is None or posting.id in core.network.posted:
                raise Disabled("posting unavailable")
            state, actual = self._post(state, posting.event,
                                       posting.id if posting.source is None else posting.source, posting.rank)
            state = replace(state, core=replace(state.core, network=replace(state.core.network,
                            posted=state.core.network.posted | {posting.id})))
            events = (actual,)
        elif operation == "Deliver":
            message = _find(core.network.messages, lambda m: m.id == action.target[0])
            if message is None or message.deliveries >= self.e0.delivery_limit:
                raise Disabled("delivery unavailable")
            if message.deliveries == 0 and any(message.id == self._notice_message_id(n)
                    for b in self.e0.delivery_bundles for n in b.notices):
                raise Disabled("first delivery belongs to a declared bundle")
            state, actual = self._deliver(state, message)
            events = (actual,)
        elif operation == "DeliverBundle":
            bundle = _find(self.e0.delivery_bundles, lambda b: b.id == action.target[0])
            if bundle is None or not controls.normal_host:
                raise Disabled("delivery bundle unavailable")
            messages = self._bundle_messages(state, bundle)  # ALL ready before the first Post.
            # A-DELIVERY-BUNDLE / paper 794,796,944: consecutive actual Posts
            # at the entry clock, separate seq values, no generation/saving here.
            for message in messages:
                state, actual = self._deliver(state, message)
                events += (actual,)
        elif operation in ("HostAck", "RejectHost"):
            if not core.h.queue or core.h.queue[0].key != action.target or not controls.normal_host:
                raise Disabled("host order/normality")
            envelope = core.h.queue[0]
            if operation == "HostAck" and not any(r.envelope == envelope for r in core.p.receipts):
                raise Disabled("host has no accepted custody handoff")
            if operation == "RejectHost" and _well_formed(envelope.event):
                raise Disabled("cannot reject well-formed head")
            h = replace(core.h, queue=core.h.queue[1:])
            eh = replace(evidence.eh, acknowledgements=evidence.eh.acknowledgements + (envelope.key,))
            state = replace(state, core=replace(core, h=h), evidence=replace(evidence, eh=eh))
            events = (Fact(operation, action.target, envelope),)
            if operation == "HostAck":
                state = self._emit(state, ObservationEvent("HostAck", ReceiptKey(*envelope.key), Posted(envelope)))
        elif operation == "FaultWindow":
            if not controls.normal_window or controls.budget.window_faults <= 0:
                raise Disabled("fault budget")
            controls = replace(controls, normal_window=False,
                               budget=replace(controls.budget, window_faults=controls.budget.window_faults - 1))
            state = replace(state, controls=controls)
            events = (Fact("FaultWindow", "window", controls.budget),)
        elif operation in ("RecoverHost", "RecoverWrapper", "RecoverStore"):
            if operation == "RecoverHost":
                controls = replace(controls, normal_host=True)
            elif operation == "RecoverWrapper":
                controls = replace(controls, normal_wrapper=True)
            else:
                controls = replace(controls, body_put=True, body_read=True, entry_add=True, entry_read=True)
            state = replace(state, controls=controls)
            events = (Fact(operation, "capability", controls),)
        elif operation == "DuplicateWrapper":
            original = _find(core.wrappers, lambda w: w.id == action.target[0])
            if original is None or original.status != "launched" or controls.budget.duplicate_wrappers <= 0:
                raise Disabled("duplicate wrapper unavailable")
            duplicate = replace(original, id=original.id + ":duplicate")
            controls = replace(controls, budget=replace(controls.budget, duplicate_wrappers=controls.budget.duplicate_wrappers - 1))
            state = replace(state, core=replace(core, wrappers=core.wrappers + (duplicate,)), controls=controls)
            actual = Fact("DuplicateWrapper", original.work, duplicate)
            state = replace(state, evidence=replace(evidence, ew=replace(evidence.ew, events=evidence.ew.events + (actual,))))
            events = (actual,)
            state = self._emit(state, ObservationEvent("Launch", WorkToken(duplicate.work, duplicate.token),
                                                       WrapperEvent(duplicate.id)))
        else:
            if operation == "Accept":
                envelope = action.target[0]
                state = self._emit(state, ObservationEvent("Present", ReceiptKey(*envelope.key), Posted(envelope)))
                evidence = state.evidence
            decision = window.dispatch(View(core, controls, evidence), action)
            # A window cannot replace E0 or any actual evidence/store/host field.
            if not isinstance(decision, Decision) or not isinstance(decision.custody, Custody):
                raise TypeError("window must return a frozen Decision/Custody")
            require_frozen(decision)
            state = replace(state, core=replace(core, p=decision.custody))
            result = decision.result
            if operation == "Accept":
                envelope = action.target[0]
                presentation = Fact("Presented", envelope.key, result if isinstance(result, str) else "accepted")
                eh = replace(state.evidence.eh, presentations=state.evidence.eh.presentations | {presentation})
                state = replace(state, evidence=replace(state.evidence, eh=eh))
                # Preserve the complete proposed envelope in the edge, including
                # a mismatched same-number re-presentation; don't overwrite EH.
                events += (Fact("Presentation", envelope.key, (envelope, result)),)
            for effect in decision.effects:
                state, actual = self._effect(state, effect, action, window)
                events += actual
            if operation == "CompleteWrite":
                state = self._close_save(state, action.target)
        state = replace(state, evidence=replace(state.evidence, el=EL(state.core.c, state.core.e)))
        state = self._emit(state)  # EL and clock are actual reads in EVERY state.
        state = self._refresh_conditions(state)
        return Step(state, tuple(self._edge_events), result)


@dataclass(frozen=True, slots=True)
class Cut:
    id: str
    excluded_operations: frozenset[str] = frozenset()
    # A boundary is untested, never a normally settled end (579 / K-U/Q/T).
    untested: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    e0: E0
    max_states: int
    initial: State | None = None
    cut: Cut = Cut("uncut")
    initial_connection: str = "I0; no persisted facts or execution history"


@dataclass(frozen=True, slots=True)
class Edge:
    source: int
    target: int
    action: Action
    actual_events: tuple[ObservationEvent, ...]
    result: object


@dataclass(frozen=True, slots=True)
class Exploration:
    scenario: str
    states: tuple[State, ...]
    edges: tuple[Edge, ...]
    enabled: tuple[tuple[Action, ...], ...]
    complete: bool
    frontier: tuple[int, ...]
    omitted: tuple[tuple[int, Action], ...]
    elapsed_seconds: float
    parents: tuple[tuple[int, Action] | None, ...]
    untested: tuple[str, ...]

    @property
    def status(self) -> str:
        # NOT a safety/liveness verdict. No checker rows exist this turn.
        return "exploration_complete" if self.complete else "state_limit_reached"

    def trace(self, target: int) -> tuple[Action, ...]:
        path = []
        while target:
            parent = self.parents[target]
            if parent is None:
                raise ValueError("unconnected state")
            target, action = parent
            path.append(action)
        return tuple(reversed(path))


def _population_delta(before: State, after: State) -> tuple[PopulationDelta, ...]:
    # Structural diff only, NOT window-provided population/status. Removed and
    # modified rows survive in the observation even when a mutant deletes them.
    def mappings(state: State) -> tuple[tuple[str, dict], ...]:
        p = state.core.p
        return (
            ("H.originals", {e.key: e for e in state.core.h.originals}),
            ("P.receipts", {r.envelope.key: r for r in p.receipts}),
            ("P.units", {u.id: u for u in p.units}),
            ("P.work", {w.descriptor.work_id: w for w in p.work}),
            ("C", {b.seal: b for b in state.core.c}),
            ("E", {e.point: e for e in state.core.e}),
        )
    result = []
    for (location, a), (_, b) in zip(mappings(before), mappings(after)):
        ak, bk = frozenset(a), frozenset(b)
        result.append(PopulationDelta(location, ak, bk, bk - ak, ak - bk,
                                      frozenset(k for k in ak & bk if a[k] != b[k])))
    return tuple(result)


def _declared_targets(e0: E0) -> tuple[object, ...]:
    return (tuple(("posting", p.id) for p in e0.postings)
            + tuple(("plan", p.unit, p.obligation_id, p.key) for p in e0.plans)
            + tuple(("work", w.work_id) for p in e0.plans for w in p.works)
            + tuple(("interval", k.id) for k in e0.intervals)
            + tuple(("acquisition", a.id) for a in e0.acquisitions)
            + tuple(("adoption", a.id) for a in e0.adoptions))


def explore(scenario: Scenario, window: CorrectWindow | None = None,
            observer: Observer | None = None) -> Exploration:
    """Deterministic BFS with full labelled edges, including loops and failures.

    No depth cutoff, partial-order reduction or environment-variable switch.
    max_states applies BEFORE inserting state max_states+1. A complete graph
    within a declared Cut is only complete for that Cut; untested scope survives.
    Fairness/SCC/relationship ROWS are intentionally deferred, not auto-passed.
    """
    if not 1 <= scenario.max_states <= 200_000:
        raise ValueError("each scenario requires 1 <= max_states <= 200000")
    started = perf_counter()
    environment = Environment(scenario.e0)
    window = window or CorrectWindow(scenario.e0)
    initial = scenario.initial or environment.initial()
    require_frozen(initial)
    states = [initial]
    indices = {initial: 0}
    parents: list[tuple[int, Action] | None] = [None]
    edges = []
    enabled_sets: list[tuple[Action, ...]] = []
    omitted = []
    declared = _declared_targets(scenario.e0)
    complete = True
    queue = deque((0,))
    stop_source: int | None = None

    def observe(index: int) -> None:
        state = states[index]
        view = View(state.core, state.controls, state.evidence)
        all_actions = _sorted(tuple(set(window.enabled(view) + environment.actions(state))))
        enabled_sets.append(all_actions)
        if observer is not None:
            observer.on_state(StateObservation(index, state, scenario.e0, all_actions, declared,
                                               environment.observation_contract, state.evidence.observation_trace))

    # Every inserted state is observed once, including an unexpanded frontier
    # at the state limit. Actual empty Enabled is never a placeholder for unknown.
    observe(0)
    while queue:
        source = queue.popleft()
        state = states[source]
        # Complete offered set BEFORE applying Cut; checker receives both.
        all_actions = enabled_sets[source]
        for action in all_actions:
            if action.operation in scenario.cut.excluded_operations or environment.presentation_cut(state, action):
                omitted.append((source, action))
                continue
            step = environment.step(state, action, window)
            target = indices.get(step.state)
            if target is None:
                if len(states) >= scenario.max_states:
                    complete = False
                    stop_source = source
                    break
                target = len(states)
                indices[step.state] = target
                states.append(step.state)
                parents.append((source, action))
                queue.append(target)
                observe(target)
            edge = Edge(source, target, action, step.events, step.result)
            edges.append(edge)
            if observer is not None:
                observer.on_step(StepObservation(source, target, state, step.state,
                                                 scenario.e0, action, step.events, step.result,
                                                 _population_delta(state, step.state), declared,
                                                 environment.observation_contract,
                                                 state.evidence.observation_trace,
                                                 step.state.evidence.observation_trace))
        if not complete:
            break
    frontier = (() if complete else tuple((stop_source, *queue)))
    result = Exploration(scenario.id, tuple(states), tuple(edges), tuple(enabled_sets),
                         complete, frontier, tuple(omitted), perf_counter() - started,
                          tuple(parents), scenario.cut.untested)
    if observer is not None:
        observer.on_graph(GraphObservation(result.states, result.edges, result.enabled,
                                           scenario.e0, complete, frontier, tuple(omitted)))
    return result
