"""K24/K24-a (F-b v0.78 :3525-3526), with Z48: say who runs each job.

Only belief_update is dispatched to the production FiniteUpdater. Measurement,
candidate generation, preparation, draws and evaluation remain test workers.
All integration requests and ports below come from the real Boot/Post host.
No implementation body is read, patched, or used as a numerical oracle.

CG-K24-INSUFFICIENT: the current no_arrival papers/helpers do not give a
constructible request guaranteed to return Insufficient. Do not manufacture a
U response or assume a missing implementation makes this first-loop U return it.
CG-K24-REGISTRY: different worker/host registries violate the stated assembly
precondition; their runtime treatment is not specified.
CG-K24-UNAVAILABLE is closed by K24-a(c): fixed reason and empty basis below.
"""

from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from threading import Event

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role

from gate_f_facts_cases import finite_world, plain
from test_fb_skeleton import boot, contract, source
from test_fb_stage1 import RealRig, wire
from test_fb_stage2 import PREPARE_BUDGET, EVALUATE_BUDGET, LaunchCut, ORDER
from test_fb_loop import (
    LoopRig, Workers, registry, delta_args, assert_update, assert_quantity,
    execution_for, row5_report_for_work, FIRST, SECOND, DOUBLE,
)

from test_fb_belief import BeliefRig, BeliefWorkers, belief1_status, T, E, U


def updater1_api():
    # Resolve in the test, never at collection: K24 is not yet implemented.
    assert hasattr(fb, "FiniteUpdater"), "K24 public API missing: fb.FiniteUpdater"
    return fb.FiniteUpdater


class UpdaterReadError(Exception):
    """A deterministic failure in the public frozen-reader operation."""


class FailingReader(f.FReader):
    """Keep the actual frozen view; fail its record read, inside the real U call."""

    def __init__(self, reader, failures):
        self.reader, self.failures = reader, failures

    def record(self, cid):
        self.failures.append(cid)
        raise UpdaterReadError("external exception text must not enter a fact")

    def entry(self, cid):
        return self.reader.entry(cid)

    def entries(self):
        return self.reader.entries()

    def ancestors(self, frontier):
        return self.reader.ancestors(frontier)

    def sealed_content(self, cid):
        return self.reader.sealed_content(cid)


class ObservedUpdaterPort(fb.FWorkContext):
    """Delegate public port operations; observe actual reads/Post and one fault.

    No host field is accessed. The production worker, not this adapter, owns
    enter(), U and WorkFinished. Removing issued is the explicit K24(5) contrast.
    """

    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate
        self.calls, self.readings, self.posted, self.read_failures = [], [], [], []

    def enter(self):
        self.calls.append("enter")
        entered = self.delegate.enter()
        self.rig.workers.entry_attempts.append((self.work.desc.work_id, entered))
        if entered:
            self.rig.workers.entries.append(self.work)
        return entered

    def now(self):
        self.calls.append("now")
        # Two different actual M readings detect invented/reused timestamps.
        self.rig.clock.set(self.rig.clock.mono_ns() + 7)
        number = len(self.readings) + 1
        if number in self.rig.unavailable_now:
            self.readings.append(None)
            raise RuntimeError("test port cannot name the clock source")
        reading = self.delegate.now()
        self.readings.append(reading)
        return reading

    def reader(self):
        self.calls.append("reader")
        actual = self.delegate.reader()
        if self.rig.reader_mode == "none":
            return None
        assert actual is not None, "real Wu must have a frozen reader"
        if self.rig.reader_mode == "raises_in_U":
            return FailingReader(actual, self.read_failures)
        return actual

    def evidence(self):
        self.calls.append("evidence")
        return self.delegate.evidence()

    def post(self, event, issued=None):
        self.calls.append("post")
        self.posted.append((event, issued))
        self.rig.workers.sent.append((event, issued))
        if isinstance(issued, u.IssuedUpdate):
            self.rig.workers.updates[self.work.request] = issued
        self.delegate.post(event, issued=None if self.rig.drop_issued else issued)


class UpdaterWorkers(BeliefWorkers):
    def run(self, work, ctx):
        if work.desc.purpose != "belief_update":
            return super().run(work, ctx)
        self.contexts["belief_update"] = ctx
        port = ObservedUpdaterPort(self.rig, work, ctx)
        self.rig.ports[work.request] = port
        if self.rig.refuse_entry:
            assert ctx.enter()  # Consume the real start ticket, making the next enter False.
        try:
            self.rig.updater.run(work, port)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            self.stops.append(work.desc.work_id)


