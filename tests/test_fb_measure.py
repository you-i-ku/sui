"""K25/K25-a, F-b v0.81 :3527-3528, public Boot/Post and real host/store boundaries.

No implementation body is read/patched. Resolve public names per test. K27:
single-acquisition K25 probes hold a public forwarding return until the TEST
sends stop(); one acquisition is no longer a production worker limit.
Deposition (A), reconstruction (B) and independent correspondence (C) are separate.

CG-K25-ES-NAMES and CG-K25-TAIL are closed by K25-a(a)/(d): directly
check all fourteen ES fields and the inherited K23(f) report literals.
CG-K25-HOST-RETURN: a forwarding mouth can hold the result before the worker
receives it; no public hook identifies commit -> return inside the host method.
CG-K25-ID-ORDER: no public ID allocator hook witnesses reserving the raw name
before source.read. Name stability/linkage and failure-before-read are tested.
K25-a(b)/(c) explicitly leave those last two internal checks to code review.
"""

from dataclasses import fields, replace
import inspect
from queue import Queue
from threading import Condition, Event, RLock, Thread, get_ident
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u
from sui.ids import Ref, RefKind
from sui.records import Payload, Prediction, Role
from gate_f_facts_cases import finite_world, plain
from test_fb_skeleton import boot, contract, source, require_boot_v5
from test_fb_stage1 import RealRig, wire
from test_fb_stage2 import PREPARE_BUDGET, EVALUATE_BUDGET, LaunchCut, Workers as Stage2Workers
from test_fb_loop import LoopRig, registry, delta_args, execution_for, CLOCK_SOURCE


ROUTE = "route-A"
RAW = b"\x00\xffraw\r\n\xe6\x89\x8b\xe7\xb4\x99"
CLAIMS = {"sender_time_ns": -900, "nested": {"text": "unclassified", "values": [1, None, True]}}


def acquire1_api():
    require_boot_v5()
    missing = [name for owner, names in (
        (fb, ("FSource", "SourceItem", "Acquisition", "SourceMeasurer")),
        (fb.FWorkContext, ("now", "acquire")), (u, ("SourceObservation",)),
        (c, ("ACQUISITION_RESULT_SAMPLING",))) for name in names if not hasattr(owner, name)]
    assert not missing, "K25 public API missing: " + ", ".join(missing)
    return SimpleNamespace(SourceItem=fb.SourceItem, Acquisition=fb.Acquisition, SourceMeasurer=fb.SourceMeasurer)


class AcquireClockFailure(RuntimeError):
    pass


class WorkerFell(RuntimeError):
    pass


class AcquireClock:
    """Public Clock adapter. tick=1 distinguishes rereading M for each envelope.

    Only acquire caller reads are traced/failed. No host-private field is used.
    tick=0 with a nonadvancing source makes two acquisitions share the same r.
    """
    def __init__(self, clock, tick=1):
        self.clock, self.tick = clock, tick
        self.owner, self.phase, self.armed = None, None, False
        self.trace, self.fired, self.lock = [], [], RLock()

    @property
    def run(self):
        return self.clock.run

    @property
    def run_index(self):
        return self.clock.run_index

    def now(self):
        return self.clock.now()

    def mono_ns(self):
        with self.lock:
            if get_ident() == self.owner and self.armed:
                self.armed = False
                self.fired.append(self.phase)
                raise AcquireClockFailure("acquire1 injected M read failure")
            self.clock.set(self.clock.mono_ns() + self.tick)
            ns = self.clock.mono_ns()
            if get_ident() == self.owner and self.phase is not None:
                self.trace.append((self.phase, ns))
            return ns

    def set(self, ns):
        self.clock.set(ns)

    def peek(self):
        return self.clock.mono_ns()


class AcquireSource:
    """The test's ordered nonconsuming source, injected through FSource.read."""
    def __init__(self, clock, items=(), *, mode="taken", advance=2, invalid=None):
        self.clock, self.items, self.mode = clock, tuple(items), mode
        self.advance, self.invalid, self.calls = advance, invalid, []
        self.block, self.reading, self.release_read = False, Event(), Event()
        self.fail_commit = False

    def read(self, cursor):
        self.calls.append(cursor)
        if self.block and len(self.calls) == 1:
            self.reading.set()
            assert self.release_read.wait(30), "source read was not released"
        self.clock.set(self.clock.peek() + self.advance)
        self.clock.phase = "commit"
        if self.fail_commit:
            self.fail_commit, self.clock.armed = False, True
        if self.mode == "raises":
            raise OSError("acquire1 external source failed")
        if self.mode == "invalid":
            return self.invalid
        return self.items[cursor] if cursor < len(self.items) else None


class AcquirePort(fb.FWorkContext):
    """Forward public operations and capture actual acquire/EH/ES boundaries.

    A held forwarding return is a worker-boundary scenario; the real host method
    has returned. No private instruction between its commit/return is claimed.
    """
    def __init__(self, rig, work, delegate):
        self.rig, self.work, self.delegate = rig, work, delegate

    def enter(self):
        entered = self.delegate.enter()
        self.rig.workers.entry_attempts.append((self.work.desc.work_id, entered))
        if entered:
            self.rig.workers.entries.append(self.work)
        return entered

    def now(self):
        reading = self.delegate.now()
        self.rig.now_reads.setdefault(self.work.desc.work_id, []).append(reading)
        return reading

    def evidence(self):
        return self.delegate.evidence()

    def read(self, point):
        return self.delegate.read(point)

    def monitored(self, interval):
        return self.delegate.monitored(interval)

    def reader(self):
        return self.delegate.reader()

    def prepared(self):
        return self.delegate.prepared()
    def perform(self, execution): return self.delegate.perform(execution)

    def post(self, event, issued=None):
        self.rig.worker_posts.append((self.work.desc.work_id, event))
        self.delegate.post(event, issued=issued)
        if isinstance(event, fb.SegmentReport) and isinstance(event.item, fb.SegmentBoundary):
            if event.item.kind == "started":
                self.rig.started.setdefault(self.work.desc.work_id, Event()).set()
            elif event.item.kind == "ended":
                self.rig.ended_posted.set()
                if self.rig.hold_ended:
                    assert self.rig.end_return_release.wait(30), "test did not release Ended Post return"

    def acquire(self):
        rig = self.rig
        before = execution_for(self.delegate, self.work.desc.work_id).reports
        epoch = rig.secondary_epoch if self.work.desc.process.slot == "sensing-2" else ROUTE
        call = SimpleNamespace(sequence=sum(a.route_epoch == epoch for a in rig.attempts), route_epoch=epoch,
            work=self.work, port=self,
            envelopes_before=tuple(r.envelope for r in before), receipts_before=rig.receipts(),
            sources_before=self.evidence().sources, trace_start=len(rig.clock.trace))
        rig.attempts.append(call)
        rig.attempted.set()
        rig.clock.owner, rig.clock.phase = get_ident(), "prepare"
        if rig.fail_prepare:
            rig.fail_prepare, rig.clock.armed = False, True
        try:
            acquired = self.delegate.acquire()
        except BaseException:
            rig.failed_calls.append(call)
            assert rig.attempts[-1] is call, "fixture does not combine concurrent acquire and failed M"
            rig.attempts.pop()
            raise
        finally:
            rig.clock.phase, rig.clock.owner = None, None
        after = execution_for(self.delegate, self.work.desc.work_id).reports
        call.acquired = acquired
        call.sources_at_return, call.receipts_at_return = self.evidence().sources, rig.receipts()
        source, = (s for s in call.sources_at_return if s.work_id == self.work.desc.work_id
                   and s.route_epoch == epoch and s.sample_seq == call.sequence)
        # Other legal Posts can occur while FSource.read is running. K25's
        # public ES identifies exactly this operation's raw/Frame envelopes;
        # a Started/Ended/Unproved Post is not an acquisition member.
        call.envelopes = tuple(n for n in (source.envelope, source.frame_envelope) if n is not None)
        assert set(call.envelopes) <= {r.envelope for r in after if r.envelope not in call.envelopes_before}
        call.trace = tuple(rig.clock.trace[call.trace_start:])
        with rig.changed:
            rig.calls.append(call)
            rig.changed.notify_all()
        if rig.hold_return:
            hold = getattr(rig, "hold_acquire_return", None)
            if hold is None:
                assert rig.return_release.wait(30), "test did not release the acquire return"
            else:
                hold(call)
        if rig.script is None and rig.gate_production_return:
            # K25 examines one operation. The test holds this forwarding return
            # until stop(), rather than relying on an obsolete one-shot worker.
            assert rig.production_returns.setdefault(self.work.desc.work_id, Event()).wait(30), "test did not stop the production probe"
        return acquired


class AcquireStopGate:
    """Test-owned stop forwarding; the actual SourceMeasurer still owns run()."""
    def __init__(self, delegate, release):
        self.delegate, self.release = delegate, release
    def run(self, work, ctx):
        return self.delegate.run(work, ctx)
    def stop(self):
        try:
            self.delegate.stop()
        finally:
            self.release.set()


class AcquireWorkers(Stage2Workers):
    def run(self, work, ctx):
        if work.desc.purpose != "measure_segment":
            return super().run(work, ctx)
        rig = self.rig
        port = rig.port_type(rig, work, ctx)
        rig.ports[work.desc.work_id], rig.work_by_id[work.desc.work_id] = port, work
        self.contexts["measure_segment"] = ctx
        rig.registered.setdefault(work.desc.work_id, Event()).set()
        try:
            if rig.script is None:
                measurer = rig.api.SourceMeasurer()
                if rig.gate_production_return:
                    measurer = AcquireStopGate(measurer,
                        rig.production_returns.setdefault(work.desc.work_id, Event()))
                rig.measurers[work.desc.work_id] = measurer
                if rig.closing:
                    measurer.stop()
                measurer.run(work, port)
            else:
                rig.script(rig, work, port)
        except BaseException as error:
            self.errors.append(error)
            raise
        finally:
            self.stops.append(work.desc.work_id)
            with rig.changed:
                rig.changed.notify_all()


