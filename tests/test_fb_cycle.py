"""K36-c/K36-c-a/K36-c-b v1.67: admission, roots and separate allocations.

Paper K36 v1.47 body :4998-5135 was read in full in request 83.
K36-b v1.55 :3568 was read in full in request 87; v1.56 (ni) and
INV-7.b :887 in 88; (nu) in 89; (ne) in 90; (no) in 91; (ne)/(no) in 92/93;
(ha) in 94; full (ha)/(chi) and related (ne)/(no) clauses in 95 (v1.61).
Request 96 rereads full (ha)/(ne)/(no) clauses for held-seat and root-order claims.
Request 97 reads Z62, K36-c and K36-c-a in full. Old seat-order/yield rules
and request96's C71/C72 are retired, not alternative accepted behaviors.
Request 98 reads K36-c-b in full; closes CG1-4 and uses the v1.65 stopped outcome.
Request 99 retries fixed records before restoring storage, then advances later roots.
Request 100 covers slot collisions, adoption ack-loss, unusable roots and zero quota.
Request 101 follows the decided adoption chain and rejects reuse of a conflicted Wg.
Request 102 uses declared target marginals for C94 and seat release for denied entry.
Request 103 observes perform results through the house and separates wrong D notices from stops.
Request 104 keeps a never-written adoption out of roots/materials until storage recovers.
Only public declarations/test helpers are used; adopted shapes are in k36_cycle_coverage.json.
All K36 names resolve per case, before fixture construction.

The environment is TEST. The seven actual workers come from start(), or the
same native classes in explicit low-level fault scenes. No script calls acquire.
Ordering uses Events and public storage cuts, never sleep lengths.
G/q expectations use entropy and exp(-J), not a second sui evaluation.
K36-a closes review/loop limitations as currently unreachable; no fake selections.
"""

from copy import deepcopy
from dataclasses import fields, replace
from decimal import Decimal, localcontext
from fractions import Fraction as Q
from itertools import product
import json
from threading import Event, Thread, RLock
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest

from sui import f, f_contracts as fc, f_entry as codec, fb, fb_contracts as c, f_update2 as u2
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role
from sui.rate import RateBudget
from gate_f_facts_cases import action, declaration, diagonal, outcome, plain, policy
from test_fb_skeleton import contract, slot, source, route
from test_fb_stage1 import RealRig, wire
from test_fb_stage2 import LaunchCut, ORDER
from test_fb_read import T, E, U, M, CONTROL, MODEL, read1_symbol


STAGES = ("measure_segment", "belief_update", "candidate_generation",
          "evaluation_prepare", "selection_draw", "evaluation", "execute_step")
P = ((Q(1), Q(0)), (Q(0), Q(1, 2)))
EMPTY = ((Q(0), Q(0)), (Q(0), Q(1, 2)))
I = ((Q(1), Q(0)), (Q(0), Q(1)))
N = ((Q(0), Q(1)), (Q(1), Q(0)))
ZERO = ((Q(0), Q(0)), (Q(0), Q(0)))
HALF = ((Q(1, 2), Q(0)), (Q(0), Q(1, 2)))
UNBOUNDED = RateBudget(tolerance=Q(1, 10**18), max_cells=None,
                       max_terms=None, max_refinements=None)
REQUESTS = {"measure_segment": c.SEGMENT_REQUESTED,
            "candidate_generation": c.CANDIDATE_REQUEST,
            "evaluation_prepare": c.EVALUATION_REQUESTED,
            "selection_draw": c.DRAW_REQUESTED,
            "belief_update": c.WORK_REQUESTED, "evaluation": c.WORK_REQUESTED}
WATCHDOG = 20


def cycle_api():
    required = ("start", "RunningSui", "Perception", "ExecuteStep", "ExecutionArgs",
                "StepExecutor", "FActor", "ExecutionResult", "PolicyStatus",
                "IntentionStatus", "ExecutionStatus", "StartInputError", "ExecutionReport",
                "ExecutionDeclaration", "EvaluationStatus", "ThinkingMaterialStatus")
    missing = [name for name in required if not hasattr(fb, name)]
    if not hasattr(fb.FWorkContext, "perform"): missing.append("FWorkContext.perform")
    missing += ["FStatus." + name for name in ("evaluations", "thinking_materials")
                if name not in {x.name for x in fields(fb.FStatus)}]
    if c.BOOT_DECLARATION.version != "5": missing.append("boot_declaration/5")
    if c.REUSE_CANDIDATES.version != "3": missing.append("reuse_candidates/3")
    assert not missing, "K36-c public shape missing: " + ", ".join(missing)
    assert "perception" in {x.name for x in fields(fb.BootDeclaration)}, "K36 Boot.perception missing"
    assert "execution" in {x.name for x in fields(fb.BootDeclaration)}, "K36 Boot.execution missing"
    return fb


def matmul(a, b):
    return tuple(tuple(sum((a[i][k] * b[k][j] for k in range(2)), Q(0))
                       for j in range(2)) for i in range(2))


def enumerate_updates(matrices, prior=(Q(1, 2), Q(1, 2))):
    """Independent sum over every state path, retaining its final state."""
    totals = [Q(0), Q(0)]
    for start in range(2):
        for path in product(range(2), repeat=len(matrices)):
            weight, previous = prior[start], start
            for matrix, arrival in zip(matrices, path):
                weight *= matrix[arrival][previous]
                previous = arrival
            totals[previous] += weight
    mass = sum(totals, Q(0))
    return (None if not mass else tuple(x / mass for x in totals)), mass


def information_and_probability(prior):
    """Zero path cost, counting measure, gamma=1: Gp-Gw=-I, qp=exp(I)/(1+exp(I))."""
    with localcontext() as ctx:
        ctx.prec = 80
        def dec(q): return Decimal(q.numerator) / Decimal(q.denominator)
        def entropy(ps): return -sum((dec(p) * dec(p).ln() for p in ps if p), Decimal(0))
        posterior, prob_t = enumerate_updates((P,), prior)
        _, prob_e = enumerate_updates((EMPTY,), prior)
        info = entropy(prior) - dec(prob_t) * entropy(posterior) if prob_t else entropy(prior)
        assert prob_t + prob_e == 1
        exp_i = info.exp()
        return +info, +(exp_i / (1 + exp_i))


def declared_one_step_information_and_probabilities(document, prior):
    """TEST oracle: complete one-step policies, blank cost, counting measure, gamma=1.

    F-a M-09 and the finite-model target map: sum observationally equal kernels,
    then marginalize joint states to X. Hidden law/state entropy is not H(X).
    No sui evaluation, selected result, or implementation supplies these numbers.
    """
    states, targets = document["states"], document["targets"]
    assert len(states) == len(prior) == 2 and sum(prior, Q(0)) == 1
    kernels = {kernel["id"]: kernel for kernel in document["kernels"]}
    policies = {policy["id"]: policy for policy in document["policies"]}
    def marginal(joint):
        return tuple(sum((p for state, p in zip(states, joint) if state["target"] == target), Q(0))
                     for target in targets)
    def rational(value):
        return Q(*value) if isinstance(value, (list, tuple)) else Q(value)
    with localcontext() as ctx:
        ctx.prec = 80
        def dec(q): return Decimal(q.numerator) / Decimal(q.denominator)
        def entropy(ps): return -sum((dec(p) * dec(p).ln() for p in ps if p), Decimal(0))
        information = {}
        for operation in document["operations"]:
            policy = policies[operation["policy"]["args"]["id"]]
            nodes = {node["id"]: node for node in policy["nodes"]}
            entry = nodes[policy["entry"]]
            assert entry["kind"] == "execute"
            assert all(nodes[next_id]["kind"] == "end" for next_id in entry["next"].values())
            assert operation["prediction"]["args"]["id"] == entry["kernel"]
            cells, columns = {}, [Q(0), Q(0)]
            for outcome in kernels[entry["kernel"]]["outcomes"]:
                assert outcome["completion"] and outcome["elapsed_ns"] == 0
                available = outcome["available"]
                assert available["computation"] is None
                emitted = outcome["evidence"]
                assert set(available["reveal"]) <= ({emitted["slot"]} if emitted else set())
                key = json.dumps(outcome["evidence"], sort_keys=True, separators=(",", ":"))
                matrix = [[rational(value) for value in row] for row in outcome["matrix"]]
                assert len(matrix) == 2 and all(len(row) == 2 for row in matrix)
                cell = cells.setdefault(key, [[Q(0), Q(0)], [Q(0), Q(0)]])
                for arrival, origin in product(range(2), repeat=2):
                    value = matrix[arrival][origin]
                    assert value >= 0
                    assert not value or states[arrival]["target"] == states[origin]["target"]
                    cell[arrival][origin] += value
                    columns[origin] += value
            assert columns == [Q(1), Q(1)]
            conditional_entropy = Decimal(0)
            for matrix in cells.values():
                posterior, probability = enumerate_updates((matrix,), prior)
                if probability:
                    conditional_entropy += dec(probability) * entropy(marginal(posterior))
            information[operation["id"]] = +(entropy(marginal(prior)) - conditional_entropy)
        weights = {name: info.exp() for name, info in information.items()}
        total = sum(weights.values(), Decimal(0))
        return information, {name: +(weight / total) for name, weight in weights.items()}


def passive_declaration(taken, empty):
    """Public K26 model constructors, without a legacy Boot/3 helper guard."""
    control = "sui.fb.acquisition_repeat_when_done/1"
    matrices = {T: taken, E: empty}
    kernel = f.FiniteKernel(id=control, outcomes=tuple(f.FiniteOutcome(
        id=s, elapsed_ns=0,
        evidence=f.EvidenceEmission(slot="acquisition", kind="measurement",
            value=read1_symbol(s), measurement_contract=c.ACQUISITION_RESULT_SAMPLING),
        available=f.AvailabilityChange(reveal=(), computation=None), completion=True,
        matrix=tuple(tuple(Q(x) for x in row) for row in matrix)) for s, matrix in matrices.items()))
    cells = tuple(f.ObservationCell(id=s, observation=f.ObservationValue(
        kind="measurement", value=read1_symbol(s)), outcomes=(s,)) for s in matrices)
    return fb.AcquisitionObservationModel(route_slot="route", states=("A", "B"),
        controls=(fb.AcquisitionControl(id=control, kernel=kernel, cells=cells),),
        control_rule=fb.MethodCall(contract=CONTROL, args={"first": [control],
            "after": {s: [control] for s in (T, E, U, M)}}),
        independence=fb.MethodCall(contract=contract("sui.fb.state_independent_control_selection"),
            args={"weights_by_initial_state": [[[1, 1]], [[1, 1]]]}),
        projection=c.ACQUISITION_RESULT_PROJECTION, time_projection=contract("sui.f.value_only"))


def world_document(*, prior=(Q(1, 2), Q(1, 2)), peek=P, empty=EMPTY,
                   exception=None, split=False, shape="end", aliases=False, targets=("A", "B")):
    """Declared finite world; no parsing of bytes/claims into a state label."""
    zero = 0
    outs = []
    groups = {T: [], E: [], U: []}
    components = [("t", peek)]
    if split:
        assert peek == HALF
        components = [("t0", ((Q(1, 2), 0), (0, 0))),
                      ("t1", ((0, 0), (0, Q(1, 2))))]
    for name, matrix in components:
        matrix = tuple(tuple(Q(x) for x in row) for row in matrix)
        outs.append(outcome(name, matrix, elapsed=zero, value=read1_symbol(T)))
        groups[T].append(name)
    outs.append(outcome("e", tuple(tuple(Q(x) for x in row) for row in empty), elapsed=zero, value=read1_symbol(E)))
    groups[E].append("e")
    if exception is not None:
        outs.append(outcome("x", tuple(tuple(Q(x) for x in row) for row in exception), elapsed=zero, value=read1_symbol(U)))
        groups[U].append("x")
    peek_kernel = {"id": "peek", "outcomes": outs}
    wait_kernel = {"id": "wait", "outcomes": [outcome("done", I, elapsed=0)]}
    operations = [action("wait", "wait"), action("peek", "peek")]
    nodes = [{"id": "first", "kind": "execute", "kernel": "peek",
              "next": {x["id"]: "end" for x in outs}}, {"id": "end", "kind": "end"}]
    if shape == "two":
        nodes[0]["next"] = {x["id"]: "second" for x in outs}
        nodes.insert(1, {"id": "second", "kind": "execute", "kernel": "peek",
                         "next": {x["id"]: "end" for x in outs}})
    elif shape == "branch":
        nodes[0]["next"] = {x["id"]: "second" if x["id"] in groups[T] else "end" for x in outs}
        nodes.insert(1, {"id": "second", "kind": "execute", "kernel": "wait", "next": {"done": "end"}})
    elif shape == "choose":
        nodes[0]["next"] = {x["id"]: "choose" for x in outs}
        nodes.insert(1, {"id": "choose", "kind": "choose", "operations": ["wait"],
                         "rule": plain(contract("sui.f.soft_choice")), "next": {"wait": "end"}})
    doc = declaration([wait_kernel, peek_kernel], operations,
                      [policy("wait", wait_kernel), {"id": "peek", "entry": "first", "nodes": nodes}],
                      states=[{"id": "A", "target": targets[0]}, {"id": "B", "target": targets[1]}],
                      targets=list(dict.fromkeys(targets)), initial=prior)
    if aliases:
        alias = deepcopy(doc["operations"][1]); alias["id"] = "peek-alias"
        doc["operations"].append(alias)
    return doc, groups


class Gate:
    def __init__(self, timeout=WATCHDOG):
        self.entered, self.release, self.timeout = Event(), Event(), timeout


class ToySource:
    """TEST passive world. Call order and cursor are independent witnesses."""
    def __init__(self, rig):
        self.rig, self.calls, self.gates = rig, [], [Gate() for _ in range(16)]
        self.symbols, self.payload = {}, b"opaque passive bytes"
    def read(self, cursor):
        i = len(self.calls); self.calls.append(cursor)
        gate = self.gates[i]; gate.entered.set()
        assert gate.release.wait(WATCHDOG), "passive source not released"
        if self.rig.closing: raise SystemExit("test teardown")
        self.rig.advance(10)
        symbol = self.symbols[i]
        if symbol == U: raise OSError("test passive read")
        return (fb.SourceItem(media_type="application/octet-stream", data=self.payload, claims={})
                if symbol == T else None)


class ToyActor:
    """TEST external actor: it receives fixed E, never chooses a sui operation."""
    def __init__(self, rig):
        self.rig, self.calls, self.gates, self.symbols = rig, [], [Gate() for _ in range(16)], {}
        self.payload = b"opaque actor bytes"
        self.entered_ns, self.returned_ns = [], []
    def perform(self, execution):
        i = len(self.calls); self.calls.append(execution)
        self.entered_ns.append(self.rig.clock.mono_ns())
        self.gates[i].entered.set()
        assert self.gates[i].release.wait(WATCHDOG), "toy actor not released"
        if self.rig.closing: raise SystemExit("test teardown")
        self.rig.advance(10)
        self.returned_ns.append(self.rig.clock.mono_ns())
        symbol = self.symbols[i]
        if symbol == U: raise OSError("test actor exception")
        return (fb.SourceItem(media_type="application/octet-stream", data=self.payload,
                              claims={"sender": "toy", "not_a_state_label": True}) if symbol == T else None)


class ObservedEntryPort(fb.FWorkContext):
    def __init__(self, owner, work, delegate):
        self.owner, self.work, self.delegate = owner, work, delegate
    def enter(self):
        wid = self.work.desc.work_id
        ok = self.delegate.enter()
        self.owner.entries.setdefault(wid, []).append(ok)
        gate = self.owner.gates.get(wid)
        if ok and gate is not None:
            gate.entered.set()
            assert gate.release.wait(gate.timeout), "entered native work was not released"
        return ok
    def now(self): return self.delegate.now()
    def read(self, point): return self.delegate.read(point)
    def monitored(self, interval): return self.delegate.monitored(interval)
    def acquire(self): return self.delegate.acquire()
    def perform(self, execution): return self.delegate.perform(execution)
    def reader(self): return self.delegate.reader()
    def prepared(self): return self.delegate.prepared()
    def evidence(self): return self.delegate.evidence()
    def post(self, event, issued=None):
        wid = self.work.desc.work_id
        self.owner.posts.setdefault(wid, []).append((event, issued))
        before = self.owner.before_post_gates.get(wid)
        if before is not None and isinstance(event, (fb.WorkFinished, fb.DrawReturned)):
            before.entered.set()
            assert before.release.wait(before.timeout), "native post was not released"
        result = self.delegate.post(event, issued=issued)
        gate = self.owner.post_gates.get(wid)
        if gate is not None and isinstance(event, (fb.WorkFinished, fb.DrawReturned)):
            gate.entered.set()
            assert gate.release.wait(gate.timeout), "posted native worker was not released"
        return result


class NativeEntryObserver:
    """Keep only the public work/port and actual entry/post/return witnesses."""
    def __init__(self, worker):
        self.worker, self.entries, self.gates = worker, {}, {}
        self.contexts, self.posts, self.returned = {}, {}, {}
        self.post_gates = {}
        self.before_post_gates = {}
    def hold(self, q, *, timeout=WATCHDOG):
        gate = Gate(timeout); self.gates[q.value["desc"]["work_id"]] = gate; return gate
    def hold_post(self, q, *, timeout=WATCHDOG):
        gate = Gate(timeout); self.post_gates[q.value["desc"]["work_id"]] = gate; return gate
    def hold_before_post(self, q, *, timeout=WATCHDOG):
        gate = Gate(timeout); self.before_post_gates[q.value["desc"]["work_id"]] = gate; return gate
    def run(self, work, ctx):
        wid = work.desc.work_id
        self.contexts[wid] = ctx
        done = self.returned.setdefault(wid, Event())
        try: return self.worker.run(work, ObservedEntryPort(self, work, ctx))
        finally: done.set()
    def wait_return(self, wid):
        return self.returned.setdefault(wid, Event()).wait(WATCHDOG)
    def request(self, rig, stage):
        matches = [q for q in rig.requests(stage) if q.value["desc"]["work_id"] in self.contexts]
        assert len(matches) == 1
        return matches[0]
    def late_terminal(self, q, *, clash):
        """Resend through the SAME actual port; never impersonate it with host.post."""
        wid = q.value["desc"]["work_id"]
        matches = [(e, issued) for e, issued in self.posts[wid] if isinstance(e, fb.WorkFinished)]
        assert len(matches) == 1
        original, issued = matches[0]
        event = (replace(original, outcome=fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="execution_error", content={"error_type": "RuntimeError"},
            readings=(), basis=()))) if clash else original)
        self.contexts[wid].post(event, issued=None if clash else issued)
        return event


class FixedRecordSaveCut:
    """Keep one fixed record pending through public write/record failures.

    In ack_loss the point is durable, but its public readback fails until restore;
    store observers can still prove durability through RealRig.read_stored.
    A failed drive may stop at this I/O; later processing is tested after restore.
    """
    class Unavailable(OSError): pass

    def __init__(self, rig, phase, *, contract_ref=None):
        assert phase in ("before_write", "ack_loss")
        self.rig, self.phase, self.armed, self.writing = rig, phase, True, False
        self.prepared, self.writes, self.reads = None, [], []
        self.contract_ref = contract_ref or contract("sui.fb.intention")
        self.normal_write, self.normal_record = rig.ledger.write, rig.ledger.record
        rig.ledger.write, rig.ledger.record = self.write, self.record

    def write(self, prepared):
        target = (self.armed and prepared.record.body.contract == self.contract_ref
                  and (self.prepared is None or prepared.cid == self.prepared.cid))
        if not target: return self.normal_write(prepared)
        if self.prepared is None: self.prepared = prepared
        assert prepared == self.prepared, "retry must keep the same fixed intention"
        self.writes.append(prepared)
        if self.phase == "ack_loss":
            self.writing = True
            try: self.normal_write(prepared)
            finally: self.writing = False
        raise self.Unavailable("test intention confirmation pending")

    def record(self, point):
        if (self.armed and self.phase == "ack_loss" and not self.writing
                and self.prepared is not None and point == self.prepared.cid):
            self.reads.append(point)
            raise self.Unavailable("test intention readback unavailable")
        return self.normal_record(point)

    def assert_pending(self):
        assert self.armed and self.prepared is not None and self.writes
        present = self.prepared.cid in dict(self.rig.entry_store.load())
        assert present == (self.phase == "ack_loss")
        if present:
            assert self.rig.read_stored(self.prepared.cid)[2] == self.prepared.record

    def retry_pending(self):
        self.assert_pending()
        fixed = self.prepared
        attempts = len(self.writes) + len(self.reads)
        with pytest.raises(self.Unavailable):
            self.rig.host.run_until(lambda _state: False, timeout=WATCHDOG)
        self.assert_pending()
        assert len(self.writes) + len(self.reads) > attempts
        assert self.prepared == fixed and all(p == fixed for p in self.writes)

    def restore(self):
        self.armed = False
        self.rig.ledger.write, self.rig.ledger.record = self.normal_write, self.normal_record