class UpdaterRig(BeliefRig):
    """K28 migration: production repeated source -> host Frame -> production Wu.

    T=diag(1/4,1/16), E=diag(1/2,1/4) yields FIRST/SECOND. U is the
    unused complement. No test script calls acquire or posts an evidence item.
    """
    def __init__(self, updater_type, *, continuation=False, model_zero=False,
                 reader_mode="normal", unavailable_now=(), drop_issued=False, refuse_entry=False):
        self.reader_mode, self.unavailable_now = reader_mode, unavailable_now
        self.drop_issued, self.refuse_entry = drop_issued, refuse_entry
        matrices = ({T: ((0,0),(0,0)), E: ((1,0),(0,1))} if model_zero else
            {T: ((Fraction(1,4),0),(0,Fraction(1,16))),
             E: ((Fraction(1,2),0),(0,Fraction(1,4))),
             U: ((Fraction(1,4),0),(0,Fraction(11,16)))})
        super().__init__(symbols=(T,E), matrices=matrices, targets=("x0","x1"),
            continuation=continuation, worker_type=UpdaterWorkers, updater_type=updater_type)
        self.published = 0
    def start(self):
        self.begin()
        for stage in ORDER: self.run_stage(stage)
        self.drive(lambda: len(self.facts(c.SELECTION)) == 1)
    def publish_next(self, slot, start, end):
        # Legacy labels/span arguments are test labels only; they never become
        # an interval Claim. Operation identity and time come from acquire.
        self.publish(self.published, last=self.published == 1)
        self.published += 1
    def update(self, slot, start, end):
        self.publish_next(slot, start, end)
        return self.run_stage("belief_update")


@pytest.fixture
def make_updater_rig():
    rigs = []
    def make(updater_type, **kwargs):
        rig = UpdaterRig(updater_type, **kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def assert_own_terminal(rig, work):
    """Match actual EH -> raw WorkReport -> T; no output is used as an oracle."""
    port = rig.ports[work.request]
    (event, issued), = port.posted
    assert isinstance(event, fb.WorkFinished) and event.work == work.desc.work_id
    assert len(port.readings) == 2
    for actual, reported in zip(port.readings, (event.started, event.finished)):
        if actual is None:
            assert isinstance(reported, f.Unavailable)
        else:
            assert reported == actual
    if all(reading is not None for reading in port.readings):
        assert event.started.reading.time_ns < event.finished.reading.time_ns
    observed = execution_for(port.delegate, work.desc.work_id)
    assert observed.entered == 1 and observed.stopped
    report, = observed.reports
    assert report.point is not None
    raw = rig.one(c.WORK_REPORT, cid=report.point)
    assert raw.value == wire(event) and raw.received_ns == report.received_ns
    terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request)
    assert terminal.value["first_receipt"] == raw.cid
    return event, issued, terminal


def assert_one_chain(rig, adoptions):
    assert rig.facts(c.BELIEF_ADOPTED) == adoptions
    assert [a.value["previous"] for a in adoptions] == [None, *(a.cid for a in adoptions[:-1])]
    assert len({a.value["previous"] for a in adoptions}) == len(adoptions)
    for work in (w for w in rig.workers.entries if w.desc.purpose == "belief_update"):
        execution = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert execution.entered == 1 and execution.launches == ("launched",)
    assert not rig.workers.errors and rig.host.halted is None


@pytest.mark.parametrize("continuation", (False, True), ids=("none", "reuse_candidates"))
def test_updater1_ce1_two_updates_and_continuation_use_the_production_worker(make_updater_rig, continuation):
    """K24(1)(2)(5); CE1 :2917-2923: weights (1/8,1/32), then (1/16,1/128).

    Dropping E fails SECOND; applying T twice fails SECOND != DOUBLE.
    Reusing initial at continuation fails the adopted R* input and entropy H(4/5), H(8/9).
    Omitting the live issue fails A*; invented/reused times fail the two real now() observations.
    """
    rig = make_updater_rig(updater1_api(), continuation=continuation)
    rig.start()
    previous, adoptions = None, []
    for number, expected, p in ((1, FIRST, Fraction(4, 5)), (2, SECOND, Fraction(8, 9))):
        work = rig.update(f"updater1-{number}", number - 1, number + 1)
        rig.drive(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == number)
        adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
        result = assert_update(rig, work, adopted, expected, previous)
        event, issued, terminal = assert_own_terminal(rig, work)
        assert issued is rig.workers.updates[work.request]
        assert isinstance(event.outcome, fb.WorkOutputs)
        assert event.outcome.outputs == u.update_response(issued)
        assert terminal.value["terminal_kind"] == "outputs"
        assert rig.ports[work.request].calls == ["enter", "now", "reader", "evidence", "now", "post"]
        assert plain(issued.result) != DOUBLE
        adoptions.append(adopted)
        previous = adopted.cid
        if continuation:
            rig.drive(lambda: len(rig.requests("evaluation_prepare")) == number + 1)
            ep = rig.run_stage("evaluation_prepare")
            prepared = rig.workers.prepared_by_request[ep.request]
            assert isinstance(prepared.value, f.FProblem)
            assert prepared.value.K.belief == rig.read_stored(result.cid)[2].id
            rig.run_stage("selection_draw")
            ee = rig.run_stage("evaluation")
            selected = rig.workers.evaluated_by_request[ee.request].value
            assert isinstance(selected, f.Selected)
            assert selected.root.K.belief == prepared.value.K.belief
            with localcontext() as context:
                context.prec = 60
                probability = Decimal(p.numerator) / Decimal(p.denominator)
                entropy = -(probability * probability.ln() + (1 - probability) * (1 - probability).ln())
                assert_quantity(selected.evaluation.information[1].additional, entropy)
            rig.drive(lambda: len(rig.facts(c.SELECTION)) == number + 1)
        else:
            assert len(rig.requests("evaluation_prepare")) == 1
    assert_one_chain(rig, adoptions)
    assert len(rig.facts(c.UPDATE_RESULT)) == len(adoptions) == 2
    assert len({a.value["request"] for a in adoptions}) == 2


