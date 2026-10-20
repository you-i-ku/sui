"""F-b stage 1: specification-owned Clash/B expectations, public entry only.

Sources: specs/関所F_Fb_今の約束.md:327-360 (keys/state function),
1123-1141 (CMP-04..09), 1172-1184 (CL-*), 3283 (frozen rules remain
meaningful), 3402-3414 (B1..B8), plus the task's public reason vocabulary.
No src/sui/_fb_*.py is read, imported directly, patched, or inspected.

All scene deliveries are Posted before ANY scene Accept, all Accepts precede
settle, and every permutation is a separate test. Expectations below are
constants selected by the input scene, never computed from FStatus.
"""

from dataclasses import dataclass, replace
from itertools import combinations, permutations
from threading import Event, Lock, Thread

import pytest

from sui import f, fb
from sui import fb_contracts as c
from test_fb_skeleton import boot, contract, segment_items, source
from test_fb_stage1 import RealRig, accept_and_save, pump_window, wire


IDENTITY = frozenset({("conflict", "report:identity")})
SEQUENCE = frozenset({("conflict", "frame:sample_seq")})
MEASUREMENT = frozenset({("conflict", "frame:measurement")})
NO_REASONS = frozenset()
UNNAMED = ("gap", "measurement_unavailable", "claim", "coverage_unproved")


class DeferredLauncher:
    """Test-owned FLauncher: capture real host callbacks, without claiming entry."""

    def __init__(self):
        self.bodies = []

    def launch(self, work_id, body):
        self.bodies.append((work_id, body))
        return "launched"


class HoldingWorkers:
    """Test-owned FWorkers: take the real ticket, keep each reporting mouth live."""

    def __init__(self, count):
        self.count = count
        self.lock = Lock()
        self.ready, self.release = Event(), Event()
        self.entered = {}
        self.errors = []

    def run(self, work, ctx):
        try:
            assert ctx.enter(), "the fixture's first launch must obtain its ticket"
            with self.lock:
                self.entered[work.request] = (work, ctx)
                if len(self.entered) == self.count:
                    self.ready.set()
            self.release.wait()
        except BaseException as error:
            with self.lock:
                self.errors.append(error)
            self.ready.set()


@dataclass(frozen=True)
class Case:
    family: str
    variant: str = ""
    legal: bool = False
    deliveries: int = 4
    segments: int = 1

    @property
    def name(self):
        return "-".join(filter(None, (self.family, self.variant,
                                     "legal" if self.legal else "violation")))


CASES = [
    Case("boundary", kind, legal, 2)
    for kind in ("started", "ended", "route_applied") for legal in (False, True)
] + [
    Case("boundary_probe", kind, legal, 3 if kind == "started" else 4)
    for kind in ("started", "ended", "route_applied") for legal in (False, True)
] + [
    Case("same_frame", legal=legal, deliveries=5) for legal in (False, True)
] + [
    Case("same_unnamed", branch, legal)
    for branch in UNNAMED for legal in (False, True)
] + [
    Case("unnamed_cross", first + "+" + second, legal)
    for first, second in combinations(UNNAMED, 2) for legal in (False, True)
] + [
    Case("sequence", legal=legal, deliveries=5) for legal in (False, True)
] + [
    Case("sequence_other_epoch", legal=True),
    Case("sequence_overlap"),
] + [
    Case(family, legal=legal, deliveries=5, segments=2)
    for family in ("measurement", "measurement_control") for legal in (False, True)
] + [
    Case("receipt", branch, legal, 3)
    for branch in ("frame", "gap", "measurement_unavailable", "claim")
    for legal in (False, True)
] + [
    Case("started_receipt", branch, legal, 3)
    for branch in ("frame", "gap", "measurement_unavailable", "claim")
    for legal in (False, True)
] + [
    Case("future_unproved", legal=True, deliveries=2),
    Case("route_applied_and_gap", legal=True, deliveries=3),
]


