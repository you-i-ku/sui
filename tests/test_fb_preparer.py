"""K32/K32-a, F-b :3555, :4620-4681. Public surfaces and test fixtures only.

Native worker names are resolved inside cases, so an absent K32 implementation
does not collapse collection. Native preparation, bounded mathematical controls,
and optional-limit calculations have separate assertions. S4 never receives None.

Mutation discrimination:
- Reusing the after-reading as started fails the public port's ordered trace.
- Ignoring the supplied reader/registry/input changes the real artifact's inputs.
- Changing/retrying the budget changes the issue or repeats registry callbacks.
- Treating NoDecision as failure loses outputs, the live issue, PR or its display.
- Escaping preparation errors or leaking open reason/field text fails exact content.
- Comparing any None limit, disabling another int limit, or range(None) fails the
  finite calculations and their bounded-limit controls, rather than a time limit.
- Substituting a budget/registry artifact fails the host's association contrasts.

No implementation has been patched. Registry spies wrap public capability
callbacks; their single-prepare control uses the same public mathematical entry,
not host read counts or wall-clock scheduling. Mathematical expectations (Q/M,
the native T/E adoption chain, and the FA13 certified-prefix choice) come from
declared fixture models, not the test worker's returned output.
"""

from dataclasses import replace
from fractions import Fraction as Q
from inspect import Parameter, signature
import json
from typing import get_type_hints

import pytest

from sui import f, fb, fb_contracts as c, f_facts as ff, rate
from gate_f_facts_cases import BUDGET, METHOD, add_draw, assemble, bound, prepare
from test_fb_skeleton import contract, desc, point, reading
from test_fb_stage1 import wire
from test_fb_stage2 import (
    Stage2Rig, ORDER, MATH, PREPARE_BUDGET, EVALUATE_BUDGET, registry,
    terminal, assert_absent,
)
from test_fb_bundle import BundleLoopRig
from test_fb_belief import ROUTE, belief1_chain
from test_gate_f_contract import assert_quantity


CAPS = ("max_cells", "max_terms", "max_refinements")
CLOSED_REASONS = ("budget_exhausted", "selection_boundary", "certificate_incomplete",
                  "cost_certificate", "c1_closure_unproved")


def preparer_type():
    assert hasattr(fb, "EvaluationPreparer"), "K32 public API missing: fb.EvaluationPreparer"
    return fb.EvaluationPreparer


def unbounded(*names, base=BUDGET):
    return replace(base, **{name: None for name in (names or CAPS)})


def budget_json(budget):
    return {"tolerance": [budget.tolerance.numerator, budget.tolerance.denominator],
            **{name: getattr(budget, name) for name in CAPS}}


def request(case, budget=BUDGET, *, label="one"):
    args = fb.EvaluationPrepareArgs(input=f.FFactsRequest(
        fixed_parents=case.fixed_parents, model=case.points["model"],
        candidates=case.points["candidates"], preferences=tuple(case.preferences),
        scope=case.scope, context=case.points["context"], method=METHOD),
        compiler=contract("sui.f.compiler"), budget=budget)
    d = replace(desc("evaluation_prepare"), work_id="K32-prepare-" + label,
                method=c.EVALUATION_PREPARE, output_contract=MATH, args=args)
    return fb.Compute(request=point("K32-request-" + label), desc=d)


class PreparationError(Exception):
    pass


class AttributedError(Exception):
    reason, field = "budget_exhausted", "/reader"


class PublicReader(f.FReader):
    """Real immutable input is available only behind the public reader methods."""
    def __init__(self, delegate, port):
        self.delegate, self.port = delegate, port
    def call(self, name, *args):
        self.port.trace.append((name, *args))
        self.port.time += 3
        if self.port.error is not None:
            raise self.port.error
        return getattr(self.delegate, name)(*args)
    def entry(self, cid): return self.call("entry", cid)
    def entries(self): return self.call("entries")
    def record(self, cid): return self.call("record", cid)
    def ancestors(self, frontier): return self.call("ancestors", frontier)
    def sealed_content(self, cid): return self.call("sealed_content", cid)


class PreparationPort(fb.FWorkContext):
    def __init__(self, reader, *, enter=True, error=None, unavailable=(), post_error=None):
        self.allowed, self.error = enter, error
        self.unavailable, self.post_error = set(unavailable), post_error
        self.trace, self.posts, self.readings, self.time = [], [], [], 100
        self.view = None if reader is None else PublicReader(reader, self)
    def enter(self): self.trace.append(("enter",)); return self.allowed
    def now(self):
        self.trace.append(("now",)); self.time += 7
        if len(self.readings) in self.unavailable:
            self.readings.append(None)
            raise RuntimeError("private clock message")
        value = reading()
        value = replace(value, reading=replace(value.reading, time_ns=self.time))
        self.readings.append(value)
        return value
    def reader(self): self.trace.append(("reader",)); return self.view
    def post(self, event, issued=None):
        self.trace.append(("post",)); self.posts.append((event, issued))
        if self.post_error is not None: raise self.post_error
    def read(self, cid): raise AssertionError("K32 reads the model through ctx.reader()")
    def prepared(self): raise AssertionError("preparation must not reuse an earlier issue")
    def acquire(self): raise AssertionError("preparation is not measurement")
    def monitored(self, interval): raise AssertionError("preparation is not monitoring")


def completed(port, work):
    assert len(port.posts) == 1 and len(port.readings) == 2
    event, issued = port.posts[0]
    assert isinstance(event, fb.WorkFinished) and event.work == work.desc.work_id
    assert port.trace[0] == ("enter",) and port.trace[-1] == ("post",)
    nows = [i for i, op in enumerate(port.trace) if op == ("now",)]
    reads = [i for i, op in enumerate(port.trace) if op[0] not in ("enter", "now", "post")]
    assert len(nows) == 2 and reads and nows[0] < min(reads) <= max(reads) < nows[1]
    assert port.trace.count(("reader",)) == 1
    for actual, observed in zip((event.started, event.finished), port.readings):
        assert actual == (f.Unavailable(reason="clock_source_unavailable", basis=())
                          if observed is None else observed)
    return event, issued


