"""S4b-1c: finite mathematical recursion and exact Z-conditioned one step.

The root and X* time set stay fixed. Branches condition the joint belief on
complete records, after merging latent allocations. Seconds enter only through
joint.transition_bounds; all driving times/deadlines here are exact integer ns.
Bounds cover transition/series truncation and propagation, not general roundoff.
evaluate_stage2 uses seconds and symbolic continuous starts, never integer facts.
"""

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import product
import math

from .inference import ModelViolation, NumericalRange
from .joint import (Attempt, Completed, JointBelief, NotArrived, ProbabilityBounds,
                    _ns, _probability_bounds, root_potential, target_marginal)
from .lookahead import NoAdmissibleCandidate, OutsideEvaluationType, _policy
from .progress import INFINITE_WORK, _fraction
from .quantity import IntegrationIncomplete, _log_fraction
from .values import InformationBounds


@dataclass(frozen=True, slots=True)
class Interval:
    """Finite ordered interval, or a proven (+inf,+inf) cost/J."""
    lower: float
    upper: float

    def __post_init__(self):
        if self.lower == self.upper == math.inf:
            return
        if not math.isfinite(self.lower) or not math.isfinite(self.upper) or self.lower > self.upper:
            raise NumericalRange("joint lookahead: invalid finite interval")

    @property
    def midpoint(self):
        if self.upper == math.inf:
            return math.inf
        span = self.upper-self.lower
        return self.lower + span/2 if math.isfinite(span) else self.lower/2 + self.upper/2

    @property
    def radius(self):
        return _half_width(self)


def _finite(value):
    if not math.isfinite(value):
        raise NumericalRange("joint lookahead: finite arithmetic exceeds numerical range")
    return value


def _float_positive(value):
    try:
        result = float(value)
    except OverflowError as exc:
        raise NumericalRange("joint lookahead: positive number exceeds numerical range") from exc
    if not result or not math.isfinite(result):
        raise NumericalRange("joint lookahead: positive number cannot be represented")
    return result


def _float_nonnegative(value):
    return 0. if value == 0 else _float_positive(value)


def _half_width(interval):
    span = interval.upper-interval.lower
    return span/2 if math.isfinite(span) else interval.upper/2-interval.lower/2


def _symmetric(center, radius):
    return Interval(_finite(center-radius), _finite(center+radius))


def _logsumexp(values):
    top = max(values)
    terms = []
    for v in values:
        p = math.exp(v-top)
        if not p:
            raise NumericalRange("joint policy: positive probability cannot be represented")
        terms.append(p)
    return _finite(top + math.log(math.fsum(terms)))


def policy_bounds(scores, gamma):
    """§3-7-4 ⑥: independent J-box bounds, calculated in logs.

    q_i lower uses U_i and every other L_j; upper uses L_i and other U_j.
    Only proven +inf entries have zero probability. No candidate is omitted
    because its calculation has not finished. gamma=0 is uniform on finite J.
    """
    gamma = _float_nonnegative(_fraction(gamma, "gamma"))
    finite = [i for i, v in enumerate(scores) if v.upper != math.inf]
    if not finite:
        raise NoAdmissibleCandidate("every candidate has infinite cost")
    result = [Interval(0., 0.) for _ in scores]
    for i in finite:
        if gamma == 0:
            result[i] = Interval(1/len(finite), 1/len(finite))
            continue
        lower_terms = [0.] + [_finite(gamma*(scores[i].upper-scores[j].lower)) for j in finite if j != i]
        upper_terms = [0.] + [_finite(gamma*(scores[i].lower-scores[j].upper)) for j in finite if j != i]
        lower, upper = math.exp(-_logsumexp(lower_terms)), math.exp(-_logsumexp(upper_terms))
        if not lower or not upper:
            raise NumericalRange("joint policy: positive bound cannot be represented")
        result[i] = Interval(lower, upper)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Context:
    """Root-relative records O and starts A; clock values remain absolute ns.

    E/O entries: (report_ns-now_ns,label,action,outcome).
    A entries: (start_ns-now_ns,label,action). unread explicitly identifies
    not-yet-ingested O0, consumed once in the first E (also when the own
    report never comes). A missing readable name does not imply O0.
    """
    now_ns: int
    time_ns: int
    O: tuple
    A: tuple
    unread: tuple


def _new_attempt(eta, belief, action):
    labels = {a.label for a in belief.attempts}
    rank = len(belief.attempts)
    while (label := f"future:{rank}") in labels:
        rank += 1
    return Attempt(label, action, eta.time_ns)


@dataclass(frozen=True, slots=True)
class Branch:
    E: tuple
    probability: Fraction
    probability_bounds: ProbabilityBounds
    belief: JointBelief
    attempt: Attempt
    t_end: int
    terminal: bool

    @property
    def log_probability(self):
        return _log_fraction(self.probability)


@dataclass(frozen=True, slots=True)
class Branches:
    """§3-10: record-conditioned children, normalized probabilities and error."""
    items: tuple[Branch, ...]
    normalization: Fraction
    normalization_bounds: ProbabilityBounds
    total_variation_error: Fraction


