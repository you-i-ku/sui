"""F-b stage 2, paper v0.26, independent facts-only black-box tests.

Read boundary: public DTOs/signatures, the two current papers, and permitted
test fixtures. No private F-b/F-a implementation is imported or inspected.
The real host, ledger, contents and entries are exercised; the test owns only
workers, the launch cut, and storage fault injection. FStatus is never an oracle.
Timeouts mean incomplete observations, never a product timing guarantee.

Discrimination: each negative starts with a legal declaration and changes one
field. Ignoring that field would wrongly create the specifically named child.
No mutation of production code has been performed. C6/C7/C9's update arithmetic
and adoption belong to stage 3 (paper:3245,3283-3287); this file does not claim
to close those conditions. C1/C2/C3/C4/C5/C8/C10/C11 apply here to generation,
fixed numerical inputs, issued outputs, and selection, not belief adoption.
"""

from collections import Counter
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
import json
from threading import Event, Thread

import pytest

from sui import f, fb, fb_contracts as c, f_facts as ff
from sui.contracts import ContractRef
from sui.ids import RefKind
from sui.ledger import entry_from_header
from sui.rate import RateBudget
from sui.records import Decided, Observed, Payload, Prediction, Role, Category

from gate_f_facts_cases import FactsCase, finite_world, plain, prepare, add_draw
from test_fb_skeleton import boot, contract, source
from test_fb_stage1 import RealRig, ObservedLedger, TestClock, wire, received


PAPER = "specs/関所F_Fb_今の約束.md"
CG = contract("sui.f.candidate_declaration")
MATH = ContractRef("sui.f.math_artifact", "2")
DF = contract("sui.f.draw_fact")
CONTEXT = contract("sui.f.context_observed")
CLOCK = contract("sui.f.clock_reading")
CLOCK_SOURCE = contract("sui.clock.source")
BOOT = contract("sui.s4.boot")
ORIGIN = contract("sui.f.knowledge_origin")
METHOD = contract("sui.f.finite_evaluation")
GENERATOR = c.MODEL_OPERATIONS
DRAW_GENERATOR = contract("stage2.scripted_draw")
PREPARE_BUDGET = RateBudget(Fraction(1, 10**18), 4096, 4096, 32)
EVALUATE_BUDGET = RateBudget(Fraction(1, 10**17), 8192, 8192, 40)
TINY_BUDGET = RateBudget(Fraction(1, 10**18), 4096, 1, 1)
REQUESTS = {
    "candidate_generation": c.CANDIDATE_REQUEST,
    "evaluation_prepare": c.EVALUATION_REQUESTED,
    "selection_draw": c.DRAW_REQUESTED,
    "evaluation": c.WORK_REQUESTED,
    "measure_segment": c.SEGMENT_REQUESTED,
}
ORDER = ("candidate_generation", "evaluation_prepare", "selection_draw", "evaluation")
TERMINAL_FIELDS = {"work", "request", "stage", "first_receipt", "terminal_kind",
                   "returned", "basis", "view"}


def canonical(value):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class ModelOperations:
    """H9 / F-a:136,138: preserve CandidateInput, including its actions."""

    def __call__(self, *, args, input, context):
        assert plain(args) == {}
        assert set(input) == {"actions", "basis", "draws"}
        # No independent candidate list is supplied by the test capability.
        return input


class ExecutionMarker:
    """Explicit test execution declaration; its actual body is FWorkers.run."""

    def __call__(self, *, args, input, context):
        raise AssertionError("stage-2 execution belongs to the worker, not the window")


def registry(*, omit_implementation=None):
    """Paper:3432; retain every builtin declaration/identity in a new registry."""
    from test_fb_skeleton import test_registry as stage1_registry
    old, fixture = f.builtin_f_registry(), stage1_registry()
    declarations = list(old.declarations) + list(fixture.declarations)
    implementations = list(old.implementations) + list(fixture.implementations)
    generator_schema = contract("sui.f.schema.candidate_input")
    for kind, ref, input_contract, output_contract, callback in (
        ("generator", GENERATOR, generator_schema, generator_schema, ModelOperations()),
        ("method", c.EVALUATION_PREPARE, c.EVALUATION_REQUESTED, MATH, ExecutionMarker()),
        ("method", c.EVALUATE_FROM_DRAW, c.WORK_REQUESTED, MATH, ExecutionMarker()),
        ("generator", DRAW_GENERATOR, c.DRAW_REQUESTED, c.DRAW_REPORT, ExecutionMarker()),
    ):
        declarations.append(f.CapabilityDeclaration(kind=kind, ref=ref,
            args_contract=contract("sui.f.args.empty"), input_contract=input_contract,
            output_contract=output_contract, dependencies=(), conditions=()))
        implementations.append(f.CapabilityImplementation(kind=kind, ref=ref,
            implementation=callback, identity="sui.tests.fb.stage2/1:" + ref.name))
    if omit_implementation is not None:
        implementations = [i for i in implementations if i.ref != omit_implementation]
    return f.make_f_registry(declarations=tuple(declarations), implementations=tuple(implementations))


class LaunchCut:
    """The host claims starts; the test explicitly runs the supplied OS body."""

    def __init__(self):
        self.attempts = []

    def launch(self, work_id, body):
        self.attempts.append((work_id, body))
        return "launched"


class ReadWitnessClock(TestClock):
    """Distinct actual M reads and save stamps; using s as j is detectable."""

    def __init__(self):
        super().__init__()
        self.reads = []

    def mono_ns(self):
        with self.lock:
            value = self.inner.mono_ns()
            self.inner.advance(10)
            self.reads.append(value)
            return value

    def now(self):
        with self.lock:
            self.inner.advance(10)
            return self.inner.now()


class Stage2Ledger(ObservedLedger):
    """Observe public prepare/write, with a one-shot per-contract cut."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cut = None
        self.store_cut = None
        self.store_cut_hits = []
        self.hit = []
        self.writes = []

    def write(self, prepared):
        self.writes.append(prepared)
        ref = prepared.record.body.contract
        if self.store_cut is not None and ref == self.store_cut[0]:
            target, boundary = self.store_cut
            self.store_cut = None
            self.store_cut_hits.append((target, boundary, prepared))
            assert self.faults.armed is None
            self.faults.armed = boundary
        if self.cut == (ref, "before"):
            self.cut = None
            self.hit.append((ref, "before", prepared))
            raise OSError("stage2 before write")
        result = super().write(prepared)
        if self.cut == (ref, "after"):
            self.cut = None
            self.hit.append((ref, "after", prepared))
            raise OSError("stage2 after committed write")
        return result


class Workers:
    """Actual test worker entry/post/return witnesses, independent of status."""

    def __init__(self, rig):
        self.rig = rig
        self.entries = []
        self.entry_attempts = []
        self.stops = []
        self.sent = []
        self.issued = {}
        self.inputs = {}
        self.contexts = {}
        self.overrides = {}
        self.gates = {}
        self.entered = {}
        self.errors = []
        self.threads = []

    def run(self, work, ctx):
        entered = ctx.enter()
        self.entry_attempts.append((work.desc.work_id, entered))
        if not entered:
            return
        stage = work.desc.purpose
        self.entries.append(work)
        self.contexts[stage] = ctx
        self.entered.setdefault(stage, Event()).set()
        try:
            gate = self.gates.get(stage)
            if gate is not None and not gate.wait(10):
                raise AssertionError("incomplete observation: worker gate was not released")
            action = self.overrides.get(stage)
            if action is None:
                event, issued = self.normal(work, ctx)
                if event is not None:
                    self.post(ctx, event, issued)
            else:
                action(work, ctx)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            self.stops.append(work.desc.work_id)

    def post(self, ctx, event, issued=None):
        self.sent.append((event, issued))
        ctx.post(event, issued=issued)

    def finished(self, work, outcome):
        reading = self.rig.actual_reading()
        return fb.WorkFinished(work=work.desc.work_id, started=reading, finished=reading,
                               outcome=outcome)

    def candidate(self, work):
        args = work.desc.args
        # Read the saved model. Its order, not finite_world's returned actions,
        # is the source of the candidates (H9).
        model = self.rig.read_stored(args.model)[2].body.content.as_json()["document"]
        order = tuple(op["id"] for op in model["operations"])
        return f.FCandidateDeclaration(model=args.model, input_order=order,
            measure=f.CandidateMeasureRef(name="counting", version="1", args={}),
            generation=f.FCandidateGeneration(generator=work.desc.method,
                args=args.generator_args, basis=args.basis, draws=()),
            continuation=f.FContinuation(after=tuple(
                f.ContinuationAfter(candidate=name, policy=None) for name in order)))

    def prepare(self, work, ctx, *, budget=None, request=None):
        reader = ctx.reader()
        assert reader is not None, "H5: Ep must receive the frozen reader"
        assert ctx.prepared() is None, "H5: only Ee receives the Ep issue"
        a = work.desc.args
        request = a.input if request is None else request
        self.inputs[work.desc.purpose] = (work.desc, reader)
        return ff.prepare_f_from_facts(reader, fixed_parents=request.fixed_parents,
            model_ref=request.model, candidate_ref=request.candidates,
            preference_refs=request.preferences, scope_request=request.scope,
            context_ref=request.context, registry=self.rig.registry,
            method=request.method, budget=a.budget if budget is None else budget)

    def evaluate(self, work, ctx, *, prepared=None, budget=None):
        reader, actual = ctx.reader(), ctx.prepared()
        assert reader is not None and actual is not None, "H5: Ee needs reader and Ep issue"
        pr = self.rig.one(c.PREPARED)
        assert pr.cid == work.desc.args.prepared
        assert self.rig.one(MATH, cid=pr.value["artifact"]).value == json.loads(actual.canonical_bytes)
        self.inputs[work.desc.purpose] = (work.desc, reader)
        return ff.evaluate_f_from_draw(actual if prepared is None else prepared,
            work.desc.args.draw, reader=reader,
            budget=work.desc.args.budget if budget is None else budget)

    def normal(self, work, ctx):
        stage = work.desc.purpose
        if stage == "measure_segment":
            return None, None
        if stage == "candidate_generation":
            assert ctx.prepared() is None
            candidate = self.candidate(work)
            value = ({"kind": "candidates", "value": plain(candidate)} if candidate.input_order
                     else {"kind": "no_candidates", "value": {}})
            return self.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
                contract=c.CANDIDATE_GENERATION, value=value))), None
        if stage == "selection_draw":
            assert ctx.prepared() is None
            # A scripted test value, not a claim of continuous uniform sampling.
            return fb.DrawReturned(work=work.desc.work_id,
                outcome=fb.DrawValue(value={"u": [1, 4]})), None
        if stage == "evaluation_prepare":
            artifact = self.prepare(work, ctx)
        elif stage == "evaluation":
            artifact = self.evaluate(work, ctx)
        else:
            raise AssertionError("unexpected stage: " + stage)
        self.issued[stage] = artifact
        return self.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=MATH, value=json.loads(artifact.canonical_bytes)))), artifact


class Stage2Rig(RealRig):
    def __init__(self, *, empty=False, prepare_budget=PREPARE_BUDGET,
                 evaluate_budget=EVALUATE_BUDGET, omit_implementation=None, ticking=False,
                 reverse_operations=False, auto_boot=True):
        super().__init__(connect=False)
        if ticking:
            self.clock = ReadWitnessClock()
        self.ledger = Stage2Ledger(contents=self.contents, entries=self.entry_store, faults=self.faults)
        self.prepare_observations = self.ledger.preparations
        self.registry = registry(omit_implementation=omit_implementation)
        self.launcher = LaunchCut()
        self.workers = Workers(self)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
                                  registry=self.registry, launcher=self.launcher)
        self.document, _ = finite_world("FA01")
        if reverse_operations:
            self.document["operations"].reverse()
        if empty:
            self.document["operations"] = []
        record = self.record(Prediction(target="model.11", about=(), basis=(),
            content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(record, ()).cid
        event = boot(True)
        initial = replace(event.declaration.initial.value, model=self.model_point,
            generator=fb.MethodCall(contract=GENERATOR, args={}),
            method=fb.MethodCall(contract=METHOD, args={}),
            draw=fb.MethodCall(contract=DRAW_GENERATOR, args={}),
            prepare_budget=prepare_budget, evaluate_budget=evaluate_budget)
        self.boot_input = replace(event, declaration=replace(event.declaration,
            initial=replace(event.declaration.initial, value=initial),
            routes=tuple(replace(route, value=replace(route.value,
                config=replace(route.value.config,
                    sampling_contract=contract("sui.f.finite_measurement"),
                    clock_contract=contract("sui.f.simulated_clock"))))
                for route in event.declaration.routes),
            environment=replace(event.declaration.environment, value=fb.Environment(
                data={"fixture": "stage2", "preference": "must not become a preference"}))))
        self.clock_event = fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock")))
        if auto_boot:
            self.host.post(self.clock_event)
            self.host.post(self.boot_input)
            self.drive(lambda: bool(self.facts(c.CANDIDATE_REQUEST)))

    def one(self, wanted, *, cid=None):
        facts = [fact for fact in self.facts(wanted) if cid is None or fact.cid == cid]
        assert len(facts) == 1, (wanted, [fact.cid for fact in facts])
        return facts[0]

    def drive(self, predicate):
        # The lambda intentionally ignores FStatus. Evidence is in actual C/E
        # or the test's independent launch/entry/return witness.
        self.host.run_until(lambda _status: predicate(), timeout=2)
        if self.workers.errors:
            raise self.workers.errors[0]
        assert predicate(), "incomplete observation: required public transition was not reached"

    def request(self, stage):
        return self.one(REQUESTS[stage])

    def callback(self, stage):
        self.drive(lambda: bool(self.facts(REQUESTS[stage])) and any(
            work_id == self.request(stage).value["desc"]["work_id"]
            for work_id, _ in self.launcher.attempts))
        work_id = self.request(stage).value["desc"]["work_id"]
        callbacks = [body for key, body in self.launcher.attempts if key == work_id]
        assert len(callbacks) == 1, "INV-3/14: a work was launched twice"
        return callbacks[0]

    def run_stage(self, stage, *, raw_contract=None):
        self.callback(stage)()
        if self.workers.errors:
            raise self.workers.errors[0]
        if raw_contract is None:
            raw_contract = c.DRAW_REPORT if stage == "selection_draw" else c.WORK_REPORT
        work_id = self.request(stage).value["desc"]["work_id"]
        self.drive(lambda: any(fact.value["work"] == work_id for fact in self.facts(raw_contract)))
        self.settle_steps()
        return next(work for work in self.workers.entries if work.desc.work_id == work_id)

    def through(self, stage):
        for current in ORDER[:ORDER.index(stage) + 1]:
            self.run_stage(current)

    def settle_steps(self):
        # Bounded safety observation after the triggering facts were saved.
        # A missing mandatory positive successor is separately required below.
        for _ in range(32):
            self.host.window.settle()

    def background(self, stage):
        body = self.callback(stage)
        def run():
            try:
                body()
            except BaseException:
                pass  # run() records the exception in workers.errors
        thread = Thread(target=run, daemon=True)
        self.workers.threads.append(thread)
        thread.start()
        assert self.workers.entered.setdefault(stage, Event()).wait(2), "worker did not enter"

    def close(self):
        for gate in self.workers.gates.values():
            gate.set()
        for thread in self.workers.threads:
            thread.join(2)
            assert not thread.is_alive(), "test worker did not stop"


@pytest.fixture
def make_rig():
    rigs = []
    def make(**kwargs):
        rig = Stage2Rig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def closure(rig, points):
    """Independently walk saved headers, including the supplied boundary."""
    result, pending = set(), list(points)
    while pending:
        cid = pending.pop()
        if cid in result:
            continue
        result.add(cid)
        header = rig.read_stored(cid)[0]
        pending.extend(entry_from_header(cid, header).parents)
    return result


def front(rig, points):
    points = set(points)
    return points - set().union(*(closure(rig, (p,)) - {p} for p in points)) if points else set()


def events_for(rig, points):
    """Paper:2059: expand P using actual parents and declared basis, never use P as parent."""
    result = set()
    for cid in points:
        header, _, record = rig.read_stored(cid)
        if isinstance(record.body, Prediction):
            basis_ids = set(record.body.basis)
            basis = [point for point, _ in rig.entry_store.load()
                     if rig.read_stored(point)[2].id in basis_ids]
            result.update(events_for(rig, entry_from_header(cid, header).parents | set(basis)))
        else:
            result.add(cid)
    return result


def assert_parents(rig, fact, points, *, reduce=True):
    expected = front(rig, points) if reduce else set(points)
    assert set(fact.parents) == expected, (fact.contract, fact.parents, expected)
    for cid in fact.parents:
        assert not isinstance(rig.read_stored(cid)[2].body, Prediction)


def captured_reader_key(rig, reader):
    """F-a:28,454,458,470: independently encode the actual worker's captured reader.

    Ee additionally reads DF and its closure. That captured reader's key need
    not equal the unchanged numerical_view key that identifies the original Xnum.
    All entries in these fixtures have bodies; no missing-body rows are invented.
    """
    rows = []
    for entry in sorted(reader.entries(), key=lambda item: item.cid):
        header, salt, record = rig.read_stored(entry.cid)
        assert reader.record(entry.cid) == record
        captured_salt, payload = reader.sealed_content(entry.cid)
        assert captured_salt == salt and payload == record.body.content
        value = wire(record)
        value["body"] = {"type": type(record.body).__name__, "value": wire(record.body)}
        rows.append({"point": entry.cid, "header_hex": header.hex(), "body_present": True,
            "salt_hex": salt.hex(), "payload_media_type": payload.media_type,
            "payload_hex": payload.data.hex(), "record_hex": canonical(value).hex()})
    return "sha256:" + sha256(canonical({"domain": "sui.f.reader_view/1", "entries": rows})).hexdigest()


def assert_k1_source_for_notice(rig, notice):
    """Paper:3442: match each published source to its actual notice and Boot."""
    boot_fact = rig.one(BOOT)
    expected_parents = front(rig, (boot_fact.cid, notice.cid))
    matches = [fact for fact in rig.facts(CLOCK_SOURCE) if set(fact.parents) == expected_parents]
    assert len(matches) == 1, "K1 requires one issued source for this saved notice"
    published = matches[0]
    assert published.value == notice.value
    assert published.value["run"] == str(rig.clock.run)
    assert_parents(rig, published, (boot_fact.cid, notice.cid))
    assert notice.parents == frozenset()
    notice_record = rig.read_stored(notice.cid)[2]
    source_record = rig.read_stored(published.cid)[2]
    assert isinstance(notice_record.body, Observed) and notice_record.body.route == "fb"
    assert isinstance(source_record.body, Observed) and source_record.body.route == "membrane"
    assert notice_record.writer == source_record.writer == Role.MEMBRANE
    assert notice_record.category == source_record.category == Category.FACT
    assert rig.read_stored(boot_fact.cid)[2].body.route == "membrane"
    assert published.received_ns >= max(boot_fact.at_ns, notice.at_ns)
    assert published.received_ns > max(boot_fact.received_ns, notice.received_ns)
    assert published.received_ns < published.at_ns  # ticking M distinguishes r from s
    assert all(fact.parents for fact in rig.facts(CLOCK_SOURCE)), "K1 forbids parentless raw sources"
    return published


def assert_ep_is_prepared_from_k1_source(rig, source_points):
    """F-a math issuance witnesses the host's clock provenance, not only its display."""
    rig.drive(lambda: bool(rig.facts(c.CANDIDATE_REQUEST)))
    rig.through("evaluation_prepare")
    artifact = rig.workers.issued["evaluation_prepare"]
    assert isinstance(artifact.value, f.FProblem)
    pr = rig.one(c.PREPARED)
    assert rig.one(MATH, cid=pr.value["artifact"]).value == json.loads(artifact.canonical_bytes)
    context = rig.one(CONTEXT)
    for field in ("observation_reading", "judgment_reading"):
        clock = rig.one(CLOCK, cid=context.value[field])
        assert clock.value["source"] in source_points
        assert clock.value["reading"]["run"] == str(rig.clock.run)
    routes = rig.facts(contract("sui.f.route_config"))
    assert len(routes) == 1
    assert closure(rig, (routes[0].cid,)) & set(source_points)
    assert routes[0].value["effective_from"]["kind"] == "clock"
    assert routes[0].value["effective_from"]["value"]["run"] == str(rig.clock.run)