def outputs(port, work, expected_type):
    event, issued = completed(port, work)
    assert isinstance(event.outcome, fb.WorkOutputs)
    assert isinstance(issued, f.FMathArtifact) and isinstance(issued.value, expected_type)
    assert event.outcome.outputs.contract == work.desc.output_contract
    body = json.loads(issued.canonical_bytes)
    assert wire(event.outcome.outputs.value) == body
    assert body["calls"][0]["op"] == "prepare"
    assert body["calls"][0]["args"]["budget"] == budget_json(work.desc.args.budget)
    assert len(body["calls"]) == 1
    actual = body["input"]["value"]
    # FFactsRequest is the declared factory input; no current-head substitute.
    assert actual == wire(work.desc.args.input)
    return issued


def failure(port, work, *, error_type=None, content=None):
    event, issued = completed(port, work)
    assert issued is None and isinstance(event.outcome, fb.WorkFailure)
    value = event.outcome.failure
    assert value.failure_kind == "execution_error"
    actual = wire(value.content)
    if content is not None: assert actual == content
    else:
        assert set(actual) == {"error_type"}
        assert isinstance(actual["error_type"], str) and actual["error_type"].isidentifier()
        if error_type is not None: assert actual["error_type"] == error_type
    return event


def counted_registry(base):
    """Observe calls to registry capabilities, with actual native implementations."""
    calls = []
    wrapped = []
    for item in base.implementations:
        def invoke(*, args, input, context, item=item):
            calls.append((item.kind, item.ref))
            return item.implementation(args=args, input=input, context=context)
        wrapped.append(replace(item, implementation=invoke))
    return f.make_f_registry(declarations=base.declarations, implementations=tuple(wrapped)), calls


def without_proof(base):
    return f.make_f_registry(declarations=base.declarations, implementations=tuple(
        item for item in base.implementations if item.ref != contract("finite_option_proof")))


def test_prep1_public_constructor_run_export_and_optional_limit_annotations():
    cls = preparer_type()
    params = signature(cls).parameters
    assert tuple(params) == ("registry",)
    assert params["registry"].kind is Parameter.KEYWORD_ONLY
    assert params["registry"].default is Parameter.empty
    assert get_type_hints(cls.__init__)["registry"] is f.FRegistry
    assert tuple(signature(cls.run).parameters) == ("self", "work", "ctx")
    assert "EvaluationPreparer" in fb.__all__
    assert {name: get_type_hints(rate.RateBudget)[name] for name in CAPS} == {
        name: int | None for name in CAPS}


@pytest.mark.parametrize("kind", ["problem", "no_decision"])
def test_prep1_native_output_uses_exact_reader_request_registry_budget_once(kind):
    worker_cls = preparer_type()
    case = assemble("FA01")
    base = f.builtin_f_registry()
    if kind == "no_decision": base = without_proof(base)
    reg, calls = counted_registry(base)
    # Count one complete public prepare on an isolated immutable input. This
    # observation does not calibrate reads of asynchronously running host jobs.
    expected = prepare(case, registry=reg)
    one_call = tuple(calls)
    assert one_call
    calls.clear()
    work, port = request(case), PreparationPort(case.reader)
    worker_cls(registry=reg).run(work, port)
    issued = outputs(port, work, f.FProblem if kind == "problem" else f.NoDecision)
    assert tuple(calls) == one_call, "must not retry even a regular NoDecision"
    assert json.loads(issued.canonical_bytes)["environment"]["registry_key"] == json.loads(expected.canonical_bytes)["environment"]["registry_key"]
    if kind == "problem": assert tuple(a.id for a in issued.value.candidates.candidates) == ("Q", "M")
    else: assert issued.value.reason == "algorithm_unavailable"


def test_prep1_native_preparation_keeps_nondefault_scope_and_preferences():
    cls = preparer_type()
    case = assemble("FA04", "nonzero", H=10**9, scope_name="finite_horizon")
    assert case.preferences and case.scope.H_ns == 10**9
    work, port = request(case), PreparationPort(case.reader)
    cls(registry=f.builtin_f_registry()).run(work, port)
    outputs(port, work, f.FProblem)


@pytest.mark.parametrize("unavailable", [(), (0,), (1,), (0, 1)])
@pytest.mark.parametrize("branch", ["problem", "failure"])
def test_prep1_reads_distinct_clocks_even_on_failure_and_preserves_readable_side(unavailable, branch):
    cls = preparer_type()
    case = assemble("FA01")
    work = request(case)
    port = PreparationPort(case.reader, unavailable=unavailable,
        error=PreparationError("private reader exception") if branch == "failure" else None)
    cls(registry=f.builtin_f_registry()).run(work, port)
    if branch == "failure": failure(port, work, error_type="PreparationError")
    else: outputs(port, work, f.FProblem)
    if not unavailable: assert port.readings[0].reading.time_ns < port.readings[1].reading.time_ns


@pytest.mark.parametrize("error", [OSError("private message"), KeyError("private key"),
    ValueError("private value"), MemoryError("private allocation"), AttributedError("private reason")],
    ids=["OSError", "KeyError", "ValueError", "MemoryError", "ordinary-reason-attribute"])
def test_prep1_reader_exceptions_are_failure_with_only_the_type_name(error):
    cls = preparer_type()
    case = assemble("FA01"); work = request(case)
    port = PreparationPort(case.reader, error=error)
    cls(registry=f.builtin_f_registry()).run(work, port)
    failure(port, work, error_type=type(error).__name__)


