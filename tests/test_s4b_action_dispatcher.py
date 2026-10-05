"""WaitDispatcher v0.19 §3-10-7; no sleeping, threads, disk, or real hand.

Each fake hand explicitly declares the test send point. Function entry and
the send point are different events. FakeClock and a bounded scripted waiter
make early wakeups and oversleep reproducible. Errors come from the hand and
must leave already emitted notices intact; their wrapping type is not fixed.
"""
import pytest

from s4b_action_cases import api, encoded


class EmptyResourceHand:
    def resources(self, action):
        return frozenset()


def fixture(*, now=100, threshold=110, wakes=(3, 2, 20)):
    from sui.clock import FakeClock
    from sui.contracts import ContractRef
    from sui.ids import Ref, RefKind
    from sui.runtime import Act
    run = Ref(RefKind.RUN, "dispatcher-contract")
    clock = FakeClock(run=run, mono_ns=now)
    dispatch = api("dispatch")
    cmd = dispatch.command_from_json(encoded({"action": "a", "choice": "a", "run": str(run),
        "not_before_ns": threshold, "reservation_rule": {"kind": "at", "not_before_ns": threshold},
        "dispatch": {"name": "wait-dispatch", "version": "1"},
        "effect": {"name": "start-impulse", "version": "2"}, "late": "send_when_ready",
        "causal_stage": 0, "causal_position": 0}))
    act = Act(attempt=Ref(RefKind.ATTEMPT, "attempt"), action="a", command=cmd)
    point = ContractRef("test.adapter.send-point", "1")
    waits, notices, events = [], [], []
    wakeups = iter(wakes)
    def wait(seconds):
        assert seconds > 0
        waits.append(seconds)
        events.append("wait")
        delta = next(wakeups, None)
        assert delta is not None, "dispatcher failed to finish after bounded fake wakeups"
        clock.advance(delta)
    def emit(notice):
        notices.append(notice)
        events.append(notice.kind)
    executor = dispatch.WaitDispatcher(clock=clock, wait=wait, point=point)
    result = dispatch.ActionResult(outcome="ok", effect_notice=None,
        measurement_reading_ns=None, completion_reading_ns=None)
    return clock, act, point, executor, result, emit, notices, waits, events


def test_wait_dispatcher_rereads_after_early_wakeup_and_records_actual_point_once():
    clock, act, point, executor, result, emit, notices, waits, events = fixture()
    class Hand(EmptyResourceHand):
        calls = 0
        def resources(self, action):
            return frozenset()
        def send(self, action, *, on_dispatched):
            self.calls += 1
            events.append("send-entry")
            assert action == "a" and clock.mono_ns() == 125
            assert [n.kind for n in notices] == ["receipt"]
            clock.advance(7)  # named physical point is later than function entry
            on_dispatched(clock.mono_ns())
            events.append("return")
            return result
    hand = Hand()
    assert executor.execute(act, hand, emit=emit) == result
    assert hand.calls == 1 and len(waits) == 3
    assert events == ["receipt", "wait", "wait", "wait", "send-entry", "dispatch", "return"]
    assert [n.reading_ns for n in notices] == [100, 132]
    assert notices[0].point is None and notices[1].point == point
    for notice in notices:
        assert notice.attempt == act.attempt and notice.command == act.command and notice.run == clock.run


@pytest.mark.parametrize("now,threshold", ((110, 110), (999, 110), (-5, -10)))
def test_wait_dispatcher_late_or_threshold_arrival_sends_without_extra_wait(now, threshold):
    clock, act, _, executor, result, emit, notices, waits, _ = fixture(now=now, threshold=threshold, wakes=())
    calls = []
    class Hand(EmptyResourceHand):
        def send(self, action, *, on_dispatched):
            calls.append(action)
            on_dispatched(clock.mono_ns())
            return result
    assert executor.execute(act, Hand(), emit=emit) == result
    assert calls == ["a"] and waits == []
    assert [(n.kind, n.reading_ns) for n in notices] == [("receipt", now), ("dispatch", now)]


@pytest.mark.parametrize("after_point", (False, True), ids=("before_send_point", "after_send_point"))
def test_wait_dispatcher_hand_exception_preserves_notices_and_never_retries(after_point):
    clock, act, _, executor, _, emit, notices, waits, _ = fixture(now=110, wakes=())
    calls = []
    failure = OSError("fixture hand failed")
    class Hand(EmptyResourceHand):
        def send(self, action, *, on_dispatched):
            calls.append(action)
            if after_point:
                on_dispatched(clock.mono_ns())
            raise failure
    with pytest.raises(Exception):
        executor.execute(act, Hand(), emit=emit)
    assert calls == ["a"] and waits == []
    assert [n.kind for n in notices] == (["receipt", "dispatch"] if after_point else ["receipt"])


def test_wait_dispatcher_does_not_invent_confirmation_when_hand_returns_without_point():
    _, act, _, executor, result, emit, notices, _, _ = fixture(now=110, wakes=())
    calls = []
    class Hand(EmptyResourceHand):
        def send(self, action, *, on_dispatched):
            calls.append(action)
            return result
    with pytest.raises(api("action_types").ActionRuntimeUnverified) as caught:
        executor.execute(act, Hand(), emit=emit)
    assert caught.value.reason == "dispatch_point"
    assert calls == ["a"] and [n.kind for n in notices] == ["receipt"]
