"""K28: binding probes use production acquisition Frames, never producer Frames.

Only the still-public Started branch is delayed/changed/redelivered by a test
forwarding port. SourceMeasurer calls acquire; a held public forwarding return
keeps Ended out of the binding scene until cleanup. B is never injected.
"""

from dataclasses import replace
from itertools import permutations

import pytest

from sui import f, fb, fb_contracts as c
from test_fb_belief import PROJECTION, T, belief1_status
from test_fb_acquisition_loop import AcquisitionLoopRig
from test_fb_measure import AcquirePort
from test_fb_loop import CLOCK_SOURCE, ROUTE, execution_for
from test_fb_acquisition_pending import original_envelopes
from test_fb_stage1 import wire


class BindingPort(AcquirePort):
    def post(self, event, issued=None):
        if isinstance(event, fb.SegmentReport) and isinstance(event.item, fb.SegmentBoundary) and event.item.kind == "started":
            self.rig.original_started = event
            self.rig.started_port = self
            if self.rig.delay_started:
                self.rig.held_started = event
                return None
            if self.rig.started_ns is not None:
                event = replace(event, item=replace(event.item, reading=replace(event.item.reading,
                    reading=replace(event.item.reading.reading, time_ns=self.rig.started_ns))))
        return super().post(event, issued=issued)


class AcquisitionBindingRig(AcquisitionLoopRig):
    def __init__(self, *, delay_started=False, started_ns=None, reading=PROJECTION, launch_hook=None):
        self.delay_started, self.started_ns = delay_started, started_ns
        self.original_started = self.held_started = self.started_port = None
        def install(rig):
            route, = rig.boot_input.declaration.routes
            rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
                routes=(replace(route, value=replace(route.value, reading_contract=reading)),)))
            rig.port_type = BindingPort
            if launch_hook is not None: launch_hook(rig)
        super().__init__(symbols=(T,), before_host=install)
        self.hold_return = True
        self.clock.set(200)

    def frame(self):
        _raw, (_observation, fact) = self.publish(0, last=True)
        return fact

    def deliver_started(self, ns=None):
        event = self.held_started
        assert event is not None
        if ns is not None:
            event = replace(event, item=replace(event.item, reading=replace(event.item.reading,
                reading=replace(event.item.reading.reading, time_ns=ns))))
        self.started_port.delegate.post(event)
        self.until(lambda: any(r.value == wire(event) for r in self.reports("started")))
        return next(r for r in self.reports("started") if r.value == wire(event))


@pytest.fixture
def make_binding():
    rigs = []
    def make(**kwargs):
        rig = AcquisitionBindingRig(**kwargs)
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs): rig.close()


def bindings_for(rig, frame):
    return [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] == frame.cid]


def pending_for(rig, frame):
    return [(p.kind, p.reason) for p in rig.host.window.status().pending if p.target == frame.cid]


def test_frame_binding_content_and_parents(make_binding):
    """B1-7 and K28(2)(d): real Frame B has exact provenance/front/view.

    Wrong segment/route/source/generation, a duplicated B or fabricated parents fails.
    """
    rig = make_binding()
    rig.begin()
    frame = rig.frame()
    rig.until(lambda: len(bindings_for(rig, frame)) == 1)
    b, = bindings_for(rig, frame)
    k = rig.one(c.SEGMENT_REQUESTED).cid
    route = rig.one(ROUTE).cid
    started = rig.one(c.SEGMENT_REPORT, cid=next(r.cid for r in rig.reports("started")))
    clock = rig.one(CLOCK_SOURCE).cid
    assert b.value["segment"] == k and b.value["report"] == frame.cid and b.value["route"] == route
    assert b.value["reading_contract"] == wire(PROJECTION)
    assert b.value["generation"] == {"applied": route, "started": started.cid, "ended": None}
    assert b.value["clock"] == [clock] and b.value["evidence"] == []
    assert b.parents == frozenset({k, frame.cid, started.cid})
    assert set(b.value["view"]["boundary"]) == {k, frame.cid, route, started.cid, clock}
    assert not pending_for(rig, frame)


def test_started_arriving_later_binds_on_a_later_settle(make_binding):
    """A valid production Frame waits for Started and binds after its late Post.

    Binding without Started, losing the Frame or retaining the old shortage fails.
    """
    rig = make_binding(delay_started=True)
    rig.begin()
    frame = rig.frame()
    assert not bindings_for(rig, frame)
    assert ("awaiting_evidence", "started") in pending_for(rig, frame)
    row = belief1_status(rig, 0)
    assert row.outcome == "waiting_binding" and row.request is None and "started" in row.reasons
    rig.clock.set(220)
    started = rig.deliver_started()
    rig.until(lambda: len(bindings_for(rig, frame)) == 1)
    assert bindings_for(rig, frame)[0].value["generation"]["started"] == started.cid
    assert not pending_for(rig, frame)