class CycleRig(RealRig):
    """New primary-loop rig: all seven worker uses are native through start().

    K36-a accepts registry/launcher/randbits as explicit dependency seams.
    The default here is the native registry, including native one-seat Need.
    """
    def __init__(self, *, thinking=True, prior=(Q(1, 2), Q(1, 2)), peek=P,
                 empty=EMPTY, exception=None, passive=P, passive_empty=EMPTY,
                 overlap="state_preserving", split=False, shape="end", aliases=False,
                  draw_bits=None, capacity=6, same_target=False):
        self.api = cycle_api(); super().__init__(connect=False)
        self.lock, self.closing, self.threads, self.errors = RLock(), False, [], []
        self.launcher, self.executed = LaunchCut(), set()
        self.passive, self.actor = ToySource(self), ToyActor(self)
        self.draw_calls, self.draw_bits, self.prior = [], draw_bits, prior
        self.registry = u2.fb_registry_v1()
        self.document, groups = world_document(prior=prior, peek=peek, empty=empty,
            exception=exception, split=split, shape=shape, aliases=aliases,
            targets=("box", "box") if same_target else ("A", "B"))
        rec = self.record(Prediction(target="cycle.model", about=(), basis=(),
            content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(rec, ()).cid
        observation = passive_declaration(passive, passive_empty)
        def allocation(name, amount=1):
            return slot(name, c.ALLOCATION, fb.Allocation(scope_slot="scope",
                amount=fb.QuantityValue(contract=c.SEATS, value=amount)))
        perception = slot("perception", contract("sui.fb.perception"), fb.Perception(
            process_slot="perceiving", reader_slot="reader", model=self.model_point,
            allocation=allocation("perception-allocation"),
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=contract("sui.fb.saved_acquisition_update"), args={
                    "route": "route", "observation_model": "observation",
                    "correspondence": {"pairs": [["A", "A"], ["B", "B"]]},
                    "execution": "execution"}))))
        initial = (slot("initial", replace(c.INITIAL_PROCESS, version="2"), fb.InitialProcess(
            process_slot="thinking", perception_slot="perception",
            generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}),
            method=fb.MethodCall(contract=contract("sui.f.finite_evaluation"), args={}),
            draw=fb.MethodCall(contract=c.OS_UNIFORM_BITS, args={}),
            prepare_budget=UNBOUNDED, evaluate_budget=UNBOUNDED,
            allocation=allocation("thinking-allocation", 2),
            continuation=fb.MethodCall(contract=c.REUSE_CANDIDATES, args={}))) if thinking else None)
        config = replace(route(), sampling_contract=c.ACQUISITION_RESULT_SAMPLING,
                         clock_contract=contract("sui.f.simulated_clock"),
                         loss_contract=c.ACQUISITION_RESULT_SAMPLING)
        self.boot_input = fb.Boot(declaration=fb.BootDeclaration(
            capacity=fb.QuantityValue(contract=c.SEATS, value=capacity),
            scope=slot("scope", c.RESOURCE_SCOPE, fb.ResourceScope(quantity_contract=c.SEATS,
                need=fb.MethodCall(contract=contract("sui.fb.one_seat_per_work"), args={}))),
            routes=(slot("route", c.BOOTSTRAP_ROUTE, fb.BootstrapRoute(config=config,
                process_slot="sensing", allocation=allocation("source-allocation"),
                reading_contract=c.ACQUISITION_SEQUENCE_PROJECTION,
                repeat=fb.MethodCall(contract=c.ACQUISITION_REPEAT_WHEN_DONE, args={}))),),
            perception=perception, initial=initial,
            environment=slot("environment", c.ENVIRONMENT, fb.Environment(data={"fixture": "cycle"})),
            execution=slot("execution", replace(contract("sui.fb.execution_declaration"), version="2"), fb.ExecutionDeclaration(
                allocation=allocation("execution-allocation"),
                actors={"peek": "toy"}, no_effect=("wait",),
                cells={"peek": tuple(f.ObservationCell(id=s,
                    observation=f.ObservationValue(kind="measurement", value=read1_symbol(s)),
                    outcomes=tuple(names)) for s, names in groups.items() if names)},
                source_overlap=overlap, actor_overlap=overlap)),
            observation_models=(slot("observation", MODEL, observation),)))
        self.clock_declaration = replace(source(), run=self.clock.run,
                                        measurement=contract("sui.f.simulated_clock"))
        self.running = None
        self.entry_observers = []

    def replace_model(self, document, *, label="cycle.variant.model"):
        """Save a new declared TEST model before Boot; never alter old records."""
        self.document = deepcopy(document)
        rec = self.record(Prediction(target=label, about=(), basis=(),
            content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(rec, ()).cid
        per = self.boot_input.declaration.perception
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            perception=replace(per, value=replace(per.value, model=self.model_point))))

    def advance(self, delta):
        with self.lock: self.clock.set(self.clock.mono_ns() + delta)

    def randbits(self, length):
        self.draw_calls.append(length)
        return (3 << (length - 2)) if self.draw_bits is None else self.draw_bits(length)

    def thinking_seats(self, seats, *, execution=False):
        initial = self.boot_input.declaration.initial
        allocation = initial.value.allocation
        initial = replace(initial, value=replace(initial.value, allocation=replace(
            allocation, value=replace(allocation.value,
                amount=fb.QuantityValue(contract=c.SEATS, value=seats)))))
        perception = self.boot_input.declaration.perception
        if not execution:
            derivation = perception.value.derivation
            args = dict(derivation.method.args)
            args.pop("execution", None)
            perception = replace(perception, value=replace(perception.value,
                derivation=replace(derivation, method=replace(derivation.method, args=args))))
        self.boot_input = replace(self.boot_input, declaration=replace(
            self.boot_input.declaration, initial=initial, perception=perception,
            capacity=fb.QuantityValue(contract=c.SEATS, value=seats + 2 + int(execution)),
            execution=self.boot_input.declaration.execution if execution else None))
        return self

    def execution_seats(self, seats):
        execution = self.boot_input.declaration.execution
        allocation = execution.value.allocation
        execution = replace(execution, value=replace(execution.value, allocation=replace(
            allocation, value=replace(allocation.value,
                amount=fb.QuantityValue(contract=c.SEATS, value=seats)))))
        thinking = self.boot_input.declaration.initial
        amount = thinking.value.allocation.value.amount.value if thinking is not None else 0
        self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
            execution=execution, capacity=fb.QuantityValue(contract=c.SEATS, value=amount + seats + 2)))
        return self

    def start(self):
        self.running = fb.start(ledger=self.ledger, clock=self.clock,
            clock_declaration=self.clock_declaration, boot=self.boot_input,
            sources={"route-A": self.passive}, actors={"toy": self.actor},
            registry=self.registry, launcher=self.launcher, randbits=self.randbits)
        assert isinstance(self.running, fb.RunningSui)
        self.host = self.running.host
        return self

    def direct(self, *, execute_worker=None, actors=None, worker_overrides=None):
        """Lower-level fault scene: explicit finite budgets/worker probes only."""
        measurer = fb.SourceMeasurer()
        workers = {"measure_segment": measurer, "belief_update": fb.FiniteUpdater(registry=self.registry),
                   "candidate_generation": fb.CandidateGenerator(),
                   "evaluation_prepare": fb.EvaluationPreparer(registry=self.registry),
                   "selection_draw": fb.UniformDraw(randbits=self.randbits), "evaluation": fb.Evaluator(),
                   "execute_step": execute_worker or fb.StepExecutor()}
        workers.update(worker_overrides or {})
        self.entry_observers.extend(w for w in (worker_overrides or {}).values()
                                    if isinstance(w, NativeEntryObserver))
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, registry=self.registry,
            workers=fb.WorkerBundle(workers), launcher=self.launcher,
            sources={"route-A": self.passive}, actors={"toy": self.actor} if actors is None else actors)
        self.running = SimpleNamespace(host=self.host, stop=measurer.stop)
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration)); self.host.post(self.boot_input)
        return self

    def until(self, predicate):
        self.host.keep_running(lambda _state: predicate(), timeout=WATCHDOG)
        assert predicate(), "required public K36 transition absent"
        assert self.host.halted is None

    def requests(self, stage):
        ref = contract("sui.fb.execute_step_requested") if stage == "execute_step" else REQUESTS[stage]
        return [r for r in self.facts(ref) if r.value["desc"]["purpose"] == stage]

    def offered(self, stage):
        def offers():
            return [(q, body) for q in self.requests(stage) for key, body in self.launcher.attempts
                    if q.value["desc"]["work_id"] == key and key not in self.executed]
        self.until(lambda: bool(offers()))
        pending = offers(); assert len(pending) == 1
        return pending[0]

    def run(self, stage, *, background=False):
        return self.invoke(*self.offered(stage), background=background)

    def request_where(self, stage, predicate):
        def matches(): return [q for q in self.requests(stage) if predicate(q)]
        self.until(lambda: bool(matches()))
        found = matches(); assert len(found) == 1
        return found[0]

    def run_request(self, request, *, background=False):
        wid = request.value["desc"]["work_id"]
        self.until(lambda: any(key == wid for key, _ in self.launcher.attempts))
        assert wid not in self.executed
        bodies = [body for key, body in self.launcher.attempts if key == wid]
        assert len(bodies) == 1
        return self.invoke(request, bodies[0], background=background)

    def prepared_for(self, request):
        def matches(): return [p for p in self.facts(c.PREPARED) if p.value["request"] == request.cid]
        self.until(lambda: bool(matches()))
        prepared, = matches(); return prepared

    def draw_for(self, request, *, fresh=False):
        prepared = self.prepared_for(request)
        return self.request_where("selection_draw", lambda q:
            q.value["desc"]["args"]["prepared"] == prepared.cid and
            (not fresh or q.value["desc"]["work_id"] not in self.executed))

    def evaluation_for(self, request, *, fresh=False):
        return self.request_where("evaluation", lambda q:
            q.value["desc"]["args"]["evaluation_request"] == request.cid and
            (not fresh or q.value["desc"]["work_id"] not in self.executed))

    def finish_thought(self, request):
        """Complete one named, non-boundary round, even with parallel offers."""
        if request.value["desc"]["work_id"] not in self.executed: self.run_request(request)
        prepared = self.prepared_for(request)
        artifact, = [a for a in self.facts(fc.MATH_ARTIFACT_V2)
                     if a.cid == prepared.value["artifact"]]
        problem = codec.f_from_json(json.dumps(artifact.value["claim"], sort_keys=True,
            separators=(",", ":")).encode(), contract=fc.VALUE_FACTS)
        assert isinstance(problem, f.FProblem)
        draw = self.draw_for(request)
        if draw.value["desc"]["work_id"] not in self.executed: self.run_request(draw)
        evaluation = self.evaluation_for(request)
        if evaluation.value["desc"]["work_id"] not in self.executed: self.run_request(evaluation)
        def matches():
            return [s for s in self.facts(c.SELECTION)
                    if self.selected_value(s).root.problem_key == problem.problem_key]
        self.until(lambda: bool(matches()))
        selected, = matches()
        return selected

    def invoke(self, q, body, *, background=False):
        wid = q.value["desc"]["work_id"]
        self.executed.add(wid)
        if background:
            def invoke():
                try: body()
                except SystemExit: pass
                except BaseException as error: self.errors.append(error)
            thread = Thread(target=invoke); self.threads.append(thread); thread.start()
        else:
            body()
        return q

    def think(self):
        previous = {x.cid for x in self.facts(c.SELECTION)}
        for stage in (ORDER if not self.facts(fc.CANDIDATE_DECLARATION) else ORDER[1:]): self.run(stage)
        self.until(lambda: len([x for x in self.facts(c.SELECTION) if x.cid not in previous]) == 1)
        return next(x for x in self.facts(c.SELECTION) if x.cid not in previous)

    def enter_step(self, index=0, *, selection=None):
        if selection is None:
            q = self.run("execute_step", background=True)
        else:
            q = self.request_where("execute_step", lambda q:
                q.value["desc"]["args"]["selection"] == selection)
            self.run_request(q, background=True)
        assert self.actor.gates[index].entered.wait(WATCHDOG)
        fixed = self.actor.calls[index]
        assert isinstance(fixed, fb.ExecutionArgs)
        assert fixed.selection in {x.cid for x in self.facts(c.SELECTION)}
        return q, fixed

    def finish_step(self, index, symbol):
        self.actor.symbols[index] = symbol; self.actor.gates[index].release.set()
        fixed = self.actor.calls[index]
        self.until(lambda: any(x.execution == fixed and x.result is not None
                              for x in self.host.window.status().executions))
        row = next(x for x in self.host.window.status().executions if x.execution == fixed)
        record = self.read_stored(row.result)[2]
        assert record.body.contract == contract("sui.fb.execution_result")
        body = record.body.content.as_json()
        assert body["execution"] == wire(fixed)
        assert body["value"] == read1_symbol(symbol)

    def assert_fixed_image(self, request, fixed, selection):
        selected = self.selected_value(selection)
        assert request.value["desc"]["args"] == wire(fixed)
        assert fixed.selection == selection.cid and fixed.root_key == selected.root.root_key
        assert fixed.draw == selected.root.draw_point and fixed.policy == selected.choice.policy
        assert fixed.action == selected.choice and fixed.model == self.model_point
        assert fixed.kernel.args["id"] == fixed.u == "peek"
        intention = self.read_stored(fixed.intention)[2]
        assert intention.body.contract == contract("sui.fb.intention")
        assert intention.body.content.as_json()["selection"] == selection.cid
        reading = self.read_stored(fixed.reading)[2]
        assert reading.body.contract == replace(contract("sui.fb.execution_declaration"), version="2")

    def sense(self, index, symbol, *, begin=False):
        if begin: self.run("measure_segment", background=True)
        assert self.passive.gates[index].entered.wait(WATCHDOG)
        self.passive.symbols[index] = symbol; self.passive.gates[index].release.set()
        self.until(lambda: len(self.frame_reports()) >= index + 1)

    def start_last_passive(self):
        self.last_measurement = self.run("measure_segment", background=True)
        assert self.passive.gates[0].entered.wait(WATCHDOG)
        self.running.stop()  # Stop SIGNAL while read 0 is blocked, before its return.

    def complete_last_passive(self, symbol):
        self.sense(0, symbol)
        wid = self.last_measurement.value["desc"]["work_id"]
        self.until(lambda: any(w.work_id == wid and w.stop_confirmed
                              for w in self.host.window.status().works))
        assert len(self.passive.calls) == 1

    def exercise_available_updates(self):
        """Negative safety probe; positive progress always has an until witness.

        The saved result/Frame already exists. Repeated public rounds let any
        erroneously startable U actually run, rather than asserting no adoption
        merely because this test never invoked a queued updater callback.
        """
        for _ in range(32):
            self.host.run_until(lambda _s: True, timeout=WATCHDOG)
            offered = [(q, body) for q in self.requests("belief_update")
                for wid, body in self.launcher.attempts
                if q.value["desc"]["work_id"] == wid and wid not in self.executed]
            for q, body in offered: self.invoke(q, body)
        assert self.host.halted is None

    def frame_reports(self):
        return [x for x in self.facts(c.SEGMENT_REPORT) if x.value["item"]["kind"] == "frame"]

    def adopt(self, count):
        while len(self.facts(c.BELIEF_ADOPTED)) < count:
            before = len(self.facts(c.BELIEF_ADOPTED))
            self.run("belief_update")
            self.until(lambda: len(self.facts(c.BELIEF_ADOPTED)) == before + 1)
        return self.adoption_chain()

    def adoption_chain(self):
        left, prior, chain = list(self.facts(c.BELIEF_ADOPTED)), None, []
        while left:
            choices = [a for a in left if a.value["previous"] == prior]
            assert len(choices) == 1
            a = choices[0]; chain.append(a); left.remove(a); prior = a.cid
        return chain

    def answer(self, index=-1):
        a = self.adoption_chain()[index]
        result = next(x for x in self.facts(c.UPDATE_RESULT) if x.cid == a.value["result"])
        return result.value["result"]

    def assert_answer(self, matrices, *, prior=None):
        joint, mass = enumerate_updates(matrices, prior or self.prior)
        assert joint is not None
        assert self.answer() == {"joint": wire(joint), "evidence_mass": wire(mass)}

    def selected_value(self, selected):
        ev = next(x for x in self.facts(c.EVALUATED) if x.cid == selected.value["evaluated"])
        art = next(x for x in self.facts(fc.MATH_ARTIFACT_V2) if x.cid == ev.value["artifact"])
        return codec.f_from_json(json.dumps(art.value["claim"], sort_keys=True,
            separators=(",", ":")).encode(), contract=fc.VALUE_FACTS)

    def snapshot(self): return {cid: header for cid, header in self.entry_store.load()}

    def close(self):
        self.closing = True
        if self.running is not None: self.running.stop()
        for observer in self.entry_observers:
            for gate in (*observer.gates.values(), *observer.before_post_gates.values(),
                         *observer.post_gates.values()): gate.release.set()
        for world in (self.actor, self.passive):
            for gate in world.gates: gate.release.set()
        for thread in self.threads:
            thread.join(WATCHDOG); assert not thread.is_alive(), "test environment still active"
        assert not self.errors, [type(x).__name__ for x in self.errors]


@pytest.fixture
def cycles():
    active = []
    def make(**kwargs):
        rig = CycleRig(**kwargs); active.append(rig); return rig
    yield make
    for rig in reversed(active): rig.close()




def evaluation_status(rig, *, context=None, activity=None):
    rows = list(rig.host.window.status().evaluations)
    if context is not None: rows = [row for row in rows if row.context == context]
    if activity is not None: rows = [row for row in rows if row.activity == activity]
    row, = rows
    assert isinstance(row, fb.EvaluationStatus)
    assert isinstance(row.activity, str)
    assert row.root in ("undetermined", "prior", "adopted")
    assert (row.root_point is not None) is (row.root == "adopted")
    assert row.outcome in ("running", "selected", "no_decision", "no_candidates", "failure",
                           "unknown", "conflict", "stopped", "short")
    assert row.counted is (row.outcome == "running" or bool(row.residual))
    boot, = rig.facts(c.BOOT_DECLARATION)
    assert row.allocation == fb.BootSlot(declaration=boot.cid,
        slot=rig.boot_input.declaration.initial.value.allocation.slot)
    assert isinstance(row.basis, fb.StatusBasis)
    return row


def activity_for_request(rig, request):
    return evaluation_status(rig, context=request.value["desc"]["args"]["input"]["context"])


def thinking_material_status(rig):
    row, = rig.host.window.status().thinking_materials
    boot, = rig.facts(c.BOOT_DECLARATION)
    assert isinstance(row, fb.ThinkingMaterialStatus)
    assert row.boot == boot.cid
    assert row.initial == fb.BootSlot(declaration=boot.cid, slot=rig.boot_input.declaration.initial.slot)
    assert isinstance(row.basis, fb.StatusBasis)
    return row

def assert_interval(quantity, expected, width=Decimal("1e-16")):
    assert quantity.status == "finite" and quantity.bounds is not None
    def dec(q): return Decimal(q.numerator) / Decimal(q.denominator)
    low, high = dec(quantity.bounds.lower), dec(quantity.bounds.upper)
    assert low - Decimal("1e-65") <= expected <= high + Decimal("1e-65")
    assert high - low < width


def assert_probability(rig, selection, prior):
    selected = rig.selected_value(selection); ev = selected.evaluation
    info, peek_probability = information_and_probability(prior)
    p, w = ev.candidates.index("peek"), ev.candidates.index("wait")
    assert_interval(ev.q_star[p], peek_probability)
    assert_interval(ev.q_star[w], 1 - peek_probability)
    gp, gw = ev.G[p].bounds, ev.G[w].bounds
    assert gp is not None and gw is not None
    with localcontext() as ctx:
        ctx.prec = 80
        low, high = gp.lower - gw.upper, gp.upper - gw.lower
        assert Decimal(low.numerator) / Decimal(low.denominator) <= -info + Decimal("1e-65")
        assert Decimal(high.numerator) / Decimal(high.denominator) >= -info - Decimal("1e-65")
    return ev


