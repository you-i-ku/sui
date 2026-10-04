"""S4b-1c §6-3 (i)-2: the continuous, one-jump mathematical ruler.

Times here are seconds, including continuous integration variables. They are
not Instant/mono_ns, rounded readings, or facts for the public driving loop.
The sole generator is 0 -> 1 at the explicitly supplied rate q (1/second).
The reference measure for reports is Lebesgue plus the union of all atoms.
Quadrature bounds cover integration error, not floating-point roundoff.
"""

from dataclasses import dataclass, field
from fractions import Fraction
import math
from types import MappingProxyType

from .inference import ModelViolation, NumericalRange
from .joint import NameSpec, ProbabilityBounds
from .progress import CompletionSpec, _fraction
from .quantity import IntegrationIncomplete, _log_fraction
from .values import InformationBounds, MeasureSpec


def _number(value, name):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise NumericalRange(f"stage2 {name}: outside finite numerical range") from exc
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise NumericalRange(f"stage2 {name}: outside finite numerical range")
    return result


def _exp(log_value):
    if log_value == -math.inf:
        return 0.0
    try:
        result = math.exp(log_value)
    except OverflowError as exc:
        raise NumericalRange("stage2: exponential outside numerical range") from exc
    if not math.isfinite(result) or result == 0:
        raise NumericalRange("stage2: positive mass/density outside numerical range")
    return result


def _sum_logs(values):
    values = tuple(v for v in values if v != -math.inf)
    if not values:
        return -math.inf
    top = max(values)
    # Relative terms that cannot be represented must not become structural 0.
    return top + math.log(math.fsum(_exp(v - top) for v in values))


def _log_one_minus_exp(x):
    """log(1-exp(-x)), x >= 0; exp(-x) need not itself be representable."""
    if x == 0:
        return -math.inf
    if not math.isfinite(x) or x < 0:
        raise NumericalRange("stage2: exponential argument outside numerical range")
    if x <= math.log(2):
        return math.log(-math.expm1(-x))
    return math.log1p(-math.exp(-x))


@dataclass(frozen=True, slots=True)
class KernelAtom:
    time_s: Fraction
    log_state_mass: tuple[float, float]

    @property
    def state_mass(self):
        return tuple(_exp(v) for v in self.log_state_mass)

    @property
    def log_mass(self):
        return _sum_logs(self.log_state_mass)


@dataclass(frozen=True, slots=True)
class KernelWindow:
    """Atoms, integrated continuous mass, and R > H remain separate."""

    atoms: tuple[KernelAtom, ...]
    log_continuous_mass: float
    log_not_arrived: float

    @property
    def continuous_mass(self):
        return _exp(self.log_continuous_mass)

    @property
    def not_arrived_mass(self):
        return _exp(self.log_not_arrived)

    @property
    def mass(self):
        return math.fsum([_exp(a.log_mass) for a in self.atoms]
                         + [self.continuous_mass, self.not_arrived_mass])


