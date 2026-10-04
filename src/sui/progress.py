"""S4b-1c: progress/1 の宣言と、状態の道を条件にした完了の核。

ここでは道そのものの分布を近似しない。時間・仕事量は宣言した単位で
渡す。∞ は仕事量の専用値であり、速さに float('inf') は使えない。
"""

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
import math


class InfiniteWork(Enum):
    INFINITY = "infinite_work"


INFINITE_WORK = InfiniteWork.INFINITY


def _fraction(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError(f"{name}: expected a finite number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name}: expected a finite number")
    result = Fraction(value)
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{name}: expected {'positive' if positive else 'nonnegative'} value")
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletionSpec:
    """§3-10。候補は全行動×全状態の表の組。順と共有をそのまま保持する。"""

    name: str
    version: str
    actions: tuple[str, ...]
    states: tuple[str, ...]
    work_unit: str
    time_unit: str
    speed_unit: str
    candidates: tuple[tuple[tuple[Fraction, ...], ...], ...]
    weights: tuple[Fraction, ...]
    share: str
    max_speed: Fraction

    def __post_init__(self):
        if self.name != "progress" or self.version != "1":
            raise ValueError("completion: unsupported family or version")
        for name in ("actions", "states"):
            names = tuple(getattr(self, name))
            if not names or any(type(n) is not str or not n for n in names) or len(set(names)) != len(names):
                raise ValueError(f"completion {name}: expected unique nonempty names")
            object.__setattr__(self, name, names)
        if any(type(u) is not str or not u for u in (self.work_unit, self.time_unit, self.speed_unit)):
            raise ValueError("completion: units must be explicit")
        if self.speed_unit != f"{self.work_unit}/{self.time_unit}":
            raise ValueError("completion: speed unit must be work_unit/time_unit")
        if self.share != "all_actions":
            raise ValueError("completion: candidates must share the complete speed table")
        bound = _fraction(self.max_speed, "max_speed")
        candidates = tuple(tuple(tuple(_fraction(r, "speed") for r in row) for row in c)
                           for c in self.candidates)
        if not candidates or any(len(c) != len(self.actions) or any(len(row) != len(self.states) for row in c)
                                 for c in candidates):
            raise ValueError("completion: expected full action/state tables")
        if any(r > bound for c in candidates for row in c for r in row):
            raise ValueError("completion: speed exceeds finite bound")
        weights = tuple(_fraction(w, "speed weight", positive=True) for w in self.weights)
        if len(weights) != len(candidates) or sum(weights) != 1:
            raise ValueError("completion: one normalized weight per candidate")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "max_speed", bound)


@dataclass(frozen=True, slots=True)
class ProgressSegment:
    """長さ None は無限に続く最後の区間。有限の長さは正の値。"""

    duration: Fraction | None
    state: str

    def __post_init__(self):
        if self.duration is not None:
            object.__setattr__(self, "duration", _fraction(self.duration, "segment duration", positive=True))
        if type(self.state) is not str:
            raise ValueError("segment: expected state name")


@dataclass(frozen=True, slots=True)
class CompletionPoint:
    elapsed: Fraction | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class DensityPiece:
    """[lower, upper) 上で一定の密度。高さは probability/time。"""

    lower: Fraction
    upper: Fraction
    density: Fraction

    def __post_init__(self):
        for name in ("lower", "upper", "density"):
            object.__setattr__(self, name, _fraction(getattr(self, name), name))
        if self.upper <= self.lower:
            raise ValueError("density: expected a nonempty finite interval")

    @property
    def mass(self):
        return (self.upper - self.lower) * self.density


@dataclass(frozen=True, slots=True)
class CompletionKernel:
    """原子・密度・永久未着の二つの理由を別々に保持する。"""

    atoms: tuple[tuple[Fraction, Fraction], ...]
    densities: tuple[DensityPiece, ...]
    infinite_work_mass: Fraction
    unreachable_work_mass: Fraction

    @property
    def mass(self):
        return (sum(m for _, m in self.atoms) + sum(p.mass for p in self.densities)
                + self.infinite_work_mass + self.unreachable_work_mass)


def _segments(spec, action, candidate, path):
    if action not in spec.actions or type(candidate) is not int or not 0 <= candidate < len(spec.candidates):
        raise ValueError("progress: unknown action or speed candidate")
    path = tuple(path)
    if (not path or any(not isinstance(p, ProgressSegment) for p in path)
            or path[-1].duration is not None or any(p.duration is None for p in path[:-1])):
        raise ValueError("progress: path must include its infinite final segment")
    if any(p.state not in spec.states for p in path):
        raise ValueError("progress: unknown path state")
    row = spec.candidates[candidate][spec.actions.index(action)]
    return tuple((p.duration, row[spec.states.index(p.state)]) for p in path)


def completion(spec, action, candidate, work, path):
    """D=inf{d:C(d)>=W}。平らな区間では最初の到達を返す。"""
    segments = _segments(spec, action, candidate, path)
    if work is INFINITE_WORK:
        return CompletionPoint(None, "infinite_work")
    work = _fraction(work, "work")
    time = total = Fraction(0)
    for duration, rate in segments:
        if total >= work:
            return CompletionPoint(time, None)
        if rate and (duration is None or total + duration * rate >= work):
            return CompletionPoint(time + (work - total) / rate, None)
        if duration is None:
            return CompletionPoint(None, "unreachable_finite_work")
        time += duration
        total += duration * rate
    raise AssertionError("validated infinite final segment was not visited")


def completion_kernel(spec, action, candidate, path, *, atoms, densities=()):
    """条件つきの核。有限原子と区分一定の仕事量密度を第一到達へ押し出す。

    密度は増加する区間で Jacobian ρ を掛ける。停止中には密度を
    作らない。道の末尾の総仕事量に届かない質量は専用の未着へ置く。
    """
    path, densities = tuple(path), tuple(densities)
    segments = _segments(spec, action, candidate, path)
    atoms = tuple((w if w is INFINITE_WORK else _fraction(w, "work"), _fraction(m, "work mass"))
                  for w, m in atoms)
    if sum(m for _, m in atoms) + sum(p.mass for p in densities) != 1:
        raise ValueError("work law: expected normalized atomic/density mass")
    output, continuous = {}, []
    infinite = unreachable = Fraction(0)
    for work, mass in atoms:
        point = completion(spec, action, candidate, work, path)
        if point.reason == "infinite_work":
            infinite += mass
        elif point.reason:
            unreachable += mass
        else:
            output[point.elapsed] = output.get(point.elapsed, Fraction(0)) + mass
    time = total = Fraction(0)
    reached = Fraction(0)
    for duration, rate in segments:
        stop = None if duration is None and rate else total + (duration or 0) * rate
        if rate:
            for piece in densities:
                lower, upper = max(total, piece.lower), piece.upper if stop is None else min(stop, piece.upper)
                if lower < upper and piece.density:
                    continuous.append(DensityPiece(time + (lower - total) / rate,
                                                   time + (upper - total) / rate, piece.density * rate))
                    reached += (upper - lower) * piece.density
        if duration is None:
            break
        time += duration
        total = stop
    unreachable += sum(p.mass for p in densities) - reached
    return CompletionKernel(tuple(sorted(output.items())), tuple(continuous), infinite, unreachable)