def raw_for(rig, work_id):
    return [fact for ref in (c.WORK_REPORT, c.DRAW_REPORT) for fact in rig.facts(ref)
            if fact.value["work"] == work_id]


def terminal(rig, work):
    facts = [fact for fact in rig.facts(c.WORK_TERMINAL)
             if fact.value["work"] == work.desc.work_id]
    assert len(facts) == 1
    fact = facts[0]
    assert set(fact.value) == TERMINAL_FIELDS
    assert fact.value["request"] == work.request
    assert fact.value["stage"] == work.desc.purpose
    assert fact.value["first_receipt"] in {raw.cid for raw in raw_for(rig, work.desc.work_id)}
    assert_parents(rig, fact, (work.request, fact.value["first_receipt"]), reduce=False)
    assert fact.received_ns <= fact.at_ns
    return fact


def assert_absent(rig, refs):
    for ref in refs:
        assert rig.facts(ref) == [], (ref, rig.facts(ref))


def comparison_purposes(rig, *, unmet):
    """Paper:1971,1973,3457: pG retains the original saved Qgen, reader and process."""
    qgen, origin = rig.one(c.CANDIDATE_REQUEST), rig.one(ORIGIN)
    wg = next(work for work in rig.workers.entries if work.request == qgen.cid)
    rows = tuple(row for row in rig.host.window.status().purposes
                 if row.role == "compare" and row.process == wg.desc.process and row.unmet)
    if unmet:
        assert rows, "FB2-R07: the original comparison purpose vanished after a saved clash"
        assert all(row.target == qgen.cid and row.reader == origin.cid
                   and row.o_id == "C-OG.run[Wg]" and row.handled
                   and row.obligation is not None for row in rows)
    else:
        assert rows == (), "equal/unknown reports cannot create a comparison pG"
    return rows


def additional_terminal(rig, stage, kind):
    """Paper:357,3456: equal and value/unknown are not clashes; value/failure is."""
    work = next(work for work in rig.workers.entries if work.desc.purpose == stage)
    first, issued = next((event, issue) for event, issue in rig.workers.sent
                         if getattr(event, "work", None) == work.desc.work_id)
    if kind == "equal":
        second = first
    else:
        failure = fb.FailureInfo(failure_kind="late_terminal_clash",
            content={"fixture": "FB2-R01-R2/R07", "code": 907}, readings=(), basis=())
        unknown = fb.UnknownInfo(reason="late unknown after value", basis=())
        if stage == "selection_draw":
            second = fb.DrawReturned(work=work.desc.work_id,
                outcome=fb.DrawFailure(failure=failure) if kind == "failure"
                else fb.DrawUnknown(unknown=unknown))
        else:
            second = rig.workers.finished(work, fb.WorkFailure(failure=failure)
                if kind == "failure" else fb.WorkUnknown(unknown=unknown))
        issued = None
    expected = ({"work": second.work, "outcome": wire(second.outcome)}
                if isinstance(second, fb.DrawReturned) else wire(second))
    return work, second, issued, expected


def assert_no_reentry(rig):
    before = tuple(rig.launcher.attempts)
    rig.host.run_until(lambda _status: False, timeout=0.02)
    assert tuple(rig.launcher.attempts) == before
    assert all(count == 1 for count in Counter(w.desc.work_id for w in rig.workers.entries).values())


def test_registry_preserves_builtin_and_model_operations_round_trip():
    """Paper:3432 H9; F-a:114,136,138. Bug: replace builtin registry or rewrite actions."""
    old, new = f.builtin_f_registry(), registry()
    assert all(d in new.declarations for d in old.declarations)
    # builtin_f_registry may allocate new callable wrappers. Its public stable
    # implementation identity, not Python object equality, identifies the code.
    assert {(i.kind, i.ref, i.identity) for i in old.implementations} <= {
        (i.kind, i.ref, i.identity) for i in new.implementations}
    declaration = next(d for d in new.declarations if d.ref == GENERATOR)
    assert declaration.kind == "generator"
    assert declaration.args_contract == contract("sui.f.args.empty")
    assert declaration.input_contract == declaration.output_contract == contract("sui.f.schema.candidate_input")
    document, _ = finite_world("FA01")
    value = {"actions": document["operations"], "basis": [], "draws": []}
    result = ModelOperations()(args={}, input=value, context=None)
    assert result == value and [op["id"] for op in result["actions"]] == ["Q", "M"]


@pytest.mark.parametrize("branch", ("selected", "prepare_no_decision", "evaluate_no_decision"))
def test_fa_worker_fixture_really_issues_the_requested_branch(branch):
    """F-a:348-359,388; F-b:789,3426. Harness QA only, not host integration coverage.

    Bug in the test: an undersized reader budget raises FIncomplete before an
    artifact is issued, so it cannot stand for a regular NoDecision response.
    """
    document, actions = finite_world("FA01")
    case = FactsCase(document, name="fb-stage2-worker-fixture")
    case.candidate([action.id for action in actions], generator=GENERATOR,
        measure=f.CandidateMeasureRef(name="counting", version="1", args={}))
    case.context()
    r = registry(omit_implementation=contract("finite_option_proof")
                 if branch == "prepare_no_decision" else None)
    artifact = prepare(case, registry=r, budget=PREPARE_BUDGET)
    if branch == "prepare_no_decision":
        assert isinstance(artifact.value, f.NoDecision)
        assert artifact.value.reason == "algorithm_unavailable"
        return
    assert isinstance(artifact.value, f.FProblem)
    draw = add_draw(case, artifact.value.problem_key, u=Fraction(1, 4))
    evaluated = ff.evaluate_f_from_draw(artifact, draw, reader=case.reader,
        budget=TINY_BUDGET if branch == "evaluate_no_decision" else EVALUATE_BUDGET)
    if branch == "evaluate_no_decision":
        assert isinstance(evaluated.value, f.NoDecision)
        assert evaluated.value.reason == "budget_exhausted"
    else:
        assert isinstance(evaluated.value, f.Selected)
        assert evaluated.value.choice.id == "Q" and evaluated.value.u == Fraction(1, 4)