@dataclass(frozen=True, slots=True, kw_only=True)
class OneJumpKernel:
    """Known positive work and speeds; no model or prior defaults.

    A jump before t0 gives R=t1+slope*T. Its density has the absolute
    Jacobian 1/abs(slope), and completion is in state 1. Equal speeds have
    only an atom, with both states. Permanent nonarrival is impossible in
    this restricted positive-speed kernel (see progress.CompletionKernel).
    """

    q: float
    work: Fraction
    speeds: tuple[Fraction, Fraction]
    t0: Fraction = field(init=False)
    t1: Fraction = field(init=False)
    slope: Fraction = field(init=False)

    def __post_init__(self):
        try:
            q = _fraction(self.q, "jump rate", positive=True)
            work = _fraction(self.work, "known work", positive=True)
            speeds = tuple(_fraction(c, "speed", positive=True) for c in self.speeds)
        except (ValueError, TypeError) as exc:
            raise IntegrationIncomplete("stage2_kernel: positive known work, rate and speeds required") from exc
        if len(speeds) != 2:
            raise IntegrationIncomplete("stage2_states: two speeds required")
        object.__setattr__(self, "q", _number(q, "jump rate"))
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "speeds", speeds)
        object.__setattr__(self, "t0", work / speeds[0])
        object.__setattr__(self, "t1", work / speeds[1])
        object.__setattr__(self, "slope", 1 - speeds[0] / speeds[1])
        _number(self.t0, "completion time")
        _number(self.t1, "completion time")

    def _qt(self, t):
        result = self.q * _number(t, "time")
        if not math.isfinite(result) or (t != 0 and result == 0):
            raise NumericalRange("stage2: q*time outside numerical range")
        return result

    def atom(self):
        x = self._qt(self.t0)
        return KernelAtom(self.t0, (-x, _log_one_minus_exp(x)
                                   if self.slope == 0 else -math.inf))

    def log_density(self, time_s):
        r = _fraction(time_s, "report time")
        if not self.slope or not min(self.t0, self.t1) < r < max(self.t0, self.t1):
            return -math.inf
        return self._density_extension(r)

    def _density_extension(self, r):
        """One-sided endpoint values for a fixed continuous piece only."""
        jump_time = (r - self.t1) / self.slope
        return math.log(self.q) - _log_fraction(abs(self.slope)) - self._qt(jump_time)

    def density(self, time_s):
        return _exp(self.log_density(time_s))

    def continuous_log_mass(self, lower, upper):
        lower, upper = _fraction(lower, "lower time"), _fraction(upper, "upper time")
        if not self.slope:
            return -math.inf
        a, b = max(lower, min(self.t0, self.t1)), min(upper, max(self.t0, self.t1))
        if a >= b:
            return -math.inf
        ta, tb = sorted(((a - self.t1) / self.slope, (b - self.t1) / self.slope))
        return -self._qt(ta) + _log_one_minus_exp(self._qt(tb - ta))

    def not_arrived_log_states(self, horizon_s):
        """Joint P(R>H,S_H=s), for diagnostics, not a new missed target."""
        h = _fraction(horizon_s, "horizon")
        if h < min(self.t0, self.t1):
            return -self._qt(h), _log_one_minus_exp(self._qt(h))
        if h >= max(self.t0, self.t1):
            return -math.inf, -math.inf
        threshold = (h - self.t1) / self.slope
        if self.slope > 0:
            # T>threshold; state 0 iff T>H. threshold <= H.
            return (-self._qt(h), -self._qt(threshold)
                    + _log_one_minus_exp(self._qt(h - threshold)))
        # Slow after the jump: pending at H>=t0 requires T<threshold.
        return -math.inf, _log_one_minus_exp(self._qt(threshold))

    def window(self, horizon_s):
        h = _fraction(horizon_s, "horizon")
        return KernelWindow((self.atom(),) if self.t0 <= h else (),
                            self.continuous_log_mass(0, h),
                            _sum_logs(self.not_arrived_log_states(h)))