def assert_declared_one_step_probabilities(rig, selection, prior):
    information, probabilities = declared_one_step_information_and_probabilities(rig.document, prior)
    selected = rig.selected_value(selection)
    assert selected.root.gamma == 1 and selected.root.preferences == ()
    ev = selected.evaluation
    assert set(ev.candidates) == set(probabilities)
    for index, candidate in enumerate(ev.candidates):
        assert_interval(ev.information[index].additional, information[candidate])
        assert_interval(ev.G[index], -information[candidate])
        assert_interval(ev.q_star[index], probabilities[candidate])
    return ev


def test_cycle1_public_separation_seven_stages_and_execution_fields():
    cycle_api()
    assert "execute_step" in get_args(fb.Stage)
    assert set(STAGES) == set(get_args(fb.Stage))
    assert {"model", "reader_slot", "derivation"}.isdisjoint(x.name for x in fields(fb.InitialProcess))
    assert {"model", "reader_slot", "derivation", "allocation", "process_slot"} <= {x.name for x in fields(fb.Perception)}
    assert {"policies", "intentions", "executions"} <= {x.name for x in fields(fb.FStatus)}
    assert {"selection", "evaluated", "root_key", "draw", "intention", "policy", "node",
            "occurrence", "action", "kernel", "u", "model", "reading", "prior"} <= {x.name for x in fields(fb.ExecutionArgs)}


@pytest.mark.parametrize("thinking", [False, True])
def test_cycle1_start_valid_declarations_assembles_native_path(cycles, thinking):
    r = cycles(thinking=thinking).start()
    r.until(lambda: bool(r.requests("measure_segment")) and bool(r.facts(MODEL)))
    if thinking: r.until(lambda: bool(r.requests("candidate_generation")))
    else:
        assert not r.requests("candidate_generation")
        assert r.host.window.status().evaluations == ()
        assert r.host.window.status().thinking_materials == ()
    assert r.actor.calls == [] and r.passive.calls == []
    assert r.draw_calls == []


@pytest.mark.parametrize("field", ["max_cells", "max_terms", "max_refinements"])
@pytest.mark.parametrize("budget_name", ["prepare_budget", "evaluate_budget"])
def test_cycle1_start_rejects_each_finite_budget_before_any_effect(cycles, budget_name, field):
    r = cycles(); before = r.snapshot()
    initial = r.boot_input.declaration.initial
    changed = replace(initial.value, **{budget_name: replace(UNBOUNDED, **{field: 1})})
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=changed)))
    with pytest.raises(fb.StartInputError) as caught: r.start()
    assert caught.value.reason == "finite_budget"
    assert budget_name in caught.value.field and field in caught.value.field
    assert r.snapshot() == before and not r.actor.calls and not r.passive.calls and not r.draw_calls


@pytest.mark.parametrize("fault", ["generator", "args"])
def test_cycle1_start_rejects_draw_generator_or_args_independently(cycles, fault):
    r = cycles(); before = r.snapshot(); initial = r.boot_input.declaration.initial
    draw = replace(initial.value.draw, **({"contract": contract("other.draw")} if fault == "generator" else {"args": {"extra": 1}}))
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=replace(initial.value, draw=draw))))
    with pytest.raises(fb.StartInputError) as caught: r.start()
    assert caught.value.reason == ("draw_generator" if fault == "generator" else "draw_args")
    assert "draw" in caught.value.field
    assert ("contract" if fault == "generator" else "args") in caught.value.field
    assert r.snapshot() == before and not r.draw_calls and not r.actor.calls and not r.passive.calls


def test_cycle1_perception_only_updates_with_its_own_origin_process_and_allocation(cycles):
    r = cycles(thinking=False).start(); r.sense(0, T, begin=True); r.adopt(1)
    r.assert_answer((P,))
    assert not r.requests("candidate_generation") and not r.facts(c.SELECTION)
    q = r.requests("belief_update")[0]
    assert q.value["desc"]["process"]["slot"] == "perceiving"
    a = r.adoption_chain()[0]
    assert q.value["desc"]["reader"] == a.value["origin"]
    assert not r.actor.calls and not r.draw_calls


@pytest.mark.parametrize("symbol,matrix", [(T, P), (E, EMPTY)])
def test_cycle1_entry_round_trip_updates_probability_and_reaches_next_actor(cycles, symbol, matrix):
    r = cycles().start(); first = r.think(); assert_probability(r, first, r.prior)
    request, fixed = r.enter_step(); r.assert_fixed_image(request, fixed, first)
    r.finish_step(0, symbol); r.adopt(1); r.assert_answer((matrix,))
    second = r.think(); posterior, _ = enumerate_updates((matrix,))
    assert_probability(r, second, posterior)
    assert second.cid != first.cid
    next_request, next_e = r.enter_step(1)
    r.assert_fixed_image(next_request, next_e, second)
    assert next_e.selection == second.cid and next_e.prior == r.adoption_chain()[-1].cid
    assert next_e.intention != fixed.intention and next_e.root_key != fixed.root_key
    r.finish_step(1, T)


def test_cycle1_wait_completes_without_actor_and_passive_sensing_continues(cycles):
    r = cycles(draw_bits=lambda n: 0).start(); selection = r.think()
    assert r.selected_value(selection).choice.id == "wait"
    r.run("execute_step")
    r.until(lambda: any(e.outcome == "no_effect" for e in r.host.window.status().executions))
    row = next(e for e in r.host.window.status().executions if e.outcome == "no_effect")
    assert row.source_called is False and row.result_symbol is None and not r.actor.calls
    r.sense(0, T, begin=True); r.adopt(1); r.assert_answer((P,))


@pytest.mark.parametrize("shape,symbol,second", [("two", T, True), ("branch", T, True), ("branch", E, False), ("end", T, False)])
def test_cycle1_certified_policy_advances_execute_branch_and_end_without_new_receipt(cycles, shape, symbol, second):
    r = cycles(shape=shape).start(); r.think(); _, first = r.enter_step()
    r.finish_step(0, symbol); r.adopt(1)
    if second and shape == "two":
        _, other = r.enter_step(1)
        assert other.selection == first.selection and other.node == "second" and other != first
        r.finish_step(1, E)
    elif second:
        r.run("execute_step")
        r.until(lambda: any(e.outcome == "no_effect" for e in r.host.window.status().executions))
        assert len(r.actor.calls) == 1
    else:
        r.until(lambda: any(p.selection == first.selection and p.outcome == "ended" for p in r.host.window.status().policies))
        assert len(r.actor.calls) == 1


def test_cycle1_choose_is_named_unconnected_and_preserves_selection_and_intention(cycles):
    r = cycles(shape="choose").start(); selected = r.think(); _, fixed = r.enter_step()
    r.finish_step(0, T); r.adopt(1)
    r.until(lambda: any(p.selection == selected.cid and p.reason == "choose_unconnected"
                        for p in r.host.window.status().policies))
    assert any(i.point == fixed.intention for i in r.host.window.status().intentions)
    assert len(r.actor.calls) == 1 and any(s.cid == selected.cid for s in r.facts(c.SELECTION))


@pytest.mark.parametrize("fault", ["state_change", "duration", "no_observation", "outside_symbols"])
def test_cycle1_unsupported_selected_step_is_not_silently_dropped_or_executed(cycles, fault):
    r = cycles()
    kernel = next(k for k in r.document["kernels"] if k["id"] == "peek")
    # Store a distinct valid F-a model through the same public ledger before Boot.
    if fault == "state_change":
        kernel["outcomes"][0]["matrix"] = wire(N); kernel["outcomes"][1]["matrix"] = wire(ZERO)
        r.document["targets"] = ["box"]
        for state in r.document["states"]: state["target"] = "box"
    elif fault == "duration":
        for out in kernel["outcomes"]: out["elapsed_ns"] = 1
    elif fault == "no_observation":
        for out in kernel["outcomes"]:
            out["evidence"] = None; out["available"]["reveal"] = []
    else:
        for out in kernel["outcomes"]: out["evidence"]["value"] = {"other": "not a result symbol"}
    rec = r.record(Prediction(target="unsupported.model", about=(), basis=(), content=Payload.json({"document": r.document}),
        contract=contract("sui.f.model_source")), RefKind.PREDICTION, Role.MODEL)
    r.model_point = r.ledger.append(rec, ()).cid
    per = r.boot_input.declaration.perception
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        perception=replace(per, value=replace(per.value, model=r.model_point))))
    r.start(); selected = r.think(); r.run("execute_step")
    r.until(lambda: any(e.outcome == "unconnected" for e in r.host.window.status().executions))
    assert not r.actor.calls and any(s.cid == selected.cid for s in r.facts(c.SELECTION))
    assert any(i.selection == selected.cid for i in r.host.window.status().intentions)


@pytest.mark.parametrize("exception_matrix,peek,empty", [(EMPTY, P, ZERO), (HALF, HALF, ZERO)])
def test_cycle1_exception_is_one_observation_including_state_independent_half_mass(cycles, exception_matrix, peek, empty):
    r = cycles(peek=peek, empty=empty, exception=exception_matrix).start(); r.think(); _, fixed = r.enter_step()
    r.finish_step(0, U); r.adopt(1); r.assert_answer((exception_matrix,))
    assert len(r.actor.calls) == 1
    row = next(e for e in r.host.window.status().executions if e.execution == fixed)
    assert row.source_called is True and row.result_symbol == U
    assert row.outcome != "no_effect"


def test_cycle1_exception_without_reading_stops_adoption_and_policy_but_not_receipts(cycles):
    r = cycles().start(); r.think(); _, fixed = r.enter_step(); r.finish_step(0, U)
    r.until(lambda: any(e.reason == "exception_reading_missing" for e in r.host.window.status().executions))
    assert all(not e.retryable for e in r.host.window.status().executions
               if e.reason == "exception_reading_missing")
    assert not r.facts(c.BELIEF_ADOPTED) and len(r.actor.calls) == 1
    for _ in range(32): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert not r.requests("belief_update"), "no execution reading must not create a known-invalid U request"
    r.sense(0, T, begin=True)
    assert r.frame_reports() and not r.facts(c.BELIEF_ADOPTED)
    assert any(p.selection == fixed.selection and p.reason == "exception_reading_missing" for p in r.host.window.status().policies)


def test_cycle1_zero_mass_execution_is_distinct_from_missing_reading_or_no_effect(cycles):
    r = cycles(peek=I, empty=ZERO, exception=ZERO).start(); r.think(); r.enter_step(); r.finish_step(0, U)
    r.until(lambda: any(e.outcome == "model_zero" for e in r.host.window.status().executions))
    assert not r.facts(c.BELIEF_ADOPTED) and len(r.actor.calls) == 1
    assert not [q for q in r.requests("belief_update") if q.value["desc"]["work_id"] in r.executed]
    row, = [e for e in r.host.window.status().executions if e.outcome == "model_zero"]
    assert not row.retryable and row.outcome != "no_effect"


@pytest.mark.parametrize("when", ["thinking_empty", "before_selection", "evaluation", "actor_waiting"])
def test_cycle1_passive_receipt_save_and_update_continue_in_each_phase(cycles, when):
    r = cycles(thinking=when != "thinking_empty").start()
    if when == "evaluation":
        for stage in ORDER[:-1]: r.run(stage)
    elif when == "actor_waiting": r.think(); r.enter_step()
    r.sense(0, T, begin=True); r.adopt(1); r.assert_answer((P,))
    assert len(r.adoption_chain()) == 1
    if when == "actor_waiting": r.finish_step(0, E)


@pytest.mark.parametrize("order", ["passive_before", "passive_after"])
def test_cycle1_causal_intervals_match_independent_state_path_enumeration(cycles, order):
    r = cycles(passive=N, passive_empty=ZERO, prior=(Q(1, 3), Q(2, 3)),
               same_target=True, overlap="serializable").start()
    if order == "passive_before":
        r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
        r.advance(1)  # Strictly after the saved first operation; never 110 == 110.
    r.think(); r.enter_step(); r.finish_step(0, T)
    if order == "passive_after":
        r.adopt(1); r.advance(1)
        r.start_last_passive(); r.complete_last_passive(T)
    frame = r.frame_reports()[0].value["item"]["value"]["measurement_interval"]
    if order == "passive_before": assert frame["end_ns"] < r.actor.entered_ns[0]
    else: assert r.actor.returned_ns[0] < frame["start_ns"]
    assert len(r.passive.calls) == 1
    r.adopt(2); r.assert_answer((N, P) if order == "passive_before" else (P, N))


@pytest.mark.parametrize("declaration_kind,commutes,split", [
    ("state_preserving", True, False), ("serializable", True, False),
    ("serializable", True, True), ("serializable", False, False),
    ("undeclared", True, False)])
def test_cycle1_overlap_uses_world_declaration_and_summed_observation_cell(cycles, declaration_kind, commutes, split):
    actor_t = HALF if commutes else ((Q(1), 0), (0, Q(0)))
    actor_e = HALF if commutes else ((Q(0), 0), (0, Q(1)))
    passive = HALF if declaration_kind == "state_preserving" else I if declaration_kind == "undeclared" else N
    passive_e = HALF if declaration_kind == "state_preserving" else ZERO
    r = cycles(peek=actor_t, empty=actor_e, passive=passive, passive_empty=passive_e,
               overlap=declaration_kind, split=split, same_target=True).start()
    r.run("measure_segment", background=True); assert r.passive.gates[0].entered.wait(WATCHDOG)
    r.think(); _, fixed = r.enter_step()
    r.sense(0, T); r.finish_step(0, T)
    progresses = declaration_kind != "undeclared" and commutes
    if progresses:
        r.adopt(2); r.assert_answer((passive, actor_t))
    else:
        r.until(lambda: any(e.outcome == "order_unknown" for e in r.host.window.status().executions))
        row = next(e for e in r.host.window.status().executions if e.execution == fixed)
        assert not row.retryable and row.reason == "observation_order_unknown"
        assert not r.facts(c.BELIEF_ADOPTED)
        before = len(r.frame_reports()); r.sense(1, E)
        assert len(r.frame_reports()) == before + 1 and not r.facts(c.BELIEF_ADOPTED)


@pytest.mark.parametrize("payload", [b"A", b"B", b"arbitrary\x00bytes"])
def test_cycle1_payload_bytes_are_preserved_but_do_not_change_the_update(cycles, payload):
    r = cycles().start(); r.actor.payload = payload; r.think(); r.enter_step(); r.finish_step(0, T)
    r.adopt(1); r.assert_answer((P,))
    fixed = r.actor.calls[0]
    row, = [e for e in r.host.window.status().executions if e.execution == fixed]
    result = r.read_stored(row.result)[2].body.content.as_json()
    # Resolve ONLY the name in this result, never search for matching bytes.
    raw_name = result["received"]
    named = [fact for fact in r.facts(c.RECEIVED)
             if raw_name in (fact.cid, str(fact.record_id))]
    assert len(named) == 1
    raw = r.read_stored(named[0].cid)[2]
    assert raw.body.contract == c.RECEIVED
    received = raw.body.content.as_json()
    assert isinstance(received["data"], list)
    assert all(type(x) is int and 0 <= x <= 255 for x in received["data"])
    assert bytes(received["data"]) == payload
    assert received["media_type"] == "application/octet-stream"
    assert received["claims"] == {"sender": "toy", "not_a_state_label": True}


@pytest.mark.parametrize("boundary", ["selected", "accepted", "entered", "result"])
def test_cycle1_window_rebuild_does_not_repeat_an_already_started_step(cycles, boundary):
    r = cycles().start(); selected = r.think()
    if boundary in {"accepted", "entered", "result"}:
        r.until(lambda: any(i.selection == selected.cid for i in r.host.window.status().intentions))
    if boundary in {"entered", "result"}: r.enter_step()
    if boundary == "result": r.finish_step(0, T)
    before = r.snapshot(); old = r.host.window; r.host.rebuild_window()
    assert r.snapshot() == before
    with pytest.raises(RuntimeError): old.status()
    if boundary in {"selected", "accepted"}: r.enter_step()
    if boundary != "result": r.finish_step(0, T)
    r.adopt(1); r.assert_answer((P,)); assert len(r.actor.calls) == 1


@pytest.mark.parametrize("packaging", ["baseline", "clock_steps", "aliases"])
def test_cycle1_packaging_preserves_G_probabilities_and_followup_request(cycles, packaging):
    r = cycles(aliases=packaging == "aliases").start()
    if packaging == "clock_steps": r.advance(1000000)
    r.think(); r.enter_step(); r.finish_step(0, T); r.adopt(1)
    second = r.think(); assert_probability(r, second, (Q(2, 3), Q(1, 3)))
    _, fixed = r.enter_step(1)
    assert fixed.prior == r.adoption_chain()[-1].cid
    assert fixed.action.id == "peek" and fixed.kernel.args["id"] == "peek"
    r.finish_step(1, E)


def test_cycle1_perception_zero_allocation_is_not_silently_topped_up(cycles):
    r = cycles(thinking=False)
    per = r.boot_input.declaration.perception
    allocation = per.value.allocation
    allocation = replace(allocation, value=replace(allocation.value,
        amount=fb.QuantityValue(contract=c.SEATS, value=0)))
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        perception=replace(per, value=replace(per.value, allocation=allocation))))
    r.start(); r.sense(0, T, begin=True)
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert not r.facts(c.BELIEF_ADOPTED)
    # No promise that an insufficient allocation already has a saved Q*.
    for q in r.requests("belief_update"):
        assert q.value["desc"]["allocation"]["slot"] == "perception-allocation"
        assert not [t for t in r.facts(c.WORK_TERMINAL) if t.value["work"] == q.value["desc"]["work_id"]]


def test_cycle1_replacement_after_entry_keeps_old_E_and_does_not_advance_new_policy(cycles):
    parts = iter((3, 0))
    r = cycles(draw_bits=lambda n: next(parts) << (n - 2)).start()
    old = r.think(); _, first = r.enter_step()
    r.sense(0, T, begin=True); r.adopt(1); new = r.think()
    assert r.selected_value(old).choice.id == "peek" and r.selected_value(new).choice.id == "wait"
    assert first.selection == old.cid and first.selection != new.cid
    r.finish_step(0, T); r.adopt(2); r.assert_answer((P, P))
    row = next(e for e in r.host.window.status().executions if e.execution == first)
    assert row.execution.selection == old.cid
    assert not any(p.selection == new.cid and p.outcome == "ended" for p in r.host.window.status().policies)
    r.run("execute_step")
    r.until(lambda: any(e.execution.selection == new.cid and e.outcome == "no_effect"
                        for e in r.host.window.status().executions))
    assert len(r.actor.calls) == 1


@pytest.mark.parametrize("fault", ["action", "u", "selection", "model", "reading", "prior"])
def test_cycle1_perform_cannot_execute_an_unselected_operation_or_foreign_E(cycles, fault):
    r = cycles(); finished = Event(); seen = []
    class GuardProbe:
        def run(self, work, ctx):
            if not ctx.enter(): return
            fixed = work.desc.args
            bad = (replace(fixed, action=replace(fixed.action, id="not-selected")) if fault == "action"
                   else replace(fixed, u="other-control") if fault == "u"
                   else replace(fixed, **{fault: "sha256:" + "0" * 64}))
            try:
                try: ctx.perform(bad)
                except Exception as error: seen.append(type(error).__name__)
            finally: finished.set()
    r.direct(execute_worker=GuardProbe()); selected = r.think()
    r.run("execute_step", background=True)
    assert finished.wait(WATCHDOG), "perform did not finish rejecting the foreign fixed image"
    assert not r.actor.calls
    assert not r.facts(contract("sui.fb.execution_result"))
    assert any(s.cid == selected.cid for s in r.facts(c.SELECTION))


def test_cycle1_result_memo_is_host_owned_not_worker_posted(cycles):
    r = cycles(); denied = Event()
    class ForgedMemo:
        def run(self, work, ctx):
            if not ctx.enter(): return
            try:
                with pytest.raises(fb.FbInputError):
                    ctx.post(fb.ExecutionReport(work=work.desc.work_id, execution=work.desc.args,
                                               value={"result": "empty", "source_called": True}))
            finally: denied.set()
    r.direct(execute_worker=ForgedMemo()); r.think(); r.run("execute_step", background=True)
    assert denied.wait(WATCHDOG)
    assert not r.actor.calls and not r.facts(contract("sui.fb.execution_result"))
    assert not r.facts(c.BELIEF_ADOPTED)