def branches(eta, belief, action, deadline_ns, *, times, branch_budget):
    """Batch every report up to the own report (inclusive), or to the deadline.

    Enumerating work values is used only to deduplicate record skeletons.
    Their probabilities are NEVER multiplied independently. Each skeleton's
    complete names/nonarrivals conditions one joint belief and integrates all
    compatible work allocations, states and parameters before its mass is used.
    Only attempts without a Completed fact are pending. Their arrivals at or
    before root now form O0; an ingested unreadable name is never retried here.
    """
    _ns(deadline_ns)
    _ns(eta.now_ns)
    _ns(eta.time_ns)
    if eta.time_ns != belief.observed_ns or not eta.now_ns <= eta.time_ns <= deadline_ns:
        raise IntegrationIncomplete("joint_branches_time: exact current time/deadline required")
    if action not in belief.model.work or type(branch_budget) is not int or branch_budget < 1:
        raise ValueError("joint branches: action and positive integer budget required")
    own = _new_attempt(eta, belief, action)
    base = belief.condition((), observed_ns=eta.time_ns, attempts=(own,))
    completed = {f.label for f in belief.facts if isinstance(f, Completed)}
    completion_facts = {f.label: f for f in belief.facts if isinstance(f, Completed)}
    prefix = tuple((eta.now_ns+e[0], e[1], e[2]) for e in eta.unread)
    prefix_names = tuple((completion_facts[e[1]].outcome,) if completion_facts[e[1]].outcome is not None
                         else base.model.outcomes for e in eta.unread)
    active = tuple(a for a in base.attempts if a.label not in completed)
    own_index = active.index(own)
    choices = [base.model.work[a.action].points for a in active]
    if math.prod(map(len, choices)) > branch_budget:
        raise IntegrationIncomplete("joint_branches_budget: allocation enumeration unfinished")
    skeletons = set()
    for allocation in product(*choices):
        work = allocation[own_index][0]
        end = deadline_ns if work is INFINITE_WORK else min(deadline_ns, own.start_ns+work)
        terminal = work is INFINITE_WORK or own.start_ns+work > deadline_ns
        records = tuple(sorted(((a.start_ns+w, a.label, a.action) for a, (w, _) in zip(active, allocation)
                                if w is not INFINITE_WORK and a.start_ns+w <= end),
                               key=lambda e: (e[0], next(a.start_ns for a in active if a.label == e[1]), e[1])))
        skeletons.add((records, end, terminal))
    # Same grid for the denominator and ALL children of this action. The exact
    # finite partition then sums to 1 even for the lower transition calculation.
    grid = tuple(sorted(base._times() | set(times)))
    denominator = target_marginal(base, times, _grid=grid)
    if not denominator.evidence:
        raise ModelViolation("joint branches: parent has zero likelihood")
    result = []
    for skeleton, end, terminal in sorted(skeletons):
        full_skeleton = prefix+skeleton
        choices = prefix_names+(base.model.outcomes,)*len(skeleton)
        if len(result) + math.prod(map(len, choices)) > branch_budget:
            raise IntegrationIncomplete("joint_branches_budget: record enumeration unfinished")
        reported = {label for _, label, _ in skeleton}
        for names in product(*choices):
            facts = tuple(Completed(label, t, y) for (t, label, _), y in zip(full_skeleton, names))
            facts += tuple(NotArrived(a.label, end) for a in active if a.label not in reported)
            child = base.condition(facts, observed_ns=end)
            numerator = target_marginal(child, times, allow_impossible=True, _grid=grid)
            if not numerator.evidence:
                continue  # Structural zero, determined by the exact kernel/support.
            p = numerator.evidence/denominator.evidence
            bound = _probability_bounds(p, max(denominator.log_error, numerator.log_error))
            E = tuple((t-eta.now_ns, label, a, y) for (t, label, a), y in zip(full_skeleton, names))
            result.append(Branch(E, p, bound, child, own, end, terminal))
    normalization = sum((b.probability for b in result), Fraction(0))
    if normalization != 1:
        raise IntegrationIncomplete("joint_branches_normalization: records do not partition the parent")
    tv = sum((max(b.probability-b.probability_bounds.lower,
                  b.probability_bounds.upper-b.probability) for b in result), Fraction(0))/2
    return Branches(tuple(result), normalization, ProbabilityBounds(Fraction(1), Fraction(1)), min(Fraction(1), tv))


def _advance(eta, branch):
    a = branch.attempt
    return Context(eta.now_ns, branch.t_end, eta.O+branch.E,
                   eta.A+((a.start_ns-eta.now_ns, a.label, a.action),), ())


def _expect(probabilities, intervals, tv):
    """Child uncertainty plus δ*osc(V); no lower/upper-corner monotonicity."""
    if any(v.upper == math.inf and p > 0 for p, v in zip(probabilities, intervals)):
        return Interval(math.inf, math.inf)
    weights = [_float_positive(p) for p in probabilities]
    center = _finite(math.fsum(p*v.midpoint for p, v in zip(weights, intervals)))
    radius = _finite(math.fsum(p*_half_width(v) for p, v in zip(weights, intervals)))
    if tv:
        radius = _finite(radius + _float_positive(tv)*(max(v.upper for v in intervals)-min(v.lower for v in intervals)))
    return _symmetric(center, radius)


def _increment(current, expected):
    # The stage-1 identity d=I(X*;E|eta,a) proves nonnegativity. This is the
    # difference of root-based expected potentials, not a pathwise positive gain.
    return InformationBounds(max(0., expected.lower-current.upper),
                             max(0., expected.upper-current.lower))


@dataclass(frozen=True, slots=True)
class Leaf:
    eta: Context
    belief: JointBelief
    potential: InformationBounds
    cost: Interval

    @property
    def information(self):
        return InformationBounds(0., 0.)

    @property
    def value(self):
        return self.cost


@dataclass(frozen=True, slots=True)
class EvaluatedBranch:
    branch: Branch
    child: object


@dataclass(frozen=True, slots=True)
class ActionValue:
    action: str
    expected_cost: Interval
    information: InformationBounds | None
    increment: InformationBounds
    J_bounds: Interval
    children: tuple[EvaluatedBranch, ...]
    reason: str | None

    @property
    def J(self):
        # §3-10: form J from the separate C/I midpoints, then softmax this J.
        return math.inf if self.information is None else self.expected_cost.midpoint-self.information.midpoint


@dataclass(frozen=True, slots=True)
class Node:
    eta: Context
    belief: JointBelief
    potential: InformationBounds
    actions: tuple[ActionValue, ...]
    q: tuple[float, ...]
    q_bounds: tuple[Interval, ...]
    cost: Interval
    information: InformationBounds | None
    value: Interval
    V: float