@dataclass(frozen=True, slots=True, kw_only=True)
class OneJumpModel:
    """§3-7-5 scope, supplied explicitly from tests; no general Q/history.

    The named state order must be ('0','1'), initially '0'. Known exact/1,
    one action, deterministic constant name, no pending work, and at most
    one informative report are required. Identical speed laws are merged
    before conditioning; duplicate candidate labels are not targets.
    """

    completion: CompletionSpec
    q: float
    work: Fraction
    measure: MeasureSpec
    names: NameSpec
    initial_state: str
    pending: tuple
    max_reports: int
    pairs: tuple = field(init=False)
    weights: tuple = field(init=False)
    kernels: tuple = field(init=False, repr=False)

    def __post_init__(self):
        s = self.completion
        if not isinstance(s, CompletionSpec):
            raise ValueError("stage2: expected CompletionSpec")
        if len(s.actions) != 1 or s.states != ("0", "1") or self.initial_state != "0":
            raise IntegrationIncomplete("stage2_states: initially 0, single 0->1 jump only")
        if s.time_unit != "second":
            raise IntegrationIncomplete("stage2_units: mathematical seconds required")
        if (not isinstance(self.measure, MeasureSpec) or self.measure.name != "exact"
                or self.measure.version != "1" or self.measure.params):
            raise IntegrationIncomplete("stage2_measure: one known exact process required")
        if (not isinstance(self.names, NameSpec) or self.names.learnable
                or self.names.columns != ((Fraction(1),), (Fraction(1),))):
            raise IntegrationIncomplete("stage2_names: constant deterministic name required")
        if tuple(self.pending) or type(self.max_reports) is not int or self.max_reports != 1:
            raise IntegrationIncomplete("stage2_window: no pending work and at most one report")
        if any(c <= 0 for candidate in s.candidates for c in candidate[0]):
            raise IntegrationIncomplete("stage2_speed: strictly positive speeds required")
        try:
            work = _fraction(self.work, "known work", positive=True)
            q = _fraction(self.q, "jump rate", positive=True)
        except (ValueError, TypeError) as exc:
            raise IntegrationIncomplete("stage2_known: positive known work and jump rate required") from exc
        merged = {}
        for candidate, weight in zip(s.candidates, s.weights):
            pair = candidate[0]
            merged[pair] = merged.get(pair, Fraction(0)) + weight
        pairs, weights = tuple(merged), tuple(merged.values())
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "q", _number(q, "jump rate"))
        object.__setattr__(self, "pending", ())
        object.__setattr__(self, "pairs", pairs)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "kernels", tuple(OneJumpKernel(q=q, work=work, speeds=p) for p in pairs))


@dataclass(frozen=True, slots=True)
class ExactCompletion:
    time_s: Fraction

    def __post_init__(self):
        object.__setattr__(self, "time_s", _fraction(self.time_s, "report time"))


@dataclass(frozen=True, slots=True)
class NoCompletion:
    horizon_s: Fraction

    def __post_init__(self):
        object.__setattr__(self, "horizon_s", _fraction(self.horizon_s, "horizon"))


@dataclass(frozen=True, slots=True)
class PotentialParts:
    laws: float
    state: float

    @property
    def total(self):
        return self.laws + self.state


