"""K23/K23-a (F-b v0.74 :3523-3524), through Boot, real worker ports and Post.

Only papers, public declarations and existing test helpers are used. New K23
names are resolved inside each test, so an absent API fails individual tests.
Correspondence is a test-side predicate, as K23(6) permits. A negative
correspondence does not require a new production rejection rule for B.
"""

from dataclasses import replace
from hashlib import sha256
import inspect
from queue import Queue
from threading import Event
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c, f_update2 as u
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role

from gate_f_facts_cases import finite_world, plain
from test_fb_skeleton import boot, contract, source
from test_fb_stage1 import RealRig, wire
from test_fb_stage2 import PREPARE_BUDGET, EVALUATE_BUDGET, Workers as Stage2Workers
from test_fb_loop import LoopRig, KeepLauncher, registry, delta_args, execution_for, CLOCK_SOURCE


ROUTE = "route-A"
RAW = b"\x00\xffraw\r\n\xe6\x89\x8b\xe7\xb4\x99"
CLAIMS = {"sender_time_ns": -900, "nested": {"text": "unclassified", "values": [1, None, True]}}


def measure1_api():
    """K23(2) is the API specification; no missing name is imported at collection."""
    missing = []
    for owner, names in ((fb, ("FSource", "SourceItem", "Acquisition", "SourceMeasurer")),
                         (fb.FWorkContext, ("now", "acquire")),
                         (u, ("SourceObservation",)), (c, ("SOURCE_SAMPLING",))):
        missing.extend(name for name in names if not hasattr(owner, name))
    if "sources" not in inspect.signature(fb.FThreadHost).parameters:
        missing.append("FThreadHost.sources")
    if "sources" not in getattr(u.TargetEvidence, "__annotations__", {}):
        missing.append("TargetEvidence.sources")
    assert not missing, "K23 public API missing: " + ", ".join(missing)
    return SimpleNamespace(SourceItem=fb.SourceItem, Acquisition=fb.Acquisition,
                           SourceMeasurer=fb.SourceMeasurer, SourceObservation=u.SourceObservation)


class Measure1Source:
    """The declared ordered source retains each item, including equal byte strings."""

    def __init__(self, clock, items, *, raises=False):
        self.clock, self.items, self.raises = clock, tuple(items), raises
        self.calls = []

    def read(self, cursor):
        self.calls.append(cursor)
        # Distinct b/t make an actual_time at b distinguishable from actual_time=t.
        self.clock.set(self.clock.mono_ns() + 2)
        if self.raises:
            raise OSError("measure1 source cannot be read")
        return self.items[cursor] if cursor < len(self.items) else None


class Measure1Workers(Stage2Workers):
    def run(self, work, ctx):
        if work.desc.purpose != "measure_segment":
            return super().run(work, ctx)
        self.rig.measure_work, self.contexts["measure_segment"] = work, ctx
        try:
            if self.rig.script is None:
                self.rig.measurer.run(work, ctx)  # The production worker owns enter().
            else:
                self.rig.script(self.rig, work, ctx)
        except BaseException as error:
            self.errors.append(error)
            raise


