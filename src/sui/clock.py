"""run ごとの順序とナノ秒の時計。"""

import threading as _threading
import time as _time
from dataclasses import dataclass as _dataclass
from typing import Protocol as _Protocol

from .ids import Ref as _Ref, RefKind as _RefKind, expect as _expect
from .ids import _check_int, _check_type


@_dataclass(frozen=True, slots=True, kw_only=True)
class Instant:
    run: _Ref
    run_index: int
    seq: int
    mono_ns: int
    wall_ns: int

    def __post_init__(self) -> None:
        _expect(self.run, _RefKind.RUN)
        _check_int("run_index", self.run_index, 0)
        _check_int("seq", self.seq, 1)
        _check_int("mono_ns", self.mono_ns)
        _check_int("wall_ns", self.wall_ns)


class ClockError(ValueError):
    """時計の順序に矛盾がある。"""


class CrossRunError(ClockError):
    """異なる run の単調時計は差を取れない。"""


def precedes(a: Instant, b: Instant) -> bool:
    """同じ run の中の連番の見え方。run をまたぐ順は台帳の網が決める。"""
    _check_type("a", a, Instant)
    _check_type("b", b, Instant)
    if a.run != b.run:
        raise CrossRunError(f"run: expected {a.run}, got {b.run}")
    if a.run_index != b.run_index:
        raise ClockError(f"run_index for {a.run}: expected {a.run_index}, got {b.run_index}")
    if a.seq == b.seq and a != b:
        raise ClockError(f"instant at seq {a.seq}: expected {a!r}, got {b!r}")
    return a.seq < b.seq


def elapsed_ns(a: Instant, b: Instant) -> int:
    """同じ run の単調時計の差を、負もそのまま返す。"""
    _check_type("a", a, Instant)
    _check_type("b", b, Instant)
    if a.run != b.run:
        raise CrossRunError(f"run: expected {a.run}, got {b.run}")
    return b.mono_ns - a.mono_ns


def wall_gap_ns(a: Instant, b: Instant) -> int:
    """run をまたいでも実時刻の差を参考値として返す。"""
    _check_type("a", a, Instant)
    _check_type("b", b, Instant)
    return b.wall_ns - a.wall_ns


def seconds(ns: int) -> float:
    """ナノ秒を秒に換算する。"""
    _check_int("ns", ns)
    return ns / 1_000_000_000


class Clock(_Protocol):
    @property
    def run(self) -> _Ref: ...

    @property
    def run_index(self) -> int: ...

    def now(self) -> Instant: ...

    def mono_ns(self) -> int: ...


class SystemClock:
    """連番の更新と時刻の取得をロック内で行う時計。"""

    def __init__(self, *, run: _Ref, run_index: int) -> None:
        _expect(run, _RefKind.RUN)
        _check_int("run_index", run_index, 0)
        self._run = run
        self._run_index = run_index
        self._seq = 0
        self._lock = _threading.Lock()

    @property
    def run(self) -> _Ref:
        return self._run

    @property
    def run_index(self) -> int:
        return self._run_index

    def mono_ns(self) -> int:
        """連番を進めず単調時計だけを読む (J1)。"""
        return _time.perf_counter_ns()

    def now(self) -> Instant:
        """連番を進め、単調時計と実時刻を読む。"""
        with self._lock:
            self._seq += 1
            return Instant(run=self.run, run_index=self.run_index, seq=self._seq,
                           mono_ns=_time.perf_counter_ns(), wall_ns=_time.time_ns())


class FakeClock:
    """明示的な操作だけで時間を進める、単一スレッド用の時計。"""

    def __init__(self, *, run: _Ref, run_index: int = 0, mono_ns: int = 0,
                 wall_ns: int = 1_790_000_000_000_000_000) -> None:
        _expect(run, _RefKind.RUN)
        _check_int("run_index", run_index, 0)
        _check_int("mono_ns", mono_ns)
        _check_int("wall_ns", wall_ns)
        self._run = run
        self._run_index = run_index
        self._seq = 0
        self._mono_ns = mono_ns
        self._wall_ns = wall_ns

    @property
    def run(self) -> _Ref:
        return self._run

    @property
    def run_index(self) -> int:
        return self._run_index

    def mono_ns(self) -> int:
        """連番も時間も進めず単調時計だけを読む (J1)。"""
        return self._mono_ns

    def now(self) -> Instant:
        """時間を進めず、連番だけを増やして時刻を返す。"""
        self._seq += 1
        return Instant(run=self.run, run_index=self.run_index, seq=self._seq,
                       mono_ns=self._mono_ns, wall_ns=self._wall_ns)

    def advance(self, ns: int) -> None:
        """非負のナノ秒だけ両時計を進め、不正な値なら変えない。"""
        _check_int("ns", ns, 0)
        self._mono_ns += ns
        self._wall_ns += ns

    def set_wall(self, wall_ns: int) -> None:
        """実時刻だけを指定された値へ動かす。"""
        _check_int("wall_ns", wall_ns)
        self._wall_ns = wall_ns