@dataclass(frozen=True, slots=True)
class OneJumpBelief:
    """A fresh derived joint posterior from the model and one observation.

    Keys are (speed pair, reported state); missed keys have state None.
    Logs keep structural zero distinct from small positive mass. No saved
    marginal is used to rebuild this posterior. The target omits jump time
    and component labels; nonarrival adds no state target (§3-3).
    """

    model: OneJumpModel
    observation: ExactCompletion | NoCompletion
    basis: str = field(init=False)
    log_evidence: float = field(init=False)
    log_joint: object = field(init=False, repr=False)

    def __post_init__(self):
        m, obs = self.model, self.observation
        if not isinstance(m, OneJumpModel):
            raise ValueError("stage2: expected OneJumpModel")
        if isinstance(obs, ExactCompletion):
            atom = any(k.t0 == obs.time_s for k in m.kernels)
            basis = "atom" if atom else "density"
            terms = {}
            for pair, p, k in zip(m.pairs, m.weights, m.kernels):
                likelihood = (k.atom().log_state_mass if k.t0 == obs.time_s else (-math.inf, -math.inf)) if atom else (-math.inf, k.log_density(obs.time_s))
                for state, log_k in enumerate(likelihood):
                    terms[pair, state] = _log_fraction(p) + log_k
        elif isinstance(obs, NoCompletion):
            basis = "not_arrived"
            terms = {(pair, None): _log_fraction(p) + _sum_logs(k.not_arrived_log_states(obs.horizon_s))
                     for pair, p, k in zip(m.pairs, m.weights, m.kernels)}
        else:
            raise IntegrationIncomplete("stage2_observation: one exact report or certified nonarrival required")
        evidence = _sum_logs(terms.values())
        if evidence == -math.inf:
            raise ModelViolation("stage2: observation has structural zero likelihood")
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "log_evidence", evidence)
        object.__setattr__(self, "log_joint", MappingProxyType({key: v - evidence for key, v in terms.items()}))

    def target_marginal(self):
        return MappingProxyType({key: _exp(v) for key, v in self.log_joint.items()})

    def speed_marginal(self):
        return MappingProxyType({pair: _exp(_sum_logs(v for (p, _), v in self.log_joint.items() if p == pair))
                                 for pair in self.model.pairs})

    def root_potential(self):
        """Chain-rule KL against the root forecast at this same r, not H."""
        speed_logs = {pair: _sum_logs(v for (p, _), v in self.log_joint.items() if p == pair)
                      for pair in self.model.pairs}
        prior = dict(zip(self.model.pairs, self.model.weights))
        laws = math.fsum(_exp(v) * (v - _log_fraction(prior[pair]))
                         for pair, v in speed_logs.items() if v != -math.inf)
        state = 0.0
        if isinstance(self.observation, ExactCompletion):
            qr = self.model.kernels[0]._qt(self.observation.time_s)
            root = (-qr, _log_one_minus_exp(qr))
            state = math.fsum(_exp(v) * (v - speed_logs[pair] - root[s])
                              for (pair, s), v in self.log_joint.items() if v != -math.inf)
        return PotentialParts(max(0.0, laws), max(0.0, state))

    def current_state_given_nonarrival(self):
        """Filtering diagnostic only; not included in root_potential."""
        if not isinstance(self.observation, NoCompletion):
            raise IntegrationIncomplete("stage2_filter: a nonarrival observation is required")
        h = self.observation.horizon_s
        logs = [_sum_logs(_log_fraction(p) + k.not_arrived_log_states(h)[s]
                          for p, k in zip(self.model.weights, self.model.kernels)) for s in (0, 1)]
        return tuple(_exp(v - self.log_evidence) for v in logs)


def condition(model, observation):
    """Condition the root, creating a new derived belief; no general history."""
    return OneJumpBelief(model, observation)


@dataclass(frozen=True, slots=True)
class AtomicBranch:
    time_s: Fraction
    log_mass: float
    child: OneJumpBelief


@dataclass(frozen=True, slots=True)
class ContinuousBranch:
    lower_s: Fraction
    upper_s: Fraction
    active: tuple[int, ...]
    log_mass: float


@dataclass(frozen=True, slots=True)
class OneJumpBranches:
    """§3-10 branches: disjoint reference-measure pieces, marginalized atoms.

    Integrated masses have closed forms (zero quadrature error). Their sum
    is returned explicitly; floating roundoff is separate from error bounds.
    """

    model: OneJumpModel
    horizon_s: Fraction
    atoms: tuple[AtomicBranch, ...]
    continuous: tuple[ContinuousBranch, ...]
    not_arrived: OneJumpBelief | None
    normalization: float

    @property
    def normalization_bounds(self):
        # For each law, transformed T<t0 + T>=t0 is exhaustive, and R<=H
        # versus R>H is a disjoint partition. The analytic total is exactly 1.
        # normalization above is its floating evaluation, with roundoff excluded.
        return ProbabilityBounds(Fraction(1), Fraction(1))