class AcquireRig(LoopRig):
    """Literal CE1 Boot with deferred launch bodies and the acquisition capability.

    Two routes use the explicit bootstrap declarations below: different
    positions/processes share identical route-A config, with explicit capacity.
    """
    def __init__(self, api, *, items=(), mode="taken", script=None, compute=None,
                 tick=1, advance=2, invalid=None, segments=1, second_route_epoch=ROUTE):
        RealRig.__init__(self, connect=False)
        self.clock.set(0)
        self.clock = AcquireClock(self.clock, tick)
        self.api, self.script, self.expected_errors = api, script, ()
        self.port_type, self.gate_production_return = AcquirePort, True
        self.production_returns = {}
        self.registry, self.launcher = registry(), LaunchCut()
        self.workers = AcquireWorkers(self)
        self.ports, self.work_by_id, self.measurers, self.now_reads = {}, {}, {}, {}
        self.registered, self.started, self.executed = {}, {}, set()
        self.threads, self.body_errors, self.worker_posts = [], [], []
        self.calls, self.attempts, self.failed_calls = [], [], []
        self.changed, self.release, self.action_done = Condition(), Event(), Event()
        self.return_release, self.attempted, self.acquire_release = Event(), Event(), Event()
        self.ended_posted, self.end_return_release, self.hold_ended = Event(), Event(), False
        self.other_ready, self.other_events = Event(), Queue()
        self.hold_return, self.fail_prepare, self.closing = False, False, False
        self.source = AcquireSource(self.clock, items, mode=mode, advance=advance, invalid=invalid)
        self.secondary_epoch = second_route_epoch
        self.other_source = AcquireSource(self.clock, items, mode=mode, advance=advance, invalid=invalid)
        if compute is not None:
            self.workers.overrides["candidate_generation"] = lambda work, ctx: compute(self, work, ctx)
        document, _ = finite_world("FA01")
        model = self.record(Prediction(target="acquire1.model", about=(), basis=(),
            content=Payload.json({"document": document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(model, ()).cid
        event = boot(True)
        event = replace(event, declaration=replace(event.declaration, perception=replace(
            event.declaration.perception, value=replace(event.declaration.perception.value,
                model=self.model_point, derivation=fb.SlottedMethod(slot='delta', method=fb.MethodCall(contract=c.SAVED_SEGMENT_UPDATE, args=delta_args()))))))
        initial = replace(event.declaration.initial.value, generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}), method=fb.MethodCall(contract=contract('sui.f.finite_evaluation'), args={}), draw=fb.MethodCall(contract=contract('stage2.scripted_draw'), args={}), prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET, continuation=None)
        first = event.declaration.routes[0]
        first = replace(first, value=replace(first.value, config=replace(first.value.config,
            sampling_contract=c.ACQUISITION_RESULT_SAMPLING, clock_contract=contract("sui.f.simulated_clock"))))
        routes = [first]
        if segments == 2:
            routes.append(replace(first, slot="route-2", value=replace(first.value, process_slot="sensing-2",
                config=replace(first.value.config, route_epoch=second_route_epoch),
                allocation=replace(first.value.allocation, slot="sensing-allocation-2"))))
        self.boot_input = replace(event, declaration=replace(event.declaration,
            capacity=fb.QuantityValue(contract=c.SEATS, value=segments + 1), routes=tuple(routes),
            initial=replace(event.declaration.initial, value=initial)))
        sources = {ROUTE: self.source}
        if segments == 2 and second_route_epoch != ROUTE:
            sources[second_route_epoch] = self.other_source
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
            registry=self.registry, launcher=self.launcher, sources=None if mode == "missing" else sources)
        self.host.post(fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        self.host.post(self.boot_input)

    def errors(self):
        return tuple({id(e): e for e in self.workers.errors + self.body_errors}.values())

    def round(self):
        self.host.keep_running(lambda _status: True, timeout=0)
        assert self.host.halted is None
        assert all(isinstance(e, self.expected_errors) for e in self.errors()), self.errors()

    def drive(self, predicate):
        self.until(predicate)

    def until(self, predicate):
        for _ in range(256):
            if predicate():
                return
            self.round()
            Event().wait(.001)  # Yield to workers; this is a watchdog, not an SLA.
        assert predicate(), "incomplete observation: required public successor did not appear"

    def launch(self, purpose, process=None):
        def ready():
            return any((process is None or q.value["desc"]["process"]["slot"] == process)
                and any(key == q.value["desc"]["work_id"] for key, _ in self.launcher.attempts)
                for q in self.requests(purpose))
        self.until(ready)
        request = next(q for q in self.requests(purpose)
                       if process is None or q.value["desc"]["process"]["slot"] == process)
        key = request.value["desc"]["work_id"]
        assert key not in self.executed
        body, = (body for wid, body in self.launcher.attempts if wid == key)
        self.executed.add(key)
        def invoke():
            try:
                body()
            except BaseException as error:
                self.body_errors.append(error)
            finally:
                with self.changed:
                    self.changed.notify_all()
        thread = Thread(target=invoke, daemon=True)
        self.threads.append(thread)
        thread.start()
        if purpose == "measure_segment":
            assert self.registered.setdefault(key, Event()).wait(30), "measurement callback did not start"
        return key

    def wait_returns(self, count=1):
        # Stop early only on an error raised while waiting; an earlier work's expected
        # error must not end the wait before this call is recorded.
        seen = len(self.errors())
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.calls) >= count or len(self.errors()) > seen, timeout=30)
        assert len(self.calls) >= count, self.errors()

    def receipts(self):
        return {r.envelope: r for r in self.host.window.status().receipts}

    def reports(self, kind):
        return [r for r in self.facts(c.SEGMENT_REPORT) if r.value["item"]["kind"] == kind]

    def records(self):
        return {cid: self.read_stored(cid)[2] for cid, _ in self.entry_store.load()}

    def source_for(self, call):
        a = call.acquired
        wanted = (call.work.desc.work_id, call.route_epoch, a.cursor, a.before.reading.time_ns, a.after.reading.time_ns, a.outcome)
        observed, = (s for s in call.port.evidence().sources if (
            s.work_id, s.route_epoch, s.cursor, s.before_ns, s.after_ns, s.outcome) == wanted)
        return observed

    def pair(self, call):
        execution = execution_for(call.port.delegate, call.work.desc.work_id)
        reports = [r for r in execution.reports if r.envelope in call.envelopes]
        if any(r.point is None for r in reports):
            return None
        raw, frames = [], []
        for r in reports:
            record = self.read_stored(r.point)[2]
            if record.body.contract == c.RECEIVED:
                raw.append((r, self.one(c.RECEIVED, cid=r.point)))
            elif record.body.contract == c.SEGMENT_REPORT:
                fact = self.one(c.SEGMENT_REPORT, cid=r.point)
                assert fact.value["item"]["kind"] == "frame"
                frames.append((r, fact))
        assert len(frames) == 1 and len(raw) == (call.acquired.outcome == "taken")
        return (raw[0] if raw else None), frames[0]

    def saved_pair(self, call):
        self.until(lambda: self.pair(call) is not None)
        return self.pair(call)

    def no_belief_update(self):
        assert not self.requests("belief_update")
        assert not self.facts(c.UPDATE_RESULT) and not self.facts(c.BELIEF_ADOPTED)
        assert not self.reports("claim") and not self.reports("measurement_unavailable")
        assert self.host.halted is None

    def close(self):
        self.closing = True
        self.source.release_read.set()
        self.other_source.release_read.set()
        self.acquire_release.set()
        self.return_release.set()
        self.end_return_release.set()
        self.release.set()
        self.other_events.put(None)
        for measurer in list(self.measurers.values()):
            measurer.stop()
        for thread in self.threads:
            thread.join(30)
            assert not thread.is_alive(), "test worker did not stop"
        assert all(isinstance(e, self.expected_errors) for e in self.errors()), self.errors()