class Measure1Rig(LoopRig):
    def __init__(self, api, *, items=(), mode="taken", script=None, compute=None, source_factory=None):
        RealRig.__init__(self, connect=False)
        self.clock.set(0)
        self.api, self.script, self.measure_work = api, script, None
        self.registry, self.thread = registry(), None
        # K23-a(a) fixes zero-argument construction.
        self.measurer = api.SourceMeasurer()
        self.production_stop_requested = False
        self.release, self.action_done, self.other_ready = Event(), Event(), Event()
        self.other_events, self.acquired = Queue(), []
        self.test_events = []
        self.workers = Measure1Workers(self)
        if compute is not None:
            self.workers.overrides["candidate_generation"] = lambda work, ctx: compute(self, work, ctx)
        self.launcher = KeepLauncher(self)
        self.source = (source_factory(self.clock) if source_factory is not None
                       else Measure1Source(self.clock, items, raises=mode == "raises"))
        document, _ = finite_world("FA01")
        model = self.record(Prediction(target="measure1.model", about=(), basis=(),
            content=Payload.json({"document": document}), contract=contract("sui.f.model_source")),
            RefKind.PREDICTION, Role.MODEL)
        self.model_point = self.ledger.append(model, ()).cid
        event = boot(True)
        initial = replace(event.declaration.initial.value, model=self.model_point,
            generator=fb.MethodCall(contract=c.MODEL_OPERATIONS, args={}),
            method=fb.MethodCall(contract=contract("sui.f.finite_evaluation"), args={}),
            draw=fb.MethodCall(contract=contract("stage2.scripted_draw"), args={}),
            prepare_budget=PREPARE_BUDGET, evaluate_budget=EVALUATE_BUDGET,
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=c.SAVED_SEGMENT_UPDATE, args=delta_args())), continuation=None)
        self.boot_input = replace(event, declaration=replace(event.declaration,
            initial=replace(event.declaration.initial, value=initial),
            routes=tuple(replace(route, value=replace(route.value, config=replace(route.value.config,
                sampling_contract=c.SOURCE_SAMPLING,
                clock_contract=contract("sui.f.simulated_clock")))) for route in event.declaration.routes)))
        self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
            registry=self.registry, launcher=self.launcher,
            sources=None if mode == "missing" else {ROUTE: self.source})
        self.host.post(fb.ClockDeclared(declaration=replace(source(), run=self.clock.run,
            measurement=contract("sui.f.simulated_clock"))))
        self.host.post(self.boot_input)

    def drive(self, predicate):
        def done(_status):
            errors = self.workers.errors + self.launcher.errors
            assert not errors, "worker failed: " + str([(type(e).__name__, str(e)) for e in errors])
            return "measure_segment" in self.workers.contexts and predicate()
        assert self.host.keep_running(done, timeout=60), "incomplete observation: public successor missing"

    def reports(self, kind):
        return [r for r in self.facts(c.SEGMENT_REPORT) if r.value["item"]["kind"] == kind]

    def evidence(self):
        return self.workers.contexts["measure_segment"].evidence()

    def observation(self):
        assert isinstance(self.evidence().sources, tuple)
        result, = self.evidence().sources
        assert isinstance(result, self.api.SourceObservation)
        return result

    def post(self, ctx, event):
        self.test_events.append(event)
        ctx.post(event)

    def stop_production(self):
        self.clock.set(self.clock.mono_ns() + 7)
        stopped_ns = self.clock.mono_ns()
        self.production_stop_requested = True
        self.measurer.stop()
        self.drive(lambda: bool(self.reports("ended")) and bool(self.reports("coverage_unproved"))
                   and execution_for(self.workers.contexts["measure_segment"], self.measure_work.desc.work_id).stopped)
        return stopped_ns

    def assert_no_frame_update(self):
        assert not self.requests("belief_update")
        assert not self.facts(c.UPDATE_RESULT) and not self.facts(c.BELIEF_ADOPTED)
        assert not self.reports("claim"), "source sampling invented a no_arrival Claim"
        assert self.host.halted is None

    def close(self):
        self.release.set()
        if self.script is None and not self.production_stop_requested:
            self.production_stop_requested = True
            self.measurer.stop()
        for thread in self.launcher.threads:
            thread.join(30)
            assert not thread.is_alive(), "incomplete observation: test worker did not stop"


@pytest.fixture
def make_measure1_rig():
    rigs = []
    def make(api, **kwargs):
        rig = Measure1Rig(api, **kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs):
        rig.close()


def measure1_started(rig, work, ctx):
    assert ctx.enter()
    reading = ctx.now()
    rig.post(ctx, fb.SegmentReport(segment=work.request, item_slot="started",
        item=fb.SegmentBoundary(kind="started", work=work.desc.work_id, reading=reading,
                               reason="entered", evidence=())))
    return reading


def measure1_frame(rig, cursor, before, after, item):
    """K23(e), from the declared payload and actual acquire/now return values."""
    return f.MeasurementFrame(route_epoch=ROUTE, sample_seq=cursor,
        measurement_id=f.MeasurementId(origin=before.reading.run, route_epoch=ROUTE,
                                       sample_seq=cursor, component="raw_payload"),
        measurement_interval=f.MeasurementInterval(clock=before.reading.run,
            start_ns=before.reading.time_ns, end_ns=after.reading.time_ns, closure="[start,end]"),
        actual_time=after.reading,
        value={"media_type": item.media_type, "length": len(item.data), "sha256": sha256(item.data).hexdigest()},
        quality=f.ContractValue(contract=contract("sui.f.measured_quality"), value="measured"),
        gap=None, source_cursor=f.ContractValue(contract=contract("sui.f.sequence_cursor"), value=cursor))