@pytest.mark.parametrize("start_ns,ok", ((200, True), (199, False)))
def test_started_before_the_observed_entry_is_not_bound(make_binding, start_ns, ok):
    """Only Started changes; the real entry is at M=200 and the Frame is authentic.

    Accepting a pre-entry Started fails the no-B/conflict control.
    """
    rig = make_binding(started_ns=start_ns)
    rig.begin()
    frame = rig.frame()
    rig.until(lambda: bool(bindings_for(rig, frame)) or bool(pending_for(rig, frame)))
    assert len(bindings_for(rig, frame)) == int(ok)
    if not ok: assert ("conflict", "started:time") in pending_for(rig, frame)


@pytest.mark.parametrize("delay_accept", (False, True))
def test_completion_window_uses_the_report_receipt(make_binding, delay_accept):
    """K25's single commit M fixes end=r; later acceptance/settle cannot change it.

    A changed Frame with end>r is rejected by the K28 entrance test in
    test_fb_belief.py [interval-end], rather than reaching B as a legal Frame.
    """
    rig = make_binding()
    rig.begin()
    rig.measurers[rig.measure_key].stop()
    rig.source.release[0].set()
    rig.wait_returns(1)
    expected_r = 210  # source adds exactly ten to M=200, tick=0
    if delay_accept: rig.clock.set(500)
    frame = rig.saved_pair(rig.calls[0])[1][1]
    rig.until(lambda: len(bindings_for(rig, frame)) == 1)
    assert frame.value["item"]["value"]["measurement_interval"]["end_ns"] == frame.received_ns == expected_r
    assert frame.received_ns <= frame.at_ns
    if delay_accept: assert frame.at_ns >= 500
    before = bindings_for(rig, frame)
    rig.clock.set(600)
    for _ in range(3): rig.round()
    assert bindings_for(rig, frame) == before


@pytest.mark.parametrize("started_ns,ok", ((201, True), (211, False)))
def test_frame_actual_time_not_before_started(make_binding, started_ns, ok):
    """Frame actual=r=210; Started 201 is legal, 211 cannot precede that Frame.

    K25 now makes actual=r, so actual<Started cannot be isolated from the
    earliest-frame-receipt condition. The negative must stay unbound; the paper
    does not specify which of those dependent clock checks reports first.
    """
    rig = make_binding(delay_started=True)
    rig.begin()
    frame = rig.frame()
    assert frame.value["item"]["value"]["actual_time"] == {
        "kind": "clock", "value": {"run": str(rig.clock.run), "time_ns": 210}}
    rig.clock.set(220)
    rig.deliver_started(started_ns)
    rig.until(lambda: bool(bindings_for(rig, frame)) or any(k == "conflict" for k, _ in pending_for(rig, frame)))
    assert len(bindings_for(rig, frame)) == int(ok)
    if not ok:
        assert any(kind == "conflict" for kind, _ in pending_for(rig, frame))
        assert not rig.requests("belief_update")
        assert belief1_status(rig, 0).outcome == "waiting_binding"


def test_undeclared_reading_contract_keeps_measuring_without_binding(make_binding):
    """No declared reading must not be guessed from sampling or a default name."""
    rig = make_binding(reading=None)
    rig.begin()
    frame = rig.frame()
    for _ in range(3): rig.round()
    assert not bindings_for(rig, frame)
    assert ("missing_contract", "reading_contract") in pending_for(rig, frame)
    assert frame.cid in rig.records() and len(rig.calls) == 1
    assert rig.host.halted is None


def test_rebuilding_the_window_does_not_rebind(make_binding):
    """Rebuild/repeated settle keeps the SAME B for the same saved evidence."""
    rig = make_binding()
    rig.begin()
    frame = rig.frame()
    rig.until(lambda: len(bindings_for(rig, frame)) == 1)
    before = bindings_for(rig, frame)
    rig.host.rebuild_window()
    rig.clock.set(300)
    for _ in range(3): rig.round()
    assert bindings_for(rig, frame) == before
    assert len(rig.calls) == 1