@pytest.fixture
def make_acquire_rig():
    rigs = []
    def make(api, **kwargs):
        rig = AcquireRig(api, **kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def acquire1_started(rig, work, ctx):
    assert ctx.enter()
    reading = ctx.now()
    ctx.post(fb.SegmentReport(segment=work.request, item_slot="started", item=fb.SegmentBoundary(
        kind="started", work=work.desc.work_id, reading=reading, reason="entered", evidence=())))
    return reading


def acquire1_quiet(rig, work, ctx):
    acquire1_started(rig, work, ctx)
    assert rig.release.wait(30)


def acquire1_item(api):
    return api.SourceItem(media_type="application/x-acquire1", data=RAW, claims=CLAIMS)


def acquire1_receipt_signature(receipts):
    # StatusBasis can describe a newly read view; it is not part of H's
    # envelope/payload/ownership identity and need not retain the same view key.
    return {n: (r.received_ns, r.state, tuple((s.contract, s.state, s.target) for s in r.slots))
            for n, r in receipts.items()}


def acquire1_frame(seq, before, after, *, cursor, called, result, route_epoch=ROUTE):
    """Every field from K25(2)(c), never from a production Frame's output."""
    return f.MeasurementFrame(route_epoch=route_epoch, sample_seq=seq,
        measurement_id=f.MeasurementId(origin=before.reading.run, route_epoch=route_epoch,
                                       sample_seq=seq, component="source_acquisition"),
        measurement_interval=f.MeasurementInterval(clock=before.reading.run,
            start_ns=before.reading.time_ns, end_ns=after.reading.time_ns, closure="[start,end]"),
        actual_time=after.reading, value={"cursor": cursor, "source_called": called,
            "clock_source": before.source, "result": result},
        quality=f.ContractValue(contract=contract("sui.f.measured_quality"), value="measured"), gap=None,
        source_cursor=f.ContractValue(contract=contract("sui.f.sequence_cursor"), value=seq))


def acquire1_expected_frame(rig, call, raw):
    a = call.acquired
    result = {"kind": a.outcome}
    if a.outcome == "taken":
        result["received"] = str(raw.record_id)
    elif a.outcome == "unavailable":
        assert isinstance(a.reason, str) and a.reason
        result["reason"] = a.reason
    else:
        assert a.reason == ""
    return acquire1_frame(call.sequence, a.before, a.after, cursor=a.cursor,
                          called=rig.source.mode != "missing", result=result, route_epoch=call.route_epoch)


def test_acquire1_started_post_during_source_read_is_not_an_acquisition_member(make_acquire_rig):
    """Public ES, not a before/after report delta, identifies raw/Frame members.

    Counting a concurrently posted Started as this acquire's Frame fails pair()
    at its branch check. The production worker still acquires exactly once.
    """
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    read, extra = rig.source.read, []
    def source_read(cursor):
        port = next(iter(rig.ports.values()))
        original = next(event for _key, event in rig.worker_posts if isinstance(event, fb.SegmentReport)
            and isinstance(event.item, fb.SegmentBoundary) and event.item.kind == "started")
        event = replace(original, item_slot="started-during-read")
        before = {r.envelope for r in execution_for(port.delegate, port.work.desc.work_id).reports}
        port.post(event)
        observation, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports if r.envelope not in before)
        extra.append(observation.envelope)
        return read(cursor)
    rig.source.read = source_read
    rig.launch("measure_segment"); rig.wait_returns()
    call, = rig.calls
    raw, (_observed, frame) = rig.saved_pair(call)
    source = rig.source_for(call)
    assert call.envelopes == (source.envelope, source.frame_envelope)
    assert len(call.envelopes) == 2 and not set(extra) & set(call.envelopes)
    assert len(rig.calls) == len(rig.source.calls) == 1
    assert frame.value["item"]["kind"] == "frame" and raw is not None
    rig.until(lambda: any(r.value.get("item_slot") == "started-during-read" for r in rig.reports("started")))


def acquire1_assert_remaining_reports(rig, call):
    """K25-a(d) :3528: K23(f)'s literal values, with independently observed clock readings."""
    key = call.work.desc.work_id
    assert len(rig.now_reads[key]) >= 2
    started_reading, stopped_reading = rig.now_reads[key][0], rig.now_reads[key][-1]
    started, = (r for r in rig.reports("started") if r.value["segment"] == call.work.request)
    ended, = (r for r in rig.reports("ended") if r.value["segment"] == call.work.request)
    unproved, = (r for r in rig.reports("coverage_unproved") if r.value["segment"] == call.work.request)
    assert started.value["item"] == {"kind": "started", "value": {"work": key,
        "reading": wire(started_reading), "reason": "entered", "evidence": []}}
    assert ended.value["item"] == {"kind": "ended", "value": {"work": key,
        "reading": wire(stopped_reading), "reason": "stopped", "evidence": []}}
    assert stopped_reading.source == call.acquired.after.source
    assert unproved.value["item"] == {"kind": "coverage_unproved", "value": {"route_epoch": call.route_epoch,
        "interval": {"clock": str(rig.clock.run), "start_ns": call.acquired.after.reading.time_ns,
                     "end_ns": stopped_reading.reading.time_ns, "closure": "(start,end]"},
        "missing_contracts": [plain(c.NO_ARRIVAL)], "evidence": []}}


def acquire1_rebuild(records, frame_point):
    """(B): only saved Records, no rig/ES/EH/Acquisition. Missing never means empty.

    Resolve result.received as Record.id, not CID, r, bytes, digest or envelope.
    """
    record = records.get(frame_point)
    if record is None or record.body.contract != c.SEGMENT_REPORT:
        return None
    body = record.body.content.as_json()
    if body["item"]["kind"] != "frame":
        return None
    frame = body["item"]["value"]
    if frame["value"]["kind"] != "value":
        return None
    value = frame["value"]["value"]
    result = value["result"]
    if result["kind"] not in ("taken", "empty", "unavailable"):
        return None
    raw = None
    if result["kind"] == "taken":
        matches = [r for r in records.values() if str(r.id) == result["received"] and r.body.contract == c.RECEIVED]
        if len(matches) != 1:
            return None
        raw = matches[0]
    return {"kind": result["kind"], "interval": frame["measurement_interval"],
        "actual_time": frame["actual_time"], "clock_source": value["clock_source"],
        "cursor": value["cursor"], "source_called": value["source_called"],
        "received_id": str(raw.id) if raw is not None else None, "raw": raw}


def acquire1_corresponds(rig, report, call):
    """(C), K25-a(a): directly match ES operation/source/name/Frame to actual EH and saved Records.

    A wrong ES sequence, pinned clock, Frame envelope/Point or Ref fails even if
    the stored Frame is otherwise correct. Never manufacture ES from that Frame.
    """
    if call is None or call not in rig.calls:
        return False
    observed = rig.source_for(call)
    execution = execution_for(call.port.delegate, observed.work_id)
    actual = {r.envelope: r for r in execution.reports}
    frame_reports = [actual[n] for n in call.envelopes if actual[n].point == report.cid]
    if len(frame_reports) != 1 or report.value["segment"] != call.work.request:
        return False
    if execution.entered != 1 or observed.work_id != call.work.desc.work_id or observed.route_epoch != call.route_epoch:
        return False
    if type(observed.sample_seq) is not int or observed.sample_seq != call.sequence:
        return False
    if observed.source_called is not (rig.source.mode != "missing"):
        return False
    if observed.clock_source != call.acquired.before.source or observed.clock_source != call.acquired.after.source:
        return False
    if (type(observed.frame_envelope) is not int or observed.frame_envelope not in call.envelopes
            or observed.frame_envelope != frame_reports[0].envelope or observed.frame != report.cid
            or actual[observed.frame_envelope].point != observed.frame):
        return False
    frame = report.value["item"]["value"]
    value = frame["value"]
    if (value["kind"] != "value" or type(frame["sample_seq"]) is not int
            or type(frame["measurement_id"]["sample_seq"]) is not int
            or type(frame["source_cursor"]["value"]) is not int
            or type(value["value"]["cursor"]) is not int
            or type(value["value"]["source_called"]) is not bool):
        return False
    raw = None
    if observed.outcome == "taken":
        if observed.envelope not in call.envelopes or observed.received is None:
            return False
        if actual[observed.envelope].point != observed.received:
            return False
        raw = rig.one(c.RECEIVED, cid=observed.received)
        if not isinstance(observed.received_id, Ref) or observed.received_id != raw.record_id:
            return False
        if frame["value"]["value"]["result"].get("received") != str(observed.received_id):
            return False
        if raw.value != wire(fb.Received(route_epoch=call.route_epoch, media_type=call.acquired.item.media_type,
                                       data=call.acquired.item.data, claims=call.acquired.item.claims)):
            return False
    elif observed.envelope is not None or observed.received is not None or observed.received_id is not None:
        return False
    if observed.before_ns != call.acquired.before.reading.time_ns or observed.after_ns != call.acquired.after.reading.time_ns:
        return False
    expected = acquire1_expected_frame(rig, call, raw)
    return (report.value == wire(fb.SegmentReport(segment=call.work.request,
                item_slot=f"frame:{call.sequence}", item=expected))
        and frame_reports[0].received_ns == observed.after_ns == report.received_ns
        and (raw is None or actual[observed.envelope].received_ns == raw.received_ns == observed.after_ns))


class AcquireStoreCut:
    """Test-owned Ledger.write plus the real before/after commit boundaries."""
    def __init__(self, rig, target="both", boundary="before_body", *, block=False):
        self.rig, self.target, self.boundary, self.block = rig, target, boundary, block
        self.attempts, self.fired = [], []
        self.normal_write = rig.ledger.write
        def write(prepared):
            kind = self.kind(prepared)
            if kind is not None and (target == "both" or kind == target):
                self.attempts.append(prepared)
                if self.block:
                    self.fired.append((kind, prepared))
                    raise OSError("acquire1 temporarily blocked save")
                if not self.fired:
                    self.fired.append((kind, prepared))
                    rig.fail_next(boundary)
            return self.normal_write(prepared)
        rig.ledger.write = write

    @staticmethod
    def kind(prepared):
        body = prepared.record.body
        if body.contract == c.RECEIVED:
            return "raw"
        if body.contract == c.SEGMENT_REPORT and body.content.as_json()["item"]["kind"] == "frame":
            return "frame"
        return None


