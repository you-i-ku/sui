"""K28 pending sequence and acknowledgement loss, from real acquire envelopes."""

import json
from threading import Event
from types import SimpleNamespace

import pytest

from sui import f, fb, fb_contracts as c
from test_fb_acquisition_store import AcquisitionFaultRig
from test_fb_acquisition_loop import sequence_answer
from test_fb_belief import T, E
from test_fb_measure import acquire1_expected_frame
from test_fb_loop import (LoopRig, Row1StoreCut, Row2AckLoss, ORDER, assert_update,
    row5_report_for_work, execution_for, assert_keep_interruption, ACQUIRED)
from test_fb_loop import assert_admitted_evaluation_root, wait_evaluation_activity_end
from test_fb_skeleton import contract
from test_fb_stage1 import wire
from test_fb_stage2 import Stage2Rig, MATH, TINY_BUDGET, terminal


def original_envelopes(rig, call):
    """Reconstruct ALREADY posted envelopes from K25's public ES and literals.

    This calls neither acquire nor Post and supplies no new Frame authority.
    """
    observed = rig.source_for(call)
    raw = SimpleNamespace(record_id=observed.received_id) if observed.envelope is not None else None
    frame = fb.SegmentReport(segment=call.work.request, item_slot=f"frame:{call.sequence}",
        item=acquire1_expected_frame(rig, call, raw))
    out = [fb.Envelope(number=observed.frame_envelope, event=frame,
        received_ns=call.acquired.after.reading.time_ns)]
    if raw is not None:
        item = call.acquired.item
        out.insert(0, fb.Envelope(number=observed.envelope,
            event=fb.Received(route_epoch=call.route_epoch, media_type=item.media_type,
                data=item.data, claims=item.claims), received_ns=call.acquired.after.reading.time_ns))
    assert {e.number for e in out} == set(call.envelopes)
    return out


def accept_operation(rig, call):
    for envelope in original_envelopes(rig, call): rig.host.window.accept(envelope)
    for _ in range(256):
        rig.host.window.settle()  # never receive another queued envelope here
        pair = rig.pair(call)
        if pair is not None and any(b.value["report"] == pair[1][1].cid for b in rig.facts(c.SEGMENT_BINDING)):
            assert pair[1][1].value == wire(original_envelopes(rig, call)[-1].event)
            return pair[1][1]
    pytest.fail("R2: direct acceptance did not save and bind the original operation")


def make_pending(symbols):
    return AcquisitionFaultRig(lambda r: Row1StoreCut(r, "request", "observer", report_kind="frame"),
        symbols=symbols, capacity=5)  # measure 1 + offered update 2 + continuation 2