def test_redelivered_started_is_one_logical_report(make_binding):
    """Two equivalent Started deliveries remain raw facts; B uses the first one."""
    rig = make_binding()
    rig.begin()
    rig.until(lambda: len(rig.reports("started")) == 1)
    first = rig.reports("started")[0]
    rig.clock.set(205)
    event = replace(rig.original_started, item_slot="start-again")
    rig.started_port.delegate.post(event)
    rig.until(lambda: len(rig.reports("started")) == 2)
    frame = rig.frame()
    rig.until(lambda: len(bindings_for(rig, frame)) == 1)
    assert bindings_for(rig, frame)[0].value["generation"]["started"] == first.cid
    assert len({r.cid for r in rig.reports("started")}) == 2
    assert not any(k == "conflict" for k, _ in pending_for(rig, frame))



def allowed_binding_scene(make_binding, branch, legal, order, *, receipt=False):
    """Only allowed Posts plus the ORIGINAL production acquisition envelopes."""
    rig = make_binding(delay_started=branch == "started", reading=c.FINITE_SEGMENT_PROJECTION)
    rig.begin()
    port = rig.started_port
    reading = rig.original_started.item.reading
    if branch != "started":
        # The three envelopes below do not include the production Started.
        # B needs it first (F-b B2/B3); keep only the target three permuted.
        seen, = execution_for(port.delegate, port.work.desc.work_id).reports
        rig.host.window.accept(fb.Envelope(number=seen.envelope,
            received_ns=seen.received_ns, event=rig.original_started))
        for _ in range(16):
            if rig.reports("started"): break
            rig.host.window.settle()
        started, = rig.reports("started")
        assert started.value == wire(rig.original_started)
        assert execution_for(port.delegate, port.work.desc.work_id).reports[0].point == started.cid
    events, envelopes = [], []
    if branch == "started":
        ns = 212 if receipt else 200
        first = replace(rig.original_started, item_slot="first", item=replace(rig.original_started.item,
            reading=replace(reading, reading=replace(reading.reading, time_ns=ns))))
    elif branch == "coverage_unproved":
        first = fb.SegmentReport(segment=port.work.request, item_slot="same-unproved",
            item=f.CoverageUnproved(route_epoch="route-A", interval=f.MeasurementInterval(
                clock=rig.clock.run, start_ns=205, end_ns=209, closure="(start,end]"),
                missing_contracts=(c.NO_ARRIVAL,), evidence=()))
    elif branch == "route_applied":
        # Paper 2-5-7: this branch names config, not work; SegmentBoundary
        # permits only started/ended. Keep the actual applied route Point.
        first = fb.SegmentReport(segment=port.work.request, item_slot="first",
            item=fb.RouteAppliedItem(config=rig.one(ROUTE).cid, reason="test boundary", evidence=(),
                reading=replace(reading, reading=replace(reading.reading, time_ns=0))))
    else:
        first = fb.SegmentReport(segment=port.work.request, item_slot="first",
            item=fb.SegmentBoundary(kind=branch, work=port.work.desc.work_id, reason="test boundary", evidence=(),
                reading=replace(reading, reading=replace(reading.reading, time_ns=220))))
    second = replace(first, item_slot="second" if branch != "coverage_unproved" else first.item_slot)
    if not legal and not receipt:
        second = replace(second, item=(replace(second.item, missing_contracts=(c.FINITE_SEGMENT_PROJECTION,))
            if branch == "coverage_unproved" else replace(second.item, reading=replace(second.item.reading,
                reading=replace(second.item.reading.reading, time_ns=second.item.reading.reading.time_ns+1)))))
    def post(event, ns):
        rig.clock.set(ns)
        before = {r.envelope for r in execution_for(port.delegate, port.work.desc.work_id).reports}
        port.delegate.post(event)
        seen, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports if r.envelope not in before)
        events.append(event); envelopes.append(fb.Envelope(number=seen.envelope, event=event, received_ns=seen.received_ns))
    if branch == "started":
        post(first, (212 if legal else 211) if receipt else 205)
        post(second, 213 if receipt else 206)
        rig.clock.set(220)
    rig.measurers[rig.measure_key].stop(); rig.source.release[0].set(); rig.wait_returns(1)
    call, = rig.calls
    originals = original_envelopes(rig, call)
    if branch != "started": post(first,230); post(second,231)
    rig.clock.set(250)
    for e in originals[:-1]: rig.host.window.accept(e)
    deliveries = [*envelopes, originals[-1]]
    for index in order: rig.host.window.accept(deliveries[index])
    for _ in range(16): rig.host.window.settle()
    pair = rig.pair(call); assert pair is not None
    frame = pair[1][1]
    raws = []
    for event, envelope in zip(events,envelopes):
        raw, = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(event) and r.received_ns == envelope.received_ns]
        raws.append(raw)
    assert frame.value == wire(originals[-1].event)
    assert len(rig.calls) == len(rig.source.calls) == 1
    return rig, frame, raws


