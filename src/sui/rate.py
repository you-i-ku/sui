"""S4b-2 mathematics and certificates (v0.8 §3-10-4 through §3-10-6)."""

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from types import MappingProxyType as _MappingProxyType
import hashlib as _hashlib
import json as _json

try:
    from gmpy2 import mpq as _InformationScalar
except (ImportError, OSError):
    _InformationScalar = _Fraction

from .contracts import ContractRef as _ContractRef
from .agent import ModelFalsified as _ModelFalsified, RebuildMismatch as _RebuildMismatch
from .ids import Ref as _Ref
from .inference import NumericalRange as _NumericalRange
from .lookahead import NoAdmissibleCandidate as _NoAdmissibleCandidate, \
    OutsideEvaluationType as _OutsideEvaluationType
from .quantity import IntegrationIncomplete as _IntegrationIncomplete


# --- 例外 (§3-10-6)。すべて reason・detail・field を持つ -------------------------

class _RateErrorMixin:
    def __init__(self, reason: str, detail: str = "", field: str | None = None):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail, self.field = reason, detail, field


class RateInputError(_RateErrorMixin, ValueError): pass
class RateSpecificationMissing(_RateErrorMixin, ValueError): pass
class RateIncomplete(_RateErrorMixin, _IntegrationIncomplete): pass
class RateOutsideEvaluationType(_RateErrorMixin, _OutsideEvaluationType): pass
class RateModelFalsified(_RateErrorMixin, _ModelFalsified): pass
class RateNumericalRange(_RateErrorMixin, _NumericalRange): pass
class RateNoAdmissibleCandidate(_RateErrorMixin, _NoAdmissibleCandidate): pass
class RateReplayUnavailable(_RateErrorMixin, LookupError): pass
class RateReplayMismatch(_RebuildMismatch):
    """root・evidence・interval・selection・intent・inputs のどれが違ったかを fields に。"""
    def __init__(self, reason: str, detail: str = "", field: str | None = None, *,
                 fields: tuple[str, ...] = ()):
        super().__init__(fields=fields)
        self.args = (f"{reason}: {detail}" if detail else reason,)
        self.reason, self.detail, self.field = reason, detail, field
class RateRuntimeUnverified(_RateErrorMixin, RuntimeError): pass


# --- 型 (§3-10-4) -------------------------------------------------------------

@_dataclass(frozen=True, slots=True)
class RationalInterval:
    lower: _Fraction
    upper: _Fraction

    def __post_init__(self):
        if not isinstance(self.lower, _Fraction) or not isinstance(self.upper, _Fraction) or self.lower > self.upper:
            raise RateNumericalRange("invalid_interval", "ordered Fraction endpoints required")


@_dataclass(frozen=True, slots=True)
class RateBudget:
    """実行側が渡す計算の予算 (§3-10-10 G2)。モデル・好み・行動の規則ではない。"""
    tolerance: _Fraction
    max_cells: int
    max_terms: int
    max_refinements: int

    def __post_init__(self):
        if (not isinstance(self.tolerance, _Fraction) or self.tolerance <= 0 or
                any(type(v) is not int or v <= 0 for v in
                    (self.max_cells, self.max_terms, self.max_refinements))):
            raise RateInputError("invalid_budget", "positive Fraction tolerance and positive integer limits required")


def default_rate_budget() -> RateBudget:
    """標準の予算 (tolerance 1/10⁹・max_cells 20000・max_terms 2000・max_refinements 20000)。"""
    return RateBudget(_Fraction(1, 10**9), 20000, 2000, 20000)


@_dataclass(frozen=True, slots=True)
class RateContext:
    run: _Ref
    now_ns: int
    observed_ns: int
    check_events: tuple
    fact_ancestors: _Mapping
    clock_source: _Ref | None


@_dataclass(frozen=True, slots=True)
class RateScope:
    status: str          # certified | incomplete | missing_spec | outside_evaluation | runtime_unverified
    method: _ContractRef | None
    reason: str | None
    conditions: tuple