def finish_continuation(rig, number, *, allow_no_decision=False):
    """K36-c: explicitly finish one admitted activity before the next serial input.

    Wait for a saved, offered WorkId that has not run. LoopRig.callback alone
    can return the previous continuation's last request; rerunning that body is
    not progress. Missing successors still fail the existing bounded watchdog.
    K28-b(so)/H8: when enabled, only a real issued NoDecision, its saved PR/EV
    and output terminal count as a regular end. A missing draw alone is never
    enough. Ep NoDecision creates no D/Ee/selection; Ee creates no selection.
    """
    selections_before = {s.cid for s in rig.facts(c.SELECTION)}
    if not allow_no_decision:
        assert len(selections_before) == number
    position, activity = 0, None
    while position < len(ORDER[1:]):
        stage = ORDER[1:][position]
        def fresh_request_offered():
            requests = rig.requests(stage)
            if not requests: return False
            work_id = requests[-1].value["desc"]["work_id"]
            return work_id not in rig.executed and any(
                key == work_id for key, _body in rig.launcher.attempts)
        rig.until(fresh_request_offered)
        request = rig.requests(stage)[-1]
        if stage == "evaluation_prepare":
            adoptions = rig.facts(c.BELIEF_ADOPTED)
            activity = assert_admitted_evaluation_root(rig, request, adoptions[-1] if adoptions else None)
        work = rig.run_stage(stage)
        assert work.request == request.cid
        if stage == "selection_draw":
            position += 1
            continue
        issued = rig.workers.issued[stage]
        if isinstance(issued.value, f.NoDecision):
            assert allow_no_decision, "this short control must reach selection"
            logical_contract = c.PREPARED if stage == "evaluation_prepare" else c.EVALUATED
            rig.until(lambda: any(p.value["request"] == work.request for p in rig.facts(logical_contract))
                and any(t.value["work"] == work.desc.work_id for t in rig.facts(c.WORK_TERMINAL)))
            saved, = (p for p in rig.facts(logical_contract) if p.value["request"] == work.request)
            assert rig.one(MATH, cid=saved.value["artifact"]).value == json.loads(issued.canonical_bytes)
            t = terminal(rig, work)
            assert t.value["terminal_kind"] == "outputs"
            rig.until(lambda: any(r.response == "no_decision" and r.selected is None
                and (r.target in (work.request, t.cid) or t.cid in r.evidence.basis)
                for r in rig.host.window.status().readings))
            # The current thinking cycle has no other body running. Drain the
            # ordinary bounded safety observation; do not request forbidden jobs.
            rig.settle_steps()
            if stage == "evaluation_prepare":
                assert not [q for q in rig.requests("selection_draw")
                    if q.value["desc"]["args"]["prepared"] == saved.cid]
                assert not [q for q in rig.requests("evaluation")
                    if q.value["desc"]["args"]["evaluation_request"] == work.request]
            else:
                assert not [s for s in rig.facts(c.SELECTION) if s.value["evaluated"] == saved.cid]
            assert {s.cid for s in rig.facts(c.SELECTION)} == selections_before
            if stage == "evaluation" and issued.value.reason == "selection_boundary":
                row, = [row for row in rig.host.window.status().evaluations if row.activity == activity]
                assert row.outcome == "running" and row.counted
                position = 1  # K35 continues D/Ee inside this same activity, without a fixed cap.
                continue
            wait_evaluation_activity_end(rig, activity)
            return stage + ":no_decision"
        assert isinstance(issued.value, f.FProblem if stage == "evaluation_prepare" else f.Selected)
        position += 1
    rig.until(lambda: len(rig.facts(c.SELECTION)) == len(selections_before) + 1)
    wait_evaluation_activity_end(rig, activity)
    return "selected"


class PendingReplyRig(Stage2Rig):
    """Exercise the thinking-only helper with real F-a issues, before K28 exists.

    This checks neither acquisition nor a production thinking worker. Reuse
    the test loop's fresh-WorkId bookkeeping for one initial thinking cycle.
    """
    requests = LoopRig.requests
    callback = LoopRig.callback
    run_stage = LoopRig.run_stage
    until = Stage2Rig.drive

    def __init__(self, **kwargs):
        self.executed = set()
        super().__init__(**kwargs)


@pytest.mark.parametrize("outcome", ["selected", "evaluation_prepare:no_decision", "evaluation:no_decision"])
def test_pending_continuation_distinguishes_selection_from_regular_no_decision(outcome):
    """H8: unavailable proof / tiny evaluation budget yield real NoDecision issues.

    Waiting for a forbidden successor, calling failure/unknown NoDecision, or
    inventing a selection fails. The normal budget control still selects.
    """
    kwargs = ({"omit_implementation": contract("finite_option_proof")}
        if outcome == "evaluation_prepare:no_decision" else
        {"evaluate_budget": TINY_BUDGET} if outcome == "evaluation:no_decision" else {})
    rig = PendingReplyRig(**kwargs)
    try:
        rig.run_stage("candidate_generation")
        assert finish_continuation(rig, 0, allow_no_decision=True) == outcome
        progressed = outcome != "evaluation_prepare:no_decision"
        assert len(rig.requests("evaluation_prepare")) == 1
        assert len(rig.requests("selection_draw")) == len(rig.requests("evaluation")) == int(progressed)
        assert len(rig.facts(c.SELECTION)) == int(outcome == "selected")
    finally:
        rig.close()