def test_prep1_missing_reader_is_failure_without_fictitious_issue():
    cls = preparer_type()
    case = assemble("FA01"); work = request(case); port = PreparationPort(None)
    cls(registry=f.builtin_f_registry()).run(work, port)
    # The paper does not choose the exception class used to signal None.
    failure(port, work)


@pytest.mark.parametrize("reason", CLOSED_REASONS)
@pytest.mark.parametrize("field", ["/reader", "private-field", None, 9], ids=["pointer", "nonpointer", "absent", "not-string"])
def test_prep1_closed_incomplete_reason_and_only_pointer_field_are_preserved(reason, field):
    cls = preparer_type()
    case = assemble("FA01"); work = request(case)
    port = PreparationPort(case.reader, error=f.FIncomplete(reason, "private detail", field))
    cls(registry=f.builtin_f_registry()).run(work, port)
    failure(port, work, content={"error_type": "FIncomplete", "reason": reason,
        "field": field if isinstance(field, str) and field.startswith("/") else None})


@pytest.mark.parametrize("kind,reason", [(f.FIncomplete, "private_reason"),
    (f.FInputError, "budget_exhausted"), (f.FIncomplete, None)])
def test_prep1_other_exception_reasons_and_details_are_not_disclosed(kind, reason):
    cls = preparer_type()
    case = assemble("FA01"); work = request(case)
    port = PreparationPort(case.reader, error=kind(reason, "private detail", "/reader"))
    cls(registry=f.builtin_f_registry()).run(work, port)
    failure(port, work, error_type=kind.__name__)


@pytest.mark.parametrize("stage", ["candidate_generation", "belief_update", "evaluation", "selection_draw", "measure_segment", "not-compute"])
def test_prep1_wrong_work_is_type_error_before_enter(stage):
    cls = preparer_type()
    d = desc("evaluation_prepare" if stage == "not-compute" else stage)
    kind = fb.MeasureSegment if stage in ("measure_segment", "not-compute") else fb.Draw if stage == "selection_draw" else fb.Compute
    port = PreparationPort(None)
    with pytest.raises(TypeError): cls(registry=f.builtin_f_registry()).run(kind(request=point(stage), desc=d), port)
    assert port.trace == [] and port.posts == []


def test_prep1_false_admission_has_no_reader_clock_or_post():
    cls = preparer_type()
    case = assemble("FA01"); port = PreparationPort(case.reader, enter=False)
    cls(registry=f.builtin_f_registry()).run(request(case), port)
    assert port.trace == [("enter",)] and not port.posts


def test_prep1_post_error_escapes_without_second_report():
    cls = preparer_type()
    case = assemble("FA01"); error = OSError("Post failed")
    port = PreparationPort(case.reader, post_error=error)
    with pytest.raises(OSError) as caught: cls(registry=f.builtin_f_registry()).run(request(case), port)
    assert caught.value is error and len(port.posts) == 1


@pytest.mark.parametrize("mask", range(1, 8))
def test_prep1_each_combination_of_optional_limits_is_accepted(mask):
    names = [name for i, name in enumerate(CAPS) if mask & (1 << i)]
    value = unbounded(*names)
    assert value.tolerance == BUDGET.tolerance
    assert {name: getattr(value, name) for name in CAPS} == {
        name: None if name in names else getattr(BUDGET, name) for name in CAPS}


@pytest.mark.parametrize("name", CAPS)
@pytest.mark.parametrize("bad", [0, -1, True, 1.0, "1", Q(1), []], ids=["zero", "negative", "bool", "float", "string", "fraction", "list"])
def test_prep1_invalid_integer_limits_still_have_invalid_budget(name, bad):
    with pytest.raises(rate.RateInputError) as caught: replace(BUDGET, **{name: bad})
    assert caught.value.reason == "invalid_budget"


@pytest.mark.parametrize("bad", [None, Q(0), Q(-1), 1, 0.1, True])
def test_prep1_tolerance_is_still_a_required_positive_fraction(bad):
    with pytest.raises(rate.RateInputError) as caught: replace(BUDGET, tolerance=bad)
    assert caught.value.reason == "invalid_budget"
    with pytest.raises(TypeError): rate.RateBudget(max_cells=10, max_terms=10, max_refinements=10)


def test_prep1_preflight_budget_failure_and_unbounded_preparation_are_distinct():
    case = assemble("FA04")
    with pytest.raises(f.FIncomplete) as caught: prepare(case, budget=replace(BUDGET, max_cells=1))
    assert (caught.value.reason, caught.value.field) == ("budget_exhausted", "/reader")
    # Eight immutable records fit the reader; the finite policy computation
    # then exhausts 64 cells. This is a real calculation NoDecision, not a
    # synthetic response or a reader exception relabelled as an issue.
    stopped = prepare(case, budget=replace(BUDGET, max_cells=64))
    assert isinstance(stopped.value, f.NoDecision) and stopped.value.reason == "budget_exhausted"
    unlimited = unbounded()
    artifact = prepare(case, budget=unlimited)
    assert isinstance(artifact.value, f.FProblem)
    assert tuple(a.id for a in artifact.value.candidates.candidates) == ("M", "Q")
    assert json.loads(artifact.canonical_bytes)["calls"][0]["args"]["budget"] == budget_json(unlimited)