@pytest.mark.parametrize("reverse,expected", ((False, ["Q", "M"]), (True, ["M", "Q"])))
def test_model_operations_follow_original_model_order(make_rig, reverse, expected):
    """Paper:3429,3432 H6/H9. Bug: substitute a universal hardcoded Q,M list.

    Reversed model order is the legal contrast to a Wg reply that alone reverses
    its input_order while the saved model still says Q,M.
    """
    rig = make_rig(reverse_operations=reverse)
    rig.through("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    cg = rig.one(CG)
    assert cg.value["input_order"] == expected
    assert cg.value["continuation"]["after"] == [{"candidate": name, "policy": None} for name in expected]
    assert cg.value["model"] == rig.model_point
    assert cg.value["generation"]["generator"] == plain(GENERATOR)


def test_boot_to_selected_actual_records_and_parent_equations(make_rig):
    """Paper:3244,343-346,405-418,1944-1949,2289-2299,2332-2342,3424-3432,3439.

    Bug: skip CG/context, use a supplied candidate list, attach the current heads,
    publish PR before artifact, or infer Selected from worker success/status.
    """
    rig = make_rig(ticking=True)
    rig.through("evaluation")
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    qgen, cg, eq, pr, draw, df, ee, ev, selection = (
        rig.one(ref) for ref in (c.CANDIDATE_REQUEST, CG, c.EVALUATION_REQUESTED,
            c.PREPARED, c.DRAW_REQUESTED, DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
    origin, context = rig.one(ORIGIN), rig.one(CONTEXT)
    expected_candidate = rig.workers.candidate(rig.workers.entries[0])
    assert cg.value == plain(expected_candidate)
    cg_body = rig.read_stored(cg.cid)[2].body
    assert isinstance(cg_body, Prediction)
    assert cg_body.about == (qgen.record_id,)
    assert {qgen.record_id, rig.read_stored(rig.model_point)[2].id} <= set(cg_body.basis)
    wg = next(work for work in rig.workers.entries if work.desc.purpose == "candidate_generation")
    wg_raw = raw_for(rig, wg.desc.work_id)[0]
    assert_parents(rig, cg, {qgen.cid, wg_raw.cid} | events_for(rig, expected_candidate.generation.basis))
    assert set(context.value) == {"knowledge_origin", "observation_reading", "judgment_reading", "check_events"}
    assert context.value["knowledge_origin"] == origin.cid and context.value["check_events"] == []
    o, j = (rig.one(CLOCK, cid=context.value[key]) for key in ("observation_reading", "judgment_reading"))
    assert o.value["reading"]["run"] == j.value["reading"]["run"] == str(rig.clock.run)
    assert o.value["reading"]["time_ns"] <= j.value["reading"]["time_ns"]
    assert o.value["reading"]["time_ns"] in rig.clock.reads
    assert j.value["reading"]["time_ns"] in rig.clock.reads
    assert o.value["reading"]["time_ns"] < j.value["reading"]["time_ns"] < context.at_ns
    assert o.value["source"] == j.value["source"] == rig.one(contract("sui.clock.source")).cid
    assert eq.cid not in closure(rig, (context.cid, o.cid, j.cid))
    assert_parents(rig, context, (origin.cid, o.cid, j.cid))
    ep_work = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    ee_work = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation")
    a = ep_work.desc.args
    assert a.input.model == rig.model_point and a.input.candidates == cg.cid
    assert a.input.context == context.cid and a.input.preferences == ()
    assert plain(a.input.scope) == {"name": "unbounded_total", "version": "1", "H_ns": None, "source": None}
    assert a.input.method == METHOD and a.budget == PREPARE_BUDGET
    fixed = closure(rig, a.input.fixed_parents)
    assert context.cid in fixed
    assert all(not isinstance(rig.read_stored(cid)[2].body, Prediction) for cid in fixed)
    assert not ({cg.cid, rig.model_point} & fixed)
    assert a.input.candidates == cg.cid and a.input.model == rig.model_point
    assert {cg.cid, rig.model_point} <= ep_work.desc.numerical_view.boundary
    assert not ({eq.cid, pr.cid, df.cid} & fixed)
    assert ep_work.desc.method == c.EVALUATION_PREPARE
    assert ee_work.desc.method == c.EVALUATE_FROM_DRAW
    assert ep_work.desc.output_contract == ee_work.desc.output_contract == MATH
    assert ee_work.desc.numerical_view == ep_work.desc.numerical_view
    eq_events = {origin.cid, context.cid} | events_for(rig, (cg.cid, rig.model_point))
    eq_events |= events_for(rig, (trigger.point for trigger in ep_work.desc.trigger))
    eq_events |= {ep_work.desc.allocation.declaration} | {p.declaration for p in ep_work.desc.permissions}
    assert_parents(rig, eq, eq_events)
    assert draw.value["desc"]["method"] == plain(DRAW_GENERATOR)
    request = draw.value["desc"]["args"]["request"]
    problem = rig.workers.issued["evaluation_prepare"]
    assert isinstance(problem.value, f.FProblem)
    assert request == {"purpose": "selection", "context_key": problem.value.problem_key,
        "ordinal": 0, "law": {"name": "uniform_unit", "version": "1"}, "args": {}}
    assert df.value == {"generator": plain(DRAW_GENERATOR),
        "stream_id": draw.value["desc"]["args"]["stream_id"], "request": request, "value": {"u": [1, 4]}}
    assert df.value["stream_id"] and df.value["stream_id"] != "selection"
    d_work = next(w for w in rig.workers.entries if w.desc.purpose == "selection_draw")
    d_raw = raw_for(rig, d_work.desc.work_id)[0]
    assert_parents(rig, df, (draw.cid, d_raw.cid), reduce=False)
    assert_parents(rig, draw, {pr.cid} | {p.declaration for p in d_work.desc.permissions})
    assert_parents(rig, ee, {eq.cid, pr.cid, df.cid} | {p.declaration for p in ee_work.desc.permissions})
    assert ee_work.desc.args.budget == EVALUATE_BUDGET
    assert ee_work.desc.args.evaluation_request == eq.cid
    assert ee_work.desc.args.prepared == pr.cid and ee_work.desc.args.draw == df.cid
    for work, trigger in ((ep_work, cg.cid), (d_work, pr.cid), (ee_work, df.cid)):
        assert {t.point for t in work.desc.trigger} == {trigger}
        assert work.desc.process == wg.desc.process
        assert work.desc.allocation == wg.desc.allocation
        assert work.desc.permissions == wg.desc.permissions
        assert work.desc.reader == origin.cid
        assert work.desc.numerical_view == ep_work.desc.numerical_view
        assert rig.one(REQUESTS[work.desc.purpose]).value == {"desc": wire(work.desc)}
    assert df.cid in ee_work.desc.input_points
    assert df.cid not in closure(rig, ep_work.desc.numerical_view.boundary)
    for work, logical in ((ep_work, pr), (ee_work, ev)):
        raw = raw_for(rig, work.desc.work_id)[0]
        artifact = rig.one(MATH, cid=logical.value["artifact"])
        issued = rig.workers.issued[work.desc.purpose]
        assert logical.value == {"request": work.request, "report": raw.cid, "artifact": artifact.cid}
        assert artifact.value == json.loads(issued.canonical_bytes)
        assert artifact.value["contract"] == plain(MATH)
        assert artifact.value["input"]["value"] == plain(a.input)
        assert artifact.value["environment"] == {
            "reader_view_key": captured_reader_key(rig, rig.workers.inputs[work.desc.purpose][1]),
            "registry_key": ep_work.desc.numerical_view.registry_key}
        for call in artifact.value["calls"]:
            if "budget" in call["args"]:
                expected = PREPARE_BUDGET if call["op"] == "prepare" else EVALUATE_BUDGET
                assert call["args"]["budget"] == plain(expected)
        input_events = events_for(rig, (a.input.model, a.input.candidates, a.input.context,
                                       *a.input.preferences, *a.input.fixed_parents))
        assert_parents(rig, artifact, {work.request, raw.cid} | input_events)
        assert_parents(rig, logical, {work.request, raw.cid} | events_for(rig, (artifact.cid,)))
    selected = rig.workers.issued["evaluation"].value
    assert isinstance(selected, f.Selected)
    # FA01: blank preference, Q has no information, M perfectly reveals one bit;
    # masses are 1 and 2, respectively. u=1/4 selects Q in declared Q,M order.
    assert selected.choice.id == "Q" and selected.index == 0 and selected.u == Fraction(1, 4)
    assert selected.root.K.belief is None and selected.root.K.incorporated == ()
    assert selection.value == {"evaluated": ev.cid}
    assert_parents(rig, selection, (ev.cid,), reduce=False)
    assert [w.desc.purpose for w in rig.workers.entries] == list(ORDER)
    for work in rig.workers.entries:
        t = terminal(rig, work)
        assert t.value["terminal_kind"] == ("value" if isinstance(work, fb.Draw) else "outputs")
    for cid, _ in rig.entry_store.load():
        record = rig.read_stored(cid)[2]
        if isinstance(record.body, Observed):
            assert record.body.received_ns <= record.at.mono_ns
        if record.body.contract in (CG, MATH):
            assert isinstance(record.body, Prediction) and record.writer == Role.MODEL
            assert record.category == Category.PREDICTION
    assert_no_reentry(rig)


def test_no_candidates_is_terminal_without_fictitious_problem(make_rig):
    """Paper:1948,1966,1973,2204,2207,3429-3430. Bug: invent empty CG or retry Wg."""
    rig = make_rig(empty=True)
    work = rig.run_stage("candidate_generation")
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "outputs"
    assert t.value["returned"] == {"kind": "output", "value": {
        "contract": plain(c.CANDIDATE_GENERATION), "value": {"kind": "no_candidates", "value": {}}}}
    assert_absent(rig, (CG, c.EVALUATION_REQUESTED, MATH, c.PREPARED, c.DRAW_REQUESTED, DF, c.SELECTION))
    assert_no_reentry(rig)


@pytest.mark.parametrize("stage,logical,forbidden", (
    ("evaluation_prepare", c.PREPARED, (c.DRAW_REQUESTED, DF, c.EVALUATED, c.SELECTION)),
    ("evaluation", c.EVALUATED, (c.SELECTION,)),
))
def test_regular_no_decision_retains_artifact_and_never_selects(make_rig, stage, logical, forbidden):
    """Paper:789,798,800,418,3426,3430-3431. Bug: equate definite reply with Selected.

    Ep uses a declared but unavailable proof implementation; Ee has a small
    numerical budget with sufficient reader capacity. Both return real issues.
    """
    kwargs = ({"omit_implementation": contract("finite_option_proof")} if stage == "evaluation_prepare"
              else {"evaluate_budget": TINY_BUDGET})
    rig = make_rig(**kwargs)
    rig.through(stage)
    artifact = rig.workers.issued[stage]
    assert isinstance(artifact.value, f.NoDecision), "NoDecision fixture not yet verified by a real F-a issue"
    assert artifact.value.attempt_id is None
    record = rig.one(logical)
    assert rig.one(MATH, cid=record.value["artifact"]).value == json.loads(artifact.canonical_bytes)
    work = next(w for w in rig.workers.entries if w.desc.purpose == stage)
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    assert_absent(rig, forbidden)
    assert_no_reentry(rig)


@pytest.mark.parametrize("stage", ("candidate_generation", "evaluation_prepare", "evaluation"))
@pytest.mark.parametrize("kind", ("failure", "unknown"))
def test_compute_failure_unknown_have_only_their_actual_terminal(make_rig, stage, kind):
    """Paper:350,408,417,798,800,1967-1968,2200-2208. Bug: fabricate a successful artifact."""
    rig = make_rig()
    def action(work, ctx):
        outcome = (fb.WorkFailure(failure=fb.FailureInfo(failure_kind="stage2.failure",
            content={"stage": stage, "detail": [7, 11]}, readings=(rig.actual_reading(),), basis=()))
            if kind == "failure" else fb.WorkUnknown(unknown=fb.UnknownInfo(
                reason="lost " + stage, basis=())))
        rig.workers.post(ctx, rig.workers.finished(work, outcome))
    rig.workers.overrides[stage] = action
    rig.through(stage)
    work = next(w for w in rig.workers.entries if w.desc.purpose == stage)
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == kind and t.value["returned"] is None
    raw = raw_for(rig, work.desc.work_id)[0]
    assert t.value["basis"][kind] == raw.value["outcome"]["value"]
    if stage == "candidate_generation":
        assert_absent(rig, (CG, c.EVALUATION_REQUESTED, MATH, c.PREPARED, c.DRAW_REQUESTED))
    elif stage == "evaluation_prepare":
        assert_absent(rig, (MATH, c.PREPARED, c.DRAW_REQUESTED))
    else:
        assert_absent(rig, (c.EVALUATED, c.SELECTION))
        assert len(rig.facts(MATH)) == 1
    assert_no_reentry(rig)


@pytest.mark.parametrize("kind", ("failure", "rejected", "unknown"))
def test_draw_failure_rejection_unknown_never_redraw(make_rig, kind):
    """Paper:344,416-417,799,1981-1983,2212,2294,3431. Bug: retry Unknown or treat rejection as value."""
    rig = make_rig()
    def action(work, ctx):
        outcome = (fb.DrawUnknown(unknown=fb.UnknownInfo(reason="draw response lost", basis=()))
            if kind == "unknown" else fb.DrawFailure(failure=fb.FailureInfo(
                failure_kind=kind, content={"draw": "fixture", "code": 23}, readings=(), basis=())))
        rig.workers.post(ctx, fb.DrawReturned(work=work.desc.work_id, outcome=outcome))
    rig.workers.overrides["selection_draw"] = action
    rig.through("selection_draw")
    work = next(w for w in rig.workers.entries if isinstance(w, fb.Draw))
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == ("unknown" if kind == "unknown" else "failure")
    assert t.value["returned"] is None
    assert_absent(rig, (DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
    if kind == "unknown":
        du = rig.one(c.DRAW_UNKNOWN)
        raw = raw_for(rig, work.desc.work_id)[0]
        assert set(du.value) == {"draw_request", "first_receipt", "unknown_basis", "view"}
        assert du.value["draw_request"] == work.request and du.value["first_receipt"] == raw.cid
        assert du.value["unknown_basis"] == {"reason": "draw response lost", "basis": []}
        assert_parents(rig, du, (work.request, raw.cid), reduce=False)
    else:
        assert_absent(rig, (c.DRAW_UNKNOWN,))
        assert t.value["basis"]["failure"]["failure_kind"] == kind
    assert_no_reentry(rig)


def test_work_finished_cannot_end_a_draw(make_rig):
    """Paper:344,1981-1983. Bug: use WorkFinished(Unknown) as I-8 and lose the run duty."""
    rig = make_rig()
    def action(work, ctx):
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkUnknown(unknown=fb.UnknownInfo(reason="wrong envelope for D", basis=()))))
    rig.workers.overrides["selection_draw"] = action
    rig.through("evaluation_prepare")
    work = rig.run_stage("selection_draw", raw_contract=c.WORK_REPORT)
    assert rig.one(c.WORK_REPORT, cid=raw_for(rig, work.desc.work_id)[0].cid).value["work"] == work.desc.work_id
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["work"] == work.desc.work_id]
    assert_absent(rig, (DF, c.DRAW_UNKNOWN, c.WORK_REQUESTED))
    # Nearest legal contrast: a real I-8 via the SAME worker's context.
    ctx = rig.workers.contexts["selection_draw"]
    rig.workers.post(ctx, fb.DrawReturned(work=work.desc.work_id,
        outcome=fb.DrawUnknown(unknown=fb.UnknownInfo(reason="formal I-8", basis=()))))
    rig.drive(lambda: bool(rig.facts(c.DRAW_UNKNOWN)))
    assert terminal(rig, work).value["terminal_kind"] == "unknown"


@pytest.mark.parametrize("field", ("legal", "model", "generator", "args", "basis", "draws",
                                   "input_order", "measure", "continuation"))
def test_wg_whole_declaration_matching(make_rig, field):
    """Paper:1947,2204,2332,2340,3429,3432. Bug: ignore exactly the parameterized CG field."""
    rig = make_rig()
    def action(work, ctx):
        candidate = rig.workers.candidate(work)
        changes = {
            "model": lambda: replace(candidate, model=rig.one(ORIGIN).cid),
            "generator": lambda: replace(candidate, generation=replace(candidate.generation, generator=METHOD)),
            "args": lambda: replace(candidate, generation=replace(candidate.generation, args={"extra": 17})),
            "basis": lambda: replace(candidate, generation=replace(candidate.generation,
                basis=tuple(reversed(candidate.generation.basis)) + (rig.one(ORIGIN).cid,))),
            "draws": lambda: replace(candidate, generation=replace(candidate.generation, draws=(rig.one(ORIGIN).cid,))),
            "input_order": lambda: replace(candidate, input_order=("M", "Q")),
            "measure": lambda: replace(candidate, measure=None),
            "continuation": lambda: replace(candidate, continuation=f.FContinuation(after=(
                f.ContinuationAfter(candidate="Q", policy=f.PolicyRef(name="finite_policy", version="1", args={"id": "M"})),
                f.ContinuationAfter(candidate="M", policy=None)))),
        }
        if field != "legal":
            changed = changes[field]()
            assert plain(changed) != plain(candidate), "nondiscriminating mutation"
            candidate = changed
        event = rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": plain(candidate)})))
        rig.workers.post(ctx, event)
    rig.workers.overrides["candidate_generation"] = action
    work = rig.run_stage("candidate_generation")
    raw = raw_for(rig, work.desc.work_id)[0]
    assert raw.value == wire(rig.workers.sent[-1][0])
    if field == "legal":
        rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
        assert rig.one(CG).value == raw.value["outcome"]["value"]["value"]["value"]
    else:
        assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))


@pytest.mark.parametrize("stage", ("evaluation_prepare", "evaluation"))
@pytest.mark.parametrize("mutation", ("legal", "missing_issue", "changed_budget", "same_problem_other_bytes", "other_pr"))
def test_math_issue_is_bound_to_the_whole_requested_computation(make_rig, stage, mutation):
    """Paper:343,345,1150-1152,2334,3426,3428,3431. Bug: trust problem_key or serialized claim alone."""
    rig = make_rig()
    donor = None
    if mutation == "other_pr":
        # A separate Boot has a different PR and issue bytes; the identical
        # mathematical problem key is deliberately insufficient evidence.
        donor = make_rig(prepare_budget=replace(PREPARE_BUDGET, max_terms=4103))
        donor.through(stage)
    def action(work, ctx):
        artifact = (rig.workers.prepare(work, ctx) if stage == "evaluation_prepare"
                    else rig.workers.evaluate(work, ctx))
        assert not isinstance(artifact.value, f.NoDecision), "positive fixture must reach its mathematical result"
        value, issued = json.loads(artifact.canonical_bytes), artifact
        if mutation == "missing_issue":
            issued = None
        elif mutation in ("changed_budget", "same_problem_other_bytes"):
            larger = replace(work.desc.args.budget, max_terms=work.desc.args.budget.max_terms + 7)
            other = (rig.workers.prepare(work, ctx, budget=larger) if stage == "evaluation_prepare"
                     else rig.workers.evaluate(work, ctx, budget=larger))
            assert other.canonical_bytes != artifact.canonical_bytes
            if stage == "evaluation_prepare":
                assert other.value.problem_key == artifact.value.problem_key
            else:
                assert other.value.root.problem_key == artifact.value.root.problem_key
            if mutation == "changed_budget":
                value, issued = json.loads(other.canonical_bytes), other
            else:
                issued = other  # reported bytes still belong to artifact
        elif mutation == "other_pr":
            issued = donor.workers.issued[stage]
            value = json.loads(issued.canonical_bytes)
            assert issued.canonical_bytes != artifact.canonical_bytes
        rig.workers.issued[stage] = artifact
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), issued)
    rig.workers.overrides[stage] = action
    rig.through(stage)
    ref = c.PREPARED if stage == "evaluation_prepare" else c.EVALUATED
    if mutation == "legal":
        rig.drive(lambda: bool(rig.facts(ref)))
        assert rig.one(MATH, cid=rig.one(ref).value["artifact"]).value == json.loads(rig.workers.issued[stage].canonical_bytes)
    else:
        assert_absent(rig, (ref, c.SELECTION))
        if stage == "evaluation_prepare":
            assert_absent(rig, (MATH, c.DRAW_REQUESTED))
        else:
            assert len(rig.facts(MATH)) == 1


@pytest.mark.parametrize("field", ("law", "args", "context_key", "ordinal"))
def test_ee_rejects_changed_draw_request_inside_artifact(make_rig, field):
    """Paper:344,1151-1152,2339,3427-3428. Bug: authenticate artifact by draw ID only.

    I-8 contains only a value. Change one field of the returned Selected root's
    DrawRecord, leaving the real D/DF and live issue untouched. A window that
    compares only problem_key/draw.id would incorrectly publish EV.
    """
    rig = make_rig()
    def action(work, ctx):
        artifact = rig.workers.evaluate(work, ctx)
        value = json.loads(artifact.canonical_bytes)
        assert value["claim"]["type"] == "Selected"
        request = value["claim"]["value"]["root"]["selection_draw"]["request"]
        replacements = {"law": {"name": "other_uniform", "version": "1"}, "args": {"grid": 4},
                        "context_key": "different_problem", "ordinal": 1}
        assert request[field] != replacements[field]
        request[field] = replacements[field]
        assert canonical(value) != artifact.canonical_bytes
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), artifact)
    rig.workers.overrides["evaluation"] = action
    rig.through("evaluation")
    assert rig.one(DF).value["request"]["ordinal"] == 0
    assert_absent(rig, (c.EVALUATED, c.SELECTION))