def _mix_policy(actions, gamma):
    try:
        q = tuple(map(float, _policy([a.J for a in actions], gamma)))
    except NoAdmissibleCandidate:
        return tuple(0. for _ in actions), tuple(Interval(0., 0.) for _ in actions), Interval(math.inf, math.inf), None, Interval(math.inf, math.inf), math.inf
    if any(p == 0 and a.J != math.inf for p, a in zip(q, actions)):
        raise NumericalRange("joint policy: positive candidate probability disappeared")
    qb = policy_bounds(tuple(a.J_bounds for a in actions), gamma)
    finite = [i for i, a in enumerate(actions) if a.J != math.inf]
    weights = tuple(Fraction(q[i]) for i in finite)
    # Float softmax's last-bit normalization is roundoff, separated from the
    # certified J box. Normalize a common copy before interval expectations.
    weights = tuple(w/sum(weights) for w in weights)
    tv = min(1., .5*math.fsum(max(abs(q[i]-qb[i].lower), abs(qb[i].upper-q[i])) for i in finite))
    cost = _expect(weights, tuple(actions[i].expected_cost for i in finite), tv)
    info = _expect(weights, tuple(actions[i].information for i in finite), tv)
    V = _finite(math.fsum(q[i]*actions[i].J for i in finite))
    # §3-7-4 ④: Boltzmann mean is not coordinatewise monotone. On the entire
    # box, ||grad V||_1 <= 1+gamma*(max U-min L)/2, not corner substitution.
    width = max(actions[i].J_bounds.upper for i in finite)-min(actions[i].J_bounds.lower for i in finite)
    L = 1. if gamma == 0 else _finite(1+gamma*width/2)
    epsilon = max(max(abs(actions[i].J-actions[i].J_bounds.lower),
                      abs(actions[i].J_bounds.upper-actions[i].J)) for i in finite)
    value = _symmetric(V, _finite(L*epsilon))
    return q, qb, cost, InformationBounds(info.lower, info.upper), value, V


def _time_set(root, candidates, deadline_ns, budget, *, unread=()):
    """Finite X*: every possible new start and measured/report time in the window."""
    starts, todo, times = {root.observed_ns}, [root.observed_ns], {root.origin_ns}
    while todo:
        start = todo.pop()
        for action in candidates:
            for work, _ in root.model.work[action].points:
                if work is INFINITE_WORK or start+work > deadline_ns:
                    continue
                end = start+work
                times.update((end, start if root.model.names[action].measures == "start" else end))
                if end <= deadline_ns and end not in starts:
                    starts.add(end)
                    todo.append(end)
        if len(starts)+len(times) > budget:
            raise IntegrationIncomplete("joint_time_budget: finite time set unfinished")
    completed = {f.label for f in root.facts if isinstance(f, Completed)}
    known_names = {f.label for f in root.facts if isinstance(f, Completed) and f.outcome is not None}
    # Only the explicit not-yet-ingested input registers old report targets.
    # Completed(None) alone may instead be an ingested unreadable report.
    by_label = {a.label: a for a in root.attempts}
    for offset, label, action, _ in unread:
        if label in known_names:
            continue  # A known report is only reposted to the cost path.
        report_ns = root.observed_ns+offset
        times.update((report_ns, by_label[label].start_ns
                      if root.model.names[action].measures == "start" else report_ns))
    for a in root.attempts:
        if a.label in completed:
            continue
        for work, _ in root.model.work[a.action].points:
            if work is not INFINITE_WORK and a.start_ns+work <= deadline_ns:
                times.update((a.start_ns+work, a.start_ns if root.model.names[a.action].measures == "start" else a.start_ns+work))
    return tuple(sorted(times))


class _Evaluator:
    def __init__(self, root, candidates, deadline, gamma, terminal_cost, cost_bound,
                 tolerance, series_budget, node_budget, times):
        self.root, self.candidates, self.deadline, self.gamma = root, candidates, deadline, gamma
        self.terminal_cost, self.cost_bound = terminal_cost, cost_bound
        self.tolerance, self.series_budget, self.node_budget = tolerance, series_budget, node_budget
        self.times, self.nodes, self.leaves, self.max_depth = times, 0, 0, 0
        self.potentials = {}

    def potential(self, belief):
        key = belief.attempts, belief.facts
        if key not in self.potentials:
            self.potentials[key] = root_potential(self.root, belief, times=self.times,
                                                 tolerance=self.tolerance, series_budget=self.series_budget)
        return self.potentials[key]

    def consume(self, depth, leaf):
        self.leaves += int(leaf)
        self.nodes += int(not leaf)
        self.max_depth = max(self.max_depth, depth)
        if self.nodes+self.leaves > self.node_budget:
            raise IntegrationIncomplete("joint_tree_budget: backward evaluation unfinished")

    def terminal(self, eta, belief, potential, depth):
        self.consume(depth, True)
        cost = self.terminal_cost(eta)
        if isinstance(cost, bool) or not isinstance(cost, (int, float, Fraction)):
            raise ValueError("joint terminal cost: numeric value required")
        if cost != cost or cost < 0:
            raise ValueError("joint terminal cost: nonnegative finite cost or +inf required")
        cost = math.inf if cost == math.inf else _float_nonnegative(cost)
        if cost != math.inf and cost > self.cost_bound:
            raise IntegrationIncomplete("joint_cost_bound: declared finite bound exceeded")
        return Leaf(eta, belief, potential, Interval(cost, cost))

    def node(self, eta, belief, depth=0):
        self.consume(depth, False)
        current = self.potential(belief)
        values = []
        for action in self.candidates:
            rows = branches(eta, belief, action, self.deadline, times=self.times,
                            branch_budget=self.node_budget)
            children, potentials = [], []
            for b in rows.items:
                child_eta = _advance(eta, b)
                potential = self.potential(b.belief)
                child = (self.terminal(child_eta, b.belief, potential, depth+1) if b.terminal
                         else self.node(child_eta, b.belief, depth+1))
                children.append(EvaluatedBranch(b, child))
                potentials.append(potential)
            probabilities = tuple(b.probability for b in rows.items)
            d = _increment(current, _expect(probabilities, potentials, rows.total_variation_error))
            cost = _expect(probabilities, tuple(c.child.cost for c in children), rows.total_variation_error)
            undefined = any(c.child.information is None for c in children)
            if undefined:
                info, J, reason = None, Interval(math.inf, math.inf), "no_admissible_continuation"
            else:
                future = _expect(probabilities, tuple(c.child.information for c in children), rows.total_variation_error)
                info = InformationBounds(d.lower+future.lower, d.upper+future.upper)
                if cost.upper == math.inf:
                    J, reason = Interval(math.inf, math.inf), "forbidden_terminal"
                else:
                    # Carry both C/I under the same future policy. Also carry
                    # the tighter direct -d+E[V] recursion bound (L above).
                    diff = Interval(cost.lower-info.upper, cost.upper-info.lower)
                    continuation = _expect(probabilities, tuple(c.child.value for c in children), rows.total_variation_error)
                    nominal = cost.midpoint-info.midpoint
                    radius = (d.upper-d.lower)/2 + continuation.radius
                    radius += abs(nominal-(continuation.midpoint-d.midpoint))
                    direct = _symmetric(nominal, _finite(radius))
                    J = Interval(min(nominal, max(diff.lower, direct.lower)),
                                 max(nominal, min(diff.upper, direct.upper)))
                    reason = None
            values.append(ActionValue(action, cost, info, d, J, tuple(children), reason))
        q, qb, cost, info, value, V = _mix_policy(tuple(values), self.gamma)
        return Node(eta, belief, current, tuple(values), q, qb, cost, info, value, V)


