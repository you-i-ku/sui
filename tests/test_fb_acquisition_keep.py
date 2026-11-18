"""K28: keep_running alone advances production acquisition/update jobs.

The source is released by successful public store commits (initial selection,
then first adoption). No test pumps run_until to recover a failure; no script
calls acquire or posts a fabricated Frame/interval Claim. Other computing jobs
are still test workers, as K28 explicitly permits until the next book.
"""

from threading import Event, Thread, get_ident

import pytest

from sui import fb, fb_contracts as c
from test_fb_belief import BeliefSource, T, E
from test_fb_acquisition_loop import AcquisitionLoopRig
from test_fb_acquisition_store import assert_loop_effects
from test_fb_loop import (
    KeepStoreFault, Row1StoreCut, FIRST, SECOND, assert_update,
    assert_keep_interruption, execution_for, ORDER, ACQUIRED, CLOCK,
)
from test_fb_stage1 import wire


class AutomaticSource(BeliefSource):
    def read(self, cursor):
        index = len(self.calls)
        value = super().read(cursor)
        if index == 1:
            # The second read is already underway: stopping must not discard it.
            for measurer in self.rig.measurers.values(): measurer.stop()
        return value


class AcquisitionLauncher:
    """Only starts OS bodies; never advances the host from a worker/launcher."""
    def __init__(self, rig, unknown_update=False):
        self.rig, self.unknown_update = rig, unknown_update
        self.attempts, self.threads, self.launch_errors = [], [], []
        self.errors = rig.body_errors

    def launch(self, work_id, body):
        self.attempts.append((work_id, body))
        request = next(q for stage in (*ORDER, "measure_segment", "belief_update")
                       for q in self.rig.requests(stage) if q.value["desc"]["work_id"] == work_id)
        purpose = request.value["desc"]["purpose"]
        if self.unknown_update and purpose == "belief_update":
            error = OSError("launcher outcome is unknown, not a store operation")
            self.launch_errors.append(error)
            assert len(self.launch_errors) == 1, "unknown launch was retried"
            self.rig.source.release[1].set()  # independent measurement must progress
            raise error
        def invoke():
            try: body()
            except BaseException as error: self.errors.append(error)
        thread = Thread(target=invoke, daemon=True)
        self.threads.append(thread)
        if purpose == "measure_segment": self.rig.thread = thread
        thread.start()
        return "launched"


class AcquisitionKeepRig(AcquisitionLoopRig):
    def __init__(self, *, fault=None, unknown_update=False, hold_update=False, auto_source=True):
        self.thread, self.post_errors, self.seen = None, [], set()
        self.update_gate, self.update_posted = Event(), Event()
        def install(rig):
            rig.source = AutomaticSource(rig, (T, E))
            rig.launcher = AcquisitionLauncher(rig, unknown_update)
            rig.threads = rig.launcher.threads
            rig.oracle = Row1StoreCut(rig, "request", "observer", report_kind="frame")
            normal_add = rig.entry_store.add
            def observed_add(cid, header):
                result = normal_add(cid, header)
                if cid not in rig.seen:
                    rig.seen.add(cid)
                    record = rig.read_stored(cid)[2]
                    if auto_source and record.body.contract == c.SELECTION:
                        rig.source.release[0].set()
                    if auto_source and record.body.contract == c.BELIEF_ADOPTED:
                        rig.source.release[1].set()
                return result
            rig.entry_store.add = observed_add
            rig.fault = KeepStoreFault(rig, **(fault or {}))
        super().__init__(continuation=True, before_host=install, defer_boot=True)
        self.update_post_hook = lambda work, event: self.update_posted.set()
        if hold_update:
            def admitted(work, ctx, entered):
                if entered:
                    assert self.update_gate.wait(60), "held production update was not released"
            self.admission_hook = admitted
            self.cleanup_releases.append(self.update_gate)

    def complete(self, _status):
        if self.errors(): raise self.errors()[0]
        return len(self.facts(c.BELIEF_ADOPTED)) == 2 and len(self.facts(c.SELECTION)) == 3 and all(
            work.desc.purpose == "measure_segment" or work.desc.work_id in self.workers.stops
            for work in self.workers.entries)

    def assert_loop(self):
        assert self.complete(None)
        for thread in self.threads:
            thread.join(30)
            assert not thread.is_alive(), "production worker did not stop"
        adoptions = self.facts(c.BELIEF_ADOPTED)
        for adopted, expected, previous in ((adoptions[0], FIRST, None), (adoptions[1], SECOND, adoptions[0].cid)):
            assert_update(self, self.update_ports[adopted.value["request"]].work, adopted, expected, previous)
        assert_loop_effects(self, [])
        self.fault.assert_preparations()
        assert self.host.halted is None

    def snapshot(self):
        return tuple((cid, self.read_stored(cid)) for cid, _ in self.oracle.raw_load())

    def queue_note(self, label):
        # Legal independent data, rather than the retired MeasurementUnavailable.
        done = Event()
        try:
            self.workers.contexts["measure_segment"].post(fb.Received(
                route_epoch="route-A", media_type="text/plain", data=label.encode(), claims={}))
        except BaseException as error: self.post_errors.append(error)
        finally: done.set()
        return done


