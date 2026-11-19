"""K33 (F-b :3557, :4693-4786 after K33-a): public surfaces/test fixtures only.

No production function body or private module is read, patched, or imported.
Native names are resolved per case, so absence does not prevent collection.
The flat FA14 policy has one execute node and one back-edge. With a finite
horizon its declarations/cycle proof stay shallow; the evaluated walk grows.
The FA13 prefix retains unbounded_total and a nonzero tail, rather than changing
the scope to make a deep prefix look complete. Deep cases have no cell/term cap.
Neither the tests nor the library are allowed to change Python's recursion limit.

Discrimination (one mutation per line):
- Reusing the finish reading as started fails the ordered public-port trace.
- Reading saved PR instead of ctx.prepared(), or bypassing ctx.reader(), fails
  the port fence and genuine issue's input/reader/draw associations.
- Changing the budget or retrying changes recorded calls or repeats real public
  registry callbacks compared with a single evaluation of identical inputs.
- Returning NoDecision as failure loses the genuine outputs issue and host EV.
- Escaping errors, open reason/field text, or relabelling RecursionError fails
  the exact WorkFailure and saved-terminal assertions.
- Any fixed depth cutoff fails a >256 completed walk or the natural recursion
  failure; a call to sys.setrecursionlimit fails the public standard-library spy.
- Removing semantic cycle/horizon stops fails their independent shallow controls.
- Altering bind_draw vs later evaluation budgets fails distinct host holds.

K33 (4) explicitly does not promise replay compatibility for old NoDecision
artifacts produced by the removed 256 guard; no fabricated old issue is used.
All timeouts are safety bounds for incomplete observations, not product promises.
"""

from dataclasses import replace
from fractions import Fraction as Q
from inspect import signature
import json
import sys

import pytest

from sui import f, fb, fb_contracts as c, f_facts as ff
from gate_f_facts_cases import BUDGET, assemble, bound, prepare, add_draw, finite_world
from test_fb_skeleton import contract, desc, point
from test_fb_stage1 import wire
from test_fb_stage2 import (
    Stage2Rig, ORDER, MATH, EVALUATE_BUDGET,
    terminal, assert_absent,
)
from test_fb_preparer import (
    PreparationPort, PreparationLoopRig, CLOSED_REASONS, CAPS, unbounded,
    budget_json, counted_registry,
)
from test_fb_belief import ROUTE, belief1_chain
from test_gate_f_contract import assert_quantity


def evaluator_type():
    assert hasattr(fb, "Evaluator"), "K33 public API missing: fb.Evaluator"
    return fb.Evaluator


def evaluation_work(draw, budget=BUDGET, *, label="one"):
    args = fb.EvaluationArgs(evaluation_request=point("K33-E-" + label),
        prepared=point("K33-PR-" + label), draw=draw, budget=budget)
    d = replace(desc("evaluation"), work_id="K33-Ee-" + label,
                method=c.EVALUATE_FROM_DRAW, output_contract=MATH, args=args)
    return fb.Compute(request=point("K33-request-" + label), desc=d)


class EvaluationPort(PreparationPort):
    def __init__(self, reader, prepared, **kwargs):
        super().__init__(reader, **kwargs)
        self.issue = prepared
    def prepared(self):
        self.trace.append(("prepared",))
        return self.issue
    def read(self, cid):
        raise AssertionError("K33: saved PR/body is not the live ctx.prepared()")


def completed(port, work):
    assert len(port.posts) == 1 and len(port.readings) == 2
    event, issued = port.posts[0]
    assert isinstance(event, fb.WorkFinished) and event.work == work.desc.work_id
    assert port.trace[0] == ("enter",) and port.trace[-1] == ("post",)
    nows = [i for i, op in enumerate(port.trace) if op == ("now",)]
    reads = [i for i, op in enumerate(port.trace)
             if op[0] not in ("enter", "now", "post")]
    assert len(nows) == 2 and reads and nows[0] < min(reads) <= max(reads) < nows[1]
    for name in ("reader", "prepared"):
        count = port.trace.count((name,))
        # Either missing dependency may short-circuit the other getter. The
        # contract does not order these getters or require useless reads.
        assert count <= 1
        if port.view is not None and port.issue is not None: assert count == 1
    for actual, observed in zip((event.started, event.finished), port.readings):
        assert actual == (f.Unavailable(reason="clock_source_unavailable", basis=())
                          if observed is None else observed)
    return event, issued