def test_acquire1_public_contract_and_unchanged_acquisition_shape():
    """K25(2)(a)(b)(5): replace the old capability; do not add Acquisition fields."""
    acquire1_api()
    assert c.ACQUISITION_RESULT_SAMPLING == contract("sui.fb.acquisition_result_sampling")
    assert not hasattr(c, "SOURCE_SAMPLING")
    declarations = u.fb_registry_v1().declarations
    assert [(d.ref, d.kind) for d in declarations if d.ref == c.ACQUISITION_RESULT_SAMPLING] == [
        (c.ACQUISITION_RESULT_SAMPLING, "measurement")]
    assert not any(d.ref == contract("sui.fb.source_sampling") for d in declarations)
    assert {field.name for field in fields(fb.Acquisition)} == {
        "route_epoch", "cursor", "before", "after", "outcome", "reason", "item"}
    assert not inspect.signature(fb.SourceMeasurer).parameters


@pytest.mark.parametrize("mode", ["taken", "empty", "missing", "raises"])
def test_acquire1_production_deposits_posts_before_return_without_worker_frame(make_acquire_rig, mode):
    """(A), :3901/:3929: already Post one/two envelopes before a runner round.

    Worker-owned-only values or a missing host Frame fails EH/receipt ownership.
    A production worker duplicating the Frame fails the independent worker-Post log.
    """
    api = acquire1_api()
    rig = make_acquire_rig(api, mode=mode, items=(acquire1_item(api),) if mode == "taken" else ())
    rig.hold_return = True
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    expected = 2 if mode == "taken" else 1
    assert len(call.envelopes) == len(set(call.envelopes)) == expected
    assert len(call.sources_at_return) == len(call.sources_before) + 1
    assert all(call.receipts_at_return[n].state == "received" for n in call.envelopes)
    assert all(r.point is None for r in execution_for(call.port.delegate, call.work.desc.work_id).reports
               if r.envelope in call.envelopes)
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame"), "pair must still be owned by H"
    assert not any(isinstance(e, fb.SegmentReport) and isinstance(e.item, f.MeasurementFrame)
                   for _, e in rig.worker_posts)
    assert call.acquired.outcome == {"taken": "taken", "empty": "empty"}.get(mode, "unavailable")
    assert rig.source.calls == ([] if mode == "missing" else [0])
    before_save = rig.source_for(call)
    assert type(before_save.sample_seq) is int and before_save.sample_seq == call.sequence
    assert before_save.source_called is (mode != "missing")
    assert before_save.clock_source == call.acquired.before.source == call.acquired.after.source
    assert type(before_save.frame_envelope) is int and before_save.frame_envelope in call.envelopes
    assert before_save.frame is None and before_save.received is None
    if mode == "taken":
        assert isinstance(before_save.received_id, Ref)
        assert before_save.envelope in call.envelopes and before_save.envelope != before_save.frame_envelope
    else:
        assert before_save.received_id is None and before_save.envelope is None
    rig.return_release.set()
    _, (frame_eh, frame) = rig.saved_pair(call)
    after_save = rig.source_for(call)
    assert after_save.frame_envelope == before_save.frame_envelope == frame_eh.envelope
    assert after_save.frame == frame.cid and after_save.received_id == before_save.received_id
    assert acquire1_corresponds(rig, frame, call)
    rig.measurers[call.work.desc.work_id].stop()
    rig.until(lambda: execution_for(call.port.delegate, call.work.desc.work_id).stopped and all(
        r.point is not None for r in execution_for(call.port.delegate, call.work.desc.work_id).reports))
    assert not any(isinstance(e, fb.SegmentReport) and isinstance(e.item, f.MeasurementFrame)
                   for _, e in rig.worker_posts)
    assert len(rig.reports("frame")) == 1
    rig.no_belief_update()


@pytest.mark.parametrize("mode", ["taken", "empty", "missing", "raises"])
def test_acquire1_saved_records_rebuild_result_without_live_control(make_acquire_rig, mode):
    """(B), :3902: saved content alone reconstructs; this does not certify the operation."""
    api = acquire1_api()
    item = acquire1_item(api)
    rig = make_acquire_rig(api, mode=mode, items=(item,) if mode == "taken" else ())
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    raw, (_, frame) = rig.saved_pair(call)
    rebuilt = acquire1_rebuild(rig.records(), frame.cid)
    assert rebuilt is not None
    assert rebuilt["kind"] == {"taken": "taken", "empty": "empty"}.get(mode, "unavailable")
    assert rebuilt["source_called"] is (mode != "missing") and rebuilt["cursor"] == 0
    assert rebuilt["clock_source"] == rig.one(CLOCK_SOURCE).cid
    assert rebuilt["interval"] == {"clock": str(rig.clock.run), "start_ns": call.acquired.before.reading.time_ns,
        "end_ns": call.acquired.after.reading.time_ns, "closure": "[start,end]"}
    assert rebuilt["actual_time"] == {"kind": "clock", "value": wire(call.acquired.after.reading)}
    if mode == "taken":
        assert rebuilt["received_id"] == str(raw[1].record_id)
        assert rebuilt["raw"].body.content.as_json() == wire(fb.Received(
            route_epoch=ROUTE, media_type=item.media_type, data=RAW, claims=CLAIMS))
    else:
        assert rebuilt["raw"] is None and rebuilt["received_id"] is None
    rig.no_belief_update()


@pytest.mark.parametrize("mode", ["taken", "empty", "missing", "raises"])
def test_acquire1_live_control_corresponds_to_host_frame_and_named_raw(make_acquire_rig, mode):
    """(C), :3903: independent real ES/EH and the actual call, never B or reconstruction alone."""
    api = acquire1_api()
    item = acquire1_item(api)
    rig = make_acquire_rig(api, mode=mode, items=(item,) if mode == "taken" else ())
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    _, (_, frame) = rig.saved_pair(call)
    assert acquire1_corresponds(rig, frame, call)
    assert not acquire1_corresponds(rig, frame, None), "a saved Frame must not manufacture ES"
    assert call.acquired.item == (item if mode == "taken" else None)
    assert rig.source_for(call).cursor == 0
    rig.no_belief_update()


def test_acquire1_production_binding_tail_and_actual_stop_keep_frame_unadopted(make_acquire_rig):
    """K25(f)/(3): B is not acquisition proof; Ended is not actual worker stop."""
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    key = rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    _, (_, frame) = rig.saved_pair(call)
    rig.until(lambda: any(b.value["report"] == frame.cid for b in rig.facts(c.SEGMENT_BINDING)))
    binding, = (b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == frame.cid)
    assert binding.value["segment"] == call.work.request and binding.value["route"] == call.work.desc.args.route
    assert binding.value["reading_contract"] == plain(c.FINITE_SEGMENT_PROJECTION)
    assert isinstance(call.work.desc.args.requested, fb.Ongoing)
    assert not execution_for(call.port.delegate, key).stopped
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")
    rig.measurers[key].stop()
    rig.until(lambda: bool(rig.reports("ended")) and bool(rig.reports("coverage_unproved"))
              and execution_for(call.port.delegate, key).stopped)
    acquire1_assert_remaining_reports(rig, call)
    assert rig.source.calls == [0] and len(rig.calls) == len(rig.reports("frame")) == 1
    for stage in ("candidate_generation", "evaluation_prepare", "selection_draw", "evaluation"):
        rig.run_stage(stage)
    rig.until(lambda: len(rig.facts(c.SELECTION)) == 1)
    rig.no_belief_update()


def test_acquire1_saved_ended_does_not_confirm_actual_worker_stop(make_acquire_rig):
    """Hold the production worker's Ended Post return: saved Ended is not actual EW stop."""
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    rig.hold_ended = True
    key = rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    rig.saved_pair(call)
    rig.measurers[key].stop()
    assert rig.ended_posted.wait(30)
    rig.until(lambda: len(rig.reports("ended")) == len(rig.reports("coverage_unproved")) == 1)
    acquire1_assert_remaining_reports(rig, call)
    assert not execution_for(call.port.delegate, key).stopped
    rig.end_return_release.set()
    rig.until(lambda: execution_for(call.port.delegate, key).stopped)
    assert rig.source.calls == [0] and len(rig.calls) == 1
    rig.no_belief_update()


@pytest.mark.parametrize("mode", ["taken", "empty"])
@pytest.mark.parametrize("ending", ["return", "raise"])
def test_acquire1_worker_stops_after_acquire_but_host_keeps_the_pair(make_acquire_rig, mode, ending):
    """No worker Frame, tail or Ended is needed to save the already-Posted result."""
    api = acquire1_api()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        if ending == "raise":
            raise WorkerFell("acquire returned; worker fell before another report")
    rig = make_acquire_rig(api, mode=mode, items=(acquire1_item(api),) if mode == "taken" else (), script=script)
    rig.expected_errors = (WorkerFell,)
    key = rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    rig.until(lambda: execution_for(call.port.delegate, key).stopped)
    _, (_, frame) = rig.saved_pair(call)
    assert acquire1_rebuild(rig.records(), frame.cid) is not None
    assert acquire1_corresponds(rig, frame, call)
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")
    assert not any(isinstance(e, fb.SegmentReport) and isinstance(e.item, f.MeasurementFrame)
                   for _, e in rig.worker_posts)
    assert bool(rig.errors()) == (ending == "raise")
    rig.no_belief_update()


