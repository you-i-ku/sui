"""K16 concurrent store failures with production acquisition and update workers."""

from queue import Queue
from threading import Event

import pytest

from sui import fb, fb_contracts as c
from test_fb_acquisition_keep import AcquisitionKeepRig
from test_fb_loop import Scene17ConcurrentRead, row6_initial_ready, assert_keep_interruption


class ConcurrentAcquisitionRig(AcquisitionKeepRig):
    def __init__(self):
        super().__init__()
        self.workers.commands = Queue()
        self.first_source_ready, self.publish_first, self.worker_read_ready = Event(), Event(), Event()
        self.continue_source = Event()
        self.cleanup_releases.extend((self.publish_first, self.continue_source))
        read_source = self.source.read
        def read(cursor):
            if not self.source.calls:
                # Initial selection releases the normal source automatically.
                # Hold this first read until the setup driver has returned, so
                # it cannot consume the Frame before the cut is installed.
                self.first_source_ready.set()
                assert self.publish_first.wait(30), "first publication not released"
            elif len(self.source.calls) == 1:
                # A real acquisition Frame is now queued. The next FSource.read
                # is outside the host; this entered mouth can independently
                # read the store when the runner's E1 has unwound its operation.
                self.worker_read_ready.set()
                action, done, errors = self.workers.commands.get(timeout=30)
                port = next(iter(self.ports.values()))
                try: action(port.work, port)
                except BaseException as error: errors.append(error)
                finally: done.set()
                assert self.continue_source.wait(30), "source continuation not released"
            return read_source(cursor)
        self.source.read = read

    def close(self):
        # Also release an unconsumed command if setup failed before the cut.
        if self.workers.commands.empty():
            self.workers.commands.put((lambda _work, _ctx: None, Event(), self.post_errors))
        super().close()


def start_concurrent():
    rig = ConcurrentAcquisitionRig()
    try:
        assert rig.host.keep_running(lambda _s: row6_initial_ready(rig) and rig.first_source_ready.is_set(), timeout=60)
        rig.publish_first.set()
        rig.wait_returns(1)  # wait for production acquire, without pumping the host
        assert rig.worker_read_ready.wait(30), "second source read did not reach the worker gate"
        call, = rig.calls
        observed = rig.source_for(call)
        assert observed.frame_envelope is not None and observed.frame is None
        assert not rig.facts(c.SEGMENT_BINDING)
        return rig
    except BaseException:
        rig.close()
        raise


def test_row1_concurrent_store_error_retries_despite_a_later_worker_read_error():
    """K16(a): worker E2 cannot overwrite the runner's store E1 classification.

    Shared last-error state, a lost preparation, a duplicate effect, or counting
    E2 as another driver interruption fails the exact history and FIRST/SECOND.
    E1 is armed only after a native Frame is published and before its B exists;
    a Received note alone does not promise any ledger.record call. The second
    source read supplies E2. Exact E1/E2/rethrow order must fire, never a timeout
    that lets the source publish after the intended interleaving was missed.
    """
    rig, cut = start_concurrent(), None
    try:
        cut = Scene17ConcurrentRead(rig, "store")
        rig.continue_source.set()
        assert rig.host.keep_running(rig.complete, timeout=60)
        assert cut.order == ["runner store E1", "worker store E2", "runner rethrows E1"]
        assert cut.worker_caught == [cut.worker_error]
        rig.assert_loop(); cut.assert_fixed()
        interruption, = rig.host.interruptions()
        assert_keep_interruption(interruption, cut.runner_error, kind="store", count=1)
    finally:
        if cut is not None: cut.go.set()
        rig.close()


def test_row1_concurrent_nonstore_clock_error_still_halts_despite_worker_store_error():
    """K16(c): a later worker store E2 cannot turn Clock.now's E1 into storage.

    Retrying because a recent store call failed, writing after halt, or killing
    the already-entered measuring body fails these separate public witnesses.
    """
    rig, cut = start_concurrent(), None
    try:
        cut = Scene17ConcurrentRead(rig, "clock")
        before = rig.snapshot()
        rig.host.post(fb.Received(route_epoch="route-A", media_type="text/plain", data=b"clock trigger", claims={}))
        with pytest.raises(fb.FHalted) as caught:
            rig.host.keep_running(rig.complete, timeout=60)
        assert caught.value.__cause__ is cut.runner_error
        assert cut.order == ["runner clock E1", "worker store E2", "runner rethrows E1"]
        interruption, = rig.host.interruptions()
        assert_keep_interruption(interruption, cut.runner_error, kind="halted", count=1)
        assert rig.host.halted == interruption and rig.snapshot() == before
        assert rig.thread.is_alive()
        # Cleanup can finish an acquisition that was already in progress when
        # the host halted. FHalted remains an allowed worker-side stop then.
        rig.expected_errors = (fb.FHalted,)
    finally:
        if cut is not None: cut.go.set()
        rig.close()


def test_row1_concurrent_worker_read_error_is_not_a_driver_interruption():
    """Only a worker sees E2; treating it as a runner interruption fails empty history."""
    rig, cut = start_concurrent(), None
    try:
        cut = Scene17ConcurrentRead(rig, "worker_only")
        rig.continue_source.set()
        assert rig.host.keep_running(rig.complete, timeout=60)
        assert cut.order == ["worker store E2"] and cut.worker_caught == [cut.worker_error]
        rig.assert_loop(); cut.assert_fixed()
        assert rig.host.interruptions() == () and rig.host.halted is None
    finally:
        if cut is not None: cut.go.set()
        rig.close()