def outputs(port, work, expected):
    event, issued = completed(port, work)
    assert isinstance(event.outcome, fb.WorkOutputs)
    assert isinstance(issued, f.FMathArtifact) and isinstance(issued.value, expected)
    assert event.outcome.outputs.contract == work.desc.output_contract
    body = json.loads(issued.canonical_bytes)
    assert wire(event.outcome.outputs.value) == body
    binds = [call for call in body["calls"] if call["op"] == "bind_draw"]
    assert len(binds) == 1 and binds[0]["args"]["draw"] == work.desc.args.draw
    assert binds[0]["args"]["budget"] == budget_json(work.desc.args.budget)
    later = body["calls"][body["calls"].index(binds[0]) + 1:]
    assert later and all(call["args"]["budget"] == budget_json(work.desc.args.budget)
                         for call in later if "budget" in call["args"])
    return issued


def failure(port, work, *, error_type=None, content=None):
    event, issued = completed(port, work)
    assert issued is None and isinstance(event.outcome, fb.WorkFailure)
    assert event.outcome.failure.failure_kind == "execution_error"
    actual = wire(event.outcome.failure.content)
    if content is not None: assert actual == content
    else:
        assert set(actual) == {"error_type"}
        assert isinstance(actual["error_type"], str) and actual["error_type"].isidentifier()
        if error_type is not None: assert actual["error_type"] == error_type
    return event


def inputs(name="FA01", *, u=Q(1, 4), budget=BUDGET, registry=None):
    case = assemble(name)
    issued = prepare(case, budget=budget, registry=registry)
    assert isinstance(issued.value, f.FProblem)
    draw = add_draw(case, issued.value.problem_key, u=u)
    return case, issued, draw


def test_eval1_public_constructor_run_and_export():
    cls = evaluator_type()
    assert signature(cls).parameters == {}
    assert tuple(signature(cls.run).parameters) == ("self", "work", "ctx")
    assert "Evaluator" in fb.__all__
    assert callable(cls().run)


@pytest.mark.parametrize("case_name,u,choice", [("FA01", Q(1, 4), "Q"), ("FA01", Q(1, 2), "M")])
def test_eval1_native_selected_uses_only_current_port_issue_reader_draw_and_budget(case_name, u, choice):
    cls = evaluator_type()
    reg, calls = counted_registry(f.builtin_f_registry())
    case, prepared, draw = inputs(case_name, u=u, registry=reg)
    # Observe one real public evaluation, not a test worker's claimed result.
    calls.clear()
    ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=BUDGET)
    once = tuple(calls); calls.clear()
    work = evaluation_work(draw); port = EvaluationPort(case.reader, prepared)
    if u == Q(1, 4):
        work = replace(work, desc=replace(work.desc, output_contract=contract("k33.test.math_output")))
    before = tuple(case.ledger.entries())
    cls().run(work, port)
    issued = outputs(port, work, f.Selected)
    assert issued.value.choice.id == choice and issued.value.u == u
    # FA01: Q adds no information, M reveals one fair bit. Zero costs give
    # exp(0):exp(ln 2) = 1:2, independently of either worker's implementation.
    assert issued.value.evaluation.candidates == ("Q", "M")
    for actual, expected in zip(issued.value.evaluation.q_star, (Q(1, 3), Q(2, 3))):
        assert_quantity(actual, expected)
    assert tuple(calls) == once, "native worker must not retry the requested evaluation"
    assert tuple(case.ledger.entries()) == before


@pytest.mark.parametrize("cap", CAPS)
def test_eval1_native_small_integer_limit_is_no_decision_and_none_can_finish(cap):
    cls = evaluator_type()
    case, prepared, draw = inputs("FA13", u=Q(1, 2))
    # Sixteen cells admit the immutable reader and draw, then exhaust the
    # actual FA13 evaluation. One cell would test intake failure instead.
    small = replace(BUDGET, **{cap: 16 if cap == "max_cells" else 1})
    worker = cls()
    for budget, expected in [(small, f.NoDecision), (unbounded(cap), f.Selected)]:
        work = evaluation_work(draw, budget); port = EvaluationPort(case.reader, prepared)
        worker.run(work, port); issue = outputs(port, work, expected)
        if expected is f.NoDecision: assert issue.value.reason == "budget_exhausted"
        else: assert issue.value.choice.id == "W"


