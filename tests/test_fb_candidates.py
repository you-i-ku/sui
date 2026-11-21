"""K31/K31-a/Z58, F-b v1.16; K31-a :3552. No implementation bodies.

CandidateGenerator is resolved per case. Host/registry assertions use public
records, ports and declarations. Need/preparation/scripted-draw/evaluation still
use test capabilities where required by the existing fixture, as K31-a allows.
Only the model_operations declaration/implementation must come exclusively from
the native registry. Unsupported failure content is exactly a method name/version
pair. Both request-64 CGs are closed by K31-a. T retains its existing contract:
Compute output is returned.kind="output"; failure returns null and uses basis.
"""

from copy import deepcopy
from dataclasses import replace
from inspect import signature
import json
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u2
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role
from test_fb_skeleton import contract, desc, point, reading
from test_fb_stage1 import wire
from test_fb_stage2 import Stage2Rig, CG, ORIGIN, MATH, ORDER, terminal, raw_for, assert_absent
from test_fb_bundle import BundleLoopRig
from test_fb_belief import belief1_chain
from test_fb_loop import execution_for


GENERATOR = contract("sui.fb.model_operations")
IDENTITY = "sui.fb.first_loop/1:sui.fb.model_operations/1"
_UNCHANGED_OPERATIONS = object()


def candidate_type():
    assert hasattr(fb, "CandidateGenerator"), "K31 public API missing: fb.CandidateGenerator"
    return fb.CandidateGenerator


def native_registration():
    registry = u2.fb_registry_v1()
    declarations = [d for d in registry.declarations if d.kind == "generator" and d.ref == GENERATOR]
    implementations = [i for i in registry.implementations if i.kind == "generator" and i.ref == GENERATOR]
    assert len(declarations) == len(implementations) == 1, "K31 public registry missing: sui.fb.model_operations/1"
    return registry, declarations[0], implementations[0]


def request(model=None, *, method=GENERATOR, args=None, label="first"):
    d = desc("candidate_generation")
    model = model or point("candidate-model-" + label)
    d = replace(d, work_id="candidate-" + label, method=method, output_contract=c.CANDIDATE_GENERATION,
        args=fb.CandidateArgs(model=model, generator_args={} if args is None else args,
            basis=(point("basis-" + label),)))
    return fb.Compute(request=point("candidate-request-" + label), desc=d)


def model_bytes(order):
    return json.dumps({"document": {"operations": [{"id": name} for name in order]}}).encode()


class CandidatePort(fb.FWorkContext):
    """Caller-owned public port; model bytes exist only behind its read method."""
    def __init__(self, bodies, *, enter=True, read_error=None, unavailable=(), post_error=None):
        self.bodies, self.allowed, self.read_error = bodies, enter, read_error
        self.unavailable, self.post_error = set(unavailable), post_error
        self.trace, self.posts, self.readings, self.uses = [], [], [], []
        self.time = 100

    def enter(self): self.trace.append(("enter",)); return self.allowed
    def now(self):
        self.trace.append(("now",)); self.time += 7
        if len(self.readings) in self.unavailable:
            self.readings.append(None)
            raise RuntimeError("private clock exception text")
        value = reading()
        value = replace(value, reading=replace(value.reading, time_ns=self.time))
        self.readings.append(value)
        return value
    def read(self, cid):
        self.trace.append(("read", cid)); self.time += 100
        if self.read_error is not None: raise self.read_error
        self.uses.append(cid)
        return self.bodies[cid]
    def post(self, event, issued=None):
        self.trace.append(("post",)); self.posts.append((event, issued))
        if self.post_error is not None: raise self.post_error
    def reader(self): raise AssertionError("K31 model must be obtained through read, not reader")
    def prepared(self): raise AssertionError("candidate generation has no prepared artifact")
    def acquire(self): raise AssertionError("candidate generation is not measurement")
    def monitored(self, interval): raise AssertionError("candidate generation does not monitor")
    def evidence(self): return SimpleNamespace(uses=tuple(self.uses))