def measure1_corresponds(rig, report, observed):
    """K23(1)(5), independent of B and of the worker's claimed digest/time.

    Check w/k/route, source envelope->saved raw, actual worker-port provenance,
    n/ID/cursor, b/t/run, actual_time=t and SHA-256/media/length of saved raw bytes.
    """
    if observed.outcome != "taken" or observed.received is None or observed.envelope is None:
        return False
    work = rig.measure_work
    evidence = rig.evidence()
    execution = execution_for(rig.workers.contexts["measure_segment"], observed.work_id)
    if (observed.work_id != work.desc.work_id or execution.entered != 1
            or report.value["segment"] != work.request or report.value["item"]["kind"] != "frame"):
        return False
    if not any(r.envelope == observed.envelope and r.point == observed.received for r in execution.reports):
        return False
    if not any(r.point == report.cid for r in execution.reports):
        return False
    raw = rig.one(c.RECEIVED, cid=observed.received)
    data = bytes(raw.value["data"])
    frame = report.value["item"]["value"]
    run, n = str(rig.clock.run), observed.cursor
    return (type(n) is int and n >= 0 and type(frame["sample_seq"]) is int
        and type(frame["measurement_id"]["sample_seq"]) is int
        and type(frame["source_cursor"]["value"]) is int
        and observed in evidence.sources and observed.route_epoch == ROUTE == raw.value["route_epoch"]
        and report.value["item_slot"] == f"frame:{n}"
        and frame["route_epoch"] == ROUTE and frame["sample_seq"] == n
        and frame["measurement_id"] == {"origin": run, "route_epoch": ROUTE, "sample_seq": n, "component": "raw_payload"}
        and frame["source_cursor"] == {"contract": plain(contract("sui.f.sequence_cursor")), "value": n}
        and observed.before_ns <= observed.after_ns
        and frame["measurement_interval"] == {"clock": run, "start_ns": observed.before_ns,
            "end_ns": observed.after_ns, "closure": "[start,end]"}
        and frame["actual_time"] == {"kind": "clock", "value": {"run": run, "time_ns": observed.after_ns}}
        and frame["value"] == {"kind": "value", "value": {"media_type": raw.value["media_type"],
            "length": len(data), "sha256": sha256(data).hexdigest()}}
        and frame["quality"] == {"contract": plain(contract("sui.f.measured_quality")), "value": "measured"}
        and frame["gap"] is None)


def measure1_assert_stopped_reports(rig, observed, stopped_ns):
    started, = rig.reports("started")
    ended, = rig.reports("ended")
    unproved, = rig.reports("coverage_unproved")
    start = started.value["item"]["value"]
    finish = ended.value["item"]["value"]
    clock_source = rig.one(CLOCK_SOURCE).cid
    assert start["work"] == finish["work"] == rig.measure_work.desc.work_id
    assert start["reason"] == "entered" and finish["reason"] == "stopped"
    assert start["evidence"] == finish["evidence"] == []
    assert start["reading"]["value"]["source"] == finish["reading"]["value"]["source"] == clock_source
    assert start["reading"]["value"]["reading"]["time_ns"] <= observed.before_ns
    assert finish["reading"]["value"]["reading"] == {"run": str(rig.clock.run), "time_ns": stopped_ns}
    assert unproved.value["item"]["value"] == {"route_epoch": ROUTE,
        "interval": {"clock": str(rig.clock.run), "start_ns": observed.after_ns,
                     "end_ns": stopped_ns, "closure": "(start,end]"},
        "missing_contracts": [plain(c.NO_ARRIVAL)], "evidence": []}
    execution = execution_for(rig.workers.contexts["measure_segment"], rig.measure_work.desc.work_id)
    assert execution.entered == 1 and execution.launches == ("launched",) and execution.stopped


def test_measure1_public_source_sampling_contract_and_shapes():
    """K23(a)-(f): absence is per-test red, and source_sampling is declared measurement/1."""
    api = measure1_api()
    assert not inspect.signature(api.SourceMeasurer).parameters
    assert c.SOURCE_SAMPLING == contract("sui.fb.source_sampling")
    declared = [d for d in u.fb_registry_v1().declarations if d.ref == c.SOURCE_SAMPLING]
    assert len(declared) == 1 and declared[0].kind == "measurement"
    inspect.signature(fb.FSource.read).bind(None, 0)
    assert inspect.signature(fb.FThreadHost).parameters["sources"].default is None
    assert {"media_type", "data", "claims"} <= api.SourceItem.__annotations__.keys()
    assert {"route_epoch", "cursor", "before", "after", "outcome", "reason", "item"} <= api.Acquisition.__annotations__.keys()
    assert {"work_id", "route_epoch", "cursor", "before_ns", "after_ns", "outcome", "envelope", "received"} <= api.SourceObservation.__annotations__.keys()


