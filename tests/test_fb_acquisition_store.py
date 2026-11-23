"""K28 migration: the real acquisition loop crosses temporary store failures.

The public ledger/store cuts are retained from rows 1/2. SourceMeasurer creates
every Frame and FiniteUpdater computes every update. A test forwarding port holds
each returned acquisition: Started Post and source.read have reached their public
barriers before runner rounds, and Ended cannot race a measured read interval.
All non-measuring callbacks run synchronously between zero-time host rounds.
No script calls acquire, fabricates a Frame, or posts an interval Claim.

R1 fixed preparation; R2 mandatory successors; R3 no extra external effects are
checked separately. A requested cut that never fires FAILS; no skip/retry-to-green.
"""

from threading import Thread
from dataclasses import replace

import pytest

from sui import fb, fb_contracts as c
from test_fb_acquisition_loop import AcquisitionLoopRig
from test_fb_loop import (
    Row2AckLoss, Row2Driver, Row1StoreCut, Row1IntervalCut, Row1FirstWriteAttempt,
    FIRST, SECOND, ACQUIRED, CLOCK, ROUTE, CG, ORDER, assert_update,
    execution_for, row5_report_for_work,
)
from test_fb_skeleton import contract


class AcquisitionFaultRig(AcquisitionLoopRig):
    def __init__(self, cut_factory, *, capacity=None, **kwargs):
        def install(rig):
            rig.cut = cut_factory(rig)
            if capacity is not None:
                rig.boot_input = replace(rig.boot_input, declaration=replace(rig.boot_input.declaration,
                    capacity=fb.QuantityValue(contract=c.SEATS, value=capacity)))
        super().__init__(continuation=True, before_host=install, defer_boot=True, **kwargs)
        self.hold_return = True
        self.return_waiting, self.return_released = [], []

    def hold_acquire_return(self, call):
        """An intentional phase barrier, released by publish_operation/close.

        Its lifetime includes arbitrary host evaluation/storage work. A wall
        timeout here turns slow correct work into a worker exception. The
        source/start/join watchdogs still diagnose failures to reach a phase;
        AcquireRig.close always sets return_release before joining workers.
        """
        with self.changed:
            self.return_waiting.append(call.sequence)
            self.changed.notify_all()
        self.return_release.wait()
        with self.changed:
            self.return_released.append(call.sequence)
            self.changed.notify_all()

    def publish_operation(self, index):
        """Release only the source. Production code calls the actual acquire()."""
        if index:
            self.return_release.set()
        assert self.source.ready[index].wait(30), "production source read did not start"
        self.return_release.clear()
        if index == len(self.source.symbols) - 1:
            self.measurers[self.measure_key].stop()
        self.source.release[index].set()
        self.wait_returns(index + 1)
        return self.calls[index]


class AcquisitionFaultDriver(Row2Driver):
    """Test-owned manual re-entry. The store exception remains observable to us."""
    def __init__(self, rig, cut, on_loss):
        super().__init__(rig, cut, on_loss)
        self.executed = rig.executed

    def drive(self, predicate, **kwargs):
        self.cut.in_host = True
        try:
            return super().drive(predicate, **kwargs)
        finally:
            self.cut.in_host = False

    def handle_loss(self):
        # A test/source callback is not a runner read-back confirmation.
        previous = self.cut.in_host
        self.cut.in_host = False
        try:
            return super().handle_loss()
        finally:
            self.cut.in_host = previous

    def advance_until(self, predicate):
        def pending():
            return [(key, body) for key, body in self.rig.launcher.attempts if key not in self.executed]
        while not predicate():
            self.drive(lambda: predicate() or bool(pending()))
            if predicate(): return
            work_id, body = pending()[0]
            assert sum(key == work_id for key, _ in self.rig.launcher.attempts) == 1, "R3: duplicate launch"
            self.executed.add(work_id)
            request = next(q for stage in (*ORDER, "measure_segment", "belief_update")
                           for q in self.rig.requests(stage) if q.value["desc"]["work_id"] == work_id)
            if request.value["desc"]["purpose"] == "measure_segment":
                def invoke(body=body):
                    try: body()
                    except BaseException as error: self.rig.body_errors.append(error)
                thread = Thread(target=invoke, daemon=True)
                self.rig.threads.append(thread)
                self.rig.measure_key = work_id
                thread.start()
                assert self.rig.source.ready[0].wait(30), "Started/source barrier was not reached"
            else:
                body()