@pytest.mark.parametrize("missing", ["reader", "prepared"])
def test_eval1_missing_port_dependency_is_execution_failure(missing):
    cls = evaluator_type(); case, prepared, draw = inputs()
    port = EvaluationPort(None if missing == "reader" else case.reader,
                          None if missing == "prepared" else prepared)
    work = evaluation_work(draw); cls().run(work, port)
    failure(port, work)  # K33 does not name the exception used to detect None.


class EvaluationError(Exception):
    pass


class AttributedError(Exception):
    reason, field = "budget_exhausted", "/private"


@pytest.mark.parametrize("error", [EvaluationError("private"), KeyError("private"),
                                   RuntimeError("private"), RecursionError("private"),
                                   AttributedError("private")], ids=lambda x: type(x).__name__)
def test_eval1_public_reader_exception_is_failure_without_open_reason(error):
    cls = evaluator_type(); case, prepared, draw = inputs()
    port = EvaluationPort(case.reader, prepared, error=error)
    work = evaluation_work(draw); cls().run(work, port)
    failure(port, work, error_type=type(error).__name__)


@pytest.mark.parametrize("reason", CLOSED_REASONS + ("not_a_closed_reason",))
@pytest.mark.parametrize("field", ["/reader", "private", None, 17])
def test_eval1_incomplete_reason_and_field_are_filtered_exactly(reason, field):
    cls = evaluator_type(); case, prepared, draw = inputs()
    port = EvaluationPort(case.reader, prepared,
        error=f.FIncomplete(reason, "private exception text", field=field))
    work = evaluation_work(draw); cls().run(work, port)
    content = {"error_type": "FIncomplete"}
    if reason in CLOSED_REASONS:
        content.update(reason=reason, field=field if isinstance(field, str) and field.startswith("/") else None)
    failure(port, work, content=content)


@pytest.mark.parametrize("unavailable", [(), (0,), (1,)])
@pytest.mark.parametrize("failed", [False, True])
def test_eval1_clock_boundaries_and_unilateral_unavailable(unavailable, failed):
    cls = evaluator_type(); case, prepared, draw = inputs()
    port = EvaluationPort(case.reader, prepared, unavailable=unavailable,
                          error=EvaluationError() if failed else None)
    work = evaluation_work(draw); cls().run(work, port)
    if failed: failure(port, work, error_type="EvaluationError")
    else: outputs(port, work, f.Selected)
    if not unavailable:
        assert port.posts[0][0].started.reading.time_ns < port.posts[0][0].finished.reading.time_ns


@pytest.mark.parametrize("purpose", ["candidate_generation", "belief_update", "evaluation_prepare", "selection_draw"])
def test_eval1_wrong_purpose_is_type_error_before_admission(purpose):
    cls = evaluator_type(); work = evaluation_work(point("draw"))
    work = replace(work, desc=replace(work.desc, purpose=purpose))
    port = EvaluationPort(None, None)
    with pytest.raises(TypeError): cls().run(work, port)
    assert port.trace == [] and port.posts == []


def test_eval1_non_compute_is_type_error_before_admission():
    cls = evaluator_type(); port = EvaluationPort(None, None)
    with pytest.raises(TypeError): cls().run(object(), port)
    assert port.trace == []


def test_eval1_false_admission_has_no_other_operation():
    cls = evaluator_type(); port = EvaluationPort(None, None, enter=False)
    cls().run(evaluation_work(point("draw")), port)
    assert port.trace == [("enter",)] and port.posts == []


@pytest.mark.parametrize("failed", [False, True])
def test_eval1_post_failure_escapes_without_second_report(failed):
    cls = evaluator_type(); case, prepared, draw = inputs()
    error = OSError("private post text")
    port = EvaluationPort(case.reader, prepared, post_error=error,
                          error=EvaluationError() if failed else None)
    with pytest.raises(OSError) as caught: cls().run(evaluation_work(draw), port)
    assert caught.value is error and len(port.posts) == 1