@pytest.mark.parametrize("stage", ORDER)
@pytest.mark.parametrize("pair", ("unknown_value", "value_unknown", "equal", "different"))
@pytest.mark.parametrize("accept_order", ("post_order", "reversed"))
def test_first_terminal_follows_post_order_not_acceptance_or_value(make_rig, stage, pair, accept_order):
    """Paper:344,417,785-800,1163,1971,1973,3431,3457 FB2-R07.

    Bug: prefer value, last report, Receipt.index, or lose pG for simultaneous clashes.

    Two posts share r; Post's envelope sequence, not value/CID sorting, breaks
    the tie. Both genuine worker reports must remain as raw receipts.
    """
    rig = make_rig()
    expected = []
    posted = []
    def action(work, ctx):
        event, issue = rig.workers.normal(work, ctx)
        unknown = (fb.DrawReturned(work=work.desc.work_id,
            outcome=fb.DrawUnknown(unknown=fb.UnknownInfo(reason="first-terminal probe", basis=())))
            if isinstance(work, fb.Draw) else rig.workers.finished(work,
                fb.WorkUnknown(unknown=fb.UnknownInfo(reason="first-terminal probe", basis=()))))
        if pair == "unknown_value":
            posts = [(unknown, None), (event, issue)]
        elif pair == "value_unknown":
            posts = [(event, issue), (unknown, None)]
        elif pair == "equal":
            posts = [(event, issue), (event, issue)]
        else:
            if isinstance(event, fb.DrawReturned):
                changed = replace(event, outcome=fb.DrawValue(value={"u": [3, 4]}))
            elif stage == "candidate_generation":
                candidate = rig.workers.candidate(work)
                order = ("M", "Q")
                other = replace(candidate, input_order=order, continuation=f.FContinuation(after=tuple(
                    f.ContinuationAfter(candidate=name, policy=None) for name in order)))
                changed = replace(event, outcome=fb.WorkOutputs(outputs=f.ContractValue(
                    contract=c.CANDIDATE_GENERATION,
                    value={"kind": "candidates", "value": plain(other)})))
            else:
                value = json.loads(issue.canonical_bytes)
                value["calls"][0]["args"]["budget"]["max_terms"] += 1
                changed = replace(event, outcome=fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value)))
            posts = [(event, issue), (changed, issue)]
        expected.extend(posts)
        for report, live in posts:
            rig.workers.post(ctx, report, live)
        # These are independent EH receipt observations, not window status or
        # private queue inspection. Re-submit those SAME public envelopes to
        # invert Accept, while Post's actual numbers/r remain untouched.
        observation = next(e for e in ctx.evidence().executions if e.work_id == work.desc.work_id)
        posted.extend(observation.reports)
        assert len(posted) == 2 and posted[0].envelope < posted[1].envelope
        if accept_order == "reversed":
            later = posted[1]
            rig.host.window.accept(fb.Envelope(number=later.envelope,
                event=posts[1][0], received_ns=later.received_ns))
            rig.settle_steps()
            assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["work"] == work.desc.work_id], (
                "INV-15: terminal published before the earlier Post was accepted/saved")
            earlier = posted[0]
            rig.host.window.accept(fb.Envelope(number=earlier.envelope,
                event=posts[0][0], received_ns=earlier.received_ns))
    rig.workers.overrides[stage] = action
    rig.through(stage)
    work = next(w for w in rig.workers.entries if w.desc.purpose == stage)
    raw = raw_for(rig, work.desc.work_id)
    assert len(raw) == 2 and raw[0].received_ns == raw[1].received_ns
    observations = next(e for e in rig.workers.contexts[stage].evidence().executions
                        if e.work_id == work.desc.work_id).reports
    points = {r.envelope: r.point for r in observations}
    assert set(points.values()) == {fact.cid for fact in raw}
    # Actual saved receipt Points mapped by EH back to the actual Post sequence.
    raw = [next(fact for fact in raw if fact.cid == points[r.envelope]) for r in posted]
    wanted = [{"work": event.work, "outcome": wire(event.outcome)} if isinstance(event, fb.DrawReturned)
              else wire(event) for event, _ in expected]
    assert [fact.value for fact in raw] == wanted
    t = terminal(rig, work)
    assert t.value["first_receipt"] == raw[0].cid
    assert t.value["terminal_kind"] == ("unknown" if pair == "unknown_value" else
        "value" if stage == "selection_draw" else "outputs")
    if pair == "unknown_value":
        if stage == "candidate_generation":
            assert_absent(rig, (CG, c.EVALUATION_REQUESTED))
        elif stage == "evaluation_prepare":
            assert_absent(rig, (c.PREPARED, c.DRAW_REQUESTED))
        elif stage == "selection_draw":
            assert_absent(rig, (DF, c.WORK_REQUESTED))
        else:
            assert_absent(rig, (c.EVALUATED, c.SELECTION))
    if "unknown" in pair:
        assert_absent(rig, (c.CONFLICT,))
    children = {
        "candidate_generation": (CG, c.EVALUATION_REQUESTED),
        "evaluation_prepare": (c.PREPARED, c.DRAW_REQUESTED),
        "selection_draw": (DF, c.WORK_REQUESTED),
        "evaluation": (c.EVALUATED, c.SELECTION),
    }[stage]
    if pair == "different":
        # Both actual posts precede processing. T still belongs to the first;
        # incompatible value reports cannot authorize a new use of that value.
        assert_absent(rig, children)
        comparison_purposes(rig, unmet=True)
    elif pair == "equal":
        # Rejecting all duplicate reports would pass the negative on its own.
        rig.drive(lambda: all(rig.facts(ref) for ref in children))
        first, second = (rig.one(ref) for ref in children)
        if stage == "candidate_generation":
            returned = raw[0].value["outcome"]["value"]["value"]["value"]
            assert first.value == returned
            assert second.value["desc"]["args"]["input"]["candidates"] == first.cid
        elif stage == "evaluation_prepare":
            assert first.value["request"] == work.request and first.value["report"] == raw[0].cid
            assert second.value["desc"]["args"]["prepared"] == first.cid
        elif stage == "selection_draw":
            assert first.value["value"] == raw[0].value["outcome"]["value"]
            assert second.value["desc"]["args"]["draw"] == first.cid
        else:
            assert first.value["request"] == work.request and first.value["report"] == raw[0].cid
            assert second.value == {"evaluated": first.cid}
        comparison_purposes(rig, unmet=False)
    assert_no_reentry(rig)


def test_fixed_eq_and_both_readers_exclude_later_received(make_rig):
    """Paper:410,3302,3424,3428,3431. Bug: lazy ctx.reader reads current ledger heads."""
    rig = make_rig()
    rig.through("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    before = rig.one(c.EVALUATION_REQUESTED)
    saved_eq = rig.read_stored(before.cid)
    rig.clock.set(200)
    event = received(b"later raw fact", claims={"value": 101, "fixture": "late"})
    rig.host.post(event)
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    late = rig.one(c.RECEIVED)
    rig.run_stage("evaluation_prepare")
    rig.run_stage("selection_draw")
    rig.run_stage("evaluation")
    assert rig.read_stored(before.cid) == saved_eq
    for stage in ("evaluation_prepare", "evaluation"):
        desc, reader = rig.workers.inputs[stage]
        assert late.cid not in desc.numerical_view.boundary
        assert late.cid not in desc.input_points
        assert late.cid not in {entry.cid for entry in reader.entries()}
        with pytest.raises(KeyError):
            reader.record(late.cid)
        artifact = json.loads(rig.workers.issued[stage].canonical_bytes)
        assert late.cid not in artifact["input"]["value"]["fixed_parents"]
    assert rig.one(c.RECEIVED).value == wire(event)
    assert rig.workers.issued["evaluation"].value.choice.id == "Q"


ENTRY_DEPENDENCIES = (
    ("candidate_generation", "evaluation_prepare"),
    ("candidate_generation", "selection_draw"),
    ("candidate_generation", "evaluation"),
    ("evaluation_prepare", "selection_draw"),
    ("evaluation_prepare", "evaluation"),
    ("selection_draw", "evaluation"),
)
ENTRY_REPORT_CASES = (
    ("failure_cut", "failure", True),
    ("equal_cut", "equal", True),
    ("unknown_cut", "unknown", True),
    ("equal_without_fault", "equal", False),
)


@pytest.mark.parametrize("upstream,target", ENTRY_DEPENDENCIES,
    ids=[f"{a}_to_{b}" for a, b in ENTRY_DEPENDENCIES])
@pytest.mark.parametrize("label,kind,fault", ENTRY_REPORT_CASES, ids=[row[0] for row in ENTRY_REPORT_CASES])
@pytest.mark.parametrize("entrance", ("enter_first", "drain_first"))
def test_fb2_r01_r2_saved_reports_guard_every_later_worker_before_settle_finishes(
        make_rig, upstream, target, label, kind, fault, entrance):
    """Paper:357,864,1971,3456-3458 FB2-R01-R2. Bug: trust a settle-updated missing flag.

    All six forward worker dependencies are tested at both public entrances.
    Received's one failing write must follow the saved second report. On the
    enter path no status/drain/settle/rebuild occurs between that cut and the
    claimed callback. On the start path a genuinely not_started launch leaves
    drain as the FIRST window observation. Equal/unknown and no-fault equal
    controls then really enter once and reach selection using the same inputs.
    """
    rig = make_rig()
    normal_launch = rig.launcher.launch
    if entrance == "drain_first":
        def not_started_target(work_id, body):
            if any(fact.value["desc"]["work_id"] == work_id
                   for fact in rig.facts(REQUESTS[target])):
                rig.launcher.attempts.append((work_id, body))
                return "not_started"
            return normal_launch(work_id, body)
        rig.launcher.launch = not_started_target
    rig.through(ORDER[ORDER.index(target) - 1])
    request = rig.request(target)
    wid = request.value["desc"]["work_id"]
    if entrance == "enter_first":
        body = rig.callback(target)
    else:
        offered, = (work for work in rig.host.window.drain() if work.desc.work_id == wid)
        assert offered.request == request.cid
    assert not [work for work in rig.workers.entries if work.desc.work_id == wid]
    before_attempts = len(rig.launcher.attempts)
    previous, second, issued, expected = additional_terminal(rig, upstream, kind)
    first_terminal = terminal(rig, previous)
    saved_request = rig.read_stored(request.cid)
    rig.workers.post(rig.workers.contexts[upstream], second, issued)
    incoming = received(b"unrelated Received cuts settle", claims={"fixture": "FB2-R01-R2",
        "upstream": upstream, "target": target, "case": label, "entrance": entrance})
    rig.host.post(incoming)
    if fault:
        rig.ledger.cut = (c.RECEIVED, "before")
        with pytest.raises(OSError, match="stage2 before write"):
            rig.host.run_until(lambda _status: False, timeout=2)
        assert len(rig.ledger.hit) == 1
        ref, side, failed = rig.ledger.hit[0]
        assert (ref, side) == (c.RECEIVED, "before")
        assert failed.record.body.content.as_json() == wire(incoming)
        assert failed.cid not in dict(rig.entry_store.load())
        assert_absent(rig, (c.RECEIVED,))
    else:
        rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
        if entrance == "drain_first":
            # A confirmed not_started launch may legally be offered again while
            # the no-fault pump runs. Discard those callbacks; none has entered.
            before_attempts = len(rig.launcher.attempts)
    # Only independent C/E and the test-owned write log are inspected here.
    raw = raw_for(rig, previous.desc.work_id)
    assert len(raw) == 2
    later, = (fact for fact in raw if fact.cid != first_terminal.value["first_receipt"])
    assert later.value == expected
    assert terminal(rig, previous) == first_terminal
    if fault:
        report_write, = (i for i, item in enumerate(rig.ledger.writes) if item.cid == later.cid)
        failed_write, = (i for i, item in enumerate(rig.ledger.writes) if item.cid == failed.cid)
        assert report_write < failed_write
    blocked = kind == "failure"
    if entrance == "enter_first":
        body()  # FIRST post-cut public entrance; do not repair the window first.
        assert [ok for key, ok in rig.workers.entry_attempts if key == wid] == [not blocked]
        assert len([work for work in rig.workers.entries if work.desc.work_id == wid]) == int(not blocked)
    else:
        available = [work for work in rig.host.window.drain() if work.desc.work_id == wid]
        assert [work.request for work in available] == ([] if blocked else [request.cid])
        assert not [attempt for attempt in rig.workers.entry_attempts if attempt[0] == wid]
        assert len(rig.launcher.attempts) == before_attempts
    # Observe the conflict without a successful settle after the failing write.
    conflicts = [row for row in rig.host.window.status().pending if row.kind == "conflict"]
    if blocked:
        assert conflicts
        related = closure(rig, (request.cid, previous.request, later.cid))
        assert any(isinstance(row.target, str) and row.target in related for row in conflicts)
        assert not [event for event, _ in rig.workers.sent if getattr(event, "work", None) == wid]
        assert raw_for(rig, wid) == []
        assert all(work.desc.work_id != wid for work in rig.host.window.drain())
    else:
        assert conflicts == []
    comparison_purposes(rig, unmet=blocked)
    rig.launcher.launch = normal_launch
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    assert rig.one(c.RECEIVED).value == wire(incoming)
    if fault:
        saved = rig.one(c.RECEIVED, cid=failed.cid)
        assert rig.read_stored(saved.cid) == (failed.header, failed.salt, failed.record)
        assert all(item == failed for item in rig.ledger.writes if item.cid == failed.cid)
    assert rig.read_stored(request.cid) == saved_request
    if blocked:
        assert len(rig.launcher.attempts) == before_attempts
        assert raw_for(rig, wid) == []
        forbidden = {"evaluation_prepare": (c.PREPARED, c.DRAW_REQUESTED),
                     "selection_draw": (DF, c.WORK_REQUESTED),
                     "evaluation": (c.EVALUATED, c.SELECTION)}[target]
        assert_absent(rig, forbidden)
    else:
        if entrance == "drain_first":
            rig.drive(lambda: any(key == wid for key, _ in rig.launcher.attempts[before_attempts:]))
            callbacks = [callback for key, callback in rig.launcher.attempts[before_attempts:] if key == wid]
            assert len(callbacks) == 1
            callbacks[0]()
        rig.drive(lambda: bool(raw_for(rig, wid)))
        assert [ok for key, ok in rig.workers.entry_attempts if key == wid] == [True]
        for stage in ORDER[ORDER.index(target) + 1:]:
            rig.run_stage(stage)
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert rig.workers.issued["evaluation"].value.choice.id == "Q"
        comparison_purposes(rig, unmet=False)


@pytest.mark.parametrize("stage", ORDER)
@pytest.mark.parametrize("kind", ("failure", "equal"))
def test_fb2_r07_late_clash_keeps_original_purpose_and_saved_facts_on_rebuild(make_rig, stage, kind):
    """Paper:357,1971,1973,3457-3458 FB2-R07. Bug: pG is added only while handling the first end.

    Save the genuine success and its next request before the second report.
    Wg/Ep/D must block the held Ep/D/Ee callback; Ee has no later worker, so its
    already saved EV/selection stay unchanged while the original pG is restored.
    Equal duplicate reports keep pG absent and genuinely permit the next worker.
    """
    rig = make_rig()
    rig.through(stage)
    first_work = next(work for work in rig.workers.entries if work.desc.purpose == stage)
    first_terminal = terminal(rig, first_work)
    published = {"candidate_generation": (CG, c.EVALUATION_REQUESTED),
                 "evaluation_prepare": (c.PREPARED, c.DRAW_REQUESTED),
                 "selection_draw": (DF, c.WORK_REQUESTED),
                 "evaluation": (c.EVALUATED, c.SELECTION)}[stage]
    saved = {fact.cid: rig.read_stored(fact.cid) for fact in (rig.one(ref) for ref in published)}
    next_index = ORDER.index(stage) + 1
    if next_index < len(ORDER):
        following = ORDER[next_index]
        callback = rig.callback(following)
        wid = rig.request(following).value["desc"]["work_id"]
        assert not [work for work in rig.workers.entries if work.desc.work_id == wid]
    comparison_purposes(rig, unmet=False)
    work, second, issued, expected = additional_terminal(rig, stage, kind)
    rig.workers.post(rig.workers.contexts[stage], second, issued)
    rig.drive(lambda: len(raw_for(rig, work.desc.work_id)) == 2)
    rig.settle_steps()
    raw = raw_for(rig, work.desc.work_id)
    later, = (fact for fact in raw if fact.cid != first_terminal.value["first_receipt"])
    assert later.value == expected
    assert terminal(rig, work) == first_terminal
    blocked = kind == "failure"
    purposes = comparison_purposes(rig, unmet=blocked)
    if next_index < len(ORDER):
        callback()
        assert [ok for key, ok in rig.workers.entry_attempts if key == wid] == [not blocked]
        if blocked:
            assert raw_for(rig, wid) == []
            assert not [event for event, _ in rig.workers.sent if getattr(event, "work", None) == wid]
            assert all(work.desc.work_id != wid for work in rig.host.window.drain())
        else:
            rig.drive(lambda: bool(raw_for(rig, wid)))
            for current in ORDER[next_index + 1:]:
                rig.run_stage(current)
            rig.drive(lambda: bool(rig.facts(c.SELECTION)))
            assert rig.workers.issued["evaluation"].value.choice.id == "Q"
    assert all(rig.read_stored(point) == original for point, original in saved.items())
    snapshot = rig.storage_snapshot()
    rig.host.rebuild_window()
    assert rig.storage_snapshot() == snapshot
    assert comparison_purposes(rig, unmet=blocked) == purposes
    rig.settle_steps()
    assert comparison_purposes(rig, unmet=blocked) == purposes
    assert terminal(rig, work) == first_terminal
    assert all(rig.read_stored(point) == original for point, original in saved.items())


@pytest.mark.parametrize("hung", ("measure_segment", "candidate_generation"))
def test_two_seats_offer_both_directions_and_receive_while_one_hangs(make_rig, hung):
    """Paper:405,412-413,424,1946,3244 D7-Q2,3433. Bug: global worker mutex or shared slot.

    Both requests originate at Boot, Need is explicitly one seat, capacity two.
    Event gates prove overlap; no internal work injection or elapsed-time oracle.
    """
    rig = make_rig()
    rig.workers.gates[hung] = Event()
    rig.background(hung)
    other = "candidate_generation" if hung == "measure_segment" else "measure_segment"
    callback = rig.callback(other)
    if other == "candidate_generation":
        callback()
        rig.drive(lambda: bool(rig.facts(CG)))
        assert rig.one(CG).value["input_order"] == ["Q", "M"]
    else:
        def report(work, ctx):
            rig.workers.post(ctx, fb.SegmentReport(segment=work.request, item_slot="while-thinking",
                item=f.MeasurementUnavailable(route_epoch="route-A",
                    requested_interval=f.MeasurementInterval(clock=rig.clock.run,
                        start_ns=90, end_ns=100, closure="(start,end]"),
                    reason="real test report while Wg held", evidence=())))
        rig.workers.overrides[other] = report
        callback()
        rig.drive(lambda: bool(rig.facts(c.SEGMENT_REPORT)))
        assert rig.one(c.SEGMENT_REPORT).value["item"]["value"]["reason"] == "real test report while Wg held"
    rig.host.post(received(b"receive while held", claims={"hung": hung}))
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    assert rig.one(c.RECEIVED).value["data"] == list(b"receive while held")
    assert {w.desc.purpose for w in rig.workers.entries} == {hung, other}
    held = next(w for w in rig.workers.entries if w.desc.purpose == hung)
    assert held.desc.work_id not in rig.workers.stops
    assert not rig.workers.gates[hung].is_set()
    assert Counter(key for key, _ in rig.launcher.attempts).most_common(1)[0][1] == 1


FAULT_TARGETS = (
    ("CG", CG, "candidate_generation"),
    ("clock", CLOCK, "candidate_generation"),
    ("context", CONTEXT, "candidate_generation"),
    ("EQ", c.EVALUATION_REQUESTED, "candidate_generation"),
    ("Ep_artifact", MATH, "evaluation_prepare"),
    ("PR", c.PREPARED, "evaluation_prepare"),
    ("DF", DF, "selection_draw"),
    ("Ee_artifact", MATH, "evaluation"),
    ("EV", c.EVALUATED, "evaluation"),
    ("selection", c.SELECTION, "evaluation"),
)


@pytest.mark.parametrize("label,target,arm_stage", FAULT_TARGETS, ids=[row[0] for row in FAULT_TARGETS])
@pytest.mark.parametrize("side", ("before", "after"))
def test_storage_retry_reuses_the_same_preparation(make_rig, target, side, label, arm_stage):
    """Paper:406,2061,2071-2076,2289-2299,2332-2334,3424. Bug: retry creates new salt/r/parents/CID."""
    rig = make_rig()
    for stage in ORDER:
        if stage == arm_stage:
            rig.ledger.cut = (target, side)
        try:
            rig.run_stage(stage)
        except OSError:
            assert rig.ledger.hit, "unexpected unclassified storage error"
        # Recovery does not create a new report or execute the worker again.
        if rig.ledger.hit:
            rig.clock.set(300)
        rig.settle_steps()
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert len(rig.ledger.hit) == 1 and rig.ledger.cut is None
    _, _, prepared = rig.ledger.hit[0]
    attempts = [item for item in rig.ledger.writes if item.cid == prepared.cid]
    assert attempts and all(item == prepared for item in attempts)
    assert len([item for item in rig.ledger.preparations if item.cid == prepared.cid]) == 1
    fact = rig.one(target, cid=prepared.cid)
    header, salt, record = rig.read_stored(fact.cid)
    assert header == prepared.header and salt == prepared.salt and record == prepared.record
    assert rig.one(c.SELECTION).value["evaluated"] == rig.one(c.EVALUATED).cid
    assert_no_reentry(rig)


@pytest.mark.parametrize("target", (CG, c.EVALUATION_REQUESTED, c.PREPARED, DF),
                         ids=lambda ref: ref.name.rsplit(".", 1)[-1])
def test_rebuild_during_saved_plan_keeps_issue_owner_and_draw_once(make_rig, target):
    """Paper:405-408,416,1933-1939 M2,3424,3427-3428. Bug: rebuild drops continuation/live Ep issue."""
    rig = make_rig()
    rig.ledger.cut = (target, "before")
    rebuilt = False
    for stage in ORDER:
        try:
            rig.run_stage(stage)
        except OSError:
            assert rig.ledger.hit
        if rig.ledger.hit and not rebuilt:
            old = rig.host.window
            entries = list(rig.workers.entries)
            issues = dict(rig.workers.issued)
            original = rig.ledger.hit[0][2]
            snapshot = rig.storage_snapshot()
            rig.host.rebuild_window()
            rebuilt = True
            assert rig.storage_snapshot() == snapshot
            assert rig.workers.entries == entries and rig.workers.issued == issues
            with pytest.raises(RuntimeError):
                old.settle()
            rig.settle_steps()
            assert rig.one(target, cid=original.cid).value == original.record.body.content.as_json()
        rig.settle_steps()
    assert rebuilt
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert [w.desc.purpose for w in rig.workers.entries] == list(ORDER)
    assert rig.workers.issued["evaluation"].value.root.problem_key == rig.workers.issued["evaluation_prepare"].value.problem_key
    assert_no_reentry(rig)


@pytest.mark.parametrize("branch", ("generated", "no_candidates", "no_decision", "failure", "unknown", "selection"))
def test_readings_show_actual_distinct_stage2_facts(make_rig, branch):
    """Paper:1920-1929 M1,3429-3430 H7. Bug: every reply is generated/selected or Unknown.

    This is explicitly a presentation test. Expected branches/targets come from
    saved facts and actual reports; status never determines the next operation.
    """
    rig = make_rig(empty=branch == "no_candidates",
                   omit_implementation=contract("finite_option_proof") if branch == "no_decision" else None)
    if branch in ("failure", "unknown"):
        def action(work, ctx):
            outcome = (fb.WorkFailure(failure=fb.FailureInfo(failure_kind="display_probe",
                content={"code": 31}, readings=(), basis=())) if branch == "failure" else
                fb.WorkUnknown(unknown=fb.UnknownInfo(reason="display unknown", basis=())))
            rig.workers.post(ctx, rig.workers.finished(work, outcome))
        rig.workers.overrides["candidate_generation"] = action
    rig.through("evaluation" if branch == "selection" else
                "evaluation_prepare" if branch == "no_decision" else "candidate_generation")
    if branch == "selection":
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    status = rig.host.window.status()
    assert isinstance(status, fb.FStatus)
    assert status.readings, "H7: stage-2 facts are missing from readings"
    if branch == "generated":
        cg = rig.one(CG)
        assert any(r.target == cg.cid and r.reached == "generated" for r in status.readings)
    elif branch == "selection":
        selected = rig.one(c.SELECTION)
        assert any(r.selected == selected.cid for r in status.readings)
    else:
        expected = "no_candidates" if branch == "no_candidates" else branch
        work = rig.workers.entries[-1]
        t = terminal(rig, work)
        assert any(r.response == expected and r.selected is None and
            (r.target in (work.request, t.cid) or t.cid in r.evidence.basis)
            for r in status.readings)
        if branch == "no_decision":
            assert isinstance(rig.workers.issued["evaluation_prepare"].value, f.NoDecision)
            shown = next(w for w in status.works if w.work_id == work.desc.work_id)
            assert shown.knowledge == "success"
    before = rig.storage_snapshot(), len(rig.launcher.attempts), len(rig.workers.sent)
    rig.host.window.status()
    assert before == (rig.storage_snapshot(), len(rig.launcher.attempts), len(rig.workers.sent))


@pytest.mark.parametrize("branch", ("no_candidates", "failure", "unknown"))
def test_generation_residual_purpose_keeps_original_target_on_rebuild(make_rig, branch):
    """Paper:1951-1973,3429-3430 H7. Bug: discard pG when Wg's reply is handled.

    Meaning 6 is checked as a display of the actual Wg request and unsuccessful
    comparison. This is not a claim that an owner string proves internal custody.
    """
    rig = make_rig(empty=branch == "no_candidates")
    if branch != "no_candidates":
        def action(work, ctx):
            outcome = (fb.WorkFailure(failure=fb.FailureInfo(failure_kind="pG_probe",
                content={"detail": 41}, readings=(), basis=())) if branch == "failure" else
                fb.WorkUnknown(unknown=fb.UnknownInfo(reason="pG unknown", basis=())))
            rig.workers.post(ctx, rig.workers.finished(work, outcome))
        rig.workers.overrides["candidate_generation"] = action
    work = rig.run_stage("candidate_generation")
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == ("outputs" if branch == "no_candidates" else branch)
    origin = rig.one(ORIGIN)
    expected = [purpose for purpose in rig.host.window.status().purposes
        if purpose.unmet and purpose.target == work.request and purpose.reader == origin.cid
        and purpose.process == work.desc.process]
    assert expected, "H7/M3: original comparison purpose vanished after non-success"
    assert all(purpose.obligation is not None for purpose in expected)
    rig.host.rebuild_window()
    assert all(purpose in rig.host.window.status().purposes for purpose in expected)
    assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.SELECTION))