@dataclass(frozen=True, slots=True)
class Evaluation:
    root: Node
    chosen: str
    times: tuple[int, ...]
    nodes: int
    leaves: int
    max_depth: int
    refinements: int


def one_step_components(root, action, *, deadline_ns, terminal_cost, cost_bound,
                        tolerance, series_budget, node_budget):
    """§6-2 bridge A / a single-record experiment, using the SAME joint branches.

    Its terminal cost is evaluated at the own report or deadline. This is a
    mathematical one-step component query, not a truncation of evaluate's
    finite-horizon continuation policy and not the public Z-conditioned entry.
    """
    if not isinstance(root, JointBelief):
        raise IntegrationIncomplete("joint_stage1: integer-ns unit-speed joint belief required")
    _ns(deadline_ns)
    if deadline_ns < root.observed_ns:
        raise ValueError("joint deadline precedes root")
    if any(type(v) is not int or v < 1 for v in (series_budget, node_budget)):
        raise ValueError("joint one step: positive work budgets required")
    tol = _float_positive(_fraction(tolerance, "tolerance", positive=True))
    bound = _float_nonnegative(_fraction(cost_bound, "terminal cost bound"))
    times = _time_set(root, (action,), deadline_ns, node_budget)
    eta = Context(root.observed_ns, root.observed_ns, (), (), ())
    engine = _Evaluator(root, (action,), deadline_ns, 0., terminal_cost, bound,
                        tol/8, series_budget, node_budget, times)
    rows = branches(eta, root, action, deadline_ns, times=times, branch_budget=node_budget)
    children = tuple(EvaluatedBranch(b, engine.terminal(_advance(eta, b), b.belief,
                      engine.potential(b.belief), 1)) for b in rows.items)
    probabilities = tuple(b.probability for b in rows.items)
    info = _increment(engine.potential(root), _expect(probabilities, tuple(c.child.potential for c in children), rows.total_variation_error))
    cost = _expect(probabilities, tuple(c.child.cost for c in children), rows.total_variation_error)
    J = Interval(math.inf, math.inf) if cost.upper == math.inf else Interval(cost.lower-info.upper, cost.upper-info.lower)
    if max(cost.upper-cost.lower if cost.upper != math.inf else 0., info.upper-info.lower,
           J.upper-J.lower if J.upper != math.inf else 0.) > tol:
        raise IntegrationIncomplete("joint_one_step_accuracy: width not reached")
    return ActionValue(action, cost, info, info, J, children,
                       "forbidden_terminal" if cost.upper == math.inf else None)


def one_step_conditioned(root, action, *, outcome_cost, tolerance, series_budget, node_budget):
    """Exact finite one-step I(X*; own record | Z,h), with ALL pending Z.

    Z includes every existing report's time/name or permanent absence, including
    reports after the candidate. Their mutual order is redundant given these
    exact times; random tie ranks are independent of X* conditional on the times
    and contribute zero conditional information. This conditioning is ONLY the
    one_step contract, never lookahead's continuation policy (§3-6-3/1b §3-5).
    Sum p(z,e) KL(P(X*|z,e,h)||P(X*|z,h)), using one common finite time grid.
    Work assignments are enumeration aids, not observed labels or independent
    posterior factors. Zero work is safe here: no subsequent action is started.
    """
    if not isinstance(root, JointBelief) or action not in root.model.work:
        raise ValueError("joint one step: joint root and model action required")
    if any(w is INFINITE_WORK for w, _ in root.model.work[action].points):
        raise OutsideEvaluationType("one_step requires every candidate to return a result")
    if any(type(n) is not int or n < 1 for n in (series_budget, node_budget)):
        raise ValueError("joint one step: positive work budgets required")
    tol = _float_positive(_fraction(tolerance, "tolerance", positive=True))
    eta = Context(root.observed_ns, root.observed_ns, (), (), ())
    own = _new_attempt(eta, root, action)
    base = root.condition((), observed_ns=root.observed_ns, attempts=(own,))
    completed = {f.label for f in root.facts if isinstance(f, Completed)}
    active = tuple(a for a in base.attempts if a.label not in completed)
    choices = [base.model.work[a.action].points for a in active]
    if math.prod(map(len, choices)) > node_budget:
        raise IntegrationIncomplete("joint_one_step_budget: work enumeration unfinished")
    end = max(a.start_ns+w for a in active for w, _ in choices[active.index(a)] if w is not INFINITE_WORK)
    times = tuple(sorted(base._times()))
    grid = times
    denominator = target_marginal(base, times, _grid=grid)
    skeletons = set()
    for allocation in product(*choices):
        skeletons.add(tuple((a.label, None if w is INFINITE_WORK else a.start_ns+w)
                           for a, (w, _) in zip(active, allocation)))
    probabilities, infos, costs, errors = [], [], [], []
    budget = 0
    z_cache = {}
    for skeleton in sorted(skeletons, key=repr):
        present = tuple((label, t) for label, t in skeleton if t is not None)
        budget += len(base.model.outcomes)**len(present)
        if budget > node_budget:
            raise IntegrationIncomplete("joint_one_step_budget: record enumeration unfinished")
        missing = tuple(NotArrived(label, end) for label, t in skeleton if t is None)
        for outcomes in product(base.model.outcomes, repeat=len(present)):
            full = tuple(Completed(label, t, y) for (label, t), y in zip(present, outcomes)) + missing
            child = base.condition(full, observed_ns=end)
            numerator = target_marginal(child, times, allow_impossible=True, _grid=grid)
            if not numerator.evidence:
                continue
            p = numerator.evidence/denominator.evidence
            bounds = _probability_bounds(p, max(numerator.log_error, denominator.log_error))
            z = tuple(f for f in full if f.label != own.label)
            if z not in z_cache:
                z_cache[z] = base.condition(z, observed_ns=end)
            info = root_potential(z_cache[z], child, times=times, tolerance=tol/16,
                                  series_budget=series_budget)
            y = next(f.outcome for f in full if f.label == own.label)
            value = outcome_cost(y)
            if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)) or value != value or value < 0:
                raise ValueError("joint one step: nonnegative outcome cost required")
            value = math.inf if value == math.inf else _float_nonnegative(value)
            probabilities.append(p)
            infos.append(info)
            costs.append(Interval(value, value))
            errors.append(max(p-bounds.lower, bounds.upper-p))
    if sum(probabilities, Fraction(0)) != 1:
        raise IntegrationIncomplete("joint_one_step_normalization: Z/E do not partition root")
    tv = min(Fraction(1), sum(errors, Fraction(0))/2)
    C = _expect(tuple(probabilities), tuple(costs), tv)
    raw = _expect(tuple(probabilities), tuple(infos), tv)
    I = InformationBounds(max(0., raw.lower), max(0., raw.upper))
    J = Interval(math.inf, math.inf) if C.upper == math.inf else Interval(C.lower-I.upper, C.upper-I.lower)
    if I.upper-I.lower > tol or (C.upper != math.inf and max(C.upper-C.lower, J.upper-J.lower) > tol):
        raise IntegrationIncomplete("joint_one_step_accuracy: transition/series width not reached")
    return ActionValue(action, C, I, I, J, (), "forbidden_terminal" if C.upper == math.inf else None)


