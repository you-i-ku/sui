"""K28 migration of reception with no initial thinking process.

Production SourceMeasurer creates the finite acquisition sequence. The remaining
public boundary/unproved branches still retain raw retransmissions, even when
their claimed request is unknown. Closed branches are refusal cases in
test_fb_belief.py, not positive reception examples in this module.
"""

from dataclasses import replace

import pytest

from sui import fb, fb_contracts as c
from test_fb_acquisition_loop import AcquisitionLoopRig
from test_fb_belief import T, E
from test_fb_measure import acquire1_expected_frame
from test_fb_skeleton import segment_items, point
from test_fb_stage1 import wire


class AcquisitionNoInitialRig(AcquisitionLoopRig):
    def __init__(self):
        def install(rig):
            rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration, initial=None, perception=None))
        super().__init__(symbols=(T, E), before_host=install)
        self.hold_return = True

    def publish_next(self, index, *, last=False):
        if index: self.return_release.set()
        assert self.source.ready[index].wait(30), "production source read did not start"
        self.return_release.clear()
        return self.publish(index, last=last)


@pytest.fixture
def make_reception():
    rigs = []
    def make():
        rig = AcquisitionNoInitialRig()
        rigs.append(rig)
        return rig
    yield make
    for rig in reversed(rigs): rig.close()


def test_initial_none_continues_measuring_receiving_and_saving(make_reception):
    """Low-level perception=None: two operations and independent Post without Compute.

    Disabling measurement with initial=None, losing a raw/Frame, or starting
    candidate/evaluation/update work fails the explicit received/saved witnesses.
    """
    rig = make_reception()
    assert rig.boot_input.declaration.initial is None
    assert rig.boot_input.declaration.perception is None
    rig.begin()
    probe = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"independent reception", claims={})
    rig.host.post(probe)
    frames = []
    for index in range(2):
        raw, (observed, frame) = rig.publish_next(index, last=index == 1)
        call = rig.calls[index]
        assert (call.acquired.before.reading.time_ns, call.acquired.after.reading.time_ns) == (
            index * 10, (index + 1) * 10)
        expected = acquire1_expected_frame(rig, call, raw[1] if raw else None)
        assert frame.value["item"] == {"kind": "frame", "value": wire(expected)}
        assert observed.point == frame.cid
        frames.append(frame.cid)
    rig.until(lambda: any(r.value == wire(probe) for r in rig.facts(c.RECEIVED)))
    assert len(set(frames)) == 2 and len(rig.calls) == len(rig.source.calls) == 2
    assert [a.acquired.outcome for a in rig.calls] == ["taken", "empty"]
    assert len(rig.workers.entries) == 1 and all(isinstance(w, fb.MeasureSegment) for w in rig.workers.entries)
    assert not rig.facts(c.CANDIDATE_REQUEST) and not rig.facts(c.EVALUATION_REQUESTED)
    assert not rig.facts(c.SELECTION) and not rig.requests("belief_update")
    assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)


@pytest.mark.parametrize("branch", ("started", "ended", "route_applied", "coverage_unproved"))
def test_all_segment_raw_reports_preserve_shape_without_certifying_unknown_request(make_reception, branch):
    """K28 leaves these four raw branches open; unknown claimed k never gets B.

    Each new Post has a fresh envelope and raw Point, even for identical content.
    The old Frame/Claim/Gap/Unavailable positives are now entrance refusals in
    test_belief1_producer_cannot_publish_frame_or_interval_evidence and
    test_belief1_accept_rejects_envelopes_outside_acquire.
    """
    rig = make_reception()
    rig.begin()
    # The closest legal Frame is produced by the real measuring worker.
    rig.publish_next(0, last=True)
    unknown = point("unknown-request")
    event = fb.SegmentReport(segment=unknown, item_slot="fixed", item=segment_items()[branch])
    before = {r.cid for r in rig.facts(c.SEGMENT_REPORT)}
    rig.host.post(event)
    rig.until(lambda: any(r.cid not in before and r.value == wire(event) for r in rig.facts(c.SEGMENT_REPORT)))
    first, = (r for r in rig.facts(c.SEGMENT_REPORT) if r.cid not in before and r.value == wire(event))
    rig.clock.set(rig.clock.peek() + 1)
    rig.host.post(event)
    rig.until(lambda: len([r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(event)]) == 2)
    records = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value == wire(event)]
    assert records[0].value == records[1].value and records[0].cid != records[1].cid
    assert first.cid in {r.cid for r in records}
    assert not [b for b in rig.facts(c.SEGMENT_BINDING) if b.value["segment"] == unknown]
    assert not rig.requests("belief_update") and not rig.facts(c.BELIEF_ADOPTED)