def test_h1_clock_parent_equations_from_saved_cg(make_rig):
    """Paper:3424,3439. Replaces CG-S2-H1-CLOCK-PARENTS with the declared equations.

    Bug: attach the whole numerical boundary to o/context, or omit o from j.
    Expected event evidence is independently expanded from the actual saved CG.
    """
    rig = make_rig(ticking=True)
    rig.through("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    cg, context, origin, clock_source = (rig.one(ref) for ref in (CG, CONTEXT, ORIGIN, CLOCK_SOURCE))
    o = rig.one(CLOCK, cid=context.value["observation_reading"])
    j = rig.one(CLOCK, cid=context.value["judgment_reading"])
    assert o.value["source"] == j.value["source"] == clock_source.cid
    assert_parents(rig, o, {clock_source.cid} | events_for(rig, (cg.cid,)))
    assert_parents(rig, j, (clock_source.cid, o.cid))
    assert_parents(rig, context, (origin.cid, o.cid, j.cid))
    assert o.value["reading"]["time_ns"] < j.value["reading"]["time_ns"] < context.at_ns
    assert rig.one(c.EVALUATION_REQUESTED).cid not in closure(rig, (context.cid,))


@pytest.mark.parametrize("first", ("notice", "boot"))
def test_k1_notice_and_boot_both_orders_issue_causal_source_and_prepare(make_rig, first):
    """Paper:3437,3442 K1. Bug: lose an early notice, require one order, or save a raw source.

    The first input is fully saved before posting the second. Counts, full bodies,
    direct parent equations, r/s and actual F-a preparation are checked separately.
    """
    rig = make_rig(auto_boot=False, ticking=True)
    events = {"notice": rig.clock_event, "boot": rig.boot_input}
    rig.host.post(events[first])
    first_contract = c.CLOCK_NOTICE if first == "notice" else c.BOOT_DECLARATION
    rig.drive(lambda: bool(rig.facts(first_contract)))
    rig.settle_steps()
    assert_absent(rig, (CLOCK_SOURCE, CONTEXT, CLOCK))
    rig.host.post(events["boot" if first == "notice" else "notice"])
    rig.drive(lambda: bool(rig.facts(CLOCK_SOURCE)))
    notice = rig.one(c.CLOCK_NOTICE)
    assert notice.value == wire(rig.clock_event.declaration)
    published = assert_k1_source_for_notice(rig, notice)
    assert len(rig.facts(CLOCK_SOURCE)) == 1
    assert_ep_is_prepared_from_k1_source(rig, {published.cid})


@pytest.mark.parametrize("first", ("notice", "boot"))
def test_k1_foreign_run_notice_is_retained_but_cannot_issue_source(make_rig, first):
    """Paper:3442 K1. Bug: adopt a foreign run's clock or erase its raw notice.

    A later matching-run notice is the nearest legal contrast: it must issue its
    own source and let the same Boot reach Ep without using the foreign notice.
    """
    rig = make_rig(auto_boot=False, ticking=True)
    foreign_run = type(rig.clock.run)(kind=RefKind.RUN, value="stage2-other-run")
    foreign = replace(rig.clock_event, declaration=replace(rig.clock_event.declaration, run=foreign_run))
    events = {"notice": foreign, "boot": rig.boot_input}
    rig.host.post(events[first])
    first_contract = c.CLOCK_NOTICE if first == "notice" else c.BOOT_DECLARATION
    rig.drive(lambda: bool(rig.facts(first_contract)))
    rig.host.post(events["boot" if first == "notice" else "notice"])
    rig.drive(lambda: bool(rig.facts(BOOT)) and bool(rig.facts(c.CLOCK_NOTICE)))
    rig.settle_steps()
    raw_foreign = rig.one(c.CLOCK_NOTICE)
    assert raw_foreign.value == wire(foreign.declaration) and raw_foreign.parents == frozenset()
    assert_absent(rig, (CLOCK_SOURCE, CONTEXT, CLOCK, contract("sui.f.route_config")))
    rig.host.post(rig.clock_event)
    rig.drive(lambda: len(rig.facts(c.CLOCK_NOTICE)) == 2 and bool(rig.facts(CLOCK_SOURCE)))
    matching = next(fact for fact in rig.facts(c.CLOCK_NOTICE)
                    if fact.value["run"] == str(rig.clock.run))
    published = assert_k1_source_for_notice(rig, matching)
    assert rig.one(c.CLOCK_NOTICE, cid=raw_foreign.cid) == raw_foreign
    assert len(rig.facts(CLOCK_SOURCE)) == 1
    assert raw_foreign.cid not in closure(rig, (published.cid,))
    assert_ep_is_prepared_from_k1_source(rig, {published.cid})


@pytest.mark.parametrize("reverse", (False, True))
def test_k1_conflicting_issued_sources_do_not_authorize_clock_use(make_rig, reverse):
    """Paper:409,420,3442 K1. Bug: select the first/CID-smallest clock declaration.

    Both notices are saved before Boot, so no earlier valid route/context is
    mistaken for a new use after a conflict. Only resolution_s differs; both
    declarations name the same run and the same supported clock contract.
    """
    rig = make_rig(auto_boot=False, ticking=True)
    changed = replace(rig.clock_event, declaration=replace(rig.clock_event.declaration,
        resolution_s=Fraction(1, 10**6)))
    notices = [rig.clock_event, changed]
    if reverse:
        notices.reverse()
    for event in notices:
        rig.host.post(event)
    rig.drive(lambda: len(rig.facts(c.CLOCK_NOTICE)) == 2)
    assert_absent(rig, (CLOCK_SOURCE,))
    rig.host.post(rig.boot_input)
    rig.drive(lambda: len(rig.facts(CLOCK_SOURCE)) == 2)
    raw = rig.facts(c.CLOCK_NOTICE)
    assert Counter(canonical(fact.value) for fact in raw) == Counter(
        canonical(wire(event.declaration)) for event in notices)
    issued = [assert_k1_source_for_notice(rig, fact) for fact in raw]
    assert {canonical(fact.value) for fact in issued} == {
        canonical(wire(rig.clock_event.declaration)), canonical(wire(changed.declaration))}
    # Exercise a genuine Wg if the public host offers it; a blocked Wg is also
    # legal here. In either case no new clock-dependent event may be issued.
    rig.host.run_until(lambda _status: False, timeout=0.02)
    qgen = rig.facts(c.CANDIDATE_REQUEST)
    if qgen:
        work_id = qgen[0].value["desc"]["work_id"]
        callbacks = [body for key, body in rig.launcher.attempts if key == work_id]
        assert len(callbacks) <= 1
        if callbacks:
            callbacks[0]()
            rig.drive(lambda: any(fact.value["work"] == work_id for fact in rig.facts(c.WORK_REPORT)))
    rig.settle_steps()
    assert_absent(rig, (CONTEXT, CLOCK, contract("sui.f.route_config"), c.EVALUATION_REQUESTED, c.PREPARED))


def test_k1_equal_notices_keep_two_receipts_without_a_false_clock_conflict(make_rig):
    """Paper:330,3442 K1. Bug: reject every second notice or coalesce identical Posts.

    Legal contrast to the resolution_s conflict: same contents, two actual
    notices, one causal source per notice, and a real F-a FProblem from Ep.
    """
    rig = make_rig(auto_boot=False, ticking=True)
    rig.host.post(rig.clock_event)
    rig.host.post(rig.clock_event)
    rig.drive(lambda: len(rig.facts(c.CLOCK_NOTICE)) == 2)
    assert_absent(rig, (CLOCK_SOURCE,))
    rig.host.post(rig.boot_input)
    rig.drive(lambda: len(rig.facts(CLOCK_SOURCE)) == 2)
    notices = rig.facts(c.CLOCK_NOTICE)
    assert notices[0].cid != notices[1].cid
    assert notices[0].value == notices[1].value == wire(rig.clock_event.declaration)
    issued = [assert_k1_source_for_notice(rig, notice) for notice in notices]
    assert issued[0].cid != issued[1].cid
    assert_ep_is_prepared_from_k1_source(rig, {fact.cid for fact in issued})


@pytest.mark.parametrize("order", (("Q", "M"), ("Q",), ("M", "Q")),
                         ids=("model_order", "proper_subset", "reordered"))
def test_model_operations_require_the_whole_model_order_with_matching_continuation(make_rig, order):
    """Paper:1947,3429,3432 H6/H9. Bug: omit the model-operations meaning check.

    Both input_order and continuation follow the returned order. A continuation
    mismatch must not reject the negative before the omitted H9 check is used.
    The saved model itself remains Q,M in every case.
    """
    rig = make_rig()
    sent = []
    def action(work, ctx):
        original = rig.workers.candidate(work)
        assert original.input_order == ("Q", "M")
        changed = replace(original, input_order=order, continuation=f.FContinuation(after=tuple(
            f.ContinuationAfter(candidate=name, policy=None) for name in order)))
        assert tuple(item.candidate for item in changed.continuation.after) == changed.input_order
        if order != original.input_order:
            assert plain(changed) != plain(original)
        event = rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": plain(changed)})))
        sent.append(event)
        rig.workers.post(ctx, event)
    rig.workers.overrides["candidate_generation"] = action
    work = rig.run_stage("candidate_generation")
    raw = raw_for(rig, work.desc.work_id)
    assert len(raw) == 1 and raw[0].value == wire(sent[0])
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    if order == ("Q", "M"):
        rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
        assert rig.one(CG).value == raw[0].value["outcome"]["value"]["value"]["value"]
        assert rig.one(c.EVALUATION_REQUESTED).value["desc"]["args"]["input"]["candidates"] == rig.one(CG).cid
    else:
        assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))