@pytest.mark.parametrize("name", ["max_cells", "max_terms"])
@pytest.mark.parametrize("method", ["recursive", "enumerated", "prefix"])
def test_prep1_real_finite_evaluation_exceeds_each_optional_cell_or_term_cap(name, method):
    case = assemble("FA01"); _, _, root = bound(case)
    paths = f.enumerate_f_paths(root.value, budget=BUDGET)
    def evaluate(budget):
        if method == "recursive": return f.evaluate_f_recursive(root.value, budget=budget)
        if method == "enumerated": return f.evaluate_f_enumerated(root.value, paths, budget=budget)
        return f.evaluate_f_prefix(root.value, steps=2, budget=budget)
    with pytest.raises(f.FIncomplete) as caught: evaluate(replace(BUDGET, **{name: 1}))
    assert caught.value.reason == "budget_exhausted"
    result = evaluate(unbounded(name))
    # FA01: quiet has no additional information, perfect M gives ln 2;
    # soft-choice weights exp(0):exp(ln2) = 1:2.
    assert result.candidates == ("Q", "M")
    for value, expected in zip(result.q_star, (Q(1, 3), Q(2, 3))):
        assert_quantity(value, expected)
    # The fixture binds u=1/2: the Q cell ends at 1/3, so this draw selects M.
    assert f.certify_f_choice(result, u=Q(*root.value.selection_draw.value["u"])).choice.id == "M"


@pytest.mark.parametrize("method", ["selected", "facts-draw"])
def test_prep1_refinement_loop_passes_one_step_with_no_refinement_cap(method):
    case = assemble("FA13")
    prepared, draw, root = bound(case, u=Q(1, 2))
    small = replace(BUDGET, tolerance=Q(1, 2), max_refinements=1)
    enough = replace(small, max_refinements=32)
    def evaluate(budget):
        return (f.evaluate_f(root.value, budget=budget) if method == "selected" else
                ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=budget).value)
    stopped = evaluate(small)
    assert isinstance(stopped, f.NoDecision) and stopped.reason == "budget_exhausted"
    # FA13's certified prefix n=2 already separates W at u=1/2. Thus this
    # particular unbounded-limit call terminates; it is not a liveness claim.
    assert evaluate(enough).choice.id == "W"
    assert evaluate(unbounded("max_refinements", base=small)).choice.id == "W"


@pytest.mark.parametrize("missing,remaining", [(a, b) for a in CAPS for b in CAPS if a != b])
def test_prep1_one_unbounded_limit_does_not_disable_other_integer_limits(missing, remaining):
    case = assemble("FA13")
    _, _, root = bound(case, u=Q(1, 2))
    budget = replace(BUDGET, tolerance=Q(1, 2), **{remaining: 1})
    result = f.evaluate_f(root.value, budget=unbounded(missing, base=budget))
    assert isinstance(result, f.NoDecision) and result.reason == "budget_exhausted"


def test_prep1_bounded_finite_control_retains_declared_choice_and_input():
    case = assemble("FA01"); _, _, root = bound(case, u=Q(1, 4))
    before = tuple(case.ledger.entries())
    result = f.evaluate_f(root.value, budget=BUDGET)
    assert isinstance(result, f.Selected) and result.choice.id == "Q" and result.u == Q(1, 4)
    assert tuple(case.ledger.entries()) == before
    evaluated = f.evaluate_f_recursive(root.value, budget=BUDGET)
    for value, expected in zip(evaluated.q_star, (Q(1, 3), Q(2, 3))):
        assert_quantity(value, expected)


def test_prep1_S4_integer_saved_budget_and_public_replay_remain_unchanged():
    """K32(3)/(6), Z59: reuse existing S4 integer-only public regressions.

    No None budget crosses an S4 entry, and no saved S4 budget is rewritten.
    """
    from test_s4b2_integration import (
        test_T14_public_roundtrip_keeps_injected_budget_and_planned_start,
        test_T12_replay_budget_is_resource_limit_and_does_not_replace_saved_budget,
    )
    test_T14_public_roundtrip_keeps_injected_budget_and_planned_start(0)
    test_T12_replay_budget_is_resource_limit_and_does_not_replace_saved_budget()


@pytest.mark.parametrize("execute_unlimited", [False, True], ids=["saved-int", "saved-null"])
@pytest.mark.parametrize("verify_unlimited", [False, True], ids=["verify-int", "verify-null"])
@pytest.mark.parametrize("op", ["prepare", "evaluate"])
def test_prep1_artifacts_restore_and_verify_with_independent_execution_and_verification_budgets(execute_unlimited, verify_unlimited, op):
    case = assemble("FA01")
    execution = unbounded() if execute_unlimited else BUDGET
    verification = unbounded() if verify_unlimited else BUDGET
    artifact = prepare(case, budget=execution)
    if op == "evaluate":
        draw = add_draw(case, artifact.value.problem_key, u=Q(1, 4))
        artifact = ff.evaluate_f_from_draw(artifact, draw, reader=case.reader, budget=execution)
        assert isinstance(artifact.value, f.Selected) and artifact.value.choice.id == "Q"
    saved = artifact.canonical_bytes
    parsed = json.loads(saved)
    assert any(call["args"].get("budget") == budget_json(execution) for call in parsed["calls"])
    checked = ff.verify_f_math_result(saved, reader=case.reader, registry=f.builtin_f_registry(), budget=verification)
    restored = ff.restore_f_math_result(saved, reader=case.reader, registry=f.builtin_f_registry(), budget=verification)
    assert isinstance(checked, f.VerifiedMathResult)
    assert restored.canonical_bytes == saved and restored.value == artifact.value
    assert checked.kind == "math" and checked.artifact_digest


@pytest.mark.parametrize("entry", ["verify", "restore"])
def test_prep1_unbounded_saved_execution_does_not_remove_bounded_replay_limit(entry):
    case = assemble("FA01")
    artifact = prepare(case, budget=unbounded())
    call = ff.verify_f_math_result if entry == "verify" else ff.restore_f_math_result
    with pytest.raises(f.FIncomplete) as caught:
        call(artifact.canonical_bytes, reader=case.reader, registry=f.builtin_f_registry(),
             budget=replace(BUDGET, max_cells=1))
    assert caught.value.reason == "budget_exhausted"
    # Larger integer verification budget still checks the saved null execution.
    call(artifact.canonical_bytes, reader=case.reader, registry=f.builtin_f_registry(), budget=BUDGET)