@pytest.mark.parametrize("order", tuple(permutations(range(3))))
def test_representative_is_the_first_accepted_delivery(make_binding, order):
    """The still-public Started logical key retains first-accepted representation.

    Authentic Frame retries cannot create a new envelope anymore (Z55); use
    two equivalent Started deliveries and their actual accept order instead.
    """
    rig, frame, raws = allowed_binding_scene(make_binding,"started",True,order)
    b, = bindings_for(rig,frame)
    first = next(index for index in order if index in (0,1))
    assert b.value["generation"]["started"] == raws[first].cid
    assert raws[0].cid != raws[1].cid


@pytest.mark.parametrize("legal", [False,True])
@pytest.mark.parametrize("order", tuple(permutations(range(3))))
def test_binding_depends_on_the_saved_reports_not_the_accept_order(make_binding, legal, order):
    """Earliest Started receipt applies even if its later redelivery is accepted first.

    Only r of the first delivery changes, 211->212; Started's reading is 212
    and the production Frame finishes at 230. Using only the representative's
    r incorrectly binds the negative. Old forged seq/window cases are refused
    at ingress and separately covered by K28 refusal tests.
    """
    rig, frame, raws = allowed_binding_scene(make_binding,"started",legal,order,receipt=True)
    assert len(bindings_for(rig,frame)) == int(legal)
    if not legal: assert ("conflict","started:time") in pending_for(rig,frame)


@pytest.mark.parametrize("branch", ["started","ended","route_applied","coverage_unproved"])
@pytest.mark.parametrize("legal", [False,True])
@pytest.mark.parametrize("order", tuple(permutations(range(3))))
def test_clash_and_binding_for_every_accept_order(make_binding, branch, legal, order):
    """Retain all open logical report keys with a production Frame and all 3! orders.

    Dropping a raw, checking only the representative, conflating identical
    redelivery with CL-SAME, or globally blocking the independent Frame fails.
    Closed Frame/Claim/Gap/Unavailable collision families have no host path now.
    """
    rig, frame, raws = allowed_binding_scene(make_binding,branch,legal,order)
    for raw in raws:
        actual = {p.reason for p in rig.host.window.status().pending if p.kind == "conflict" and p.target == raw.cid}
        assert actual == (set() if legal else {"report:identity"})
    assert len(bindings_for(rig,frame)) == (0 if branch == "started" and not legal else 1)
    raw_ids = {raw.cid for raw in raws}
    raw_bindings = [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["report"] in raw_ids]
    assert len(raw_bindings) == (1 if branch == "coverage_unproved" and legal else 0)
    if branch == "started" and not legal: assert ("conflict","started:twice") in pending_for(rig,frame)


def test_report_from_a_launch_without_the_ticket_is_not_bound(make_binding):
    """A retained not_started body cannot use the current launch's admission.

    The genuine body is production SourceMeasurer. A stale test body emits only
    an allowed Unproved report; saving it must not give it a B. The genuine
    acquisition remains saved/bound and is never repeated.
    """
    old = []
    def install(rig):
        launch = rig.launcher.launch
        def offered(work_id, body):
            if not old and any(q.value["desc"]["work_id"] == work_id for q in rig.requests("measure_segment")):
                old.append(body); return "not_started"
            return launch(work_id,body)
        rig.launcher.launch = offered
    rig = make_binding(launch_hook=install)
    rig.begin(); frame = rig.frame()
    assert len(old) == 1 and len(bindings_for(rig,frame)) == 1
    original_run = rig.workers.run
    attempts = []
    def stale(work,ctx):
        attempts.append(ctx.enter()); assert attempts[-1] is False
        ctx.post(fb.SegmentReport(segment=work.request,item_slot="unentered-unproved",
            item=f.CoverageUnproved(route_epoch="route-A",interval=f.MeasurementInterval(
                clock=rig.clock.run,start_ns=205,end_ns=209,closure="(start,end]"),
                missing_contracts=(c.NO_ARRIVAL,),evidence=())))
    rig.workers.run = stale
    try: old[0]()
    finally: rig.workers.run = original_run
    rig.until(lambda: any(r.value.get("item_slot") == "unentered-unproved" for r in rig.facts(c.SEGMENT_REPORT)))
    raw, = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value.get("item_slot") == "unentered-unproved"]
    assert not any(b.value["report"] == raw.cid for b in rig.facts(c.SEGMENT_BINDING))
    assert len(bindings_for(rig,frame)) == 1 and len(rig.calls) == 1 and attempts == [False]