@pytest.mark.parametrize("changed_input", (False, True), ids=("requested_input", "different_method"))
def test_ep_real_issue_from_same_reader_must_match_eq_input(make_rig, changed_input):
    """Paper:343,1150,2334,3431 H8. Bug: compare issue bytes/budget but omit EQ input.

    The negative is a genuinely issued NoDecision for another method. It uses
    the same reader, registry, compiler and prepare budget, and its reported bytes
    match its own live issue. Regular NoDecision is legal for Ep, so that outcome
    alone is not a reason to reject the reply; its different input is the reason.
    """
    rig = make_rig()
    seen = {}
    def action(work, ctx):
        requested = work.desc.args.input
        normal = rig.workers.prepare(work, ctx)
        assert isinstance(normal.value, f.FProblem)
        other_input = replace(requested, method=contract("stage2.other_evaluation"))
        artifact = rig.workers.prepare(work, ctx, request=other_input) if changed_input else normal
        value = json.loads(artifact.canonical_bytes)
        normal_value = json.loads(normal.canonical_bytes)
        assert value["environment"] == normal_value["environment"]
        assert value["compiler"] == normal_value["compiler"] and value["calls"] == normal_value["calls"]
        assert value["input"]["value"] == plain(other_input if changed_input else requested)
        if changed_input:
            assert isinstance(artifact.value, f.NoDecision)
            assert value["input"] != normal_value["input"]
        seen["artifact"] = artifact
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), artifact)
    rig.workers.overrides["evaluation_prepare"] = action
    rig.through("evaluation_prepare")
    work = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    assert raw_for(rig, work.desc.work_id)[0].value["outcome"]["value"]["value"] == json.loads(
        seen["artifact"].canonical_bytes)
    if changed_input:
        assert_absent(rig, (MATH, c.PREPARED, c.DRAW_REQUESTED))
    else:
        rig.drive(lambda: bool(rig.facts(c.DRAW_REQUESTED)))
        pr = rig.one(c.PREPARED)
        assert rig.one(MATH, cid=pr.value["artifact"]).value == json.loads(seen["artifact"].canonical_bytes)


@pytest.mark.parametrize("fresh_budget", (False, True), ids=("issued_ep_prefix", "fresh_prepare_other_budget"))
def test_ee_real_issue_must_continue_the_original_prepare_calls(make_rig, fresh_budget):
    """Paper:345,1152,3426,3428,3431 H3/H5/H8. Bug: ignore the prepare-call prefix.

    Re-prepare the same FFactsRequest with a different preparation budget and
    the SAME Ee reader, then evaluate the real requested DF with the requested
    Ee budget. The fresh problem_key is equal; its genuine call prefix differs.
    """
    rig = make_rig()
    seen = {}
    def action(work, ctx):
        original, reader = ctx.prepared(), ctx.reader()
        assert original is not None and reader is not None
        ep_args = next(w.desc.args for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
        request = ep_args.input
        prepared = original
        if fresh_budget:
            other_budget = replace(ep_args.budget, max_terms=ep_args.budget.max_terms + 7)
            prepared = ff.prepare_f_from_facts(reader, fixed_parents=request.fixed_parents,
                model_ref=request.model, candidate_ref=request.candidates,
                preference_refs=request.preferences, scope_request=request.scope,
                context_ref=request.context, registry=rig.registry,
                method=request.method, budget=other_budget)
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.problem_key == original.value.problem_key
        prefix = json.loads(prepared.canonical_bytes)["calls"]
        original_prefix = json.loads(original.canonical_bytes)["calls"]
        assert (prefix != original_prefix) == fresh_budget
        artifact = ff.evaluate_f_from_draw(prepared, work.desc.args.draw,
            reader=reader, budget=work.desc.args.budget)
        assert isinstance(artifact.value, f.Selected)
        value = json.loads(artifact.canonical_bytes)
        assert value["input"]["value"] == plain(request)
        assert value["calls"][:len(prefix)] == prefix
        binds = [call for call in value["calls"] if call["op"] == "bind_draw"]
        assert binds and all(call["args"]["draw"] == work.desc.args.draw for call in binds)
        seen["artifact"] = artifact
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), artifact)
    rig.workers.overrides["evaluation"] = action
    rig.through("evaluation")
    work = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation")
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    if fresh_budget:
        assert_absent(rig, (c.EVALUATED, c.SELECTION))
    else:
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        ev = rig.one(c.EVALUATED)
        assert rig.one(MATH, cid=ev.value["artifact"]).value == json.loads(seen["artifact"].canonical_bytes)
        assert rig.one(c.SELECTION).value == {"evaluated": ev.cid}


@pytest.mark.parametrize("draw_case", ("requested", "other_saved_fact"))
def test_ee_reader_allows_requested_df_and_rejects_saved_df_outside_closure(make_rig, draw_case):
    """Paper:3428 H5,3431 H8; F-a:388. Bug: expose a saved DF outside Ee's closure.

    A second DF is stored through the public Ledger before Ee enters. This does
    not authorize expanding Desc's frozen boundary/input_points. The SAME public
    reader must reject that actual point and read the requested DF exactly.
    Both cases then evaluate the requested DF and reach selection, so rejecting
    every DF cannot satisfy the test. No alternate-DF artifact is fabricated.
    """
    rig = make_rig()
    rig.through("selection_draw")
    requested_df = rig.one(DF)
    alternate = None
    if draw_case == "other_saved_fact":
        value = dict(requested_df.value)
        value["stream_id"] += ":independent-test-draw"
        value["value"] = {"u": [3, 4]}
        record = rig.record(Observed(route="draw", content=Payload.json(value), contract=DF,
            caused_by=None, source_id=None, source_time_ns=None, received_ns=rig.clock.mono_ns()))
        alternate = rig.ledger.append(record, requested_df.parents).cid
        assert alternate != requested_df.cid and rig.one(DF, cid=alternate).value == value
    seen = {}
    def action(work, ctx):
        reader, prepared = ctx.reader(), ctx.prepared()
        assert reader is not None and prepared is not None
        allowed = closure(rig, set(work.desc.numerical_view.boundary) | set(work.desc.input_points))
        available_draws = {entry.cid for entry in reader.entries()
                           if reader.record(entry.cid).body.contract == DF}
        assert work.desc.args.draw == requested_df.cid and requested_df.cid in available_draws
        assert requested_df.cid in allowed
        assert reader.record(requested_df.cid) == rig.read_stored(requested_df.cid)[2]
        if alternate is not None:
            assert alternate not in allowed
            assert alternate not in available_draws
            with pytest.raises(KeyError):
                reader.record(alternate)
            seen["alternate_rejected"] = True
        artifact = ff.evaluate_f_from_draw(prepared, requested_df.cid,
            reader=reader, budget=work.desc.args.budget)
        assert isinstance(artifact.value, f.Selected)
        value = json.loads(artifact.canonical_bytes)
        assert any(call["op"] == "bind_draw" and call["args"]["draw"] == requested_df.cid
                   for call in value["calls"])
        seen["artifact"] = artifact
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), artifact)
    rig.workers.overrides["evaluation"] = action
    rig.run_stage("evaluation")
    if draw_case == "other_saved_fact":
        assert seen["alternate_rejected"]
        assert rig.one(DF, cid=alternate).value == value
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    ev = rig.one(c.EVALUATED)
    assert rig.one(MATH, cid=ev.value["artifact"]).value == json.loads(seen["artifact"].canonical_bytes)
    assert rig.one(c.SELECTION).value == {"evaluated": ev.cid}


DRAW_VALUE_CASES = (
    ("zero", {"u": [0, 1]}, True),
    ("half", {"u": [1, 2]}, True),
    ("one", {"u": [1, 1]}, False),
    ("negative", {"u": [-1, 2]}, False),
    ("wrong_key", {"v": [1, 2]}, False),
    ("not_rational", {"u": "x"}, False),
)


@pytest.mark.parametrize("label,value,legal", DRAW_VALUE_CASES, ids=[row[0] for row in DRAW_VALUE_CASES])
def test_draw_value_contract_is_checked_before_saving_df(make_rig, label, value, legal):
    """Paper:344,799,2333,2339,3427; F-a:388. Bug: persist DF before validating {u}, 0<=u<1.

    Check DF absence immediately after D, before Ee or F-a can reject a bad draw.
    Raw value and T remain exact. Both boundary zero and interior half are legal.
    """
    rig = make_rig()
    def action(work, ctx):
        rig.workers.post(ctx, fb.DrawReturned(work=work.desc.work_id, outcome=fb.DrawValue(value=value)))
    rig.workers.overrides["selection_draw"] = action
    rig.through("selection_draw")
    work = next(w for w in rig.workers.entries if w.desc.purpose == "selection_draw")
    raw = raw_for(rig, work.desc.work_id)
    assert len(raw) == 1 and raw[0].value == {
        "work": work.desc.work_id, "outcome": {"kind": "value", "value": value}}
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "value"
    assert t.value["returned"] == {"kind": "draw_value", "value": value}
    if legal:
        rig.drive(lambda: bool(rig.facts(c.WORK_REQUESTED)))
        df = rig.one(DF)
        assert df.value == {"generator": plain(work.desc.method),
            "stream_id": work.desc.args.stream_id, "request": plain(work.desc.args.request), "value": value}
        rig.run_stage("evaluation")
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert rig.workers.issued["evaluation"].value.choice.id == ("Q" if label == "zero" else "M")
    else:
        assert_absent(rig, (DF, c.DRAW_UNKNOWN, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))


@pytest.mark.parametrize("measurement", (None, contract("sui.f.simulated_clock")), ids=("undeclared", "declared"))
def test_context_requires_a_declared_clock_measurement_contract(make_rig, measurement):
    """Paper:3424,3440 H1 addition. Bug: build o/j and EQ despite measurement=None.

    The same saved model, candidates and source metadata are used in both cases;
    only ClockDeclared.measurement differs. Pending is checked as presentation
    after CG exists, never used as the oracle that decides whether work runs.
    """
    rig = make_rig(auto_boot=False)
    notice = replace(rig.clock_event, declaration=replace(rig.clock_event.declaration, measurement=measurement))
    rig.host.post(notice)
    rig.host.post(rig.boot_input)
    rig.drive(lambda: bool(rig.facts(c.CANDIDATE_REQUEST)))
    rig.through("candidate_generation")
    cg = rig.one(CG)
    assert cg.value["input_order"] == ["Q", "M"]
    assert rig.one(c.CLOCK_NOTICE).value["measurement"] == plain(measurement)
    if measurement is None:
        assert_absent(rig, (CLOCK, CONTEXT, c.EVALUATION_REQUESTED, c.PREPARED))
        pending = [row for row in rig.host.window.status().pending
                   if row.reason == "context:clock_contract" and row.target is not None]
        assert pending, "the missing clock contract lost its target"
        for row in pending:
            if isinstance(row.target, str):
                rig.read_stored(row.target)  # the named saved target really exists
            else:
                assert isinstance(row.target, fb.Unsaved) and row.target.plan
    else:
        rig.run_stage("evaluation_prepare")
        assert isinstance(rig.workers.issued["evaluation_prepare"].value, f.FProblem)
        assert rig.one(c.PREPARED).value["request"] == rig.one(c.EVALUATION_REQUESTED).cid
        assert not any(row.reason == "context:clock_contract" for row in rig.host.window.status().pending)