def evaluate(root, *, candidates, deadline_ns, gamma, u, terminal_cost, cost_bound,
             tolerance, series_budget, node_budget, refinement_budget, unread=()):
    """Backward finite recursion with root C/I/J/q intervals and midpoint choice.

    Caller supplies the absolute original deadline, pure terminal cost and its
    finite bound (individual forbidden leaves may return +inf), and all accuracy/
    work budgets. No G0/alpha/rho/lambda/Q/prior weights are supplied by this code.
    Failed accuracy is refined globally, including transitions and future softmax;
    no leaf, candidate, rare positive branch or series remainder is silently cut.
    unread explicitly declares not-yet-ingested O0 and supplies its report
    metadata; names are first conditioned in E. Completed(..., None) alone
    retains timing evidence and never declares a readable future name.
    Pending attempts also generate O0 when their reports arrive at/before now.
    A previously known name may be reposted to the cost path without new
    information.
    """
    if not isinstance(root, JointBelief):
        raise IntegrationIncomplete("joint_stage1: integer-ns unit-speed joint belief required")
    if any(w == 0 for p in root.model.work.values() for w, _ in p.points):
        if any(p.points == ((0, Fraction(1)),) for p in root.model.work.values()):
            raise OutsideEvaluationType("certain_zero_completion: infinite repetition is outside lookahead")
        raise IntegrationIncomplete("joint_lower_work: positive duration bound is not certified")
    _ns(deadline_ns)
    if deadline_ns < root.observed_ns:
        raise ValueError("joint deadline precedes root")
    candidates = tuple(candidates)
    if not candidates or len(set(candidates)) != len(candidates) or any(a not in root.model.work for a in candidates):
        raise ValueError("joint candidates: unique model actions in explicit order required")
    gamma = _float_nonnegative(_fraction(gamma, "gamma"))
    tol = _float_positive(_fraction(tolerance, "tolerance", positive=True))
    bound = _float_nonnegative(_fraction(cost_bound, "terminal cost bound"))
    if isinstance(u, bool) or not isinstance(u, (int, float)) or not 0 <= u < 1:
        raise ValueError("joint u: expected a value in [0,1)")
    if any(type(v) is not int or v < 1 for v in (series_budget, node_budget, refinement_budget)) or not callable(terminal_cost):
        raise ValueError("joint evaluation: positive budgets and a terminal-cost function required")
    completed = {f.label: f for f in root.facts if isinstance(f, Completed)}
    for a in root.attempts:
        if a.label not in completed and a.start_ns < root.observed_ns and not any(isinstance(f, NotArrived) and f.label == a.label and f.until_ns == root.observed_ns for f in root.facts):
            raise IntegrationIncomplete("joint_pending_context: certified nonarrival at the root required")
    unread = tuple(unread)
    by_label = {a.label: a for a in root.attempts}
    if any(len(e) != 4 or e[1] not in completed or e[2] != by_label[e[1]].action
           or completed[e[1]].report_ns != root.observed_ns+e[0]
           or (completed[e[1]].outcome is not None and completed[e[1]].outcome != e[3]) for e in unread):
        raise ValueError("joint unread: O0 metadata must match root completed records")
    if len({e[1] for e in unread}) != len(unread):
        raise ValueError("joint unread: duplicate report")
    times = _time_set(root, candidates, deadline_ns, node_budget, unread=unread)
    eta = Context(root.observed_ns, root.observed_ns, (), (), unread)
    local = tol/16
    total_nodes = total_leaves = 0
    for refinement in range(refinement_budget):
        if not local:
            raise NumericalRange("joint refinement: tolerance cannot be represented")
        precise_root = replace(root, transition_tolerance=min(root.transition_tolerance, local/64))
        engine = _Evaluator(precise_root, candidates, deadline_ns, gamma, terminal_cost, bound,
                            local, series_budget, node_budget-total_nodes-total_leaves, times)
        try:
            answer = engine.node(eta, precise_root)
        except IntegrationIncomplete as exc:
            # This reason asks for tighter transitions, not a larger fixed
            # series/work budget. Do not disguise other unfinished calculations.
            if str(exc) != "joint_information: transition/series error exceeds requested width":
                raise
            total_nodes += engine.nodes
            total_leaves += engine.leaves
            local /= 4
            continue
        except RecursionError as exc:
            raise IntegrationIncomplete("joint_depth: finite backward recursion exceeds available stack") from exc
        total_nodes += engine.nodes
        total_leaves += engine.leaves
        if all(a.J == math.inf for a in answer.actions):
            raise NoAdmissibleCandidate("every candidate has infinite cost")
        widths = [v.upper-v.lower for a in answer.actions if a.J != math.inf
                  for v in (a.expected_cost, a.information, a.J_bounds)]
        widths += [q.upper-q.lower for q in answer.q_bounds]
        if max(widths) <= tol:
            cumulative, chosen = 0., None
            for action, p in zip(candidates, answer.q):
                cumulative += p
                if p and u < cumulative:
                    chosen = action
                    break
            if chosen is None:
                chosen = candidates[max(i for i, p in enumerate(answer.q) if p)]
            return Evaluation(answer, chosen, times, total_nodes, total_leaves, engine.max_depth, refinement+1)
        local /= 4
    raise IntegrationIncomplete("joint_accuracy: root C/I/J/q width not reached")