def branches(model, horizon_s):
    h = _fraction(horizon_s, "horizon")
    atoms = []
    for r in sorted({k.t0 for k in model.kernels if k.t0 <= h}):
        child = condition(model, ExactCompletion(r))
        atoms.append(AtomicBranch(r, child.log_evidence, child))
    cuts = sorted({Fraction(0), h} | {t for k in model.kernels for t in (k.t0, k.t1) if 0 < t < h})
    continuous = []
    for a, b in zip(cuts, cuts[1:]):
        middle = (a + b) / 2
        active = tuple(i for i, k in enumerate(model.kernels)
                       if k.slope and min(k.t0, k.t1) < middle < max(k.t0, k.t1))
        if active:
            mass = _sum_logs(_log_fraction(model.weights[i]) + model.kernels[i].continuous_log_mass(a, b)
                             for i in active)
            continuous.append(ContinuousBranch(a, b, active, mass))
    miss_log = _sum_logs(_log_fraction(p) + _sum_logs(k.not_arrived_log_states(h))
                         for p, k in zip(model.weights, model.kernels))
    missed = condition(model, NoCompletion(h)) if miss_log != -math.inf else None
    mass = math.fsum([_exp(a.log_mass) for a in atoms] + [_exp(c.log_mass) for c in continuous]
                     + ([] if missed is None else [_exp(missed.log_evidence)]))
    return OneJumpBranches(model, h, tuple(atoms), tuple(continuous), missed, mass)


def _fourth_derivative_bounds(model, piece):
    """Conservative analytic bounds for composite Simpson, piece by piece.

    f_j=p_j*k_j is exponential with slope b_j. If B=max|b_j|,
    |p^(n)|<=p*B^n. Differentiating log p gives bounds B,2B²,6B³,26B⁴.
    Thus |(p log p)''''|<=p_max*B⁴*(|log p|+66).
    (f_j log k_j)''''=f_j*b_j⁴*(log k_j+4).
    The state term is -p log(1-exp(-q*r)); its first four log derivatives
    decrease in magnitude with r and have the explicit bounds below.
    """
    log_min, log_max, law_terms, slopes = [], [], [], []
    for i in piece.active:
        k = model.kernels[i]
        ends = (k._density_extension(piece.lower_s), k._density_extension(piece.upper_s))
        p_log = _log_fraction(model.weights[i])
        log_min.append(p_log + min(ends))
        log_max.append(p_log + max(ends))
        b = abs(k.q / _number(k.slope, "density slope"))
        slopes.append(b)
        law_terms.append(_exp(p_log + max(ends)) * b**4 * (max(map(abs, ends)) + 4))
    p_min_log, p_max_log = _sum_logs(log_min), _sum_logs(log_max)
    p_max, B = _exp(p_max_log), max(slopes)
    law = math.fsum(law_terms) + p_max * B**4 * (max(abs(p_min_log), abs(p_max_log)) + 66)
    q = model.q
    x = model.kernels[0]._qt(piece.lower_s)
    z, v = _exp(-x), -math.expm1(-x)
    state = p_max * (B**4 * -math.log(v) + 4*B**3*q*z/v
                     + 6*B**2*q**2*z/v**2 + 4*B*q**3*z*(1+z)/v**3
                     + q**4*z*(1+4*z+z*z)/v**4)
    if not math.isfinite(law) or not math.isfinite(state) or law <= 0 or state <= 0:
        raise NumericalRange("stage2: derivative bound outside numerical range")
    return law, state


def _integrands(model, piece, r):
    logs_k = [model.kernels[i]._density_extension(r) for i in piece.active]
    logs_f = [_log_fraction(model.weights[i]) + lk for i, lk in zip(piece.active, logs_k)]
    log_p = _sum_logs(logs_f)
    laws = math.fsum(_exp(lf) * (lk - log_p) for lf, lk in zip(logs_f, logs_k))
    state = -_exp(log_p) * _log_one_minus_exp(model.kernels[0]._qt(r))
    return laws, state


@dataclass(frozen=True, slots=True)
class OneJumpInformation:
    total: InformationBounds
    laws: InformationBounds
    state: InformationBounds
    not_arrived_probability: float
    not_arrived_potential: float
    normalization: float
    pieces: int
    nodes: int