def test_cycle1_pending_result_storage_blocks_later_observation_until_saved(cycles):
    r = cycles().start(); r.think(); r.enter_step()
    measure = r.offered("measure_segment")
    original, cut = r.ledger.write, []
    class StorageWaiting(OSError): pass
    def hold(prepared):
        if prepared.record.body.contract == contract("sui.fb.execution_result"):
            cut.append(prepared); raise StorageWaiting("test execution result pending")
        return original(prepared)
    r.ledger.write = hold
    try:
        r.actor.symbols[0] = T; r.actor.gates[0].release.set()
        # Start passive only after perform's after-reading was reached.
        try: r.host.run_until(lambda _state: bool(cut), timeout=WATCHDOG)
        except StorageWaiting: pass
        assert cut, "execution result storage cut was not reached"
        r.advance(10); r.invoke(*measure, background=True)
        assert r.passive.gates[0].entered.wait(WATCHDOG)
        r.passive.symbols[0] = T; r.passive.gates[0].release.set()
        try: r.host.run_until(lambda _state: True, timeout=WATCHDOG)
        except StorageWaiting: pass
        state = r.host.window.status()
        waiting = [e for e in state.executions if e.outcome == "waiting_storage"]
        assert waiting and all(e.retryable for e in waiting)
        assert not r.facts(c.BELIEF_ADOPTED)
    finally: r.ledger.write = original
    r.until(lambda: bool(r.facts(contract("sui.fb.execution_result"))))
    r.adopt(2); r.assert_answer((P, P))


@pytest.mark.parametrize("moment", ["thinking", "actor_wait"])
def test_cycle1_identical_frame_redelivery_does_not_double_adopt_but_new_measurement_does(cycles, moment):
    r = cycles().start()
    if moment == "actor_wait": r.think(); r.enter_step()
    r.sense(0, T, begin=True); r.adopt(1)
    # Rebuild re-presents the same saved frame; it is not a second observation.
    saved = tuple(a.cid for a in r.adoption_chain()); r.host.rebuild_window()
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert tuple(a.cid for a in r.adoption_chain()) == saved
    r.sense(1, T); r.adopt(2); r.assert_answer((P, P))
    frames = r.frame_reports()
    assert frames[0].value["item"]["value"]["measurement_id"] != frames[1].value["item"]["value"]["measurement_id"]
    if moment == "actor_wait": r.finish_step(0, E)


def test_cycle1_two_empty_steps_are_distinct_even_without_passive_cursor_progress(cycles):
    r = cycles(shape="two").start(); r.think(); _, first = r.enter_step()
    r.finish_step(0, E); r.adopt(1)
    _, second = r.enter_step(1); r.finish_step(1, E); r.adopt(2)
    assert first != second and first.selection == second.selection
    assert first.node != second.node and r.passive.calls == []
    r.assert_answer((EMPTY, EMPTY))
    rows = [e for e in r.host.window.status().executions if e.execution in (first, second)]
    assert len(rows) == 2 and len({e.result for e in rows}) == 2


def test_cycle1_late_old_root_selection_is_saved_without_rewinding_current_intention(cycles):
    r = cycles(); observer = NativeEntryObserver(fb.Evaluator())
    r.direct(worker_overrides={"evaluation": observer})
    for stage in ORDER[:-1]: r.run(stage)
    old_q, old_body = r.offered("evaluation")
    gate = observer.hold(old_q)
    r.invoke(old_q, old_body, background=True)
    assert gate.entered.wait(WATCHDOG)  # Actual delegate.enter() already succeeded.
    assert observer.entries[old_q.value["desc"]["work_id"]] == [True]
    r.sense(0, T, begin=True); r.adopt(1)
    current = r.think()
    before = {x.cid for x in r.facts(c.SELECTION)}
    gate.release.set()
    r.until(lambda: len(r.facts(c.SELECTION)) == len(before) + 1)
    late = next(x for x in r.facts(c.SELECTION) if x.cid not in before)
    assert r.selected_value(late).root.root_key != r.selected_value(current).root.root_key
    active = [x for x in r.host.window.status().intentions if x.active]
    assert active and all(x.selection == current.cid for x in active)
    _, execution = r.enter_step()
    assert execution.selection == current.cid and execution.selection != late.cid
    r.finish_step(0, E)


def near_boundary_bits(prior, length):
    _, peek_probability = information_and_probability(prior)
    with localcontext() as ctx:
        ctx.prec = 100
        return int((1 - peek_probability) * Decimal(1 << length))


def test_cycle1_no_decision_never_creates_an_intention_or_execution(cycles):
    r = cycles(draw_bits=lambda n: near_boundary_bits((Q(1, 2), Q(1, 2)), n))
    initial = r.boot_input.declaration.initial
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=replace(initial.value, evaluate_budget=replace(UNBOUNDED, max_refinements=1)))))
    r.direct()
    for stage in ORDER: r.run(stage)
    r.until(lambda: any(x.response == "no_decision" for x in r.host.window.status().readings))
    assert not r.facts(c.SELECTION) and not r.host.window.status().intentions
    assert not r.requests("execute_step") and not r.actor.calls


def test_cycle1_review_no_decision_keeps_the_existing_live_intention(cycles):
    index = [0]
    def bits(n):
        index[0] += 1
        return 3 << (n - 2) if index[0] == 1 else near_boundary_bits((Q(2, 3), Q(1, 3)), n)
    r = cycles(draw_bits=bits)
    initial = r.boot_input.declaration.initial
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=replace(initial.value, evaluate_budget=replace(UNBOUNDED, max_refinements=1)))))
    r.direct(); chosen = r.think(); _, fixed = r.enter_step()
    r.sense(0, T, begin=True); r.adopt(1)
    for stage in ORDER[1:]: r.run(stage)
    r.until(lambda: any(x.response == "no_decision" for x in r.host.window.status().readings))
    assert {x.cid for x in r.facts(c.SELECTION)} == {chosen.cid}
    assert any(x.point == fixed.intention and x.active for x in r.host.window.status().intentions)
    r.finish_step(0, E); r.adopt(2); r.assert_answer((P, EMPTY))


@pytest.mark.parametrize("batch", [False, True], ids=["one-by-one", "saved-before-adoption"])
def test_cycle1_delivery_grouping_preserves_posterior_probability_and_next_E(cycles, batch):
    r = cycles().start(); r.sense(0, T, begin=True)
    if not batch: r.adopt(1)
    r.sense(1, E); r.adopt(2); r.assert_answer((P, EMPTY))
    selected = r.think(); assert_probability(r, selected, (Q(0), Q(1)))
    _, fixed = r.enter_step()
    assert fixed.selection == selected.cid and fixed.prior == r.adoption_chain()[-1].cid
    r.finish_step(0, E)


# K36-a (a): no fixture Need is needed by the birth entry or native registry.
def test_cycle1_native_need_registry_and_birth_path_do_not_depend_on_test_need(cycles):
    r = cycles()
    need = contract("sui.fb.one_seat_per_work")
    declarations = [d for d in r.registry.declarations if d.ref == need]
    implementations = [i for i in r.registry.implementations if i.ref == need]
    assert len(declarations) == len(implementations) == 1
    assert declarations[0].input_contract == c.NEED_INPUT
    assert declarations[0].output_contract == c.QUANTITY_VALUE
    assert not any(d.ref.name.startswith("test.") for d in r.registry.declarations)
    assert r.boot_input.declaration.scope.value.need == fb.MethodCall(contract=need, args={})
    r.start(); first = r.think()
    q, fixed = r.enter_step(); r.assert_fixed_image(q, fixed, first)
    active, = [w for w in r.host.window.status().works if w.work_id == q.value["desc"]["work_id"]]
    assert active.held == fb.QuantityValue(contract=c.SEATS, value=1)
    r.finish_step(0, T); r.adopt(1); r.assert_answer((P,))
    assert r.host.halted is None


def test_cycle1_start_requires_perception_and_names_the_absent_slot(cycles):
    r = cycles(thinking=False)
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration, perception=None))
    before = r.snapshot()
    with pytest.raises(fb.StartInputError) as caught: r.start()
    assert caught.value.reason == "perception_missing"
    assert "perception" in caught.value.field
    assert r.snapshot() == before
    assert not r.actor.calls and not r.passive.calls and not r.draw_calls


def test_cycle1_start_rejects_declared_execution_with_missing_actor_before_effects(cycles):
    r = cycles(); before = r.snapshot()
    with pytest.raises(fb.StartInputError) as caught:
        fb.start(ledger=r.ledger, clock=r.clock, clock_declaration=r.clock_declaration,
            boot=r.boot_input, sources={"route-A": r.passive}, actors={}, registry=r.registry,
            launcher=r.launcher, randbits=r.randbits)
    assert caught.value.reason == "actor_missing"
    assert "toy" in caught.value.field
    assert r.snapshot() == before
    assert not r.actor.calls and not r.passive.calls and not r.draw_calls


def test_cycle1_low_level_initial_without_perception_is_a_named_plan_shortage(cycles):
    r = cycles()
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration, perception=None))
    r.direct()
    r.until(lambda: any("perception" in p.reason for p in r.host.window.status().pending))
    assert not r.requests("candidate_generation") and not r.facts(c.SELECTION)
    assert not r.actor.calls and not r.draw_calls
    # The low-level measure-only route remains live; no invented model/origin.
    r.sense(0, T, begin=True)
    assert r.frame_reports() and not r.requests("belief_update")


def test_cycle1_missing_actor_before_call_is_unperformed_not_an_observation(cycles):
    # A low-level host has no birth-entry prevalidation. This is a public way to
    # reach the pre-call shortage, without removing a private runtime actor map.
    r = cycles().direct(actors={}); selected = r.think()
    r.run("execute_step")
    r.until(lambda: any(e.outcome == "not_performed" for e in r.host.window.status().executions))
    row, = [e for e in r.host.window.status().executions if e.outcome == "not_performed"]
    assert row.reason == "actor_missing:toy" and row.retryable is False
    assert row.result_symbol is None and row.source_called is False
    assert row.result is not None
    record = r.read_stored(row.result)[2]
    assert record.body.contract == contract("sui.fb.execution_result")
    assert record.body.content.as_json()["execution"] == wire(row.execution)
    assert not r.actor.calls and not r.facts(c.BELIEF_ADOPTED)
    assert not r.requests("belief_update")
    intention, = [i for i in r.host.window.status().intentions if i.selection == selected.cid]
    assert intention.active
    # Additional rounds neither retry the actor nor turn a non-call into an
    # unavailable observation or declared no-effect completion.
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("execute_step")) == 1 and not r.actor.calls
    assert not r.requests("belief_update") and not r.facts(c.BELIEF_ADOPTED)


# K36-c4: an admitted activity keeps its next stages after newer adoptions.
@pytest.mark.parametrize("stage", ["selection_draw", "evaluation"])
def test_cycle1_begun_thought_keeps_unentered_next_stage_after_a_newer_adoption(cycles, stage):
    r = cycles().thinking_seats(2)
    native = fb.UniformDraw(randbits=r.randbits) if stage == "selection_draw" else fb.Evaluator()
    observer = NativeEntryObserver(native)
    r.direct(worker_overrides={stage: observer}); r.run("candidate_generation")
    old = r.request_where("evaluation_prepare", lambda _q: True)
    r.run_request(old)  # The thought, not merely this next work, has begun.
    if stage == "evaluation": r.run_request(r.draw_for(old))
    waiting = r.draw_for(old) if stage == "selection_draw" else r.evaluation_for(old)
    old_id = waiting.value["desc"]["work_id"]
    assert old_id not in observer.entries
    r.sense(0, T, begin=True); r.adopt(1)
    newer = r.request_where("evaluation_prepare", lambda q: q.cid != old.cid)
    r.run_request(newer)
    first = r.finish_thought(old)
    assert observer.entries[old_id] == [True]
    assert_probability(r, first, (Q(1, 2), Q(1, 2)))
    second = r.finish_thought(newer)
    assert_probability(r, second, (Q(2, 3), Q(1, 3)))
    assert first.cid != second.cid and len(r.facts(c.SELECTION)) == 2
    assert r.read_stored(waiting.cid)[2].body.content.as_json() == waiting.value


@pytest.mark.parametrize("generator_entered", [False, True], ids=["Wg-starting", "Wg-entered"])
def test_cycle1_initial_activity_reads_all_pre_candidate_adoptions_as_one_latest_root(cycles, generator_entered):
    r = cycles().thinking_seats(2)
    generator = NativeEntryObserver(fb.CandidateGenerator())
    r.direct(worker_overrides={"candidate_generation": generator})
    qgen = r.request_where("candidate_generation", lambda _q: True)
    gate = generator.hold(qgen, timeout=3 * WATCHDOG)
    if generator_entered:
        r.run_request(qgen, background=True); assert gate.entered.wait(WATCHDOG)
    else:
        r.until(lambda: any(key == qgen.value["desc"]["work_id"] for key, _ in r.launcher.attempts))
        assert qgen.value["desc"]["work_id"] not in generator.entries
    initial_activity = evaluation_status(r)
    assert initial_activity.root == "undetermined" and initial_activity.context is None
    assert initial_activity.outcome == "running" and initial_activity.counted
    assert qgen.value["desc"]["work_id"] in initial_activity.residual
    r.sense(0, T, begin=True); r.adopt(1)
    assert r.passive.gates[1].entered.wait(WATCHDOG); r.running.stop()
    r.sense(1, T); r.adopt(2); r.assert_answer((P, P))
    pending = evaluation_status(r, activity=initial_activity.activity)
    assert pending.root == "undetermined" and pending.context is None
    material = thinking_material_status(r)
    assert material.latest == r.adoption_chain()[-1].cid and material.handed is None
    assert material.unevaluated and material.blocked_by == (initial_activity.activity,)
    assert {row.activity for row in r.host.window.status().evaluations} == {initial_activity.activity}
    assert not r.requests("evaluation_prepare") and not r.facts(fc.CANDIDATE_DECLARATION)
    gate.release.set()
    if not generator_entered: r.run_request(qgen, background=True)
    assert generator.wait_return(qgen.value["desc"]["work_id"])
    first = r.request_where("evaluation_prepare", lambda _q: True)
    fixed = activity_for_request(r, first)
    assert fixed.activity == initial_activity.activity
    assert fixed.root == "adopted" and fixed.root_point == r.adoption_chain()[-1].cid
    material = thinking_material_status(r)
    assert material.latest == material.handed == fixed.root_point
    assert not material.unevaluated and material.blocked_by == ()
    selected = r.finish_thought(first)
    assert_probability(r, selected, (Q(4, 5), Q(1, 5)))
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("candidate_generation")) == len(r.requests("evaluation_prepare")) == 1
    assert len(r.facts(c.SELECTION)) == 1


@pytest.mark.parametrize("stage", ["evaluation_prepare", "selection_draw"])
def test_cycle1_entered_old_prepare_or_draw_finishes_after_a_newer_review(cycles, stage):
    r = cycles()
    native = (fb.EvaluationPreparer(registry=r.registry) if stage == "evaluation_prepare"
              else fb.UniformDraw(randbits=r.randbits))
    observer = NativeEntryObserver(native); r.direct(worker_overrides={stage: observer})
    r.run("candidate_generation")
    old_round = r.request_where("evaluation_prepare", lambda _q: True)
    if stage == "selection_draw": r.run_request(old_round)
    old_q = old_round if stage == "evaluation_prepare" else r.draw_for(old_round)
    old_id = old_q.value["desc"]["work_id"]
    gate = observer.hold(old_q); r.run_request(old_q, background=True)
    assert gate.entered.wait(WATCHDOG) and observer.entries[old_id] == [True]
    r.sense(0, T, begin=True); r.adopt(1)
    newer = r.request_where("evaluation_prepare", lambda q: q.cid != old_round.cid)
    current = r.finish_thought(newer)
    gate.release.set(); assert observer.wait_return(old_id)
    r.until(lambda: any(t.value["work"] == old_id for t in r.facts(c.WORK_TERMINAL)))
    old_terminal, = [t for t in r.facts(c.WORK_TERMINAL) if t.value["work"] == old_id]
    assert old_terminal.value["terminal_kind"] == ("value" if stage == "selection_draw" else "outputs")
    late = r.finish_thought(old_round)
    assert r.selected_value(late).root.root_key != r.selected_value(current).root.root_key
    assert observer.entries[old_id] == [True]
    assert any(i.selection == current.cid and i.active for i in r.host.window.status().intentions)


@pytest.mark.parametrize("gap", [0, 1], ids=["equal-is-overlap", "strict-before-control"])
def test_cycle1_equal_endpoints_are_overlap_not_receipt_order(cycles, gap):
    r = cycles(passive=N, passive_empty=ZERO, overlap="serializable", same_target=True,
               prior=(Q(1, 3), Q(2, 3))).start()
    r.start_last_passive(); r.complete_last_passive(T)
    # Keep the earlier N saved but not yet adopted; isolate the endpoint rule.
    assert not r.facts(c.BELIEF_ADOPTED)
    r.advance(gap); r.think(); _, fixed = r.enter_step(); r.finish_step(0, T)
    frame = r.frame_reports()[0].value["item"]["value"]["measurement_interval"]
    assert r.actor.entered_ns[0] - frame["end_ns"] == gap
    if gap:
        r.adopt(2); r.assert_answer((N, P))
    else:
        r.until(lambda: any(e.execution == fixed and e.outcome == "order_unknown"
                            for e in r.host.window.status().executions))
        r.exercise_available_updates()
        assert not r.facts(c.BELIEF_ADOPTED)
        assert any(e.execution == fixed and not e.retryable
                   for e in r.host.window.status().executions)
    assert len(r.passive.calls) == len(r.actor.calls) == 1


@pytest.mark.parametrize("pending", ["actor", "passive"])
@pytest.mark.parametrize("all_cells_commute", [False, True], ids=["one-other-cell-does-not", "every-cell-commutes"])
def test_cycle1_pending_observation_checks_every_possible_cell_then_actual_cell(cycles, pending, all_cells_commute):
    half_swap = tuple(tuple(x / 2 for x in row) for row in N)
    if pending == "actor":
        actor_empty = HALF if all_cells_commute else ((Q(1, 2), Q(0)), (Q(0), Q(0)))
        actor_exception = None if all_cells_commute else ((Q(0), Q(0)), (Q(0), Q(1, 2)))
        r = cycles(peek=HALF, empty=actor_empty, exception=actor_exception,
                   passive=N, passive_empty=ZERO, overlap="serializable", same_target=True).start()
        r.think(); _, fixed = r.enter_step()
        r.start_last_passive(); r.complete_last_passive(T)
        known = N
    else:
        passive_empty = HALF if all_cells_commute else half_swap
        r = cycles(passive=HALF, passive_empty=passive_empty,
                   overlap="serializable", same_target=True).start()
        r.start_last_passive()
        r.think(); _, fixed = r.enter_step(); r.finish_step(0, T)
        known = P
    assert matmul(known, HALF) == matmul(HALF, known)
    if all_cells_commute:
        # Progress is witnessed BEFORE the other world's release. A fixed delay
        # or merely starting an updater cannot satisfy this assertion.
        r.adopt(1); r.assert_answer((known,))
    else:
        other = actor_empty if pending == "actor" else passive_empty
        assert matmul(known, other) != matmul(other, known)
        r.exercise_available_updates()
        assert not r.facts(c.BELIEF_ADOPTED)
        assert not any(e.execution == fixed and e.outcome == "order_unknown"
                       for e in r.host.window.status().executions)  # Still resolvable.
    if pending == "actor": r.finish_step(0, T)
    else: r.complete_last_passive(T)
    # The actual pending result is the commuting HALF in BOTH declarations.
    # Rejecting permanently on an impossible future result also fails here.
    r.adopt(2); r.assert_answer((known, HALF))
    assert len(r.passive.calls) == len(r.actor.calls) == 1


@pytest.mark.parametrize("gap", [0, 1], ids=["overlaps-adopted", "strictly-after-adopted-control"])
def test_cycle1_later_observation_checks_overlap_with_an_already_adopted_step(cycles, gap):
    r = cycles(passive=N, passive_empty=ZERO, overlap="serializable", same_target=True,
               prior=(Q(1, 3), Q(2, 3))).start()
    r.think(); _, fixed = r.enter_step(); r.finish_step(0, T); r.adopt(1)
    adopted_before = tuple(a.cid for a in r.adoption_chain())
    r.advance(gap); r.start_last_passive(); r.complete_last_passive(T)
    frame = r.frame_reports()[0].value["item"]["value"]["measurement_interval"]
    assert frame["start_ns"] - r.actor.returned_ns[0] == gap
    if gap:
        from test_fb_belief import BeliefSnapshotReader
        q, _ = r.offered("belief_update")
        records = {cid: r.read_stored(cid)[2] for cid, _ in r.entry_store.load()}
        direct = u2.compute_finite_update(q.cid, reader=BeliefSnapshotReader(records),
                                         registry=r.registry, evidence=None)
        expected_joint, expected_mass = enumerate_updates((P, N), r.prior)
        assert isinstance(direct, u2.IssuedUpdate)
        assert wire(direct.result) == {"joint": wire(expected_joint), "evidence_mass": wire(expected_mass)}
        r.adopt(2); r.assert_answer((P, N))
    else:
        def named_order_block():
            state = r.host.window.status()
            return (any(e.reason == "observation_order_unknown" for e in state.executions)
                    or any("observation_order_unknown" in u.reasons for u in state.updates)
                    or any("observation_order_unknown" in p.reason and p.target is not None
                           for p in state.pending))
        r.until(named_order_block)
        r.exercise_available_updates()
        assert tuple(a.cid for a in r.adoption_chain()) == adopted_before
        assert r.frame_reports() and r.read_stored(adopted_before[0])
        # Additional rounds cannot make unchanged, noncommuting intervals safe.
        r.exercise_available_updates()
        assert tuple(a.cid for a in r.adoption_chain()) == adopted_before
    assert len(r.passive.calls) == 1 and fixed.selection in {x.cid for x in r.facts(c.SELECTION)}