@pytest.fixture
def scene_rig(case):
    """Real stores/clock/registry from existing tests, our workers and launcher.

    Two distinct public routes in ONE Boot deliberately share an identical
    route-A config: the same original Frame can therefore be valid in both k.
    Only route/process/allocation positions differ. No segment is injected.
    """
    rig = RealRig(connect=False)
    launcher = DeferredLauncher()
    rig.workers = HoldingWorkers(case.segments)
    rig.host = fb.FThreadHost(ledger=rig.ledger, clock=rig.clock,
                             workers=rig.workers, registry=rig.registry,
                             launcher=launcher)
    threads = []
    try:
        clock_event = fb.ClockDeclared(declaration=replace(source(), run=rig.clock.run))
        accept_and_save(rig, rig.envelope(100, clock_event, 10),
                        c.CLOCK_NOTICE, 1)  # §6-9 K1
        event = boot(False)
        first = event.declaration.routes[0]
        routes = [first]
        if case.segments == 2:
            routes.append(replace(first, slot="route-2", value=replace(
                first.value, process_slot="sensing-2", allocation=replace(
                    first.value.allocation, slot="sensing-allocation-2"))))
        event = replace(event, declaration=replace(event.declaration, routes=tuple(routes)))
        rig.host.window.accept(rig.envelope(101, event, 11))
        pump_window(rig, lambda: len(rig.facts(c.SEGMENT_REQUESTED)) == case.segments)
        works = sorted(rig.host.window.drain(), key=lambda work: work.desc.process.slot)
        assert len(works) == case.segments
        assert all(isinstance(work, fb.MeasureSegment) for work in works)
        assert len({work.request for work in works}) == case.segments
        rig.set_clock(200)  # both workers take their tickets before any scene Post
        assert rig.host.run_until(lambda _status: len(launcher.bodies) == case.segments,
                                  timeout=3), "public launch callbacks not reached"
        for _work_id, body in launcher.bodies:
            thread = Thread(target=body, daemon=True)
            threads.append(thread)
            thread.start()
        assert rig.workers.ready.wait(3), "worker entry witness not reached"
        assert not rig.workers.errors
        assert len(rig.workers.entered) == case.segments
        rig.clash_works = works
        rig.clash_source = rig.facts(contract("sui.clock.source"))[0].cid
        yield rig
    finally:
        rig.workers.release.set()
        for thread in threads:
            thread.join(3)
        assert not any(thread.is_alive() for thread in threads), "fixture worker did not stop"
        assert not rig.workers.errors


def reading(rig, ns):
    return fb.ReadingClock(source=rig.clash_source,
                           reading=f.ClockReading(run=rig.clock.run, time_ns=ns))


def interval(rig, end=225):
    return f.MeasurementInterval(clock=rig.clock.run, start_ns=215, end_ns=end,
                                 closure="(start,end]")


def frame(rig, *, origin="origin-a", seq=0, epoch="route-A", value=0):
    base = segment_items()["frame"]
    mid = replace(base.measurement_id, origin=replace(base.measurement_id.origin, value=origin),
                  route_epoch=epoch, sample_seq=seq)
    return replace(base, route_epoch=epoch, sample_seq=seq, measurement_id=mid,
                   measurement_interval=interval(rig),
                   actual_time=f.ClockReading(run=rig.clock.run, time_ns=220), value=value,
                   source_cursor=replace(base.source_cursor, value=seq))


def unnamed(rig, branch, **changes):
    item = segment_items()[branch]
    field = "requested_interval" if branch == "measurement_unavailable" else "interval"
    return replace(item, **{field: interval(rig), "evidence": (), **changes})


def boundary(rig, kind, segment=0, ns=None):
    work = rig.clash_works[segment]
    if kind == "route_applied":
        return fb.RouteAppliedItem(config=work.desc.args.route,
                                   reading=reading(rig, 100 if ns is None else ns),
                                   reason="applied", evidence=())
    return fb.SegmentBoundary(kind=kind, work=work.desc.work_id,
                              reading=reading(rig, (210 if kind == "started" else 225)
                                              if ns is None else ns),
                              reason=kind, evidence=())


