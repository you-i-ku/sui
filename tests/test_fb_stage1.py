"""FBS0-03 / stage 1, independently specified black-box contrast tests.

These are NOT implemented-product coverage claims. The actual public Ledger,
stores, clock and registry are constructed before FThreadHost is entered.
No private state, model implementation, or FStatus oracle is substituted.

The observer API below belongs to the TEST HARNESS, not to sui. Its factory must
wrap actual public stores; it may not simulate FWindow or invent expected facts.
Timeout is an incomplete observation, not a specified product deadline.
"""

from dataclasses import dataclass, replace, fields, is_dataclass
from threading import Event, Lock, RLock
from collections.abc import Mapping
from enum import Enum
from fractions import Fraction
from hashlib import sha256
from time import monotonic
from typing import Callable

import pytest

from sui import fb, f
from sui import fb_contracts as c
from sui.clock import FakeClock
from sui.ledger import Ledger, MemoryContents, SequentialSalts, CorruptEntry, entry_from_header, decode_record, encode_header, seal
from sui.store import MemoryEntries
from sui.records import Record, Payload, Observed, Prediction, Decided, JobOpened, Producer, StateRef, Role
from sui.ids import SequentialIds, RefKind, Ref
from fb_stage_map import STAGE_MAP
from fb_targets import TARGETS
from test_fb_skeleton import (ContractGap, PAPER, boot, contract, gap, reading,
                              segment_items, point, source, work_outcomes, test_registry,
                              WitnessLauncher)


def test_need_structural_contract_gap():
    """Stage-1 red: declaration construction is covered by stage-0 CG-METHOD.

    The public contract schedules F-a structural NEED_INPUT/QUANTITY_VALUE acceptance
    for stage 1; do not substitute a direct implementation call or a skip.
    """
    registry = test_registry()
    need = next(d for d in registry.declarations if d.ref == contract("test.need"))
    assert (need.kind, need.input_contract, need.output_contract) == ("method", c.NEED_INPUT, c.QUANTITY_VALUE)
    # 段 1 で接続した (CG-NEED-STRUCTURAL を閉じる): F-a の能力の呼出しの規約が NEED_INPUT と
    # QUANTITY_VALUE を構造検査する。合法な入力は通り、欄の欠けた入力は shape で落ちる。
    legal_input = {"work": {"work_id": "w"}, "scope": {"quantity_contract": {"name": "sui.fb.seats", "version": "1"},
                                                       "need": {"contract": {"name": "test.need", "version": "1"}, "args": {}}}}
    out = f._call_capability("method", contract("test.need"), args={}, input=legal_input, registry=registry)
    assert out == {"contract": {"name": c.SEATS.name, "version": c.SEATS.version}, "value": 1}
    with pytest.raises(f.FInputError):
        f._call_capability("method", contract("test.need"), args={}, input={"work": {}}, registry=registry)


class IncompleteObservation(AssertionError):
    """The harness did not reach its required point; never product Failure."""


class TestConnectionGap(AssertionError):
    """An uncovered test obligation, distinct from a missing production API."""
    __test__ = False


@dataclass(frozen=True)
class SavedFact:
    """Projection decoded from actual C/E by the test's independent observer."""
    cid: str
    record_id: object
    contract: object
    received_ns: int | None
    at_ns: int
    parents: frozenset[str]
    value: object


class WitnessWorkers:
    """EW is recorded here at actual entry/post/return, never from FStatus."""

    def __init__(self):
        self.lock = Lock()
        self.calls = []
        self.entries = []
        self.reports = []
        self.stops = []
        self.release = Event()
        self.action: Callable | None = None
        self.hold = False

    def run(self, work, ctx):
        with self.lock:
            self.calls.append(work)
        if not ctx.enter():
            return
        with self.lock:
            self.entries.append(work)
        try:
            if self.action is not None:
                self.action(work, ctx, self)
            if self.hold and not self.release.wait(5):
                raise IncompleteObservation("worker gate not released; harness incomplete")
        finally:
            with self.lock:
                self.stops.append(work.desc.work_id)

    def report(self, ctx, event):
        with self.lock:
            self.reports.append(event)
        ctx.post(event)


