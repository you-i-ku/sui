"""K28 migration: K17 rejections ahead of real production acquisitions.

Only keep_running advances the host. A source-side public callback posts bad
envelopes before it returns its first item; SourceMeasurer alone calls acquire.
No rejected payload uses the now-closed Claim/Gap/Unavailable/Frame ingress.
"""

from dataclasses import replace
import re

import pytest

from sui import fb, fb_contracts as c
from test_fb_acquisition_keep import AcquisitionKeepRig
from test_fb_loop import execution_for, assert_keep_interruption
from test_fb_skeleton import segment_items


class AcquisitionRejectionRig(AcquisitionKeepRig):
    def __init__(self, kinds, *, fault=None, **kwargs):
        self.bad, self.bad_events = [], {}
        super().__init__(fault=fault, **kwargs)
        source_read = self.source.read
        def read(cursor):
            if not self.source.calls:
                port = next(iter(self.ports.values()))
                for kind in kinds:
                    if kind == "non_event": event, field = object(), ""
                    elif kind == "media_type":
                        event = fb.Received(route_epoch="route-A", media_type=999999,
                            data=b"row6-poison", claims={"row6-poison": True})
                        field = "media_type"
                    else:
                        assert kind == "item_slot"
                        event = fb.SegmentReport(segment=port.work.request, item_slot=999999,
                            item=replace(segment_items()["coverage_unproved"],
                                route_epoch="route-A"))
                        field = "item_slot"
                    before = {r.envelope for r in execution_for(port.delegate, port.work.desc.work_id).reports}
                    port.post(event)
                    observation, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports
                                    if r.envelope not in before)
                    self.bad.append((observation.envelope, field, port))
                    self.bad_events[observation.envelope] = event
            return source_read(cursor)
        self.source.read = read

    def assert_rejections(self):
        rejected = [i for i in self.host.interruptions() if i.kind == "rejected"]
        assert len(rejected) == len(self.bad) and self.bad
        for interruption, (number, field, port) in zip(rejected, self.bad):
            assert interruption.operation == "accept" and interruption.error_type == "FbInputError"
            assert interruption.count == 1 and interruption.first_ns <= interruption.last_ns
            if field: assert field in interruption.message
            assert re.search(r"(?<![0-9A-Za-z_])" + str(number) + r"(?![0-9A-Za-z_])", interruption.message)
            observation, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports
                            if r.envelope == number)
            assert observation.point is None
            assert number not in self.receipts()
        # No malformed Received or malformed allowed-branch report became a fact.
        assert not [r for r in self.facts(c.RECEIVED) if r.value.get("data") == list(b"row6-poison")]
        assert not [r for r in self.facts(c.SEGMENT_REPORT) if r.value.get("item_slot") == 999999]
        ctx = self.workers.contexts["measure_segment"]
        numbers = [r.envelope for e in ctx.evidence().executions for r in e.reports]
        assert len(numbers) == len(set(numbers))
        assert self.host.halted is None and not any(i.kind == "halted" for i in self.host.interruptions())


@pytest.mark.parametrize("kind", ["non_event", "media_type", "item_slot"])
def test_row6_rejected_head_does_not_block_or_change_the_two_ce1_updates(kind):
    """K17 + K28: malformed head cannot halt/block or poison FIRST->SECOND.

    Leaving the bad head queued, applying its payload or losing a later real
    acquisition fails completed production updates and the exact saved chain.
    """
    rig = AcquisitionRejectionRig((kind,))
    try:
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop(); rig.assert_rejections()
        assert [i.kind for i in rig.host.interruptions()] == ["rejected"]
    finally: rig.close()


def test_row6_two_rejections_create_no_record_or_custody_and_survive_later_success():
    """Coalescing two rejections, reusing their numbers or clearing history fails.

    Both bad envelopes precede the two authentic Frames; their report points
    remain None after all updates/selections finish and neither has custody.
    """
    rig = AcquisitionRejectionRig(("media_type", "item_slot"))
    try:
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop(); rig.assert_rejections()
        history = rig.host.interruptions()
        assert [i.kind for i in history] == ["rejected", "rejected"]
        assert rig.host.keep_running(lambda _status: True, timeout=0) is True
        assert rig.host.interruptions() == history
    finally: rig.close()


