from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from sui.clock import ClockError, CrossRunError, FakeClock, Instant, SystemClock
from sui.clock import elapsed_ns, precedes, seconds, wall_gap_ns
from sui.ids import Ref, RefKind as K, WrongKind


@pytest.fixture
def clk():
    return FakeClock(run=Ref(K.RUN, "r1"))


def test_c1_fake_clock_advances_both_times(clk):
    a = clk.now()
    clk.advance(1_500_000_000)
    b = clk.now()
    assert elapsed_ns(a, b) == 1_500_000_000
    assert b.wall_ns - a.wall_ns == 1_500_000_000
    assert seconds(elapsed_ns(a, b)) == 1.5
    assert elapsed_ns(b, a) == -1_500_000_000


def test_c2_sequence_orders_equal_times(clk):
    a, b, c = (clk.now() for _ in range(3))
    assert [a.seq, b.seq, c.seq] == [1, 2, 3]
    assert a.mono_ns == b.mono_ns == c.mono_ns == 0
    assert a.wall_ns == b.wall_ns == c.wall_ns == 1_790_000_000_000_000_000
    assert a.seq == 1
    assert not hasattr(a, "order_key")
    assert precedes(a, b) and precedes(b, c)
    assert not precedes(b, a) and not precedes(a, a)
    assert clk.run == Ref(K.RUN, "r1") and clk.run_index == 0


def test_c3_wall_jump_does_not_change_elapsed(clk):
    a = clk.now()
    clk.advance(10_000_000_000)
    clk.set_wall(a.wall_ns - 3_600_000_000_000)
    b = clk.now()
    assert elapsed_ns(a, b) == 10_000_000_000
    assert wall_gap_ns(a, b) == -3_600_000_000_000
    clk.set_wall(a.wall_ns + 7_200_000_000_000)
    c = clk.now()
    assert c.mono_ns == b.mono_ns
    assert wall_gap_ns(a, c) == 7_200_000_000_000


def test_c4_cross_run_order_and_wall_gap():
    wall = 1_790_000_000_000_000_000
    a = FakeClock(run=Ref(K.RUN, "r1"), run_index=0, mono_ns=5_000_000_000_000, wall_ns=wall).now()
    b = FakeClock(run=Ref(K.RUN, "r2"), run_index=1, mono_ns=1_000_000_000,
                  wall_ns=wall - 100_000_000_000).now()
    with pytest.raises(CrossRunError):
        elapsed_ns(a, b)
    with pytest.raises(CrossRunError):
        precedes(a, b)
    with pytest.raises(CrossRunError):
        precedes(b, a)
    assert wall_gap_ns(a, b) == -100_000_000_000


@pytest.mark.parametrize("change", [
    {"run_index": 1}, {"run_index": 1, "seq": 2}, {"mono_ns": 1}, {"wall_ns": 1},
])
def test_c5_inconsistent_order_is_rejected(clk, change):
    a = clk.now()
    b = replace(a, **change)
    with pytest.raises(ClockError) as forward:
        precedes(a, b)
    assert type(forward.value) is ClockError
    with pytest.raises(ClockError) as backward:
        precedes(b, a)
    assert type(backward.value) is ClockError


@pytest.mark.parametrize("value, error", [(-1, ValueError), (True, TypeError), (1.0, TypeError), ("1", TypeError)])
def test_c6_invalid_advance_is_atomic(clk, value, error):
    before = clk.now()
    with pytest.raises(error):
        clk.advance(value)
    after = clk.now()
    assert (after.mono_ns, after.wall_ns) == (before.mono_ns, before.wall_ns)
    assert after.seq == before.seq + 1


@pytest.mark.parametrize("change, error", [
    ({"seq": 0}, ValueError), ({"run_index": -1}, ValueError),
    ({"seq": True}, TypeError), ({"run_index": True}, TypeError),
    ({"mono_ns": True}, TypeError), ({"wall_ns": True}, TypeError),
    ({"run": Ref(K.JOB, "x")}, WrongKind), ({"run": "r1"}, TypeError),
])
def test_c6_instant_arguments(clk, change, error):
    with pytest.raises(error):
        replace(clk.now(), **change)


def test_c6_clock_arguments_and_negative_origins(clk):
    with pytest.raises(WrongKind):
        FakeClock(run=Ref(K.JOB, "x"))
    with pytest.raises(ValueError):
        SystemClock(run=Ref(K.RUN, "r1"), run_index=-1)
    before = clk.now()
    with pytest.raises(TypeError):
        clk.set_wall(True)
    after = clk.now()
    assert (after.mono_ns, after.wall_ns) == (before.mono_ns, before.wall_ns)
    negative = FakeClock(run=Ref(K.RUN, "negative"), mono_ns=-10, wall_ns=-20).now()
    assert (negative.mono_ns, negative.wall_ns) == (-10, -20)
    with pytest.raises(TypeError):
        seconds(True)


def test_c7_system_clock_sequence_and_threads():
    clock = SystemClock(run=Ref(K.RUN, "r1"), run_index=2)
    values = [clock.now() for _ in range(1000)]
    assert [value.seq for value in values] == list(range(1, 1001))
    assert all(a.mono_ns <= b.mono_ns for a, b in zip(values, values[1:]))
    assert all(value.run == clock.run and value.run_index == 2 for value in values)
    threaded = SystemClock(run=Ref(K.RUN, "r2"), run_index=3)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: [threaded.now() for _ in range(500)], range(4)))
    assert {value.seq for batch in batches for value in batch} == set(range(1, 2001))
    # GIL 下では、ロックを外す誤実装を必ず落とせる試験ではない。
