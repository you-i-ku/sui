"""Independent checker; completion custody follows v0.18 (9-3補, M3/M4).

This module never imports fb_machine (including its helpers or window classes).
The explorer supplies frozen values, independent E0 and observations of every
state/edge. Rows derive their populations from those values, never
from the window's success/settled flags. Spec: 405, 553-564, 806-907.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from types import UnionType
from typing import Annotated, Hashable, Iterable, Literal, Mapping, Protocol, Sequence, Union, get_args, get_origin, get_type_hints


class PropertyKind(str, Enum):
    STATE = "state_safety"
    STEP = "before_after"
    ENABLED = "operation_enabled"
    PATH = "path_progress"
    RELATION = "state_relation"


# Spec 839-883: separate denominator, not generated from registered predicates.
CONDITION_IDS = (
    "INV-1.a", "INV-1.b", "INV-1.c",
    "INV-2.a", "INV-2.b", "INV-2.c", "INV-2.d", "INV-2.e", "INV-2.f",
    "INV-3.a", "INV-3.b", "INV-3.c",
    "INV-4.a", "INV-4.b", "INV-4.c",
    "INV-5.a", "INV-5.b", "INV-5.c",
    "INV-6.a", "INV-6.b", "INV-6.c",
    "INV-7.a", "INV-7.b", "INV-7.c", "INV-8.a", "INV-8.b",
    "INV-9.a", "INV-9.b", "INV-10.a", "INV-10.b",
    "INV-11.a", "INV-11.b", "INV-11.c", "INV-12.a", "INV-12.b",
    "INV-13.a", "INV-13.b", "INV-14.a", "INV-14.b",
    "INV-15.a", "INV-15.b", "INV-16.a", "INV-16.b",
    "L-RECEIPT", "L-DERIVE", "INV-2.g", "INV-16.c",
)
# Populated after the executable registry below. Partial is NOT implemented in
# the coverage report: an unavailable observation must never silently pass.
UNIMPLEMENTED = ()
HUMAN_IDS = tuple(f"H-{i:02d}" for i in range(1, 7))

# Independent scope denominator from the paper's rows (839-883), not from
# window work enumeration. A later row cannot cover just D for an all-work row.
RECEIPT_TYPES = ("Boot", "Received", "SegmentReport", "WorkFinished", "DrawReturned")
WORK_TYPES = ("Wr", "Wp", "Wv", "Wg", "Ep", "D", "Ee", "MeasureSegment")
END_WORK_TYPES = ("Wr", "Wp", "Wv", "Wg", "Ep", "D", "Ee")
REPORT_TYPES = ("Frame", "Started", "Ended", "RouteApplied", "Gap", "Unavailable", "Claim", "Unproved", "NoReport")
OBLIGATION_TYPES = ("O-01", "O-02", "O-03", "O-04", "O-05", "O-06", "O-07", "O-08", "O-09.a", "O-09.b", "O-10", "O-11", "O-12", "O-13", "O-14", "O-G")
PUBLICATION_TYPES = ("initial", "k", "Q", "R", "P/Cq", "G", "PR:FProblem", "PR:NoDecision", "DF", "DU", "EV", "S", "T", "V", "A/ST", "Xc/W/B", "Qgen", "CG", "EQ")
RECORD_SCOPE = ("all_declared_record_contracts",)  # quantified, not a handpicked subset
SCOPE_UNIVERSE = (
    *((c, RECEIPT_TYPES) for c in ("INV-1.a", "INV-1.b", "INV-1.c")),
    ("INV-2.a", OBLIGATION_TYPES), ("INV-2.b", PUBLICATION_TYPES),
    ("INV-2.c", END_WORK_TYPES), ("INV-2.d", ("O-03",)),
    ("INV-2.e", WORK_TYPES), ("INV-2.f", OBLIGATION_TYPES),
    *((c, WORK_TYPES) for c in ("INV-3.a", "INV-3.b", "INV-3.c")),
    *((c, RECORD_SCOPE) for c in ("INV-4.a", "INV-4.b", "INV-4.c", "INV-5.a", "INV-5.c")),
    ("INV-5.b", WORK_TYPES), ("INV-6.a", ("update_Q",)),
    ("INV-6.b", ("terminal", "draw", "measurement_application", "generation")),
    ("INV-6.c", ("measurement", "unnamed_slot", "acquisition_intent", "adoption_intent", "reader")),
    ("INV-7.a", ("all_valid_report_families", "all_declared_exclusion_units")),
    ("INV-7.b", ("Publish", "ClaimStart", "EnterWorker", "Acquire", "verification_use", "Adopt")),
    ("INV-7.c", ("all_preexisting_commitments_and_frozen_views",)),
    ("INV-8.a", ("Wr", "Wp", "Wv", "Wg", "Ep", "Ee")), ("INV-8.b", WORK_TYPES),
    ("INV-9.a", ("V", "Adopted", "actual_acquisition", "actual_verification_reply")),
    ("INV-9.b", ("all_readers", "all_adoption_intents")),
    ("INV-10.a", ("all_resources", "all_reservations")), ("INV-10.b", ("all_release_steps",)),
    *((c, RECEIPT_TYPES) for c in ("INV-11.a", "INV-11.b", "INV-11.c")),
    ("INV-12.a", REPORT_TYPES), ("INV-12.b", ("all_requested_cells",)),
    ("INV-13.a", ("all_bootstrap_computations",)), ("INV-13.b", ("initial_present_absent_pairs",)),
    ("INV-14.a", ("all_draw_requests_across_WorkIds",)), ("INV-14.b", ("all_draw_restart_attempts",)),
    ("INV-15.a", END_WORK_TYPES), ("INV-15.b", END_WORK_TYPES),
    ("INV-16.a", ("all_selections",)), ("INV-16.b", ("EQ", "PR", "artifact", "problem", "Draw", "EV", "S")),
    ("L-RECEIPT", RECEIPT_TYPES), ("L-DERIVE", ("O-03.N", "O-03.P")),
    ("INV-2.g", ("Qgen", "Wg", "CG", "EQ", "pG")),
    ("INV-16.c", ("Qgen", "Wg", "CG", "EQ", "R10")),
)


@dataclass(frozen=True, slots=True)
class RowContract:
    """All six columns plus the formula and root/dependency declarations.

Spec 557-562 / 902-906. These are declarations, NOT executable predicates.
No blanket default scope, evidence, excuse or terminal-only timing is supplied.
"""

    condition_id: str
    scope: tuple[str, ...]
    population: str
    correspondence_keys: tuple[str, ...]
    kinds: frozenset[PropertyKind]
    timing: str
    root: str
    lifetime: str
    readable_fields: tuple[str, ...]
    comparisons: tuple[str, ...]
    evidence: tuple[str, ...]
    depends_on: tuple[str, ...]
    unfinished_targets: tuple[str, ...]
    permitted_completion_conditions: tuple[str, ...]
    formula: str
    implementation: str = "not_implemented"
    identification: str = "未具体化"
    paper_line: int = 0
    paper_columns: tuple[str, ...] = ()

    def __post_init__(self):
        if self.condition_id not in CONDITION_IDS:
            raise ValueError("unknown paper condition ID")
        required = (self.scope, self.population, self.correspondence_keys, self.kinds,
                    self.timing, self.root, self.lifetime, self.readable_fields,
                    self.comparisons, self.evidence, self.formula)
        if not all(required):
            raise ValueError("row must declare columns, root, lifetime and readable fields")
        allowed = dict(SCOPE_UNIVERSE)[self.condition_id]
        if any(scope not in allowed for scope in self.scope):
            raise ValueError("row scope absent from independent paper denominator")


ROWS: tuple[RowContract, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageCell:
    condition_id: str
    scope: str
    state: str


def coverage(rows: tuple[RowContract, ...] | None = None) -> tuple[CoverageCell, ...]:
    """Declaration coverage only; never turns absence/registration into a pass."""
    rows = ROWS if rows is None else rows
    return tuple(CoverageCell(condition, scope,
                             next((r.implementation for r in rows
                                   if r.condition_id == condition and scope in r.scope),
                                  "not_implemented"))
                 for condition, scopes in SCOPE_UNIVERSE for scope in scopes)


@dataclass(frozen=True, slots=True)
class PopulationDelta:
    location: str
    before_keys: frozenset[object]
    after_keys: frozenset[object]
    added: frozenset[object]
    removed: frozenset[object]
    changed: frozenset[object]


@dataclass(frozen=True, slots=True)
class StateObservation:
    index: int
    state: object
    e0: object
    # Full enabled set, BEFORE restricting to an SCC, Cut or missing-receipt set.
    enabled: tuple[object, ...]
    # A declaration universe, not an assertion that all these targets exist.
    # Dynamic required targets must later be derived from E0/EH/EW/EL.
    declared_targets: tuple[object, ...]
    # Checker-owned transport v1. None means NOT CONNECTED, never an empty log.
    observation_contract: object | None = None
    observation_trace: object | None = None


@dataclass(frozen=True, slots=True)
class StepObservation:
    source: int
    target: int
    before: object
    after: object
    e0: object
    action: object
    actual_events: tuple[object, ...]
    result: object
    populations: tuple[PopulationDelta, ...]
    declared_targets: tuple[object, ...]
    observation_contract: object | None = None
    before_trace: object | None = None
    after_trace: object | None = None


@dataclass(frozen=True, slots=True)
class RelationObservation:
    left: StateObservation
    right: StateObservation
    declaration: object


@dataclass(frozen=True, slots=True)
class GraphObservation:
    states: tuple[object, ...]
    edges: tuple[object, ...]
    enabled: tuple[tuple[object, ...], ...]
    e0: object
    complete: bool
    frontier: tuple[int, ...]
    excluded_by_cut: tuple[tuple[int, object], ...]


class Observer(Protocol):
    """A passive consumer. No window instance or executable callback is passed."""

    def on_state(self, observation: StateObservation) -> None: ...

    def on_step(self, observation: StepObservation) -> None: ...

    def on_graph(self, observation: GraphObservation) -> None: ...


# Relationship rows can be supplied pairs after exploration; a single-state
# observation is not evidence for INV-11.c / INV-13.b (spec 887).
# The checker below consumes these values, never a window or its callbacks.

@dataclass(frozen=True, slots=True)
class Finding:
    condition_id: str
    message: str
    location: tuple[object, ...]
    target: object = None


@dataclass(frozen=True, slots=True)
class Gap:
    id: str
    fields: str
    reason: str


# These are missing contracts, not exemptions from the paper. In particular an
# opaque Fact cannot be decoded by watching what CorrectWindow happens to emit.
GAPS = {
    "seal": Gap("seal", "fb_machine.py:723-749,914-941",
                "E0 has no seal(payload,salt) definition; payload/header checks do not prove Saved"),
    "receipt_wire": Gap("receipt_wire", "fb_machine.py:247-263,543-551,896-903",
                        "no complete Envelope -> RecordPlan.content/slot/name conversion, including Boot's two slots"),
    "facts": Gap("facts", "fb_machine.py:753-789,861-863",
                 "Fact.kind/key/value have no tagged payload schema for EH/EW/EP/EU or adoption events"),
    "derivation": Gap("derivation", "fb_machine.py:610-623,730-748",
                      "eligible_receipts/trigger strings lack a typed EH/EL binding and numerical_projection has no evaluator"),
    "completion": Gap("completion", "fb_machine.py:420-472,977-991",
                      "completion conditions are prose; no typed CloseSave/HandoffPurpose and remaining-condition observations"),
    "references": Gap("references", "fb_machine.py:271-359,507-513,562-582",
                      "contract-specific closure, permission validity and parent minima are explicitly incomplete"),
    "apply": Gap("apply", "fb_machine.py:723-749",
                 "E0 lacks RIGHT-APPLY finite transition/input-digest/measurement projection table"),
    "adoption": Gap("adoption", "fb_machine.py:793-800,820-863",
                    "no typed actual adoption event with its ancestor closure; acquisition.ancestors is not adoption.ancestors"),
    "support": Gap("support", "fb_machine.py:680-700,866-882",
                   "no contract relation from X-resident EI evidence to Support, or typed certified coverage observation"),
    "artifact": Gap("artifact", "fb_machine.py:507-513,635-640,820-853",
                    "no independently issued/verified math artifact observation and full EQ/PR/DF/EV/S binding"),
}


@dataclass(frozen=True, slots=True)
class RowResult:
    condition_id: str
    identification: str
    classification: str
    observations: int
    reached: int
    violations: tuple[Finding, ...]
    limitations: tuple[str, ...]
    observation_connection: str = "約束の未接続"


@dataclass(frozen=True, slots=True)
class CheckReport:
    rows: tuple[RowResult, ...]
    human: tuple[tuple[str, str], ...]
    complete: bool
    contract_violations: tuple[BoundaryViolation, ...] = ()
    # Schema connection is not completeness of every required observation.
    # Keep missing (row, tag) ports explicit even with valid trace/E0 shapes.
    unconnected_observations: tuple[tuple[str, str], ...] = ()

    @property
    def connection_counts(self):
        """Trace/E0 boundary status; see unconnected_observations for missing ports."""
        return {name: sum(r.observation_connection == name for r in self.rows)
                for name in ("約束の未接続", "約束違反", "約束接続・部分判定")}

    @property
    def violations(self):
        return tuple(f for row in self.rows for f in row.violations)

    @property
    def counts(self):
        # The denominator is ALWAYS 45, including unreached/partial/Cut rows.
        return {name: sum(r.classification == name for r in self.rows) for name in (
            "違反", "違反なし・識別力確認済み", "違反なし・識別力未確認")}

    @property
    def passed(self):
        return (self.complete and not self.contract_violations and not self.unconnected_observations
                and all(r.classification == "違反なし・識別力確認済み"
                                     and not r.limitations for r in self.rows)
                and all(status == "点検済み" for _, status in self.human))


class Probe:
    def __init__(self, checker, row, location):
        self.checker, self.row, self.location = checker, row, location

    def require(self, condition, message, target=None):
        self.checker.reached[self.row] += 1
        if not condition:
            finding = Finding(self.row, message, self.location, target)
            # Retain a first witness for each clause/target, rather than 100000
            # copies. The row still runs on EVERY state and edge.
            key = (message, repr(target))
            self.checker.failures[self.row].setdefault(key, finding)
        return condition

    def gap(self, key):
        g = GAPS.get(key)
        if g:
            # The turn-1 inventory remains the source-field locator. The target
            # contracts now exist here; missing transport and paper-unsupported
            # meanings are distinct, neither means a successful row.
            status = ("既存判定の残りは未接続" if "約束接続・部分判定" in self.checker._connections[self.row]
                      else "約束の未接続")
            parts = "; ".join(f"{part.category}: {part.meaning} [paper {part.paper.lines[0]}-{part.paper.lines[1]}]"
                              for part in GAP_PARTS if part.gap == key)
            self.checker.limits[self.row].add(f"{status}: {g.id} ({g.fields}); {parts}")
        else:
            self.checker.limits[self.row].add(key)


def _type(value, name):
    # Only public frozen value types, never window class/mutant names.
    return type(value).__name__ == name


def _get(value, name, default=None):
    if _type(value, "Object"):
        return dict(value.items).get(name, default)
    return getattr(value, name, default)


def _wire(value):
    """Independent implementation of public MODEL encoding (type section 105-124).

    This is not F-a wire compatibility and does not define the missing seal.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if is_dataclass(value):
        return {"type": type(value).__name__,
                "fields": {f.name: _wire(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, frozenset):
        return sorted((_wire(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, tuple):
        return [_wire(v) for v in value]
    return value


def _encode(value):
    return json.dumps(_wire(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _hash(value):
    return sha256(_encode(value)).hexdigest()


def _points(value):
    """Walk typed values, never interpret strings as Points or guess field roles."""
    if _type(value, "Point") or _type(value, "PlanRef"):
        yield value
    elif is_dataclass(value):
        for f in fields(value):
            yield from _points(getattr(value, f.name))
    elif isinstance(value, (tuple, frozenset)):
        for v in value:
            yield from _points(v)


def _path(value, path):
    if not path:
        return (value,)
    head, *tail = path
    if head == "*":
        if not isinstance(value, (tuple, frozenset)):
            return ()
        return tuple(v for item in value for v in _path(item, tail))
    if isinstance(head, int):
        child = value[head] if isinstance(value, tuple) and 0 <= head < len(value) else None
    else:
        child = _get(value, head)
    return () if child is None else _path(child, tail)


def reference_paths(value: object, path: tuple[str | int, ...]) -> tuple[tuple[tuple[str | int, ...], object], ...]:
    """Expand a declared reference path to concrete (path, value) pairs.

    PATH-Q0/QPREV/OUTER/COMPLETE (1076-1086), E0-01/07 (997,1003).
    A-REFERENCE-PATH: '*' enumerates only the named tuple array, using zero
    based indices. Nested stars expand independently; repeated Point values at
    different positions remain different references. No recursive name search,
    set ordering, or out-of-range index is invented. Missing/null paths yield
    no edges; an actual reference there is still undeclared, not authorized.
    This expands paths only, and does not certify any semantic closure.
    """
    def walk(current, remaining, concrete):
        if not remaining:
            return ((concrete, current),)
        head, *tail = remaining
        if head == "*":
            if not isinstance(current, tuple):
                return ()
            return tuple(pair for index, child in enumerate(current)
                         for pair in walk(child, tail, concrete + (index,)))
        if type(head) is int:
            child = current[head] if isinstance(current, tuple) and 0 <= head < len(current) else None
        elif type(head) is str:
            child = _get(current, head)
        else:
            return ()
        return () if child is None else walk(child, tail, concrete + (head,))
    return walk(value, path, ())


class Snapshot:
    """Indexes of frozen values. 'present' is deliberately weaker than Saved.

    Consumers that need Saved report the missing seal contract. It is useful to
    refute a missing/wrong record, but cannot turn mere presence into success.
    """
    def __init__(self, state, e0):
        self.s, self.e0 = state, e0
        self.p = state.core.p
        self.entries = {e.point: e for e in state.core.e}
        self.bodies = {b.seal: b for b in state.core.c}
        self.originals = {e.key: e for e in state.evidence.eh.originals}
        self.receipts = {r.envelope.key: r for r in self.p.receipts}
        self.units = {u.id: u for u in self.p.units}
        self.units.update((r.unit.id, r.unit) for r in self.p.receipts)
        # Public E0 declaration, fixed before execution; never a P/EU plan.
        self.plans = {u.unit: u for u in getattr(e0, "publication_plans", e0.plans)}
        self.descriptors = {w.work_id: w for u in e0.plans for w in u.works}
        self.work = {w.descriptor.work_id: w for w in self.p.work}
        self.slots = {(u.id, slot.plan.slot): slot for u in self.units.values() for slot in u.slots}
        self.records = tuple((e.point, e.header.record) for e in state.core.e)
        contract = getattr(e0, "observation_contract", None)
        trace = getattr(state.evidence, "observation_trace", None)
        self.declaration_resolver = (DeclarationResolver(contract, trace)
                                     if isinstance(contract, ObservationE0) and isinstance(trace, ObservationTrace) else None)

    def present(self, point):
        entry = self.entries.get(point)
        if entry is None:
            return False
        body = self.bodies.get(entry.header.seal)
        return (body is not None and body.payload == _encode(entry.header.record)
                and _hash(entry.header) == entry.point.cid)

    def resolve(self, ref):
        if ref is None:
            return None
        if _type(ref, "Point"):
            return ref if self.present(ref) else None
        if _type(ref, "PlanRef"):
            if self.declaration_resolver is None:
                return None
            try:
                point = self.declaration_resolver.resolve(ref)
                return point if self.present(point) else None
            except UnresolvedDeclaration:
                return None
        return None

    def resolved_value(self, value):
        if _type(value, "PlanRef"):
            return self.resolve(value) or value
        if is_dataclass(value):
            return replace(value, **{f.name: self.resolved_value(getattr(value, f.name)) for f in fields(value)})
        if isinstance(value, tuple):
            return tuple(self.resolved_value(v) for v in value)
        if isinstance(value, frozenset):
            return frozenset(self.resolved_value(v) for v in value)
        return value

    def receipt_materialized(self, envelope):
        receipt = self.receipts.get(envelope.key)
        if receipt is None or receipt.envelope != envelope:
            return False
        expected = receipt_contracts(envelope.event.kind)
        slots = receipt.unit.slots
        return (Counter((s.plan.contract.name, s.plan.contract.version) for s in slots) == Counter(expected)
                and all(s.prepared and self.present(s.prepared.point) for s in slots))

    def record(self, point):
        entry = self.entries.get(self.resolve(point))
        return entry.header.record if entry else None

    def required_work(self):
        # E0 determines ALL promised descriptors, even when P.work omits one.
        return {d.work_id: d for plan in self.e0.plans if plan.unit in self.units for d in plan.works}

    def references(self, record):
        # Roles come from E0, not record.references. Typed body references outside
        # these declared paths are reported as incomplete, never 'no dependency'.
        return tuple((replace(rule, path=path), ref) for rule in self.e0.field_roles
                     if rule.record_contract == record.contract and rule.operation == "PrepareOne"
                     for path, value in reference_paths(record.content, rule.path)
                     for ref in _points(value))


def receipt_contracts(kind):
    return {
        "Boot": (("sui.s4.boot", "1"), ("sui.fb.boot_declaration", "1")),
        "Received": (("sui.fb.received", "1"),),
        "SegmentReport": (("sui.fb.segment_report", "1"),),
        "WorkFinished": (("sui.fb.work_report", "1"),),
        "DrawReturned": (("sui.fb.draw_report", "1"),),
    }.get(kind, ())


def acyclic(parents: Mapping[Hashable, Iterable[Hashable]]) -> bool:
    """Public INV-5.c clause for finite symbolic PRE-ADMISSION graphs.

    SC-05-CYCLE (1384,1393): parents maps a node to its direct parents. Symbols
    a/b need not be CIDs. {'a': {'b'}} is acyclic; adding b -> a is not. Missing
    parent records are an existence question, not a reason to skip this clause.
    A cyclic candidate is a negative checker input, not a reachable legal ledger
    and never a passing correct-window scene. True proves only acyclicity, not
    Saved, parent type, or independence of the identification experiment.
    """
    pending = {node: set(ps) for node, ps in parents.items()}
    # Missing parents violate existence, not acyclicity. Keep the two clauses
    # distinguishable for SC-05-CYCLE and for partial candidate graphs.
    for parent in {p for ps in pending.values() for p in ps} - pending.keys():
        pending[parent] = set()
    reverse = defaultdict(set)
    for node, ps in pending.items():
        for parent in ps:
            reverse[parent].add(node)
    ready = [n for n, ps in pending.items() if not ps]
    removed = set()
    while ready:
        node = ready.pop()
        if node in removed:
            continue
        removed.add(node)
        for child in reverse[node]:
            pending[child].discard(node)
            if not pending[child]:
                ready.append(child)
    return len(removed) == len(pending)


def strongly_connected(nodes, edges):
    """Iterative Kosaraju: no Python recursion limit at the 200000-state bound."""
    nodes = frozenset(nodes)
    forward, backward = defaultdict(list), defaultdict(list)
    for source, target, _ in edges:
        if source in nodes and target in nodes:
            forward[source].append(target)
            backward[target].append(source)
    seen, finish = set(), []
    for start in sorted(nodes):
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(forward[start]))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                finish.append(node)
                stack.pop()
            elif child not in seen:
                seen.add(child)
                stack.append((child, iter(forward[child])))
    seen.clear()
    result = []
    for start in reversed(finish):
        if start in seen:
            continue
        component, stack = set(), [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            component.add(node)
            for child in backward[node]:
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        result.append(frozenset(component))
    return tuple(result)


GraphEdges = tuple[tuple[int, int, Hashable], ...]
EnabledByState = Mapping[int, frozenset[Hashable]] | Sequence[frozenset[Hashable]]


def fair_cycle(nodes: Iterable[int], candidate_edges: GraphEdges, full_enabled: EnabledByState) -> bool:
    """Weak fairness of THIS recurrent candidate, using uncut enabled sets.

    Full labels include the target. A maximal SCC with all its internal edges
    admits a tour of every vertex and required edge iff this predicate holds.
    A singleton needs a self-loop; Wait after completion is filtered upstream.

    Public SC-19-T1/T2/N1/N2 input (1451-1469): nodes/edges describe the chosen
    recurrent candidate (integer state IDs), while full_enabled retains every enabled action
    in the COMPLETE graph, including exits omitted from this candidate. Labels
    identify operation AND run/target/slot, not just operation names. All chosen
    internal edges are traversed infinitely often in the represented tour.
    Negative candidates never count as correct-window passes or reachability.
    """
    nodes = frozenset(nodes)
    internal = tuple(e for e in candidate_edges if e[0] in nodes and e[1] in nodes)
    if not nodes or not internal or len(strongly_connected(nodes, internal)) != 1:
        return False
    continuous = set.intersection(*(set(full_enabled[s]) for s in nodes))
    taken = {label for _, _, label in internal}
    return continuous <= taken


def progress_counterexamples(nodes: Iterable[int], edges: GraphEdges, full_enabled: EnabledByState,
                              frontier: Iterable[int] = ()) -> tuple[frozenset[int], ...]:
    """Public L-RECEIPT/SC-19 candidate formula (1451-1469).

    nodes are the independently established undischarged/environment-ready
    states for ONE fixed target. edges are the candidate execution edges, NOT
    the source of full_enabled. Frontier states are never counted as dead ends.
    Returns fair recurrent components and genuine terminal counterexamples.
    Call only with a complete base graph for a verdict; use derive_progress's
    complete/frontier gate for an explicitly incomplete exploration. An abstract
    negative input tests the clause; it cannot certify the correct window.
    """
    nodes = frozenset(nodes) - frozenset(frontier)
    recurrent = tuple(c for c in strongly_connected(nodes, edges)
                      if fair_cycle(c, edges, full_enabled))
    outgoing = {a for a, _, _ in edges}
    dead = tuple(frozenset((s,)) for s in sorted(nodes - outgoing)
                 if not full_enabled[s])
    return recurrent + dead


@dataclass(frozen=True, slots=True)
class Clash:
    left: object
    right: object
    rule: str
    affected: frozenset[object]


def report_clashes(reports):
    """Paper CMP-04..09/CL-SAME/SEQ/MEASUREMENT on validated typed Reports.

    The caller must separately establish saved/source/request correspondence;
    raw sender claims alone never enter Reports(X).
    """
    result = set()
    unnamed = {"Gap", "Unavailable", "Claim", "Unproved"}
    def key(z):
        kind = z.kind.value
        if kind == "Frame":
            return (z.segment, _get(z.fields, "measurement_id"))
        return (z.segment, z.item_slot if kind in unnamed else kind)
    def comparison(z):
        # Report.fields is the entire typed branch. Delivery r/s are in Envelope,
        # not Report; item_slot is identity, not the measurement body.
        return (z.kind, z.route_epoch, z.fields)
    for i, (lp, left) in enumerate(reports):
        for rp, right in reports[i + 1:]:
            lk, rk = key(left), key(right)
            if lk == rk and comparison(left) != comparison(right):
                result.add(Clash(lp, rp, "CL-SAME", frozenset((lk,))))
            if left.kind.value == right.kind.value == "Frame":
                lm, rm = _get(left.fields, "measurement_id"), _get(right.fields, "measurement_id")
                ls, rs = _get(left.fields, "sample_seq"), _get(right.fields, "sample_seq")
                if (left.segment, left.route_epoch, ls) == (right.segment, right.route_epoch, rs) and lm != rm:
                    result.add(Clash(lp, rp, "CL-SEQ", frozenset((lk, rk, (left.segment, left.route_epoch, ls)))))
                if lm == rm and comparison(left) != comparison(right):
                    result.add(Clash(lp, rp, "CL-MEASUREMENT", frozenset((lk, rk, lm))))
    return frozenset(result)


def interval_atoms(interval, endpoints):
    """Endpoint/open-cell coordinates; no length arithmetic or closed-end loss."""
    if (interval.start not in endpoints or interval.end not in endpoints
            or interval.start > interval.end):
        return None
    result = {(a, b) for a, b in zip(endpoints, endpoints[1:])
              if interval.start <= a < b <= interval.end}
    result.update((t, t) for t in endpoints if
                  interval.start < t < interval.end
                  or t == interval.start < interval.end and interval.left_closed
                  or t == interval.end > interval.start and interval.right_closed
                  or t == interval.start == interval.end and interval.left_closed and interval.right_closed)
    return frozenset(result)


def _has_source(value):
    if _type(value, "Source"):
        return True
    if is_dataclass(value):
        return any(_has_source(getattr(value, f.name)) for f in fields(value))
    return isinstance(value, (tuple, frozenset)) and any(_has_source(v) for v in value)


def _persist(p, before, after, key, message):
    right = {key(v): v for v in after}
    for v in before:
        p.require(right.get(key(v)) == v, message, key(v))


def _offered(enabled, operation, target):
    return any(a.operation == operation and a.target == target for a in enabled)


def _ready_refs(x, descriptor):
    refs = set(_points(descriptor))
    # use_keys are declared logical keys; _points does not interpret strings.
    work = x.work.get(descriptor.work_id)
    resolutions = dict(work.resolutions) if work else {}
    return all(x.resolve(ref) is not None and
               (not _type(ref, "PlanRef") or resolutions.get(ref) == x.resolve(ref))
               for ref in refs)


def actual_start_history(trace):
    """EW only: START-0/1/2/3/? and Occ (829-835,1285-1294).

    Empty history is distinct from missing transport. An invalid release does
    not free capacity; another work's events do not change this work's stage.
    """
    held, wrappers, entered, uncertain, stopped, ended = {}, defaultdict(set), set(), set(), set(), set()
    for event in trace.events:
        key, value = event.key, event.value
        if event.tag == "Reserve":
            held.setdefault(key, value.resources)
        elif event.tag == "Launch":
            wrappers[key.work].add(value.wrapper)
        elif event.tag == "LaunchResponse":
            if value.response == "unknown":
                uncertain.add(key.work)
            elif value.response == "not_entered":
                wrappers[key.work].discard(value.wrapper)
        elif event.tag in ("ConsumeToken", "EnterBody"):
            entered.add(key.work)
        elif event.tag == "HostUnknown":
            uncertain.add(key.work)
        elif event.tag == "WorkerReturn":
            ended.add(key.work)
        elif event.tag == "Stop":
            stopped.add(key)
        elif event.tag == "Release" and key in stopped and held.get(key) == value.resources:
            held.pop(key, None)
            ended.add(key.work)
    return held, wrappers, entered, uncertain, ended


def actual_owner_exists(state, owner):
    """1185/1193: an owner reference is not proof of the actual owner row."""
    p = state.core.p
    if owner.location == "P.work":
        return any(w.descriptor.work_id == owner.key for w in p.work)
    if owner.location == "P.units":
        return any(u.id == owner.key for u in p.units)
    if owner.location == "P.receipts":
        return any(owner.key in (r.envelope.key, r.unit.id) for r in p.receipts)
    if owner.location == "H":
        return (owner.key == state.core.h.run or any(k.id == owner.key for k in state.core.h.interval_requests)
                or any(e.key == owner.key for e in state.core.h.queue))
    return False


def bootstrap_origin(contract, trace, descriptor):
    """1018-1019/874: follow the process declaration, not a unit-name heuristic.

    The existing A-INITIAL-WIRE's origin field is interpreted only on the E0
    process recipe or its independently resolved Saved record. O-02 ownership
    is also independent provenance; the actual stage is checked separately.
    """
    norm = next((d for d in contract.descriptors if d.work_id == descriptor.work_id), descriptor)
    if any(p.obligation_id == "O-02" and any(d.work_id == norm.work_id for d in p.works) for p in contract.plans):
        return True
    ref = norm.process
    if _type(ref, "PlanRef"):
        records = [r for p in contract.plans if p.unit == ref.unit for r in p.records if r.slot == ref.slot]
    else:
        records = [e.header.record for e in trace.entries if e.point == ref and ledger_saved(ref, trace, contract.codec)]
    return any(_get(r.content, "origin") == "bootstrap" for r in records)


def _reference_check(p, x, record):
    declared = x.references(record)
    expected = {(rule.path_id, rule.path, ref, rule.role, rule.use) for rule, ref in declared}
    actual = {(r.path_id, r.path, r.ref, r.role, r.use) for r in record.references}
    p.require(expected == actual, "typed reference list/roles disagree with E0 field paths", record.name)
    for _, _, ref, _, _ in expected:
        p.require(_type(ref, "Point") and x.present(ref), "body reference is unresolved or not materialized", ref)
    body_points = set(_points(record.content))
    if body_points - {ref for _, ref in declared}:
        p.gap("references")
    p.gap("seal")


def _plan_check(p, x, unit):
    allowed = x.plans.get(unit.id)
    if allowed is None:
        # Diagnostic T/V are generated by EndKnown, not necessarily explicit
        # AllowedPlans. No missing plan is quietly accepted as an empty plan.
        if unit.obligation_id in {"O-05", "O-07", "O-09.a", "O-10", "O-11", "O-12", "O-G"}:
            p.gap("completion")
        else:
            p.require(False, "publication has no E0 plan or declared terminal derivation", unit.id)
        return
    if (_has_source(allowed) or allowed.obligation_id == 'O-G') and x.declaration_resolver is not None:
        try:
            allowed = x.declaration_resolver.plan(unit.id)
        except UnresolvedDeclaration as error:
            p.gap("約束の未接続: " + str(error))
    p.require((unit.obligation_id, unit.key) == (allowed.obligation_id, allowed.key),
              "publication obligation/key differs from E0", unit.id)
    p.require(tuple(slot.plan.slot for slot in unit.slots) == tuple(r.slot for r in allowed.records),
              "publication record slots differ from E0 (including missing slots)", unit.id)
    p.require(unit.works == tuple(d.work_id for d in allowed.works),
              "publication promised work list differs from E0", unit.id)
    for expected in allowed.records:
        actual = next((s.plan for s in unit.slots if s.plan.slot == expected.slot), None)
        if _has_source(expected):
            p.gap("facts")
        else:
            p.require(actual == expected, "publication record plan differs from E0 in fixed fields", (unit.id, expected.slot))
    for expected in allowed.works:
        actual = x.work.get(expected.work_id)
        p.require(actual is not None and actual.descriptor == expected,
                  "publication lacks the simultaneous corresponding work row", expected.work_id)
    if allowed.semantic_limits:
        p.gap("references")


def _storage_enabled(p, x, enabled, unit, receipt=False):
    if not x.s.controls.normal_window:
        return
    c = x.s.controls
    for slot in unit.slots:
        key = (unit.id, slot.plan.slot)
        prepared = slot.prepared
        if prepared is None:
            refs = set(_points(slot.plan))
            if all(x.resolve(ref) is not None for ref in refs):
                p.require(_offered(enabled, "PrepareReceipt" if receipt else "PrepareOne", key),
                          "ready unprepared slot lacks its preparation operation", key)
        elif prepared.seal not in x.bodies:
            if c.body_put:
                p.require(_offered(enabled, "PutBody", key), "body capability exists but PutBody is absent", key)
        else:
            # EP distinguishes confirmation from response loss. Its tagged
            # schema is absent, so do not read Slot.body_confirmed as truth.
            p.gap("facts")
            if prepared.point not in x.entries and c.entry_add:
                p.require(any(_offered(enabled, op, key) for op in ("ConfirmBody", "PutBody", "AddEntry")),
                          "body exists but no confirmation/retry/entry step is offered", key)
            elif prepared.point in x.entries and c.body_read and c.entry_read:
                # CompleteWrite may already have run. A completed memory bit is
                # neither evidence of readback nor grounds for demanding it twice.
                p.gap("SAVE-7/8: EP readback/completion event decoding is unavailable")
        p.gap("seal")


def _first_candidates(x, work):
    """Ordering is computable; source validation is a separate missing EH tag.

    These are candidates, NOT EndKnown/valid Reports. Never used to authorize
    success or certify an adopted result.
    """
    descriptor = x.descriptors.get(work)
    kind = "DrawReturned" if descriptor is not None and descriptor.stage == "D" else "WorkFinished"
    envelopes = [e for e in x.s.evidence.eh.originals
                 if e.event.kind == kind
                 and _get(e.event.fields, "work") == work]
    return tuple(sorted(envelopes, key=lambda e: (e.r.rank, e.receipt_seq)))


def _receipt_projection(x):
    points = {s.prepared.point for r in x.p.receipts for s in r.unit.slots if s.prepared}
    todo = list(points)
    while todo:
        entry = x.entries.get(todo.pop())
        if entry:
            for parent in entry.header.parents - points:
                points.add(parent)
                todo.append(parent)
    entries = frozenset(e for p, e in x.entries.items() if p in points)
    seals = {e.header.seal for e in entries}
    seals.update(s.prepared.seal for r in x.p.receipts for s in r.unit.slots if s.prepared)
    bodies = frozenset(b for seal, b in x.bodies.items() if seal in seals)
    c = x.s.controls
    return (x.s.core.h.run, x.s.core.h.reading, x.s.core.h.queue,
            x.s.evidence.eh.originals, x.s.evidence.eh.acknowledgements,
            x.p.receipts, entries, bodies, c.normal_window, c.normal_host,
            c.body_put, c.body_read, c.entry_add, c.entry_read)


def _receipt_services(x, enabled):
    units = {r.unit.id for r in x.p.receipts}
    return frozenset((a.operation, a.target) for a in enabled if
                     a.operation in ("Accept", "HostAck")
                     or a.operation in STORAGE_OPS and a.target and a.target[0] in units)


STORAGE_OPS = frozenset(("PrepareReceipt", "PrepareOne", "PutBody", "ConfirmBody", "AddEntry", "ConfirmWrite", "CompleteWrite"))
RECEIPT_FAIR = STORAGE_OPS | {"Accept", "HostAck"}


class Checker:
    """Passive observer, with one executable dispatch for every paper row.

    Identification *specified* (13 rows) is not identification *demonstrated*.
    No row is promoted by a successful positive smoke test. A checker author
    cannot certify their own identification via a caller-supplied success bit.
    """
    def __init__(self):
        self.failures = {c: {} for c in CONDITION_IDS}
        self.limits = {c: set() for c in CONDITION_IDS}
        self.observations = Counter()
        self.reached = Counter()
        self.complete = False
        self._snapshots = {}
        self._boundary_failures = {}
        self._connections = {c: set() for c in CONDITION_IDS}
        self._unconnected_observations = set()
        self._observation_e0 = None

    def on_observations(self, contract, trace, location=("typed-evidence",), kinds=None):
        """Also usable by hand-built public observations before explorer wiring."""
        evaluation = evaluate_observations(contract, trace)
        for row in CONDITION_IDS:
            self._connections[row].add(evaluation.boundary.connection)
        for failure in evaluation.boundary.violations:
            self._boundary_failures.setdefault((failure.path, failure.message), failure)
        if evaluation.boundary.connection == "約束接続・部分判定":
            if self._observation_e0 is None:
                self._observation_e0 = contract
            elif self._observation_e0 != contract:
                failure = BoundaryViolation("E0", "frozen observation declaration changed between states",
                                            Paper(("E0", "REF-8"), (1065, 1065)))
                self._boundary_failures.setdefault((failure.path, failure.message), failure)
                for row in CONDITION_IDS:
                    self._connections[row].add("約束違反")
            for clause in evaluation.clauses:
                if kinds is not None and not next(r.kinds for r in ROWS if r.condition_id == clause.row) & kinds:
                    continue
                self.observations[clause.row] += 1
                Probe(self, clause.row, location).require(clause.satisfied, clause.message, clause.target)
            for row, limitation in evaluation.limitations:
                self.limits[row].add(limitation)
        return evaluation

    def _snapshot(self, index, state, e0):
        if index not in self._snapshots:
            self._snapshots[index] = Snapshot(state, e0)
        return self._snapshots[index]

    def on_state(self, observation):
        contract = (observation.observation_contract if observation.observation_contract is not None
                    else getattr(observation.e0, "observation_contract", None))
        contract = bind_interval_declarations(contract, observation.e0)
        trace = (observation.observation_trace if observation.observation_trace is not None
                 else getattr(observation.state.evidence, "observation_trace", None))
        evaluation = self.on_observations(contract, trace, ("state", observation.index, "typed-evidence"),
                                          {PropertyKind.STATE, PropertyKind.ENABLED})
        if evaluation.boundary.connection == "約束接続・部分判定":
            # EL is a transported read of C/E, not an independently forgeable
            # second ledger with which the window can agree by construction.
            if frozenset(observation.state.core.c) != trace.bodies or frozenset(observation.state.core.e) != trace.entries:
                failure = BoundaryViolation("EL", "observation trace differs from actual state C/E",
                                            Paper(("EL", "INV-4"), (820, 820)))
                self._boundary_failures.setdefault((failure.path, failure.message), failure)
                self._connections["INV-4.a"].add("約束違反")
            for name in ("plans", "capacity", "allocation"):
                expected = getattr(observation.e0, name)
                # Older transport omits static T/V; retain its missing-plan
                # violation at Publish. Full transport uses the public E0
                # publication_plans declaration, never plans taken from EU.
                if name == "plans" and contract.plans != expected:
                    expected = getattr(observation.e0, "publication_plans", expected)
                if getattr(contract, name) != expected:
                    failure = BoundaryViolation("E0." + name, "supplement disagrees with independently frozen E0",
                                                Paper(("E0",), (816, 816)))
                    self._boundary_failures.setdefault((failure.path, failure.message), failure)
                    for row in CONDITION_IDS:
                        self._connections[row].add("約束違反")
            if trace.clock is not None and trace.clock != observation.state.core.h.reading:
                failure = BoundaryViolation("EH.clock", "transported clock differs from the actual host reading",
                                            Paper(("EH", "INV-1.b"), (461, 461)))
                self._boundary_failures.setdefault((failure.path, failure.message), failure)
                self._connections["INV-1.b"].add("約束違反")
            expected_intervals = bind_interval_declarations(ObservationE0(), observation.e0).intervals
            if contract.intervals != expected_intervals:
                failure = BoundaryViolation("E0.intervals", "interval declarations disagree with raw E0 requests",
                                            Paper(("E0-02", "REF-5"), (998, 1062)))
                self._boundary_failures.setdefault((failure.path, failure.message), failure)
                self._connections["INV-12.a"].add("約束違反")
            # A retained request exposes a transport gap; it does NOT establish
            # the undertaking time. Neither E0 declarations nor EI progress may
            # manufacture C-O04 occurrence (1186,1205-1207).
            retained = (*observation.state.core.h.interval_requests, *observation.state.evidence.ei.requests)
            for request in retained:
                key = IntervalKey(request.id, request.route_epoch, request.interval.run)
                if not any(e.tag == "IntervalUndertaken" and e.key == key for e in trace.events):
                    for row in ("INV-2.a", "INV-12.a"):
                        self._unconnected_observations.add((row, "IntervalUndertaken"))
                        self.limits[row].add("約束の未接続: retained interval request lacks actual EH IntervalUndertaken; "
                                            "E0/EI retention is not occurrence: " + repr(key))
        x = self._snapshot(observation.index, observation.state, observation.e0)
        for row in ROWS:
            if row.kinds & {PropertyKind.STATE, PropertyKind.ENABLED}:
                p = Probe(self, row.condition_id, ("state", observation.index))
                self.observations[row.condition_id] += 1
                self._state(row.condition_id, p, x, observation.enabled)

    def on_step(self, observation):
        contract = (observation.observation_contract if observation.observation_contract is not None
                    else getattr(observation.e0, "observation_contract", None))
        contract = bind_interval_declarations(contract, observation.e0)
        before_trace = (observation.before_trace if observation.before_trace is not None
                        else getattr(observation.before.evidence, "observation_trace", None))
        after_trace = (observation.after_trace if observation.after_trace is not None
                       else getattr(observation.after.evidence, "observation_trace", None))
        if contract is not None and before_trace is not None and after_trace is not None:
            actual_acquisitions = set(observation.after.evidence.ea.acquisitions) - set(observation.before.evidence.ea.acquisitions)
            transported = {e.value.acquisition for e in observation.actual_events
                           if isinstance(e, ObservationEvent) and e.tag == "Acquire" and isinstance(e.value, Acquired)}
            if actual_acquisitions != transported:
                self.limits["INV-9.a"].add("約束の未接続: Acquire must accompany the actual EA acquisition edge, before G publication (1216)")
            self.on_observations(contract, after_trace, ("edge", observation.source, observation.target, "typed-evidence"),
                                 {PropertyKind.STEP})
            evaluation = evaluate_observation_step(contract, before_trace, after_trace, observation.actual_events,
                                                   before_state=observation.before, after_state=observation.after,
                                                   action=observation.action)
            for failure in evaluation.boundary.violations:
                self._boundary_failures.setdefault((failure.path, failure.message), failure)
                for row in CONDITION_IDS:
                    self._connections[row].add("約束違反")
            for clause in evaluation.clauses:
                self.observations[clause.row] += 1
                Probe(self, clause.row, ("edge", observation.source, observation.target, "typed-evidence")).require(
                    clause.satisfied, clause.message, clause.target)
            for row, limitation in evaluation.limitations:
                self.limits[row].add(limitation)
        else:
            for row in CONDITION_IDS:
                self._connections[row].add("約束の未接続")
        a = self._snapshot(observation.source, observation.before, observation.e0)
        b = self._snapshot(observation.target, observation.after, observation.e0)
        for row in ROWS:
            if PropertyKind.STEP in row.kinds:
                p = Probe(self, row.condition_id, ("edge", observation.source, observation.target,
                                                  observation.action.operation, observation.action.target))
                self.observations[row.condition_id] += 1
                self._step(row.condition_id, p, a, b, observation)

    def _state(self, row, p, x, enabled):
        if row in ("INV-2.g", "INV-16.c"):
            self._conditions(p, x, row)
        elif row == "INV-1.a":
            for e in x.s.evidence.eh.originals:
                retained = e in x.s.core.h.queue or (e.key in x.receipts and x.receipts[e.key].envelope == e)
                p.require(retained or x.receipt_materialized(e), "posted unsaved envelope has no owner", e.key)
            p.gap("receipt_wire")
        elif row == "INV-1.b":
            for receipt in x.p.receipts:
                p.require(x.originals.get(receipt.envelope.key) == receipt.envelope,
                          "receipt envelope differs from the full EH original", receipt.envelope.key)
            p.gap("facts")
            p.gap("receipt_wire")
        elif row == "INV-1.c":
            names = []
            for e in x.s.evidence.eh.originals:
                rs = [r for r in x.p.receipts if r.envelope.key == e.key]
                p.require(len(rs) <= 1, "duplicate custody receipt for one envelope", e.key)
                for r in rs:
                    actual = [(s.plan.contract.name, s.plan.contract.version) for s in r.unit.slots]
                    p.require(Counter(actual) == Counter(receipt_contracts(e.event.kind)),
                              "receipt/Boot record population differs from paper", e.key)
                    names.extend((s.prepared.record.name, e.key, s.plan.slot) for s in r.unit.slots if s.prepared)
            p.require(len({name for name, _, _ in names}) == len(names), "different receipt slots share a record name")
            p.gap("receipt_wire")
        elif row == "INV-2.a":
            self._conditions(p, x, row)
            for wid in x.required_work():
                p.require(wid in x.work, "E0-promised work has no P.work owner", wid)
            for e in x.s.evidence.eh.originals:
                p.require(e in x.s.core.h.queue or e.key in x.receipts or x.receipt_materialized(e),
                          "O-01 responsibility disappeared", e.key)
            for k in x.s.evidence.ei.requests:
                p.require(k in x.s.core.h.interval_requests or k.work in x.work,
                          "O-04 responsibility has no host/work owner", k.id)
            # Pre-publication obligations are not enumerated from P.units.
            for intent in x.e0.acquisitions:
                if x.resolve(intent.completion):
                    p.require(x.s.core.h.run == x.e0.run, "O-08 host owner is absent", intent.id)
            p.gap("completion")
            p.gap("facts")
            if x.e0.derivations:
                p.gap("derivation")
        elif row == "INV-2.c":
            for wid, desc in x.descriptors.items():
                if desc.stage not in END_WORK_TYPES:
                    continue
                candidates = _first_candidates(x, wid)
                if candidates and x.receipt_materialized(candidates[0]):
                    # The work row owns unmaterialized T/V; no immediate Publish
                    # or successful R/P is required merely because a reply exists.
                    p.require(wid in x.work, "known end lost its T/V and purpose owner", wid)
            self._conditions(p, x, row)
            p.gap("completion")
            p.gap("facts")
        elif row == "INV-2.d":
            for plan in x.e0.plans:
                if plan.obligation_id == "O-03" and plan.unit in x.units:
                    _plan_check(p, x, x.units[plan.unit])
                    _storage_enabled(p, x, enabled, x.units[plan.unit])
            if x.e0.derivations or any(u.obligation_id == "O-03" for u in x.p.units):
                p.gap("derivation")
        elif row == "INV-2.e":
            trace = x.s.evidence.observation_trace
            if not isinstance(trace, ObservationTrace):
                p.gap("facts")
                return
            held, wrappers, entered, uncertain, ended = actual_start_history(trace)
            generation = (GenerationFacts(x.e0.observation_contract, trace, x.s)
                          if any(d.stage == 'Wg' for d in x.descriptors.values()) else None)
            occupation = Counter()  # quantities, not phase counts
            for resources in held.values():
                occupation.update(dict(resources))
            for wid, desc in x.required_work().items():
                work = x.work.get(wid)
                resolutions = work.resolutions if work is not None else ()
                if wid in entered | uncertain | ended or not start_references_ready(
                        x.e0.observation_contract, trace, desc, resolutions):
                    continue
                if desc.semantic_limits or desc.use_keys:
                    p.gap("references")  # no invented Ready for unsupported use closure
                    continue
                if generation is not None:
                    blocked = generation.start_conflict(desc)
                    if blocked is None:
                        p.gap("M3 start-use dependency adapter is unconnected")
                        continue
                    if blocked:
                        continue  # 840/852/867/1957: Saved alone is not StartReady.
                reserved = any(k.work == wid for k in held)
                if not reserved:  # START-0: allocation minus ALL actual occupancy
                    fit = all(n <= dict(x.e0.allocation).get(a, 0) - occupation[a] for a, n in desc.need)
                    if x.s.controls.normal_window and fit:
                        p.require(_offered(enabled, "ClaimStart", (wid,)), "ready unreserved work lacks ClaimStart", wid)
                elif not wrappers[wid]:  # START-1 and START-2 retain the same reservation
                    if x.s.controls.normal_host:
                        p.require(_offered(enabled, "Launch", (wid,)), "ready reserved/retry work lacks Launch", wid)
                elif x.s.controls.normal_wrapper:  # START-3; window failure is irrelevant
                    p.require(any(_offered(enabled, "EnterWorker", (w,)) for w in wrappers[wid]),
                              "ready launched work lacks EnterWorker", wid)
            p.gap("references")
            p.gap("seal")
        elif row == "INV-2.f":
            for work in x.p.work:
                for excuse in work.purposes:
                    self._excuse(p, x, work, excuse, enabled)
        elif row == "INV-3.a":
            counts = Counter(r.work for r in x.s.core.runners)
            for wid, count in counts.items():
                p.require(count <= 1, "more than one actual body for a WorkId", wid)
                tokens = {r.token for r in x.s.core.runners if r.work == wid}
                w = x.work.get(wid)
                p.require(w is not None and tokens == {w.token}, "body token has no corresponding custody token", wid)
            if x.s.evidence.ew.events:
                p.gap("facts")
        elif row == "INV-3.b":
            for wid, work in x.work.items():
                p.require(x.descriptors.get(wid) == work.descriptor, "fixed descriptor differs from independent E0", wid)
                for ref, point in work.resolutions:
                    p.require(x.resolve(ref) == point, "PlanRef resolution points to a different plan/slot", (wid, ref))
            if x.s.evidence.ew.events:
                p.gap("facts")
        elif row == "INV-3.c":
            if not x.s.evidence.ew.events:
                for wid, work in x.work.items():
                    p.require(not work.held and not work.released, "reservation/release asserted without any actual history", wid)
            else:
                p.gap("facts")
        elif row == "INV-4.a":
            for entry in x.s.core.e:
                body = x.bodies.get(entry.header.seal)
                p.require(body is not None, "ledger entry has no corresponding body", entry.point)
                if body:
                    p.require(body.payload == _encode(entry.header.record), "body bytes disagree with full header record", entry.point)
                p.require(_hash(entry.header) == entry.point.cid, "CID does not hash the full header", entry.point)
            p.gap("seal")
        elif row == "INV-4.b":
            if x.s.evidence.ep.first_preparations:
                p.gap("facts")
            for key, slot in x.slots.items():
                prepared = slot.prepared
                if prepared:
                    p.require(prepared.record == prepared.header.record and prepared.parents == prepared.header.parents
                              and prepared.seal == prepared.header.seal,
                              "PreparedEntry fixed fields disagree internally", key)
        elif row == "INV-5.c":
            parents = {entry.point: entry.header.parents for entry in x.s.core.e}
            for child, refs in parents.items():
                for ref in refs:
                    entry = x.entries.get(ref)
                    p.require(entry is not None and x.present(ref), "parent does not resolve to an existing record", (child, ref))
                    if entry:
                        record = entry.header.record
                        p.require(record.category == "Event", "parent is not an allowed Event (Prediction is forbidden)", (child, ref))
            p.require(acyclic(parents), "causal parent graph has a cycle")
            p.gap("seal")
            p.gap("references")
        elif row == "INV-6.a":
            self._completed(p, x)
        elif row == "INV-6.b":
            terminal = Counter(_get(r.content, "work") for _, r in x.records
                               if r.contract.name == "sui.fb.work_terminal")
            for wid, count in terminal.items():
                p.require(count <= 1, "same terminal right consumed twice", wid)
            p.gap("apply")
            if x.s.evidence.ew.events:
                p.gap("facts")
        elif row == "INV-6.c":
            counts = Counter((a.reader, a.intent) for a in x.s.evidence.ea.acquisitions)
            for identity, count in counts.items():
                p.require(count == 1, "one acquisition intent produced multiple actual acquisitions", identity)
            for actual in x.s.evidence.ea.acquisitions:
                intent = next((i for i in x.e0.acquisitions if i.id == actual.intent), None)
                p.require(intent is not None, "actual acquisition has no declared intent", actual.intent)
                if intent:
                    p.require(x.resolve(intent.reader) == actual.reader
                              and {x.resolve(t) for t in intent.targets} == set(actual.targets),
                              "acquisition conflates reader/intent/targets", actual.intent)
            p.gap("adoption")
            p.gap("apply")
        elif row == "INV-7.a":
            # No sender claim or Xc claim is promoted to a validated report.
            for _, r in x.records:
                if r.contract.name == "sui.fb.conflict":
                    refs = _get(r.content, "reports", frozenset())
                    p.require(len(refs) >= 2 and all(x.present(ref) for ref in refs),
                              "conflict record lacks two materialized evidence reports", r.name)
                    p.gap("facts")
            p.gap("references")
            p.gap("apply")
        elif row == "INV-8.a":
            for wid, work in x.work.items():
                expected = x.descriptors.get(wid)
                p.require(expected is not None and work.descriptor == expected,
                          "work's full expected input/descriptor differs from E0", wid)
            for call in x.s.evidence.ea.calls:
                expected = x.descriptors.get(call.work)
                if expected:
                    p.require(call.input_read == x.resolved_value(expected.numerical_view),
                              "verification changed numerical input to its evidence view", call.work)
            p.gap("references")
        elif row == "INV-9.a":
            self._verification(p, x)
        elif row == "INV-9.b":
            counts = Counter(reader for reader, _ in x.p.adoption_reservations)
            for reader, count in counts.items():
                p.require(count <= 1, "reader has more than one unpersisted adoption reservation", reader)
            for intent in x.e0.adoptions:
                plan = x.units.get(intent.plan)
                if plan:
                    p.require(x.resolve(intent.reader) is not None, "adoption reader is unresolved", intent.id)
            p.gap("adoption")
        elif row == "INV-10.a":
            capacities, allocations = dict(x.e0.capacity), dict(x.e0.allocation)
            for resource in capacities.keys() | allocations.keys():
                p.require(0 <= allocations.get(resource, 0) <= capacities.get(resource, 0),
                          "allocation exceeds independent capacity", resource)
            if x.s.evidence.ew.events:
                p.gap("facts")
            else:
                for wid, work in x.work.items():
                    p.require(not any(n for _, n in work.held), "held occupancy exists without actual reservation history", wid)
        elif row == "INV-11.a":
            queue = x.s.core.h.queue
            if queue:
                e = queue[0]
                original = x.originals.get(e.key)
                well_formed = (original == e and e.run == x.e0.run and e.r.run == e.run
                               and e.r.source == x.e0.clock_source and bool(receipt_contracts(e.event.kind)))
                if x.s.controls.normal_window and well_formed and e.key not in x.receipts:
                    p.require(_offered(enabled, "Accept", (e,)), "eligible well-formed receipt lacks Accept", e.key)
                if e.key in x.receipts and x.receipts[e.key].envelope == e and x.s.controls.normal_host:
                    p.require(_offered(enabled, "HostAck", e.key), "accepted head lacks host acknowledgement", e.key)
            p.gap("receipt_wire")
        elif row == "INV-11.b":
            for e in x.s.evidence.eh.originals:
                r = x.receipts.get(e.key)
                if r:
                    _storage_enabled(p, x, enabled, r.unit, receipt=True)
        elif row == "INV-12.a":
            self._intervals(p, x)
        elif row == "INV-12.b":
            for request in x.s.evidence.ei.requests:
                for cell in request.cells:
                    conditions = [c for c in x.p.conditions if c.key.obligation == "O-04" and c.key.kind == "handle"
                                  and _type(c.key.target, "WorkKey") and c.key.target.work == request.work]
                    contract, trace = x.e0.observation_contract, x.s.evidence.observation_trace
                    if isinstance(trace, ObservationTrace):
                        # 873/1207: an absent owner/condition is still in the E0/EI
                        # population. Without any report, no Support interpretation
                        # can manufacture coverage or a witnessed cell conclusion.
                        declared = [b for b in contract.completions if b.trigger == "IntervalRequest"
                                    and b.key.kind == "handle" and _type(b.key.target, "WorkKey")
                                    and b.key.target.work == request.work and completion_occurred(b, contract, trace)]
                        reports = [e for e in trace.events if e.tag == "ReportGenerated" and e.value.work == request.work]
                        if declared and not reports:
                            p.require(all(any(c.key == b.key and b.key in c.unmet and actual_owner_exists(x.s, c.owner)
                                              for c in conditions) for b in declared),
                                      "unreported requested cell lost its independently born responsibility", (request.id, cell))
                    if conditions:
                        p.require(any(actual_owner_exists(x.s, c.owner) for c in conditions),
                                  "requested cell's transferred responsibility has no actual owner", (request.id, cell))
                    # O-04 N has H ownership until k publication; after k is
                    # saved, Report/MeasureSegment/typed missing evidence is needed.
                    if x.resolve(request.point):
                        p.require(request.work in x.work, "requested cell has no corresponding report work owner", (request.id, cell))
                    else:
                        p.require(request in x.s.core.h.interval_requests or request.work in x.work,
                                  "unpublished interval cell has no undertaking owner", (request.id, cell))
            if x.s.evidence.ei.requests:
                p.gap("support")
        elif row == "INV-13.a":
            if x.e0.initial is None:
                contract, trace = x.e0.observation_contract, x.s.evidence.observation_trace
                if isinstance(trace, ObservationTrace):
                    actual_descriptors = [w.descriptor for w in x.p.work]
                    actual_descriptors.extend(d for e in trace.events if e.tag == "Publish" for d in e.value.plan.works)
                    actual_descriptors.extend(e.value.descriptor for e in trace.events if e.tag in ("Reserve", "ReadInputs"))
                    actual_descriptors.extend(x.descriptors[e.key.work] for e in trace.events
                                              if e.tag == "EnterBody" and e.key.work in x.descriptors)
                    actual_descriptors.extend(r.descriptor_read for r in x.s.core.runners if r.descriptor_read is not None)
                    for d in actual_descriptors:
                        p.require(d.stage == "MeasureSegment" or not bootstrap_origin(contract, trace, d),
                                  "bootstrap process published/entered computation with initial=None", d.work_id)
                bootstrap = {d.work_id for plan in x.e0.plans if plan.obligation_id == "O-02"
                             for d in plan.works if d.stage != "MeasureSegment"}
                for work in x.p.work:
                    d = work.descriptor
                    from_initial = d.work_id in bootstrap or any(
                        u.obligation_id == "O-02" and d.work_id in u.works for u in x.p.units)
                    p.require(not from_initial or d.stage == "MeasureSegment",
                              "bootstrap computation exists with initial=None", d.work_id)
                for runner in x.s.core.runners:
                    p.require(runner.work not in bootstrap, "bootstrap body entered with initial=None", runner.work)
        elif row == "INV-14.a":
            grouped = defaultdict(list)
            for desc in x.descriptors.values():
                if desc.stage == "D":
                    # ID-bearing Draw arguments are not a typed public value.
                    # Do not use WorkId as a substitute Draw right denominator.
                    p.gap("RIGHT-DRAW: Descriptor.args has no declared DrawRequest field conversion")
                    grouped[desc.args].append(desc.work_id)
            for args, ids in grouped.items():
                p.require(sum(r.work in ids for r in x.s.core.runners) <= 1,
                          "identical full Draw request entered across multiple WorkIds", tuple(ids))
            if grouped:
                p.gap("facts")
        elif row == "INV-15.a":
            for wid, work in x.work.items():
                if work.descriptor.stage not in END_WORK_TYPES or work.first is None:
                    continue
                candidates = _first_candidates(x, wid)
                if not candidates:
                    p.require(False, "terminal points to no EH end notice", wid)
                    continue
                selected = x.originals.get(work.first)
                p.require(selected is not None and selected in candidates,
                          "chosen first notice is unrelated to this work", wid)
                if selected:
                    p.require(x.receipt_materialized(selected), "chosen first notice is not materialized", wid)
                    for earlier in x.s.evidence.eh.originals:
                        if earlier.run == selected.run and (earlier.r.rank, earlier.receipt_seq) < (selected.r.rank, selected.receipt_seq):
                            p.require(earlier.key in x.receipts, "terminal fixed before preceding Post was accepted", wid)
                # argmin applies only to source-validated candidates. The absent
                # generation tag schema cannot be replaced with sender WorkId.
                p.gap("facts")
                p.gap("receipt_wire")
                p.gap("seal")
        elif row == "INV-15.b":
            for wid, work in x.work.items():
                if work.knowledge is not None:
                    p.require(work.first is not None, "terminal knowledge lacks first receipt binding", wid)
                    if work.first in x.originals:
                        declared = _get(x.originals[work.first].event.fields, "outcome")
                        if _type(declared, "Outcome"):
                            p.require(work.knowledge == declared, "logical end differs from first notice's full outcome", wid)
                        else:
                            p.gap("receipt_wire")
            p.gap("completion")
        elif row == "INV-16.a":
            for point, record in x.records:
                if record.contract.name == "sui.fb.selection":
                    evaluated = _get(record.content, "evaluated")
                    p.require(evaluated is not None and x.present(evaluated),
                              "selection has no materialized corresponding evaluation", point)
                    p.gap("artifact")
        else:
            raise AssertionError(f"no state predicate for {row}")

    def _step(self, row, p, a, b, o):
        op, target = o.action.operation, o.action.target
        if row in ("INV-2.g", "INV-16.c"):
            self._conditions(p, b, row)
        elif row in ("INV-1.a", "INV-1.b"):
            _persist(p, a.s.evidence.eh.originals, b.s.evidence.eh.originals, lambda e: e.key, "EH original changed or vanished")
            if row == "INV-1.a":
                for e in a.s.core.h.queue:
                    if e not in b.s.core.h.queue:
                        p.require(e.key in b.receipts and b.receipts[e.key].envelope == e
                                  or b.receipt_materialized(e), "host dropped original before complete handoff", e.key)
            else:
                for key, old in a.receipts.items():
                    new = b.receipts.get(key)
                    p.require(new is not None and new.envelope == old.envelope
                              and tuple(s.plan for s in new.unit.slots) == tuple(s.plan for s in old.unit.slots),
                              "reaccept changed receipt/envelope plans", key)
                if op == "Accept" and target:
                    envelope = target[0]
                    original = a.originals.get(envelope.key)
                    if original != envelope:
                        p.require(b.p == a.p and not _type(o.result, "Acceptance"), "mismatched same-number receipt was accepted", envelope.key)
        elif row == "INV-2.a":
            for wid in a.work:
                p.require(wid in b.work, "work owner vanished (including stopped/Unknown work)", wid)
            for uid, unit in a.units.items():
                if uid not in b.units:
                    p.require(all(s.prepared and b.present(s.prepared.point) for s in unit.slots),
                              "published record responsibility vanished before storage", uid)
        elif row == "INV-2.b":
            for uid in b.units.keys() - a.units.keys():
                if uid not in {r.unit.id for r in b.p.receipts}:
                    _plan_check(p, b, b.units[uid])
            if op in ("PublishUnit", "Recognize") and target and target[0] in b.plans:
                p.require(target[0] in b.units, "executed publication lacks its unit", target[0])
                if target[0] in b.units:
                    _plan_check(p, b, b.units[target[0]])
            for wid in a.work:
                p.require(wid in b.work, "published successor disappeared during its lifetime", wid)
            if a.s.evidence.eu != b.s.evidence.eu:
                p.gap("facts")
        elif row == "INV-2.c":
            self._state(row, p, b, ())
            for wid, work in a.work.items():
                if work.knowledge is not None and wid not in b.work:
                    p.require(False, "end owner removed without typed CloseSave/HandoffPurpose evidence", wid)
            p.gap("completion")
        elif row == "INV-2.f":
            self._state(row, p, b, ())
        elif row in ("INV-3.a", "INV-3.c"):
            self._state(row, p, b, ())
            p.gap("facts")
        elif row == "INV-3.b":
            for wid, old in a.work.items():
                new = b.work.get(wid)
                p.require(new is not None and new.descriptor == old.descriptor, "fixed full descriptor changed/deleted", wid)
                if new:
                    for ref, point in old.resolutions:
                        p.require(dict(new.resolutions).get(ref) == point, "previous PlanRef resolution changed", (wid, ref))
            if op in ("Launch", "EnterWorker"):
                p.gap("facts")
        elif row == "INV-4.b":
            for key, old in a.slots.items():
                if old.prepared:
                    new = b.slots.get(key)
                    if new and new.prepared:
                        p.require(new.prepared == old.prepared, "retry changed one or more PreparedEntry fixed fields", key)
                    elif not b.present(old.prepared.point):
                        p.require(False, "PreparedEntry discarded before matching storage", key)
            p.gap("facts")
        elif row == "INV-4.c":
            for key, slot in b.slots.items():
                old = a.slots.get(key)
                first = slot.prepared and (old is None or old.prepared is None)
                if first:
                    prepared = slot.prepared
                    if key[0] in b.plans:
                        plan = next((r for r in b.plans[key[0]].records if r.slot == key[1]), None)
                        p.require(plan is not None, "first preparation has no E0 slot", key)
                        if plan and not _has_source(plan):
                            expected = a.resolved_value(plan)
                            p.require((prepared.record.contract, prepared.record.category, prepared.record.content,
                                       prepared.record.references, prepared.parents) ==
                                      (expected.contract, expected.category, expected.content,
                                       expected.references, expected.parents), "first preparation disagrees with E0 plan", key)
                            p.require(prepared.record.at == (plan.at or a.s.core.h.reading),
                                      "first preparation s differs from E0/actual generation reading", key)
                        elif plan:
                            p.gap("facts")
                    else:
                        p.gap("receipt_wire")
                        # Receipt creation happens at Accept, potentially before
                        # this PrepareReceipt. EP/EH need to identify that event;
                        # the window's RecordPlan.at is not independent evidence.
                        p.gap("facts")
                    p.require(prepared.payload == _encode(prepared.record), "first preparation payload differs from record", key)
                if slot.completed or slot.entry_confirmed:
                    p.require(slot.prepared is not None and b.present(slot.prepared.point),
                              "window claims saved/confirmed without matching C/E bytes/header/CID", key)
                    p.gap("seal")
                    p.gap("facts")
            for key, old in a.slots.items():
                if old.prepared and (key not in b.slots or b.slots[key].prepared is None):
                    p.require(b.present(old.prepared.point), "preparation deleted before matching C/E", key)
                    p.gap("facts")
        elif row == "INV-5.a":
            for key, slot in b.slots.items():
                old = a.slots.get(key)
                if slot.prepared and (old is None or old.prepared is None):
                    if not any(r.unit.id == key[0] for r in b.p.receipts):
                        _reference_check(p, a, slot.prepared.record)
            for point in b.entries.keys() - a.entries.keys():
                record = b.entries[point].header.record
                if not record.contract.name in {name for kind in RECEIPT_TYPES for name, _ in receipt_contracts(kind)}:
                    _reference_check(p, a, record)
        elif row == "INV-5.b":
            if op in ("ClaimStart", "EnterWorker"):
                wid = target[0] if target else None
                if op == "EnterWorker":
                    wrapper = next((w for w in a.s.core.wrappers if w.id == wid), None)
                    wid = wrapper.work if wrapper else wid
                descriptor = a.descriptors.get(wid)
                p.require(descriptor is not None, "started work lacks independent expected descriptor", wid)
                if descriptor:
                    p.require(_ready_refs(a, descriptor), "start/entry before all required Points were stored", wid)
                    p.gap("references")
                    p.gap("seal")
        elif row == "INV-5.c":
            self._state(row, p, b, ())
        elif row in ("INV-6.b", "INV-6.c"):
            self._state(row, p, b, ())
        elif row == "INV-7.a":
            self._state(row, p, b, ())
        elif row == "INV-7.b":
            if op in ("PublishUnit", "Recognize", "ClaimStart", "EnterWorker", "Acquire", "Adopt", "WorkerStep"):
                p.gap("references")
                p.gap("facts")
                # Enforce role declarations at the operation boundary. The
                # missing validated report mapping prevents full Clash closure.
                for uid in b.units.keys() - a.units.keys():
                    for slot in b.units[uid].slots:
                        for ref in slot.plan.references:
                            rules = [r for r, _ in b.references(slot.plan)
                                     if r.path_id == ref.path_id and r.path == ref.path]
                            p.require(bool(rules) and any((r.role, r.use) == (ref.role, ref.use) for r in rules),
                                      "new use reclassified a declared reference role", (uid, ref.path))
        elif row == "INV-7.c":
            _persist(p, a.s.core.e, b.s.core.e, lambda e: e.point, "late input changed/deleted committed record")
            _persist(p, a.s.core.c, b.s.core.c, lambda body: body.seal, "late input changed/deleted committed body")
            for wid, old in a.work.items():
                p.require(wid in b.work and b.work[wid].descriptor == old.descriptor,
                          "late input changed/deleted frozen work view", wid)
            for uid, old in a.units.items():
                new = b.units.get(uid)
                if new:
                    p.require(new.issued_view == old.issued_view and
                              tuple(s.plan for s in new.slots) == tuple(s.plan for s in old.slots),
                              "late input changed issued root/plan", uid)
        elif row == "INV-8.a":
            self._state(row, p, b, ())
            for wid, old in a.work.items():
                p.require(wid in b.work and b.work[wid].descriptor.numerical_view == old.descriptor.numerical_view,
                          "numerical root changed during work lifetime", wid)
        elif row == "INV-8.b":
            for runner in b.s.core.runners:
                if runner not in a.s.core.runners:
                    descriptor = a.descriptors.get(runner.work)
                    p.require(descriptor is not None, "actual input read has no independent expected work", runner.work)
                    if descriptor:
                        p.require(runner.numerical_input == a.resolved_value(descriptor.numerical_view),
                                  "actual numerical input differs from fixed expected input", runner.work)
                        if runner.descriptor_read is None:
                            p.gap("Runners.descriptor_read: actual read was not supplied")
                        else:
                            # REF-5 permits observing resolved Points. Compare
                            # against the SAME slot, never a refreshed/current root.
                            p.require(a.resolved_value(runner.descriptor_read) == a.resolved_value(descriptor),
                                      "actual descriptor read differs from E0 after same-slot resolution", runner.work)
                        for ref, point in runner.reference_read:
                            p.require(a.resolve(ref) == point, "actual reference read resolves a different slot", (runner.work, ref))
            if a.s.evidence.ew != b.s.evidence.ew:
                p.gap("facts")
        elif row in ("INV-9.a", "INV-9.b"):
            self._state(row, p, b, ())
        elif row == "INV-10.b":
            reduced = any(dict(b.work[wid].held).get(resource, 0) < quantity
                          for wid, work in a.work.items() if wid in b.work
                          for resource, quantity in work.held)
            if op == "Release" or reduced:
                p.gap("facts")
                wid = target[0] if target else None
                old = a.work.get(wid)
                if old and old.released:
                    p.require(a.p == b.p, "second release changes custody", wid)
                # A prior window stopped/released bit is not a Stop witness.
                if not a.s.evidence.ew.events:
                    p.require(False, "release has no actual reservation or stop history", wid)
        elif row == "INV-12.a":
            self._state(row, p, b, ())
        elif row == "INV-13.a":
            self._state(row, p, b, ())
        elif row == "INV-14.a":
            self._state(row, p, b, ())
        elif row == "INV-14.b":
            if op in ("PublishUnit", "ClaimStart", "Launch", "EnterWorker"):
                old_draws = {w.descriptor.args for w in a.p.work if w.descriptor.stage == "D"}
                for wid in b.work.keys() - a.work.keys():
                    d = b.work[wid].descriptor
                    if d.stage == "D":
                        p.require(d.args not in old_draws, "same full Draw request republished under another WorkId", wid)
                if old_draws:
                    p.gap("facts")
                    p.gap("RIGHT-DRAW: id projection/refinement bindings not declared")
        elif row in ("INV-15.a", "INV-15.b"):
            self._state(row, p, b, ())
            if row == "INV-15.b":
                for wid, old in a.work.items():
                    if old.knowledge is not None:
                        new = b.work.get(wid)
                        p.require(new is not None and (new.first, new.knowledge) == (old.first, old.knowledge),
                                  "late notice rewrote the first logical terminal", wid)
        elif row == "INV-16.a":
            self._state(row, p, b, ())
        elif row == "INV-16.b":
            for uid in b.units.keys() - a.units.keys():
                unit = b.units[uid]
                if unit.obligation_id in ("O-10", "O-11", "O-12"):
                    _plan_check(p, b, unit)
                    p.gap("artifact")
            for runner in b.s.core.runners:
                desc = b.descriptors.get(runner.work)
                if desc and desc.stage in ("Ep", "D", "Ee"):
                    p.require(runner.numerical_input == a.resolved_value(desc.numerical_view),
                              "evaluation used a different fixed numerical input", runner.work)
                    p.gap("artifact")
        else:
            raise AssertionError(f"no step predicate for {row}")

    def _conditions(self, p, x, row):
        contract, trace = getattr(x.e0, "observation_contract", None), x.s.evidence.observation_trace
        if not isinstance(contract, ObservationE0) or not isinstance(trace, ObservationTrace):
            p.gap("completion")
            return
        if not hasattr(x, "condition_evaluation"):
            x.condition_evaluation = evaluate_condition_custody(contract, trace, x.s)
        result = x.condition_evaluation
        for failure in result.boundary.violations:
            self._boundary_failures.setdefault((failure.path, failure.message), failure)
            self._connections[row].add("約束違反")
        for clause in result.clauses:
            if clause.row == row:
                p.require(clause.satisfied, clause.message, clause.target)
        for affected, reason in result.limitations:
            if affected == row:
                p.gap(reason)

    def _excuse(self, p, x, work, excuse, enabled):
        if excuse.obligation_id == 'O-G':
            # M3 residual purposes have their own identity and independent birth.
            # No reason string supplied by the window serves as a proof.
            self._conditions(p, x, 'INV-2.g')
            return
        p.require(excuse.obligation_id in OBLIGATION_TYPES, "excuse has undeclared obligation", excuse.obligation_id)
        p.require(bool(excuse.completion_conditions), "excuse has no named completion target", work.descriptor.work_id)
        for completion in excuse.completion_conditions:
            p.require(".save" not in completion, "unfinished reason illegally exempts storage", completion)
            oid = excuse.obligation_id.replace(".a", "a").replace(".b", "b").replace("O-", "C-O")
            p.require(completion.startswith(oid + "."), "reason exempts another obligation", completion)
            if excuse.reason_id == "B-STOP":
                p.require(completion.startswith("C-O14.stop"), "stop reason leaked to another completion", completion)
            elif excuse.reason_id in ("B-WINDOW", "B-STORE", "B-HOST"):
                # These change operation preconditions, never settle an O.
                p.gap("completion")
        rid = excuse.reason_id
        if rid == "B-STORE":
            p.gap("facts")  # witness must specify WHICH put/read/add stage
        elif rid == "B-WINDOW":
            p.gap("completion")  # needs the owner of the named operation
        elif rid == "B-POINT":
            needed = set(_points(work.descriptor))
            p.require(any(x.resolve(r) is None for r in needed), "claimed missing Point is not missing", work.descriptor.work_id)
        elif rid == "B-MEANING":
            p.gap("references")
        elif rid == "B-RESOURCE":
            trace = x.s.evidence.observation_trace
            if isinstance(trace, ObservationTrace):
                held, _, entered, uncertain, ended = actual_start_history(trace)
                wid = work.descriptor.work_id
                occupation = Counter()
                for resources in held.values():
                    occupation.update(dict(resources))
                desc = x.descriptors.get(wid)
                unreserved = not any(k.work == wid for k in held) and wid not in entered | uncertain | ended
                shortage = desc is not None and any(n > dict(x.e0.allocation).get(a, 0) - occupation[a] for a, n in desc.need)
                p.require(unreserved and shortage, "B-RESOURCE lacks actual START-0 resource shortage", wid)
                for c in x.p.conditions:
                    if c.key.obligation == excuse.obligation_id and c.key.obligation_key == excuse.obligation_key and c.key.kind == "run":
                        p.require(c.key in c.unmet, "B-RESOURCE wait was used to settle the run condition", c.key)
            else:
                p.gap("facts")
        elif rid in ("B-STOP", "B-REPORT", "B-FIRST"):
            p.gap("facts")
        elif rid == "B-CONFLICT":
            p.gap("references")
        elif rid == "B-CHOICE":
            p.gap("completion")
        elif rid != "B-HOST":
            p.require(False, "undeclared unfinished reason", rid)
        p.gap("completion")

    def _completed(self, p, x):
        counts = Counter()
        for point, record in x.records:
            if record.contract.name != "computation_completed":
                continue
            body = record.content
            q, r = _get(body, "request"), _get(body, "result")
            proofs = _get(body, "proofs", frozenset())
            counts[q] += 1
            result = x.record(r)
            p.require(x.record(q) is not None and result is not None, "completed lacks corresponding Q/R", point)
            if result:
                p.require(_get(result.content, "request") == q, "completed R belongs to another Q", point)
            p.require(bool(proofs), "completed contains no proofs", point)
            for ref in proofs:
                proof = x.record(ref)
                p.require(proof is not None and (_get(proof.content, "request"), _get(proof.content, "result")) == (q, r),
                          "completed proof belongs to another Q/R", ref)
            for field in ("started_clock", "finished_clock"):
                clock = _get(body, field)
                if x.declaration_resolver is None:
                    p.gap("約束の未接続: Cq Saved clocks need the actual EL trace")
                else:
                    try:
                        completed_clock_reading(x.declaration_resolver.contract,
                                                x.declaration_resolver.trace, clock, q, field)
                    except UnresolvedDeclaration as error:
                        p.gap("約束の未接続: " + str(error))
                    except ValueError as error:
                        p.require(False, str(error), (point, field))
                # PATH-COMPLETE (1031,1084): E0 Source -> actual EW/EH generation,
                # not equality with a clock selected by its reading alone.
            p.gap("facts")  # matching values cannot establish the generator
            p.gap("seal")
        for q, count in counts.items():
            p.require(count <= 1, "more than one completed for a logical request", q)

    def _verification(self, p, x):
        ea = x.s.evidence.ea
        for acquisition in ea.acquisitions:
            intent = next((i for i in x.e0.acquisitions if i.id == acquisition.intent), None)
            p.require(intent is not None, "acquisition lacks E0 intent", acquisition.intent)
            if intent:
                p.require(x.resolve(intent.reader) == acquisition.reader and
                          {x.resolve(t) for t in intent.targets} == set(acquisition.targets),
                          "actual acquisition differs from intended reader/targets", intent.id)
                p.require({x.resolve(t) for t in intent.required_ancestors} <= acquisition.ancestors,
                          "acquisition lacks required actual ancestors", intent.id)
            p.require(set(dict(acquisition.contents)) == set(acquisition.targets), "acquisition contents omit target bytes", acquisition.intent)
            for point, payload in acquisition.contents:
                entry = x.entries.get(point)
                body = x.bodies.get(entry.header.seal) if entry else None
                p.require(body is not None and body.payload == payload, "acquired bytes differ from actual stored target", point)
        for wid, reply in ea.replies:
            call = next((c for c in ea.calls if c.work == wid), None)
            p.require(call is not None, "verification reply lacks actual call", wid)
            if call:
                p.require((reply.target, reply.numerical_view, reply.check_view) ==
                          (call.target, call.input_read, call.check_view), "verification reply changed call target/input/view", wid)
            if reply.certificate is not None:
                p.require((wid, reply.certificate) in ea.issued, "certificate was not independently issued", wid)
                cert = reply.certificate
                for field in ("target", "reader", "target_contents", "numerical_view", "evidence_closure", "check_view", "registry", "checker"):
                    p.require(_get(cert, field) == _get(reply, field), "certificate differs from actual reply binding", (wid, field))
        for _, record in x.records:
            if record.contract.name == "sui.fb.verification_result":
                p.gap("receipt_wire")  # V -> VerificationReply field mapping
            if record.contract.name == "knowledge_adopted":
                p.gap("adoption")
        if ea.adoptions or ea.adoption_plans:
            p.gap("adoption")
        p.gap("seal")

    def _intervals(self, p, x):
        for request in x.s.evidence.ei.requests:
            p.require(request in x.e0.intervals, "actual interval request differs from E0", request.id)
            cells = interval_atoms(request.interval, x.e0.endpoints)
            p.require(cells is not None and {(c.start, c.end) for c in request.cells} == cells,
                      "interval cell partition loses endpoints/closure", request.id)
        for fact in x.s.evidence.ei.events:
            request = next((k for k in x.e0.intervals if k.id == fact.interval_request), None)
            p.require(request is not None, "interval fact has no corresponding request", fact.interval_request)
            if request:
                p.require(fact.route_epoch == request.route_epoch, "interval fact uses a different route epoch", request.id)
                p.require(fact.cells <= request.cells, "interval fact extends outside requested cells", request.id)
        # Report storage is raw. Unsupported/false claims may be stored; only
        # binding/certification checks may reject their meaning (PATH-RECEIPT).
        if x.e0.intervals or x.s.evidence.ei.events:
            p.gap("support")

    def on_relation(self, observation):
        left, right = observation.left, observation.right
        a, b = Snapshot(left.state, left.e0), Snapshot(right.state, right.e0)
        for row in ("INV-11.c", "INV-13.b"):
            self.observations[row] += 1
            p = Probe(self, row, ("relation", left.index, right.index))
            if _receipt_projection(a) != _receipt_projection(b):
                continue
            if row == "INV-13.b":
                # Exactly an initial-present/absent pair; no self-pair evidence.
                if (a.e0.initial is None) == (b.e0.initial is None):
                    continue
                if replace(a.e0, initial=None) != replace(b.e0, initial=None):
                    p.gap("initial-pair: declarations other than initial differ")
                    continue
                p.require(a.s.core.h.interval_requests == b.s.core.h.interval_requests
                          and a.s.evidence.ei.requests == b.s.evidence.ei.requests,
                          "initial changed measurement/interval undertaking")
            p.require(_receipt_services(a, left.enabled) == _receipt_services(b, right.enabled),
                      "equal receipt projection has unequal service operations")
            if row == "INV-13.b":
                p.gap("support")

    def on_graph(self, observation):
        self.complete = observation.complete and not observation.excluded_by_cut
        groups = {}
        for i, state in enumerate(observation.states):
            x = self._snapshot(i, state, observation.e0)
            projection = _receipt_projection(x)
            obs = StateObservation(i, state, observation.e0, observation.enabled[i], ())
            if projection in groups:
                self.on_relation(RelationObservation(groups[projection], obs, "same_receipt_projection"))
            else:
                groups[projection] = obs
        self._progress(observation)
        if not observation.complete:
            for c in CONDITION_IDS:
                self.limits[c].add("exploration incomplete: frontier is not a dead end")
        if observation.excluded_by_cut:
            for c in CONDITION_IDS:
                self.limits[c].add("Cut: excluded operations remain untested, not discharged")

    def _progress(self, graph):
        for row in ("L-RECEIPT", "L-DERIVE"):
            self.observations[row] += 1
        rp = Probe(self, "L-RECEIPT", ("graph",))
        dp = Probe(self, "L-DERIVE", ("graph",))
        if not graph.complete or graph.excluded_by_cut:
            rp.gap("path check not run: incomplete graph or Cut edges")
            dp.gap("path check not run: incomplete graph or Cut edges")
            return
        snapshots = [self._snapshot(i, s, graph.e0) for i, s in enumerate(graph.states)]
        enabled = tuple(frozenset((a.operation, *a.target) for a in actions if a.operation in RECEIPT_FAIR)
                        for actions in graph.enabled)
        edges = tuple((e.source, e.target, (e.action.operation, *e.action.target)) for e in graph.edges)
        # L-ENV eventual normality/capability is tested independently of Enabled.
        normal = {i for i, x in enumerate(snapshots) if
                  x.s.controls.normal_window and x.s.controls.normal_host and
                  x.s.controls.body_put and x.s.controls.body_read and
                  x.s.controls.entry_add and x.s.controls.entry_read}
        originals = {e for x in snapshots for e in x.s.evidence.eh.originals}
        for envelope in originals:
            pending = {i for i in normal if snapshots[i].originals.get(envelope.key) == envelope
                       and not snapshots[i].receipt_materialized(envelope)}
            if pending:
                rp.require(not progress_counterexamples(pending, edges, enabled, graph.frontier),
                           "fair recurrent/dead-end execution leaves the same receipt unmaterialized", envelope.key)
        rp.gap("seal")
        rp.gap("receipt_wire")
        rp.gap("facts")  # actual I/O outcomes still need the EP tag contract
        if graph.e0.derivations:
            dp.gap("derivation")
        # N/P graph algorithm is executable separately, but the current E0
        # adapter cannot establish Match/Ready/Discharge. Do NOT substitute the
        # window's operation set or root inclusion for any of these predicates.
        dp.gap("L-DERIVE N/P connection: typed Matchδ/ReadyN/Dischargeδ observations unavailable")

    def report(self):
        rows = []
        for contract in ROWS:
            cid = contract.condition_id
            limits = set(self.limits[cid])
            if contract.implementation != "implemented":
                limits.add(contract.implementation)
            if not self.observations[cid]:
                limits.add("not_run")
            if not self.reached[cid]:
                limits.add("target_not_reached")
            violations = tuple(self.failures[cid].values())
            # A specified discriminator is not a completed independent test.
            classification = "違反" if violations else "違反なし・識別力未確認"
            connections = self._connections[cid]
            connection = ("約束違反" if "約束違反" in connections else
                          "約束の未接続" if not connections or "約束の未接続" in connections else
                          "約束接続・部分判定")
            if connection != "約束接続・部分判定":
                limits.add(connection)
            rows.append(RowResult(cid, contract.identification, classification,
                                  self.observations[cid], self.reached[cid], violations, tuple(sorted(limits)), connection))
        return CheckReport(tuple(rows), tuple((h, "未点検") for h in HUMAN_IDS), self.complete,
                           tuple(self._boundary_failures.values()), tuple(sorted(self._unconnected_observations)))


def check_exploration(scenario, graph):
    """Offline adapter; every vertex/edge has exactly the same row dispatch."""
    checker = Checker()
    for i, state in enumerate(graph.states):
        checker.on_state(StateObservation(i, state, scenario.e0, graph.enabled[i], ()))
    for edge in graph.edges:
        checker.on_step(StepObservation(edge.source, edge.target, graph.states[edge.source],
                                       graph.states[edge.target], scenario.e0, edge.action,
                                       edge.actual_events, edge.result, (), ()))
    checker.on_graph(GraphObservation(graph.states, graph.edges, graph.enabled, scenario.e0,
                                      graph.complete, graph.frontier, graph.omitted))
    if graph.untested:
        checker.complete = False
        for cid in CONDITION_IDS:
            checker.limits[cid].update("scenario untested: " + t for t in graph.untested)
    return checker.report()


def derive_progress(unpublished: Iterable[int], ready: Iterable[int], pending: Iterable[int],
                    discharged: Iterable[int], edges: GraphEdges, full_enabled: EnabledByState,
                    *, environment_ready: Iterable[int], complete: bool = True,
                    frontier: Iterable[int] = ()) -> dict[str, tuple[frozenset[int], ...]] | None:
    """Paper L-DERIVE N/P formula over independently established frozen sets.

    Public SC-19-N1..N4 (1451-1469) entry for ONE fixed obligation o. Each set
    contains the state IDs where its independently established predicate holds:
    unpublished(o), ReadyN(o), pending P(o), Discharge_delta(o), and P's storage
    environment premise. ReadyN must not be inferred from offered operations.
    StableN is computed temporally by restricting recurrent states to ready;
    it is not a window-supplied bool. N4 can therefore detect hidden Publish.

    edges are the chosen candidate edges; full_enabled is from the COMPLETE
    base graph, retaining omitted exits and full target-specific action labels.
    Return {'N': components, 'P': components}, or None for incomplete/frontier.
    Abstract positive/negative candidates test the formula only: negative input
    is not a correct-window pass, and neither kind establishes real reachability
    or independently confirmed identification. For a real model, derive the
    predicates from E0/EH/EL, not mutable ready/Saved flags (1467).
    """
    if not complete or frozenset(frontier):
        return None
    n = set(unpublished) & set(ready)
    p = (set(pending) - set(discharged)) & set(environment_ready)
    return {"N": progress_counterexamples(n, edges, full_enabled),
            "P": progress_counterexamples(p, edges, full_enabled)}


# Verbatim six columns and formula, spec v0.11:839-883. These declarations
# are frozen here; execution never rereads the spec or asks the window.
_PAPER_ROWS = [
  [
    839,
    [
      "INV-1.a〔F〕S:273–274,384；全封筒",
      "EHの全Post済みe",
      "状態・前後",
      "Postから保存まで、毎状態",
      "EH、EL→4.a",
      "なし",
      "`Post(e) ∧ ¬SavedReceipt(e) ⇒ H保持(e) ∨ P.receipts保持(e)`。Hが手放す歩ではPへの引受けまたは保存を要する"
    ]
  ],
  [
    840,
    [
      "INV-1.b〔F〕S:297,319,384；再受付",
      "同じeの全提示・全受付",
      "状態・前後",
      "最初の原本から照合情報の寿命全体",
      "EH、EP→4.c",
      "なし",
      "同番号なら型・run・全内容・r・receipt_seq・受信記録計画が等しい時だけ同じ受付を返す。不一致なら成功を返さず原本不変"
    ]
  ],
  [
    841,
    [
      "INV-1.c〔F〕S:319,384；受信の個数",
      "全eと対応する記録の集合",
      "状態",
      "毎状態、EL",
      "EH、EL→4/5",
      "保存途中だけ未完可",
      "一般封筒は受信記録計画が1つ。`e1≠e2 ⇒ receiptId(e1)≠receiptId(e2)`。Bootの組は宣言された各slotが各1つ"
    ]
  ],
  [
    842,
    [
      "INV-2.a〔F〕S:385；O-01〜14",
      "E0/EH/EW/ELから生じる全oと、実際の全約束",
      "状態・前後",
      "発生から表の解消まで。削除も対象",
      "E0、EH/EW、EL→4/5、O表",
      "待ちでも所有は免除なし",
      "`Required(o) ∧ ¬Settled(o) ⇒ ResponsibleOwner(o)`。所有の移行は同じ歩で次の持ち主成立。受信の所有は1.aも満たす"
    ]
  ],
  [
    843,
    [
      "INV-2.b〔F〕S:298,385；全Publish",
      "全実際のPublishと、規範上の発行可能計画",
      "前後",
      "Publish直後。後続の行の寿命全体",
      "EUとE0/EH/EW/EL。参照は5",
      "なし",
      "`Publish(u) ⇒ PlannedRecords(u)=AllowedRecords(u) ∧ PromisedWorks(u)=AllowedWorks(u)`。全wの行が同時に存在し、記述・鍵が対応する"
    ]
  ],
  [
    844,
    [
      "INV-2.c〔F・差替え〕S:284,333,354–369；終わりと後続の引継ぎ",
      "全仕事の終わり、必要なT、種類別の記録、元の目的の未完責務。未作成・削除されたものも含む",
      "状態・前後",
      "返答の処理義務発生から、各保存・引継ぎの解消まで毎状態と全遷移",
      "EWの実返答、EHの最初の通知、EL、INV-4/5/15、終わりの表、O-09.a/b",
      "待ちは元の目的についてだけ。T等の保存義務を免除しない",
      "`CloseSave(o) ⇒ ∀p∈RequiredEndRecords(o): Saved(p)`。必要なTを明示的に含む。Wvの採るべきInsufficient返答ではTとV(Insufficient)の保存を要する。`HandoffPurpose(o,o') ⇒ 同じ目的・過程・ρ・対象と対応する未完理由 ∧ Owner(o')`。引継ぎは保存済みの代用にならず、元の目的の達成とも数えない。全処理終了には必要な保存と後続の処理/引継ぎをともに要する"
    ]
  ],
  [
    845,
    [
      "INV-2.d〔F・差替え〕S:235,250,298–302,325；要求導出",
      "δとCutから生じる全O-03のo、および対応u/q",
      "操作有効・状態",
      "N/P/Sを毎状態で区別。Nは発行直前のXuse、Pは固定済みuと実保存段",
      "E0のδ、EH、EL、EUとの照合、INV-4/5/7/8、WIN-PRE/SAVE-PRE",
      "Nは対象に結んだ証拠・許可・食い違いの待ち。Pは当該保存段の前提不足だけ",
      "Nで`ReadyN(o,s) ⇒ Enabled(PublishMatching(o))`。Pでは対応uを保持し、`SAVE-PRE(u,slot,s) ⇒ Enabled(当該slotの次の保存操作)`。NormalWindowや必要な能力がない時に有効性を要求しない。Sによる解消は`Dischargeδ(o,q)`を要する。待ちをSに変更しない"
    ]
  ],
  [
    846,
    [
      "INV-2.e〔F・新設、v0.10 で段ごとに〕S:282,303,385,393,405；開始操作の提供",
      "本来存在すべき全未開始w。別の仕事のHung、欠けた行、操作の欠落も対象",
      "操作有効",
      "毎状態。現在有効な許可・割り当てと独立した占有・EW の段を使用",
      "E0の仕事記述/資源/割り当て、EL→INV-4/5/7、EW→INV-3/10、EU→INV-2.b",
      "実行が選ばれないことと、操作を隠すことを分ける。別仕事のHungだけでは免除不可",
      "段ごとに要求する操作を固定する: `StartReady(w,s) ∧ Stage=確保前 ∧ Fit(w,s) ⇒ Enabled(ClaimStart(w))` (ここでは Held=0) / `StartReady ∧ Stage=確保済みの起動待ち ⇒ Enabled(Launch(w))` (ClaimStart を再び要求しない) / `StartReady ∧ Stage=未開始を確かめた後の再試行 ⇒ Enabled(Launch(w))` (既存の札と占有を使う。新規の確保を要求しない) / `StartReady(w,s) ∧ Stage=起動済み・入場前 ⇒ Enabled(EnterWorker(w))` (StartReady の「担当の正常」は EnterWorker を行う係 (起動の包み) について判定する。Launch の後・入場の前に上位の食い違いが保存されれば INV-7.b で StartReady が偽になり、未使用の札と包みが残っていても新しい入場は止める。Codex `sui-fb-slip` 6 通目 FBC6-01)。SC-14の席2でDの全前提と空席が揃うのにClaimStart(D)だけがない状態は違反。通常の ClaimStart の直後に再び ClaimStart を要求しない。これはどの段でも操作の選択・完了を要求する公平性ではない (出どころ: Codex `sui-fb-slip` 5 通目 FBC5-01 の指示で Claude が書いた)"
    ]
  ],
  [
    847,
    [
      "INV-2.f〔F・新設〕S:385,393,395,405および未完理由の契約；理由の正当性と効力",
      "全未完義務について、実際に使った待ち理由・完了免除とその対象",
      "状態・前後",
      "理由を採用する各時点と、未完を許す各状態。理由の対象に応じた現在の状態または固定像",
      "E0/EH/EW/ELから理由を再計算。INV-2.a/e、INV-4/5/7/10/11/12/15",
      "免除先は名指した義務の完了条件だけ。所有、T保存、固定値、参照の安全、受信保存へ伝播させない",
      "`UseExcuse(o,b,J) ⇒ Witness(o,b) ∧ J⊆AllowedCompletionConditions(o,b)`。資源待ちなら`∃a∈RequiredResources(w): max(Need(w,a)−Held(w,a),0)>Free(a,s)` (新規の確保の待ちに限る。保持済みの占有を持つ開始前の再試行を資源不足にしない、FBC4-01)を独立に確認。食い違い待ちなら当該結論使用の依存先にConflictが必要。証拠待ちなら当該用途・像で必要なPoint/契約等が実際に不足。報告待ちなら対応仕事と未処理/未受信の報告責務が存在。停止未確認ならEWに停止確認がない。窓口・置き場待ちはWIN-PRE/SAVE-PREの該当条件が不成立。正当な理由でも別義務の完了免除には使わない"
    ]
  ],
  [
    848,
    [
      "INV-3.a〔F〕S:303–305,386；全仕事",
      "発生済みの全WorkId。消えた行も含む",
      "状態・前後",
      "仕事の引受けから遅着照合まで",
      "EWとE0、10",
      "なし",
      "`body_entries(w)≤1 ∧ consumed_start_token(w)≤1`。実際の入場は有効な同一札を要する"
    ]
  ],
  [
    849,
    [
      "INV-3.b〔F〕S:284,304,386；記述と再起動",
      "全wの各段・起動包み",
      "状態・前後",
      "行設置から全期間",
      "EU→2.b、EW、EP、8",
      "なし",
      "記述の全固定欄が初期記述と等しい。開始前と確かめた再試行だけ許す。開始不明・終わり確定後は同じwを再入場させない"
    ]
  ],
  [
    850,
    [
      "INV-3.c〔F〕S:386；占有の一回性",
      "全wの確保・解放履歴",
      "状態・前後",
      "全履歴",
      "EW、10.b",
      "なし",
      "同じ確保を重複計上せず、同じ占有の解放は高々1回。開始前の再試行が同じ確保を保持する場合も再確保として加算しない"
    ]
  ],
  [
    851,
    [
      "INV-4.a〔F〕S:300–302,387；保存整合",
      "全cid∈Eと参照するCの本文",
      "状態",
      "毎状態",
      "C/E実値、E0のseal/encode/hash定義",
      "なし",
      "`C[header.seal]`が存在し、`seal(payload,salt)=header.seal ∧ encode_header(record,seal,parents)=header ∧ hash(header)=cid`"
    ]
  ],
  [
    852,
    [
      "INV-4.b〔F〕S:299–302,387；全再試行",
      "全PreparedEntryと全再準備/保存/照合",
      "状態・前後",
      "初回準備から保存確認まで、後の同一書込みも対象",
      "EP→4.c、EL→4.a",
      "なし",
      "名前・s・本文bytes・本文内参照・親集合・salt・seal・header・CIDの各欄が初回準備と等しい"
    ]
  ],
  [
    853,
    [
      "INV-4.c〔F〕S:297–302；初回準備と確認",
      "全初回準備、保存成功扱い、準備の削除",
      "前後",
      "作成/確認/削除の各歩",
      "E0、EH/EW、EU→2.b、EL→4.a/5",
      "準備保持による待ちのみ",
      "初回準備は許された計画と一致。receiptのrはEH原本、sは実際の生成の読み。`ConfirmWrite/保存済扱い ⇒ C/Eとの全欄照合`"
    ]
  ],
  [
    854,
    [
      "INV-5.a〔F〕S:299,374,388；記録の参照",
      "全計画から準備/保存される記録の全型付きPoint",
      "前後",
      "PrepareOneと保存の直前",
      "EL→4、E0の型別参照一覧",
      "参照不足なら当該段を待つ",
      "`PrepareOne/Save(v) ⇒ ∀p∈BodyPoints(v): Saved(p)`。未解決PlanRefを実在Pointとして渡さない"
    ]
  ],
  [
    855,
    [
      "INV-5.b〔F〕S:282,303–304,388；仕事入力",
      "全約束wの必要なPointと許可",
      "前後",
      "ClaimStart・EnterWorkerの直前",
      "E0の仕事別参照、EL→4/5.a、EU→2.b",
      "当該依存・許可待ち",
      "`Claim/Enter(w) ⇒ 全必要Point保存済み ∧ 対応する許可が有効`。Q/R/G/PR/DFだけでなく記述の全必要参照を対象"
    ]
  ],
  [
    856,
    [
      "INV-5.c〔F〕S:374,388；親と因果",
      "全保存点の全親、参照グラフ",
      "状態・前後",
      "各追加時と毎状態",
      "EL→4、E0の許された出来事型",
      "なし",
      "全親が保存済みの許された出来事。結果/証明のPredictionを親にしない。因果グラフに循環なし"
    ]
  ],
  [
    857,
    [
      "INV-6.a〔F〕S:332,389；completed",
      "期待する全q、存在する全completed",
      "状態",
      "毎状態、当時の根",
      "EL→4/5、EW、O-07",
      "未完はO-07で保持",
      "`count(completed(q))≤1`。各CのQ・R・全P・Wr開始・Wp終わりが同じ論理要求に対応"
    ]
  ],
  [
    858,
    [
      "INV-6.b〔F〕S:313–338,389；同一性",
      "全論理鍵と有効報告、全処理/消費",
      "状態・前後",
      "各処理時の根と全履歴",
      "EH/EW/EL、E0比較欄；H-02",
      "証拠待ちは当該鍵だけ",
      "同じ鍵で意味の全欄が同値なら論理処理を増やさない。測定適用、仕事の終わり、くじ消費の各権利単位で回数≤1"
    ]
  ],
  [
    859,
    [
      "INV-6.c〔F〕S:315,334,389；区別すべき出来事",
      "全区間/MeasurementId/item_slot、全取得・採用意図",
      "状態・前後",
      "毎状態、各確定時",
      "EH/EA/EL、E0；H-02",
      "なし",
      "別slot・別の実際の取得意図・別読み手を内容一致だけで統合しない。測定の再配送と新しい測定を、rや受信件数で区別しない"
    ]
  ],
  [
    860,
    [
      "INV-7.a〔F・共通定義に合わせ差替え〕S:313–340,390；食い違い",
      "X内の全有効報告、同じ論理鍵の組、宣言済み排他単位を共有する異なる鍵の組",
      "状態・前後",
      "毎状態とX記録発行時。指定された固定像Xを使用",
      "EL→INV-4/5、E0の全比較欄と相互排他規則、H-02",
      "X保存待ちは使用の免除にしない",
      "`Conflict(X,k) ⇔ ∃c∈Clashes(X): k∈affected(c)`。X記録の発行にはその報告Point・規則・全比較内容の対応を要する。同値再配送だけ、またはUnknown＋値だけではXを作らない。同値の結果でも生成の読み等が異なる場合、および同sample_seq・異MeasurementIdの排他違反を落とさない"
    ]
  ],
  [
    861,
    [
      "INV-7.b〔F・差替え〕S:342–346,390,401；新しい結論使用",
      "全新規Publish/開始/認証使用/取得/採用のUseDepsと、その依存先に影響する排他単位。証拠参照も種類を検査",
      "前後",
      "新しい使用・確定直前のXuse。固定済み記録の保存再試行と区別",
      "更新したINV-7.a、EL→INV-4/5、E0の型付き依存関係、H-02",
      "当該結論使用の完了だけ止められる。Xや不足の記録、受信保存まで禁止しない",
      "`∃k∈UseDeps(v): Conflict(Xuse(v),k) ⇒ ¬PermitNewUse(v)`。食い違い・不足を記録するvが当該報告をEvidenceRefsとして指すだけなら、この禁止をその参照だけから適用しない。ただし証拠Pointの保存・内容一致・記録する食い違い/不足の事実は検査する。Wr/Wp/Ep/D等の上位の結論使用依存には禁止を伝える"
    ]
  ],
  [
    862,
    [
      "INV-7.c〔F〕S:343–344；後着",
      "既存の確定と、その後の報告追加",
      "前後",
      "確定時の根を保持",
      "EL、EP、8",
      "なし",
      "後着で既存記録と固定根を改変しない。古いX0の再読結果を変えない。新しい使用では新しい食い違いを検査"
    ]
  ],
  [
    863,
    [
      "INV-8.a〔F〕S:325,391；根の固定",
      "全qとそのWr/Wp/Wv、全評価仕事",
      "状態・前後",
      "要求確定から仕事の全寿命",
      "E0の本来の入力対応、EU→2.b、EL",
      "なし",
      "各段の数値入力像がXnum(q)と等しい。要求・入力・前の結果・方法/版の対応を全期間比較"
    ]
  ],
  [
    864,
    [
      "INV-8.b〔F〕S:279,391；実際に読む根",
      "EWの全本体入場・入力読取り",
      "前後",
      "各実読取り時",
      "EWと8.aの期待値",
      "なし",
      "`ActualNumericalInput(w)=ExpectedNumericalInput(q,stage)`。新しいReceivedを既存入力へ混入させない。認証証拠像の追加と数値入力変更を区別"
    ]
  ],
  [
    865,
    [
      "INV-9.a〔F〕S:335,359,366–371,392；認証返答・V・取得・採用",
      "全Vの発行/保存、全Adopted、対応する実認証呼出しと返答、実取得。Vまたは採用が存在する場合に、その対応元の欠落も検査",
      "前後・状態",
      "V発行時と採用確定直前。認証に使った固定像と、採用直前のXuseを区別。保存済みVも対応を保持",
      "EW/EAで独立に観測した認証の対象と返答、EL→INV-4/5、INV-7/8/15、H-03",
      "不足・拒否・Unknownは当該採用を禁止/保留する理由。成功の代用にはならない",
      "`Publish(V) ⇒ Vの返答内容=対応する実認証返答の正準内容`。比較するのはWorkId、Q/R/P/Cと全証明、ρ、対象bytes/digest、入力、根拠閉包、検査像、registry/checker版、返答の種類、結果・理由・不足対象・発行物との対応。`Adopted(d) ⇒ 実認証返答が当該対象について認証成功 ∧ Vも同じ成功内容 ∧ 当該対象に結んだ有効な発行済み認証物 ∧ dの対象との全対応一致 ∧ INV-15の終わりと整合`。さらに元の測定/R/全Pの実取得が当該ρによる採用以前の出来事であり、必要な実祖先を持つことを要する。呼出しが正常終了しただけ、対象が一致するだけ、Vのsuccess印だけでは認証成功としない"
    ]
  ],
  [
    866,
    [
      "INV-9.b〔F〕S:336,392；系列とStale",
      "全ρ、全採用計画、前の採用と結果",
      "状態・前後",
      "計画確定から保存までρごとの予約を保持",
      "EA/EL、Qの引数→8",
      "他のρへ待ちを波及させない",
      "新導出なら`Q.previous_result=result(current_adoption(ρ))`。不一致ならStaleでAdoptedなし。ρごとの未保存採用単位は高々1"
    ]
  ],
  [
    867,
    [
      "INV-10.a〔F〕S:284,393；容量",
      "全資源と全wの実際の確保・解放",
      "状態",
      "毎状態。削除された行の占有も含む",
      "EW、E0の容量/割当、3",
      "当該資源不足は開始完了だけ免除",
      "`占有=実確保−正当な解放`。各資源で`Σ占有≤有効割当≤capacity`。窓口のphaseの数だけで代用しない"
    ]
  ],
  [
    868,
    [
      "INV-10.b〔F〕S:284,393；解放",
      "全解放遷移",
      "前後",
      "各解放直前",
      "EWのStop/確かな未開始、3.c",
      "停止未確認なら占有保持",
      "`Release(w) ⇒ 停止確認または確かな未開始終了 ∧ 未解放`。Unknown・返答保存・Rebuild・遅着だけでは解放不可"
    ]
  ],
  [
    869,
    [
      "INV-11.a〔F〕S:394；受付",
      "全正常状態のHostEligibleなe",
      "操作有効",
      "初期と再建後を含む毎状態",
      "EH、環境の正常性/型、E0",
      "後方の封筒はホスト順待ちのみ",
      "`Normal ∧ WellFormed(e) ∧ Eligible(e) ∧ ¬Accepted(e) ⇒ Enabled(Accept(e))`。受付後は必要なHostAckも有効"
    ]
  ],
  [
    870,
    [
      "INV-11.b〔F〕S:299–302,394；受信保存",
      "全受付済みeと保存段",
      "操作有効",
      "毎状態、実C/Eと準備状態",
      "EP/EL→4、環境の能力",
      "置き場能力がない当該段だけ",
      "段階表の前提なら、その段のPrepare/PutBody/Confirm/AddEntryが有効。本文保存前のAddEntryを要求しない"
    ]
  ],
  [
    871,
    [
      "INV-11.c〔F〕S:394；計算からの独立",
      "受信関連状態が等しく計算関連状態だけ違う状態対",
      "状態間の関係",
      "全該当状態対、または同じガードの構造検査",
      "11.a/bの入力射影、E0；H-05",
      "なし",
      "受付/保存サービス操作の有効集合が等しい。操作のガードがFinish・証明完成・空席を参照しない"
    ]
  ],
  [
    872,
    [
      "INV-12.a〔F・差替え〕S:321–338,395；区間・報告・被覆",
      "全要求k、全報告、全認証被覆kind、その認証で使うXと証拠参照",
      "状態・前後",
      "報告結合/被覆認証時と毎状態。既存認証は当時のXで再照合",
      "X内のEL→INV-4/5、EIによる対応事実の照合、有限対応表、A-13〜15、H-04",
      "不足は当該区間・用途の使用だけ保留。原報告の保存と責務の保持は継続",
      "route/run/要求/slot/MeasurementId/sample_seq/端/開閉/適用/開始/生成/時計を比較。Frameと全Claimは`start≤end≤r`。Frameのactual_timeがUnavailableなら実測時刻を要する使用を許さない。Claimは完了窓条件と契約別生成条件を別々に満たす。`EvidenceRefs⊆VisibleSavedPoints(X)`かつ、被覆は同じXの認証済みSupportの和以下。後から増えたEIだけで古いXのSupportを拡大しない"
    ]
  ],
  [
    873,
    [
      "INV-12.b〔F〕S:395；未報告部分",
      "要求区間の全セル。報告なしも対象",
      "状態",
      "毎状態。待機状態も同じ",
      "E0/EI、O-04/13、2.a",
      "実在する報告責務による待ち可",
      "全セルに報告・責務・根拠付き不足/食い違いが対応。`NoReport`からGap・ゼロ測定・被覆を作らない"
    ]
  ],
  [
    874,
    [
      "INV-13.a〔F〕S:250,396；空の起動",
      "全bootstrap由来の計算仕事と入場履歴",
      "状態・前後",
      "全実行",
      "E0のinitial、EW、2.b",
      "なし",
      "`initial=None ⇒ bootstrap由来の計算仕事の発行/本体入場=0`。MeasureSegmentと受信は計算仕事に混ぜない"
    ]
  ],
  [
    875,
    [
      "INV-13.b〔F〕S:250,396；測定の独立",
      "同じ口/区間/受信でinitialだけ異なる対照",
      "状態間の関係",
      "初期と各対応状態",
      "E0/EI、11/12",
      "測定自身の理由だけ",
      "initialなしを理由に口・区間要求・受付・保存の責務や有効操作を消さない"
    ]
  ],
  [
    876,
    [
      "INV-14.a〔F〕S:327,397；Drawの権利",
      "全Draw要求。別WorkIdへの付け替えも合算",
      "状態・前後",
      "要求固定から全期間",
      "E0のDraw式、EW、EL、3/8",
      "報告待ちのみ",
      "要求のgenerator・stream_id・purpose・context_key・ordinalと法則等の宣言欄が固定。`Σbody_entries(w for same Draw request)≤1`"
    ]
  ],
  [
    877,
    [
      "INV-14.b〔F〕S:327,397；再抽選禁止",
      "Unknown/失敗/遅着後の全Draw開始",
      "前後",
      "各新規開始・計画",
      "14.a、15、EW",
      "不足は再抽選の許可にならない",
      "同じDraw要求を別WorkId/別札で再発行・再入場しない。同根精密化は同じDraw Pointと値を保持"
    ]
  ],
  [
    878,
    [
      "INV-15.a〔F〕S:296–297,327,398；最初の知らせ",
      "Wr/Wp/Wv/Ep/D/Eeの全終わりの知らせ",
      "状態・前後",
      "各終わりの確定直前",
      "EH→1、EL→4、順序表",
      "最初の受信未保存なら待つ",
      "`first(w)=argmin(r,receipt_seq)`。受付前方範囲が確定し、`SavedReceipt(first(w))`。本文のWorkId/要求/段/出どころが対応"
    ]
  ],
  [
    879,
    [
      "INV-15.b〔F〕S:333,398；種類の固定",
      "全T/R/PR/DF/DU/EVとその後続",
      "状態・前後",
      "最初の確定から全期間",
      "15.a、EW、終わりの表、7",
      "当該段の証拠待ち/食い違いのみ",
      "論理の終わりは最初の知らせの種類と一致し、後着で上書きしない。Unknownから成功記録を生成しない。Xは独立の証拠を要する"
    ]
  ],
  [
    880,
    [
      "INV-16.a〔F〕S:328–329,399；選ぶ",
      "全selection。存在すべき対応評価も対象",
      "前後・状態",
      "selection確定時と保存後",
      "EL、EW/EA、15、H-03",
      "NoDecision等はselectionなしで終了可",
      "`selection ⇒ 対応する保存済み評価の返答が認証されたSelected`。NoDecision/Unknown/Failure/不足からは生成しない"
    ]
  ],
  [
    881,
    [
      "INV-16.b〔F〕S:326–329,368–369；対象の対応",
      "評価要求・PR・artifact・problem・Draw・EV・selection",
      "前後",
      "準備/評価/選択の各確定時の根",
      "E0、EL、EW、4/5/7/8",
      "対応不足は当該段だけ待つ",
      "要求入力・処理/版・Xnum・artifact bytes/digest・problem_key・Drawのpurpose/context/Point/値が対応。別問題のPR/Draw/Selectedを流用しない"
    ]
  ],
  [
    882,
    [
      "L-RECEIPT〔F〕S:405,427；受信保存",
      "全正常Post済みeと全到達経路",
      "経路進行",
      "完全探索したグラフと環境前提",
      "EH、11、L-ENV/FAIR、操作札付き辺",
      "前提不成立は保証対象外と記録",
      "公平な未保存の無限実行または前提成立下の未保存行き止まりが存在すれば違反"
    ]
  ],
  [
    883,
    [
      "L-DERIVE〔F・差替え〕§2-4-10 (1) O-03・(2) L-DERIVE；要求生成と保存",
      "δとCutで固定した全oと対応する合法なu/q",
      "経路進行",
      "NとPを分け、上記の時間的前提の下で完全な探索グラフを検査",
      "INV-2.d、Matchδ/Dischargeδ、L-ENV、WIN-PRE/SAVE-PRE、操作札付き辺",
      "Nの正当な前提喪失は発行保証の対象外。ただし所有と理由の検査は継続。Pは保存前提に従う",
      "StableNと対象ごとの弱い公平性を満たす未発行の無限実行、または合法なPublish後に保存前提と公平性を満たす未保存の無限実行があれば違反。前提不成立・未実行・探索未完を反例なしと混同しない"
    ]
  ]
]


CONCRETE_IDENTIFICATION = frozenset((
    "INV-2.a", "INV-2.c", "INV-3.b", "INV-3.c", "INV-4.b", "INV-4.c",
    "INV-5.c", "INV-6.a", "INV-7.a", "INV-9.a", "INV-10.a", "L-RECEIPT", "L-DERIVE",
))

# Explicit read sets and correspondence keys. The exact six paper columns above
# remain attached to every row, including its individual exception/lifetime.
_READS = {
    "1": ("E0.postings", "EH.originals/accepts/acknowledgements", "H.queue", "P.receipts", "EP", "C/E"),
    "2": ("E0.plans/derivations/intervals/acquisitions", "EH/EW/EU/EL", "P.receipts/units/work", "Controls", "Enabled"),
    "3": ("E0.plans.works", "EW.events", "P.work.descriptor/resolutions/token/held", "Runners", "Wrappers"),
    "4": ("E0.plans", "EH/EW/EP", "P.receipts/units.slots.prepared", "Slot.completed/entry_confirmed (claims only)", "C/E"),
    "5": ("E0.field_roles/plans.works", "P.work.resolutions", "PreparedEntry.record.references", "C/E", "Action"),
    "6": ("E0.plans/acquisitions/adoptions", "EH/EW/EA", "C/E"),
    "7": ("E0.field_roles/comparisons/plans", "EH/EW", "C/E", "P.units.issued_view", "P.work.descriptor", "Action"),
    "8": ("E0.plans.works.numerical_view/args/method", "P.work.descriptor/resolutions", "Runners.numerical_input/descriptor_read/reference_read", "EA.calls", "EW"),
    "9": ("E0.acquisitions/adoptions/plans", "EA.acquisitions/calls/replies/issued/adoptions", "P.adoption_reservations", "C/E"),
    "10": ("E0.capacity/allocation/plans.works.need", "EW.events", "P.work.held/released (claims only)", "Action"),
    "11": ("E0.postings", "EH.originals/acknowledgements", "H.queue/reading", "P.receipts", "EP", "C/E", "Controls", "Enabled"),
    "12": ("E0.intervals/endpoints/support_contracts", "EI.requests/events", "H.interval_requests", "P.work", "C/E"),
    "13": ("E0.initial/plans/intervals", "P.work/units", "Runners", "EI.requests", "H.interval_requests", "receipt projection", "Enabled"),
    "14": ("E0.plans.works.args", "EW.events", "P.work.descriptor", "Runners", "Action"),
    "15": ("E0.plans.works", "EH.originals/generations", "P.receipts", "P.work.first/knowledge (claims only)", "EW", "C/E"),
    "16": ("E0.plans", "EW/EA", "P.units", "Runners.numerical_input", "C/E"),
    "L-RECEIPT": ("E0", "EH", "EP", "P.receipts", "C/E", "Controls", "Graph.states/edges/enabled/frontier/excluded_by_cut"),
    "L-DERIVE": ("E0.derivations/plans", "EH/EU/EL", "Controls", "Graph.states/edges/enabled/frontier/excluded_by_cut"),
}
_KEYS = {
    "1": ("run", "envelope_number", "receipt_slot"),
    "2": ("O-ID", "obligation_key", "completion_kind", "slot/work", "process", "reader", "purpose"),
    "3": ("WorkId", "undertaking", "token", "reservation"),
    "4": ("unit", "slot", "record.name", "seal", "CID"),
    "5": ("record_contract/version", "field_path", "use", "WorkId", "Point/PlanRef"),
    "6": ("Q", "WorkId", "Draw id", "transition_key", "reader", "intent", "MeasurementId", "item_slot"),
    "7": ("report family/logical key", "exclusion unit", "Xuse", "reference role/use"),
    "8": ("Q/EQ", "WorkId", "stage", "Xnum", "PlanRef"),
    "9": ("reader", "intent", "Q/R/all P/Cq", "verification work", "check_view", "registry/checker"),
    "10": ("resource", "WorkId", "reservation", "release"),
    "11": ("run", "envelope_number", "receipt_slot", "receipt projection"),
    "12": ("route/run", "k", "cell", "kind", "X", "MeasurementId", "item_slot"),
    "13": ("bootstrap", "work stage", "initial pair", "route/k/receipt"),
    "14": ("domain/generator/stream/purpose/context/ordinal", "all WorkIds"),
    "15": ("WorkId", "request", "stage", "r/receipt_seq", "first_receipt"),
    "16": ("EQ", "PR", "problem", "Draw", "EV", "selection", "artifact"),
    "L-RECEIPT": ("run/envelope", "operation/target/slot", "SCC"),
    "L-DERIVE": ("delta/version/process/reader/Received/purpose/trigger_slot", "N/P", "unit/slot", "SCC"),
}

_DEPENDENCIES = {
    "INV-1.a": ("INV-4.a",), "INV-1.b": ("INV-4.c",), "INV-1.c": ("INV-4.a", "INV-5.a"),
    "INV-2.a": ("INV-4.a", "INV-5.a"), "INV-2.b": ("INV-5.a",),
    "INV-2.c": ("INV-4.a", "INV-5.a", "INV-15.a", "INV-15.b"),
    "INV-2.d": ("INV-4.a", "INV-5.a", "INV-7.a", "INV-7.b", "INV-8.a"),
    "INV-2.e": ("INV-2.b", "INV-3.a", "INV-3.b", "INV-4.a", "INV-5.b", "INV-7.b", "INV-10.a"),
    "INV-2.f": ("INV-2.a", "INV-2.e", "INV-4.a", "INV-5.a", "INV-7.a", "INV-10.a", "INV-11.a", "INV-11.b", "INV-12.b", "INV-15.a"),
    "INV-3.a": ("INV-10.a",), "INV-3.b": ("INV-2.b", "INV-8.a"), "INV-3.c": ("INV-10.b",),
    "INV-4.a": (), "INV-4.b": ("INV-4.c", "INV-4.a"), "INV-4.c": ("INV-2.b", "INV-4.a", "INV-5.a"),
    "INV-5.a": ("INV-4.a",), "INV-5.b": ("INV-2.b", "INV-4.a", "INV-5.a"), "INV-5.c": ("INV-4.a",),
    "INV-6.a": ("INV-4.a", "INV-5.a"), "INV-6.b": (), "INV-6.c": (),
    "INV-7.a": ("INV-4.a", "INV-5.a"), "INV-7.b": ("INV-7.a", "INV-4.a", "INV-5.a"),
    "INV-7.c": ("INV-8.a",), "INV-8.a": ("INV-2.b",), "INV-8.b": ("INV-8.a",),
    "INV-9.a": ("INV-4.a", "INV-5.a", "INV-7.b", "INV-8.a", "INV-15.a", "INV-15.b"),
    "INV-9.b": ("INV-8.a",), "INV-10.a": ("INV-3.a", "INV-3.c"), "INV-10.b": ("INV-3.c",),
    "INV-11.a": (), "INV-11.b": ("INV-4.a", "INV-4.c"), "INV-11.c": ("INV-11.a", "INV-11.b"),
    "INV-12.a": ("INV-4.a", "INV-5.a"), "INV-12.b": ("INV-2.a",),
    "INV-13.a": ("INV-2.b",), "INV-13.b": ("INV-11.a", "INV-11.b", "INV-12.b"),
    "INV-14.a": ("INV-3.a", "INV-8.a"), "INV-14.b": ("INV-14.a", "INV-15.a", "INV-15.b"),
    "INV-15.a": ("INV-1.a", "INV-1.b", "INV-4.a"), "INV-15.b": ("INV-15.a", "INV-7.a"),
    "INV-16.a": ("INV-15.a", "INV-15.b"), "INV-16.b": ("INV-4.a", "INV-5.a", "INV-7.b", "INV-8.a"),
    "L-RECEIPT": ("INV-11.a", "INV-11.b"), "L-DERIVE": ("INV-2.d",),
}


def _build_rows():
    rows = []
    for cid, (line, columns) in zip(CONDITION_IDS[:-2], _PAPER_ROWS, strict=True):
        if not columns[0].startswith(cid + "〔"):
            raise ValueError("paper condition order drift")
        label = columns[2]
        kinds = set()
        if "状態間" in label:
            kinds.add(PropertyKind.RELATION)
        elif "状態" in label:
            kinds.add(PropertyKind.STATE)
        if "前後" in label:
            kinds.add(PropertyKind.STEP)
        if "操作有効" in label:
            kinds.add(PropertyKind.ENABLED)
        if "経路進行" in label:
            kinds.add(PropertyKind.PATH)
        family = cid.split("-")[1].split(".")[0] if cid.startswith("INV-") else cid
        rows.append(RowContract(
            condition_id=cid, scope=dict(SCOPE_UNIVERSE)[cid], population=columns[1],
            correspondence_keys=_KEYS[family], kinds=frozenset(kinds), timing=columns[3],
            root=columns[3] + "; E0 fixes the expected values; actual observations do not authorize them",
            lifetime=columns[3], readable_fields=_READS[family], comparisons=(columns[6],),
            evidence=(columns[4],), depends_on=_DEPENDENCIES[cid],
            unfinished_targets=() if columns[5] == "なし" else (columns[5],),
            permitted_completion_conditions=() if columns[5] == "なし" else (columns[5],),
            formula=columns[6], implementation="partial_observation_contract",
            identification="具体化済み" if cid in CONCRETE_IDENTIFICATION else "未具体化",
            paper_line=line, paper_columns=tuple(columns),
        ))
    for cid, population, formula in (
        ('INV-2.g', 'E0 Wg and every born O-G condition and original Qgen purpose',
         'Independent Required implies Direct, permitted Transfer, or matching real custody; D3 pG never Direct'),
        ('INV-16.c', 'E0 Qgen/Wg and every actual generation, CG and EQ; R10 remains unconnected',
         'Fixed whole request = actual read; first return = whole CG; Saved CG and usable evaluation inputs precede EQ/Ep'),
    ):
        columns = (cid, population, 'state and before/after', 'each state and publication/entry/storage edge',
                   'E0/EH/EW/EL/EU/EP/EA; original request and actual owner',
                   'individual O-G conditions and pG; gaps are unconnected', formula)
        rows.append(RowContract(cid, dict(SCOPE_UNIVERSE)[cid], population,
            ('Wg', 'Qgen', 'CG slot', 'EQ slot', 'CompletionKey', 'PurposePart'),
            frozenset((PropertyKind.STATE, PropertyKind.STEP)), columns[3],
            'E0 and the independent observation prefix at the relevant event',
            'from initial promise through all later states, including late shortage/conflict',
            ('E0.plans/descriptors', 'EH/EW/EL/EU/EP/EA', 'P.work', 'P.units', 'P.conditions'),
            (formula,), (columns[4],), ('INV-4.a', 'INV-5.a', 'INV-15.a'),
            ('O-G', 'pG', 'R10'), ('seven separate O-G conditions; Direct(pG)=False',), formula,
            'partial_observation_contract', '未具体化', 1961, columns))
    return tuple(rows)


ROWS = _build_rows()
PARTIAL = tuple(r.condition_id for r in ROWS if r.implementation != "implemented")


# ---------------------------------------------------------------------------
# Checker-owned observation contract, version 1. No fb_machine import/callback.
# This is the target for the ENVIRONMENT author, not a decoder of legacy Facts.
# Normative references throughout this section are to the v0.11 paper.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Paper:
    ids: tuple[str, ...]
    lines: tuple[int, int]


@dataclass(frozen=True, slots=True)
class GapPart:
    gap: str
    category: Literal["甲", "乙"]
    meaning: str
    paper: Paper


GAP_PARTS = (
    GapPart("seal", "甲", "seal/payload/salt, encoded header and CID must agree; define a MODEL codec explicitly",
            Paper(("INV-4.a", "SAVE-4..8"), (461, 462))),
    GapPart("receipt_wire", "甲", "full raw input, Observed fields, r/s and Boot's two slots; concrete model layout is A-RECEIPT",
            Paper(("I-1..3", "I-6", "I-8", "PATH-RECEIPT"), (457, 467))),
    GapPart("facts", "甲", "actual EH/EW/EP/EL/EU/EA/EI events, not copies of window flags",
            Paper(("EH", "EW", "EP", "EL", "EU", "EA", "EI"), (816, 835))),
    GapPart("derivation", "甲", "delta declaration/version, receipt eligibility, trigger/group/stage, root/input/previous bindings",
            Paper(("O-03", "Matchδ", "Dischargeδ"), (616, 620))),
    GapPart("derivation", "乙", "PATH-QOBS generation closure and bootstrap /2 numerical projection",
            Paper(("PATH-QOBS", "RIGHT-APPLY"), (1081, 1081))),
    GapPart("completion", "甲", "condition identity, independent occurrence, saved conclusions and preservation on handoff",
            Paper(("C-O01..14", "EndKnown", "RequiredEndRecords"), (1185, 1237))),
    GapPart("completion", "乙", "terminal and targeted-certificate concrete wire; logical fields remain expressible",
            Paper(("T", "PATH-LINK-ACQUISITION"), (769, 769))),
    GapPart("references", "甲", "explicit contract/path/use/operation roles; specified direct edges, parent existence/type/acyclicity",
            Paper(("E0-01..08", "REF-1..8", "PATH-*"), (997, 1094))),
    GapPart("references", "乙", "unlisted paths, /2 and artifact semantic closure, unspecified parent minima/extras",
            Paper(("PATH-QOBS", "PATH-ARTIFACT-*", "PATH-PARENTS"), (1081, 1096))),
    GapPart("apply", "甲", "finite declared input-to-transition relation and per reader/model/series consumption",
            Paper(("RIGHT-APPLY",), (1148, 1149))),
    GapPart("apply", "乙", "bootstrap /2 projection when unspecified; never derive it from the /1 rule",
            Paper(("RIGHT-APPLY",), (1149, 1149))),
    GapPart("adoption", "甲", "intent, reader, actual acquisitions, verification binding, previous adoption, ACTUAL ancestors",
            Paper(("PATH-ACQUIRE", "PATH-ADOPT", "RIGHT-ADOPT"), (1085, 1086))),
    GapPart("adoption", "乙", "targeted-certificate wire expansion is not implemented",
            Paper(("PATH-LINK-ACQUISITION",), (1093, 1093))),
    GapPart("support", "甲", "fixed X inputs, actual EI correspondence, cells/kind separation and coverage subset constraint",
            Paper(("Support", "CertifiedCoverage"), (723, 750))),
    GapPart("support", "乙", "kind/contract-specific generation meaning and complete Support closure not supplied by paper",
            Paper(("PATH-REPORT-EVIDENCE",), (1087, 1087))),
    GapPart("artifact", "甲", "actual issued/verified port values and work/input/compiler/reader/registry/output bindings; explicit direct paths",
            Paper(("PATH-ARTIFACT-INPUT", "PATH-ARTIFACT-DRAW", "PATH-ARTIFACT-NONPOINT"), (1089, 1092))),
    GapPart("artifact", "乙", "full semantic closure, other input branches/calls/claims and actual F-a certification",
            Paper(("PATH-ARTIFACT-*", "H-03"), (1089, 1096))),
)

# 紙に無い仮定: representational choices, NOT additional success premises.
OBSERVATION_ASSUMPTIONS = (
    ("A-RECEIPT-SELECTOR", "紙に無い仮定: a finite E0 alias selects a unique actual EH Post by delivery provenance, full Event, and optional run; it never predicts number/r/receipt_seq", (616, 620)),
    ("A-REFERENCE-PATH", "紙に無い仮定: model arrays are tuples; declared '*' paths expand to zero-based concrete indices in TypedReference, without implicit field discovery or unordered-set indexing", (1076, 1096)),
    ("A-CODEC", "紙に無い仮定: model-json-v1 and length-framed SHA256 seal below; not real F-a wire/cryptography", (427, 428)),
    ("A-RECEIPT", "紙に無い仮定: deterministic receipt names/slots, declared route/parents, and Object packing of Observed; both Boot slots retain the entire original Event", (457, 467)),
    ("A-TAGS", "紙に無い仮定: tag spellings, typed compound keys and transport version; absence is distinct from empty evidence", (816, 823)),
    ("A-IO", "紙に無い仮定: identical I/O facts may be quotiented in state; every occurrence remains on an edge; EW is never quotiented", (1309, 1316)),
    ("A-FINITE", "紙に無い仮定: scenario-authored finite tables bind concrete receipt/derivation/application/port instances; H-01 checks their origin, and missing rows stay unconnected", (816, 816)),
    ("A-ANCESTRY", "紙に無い仮定: actual causal DAG is transported as point/parents pairs separately from visible points and window ledger-parent claims", (1085, 1086)),
    ("A-SOURCE", "紙に無い仮定: finite Source projections are first_receipt, generation, outcome, acquisition, numerical_view, started_clock, finished_clock, acquisition_clock, outcome_kind, outcome_content, terminal_basis, terminal_view; all use E0 and actual EH/EW/EA/EL, never EU values or success flags", (769, 1085)),
    ("A-CLOCK-WIRE", "紙に無い仮定: the model stores Event clock_reading/1 {source: Point, reading: Reading}; G.clock and Cq clocks reference its Saved Point. The source is a Saved model.clock_source/1 Event matching reading.run/source. Only A-READING-NS maps the reading to F-a's wire; no notification or record-creation time substitutes for it", (1031, 1511)),
    ("A-READING-NS", "紙に無い仮定: time_ns = Reading.rank and run is retained; Reading.source identifies the clock source. This is an integer model correspondence, not a claim about physical nanosecond accuracy", (1511, 1511)),
    ("A-CLOCK-SOURCE", "紙に無い仮定: a predeclared Saved Event model.clock_source/1 {run, source} identifies the clock; clock_reading/1.source points to it, and both fields equal reading.run/source. Save the source before preparing clock evidence; physical clock wiring/performance is outside this model", (1511, 1511)),
    ("A-T-UNKNOWN", "紙に無い仮定: terminal_basis names the whole original Unknown Outcome.content, without adding or projecting a Generation carrier; it establishes neither an EW return nor Stop. Failure basis is the validated Generation; definite-reply basis is None", (769, 1510)),
    ("A-EL-ROOT", "紙に無い仮定: a raw ObservationTrace supplies a complete append-only history and its final actual EL; values with no IO write/readback occurrence are supplied initial EL. trace_at uses exclusive event offsets, retains the uncut origin, and rewinds events/bodies/entries together. A strict prefix has clock=None: the event log does not give its exact host clock. An origin-bearing mixed snapshot is rejected; a raw truncated log cannot be distinguished from initial EL without additional provenance. Unlogged late preparation cannot establish an earlier publication view", (816, 823)),
    ("A-PUBLISH-REF", "紙に無い仮定: at Publish, record recipes retain the exact unit/slot identity of PlanRefs to declared slots of that same unit; other-unit record PlanRefs require independent Saved resolution. Full E0/EU records AND work descriptions still compare exactly; pending work requirements resolve at start (390), not by this record projection. Preparation/Saved checks resolve every record reference to Point; a retained PlanRef never establishes Saved", (843, 1000)),
)


@dataclass(frozen=True, slots=True)
class PublicType:
    """Structural type name in the allowed public data section, NOT an import."""
    name: str
    context: str = "default"


def _public(name, context="default"):
    return Annotated[object, PublicType(name, context)]


FrozenData = Annotated[object, "frozen-data"]
MPoint = _public("Point")
MPlanRef = _public("PlanRef")
MRef = MPoint | MPlanRef
MSource = _public("Source")
MDeclRef = MRef | MSource
MDeclPlan = _public("AllowedPlan", "declaration")
MDeclRecordPlan = _public("RecordPlan", "declaration")
MReading = _public("Reading")
MContract = _public("Contract")
MObject = _public("Object")
MEnvelope = _public("Envelope")
MDescriptor = _public("Descriptor")
MPlan = _public("AllowedPlan")
MPrepared = _public("PreparedEntry")
MBody = _public("Body")
MEntry = _public("Entry")
MView = _public("NumericalView")
MGeneration = _public("Generation")
MAcquisition = _public("ActualAcquisition")
MCall = _public("VerificationCall")
MReply = _public("VerificationReply")
MCertificate = _public("Certificate")
MInterval = _public("Interval")
MCell = _public("Cell")

# Exact public shapes; object-typed leaves are NOT permission for mutable or
# arbitrary objects. All such leaves recursively use this closed data grammar.
# Source: fb_machine.py permitted data definitions, 131-1129 ONLY.
PUBLIC_SHAPES = {
    "Point": {"cid": str}, "PlanRef": {"unit": str, "slot": str},
    "Contract": {"name": str, "version": str},
    "Reading": {"run": str, "source": str, "rank": int},
    "Unavailable": {"reason": str, "basis": frozenset[MPoint]},
    "Object": {"items": tuple[tuple[str, FrozenData], ...]},
    "Event": {"kind": str, "fields": MObject},
    "Envelope": {"run": str, "number": int, "r": MReading, "receipt_seq": int,
                 "event": _public("Event"), "source": str},
    "Outcome": {"kind": Literal["Success", "Failure", "Unknown"], "content": FrozenData},
    "Generation": {"work": str, "request": MRef, "stage": str,
                   "started": MReading | _public("Unavailable"),
                   "finished": MReading | _public("Unavailable"),
                   "outcome": _public("Outcome"), "provenance": str},
    "Report": {"kind": Literal["Frame", "Started", "Ended", "RouteApplied", "Gap", "Unavailable", "Claim", "Unproved"],
               "segment": MRef, "item_slot": str, "route_epoch": str, "fields": MObject},
    "TypedReference": {"path_id": str, "path": tuple[str | int, ...], "ref": MRef, "role": str, "use": str},
    "NumericalView": {"points": frozenset[MRef], "application_order": tuple[MRef, ...], "context": MObject},
    "Record": {"name": str, "at": MReading, "contract": MContract, "category": str,
                "content": MObject, "references": tuple[_public("TypedReference", "materialized"), ...]},
    "RecordPlan": {"slot": str, "contract": MContract, "category": str, "content": MObject,
                   "references": tuple[_public("TypedReference"), ...], "parents": frozenset[MRef], "at": MReading | None},
    "Header": {"record": _public("Record"), "seal": str, "parents": frozenset[MPoint]},
    "PreparedEntry": {"record": _public("Record"), "parents": frozenset[MPoint], "salt": bytes,
                      "payload": bytes, "seal": str, "header": _public("Header"), "point": MPoint},
    "Body": {"seal": str, "salt": bytes, "payload": bytes},
    "Entry": {"point": MPoint, "header": _public("Header")},
    "Descriptor": {"work_id": str, "process": MRef, "trigger": MRef, "purpose": str, "stage_slot": str,
                   "reader": MRef, "method": MContract, "output_contract": MContract, "args": MObject,
                   "input_points": frozenset[MRef], "numerical_view": MView, "allocation": str,
                   "permissions": frozenset[MRef], "request": MRef, "stage": str,
                   "need": tuple[tuple[str, int], ...], "required": frozenset[MRef],
                   "use_keys": frozenset[FrozenData], "semantic_limits": tuple[str, ...]},
    "Source": {"kind": str, "key": str},
    "IntervalRequest": {"id": str, "point": MRef, "route_epoch": str, "work": str,
                        "interval": MInterval, "measurement_contract": MContract,
                        "clock_contract": MContract, "cells": frozenset[MCell]},
    "Guard": {"kind": str, "key": FrozenData, "value": FrozenData},
    "AllowedPlan": {"unit": str, "obligation_id": str, "key": FrozenData,
                    "records": tuple[_public("RecordPlan"), ...], "works": tuple[MDescriptor, ...],
                    "guards": tuple[_public("Guard"), ...], "use_keys": frozenset[FrozenData],
                    "operation": str, "semantic_limits": tuple[str, ...]},
    "ActualAcquisition": {"intent": str, "reader": MPoint, "targets": frozenset[MPoint],
                          "contents": tuple[tuple[MPoint, bytes], ...], "view": frozenset[MPoint],
                          "reading": MReading, "ancestors": frozenset[MPoint]},
    "UpdateTarget": {"request": MRef, "result": MRef, "proofs": frozenset[MRef], "completion": MRef},
    "VerificationCall": {"work": str, "target": _public("UpdateTarget"), "input_read": MView,
                         "check_view": frozenset[MPoint], "arguments": MObject},
    "Certificate": {"issuer": str, "target": _public("UpdateTarget"), "reader": MPoint,
                    "target_contents": tuple[tuple[MPoint, bytes], ...], "numerical_view": MView,
                    "evidence_closure": frozenset[MPoint], "check_view": frozenset[MPoint],
                    "registry": str, "checker": MContract, "result_digest": str},
    "VerificationReply": {"response": Literal["Success", "Rejected", "Insufficient"],
                          "target": _public("UpdateTarget"), "reader": MPoint,
                          "target_contents": tuple[tuple[MPoint, bytes], ...], "numerical_view": MView,
                          "evidence_closure": frozenset[MPoint], "check_view": frozenset[MPoint],
                          "registry": str, "checker": MContract, "result": FrozenData,
                          "reasons": tuple[FrozenData, ...], "missing": frozenset[FrozenData],
                          "certificate": MCertificate | None},
    "Cell": {"start": int, "end": int},
    "Interval": {"run": str, "clock": str, "start": int, "end": int,
                 "left_closed": bool, "right_closed": bool},
}


DECLARATION_SHAPES = {
    "TypedReference": dict(PUBLIC_SHAPES["TypedReference"], ref=MDeclRef),
    "RecordPlan": dict(PUBLIC_SHAPES["RecordPlan"], content=MObject | MSource, parents=frozenset[MDeclRef],
                       references=tuple[_public("TypedReference", "declaration"), ...]),
    "AllowedPlan": dict(PUBLIC_SHAPES["AllowedPlan"], records=tuple[MDeclRecordPlan, ...]),
}


def declaration_reference_contract() -> str:
    """Public source-bearing declaration contract (F-b 843,998,1062,1094).

    MDeclRef = Point | PlanRef | Source is allowed ONLY in declared
    RecordPlan.references[*].ref and RecordPlan.parents. ObservationE0.plans,
    DerivationBinding.plan and planned IntervalEvidenceBinding.record use these
    declaration shapes. Published plans may retain PlanRef, but not Source in
    these positions. Actual Record.references[*].ref and Header/PreparedEntry
    parents MUST be resolved Points. Missing Source input stays unconnected.
    E0 fixes the recipe before execution; EH/EW/EA/EL supply its arguments.
    No observed reference or parent is used as the expected resolution.
    """
    return "MDeclRef = Point | PlanRef | Source; materialized references/parents = Point"


@dataclass(frozen=True, slots=True)
class ReceiptKey:
    run: str
    number: int


@dataclass(frozen=True, slots=True)
class SlotKey:
    unit: str
    slot: str


@dataclass(frozen=True, slots=True)
class WorkKey:
    work: str


@dataclass(frozen=True, slots=True)
class WorkToken:
    work: str
    token: str


@dataclass(frozen=True, slots=True)
class IOKey:
    slot: SlotKey
    operation: Literal["PutBody", "AddEntry", "ReadBody", "ReadEntry"]
    attempt: str  # stable finite request identity, not an unbounded retry counter


@dataclass(frozen=True, slots=True)
class UnitKey:
    unit: str


@dataclass(frozen=True, slots=True)
class IntentKey:
    reader: MRef  # E0 may declare a PlanRef; actual Acquire still requires its Point.
    intent: str


@dataclass(frozen=True, slots=True)
class VerificationKey:
    work: str
    call: str


@dataclass(frozen=True, slots=True)
class CompletionKey:
    obligation: str
    obligation_key: FrozenData
    kind: Literal["save", "run", "issue", "handle", "stop"]
    target: SlotKey | WorkKey | IntentKey


@dataclass(frozen=True, slots=True)
class Owner:
    location: Literal["H", "P.receipts", "P.units", "P.work"]
    key: FrozenData


# Paper 1185/1193; frozen state observation, never an achievement flag.
PUBLIC_SHAPES["ConditionCustody"] = {
    "key": CompletionKey, "owner": Owner, "unmet": frozenset[CompletionKey],
}


@dataclass(frozen=True, slots=True)
class Posted:
    envelope: MEnvelope


@dataclass(frozen=True, slots=True)
class Accepted:
    envelope: MEnvelope
    unit: str
    plans: tuple[_public("RecordPlan"), ...]
    created: MReading


@dataclass(frozen=True, slots=True)
class Reserved:
    descriptor: MDescriptor
    resources: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class WrapperEvent:
    wrapper: str


@dataclass(frozen=True, slots=True)
class BodyEntered:
    wrapper: str
    started: MReading | _public("Unavailable")


@dataclass(frozen=True, slots=True)
class LaunchResponse:
    wrapper: str
    response: Literal["not_entered", "unknown"]
    evidence: FrozenData


@dataclass(frozen=True, slots=True)
class InputRead:
    descriptor: MDescriptor
    numerical_view: MView
    resolutions: tuple[tuple[MPlanRef, MPoint], ...]


@dataclass(frozen=True, slots=True)
class Returned:
    generation: MGeneration


@dataclass(frozen=True, slots=True)
class UnknownObserved:
    # Host knowledge, NOT a worker return or evidence of Stop. Paper 333,786-790.
    envelope: MEnvelope
    request: MRef
    stage: str
    basis: FrozenData
    witnesses: tuple[ObservationEvent, ...]


@dataclass(frozen=True, slots=True)
class Stopped:
    evidence: FrozenData


@dataclass(frozen=True, slots=True)
class Released:
    resources: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class FirstPrepared:
    prepared: MPrepared


@dataclass(frozen=True, slots=True)
class IORequest:
    prepared: MPrepared


@dataclass(frozen=True, slots=True)
class IOResponse:
    response: Literal["acknowledged", "rejected", "lost"]
    # Actual commit bytes, not a "saved" boolean. Still checked against EL.
    written: MBody | MEntry | None


@dataclass(frozen=True, slots=True)
class ReadBack:
    value: MBody | MEntry | None


@dataclass(frozen=True, slots=True)
class Published:
    plan: MPlan


@dataclass(frozen=True, slots=True)
class Acquired:
    acquisition: MAcquisition
    # C-O08.handle precedes C-O08.save[G] (1216-1217). None is an actual
    # acquisition BEFORE G exists, not an absent acquisition observation.
    # A legacy non-None claim is checked against independently reconstructed G.
    record: MPoint | None = None


@dataclass(frozen=True, slots=True)
class VerificationInvoked:
    call: MCall


@dataclass(frozen=True, slots=True)
class VerificationReturned:
    reply: MReply


@dataclass(frozen=True, slots=True)
class CertificateIssued:
    certificate: MCertificate


@dataclass(frozen=True, slots=True)
class CausalNode:
    point: MPoint
    parents: frozenset[MPoint]


@dataclass(frozen=True, slots=True)
class Adopted:
    record: MPoint
    completion: MPoint
    result: MPoint
    previous: MPoint | None
    previous_result: MPoint | None
    verification: VerificationKey
    acquisitions: tuple[IntentKey, ...]
    actual_ancestors: frozenset[MPoint]
    causal_dag: tuple[CausalNode, ...]
    view: frozenset[MPoint]


@dataclass(frozen=True, slots=True)
class AdoptionReserved:
    completion: MPoint


@dataclass(frozen=True, slots=True)
class CloseSave:
    slots: tuple[SlotKey, ...]


@dataclass(frozen=True, slots=True)
class HandoffPurpose:
    """C-O01..14 (1185,1193): EU transport target for the window author.

    The edge carries CompletionKey plus the actual source/destination owners and
    ALL still-unmet conditions before/after, preserving keys and targets. This
    event does not attest achievement. evaluate_observation_step compares it
    with both frozen states' P.conditions, independently of E0 owner defaults.
    """
    source: Owner
    destination: Owner
    before: frozenset[CompletionKey]
    after: frozenset[CompletionKey]


@dataclass(frozen=True, slots=True)
class ApplicationKey:
    reader: MPoint
    model: MPoint
    series: MPoint


@dataclass(frozen=True, slots=True)
class Applied:
    contract: MContract
    report_meaning: FrozenData
    binding: MPoint
    transition_key: FrozenData
    kernel: FrozenData
    outcomes: FrozenData
    measurements: frozenset[str]
    input_digest: str
    purpose: Literal["new_application", "replay", "no_op"]


@dataclass(frozen=True, slots=True)
class IntervalKey:
    request: str
    route: str
    run: str


@dataclass(frozen=True, slots=True)
class IntervalUndertaken:
    """C-O04.save[k]/handle[cells], paper 629,1186,1205-1207.

    Actual acceptance of the FULL request, before or after k publication. EI's
    measurement/configuration/report facts are not acceptance. A-TAGS: the
    spelling and EH transport are model choices; the paper does not identify
    an existing Environment operation with this event. No implicit adapter.
    """
    request: _public("IntervalRequest")
    owner: Owner
    reading: MReading


@dataclass(frozen=True, slots=True)
class IntervalObserved:
    reading: MReading | _public("Unavailable")
    interval: MInterval | None
    cells: frozenset[MCell]
    work: str
    evidence: MRef | None  # Only E0's expected event may retain a PlanRef.
    content: FrozenData


@dataclass(frozen=True, slots=True)
class CoverageClaimed:
    view: frozenset[MPoint]
    report: MPoint
    kind: str
    contract: MContract
    evidence: frozenset[MPoint]
    cells: frozenset[MCell]


@dataclass(frozen=True, slots=True)
class ArtifactValue:
    contract: MContract
    compiler: MContract
    reader_view_key: str
    registry_key: str
    inputs: FrozenData
    calls: FrozenData
    output: FrozenData


@dataclass(frozen=True, slots=True)
class ArtifactIssued:
    artifact: ArtifactValue
    generation: MGeneration


@dataclass(frozen=True, slots=True)
class ArtifactChecked:
    artifact: ArtifactValue
    result: Literal["Selected", "FProblem", "NoDecision", "Rejected", "Insufficient"]
    request: MRef  # E0 may use PlanRef; actual port values must be Points.
    problem: MRef | None
    draw: MRef | None
    evidence: frozenset[MRef]


@dataclass(frozen=True, slots=True)
class TagContract:
    tag: str
    channel: str
    key_type: type
    value_type: type
    paper: Paper
    rows: tuple[str, ...]


def _tag(tag, channel, key, value, ids, lines, rows):
    return TagContract(tag, channel, key, value, Paper(tuple(ids), lines), tuple(rows))


OBSERVATION_TAGS = (
    _tag("IntervalUndertaken", "EH", IntervalKey, IntervalUndertaken,
         ("C-O04.save[k]", "C-O04.handle[cells]", "INV-12"), (1205, 1207), ("INV-2.a", "INV-12.a")),
    *(_tag(tag, "EH", ReceiptKey, Posted, ("SAVE-1/2", "RIGHT-RECEIPT"), (794, 802),
           ("INV-1.a", "INV-1.b", "INV-15.a")) for tag in ("Post", "Present", "HostAck")),
    _tag("Accept", "EH", ReceiptKey, Accepted, ("I-1..8", "SAVE-2"), (457, 467), ("INV-1.a", "INV-1.b", "INV-1.c")),
    _tag("Reserve", "EW", WorkToken, Reserved, ("Need", "Occ", "START-0", "INV-5.b"), (829, 855), ("INV-3.c", "INV-5.b", "INV-10.a")),
    *(_tag(tag, "EW", WorkToken, WrapperEvent, ("RIGHT-WORK", "START-1..4"), (1289, 1294),
           ("INV-3.a", "INV-3.b", "INV-3.c")) for tag in ("Launch", "ConsumeToken")),
    _tag("EnterBody", "EW", WorkToken, BodyEntered, ("START-3", "E0-05", "INV-5.b"), (855, 1001), ("INV-3.a", "INV-3.b", "INV-5.b", "INV-6.a", "INV-13.a")),
    _tag("LaunchResponse", "EW", WorkToken, LaunchResponse, ("START-2", "START-?"), (1291, 1294), ("INV-3.b", "INV-3.c")),
    _tag("ReadInputs", "EW", WorkToken, InputRead, ("E0-04", "INV-8.b"), (1000, 1001), ("INV-3.b", "INV-8.a", "INV-8.b")),
    _tag("WorkerReturn", "EW", WorkToken, Returned, ("E0-05", "Gen(w)"), (1001, 1001), ("INV-6.a", "INV-15.a", "INV-15.b")),
    _tag("HostUnknown", "EH", WorkKey, UnknownObserved, ("T(Unknown)", "EndKnown"), (786, 790), ("INV-15.a", "INV-15.b", "INV-10.b")),
    _tag("Stop", "EW", WorkToken, Stopped, ("O-14", "START-4"), (1237, 1237), ("INV-3.c", "INV-10.b")),
    _tag("Release", "EW", WorkToken, Released, ("O-14", "Occ"), (829, 835), ("INV-3.c", "INV-10.a", "INV-10.b")),
    _tag("FirstPrepare", "EP", SlotKey, FirstPrepared, ("INV-4.c", "SAVE-3", "INV-7.a", "INV-9.a"), (860, 1316), ("INV-4.a", "INV-4.b", "INV-4.c", "INV-7.a", "INV-9.a")),
    _tag("IORequest", "EP", IOKey, IORequest, ("SAVE-4..7",), (1312, 1315), ("INV-4.a", "INV-4.c")),
    _tag("IOResponse", "EP", IOKey, IOResponse, ("SAVE-4..7",), (1312, 1315), ("INV-4.a", "INV-4.c")),
    _tag("ReadBack", "EP", IOKey, ReadBack, ("SAVE-5/7",), (1313, 1315), ("INV-4.a", "INV-4.c")),
    _tag("Publish", "EU", UnitKey, Published, ("O-01..14", "INV-2.b", "INV-7.a", "INV-9.a"), (608, 865), ("INV-2.a", "INV-2.b", "INV-2.c", "INV-7.a", "INV-9.a", "INV-13.a")),
    _tag("Acquire", "EA", IntentKey, Acquired, ("PATH-ACQUIRE", "C-O08.handle/issue/save", "INV-6.c"), (859, 1217), ("INV-6.c", "INV-9.a")),
    _tag("VerifyCall", "EA", VerificationKey, VerificationInvoked, ("PATH-LINK-ACQUISITION",), (1093, 1093), ("INV-8.a", "INV-9.a")),
    _tag("VerifyReply", "EA", VerificationKey, VerificationReturned, ("O-09.a", "INV-9.a"), (779, 784), ("INV-9.a", "INV-15.b")),
    _tag("CertificateIssued", "EA", VerificationKey, CertificateIssued, ("H-03", "INV-9.a"), (820, 822), ("INV-9.a",)),
    *(_tag(tag, "EA", IntentKey, AdoptionReserved, ("RIGHT-ADOPT", "INV-9.b"), (335, 336), ("INV-9.b",))
      for tag in ("ReserveAdoption", "ReleaseAdoption")),
    _tag("Adopt", "EA", IntentKey, Adopted, ("PATH-ADOPT", "RIGHT-ADOPT", "INV-6.c"), (859, 1086), ("INV-6.c", "INV-9.a", "INV-9.b")),
    _tag("CloseSave", "EU", CompletionKey, CloseSave, ("C-O01..14",), (1185, 1194), ("INV-2.a", "INV-2.c", "INV-4.c")),
    _tag("HandoffPurpose", "EU", CompletionKey, HandoffPurpose, ("O-09.b", "C-O01..14"), (1193, 1194), ("INV-2.a", "INV-2.c", "INV-2.f")),
    _tag("Apply", "EW", ApplicationKey, Applied, ("RIGHT-APPLY",), (1148, 1149), ("INV-6.b", "INV-6.c", "INV-7.a")),
    *(_tag(tag, "EI", IntervalKey, IntervalObserved, ("Support", "INV-12"), (729, 739), ("INV-12.a", "INV-12.b"))
      for tag in ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "ReportGenerated", "MeasurementEnded")),
    _tag("CertifiedCoverage", "EA", IntervalKey, CoverageClaimed, ("Support", "CertifiedCoverage"), (745, 750), ("INV-12.a",)),
    _tag("ArtifactIssued", "EW", WorkKey, ArtifactIssued, ("PATH-ARTIFACT-*", "O-10", "O-12"), (1089, 1092), ("INV-16.a", "INV-16.b")),
    _tag("ArtifactChecked", "EA", WorkKey, ArtifactChecked, ("PATH-ARTIFACT-*", "H-03"), (1089, 1096), ("INV-16.a", "INV-16.b")),
)
TAG_BY_NAME = {t.tag: t for t in OBSERVATION_TAGS}


@dataclass(frozen=True, slots=True)
class ObservationEvent:
    tag: str
    key: object  # validated against TagContract.key_type, no opaque escape
    value: object  # validated against TagContract.value_type


@dataclass(frozen=True, slots=True)
class ObservationOrigin:
    """Checker-retained uncut input, never a window-declared historical view.

    A-EL-ROOT (816-823,1002): writes are first actual IOResponse/ReadBack
    occurrences, not successful-response or Prepared flags. Only trace_at
    constructs this index; the source events remain available for validation.
    """
    events: tuple[ObservationEvent, ...]
    bodies: frozenset[MBody]
    entries: frozenset[MEntry]
    clock: MReading | None
    writes: tuple[tuple[int, MBody | MEntry], ...]


@dataclass(frozen=True, slots=True)
class ObservationTrace:
    events: tuple[ObservationEvent, ...]
    # EL full values, independent of EP response flags; compare with actual C/E.
    bodies: frozenset[MBody] = frozenset()
    entries: frozenset[MEntry] = frozenset()
    clock: MReading | None = None  # actual host reading at this state, not Record.at
    origin: ObservationOrigin | None = None  # trace_at provenance, not an extra EL view


@dataclass(frozen=True, slots=True)
class ReceiptLayout:
    kind: Literal["Boot", "Received", "SegmentReport", "WorkFinished", "DrawReturned"]
    route: str
    slots: tuple[tuple[str, str, str], ...]  # (slot, contract name, version)
    parents: frozenset[MPoint] = frozenset()


RECEIPT_LAYOUTS = (
    ReceiptLayout("Boot", "model/receipt", (("boot", "sui.s4.boot", "1"), ("declaration", "sui.fb.boot_declaration", "1"))),
    ReceiptLayout("Received", "model/receipt", (("receipt", "sui.fb.received", "1"),)),
    ReceiptLayout("SegmentReport", "model/receipt", (("receipt", "sui.fb.segment_report", "1"),)),
    ReceiptLayout("WorkFinished", "model/receipt", (("receipt", "sui.fb.work_report", "1"),)),
    ReceiptLayout("DrawReturned", "model/receipt", (("receipt", "sui.fb.draw_report", "1"),)),
)


@dataclass(frozen=True, slots=True)
class CodecDeclaration:
    encoding: Literal["model-json-v1"] = "model-json-v1"
    seal: Literal["fb-check-seal/1"] = "fb-check-seal/1"
    cid: Literal["sha256-model-header/1"] = "sha256-model-header/1"


@dataclass(frozen=True, slots=True)
class ReceiptSource:
    """Public pre-run EH selector/receipt alias (616-620,997-999,1363).

    unit is a distinct logical PlanRef unit, not a predicted receipt unit/CID.
    source is the declared delivery-provenance label (Envelope.source, not an
    event payload field). Match the complete Event and, if given, run. Resolve
    only a UNIQUE actual Post; never guess number, r or receipt_seq. Declare
    this object in ObservationE0.receipt_sources and use it as a derivation's
    envelope. SlotKey(unit, slot) / PlanRef(unit, slot) refer to its saved receipt.
    Multiple matching originals remain unconnected, not first-wins.

    A-RECEIPT-SELECTOR is model representation. Environment must preserve the
    declared provenance and support this alias for model-side plan resolution;
    this checker entry alone does not make the scenario executable.
    """
    unit: str
    source: str
    event: _public("Event")
    slot: str = "receipt"
    run: str | None = None


@dataclass(frozen=True, slots=True)
class DerivationBinding:
    """Finite E0 relation, never reverse-engineered from a published Q.

    O-03 / paper 616-620. Actual eligibility additionally requires the exact EH
    original and its Saved receipt. `unsupported` is not an eligibility flag.
    Pre-run declarations may use PlanRef throughout the reference fields and
    ReceiptSource for envelope. receipt names that source's logical unit/slot;
    actual EH numbers are resolved by resolve_derivation_binding. plan remains
    the predeclared AllowedPlan (including PlanRefs/declared Source recipes).
    No plan/root/method is inferred from a published Q. /2 stays unsupported.
    """
    declaration: MRef
    version: str
    process: MRef
    reader: MRef
    purpose: str
    envelope: MEnvelope | ReceiptSource
    receipt: SlotKey
    trigger_slot: str
    stage_slot: str
    allowed_group: frozenset[str]
    method: MContract
    inputs: frozenset[MRef]
    evidence: frozenset[MRef]
    root: frozenset[MRef]
    previous_result: MRef | None
    request: SlotKey
    plan: MDeclPlan
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompletionBinding:
    # Typed INSTANCE, not just a reusable string C-Oxx.save[T]. 1185-1194.
    key: CompletionKey
    trigger: Literal["Post", "Publish", "EndKnown", "Acquire", "IntervalRequest", "Reserve"]
    source: ReceiptKey | UnitKey | WorkKey | IntentKey | IntervalKey | WorkToken
    slots: tuple[SlotKey, ...]
    owner: Owner


@dataclass(frozen=True, slots=True)
class ApplicationBinding:
    key: ApplicationKey
    contract: MContract
    report_meaning: FrozenData
    binding: MPoint
    transition_key: FrozenData
    kernel: FrozenData
    outcomes: FrozenData
    measurements: frozenset[str]
    input_digest: str
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquisitionBinding:
    key: IntentKey
    targets: frozenset[MRef]
    completion: MRef
    required_ancestors: frozenset[MRef]
    # PATH-LINK-ACQUISITION (1093). A PlanRef declares the exact G for this
    # intent; None means this second-stage connection is still unavailable.
    record: MRef | None = None


@dataclass(frozen=True, slots=True)
class VerificationBinding:
    key: VerificationKey
    target: _public("UpdateTarget")
    reader: MRef  # E0-04 / REF-5 (1000,1062): resolved at the actual call.
    numerical_view: MView
    evidence_closure: frozenset[MRef]
    check_view: frozenset[MRef]
    registry: str
    checker: MContract
    arguments: MObject


@dataclass(frozen=True, slots=True)
class AdoptionBinding:
    key: IntentKey
    completion: MRef
    result: MRef
    previous_result: MRef | None
    verification: VerificationKey
    acquisitions: tuple[IntentKey, ...]
    re_adoption: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactPortBinding:
    """Public finite declared issuer/checker-port relation (636-637,1089-1096).

    Author before execution; PlanRefs in inputs/returns resolve at the actual
    issuing/checking edge, independently of port output. checked_returns may
    name EQ/problem/Draw with PlanRefs; actual ArtifactChecked uses Points.
    Pair with ObservationE0.plans (AllowedPlan/Descriptor) to declare EQ -> Ep,
    FProblem PR -> D, DF -> Ee; D's full args remain fixed by its Descriptor.
    This is not a F-a artifact generator, proof of IE/ID legality, a general
    artifact closure, or permission to generate D from NoDecision/Unknown.
    Those real execution/issuance paths remain the Environment author's work.
    """
    work: str
    contract: MContract
    compiler: MContract
    reader_view_key: str
    registry_key: str
    inputs: FrozenData
    # Independent finite environment-port program, not an assertion of proof.
    possible_returns: tuple[ArtifactValue, ...]
    checked_returns: tuple[ArtifactChecked, ...] = ()


@dataclass(frozen=True, slots=True)
class HostUnknownBinding:
    work: str
    source: str
    request: MRef
    stage: str
    basis: FrozenData


@dataclass(frozen=True, slots=True)
class ReferenceBinding:
    """Public E0 reference rule (997,1003,1076-1096).

    `path` may contain '*'; reference_paths expands each named tuple array.
    The observed TypedReference uses concrete indices (A-REFERENCE-PATH).
    Contract/version/use/operation remain part of the declaration, not a name
    heuristic. Unsupported closure remains unsupported after path expansion.
    """
    record_contract: MContract
    path_id: str
    path: tuple[str | int, ...]
    role: Literal["E", "U", "UE"]
    use: str
    operation: str
    closure: Literal["direct", "unsupported"]


@dataclass(frozen=True, slots=True)
class IntervalBinding:
    key: IntervalKey
    point: MRef  # REF-5 (1062): undertaking/actual EI can precede k's publication.
    work: str
    interval: MInterval
    endpoints: tuple[int, ...]
    measurement_contract: MContract
    clock_contract: MContract


@dataclass(frozen=True, slots=True)
class IntervalEvidenceBinding:
    """Public EI -> saved evidence declaration (739,745-750,1334).

    Pre-run form: point=PlanRef(unit,slot), record=the E0 RecordPlan for that
    slot. No CID/name/salt/time needs predicting. The checker reconstructs the
    complete Record/bytes/CID from that plan and EP's fixed fresh values.
    event.evidence may be that PlanRef; actual EI observations require a Point.
    Concrete Point + full Record remains supported for frozen fixtures.
    This correspondence neither defines Support nor admits outside-X history.
    """
    point: MRef
    key: IntervalKey
    tag: str
    event: IntervalObserved
    record: _public("Record") | MDeclRecordPlan


@dataclass(frozen=True, slots=True)
class ObservationE0:
    """Public immutable expectations, authored BEFORE any window execution.

    receipt_sources/derivations declare delta's EH selection and logical receipt
    PlanRefs; interval_evidence binds EI facts to predeclared saved plans;
    artifacts specifies finite actual-port expectations. plans/descriptors carry
    structural EQ/PR/D correspondences. None supplies unspecified Support,
    /2 projection, full artifact closure or a legal real F-a prefix by fiat.
    See PUBLIC_SCENE_API for independently evaluable candidate entry points.
    """
    version: Literal["fb-observation/1"] = "fb-observation/1"
    codec: CodecDeclaration = CodecDeclaration()
    receipt_layouts: tuple[ReceiptLayout, ...] = RECEIPT_LAYOUTS
    plans: tuple[MDeclPlan, ...] = ()
    descriptors: tuple[MDescriptor, ...] = ()
    capacity: tuple[tuple[str, int], ...] = ()
    allocation: tuple[tuple[str, int], ...] = ()
    generation_sources: tuple[tuple[str, str], ...] = ()  # work -> actual port provenance
    host_unknowns: tuple[HostUnknownBinding, ...] = ()
    derivations: tuple[DerivationBinding, ...] = ()
    completions: tuple[CompletionBinding, ...] = ()
    applications: tuple[ApplicationBinding, ...] = ()
    acquisitions: tuple[AcquisitionBinding, ...] = ()
    verifications: tuple[VerificationBinding, ...] = ()
    adoptions: tuple[AdoptionBinding, ...] = ()
    artifacts: tuple[ArtifactPortBinding, ...] = ()
    references: tuple[ReferenceBinding, ...] = ()
    intervals: tuple[IntervalBinding, ...] = ()
    interval_evidence: tuple[IntervalEvidenceBinding, ...] = ()
    receipt_sources: tuple[ReceiptSource, ...] = ()
    # Explicitly unsupported, not a way to erase an obligation or a row.
    unsupported: tuple[str, ...] = ("PATH-QOBS", "bootstrap/2-projection", "contract-specific-Support",
                                    "artifact-full-closure", "unfixed-parent-minima", "targeted-certificate-wire")


E0_OBSERVATION_CONTRACTS = (
    ("receipt_sources", ReceiptSource, Paper(("O-03", "E0-02", "SC-08"), (616, 620))),
    ("codec", CodecDeclaration, Paper(("INV-4.a", "SAVE-4..8"), (427, 462))),
    ("receipt_layouts", ReceiptLayout, Paper(("I-1..8", "PATH-RECEIPT"), (457, 467))),
    ("plans/descriptors", "AllowedPlan/Descriptor (public exact shapes)", Paper(("E0-04", "INV-2.b"), (997, 1004))),
    ("capacity/allocation", "tuple[(resource, nonnegative integer)]", Paper(("Need", "Occ", "Fit"), (829, 835))),
    ("generation_sources", "tuple[(WorkId, provenance)]", Paper(("E0-05", "PATH-LINK-GENERATION"), (1092, 1092))),
    ("host_unknowns", HostUnknownBinding, Paper(("T(Unknown)", "EndKnown"), (786, 790))),
    ("derivations", DerivationBinding, Paper(("O-03", "Matchδ", "Dischargeδ"), (616, 620))),
    ("completions", CompletionBinding, Paper(("C-O01..14",), (1185, 1237))),
    ("applications", ApplicationBinding, Paper(("RIGHT-APPLY",), (1148, 1149))),
    ("acquisitions/adoptions", "AcquisitionBinding/AdoptionBinding", Paper(("PATH-ACQUIRE", "PATH-ADOPT"), (1085, 1086))),
    ("verifications", VerificationBinding, Paper(("INV-9.a", "PATH-LINK-ACQUISITION"), (1093, 1093))),
    ("artifacts", ArtifactPortBinding, Paper(("PATH-ARTIFACT-*",), (1089, 1092))),
    ("references", ReferenceBinding, Paper(("E0-01", "REF-1..8", "PATH-*"), (997, 1096))),
    ("intervals/interval_evidence", "IntervalBinding/IntervalEvidenceBinding", Paper(("EI", "Support"), (723, 750))),
    ("PlanRef/Source resolution", "E0 recipe + actual EP fresh values + checker A-CODEC; never P/EU resolution values",
     Paper(("E0-02", "REF-5", "SAVE-3..7"), (998, 1062))),
    ("Source started_clock/finished_clock", "validated Generation.started/finished of the named WorkId; values, not evidence Points",
     Paper(("E0-05", "PATH-COMPLETE"), (1001, 1084))),
    ("Source acquisition_clock", "unique actual Acquire.reading for the intent; before Acquire unresolved",
     Paper(("PATH-ACQUIRE", "G"), (1032, 1085))),
    ("Source outcome_kind/outcome_content/terminal_basis/terminal_view",
     "first validated Outcome; full Failure/Unknown evidence; Saved set at publication root",
     Paper(("INV-2.b", "T"), (769, 1044))),
    ("MDeclRef / A-CLOCK-WIRE", "declaration_reference_contract / clock_evidence_reading public docstrings",
     Paper(("REF-5", "PATH-COMPLETE", "PATH-ACQUIRE", "PATH-PARENTS"), (1031, 1094))),
)


# Public contract surface for independently authored scenes. Read signatures,
# annotations and docstrings, not checker internals or the window algorithm.
# None of these entry points promotes handmade candidates to verified rows.
PUBLIC_SCENE_API = (
    "trace_at", "publication_root", "ObservationOrigin",
    "declaration_reference_contract", "clock_evidence_reading", "completed_clock_reading", "MDeclRef", "MDeclPlan", "MDeclRecordPlan",
    "CheckReport", "Checker", "check_exploration", "ObservationE0", "evaluate_observations", "evaluate_observation_step",
    "evaluate_condition_custody",
    "acyclic", "fair_cycle", "progress_counterexamples", "derive_progress", "reference_paths", "ReferenceBinding",
    "ReceiptSource", "DerivationBinding", "resolve_receipt_source", "resolve_derivation_binding", "derive_observation_status",
    "IntervalEvidenceBinding", "resolve_interval_evidence", "ArtifactPortBinding", "resolve_artifact_port", "declaration_value",
    "publication_value",
)


# Body-free public handoff: read this literal catalogue, the frozen observation
# types above, PUBLIC_SHAPES/DECLARATION_SHAPES, OBSERVATION_TAGS, E0_OBSERVATION_CONTRACTS,
# and OBSERVATION_ASSUMPTIONS. No predicate/window implementation is required.
# Candidate evaluations never count as correct-window or discrimination passes.
PUBLIC_CHECK_CONTRACTS = (
    ("evaluate_condition_custody", "(contract: ObservationE0, trace: ObservationTrace, state, *, before_state=None) -> ObservationEvaluation",
     "C-05 / v0.15 (1307,1315-1353,1529-1586): 44 per-ID Direct predicates, typed custody judgements and independent D3 PurposePart identities. Population includes E0/observed births, actual promises and every prior unmet identity. Direct/Transfer/retention/loss are distinct; unknown conclusions stay in custody/limitations, never become violations by default. Fixed cells are checked separately. Current legacy HandoffPurpose transports whole condition identities; subset-cell and same-owner acceptance are unconnected, not new paper prohibitions. No numerical /2, Support, artifact closure or CMP-04 Ended mapping is invented. Public paths/independent controls are required for identification."),
    ("trace_at", "(trace: ObservationTrace, index: int) -> ObservationTrace",
     "A-EL-ROOT / P-10 (816-823,843,853,1002,1044): index is an exclusive event offset in the uncut input, not a model-step number. Return events[:index] and actual C/E at that same offset. Preserve the original complete history in origin for nested projections; reject an origin-bearing events-only cut or mixed ledger/clock. Strict-prefix clock is None (exact historical host reading unavailable). Raw inputs must carry complete append-only IO write/readback history; unlogged values are declared initial EL. A raw silently truncated history is not distinguishable from initial EL. publication_root adds the late-unlogged-preparation guard. Handmade histories are candidate checks, never identification passes."),
    ("publication_value", "(contract: ObservationE0, trace: ObservationTrace, unit: str, value: FrozenData) -> FrozenData",
     "A-PUBLISH-REF / INV-2.b (843,997-1000): project record recipes or their fields, not pending work descriptions (390). Expand Sources; keep exact PlanRef(unit,slot) for declared slots of this unit, independently resolve every other-unit record PlanRef to a Saved Point. Unknown local slot: ValueError; unavailable external slot: UnresolvedDeclaration. Compare the complete expanded E0/EU records AND work descriptions before this projection. No local reference is thereby Saved; preparation and storage still require full Point/codec/semantic checks."),
    ("types", "PublicType / PUBLIC_SHAPES / DECLARATION_SHAPES / ObservationE0 / ObservationTrace",
     "Frozen public types and exact schemas in the observation-contract section; MDeclRef = MPoint | MPlanRef | MSource is declaration-only. Actual Record references and Header parents are Points."),
    ("assumptions", "OBSERVATION_ASSUMPTIONS: tuple[(A-id, full text, F-b line range)]",
     "Body-free complete named observation assumptions; F-a 60/64/66 applies to A-CLOCK-WIRE, A-READING-NS and A-CLOCK-SOURCE."),
    ("clock_evidence_reading", "(contract: ObservationE0, trace: ObservationTrace, point: MPoint, *, acquisition: MAcquisition | None = None) -> Reading",
     "F-a 60/64/66; F-b 1511. Saved Event clock_reading/1 {source:Point, reading:Reading}; source is a Saved Event model.clock_source/1 {run, source} matching reading.run/source. A-READING-NS alone maps rank to time_ns and retains run. Other wires: UnresolvedDeclaration; invalid wire/Saved/source: ValueError. Optional acquisition compares the actual reading. No real-time precision claim."),
    ("completed_clock_reading", "(contract: ObservationE0, trace: ObservationTrace, point: MPoint, request: MPoint, field: Literal['started_clock', 'finished_clock']) -> Reading",
     "INV-6.a / PATH-COMPLETE (358,1031,1084): canonical Saved clock/source + independently reconstructed E0 Source(field,work) slot + actual EW/EH generation for the same request, Wr-start or Wp-finish. Equal clocks alone do not identify a generator. Missing linkage: UnresolvedDeclaration; incorrect link/value: ValueError. Does not certify numerical R/P correctness."),
    ("declaration_value", "(contract: ObservationE0, trace: ObservationTrace, value: FrozenData) -> FrozenData",
     "Expand PlanRef and A-SOURCE independently at the supplied history root using E0/EH/EW/EP/EA/EL. EP supplies name/at/salt only. Unknown input: UnresolvedDeclaration. first_receipt, generation, outcome, acquisition, numerical_view, started_clock, finished_clock, acquisition_clock, outcome_kind, outcome_content, terminal_basis, terminal_view are the complete Source list. Worker generation sources reject host Unknown. Basis is full Unknown content / validated Failure Generation / None for definite replies. terminal_view uses Saved C/E at Publish, requiring A-EL-ROOT history."),
    ("declaration_reference_contract", "() -> str",
     "MDeclRef applies only to E0 RecordPlan.references[*].ref and parents. Source must independently resolve to Point before comparison; unresolved input is not a pass."),
    ("CheckReport", "CheckReport(rows, human, complete, contract_violations=(), unconnected_observations=())",
     "45-row denominator; counts separates violations / independently identified / unidentified. connection_counts separates absent contract / boundary violations / connected partial judgment. H-01..06 remain human-unchecked; connection is not completeness or a pass."),
    ("Checker", "Checker(); on_state(StateObservation); on_step(StepObservation); on_graph(GraphObservation); report() -> CheckReport",
     "Incremental checker over all frozen states/edges, full enabled operations and graph. Public observation dataclasses are declared at the start of this file; no window success flags are normative."),
    ("start_references_ready", "(contract: ObservationE0, trace: ObservationTrace, descriptor: MDescriptor, resolutions: tuple[tuple[MPlanRef, MPoint], ...]) -> bool",
     "C-02 / INV-2.e, START-0..3 (390,572,583,834-846,1062): reference conjunct only. At one frozen state require actual EL Saved AND each required PlanRef's existing resolution to equal the independent E0/codec Point. A resolvable but unresolved declaration is not a resolved work description. Neither ReadBack/CloseSave nor a completed flag replaces the mapping; mapping presence alone cannot establish Saved or correct identity. No operation list is consulted. Permissions/use closure and actor health remain separate predicates; handmade controls do not establish independent discrimination."),
    ("check_exploration", "(scenario, graph) -> CheckReport",
     "Offline adapter: evaluate every state and edge, plus graph progress. Cut/frontier/untested scopes remain limitations."),
    ("evaluate_observations", "(contract: ObservationE0, trace: ObservationTrace) -> ObservationEvaluation",
     "Frozen complete history and ledger at one root; boundary errors, clauses and limitations are distinct. This public observation evaluation alone does not cover all state/graph rows."),
    ("evaluate_observation_step", "(contract, before, after, edge_events, *, before_state=None, after_state=None, action=None) -> ObservationEvaluation",
     "Frozen one-step trace/state correspondence. Supply actual before/after states for ownership/edge checks; absent state is unconnected, never implied success."),
    ("acyclic", "(parents: Mapping[Hashable, Iterable[Hashable]]) -> bool",
     "INV-5.c: finite symbolic child-to-parent graph, including pre-acceptance candidates; does not require counterfeit cyclic CIDs. Handmade positive/negative inputs do not establish independent discrimination."),
    ("reference_paths", "(value: object, path: tuple[str | int, ...]) -> tuple[tuple[tuple[str | int, ...], object], ...]",
     "A-REFERENCE-PATH: expand '*' only across the explicitly named tuple array to concrete zero-based indices. No implicit field discovery."),
    ("fair_cycle", "(nodes: Iterable[int], candidate_edges: GraphEdges, full_enabled: EnabledByState) -> bool",
     "SC-19 (1451-1469): action-specific weak fairness; retain the complete base graph's enabled operations, not only candidate edges."),
    ("progress_counterexamples", "(nodes, edges: GraphEdges, full_enabled: EnabledByState, frontier=()) -> tuple[frozenset[int], ...]",
     "ONE target's independent undischarged/environment-ready nodes. Fair recurrent SCCs and true terminal counterexamples; frontier is not a dead end. Requires a complete base graph for a verdict."),
    ("derive_progress", "(unpublished, ready, pending, discharged, edges: GraphEdges, full_enabled: EnabledByState, *, environment_ready, complete=True, frontier=()) -> dict[str, tuple[frozenset[int], ...]] | None",
     "SC-19 N/P (1451-1469), ONE fixed obligation. ReadyN is an independent frozen predicate, never inferred from offered operations; StableN is temporal recurrence within ready. full_enabled comes from the complete base graph including omitted exits. Incomplete/frontier returns None. Abstract negative inputs are not correct-window passes; neither positive nor negative candidates establish real reachability or independent discrimination."),
    ("resolve_receipt_source", "(contract: ObservationE0, trace: ObservationTrace, source: ReceiptSource) -> tuple[MEnvelope, SlotKey]",
     "SC-08 (616-620): full declared EH selector, unique actual Post, independent receipt slot; no predicted number/r/receipt_seq. This identity alone does not prove Saved."),
    ("resolve_derivation_binding", "(contract: ObservationE0, trace: ObservationTrace, binding: DerivationBinding) -> DerivationBinding",
     "Predeclared delta/EH correspondence and logical receipt aliases; resolve PlanRefs independently, never select a plan from EU."),
    ("derive_observation_status", "(contract: ObservationE0, trace: ObservationTrace) -> tuple[DerivationStatus, ...]",
     "Compute declared delta's eligibility/discharge from frozen E0/EH/EL observations; missing correspondence is not eligibility."),
    ("resolve_interval_evidence", "(contract: ObservationE0, trace: ObservationTrace, binding: IntervalEvidenceBinding) -> IntervalEvidenceBinding",
     "EI (739,746-747,1334): reconstruct declared evidence plan/Point with E0 + EP fresh fields + A-CODEC. Contract-specific Support remains unsupported."),
    ("resolve_artifact_port", "(contract: ObservationE0, trace: ObservationTrace, work: str, *, checked: bool = False) -> ArtifactPortBinding",
     "Finite artifact inputs/return declarations at this boundary (1089-1092). Issuance does not require future Draw/check evidence. Full semantic closure and F-a legality remain outside this structural model."),
)


@dataclass(frozen=True, slots=True)
class BoundaryViolation:
    path: str
    message: str
    paper: Paper
    classification: str = "約束違反"


@dataclass(frozen=True, slots=True)
class BoundaryReport:
    connection: str
    violations: tuple[BoundaryViolation, ...]


def _shape_errors(value, expected, path):
    """Validate types all the way to leaves; bool is not an integer here.

    Annotated public types are exact frozen STRUCTURAL shapes. No value's
    methods, serializers, type annotations, or window predicates are invoked.
    """
    origin, args = get_origin(expected), get_args(expected)
    if origin is Annotated:
        marker = args[1]
        if marker == "frozen-data":
            if value is None or type(value) in (str, bytes, int, bool):
                return []
            if type(value) is float:
                return [] if isfinite(value) else [f"{path}: non-finite model number"]
            if isinstance(value, Enum):
                return _shape_errors(value.value, FrozenData, path)
            if type(value) in (tuple, frozenset):
                return [e for i, child in enumerate(value)
                        for e in _shape_errors(child, FrozenData, f"{path}[{i}]")]
            if type(value).__name__ in PUBLIC_SHAPES:
                return _shape_errors(value, _public(type(value).__name__), path)
            return [f"{path}: undeclared/mutable data leaf {type(value).__name__}"]
        name = marker.name
        if (type(value).__name__ != name or not is_dataclass(value)
                or not type(value).__dataclass_params__.frozen):
            return [f"{path}: expected frozen public {name}"]
        shape = (DECLARATION_SHAPES[name] if marker.context == "declaration" else
                 dict(PUBLIC_SHAPES[name], ref=MPoint) if marker.context == "materialized" else PUBLIC_SHAPES[name])
        if {f.name for f in fields(value)} != set(shape):
            return [f"{path}: public {name} fields differ from the declared shape"]
        errors = [e for field, schema in shape.items()
                  for e in _shape_errors(getattr(value, field), schema, f"{path}.{field}")]
        if not errors and name == "Object":
            keys = [k for k, _ in value.items]
            if len(set(keys)) != len(keys) or keys != sorted(keys):
                errors.append(f"{path}: Object keys must be unique and canonical")
        return errors
    if origin in (Union, UnionType):
        alternatives = [_shape_errors(value, option, path) for option in args]
        return [] if any(not errors for errors in alternatives) else [f"{path}: no declared union branch matches"]
    if origin is Literal:
        literal = value.value if isinstance(value, Enum) else value
        return [] if any(type(literal) is type(a) and literal == a for a in args) else [f"{path}: unsupported literal {literal!r}"]
    if origin in (tuple, frozenset):
        if type(value) is not origin:
            return [f"{path}: expected immutable {origin.__name__}"]
        if origin is frozenset or len(args) == 2 and args[1] is Ellipsis:
            return [e for i, child in enumerate(value)
                    for e in _shape_errors(child, args[0], f"{path}[{i}]")]
        if len(value) != len(args):
            return [f"{path}: tuple arity differs"]
        return [e for i, (child, schema) in enumerate(zip(value, args))
                for e in _shape_errors(child, schema, f"{path}[{i}]")]
    if expected is ObservationEvent:
        if type(value) is not ObservationEvent:
            return [f"{path}: expected ObservationEvent, not legacy Fact/Effect"]
        tag = TAG_BY_NAME.get(value.tag) if type(value.tag) is str else None
        if tag is None:
            return [f"{path}.tag: undeclared observation tag"]
        return (_shape_errors(value.key, tag.key_type, f"{path}.key")
                + _shape_errors(value.value, tag.value_type, f"{path}.value"))
    if isinstance(expected, type) and is_dataclass(expected):
        if type(value) is not expected:
            return [f"{path}: expected {expected.__name__}"]
        return [e for field, schema in get_type_hints(expected, include_extras=True).items()
                for e in _shape_errors(getattr(value, field), schema, f"{path}.{field}")]
    if expected in (str, int, bytes, bool, float, type(None)):
        return [] if type(value) is expected else [f"{path}: expected {expected.__name__}"]
    # Never accept plain object as an untyped escape hatch.
    return [f"{path}: undeclared schema {expected!r}"]


def validate_observation_boundary(contract, trace, edge_events=None):
    """Public target for the explorer. Missing transport != malformed transport.

    No downstream predicate runs on a malformed trace. Type correctness does
    not imply any invariant, completeness, or successful identification.
    """
    if contract is None and trace is None and edge_events is None:
        return BoundaryReport("約束の未接続", ())
    root = Paper(("E0", "EH/EW/EP/EL/EU/EA/EI"), (816, 823))
    violations = []
    for name, value, schema in (("E0.observation_contract", contract, ObservationE0),
                                ("evidence.observation_trace", trace, ObservationTrace)):
        if value is not None:
            violations.extend(BoundaryViolation(name, message, root)
                              for message in _shape_errors(value, schema, name))
    if edge_events is not None:
        violations.extend(BoundaryViolation("edge.actual_events", message, root)
                          for message in _shape_errors(edge_events, tuple[ObservationEvent, ...], "edge.actual_events"))
    if violations:
        return BoundaryReport("約束違反", tuple(violations))
    if contract is None or trace is None:
        return BoundaryReport("約束の未接続", ())

    def require(ok, path, message, paper=root):
        if not ok:
            violations.append(BoundaryViolation(path, message, paper))

    if trace.origin is not None:
        require(trace.origin.writes == _el_writes(trace.origin.events), "trace.origin.writes",
                "historical write index differs from the complete actual history")
        try:
            trace_at(trace, len(trace.events))
        except UnresolvedDeclaration as error:
            require(False, "trace.origin", str(error))
        if violations:
            return BoundaryReport("約束違反", tuple(violations))

    layouts = contract.receipt_layouts
    require(Counter(r.kind for r in layouts) == Counter(RECEIPT_TYPES), "E0.receipt_layouts",
            "all five receipt kinds must be declared exactly once", Paper(("I-1..8",), (463, 467)))
    for layout in layouts:
        require(tuple((name, version) for _, name, version in layout.slots)
                == tuple(receipt_contracts(layout.kind)), "E0.receipt_layouts",
                "paper contract/version/count mismatch; Boot requires both slots", Paper(("I-6",), (463, 467)))
        require(len({slot for slot, _, _ in layout.slots}) == len(layout.slots), "E0.receipt_layouts", "duplicate slot")
    for name, pairs in (("capacity", contract.capacity), ("allocation", contract.allocation)):
        require(len({key for key, _ in pairs}) == len(pairs) and all(n >= 0 for _, n in pairs),
                f"E0.{name}", "resource declarations require unique keys and nonnegative integer amounts")
    for name, values, keys in (
        ("plans", contract.plans, [p.unit for p in contract.plans]),
        ("descriptors", contract.descriptors, [d.work_id for d in contract.descriptors]),
        ("completions", contract.completions, [c.key for c in contract.completions]),
        ("acquisitions", contract.acquisitions, [c.key for c in contract.acquisitions]),
        ("verifications", contract.verifications, [c.key for c in contract.verifications]),
        ("adoptions", contract.adoptions, [c.key for c in contract.adoptions]),
        ("intervals", contract.intervals, [c.key for c in contract.intervals]),
        ("receipt_sources", contract.receipt_sources, [c.unit for c in contract.receipt_sources]),
        ("artifacts", contract.artifacts, [c.work for c in contract.artifacts]),
    ):
        require(len(set(keys)) == len(values), f"E0.{name}", "duplicate declaration key")
    for binding in contract.completions:
        require(binding.key.obligation in OBLIGATION_TYPES, "E0.completions", "undeclared O-ID",
                Paper(("C-O01..14",), (1185, 1185)))
        require(binding.key.kind != "save" or bool(binding.slots), "E0.completions", "save conclusion requires concrete slots")
        source_type = {"Post": ReceiptKey, "Publish": UnitKey, "EndKnown": WorkKey,
                       "Acquire": IntentKey, "IntervalRequest": IntervalKey, "Reserve": WorkToken}[binding.trigger]
        require(type(binding.source) is source_type, "E0.completions", "trigger/source key type mismatch")
    for binding in contract.derivations:
        layout = next((r for r in layouts if r.kind == binding.envelope.event.kind), None)
        require(layout is not None and binding.envelope.event.kind == "Received"
                and binding.receipt.slot in {slot for slot, _, _ in layout.slots},
                "E0.derivations", "delta source must name a declared Received slot")
        if isinstance(binding.envelope, ReceiptSource):
            source = binding.envelope
            require(source in contract.receipt_sources and binding.receipt == SlotKey(source.unit, source.slot),
                    "E0.derivations", "receipt selector must be independently declared and match the logical receipt slot")
        if (binding.method.name, binding.method.version) == ("finite_update", "2"):
            require(bool(binding.unsupported), "E0.derivations", "/2 numerical projection cannot be silently supplied by a finite fixture",
                    Paper(("PATH-QOBS", "RIGHT-APPLY"), (1081, 1149)))
    for source in contract.receipt_sources:
        layout = next((r for r in layouts if r.kind == source.event.kind), None)
        require(source.unit not in {p.unit for p in contract.plans} and layout is not None
                and source.slot in {s for s, _, _ in layout.slots}, "E0.receipt_sources",
                "receipt alias collides with a plan or names an undeclared receipt slot")
    for binding in contract.interval_evidence:
        if _type(binding.record, "RecordPlan"):
            require(_type(binding.point, "PlanRef") and binding.point.slot == binding.record.slot,
                    "E0.interval_evidence", "a planned evidence record needs its exact unit/slot PlanRef")
    for rule in contract.references:
        if rule.path_id == "PATH-QOBS":
            require(rule.closure == "unsupported", "E0.references", "PATH-QOBS full closure is explicitly unsupported",
                    Paper(("PATH-QOBS",), (1081, 1081)))
    # Matching the key and value is a boundary obligation, not a window success.
    for i, event in enumerate(trace.events + (() if edge_events is None else edge_events)):
        tag, key, value = event.tag, event.key, event.value
        paper = TAG_BY_NAME[tag].paper
        path = f"events[{i}]/{tag}"
        if tag in ("Post", "Present", "Accept", "HostAck"):
            env = value.envelope
            require((key.run, key.number) == (env.run, env.number), path, "receipt key does not match full envelope", paper)
            require(env.run == env.r.run and env.number == env.receipt_seq, path, "Post run/number/sequence contract mismatch", paper)
            if tag == "Accept":
                require(env.event.kind in RECEIPT_TYPES, path, "Accept event kind is outside the declared receipt shapes", paper)
        if tag in ("Reserve", "ReadInputs"):
            require(key.work == value.descriptor.work_id, path, "work key/descriptor mismatch", paper)
        if tag == "WorkerReturn":
            require(key.work == value.generation.work, path, "work key/generation mismatch", paper)
        if tag == "HostUnknown":
            outcome = _get(value.envelope.event.fields, "outcome")
            require(value.envelope.event.kind in ("WorkFinished", "DrawReturned")
                    and _get(value.envelope.event.fields, "work") == key.work
                    and _type(outcome, "Outcome") and outcome.kind == "Unknown", path,
                    "host Unknown must carry the full same-work Unknown notice", paper)
        if tag == "Publish":
            require(key.unit == value.plan.unit, path, "unit key/actual promise mismatch", paper)
        if tag == "Acquire":
            require((key.reader, key.intent) == (value.acquisition.reader, value.acquisition.intent), path, "acquisition key mismatch", paper)
        if tag in ("ReserveAdoption", "ReleaseAdoption", "Adopt"):
            require(_type(key.reader, "Point"), path, "actual adoption reader must be resolved; only E0 may retain a PlanRef", paper)
        if tag == "VerifyCall":
            require(key.work == value.call.work, path, "verification call key mismatch", paper)
        if tag in ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "ReportGenerated", "MeasurementEnded"):
            require(value.evidence is None or _type(value.evidence, "Point"), path,
                    "actual EI evidence must be a Point; only E0 may retain PlanRef", paper)
        if tag == "ArtifactChecked":
            require(_type(value.request, "Point") and all(p is None or _type(p, "Point") for p in (value.problem, value.draw))
                    and all(_type(p, "Point") for p in value.evidence), path,
                    "actual artifact check must use resolved Points", paper)
        if tag == "IntervalUndertaken":
            request = value.request
            require((key.request, key.route, key.run) == (request.id, request.route_epoch, request.interval.run),
                    path, "undertaking key differs from the full request", paper)
            require(value.owner.location in ("H", "P.work"), path,
                    "interval undertaking requires a host or requesting-work owner (629)", paper)
        if tag in ("Reserve", "Release"):
            require(all(n >= 0 for _, n in value.resources)
                    and len({r for r, _ in value.resources}) == len(value.resources), path, "invalid resource vector", paper)
    return BoundaryReport("約束違反" if violations else "約束接続・部分判定", tuple(violations))


def model_seal(payload: bytes, salt: bytes, codec=CodecDeclaration()):
    """A-CODEC. Independent, length framed, domain separated MODEL definition.

    Paper 462 requires a declared seal relation; it does not specify this hash.
    No imported _seal, no window-provided digest/callback, no success bits.
    """
    if type(payload) is not bytes or type(salt) is not bytes or codec != CodecDeclaration():
        raise ValueError("unsupported model codec or non-byte seal input")
    framed = (b"fb-check-seal/1\0" + len(salt).to_bytes(8, "big") + salt
              + len(payload).to_bytes(8, "big") + payload)
    return sha256(framed).hexdigest()


def _wire_struct(type_name, **values):
    return {"type": type_name, "fields": values}


def _wire_object(values):
    return _wire_struct("Object", items=[[key, value] for key, value in sorted(values.items())])


def receipt_unit(envelope):
    # A-RECEIPT: injective tuple encoding rather than ambiguous string joining.
    return "receipt/" + _encode((envelope.run, envelope.number)).hex()


def receipt_record_wire(contract, envelope, created, slot):
    """Complete expected Record MODEL image from E0 + original EH + real clock.

    PATH-RECEIPT deliberately keeps the raw Event. Unknown inner names are not
    resolved. Concrete packing/names/routes/parents are A-RECEIPT, not real DTOs.
    """
    layout = next(r for r in contract.receipt_layouts if r.kind == envelope.event.kind)
    _, name, version = next(s for s in layout.slots if s[0] == slot)
    record_contract = _wire_struct("Contract", name=name, version=version)
    content = _wire_object({
        "writer": "MEMBRANE", "route": layout.route, "contract": record_contract,
        "content": _wire(envelope.event), "caused_by": None, "source_id": None,
        "source_time_ns": None, "received_ns": _wire(envelope.r),
    })
    return _wire_struct("Record", name=receipt_unit(envelope) + "/" + slot, at=_wire(created),
                        contract=record_contract, category="Event", content=content, references=[])


def receipt_plan_wire(contract, envelope, created, slot):
    record = receipt_record_wire(contract, envelope, created, slot)["fields"]
    layout = next(r for r in contract.receipt_layouts if r.kind == envelope.event.kind)
    return _wire_struct("RecordPlan", slot=slot, contract=record["contract"], category=record["category"],
                        content=record["content"], references=[], parents=_wire(layout.parents), at=_wire(created))


def prepared_consistent(prepared, codec):
    return (prepared.payload == _encode(prepared.record)
            and prepared.seal == model_seal(prepared.payload, prepared.salt, codec)
            and prepared.header.record == prepared.record
            and prepared.header.seal == prepared.seal
            and prepared.header.parents == prepared.parents
            and prepared.point.cid == _hash(prepared.header))


def ledger_saved(point, trace, codec):
    """Saved is a recomputation over actual C/E bytes, not a presence test."""
    entries = [e for e in trace.entries if e.point == point]
    if len(entries) != 1:
        return False
    entry = entries[0]
    bodies = [b for b in trace.bodies if b.seal == entry.header.seal]
    return (len(bodies) == 1 and point.cid == _hash(entry.header)
            and bodies[0].payload == _encode(entry.header.record)
            and bodies[0].seal == model_seal(bodies[0].payload, bodies[0].salt, codec))


class UnresolvedDeclaration(ValueError):
    """Missing/unsupported independent input; never use EU as a fallback."""


def _el_writes(events):
    first_seen = {}
    for i, event in enumerate(events):
        value = (event.value.written if event.tag == "IOResponse" else
                 event.value.value if event.tag == "ReadBack" else None)
        if _type(value, "Body") or _type(value, "Entry"):
            first_seen.setdefault(value, i)
    return tuple((i, value) for value, i in first_seen.items())


def _el_at(origin, index):
    later = {value for i, value in origin.writes if i >= index}
    return origin.bodies - later, origin.entries - later


def trace_at(trace: ObservationTrace, index: int) -> ObservationTrace:
    """A-EL-ROOT / P-10: one coherent historical snapshot, events[:index].

    index is an exclusive event offset (not an action/step number). Paper
    816-823,843,853,1002,1044 requires the actual evidence at the judgment root.
    Project actual IO writes/readbacks and retain the *uncut* origin so nested
    projections cannot turn a later write into an initial-ledger value. Unknown
    historical clock is None, never the final clock or a guessed Post rank.
    No other field of ObservationTrace is silently copied from the future.

    Raw input promises complete append-only history: unlogged EL is supplied
    initial EL (A-EL-ROOT). Without origin a secretly truncated raw history is
    indistinguishable from initial EL. Origin-bearing mixed snapshots raise
    UnresolvedDeclaration; they are not repaired into apparently valid input.
    """
    if type(index) is not int or not 0 <= index <= len(trace.events):
        raise UnresolvedDeclaration("historical trace offset outside supplied history")
    origin = trace.origin
    if origin is None:
        origin = ObservationOrigin(trace.events, trace.bodies, trace.entries, trace.clock, _el_writes(trace.events))
    else:
        size = len(trace.events)
        bodies, entries = _el_at(origin, size)
        clock = origin.clock if size == len(origin.events) else None
        if (trace.events != origin.events[:size] or trace.bodies != bodies
                or trace.entries != entries or trace.clock != clock):
            raise UnresolvedDeclaration("historical trace mixes event prefix with another ledger/clock root")
    bodies, entries = _el_at(origin, index)
    clock = origin.clock if index == len(origin.events) else None
    return ObservationTrace(origin.events[:index], bodies, entries, clock, origin)


def publication_root(trace: ObservationTrace, index: int) -> ObservationTrace:
    """trace_at plus the A-EL-ROOT ambiguous-initial-ledger guard (1044).

    A later FirstPrepare without actual IO history cannot justify an earlier
    Saved publication view. Inspect the uncut origin, including on nested calls.
    An events-only cut retaining origin is rejected by trace_at. A raw input
    lacking that provenance must satisfy the complete-history input contract;
    there is no observation that distinguishes silently removed IO from initial
    EL. Never borrow EU's view to fill that information gap.
    """
    root = trace_at(trace, index)
    origin = root.origin
    written = {value for _, value in origin.writes}
    prior = {e.value.prepared.point for e in origin.events[:index] if e.tag == "FirstPrepare"}
    for event in origin.events[index:]:
        if event.tag == "FirstPrepare" and event.value.prepared.point not in prior:
            if any(e.point == event.value.prepared.point and e not in written for e in root.entries):
                raise UnresolvedDeclaration("historical EL root lacks actual write history for a later preparation")
    return root


def _uses_terminal_view(value):
    if _type(value, "Source"):
        return value.kind == "terminal_view"
    if is_dataclass(value):
        return any(_uses_terminal_view(getattr(value, f.name)) for f in fields(value))
    return isinstance(value, (tuple, frozenset)) and any(_uses_terminal_view(v) for v in value)


def resolve_receipt_source(contract: ObservationE0, trace: ObservationTrace,
                           source: ReceiptSource) -> tuple[MEnvelope, SlotKey]:
    """Resolve a predeclared selector from actual EH Post, never from Q/EU.

    Public SC-08 (616-620,1363). Returns the complete observed Envelope and the
    independently computed A-RECEIPT unit/slot. Zero or multiple matching Posts
    raise UnresolvedDeclaration; neither case invents an acceptance number.
    Returned identity does not itself prove that the receipt is Saved.
    """
    if source not in contract.receipt_sources:
        raise UnresolvedDeclaration("undeclared EH receipt selector")
    matches = {e.value.envelope for e in trace.events if e.tag == "Post"
               and e.value.envelope.source == source.source and e.value.envelope.event == source.event
               and (source.run is None or e.value.envelope.run == source.run)}
    if len(matches) != 1:
        raise UnresolvedDeclaration("EH receipt selector needs one actual full original: " + source.unit)
    envelope = next(iter(matches))
    return envelope, SlotKey(receipt_unit(envelope), source.slot)


def _map_frozen(value, leaf):
    replacement = leaf(value)
    if replacement is not value:
        return replacement
    if is_dataclass(value):
        return replace(value, **{f.name: _map_frozen(getattr(value, f.name), leaf) for f in fields(value)})
    if isinstance(value, tuple):
        return tuple(_map_frozen(v, leaf) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_map_frozen(v, leaf) for v in value)
    return value


class DeclarationResolver:
    """REF-5/E0-02 (998,1062), SAVE-3..7 (1311-1315), A-CODEC.

    Reconstruct from E0/EH/EW/EP/EA, never a P resolution table or EU payload.
    EP contributes the fresh name, creation reading and salt fixed at preparation
    (these cannot be predicted by E0). Everything else is recomputed from the
    declared plan. Edges separately check the actual creation reading. No Point
    exists for an unsaved/unprepared slot. Source expansion is frozen at Publish.
    """

    def __init__(self, contract, trace):
        self.contract, self.trace = contract, trace
        self.firsts = {}
        for event in trace.events:
            if event.tag == "FirstPrepare":
                self.firsts.setdefault(event.key, event.value.prepared)
        self.active = set()
        self.points = {}

    def sources(self, value):
        return _map_frozen(value, lambda v: self.source(v) if _type(v, "Source") else v)

    def resolve(self, value):
        return _map_frozen(value, lambda v: self.point(SlotKey(v.unit, v.slot)) if _type(v, "PlanRef") else v)

    def publication(self, value, unit):
        slots = {r.slot for p in self.contract.plans if p.unit == unit for r in p.records}

        def reference(ref):
            if not _type(ref, "PlanRef"):
                return ref
            if ref.unit != unit:
                return self.point(SlotKey(ref.unit, ref.slot))
            if ref.slot not in slots:
                raise ValueError("publication names an undeclared same-unit slot: " + repr(ref))
            return ref

        return _map_frozen(self.sources(value), reference)

    def plan(self, unit):
        plan = next((p for p in self.contract.plans if p.unit == unit), None)
        if plan is None:
            raise UnresolvedDeclaration("no E0 plan for " + unit)
        evaluation = plan.obligation_id == 'O-G' and any(g.kind == 'evaluation' for g in plan.guards)
        if not _has_source(plan) and not evaluation:
            return plan
        # The EU event determines WHEN to take the root, never WHAT is expected.
        index = next((i for i, e in enumerate(self.trace.events) if e.tag == "Publish" and e.key.unit == unit), None)
        root = (publication_root(self.trace, index) if index is not None and _uses_terminal_view(plan) else
                trace_at(self.trace, index) if index is not None else self.trace)
        resolver = self if index is None else DeclarationResolver(self.contract, root)
        expanded = resolver.sources(plan)
        if evaluation:
            # 1935: the EQ's actual usable evaluation inputs are fixed at PUB.
            # Its Ep descriptor keeps the public E0 recipe, including EQ's ref.
            expanded = replace(expanded, records=resolver.publication(expanded.records, unit))
        # Source is a declaration recipe, not permission to put a clock/value
        # or an unresolved token in a reference/parent position (REF-5).
        for record in plan.records:
            for ref in tuple(r.ref for r in record.references) + tuple(record.parents):
                if _type(ref, "Source") and not _type(resolver.source(ref), "Point"):
                    raise UnresolvedDeclaration("declared reference/parent Source did not resolve to a Point: " + repr(ref))
        return expanded

    def expected_preparation(self, key):
        first = self.firsts.get(key)
        if first is None:
            raise UnresolvedDeclaration("slot has no actual first preparation: " + repr(key))
        acceptance = next((e.value for e in self.trace.events if e.tag == "Accept" and e.value.unit == key.unit), None)
        if acceptance is not None:
            layout = next(r for r in self.contract.receipt_layouts if r.kind == acceptance.envelope.event.kind)
            if key.slot not in {s for s, _, _ in layout.slots}:
                raise UnresolvedDeclaration("undeclared receipt slot: " + repr(key))
            wire = receipt_record_wire(self.contract, acceptance.envelope, acceptance.created, key.slot)
            if _wire(first.record) != wire:
                raise UnresolvedDeclaration("receipt preparation disagrees with full EH original: " + repr(key))
            record, parents = first.record, layout.parents
        else:
            plan = self.plan(key.unit)
            slot = next((r for r in plan.records if r.slot == key.slot), None)
            if slot is None:
                raise UnresolvedDeclaration("undeclared E0 slot: " + repr(key))
            slot = self.resolve(slot)
            record = replace(first.record, at=slot.at if slot.at is not None else first.record.at,
                             contract=slot.contract, category=slot.category, content=slot.content, references=slot.references)
            parents = slot.parents
        payload = _encode(record)
        seal = model_seal(payload, first.salt, self.contract.codec)
        header = replace(first.header, record=record, seal=seal, parents=parents)
        point = replace(first.point, cid=_hash(header))
        return replace(first, record=record, parents=parents, payload=payload, seal=seal, header=header, point=point)

    def point(self, key):
        if key in self.points:
            return self.points[key]
        if key in self.active:
            raise UnresolvedDeclaration("cyclic/unresolved E0 slot: " + repr(key))
        self.active.add(key)
        try:
            source = next((s for s in self.contract.receipt_sources if (s.unit, s.slot) == (key.unit, key.slot)), None)
            if source is not None:
                _, actual = resolve_receipt_source(self.contract, self.trace, source)
                point = self.point(actual)
                self.points[key] = point
                return point
            expected = self.expected_preparation(key)
            if expected != self.firsts[key] or not ledger_saved(expected.point, self.trace, self.contract.codec):
                raise UnresolvedDeclaration("slot plan/preparation/Saved content mismatch: " + repr(key))
            self.points[key] = expected.point
            return expected.point
        finally:
            self.active.remove(key)

    def source(self, source):
        marker = ("Source", source.kind, source.key)
        if marker in self.active:
            raise UnresolvedDeclaration("cyclic Source: " + repr(source))
        self.active.add(marker)
        try:
            if source.kind in ("candidate_declaration", "first_receipt", "generation", "outcome", "started_clock", "finished_clock",
                               "outcome_kind", "outcome_content", "terminal_basis", "terminal_view"):
                known = observed_end_known(self.contract, self.trace, source.key, resolver=self)
                if known is None:
                    raise UnresolvedDeclaration("Source requires independently established EndKnown: " + repr(source))
                envelope, generation = known
                outcome = _get(envelope.event.fields, "outcome")
                if source.kind == 'candidate_declaration':
                    if outcome.kind != 'Success' or _get(outcome.content, 'variant') != 'Candidates':
                        raise UnresolvedDeclaration('CG Source lacks a nonempty-generation reply')
                    return self.resolve(_get(outcome.content, 'declaration'))
                if source.kind == "outcome":
                    return outcome
                if source.kind == "outcome_kind":
                    return outcome.kind
                if source.kind == "outcome_content":
                    return outcome.content
                if source.kind == "terminal_view":
                    return frozenset(e.point for e in self.trace.entries if ledger_saved(e.point, self.trace, self.contract.codec))
                if source.kind == "terminal_basis":
                    return outcome.content if outcome.kind == "Unknown" else generation if outcome.kind == "Failure" else None
                if source.kind in ("generation", "started_clock", "finished_clock"):
                    if not _type(generation, "Generation"):
                        raise UnresolvedDeclaration("host Unknown is not a worker generation")
                    return (generation if source.kind == "generation" else generation.started
                            if source.kind == "started_clock" else generation.finished)
                acceptance = next(e.value for e in self.trace.events if e.tag == "Accept" and e.value.envelope == envelope)
                layout = next(r for r in self.contract.receipt_layouts if r.kind == envelope.event.kind)
                if len(layout.slots) != 1:
                    raise UnresolvedDeclaration("first receipt Source has no unique declared slot")
                return self.point(SlotKey(acceptance.unit, layout.slots[0][0]))
            if source.kind in ("acquisition", "acquisition_clock"):
                actual = {e.value.acquisition for e in self.trace.events if e.tag == "Acquire" and e.key.intent == source.key}
                if len(actual) != 1:
                    raise UnresolvedDeclaration("Source lacks a unique actual acquisition before Publish")
                acquisition = next(iter(actual))
                return acquisition.reading if source.kind == "acquisition_clock" else acquisition
            if source.kind == "numerical_view":
                descriptor = next((d for d in self.contract.descriptors if d.work_id == source.key), None)
                if descriptor is None:
                    raise UnresolvedDeclaration("Source lacks an E0 descriptor")
                return self.resolve(descriptor.numerical_view)
            raise UnresolvedDeclaration("未対応: undeclared Source kind " + source.kind)
        finally:
            self.active.remove(marker)


def publication_value(contract: ObservationE0, trace: ObservationTrace, unit: str, value: FrozenData) -> FrozenData:
    """A-PUBLISH-REF / INV-2.b (843,997-1000): publication-root projection.

    Same-unit PlanRefs keep their exact declared unit/slot identity, including
    unprepared clock slots. Other-unit PlanRefs require independent Saved Point
    resolution; missing input raises UnresolvedDeclaration. An undeclared local
    slot raises ValueError. The full Source-expanded E0/EU recipes must still
    compare exactly, so substitution of two equal-content local slots is wrong.
    Project record recipes or their fields only. Pending work descriptions are
    compared in full but their required inputs resolve at START (390), not here.
    Retaining a PlanRef does not assert Saved. FirstPrepare / Saved-G / Cq checks
    later resolve all Points and compare the full recipe, bytes and provenance.
    G's local clock recipe reading can be compared to actual EA at Publish;
    its Saved clock/source Points are required at storage, not invented here.
    Public signature and contract are also in PUBLIC_CHECK_CONTRACTS.
    """
    return DeclarationResolver(contract, trace).publication(value, unit)


def declaration_value(contract: ObservationE0, trace: ObservationTrace, value: FrozenData) -> FrozenData:
    """Public independent PlanRef/Source expansion at the supplied history root.

    REF-5/E0-02/05 (998,1001,1062), A-SOURCE. Sources: first_receipt,
    generation, outcome, acquisition, numerical_view, started_clock,
    finished_clock, acquisition_clock, outcome_kind, outcome_content,
    terminal_basis, terminal_view. Work clock sources return that validated
    Generation's Reading/Unavailable (never delivery r or record s). They are
    clock VALUES, not evidence Points: predeclare separate clock-evidence slots
    and refer to them with PlanRef when the saved contract requires a Point.
    Unknown/ambiguous/missing input raises UnresolvedDeclaration, never zero or
    an empty dependency. Use the publication/call root, not a later snapshot.
    Environment must separately implement any recipe used by executable scenes.

    acquisition_clock names an intent and projects the unique actual Acquire's
    reading; before acquisition it is Unresolved. Terminal projections require
    EndKnown: kind/content keep the full first Outcome; basis keeps Unknown's
    whole content or Failure's validated generation, otherwise None. A-T-UNKNOWN
    adds no Generation carrier to Unknown's original content (v0.12, 1510).
    terminal_view is the recomputed Saved set in this root's C/E (769,1044), not
    a chosen input set or EU's claim. Historical roots require A-EL-ROOT history.
    """
    resolver = DeclarationResolver(contract, trace)
    return resolver.resolve(resolver.sources(value))


def resolve_derivation_binding(contract: ObservationE0, trace: ObservationTrace,
                               binding: DerivationBinding) -> DerivationBinding:
    """Public SC-08 declaration -> actual EH/EL correspondence (616-620).

    Does not mutate E0 or select a plan from EU. Resolves predeclared receipt
    aliases and PlanRefs at trace's root; keeps the predeclared plan as a recipe.
    Missing Post/Saved input raises UnresolvedDeclaration, not eligibility.
    Use derive_observation_status for eligibility/Match_delta/Discharge_delta.
    """
    envelope, receipt = binding.envelope, binding.receipt
    if isinstance(envelope, ReceiptSource):
        if receipt != SlotKey(envelope.unit, envelope.slot):
            raise UnresolvedDeclaration("derivation receipt differs from its declared selector")
        envelope, receipt = resolve_receipt_source(contract, trace, envelope)
    resolver = DeclarationResolver(contract, trace)
    names = ("declaration", "process", "reader", "inputs", "evidence", "root", "previous_result")
    return replace(binding, envelope=envelope, receipt=receipt,
                   **{name: resolver.resolve(getattr(binding, name)) for name in names})


def resolve_interval_evidence(contract: ObservationE0, trace: ObservationTrace,
                              binding: IntervalEvidenceBinding) -> IntervalEvidenceBinding:
    """Public planned EI evidence -> concrete saved Record (739,746-747,1334).

    Resolve its Point with E0 + EP fresh values + A-CODEC, then compare the
    binding's exact RecordPlan to E0 before constructing the expected Record.
    No field is copied from the observed EI evidence record as the expectation.
    Does not infer Support, certified cells, or evidence outside a fixed X.
    Raises UnresolvedDeclaration for missing/incorrect plan or Saved content.
    """
    resolver = DeclarationResolver(contract, trace)
    point = resolver.resolve(binding.point)
    record = binding.record
    if _type(record, "RecordPlan"):
        if not _type(binding.point, "PlanRef"):
            raise UnresolvedDeclaration("planned EI evidence needs a PlanRef")
        unit, slot = binding.point.unit, binding.point.slot
        plan = next((p for p in contract.plans if p.unit == unit), None)
        expected = next((r for r in plan.records if r.slot == slot), None) if plan else None
        if expected != record:
            raise UnresolvedDeclaration("EI evidence recipe differs from its E0 unit/slot")
        record = resolver.expected_preparation(SlotKey(unit, slot)).record
    else:
        record = declaration_value(contract, trace, record)
    return replace(binding, point=point, record=record, event=resolver.resolve(binding.event))


def resolve_artifact_port(contract: ObservationE0, trace: ObservationTrace, work: str,
                          *, checked: bool = False) -> ArtifactPortBinding:
    """Public finite artifact port expectations at issue/check time (1089-1092).

    Only resolves fields used at THIS boundary: issuance must not demand future
    Draw/evidence referenced by checked_returns. No returned ArtifactValue or
    ArtifactChecked is an input to this resolver. Real F-a validity/full closure
    remain unsupported; a finite port table is not a certificate of IE/ID.
    """
    binding = next((b for b in contract.artifacts if b.work == work), None)
    if binding is None:
        raise UnresolvedDeclaration("no independently declared artifact port for " + work)
    names = ("checked_returns",) if checked else ("inputs", "possible_returns")
    return replace(binding, **{name: declaration_value(contract, trace, getattr(binding, name)) for name in names})


def bind_interval_declarations(contract, e0):
    """E0-02/REF-5: bridge old transport which omitted nonmaterialized k.

    Read only raw E0 IntervalRequest/endpoints, not its conversion implementation.
    Supplied bindings are retained (and compared below), never silently repaired.
    """
    if not isinstance(contract, ObservationE0):
        return contract
    existing = {b.key for b in contract.intervals}
    missing = tuple(IntervalBinding(IntervalKey(r.id, r.route_epoch, r.interval.run), r.point,
                                   r.work, r.interval, e0.endpoints, r.measurement_contract, r.clock_contract)
                    for r in e0.intervals if IntervalKey(r.id, r.route_epoch, r.interval.run) not in existing)
    return replace(contract, intervals=contract.intervals + missing) if missing else contract


def acquisition_record_points(contract, trace, key, acquisition):
    """PATH-ACQUIRE (1085,1093), C-O08 (1216-1217): second, Saved-G stage.

    Population comes from E0 content_acquired slots, not Acquired.record claims.
    Bytes, CID, full plan and actual origin/targets/clock must all agree.
    """
    resolver = DeclarationResolver(contract, trace)
    record_ref = acquisition_record_reference(contract, trace, key)
    if record_ref is None:
        return frozenset()  # matching contents alone do not identify the intent
    try:
        expected_point = resolver.resolve(record_ref)
    except UnresolvedDeclaration:
        return frozenset()
    result = set()
    for plan in contract.plans:
        for record in plan.records:
            if (record.contract.name, record.contract.version) != ("content_acquired", "1"):
                continue
            try:
                point = resolver.point(SlotKey(plan.unit, record.slot))
            except UnresolvedDeclaration:
                continue
            if point != expected_point:
                continue
            entry = next(e for e in trace.entries if e.point == point)
            if _acquisition_content_matches(contract, trace, entry.header.record.content, acquisition):
                result.add(point)
    return frozenset(result)


def acquisition_record_reference(contract, trace, key):
    """Independent intent -> G declaration, never inferred from observed G."""
    resolver = DeclarationResolver(contract, trace)
    bindings = []
    for binding in contract.acquisitions:
        try:
            binding_key = resolver.resolve(binding.key)
        except UnresolvedDeclaration:
            continue
        if binding_key == key:
            bindings.append(binding)
    return bindings[0].record if len(bindings) == 1 else None


def clock_evidence_reading(contract: ObservationE0, trace: ObservationTrace, point: MPoint,
                           *, acquisition: MAcquisition | None = None):
    """A-CLOCK-WIRE. F-a 60/64/66; F-b 1031-1032,1084-1085,1511.

    Exact model wire: Saved Event clock_reading/1 {source: Point, reading: Reading}.
    source must point to a Saved Event model.clock_source/1 {run: str, source: str}
    whose run/source equal reading.run/source (A-CLOCK-SOURCE). A-READING-NS is
    the sole conversion: {run: reading.run, time_ns: reading.rank}; Reading.source
    identifies the source, without a physical-clock precision claim. Record.at
    and notification r never substitute for reading. Unavailable is not a reading.
    Other contracts raise UnresolvedDeclaration; malformed data/missing Saved
    records raise ValueError. The optional acquisition checks its actual reading;
    Cq generation correspondence is checked by completed_clock_reading, not by
    reading equality alone. See PUBLIC_CHECK_CONTRACTS without reading this body.
    """
    if not _type(point, "Point") or not ledger_saved(point, trace, contract.codec):
        raise ValueError("clock must reference a Saved record")
    record = next(e.header.record for e in trace.entries if e.point == point)
    if record.category != "Event":
        raise ValueError("clock evidence must be an Event")
    shape = (record.contract.name, record.contract.version)
    if shape != ("clock_reading", "1"):
        raise UnresolvedDeclaration("unsupported clock evidence wire: " + repr(shape))
    source, reading = _get(record.content, "source"), _get(record.content, "reading")
    if (set(k for k, _ in record.content.items) != {"source", "reading"}
            or _shape_errors(reading, MReading, "clock.reading")):
        raise ValueError("invalid clock_reading/1 wire: require source and Reading")
    if not _type(source, "Point") or not ledger_saved(source, trace, contract.codec):
        raise ValueError("clock source must reference a Saved record")
    origin = next(e.header.record for e in trace.entries if e.point == source)
    if ((origin.contract.name, origin.contract.version, origin.category) != ("model.clock_source", "1", "Event")
            or set(k for k, _ in origin.content.items) != {"run", "source"}
            or (_get(origin.content, "run"), _get(origin.content, "source")) != (reading.run, reading.source)):
        raise ValueError("clock source differs from reading.run/source (A-CLOCK-SOURCE)")
    if acquisition is not None and reading != acquisition.reading:
        raise ValueError("clock reading differs from actual acquisition")
    return reading


def completed_clock_reading(contract: ObservationE0, trace: ObservationTrace, point: MPoint,
                            request: MPoint, field: Literal["started_clock", "finished_clock"]):
    """INV-6.a / PATH-COMPLETE (358,1031,1084), structural generation link.

    Require the canonical Saved clock and source, an independently reconstructed
    E0 clock slot with Source(field, work), and that work's validated EW/EH first
    generation for this request at Wr (start) or Wp (finish). EP supplies only
    name/at/salt. Equal readings from another request/stage do not suffice.
    Missing E0/EP/EW/EH linkage is UnresolvedDeclaration, a wrong link/value is
    ValueError. This does not certify the numerical R/P result or its F-a wire.
    """
    reading = clock_evidence_reading(contract, trace, point)
    if field not in ("started_clock", "finished_clock"):
        raise ValueError("unknown Cq clock field")
    resolver = DeclarationResolver(contract, trace)
    keys = {e.key for e in trace.events if e.tag == "FirstPrepare" and e.value.prepared.point == point}
    if len(keys) != 1:
        raise UnresolvedDeclaration("Cq clock needs a unique E0/EP slot and Wr-start/Wp-finish provenance (1031,1084)")
    key = next(iter(keys))
    plan = next((r for u in contract.plans if u.unit == key.unit for r in u.records if r.slot == key.slot), None)
    source = _get(plan.content, "reading") if plan is not None else None
    if not _type(source, "Source"):
        raise UnresolvedDeclaration("Cq clock E0 reading lacks an explicit work Source (1031,1084)")
    if source.kind != field:
        raise ValueError("Cq clock Source names another generation boundary")
    known = observed_end_known(contract, trace, source.key, resolver=resolver)
    if known is None or not _type(known[1], "Generation"):
        raise UnresolvedDeclaration("Cq clock lacks validated worker EW/EH generation (1031,1084)")
    generation = known[1]
    if (generation.request, generation.stage) != (request, "Wr" if field == "started_clock" else "Wp"):
        raise ValueError("Cq clock generation belongs to another request/stage")
    expected = generation.started if field == "started_clock" else generation.finished
    if reading != expected:
        raise ValueError("Cq clock reading differs from corresponding Wr-start/Wp-finish")
    if resolver.expected_preparation(key) != resolver.firsts[key]:
        raise ValueError("Cq clock preparation differs from independent E0 Source recipe")
    return reading


def _acquisition_content_matches(contract, trace, content, acquisition):
    targets = _get(content, "contents")
    if not (isinstance(targets, (tuple, frozenset)) and len(targets) == len(acquisition.targets)
            and frozenset(targets) == acquisition.targets and _get(content, "origin") == acquisition.reader):
        return False
    try:
        return clock_evidence_reading(contract, trace, _get(content, "clock"), acquisition=acquisition) == acquisition.reading
    except UnresolvedDeclaration:
        raise
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ClauseResult:
    row: str
    satisfied: bool
    message: str
    target: object


@dataclass(frozen=True, slots=True)
class ObservationEvaluation:
    boundary: BoundaryReport
    clauses: tuple[ClauseResult, ...]
    limitations: tuple[tuple[str, str], ...]
    custody: tuple[CustodyJudgement, ...] = ()

    @property
    def violations(self):
        return tuple(c for c in self.clauses if not c.satisfied)


def _causal_ancestors(point, nodes):
    """EA's actual causal graph, NOT the visible set or window parent claims."""
    mapping = {n.point: n.parents for n in nodes}
    if len(mapping) != len(nodes) or point not in mapping or not acyclic(mapping):
        return None
    found, todo = set(), list(mapping[point])
    while todo:
        parent = todo.pop()
        if parent not in mapping:
            return None
        if parent not in found:
            found.add(parent)
            todo.extend(mapping[parent])
    return frozenset(found)


def completion_slots_saved(contract, trace, slots):
    """844/1189/1191: all independently named end slots, never CloseSave's list."""
    resolver = DeclarationResolver(contract, trace)
    try:
        return bool(slots) and all(ledger_saved(resolver.point(s), trace, contract.codec) for s in slots)
    except UnresolvedDeclaration:
        return False


def start_points_saved(contract, trace, descriptor):
    """855/1076-1086: before actual reservation AND body entry, regardless of action.

    This is the Saved conjunct only; unresolved permission/use closures remain
    limitations. Descriptor fields come from E0, not the observed worker copy.
    """
    if descriptor is None:
        return False
    resolver = DeclarationResolver(contract, trace)
    try:
        return all(ledger_saved(resolver.resolve(p), trace, contract.codec) for p in _points(descriptor))
    except UnresolvedDeclaration:
        return False


def start_references_ready(contract: ObservationE0, trace: ObservationTrace,
                           descriptor: MDescriptor,
                           resolutions: tuple[tuple[MPlanRef, MPoint], ...]) -> bool:
    """C-02: Saved facts AND the resolved description at this same state.

    Paper 572 defines Saved from C/E; 390,583,1062 separately require each
    pending PlanRef to have been resolved to its original plan's Saved Point.
    START-0..3 (834-846,1289-1292) need both. C/E commit alone cannot advance
    an unresolved description. Conversely, paper 302,1315-1316 separates
    ConfirmWrite/CloseSave from resolving a description: requiring those tags
    would incorrectly postpone Ready even after an independently valid mapping.

    The supplied mapping is a frozen observed value, NOT a correctness oracle:
    its keys come from E0 requirements and its values must equal independent
    E0/EP/codec reconstruction AND satisfy full EL Saved. Never use phase,
    completed/body_confirmed/entry_confirmed flags, or the enabled operations.
    Caller supplies trace and resolutions from the same state (no later map).
    Missing work rows remain in the E0 population; ownership/row existence is
    also checked by INV-2.a/b. This function does not assert resolution progress.
    """
    if not start_points_saved(contract, trace, descriptor):
        return False
    resolver = DeclarationResolver(contract, trace)
    try:
        for ref in set(_points(descriptor)):
            if _type(ref, "PlanRef"):
                actual = tuple(point for key, point in resolutions if key == ref)
                if len(actual) != 1 or actual[0] != resolver.resolve(ref):
                    return False
    except UnresolvedDeclaration:
        return False
    return True


def issued_evidence_clauses(contract, root, record, require, missing, target):
    """860/865/1045: check Xc and V at Publish, preparation and Saved roots.

    A publication is evidence of issuance, never the oracle for its content.
    Full V reply is read from EW/EA and the independently validated first receipt.
    CMP-22 compares full Generation (590/1137), excluding delivery metadata.
    Other comparison families/affected encodings remain explicit limitations.
    """
    name, content = record.contract.name, record.content
    if name == "sui.fb.verification_result":
        work = _get(content, "work")
        descriptor = next((d for d in contract.descriptors if d.work_id == work), None)
        first = observed_end_known(contract, root, work)
        reply = first[1].outcome.content if first is not None and _type(first[1], "Generation") else None
        require("INV-9.a", descriptor is not None and descriptor.stage == "Wv"
                and _type(reply, "VerificationReply") and _get(content, "reply") == reply,
                "V publication/preparation/Saved reply differs from full actual verification return", target)
        actual = [e.value.reply for e in root.events if e.tag == "VerifyReply" and e.key.work == work]
        if actual:
            require("INV-9.a", all(r == _get(content, "reply") for r in actual),
                    "V differs from actual EA verification reply", target)
        if first is not None:
            try:
                point = DeclarationResolver(contract, root).point(SlotKey(receipt_unit(first[0]), "receipt"))
                require("INV-9.a", _get(content, "first_receipt") == point,
                        "V refers to a different first receipt", target)
            except UnresolvedDeclaration as error:
                missing(("INV-9.a",), str(error))
    elif name == "sui.fb.conflict":
        refs = _get(content, "reports", frozenset())
        if not require("INV-7.a", isinstance(refs, (tuple, frozenset)) and len(set(refs)) >= 2
                       and all(ledger_saved(p, root, contract.codec) for p in refs),
                       "Xc issuance/preparation/Saved lacks two distinct Saved reports", target):
            return
        if _get(content, "rule") != "CMP-22":
            missing(("INV-7.a",), "Xc comparison family and independently derived affected mapping")
            return
        # Receipt wire + raw EH source/type/target correspondence, not Xc claims.
        witnesses = {}
        for event in root.events:
            if event.tag != "Accept":
                continue
            envelope = event.value.envelope
            if envelope.event.kind not in ("WorkFinished", "DrawReturned"):
                continue
            work = _get(envelope.event.fields, "work")
            descriptor = next((d for d in contract.descriptors if d.work_id == work), None)
            if descriptor is None or envelope.source != dict(contract.generation_sources).get(work):
                continue
            try:
                resolver = DeclarationResolver(contract, root)
                point = resolver.point(SlotKey(event.value.unit, "receipt"))
                request = resolver.resolve(descriptor.request)
            except UnresolvedDeclaration:
                continue
            if point not in refs:
                continue
            for returned in root.events:
                if returned.tag != "WorkerReturn" or returned.key.work != work:
                    continue
                g = returned.value.generation
                if (g.request, g.stage, g.provenance, g.outcome) != (request, descriptor.stage, envelope.source, _get(envelope.event.fields, "outcome")):
                    continue
                if envelope.event.kind == "WorkFinished" and (g.started, g.finished) != (_get(envelope.event.fields, "started"), _get(envelope.event.fields, "finished")):
                    continue
                if g.outcome.kind != "Unknown":
                    witnesses[point] = (work, g)
        pairs = [(a, b) for a in witnesses for b in witnesses if a != b
                 and witnesses[a][0] == witnesses[b][0] and witnesses[a][1] != witnesses[b][1]]
        require("INV-7.a", bool(pairs) and set(witnesses) == set(refs),
                "Xc CMP-22 has no full, source-corresponding incompatible report pair", target)
        missing(("INV-7.a",), "CMP-22 affected logical-key wire mapping remains unconnected")


def issued_evidence_at_root(contract, trace, publication, record, require, missing, target):
    """Route only V/Xc to their historical root; absent EL history is a limitation."""
    row = {"sui.fb.verification_result": "INV-9.a", "sui.fb.conflict": "INV-7.a"}.get(record.contract.name)
    if row is None:
        return
    try:
        root = publication_root(trace, publication) if publication is not None else trace
    except UnresolvedDeclaration as error:
        missing((row,), str(error))
        return
    issued_evidence_clauses(contract, root, record, require, missing, target)


def evaluate_observations(contract, trace):
    """Independent executable clauses for the 甲 portions of the ten GAPS.

    Unspecified semantics and still-unconnected clauses remain limitations.
    This returns clause checks, NOT a declaration that a whole row has passed.
    """
    boundary = validate_observation_boundary(contract, trace)
    if boundary.connection != "約束接続・部分判定":
        return ObservationEvaluation(boundary, (), ())
    trace = trace_at(trace, len(trace.events))
    clauses, limitations = [], set()

    def require(row, condition, message, target=None):
        clauses.append(ClauseResult(row, bool(condition), message, target))
        return bool(condition)

    def missing(rows, meaning):
        for row in rows:
            limitations.add((row, "約束の未接続: " + meaning))

    saved = lambda point: ledger_saved(point, trace, contract.codec)
    plans = {p.unit: p for p in contract.plans}
    descriptors = {d.work_id: d for d in contract.descriptors}
    capacity, allocation = dict(contract.capacity), dict(contract.allocation)
    sources = dict(contract.generation_sources)
    posts, accepts, prepared, requests = {}, {}, {}, {}
    reserves, wrappers, consumed, entered, stopped, releases, unknown = {}, {}, Counter(), Counter(), set(), set(), set()
    entry_readings, consumed_wrappers, release_attempts = {}, {}, Counter()
    acquisitions, calls, replies, certificates, adoption_reservations, adoption_heads = {}, {}, {}, {}, {}, {}
    verification_bindings = {}
    applied, artifacts, issued_units = defaultdict(list), {}, {}
    for resource in set(capacity) | set(allocation):
        require("INV-10.a", 0 <= allocation.get(resource, 0) <= capacity.get(resource, 0), "allocation exceeds capacity", resource)

    # Full EL integrity, even for entries that have never appeared in EP.
    for body in trace.bodies:
        require("INV-4.a", body.seal == model_seal(body.payload, body.salt, contract.codec), "EL body seal does not match actual payload/salt", body.seal)
    for entry in trace.entries:
        require("INV-4.a", saved(entry.point), "EL Saved recomputation failed", entry.point)
        preparation = next((e for e in trace.events if e.tag == "FirstPrepare" and e.value.prepared.point == entry.point), None)
        publication = next((i for i, e in enumerate(trace.events) if preparation is not None
                            and e.tag == "Publish" and e.key.unit == preparation.key.unit), None)
        issued_evidence_at_root(contract, trace, publication, entry.header.record, require, missing, entry.point)
        for parent in entry.header.parents:
            parent_entries = [e for e in trace.entries if e.point == parent]
            require("INV-5.c", saved(parent) and len(parent_entries) == 1
                    and parent_entries[0].header.record.category == "Event", "parent must be a Saved allowed Event, not Prediction", entry.point)
    require("INV-5.c", acyclic({e.point: e.header.parents for e in trace.entries}), "EL parent cycle")

    for index, event in enumerate(trace.events):
        tag, key, value = event.tag, event.key, event.value
        target = (index, key)
        # Direct Saved/byte checks must use the same historical root as the
        # declaration resolver. Otherwise a late save can validate an early use.
        seen = trace_at(trace, index + 1)
        saved = lambda point: ledger_saved(point, seen, contract.codec)
        if tag == "Post":
            envelope = value.envelope
            require("INV-1.b", key not in posts or posts[key] == envelope, "Post changed an immutable original", key)
            same_run = [e for e in posts.values() if e.run == envelope.run]
            if key not in posts and same_run:
                last = max(same_run, key=lambda e: e.receipt_seq)
                require("INV-15.a", envelope.receipt_seq > last.receipt_seq
                        and envelope.r.source == last.r.source and envelope.r.rank >= last.r.rank,
                        "Post order is not monotone within its run/clock", key)
            posts.setdefault(key, envelope)
        elif tag in ("Present", "HostAck", "Accept"):
            require("INV-1.b", posts.get(key) == value.envelope, "EH operation does not match original full envelope", key)
            if tag == "HostAck":
                require("INV-1.a", key in accepts and accepts[key].envelope == value.envelope, "HostAck precedes custody of the complete receipt", key)
            if tag == "Accept":
                envelope = value.envelope
                prior = [ReceiptKey(e.run, e.number) for e in posts.values()
                         if e.run == envelope.run and (e.r.rank, e.receipt_seq) < (envelope.r.rank, envelope.receipt_seq)]
                require("INV-15.a", all(p in accepts for p in prior), "Accept skipped an earlier Post", key)
                require("INV-1.b", key not in accepts or accepts[key] == value, "reaccept changed original/created/plans", key)
                require("INV-1.b", value.created.run == envelope.run and value.created.source == envelope.r.source
                        and envelope.r.rank <= value.created.rank, "receipt r/s/run/clock mismatch", key)
                layout = next((r for r in contract.receipt_layouts if r.kind == envelope.event.kind), None)
                if layout is None:
                    missing(("INV-1.b",), "outer event shape is outside the five declared receipt kinds")
                else:
                    expected = [receipt_plan_wire(contract, envelope, value.created, slot) for slot, _, _ in layout.slots]
                    require("INV-1.c", len(value.plans) == len(expected), "wrong number of receipt slots, including Boot", key)
                    require("INV-1.b", value.unit == receipt_unit(envelope)
                            and [_wire(p) for p in value.plans] == expected, "full receipt conversion differs from E0/EH", key)
                accepts.setdefault(key, value)
        elif tag == "Reserve":
            descriptor = descriptors.get(key.work)
            require("INV-5.b", start_points_saved(contract, trace_at(trace, index), descriptor),
                    "actual reservation precedes required Saved Points/permissions", target)
            require("INV-3.c", descriptor is not None and value.descriptor == descriptor, "reservation lacks the normative work descriptor", target)
            require("INV-10.a", descriptor is not None and value.resources == descriptor.need, "reservation differs from independent Need", target)
            require("INV-3.c", key not in reserves and not any(k.work == key.work for k in reserves), "work reserves twice or changes token on retry", target)
            reserves[key] = value.resources
        elif tag == "Launch":
            require("INV-3.c", key in reserves and key not in releases, "launch has no retained reservation", target)
            require("INV-3.b", not entered[key] and key not in unknown, "launch restarts an entered/uncertain body", target)
            wrappers.setdefault(key, set()).add(value.wrapper)
        elif tag == "LaunchResponse":
            require("INV-3.b", value.wrapper in wrappers.get(key, set()), "launch reply has no actual wrapper", target)
            if value.response == "unknown":
                unknown.add(key)
            elif require("INV-3.b", not entered[key] and not consumed[key], "not-entered reply contradicts actual token/entry", target):
                unknown.discard(key)
                wrappers.get(key, set()).discard(value.wrapper)
        elif tag == "ConsumeToken":
            require("INV-3.a", key in reserves and key not in releases and value.wrapper in wrappers.get(key, set()), "token consumed without actual reservation/wrapper", target)
            consumed[key] += 1
            consumed_wrappers.setdefault(key, value.wrapper)
            require("INV-3.a", consumed[key] == 1 and sum(n for k, n in consumed.items() if k.work == key.work) == 1, "token/work consumed more than once", target)
            require("INV-3.b", key not in unknown, "uncertain start retried", target)
        elif tag == "EnterBody":
            require("INV-5.b", start_points_saved(contract, trace_at(trace, index), descriptors.get(key.work)),
                    "actual body entry precedes required Saved Points/permissions", target)
            entered[key] += 1
            require("INV-3.a", consumed[key] == 1 and entered[key] == 1
                    and value.wrapper in wrappers.get(key, set())
                    and value.wrapper == consumed_wrappers.get(key) and key not in unknown
                    and sum(n for k, n in entered.items() if k.work == key.work) == 1,
                    "body entered without its one token, or entered twice", target)
            entry_readings.setdefault(key, value.started)
        elif tag == "ReadInputs":
            descriptor = descriptors.get(key.work)
            require("INV-8.b", entered[key] == 1 and descriptor is not None, "actual input read lacks normative entered work", target)
            if descriptor is not None:
                resolution = {ref: point for ref, point in value.resolutions}
                require("INV-3.b", len(resolution) == len(value.resolutions), "duplicate resolution key", target)
                resolver = DeclarationResolver(contract, trace_at(trace, index))
                try:
                    expected_resolution = {ref: resolver.resolve(ref) for ref in _points(descriptor) if _type(ref, "PlanRef")}
                    require("INV-3.b", resolution == expected_resolution, "PlanRef resolutions differ from E0 plan/codec/Saved recomputation", target)
                    expected = resolver.resolve(descriptor)
                    require("INV-8.b", value.descriptor == expected and value.numerical_view == expected.numerical_view,
                            "actual descriptor/numerical input differs from E0 fixed values", target)
                    require("INV-8.b", all(_type(p, "Point") and saved(p) for p in expected.input_points), "actual input includes unresolved/unsaved Points", target)
                except UnresolvedDeclaration as error:
                    require("INV-8.b", False, "actual read used an unresolved or mismatching declared dependency: " + str(error), target)
        elif tag == "WorkerReturn":
            descriptor = descriptors.get(key.work)
            g = value.generation
            require("INV-15.a", entered[key] == 1 and descriptor is not None, "return without the corresponding actual body", target)
            if descriptor is not None:
                request = descriptor.request
                try:
                    request = DeclarationResolver(contract, trace_at(trace, index)).resolve(request)
                except UnresolvedDeclaration as error:
                    missing(("INV-15.a",), str(error))
                require("INV-15.a", (g.request, g.stage) == (request, descriptor.stage)
                        and sources.get(key.work) == g.provenance, "generation request/stage/provenance mismatch", target)
                require("INV-6.a", g.started == entry_readings.get(key), "generation started clock differs from actual entry", target)
                if _type(g.started, "Reading") and _type(g.finished, "Reading"):
                    require("INV-6.a", g.started.run == g.finished.run and g.started.source == g.finished.source
                            and g.started.rank <= g.finished.rank, "generation clock order/source differs", target)
        elif tag == "HostUnknown":
            require("INV-15.a", _host_unknown_matches(contract, trace, index, event),
                    "host Unknown lacks declared source/request/stage/basis and actual preceding witnesses", key)
            # Deliberately does not add to stopped, releases, or worker returns.
        elif tag == "Stop":
            require("INV-10.b", key in reserves, "stop has no work reservation", target)
            stopped.add(key)
        elif tag == "Release":
            release_attempts[key] += 1
            require("INV-3.c", release_attempts[key] <= 1, "same actual holding released more than once", target)
            require("INV-10.b", key in stopped and key not in releases and reserves.get(key) == value.resources,
                    "release requires actual Stop and the same still-held reservation exactly once", target)
            # Illegal release must not manufacture free capacity.
            if key in stopped and key not in releases and reserves.get(key) == value.resources:
                releases.add(key)
        elif tag == "FirstPrepare":
            first = value.prepared
            publication = next((i for i, e in enumerate(trace.events[:index]) if e.tag == "Publish" and e.key.unit == key.unit), None)
            issued_evidence_at_root(contract, trace_at(trace, index + 1), publication, first.record, require, missing, key)
            require("INV-4.c", prepared_consistent(first, contract.codec), "first preparation's complete codec linkage is wrong", key)
            require("INV-4.c", key not in prepared or prepared[key] == first, "first preparation changed fixed values", key)
            receipt = next((a for a in accepts.values() if a.unit == key.unit), None)
            if receipt is not None:
                layout = next(r for r in contract.receipt_layouts if r.kind == receipt.envelope.event.kind)
                if require("INV-4.c", key.slot in {s for s, _, _ in layout.slots}, "undeclared receipt slot", key):
                    require("INV-4.c", _wire(first.record) == receipt_record_wire(contract, receipt.envelope, receipt.created, key.slot),
                            "self-consistent first preparation disagrees with raw EH receipt", key)
                require("INV-4.c", first.parents == layout.parents, "receipt parents differ from declared finite layout", key)
            elif key.unit in plans:
                require("INV-4.c", any(r.slot == key.slot for r in plans[key.unit].records), "prepared undeclared slot", key)
                resolver = DeclarationResolver(contract, trace_at(trace, index + 1))
                try:
                    expected = resolver.expected_preparation(key)
                    require("INV-4.c", first == expected, "first preparation differs from independent permitted plan/codec", key)
                except UnresolvedDeclaration as error:
                    missing(("INV-4.c",), str(error))
            else:
                missing(("INV-4.c",), "no E0/EH normative preparation plan for slot " + repr(key))
            prepared.setdefault(key, first)
        elif tag == "IORequest":
            require("INV-4.c", prepared.get(key.slot) == value.prepared, "I/O replaced the first PreparedEntry", target)
            require("INV-4.a", prepared_consistent(value.prepared, contract.codec), "I/O submitted invalid seal/header/CID", target)
            require("INV-4.c", key not in requests or requests[key] == value.prepared, "same I/O identity changed bytes", target)
            requests.setdefault(key, value.prepared)
        elif tag in ("IOResponse", "ReadBack"):
            first = requests.get(key)
            require("INV-4.c", first is not None, "I/O result lacks matching actual request", target)
            actual = value.written if tag == "IOResponse" else value.value
            if actual is not None and first is not None:
                is_body = key.operation in ("PutBody", "ReadBody")
                require("INV-4.a", (is_body and _type(actual, "Body") and actual.seal == first.seal
                                    and actual.salt == first.salt and actual.payload == first.payload)
                        or (not is_body and _type(actual, "Entry") and actual.point == first.point and actual.header == first.header),
                        "I/O result matches neither the full body nor the full entry requested", target)
                require("INV-4.a", actual in (seen.bodies if is_body else seen.entries), "reported actual I/O bytes absent from EL", target)
            # Acknowledged alone never establishes Saved; lost may have committed.
        elif tag == "Publish":
            for record in value.plan.records:
                issued_evidence_at_root(contract, trace, index, record, require, missing, key)
            if key.unit not in plans:
                require("INV-2.b", False, "actual publication has no independent E0 promise", key)
            else:
                try:
                    root = (publication_root(trace, index) if _uses_terminal_view(plans[key.unit]) else
                            trace_at(trace, index))
                    resolver = DeclarationResolver(contract, root)
                    expected = resolver.plan(key.unit)
                    require("INV-2.b", expected == value.plan, "actual publication differs from independently expanded E0 promise", key)
                    records = resolver.publication(expected.records, key.unit)
                    for record in records:
                        if (record.contract.name, record.contract.version) == ("content_acquired", "1"):
                            content = record.content
                            clock = _get(content, "clock")
                            if _type(clock, "PlanRef"):
                                # Only declared same-unit refs survive publication().
                                # EA already exists; the future clock's CID does not.
                                clock_plan = next(r for r in records if r.slot == clock.slot)
                                matches = lambda a: ((clock_plan.contract.name, clock_plan.contract.version, clock_plan.category) == ("clock_reading", "1", "Event")
                                    and _get(clock_plan.content, "reading") == a.reading
                                    and _get(content, "origin") == a.reader
                                    and isinstance(_get(content, "contents"), (tuple, frozenset))
                                    and len(_get(content, "contents")) == len(a.targets)
                                    and frozenset(_get(content, "contents")) == a.targets)
                            else:
                                matches = lambda a: _acquisition_content_matches(contract, root, content, a)
                            require("INV-2.b", any(matches(a.acquisition) for a in acquisitions.values()),
                                    "G publication precedes the corresponding actual acquisition", key)
                except UnresolvedDeclaration as error:
                    missing(("INV-2.b",), str(error))
                except ValueError as error:
                    require("INV-2.b", False, str(error), key)
            require("INV-2.b", key not in issued_units or issued_units[key] == value.plan, "publication changed the already-fixed promise", key)
            issued_units.setdefault(key, value.plan)  # retain even illegal promises
        elif tag == "Acquire":
            require("INV-6.c", key not in acquisitions, "same reader/intent acquired twice instead of a distinct intended acquisition", key)
            resolver = DeclarationResolver(contract, trace_at(trace, index))
            bindings = []
            for declared in contract.acquisitions:
                try:
                    # G is deliberately excluded: it does not exist at acquisition.
                    bindings.append(replace(declared, key=resolver.resolve(declared.key), targets=resolver.resolve(declared.targets),
                                            completion=resolver.resolve(declared.completion), required_ancestors=resolver.resolve(declared.required_ancestors)))
                except UnresolvedDeclaration as error:
                    missing(("INV-9.a",), str(error))
            binding = next((b for b in bindings if b.key == key), None)
            a = value.acquisition
            require("INV-9.a", binding is not None and a.targets == binding.targets, "actual acquisition differs from declared intent targets", key)
            require("INV-9.a", len(dict(a.contents)) == len(a.contents) and set(dict(a.contents)) == set(a.targets), "acquisition contents do not cover targets exactly", key)
            for point, payload in a.contents:
                entries = [e for e in seen.entries if e.point == point]
                require("INV-9.a", saved(point) and point in a.view and len(entries) == 1
                        and payload == _encode(entries[0].header.record), "acquired bytes/view do not match the actual Saved record", point)
            if binding is not None:
                require("INV-9.a", binding.required_ancestors <= a.ancestors, "actual acquisition lacks required ancestors", key)
            require("INV-9.a", key not in acquisitions or acquisitions[key].acquisition == a, "same acquisition intent changed actual contents/clock/view", key)
            acquisitions.setdefault(key, value)
            if binding is not None and binding.record is None:
                missing(("INV-9.a",), "E0 acquisition intent -> G slot declaration (PATH-LINK-ACQUISITION)")
            elif value.record is not None:
                try:
                    require("INV-9.a", value.record in acquisition_record_points(contract, seen, key, a),
                            "claimed G does not match declared plan and actual origin/contents/clock", key)
                except UnresolvedDeclaration as error:
                    missing(("INV-9.a",), str(error))
        elif tag == "VerifyCall":
            require("INV-9.a", key not in calls or calls[key] == value.call, "verification call identity changed", key)
            descriptor = descriptors.get(key.work)
            binding = next((b for b in contract.verifications if b.key == key), None)
            resolver = DeclarationResolver(contract, trace_at(trace, index))
            if binding is None:
                missing(("INV-9.a",), "full normative verification call binding")
            else:
                try:
                    binding = resolver.resolve(resolver.sources(binding))
                except UnresolvedDeclaration as error:
                    require("INV-9.a", False, "verification used an unresolved E0 declaration: " + str(error), key)
                else:
                    require("INV-9.a", (value.call.target, value.call.input_read, value.call.check_view, value.call.arguments)
                            == (binding.target, binding.numerical_view, binding.check_view, binding.arguments),
                            "verification call differs from independently declared target/input/check view/arguments", key)
                    # E0-04 (1002): reply uses THIS call's fixed normative root.
                    verification_bindings.setdefault(key, binding)
            try:
                inputs = resolver.resolve(descriptor.numerical_view) if descriptor is not None else None
                arguments = resolver.resolve(resolver.sources(descriptor.args)) if descriptor is not None else None
            except UnresolvedDeclaration as error:
                require("INV-8.a", False, "verification descriptor cannot resolve at call: " + str(error), key)
            else:
                require("INV-8.a", descriptor is not None and descriptor.stage == "Wv"
                        and value.call.input_read == inputs and value.call.arguments == arguments,
                        "verification did not read the fixed normative inputs/arguments", key)
            calls.setdefault(key, value.call)
        elif tag == "CertificateIssued":
            require("INV-9.a", key in calls, "issued certificate lacks actual matching call", key)
            certificates[key] = value.certificate
        elif tag == "VerifyReply":
            call, reply = calls.get(key), value.reply
            require("INV-9.a", call is not None and (reply.target, reply.numerical_view, reply.check_view)
                    == (call.target, call.input_read, call.check_view), "reply target/input/check view differs from actual call", key)
            require("INV-9.a", key not in replies or replies[key] == reply, "definite verification reply changed", key)
            binding = verification_bindings.get(key)
            if binding is not None:
                names = ("target", "reader", "numerical_view", "evidence_closure", "check_view", "registry", "checker")
                require("INV-9.a", all(getattr(reply, n) == getattr(binding, n) for n in names),
                        "actual verification reply differs from E0 target/reader/closure/registry/checker", key)
                target = binding.target
                points = {target.request, target.result, target.completion, *target.proofs}
                require("INV-9.a", set(dict(reply.target_contents)) == points
                        and len(dict(reply.target_contents)) == len(reply.target_contents), "verification target contents omit/add/duplicate a target", key)
                entries = {e.point: e for e in seen.entries}
                require("INV-9.a", all(saved(p) and content == _encode(entries[p].header.record)
                                        for p, content in reply.target_contents), "verification target bytes differ from EL", key)
                require("INV-9.a", points <= reply.check_view and reply.evidence_closure <= reply.check_view
                        and all(saved(p) for p in reply.check_view), "verification view/closure contains missing or unsaved evidence", key)
            if reply.response == "Success":
                certificate = certificates.get(key)
                require("INV-9.a", certificate is not None and reply.certificate == certificate, "success reply has no independently issued matching certificate", key)
                if certificate is not None:
                    names = ("target", "reader", "target_contents", "numerical_view", "evidence_closure", "check_view", "registry", "checker")
                    require("INV-9.a", all(getattr(certificate, n) == getattr(reply, n) for n in names)
                            and certificate.result_digest == _hash(reply.result), "certificate binding/content/digest differs from actual reply", key)
            replies.setdefault(key, reply)
        elif tag == "ReserveAdoption":
            require("INV-9.b", key.reader not in adoption_reservations, "reader has more than one live adoption reservation", key)
            try:
                binding = resolved_adoption_binding(contract, trace_at(trace, index), key)
            except UnresolvedDeclaration as error:
                require("INV-9.b", False, "adoption reservation cannot resolve its declaration: " + str(error), key)
            else:
                require("INV-9.b", binding is not None and value.completion == binding.completion,
                        "adoption reservation differs from the declared reader/intent/completion", key)
            adoption_reservations[key.reader] = (key, value.completion)
        elif tag == "ReleaseAdoption":
            require("INV-9.b", adoption_reservations.get(key.reader) == (key, value.completion), "adoption reservation release mismatches the intent", key)
            adoption_reservations.pop(key.reader, None)
        elif tag == "Adopt":
            try:
                binding = resolved_adoption_binding(contract, trace_at(trace, index), key)
            except UnresolvedDeclaration as error:
                binding = None
                require("INV-9.a", False, "adoption cannot resolve its E0 declaration: " + str(error), key)
            require("INV-9.a", binding is not None, "adoption has no E0 intent", key)
            require("INV-9.b", adoption_reservations.get(key.reader) == (key, value.completion), "adoption lacks reader reservation", key)
            if binding is not None:
                require("INV-9.a", (value.completion, value.result, value.previous_result, value.verification, value.acquisitions)
                        == (binding.completion, binding.result, binding.previous_result, binding.verification, binding.acquisitions),
                        "adoption differs from full E0 intent", key)
            ancestors = _causal_ancestors(value.record, value.causal_dag)
            require("INV-9.a", ancestors is not None and ancestors == value.actual_ancestors,
                    "actual ancestry is not the closure of the transported causal DAG", key)
            for acquisition_key in value.acquisitions:
                if acquisition_key not in acquisitions:
                    require("INV-9.a", False, "adoption lacks its actual acquisition", acquisition_key)
                elif acquisition_record_reference(contract, seen, acquisition_key) is None:
                    missing(("INV-9.a",), "E0 intent -> G slot needed to check adoption's actual acquisition ancestor")
                else:
                    try:
                        require("INV-9.a", bool(acquisition_record_points(contract, seen, acquisition_key, acquisitions[acquisition_key].acquisition)
                                                & value.actual_ancestors),
                                "visible acquisition is not an actual ancestor of adoption", key)
                    except UnresolvedDeclaration as error:
                        missing(("INV-9.a",), str(error))
            reply = replies.get(value.verification)
            require("INV-9.a", reply is not None and reply.response == "Success" and reply.certificate is not None
                    and reply.certificate == certificates.get(value.verification)
                    and reply.reader == key.reader and reply.target.completion == value.completion
                    and reply.target.result == value.result, "adoption lacks corresponding actual successful verification", key)
            require("INV-9.a", value.previous == adoption_heads.get(key.reader), "adoption previous belongs to another reader/old head", key)
            require("INV-9.a", all(saved(p) for p in value.actual_ancestors), "actual ancestor is not Saved", key)
            adoption_heads[key.reader] = value.record
        elif tag == "Apply":
            candidates = [b for b in contract.applications if (b.key, b.contract, b.report_meaning, b.binding)
                          == (key, value.contract, value.report_meaning, value.binding)]
            if not candidates or any(b.unsupported for b in candidates):
                missing(("INV-6.b", "INV-6.c", "INV-7.a"), "RIGHT-APPLY finite projection absent/explicitly unsupported")
            else:
                require("INV-6.b", len(candidates) == 1, "ambiguous finite application declaration", key)
                binding = candidates[0]
                names = ("transition_key", "kernel", "outcomes", "measurements", "input_digest")
                require("INV-6.b", all(getattr(value, n) == getattr(binding, n) for n in names), "application is not the independently declared projection", key)
                if value.purpose == "new_application":
                    for previous in applied[key]:
                        require("INV-6.b", previous.transition_key != value.transition_key
                                and not (previous.measurements & value.measurements), "repeated transition/overlapping measurement in the same reader/model/series", key)
                    applied[key].append(value)
                elif value.purpose == "no_op":
                    require("INV-6.b", any(p.transition_key == value.transition_key and p.input_digest == value.input_digest
                                          for p in applied[key]), "no-op does not repeat an already applied identical input", key)
        elif tag == "CloseSave":
            binding = next((b for b in contract.completions if b.key == key), None)
            if binding is not None and binding.trigger == "EndKnown":
                require("INV-2.c", completion_slots_saved(contract, seen, binding.slots),
                        "end save closed before every independently required record is Saved", key)
            require("INV-2.a", binding is not None and key.kind == "save" and binding.slots == value.slots,
                    "CloseSave changes condition identity/target or omits required slots", key)
            require("INV-4.c", bool(value.slots) and all(s in prepared and saved(prepared[s].point) for s in value.slots),
                    "CloseSave without complete actual Saved conclusions", key)
            if binding is not None:
                occurred = completion_occurred(binding, contract, trace_at(trace, index))
                if occurred is None:
                    missing(("INV-2.a",), "completion occurrence adapter is not connected for " + repr(key))
                else:
                    require("INV-2.a", occurred, "CloseSave precedes independent occurrence of its condition", key)
        elif tag == "HandoffPurpose":
            binding = next((b for b in contract.completions if b.key == key), None)
            require("INV-2.c", binding is not None and key in value.before and value.before == value.after,
                    "handoff erased/renamed unmet conditions or treated transfer as achievement", key)
            if value.source == value.destination:
                missing(("INV-2.c",), "same-owner next-responsibility acceptance is absent from legacy handoff wire")
            # State/history clauses above are not proof of a custody transfer.
            # evaluate_observation_step checks the two actual P snapshots.
        elif tag == "IntervalUndertaken":
            require("INV-12.a", interval_undertaking_matches(contract, trace_at(trace, index + 1), event),
                    "actual undertaking differs from the full E0 request/finite cells/clock", key)
            # The full immutable E0 request fixes every field above. Do not
            # additionally require raw PlanRef == Point on a later observation;
            # both must independently resolve to that SAME declared target.
        elif tag in ("RouteApplied", "MeasurementStarted", "Monitored", "Measured", "ReportGenerated", "MeasurementEnded"):
            declaration = next((b for b in contract.intervals if b.key == key), None)
            require("INV-12.a", declaration is not None and declaration.work == value.work,
                    "EI event has no corresponding declared interval/work", target)
            if _type(value.reading, "Reading"):
                require("INV-12.a", value.reading.run == key.run, "EI clock run differs from interval request", target)
            if value.interval is not None:
                require("INV-12.a", value.interval.run == key.run and value.interval.start <= value.interval.end,
                        "EI interval/run correspondence failed", target)
            if declaration is not None:
                i = declaration.interval
                cells = interval_atoms(i, declaration.endpoints)
                require("INV-12.a", cells is not None and {(c.start, c.end) for c in value.cells} <= cells,
                        "EI cells exceed declared finite interval including endpoint openness", target)
            if value.evidence is not None:
                # Exact evidence DTO conversion is purpose-specific; do not say
                # that mere Saved status establishes its generation meaning.
                require("INV-12.a", saved(value.evidence), "EI evidence point is not Saved", target)
                declarations = [b for b in contract.interval_evidence if (b.key, b.tag) == (key, tag)]
                bindings = []
                for binding in declarations:
                    try:
                        bindings.append(resolve_interval_evidence(contract, trace_at(trace, index + 1), binding))
                    except UnresolvedDeclaration as error:
                        missing(("INV-12.a",), str(error))
                if not declarations:
                    missing(("INV-12.a",), "contract-specific EI event -> evidence content binding")
                else:
                    entries = [e for e in seen.entries if e.point == value.evidence]
                    require("INV-12.a", any((b.point, b.key, b.tag, b.event) == (value.evidence, key, tag, value)
                                            and len(entries) == 1 and b.record == entries[0].header.record for b in bindings),
                            "X-resident EI evidence content does not correspond to the actual event", target)
        elif tag == "CertifiedCoverage":
            require("INV-12.a", value.report in value.view and saved(value.report)
                    and value.evidence <= value.view and all(saved(p) for p in value.evidence),
                    "Support uses unsaved or outside-X evidence", key)
            limitations.add(("INV-12.a", "未対応: contract-specific Support; supplied coverage is NOT an oracle (paper 735,1087)"))
        elif tag == "ArtifactIssued":
            try:
                binding = resolve_artifact_port(contract, trace_at(trace, index), key.work)
            except UnresolvedDeclaration as error:
                binding = None
                missing(("INV-16.b",), str(error))
            a = value.artifact
            require("INV-16.b", binding is not None and a in binding.possible_returns, "artifact is not an actual declared port output", key)
            if binding is not None:
                require("INV-16.b", all(getattr(a, n) == getattr(binding, n) for n in
                                        ("contract", "compiler", "reader_view_key", "registry_key", "inputs")),
                        "issued artifact contract/compiler/reader/registry/input differs", key)
            require("INV-16.b", value.generation.work == key.work and sources.get(key.work) == value.generation.provenance,
                    "artifact generation source/work mismatch", key)
            artifacts[key] = a
        elif tag == "ArtifactChecked":
            require("INV-16.a", artifacts.get(key) == value.artifact, "checked artifact differs from independently issued artifact", key)
            try:
                binding = resolve_artifact_port(contract, trace_at(trace, index), key.work, checked=True)
            except UnresolvedDeclaration as error:
                binding = None
                missing(("INV-16.a", "INV-16.b"), str(error))
            if binding is None or not binding.checked_returns:
                missing(("INV-16.a", "INV-16.b"), "declared artifact verification port and EQ/PR/Draw/EV/S bindings")
            else:
                require("INV-16.b", value in binding.checked_returns, "artifact assessment/request/problem/Draw binding differs from declared actual port", key)
            limitations.add(("INV-16.a", "未対応: artifact mathematical validity/full semantic closure; port observation is not H-03"))

        # At EVERY history prefix: invalid release never reduces independent Occ.
        if tag in ("Reserve", "Release"):
            occupation = Counter()
            for held_key, resources in reserves.items():
                if held_key not in releases:
                    occupation.update(dict(resources))
            for resource, amount in occupation.items():
                require("INV-10.a", 0 <= amount <= allocation.get(resource, 0), "actual EW occupancy exceeds allocation", (index, resource))

    saved = lambda point: ledger_saved(point, trace, contract.codec)
    for entry in trace.entries:
        record = entry.header.record
        rules = [r for r in contract.references if r.record_contract == record.contract and r.operation == "PrepareOne"]
        if not rules:
            if record.references:
                missing(("INV-5.a", "INV-7.b", "INV-8.a"), "undeclared contract/path/use/operation reference role")
            continue
        expected = set()
        for rule in rules:
            if rule.closure == "unsupported":
                limitations.add(("INV-5.a", "未対応: " + rule.path_id + " semantic closure"))
            for path, value in reference_paths(record.content, rule.path):
                for point in _points(value):
                    expected.add((rule.path_id, path, point, rule.role, rule.use))
                    require("INV-5.a", _type(point, "Point") and saved(point), "declared direct reference is unresolved or not Saved", entry.point)
        actual = {(r.path_id, r.path, r.ref, r.role, r.use) for r in record.references}
        require("INV-5.a", actual == expected, "record typed references differ from explicit declared paths/roles", entry.point)
    for status in derive_observation_status(contract, trace):
        if status.unsupported:
            missing(("INV-2.d", "L-DERIVE"), "; ".join(status.unsupported))
        if status.published and not status.unsupported:
            require("INV-2.d", status.matched, "published Q does not satisfy independent Matchδ", status.key)
        # ReadyN includes permission, binding and conflict closure. Saved inputs
        # alone must never become a ReadyN oracle (paper 683-690).
        if status.eligible:
            missing(("L-DERIVE",), "ReadyN permission/conflict closure and graph binding remain unconnected")

    # Data declarations never fill in the explicitly unsupported paper meanings.
    for part in GAP_PARTS:
        if part.category == "乙":
            for row in _GAP_ROWS[part.gap]:
                limitations.add((row, f"未対応: {part.meaning} (paper {part.paper.lines[0]}-{part.paper.lines[1]})"))
    m4 = check_m4_draw_followups(contract, trace)
    clauses.extend(m4.clauses)
    limitations.update(m4.limitations)
    return ObservationEvaluation(boundary, tuple(clauses), tuple(sorted(limitations)))


_GAP_ROWS = {
    "seal": ("INV-4.a", "INV-4.b", "INV-4.c", "L-RECEIPT"),
    "receipt_wire": ("INV-1.a", "INV-1.b", "INV-1.c", "INV-11.a", "INV-11.b", "INV-11.c", "L-RECEIPT"),
    "facts": ("INV-2.a", "INV-2.b", "INV-2.c", "INV-2.e", "INV-3.a", "INV-3.b", "INV-3.c", "INV-6.a", "INV-8.b", "INV-10.a", "INV-10.b", "INV-14.a", "INV-14.b", "INV-15.a", "INV-15.b"),
    "derivation": ("INV-2.a", "INV-2.d", "L-DERIVE"),
    "completion": ("INV-2.a", "INV-2.c", "INV-2.f", "INV-15.a", "INV-15.b"),
    "references": ("INV-5.a", "INV-5.b", "INV-5.c", "INV-7.a", "INV-7.b", "INV-7.c", "INV-8.a", "INV-8.b", "INV-9.a", "INV-16.b"),
    "apply": ("INV-6.b", "INV-6.c", "INV-7.a"),
    "adoption": ("INV-9.a", "INV-9.b", "INV-6.c"),
    "support": ("INV-12.a", "INV-12.b", "INV-13.a", "INV-13.b"),
    "artifact": ("INV-16.a", "INV-16.b"),
}


def observed_end_known(contract, trace, work, *, resolver=None):
    """1187,794-802: argmin before testing Saved, never earliest saved reply.

    A return binds EW generation to EH. A host Unknown instead binds its declared
    source and actual witnesses; it neither invents a return nor implies Stop.
    """
    descriptor = next((d for d in contract.descriptors if d.work_id == work), None)
    if descriptor is None:
        return None
    resolver = resolver or DeclarationResolver(contract, trace)
    sources = dict(contract.generation_sources)
    generations = [e.value.generation for e in trace.events if e.tag == "WorkerReturn" and e.key.work == work]
    starts = [e.value.started for e in trace.events if e.tag == "EnterBody" and e.key.work == work]
    posts = [e.value.envelope for e in trace.events if e.tag == "Post"]
    accepted = {e.key: e.value for e in trace.events if e.tag == "Accept"}
    prepared = {e.key: e.value.prepared for e in trace.events if e.tag == "FirstPrepare"}
    candidates = []
    for envelope in posts:
        # M4 (1967): a well-formed other envelope still needs C-O01 storage,
        # but cannot become this work's first terminal notice.
        kind = "DrawReturned" if descriptor.stage == "D" else "WorkFinished"
        if envelope.event.kind != kind or _get(envelope.event.fields, "work") != work:
            continue
        for generation in generations:
            try:
                request = resolver.resolve(descriptor.request)
            except UnresolvedDeclaration:
                continue
            if (generation.request != request or generation.stage != descriptor.stage
                    or len(starts) != 1 or generation.started != starts[0]
                    or sources.get(work) != generation.provenance or envelope.source != generation.provenance
                    or _get(envelope.event.fields, "outcome") != generation.outcome):
                continue
            if envelope.event.kind == "WorkFinished" and (_get(envelope.event.fields, "started"), _get(envelope.event.fields, "finished")) != (generation.started, generation.finished):
                continue
            candidates.append((envelope, generation))
    for index, event in enumerate(trace.events):
        if event.tag == "HostUnknown" and event.key.work == work and _host_unknown_matches(contract, trace, index, event):
            if event.value.envelope in posts:
                candidates.append((event.value.envelope, event.value))
    if not candidates:
        return None
    if len({e.run for e, _ in candidates}) != 1:
        return None  # no invented total order between runs
    first, generation = min(candidates, key=lambda pair: (pair[0].r.rank, pair[0].receipt_seq))
    prior = [e for e in posts if e.run == first.run and (e.r.rank, e.receipt_seq) <= (first.r.rank, first.receipt_seq)]
    if not all(ReceiptKey(e.run, e.number) in accepted for e in prior):
        return None
    acceptance = accepted[ReceiptKey(first.run, first.number)]
    layout = next(r for r in contract.receipt_layouts if r.kind == first.event.kind)
    for slot, _, _ in layout.slots:
        entry = prepared.get(SlotKey(acceptance.unit, slot))
        if (entry is None or not ledger_saved(entry.point, trace, contract.codec)
                or _wire(entry.record) != receipt_record_wire(contract, first, acceptance.created, slot)):
            return None
        try:
            if resolver.point(SlotKey(acceptance.unit, slot)) != entry.point:
                return None
        except UnresolvedDeclaration:
            return None
    return first, generation


def _host_unknown_matches(contract, trace, index, event):
    key, value = event.key, event.value
    descriptor = next((d for d in contract.descriptors if d.work_id == key.work), None)
    bindings = [b for b in contract.host_unknowns if b.work == key.work]
    outcome = _get(value.envelope.event.fields, "outcome")
    return (descriptor is not None
            and value.envelope.event.kind == ("DrawReturned" if descriptor.stage == "D" else "WorkFinished")
            and (value.request, value.stage) == (descriptor.request, descriptor.stage)
            and any((b.source, b.request, b.stage, b.basis)
                    == (value.envelope.source, value.request, value.stage, value.basis) for b in bindings)
            and _type(outcome, "Outcome") and outcome.kind == "Unknown" and outcome.content == value.basis
            and bool(value.witnesses) and all(
                witness in trace.events[:index] and witness.tag in ("EnterBody", "LaunchResponse", "Stop")
                and witness.key.work == key.work for witness in value.witnesses))


def check_m4_draw_followups(contract, trace):
    """M4, 332/787/1967-1969: first Failure permits T, never DF/DU/Ee.

    The guard identifies the declared originating Draw. Each publication is
    checked at its own root, so a later return cannot authorize an earlier use.
    This finite correspondence does not claim full F-a Draw validation.
    """
    clauses, limitations = [], set()
    descriptors = {d.work_id: d for d in contract.descriptors}
    for index, event in enumerate(trace.events):
        if event.tag != 'Publish':
            continue
        declared = next((p for p in contract.plans if p.unit == event.key.unit), None)
        plan = event.value.plan
        names = {r.contract.name for r in plan.records}
        is_df, is_du = 'draw_fact' in names, 'sui.fb.draw_unknown' in names
        has_ee = any(d.stage == 'Ee' for d in plan.works)
        if not (is_df or is_du or has_ee):
            continue
        works = ({g.key for g in declared.guards if g.kind in ('first', 'outcome')
                  and g.key in descriptors and descriptors[g.key].stage == 'D'}
                 if declared is not None else set())
        if not works:
            limitations.add(('INV-15.b',
                'M4 unconnected Draw -> DF/DU/Ee correspondence: ' + repr(event.key)))
        for work in works:
            first = observed_end_known(contract, publication_root(trace, index), work)
            outcome = _get(first[0].event.fields, 'outcome') if first else None
            lawful = (outcome is not None and outcome.kind != 'Failure'
                      and (not is_du or outcome.kind == 'Unknown')
                      and (not (is_df or has_ee) or outcome.kind == 'Success'))
            clauses.append(ClauseResult('INV-15.b', lawful,
                'M4 first Draw terminal forbids this DF/DU/Ee publication', (WorkKey(work), event.key)))
    return ObservationEvaluation(BoundaryReport('約束接続・部分判定', ()),
                                 tuple(clauses), tuple(sorted(limitations)))


def resolved_adoption_binding(contract, trace, key):
    """E0 intent/REF-5, 1062,1086: no EA/EU-supplied resolution table."""
    resolver = DeclarationResolver(contract, trace)
    candidates, unresolved = [], []
    for binding in contract.adoptions:
        if binding.key.intent != key.intent:
            continue
        try:
            if resolver.resolve(binding.key) == key:
                candidates.append(resolver.resolve(resolver.sources(binding)))
        except UnresolvedDeclaration as error:
            unresolved.append(error)
    if len(candidates) > 1:
        raise UnresolvedDeclaration("multiple E0 intents resolve to the same adoption key")
    if candidates:
        return candidates[0]
    if unresolved:
        raise unresolved[0]
    return None


def interval_undertaking_matches(contract, trace, event):
    """Full C-O04 undertaking (629,723,1186,1205-1207), not EI progress.

    The actual request may still contain its declared PlanRef: undertaking
    precedes publication. If a Point is observed, reconstruct it independently.
    """
    declaration = next((b for b in contract.intervals if b.key == event.key), None)
    if declaration is None:
        return False
    value, request = event.value, event.value.request
    expected_point = declaration.point
    if request.point != expected_point:
        try:
            expected_point = DeclarationResolver(contract, trace).resolve(expected_point)
        except UnresolvedDeclaration:
            return False
    cells = interval_atoms(declaration.interval, declaration.endpoints)
    return (request.point == expected_point and request.work == declaration.work
            and request.interval == declaration.interval
            and request.measurement_contract == declaration.measurement_contract
            and request.clock_contract == declaration.clock_contract
            and cells is not None and {(c.start, c.end) for c in request.cells} == cells
            and (request.id, request.route_epoch, request.interval.run)
            == (event.key.request, event.key.route, event.key.run)
            and value.reading.run == event.key.run and value.reading.source == declaration.interval.clock
            and value.owner.location in ("H", "P.work"))


def completion_occurred(binding, contract, trace):
    """Occurrence independent of Recognize/ready/done flags, 1185-1194.

    None means missing observation/adapter, not False or completed. Full
    conditional .issue semantics still require the paper's unsupported closures.
    """
    if binding.trigger == "EndKnown":
        work = getattr(binding.source, 'work', None)
        if not any(d.work_id == work for d in contract.descriptors):
            return None
        return observed_end_known(contract, trace, work) is not None
    tags = {"Post": "Post", "Publish": "Publish", "Acquire": "Acquire", "Reserve": "Reserve"}
    if binding.trigger in tags:
        return any(e.tag == tags[binding.trigger] and e.key == binding.source for e in trace.events)
    if binding.trigger == "IntervalRequest":
        return any(e.tag == "IntervalUndertaken" and e.key == binding.source
                   and interval_undertaking_matches(contract, trace_at(trace, i + 1), e)
                   for i, e in enumerate(trace.events))
    return None


@dataclass(frozen=True, slots=True)
class ConditionPart:
    condition: CompletionKey
    part: object


@dataclass(frozen=True, slots=True)
class PurposePart:
    """1317/1328: identity derived from E0, never from an owner's chosen name.

    This is a checker identity, not a new record or a 45th completion schema.
    The old condition and the original descriptor/notice can retain it (1324).
    """
    origin: CompletionKey
    purpose: tuple[object, ...]
    part: object


@dataclass(frozen=True, slots=True)
class CustodyJudgement:
    target: object
    classification: str
    direct: bool | None
    transfer: bool | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnconnectedCompletion:
    """An observed role whose occurrence/instance adapter is missing (1586)."""
    condition_id: str
    witness: object


def _truth_all(values):
    """A known false conjunct is independent evidence, even beside a gap."""
    values = tuple(values)
    return False if False in values else None if None in values else True


class CompletionFacts:
    """Per-evaluation facts shared by 44 separate predicates (1529-1572).

    No imports/calls into the window. None means an adapter/meaning is absent;
    missing actual evidence under a connected predicate means False.
    """
    def __init__(self, contract, trace, state):
        self.contract, self.trace, self.state = contract, trace, state
        self.resolver = DeclarationResolver(contract, trace)
        self.plans = {p.unit: p for p in contract.plans}
        self.descriptors = {d.work_id: d for d in contract.descriptors}
        self.rows = {c.key: c for c in state.core.p.conditions}
        self.work = {w.descriptor.work_id: w for w in state.core.p.work}
        self.ends, self.pubs = {}, {}
        self.gaps = set()
        self._derivations = None

    def gap(self, reason):
        self.gaps.add(reason)
        return None

    def end(self, work):
        if work not in self.ends:
            self.ends[work] = observed_end_known(self.contract, self.trace, work)
        return self.ends[work]

    def record(self, slot):
        plan = self.plans.get(slot.unit)
        return next((r for r in plan.records if r.slot == slot.slot), None) if plan is not None else None

    def sv(self, binding):
        # Each slot is checked against E0/EH and actual bytes, not CloseSave.
        if not binding.slots:
            return self.gap('SV slot correspondence absent: ' + repr(binding.key))
        for slot in binding.slots:
            try:
                self.resolver.point(slot)
            except UnresolvedDeclaration:
                return False
        return True

    def end_save(self, binding, stage, verification=False):
        work = getattr(binding.source, 'work', None)
        descriptor = self.descriptors.get(work)
        if descriptor is None or descriptor.stage != stage:
            return self.gap('terminal save -> E0 work/stage: ' + repr(binding.key))
        first = self.end(work)
        if first is None:
            return False
        if verification:
            reply = _get(first[0].event.fields, 'outcome').content
            if not _type(reply, 'VerificationReply'):
                return False
            actual = [e.value.reply for e in self.trace.events if e.tag == 'VerifyReply' and e.key.work == work]
            if not actual or any(r != reply for r in actual):
                return False
        return self.sv(binding)

    def run(self, binding, stage):
        work = getattr(binding.key.target, 'work', None)
        descriptor = self.descriptors.get(work)
        if descriptor is None or descriptor.stage != stage:
            return self.gap('run -> E0 work/stage: ' + repr(binding.key))
        return self.end(work) is not None

    def delta(self, binding, discharge):
        if discharge and self.sv(binding) is not True:
            return False  # Q itself is not Saved: independent of /2 semantics.
        if not any(e.tag == 'Publish' and isinstance(binding.key.target, SlotKey)
                   and e.key.unit == binding.key.target.unit for e in self.trace.events):
            return False
        selected = [i for i, d in enumerate(self.contract.derivations)
                    if d.request == binding.key.target and d.plan.key == binding.key.obligation_key]
        if not selected:
            return self.gap('delta instance -> declared obligation/request: ' + repr(binding.key))
        if self._derivations is None:
            self._derivations = derive_observation_status(self.contract, self.trace)
        values = []
        for i in selected:
            status = self._derivations[i]
            if status.unsupported:
                values.append(self.gap('Discharge/Match delta: ' + '; '.join(status.unsupported)))
            else:
                values.append(status.discharged if discharge else
                              _truth_all((status.matched, self.pub(binding.key.target.unit))))
        return _truth_all(values)

    def pub(self, unit, successor=None):
        """1319/1523: validate issuance at its root, retain late-conflict history.

        A P.units row or a matching EU label is never sufficient. Full recipes,
        guard evidence, references and every promised work descriptor are checked.
        Unsupported use/semantic closures are NOT presumed lawful.
        """
        cache_key = (unit, successor)
        if cache_key in self.pubs:
            return self.pubs[cache_key]
        plan = self.plans.get(unit)
        events = [(i, e) for i, e in enumerate(self.trace.events) if e.tag == 'Publish' and e.key.unit == unit]
        if not events:
            return False
        if plan is None:
            return False  # actual extra promises still belong to the population
        if plan.semantic_limits or plan.use_keys:
            return self.gap('PUB use/semantic closure: ' + repr((unit, plan.semantic_limits, plan.use_keys)))
        results = []
        for index, event in events:
            try:
                root = publication_root(self.trace, index)
                resolver = DeclarationResolver(self.contract, root)
                expected = resolver.plan(plan.unit)
                if expected != event.value.plan:
                    return False
                resolver.publication(expected.records, unit)
                guard_values = []
                for guard in plan.guards:
                    if guard.kind == 'saved':
                        guard_values.append(ledger_saved(resolver.resolve(guard.key), root, self.contract.codec))
                    elif guard.kind in ('first', 'outcome', 'definite_verification'):
                        known = observed_end_known(self.contract, root, guard.key)
                        ok = known is not None
                        if ok and guard.kind == 'outcome':
                            outcome = _get(known[0].event.fields, 'outcome')
                            ok = (outcome.kind, _get(outcome.content, 'variant')) == guard.value
                        if ok and guard.kind == 'definite_verification':
                            ok = _type(_get(known[0].event.fields, 'outcome').content, 'VerificationReply')
                        guard_values.append(ok)
                    elif guard.kind == 'acquired':
                        guard_values.append(any(e.tag == 'Acquire' and e.key.intent == guard.key for e in root.events))
                    elif guard.kind == 'initial':
                        guard_values.append(self.gap('PUB initial guard wire: ' + repr(unit)))
                    else:
                        guard_values.append(self.gap('PUB guard adapter: ' + guard.kind))
                results.extend(guard_values)
            except UnresolvedDeclaration:
                return False
            except ValueError:
                return False
        results.append(all(d.work_id in self.work and self.work[d.work_id].descriptor == d for d in plan.works))
        if successor is not None:
            results.append(any(d.stage == successor for d in plan.works))
        result = _truth_all(results)
        self.pubs[cache_key] = result
        return result

    def issue(self, binding, names, successor=None):
        units = {s.unit for s in binding.slots}
        if isinstance(binding.key.target, SlotKey):
            units.add(binding.key.target.unit)
        if not units:
            return self.gap('issue -> fixed record plans: ' + repr(binding.key))
        plans = [self.plans.get(u) for u in units]
        if any(p is None for p in plans):
            return self.gap('issue has no independently declared plan: ' + repr(binding.key))
        present = {r.contract.name for p in plans for r in p.records}
        if not set(names) <= present:
            return self.gap('issue record-family correspondence: ' + repr(binding.key))
        return _truth_all(self.pub(u, successor) for u in units)

    def segment_end(self, binding):
        """1415-1449. No Ended -> false; unconnected Ended evidence -> None.

        The current EI port has no declared CMP-04 report/clock mapping. Do not
        mistake MeasurementEnded, Unavailable or generic worker EndKnown for it.
        Source correspondence must be connected before applying argmin. Taking
        an unverified candidate as the first one would itself overconstrain run.
        """
        work = getattr(binding.key.target, 'work', None)
        declarations = [d for d in self.contract.intervals if d.work == work]
        if len(declarations) != 1:
            return self.gap('SegmentEndKnown interval/work declaration')
        declaration = declarations[0]
        candidates = []
        for event in self.trace.events:
            if event.tag != 'Post' or event.value.envelope.event.kind != 'SegmentReport':
                continue
            envelope = event.value.envelope
            report = _get(envelope.event.fields, 'report')
            if not _type(report, 'Report') or report.kind != 'Ended':
                continue
            try:
                corresponds = (self.resolver.resolve(report.segment) == self.resolver.resolve(declaration.point)
                               and report.route_epoch == declaration.key.route and envelope.run == declaration.key.run)
            except UnresolvedDeclaration:
                return self.gap('SegmentEndKnown unresolved candidate correspondence')
            if corresponds:
                candidates.append(envelope)
        if not candidates:
            return False
        return self.gap('SegmentEndKnown CMP-04 source/end-reading/reason/evidence and Started order adapter')

    def cells(self, binding):
        work = getattr(binding.key.target, 'work', None)
        declarations = [d for d in self.contract.intervals if d.work == work]
        if len(declarations) != 1:
            return self.gap('Parts(c) fixed interval declaration')
        cells = interval_atoms(declarations[0].interval, declarations[0].endpoints)
        if cells is None:
            return self.gap('Parts(c) interval atoms')
        return tuple(sorted(cells))

    def cell_direct(self, binding, part):
        work = getattr(binding.key.target, 'work', None)
        reports = [e for e in self.trace.events if e.tag == 'ReportGenerated' and e.value.work == work
                   and any((c.start, c.end) == part for c in e.value.cells)]
        if not reports:
            if any(e.tag == 'Post' and e.value.envelope.event.kind == 'SegmentReport' for e in self.trace.events):
                return self.gap('cell explanation: EH report -> original interval/cell and required evidence adapter')
            return False
        return self.gap('cell explanation: typed ReportCells/evidence -> local Direct (not Support)')

    def cell_owned(self, binding, part, retained):
        if retained is not True:
            return retained
        work = binding.key.target.work
        requests = [k for k in self.state.core.h.interval_requests if k.work == work]
        if requests:
            return any(part in {(a.start, a.end) for a in k.cells} for k in requests)
        descriptor = self.descriptors.get(work)
        return work in self.work and self.work[work].descriptor == descriptor


# The registry is deliberately 44 paper rows, not a dispatcher by five kinds.
# Shared SV/PUB/EndKnown primitives do not turn one condition into another.
def direct_o01_receipt(b, f):
    return f.sv(b)


def direct_o02_initial(b, f):
    return f.issue(b, ())


def direct_o02_slot(b, f):
    return f.sv(b)


def direct_o03_issue_q(b, f):
    return f.delta(b, False)


def direct_o03_save_q(b, f):
    return f.delta(b, True)


def direct_o04_save_k(b, f):
    return f.sv(b)


def direct_o04_run(b, f):
    return f.segment_end(b)


def direct_o04_cells(b, f):
    parts = f.cells(b)
    return None if parts is None else _truth_all(f.cell_direct(b, a) for a in parts)


def direct_o05_run(b, f):
    return f.run(b, 'Wr')


def direct_o05_t(b, f):
    return f.end_save(b, 'Wr')


def direct_o05_handle(b, f):
    return False  # 1386-1388: local conclusion is Transfer, not T/R Saved.


def direct_o06_issue_r(b, f):
    return f.issue(b, ('computation_result',), 'Wp')


def direct_o06_save_r(b, f):
    return _truth_all((f.sv(b), *(f.pub(s.unit, 'Wp') for s in b.slots)))


def direct_o07_run(b, f):
    return f.run(b, 'Wp')


def direct_o07_t(b, f):
    return f.end_save(b, 'Wp')


def direct_o07_handle(b, f):
    return False  # 1389-1391: p and issue/P/Cq have their own identities.


def direct_o07_issue_pc(b, f):
    return f.issue(b, ('computation_proof', 'computation_completed'))


def direct_o07_save_p(b, f):
    return f.sv(b)


def direct_o07_save_cq(b, f):
    saved = f.sv(b)
    if saved is not True:
        return saved
    try:
        for slot in b.slots:
            record = f.resolver.expected_preparation(slot).record
            request = _get(record.content, 'request')
            for field in ('started_clock', 'finished_clock'):
                completed_clock_reading(f.contract, f.trace, _get(record.content, field), request, field)
            same = [e for e in f.trace.entries if e.header.record.contract.name == 'computation_completed'
                    and _get(e.header.record.content, 'request') == request]
            if len(same) != 1:
                return False
    except UnresolvedDeclaration as error:
        return f.gap(str(error))
    except ValueError:
        return False
    return True


def direct_o08_handle(b, f):
    return False  # 1392: the G handoff is checked by Transfer.


def direct_o08_issue_g(b, f):
    published = f.issue(b, ('content_acquired',), 'Wv')
    if published is not True:
        return published
    return f.gap('G issue: full EA acquisition -> G/Wv/original purpose correspondence')


def direct_o08_save_g(b, f):
    saved = f.sv(b)
    if saved is not True:
        return saved
    return _truth_all((*[f.pub(s.unit, 'Wv') for s in b.slots],
                       f.gap('G handoff: original purpose -> O-09a/b atomic acceptance')))


def direct_o09a_run(b, f):
    return f.run(b, 'Wv')


def direct_o09a_t(b, f):
    return f.end_save(b, 'Wv')


def direct_o09a_v(b, f):
    return f.end_save(b, 'Wv', verification=True)


def direct_o09b_handle(b, f):
    work = getattr(b.key.target, 'work', None)
    if work is not None and f.end(work) is None:
        return False
    return f.gap('O-09b A/ST/rejection processing record -> original purpose/EA binding')


def direct_o09b_slot(b, f):
    return f.sv(b)


def direct_o10_run(b, f):
    return f.run(b, 'Ep')


def direct_o10_t(b, f):
    return f.end_save(b, 'Ep')


def direct_o10_issue(b, f):
    return f.gap('O-10 artifact/PR and FProblem-only D: full artifact closure')


def direct_o10_slot(b, f):
    return f.sv(b)


def direct_o11_run(b, f):
    return f.run(b, 'D')


def direct_o11_t(b, f):
    return f.end_save(b, 'D')


def direct_o11_issue(b, f):
    return f.gap('O-11 DF/DU first/full Draw request/use closure and value-only Ee')


def direct_o11_slot(b, f):
    return f.sv(b)


def direct_o12_run(b, f):
    return f.run(b, 'Ee')


def direct_o12_t(b, f):
    return f.end_save(b, 'Ee')


def direct_o12_handle(b, f):
    return False  # 1398-1400: all branches transfer, including NoDecision.


def direct_o12_issue_ev(b, f):
    return f.gap('O-12 artifact/EV: EQ/PR/Draw/confirmed-artifact full closure')


def direct_o12_issue_s(b, f):
    return f.gap('O-12 S: Saved EV/certified Selected/full use closure')


def direct_o12_slot(b, f):
    return f.sv(b)


def direct_o13_handle(b, f):
    return False  # 1401-1403: processing/save transfer, never purpose achievement.


def direct_o13_slot(b, f):
    return f.sv(b)


def direct_o14_stop(b, f):
    work = getattr(b.key.target, 'work', None)
    reservations, stopped, released = {}, set(), Counter()
    for event in f.trace.events:
        if getattr(event.key, 'work', None) != work:
            continue
        if event.tag == 'Reserve':
            if event.key in reservations or any(k.work == work for k in reservations):
                return False
            reservations[event.key] = event.value.resources
        elif event.tag == 'Stop' and event.key in reservations:
            stopped.add(event.key)
        elif event.tag == 'Release':
            if event.key not in stopped or event.value.resources != reservations.get(event.key):
                return False
            released[event.key] += 1
    return bool(reservations) and all(released[k] == 1 for k in reservations)


COMPLETION_PREDICATES = (
    ('C-O01.save[receipt_slot]', direct_o01_receipt, 1529),
    ('C-O02.issue[initial]', direct_o02_initial, 1530),
    ('C-O02.save[各slot]', direct_o02_slot, 1531),
    ('C-O03.issue[Q]', direct_o03_issue_q, 1532),
    ('C-O03.save[Q]', direct_o03_save_q, 1533),
    ('C-O04.save[k]', direct_o04_save_k, 1534),
    ('C-O04.run[MeasureSegment]', direct_o04_run, 1535),
    ('C-O04.handle[cells]', direct_o04_cells, 1536),
    ('C-O05.run[Wr]', direct_o05_run, 1537),
    ('C-O05.save[T]', direct_o05_t, 1538),
    ('C-O05.handle[Wr]', direct_o05_handle, 1539),
    ('C-O06.issue[R]', direct_o06_issue_r, 1540),
    ('C-O06.save[R]', direct_o06_save_r, 1541),
    ('C-O07.run[Wp]', direct_o07_run, 1542),
    ('C-O07.save[T]', direct_o07_t, 1543),
    ('C-O07.handle[Wp]', direct_o07_handle, 1544),
    ('C-O07.issue[P,Cq]', direct_o07_issue_pc, 1545),
    ('C-O07.save[P]', direct_o07_save_p, 1546),
    ('C-O07.save[Cq]', direct_o07_save_cq, 1547),
    ('C-O08.handle[取得意図]', direct_o08_handle, 1548),
    ('C-O08.issue[G]', direct_o08_issue_g, 1549),
    ('C-O08.save[G]', direct_o08_save_g, 1550),
    ('C-O09a.run[Wv]', direct_o09a_run, 1551),
    ('C-O09a.save[T]', direct_o09a_t, 1552),
    ('C-O09a.save[V]', direct_o09a_v, 1553),
    ('C-O09b.handle[目的]', direct_o09b_handle, 1554),
    ('C-O09b.save[処理slot]', direct_o09b_slot, 1555),
    ('C-O10.run[Ep]', direct_o10_run, 1556),
    ('C-O10.save[T]', direct_o10_t, 1557),
    ('C-O10.issue[artifact,PR]', direct_o10_issue, 1558),
    ('C-O10.save[artifact,PRの各slot]', direct_o10_slot, 1559),
    ('C-O11.run[D]', direct_o11_run, 1560),
    ('C-O11.save[T]', direct_o11_t, 1561),
    ('C-O11.issue[DF/DU]', direct_o11_issue, 1562),
    ('C-O11.save[DF/DU/別の必須終わりslot]', direct_o11_slot, 1563),
    ('C-O12.run[Ee]', direct_o12_run, 1564),
    ('C-O12.save[T]', direct_o12_t, 1565),
    ('C-O12.handle[評価の終わり]', direct_o12_handle, 1566),
    ('C-O12.issue[artifact,EV]', direct_o12_issue_ev, 1567),
    ('C-O12.issue[S]', direct_o12_issue_s, 1568),
    ('C-O12.save[artifact,EV,Sの各slot]', direct_o12_slot, 1569),
    ('C-O13.handle[報告/鍵/根]', direct_o13_handle, 1570),
    ('C-O13.save[処理slot]', direct_o13_slot, 1571),
    ('C-O14.stop[w]', direct_o14_stop, 1572),
)


def completion_predicate(binding, facts):
    if binding is None:
        return None
    key = binding.key
    prefix = 'C-' + key.obligation.replace('O-', 'O').replace('.a', 'a').replace('.b', 'b') + '.' + key.kind + '['
    candidates = [(cid, fn) for cid, fn, _ in COMPLETION_PREDICATES if cid.startswith(prefix)]
    if len(candidates) == 1:
        return candidates[0][1]
    # Same O/kind may still have distinct conclusions. Use E0 target contracts,
    # not the spelling of a window slot, to distinguish T/V/P/Cq and issue S.
    names = {r.contract.name for s in binding.slots if (r := facts.record(s)) is not None}
    if key.kind == 'save' and binding.trigger == 'EndKnown':
        suffix = '[V]' if 'sui.fb.verification_result' in names else '[T]'
    elif key.obligation == 'O-07' and key.kind == 'save':
        suffix = '[Cq]' if 'computation_completed' in names else '[P]' if 'computation_proof' in names else None
    elif key.kind == 'issue' and key.obligation == 'O-12':
        suffix = '[S]' if 'decision' in names else '[artifact,EV]'
    elif key.obligation == 'O-G':
        suffix = ('[CG]' if 'candidate_declaration' in names else
                  '[EQ]' if 'sui.fb.evaluation_request' in names else None)
    else:
        suffix = None
    return next((fn for cid, fn in candidates if suffix is not None and cid.endswith(suffix)), None)


def completion_conclusion(binding, contract, trace, state):
    """Local Direct only. Transfer and D3 purposes are evaluated separately."""
    facts = (GenerationFacts if binding.key.obligation == 'O-G' else CompletionFacts)(contract, trace, state)
    predicate = completion_predicate(binding, facts)
    return predicate(binding, facts) if predicate is not None else None


def required_purpose_parts(binding, facts):
    """1365-1374: derive p before any W/Transfer/condition-birth flag exists.

    Connected here: independently known Failure/Unknown for Wr/Wp/Wv/Ep/Ee,
    and an actual Wv Insufficient. D.Unknown/Failure does not imply a retry
    purpose. Other declared insufficient/use-prohibition branches remain gaps.
    """
    key = binding.key
    source_kind = {'O-05': 'handle', 'O-07': 'handle', 'O-09.b': 'handle',
                   'O-10': 'run', 'O-11': 'run', 'O-12': 'handle'}
    if key.obligation in ('O-04', 'O-13') and key.kind == 'handle':
        # No missing-purpose flag supplied by the window can close this gap.
        facts.gap('residual purpose: per-cell/report concrete insufficiency/Clash branch correspondence')
    if source_kind.get(key.obligation) != key.kind:
        return ()
    if not isinstance(key.target, WorkKey):
        facts.gap('residual purpose: original intent/purpose -> work/notice correspondence: ' + repr(key))
        return ()
    descriptor = facts.descriptors.get(key.target.work)
    first = facts.end(key.target.work)
    if descriptor is None or first is None:
        return ()
    outcome = _get(first[0].event.fields, 'outcome')
    non_success = outcome.kind in ('Failure', 'Unknown') and key.obligation != 'O-11'
    insufficient = _type(outcome.content, 'VerificationReply') and outcome.content.response == 'Insufficient'
    if not non_success and not insufficient:
        # No new success/NoDecision/Draw-retry purpose is invented here.
        if descriptor.semantic_limits or descriptor.use_keys:
            facts.gap('residual purpose: concrete insufficiency/prohibition branch adapter for ' + repr(key))
        return ()
    identity = (descriptor.purpose, descriptor.process, descriptor.reader,
                descriptor.request, descriptor.stage_slot)
    return (PurposePart(key, identity, key.target),)


def purpose_carried(part, facts):
    """1324/1376: reconstruct from the original descriptor/notice in real P.work.

    D3 fixes p as unmet; the local condition row need not remain its carrier.
    Requiring that row forever would conflate local Transfer with residual p.
    A reference or terminal record alone cannot replace the original metadata.
    """
    work = facts.work.get(part.part.work)
    descriptor = facts.descriptors.get(part.part.work)
    return work is not None and work.descriptor == descriptor and facts.end(part.part.work) is not None


def condition_owner(binding, held, facts):
    """1320: real matching responsibility, not merely an existing owner name."""
    if held is None or held.key not in held.unmet or not actual_owner_exists(facts.state, held.owner):
        return False
    if binding is None:
        return facts.gap('Owner correspondence for undeclared original condition')
    key, owner = binding.key, held.owner
    if owner.location == 'P.work':
        descriptor = facts.descriptors.get(owner.key)
        if descriptor is None or facts.work[owner.key].descriptor != descriptor:
            return False
        if owner == binding.owner or key.target == WorkKey(owner.key):
            return True
        return facts.gap('Owner successor work -> original purpose/target')
    if key.kind == 'save' and owner.location == 'P.units':
        return bool(binding.slots) and all(s.unit == owner.key for s in binding.slots)
    if key.obligation == 'O-01' and owner.location == 'P.receipts':
        return isinstance(binding.source, ReceiptKey) and owner.key in (
            (binding.source.run, binding.source.number), *(s.unit for s in binding.slots))
    if owner == binding.owner:
        return True
    if key.kind == 'handle' and any(e.tag == 'HandoffPurpose' and e.key == key
                                   and e.value.destination == owner for e in facts.trace.events):
        transfer = condition_transfer(binding, facts)
        return transfer if transfer is not False else False
    return False


def condition_transfer(binding, facts):
    """1330-1338: existing whole-condition transport, with branch constraints.

    The public HandoffPurpose wire preserves a bundle, not a completion flag.
    Validate each member's own Direct/Carry, not an equality-of-whole-O shortcut.
    A future cell/subset or same-owner acceptance adapter must supply its real
    atomic acceptance; no such event is invented from a cleared unmet set.
    """
    if binding is None or binding.key.kind != 'handle':
        return False
    key = binding.key
    events = [e for e in facts.trace.events if e.tag == 'HandoffPurpose' and e.key == key]
    if not events:
        return False
    event = events[-1]
    if event.value.source == event.value.destination:
        return facts.gap('same-owner next-responsibility acceptance is absent from legacy handoff wire')
    held = facts.rows.get(key)
    if held is None or key not in held.unmet:
        # A local obligation may disappear AFTER a real Transfer. The legacy
        # event alone has no historical acceptance snapshot: neither certify
        # it nor require the original condition forever. D3/p is still checked.
        return facts.gap('Transfer historical acceptance after local condition discharge')
    if event.value.destination != held.owner:
        return False
    if not actual_owner_exists(facts.state, held.owner):
        return False
    if event.value.before != event.value.after or key not in event.value.after:
        return False
    for member in event.value.before:
        other = next((b for b in facts.contract.completions if b.key == member), None)
        predicate = completion_predicate(other, facts)
        direct = predicate(other, facts) if predicate is not None else None
        carried = facts.rows.get(member)
        if direct is not True and not (carried is not None and member in carried.unmet
                                      and carried.owner == held.owner and actual_owner_exists(facts.state, carried.owner)):
            return False if direct is False else facts.gap('Transfer payload Direct/Carry: ' + repr(member))
    parts = required_purpose_parts(binding, facts)
    if any(not purpose_carried(p, facts) for p in parts):
        return False
    # Payload also contains the independently born save/run/stop obligations,
    # including T under a DIFFERENT obligation key. They need not move to the
    # same destination; each can be Direct or remain with its own real owner.
    if isinstance(key.target, WorkKey):
        for other in facts.contract.completions:
            if other.key == key or not (other.source == key.target or other.key.target == key.target):
                continue
            if completion_occurred(other, facts.contract, facts.trace) is not True:
                continue
            predicate = completion_predicate(other, facts)
            direct = predicate(other, facts) if predicate is not None else None
            carrier = facts.rows.get(other.key)
            carried = (carrier is not None and other.key in carrier.unmet
                       and actual_owner_exists(facts.state, carrier.owner))
            if direct is not True and not carried:
                return False if direct is False else facts.gap('Transfer independently born payload: ' + repr(other.key))
    # A P.units processing carrier must be this work's declared terminal plan;
    # the original P.work still carries its residual purpose. Another arbitrary
    # live unit/row or an E0 HandoffRoute destination is not semantic authority.
    if parts and held.owner.location == 'P.units':
        plan = facts.plans.get(held.owner.key)
        source_work = key.target.work
        if plan is None or not any(g.kind == 'first' and g.key == source_work for g in plan.guards):
            return facts.gap('Transfer destination -> same non-success processing responsibility')
        return facts.pub(plan.unit)
    if key.obligation == 'O-05' and isinstance(key.target, WorkKey):
        known = facts.end(key.target.work)
        if known is None:
            return False
        outcome = _get(known[0].event.fields, 'outcome')
        if outcome.kind == 'Success' and held.owner.location == 'P.units':
            plan = facts.plans.get(held.owner.key)
            if (plan is not None and plan.obligation_id == 'O-06'
                    and any(g.kind == 'first' and g.key == key.target.work for g in plan.guards)):
                return facts.pub(plan.unit, 'Wp')
    return facts.gap('Transfer branch/destination acceptance: ' + repr(key))


def classify_custody(direct, transfer, retained):
    """1346-1351/1582-1586: unknown is not the fourth (violation) category."""
    if direct is True:
        return '達成済み'
    if transfer is True:
        return '引継ぎ済み'
    if direct is None or transfer is None:
        return '未接続'
    return '未達のまま保全' if retained else '削除・消去の違反'


@dataclass(frozen=True, slots=True)
class IssueOccurrence:
    """1203-1235/1586: a birth witness, never an actual Publish selector.

    None records an observed prerequisite whose full occurrence correspondence
    is still unconnected. A known finite instance can also name its original
    carrier; it does not require the window to invent another custody row.
    """
    condition_id: str
    witness: object
    occurred: bool | None
    binding: CompletionBinding | None = None
    carrier: CompletionBinding | None = None
    reasons: tuple[str, ...] = ()


def issue_plan_sources(plan, facts, seen=frozenset()):
    """E0 dependencies, including P -> Cq, without reading a published plan."""
    if plan.unit in seen:
        return frozenset()
    works = {g.key for g in plan.guards if g.kind in ('first', 'outcome', 'definite_verification')}
    refs = set()

    def collect(value):
        if _type(value, 'PlanRef'):
            refs.add(value.unit)
        elif _type(value, 'Source') and value.kind in (
                'first_receipt', 'generation', 'outcome', 'outcome_kind', 'outcome_content',
                'started_clock', 'finished_clock'):
            works.add(value.key)
        return value

    _map_frozen((plan.records, plan.guards), collect)
    for unit in refs - {plan.unit}:
        other = facts.plans.get(unit)
        if other is not None:
            works.update(issue_plan_sources(other, facts, seen | {plan.unit}))
    return frozenset(works)


def issue_occurrences(facts):
    """C-06: registration-table births from E0 + EH/EW/EL/EA (1241/1307).

    No Publish event, P flag or actual plan creates this population. Missing
    full artifact/use/instance adapters are reported at the observed premise,
    not postponed until a successful issuance. False branch prerequisites do
    not manufacture success issues. Historical EndKnown/Saved evidence keeps
    the candidates present after issuance or later loss of current readiness.
    """
    by_function = {fn: cid for cid, fn, _ in COMPLETION_PREDICATES}
    required = []

    def add(predicate, witness, reason, *, occurred=None, binding=None, carrier=None):
        required.append(IssueOccurrence(by_function[predicate], witness, occurred,
                                        binding, carrier, (reason,) if reason else ()))

    # Boot's original declaration and both independently Saved receipt slots.
    for event in facts.trace.events:
        if event.tag != 'Accept' or event.value.envelope.event.kind != 'Boot':
            continue
        declaration = _get(event.value.envelope.event.fields, 'declaration')
        if _get(declaration, 'initial') is None:
            continue
        layout = next(r for r in facts.contract.receipt_layouts if r.kind == 'Boot')
        try:
            for slot, _, _ in layout.slots:
                facts.resolver.point(SlotKey(event.value.unit, slot))
        except UnresolvedDeclaration:
            continue
        plans = [p for p in facts.contract.plans if p.obligation_id == 'O-02'
                 and (p.works or any(r.contract.name == 'computation_requested' for r in p.records))]
        for witness in [UnitKey(p.unit) for p in plans] or [event.key]:
            add(direct_o02_initial, witness, 'Boot/initial Saved; initial-plan occurrence/owner correspondence')

    # ReadyN is not an occurrence guard. In particular /2 is unknown, not absent.
    covered_receipts = set()
    for derivation in facts.contract.derivations:
        try:
            facts.resolver.point(derivation.receipt)
            envelope = (resolve_receipt_source(facts.contract, facts.trace, derivation.envelope)[0]
                        if isinstance(derivation.envelope, ReceiptSource) else derivation.envelope)
        except UnresolvedDeclaration:
            continue
        covered_receipts.add(ReceiptKey(envelope.run, envelope.number))
        add(direct_o03_issue_q, derivation.request,
            'Saved delta receipt; issue instance/owner or full delta occurrence adapter',
            occurred=True if not derivation.unsupported else None)
    # Without a delta target relation, a Saved Received cannot tell us whether
    # o exists. Keep that precise uncertainty, rather than relying on a future Q.
    for event in facts.trace.events:
        if (event.tag != 'Accept' or event.key in covered_receipts
                or event.value.envelope.event.kind != 'Received'):
            continue
        layout = next(r for r in facts.contract.receipt_layouts if r.kind == 'Received')
        try:
            for slot, _, _ in layout.slots:
                facts.resolver.point(SlotKey(event.value.unit, slot))
        except UnresolvedDeclaration:
            continue
        add(direct_o03_issue_q, event.key,
            'Saved Received; delta target/occurrence relation unavailable, not an assertion that o exists')

    # EndKnown is reconstructed from full EH/EW and Saved first receipt, not
    # work.first or a window's generated issue/handle row.
    for descriptor in facts.contract.descriptors:
        known = facts.end(descriptor.work_id)
        if known is None:
            continue
        outcome = _get(known[0].event.fields, 'outcome')
        success = outcome.kind == 'Success'
        variant = _get(outcome.content, 'variant')
        if descriptor.stage == 'Wr' and success and variant == 'Success':
            plans = [p for p in facts.contract.plans if p.obligation_id == 'O-06'
                     and any(r.contract.name == 'computation_result' for r in p.records)
                     and descriptor.work_id in issue_plan_sources(p, facts)]
            if not plans:
                add(direct_o06_issue_r, WorkKey(descriptor.work_id),
                    'first Wr Success; no independent R plan/instance correspondence')
            for plan in plans:
                slots = tuple(SlotKey(plan.unit, r.slot) for r in plan.records
                              if r.contract.name == 'computation_result')
                carrier = next((b for b in facts.contract.completions
                                if b.key.obligation == 'O-05' and b.key.kind == 'handle'
                                and b.source == WorkKey(descriptor.work_id)), None)
                binding = CompletionBinding(CompletionKey('O-06', plan.key, 'issue', slots[0]),
                    'EndKnown', WorkKey(descriptor.work_id), slots, Owner('P.work', descriptor.work_id))
                # The same finite E0 permission boundary as PUB: unsupported
                # semantic/use closures stay unknown. Resolve Q/inputs/output
                # before any EU issuance; a static recipe alone is insufficient.
                connected = not (plan.semantic_limits or plan.use_keys or descriptor.semantic_limits
                                 or descriptor.use_keys) and carrier is not None
                try:
                    record = facts.resolver.resolve(facts.resolver.sources(facts.record(slots[0])))
                    request = facts.resolver.resolve(descriptor.request)
                    inputs = facts.resolver.resolve(descriptor.input_points)
                    connected = connected and all(ledger_saved(p, facts.trace, facts.contract.codec) for p in inputs)
                    connected = connected and _get(record.content, 'request') == request == known[1].request
                    connected = connected and _get(record.content, 'output') == _get(outcome.content, 'output')
                    connected = connected and all(g.kind in ('first', 'outcome')
                        and g.key == descriptor.work_id
                        and (g.kind != 'outcome' or g.value == (outcome.kind, variant)) for g in plan.guards)
                except (UnresolvedDeclaration, AttributeError):
                    connected = False
                add(direct_o06_issue_r, UnitKey(plan.unit),
                    '' if connected else 'first Wr Success; Q/input/generation/use or original-carrier adapter',
                    occurred=True if connected else None,
                    binding=binding if connected else None, carrier=carrier if connected else None)
        elif descriptor.stage == 'Wp' and success and variant == 'Success':
            plans = [p for p in facts.contract.plans if p.obligation_id == 'O-07'
                     and any(r.contract.name in ('computation_proof', 'computation_completed') for r in p.records)
                     and descriptor.work_id in issue_plan_sources(p, facts)]
            for witness in [UnitKey(p.unit) for p in plans] or [WorkKey(descriptor.work_id)]:
                add(direct_o07_issue_pc, witness,
                    'first Wp Success; Q/R/statement/checker/generation and P/Cq issue-instance adapter')
        elif descriptor.stage == 'Ep' and success:
            add(direct_o10_issue, WorkKey(descriptor.work_id),
                'first Ep return; issued artifact/FProblem-or-NoDecision/EQ/root occurrence adapter')
        elif descriptor.stage == 'D' and outcome.kind in ('Success', 'Unknown'):
            add(direct_o11_issue, WorkKey(descriptor.work_id),
                'first D value/Unknown; full Draw request and generation-use occurrence adapter')
        elif descriptor.stage == 'Ee' and success:
            add(direct_o12_issue_ev, WorkKey(descriptor.work_id),
                'first Ee return; confirmed artifact/PR/Draw/request occurrence adapter')
            if variant == 'Selected':
                add(direct_o12_issue_s, WorkKey(descriptor.work_id),
                    'first Ee Selected; Saved EV/certified Selected/root/Draw/request occurrence adapter')

    # Cq + declared undertaking, not Acquire or G Publish. The existing EA
    # transport has no separate acceptance-of-intent event: retain that gap.
    for acquisition in facts.contract.acquisitions:
        try:
            completion = facts.resolver.resolve(acquisition.completion)
        except UnresolvedDeclaration:
            continue
        if ledger_saved(completion, facts.trace, facts.contract.codec):
            add(direct_o08_issue_g, acquisition.key,
                'Saved Cq and E0 acquisition intent; undertaking/issue-instance adapter')

    # S has a separate birth; neither Ee Unknown nor mere EV Publish creates it.
    # Use the already declared S instance's evaluated reference (1045), without
    # inventing an EV contract name for the unconnected artifact wire.
    for plan in facts.contract.plans:
        if plan.obligation_id != 'O-12':
            continue
        for record in plan.records:
            if record.contract.name != 'decision':
                continue
            evaluated = _get(record.content, 'evaluated')
            if evaluated is None:
                continue
            try:
                point = facts.resolver.resolve(evaluated)
            except UnresolvedDeclaration:
                continue
            if ledger_saved(point, facts.trace, facts.contract.codec):
                add(direct_o12_issue_s, UnitKey(plan.unit),
                    'Saved evaluated target; EV/certified Selected/root/Draw/request occurrence adapter')
    return tuple(required)


def issue_instance_matches(binding, occurrence, facts):
    predicate = completion_predicate(binding, facts)
    if not any(cid == occurrence.condition_id and fn is predicate for cid, fn, _ in COMPLETION_PREDICATES):
        return False
    witness = occurrence.witness
    return (binding.source == witness or binding.key.target == witness
            or isinstance(witness, UnitKey) and any(s.unit == witness.unit for s in binding.slots)
            or isinstance(witness, SlotKey) and witness in binding.slots)


def unmapped_completion_roles(facts):
    """Keep missing instance adapters visible; the 44-ID registry is not E0.

    In particular the current public declarations omit most issue instances and
    spell Wv's post-return handle as O-09.a, not O-09.b. Do not silently alias
    those identities, infer absence of the responsibility, or count a pass.
    """
    declared = [(completion_predicate(b, facts), b) for b in facts.contract.completions]
    by_function = {fn: cid for cid, fn, _ in COMPLETION_PREDICATES}
    required = set()

    def add(predicate, witness):
        def same_instance(binding):
            if binding.source == witness or binding.key.target == witness:
                return True
            if isinstance(witness, UnitKey):
                return any(s.unit == witness.unit for s in binding.slots)
            if isinstance(witness, SlotKey):
                return witness in binding.slots
            return False

        if not any(fn is predicate and same_instance(binding) for fn, binding in declared):
            required.add(UnconnectedCompletion(by_function[predicate], witness))

    for event in facts.trace.events:
        if event.tag == 'Publish':
            plan = facts.plans.get(event.key.unit)
            if plan is None:
                continue
            for descriptor in plan.works:
                if descriptor.stage == 'Wv':
                    add(direct_o09b_handle, WorkKey(descriptor.work_id))
        elif event.tag == 'Acquire':
            add(direct_o08_handle, event.key)
        elif event.tag == 'ReportGenerated':
            add(direct_o13_handle, event.key)
    return tuple(sorted(required, key=repr))


def contrast_result(*, normative, detected, reached, complete, connected=True, outside=False):
    """1590-1627: execution/confirmation and discrimination are separate axes."""
    confirmation = ('範囲外★' if outside else '未接続' if not connected else
                    '未確認' if not reached else '確認済み' if complete else '未完')
    result = ('判定未成立' if not reached or normative not in ('合法', '違反') else
              '合法対照の誤検出' if normative == '合法' and detected else
              '合法対照を許容' if normative == '合法' else
              '違反対照を検出' if detected else '違反対照の見逃し')
    legacy = ('範囲外' if outside else '検出できず' if result == '違反対照の見逃し' else '未到達・未完')
    # One contrast cannot by itself establish BOTH controls' discrimination.
    return confirmation, result, legacy


def evaluate_condition_custody(contract: ObservationE0, trace: ObservationTrace, state,
                               *, before_state=None) -> ObservationEvaluation:
    """C-05, 1307/1346-1351: E0/observations + all previous unmet, at every edge.

    Missing conclusion connections remain in judgements/limitations. Independent
    p/save violations still report; an unknown conclusion is never false by fiat.
    """
    clauses, limitations = [], set()
    rows = getattr(getattr(getattr(state, "core", None), "p", None), "conditions", None)
    old_rows = (getattr(getattr(getattr(before_state, "core", None), "p", None), "conditions", None)
                if before_state is not None else ())
    if rows is None or old_rows is None:
        return ObservationEvaluation(BoundaryReport("約束接続・部分判定", ()), (), tuple(
            (row, "約束の未接続: actual condition-owner snapshots") for row in ("INV-2.a", "INV-2.c")))
    errors = (_shape_errors(rows, tuple[_public("ConditionCustody"), ...], "P.conditions")
              + _shape_errors(old_rows, tuple[_public("ConditionCustody"), ...], "before.P.conditions"))
    if errors:
        failures = tuple(BoundaryViolation("P.conditions", error, Paper(("C-O01..14",), (1185, 1193)))
                         for error in errors)
        return ObservationEvaluation(BoundaryReport("約束違反", failures), (), ())
    current, old = {c.key: c for c in rows}, {c.key: c for c in old_rows}
    bindings = {b.key: b for b in contract.completions}
    facts = CompletionFacts(contract, trace, state)
    judgements = []

    def require(condition, message, target=None):
        for row in ("INV-2.a", "INV-2.c"):
            clauses.append(ClauseResult(row, bool(condition), message, target))

    require(len(current) == len(rows) and len(old) == len(old_rows),
            "actual custody contains duplicate condition identities")
    issue_families = {'O-02', 'O-03', 'O-06', 'O-07', 'O-08', 'O-10', 'O-11', 'O-12'}
    occurrences = {b.key: (False if b.key.kind == 'issue' and b.key.obligation in issue_families
                           else completion_occurred(b, contract, trace)) for b in contract.completions
                   if b.key.obligation != 'O-G'}
    issue_carriers = {}
    issue_instances = set()
    independent_issues = issue_occurrences(facts)
    for occurrence in independent_issues:
        matches = [b for b in contract.completions if issue_instance_matches(b, occurrence, facts)]
        if occurrence.binding is not None and not matches:
            matches = [occurrence.binding]
            bindings[occurrence.binding.key] = occurrence.binding
        if occurrence.occurred is True and matches:
            for binding in matches:
                occurrences[binding.key] = True
                issue_instances.add(binding.key)
                if occurrence.carrier is not None:
                    issue_carriers[binding.key] = occurrence.carrier
        else:
            for binding in matches:
                if occurrences.get(binding.key) is not True:
                    occurrences[binding.key] = None
            target = UnconnectedCompletion(occurrence.condition_id, occurrence.witness)
            reason = 'issue occurrence/instance: ' + repr(target) + ': ' + '; '.join(occurrence.reasons)
            facts.gap(reason)
            judgements.append(CustodyJudgement(target, '未接続', None, None, (reason,)))
    check_excess_occurrences(facts, bindings,
        lambda b: excess_occurrence(b, facts, independent_issues),
        clauses, judgements, ('INV-2.a', 'INV-2.c'),
        exclude_generation=any(d.stage == 'Wg' for d in contract.descriptors))
    born = {key for key, occurred in occurrences.items() if occurred is True}
    for key, occurred in occurrences.items():
        if occurred is None:
            facts.gap('condition occurrence adapter: ' + repr(key))
            judgements.append(CustodyJudgement(key, '未接続', None, None, ('occurrence adapter',)))
    previous = {key for c in old_rows for key in c.unmet}
    for target in unmapped_completion_roles(facts):
        reason = 'observed role has no E0 occurrence/condition-instance/branch adapter: ' + repr(target)
        facts.gap(reason)
        judgements.append(CustodyJudgement(target, '未接続', None, None, (reason,)))
    # Actual promises stay in the denominator even when EU is not a lawful plan.
    promised = set()
    for event in trace.events:
        if event.tag != 'Publish':
            continue
        plan = event.value.plan
        for descriptor in plan.works:
            actual = facts.work.get(descriptor.work_id)
            require(actual is not None and actual.descriptor == descriptor,
                    'actual promised work lost its matching P.work responsibility', WorkKey(descriptor.work_id))
        for record in plan.records:
            slot = SlotKey(plan.unit, record.slot)
            matches = [b.key for b in contract.completions if b.key.kind == 'save' and slot in b.slots]
            if matches:
                promised.update(matches)
            else:
                key = CompletionKey(plan.obligation_id, plan.key, 'save', slot)
                promised.add(key)
                bindings.setdefault(key, CompletionBinding(key, 'Publish', UnitKey(plan.unit), (slot,), Owner('P.units', plan.unit)))
    for key in sorted((k for k in born | previous | promised if k.obligation != 'O-G'), key=repr):
        # 1199/1311/1588: unknown birth is not unknown discharge. Previous
        # unmet and actual promises remain subject to independently evaluated
        # Direct/Transfer/Owner; the birth limitation above is still reported.
        held = current.get(key)
        binding = bindings.get(key)
        retained = condition_owner(binding, held, facts)
        # O-06's original unmet Wr handle may carry the not-yet-issued goal.
        # A previously explicit issue row cannot silently fall back to it after
        # deletion; no new window flag is required to establish the population.
        if key in issue_carriers and held is None and key not in old:
            carrier = issue_carriers[key]
            retained = condition_owner(carrier, current.get(carrier.key), facts)
        elif key in issue_instances and held is None and key not in old:
            retained = None
        predicate = completion_predicate(binding, facts)
        start_gaps = set(facts.gaps)
        direct = predicate(binding, facts) if predicate is not None else facts.gap('independent conclusion for ' + repr(key))
        if retained is None and key in issue_instances and direct is not True:
            facts.gap('pre-publication issue has no original-carrier adapter: ' + repr(key))
        transfer = condition_transfer(binding, facts)
        classification = ('未接続' if retained is None and direct is not True and transfer is not True
                          else classify_custody(direct, transfer, retained))
        judgements.append(CustodyJudgement(key, classification, direct, transfer, tuple(sorted(facts.gaps - start_gaps))))
        if classification != '未接続':
            require(classification != '削除・消去の違反',
                    'occurred unmet condition was deleted/cleared or lost its actual owner without Direct/Transfer', key)
        if binding is not None:
            if key.obligation == 'O-04' and key.kind == 'handle':
                parts = facts.cells(binding)
                for part in parts if parts is not None else ():
                    local_direct = facts.cell_direct(binding, part)
                    carried = facts.cell_owned(binding, part, retained)
                    local = classify_custody(local_direct, False, carried)
                    if carried is None and local_direct is not True:
                        local = '未接続'
                    target = ConditionPart(key, part)
                    judgements.append(CustodyJudgement(target, local, local_direct, False))
                    if local != '未接続':
                        require(local != '削除・消去の違反',
                                'fixed cell lost its own unmet/actual owner; other cells cannot discharge it', target)
            for part in required_purpose_parts(binding, facts):
                carried = purpose_carried(part, facts)
                judgements.append(CustodyJudgement(part, classify_custody(False, False, carried), False, False))
                require(carried, 'D3 residual purpose lost original identity/unmet/actual owner', part)
    for reason in facts.gaps:
        for row in ('INV-2.a', 'INV-2.c'):
            limitations.add((row, '約束の未接続: ' + reason))
    generation = evaluate_generation_custody(contract, trace, state, before_state=before_state)
    return ObservationEvaluation(BoundaryReport("約束接続・部分判定", ()), tuple(clauses) + generation.clauses,
                                 tuple(sorted(limitations | set(generation.limitations))),
                                 merge_unconnected_judgements((*judgements, *generation.custody)))


def merge_unconnected_judgements(judgements):
    """One unknown target, retaining both occurrence and conclusion reasons."""
    merged, positions = [], {}
    for item in judgements:
        if item.classification != '未接続':
            merged.append(item)
            continue
        if item.target not in positions:
            positions[item.target] = len(merged)
            merged.append(item)
            continue
        index = positions[item.target]
        previous = merged[index]
        merged[index] = CustodyJudgement(item.target, '未接続',
            previous.direct if previous.direct is not None else item.direct,
            previous.transfer if previous.transfer is not None else item.transfer,
            tuple(dict.fromkeys((*previous.reasons, *item.reasons))))
    return tuple(merged)


def claimed_conditions(state):
    """Actual claims are the population to audit, never evidence of birth."""
    return (set(getattr(state.evidence, 'condition_births', ()))
            | {c.key for c in state.core.p.conditions}
            | {key for c in state.core.p.conditions for key in c.unmet})


def check_excess_occurrences(facts, bindings, occurrence, clauses, judgements, rows,
                             *, exclude_generation=False, generation_only=False, exclude_keys=frozenset()):
    # 1192/1200/1311/1327: audit even cleared rows and historical birth claims.
    # A real (also unlawful) Publish still creates save/run custody; its legality
    # is checked separately. A claim cannot manufacture its own occurrence.
    for key in sorted(claimed_conditions(facts.state), key=repr):
        if key in exclude_keys:
            continue
        if exclude_generation and key.obligation == 'O-G':
            continue
        if generation_only and key.obligation != 'O-G':
            continue
        binding = bindings.get(key)
        occurred = occurrence(binding) if binding is not None else None
        if occurred is None:
            reason = 'excess occurrence adapter unconnected: ' + repr(key)
            facts.gap(reason)
            judgements.append(CustodyJudgement(key, '未接続', None, None, (reason,)))
        elif occurred is False:
            clauses.extend(ClauseResult(row, False,
                'condition claimed before independent occurrence', key) for row in rows)


def excess_occurrence(binding, facts, issues):
    """1192-1243: tri-state historical birth, not present operation readiness.

    Known absent necessary premises give False. Missing full use/intent/instance
    adapters give None; no issue witness is not by itself proof of absence.
    """
    predicate = completion_predicate(binding, facts)
    if predicate is None:
        return None
    key = binding.key
    if key.obligation == 'O-G':
        return None  # no Wg declaration: leave the claimed instance unconnected
    if key.kind == 'issue':
        matches = [o for o in issues if issue_instance_matches(binding, o, facts)]
        if any(o.occurred is True for o in matches):
            return True
        if matches:
            return None
        if key.obligation == 'O-02':
            boots = [e for e in facts.trace.events if e.tag == 'Accept'
                     and e.value.envelope.event.kind == 'Boot']
            if not boots or all(_get(_get(e.value.envelope.event.fields, 'declaration'), 'initial') is None
                                for e in boots):
                return False
            for event in boots:
                layout = next(r for r in facts.contract.receipt_layouts if r.kind == 'Boot')
                try:
                    for slot, _, _ in layout.slots:
                        facts.resolver.point(SlotKey(event.value.unit, slot))
                except UnresolvedDeclaration:
                    continue
                return None
            return False
        if key.obligation == 'O-03':
            derivations = [d for d in facts.contract.derivations if d.request in binding.slots]
            if not derivations:
                return None
            for d in derivations:
                try:
                    facts.resolver.point(d.receipt)
                except UnresolvedDeclaration:
                    continue
                return None  # full delta adapter, never ReadyN or Publish
            return False
        if key.obligation == 'O-08':
            intents = [a for a in facts.contract.acquisitions
                       if a.key in (binding.source, key.target)]
            if not intents:
                return None
            for intent in intents:
                try:
                    if ledger_saved(facts.resolver.resolve(intent.completion), facts.trace, facts.contract.codec):
                        return None  # acceptance of intent is a separate fact
                except UnresolvedDeclaration:
                    pass
            return False
        stage = {'O-06': 'Wr', 'O-07': 'Wp', 'O-10': 'Ep', 'O-11': 'D', 'O-12': 'Ee'}.get(key.obligation)
        work = getattr(binding.source, 'work', None)
        if work is None:
            plans = [facts.plans[s.unit] for s in binding.slots if s.unit in facts.plans]
            works = {w for p in plans for w in issue_plan_sources(p, facts)
                     if w in facts.descriptors and facts.descriptors[w].stage == stage}
            work = next(iter(works)) if len(works) == 1 else None
        descriptor = facts.descriptors.get(work)
        if descriptor is None or stage is None or descriptor.stage != stage:
            return None
        known = facts.end(work)
        if known is None:
            return False
        outcome = _get(known[0].event.fields, 'outcome')
        if stage == 'D':
            return None if outcome.kind in ('Success', 'Unknown') else False
        if outcome.kind != 'Success':
            return False
        if stage in ('Wr', 'Wp') and _get(outcome.content, 'variant') != 'Success':
            return False
        if predicate is direct_o12_issue_s and _get(outcome.content, 'variant') != 'Selected':
            return False
        return None
    if predicate in (direct_o08_handle, direct_o13_handle):
        return None  # intent undertaking / processing need not wired by Acquire/Post
    if predicate is direct_o09b_handle:
        if binding.trigger != 'Publish':
            return None
        return None if completion_occurred(binding, facts.contract, facts.trace) else False
    if predicate is direct_o14_stop and binding.trigger != 'Publish':
        return None  # 1243: undertaking, not the later Reserve
    if predicate is direct_o09a_v:
        work = getattr(binding.source, 'work', None)
        known = facts.end(work)
        if known is None:
            return False if work in facts.descriptors else None
        outcome = _get(known[0].event.fields, 'outcome')
        if outcome.kind in ('Failure', 'Unknown'):
            return False
        return None  # definite verification response correspondence
    return completion_occurred(binding, facts.contract, facts.trace)


@dataclass(frozen=True, slots=True)
class DerivationStatus:
    key: tuple[object, ...]
    eligible: bool
    published: bool
    matched: bool
    discharged: bool
    unsupported: tuple[str, ...]


def derive_observation_status(contract: ObservationE0, trace: ObservationTrace) -> tuple[DerivationStatus, ...]:
    """Executable G/Matchδ/Dischargeδ on the declared finite typed relation.

    Public SC-08: E0 enumerates the candidates; EU never supplies the denominator.
    ReceiptSource/PlanRef resolve at the pre-publication history root. Unknown
    inputs remain explicitly unsupported/unconnected, never an empty root.
    This does not invent ReadyN, reachability or unsupported /2 semantics.
    """
    trace = trace_at(trace, len(trace.events))
    prepared = {e.key: e.value.prepared for e in trace.events if e.tag == "FirstPrepare"}
    published = {e.key.unit: e.value.plan for e in trace.events if e.tag == "Publish"}

    def receipt_eligible(binding, root):
        first = next((e.value.prepared for e in root.events if e.tag == "FirstPrepare" and e.key == binding.receipt), None)
        acceptance = next((e.value for e in root.events if e.tag == "Accept" and e.value.envelope == binding.envelope), None)
        return bool(any(e.tag == "Post" and e.value.envelope == binding.envelope for e in root.events)
                    and acceptance is not None and first is not None
                    and acceptance.unit == binding.receipt.unit
                    and ledger_saved(first.point, root, contract.codec)
                    and _wire(first.record) == receipt_record_wire(contract, binding.envelope, acceptance.created, binding.receipt.slot))

    results = []
    for declared in contract.derivations:
        candidate = published.get(declared.request.unit)
        publication_index = next((i for i, e in enumerate(trace.events)
                                  if e.tag == "Publish" and e.key.unit == declared.request.unit), len(trace.events))
        root = trace_at(trace, publication_index)
        try:
            b = resolve_derivation_binding(contract, root, declared)
        except UnresolvedDeclaration as error:
            key = (declared.declaration, declared.version, declared.process, declared.reader,
                   declared.receipt, declared.purpose, declared.trigger_slot)
            results.append(DerivationStatus(key, False, candidate is not None, False, False,
                                            declared.unsupported + ("約束の未接続: " + str(error),)))
            continue
        receipt = prepared.get(b.receipt)
        eligible = receipt_eligible(b, root)
        full_key = (b.declaration, b.version, b.process, b.reader,
                    receipt.point if receipt is not None else b.receipt, b.purpose, b.trigger_slot)
        # Missing table meaning must not be repaired by a plausible Q.
        limitations = b.unsupported
        expected_plan = b.plan
        if _has_source(expected_plan):
            try:
                expected_plan = DeclarationResolver(contract, root).sources(b.plan)
            except UnresolvedDeclaration as error:
                limitations += ("約束の未接続: " + str(error),)
        group = []
        for other in contract.derivations:
            if other.request == b.request:
                try:
                    group.append(resolve_derivation_binding(contract, root, other))
                except UnresolvedDeclaration as error:
                    limitations += ("約束の未接続: " + str(error),)
        declared_group = frozenset(o.trigger_slot for o in group)
        group_ok = (declared_group == b.allowed_group and all(
            (o.declaration, o.version, o.process, o.reader, o.purpose, o.allowed_group)
            == (b.declaration, b.version, b.process, b.reader, b.purpose, b.allowed_group)
            and receipt_eligible(o, root) for o in group))
        descriptors = () if candidate is None else candidate.works
        work_matches = False
        for d in descriptors:
            try:
                actual = declaration_value(contract, root, (d.process, d.reader, d.purpose, d.stage_slot, d.method,
                                                            d.input_points, _get(d.args, "previous_result")))
            except UnresolvedDeclaration:
                continue
            work_matches |= actual == (b.process, b.reader, b.purpose, b.stage_slot, b.method, b.inputs, b.previous_result)
        roots_saved = all(ledger_saved(p, root, contract.codec) for p in b.root | b.inputs | b.evidence)
        receipt_in_root = receipt is not None and receipt.point in (b.inputs | b.evidence)
        matched = (eligible and not limitations and group_ok and candidate == expected_plan
                   and work_matches and roots_saved and receipt_in_root)
        q = prepared.get(b.request)
        planned = next((r for r in expected_plan.records if r.slot == b.request.slot), None)
        if planned is not None:
            try:
                planned = DeclarationResolver(contract, trace).resolve(planned)
            except UnresolvedDeclaration:
                planned = None  # keep the required edge; do not call it discharged
        discharged = bool(matched and q is not None and planned is not None
                          and ledger_saved(q.point, trace, contract.codec)
                          and (q.record.contract, q.record.category, q.record.content, q.record.references, q.parents)
                          == (planned.contract, planned.category, planned.content, planned.references, planned.parents))
        results.append(DerivationStatus(full_key, bool(eligible), candidate is not None, bool(matched), discharged, limitations))
    return tuple(results)


def evaluate_observation_step(contract, before, after, edge_events, *, before_state=None, after_state=None, action=None):
    """All edges, including identical I/O retry self-edges (A-IO).

    The trace is a finite summary; edge occurrences remain the authority for
    temporal order. A repeated EW event must never disappear by quotienting.
    """
    a = validate_observation_boundary(contract, before, edge_events)
    b = validate_observation_boundary(contract, after)
    if a.connection != "約束接続・部分判定" or b.connection != "約束接続・部分判定":
        failures = a.violations + b.violations
        return ObservationEvaluation(BoundaryReport("約束違反" if failures else "約束の未接続", failures), (), ())
    clauses, limitations = [], []

    def require(row, condition, message, target=None):
        clauses.append(ClauseResult(row, bool(condition), message, target))

    if before_state is not None or after_state is not None:
        custody = evaluate_condition_custody(contract, after, after_state, before_state=before_state)
        if custody.boundary.violations:
            return custody
        clauses.extend(custody.clauses)
        limitations.extend(custody.limitations)

    handoffs = tuple(e for e in edge_events if e.tag == "HandoffPurpose")
    if action is not None and action.operation == "HandoffPurpose":
        require("INV-2.c", bool(handoffs), "actual handoff edge lacks condition observations")
    if handoffs:
        old_rows = getattr(getattr(getattr(before_state, "core", None), "p", None), "conditions", None)
        new_rows = getattr(getattr(getattr(after_state, "core", None), "p", None), "conditions", None)
        if old_rows is None or new_rows is None:
            limitations.extend((row, "約束の未接続: actual condition-owner snapshots before/after handoff")
                               for row in ("INV-2.a", "INV-2.c"))
        else:
            errors = (_shape_errors(old_rows, tuple[_public("ConditionCustody"), ...], "before.P.conditions")
                      + _shape_errors(new_rows, tuple[_public("ConditionCustody"), ...], "after.P.conditions"))
            if errors:
                failures = tuple(BoundaryViolation("P.conditions", error, Paper(("C-O01..14",), (1185, 1193)))
                                 for error in errors)
                return ObservationEvaluation(BoundaryReport("約束違反", failures), (), ())
            old, new = {c.key: c for c in old_rows}, {c.key: c for c in new_rows}
            require("INV-2.c", len(old) == len(old_rows) and len(new) == len(new_rows),
                    "actual custody contains duplicate condition identities")
            event_keys = Counter(e.key for e in handoffs)
            require("INV-2.c", all(n == 1 for n in event_keys.values()), "duplicate condition handoff observation")
            for event in handoffs:
                key, value = event.key, event.value
                prior, following = old.get(key), new.get(key)
                require("INV-2.c", prior is not None and following is not None,
                        "handoff condition is absent in an actual custody snapshot", key)
                if prior is None or following is None:
                    continue
                # 1185/1193: a condition row has its own unmet set; the handoff
                # carries the obligation's union at the actual source owner.
                # Do not assume that EVERY row stores a copy of that union.
                group = frozenset(k for c in old_rows if c.owner == prior.owner
                                  and (c.key.obligation, c.key.obligation_key) == (key.obligation, key.obligation_key)
                                  for k in c.unmet)
                require("INV-2.c", key in value.before and value.before <= group and value.before == value.after,
                        "handoff changed actual unmet conditions or reported a different set", key)
                require("INV-2.c", (value.source, value.destination) == (prior.owner, following.owner),
                        "handoff source/destination differ from actual before/after custody", key)
                if prior.owner == following.owner:
                    limitations.append(("INV-2.c", "約束の未接続: same-owner atomic next-responsibility acceptance"))
                # 1337: members outside this transfer remain independently in
                # the common population. They need not all move to this owner.
                for member in value.before:
                    a_member, b_member = old.get(member), new.get(member)
                    require("INV-2.c", a_member is not None and b_member is not None
                            and a_member.owner == prior.owner and b_member.owner == following.owner
                            and member in a_member.unmet and member in b_member.unmet
                            and event_keys[member] == 1,
                            "handoff lost/renamed/achieved an actual unmet member or failed to transfer it", member)

    expected = list(before.events)
    for event in edge_events:
        if event.tag not in ("IORequest", "IOResponse", "ReadBack") or event not in expected:
            expected.append(event)
    require("INV-3.b", tuple(expected) == after.events, "state trace does not retain every actual event (only identical I/O may be quotiented)")
    require("INV-7.c", before.bodies <= after.bodies and before.entries <= after.entries, "actual C/E content was deleted or rewritten")
    writes = {e.value.written for e in edge_events if e.tag == "IOResponse" and e.value.written is not None}
    require("INV-4.c", (after.bodies - before.bodies) <= writes and (after.entries - before.entries) <= writes,
            "new C/E data lacks an independently observed actual I/O write")
    firsts = {e.key: e.value.prepared for e in before.events if e.tag == "FirstPrepare"}
    request_by_key = {e.key: e.value.prepared for e in before.events if e.tag == "IORequest"}
    accepted = {e.value.unit: e.value for e in before.events if e.tag == "Accept"}
    # Paper 797/801: key by the entire immutable original, not by P's copy or
    # by number alone. Preserve the FIRST preceding Accept, including on a
    # multi-event edge; a later bad retry must not become the baseline.
    first_accepts = {}
    for prior in before.events:
        if prior.tag == "Accept":
            first_accepts.setdefault(prior.value.envelope, prior.value)
    for event in edge_events:
        key, value = event.key, event.value
        if event.tag in ("Reserve", "EnterBody"):
            descriptor = next((d for d in contract.descriptors if d.work_id == key.work), None)
            require("INV-5.b", start_points_saved(contract, before, descriptor),
                    "actual reservation/entry edge precedes required Saved Points/permissions", key)
        if event.tag == "Release":
            require("INV-3.c", sum(e.tag == "Release" and e.key == key for e in before.events)
                    + sum(e.tag == "Release" and e.key == key for e in edge_events) <= 1,
                    "same actual holding released more than once on an edge", key)
        if event.tag in ("Acquire", "Adopt") and action is not None and action.operation == event.tag:
            require("INV-6.c", bool(action.target) and key.intent == action.target[0],
                    "actual acquisition/adoption intent differs from the selected independent intent", key)
        if event.tag == "Accept":
            first_accept = first_accepts.get(value.envelope)
            if first_accept is not None:
                require("INV-1.b", value.created == first_accept.created,
                        "reaccept creation time differs from the first Accept for this full original", key)
            elif before.clock is None:
                limitations.append(("INV-1.b", "約束の未接続: actual clock at Accept"))
            else:
                require("INV-1.b", value.created == before.clock, "Accept copied a creation time other than the actual host reading", key)
            first_accepts.setdefault(value.envelope, value)
        if event.tag == "Acquire":
            if before.clock is None:
                limitations.append(("INV-9.a", "約束の未接続: actual clock at acquisition"))
            else:
                require("INV-9.a", value.acquisition.reading == before.clock, "acquisition clock differs from actual acquisition edge", key)
        if event.tag == "IntervalUndertaken":
            if before.clock is None:
                limitations.append(("INV-12.a", "約束の未接続: actual clock at interval undertaking"))
            else:
                require("INV-12.a", value.reading == before.clock, "interval undertaking clock differs from its actual edge", key)
        if event.tag == "FirstPrepare":
            if key.unit not in accepted:
                plan = next((p for p in contract.plans if p.unit == key.unit), None)
                slot = next((s for s in plan.records if s.slot == key.slot), None) if plan else None
                if slot is not None and slot.at is None:
                    if before.clock is None:
                        limitations.append(("INV-4.c", "約束の未接続: actual clock at internal record creation"))
                    else:
                        require("INV-4.c", value.prepared.record.at == before.clock, "first preparation's s is not the actual creation clock", key)
        if event.tag == "IORequest":
            request_by_key[key] = value.prepared
            if key.operation == "AddEntry":
                prepared = value.prepared
                body_matches = lambda body: (_type(body, "Body") and body.seal == prepared.seal
                                             and body.salt == prepared.salt and body.payload == prepared.payload)
                confirmed = any((e.tag == "ReadBack" and body_matches(e.value.value))
                                or (e.tag == "IOResponse" and e.value.response == "acknowledged" and body_matches(e.value.written))
                                for e in before.events)
                require("INV-4.c", any(body_matches(body) for body in before.bodies) and confirmed,
                        "AddEntry before the actual body and a matching acknowledgement/readback", key)
        if event.tag == "IOResponse" and value.written is not None:
            request = request_by_key.get(key)
            require("INV-4.c", request is not None and key.operation in ("PutBody", "AddEntry"),
                    "write response has no preceding write request", key)
        if event.tag == "CloseSave":
            require("INV-4.c", all(s in firsts and ledger_saved(firsts[s].point, before, contract.codec) for s in value.slots),
                    "save condition was closed before its actual records were Saved", key)
        if event.tag == "Publish":
            at_publication = replace(before, events=before.events + (event,))
            for binding, status in zip(contract.derivations, derive_observation_status(contract, at_publication)):
                if binding.request.unit == value.plan.unit and status.published and not status.unsupported:
                    require("INV-2.b", status.matched, "Matchδ was false at the actual publication edge", status.key)
    # G is matched on the actual Saved edge, not required at Acquire. A later
    # Acquire event cannot retroactively justify a G already saved (1216-1217).
    acquisitions = [e for e in before.events if e.tag == "Acquire"]
    for entry in after.entries - before.entries:
        if (entry.header.record.contract.name, entry.header.record.contract.version) == ("content_acquired", "1"):
            try:
                candidates = [e for e in acquisitions if _acquisition_content_matches(contract, before, entry.header.record.content, e.value.acquisition)]
            except UnresolvedDeclaration as error:
                limitations.append(("INV-9.a", "約束の未接続: " + str(error)))
                continue
            require("INV-9.a", bool(candidates), "Saved G lacks a preceding actual acquisition matching origin/contents/clock", entry.point)
            if candidates and all(acquisition_record_reference(contract, after, e.key) is None for e in candidates):
                limitations.append(("INV-9.a", "約束の未接続: E0 intent -> G slot declaration"))
            elif candidates:
                require("INV-9.a", any(entry.point in acquisition_record_points(contract, after, e.key, e.value.acquisition) for e in candidates),
                        "Saved G does not match the independently declared intent/plan/slot", entry.point)
    # Claim reservation is one event containing all resources. Entry and token
    # consumption are the SAME step, not two separately observable states.
    consumed = Counter(e.key for e in edge_events if e.tag == "ConsumeToken")
    entered = Counter(e.key for e in edge_events if e.tag == "EnterBody")
    require("INV-3.a", consumed == entered and all(n == 1 for n in entered.values()), "token consumption and body entry are not atomic/unique")
    reads = Counter(e.key for e in edge_events if e.tag == "ReadInputs")
    require("INV-8.b", all(reads[k] == 1 for k in entered), "actual entry lacks its fixed input read in the same step")
    return ObservationEvaluation(a, tuple(clauses), tuple(limitations))


# MG-02: v0.18 1930-1961. All seven predicates have separate registration.
# The following adapter consumes E0 declarations and public observations only.
def _same_reference_set(serialized, expected):
    # E0-04 (1006): input/permission sets have no numerical application order.
    # Qgen's tuple serialization is fixed by E0 and compared in full at PUB/SV;
    # comparing its members to Desc must not require Ref.__lt__ or lose a member
    # through duplicate collapse. application_order is compared separately below.
    return (isinstance(serialized, tuple) and len(serialized) == len(expected)
            and all(_type(p, 'Point') or _type(p, 'PlanRef') for p in serialized)
            and frozenset(serialized) == expected)


def _generation_evaluation_refs(content):
    # 1935/1937, public EQ wire: tuples are ordered bindings, not one Point.
    # A malformed field must not become the empty set through _points().
    members = []
    for name in ('candidates', 'reader', 'model', 'preferences', 'context', 'o', 'j'):
        value = _get(content, name)
        if name in ('preferences', 'o', 'j') and isinstance(value, tuple):
            if name == 'preferences' and not value:
                return None
            values = value
        else:
            values = (value,)
        if not all(_type(p, 'Point') for p in values):
            return None
        if name != 'reader':
            members.extend(values)
    return tuple(members)


class GenerationFacts(CompletionFacts):
    def __init__(self, contract, trace, state):
        super().__init__(contract, trace, state)
        self.units = {u.id: u for u in state.core.p.units}
        self._branches, self._purposes, self._first_roots = {}, {}, {}
        self.before_state = None

    def descriptor_for(self, binding):
        source = binding.key.target if isinstance(binding.key.target, WorkKey) else binding.source
        if isinstance(source, WorkKey):
            return self.descriptors.get(source.work)
        unit = getattr(binding.key.target, 'unit', getattr(source, 'unit', None))
        plan = self.plans.get(unit)
        work = next((g.key for g in plan.guards if g.kind in ('generation', 'evaluation')), None) if plan else None
        return self.descriptors.get(work)

    def plan_for(self, descriptor, family):
        plans = [p for p in self.contract.plans if p.obligation_id == 'O-G'
                 and any(g.kind == ('generation' if family == 'CG' else 'evaluation')
                         and g.key == descriptor.work_id for g in p.guards)
                 and any(r.contract.name == ('candidate_declaration' if family == 'CG' else
                                             'sui.fb.evaluation_request') for r in p.records)]
        if len(plans) != 1:
            self.gap(f'{family}: unique E0 generation/evaluation plan for {descriptor.work_id}')
            return None
        return plans[0]

    def bindings(self, descriptor):
        selected = {}
        for binding in self.contract.completions:
            if binding.key.obligation == 'O-G' and self.descriptor_for(binding) == descriptor:
                predicate = completion_predicate(binding, self)
                if predicate is not None:
                    selected.setdefault(predicate, []).append(binding)
        # E0 defines instance spellings; it does not assert that they occurred.
        # Missing or duplicate adapters stay in the seven-member denominator.
        return {fn: values[0] for fn, values in selected.items() if len(values) == 1}

    def purpose(self, descriptor):
        run = CompletionKey('O-G', ('work', descriptor.work_id), 'run', WorkKey(descriptor.work_id))
        return PurposePart(run, (descriptor.purpose, descriptor.process, descriptor.reader,
                                descriptor.request, descriptor.stage_slot), descriptor.request)

    def request_matches(self, d):
        if not _type(d.request, 'PlanRef'):
            return self.gap('Qgen declaration requires a declared request slot')
        plan = self.plans.get(d.request.unit)
        record = next((r for r in plan.records if r.slot == d.request.slot), None) if plan else None
        if record is None:
            return False
        if (record.contract.name, record.contract.version, record.category) != ('sui.fb.candidate_request', '1', 'Event'):
            return False
        content = dict(record.content.items) if _type(record.content, 'Object') else {}
        expected = {key: getattr(d, key) for key in ('process', 'trigger', 'reader', 'purpose', 'stage_slot',
                    'method', 'output_contract', 'args', 'allocation', 'need')}
        input_points, permissions = content.pop('input_points', None), content.pop('permissions', None)
        numerical = content.pop('numerical_view', None)
        numerical_fields = dict(numerical.items) if _type(numerical, 'Object') else {}
        points = numerical_fields.pop('points', None)
        return (content == expected and _same_reference_set(input_points, d.input_points)
                and _same_reference_set(permissions, d.permissions)
                and _same_reference_set(points, d.numerical_view.points)
                and numerical_fields == {'application_order': d.numerical_view.application_order,
                                         'context': d.numerical_view.context}
                and (d.output_contract.name, d.output_contract.version) == ('sui.fb.candidate_generation', '1'))

    def branch(self, d):
        if d.work_id in self._branches:
            return self._branches[d.work_id]
        first = self.end(d.work_id)
        result = 'BeforeEnd'
        if first is not None:
            outcome = _get(first[0].event.fields, 'outcome')
            result = outcome.kind if outcome.kind in ('Failure', 'Unknown') else _get(outcome.content, 'variant')
            if result == 'Candidates':
                try:
                    declaration = self.resolver.resolve(_get(outcome.content, 'declaration'))
                    gen = _get(declaration, 'generation')
                    order = _get(declaration, 'input_order')
                    fixed = self.resolver.resolve(d)
                    required = {'model', 'input_order', 'measure', 'generation', 'continuation'}
                    good = (self.request_matches(d) is True and _type(declaration, 'Object')
                            and set(dict(declaration.items)) == required
                            and isinstance(order, tuple) and bool(order) and len(set(order)) == len(order)
                            and _get(declaration, 'model') == _get(fixed.numerical_view.context, 'model')
                            and _type(gen, 'Object') and set(dict(gen.items)) == {'generator', 'args', 'basis', 'draws'}
                            and _get(gen, 'generator') == fixed.method and _get(gen, 'args') == fixed.args
                            and _get(gen, 'basis') == _get(fixed.numerical_view.context, 'generation_basis')
                            and _get(gen, 'draws') == _get(fixed.args, 'draws') == ()
                            and _type(_get(declaration, 'continuation'), 'Object'))
                    result = 'Candidates' if good else 'Insufficient'
                except (UnresolvedDeclaration, TypeError):
                    result = 'Insufficient'
            elif result not in ('NoCandidates', 'Failure', 'Unknown'):
                self.gap('Wg reply variant/whole candidate-declaration contract')
                result = 'Unconnected'
        self._branches[d.work_id] = result
        return result

    def published(self, plan):
        return plan is not None and any(e.tag == 'Publish' and e.key.unit == plan.unit for e in self.trace.events)

    def first_end_root(self, d):
        if d.work_id not in self._first_roots:
            lo, hi = 0, len(self.trace.events)
            while lo < hi:
                mid = (lo + hi) // 2
                if observed_end_known(self.contract, trace_at(self.trace, mid), d.work_id) is None:
                    lo = mid + 1
                else:
                    hi = mid
            self._first_roots[d.work_id] = trace_at(self.trace, lo)
        return self._first_roots[d.work_id]

    def conflict(self, d, trace=None):
        # CMP-22: independently returned, source-corresponding *saved* originals.
        trace = trace or self.trace
        resolver = DeclarationResolver(self.contract, trace)
        sources = dict(self.contract.generation_sources)
        starts = [e.value.started for e in trace.events if e.tag == 'EnterBody' and e.key.work == d.work_id]
        try:
            request = resolver.resolve(d.request)
        except UnresolvedDeclaration:
            return False
        reports = set()
        for event in trace.events:
            if event.tag != 'Accept':
                continue
            envelope = event.value.envelope
            if (envelope.event.kind != 'WorkFinished' or _get(envelope.event.fields, 'work') != d.work_id
                    or envelope.source != sources.get(d.work_id)):
                continue
            layout = next(r for r in self.contract.receipt_layouts if r.kind == 'WorkFinished')
            try:
                for slot, _, _ in layout.slots:
                    resolver.point(SlotKey(event.value.unit, slot))
            except UnresolvedDeclaration:
                continue
            for actual in trace.events:
                if actual.tag != 'WorkerReturn' or actual.key.work != d.work_id:
                    continue
                gen = actual.value.generation
                if (gen.request == request and gen.stage == 'Wg' and gen.provenance == envelope.source
                        and gen.outcome.kind != 'Unknown' and len(starts) == 1 and gen.started == starts[0]
                        and (gen.outcome, gen.started, gen.finished) == tuple(_get(envelope.event.fields, k)
                                                                                 for k in ('outcome', 'started', 'finished'))):
                    reports.add(gen)
        return len(reports) > 1

    def start_conflict(self, descriptor):
        """840/852/867/1957: M3 upstream use at the current observation root.

        E0's evaluation guard identifies Wg for its promised Ep. The conflict
        comes from corresponding EW returns and Saved originals, never an Xc
        flag, custody reason, work phase, or missing EnterWorker operation.
        Other semantic/use-key closures remain the caller's explicit gaps.
        """
        upstream = {guard.key for plan in self.contract.plans if descriptor in plan.works
                    and plan.obligation_id == 'O-G' for guard in plan.guards
                    if guard.kind == 'evaluation'}
        unresolved = False
        for work in upstream:
            source = self.descriptors.get(work)
            if source is None or source.stage != 'Wg':
                unresolved = True
            elif self.conflict(source):
                return True
        if unresolved:
            return self.gap('M3 start-use dependency adapter is unconnected')
        return False

    def context_missing(self, d, trace):
        resolver = DeclarationResolver(self.contract, trace)
        missing = []
        for family in ('CG', 'EQ'):
            plan = self.plan_for(d, family)
            if plan is None:
                continue
            for guard in plan.guards:
                if guard.kind == 'generation_context':
                    try:
                        if not ledger_saved(resolver.resolve(guard.key), trace, self.contract.codec):
                            missing.append(guard.key)
                    except UnresolvedDeclaration:
                        missing.append(guard.key)
                elif guard.kind not in ('saved', 'generation', 'evaluation'):
                    self.gap('O-G use guard adapter: ' + guard.kind)
            if plan.semantic_limits or plan.use_keys:
                self.gap('O-G concrete semantic/use-key shortage adapter')
        return tuple(missing)

    def purpose_required(self, d):
        if d.work_id not in self._purposes:
            branch = self.branch(d)
            # Saved is monotone in this public model. An actual shortage at the
            # first EndKnown remains historical evidence after inputs arrive.
            self._purposes[d.work_id] = (branch != 'BeforeEnd' and
                (branch in ('NoCandidates', 'Failure', 'Unknown', 'Insufficient') or self.conflict(d)
                 or bool(self.context_missing(d, self.first_end_root(d)))))
            plans = [self.plan_for(d, family) for family in ('CG', 'EQ')]
            unsupported = branch == 'Unconnected' or any(p is None or p.semantic_limits or p.use_keys
                or any(g.kind not in ('saved', 'generation_context', 'generation', 'evaluation') for g in p.guards)
                for p in plans)
            if branch != 'BeforeEnd' and not self._purposes[d.work_id] and unsupported:
                self.gap('pG occurrence: concrete generation/evaluation use contract is unconnected')
                self._purposes[d.work_id] = None
        return self._purposes[d.work_id]

    def issue_cg_occurred(self, d):
        if self.branch(d) == 'Unconnected':
            return self.gap('issue[CG] occurrence: whole generation reply correspondence')
        if self.branch(d) != 'Candidates':
            return False
        plan = self.plan_for(d, 'CG')
        if plan is None:
            return None
        if plan.semantic_limits or plan.use_keys or any(g.kind not in ('generation', 'saved', 'generation_context') for g in plan.guards):
            return self.gap('issue[CG] occurrence: generation use prerequisites')
        first = self.first_end_root(d)
        contexts = [g.key for g in plan.guards if g.kind == 'generation_context']
        roots = [first]
        if contexts:
            # Historical birth survives later Conflict or a loss of readiness.
            roots += [trace_at(self.trace, i + 1) for i, e in enumerate(self.trace.events)
                      if i >= len(first.events) and e.tag in ('IOResponse', 'ReadBack')]
        for root in roots:
            resolver = DeclarationResolver(self.contract, root)
            try:
                usable = all(ledger_saved(resolver.resolve(ref), root, self.contract.codec) for ref in contexts)
            except UnresolvedDeclaration:
                usable = False
            if usable and not self.conflict(d, root):
                return True
        return False

    def continuation_matches(self, d):
        cg, eq = self.plan_for(d, 'CG'), self.plan_for(d, 'EQ')
        unit = self.units.get(cg.unit) if cg else None
        continuation = getattr(unit, 'generation', None)
        if continuation is None or eq is None:
            return False
        cr = next(r for r in cg.records if r.contract.name == 'candidate_declaration')
        er = next(r for r in eq.records if r.contract.name == 'sui.fb.evaluation_request')
        return (continuation.descriptor == d and continuation.purpose == self.purpose(d)
                and (continuation.candidate.unit, continuation.candidate.slot) == (cg.unit, cr.slot)
                and (continuation.evaluation.unit, continuation.evaluation.slot) == (eq.unit, er.slot))

    def purpose_carried(self, d):
        part = self.purpose(d)
        work = self.work.get(d.work_id)
        excuses = tuple(getattr(work, 'purposes', ()))
        cg = self.plan_for(d, 'CG')
        unit = self.units.get(cg.unit) if cg else None
        continuation = getattr(unit, 'generation', None)
        if continuation is not None and self.continuation_matches(d):
            excuses += continuation.shortages
        if any(x.obligation_id == 'O-G' and x.obligation_key == part and x.completion_conditions == ('pG',)
               and x.witness is not None and bool(x.reason_id) for x in excuses):
            return work is not None and work.descriptor == d or self.continuation_matches(d)
        # Before an explicit local acceptance, the original, still-unmet handle
        # and unchanged descriptor reconstruct the original purpose (1324).
        handle = self.bindings(d).get(direct_og_handle)
        held = self.rows.get(handle.key) if handle else None
        return (work is not None and work.descriptor == d and held is not None
                and held.key in held.unmet and held.owner == Owner('P.work', d.work_id))

    def lawful_pub(self, d, family):
        plan = self.plan_for(d, family)
        if not self.published(plan):
            return False
        results = []
        for index, event in enumerate(self.trace.events):
            if event.tag != 'Publish' or event.key.unit != plan.unit:
                continue
            root = publication_root(self.trace, index)
            rf = GenerationFacts(self.contract, root, self.state)
            resolver = rf.resolver
            try:
                expected = resolver.plan(plan.unit)
                results.append(expected == event.value.plan)
                resolver.publication(expected.records, plan.unit)
                branch = rf.branch(d)
                results.append(None if branch == 'Unconnected' else branch == 'Candidates' and not rf.conflict(d))
                if family == 'CG':
                    results.append(not plan.works and len(plan.records) == 1
                        and (plan.records[0].contract.name, plan.records[0].contract.version, plan.records[0].category)
                        == ('candidate_declaration', '1', 'Prediction'))
                else:
                    cg = rf.plan_for(d, 'CG')
                    cg_record = next(r for r in cg.records if r.contract.name == 'candidate_declaration') if cg else None
                    results.append(cg_record is not None and rf.published(cg))
                    if cg_record is not None:
                        resolver.point(SlotKey(cg.unit, cg_record.slot))
                    results.append(len(plan.works) == 1 and plan.works[0].stage == 'Ep' and len(plan.records) == 1)
                    record = resolver.publication(plan.records[0], plan.unit)
                    content = record.content
                    results.append((record.contract.name, record.contract.version, record.category)
                                   == ('sui.fb.evaluation_request', '1', 'Event'))
                    results.append(all(ledger_saved(p, root, self.contract.codec) for p in _points(content)))
                    ep = plan.works[0] if plan.works else None
                    results.append(_type(content, 'Object') and set(dict(content.items)) ==
                                   {'candidates', 'reader', 'model', 'preferences', 'context', 'o', 'j'})
                    if ep is not None and cg_record is not None:
                        results.append(_get(content, 'candidates') == resolver.point(SlotKey(cg.unit, cg_record.slot))
                            and _get(content, 'reader') == resolver.resolve(d.reader)
                            and _type(ep.request, 'PlanRef') and (ep.request.unit, ep.request.slot) == (plan.unit, record.slot))
                        fixed = resolver.publication(ep, plan.unit)
                        members = _generation_evaluation_refs(content)
                        results.append(_get(content, 'model') == _get(fixed.numerical_view.context, 'model')
                            and _get(content, 'context') == _get(fixed.numerical_view.context, 'context')
                            and members is not None
                            and all(p in fixed.input_points | fixed.numerical_view.points for p in members)
                            and fixed.reader == resolver.resolve(d.reader) and fixed.purpose == d.purpose)
                        context = dict(fixed.numerical_view.context.items)
                        results.append(all(context[k] == _get(content, k)
                                           for k in ('preferences', 'o', 'j') if k in context))
                for guard in plan.guards:
                    if guard.kind in ('saved', 'generation_context'):
                        results.append(ledger_saved(resolver.resolve(guard.key), root, self.contract.codec))
                    elif guard.kind not in ('generation', 'evaluation'):
                        results.append(self.gap('O-G PUB guard: ' + guard.kind))
                if plan.semantic_limits or plan.use_keys:
                    results.append(self.gap('O-G PUB semantic/use closure'))
                self.gaps.update(rf.gaps)
            except UnresolvedDeclaration:
                results.append(False)
        return _truth_all(results)

    def held(self, binding, d):
        row = self.rows.get(binding.key)
        if row is None or row.key not in row.unmet:
            return False
        predicate = completion_predicate(binding, self)
        if row.owner == Owner('P.work', d.work_id):
            return (predicate in (direct_og_run, direct_og_t, direct_og_handle, direct_og_issue_cg)
                    and d.work_id in self.work and self.work[d.work_id].descriptor == d)
        if row.owner.location == 'P.units':
            if predicate is direct_og_run:
                return False  # 1941: the actual Wg work row is required.
            if binding.key.kind == 'save':
                if row.owner.key not in self.units:
                    return False
                try:
                    expected = self.resolver.plan(row.owner.key)
                except UnresolvedDeclaration:
                    return self.gap('save actual owner -> fixed record plan')
                return all(s.unit == row.owner.key and any(x.plan == r for x in self.units[row.owner.key].slots
                    for r in expected.records if r.slot == s.slot) for s in binding.slots)
            cg = self.plan_for(d, 'CG')
            return cg is not None and row.owner.key == cg.unit and self.continuation_matches(d)
        return False

    def missing_acceptance(self, unit, reason):
        # A current publication edge supplies the actual acceptance snapshot.
        # Later missing custody cannot disprove an earlier atomic acceptance;
        # without that snapshot, keep its local conclusion unconnected (1588).
        if self.before_state is not None:
            previous = self.before_state.evidence.observation_trace
            if any(e.tag == 'Publish' and e.key.unit == unit for e in self.trace.events[len(previous.events):]):
                return False
        return self.gap(reason + ': historical atomic acceptance snapshot is absent')


def direct_og_run(b, f):
    return f.run(b, 'Wg')


def direct_og_t(b, f):
    return f.end_save(b, 'Wg')


def direct_og_handle(b, f):
    return False  # 1943: only a permitted Transfer can close local handling.


def direct_og_issue_cg(b, f):
    d = f.descriptor_for(b)
    lawful = f.lawful_pub(d, 'CG')
    if lawful is not True:
        return lawful
    bindings = f.bindings(d)
    for fn in (direct_og_save_cg, direct_og_issue_eq):
        other = bindings.get(fn)
        if other is None:
            return f.gap('CG PUB -> simultaneous save[CG]/issue[EQ] instance adapter')
        if not (fn(other, f) is True or f.held(other, d)):
            return f.missing_acceptance(f.plan_for(d, 'CG').unit, 'CG save/issue acceptance')
    return True


def direct_og_save_cg(b, f):
    return f.sv(b)


def direct_og_issue_eq(b, f):
    d = f.descriptor_for(b)
    lawful = f.lawful_pub(d, 'EQ')
    if lawful is not True:
        return lawful
    eq = f.plan_for(d, 'EQ')
    ep = eq.works[0]
    actual = f.work.get(ep.work_id)
    run = CompletionKey('O-10', ('work', ep.work_id), 'run', WorkKey(ep.work_id))
    row = f.rows.get(run)
    actual_owner = (actual is not None and actual.descriptor == ep
            and (f.end(ep.work_id) is not None or row is not None and run in row.unmet
                 and row.owner == Owner('P.work', ep.work_id)))
    if not actual_owner:
        return f.missing_acceptance(eq.unit, 'EQ Ep/run/original-purpose acceptance')
    required = f.purpose_required(d)
    return _truth_all((actual_owner, None if required is None else not required or f.purpose_carried(d)))


def direct_og_save_eq(b, f):
    return f.sv(b)


GENERATION_PREDICATES = (
    ('C-OG.run[Wg]', direct_og_run, 1941), ('C-OG.save[T]', direct_og_t, 1942),
    ('C-OG.handle[Wg]', direct_og_handle, 1943), ('C-OG.issue[CG]', direct_og_issue_cg, 1944),
    ('C-OG.save[CG]', direct_og_save_cg, 1945), ('C-OG.issue[EQ]', direct_og_issue_eq, 1946),
    ('C-OG.save[EQ]', direct_og_save_eq, 1947),
)
COMPLETION_PREDICATES += GENERATION_PREDICATES


def check_inv_16c(f, d):
    """1961 / 1931,1933,1935: full request -> actual generation -> CG -> EQ."""
    clauses = [ClauseResult('INV-16.c', f.request_matches(d) is not False,
                            'Qgen differs from the whole fixed Wg descriptor', WorkKey(d.work_id))]
    if _type(d.request, 'PlanRef') and d.request.unit in f.units:
        original = f.record(SlotKey(d.request.unit, d.request.slot))
        actual = next((s.plan for s in f.units[d.request.unit].slots if s.plan.slot == d.request.slot), None)
        clauses.append(ClauseResult('INV-16.c', actual == original,
            'Qgen actual fixed plan changed a field of the original request', SlotKey(d.request.unit, d.request.slot)))
    # Paper 1004/1006/1931/1961: Qgen fixes the entire generation input.
    # Compare actual EW reads at their own historical roots, without waiting
    # for a return/CG/EQ or trusting the window's supplied resolution table.
    for index, event in enumerate(f.trace.events):
        if event.tag != 'ReadInputs' or event.key.work != d.work_id:
            continue
        try:
            expected = DeclarationResolver(f.contract, trace_at(f.trace, index)).resolve(d)
            clauses.append(ClauseResult('INV-16.c', event.value.descriptor == expected
                and event.value.numerical_view == expected.numerical_view,
                'actual Wg input differs from the fixed Qgen descriptor/numerical view', (index, event.key)))
        except UnresolvedDeclaration as error:
            clauses.append(ClauseResult('INV-16.c', False,
                'actual Wg input used an unresolved or mismatching Qgen dependency: ' + str(error), (index, event.key)))
    draws = _get(d.args, 'draws', None)
    if draws != ():
        f.gap('R10/D6: generation randomness requires RG/Dg/O-GD; never replace draws with empty/fixed values')
        actual = f.work.get(d.work_id)
        if actual is not None:
            clauses.append(ClauseResult('INV-16.c', _get(actual.descriptor.args, 'draws', None) == draws,
                'D6 random generation declaration was coerced to empty/fixed draws', WorkKey(d.work_id)))
        for event in f.trace.events:
            if event.tag in ('EnterBody', 'WorkerReturn') and event.key.work == d.work_id:
                clauses.append(ClauseResult('INV-16.c', False,
                    'D6 unsupported random generation executed instead of remaining unconnected', WorkKey(d.work_id)))
    for family in ('CG', 'EQ'):
        plan = f.plan_for(d, family)
        if f.published(plan):
            lawful = f.lawful_pub(d, family)
            if lawful is not None:
                clauses.append(ClauseResult('INV-16.c', lawful,
                    'generation publication lacks full corresponding return/request/use prerequisites', UnitKey(plan.unit)))
            if family == 'CG' and any(_points(r.content) and not r.references for r in
                                      next(e.value.plan for e in f.trace.events if e.tag == 'Publish' and e.key.unit == plan.unit).records):
                f.gap('CG reference-path/meaning closure is not declared; full F-a validity remains unconnected')
    return clauses


def check_inv_2g(f, d, *, before_state=None):
    """1961 / 1937,1941-1959: independent occurrence, four classes, D3."""
    clauses, judgements = [], []
    bindings = f.bindings(d)
    branch = f.branch(d)
    initial = [p for p in f.contract.plans if d in p.works]
    promised = any(f.published(p) for p in initial)
    cg, eq = f.plan_for(d, 'CG'), f.plan_for(d, 'EQ')
    cg_lawful = f.lawful_pub(d, 'CG') if f.published(cg) else False
    born = {direct_og_run: promised, direct_og_t: branch != 'BeforeEnd',
            direct_og_handle: branch != 'BeforeEnd', direct_og_save_cg: f.published(cg),
            direct_og_issue_eq: cg_lawful,
            direct_og_save_eq: f.published(eq)}
    born[direct_og_issue_cg] = f.issue_cg_occurred(d)
    check_excess_occurrences(f, {b.key: b for b in bindings.values()},
        lambda b: born.get(completion_predicate(b, f)), clauses, judgements,
        ('INV-2.g',), generation_only=True, exclude_keys={b.key for b in f.contract.completions
            if b.key.obligation == 'O-G' and f.descriptor_for(b) is not None and f.descriptor_for(b) != d})
    previous = {c.key for c in before_state.core.p.conditions if c.key in c.unmet} if before_state else set()
    for cid, fn, _ in GENERATION_PREDICATES:
        binding = bindings.get(fn)
        if binding is None:
            if promised:
                reason = f'{cid}: missing/ambiguous E0 instance mapping for {d.work_id}'
                f.gap(reason)
                judgements.append(CustodyJudgement(UnconnectedCompletion(cid, WorkKey(d.work_id)), '未接続', None, None, (reason,)))
            continue
        if born[fn] is None:
            reason = cid + ': independent occurrence is unconnected'
            f.gap(reason)
            judgements.append(CustodyJudgement(binding.key, '未接続', None, None, (reason,)))
            continue
        if not born[fn] and binding.key not in previous:
            continue
        direct, transfer = fn(binding, f), False
        if fn is direct_og_handle:
            if f.purpose_required(d) is None:
                transfer = None
            elif branch == 'Candidates' and not f.purpose_required(d):
                issue = bindings.get(direct_og_issue_cg)
                transfer = issue is not None and (f.held(issue, d) or direct_og_issue_cg(issue, f) is True)
            elif f.purpose_required(d):
                # Same owner can accept a distinct residual responsibility.
                handle = f.rows.get(binding.key)
                transfer = f.purpose_carried(d) and (handle is None or binding.key not in handle.unmet)
        retained = f.held(binding, d)
        classification = ('未接続' if retained is None and direct is not True and transfer is not True
                          else classify_custody(direct, transfer, retained))
        judgements.append(CustodyJudgement(binding.key, classification, direct, transfer))
        if classification != '未接続':
            clauses.append(ClauseResult('INV-2.g', classification != '削除・消去の違反',
                'O-G condition lost its own Direct/Transfer or matching real owner', binding.key))
    required = f.purpose_required(d)
    if required is None:
        judgements.append(CustodyJudgement(f.purpose(d), '未接続', False, None,
                                           ('pG concrete use/branch occurrence',)))
    elif required:
        carried = f.purpose_carried(d)
        part = f.purpose(d)
        judgements.append(CustodyJudgement(part, classify_custody(False, False, carried), False, False))
        clauses.append(ClauseResult('INV-2.g', carried, 'D3 pG lost original run/Qgen identity or actual carrier', part))
    # Actual pG claims do not generate their own normative birth.
    work = f.work.get(d.work_id)
    excuses = list(getattr(work, 'purposes', ()))
    continuation = getattr(f.units.get(cg.unit) if cg else None, 'generation', None)
    if continuation is not None:
        excuses.extend(continuation.shortages)
    for excuse in excuses:
        if excuse.obligation_id == 'O-G' and required is not None:
            clauses.append(ClauseResult('INV-2.g', required and excuse.obligation_key == f.purpose(d)
                and excuse.completion_conditions == ('pG',) and excuse.witness is not None,
                'pG was invented for delivery/save wait or has changed its original target', f.purpose(d)))
    if f.published(cg) and not f.published(eq):
        clauses.append(ClauseResult('INV-2.g', f.continuation_matches(d),
            'CG-to-EQ continuation cannot reconstruct Qgen/reader/original purpose/target slots', UnitKey(cg.unit)))
    return clauses, judgements


def evaluate_generation_custody(contract, trace, state, *, before_state=None):
    f = GenerationFacts(contract, trace, state)
    f.before_state = before_state
    clauses, judgements = [], []
    for d in contract.descriptors:
        if d.stage != 'Wg':
            continue
        clauses.extend(check_inv_16c(f, d))
        local, custody = check_inv_2g(f, d, before_state=before_state)
        clauses.extend(local)
        # Existing condition/terminal rows share the enlarged population.
        clauses.extend(ClauseResult(row, c.satisfied, c.message, c.target)
                       for c in local for row in ('INV-2.a', 'INV-2.c'))
        judgements.extend(custody)
    limits = tuple((row, '約束の未接続: ' + reason) for reason in sorted(f.gaps)
                   for row in ('INV-2.g', 'INV-16.c'))
    return ObservationEvaluation(BoundaryReport('約束接続・部分判定', ()), tuple(clauses), limits,
                                 merge_unconnected_judgements(judgements))