def assert_loop_effects(rig, route_before):
    """R2/R3: one chain and one body/launch/draw/acquisition/application per use."""
    adoptions = rig.facts(c.BELIEF_ADOPTED)
    assert len(adoptions) == 2 and [a.value["previous"] for a in adoptions] == [None, adoptions[0].cid]
    assert len(rig.requests("belief_update")) == len(rig.facts(c.UPDATE_RESULT)) == 2
    assert len(rig.requests("evaluation_prepare")) == len(rig.facts(c.PREPARED)) == 3
    assert len(rig.requests("selection_draw")) == len(rig.facts(contract("sui.f.draw_fact"))) == 3
    assert len(rig.requests("evaluation")) == len(rig.facts(c.EVALUATED)) == 3
    assert len(rig.facts(CG)) == 1 and not rig.facts(c.STALE)
    assert len(rig.workers.entries) == len(rig.launcher.attempts) == 13, "R3: extra body/launch"
    ctx = rig.workers.contexts["measure_segment"]
    for work in rig.workers.entries:
        assert [ok for key, ok in rig.workers.entry_attempts if key == work.desc.work_id] == [True]
        observed = execution_for(ctx, work.desc.work_id)
        assert observed.entered == 1 and observed.launches == ("launched",)
        terminals = [t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
        assert len(terminals) <= 1
        if work.desc.purpose not in ("measure_segment", "selection_draw"):
            assert len(terminals) == 1
            assert len([r for r in rig.facts(c.WORK_REPORT) if r.value["work"] == work.desc.work_id]) == 1
    assert len([event for event, _ in rig.workers.sent if isinstance(event, fb.DrawReturned)]) == 3
    for result in rig.facts(c.UPDATE_RESULT):
        acquired = [a for a in ctx.evidence().acquisitions if result.cid in a.contents]
        assert len(acquired) == 1, "R3: repeated result acquisition"
        saved, = (g for g in rig.facts(ACQUIRED) if result.cid in g.value["contents"])
        assert rig.one(CLOCK, cid=saved.value["clock"]).value["reading"]["time_ns"] == acquired[0].acquired_ns
    route, = rig.facts(ROUTE)
    if route_before: assert [route] == route_before
    preparations = [p for p in rig.ledger.preparations if p.record.body.contract == ROUTE]
    assert preparations and all(p == preparations[0] for p in preparations), "R3: route/time resampled"
    assert len(rig.calls) == 2 and len(rig.source.calls) == 2, "R3: extra source operation"
    assert [call.acquired.outcome for call in rig.calls] == ["taken", "empty"]
    assert len(ctx.evidence().sources) == 2


def complete_fault_scene(rig, *, on_loss=None, during_loss=False):
    """Fixed external schedule for baseline and cut; no internal window state."""
    cut, second = rig.cut, {}
    route_before = rig.facts(ROUTE)
    def loss():
        if on_loss is not None: on_loss()
        if "measure_segment" in rig.workers.contexts:
            rig.clock.set(rig.clock.peek() + 10)
        if during_loss:
            second["call"] = rig.publish_operation(1)
            observations = execution_for(second["call"].port, second["call"].work.desc.work_id).reports
            own = [o for o in observations if o.envelope in second["call"].envelopes]
            assert own and all(o.point is None for o in own)
            # A prepared Q* is not yet a saved request. Before its first entry
            # commit the public saved-request count is zero, including a body
            # commit whose acknowledgement was lost before AddEntry.
            request_not_committed = cut.target == "request" and (
                getattr(cut, "operation", None) in ("before_body", "before_entry")
                or getattr(cut, "boundary", None) == "after_body_commit")
            assert len(rig.requests("belief_update")) == (0 if request_not_committed else 1)
            if on_loss is not None and isinstance(cut, Row2AckLoss):
                assert not cut.confirmed
                if cut.boundary == "after_entry_commit":
                    before = dict(rig.entry_store.load())
                    rig.host.rebuild_window()
                    assert dict(rig.entry_store.load()) == before
    driver = AcquisitionFaultDriver(rig, cut, loss)
    driver.advance_until(lambda: len(rig.facts(c.SELECTION)) == 1 and rig.source.ready[0].is_set())
    first = rig.publish_operation(0)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) >= 1)
    a1 = rig.facts(c.BELIEF_ADOPTED)[0]
    w1 = rig.update_ports[a1.value["request"]].work
    r1 = assert_update(rig, w1, a1, FIRST)
    if "call" not in second: second["call"] = rig.publish_operation(1)
    driver.advance_until(lambda: len(rig.facts(c.BELIEF_ADOPTED)) == 2 and len(rig.facts(c.SELECTION)) == 3)
    a2 = rig.facts(c.BELIEF_ADOPTED)[1]
    w2 = rig.update_ports[a2.value["request"]].work
    assert_update(rig, w2, a2, SECOND, a1.cid)
    for work, call in ((w1, first), (w2, second["call"])):
        pair = rig.pair(call)
        assert pair is not None
        assert row5_report_for_work(rig, work).cid == pair[1][1].cid
    assert_loop_effects(rig, route_before)
    assert not rig.errors(), rig.errors()
    return driver, w1, a1, r1