def completed(port, work):
    assert len(port.posts) == 1
    event, issued = port.posts[0]
    assert isinstance(event, fb.WorkFinished) and event.work == work.desc.work_id
    assert issued is None and len(port.readings) == 2
    for actual, observed in zip((event.started, event.finished), port.readings):
        if observed is None:
            assert actual == f.Unavailable(reason="clock_source_unavailable", basis=())
        else: assert actual == observed
    now_positions = [i for i, call in enumerate(port.trace) if call[0] == "now"]
    reads = [i for i, call in enumerate(port.trace) if call[0] == "read"]
    assert len(now_positions) == 2
    if reads: assert now_positions[0] < min(reads) <= max(reads) < now_positions[1]
    assert port.trace[-1] == ("post",)
    return event


def expected_declaration(work, order):
    return f.FCandidateDeclaration(model=work.desc.args.model, input_order=tuple(order),
        measure=f.CandidateMeasureRef(name="counting", version="1", args={}),
        generation=f.FCandidateGeneration(generator=work.desc.method, args=work.desc.args.generator_args,
            basis=work.desc.args.basis, draws=()),
        continuation=f.FContinuation(after=tuple(f.ContinuationAfter(candidate=name, policy=None) for name in order)))


def assert_failure(event, kind, error_type=None, *, method=None):
    assert isinstance(event.outcome, fb.WorkFailure)
    failure = event.outcome.failure
    assert failure.failure_kind == kind
    content = wire(failure.content)
    assert set(content) == ({"method"} if kind == "unsupported_method" else {"error_type"})
    if kind == "execution_error":
        assert isinstance(content["error_type"], str) and content["error_type"].isidentifier()
        if error_type is not None: assert content["error_type"] == error_type
    else:
        assert method is not None
        assert content == {"method": {"name": method.name, "version": method.version}}


def test_cand1_public_constructor_run_and_export():
    cls = candidate_type()
    assert "CandidateGenerator" in fb.__all__ and not signature(cls).parameters
    assert tuple(signature(cls.run).parameters) == ("self", "work", "ctx")


@pytest.mark.parametrize("order", [("A", "B"), ("B", "A"), ()], ids=["ordered", "reversed", "empty"])
def test_cand1_native_declaration_uses_model_order_public_read_and_distinct_clock_reads(order):
    worker = candidate_type()()
    work = request()
    port = CandidatePort({work.desc.args.model: model_bytes(order)})
    worker.run(work, port)
    event = completed(port, work)
    assert port.evidence().uses and set(port.evidence().uses) == {work.desc.args.model}
    assert event.started.reading.time_ns < event.finished.reading.time_ns
    assert isinstance(event.outcome, fb.WorkOutputs)
    assert event.outcome.outputs.contract == work.desc.output_contract
    assert wire(event.outcome.outputs.value) == ({"kind": "candidates", "value": wire(expected_declaration(work, order))}
        if order else {"kind": "no_candidates", "value": {}})


def test_cand1_output_uses_the_requested_contract():
    worker = candidate_type()()
    work = request()
    work = replace(work, desc=replace(work.desc, output_contract=contract("test.candidate_output")))
    port = CandidatePort({work.desc.args.model: model_bytes(("A", "B"))})
    worker.run(work, port)
    assert completed(port, work).outcome.outputs.contract == work.desc.output_contract


@pytest.mark.parametrize("mode", ["unknown-name", "unknown-version", "nonempty-args", "empty-list-args", "null-args"])
def test_cand1_unsupported_method_is_failure_not_empty_or_no_candidates(mode):
    worker = candidate_type()()
    work = request(method=contract("test.unknown") if mode == "unknown-name" else
        replace(GENERATOR, version="2") if mode == "unknown-version" else GENERATOR,
        args={"extra": 1} if mode == "nonempty-args" else {})
    if mode in ("empty-list-args", "null-args"):
        work = replace(work, desc=replace(work.desc, args=replace(work.desc.args,
            generator_args=[] if mode == "empty-list-args" else None)))
    port = CandidatePort({work.desc.args.model: model_bytes(("A", "B"))})
    worker.run(work, port)
    assert_failure(completed(port, work), "unsupported_method", method=work.desc.method)