# Stage 2 deliberately has its own time/context types. A continuous report
# interval is an expression-valued edge, not a set of sampled event records.
@dataclass(frozen=True, slots=True)
class RulerStart:
    """Mathematical seconds: a constant, or the SAME report variable r + offset."""
    variable: str | None
    offset_s: Fraction

    def shifted(self, duration):
        return RulerStart(self.variable, self.offset_s+duration)

    def __float__(self):
        raise IntegrationIncomplete("stage2_record: mathematical starts are not driving facts")

    def __int__(self):
        raise IntegrationIncomplete("stage2_record: mathematical starts are not integer records")


@dataclass(frozen=True, slots=True)
class KnownContinuation:
    """A known positive deterministic delay, exact report and constant name.

    Equivalent to known work/known equal positive speeds in both states.
    Its report/nonarrival supplies no information about laws or state. These
    certify a member of the SAME root candidate set, never replace that set.
    No model work, speed, rate or weight is implicitly supplied here.
    """
    action: str
    duration_s: Fraction

    def __post_init__(self):
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("stage2 continuation: nonempty action label required")
        try:
            duration = _fraction(self.duration_s, "known duration", positive=True)
        except (ValueError, TypeError) as exc:
            raise IntegrationIncomplete("stage2_continuation: known positive delay required") from exc
        _float_positive(duration)
        object.__setattr__(self, "duration_s", duration)


@dataclass(frozen=True, slots=True)
class _CompletionLowerBound:
    action: str
    duration_s: Fraction


@dataclass(frozen=True, slots=True)
class RulerPotential:
    """Fixed-root B_h(r) expression, or the fixed atom/nonarrival posterior.

    Later deterministic reports add states whose conditional law, given the
    first report's state, is unchanged by that report (Markov property). Their
    conditional KL is zero. Thus this SAME potential persists to the leaf;
    d_h for each continuation is zero. Do not replace its root by a child.
    """
    model: object
    piece: object | None
    belief: object | None

    def value_at(self, r):
        """An expression query, NOT conditioning on a sampled observation."""
        from .joint_stage2 import _integrands, _sum_logs, _exp
        if self.belief is not None:
            return self.belief.root_potential()
        r = _fraction(r, "integration variable")
        if not self.piece.lower_s < r < self.piece.upper_s:
            raise ValueError("stage2 potential: interior integration variable required")
        law, state = _integrands(self.model, self.piece, r)
        p = _exp(_sum_logs(_log_fraction(self.model.weights[i])
                          + self.model.kernels[i]._density_extension(r) for i in self.piece.active))
        from .joint_stage2 import PotentialParts
        return PotentialParts(law/p, state/p)


@dataclass(frozen=True, slots=True)
class RulerLeaf:
    start: RulerStart
    potential: RulerPotential
    intercept: Interval
    action: str
    report_in_window: bool


@dataclass(frozen=True, slots=True)
class RulerContinuationValue:
    action: str
    child: object
    J_intercept: Interval
    increment: InformationBounds


@dataclass(frozen=True, slots=True)
class RulerNode:
    """Common cost slope beta*r cancels from softmax on each time piece."""
    start: RulerStart
    potential: RulerPotential
    actions: tuple[RulerContinuationValue, ...]
    q: tuple[float, ...]
    q_bounds: tuple[Interval, ...]
    intercept: Interval
    value_intercept: Interval


@dataclass(frozen=True, slots=True)
class RulerEdge:
    """An integrated mass; density pieces and atoms retain distinct bases."""
    basis: str
    probability: float
    lower_s: Fraction | None
    upper_s: Fraction | None
    start: RulerStart | None
    potential: RulerPotential
    child: RulerNode | RulerLeaf


@dataclass(frozen=True, slots=True)
class Stage2Root:
    horizon_s: Fraction
    actions: tuple[ActionValue, ...]
    q: tuple[float, ...]
    q_bounds: tuple[Interval, ...]
    cost: Interval
    information: InformationBounds
    value: Interval
    V: float


@dataclass(frozen=True, slots=True)
class Stage2Evaluation:
    root: Stage2Root
    chosen: str
    nodes: int
    leaves: int
    max_depth: int
    integration_nodes: int
    refinements: int


def _density_first_moment(model, piece):
    """Analytic integral of r*p(r), with NO sampled report/start.

    For a decreasing exponential on [l,u], x=rate*(u-l), the distance
    of its conditional mean from l is (u-l)*P(2,x)/(x*(1-exp(-x))).
    P(2,x)=integral_0^x t*exp(-t)dt. For an increasing density reflect
    about u. gammainc avoids cancellation in 1-(1+x)*exp(-x).
    Special-function arithmetic, like other floating roundoff, is excluded
    from the analytic/integration error guarantee.
    """
    from scipy.special import gammainc
    from .joint_stage2 import _exp, _number
    length = _number(piece.upper_s-piece.lower_s, "piece length")
    result = []
    for i in piece.active:
        k = model.kernels[i]
        x = _float_positive(k.q*length/_float_positive(abs(k.slope)))
        numerator = _float_positive(gammainc(2., x))
        denominator = _float_positive(x * -math.expm1(-x))
        distance = _float_positive(length*numerator/denominator)
        mean = (float(piece.lower_s)+distance if k.slope > 0
                else float(piece.upper_s)-distance)
        if not float(piece.lower_s) <= mean <= float(piece.upper_s):
            raise NumericalRange("stage2 moment: conditional mean outside its support")
        mass = _exp(_log_fraction(model.weights[i])+k.continuous_log_mass(piece.lower_s, piece.upper_s))
        result.append(_float_positive(mass*mean))
    return _finite(math.fsum(result))


def _ruler_product(a, b):
    value = _finite(a*b)
    if a != 0 and b != 0 and value == 0:
        raise NumericalRange("stage2 product: positive magnitude cannot be represented")
    return value