def test_acquire1_same_bytes_same_receipt_time_keep_distinct_names_and_reject_swaps(make_acquire_rig):
    """K25(d): identical bytes/r do not identify an acquisition. Name swaps fail (C), not (B)."""
    api = acquire1_api()
    item = acquire1_item(api)
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        ctx.acquire()  # Test worker repetition, NOT production repetition.
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, items=(item, item), script=script, tick=0, advance=0)
    rig.launch("measure_segment")
    rig.wait_returns(2)
    first, second = sorted(rig.calls, key=lambda call: call.sequence)
    (eh1, raw1), (_, frame1) = rig.saved_pair(first)
    (eh2, raw2), (_, frame2) = rig.saved_pair(second)
    assert raw1.value == raw2.value and raw1.received_ns == raw2.received_ns == frame1.received_ns == frame2.received_ns
    assert raw1.record_id != raw2.record_id and raw1.cid != raw2.cid and eh1.envelope != eh2.envelope
    assert [call.acquired.cursor for call in (first, second)] == rig.source.calls == [0, 1]
    assert acquire1_corresponds(rig, frame1, first) and acquire1_corresponds(rig, frame2, second)
    assert not acquire1_corresponds(rig, frame1, second) and not acquire1_corresponds(rig, frame2, first)
    # In-memory semantic negative copies only; no saved record is overwritten.
    for frame, call, other in ((frame1, first, raw2), (frame2, second, raw1)):
        body = frame.value["item"]["value"]
        swapped_body = {**body, "value": {"kind": "value", "value": {**body["value"]["value"],
            "result": {"kind": "taken", "received": str(other.record_id)}}}}
        swapped = replace(frame, value={**frame.value, "item": {"kind": "frame", "value": swapped_body}})
        # Reconstruction can still resolve the other real raw Record. That
        # does not establish correspondence with this actual acquisition.
        records = rig.records()
        record = records[frame.cid]
        records[frame.cid] = replace(record, body=replace(record.body, content=Payload.json(swapped.value)))
        assert acquire1_rebuild(records, frame.cid)["received_id"] == str(other.record_id)
        assert not acquire1_corresponds(rig, swapped, call)
    rig.no_belief_update()


@pytest.mark.parametrize("saved_kind", ["raw", "frame"])
def test_acquire1_only_one_saved_member_is_not_a_reconstructible_pair(make_acquire_rig, saved_kind):
    """K25(d)/(d2): accept one actual envelope first; block only the missing member.

    K16 does not require preparing a successor after a failed save. Selective
    acceptance makes both partial states without that assumption. Reconstructing
    either incomplete pair as complete/empty fails; recovery must keep the saved
    record unchanged and must not acquire again.
    """
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    missing = {"raw": "frame", "frame": "raw"}[saved_kind]
    cut = AcquireStoreCut(rig, target=missing, block=True)
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    a, observed = call.acquired, rig.source_for(call)
    # Replay exactly the already-posted envelope, using public ES identifiers
    # and K25's literals; do not Post another event or infer an envelope order.
    events = {
        "raw": fb.Received(route_epoch=call.route_epoch, media_type=a.item.media_type,
                           data=a.item.data, claims=a.item.claims),
        "frame": fb.SegmentReport(segment=call.work.request, item_slot=f"frame:{call.sequence}",
            item=acquire1_frame(call.sequence, a.before, a.after, cursor=a.cursor, called=True,
                result={"kind": "taken", "received": str(observed.received_id)},
                route_epoch=call.route_epoch)),
    }
    numbers = {"raw": observed.envelope, "frame": observed.frame_envelope}
    envelopes = {kind: fb.Envelope(number=numbers[kind], event=event,
        received_ns=a.after.reading.time_ns) for kind, event in events.items()}
    rig.host.window.accept(envelopes[saved_kind])
    def saved_members():
        candidates = rig.facts(c.RECEIVED) if saved_kind == "raw" else rig.reports("frame")
        return [r for r in candidates if r.value == wire(events[saved_kind])]
    # settle only: keep_running would also accept the other queued envelope.
    for _ in range(256):
        if saved_members():
            break
        rig.host.window.settle()
    saved, = saved_members()
    assert not cut.fired
    before = rig.read_stored(saved.cid)
    rig.host.window.accept(envelopes[missing])
    rig.until(lambda: bool(cut.fired))
    blocked_kind, blocked = cut.fired[0]
    assert blocked_kind == missing
    frame_point = saved.cid if saved_kind == "frame" else blocked.cid
    records = rig.records()
    assert saved.cid in records and blocked.cid not in records
    assert acquire1_rebuild(records, frame_point) is None
    cut.block = False
    rig.saved_pair(call)
    assert rig.read_stored(saved.cid) == before
    assert acquire1_rebuild(rig.records(), frame_point) is not None
    assert rig.source.calls == [0] and len(rig.calls) == 1
    rig.no_belief_update()


@pytest.mark.parametrize("target", ["raw", "frame"])
@pytest.mark.parametrize("boundary", ["after_body_commit", "after_entry_commit"])
def test_acquire1_lost_save_reply_reuses_names_without_reacquiring(make_acquire_rig, target, boundary):
    """K25(d): no renamed record, extra operation or source-unavailable after lost acknowledgement."""
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    cut = AcquireStoreCut(rig, target, boundary)
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    rig.until(lambda: len(cut.fired) == 1)
    fixed = cut.fired[0][1]
    assert rig.fault_observations == [boundary], "specified commit boundary must actually fire"
    raw, (_, frame) = rig.saved_pair(call)
    assert cut.attempts and all(p == fixed for p in cut.attempts)
    assert len({p.cid for p in rig.ledger.preparations if cut.kind(p) == target}) == 1
    assert frame.value["item"]["value"]["value"]["value"]["result"] == {
        "kind": "taken", "received": str(raw[1].record_id)}
    assert rig.source.calls == [0] and len(rig.calls) == len(call.port.evidence().sources) == 1
    assert acquire1_corresponds(rig, frame, call)
    assert any(i.kind == "store" for i in rig.host.interruptions())
    rig.no_belief_update()


@pytest.mark.parametrize("mode", ["empty", "missing", "raises"])
def test_acquire1_repeated_empty_unavailable_advances_operation_not_source_cursor(make_acquire_rig, mode):
    """Operations 0,1,2 have distinct Frames/slots, while attempted source cursor stays 0."""
    api = acquire1_api()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        for _ in range(3):
            a = ctx.acquire()  # Test worker, not production repetition.
            assert a.cursor == 0 and a.item is None
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, mode=mode, script=script)
    rig.launch("measure_segment")
    rig.wait_returns(3)
    for seq, call in enumerate(sorted(rig.calls, key=lambda call: call.sequence)):
        _, (_, frame) = rig.saved_pair(call)
        body = frame.value["item"]["value"]
        assert body["sample_seq"] == seq and body["source_cursor"]["value"] == seq
        assert body["value"]["value"]["cursor"] == 0
        assert acquire1_corresponds(rig, frame, call)
    assert rig.source.calls == ([] if mode == "missing" else [0, 0, 0])
    assert not rig.facts(c.RECEIVED) and len({r.value["item_slot"] for r in rig.reports("frame")}) == 3
    assert not [p for p in rig.host.window.status().pending if p.kind == "conflict"]
    rig.no_belief_update()


def test_acquire1_mixed_results_separate_operation_number_from_source_cursor(make_acquire_rig):
    """Fourth operation: sample_seq=3 takes source cursor=1. Counting either as the other fails."""
    api = acquire1_api()
    item = acquire1_item(api)
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        for _ in range(3):
            ctx.acquire()  # taken 0, empty 1, empty 1
        rig.source.items = (item, item)  # New external item at cursor 1.
        ctx.acquire()
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, items=(item,), script=script)
    rig.launch("measure_segment")
    rig.wait_returns(4)
    calls = sorted(rig.calls, key=lambda call: call.sequence)
    assert [a.acquired.cursor for a in calls] == rig.source.calls == [0, 1, 1, 1]
    assert [a.acquired.outcome for a in calls] == ["taken", "empty", "empty", "taken"]
    for seq, call in enumerate(calls):
        _, (_, frame) = rig.saved_pair(call)
        assert frame.value["item"]["value"]["sample_seq"] == seq
        assert frame.value["item"]["value"]["source_cursor"]["value"] == seq
        assert acquire1_corresponds(rig, frame, call)
    rig.no_belief_update()


@pytest.mark.parametrize("fault", ["wrong-object", "lookalike", "media-type", "data", "claims"])
def test_acquire1_invalid_source_return_is_a_called_unavailable_frame(make_acquire_rig, fault):
    """K23-a(e) survives: malformed/foreign values are unavailable results, not raw records or empty."""
    api = acquire1_api()
    if fault == "wrong-object":
        value = "not a SourceItem"
    elif fault == "lookalike":
        value = SimpleNamespace(media_type="application/x-acquire1", data=RAW, claims=CLAIMS)
        assert not isinstance(value, api.SourceItem)
    else:
        value = api.SourceItem(media_type=7 if fault == "media-type" else "application/x-acquire1",
            data="not bytes" if fault == "data" else RAW, claims={1: "invalid key"} if fault == "claims" else CLAIMS)
    rig = make_acquire_rig(api, mode="invalid", invalid=value)
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    _, (_, frame) = rig.saved_pair(call)
    value = frame.value["item"]["value"]["value"]["value"]
    assert call.acquired.outcome == "unavailable" and call.acquired.cursor == 0 and call.acquired.item is None
    assert value["source_called"] is True and value["result"] == {"kind": "unavailable", "reason": call.acquired.reason}
    assert isinstance(call.acquired.reason, str) and call.acquired.reason
    assert not rig.facts(c.RECEIVED) and rig.source.calls == [0]
    assert acquire1_corresponds(rig, frame, call)
    rig.no_belief_update()


