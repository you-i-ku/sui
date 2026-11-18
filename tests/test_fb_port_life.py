"""K29, F-b v1.09; K29-a :3547, K29-b :3548, body :4376-4438.

Public contexts, workers, stores and sources only.

RuntimeError text is deliberately unspecified. No private host state, source
lock, stack inspection, or sleep-based race ordering is used. Each helper thread
is joined and every source/body/store gate is released during cleanup.

K29-a closes CG-K29-SOURCE-LOCK-WAIT without a new public synchronization point.
Acquire checks admission only at entry (K11); its sole stopped check is after
taking the source-read lock, immediately before before-M. A stopped call can
wait for that lock before rejection. No second stopped check/race is required.
Removing this sole boundary check is detected by these existing cases:
test_portlife1_stopped_test_measurement_port_rejects_without_effects[acquire-return]
test_portlife1_stopped_test_measurement_port_rejects_without_effects[acquire-exception]
test_portlife1_stopped_production_measurer_port_rejects_without_effects[acquire]
test_portlife1_unknown_launch_does_not_keep_a_returned_body_alive[acquire]
K29-b records the mutation results (9 red, 1 equivalent); these were not rerun
by this test author. The equivalent read-entry change leaves the decisive
post-ledger-read stopped check intact, so entry-time rejection is not required.

Implemented-copy result reported for impl29: 51 passed. Independently verified
in request 61: this work29 test with impl29/src, 51 passed (27.27s, -n 0).
Historical pre-K29 work29 result: 31 passed / 20 failed. See
k29_port_life_coverage.json for verification/provenance. Bodies/assertions unchanged.
"""

from dataclasses import replace
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c
from test_fb_measure import AcquireRig, acquire1_api, acquire1_started, acquire1_expected_frame
from test_fb_belief import BeliefWorkers, T
from test_fb_acquisition_loop import AcquisitionLoopRig
from test_fb_loop import execution_for, FIRST, assert_update, cut_first_update_launch
from test_fb_stage1 import wire
from test_fb_stage2 import Stage2Rig, ORDER


WATCHDOG = 30


class WorkerExit(Exception):
    pass


def join(thread):
    thread.join(WATCHDOG)
    assert not thread.is_alive(), "fixture thread did not finish"


def spawn(rig, action):
    result = SimpleNamespace(value=None, error=None, done=Event())
    def invoke():
        try:
            result.value = action()
        except BaseException as error:
            result.error = error
        finally:
            result.done.set()
    result.thread = Thread(target=invoke, daemon=True)
    rig.life_threads.append(result.thread)
    result.thread.start()
    return result


def span(rig):
    return f.MeasurementInterval(clock=rig.clock.run, start_ns=0, end_ns=1, closure="(start,end]")


def evidence_rows(ctx):
    e = ctx.evidence()
    return e.uses, e.intervals, e.sources


def publication(rig, ctx):
    e = ctx.evidence()
    return (tuple(rig.receipts().items()), tuple(
        (w.work_id, w.reports) for w in e.executions))


def signature(rig, ctx):
    return evidence_rows(ctx), publication(rig, ctx), tuple(rig.source.calls)


def operate(rig, ctx, operation):
    if operation == "read": return ctx.read(rig.model_point)
    if operation == "monitored": return ctx.monitored(span(rig))
    return ctx.acquire()