def test_eval1_same_worker_does_not_reuse_problem_draw_or_budget():
    cls = evaluator_type(); worker = cls(); issues = []
    for i, (name, u, budget) in enumerate([
            ("FA01", Q(1, 4), BUDGET), ("FA13", Q(1, 2), unbounded())]):
        case, prepared, draw = inputs(name, u=u, budget=budget)
        work = evaluation_work(draw, budget, label=str(i))
        port = EvaluationPort(case.reader, prepared); worker.run(work, port)
        issue = outputs(port, work, f.Selected)
        assert issue.value.choice.id == ("Q" if i == 0 else "W")
        issues.append(issue)
    assert issues[0].value.root.problem_key != issues[1].value.root.problem_key
    assert issues[0].value.u != issues[1].value.u


class HostEvaluationPort(fb.FWorkContext):
    """Only forward public operations; association negatives use genuine issues."""
    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate
    def enter(self):
        entered = self.delegate.enter()
        if entered:
            self.rig.workers.entries.append(self.work)
            self.rig.workers.contexts["evaluation"] = self.delegate
        return entered
    def now(self):
        self.rig.clock.set(self.rig.clock.mono_ns() + 7)
        return self.delegate.now()
    def reader(self):
        self.rig.evaluation_reader = self.delegate.reader()
        if self.rig.reader_error is not None:
            self.rig.evaluation_reader = FaultingReader(self.rig.evaluation_reader, self.rig.reader_error)
        return self.rig.evaluation_reader
    def prepared(self):
        self.rig.evaluation_problem = self.delegate.prepared()
        return self.rig.evaluation_problem
    def post(self, event, issued=None):
        self.rig.evaluation_posts.append((self.work, event, issued))
        if self.rig.replace_evaluation_issue is not None:
            issued = self.rig.replace_evaluation_issue(self.work,
                self.rig.evaluation_reader, self.rig.evaluation_problem)
            event = replace(event, outcome=fb.WorkOutputs(outputs=f.ContractValue(
                contract=self.work.desc.output_contract, value=json.loads(issued.canonical_bytes))))
        self.rig.workers.sent.append((event, issued))
        self.rig.workers.issued["evaluation"] = issued
        self.delegate.post(event, issued=issued)
    def read(self, cid): raise AssertionError("native evaluator must not compare saved PR")


class HostEvaluatorProbe:
    def __init__(self, rig, worker): self.rig, self.worker = rig, worker
    def run(self, work, ctx): return self.worker.run(work, HostEvaluationPort(self.rig, work, ctx))


class FaultingReader(f.FReader):
    """A public reading operation can fail by running another public calculation."""
    def __init__(self, delegate, error): self.delegate, self.error = delegate, error
    def fail(self):
        self.error()
        raise AssertionError("K33: a natural deep walk must not return a fixed-depth NoDecision")
    def entry(self, cid): return self.fail()
    def entries(self): return self.fail()
    def record(self, cid): return self.fail()
    def ancestors(self, frontier): return self.fail()
    def sealed_content(self, cid): return self.fail()


class EvaluationRig(Stage2Rig):
    def __init__(self, cls, *, budget=EVALUATE_BUDGET, replace_issue=None,
                 reader_error=None):
        super().__init__(auto_boot=False, evaluate_budget=budget)
        self.evaluation_posts = []
        self.replace_evaluation_issue = replace_issue
        self.reader_error = reader_error
        self.evaluation_reader = self.evaluation_problem = None
        self.native_evaluator = cls()
        workers = {stage: self.workers for stage in (
            "candidate_generation", "measure_segment", "belief_update", "evaluation_prepare", "selection_draw", "evaluation")}
        workers["evaluation"] = HostEvaluatorProbe(self, self.native_evaluator)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock,
            workers=fb.WorkerBundle(workers), registry=self.registry, launcher=self.launcher)
        self.host.post(self.clock_event); self.host.post(self.boot_input)


@pytest.fixture
def rigs():
    active = []
    def register(rig): active.append(rig); return rig
    yield register
    for rig in reversed(active): rig.close()