class _RulerEvaluator:
    def __init__(self, horizon, continuations, beta, offsets, bound, gamma, budget):
        self.horizon, self.continuations = horizon, continuations
        self.beta, self.offsets, self.gamma, self.budget = beta, offsets, gamma, budget
        self.cost_bound = bound
        self.nodes = self.leaves = self.integration_nodes = self.max_depth = 0

    def consume(self, depth, leaf=False):
        self.nodes += int(not leaf)
        self.leaves += int(leaf)
        self.max_depth = max(depth, self.max_depth)
        if self.nodes+self.leaves+self.integration_nodes > self.budget:
            raise IntegrationIncomplete("stage2_tree_budget: backward evaluation unfinished")

    def cuts(self, lower, upper):
        # Every possible future start is r+lag. Branch structure changes ONLY
        # at r=H-lag-duration. Enumerate cuts before doing any integration.
        lags, todo, cuts = {Fraction(0)}, [Fraction(0)], {lower, upper}
        while todo:
            lag = todo.pop()
            for a in self.continuations:
                end = lag+a.duration_s
                cut = self.horizon-end
                if lower < cut < upper:
                    cuts.add(cut)
                if isinstance(a, KnownContinuation) and end <= self.horizon-lower and end not in lags:
                    lags.add(end)
                    todo.append(end)
            if len(lags)+len(cuts) > self.budget:
                raise IntegrationIncomplete("stage2_time_budget: symbolic partition unfinished")
        return tuple(sorted(cuts))

    def leaf(self, start, potential, action, before, depth):
        self.consume(depth, True)
        intercept = _finite(_ruler_product(self.beta, _float_nonnegative(start.offset_s))+self.offsets[action])
        last_variable = _float_positive(potential.piece.upper_s) if start.variable else 0.
        if _finite(intercept+_ruler_product(self.beta, last_variable)) > self.cost_bound:
            raise IntegrationIncomplete("stage2_cost_bound: declared finite terminal bound exceeded")
        return RulerLeaf(start, potential, Interval(intercept, intercept), action, before)

    def node(self, start, potential, lower, upper, depth):
        self.consume(depth)
        if not self.continuations:
            raise IntegrationIncomplete("stage2_continuation: future candidates required before deadline")
        values, children = [], []
        for a in self.continuations:
            end = start.offset_s+a.duration_s
            if isinstance(a, _CompletionLowerBound):
                # A density piece is open at its endpoints. An equality at
                # its lower endpoint has zero Lebesgue mass; atoms are tested
                # separately with a strict inequality. No quadrature point
                # is substituted for the variable r.
                outside = (end > self.horizon if start.variable is None
                           else lower+end >= self.horizon)
                if not outside:
                    raise IntegrationIncomplete("stage2_continuation: candidate "+a.action+
                                                " may yield another informative report")
                child = self.leaf(start, potential, a.action, False, depth+1)
                cost = child.intercept
                values.append(ActionValue(a.action, cost, InformationBounds(0., 0.),
                                          InformationBounds(0., 0.), cost, (), None))
                children.append(RulerContinuationValue(a.action, child, cost, InformationBounds(0., 0.)))
                continue
            if start.variable is None:
                before = end <= self.horizon
            else:
                # No interior point becomes a start/fact. This comparison is
                # valid on the ENTIRE piece, whose structural cuts are fixed.
                if upper+end <= self.horizon:
                    before = True
                elif lower+end >= self.horizon:
                    before = False
                else:
                    raise IntegrationIncomplete("stage2_piece: unresolved deadline crossing")
            in_window = (end <= self.horizon if start.variable is None
                         else upper+end <= self.horizon)
            child = (self.node(start.shifted(a.duration_s), potential, lower, upper, depth+1)
                     if before else self.leaf(start, potential, a.action, in_window, depth+1))
            cost = child.intercept
            values.append(ActionValue(a.action, cost, InformationBounds(0., 0.),
                                      InformationBounds(0., 0.), cost, (), None))
            children.append(RulerContinuationValue(a.action, child, cost, InformationBounds(0., 0.)))
        q, qb, cost, _, value, _ = _mix_policy(tuple(values), self.gamma)
        return RulerNode(start, potential, tuple(children), q, qb, cost, value)

    def action(self, action, model, tolerance):
        from .joint_stage2 import (branches as jump_branches, information as jump_information,
                                  ContinuousBranch, _exp)
        tree = jump_branches(model, self.horizon)
        info = jump_information(model, self.horizon, tolerance=tolerance,
                                node_budget=self.budget-self.nodes-self.leaves-self.integration_nodes)
        self.integration_nodes += info.nodes
        edges, costs = [], []
        for atom in tree.atoms:
            potential = RulerPotential(model, None, atom.child)
            start = RulerStart(None, atom.time_s)
            child = (self.node(start, potential, atom.time_s, atom.time_s, 1) if atom.time_s <= self.horizon
                     else self.leaf(RulerStart(None, Fraction(0)), potential, action, True, 1))
            p = _exp(atom.log_mass)
            costs.append(_symmetric(_ruler_product(p, child.intercept.midpoint), _ruler_product(p, child.intercept.radius)))
            edges.append(RulerEdge("atom", p, atom.time_s, atom.time_s, start, potential, child))
        for original in tree.continuous:
            cuts = self.cuts(original.lower_s, original.upper_s)
            for lower, upper in zip(cuts, cuts[1:]):
                from .joint_stage2 import _sum_logs
                log_p = _sum_logs(_log_fraction(model.weights[i])
                                  + model.kernels[i].continuous_log_mass(lower, upper) for i in original.active)
                piece = ContinuousBranch(lower, upper, original.active, log_p)
                potential = RulerPotential(model, piece, None)
                start = RulerStart(f"R:{action}", Fraction(0))
                child = self.node(start, potential, lower, upper, 1)
                p = _exp(log_p)
                moment = _density_first_moment(model, piece) if self.beta else 0.
                costs.append(_symmetric(_finite(_ruler_product(p, child.intercept.midpoint)+_ruler_product(self.beta, moment)),
                                        _ruler_product(p, child.intercept.radius)))
                edges.append(RulerEdge("density", p, lower, upper, start, potential, child))
        if tree.not_arrived is not None:
            potential = RulerPotential(model, None, tree.not_arrived)
            child = self.leaf(RulerStart(None, Fraction(0)), potential, action, False, 1)
            p = _exp(tree.not_arrived.log_evidence)
            costs.append(Interval(_ruler_product(p, child.intercept.lower), _ruler_product(p, child.intercept.upper)))
            edges.append(RulerEdge("not_arrived", p, None, None, None, potential, child))
        cost = Interval(_finite(math.fsum(c.lower for c in costs)), _finite(math.fsum(c.upper for c in costs)))
        I = info.total
        return ActionValue(action, cost, I, I, Interval(cost.lower-I.upper, cost.upper-I.lower), tuple(edges), None)