@pytest.mark.parametrize("kind", ["no_effect", "unconnected", "not_performed"])
def test_cycle1_nonobservational_steps_do_not_block_an_overlapping_passive_observation(cycles, kind):
    r = cycles(passive=N, passive_empty=ZERO, overlap="undeclared", same_target=True,
               draw_bits=(lambda n: 0) if kind == "no_effect" else None)
    if kind == "unconnected":
        kernel = next(k for k in r.document["kernels"] if k["id"] == "peek")
        for out in kernel["outcomes"]: out["elapsed_ns"] = 1
        record = r.record(Prediction(target="unconnected-overlap.model", about=(), basis=(),
            content=Payload.json({"document": r.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        r.model_point = r.ledger.append(record, ()).cid
        per = r.boot_input.declaration.perception
        r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
            perception=replace(per, value=replace(per.value, model=r.model_point))))
    if kind == "not_performed": r.direct(actors={})
    else: r.start()
    r.start_last_passive(); selected = r.think(); r.run("execute_step")
    r.until(lambda: any(e.execution.selection == selected.cid and e.outcome == kind
                        for e in r.host.window.status().executions))
    assert not r.actor.calls and not r.facts(c.BELIEF_ADOPTED)
    r.complete_last_passive(T); r.adopt(1); r.assert_answer((N,))
    assert not any(e.outcome == "order_unknown" for e in r.host.window.status().executions)


def test_cycle1_nonzero_cell_zero_on_current_prior_is_falsified_by_U_not_early_matrix_zero(cycles):
    from test_fb_belief import BeliefSnapshotReader
    only_a = ((Q(1), Q(0)), (Q(0), Q(0)))
    only_b = ((Q(0), Q(0)), (Q(0), Q(1)))
    r = cycles(prior=(Q(0), Q(1)), peek=only_b, empty=ZERO, exception=only_a).start()
    r.think(); _, fixed = r.enter_step(); r.finish_step(0, U)
    q, _body = r.offered("belief_update")
    assert not any(e.execution == fixed and e.outcome == "model_zero"
                   for e in r.host.window.status().executions)
    records = {cid: r.read_stored(cid)[2] for cid, _ in r.entry_store.load()}
    returned = u2.compute_finite_update(q.cid, reader=BeliefSnapshotReader(records),
                                       registry=r.registry, evidence=None)
    assert isinstance(returned, u2.Rejected)
    assert {issue.code for issue in returned.issues} == {"model_falsified"}
    r.run("belief_update")
    r.until(lambda: any(e.execution == fixed and e.outcome == "model_zero"
                        for e in r.host.window.status().executions))
    assert not r.facts(c.BELIEF_ADOPTED) and len(r.actor.calls) == 1


def test_cycle1_boot_without_execution_keeps_selections_without_accepting_them(cycles):
    r = cycles()
    per = r.boot_input.declaration.perception
    derivation = per.value.derivation
    args = dict(derivation.method.args); args.pop("execution")
    per = replace(per, value=replace(per.value, derivation=replace(derivation,
        method=replace(derivation.method, args=args))))
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        execution=None, perception=per))
    r.start(); first = r.think()
    assert first.cid in {x.cid for x in r.facts(c.SELECTION)}
    assert not r.host.window.status().intentions and not r.requests("execute_step")
    r.sense(0, T, begin=True); r.adopt(1); second = r.think()
    assert second.cid != first.cid and not r.requests("execute_step")
    assert not r.host.window.status().intentions and not r.actor.calls


# K36-b(ki): a saved S does not waive its dependencies at the next actual use.
@pytest.mark.parametrize("upstream", ["evaluation", "belief_update"])
@pytest.mark.parametrize("moment", ["before_entry", "after_entry", "equal_before_entry"])
def test_cycle1_selection_new_use_checks_late_terminal_clash_but_keeps_entered_result(cycles, upstream, moment):
    r = cycles()
    evaluator = NativeEntryObserver(fb.Evaluator())
    updater = NativeEntryObserver(fb.FiniteUpdater(registry=r.registry))
    executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"evaluation": evaluator, "belief_update": updater,
                               "execute_step": executor})
    if upstream == "belief_update":
        r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    selected = r.think()
    witness = evaluator if upstream == "evaluation" else updater
    ancestor = witness.request(r, upstream)
    q, body = r.offered("execute_step"); wid = q.value["desc"]["work_id"]
    assert any(key == wid for key, _ in r.launcher.attempts)
    assert wid not in executor.entries  # Launched does not mean admitted.
    if moment == "after_entry":
        r.invoke(q, body, background=True)
        assert r.actor.gates[0].entered.wait(WATCHDOG)
        assert executor.entries[wid] == [True]
    clash = moment != "equal_before_entry"
    witness.late_terminal(ancestor, clash=clash)
    ancestor_id = ancestor.value["desc"]["work_id"]
    r.until(lambda: len([x for x in r.facts(c.WORK_REPORT) if x.value["work"] == ancestor_id]) == 2)
    if clash:
        r.until(lambda: bool(r.facts(c.CONFLICT))
                        or any(p.kind == "conflict" for p in r.host.window.status().pending))
    else:
        assert not r.facts(c.CONFLICT)
    if moment != "after_entry": r.invoke(q, body, background=True)
    if moment == "before_entry":
        assert executor.wait_return(wid)
        assert executor.entries[wid] == [False] and not r.actor.calls
    else:
        assert r.actor.gates[0].entered.wait(WATCHDOG)
        assert executor.entries[wid] == [True]
        r.finish_step(0, T)
        fixed = r.actor.calls[0]
        row, = [e for e in r.host.window.status().executions if e.execution == fixed]
        assert row.result is not None and fixed.selection == selected.cid
        saved = r.read_stored(row.result)[2].body.content.as_json()
        assert saved["execution"] == wire(fixed) and saved["value"] == read1_symbol(T)
        assert len(r.actor.calls) == 1
    assert any(x.cid == selected.cid and x.value == selected.value for x in r.facts(c.SELECTION))


@pytest.mark.parametrize("conflicting", [False, True], ids=["same-notice-control", "different-source"])
def test_cycle1_clock_source_missing_before_perform_is_named_unperformed_not_an_observation(cycles, conflicting):
    r = cycles().start(); selected = r.think()
    q, body = r.offered("execute_step")
    declaration = (replace(r.clock_declaration, resolution_s=r.clock_declaration.resolution_s * 2)
                   if conflicting else r.clock_declaration)
    r.host.post(fb.ClockDeclared(declaration=declaration))
    r.until(lambda: len(r.facts(c.CLOCK_NOTICE)) == 2
                    and any(n.value == wire(declaration) for n in r.facts(c.CLOCK_NOTICE)))
    r.invoke(q, body, background=True)
    if not conflicting:
        assert r.actor.gates[0].entered.wait(WATCHDOG)
        r.finish_step(0, T); r.adopt(1); r.assert_answer((P,))
        return
    r.until(lambda: any(e.outcome == "not_performed" and e.reason == "clock_source_unavailable"
                        for e in r.host.window.status().executions))
    row, = [e for e in r.host.window.status().executions if e.execution.selection == selected.cid]
    assert row.outcome == "not_performed" and row.reason == "clock_source_unavailable"
    assert row.result is not None and row.source_called is False and row.result_symbol is None
    memo = r.read_stored(row.result)[2]
    assert memo.body.contract == contract("sui.fb.execution_result")
    assert memo.body.content.as_json()["execution"] == wire(row.execution)
    assert not r.actor.calls and not r.passive.calls and not r.facts(c.RECEIVED)
    assert not r.requests("belief_update") and not r.facts(c.BELIEF_ADOPTED)
    assert any(p.selection == selected.cid and p.reason == "clock_source_unavailable"
               for p in r.host.window.status().policies)


def test_cycle1_passive_adopted_through_ignores_a_preceding_execution_adoption(cycles):
    r = cycles().start(); r.think(); r.enter_step(); r.finish_step(0, T); r.adopt(1)
    r.advance(1); r.start_last_passive(); r.complete_last_passive(T); r.adopt(2)
    r.assert_answer((P, P))
    epoch = r.boot_input.declaration.routes[0].value.config.route_epoch
    frame, = r.frame_reports()
    binding, = [b for b in r.facts(c.SEGMENT_BINDING) if b.value["report"] == frame.cid]
    rows = [u for u in r.host.window.status().updates
            if u.obligation == binding.cid and u.route_epoch == epoch and u.sample_seq == 0]
    assert len(rows) == 1 and rows[0].outcome == "adopted"
    assert rows[0].adopted_through == 0
    assert (rows[0].published_through, rows[0].saved_through) == (0, 0)
    assert len(r.adoption_chain()) == 2 and len(r.frame_reports()) == 1


@pytest.mark.parametrize("delivery", ["update_first", "step_first"])
@pytest.mark.parametrize("gap", [0, 1], ids=["equal-noncommuting", "strict-before-control"])
def test_cycle1_decide_observation_order_before_adopting_any_already_delivered_reply(cycles, delivery, gap):
    r = cycles(passive=N, passive_empty=ZERO, overlap="serializable", same_target=True,
               prior=(Q(1, 3), Q(2, 3)))
    updater = NativeEntryObserver(fb.FiniteUpdater(registry=r.registry))
    executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"belief_update": updater, "execute_step": executor})
    r.start_last_passive(); r.complete_last_passive(T)
    r.think()
    step_q, step_body = r.offered("execute_step")
    update_q, update_body = r.offered("belief_update")
    update_id, step_id = update_q.value["desc"]["work_id"], step_q.value["desc"]["work_id"]
    gate = updater.hold(update_q); r.invoke(update_q, update_body, background=True)
    assert gate.entered.wait(WATCHDOG) and updater.entries[update_id] == [True]
    r.advance(gap)
    # From here until both callbacks return, invoke only actual worker bodies;
    # do not drive the host, settle, accept, or wait through CycleRig.until.
    if delivery == "update_first":
        gate.release.set(); assert updater.wait_return(update_id)
    r.invoke(step_q, step_body, background=True)
    assert r.actor.gates[0].entered.wait(WATCHDOG)
    frame = r.frame_reports()[0].value["item"]["value"]["measurement_interval"]
    assert r.actor.entered_ns[0] - frame["end_ns"] == gap
    r.actor.symbols[0] = T; r.actor.gates[0].release.set()
    assert executor.wait_return(step_id)
    if delivery == "step_first":
        gate.release.set(); assert updater.wait_return(update_id)
    for thread in r.threads:
        thread.join(WATCHDOG); assert not thread.is_alive()
    returned, issued = updater.posts[update_id][0]
    assert isinstance(returned.outcome, fb.WorkOutputs) and issued is not None
    assert len(r.actor.calls) == len(r.passive.calls) == 1
    assert not r.facts(c.BELIEF_ADOPTED)
    if gap:
        r.until(lambda: len(r.facts(c.BELIEF_ADOPTED)) >= 1)
        r.adopt(2); r.assert_answer((N, P))
    else:
        r.until(lambda: any(e.outcome == "order_unknown" for e in r.host.window.status().executions))
        r.exercise_available_updates()
        assert not r.facts(c.BELIEF_ADOPTED)
        assert not any(u.outcome == "adopted" for u in r.host.window.status().updates)
        assert any(e.outcome == "order_unknown" and not e.retryable
                   for e in r.host.window.status().executions)
        assert any(t.value["work"] == update_id and t.value["terminal_kind"] == "outputs"
                   for t in r.facts(c.WORK_TERMINAL))


@pytest.mark.parametrize("save_before_second", [False, True], ids=["before-first-save", "after-first-save"])
def test_cycle1_repeating_perform_with_same_fixed_E_is_rejected_without_second_actor_or_memo(cycles, save_before_second):
    r = cycles(); first_returned, allow_second, finished = Event(), Event(), Event()
    first_results, second_results, rejected = [], [], []
    class DuplicatePerform:
        def run(self, work, ctx):
            if not ctx.enter(): return
            fixed = work.desc.args
            try:
                first_results.append(ctx.perform(fixed)); first_returned.set()
                assert allow_second.wait(WATCHDOG), "second perform probe not released"
                try: second_results.append(ctx.perform(fixed))
                except Exception as error: rejected.append(type(error).__name__)
            finally: finished.set()
    r.direct(execute_worker=DuplicatePerform()); r.think(); r.run("execute_step", background=True)
    try:
        assert r.actor.gates[0].entered.wait(WATCHDOG)
        r.actor.symbols[0] = T; r.actor.gates[0].release.set()
        # If an incorrect second call reaches the actor, let it finish instead
        # of turning an extra-call failure into a test timeout.
        r.actor.symbols[1] = T; r.actor.gates[1].release.set()
        assert first_returned.wait(WATCHDOG)
        if save_before_second:
            r.until(lambda: any(e.result is not None for e in r.host.window.status().executions))
        # Otherwise no host round has occurred since the first call returned.
        allow_second.set(); assert finished.wait(WATCHDOG)
        assert len(first_results) == 1 and len(rejected) == 1 and not second_results
        assert len(r.actor.calls) == 1
        fixed = r.actor.calls[0]
        r.until(lambda: any(e.execution == fixed and e.result is not None
                            for e in r.host.window.status().executions))
        memos = r.facts(contract("sui.fb.execution_result"))
        assert len(memos) == 1 and memos[0].value["execution"] == wire(fixed)
        assert memos[0].value["value"] == read1_symbol(T)
    finally:
        allow_second.set()
        for gate in r.actor.gates: gate.release.set()


@pytest.mark.parametrize("selected", ["wait", "peek"], ids=["identity-control", "nonidentity-declared-no-effect"])
def test_cycle1_declared_no_effect_is_checked_against_selected_kernel(cycles, selected):
    r = cycles(draw_bits=(lambda n: 0) if selected == "wait" else None)
    execution = r.boot_input.declaration.execution
    # No actor binding competes with the claimed no-effect declaration.
    declaration = replace(execution.value, actors={}, no_effect=("wait", "peek"), cells={})
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        execution=replace(execution, value=declaration)))
    r.direct(actors={}); choice = r.think()
    assert r.selected_value(choice).choice.id == selected
    r.run("execute_step")
    expected = "no_effect" if selected == "wait" else "unconnected"
    r.until(lambda: any(e.execution.selection == choice.cid and e.outcome == expected
                        for e in r.host.window.status().executions))
    row, = [e for e in r.host.window.status().executions if e.execution.selection == choice.cid]
    assert row.outcome == expected and not r.actor.calls
    assert row.source_called is False and row.result_symbol is None
    assert not r.requests("belief_update") and not r.facts(c.BELIEF_ADOPTED)
    if selected == "peek":
        assert row.outcome != "no_effect"
        assert any(i.selection == choice.cid for i in r.host.window.status().intentions)


@pytest.mark.parametrize("replace_intention", [False, True], ids=["live-policy-control", "withdrawn-policy"])
def test_cycle1_replaced_two_step_policy_does_not_request_second_step_but_keeps_first_observation(cycles, replace_intention):
    r = cycles(shape="two").start(); old = r.think(); _, first = r.enter_step()
    if replace_intention:
        r.sense(0, T, begin=True); r.adopt(1); newer = r.think()
        assert newer.cid != old.cid
        r.until(lambda: any(p.selection == old.cid and p.outcome == "withdrawn"
                            for p in r.host.window.status().policies))
    r.finish_step(0, T)
    r.adopt(2 if replace_intention else 1)
    r.assert_answer((P, P) if replace_intention else (P,))
    old_steps = [q for q in r.requests("execute_step") if q.value["desc"]["args"]["selection"] == old.cid]
    if replace_intention:
        for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
        assert len(old_steps) == 1 and old_steps[0].value["desc"]["args"]["node"] == first.node
        assert not [q for q in r.requests("execute_step") if q.value["desc"]["args"]["selection"] == old.cid
                    and q.value["desc"]["args"]["node"] == "second"]
        assert any(p.selection == old.cid and p.outcome == "withdrawn"
                   for p in r.host.window.status().policies)
        assert len(r.actor.calls) == 1
    else:
        _, second = r.enter_step(1)
        assert second.selection == old.cid and second.node == "second"
        r.finish_step(1, E); r.adopt(2); r.assert_answer((P, EMPTY))


def next_cell_document(*, ambiguous):
    """F-a distinguishes public evidence slots; K36's declared result cell coarsens them.

    Identical F-a K with different next nodes is not certifiable. These distinct
    slots are a public, certified construction, not a fake Selected value.
    """
    document, _ = world_document(peek=HALF, empty=HALF, split=True, shape="two")
    plan = next(p for p in document["policies"] if p["id"] == "peek")
    first = next(n for n in plan["nodes"] if n["id"] == "first")
    second = next(n for n in plan["nodes"] if n["id"] == "second")
    second["kernel"], second["next"] = "wait", {"done": "end"}
    first["next"] = {"t0": "second", "t1": "end" if ambiguous else "second", "e": "end"}
    kernel = next(k for k in document["kernels"] if k["id"] == "peek")
    for index, out in enumerate(kernel["outcomes"][:2]):
        out["evidence"]["slot"] = f"m{index}"
        out["available"]["reveal"] = [f"m{index}"]
    return document


@pytest.mark.parametrize("ambiguous", [False, True], ids=["same-next-control", "different-next-in-one-cell"])
def test_cycle1_ambiguous_next_node_in_one_observation_cell_is_named_not_guessed(cycles, ambiguous):
    r = cycles(peek=HALF, empty=HALF, split=True, shape="two")
    r.replace_model(next_cell_document(ambiguous=ambiguous), label="next-cell.model")
    r.start(); selected = r.think(); assert r.selected_value(selected).choice.id == "peek"
    _, first = r.enter_step(); r.finish_step(0, T); r.adopt(1); r.assert_answer((HALF,))
    if ambiguous:
        r.until(lambda: any(p.selection == selected.cid and
                            (p.reason == "next_unknown" or p.outcome == "next_unknown")
                            for p in r.host.window.status().policies))
        for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
        steps = [q for q in r.requests("execute_step") if q.value["desc"]["args"]["selection"] == selected.cid]
        assert len(steps) == 1 and steps[0].value["desc"]["args"]["node"] == first.node
    else:
        q = r.run("execute_step")
        assert q.value["desc"]["args"]["selection"] == selected.cid
        assert q.value["desc"]["args"]["node"] == "second"
        r.until(lambda: any(e.execution.selection == selected.cid and e.execution.node == "second"
                            and e.outcome == "no_effect" for e in r.host.window.status().executions))
    assert len(r.actor.calls) == 1


@pytest.mark.parametrize("clash", [False, True], ids=["same-terminal-control", "conflicting-terminal"])
def test_cycle1_clash_after_entered_first_step_prevents_second_request_without_losing_result(cycles, clash):
    r = cycles(shape="two"); evaluator = NativeEntryObserver(fb.Evaluator())
    r.direct(worker_overrides={"evaluation": evaluator}); selected = r.think()
    _, first = r.enter_step()
    evaluation = evaluator.request(r, "evaluation")
    evaluator.late_terminal(evaluation, clash=clash)
    wid = evaluation.value["desc"]["work_id"]
    r.until(lambda: len([x for x in r.facts(c.WORK_REPORT) if x.value["work"] == wid]) == 2)
    if clash:
        r.until(lambda: bool(r.facts(c.CONFLICT))
                        or any(p.kind == "conflict" for p in r.host.window.status().pending))
    r.finish_step(0, T)
    row, = [e for e in r.host.window.status().executions if e.execution == first]
    assert row.result is not None
    assert r.read_stored(row.result)[2].body.content.as_json()["execution"] == wire(first)
    if clash:
        r.exercise_available_updates()
        assert not [q for q in r.requests("execute_step") if q.value["desc"]["args"]["selection"] == selected.cid
                    and q.value["desc"]["args"]["node"] == "second"]
        assert len(r.actor.calls) == 1
    else:
        r.adopt(1)
        _, second = r.enter_step(1)
        assert second.selection == selected.cid and second.node == "second"
        r.finish_step(1, E); r.adopt(2); r.assert_answer((P, EMPTY))
    assert any(s.cid == selected.cid and s.value == selected.value for s in r.facts(c.SELECTION))