def scene(rig, case):
    """Return input deliveries and a literal per-logical-report oracle.

    Each paired case changes ONE independent input coordinate. Most pairs
    change one DTO field (reading ns, value, slot, origin, reason/kind/etc., r).
    Frame/MID/cursor sample sequence representations stay consistent except
    in the explicit SAME/SEQ overlap probe inherited from the paper's keys.
    """
    deliveries, expected = [], {}

    def add(group, item, *, segment=0, slot=None, r=None):
        # Receipt times identify the observed deliveries, never their outcome.
        if r is None:
            r = 230 + len(deliveries)
        event = fb.SegmentReport(segment=rig.clash_works[segment].request,
                                 item_slot=slot or group, item=item)
        deliveries.append((group, r, event))

    def expect(group, bound=False, reasons=NO_REASONS):
        expected[group] = (bound, reasons)

    def start(segment=0):
        group = "start-" + str(segment)
        add(group, boundary(rig, "started", segment), segment=segment,
            r=211 + segment)
        expect(group)

    def control():
        add("unaffected", unnamed(rig, "gap"), slot="unaffected")
        expect("unaffected", True)

    family, legal = case.family, case.legal
    if family in ("boundary", "boundary_probe"):
        kind = case.variant
        if family == "boundary_probe" and kind != "started":
            start()
        first = boundary(rig, kind)
        second = first if legal else replace(first, reading=replace(
            first.reading, reading=replace(first.reading.reading,
                                          time_ns=first.reading.reading.time_ns + 1)))
        add("boundary", first, slot="boundary-first")
        add("boundary", second, slot="boundary-redelivery")
        expect("boundary", reasons=NO_REASONS if legal else IDENTITY)
        if family == "boundary_probe":
            add("finite", frame(rig))
            blocked = kind == "started" and not legal
            expect("finite", not blocked,
                   frozenset({("conflict", "started:twice")}) if blocked else NO_REASONS)

    elif family in ("same_frame", "sequence", "sequence_other_epoch", "sequence_overlap"):
        start()
        a = frame(rig)
        if family == "same_frame":
            add("frame", a, slot="frame-first")
            add("frame", a, slot="frame-redelivery")
            add("frame", replace(a, value=0 if legal else 1), slot="frame-second")
            expect("frame", legal, NO_REASONS if legal else IDENTITY)
            control()
        elif family == "sequence":
            # Only MID.origin changes between the violation and legal twin.
            # Making it origin-a makes the entire second Frame a redelivery.
            b = frame(rig, origin="origin-a" if legal else "origin-b")
            add("a", a, slot="a-first")
            add("a", a, slot="a-redelivery")
            add("a" if legal else "b", b, slot="b")
            expect("a", legal, NO_REASONS if legal else SEQUENCE)
            if not legal:
                expect("b", reasons=SEQUENCE)
            control()
        elif family == "sequence_other_epoch":
            add("a", a)
            add("other-epoch", frame(rig, origin="origin-b", epoch="route-z"))
            expect("a", True)
            expect("other-epoch", reasons=frozenset({("conflict", "route:epoch")}))
            control()
        else:
            # a0/a1 share a MID but disagree on seq; a1 and b1 share seq=1.
            # CL-SEQ affects the WHOLE a key and takes priority over CL-SAME.
            add("a", a, slot="a0")
            add("a", replace(a, sample_seq=1), slot="a1")
            add("b", frame(rig, origin="origin-b", seq=1), slot="b1")
            expect("a", reasons=SEQUENCE)
            expect("b", reasons=SEQUENCE)

    elif family in ("same_unnamed", "unnamed_cross"):
        start()
        if family == "same_unnamed":
            branch = case.variant
            a = unnamed(rig, branch)
            changes = {
                "gap": {"reason": "different loss"},
                "measurement_unavailable": {"reason": "different unavailability"},
                "claim": {"kind": "different claim"},
                "coverage_unproved": {"missing_contracts": (c.FINITE_SEGMENT_PROJECTION,)},
            }[branch]
            b = a if legal else replace(a, **changes)
            add("unnamed", a, slot="shared")
            add("unnamed", b, slot="shared")
            expect("unnamed", legal, NO_REASONS if legal else IDENTITY)
        else:
            first, second = case.variant.split("+")
            add("first", unnamed(rig, first), slot="shared")
            add("second" if legal else "first", unnamed(rig, second),
                slot="separate" if legal else "shared")
            expect("first", legal, NO_REASONS if legal else IDENTITY)
            if legal:
                expect("second", True)
        control()

    elif family in ("measurement", "measurement_control"):
        start(0)
        start(1)
        a = frame(rig)
        add("frame-k0", a, slot="frame-first")
        if family == "measurement":
            add("frame-k0", a, slot="frame-redelivery")
        add("frame-k1", replace(a, value=0 if legal else 1), segment=1, slot="frame-other-k")
        for group in ("frame-k0", "frame-k1"):
            expect(group, legal, NO_REASONS if legal else MEASUREMENT)
        if family == "measurement_control":
            control()

    elif family == "receipt":
        start()
        item = frame(rig) if case.variant == "frame" else unnamed(rig, case.variant)
        add("finite", item, r=226 if legal else 224)
        add("finite", item, r=240)
        expect("finite", legal, NO_REASONS if legal else
               frozenset({("conflict", "interval:after_receipt")}))

    elif family == "started_receipt":
        item = boundary(rig, "started", ns=212)
        add("start", item, slot="start-first", r=212 if legal else 211)
        add("start", item, slot="start-redelivery", r=213)
        finite = frame(rig) if case.variant == "frame" else unnamed(rig, case.variant)
        add("finite", finite, r=230)
        expect("start")
        expect("finite", legal, NO_REASONS if legal else
               frozenset({("conflict", "started:time")}))

    elif family == "future_unproved":
        start()
        add("unproved", unnamed(rig, "coverage_unproved", interval=interval(rig, 260)), r=224)
        expect("unproved", True)

    elif family == "route_applied_and_gap":
        start()
        add("applied", boundary(rig, "route_applied"), slot="shared")
        add("gap", unnamed(rig, "gap"), slot="shared")
        expect("applied")
        expect("gap", True)
    else:
        raise AssertionError("unimplemented test scene: " + family)

    assert len(deliveries) == case.deliveries
    assert set(expected) == {group for group, _r, _event in deliveries}
    return deliveries, expected


