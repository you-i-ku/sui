"""量の事前、測定の結合の核、DP の分割の和。値はモデルから受け取る。

測定の族の検査と計算はこのファイルに置く。model.py からも検査を呼ぶため、
モデル・推論への依存は計算時に読み込む (モジュールの循環を作らない)。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from itertools import permutations, product
import heapq
import math
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from .values import MeasureSpec, ValueSpace, InformationBounds, _freeze, _thaw


def _number(value, name, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(f"{name}: expected a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name}: expected a finite number") from exc
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f"{name}: expected finite {'positive' if positive else 'nonnegative'} number")
    return result


def _mass_total(values, name):
    try:
        total = math.fsum(values)
    except OverflowError as exc:
        raise ValueError(f"{name}: masses must sum to one") from exc
    if abs(total - 1) > 1e-12:
        raise ValueError(f"{name}: masses must sum to one")


def _keys(value, keys, name):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError(f"{name}: unexpected keys")


@dataclass(frozen=True, slots=True)
class BaseSpec:
    name: str
    version: str
    params: Mapping

    def __post_init__(self):
        if self.version != "1":
            raise ValueError("base: unsupported version")
        params = self.params
        if self.name == "atoms":
            _keys(params, ("points",), "atoms")
            points = params["points"]
            if not isinstance(points, (list, tuple)) or not points:
                raise ValueError("atoms: expected nonempty points")
            seen, normalized = set(), []
            for point in points:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise ValueError("atoms: expected (ns, mass) points")
                ns, mass = point
                if ns is not None and (type(ns) is not int or ns < 0):
                    raise ValueError("atoms: expected nonnegative integer ns or null")
                if ns in seen:
                    raise ValueError("atoms: duplicate point")
                seen.add(ns)
                normalized.append((ns, _number(mass, "atoms mass")))
            _mass_total((mass for _, mass in normalized), "atoms")
            params = {"points": sorted(normalized, key=lambda p: (p[0] is None, p[0]))}
        elif self.name == "piecewise":
            _keys(params, ("edges_ns", "masses", "tail", "p_inf"), "piecewise")
            edges, masses = params["edges_ns"], params["masses"]
            if (not isinstance(edges, (list, tuple)) or len(edges) < 2
                    or any(type(e) is not int or e < 0 for e in edges)
                    or edges[0] != 0 or any(b <= a for a, b in zip(edges, edges[1:]))):
                raise ValueError("piecewise: expected increasing integer edges starting at zero")
            if not isinstance(masses, (list, tuple)) or len(masses) != len(edges) - 1:
                raise ValueError("piecewise: expected one mass per interval")
            _keys(params["tail"], ("kind", "kappa", "mass"), "tail")
            if params["tail"]["kind"] != "pareto":
                raise ValueError("tail: unsupported kind")
            masses = tuple(_number(m, "piecewise mass") for m in masses)
            tail = {"kind": "pareto", "kappa": _number(params["tail"]["kappa"], "kappa", positive=True),
                    "mass": _number(params["tail"]["mass"], "tail mass")}
            p_inf = _number(params["p_inf"], "p_inf")
            _mass_total((*masses, tail["mass"], p_inf), "piecewise")
            params = {"edges_ns": edges, "masses": masses, "tail": tail, "p_inf": p_inf}
        else:
            raise ValueError("base: unsupported family")
        object.__setattr__(self, "params", _freeze(params))

    def as_json(self):
        return {"name": self.name, "version": self.version, "params": _thaw(self.params)}

    @property
    def p_inf(self):
        if self.name == "piecewise":
            return self.params["p_inf"]
        return next((mass for ns, mass in self.params["points"] if ns is None), 0.)

    def interval_moment(self, order, lower, upper):
        """有限部分の ∫_[lower,upper) x**order G₀(dx)。∞ の原子は含めない。

        閉じた式の離散化誤差は 0 (§4-6)。パレート全域の発散は断る。
        小さい正を返り値の 0 にしない計算には log_interval_moment を使う。
        """
        log_value = self.log_interval_moment(order, lower, upper)
        if log_value == -math.inf:
            return 0.
        try:
            value = math.exp(log_value)
        except OverflowError:
            _range("base: moment cannot be represented; use log moment")
        if value == 0 or not math.isfinite(value):
            _range("base: positive moment cannot be represented; use log moment")
        return value

    def log_interval_moment(self, order, lower, upper):
        if type(order) is not int or order < 0 or lower < 0 or (upper is not None and upper < lower):
            raise ValueError("base moment: expected nonnegative order and interval")
        if upper == lower:
            return -math.inf
        terms = []
        if self.name == "atoms":
            for point, mass in self.params["points"]:
                if point is not None and lower <= point and (upper is None or point < upper) and mass:
                    if order == 0 or point:
                        terms.append(math.log(mass) + (order * math.log(point) if order else 0.))
        else:
            edges, masses = self.params["edges_ns"], self.params["masses"]
            for a, b, mass in zip(edges, edges[1:], masses):
                lo, hi = max(lower, a), b if upper is None else min(upper, b)
                if mass and lo < hi:
                    # Exact rational difference avoids cancellation at close integer edges.
                    integral = ((_fraction(hi) ** (order + 1) - _fraction(lo) ** (order + 1))
                                / (order + 1) / (b - a))
                    terms.append(math.log(mass) + _log_fraction(integral))
            tail = self.params["tail"]
            lo = max(lower, edges[-1])
            if tail["mass"] and (upper is None or lo < upper):
                terms.append(_pareto_log_moment(tail["kappa"], tail["mass"], edges[-1], order, lo, upper))
        return _logadd(terms)

    def log_finite_tail(self, cutoff):
        """残りの有限の質量。∞ の質量と打ち切る有限の尾を分ける (§3-4.7)。"""
        return self.log_interval_moment(0, cutoff, None)


@dataclass(frozen=True, slots=True)
class DurationPrior:
    alpha: float
    base: BaseSpec

    def __post_init__(self):
        object.__setattr__(self, "alpha", _number(self.alpha, "alpha", positive=True))
        if not isinstance(self.base, BaseSpec):
            raise ValueError("duration prior: expected BaseSpec")

    def as_json(self):
        return {"alpha": self.alpha, "base": self.base.as_json()}


def _validate_measure_spec(spec):
    if not isinstance(spec, MeasureSpec) or spec.version != "1":
        raise ValueError("measure: unsupported version")
    params = spec.params
    if spec.name == "exact":
        _keys(params, (), "exact")
    elif spec.name == "tick":
        _keys(params, ("width_ns", "phase", "check"), "tick")
        width, phase = params["width_ns"], params["phase"]
        if type(width) is not int or width <= 0:
            raise ValueError("tick: expected positive integer width_ns")
        if phase != "uniform":
            _keys(phase, ("point_ns",), "phase")
            if type(phase["point_ns"]) is not int or not 0 <= phase["point_ns"] < width:
                raise ValueError("phase: expected integer point_ns inside tick")
        if params["check"] != "uniform_in_tick":
            raise ValueError("tick: unsupported check process")
    else:
        raise ValueError("measure: unsupported family")


@dataclass(frozen=True, slots=True)
class MeasureCandidate:
    spec: MeasureSpec
    weight: float

    def __post_init__(self):
        _validate_measure_spec(self.spec)
        object.__setattr__(self, "weight", _number(self.weight, "weight", positive=True))

    def as_json(self):
        return {**self.spec.as_json(), "weight": self.weight}


@dataclass(frozen=True, slots=True)
class MeasurePrior:
    share: str
    candidates: tuple[MeasureCandidate, ...]

    def __post_init__(self):
        if self.share != "all_actions":
            raise ValueError("measure: unsupported sharing")
        if (not isinstance(self.candidates, tuple) or not self.candidates
                or any(not isinstance(c, MeasureCandidate) for c in self.candidates)):
            raise ValueError("measure: expected nonempty candidates")
        _mass_total((c.weight for c in self.candidates), "measure")

    def as_json(self):
        return {"share": self.share, "candidates": [c.as_json() for c in self.candidates]}


def duration_prior(value):
    if isinstance(value, DurationPrior):
        return value
    _keys(value, ("alpha", "base"), "duration prior")
    _keys(value["base"], ("name", "version", "params"), "base")
    return DurationPrior(value["alpha"], BaseSpec(**value["base"]))


def measure_prior(value):
    if isinstance(value, MeasurePrior):
        return value
    _keys(value, ("share", "candidates"), "measure")
    if not isinstance(value["candidates"], (list, tuple)):
        raise ValueError("measure: expected candidates")
    candidates = []
    for item in value["candidates"]:
        _keys(item, ("name", "version", "params", "weight"), "candidate")
        candidates.append(MeasureCandidate(MeasureSpec(item["name"], item["version"], item["params"]),
                                           item["weight"]))
    return MeasurePrior(value["share"], tuple(candidates))


def validate_model(priors, measure, actions):
    if not isinstance(priors, Mapping) or set(priors) != set(actions):
        raise ValueError("duration_priors: expected exactly the actions as keys")
    priors = {action: duration_prior(priors[action]) for action in actions}
    measure = measure_prior(measure)
    if any(c.spec.name == "exact" for c in measure.candidates):
        if any(p.base.name == "piecewise" for p in priors.values()):
            raise ValueError("exact with piecewise base has infinite information")
    return MappingProxyType(priors), measure


@runtime_checkable
class QuantityMeasure(Protocol):
    def history_kernel(self, timing, *, lam): ...


@dataclass(frozen=True, slots=True)
class TimingEvent:
    id: object
    run: object
    run_index: int
    seq: int
    reading: int | None
    kind: str
    attempt: object | None


@dataclass(frozen=True, slots=True)
class AttemptTiming:
    attempt: object | None
    job: object
    action: str | None
    start_event: object | None
    check_events: tuple
    report_event: object | None
    state: str


@dataclass(frozen=True, slots=True)
class Timing:
    events: Mapping
    attempts: tuple[AttemptTiming, ...]
    positions: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "events", MappingProxyType(dict(self.events)))
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "positions", MappingProxyType({
            ref: frozenset(before) for ref, before in self.positions.items()}))

    def exact_evidence(self, action):
        result = []
        for item in self.attempts:
            if item.action != action or item.state in ("queued", "unreadable"):
                continue
            start = self.events[item.start_event].reading
            checks = tuple((self.events[ref].reading - start, False) for ref in item.check_events)
            complete = item.state == "complete"
            value = self.events[item.report_event].reading - start if complete else None
            result.append(ExactEvidence(str(item.attempt), checks, complete, value))
        return tuple(result)


def read_timing(records, axis, jobs, actions_by_attempt, pending):
    """名前の可読性とは独立に、全試みと最初の受け取りを事実から読む (§4-3)。

    ここでは永続の受け取りだけを使う。Tick/Thought の確かめは決定の文脈で扱う。
    呼ぶ側の境界を指定する決定時の照会は、この不変な読みを元に構築する。
    """
    from .records import AttemptStarted, Observed, Decided
    from .s3_contracts import ABANDON
    events, starts, reports, abandons = {}, {}, {}, {}
    order = lambda r: (r.at.run_index, r.at.seq, str(r.id))
    for record in sorted(records, key=order):
        body = record.body
        if isinstance(body, AttemptStarted):
            starts[record.id] = record
            ns = (axis.to_axis(record.at.run, record.at.mono_ns)
                  if axis is not None and record.at.run in axis.runs else None)
            kind, attempt = "start", record.id
        elif isinstance(body, Observed):
            ns = axis.received_ns.get(record.id) if axis is not None else None
            attempt = body.caused_by if body.caused_by in actions_by_attempt else None
            kind = "report" if attempt is not None else "external"
            if attempt is not None:
                reports.setdefault(attempt, record)
        elif isinstance(body, Decided) and body.contract == ABANDON and len(body.inputs) == 1:
            try:
                valid = body.content.as_json() == {"job": str(body.inputs[0])}
            except (ValueError, UnicodeError):
                valid = False
            if valid:
                abandons.setdefault(body.inputs[0], record)
            continue
        else:
            continue
        events[record.id] = TimingEvent(record.id, record.at.run, record.at.run_index,
            record.at.seq, ns, kind, attempt)
    # v0.14: 後のrunの受け取りは、他の試みの確かめにも使わない。
    excluded = {event.id for event in events.values() if event.kind == "report"
                and event.attempt in starts and event.run != starts[event.attempt].at.run}
    attempts = []
    for ref, record in starts.items():
        action = actions_by_attempt[ref]
        report = reports.get(ref)
        abandoned = abandons.get(record.body.job)
        cut = min((r for r in (report, abandoned) if r is not None), key=order, default=None)
        checks = tuple(event.id for event in sorted(events.values(), key=lambda e: (
                       math.inf if e.reading is None else e.reading, e.run_index, e.seq, str(e.id)))
                       if event.kind != "start" and event.id not in excluded and event.run == record.at.run
                       and event.reading is not None
                       and (event.run_index, event.seq, str(event.id)) > order(record)
                       and (cut is None or (event.run_index, event.seq, str(event.id)) < order(cut)))
        if action is None or events[ref].reading is None:
            state = "unreadable"
        elif abandoned is not None and (report is None or order(abandoned) < order(report)):
            state = "unknown"
        elif report is not None:
            state = ("complete" if events[report.id].reading is not None
                     and report.at.run == record.at.run else "unknown")
        else:
            state = "pending"
        attempts.append(AttemptTiming(ref, record.body.job, action or jobs.get(record.body.job),
            ref, checks, None if report is None else report.id, state))
    started_jobs = {r.body.job for r in starts.values()}
    attempts.extend(AttemptTiming(None, job, action, None, (), None, "queued")
                    for job, action in pending.items() if job not in started_jobs)
    def attempt_order(item):
        event = events.get(item.start_event)
        return (math.inf if event is None or event.reading is None else event.reading,
                -1 if event is None else event.run_index, -1 if event is None else event.seq,
                str(item.attempt if item.attempt is not None else item.job))
    return Timing(events, tuple(sorted(attempts, key=attempt_order)))


def _excluded_timing_events(timing):
    """後のrunの受け取りを、Kの変数/順序/正規化からも除く (§4-3)。"""
    starts = {a.attempt: timing.events[a.start_event] for a in timing.attempts
              if a.start_event in timing.events}
    return frozenset(e.id for e in timing.events.values() if e.kind == "report"
                     and e.attempt in starts and e.run != starts[e.attempt].run)


def _cross_run_arrival(timing, attempt):
    return (attempt.report_event in timing.events and attempt.start_event in timing.events
            and timing.events[attempt.report_event].run != timing.events[attempt.start_event].run)


@dataclass(frozen=True, slots=True)
class QuantityStats:
    partitions: int
    series_terms: int = 0
    aggregated_records: int = 0
    final_groups: int = 0
    integration_pieces: int = 0
    allocated_branches: int = 0
    integration_boxes: int = 0
    integration_nodes: int = 0
    max_integration_degree: int = 0


def _range(reason):
    from .inference import NumericalRange
    raise NumericalRange(reason)


def _fraction(value):
    """入力の二進浮動小数点も、その値のまま有理数にする。"""
    return value if isinstance(value, Fraction) else Fraction(value)


def _log_fraction(value):
    if value == 0:
        return -math.inf
    if value < 0:
        raise ValueError("quantity: expected nonnegative rational")
    # Do not first round an arbitrarily small positive rational to float zero.
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    scaled = value / (1 << exponent) if exponent >= 0 else value * (1 << -exponent)
    result = math.log(float(scaled)) + exponent * math.log(2.)
    if not math.isfinite(result):
        _range("quantity: rational logarithm exceeds numerical range")
    return result


def _pareto_log_moment(kappa, mass, boundary, order, lower, upper):
    """パレート密度だけの区間の解析モーメント。全ての族の値は引数。"""
    q = order - kappa
    scale = math.log(mass) + math.log(kappa) + kappa * math.log(boundary)
    if upper is None:
        if q >= 0:
            raise ValueError("pareto: whole-tail moment diverges")
        result = scale + q * math.log(lower) - math.log(-q)
    else:
        ratio = (_fraction(upper) - _fraction(lower)) / _fraction(lower)
        try:
            relative = float(ratio)
        except OverflowError:
            relative = math.inf
        ratio_log = math.log1p(relative) if math.isfinite(relative) else _log_fraction(ratio + 1)
        if ratio_log <= 0 or not math.isfinite(ratio_log):
            _range("pareto: positive interval width cannot be represented")
        if q == 0:
            result = scale + math.log(ratio_log)
        else:
            z = q * ratio_log
            difference = z + math.log(-math.expm1(-z)) if z > 0 else math.log(-math.expm1(z))
            result = scale + q * math.log(lower) + difference - math.log(abs(q))
    if not math.isfinite(result):
        _range("pareto: moment exceeds numerical range")
    return result


def _affine_subtract(left, right):
    return tuple(a - b for a, b in zip(left, right))


def _polynomial_add(target, source, scale=Fraction(1)):
    for powers, coefficient in source.items():
        value = target.get(powers, Fraction(0)) + scale * coefficient
        if value:
            target[powers] = value
        else:
            target.pop(powers, None)


def _polynomial_multiply(left, right):
    result = {}
    for p, a in left.items():
        for q, b in right.items():
            powers = tuple(i + j for i, j in zip(p, q))
            result[powers] = result.get(powers, Fraction(0)) + a * b
    return {p: a for p, a in result.items() if a}


def _affine_power(affine, order):
    dimension = len(affine) - 1
    zero = (0,) * dimension
    result, polynomial = {zero: Fraction(1)}, {zero: affine[0]} if affine[0] else {}
    for i, coefficient in enumerate(affine[1:]):
        if coefficient:
            powers = tuple(int(j == i) for j in range(dimension))
            polynomial[powers] = coefficient
    for _ in range(order):
        result = _polynomial_multiply(result, polynomial)
    return result


def _clean_constraints(constraints):
    """制約は (定数, 係数...), strict。等号の点の位相もここで検査する。"""
    result = {}
    for affine, strict in constraints:
        if not any(affine[1:]):
            if affine[0] < 0 or (strict and affine[0] == 0):
                return None
            continue
        scale = abs(next(a for a in affine[1:] if a))
        normalized = tuple(a / scale for a in affine)
        result[normalized] = result.get(normalized, False) or strict
    return tuple(sorted(result.items()))


def _polytope_integral(dimension, constraints, polynomial):
    """有界な線形領域の多項式積分 (Fraction)、正の体積の片数も返す。

    内側の変数の max/min の各面を選び、その面が有効な外側の領域へ
    制約を渡す。境界の同点は候補の正準の順で片側だけに割り当てる。
    零次元の strict は残すので、点の位相を「測度0」として捨てない。
    """
    constraints = _clean_constraints(constraints)
    if constraints is None or not polynomial:
        return Fraction(0), 0
    if dimension == 0:
        return polynomial.get((), Fraction(0)), 1
    lowers, uppers, outer = set(), set(), []
    for affine, strict in constraints:
        coefficient = affine[-1]
        if coefficient:
            bound = tuple(-a / coefficient for a in affine[:-1])
            (lowers if coefficient > 0 else uppers).add(bound)
        else:
            outer.append((affine[:-1], strict))
    if not lowers or not uppers:
        raise ValueError("polytope: bounded variables are required")
    lowers, uppers = sorted(lowers), sorted(uppers)
    total, pieces = Fraction(0), 0
    for i, lower in enumerate(lowers):
        for j, upper in enumerate(uppers):
            region = outer + [(_affine_subtract(upper, lower), True)]
            region += [(_affine_subtract(lower, b), k < i) for k, b in enumerate(lowers) if k != i]
            region += [(_affine_subtract(b, upper), k < j) for k, b in enumerate(uppers) if k != j]
            if _clean_constraints(region) is None:
                continue
            integrated = {}
            powers_needed = {p[-1] + 1 for p in polynomial}
            differences = {}
            for power in powers_needed:
                difference = _affine_power(upper, power)
                _polynomial_add(difference, _affine_power(lower, power), Fraction(-1))
                differences[power] = difference
            for powers, coefficient in polynomial.items():
                for added, factor in differences[powers[-1] + 1].items():
                    p = tuple(a + b for a, b in zip(powers[:-1], added))
                    integrated[p] = integrated.get(p, Fraction(0)) + coefficient * factor / (powers[-1] + 1)
            value, count = _polytope_integral(dimension - 1, region, integrated)
            total += value
            pieces += count
    return total, pieces


def _linear_pieces(dimension, constraints):
    """外から内への一次の上下限。max/minの面で全領域を重ならず覆う。"""
    constraints = _clean_constraints(constraints)
    if constraints is None:
        return
    if dimension == 0:
        yield ()
        return
    lowers, uppers, outer = set(), set(), []
    for affine, strict in constraints:
        if affine[-1]:
            bound = tuple(-a / affine[-1] for a in affine[:-1])
            (lowers if affine[-1] > 0 else uppers).add(bound)
        else:
            outer.append((affine[:-1], strict))
    if not lowers or not uppers:
        raise ValueError("linear pieces: finite bounds required")
    lowers, uppers = sorted(lowers), sorted(uppers)
    for i, lo in enumerate(lowers):
        for j, hi in enumerate(uppers):
            region = outer + [(_affine_subtract(hi, lo), True)]
            region += [(_affine_subtract(lo, b), k < i) for k, b in enumerate(lowers) if k != i]
            region += [(_affine_subtract(b, hi), k < j) for k, b in enumerate(uppers) if k != j]
            for bounds in _linear_pieces(dimension - 1, region):
                yield bounds + ((lo, hi),)


@dataclass(frozen=True, slots=True)
class PowerFactor:
    affine: tuple
    power: float

    def __post_init__(self):
        affine = tuple(_fraction(a) for a in self.affine)
        power = float(self.power)
        if not affine or not math.isfinite(power):
            raise ValueError("power factor: finite affine coefficients and power required")
        object.__setattr__(self, "affine", affine)
        object.__setattr__(self, "power", power)


@dataclass(frozen=True, slots=True)
class PowerTerm:
    """係数×exp(log_scale)×一次式の冪の積。有限和の符号も残す。"""
    coefficient: Fraction
    factors: tuple[PowerFactor, ...]
    log_scale: float = 0.

    def __post_init__(self):
        object.__setattr__(self, "coefficient", _fraction(self.coefficient))
        object.__setattr__(self, "factors", tuple(self.factors))
        if not math.isfinite(self.log_scale):
            _range("integration: nonfinite term scale")


@dataclass(frozen=True, slots=True)
class IntegralEstimate:
    """正の積分の求積値と離散化/有限の尾の上界。丸めは含めない。"""
    log_value: float
    log_error: float
    log_tail: float = -math.inf
    pieces: int = 0
    boxes: int = 0
    max_degree: int = 0
    nodes: int = 0

    def __post_init__(self):
        if any(v != -math.inf and not math.isfinite(v) for v in
               (self.log_value, self.log_error, self.log_tail)):
            _range("integration: nonfinite estimate or bound")

    @property
    def log_lower(self):
        if self.log_error == -math.inf:
            return self.log_value
        if self.log_value <= self.log_error:
            return -math.inf
        return self.log_value + math.log(-math.expm1(self.log_error - self.log_value))

    @property
    def log_upper(self):
        return _logadd((self.log_value, self.log_error, self.log_tail))

    @property
    def log_width(self):
        if self.log_value > self.log_error:
            return _logadd((self.log_error + math.log(2.), self.log_tail))
        return self.log_upper

    def bounds(self):
        try:
            result = tuple(0. if v == -math.inf else math.exp(v) for v in (self.log_lower, self.log_upper))
        except OverflowError:
            _range("integration: bound cannot be represented; use log bounds")
        if any(not math.isfinite(v) or (v == 0 and log_v != -math.inf)
               for v, log_v in zip(result, (self.log_lower, self.log_upper))):
            _range("integration: positive bound cannot be represented; use log bounds")
        return result

    def with_tail(self, log_tail):
        return IntegralEstimate(self.log_value, self.log_error, _logadd((self.log_tail, log_tail)),
                                self.pieces, self.boxes, self.max_degree, self.nodes)


@dataclass(frozen=True, slots=True)
class ProbabilityInterval:
    log_lower: float
    log_upper: float
    log_span: float | None = None

    def __post_init__(self):
        if (self.log_lower > self.log_upper or self.log_upper > 0
                or any(v != -math.inf and not math.isfinite(v) for v in (self.log_lower, self.log_upper))):
            raise ValueError("probability interval: invalid bounds")
        if self.log_span is not None and self.log_span != -math.inf and not math.isfinite(self.log_span):
            _range("probability interval: nonfinite propagated width")

    @property
    def log_width(self):
        if self.log_span is not None:
            return self.log_span
        if self.log_lower == self.log_upper:
            return -math.inf
        if self.log_lower == -math.inf:
            return self.log_upper
        return self.log_upper + math.log(-math.expm1(self.log_lower - self.log_upper))


def condition_probability(numerator, denominator):
    """分子が分母の事象の一部分という約束の下で、積分の区間を条件づける。"""
    if denominator.log_upper == -math.inf:
        from .inference import ModelViolation
        raise ModelViolation("quantity: observations have zero probability")
    if numerator.log_upper == -math.inf:
        return ProbabilityInterval(-math.inf, -math.inf, -math.inf)
    lower = numerator.log_lower - denominator.log_upper
    upper = (0. if denominator.log_lower == -math.inf else
             min(0., numerator.log_upper - denominator.log_lower))
    if denominator.log_lower == -math.inf or numerator.log_lower == -math.inf:
        span = upper
    else:
        span = min(0., _logadd((numerator.log_upper + denominator.log_width,
                               denominator.log_lower + numerator.log_width))
                   - denominator.log_lower - denominator.log_upper)
    return ProbabilityInterval(min(lower, 0.), upper, span)


def sum_integrals(estimates, weights):
    """片・分割・λを全て合算する。各項の誤差を同じ目標にしたとは扱わない。"""
    estimates, weights = tuple(estimates), tuple(weights)
    if len(estimates) != len(weights):
        raise ValueError("integral sum: one nonnegative weight per term required")
    logs = tuple(_log_fraction(_fraction(w)) for w in weights)
    return IntegralEstimate(*(_logadd(log + getattr(e, name) for e, log in zip(estimates, logs))
                              for name in ("log_value", "log_error", "log_tail")),
        sum(e.pieces for e in estimates), sum(e.boxes for e in estimates),
        max((e.max_degree for e in estimates), default=0), sum(e.nodes for e in estimates))


class IntegrationIncomplete(RuntimeError):
    """明示された計算量の予算が尽きた。NumericalRangeではない。"""


class _IntegrationWork:
    def __init__(self, limit):
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("integration work: expected nonnegative node budget or None")
        self.limit, self.nodes = limit, 0

    def consume(self, nodes):
        if self.limit is not None and nodes > self.limit - self.nodes:
            raise IntegrationIncomplete("integration: explicit quadrature-node budget exhausted")
        self.nodes += nodes


def _ml_add(target, source, scale):
    for mask, coefficient in source.items():
        value = target.get(mask, Fraction(0)) + scale * coefficient
        if value:
            target[mask] = value
        else:
            target.pop(mask, None)


def _map_affine(affine, coordinates):
    result = {0: affine[0]} if affine[0] else {}
    for coefficient, coordinate in zip(affine[1:], coordinates):
        _ml_add(result, coordinate, coefficient)
    return result


def _ml_box(polynomial, box):
    """s=lo+(hi-lo)tを有理数で代入。各軸が高々一次という形を保つ。"""
    result = {}
    for mask, coefficient in polynomial.items():
        term = {0: coefficient}
        for axis, (lo, hi) in enumerate(box):
            if mask & (1 << axis):
                changed = {}
                for m, c in term.items():
                    changed[m] = changed.get(m, Fraction(0)) + c * _fraction(lo)
                    changed[m | (1 << axis)] = changed.get(m | (1 << axis), Fraction(0)) + c * (_fraction(hi) - _fraction(lo))
                term = changed
        _ml_add(result, term, Fraction(1))
    return result


def _ml_value(polynomial, values):
    return sum((coefficient * math.prod(values[i] for i in range(len(values)) if mask & (1 << i))
                for mask, coefficient in polynomial.items()), Fraction(0))


@dataclass(frozen=True, slots=True)
class _MappedTerm:
    coefficient: Fraction
    log_scale: float
    factors: tuple


@dataclass(frozen=True, slots=True)
class IntegrationPiece:
    """原変数の一次の上下限と、原変数で表した被積分の有限和。"""
    bounds: tuple
    terms: tuple[PowerTerm, ...]

    def __post_init__(self):
        bounds = tuple((tuple(_fraction(a) for a in lo), tuple(_fraction(a) for a in hi))
                       for lo, hi in self.bounds)
        if any(len(lo) != i + 1 or len(hi) != i + 1 for i, (lo, hi) in enumerate(bounds)):
            raise ValueError("integration piece: affine bounds must depend only on outer variables")
        if any(len(f.affine) != len(bounds) + 1 for t in self.terms for f in t.factors):
            raise ValueError("integration piece: factor dimension differs")
        object.__setattr__(self, "bounds", bounds)
        object.__setattr__(self, "terms", tuple(self.terms))

    def mapped_terms(self):
        coordinates, jacobians = [], []
        for i, (lo, hi) in enumerate(self.bounds):
            lower, upper = _map_affine(lo, coordinates), _map_affine(hi, coordinates)
            width = dict(upper)
            _ml_add(width, lower, Fraction(-1))
            jacobians.append((width, 1.))
            coordinate = dict(lower)
            _ml_add(coordinate, {mask | (1 << i): c for mask, c in width.items()}, Fraction(1))
            coordinates.append(coordinate)
        return tuple(_MappedTerm(t.coefficient, t.log_scale,
                     tuple((_map_affine(f.affine, coordinates), f.power) for f in t.factors) + tuple(jacobians))
                     for t in self.terms if t.coefficient)


def _box_terms(mapped, box):
    log_volume = math.fsum(math.log(hi - lo) for lo, hi in box)
    result = []
    for term in mapped:
        factors, log_scale, zero = [], term.log_scale + log_volume, False
        for polynomial, power in term.factors:
            if power == 0:
                continue
            changed = _ml_box(polynomial, box)
            scale = max((abs(c) for c in changed.values()), default=Fraction(0))
            if not scale:
                if power > 0:
                    zero = True
                    break
                _range("integration: zero denominator factor")
            factors.append(({m: c / scale for m, c in changed.items()}, power))
            log_scale += power * _log_fraction(scale)
        if not zero:
            if not math.isfinite(log_scale):
                _range("integration: nonfinite box scale")
            result.append(_MappedTerm(term.coefficient, log_scale, tuple(factors)))
    return tuple(result)


def _axis_log_m(terms, dimension, axis, rho):
    radius = (_fraction(rho) + 1 / _fraction(rho)) / 2
    left, right = (1 - radius) / 2, (1 + radius) / 2
    term_bounds = []
    other = tuple(i for i in range(dimension) if i != axis)
    for term in terms:
        log_m = _log_fraction(abs(term.coefficient)) + term.log_scale
        for polynomial, power in term.factors:
            lower, upper = None, Fraction(0)
            for vertex in product((Fraction(0), Fraction(1)), repeat=len(other)):
                values = [Fraction(0)] * dimension
                for i, value in zip(other, vertex):
                    values[i] = value
                alpha = _ml_value(polynomial, values)
                values[axis] = Fraction(1)
                beta = _ml_value(polynomial, values) - alpha
                real_min = min(alpha + beta * left, alpha + beta * right)
                lower = real_min if lower is None else min(lower, real_min)
                upper = max(upper, abs(alpha) + abs(beta) * right)
            if (power < 0 or not power.is_integer()) and lower <= 0:
                return None               # Analyticity not certified: bisect this box.
            bound = lower if power < 0 else upper
            if not bound:
                _range("integration: positive factor bound disappeared")
            log_m += power * _log_fraction(bound)
        if not math.isfinite(log_m):
            _range("integration: nonfinite analytic bound")
        term_bounds.append(log_m)
    return _logadd(term_bounds)


def _quadrature_error(terms, dimension, degree):
    if not terms:
        return (-math.inf,) * dimension
    errors = []
    for axis in range(dimension):
        best = math.inf
        # Search expands with degree, with no fixed upper limit on rho.
        def rhos():
            yield 1.25
            yield 1.5
            for i in range(1, degree + 2):
                try:
                    yield float(2 ** i)
                except OverflowError:
                    _range("integration: ellipse parameter exceeds numerical range")
        for rho in rhos():
            if not math.isfinite(rho):
                _range("integration: ellipse parameter exceeds numerical range")
            log_m = _axis_log_m(terms, dimension, axis, rho)
            if log_m is None:
                break
            log_error = (log_m + math.log(2 + 2 / (4 * degree * degree - 1))
                         - 2 * degree * math.log(rho) - math.log1p(-rho ** -2))
            if not math.isfinite(log_error):
                _range("integration: analytic error bound disappeared or is nonfinite")
            best = min(best, log_error)
        errors.append(best)
    return tuple(errors)


@lru_cache(None)
def _gauss_rule(degree):
    import numpy as np
    nodes, weights = np.polynomial.legendre.leggauss(degree)
    nodes, weights = (nodes + 1) / 2, weights / 2
    if not np.all(np.isfinite(nodes)) or not np.all(np.isfinite(weights)) or np.any(weights <= 0):
        _range("integration: invalid Gauss-Legendre rule")
    return nodes, weights


def _quadrature_value(terms, dimension, degree, work):
    import numpy as np
    work.consume(degree ** dimension)
    nodes, weights = _gauss_rule(degree)
    grid = np.meshgrid(*(nodes for _ in range(dimension)), indexing="ij")
    weight_grid = np.meshgrid(*(np.log(weights) for _ in range(dimension)), indexing="ij")
    log_weights = sum(weight_grid)
    positive, negative = np.full_like(log_weights, -np.inf), np.full_like(log_weights, -np.inf)
    for term in terms:
        logs = np.full_like(log_weights, _log_fraction(abs(term.coefficient)) + term.log_scale)
        signs = np.ones_like(log_weights) * (1 if term.coefficient > 0 else -1)
        for polynomial, power in term.factors:
            value = np.zeros_like(log_weights)
            for mask, coefficient in polynomial.items():
                scalar = float(coefficient)
                if scalar == 0 and coefficient:
                    _range("integration: positive coefficient cannot be represented")
                item = scalar
                for i in range(dimension):
                    if mask & (1 << i):
                        item = item * grid[i]
                value += item
            if not np.all(np.isfinite(value)):
                _range("integration: nonfinite factor value")
            if (power < 0 or not power.is_integer()) and np.any(value <= 0):
                _range("integration: real factor left its analytic domain")
            if power.is_integer() and int(power) % 2:
                signs *= np.sign(value)
            nonzero = value != 0
            log_factor = np.full_like(value, -np.inf)
            log_factor[nonzero] = power * np.log(np.abs(value[nonzero]))
            logs = logs + log_factor
        if not np.all(np.isfinite(logs) | np.isneginf(logs)):
            _range("integration: nonfinite quadrature term")
        positive = np.logaddexp(positive, np.where(signs > 0, logs, -np.inf))
        negative = np.logaddexp(negative, np.where(signs < 0, logs, -np.inf))
    if np.any(negative > positive):
        _range("integration: finite sum cannot represent a nonnegative integrand")
    function = positive.copy()
    subtract = np.isfinite(negative) & (negative < positive)
    function[subtract] += np.log(-np.expm1(negative[subtract] - positive[subtract]))
    function[negative == positive] = -np.inf
    return float(np.logaddexp.reduce((function + log_weights).ravel()))


def _bisect_box(box, axis):
    lo, hi = box[axis]
    midpoint = lo + (hi - lo) / 2
    if not math.isfinite(midpoint) or midpoint == lo or midpoint == hi:
        _range("integration: box cannot be bisected")
    return tuple(box[:axis] + (interval,) + box[axis + 1:]
                 for interval in ((lo, midpoint), (midpoint, hi)))


def integrate_pieces(pieces, *, tolerance, initial_degree=4, node_budget=None, _work=None):
    """全片の離散化誤差の幅をtolerance以内に。次数と空間の両方で適応。

    toleranceは積分全体の幅であり、一片ごとの目標ではない。尾と
    正規化後の目標は、呼ぶ側がIntegralEstimateで更に伝播させる。
    """
    tolerance = _number(tolerance, "integration tolerance", positive=True)
    if type(initial_degree) is not int or initial_degree < 1:
        raise ValueError("integration: positive initial degree required")
    work, boxes, serial = _IntegrationWork(node_budget) if _work is None else _work, {}, 0
    pieces = tuple(pieces)
    heap = []
    def add(mapped, box, degree, terms=None, errors=None):
        nonlocal serial
        terms = _box_terms(mapped, box) if terms is None else terms
        if not terms:
            return
        dimension = len(box)
        errors = _quadrature_error(terms, dimension, degree) if errors is None else errors
        error = math.inf if math.inf in errors else _logadd(errors)
        if dimension:
            value = -math.inf if error == math.inf else _quadrature_value(terms, dimension, degree, work)
        else:
            constants = []
            for t in terms:
                sign = 1 if t.coefficient > 0 else -1
                for polynomial, power in t.factors:
                    scalar = polynomial.get(0, Fraction(0))
                    if scalar < 0:
                        if power < 0 or not power.is_integer():
                            _range("integration: constant outside analytic domain")
                        if int(power) % 2:
                            sign = -sign
                constants.append((sign, _log_fraction(abs(t.coefficient)) + t.log_scale))
            value = _signed_log_sum(constants)
        boxes[serial] = (mapped, box, degree, value, error, errors)
        heapq.heappush(heap, (-error, serial))
        serial += 1
    for piece in pieces:
        add(piece.mapped_terms(), ((0., 1.),) * len(piece.bounds), initial_degree)
    target = math.log(tolerance) - math.log(2.)
    while boxes:
        total_error = math.inf if any(b[4] == math.inf for b in boxes.values()) else _logadd(b[4] for b in boxes.values())
        if total_error <= target:
            break
        _, index = heapq.heappop(heap)
        mapped, box, degree, value, error, axis_errors = boxes.pop(index)
        axis = max(range(len(box)), key=lambda k: axis_errors[k])
        children = []
        for child in _bisect_box(box, axis):
            terms = _box_terms(mapped, child)
            errors = _quadrature_error(terms, len(box), degree)
            children.append((child, terms, errors))
        higher_terms = _box_terms(mapped, box)
        higher_errors = _quadrature_error(higher_terms, len(box), degree + 1)
        def error_sum(values):
            return math.inf if any(v == math.inf for v in values) else _logadd(values)
        split_error = error_sum(tuple(error_sum(e) for _, _, e in children))
        higher_error = error_sum(higher_errors)
        # Choose reduction per node cost. Entire/constant functions can finish
        # by increasing degree on one box; no cap on degree or rho is imposed.
        if higher_error + math.log((degree + 1) ** len(box)) <= split_error + math.log(2 * degree ** len(box)):
            if higher_error == math.inf:
                for child, terms, errors in children:
                    add(mapped, child, degree, terms, errors)
            else:
                add(mapped, box, degree + 1, higher_terms, higher_errors)
        else:
            for child, terms, errors in children:
                add(mapped, child, degree, terms, errors)
    return IntegralEstimate(_logadd(b[3] for b in boxes.values()),
        _logadd(b[4] for b in boxes.values()), pieces=len(pieces), boxes=len(boxes),
        max_degree=max((b[2] for b in boxes.values()), default=0), nodes=work.nodes)


@dataclass(frozen=True, slots=True)
class TailDensity:
    """一つの基底の有限のパレート尾。bound_weightは他の基底選択の質量。

    0≤K≤1の事象に対してだけ、残りの質量の上界として使う。
    """
    name: object
    variable: int
    boundary: Fraction
    kappa: float
    mass: float
    bound_weight: Fraction

    def __post_init__(self):
        if type(self.variable) is not int or self.variable < 0:
            raise ValueError("tail density: nonnegative variable index required")
        object.__setattr__(self, "boundary", _fraction(self.boundary))
        object.__setattr__(self, "bound_weight", _fraction(self.bound_weight))
        if self.boundary <= 0 or self.bound_weight < 0:
            raise ValueError("tail density: positive boundary and nonnegative bound weight required")
        _number(self.kappa, "tail density kappa", positive=True)
        _number(self.mass, "tail density mass", positive=True)

    def log_remaining(self, cutoff):
        cutoff = _fraction(cutoff)
        if cutoff < self.boundary:
            raise ValueError("tail cutoff: must be at least the Pareto boundary")
        return (_log_fraction(self.bound_weight) + math.log(self.mass)
                + self.kappa * (_log_fraction(self.boundary) - _log_fraction(cutoff)))


@dataclass(frozen=True, slots=True)
class LinearIntegral:
    dimension: int
    constraints: tuple
    terms: tuple[PowerTerm, ...]
    tails: tuple[TailDensity, ...] = ()

    def __post_init__(self):
        constraints = tuple((tuple(_fraction(a) for a in affine), bool(strict)) for affine, strict in self.constraints)
        if type(self.dimension) is not int or self.dimension < 0:
            raise ValueError("linear integral: nonnegative dimension required")
        if any(len(a) != self.dimension + 1 for a, _ in constraints):
            raise ValueError("linear integral: constraint dimension differs")
        if any(len(f.affine) != self.dimension + 1 for t in self.terms for f in t.factors):
            raise ValueError("linear integral: factor dimension differs")
        if any(t.variable >= self.dimension for t in self.tails) or len({t.name for t in self.tails}) != len(self.tails):
            raise ValueError("linear integral: invalid tail variables")
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "terms", tuple(self.terms))
        object.__setattr__(self, "tails", tuple(self.tails))


def permute_integral(region, order):
    """同じ生の領域の変数順だけを変える。潜在の共有も密度も変えない。"""
    order = tuple(order)
    if sorted(order) != list(range(region.dimension)):
        raise ValueError("integral permutation: expected every variable once")
    def affine(value):
        return (value[0],) + tuple(value[i + 1] for i in order)
    return LinearIntegral(region.dimension, tuple((affine(a), strict) for a, strict in region.constraints),
        tuple(PowerTerm(t.coefficient, tuple(PowerFactor(affine(f.affine), f.power) for f in t.factors), t.log_scale)
              for t in region.terms),
        tuple(TailDensity(t.name, order.index(t.variable), t.boundary, t.kappa, t.mass, t.bound_weight)
              for t in region.tails))


def _remove_affine_variable(affine, variable):
    return affine[:variable + 1] + affine[variable + 2:]


def _has_continuous_volume(dimension, constraints):
    try:
        return next(_linear_pieces(dimension, constraints), None) is not None
    except ValueError as exc:
        if str(exc) != "linear pieces: finite bounds required":
            raise
        return True       # Unbounded pieces require their density/tail treatment.


def _eliminate_density_halfline(region, tail):
    """片の半直線全体で変数に依る因子が基底密度だけの時のみ消す。"""
    variable = tail.variable
    lowers, outer = set(), []
    for affine, strict in region.constraints:
        coefficient = affine[variable + 1]
        if coefficient < 0:
            return None
        if coefficient:
            lowers.add(tuple(-a / coefficient for a in _remove_affine_variable(affine, variable)))
        else:
            outer.append((_remove_affine_variable(affine, variable), strict))
    if not lowers:
        return None
    unit = tuple(Fraction(int(i == variable + 1)) for i in range(region.dimension + 1))
    reduced = []
    for term in region.terms:
        density, factors = [], []
        for factor in term.factors:
            if factor.affine[variable + 1]:
                if factor.affine != unit or factor.power != -tail.kappa - 1:
                    return None
                density.append(factor)
            else:
                factors.append(PowerFactor(_remove_affine_variable(factor.affine, variable), factor.power))
        if len(density) != 1:
            return None
        reduced.append((term, tuple(factors)))
    result = []
    for i, lower in enumerate(sorted(lowers)):
        constraints = outer + [(_affine_subtract(lower, b), k < i)
                               for k, b in enumerate(sorted(lowers)) if b != lower]
        if _clean_constraints(constraints) is None:
            continue
        terms = tuple(PowerTerm(t.coefficient, factors + (PowerFactor(lower, -tail.kappa),),
                                t.log_scale - math.log(tail.kappa)) for t, factors in reduced)
        tails = tuple(TailDensity(t.name, t.variable - int(t.variable > variable), t.boundary,
                                  t.kappa, t.mass, t.bound_weight) for t in region.tails if t != tail)
        result.append(LinearIntegral(region.dimension - 1, tuple(constraints), terms, tails))
    return tuple(result)


def _density_halfline_regions(region):
    pending, result = [region], []
    while pending:
        current = pending.pop()
        if _clean_constraints(current.constraints) is None:
            continue
        for tail in current.tails:
            reduced = _eliminate_density_halfline(current, tail)
            if reduced is not None:
                pending.extend(reversed(reduced))
                break
        else:
            result.append(current)
    return tuple(result)


def _eliminate_separable_interval(region, variable):
    """有限区間の純粋な実数冪を解析的に積分し、上下端の有限和にする。

    logの原始関数や結びついた因子が要る場合は、生の求積の道に残す。
    半直線の消去の条件をこの有限区間の条件に緩めることはしない。
    """
    lowers, uppers, outer = set(), set(), []
    for affine, strict in region.constraints:
        coefficient = affine[variable + 1]
        if coefficient:
            bound = tuple(-a / coefficient for a in _remove_affine_variable(affine, variable))
            (lowers if coefficient > 0 else uppers).add(bound)
        else:
            outer.append((_remove_affine_variable(affine, variable), strict))
    if not lowers or not uppers:
        return None
    unit = tuple(Fraction(int(i == variable + 1)) for i in range(region.dimension + 1))
    reduced = []
    for term in region.terms:
        power, factors = 0., []
        for factor in term.factors:
            if factor.affine[variable + 1]:
                if factor.affine != unit:
                    return None
                power += factor.power
            else:
                factors.append(PowerFactor(_remove_affine_variable(factor.affine, variable), factor.power))
        exponent = power + 1
        if exponent == 0:
            return None
        if not math.isfinite(exponent):
            _range("integration: nonfinite primitive exponent")
        reduced.append((term, tuple(factors), exponent))
    result = []
    for i, lo in enumerate(sorted(lowers)):
        for j, hi in enumerate(sorted(uppers)):
            constraints = outer + [(_affine_subtract(hi, lo), True)]
            constraints += [(_affine_subtract(lo, b), k < i) for k, b in enumerate(sorted(lowers)) if b != lo]
            constraints += [(_affine_subtract(b, hi), k < j) for k, b in enumerate(sorted(uppers)) if b != hi]
            if _clean_constraints(constraints) is None or not _has_continuous_volume(region.dimension - 1, constraints):
                continue
            terms = []
            for term, factors, exponent in reduced:
                sign = 1 if exponent > 0 else -1
                scale = term.log_scale - math.log(abs(exponent))
                terms.append(PowerTerm(sign * term.coefficient, factors + (PowerFactor(hi, exponent),), scale))
                terms.append(PowerTerm(-sign * term.coefficient, factors + (PowerFactor(lo, exponent),), scale))
            tails = tuple(TailDensity(t.name, t.variable - int(t.variable > variable), t.boundary,
                t.kappa, t.mass, t.bound_weight) for t in region.tails if t.variable != variable)
            result.append(LinearIntegral(region.dimension - 1, tuple(constraints), tuple(terms), tails))
    return tuple(result)


def _separable_interval_regions(regions):
    pending, result = list(reversed(regions)), []
    while pending:
        region = pending.pop()
        if _clean_constraints(region.constraints) is None:
            continue
        for variable in range(region.dimension - 1, -1, -1):
            changed = _eliminate_separable_interval(region, variable)
            if changed is not None:
                pending.extend(reversed(changed))
                break
        else:
            result.append(region)
    return tuple(result)


def _closed_polynomial_integral(regions):
    """変数の依存が多項式なら有理数の解析積分。定数の実数冪も誤差0。"""
    by_scale, pieces = {}, 0
    for region in regions:
        region_count = 0
        for term in region.terms:
            polynomial = {(0,) * region.dimension: term.coefficient}
            log_scale = term.log_scale
            for factor in term.factors:
                if not any(factor.affine[1:]):
                    constant = factor.affine[0]
                    if constant <= 0 and (factor.power < 0 or not factor.power.is_integer()):
                        _range("integration: constant outside analytic domain")
                    if factor.power.is_integer():
                        polynomial = {p: c * constant ** int(factor.power) for p, c in polynomial.items()}
                    else:
                        log_scale += factor.power * _log_fraction(constant)
                elif factor.power >= 0 and factor.power.is_integer():
                    polynomial = _polynomial_multiply(polynomial, _affine_power(factor.affine, int(factor.power)))
                else:
                    return None
            value, count = _polytope_integral(region.dimension, region.constraints, polynomial)
            region_count = max(region_count, count)
            if value:
                by_scale[log_scale] = by_scale.get(log_scale, Fraction(0)) + value
        pieces += region_count
    signed = tuple((1 if value > 0 else -1, _log_fraction(abs(value)) + scale)
                   for scale, value in by_scale.items() if value)
    return IntegralEstimate(_signed_log_sum(signed), -math.inf, pieces=pieces, boxes=pieces)


def integrate_linear(region, *, tolerance, finite_tolerance=None, cutoffs=None, initial_degree=4,
                     node_budget=None, eliminate_finite=False):
    """生の線形領域の有限和。半直線は検査して消去、残る尾は質量で包む。

    明示のcutoffsを固定して目標に届かない場合はIntegrationIncomplete。
    自動の場合は有限の切断点を増やし、尾と全片の求積の幅を合算する。
    """
    tolerance = _number(tolerance, "linear integral tolerance", positive=True)
    if finite_tolerance is not None:
        finite_tolerance = _number(finite_tolerance, "finite integral tolerance", positive=True)
    regions = _density_halfline_regions(region)
    if eliminate_finite:
        regions = _separable_interval_regions(regions)
    if not regions:
        return IntegralEstimate(-math.inf, -math.inf)
    closed = _closed_polynomial_integral(regions)
    if closed is not None:
        return closed
    work = _IntegrationWork(node_budget)
    tails = {t.name: t for r in regions for t in r.tails}
    chosen = {} if cutoffs is None else {name: _fraction(c) for name, c in cutoffs.items()}
    if any(name not in tails for name in chosen):
        raise ValueError("linear integral: cutoff names differ from remaining tails")
    try:
        if not chosen:
            pieces = tuple(IntegrationPiece(bounds, r.terms) for r in regions
                           for bounds in _linear_pieces(r.dimension, r.constraints))
            return integrate_pieces(pieces, tolerance=tolerance, initial_degree=initial_degree, _work=work)
    except ValueError as exc:
        if str(exc) != "linear pieces: finite bounds required":
            raise
        if not tails:
            raise ValueError("linear integral: unbounded variables lack a finite-tail bound") from exc
        if cutoffs is not None:
            raise ValueError("linear integral: explicit cutoffs do not bound all remaining variables") from exc
        chosen = {name: t.boundary * 2 for name, t in tails.items()}
    while True:
        log_tail = _logadd(tails[name].log_remaining(c) for name, c in chosen.items())
        if log_tail >= math.log(tolerance):
            if cutoffs is not None:
                raise IntegrationIncomplete("integration: explicit finite cutoffs cannot meet total error budget")
            chosen = {name: c * 2 for name, c in chosen.items()}
            continue
        # Leave half the budget for tail unless a smaller explicit finite goal is given.
        finite_goal = min(tolerance / 2, finite_tolerance) if finite_tolerance is not None else tolerance / 2
        pieces = []
        for r in regions:
            constraints = list(r.constraints)
            for t in r.tails:
                if t.name in chosen:
                    upper = [Fraction(0)] * (r.dimension + 1)
                    upper[0], upper[t.variable + 1] = chosen[t.name], Fraction(-1)
                    constraints.append((tuple(upper), False))
            pieces.extend(IntegrationPiece(bounds, r.terms) for bounds in _linear_pieces(r.dimension, constraints))
        estimate = integrate_pieces(pieces, tolerance=finite_goal, initial_degree=initial_degree,
                                    _work=work).with_tail(log_tail)
        if estimate.log_width <= math.log(tolerance):
            return estimate
        if cutoffs is not None:
            raise IntegrationIncomplete("integration: explicit cutoffs cannot meet total error budget")
        chosen = {name: c * 2 for name, c in chosen.items()}


def _event_order(event):
    return event.run_index, event.seq, str(event.id)


def _timing_order_pairs(timing, selected):
    """受け取りの位置を、同じrunの外の条件と履歴に共通して使う。"""
    selected = frozenset(selected)
    ordinary = sorted((e for e in timing.events.values()
                       if e.id in selected and e.id not in timing.positions), key=_event_order)
    pairs, previous = set(), {}
    for event in ordinary:
        if event.run in previous:
            pairs.add((previous[event.run], event.id))
        previous[event.run] = event.id
    receipts = sorted((timing.events[ref] for ref in timing.positions if ref in selected), key=_event_order)
    previous = {}
    for receipt in receipts:
        for event in ordinary:
            if event.run == receipt.run:
                pairs.add((event.id, receipt.id) if event.id in timing.positions[receipt.id]
                          else (receipt.id, event.id))
        if receipt.run in previous:
            pairs.add((previous[receipt.run], receipt.id))
        previous[receipt.run] = receipt.id
    return tuple(sorted(pairs, key=lambda pair: tuple(str(ref) for ref in pair)))


def _arrival_expressions(kernel, durations, dimension):
    extra = (Fraction(0),) * (dimension - kernel.dimension)
    return {a.attempt: tuple(s + d for s, d in
            zip(kernel._external[a.start_event] + extra, durations[a.attempt]))
            for a in kernel.attempts if durations[a.attempt] is not None}


@dataclass(frozen=True, slots=True)
class _TieRanks:
    by_kernel: Mapping


def _tie_rankings(kernel, durations, dimension, *, kernels=None):
    """各段の一様な選択を同じ写しの全履歴で共有する。

    DPの同じまとまりの連続所要も、同じ始まりなら同着になる。
    異なる連続の一次式の同着は零集合。写し間の選択は独立。
    """

    arrivals = _arrival_expressions(kernel, durations, dimension)
    groups = {}
    for a in kernel.attempts:
        if a.attempt in arrivals:
            key = (kernel.timing.events[a.start_event].run, arrivals[a.attempt])
            groups.setdefault(key, []).append(a.attempt)
    groups = tuple(tuple(sorted(group, key=str)) for group in groups.values() if len(group) > 1)
    if not groups:
        yield Fraction(1), {}
        return
    kernels = tuple({id(k): k for k in (kernels if kernels is not None else (kernel,))}.values())
    programs = []
    for group in groups:
        local = []
        for k in kernels:
            attempts = {a.attempt: a for a in k.attempts}
            before = []
            for ref in group:
                start = k.timing.events[attempts[ref].start_event]
                mask = 0
                for i, other in enumerate(group):
                    attempt = attempts[other]
                    report = k.timing.events.get(attempt.report_event)
                    if (report is not None and not _cross_run_arrival(k.timing, attempt)
                            and report.run == start.run and _event_order(report) < _event_order(start)):
                        mask |= 1 << i
                before.append(mask)
            local.append(tuple(before))
        programs.append(tuple(local))

    def visit(index, ranks, weight):
        if index == len(groups):
            yield weight, _TieRanks({id(k): r for k, r in zip(kernels, ranks)})
            return
        group, before = groups[index], programs[index]

        def extend(stage, remaining, ranks, weight):
            if stage == len(group):
                yield from visit(index + 1, ranks, weight)
                return
            choices = tuple(tuple(i for i, mask in enumerate(p)
                if rem & (1 << i) and not mask & rem) if r is not None else ()
                for p, rem, r in zip(before, remaining, ranks))
            # The SAME independent U_stage in [0,1) selects the canonical
            # floor(U_stage * available_count) in every history. Split at all
            # thresholds, so unions/intersections use one probability law.
            boundaries = {Fraction(0), Fraction(1)}
            for eligible in choices:
                if eligible:
                    boundaries.update(Fraction(i, len(eligible)) for i in range(1, len(eligible)))
            boundaries = sorted(boundaries)
            for lower, upper in zip(boundaries, boundaries[1:]):
                middle = (lower + upper) / 2
                next_remaining, next_ranks = [], []
                for rem, r, eligible in zip(remaining, ranks, choices):
                    if not eligible:
                        next_remaining.append(0)
                        next_ranks.append(None)
                    else:
                        selected = eligible[int(middle * len(eligible))]
                        next_remaining.append(rem ^ (1 << selected))
                        next_ranks.append({**r, group[selected]: stage})
                yield from extend(stage + 1, tuple(next_remaining), tuple(next_ranks),
                                  weight * (upper - lower))

        yield from extend(0, ((1 << len(group)) - 1,) * len(kernels), ranks, weight)
    yield from visit(0, ({},) * len(kernels), Fraction(1))


def _tie_precedes(before, after, arrivals, ranks):
    return (ranks is None or before == after or arrivals[before] != arrivals[after]
            or ranks.get(before, 0) < ranks.get(after, 0))


@dataclass(frozen=True, slots=True)
class HistoryKernel:
    """K_λ(h|d,𝒟)。報告は S+D、共有の出来事は常に一つの変数。

    有限原子の値を固定した核は有理数で解く。読み r の tick 区間は
    [r,r+h)。軸への平行移動後も実際の整数の読みをそのまま使う。
    """

    timing: Timing
    spec: MeasureSpec
    attempts: tuple = field(init=False)
    external_ids: tuple = field(init=False)
    dimension: int = field(init=False)
    _external: Mapping = field(init=False, repr=False)
    _constraints: tuple = field(init=False, repr=False)
    _normalizer: Fraction = field(init=False, repr=False)

    def __post_init__(self):
        # Validation uses no default prior/phase/process.
        _validate_measure_spec(self.spec)
        excluded = _excluded_timing_events(self.timing)
        active = tuple(AttemptTiming(a.attempt, a.job, a.action, a.start_event,
                       tuple(ref for ref in a.check_events if ref not in excluded), a.report_event,
                       "unknown" if a.state == "complete" and _cross_run_arrival(self.timing, a) else a.state)
                       for a in self.timing.attempts if a.state not in ("queued", "unreadable"))
        if len({a.attempt for a in active}) != len(active):
            raise ValueError("history kernel: duplicate attempt")
        reports = {a.report_event for a in active if a.report_event in self.timing.events
                   and not _cross_run_arrival(self.timing, a)}
        external = tuple(e for e in sorted(self.timing.events.values(), key=_event_order)
                         if e.reading is not None and e.id not in reports and e.id not in excluded)
        free = tuple(e for e in external if self.spec.name == "tick" and
                     (e.kind != "start" or self.spec.params["phase"] == "uniform"))
        dimension, expressions, constraints = len(free), {}, []
        indexes = {e.id: i for i, e in enumerate(free)}
        width = self.spec.params["width_ns"] if self.spec.name == "tick" else None
        for e in external:
            expression = [Fraction(e.reading)] + [Fraction(0)] * dimension
            if e.id in indexes:
                expression[0] = Fraction(0)
                expression[indexes[e.id] + 1] = Fraction(1)
                lo = [-Fraction(e.reading)] + expression[1:]
                hi = [Fraction(e.reading + width)] + [-a for a in expression[1:]]
                constraints.extend(((tuple(lo), False), (tuple(hi), True)))
            elif self.spec.name == "tick" and e.kind == "start":
                expression[0] += self.spec.params["phase"]["point_ns"]
            expressions[e.id] = tuple(expression)
        # Only externally imposed order conditions the base external law.
        for before, after in _timing_order_pairs(self.timing, expressions):
            constraints.append((_affine_subtract(expressions[after], expressions[before]), False))
        compatible = True
        if width is not None:
            residues = {}
            for e in self.timing.events.values():
                if e.reading is not None and e.id not in excluded:
                    residue = e.reading % width
                    if e.run in residues and residues[e.run] != residue:
                        compatible = False
                    residues[e.run] = residue
        # Equal-width clock labels form one lattice per run. Its origin shifts
        # with the existing axis translation; no clock-origin default is added.
        normalizer = Fraction(0)
        if compatible:
            normalizer, _ = _polytope_integral(dimension, constraints, {(0,) * dimension: Fraction(1)})
        object.__setattr__(self, "attempts", active)
        object.__setattr__(self, "external_ids", tuple(e.id for e in external))
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "_external", MappingProxyType(expressions))
        object.__setattr__(self, "_constraints", tuple(constraints))
        object.__setattr__(self, "_normalizer", normalizer)

    def integrate(self, durations):
        """(確率 Fraction, 領域の片数)。∞ は線形式へ代入しない。"""
        if set(durations) != {a.attempt for a in self.attempts}:
            raise ValueError("history kernel: expected exactly one duration per readable attempt")
        if any(d is not None and (not isinstance(d, (int, float, Fraction)) or isinstance(d, bool)
                                 or d < 0 or (isinstance(d, float) and not math.isfinite(d)))
               for d in durations.values()):
            raise ValueError("history kernel: expected finite nonnegative durations or infinity")
        if not self._normalizer:
            return Fraction(0), 0
        affine_durations = {ref: None if d is None else
                            (_fraction(d),) + (Fraction(0),) * self.dimension for ref, d in durations.items()}
        numerator, pieces = Fraction(0), 0
        for weight, ranks in _tie_rankings(self, affine_durations, self.dimension):
            constraints = self.raw_constraints(affine_durations, self.dimension, ranks=ranks)
            if constraints is not None:
                value, count = _polytope_integral(self.dimension, constraints,
                                                 {(0,) * self.dimension: Fraction(1)})
                numerator += weight * value
                pieces += count
        probability = numerator / self._normalizer
        if not 0 <= probability <= 1:
            raise ArithmeticError("history kernel: volume does not define a probability")
        return probability, pieces

    def raw_constraints(self, durations, dimension, *, ranks=None):
        """ブロックの所要の一次式を生の変数に足す。原子/∞と同じ核を使う。"""
        if isinstance(ranks, _TieRanks):
            ranks = ranks.by_kernel[id(self)]
            if ranks is None:
                return None
        if dimension < self.dimension or set(durations) != {a.attempt for a in self.attempts}:
            raise ValueError("raw history kernel: invalid dimensions or duration keys")
        if any(d is not None and len(d) != dimension + 1 for d in durations.values()):
            raise ValueError("raw history kernel: duration expression dimension differs")
        extra = (Fraction(0),) * (dimension - self.dimension)
        expressions = {ref: expression + extra for ref, expression in self._external.items()}
        constraints = [(affine + extra, strict) for affine, strict in self._constraints]
        arrivals = _arrival_expressions(self, durations, dimension)
        reports = {a.report_event: a.attempt for a in self.attempts
                   if a.report_event in self.timing.events and not _cross_run_arrival(self.timing, a)}
        for a in self.attempts:
            if a.start_event not in expressions:
                raise ValueError("history kernel: missing start reading")
            start, duration = expressions[a.start_event], durations[a.attempt]
            if duration is None:
                # 時刻が読めなくても、受け取りの事実は同じ古いD<∞の証拠。
                # 受け取りの無い中断・紛失のunknownにはこの条件を足さない。
                if a.state == "complete" or a.report_event in self.timing.events:
                    return None
                continue
            arrival = tuple(s + d for s, d in zip(start, duration))
            if a.report_event in reports:
                # A same-run receipt retains its ordinal fact even when its
                # clock reading is missing; no numerical reading is invented.
                expressions[a.report_event] = arrival
            if a.state == "complete":
                e = self.timing.events[a.report_event]
                expressions[e.id] = arrival
                if self.spec.name == "exact":
                    delta = _affine_subtract(arrival, (Fraction(e.reading),) + (Fraction(0),) * dimension)
                    constraints.extend(((delta, False), (tuple(-x for x in delta), False)))
                else:
                    width = self.spec.params["width_ns"]
                    constraints.extend((((arrival[0] - e.reading,) + arrival[1:], False),
                        ((e.reading + width - arrival[0],) + tuple(-x for x in arrival[1:]), True)))
        # The whole report/external record order is part of h, not the denominator.
        for before, after in _timing_order_pairs(self.timing, expressions):
            constraints.append((_affine_subtract(expressions[after], expressions[before]), False))
        # Starts/checks may separate reports in the full event sequence. Time
        # inequalities are transitive, but they do not constrain discrete tie
        # ranks: apply the report-only subsequence separately in each run.
        for before, after in _timing_order_pairs(self.timing, reports):
            if not _tie_precedes(reports[before], reports[after], arrivals, ranks):
                return None
        # External receipts win an equal-time boundary. Starts are actions,
        # not receipt competitors, and may intervene between these receipts.
        receipts = {**{ref: expression for ref, expression in expressions.items()
                       if self.timing.events[ref].kind != "start"},
                    **{ref: expressions[ref] for ref in reports}}
        for before, after in _timing_order_pairs(self.timing, receipts):
            if before in reports and after not in reports:
                constraints.append((_affine_subtract(expressions[after], expressions[before]), True))
        for a in self.attempts:
            duration = durations[a.attempt]
            if duration is None:
                continue
            start = expressions[a.start_event]
            arrival = tuple(s + d for s, d in zip(start, duration))
            for ref in a.check_events:
                if ref not in expressions:
                    raise ValueError("history kernel: missing shared check reading")
                if ref in reports and not _tie_precedes(reports[ref], a.attempt, arrivals, ranks):
                    return None
                constraints.append((_affine_subtract(arrival, expressions[ref]), False))
            if a.state == "pending":
                # A received same-run report after this start is also an
                # ingestion boundary. read_timing cannot give a numerical
                # check reading for an untimed receipt, but its S+D is shared.
                for ref, report_attempt in reports.items():
                    event = self.timing.events[ref]
                    start_event = self.timing.events[a.start_event]
                    if (event.reading is None and event.run == start_event.run
                            and _event_order(start_event) < _event_order(event)
                            and ref not in a.check_events):
                        if not _tie_precedes(report_attempt, a.attempt, arrivals, ranks):
                            return None
                        constraints.append((_affine_subtract(arrival, expressions[ref]), False))
        return tuple(constraints)

    def __call__(self, durations):
        return self.integrate(durations)[0]

    def log_probability(self, durations):
        return _log_fraction(self(durations))


@dataclass(frozen=True, slots=True)
class ClockMeasure:
    """組み込み exact/tick の QuantityMeasure 実装。"""

    def history_kernel(self, timing, *, lam):
        spec = lam.spec if isinstance(lam, MeasureCandidate) else lam
        return HistoryKernel(timing, spec)


def restricted_growth_strings(size):
    """名札つきの集合分割。試みの順の RGS を辞書順に全て返す。"""
    if type(size) is not int or size < 0:
        raise ValueError("partitions: expected nonnegative size")
    def grow(prefix, largest):
        if len(prefix) == size:
            yield prefix
        else:
            for label in range(largest + 2):
                yield from grow(prefix + (label,), max(largest, label))
    if size == 0:
        yield ()
    else:
        yield from grow((0,), 0)


def _partition_weight(alpha, rgs):
    alpha = _fraction(alpha)
    counts = tuple(rgs.count(i) for i in range(max(rgs, default=-1) + 1))
    numerator = alpha ** len(counts)
    for count in counts:
        numerator *= math.factorial(count - 1)
    denominator = Fraction(1)
    for i in range(len(rgs)):
        denominator *= alpha + i
    return numerator / denominator


def isolated_record_likelihood(spec, duration, reading):
    """他の出来事が無い一試みの周辺。結合の履歴の代わりには使わない。"""
    if duration is None or reading is None:
        return Fraction(int(duration is None and reading is None))
    duration, reading = _fraction(duration), _fraction(reading)
    if spec.name == "exact":
        return Fraction(int(duration == reading))
    if spec.name != "tick":
        raise ValueError("record likelihood: unsupported measure")
    width = spec.params["width_ns"]
    if reading % width:
        return Fraction(0)
    phase = spec.params["phase"]
    if phase == "uniform":
        lo, hi = max(Fraction(0), reading - duration), min(Fraction(width), reading + width - duration)
        return max(Fraction(0), hi - lo) / width
    arrival = phase["point_ns"] + duration
    return Fraction(int(reading <= arrival < reading + width))


@dataclass(frozen=True, slots=True)
class AtomComponent:
    lam: int
    partitions: tuple
    block_atoms: tuple
    allocation: tuple
    counts: tuple

    @property
    def key(self):
        return self.lam, self.partitions, self.block_atoms


@dataclass(frozen=True, slots=True)
class AtomsPosterior:
    """結合の K を保つ分割の和。有限原子の積分と重みは有理数で閉じる。

    同じ原子に着地した別の Polya ブロックも別の項に残す。予測は
    F と λ の結合の重みを使う。情報量・一歩の入口の接続は別の照会。
    """

    priors: Mapping
    measure: MeasurePrior
    timing: Timing
    attempts: tuple
    components: tuple[AtomComponent, ...]
    fraction_weights: tuple[Fraction, ...]
    fraction_evidence: Fraction
    stats: QuantityStats
    log_w: Mapping = field(init=False)
    log_evidence: float = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "priors", MappingProxyType(dict(self.priors)))
        object.__setattr__(self, "log_w", MappingProxyType({c.key: _log_fraction(w)
            for c, w in zip(self.components, self.fraction_weights)}))
        object.__setattr__(self, "log_evidence", _log_fraction(self.fraction_evidence))

    @property
    def fraction_measure_weights(self):
        return tuple(sum((w for c, w in zip(self.components, self.fraction_weights) if c.lam == i), Fraction(0))
                     for i in range(len(self.measure.candidates)))

    @property
    def measure_weights(self):
        """モデルの候補順の対数の事後の重み。構造の 0 は -inf。"""
        return tuple(_log_fraction(w) for w in self.fraction_measure_weights)

    def allocated(self, requests):
        indexes = {a.attempt: i for i, a in enumerate(self.attempts)}
        if any(ref not in indexes for ref in requests):
            raise ValueError("allocated: unknown attempt")
        return _log_fraction(sum((w for c, w in zip(self.components, self.fraction_weights)
            if all(c.allocation[indexes[ref]] == value for ref, value in requests.items())), Fraction(0)))

    def fraction_new_value(self, action):
        """新しい一標本の潜在の値。既存の pending を標本として足さない。"""
        if action not in self.priors:
            raise ValueError("new value: unknown action")
        action_index = tuple(self.priors).index(action)
        prior = self.priors[action]
        total = _fraction(prior.alpha) + sum(a.action == action for a in self.attempts)
        result = {}
        for i, (point, mass) in enumerate(prior.base.params["points"]):
            result[point] = sum((w * (_fraction(prior.alpha) * _fraction(mass) + c.counts[action_index][i]) / total
                for c, w in zip(self.components, self.fraction_weights)), Fraction(0))
        return MappingProxyType(result)

    def new_value(self, action):
        return MappingProxyType({point: _log_fraction(w) for point, w in self.fraction_new_value(action).items()})

    def fraction_isolated_record(self, action, reading):
        """独立の開始位相を持つ新しい孤立した試みの記録の予測。

        今の履歴と共有する外の出来事がある未来の照会には使わない。
        """
        if action not in self.priors:
            raise ValueError("isolated record: unknown action")
        index, prior = tuple(self.priors).index(action), self.priors[action]
        total = _fraction(prior.alpha) + sum(a.action == action for a in self.attempts)
        return sum((weight * sum(((_fraction(prior.alpha) * _fraction(mass) + component.counts[index][i])
                    * isolated_record_likelihood(self.measure.candidates[component.lam].spec, point, reading)
                    for i, (point, mass) in enumerate(prior.base.params["points"])), Fraction(0)) / total
                    for component, weight in zip(self.components, self.fraction_weights)), Fraction(0))


def atoms_posterior(priors, measure, timing):
    """全ての λ・行動ごとの分割・ブロックの原子の選択を正準の順で合算。

    通常の Python の計算資源の例外はそのまま伝える。計算量の停止を
    NumericalRange に置き換えず、分割数や枝数による上限も置かない。
    """
    priors = {action: duration_prior(prior) for action, prior in priors.items()}
    if any(p.base.name != "atoms" for p in priors.values()):
        raise ValueError("atoms posterior: expected finite-atom bases")
    measure = measure_prior(measure)
    kernels = tuple(ClockMeasure().history_kernel(timing, lam=c) for c in measure.candidates)
    attempts = kernels[0].attempts
    if any(a.action not in priors for a in attempts):
        raise ValueError("atoms posterior: unknown action")
    actions = tuple(priors)
    action_indexes = tuple(tuple(i for i, a in enumerate(attempts) if a.action == action) for action in actions)
    partitions = tuple(tuple(restricted_growth_strings(len(indexes))) for indexes in action_indexes)
    components, raw, term_count, branch_count, piece_count = [], [], 0, 0, 0
    for lam, (candidate, kernel) in enumerate(zip(measure.candidates, kernels)):
        for rgs_by_action in product(*partitions):
            term_count += 1
            weight, blocks = _fraction(candidate.weight), []
            for action, indexes, rgs in zip(actions, action_indexes, rgs_by_action):
                weight *= _partition_weight(priors[action].alpha, rgs)
                for label in range(max(rgs, default=-1) + 1):
                    blocks.append((action, tuple(indexes[j] for j, b in enumerate(rgs) if b == label)))
            choices = tuple(tuple((i, point, _fraction(mass)) for i, (point, mass) in
                enumerate(priors[action].base.params["points"]) if mass) for action, _ in blocks)
            for chosen in product(*choices):
                branch_count += 1
                allocation = [None] * len(attempts)
                counts = [[0] * len(priors[action].base.params["points"]) for action in actions]
                block_weight = weight
                for (action, indexes), (atom_index, point, mass) in zip(blocks, chosen):
                    block_weight *= mass       # Once per Polya block, including infinity.
                    counts[actions.index(action)][atom_index] += len(indexes)
                    for i in indexes:
                        allocation[i] = point
                probability, pieces = kernel.integrate({a.attempt: d for a, d in zip(attempts, allocation)})
                piece_count += pieces
                if probability:                # Only exact structural zeros are omitted.
                    components.append(AtomComponent(lam, rgs_by_action, tuple(c[0] for c in chosen),
                        tuple(allocation), tuple(tuple(c) for c in counts)))
                    raw.append(block_weight * probability)
    evidence = sum(raw, Fraction(0))
    if not evidence:
        from .inference import ModelViolation
        raise ModelViolation("quantity: observations have zero probability")
    # Empty history has a single empty partition by the recording convention (§4-4).
    count = term_count if attempts else 1
    return AtomsPosterior(priors, measure, timing, attempts, tuple(components), tuple(w / evidence for w in raw),
        evidence, QuantityStats(partitions=count, final_groups=len(components), integration_pieces=piece_count,
                                allocated_branches=branch_count))


def _base_regions(base):
    """原子/∞・一様区間・パレートを別の項。質量はブロックにつき一回。"""
    if base.name == "atoms":
        return tuple(("atom", point, None, mass, None) for point, mass in base.params["points"] if mass)
    edges = base.params["edges_ns"]
    result = [("uniform", lo, hi, mass, None) for lo, hi, mass in
              zip(edges, edges[1:], base.params["masses"]) if mass]
    tail = base.params["tail"]
    if tail["mass"]:
        result.append(("tail", edges[-1], None, tail["mass"], tail["kappa"]))
    if base.p_inf:
        result.append(("atom", None, None, base.p_inf, None))
    return tuple(result)


def _partition_region(kernel, blocks, choices):
    """自由な時刻＋ブロックごとの所要という生の表現へ、基底の選択を足す。"""
    if not kernel._normalizer:
        return ((None, ()),)
    continuous = tuple(i for i, choice in enumerate(choices) if choice[0] != "atom")
    dimension = kernel.dimension + len(continuous)
    indexes = {b: kernel.dimension + j for j, b in enumerate(continuous)}
    variables = tuple(ref for ref in kernel.external_ids if any(kernel._external[ref][1:])) + tuple(
        (action, indexes_in_history) for i, (action, indexes_in_history) in enumerate(blocks) if i in indexes)
    durations, bounds, factors, tails = {}, [], [], []
    coefficient, log_scale = 1 / kernel._normalizer, 0.
    for i, ((action, attempt_indexes), choice) in enumerate(zip(blocks, choices)):
        kind, lower, upper, mass, kappa = choice
        if kind == "atom":
            expression = None if lower is None else (Fraction(lower),) + (Fraction(0),) * dimension
            coefficient *= _fraction(mass)
        else:
            variable = indexes[i]
            expression = tuple(Fraction(int(j == variable + 1)) for j in range(dimension + 1))
            lo = list(expression)
            lo[0] = -Fraction(lower)
            bounds.append((tuple(lo), False))
            if upper is not None:
                hi = [-a for a in expression]
                hi[0] = Fraction(upper)
                bounds.append((tuple(hi), True))
                coefficient *= _fraction(mass) / (upper - lower)
            else:
                factors.append(PowerFactor(expression, -kappa - 1))
                log_scale += math.log(mass) + math.log(kappa) + kappa * math.log(lower)
                other_mass = math.prod((_fraction(c[3]) for j, c in enumerate(choices) if j != i), start=Fraction(1))
                tails.append(TailDensity((action, attempt_indexes), variable, lower, kappa, mass, other_mass))
            # A finite completion supplies a constant upper bound, even when
            # report/check constraints connect this block with other variables.
            for j in attempt_indexes:
                attempt = kernel.attempts[j]
                if attempt.state == "complete":
                    start, report = kernel.timing.events[attempt.start_event], kernel.timing.events[attempt.report_event]
                    phase = kernel.spec.params["phase"]
                    minimum_start = start.reading + (0 if phase == "uniform" else phase["point_ns"])
                    maximum_duration = report.reading + kernel.spec.params["width_ns"] - minimum_start
                    hi = [-a for a in expression]
                    hi[0] = Fraction(maximum_duration)
                    bounds.append((tuple(hi), True))
        for j in attempt_indexes:
            durations[kernel.attempts[j].attempt] = expression
    # Reverse the first continuous variables, retaining the last innermost.
    # The 4-report chain then uses c,b,a,d and has the specified three pieces.
    order = tuple(range(kernel.dimension)) + tuple(reversed(range(kernel.dimension, dimension - 1))) + (
        (dimension - 1,) if continuous else ())
    regions = []
    for weight, ranks in _tie_rankings(kernel, durations, dimension):
        constraints = kernel.raw_constraints(durations, dimension, ranks=ranks)
        if constraints is None:
            regions.append((None, ()))
            continue
        region = LinearIntegral(dimension, constraints + tuple(bounds),
            (PowerTerm(coefficient * weight, tuple(factors), log_scale),), tuple(tails))
        regions.append((permute_integral(region, order), tuple(variables[i] for i in order)))
    return tuple(regions)


@dataclass(frozen=True, slots=True)
class PartitionIntegral:
    lam: int
    partitions: tuple
    blocks: tuple
    base_choices: tuple
    variables: tuple
    weight: Fraction
    region: LinearIntegral | None


@dataclass(frozen=True, slots=True)
class PartitionEvidence:
    """一般の基底の分割の全和と、正規化した成分の区間。

    生の領域を保持する。連続のブロックの平均で一つのDPに置き換えない。
    情報/未来の照会はこの領域を条件づけて更に計算する。
    """
    priors: Mapping
    measure: MeasurePrior
    timing: Timing
    entries: tuple[PartitionIntegral, ...]
    estimates: tuple[IntegralEstimate, ...]
    evidence: IntegralEstimate
    component_probabilities: tuple[ProbabilityInterval, ...]
    measure_probabilities: tuple[ProbabilityInterval, ...]
    stats: QuantityStats
    tolerance: float

    def __post_init__(self):
        object.__setattr__(self, "priors", MappingProxyType(dict(self.priors)))


def partition_evidence(priors, measure, timing, *, tolerance, initial_degree=4, node_budget=None,
                       eliminate_finite=False):
    """piecewise/atomsの結合のKを、全λ・全分割の生の積分に保つ。

    全成分の正規化後の区間の幅の和もtolerance以内になるまで求積を
    精密にする。各積分がtolerance以内という条件で停止しない。
    情報量までの誤差伝播と停止条件は③の照会側にも必要。
    """
    priors = {action: duration_prior(p) for action, p in priors.items()}
    measure, tolerance = measure_prior(measure), _number(tolerance, "posterior tolerance", positive=True)
    if any(c.spec.name == "exact" for c in measure.candidates) and any(p.base.name != "atoms" for p in priors.values()):
        raise ValueError("exact with piecewise base has infinite information")
    kernels = tuple(ClockMeasure().history_kernel(timing, lam=c) for c in measure.candidates)
    attempts, actions = kernels[0].attempts, tuple(priors)
    if any(a.action not in priors for a in attempts):
        raise ValueError("partition evidence: unknown action")
    indexes = tuple(tuple(i for i, a in enumerate(attempts) if a.action == action) for action in actions)
    partitions = tuple(tuple(restricted_growth_strings(len(group))) for group in indexes)
    entries, term_count = [], 0
    for lam, (candidate, kernel) in enumerate(zip(measure.candidates, kernels)):
        for rgs_by_action in product(*partitions):
            term_count += 1
            weight, blocks = _fraction(candidate.weight), []
            for action, group, rgs in zip(actions, indexes, rgs_by_action):
                weight *= _partition_weight(priors[action].alpha, rgs)
                blocks.extend((action, tuple(group[j] for j, b in enumerate(rgs) if b == label))
                              for label in range(max(rgs, default=-1) + 1))
            blocks = tuple(blocks)
            for chosen in product(*(_base_regions(priors[action].base) for action, _ in blocks)):
                for region, variables in _partition_region(kernel, blocks, chosen):
                    entries.append(PartitionIntegral(lam, rgs_by_action, blocks, chosen, variables, weight, region))
    work = _IntegrationWork(node_budget)
    goal = tolerance / (4 * max(len(entries), 1))
    if goal == 0:
        _range("posterior: positive integration budget disappeared")
    while True:
        estimates = []
        for entry in entries:
            if entry.region is None:
                estimates.append(IntegralEstimate(-math.inf, -math.inf))
                continue
            remaining = None if work.limit is None else work.limit - work.nodes
            # Allocate after multiplying the partition/measure weight.
            log_goal = math.log(goal) - _log_fraction(entry.weight)
            if log_goal > math.log(float.fromhex('0x1.fffffffffffffp+1023')):
                raw_goal = float.fromhex('0x1.fffffffffffffp+1023')
            else:
                raw_goal = math.exp(log_goal)
            if raw_goal == 0:
                _range("posterior: positive raw integration budget disappeared")
            estimate = integrate_linear(entry.region, tolerance=raw_goal, initial_degree=initial_degree,
                                        node_budget=remaining, eliminate_finite=eliminate_finite)
            work.consume(estimate.nodes)
            estimates.append(estimate)
        estimates = tuple(estimates)
        evidence = sum_integrals(estimates, (entry.weight for entry in entries))
        if evidence.log_upper == -math.inf:
            from .inference import ModelViolation
            raise ModelViolation("quantity: observations have zero probability")
        weighted = tuple(sum_integrals((e,), (entry.weight,)) for entry, e in zip(entries, estimates))
        probabilities = tuple(condition_probability(e, evidence) for e in weighted)
        if _logadd(p.log_width for p in probabilities) <= math.log(tolerance) and evidence.log_width <= math.log(tolerance):
            break
        goal /= 4
        if goal == 0:
            _range("posterior: integration budget cannot be represented")
    measure_probabilities = []
    for lam in range(len(measure.candidates)):
        selected = tuple(i for i, entry in enumerate(entries) if entry.lam == lam)
        if len(selected) == len(entries):
            measure_probabilities.append(ProbabilityInterval(0., 0.))
        else:
            numerator = sum_integrals((estimates[i] for i in selected), (entries[i].weight for i in selected))
            measure_probabilities.append(condition_probability(numerator, evidence))
    stats = QuantityStats(partitions=term_count if attempts else 1,
        final_groups=sum(e.log_upper != -math.inf for e in estimates), allocated_branches=len(entries),
        integration_pieces=evidence.pieces, integration_boxes=evidence.boxes, integration_nodes=work.nodes,
        max_integration_degree=evidence.max_degree)
    return PartitionEvidence(priors, measure, timing, tuple(entries), estimates, evidence,
                             probabilities, tuple(measure_probabilities), stats, tolerance)


@dataclass(frozen=True, slots=True)
class AtomLikelihood:
    """基底の原子の順の非負の核。値は入力にだけ置く。"""
    values: tuple

    def __post_init__(self):
        values = tuple(_fraction(v) for v in self.values)
        if not values or any(not 0 <= v <= 1 for v in values):
            raise ValueError("atom likelihood: expected probabilities")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class PolynomialPiece:
    lower: Fraction
    upper: Fraction | None
    coefficients: tuple

    def __post_init__(self):
        lower, upper = _fraction(self.lower), None if self.upper is None else _fraction(self.upper)
        coefficients = tuple(_fraction(c) for c in self.coefficients)
        if lower < 0 or (upper is not None and upper <= lower) or not coefficients:
            raise ValueError("polynomial piece: expected nonempty interval and polynomial")
        while len(coefficients) > 1 and coefficients[-1] == 0:
            coefficients = coefficients[:-1]
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)
        object.__setattr__(self, "coefficients", coefficients)


@dataclass(frozen=True, slots=True)
class PolynomialLikelihood:
    """[0,∞) を覆う区分多項式。核が非負で有界なことは供給側の約束。

    ∞ の値は別の入力。半直線上の非定数の多項式は有界な核でない。
    パレートの密度だけを残す半直線の消去にもこの条件が必要。
    """
    pieces: tuple[PolynomialPiece, ...]
    at_infinity: Fraction

    def __post_init__(self):
        pieces, at_infinity = tuple(self.pieces), _fraction(self.at_infinity)
        if (not pieces or pieces[0].lower != 0 or pieces[-1].upper is not None
                or any(a.upper != b.lower for a, b in zip(pieces, pieces[1:]))
                or not 0 <= at_infinity <= 1):
            raise ValueError("polynomial likelihood: expected exhaustive adjacent pieces")
        if any(pieces[-1].coefficients[1:]) or not 0 <= pieces[-1].coefficients[0] <= 1:
            raise ValueError("polynomial likelihood: unbounded interval must have a constant probability")
        merged = []
        for piece in pieces:
            if merged and merged[-1].coefficients == piece.coefficients:
                merged[-1] = PolynomialPiece(merged[-1].lower, piece.upper, piece.coefficients)
            else:
                merged.append(piece)
        object.__setattr__(self, "pieces", tuple(merged))
        object.__setattr__(self, "at_infinity", at_infinity)

    def value(self, point):
        if point is None:
            return self.at_infinity
        for piece in self.pieces:
            if piece.lower <= point and (piece.upper is None or point < piece.upper):
                value = Fraction(0)
                for coefficient in reversed(piece.coefficients):
                    value = value * point + coefficient
                if not 0 <= value <= 1:
                    raise ValueError("polynomial likelihood: value is not a probability")
                return value
        raise ValueError("polynomial likelihood: point outside domain")


def _univariate_multiply(left, right):
    result = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] += a * b
    while len(result) > 1 and result[-1] == 0:
        result.pop()
    return tuple(result)


def _product_polynomial_pieces(kernels, powers):
    active = tuple((kernel, n) for kernel, n in zip(kernels, powers) if n)
    boundaries = sorted({Fraction(0)} | {p.lower for k, _ in active for p in k.pieces})
    for lower, upper in zip(boundaries, boundaries[1:] + [None]):
        polynomial = (Fraction(1),)
        for kernel, n in active:
            piece = next(p for p in kernel.pieces if p.lower <= lower and (p.upper is None or lower < p.upper))
            for _ in range(n):
                polynomial = _univariate_multiply(polynomial, piece.coefficients)
        yield lower, upper, polynomial


def _signed_log_sum(terms):
    positive = _logadd(v for sign, v in terms if sign > 0)
    negative = _logadd(v for sign, v in terms if sign < 0)
    if negative == -math.inf:
        return positive
    if positive <= negative:
        _range("base: cancellation cannot represent a positive polynomial moment")
    return positive + math.log(-math.expm1(negative - positive))


def _kernel_moment(base, kernels, powers):
    """(log μ_b, 有理数で閉じる時の μ_b)。非定数の半直線は消さない。"""
    if base.name == "atoms":
        total = Fraction(0)
        for i, (point, mass) in enumerate(base.params["points"]):
            term = _fraction(mass)
            for kernel, n in zip(kernels, powers):
                if n:
                    value = kernel.values[i] if isinstance(kernel, AtomLikelihood) else kernel.value(point)
                    term *= value ** n
            total += term
        return _log_fraction(total), total
    if any(not isinstance(k, PolynomialLikelihood) for k in kernels):
        raise ValueError("piecewise base: expected polynomial likelihoods")
    at_infinity = _fraction(base.p_inf)
    for k, n in zip(kernels, powers):
        at_infinity *= k.at_infinity ** n
    exact, tail_terms = at_infinity, []
    edges, masses, tail = base.params["edges_ns"], base.params["masses"], base.params["tail"]
    for lower, upper, coefficients in _product_polynomial_pieces(kernels, powers):
        if not any(coefficients):
            continue
        for a, b, mass in zip(edges, edges[1:], masses):
            lo, hi = max(lower, a), b if upper is None else min(upper, b)
            if mass and lo < hi:
                value = sum((coefficient * (hi ** (m + 1) - lo ** (m + 1)) / (m + 1)
                             for m, coefficient in enumerate(coefficients)), Fraction(0))
                if value < 0:
                    raise ValueError("polynomial likelihood: negative integral")
                exact += _fraction(mass) * value / (b - a)
        lo = max(lower, edges[-1])
        if not tail["mass"] or (upper is not None and lo >= upper):
            continue
        if upper is None:
            if any(coefficients[1:]):
                raise ValueError("pareto: halfline elimination requires density-only dependence")
            coefficient = coefficients[0]
            if coefficient < 0:
                raise ValueError("polynomial likelihood: negative tail probability")
            if coefficient:
                if lo == edges[-1]:
                    exact += coefficient * _fraction(tail["mass"])
                else:
                    tail_terms.append(_log_fraction(coefficient) + base.log_finite_tail(lo))
        else:
            # Only the tail density on this interval. Do not integrate the uniform
            # part twice through BaseSpec.log_interval_moment.
            terms = [(1 if coefficient > 0 else -1,
                      _log_fraction(abs(coefficient))
                      + _pareto_log_moment(tail["kappa"], tail["mass"], edges[-1], m, lo, upper))
                     for m, coefficient in enumerate(coefficients) if coefficient]
            tail_terms.append(_signed_log_sum(terms))
    if not tail_terms:
        return _log_fraction(exact), exact
    return _logadd((_log_fraction(exact), *tail_terms)), None


class MultiplicityMoments:
    """分解を証明した積の核のための厳密な多重度の漸化式 (§4-6)。

    結合の K をこの形に仮定して置き換えない。履歴・補助の核は同じ
    種類の個数で表し、Z は上昇階乗を含めて正規化する。
    """

    def __init__(self, prior, kernels):
        self.prior, self._input_kernels = duration_prior(prior), tuple(kernels)
        if not self._input_kernels:
            raise ValueError("multiplicity: expected kernel types")
        if any(not isinstance(k, (AtomLikelihood, PolynomialLikelihood)) for k in self._input_kernels):
            raise ValueError("multiplicity: unsupported likelihood")
        self.kernels = tuple(dict.fromkeys(self._input_kernels))
        self._types = tuple(self.kernels.index(k) for k in self._input_kernels)
        if self.prior.base.name == "atoms":
            size = len(self.prior.base.params["points"])
            if any(isinstance(k, AtomLikelihood) and len(k.values) != size for k in self.kernels):
                raise ValueError("multiplicity: atom likelihood shape differs from base")
        self._mu = lru_cache(None)(lambda counts: _kernel_moment(self.prior.base, self.kernels, counts))
        zero = (0,) * len(self.kernels)
        self._log_cache, self._fraction_cache = {zero: 0.}, {zero: Fraction(1)}

    def _counts(self, counts):
        counts = tuple(counts)
        if len(counts) != len(self._input_kernels) or any(type(n) is not int or n < 0 for n in counts):
            raise ValueError("multiplicity: expected nonnegative counts per kernel type")
        return tuple(sum(n for t, n in zip(self._types, counts) if t == i) for i in range(len(self.kernels)))

    def _blocks(self, counts):
        i = next(i for i, n in enumerate(counts) if n)
        for block in product(*(range(n + 1) for n in counts)):
            if block[i] == 0:
                continue
            ways = math.comb(counts[i] - 1, block[i] - 1)
            for j, (n, b) in enumerate(zip(counts, block)):
                if j != i:
                    ways *= math.comb(n, b)
            yield block, ways * math.factorial(sum(block) - 1), tuple(n - b for n, b in zip(counts, block))

    def _compute_log_c(self, counts):
        if not any(counts):
            return 0.
        terms = []
        for block, ways, remaining in self._blocks(counts):
            moment = self._mu(block)[0]
            if moment != -math.inf:
                rest = self._log_cache[remaining]
                if rest != -math.inf:
                    terms.append(math.log(ways) + moment + rest)
        total = _logadd(terms)
        return math.log(self.prior.alpha) + total if total != -math.inf else total

    def _compute_fraction_c(self, counts):
        if not any(counts):
            return Fraction(1)
        total = Fraction(0)
        for block, ways, remaining in self._blocks(counts):
            moment = self._mu(block)[1]
            if moment is None:
                raise ValueError("multiplicity: moment is not a rational closed form")
            total += ways * moment * self._fraction_cache[remaining]
        return _fraction(self.prior.alpha) * total

    def _ensure(self, counts, rational):
        cache = self._fraction_cache if rational else self._log_cache
        compute = self._compute_fraction_c if rational else self._compute_log_c
        # Every n-b precedes n in this componentwise grid. No Python recursion
        # depth or maximum number of replica/series terms becomes a cutoff.
        for state in product(*(range(n + 1) for n in counts)):
            if state not in cache:
                cache[state] = compute(state)
        return cache[counts]

    def log_z(self, counts):
        return self._log_z_counts(self._counts(counts))

    def _log_z_counts(self, counts):
        denominator = math.fsum(_logadd((math.log(self.prior.alpha), math.log(i) if i else -math.inf))
                                for i in range(sum(counts)))
        result = self._ensure(counts, False) - denominator
        if result != -math.inf and not math.isfinite(result):
            _range("multiplicity: normalized moment exceeds numerical range")
        return result

    def fraction_z(self, counts):
        counts = self._counts(counts)
        denominator = Fraction(1)
        for i in range(sum(counts)):
            denominator *= _fraction(self.prior.alpha) + i
        return self._ensure(counts, True) / denominator

    def log_ratio(self, history, added):
        history, added = self._counts(history), self._counts(added)
        normalizer = self._log_z_counts(history)
        if normalizer == -math.inf:
            from .inference import ModelViolation
            raise ModelViolation("quantity: observations have zero probability")
        return self._log_z_counts(tuple(n + k for n, k in zip(history, added))) - normalizer

    @property
    def cached_states(self):
        return len(self._log_cache)


def _logadd(values):
    values = tuple(values)
    maximum = max(values, default=-math.inf)
    if maximum == -math.inf:
        return maximum
    if not math.isfinite(maximum):
        _range("quantity: nonfinite log weight")
    shifted = tuple(v - maximum for v in values if v != -math.inf)
    if any(not math.isfinite(v) for v in shifted):
        _range("quantity: log weight difference exceeds numerical range")
    result = maximum + math.log(math.fsum(math.exp(v) for v in shifted))
    if not math.isfinite(result):
        _range("quantity: log sum exceeds numerical range")
    return result


def _normalize(table):
    maximum = max(table.values(), default=-math.inf)
    if maximum == -math.inf:
        from .inference import ModelViolation
        raise ModelViolation("quantity: observations have zero probability")
    shifted = {key: value - maximum for key, value in table.items()}
    if any(not math.isfinite(v) for v in shifted.values()):
        _range("quantity: normalized log weight exceeds numerical range")
    offset = _logadd(shifted.values())
    return {key: value - offset for key, value in shifted.items()}, maximum + offset


def _count_vectors(total, size):
    if size == 1:
        yield (total,)
    else:
        for first in range(total + 1):
            for rest in _count_vectors(total - first, size - 1):
                yield (first,) + rest


def _multinomial(counts):
    result, remaining = 1, sum(counts)
    for count in counts:
        result *= math.comb(remaining, count)
        remaining -= count
    return result


def _simplex_groups(sizes, counts):
    offset, result = 0, []
    for size in sizes:
        result.append(counts[offset:offset + size])
        offset += size
    return tuple(result)


@dataclass(frozen=True, slots=True)
class SimplexPolynomial:
    """Fの単体ごとの斉次多項式。係数は非負、Bernsteinの値は[0,1]。

    項は普通の単項式の係数。補集合は単体の1=(Σ_v F_v)^nから作る。
    写しを掛けても潜在のFは同じ。外の時刻Tはこの型に入らない。
    """
    sizes: tuple
    degrees: tuple
    coefficients: Mapping

    def __post_init__(self):
        sizes, degrees = tuple(self.sizes), tuple(self.degrees)
        if (len(sizes) != len(degrees) or any(type(s) is not int or s < 1 for s in sizes)
                or any(type(d) is not int or d < 0 for d in degrees)):
            raise ValueError("simplex polynomial: invalid sizes or degrees")
        coefficients = {}
        for key, value in self.coefficients.items():
            key, value = tuple(key), _fraction(value)
            if len(key) != sum(sizes) or any(type(c) is not int or c < 0 for c in key):
                raise ValueError("simplex polynomial: invalid count vector")
            groups = _simplex_groups(sizes, key)
            if tuple(map(sum, groups)) != degrees:
                raise ValueError("simplex polynomial: nonhomogeneous count vector")
            if not 0 <= value <= math.prod(_multinomial(g) for g in groups):
                raise ValueError("simplex polynomial: control probability outside [0,1]")
            if value:
                coefficients[key] = value
        object.__setattr__(self, "sizes", sizes)
        object.__setattr__(self, "degrees", degrees)
        object.__setattr__(self, "coefficients", MappingProxyType(dict(sorted(coefficients.items()))))

    @classmethod
    def constant(cls, sizes, value):
        return cls(tuple(sizes), (0,) * len(sizes), {(0,) * sum(sizes): _fraction(value)})

    @classmethod
    def one(cls, sizes, degrees):
        coefficients = {}
        for groups in product(*(_count_vectors(d, s) for s, d in zip(sizes, degrees))):
            counts = tuple(c for group in groups for c in group)
            coefficients[counts] = Fraction(math.prod(_multinomial(g) for g in groups))
        return cls(sizes, degrees, coefficients)

    def multiply(self, other):
        if self.sizes != other.sizes:
            raise ValueError("simplex polynomial: different latent variables")
        coefficients = {}
        for left, a in self.coefficients.items():
            for right, b in other.coefficients.items():
                key = tuple(x + y for x, y in zip(left, right))
                coefficients[key] = coefficients.get(key, Fraction(0)) + a * b
        return SimplexPolynomial(self.sizes, tuple(a + b for a, b in zip(self.degrees, other.degrees)), coefficients)

    def scale(self, weight):
        weight = _fraction(weight)
        return SimplexPolynomial(self.sizes, self.degrees, {k: weight * v for k, v in self.coefficients.items()})

    def elevate(self, degrees):
        degrees = tuple(degrees)
        if len(degrees) != len(self.degrees):
            raise ValueError("simplex polynomial: different number of latent groups")
        extra = tuple(d - old for d, old in zip(degrees, self.degrees))
        if len(extra) != len(self.degrees) or any(d < 0 for d in extra):
            raise ValueError("simplex polynomial: cannot lower degree")
        if not self.coefficients:
            return SimplexPolynomial(self.sizes, degrees, {})
        return self if not any(extra) else self.multiply(SimplexPolynomial.one(self.sizes, extra))

    def add(self, other):
        if self.sizes != other.sizes:
            raise ValueError("simplex polynomial: different latent variables")
        degrees = tuple(max(a, b) for a, b in zip(self.degrees, other.degrees))
        coefficients = dict(self.elevate(degrees).coefficients)
        for key, value in other.elevate(degrees).coefficients.items():
            coefficients[key] = coefficients.get(key, Fraction(0)) + value
        return SimplexPolynomial(self.sizes, degrees, coefficients)

    def complement(self):
        one = SimplexPolynomial.one(self.sizes, self.degrees)
        return SimplexPolynomial(self.sizes, self.degrees,
            {key: value - self.coefficients.get(key, Fraction(0)) for key, value in one.coefficients.items()})

    def constant_value(self):
        if not self.coefficients:
            return Fraction(0)
        if len(self.coefficients) != math.prod(math.comb(d + s - 1, s - 1) for s, d in zip(self.sizes, self.degrees)):
            return None
        ratios = {value / math.prod(_multinomial(g) for g in _simplex_groups(self.sizes, key))
                  for key, value in self.coefficients.items()}
        return next(iter(ratios)) if len(ratios) == 1 else None

    def ratio_to(self, denominator):
        if self.sizes != denominator.sizes or not denominator.coefficients:
            return None
        degrees = tuple(max(a, b) for a, b in zip(self.degrees, denominator.degrees))
        numerator, denominator = self.elevate(degrees), denominator.elevate(degrees)
        key = next(iter(denominator.coefficients))
        ratio = numerator.coefficients.get(key, Fraction(0)) / denominator.coefficients[key]
        return ratio if all(numerator.coefficients.get(k, Fraction(0)) == ratio * denominator.coefficients.get(k, Fraction(0))
            for k in numerator.coefficients.keys() | denominator.coefficients.keys()) else None

    def reduced(self):
        """ΣF=1による次数の引き上げを逆にする。同じ関数を厳密に保つ。"""
        result = self
        for axis, size in enumerate(self.sizes):
            pivot = sum(self.sizes[:axis + 1]) - 1
            while result.degrees[axis]:
                residual, quotient = dict(result.coefficients), {}
                # Divide by the last coordinate plus the other coordinates.
                # Its leading coordinate decreases, so the finite division ends.
                pending = sorted(residual, key=lambda k: (-k[pivot], k))
                failed = False
                for key in pending:
                    value = residual.get(key, Fraction(0))
                    if not value:
                        continue
                    if not key[pivot] or value < 0:
                        failed = True
                        break
                    lower = list(key)
                    lower[pivot] -= 1
                    lower = tuple(lower)
                    quotient[lower] = value
                    for coordinate in range(pivot - size + 1, pivot + 1):
                        term = list(lower)
                        term[coordinate] += 1
                        term = tuple(term)
                        residual[term] = residual.get(term, Fraction(0)) - value
                if failed or any(residual.values()):
                    break
                degrees = list(result.degrees)
                degrees[axis] -= 1
                if any(value > math.prod(_multinomial(g) for g in _simplex_groups(result.sizes, key))
                       for key, value in quotient.items()):
                    # A lower degree may have controls outside [0,1] even when
                    # the elevated probability satisfies this representation's contract.
                    break
                result = SimplexPolynomial(result.sizes, tuple(degrees), quotient)
        return result


class AtomicPolynomialMeasure:
    """全行動の有限原子のDPの、同じFを共有する写しの厳密な積分。

    Kを先に時刻について積分し、有限の全割り振りを個数の単項式へ
    まとめる。独立のTを共有するFへ混ぜ込まず、λも混ぜ直さない。
    """
    def __init__(self, priors):
        self.priors = MappingProxyType({a: duration_prior(p) for a, p in priors.items()})
        if any(p.base.name != "atoms" for p in self.priors.values()):
            raise ValueError("atomic polynomial measure: finite atoms required")
        self.actions = tuple(self.priors)
        self.points = tuple(tuple(point for point, mass in p.base.params["points"] if mass) for p in self.priors.values())
        self.beta = tuple(tuple(_fraction(p.alpha) * _fraction(mass) for _, mass in p.base.params["points"] if mass)
                          for p in self.priors.values())
        self.sizes = tuple(map(len, self.points))
        self._rising, self._moments = {}, {}

    def _rising_value(self, value, order):
        values = self._rising.setdefault(value, [Fraction(1)])
        while len(values) <= order:
            values.append(values[-1] * (value + len(values) - 1))
        return values[order]

    def moment(self, counts):
        counts = tuple(counts)
        if counts not in self._moments:
            if len(counts) != sum(self.sizes) or any(type(c) is not int or c < 0 for c in counts):
                raise ValueError("atomic moment: invalid count vector")
            result = Fraction(1)
            for beta, group in zip(self.beta, _simplex_groups(self.sizes, counts)):
                result *= math.prod((self._rising_value(b, n) for b, n in zip(beta, group)), start=Fraction(1))
                result /= self._rising_value(sum(beta), sum(group))
            self._moments[counts] = result
        return self._moments[counts]

    def expectation(self, polynomial):
        if polynomial.sizes != self.sizes:
            raise ValueError("atomic expectation: different latent variables")
        value = sum((coefficient * self.moment(key) for key, coefficient in polynomial.coefficients.items()), Fraction(0))
        if not 0 <= value <= 1:
            raise ArithmeticError("atomic expectation: not a probability")
        return value

    def likelihood(self, kernel):
        attempts = tuple(kernel.attempts)
        if any(a.action not in self.priors for a in attempts):
            raise ValueError("atomic likelihood: unknown action")
        indexes = tuple(self.actions.index(a.action) for a in attempts)
        degrees = tuple(indexes.count(i) for i in range(len(self.actions)))
        offsets = tuple(sum(self.sizes[:i]) for i in range(len(self.actions)))
        coefficients = {}
        for assignment in product(*(range(self.sizes[i]) for i in indexes)):
            durations = {a.attempt: self.points[i][v] for a, i, v in zip(attempts, indexes, assignment)}
            probability = _fraction(kernel(durations))
            if not 0 <= probability <= 1:
                raise ValueError("atomic likelihood: kernel is not a normalized probability")
            counts = [0] * sum(self.sizes)
            for i, v in zip(indexes, assignment):
                counts[offsets[i] + v] += 1
            counts = tuple(counts)
            coefficients[counts] = coefficients.get(counts, Fraction(0)) + probability
        return SimplexPolynomial(self.sizes, degrees, coefficients)


def _log_phi_fraction(probability):
    """-p log pの対数。pが1に極端に近い時も正を0にしない。"""
    probability = _fraction(probability)
    if probability in (0, 1):
        return -math.inf
    if not 0 < probability < 1:
        raise ValueError("entropy: expected probability")
    if probability >= Fraction(1, 2):
        log_delta = _log_fraction(1 - probability)
        delta = math.exp(log_delta)
        ratio = -math.log1p(-delta) / delta if delta else 1.
        return math.log1p(-delta) + log_delta + math.log(ratio)
    log_p = _log_fraction(probability)
    return log_p + math.log(-log_p)


def _closed_phi_monomial(measure, polynomial):
    """単項式cΠF_v^nのφはDPの対数モーメントで閉じる (誤差0)。"""
    constant = polynomial.constant_value()
    if constant is not None:
        return _log_phi_fraction(constant)
    if len(polynomial.coefficients) != 1:
        return None
    counts, coefficient = next(iter(polynomial.coefficients.items()))
    terms = [-_log_fraction(coefficient)]
    for beta, group in zip(measure.beta, _simplex_groups(measure.sizes, counts)):
        total = sum(beta) + sum(group)
        for b, n in zip(beta, group):
            if not n:
                continue
            coordinate = b + n
            if (coordinate.denominator == total.denominator == 1
                    and total - coordinate <= sum(group) + len(beta)):
                delta = math.fsum(1 / k for k in range(int(coordinate), int(total)))
            else:
                from scipy.special import digamma
                try:
                    delta = float(digamma(float(total)) - digamma(float(coordinate)))
                except (OverflowError, FloatingPointError):
                    _range("information: closed logarithmic moment exceeds numerical range")
            terms.append(n * delta)
    factor = math.fsum(terms)
    if factor <= 0 or not math.isfinite(factor):
        _range("information: closed logarithmic moment disappeared or is nonfinite")
    return _log_fraction(coefficient * measure.moment(counts)) + math.log(factor)


class PhiSeries:
    """E[φ(P)]の正の項。補集合も写しも同じ全行動のFを共有する。"""
    def __init__(self, measure, probability, *, closed_forms=False):
        self.measure, self.probability = measure, probability
        self.closed = _closed_phi_monomial(measure, probability.reduced()) if closed_forms else None
        self.constant = probability.constant_value()
        self.complement = probability.complement() if self.constant is None else 1 - self.constant
        self.power = SimplexPolynomial.constant(measure.sizes, 1) if self.constant is None else Fraction(1)
        self._next, self._logs, self.terms = None, [], 0

    def advance(self):
        self.terms += 1
        if self.closed is not None or self.constant in (0, 1):
            return
        if self.constant is not None:
            self.power *= self.complement
            moment = self.constant * self.power
        else:
            self.power = self._next if self._next is not None else self.power.multiply(self.complement)
            self._next = None
            moment = self.measure.expectation(self.probability.multiply(self.power))
        self._logs.append(_log_fraction(moment) - math.log(self.terms))

    @property
    def log_value(self):
        return self.closed if self.closed is not None else _logadd(self._logs)

    @property
    def log_remainder(self):
        if self.closed is not None or self.constant in (0, 1):
            return -math.inf
        if self.constant is not None:
            value = self.power * self.complement
        else:
            if self._next is None:
                self._next = self.power.multiply(self.complement)
            value = self.measure.expectation(self._next)
        return _log_fraction(value) - math.log(self.terms + 1)


def _polynomial_grid_logs(polynomial, coordinates, shape):
    """正の単項式を対数で合算。小さい係数を構造の0にしない。"""
    import numpy as np
    result = np.full(shape, -np.inf)
    for counts, coefficient in polynomial.coefficients.items():
        value = _log_fraction(coefficient)
        for group, x in zip(_simplex_groups(polynomial.sizes, counts), coordinates):
            if sum(group):
                value = value + group[0] * np.log(x) + group[1] * np.log1p(-x)
        result = np.logaddexp(result, value)
    return result


class _EnclosedPhi:
    """同じφの積分の下界と残り。Gaussに渡した次数も計測する。"""
    def __init__(self, log_value, log_remainder, terms, nodes):
        self.log_value, self.log_remainder = log_value, log_remainder
        self.terms, self.integration_nodes = terms, nodes

    def advance(self):
        # This enclosure already meets its allocated part of the total budget.
        pass


def _bounded_phi_quadrature(measure, probability, log_goal, series_budget, work=None):
    """一様な2原子のDPの特例。Fractionの高い冪を作らず同じ式を包む。

    Bernsteinの制御値から0<l≤P≤cを証明できる場合だけ使う。
    Q=P/c, ρ=1-l/c。φ(P)=-P log c+c φ(Q)で、M項の後は
    B=c ρ^(M+1)/(M+1)以下。各軸でdegree(P)(M+1)を積分できる
    正のGauss則Gなら、多項式の部分は厳密に同じ積分なので
    |Gφ(P)-Eφ(P)|≤B。下界Gφ-B、残り2Bを恒等式へ運ぶ。
    丸めは§4-6どおりこの上界に含めない。一般の道を置き換えない。
    """
    import numpy as np
    probability = probability.reduced()
    active = tuple(i for i, d in enumerate(probability.degrees) if d)
    if not active or any(measure.sizes[i] != 2 or measure.beta[i] != (1, 1) for i in active):
        return None
    expected_size = math.prod(math.comb(d + s - 1, s - 1)
                              for s, d in zip(probability.sizes, probability.degrees))
    if len(probability.coefficients) != expected_size:
        return None  # zero controls do not establish the required positive lower bound
    controls = tuple(c / math.prod(_multinomial(g) for g in _simplex_groups(probability.sizes, k))
                     for k, c in probability.coefficients.items())
    lower, upper = min(controls), max(controls)
    ratio = math.exp(_log_fraction(lower / upper))
    if not 0 < ratio < 1:
        return None
    log_rho, log_scale = math.log1p(-ratio), _log_fraction(upper)
    def log_bound(m):
        return log_scale + (m + 1) * log_rho - math.log(m + 1)
    low, high = -1, 0
    while math.log(2) + log_bound(high) > log_goal:
        low, high = high, 2 * high + 1
        if series_budget is not None and low >= series_budget:
            raise IntegrationIncomplete("information: explicit series-work budget exhausted")
    while high - low > 1:
        middle = (low + high) // 2
        if math.log(2) + log_bound(middle) <= log_goal:
            high = middle
        else:
            low = middle
    if series_budget is not None and high > series_budget:
        raise IntegrationIncomplete("information: explicit series-work budget exhausted")
    orders = tuple((probability.degrees[i] * (high + 1) + 2) // 2 for i in active)
    if work is not None:
        work.consume(math.prod(orders))
    shape, coordinates, log_weights = orders, [], np.zeros(orders)
    axis = 0
    for i, degree in enumerate(probability.degrees):
        if not degree:
            coordinates.append(None)
            continue
        nodes, weights = _gauss_rule(orders[axis])
        view_shape = tuple(len(nodes) if j == axis else 1 for j in range(len(active)))
        coordinates.append(nodes.reshape(view_shape))
        log_weights = log_weights + np.log(weights).reshape(view_shape)
        axis += 1
    log_p = np.minimum(0., _polynomial_grid_logs(probability, coordinates, shape))
    log_delta = _polynomial_grid_logs(probability.complement(), coordinates, shape)
    # Near one, use its positive complement instead of subtracting rounded P.
    with np.errstate(divide="ignore", invalid="ignore", under="ignore"):
        delta = np.exp(np.minimum(-math.log(2), log_delta))
        correction = np.where(delta > 0, np.log(-np.log1p(-delta) / delta), 0.)
        phi = np.where(log_p < -math.log(2), log_p + np.log(-log_p),
                       log_p + log_delta + correction)
    center = float(np.logaddexp.reduce((log_weights + phi).ravel()))
    bound = log_bound(high)
    if not math.isfinite(center) or not math.isfinite(bound):
        _range("information: bounded phi value or upper bound disappeared")
    below = (-math.inf if center <= bound else
             center + math.log(-math.expm1(bound - center)))
    return _EnclosedPhi(below, math.log(2) + bound, high, math.prod(orders))


@dataclass(frozen=True, slots=True)
class EntropyTailBounds:
    """元の証拠をその他へまとめた誤差。モデルから証明した上界を渡す。"""
    log_e: float
    log_z: float

    def __post_init__(self):
        if any(v != -math.inf and not math.isfinite(v) for v in (self.log_e, self.log_z)):
            _range("entropy tail: nonfinite or unavailable bound")

    @property
    def log_width(self):
        return _logadd((self.log_e, self.log_z + math.log(2.)))


@dataclass(frozen=True, slots=True)
class InformationComputation:
    bounds: InformationBounds
    log_width: float
    log_series_width: float
    stats: QuantityStats


def _display_information_bound(value):
    if value == -math.inf:
        return 0.
    try:
        number = math.exp(value)
    except OverflowError:
        _range("information: nonfinite displayed bound")
    if number == 0 or not math.isfinite(number):
        _range("information: positive displayed bound disappeared")
    return number


class AtomicRecordLaw:
    """P(h,z,e|W)の表。Wは全行動のFと共有するλ、Tは周辺化済み。

    cells[z][e]はλの順の多項式。表は省かず、その他の枝を作った時は
    その確率も表に残し、E/Zのエントロピーの上界を別に渡す。
    """
    def __init__(self, measure, weights, cells, *, history=None, tails=None):
        self.measure = measure
        self.weights = tuple(_fraction(w) for w in weights)
        if (not self.weights or any(w <= 0 for w in self.weights)
                or not math.isclose(float(sum(self.weights)), 1., rel_tol=0, abs_tol=1e-12)):
            raise ValueError("record law: expected positive normalized latent weights")
        self.rows, self.tails = [], tails
        totals = [SimplexPolynomial.constant(measure.sizes, 0) for _ in self.weights]
        for z, records in cells.items():
            records = tuple((e, tuple(values)) for e, values in records.items())
            if not records or any(len(v) != len(self.weights) or any(p.sizes != measure.sizes for p in v) for _, v in records):
                raise ValueError("record law: one likelihood per latent candidate required")
            a = tuple(SimplexPolynomial.constant(measure.sizes, 0) for _ in self.weights)
            for _, values in records:
                a = tuple(left.add(right) for left, right in zip(a, values))
            self.rows.append((z, records, a))
            totals = [left.add(right) for left, right in zip(totals, a)]
        self.rows = tuple(self.rows)
        if history is not None:
            if len(history) != len(totals) or any(left.ratio_to(right) != 1 if right.coefficients else bool(left.coefficients)
                                                 for left, right in zip(totals, history)):
                raise ValueError("record law: cells do not partition the supplied history")
        self.history = tuple(totals)
        self.evidence = self.expectation(self.history)
        if self.evidence == 0:
            from .inference import ModelViolation
            raise ModelViolation("quantity: observations have zero probability")

    @classmethod
    def from_timings(cls, priors, measure, cells, *, history=None, measurement=None):
        polynomial_measure, measure = AtomicPolynomialMeasure(priors), measure_prior(measure)
        measurement = ClockMeasure() if measurement is None else measurement
        def likelihood(timing):
            return tuple(polynomial_measure.likelihood(measurement.history_kernel(timing, lam=c)) for c in measure.candidates)
        return cls(polynomial_measure, (c.weight for c in measure.candidates),
            {z: {e: likelihood(timing) for e, timing in records.items()} for z, records in cells.items()},
            history=None if history is None else likelihood(history))

    def expectation(self, likelihoods):
        likelihoods = tuple(likelihoods)
        if len(likelihoods) != len(self.weights):
            raise ValueError("record expectation: one likelihood per latent candidate required")
        return sum((w * self.measure.expectation(p) for w, p in zip(self.weights, likelihoods)), Fraction(0))

    def project_parameters(self):
        """全Fを先に周辺化し、情報の対象をλだけにした低水準の照会。"""
        constant = lambda p: SimplexPolynomial.constant(self.measure.sizes, self.measure.expectation(p))
        return AtomicRecordLaw(self.measure, self.weights,
            {z: {e: tuple(constant(p) for p in values) for e, values in records} for z, records, _ in self.rows},
            tails=self.tails)

    def project_latent(self):
        """λを先に周辺化し、Fについての情報を保つ。事後の相関も残す。"""
        weights = tuple(w / sum(self.weights) for w in self.weights)
        def average(values):
            result = SimplexPolynomial.constant(self.measure.sizes, 0)
            for weight, p in zip(weights, values):
                result = result.add(p.scale(weight))
            return result
        return AtomicRecordLaw(self.measure, (1,),
            {z: {e: (average(values),) for e, values in records} for z, records, _ in self.rows}, tails=self.tails)

    def given_latent(self, *, tolerance):
        """I(F;E|λ,Z,h)。履歴の後のλの重みで各候補の値を平均する。"""
        results, weights = [], []
        for i, weight in enumerate(self.weights):
            evidence = self.measure.expectation(self.history[i])
            if not evidence:
                continue
            law = AtomicRecordLaw(self.measure, (1,),
                {z: {e: (values[i],) for e, values in records} for z, records, _ in self.rows})
            results.append(law.information(tolerance=tolerance))
            weights.append(weight * evidence / self.evidence)
        def sum_bound(name):
            logs = tuple(_log_fraction(w) + math.log(getattr(r.bounds, name))
                         for w, r in zip(weights, results) if getattr(r.bounds, name) > 0)
            return _logadd(logs)
        low, high = sum_bound("lower"), sum_bound("upper")
        width = _logadd(_log_fraction(w) + r.log_width for w, r in zip(weights, results))
        if self.tails is not None:
            if self.tails.log_width > math.log(_number(tolerance, "information tolerance", positive=True)):
                raise IntegrationIncomplete("information: fixed record aggregation cannot meet total error budget")
            if low <= self.tails.log_z:
                low = -math.inf
            elif self.tails.log_z != -math.inf:
                low += math.log(-math.expm1(self.tails.log_z - low))
            high = _logadd((high, self.tails.log_e, self.tails.log_z))
            width = _logadd((width, self.tails.log_width))
        return InformationComputation(InformationBounds(_display_information_bound(low), _display_information_bound(high)),
            width, _logadd(_log_fraction(w) + r.log_series_width for w, r in zip(weights, results)),
            QuantityStats(partitions=0, series_terms=max((r.stats.series_terms for r in results), default=0)))

    def conditional_variance(self, z, e, *, tolerance, terms=None, series_budget=None):
        """E[P_e(1-P_e)|h,z]。Aで割る前にTを周辺化したA/Bから作る。

        BC/A=Σ_{m≥0}BC(1-A)^m。残り≤E[A(1-A)^(M+1)]/4。
        非負の多項式だけを使い、Tごとのモーメントを平均しない。
        """
        tolerance = _number(tolerance, "conditional moment tolerance", positive=True)
        if terms is not None and (type(terms) is not int or terms < 0):
            raise ValueError("conditional moment: nonnegative series order required")
        if series_budget is not None and (type(series_budget) is not int or series_budget < 0):
            raise ValueError("conditional moment: nonnegative work budget required")
        row = next((row for row in self.rows if row[0] == z), None)
        if row is None or e not in dict(row[1]):
            raise ValueError("conditional moment: unknown record")
        _, records, a = row
        b, c = dict(records)[e], tuple(SimplexPolynomial.constant(self.measure.sizes, 0) for _ in self.weights)
        for record, values in records:
            if record != e:
                c = tuple(left.add(right) for left, right in zip(c, values))
        evidence = self.expectation(a)
        if not evidence:
            from .inference import ModelViolation
            raise ModelViolation("quantity: conditioning event has zero probability")
        bc = tuple(left.multiply(right) for left, right in zip(b, c))
        if not self.expectation(bc):
            return IntegralEstimate(-math.inf, -math.inf)
        complement = tuple(p.complement() for p in a)
        power = tuple(SimplexPolynomial.constant(self.measure.sizes, 1) for _ in a)
        sums, count = [], 0
        log_r = _log_fraction(evidence)
        while True:
            remainder = self.expectation(tuple(p.multiply(q) for p, q in zip(a, power))) / 4
            estimate = IntegralEstimate(_logadd(sums) - log_r, -math.inf, _log_fraction(remainder) - log_r)
            if (terms is not None and count == terms) or (terms is None and estimate.log_width <= math.log(tolerance)):
                return estimate
            if series_budget is not None and count >= series_budget:
                raise IntegrationIncomplete("conditional moment: explicit series-work budget exhausted")
            sums.append(_log_fraction(self.expectation(tuple(p.multiply(q) for p, q in zip(bc, power)))))
            power = tuple(p.multiply(q) for p, q in zip(power, complement))
            count += 1

    def _series(self, *, closed_forms):
        predictive, plus, minus = [], [], []
        for _, records, a in self.rows:
            az = self.expectation(a)
            if not az:
                continue
            b = tuple(self.expectation(values) for _, values in records)
            # Prove the conditional record distribution independent of W.
            reference, independent = None, True
            for i, probability in enumerate(a):
                if not probability.coefficients:
                    continue
                ratios = tuple(values[i].ratio_to(probability) for _, values in records)
                if None in ratios or (reference is not None and ratios != reference):
                    independent = False
                    break
                reference = ratios
            if independent:
                continue
            log_h = _logadd(_log_phi_fraction(value / az) for value in b)
            predictive.append(_log_fraction(az) + log_h)
            def fingerprint(p):
                constant = p.constant_value()
                return ("constant", constant) if constant is not None else (p.degrees, tuple(p.coefficients.items()))
            columns = {}
            for i, weight in enumerate(self.weights):
                key = (fingerprint(a[i]), tuple(fingerprint(values[i]) for _, values in records))
                first, previous = columns.get(key, (i, Fraction(0)))
                columns[key] = (first, previous + weight)
            # Identical conditional laws are merged by exact weights, never by
            # the number of lambda labels. The original law retains its labels.
            for i, weight in columns.values():
                probability = a[i]
                values = tuple(v[i] for _, v in records)
                # A deterministic record has exactly zero conditional entropy,
                # including zero probability records: no generic remainder there.
                if sum(bool(v.coefficients) for v in values) <= 1:
                    continue
                log_weight = _log_fraction(weight)
                plus.append((log_weight, PhiSeries(self.measure, probability, closed_forms=closed_forms)))
                minus.extend((log_weight, PhiSeries(self.measure, v, closed_forms=closed_forms)) for v in values if v.coefficients)
        return _logadd(predictive), plus, minus

    def _result(self, predictive, plus, minus, terms):
        a = _logadd(w + s.log_value for w, s in plus)
        b = _logadd(w + s.log_value for w, s in minus)
        ea = _logadd(w + s.log_remainder for w, s in plus)
        eb = _logadd(w + s.log_remainder for w, s in minus)
        def difference(positive, negative, *, lower):
            if negative == -math.inf:
                return positive
            if positive <= negative:
                if lower:
                    return -math.inf
                _range("information: positive upper bound lost in cancellation")
            return positive + math.log(-math.expm1(negative - positive))
        log_r = _log_fraction(self.evidence)
        if predictive == -math.inf:
            low = high = -math.inf
        else:
            low = difference(_logadd((predictive, a)), _logadd((b, eb)), lower=True) - log_r
            high = min(predictive - log_r, difference(_logadd((predictive, a, ea)), b, lower=False) - log_r)
        series_width = _logadd((ea, eb)) - log_r
        width = series_width
        if self.tails is not None:
            low = difference(low, self.tails.log_z, lower=True)
            high = _logadd((high, self.tails.log_e, self.tails.log_z))
            width = _logadd((width, self.tails.log_width))
        if low > high:
            _range("information: rounded bound ordering lost")
        return InformationComputation(InformationBounds(_display_information_bound(low), _display_information_bound(high)), width, series_width,
            QuantityStats(partitions=0, series_terms=terms, final_groups=len(self.rows),
                integration_nodes=sum(getattr(s, "integration_nodes", 0) for _, s in plus + minus)))

    def information(self, *, tolerance, terms=None, series_budget=None, node_budget=None):
        """恒等式のφの正の級数。項数の上限を置かず全体の幅で停止。

        termsは固定次数の検査用。series_budgetは明示した計算資源の予算。
        piecewiseと情報までの求積誤差の伝播は別の一般の道で接続する。
        """
        tolerance = _number(tolerance, "information tolerance", positive=True)
        if terms is not None and (type(terms) is not int or terms < 0):
            raise ValueError("information: nonnegative fixed series order required")
        if series_budget is not None and (type(series_budget) is not int or series_budget < 0):
            raise ValueError("information: nonnegative series budget required")
        work = _IntegrationWork(node_budget)
        predictive, plus, minus = self._series(closed_forms=terms is None)
        if terms is None and self.tails is not None and self.tails.log_width > math.log(tolerance):
            raise IntegrationIncomplete("information: fixed record aggregation cannot meet total error budget")
        if terms is None and any(s.closed is None and sum(s.probability.degrees) > 1 for _, s in plus + minus):
            available = math.log(tolerance)
            if self.tails is not None and self.tails.log_width != -math.inf:
                if available <= self.tails.log_width:
                    raise IntegrationIncomplete("information: fixed record aggregation cannot meet total error budget")
                available += math.log(-math.expm1(self.tails.log_width - available))
            weights = _logadd(w for w, s in plus + minus if s.closed is None)
            goal = available + _log_fraction(self.evidence) - weights - math.log(4)
            def accelerate(collection):
                return [(w, (_bounded_phi_quadrature(self.measure, s.probability, goal, series_budget, work) or s)
                         if s.closed is None else s) for w, s in collection]
            plus, minus = accelerate(plus), accelerate(minus)
        count = 0
        while True:
            used = max((s.terms for _, s in plus + minus), default=count)
            result = self._result(predictive, plus, minus, max(count, used))
            if (terms is not None and count == terms) or (terms is None and result.log_width <= math.log(tolerance)):
                return result
            if series_budget is not None and count >= series_budget:
                raise IntegrationIncomplete("information: explicit series-work budget exhausted")
            count += 1
            for _, series in plus + minus:
                series.advance()


@dataclass(frozen=True, slots=True)
class ExactEvidence:
    """一つの試みの全証拠。checks は (下限ns, strict) の列。None は永久未着。

    complete=False の value=None は情報の無い記録で、∞ の完了ではない。
    公開の一歩は strict=False。strict=True は帰着の定規にだけ用いる。
    """

    attempt: str
    checks: tuple[tuple[int, bool], ...]
    complete: bool
    value: int | None

    def __post_init__(self):
        if type(self.attempt) is not str or not self.attempt:
            raise ValueError("exact evidence: expected attempt name")
        checks = tuple(self.checks)
        if any(not isinstance(c, tuple) or len(c) != 2 or type(c[0]) is not int
               or c[0] < 0 or type(c[1]) is not bool for c in checks):
            raise ValueError("exact checks: expected (nonnegative ns, strict)")
        if type(self.complete) is not bool or (self.value is not None and
                (type(self.value) is not int or self.value < 0)):
            raise ValueError("exact evidence: invalid completion")
        if not self.complete and self.value is not None:
            raise ValueError("exact evidence: incomplete attempt has no value")
        object.__setattr__(self, "checks", checks)

    def accepts(self, value):
        if self.complete and value != self.value:
            return False
        return value is None or all(value > lower if strict else value >= lower
                                    for lower, strict in self.checks)


ExactKey = tuple[tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class ExactPosterior:
    """(整数N, 試みごとの割り振り) の全成分を対数で持つ。平均で更新しない。"""

    prior: DurationPrior
    evidence: tuple[ExactEvidence, ...]
    log_w: Mapping[ExactKey, float]
    log_evidence: float
    stats: QuantityStats
    value_space: ValueSpace = field(default=ValueSpace("quantity", "1"), init=False)
    condition_keys: tuple = field(default=("action",), init=False)

    def __post_init__(self):
        object.__setattr__(self, "log_w", MappingProxyType(dict(sorted(self.log_w.items()))))

    def predictive(self, query=None):
        """query=None: 新しい一標本の原子ごとの対数確率。"""
        if query is not None:
            raise ValueError("exact predictive: expected None for a new sample")
        points = self.prior.base.params["points"]
        alpha = self.prior.alpha
        total = _logadd((math.log(alpha), math.log(len(self.evidence))
                         if self.evidence else -math.inf))
        result = {}
        for index, (point, mass) in enumerate(points):
            terms = []
            for (counts, _), weight in self.log_w.items():
                numerator = _logadd((math.log(alpha) + math.log(mass) if mass else -math.inf,
                                     math.log(counts[index]) if counts[index] else -math.inf))
                if numerator != -math.inf:
                    terms.append(weight + numerator - total)
            result[point] = _logadd(terms)
        return MappingProxyType(result)

    def allocated(self, requests):
        """requests={既存の試み: 原子} の結合確率。新しい標本を足さない。"""
        indexes = {e.attempt: i for i, e in enumerate(self.evidence)}
        points = tuple(p for p, _ in self.prior.base.params["points"])
        if any(name not in indexes for name in requests):
            raise ValueError("allocated: unknown attempt")
        return _logadd(weight for (_, allocation), weight in self.log_w.items()
                       if all(points[allocation[indexes[name]]] == point
                              for name, point in requests.items()))

    def joint_new(self, values):
        """新しい標本の結合の対数確率。既存の進行中の割り振りとは区別する。"""
        points = tuple(p for p, _ in self.prior.base.params["points"])
        if any(value not in points for value in values):
            return -math.inf
        terms = []
        for (counts, _), weight in self.log_w.items():
            updated = list(counts)
            for step, value in enumerate(values):
                index = points.index(value)
                mass = self.prior.base.params["points"][index][1]
                numerator = _logadd((math.log(self.prior.alpha) + math.log(mass) if mass else -math.inf,
                                     math.log(updated[index]) if updated[index] else -math.inf))
                denominator = _logadd((math.log(self.prior.alpha),
                    math.log(len(self.evidence) + step) if len(self.evidence) + step else -math.inf))
                weight += numerator - denominator
                updated[index] += 1
            terms.append(weight)
        return _logadd(terms)

    def information(self, target, evidence, given) -> InformationBounds:
        """新しい exact の値が F 全体について教える量 (原子の閉じた式)。"""
        if target != "distribution" or evidence != "new_value" or given is not None:
            raise ValueError("exact information: expected distribution, new_value, None")
        # 既存の安定なdigammaの差の式を用いる。混合の予測のHを別に足す。
        import numpy as np
        from .inference import _s4d_novelty, _log_A
        prediction = self.predictive()
        entropy = -math.fsum(math.exp(log_p) * log_p for log_p in prediction.values()
                            if log_p != -math.inf)
        expected_entropy = []
        for (counts, _), weight in self.log_w.items():
            beta = np.array([self.prior.alpha * mass + count
                for (_, mass), count in zip(self.prior.base.params["points"], counts)])[:, None]
            if not np.all(np.isfinite(beta)) or not np.any(beta > 0):
                _range("exact: posterior parameters exceed numerical range")
            # A positive αG₀ that rounded to zero is a numerical failure, not a structural zero.
            if any(mass > 0 and value == 0 for (_, mass), value in
                   zip(self.prior.base.params["points"], beta[:, 0])):
                _range("exact: positive posterior mass cannot be represented")
            logs = _log_A(beta)[:, 0]
            mean_entropy = -math.fsum(math.exp(v) * v for v in logs if math.isfinite(v))
            information = _s4d_novelty(np.array([0.]), beta)
            expected_entropy.append(math.exp(weight) * (mean_entropy - information))
        result = entropy - math.fsum(expected_entropy)
        if not math.isfinite(result):
            _range("exact: information exceeds numerical range")
        return InformationBounds(result, result)


def exact_posterior(prior, evidence):
    """全試みを、事実から一度ずつ作り直す。確かめの反復は同一の行の中。

    同じ試みを二行で与えるのは入力の誤り。根≥と定規の>の両方を集合で扱う。
    """
    prior = duration_prior(prior)
    if prior.base.name != "atoms":
        raise ValueError("exact posterior: finite atoms are required")
    evidence = tuple(evidence)
    if any(not isinstance(e, ExactEvidence) for e in evidence):
        raise ValueError("exact posterior: expected ExactEvidence")
    if len({e.attempt for e in evidence}) != len(evidence):
        raise ValueError("exact posterior: duplicate attempt")
    points = prior.base.params["points"]
    table = {((0,) * len(points), ()): 0.}
    log_evidence, branches = 0., 0
    for step, item in enumerate(evidence):
        updated = {}
        denominator = _logadd((math.log(prior.alpha), math.log(step) if step else -math.inf))
        for (counts, allocation), weight in sorted(table.items()):
            for index, (point, mass) in enumerate(points):
                if not item.accepts(point):
                    continue
                numerator = _logadd((math.log(prior.alpha) + math.log(mass) if mass else -math.inf,
                                     math.log(counts[index]) if counts[index] else -math.inf))
                if numerator == -math.inf:
                    continue
                branches += 1
                incremented = list(counts)
                incremented[index] += 1
                updated[(tuple(incremented), allocation + (index,))] = weight + numerator - denominator
        table, normalizer = _normalize(updated)
        log_evidence += normalizer
        if not math.isfinite(log_evidence):
            _range("exact: evidence exceeds numerical range")
    # Polya の有限射影は同じ DP の和を解析して計算する。割り振りの枝の数は
    # Antoniak の名札つき分割の項数と混同せず、別に計測する。
    bells = [1]
    for n in range(len(evidence)):
        bells.append(sum(math.comb(n, k) * bells[k] for k in range(n + 1)))
    return ExactPosterior(prior, evidence, table, log_evidence,
                          QuantityStats(partitions=bells[-1], final_groups=len(table),
                                        allocated_branches=branches))


@dataclass(frozen=True, slots=True)
class RecordTailBound:
    """記録の有限の尾のエントロピー。∞は別の記録で、ここへ混ぜない。

    P(h,E=r,λ) ≤ π_λ G₀(((r−1)h,(r+1)h)) を用いる。
    候補も既存の試みも、条件づける前の所要の周辺はG₀なので同じ上界。
    F/λ/Tの独立な事後を仮定せず、履歴の尤度の下界で割る。
    """

    base: BaseSpec
    measure: MeasurePrior
    log_history_lower: float

    def __post_init__(self):
        if not isinstance(self.base, BaseSpec) or not isinstance(self.measure, MeasurePrior):
            raise ValueError("record tail: expected base and measure prior")
        if not math.isfinite(self.log_history_lower) or self.log_history_lower > 0:
            raise ValueError("record tail: expected positive history probability lower bound")

    def log_bound(self, cutoff_ns):
        """E ≥ cutoff_nsの集約誤差δ。未だ単調な領域の外なら上界を作らない。"""
        if type(cutoff_ns) is not int or cutoff_ns <= 0:
            raise ValueError("record tail: expected positive integer cutoff_ns")
        if self.base.name == "atoms":
            largest = max((d for d, mass in self.base.params["points"] if d is not None and mass), default=0)
            widths = [c.spec.params["width_ns"] for c in self.measure.candidates if c.spec.name == "tick"]
            if cutoff_ns <= largest + max(widths, default=0):
                raise ValueError("record tail: cutoff does not cover finite atoms")
            return -math.inf
        tail = self.base.params["tail"]
        if not tail["mass"]:
            largest = self.base.params["edges_ns"][-1]
            if any(c.spec.name == "tick" and cutoff_ns <= largest + c.spec.params["width_ns"]
                   for c in self.measure.candidates):
                raise ValueError("record tail: cutoff does not cover bounded base")
            return -math.inf
        kappa, boundary = tail["kappa"], self.base.params["edges_ns"][-1]
        values = []
        for candidate in self.measure.candidates:
            if candidate.spec.name != "tick":
                raise ValueError("record tail: continuous base requires tick")
            width = candidate.spec.params["width_ns"]
            first = (cutoff_ns + width - 1) // width
            n = first - 1
            if n <= 0 or n * width < boundary:
                raise ValueError("record tail: cutoff must be beyond bounded base")
            log_c = (math.log(2) + math.log(tail["mass"]) + math.log(kappa)
                     + kappa * (math.log(boundary) - math.log(width))
                     + math.log(candidate.weight) - self.log_history_lower)
            log_n = math.log(n)
            log_envelope = log_c - (kappa + 1) * log_n
            if log_envelope > -1:
                raise ValueError("record tail: cutoff must put envelope below 1/e")
            # f(n)+∫_n^∞ f(x)dx for decreasing f=φ(c x^(-κ-1)).
            first_log = log_envelope + math.log(-log_envelope)
            integral_log = (log_c - kappa * log_n - math.log(kappa)
                            + math.log(-log_envelope + 1 + 1/kappa))
            if not all(math.isfinite(v) for v in (first_log, integral_log)):
                _range("record tail: entropy bound cannot be represented in logs")
            values.append(_logadd((first_log, integral_log)))
        return _logadd(values)


def _outside_constraints(regions, excluded):
    """線形の領域の補集合を、最初に破る制約で重ならずに分ける。

    等号の側も反転する。原子の同時刻を測度0として落とさない。
    正負の包含排除は使わず、非負の領域だけを返す。
    """
    excluded = _clean_constraints(excluded)
    if excluded is None:
        return tuple(regions)
    result = []
    for region in regions:
        prefix = list(region)
        for affine, strict in excluded:
            outside = _clean_constraints(prefix + [(tuple(-x for x in affine), not strict)])
            if outside is not None:
                result.append(outside)
            prefix.append((affine, strict))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class KernelEvent:
    """同じ外の条件/試みの下の、履歴の有限の和集合。

    『その他』にも使える。和集合は領域の側で重ならずに分けるので、
    重複した説明や共有時刻があっても確率を二重に足さない。
    """

    kernels: tuple[HistoryKernel, ...]
    inverted: bool = False

    def __post_init__(self):
        if not self.kernels or any(not isinstance(k, HistoryKernel) for k in self.kernels):
            raise ValueError("kernel event: expected nonempty history kernels")
        if type(self.inverted) is not bool:
            raise ValueError("kernel event: expected boolean complement")
        first = self.kernels[0]
        shape = lambda k: tuple((a.attempt, a.action, a.start_event) for a in k.attempts)
        if any(k.spec != first.spec or k.external_ids != first.external_ids
               or k._external != first._external or k._constraints != first._constraints
               or shape(k) != shape(first) for k in self.kernels[1:]):
            raise ValueError("kernel event: histories must have the same external conditions and trials")

    def complement(self):
        return KernelEvent(self.kernels, not self.inverted)

    @property
    def attempts(self):
        return self.kernels[0].attempts

    def __call__(self, durations):
        first = self.kernels[0]
        if not first._normalizer:
            return Fraction(0)
        affine = {ref: None if value is None else
                  (_fraction(value),) + (Fraction(0),) * first.dimension
                  for ref, value in durations.items()}
        total = sum((weight * _polytope_integral(first.dimension, region,
                     {(0,) * first.dimension: Fraction(1)})[0]
                     for weight, region in self.ranked_regions(affine, first.dimension)), Fraction(0))
        return total / first._normalizer

    def ranked_regions(self, durations, dimension):
        for weight, ranks in _tie_rankings(self.kernels[0], durations, dimension, kernels=self.kernels):
            for region in self.raw_regions(durations, dimension, ranks=ranks):
                yield weight, region

    def raw_regions(self, durations, dimension, *, ranks=None):
        first = self.kernels[0]
        extra = (Fraction(0),) * (dimension - first.dimension)
        universe = tuple((a + extra, strict) for a, strict in first._constraints)
        remaining, inside = (universe,), []
        for kernel in self.kernels:
            constraints = kernel.raw_constraints(durations, dimension, ranks=ranks)
            if constraints is None:
                continue
            for region in remaining:
                intersection = _clean_constraints(region + constraints)
                if intersection is not None:
                    inside.append(intersection)
            remaining = _outside_constraints(remaining, constraints)
        return remaining if self.inverted else tuple(inside)


@dataclass(frozen=True, slots=True)
class ReplicaProduct:
    """W全体を共有し、外の時刻は写しごとに独立な補助の写し。"""

    factors: tuple[KernelEvent, ...]

    def __post_init__(self):
        if not self.factors or any(not isinstance(e, KernelEvent) for e in self.factors):
            raise ValueError("replicas: expected nonempty kernel events")


def _partition_combinations(groups, index=0, prefix=()):
    # product()のプールへ巨大なBell数の列を先に展開しない。
    if index == len(groups):
        yield prefix
    else:
        for rgs in restricted_growth_strings(len(groups[index])):
            yield from _partition_combinations(groups, index + 1, prefix + (rgs,))


def _embed_copy_affine(affine, local_dimension, offset):
    values = list(affine)
    for index in range(local_dimension):
        values[index + 1] = Fraction(0)
    for index in range(local_dimension):
        values[offset + index + 1] += affine[index + 1]
    return tuple(values)


def _replica_partition_regions(events, attempts, blocks, choices):
    """生の自由時刻とDPのまとまりの変数を、全ての写しへつなぐ。"""
    kernels = tuple(e.kernels[0] for e in events)
    if any(not k._normalizer for k in kernels):
        return ()
    external_dimension = sum(k.dimension for k in kernels)
    continuous = tuple(i for i, choice in enumerate(choices) if choice[0] != "atom")
    dimension = external_dimension + len(continuous)
    indexes = {b: external_dimension + i for i, b in enumerate(continuous)}
    expressions, bounds, factors, tails = {}, [], [], []
    coefficient = 1 / math.prod((k._normalizer for k in kernels), start=Fraction(1))
    log_scale = 0.
    for i, ((action, group), choice) in enumerate(zip(blocks, choices)):
        kind, lower, upper, mass, kappa = choice
        if kind == "atom":
            expression = None if lower is None else (Fraction(lower),) + (Fraction(0),) * dimension
            coefficient *= _fraction(mass)
        else:
            variable = indexes[i]
            expression = tuple(Fraction(int(j == variable + 1)) for j in range(dimension + 1))
            lo = list(expression)
            lo[0] = -Fraction(lower)
            bounds.append((tuple(lo), False))
            if upper is not None:
                hi = [-x for x in expression]
                hi[0] = Fraction(upper)
                bounds.append((tuple(hi), True))
                coefficient *= _fraction(mass) / (upper - lower)
            else:
                factors.append(PowerFactor(expression, -kappa - 1))
                log_scale += math.log(mass) + math.log(kappa) + kappa * math.log(lower)
                other_mass = math.prod((_fraction(c[3]) for j, c in enumerate(choices) if j != i), start=Fraction(1))
                tails.append(TailDensity((action, group), variable, lower, kappa, mass, other_mass))
            # 有限の上限を与える写しがある時だけ。補集合では使わない。
            for j in group:
                copy, ref, _ = attempts[j]
                event = events[copy]
                rows = [next(a for a in k.attempts if a.attempt == ref) for k in event.kernels]
                if (not event.inverted and not isinstance(event, ConjunctionEvent)
                        and all(a.state == "complete" for a in rows)):
                    maxima = []
                    for k, a in zip(event.kernels, rows):
                        start = k.timing.events[a.start_event].reading
                        report = k.timing.events[a.report_event].reading
                        phase = k.spec.params["phase"]
                        minima = start + (0 if phase == "uniform" else phase["point_ns"])
                        maxima.append(report + k.spec.params["width_ns"] - minima)
                    hi = [-x for x in expression]
                    hi[0] = Fraction(max(maxima))
                    bounds.append((tuple(hi), True))
        for j in group:
            copy, ref, _ = attempts[j]
            expressions[copy, ref] = expression
    regions, offset = ((Fraction(1), tuple(bounds)),), 0
    for copy, (event, kernel) in enumerate(zip(events, kernels)):
        durations = {a.attempt: expressions[copy, a.attempt] for a in kernel.attempts}
        local = event.ranked_regions(durations, dimension)
        embedded = tuple((weight, tuple((_embed_copy_affine(a, kernel.dimension, offset), strict)
                              for a, strict in region)) for weight, region in local)
        merged = []
        for (lw, left), (rw, right) in product(regions, embedded):
            cleaned = _clean_constraints(left + right)
            if cleaned is not None:
                merged.append((lw * rw, cleaned))
        regions = tuple(merged)
        offset += kernel.dimension
    return tuple(LinearIntegral(dimension, region,
        (PowerTerm(coefficient * weight, tuple(factors), log_scale),), tuple(tails))
        for weight, region in regions)


class ReplicaMoments:
    """補助の写しの一般のDPの分割の和。平均のDPへの置き換え無し。

    各写しの中でKの全ての時刻/試みの結合を保ち、写し間では全行動のF
    を共有する。積分は②bと同じ片/次数/空間/残りの質量の道。
    """

    def __init__(self, priors):
        self.priors = MappingProxyType({a: duration_prior(p) for a, p in priors.items()})
        self.partitions = 0
        self._multiplicity = {}
        self._atomic = (AtomicPolynomialMeasure(self.priors)
                        if all(p.base.name == "atoms" for p in self.priors.values()) else None)
        self._atomic_programs = {}

    def expectation(self, probability, *, tolerance, partition_budget=None, node_budget=None):
        events = ((probability,) if isinstance(probability, KernelEvent) else
                  probability.factors if isinstance(probability, ReplicaProduct) else None)
        if events is None:
            raise ValueError("replicas: expected KernelEvent or ReplicaProduct")
        tolerance = _number(tolerance, "replica tolerance", positive=True)
        if partition_budget is not None and (type(partition_budget) is not int or partition_budget < 0):
            raise ValueError("replicas: expected nonnegative partition budget")
        if self._atomic is not None:
            polynomial = SimplexPolynomial.constant(self._atomic.sizes, Fraction(1))
            for event in events:
                if id(event) not in self._atomic_programs:
                    self._atomic_programs[id(event)] = (event, self._atomic.likelihood(event))
                polynomial = polynomial.multiply(self._atomic_programs[id(event)][1])
            return IntegralEstimate(_log_fraction(self._atomic.expectation(polynomial)), -math.inf)
        isolated = tuple(_isolated_polynomial_event(e) for e in events)
        if all(item is not None for item in isolated) and partition_budget is None:
            if any(action not in self.priors for action, _ in isolated):
                raise ValueError("replicas: unknown action")
            log_values = []
            logical_partitions = 1
            for action in self.priors:
                kernels, counts = [], []
                for group_action, kernel in isolated:
                    if group_action != action:
                        continue
                    if kernel in kernels:
                        counts[kernels.index(kernel)] += 1
                    else:
                        kernels.append(kernel)
                        counts.append(1)
                if not kernels:
                    continue
                bells = [1]
                for n in range(sum(counts)):
                    bells.append(sum(math.comb(n, k) * bells[k] for k in range(n + 1)))
                logical_partitions *= bells[-1]
                key = action, tuple(kernels)
                if key not in self._multiplicity:
                    self._multiplicity[key] = MultiplicityMoments(self.priors[action], tuple(kernels))
                log_values.append(self._multiplicity[key].log_z(tuple(counts)))
            self.partitions += logical_partitions
            if any(v == -math.inf for v in log_values):
                return IntegralEstimate(-math.inf, -math.inf)
            return IntegralEstimate(math.fsum(log_values), -math.inf)
        attempts = tuple((copy, a.attempt, a.action) for copy, event in enumerate(events)
                         for a in event.kernels[0].attempts)
        if any(a not in self.priors for _, _, a in attempts):
            raise ValueError("replicas: unknown action")
        actions = tuple(self.priors)
        groups = tuple(tuple(i for i, (_, _, a) in enumerate(attempts) if a == action) for action in actions)
        entries, weights = [], []
        count = 0
        for rgs_by_action in _partition_combinations(groups):
            if partition_budget is not None and count >= partition_budget:
                raise IntegrationIncomplete("replicas: partition resource budget exhausted")
            count += 1
            weight, blocks = Fraction(1), []
            for action, group, rgs in zip(actions, groups, rgs_by_action):
                weight *= _partition_weight(self.priors[action].alpha, rgs)
                blocks.extend((action, tuple(group[j] for j, b in enumerate(rgs) if b == label))
                              for label in range(max(rgs, default=-1) + 1))
            for chosen in product(*(_base_regions(self.priors[a].base) for a, _ in blocks)):
                regions = _replica_partition_regions(events, attempts, tuple(blocks), chosen)
                entries.extend(regions)
                weights.extend((weight,) * len(regions))
        self.partitions += count
        if not entries:
            return IntegralEstimate(-math.inf, -math.inf)
        work = _IntegrationWork(node_budget)
        goal = tolerance / (4 * len(entries))
        while True:
            if goal == 0:
                _range("replicas: positive integration budget disappeared")
            estimates = []
            for region, weight in zip(entries, weights):
                log_goal = math.log(goal) - _log_fraction(weight)
                raw_goal = math.exp(min(log_goal, math.log(float.fromhex('0x1.fffffffffffffp+1023'))))
                if raw_goal == 0:
                    _range("replicas: raw integration budget disappeared")
                remaining = None if work.limit is None else work.limit - work.nodes
                estimate = integrate_linear(region, tolerance=raw_goal, node_budget=remaining)
                estimates.append(estimate)
                work.consume(estimate.nodes)
            result = sum_integrals(estimates, weights)
            if result.log_width <= math.log(tolerance):
                return result
            goal /= 4


def _isolated_polynomial_event(event):
    """共有時刻/他試み/確かめが無いと構造で証明した一試みだけを縮約。"""
    if isinstance(event, (RecordEvent, UnionEvent)):
        return _isolated_selection_event(event)
    if (type(event) is KernelEvent and len(event.kernels) == 1 and len(event.attempts) == 1
            and event.attempts[0].state == "pending"):
        return _isolated_selection_event(event)
    if isinstance(event, ConjunctionEvent):
        return None
    first = event.kernels[0]
    if first.spec.name != "tick" or len(first.attempts) != 1:
        return None
    attempt = first.attempts[0]
    if any(len(k.timing.events) != 2 or k.external_ids != (attempt.start_event,)
           or len(k.attempts) != 1 or k.attempts[0].check_events
           or k.attempts[0].state != "complete" for k in event.kernels):
        return None
    width, phase = first.spec.params["width_ns"], first.spec.params["phase"]
    start = first.timing.events[attempt.start_event].reading
    readings = sorted({k.timing.events[k.attempts[0].report_event].reading - start for k in event.kernels})
    boundaries = {Fraction(0)}
    for reading in readings:
        if phase == "uniform":
            boundaries.update(Fraction(max(0, v)) for v in (reading - width, reading, reading + width))
        else:
            point = phase["point_ns"]
            boundaries.update(Fraction(max(0, v)) for v in (reading - point, reading + width - point))
    boundaries = sorted(boundaries)
    pieces = []
    for lower, upper in zip(boundaries, boundaries[1:] + [None]):
        sample = lower + 1 if upper is None else (lower + upper) / 2
        constant, slope = Fraction(0), Fraction(0)
        for reading in readings:
            if phase == "uniform":
                if max(0, reading - width) <= sample < reading:
                    constant += 1 - Fraction(reading, width)
                    slope += Fraction(1, width)
                elif reading <= sample < reading + width:
                    constant += 1 + Fraction(reading, width)
                    slope -= Fraction(1, width)
            elif reading - phase["point_ns"] <= sample < reading + width - phase["point_ns"]:
                constant += 1
        if event.inverted:
            constant, slope = 1 - constant, -slope
        pieces.append(PolynomialPiece(lower, upper, (constant, slope)))
    return attempt.action, PolynomialLikelihood(tuple(pieces), Fraction(int(event.inverted)))


class ConjunctionEvent(KernelEvent):
    """同じ写しの同じ所要/T上の事象の交差。独立な写しの積とは別。"""

    def __init__(self, parts, inverted=False):
        parts = tuple(parts)
        if not parts or any(not isinstance(p, KernelEvent) for p in parts):
            raise ValueError("conjunction: expected kernel events")
        super().__init__(tuple(k for p in parts for k in p.kernels), inverted)
        object.__setattr__(self, "parts", parts)

    def complement(self):
        return ConjunctionEvent(self.parts, not self.inverted)

    def __eq__(self, other):
        return type(self) is type(other) and self.parts == other.parts and self.inverted == other.inverted

    def raw_regions(self, durations, dimension, *, ranks=None):
        first = self.kernels[0]
        extra = (Fraction(0),) * (dimension - first.dimension)
        universe = tuple((a + extra, strict) for a, strict in first._constraints)
        regions = (universe,)
        for part in self.parts:
            intersections = []
            for left, right in product(regions, part.raw_regions(durations, dimension, ranks=ranks)):
                cleaned = _clean_constraints(left + right)
                if cleaned is not None:
                    intersections.append(cleaned)
            regions = tuple(intersections)
        if not self.inverted:
            return regions
        outside = (universe,)
        for region in regions:
            outside = _outside_constraints(outside, region)
        return outside


def _phi_log_probability(log_probability):
    if log_probability == -math.inf or log_probability == 0:
        return -math.inf
    if log_probability > 0 or not math.isfinite(log_probability):
        _range("entropy: invalid probability")
    return log_probability + math.log(-log_probability)


def _log_entropy_continuity(log_error):
    """|φ(x)−φ(y)| ≤ δ(1−logδ), δ=|x−y|≤1。丸めは含めない。"""
    if log_error == -math.inf:
        return -math.inf
    if log_error >= 0:
        return -1.  # φ全体の最大値1/e。
    return log_error + math.log(1 - log_error)


def _normalized_positive(log_value, log_normalizer):
    if log_value == -math.inf:
        return 0.
    try:
        value = math.exp(log_value - log_normalizer)
    except OverflowError:
        _range("information: normalized value overflow")
    if not math.isfinite(value) or value == 0:
        _range("information: positive normalized value cannot be displayed")
    return value


class GeneralRecordLaw:
    """piecewiseも含むW全体の恒等式。各写しの中でTを先に積分する。

    求積の絶対誤差はφの連続性と、履歴で割る誤差を通して運ぶ。
    δE/δZ、φの残り、全λ/片/分割の求積を最終の一つの幅で管理。
    """

    def __init__(self, priors, weights, cells, *, history=None, tails=None):
        self.backend = ReplicaMoments(priors)
        self.weights = tuple(_fraction(w) for w in weights)
        if (not self.weights or any(w <= 0 for w in self.weights)
                or not math.isclose(float(sum(self.weights)), 1., rel_tol=0, abs_tol=1e-12)):
            raise ValueError("record law: expected positive normalized weights")
        original_count = len(self.weights)
        self.cells = {z: {e: tuple(row) for e, row in values.items()} for z, values in cells.items()}
        if not self.cells or any(not row or any(len(v) != len(self.weights) or
                any(not isinstance(p, KernelEvent) or p.inverted for p in v) for v in row.values())
                for row in self.cells.values()):
            raise ValueError("record law: expected nonempty tables of kernel events")
        if any(isinstance(p, ConjunctionEvent) for row in self.cells.values() for v in row.values() for p in v):
            raise ValueError("record law: cells must be unions of record preimages")
        selected, combined, columns = [], [], []
        for lam, weight in enumerate(self.weights):
            column = tuple(values[lam] for row in self.cells.values() for values in row.values())
            if column in columns:
                combined[columns.index(column)] += weight
            else:
                columns.append(column)
                selected.append(lam)
                combined.append(weight)
        self.weights = tuple(combined)
        self.cells = {z: {e: tuple(values[i] for i in selected) for e, values in row.items()}
                      for z, row in self.cells.items()}
        self.a = {z: tuple(UnionEvent(tuple(row[lam] for row in values.values()))
                          for lam in range(len(self.weights))) for z, values in self.cells.items()}
        self.history = tuple(UnionEvent(tuple(values[lam] for values in self.a.values()))
                              for lam in range(len(self.weights)))
        if history is not None and len(history) != original_count:
            raise ValueError("record law: history candidate count differs")
        self.requested_history = None if history is None else tuple(history[i] for i in selected)
        if self.requested_history is not None and len(self.requested_history) != len(self.weights):
            raise ValueError("record law: history candidate count differs")
        self.tails = EntropyTailBounds(-math.inf, -math.inf) if tails is None else tails
        self._moments = {}
        self._checked = False

    def _moment(self, factors, goal, work, partition_budget):
        key = tuple(id(p) for p in factors)
        cached = self._moments.get(key)
        if cached is not None and cached.log_width <= math.log(goal):
            return cached
        remaining = None if work.limit is None else work.limit - work.nodes
        probability = factors[0] if len(factors) == 1 else ReplicaProduct(factors)
        value = self.backend.expectation(probability, tolerance=goal,
            partition_budget=partition_budget, node_budget=remaining)
        work.consume(value.nodes)
        self._moments[key] = value
        return value

    def _check_records(self, goal, work, partition_budget):
        if self._checked:
            return
        # 同じ外の条件の履歴を包むこと、枝どうしが重ならないことを、
        # 同一の所要/時刻上の事象の差として検査する (独立な写しの積ではない)。
        for lam in range(len(self.weights)):
            rows = tuple(p[lam] for row in self.cells.values() for p in row.values())
            for i, left in enumerate(rows):
                for right in rows[i + 1:]:
                    overlap = ConjunctionEvent((left, right))
                    value = self.backend.expectation(overlap, tolerance=goal, partition_budget=partition_budget,
                        node_budget=None if work.limit is None else work.limit - work.nodes)
                    work.consume(value.nodes)
                    if value.log_upper != -math.inf:
                        raise ValueError("record law: records overlap under the prior")
            if self.requested_history is not None:
                expected, actual = self.requested_history[lam], self.history[lam]
                for left, right in ((expected, actual), (actual, expected)):
                    difference = ConjunctionEvent((left, right.complement()))
                    value = self.backend.expectation(difference, tolerance=goal, partition_budget=partition_budget,
                        node_budget=None if work.limit is None else work.limit - work.nodes)
                    work.consume(value.nodes)
                    if value.log_upper != -math.inf:
                        raise ValueError("record law: record sum differs from history in the same external conditions")
        self._checked = True

    def information(self, *, tolerance, terms=None, series_budget=None, partition_budget=None, node_budget=None):
        tolerance = _number(tolerance, "information tolerance", positive=True)
        if terms is not None and (type(terms) is not int or terms < 0):
            raise ValueError("information: expected nonnegative integer terms")
        if series_budget is not None and (type(series_budget) is not int or series_budget < 0):
            raise ValueError("information: expected nonnegative series budget")
        if terms is not None and series_budget is not None and terms > series_budget:
            raise IntegrationIncomplete("information: series-work resource budget exhausted")
        work = _IntegrationWork(node_budget)
        size = sum(len(row) for row in self.cells.values()) + len(self.cells)
        goal = tolerance / (32 * size)
        count = 0 if terms is None else terms
        complements = {}
        while True:
            if goal == 0:
                _range("information: positive integration budget disappeared")
            self._check_records(goal, work, partition_budget)
            raw_means = {z: {e: tuple(self._moment((p,), goal, work, partition_budget) for p in values)
                            for e, values in row.items()} for z, row in self.cells.items()}
            means = {z: {e: sum_integrals(values, self.weights) for e, values in row.items()}
                     for z, row in raw_means.items()}
            plus, minus = [], []
            for z, row in self.cells.items():
                for lam, weight in enumerate(self.weights):
                    supported = [e for e in row if raw_means[z][e][lam].log_upper != -math.inf]
                    # 非負の事象の他の枝が全て確率0ならA=Bを証明できる。
                    # 決まった記録に一般のφの残りを当てない。
                    if len(supported) <= 1:
                        continue
                    plus.append((self.a[z][lam], weight))
                    minus.extend((row[e][lam], weight) for e in supported)
            for p, _ in plus + minus:
                if id(p) not in complements:
                    complements[id(p)] = p.complement()
            a_means = {z: sum_integrals(tuple(row.values()), (Fraction(1),) * len(row))
                       for z, row in means.items()}
            evidence = sum_integrals(tuple(a_means.values()), (Fraction(1),) * len(a_means))
            if evidence.log_upper == -math.inf:
                from .inference import ModelViolation
                raise ModelViolation("quantity: observations have zero probability")
            if evidence.log_lower == -math.inf:
                goal /= 4
                continue
            # 全λを混ぜた予測のエントロピー。φ(b)−φ(a)をRで割る。
            variable = {z: tuple(p for p in row.values() if p.log_upper != -math.inf)
                        for z, row in means.items()}
            predictive = math.fsum(
                [_normalized_positive(_phi_log_probability(min(0., p.log_value)), evidence.log_value)
                 for z, row in variable.items() if len(row) > 1 for p in row]
                + [-_normalized_positive(_phi_log_probability(min(0., a_means[z].log_value)), evidence.log_value)
                   for z, row in variable.items() if len(row) > 1])
            log_c_error = _logadd(
                [_log_entropy_continuity(_logadd((p.log_error, p.log_tail)))
                 for z, row in variable.items() if len(row) > 1 for p in row]
                + [_log_entropy_continuity(_logadd((a_means[z].log_error, a_means[z].log_tail)))
                   for z, row in variable.items() if len(row) > 1])
            partials, remainders = [], []
            for collection in (plus, minus):
                additions, residuals = [], []
                for p, weight in collection:
                    complement = complements[id(p)]
                    local = []
                    for m in range(1, count + 1):
                        value = self._moment((p,) + (complement,) * m, goal / (m + 1) ** 2,
                                             work, partition_budget)
                        additions.append((value, weight / m))
                        local.append((value, Fraction(1, m)))
                    remainder = self._moment((complement,) * (count + 1), goal,
                                              work, partition_budget)
                    residual_weight = weight / (count + 1)
                    if terms is None:
                        # Jensen is a second exact upper bound for the same φ.
                        # The branch/moment remains present, even for tiny mass.
                        mean = self._moment((p,), goal, work, partition_budget)
                        other = self._moment((complement,), goal, work, partition_budget)
                        # φ(x) ≤ 1−x also avoids subtracting a tiny complement from 1.
                        bound = min(_phi_log_probability(mean.log_upper) if mean.log_upper <= -1. else -1.,
                                    other.log_upper)
                        partial = sum_integrals((v for v, _ in local), (w for _, w in local))
                        if partial.log_lower == -math.inf or bound > partial.log_lower:
                            residual = (bound if partial.log_lower == -math.inf else
                                        bound + math.log(-math.expm1(partial.log_lower - bound)))
                            remainder = IntegralEstimate(min(remainder.log_upper - math.log(count + 1), residual), -math.inf)
                            residual_weight = weight
                    residuals.append((remainder, residual_weight))
                partials.append(sum_integrals((v for v, _ in additions), (w for _, w in additions)))
                remainders.append(sum_integrals((v for v, _ in residuals), (w for _, w in residuals)))
            center = math.fsum((predictive,
                _normalized_positive(partials[0].log_value, evidence.log_value),
                -_normalized_positive(partials[1].log_value, evidence.log_value)))
            log_r_error = _logadd((evidence.log_error, evidence.log_tail))
            log_quad = _logadd((_logadd((log_c_error, *(_logadd((p.log_error, p.log_tail)) for p in partials)))
                               - evidence.log_lower,
                (math.log(abs(center)) + log_r_error - evidence.log_lower
                 if center and log_r_error != -math.inf else -math.inf)))
            errors = tuple(r.log_upper - evidence.log_lower for r in remainders)
            log_series_width = _logadd(errors)
            log_width = _logadd((math.log(2) + log_quad, log_series_width, self.tails.log_width))
            below = _normalized_positive(_logadd((log_quad, errors[1], self.tails.log_z)), 0.)
            above = _normalized_positive(_logadd((log_quad, errors[0], self.tails.log_e, self.tails.log_z)), 0.)
            lower, upper = max(0., center - below), center + above
            if not math.isfinite(upper) or upper < lower:
                _range("information: quadrature/series bounds lost their order")
            result = InformationComputation(InformationBounds(lower, upper), log_width, log_series_width,
                QuantityStats(partitions=self.backend.partitions, series_terms=count,
                              aggregated_records=sum(len(row) for row in self.cells.values()),
                              integration_nodes=work.nodes))
            if terms is not None or log_width <= math.log(tolerance):
                return result
            if self.tails.log_width > math.log(tolerance):
                raise IntegrationIncomplete("information: record aggregation must be refined")
            if math.log(2) + log_quad > math.log(tolerance / 4):
                goal /= 4
                continue
            if series_budget is not None and count >= series_budget:
                raise IntegrationIncomplete("information: series-work resource budget exhausted")
            count += 1


class RecordEvent(KernelEvent):
    """K(h|d)と、未来の記録の前像。新しい時刻を一様に置かない。

    selectors=(試み, 種類, 下限, 上限)。finite/infiniteは古い同じDの印、
    recordは時計の読み、durationは潜在の量の照会。その他も有限の領域。
    """

    def __init__(self, kernel, selectors=(), inverted=False, *, order=()):
        super().__init__((kernel,), inverted)
        object.__setattr__(self, "selectors", tuple(selectors))
        object.__setattr__(self, "order", tuple(order))
        keys = {a.attempt for a in kernel.attempts}
        if len(set(self.order)) != len(self.order) or any(ref not in keys for ref in self.order):
            raise ValueError("record event: invalid report order")
        if any(ref not in keys or kind not in ("finite", "infinite", "record", "other", "duration", "point")
               for ref, kind, _, _ in self.selectors):
            raise ValueError("record event: invalid duration selector")

    def __eq__(self, other):
        return (type(self) is type(other) and self.kernels == other.kernels
                and self.selectors == other.selectors and self.order == other.order
                and self.inverted == other.inverted)

    def complement(self):
        return RecordEvent(self.kernels[0], self.selectors, not self.inverted, order=self.order)

    def raw_regions(self, durations, dimension, *, ranks=None):
        kernel = self.kernels[0]
        raw = kernel.raw_constraints(durations, dimension, ranks=ranks)
        if isinstance(ranks, _TieRanks):
            ranks = ranks.by_kernel[id(kernel)]
        constraints = None if raw is None else list(raw)
        attempts = {a.attempt: a for a in kernel.attempts}
        extra = (Fraction(0),) * (dimension - kernel.dimension)
        if constraints is not None:
            for ref, kind, lower, upper in self.selectors:
                duration = durations[ref]
                if kind == "infinite":
                    if duration is not None:
                        constraints = None
                        break
                    continue
                if duration is None:
                    constraints = None
                    break
                if kind == "finite":
                    continue
                value = duration
                if kind in ("record", "other"):
                    start = kernel._external[attempts[ref].start_event] + extra
                    value = tuple(s + d for s, d in zip(start, duration))
                    if kind == "record" and kernel.spec.name == "tick":
                        width = kernel.spec.params["width_ns"]
                        reading = kernel.timing.events[attempts[ref].start_event].reading
                        if (lower - reading) % width:
                            constraints = None
                            break
                        upper = lower + width
                    elif kind == "record":
                        upper = lower
                constraints.append(((value[0] - lower,) + value[1:], False))
                if upper is not None:
                    constraints.append(((upper - value[0],) + tuple(-x for x in value[1:]),
                                        kind not in ("point",) and upper != lower))
        if constraints is not None:
            arrivals = _arrival_expressions(kernel, durations, dimension)
            if any(ref not in arrivals for ref in self.order):
                constraints = None
            else:
                for before, after in zip(self.order, self.order[1:]):
                    if not _tie_precedes(before, after, arrivals, ranks):
                        constraints = None
                        break
                    constraints.append((_affine_subtract(arrivals[after], arrivals[before]), False))
        inside = () if constraints is None else (tuple(constraints),)
        universe = tuple((a + extra, strict) for a, strict in kernel._constraints)
        if not self.inverted:
            return inside
        remaining = (universe,)
        for selected in inside:
            remaining = _outside_constraints(remaining, selected)
        return remaining


class UnionEvent(KernelEvent):
    """前像の有限和。選択の制約も保持し、重なりを非負の領域で除く。"""

    def __init__(self, parts, inverted=False):
        parts = tuple(parts)
        super().__init__(tuple(k for part in parts for k in part.kernels), inverted)
        object.__setattr__(self, "parts", parts)

    def __eq__(self, other):
        return type(self) is type(other) and self.parts == other.parts and self.inverted == other.inverted

    def complement(self):
        return UnionEvent(self.parts, not self.inverted)

    def raw_regions(self, durations, dimension, *, ranks=None):
        first = self.kernels[0]
        extra = (Fraction(0),) * (dimension - first.dimension)
        remaining = (tuple((a + extra, strict) for a, strict in first._constraints),)
        inside = []
        for part in self.parts:
            local = part.raw_regions(durations, dimension, ranks=ranks)
            for selected in local:
                for region in remaining:
                    clean = _clean_constraints(region + selected)
                    if clean is not None:
                        inside.append(clean)
                remaining = _outside_constraints(remaining, selected)
        return remaining if self.inverted else tuple(inside)


def _isolated_selection_event(event):
    if isinstance(event, UnionEvent) and all(type(p) is KernelEvent for p in event.parts):
        return _isolated_polynomial_event(KernelEvent(event.kernels, event.inverted))
    first = event.kernels[0]
    if first.spec.name != "tick" or len(first.attempts) != 1:
        return None
    attempt = first.attempts[0]
    if attempt.state != "pending" or attempt.check_events:
        return None
    width, phase = first.spec.params["width_ns"], first.spec.params["phase"]
    start = first.timing.events[attempt.start_event].reading
    # Events in the start's tick would change its phase law. Other ticks cancel.
    if any(ref != attempt.start_event and
           start - width < first.timing.events[ref].reading < start + width for ref in first.external_ids):
        return None
    ranges, infinite = [], False
    def collect(part):
        nonlocal infinite
        if part.inverted:
            return False
        if isinstance(part, UnionEvent):
            return all(collect(p) for p in part.parts)
        if part.kernels != (first,):
            return False
        if type(part) is KernelEvent:
            ranges.append((Fraction(0), None))
            infinite = True
            return True
        if not isinstance(part, RecordEvent) or len(part.selectors) > 1:
            return False
        if not part.selectors:
            ranges.append((Fraction(0), None))
            # Even a one-report order asserts that this report is finite.
            infinite = infinite or not part.order
            return True
        ref, kind, lo, hi = part.selectors[0]
        if ref != attempt.attempt:
            return False
        if part.order and kind == "infinite":
            return True  # empty intersection: an infinite attempt cannot report
        if kind == "infinite":
            infinite = True
        elif kind == "finite":
            ranges.append((Fraction(0), None))
        elif kind in ("record", "other"):
            if (lo - start) % width:
                return kind == "record"
            ranges.append((Fraction(lo - start), None if kind == "other" else Fraction(lo - start + width)))
        else:
            return False
        return True
    original = event.complement() if event.inverted else event
    if not collect(original):
        return None
    merged = []
    for lo, hi in sorted(ranges, key=lambda p: p[0]):
        if merged and (merged[-1][1] is None or lo <= merged[-1][1]):
            oldlo, oldhi = merged.pop()
            merged.append((oldlo, None if oldhi is None or hi is None else max(oldhi, hi)))
        else:
            merged.append((lo, hi))
    boundaries = {Fraction(0)}
    for lo, hi in merged:
        for value in (lo, hi):
            if value is not None:
                offsets = (value - width, value) if phase == "uniform" else (value - phase["point_ns"],)
                boundaries.update(max(Fraction(0), p) for p in offsets)
    boundaries, pieces = sorted(boundaries), []
    for lo, hi in zip(boundaries, boundaries[1:] + [None]):
        sample = lo + 1 if hi is None else (lo + hi) / 2
        def above(bound):
            if bound is None:
                return Fraction(0), Fraction(0)
            if phase != "uniform":
                return Fraction(int(sample + phase["point_ns"] >= bound)), Fraction(0)
            if sample >= bound:
                return Fraction(1), Fraction(0)
            if sample <= bound - width:
                return Fraction(0), Fraction(0)
            return 1 - bound / width, Fraction(1, width)
        values = [tuple(a - b for a, b in zip(above(low), above(high))) for low, high in merged]
        constant, slope = (sum(v[i] for v in values) for i in range(2))
        if event.inverted:
            constant, slope = 1 - constant, -slope
        pieces.append(PolynomialPiece(lo, hi, (constant, slope)))
    return attempt.action, PolynomialLikelihood(tuple(pieces), Fraction(int(infinite != event.inverted)))


@dataclass(frozen=True, slots=True)
class QuantityQuery:
    action: str
    lower: int = 0
    upper: int | None = None
    attempt: object | None = None
    infinite: bool = False


@dataclass(frozen=True, slots=True)
class FutureRecordsQuery:
    action: str
    now_ns: int
    run: object
    pending: tuple = ()


def timing_context(timing, *, run, observed_ns, check_events=(), fact_ancestors=None):
    """事実の読みを変えず、呼ぶ側の保証と確かめの出どころを適用。"""
    if type(observed_ns) is not int:
        raise ValueError("quantity context: integer observed_ns is required")
    events, extra, positions = dict(timing.events), [], dict(timing.positions)
    fact_ancestors = {} if fact_ancestors is None else fact_ancestors
    lookup = {str(ref): ref for ref in events}
    excluded = _excluded_timing_events(timing)
    for index, source in enumerate(check_events):
        if not isinstance(source, Mapping):
            raise ValueError("check_events: expected fact or unrecorded source")
        if set(source) == {"fact"}:
            if source["fact"] not in lookup:
                raise ValueError("check_events: unknown fact")
            # Existing receipts, including excluded cross-run receipts, are not new checks.
            continue
        if set(source) != {"unrecorded"}:
            raise ValueError("check_events: expected fact or unrecorded source")
        value = source["unrecorded"]
        if (not isinstance(value, Mapping) or set(value) != {"kind", "reading", "after"}
                or value["kind"] not in ("tick", "thought") or type(value["reading"]) is not int
                or value["reading"] > observed_ns):
            raise ValueError("check_events: invalid unrecorded receipt")
        after = value["after"]
        if (not isinstance(after, (tuple, list)) or any(not isinstance(cid, str) for cid in after)
                or list(after) != sorted(set(after)) or any(cid not in fact_ancestors for cid in after)):
            raise ValueError("check_events: after must be a known canonical frontier")
        prior = [e for e in events.values() if e.run == run]
        if not prior:
            raise ValueError("quantity context: current run is required")
        run_index, seq = max((e.run_index, e.seq) for e in prior)
        ref = ("check", index)
        if ref in events:
            raise ValueError("check_events: duplicate event identity")
        events[ref] = TimingEvent(ref, run, run_index, seq + 1, value["reading"], "unrecorded", None)
        positions[ref] = frozenset().union(*(fact_ancestors[cid] for cid in after))
        extra.append(ref)
    attempts = []
    for a in timing.attempts:
        checks = tuple(ref for ref in a.check_events if ref not in excluded and
                       (events[ref].run != run or events[ref].reading <= observed_ns))
        start = events.get(a.start_event)
        if a.state == "pending" and start is not None and start.run == run:
            checks += tuple(ref for ref in extra if start.id in positions[ref])
        attempts.append(AttemptTiming(a.attempt, a.job, a.action, a.start_event, checks, a.report_event, a.state))
    return Timing(events, tuple(attempts), positions)


class QuantityPosterior:
    """モデルと事実を保持する結合の信念。保存した件数/平均から復元しない。"""
    value_space = ValueSpace("quantity", "1")
    condition_keys = ("action",)

    def __init__(self, priors, measure, timing, *, tolerance=1e-12):
        self.priors = MappingProxyType({a: duration_prior(p) for a, p in priors.items()})
        self.measure, self.timing = measure_prior(measure), timing
        self.tolerance = _number(tolerance, "posterior tolerance", positive=True)
        if all(p.base.name == "atoms" for p in self.priors.values()):
            self.base = atoms_posterior(self.priors, self.measure, timing)
            self.evidence = IntegralEstimate(self.base.log_evidence, -math.inf)
        else:
            self.base = partition_evidence(self.priors, self.measure, timing, tolerance=self.tolerance)
            self.evidence = self.base.evidence
        self.stats = self.base.stats

    @property
    def measure_weights(self):
        if isinstance(self.base, AtomsPosterior):
            return self.base.measure_weights
        return tuple(sum_integrals((self.base.estimates[i] for i, entry in enumerate(self.base.entries) if entry.lam == lam),
                                   (entry.weight for entry in self.base.entries if entry.lam == lam)).log_value
                     - self.evidence.log_value for lam in range(len(self.measure.candidates)))

    def _probability(self, events, kernels, tolerance):
        backend, goal = ReplicaMoments(self.priors), tolerance / 8
        while True:
            numerator = sum_integrals((backend.expectation(p, tolerance=goal) for p in events),
                                     (c.weight for c in self.measure.candidates))
            denominator = sum_integrals((backend.expectation(KernelEvent((k,)), tolerance=goal) for k in kernels),
                                       (c.weight for c in self.measure.candidates))
            result = condition_probability(numerator, denominator)
            if result.log_width <= math.log(tolerance):
                return result, numerator, denominator
            goal /= 4
            if goal == 0:
                _range("predictive: positive integration budget disappeared")

    def predictive(self, query):
        if type(query) is str and isinstance(self.base, AtomsPosterior):
            return self.base.new_value(query)
        if not isinstance(query, QuantityQuery) or query.action not in self.priors:
            raise ValueError("quantity predictive: expected QuantityQuery")
        if (type(query.lower) is not int or query.lower < 0 or
                (query.upper is not None and (type(query.upper) is not int or query.upper <= query.lower))
                or type(query.infinite) is not bool):
            raise ValueError("quantity predictive: invalid interval")
        timing, ref = self.timing, query.attempt
        if ref is None:
            ref, start = ("query", query.action), ("query-start", query.action)
            events = dict(timing.events)
            events[start] = TimingEvent(start, ("query-run",), -1, 0, 0, "start", ref)
            timing = Timing(events, timing.attempts + (AttemptTiming(ref, ref, query.action, start, (), None, "pending"),), timing.positions)
        elif not any(a.attempt == ref and a.action == query.action for a in timing.attempts):
            raise ValueError("quantity predictive: unknown attempt/action")
        kernels = tuple(HistoryKernel(timing, c.spec) for c in self.measure.candidates)
        selection = (ref, "infinite" if query.infinite else "duration", query.lower, query.upper)
        events = tuple(RecordEvent(k, (selection,)) for k in kernels)
        return self._probability(events, kernels, self.tolerance)[0]

    def future_records(self, query, *, tolerance=None):
        return FutureRecordTable(self, query, tolerance=self.tolerance if tolerance is None else tolerance)

    def information(self, target, evidence, given) -> InformationBounds:
        if target not in ("distribution", "all_distributions_and_measure") or not isinstance(evidence, FutureRecordsQuery):
            raise ValueError("quantity information: expected full W and FutureRecordsQuery")
        if given is not None:
            evidence = FutureRecordsQuery(evidence.action, evidence.now_ns, evidence.run, tuple(given))
        return self.future_records(evidence).information().bounds


def posterior(prior, measure, attempts, *, tolerance=1e-12):
    if not isinstance(attempts, Timing):
        raise ValueError("quantity posterior: expected Timing")
    return QuantityPosterior(prior, measure, attempts, tolerance=tolerance)


class FutureRecordTable:
    """有限の記録/その他/∞の前像の表。各枝は同じKと古いDを条件づける。"""

    def __init__(self, belief, query, *, tolerance):
        if (not isinstance(query, FutureRecordsQuery) or query.action not in belief.priors
                or type(query.now_ns) is not int):
            raise ValueError("future records: expected action/run/integer now_ns")
        self.belief, self.query = belief, query
        self.tolerance = _number(tolerance, "information tolerance", positive=True)
        events, attempts = dict(belief.timing.events), list(belief.timing.attempts)
        current = [e for e in events.values() if e.run == query.run]
        if not current:
            raise ValueError("future records: current run is required")
        run_index, seq = max((e.run_index, e.seq) for e in current)
        waiting = []
        for job, action in query.pending:
            if action not in belief.priors:
                raise ValueError("future records: unknown pending action")
            rows = [a for a in attempts if a.job == job and a.state in ("pending", "queued")]
            if len(rows) != 1:
                raise ValueError("future records: exactly one pending attempt per job is required (S5)")
            row = rows[0]
            if row.state == "queued":
                ref, start = ("queued", str(job)), ("queued-start", str(job))
                seq += 1
                events[start] = TimingEvent(start, query.run, run_index, seq, query.now_ns, "start", ref)
                row = AttemptTiming(ref, job, action, start, (), None, "pending")
                attempts = [a for a in attempts if a.job != job] + [row]
            waiting.append(row)
        ref, start = ("candidate", query.action), ("candidate-start", query.action)
        seq += 1
        events[start] = TimingEvent(start, query.run, run_index, seq, query.now_ns, "start", ref)
        candidate = AttemptTiming(ref, ref, query.action, start, (), None, "pending")
        attempts.append(candidate)
        self.waiting, self.candidate = tuple(waiting), candidate
        self.timing = Timing(events, tuple(attempts), belief.timing.positions)
        self.kernels = tuple(HistoryKernel(self.timing, c.spec) for c in belief.measure.candidates)
        backend = ReplicaMoments(belief.priors)
        goal = self.tolerance / 32
        while True:
            self.evidence = sum_integrals((backend.expectation(KernelEvent((k,)), tolerance=goal) for k in self.kernels),
                                         (c.weight for c in belief.measure.candidates))
            if self.evidence.log_upper == -math.inf:
                from .inference import ModelViolation
                raise ModelViolation("quantity: observations have zero probability")
            if self.evidence.log_lower != -math.inf:
                break
            goal /= 4
            if goal == 0:
                _range("future records: history lower bound disappeared")
        width = max((c.spec.params["width_ns"] for c in belief.measure.candidates if c.spec.name == "tick"), default=0)
        extent = max((max((d for d, mass in p.base.params["points"] if d is not None and mass), default=0)
                      if p.base.name == "atoms" else p.base.params["edges_ns"][-1] for p in belief.priors.values()), default=0)
        self.cutoff = max(1, extent + width + 1)

    def _numeric(self, attempt):
        return self.timing.events[attempt.start_event].run == self.query.run

    def _labels(self, attempt):
        if not self._numeric(attempt):
            return ("finite", "infinite")
        start = self.timing.events[attempt.start_event].reading
        readings = set()
        for c in self.belief.measure.candidates:
            if c.spec.name == "tick":
                width = c.spec.params["width_ns"]
                readings.update(start + i * width for i in range((self.cutoff + width - 1) // width))
            else:
                readings.update(start + d for d, mass in self.belief.priors[attempt.action].base.params["points"]
                                if d is not None and mass)
        return (*sorted(readings), "other", "infinite")

    def _selector(self, attempt, label, candidate):
        if label in ("finite", "infinite"):
            return (attempt.attempt, label, 0, None)
        if label == "other":
            cutoff = self.cutoff
            if candidate.spec.name == "tick":
                width = candidate.spec.params["width_ns"]
                cutoff = ((cutoff + width - 1) // width) * width
            return (attempt.attempt, "other", self.timing.events[attempt.start_event].reading + cutoff, None)
        return (attempt.attempt, "record", label, None)

    def _tail_bounds(self):
        values = []
        for attempt in (*self.waiting, self.candidate):
            if not self._numeric(attempt):
                values.append(-math.inf)
                continue
            values.append(RecordTailBound(self.belief.priors[attempt.action].base,
                self.belief.measure, self.evidence.log_lower).log_bound(self.cutoff))
        return EntropyTailBounds(values[-1], _logadd(values[:-1]))

    def build(self):
        self.tails = self._tail_bounds()
        self.cells = {}
        for readings in product(*(self._labels(a) for a in self.waiting)):
            ordered = tuple(a.attempt for a, label in zip(self.waiting, readings)
                            if self._numeric(a) and label != "infinite")
            for order in permutations(ordered):
                z = (readings, order)
                self.cells[z] = {}
                for reading in self._labels(self.candidate):
                    positions = range(len(order) + 1) if reading != "infinite" else (None,)
                    for position in positions:
                        whole = (order[:position] + (self.candidate.attempt,) + order[position:]
                                 if position is not None else order)
                        self.cells[z][reading, position] = tuple(RecordEvent(k,
                            tuple(self._selector(a, label, c) for a, label in
                                  zip((*self.waiting, self.candidate), (*readings, reading))), order=whole)
                            for k, c in zip(self.kernels, self.belief.measure.candidates))
        return self.cells

    def information(self, *, terms=None, series_budget=None, partition_budget=None, node_budget=None):
        while True:
            try:
                tails = self._tail_bounds()
            except ValueError as exc:
                if "cutoff" not in str(exc):
                    raise
                self.cutoff *= 2
                continue
            if terms is not None or tails.log_width <= math.log(self.tolerance / 4):
                break
            self.cutoff *= 2
        while True:
            cells = self.build()
            histories = tuple(KernelEvent((k,)) for k in self.kernels)
            if all(p.base.name == "atoms" for p in self.belief.priors.values()):
                measure = AtomicPolynomialMeasure(self.belief.priors)
                law = AtomicRecordLaw(measure, (c.weight for c in self.belief.measure.candidates),
                    {z: {e: tuple(measure.likelihood(p) for p in row) for e, row in values.items()}
                     for z, values in cells.items()}, history=tuple(measure.likelihood(h) for h in histories), tails=self.tails)
                return law.information(tolerance=self.tolerance, terms=terms, series_budget=series_budget,
                                       node_budget=node_budget)
            law = GeneralRecordLaw(self.belief.priors, (c.weight for c in self.belief.measure.candidates),
                                   cells, history=histories, tails=self.tails)
            # The constructor's per-trial intervals, finite other and infinite
            # are disjoint and cover the clock preimages on the base support.
            # Their Cartesian product and exclusive report orders partition
            # this SAME external history (including the shared tie ranks);
            # no normalization by the sum of a deficient table is performed.
            law._checked = True
            return law.information(tolerance=self.tolerance, terms=terms, series_budget=series_budget,
                                   partition_budget=partition_budget, node_budget=node_budget)

    def arrival_masks(self, *, tolerance):
        """Zの名前の項には尾を切らず、有限/∞の印の周辺を直接使う。"""
        result = {}
        goal, backend = tolerance / (8 * 2 ** len(self.waiting)), ReplicaMoments(self.belief.priors)
        while True:
            denominator = sum_integrals((backend.expectation(KernelEvent((k,)), tolerance=goal) for k in self.kernels),
                                        (c.weight for c in self.belief.measure.candidates))
            for mask in product((False, True), repeat=len(self.waiting)):
                events = tuple(RecordEvent(k, tuple((a.attempt, "finite" if present else "infinite", 0, None)
                               for a, present in zip(self.waiting, mask))) for k in self.kernels)
                numerator = sum_integrals((backend.expectation(p, tolerance=goal) for p in events),
                                         (c.weight for c in self.belief.measure.candidates))
                result[mask] = (condition_probability(numerator, denominator),
                                numerator.log_value - denominator.log_value)
            if _logadd(p.log_width for p, _ in result.values()) <= math.log(tolerance):
                return result
            goal /= 4
            if goal == 0:
                _range("arrival masks: positive integration budget disappeared")


@dataclass(frozen=True, slots=True)
class OneStepValues:
    expected_cost: float
    information: InformationBounds
    names_information: float
    durations_information: InformationBounds
    stats: QuantityStats


def one_step_values(belief, names, pending, candidate, costs, *, tolerance):
    """Qなし・候補は有限。共通の到着の印で条件づけた後にUとWを分解。

    hの尤度はL_names(U)L_quantity(W)。Zの印を固定すればZの名前はU、
    時刻はWだけの尤度なので、事後も積。候補Y/Eも別々の尤度。
    したがって連鎖の式は名前の項+W全体の項へ帰着する (§3-5)。
    """
    if names.model.Q is not None or belief.priors[candidate.action].base.p_inf > 0:
        from .lookahead import OutsideEvaluationType
        raise OutsideEvaluationType("one_step requires every candidate to return a result")
    from .names import NameQuery
    from .lattice import hand_table, one_step_components
    tolerance = _number(tolerance, "information tolerance", positive=True)
    query = FutureRecordsQuery(candidate.action, candidate.now_ns, candidate.run, tuple(pending))
    table = belief.future_records(query, tolerance=tolerance / 2)
    duration = table.information()
    masks = table.arrival_masks(tolerance=tolerance / 16)
    additions, errors = [], []
    for mask, (probability, log_weight) in masks.items():
        if probability.log_upper == -math.inf:
            continue
        given = tuple((job, action, candidate.now_ns if present else None)
                      for (job, action), present in zip(pending, mask))
        name_table = hand_table(names.model, names._history(), given, candidate.action, capture_ns=candidate.now_ns)
        _, information = one_step_components(names.model, name_table, candidate.action, [0.] * len(costs))
        if information:
            additions.append(_normalized_positive(log_weight + math.log(information), 0.))
            errors.append(probability.log_width + math.log(information))
    name_value, name_error = math.fsum(additions), _logadd(errors)
    prediction = names.predictive(NameQuery(candidate.action, candidate.now_ns))
    weighted = []
    for log_p, value in zip(prediction, costs):
        if log_p == -math.inf or value == 0:
            continue
        if value == math.inf:
            weighted = [math.inf]
            break
        if not math.isfinite(value):
            _range("one_step: nonfinite cost")
        weighted.append(math.copysign(_normalized_positive(float(log_p) + math.log(abs(value)), 0.), value))
    try:
        expected = math.fsum(weighted)
    except OverflowError:
        _range("one_step: expected cost exceeds numerical range")
    error = _normalized_positive(name_error, 0.)
    bounds = InformationBounds(max(0., name_value + duration.bounds.lower - error),
                               name_value + duration.bounds.upper + error)
    if _logadd((duration.log_width, math.log(2) + name_error)) > math.log(tolerance):
        # Recompute the same formula at a tighter computational tolerance.
        return one_step_values(belief, names, pending, candidate, costs, tolerance=tolerance / 2)
    return OneStepValues(expected, bounds, name_value, duration.bounds, duration.stats)