def test_keep_running_persistent_store_times_out_then_resumes_same_preparation():
    """A deadline is neither adoption nor abandonment; queued Post survives outage.

    Resetting interruption counts, inventing R/A, losing the probe or abandoning a
    preparation fails recovery. Only keep_running retries the failed store call.
    """
    rig = AcquisitionKeepRig(fault={"boundary": "before_body", "target": "result", "times": None}, hold_update=True)
    try:
        assert rig.host.keep_running(lambda _s: bool(rig.update_ports) and any(
            execution_for(rig.workers.contexts["measure_segment"], port.work.desc.work_id).entered == 1
            for port in rig.update_ports.values()), timeout=60) is True
        rig.update_gate.set()
        assert rig.update_posted.wait(30), "production updater did not post"
        assert rig.host.keep_running(rig.complete, timeout=1) is False
        assert len(rig.fault.raised) >= 2
        history = rig.host.interruptions()
        assert len(history) == 1
        assert_keep_interruption(history[0], rig.fault.raised[0], kind="store", count=len(rig.fault.raised))
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
        assert rig.host.halted is None and rig.thread.is_alive()
        probe = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"during outage", claims={})
        rig.host.post(probe)
        rig.fault.enabled = False
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop()
        assert len([r for r in rig.facts(c.RECEIVED) if r.value == wire(probe)]) == 1
        assert rig.host.interruptions() == history
    finally: rig.close()