@pytest.mark.parametrize("worker", ["production", "port-script"])
def test_acquire1_mid_read_clock_conflict_keeps_pinned_source_and_taken_fact(make_acquire_rig, worker):
    """K25(3)/K23-a(f): save with the pinned clock Point; later use/tail may be blocked."""
    api = acquire1_api()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        assert rig.release.wait(30)
        with pytest.raises(RuntimeError):
            ctx.now()
        with pytest.raises(RuntimeError):
            ctx.acquire()
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script if worker == "port-script" else None)
    rig.expected_errors, rig.source.block = (RuntimeError,), True
    key = rig.launch("measure_segment")
    assert rig.source.reading.wait(30)
    original = rig.one(CLOCK_SOURCE).cid
    conflicting = replace(source(), run=rig.clock.run, measurement=contract("sui.f.simulated_clock"),
                          provider="acquire1-conflicting-clock")
    rig.host.post(fb.ClockDeclared(declaration=conflicting))
    rig.until(lambda: any(n.value == wire(conflicting) for n in rig.facts(c.CLOCK_NOTICE)))
    rig.source.release_read.set()
    rig.wait_returns()
    call, = rig.calls
    raw, (_, frame) = rig.saved_pair(call)
    assert raw is not None and call.acquired.before.source == call.acquired.after.source == original
    assert frame.value["item"]["value"]["value"]["value"]["clock_source"] == original
    assert acquire1_corresponds(rig, frame, call)
    for _ in range(16):
        rig.round()
    assert not [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == frame.cid]
    if worker == "production":
        rig.measurers[key].stop()
    rig.release.set()
    rig.until(lambda: execution_for(call.port.delegate, key).stopped)
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")
    assert rig.source.calls == [0] and len(rig.calls) == 1
    rig.no_belief_update()






@pytest.mark.parametrize("phase", ["prepare", "commit"])
def test_acquire1_host_exception_before_publication_changes_no_receipts_control_or_envelopes(make_acquire_rig, phase):
    """K25(d2)/Z49: unhandled injected M failure stops worker and publishes neither half.

    The lost take's result/time need not survive. Next actual Post observes the
    envelope number, without reading a private counter.
    """
    api = acquire1_api()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        pytest.fail("clock fault did not fire")
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script)
    # K25 fixes publication/stop effects, not preservation of the exception's
    # concrete class. clock.fired independently proves the requested fault.
    rig.expected_errors = (Exception,)
    rig.fail_prepare, rig.source.fail_commit = phase == "prepare", phase == "commit"
    key = rig.launch("measure_segment")
    thread, = rig.threads
    thread.join(30)
    assert not thread.is_alive() and rig.errors()
    failed, = rig.failed_calls
    assert rig.clock.fired == [phase] and rig.source.calls == ([] if phase == "prepare" else [0])
    assert not rig.calls and not rig.ports[key].evidence().sources
    assert tuple(r.envelope for r in execution_for(rig.ports[key].delegate, key).reports) == failed.envelopes_before
    assert acquire1_receipt_signature(rig.receipts()) == acquire1_receipt_signature(failed.receipts_before)
    assert not rig.reports("frame") and not rig.facts(c.RECEIVED)
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")
    assert execution_for(rig.ports[key].delegate, key).stopped
    marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"after-failed-acquire", claims={})
    prior = max(rig.receipts())
    rig.host.post(marker)
    assert max(rig.receipts()) == prior + 1
    rig.until(lambda: any(r.value == wire(marker) for r in rig.facts(c.RECEIVED)))
    assert not rig.reports("frame")
    # Also establish that the previously queued Started payload was preserved,
    # rather than only comparing envelope numbers/status projections.
    original, = (event for work_id, event in rig.worker_posts if work_id == key)
    original_report, = (r for r in execution_for(rig.ports[key].delegate, key).reports
                       if r.envelope in failed.envelopes_before)
    assert original_report.point is not None
    assert rig.one(c.SEGMENT_REPORT, cid=original_report.point).value == wire(original)


@pytest.mark.parametrize("phase", ["prepare", "commit"])
def test_acquire1_failed_attempt_preserves_operation_and_source_cursor(make_acquire_rig, phase):
    """Test worker catches the clock fault and probes while still entered; first success is operation/cursor 0.

    This is not production repetition or a preservation promise for the lost take.
    """
    api = acquire1_api()
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        with pytest.raises(Exception):
            ctx.acquire()
        assert ctx.evidence().sources == ()
        assert ctx.acquire().cursor == 0
    rig = make_acquire_rig(api, items=(acquire1_item(api),), script=script)
    rig.fail_prepare, rig.source.fail_commit = phase == "prepare", phase == "commit"
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    _, (_, frame) = rig.saved_pair(call)
    assert call.sequence == call.acquired.cursor == frame.value["item"]["value"]["sample_seq"] == 0
    assert rig.source.calls == ([0] if phase == "prepare" else [0, 0]) and rig.clock.fired == [phase]
    rig.no_belief_update()


@pytest.mark.parametrize("mode", ["taken", "empty", "missing", "raises"])
def test_acquire1_one_commit_M_read_is_after_and_both_receipt_times(make_acquire_rig, mode):
    """K25(d2) 1: ticking M distinguishes before/after once from per-envelope rereads."""
    api = acquire1_api()
    rig = make_acquire_rig(api, mode=mode, items=(acquire1_item(api),) if mode == "taken" else (), tick=1)
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    raw, (frame_eh, frame) = rig.saved_pair(call)
    assert [ns for _, ns in call.trace] == [call.acquired.before.reading.time_ns,
        call.acquired.after.reading.time_ns], "prepare/commit must each read M once"
    if mode != "missing":
        assert [phase for phase, _ in call.trace] == ["prepare", "commit"], "before M must precede source.read"
    assert call.acquired.after.reading.time_ns == frame_eh.received_ns == frame.received_ns
    if raw is not None:
        assert raw[0].received_ns == raw[1].received_ns == frame.received_ns
        assert raw[0].envelope != frame_eh.envelope


@pytest.mark.parametrize("owner", ["accepted", "saved"])
def test_acquire1_owner_may_progress_before_worker_receives_return(make_acquire_rig, owner):
    """(A): held public forwarding return permits another thread to move H -> P/C.

    Host method has already returned; no private pre-return hook is claimed.
    At the worker boundary, responsibility can already be P/C rather than H.
    """
    api = acquire1_api()
    rig = make_acquire_rig(api, items=(acquire1_item(api),))
    cut = AcquireStoreCut(rig, block=owner == "accepted")
    if owner == "saved":
        rig.ledger.write = cut.normal_write
    rig.hold_return = True
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    if owner == "accepted":
        rig.until(lambda: all(rig.receipts()[n].state == "accepted" for n in call.envelopes))
        assert cut.fired and not rig.reports("frame") and not rig.facts(c.RECEIVED)
    else:
        rig.saved_pair(call)
    rig.return_release.set()
    cut.block = False
    rig.saved_pair(call)
    assert rig.source.calls == [0] and len(rig.calls) == 1


def test_acquire1_another_measuring_job_does_not_reset_operation_or_source_cursor(make_acquire_rig):
    """Two production worker instances each acquire ONCE under distinct WorkIds in run/route-A."""
    api = acquire1_api()
    item = acquire1_item(api)
    rig = make_acquire_rig(api, items=(item, item), segments=2)
    first = rig.launch("measure_segment", "sensing")
    rig.wait_returns()
    second = rig.launch("measure_segment", "sensing-2")
    rig.wait_returns(2)
    assert first != second and rig.source.calls == [0, 1]
    for seq, call in enumerate(sorted(rig.calls, key=lambda call: call.sequence)):
        _, (_, frame) = rig.saved_pair(call)
        assert call.acquired.route_epoch == ROUTE and call.acquired.cursor == seq
        assert frame.value["item"]["value"]["sample_seq"] == seq
        assert acquire1_corresponds(rig, frame, call)
    assert len({call.work.request for call in rig.calls}) == 2
    rig.no_belief_update()


def test_acquire1_overlapping_acquires_serialize_source_reads_without_blocking_other_post(make_acquire_rig):
    """K25(d2): public effects of the source lock and reading outside the acceptance lock.

    First read stays blocked while the second entered work attempts acquire.
    Another Post must save before releasing that read; source cursors stay 0,1.
    Lock identity/internal instructions are not observed or asserted.
    """
    api = acquire1_api()
    item = acquire1_item(api)
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, items=(item, item), script=script, segments=2)
    rig.source.block = True
    rig.launch("measure_segment", "sensing")
    assert rig.source.reading.wait(30)
    rig.attempted.clear()
    rig.launch("measure_segment", "sensing-2")
    assert rig.attempted.wait(30), "second work did not attempt acquire"
    marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"during-blocked-source", claims={})
    rig.host.post(marker)
    rig.until(lambda: any(r.value == wire(marker) for r in rig.facts(c.RECEIVED)))
    assert not rig.source.release_read.is_set() and rig.source.calls == [0]
    rig.source.release_read.set()
    rig.wait_returns(2)
    assert rig.source.calls == [0, 1]
    for seq, call in enumerate(sorted(rig.calls, key=lambda call: call.sequence)):
        _, (_, frame) = rig.saved_pair(call)
        assert call.acquired.cursor == frame.value["item"]["value"]["sample_seq"] == seq
        assert acquire1_corresponds(rig, frame, call)
    rig.no_belief_update()