# K36-c/c-a: explicit version-three activity admission.
def test_cycle1_reuse_candidates_version_three_declares_activity_admission(cycles):
    r = cycles()
    assert c.BOOT_DECLARATION == replace(contract("sui.fb.boot_declaration"), version="5")
    assert c.REUSE_CANDIDATES == replace(contract("sui.fb.reuse_candidates"), version="3")
    assert r.boot_input.declaration.initial.value.continuation == fb.MethodCall(
        contract=c.REUSE_CANDIDATES, args={})
    assert r.boot_input.declaration.execution.contract == replace(
        contract("sui.fb.execution_declaration"), version="2")
    assert {"evaluations", "thinking_materials"} <= {x.name for x in fields(fb.FStatus)}


def test_cycle1_fast_passive_adoptions_preserve_selections_and_execution_with_separate_allocations(cycles):
    r = cycles().thinking_seats(1, execution=True)
    observers = {"evaluation_prepare": NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry)),
                 "selection_draw": NativeEntryObserver(fb.UniformDraw(randbits=r.randbits)),
                 "evaluation": NativeEntryObserver(fb.Evaluator())}
    r.direct(worker_overrides=observers); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    for index, stage in enumerate(("evaluation_prepare", "selection_draw", "evaluation")):
        q = first if index == 0 else r.draw_for(first) if index == 1 else r.evaluation_for(first)
        observer = observers[stage]; gate = observer.hold(q)
        r.run_request(q, background=True); assert gate.entered.wait(WATCHDOG)
        if index == 2:
            assert r.passive.gates[index].entered.wait(WATCHDOG); r.running.stop()
        r.sense(index, T, begin=index == 0); r.adopt(index + 1)
        assert {x.cid for x in r.requests("evaluation_prepare")} == {first.cid}
        assert not r.facts(c.SELECTION)
        gate.release.set(); assert observer.wait_return(q.value["desc"]["work_id"])
    r.until(lambda: len(r.facts(c.SELECTION)) == 1)
    selected, = r.facts(c.SELECTION)
    assert_probability(r, selected, (Q(1, 2), Q(1, 2)))
    _, old_E = r.enter_step(selection=selected.cid)
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    next_selection = r.finish_thought(second)
    assert_probability(r, next_selection, (Q(8, 9), Q(1, 9)))
    assert len(r.actor.calls) == 1 and r.actor.calls[0].selection == selected.cid
    r.finish_step(0, T); r.adopt(4)
    _, new_E = r.enter_step(1, selection=next_selection.cid)
    assert new_E.selection != old_E.selection
    r.finish_step(1, E)
    assert len(r.facts(c.SELECTION)) == 2 and len(r.actor.calls) == 2


@pytest.mark.parametrize("seats", [1, 2])
def test_cycle1_bit_continuation_keeps_its_activity_after_a_newer_adoption(cycles, seats):
    calls = []
    def bits(n):
        calls.append(n)
        return (1 << n) // 3 if len(calls) == 1 else 0
    perfect = ((Q(1), Q(0)), (Q(0), Q(0)))
    other = ((Q(0), Q(0)), (Q(0), Q(1)))
    r = cycles(peek=perfect, empty=other, draw_bits=bits).thinking_seats(seats)
    draws = NativeEntryObserver(fb.UniformDraw(randbits=r.randbits))
    evaluator = NativeEntryObserver(fb.Evaluator())
    r.direct(worker_overrides={"selection_draw": draws, "evaluation": evaluator})
    r.run("candidate_generation")
    old = r.request_where("evaluation_prepare", lambda _q: True)
    initial_activity = activity_for_request(r, old)
    assert initial_activity.root == "prior" and initial_activity.root_point is None
    r.run_request(old); first_draw = r.draw_for(old); r.run_request(first_draw)
    first_evaluation = r.evaluation_for(old); r.run_request(first_evaluation)
    wid = first_evaluation.value["desc"]["work_id"]
    _, artifact = evaluator.posts[wid][0]
    assert isinstance(artifact.value, f.NoDecision)
    assert artifact.value.outcome == "incomplete" and artifact.value.reason == "selection_boundary"
    following = r.draw_for(old, fresh=True); next_id = following.value["desc"]["work_id"]
    continued = evaluation_status(r, activity=initial_activity.activity)
    assert continued.context == initial_activity.context
    assert continued.outcome == "running" and continued.counted
    assert next_id not in draws.entries
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    if seats == 1:
        assert {q.cid for q in r.requests("evaluation_prepare")} == {old.cid}
        material = thinking_material_status(r)
        assert material.unevaluated and material.blocked_by == (initial_activity.activity,)
    r.run_request(following)
    assert draws.entries[next_id] == [True]
    evaluation = r.evaluation_for(old, fresh=True)
    r.run_request(evaluation); r.until(lambda: bool(r.facts(c.SELECTION)))
    selected, = r.facts(c.SELECTION); value = r.selected_value(selected)
    assert len(value.root.selection_prefix) == 2
    assert value.prefix == f.DrawPrefix(bits=((1 << calls[0]) // 3) << calls[1], length=sum(calls))
    assert calls == [c.OS_UNIFORM_BITS_BLOCK, c.OS_UNIFORM_BITS_BLOCK]
    assert value.choice.id == "wait"
    r.until(lambda: evaluation_status(r, activity=initial_activity.activity).outcome == "selected"
                    and not evaluation_status(r, activity=initial_activity.activity).counted)
    completed = evaluation_status(r, activity=initial_activity.activity)
    assert completed.context == initial_activity.context and completed.residual == ()


@pytest.mark.parametrize("next_stage", ["selection_draw", "evaluation"])
def test_cycle1_begun_thoughts_do_not_block_each_others_saved_next_stage(cycles, next_stage):
    r = cycles().thinking_seats(2)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    draws = NativeEntryObserver(fb.UniformDraw(randbits=r.randbits))
    evaluator = NativeEntryObserver(fb.Evaluator())
    r.direct(worker_overrides={"evaluation_prepare": preparer,
                              "selection_draw": draws, "evaluation": evaluator})
    r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    first_entry, first_post = preparer.hold(first), preparer.hold_post(first)
    r.run_request(first, background=True); assert first_entry.entered.wait(WATCHDOG)
    r.sense(0, T, begin=True); r.adopt(1)
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    second_entry, second_post = preparer.hold(second), preparer.hold_post(second)
    r.run_request(second, background=True); assert second_entry.entered.wait(WATCHDOG)
    rounds = (first, second)
    for gate in (first_entry, second_entry): gate.release.set()
    for gate in (first_post, second_post): assert gate.entered.wait(WATCHDOG)
    parent_requests, parent_observer = rounds, preparer
    parent_posts = (first_post, second_post)
    requests = tuple(r.draw_for(q) for q in rounds)
    observer = draws
    if next_stage == "evaluation":
        draw_entries = tuple(draws.hold(q) for q in requests)
        draw_posts = tuple(draws.hold_post(q) for q in requests)
        for gate in parent_posts: gate.release.set()
        for q in parent_requests: assert parent_observer.wait_return(q.value["desc"]["work_id"])
        for q in requests: r.run_request(q, background=True)
        for gate in draw_entries: assert gate.entered.wait(WATCHDOG)
        for gate in draw_entries: gate.release.set()
        for gate in draw_posts: assert gate.entered.wait(WATCHDOG)
        parent_requests, parent_observer, parent_posts = requests, draws, draw_posts
        requests = tuple(r.evaluation_for(q) for q in rounds)
        observer = evaluator
    # Both native parents posted but have not returned, so both seats remain held.
    assert all(not parent_observer.returned[q.value["desc"]["work_id"]].is_set()
               for q in parent_requests)
    rows = {w.work_id: w for w in r.host.window.status().works}
    for own, other in ((requests[0], requests[1]), (requests[1], requests[0])):
        row = rows[own.value["desc"]["work_id"]]
        assert row.phase == "pending" and not row.startable
        assert other.cid not in row.blocked_by
    entries = tuple(observer.hold(q) for q in requests)
    for gate in parent_posts: gate.release.set()
    for q in parent_requests: assert parent_observer.wait_return(q.value["desc"]["work_id"])
    for q in requests: r.run_request(q, background=True)
    assert all(gate.entered.wait(WATCHDOG) for gate in entries)
    for own, other in ((requests[0], requests[1]), (requests[1], requests[0])):
        assert observer.entries[own.value["desc"]["work_id"]] == [True]
        row, = [w for w in r.host.window.status().works if w.work_id == own.value["desc"]["work_id"]]
        assert other.cid not in row.blocked_by
    for gate in entries: gate.release.set()
    for q in requests: assert observer.wait_return(q.value["desc"]["work_id"])
    selected_first, selected_second = (r.finish_thought(q) for q in rounds)
    assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
    assert_probability(r, selected_second, (Q(2, 3), Q(1, 3)))
    assert len(r.facts(c.SELECTION)) == 2 and not r.facts(contract("sui.fb.thinking_yielded"))


# Request93: boundaries missed by the earlier scheduling/step-display scenes.


@pytest.mark.parametrize("clash", [False, True], ids=["equal-return-control", "late-clash"])
def test_cycle1_pending_step_names_conflicting_selection_before_any_launch(cycles, clash):
    r = cycles()
    evaluator = NativeEntryObserver(fb.Evaluator())
    executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"evaluation": evaluator, "execute_step": executor})
    normal_launch, held = r.launcher.launch, []
    def keep_step_pending(work_id, body):
        if any(q.value["desc"]["work_id"] == work_id for q in r.requests("execute_step")):
            if not held: held.append((work_id, body))
            return "not_started"
        return normal_launch(work_id, body)
    r.launcher.launch = keep_step_pending
    try:
        selected = r.think(); ancestor = evaluator.request(r, "evaluation")
        step = r.request_where("execute_step", lambda _q: True)
        wid = step.value["desc"]["work_id"]
        r.until(lambda: bool(held)); assert held[0][0] == wid
        assert wid not in {key for key, _ in r.launcher.attempts} and wid not in executor.entries
        before, = [w for w in r.host.window.status().works if w.work_id == wid]
        assert before.phase == "pending"
        evaluator.late_terminal(ancestor, clash=clash)
        ancestor_id = ancestor.value["desc"]["work_id"]
        r.until(lambda: len([x for x in r.facts(c.WORK_REPORT) if x.value["work"] == ancestor_id]) == 2)
        if clash:
            r.until(lambda: bool(r.facts(c.CONFLICT)) or
                            any(p.kind == "conflict" for p in r.host.window.status().pending))
        row, = [w for w in r.host.window.status().works if w.work_id == wid]
        assert row.phase == "pending" and wid not in executor.entries and not r.actor.calls
        if clash:
            assert not row.startable and selected.cid in row.blocked_by
        else:
            assert selected.cid not in row.blocked_by
    finally:
        r.launcher.launch = normal_launch
    if clash:
        for _ in range(4): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
        assert wid not in {key for key, _ in r.launcher.attempts}
        assert not r.facts(contract("sui.fb.execution_result")) and not r.actor.calls
    else:
        r.run_request(step, background=True)
        assert r.actor.gates[0].entered.wait(WATCHDOG) and executor.entries[wid] == [True]
        r.finish_step(0, T); r.adopt(1); r.assert_answer((P,))
    assert r.read_stored(step.cid)[2].body.content.as_json() == step.value


# K36-c: probes keep the actual work/port; wrong-family D supplies valid clock fields.
class ActivityTerminalPort(ObservedEntryPort):
    def post(self, event, issued=None):
        if self.owner.mode == "wrong_draw_terminal" and isinstance(event, fb.DrawReturned):
            reading = self.now()
            event = fb.WorkFinished(work=event.work, started=reading, finished=reading,
                outcome=fb.WorkUnknown(unknown=fb.UnknownInfo(
                    reason="test wrong notification family for D", basis=())))
            issued = None
        if isinstance(event, fb.WorkFinished):
            if self.owner.mode == "failure":
                event = replace(event, outcome=fb.WorkFailure(failure=fb.FailureInfo(
                    failure_kind="execution_error", content={"error_type": "RuntimeError"},
                    readings=(), basis=())))
                issued = None
            elif self.owner.mode == "unknown":
                event = replace(event, outcome=fb.WorkUnknown(
                    unknown=fb.UnknownInfo(reason="test terminal unknown", basis=())))
                issued = None
        return super().post(event, issued=issued)


class ActivityTerminalObserver(NativeEntryObserver):
    def __init__(self, worker, mode="native"):
        super().__init__(worker); self.mode = mode
    def run(self, work, ctx):
        wid = work.desc.work_id
        self.contexts[wid] = ctx
        done = self.returned.setdefault(wid, Event())
        port = ActivityTerminalPort(self, work, ctx)
        try:
            if self.mode == "stopped":
                if port.enter(): raise SystemExit("test worker actually stopped after entry")
                return
            return self.worker.run(work, port)
        finally: done.set()


def test_cycle1_busy_activity_batches_adoptions_and_admits_only_the_latest_unused_root(cycles):
    r = cycles().thinking_seats(1)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    gate = preparer.hold(first, timeout=3 * WATCHDOG)
    r.run_request(first, background=True); assert gate.entered.wait(WATCHDOG)
    initial_activity = activity_for_request(r, first)
    assert initial_activity.root == "prior" and initial_activity.counted
    r.sense(0, T, begin=True); r.adopt(1)
    assert r.passive.gates[1].entered.wait(WATCHDOG); r.running.stop()
    r.sense(1, T); r.adopt(2); r.assert_answer((P, P))
    material = thinking_material_status(r)
    assert material.latest == r.adoption_chain()[-1].cid and material.handed is None
    assert material.unevaluated and material.blocked_by == (initial_activity.activity,)
    assert {row.activity for row in r.host.window.status().evaluations} == {initial_activity.activity}
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert {q.cid for q in r.requests("evaluation_prepare")} == {first.cid}
    gate.release.set(); assert preparer.wait_return(first.value["desc"]["work_id"])
    selected_first = r.finish_thought(first)
    assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
    latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    next_activity = activity_for_request(r, latest)
    assert next_activity.activity != initial_activity.activity
    assert next_activity.root == "adopted" and next_activity.root_point == material.latest
    handed = thinking_material_status(r)
    assert handed.latest == handed.handed == material.latest
    assert not handed.unevaluated and handed.blocked_by == ()
    selected_latest = r.finish_thought(latest)
    assert_probability(r, selected_latest, (Q(4, 5), Q(1, 5)))
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("evaluation_prepare")) == len(r.facts(c.SELECTION)) == 2
    assert not r.facts(contract("sui.fb.thinking_yielded"))


@pytest.mark.parametrize("mode", ["failure", "unknown", "stopped"])
def test_cycle1_terminal_or_stop_never_rewinds_the_handed_root_boundary(cycles, mode):
    r = cycles().thinking_seats(1)
    observer = ActivityTerminalObserver(fb.EvaluationPreparer(registry=r.registry), mode)
    r.direct(worker_overrides={"evaluation_prepare": observer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    initial_activity = activity_for_request(r, first)
    r.run_request(first, background=True)
    wid = first.value["desc"]["work_id"]
    assert observer.wait_return(wid) and observer.entries[wid] == [True]
    r.until(lambda: any(w.work_id == wid and w.stop_confirmed for w in r.host.window.status().works))
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert {q.cid for q in r.requests("evaluation_prepare")} == {first.cid}
    assert len(r.requests("candidate_generation")) == 1 and not r.facts(c.SELECTION)
    ended = evaluation_status(r, activity=initial_activity.activity)
    assert ended.outcome == mode
    assert not ended.counted and ended.residual == ()
    observer.mode = "native"
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    next_activity = activity_for_request(r, second)
    assert next_activity.activity != initial_activity.activity
    assert next_activity.root_point == r.adoption_chain()[-1].cid
    material = thinking_material_status(r)
    assert material.handed == material.latest == next_activity.root_point
    assert not material.unevaluated
    selected = r.finish_thought(second)
    assert_probability(r, selected, (Q(2, 3), Q(1, 3)))
    assert len(r.requests("evaluation_prepare")) == 2


@pytest.mark.parametrize("ending", ["failure", "terminal_clash"])
def test_cycle1_logical_end_with_a_live_worker_still_occupies_activity_capacity(cycles, ending):
    r = cycles().thinking_seats(1)
    observer = ActivityTerminalObserver(fb.EvaluationPreparer(registry=r.registry),
                                        "failure" if ending == "failure" else "native")
    r.direct(worker_overrides={"evaluation_prepare": observer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    wid = first.value["desc"]["work_id"]
    gate = observer.hold_post(first, timeout=3 * WATCHDOG)
    r.run_request(first, background=True); assert gate.entered.wait(WATCHDOG)
    if ending == "failure":
        r.until(lambda: any(t.value["work"] == wid and t.value["terminal_kind"] == "failure"
                            for t in r.facts(c.WORK_TERMINAL)))
    else:
        r.prepared_for(first)
        observer.late_terminal(first, clash=True)
        r.until(lambda: len([x for x in r.facts(c.WORK_REPORT) if x.value["work"] == wid]) == 2)
        r.until(lambda: bool(r.facts(c.CONFLICT)) or
                        any(p.kind == "conflict" for p in r.host.window.status().pending))
    assert not observer.returned[wid].is_set()
    row, = [w for w in r.host.window.status().works if w.work_id == wid]
    assert row.held is not None and row.held.value == 1
    initial_activity = activity_for_request(r, first)
    assert initial_activity.outcome == ("failure" if ending == "failure" else "conflict")
    assert initial_activity.counted and initial_activity.residual == (wid,)
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert {q.cid for q in r.requests("evaluation_prepare")} == {first.cid}
    material = thinking_material_status(r)
    assert material.latest == r.adoption_chain()[-1].cid and material.handed is None
    assert material.unevaluated and material.blocked_by == (initial_activity.activity,)
    assert {row.activity for row in r.host.window.status().evaluations} == {initial_activity.activity}
    observer.mode = "native"
    gate.release.set(); assert observer.wait_return(wid)
    r.until(lambda: not evaluation_status(r, activity=initial_activity.activity).counted)
    assert evaluation_status(r, activity=initial_activity.activity).residual == ()
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    selected = r.finish_thought(second)
    assert_probability(r, selected, (Q(2, 3), Q(1, 3)))


@pytest.mark.parametrize("mode", ["failure", "unknown", "stopped", "no_candidates"])
def test_cycle1_first_generator_terminal_does_not_recreate_the_initial_activity(cycles, mode):
    r = cycles().thinking_seats(2)
    if mode == "no_candidates":
        document = deepcopy(r.document); document["operations"] = []
        r.replace_model(document)
    observer = ActivityTerminalObserver(fb.CandidateGenerator(), "native" if mode == "no_candidates" else mode)
    r.direct(worker_overrides={"candidate_generation": observer})
    qgen = r.request_where("candidate_generation", lambda _q: True)
    wid = qgen.value["desc"]["work_id"]
    initial_activity = evaluation_status(r)
    assert initial_activity.root == "undetermined" and initial_activity.context is None
    r.run_request(qgen, background=True); assert observer.wait_return(wid)
    r.until(lambda: any(w.work_id == wid and w.stop_confirmed for w in r.host.window.status().works))
    if mode == "no_candidates":
        r.until(lambda: any(row.response == "no_candidates" for row in r.host.window.status().readings))
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("candidate_generation")) == 1
    assert not r.requests("evaluation_prepare") and not r.facts(c.SELECTION)
    ended = evaluation_status(r, activity=initial_activity.activity)
    assert ended.root == "undetermined" and ended.root_point is None and ended.context is None
    assert ended.outcome == mode
    assert not ended.counted and ended.residual == ()


def test_cycle1_continuation_none_keeps_only_the_first_activity_despite_fresh_material(cycles):
    r = cycles().thinking_seats(2)
    initial = r.boot_input.declaration.initial
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=replace(initial.value, continuation=None))))
    r.direct(); selected = r.think()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("evaluation_prepare")) == 1
    assert {s.cid for s in r.facts(c.SELECTION)} == {selected.cid}