def test_prep1_native_preflight_failure_is_not_regular_calculation_no_decision():
    cls = preparer_type(); case = assemble("FA04")
    work = request(case, replace(BUDGET, max_cells=1)); port = PreparationPort(case.reader)
    cls(registry=f.builtin_f_registry()).run(work, port)
    failure(port, work, content={"error_type": "FIncomplete", "reason": "budget_exhausted", "field": "/reader"})
    # The same input, with enough reader capacity but insufficient calculation
    # capacity, yields the genuine regular NoDecision (paper :4677).
    work2 = request(case, replace(BUDGET, max_cells=64), label="regular")
    port2 = PreparationPort(case.reader)
    cls(registry=f.builtin_f_registry()).run(work2, port2)
    assert outputs(port2, work2, f.NoDecision).value.reason == "budget_exhausted"


def test_prep1_same_native_worker_uses_two_current_inputs_and_budgets():
    cls = preparer_type(); worker = cls(registry=f.builtin_f_registry())
    issues = []
    for i, (case, budget) in enumerate(((assemble("FA01"), BUDGET),
                                       (assemble("FA04"), unbounded()))):
        work = request(case, budget, label=str(i)); port = PreparationPort(case.reader)
        worker.run(work, port)
        issues.append(outputs(port, work, f.FProblem))
    assert issues[0].value.problem_key != issues[1].value.problem_key


class HostPreparationPort(fb.FWorkContext):
    """Observe/forward public operations; optionally substitute a REAL issue."""
    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate
    def enter(self):
        entered = self.delegate.enter()
        if entered:
            self.rig.workers.entries.append(self.work)
            self.rig.workers.contexts["evaluation_prepare"] = self.delegate
        return entered
    def now(self):
        self.rig.clock.set(self.rig.clock.mono_ns() + 7)
        return self.delegate.now()
    def reader(self):
        self.rig.prepare_reader = self.delegate.reader()
        return self.rig.prepare_reader
    def post(self, event, issued=None):
        self.rig.native_posts.append((self.work, event, issued))
        self.rig.pending_before_issue = self.rig.host.window.status().pending
        if self.rig.replace_issue is not None:
            issued = self.rig.replace_issue(self.work, self.rig.prepare_reader)
            event = replace(event, outcome=fb.WorkOutputs(outputs=f.ContractValue(
                contract=self.work.desc.output_contract, value=json.loads(issued.canonical_bytes))))
        self.rig.workers.sent.append((event, issued))
        self.rig.workers.issued["evaluation_prepare"] = issued
        self.delegate.post(event, issued=issued)


class HostPreparationProbe:
    def __init__(self, rig, worker): self.rig, self.worker = rig, worker
    def run(self, work, ctx): return self.worker.run(work, HostPreparationPort(self.rig, work, ctx))


class PreparationRig(Stage2Rig):
    def __init__(self, cls, *, budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET,
                 no_decision=False, replace_issue=None):
        super().__init__(auto_boot=False, prepare_budget=budget, evaluate_budget=evaluate_budget,
            omit_implementation=contract("finite_option_proof") if no_decision else None)
        self.native_posts, self.replace_issue, self.prepare_reader = [], replace_issue, None
        self.native_preparer = cls(registry=self.registry)
        self.bundle_workers = {stage: fb.StepExecutor() if stage == "execute_step" else self.workers for stage in (
            "candidate_generation", "measure_segment", "belief_update", "evaluation_prepare", "selection_draw", "evaluation", "execute_step")}
        self.bundle_workers["evaluation_prepare"] = HostPreparationProbe(self, self.native_preparer)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=fb.WorkerBundle(self.bundle_workers), registry=self.registry, launcher=self.launcher)
        self.host.post(self.clock_event); self.host.post(self.boot_input)


@pytest.fixture
def rigs():
    active = []
    def register(rig): active.append(rig); return rig
    yield register
    for rig in reversed(active): rig.close()


@pytest.mark.parametrize("null_budget", [False, True], ids=["bounded-control", "null-limits"])
def test_prep1_host_saves_requested_budget_and_live_problem_then_offers_draw(rigs, null_budget):
    cls = preparer_type()
    budget = unbounded(base=PREPARE_BUDGET) if null_budget else PREPARE_BUDGET
    evaluation = unbounded(base=EVALUATE_BUDGET) if null_budget else EVALUATE_BUDGET
    rig = rigs(PreparationRig(cls, budget=budget, evaluate_budget=evaluation))
    rig.through("evaluation_prepare")
    rig.drive(lambda: bool(rig.facts(c.DRAW_REQUESTED)))
    work, event, issued = rig.native_posts[0]
    assert isinstance(issued.value, f.FProblem) and event.started.reading.time_ns < event.finished.reading.time_ns
    assert rig.request("evaluation_prepare").value["desc"]["args"]["budget"] == budget_json(budget)
    saved = rig.one(MATH, cid=rig.one(c.PREPARED).value["artifact"])
    assert saved.value == json.loads(issued.canonical_bytes)
    assert saved.value["calls"][0]["args"]["budget"] == budget_json(budget)
    assert terminal(rig, work).value["returned"] == {"kind": "output", "value": wire(event.outcome.outputs)}
    rig.run_stage("selection_draw"); rig.run_stage("evaluation")
    assert rig.request("evaluation").value["desc"]["args"]["budget"] == budget_json(evaluation)
    selected = rig.workers.issued["evaluation"].value
    assert isinstance(selected, f.Selected) and selected.choice.id == "Q"
    assert rig.host.halted is None