def test_acquire1_overlapping_different_routes_keep_each_cursor_and_global_envelopes(make_acquire_rig):
    """K25(d2): different routes share the acquisition gate but number operations per route.

    Each source's first cursor/operation is 0; the four host envelopes are distinct.
    The test workers, not production SourceMeasurer, issue these two calls.
    """
    api = acquire1_api()
    item = acquire1_item(api)
    def script(rig, work, ctx):
        acquire1_started(rig, work, ctx)
        ctx.acquire()
        assert rig.release.wait(30)
    rig = make_acquire_rig(api, items=(item,), script=script, segments=2, second_route_epoch="route-B")
    rig.source.block = True
    rig.launch("measure_segment", "sensing")
    assert rig.source.reading.wait(30)
    rig.attempted.clear()
    rig.launch("measure_segment", "sensing-2")
    assert rig.attempted.wait(30)
    marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"between-route-acquires", claims={})
    rig.host.post(marker)
    rig.until(lambda: any(r.value == wire(marker) for r in rig.facts(c.RECEIVED)))
    assert rig.source.calls == [0] and rig.other_source.calls == []
    rig.source.release_read.set()
    rig.wait_returns(2)
    assert rig.source.calls == rig.other_source.calls == [0]
    assert {call.acquired.route_epoch for call in rig.calls} == {ROUTE, "route-B"}
    envelopes = []
    for call in rig.calls:
        raw, (eh, frame) = rig.saved_pair(call)
        body = frame.value["item"]["value"]
        assert call.sequence == call.acquired.cursor == body["sample_seq"] == 0
        assert body["route_epoch"] == body["measurement_id"]["route_epoch"] == call.route_epoch
        assert body["value"]["value"]["result"] == {"kind": "taken", "received": str(raw[1].record_id)}
        assert raw[1].value == wire(fb.Received(route_epoch=call.route_epoch, media_type=item.media_type,
                                              data=RAW, claims=CLAIMS))
        assert raw[0].received_ns == eh.received_ns == call.acquired.after.reading.time_ns
        assert acquire1_corresponds(rig, frame, call)
        envelopes.extend(call.envelopes)
    assert len(envelopes) == len(set(envelopes)) == 4
    rig.no_belief_update()




@pytest.mark.parametrize("operation", ["now", "acquire"])
def test_acquire1_unentered_port_cannot_read_now_or_acquire(make_acquire_rig, operation):
    """Retain K23 entry guard: no source observation or envelope is invented."""
    api = acquire1_api()
    def script(rig, work, ctx):
        with pytest.raises(RuntimeError):
            getattr(ctx, operation)()
        rig.action_done.set()
    rig = make_acquire_rig(api, script=script)
    key = rig.launch("measure_segment")
    assert rig.action_done.wait(30)
    assert rig.source.calls == [] and not rig.calls and not rig.ports[key].evidence().sources
    assert execution_for(rig.ports[key].delegate, key).entered == 0
    assert execution_for(rig.ports[key].delegate, key).reports == ()


def test_acquire1_entered_compute_can_read_now_but_cannot_acquire(make_acquire_rig):
    api = acquire1_api()
    def compute(rig, work, ctx):
        reading = ctx.now()
        assert isinstance(reading, fb.ReadingClock) and reading.source == rig.one(CLOCK_SOURCE).cid
        before = ctx.evidence().sources
        with pytest.raises(RuntimeError):
            ctx.acquire()
        assert ctx.evidence().sources == before
        rig.action_done.set()
    rig = make_acquire_rig(api, script=acquire1_quiet, compute=compute)
    rig.launch("measure_segment")
    rig.launch("candidate_generation")
    assert rig.action_done.wait(30) and rig.source.calls == []


def test_acquire1_production_measurer_rejects_nonmeasurement_work(make_acquire_rig):
    api = acquire1_api()
    def compute(rig, work, ctx):
        with pytest.raises(TypeError):
            api.SourceMeasurer().run(work, ctx)
        rig.action_done.set()
    rig = make_acquire_rig(api, script=acquire1_quiet, compute=compute)
    rig.launch("measure_segment")
    rig.launch("candidate_generation")
    assert rig.action_done.wait(30) and rig.source.calls == []


@pytest.mark.parametrize("mutation", ["invalid-type", "valid-other-json"])
def test_acquire1_production_preserves_source_claims_changed_at_commit(make_acquire_rig, mutation):
    """K25(1)(a)(c)/(d2), :3902/:3904/:3930: freeze source-owned claims.

    The test source marks commit after its read; its next public Clock read
    changes a nested value before returning the terminal M reading. No runner
    round or worker-side Frame intervenes. An aliased or shallow-copied claims
    dict fails: object() must not cause rejection/Frame-only storage, and valid
    replacement JSON must not silently replace the original saved payload.
    """
    api = acquire1_api()
    source_claims = {"sender_time_ns": -900, "nested": {"text": "original"}}
    expected_claims = {"sender_time_ns": -900, "nested": {"text": "original"}}
    item = api.SourceItem(media_type="application/x-acquire1", data=RAW, claims=source_claims)
    rig = make_acquire_rig(api, items=(item,))  # Production SourceMeasurer, not a scripted worker.
    replacement = object() if mutation == "invalid-type" else "changed"
    mutated_at = []
    read_m = rig.clock.mono_ns

    def mutate_on_terminal_read():
        with rig.clock.lock:
            change = (get_ident() == rig.clock.owner and rig.clock.phase == "commit" and not mutated_at)
            if change:
                assert rig.source.calls == [0]
                source_claims["nested"]["text"] = replacement
            ns = read_m()
            if change:
                mutated_at.append(ns)
            return ns

    rig.clock.mono_ns = mutate_on_terminal_read
    rig.launch("measure_segment")
    rig.wait_returns()
    call, = rig.calls
    assert mutated_at == [call.acquired.after.reading.time_ns], "requested mutation must fire once at after"
    assert source_claims["nested"]["text"] is replacement
    assert call.acquired.outcome == "taken" and len(call.envelopes) == 2
    raw, (frame_eh, frame) = rig.saved_pair(call)
    assert raw is not None
    expected_raw = wire(fb.Received(route_epoch=ROUTE, media_type="application/x-acquire1",
                                    data=RAW, claims=expected_claims))
    assert raw[1].value == expected_raw
    assert len(rig.facts(c.RECEIVED)) == len(rig.reports("frame")) == 1
    rebuilt = acquire1_rebuild(rig.records(), frame.cid)
    assert rebuilt is not None and rebuilt["kind"] == "taken"
    assert rebuilt["raw"].body.content.as_json() == expected_raw
    # Compare with the source's pre-mutation literal, without requiring the
    # worker's returned Acquisition.item to retain an immutable claims dict.
    expected_frame = acquire1_expected_frame(rig, call, raw[1])
    assert frame.value == wire(fb.SegmentReport(segment=call.work.request,
        item_slot="frame:0", item=expected_frame))
    assert rig.source_for(call) == u.SourceObservation(
        work_id=call.work.desc.work_id, route_epoch=ROUTE, cursor=0, sample_seq=0,
        before_ns=call.acquired.before.reading.time_ns, after_ns=mutated_at[0],
        outcome="taken", source_called=True, clock_source=call.acquired.before.source,
        envelope=raw[0].envelope, received=raw[1].cid, received_id=raw[1].record_id,
        frame_envelope=frame_eh.envelope, frame=frame.cid)
    assert raw[0].received_ns == frame_eh.received_ns == raw[1].received_ns == frame.received_ns == mutated_at[0]
    assert rig.source.calls == [0] and len(rig.calls) == 1
    assert rig.host.interruptions() == ()
    rig.no_belief_update()


def test_acquire1_production_copy_memory_error_publishes_nothing_and_preserves_counters(make_acquire_rig):
    """K25(d2), :3932/:3971: host-side resource failure is not source-unavailable.

    A valid dict's public items() raises once during host traversal, armed by a
    normally returning FSource.read. No host function or private state is used.
    Swallowing MemoryError as unavailable fails the no-publication/stop checks;
    publishing half a pair or consuming a counter fails the EH/ES/next-take checks.
    Both jobs use production SourceMeasurer; the TEST gates each returned take until stop().
    The second take is a new observation, not recovery of the lost first result.
    """
    api = acquire1_api()
    fired, source_returns = [], []
    in_source = False

    class CopyLimitedClaims(dict):
        armed = False

        def items(self):
            if self.armed:
                self.armed = False
                fired.append((in_source, tuple(rig.source.calls), rig.clock.phase))
                raise MemoryError("acquire1 source claims copy exhausted memory")
            return super().items()

    claims = CopyLimitedClaims({"sender_time_ns": -900, "nested": {"text": "valid"}})
    item = api.SourceItem(media_type="application/x-acquire1", data=RAW, claims=claims)
    expected_raw = wire(fb.Received(route_epoch=ROUTE, media_type=item.media_type, data=RAW,
        claims={"sender_time_ns": -900, "nested": {"text": "valid"}}))
    rig = make_acquire_rig(api, items=(item,), segments=2)
    rig.expected_errors = (Exception,)  # K25 fixes the effects, not an exception wrapper's class.
    read_source = rig.source.read

    def returning_source(cursor):
        nonlocal in_source
        in_source = True
        try:
            result = read_source(cursor)
            source_returns.append(cursor)
            if len(source_returns) == 1:
                assert result is item
                claims.armed = True
            return result
        finally:
            in_source = False

    rig.source.read = returning_source
    first = rig.launch("measure_segment", "sensing")
    thread, = rig.threads
    thread.join(30)
    assert not thread.is_alive() and rig.errors(), "copy failure must reach the production worker and stop it"
    assert fired == [(False, (0,), "commit")], "fault must fire once outside the normally returning source"
    assert source_returns == rig.source.calls == [0]
    failed, = rig.failed_calls
    assert failed.work.desc.work_id == first
    first_port = rig.ports[first]
    stopped = execution_for(first_port.delegate, first)
    assert stopped.entered == 1 and stopped.stopped
    assert not rig.calls and first_port.evidence().sources == failed.sources_before == ()
    assert tuple(r.envelope for r in stopped.reports) == failed.envelopes_before
    assert acquire1_receipt_signature(rig.receipts()) == acquire1_receipt_signature(failed.receipts_before)
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame")
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")

    # A real subsequent Post witnesses that neither envelope number was consumed.
    prior = max(rig.receipts())
    marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"after-copy-failure", claims={})
    rig.host.post(marker)
    assert max(rig.receipts()) == prior + 1
    rig.until(lambda: any(r.value == wire(marker) for r in rig.facts(c.RECEIVED)))
    assert not rig.reports("frame") and not first_port.evidence().sources

    # Same run/route_epoch, different production worker: probe both public counters.
    second = rig.launch("measure_segment", "sensing-2")
    with rig.changed:
        assert rig.changed.wait_for(lambda: len(rig.calls) == 1, timeout=30)
    call, = rig.calls
    assert call.work.desc.work_id == second and second != first
    assert call.acquired.outcome == "taken"
    raw, (_, frame) = rig.saved_pair(call)
    assert source_returns == rig.source.calls == [0, 0]
    assert call.sequence == call.acquired.cursor == frame.value["item"]["value"]["sample_seq"] == 0
    assert raw[1].value == expected_raw and acquire1_corresponds(rig, frame, call)
    assert len(first_port.evidence().sources) == len(rig.reports("frame")) == 1
    assert len(fired) == 1 and rig.host.interruptions() == ()
    rig.no_belief_update()


