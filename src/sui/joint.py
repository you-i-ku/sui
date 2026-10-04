"""S4b-1c §6-3 (i)-1: 単一 exact・ρ=1 の結合の事後。

公開の Agent/記録にはつながない。モデル、試み、事実、整数 ns の文脈
から毎回派生する。Q の列が出発状態、行が到着状態、単位は 1/秒。
遷移の一様化の尾と情報の級数の尾を包む。浮動小数点の丸めは別。
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product
import math
from types import MappingProxyType

import numpy as np
from scipy.special import digamma

from .inference import (ModelViolation, NumericalRange, _s4d_log_matmul,
                        _s4d_poisson_log, _s4d_poisson_tail)
from .lookahead import OutsideEvaluationType
from .model import _array, _generator
from .progress import CompletionSpec, INFINITE_WORK, _fraction
from .quantity import IntegrationIncomplete, PhiSeries, SimplexPolynomial, _log_fraction
from .values import InformationBounds, MeasureSpec


def _ns(value):
    if type(value) is not int or value < 0:
        raise IntegrationIncomplete("stage1_time: integer ns must identify the true time")
    return value


def _known_generator(value):
    Q = _array(np.asarray(value), "Q", 2)
    if Q.shape[0] != Q.shape[1]:
        raise ValueError("joint: Q must be square")
    # 旧モデルは静的な世界を Q=None と書くため _generator が0行列を
    # 断る。段1の既知 Q=0 は正当な帰着なので、ここで明示して受ける。
    return Q if not np.any(Q) else _generator(Q)


@dataclass(frozen=True, slots=True)
class WorkPrior:
    """有限原子の αG₀。整数の仕事量は ρ=1 での所要 ns。∞ は別値。"""

    alpha: Fraction
    points: tuple

    def __post_init__(self):
        alpha = _fraction(self.alpha, "work alpha", positive=True)
        points = tuple((w, _fraction(m, "base mass")) for w, m in self.points)
        if not points or len({w for w, _ in points}) != len(points) or sum(m for _, m in points) != 1:
            raise ValueError("work prior: expected distinct normalized atoms")
        for w, _ in points:
            if w is not INFINITE_WORK:
                _ns(w)
        points = tuple(sorted(((w, m) for w, m in points if m),
                              key=lambda p: (p[0] is INFINITE_WORK, 0 if p[0] is INFINITE_WORK else p[0])))
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "points", points)


@dataclass(frozen=True, slots=True)
class KnownWorkLaw:
    """Known finite atomic law. Independent draws, without a learnable F or alpha."""
    points: tuple

    def __post_init__(self):
        points = tuple((w, _fraction(m, "known work mass")) for w, m in self.points)
        if not points or len({w for w, _ in points}) != len(points) or sum(m for _, m in points) != 1:
            raise ValueError("known work: distinct normalized atoms required")
        for w, _ in points:
            if w is not INFINITE_WORK:
                _ns(w)
        object.__setattr__(self, "points", tuple(sorted(((w, m) for w, m in points if m),
            key=lambda p: (p[0] is INFINITE_WORK, 0 if p[0] is INFINITE_WORK else p[0]))))


@dataclass(frozen=True, slots=True)
class NameSpec:
    """状態ごとの列。learnable=True は Dirichlet の擬似回数、False は確率。"""

    columns: tuple
    learnable: bool
    measures: str

    def __post_init__(self):
        columns = tuple(tuple(_fraction(v, "name column") for v in c) for c in self.columns)
        if not columns or not columns[0] or any(len(c) != len(columns[0]) or not sum(c) for c in columns):
            raise ValueError("names: nonempty equal-size positive-total columns required")
        if type(self.learnable) is not bool or self.measures not in ("start", "report"):
            raise ValueError("names: expected learnable flag and start/report")
        if not self.learnable and any(sum(c) != 1 for c in columns):
            raise ValueError("fixed names: columns must be probabilities")
        object.__setattr__(self, "columns", columns)


@dataclass(frozen=True, slots=True, kw_only=True)
class JointModel:
    """試験から直接渡すモデル。事前・Q・λ・速さに既定値を置かない。"""

    completion: CompletionSpec
    work: Mapping[str, WorkPrior]
    names: Mapping[str, NameSpec]
    outcomes: tuple[str, ...]
    initial: tuple
    Q: object = field(repr=False)
    measure: MeasureSpec
    w_star_ns: int
    allow_zero_work: bool = False

    def __post_init__(self):
        spec = self.completion
        if not isinstance(spec, CompletionSpec):
            raise ValueError("joint: expected CompletionSpec")
        if (spec.work_unit, spec.time_unit, spec.speed_unit) != ("ns", "ns", "ns/ns"):
            raise IntegrationIncomplete("stage1_units: work must be unit-speed integer ns")
        if any(r != 1 for c in spec.candidates for row in c for r in row):
            raise IntegrationIncomplete("stage1_speed: only rho identically one is certified")
        if not isinstance(self.measure, MeasureSpec) or self.measure.name != "exact" or self.measure.version != "1" or self.measure.params:
            raise IntegrationIncomplete("stage1_measure: a single exact process is required")
        if type(self.w_star_ns) is not int or self.w_star_ns <= 0:
            raise IntegrationIncomplete("stage1_lower_work: positive w_star is required")
        work, names = dict(self.work), dict(self.names)
        if set(work) != set(spec.actions) or set(names) != set(spec.actions):
            raise ValueError("joint: one work and name prior per action required")
        if any(not isinstance(p, (WorkPrior, KnownWorkLaw)) for p in work.values()) or any(not isinstance(p, NameSpec) for p in names.values()):
            raise ValueError("joint: invalid work or name prior")
        if type(self.allow_zero_work) is not bool:
            raise ValueError("joint: allow_zero_work must be a boolean")
        # Finite history / Z-conditioned one_step may contain zero work. The
        # recursive evaluator separately requires a positive duration bound.
        if not self.allow_zero_work and any(w is not INFINITE_WORK and w < self.w_star_ns for p in work.values() for w, _ in p.points):
            if any(p.points == ((0, Fraction(1)),) for p in work.values()):
                raise OutsideEvaluationType("stage1_zero_work: positive lower work is required")
            raise IntegrationIncomplete("stage1_lower_work: atom below w_star")
        outcomes = tuple(self.outcomes)
        if not outcomes or any(type(o) is not str or not o for o in outcomes) or len(set(outcomes)) != len(outcomes):
            raise ValueError("joint: expected unique outcome names")
        if any(len(n.columns) != len(spec.states) or any(len(c) != len(outcomes) for c in n.columns) for n in names.values()):
            raise ValueError("joint: wrong name table dimensions")
        initial = tuple(_fraction(p, "initial state") for p in self.initial)
        if len(initial) != len(spec.states) or sum(initial) != 1:
            raise ValueError("joint: expected normalized initial state probabilities")
        Q = _known_generator(self.Q)
        if Q.shape != (len(spec.states), len(spec.states)):
            raise ValueError("joint: wrong Q dimensions")
        Q.setflags(write=False)
        object.__setattr__(self, "Q", Q)
        object.__setattr__(self, "work", MappingProxyType({a: work[a] for a in spec.actions}))
        object.__setattr__(self, "names", MappingProxyType({a: names[a] for a in spec.actions}))
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "initial", initial)


@dataclass(frozen=True, slots=True)
class Attempt:
    label: str
    action: str
    start_ns: int

    def __post_init__(self):
        if type(self.label) is not str or not self.label or type(self.action) is not str:
            raise ValueError("attempt: expected label and action")
        _ns(self.start_ns)


@dataclass(frozen=True, slots=True)
class Completed:
    """本当の完了 ns。None は読めた名前の証拠が無いことだけを表す。

    取り込み済みで名前を読めなかった場合も None になる。未取り込みの
    O₀ であることは、この値から推測せず評価の入力で別に指定する。
    """

    label: str
    report_ns: int
    outcome: str | None

    def __post_init__(self):
        _ns(self.report_ns)
        if type(self.label) is not str or not self.label or (self.outcome is not None and type(self.outcome) is not str):
            raise ValueError("completed: invalid label or outcome")


@dataclass(frozen=True, slots=True)
class NotArrived:
    """未着。未来の一括取り込み後は >、実履歴の外の確かめは >=。"""

    label: str
    until_ns: int
    inclusive: bool = False

    def __post_init__(self):
        _ns(self.until_ns)
        if type(self.inclusive) is not bool:
            raise ValueError("not arrived: inclusive must be boolean")
        if type(self.label) is not str or not self.label:
            raise ValueError("not arrived: expected label")


@dataclass(frozen=True, slots=True)
class ProbabilityBounds:
    lower: Fraction
    upper: Fraction


@dataclass(frozen=True, slots=True)
class JointComponent:
    """対象の状態と全 Dirichlet の結合。成分の識別子は情報の対象ではない。"""

    states: tuple[int, ...]
    parameters: tuple[tuple[Fraction, ...], ...]
    weight: Fraction


class _DirichletMeasure:
    def __init__(self, model):
        groups, keys, work, names = [], [], {}, {}
        for action in model.completion.actions:
            p = model.work[action]
            if isinstance(p, KnownWorkLaw):
                work[action] = None
                continue
            work[action] = len(groups)
            groups.append(tuple(p.alpha * m for _, m in p.points))
            keys.append(("work", action))
        for action, spec in model.names.items():
            if spec.learnable:
                for state, column in enumerate(spec.columns):
                    group = len(groups)
                    active = tuple(i for i, v in enumerate(column) if v)
                    groups.append(tuple(column[i] for i in active))
                    keys.append(("names", action, state))
                    for coordinate, outcome in enumerate(active):
                        names[action, state, outcome] = (group, coordinate)
        self.beta, self.keys = tuple(groups), tuple(keys)
        self.sizes = tuple(map(len, groups))
        self.offsets = tuple(sum(self.sizes[:i]) for i in range(len(groups)))
        self.work, self.names = work, names
        self._moments = {}

    def moment(self, counts):
        if counts in self._moments:
            return self._moments[counts]
        value = Fraction(1)
        for beta, offset, size in zip(self.beta, self.offsets, self.sizes):
            group = counts[offset:offset + size]
            for b, n in zip(beta, group):
                for k in range(n):
                    value *= b + k
            for k in range(sum(group)):
                value /= sum(beta) + k
        self._moments[counts] = value
        return value

    def expectation(self, polynomial):
        return sum((c * self.moment(k) for k, c in polynomial.coefficients.items()), Fraction(0))

    def parameters(self, counts):
        return tuple(tuple(b + n for b, n in zip(beta, counts[o:o + s]))
                     for beta, o, s in zip(self.beta, self.offsets, self.sizes))


def transition_bounds(Q, dt_ns, *, tolerance):
    """e^(Q*dt_ns/1e9) の対数の下界と、要素ごとの相対尾の対数上界。

    構造の0は到達可能性で判定する。返す κ により P_low <= P <=
    exp(κ) P_low。丸めを含めない。要求の精度まで一様化を続ける。
    """
    _ns(dt_ns)
    tolerance = float(_fraction(tolerance, "transition tolerance", positive=True))
    if not math.isfinite(tolerance) or tolerance >= 1:
        raise ValueError("transition: expected tolerance in (0,1)")
    Q = _known_generator(Q)
    size = len(Q)
    identity = np.full((size, size), -math.inf)
    np.fill_diagonal(identity, 0.)
    if dt_ns == 0 or not np.any(Q):
        return identity, 0.
    try:
        dt = dt_ns / 1e9  # Q は 1/秒。仕事量と記録は整数 ns。
    except OverflowError as exc:
        raise NumericalRange("joint transition: time exceeds numerical range") from exc
    rate = float(-np.diag(Q).min())
    mean = rate * dt
    if mean <= 0 or not math.isfinite(mean):
        raise NumericalRange("joint transition: Poisson mean cannot be represented")
    log_mean = math.log(rate) + math.log(dt)
    log_P = np.full_like(Q, -math.inf)
    positive = Q > 0
    log_P[positive] = np.log(Q[positive]) - math.log(rate)
    for i in range(size):
        if rate + Q[i, i] > 0:
            log_P[i, i] = math.log(rate + Q[i, i]) - math.log(rate)
    reachable = positive | np.eye(size, dtype=bool)
    for i in range(size):
        reachable |= reachable[:, i, None] & reachable[None, i, :]
    partial, power = np.full_like(Q, -math.inf), identity
    k = 0
    while True:
        partial = np.logaddexp(partial, power + _s4d_poisson_log(k, mean, log_mean))
        tail = _s4d_poisson_tail(k, mean, log_mean)
        if np.all(np.isfinite(partial[reachable])):
            delta = tail - float(partial[reachable].min())
            if delta <= math.log(tolerance):
                return partial, math.log1p(math.exp(delta))
        power = _s4d_log_matmul(log_P, power)
        k += 1


def _exp_fraction(log_value):
    if log_value == -math.inf:
        return Fraction(0)
    value = math.exp(log_value)
    if not value or not math.isfinite(value):
        raise NumericalRange("joint: positive path probability cannot be represented")
    return Fraction(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class JointBelief:
    """§3-10。入力の事実から作る派生物。condition は新しい派生物を返す。"""

    model: JointModel
    attempts: tuple[Attempt, ...]
    facts: tuple[Completed | NotArrived, ...]
    origin_ns: int
    observed_ns: int
    transition_tolerance: float
    history_kernel: object = field(default=None, repr=False)

    def __post_init__(self):
        _ns(self.origin_ns)
        _ns(self.observed_ns)
        if self.observed_ns < self.origin_ns:
            raise ValueError("joint: observed time precedes origin")
        tolerance = float(_fraction(self.transition_tolerance, "transition tolerance", positive=True))
        if not 0 < tolerance < 1:
            raise ValueError("joint: expected transition tolerance in (0,1)")
        attempts = tuple(sorted(self.attempts, key=lambda a: a.label))
        if len({a.label for a in attempts}) != len(attempts):
            raise ValueError("joint: duplicate attempt")
        if any(a.action not in self.model.work or a.start_ns < self.origin_ns or a.start_ns > self.observed_ns for a in attempts):
            raise ValueError("joint: unknown action or attempt outside time context")
        by_label = {a.label: a for a in attempts}
        if any(not isinstance(f, (Completed, NotArrived)) for f in self.facts):
            raise ValueError("joint: expected exact completion or guaranteed nonarrival facts")
        facts = tuple(sorted(set(self.facts), key=lambda f: (f.label, type(f).__name__, repr(f))))
        for f in facts:
            if f.label not in by_label:
                raise ValueError("joint: fact for unknown attempt")
            t = f.report_ns if isinstance(f, Completed) else f.until_ns
            if not by_label[f.label].start_ns <= t <= self.observed_ns:
                raise ValueError("joint: fact outside time context")
            if isinstance(f, Completed) and f.outcome is not None and f.outcome not in self.model.outcomes:
                raise ValueError("joint: unknown outcome")
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "transition_tolerance", tolerance)

    def condition(self, facts, *, observed_ns, attempts=()):
        return JointBelief(model=self.model, attempts=self.attempts + tuple(attempts),
                          facts=self.facts + tuple(facts), origin_ns=self.origin_ns,
                          observed_ns=observed_ns, transition_tolerance=self.transition_tolerance,
                          history_kernel=self.history_kernel)

    def _times(self):
        # 全割り当てで固定した有限の列。補助の時刻は対象へ自動登録しない。
        times = {self.origin_ns}
        for a in self.attempts:
            times.add(a.start_ns)
            times.update(a.start_ns + w for w, _ in self.model.work[a.action].points if w is not INFINITE_WORK)
        return times

    def _enumerate(self, times, measure, *, transition_tolerance=None):
        model = self.model
        tolerance = self.transition_tolerance if transition_tolerance is None else transition_tolerance
        paths = [((s,), p) for s, p in enumerate(model.initial) if p]
        log_error = 0.
        for before, after in zip(times, times[1:]):
            matrix, error = transition_bounds(model.Q, after - before, tolerance=tolerance / max(1, len(times) - 1))
            log_error += error
            paths = [(path + (s,), p * _exp_fraction(matrix[s, path[-1]]))
                     for path, p in paths for s in range(len(model.initial)) if math.isfinite(matrix[s, path[-1]])]
        # 一様化の部分和は、本来は全道で質量 <= 1 の下界。しかし
        # exp(log P) の丸めを Fraction に固定すると、和がわずかに1を
        # 超えることがある。SimplexPolynomial は Bernstein の確率を
        # 厳密に検査するので、状態の道の共通質量を先に補正する。
        # 全成分へ同じ係数を掛け、道・仕事量・名前の相対重みを保つ。
        # 縮小係数も相対尾へ積む。それ以外の丸めは従来どおり別扱い。
        path_mass = sum((p for _, p in paths), Fraction(0))
        if path_mass > 1:
            paths = [(path, p / path_mass) for path, p in paths]
            try:
                excess = float(path_mass - 1)
            except OverflowError as exc:
                raise NumericalRange("joint: path-mass correction exceeds numerical range") from exc
            if not excess or not math.isfinite(excess):
                raise NumericalRange("joint: positive path-mass correction cannot be represented")
            log_error += math.log1p(excess)
        index = {t: i for i, t in enumerate(times)}
        constraints = defaultdict(list)
        for f in self.facts:
            constraints[f.label].append(f)
        rows = []
        choices = [range(len(model.work[a.action].points)) for a in self.attempts]
        for assignment in product(*choices):
            counts = [0] * sum(measure.sizes)
            known_weight = Fraction(1)
            emissions = []
            possible = True
            for a, j in zip(self.attempts, assignment):
                work = model.work[a.action].points[j][0]
                report = None if work is INFINITE_WORK else a.start_ns + work
                group = measure.work[a.action]
                if group is None:
                    known_weight *= model.work[a.action].points[j][1]
                else:
                    counts[measure.offsets[group] + j] += 1
                seen_names = set()
                for f in constraints[a.label]:
                    if isinstance(f, NotArrived):
                        possible &= report is None or (report >= f.until_ns if f.inclusive else report > f.until_ns)
                    else:
                        possible &= report == f.report_ns
                        if f.outcome is not None:
                            seen_names.add(f.outcome)
                if len(seen_names) > 1:
                    possible = False
                if seen_names:
                    ns = a.start_ns if model.names[a.action].measures == "start" else report
                    emissions.append((a.action, model.outcomes.index(next(iter(seen_names))), ns))
            if not possible:
                continue
            if self.history_kernel is not None:
                # K retains the real event kinds, causal positions and uptake
                # order INSIDE the work-allocation sum. Future batch facts above
                # use a separate strict boundary, never a second history K.
                work_by_label = {a.label: model.work[a.action].points[j][0]
                                 for a, j in zip(self.attempts, assignment)}
                durations = {a.attempt: None if work_by_label[str(a.attempt)] is INFINITE_WORK
                             else work_by_label[str(a.attempt)] for a in self.history_kernel.attempts}
                known_weight *= self.history_kernel(durations)
                if not known_weight:
                    continue
            for path, weight in paths:
                updated, coefficient = counts.copy(), weight * known_weight
                for action, outcome, ns in emissions:
                    state = path[index[ns]]
                    spec = model.names[action]
                    if spec.learnable:
                        coordinate = measure.names.get((action, state, outcome))
                        if coordinate is None:
                            coefficient = Fraction(0)
                            break
                        group, j = coordinate
                        updated[measure.offsets[group] + j] += 1
                    else:
                        coefficient *= spec.columns[state][outcome]
                if coefficient:
                    rows.append((path, tuple(updated), assignment, coefficient))
        return rows, log_error

    def target_marginal(self, times=(), *, allow_impossible=False):
        """(Θ,全F,対象の状態)へ先に周辺化。進行中の割り当ては対象にしない。"""
        return target_marginal(self, times, allow_impossible=allow_impossible)

    def predictive(self, attempt, *, until_ns):
        """同じ試みの (完了ns,名前) の結合。窓外は (None,None) に合算する。"""
        _ns(until_ns)
        existing = next((a for a in self.attempts if a.label == attempt.label), None)
        if existing is not None and existing != attempt:
            raise ValueError("predictive: changed an existing attempt")
        base = self if existing is not None else self.condition((), observed_ns=max(self.observed_ns, attempt.start_ns), attempts=(attempt,))
        if until_ns < base.observed_ns:
            raise ValueError("predictive: horizon precedes the observed context")
        marginal = base.target_marginal(())
        denominator = marginal.evidence
        result, bounds = {}, {}
        reports = tuple(attempt.start_ns + w for w, _ in self.model.work[attempt.action].points
                        if w is not INFINITE_WORK and attempt.start_ns + w <= until_ns)
        for report in reports:
            for outcome in self.model.outcomes:
                child = base.condition((Completed(attempt.label, report, outcome),), observed_ns=until_ns)
                num = child.target_marginal((), allow_impossible=True)
                p = num.evidence / denominator
                result[report, outcome] = p
                bounds[report, outcome] = _probability_bounds(p, max(marginal.log_error, num.log_error))
        child = base.condition((NotArrived(attempt.label, until_ns),), observed_ns=until_ns)
        num = child.target_marginal((), allow_impossible=True)
        p = num.evidence / denominator
        result[None, None] = p
        bounds[None, None] = _probability_bounds(p, max(marginal.log_error, num.log_error))
        return JointPrediction(MappingProxyType(result), MappingProxyType(bounds))

    def pending_work(self, label):
        """未着で絞った、開始時の同じ仕事量の周辺 (新しいFの標本ではない)。"""
        attempt = next((a for a in self.attempts if a.label == label), None)
        if attempt is None:
            raise ValueError("pending work: unknown attempt")
        measure = _DirichletMeasure(self.model)
        rows, _ = self._enumerate(tuple(sorted(self._times())), measure)
        table = defaultdict(Fraction)
        position = self.attempts.index(attempt)
        for _, counts, assignment, coefficient in rows:
            work = self.model.work[attempt.action].points[assignment[position]][0]
            table[work] += coefficient * measure.moment(counts)
        evidence = sum(table.values())
        if not evidence:
            raise ModelViolation("joint: facts have zero probability")
        return MappingProxyType({w: p / evidence for w, p in table.items()})

    def root_potential(self, root, *, times, tolerance, series_budget):
        return root_potential(root, self, times=times, tolerance=tolerance, series_budget=series_budget)


@dataclass(frozen=True, slots=True)
class JointPrediction:
    probabilities: Mapping
    bounds: Mapping


@dataclass(frozen=True, slots=True)
class TargetMarginal:
    times: tuple[int, ...]
    components: tuple[JointComponent, ...]
    group_keys: tuple
    evidence: Fraction
    evidence_bounds: ProbabilityBounds
    log_error: float
    _polynomials: Mapping = field(repr=False)
    _measure: object = field(repr=False)

    def state_probabilities(self):
        result = defaultdict(Fraction)
        for c in self.components:
            result[c.states] += c.weight
        return MappingProxyType(dict(sorted(result.items())))

    def state_bounds(self):
        return MappingProxyType({s: _probability_bounds(p, self.log_error)
                                 for s, p in self.state_probabilities().items()})

    def mean(self, key):
        group = self.group_keys.index(key)
        result = [Fraction(0)] * len(self._measure.beta[group])
        for component in self.components:
            beta = component.parameters[group]
            for j, value in enumerate(beta):
                result[j] += component.weight * value / sum(beta)
        return tuple(result)


def _probability_bounds(p, log_error):
    if not p or log_error == 0:
        return ProbabilityBounds(p, p)
    factor = 1 + Fraction(math.expm1(log_error))
    return ProbabilityBounds(p / factor, min(Fraction(1), p * factor))


def target_marginal(belief, times=(), *, allow_impossible=False, _grid=None, _transition_tolerance=None):
    times = tuple(sorted(set(_ns(t) for t in times)))
    if any(t < belief.origin_ns for t in times):
        raise ValueError("target: time precedes the state origin")
    grid = tuple(sorted(belief._times() | set(times))) if _grid is None else _grid
    measure = _DirichletMeasure(belief.model)
    rows, error = belief._enumerate(grid, measure, transition_tolerance=_transition_tolerance)
    positions = tuple(grid.index(t) for t in times)
    coefficients = defaultdict(lambda: defaultdict(Fraction))
    for path, counts, _, weight in rows:
        coefficients[tuple(path[i] for i in positions)][counts] += weight
    polynomials, entries = {}, []
    evidence = Fraction(0)
    for states, table in sorted(coefficients.items()):
        # 全試みの仕事量と観測済みの名前を同じ単項式へ。異なる列の
        # 名前の回数は斉次の次数が異なるので、Σp=1 で次数をそろえる。
        poly = SimplexPolynomial.constant(measure.sizes, 0)
        for counts, weight in sorted(table.items()):
            degrees = tuple(sum(counts[o:o + s]) for o, s in zip(measure.offsets, measure.sizes))
            poly = poly.add(SimplexPolynomial(measure.sizes, degrees, {counts: weight}))
            mass = weight * measure.moment(counts)
            entries.append((states, measure.parameters(counts), mass))
            evidence += mass
        polynomials[states] = poly.reduced()
    if not evidence and not allow_impossible:
        raise ModelViolation("joint: facts have zero probability")
    components = tuple(JointComponent(s, beta, mass / evidence) for s, beta, mass in entries) if evidence else ()
    upper = min(Fraction(1), evidence * (1 + Fraction(math.expm1(error)))) if error else evidence
    return TargetMarginal(times, components, measure.keys, evidence, ProbabilityBounds(evidence, upper),
                          error, MappingProxyType(polynomials), measure)


def condition(belief, facts, *, observed_ns, attempts=()):
    return belief.condition(facts, observed_ns=observed_ns, attempts=attempts)


def _digamma_gap(total, coordinate):
    gap = total - coordinate
    if not gap:
        return 0.
    # 整数の短い差は ψ(x+n)-ψ(x)=Σ1/(x+k) で桁落ちを避ける。
    if gap.denominator == 1 and gap <= 64:
        value = float(sum((1 / (coordinate + k) for k in range(int(gap))), Fraction(0)))
    else:
        try:
            a, b = float(total), float(coordinate)
        except OverflowError as exc:
            raise NumericalRange("joint: Dirichlet parameters exceed numerical range") from exc
        if not math.isfinite(a) or not math.isfinite(b) or b <= 0:
            raise NumericalRange("joint: Dirichlet parameters cannot be represented")
        value = float(digamma(a) - digamma(b))
    if value <= 0 or not math.isfinite(value):
        raise NumericalRange("joint: positive logarithmic moment disappeared")
    return value


def _log_monomial_integral(measure, numerator, denominator):
    """E[numerator*(-log denominator)]。分母が単項式なら対数モーメント。"""
    if len(denominator.coefficients) != 1:
        return None
    powers, coefficient = next(iter(denominator.coefficients.items()))
    values = []
    for counts, weight in numerator.coefficients.items():
        terms = [-_log_fraction(coefficient)]
        for beta, offset, size in zip(measure.beta, measure.offsets, measure.sizes):
            total = sum(beta) + sum(counts[offset:offset + size])
            for j, b in enumerate(beta):
                n = powers[offset + j]
                if n:
                    terms.append(n * _digamma_gap(total, b + counts[offset + j]))
        term = math.fsum(terms)
        if term:
            value = math.exp(_log_fraction(weight * measure.moment(counts)) + math.log(abs(term)))
            if not value:
                raise NumericalRange("joint: positive information cannot be represented")
            values.append(math.copysign(value, term))
    value = math.fsum(values)
    if not math.isfinite(value):
        raise NumericalRange("joint: logarithmic moment exceeds numerical range")
    return value


def _cross_bounds(measure, numerator, denominator, *, tolerance, series_budget):
    closed = _log_monomial_integral(measure, numerator, denominator)
    if closed is not None:
        return closed, closed
    power = SimplexPolynomial.constant(measure.sizes, 1)
    complement = denominator.complement()
    values = []
    for m in range(1, series_budget + 1):
        power = power.multiply(complement)
        values.append(float(measure.expectation(numerator.multiply(power))) / m)
        value = math.fsum(values)
        # numerator <= denominator, so pointwise numerator/denominator <=1.
        remainder = float(measure.expectation(power.multiply(complement))) / (m + 1)
        if remainder <= tolerance:
            return value, value + remainder
    raise IntegrationIncomplete("joint_information: cross-log series budget exhausted")


def _phi_bounds(measure, polynomial, *, tolerance, series_budget):
    closed = _log_monomial_integral(measure, polynomial, polynomial)
    if closed is not None:
        return closed, closed
    series = PhiSeries(measure, polynomial)
    for _ in range(series_budget + 1):
        value = 0. if series.log_value == -math.inf else math.exp(series.log_value)
        tail = 0. if series.log_remainder == -math.inf else math.exp(series.log_remainder)
        if tail <= tolerance:
            return value, value + tail
        series.advance()
    raise IntegrationIncomplete("joint_information: entropy series budget exhausted")


def root_potential(root, child, *, times, tolerance, series_budget):
    """根を分母に固定した共同 KL (§3-3・§3-7-2〜4)。

    成分・仕事量の割り当て・対象外の状態を先に多項式へ合算する。
    同じ派生物なら0。一般の混合は正の対数級数で包み、予算不足なら
    IntegrationIncomplete。返す区間には丸めを含めない。
    """
    tolerance = float(_fraction(tolerance, "information tolerance", positive=True))
    if not math.isfinite(tolerance) or type(series_budget) is not int or series_budget < 1:
        raise ValueError("root potential: finite tolerance and positive series budget required")
    if root.model is not child.model or root.origin_ns != child.origin_ns:
        raise ValueError("root potential: same model and state origin required")
    if not set(root.facts).issubset(child.facts) or not set(root.attempts).issubset(child.attempts):
        raise ValueError("root potential: child must extend the root facts/attempts")
    times = tuple(sorted(set(_ns(t) for t in times)))
    grid = tuple(sorted(root._times() | child._times() | set(times)))
    transition_tolerance = min(root.transition_tolerance, child.transition_tolerance)
    before = target_marginal(root, times, _grid=grid, _transition_tolerance=transition_tolerance)
    after = target_marginal(child, times, _grid=grid, _transition_tolerance=transition_tolerance)
    if (set(root.facts) == set(child.facts) or max(before.log_error, after.log_error) == 0) and all(p.ratio_to(before._polynomials[s]) == after.evidence / before.evidence
           for s, p in after._polynomials.items()) and set(before._polynomials) == set(after._polynomials):
        return InformationBounds(0., 0.)
    ratio_log = _log_fraction(before.evidence / after.evidence)
    z = float(after.evidence)
    if not z:
        raise NumericalRange("joint information: evidence cannot be represented")
    goal = tolerance * z / (8 * max(1, len(after._polynomials)))
    if not goal:
        raise NumericalRange("joint information: error budget cannot be represented")
    lows, highs, absolute = [], [], []
    measure = after._measure
    for states, poly in after._polynomials.items():
        reference = before._polynomials.get(states)
        if reference is None:
            raise ModelViolation("joint information: child outside root support")
        cross = _cross_bounds(measure, poly, reference, tolerance=goal, series_budget=series_budget)
        phi = _phi_bounds(measure, poly, tolerance=goal, series_budget=series_budget)
        lows.append(cross[0] - phi[1])
        highs.append(cross[1] - phi[0])
        absolute.append(cross[1] + phi[1])
    low, high = ratio_log + math.fsum(lows) / z, ratio_log + math.fsum(highs) / z
    # 全状態の道の事前は低い一様化の和から作った。同じ有限の道の
    # 真の重み/低い重みは [1,exp(κ)]。正規化後は [exp(-κ),exp(κ)]。
    # |KL-KL_low| <= (exp(κ)-1) E_low|log(q_low/p_low)| + 2κ。
    kappa = max(before.log_error, after.log_error)
    error = math.expm1(kappa) * (abs(ratio_log) + math.fsum(absolute) / z) + 2 * kappa
    lower, upper = max(0., low - error), max(0., high + error)
    if not math.isfinite(upper):
        raise NumericalRange("joint information: bound exceeds numerical range")
    if upper - lower > tolerance:
        raise IntegrationIncomplete("joint_information: transition/series error exceeds requested width")
    return InformationBounds(lower, upper)