def test_prep1_host_keeps_no_decision_as_outputs_and_never_draws(rigs):
    cls = preparer_type(); rig = rigs(PreparationRig(cls, no_decision=True))
    rig.through("evaluation_prepare")
    work, event, issued = rig.native_posts[0]
    assert isinstance(event.outcome, fb.WorkOutputs) and isinstance(issued.value, f.NoDecision)
    assert issued.value.reason == "algorithm_unavailable"
    assert rig.one(MATH, cid=rig.one(c.PREPARED).value["artifact"]).value == json.loads(issued.canonical_bytes)
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    assert any(row.response == "no_decision" for row in rig.host.window.status().readings)
    assert_absent(rig, (c.DRAW_REQUESTED, c.DRAW_REPORT, c.EVALUATED, c.SELECTION))


def test_prep1_host_records_preflight_failure_reason_field_and_no_regular_issue(rigs):
    cls = preparer_type()
    rig = rigs(PreparationRig(cls, budget=replace(PREPARE_BUDGET, max_cells=1)))
    rig.through("evaluation_prepare")
    work, event, issued = rig.native_posts[0]
    assert issued is None and isinstance(event.outcome, fb.WorkFailure)
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "failure" and t.value["returned"] is None
    assert t.value["basis"]["failure"]["failure_kind"] == "execution_error"
    assert t.value["basis"]["failure"]["content"] == {
        "error_type": "FIncomplete", "reason": "budget_exhausted", "field": "/reader"}
    assert any(row.response == "failure" for row in rig.host.window.status().readings)
    assert_absent(rig, (MATH, c.PREPARED, c.DRAW_REQUESTED, c.SELECTION))
    assert rig.host.halted is None


@pytest.mark.parametrize("substitution", ["integer-budget", "foreign-registry"])
def test_prep1_host_rejects_real_issue_with_changed_budget_or_registry(rigs, substitution):
    cls = preparer_type()
    budget = unbounded(base=PREPARE_BUDGET)
    def substitute(work, reader):
        a = work.desc.args
        changed_registry = rig.registry
        if substitution == "foreign-registry":
            implementation = changed_registry.implementations[0]
            changed_registry = f.make_f_registry(declarations=changed_registry.declarations,
                implementations=(replace(implementation, identity=implementation.identity + ":K32-foreign"),) + changed_registry.implementations[1:])
        return ff.prepare_f_from_facts(reader, fixed_parents=a.input.fixed_parents,
            model_ref=a.input.model, candidate_ref=a.input.candidates, preference_refs=a.input.preferences,
            scope_request=a.input.scope, context_ref=a.input.context, method=a.input.method,
            registry=changed_registry, budget=PREPARE_BUDGET if substitution == "integer-budget" else budget)
    rig = rigs(PreparationRig(cls, budget=budget, replace_issue=substitute))
    rig.through("evaluation_prepare")
    assert_absent(rig, (c.PREPARED, c.DRAW_REQUESTED))
    reasons = [p.reason for p in rig.host.window.status().pending]
    if substitution == "integer-budget": assert "artifact:budget" in reasons
    else:
        # K32 specifies a hold, not this diagnostic's spelling or target.
        assert terminal(rig, rig.native_posts[0][0]).value["terminal_kind"] == "outputs"
        assert any(p not in rig.pending_before_issue
                   for p in rig.host.window.status().pending), "different-registry issue must remain pending"
    assert rig.host.halted is None


class PreparationLoopRig(BundleLoopRig):
    """Extend the K30/K31 main rig: native M/U/Cg/Ep, TEST D/Ee only."""
    def __init__(self, cls):
        self.native_posts, self.replace_issue, self.prepare_reader = [], None, None
        super().__init__(fb.WorkerBundle, candidate_worker=fb.CandidateGenerator())
        self.native_preparer = cls(registry=self.registry)
        self.bundle_workers["evaluation_prepare"] = HostPreparationProbe(self, self.native_preparer)
        self.bundle = fb.WorkerBundle(self.bundle_workers)
        # The old host has only queued declarations; reconnect before acceptance.
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.bundle,
            registry=self.registry, launcher=self.launcher, sources={ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration)); self.host.post(self.boot_input)
    def run_stage(self, stage):
        if stage != "evaluation_prepare": return super().run_stage(stage)
        request, body = self.callback(stage)
        wid = request.value["desc"]["work_id"]
        self.executed.add(wid); body()
        self.drive(lambda: any(x.value["work"] == wid for x in self.facts(c.WORK_REPORT)))
        self.settle_steps()


def test_prep1_main_loop_native_source_update_candidate_preparation_and_three_selections(rigs):
    cls = preparer_type(); rig = rigs(PreparationLoopRig(cls))
    assert rig.bundle_workers["measure_segment"] is rig.native_measurer
    assert rig.bundle_workers["belief_update"] is rig.native_updater
    assert type(rig.bundle_workers["candidate_generation"]) is fb.CandidateGenerator
    assert rig.bundle_workers["evaluation_prepare"].worker is rig.native_preparer
    assert rig.bundle_workers["selection_draw"] is rig.bundle_workers["evaluation"] is rig.workers
    rig.start()
    expected = ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},
                {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]})
    for index in range(2):
        rig.publish(index, last=index == 1); rig.update()
        for stage in ORDER[1:]: rig.run_stage(stage)
        rig.until(lambda: len(rig.facts(c.SELECTION)) == index + 2)
    belief1_chain(rig, expected)
    assert len(rig.native_posts) == len(rig.facts(c.PREPARED)) == 3
    assert all(isinstance(issue.value, f.FProblem) for _, _, issue in rig.native_posts)
    assert len(rig.reports("frame")) == len(rig.source.calls) == 2
    assert len(rig.facts(c.SELECTION)) == 3
    assert rig.host.halted is None and not rig.host.interruptions()