def finish_precommit_scene(rig):
    cut = rig.cut
    def loss():
        assert cut.hits == 1
        if cut.operation in ("before_body", "before_entry"):
            assert cut.prepared.cid not in cut.headers_at_loss
            present = cut.entry_from_header(cut.prepared.cid, cut.prepared.header).seal in cut.seals_at_loss
            assert present == (cut.operation == "before_entry")
    driver, _work, _a, _r = complete_fault_scene(rig, on_loss=loss,
        during_loss=cut.target == "request" and cut.ordinal == 1)
    assert cut.hits == 1, f"UNFIRED {cut.target}/{cut.operation}/{cut.read_occurrence}"
    assert driver.handled and driver.calls > driver.call_at_loss and cut.confirmed
    cut.assert_fixed_preparations()


@pytest.mark.parametrize("boundary", ("after_body_commit", "after_entry_commit"))
@pytest.mark.parametrize("target", ("request", "terminal", "result", "acquisition_clock",
                                    "acquisition", "adoption", "continuation_request"))
def test_row2_committed_write_ack_loss_keeps_one_record_and_one_ce1_adoption_chain(target, boundary):
    """Lost acknowledgments retain exact preparations and one FIRST->SECOND chain.

    New IDs/times, skipping pending A*, stuck retry or duplicate application fails.
    During A* uncertainty the next production acquisition publishes but Q2 waits;
    after_entry_commit also rebuilds the public window before confirmation.
    """
    rig = AcquisitionFaultRig(lambda r: Row2AckLoss(r, target, boundary))
    try:
        # The cut must not mistake an initial thinking terminal/request for Wu.
        cut = rig.cut
        normal_matches = cut.matches
        def matches(prepared):
            if target == "terminal":
                v = prepared.record.body.content.as_json()
                return prepared.record.body.contract == c.WORK_TERMINAL and v.get("request") in {
                    q.cid for q in rig.requests("belief_update")}
            if target == "continuation_request":
                if prepared.record.body.contract != c.EVALUATION_REQUESTED: return False
                return any(t["point"] in {a.cid for a in rig.facts(c.BELIEF_ADOPTED)}
                           for t in prepared.record.body.content.as_json()["desc"]["trigger"])
            return normal_matches(prepared)
        cut.matches = matches
        driver, work, adopted, result = complete_fault_scene(rig,
            on_loss=cut.assert_commit_at_loss, during_loss=target == "adoption")
        terminal, = (t for t in rig.facts(c.WORK_TERMINAL) if t.value["request"] == work.request)
        acquired = rig.one(ACQUIRED, cid=adopted.value["acquisition"])
        actual = {"request": work.request, "terminal": terminal.cid, "result": result.cid,
            "acquisition_clock": acquired.value["clock"], "acquisition": acquired.cid,
            "adoption": adopted.cid, "continuation_request": rig.requests("evaluation_prepare")[1].cid}[target]
        assert actual == cut.prepared.cid and driver.handled and cut.failed and cut.confirmed
        assert driver.calls > driver.call_at_loss and rig.faults.observed == [boundary]
        assert cut.attempts and all(p == cut.prepared for p in cut.attempts)
        assert rig.read_stored(actual) == (cut.prepared.header, cut.prepared.salt, cut.prepared.record)
        same = [p for p in rig.ledger.preparations if p.record.body.contract == cut.ref and p.parents == cut.prepared.parents]
        assert same and all(p == cut.prepared for p in same)
        assert [f.cid for f in rig.facts(cut.ref) if f.parents == cut.prepared.parents] == [actual]
    finally: rig.close()