def test_updater1_rejected_model_zero_is_normal_return_and_next_acquisition_waits(make_updater_rig):
    """K24(1)(5), :2739/:2868: zero likelihood is rejected/model_falsified, not a crash.

    Epsilon adoption or relabeling rejected as failure/insufficient fails the exact branch and no A*.
    K28 decision 5 replaces skipping a rejected report: the saved E must wait for T adoption.
    """
    rig = make_updater_rig(updater1_api(), model_zero=True)
    rig.start()
    bad = rig.update("updater1-zero", 0, 1)
    event, issued, terminal = assert_own_terminal(rig, bad)
    assert issued is None and isinstance(event.outcome, fb.WorkOutputs)
    response = plain(event.outcome.outputs.value)
    assert response["kind"] == "rejected" and response["value"]["issues"]
    assert {issue["code"] for issue in response["value"]["issues"]} == {"model_falsified"}
    # K24's transport equality, not a numerical oracle: the independent paper
    # verdict above must hold; additionally preserve every public U issue field.
    direct = u.compute_finite_update(bad.request, reader=rig.ports[bad.request].delegate.reader(),
        registry=rig.registry, evidence=rig.ports[bad.request].delegate.evidence())
    assert isinstance(direct, u.Rejected)
    assert event.outcome.outputs == u.update_response(direct)
    assert terminal.value["terminal_kind"] == "outputs"
    assert terminal.value["returned"]["value"] == wire(event.outcome.outputs)
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED) and not rig.facts(c.CONFLICT)
    original = row5_report_for_work(rig, bad)
    saved = rig.read_stored(original.cid)
    rig.publish_next("updater1-outside", 1, 2)
    for _ in range(4): rig.round()
    assert len(rig.requests("belief_update")) == 1
    assert not rig.facts(c.BELIEF_ADOPTED)
    assert rig.read_stored(original.cid) == saved
    assert belief1_status(rig, 1).outcome == "waiting_predecessor"



@pytest.mark.parametrize("reader_mode,error_type", [("raises_in_U", "UpdaterReadError"), ("none", "RuntimeError")])
def test_updater1_execution_exception_is_failure_without_external_message_and_next_acquisition_waits(
        make_updater_rig, reader_mode, error_type):
    """K24(2) step4 and reader=None: preserve execution_error, never a U verdict.

    Crashing/silently returning fails the own-port WorkFailure and T.
    Copying exception text or changing failure classification fails the exact FailureInfo.
    K28 decision 5: the later acquisition is saved, but cannot skip the failed operation.
    """
    rig = make_updater_rig(updater1_api(), reader_mode=reader_mode)
    rig.start()
    bad = rig.update("updater1-failure", 0, 2)
    event, issued, terminal = assert_own_terminal(rig, bad)
    assert issued is None and isinstance(event.outcome, fb.WorkFailure)
    assert event.outcome.failure == fb.FailureInfo(failure_kind="execution_error",
        content={"error_type": error_type}, readings=(event.started, event.finished), basis=())
    assert terminal.value["terminal_kind"] == "failure"
    if reader_mode == "raises_in_U":
        assert rig.ports[bad.request].read_failures, "fault must fire inside U's record read"
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    raw = row5_report_for_work(rig, bad)
    saved = rig.read_stored(raw.cid)
    rig.reader_mode = "normal"
    rig.publish_next("updater1-after-failure", 1, 3)
    for _ in range(4): rig.round()
    assert len(rig.requests("belief_update")) == 1
    assert not rig.facts(c.BELIEF_ADOPTED)
    assert rig.read_stored(raw.cid) == saved
    assert belief1_status(rig, 1).outcome == "waiting_predecessor"



