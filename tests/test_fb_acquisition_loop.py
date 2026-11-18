"""K28 migration of launch/admission, long work, and pending-delivery probes.

SourceMeasurer and FiniteUpdater own the two production jobs. The test changes
only sources, launch scheduling, and a forwarding public work port. It never
calls acquire or posts a fabricated Frame/interval Claim.
"""

from fractions import Fraction as Q
from threading import Event, Thread

import pytest

from sui import f, fb, fb_contracts as c
from test_fb_belief import BeliefRig, T, E, U
from test_fb_loop import (
    FIRST, SECOND, assert_update, cut_first_update_launch, execution_for,
    row5_report_for_work,
)
from test_fb_stage1 import wire
from test_fb_stage2 import ORDER
from test_fb_measure import acquire1_expected_frame


MATRICES = {
    T: ((Q(1, 4), Q(0)), (Q(0), Q(1, 16))),
    E: ((Q(1, 2), Q(0)), (Q(0), Q(1, 4))),
    U: ((Q(1, 4), Q(0)), (Q(0), Q(11, 16))),
}


def sequence_answer(symbols):
    """Independent diagonal product: p0=(1/2,1/2), paper K28 decision 1."""
    a = b = Q(1, 2)
    for symbol in symbols:
        a *= Q(1, 4) if symbol == T else Q(1, 2)
        b *= Q(1, 16) if symbol == T else Q(1, 4)
    mass = a + b
    return wire({"joint": (a / mass, b / mass), "evidence_mass": mass})


def test_rowI_late_conflict_identical_redelivery_keeps_the_adoption_chain(make_acquisition_probe):
    """K28-b(sa): keep the redelivery control, using the ORIGINAL acquire envelope.

    Counting its retry twice, making a conflict, losing historical facts or
    forking the next prior fails FIRST->SECOND and three completed selections.
    A new producer Post of this Frame is deliberately not used (Z55).
    """
    rig = make_acquisition_probe(continuation=True)
    rig.start()
    first, head = rig.adopt(1)
    assert_update(rig, first, head, FIRST)
    call = rig.calls[0]
    raw, (observed, frame) = rig.saved_pair(call)
    event = fb.SegmentReport(segment=call.work.request, item_slot="frame:0",
        item=acquire1_expected_frame(rig, call, raw[1]))
    assert wire(event) == frame.value
    envelope = fb.Envelope(number=observed.envelope, received_ns=observed.received_ns, event=event)
    before = {cid: rig.read_stored(cid) for cid in rig.records()}
    rig.host.window.accept(envelope)
    for _ in range(3): rig.round()
    assert [r.cid for r in rig.reports("frame")] == [frame.cid]
    assert len(rig.requests("belief_update")) == len(rig.facts(c.BELIEF_ADOPTED)) == 1
    # K27: the next read can already be waiting, without a second completed
    # acquisition. Synchronize at the source instead of racing that entry.
    assert rig.source.ready[1].wait(30), "production measurer did not start its next read"
    assert not rig.source.release[1].is_set()
    assert len(rig.calls) == len(rig.calls[0].port.evidence().sources) == 1
    assert len(rig.source.calls) == 2
    for stage in ORDER[1:]: rig.run_stage(stage)
    second, adopted = rig.adopt(2)
    assert_update(rig, second, adopted, SECOND, head.cid)
    for stage in ORDER[1:]: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.SELECTION)) == 3)
    assert [a.value["previous"] for a in rig.facts(c.BELIEF_ADOPTED)] == [None, head.cid]
    assert len(rig.calls) == len(rig.source.calls) == len(rig.requests("belief_update")) == 2
    assert all(rig.read_stored(cid) == saved for cid, saved in before.items())
    assert not any(p.kind == "conflict" for p in rig.host.window.status().pending)
    assert rig.host.halted is None


class AdmissionPort(fb.FWorkContext):
    """A public-port forwarding adapter, with a test barrier AFTER admission."""
    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate

    def enter(self):
        entered = self.delegate.enter()
        self.rig.admission_hook(self.work, self.delegate, entered)
        return entered

    def read(self, point): return self.delegate.read(point)
    def monitored(self, interval): return self.delegate.monitored(interval)
    def evidence(self): return self.delegate.evidence()
    def reader(self): return self.delegate.reader()
    def prepared(self): return self.delegate.prepared()
    def now(self): return self.delegate.now()
    def post(self, event, issued=None):
        result = self.delegate.post(event, issued=issued)
        hook = getattr(self.rig, "update_post_hook", None)
        if hook is not None: hook(self.work, event)
        return result