@pytest.mark.parametrize("error", [OSError("private source message"), RuntimeError("private ledger message"),
    KeyError("private key"), ValueError("private parse message"), MemoryError("private allocation message")],
    ids=["OSError", "RuntimeError", "KeyError", "ValueError", "MemoryError"])
def test_cand1_model_read_exception_is_reported_not_raised_and_preserves_error_type(error):
    worker = candidate_type()()
    work = request()
    port = CandidatePort({}, read_error=error)
    worker.run(work, port)
    assert_failure(completed(port, work), "execution_error", type(error).__name__)


@pytest.mark.parametrize("body", [b"private non-JSON text", b"{}", b'{"document":{}}',
    b'{"document":{"operations":[{}]}}', b'{"document":{"operations":[{"id":1}]}}',
    b'{"document":{"operations":[{"id":"A"},{"id":"A"}]}}',
    b'{"document":{"operations":{}}}', b'{"document":{"operations":""}}'],
    ids=["non-json", "no-document", "no-operations", "no-id", "non-string-id", "duplicate-id",
         "operations-object", "operations-string"])
def test_cand1_malformed_model_is_execution_failure_not_a_fictitious_candidate_result(body):
    worker = candidate_type()()
    work = request()
    port = CandidatePort({work.desc.args.model: body})
    worker.run(work, port)
    assert_failure(completed(port, work), "execution_error")


@pytest.mark.parametrize("unavailable", [(), (0,), (1,), (0, 1)], ids=["both-readable", "start-missing", "finish-missing", "both-missing"])
@pytest.mark.parametrize("outcome", ["candidates", "unsupported", "read-error"])
def test_cand1_success_and_failures_read_two_clocks_and_only_replace_unavailable_side(unavailable, outcome):
    worker = candidate_type()()
    work = request(method=contract("test.unknown") if outcome == "unsupported" else GENERATOR)
    port = CandidatePort({work.desc.args.model: model_bytes(("A", "B"))}, unavailable=unavailable,
        read_error=RuntimeError("private ledger message") if outcome == "read-error" else None)
    worker.run(work, port)
    event = completed(port, work)
    if outcome == "unsupported": assert_failure(event, "unsupported_method", method=work.desc.method)
    elif outcome == "read-error": assert_failure(event, "execution_error", "RuntimeError")
    else: assert isinstance(event.outcome, fb.WorkOutputs)


@pytest.mark.parametrize("stage", ["measure_segment", "belief_update", "evaluation_prepare", "selection_draw", "evaluation", "wrong-work-class"])
def test_cand1_wrong_work_is_type_error_before_admission(stage):
    worker = candidate_type()()
    d = desc("candidate_generation" if stage == "wrong-work-class" else stage)
    kind = fb.MeasureSegment if stage in ("measure_segment", "wrong-work-class") else fb.Draw if stage == "selection_draw" else fb.Compute
    work, port = kind(request=point("wrong-work"), desc=d), CandidatePort({})
    with pytest.raises(TypeError): worker.run(work, port)
    assert port.trace == [] and port.posts == []


def test_cand1_failed_admission_has_no_read_clock_or_report():
    worker = candidate_type()()
    port = CandidatePort({}, enter=False)
    worker.run(request(), port)
    assert port.trace == [("enter",)] and port.posts == []


def test_cand1_same_worker_reads_each_new_model_from_its_current_port():
    worker = candidate_type()()
    for label, order in [("one", ("A", "B")), ("two", ("D", "C"))]:
        work = request(label=label)
        port = CandidatePort({work.desc.args.model: model_bytes(order)})
        worker.run(work, port)
        event = completed(port, work)
        assert wire(event.outcome.outputs.value) == {"kind": "candidates", "value": wire(expected_declaration(work, order))}
        assert set(port.evidence().uses) == {work.desc.args.model}