@pytest.mark.parametrize("clash", (False, True), ids=("legal", "ep_failure_after_d_launch"))
def test_fb2_r01_deferred_draw_rechecks_upstream_clash_at_entry(make_rig, clash):
    """Paper:864,3447 FB2-R01. Bug: enter checks only a claimed, unused start token.

    Hold the real host launch callback after PR and D are saved. Only the second
    Ep report differs between cases; PR, D, claim and callback stay identical.
    Entry attempts are recorded at the actual public ctx.enter(), not inferred
    from launch/status. A rejected entry must remain absent from drain.
    """
    rig = make_rig()
    rig.through("evaluation_prepare")
    pr, draw = rig.one(c.PREPARED), rig.one(c.DRAW_REQUESTED)
    body = rig.callback("selection_draw")
    wid = draw.value["desc"]["work_id"]
    assert [key for key, _ in rig.launcher.attempts].count(wid) == 1
    assert not [w for w in rig.workers.entries if w.desc.work_id == wid]
    assert not [attempt for attempt in rig.workers.entry_attempts if attempt[0] == wid]
    ep = next(w for w in rig.workers.entries if w.desc.purpose == "evaluation_prepare")
    if clash:
        failure = rig.workers.finished(ep, fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="post_launch_clash", content={"code": 901}, readings=(), basis=())))
        rig.workers.post(rig.workers.contexts["evaluation_prepare"], failure)
        rig.drive(lambda: len(raw_for(rig, ep.desc.work_id)) == 2)
        rig.settle_steps()
        assert any(raw.value == wire(failure) for raw in raw_for(rig, ep.desc.work_id))
        assert terminal(rig, ep).value["first_receipt"] == pr.value["report"]
        assert all(w.desc.work_id != wid for w in rig.host.window.drain())
    body()
    rig.settle_steps()
    assert [result for key, result in rig.workers.entry_attempts if key == wid] == [not clash]
    assert len([w for w in rig.workers.entries if w.desc.work_id == wid]) == int(not clash)
    sent_draws = [event for event, _ in rig.workers.sent
                  if isinstance(event, fb.DrawReturned) and event.work == wid]
    if clash:
        assert sent_draws == []
        assert_absent(rig, (c.DRAW_REPORT, DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
        row, = (row for row in rig.host.window.status().works if row.work_id == wid)
        assert row.phase == "pending" and not row.startable
        assert all(w.desc.work_id != wid for w in rig.host.window.drain())
    else:
        assert len(sent_draws) == 1 and wire(sent_draws[0].outcome) == {
            "kind": "value", "value": {"u": [1, 4]}}
        rig.drive(lambda: bool(rig.facts(DF)))
        assert rig.one(DF).value["value"] == {"u": [1, 4]}
        rig.run_stage("evaluation")
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert rig.one(c.PREPARED) == pr and rig.one(c.DRAW_REQUESTED) == draw
    assert [key for key, _ in rig.launcher.attempts].count(wid) == 1


@pytest.mark.parametrize("bind_only", (False, True), ids=("selected", "intermediate_froot"))
def test_fb2_r02_only_evaluation_result_types_can_authorize_ev(make_rig, bind_only):
    """Paper:345,798-800,1970,3448 FB2-R02; F-a:388. Bug: accept any genuine issued type.

    Both branches use ctx.prepared(), the requested DF and the SAME Ee reader
    and budget. Return the genuine issue's exact bytes, never a hand-edited
    claim. The legal branch evaluates; the negative only binds to produce FRoot.
    The shortage target may retain the original comparison request; require a
    real target tied to this work's ancestry/report, not specifically the Ee request.
    Ep in this single-pass fixture has no DF in its frozen reader, so it cannot
    issue an FRoot there through bind_f_draw; this is not an Ep-type counterexample.
    """
    rig = make_rig()
    rig.through("selection_draw")
    _, ep_reader = rig.workers.inputs["evaluation_prepare"]
    assert not [entry for entry in ep_reader.entries()
                if ep_reader.record(entry.cid).body.contract == DF]
    seen = {}
    def action(work, ctx):
        prepared, reader = ctx.prepared(), ctx.reader()
        assert prepared is not None and reader is not None
        args = work.desc.args
        issue = (ff.bind_f_draw(prepared, args.draw, reader=reader, budget=args.budget)
                 if bind_only else ff.evaluate_f_from_draw(prepared, args.draw,
                     reader=reader, budget=args.budget))
        assert isinstance(issue.value, f.FRoot if bind_only else f.Selected)
        value, original = json.loads(issue.canonical_bytes), json.loads(prepared.canonical_bytes)
        assert value["claim"]["type"] == ("FRoot" if bind_only else "Selected")
        assert value["input"] == original["input"]
        assert value["calls"][:len(original["calls"])] == original["calls"]
        binds = [call for call in value["calls"] if call["op"] == "bind_draw"]
        assert len(binds) == 1
        assert binds[0]["args"]["draw"] == args.draw
        assert binds[0]["args"]["budget"] == plain(args.budget)
        if bind_only:
            assert value["calls"] == original["calls"] + binds
        seen["value"] = value
        rig.workers.post(ctx, rig.workers.finished(work,
            fb.WorkOutputs(outputs=f.ContractValue(contract=MATH, value=value))), issue)
    rig.workers.overrides["evaluation"] = action
    work = rig.run_stage("evaluation")
    raw, = raw_for(rig, work.desc.work_id)
    assert raw.value["outcome"]["value"] == {"contract": plain(MATH), "value": seen["value"]}
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    if bind_only:
        assert_absent(rig, (c.EVALUATED, c.SELECTION))
        pending = [row for row in rig.host.window.status().pending
                   if row.reason == "artifact:type" and row.target is not None]
        assert pending
        related = closure(rig, (work.request, raw.cid))
        for row in pending:
            if isinstance(row.target, str):
                rig.read_stored(row.target)
                assert row.target in related
            else:
                assert isinstance(row.target, fb.Unsaved) and row.target.plan
    else:
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        ev = rig.one(c.EVALUATED)
        assert rig.one(MATH, cid=ev.value["artifact"]).value == seen["value"]
        assert rig.one(c.SELECTION).value == {"evaluated": ev.cid}
        assert not any(row.reason == "artifact:type" for row in rig.host.window.status().pending)


@pytest.mark.parametrize("stage", ("evaluation_prepare", "selection_draw", "evaluation"))
def test_fb2_r03_decided_inputs_include_used_record_refs_but_not_x_only_roots(make_rig, stage):
    """Paper:2290-2292,3425,3441,3449 FB2-R03. Bug: omit outer inputs or copy fixed X.

    A real Received head is saved before o. It belongs to fixed X, but is not
    used by EQ and must not become a Decided input. Compare Record Refs resolved
    from actual stored Points, not the Points themselves or status. Context can
    be both a fixed root and a used input; exclude X-only roots, not that context.
    H2:3441 limits this legal stage-2 path to empty preferences.
    """
    rig = make_rig()
    event = received(b"R03 unused numerical root", claims={"fixture": "R03-X"})
    rig.host.post(event)
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    sentinel = rig.one(c.RECEIVED)
    rig.through("evaluation")
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    fact = rig.request(stage)
    body = rig.read_stored(fact.cid)[2].body
    assert isinstance(body, Decided)
    work = next(w for w in rig.workers.entries if w.desc.purpose == stage)
    desc = work.desc
    points = {desc.process.declaration, desc.reader} | set(desc.input_points)
    points |= {trigger.point for trigger in desc.trigger}
    if stage == "evaluation_prepare":
        request = desc.args.input
        assert request.preferences == ()
        points |= {request.model, request.candidates, request.context} | set(request.preferences)
        assert sentinel.cid in closure(rig, request.fixed_parents)
        excluded = set(request.fixed_parents) - points
        assert sentinel.cid in excluded
        assert not ({rig.read_stored(point)[2].id for point in excluded} & set(body.inputs))
    elif stage == "selection_draw":
        points.add(desc.args.prepared)
    else:
        points |= {desc.args.evaluation_request, desc.args.prepared, desc.args.draw}
    assert None not in points
    expected = {rig.read_stored(point)[2].id for point in points}
    assert expected <= set(body.inputs), (stage, expected - set(body.inputs))
    assert rig.read_stored(desc.process.declaration)[2].body.contract == c.BOOT_DECLARATION
    assert rig.read_stored(desc.reader)[2].body.contract == ORIGIN
    assert rig.workers.issued["evaluation"].value.choice.id == "Q"


@pytest.mark.parametrize("published,arm_stage,next_stage", (
    (c.PREPARED, "evaluation_prepare", "selection_draw"),
    (DF, "selection_draw", "evaluation")), ids=("PR_to_D", "DF_to_Ee"))
def test_fb2_r04_publish_owns_unsaved_successor_then_resolves_same_work(make_rig, published, arm_stage, next_stage):
    """Paper:3431,3450 FB2-R04. Bug: create a successor row only after predecessor SV.

    Stop exactly at the predecessor's first failing write. Its Publish already
    requires an Unsaved successor, while no request/launch/entry is authorized.
    Recovery must resolve that same public WorkId and genuinely run it once.
    """
    rig = make_rig()
    for stage in ORDER[:ORDER.index(arm_stage)]:
        rig.run_stage(stage)
    rig.ledger.cut = (published, "before")
    with pytest.raises(OSError, match="stage2 before write"):
        rig.run_stage(arm_stage)
    assert len(rig.ledger.hit) == 1
    prepared = rig.ledger.hit[0][2]
    assert prepared.cid not in dict(rig.entry_store.load())
    assert isinstance(rig.workers.issued["evaluation_prepare"].value, f.FProblem)
    row, = (row for row in rig.host.window.status().works if row.purpose == next_stage)
    assert isinstance(row.request, fb.Unsaved) and row.request.plan
    assert row.phase == "pending" and not row.startable
    wid = row.work_id
    assert_absent(rig, (REQUESTS[next_stage],))
    assert all(work.desc.work_id != wid for work in rig.host.window.drain())
    assert not [key for key, _ in rig.launcher.attempts if key == wid]
    assert not [work for work in rig.workers.entries if work.desc.work_id == wid]
    rig.settle_steps()
    saved = rig.one(published, cid=prepared.cid)
    assert saved.value == prepared.record.body.content.as_json()
    request = rig.request(next_stage)
    recovered, = (row for row in rig.host.window.status().works if row.purpose == next_stage)
    assert recovered.work_id == wid == request.value["desc"]["work_id"]
    assert recovered.request == request.cid and recovered.phase == "pending" and recovered.startable
    offered, = (work for work in rig.host.window.drain() if work.desc.work_id == wid)
    assert offered.request == request.cid
    assert {trigger.point for trigger in offered.desc.trigger} == {saved.cid}
    assert len([item for item in rig.ledger.preparations if item.cid == prepared.cid]) == 1
    assert all(item == prepared for item in rig.ledger.writes if item.cid == prepared.cid)
    rig.run_stage(next_stage)
    if next_stage == "selection_draw":
        rig.run_stage("evaluation")
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert [result for key, result in rig.workers.entry_attempts if key == wid] == [True]
    assert len([work for work in rig.workers.entries if work.desc.work_id == wid]) == 1


@pytest.mark.parametrize("branch,reason", (
    ("legal", None), ("method_args", "eq:method"),
    ("clock_contract", "context:clock_contract"), ("preferences", "eq:preferences")))
def test_fb2_r05_post_cg_usage_gap_preserves_original_comparison_purpose(make_rig, branch, reason):
    """Paper:1951,1970,1973,3440-3441,3451 FB2-R05. Bug: CG success erases residual pG.

    Change only one use condition from a legal Boot. CG and its genuine Wg
    terminal remain saved; the named shortage must keep the original target,
    reader and process, handled=True/unmet=True, including after M2 rebuild.
    """
    rig = make_rig(auto_boot=False)
    boot_event, clock_event = rig.boot_input, rig.clock_event
    if branch == "method_args":
        initial = boot_event.declaration.initial
        method = replace(initial.value.method, args={"unsupported": 1})
        boot_event = replace(boot_event, declaration=replace(boot_event.declaration,
            initial=replace(initial, value=replace(initial.value, method=method))))
    elif branch == "clock_contract":
        clock_event = replace(clock_event, declaration=replace(clock_event.declaration, measurement=None))
    elif branch == "preferences":
        # Reuse only a public F-a fixture's saved preference body, not its reader.
        case = FactsCase(finite_world("FA01")[0], name="fb2-r05-preference")
        case.style()
        pref_body = case.ledger.record(case.preferences[0]).body
        pref = rig.ledger.append(rig.record(pref_body, RefKind.PREFERENCE, Role.MODEL),
                                rig.ledger.heads()).cid
        assert rig.read_stored(pref)[2].body == pref_body
    rig.host.post(clock_event)
    rig.host.post(boot_event)
    rig.drive(lambda: bool(rig.facts(c.CANDIDATE_REQUEST)))
    work = rig.run_stage("candidate_generation")
    cg, origin = rig.one(CG), rig.one(ORIGIN)
    assert cg.value["input_order"] == ["Q", "M"]
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    if reason is None:
        rig.run_stage("evaluation_prepare")
        assert isinstance(rig.workers.issued["evaluation_prepare"].value, f.FProblem)
        assert not any(row.unmet and row.target == work.request
                       for row in rig.host.window.status().purposes)
        assert not any(row.reason in {"eq:method", "eq:preferences", "context:clock_contract"}
                       for row in rig.host.window.status().pending)
        return
    assert_absent(rig, (c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))
    def observe_residual():
        status = rig.host.window.status()
        assert any(row.reason == reason and row.target == work.request for row in status.pending)
        purposes = [row for row in status.purposes
                    if row.target == work.request and row.reader == origin.cid
                    and row.process == work.desc.process and row.role == "compare"]
        assert purposes
        assert all(row.handled and row.unmet and row.obligation is not None for row in purposes)
        return purposes
    before = observe_residual()
    snapshot = rig.storage_snapshot()
    rig.host.rebuild_window()
    assert rig.storage_snapshot() == snapshot
    assert observe_residual() == before
    rig.settle_steps()
    assert observe_residual() == before
    assert rig.one(CG) == cg
    assert_absent(rig, (c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))


@pytest.mark.parametrize("arrival", ("during_o_retry", "after_eq"))
def test_fb2_r06_fixed_x_excludes_received_saved_during_o_write_retry(make_rig, arrival):
    """Paper:410,3424,3439,3452 FB2-R06. Bug: freeze X from heads when creating EQ.

    A one-shot OSError occurs after o's prepare but before its write. The actual
    write log must show Received saved before o's retry; otherwise this fixture
    cannot discriminate that bug. Legal control receives only after saved EQ.
    Both Ep/Ee readers and artifact requests must keep the frozen roots.
    """
    rig = make_rig(ticking=True)
    if arrival == "during_o_retry":
        rig.ledger.cut = (CLOCK, "before")
        with pytest.raises(OSError, match="stage2 before write"):
            rig.run_stage("candidate_generation")
        assert len(rig.ledger.hit) == 1 and not rig.facts(CLOCK)
        original = rig.ledger.hit[0][2]
        x = set(rig.ledger.heads())
        assert_absent(rig, (CONTEXT, c.EVALUATION_REQUESTED))
    else:
        rig.run_stage("candidate_generation")
        rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
        saved_eq = rig.one(c.EVALUATION_REQUESTED)
    event = received(b"R06 late during o retry", claims={"fixture": "R06", "arrival": arrival})
    rig.host.post(event)
    rig.drive(lambda: bool(rig.facts(c.RECEIVED)))
    rig.settle_steps()
    late, eq = rig.one(c.RECEIVED), rig.one(c.EVALUATION_REQUESTED)
    assert late.value == wire(event)
    fixed = set(eq.value["desc"]["args"]["input"]["fixed_parents"])
    assert late.cid not in fixed and late.cid not in closure(rig, fixed)
    if arrival == "during_o_retry":
        context = rig.one(CONTEXT)
        assert context.value["observation_reading"] == original.cid
        assert fixed == front(rig, x | events_for(rig, (context.cid,)))
        writes = rig.ledger.writes
        attempts = [i for i, item in enumerate(writes) if item.cid == original.cid]
        received_write, = (i for i, item in enumerate(writes) if item.cid == late.cid)
        assert len(attempts) >= 2 and attempts[0] < received_write < attempts[1]
        assert all(writes[i] == original for i in attempts)
        assert len([item for item in rig.ledger.preparations if item.cid == original.cid]) == 1
    else:
        assert eq == saved_eq
    for stage in ("evaluation_prepare", "selection_draw", "evaluation"):
        rig.run_stage(stage)
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    for stage in ("evaluation_prepare", "evaluation"):
        desc, reader = rig.workers.inputs[stage]
        assert late.cid not in closure(rig, desc.numerical_view.boundary | desc.input_points)
        with pytest.raises(KeyError):
            reader.record(late.cid)
        artifact = json.loads(rig.workers.issued[stage].canonical_bytes)
        assert set(artifact["input"]["value"]["fixed_parents"]) == fixed
    assert rig.workers.issued["evaluation"].value.choice.id == "Q"


REPORT_SAVE_BOUNDARIES = (
    ("before_body", False, False),
    ("after_body_commit", True, False),
    ("after_entry_commit", True, True),
    ("after_write", True, True),
)


@pytest.mark.parametrize("upstream,target", ENTRY_DEPENDENCIES,
    ids=[f"{a}_to_{b}" for a, b in ENTRY_DEPENDENCIES])
@pytest.mark.parametrize("boundary,body_present,point_present", REPORT_SAVE_BOUNDARIES,
    ids=[row[0] for row in REPORT_SAVE_BOUNDARIES])
@pytest.mark.parametrize("kind", ("failure", "equal"))
@pytest.mark.parametrize("entrance", ("enter_first", "drain_first"))
def test_fb2_r01_r3_report_commit_boundary_controls_entry_and_confirmation(
        make_rig, upstream, target, boundary, body_present, point_present, kind, entrance):
    """Paper:295,318,357,1924-1932,1973,3462 FB2-R01-R3, corrected 2026-10-20 20:1x.

    Bug: only a normally returned write can make a report visible to the guard.
    Fault exactly the second report, independently verify C and E, then invoke
    the FIRST public entrance without settle/status/drain/rebuild before it.
    Once an incompatible report is accepted, every storage boundary blocks as
    unchecked, including a missing point or an orphan body. C/E observations
    distinguish the injected boundaries, not permission to enter. Confirmation
    changes unchecked to conflict; it cannot retroactively authorize an entry.
    Equal reports at every boundary must remain a legal control. pG waits for
    confirmed conflict, and the identical preparation is retried on recovery.
    """
    rig = make_rig()
    normal_launch = rig.launcher.launch
    if entrance == "drain_first":
        def not_started_target(work_id, body):
            if any(fact.value["desc"]["work_id"] == work_id
                   for fact in rig.facts(REQUESTS[target])):
                rig.launcher.attempts.append((work_id, body))
                return "not_started"
            return normal_launch(work_id, body)
        rig.launcher.launch = not_started_target
    rig.through(ORDER[ORDER.index(target) - 1])
    request = rig.request(target)
    wid = request.value["desc"]["work_id"]
    if entrance == "enter_first":
        callback = rig.callback(target)
    else:
        offered, = (work for work in rig.host.window.drain() if work.desc.work_id == wid)
        assert offered.request == request.cid
    assert not [attempt for attempt in rig.workers.entry_attempts if attempt[0] == wid]
    launch_cutoff = len(rig.launcher.attempts)
    previous, second, issued, expected = additional_terminal(rig, upstream, kind)
    first_terminal = terminal(rig, previous)
    saved_request = rig.read_stored(request.cid)
    raw_contract = c.DRAW_REPORT if upstream == "selection_draw" else c.WORK_REPORT
    preparation_cutoff = len(rig.ledger.preparations)
    if boundary == "after_write":
        rig.ledger.cut = (raw_contract, "after")
        error = "stage2 after committed write"
    else:
        rig.ledger.store_cut = (raw_contract, boundary)
        error = "injected test store fault: " + boundary
    rig.workers.post(rig.workers.contexts[upstream], second, issued)
    with pytest.raises(OSError, match=error):
        rig.host.run_until(lambda _status: False, timeout=2)
    prepared, = (item for item in rig.ledger.preparations[preparation_cutoff:]
                 if item.record.body.contract == raw_contract
                 and item.record.body.content.as_json() == expected)
    if boundary == "after_write":
        assert rig.ledger.hit == [(raw_contract, "after", prepared)]
        assert rig.faults.observed == []
    else:
        assert rig.ledger.store_cut_hits == [(raw_contract, boundary, prepared)]
        assert rig.faults.observed == [boundary] and rig.faults.armed is None
    # C/E are the independent oracle; no window observation can confirm the slot.
    seal = entry_from_header(prepared.cid, prepared.header).seal
    assert (seal in set(rig.contents.seals())) == body_present
    assert (prepared.cid in dict(rig.entry_store.load())) == point_present
    if body_present:
        stored_body = rig.contents.get(seal)
        assert stored_body[0] == prepared.salt
    if point_present:
        assert rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record)
        assert rig.one(raw_contract, cid=prepared.cid).value == expected
    else:
        assert [fact.cid for fact in raw_for(rig, previous.desc.work_id)] == [
            first_terminal.value["first_receipt"]]
    assert terminal(rig, previous) == first_terminal
    blocked = kind == "failure"
    writes_at_cut = len(rig.ledger.writes)
    if entrance == "enter_first":
        callback()
        assert [ok for key, ok in rig.workers.entry_attempts if key == wid] == [not blocked]
        assert len([work for work in rig.workers.entries if work.desc.work_id == wid]) == int(not blocked)
        reports = [event for event, _ in rig.workers.sent if getattr(event, "work", None) == wid]
        assert len(reports) == int(not blocked)
    else:
        offered = [work for work in rig.host.window.drain() if work.desc.work_id == wid]
        assert [work.request for work in offered] == ([] if blocked else [request.cid])
        assert not [attempt for attempt in rig.workers.entry_attempts if attempt[0] == wid]
        assert len(rig.launcher.attempts) == launch_cutoff
    assert len(rig.ledger.writes) == writes_at_cut
    pending = rig.host.window.status().pending
    assert not any(row.kind == "conflict" for row in pending)
    if blocked:
        assert any(row.kind == "unchecked" and row.reason == "conflict:unconfirmed:" + upstream
                   and row.target is not None for row in pending)
        assert raw_for(rig, wid) == []
        assert not [event for event, _ in rig.workers.sent if getattr(event, "work", None) == wid]
        assert all(work.desc.work_id != wid for work in rig.host.window.drain())
    comparison_purposes(rig, unmet=False)
    # Confirmation is deliberately after the entrance and unchecked/pG observations.
    rig.launcher.launch = normal_launch
    rig.settle_steps()
    assert rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record)
    assert rig.one(raw_contract, cid=prepared.cid).value == expected
    assert all(item == prepared for item in rig.ledger.writes if item.cid == prepared.cid)
    assert len([item for item in rig.ledger.preparations if item.cid == prepared.cid]) == 1
    if body_present:
        assert rig.contents.get(seal) == stored_body
    assert terminal(rig, previous) == first_terminal
    assert rig.read_stored(request.cid) == saved_request
    pending = rig.host.window.status().pending
    assert not any(row.reason == "conflict:unconfirmed:" + upstream for row in pending)
    if kind == "failure":
        assert any(row.kind == "conflict" and row.target is not None for row in pending)
        comparison_purposes(rig, unmet=True)
        assert all(work.desc.work_id != wid for work in rig.host.window.drain())
        assert raw_for(rig, wid) == []
        forbidden = {"evaluation_prepare": (c.PREPARED, c.DRAW_REQUESTED),
                     "selection_draw": (DF, c.WORK_REQUESTED),
                     "evaluation": (c.EVALUATED, c.SELECTION)}[target]
        assert_absent(rig, forbidden)
    else:
        assert not any(row.kind == "conflict" for row in pending)
        comparison_purposes(rig, unmet=False)
        if entrance == "drain_first":
            rig.drive(lambda: any(key == wid for key, _ in rig.launcher.attempts[launch_cutoff:]))
            callback, = (body for key, body in rig.launcher.attempts[launch_cutoff:] if key == wid)
            callback()
        rig.drive(lambda: bool(raw_for(rig, wid)))
        assert [ok for key, ok in rig.workers.entry_attempts if key == wid] == [True]
        for stage in ORDER[ORDER.index(target) + 1:]:
            rig.run_stage(stage)
        rig.drive(lambda: bool(rig.facts(c.SELECTION)))
        assert rig.workers.issued["evaluation"].value.choice.id == "Q"
        comparison_purposes(rig, unmet=False)