def wire(value):
    """Independent value encoding from F-a V-01/V-02 and F-b §2-5.

    No production serializer or status is used to generate expected payloads.
    Tagged unions are assembled at their explicit envelope boundary.
    """
    if isinstance(value, Ref):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Fraction):
        return [value.numerator, value.denominator]
    if isinstance(value, fb.SlotValue):
        return {"slot": value.slot, "declaration": {"contract": wire(value.contract), "value": wire(value.value)}}
    if isinstance(value, fb.FixedView):
        return {"boundary": wire(value.boundary), "environment": {
            "reader_view_key": value.reader_view_key, "registry_key": value.registry_key}}
    if isinstance(value, fb.ReadingClock):
        return reading_wire(value)
    if isinstance(value, fb.GenerationPair):
        return {"started": reading_wire(value.started), "finished": reading_wire(value.finished)}
    if isinstance(value, fb.FailureInfo):
        return {"failure_kind": value.failure_kind, "content": wire(value.content),
                "readings": [reading_wire(r) for r in value.readings], "basis": wire(value.basis)}
    if isinstance(value, fb.SegmentReport):
        return {"segment": value.segment, "item_slot": value.item_slot, "item": segment_wire(value.item)}
    if isinstance(value, fb.SegmentArgs):
        # 紙 F-b :2214「新しい和型は kind/value」、Z34 (c) SEGMENT-INTERVAL: 有限 finite / 継続 ongoing
        branch = "ongoing" if isinstance(value.requested, fb.Ongoing) else "finite"
        return {"route": value.route, "requested": {"kind": branch, "value": wire(value.requested)},
                "start_reason": value.start_reason}
    if isinstance(value, f.MeasurementFrame):
        return {"route_epoch": value.route_epoch, "sample_seq": value.sample_seq,
            "measurement_id": wire(value.measurement_id), "measurement_interval": wire(value.measurement_interval),
            "actual_time": {"kind": "unavailable" if isinstance(value.actual_time, f.Unavailable) else "clock",
                            "value": wire(value.actual_time)},
            "value": {"kind": "unavailable" if isinstance(value.value, f.Unavailable) else "value",
                      "value": wire(value.value)},
            "quality": wire(value.quality), "gap": wire(value.gap), "source_cursor": wire(value.source_cursor)}
    for cls, tag, field in ((fb.WorkOutputs, "outputs", "outputs"), (fb.WorkFailure, "failure", "failure"),
            (fb.WorkUnknown, "unknown", "unknown"), (fb.DrawValue, "value", "value"),
            (fb.DrawFailure, "failure", "failure"), (fb.DrawUnknown, "unknown", "unknown")):
        if isinstance(value, cls):
            return {"kind": tag, "value": wire(getattr(value, field))}
    if isinstance(value, fb.WorkFinished):
        return {"work": value.work, "started": reading_wire(value.started), "finished": reading_wire(value.finished),
                "outcome": wire(value.outcome)}
    if is_dataclass(value):
        return {field.name: wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, bytes)):
        return [wire(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # F-b §2-5: 集合は正準 JSON の bytes の順 (要素が dict でも並べられる)
        import json
        return sorted((wire(item) for item in value), key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return value


def reading_wire(value):
    if isinstance(value, f.Unavailable):
        return {"kind": "unavailable", "value": {"reason": value.reason, "basis": wire(value.basis)}}
    assert isinstance(value, fb.ReadingClock)
    return {"kind": "clock", "value": {"source": value.source, "reading": wire(value.reading)}}


def segment_wire(value):
    if isinstance(value, fb.SegmentBoundary):
        tag = value.kind
        body = {"work": value.work, "reading": reading_wire(value.reading),
                "reason": value.reason, "evidence": wire(value.evidence)}
    elif isinstance(value, fb.RouteAppliedItem):
        tag = "route_applied"
        body = {"config": value.config, "reading": reading_wire(value.reading),
                "reason": value.reason, "evidence": wire(value.evidence)}
    else:
        tag = {f.MeasurementFrame: "frame", f.Gap: "gap", f.MeasurementUnavailable: "measurement_unavailable",
               f.CoverageClaim: "claim", f.CoverageUnproved: "coverage_unproved"}[type(value)]
        body = wire(value)
    return {"kind": tag, "value": body}


def test_expected_wire_matches_paper_literals():
    """F-a:27-29, F-b:2059,2110,2194,2206,2220-2227. Test-side encoder QA."""
    assert wire(Fraction(1, 1000)) == [1, 1000]
    assert wire(fb.SlotValue(slot="s", contract=c.SEATS, value=2)) == {
        "slot": "s", "declaration": {"contract": {"name": "sui.fb.seats", "version": "1"}, "value": 2}}
    assert wire(fb.FixedView(boundary=frozenset(), reader_view_key="v", registry_key=None)) == {
        "boundary": [], "environment": {"reader_view_key": "v", "registry_key": None}}
    unavailable = f.Unavailable(reason="not measured", basis=())
    assert reading_wire(unavailable) == {"kind": "unavailable", "value": {"reason": "not measured", "basis": []}}
    assert wire(fb.WorkUnknown(unknown=fb.UnknownInfo(reason="lost", basis=()))) == {
        "kind": "unknown", "value": {"reason": "lost", "basis": []}}
    item = fb.SegmentBoundary(kind="ended", work="w", reading=unavailable, reason="end", evidence=())
    assert segment_wire(item) == {"kind": "ended", "value": {"work": "w", "reading": {
        "kind": "unavailable", "value": {"reason": "not measured", "basis": []}}, "reason": "end", "evidence": []}}
    frame = wire(segment_items()["frame"])
    assert frame["actual_time"]["kind"] == "clock" and frame["value"] == {"kind": "value", "value": 0}
    assert frame["gap"] is None


class TestClock:
    """Serialize the public single-thread FakeClock; reversal is a fault input."""
    __test__ = False
    def __init__(self):
        self.lock = RLock()
        self.inner = FakeClock(run=Ref(kind=RefKind.RUN, value="fb-stage1"), mono_ns=100)
    @property
    def run(self):
        return self.inner.run
    @property
    def run_index(self):
        return self.inner.run_index
    def now(self):
        with self.lock:
            return self.inner.now()
    def mono_ns(self):
        with self.lock:
            return self.inner.mono_ns()
    def set(self, ns):
        with self.lock:
            delta = ns - self.inner.mono_ns()
            if delta >= 0:
                self.inner.advance(delta)
            else:
                # Deliberate broken-clock test, not legal clock advancement.
                self.inner = FakeClock(run=self.run, run_index=self.run_index, mono_ns=ns)


class StorageFaults:
    def __init__(self):
        self.armed = None
        self.observed = []
    def at(self, boundary):
        if boundary == self.armed:
            self.armed = None
            self.observed.append(boundary)
            raise OSError("injected test store fault: " + boundary)


class ObservedContents:
    writable = True
    def __init__(self, store, faults):
        self.store, self.faults = store, faults
    def put(self, value_seal, salt, content):
        self.faults.at("before_body")
        self.store.put(value_seal, salt, content)
        self.faults.at("after_body_commit")
    def get(self, value_seal):
        return self.store.get(value_seal)
    def seals(self):
        return self.store.seals()
    def discard(self, value_seal):
        return self.store.discard(value_seal)


class ObservedEntries:
    writable = True
    def __init__(self, store, faults):
        self.store, self.faults = store, faults
    def add(self, cid, header):
        self.store.add(cid, header)
        self.faults.at("after_entry_commit")
    def load(self):
        return self.store.load()


class ObservedLedger(Ledger):
    """Observe only public prepare/write calls, never inspect ledger internals."""
    def __init__(self, *, contents, entries, faults):
        self.preparations = []
        self.faults = faults
        super().__init__(salts=SequentialSalts(), contents=contents, entries=entries)
    def prepare(self, record, parents):
        result = super().prepare(record, parents)
        self.preparations.append(result)
        return result
    def write(self, prepared):
        name = prepared.record.body.contract.name
        phase = "origin" if name == "sui.f.knowledge_origin" else "qgen" if name == c.CANDIDATE_REQUEST.name else None
        if phase:
            self.faults.at("before_" + phase)
        result = super().write(prepared)
        if phase:
            self.faults.at("after_" + phase)
        return result


class RealRig:
    """Test adapters over real public stores; no FWindow state machine here."""
    def __init__(self, *, initial=False, connect=True, launcher=None):
        self.faults = StorageFaults()
        self.contents = ObservedContents(MemoryContents(), self.faults)
        self.entry_store = ObservedEntries(MemoryEntries(), self.faults)
        self.ledger = ObservedLedger(contents=self.contents, entries=self.entry_store, faults=self.faults)
        self.clock, self.ids = TestClock(), SequentialIds("fb-test")
        self.workers, self.registry = WitnessWorkers(), test_registry()
        self.prepare_observations = self.ledger.preparations
        self.fault_observations = self.faults.observed
        self.model_point = None
        self.boot_input = None
        if initial:
            # Stage 1 checks declaration/Point ownership. No mathematical claim is
            # made by this explicit test generator's opaque model document.
            record = self.record(Prediction(target="test-generator-input", about=(), basis=(),
                content=Payload.json({"document": {"contract": {"name": "test.model", "version": "1"},
                    "states": ["one"], "initial": ["1"]}}), contract=contract("sui.f.model_source")),
                RefKind.PREDICTION, Role.MODEL)
            self.model_point = self.ledger.append(record, ()).cid
        if connect:
            self.host = fb.FThreadHost(ledger=self.ledger, clock=self.clock, workers=self.workers,
                                      registry=self.registry, launcher=launcher)

    def record(self, body, kind=RefKind.OBSERVATION, role=Role.MEMBRANE):
        return Record(id=self.ids.new(kind), at=self.clock.now(), writer=role,
            producer=Producer(component="fb-test", code_version="2", state=None), body=body, schema=3)

    def envelope(self, number, event, r):
        return fb.Envelope(number=number, event=event, received_ns=r)

    def storage_snapshot(self):
        return (tuple(sorted(self.entry_store.load())), tuple((key, self.contents.get(key)) for key in sorted(self.contents.seals())))

    def raw_contents(self):
        return tuple(self.contents.get(key)[1] for key in sorted(self.contents.seals()))

    def read_stored(self, cid):
        header = dict(self.entry_store.load())[cid]
        # The paper requires the hash binding. Do not make the optional textual
        # algorithm prefix a new acceptance rule for the stored-point observer.
        assert sha256(header).hexdigest() == cid.removeprefix("sha256:")
        entry = entry_from_header(cid, header)
        salt, payload = self.contents.get(entry.seal)
        assert seal(payload, salt) == entry.seal
        record = decode_record(header, payload)
        assert encode_header(record, entry.seal, entry.parents) == header
        return header, salt, record

    def facts(self, wanted):
        result = []
        for cid, _header in self.entry_store.load():
            header, _salt, record = self.read_stored(cid)
            if record.body.contract == wanted:
                result.append(SavedFact(cid=cid, record_id=record.id, contract=wanted,
                    received_ns=getattr(record.body, "received_ns", None), at_ns=record.at.mono_ns,
                    parents=entry_from_header(cid, header).parents, value=record.body.content.as_json()))
        return result

    def fail_next(self, boundary):
        self.faults.armed = boundary
    def recover(self):
        self.faults.armed = None
    def set_clock(self, ns):
        self.clock.set(ns)
    def close(self):
        self.workers.release.set()
    def probe_record(self):
        return self.record(Observed(route="test", content=Payload.json({"probe": 1}), contract=contract("test.probe"),
            caused_by=None, source_id=None, source_time_ns=None, received_ns=30)), ()

    def install_legal_boot(self, *, initial):
        event = boot(initial)
        if initial:
            event = replace(event, declaration=replace(event.declaration, initial=replace(event.declaration.initial,
                value=replace(event.declaration.initial.value, model=self.model_point))))
        self.boot_input = event
        clock_event = fb.ClockDeclared(declaration=replace(source(), run=self.clock.run))
        accept_and_save(self, self.envelope(100, clock_event, 10), c.CLOCK_NOTICE, 1)  # §6-9 K1
        self.host.window.accept(self.envelope(101, event, 11))
        wanted = c.CANDIDATE_REQUEST if initial else c.SEGMENT_REQUESTED
        pump_window(self, lambda: len(self.facts(wanted)) == 1)

    def actual_reading(self):
        return fb.ReadingClock(source=self.facts(contract("sui.clock.source"))[0].cid,
            reading=f.ClockReading(run=self.clock.run, time_ns=self.clock.mono_ns()))
    def declared_need(self, desc):
        return fb.QuantityValue(contract=c.SEATS, value=1)  # explicit DeclaredNeed fixture

    def assert_initial_slots_saved_from_original_declaration(self):
        assert self.facts(c.BOOT_DECLARATION)[0].value == wire(self.boot_input.declaration)
        assert len(self.facts(contract("sui.s4.boot"))) == 1
        origin = self.facts(contract("sui.f.knowledge_origin"))
        qgen = self.facts(c.CANDIDATE_REQUEST)
        assert len(origin) == len(qgen) == 1
        assert origin[0].value == {"model": self.model_point}
        assert qgen[0].value["desc"]["reader"] == origin[0].cid

    def report_matching_ended(self, work, ctx, witness):
        witness.report(ctx, fb.SegmentReport(segment=work.request, item_slot="end", item=fb.SegmentBoundary(
            kind="ended", work=work.desc.work_id, reading=self.actual_reading(), reason="test end", evidence=())))

    def report_two_actual_intervals(self, work, ctx, witness):
        for index in range(2):
            witness.report(ctx, fb.SegmentReport(segment=work.request, item_slot=f"test-unavailable-{index}",
                item=f.MeasurementUnavailable(route_epoch=self.boot_input.declaration.routes[0].value.config.route_epoch,
                    # v0.25 §6-5 G1: 要求は続けて測る枝でもよい。報告は 1 つずつ有限の区間 (要求の時計で)
                    requested_interval=f.MeasurementInterval(clock=work.desc.args.requested.clock,
                        start_ns=index * 10, end_ns=(index + 1) * 10, closure="(start,end]"),
                    reason="test sensor unavailable", evidence=())))


def make_rig(*, initial=False, launcher=None):
    return RealRig(initial=initial, launcher=launcher)


@pytest.fixture
def rig():
    result = make_rig()
    try:
        yield result
    finally:
        result.workers.release.set()
        result.close()


@pytest.fixture
def storage_rig():
    """Ledger requirements do not depend on an implemented FThreadHost."""
    result = RealRig(connect=False)
    try:
        yield result
    finally:
        result.close()


def received(data=b"\x00\xff", claims=None):
    return fb.Received(route_epoch="unknown-route", media_type="application/octet-stream",
                       data=data, claims={"sender_id": "same"} if claims is None else claims)


def pump_window(rig, reached):
    """Do not start workers; legal comparison for 'all saved, Wg unstarted'."""
    deadline = monotonic() + 2
    while not reached():
        rig.host.window.settle()
        if monotonic() >= deadline:
            raise IncompleteObservation("required saved point not reached; no timing guarantee inferred")


def run_until_witness(rig, reached):
    done = rig.host.run_until(lambda _status: reached(), timeout=2)
    if not done or not reached():
        raise IncompleteObservation("public run_until did not reach independent witness")


def accept_and_save(rig, envelope, contract_ref, count):
    assert rig.host.window.accept(envelope) is None
    pump_window(rig, lambda: len(rig.facts(contract_ref)) == count)
    return rig.facts(contract_ref)


def reach_injected_storage_fault(rig, call):
    """Observe the injected fault, without inventing settle's exception policy."""
    before = len(rig.fault_observations)
    try:
        call()
    except OSError:
        pass  # the harness injection may be surfaced or retained for retry
    assert len(rig.fault_observations) == before + 1


def assert_host_fault(call):
    try:
        call()
    except NotImplementedError:
        raise
    except fb.FbInputError:
        pytest.fail("host fault was incorrectly classified as input shape")
    except (TypeError, AttributeError, NameError, AssertionError, OSError):
        raise  # signature/test-connection failures must never count as legal host rejection
    except Exception:
        return
    pytest.fail("changed envelope / reversed host clock was accepted")


def test_accept_is_custody_not_storage(rig):
    """B:470-475 / B1: forbid writes during accept; settle is the legal contrast."""
    before = rig.storage_snapshot()
    envelope = rig.envelope(1, received(), 30)
    assert rig.host.window.accept(envelope) is None
    assert rig.storage_snapshot() == before
    records = accept_and_save(rig, envelope, c.RECEIVED, 1)
    assert records[0].received_ns == 30
    assert records[0].at_ns >= 30


@pytest.mark.parametrize("mutation", ("data", "media_type", "route_epoch", "claims"))
def test_bad_outer_shape_and_nearest_legal_raw_payload(rig, mutation):
    """B:471-473. Unknown semantics are legal; a wrong outer type is not."""
    bad_value = {"data": "not-bytes", "media_type": 3, "route_epoch": 3, "claims": object()}[mutation]
    bad = replace(received(), **{mutation: bad_value})
    before = rig.storage_snapshot()
    with pytest.raises(fb.FbInputError) as caught:
        rig.host.window.accept(rig.envelope(1, bad, 30))
    assert caught.value.reason == "shape"
    assert caught.value.field.startswith("/")
    assert rig.storage_snapshot() == before
    # No numeric observation is inferred from this otherwise valid unknown input.
    records = accept_and_save(rig, rig.envelope(2, received(), 31), c.RECEIVED, 1)
    assert records[0].value["data"] == [0, 255]
    assert not rig.facts(c.SEGMENT_BINDING)


@pytest.mark.parametrize("changed", ("data", "media_type", "route_epoch", "claims", "received_ns", "event_type"))
def test_same_number_compares_all_content_and_r(rig, changed):
    """B:332. Same envelope retry succeeds; changing one field is a host fault."""
    original = rig.envelope(1, received(), 30)
    records = accept_and_save(rig, original, c.RECEIVED, 1)
    saved = rig.storage_snapshot()
    assert rig.host.window.accept(original) is None
    assert rig.storage_snapshot() == saved
    event = replace(received(), **{changed: {
        "data": b"changed", "media_type": "text/unknown", "route_epoch": "changed-route", "claims": {"changed": True}
    }[changed]}) if changed in ("data", "media_type", "route_epoch", "claims") else (
        fb.ClockDeclared(declaration=source()) if changed == "event_type" else received())
    bad = rig.envelope(1, event, 31 if changed == "received_ns" else 30)
    assert_host_fault(lambda: rig.host.window.accept(bad))
    assert rig.facts(c.RECEIVED) == records


def test_distinct_envelopes_are_distinct_receipts(rig):
    """B:179,332. Same sender ID/bytes/r is not reception identity."""
    first = rig.envelope(1, received(), 30)
    second = rig.envelope(2, received(), 30)
    accept_and_save(rig, first, c.RECEIVED, 1)
    rig.host.window.accept(first)  # nearest legal dedup: same envelope
    records = accept_and_save(rig, second, c.RECEIVED, 2)
    assert len({r.record_id for r in records}) == 2
    assert len({r.cid for r in records}) == 2
    assert [r.received_ns for r in records] == [30, 30]


def test_receive_clock_is_not_replaced_by_save_clock(rig):
    """B:474,2067-2069: delayed save preserves r; r>s is a separate host fault."""
    rig.set_clock(40)
    envelope = rig.envelope(1, received(), 30)
    rig.host.window.accept(envelope)
    rig.set_clock(1000)
    pump_window(rig, lambda: len(rig.facts(c.RECEIVED)) == 1)
    assert rig.facts(c.RECEIVED)[0].received_ns == 30
    rig.set_clock(20)
    assert_host_fault(lambda: rig.host.window.accept(rig.envelope(2, received(), 30)))


@pytest.mark.parametrize("boundary", ("before_body", "after_body_commit", "after_entry_commit"))
def test_write_retry_and_rebuild_keep_identical_preparation(rig, boundary):
    """B:312-315,3253: only the fault point changes, not record/parents/salt/CID."""
    envelope = rig.envelope(1, received(), 30)
    rig.host.window.accept(envelope)
    rig.fail_next(boundary)
    reach_injected_storage_fault(rig, rig.host.window.settle)
    prepared_before = tuple(rig.prepare_observations)
    assert prepared_before
    rig.host.rebuild_window()
    rig.recover()
    records = accept_and_save(rig, envelope, c.RECEIVED, 1)
    assert tuple(rig.prepare_observations) == prepared_before
    assert records[0].cid == prepared_before[0].cid
    assert records[0].received_ns == 30


def test_ledger_prepare_is_write_free_and_write_is_idempotent(storage_rig):
    """B:475,3253. Preparation is not save; one actual write is the legal completion."""
    rig = storage_rig
    record, parents = rig.probe_record()
    before = rig.storage_snapshot()
    prepared = rig.ledger.prepare(record, parents)
    assert rig.storage_snapshot() == before
    assert prepared.record == record and prepared.parents == frozenset(parents)
    first = rig.ledger.write(prepared)
    after = rig.storage_snapshot()
    second = rig.ledger.write(prepared)
    assert first == second
    assert rig.storage_snapshot() == after
    assert rig.read_stored(prepared.cid) == (prepared.header, prepared.salt, record)


@pytest.mark.parametrize("field", ("record", "parents", "salt", "header", "cid"))
def test_ledger_rejects_one_changed_prepared_component(storage_rig, field):
    """B:315,475,3253; Ledger.write doc:353-356: CorruptEntry, not any host error."""
    rig = storage_rig
    record, parents = rig.probe_record()
    prepared = rig.ledger.prepare(record, parents)
    values = dict(record=replace(record, producer=replace(record.producer, code_version="changed")),
                  parents=frozenset({point("other-parent")}), salt=prepared.salt + b"!",
                  header=prepared.header + b"!", cid=point("wrong-cid"))
    altered = replace(prepared, **{field: values[field]})
    before = rig.storage_snapshot()
    with pytest.raises(CorruptEntry):
        rig.ledger.write(altered)
    assert rig.storage_snapshot() == before
    rig.ledger.write(prepared)
    after = rig.storage_snapshot()
    with pytest.raises(CorruptEntry):
        rig.ledger.write(altered)
    assert rig.storage_snapshot() == after
    rig.ledger.write(prepared)
    assert rig.storage_snapshot() == after


@pytest.mark.parametrize("operation", ("accept", "settle", "status", "drain"))
def test_rebuild_invalidates_old_window_without_new_boot(rig, operation):
    """B:1935. Old handle fails; new handle continues same custody and no new receive."""
    envelope = rig.envelope(1, received(), 30)
    rig.host.window.accept(envelope)
    old = rig.host.window
    before = rig.storage_snapshot()
    new = rig.host.rebuild_window()
    assert new is rig.host.window and new is not old
    assert rig.storage_snapshot() == before
    with pytest.raises(RuntimeError) as caught:
        getattr(old, operation)(envelope) if operation == "accept" else getattr(old, operation)()
    if isinstance(caught.value, NotImplementedError):
        raise caught.value
    assert not isinstance(caught.value, fb.FbInputError)
    accept_and_save(rig, envelope, c.RECEIVED, 1)
    assert not rig.facts(contract("sui.s4.boot"))


def test_status_and_drain_do_not_consume_work_or_write(rig):
    """B:295,1929: legal repeated read; consuming a row or changing C/E is a violation."""
    rig.install_legal_boot(initial=False)
    before = rig.storage_snapshot()
    first = rig.host.window.drain()
    assert any(isinstance(w, fb.MeasureSegment) for w in first)
    for _ in range(2):
        rig.host.window.status()
        assert rig.host.window.drain() == first
    assert rig.storage_snapshot() == before
    assert rig.workers.entries == []


def test_initial_none_continues_measuring_receiving_and_saving(rig):
    """B:263,3239: two report intervals and independent receive, not merely absence of Compute."""
    rig.install_legal_boot(initial=False)
    rig.workers.action = rig.report_two_actual_intervals
    rig.host.post(received())
    run_until_witness(rig, lambda: len(rig.facts(c.SEGMENT_REPORT)) >= 2 and len(rig.facts(c.RECEIVED)) == 1)
    assert rig.workers.entries
    assert all(isinstance(w, fb.MeasureSegment) for w in rig.workers.entries)
    assert not rig.facts(c.CANDIDATE_REQUEST)
    assert not rig.facts(c.EVALUATION_REQUESTED)
    assert not rig.facts(c.SELECTION)


def test_initial_plan_saved_with_origin_qgen_and_unstarted_wg():
    """B:3239: Wg row alone is insufficient; all initial records saved is legal without entry."""
    rig = make_rig(initial=True)
    try:
        rig.install_legal_boot(initial=True)
        origins = rig.facts(contract("sui.f.knowledge_origin"))
        qgen = rig.facts(c.CANDIDATE_REQUEST)
        assert len(origins) == len(qgen) == 1
        assert rig.model_point == origins[0].value["model"]
        assert qgen[0].value["desc"]["reader"] == origins[0].cid
        work = [w for w in rig.host.window.drain() if w.desc.purpose == "candidate_generation"]
        assert len(work) == 1 and work[0].request == qgen[0].cid
        assert rig.workers.entries == []
        rig.assert_initial_slots_saved_from_original_declaration()
    finally:
        rig.workers.release.set()
        rig.close()


@pytest.mark.parametrize("boundary", ("before_origin", "after_origin", "before_qgen", "after_qgen"))
def test_partial_initial_plan_is_not_complete_and_recovers_same_plan(boundary):
    """B:3239: compare incomplete Qgen with the same fully saved, still unstarted plan."""
    rig = make_rig(initial=True)
    try:
        rig.fail_next(boundary)
        reach_injected_storage_fault(rig, lambda: rig.install_legal_boot(initial=True))
        original_preparations = tuple(rig.prepare_observations)
        rig.host.rebuild_window()
        rig.recover()
        pump_window(rig, lambda: len(rig.facts(c.CANDIDATE_REQUEST)) == 1)
        assert tuple(rig.prepare_observations)[:len(original_preparations)] == original_preparations
        rig.assert_initial_slots_saved_from_original_declaration()
        assert len([w for w in rig.host.window.drain() if w.desc.purpose == "candidate_generation"]) == 1
        assert rig.workers.entries == []
    finally:
        rig.workers.release.set()
        rig.close()


@pytest.mark.parametrize("branch", tuple(segment_items()))
def test_all_segment_raw_reports_preserve_shape_without_certifying_unknown_request(rig, branch):
    """B:471,2216-2235: unknown claimed Point legal raw; never forge a successful binding."""
    event = fb.SegmentReport(segment=point("unknown-request"), item_slot="fixed", item=segment_items()[branch])
    accept_and_save(rig, rig.envelope(1, event, 30), c.SEGMENT_REPORT, 1)
    assert not rig.facts(c.SEGMENT_BINDING)
    # Exact retransmission in a new envelope retains two raw receipts.
    records = accept_and_save(rig, rig.envelope(2, event, 31), c.SEGMENT_REPORT, 2)
    assert records[0].value == records[1].value
    assert records[0].cid != records[1].cid


def test_ended_and_actual_worker_stop_are_different(rig):
    """B:2221,3239: report Ended while worker still held, then independently let it return."""
    rig.install_legal_boot(initial=False)
    rig.workers.hold = True

    def ended_then_wait(work, ctx, witness):
        witness.report(ctx, fb.SegmentReport(segment=work.request, item_slot="end",
            item=fb.SegmentBoundary(kind="ended", work=work.desc.work_id,
                reading=rig.actual_reading(), reason="end", evidence=())))

    rig.workers.action = ended_then_wait
    try:
        run_until_witness(rig, lambda: len(rig.workers.reports) == 1 and bool(rig.facts(c.SEGMENT_REPORT)))
        assert rig.workers.entries and rig.workers.stops == []
        wid = rig.workers.entries[0].desc.work_id
        displayed = next(w for w in rig.host.window.status().works if w.work_id == wid)
        assert not displayed.stop_confirmed
        assert displayed.held == rig.declared_need(rig.workers.entries[0].desc)
        rig.host.post(received())
        run_until_witness(rig, lambda: len(rig.facts(c.RECEIVED)) == 1)
        assert rig.workers.stops == []
        rig.workers.release.set()
        run_until_witness(rig, lambda: wid in rig.workers.stops)
        # Drive the public loop to its stop-observation point, but do not use it as oracle.
        rig.host.run_until(lambda s: any(w.work_id == wid and w.stop_confirmed for w in s.works), timeout=2)
        displayed = next(w for w in rig.host.window.status().works if w.work_id == wid)
        assert displayed.stop_confirmed
        assert displayed.held is None or displayed.held.value == 0
        assert sum(w.desc.work_id == wid for w in rig.workers.entries) == 1
    finally:
        rig.workers.release.set()


def test_workfinished_is_not_the_end_of_measuresegment(rig):
    """B:3239: wrong entry is raw only; the nearest legal end is I-2 Ended."""
    rig.install_legal_boot(initial=False)
    work = next(w for w in rig.host.window.drain() if isinstance(w, fb.MeasureSegment))
    wrong = fb.WorkFinished(work=work.desc.work_id, started=reading(), finished=reading(),
                            outcome=work_outcomes()["unknown"])
    accept_and_save(rig, rig.envelope(20, wrong, 40), c.WORK_REPORT, 1)
    assert not rig.facts(c.WORK_TERMINAL)
    assert not next(s for s in rig.host.window.status().segments if s.segment == work.request).ended
    # A matching worker must deliver Ended through ctx.post; provenance is not fabricated.
    rig.workers.action = rig.report_matching_ended
    run_until_witness(rig, lambda: bool(rig.facts(c.SEGMENT_REPORT)))


def test_real_store_observer_roundtrip_without_host():
    """Validate the independent observer on actual append, not an FWindow model."""
    rig = RealRig(connect=False)
    record, parents = rig.probe_record()
    before = rig.storage_snapshot()
    entry = rig.ledger.append(record, parents)
    assert rig.storage_snapshot() != before
    assert rig.read_stored(entry.cid)[2] == record
    assert rig.facts(contract("test.probe"))[0].value == {"probe": 1}


@pytest.mark.parametrize("event_kind", ("received", "clock", "boot"))
def test_raw_event_entire_payload_and_storage_envelope(rig, event_kind):
    """B:2063-2080,2317-2320: entire source value, not status-derived expected data."""
    event = received() if event_kind == "received" else fb.ClockDeclared(declaration=source()) if event_kind == "clock" else boot()
    target = c.RECEIVED if event_kind == "received" else c.CLOCK_NOTICE if event_kind == "clock" else c.BOOT_DECLARATION
    original = wire(event if event_kind == "received" else event.declaration)
    first = accept_and_save(rig, rig.envelope(1, event, 30), target, 1)[0]
    assert first.value == original and first.parents == frozenset()
    header, _salt, record = rig.read_stored(first.cid)
    assert record.schema == 3 and record.writer == Role.MEMBRANE and isinstance(record.body, Observed)
    assert record.body.received_ns == 30 and record.at.run == rig.clock.run
    assert record.at.mono_ns >= 30 and isinstance(record.at.wall_ns, int)
    assert isinstance(record.producer.component, str) and record.producer.component
    # A different receipt is legal even with the same sender claims and data.
    # facts() は CID の順で受信の順ではない (CID の順を仮定すると半分の確率で落ちていた)
    second = next(fact for fact in accept_and_save(rig, rig.envelope(2, event, 31), target, 2)
                  if fact.cid != first.cid)
    assert second.value == original and second.record_id != first.record_id
    assert second.cid != first.cid


def test_boot_two_slots_are_not_initial_plan_completion(rig):
    """B:476,1934,3239: Boot's two raw slots are necessary but not Qgen completion."""
    event = boot(initial=True)  # unknown model is legal raw, insufficient for use
    rig.host.window.accept(rig.envelope(1, event, 30))
    pump_window(rig, lambda: bool(rig.facts(c.BOOT_DECLARATION)) and bool(rig.facts(contract("sui.s4.boot"))))
    assert rig.facts(c.BOOT_DECLARATION)[0].value == wire(event.declaration)
    assert rig.facts(contract("sui.s4.boot"))[0].value == {}
    assert not rig.facts(c.CANDIDATE_REQUEST)
    assert not [w for w in rig.host.window.drain() if w.desc.purpose == "candidate_generation"]
    # The legal fully saved initial-plan counterpart is a separate fresh rig.
    test_initial_plan_saved_with_origin_qgen_and_unstarted_wg()


@pytest.mark.parametrize("slot", ("capacity", "allocation", "need", "sampling", "model"))
def test_boot_missing_precondition_retains_raw_and_can_receive(rig, slot):
    """B:2120-2157,3239: malformed meaning is not permission or loss of raw custody."""
    event = boot(initial=slot == "model")
    d = event.declaration
    if slot == "capacity":
        d = replace(d, capacity=replace(d.capacity, value=-1))
    elif slot == "allocation":
        route_slot = d.routes[0]
        allocation = replace(route_slot.value.allocation, value=replace(route_slot.value.allocation.value,
            amount=fb.QuantityValue(contract=c.SEATS, value=3)))
        d = replace(d, routes=(replace(route_slot, value=replace(route_slot.value, allocation=allocation)),))
    elif slot == "need":
        d = replace(d, scope=replace(d.scope, value=replace(d.scope.value,
            need=fb.MethodCall(contract=contract("test.undeclared_need"), args={}))))
    elif slot == "sampling":
        route_slot = d.routes[0]
        d = replace(d, routes=(replace(route_slot, value=replace(route_slot.value,
            config=replace(route_slot.value.config, sampling_contract=contract("test.undeclared_measurement")))),))
    event = replace(event, declaration=d)
    accept_and_save(rig, rig.envelope(1, event, 30), c.BOOT_DECLARATION, 1)
    assert rig.facts(c.BOOT_DECLARATION)[0].value == wire(d)
    assert rig.workers.entries == []
    accept_and_save(rig, rig.envelope(2, received(), 31), c.RECEIVED, 1)
    rig.host.rebuild_window()
    assert rig.facts(c.BOOT_DECLARATION)[0].value == wire(d)
    assert rig.workers.entries == []
    # Nearest legal declaration differs only at the tested boundary in a fresh environment.
    legal = make_rig(initial=slot == "model")
    try:
        legal.install_legal_boot(initial=slot == "model")
        assert legal.host.window.drain()
    finally:
        legal.close()


def test_saved_descriptors_match_original_boot_and_worker_arguments(rig):
    """B:2165-2184: full Desc fields remain fixed through rebuild; no hidden injection."""
    rig.install_legal_boot(initial=False)
    declaration = rig.facts(c.BOOT_DECLARATION)[0]
    route_fact = rig.facts(contract("sui.f.route_config"))[0]
    requests = rig.facts(c.SEGMENT_REQUESTED)
    assert len(requests) == 1
    work = next(w for w in rig.host.window.drain() if isinstance(w, fb.MeasureSegment))
    desc = work.desc
    assert requests[0].value == {"desc": wire(desc)}
    assert desc.purpose == "measure_segment" and desc.reader is None and desc.numerical_view is None
    assert desc.process == fb.BootSlot(declaration=declaration.cid, slot="sensing")
    assert desc.allocation == fb.BootSlot(declaration=declaration.cid, slot="sensing-allocation")
    assert desc.args.route == route_fact.cid and desc.method == rig.boot_input.declaration.routes[0].value.config.sampling_contract
    assert desc.work_id and desc.stage_slot and desc.trigger and desc.permissions
    assert all(t.point in {declaration.cid, route_fact.cid} for t in desc.trigger)
    before = rig.storage_snapshot()
    rig.host.rebuild_window()
    same = next(w for w in rig.host.window.drain() if w.desc.work_id == desc.work_id)
    assert same == work and rig.storage_snapshot() == before
    assert rig.workers.entries == []  # enumeration/rebuild is not worker entry


def test_worker_start_ticket_is_once_and_rebuild_keeps_running_hold(rig):
    """B:309-311,1935: actual enter guard and occupied worker, not displayed phase."""
    rig.install_legal_boot(initial=False)
    rig.workers.hold = True
    extra_entries = []
    def action(work, ctx, witness):
        extra_entries.append(ctx.enter())
        witness.report(ctx, fb.SegmentReport(segment=work.request, item_slot="start", item=fb.SegmentBoundary(
            kind="started", work=work.desc.work_id, reading=rig.actual_reading(), reason="entered", evidence=())))
    rig.workers.action = action
    try:
        run_until_witness(rig, lambda: bool(rig.workers.entries) and bool(rig.facts(c.SEGMENT_REPORT)))
        assert extra_entries == [False]
        wid = rig.workers.entries[0].desc.work_id
        before = rig.storage_snapshot()
        rig.host.rebuild_window()
        assert rig.storage_snapshot() == before and rig.workers.stops == []
        assert sum(w.desc.work_id == wid for w in rig.workers.entries) == 1
        rig.host.post(received())
        run_until_witness(rig, lambda: bool(rig.facts(c.RECEIVED)))
        assert rig.workers.stops == []
    finally:
        rig.workers.release.set()


@pytest.mark.parametrize("first_outcome", ("not_started", "launched"))
def test_launch_return_and_worker_entry_are_separate(first_outcome):
    """B:316-318: definite non-start can retry; launched still needs entry.

    The nearest legal comparison for the uncertain-start tests below is an
    explicit not_started result followed by a successful launch of SAME work.
    The all-launched branch checks the delayed-entry boundary on its own.
    """
    launcher = WitnessLauncher(first_outcome)
    rig = make_rig(launcher=launcher)
    try:
        rig.install_legal_boot(initial=False)
        work = next(w for w in rig.host.window.drain() if isinstance(w, fb.MeasureSegment))
        wid = work.desc.work_id
        run_until_witness(rig, lambda: bool(launcher.attempts))
        assert all(attempt[0] == wid for attempt in launcher.attempts)
        assert rig.workers.calls == rig.workers.entries == rig.workers.stops == []
        if first_outcome == "not_started":
            before_retry = len(launcher.attempts)
            rig.host.rebuild_window()
            launcher.outcome = "launched"
            run_until_witness(rig, lambda: len(launcher.attempts) > before_retry)
            assert all(attempt[0] == wid for attempt in launcher.attempts)
        launched = [attempt for attempt in launcher.attempts if attempt[2] == "launched"]
        assert len(launched) == 1  # deferred body must not invite a second launch
        rig.host.rebuild_window()
        rig.host.post(received(data=b"launched-but-not-entered"))
        run_until_witness(rig, lambda: len(rig.facts(c.RECEIVED)) == 1)
        assert sum(attempt[2] == "launched" for attempt in launcher.attempts) == 1
        assert rig.workers.calls == rig.workers.entries == rig.workers.stops == []
        duplicate_entries = []
        rig.workers.action = lambda work, ctx, witness: duplicate_entries.append(ctx.enter())
        launched[0][1]()  # actual host wrapper; WitnessWorkers calls the real ctx.enter
        assert [entered.desc.work_id for entered in rig.workers.entries] == [wid]
        assert duplicate_entries == [False]
        assert rig.workers.stops == [wid]
    finally:
        rig.close()


@pytest.mark.parametrize("outcome", ("unknown", "raises"))
def test_uncertain_launch_keeps_occupancy_and_does_not_retry(outcome):
    """B:316-318,3193: uncertainty/exception retains the claim without entry.

    Violation: retry same WorkId or free its declared one seat, despite no
    stop witness. Nearest legal retry is not_started in the companion test.
    Expected occupancy comes from DeclaredNeed, never from a status oracle.
    """
    launcher = WitnessLauncher(outcome)
    rig = make_rig(launcher=launcher)
    try:
        rig.install_legal_boot(initial=False)
        work = next(w for w in rig.host.window.drain() if isinstance(w, fb.MeasureSegment))
        wid = work.desc.work_id
        run_until_witness(rig, lambda: bool(launcher.attempts))
        assert [attempt[0] for attempt in launcher.attempts] == [wid]
        assert rig.workers.calls == rig.workers.entries == rig.workers.stops == []
        for rebuild in (False, True):
            if rebuild:
                rig.host.rebuild_window()
            rig.host.post(received(data=b"launch-cut-" + str(rebuild).encode()))
            run_until_witness(rig, lambda: len(rig.facts(c.RECEIVED)) == (2 if rebuild else 1))
            rig.host.window.drain()  # enumeration is not a fresh start right
            status = next(w for w in rig.host.window.status().works if w.work_id == wid)
            assert status.held == rig.declared_need(work.desc)
            assert not status.stop_confirmed
            assert [attempt[0] for attempt in launcher.attempts] == [wid]
            assert rig.workers.calls == rig.workers.entries == rig.workers.stops == []
    finally:
        rig.close()


def test_forged_boundary_does_not_supply_worker_provenance(rig):
    """B:2086-2088: copied WorkId is raw evidence, not actual entry/stop."""
    rig.install_legal_boot(initial=False)
    work = next(w for w in rig.host.window.drain() if isinstance(w, fb.MeasureSegment))
    event = fb.SegmentReport(segment=work.request, item_slot="forged-end", item=fb.SegmentBoundary(
        kind="ended", work=work.desc.work_id, reading=rig.actual_reading(), reason="claimed", evidence=()))
    accept_and_save(rig, rig.envelope(200, event, 30), c.SEGMENT_REPORT, 1)
    assert not rig.facts(c.SEGMENT_BINDING) and rig.workers.entries == [] and rig.workers.stops == []
    assert not next(w for w in rig.host.window.status().works if w.work_id == work.desc.work_id).stop_confirmed
    rig.workers.action = rig.report_matching_ended
    run_until_witness(rig, lambda: bool(rig.workers.entries) and len(rig.facts(c.SEGMENT_REPORT)) == 2)


def test_status_receipt_states_and_evidence_are_read_only(rig):
    """M1: Post is not Accept; saved Point must be independently present in C/E."""
    rig.host.post(received())
    before = rig.storage_snapshot()
    queued = rig.host.window.status()
    assert len(queued.receipts) == 1 and queued.receipts[0].state == "received"
    assert queued.receipts[0].slots == ()
    assert rig.storage_snapshot() == before
    run_until_witness(rig, lambda: len(rig.facts(c.RECEIVED)) == 1)
    fact = rig.facts(c.RECEIVED)[0]
    saved = rig.host.window.status()
    assert len(saved.receipts) == 1 and saved.receipts[0].state == "accepted"
    assert saved.receipts[0].received_ns == fact.received_ns
    slots = saved.receipts[0].slots
    assert len(slots) == 1 and slots[0].state == "saved" and slots[0].target == fact.cid
    assert slots[0].evidence is not None
    assert not saved.readings and not saved.segments  # no numeric facts inferred from unknown bytes


@pytest.mark.parametrize("claim", ("select", "belief", "saved", "candidates"))
def test_external_decisions_are_raw_claims_not_events(rig, claim):
    """Paper:182-184,2031,2125. A command-shaped claim is legal inside raw bytes only."""
    import json
    supplied = {"kind": claim, "value": {"point": point("claimed")}}
    before = rig.storage_snapshot()
    with pytest.raises(fb.FbInputError) as caught:
        rig.host.window.accept(rig.envelope(1, supplied, 30))
    assert caught.value.reason == "shape" and rig.storage_snapshot() == before
    event = received(json.dumps(supplied).encode("utf-8"), claims=supplied)
    saved = accept_and_save(rig, rig.envelope(1, event, 30), c.RECEIVED, 1)[0]
    assert saved.value == wire(event)
    assert not rig.facts(c.SELECTION) and not rig.facts(contract("sui.f.knowledge_adopted"))
    assert not rig.host.window.drain()


LEGACY_CASES = tuple((kind, changed) for kind in ("request", "job") for changed in ("plan", "step", "outer_link"))


@pytest.mark.parametrize("kind,changed", LEGACY_CASES, ids=["-".join(case) for case in LEGACY_CASES])
def test_old_measurement_contracts_keep_body_and_parent_correspondence(kind, changed):
    """F-a:69-70,157,172. Compare exact legal prepared value against one changed body."""
    rig = RealRig(connect=False)
    raw, _ = rig.probe_record()
    plan = rig.ledger.append(raw, ())
    request = rig.record(Decided(inputs=(raw.id,), content=Payload.json({"plan": plan.cid, "step": 0}),
        contract=contract("sui.f.measurement_requested")), RefKind.DECISION, Role.MODEL)
    record, parents = request, (plan.cid,)
    if kind == "job":
        requested = rig.ledger.append(request, parents)
        record = rig.record(JobOpened(decision=request.id, step=0, content=Payload.json({"plan": plan.cid, "step": 0}),
            contract=contract("sui.f.measurement_job")), RefKind.JOB, Role.MODEL)
        parents = (requested.cid,)
    prepared = rig.ledger.prepare(record, parents)
    if changed in ("plan", "step"):
        bad_content = {"plan": point("changed-plan") if changed == "plan" else plan.cid,
                       "step": 1 if changed == "step" else 0}
        bad_body = replace(record.body, content=Payload.json(bad_content))
    elif kind == "request":
        bad_body = replace(record.body, inputs=(Ref(kind=RefKind.OBSERVATION, value="changed-input"),))
    else:
        bad_body = replace(record.body, decision=Ref(kind=RefKind.DECISION, value="changed-decision"))
    altered = replace(prepared, record=replace(record, body=bad_body))
    before = rig.storage_snapshot()
    with pytest.raises(CorruptEntry):
        rig.ledger.write(altered)
    assert rig.storage_snapshot() == before
    result = rig.ledger.write(prepared)
    saved = rig.read_stored(result.cid)[2]
    assert saved == record and saved.body.content.as_json() == {"plan": plan.cid, "step": 0}
    assert rig.ledger.entry(result.cid).parents == frozenset(parents)
    if kind == "request":
        assert saved.body.inputs == (raw.id,)
    else:
        assert saved.body.decision == request.id and saved.body.step == 0


def raw_examples():
    """Paper §2-5-3/6/7: all examples are test inputs, not status projections."""
    examples = {"boot_none": boot(), "boot_initial": boot(True), "clock": fb.ClockDeclared(declaration=source()),
                "received": received()}
    unavailable = f.Unavailable(reason="test unavailable", basis=())
    for tag, item in segment_items().items():
        examples["segment_" + tag] = fb.SegmentReport(segment=point("unknown-request"), item_slot="raw", item=item)
    frame = segment_items()["frame"]
    for field, value in (("actual_time", unavailable), ("value", unavailable), ("gap", segment_items()["gap"])):
        examples["frame_" + field] = replace(examples["segment_frame"], item=replace(frame, **{field: value}))
    for tag in ("started", "ended", "route_applied"):
        examples[tag + "_unavailable"] = replace(examples["segment_" + tag],
            item=replace(segment_items()[tag], reading=unavailable))
    for tag, outcome in work_outcomes().items():
        examples["work_" + tag] = fb.WorkFinished(work="unknown", started=reading(), finished=reading(), outcome=outcome)
    return examples


RAW_EXAMPLES = raw_examples()


def fixture_nodes(value, path=()):
    """Walk only declared DTO fields in OUR fixtures. Never inspect a host or P."""
    yield path, value
    if is_dataclass(value):
        for field in fields(value):
            yield from fixture_nodes(getattr(value, field.name), path + (field.name,))
    elif isinstance(value, tuple):
        for index, child in enumerate(value):
            yield from fixture_nodes(child, path + (index,))


# Only field obligations with an exact raw-input path are connected here. In
# particular, finding a nearby class does not discharge a relation, Support,
# conflict, ownership, or branch obligation. Those remain explicit gaps below.
RAW_SUBJECTS = {
    "Boot": fb.Boot, "BootDeclaration": fb.BootDeclaration, "ClockDeclared": fb.ClockDeclared,
    "ClockSource": type(source()), "ExistingClockSource": type(source()), "Received": fb.Received,
    "QuantityValue": fb.QuantityValue, "ResourceScope": fb.ResourceScope, "Allocation": fb.Allocation,
    "BootstrapRoute": fb.BootstrapRoute, "InitialProcess": fb.InitialProcess, "Environment": fb.Environment,
    "SlotValue<T>": fb.SlotValue, "SlotValue.declaration<T>": fb.SlotValue, "SlottedMethod": fb.SlottedMethod,
    "MethodCall": fb.MethodCall, "ContractRef": type(c.RECEIVED), "ContractValue": f.ContractValue,
    "SegmentReport": fb.SegmentReport, "MeasurementFrame": f.MeasurementFrame, "MeasurementId": f.MeasurementId,
    "MeasurementInterval": f.MeasurementInterval, "Gap": f.Gap, "MeasurementUnavailable": f.MeasurementUnavailable,
    "CoverageClaim": f.CoverageClaim, "CoverageUnproved": f.CoverageUnproved, "Unavailable": f.Unavailable,
    "ClockReading": f.ClockReading, "ReadingEvidence.clock": fb.ReadingClock,
    "SegmentItem.started": fb.SegmentBoundary, "SegmentItem.ended": fb.SegmentBoundary,
    "SegmentItem.route_applied": fb.RouteAppliedItem, "FailureInfo": fb.FailureInfo, "UnknownInfo": fb.UnknownInfo,
}


def raw_field_probe(target):
    """Return a concrete single-field shape fault and its otherwise identical legal input."""
    if target["kind"] != "field" or target["subject"] not in RAW_SUBJECTS:
        return None
    field = target["field"].removesuffix("[]")
    for name, event in RAW_EXAMPLES.items():
        for path, value in fixture_nodes(event):
            if type(value) is not RAW_SUBJECTS[target["subject"]]:
                continue
            if target["subject"].startswith("SegmentItem.") and target["subject"].split(".")[1] != (
                    value.kind if isinstance(value, fb.SegmentBoundary) else "route_applied"):
                continue
            if field in {f.name for f in fields(value)}:
                return dict(example=name, path=path + (field,), target=target["id"],
                    negative=target["negative"], nearest_legal=target["nearest_legal"],
                    required_reach="shape拒否は無書込み/無預かり。同じ番号の合法原本が全欄を保って実C/Eに保存")
    return None


def raw_branch_probe(target):
    """Explicit union/nullable/closure alternatives from paper, not class-name guessing."""
    branch = target["branch"].strip("'")
    subject = target["subject"]
    names = {"Started": "started", "Ended": "ended", "Frame": "frame", "Gap": "gap",
             "Unavailable": "measurement_unavailable", "Claim": "claim", "Unproved": "coverage_unproved",
             "RouteApplied": "route_applied"}
    if subject in ("SegmentItem", "SegmentReport") and branch in {*names, *names.values()}:
        tag = names.get(branch, branch)
        event = RAW_EXAMPLES["segment_" + tag]
        foil = replace(event, item=segment_items()["gap" if tag != "gap" else "measurement_unavailable"])
    elif subject in ("BootDeclaration", "BootDeclaration.initial") and branch in ("initialあり", "initial=None", "value", "null"):
        has_initial = branch in ("initialあり", "value")
        event, foil = boot(has_initial), boot(not has_initial)
    elif subject == "ReadingEvidence" and branch in ("clock", "unavailable"):
        event = RAW_EXAMPLES["segment_started" if branch == "clock" else "started_unavailable"]
        foil = RAW_EXAMPLES["started_unavailable" if branch == "clock" else "segment_started"]
    elif subject.startswith("MeasurementFrame"):
        if subject == "MeasurementFrame":
            if "." not in branch:
                return None
            field, branch = branch.split(".", 1)
        else:
            field = subject.split(".", 1)[1]
        options = {
            "actual_time": {"clock": "segment_frame", "ClockReading": "segment_frame",
                            "unavailable": "frame_actual_time", "Unavailable": "frame_actual_time"},
            "value": {"value": "segment_frame", "ImmutableJSON": "segment_frame",
                      "unavailable": "frame_value", "Unavailable": "frame_value"},
            "gap": {"null": "segment_frame", "None": "segment_frame", "value": "frame_gap", "Gap": "frame_gap"},
        }
        if field not in options or branch not in options[field]:
            return None
        event = RAW_EXAMPLES[options[field][branch]]
        other = {"actual_time": "frame_actual_time", "value": "frame_value", "gap": "frame_gap"}[field]
        foil = RAW_EXAMPLES[other if options[field][branch] == "segment_frame" else "segment_frame"]
    elif subject in ("MeasurementInterval", "MeasurementInterval.closure"):
        closure = {"両閉": "[start,end]", "左閉": "[start,end)", "右閉": "(start,end]", "両開": "(start,end)"}.get(branch, branch)
        if closure not in ("[start,end]", "[start,end)", "(start,end]", "(start,end)"):
            return None
        original = RAW_EXAMPLES["segment_frame"]
        interval = replace(original.item.measurement_interval, closure=closure)
        event = replace(original, item=replace(original.item, measurement_interval=interval))
        other_closure = "[start,end]" if closure != "[start,end]" else "(start,end)"
        foil = replace(event, item=replace(event.item, measurement_interval=replace(interval, closure=other_closure)))
    else:
        return None
    assert wire(event) != wire(foil), target["id"]
    return dict(event=event, foil=foil, negative=target["negative"], nearest_legal=target["nearest_legal"])


def replace_fixture_path(value, path, replacement):
    head, *tail = path
    child = value[head] if isinstance(head, int) else getattr(value, head)
    changed = replace_fixture_path(child, tail, replacement) if tail else replacement
    if isinstance(head, int):
        return tuple(changed if i == head else item for i, item in enumerate(value))
    return replace(value, **{head: changed})


def fixture_value(value, path):
    for part in path:
        value = value[part] if isinstance(part, int) else getattr(value, part)
    return value


def malformed_raw_example(probe):
    """Compare the same public constructor with one bad field; no frozen-object bypass.

    Some existing F-a value constructors enforce their own outer type. That
    rejection is a constructor-boundary observation, not an FWindow rejection.
    """
    event = RAW_EXAMPLES[probe["example"]]
    assert replace_fixture_path(event, probe["path"], fixture_value(event, probe["path"])) == event
    try:
        return replace_fixture_path(event, probe["path"], object())
    except (TypeError, ValueError):
        return None


STAGE1_ROWS = tuple(r for r in STAGE_MAP if "1" in r["required_stages"])
STAGE1_IDS = frozenset(r["id"] for r in STAGE1_ROWS)
ORIGINAL_BY_ID = {r["id"]: r for r in TARGETS}
RAW_FIELD_PROBES = {r["id"]: probe for r in STAGE1_ROWS
                    if (probe := raw_field_probe(ORIGINAL_BY_ID[r["id"]])) is not None}
RAW_BRANCH_PROBES = {r["id"]: probe for r in STAGE1_ROWS
                    if r["id"] not in RAW_FIELD_PROBES and (probe := raw_branch_probe(ORIGINAL_BY_ID[r["id"]])) is not None}


RECORD_SUBJECT_PATHS = {
    "Record schema 3": (), "RecordEnvelope": (),
    "Observed": ("body",), "ObservedEnvelope": ("body",),
    "Decided": ("body",), "DecidedEnvelope": ("body",),
    "Prediction": ("body",), "PredictionEnvelope": ("body",),
    "Producer": ("producer",), "ProducerState": ("producer", "state"), "StateRef": ("producer", "state"),
    "Instant": ("at",), "Instant (wall_nsは不一致 D-01 に隔離)": ("at",),
    "Payload": ("body", "content"),
}


def record_example(rig, subject):
    """Only O/D/P used by F-b; this is not a new use of any other Body."""
    body = Observed(route="test", content=Payload.json({"probe": 1}), contract=contract("test.probe"),
        caused_by=None, source_id=None, source_time_ns=None, received_ns=30)
    kind, role = RefKind.OBSERVATION, Role.MEMBRANE
    if subject.startswith("Decided"):
        body, kind, role = Decided(inputs=(), content=Payload.json({"probe": 1}), contract=contract("test.probe")), RefKind.DECISION, Role.MODEL
    elif subject.startswith("Prediction"):
        body, kind, role = Prediction(target="test", about=(), basis=(), content=Payload.json({"probe": 1}),
            contract=contract("test.probe")), RefKind.PREDICTION, Role.MODEL
    record = rig.record(body, kind, role)
    return replace(record, producer=replace(record.producer, state=StateRef(lineage="stage1-test", revision=1)))


def changed_record_field(record, path):
    """Keep a legal outer value whenever possible; break its fixed header binding."""
    value = fixture_value(record, path)
    if isinstance(value, Ref):
        changed = replace(value, value=value.value + "-changed")
    elif isinstance(value, Enum):
        changed = next(item for item in type(value) if item != value)
    elif isinstance(value, str):
        changed = value + "-changed"
    elif isinstance(value, int):
        changed = value + 1
    elif isinstance(value, bytes):
        changed = value + b" "
    elif isinstance(value, Payload):
        changed = Payload.json({"probe": 2})
    elif isinstance(value, tuple):
        changed = value + (Ref(kind=RefKind.OBSERVATION, value="changed"),)
    elif value is None:
        changed = (Ref(kind=RefKind.ATTEMPT, value="changed") if path[-1] == "caused_by" else
                   "changed" if path[-1] == "source_id" else 31)
    elif path[-1] == "at":
        changed = replace(value, mono_ns=value.mono_ns + 1)
    elif path[-1] == "producer":
        changed = replace(value, code_version=value.code_version + "-changed")
    elif path[-1] == "body":
        changed = replace(value, content=Payload.json({"probe": 2}))
    elif isinstance(value, StateRef):
        changed = replace(value, revision=value.revision + 1)
    elif isinstance(value, type(c.RECEIVED)):
        changed = replace(value, version=value.version + "-changed")
    else:
        raise TestConnectionGap(f"no typed field contrast: {path}")
    return replace_fixture_path(record, path, changed)


RECORD_FIELD_PROBES = {
    row["id"]: dict(subject=row["subject"], path=RECORD_SUBJECT_PATHS[row["subject"]] + (row["field"].removesuffix("[]"),))
    for row in TARGETS if row["id"] in STAGE1_IDS and row["kind"] == "field"
    and row["subject"] in RECORD_SUBJECT_PATHS
}


@pytest.mark.parametrize("rid", tuple(RECORD_FIELD_PROBES))
def test_stage1_record_field(rid, storage_rig):
    """Exact field preservation and changed-record/header rejection at Ledger.write.

    This discharges a field integrity contrast. It does not certify the semantic
    claims inside arbitrary payload JSON or the old F-a mathematical route.
    """
    probe = RECORD_FIELD_PROBES[rid]
    original = record_example(storage_rig, probe["subject"])
    path = probe["path"]
    assert replace_fixture_path(original, path, fixture_value(original, path)) == original
    before = storage_rig.storage_snapshot()
    try:
        bad = changed_record_field(original, path)
    except (TypeError, ValueError):
        bad = None  # existing public constructor type check, not a write observation
    prepared = storage_rig.ledger.prepare(original, ())
    assert storage_rig.storage_snapshot() == before
    assert prepared.record == original and prepared.parents == frozenset()
    if bad is not None:
        with pytest.raises(CorruptEntry):
            storage_rig.ledger.write(replace(prepared, record=bad))
        assert storage_rig.storage_snapshot() == before
    result = storage_rig.ledger.write(prepared)
    assert storage_rig.read_stored(result.cid)[2] == original


def test_stage1_raw_field_probes_are_constructible():
    """Assemble every negative before the stub host can mask a fixture mistake."""
    assert RAW_FIELD_PROBES
    for rid, probe in RAW_FIELD_PROBES.items():
        event = RAW_EXAMPLES[probe["example"]]
        bad = malformed_raw_example(probe)
        assert bad is None or type(bad) is type(event), rid
        assert probe["negative"] == ORIGINAL_BY_ID[rid]["negative"]
        assert probe["nearest_legal"] == ORIGINAL_BY_ID[rid]["nearest_legal"]


@pytest.mark.parametrize("rid", tuple(RAW_FIELD_PROBES))
def test_stage1_raw_field(rid, rig):
    """An executable exact input-field contrast, not a case-name-only connection."""
    probe = RAW_FIELD_PROBES[rid]
    event = RAW_EXAMPLES[probe["example"]]
    # object() is outside every declared outer type, including free JSON and nullable DTOs.
    bad = malformed_raw_example(probe)
    target = c.BOOT_DECLARATION if isinstance(event, fb.Boot) else c.CLOCK_NOTICE if isinstance(
        event, fb.ClockDeclared) else c.RECEIVED if isinstance(event, fb.Received) else c.SEGMENT_REPORT if isinstance(
        event, fb.SegmentReport) else c.WORK_REPORT
    before = rig.storage_snapshot()
    if bad is not None:
        with pytest.raises(fb.FbInputError) as caught:
            rig.host.window.accept(rig.envelope(1, bad, 30))
        assert caught.value.reason == "shape" and caught.value.field.startswith("/")
    assert rig.storage_snapshot() == before
    expected = wire(event.declaration if isinstance(event, (fb.Boot, fb.ClockDeclared)) else event)
    saved = accept_and_save(rig, rig.envelope(1, event, 30), target, 1)[0]
    assert saved.value == expected and saved.received_ns == 30 and not saved.parents
    assert not rig.facts(c.SEGMENT_BINDING)  # unknown raw names have not been certified


@pytest.mark.parametrize("rid", tuple(RAW_BRANCH_PROBES))
def test_stage1_raw_branch(rid, rig):
    """Both branches legal as raw reports; retyping an already accepted envelope is not."""
    probe = RAW_BRANCH_PROBES[rid]
    event, foil = probe["event"], probe["foil"]
    target = c.BOOT_DECLARATION if isinstance(event, fb.Boot) else c.SEGMENT_REPORT
    expected = wire(event.declaration if isinstance(event, fb.Boot) else event)
    other = wire(foil.declaration if isinstance(foil, fb.Boot) else foil)
    saved = accept_and_save(rig, rig.envelope(1, event, 30), target, 1)
    assert saved[0].value == expected and expected != other
    assert_host_fault(lambda: rig.host.window.accept(rig.envelope(1, foil, 30)))
    assert rig.facts(target) == saved
    rig.host.window.accept(rig.envelope(1, event, 30))
    second = accept_and_save(rig, rig.envelope(2, foil, 30), target, 2)
    assert {fact.cid for fact in second} != {fact.cid for fact in saved}
    assert sorted((fact.value == other, fact.value == expected) for fact in second) == [(False, True), (True, False)]
    assert not rig.facts(c.SEGMENT_BINDING)


# Exact bundles below are linked only after their operation/assertion paths were
# read. Field probes above have more precise per-ID nodes. A runtime stub still
# leaves ALL these links unverified; this is preparation, not stage-1 completion.
EXACT_SCENARIO_LINKS = {
    **{f"T.measurement_{subject}": tuple(
        f"test_old_measurement_contracts_keep_body_and_parent_correspondence[{kind}-{changed}]"
        for changed in ("plan", "step", "outer_link"))
       for subject, kind in (("requested", "request"), ("job", "job"))},
    **{f"T.measurement_{subject}.{field}": (
        f"test_old_measurement_contracts_keep_body_and_parent_correspondence[{kind}-{field}]",)
       for subject, kind in (("requested", "request"), ("job", "job")) for field in ("plan", "step")},
    **{rid: ("test_raw_event_entire_payload_and_storage_envelope[received]",
             "test_accept_is_custody_not_storage", "test_distinct_envelopes_are_distinct_receipts",
             "test_receive_clock_is_not_replaced_by_save_clock") + tuple(
                 f"test_same_number_compares_all_content_and_r[{changed}]"
                 for changed in ("data", "media_type", "route_epoch", "claims", "received_ns", "event_type"))
       for rid in ("T.received", "T.entry.I-1", "T.wire.text.2532", "T.rel.receipt")},
    **{rid: tuple(f"test_external_decisions_are_raw_claims_not_events[{claim}]"
                  for claim in ("select", "belief", "saved", "candidates"))
       for rid in ("T.paper.182", "T.paper.183", "T.paper.184")},
}


UNCONNECTED_BY_POLICY = {
    policy: tuple(r["id"] for r in STAGE1_ROWS if r["policy"] == policy and
                  r["id"] not in RAW_FIELD_PROBES and r["id"] not in RAW_BRANCH_PROBES and
                  r["id"] not in RECORD_FIELD_PROBES and r["id"] not in EXACT_SCENARIO_LINKS)
    for policy in sorted({r["policy"] for r in STAGE1_ROWS})
}


def collected_id(value):
    """pytest's default string-id escaping, including the catalogue's Japanese IDs."""
    return value.encode("unicode_escape").decode("ascii")


STAGE1_CONNECTIONS = {
    row["id"]: dict(
        focus={name: ORIGINAL_BY_ID[row["id"]][name] for name in ("subject", "field", "branch", "use", "negative", "nearest_legal")},
        references=(f"tests/test_fb_stage1.py::test_stage1_raw_field[{collected_id(row['id'])}]",) if row["id"] in RAW_FIELD_PROBES else
                   (f"tests/test_fb_stage1.py::test_stage1_raw_branch[{collected_id(row['id'])}]",) if row["id"] in RAW_BRANCH_PROBES else
                   (f"tests/test_fb_stage1.py::test_stage1_record_field[{collected_id(row['id'])}]",) if row["id"] in RECORD_FIELD_PROBES else
                   tuple("tests/test_fb_stage1.py::" + node for node in EXACT_SCENARIO_LINKS[row["id"]]) if row["id"] in EXACT_SCENARIO_LINKS else
                   (f"tests/test_fb_stage1.py::test_stage1_obligation_connection[{row['policy']}]",),
        connection="raw_field_contrast" if row["id"] in RAW_FIELD_PROBES else
                   "raw_branch_contrast" if row["id"] in RAW_BRANCH_PROBES else
                   "record_field_integrity_contrast" if row["id"] in RECORD_FIELD_PROBES else
                   "exact_scenario_bundle" if row["id"] in EXACT_SCENARIO_LINKS else "unconnected",
        execution="not_run") for row in STAGE1_ROWS
}


@pytest.mark.skip(reason="D11 (2026-10-19、紙 v0.25 §6-7): 割当表と独立の対象一覧は参考として凍結し、分母にしない")
@pytest.mark.parametrize("policy", tuple(UNCONNECTED_BY_POLICY))
def test_stage1_obligation_connection(policy):
    pending = UNCONNECTED_BY_POLICY[policy]
    if not pending:
        assert all(row["id"] in EXACT_SCENARIO_LINKS or row["id"] in RAW_FIELD_PROBES or row["id"] in RAW_BRANCH_PROBES or row["id"] in RECORD_FIELD_PROBES
                   for row in STAGE1_ROWS if row["policy"] == policy)
        return  # bookkeeping only; the referenced behavioral tests remain independently red
    raise TestConnectionGap(
        f"FBS0-03 未接続 {policy}: {len(pending)} rows; first={pending[:5]}; "
        f"{PAPER}:3256,3258. 各行の正負対照/必須到達点の実接続は未完。"
        "ContractGapや骨組みのNotImplementedErrorを識別力の証拠にしない。"
    )


def test_stage1_catalogue_inventory(request):
    from collections import Counter
    import os
    if os.environ.get("FB_STAGE0_INVENTORY"):
        import json
        print("\nFBS0_INVENTORY " + json.dumps(dict(
            owner=Counter(row["owner_stage"] for row in STAGE_MAP),
            required_stage1=len(STAGE1_ROWS), raw_field_probes=len(RAW_FIELD_PROBES), record_field_probes=len(RECORD_FIELD_PROBES),
            raw_branch_probes=len(RAW_BRANCH_PROBES),
            exact_bundles=len(EXACT_SCENARIO_LINKS),
            unconnected={key: len(value) for key, value in UNCONNECTED_BY_POLICY.items()}), ensure_ascii=False))
    # Previous report counted the twelve Run/RunException rows. Paper:3247
    # excludes them from this vertical path; do not silently keep that denominator.
    assert len(STAGE1_ROWS) == 1272 - 12 + 4 == 1264
    assert len(STAGE1_CONNECTIONS) == len(STAGE1_ROWS)
    assert not set(RAW_FIELD_PROBES) & set(RECORD_FIELD_PROBES)
    assert not set(EXACT_SCENARIO_LINKS) & (set(RAW_FIELD_PROBES) | set(RECORD_FIELD_PROBES))
    assert not set(RAW_BRANCH_PROBES) & (set(RAW_FIELD_PROBES) | set(RECORD_FIELD_PROBES) | set(EXACT_SCENARIO_LINKS))
    assert set(EXACT_SCENARIO_LINKS) <= STAGE1_IDS
    assert sum(map(len, UNCONNECTED_BY_POLICY.values())) + len(RAW_FIELD_PROBES) + len(RAW_BRANCH_PROBES) + len(RECORD_FIELD_PROBES) + len(EXACT_SCENARIO_LINKS) == len(STAGE1_ROWS)
    collected = {item.nodeid for item in request.session.items}
    for row in STAGE1_CONNECTIONS.values():
        for node in row["references"]:
            function = node.split("::")[1].split("[")[0]
            assert callable(globals().get(function)), node
            assert node in collected, node