@pytest.mark.parametrize("operation", ("before_body", "before_entry"))
@pytest.mark.parametrize("target", ("report", "binding", "request", "work_report", "terminal", "result",
                                    "acquisition_clock", "acquisition", "adoption", "continuation_request"))
def test_row1_precommit_failure_reenters_same_ce1_loop_without_extra_effects(target, operation):
    """R1 exact prepared bytes; R2 mandatory Q/R/A/selection; R3 no extra effects.

    Stuck successor, regenerated preparation or repeated entry/draw/acquisition fails.
    The report target is now the host's acquisition Frame, not a producer Claim.
    """
    rig = AcquisitionFaultRig(lambda r: Row1StoreCut(r, target, operation, report_kind="frame"))
    try: finish_precommit_scene(rig)
    finally: rig.close()


@pytest.mark.parametrize("read_occurrence", (1, 2))
@pytest.mark.parametrize("operation", ("entry", "record", "body"))
@pytest.mark.parametrize("target", ("report", "binding", "request", "work_report", "terminal", "result",
                                    "acquisition_clock", "acquisition", "adoption", "continuation_request"))
def test_row1_public_host_read_failure_reenters_same_ce1_loop_without_extra_effects(target, operation, read_occurrence):
    """Each requested public runner read fails once; oracle/worker reads never do.

    Missing successor, changed preparation or repeated external effects fails R1-3.
    """
    rig = AcquisitionFaultRig(lambda r: Row1StoreCut(r, target, operation,
        read_occurrence=read_occurrence, report_kind="frame"))
    try: finish_precommit_scene(rig)
    finally: rig.close()


@pytest.mark.parametrize("target", ("boot", "candidate", "prepare", "draw", "evaluate"))
def test_row1_boot_and_initial_thinking_read_failure_still_complete_both_continuations(target):
    """A Boot/thinking read cut must recover through BOTH adopted continuations.

    A missing successor or re-sampling/relaunching/redrawing fails R1-3.
    """
    rig = AcquisitionFaultRig(lambda r: Row1StoreCut(r, target, "body", report_kind="frame"))
    try: finish_precommit_scene(rig)
    finally: rig.close()


def test_row1_second_update_precommit_failure_keeps_adopted_prior_and_one_chain():
    """Fail Q2 with a non-None prior: a fork, stuck retry or duplicate use fails."""
    rig = AcquisitionFaultRig(lambda r: Row1StoreCut(r, "request", "before_body", ordinal=2, report_kind="frame"))
    try: finish_precommit_scene(rig)
    finally: rig.close()