@_dataclass(frozen=True, slots=True)
class Certificate:
    """sui.s4b.rate_certificate.1 (§3-10-5)。"""
    problem_key: str
    method: _ContractRef
    arithmetic: _ContractRef
    budget: RateBudget
    trace: tuple
    enclosures: object
    residuals: tuple

    def __post_init__(self):
        for name in ("trace", "enclosures", "residuals"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@_dataclass(frozen=True, slots=True)
class LikelihoodCertificate:
    value: RationalInterval
    kind: str        # mass | density
    measure: _ContractRef
    unit: str
    support: str     # zero | positive | unproved
    certificate: Certificate


@_dataclass(frozen=True, slots=True)
class CertifiedQuantity:
    status: str      # finite | positive_infinity | uncertified
    bounds: RationalInterval | None
    support: str     # zero | positive | signed | unproved
    log_bounds: RationalInterval | None
    reason: str | None
    certificate: Certificate | None


@_dataclass(frozen=True, slots=True, init=False)
class RateHistory:
    """factory (rate_entry.rate_history) だけが構築する不変ハンドル。"""
    model_ref: str
    context: RateContext
    fact_ids: tuple
    evidence_key: str
    _records: tuple
    _boot_ns: int

    def __init__(self, *_, **__):
        raise TypeError("RateHistory: use rate_history()")


@_dataclass(frozen=True, slots=True, init=False)
class RateBelief:
    """factory (rebuild_rate_belief) だけが構築する不変ハンドル。"""
    model_ref: str
    history: RateHistory
    evidence: LikelihoodCertificate
    _model: object
    _windows: tuple
    _measurements: tuple
    _time: _Fraction
    _problem: str

    def __init__(self, *_, **__):
        raise TypeError("RateBelief: use rebuild_rate_belief()")


@_dataclass(frozen=True, slots=True)
class RateBranch:
    key: str
    report: object
    probability: CertifiedQuantity
    child: RateBelief

    def __post_init__(self):
        object.__setattr__(self, "report", _rate_json(self.report))


@_dataclass(frozen=True, slots=True)
class RateEvaluation:
    candidates: tuple
    expected_cost: tuple
    information: tuple
    G: tuple
    J: tuple
    q_star: tuple
    cumulative: tuple    # K + 1 個の RationalInterval
    certificate: Certificate
    _source: object = None


@_dataclass(frozen=True, slots=True)
class CertifiedChoice:
    index: int           # 0 始まり
    choice: str
    u: _Fraction
    previous: RationalInterval
    current: RationalInterval
    certificate: Certificate | None = None


# --- 数学の入口 (§3-10-4)。中身は区切り 1〜3 -----------------------------------

def fixed_likelihood(model, history, *, theta, budget) -> LikelihoodCertificate:
    """Unnormalized column forward likelihood, with rational Poisson remainders.

    Finite counts use an augmented (state, saturated count) generator. Exact
    arrivals use Q - Lambda between arrivals and diagonal arrival operators.
    Neither operator's columns are renormalized. Unobserved arrivals disappear
    by marginalization, leaving Q alone outside declared active windows.
    """
    from .rate_model import RateModel
    from .rate_entry import _fixed_events
    if not isinstance(model, RateModel) or not isinstance(history, RateHistory):
        raise RateInputError("schema", "RateModel and factory RateHistory required")
    if history.model_ref != model.ref:
        raise RateInputError("shape", "history belongs to another model", "history.model_ref")
    if not isinstance(budget, RateBudget):
        raise RateInputError("invalid_budget", "RateBudget required", "budget")
    d = _json.loads(model.declaration)
    values = _theta(d, theta)
    if not any(c == {"name": "sui.s4b.rate_fixed_mmpp", "version": "1"}
               for c in d["certificate_capabilities"]):
        raise RateIncomplete("proof_unavailable", "fixed MMPP capability not available")
    if any(r["clock"]["name"] != "exact" for r in d["records"]):
        raise RateIncomplete("latent_clock", "tick arrival times require a joint clock integral")
    processes = {p["id"]: p for p in d["processes"]}
    state = next(p for p in processes.values() if p["family"]["name"] == "finite-ctmc")
    n = len(model.states)
    if n > budget.max_cells: raise RateIncomplete("budget", "state space exceeds max_cells")
    def expr(e):
        return _Fraction(*e["value"]) if e["kind"] == "constant" else values[e["variable"]] * _Fraction(*e["coefficient"])
    generators = {}
    rates = {}
    for mode, matrix in state["params"]["off_diagonal"].items():
        q = [[expr(e) for e in row] for row in matrix]
        for j in range(n): q[j][j] = -sum(q[i][j] for i in range(n) if i != j)
        generators[mode] = q
    for process in processes.values():
        if process["family"]["name"] == "marked-arrival":
            rates[process["id"]] = {m: tuple(expr(e) for e in row) for m, row in process["params"]["rates"].items()}
    windows, arrivals, reports, horizon = _fixed_events(d, history)
    # Past the last likelihood factor, 1^T exp(Q t)=1^T exactly. Marginalize
    # that unobserved terminal state interval analytically, including host
    # delivery delay. The last *covered* no-arrival interval is retained.
    horizon = max([w["end"] for w in windows] + [t for t, _, _ in arrivals] +
                  [t for t, report in reports if report["outcome"] is not None] + [_Fraction(0)])
    # Events are kept on the declared physical axis, not the receipt axis.
    boundaries = { _Fraction(0), horizon }
    boundaries.update(t for w in windows for t in (w["start"], w["end"]))
    boundaries.update(t for t, _, _ in arrivals)
    boundaries.update(t for t, _ in reports)
    calendar = [(_Fraction(*c["time"]), c["mode"]) for c in d["controls"]["calendar"] if _Fraction(*c["time"]) <= horizon]
    boundaries.update(t for t, _ in calendar)
    times = sorted(t for t in boundaries if 0 <= t <= horizon)
    mode = state["params"]["initial_mode"]
    vector = tuple(_Fraction(*v) for v in d["state_space"]["initial"])
    error = _Fraction(0)
    source_errors = {"series": _Fraction(0), "tail": _Fraction(0)}
    trace = []
    enclosures = []
    work = _SeriesWork(budget, trace)
    # A local remainder can be magnified by future density operators. Reserve
    # error against a bound on the whole remaining product, including modes.
    amplification = _Fraction(1)
    for _, pid, mark in arrivals:
        marks = processes[pid]["params"]["marks"]
        mark_probabilities = tuple(_Fraction(*p) for p in marks["probabilities"][marks["labels"].index(mark)]) if mark is not None else (_Fraction(1),) * n
        norm = max(v * mark_probabilities[s] for row in rates[pid].values() for s, v in enumerate(row))
        amplification *= max(_Fraction(1), norm)
    work.local_tolerance = budget.tolerance / (4 * max(1, len(times) - 1) * amplification)
    active_counts = ()
    count_records = {w["record"]: w for w in windows if w["kind"] == "count"}
    possible = tuple(v > 0 for v in vector)

    def rescale(norm):
        nonlocal error
        error *= norm
        for key in source_errors: source_errors[key] *= norm

    def start_counts(t):
        nonlocal vector, active_counts, possible
        starting = [w for w in windows if w["kind"] == "count" and w["start"] == t]
        for w in starting:
            size = len(vector) * (w["cap"] + 1)
            if size > budget.max_cells: raise RateIncomplete("budget", "count state space exceeds max_cells")
            vector = vector + (_Fraction(0),) * (size - len(vector))
            possible = possible + (False,) * (size - len(possible))
            active_counts += (w["record"],)

    def count_strides():
        strides, size = {}, n
        for rid in active_counts:
            strides[rid] = size
            size *= count_records[rid]["cap"] + 1
        return strides

    def finish_counts(t):
        nonlocal vector, active_counts, possible
        # Project reports before starting a new left-open window at this time.
        ending = [rid for rid in active_counts if count_records[rid]["end"] == t]
        for rid in ending:
            w, strides = count_records[rid], count_strides()
            stride, bins = strides[rid], count_records[rid]["cap"] + 1
            target = w["count"]
            projected = [_Fraction(0)] * (len(vector) // bins)
            reachable = [False] * len(projected)
            for i, v in enumerate(vector):
                digit = (i // stride) % bins
                if digit == target:
                    dest = i % stride + (i // (stride * bins)) * stride
                    projected[dest] += v
                    reachable[dest] |= possible[i]
            vector = tuple(projected)
            possible = tuple(reachable)
            active_counts = tuple(item for item in active_counts if item != rid)
            _trace(trace, "aggregate", dimension="count:" + rid)

    start_counts(_Fraction(0))
    for left, right in zip(times, times[1:]):
        for t, changed in calendar:
            if t == left: mode = changed
        q = generators[mode]
        active_exact = [w for w in windows if w["kind"] == "exact" and w["start"] <= left < w["end"]]
        strides = count_strides()
        size = len(vector)
        # Sparse column generator avoids materializing a square count product.
        columns = []
        for j in range(size):
            s = j % n
            column = {j - s + i: q[i][s] for i in range(n) if i != s and q[i][s]}
            diagonal = q[s][s] - sum(rates[w["process"]][mode][s] for w in active_exact)
            for rid in active_counts:
                w = count_records[rid]
                stride = strides[rid]
                if (j // stride) % (w["cap"] + 1) < w["cap"]:
                    arrival_rate = rates[w["process"]][mode][s]
                    diagonal -= arrival_rate
                    column[j + stride] = column.get(j + stride, _Fraction(0)) + arrival_rate
                # At saturation the arrival is marginalized; Q still runs.
            column[j] = diagonal
            columns.append(column)
        if right > left:
            reachable = set(i for i, flag in enumerate(possible) if flag)
            pending = list(reachable)
            while pending:
                j = pending.pop()
                for i, v in columns[j].items():
                    if i != j and v > 0 and i not in reachable:
                        reachable.add(i)
                        pending.append(i)
            possible = tuple(i in reachable for i in range(size))
        vector, series_error, tail_error, omega, terms = work.propagate(columns, vector, right - left)
        source_errors["series"] += series_error
        source_errors["tail"] += tail_error
        error += series_error + tail_error
        enclosures.append({"start": _pair(left), "end": _pair(right), "omega": _pair(omega),
                           "mode": mode, "terms": terms, "dimension": size})
        for event_time, pid, mark in arrivals:
            if event_time != right: continue
            factor = list(rates[pid][mode])
            marks = processes[pid]["params"]["marks"]
            if mark is not None:
                probabilities = marks["probabilities"][marks["labels"].index(mark)]
                factor = [v * _Fraction(*p) for v, p in zip(factor, probabilities)]
            norm = max(factor)
            vector = tuple(v * factor[i % n] for i, v in enumerate(vector))
            possible = tuple(flag and factor[i % n] > 0 for i, flag in enumerate(possible))
            rescale(norm)
            _trace(trace, "analytic", dimension="arrival:" + pid)
        finish_counts(right)
        for event_time, report in reports:
            if event_time != right or report["outcome"] is None: continue
            probe = processes[report["probe"]]
            labels = probe["params"]["labels"]
            probability = values[probe["params"]["probability_variable"]][labels.index(report["outcome"])]
            vector = tuple(v * probability for v in vector)
            possible = tuple(flag and probability > 0 for flag in possible)
            rescale(probability)
            _trace(trace, "analytic", dimension="probe:" + probe["id"])
        start_counts(right)
    lower = sum(vector)
    if not any(possible):
        # Reachability proved that every physical path is impossible. A loose
        # scalar remainder alone is never used to assert this structural zero.
        error = _Fraction(0)
        source_errors = {source: _Fraction(0) for source in source_errors}
        _trace(trace, "analytic", dimension="structural_zero")
    upper = lower + error
    density = d["measure"]["family"]["name"] == "marked-arrival-density"
    if not density: upper = min(_Fraction(1), upper)
    if upper - lower > budget.tolerance:
        raise RateIncomplete("accuracy", "propagated likelihood enclosure exceeds tolerance")
    value = RationalInterval(lower, upper)
    support = "zero" if upper == 0 else "positive" if lower > 0 else "unproved"
    unit = d["units"]["time"]["name"] + "^-" + str(len(arrivals)) if density and arrivals else "1"
    _trace(trace, "aggregate", dimension="likelihood")
    key = {"model": model.ref, "history": history.evidence_key,
           "theta": {vid: [_pair(v) for v in val] if isinstance(val, tuple) else _pair(val) for vid, val in values.items()},
           "method": "sui.s4b.rate_fixed_mmpp/1"}
    problem_key = "sha256:" + _hashlib.sha256(_json.dumps(key, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    residuals = tuple({"quantity": "likelihood", "candidate": None, "source": source, "upper": _pair(bound)}
                      for source, bound in (*source_errors.items(), ("rounding", _Fraction(0))))
    certificate = Certificate(problem_key, _ContractRef("sui.s4b.rate_fixed_mmpp", "1"),
                              _ContractRef("rational-series", "1"), budget, tuple(trace),
                              {"intervals": enclosures, "value": {"lower": _pair(lower), "upper": _pair(upper)},
                               "unit": unit, "kind": "density" if density else "mass"}, residuals)
    return LikelihoodCertificate(value, "density" if density else "mass", _ContractRef(**d["measure"]["family"]), unit, support, certificate)


def _freeze(value):
    if isinstance(value, _Mapping):
        return _MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)): return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, _Fraction)): return value
    raise RateInputError("schema", "certificate/context requires immutable JSON values")


def _pair(value):
    return [value.numerator, value.denominator]


def _trace(trace, operation, *, cell=None, dimension=None, terms=None, cutoff=None):
    trace.append({"index": len(trace), "operation": operation, "cell": cell,
                  "dimension": dimension, "terms": terms, "cutoff": cutoff})


def _theta(d, theta):
    variables = {v["id"]: v for v in d["variables"]}
    laws = [v for v in variables.values() if v["role"] == "law"]
    if not isinstance(theta, _Mapping) or set(theta) != {v["id"] for v in laws}:
        raise RateInputError("shape", "theta must specify every law exactly once", "theta")
    result = {}
    for variable in variables.values():
        ident, domain = variable["id"], variable["domain"]
        if variable["role"] == "law":
            if variable["scope"] != "model":
                raise RateIncomplete("rate_prior_scope", "fixed theta has no scoped law instances", "variables." + ident)
            value = theta[ident]
        elif variable["prior"] is not None:
            if variable["prior"]["name"] != "point":
                raise RateIncomplete("rate_prior_scope", "random auxiliary variable not fixed by theta")
            raw = variable["prior"]["params"]["value"]
            value = tuple(_Fraction(*v) for v in raw) if domain["kind"] == "simplex" else _Fraction(*raw)
        else: continue
        if domain["kind"] == "simplex":
            if not isinstance(value, tuple) or len(value) != len(domain["labels"]) or any(not isinstance(v, _Fraction) for v in value):
                raise RateInputError("shape", "simplex theta requires a Fraction tuple in label order", "theta." + ident)
            if any(v < 0 for v in value): raise RateInputError("unit", "theta outside simplex", "theta." + ident)
            if sum(value) != 1: raise RateInputError("normalization", "theta simplex sum", "theta." + ident)
        else:
            if not isinstance(value, _Fraction): raise RateInputError("schema", "theta scalar requires Fraction", "theta." + ident)
            if value < 0 or domain["kind"] == "positive-real" and value == 0:
                raise RateInputError("unit", "theta outside support", "theta." + ident)
        prior = variable["prior"]
        if prior is not None and prior["name"] == "point":
            raw = prior["params"]["value"]
            point = tuple(_Fraction(*v) for v in raw) if domain["kind"] == "simplex" else _Fraction(*raw)
            if value != point: raise RateInputError("unit", "theta differs from point support", "theta." + ident)
        result[ident] = value
    return result


class _SeriesWork:
    """Exact uniformization with separate exponential-series and Poisson tails.

    For x>=0, e^x lies between its positive Taylor polynomial S and
    S + next_term/(1-x/(k+2)). Inverting that interval gives e^-x.
    P=I+G/Omega is nonnegative and column-substochastic, so its omitted
    Poisson powers have L1 norm at most the Poisson tail times input mass.
    All propagated approximations are lower vectors; a scalar L1 remainder
    follows them through substochastic transitions and observation norms.
    """
    def __init__(self, budget, trace):
        self.budget, self.trace, self.terms, self.refinements = budget, trace, 0, 0

    def propagate(self, columns, vector, duration):
        omega = max(-column.get(j, _Fraction(0)) for j, column in enumerate(columns))
        if omega == 0 or duration == 0 or not any(vector):
            _trace(self.trace, "analytic", dimension="uniformization", terms=0, cutoff=_pair(omega))
            return vector, _Fraction(0), _Fraction(0), omega, 0
        # Split large x before the positive exponential series. Each substep
        # has x<=1; this is exact composition of the same constant generator.
        x = omega * duration
        pieces = max(1, (x.numerator + x.denominator - 1) // x.denominator)
        if pieces + self.refinements > self.budget.max_refinements:
            raise RateIncomplete("budget", "uniformization time subdivisions exceed max_refinements")
        self.refinements += pieces
        if pieces > 1: _trace(self.trace, "split", dimension="time", cutoff=_pair(duration / pieces))
        p = tuple({i: value / omega + (1 if i == j else 0) for i, value in column.items()
                   if value / omega + (1 if i == j else 0)} for j, column in enumerate(columns))
        result, series_total, tail_total = vector, _Fraction(0), _Fraction(0)
        start_terms = self.terms
        # Leave ample room for subsequent arrival norms. The caller may set a
        # smaller local tolerance before work starts, without changing budget.
        tolerance = self.local_tolerance / pieces if hasattr(self, "local_tolerance") else self.budget.tolerance / (16 * pieces)
        x /= pieces
        for _ in range(pieces):
            mass = sum(result)
            term = total = _Fraction(1)
            power = result
            accumulation = list(result)
            k = 0
            while True:
                self.terms += 1
                if self.terms > self.budget.max_terms:
                    raise RateIncomplete("budget", "uniformization series exceeds max_terms")
                next_term = term * x / (k + 1)
                remainder = next_term / (1 - x / (k + 2))
                exp_lower, exp_upper = 1 / (total + remainder), 1 / total
                series = (exp_upper - exp_lower) * total * mass
                tail = remainder * exp_upper * mass
                if series + tail <= tolerance: break
                following = [_Fraction(0)] * len(power)
                for j, v in enumerate(power):
                    if v:
                        for i, probability in p[j].items(): following[i] += probability * v
                power = tuple(following)
                k += 1
                term = next_term
                total += term
                for i, v in enumerate(power): accumulation[i] += term * v
            result = tuple(exp_lower * v for v in accumulation)
            series_total += series
            tail_total += tail
            _trace(self.trace, "series", dimension="uniformization", terms=k + 1, cutoff=_pair(x))
            _trace(self.trace, "tail", dimension="poisson", terms=k + 1, cutoff=_pair(tail))
        return result, series_total, tail_total, omega, self.terms - start_terms


def rebuild_rate_belief(model, reading, *, context, budget) -> RateBelief:
    """Integrate the joint continuous prior against the original record kernel.

    The C1 one-way path is eliminated symbolically. Its exponential-polynomial
    kernel is retained, including signed complements for saturated reports;
    neither state/rate factorization nor a mean-rate transition is used.
    """
    from .rate_entry import rate_history, _fixed_events
    _rate_budget(budget)
    history = rate_history(model, reading, context=context)
    cfg = _c1_config(model)
    windows, arrivals, reports, horizon = _fixed_events(cfg, history)
    if arrivals:
        raise RateIncomplete("history_scope", "C1 observes window counts, not exact arrivals")
    if any(w["kind"] != "count" for w in windows):
        raise RateIncomplete("history_scope", "C1 requires finite count reports")
    root = cfg["_root"]
    if len(windows) > 2 or len(reports) > 2:
        raise RateIncomplete("history_scope", "C1 certifies one root and one completion")
    if reports and not any(w["record"] == root["id"] for w in windows):
        raise RateIncomplete("history_scope", "completion requires its root report")
    if any(w["record"] == cfg["_read"]["id"] for w in windows) and any(
            r[0] > cfg["_duration"] and r[1]["probe"] is None for r in reports):
        raise RateIncomplete("history_scope", "two alternative completions in one history")
    measurements = tuple(r[1]["outcome"] for r in reports if r[1]["outcome"] is not None)
    # The inference horizon is a physical position, not the host creation time.
    return _c1_belief(model, history, tuple(_freeze(w) for w in windows),
                      measurements, horizon, history.evidence_key, budget)


def state_marginal(belief, *, targets, budget) -> tuple:
    """Joint marginal at fixed physical positions, in the caller's axis order."""
    from itertools import product
    cfg = _c1_checked(belief, budget)
    if not isinstance(targets, tuple) or not targets:
        raise RateInputError("shape", "nonempty tuple of FixedLabel targets required", "targets")
    times = tuple(_c1_label(cfg, t) for t in targets)
    if 2**len(times) > budget.max_cells:
        raise RateIncomplete("budget", "joint state output exceeds max_cells")
    kernels = _c1_paths(cfg, belief._windows, times, budget)
    raw = tuple(kernels.get(tuple(cfg["state_space"]["states"].index(s) for s in states), ())
                for states in product(belief._model.states, repeat=len(times)))
    intervals, cert = _c1_integrate(cfg, raw, budget, belief._problem,
                                  "state_marginal", normalize=True)
    return tuple((states, _c1_quantity(interval, cert, not kernel)) for states, interval, kernel in
                 zip(product(belief._model.states, repeat=len(times)), intervals, raw))


def parameter_moment(belief, *, powers, budget) -> CertifiedQuantity:
    """Joint expectation of scalar and labelled simplex component powers.

    Scalar entries are (law ID, power), simplex entries (law ID, label, power).
    Entries follow variable declaration order and then simplex label order;
    repeated entries and zero powers are noncanonical. The Dirichlet integral
    includes every requested component in one monomial, not marginal moments.
    """
    cfg = _c1_checked(belief, budget)
    if not isinstance(powers, tuple):
        raise RateInputError("schema", "powers must be a tuple", "powers")
    laws = {v["id"]: (index, v) for index, v in enumerate(cfg["variables"]) if v["role"] == "law"}
    indices, power = [], 0
    component_powers = [0] * len(cfg["_probability"]["domain"]["labels"])
    for item in powers:
        if (not isinstance(item, tuple) or len(item) not in (2, 3) or
                not isinstance(item[0], str) or item[0] not in laws):
            raise RateInputError("shape", "declared law ID and correctly shaped power entry required", "powers")
        variable_index, variable = laws[item[0]]
        if variable["domain"]["kind"] == "simplex":
            labels = variable["domain"]["labels"]
            if len(item) != 3 or not isinstance(item[1], str) or item[1] not in labels:
                raise RateInputError("shape", "simplex power requires a declared component label", "powers")
            component_index = labels.index(item[1])
            indices.append((variable_index, component_index))
        else:
            if len(item) != 2:
                raise RateInputError("shape", "scalar power does not take a component label", "powers")
            indices.append((variable_index, -1))
        exponent = item[-1]
        if type(exponent) is not int or exponent < 0:
            raise RateInputError("shape", "nonnegative integer power required (not bool)", "powers")
        if exponent == 0:
            raise RateInputError("noncanonical", "zero powers must be omitted", "powers")
        if variable["domain"]["kind"] == "simplex":
            component_powers[component_index] = exponent
        else:
            power = exponent
    if indices != sorted(set(indices)):
        raise RateInputError("noncanonical", "powers must follow variable/label declaration order without duplicates", "powers")
    if not powers:
        return _c1_exact_quantity(_Fraction(1), belief, budget, "parameter_moment")
    if sum(component_powers) + len(belief._measurements) > budget.max_terms:
        raise RateIncomplete("budget", "Dirichlet monomial degree exceeds max_terms")
    kernel = _c1_total(_c1_paths(cfg, belief._windows, (), budget).values())
    probe_mass = _c1_probe_mass(cfg, belief._measurements)
    probe_weighted_mass = _c1_probe_mass(cfg, belief._measurements, powers=component_powers)
    denominator = _ep_scale(kernel, probe_mass)
    numerator = _ep_scale(kernel, probe_weighted_mass)
    problem = _c1_key(belief._problem, "parameter_moment", powers)
    intervals, cert = _c1_integrate(cfg, (numerator,), budget, problem,
                                  "parameter_moment", normalize=True, power=power,
                                  denominator=denominator)
    trace = []
    _trace(trace, "analytic", dimension="dirichlet-monomial:" + cfg["_probability"]["id"],
           terms=sum(component_powers) + len(belief._measurements))
    trace.extend({**step, "index": index + 1} for index, step in enumerate(cert.trace))
    cert = Certificate(cert.problem_key, cert.method, cert.arithmetic, cert.budget, tuple(trace),
                       {**cert.enclosures, "parameter_powers": powers,
                        "probe_record_integral": _pair(probe_mass),
                        "probe_monomial_integral": _pair(probe_weighted_mass)}, cert.residuals)
    return _c1_quantity(intervals[0], cert)


def rate_branches(belief, *, choice, budget) -> tuple:
    """Finite reports, with all internal paths summed and no synthetic Records."""
    cfg = _c1_checked(belief, budget)
    if not isinstance(choice, str) or choice not in belief._model.choices:
        raise RateInputError("unknown_candidate", "choice is not declared", "choice")
    if len(belief._windows) != 1 or belief._measurements or belief._time != cfg["_duration"]:
        raise RateIncomplete("depth_scope", "C1 branches start at its first completed count window")
    c = next(c for c in cfg["controls"]["choices"] if c["id"] == choice)
    spec = next(r for r in cfg["records"] if r["id"] == c["observation_records"][0])
    counted = spec["kernel"]["name"] == "saturating-count"
    root_kernel = _c1_total(_c1_paths(cfg, belief._windows, (), budget).values())
    duration, unit_ns = cfg["_duration"], cfg["_unit_seconds"] * 10**9
    def reading(t):
        ns = t * unit_ns
        if ns.denominator != 1:
            raise RateIncomplete("history_scope", "completion position is not an integer ns reading")
        return belief.history._boot_ns + int(ns)
    branches = []
    for index, cell in enumerate(spec["alphabet"]["values"]):
        windows = belief._windows
        if counted:
            windows += (_freeze({"record": spec["id"], "process": cfg["_arrival"]["id"],
                                  "start": duration, "end": 2 * duration, "kind": "count",
                                  "cap": spec["kernel"]["params"]["cap"],
                                  "count": cell["arrival_count"]["value"]}),)
        measurements = belief._measurements + ((cell["outcome"],) if counted else ())
        report = _rate_json({"channel": spec["id"], "experiment": spec["experiment"],
                          "window_start_ns": reading(duration) if counted else None,
                          "window_end_ns": reading(2 * duration) if counted else None,
                          "arrival_count": cell["arrival_count"], "outcome": cell["outcome"],
                          "completion_ns": reading(2 * duration)})
        key = _c1_key(belief._problem, "branch", (choice, index, report))
        child = _c1_belief(belief._model, belief.history, windows, measurements,
                           2 * duration, key, budget)
        if counted:
            kernel = _c1_total(_c1_paths(cfg, windows, (), budget).values())
            mass = _c1_probe_mass(cfg, measurements) / _c1_probe_mass(cfg, belief._measurements)
            intervals, cert = _c1_integrate(cfg, (_ep_scale(kernel, mass),), budget,
                                          key, "branch_probability", normalize=True,
                                          denominator=root_kernel)
            probability = _c1_quantity(intervals[0], cert)
        else:
            # This equality follows from marginalizing the unobserved arrival
            # and the stochastic CTMC, not from conditioning on count zero.
            probability = _c1_exact_quantity(_Fraction(1), belief, budget, "branch_probability")
        branches.append(RateBranch(key, report, probability, child))
    return tuple(branches)


def natural_change(belief, *, start, end, budget) -> _Mapping:
    """Three distinct path observables; a C1 path has at most one natural jump."""
    cfg = _c1_checked(belief, budget)
    try:
        left, right = _c1_label(cfg, start), _c1_label(cfg, end)
    except RateIncomplete as exc:
        return _MappingProxyType({name: CertifiedQuantity("uncertified", None, "unproved", None,
                                                         exc.reason, None) for name in _CHANGE_KEYS})
    if left > right:
        raise RateInputError("unit", "end precedes start", "end")
    if left == right:
        quantity = _c1_exact_quantity(_Fraction(0), belief, budget, "natural_change")
    else:
        kernels = _c1_paths(cfg, belief._windows, (left, right), budget)
        kernel = kernels.get((0, 1), ())
        intervals, cert = _c1_integrate(cfg, (kernel,), budget, belief._problem,
                                      "natural_change", normalize=True,
                                      denominator=_c1_total(kernels.values()))
        quantity = _c1_quantity(intervals[0], cert, not kernel)
    return _MappingProxyType({name: quantity for name in _CHANGE_KEYS})


_CHANGE_KEYS = ("jump_probability", "expected_jump_count", "endpoint_change_probability")


class _RateJSON(dict):
    """Immutable JSON object that the standard JSON encoder can serialize."""
    __slots__ = ()

    def _immutable(self, *args, **kwargs):
        raise TypeError("immutable rate report")

    __init__ = __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


def _rate_json(value):
    if isinstance(value, _Mapping):
        result = dict.__new__(_RateJSON)
        dict.__init__(result, ((k, _rate_json(v)) for k, v in value.items()))
        return result
    if isinstance(value, (list, tuple)): return tuple(_rate_json(v) for v in value)
    if value is None or isinstance(value, (str, bool, int)): return value
    raise RateInputError("schema", "report requires JSON values")


def _rate_budget(budget):
    if not isinstance(budget, RateBudget):
        raise RateInputError("invalid_budget", "RateBudget required", "budget")


def _c1_key(parent, operation, inputs):
    from .rate_entry import _plain
    def encode(value):
        if isinstance(value, _Fraction): return _pair(value)
        if isinstance(value, _Mapping): return {k: encode(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)): return [encode(v) for v in value]
        return value
    value = {"parent": parent, "operation": operation, "inputs": encode(_plain(inputs))}
    return "sha256:" + _hashlib.sha256(_json.dumps(value, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()


def _c1_config(model):
    """Check C1's physical/graph conditions without depending on fixture IDs."""
    from .rate_model import RateModel
    if not isinstance(model, RateModel):
        raise RateInputError("schema", "RateModel required", "model")
    d = _json.loads(model.declaration)
    def scope(condition, reason, detail):
        if not condition: raise RateIncomplete(reason, detail)
    scope({"name": "sui.s4b.rate_c1", "version": "1"} in d["certificate_capabilities"],
          "proof_unavailable", "C1 capability is unavailable")
    scope(all(r["clock"]["name"] == "exact" for r in d["records"]),
          "latent_clock", "C1 has no latent clock integral")
    laws = [v for v in d["variables"] if v["role"] == "law"]
    rates = [v for v in laws if v["domain"]["kind"] == "positive-real" and v["prior"]["name"] == "gamma"]
    probes = [v for v in laws if v["domain"]["kind"] == "simplex" and v["prior"]["name"] == "dirichlet"]
    scope(len(laws) == 2 and len(rates) == len(probes) == 1 and all(v["scope"] == "model" for v in laws),
          "rate_prior_scope", "C1 requires one persistent shared rate and one shared simplex")
    rate, probability = rates[0], probes[0]
    families = {name: [p for p in d["processes"] if p["family"]["name"] == name]
                for name in ("finite-ctmc", "marked-arrival", "shared-probe", "fixed-completion")}
    scope(tuple(map(len, families.values())) == (1, 1, 1, 2) and len(d["processes"]) == 5,
          "history_scope", "C1 requires one state/arrival/probe process and two fixed completions")
    state, arrival, probe = (families[name][0] for name in ("finite-ctmc", "marked-arrival", "shared-probe"))
    scope(len(model.states) == 2 and d["state_space"]["initial"] == [[1, 1], [0, 1]],
          "rate_prior_scope", "C1 starts in its first of two states")
    sp = state["params"]
    scope(len(sp["modes"]) == 1 and not d["controls"]["calendar"],
          "history_scope", "C1 has one fixed activity and no impulses")
    mode = sp["initial_mode"]
    zero = {"kind": "constant", "value": [0, 1]}
    def scaled(coefficient):
        return {"kind": "scaled_variable", "variable": rate["id"], "coefficient": [coefficient, 1]}
    scope(sp["off_diagonal"][mode] == [[zero, zero], [scaled(1), zero]] and
          arrival["params"]["rates"][mode] == [scaled(1), scaled(2)] and arrival["params"]["marks"] is None,
          "rate_prior_scope", "C1's one-way jump and two arrival rates must share the same rate")
    scope(probe["params"]["probability_variable"] == probability["id"] and
          len(probe["params"]["labels"]) == 2,
          "rate_prior_scope", "C1 has a two-label state-independent shared probe")
    read_done = [p for p in families["fixed-completion"] if p["params"]["count_record"] is not None]
    wait_done = [p for p in families["fixed-completion"] if p["params"]["count_record"] is None]
    scope(len(read_done) == len(wait_done) == 1, "history_scope", "C1 requires read and unobserved wait")
    records = {r["id"]: r for r in d["records"]}
    root = [r for r in records.values() if r["generator"] == arrival["id"]]
    wait = [r for r in records.values() if r["generator"] == wait_done[0]["id"]]
    scope(len(root) == len(wait) == 1 and len(records) == 3,
          "history_scope", "C1 has one root, read and constant wait report")
    root, read, wait = root[0], records[read_done[0]["params"]["count_record"]], wait[0]
    duration = _Fraction(*read_done[0]["params"]["duration"])
    unit = _Fraction(*d["units"]["time"]["seconds"])
    scope(duration * unit == 1 and _Fraction(*wait_done[0]["params"]["duration"]) == duration,
          "history_scope", "C1's two completions have the same physical one-second duration")
    scope(rate["prior"]["params"]["shape"] == [2, 1] and
          _Fraction(*rate["prior"]["params"]["rate"]) == 2 * duration and
          probability["prior"]["params"]["alpha"] == [[1, 1], [1, 1]],
          "rate_prior_scope", "C1 requires its unit-pushed Gamma and Dirichlet prior")
    labels = probe["params"]["labels"]
    cells = [{"kind": "exact", "value": k} for k in range(3)] + [{"kind": "at_least", "value": 3}]
    for report, measured in ((root, False), (read, True)):
        scope(report["kernel"]["name"] == "saturating-count" and
              report["kernel"]["params"]["cap"] == 3 and
              report["kernel"]["params"]["arrival_process"] == arrival["id"] and
              report["probe"] == (probe["id"] if measured else None) and
              report["alphabet"]["values"] == [{"arrival_count": cell, "outcome": y}
                 for cell in cells for y in (labels if measured else [None])],
              "history_scope", "C1 retains all four count cells and both read measurements")
    scope(wait["kernel"]["name"] == "constant-report" and wait["probe"] is None and
          wait["alphabet"]["values"] == [{"arrival_count": None, "outcome": None}] and
          read_done[0]["params"]["probe"] == probe["id"],
          "history_scope", "wait must not observe counts or measurements")
    choices = d["controls"]["choices"]
    scope(len(choices) == 2 and {c["completion_process"] for c in choices} ==
          {read_done[0]["id"], wait_done[0]["id"]} and
          all(c["reservation"] == {"kind": "immediate"} and
              c["observation_records"] == [read["id"] if c["completion_process"] == read_done[0]["id"] else wait["id"]]
              for c in choices), "history_scope", "C1 requires its declared immediate read/wait controls")
    read_choice = next(c for c in choices if c["completion_process"] == read_done[0]["id"])
    expected = ((root["id"], _Fraction(0), duration, {"kind": "exogenous", "id": root["experiment"]}),
                (read["id"], duration, 2 * duration, {"kind": "choice", "id": read_choice["id"]}))
    scope(len(d["coverage"]["intervals"]) == 2 and all(any(
          w["record"] == rid and _Fraction(*w["start"]) == left and _Fraction(*w["end"]) == right and w["source"] == source
          for w in d["coverage"]["intervals"]) for rid, left, right, source in expected) and
          d["coverage"]["policy"]["name"] == "choice-gated-window",
          "history_scope", "C1 observes its root and choice-gated read window only")
    scope(d["measure"]["family"]["name"] == "finite-record-counting" and not d["measure"]["conditioning"],
          "history_scope", "C1 evidence uses unconditioned finite-record mass")
    positions = d["targets"]["state_positions"]
    scope(len(positions) == 2 and {p["record"] for p in positions} == {read["id"], wait["id"]} and
          all(_Fraction(*p["position"]["time"]) == 2 * duration and
              p["position"]["causal_stage"] == p["position"]["causal_position"] == 0 and p["side"] == "post"
              for p in positions), "history_scope", "C1 targets its fixed completion state")
    d.update(_rate=rate, _probability=probability, _arrival=arrival, _root=root, _read=read,
             _wait=wait, _duration=duration, _unit_seconds=unit)
    return d


def _c1_checked(belief, budget):
    _rate_budget(budget)
    if not isinstance(belief, RateBelief):
        raise RateInputError("schema", "factory RateBelief required", "belief")
    return _c1_config(belief._model)


def _c1_label(cfg, label):
    from .action_types import FixedLabel
    if not isinstance(label, FixedLabel):
        raise RateInputError("shape", "FixedLabel required", "targets")
    if label.time_s < 0:
        raise RateInputError("unit", "negative physical position", "targets")
    if label.causal_stage or label.causal_position or label.time_s > 2:
        raise RateIncomplete("history_scope", "position outside C1's fixed-activity two-window experiment")
    return label.time_s / cfg["_unit_seconds"]


def _ep(terms):
    """Canonical finite sum of c r^k exp(-d r), with exact cancellations."""
    result = {}
    for degree, decay, coefficient in terms:
        key = (degree, decay)
        result[key] = result.get(key, _Fraction(0)) + coefficient
    return tuple((k, d, c) for (k, d), c in sorted(result.items()) if c)


def _ep_scale(kernel, scale):
    return _ep((k, d, c * scale) for k, d, c in kernel)


def _ep_product(left, right):
    return _ep((k + l, d + e, c * v) for k, d, c in left for l, e, v in right)


def _c1_total(kernels):
    return _ep(term for kernel in kernels for term in kernel)


def _c1_transition(duration, count=None, threshold=None):
    """COLUMN kernel after integrating the time of the sole possible jump.

    Given a jump at u, the arrival exposure is r(2t-u); integrating
    (2t-u)^n over u in [0,t] gives ((2t)^(n+1)-t^(n+1))/(n+1).
    This computes coefficients from the physical duration, not reference values.
    """
    from math import factorial
    one = ((0, _Fraction(0), _Fraction(1)),)
    survival = ((0, duration, _Fraction(1)),)
    unobserved = ((survival, ()), (_c1_total((one, _ep_scale(survival, -1))), one))
    if count is None and threshold is None: return unobserved
    if threshold is not None:
        exact = tuple(_c1_transition(duration, count=k) for k in range(threshold))
        return tuple(tuple(_c1_total((unobserved[i][j], *(_ep_scale(v[i][j], -1) for v in exact)))
                           for j in range(2)) for i in range(2))
    coefficient = duration**count / factorial(count)
    diagonal0 = _ep(((count, 2 * duration, coefficient),))
    diagonal1 = _ep_scale(diagonal0, 2**count)
    jump = _ep(((count + 1, 2 * duration,
                 ((2 * duration)**(count + 1) - duration**(count + 1)) / factorial(count + 1)),))
    return ((diagonal0, ()), (jump, diagonal1))


def _c1_paths(cfg, windows, labels, budget):
    """Sum hidden paths; split count windows without resetting their counter."""
    times = sorted({_Fraction(0), *(t for w in windows for t in (w["start"], w["end"])), *labels})
    if len(times) - 1 > budget.max_refinements:
        raise RateIncomplete("budget", "physical time subdivisions exceed max_refinements")
    vector = {((), 0, 0): ((0, _Fraction(0), _Fraction(1)),)}
    active = None
    for index, time in enumerate(times):
        ending = [w for w in windows if w["end"] == time]
        if ending:
            w = ending[0]
            vector = {(prefix, state, 0): kernel for (prefix, state, count), kernel in vector.items()
                      if count == w["count"]}
            active = None
        for position, label in enumerate(labels):
            if label == time:
                vector = {(prefix + ((position, state),), state, count): kernel
                          for (prefix, state, count), kernel in vector.items()}
        starting = [w for w in windows if w["start"] == time]
        if starting: active = starting[0]
        if index == len(times) - 1: break
        duration = times[index + 1] - time
        cap = active["cap"] if active else 0
        transitions = {k: _c1_transition(duration, count=k) for k in range(cap)}
        overflow = {k: _c1_transition(duration, threshold=cap - k) for k in range(cap)}
        unobserved = _c1_transition(duration)
        following = {}
        for (prefix, state, count), kernel in vector.items():
            for next_count in (range(count, cap + 1) if active else (0,)):
                transition = (unobserved if not active or count == cap else
                              overflow[count] if next_count == cap else transitions[next_count - count])
                for endpoint in range(2):
                    contribution = _ep_product(kernel, transition[endpoint][state])
                    if not contribution: continue
                    key = (prefix, endpoint, next_count)
                    following[key] = _c1_total((following.get(key, ()), contribution))
        vector = following
        if len(vector) > budget.max_cells:
            raise RateIncomplete("budget", "joint state/count cells exceed max_cells")
    result = {}
    for (prefix, state, count), kernel in vector.items():
        key = tuple(v for _, v in sorted(prefix))
        result[key] = _c1_total((result.get(key, ()), kernel))
    return result


def _c1_probe_mass(cfg, measurements, *, powers=()):
    """Integrate the record likelihood times one Dirichlet monomial exactly."""
    alpha = [_Fraction(*v) for v in cfg["_probability"]["prior"]["params"]["alpha"]]
    labels = cfg["_probability"]["domain"]["labels"]
    mass = _Fraction(1)
    for y in measurements:
        index = labels.index(y)
        mass *= alpha[index] / sum(alpha)
        alpha[index] += 1
    total_power = sum(powers)
    # The numerator contains joint rising factorials for every component;
    # the common denominator uses their TOTAL degree.
    for index, exponent in enumerate(powers):
        for k in range(exponent): mass *= alpha[index] + k
    concentration = sum(alpha)
    for k in range(total_power): mass /= concentration + k
    return mass


def _c1_belief(model, history, windows, measurements, time, problem, budget):
    cfg = _c1_config(model)
    kernel = _c1_total(_c1_paths(cfg, windows, (), budget).values())
    kernel = _ep_scale(kernel, _c1_probe_mass(cfg, measurements))
    intervals, cert = _c1_integrate(cfg, (kernel,), budget, problem, "evidence")
    interval = intervals[0]
    if not kernel:
        raise RateModelFalsified("zero_evidence", "empty path support")
    if interval.lower <= 0:
        raise RateIncomplete("evidence_lower_bound", "positive evidence lower bound not established")
    evidence = LikelihoodCertificate(interval, "mass", _ContractRef(**cfg["measure"]["family"]),
                                     "1", "positive", cert)
    result = object.__new__(RateBelief)
    for name, value in (("model_ref", model.ref), ("history", history), ("evidence", evidence),
                        ("_model", model), ("_windows", windows), ("_measurements", measurements),
                        ("_time", time), ("_problem", problem)):
        object.__setattr__(result, name, value)
    return result


class _C1IntegralWork:
    """Compact Gamma integrals and certified prior tails, using only Fraction.

    Each rate cell has its prior mass times whole-cell kernel bounds. Analytic
    conjugate integrals of the one-way path tighten that enclosure. The
    unevaluated rate tail uses 0<=record mass<=1 (weighted for moments).
    """
    def __init__(self, budget):
        self.budget, self.trace, self.terms, self.cache = budget, [], 0, {}

    def negative_exp(self, x, epsilon):
        old = self.cache.get(x)
        if old is not None and old.upper - old.lower <= epsilon: return old
        term = total = _Fraction(1)
        k = 0
        while True:
            self.terms += 1
            if self.terms > self.budget.max_terms:
                raise RateIncomplete("budget", "Gamma/exponential series exceeds max_terms")
            following = term * x / (k + 1)
            if x < k + 2:
                remainder = following / (1 - x / (k + 2))
                interval = RationalInterval(1 / (total + remainder), 1 / total)
                if interval.upper - interval.lower <= epsilon: break
            k += 1
            term = following
            total += term
        self.cache[x] = interval
        _trace(self.trace, "series", dimension="exp(-rate*cutoff)", terms=k + 1, cutoff=_pair(x))
        return interval

    def gamma_term(self, shape, beta, degree, decay, cutoff, epsilon):
        from math import factorial
        n = shape + degree - 1
        if n + 1 > self.budget.max_terms:
            raise RateIncomplete("budget", "Gamma moment degree exceeds max_terms")
        rate = beta + decay
        x = rate * cutoff
        term = polynomial = _Fraction(1)
        for k in range(1, n + 1):
            term *= x / k
            polynomial += term
        full = beta**shape * factorial(n) / (factorial(shape - 1) * rate**(n + 1))
        exponential = self.negative_exp(x, epsilon / (full * polynomial))
        tail = RationalInterval(full * polynomial * exponential.lower, full * polynomial * exponential.upper)
        compact = RationalInterval(max(_Fraction(0), full - tail.upper), min(full, full - tail.lower))
        _trace(self.trace, "analytic", cell="0", dimension="gamma-cell", terms=n + 1, cutoff=_pair(cutoff))
        return compact, tail


def _c1_integrate(cfg, kernels, budget, parent, quantity, *, normalize=False, power=0, denominator=None):
    """Enclose the actual continuous-prior integral, then condition on Z_->0."""
    _rate_budget(budget)
    shape = int(_Fraction(*cfg["_rate"]["prior"]["params"]["shape"]))
    if shape + power > budget.max_terms:
        raise RateIncomplete("budget", "Gamma moment degree exceeds max_terms")
    beta = _Fraction(*cfg["_rate"]["prior"]["params"]["rate"])
    denominator = denominator if denominator is not None else _c1_total(kernels)
    # A moment has one numerator; its denominator is the original record mass.
    weighted = tuple(_ep((k + power, d, c) for k, d, c in kernel) for kernel in kernels)
    weights = sum(abs(c) for kernel in (*weighted, denominator) for _, _, c in kernel)
    from math import factorial
    def full_integral(kernel):
        return sum((c * beta**shape * factorial(shape + k - 1) /
                    (factorial(shape - 1) * (beta + d)**(shape + k)) for k, d, c in kernel), _Fraction(0))
    z = full_integral(denominator)
    if normalize and z <= 0:
        if z == 0: raise RateModelFalsified("zero_evidence", "analytic record integral is zero")
        raise RateNumericalRange("invalid_interval", "negative integral of a nonnegative record kernel")
    moment_bound = beta**(-power) * _Fraction(factorial(shape + power - 1), factorial(shape - 1))
    allocation = budget.tolerance * min(_Fraction(1), z)**2 / (256 * max(_Fraction(1), moment_bound))
    epsilon = allocation / max(_Fraction(1), weights)
    # e>=2 gives an exact rational preliminary tail bound. Select the compact
    # cell before evaluating its expensive series; do not spend terms on cells
    # already known to have an insufficient tail for conditioning.
    x = 1
    subdivisions = 0
    while True:
        polynomial = sum((_Fraction(x**k, factorial(k)) for k in range(shape + power)), _Fraction(0))
        if moment_bound * polynomial / 2**x <= allocation: break
        subdivisions += 1
        if subdivisions >= budget.max_refinements:
            raise RateIncomplete("budget", "prior tail cutoff exceeds max_refinements")
        x *= 2
    work = _C1IntegralWork(budget)
    for refinement in range(budget.max_refinements - subdivisions):
        cutoff = _Fraction(x * 2**refinement, 1) / beta
        compact_prior, tail_prior = work.gamma_term(shape, beta, 0, _Fraction(0), cutoff, epsilon)
        _, tail_moment = work.gamma_term(shape, beta, power, _Fraction(0), cutoff, epsilon)
        compact_values = []
        def integrate(kernel, tail, cell_bound):
            lower = upper = _Fraction(0)
            for degree, decay, coefficient in kernel:
                compact, _ = work.gamma_term(shape, beta, degree, decay, cutoff, epsilon)
                if coefficient > 0:
                    lower += coefficient * compact.lower
                    upper += coefficient * compact.upper
                else:
                    lower += coefficient * compact.upper
                    upper += coefficient * compact.lower
            if not kernel:
                compact = RationalInterval(_Fraction(0), _Fraction(0))
            else:
                # Intersect the analytic enclosure with prior cell mass times
                # the kernel bound valid on the ENTIRE cell, not point values.
                compact = RationalInterval(max(_Fraction(0), lower), min(cell_bound, max(_Fraction(0), upper)))
            compact_values.append(compact)
            if not kernel: return compact
            return RationalInterval(compact.lower, compact.upper + tail.upper)
        evidence = integrate(denominator, tail_prior, compact_prior.upper)
        raw = tuple(integrate(k, tail_moment, compact_prior.upper * cutoff**power) for k in weighted)
        if normalize and evidence.lower <= 0:
            epsilon /= 2
            continue
        intervals = tuple(RationalInterval(v.lower / evidence.upper, v.upper / evidence.lower)
                          if normalize else v for v in raw)
        if power == 0:
            intervals = tuple(RationalInterval(max(_Fraction(0), v.lower), min(_Fraction(1), v.upper)) for v in intervals)
        if all(v.upper - v.lower <= budget.tolerance for v in intervals): break
        # The raw precision must survive division by small evidence and large
        # moments. This allocation uses the enclosed denominator, never E[r].
        if normalize and evidence.lower > 0:
            epsilon = min(epsilon / 2, budget.tolerance * evidence.lower**2 /
                          (64 * max(_Fraction(1), weights) * max(_Fraction(1), *(v.upper for v in raw))))
        else: epsilon /= 2
    else:
        reason = "evidence_lower_bound" if normalize and evidence.lower <= 0 else "accuracy"
        raise RateIncomplete(reason, "continuous rate enclosure did not reach its requested width")
    _trace(work.trace, "tail", dimension="prior-rate", cutoff=_pair(cutoff))
    _trace(work.trace, "aggregate", dimension=quantity)
    key = _c1_key(parent, quantity, (kernels, denominator, power))
    residuals = tuple({"quantity": quantity, "candidate": None, "source": source, "upper": _pair(value)}
                      for source, value in (("series", epsilon * weights), ("tail", tail_moment.upper),
                                            ("quadrature", _Fraction(0)),
                                            ("conditioning", max(v.upper - v.lower for v in intervals) if normalize else _Fraction(0)),
                                            ("rounding", _Fraction(0))))
    cert = Certificate(key, _ContractRef("sui.s4b.rate_c1", "1"), _ContractRef("rational-series", "1"),
                       budget, tuple(work.trace),
                       {"rate_cells": [{"id": "0", "lower": _pair(_Fraction(0)), "upper": _pair(cutoff),
                         "prior_mass": {"lower": _pair(compact_prior.lower), "upper": _pair(compact_prior.upper)},
                         "record_kernel_bounds": [[0, 1], [1, 1]],
                         "moment_kernel_bounds": [[0, 1], _pair(cutoff**power)],
                         "analytic_integrals": [{"lower": _pair(v.lower), "upper": _pair(v.upper)} for v in compact_values]}],
                        "prior_tail": {"lower": _pair(tail_prior.lower), "upper": _pair(tail_prior.upper)},
                        "evidence": {"lower": _pair(evidence.lower), "upper": _pair(evidence.upper)},
                        "values": [{"lower": _pair(v.lower), "upper": _pair(v.upper)} for v in intervals]}, residuals)
    return intervals, cert


def _c1_quantity(interval, certificate, structural_zero=False):
    return CertifiedQuantity("finite", interval, "zero" if structural_zero else "positive",
                             None, None, certificate)


def _c1_exact_quantity(value, belief, budget, quantity):
    trace = []
    _trace(trace, "analytic", dimension=quantity)
    cert = Certificate(_c1_key(belief._problem, quantity, value), _ContractRef("sui.s4b.rate_c1", "1"),
                       _ContractRef("rational-series", "1"), budget, tuple(trace),
                       {"value": _pair(value)}, ({"quantity": quantity, "candidate": None,
                                                "source": "rounding", "upper": [0, 1]},))
    return _c1_quantity(RationalInterval(value, value), cert, value == 0)


def evaluate_rate(view, candidates, resolved, *, budget) -> RateEvaluation:
    return _evaluate_rate(view, candidates, resolved, budget)[0]


def certify_choice(evaluation, *, u) -> CertifiedChoice:
    u = _choice_u(u)
    if not isinstance(evaluation, RateEvaluation):
        raise RateInputError("schema", "RateEvaluation required")
    _check_rate_evaluation(evaluation)
    engine = None
    if evaluation._source is not None:
        view, candidates, resolved = evaluation._source
        rebuilt, engine = _evaluate_rate(view, candidates, resolved, evaluation.certificate.budget)
        if rebuilt != evaluation:
            raise RateIncomplete("proof_unavailable", "evaluation differs from version-fixed recomputation")
    else:
        _check_algebraic_evaluation(evaluation)
    return _certify_computed_choice(evaluation, engine, u=u)


def _choice_u(u):
    from math import isfinite
    if (isinstance(u, bool) or not isinstance(u, (int, float, _Fraction)) or
            isinstance(u, float) and not isfinite(u)):
        raise RateInputError("invalid_u", "u must be an exact number in [0,1)", "u")
    u = _Fraction(u)
    if not 0 <= u < 1:
        raise RateInputError("invalid_u", "u must be in [0,1)", "u")
    return u


def _certify_computed_choice(evaluation, engine, *, u):
    """Select from a just-computed evaluation, retaining its live refinement.

    Public supplied evaluations still go through certify_choice's complete
    recomputation. Persistence uses this only with a fresh version-fixed run.
    """
    u = _choice_u(u)
    _check_rate_evaluation(evaluation)
    while True:
        for index, candidate in enumerate(evaluation.candidates):
            previous, current = evaluation.cumulative[index:index + 2]
            if previous.upper <= u < current.lower:
                trace = [dict(step) for step in evaluation.certificate.trace]
                _trace(trace, "select", dimension=candidate)
                enclosures = dict(evaluation.certificate.enclosures) if isinstance(
                    evaluation.certificate.enclosures, _Mapping) else {}
                enclosures["selection"] = {"index": index, "choice": candidate, "u": _pair(u),
                                            "previous": _interval_json(previous), "current": _interval_json(current)}
                cert = Certificate(evaluation.certificate.problem_key, evaluation.certificate.method,
                                   evaluation.certificate.arithmetic, evaluation.certificate.budget,
                                   tuple(trace), enclosures, evaluation.certificate.residuals)
                return CertifiedChoice(index, candidate, u, previous, current, cert)
        if engine is None:
            raise RateIncomplete("selection_boundary", "cumulative boundary is not certified")
        try:
            engine.refine()
            evaluation = engine.evaluation()
        except RateIncomplete as exc:
            if exc.reason not in ("budget", "accuracy"):
                raise
            raise RateIncomplete("selection_boundary", "refinement budget cannot separate u from the boundary") from exc


def _interval_json(interval):
    return {"lower": _pair(interval.lower), "upper": _pair(interval.upper)}


def _full_gamma_integral(cfg, kernel):
    from math import factorial
    shape = int(_Fraction(*cfg["_rate"]["prior"]["params"]["shape"]))
    beta = _Fraction(*cfg["_rate"]["prior"]["params"]["rate"])
    return sum((c * beta**shape * factorial(shape + k - 1) /
                (factorial(shape - 1) * (beta + d)**(shape + k)) for k, d, c in kernel), _Fraction(0))


def _ep_derivative(kernel):
    return _ep((term for k, d, c in kernel for term in
                ((k - 1, d, k * c), (k, d, -d * c)) if term[0] >= 0))


@_dataclass(frozen=True, slots=True)
class _InformationInterval:
    lower: object
    upper: object


@_dataclass(frozen=True, slots=True)
class _InformationArithmetic:
    """Exact scalar arithmetic and conversion at the information boundary."""
    scalar: object = _InformationScalar

    def number(self, numerator=0, denominator=None):
        if denominator is not None:
            return self.scalar(int(numerator), int(denominator))
        if isinstance(numerator, _Fraction):
            return self.scalar(numerator.numerator, numerator.denominator)
        return self.scalar(numerator)

    def ratio(self, value, *, upper=False):
        return int(value.numerator), int(value.denominator)

    def to_fraction(self, value, *, upper=False):
        return _Fraction(*self.ratio(value, upper=upper))

    def endpoints(self, value):
        return value, value

    def interval(self, lower, upper):
        lower, upper = self.number(lower), self.number(upper)
        lower, upper = self.endpoints(lower)[0], self.endpoints(upper)[1]
        if lower > upper:
            raise RateNumericalRange("invalid_interval", "ordered Fraction endpoints required")
        return _InformationInterval(lower, upper)

    @staticmethod
    def minimum(*values):
        return min(*values)

    @staticmethod
    def maximum(*values):
        return max(*values)

    def floor(self, value):
        numerator, denominator = self.ratio(value)
        return numerator // denominator

    @staticmethod
    def order_key(value):
        return value


class _RateInformationWork:
    """Reusable rational series, with uniform remainders on reduced domains.

    max_terms counts the coefficients constructed, not repeated evaluations
    of the same certified polynomial. Cell evaluations use those coefficients
    and outward integer rounding; their number is bounded by max_cells and
    max_refinements. No floating point value participates in an enclosure.
    """
    def __init__(self, budget, *, arithmetic=None):
        self.arithmetic = arithmetic or _InformationArithmetic()
        self.number = self.arithmetic.number
        self.interval = self.arithmetic.interval
        self.minimum, self.maximum = self.arithmetic.minimum, self.arithmetic.maximum
        self.budget, self.trace, self.terms = budget, [], 0
        self.logs = {}
        # A tiny requested tolerance must not prevent an early selection.
        self.epsilon = self.number(1, 10**24)
        self.log_degree = self.exp_degree = 0
        self.log_coefficients = []
        self.exp_coefficients = [self.number(1)]
        self.exponentials = {}

    def pair(self, value):
        return _pair(self.arithmetic.to_fraction(value))

    def public(self, interval):
        return RationalInterval(self.arithmetic.to_fraction(interval.lower),
                                self.arithmetic.to_fraction(interval.upper, upper=True))

    def coefficients(self, kind, degree):
        name = kind + "_degree"
        old = getattr(self, name)
        if degree <= old:
            return
        if self.terms + degree - old > self.budget.max_terms:
            raise RateIncomplete("budget", "elementary-series coefficients exceed max_terms")
        if kind == "log":
            self.log_coefficients.extend(self.number(2, 2 * n + 1) for n in range(old, degree))
        else:
            for n in range(old + 1, degree + 1):
                self.exp_coefficients.append(self.exp_coefficients[-1] / n)
        self.terms += degree - old
        setattr(self, name, degree)
        _trace(self.trace, "series", dimension=kind + "-uniform", terms=degree - old,
               cutoff=self.pair(self.number(1, 3) if kind == "log" else self.number(1)))

    def series_enclosure(self, interval, *, positive=False):
        # Integer floor/ceil bounds retain the elementary-series grid.
        numerator, denominator = self.arithmetic.ratio(self.epsilon)
        target = 8 * denominator // numerator + 1
        grid = 1 << target.bit_length()
        if positive and interval.lower > 0:
            numerator, denominator = self.arithmetic.ratio(interval.lower)
            grid <<= max(0, denominator.bit_length() - numerator.bit_length())
        lower = self.arithmetic.floor(interval.lower * grid)
        upper = -self.arithmetic.floor(-interval.upper * grid)
        return self.interval(self.number(lower, grid), self.number(upper, grid))

    def log(self, x):
        x = self.number(x)
        lower, upper = self.arithmetic.endpoints(x)
        if lower != upper:
            return self.interval(self.log(lower).lower, self.log(upper).upper)
        if x <= 0:
            raise RateNumericalRange("invalid_interval", "log requires a positive endpoint")
        if x in self.logs:
            return self.logs[x]
        m, exponent = x, 0
        while m < 1:
            m *= 2
            exponent -= 1
        while m >= 2:
            m /= 2
            exponent += 1
        def series(value, degree):
            z = (value - 1) / (value + 1)
            term, total = z, self.number(0)
            if not z:
                return self.interval(self.number(0), self.number(0))
            for coefficient in self.log_coefficients[:degree]:
                total += coefficient * term
                term *= z * z
            remainder = 2 * term / ((2 * degree + 1) * (1 - z * z))
            return self.interval(total, total + remainder)
        epsilon = self.epsilon / (1 + abs(exponent))
        degree = self.maximum(1, self.log_degree)
        while self.number(9, 4) * self.number(1, 3)**(2 * degree + 1) / (2 * degree + 1) > epsilon:
            degree += 1
        self.coefficients("log", degree)
        base = series(m, degree)
        if exponent:
            ln2 = self.logs.get(self.number(2))
            if ln2 is None or ln2.upper - ln2.lower > epsilon:
                ln2 = series(self.number(2), degree)
                self.logs[self.number(2)] = ln2
            if exponent > 0:
                base = self.interval(base.lower + exponent * ln2.lower, base.upper + exponent * ln2.upper)
            else:
                base = self.interval(base.lower + exponent * ln2.upper, base.upper + exponent * ln2.lower)
        base = self.series_enclosure(base)
        self.logs[x] = base
        return base

    def exp(self, x):
        x = self.number(x)
        lower, upper = self.arithmetic.endpoints(x)
        if lower != upper:
            return self.interval(self.exp(lower).lower, self.exp(upper).upper)
        if x == 0:
            return self.interval(self.number(1), self.number(1))
        if abs(x) > self.budget.max_terms:
            raise RateNumericalRange("representation_limit", "exponential argument exceeds rational series resources")
        key = (x, self.epsilon)
        if key in self.exponentials:
            return self.exponentials[key]
        from math import factorial
        reduced, squares = abs(x), 0
        while reduced > 1:
            reduced /= 2
            squares += 1
        degree = self.maximum(1, self.exp_degree)
        epsilon = self.epsilon / (2**squares * 16)
        while self.number(degree + 2, (degree + 1) * factorial(degree + 1)) > epsilon:
            degree += 1
        self.coefficients("exp", degree)
        total = power = self.number(1)
        for n in range(1, degree + 1):
            power *= reduced
            total += power * self.exp_coefficients[n]
        term = power * self.exp_coefficients[degree]
        remainder = term * reduced / (degree + 1) / (1 - reduced / (degree + 2))
        value = self.series_enclosure(self.interval(total, total + remainder))
        for _ in range(squares):
            value = self.series_enclosure(self.interval(value.lower**2, value.upper**2))
        if x < 0:
            value = self.series_enclosure(self.interval(1 / value.upper, 1 / value.lower), positive=True)
        self.exponentials[key] = value
        return value

    def phi(self, x):
        x = self.number(x)
        lower, upper = self.arithmetic.endpoints(x)
        if lower != upper:
            return self.phi_interval(self.interval(lower, upper))
        if x == 0:
            return self.interval(self.number(0), self.number(0))
        value = self.log(x)
        return self.interval(-x * value.upper, -x * value.lower)

    def phi_interval(self, interval):
        """Continuous envelope at zero; never take log(0) or divide by zero."""
        a, b = self.maximum(self.number(0), interval.lower), self.minimum(self.number(1), interval.upper)
        if not b:
            return self.interval(self.number(0), self.number(0))
        left, right = self.phi(a), self.phi(b)
        peak = self.exp(self.number(-1))
        upper = right.upper if b <= peak.lower else left.upper if a >= peak.upper else peak.upper
        return self.interval(self.maximum(self.number(0), self.minimum(left.lower, right.lower)), upper)

    def add(self, a, b):
        return self.series_enclosure(self.interval(a.lower + b.lower, a.upper + b.upper))

    def scale(self, a, b):
        return self.series_enclosure(self.interval(self.minimum(a.lower * b, a.upper * b),
                                                      self.maximum(a.lower * b, a.upper * b)))

    def multiply(self, a, b):
        products = (a.lower * b.lower, a.lower * b.upper, a.upper * b.lower, a.upper * b.upper)
        return self.series_enclosure(self.interval(self.minimum(products), self.maximum(products)))

    def divide(self, a, b):
        if b.lower <= 0:
            raise RateNumericalRange("invalid_interval", "positive divisor required")
        return self.multiply(a, self.interval(1 / b.upper, 1 / b.lower))

    def power(self, a, n):
        if n % 2:
            return self.series_enclosure(self.interval(a.lower**n, a.upper**n), positive=a.lower > 0)
        return self.series_enclosure(self.interval(self.number(0) if a.lower <= 0 <= a.upper else
                                                      self.minimum(a.lower**n, a.upper**n), self.maximum(a.lower**n, a.upper**n)),
                                         positive=a.lower > 0)


def _entropy(work, probabilities):
    bounds = tuple(work.phi(p) for p in probabilities)
    return work.interval(sum((b.lower for b in bounds), work.number(0)),
                            sum((b.upper for b in bounds), work.number(0)))


def _rate_policy(work, values, gamma):
    if any(v.status == "uncertified" for v in values):
        reason = next(v.reason for v in values if v.status == "uncertified") or "proof_unavailable"
        raise RateIncomplete(reason, "an uncertified candidate cannot be discarded")
    finite = [i for i, v in enumerate(values) if v.status == "finite"]
    if not finite:
        raise RateNoAdmissibleCandidate("all_forbidden", "all J are certified positive infinity")
    if any(v.status not in ("finite", "positive_infinity") for v in values):
        raise RateInputError("shape", "unknown quantity status")
    gamma = work.number(gamma)
    bounds = tuple(None if v.bounds is None else work.interval(work.number(v.bounds.lower),
                                                               work.number(v.bounds.upper)) for v in values)
    zero = work.interval(work.number(0), work.number(0))
    result = [zero] * len(values)
    equal = gamma == 0 or all(bounds[i].lower == bounds[i].upper == bounds[finite[0]].lower
                              for i in finite)
    for i in finite:
        if equal or len(finite) == 1:
            result[i] = work.interval(work.number(1, len(finite)), work.number(1, len(finite)))
            continue
        lower_sum = upper_sum = work.number(1)
        for j in finite:
            if j == i:
                continue
            lower_sum += work.exp(gamma * (bounds[i].lower - bounds[j].upper)).lower
            upper_sum += work.exp(gamma * (bounds[i].upper - bounds[j].lower)).upper
        result[i] = work.interval(1 / upper_sum, 1 / lower_sum)
    if len(result) == 2:
        # With two candidates the complement is an exact identity, including
        # the elementary-series enclosure width of the first probability.
        result[1] = work.interval(1 - result[0].upper, 1 - result[0].lower)
    cumulative = [zero]
    for i in range(1, len(result)):
        lower = work.maximum(sum(v.lower for v in result[:i]), 1 - sum(v.upper for v in result[i:]))
        upper = work.minimum(sum(v.upper for v in result[:i]), 1 - sum(v.lower for v in result[i:]))
        cumulative.append(work.interval(work.maximum(work.number(0), lower), work.minimum(work.number(1), upper)))
    cumulative.append(work.interval(work.number(1), work.number(1)))
    return tuple(result), tuple(cumulative)


def _evaluate_rate(view, candidates, resolved, budget, *, require_width=True, _arithmetic=None):
    from .rate_entry import certify_rate_scope, _rate_evaluation_inputs, rate_history, _fixed_events
    scope = certify_rate_scope(view, candidates, resolved, budget=budget)
    errors = {"incomplete": RateIncomplete, "missing_spec": RateSpecificationMissing,
              "outside_evaluation": RateOutsideEvaluationType, "runtime_unverified": RateRuntimeUnverified}
    if scope.status != "certified":
        raise errors[scope.status](scope.reason, "; ".join(scope.conditions))
    cfg, choices, context, gamma = _rate_evaluation_inputs(view, candidates, resolved, budget)
    history = rate_history(view.model, view.reading, context=context)
    windows, _, _, horizon = _fixed_events(cfg, history)
    # This root's full Gamma integral is rational. Use its analytic proof
    # directly; a selection query must not wait for a tolerance-sized tail
    # that the already proved full integral does not need.
    kernel = _c1_total(_c1_paths(cfg, windows, (), budget).values())
    z = _full_gamma_integral(cfg, kernel)
    if z <= 0:
        raise RateModelFalsified("zero_evidence", "analytic root mass is zero")
    trace = []
    _trace(trace, "analytic", dimension="full-gamma-evidence")
    cert = Certificate(history.evidence_key, _ContractRef("sui.s4b.rate_c1", "1"),
                       _ContractRef("rational-series", "1"), budget, tuple(trace), {"evidence": _pair(z)},
                       ({"quantity": "evidence", "candidate": None, "source": "rounding", "upper": [0, 1]},))
    evidence = LikelihoodCertificate(RationalInterval(z, z), "mass", _ContractRef(**cfg["measure"]["family"]),
                                     "1", "positive", cert)
    belief = object.__new__(RateBelief)
    for name, value in (("model_ref", view.model.ref), ("history", history), ("evidence", evidence),
                        ("_model", view.model), ("_windows", tuple(_freeze(w) for w in windows)),
                        ("_measurements", ()), ("_time", horizon), ("_problem", history.evidence_key)):
        object.__setattr__(belief, name, value)
    engine = _C1Information(view, choices, resolved, belief, cfg, gamma, budget, arithmetic=_arithmetic)
    evaluation = engine.evaluation()
    # A public selection tests its exact u against this initial enclosure and
    # refines only while unresolved. Standalone mathematical queries and later
    # refinement retain §7's probability-width calculation.
    if require_width:
        probability_width = max(budget.tolerance, _Fraction(1, 10**6))
        while any(q.bounds.upper - q.bounds.lower > probability_width for q in evaluation.q_star):
            engine.refine()
            evaluation = engine.evaluation()
    return evaluation, engine


class _C1Information:
    """B2's joint entropy integral; analytic elimination supplies early bounds.

    With the shared independent probe, p integrates to E[H(Y|p)]=1/2.
    The count integrand is sum(phi(g_sc))-sum(phi(r_s)), not a sum of
    marginal law and state informations. Jensen gives its initial envelope;
    Cells tighten the same integral for the standalone probability enclosure
    and, when necessary, for the selector's exact cumulative inequality.
    """
    def __init__(self, view, choices, resolved, belief, cfg, gamma, budget, *, arithmetic=None):
        self.view, self.choices, self.resolved = view, choices, resolved
        self.belief, self.cfg, self.gamma, self.budget = belief, cfg, gamma, budget
        self.work = _RateInformationWork(budget, arithmetic=arithmetic)
        self.number, self.interval = self.work.number, self.work.interval
        self.minimum, self.maximum = self.work.minimum, self.work.maximum
        self.work.trace = [dict(step) for step in belief.evidence.certificate.trace]
        self.work.terms = sum(step["terms"] or 0 for step in self.work.trace if step["operation"] == "series")
        duration = cfg["_duration"]
        self.kernels = []
        for count in range(cfg["_read"]["kernel"]["params"]["cap"] + 1):
            window = _freeze({"record": cfg["_read"]["id"], "process": cfg["_arrival"]["id"],
                              "start": duration, "end": 2 * duration, "kind": "count",
                              "cap": cfg["_read"]["kernel"]["params"]["cap"], "count": count})
            paths = _c1_paths(cfg, belief._windows + (window,), (2 * duration,), budget)
            self.kernels.append(tuple(paths.get((s,), ()) for s in range(len(view.model.states))))
        self.kernels = tuple(self.kernels)
        self.beta = _Fraction(*cfg["_rate"]["prior"]["params"]["rate"])
        state_kernels = tuple(_c1_total(row[s] for row in self.kernels) for s in range(2))
        self.entropy_kernels = tuple(k for row in self.kernels for k in row) + state_kernels
        self.derivatives = []
        for kernel in self.entropy_kernels + (((1, self.beta, self.beta**2),),):
            derivatives = [kernel]
            for _ in range(8):
                derivatives.append(_ep_derivative(derivatives[-1]))
            self.derivatives.append(tuple(derivatives))
        self.derivatives = tuple(self.derivatives)
        masses = tuple(tuple(_full_gamma_integral(cfg, k) for k in row) for row in self.kernels)
        self.z = sum(sum(row) for row in masses)
        if self.z <= 0:
            raise RateModelFalsified("zero_evidence", "analytic root mass is zero")
        self.probabilities = tuple(tuple(m / self.z for m in row) for row in masses)
        self.beta = self.number(self.beta)
        self.numeric_derivatives = tuple(tuple(tuple((k, self.number(d), self.number(v)) for k, d, v in kernel)
                                               for kernel in row) for row in self.derivatives)
        self.numeric_entropy_kernels = tuple(row[0] for row in self.numeric_derivatives[:-1])
        self.z = self.number(self.z)
        self.probabilities = tuple(tuple(self.number(p) for p in row) for row in self.probabilities)
        pc = tuple(sum(row) for row in self.probabilities)
        ps = tuple(sum(row[s] for row in self.probabilities) for s in range(2))
        self.hc = _entropy(self.work, pc)
        joint, state = _entropy(self.work, (p for row in self.probabilities for p in row)), _entropy(self.work, ps)
        h_conditional = self.interval(self.maximum(self.number(0), joint.lower - state.upper), joint.upper - state.lower)
        ln2 = self.work.log(self.number(2))
        self.hp = self.interval(ln2.lower - self.number(1, 2), ln2.upper - self.number(1, 2))
        self.base_series = sum(v.upper - v.lower for v in (self.hp, self.hc, joint, state))
        self.conditional = self.interval(self.number(0), self.z * h_conditional.upper)
        self.cutoff = _Fraction(8) / _Fraction(*cfg["_rate"]["prior"]["params"]["rate"])
        exponential = self.work.exp(-self.beta * self.number(self.cutoff))
        self.tail = self.interval(9 * exponential.lower, 9 * exponential.upper)
        self.log_k = self.work.log(self.number(len(cfg["_read"]["alphabet"]["values"])))
        self.cells, self.refinements, self.next_box = {}, 0, 1
        _trace(self.work.trace, "analytic", dimension="joint-masses-and-probe-entropy")
        _trace(self.work.trace, "tail", dimension="conditional-entropy", cutoff=_pair(self.cutoff))
        self.read_choice = next(c["id"] for c in cfg["controls"]["choices"]
                                if c["observation_records"] == [cfg["_read"]["id"]])
        self.key = _c1_key(belief._problem, "evaluation", (choices, resolved.H_ns, gamma))

    def evaluation(self):
        information = self.interval(self.maximum(self.number(0), self.hp.lower + self.hc.lower - self.conditional.upper / self.z),
                                       self.hp.upper + self.hc.upper - self.conditional.lower / self.z)
        zero = self.interval(self.number(0), self.number(0))
        infos = tuple(information if c == self.read_choice else zero for c in self.choices)
        js = tuple(self.interval(-v.upper, -v.lower) for v in infos)
        temporary = tuple(CertifiedQuantity("finite", j, "signed" if j.lower < 0 else "zero", None, None, None) for j in js)
        qs, cumulative = _rate_policy(self.work, temporary, self.gamma)
        trace = [dict(step) for step in self.work.trace]
        _trace(trace, "aggregate", dimension="information-J-q-cumulative")
        residuals = []
        for c, i, q in zip(self.choices, infos, qs):
            for quantity, sources in (("information", (("information", i.upper - i.lower),
                   ("series", self.base_series + sum(v[3] for v in self.cells.values()) / self.z
                    if c == self.read_choice else self.number(0)),
                   ("tail", self.tail.upper * self.log_k.upper / self.z if c == self.read_choice else self.number(0)),
                   ("quadrature", sum(v[4] for v in self.cells.values()) / self.z
                    if c == self.read_choice else self.number(0)), ("conditioning", self.number(0)))),
                   ("q_star", (("information", q.upper - q.lower),
                               ("series", self.minimum(q.upper - q.lower, 2 * len(self.choices) * self.work.epsilon))))):
                for source, value in (*sources, ("rounding", self.number(0))):
                    residuals.append({"quantity": quantity, "candidate": c, "source": source, "upper": self.work.pair(value)})
        enclosures = {"gamma": _pair(self.gamma), "evidence": self.work.pair(self.z),
                      "joint_count_state": [[self.work.pair(v) for v in row] for row in self.probabilities],
                      "probe_conditional_entropy": [1, 2], "count_conditional_integral": _interval_json(self.work.public(self.conditional)),
                      "prior_tail": _interval_json(self.work.public(self.tail)), "entropy_tail_upper": self.work.pair(self.tail.upper * self.log_k.upper),
                      "rate_cells": [{"id": key, "lower": _pair(v[0]), "upper": _pair(v[1]),
                                      "conditional_integral": _interval_json(self.work.public(v[2])),
                                      "series_upper": self.work.pair(v[3]), "quadrature_upper": self.work.pair(v[4])}
                                     for key, v in sorted(self.cells.items())],
                      "information": [_interval_json(self.work.public(v)) for v in infos], "J": [_interval_json(self.work.public(v)) for v in js],
                      "q_star": [_interval_json(self.work.public(v)) for v in qs], "cumulative": [_interval_json(self.work.public(v)) for v in cumulative]}
        cert = Certificate(self.key, _ContractRef("sui.s4b.rate_c1", "1"), _ContractRef("rational-series", "1"),
                           self.budget, tuple(trace), enclosures, tuple(residuals))
        def quantity(v, signed=False):
            support = "zero" if v.upper == v.lower == 0 else "signed" if signed else "positive" if v.lower > 0 else "unproved"
            return CertifiedQuantity("finite", self.work.public(v), support, None, None, cert)
        costs = tuple(quantity(zero) for _ in self.choices)
        objective = tuple(quantity(v, True) for v in js)
        return RateEvaluation(self.choices, costs, tuple(quantity(v) for v in infos), objective, objective,
                              tuple(quantity(v) for v in qs), tuple(self.work.public(v) for v in cumulative), cert, (self.view, self.choices, self.resolved))

    def refine(self):
        if self.refinements >= self.budget.max_refinements:
            raise RateIncomplete("budget", "information subdivisions exceed max_refinements")
        self.refinements += 1
        if self.cells and (self.base_series * self.z + sum(v[3] for v in self.cells.values()) >=
                           sum(v[4] for v in self.cells.values()) + self.tail.upper * self.log_k.upper):
            self.work.epsilon /= 2
            self.work.logs.clear()
            self.hc = _entropy(self.work, (sum(row) for row in self.probabilities))
            ln2 = self.work.log(self.number(2))
            self.hp = self.interval(ln2.lower - self.number(1, 2), ln2.upper - self.number(1, 2))
            self.base_series = self.hp.upper - self.hp.lower + self.hc.upper - self.hc.lower
            self.log_k = self.work.log(self.number(len(self.cfg["_read"]["alphabet"]["values"])))
            exponential = self.work.exp(-self.beta * self.number(self.cutoff))
            self.tail = self.interval((1 + self.beta * self.number(self.cutoff)) * exponential.lower,
                                         (1 + self.beta * self.number(self.cutoff)) * exponential.upper)
            _trace(self.work.trace, "analytic", dimension="refine-elementary-series", cutoff=self.work.pair(self.work.epsilon))
            for key, value in sorted(self.cells.items()):
                self.cells[key] = self.cell(value[0], value[1])
            self.update_integral()
            return
        if not self.cells:
            self.cells["0"] = self.cell(_Fraction(0), self.cutoff)
        else:
            if len(self.cells) >= self.budget.max_cells:
                raise RateIncomplete("budget", "information cells exceed max_cells")
            key = min(self.cells, key=lambda k: (self.work.arithmetic.order_key(-(self.cells[k][2].upper - self.cells[k][2].lower)), k))
            cell_width = self.cells[key][2].upper - self.cells[key][2].lower
            if self.tail.upper * self.log_k.upper >= cell_width:
                # Reveal the next dyadic prior box when the unevaluated tail
                # dominates. Box roots and their binary split paths are stable
                # IDs; a tail is never silently fixed at the initial cutoff.
                left, right = self.cutoff, 2 * self.cutoff
                box = str(self.next_box) + ":0"
                self.next_box += 1
                self.cells[box] = self.cell(left, right)
                self.cutoff = right
                exponential = self.work.exp(-self.beta * self.number(right))
                self.tail = self.interval((1 + self.beta * self.number(right)) * exponential.lower,
                                             (1 + self.beta * self.number(right)) * exponential.upper)
                _trace(self.work.trace, "tail", dimension="conditional-entropy", cutoff=_pair(right))
            else:
                left, right, *_ = self.cells.pop(key)
                middle = (left + right) / 2
                _trace(self.work.trace, "split", cell=key, dimension=self.cfg["_rate"]["id"], cutoff=_pair(middle))
                self.cells[key + "0"] = self.cell(left, middle)
                self.cells[key + "1"] = self.cell(middle, right)
        self.update_integral()

    def update_integral(self):
        lower = sum(v[2].lower for v in self.cells.values())
        upper = sum(v[2].upper for v in self.cells.values()) + self.tail.upper * self.log_k.upper
        self.conditional = self.interval(self.maximum(self.conditional.lower, lower), self.minimum(self.conditional.upper, upper))

    def cell(self, left, right):
        work = self.work
        from math import comb, factorial
        zero = self.interval(self.number(0), self.number(0))
        exact_left, exact_right = left, right
        left, right = self.number(left), self.number(right)
        middle, radius = (left + right) / 2, (right - left) / 2
        def point(kernel, t):
            lower = upper = self.number(0)
            for k, d, c in kernel:
                exponential = work.exp(-d * t)
                coefficient = c * t**k
                lower += coefficient * (exponential.lower if coefficient > 0 else exponential.upper)
                upper += coefficient * (exponential.upper if coefficient > 0 else exponential.lower)
            return work.series_enclosure(self.interval(lower, upper))
        def natural_range(kernel):
            lower = upper = self.number(0)
            for k, d, c in kernel:
                a, b = work.exp(-d * right), work.exp(-d * left)
                lo, hi = left**k * a.lower, right**k * b.upper
                lower += c * (lo if c > 0 else hi)
                upper += c * (hi if c > 0 else lo)
            return self.interval(lower, upper)
        ranges = []
        for derivatives in self.numeric_derivatives:
            coefficients = tuple(point(k, middle) for k in derivatives[:8])
            final = natural_range(derivatives[8])
            row = []
            for j in range(5):
                remainder = self.maximum(abs(final.lower), abs(final.upper)) * radius**(8 - j) / factorial(8 - j)
                for k in range(j + 1, 8):
                    value = coefficients[k]
                    remainder += self.maximum(abs(value.lower), abs(value.upper)) * radius**(k - j) / factorial(k - j)
                row.append(self.interval(coefficients[j].lower - remainder, coefficients[j].upper + remainder))
            ranges.append(tuple(row))
        # Taylor's theorem bounds whole-cell derivatives, including the
        # cancellations in overflow probabilities. At a zero we use the
        # continuous entropy envelope instead of differentiating log(0).
        if any(row[0].lower <= 0 for row in ranges[:-1]):
            a, b = work.exp(-self.beta * left), work.exp(-self.beta * self.number(right))
            mass = self.maximum(self.number(0), (1 + self.beta * left) * a.upper - (1 + self.beta * self.number(right)) * b.lower)
            values = tuple(work.phi_interval(self.interval(self.maximum(self.number(0), row[0].lower),
                                                              self.minimum(self.number(1), self.maximum(self.number(0), row[0].upper))))
                           for row in ranges[:-1])
            upper = self.minimum(self.log_k.upper, self.maximum(self.number(0), sum(v.upper for v in values[:-2]) -
                                             sum(v.lower for v in values[-2:])))
            integral = self.interval(self.number(0), mass * upper)
            _trace(work.trace, "analytic", dimension="zero-safe-entropy-envelope", cutoff=_pair(exact_right))
            return exact_left, exact_right, integral, self.number(0), integral.upper - integral.lower

        def phi_derivatives(row):
            g, d1, d2, d3, d4 = row
            log = self.interval(work.log(g.lower).lower + 1, work.log(g.upper).upper + 1)
            mul, add, scale, div, power = work.multiply, work.add, work.scale, work.divide, work.power
            f0 = work.phi_interval(g)
            f1 = scale(mul(log, d1), -1)
            f2 = scale(add(div(power(d1, 2), g), mul(log, d2)), -1)
            f3 = add(div(power(d1, 3), power(g, 2)),
                     scale(add(scale(div(mul(d1, d2), g), 3), mul(log, d3)), -1))
            f4 = add(scale(div(power(d1, 4), power(g, 3)), -2),
                     scale(div(mul(power(d1, 2), d2), power(g, 2)), 6))
            f4 = add(f4, scale(div(add(scale(power(d2, 2), 3), scale(mul(d1, d3), 4)), g), -1))
            f4 = add(f4, scale(mul(log, d4), -1))
            return f0, f1, f2, f3, f4
        entropy_derivatives = [zero] * 5
        for index, row in enumerate(ranges[:-1]):
            for j, value in enumerate(phi_derivatives(row)):
                entropy_derivatives[j] = work.add(entropy_derivatives[j],
                                                  work.scale(value, 1 if index < len(ranges) - 3 else -1))
        fourth = zero
        for j in range(5):
            fourth = work.add(fourth, work.scale(work.multiply(ranges[-1][j], entropy_derivatives[4 - j]), comb(4, j)))
        def integrand(t):
            entropy = zero
            for index, kernel in enumerate(self.numeric_entropy_kernels):
                value = point(kernel, t)
                phi = work.phi_interval(self.interval(self.maximum(self.number(0), value.lower),
                                                         self.minimum(self.number(1), self.maximum(self.number(0), value.upper))))
                entropy = work.add(entropy, work.scale(phi, 1 if index < len(self.entropy_kernels) - 2 else -1))
            return work.multiply(point(self.numeric_derivatives[-1][0], t), entropy)
        simpson = work.scale(work.add(work.add(integrand(left), work.scale(integrand(middle), 4)), integrand(right)),
                             (right - left) / 6)
        # One-panel Simpson remainder: width^5 / 2880 * sup |f''''|.
        error = (right - left)**5 * self.maximum(abs(fourth.lower), abs(fourth.upper)) / 2880
        integral = self.interval(self.maximum(self.number(0), simpson.lower - error), self.maximum(self.number(0), simpson.upper + error))
        _trace(work.trace, "analytic", dimension="joint-entropy-Simpson-fourth-derivative", cutoff=_pair(exact_right))
        return exact_left, exact_right, integral, simpson.upper - simpson.lower, 2 * error


def _check_rate_evaluation(evaluation):
    k = len(evaluation.candidates)
    if not k or any(not isinstance(c, str) for c in evaluation.candidates) or len(set(evaluation.candidates)) != k:
        raise RateInputError("shape", "distinct nonempty candidate IDs required")
    if any(len(getattr(evaluation, name)) != k for name in ("expected_cost", "information", "G", "J", "q_star")) or len(evaluation.cumulative) != k + 1:
        raise RateInputError("shape", "evaluation dimensions do not match candidates")
    if not isinstance(evaluation.certificate, Certificate):
        raise RateIncomplete("proof_unavailable", "evaluation certificate required")
    _rate_budget(evaluation.certificate.budget)
    if (evaluation.certificate.method != _ContractRef("sui.s4b.rate_c1", "1") or
            evaluation.certificate.arithmetic != _ContractRef("rational-series", "1")):
        raise RateIncomplete("proof_unavailable", "unknown method/arithmetic version")
    for name in ("expected_cost", "information", "G", "J", "q_star"):
        for v in getattr(evaluation, name):
            if v.status == "uncertified":
                raise RateIncomplete(v.reason or "proof_unavailable", "uncertified candidate cannot be discarded")
    if all(v.status == "positive_infinity" for v in evaluation.J):
        raise RateNoAdmissibleCandidate("all_forbidden", "all candidates are forbidden")
    if evaluation.cumulative[0] != RationalInterval(_Fraction(0), _Fraction(0)) or evaluation.cumulative[-1] != RationalInterval(_Fraction(1), _Fraction(1)):
        raise RateIncomplete("proof_unavailable", "endpoint identities are missing")
    if any(not isinstance(v, RationalInterval) or not 0 <= v.lower <= v.upper <= 1 for v in evaluation.cumulative):
        raise RateIncomplete("proof_unavailable", "invalid cumulative enclosure")


def _check_algebraic_evaluation(evaluation):
    # Public mathematical fixtures can be checked against their supplied
    # C/I intervals without trusting certificate fields. A model certificate
    # needs its frozen inputs for the version-fixed recomputation above.
    if evaluation.certificate.trace or evaluation.certificate.enclosures:
        raise RateIncomplete("proof_unavailable", "model certificate has no frozen recomputation inputs")
    for cost, info, g, j in zip(evaluation.expected_cost, evaluation.information, evaluation.G, evaluation.J):
        if j.status == "positive_infinity":
            if cost.status != "positive_infinity" or info.status != "finite":
                raise RateIncomplete("proof_unavailable", "positive infinity is not certified by a finite-information cost")
            continue
        if any(v.status != "finite" or v.bounds is None for v in (cost, info, g, j)):
            raise RateIncomplete("proof_unavailable", "finite C/I/G/J bounds required")
        difference = RationalInterval(cost.bounds.lower - info.bounds.upper, cost.bounds.upper - info.bounds.lower)
        if g.bounds != difference or j.bounds != g.bounds:
            raise RateIncomplete("proof_unavailable", "G/J do not match C-I")
    gamma = _Fraction(1)
    if isinstance(evaluation.certificate.enclosures, _Mapping) and "gamma" in evaluation.certificate.enclosures:
        gamma = _Fraction(*evaluation.certificate.enclosures["gamma"])
    work = _RateInformationWork(evaluation.certificate.budget)
    # Independently supplied enclosures may be much narrower than the display
    # tolerance. Verify their inequalities with rational series guard digits.
    work.epsilon = work.minimum(work.epsilon, work.number(1, 10**40))
    qs, cumulative = _rate_policy(work, evaluation.J, gamma)
    qs, cumulative = tuple(map(work.public, qs)), tuple(map(work.public, cumulative))
    for supplied, checked in zip(evaluation.q_star, qs):
        if supplied.status != "finite" or supplied.bounds is None or not 0 <= supplied.bounds.lower <= checked.lower <= checked.upper <= supplied.bounds.upper <= 1:
            raise RateIncomplete("proof_unavailable", "q enclosure fails independent algebraic check")
    for supplied, checked in zip(evaluation.cumulative, cumulative):
        if not supplied.lower <= checked.lower <= checked.upper <= supplied.upper:
            raise RateIncomplete("proof_unavailable", "cumulative enclosure fails independent algebraic check")