READING_TERMINAL_PAIRS = (
    ("failure_success", "failure", "success", True),
    ("failure_equal", "failure", "equal", False),
    ("unknown_success", "unknown", "success", False),
    ("unknown_equal", "unknown", "equal", False),
    ("unknown_then_two_values", "unknown", "two_values", True),
    ("values_different", "value", "different", True),
    ("values_equal", "value", "equal", False),
)


@pytest.mark.parametrize("label,first_kind,later_kind,clash", READING_TERMINAL_PAIRS,
    ids=[row[0] for row in READING_TERMINAL_PAIRS])
@pytest.mark.parametrize("arrival", ("together", "late"))
def test_fb2_r08_first_terminal_remains_visible_separately_from_conflict(
        make_rig, label, first_kind, later_kind, clash, arrival):
    """Paper:357,417,1924-1932,1971-1973,3463 FB2-R08. Bug: clash erases meaning 3.

    Expected response comes from the actual FIRST Post and T, not pending/status.
    Failure then success keeps failure; value then a different value still has
    a none/generated reading. Equal duplicates are the nearest legal controls.
    Unknown plus one value is NOT a clash (357); unknown followed by TWO mutually
    different values supplies a real clash while the first response stays unknown.
    Late values preserve an already saved CG/EQ; simultaneous clashes create none.
    """
    rig = make_rig()
    reports = []
    def action(work, ctx):
        success, issue = rig.workers.normal(work, ctx)
        assert issue is None
        failure = rig.workers.finished(work, fb.WorkFailure(failure=fb.FailureInfo(
            failure_kind="R08_first_failure", content={"code": 908}, readings=(), basis=())))
        unknown = rig.workers.finished(work, fb.WorkUnknown(unknown=fb.UnknownInfo(
            reason="R08_first_unknown", basis=())))
        candidate = rig.workers.candidate(work)
        order = ("M", "Q")
        changed = replace(candidate, input_order=order, continuation=f.FContinuation(after=tuple(
            f.ContinuationAfter(candidate=name, policy=None) for name in order)))
        different = replace(success, outcome=fb.WorkOutputs(outputs=f.ContractValue(
            contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": plain(changed)})))
        first = {"failure": failure, "unknown": unknown, "value": success}[first_kind]
        later = {"success": [success], "equal": [first],
                 "different": [different], "two_values": [success, different]}[later_kind]
        reports.extend([first] + later)
        for event in reports if arrival == "together" else reports[:1]:
            rig.workers.post(ctx, event)
    rig.workers.overrides["candidate_generation"] = action
    work = rig.run_stage("candidate_generation")
    if arrival == "late":
        before = terminal(rig, work)
        saved = {fact.cid: rig.read_stored(fact.cid)
                 for ref in (CG, c.EVALUATION_REQUESTED) for fact in rig.facts(ref)}
        for event in reports[1:]:
            rig.workers.post(rig.workers.contexts["candidate_generation"], event)
        rig.drive(lambda: len(raw_for(rig, work.desc.work_id)) == len(reports))
        rig.settle_steps()
        assert terminal(rig, work) == before
        assert all(rig.read_stored(point) == original for point, original in saved.items())
    t = terminal(rig, work)
    observations = next(item for item in rig.workers.contexts["candidate_generation"].evidence().executions
                        if item.work_id == work.desc.work_id).reports
    ordered = sorted(observations, key=lambda item: (item.received_ns, item.envelope))
    assert len(ordered) == len(reports)
    actual = {fact.cid: fact.value for fact in raw_for(rig, work.desc.work_id)}
    assert [actual[item.point] for item in ordered] == [wire(event) for event in reports]
    assert t.value["first_receipt"] == ordered[0].point
    assert t.value["terminal_kind"] == ("outputs" if first_kind == "value" else first_kind)
    generation_saved = first_kind == "value" and (not clash or arrival == "late")
    if generation_saved:
        cg, eq = rig.one(CG), rig.one(c.EVALUATION_REQUESTED)
        assert cg.value["input_order"] == ["Q", "M"]
        assert eq.value["desc"]["args"]["input"]["candidates"] == cg.cid
    else:
        assert_absent(rig, (CG, c.EVALUATION_REQUESTED))
    assert_absent(rig, (c.PREPARED, DF, c.EVALUATED, c.SELECTION))
    status = rig.host.window.status()
    conflicts = [row for row in status.pending if row.kind == "conflict"]
    if clash:
        assert any(row.target == work.request for row in conflicts)
    else:
        assert conflicts == []
    comparison_purposes(rig, unmet=first_kind in ("failure", "unknown") or clash)
    targets = {work.request, t.cid} | {fact.cid for fact in rig.facts(CG)}
    readings = [row for row in status.readings if row.reader == work.desc.reader
                and (row.target in targets or t.cid in row.evidence.basis)]
    assert readings, "FB2-R08: meaning 3 vanished even though the first terminal is saved"
    expected_response = "none" if first_kind == "value" else first_kind
    assert all(row.response == expected_response and row.selected is None for row in readings)
    assert any(row.reached == ("generated" if generation_saved else "none") for row in readings)


@pytest.mark.parametrize("stage", ("candidate_generation", "evaluation_prepare", "evaluation"),
                         ids=("Wg_NoCandidates", "Ep_NoDecision", "Ee_NoDecision"))
@pytest.mark.parametrize("pair", ("clash", "equal"))
def test_fb2_r08_definite_empty_reply_survives_clash_without_new_publications(make_rig, stage, pair):
    """Paper:789,798,800,1926-1927,1966,1971-1973,2293,2297-2298,3431,3463 FB2-R08.

    Bug: return on Conflict before classifying the first NoCandidates/NoDecision.
    Accept both real Post envelopes without settle, before any artifact/PR/EV.
    Ep/Ee return genuine F-a NoDecision issues with their exact canonical bytes;
    only the second report changes to Failure. Wg's empty model legitimately
    returns NoCandidates; the second candidates branch is an incompatible claim,
    not evidence that the fixed model contains those operations.
    Equal must retain the same response and publish the legal artifact + PR/EV.
    NoCandidates has no CG/EQ successor even for equal (1966); Ep NoDecision has
    no D and Ee NoDecision has no selection (3431).
    """
    kwargs = ({"empty": True} if stage == "candidate_generation" else
              {"omit_implementation": contract("finite_option_proof")} if stage == "evaluation_prepare" else
              {"evaluate_budget": TINY_BUDGET})
    rig = make_rig(**kwargs)
    for previous in ORDER[:ORDER.index(stage)]:
        rig.run_stage(previous)
    math_before = {fact.cid: rig.read_stored(fact.cid) for fact in rig.facts(MATH)}
    logical = {"evaluation_prepare": c.PREPARED, "evaluation": c.EVALUATED}.get(stage)
    reports, issued = [], {}
    def action(work, ctx):
        first, artifact = rig.workers.normal(work, ctx)
        if stage == "candidate_generation":
            assert artifact is None
            assert rig.read_stored(rig.model_point)[2].body.content.as_json()["document"]["operations"] == []
            assert plain(first.outcome.outputs.value) == {"kind": "no_candidates", "value": {}}
        else:
            assert isinstance(artifact.value, f.NoDecision)
            assert artifact.value.attempt_id is None
            assert artifact.value.reason == ("algorithm_unavailable" if stage == "evaluation_prepare"
                                             else "budget_exhausted")
            assert plain(first.outcome.outputs.value) == json.loads(artifact.canonical_bytes)
            issued["artifact"] = artifact
        if pair == "equal":
            second, second_issue = first, artifact
        elif stage == "candidate_generation":
            order = tuple(operation["id"] for operation in finite_world("FA01")[0]["operations"])
            candidate = replace(rig.workers.candidate(work), input_order=order,
                continuation=f.FContinuation(after=tuple(
                    f.ContinuationAfter(candidate=name, policy=None) for name in order)))
            second = rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
                contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": plain(candidate)})))
            second_issue = None
        else:
            second = rig.workers.finished(work, fb.WorkFailure(failure=fb.FailureInfo(
                failure_kind="R08_after_regular_no_decision", content={"code": 910}, readings=(), basis=())))
            second_issue = None
        reports.extend([first, second])
        rig.workers.post(ctx, first, artifact)
        rig.workers.post(ctx, second, second_issue)
        observations = next(item for item in ctx.evidence().executions
                            if item.work_id == work.desc.work_id).reports
        ordered = sorted(observations, key=lambda item: (item.received_ns, item.envelope))
        assert len(ordered) == 2 and ordered[0].envelope < ordered[1].envelope
        for receipt, event in zip(ordered, reports):
            rig.host.window.accept(fb.Envelope(number=receipt.envelope,
                event=event, received_ns=receipt.received_ns))
        assert {fact.cid for fact in rig.facts(MATH)} == set(math_before)
        if logical is not None:
            assert_absent(rig, (logical,))
    rig.workers.overrides[stage] = action
    work = rig.run_stage(stage)
    rig.drive(lambda: len(raw_for(rig, work.desc.work_id)) == 2)
    rig.settle_steps()
    t = terminal(rig, work)
    observations = next(item for item in rig.workers.contexts[stage].evidence().executions
                        if item.work_id == work.desc.work_id).reports
    ordered = sorted(observations, key=lambda item: (item.received_ns, item.envelope))
    raw = {fact.cid: fact for fact in raw_for(rig, work.desc.work_id)}
    assert len(raw) == 2
    assert [raw[receipt.point].value for receipt in ordered] == [wire(event) for event in reports]
    assert t.value["first_receipt"] == ordered[0].point
    assert t.value["terminal_kind"] == "outputs"
    expected_output = {"contract": plain(c.CANDIDATE_GENERATION),
                       "value": {"kind": "no_candidates", "value": {}}} if logical is None else {
                           "contract": plain(MATH),
                           "value": json.loads(issued["artifact"].canonical_bytes)}
    assert t.value["returned"] == {"kind": "output", "value": expected_output}
    status = rig.host.window.status()
    readings = [row for row in status.readings if row.reader == work.desc.reader
                and (row.target in (work.request, t.cid) or t.cid in row.evidence.basis)]
    assert readings, "FB2-R08: Conflict hid the first definite empty reply"
    expected_response = "no_candidates" if logical is None else "no_decision"
    assert all(row.response == expected_response and row.selected is None for row in readings)
    conflicts = [row for row in status.pending if row.kind == "conflict"]
    if pair == "clash":
        assert any(row.target == rig.one(c.CANDIDATE_REQUEST).cid for row in conflicts)
        comparison_purposes(rig, unmet=True)
    else:
        assert conflicts == []
    current_math = {fact.cid for fact in rig.facts(MATH)}
    if pair == "clash" or logical is None:
        assert current_math == set(math_before)
        if logical is not None:
            assert_absent(rig, (logical,))
    else:
        record = rig.one(logical)
        artifact_point, = current_math - set(math_before)
        assert record.value == {"request": work.request, "report": ordered[0].point,
                                "artifact": artifact_point}
        assert rig.one(MATH, cid=artifact_point).value == expected_output["value"]
    assert all(rig.read_stored(point) == original for point, original in math_before.items())
    if stage == "candidate_generation":
        assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED,
                            DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
        comparison_purposes(rig, unmet=True)
    elif stage == "evaluation_prepare":
        assert_absent(rig, (c.DRAW_REQUESTED, DF, c.WORK_REQUESTED, c.EVALUATED, c.SELECTION))
    else:
        assert_absent(rig, (c.SELECTION,))