@pytest.mark.parametrize(("target", "operation", "read_occurrence"), (
    ("candidates", "body", 2), ("prepared", "body", 2),
    ("draw_report", "body", 2), ("route", "body", 2),
))
def test_row1_saved_boot_and_thinking_inputs_read_failure_preserves_the_loop(target, operation, read_occurrence):
    """Saved CG/PR/draw/route read failures retain R1-3 and three selections."""
    rig = AcquisitionFaultRig(lambda r: Row1StoreCut(r, target, operation,
        read_occurrence=read_occurrence, report_kind="frame"))
    try: finish_precommit_scene(rig)
    finally: rig.close()


def make_interval_rig(flow, lap, left, right, k, *, prewrite=False):
    rig = AcquisitionFaultRig(lambda r: Row1IntervalCut(r, flow, lap, left, right, k, report_kind="frame"))
    if prewrite: rig.prewrite = Row1FirstWriteAttempt(rig)
    return rig


def complete_interval_scene(rig, *, inject):
    driver, _w, _a, _r = complete_fault_scene(rig)
    cut = rig.cut
    points = cut.saved_points()
    assert set(cut.committed) == {cid for cid, _ in cut.raw_load()}
    assert cut.left in points and cut.right in points, "R2: missing interval successor"
    if inject:
        assert cut.hits == 1, f"UNFIRED_TAIL {cut.target}; available_reads={len(cut.reads)}"
        assert driver.handled and driver.calls > driver.call_at_loss and cut.confirmed
        assert len(cut.reads) == cut.k and points[cut.left] == cut.left_at_loss
        cut.assert_fixed_preparations()


# Profiles are acquired by the TEST BODY, so missing public API fails per case,
# not in collection or a session-wide fixture. A successful baseline is cached
# once, exactly as the former module fixture; a missed cut never triggers a new one.
_profiles = {}


def measured_profile(scene, *, prewrite=False, minimum=None):
    key = (prewrite, *scene)
    if key not in _profiles:
        rig = make_interval_rig(*scene, None, prewrite=prewrite)
        try:
            complete_interval_scene(rig, inject=False)
            if prewrite: rig.prewrite.assert_boundary(inject=False)
            count = len(rig.cut.reads)
            _profiles[key] = (*scene, count)
        finally: rig.close()
    required = minimum if minimum is not None else ((12 if scene[-1] == "request" else 4) if prewrite else 3)
    assert _profiles[key][-1] >= required, f"BASELINE_TOO_SHORT {scene}: {_profiles[key][-1]} < {required}"
    return _profiles[key]


def check_interval_target(profile, k, *, prewrite=False):
    rig = make_interval_rig(*profile[:-1], k, prewrite=prewrite)
    try:
        try:
            complete_interval_scene(rig, inject=True)
        except AssertionError as error:
            if rig.cut.hits == 0:
                label = "UNFIRED_PREWRITE" if prewrite else "UNFIRED_TAIL"
                raise AssertionError(f"{label} {profile[:-1]}; baseline={profile[-1]}, "
                                     f"target={k}, available={len(rig.cut.reads)}; {error}") from None
            raise
        if prewrite:
            rig.prewrite.assert_boundary(inject=True)
            assert rig.cut.k == k
    finally: rig.close()


@pytest.fixture(scope="module")
def row1_tail_profile(request):
    return request.param


@pytest.fixture(scope="module")
def row1_prewrite_profile(request):
    return request.param