class ProductionUpdaterProbe:
    def __init__(self, rig):
        self.rig = rig
        self.production = fb.FiniteUpdater(registry=rig.registry)

    def run(self, work, ctx):
        return self.production.run(work, AdmissionPort(self.rig, work, ctx))


class AcquisitionLoopRig(BeliefRig):
    def __init__(self, *, symbols=(T, E), continuation=False, **kwargs):
        super().__init__(symbols=symbols, matrices=MATRICES, targets=("x0", "x1"),
                         continuation=continuation, **kwargs)
        self.admission_hook = lambda work, ctx, entered: None
        self.cleanup_releases = []
        self.updater = ProductionUpdaterProbe(self)

    def start(self):
        self.begin()
        for stage in ORDER:
            self.run_stage(stage)
        self.until(lambda: len(self.facts(c.SELECTION)) == 1)

    def publish_frame(self, index, *, last=False):
        _raw, (_observation, frame) = self.publish(index, last=last)
        return frame

    def adopt(self, number):
        self.publish_frame(number - 1, last=number == len(self.source.symbols))
        return self.update()

    def start_update_thread(self):
        request, body = self.callback("belief_update")
        work_id = request.value["desc"]["work_id"]
        assert work_id not in self.executed
        self.executed.add(work_id)
        def invoke():
            try:
                body()
            except BaseException as error:
                self.body_errors.append(error)
        thread = Thread(target=invoke, daemon=True)
        self.threads.append(thread)
        thread.start()
        return request, thread

    def close(self):
        for release in self.cleanup_releases:
            release.set()
        super().close()


@pytest.fixture
def make_acquisition_probe():
    rigs = []
    def make(**kwargs):
        rig = AcquisitionLoopRig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def finish_update(rig, previous, expected):
    before = len(rig.facts(c.BELIEF_ADOPTED))
    work = rig.run_stage("belief_update")
    rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == before + 1)
    adopted = rig.facts(c.BELIEF_ADOPTED)[-1]
    assert_update(rig, work, adopted, expected, previous)
    return work, adopted


def test_update_not_started_retries_once_and_continues_ce1(make_acquisition_probe):
    """K28: retry not_started; no retry, double admission or counting fails.

    T then E give FIRST then SECOND. Production admission rejects another enter.
    """
    rig = make_acquisition_probe(continuation=True)
    rig.start()
    attempts = cut_first_update_launch(rig, "not_started")
    extra = []
    rig.admission_hook = lambda work, ctx, entered: extra.append(ctx.enter()) if entered else None
    first, a1 = rig.adopt(1)
    assert_update(rig, first, a1, FIRST)
    assert [(wid, result) for wid, _body, result in attempts] == [
        (first.desc.work_id, "not_started"), (first.desc.work_id, "launched")]
    for stage in ORDER[1:]: rig.run_stage(stage)
    second, a2 = rig.adopt(2)
    assert_update(rig, second, a2, SECOND, a1.cid)
    for stage in ORDER[1:]: rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.SELECTION)) == 3)
    assert extra == [False, False]
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    for work, launches in ((first, ("not_started", "launched")), (second, ("launched",))):
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == launches and observed.entered == 1 and observed.stopped
        # The hook deliberately probes enter() again. Only the first succeeds;
        # executions.entered above is the independent body-admission count.
        assert [ok for wid, ok in rig.workers.entry_attempts if wid == work.desc.work_id] == [True, False]