def test_row6_rejection_and_store_recovery_share_one_keep_running_call():
    """K16/K17 + K28: one call handles rejection and a lost R* write reply.

    Misclassifying either exception, retrying acquisition/update, or abandoning
    the prepared result fails one store interruption plus FIRST->SECOND.
    """
    rig = AcquisitionRejectionRig(("media_type",),
        fault={"boundary": "after_entry_commit", "target": "result", "times": 1})
    try:
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop(); rig.assert_rejections()
        assert len(rig.fault.raised) == 1
        stores = [i for i in rig.host.interruptions() if i.kind == "store"]
        assert len(stores) == 1
        assert_keep_interruption(stores[0], rig.fault.raised[0], kind="store", count=1)
        assert [i.kind for i in rig.host.interruptions()] == ["rejected", "store"]
    finally: rig.close()


def finish_rejected_number_scene(rig, observed, port, before, preparations, history):
    assert rig.snapshot() == before and tuple(rig.ledger.preparations) == preparations
    current, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports if r.envelope == observed.envelope)
    assert current.point is None
    good = replace(rig.bad_events[observed.envelope], item_slot="new-legal-unproved")
    port.post(good)  # a NEW Post from the same admitted mouth
    rig.source.release[0].set()
    assert rig.host.keep_running(lambda _s: len(rig.facts(c.BELIEF_ADOPTED)) == 1, timeout=60)
    rig.source.release[1].set()
    assert rig.host.keep_running(rig.complete, timeout=60)
    rig.assert_loop(); rig.assert_rejections()
    saved, = [r for r in rig.facts(c.SEGMENT_REPORT) if r.value.get("item_slot") == good.item_slot]
    assert saved.value["item"]["kind"] == "coverage_unproved"
    assert rig.host.interruptions() == history


def rejected_number_scene():
    rig = AcquisitionRejectionRig(("item_slot",), auto_source=False)
    try:
        assert rig.host.keep_running(lambda _s: bool(rig.bad) and rig.source.ready[0].is_set()
            and len([i for i in rig.host.interruptions() if i.kind == "rejected"]) == 1, timeout=60)
        number, _field, port = rig.bad[0]
        observed, = (r for r in execution_for(port.delegate, port.work.desc.work_id).reports if r.envelope == number)
        assert observed.point is None
        return rig, observed, port
    except BaseException:
        rig.close()
        raise


def test_row6_rejected_number_changed_payload_is_host_fault_and_new_post_still_updates():
    """K17: checking only queued/accepted numbers misses a consumed rejected number.

    A repaired open-branch report under n must raise HostFault, not InputError;
    neither custody nor prepared facts may change. A new Post still progresses.
    """
    rig, observed, port = rejected_number_scene()
    try:
        before, preparations, history = rig.snapshot(), tuple(rig.ledger.preparations), rig.host.interruptions()
        event = replace(rig.bad_events[observed.envelope], item_slot="repaired-under-old-number")
        with pytest.raises(fb.FbHostFault):
            rig.host.window.accept(fb.Envelope(number=observed.envelope, received_ns=observed.received_ns, event=event))
        finish_rejected_number_scene(rig, observed, port, before, preparations, history)
    finally: rig.close()


def test_row6_rejected_number_same_malformed_payload_stays_shape_without_custody():
    """K17: remembering a rejected body never turns its replay into successful custody."""
    rig, observed, port = rejected_number_scene()
    try:
        before, preparations, history = rig.snapshot(), tuple(rig.ledger.preparations), rig.host.interruptions()
        event = rig.bad_events[observed.envelope]
        for _ in range(2):
            with pytest.raises(fb.FbInputError) as caught:
                rig.host.window.accept(fb.Envelope(number=observed.envelope, received_ns=observed.received_ns, event=event))
            assert caught.value.reason == "shape" and "item_slot" in caught.value.field
        finish_rejected_number_scene(rig, observed, port, before, preparations, history)
    finally: rig.close()