@pytest.mark.parametrize(("flow", "lap", "left", "right"), (
    ('initial', 1, 'candidate_request', 'candidate_report'),
    ('initial', 1, 'candidate_report', 'candidates'),
    ('initial', 1, 'candidates', 'prepare_request'),
    ('initial', 1, 'prepare_request', 'prepare_report'),
    ('initial', 1, 'prepare_report', 'prepared'),
    ('initial', 1, 'prepared', 'draw_request'),
    ('initial', 1, 'draw_request', 'draw_report'),
    ('initial', 1, 'draw_report', 'draw_fact'),
    ('initial', 1, 'draw_fact', 'evaluate_request'),
    ('initial', 1, 'evaluate_request', 'evaluate_report'),
    ('initial', 1, 'evaluate_report', 'evaluated'),
    ('initial', 1, 'evaluated', 'selection'),
    ('update', 1, 'report', 'binding'),
    ('update', 1, 'binding', 'request'),
    ('update', 1, 'request', 'work_report'),
    ('update', 1, 'work_report', 'terminal'),
    ('update', 1, 'terminal', 'result'),
    ('update', 1, 'result', 'acquisition_clock'),
    ('update', 1, 'acquisition_clock', 'acquisition'),
    ('update', 1, 'acquisition', 'adoption'),
    ('update', 1, 'adoption', 'continuation_request'),
    ('update', 2, 'binding', 'request'),
    ('update', 2, 'acquisition', 'adoption'),
))
def test_row1_read_between_saved_public_transitions_reenters_without_losing_or_duplicating_successors(flow, lap, left, right):
    """K16/PrepareOne: recover each of the measured first up-to-three reads.

    The paper does not promise three reads in an interval. Measure the same
    externally synchronized baseline once, then target 1..min(3,N), without
    rebuilding a profile, skipping, or changing a target after a missed cut.
    N=0 is an explicit BASELINE_TOO_SHORT fixture limit, never a fault pass.
    A shorter fault walk still fails UNFIRED_TAIL. Lost successors fail R2;
    changed fixed preparation or duplicate effects fail R1/R3 as before.
    """
    profile = measured_profile((flow, lap, left, right), minimum=1)
    for k in range(1, min(3, profile[-1]) + 1):
        check_interval_target(profile, k)


@pytest.mark.parametrize("from_end", (0, 1, 2), ids=("last", "last-minus-1", "last-minus-2"))
@pytest.mark.parametrize("row1_tail_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
    pytest.param(("update", 1, "work_report", "terminal"), id="update1-report-terminal"),
    pytest.param(("update", 2, "work_report", "terminal"), id="update2-report-terminal"),
    pytest.param(("update", 1, "terminal", "result"), id="update1-terminal-result"),
    pytest.param(("update", 2, "terminal", "result"), id="update2-terminal-result"),
    pytest.param(("update", 1, "acquisition", "adoption"), id="update1-acquisition-adoption"),
    pytest.param(("update", 2, "acquisition", "adoption"), id="update2-acquisition-adoption"),
    pytest.param(("update", 1, "adoption", "continuation_request"), id="update1-adoption-continuation"),
    pytest.param(("update", 2, "adoption", "continuation_request"), id="update2-adoption-continuation"),
    pytest.param(("initial", 1, "candidate_report", "candidates"), id="initial-report-candidates"),
    pytest.param(("initial", 1, "candidates", "prepare_request"), id="initial-candidates-prepare"),
    pytest.param(("initial", 1, "prepare_report", "prepared"), id="initial-report-prepared"),
    pytest.param(("initial", 1, "draw_fact", "evaluate_request"), id="initial-draw-evaluate"),
    pytest.param(("initial", 1, "evaluate_report", "evaluated"), id="initial-report-evaluated"),
), indirect=True)
def test_row1_interval_tail_reads_reenter_without_losing_or_duplicating_successors(row1_tail_profile, from_end):
    """F-b :323-327,3328-3332,3437,3509-3513; CE1 :2917-2923; v2 :19,31.
    
    A lost request/terminal successor after a late read fails R2's bounded mandatory progression.
    New preparation/time/boundary fails R1; duplicate successors or external effects fail R2/R3.
    Select N, N-1, N-2 from this scene's fault-free count; a shorter fault walk fails UNFIRED_TAIL.
    Positions are relative to the measured baseline, never silently recalibrated or skipped after a miss.
    Completed Started Post plus single host rounds fix the external schedule in both walks.
    The position is the kth outer public read between the same named saved-record boundaries,
    not a CID selected from a different execution. It is chosen once; ending the interval before k fails.

    K28: two production acquisitions replace Claims; a forwarding-return/source
    barrier fixes the external schedule. No position is recalibrated after a miss.
    """
    profile = measured_profile(row1_tail_profile)
    check_interval_target(profile, profile[-1] - from_end)