def positive(rig, ctx, work_id, operation):
    """The caller is still admitted, with the same purpose as the tested port."""
    assert execution_for(ctx, work_id).entered == 1
    assert not execution_for(ctx, work_id).stopped
    before = ctx.evidence()
    result = operate(rig, ctx, operation)
    after = ctx.evidence()
    if operation == "read":
        assert result == rig.read_stored(rig.model_point)[2].body.content.data
        assert after.uses[:-1] == before.uses and len(after.uses) == len(before.uses) + 1
        assert (after.uses[-1].work_id, after.uses[-1].point) == (work_id, rig.model_point)
        assert after.intervals == before.intervals and after.sources == before.sources
    elif operation == "monitored":
        assert result is None
        assert after.intervals[:-1] == before.intervals and len(after.intervals) == len(before.intervals) + 1
        assert (after.intervals[-1].work_id, after.intervals[-1].interval) == (work_id, span(rig))
        assert after.uses == before.uses and after.sources == before.sources
    else:
        assert result.outcome == "taken"
        assert len(after.sources) == len(before.sources) + 1
        assert after.sources[-1].work_id == work_id
        assert after.uses == before.uses and after.intervals == before.intervals
    return result


def marker(rig, ctx, label):
    """Next real Post witnesses the envelope counter, including pending reports."""
    numbers = [r.envelope for w in ctx.evidence().executions for r in w.reports]
    numbers += list(rig.receipts())
    last = max(numbers, default=0)
    before = set(numbers)
    event = fb.Received(route_epoch="route-A", media_type="text/plain", data=label.encode(), claims={})
    ctx.post(event)
    after = set(rig.receipts()) | {r.envelope for w in ctx.evidence().executions for r in w.reports}
    # An unentered Post is retained as raw input, not attributed to that work's
    # EH. ReceiptStatus still exposes its envelope number (K11/B6).
    assert after - before == {last + 1}
    rig.until(lambda: any(r.value == wire(event) for r in rig.facts(c.RECEIVED)))


def init_life(rig):
    rig.life_threads, rig.life_releases = [], []
    return rig


@pytest.fixture
def life():
    rigs = []
    def register(rig):
        rigs.append(init_life(rig))
        return rig
    yield register
    for rig in reversed(rigs):
        for measurer in getattr(rig, "measurers", {}).values(): measurer.stop()
        for release in rig.life_releases: release.set()
        if hasattr(rig, "release"): rig.release.set()
        if hasattr(rig, "return_release"): rig.return_release.set()
        for release in getattr(rig, "production_returns", {}).values(): release.set()
        for thread in rig.life_threads: join(thread)
        rig.close()


def make_measure(life, *, production=False, failure=False, enter=True, take=True):
    def script(rig, work, port):
        ctx = port.delegate
        admitted = port.enter() if enter else False
        rig.life_ports.append((work, ctx, admitted))
        if not admitted:
            rig.life_ready.set()
            if enter: return  # A duplicate/cancelled wrapper has no body to run.
        else:
            reading = ctx.now()
            ctx.post(fb.SegmentReport(segment=work.request, item_slot="started",
                item=fb.SegmentBoundary(kind="started", work=work.desc.work_id,
                    reading=reading, reason="entered", evidence=())))
            if take: port.acquire()
            rig.life_ready.set()
        assert rig.release.wait(WATCHDOG), "test body not released"
        if failure: raise WorkerExit("test body exits without a terminal")

    api = acquire1_api()
    items = tuple(api.SourceItem(media_type="text/plain", data=b"port-life:" + str(i).encode(), claims={})
        for i in range(4))
    rig = life(AcquireRig(api, items=items, script=None if production else script,
        tick=0, advance=10, segments=2))
    rig.life_ready, rig.life_ports = Event(), []
    rig.expected_errors = (WorkerExit,) if failure else ()
    return rig


def start_measure(rig):
    key = rig.launch("measure_segment", "sensing")
    if rig.script is None:
        rig.wait_returns(1)
        ctx = rig.ports[key].delegate
        work = rig.work_by_id[key]
    else:
        assert rig.life_ready.wait(WATCHDOG), "test body did not reach its gate"
        work, ctx, _entered = rig.life_ports[0]
    return work, ctx


def stop_measure(rig, work, ctx):
    if rig.script is None:
        rig.measurers[work.desc.work_id].stop()
        rig.production_returns[work.desc.work_id].set()
    else: rig.release.set()
    for thread in rig.threads: join(thread)
    observed = execution_for(ctx, work.desc.work_id)
    assert observed.stopped
    return observed