def test_cand1_post_failure_escapes_without_a_second_failure_report():
    worker = candidate_type()()
    work, error = request(), OSError("test Post failure")
    port = CandidatePort({work.desc.args.model: model_bytes(("A", "B"))}, post_error=error)
    with pytest.raises(OSError) as caught: worker.run(work, port)
    assert caught.value is error and len(port.posts) == 1


def test_cand1_native_registry_declares_and_preserves_the_candidate_input():
    _registry, declaration, implementation = native_registration()
    assert declaration.args_contract == contract("sui.f.args.empty")
    assert declaration.input_contract == declaration.output_contract == contract("sui.f.schema.candidate_input")
    assert declaration.dependencies == declaration.conditions == ()
    assert implementation.identity == IDENTITY
    from gate_f_facts_cases import finite_world
    document, _ = finite_world("FA01")
    value = {"actions": list(reversed(document["operations"])), "basis": [], "draws": []}
    before = deepcopy(value)
    result = implementation.implementation(args={}, input=value, context=None)
    assert json.dumps(wire(value), sort_keys=True) == json.dumps(wire(before), sort_keys=True)
    assert json.dumps(wire(result), sort_keys=True) == json.dumps(wire(before), sort_keys=True)
    assert [a["id"] for a in result["actions"]] == ["M", "Q"]


@pytest.mark.parametrize("bad", ["args", "missing-actions", "missing-basis", "missing-draws", "extra"])
def test_cand1_native_generator_rejects_bad_args_and_input_fields_with_shape(bad):
    _registry, _declaration, implementation = native_registration()
    args, value = {}, {"actions": [], "basis": [], "draws": []}
    if bad == "args": args = {"extra": 1}
    elif bad == "extra": value["extra"] = 1
    else: del value[bad.removeprefix("missing-")]
    with pytest.raises(f.FInputError) as caught:
        implementation.implementation(args=args, input=value, context=None)
    assert caught.value.reason == "shape"


@pytest.fixture
def rigs():
    active = []
    def register(rig): active.append(rig); return rig
    yield register
    for rig in reversed(active): rig.close()


class CandidateHostPort(fb.FWorkContext):
    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate
    def enter(self):
        entered = self.delegate.enter()
        if entered:
            self.rig.workers.entries.append(self.work)
            self.rig.workers.contexts["candidate_generation"] = self.delegate
        return entered
    def now(self):
        self.rig.clock.set(self.rig.clock.mono_ns() + 7)
        return self.delegate.now()
    def read(self, cid):
        if self.rig.candidate_read_error is not None: raise self.rig.candidate_read_error
        return self.delegate.read(cid)
    def post(self, event, issued=None):
        self.rig.workers.sent.append((event, issued))
        return self.delegate.post(event, issued=issued)


class CandidateHostProbe:
    def __init__(self, rig, native): self.rig, self.native = rig, native
    def run(self, work, ctx): return self.native.run(work, CandidateHostPort(self.rig, work, ctx))


class CandidateHostRig(Stage2Rig):
    def __init__(self, cls, *, empty=False, reverse=False, unsupported=False, read_error=None,
                 operations=_UNCHANGED_OPERATIONS):
        super().__init__(auto_boot=False, empty=empty, reverse_operations=reverse)
        self.candidate_read_error = read_error
        if operations is not _UNCHANGED_OPERATIONS:
            # Keep the entire legal FA01 model except this single field. Save a
            # new immutable record and make Boot name it; do not replace read().
            self.document = deepcopy(self.document)
            self.document["operations"] = deepcopy(operations)
            record = self.record(Prediction(target="K31.operations-shape", about=(), basis=(),
                content=Payload.json({"document": self.document}), contract=contract("sui.f.model_source")),
                RefKind.PREDICTION, Role.MODEL)
            self.model_point = self.ledger.append(record, ()).cid
            slot = self.boot_input.declaration.perception
            self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
                perception=replace(slot, value=replace(slot.value, model=self.model_point))))
        if unsupported:
            slot = self.boot_input.declaration.initial
            self.boot_input = replace(self.boot_input, declaration=replace(self.boot_input.declaration,
                initial=replace(slot, value=replace(slot.value, generator=fb.MethodCall(contract=contract("sui.f.explicit_candidates"), args={})))))
        self.bundle = fb.WorkerBundle({stage: CandidateHostProbe(self, cls()) if stage == "candidate_generation"
            else (fb.StepExecutor() if stage == "execute_step" else self.workers) for stage in ("measure_segment", "candidate_generation", "belief_update", "evaluation_prepare", "selection_draw", "evaluation", "execute_step")})
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.bundle,
            registry=self.registry, launcher=self.launcher)
        self.host.post(self.clock_event); self.host.post(self.boot_input)