def evaluate_stage2(models, *, horizon_s, continuations, cost_slope, terminal_offsets,
                    cost_bound, gamma, u, tolerance, node_budget, refinement_budget):
    """§6-3 (ii)-2 ruler with the SAME candidate set at every node.

    Each root candidate explicitly supplies a OneJumpModel (initial 0 at time
    0, no pending jobs). KnownContinuations are optional certificates of root
    actions' deterministic delays. All root models remain suffix candidates.
    A positive-work/max-speed bound certifies a suffix report outside the
    remaining window. Otherwise an informative later job, arbitrary history,
    unknown work/name law, or integer driving context is outside this calculator.
    On every path there is at most one informative report. No root state/time
    union X* is used. Later starts are the SAME r plus exact known delays.

    Finite terminal cost is beta*start_of_last_job + offset[last_action], with
    caller-supplied nonnegative beta/offsets/bound. On each deadline piece all
    suffix costs have the same beta*r, so suffix softmax cancels this term;
    integrate the resulting affine cost analytically. Root information uses
    the certified Simpson integral of fixed-root B_h, including nonarrival.
    C/I are carried under the SAME suffix policy. J/q use §3-10 midpoints
    and §3-7-4 bounds. Error excludes ordinary/special-function roundoff.
    No sampled posterior/event records or public driving/ledger operations.
    """
    from .joint_stage2 import OneJumpModel
    try:
        models = tuple(models.items())
    except AttributeError as exc:
        raise IntegrationIncomplete("stage2_models: explicit root action/models required") from exc
    if not models or any(not isinstance(m, OneJumpModel) for _, m in models):
        raise IntegrationIncomplete("stage2_models: one-jump mathematical models required")
    if any(not isinstance(a, str) or m.completion.actions != (a,) for a, m in models):
        raise ValueError("stage2 model action labels must match candidates")
    if len({m.q for _, m in models}) != 1 or len({m.completion.work_unit for _, m in models}) != 1:
        raise IntegrationIncomplete("stage2_root: common rate/world units required")
    h = _fraction(horizon_s, "horizon")
    _float_nonnegative(h)
    continuations = tuple(continuations)
    if any(not isinstance(a, KnownContinuation) for a in continuations):
        raise IntegrationIncomplete("stage2_continuation: only certified known uninformative jobs")
    if len({a.action for a in continuations}) != len(continuations):
        raise ValueError("stage2 continuation: unique action labels required")
    by_action = dict(models)
    for a in continuations:
        if a.action not in by_action:
            raise IntegrationIncomplete("stage2_continuation: candidate is outside the root U")
        m = by_action[a.action]
        if any(k.slope or k.t0 != a.duration_s for k in m.kernels):
            raise IntegrationIncomplete("stage2_continuation: reused action is not the same uninformative law")
    # Derive a certificate for EVERY root action. Uncertified candidates are
    # retained with a lower bound, so any unresolved positive branch stops.
    common = []
    for a, m in models:
        if all(not k.slope and k.t0 == m.kernels[0].t0 for k in m.kernels):
            common.append(KnownContinuation(a, m.kernels[0].t0))
        else:
            fastest = max(c for row in m.completion.candidates for pair in row for c in pair)
            common.append(_CompletionLowerBound(a, m.work/fastest))
    continuations = tuple(common)
    beta = _float_nonnegative(_fraction(cost_slope, "cost slope"))
    offsets = {a: _float_nonnegative(_fraction(c, "terminal offset")) for a, c in terminal_offsets.items()}
    if set(offsets) != set(by_action):
        raise ValueError("stage2 terminal offsets: one value per explicit action required")
    bound = _float_nonnegative(_fraction(cost_bound, "cost bound"))
    gamma = _float_nonnegative(_fraction(gamma, "gamma"))
    tol = _float_positive(_fraction(tolerance, "tolerance", positive=True))
    if isinstance(u, bool) or not isinstance(u, (int, float)) or not 0 <= u < 1:
        raise ValueError("stage2 u: expected a value in [0,1)")
    if any(type(v) is not int or v < 1 for v in (node_budget, refinement_budget)):
        raise ValueError("stage2: positive integer work budgets required")
    used = integration_nodes = nodes = leaves = 0
    local = tol/16
    for refinement in range(refinement_budget):
        if not local:
            raise NumericalRange("stage2 refinement: tolerance cannot be represented")
        engine = _RulerEvaluator(h, continuations, beta, offsets, bound, gamma, node_budget-used)
        engine.consume(0)
        try:
            actions = tuple(engine.action(a, m, local) for a, m in models)
        except RecursionError as exc:
            raise IntegrationIncomplete("stage2_depth: finite recursion exceeds available stack") from exc
        q, qb, C, I, V, point = _mix_policy(actions, gamma)
        used += engine.nodes+engine.leaves+engine.integration_nodes
        nodes += engine.nodes
        leaves += engine.leaves
        integration_nodes += engine.integration_nodes
        widths = [v.upper-v.lower for a in actions for v in (a.expected_cost, a.information, a.J_bounds)]
        widths.extend(qi.upper-qi.lower for qi in qb)
        if max(widths) <= tol:
            cumulative = 0.
            for (action, _), p in zip(models, q):
                cumulative += p
                if p and u < cumulative:
                    break
            else:
                action = models[max(i for i, p in enumerate(q) if p)][0]
            root = Stage2Root(h, actions, q, qb, C, I, V, point)
            return Stage2Evaluation(root, action, nodes, leaves, engine.max_depth,
                                    integration_nodes, refinement+1)
        local /= 4
    raise IntegrationIncomplete("stage2_accuracy: root C/I/J/q width not reached")