@pytest.mark.parametrize("missing", ["max_terms", "max_refinements"])
def test_prep1_preflight_retains_cell_limit_when_another_limit_is_unbounded(missing):
    """K32 decision 5 / scene 11, at reader intake rather than evaluation.

    Disabling max_cells because another limit is None loses the /reader failure.
    Rejecting every such mixed budget also fails the adequate-cell contrasts.
    """
    case = assemble("FA01")
    before = tuple(case.ledger.entries())
    small = replace(BUDGET, max_cells=1)
    with pytest.raises(f.FIncomplete) as bounded:
        prepare(case, budget=small)
    assert (bounded.value.reason, bounded.value.field) == ("budget_exhausted", "/reader")

    mixed = unbounded(missing, base=small)
    with pytest.raises(f.FIncomplete) as stopped:
        prepare(case, budget=mixed)
    assert (stopped.value.reason, stopped.value.field) == ("budget_exhausted", "/reader")
    for enough in (replace(mixed, max_cells=BUDGET.max_cells),
                   unbounded("max_cells", base=mixed)):
        artifact = prepare(case, budget=enough)
        assert isinstance(artifact.value, f.FProblem)
        assert json.loads(artifact.canonical_bytes)["calls"][0]["args"]["budget"] == budget_json(enough)
    assert tuple(case.ledger.entries()) == before


@pytest.mark.parametrize("entry", ["verify", "restore"])
@pytest.mark.parametrize("limited", ["max_cells", "max_terms"])
def test_prep1_replay_integer_cap_stops_verification_after_reader_intake_fits(entry, limited):
    """K32 decision 5 / scene 13: isolate verification from reader preflight.

    A three-step evaluated issue needs more checking than T22's prepare-only
    issue. Choose the small bound once from the public input: reader entry count
    for cells, one for terms. A real prepare issue proves that this same reader
    and budget pass intake, even if the calculation itself returns NoDecision.
    Removing the verification cap must therefore fail pytest.raises; a later
    /reader budget failure must not mask it. No limit is retuned after a miss.
    """
    case = assemble("FA01")
    initial = prepare(case, budget=BUDGET)
    draw = add_draw(case, initial.value.problem_key, u=Q(1, 4))
    bounded = ff.evaluate_f_from_draw(initial, draw, reader=case.reader, budget=BUDGET)
    assert isinstance(bounded.value, f.Selected) and bounded.value.choice.id == "Q"
    assert len(json.loads(bounded.canonical_bytes)["calls"]) > 1
    cells = len(tuple(case.reader.entries()))
    small = replace(BUDGET, **{limited: cells if limited == "max_cells" else 1})
    before = tuple(case.ledger.entries())

    # Unlike max_cells=1 in T22, this bound permits reader intake. This control
    # deliberately requires a genuine issue, not a caught FIncomplete.
    intake = prepare(case, budget=small)
    assert isinstance(intake, f.FMathArtifact)
    call = ff.verify_f_math_result if entry == "verify" else ff.restore_f_math_result

    def succeeds(artifact, budget):
        result = call(artifact.canonical_bytes, reader=case.reader,
                      registry=f.builtin_f_registry(), budget=budget)
        if entry == "verify":
            assert isinstance(result, f.VerifiedMathResult) and result.kind == "math"
        else:
            assert result.canonical_bytes == artifact.canonical_bytes
            assert result.value == artifact.value

    # Bounded execution gives an executable control even in the pre-K32 copy.
    succeeds(bounded, BUDGET)
    with pytest.raises(f.FIncomplete) as integer_control:
        call(bounded.canonical_bytes, reader=case.reader,
             registry=f.builtin_f_registry(), budget=small)
    assert integer_control.value.reason == "budget_exhausted"

    execution = unbounded()
    prepared = prepare(case, budget=execution)
    assert isinstance(prepared.value, f.FProblem)
    assert prepared.value.problem_key == initial.value.problem_key
    artifact = ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=execution)
    assert isinstance(artifact.value, f.Selected) and artifact.value.choice.id == "Q"
    assert any(step["args"].get("budget") == budget_json(execution)
               for step in json.loads(artifact.canonical_bytes)["calls"])
    with pytest.raises(f.FIncomplete) as stopped:
        call(artifact.canonical_bytes, reader=case.reader,
             registry=f.builtin_f_registry(), budget=small)
    assert stopped.value.reason == "budget_exhausted"
    succeeds(artifact, BUDGET)
    succeeds(artifact, unbounded(limited, base=small))
    assert tuple(case.ledger.entries()) == before


@pytest.mark.parametrize("entry", ["selected", "facts-draw"])
def test_prep1_integer_refinement_cap_includes_the_last_required_attempt(entry):
    """K32 decision 5 / scene 12: inclusive integer refinement boundaries.

    FA13 reveals by prefix n with probability (3/4)*(1-2**(-n)). Its
    information lower bound is 3/8 ln2 at n=1 and 9/16 ln2 at n=2; A gives
    1/2 ln2. Thus u=1/2 is unresolved at prefix 1 and selects W at prefix 2.
    The high-level prefix walk needs exactly N=2 attempts, not 1. Also require
    fixed-prefix evaluation to execute its last allowed attempt when the cap
    is 1; dropping that iteration must not be hidden by a larger outer cap.
    Zero is not used as a budget: integer limits must remain positive.
    """
    case = assemble("FA13")
    prepared, draw, root = bound(case, u=Q(1, 2))
    one = replace(BUDGET, tolerance=Q(1, 2), max_refinements=1)
    two = replace(one, max_refinements=2)
    before = tuple(case.ledger.entries())

    first = f.evaluate_f_prefix(root.value, steps=1, budget=one)
    pending = f.certify_f_choice(first, u=Q(1, 2))
    assert isinstance(pending, f.NoDecision) and pending.reason == "selection_boundary"
    second = f.evaluate_f_prefix(root.value, steps=2, budget=one)
    prefix_choice = f.certify_f_choice(second, u=Q(1, 2))
    assert isinstance(prefix_choice, f.Selected) and prefix_choice.choice.id == "W"

    def evaluate(budget):
        return (f.evaluate_f(root.value, budget=budget) if entry == "selected" else
                ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=budget).value)

    stopped = evaluate(one)
    assert isinstance(stopped, f.NoDecision)
    assert (stopped.outcome, stopped.reason) == ("incomplete", "budget_exhausted")
    selected = evaluate(two)
    assert isinstance(selected, f.Selected) and selected.choice.id == "W"
    assert selected.u == Q(1, 2)
    assert tuple(case.ledger.entries()) == before