@pytest.mark.parametrize("reverse", [False, True])
def test_cand1_host_records_native_model_use_and_advances_to_evaluation_request(rigs, reverse):
    cls = candidate_type()
    rig = rigs(CandidateHostRig(cls, reverse=reverse))
    work = rig.run_stage("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    event = rig.workers.sent[-1][0]
    assert event.started.reading.time_ns < event.finished.reading.time_ns
    cg = rig.one(CG)
    assert cg.value["input_order"] == (["M", "Q"] if reverse else ["Q", "M"])
    ctx = rig.workers.contexts["candidate_generation"]
    assert any(use.work_id == work.desc.work_id and use.point == rig.model_point for use in ctx.evidence().uses)
    assert terminal(rig, work).value["terminal_kind"] == "outputs"


@pytest.mark.parametrize("branch", ["no_candidates", "unsupported_method", "execution_error"])
def test_cand1_host_preserves_native_non_success_terminal_and_display_without_CG_or_EQ(rigs, branch):
    cls = candidate_type()
    rig = rigs(CandidateHostRig(cls, empty=branch == "no_candidates", unsupported=branch == "unsupported_method",
        read_error=RuntimeError("test model read failure") if branch == "execution_error" else None))
    work = rig.run_stage("candidate_generation")
    event = rig.workers.sent[-1][0]
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == ("outputs" if branch == "no_candidates" else "failure")
    basis = t.value["basis"]
    assert basis["generation"] == wire(fb.GenerationPair(started=event.started, finished=event.finished))
    assert basis["unknown"] is None
    if branch == "no_candidates":
        assert wire(event.outcome.outputs.value) == {"kind": "no_candidates", "value": {}}
        assert t.value["returned"] == {"kind": "output", "value": wire(event.outcome.outputs)}
        assert basis["failure"] is None
    else:
        assert_failure(event, branch, "RuntimeError" if branch == "execution_error" else None, method=work.desc.method)
        assert t.value["returned"] is None
        assert basis["failure"] == wire(event.outcome.failure)
    assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))
    expected = "no_candidates" if branch == "no_candidates" else "failure"
    assert any(row.response == expected and (row.target in (work.request, t.cid) or t.cid in row.evidence.basis)
        for row in rig.host.window.status().readings)
    assert rig.host.halted is None


@pytest.mark.parametrize("operations", [[], {}, ""], ids=["empty-array", "empty-object", "empty-string"])
def test_cand1_host_distinguishes_empty_operations_array_from_non_array_failure(rigs, operations):
    """K31-R1: a falsey non-array is not a legitimate zero-operation model.

    Treating {} or "" as [] fails both the worker outcome and saved T/display.
    The [] control preserves NoCandidates, not failure. Parser-chosen exception
    type is not fixed; execution_error content still contains only error_type.
    """
    cls = candidate_type()
    rig = rigs(CandidateHostRig(cls, operations=operations))
    saved = rig.read_stored(rig.model_point)[2].body.content.as_json()["document"]["operations"]
    assert type(saved) is type(operations) and saved == operations
    work = rig.run_stage("candidate_generation")
    assert work.desc.args.model == rig.model_point
    ctx = rig.workers.contexts["candidate_generation"]
    assert any(use.work_id == work.desc.work_id and use.point == rig.model_point for use in ctx.evidence().uses)
    event = rig.workers.sent[-1][0]
    t = terminal(rig, work)
    no_candidates = isinstance(operations, list)
    assert t.value["terminal_kind"] == ("outputs" if no_candidates else "failure")
    basis = t.value["basis"]
    assert basis["generation"] == wire(fb.GenerationPair(started=event.started, finished=event.finished))
    assert basis["unknown"] is None
    if no_candidates:
        assert isinstance(event.outcome, fb.WorkOutputs)
        assert wire(event.outcome.outputs.value) == {"kind": "no_candidates", "value": {}}
        assert t.value["returned"] == {"kind": "output", "value": wire(event.outcome.outputs)}
        assert basis["failure"] is None
    else:
        assert_failure(event, "execution_error")
        assert t.value["returned"] is None
        assert basis["failure"] == wire(event.outcome.failure)
    expected = "no_candidates" if no_candidates else "failure"
    assert any(row.response == expected and (row.target in (work.request, t.cid) or t.cid in row.evidence.basis)
        for row in rig.host.window.status().readings)
    assert_absent(rig, (CG, c.EVALUATION_REQUESTED, c.PREPARED, c.DRAW_REQUESTED))
    assert rig.host.halted is None