@pytest.mark.parametrize("nulls", [(), ("max_cells",), ("max_terms",), ("max_refinements",), CAPS])
def test_eval1_host_accepts_matching_bind_and_evaluation_budgets_and_selects(rigs, nulls):
    cls = evaluator_type()
    budget = unbounded(*nulls, base=EVALUATE_BUDGET) if nulls else EVALUATE_BUDGET
    rig = rigs(EvaluationRig(cls, budget=budget)); rig.through("evaluation")
    work, event, issued = rig.evaluation_posts[0]
    assert isinstance(issued.value, f.Selected) and issued.value.choice.id == "Q"
    assert issued.value.u == Q(1, 4)
    body = json.loads(issued.canonical_bytes)
    bind = next(i for i, call in enumerate(body["calls"]) if call["op"] == "bind_draw")
    assert body["calls"][bind]["args"]["budget"] == budget_json(budget)
    assert all(call["args"]["budget"] == budget_json(budget)
               for call in body["calls"][bind + 1:] if "budget" in call["args"])
    rig.drive(lambda: bool(rig.facts(c.SELECTION)))
    assert rig.one(MATH, cid=rig.one(c.EVALUATED).value["artifact"]).value == body
    assert terminal(rig, work).value["returned"] == {"kind": "output", "value": wire(event.outcome.outputs)}
    assert rig.host.halted is None


def test_eval1_host_preserves_no_decision_as_outputs_without_selection(rigs):
    cls = evaluator_type()
    rig = rigs(EvaluationRig(cls, budget=replace(EVALUATE_BUDGET, max_terms=1)))
    rig.through("evaluation")
    work, event, issued = rig.evaluation_posts[0]
    assert isinstance(issued.value, f.NoDecision) and issued.value.reason == "budget_exhausted"
    assert isinstance(event.outcome, fb.WorkOutputs)
    assert terminal(rig, work).value["terminal_kind"] == "outputs"
    assert rig.one(MATH, cid=rig.one(c.EVALUATED).value["artifact"]).value == json.loads(issued.canonical_bytes)
    assert any(row.response == "no_decision" for row in rig.host.window.status().readings)
    assert_absent(rig, (c.SELECTION,))


@pytest.mark.parametrize("mutation,reason", [
    ("bind-budget", "artifact:draw"), ("later-budget", "artifact:budget")])
def test_eval1_host_distinguishes_bind_draw_and_later_budget_association(rigs, mutation, reason):
    """K33 :4774 permits bind budget OR draw; use a genuine changed budget.

    A different draw in an expanded reader fails environment association first;
    a changed reported call with the original issue fails output association.
    Neither is counted as this isolated draw-binding contrast. The genuine
    changed-budget issue keeps the reader and every other binding unchanged.
    """
    cls = evaluator_type()
    budget = unbounded(base=EVALUATE_BUDGET)
    def substitute(work, reader, prepared):
        other = replace(budget, max_terms=100000)
        draw = work.desc.args.draw
        if mutation == "bind-budget":
            return ff.evaluate_f_from_draw(prepared, draw, reader=reader, budget=other)
        root = ff.bind_f_draw(prepared, draw, reader=reader, budget=budget)
        value = f.evaluate_f(root.value, budget=other)
        return ff.restore_f_math_result(ff.f_math_json(value), reader=reader,
                                       registry=rig.registry, budget=BUDGET)
    rig = rigs(EvaluationRig(cls, budget=budget, replace_issue=substitute))
    rig.through("evaluation")
    reasons = [row.reason for row in rig.host.window.status().pending]
    assert reason in reasons, reasons
    assert_absent(rig, (c.EVALUATED, c.SELECTION))
    assert rig.host.halted is None


def flat_document():
    document, _ = finite_world("FA14")
    for kernel in document["kernels"]:
        if kernel["id"] == "quiet":
            for outcome in kernel["outcomes"]: outcome["elapsed_ns"] = 1
    return document


def flat_case(horizon=None):
    return assemble("FA14", document=flat_document(), order=["Q"],
                    H=horizon, scope_name="unbounded_total" if horizon is None else "finite_horizon")


@pytest.fixture
def unchanged_recursion_limit(monkeypatch):
    before = sys.getrecursionlimit()
    calls = []
    def forbidden(limit):
        calls.append(limit)
        raise AssertionError("K33: sui must not set Python's recursion limit")
    monkeypatch.setattr(sys, "setrecursionlimit", forbidden)
    yield before
    assert calls == [] and sys.getrecursionlimit() == before