def deliver_all_then_accept(rig, deliveries, order):
    """Post via entered worker contexts; replay only real, publicly visible envelopes."""
    for _group, ns, event in deliveries:
        rig.set_clock(ns)
        rig.workers.entered[event.segment][1].post(event)
    queued = sorted((receipt for receipt in rig.host.window.status().receipts
                     if receipt.state == "received"), key=lambda receipt: receipt.envelope)
    assert len(queued) == len(deliveries)
    assert [receipt.received_ns for receipt in queued] == [ns for _g, ns, _e in deliveries]
    # FStatus supplies the actual envelope identifiers ONLY, not the oracle.
    rig.set_clock(max(ns for _g, ns, _e in deliveries) + 10)
    for index in order:
        receipt = queued[index]
        rig.host.window.accept(fb.Envelope(number=receipt.envelope,
                                           event=deliveries[index][2],
                                           received_ns=receipt.received_ns))
    for _ in range(3):
        rig.host.window.settle()


def assert_logical_outcomes(rig, deliveries, expected):
    raw = rig.facts(c.SEGMENT_REPORT)
    assert len(raw) == len(deliveries), "every delivery must remain a saved original report"
    bindings = rig.facts(c.SEGMENT_BINDING)
    pending = rig.host.window.status().pending
    observed = {group: (False, set()) for group in expected}
    delivery_reasons = []
    report_cids = set()
    for group, ns, event in deliveries:
        matches = [fact for fact in raw if fact.received_ns == ns and fact.value == wire(event)]
        assert len(matches) == 1, "original delivery missing, duplicated, or rewritten"
        cid = matches[0].cid
        report_cids.add(cid)
        reasons = {(item.kind, item.reason) for item in pending if item.target == cid}
        delivery_reasons.append((group, ns, reasons))
        bound, all_reasons = observed[group]
        observed[group] = (bound or any(b.value["report"] == cid for b in bindings),
                           all_reasons | reasons)
    assert all(b.value["report"] in report_cids for b in bindings)
    actual = {group: (bound, frozenset(reasons)) for group, (bound, reasons) in observed.items()}
    assert actual == expected
    # The task explicitly requires per-delivery reasons for Clash keys.
    # B7's receipt constraint specifies no B for the logical report; it does
    # not specify which redelivery CID carries a timing diagnostic. Its exact
    # per-logical-report oracle above is unchanged by this distinction.
    clash_reasons = (IDENTITY, SEQUENCE, MEASUREMENT,
                     frozenset({("conflict", "started:twice")}))
    for group, ns, reasons in delivery_reasons:
        if expected[group][1] in clash_reasons:
            assert reasons == expected[group][1], (group, ns, reasons, expected[group][1])


@pytest.mark.parametrize(
    "case,order",
    [pytest.param(case, order, id=case.name + "-accept-" + "".join(map(str, order)))
     for case in CASES for order in permutations(range(case.deliveries))],
)
def test_clash_and_binding_for_every_accept_order(case, order, scene_rig):
    deliveries, expected = scene(scene_rig, case)
    deliver_all_then_accept(scene_rig, deliveries, order)
    assert_logical_outcomes(scene_rig, deliveries, expected)