def changed_candidate(rig, work, case):
    value = rig.workers.candidate(work)
    if case == "reordered":
        order = tuple(reversed(value.input_order))
        return replace(value, input_order=order, continuation=f.FContinuation(after=tuple(f.ContinuationAfter(candidate=x, policy=None) for x in order)))
    if case == "measure": return replace(value, measure=None)
    if case == "policy": return replace(value, continuation=f.FContinuation(after=(
        f.ContinuationAfter(candidate="Q", policy=f.PolicyRef(name="finite_policy", version="1", args={"id": "M"})),
        f.ContinuationAfter(candidate="M", policy=None))))
    if case == "continuation-order": return replace(value, continuation=f.FContinuation(after=tuple(reversed(value.continuation.after))))
    if case in ("subset", "unknown-candidate"):
        order = ("Q",) if case == "subset" else ("not-in-model",)
        return replace(value, input_order=order, continuation=f.FContinuation(after=tuple(f.ContinuationAfter(candidate=x, policy=None) for x in order)))
    return value


@pytest.mark.parametrize("case", ["legal", "reordered", "measure", "policy", "continuation-order", "different-method", "subset", "unknown-candidate"])
def test_cand1_host_saves_declaration_without_reconstructing_its_semantics(rigs, case):
    rig = rigs(Stage2Rig(auto_boot=False))
    if case == "different-method":
        slot = rig.boot_input.declaration.initial
        rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
            initial=replace(slot, value=replace(slot.value, generator=fb.MethodCall(contract=contract("sui.f.explicit_candidates"), args={})))))
    rig.host.post(rig.clock_event); rig.host.post(rig.boot_input)
    sent = []
    def reply(work, ctx):
        candidate = changed_candidate(rig, work, case)
        sent.append(wire(candidate))
        rig.workers.post(ctx, rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": wire(candidate)}))))
    rig.workers.overrides["candidate_generation"] = reply
    work = rig.run_stage("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    assert rig.one(CG).value == sent[0]
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    assert not any("cg:method_semantics" in (p.kind, p.reason) for p in rig.host.window.status().pending)


@pytest.mark.parametrize("case,reason", [("output_contract", "cg:output_contract"), ("shape", "cg:shape"),
    ("model", "cg:model"), ("generator", "cg:generator"), ("args", "cg:args"), ("basis", "cg:basis"),
    ("draws", "cg:draws"), ("empty", "cg:input_order"), ("duplicate", "cg:input_order")])
def test_cand1_host_keeps_shape_association_and_D6_rejection(rigs, case, reason):
    rig = rigs(Stage2Rig())
    def reply(work, ctx):
        candidate = rig.workers.candidate(work)
        if case == "model": candidate = replace(candidate, model=rig.one(ORIGIN).cid)
        if case == "generator": candidate = replace(candidate, generation=replace(candidate.generation, generator=contract("test.other")))
        if case == "args": candidate = replace(candidate, generation=replace(candidate.generation, args={"extra": 1}))
        if case == "basis": candidate = replace(candidate, generation=replace(candidate.generation, basis=candidate.generation.basis+(rig.one(ORIGIN).cid,)))
        if case == "draws": candidate = replace(candidate, generation=replace(candidate.generation, draws=(rig.one(ORIGIN).cid,)))
        if case in ("empty", "duplicate"):
            order = () if case == "empty" else ("Q", "Q")
            candidate = replace(candidate, input_order=order, continuation=f.FContinuation(after=tuple(f.ContinuationAfter(candidate=x, policy=None) for x in order)))
        rig.workers.post(ctx, rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=contract("test.wrong_output") if case == "output_contract" else c.CANDIDATE_GENERATION,
            value={"bad": 1} if case == "shape" else {"kind": "candidates", "value": wire(candidate)}))))
    rig.workers.overrides["candidate_generation"] = reply
    rig.run_stage("candidate_generation")
    assert_absent(rig, (CG, c.EVALUATION_REQUESTED))
    assert any(reason in (p.reason, p.kind) for p in rig.host.window.status().pending)