def test_prep1_integer_policy_cell_cap_limits_a_zero_information_finite_chain():
    """K32 decision 5 / scene 11: policy cells, not a tiny arithmetic budget.

    One candidate Q repeats a deterministic identity/zero-time/zero-cost kernel.
    Length 1 and length 40 have the same information, cost and q*=1. Both roots
    are prepared with ample integer budgets before limiting evaluation cells.
    The short chain passes 40 cells; the long policy has 40 execute nodes plus
    end, so 40 cells cannot finish it and 41 can. Omitting the policy-cell check
    must lose the budget failure. Do not freeze free-form exception detail.
    """
    from gate_f_facts_cases import finite_world, execute

    high = replace(BUDGET, max_cells=100000, max_terms=100000)

    def root_for(length):
        document, _ = finite_world("FA01")
        policy = next(p for p in document["policies"] if p["id"] == "Q")
        policy["entry"] = "q0"
        policy["nodes"] = [
            execute("q" + str(i), "quiet", ["done"],
                    "end" if i + 1 == length else "q" + str(i + 1))
            for i in range(length)
        ] + [{"id": "end", "kind": "end"}]
        case = assemble("FA01", document=document, order=["Q"])
        return case, bound(case, u=Q(1, 2), budget=high)[2].value

    short_case, short = root_for(1)
    long_case, long = root_for(40)
    snapshots = [tuple(case.ledger.entries()) for case in (short_case, long_case)]
    limit = replace(high, max_cells=40)

    def check(result):
        assert result.candidates == ("Q",)
        assert_quantity(result.expected_cost[0], Q(0))
        assert_quantity(result.information[0].additional, Q(0))
        assert_quantity(result.q_star[0], Q(1))
        selected = f.certify_f_choice(result, u=Q(1, 2))
        assert isinstance(selected, f.Selected) and selected.choice.id == "Q"

    check(f.evaluate_f_recursive(short, budget=limit))
    with pytest.raises(f.FIncomplete) as stopped:
        f.evaluate_f_recursive(long, budget=limit)
    assert stopped.value.reason == "budget_exhausted"
    check(f.evaluate_f_recursive(long, budget=replace(limit, max_cells=41)))
    assert [tuple(case.ledger.entries()) for case in (short_case, long_case)] == snapshots


@pytest.mark.parametrize("missing", ["max_terms", "max_refinements"])
def test_prep1_facts_preflight_retains_cell_limit_after_reader_intake(missing):
    """K32 decision 5: the public preflight audit has its own cell cutoff.

    Fix cells once at the public reader's record count. The requested model,
    other records and implemented capability require more checks than that.
    Both all-int and mixed budgets must stop at /preflight, not /reader.
    If a None term/refinement cap disables audit counting, even a later /world
    budget failure must not mask the error: check the specified field too.
    Enough integer cells and no cell cap must both issue PreflightReady.
    """
    case = assemble("FA01")
    registry = f.builtin_f_registry()
    points = tuple(sorted(entry.cid for entry in case.reader.entries()))
    requested = f.FPreflightFacts(
        fixed_parents=case.fixed_parents, model=case.points["model"],
        required_records=tuple(p for p in points if p != case.points["model"]),
        required_capabilities=(f.RequiredCapability(kind="kernel",
            ref=contract("finite_kernel"), implementation_required=True),))
    small = replace(BUDGET, max_cells=len(points))
    assert small.max_cells >= len(points)
    assert 1 + len(requested.required_records) + len(requested.required_capabilities) > small.max_cells
    before = tuple(case.ledger.entries())

    def check(budget):
        return ff.check_f_preflight_from_facts(case.reader, requested,
            registry=registry, budget=budget)

    with pytest.raises(f.FIncomplete) as integer_control:
        check(small)
    assert (integer_control.value.reason, integer_control.value.field) == ("budget_exhausted", "/preflight")

    # This positive control also proves the request has no absent record or
    # capability whose diagnostic could be mistaken for budget exhaustion.
    ready = check(BUDGET)
    assert isinstance(ready.value, f.PreflightReady)

    mixed = unbounded(missing, base=small)
    with pytest.raises(f.FIncomplete) as stopped:
        check(mixed)
    assert (stopped.value.reason, stopped.value.field) == ("budget_exhausted", "/preflight")
    for enough in (replace(mixed, max_cells=BUDGET.max_cells),
                   unbounded("max_cells", base=mixed)):
        artifact = check(enough)
        assert isinstance(artifact, f.FMathArtifact) and isinstance(artifact.value, f.PreflightReady)
        body = json.loads(artifact.canonical_bytes)
        assert body["input"] == {"kind": "preflight", "value": wire(requested)}
        assert body["calls"] == [{"op": "preflight", "args": {"budget": budget_json(enough)}}]
    assert tuple(case.ledger.entries()) == before