def counter_probe(rig, expected_cursor, expected_seq):
    """A different live measuring work observes both counters of the same route."""
    before = len(rig.calls)
    key = rig.launch("measure_segment", "sensing-2")
    rig.wait_returns(before + 1)
    call = rig.calls[-1]
    assert call.work.desc.work_id == key
    assert call.acquired.cursor == expected_cursor
    observed = rig.source_for(call)
    assert observed.cursor == expected_cursor and observed.sample_seq == expected_seq
    raw, (_seen, frame) = rig.saved_pair(call)
    assert frame.value == wire(fb.SegmentReport(segment=call.work.request,
        item_slot=f"frame:{expected_seq}", item=acquire1_expected_frame(rig, call, raw[1])))
    if rig.script is None:
        rig.measurers[key].stop(); rig.production_returns[key].set()


@pytest.mark.parametrize("production", [False, True], ids=["test-worker", "SourceMeasurer"])
@pytest.mark.parametrize("operation", ["read", "monitored", "acquire"])
def test_portlife1_live_measurement_operations_keep_their_purpose_correct_effects(life, production, operation):
    """K29(3): before return, all three operations work on a measuring port."""
    rig = make_measure(life, production=production, take=False)
    work, ctx = start_measure(rig)
    if operation == "acquire" and production:
        assert rig.calls[0].acquired.outcome == "taken" and len(ctx.evidence().sources) == 1
        assert not execution_for(ctx, work.desc.work_id).stopped
    else: positive(rig, ctx, work.desc.work_id, operation)


@pytest.mark.parametrize("failure", [False, True], ids=["return", "exception"])
@pytest.mark.parametrize("operation", ["read", "monitored", "acquire"])
def test_portlife1_stopped_test_measurement_port_rejects_without_effects(life, failure, operation):
    """K29: return/exception revokes evidence-writing operations, not late Post.

    Missing stopped checks fail RuntimeError; partial revocation fails unchanged
    EH/EW uses/intervals/sources, next envelope, or next real cursor/sample_seq.
    """
    rig = make_measure(life, failure=failure)
    work, ctx = start_measure(rig)
    assert stop_measure(rig, work, ctx).entered == 1
    before = signature(rig, ctx)
    with pytest.raises(RuntimeError): operate(rig, ctx, operation)
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-stopped-denial")
    counter_probe(rig, 1, 1)


@pytest.mark.parametrize("operation", ["read", "monitored", "acquire"])
def test_portlife1_stopped_production_measurer_port_rejects_without_effects(life, operation):
    """A real SourceMeasurer has returned, not merely posted Ended or stop()."""
    rig = make_measure(life, production=True)
    work, ctx = start_measure(rig)
    assert stop_measure(rig, work, ctx).entered == 1
    before = signature(rig, ctx)
    with pytest.raises(RuntimeError): operate(rig, ctx, operation)
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-production-stop")
    counter_probe(rig, 1, 1)


@pytest.mark.parametrize("operation", ["read", "monitored", "acquire"])
def test_portlife1_unentered_measurement_port_still_rejects_without_effects(life, operation):
    """K11 remains: no start ticket is not evidence of use or an acquisition."""
    rig = make_measure(life, enter=False, take=False)
    work, ctx = start_measure(rig)
    assert execution_for(ctx, work.desc.work_id).entered == 0
    before = signature(rig, ctx)
    with pytest.raises(RuntimeError): operate(rig, ctx, operation)
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-unentered-denial")
    # This mouth still owns an unused start ticket; claim it now to observe
    # counters through a genuinely admitted acquisition, without inventing EW
    # stopped for a body that had never entered.
    assert ctx.enter()
    acquired = ctx.acquire()
    observed = ctx.evidence().sources[-1]
    assert acquired.cursor == observed.cursor == observed.sample_seq == 0
    assert rig.source.calls == [0]