@pytest.mark.parametrize("unavailable_now", [(1,), (2,), (1, 2)], ids=("started", "finished", "both"))
def test_updater1_unavailable_clock_reading_does_not_discard_U_result(make_updater_rig, unavailable_now):
    """K24(2), K24-a(c) :3526: now RuntimeError changes only that reading to Unavailable.

    Discarding/relabeling the computed result fails issued/FIRST and its live factory issue.
    Reusing another reading instead of Unavailable fails the branch check for each failed now().
    An empty/changed reason or nonempty basis fails the exact K24-a(c) value.
    """
    rig = make_updater_rig(updater1_api(), unavailable_now=unavailable_now)
    rig.start()
    work = rig.update("updater1-clock", 0, 2)
    event, issued, _ = assert_own_terminal(rig, work)
    readings = (event.started, event.finished)
    for number in unavailable_now:
        assert readings[number - 1] == f.Unavailable(reason="clock_source_unavailable", basis=())
    assert isinstance(event.outcome, fb.WorkOutputs) and isinstance(issued, u.IssuedUpdate)
    assert issued.request == work.request and plain(issued.result) == FIRST
    assert event.outcome.outputs == u.update_response(issued)
    assert rig.host.halted is None and not rig.workers.errors


def test_updater1_enter_false_reports_nothing_and_does_not_read(make_updater_rig):
    """K24(2) step2: no second entry, computation, now or Post after enter=False.

    Ignoring enter=False fails zero reports and the single public enter call.
    """
    rig = make_updater_rig(updater1_api(), refuse_entry=True)
    rig.start()
    rig.publish_next("updater1-no-entry", 0, 2)
    _, body = rig.callback("belief_update")
    body()
    rig.settle_steps()
    work_request, = rig.requests("belief_update")
    port = rig.ports[work_request.cid]
    assert port.calls == ["enter"] and port.posted == []
    observed = execution_for(port.delegate, work_request.value["desc"]["work_id"])
    assert observed.entered == 1 and observed.stopped and observed.reports == ()
    assert not rig.facts(c.WORK_TERMINAL) or all(
        t.value["request"] != work_request.cid for t in rig.facts(c.WORK_TERMINAL))
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)


@pytest.mark.parametrize("purpose", ["measure_segment", "candidate_generation", "selection_draw"])
def test_updater1_other_job_raises_TypeError_without_enter_or_report(make_updater_rig, purpose):
    """K24(2) step1: actual MeasureSegment, other-purpose Compute and Draw are not Wu.

    Accepting another job or entering/posting before the guard fails TypeError and an untouched port.
    """
    updater_type = updater1_api()
    rig = make_updater_rig(updater_type)
    rig.start()
    work = next(w for w in rig.workers.entries if w.desc.purpose == purpose)
    ctx = rig.workers.contexts[purpose]
    before = ctx.evidence()
    port = ObservedUpdaterPort(rig, work, ctx)
    with pytest.raises(TypeError):
        rig.updater.run(work, port)
    assert port.calls == [] and port.posted == []
    assert ctx.evidence() == before


@pytest.mark.parametrize("wrong_type", ["MeasureSegment", "Draw"])
def test_updater1_update_purpose_on_a_non_Compute_is_still_a_TypeError(make_updater_rig, wrong_type):
    """K24(2) step1 requires both Compute and the update purpose, not just a label.

    Checking purpose alone fails TypeError for a public non-Compute wrapper around the same Wu Desc.
    """
    rig = make_updater_rig(updater1_api())
    rig.start()
    work = rig.update("updater1-wrong-wrapper", 0, 2)
    wrong_work = getattr(fb, wrong_type)(request=work.request, desc=work.desc)
    ctx = rig.workers.contexts["belief_update"]
    before = ctx.evidence()
    port = ObservedUpdaterPort(rig, work, ctx)
    with pytest.raises(TypeError):
        rig.updater.run(wrong_work, port)
    assert port.calls == [] and port.posted == [] and ctx.evidence() == before


def test_updater1_issued_without_the_live_artifact_cannot_be_adopted(make_updater_rig):
    """K24(5), K7 :3507: identical issued JSON is insufficient without the live issue.

    Trusting JSON alone fails no R*/A*; not actually computing fails issued/FIRST in the intercepted Post.
    """
    rig = make_updater_rig(updater1_api(), drop_issued=True)
    rig.start()
    work = rig.update("updater1-drop-issue", 0, 2)
    event, issued, terminal = assert_own_terminal(rig, work)
    assert isinstance(issued, u.IssuedUpdate) and plain(issued.result) == FIRST
    assert isinstance(event.outcome, fb.WorkOutputs) and event.outcome.outputs == u.update_response(issued)
    assert terminal.value["terminal_kind"] == "outputs"
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    assert rig.host.halted is None and not rig.workers.errors