def test_measure1_production_worker_preserves_raw_frame_binding_and_actual_stop(make_measure1_rig):
    """K23(5) positive: raw loss/copy, invented provenance or Ended-as-stop each fails an independent observation."""
    api = measure1_api()
    item = api.SourceItem(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    rig = make_measure1_rig(api, items=(item,))
    rig.drive(lambda: len(rig.reports("frame")) == 1 and bool(rig.evidence().sources)
              and rig.observation().received is not None)
    observed = rig.observation()
    report, = rig.reports("frame")
    assert observed.outcome == "taken" and observed.cursor == 0
    assert rig.source.calls == [0] and measure1_corresponds(rig, report, observed)
    raw = rig.one(c.RECEIVED, cid=observed.received)
    assert raw.value == wire(fb.Received(route_epoch=ROUTE, media_type=item.media_type, data=RAW, claims=CLAIMS))
    assert isinstance(rig.measure_work.desc.args.requested, fb.Ongoing)
    assert rig.measure_work.desc.args.requested.clock == rig.clock.run
    rig.drive(lambda: any(b.value["report"] == report.cid for b in rig.facts(c.SEGMENT_BINDING)))
    binding, = [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == report.cid]
    started, = rig.reports("started")
    assert binding.value["segment"] == rig.measure_work.request
    assert binding.value["route"] == rig.measure_work.desc.args.route
    assert binding.value["reading_contract"] == plain(c.FINITE_SEGMENT_PROJECTION)
    assert binding.value["generation"] == {"applied": binding.value["route"], "started": started.cid, "ended": None}
    assert binding.value["clock"] == [rig.one(CLOCK_SOURCE).cid]
    assert not execution_for(rig.workers.contexts["measure_segment"], rig.measure_work.desc.work_id).stopped
    assert not rig.reports("ended") and not rig.reports("coverage_unproved")
    stopped_ns = rig.stop_production()
    measure1_assert_stopped_reports(rig, observed, stopped_ns)
    rig.drive(lambda: len(rig.facts(c.SELECTION)) == 1)
    assert rig.source.calls == [0]
    rig.assert_no_frame_update()


@pytest.mark.parametrize("mode", ("empty", "missing", "raises"))
def test_measure1_empty_missing_and_failed_source_remain_distinct_from_measurement(make_measure1_rig, mode):
    """K23(c)(f): a source failure cannot become empty, a zero Frame or a no_arrival Claim."""
    api = measure1_api()
    rig = make_measure1_rig(api, mode=mode)
    rig.drive(lambda: len(rig.reports("measurement_unavailable")) == 1 and bool(rig.evidence().sources))
    observed = rig.observation()
    assert observed.outcome == ("empty" if mode == "empty" else "unavailable")
    assert observed.cursor == 0  # K23-a(b): even an unavailable attempt names the attempted cursor.
    assert observed.work_id == rig.measure_work.desc.work_id and observed.route_epoch == ROUTE
    assert observed.envelope is None and observed.received is None
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame")
    unavailable, = rig.reports("measurement_unavailable")
    body = unavailable.value["item"]["value"]
    assert body["route_epoch"] == ROUTE and body["evidence"] == []
    assert body["requested_interval"] == {"clock": str(rig.clock.run), "start_ns": observed.before_ns,
        "end_ns": observed.after_ns, "closure": "[start,end]"}
    if mode == "empty":
        assert body["reason"] == "source_empty" and rig.source.calls == [0]
    else:
        assert body["reason"].startswith("source_unavailable:") and body["reason"].removeprefix("source_unavailable:")
        assert rig.source.calls == ([] if mode == "missing" else [0])
    stopped_ns = rig.stop_production()
    measure1_assert_stopped_reports(rig, observed, stopped_ns)
    rig.assert_no_frame_update()


@pytest.mark.parametrize("fault", ("no-acquisition", "wrong-sha256", "different-port", "early-actual-time"))
def test_measure1_saved_frame_can_fail_source_correspondence_without_losing_the_report(make_measure1_rig, fault):
    """K23(5): an elegant Frame, digest alone or plausible time cannot replace actual w/n/b/t provenance.

    No new production gate is required here: source-to-Frame correspondence belongs to this test predicate (K23(6)).
    """
    api = measure1_api()
    item = api.SourceItem(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    def script(rig, work, ctx):
        before = measure1_started(rig, work, ctx)
        if fault == "no-acquisition":
            rig.clock.set(rig.clock.mono_ns() + 2)
            frame = measure1_frame(rig, 0, before, ctx.now(), item)
        else:
            acquired = ctx.acquire()
            rig.acquired.append(acquired)
            assert isinstance(acquired, api.Acquisition) and acquired.outcome == "taken"
            frame = measure1_frame(rig, acquired.cursor, acquired.before, acquired.after, item)
            if fault == "wrong-sha256":
                frame = replace(frame, value={**frame.value, "sha256": "0" * 64})
            if fault == "early-actual-time":
                assert acquired.before.reading.time_ns < acquired.after.reading.time_ns
                frame = replace(frame, actual_time=acquired.before.reading)
        event = fb.SegmentReport(segment=work.request, item_slot="frame:0", item=frame)
        rig.test_events.append(event)
        if fault == "different-port":
            rig.other_events.put(event)
            assert rig.action_done.wait(30), "other entered port did not Post"
        else:
            ctx.post(event)
    def other_port(rig, work, ctx):
        rig.other_ready.set()
        ctx.post(rig.other_events.get(timeout=30))
        rig.action_done.set()
    rig = make_measure1_rig(api, items=(item,), script=script,
                            compute=other_port if fault == "different-port" else None)
    rig.drive(lambda: len(rig.reports("frame")) == 1 and (fault == "no-acquisition"
              or bool(rig.evidence().sources) and rig.observation().received is not None))
    report, = rig.reports("frame")
    assert report.value == wire(rig.test_events[-1])
    assert not any(measure1_corresponds(rig, report, observed) for observed in rig.evidence().sources)
    if fault == "no-acquisition":
        assert rig.source.calls == [] and rig.evidence().sources == () and not rig.facts(c.RECEIVED)
    else:
        observed = rig.observation()
        assert rig.one(c.RECEIVED, cid=observed.received).value == wire(
            fb.Received(route_epoch=ROUTE, media_type=item.media_type, data=RAW, claims=CLAIMS))
    if fault == "different-port":
        worker = next(w for w in rig.workers.entries if w.desc.purpose == "candidate_generation")
        assert execution_for(rig.workers.contexts["candidate_generation"], worker.desc.work_id).entered == 1
        assert not any(r.point == report.cid for r in execution_for(
            rig.workers.contexts["measure_segment"], rig.measure_work.desc.work_id).reports)
    rig.assert_no_frame_update()


def test_measure1_taken_raw_survives_worker_return_without_any_frame(make_measure1_rig):
    """K23(c): omitting the Frame cannot silently discard the raw item already taken by the host."""
    api = measure1_api()
    item = api.SourceItem(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    def script(rig, work, ctx):
        measure1_started(rig, work, ctx)
        rig.acquired.append(ctx.acquire())
    rig = make_measure1_rig(api, items=(item,), script=script)
    rig.drive(lambda: bool(rig.evidence().sources) and rig.observation().received is not None
              and execution_for(rig.workers.contexts["measure_segment"], rig.measure_work.desc.work_id).stopped)
    observed = rig.observation()
    assert observed.outcome == "taken" and not rig.reports("frame")
    assert rig.one(c.RECEIVED, cid=observed.received).value == wire(
        fb.Received(route_epoch=ROUTE, media_type=item.media_type, data=RAW, claims=CLAIMS))
    assert rig.source.calls == [0]


@pytest.mark.parametrize("operation", ("now", "acquire"))
def test_measure1_unentered_port_cannot_read_now_or_acquire(make_measure1_rig, operation):
    """K23(b)(c): the unentered measuring port must not read the source or add a source observation."""
    api = measure1_api()
    def script(rig, work, ctx):
        with pytest.raises(RuntimeError):
            getattr(ctx, operation)()
        rig.action_done.set()
    rig = make_measure1_rig(api, script=script)
    rig.drive(rig.action_done.is_set)
    assert rig.source.calls == [] and rig.evidence().sources == ()
    assert execution_for(rig.workers.contexts["measure_segment"], rig.measure_work.desc.work_id).entered == 0


def measure1_quiet_entered(rig, work, ctx):
    measure1_started(rig, work, ctx)
    assert rig.release.wait(60), "test did not release quiet measurement worker"


def test_measure1_entered_compute_port_can_read_now_but_cannot_acquire(make_measure1_rig):
    """K23(b) permits now for an entered job; (c) restricts acquire to a measuring job."""
    api = measure1_api()
    def compute(rig, work, ctx):
        reading = ctx.now()
        assert isinstance(reading, fb.ReadingClock) and reading.reading.run == rig.clock.run
        assert reading.source == rig.one(CLOCK_SOURCE).cid
        before = ctx.evidence().sources
        with pytest.raises(RuntimeError):
            ctx.acquire()
        assert ctx.evidence().sources == before
        rig.action_done.set()
    rig = make_measure1_rig(api, script=measure1_quiet_entered, compute=compute)
    rig.drive(rig.action_done.is_set)
    assert rig.source.calls == []


def test_measure1_production_measurer_rejects_a_nonmeasurement_work(make_measure1_rig):
    """K23(f) requires TypeError for a Compute work, without taking an item."""
    api = measure1_api()
    def compute(rig, work, ctx):
        measurer = api.SourceMeasurer()
        with pytest.raises(TypeError):
            measurer.run(work, ctx)
        rig.action_done.set()
    rig = make_measure1_rig(api, script=measure1_quiet_entered, compute=compute)
    rig.drive(rig.action_done.is_set)
    assert rig.source.calls == []


def test_measure1_equal_bytes_are_two_cursor_items_and_do_not_cross_match(make_measure1_rig):
    """K23(c)(5): digest equality must not identify cursor 0 and cursor 1 as the same take.

    The test worker takes twice through the public port; the production worker's one-take rule is unchanged.
    """
    api = measure1_api()
    item = api.SourceItem(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    def script(rig, work, ctx):
        measure1_started(rig, work, ctx)
        for _ in range(2):
            acquired = ctx.acquire()
            assert isinstance(acquired, api.Acquisition) and acquired.outcome == "taken"
            assert acquired.reason == ""  # K23-a(c).
            assert acquired.item == item and acquired.route_epoch == ROUTE
            assert acquired.before.source == acquired.after.source == rig.one(CLOCK_SOURCE).cid
            assert acquired.before.reading.run == acquired.after.reading.run == rig.clock.run
            rig.acquired.append(acquired)
            rig.post(ctx, fb.SegmentReport(segment=work.request, item_slot=f"frame:{acquired.cursor}",
                item=measure1_frame(rig, acquired.cursor, acquired.before, acquired.after, item)))
    rig = make_measure1_rig(api, items=(item, item), script=script)
    rig.drive(lambda: len(rig.reports("frame")) == 2 and len(rig.evidence().sources) == 2
              and all(s.received is not None for s in rig.evidence().sources))
    first, second = sorted(rig.evidence().sources, key=lambda s: s.cursor)
    frames = sorted(rig.reports("frame"), key=lambda r: r.value["item"]["value"]["sample_seq"])
    assert rig.source.calls == [0, 1] and [a.cursor for a in rig.acquired] == [0, 1]
    assert (first.cursor, second.cursor) == (0, 1)
    assert first.envelope != second.envelope and first.received != second.received
    assert rig.one(c.RECEIVED, cid=first.received).value == rig.one(c.RECEIVED, cid=second.received).value
    assert measure1_corresponds(rig, frames[0], first)
    assert measure1_corresponds(rig, frames[1], second)
    assert not measure1_corresponds(rig, frames[0], second)
    assert not measure1_corresponds(rig, frames[1], first)
    rig.assert_no_frame_update()


class Measure1ReturningSource(Measure1Source):
    """An external source defect, supplied through the public FSource boundary."""

    def __init__(self, clock, value):
        super().__init__(clock, ())
        self.value = value

    def read(self, cursor):
        self.calls.append(cursor)
        self.clock.set(self.clock.mono_ns() + 2)
        return self.value


def measure1_invalid_source_value(api, fault):
    if fault == "wrong-object":
        return "not a SourceItem"
    if fault == "lookalike":
        return SimpleNamespace(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    if fault == "media-type":
        return api.SourceItem(media_type=7, data=RAW, claims=CLAIMS)
    if fault == "data":
        return api.SourceItem(media_type="application/x-measure1", data="not bytes", claims=CLAIMS)
    return api.SourceItem(media_type="application/x-measure1", data=RAW, claims={1: "non-string JSON key"})


@pytest.mark.parametrize("mode", ("empty", "missing", "raises"))
def test_measure1_failed_attempt_cursor_and_reason_are_preserved_on_another_acquire(make_measure1_rig, mode):
    """K23-a(b)(c): empty/unavailable do not consume cursor 0; only taken advances it.

    Advancing on failure, inventing an item, or returning the wrong reason branch fails both actual port returns and ES.
    """
    api = measure1_api()
    def script(rig, work, ctx):
        measure1_started(rig, work, ctx)
        for _ in range(2):
            acquired = ctx.acquire()
            rig.acquired.append(acquired)
            assert acquired.route_epoch == ROUTE and acquired.cursor == 0
            assert acquired.outcome == ("empty" if mode == "empty" else "unavailable")
            assert acquired.item is None and isinstance(acquired.reason, str)
            assert (acquired.reason == "") == (mode == "empty")
        rig.action_done.set()
    rig = make_measure1_rig(api, mode=mode, script=script)
    rig.drive(rig.action_done.is_set)
    assert len(rig.evidence().sources) == 2
    assert [s.cursor for s in rig.evidence().sources] == [0, 0]
    assert [s.outcome for s in rig.evidence().sources] == [a.outcome for a in rig.acquired]
    assert all(s.work_id == rig.measure_work.desc.work_id and s.route_epoch == ROUTE
               and s.envelope is None and s.received is None for s in rig.evidence().sources)
    assert rig.source.calls == ([] if mode == "missing" else [0, 0])
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame")


@pytest.mark.parametrize("fault", ("wrong-object", "lookalike", "media-type", "data", "claims"))
def test_measure1_invalid_source_return_is_unavailable_and_does_not_consume_cursor(make_measure1_rig, fault):
    """K23-a(e): malformed external values are unavailable, with no raw save or cursor consumption.

    Accepting a foreign value or a wrongly typed SourceItem fails production Unavailable and repeated cursor-0 attempts.
    Accepting a non-SourceItem merely because its three fields have valid types fails the lookalike case.
    """
    api = measure1_api()
    value = measure1_invalid_source_value(api, fault)
    if fault == "lookalike":
        assert not isinstance(value, api.SourceItem)
        assert isinstance(value.media_type, str) and isinstance(value.data, bytes)
        assert value.claims == CLAIMS
    factory = lambda clock: Measure1ReturningSource(clock, value)
    rig = make_measure1_rig(api, source_factory=factory)
    rig.drive(lambda: bool(rig.evidence().sources))
    observed = rig.observation()
    assert observed.outcome == "unavailable" and observed.cursor == 0
    assert observed.envelope is None and observed.received is None and rig.source.calls == [0]
    rig.drive(lambda: len(rig.reports("measurement_unavailable")) == 1)
    unavailable, = rig.reports("measurement_unavailable")
    reason = unavailable.value["item"]["value"]["reason"]
    assert reason.startswith("source_unavailable:") and reason.removeprefix("source_unavailable:")
    assert not rig.facts(c.RECEIVED) and not rig.reports("frame")
    stopped_ns = rig.stop_production()
    measure1_assert_stopped_reports(rig, observed, stopped_ns)
    rig.assert_no_frame_update()

    def script(repeated, work, ctx):
        measure1_started(repeated, work, ctx)
        for _ in range(2):
            acquired = ctx.acquire()
            repeated.acquired.append(acquired)
            assert acquired.outcome == "unavailable" and acquired.cursor == 0
            assert acquired.item is None and isinstance(acquired.reason, str) and acquired.reason
        repeated.action_done.set()
    repeated = make_measure1_rig(api, source_factory=factory, script=script)
    repeated.drive(repeated.action_done.is_set)
    assert repeated.source.calls == [0, 0]
    assert [s.cursor for s in repeated.evidence().sources] == [0, 0]
    assert all(s.outcome == "unavailable" and s.envelope is None and s.received is None
               for s in repeated.evidence().sources)
    assert not repeated.facts(c.RECEIVED) and not repeated.reports("frame")


class Measure1BlockingSource(Measure1Source):
    """Hold read() outside the runner until a conflicting ClockDeclared is saved."""

    def __init__(self, clock, item):
        super().__init__(clock, (item,))
        self.reading, self.release_read = Event(), Event()

    def read(self, cursor):
        self.calls.append(cursor)
        self.reading.set()
        assert self.release_read.wait(60), "test did not release the source read"
        self.clock.set(self.clock.mono_ns() + 2)
        return self.items[cursor] if cursor < len(self.items) else None


@pytest.mark.parametrize("worker", ("port-script", "production"))
def test_measure1_inflight_take_pins_clock_and_keeps_raw_when_clock_declarations_conflict(make_measure1_rig, worker):
    """K23-a(f): an already performed take retains its first clock Point through read().

    Reselecting after-source clock or losing the take fails raw/ES/Frame correspondence; permitting B fails the use gate.
    The port-script also checks both Points directly and checks RuntimeError for later now/acquire.
    The production case observes the real SourceMeasurer returning after stop without false tail/Ended reports.
    """
    api = measure1_api()
    item = api.SourceItem(media_type="application/x-measure1", data=RAW, claims=CLAIMS)
    def script(rig, work, ctx):
        measure1_started(rig, work, ctx)
        acquired = ctx.acquire()
        rig.acquired.append(acquired)
        assert acquired.outcome == "taken" and acquired.reason == "" and acquired.item == item
        rig.post(ctx, fb.SegmentReport(segment=work.request, item_slot=f"frame:{acquired.cursor}",
            item=measure1_frame(rig, acquired.cursor, acquired.before, acquired.after, item)))
        assert rig.release.wait(60), "test did not release the post-take worker"
        with pytest.raises(RuntimeError):
            ctx.now()
        with pytest.raises(RuntimeError):
            ctx.acquire()
        rig.action_done.set()
    def quiet_compute(rig, work, ctx):
        assert rig.release.wait(60), "test did not release the unrelated compute worker"
    rig = make_measure1_rig(api, script=script if worker == "port-script" else None,
        compute=quiet_compute, source_factory=lambda clock: Measure1BlockingSource(clock, item))
    try:
        rig.drive(rig.source.reading.is_set)
        original_clock = rig.one(CLOCK_SOURCE).cid
        conflicting = replace(source(), run=rig.clock.run, measurement=contract("sui.f.simulated_clock"),
                              provider="measure1-conflicting-clock")
        rig.host.post(fb.ClockDeclared(declaration=conflicting))
        rig.drive(lambda: any(n.value == wire(conflicting) for n in rig.facts(c.CLOCK_NOTICE)))
        assert not rig.source.release_read.is_set() and rig.source.calls == [0]
        rig.source.release_read.set()
        rig.drive(lambda: len(rig.reports("frame")) == 1 and bool(rig.evidence().sources)
                  and rig.observation().received is not None)
        observed = rig.observation()
        report, = rig.reports("frame")
        assert observed.outcome == "taken" and observed.cursor == 0
        assert measure1_corresponds(rig, report, observed)
        raw = rig.one(c.RECEIVED, cid=observed.received)
        assert raw.value == wire(fb.Received(route_epoch=ROUTE, media_type=item.media_type, data=RAW, claims=CLAIMS))
        if worker == "port-script":
            acquired, = rig.acquired
            assert acquired.before.source == acquired.after.source == original_clock
            assert acquired.before.reading.time_ns == observed.before_ns
            assert acquired.after.reading.time_ns == observed.after_ns
        for _ in range(16):
            assert rig.host.keep_running(lambda _status: True, timeout=0)
        assert not [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == report.cid]
        assert not rig.workers.errors and not rig.launcher.errors
        rig.clock.set(rig.clock.mono_ns() + 7)
        if worker == "production":
            rig.production_stop_requested = True
            rig.measurer.stop()
        rig.release.set()
        ctx = rig.workers.contexts["measure_segment"]
        assert rig.host.keep_running(lambda _status: execution_for(ctx, rig.measure_work.desc.work_id).stopped,
                                     timeout=60), "actual worker stop was not observed"
        errors = {id(e): e for e in rig.workers.errors + rig.launcher.errors}.values()
        assert all(isinstance(error, RuntimeError) for error in errors), "unexpected worker failure after stop"
        if worker == "port-script":
            assert rig.action_done.is_set() and not rig.workers.errors
        assert not rig.reports("coverage_unproved") and not rig.reports("ended")
        assert rig.source.calls == [0] and len(rig.evidence().sources) == 1
        assert rig.one(c.RECEIVED, cid=observed.received).value == raw.value
        assert rig.host.halted is None
        rig.assert_no_frame_update()
    finally:
        rig.source.release_read.set()
        rig.release.set()