@pytest.mark.parametrize("row1_tail_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
), indirect=True)
def test_row1_interval_middle_read_reenters_without_losing_the_update_request(row1_tail_profile):
    """Use the measured midpoint ceil(N/2) as well as the tail for the two B -> Q* intervals.
    
    Losing Q* after this read fails R2; replacing a preparation or repeating work/acquisition fails R1/R3.
    The same Started-Post barrier and host rounds fix the schedule; the measured kth position is never retargeted.

    K28: two production acquisitions replace Claims; a forwarding-return/source
    barrier fixes the external schedule. No position is recalibrated after a miss.
    """
    profile = measured_profile(row1_tail_profile)
    check_interval_target(profile, (profile[-1] + 1) // 2)


@pytest.mark.parametrize("from_end", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))
@pytest.mark.parametrize("row1_prewrite_profile", (
    pytest.param(("update", 1, "binding", "request"), id="update1-binding-request"),
    pytest.param(("update", 2, "binding", "request"), id="update2-binding-request"),
), indirect=True)
def test_row1_before_first_request_put_last_twelve_reads_keep_the_update_chain(row1_prewrite_profile, from_end):
    """F-b PrepareOne/PutBody :324-325, update request :3328, K13 :3513; CE1 :2917-2923.
    
    A lost Q* after a read before its first put fails R2's mandatory successors, even if no write was attempted.
    Replacing a fixed preparation or duplicating a successor fails R1/R2; repeated external effects fail R3.
    Count N before the first physical put/add, then inject N..N-11; UNFIRED is a failure, never a late injection.
    Completed Started Post and one-round calls fix both walks' external schedule. The position is
    the kth outer read from the named saved left record to the right record's first physical put/add.
    No new baseline or second fault walk is allowed after a miss; a shorter walk still fails UNFIRED.

    K28: two production acquisitions replace Claims; a forwarding-return/source
    barrier fixes the external schedule. No position is recalibrated after a miss.
    """
    profile = measured_profile(row1_prewrite_profile, prewrite=True)
    check_interval_target(profile, profile[-1] - from_end, prewrite=True)


@pytest.mark.parametrize("from_end", (0, 1, 2, 3))
@pytest.mark.parametrize("row1_prewrite_profile", (
    pytest.param(("initial", 1, "candidate_report", "candidates"), id="initial-report-candidates"),
    pytest.param(("initial", 1, "evaluate_report", "evaluated"), id="initial-report-evaluated"),
    pytest.param(("update", 1, "work_report", "terminal"), id="update1-report-terminal"),
    pytest.param(("update", 1, "acquisition", "adoption"), id="update1-acquisition-adoption"),
), indirect=True)
def test_row1_before_first_successor_put_last_four_reads_preserve_progress(row1_prewrite_profile, from_end):
    """F-b :323-327,3330-3332,3442-3444,3509: the permitted four-position smaller range.
    
    A missing CG/EV/T/A* after a pre-put read fails R2; duplicate records or repeated work/acquisition fail R1/R2/R3.
    The fixed Started-Post/host-round schedule identifies the measured kth read before first put; misses still fail UNFIRED.

    K28: two production acquisitions replace Claims; a forwarding-return/source
    barrier fixes the external schedule. No position is recalibrated after a miss.
    """
    profile = measured_profile(row1_prewrite_profile, prewrite=True)
    check_interval_target(profile, profile[-1] - from_end, prewrite=True)