@pytest.mark.parametrize("outcome", ("unknown", "raises"))
def test_update_unknown_launch_does_not_retry_and_measurement_keeps_reporting(make_acquisition_probe, outcome):
    """Unknown is never retried; a later production acquisition and Post still save.

    Retrying unknown or blocking the independent measuring worker fails witnesses.
    K28: the second update waits, rather than skipping the unknown operation.
    """
    rig = make_acquisition_probe()
    rig.start()
    attempts = cut_first_update_launch(rig, outcome)
    first = rig.publish_frame(0)
    rig.until(lambda: bool(attempts))
    request, = rig.requests("belief_update")
    work_id = request.value["desc"]["work_id"]
    later = rig.publish_frame(1, last=True)
    event = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"independent reception", claims={})
    rig.host.post(event)
    rig.until(lambda: any(raw.value == wire(event) for raw in rig.facts(c.RECEIVED)))
    for _ in range(3): rig.round()
    assert first.cid != later.cid and later.value["item"]["value"]["sample_seq"] == 1
    assert [(wid, result) for wid, _body, result in attempts] == [(work_id, outcome)]
    observed = execution_for(rig.workers.contexts["measure_segment"], work_id)
    assert observed.launches == ("unknown",) and observed.entered == 0 and not observed.stopped
    assert observed.reports == ()
    assert len(rig.requests("belief_update")) == 1
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == request.cid]


@pytest.mark.parametrize("operation", ("read", "monitored"))
def test_unentered_update_port_cannot_record_evidence_but_entered_port_can(make_acquisition_probe, operation):
    """An unentered read/monitored raises and adds no evidence; entered control adds one.

    Reusing a canceled not_started callback must never record denied-port evidence.
    """
    rig = make_acquisition_probe()
    rig.start()
    attempts = cut_first_update_launch(rig, "not_started")
    seen = {}
    span = f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=2, closure="(start,end]")
    def observe(ctx):
        before = ctx.evidence()
        try:
            result = ctx.read(rig.model_point) if operation == "read" else ctx.monitored(span)
            rejected = False
        except RuntimeError:
            result, rejected = None, True
        return before, ctx.evidence(), rejected, result
    def admitted(work, ctx, entered):
        if not entered:
            seen["denied"] = observe(ctx)
            return
        seen["allowed"] = observe(ctx)
        attempts[0][1]()
    rig.admission_hook = admitted
    rig.publish_frame(0)
    work, _adopted = finish_update(rig, None, FIRST)
    before, after, rejected, result = seen["allowed"]
    assert not rejected
    if operation == "read":
        assert isinstance(result, bytes) and result
        added = tuple(x for x in after.uses if x not in before.uses)
        assert len(added) == 1 and len(after.uses) == len(before.uses) + 1
        assert (added[0].work_id, added[0].point) == (work.desc.work_id, rig.model_point)
        assert after.intervals == before.intervals
    else:
        added = tuple(x for x in after.intervals if x not in before.intervals)
        assert len(added) == 1 and len(after.intervals) == len(before.intervals) + 1
        assert (added[0].work_id, added[0].interval) == (work.desc.work_id, span)
        assert after.uses == before.uses
    before, after, rejected, _result = seen["denied"]
    assert rejected and after.uses == before.uses and after.intervals == before.intervals
    assert [ok for wid, ok in rig.workers.entry_attempts if wid == work.desc.work_id] == [True, False]


def test_running_update_keeps_receiving_and_resumes_with_waiting_ce1_report(make_acquisition_probe):
    """While admitted Wu waits, production measurement and independent reception save.

    Premature terminal/R*/A*, a lost waiting Frame, or duplicate first use fails.
    """
    rig = make_acquisition_probe()
    rig.start()
    held, release, receiving_done = Event(), Event(), Event()
    rig.cleanup_releases.append(release)
    def admitted(work, ctx, entered):
        if entered:
            held.set()
            assert release.wait(30), "held update was not released"
    rig.admission_hook = admitted
    first = rig.publish_frame(0)
    request, update_thread = rig.start_update_thread()
    assert held.wait(30), "Wu did not enter"
    seen, errors = {}, []
    def receive():
        try:
            seen["second"] = rig.publish_frame(1, last=True)
            event = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"while Wu waits", claims={})
            rig.host.post(event)
            rig.until(lambda: any(raw.value == wire(event) for raw in rig.facts(c.RECEIVED)))
        except BaseException as error:
            errors.append(error)
        finally:
            receiving_done.set()
    receiving_thread = Thread(target=receive, daemon=True)
    rig.threads.append(receiving_thread)
    receiving_thread.start()
    try:
        assert receiving_done.wait(30), "reception did not progress while Wu was held"
        assert not errors, errors
        assert update_thread.is_alive() and not release.is_set()
        assert first.value["segment"] == seen["second"].value["segment"]
        assert len(rig.requests("belief_update")) == 1
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
        assert not [x for x in rig.facts(c.WORK_TERMINAL) if x.value["request"] == request.cid]
        assert not [x for x in rig.facts(c.WORK_REPORT) if x.value["work"] == request.value["desc"]["work_id"]]
        observed = execution_for(rig.workers.contexts["measure_segment"], request.value["desc"]["work_id"])
        assert observed.entered == 1 and not observed.stopped and observed.launches == ("launched",)
    finally:
        release.set()
        for thread in (receiving_thread, update_thread):
            thread.join(30)
            assert not thread.is_alive()
    rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    first_work = rig.update_ports[request.cid].work
    a1 = rig.one(c.BELIEF_ADOPTED)
    assert_update(rig, first_work, a1, FIRST)
    second_work, _a2 = finish_update(rig, a1.cid, SECOND)
    assert row5_report_for_work(rig, second_work).cid == seen["second"].cid
    assert first_work.desc.work_id != second_work.desc.work_id
    for work in (first_work, second_work):
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped


def test_eight_updates_preserve_one_adoption_chain_and_ce1_conjunction(make_acquisition_probe):
    """Eight DISTINCT operations T,E,E,... each multiply the declared diagonal kernel.

    This replaces entailed interval predicates: unlike a repeated Claim, each new
    MID contributes. A wrong prior/fork/drop/recount fails all eight exact answers.
    """
    symbols = (T,) + (E,) * 7
    # Hand product: unnormalised weights are 1/1024 and 1/524288.
    assert sequence_answer(symbols) == {
        "joint": [[512, 513], [1, 513]], "evidence_mass": [513, 524288]}
    rig = make_acquisition_probe(symbols=symbols)
    rig.start()
    previous, reports, work_ids, adoptions = None, [], [], []
    for number in range(1, 9):
        report = rig.publish_frame(number - 1, last=number == 8)
        work, adopted = finish_update(rig, previous, sequence_answer(symbols[:number]))
        assert row5_report_for_work(rig, work).cid == report.cid
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.launches == ("launched",) and observed.entered == 1 and observed.stopped
        assert [ok for wid, ok in rig.workers.entry_attempts if wid == work.desc.work_id] == [True]
        reports.append(report.cid); work_ids.append(work.desc.work_id); adoptions.append(adopted)
        previous = adopted.cid
    assert len(set(reports)) == len(set(work_ids)) == len(rig.requests("belief_update")) == 8
    assert len(rig.facts(c.UPDATE_RESULT)) == len(rig.facts(c.BELIEF_ADOPTED)) == 8
    assert [a.value["previous"] for a in adoptions] == [None] + [a.cid for a in adoptions[:-1]]
    assert not rig.facts(c.STALE)


def test_row5_two_waiting_reports_are_each_used_once_in_one_adoption_chain(make_acquisition_probe):
    """Three production Frames save before Wu runs; sample order is now mandatory.

    Dropping/recounting a Frame or issuing same-prior requests fails exact coverage.
    K28: T,E,T multiply in order, not the old entailed-interval arithmetic.
    """
    symbols = (T, E, T)
    # Hand product: weights 1/64 and 1/2048, not CE1's entailed SECOND.
    assert sequence_answer(symbols) == {
        "joint": [[32, 33], [1, 33]], "evidence_mass": [33, 2048]}
    rig = make_acquisition_probe(symbols=symbols)
    rig.start()
    reports = [rig.publish_frame(i, last=i == 2) for i in range(3)]
    event = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"behind three frames", claims={})
    rig.host.post(event)
    rig.until(lambda: any(x.value == wire(event) for x in rig.facts(c.RECEIVED)))
    assert len(rig.requests("belief_update")) == 1 and not rig.facts(c.BELIEF_ADOPTED)
    previous, adoptions = None, []
    for index, report in enumerate(reports):
        work, adopted = finish_update(rig, previous, sequence_answer(symbols[:index + 1]))
        assert row5_report_for_work(rig, work).cid == report.cid
        assert work.desc.args.prior == previous
        adoptions.append(adopted); previous = adopted.cid
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 3
    assert [a.value["previous"] for a in adoptions] == [None] + [a.cid for a in adoptions[:-1]]