def assert_quiet_choice(result):
    assert isinstance(result, f.Selected), "K33: fixed-depth guard must not replace a completed walk"
    assert result.choice.id == "Q" and result.u == Q(1, 2)


@pytest.mark.parametrize("horizon", [4, 258], ids=["shallow-control", "over-256"])
def test_eval1_full_finite_horizon_walk_completes_without_a_fixed_depth_cap(horizon, unchanged_recursion_limit):
    budget = unbounded(); case = flat_case(horizon)
    prepared, draw, root = bound(case, budget=budget)
    before = tuple(case.ledger.entries())
    selected = ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=budget)
    assert_quiet_choice(selected.value)
    evaluation = f.evaluate_f_recursive(root.value, budget=budget)
    assert evaluation.candidates == ("Q",)
    assert_quantity(evaluation.information[0].additional, Q(0))
    assert_quantity(evaluation.expected_cost[0], Q(0))
    assert_quantity(evaluation.q_star[0], Q(1))
    assert root.value.scope.name == "finite_horizon" and root.value.scope.H_ns == horizon
    assert tuple(case.ledger.entries()) == before


@pytest.mark.parametrize("steps", [2, 258], ids=["shallow-control", "over-256"])
def test_eval1_unbounded_prefix_walk_keeps_scope_and_nonzero_tail(steps, unchanged_recursion_limit):
    budget = unbounded(); case = assemble("FA13")
    _, _, root = bound(case, u=Q(1, 2), budget=budget)
    result = f.evaluate_f_prefix(root.value, steps=steps, budget=budget)
    choice = f.certify_f_choice(result, u=Q(1, 2))
    assert isinstance(choice, f.Selected) and choice.choice.id == "W"
    assert result.root.scope.name == "unbounded_total" and result.root.scope.H_ns is None
    tail = next(t for t in result.tails if t.candidate == "W")
    # Residual is the never-arriving 1/4 plus pending 3/4 * 2**(-n),
    # not a fabricated zero that would turn a prefix into a complete tree.
    assert_quantity(tail.residual_mass, Q(1, 4) + Q(3, 4 * 2**steps))
    assert tail.closure != "zero"


def test_eval1_unbounded_cycle_still_stops_semantically_and_horizon_finishes(unchanged_recursion_limit):
    budget = unbounded(); case = flat_case()
    _, _, root = bound(case, budget=budget)
    with pytest.raises(f.FIncomplete) as caught:
        f.enumerate_f_paths(root.value, budget=budget)
    assert caught.value.reason == "certificate_incomplete"
    finite = flat_case(3); p, d, _ = bound(finite, budget=budget)
    assert_quiet_choice(ff.evaluate_f_from_draw(p, d, reader=finite.reader, budget=budget).value)


def test_eval1_natural_walk_recursion_error_propagates_from_public_math(unchanged_recursion_limit):
    # A flat back-edge proves this is dynamic walking, not a deeply nested
    # declaration or a long acyclic-policy proof. No exact failing depth is fixed.
    case = flat_case(unchanged_recursion_limit * 2)
    budget = unbounded(); prepared, draw, _ = bound(case, budget=budget)
    with pytest.raises(RecursionError):
        ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=budget)


def test_eval1_native_real_walk_limit_is_execution_failure(unchanged_recursion_limit):
    cls = evaluator_type()
    case = flat_case(unchanged_recursion_limit * 2); budget = unbounded()
    prepared, draw, _ = bound(case, budget=budget)
    work = evaluation_work(draw, budget); port = EvaluationPort(case.reader, prepared)
    cls().run(work, port)
    failure(port, work, content={"error_type": "RecursionError"})