@pytest.mark.parametrize("accept_order", [(2, 1), (1, 2)], ids=["reverse_accept", "receipt_order_control"])
def test_row2_accept_order_ack_loss_confirms_a_before_q_b_and_keeps_one_chain(accept_order):
    """K13/K28: saved B-discovery order cannot bypass the pending adoption.

    Treating a as absent/confirmed too soon fails Q_B absence at loss and
    Q_B.prior=a after readback. Recreating a or effects fails exact counts.
    Diagonal T,E,T yield FIRST, SECOND, then (32/33,1/33;33/2048) by products.
    """
    rig = make_pending((T, E, T))
    ready, release = [Event() for _ in range(3)], [Event() for _ in range(3)]
    rig.cleanup_releases.extend(release)
    def admitted(work, ctx, entered):
        if entered:
            seq = row5_report_for_work(rig, work).value["item"]["value"]["sample_seq"]
            ready[seq].set()
            assert release[seq].wait(30), "update gate not released"
    rig.admission_hook = admitted
    try:
        rig.start()
        h_call = rig.publish_operation(0)
        rig.saved_pair(h_call)
        h_q, h_thread = rig.start_update_thread()
        assert ready[0].wait(30)
        calls = {i: rig.publish_operation(i) for i in (1, 2)}
        assert len(rig.requests("belief_update")) == 1
        points = {i: accept_operation(rig, calls[i]).cid for i in accept_order}
        assert [r.value["item"]["value"]["sample_seq"] for r in rig.reports("frame")][-2:] == list(accept_order)
        release[0].set(); h_thread.join(30); assert not h_thread.is_alive()
        rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 1)
        h, = rig.facts(c.BELIEF_ADOPTED)
        finish_continuation(rig, 1)
        a_q, a_thread = rig.start_update_thread(); assert ready[1].wait(30)
        a_work = rig.update_ports[a_q.cid].work
        assert row5_report_for_work(rig, a_work).cid == points[1]
        assert a_work.desc.args.prior == h.cid and len(rig.requests("belief_update")) == 2
        loss = Row2AckLoss(rig, "adoption", "after_entry_commit")
        release[1].set(); a_thread.join(30); assert not a_thread.is_alive()
        for _ in range(128):
            rig.host.keep_running(lambda _s: loss.failed, timeout=0)
            if loss.failed: break
        assert loss.failed and not loss.confirmed, "UNFIRED: adoption acknowledgement was not lost"
        loss.assert_commit_at_loss()
        assert len(rig.requests("belief_update")) == 2, "Q_B preceded a confirmation"
        a = rig.one(c.BELIEF_ADOPTED, cid=loss.prepared.cid)
        rig.until(lambda: loss.confirmed)
        finish_continuation(rig, 2)
        b_q, b_thread = rig.start_update_thread(); assert ready[2].wait(30)
        b_work = rig.update_ports[b_q.cid].work
        assert b_work.desc.args.prior == a.cid and row5_report_for_work(rig, b_work).cid == points[2]
        release[2].set(); b_thread.join(30); assert not b_thread.is_alive()
        rig.until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 3)
        finish_continuation(rig, 3)
        h, same_a, b = rig.facts(c.BELIEF_ADOPTED)
        assert same_a == a and [x.value["previous"] for x in (h, a, b)] == [None, h.cid, a.cid]
        for i, adopted in enumerate((h, a, b)):
            work = rig.update_ports[adopted.value["request"]].work
            assert_update(rig, work, adopted, sequence_answer((T,E,T)[:i+1]), None if not i else (h,a)[i-1].cid)
        assert loss.attempts and all(attempt == loss.prepared for attempt in loss.attempts)
        assert rig.read_stored(a.cid) == (loss.prepared.header, loss.prepared.salt, loss.prepared.record)
        assert len(rig.workers.entries) == len(rig.launcher.attempts) == 17
        assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 3
        assert len({x.value["previous"] for x in (h,a,b)}) == 3
        assert len([event for event, _issued in rig.workers.sent if isinstance(event,fb.DrawReturned)]) == 4
        ctx = rig.workers.contexts["measure_segment"]
        for work in rig.workers.entries:
            assert [ok for wid,ok in rig.workers.entry_attempts if wid == work.desc.work_id] == [True]
            execution = execution_for(ctx, work.desc.work_id)
            assert execution.entered == 1 and execution.launches == ("launched",)
        for result in rig.facts(c.UPDATE_RESULT):
            assert len([e for e in ctx.evidence().acquisitions if result.cid in e.contents]) == 1
            assert len([g for g in rig.facts(ACQUIRED) if result.cid in g.value["contents"]]) == 1
        assert not rig.facts(c.STALE) and len(rig.calls) == len(rig.source.calls) == 3
        interruption, = rig.host.interruptions()
        assert_keep_interruption(interruption, loss.loss_error, kind="store", count=1)
        assert rig.host.halted is None
    finally: rig.close()


