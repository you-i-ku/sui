"""K27/K27-a, F-b v0.97 :3541-3542/:4125-4216. Public Boot, ports, sources and stores.

Production SourceMeasurer owns every acquire call. TEST sources hold their last
read; the driver only posts Boot, runs the host and sends stop. Event watchdogs
diagnose incomplete observations, never an environment latency requirement.
"""

from dataclasses import fields, replace
from fractions import Fraction as Q
from threading import Event, Thread
from time import monotonic_ns, process_time_ns
import json
import sys
import tracemalloc

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u
from test_fb_skeleton import contract, slot, source, require_boot_v3, repeat_method
from test_fb_stage1 import wire
from test_fb_measure import AcquireRig, AcquirePort, AcquireWorkers, acquire1_api, RAW, ROUTE
from test_fb_loop import execution_for
from test_fb_read import read1_static, T, E, U, M, SYMBOLS, MODEL, CONTROL


REPEAT = contract("sui.fb.acquisition_repeat_when_done")
CONTROL_ID = "sui.fb.acquisition_repeat_when_done/1"


class RepeatOverrun(BaseException):
    """Bound a broken test run; never let host convert fixture exhaustion to unavailable."""


def repeat1_api():
    require_boot_v3()
    assert c.ACQUISITION_REPEAT_WHEN_DONE == REPEAT
    return acquire1_api()


class RepeatSource:
    """Finite environment script. Its last read is released after stop or halt."""
    def __init__(self, rig, symbols):
        self.rig, self.symbols, self.calls = rig, tuple(symbols), []
        self.waiting, self.release = Event(), Event()
        self.release_read = self.release  # Shared rig teardown releases a blocked public source.
    def read(self, cursor):
        number = len(self.calls)
        self.calls.append(cursor)
        if number >= len(self.symbols):
            raise RepeatOverrun("new source read after the stop boundary")
        symbol = self.symbols[number]
        if number == len(self.symbols) - 1:
            self.waiting.set()
            assert self.release.wait(30), "test did not release the source"
        self.rig.clock.set(self.rig.clock.peek() + 10)
        self.rig.clock.phase = "commit"
        if symbol == U:
            raise OSError("repeat1 source unavailable")
        if symbol == "interrupt":
            raise KeyboardInterrupt("repeat1 source interrupted")
        if symbol == "exit":
            raise SystemExit("repeat1 source exited")
        if symbol == "deep":
            claims = {"leaf": "valid"}
            for _ in range(max(1200, sys.getrecursionlimit() + 100)):
                claims = {"nested": claims}
            return self.rig.api.SourceItem(media_type="text/plain", data=RAW, claims=claims)
        if symbol == T:
            return self.rig.api.SourceItem(media_type="text/plain", data=RAW, claims={})
        assert symbol == E
        return None


class RepeatPort(AcquirePort):
    def acquire(self):
        rig = self.rig
        index = len(rig.invocations)
        rig.invocations.append(self.work.desc.work_id)
        if index >= len(rig.repeat_symbols) and rig.host.halted is None:
            raise RepeatOverrun("new accepted call after the finite experiment's stop boundary")
        if index == rig.before_acquire:
            # A call made by the real measurer, after its start decision but
            # before the forwarding port calls the real host acquire().
            rig.accepted.set()
            assert rig.allow_acquire.wait(30), "test did not release the accepted operation"
        try:
            return super().acquire()
        except BaseException as error:
            rig.acquire_errors.append(error)
            raise


class RepeatWorkers(AcquireWorkers):
    def run(self, work, ctx):
        if work.desc.purpose != "measure_segment":
            return super().run(work, ctx)
        rig = self.rig
        port = RepeatPort(rig, work, ctx)
        rig.ports[work.desc.work_id], rig.work_by_id[work.desc.work_id] = port, work
        self.contexts["measure_segment"] = ctx
        measurer = rig.api.SourceMeasurer()
        rig.measurers[work.desc.work_id] = measurer
        if rig.stop_before_run or rig.closing:
            measurer.stop()
        rig.registered.setdefault(work.desc.work_id, Event()).set()
        try:
            measurer.run(work, port)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            self.stops.append(work.desc.work_id)
            with rig.changed:
                rig.changed.notify_all()