@pytest.mark.parametrize("failure", [False, True], ids=["return", "exception"])
def test_portlife1_read_rechecks_after_public_ledger_read_and_does_not_return_body(life, failure):
    """K29 read boundary: admitted at entry, stopped before recording the use.

    A ledger.read barrier is outside the host's lock. Checking only entry,
    recording a use after return, or returning bytes fails the separate checks.
    """
    rig = make_measure(life, failure=failure)
    work, ctx = start_measure(rig)
    in_read, release = Event(), Event()
    rig.life_releases.append(release)
    record = rig.ledger.record
    owner = []
    def held_record(point):
        value = record(point)
        if owner and get_ident() == owner[0] and point == rig.model_point:
            in_read.set()
            assert release.wait(WATCHDOG), "ledger read not released"
        return value
    rig.ledger.record = held_record
    before = signature(rig, ctx)
    def read():
        owner.append(get_ident())
        return ctx.read(rig.model_point)
    result = spawn(rig, read)
    assert in_read.wait(WATCHDOG), "public ledger barrier not reached"
    stop_measure(rig, work, ctx)
    release.set(); join(result.thread)
    assert isinstance(result.error, RuntimeError) and result.value is None
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-mid-read-stop")


def make_update(life, operation=None, *, delayed=False, failure=False):
    class Workers(BeliefWorkers):
        def run(self, work, ctx):
            result = super().run(work, ctx)
            if failure and work.desc.purpose == "belief_update": raise WorkerExit("after native updater return")
            return result
    rig = life(AcquisitionLoopRig(symbols=(T,), worker_type=Workers,
        update_modes={0: "stopped"} if delayed else {}))
    rig.expected_errors = (WorkerExit,) if failure else ()
    captured = {}
    def admitted(work, port, entered):
        if entered:
            ctx = port.delegate  # The test's BeliefPort forwards the real public context.
            captured.update(work=work, ctx=ctx)
            if operation: captured["positive"] = positive(rig, ctx, work.desc.work_id, operation)
    rig.admission_hook = admitted
    rig.start(); rig.publish_frame(0, last=True)
    if delayed:
        q, body = rig.callback("belief_update")
        if failure:
            with pytest.raises(WorkerExit): body()
        else: body()
        work = captured["work"]
    else:
        work, adopted = rig.update()
        assert_update(rig, work, adopted, FIRST)
    assert execution_for(captured["ctx"], work.desc.work_id).stopped
    return rig, work, captured["ctx"]


@pytest.mark.parametrize("operation", ["read", "monitored"])
def test_portlife1_live_production_updater_can_record_evidence(life, operation):
    """Read/monitored before real FiniteUpdater computation remain legal."""
    make_update(life, operation)


@pytest.mark.parametrize("operation", ["read", "monitored"])
def test_portlife1_stopped_production_updater_cannot_record_more_evidence(life, operation):
    """A genuine native update/adoption does not keep the old mouth active."""
    rig, work, ctx = make_update(life, operation)
    before = signature(rig, ctx)
    with pytest.raises(RuntimeError): operate(rig, ctx, operation)
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-updater-stop")