def test_keep_running_halts_on_non_store_error_and_guards_every_advancing_entry():
    """Non-store RuntimeError halts; every advancing entry freezes, Post still works.

    Retrying by exception type, advancing after halt, or killing the active
    measuring worker before the TEST sends stop fails these public witnesses.
    """
    rig = AcquisitionKeepRig(fault={"boundary": "before_body", "exception_type": RuntimeError})
    try:
        with pytest.raises(fb.FHalted) as caught:
            rig.host.keep_running(rig.complete, timeout=60)
        assert len(rig.fault.raised) == 1 and caught.value.__cause__ is rig.fault.raised[0]
        halted = rig.host.halted
        assert_keep_interruption(halted, rig.fault.raised[0], kind="halted", count=1)
        assert halted.operation == "settle" and rig.host.interruptions()[-1] == halted
        assert halted.operation == "settle" and rig.host.interruptions()[-1] == halted
        before = rig.snapshot()
        probe = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"after halt", claims={})
        envelope = rig.envelope(10000, probe, rig.clock.peek())
        for advance in (lambda: rig.host.keep_running(lambda _s: True, timeout=0),
                        lambda: rig.host.run_until(lambda _s: True, timeout=0), rig.host.window.settle,
                        lambda: rig.host.window.accept(envelope)):
            with pytest.raises(fb.FHalted): advance()
            assert rig.snapshot() == before
        rig.host.post(probe)
        assert rig.queue_note("halted-worker-note").wait(30) and not rig.post_errors
        assert rig.thread.is_alive() and rig.snapshot() == before
        work, = (w for w in rig.workers.entries if w.desc.purpose == "measure_segment")
        observed = execution_for(rig.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.entered == 1 and not observed.stopped and any(r.point is None for r in observed.reports)
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    finally:
        # The TEST's cleanup stop may meet an already halted host at acquire.
        rig.expected_errors = (fb.FHalted,)
        rig.close()


def test_keep_running_clock_oserror_is_halted_not_misclassified_as_store():
    """Clock OSError after a real Frame binding is not a store failure.

    Using the exception class alone to recover fails halted/type/cause/history.
    """
    error = OSError("clock.now is not a store operation")
    rig, calls, caller = AcquisitionKeepRig(), [], get_ident()
    normal = rig.clock.now
    def fail_clock():
        frames = {r.cid for r in rig.facts(c.SEGMENT_REPORT) if r.value["item"]["kind"] == "frame"}
        ready = any(b.value["report"] in frames for b in rig.facts(c.SEGMENT_BINDING))
        if get_ident() == caller and ready and not rig.requests("belief_update") and not calls:
            calls.append(error)
            raise error
        return normal()
    rig.clock.now = fail_clock
    try:
        with pytest.raises(fb.FHalted) as caught: rig.host.keep_running(rig.complete, timeout=60)
        assert caught.value.__cause__ is error and calls == [error]
        assert_keep_interruption(rig.host.halted, error, kind="halted", count=1)
        assert all(i.kind != "store" for i in rig.host.interruptions())
    finally:
        rig.expected_errors = (fb.FHalted,)
        rig.close()


def test_keep_running_launcher_oserror_remains_unknown_and_measurement_can_report():
    """Launcher OSError stays unknown, while a second real acquisition saves.

    Store-retrying/halting/relaunching fails. K28 also forbids skipping the
    unknown first operation to create Q2; the later saved Frame must wait.
    """
    rig = AcquisitionKeepRig(unknown_update=True)
    try:
        def done(_s):
            return bool(rig.launcher.launch_errors) and any(r.value["item"]["kind"] == "frame"
                and r.value["item"]["value"]["sample_seq"] == 1 for r in rig.facts(c.SEGMENT_REPORT))
        assert rig.host.keep_running(done, timeout=60) is True
        assert len(rig.launcher.launch_errors) == 1 and rig.host.interruptions() == () and rig.host.halted is None
        request, = rig.requests("belief_update")
        wid = request.value["desc"]["work_id"]
        observed = execution_for(rig.workers.contexts["measure_segment"], wid)
        assert observed.launches == ("unknown",) and observed.entered == 0
        assert sum(key == wid for key, _ in rig.launcher.attempts) == 1
        assert not rig.facts(c.UPDATE_RESULT) and not rig.facts(c.BELIEF_ADOPTED)
    finally: rig.close()


class AcquisitionJumpRig(AcquisitionKeepRig):
    """Advance injected M at public source/body/store boundaries, without sleep."""
    def __init__(self, phase, jump_ns):
        super().__init__(hold_update=phase in ("running_update", "deadline"), auto_source=False)
        self.phase, self.jump_ns, self.jumps, self.expected_receipts = phase, jump_ns, [], []
        add = self.entry_store.add
        def observe(cid, header):
            result = add(cid, header)
            if phase == "result_saved" and not self.jumps:
                if self.read_stored(cid)[2].body.contract == c.UPDATE_RESULT:
                    assert not self.facts(c.BELIEF_ADOPTED)
                    self.jump("result_saved", cid)
            return result
        self.entry_store.add = observe

    def jump(self, boundary, point=None):
        assert not self.jumps, "the clock jump fired twice"
        before, fixed = self.clock.peek(), tuple(self.ledger.preparations)
        self.clock.set(before + self.jump_ns)
        assert self.clock.peek() - before == self.jump_ns
        self.jumps.append((boundary, point, before, self.clock.peek(), fixed))

    def release_operation(self, index):
        assert self.source.ready[index].wait(30), "source operation did not start"
        # The source is waiting at an Event; its only M advance is exactly +10.
        self.expected_receipts.append(self.clock.peek() + 10)
        self.source.release[index].set()
        self.wait_returns(index + 1)

    def start_first(self):
        assert self.host.keep_running(lambda _s: len(self.facts(c.SELECTION)) == 1
            and self.source.ready[0].is_set(), timeout=60) is True
        assert not self.requests("belief_update") and not self.facts(c.BELIEF_ADOPTED)
        if self.phase == "before_report": self.jump("before_report")
        self.release_operation(0)
        if self.phase == "after_report": self.jump("after_report")

    def held_update(self):
        def entered(_s):
            return bool(self.update_ports) and any(execution_for(
                self.workers.contexts["measure_segment"], port.work.desc.work_id).entered == 1
                for port in self.update_ports.values())
        assert self.host.keep_running(entered, timeout=60) is True
        port, = self.update_ports.values()
        self.assert_held(port.work)
        return port.work

    def assert_held(self, work):
        observed = execution_for(self.workers.contexts["measure_segment"], work.desc.work_id)
        assert observed.entered == 1 and not observed.stopped and not observed.reports
        assert observed.launches == ("launched",) and len(self.requests("belief_update")) == 1
        assert not [t for t in self.facts(c.WORK_TERMINAL) if t.value["request"] == work.request]
        assert not self.facts(c.UPDATE_RESULT) and not self.facts(c.BELIEF_ADOPTED)
        assert self.host.halted is None and self.host.interruptions() == ()

    def finish(self):
        assert self.host.keep_running(lambda _s: len(self.facts(c.BELIEF_ADOPTED)) == 1, timeout=60) is True
        if self.phase == "after_adoption": self.jump("after_adoption", self.one(c.BELIEF_ADOPTED).cid)
        self.release_operation(1)
        assert self.host.keep_running(self.complete, timeout=60) is True
        self.assert_loop()
        assert self.host.halted is None and self.host.interruptions() == ()
        assert len(self.jumps) == 1 and len(self.expected_receipts) == 2
        boundary, point, before, after, fixed = self.jumps[0]
        for prepared in fixed:
            assert self.read_stored(prepared.cid) == (prepared.header, prepared.salt, prepared.record)
            assert all(p == prepared for p in self.ledger.preparations if p.record.id == prepared.record.id)
        frames = []
        for call, expected_r in zip(self.calls, self.expected_receipts):
            pair = self.pair(call)
            assert pair is not None
            observation, raw = pair[1]
            assert observation.received_ns == raw.received_ns == expected_r <= raw.at_ns
            frames.append(raw)
        started, = (r for r in self.facts(c.SEGMENT_REPORT) if r.value["item"]["kind"] == "started")
        earlier, later = (started, frames[0]) if boundary == "before_report" else frames
        assert earlier.received_ns <= before and later.received_ns >= after
        assert later.received_ns - earlier.received_ns >= self.jump_ns
        for _cid, (_header, _salt, record) in self.snapshot():
            r = getattr(record.body, "received_ns", None)
            if r is not None: assert r <= record.at.mono_ns
        if boundary == "after_report":
            assert frames[0].at_ns - frames[0].received_ns >= self.jump_ns
        if boundary == "result_saved":
            adopted = self.facts(c.BELIEF_ADOPTED)[0]
            assert adopted.value["result"] == point and self.one(c.UPDATE_RESULT, cid=point).at_ns <= before
            assert adopted.at_ns >= after
            acquired = self.one(ACQUIRED, cid=adopted.value["acquisition"])
            assert self.one(CLOCK, cid=acquired.value["clock"]).value["reading"]["time_ns"] >= after
        if boundary == "after_adoption":
            assert self.facts(c.BELIEF_ADOPTED)[0].cid == point
            assert self.facts(c.BELIEF_ADOPTED)[0].at_ns <= before


@pytest.mark.parametrize(("boundary", "target", "times", "error_kind"), (
    ("before_body", "request", 1, "os"),
    ("before_body", "request", 3, "os"),
    ("after_body_commit", "result", 1, "os"),
    ("after_entry_commit", "adoption", 1, "os"),
    ("read", "result", 1, "os"),
    ("read", "result", 3, "os"),
    ("read", "result", 3, "sqlite"),
))
def test_keep_running_one_call_recovers_store_interruptions_without_extra_effects(boundary, target, times, error_kind):
    """K16 :3516 (1)-(4), CE1 :2917-2923: one keep_running call owns every retry.

    Escaping/stopping on a store error or losing a successor fails mandatory completion/FIRST/SECOND.
    Re-preparing/re-adopting/relaunching/redrawing/reacquiring fails the fixed-record/one-chain/effect witnesses.
    Missing/splitting/clearing interruption history fails its single entry/count and retained snapshot.
    """
    import sqlite3
    error_type = OSError if error_kind == "os" else sqlite3.OperationalError
    rig = AcquisitionKeepRig(fault={"boundary": boundary, "target": target, "times": times, "exception_type": error_type})
    try:
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop()
        assert len(rig.fault.raised) == times
        history = rig.host.interruptions()
        assert len(history) == 1
        assert_keep_interruption(history[0], rig.fault.raised[0], kind="store", count=times)
        assert rig.host.interruptions() == history
    finally:
        rig.close()


def test_keep_running_separates_identical_interruptions_after_a_successful_round():
    """K16 (4): Q1 and Q2 have identical store exceptions with successful rounds between them.

    Merging across success, splitting consecutive failures, or clearing on success fails two retained counts of three.
    """
    rig = AcquisitionKeepRig(fault={"boundary": "before_body", "times": 3, "each_update": True})
    try:
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop()
        assert len(rig.fault.raised) == 6 and len(rig.fault.selected) == 2
        first, second = rig.host.interruptions()
        for item in (first, second):
            assert_keep_interruption(item, rig.fault.raised[0], kind="store", count=3)
        assert (first.operation, first.error_type, first.message) == (second.operation, second.error_type, second.message)
        assert first.last_ns <= second.first_ns
        assert rig.host.interruptions() == (first, second)
    finally:
        rig.close()


@pytest.mark.parametrize("error_type", (OSError, RuntimeError))
def test_keep_running_done_exception_is_the_callers_and_does_not_halt(error_type):
    """K16 (2): done is outside recovery, including OSError and RuntimeError.

    Swallowing/retrying done or turning it into store/halted history fails exact propagation and later completion.
    """
    rig = AcquisitionKeepRig()
    error, calls = error_type("done belongs to the caller"), []
    try:
        def done(_s):
            calls.append(1)
            assert len(calls) == 1, "done was retried"
            raise error
        with pytest.raises(error_type) as caught:
            rig.host.keep_running(done, timeout=60)
        assert caught.value is error and calls == [1]
        assert rig.host.interruptions() == () and rig.host.halted is None
        assert rig.host.keep_running(rig.complete, timeout=60) is True
        rig.assert_loop()
    finally:
        rig.close()


def test_run_until_still_propagates_the_same_store_error_without_driver_history():
    """K16 (1): the legacy entry does not gain keep_running recovery semantics.

    Changing run_until into a retry loop fails exact propagation of its first store exception.
    """
    rig = AcquisitionKeepRig(fault={"boundary": "before_body", "target": "any", "times": 1})
    try:
        with pytest.raises(OSError) as caught:
            rig.host.run_until(lambda _s: False, timeout=0)
        assert len(rig.fault.raised) == 1 and caught.value is rig.fault.raised[0]
        assert rig.host.interruptions() == () and rig.host.halted is None
    finally:
        rig.close()


@pytest.mark.parametrize("jump_ns", (341 * 10**9, 8 * 60 * 60 * 10**9), ids=("341s", "8h"))
@pytest.mark.parametrize("phase", ("before_report", "after_report", "running_update", "result_saved", "after_adoption"))
def test_row8_forward_clock_jump_preserves_two_updates_receipt_times_and_effects(phase, jump_ns):
    """K18 :3518 (1)-(2), acceptance :486; advance injected M, without sleeping.
    
    CE1 :2917-2923: E1 weights=(1/8,1/32), mass=5/32, joint=(4/5,1/5).
    E1 AND E2 weights=(1/16,1/128), mass=9/128, joint=(8/9,1/9); M is not a likelihood.
    Treating a large forward M step as a host fault fails completion/empty interruptions/no halted.
    Discarding/rebuilding the update or recounting reports fails literal FIRST/SECOND, one chain and effect counts.
    Failing/marking unknown/aborting Wu by elapsed M fails the held no-terminal witness and eventual adoption.
    Reusing a pre-jump M for receipt fails independent pre-Post reads, EH/raw equality and r's jump-sized increase.

    K28: production T then E replace interval Claims. Receipt expectations come
    from the test clock and the source's +10 step, not the issued result.
    """
    rig = AcquisitionJumpRig(phase, jump_ns)
    try:
        rig.start_first()
        if phase == "running_update":
            work = rig.held_update()
            rig.jump("running_update", work.request)
            expected_r = rig.clock.peek()
            probe = fb.Received(route_epoch="route-A", media_type="text/plain", data=b"after forward jump", claims={})
            rig.host.post(probe)
            assert rig.host.keep_running(lambda _s: any(r.value == wire(probe) for r in rig.facts(c.RECEIVED)), timeout=60) is True
            received, = (r for r in rig.facts(c.RECEIVED) if r.value == wire(probe))
            assert received.received_ns == expected_r <= received.at_ns
            assert received.received_ns - rig.expected_receipts[0] >= jump_ns
            rig.assert_held(work)
            rig.update_gate.set()
        rig.finish()
    finally: rig.close()


@pytest.mark.parametrize("jump_ns", (341 * 10**9, 8 * 60 * 60 * 10**9), ids=("341s", "8h"))
def test_row8_keep_running_deadline_preserves_entered_update_for_the_next_call(jump_ns):
    """K18 (3), K16 (5): timeout=0 observes the caller's deadline, separate from injected M.
    
    Treating False as failure/unknown/abandonment fails the still-entered same Q* and no T/R*/A* witness.
    Rebuilding/relaunching on the next call fails the unchanged Q*, FIRST/SECOND, chain and exact effect counts.
    No elapsed wall-time assertion or time.monotonic replacement is used; reverse-M control is row6's clock-fault test.

    K28: production T then E replace interval Claims. Receipt expectations come
    from the test clock and the source's +10 step, not the issued result.
    """
    rig = AcquisitionJumpRig("deadline", jump_ns)
    try:
        rig.start_first()
        work = rig.held_update()
        rig.jump("deadline", work.request)
        assert rig.host.keep_running(lambda _s: False, timeout=0) is False
        rig.assert_held(work)
        rig.update_gate.set()
        rig.finish()
    finally: rig.close()