def test_row5_pending_order_follows_received_time_and_envelope_not_report_sort_keys():
    """K28 replaces interval-Claim order by native acquisition order, without skips.

    At least eleven Frames wait behind seq0; reverse acceptance, CID order and
    lexical frame:10/frame:2 slot order differ from the observed reception order.
    Acquisition intervals intrinsically follow seq, so a different interval
    order is no longer a legal fixture (K28-b(b)); do not fabricate a Frame.
    K28-b(so): every real acquisition must still be adopted in order, but the
    subsequent thinking may regularly end at NoDecision instead of selection.
    """
    symbols = (T, E) * 8
    rig = make_pending(symbols)
    try:
        rig.start()
        rig.clock.set(200)
        rig.clock.set = lambda _ns: None  # legal constant test M: all subsequent r tie
        first = rig.publish_operation(0); rig.saved_pair(first)
        calls = []
        for i in range(1, 12): calls.append(rig.publish_operation(i))
        points = {call.sequence: accept_operation(rig, call) for call in reversed(calls)}
        for i in range(12, 16):
            ordered = [points[call.sequence].cid for call in calls]
            if ordered not in (sorted(ordered), sorted(ordered, reverse=True)): break
            call = rig.publish_operation(i); calls.append(call); points[i] = accept_operation(rig, call)
        rig.measurers[rig.measure_key].stop(); rig.return_release.set()
        expected = [points[call.sequence].cid for call in calls]
        assert expected not in (sorted(expected), sorted(expected, reverse=True)), "fixture did not discriminate CID order"
        assert expected != [p.cid for p in sorted(points.values(), key=lambda p: p.value["item_slot"])]
        observations = [rig.source_for(call) for call in calls]
        assert len({o.after_ns for o in observations}) == 1
        assert sorted(observations, key=lambda o: (o.after_ns, o.frame_envelope)) == observations
        assert len(rig.requests("belief_update")) == 1 and not rig.facts(c.BELIEF_ADOPTED)
        previous = None
        all_calls = [first, *calls]
        thinking_outcomes = []
        for i, call in enumerate(all_calls):
            work, adopted = rig.update()
            assert row5_report_for_work(rig, work).cid == rig.pair(call)[1][1].cid
            assert_update(rig, work, adopted, sequence_answer(symbols[:i+1]), previous)
            previous = adopted.cid
            thinking_outcomes.append(finish_continuation(rig, i+1, allow_no_decision=True))
        assert len(rig.calls) == len(rig.requests("belief_update")) == len(rig.facts(c.BELIEF_ADOPTED)) == len(all_calls)
        assert len({a.value["previous"] for a in rig.facts(c.BELIEF_ADOPTED)}) == len(all_calls)
        assert len(thinking_outcomes) == len(all_calls)
        assert set(thinking_outcomes) <= {"selected", "evaluation_prepare:no_decision", "evaluation:no_decision"}
        assert len(rig.facts(c.SELECTION)) == 1 + thinking_outcomes.count("selected")
        assert not rig.facts(c.STALE)
    finally: rig.close()