def test_eval1_host_saves_native_recursion_failure_and_accepts_next_work(rigs, unchanged_recursion_limit):
    # H2 accepts blank preferences only. Keep that host path and make a public
    # reader operation perform the independent flat-policy calculation below.
    # Its REAL walk RecursionError crosses the reader boundary unmodified. The
    # evaluator receives the host's actual prepared problem; no PR is forged.
    # The separate worker case above also evaluates the deep problem directly.
    cls = evaluator_type()
    deep = flat_case(unchanged_recursion_limit * 2); budget = unbounded()
    prepared, draw, _ = bound(deep, budget=budget)
    def natural_walk_failure():
        ff.evaluate_f_from_draw(prepared, draw, reader=deep.reader, budget=budget)
    rig = rigs(EvaluationRig(cls, reader_error=natural_walk_failure))
    rig.through("evaluation")
    work, event, issued = rig.evaluation_posts[0]
    assert issued is None and isinstance(event.outcome, fb.WorkFailure)
    assert wire(event.outcome.failure.content) == {"error_type": "RecursionError"}
    t = terminal(rig, work)
    assert t.value["terminal_kind"] == "failure" and t.value["returned"] is None
    saved_failure = t.value["basis"]["failure"]
    assert saved_failure["failure_kind"] == "execution_error"
    assert saved_failure["content"] == {"error_type": "RecursionError"}
    assert any(row.response == "failure" for row in rig.host.window.status().readings)
    assert_absent(rig, (c.EVALUATED, c.SELECTION))
    # The independent measuring request is the next real host job. TEST worker
    # just enters/returns; no fabricated acquire or evaluation report is used.
    rig.drive(lambda: bool(rig.facts(c.SEGMENT_REQUESTED)))
    wid = rig.one(c.SEGMENT_REQUESTED).value["desc"]["work_id"]
    rig.drive(lambda: any(key == wid for key, _ in rig.launcher.attempts))
    next(body for key, body in rig.launcher.attempts if key == wid)()
    rig.settle_steps()
    assert any(w.desc.work_id == wid for w in rig.workers.entries)
    assert wid in rig.workers.stops and rig.host.halted is None


@pytest.mark.parametrize("branch", ["full-horizon", "unbounded-prefix"])
@pytest.mark.parametrize("depth", [4, 258], ids=["shallow-control", "over-256"])
def test_eval1_over_256_evaluation_is_verifiable_and_restorable(branch, depth, unchanged_recursion_limit):
    budget = unbounded()
    case = flat_case(depth) if branch == "full-horizon" else assemble("FA13")
    prepared, draw, root = bound(case, budget=budget)
    if branch == "full-horizon":
        issue = ff.evaluate_f_from_draw(prepared, draw, reader=case.reader, budget=budget)
        assert_quiet_choice(issue.value)
        data = issue.canonical_bytes
    else:
        evaluation = f.evaluate_f_prefix(root.value, steps=depth, budget=budget)
        assert isinstance(f.certify_f_choice(evaluation, u=Q(1, 2)), f.Selected)
        data = ff.f_math_json(evaluation)
    # Persist bytes as an ordinary fact, then replay through public factories.
    saved = case.observe("K33-math", MATH, json.loads(data))
    persisted = case.reader.record(saved).body.content.data
    assert json.loads(persisted) == json.loads(data)
    before = tuple(case.ledger.entries())
    checked = ff.verify_f_math_result(data, reader=case.reader,
        registry=f.builtin_f_registry(), budget=budget)
    assert isinstance(checked, f.VerifiedMathResult) and checked.kind == "math"
    assert checked.root_key == root.value.root_key
    restored = ff.restore_f_math_result(data, reader=case.reader,
        registry=f.builtin_f_registry(), budget=budget)
    assert isinstance(restored, f.FMathArtifact) and restored.canonical_bytes == data
    if branch == "full-horizon": assert_quiet_choice(restored.value)
    else:
        assert isinstance(restored.value, f.FEvaluation)
        assert restored.value.root.scope.name == "unbounded_total"
        assert f.certify_f_choice(restored.value, u=Q(1, 2)).choice.id == "W"
    assert tuple(case.ledger.entries()) == before


class EvaluationLoopRig(PreparationLoopRig):
    """Native M/U/Cg/Ep/Ee in the bundle; only D stays a TEST capability."""
    def __init__(self, cls):
        super().__init__(fb.EvaluationPreparer)
        self.evaluation_posts, self.replace_evaluation_issue = [], None
        self.reader_error = None
        self.evaluation_reader = self.evaluation_problem = None
        self.native_evaluator = cls()
        self.bundle_workers["evaluation"] = HostEvaluatorProbe(self, self.native_evaluator)
        self.bundle = fb.WorkerBundle(self.bundle_workers)
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.bundle,
            registry=self.registry, launcher=self.launcher, sources={ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=self.clock_declaration)); self.host.post(self.boot_input)
    def run_stage(self, stage):
        if stage != "evaluation": return super().run_stage(stage)
        request, body = self.callback(stage)
        wid = request.value["desc"]["work_id"]
        self.executed.add(wid); body()
        self.drive(lambda: any(x.value["work"] == wid for x in self.facts(c.WORK_REPORT)))
        self.settle_steps()