@pytest.fixture
def make_repeat1():
    rigs = []
    def make(symbols=(E, T), *, before_acquire=None, stop_before_run=False,
             unsupported=None, omit_repeat=False, zero=False, fail_commit=False):
        api = repeat1_api()
        symbols = tuple(symbols)
        assert M not in symbols or all(s == M for s in symbols)
        rig = AcquireRig(api, mode="missing" if M in symbols else "taken", tick=0, advance=0)
        rigs.append(rig)
        rig.invocations, rig.before_acquire = [], before_acquire
        rig.acquire_errors = []
        rig.repeat_symbols = symbols
        rig.accepted, rig.allow_acquire = Event(), Event()
        rig.stop_before_run, rig.unsupported, rig.stop_threads = stop_before_run, unsupported, []
        rig.gate_production_return = False
        rig.source = RepeatSource(rig, symbols)
        rig.workers = RepeatWorkers(rig)
        rig.expected_errors = (Exception,)
        weights = ({T: (0, 0), E: (1, 1), U: (0, 0), M: (0, 0)} if zero else None)
        model = read1_static(weights, controls=(CONTROL_ID,), schedule=(CONTROL_ID,))
        model.declaration = replace(model.declaration, control_rule=fb.MethodCall(contract=CONTROL,
            args={"first": [CONTROL_ID], "after": {s: [CONTROL_ID] for s in SYMBOLS}}))
        rig.model_declaration = model.declaration
        rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
            initial=None, observation_models=(slot("repeat-model", MODEL, model.declaration),)))
        if unsupported is not None:
            route, = rig.boot_input.declaration.routes
            rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
                routes=(replace(route, value=replace(route.value, repeat=unsupported)),)))
            if unsupported.contract != REPEAT:
                declared, = (d for d in rig.registry.declarations if d.ref == REPEAT)
                rig.registry = f.make_f_registry(
                    declarations=rig.registry.declarations + (replace(declared, ref=unsupported.contract),),
                    implementations=rig.registry.implementations)
        if omit_repeat:
            rig.registry = f.make_f_registry(
                declarations=tuple(d for d in rig.registry.declarations if d.ref != REPEAT),
                implementations=tuple(i for i in rig.registry.implementations if i.ref != REPEAT))
        rig.host = fb.FThreadHost(ledger=rig.ledger, clock=rig.clock, workers=rig.workers,
            registry=rig.registry, launcher=rig.launcher,
            sources=None if M in symbols else {ROUTE: rig.source})
        if fail_commit:
            read_m = rig.clock.mono_ns
            def commit_failure():
                if rig.clock.phase == "commit":
                    raise MemoryError("repeat1 commit assembly failure")
                return read_m()
            rig.clock.mono_ns = commit_failure
        rig.host.post(fb.ClockDeclared(declaration=replace(source(), run=rig.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        rig.host.post(rig.boot_input)
        rig.until(lambda: bool(rig.facts(MODEL)))
        return rig
    yield make
    for rig in reversed(rigs):
        rig.source.release.set()
        rig.allow_acquire.set()
        rig.close()
        for thread in rig.stop_threads:
            thread.join(30)
            assert not thread.is_alive(), "stop callback did not return"


def repeat1_stop(rig, key):
    done = Event()
    def send():
        try:
            rig.measurers[key].stop()
        finally:
            done.set()
    thread = Thread(target=send, daemon=True)
    rig.stop_threads.append(thread)
    started = monotonic_ns()
    thread.start()
    returned = done.wait(5)
    if not returned:
        rig.source.release.set()
        rig.allow_acquire.set()
    assert returned, "stop held the source/acquire lock instead of setting the signal"
    return monotonic_ns() - started


def repeat1_finish(rig, key):
    assert (rig.accepted if rig.before_acquire is not None else rig.source.waiting).wait(10)
    started = monotonic_ns()
    repeat1_stop(rig, key)
    rig.source.release.set()
    rig.allow_acquire.set()
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    return monotonic_ns() - started


def repeat1_terminal(rig, key):
    """Terminal derives only from the public work port ES, never max(saved Frame)."""
    observations = tuple(s for s in rig.ports[key].evidence().sources if s.route_epoch == ROUTE)
    assert tuple(s.sample_seq for s in observations) == tuple(range(len(observations)))
    return observations, observations[-1].sample_seq if observations else None


def repeat1_read(rig, key, *, records=None):
    observations, through = repeat1_terminal(rig, key)
    if through is None:
        return None  # K27 explicitly does not call K26 for zero published acquisitions.
    model, = rig.facts(MODEL)
    return fb.read_acquisition_sequence(rig.records() if records is None else records,
        model=model.cid, run=rig.clock.run, route_epoch=ROUTE, through_seq=through)


def repeat1_saved(rig, key):
    """K27-a(a): full tail literals, including zero-publication/unsupported runs."""
    rig.until(lambda: all(s.frame is not None and (s.outcome != "taken" or s.received is not None)
        for s in repeat1_terminal(rig, key)[0]))
    rig.until(lambda: len(rig.reports("ended")) == len(rig.reports("coverage_unproved")) == 1)
    observations, _ = repeat1_terminal(rig, key)
    started, = rig.reports("started")
    ended, = rig.reports("ended")
    tail, = rig.reports("coverage_unproved")
    endpoint = ended.value["item"]["value"]["reading"]["value"]["reading"]["time_ns"]
    started_reading = started.value["item"]["value"]["reading"]["value"]["reading"]
    beginning = observations[-1].after_ns if observations else started_reading["time_ns"]
    assert beginning <= endpoint
    assert tail.value["item"]["value"]["interval"]["start_ns"] == beginning
    assert tail.value["item"]["value"]["interval"]["end_ns"] == endpoint
    assert tail.value["item"]["value"]["interval"]["clock"] == started_reading["run"] == str(rig.clock.run)
    assert tail.value["item"]["value"]["interval"]["closure"] == "(start,end]"
    assert tail.value["item"]["value"]["missing_contracts"] == wire((c.NO_ARRIVAL,))
    assert tail.value["item"]["value"]["evidence"] == []
    assert tail.value["item"]["value"]["route_epoch"] == ROUTE
    assert ended.value["item"]["value"]["reason"] == (
        "unsupported_repeat" if rig.unsupported is not None else "stopped")
    if not observations:
        route = rig.work_by_id[key].desc.args.route
        assert any(use.work_id == key and use.point == route for use in rig.ports[key].evidence().uses)
    rig.no_belief_update()
    return observations


def test_repeat1_public_versions_fields_registry_and_route_copy(make_repeat1):
    """K27(2): no implicit repeat default; request copies the declared MethodCall."""
    repeat1_api()
    declarations = u.fb_registry_v1().declarations
    assert [(d.ref, d.kind) for d in declarations if d.ref == REPEAT] == [(REPEAT, "measurement")]
    segment_refs = [ref for d in declarations for ref in (d.input_contract, d.output_contract)
                    if ref.name == "sui.fb.segment_requested"]
    assert segment_refs and all(ref.version == "2" for ref in segment_refs)
    rig = make_repeat1(stop_before_run=True)
    key = rig.launch("measure_segment")
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    work = rig.work_by_id[key]
    assert work.desc.args.repeat == rig.boot_input.declaration.routes[0].value.repeat == repeat_method()
    request, = rig.requests("measure_segment")
    assert request.value["desc"]["args"]["repeat"] == wire(repeat_method())


@pytest.mark.parametrize("symbols", [(E, E, T), (T, E), (E, T), (U, T), (M, M)],
    ids=["empty-empty-taken", "after-taken", "after-empty", "after-source-error", "after-source-missing"])
def test_repeat1_production_repeats_every_normal_outcome_and_reads_the_same_sequence(make_repeat1, symbols):
    """K27(a)(c): production makes every call; dropping E/U or taking once fails length/L.

    Independent static model: H=(T,E,U,M)=(1/2,1/4,1/8,1/8),
    L=(1/4,1/4,1/8,3/8); expected L is their product, never normalized.
    """
    rig = make_repeat1(symbols, before_acquire=1 if M in symbols else None)
    key = rig.launch("measure_segment")
    repeat1_finish(rig, key)
    observations = repeat1_saved(rig, key)
    assert len(observations) == len(symbols) == len(rig.invocations)
    assert tuple(s.outcome for s in observations) == tuple("unavailable" if s in (U, M) else s for s in symbols)
    assert tuple(s.source_called for s in observations) == tuple(s != M for s in symbols)
    assert tuple(s.cursor for s in observations) == tuple(sum(x == T for x in symbols[:i]) for i in range(len(symbols)))
    assert rig.source.calls == ([] if M in symbols else [s.cursor for s in observations])
    assert not any(isinstance(event, fb.SegmentReport) and isinstance(event.item, f.MeasurementFrame)
        for _, event in rig.worker_posts)
    declaration = rig.model_declaration
    assert declaration.controls[0].id == CONTROL_ID == f"{REPEAT.name}/{REPEAT.version}"
    assert declaration.control_rule.args == {"first": [CONTROL_ID], "after": {s: [CONTROL_ID] for s in SYMBOLS}}
    assert declaration.independence.args == {"weights_by_initial_state": [[[1, 1]], [[1, 1]]]}
    weights = {T: (Q(1, 2), Q(1, 4)), E: (Q(1, 4), Q(1, 4)), U: (Q(1, 8), Q(1, 8)), M: (Q(1, 8), Q(3, 8))}
    expected = [Q(1), Q(1)]
    for symbol in symbols:
        for state in range(2): expected[state] *= weights[symbol][state]
    result = repeat1_read(rig, key)
    assert result.kind == "read" and result.reason is None and result.likelihood == tuple(expected)
    assert result.controls == (CONTROL_ID,) * len(symbols)


@pytest.mark.parametrize("boundary", ["accepted-before-host-acquire", "inside-source-read"])
def test_repeat1_stop_keeps_the_accepted_last_result_and_precedes_ended(make_repeat1, boundary):
    """K27(b): stop cannot wait on read; an accepted operation still publishes exactly once."""
    rig = make_repeat1((T,), before_acquire=0 if boundary.startswith("accepted") else None)
    key = rig.launch("measure_segment")
    gate = rig.accepted if rig.before_acquire is not None else rig.source.waiting
    assert gate.wait(10)
    assert rig.source.calls == ([] if rig.before_acquire is not None else [0])
    assert repeat1_terminal(rig, key) == ((), None)
    repeat1_stop(rig, key)
    assert not rig.reports("ended") and not execution_for(rig.ports[key], key).stopped
    assert not any(isinstance(event, fb.SegmentReport) and isinstance(event.item, fb.SegmentBoundary)
                   and event.item.kind == "ended" for _, event in rig.worker_posts)
    rig.allow_acquire.set(); rig.source.release.set()
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    observations = repeat1_saved(rig, key)
    assert len(observations) == len(rig.invocations) == len(rig.source.calls) == 1
    assert observations[0].outcome == T


def test_repeat1_stop_before_first_operation_is_zero_publications_not_empty(make_repeat1):
    """K27(c): a pre-existing stop signal is a normal zero-publication branch, not model_zero."""
    rig = make_repeat1(stop_before_run=True)
    key = rig.launch("measure_segment")
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    assert repeat1_saved(rig, key) == ()
    assert repeat1_read(rig, key) is None
    assert not rig.calls and not rig.invocations and not rig.source.calls and not rig.reports("frame")
    assert rig.errors() == ()


def test_repeat1_already_entered_port_does_not_start_another_measurer_body(make_repeat1):
    """K27 decision 4: a false enter must produce no Started, read or acquisition."""
    rig = make_repeat1((T,))
    key = rig.launch("measure_segment")
    assert rig.source.waiting.wait(10)
    before = tuple(rig.worker_posts), tuple(rig.source.calls), tuple(rig.ports[key].evidence().sources)
    rig.api.SourceMeasurer().run(rig.work_by_id[key], rig.ports[key])
    assert (tuple(rig.worker_posts), tuple(rig.source.calls), tuple(rig.ports[key].evidence().sources)) == before
    assert rig.workers.entry_attempts[-1] == (key, False)
    repeat1_finish(rig, key)
    assert len(repeat1_saved(rig, key)) == 1


@pytest.mark.parametrize("previous,kind", [((), "deep"), ((E,), "deep"), ((), "commit")])
def test_repeat1_host_side_failure_stops_without_publishing_a_false_result(make_repeat1, previous, kind):
    """K27(d): host copy/assembly failure is not source unavailable; earlier ES facts survive."""
    symbols = previous + (("deep",) if kind == "deep" else (T,))
    rig = make_repeat1(symbols, fail_commit=kind == "commit")
    key = rig.launch("measure_segment")
    assert rig.source.waiting.wait(10)
    rig.source.release.set()
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    observations, through = repeat1_terminal(rig, key)
    assert len(rig.source.calls) == len(previous) + 1  # Zero publications does not mean untried.
    assert len(observations) == len(rig.calls) == len(previous)
    assert len(rig.failed_calls) == 1 and rig.errors() and rig.host.halted is None
    assert not any(isinstance(event, fb.SegmentReport) and isinstance(event.item, fb.SegmentBoundary)
                   and event.item.kind == "ended" for _, event in rig.worker_posts)
    assert not rig.facts(c.WORK_TERMINAL) and not rig.reports("measurement_unavailable")
    if previous:
        rig.saved_pair(rig.calls[0])
        assert through == 0 and repeat1_read(rig, key).likelihood == (Q(1, 4), Q(1, 4))
    else:
        assert through is None and repeat1_read(rig, key) is None
        assert not rig.reports("frame") and not rig.facts(c.RECEIVED)


@pytest.mark.parametrize("symbol,error_type", [("interrupt", KeyboardInterrupt), ("exit", SystemExit)])
def test_repeat1_process_signals_are_not_normal_unavailable_results(make_repeat1, symbol, error_type):
    """K27 decision 7: broad BaseException-to-unavailable conversion invents a normal result."""
    rig = make_repeat1((symbol,))
    rig.expected_errors = (error_type,)
    key = rig.launch("measure_segment")
    assert rig.source.waiting.wait(10)
    rig.source.release.set()
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    assert rig.errors() and all(isinstance(error, error_type) for error in rig.errors())
    assert rig.source.calls == [0] and repeat1_terminal(rig, key) == ((), None)
    assert not rig.calls and not rig.reports("frame") and rig.host.halted is None


@pytest.mark.parametrize("call", [fb.MethodCall(contract=contract("test.other-repeat"), args={}),
                                fb.MethodCall(contract=REPEAT, args={"unexpected": True})],
                         ids=["contract", "args"])
def test_repeat1_unsupported_work_repeat_enters_and_ends_without_acquiring(make_repeat1, call):
    """K27-a(b): Boot admits a registered measurement repeat; the real saved request is unsupported.

    Rejecting nonempty args at Boot prevents this route; ignoring repeat or
    refusing entry gives wrong I/O or a relaunch instead of one stopped worker.
    """
    rig = make_repeat1(unsupported=call)
    key = rig.launch("measure_segment")
    request, = rig.requests("measure_segment")
    assert rig.boot_input.declaration.routes[0].value.repeat == call
    assert request.value["desc"]["args"]["repeat"] == wire(call)
    assert rig.work_by_id[key].desc.args.repeat == call
    rig.until(lambda: execution_for(rig.ports[key], key).stopped)
    assert repeat1_saved(rig, key) == ()
    assert not rig.source.calls and not rig.invocations
    ended, = rig.reports("ended")
    assert ended.value["item"]["value"]["reason"] == "unsupported_repeat"
    before = tuple(rig.launcher.attempts)
    for _ in range(3): rig.round()
    assert tuple(rig.launcher.attempts) == before
    assert execution_for(rig.ports[key], key).entered == 1


def test_repeat1_undeclared_repeat_blocks_route_application(make_repeat1):
    """K27(2)(a): no declaration is route:<slot>:missing_contract, not an implicit default."""
    rig = make_repeat1(omit_repeat=True)
    rig.round()
    assert not rig.requests("measure_segment") and not rig.workers.entries
    assert not rig.facts(contract("sui.f.route_config"))
    pending = rig.host.window.status().pending
    assert any(p.kind == "route:route:missing_contract" or p.reason == "route:route:missing_contract"
               for p in pending)


@pytest.mark.parametrize("boundary", ["before-acquire", "during-read"])
def test_repeat1_halted_host_does_not_invent_saved_acquisitions(make_repeat1, boundary):
    """K27(b)(d): check halt on entry only; an in-flight publication has ES ownership, no saved Point."""
    rig = make_repeat1((T,), before_acquire=0 if boundary == "before-acquire" else None)
    key = rig.launch("measure_segment")
    assert (rig.accepted if rig.before_acquire is not None else rig.source.waiting).wait(10)
    write = rig.ledger.write
    def halt_store(_prepared): raise RuntimeError("repeat1 host store protocol fault")
    rig.ledger.write = halt_store
    rig.host.post(fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"halt-trigger", claims={}))
    with pytest.raises(fb.FHalted): rig.host.keep_running(lambda _status: False, timeout=1)
    rig.ledger.write = write
    before = rig.storage_snapshot()
    rig.allow_acquire.set(); rig.source.release.set()
    for thread in rig.threads:
        thread.join(30)
        assert not thread.is_alive()
    assert execution_for(rig.ports[key], key).stopped and rig.host.halted is not None
    assert len(rig.acquire_errors) == 1 and isinstance(rig.acquire_errors[0], fb.FHalted)
    observations, through = repeat1_terminal(rig, key)
    assert rig.storage_snapshot() == before
    assert not rig.reports("frame") and not rig.facts(c.RECEIVED)
    assert len(observations) == (boundary == "during-read")
    assert rig.source.calls == ([0] if boundary == "during-read" else [])
    if observations:
        assert through == 0 and observations[0].frame is None and observations[0].received is None


@pytest.mark.parametrize("missing", ["frame", "raw"])
def test_repeat1_terminal_from_evidence_exposes_an_unsaved_tail(make_repeat1, missing):
    """K27(c): never shorten through_seq to max(saved Frame); recover same posts without retaking."""
    rig = make_repeat1((E, T))
    key = rig.launch("measure_segment")
    assert rig.source.waiting.wait(10)
    rig.saved_pair(rig.calls[0])
    write = rig.ledger.write
    fired = []
    def block(prepared):
        body = prepared.record.body
        tail = body.contract == c.RECEIVED if missing == "raw" else (
            body.contract == c.SEGMENT_REPORT and body.content.as_json()["item"]["kind"] == "frame"
            and body.content.as_json()["item"]["value"]["sample_seq"] == 1)
        if tail:
            fired.append(prepared.cid)
            raise OSError("repeat1 tail temporarily unsaved")
        return write(prepared)
    rig.ledger.write = block
    repeat1_finish(rig, key)
    rig.round()
    assert fired and repeat1_terminal(rig, key)[1] == 1
    result = repeat1_read(rig, key)
    assert result.kind == "unreadable" and result.reason == "missing_record" and result.likelihood is None
    rig.ledger.write = write
    repeat1_saved(rig, key)
    assert repeat1_read(rig, key).likelihood == (Q(1, 8), Q(1, 16))
    assert len(rig.calls) == len(rig.invocations) == 2


def test_repeat1_a_valid_zero_likelihood_sequence_is_model_zero(make_repeat1):
    """K27 decision 9: completed true taken may be model_zero, not insufficient or an enforced positive L."""
    rig = make_repeat1((T,), zero=True)
    key = rig.launch("measure_segment")
    repeat1_finish(rig, key); repeat1_saved(rig, key)
    result = repeat1_read(rig, key)
    assert result.kind == "model_zero" and result.reason is None and result.likelihood == (Q(0), Q(0))


def test_repeat1_short_run_records_amount_and_cost_without_performance_threshold(make_repeat1, record_property):
    """K27 decision 10: record resource numbers; only identity, ownership and stop correctness are pass criteria."""
    own_trace = not tracemalloc.is_tracing()
    if own_trace: tracemalloc.start()
    try:
        rig = make_repeat1((E, E, E, T))
        before_bytes = sum(len(rig.contents.get(seal)[1].data) for seal in rig.contents.seals()) + sum(
            len(header) for _, header in rig.entry_store.load())
        cpu = process_time_ns()
        key = rig.launch("measure_segment")
        stop_ns = repeat1_finish(rig, key)
        observations = repeat1_saved(rig, key)
        memory, peak = tracemalloc.get_traced_memory()
        ownership = [{"sample_seq": s.sample_seq, "frame": s.frame,
                      "received": s.received, "frame_envelope": s.frame_envelope} for s in observations]
        at_return = [{"work_id": call.work.desc.work_id,
                      "published": [{"sample_seq": s.sample_seq, "frame": s.frame, "received": s.received}
                                    for s in call.sources_at_return]} for call in rig.calls]
        amount = sum(len(rig.contents.get(seal)[1].data) for seal in rig.contents.seals()) + sum(
            len(header) for _, header in rig.entry_store.load())
        record_property("k27_short_run", json.dumps({"published": len(observations), "ownership": ownership,
            "ownership_at_return": at_return, "total_stored_bytes": amount, "stored_bytes_delta": amount-before_bytes,
            "process_cpu_ns": process_time_ns()-cpu, "python_traced_bytes": memory,
            "python_traced_peak_bytes": peak, "stop_to_worker_stopped_ns": stop_ns}, ensure_ascii=False))
        assert len(observations) == 4 and all(s.frame is not None for s in observations)
        assert len(rig.invocations) == 4
    finally:
        if own_trace: tracemalloc.stop()