@pytest.mark.parametrize("failure", [False, True], ids=["return", "exception"])
def test_portlife1_late_native_update_terminal_post_still_adopts_once(life, failure):
    """K15(4)/K29: late Post is allowed even when no terminal preceded return."""
    rig, work, ctx = make_update(life, delayed=True, failure=failure)
    port, event, issued = rig.returned[work.request]
    assert not [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    before = evidence_rows(ctx)
    ctx.post(event, issued=issued)
    rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
    assert_update(rig, work, rig.facts(c.BELIEF_ADOPTED)[0], FIRST)
    ctx.post(event, issued=issued)
    for _ in range(3): rig.round()
    assert len(rig.facts(c.BELIEF_ADOPTED)) == len(rig.facts(c.UPDATE_RESULT)) == 1
    assert evidence_rows(ctx) == before


@pytest.mark.parametrize("production", [False, True], ids=["test-worker", "SourceMeasurer"])
def test_portlife1_now_reader_prepared_evidence_and_post_survive_measurement_return(life, production):
    """The old port is not wholly invalid: these five accessors retain meaning."""
    rig = make_measure(life, production=production)
    work, ctx = start_measure(rig)
    reader = ctx.reader()
    assert ctx.prepared() is None
    visible = next(iter(work.desc.input_points), None)
    if visible is not None:
        assert reader is not None
        expected_record = reader.record(visible)
    stop_measure(rig, work, ctx)
    before = evidence_rows(ctx)
    rig.clock.set(rig.clock.peek() + 123)
    reading = ctx.now()
    assert reading.reading.run == rig.clock.run and reading.reading.time_ns == rig.clock.peek()
    if reader is None: assert ctx.reader() is None
    elif visible is not None: assert ctx.reader().record(visible) == expected_record
    assert ctx.prepared() is None
    assert evidence_rows(ctx) == before == evidence_rows(ctx)
    marker(rig, ctx, "late-measuring-post")
    counter_probe(rig, 1, 1)


@pytest.mark.parametrize("stage", ["candidate_generation", "evaluation_prepare", "evaluation"])
def test_portlife1_frozen_reader_and_prepared_remain_usable_after_compute_return(life, stage):
    """H5/K29: reading via an old frozen reader is still possible and unrecorded."""
    rig = life(Stage2Rig())
    seen = {}
    def action(work, ctx):
        seen.update(work=work, ctx=ctx, reader=ctx.reader(), prepared=ctx.prepared())
        event, issued = rig.workers.normal(work, ctx)
        rig.workers.post(ctx, event, issued)
    rig.workers.overrides[stage] = action
    rig.through(stage)
    work, ctx = seen["work"], seen["ctx"]
    assert execution_for(ctx, work.desc.work_id).stopped
    before = evidence_rows(ctx)
    assert seen["reader"] is not None and ctx.reader() is not None
    expected = rig.read_stored(rig.model_point)[2]
    assert ctx.reader().record(rig.model_point) == seen["reader"].record(rig.model_point) == expected
    if stage == "evaluation":
        assert isinstance(ctx.prepared().value, f.FProblem)
        assert ctx.prepared().canonical_bytes == seen["prepared"].canonical_bytes
    else: assert seen["prepared"] is None and ctx.prepared() is None
    rig.clock.set(rig.clock.mono_ns() + 123)
    assert ctx.now().reading.time_ns == rig.clock.mono_ns()
    assert evidence_rows(ctx) == before


@pytest.mark.parametrize("production", [False, True], ids=["test-worker", "SourceMeasurer"])
@pytest.mark.parametrize("outcome", ["taken", "empty", "unavailable"])
def test_portlife1_acquire_past_before_publishes_once_even_after_body_returns(life, production, outcome):
    """K29/K25: a real source read proves the before boundary was passed.

    Rejecting at commit, discarding a result, double publication or assigning
    the take to another work fails ES, EH, raw/Frame and operation-number checks.
    A helper holds the same admitted capability while FWorkers.run returns.
    """
    rig = make_measure(life, production=production, take=False)
    work, ctx = start_measure(rig)
    initial = ctx.evidence().sources
    seq = cursor = int(production)  # SourceMeasurer already completed one taken.
    start = rig.clock.peek()
    in_source, release = Event(), Event()
    rig.life_releases.append(release)
    def read(number):
        rig.source.calls.append(number)
        assert number == cursor
        in_source.set()
        assert release.wait(WATCHDOG), "source result not released"
        rig.clock.set(start + 10)
        if outcome == "unavailable": raise OSError("test source unavailable")
        return rig.source.items[number] if outcome == "taken" else None
    rig.source.read = read
    result = spawn(rig, ctx.acquire)
    assert in_source.wait(WATCHDOG)
    assert not execution_for(ctx, work.desc.work_id).stopped
    stop_measure(rig, work, ctx)
    assert ctx.evidence().sources == initial and result.value is None
    numbers = list(rig.receipts()) + [r.envelope for w in ctx.evidence().executions for r in w.reports]
    last = max(numbers, default=0)
    release.set(); join(result.thread)
    assert result.error is None and result.value.outcome == outcome
    acquired = result.value
    assert acquired.cursor == cursor
    assert (acquired.before.reading.time_ns, acquired.after.reading.time_ns) == (start, start + 10)
    e = ctx.evidence()
    assert e.sources[:-1] == initial and len(e.sources) == len(initial) + 1
    source = e.sources[-1]
    assert (source.work_id, source.sample_seq, source.cursor, source.outcome) == (work.desc.work_id, seq, cursor, outcome)
    assert source.source_called
    expected_numbers = (last + 1, last + 2) if outcome == "taken" else (last + 1,)
    assert tuple(n for n in (source.envelope, source.frame_envelope) if n is not None) == expected_numbers
    call = SimpleNamespace(work=work, port=rig.ports[work.desc.work_id], acquired=acquired,
        sequence=seq, route_epoch="route-A", envelopes=expected_numbers)
    raw, (_observation, frame) = rig.saved_pair(call)
    assert (raw is not None) == (outcome == "taken")
    assert frame.value == wire(fb.SegmentReport(segment=work.request, item_slot=f"frame:{seq}",
        item=acquire1_expected_frame(rig, call, raw[1] if raw else None)))
    assert len(rig.reports("frame")) == seq + 1
    assert len(ctx.evidence().sources) == seq + 1


def start_unknown(rig):
    normal = rig.launcher.launch
    def launch(work_id, body):
        normal(work_id, body)
        target = any(q.value["desc"]["work_id"] == work_id and q.value["desc"]["process"]["slot"] == "sensing"
            for q in rig.requests("measure_segment"))
        if not target: return "launched"
        def invoke():
            try: body()
            except BaseException as error: rig.body_errors.append(error)
        thread = Thread(target=invoke, daemon=True)
        rig.threads.append(thread)
        thread.start()
        return "unknown"  # Do not wait for enter while launch is being called.
    rig.launcher.launch = launch
    assert rig.host.keep_running(lambda _s: rig.life_ready.is_set(), timeout=WATCHDOG)
    work, ctx, admitted = rig.life_ports[0]
    assert admitted
    observed = execution_for(ctx, work.desc.work_id)
    assert observed.launches == ("unknown",) and observed.entered == 1 and not observed.stopped
    return work, ctx


def test_portlife1_unknown_launch_with_an_entered_running_body_is_still_live(life):
    """Launch uncertainty is not the stopped observation; all three remain legal."""
    rig = make_measure(life)
    work, ctx = start_unknown(rig)
    for operation in ("read", "monitored", "acquire"):
        positive(rig, ctx, work.desc.work_id, operation)
    assert rig.host.halted is None and not rig.host.interruptions()


@pytest.mark.parametrize("operation", ["read", "monitored", "acquire"])
def test_portlife1_unknown_launch_does_not_keep_a_returned_body_alive(life, operation):
    """Once EW stopped is observed, unknown no longer excuses evidence writes."""
    rig = make_measure(life)
    work, ctx = start_unknown(rig)
    stop_measure(rig, work, ctx)
    before = signature(rig, ctx)
    with pytest.raises(RuntimeError): operate(rig, ctx, operation)
    assert signature(rig, ctx) == before
    marker(rig, ctx, "after-unknown-stop")


@pytest.mark.parametrize("cancelled", [False, True], ids=["same-wrapper-twice", "old-not-started-wrapper"])
def test_portlife1_denied_wrapper_cannot_reenter_or_revoke_the_live_owner(life, cancelled):
    """K29(6): stale/duplicate wrappers cannot release another context's claim."""
    rig = make_measure(life)
    if cancelled:
        normal = rig.launcher.launch
        rejected = []
        def launch(work_id, body):
            normal(work_id, body)
            target = any(q.value["desc"]["work_id"] == work_id and q.value["desc"]["process"]["slot"] == "sensing"
                for q in rig.requests("measure_segment"))
            if target and not rejected:
                rejected.append(body)
                return "not_started"
            return "launched"
        rig.launcher.launch = launch
        def ready():
            return any(q.value["desc"]["process"]["slot"] == "sensing" and
                sum(wid == q.value["desc"]["work_id"] for wid, _ in rig.launcher.attempts) == 2
                for q in rig.requests("measure_segment"))
        rig.until(ready)
        q, = (q for q in rig.requests("measure_segment") if q.value["desc"]["process"]["slot"] == "sensing")
        bodies = [body for wid, body in rig.launcher.attempts if wid == q.value["desc"]["work_id"]]
        running = spawn(rig, bodies[-1])
        rig.threads.append(running.thread)
        assert rig.life_ready.wait(WATCHDOG)
        work, ctx, _ = rig.life_ports[0]
        old = rejected[0]
    else:
        work, ctx = start_measure(rig)
        old, = (body for wid, body in rig.launcher.attempts if wid == work.desc.work_id)
    before = signature(rig, ctx)
    calls_before = len(rig.life_ports)
    old()
    ghost = None
    if len(rig.life_ports) != calls_before:
        ghost_work, ghost, entered = rig.life_ports[-1]
        assert len(rig.life_ports) == calls_before + 1
        assert ghost is not ctx and not entered
        assert ghost_work.desc.work_id == work.desc.work_id
    # A wrapper may reject before calling FWorkers.run at all; the contract
    # requires no second admission, not the creation of a fresh denied context.
    assert signature(rig, ctx) == before
    observed = execution_for(ctx, work.desc.work_id)
    assert observed.entered == 1 and not observed.stopped
    for operation in ("read", "monitored", "acquire"):
        before = signature(rig, ctx)
        if ghost is not None:
            with pytest.raises(RuntimeError): operate(rig, ghost, operation)
        assert signature(rig, ctx) == before
        positive(rig, ctx, work.desc.work_id, operation)
    assert execution_for(ctx, work.desc.work_id).entered == 1
    assert not execution_for(ctx, work.desc.work_id).stopped


@pytest.mark.parametrize("stage", ["candidate_generation", "evaluation"])
@pytest.mark.parametrize("operation", ["read", "monitored"])
@pytest.mark.parametrize("after_stop", [False, True], ids=["live-control", "stopped"])
def test_portlife1_compute_read_and_monitored_have_the_same_return_boundary(life, stage, operation, after_stop):
    """Purpose-specific compute controls: acquire is not a lifetime discriminator."""
    rig = life(Stage2Rig())
    captured = {}
    def action(work, ctx):
        captured.update(work=work, ctx=ctx)
        positive(rig, ctx, work.desc.work_id, operation)
        before = evidence_rows(ctx)
        with pytest.raises(RuntimeError): ctx.acquire()  # Wrong purpose even while live.
        assert evidence_rows(ctx) == before
        event, issued = rig.workers.normal(work, ctx)
        rig.workers.post(ctx, event, issued)
    rig.workers.overrides[stage] = action
    rig.through(stage)
    work, ctx = captured["work"], captured["ctx"]
    assert execution_for(ctx, work.desc.work_id).stopped
    if after_stop:
        before = evidence_rows(ctx)
        with pytest.raises(RuntimeError): operate(rig, ctx, operation)
        assert evidence_rows(ctx) == before