@pytest.mark.parametrize("failure", ["deep-json", "source-dict-growth"])
def test_acquire1_production_unfinished_copy_is_not_source_unavailable(make_acquire_rig, failure):
    """K25-b :3529: failure to finish copying/checking is not a proved shape error.

    Deep claims are an acyclic chain of string-keyed dicts with a string leaf,
    beyond the interpreter's recursion limit; no private JSON checker is used.
    In the growth case, the source-owned items() iterator first yields a valid
    pair, then adds a valid pair before resuming its live dict iterator. The
    iterator itself raises RuntimeError; no host function or exception is mocked.
    Turning either failure into unavailable, publishing a partial result or
    consuming counters fails the stop/EH/ES/next-take checks. Each of the two
    production jobs is gated by the test after its returned take. Repairing the external claims
    permits a new observation; it does not recover the failed take's result/time.
    """
    import sys

    api = acquire1_api()
    source_returns, growth, iterator_errors = [], [], []
    in_source = False
    if failure == "deep-json":
        claims = {"leaf": "valid"}
        for _ in range(max(1200, sys.getrecursionlimit() + 100)):
            claims = {"nested": claims}
    else:
        class GrowingClaims(dict):
            armed = False

            def items(self):
                if not self.armed:
                    return super().items()
                self.armed = False
                pairs = iter(super().items())

                def changed_during_traversal():
                    yield next(pairs)
                    self["added-by-source"] = "also valid JSON"
                    growth.append((in_source, tuple(rig.source.calls), rig.clock.phase))
                    try:
                        yield from pairs
                    except RuntimeError as error:
                        iterator_errors.append(error)
                        raise

                return changed_during_traversal()

        claims = GrowingClaims({"first": "valid", "second": "also valid"})

    item = api.SourceItem(media_type="application/x-acquire1", data=RAW, claims=claims)
    rig = make_acquire_rig(api, items=(item,), segments=2)
    rig.expected_errors = (Exception,)  # Effects are fixed; the worker may receive a wrapper.
    read_source = rig.source.read

    def returning_source(cursor):
        nonlocal in_source
        in_source = True
        try:
            result = read_source(cursor)
            assert result is item
            source_returns.append(cursor)
            if failure == "source-dict-growth" and len(source_returns) == 1:
                claims.armed = True
            return result
        finally:
            in_source = False

    rig.source.read = returning_source
    first = rig.launch("measure_segment", "sensing")
    thread, = rig.threads
    thread.join(30)
    assert not thread.is_alive() and rig.errors(), "unfinished copy must reach the worker and stop it"
    assert source_returns == rig.source.calls == [0]
    if failure == "source-dict-growth":
        assert growth == [(False, (0,), "commit")] and len(iterator_errors) == 1
        assert claims["added-by-source"] == "also valid JSON"
    failed, = rig.failed_calls
    assert failed.work.desc.work_id == first
    first_port = rig.ports[first]
    stopped = execution_for(first_port.delegate, first)
    assert stopped.entered == 1 and stopped.stopped
    assert not rig.calls and first_port.evidence().sources == failed.sources_before == ()
    assert tuple(r.envelope for r in stopped.reports) == failed.envelopes_before
    assert acquire1_receipt_signature(rig.receipts()) == acquire1_receipt_signature(failed.receipts_before)
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame")
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")

    prior = max(rig.receipts())
    marker = fb.Received(route_epoch=ROUTE, media_type="text/plain", data=b"after-unfinished-copy", claims={})
    rig.host.post(marker)
    assert max(rig.receipts()) == prior + 1
    rig.until(lambda: any(r.value == wire(marker) for r in rig.facts(c.RECEIVED)))
    assert not rig.reports("frame") and not first_port.evidence().sources

    # The source owner repairs the same mutable claims after the failed take.
    # A fresh take on the same run/route_epoch exposes the unchanged counters.
    claims.clear()
    claims.update({"repaired": "valid"})
    second = rig.launch("measure_segment", "sensing-2")
    with rig.changed:
        assert rig.changed.wait_for(lambda: len(rig.calls) == 1, timeout=30)
    call, = rig.calls
    assert call.work.desc.work_id == second and second != first
    assert call.acquired.outcome == "taken"
    raw, (_, frame) = rig.saved_pair(call)
    assert source_returns == rig.source.calls == [0, 0]
    assert call.sequence == call.acquired.cursor == frame.value["item"]["value"]["sample_seq"] == 0
    assert raw[1].value == wire(fb.Received(route_epoch=ROUTE, media_type=item.media_type,
        data=RAW, claims={"repaired": "valid"}))
    assert acquire1_corresponds(rig, frame, call)
    assert len(first_port.evidence().sources) == len(rig.reports("frame")) == 1
    assert rig.host.interruptions() == ()
    rig.no_belief_update()


@pytest.mark.parametrize("change_at", ["after-first-scan", "before-first-yield"])
def test_acquire1_accept_checks_the_same_snapshot_it_saves(change_at):
    """K25-b star(4) :3529, acceptance :483-485: verify the frozen snapshot.

    A caller-owned dict changes to an invalid integer key inside the first
    public items() traversal. Later traversals return that invalid content.
    Validating the first scan then freezing the second fails the stored literal;
    keeping the caller's mutable dict fails the later mutation before saving.
    Acceptance may succeed with the initial valid snapshot or reject shape;
    rejection must leave neither storage nor custody, including deferred saves.
    This direct-window stage-1 scenario lives here within the allowed files.
    """
    accepting = False
    scans, changes = [], []

    class ChangesDuringRead(dict):
        def items(self):
            first_scan = not scans
            if first_scan and change_at == "before-first-yield":
                self.change_shape()
            pairs = tuple(dict.items(self))
            scans.append(pairs)

            def traverse():
                yield from pairs
                if first_scan and change_at == "after-first-scan":
                    self.change_shape()

            return traverse()

        def change_shape(self):
            dict.clear(self)
            dict.__setitem__(self, 7, "invalid non-string claim key")
            changes.append(accepting)

    rig = RealRig()
    try:
        rig.set_clock(40)
        claims = ChangesDuringRead({"sender": "initial valid claim"})
        event = fb.Received(route_epoch="unknown-route", media_type="application/octet-stream",
                            data=RAW, claims=claims)
        envelope = rig.envelope(1, event, 30)  # No Post: exercise the unfrozen public accept input.
        expected = wire(fb.Received(route_epoch="unknown-route", media_type="application/octet-stream",
                                   data=RAW, claims={"sender": "initial valid claim"}))
        before_store = rig.storage_snapshot()
        before_prepared = tuple(rig.ledger.preparations)
        before_receipts = rig.host.window.status().receipts
        assert not scans and not before_receipts
        rejected = None
        accepting = True
        try:
            rig.host.window.accept(envelope)
        except fb.FbInputError as error:
            rejected = error
        finally:
            accepting = False
        assert changes == [True], "the shape change must actually occur inside accept"
        assert dict(claims) == {7: "invalid non-string claim key"}
        assert scans[0] == ((("sender", "initial valid claim"),) if change_at == "after-first-scan"
                            else ((7, "invalid non-string claim key"),))
        if rejected is not None:
            assert rejected.reason == "shape" and rejected.field.startswith("/")
            for _ in range(3):
                rig.host.window.settle()
            assert rig.host.window.status().receipts == before_receipts
            assert tuple(rig.ledger.preparations) == before_prepared
            assert rig.storage_snapshot() == before_store and not rig.facts(c.RECEIVED)
            assert rig.host.window.drain() == ()
        else:
            # R02: subsequent caller edits cannot change the accepted snapshot.
            dict.clear(claims)
            dict.__setitem__(claims, "after-accept", "must not be saved")
            for _ in range(256):
                rig.host.window.settle()
                if rig.facts(c.RECEIVED):
                    break
            saved, = rig.facts(c.RECEIVED)
            assert saved.value == expected and saved.received_ns == 30
            assert all(type(key) is str for key in saved.value["claims"])
            receipt, = rig.host.window.status().receipts
            assert receipt.envelope == 1 and receipt.state == "accepted"
            assert len(receipt.slots) == 1 and receipt.slots[0].state == "saved"
            assert receipt.slots[0].target == saved.cid
        assert rig.host.halted is None
    finally:
        rig.close()