def test_cycle1_two_activities_run_distinct_roots_and_batch_only_after_both_are_busy(cycles):
    r = cycles().thinking_seats(2)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    first_gate = preparer.hold(first, timeout=3 * WATCHDOG)
    r.run_request(first, background=True); assert first_gate.entered.wait(WATCHDOG)
    r.sense(0, T, begin=True); r.adopt(1)
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    second_gate = preparer.hold(second, timeout=3 * WATCHDOG)
    r.run_request(second, background=True); assert second_gate.entered.wait(WATCHDOG)
    assert not first_gate.release.is_set()
    first_activity, second_activity = activity_for_request(r, first), activity_for_request(r, second)
    assert first_activity.activity != second_activity.activity
    assert first_activity.root == "prior" and second_activity.root == "adopted"
    assert second_activity.root_point == r.adoption_chain()[-1].cid
    assert sum(row.counted for row in r.host.window.status().evaluations) == 2
    assert r.passive.gates[1].entered.wait(WATCHDOG); r.running.stop()
    r.sense(1, T); r.adopt(2)
    assert {q.cid for q in r.requests("evaluation_prepare")} == {first.cid, second.cid}
    material = thinking_material_status(r)
    assert material.latest == r.adoption_chain()[-1].cid
    assert material.handed == second_activity.root_point and material.unevaluated
    assert set(material.blocked_by) == {first_activity.activity, second_activity.activity}
    assert {row.activity for row in r.host.window.status().evaluations} == {first_activity.activity, second_activity.activity}
    first_gate.release.set(); assert preparer.wait_return(first.value["desc"]["work_id"])
    s0 = r.finish_thought(first)
    third = r.request_where("evaluation_prepare", lambda q: q.cid not in {first.cid, second.cid})
    second_gate.release.set(); assert preparer.wait_return(second.value["desc"]["work_id"])
    s1, s2 = r.finish_thought(second), r.finish_thought(third)
    for selected, prior in ((s0, (Q(1, 2), Q(1, 2))), (s1, (Q(2, 3), Q(1, 3))), (s2, (Q(4, 5), Q(1, 5)))):
        assert_probability(r, selected, prior)
    assert len(r.facts(c.SELECTION)) == len(r.requests("evaluation_prepare")) == 3


def test_cycle1_one_thinking_and_one_execution_allocation_allow_simultaneous_entry(cycles):
    r = cycles().thinking_seats(1, execution=True)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer})
    chosen = r.think(); step, fixed = r.enter_step(selection=chosen.cid)
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    fresh = r.request_where("evaluation_prepare", lambda q:
                            q.value["desc"]["work_id"] not in preparer.contexts)
    gate = preparer.hold(fresh)
    r.run_request(fresh, background=True); assert gate.entered.wait(WATCHDOG)
    assert not r.actor.gates[0].release.is_set() and len(r.actor.calls) == 1
    rows = {w.work_id: w for w in r.host.window.status().works}
    assert all(rows[q.value["desc"]["work_id"]].held.value == 1 for q in (step, fresh))
    assert step.value["desc"]["allocation"]["slot"] == "execution-allocation"
    assert fresh.value["desc"]["allocation"]["slot"] == "thinking-allocation"
    assert step.value["desc"]["process"] == fresh.value["desc"]["process"]
    statuses = r.host.window.status().evaluations
    assert sum(row.counted for row in statuses) == 1
    assert all(step.value["desc"]["work_id"] not in row.residual for row in statuses)
    assert activity_for_request(r, fresh).counted
    gate.release.set(); assert preparer.wait_return(fresh.value["desc"]["work_id"])
    newer = r.finish_thought(fresh)
    assert_probability(r, newer, (Q(2, 3), Q(1, 3)))
    r.finish_step(0, T); r.adopt(2)
    assert r.actor.calls[0] == fixed and fixed.selection == chosen.cid


def test_cycle1_zero_execution_allocation_never_uses_a_thinking_seat(cycles):
    r = cycles().thinking_seats(1, execution=True).execution_seats(0).start()
    selected = r.think()
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    r.until(lambda: any(w.purpose == "execute_step" for w in r.host.window.status().works))
    rows = [w for w in r.host.window.status().works if w.purpose == "execute_step"]
    row, = rows
    assert row.phase == "pending" and not row.startable and row.blocked_by == () and row.held is None
    execution, = [x for x in r.host.window.status().executions if x.execution.selection == selected.cid]
    assert execution.outcome == "requested"
    ids = {w.work_id for w in rows} | {q.value["desc"]["work_id"] for q in r.requests("execute_step")}
    assert not [key for key, _ in r.launcher.attempts if key in ids]
    assert not r.actor.calls and not r.facts(contract("sui.fb.execution_result"))
    assert selected.cid in {s.cid for s in r.facts(c.SELECTION)}


def test_cycle1_unused_execution_allocation_is_not_lent_to_busy_thinking(cycles):
    r = cycles().thinking_seats(1, execution=True).execution_seats(3)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    gate = preparer.hold(first, timeout=3 * WATCHDOG)
    r.run_request(first, background=True); assert gate.entered.wait(WATCHDOG)
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert len(r.requests("evaluation_prepare")) == 1 and not r.actor.calls
    gate.release.set(); assert preparer.wait_return(first.value["desc"]["work_id"])
    r.finish_thought(first)
    fresh = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    selected = r.finish_thought(fresh)
    assert_probability(r, selected, (Q(2, 3), Q(1, 3)))


@pytest.mark.parametrize("clash", [False, True], ids=["new-S-does-not-retarget", "clash-ends-start-and-recompares"])
def test_cycle1_claimed_execution_start_keeps_its_selection_until_entry_or_conflict(cycles, clash):
    r = cycles().thinking_seats(2, execution=True)
    evaluator = NativeEntryObserver(fb.Evaluator()); executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"evaluation": evaluator, "execute_step": executor})
    old = r.think(); ancestor = evaluator.request(r, "evaluation")
    step, body = r.offered("execute_step"); wid = step.value["desc"]["work_id"]
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    adopted, = r.adoption_chain(); new = r.think()
    assert new.cid != old.cid and wid not in executor.entries
    r.until(lambda: any(row.selected == new.cid for row in r.host.window.status().readings))
    state = r.host.window.status()
    assert not any(i.selection == new.cid for i in state.intentions)
    assert not any(p.selection == new.cid for p in state.policies)
    assert not any(x.execution.selection == new.cid for x in state.executions)
    old_execution, = [x for x in state.executions if x.execution.selection == old.cid]
    assert old_execution.outcome == "requested"
    evaluator.late_terminal(ancestor, clash=clash)
    r.until(lambda: len([x for x in r.facts(c.WORK_REPORT)
                        if x.value["work"] == ancestor.value["desc"]["work_id"]]) == 2)
    if clash:
        r.invoke(step, body); assert executor.entries[wid] == [False] and not r.actor.calls
        _, fixed = r.enter_step(selection=new.cid)
        assert fixed.selection == new.cid and fixed.prior == adopted.cid
        r.until(lambda: any(p.selection == old.cid and p.outcome == "stopped" and
                            p.reason == "selection_conflict" for p in r.host.window.status().policies))
    else:
        r.invoke(step, body, background=True); assert r.actor.gates[0].entered.wait(WATCHDOG)
        assert executor.entries[wid] == [True] and r.actor.calls[0].selection == old.cid
        entered, = [x for x in r.host.window.status().executions if x.execution.selection == old.cid]
        assert entered.outcome == "entered"
    r.finish_step(0, T); r.adopt(2)
    assert {old.cid, new.cid} <= {s.cid for s in r.facts(c.SELECTION)}


@pytest.mark.parametrize("phase", ["before_write", "ack_loss"])
@pytest.mark.parametrize("clash", [False, True], ids=["same-target-through-retry", "conflict-releases-target"])
def test_cycle1_fixed_intention_retry_keeps_start_target_but_never_uses_a_conflicted_target(cycles, phase, clash):
    r = cycles().thinking_seats(2, execution=True)
    evaluator = NativeEntryObserver(fb.Evaluator())
    executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"evaluation": evaluator, "execute_step": executor})
    for stage in ORDER[:-1]: r.run(stage)
    evaluation, body = r.offered("evaluation")
    cut = FixedRecordSaveCut(r, phase)
    try:
        r.invoke(evaluation, body)
        try: r.host.run_until(lambda _s: cut.prepared is not None, timeout=WATCHDOG)
        except FixedRecordSaveCut.Unavailable: pass
        cut.assert_pending()
        fixed_intention = cut.prepared
        old_point = fixed_intention.record.body.content.as_json()["selection"]
        if phase == "before_write":
            state = r.host.window.status()
            assert not any(i.selection == old_point for i in state.intentions)
            assert not any(p.selection == old_point for p in state.policies)
            assert not any(x.execution.selection == old_point for x in state.executions)
        cut.retry_pending()
    finally: cut.restore()
    r.until(lambda: any(x.cid == fixed_intention.cid for x in r.facts(contract("sui.fb.intention"))))
    assert r.read_stored(fixed_intention.cid)[2] == fixed_intention.record
    old_step, old_body = r.offered("execute_step")
    old_wid = old_step.value["desc"]["work_id"]
    assert old_step.value["desc"]["args"]["selection"] == old_point
    assert old_wid not in executor.entries and not r.actor.calls
    # Storage is available again, but the claimed start still awaits entry.
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    new = r.think()
    assert new.cid != old_point
    r.until(lambda: any(row.selected == new.cid for row in r.host.window.status().readings))
    state = r.host.window.status()
    assert not any(i.selection == new.cid for i in state.intentions)
    assert not any(p.selection == new.cid for p in state.policies)
    assert not any(x.execution.selection == new.cid for x in state.executions)
    evaluator.late_terminal(evaluation, clash=clash)
    wid = evaluation.value["desc"]["work_id"]
    r.until(lambda: len([x for x in r.facts(c.WORK_REPORT) if x.value["work"] == wid]) == 2)
    if clash:
        r.invoke(old_step, old_body)
        assert executor.entries[old_wid] == [False] and not r.actor.calls
    target = new.cid if clash else old_point
    _, fixed = r.enter_step(selection=target)
    assert fixed.selection == target
    if clash:
        assert not any(i.selection == old_point and i.active for i in r.host.window.status().intentions)
    assert all(p == fixed_intention for p in cut.writes)
    r.finish_step(0, T); r.adopt(2)
    assert any(s.cid == old_point for s in r.facts(c.SELECTION))


@pytest.mark.parametrize("phase", ["before_write", "ack_loss"])
def test_cycle1_admission_root_stays_fixed_while_its_context_storage_is_retried(cycles, phase):
    from test_fb_stage2 import CONTEXT
    r = cycles().thinking_seats(1)
    r.direct(); r.run("candidate_generation")
    cut = FixedRecordSaveCut(r, phase, contract_ref=CONTEXT)
    try:
        try: r.host.run_until(lambda _s: cut.prepared is not None, timeout=WATCHDOG)
        except FixedRecordSaveCut.Unavailable: pass
        cut.assert_pending()
        fixed = cut.prepared
        initial_activity = evaluation_status(r)
        assert initial_activity.root == "prior" and initial_activity.root_point is None
        assert initial_activity.outcome == "running" and initial_activity.counted
        if phase == "before_write": assert isinstance(initial_activity.context, fb.Unsaved)
        else: assert initial_activity.context == fixed.cid or isinstance(initial_activity.context, fb.Unsaved)
        cut.retry_pending()
        assert cut.armed and cut.prepared == fixed
        during = evaluation_status(r, activity=initial_activity.activity)
        assert during.root == "prior" and during.root_point is None
        if phase == "before_write": assert during.context == initial_activity.context
        else: assert during.context == fixed.cid or isinstance(during.context, fb.Unsaved)
        assert all(p == fixed for p in cut.writes)
    finally: cut.restore()
    first = r.request_where("evaluation_prepare", lambda _q: True)
    assert first.value["desc"]["args"]["input"]["context"] == fixed.cid
    confirmed = activity_for_request(r, first)
    assert confirmed.activity == initial_activity.activity and confirmed.context == fixed.cid
    assert confirmed.root == "prior" and confirmed.root_point is None
    assert r.read_stored(fixed.cid)[2] == fixed.record
    # The next adoption happens only after the context's storage is restored.
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    after_adoption = activity_for_request(r, first)
    assert after_adoption.activity == initial_activity.activity and after_adoption.context == fixed.cid
    assert after_adoption.root == "prior" and after_adoption.root_point is None
    material = thinking_material_status(r)
    assert material.latest == r.adoption_chain()[-1].cid and material.handed is None
    assert material.unevaluated and material.blocked_by == (initial_activity.activity,)
    selected_first = r.finish_thought(first)
    assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
    latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    assert activity_for_request(r, latest).root_point == material.latest
    selected_latest = r.finish_thought(latest)
    assert_probability(r, selected_latest, (Q(2, 3), Q(1, 3)))
    assert r.read_stored(fixed.cid)[2] == fixed.record
    assert len(r.requests("evaluation_prepare")) == 2


def test_cycle1_separate_allocations_still_obey_the_shared_total_capacity(cycles):
    r = cycles().thinking_seats(2, execution=True)
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        capacity=fb.QuantityValue(contract=c.SEATS, value=2)))
    declaration = r.boot_input.declaration
    thinking = declaration.initial.value.allocation.value.amount.value
    execution = declaration.execution.value.allocation.value.amount.value
    assert max(thinking, execution) <= declaration.capacity.value < thinking + execution
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer})
    r.think()
    previous = {q.cid for q in r.requests("evaluation_prepare")}
    step, _body = r.offered("execute_step")  # Holds one execution seat, not yet entered.
    launch = r.launcher.launch
    def not_started_prepare(work_id, body):
        if any(q.value["desc"]["work_id"] == work_id for q in r.requests("evaluation_prepare")):
            return "not_started"
        return launch(work_id, body)
    r.launcher.launch = not_started_prepare
    try:
        r.sense(0, T, begin=True)
        assert r.passive.gates[1].entered.wait(WATCHDOG); r.running.stop()
        r.sense(1, T); r.adopt(1)
        first = r.request_where("evaluation_prepare", lambda q: q.cid not in previous)
        r.adopt(2)
        second = r.request_where("evaluation_prepare", lambda q: q.cid not in previous | {first.cid})
        assert first.value["desc"]["work_id"] not in preparer.entries
        assert second.value["desc"]["work_id"] not in preparer.entries
    finally: r.launcher.launch = launch
    ids = {q.value["desc"]["work_id"] for q in (first, second)}
    r.until(lambda: bool(ids & {key for key, _ in r.launcher.attempts}))
    offered = ids & {key for key, _ in r.launcher.attempts}
    assert len(offered) == 1
    selected = next(q for q in (first, second) if q.value["desc"]["work_id"] in offered)
    gate = preparer.hold(selected)
    r.run_request(selected, background=True); assert gate.entered.wait(WATCHDOG)
    rows = {w.work_id: w for w in r.host.window.status().works}
    assert rows[step.value["desc"]["work_id"]].held.value == 1
    assert sum(w.held.value for w in rows.values() if w.held is not None) == 2
    waiting, = ids - offered
    assert not rows[waiting].startable and rows[waiting].held is None
    assert not r.actor.calls
    gate.release.set(); assert preparer.wait_return(selected.value["desc"]["work_id"])


def test_cycle1_final_native_no_decision_closes_activity_without_rewinding_material(cycles):
    from test_fb_preparer import without_proof
    r = cycles().thinking_seats(1)
    r.registry = without_proof(r.registry)
    observer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": observer}); r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    initial_activity = activity_for_request(r, first)
    r.run_request(first)
    event, issued = next((event, issued) for event, issued in observer.posts[first.value["desc"]["work_id"]]
                         if isinstance(event, fb.WorkFinished))
    assert isinstance(event.outcome, fb.WorkOutputs)
    assert isinstance(issued.value, f.NoDecision) and issued.value.reason == "algorithm_unavailable"
    r.until(lambda: any(row.response == "no_decision" for row in r.host.window.status().readings))
    for _ in range(8): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert {q.cid for q in r.requests("evaluation_prepare")} == {first.cid}
    assert not r.requests("selection_draw") and not r.facts(c.SELECTION)
    ended = evaluation_status(r, activity=initial_activity.activity)
    assert ended.outcome == "no_decision" and not ended.counted and ended.residual == ()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    second = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    r.run_request(second)
    r.until(lambda: len([row for row in r.host.window.status().readings if row.response == "no_decision"]) == 2)
    assert len(r.requests("evaluation_prepare")) == 2
    assert not r.requests("selection_draw") and not r.facts(c.SELECTION)


def test_cycle1_execution_allocation_is_required_at_public_construction(cycles):
    r = cycles()
    value = r.boot_input.declaration.execution.value
    complete = {field.name: getattr(value, field.name) for field in fields(value)}
    assert fb.ExecutionDeclaration(**complete) == value
    assert get_type_hints(fb.ExecutionDeclaration)["allocation"] == fb.SlotValue
    missing = dict(complete); del missing["allocation"]
    with pytest.raises(TypeError): fb.ExecutionDeclaration(**missing)
    assert not r.actor.calls and r.running is None


@pytest.mark.parametrize("entry", ["direct", "start"])
@pytest.mark.parametrize("fault", ["scope", "amount", "contract"])
def test_cycle1_execution_allocation_mismatch_is_a_saved_boot_shortage(cycles, entry, fault):
    r = cycles()
    execution = r.boot_input.declaration.execution
    allocation = execution.value.allocation
    if fault == "scope":
        allocation = replace(allocation, value=replace(allocation.value, scope_slot="absent-scope"))
    elif fault == "amount":
        allocation = replace(allocation, value=replace(allocation.value,
            amount=fb.QuantityValue(contract=c.SEATS, value=r.boot_input.declaration.capacity.value + 1)))
    else:
        allocation = replace(allocation, contract=contract("test.not-allocation"))
    execution = replace(execution, value=replace(execution.value, allocation=allocation))
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration, execution=execution))
    getattr(r, entry)()  # start must save Boot, rather than raising StartInputError here.
    r.until(lambda: bool(r.facts(c.BOOT_DECLARATION)))
    boot, = r.facts(c.BOOT_DECLARATION)
    def shortages():
        return [row for row in r.host.window.status().pending if row.kind == "missing_contract"
                and row.target == boot.cid and row.contract == c.BOOT_DECLARATION
                and row.reason == "execution:allocation"]
    r.until(lambda: bool(shortages()))
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert shortages() and not r.requests("execute_step") and not r.actor.calls


@pytest.mark.parametrize("entry", ["direct", "start"])
@pytest.mark.parametrize("fault", ["old-v2", "nonempty-args", "other-contract"])
def test_cycle1_wrong_continuation_is_a_saved_boot_shortage_before_first_activity(cycles, entry, fault):
    r = cycles()
    initial = r.boot_input.declaration.initial
    method = initial.value.continuation
    if fault == "old-v2": method = replace(method, contract=replace(c.REUSE_CANDIDATES, version="2"))
    elif fault == "nonempty-args": method = replace(method, args={"extra": True})
    else: method = replace(method, contract=replace(contract("test.not-reuse"), version="3"))
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        initial=replace(initial, value=replace(initial.value, continuation=method))))
    getattr(r, entry)()  # The same saved-plan shortage is required through birth entry.
    r.until(lambda: bool(r.facts(c.BOOT_DECLARATION)))
    boot, = r.facts(c.BOOT_DECLARATION)
    r.until(lambda: any(row.kind == "missing_contract" and row.target == boot.cid
                        and row.contract == c.BOOT_DECLARATION and row.reason == "initial:continuation"
                        for row in r.host.window.status().pending))
    for _ in range(16): r.host.run_until(lambda _s: True, timeout=WATCHDOG)
    assert r.host.window.status().evaluations == ()
    assert not r.requests("candidate_generation") and not r.requests("execute_step")
    assert not r.actor.calls