def information(model, horizon_s, *, tolerance, node_budget):
    """Expected root potential, including law information on the missed branch.

    Split at all support endpoints/atoms/deadline. Composite Simpson uses
    |error| <= L4*(b-a)^5/(180*n^4) for even n. Analytical derivative bounds
    are recomputed per piece; quantity.py's polynomial bounds are not used.
    Failure to meet the requested width/budget raises IntegrationIncomplete.
    Nodes are integration variables only. Total's midpoint is its representative.
    """
    tol = _number(_fraction(tolerance, "tolerance", positive=True), "tolerance")
    if type(node_budget) is not int or node_budget < 0:
        raise ValueError("stage2: nonnegative integer node budget required")
    tree = branches(model, horizon_s)
    law_values, state_values = [], []
    for atom in tree.atoms:
        parts = atom.child.root_potential()
        p = _exp(atom.log_mass)
        law_values.append(p * parts.laws)
        state_values.append(p * parts.state)
    miss_p = miss_b = 0.0
    if tree.not_arrived is not None:
        miss_p = _exp(tree.not_arrived.log_evidence)
        miss_b = tree.not_arrived.root_potential().laws
        law_values.append(miss_p * miss_b)
    law_errors, state_errors, nodes = [], [], 0
    goal = tol / (8 * max(1, len(tree.continuous)))
    if goal == 0:
        raise NumericalRange("stage2: requested tolerance outside numerical range")
    for piece in tree.continuous:
        try:
            law_bound, state_bound = _fourth_derivative_bounds(model, piece)
            length = _number(piece.upper_s - piece.lower_s, "piece length")
            coefficients = (law_bound * length**5 / 180, state_bound * length**5 / 180)
            if any(c <= 0 or not math.isfinite(c) for c in coefficients):
                raise NumericalRange("stage2: positive error bound outside numerical range")
            required = (max(coefficients) / goal)**0.25
            if not math.isfinite(required):
                raise NumericalRange("stage2: quadrature size outside numerical range")
            n = max(2, 2 * math.ceil(required / 2))
            # Integer ceil and final check avoid choosing an insufficient mesh.
            while max(coefficients) / n**4 > goal:
                n += 2
        except (OverflowError, ZeroDivisionError) as exc:
            raise NumericalRange("stage2: derivative bound outside numerical range") from exc
        if nodes + n + 1 > node_budget:
            raise IntegrationIncomplete("stage2_quadrature_budget: requested error not reached")
        # Stream each scalar sum; do not retain n sampled posteriors/values.
        def weighted_values(part):
            for i in range(n + 1):
                r = piece.lower_s + (piece.upper_s - piece.lower_s) * Fraction(i, n)
                weight = 1 if i in (0, n) else (4 if i % 2 else 2)
                yield weight * _integrands(model, piece, r)[part]
        law_values.append(length * math.fsum(weighted_values(0)) / (3*n))
        state_values.append(length * math.fsum(weighted_values(1)) / (3*n))
        law_errors.append(coefficients[0] / n**4)
        state_errors.append(coefficients[1] / n**4)
        nodes += n + 1
    law, state = math.fsum(law_values), math.fsum(state_values)
    le, se = math.fsum(law_errors), math.fsum(state_errors)
    laws = InformationBounds(max(0.0, law - le), max(0.0, law + le))
    states = InformationBounds(max(0.0, state - se), max(0.0, state + se))
    if ((le > 0 and laws.lower == laws.upper)
            or (se > 0 and states.lower == states.upper)):
        raise NumericalRange("stage2: positive integration error cannot be represented by bounds")
    total = InformationBounds(laws.lower + states.lower, laws.upper + states.upper)
    if le+se > 0 and total.lower == total.upper:
        raise NumericalRange("stage2: positive total integration error cannot be represented by bounds")
    if total.upper - total.lower > tol:
        raise IntegrationIncomplete("stage2_quadrature_width: requested error not reached")
    return OneJumpInformation(total, laws, states, miss_p, miss_b,
                              tree.normalization, len(tree.continuous), nodes)