def test_eval1_main_loop_native_measure_update_candidates_prepare_evaluate_and_three_choices(rigs):
    cls = evaluator_type(); rig = rigs(EvaluationLoopRig(cls))
    assert rig.bundle_workers["measure_segment"] is rig.native_measurer
    assert rig.bundle_workers["belief_update"] is rig.native_updater
    assert type(rig.bundle_workers["candidate_generation"]) is fb.CandidateGenerator
    assert rig.bundle_workers["evaluation_prepare"].worker is rig.native_preparer
    assert rig.bundle_workers["evaluation"].worker is rig.native_evaluator
    assert rig.bundle_workers["selection_draw"] is rig.workers
    rig.start()
    expected = ({"joint": [[4, 5], [1, 5]], "evidence_mass": [5, 32]},
                {"joint": [[8, 9], [1, 9]], "evidence_mass": [9, 128]})
    for index in range(2):
        rig.publish(index, last=index == 1); rig.update()
        for stage in ORDER[1:]: rig.run_stage(stage)
        rig.until(lambda: len(rig.facts(c.SELECTION)) == index + 2)
    belief1_chain(rig, expected)
    assert len(rig.evaluation_posts) == len(rig.facts(c.EVALUATED)) == 3
    assert all(isinstance(issue.value, f.Selected) for _, _, issue in rig.evaluation_posts)
    assert len(rig.reports("frame")) == len(rig.source.calls) == 2
    assert len(rig.facts(c.SELECTION)) == 3
    assert rig.host.halted is None and not rig.host.interruptions()


def test_eval1_public_math_and_replay_entry_signatures_are_unchanged():
    assert tuple(signature(ff.evaluate_f_from_draw).parameters) == (
        "prepared", "draw_record_ref", "reader", "budget")
    for name in ("reader", "budget"):
        assert signature(ff.evaluate_f_from_draw).parameters[name].kind.name == "KEYWORD_ONLY"
    assert tuple(signature(f.evaluate_f).parameters) == ("root", "budget", "resume")
    assert tuple(signature(f.evaluate_f_prefix).parameters) == ("root", "steps", "budget")
    for read in (ff.verify_f_math_result, ff.restore_f_math_result):
        assert tuple(signature(read).parameters) == ("data", "reader", "registry", "budget")


def test_eval1_recursive_unbounded_cycle_preserves_revisit_stop_and_returns_zero_information(unchanged_recursion_limit):
    """K33 decision 5 / scene 11 (:4726, :4777 after K33-a).

    Unlike T18's complete-enumeration precheck, evaluate_f_recursive evaluates
    the unbounded policy with no steps bound. Q is a flat identity-kernel loop:
    no new information, no costs, and probability one of never terminating.
    The semantic revisit stop lets the public evaluator account for that tail
    and return FEvaluation; the low-level certificate_incomplete need not escape
    this entry. Removing that stop must fail to produce this finite answer.

    No cutoff depth, recursion-limit change, private trace/counter, or production
    patch is used. RecursionError/budget failure is not caught as a passing case.
    """
    budget = unbounded()
    case = flat_case()
    _, _, root = bound(case, budget=budget)
    assert root.value.scope.name == "unbounded_total" and root.value.scope.H_ns is None
    before = tuple(case.ledger.entries())

    result = f.evaluate_f_recursive(root.value, budget=budget)

    assert isinstance(result, f.FEvaluation)
    assert result.root == root.value and result.candidates == ("Q",)
    assert_quantity(result.information[0].additional, Q(0))
    assert_quantity(result.expected_cost[0], Q(0))
    assert_quantity(result.q_star[0], Q(1))
    assert_quiet_choice(f.certify_f_choice(result, u=Q(1, 2)))
    assert tuple(case.ledger.entries()) == before