@pytest.mark.parametrize("collide", [False, True], ids=["distinct-slots-control", "same-slot"])
def test_cycle1_execution_allocation_slot_must_not_alias_the_thinking_allocation(cycles, collide):
    r = cycles().thinking_seats(1, execution=True).execution_seats(0)
    declaration = r.boot_input.declaration
    thinking = declaration.initial.value.allocation
    execution = declaration.execution
    allocation = execution.value.allocation
    assert thinking.value.amount.value == 1 and allocation.value.amount.value == 0
    assert allocation.slot != thinking.slot
    if collide:
        allocation = replace(allocation, slot=thinking.slot)  # Only the declaration position changes.
        r.boot_input = replace(r.boot_input, declaration=replace(declaration,
            execution=replace(execution, value=replace(execution.value, allocation=allocation))))
    r.direct()
    r.until(lambda: bool(r.facts(c.BOOT_DECLARATION)))
    boot, = r.facts(c.BOOT_DECLARATION)
    def shortages():
        return [row for row in r.host.window.status().pending
                if row.target == boot.cid]
    if collide:
        r.until(lambda: bool(shortages()))
        for _ in range(16): r.host.window.settle()
        assert shortages() and not r.actor.calls
        assert not any(row.purpose == "execute_step" and row.startable
                       for row in r.host.window.status().works)
    else:
        selected = r.think()
        r.until(lambda: any(row.purpose == "execute_step" for row in r.host.window.status().works))
        assert not shortages()
        step, = [row for row in r.host.window.status().works if row.purpose == "execute_step"]
        assert step.phase == "pending" and not step.startable and step.held is None
        assert any(row.execution.selection == selected.cid and row.outcome == "requested"
                   for row in r.host.window.status().executions)
        assert not r.actor.calls


@pytest.mark.parametrize("ack_loss", [False, True], ids=["confirmed-control", "adoption-ack-loss"])
def test_cycle1_initial_activity_uses_the_durable_adoption_after_ack_loss_exactly_once(cycles, ack_loss):
    r = cycles().thinking_seats(2)
    generator = NativeEntryObserver(fb.CandidateGenerator())
    r.direct(worker_overrides={"candidate_generation": generator})
    qgen = r.request_where("candidate_generation", lambda _q: True)
    gate = generator.hold(qgen, timeout=3 * WATCHDOG)
    r.run_request(qgen, background=True); assert gate.entered.wait(WATCHDOG)
    initial = evaluation_status(r)
    assert initial.root == "undetermined" and initial.context is None
    r.start_last_passive(); r.complete_last_passive(T)
    if ack_loss:
        cut = FixedRecordSaveCut(r, "ack_loss", contract_ref=c.BELIEF_ADOPTED)
        try:
            r.run("belief_update")
            try: r.host.run_until(lambda _s: cut.prepared is not None, timeout=WATCHDOG)
            except FixedRecordSaveCut.Unavailable: pass
            cut.assert_pending()
            fixed = cut.prepared
            assert fixed.record.body.contract == c.BELIEF_ADOPTED
            adopted_point = fixed.cid
            cut.retry_pending()
        finally: cut.restore()
        # No host drive between storage recovery and finishing Wg: o must see A itself.
    else:
        adopted, = r.adopt(1)
        adopted_point = adopted.cid
    gate.release.set(); assert generator.wait_return(qgen.value["desc"]["work_id"])
    first = r.request_where("evaluation_prepare", lambda _q: True)
    activity = activity_for_request(r, first)
    assert activity.activity == initial.activity and activity.root == "adopted"
    assert activity.root_point == adopted_point
    material = thinking_material_status(r)
    assert material.latest == material.handed == adopted_point and not material.unevaluated
    selected = r.finish_thought(first)
    assert_probability(r, selected, (Q(2, 3), Q(1, 3)))
    r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
    for _ in range(16): r.host.window.settle()
    assert {row.activity for row in r.host.window.status().evaluations} == {initial.activity}
    assert len(r.requests("evaluation_prepare")) == 1
    assert len(r.facts(c.SELECTION)) == 1
    assert [adopted.cid for adopted in r.adoption_chain()] == [adopted_point]
    if ack_loss:
        assert r.read_stored(adopted_point)[2] == fixed.record
        assert all(prepared == fixed for prepared in cut.writes)


@pytest.mark.parametrize("clash", [False, True], ids=["identical-terminal-control", "unusable-latest-root"])
def test_cycle1_conflicted_latest_adoption_does_not_create_an_evaluation_activity(cycles, clash):
    r = cycles().thinking_seats(1)
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    updater = NativeEntryObserver(fb.FiniteUpdater(registry=r.registry))
    r.direct(worker_overrides={"evaluation_prepare": preparer, "belief_update": updater})
    r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    gate = preparer.hold(first, timeout=3 * WATCHDOG)
    r.run_request(first, background=True); assert gate.entered.wait(WATCHDOG)
    initial = activity_for_request(r, first)
    assert initial.root == "prior" and initial.root_point is None
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    adopted, = r.adoption_chain()
    update = updater.request(r, "belief_update")
    updater.late_terminal(update, clash=clash)
    wid = update.value["desc"]["work_id"]
    r.until(lambda: len([report for report in r.facts(c.WORK_REPORT)
                         if report.value["work"] == wid]) == 2)
    if clash:
        r.until(lambda: bool(r.facts(c.CONFLICT)) or
                any(row.kind == "conflict" for row in r.host.window.status().pending))
    gate.release.set(); assert preparer.wait_return(first.value["desc"]["work_id"])
    selected_first = r.finish_thought(first)
    assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
    # Release of the old activity is essential: a busy seat must not hide the bad root.
    r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
    if clash:
        for _ in range(16): r.host.window.settle()
        assert {row.activity for row in r.host.window.status().evaluations} == {initial.activity}
        assert {request.cid for request in r.requests("evaluation_prepare")} == {first.cid}
        assert {selected.cid for selected in r.facts(c.SELECTION)} == {selected_first.cid}
    else:
        latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
        assert activity_for_request(r, latest).root_point == adopted.cid
        selected_latest = r.finish_thought(latest)
        assert_probability(r, selected_latest, (Q(2, 3), Q(1, 3)))
        assert len(r.host.window.status().evaluations) == len(r.requests("evaluation_prepare")) == 2
        assert not r.facts(c.CONFLICT)
    assert adopted.cid in {record.cid for record in r.facts(c.BELIEF_ADOPTED)}


@pytest.mark.parametrize("seats", [0, 1], ids=["zero-thinking", "one-seat-control"])
def test_cycle1_zero_thinking_allocation_never_admits_even_the_initial_activity(cycles, seats):
    r = cycles().thinking_seats(seats)
    # Keep global capacity identical and sufficient; only the thinking amount varies.
    r.boot_input = replace(r.boot_input, declaration=replace(r.boot_input.declaration,
        capacity=fb.QuantityValue(contract=c.SEATS, value=4)))
    r.direct()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    boot, = r.facts(c.BOOT_DECLARATION)
    assert not any(row.target == boot.cid and row.contract == c.BOOT_DECLARATION
                   for row in r.host.window.status().pending)
    if seats == 0:
        for _ in range(16): r.host.window.settle()
        assert r.host.window.status().evaluations == ()
        assert not r.requests("candidate_generation") and not r.requests("evaluation_prepare")
        assert not r.facts(c.SELECTION)
    else:
        selected = r.think()
        assert_probability(r, selected, (Q(2, 3), Q(1, 3)))
        activity = evaluation_status(r)
        assert activity.root == "adopted" and activity.root_point == r.adoption_chain()[0].cid
        assert len(r.requests("candidate_generation")) == len(r.requests("evaluation_prepare")) == 1


def test_cycle1_thinking_root_and_latest_follow_the_decided_adoption_chain(cycles):
    prior = (Q(1, 4), Q(3, 4))
    r = cycles(prior=prior, passive=N, passive_empty=ZERO,
               same_target=True, overlap="serializable").thinking_seats(1, execution=True)
    evaluator = NativeEntryObserver(fb.Evaluator())
    executor = NativeEntryObserver(fb.StepExecutor())
    r.direct(worker_overrides={"evaluation": evaluator, "execute_step": executor})
    for stage in ORDER[:-1]: r.run(stage)
    first = r.request_where("evaluation_prepare", lambda _q: True)
    first_activity = activity_for_request(r, first)
    evaluation, evaluation_body = r.offered("evaluation")
    evaluation_id = evaluation.value["desc"]["work_id"]
    residual = evaluator.hold_post(evaluation, timeout=3 * WATCHDOG)
    r.invoke(evaluation, evaluation_body, background=True); assert residual.entered.wait(WATCHDOG)
    r.until(lambda: len(r.facts(c.SELECTION)) == 1)
    original, = r.facts(c.SELECTION)
    assert_declared_one_step_probabilities(r, original, prior)
    held = evaluation_status(r, activity=first_activity.activity)
    assert held.root == "prior" and held.outcome == "selected"
    assert held.counted and held.residual == (evaluation_id,)
    step, step_body = r.offered("execute_step")
    measurement, measurement_body = r.offered("measure_segment")
    step_id = step.value["desc"]["work_id"]
    r.invoke(step, step_body, background=True); assert r.actor.gates[0].entered.wait(WATCHDOG)
    assert r.actor.calls[0].selection == original.cid
    # Do not drive/accept/settle until both native workers have published their reports.
    r.actor.symbols[0] = T; r.actor.gates[0].release.set()
    assert executor.wait_return(step_id)
    r.advance(1)
    r.invoke(measurement, measurement_body, background=True)
    measurement_thread = r.threads[-1]
    assert r.passive.gates[0].entered.wait(WATCHDOG)
    r.running.stop()
    r.passive.symbols[0] = T; r.passive.gates[0].release.set()
    measurement_thread.join(WATCHDOG); assert not measurement_thread.is_alive()
    assert len(r.actor.calls) == len(r.passive.calls) == 1
    assert not r.facts(c.BELIEF_ADOPTED)
    chain = r.adopt(2)
    first_adoption, latest_adoption = chain
    assert first_adoption.value["previous"] is None
    assert latest_adoption.value["previous"] == first_adoption.cid
    execution, = [row for row in r.host.window.status().executions if row.execution == r.actor.calls[0]]
    assert execution.result is not None and execution.source_called is True
    result_record = r.read_stored(execution.result)[2]
    assert result_record.body.contract == contract("sui.fb.execution_result")
    result = result_record.body.content.as_json()
    assert result["execution"] == wire(r.actor.calls[0]) and result["value"] == read1_symbol(T)
    frame, = r.frame_reports()
    interval = frame.value["item"]["value"]["measurement_interval"]
    assert r.actor.returned_ns[0] < interval["start_ns"]
    for index, matrices in enumerate(((P,), (P, N))):
        joint, mass = enumerate_updates(matrices, prior)
        assert r.answer(index) == {"joint": wire(joint), "evidence_mass": wire(mass)}
    material = thinking_material_status(r)
    assert material.latest == latest_adoption.cid and material.handed is None
    assert material.unevaluated and material.blocked_by == (first_activity.activity,)
    assert {row.activity for row in r.host.window.status().evaluations} == {first_activity.activity}
    residual.release.set(); assert evaluator.wait_return(evaluation_id)
    latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    activity = activity_for_request(r, latest)
    assert activity.root == "adopted" and activity.root_point == chain[-1].cid
    material = thinking_material_status(r)
    assert material.latest == material.handed == activity.root_point and not material.unevaluated
    selected = r.finish_thought(latest)
    joint, _mass = enumerate_updates((P, N), prior)
    assert_declared_one_step_probabilities(r, selected, joint)
    assert r.selected_value(selected).root.K.belief == r.read_stored(latest_adoption.value["result"])[2].id
    r.until(lambda: any(row.selection == selected.cid and row.active
                        for row in r.host.window.status().intentions))
    assert not any(row.selection == original.cid and row.active
                   for row in r.host.window.status().intentions)
    r.until(lambda: not evaluation_status(r, activity=activity.activity).counted)
    for _ in range(16): r.host.window.settle()
    roots = [row.root_point for row in r.host.window.status().evaluations if row.root == "adopted"]
    assert roots == [chain[-1].cid] and len(roots) == len(set(roots))
    assert len(r.host.window.status().evaluations) == len(r.requests("evaluation_prepare")) == 2
    assert thinking_material_status(r).latest == r.adoption_chain()[-1].cid


@pytest.mark.parametrize("clash", [False, True], ids=["identical-Wg-terminal-control", "conflicted-reused-candidates"])
def test_cycle1_conflicted_candidate_generation_does_not_admit_reuse_activities(cycles, clash):
    r = cycles().thinking_seats(1)
    generator = NativeEntryObserver(fb.CandidateGenerator())
    preparer = NativeEntryObserver(fb.EvaluationPreparer(registry=r.registry))
    r.direct(worker_overrides={"candidate_generation": generator, "evaluation_prepare": preparer})
    r.run("candidate_generation")
    generation = generator.request(r, "candidate_generation")
    first, first_body = r.offered("evaluation_prepare")
    wid = first.value["desc"]["work_id"]
    initial = activity_for_request(r, first)
    assert initial.root == "prior" and initial.counted and wid in initial.residual
    assert wid not in preparer.entries
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    adopted, = r.adoption_chain()
    assert {row.activity for row in r.host.window.status().evaluations} == {initial.activity}
    generator.late_terminal(generation, clash=clash)
    generation_id = generation.value["desc"]["work_id"]
    r.until(lambda: len([report for report in r.facts(c.WORK_REPORT)
                         if report.value["work"] == generation_id]) == 2)
    if clash:
        r.until(lambda: bool(r.facts(c.CONFLICT)) or
                any(row.kind == "conflict" for row in r.host.window.status().pending))
    r.invoke(first, first_body)
    assert preparer.entries[wid] == [not clash]
    if clash:
        r.until(lambda: any(row.work_id == wid and row.held is None
                           for row in r.host.window.status().works))
        r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
        ended = evaluation_status(r, activity=initial.activity)
        assert ended.outcome == "conflict" and ended.residual == ()
        for _ in range(16): r.host.window.settle()
        assert {row.activity for row in r.host.window.status().evaluations} == {initial.activity}
        assert {request.cid for request in r.requests("evaluation_prepare")} == {first.cid}
        assert not r.requests("selection_draw") and not r.requests("evaluation")
        assert not r.facts(c.SELECTION)
    else:
        selected_first = r.finish_thought(first)
        assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
        r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
        latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
        assert activity_for_request(r, latest).root_point == adopted.cid
        selected_latest = r.finish_thought(latest)
        assert_probability(r, selected_latest, (Q(2, 3), Q(1, 3)))
        assert len(r.host.window.status().evaluations) == 2
        assert not r.facts(c.CONFLICT)
    assert [record.cid for record in r.adoption_chain()] == [adopted.cid]
    assert len(r.requests("candidate_generation")) == 1


@pytest.mark.parametrize("wrong_family", [False, True], ids=["DrawReturned-control", "WorkFinished-only"])
def test_cycle1_draw_with_only_wrong_family_notice_stops_and_releases_activity(cycles, wrong_family):
    r = cycles().thinking_seats(1)
    draws = ActivityTerminalObserver(fb.UniformDraw(randbits=r.randbits),
        "wrong_draw_terminal" if wrong_family else "native")
    r.direct(worker_overrides={"selection_draw": draws})
    r.run("candidate_generation")
    first = r.request_where("evaluation_prepare", lambda _q: True)
    initial = activity_for_request(r, first)
    assert initial.root == "prior"
    r.run_request(first)
    draw = r.draw_for(first)
    wid = draw.value["desc"]["work_id"]
    before_post = draws.hold_before_post(draw, timeout=3 * WATCHDOG)
    r.run_request(draw, background=True); assert before_post.entered.wait(WATCHDOG)
    assert draws.entries[wid] == [True] and not draws.returned[wid].is_set()
    r.start_last_passive(); r.complete_last_passive(T); r.adopt(1)
    adopted, = r.adoption_chain()
    held = evaluation_status(r, activity=initial.activity)
    assert held.outcome == "running" and held.counted and wid in held.residual
    assert {row.activity for row in r.host.window.status().evaluations} == {initial.activity}
    before_post.release.set(); assert draws.wait_return(wid)
    sent, = [event for event, _issued in draws.posts[wid]
             if isinstance(event, (fb.WorkFinished, fb.DrawReturned))]
    assert isinstance(sent, fb.WorkFinished if wrong_family else fb.DrawReturned)
    raw_contract = c.WORK_REPORT if wrong_family else c.DRAW_REPORT
    r.until(lambda: len([report for report in r.facts(raw_contract) if report.value["work"] == wid]) == 1)
    r.until(lambda: any(row.work_id == wid and row.stop_confirmed and row.held is None
                       for row in r.host.window.status().works))
    if wrong_family:
        r.until(lambda: evaluation_status(r, activity=initial.activity).outcome == "stopped"
                        and not evaluation_status(r, activity=initial.activity).counted)
        ended = evaluation_status(r, activity=initial.activity)
        assert ended.residual == ()
        assert not [terminal for terminal in r.facts(c.WORK_TERMINAL) if terminal.value["work"] == wid]
        assert not r.facts(c.DRAW_REPORT) and not r.facts(contract("sui.f.draw_fact"))
        assert not r.requests("evaluation") and not r.facts(c.SELECTION)
    else:
        running = evaluation_status(r, activity=initial.activity)
        assert running.outcome == "running" and running.counted
        assert any(terminal.value["work"] == wid and terminal.value["terminal_kind"] == "value"
                   for terminal in r.facts(c.WORK_TERMINAL))
        selected_first = r.finish_thought(first)
        assert_probability(r, selected_first, (Q(1, 2), Q(1, 2)))
        r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
        assert evaluation_status(r, activity=initial.activity).outcome == "selected"
    draws.mode = "native"
    latest = r.request_where("evaluation_prepare", lambda q: q.cid != first.cid)
    activity = activity_for_request(r, latest)
    assert activity.activity != initial.activity and activity.root == "adopted"
    assert activity.root_point == adopted.cid
    selected_latest = r.finish_thought(latest)
    assert_probability(r, selected_latest, (Q(2, 3), Q(1, 3)))
    assert len(r.facts(c.SELECTION)) == (1 if wrong_family else 2)
    assert len(r.host.window.status().evaluations) == len(r.requests("evaluation_prepare")) == 2
    assert [record.cid for record in r.adoption_chain()] == [adopted.cid]


def test_cycle1_before_write_adoption_never_becomes_a_root_until_saved(cycles):
    r = cycles().thinking_seats(1).direct()
    original = r.think()
    initial = evaluation_status(r)
    r.until(lambda: not evaluation_status(r, activity=initial.activity).counted)
    ended = evaluation_status(r, activity=initial.activity)
    assert ended.root == "prior" and ended.outcome == "selected" and ended.residual == ()
    old_requests = {request.cid for request in r.requests("evaluation_prepare")}
    assert len(old_requests) == 1
    r.start_last_passive(); r.complete_last_passive(T)
    cut = FixedRecordSaveCut(r, "before_write", contract_ref=c.BELIEF_ADOPTED)
    try:
        r.run("belief_update")
        try: r.host.run_until(lambda _state: cut.prepared is not None, timeout=WATCHDOG)
        except FixedRecordSaveCut.Unavailable: pass
        cut.assert_pending()
        fixed = cut.prepared
        assert fixed.record.body.contract == c.BELIEF_ADOPTED
        for _ in range(2):
            assert fixed.cid not in dict(r.entry_store.load())  # Unlike ack_loss, A is not durable.
            assert not r.facts(c.BELIEF_ADOPTED)
            state = r.host.window.status()
            assert {row.activity for row in state.evaluations} == {initial.activity}
            assert not any(row.root_point == fixed.cid for row in state.evaluations)
            material = thinking_material_status(r)
            assert material.latest is None and material.handed is None
            assert {request.cid for request in r.requests("evaluation_prepare")} == old_requests
            cut.retry_pending()
        # Include the snapshot after the last failed retry, before restoring storage.
        assert not any(row.root_point == fixed.cid for row in r.host.window.status().evaluations)
        assert thinking_material_status(r).latest is None
        assert fixed.cid not in dict(r.entry_store.load())
        assert all(prepared == fixed for prepared in cut.writes)
    finally: cut.restore()
    latest = r.request_where("evaluation_prepare", lambda request: request.cid not in old_requests)
    adopted, = r.adoption_chain()
    assert adopted.cid == fixed.cid and r.read_stored(adopted.cid)[2] == fixed.record
    r.assert_answer((P,))
    activity = activity_for_request(r, latest)
    assert activity.activity != initial.activity and activity.root == "adopted"
    assert activity.root_point == fixed.cid
    material = thinking_material_status(r)
    assert material.latest == material.handed == fixed.cid and not material.unevaluated
    selected = r.finish_thought(latest)
    assert_probability(r, selected, (Q(2, 3), Q(1, 3)))
    r.until(lambda: not evaluation_status(r, activity=activity.activity).counted)
    for _ in range(16): r.host.window.settle()
    roots = [row.root_point for row in r.host.window.status().evaluations if row.root == "adopted"]
    assert roots == [fixed.cid]
    assert len(r.host.window.status().evaluations) == len(r.requests("evaluation_prepare")) == 2
    assert {selection.cid for selection in r.facts(c.SELECTION)} == {original.cid, selected.cid}
    assert [record.cid for record in r.adoption_chain()] == [fixed.cid]
    assert all(prepared == fixed for prepared in cut.writes)