@pytest.mark.parametrize("case", ["legal", "subset", "unknown-candidate", "continuation-order"])
def test_cand1_Fa_keeps_model_membership_and_continuation_checks_but_not_completeness(rigs, case):
    rig = rigs(Stage2Rig())
    def reply(work, ctx):
        candidate = changed_candidate(rig, work, case)
        rig.workers.post(ctx, rig.workers.finished(work, fb.WorkOutputs(outputs=f.ContractValue(
            contract=c.CANDIDATE_GENERATION, value={"kind": "candidates", "value": wire(candidate)}))))
    rig.workers.overrides["candidate_generation"] = reply
    rig.run_stage("candidate_generation")
    rig.drive(lambda: bool(rig.facts(c.EVALUATION_REQUESTED)))
    captured = []
    def prepare(work, ctx):
        try: artifact = rig.workers.prepare(work, ctx)
        except f.FInputError as error: captured.append(error)
        else: captured.append(artifact)
    rig.workers.overrides["evaluation_prepare"] = prepare
    rig.callback("evaluation_prepare")()
    assert len(captured) == 1
    if case in ("legal", "subset"):
        assert isinstance(captured[0], f.FMathArtifact) and isinstance(captured[0].value, f.FProblem)
    else:
        assert isinstance(captured[0], f.FInputError) or (
            isinstance(captured[0], f.FMathArtifact) and isinstance(captured[0].value, f.NoDecision))


def test_cand1_main_loop_uses_native_candidates_and_native_generator_registration(rigs):
    cls = candidate_type()
    builtin, declaration, implementation = native_registration()
    rig = rigs(BundleLoopRig(fb.WorkerBundle, candidate_worker=cls()))
    native_decl, = (d for d in rig.registry.declarations if d.kind == "generator" and d.ref == GENERATOR)
    native_impl, = (i for i in rig.registry.implementations if i.kind == "generator" and i.ref == GENERATOR)
    assert native_decl == declaration and native_impl.identity == implementation.identity == IDENTITY
    # K31-a: unrelated TEST capabilities are allowed; only this generator pair
    # must be exclusively the native registration, with no same-ref TEST row.
    rig.start()
    expected = ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},
                {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]})
    for i in range(2):
        rig.publish(i, last=i == 1); rig.update()
        for stage in ORDER[1:]: rig.run_stage(stage)
        rig.until(lambda: len(rig.facts(c.SELECTION)) == i + 2)
    belief1_chain(rig, expected)
    assert len(rig.facts(c.SELECTION)) == 3
    assert all(w.desc.purpose != "candidate_generation" for w in rig.workers.entries)
    ctx = rig.workers.contexts["evaluation"]
    qgen, = rig.requests("candidate_generation")
    wid = qgen.value["desc"]["work_id"]
    assert any(use.work_id == wid and use.point == rig.model_point for use in ctx.evidence().uses)
    assert execution_for(ctx, wid).entered == 1 and execution_for(ctx, wid).stopped
    assert rig.host.halted is None
