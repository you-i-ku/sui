"""根で固定した好みと世界を、観測の枝だけで先読みする。"""

import math as _math
from dataclasses import dataclass as _dataclass, replace as _replace
from itertools import product as _product
import numpy as _np
from scipy.special import logsumexp as _logsumexp, digamma as _digamma

from .inference import (policy_posterior as _policy_posterior, remaining as _remaining,
    _log_A, _s4d_likelihood as _log_likelihood,
    ledger as _ledger, ModelViolation as _ModelViolation, select as _select,
    NumericalRange, _s4d_log_transition, _s4d_log_product, _s4d_normalize,
    _s4d_log_belief, _s4d_finite, _s4d_fsum, _s4d_weighted_cost, _s4d_cost_sum)
from .model import _duration_ns
from .preference import cost as _cost, _key, EvaluationInput as _EvaluationInput


class NoAdmissibleCandidate(ValueError):
    """すべての候補が禁じた結果に通じる (R4・C7)。"""


class OutsideEvaluationType(ValueError):
    """候補や特徴を、この型の評価では扱えない (N3・C4・C7)。"""


def _policy(values, gamma):
    """+∞を外してsoftmax。γ=0も残る候補だけ一様、全+∞なら失敗 (R4・R7)。"""
    if type(gamma) not in (int, float) or not _math.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma: expected finite nonnegative number")
    values = _np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or _np.any(_np.isnan(values) | _np.isneginf(values)):
        raise ValueError("values: expected finite costs or positive infinity")
    finite = _np.isfinite(values)
    if not _np.any(finite):
        raise NoAdmissibleCandidate("every candidate has infinite cost")
    result = _np.zeros(len(values))
    result[finite] = (1.0 / finite.sum() if gamma == 0 else
                      _policy_posterior(values[finite], float(gamma)))
    return result


@_dataclass(frozen=True, slots=True)
class Job:
    """名札は根で固定。pointsは総所要nsと対数の事後確率 (N4・C9)。"""
    label: tuple
    action: str
    start_ns: int
    points: tuple[tuple[int | None, float], ...]


@_dataclass(frozen=True, slots=True)
class World:
    """Xの時刻と状態の道は、根の全候補・全枝の和集合で固定する (R1)。"""
    model: object
    times: tuple[int, ...]
    paths: tuple[tuple[int, ...], ...]


@_dataclass(frozen=True, slots=True)
class Belief:
    """Xの周辺と所要の結合を保つ。S4dでは両者と各仕事の所要が独立 (C9)。

    Θは状態ごとのDirichletと回数で厳密に表す。所要の点を平均に置き換えない。
    """
    world: World
    log_x: tuple[float, ...]
    n: tuple[tuple[int, ...], ...]
    jobs: tuple[Job, ...]

    def kl(self, parent):
        """XだけのKL。Θの更新は含め、所要の枝のKLは足さない (C9・R1ii)。"""
        child, prior = _np.array(self.log_x), _np.array(parent.log_x)
        support = _np.isfinite(child)
        weights = _np.exp(child[support])
        with _np.errstate(over="ignore", invalid="ignore"):
            difference = child[support] - prior[support]
        _s4d_finite(difference, "KL log ratio exceeds numerical range")
        value = float(weights @ difference)
        model = self.world.model
        for i, action in enumerate(model.actions):
            if action not in model.learnable or self.n[i] == parent.n[i]:
                continue
            before, after = _np.array(parent.n[i]), _np.array(self.n[i])
            delta = after - before
            a = _ledger(model.a[action], before)
            updated = _ledger(model.a[action], after)
            log_evidence = _log_likelihood(a, delta, learnable=True)
            for j, path in enumerate(self.world.paths):
                if not _np.isfinite(child[j]):
                    continue
                s = path[0]
                positive = delta > 0
                # log E[p(y|Θ)]と、事後でのlog p(y|Θ)の期待値の差。
                term = float(delta[positive] @ (_digamma(updated[positive, s]) -
                                               _digamma(updated[:, s].sum())))
                value += _math.exp(child[j]) * (term - log_evidence[s])
        return max(0.0, float(_s4d_finite(value, "KL exceeds numerical range")))


@_dataclass(frozen=True, slots=True)
class Context:
    now_ns: int
    time_ns: int
    O: tuple = ()
    A: tuple = ()
    root: bool = True


@_dataclass(frozen=True, slots=True)
class Branch:
    """同じEの内部の枝を合算済み。log_probabilityが有限の枝だけ (N4・C9)。"""
    E: tuple
    log_probability: float
    belief: Belief
    t_end: int
    terminal: bool


def _log_points(points):
    values = tuple((d, _math.log(p)) for d, p in points)
    normalized, _ = _s4d_normalize([p for _, p in values])
    return tuple((d, float(p)) for (d, _), p in zip(values, normalized))


def _duration_points(model, action):
    return tuple((None if d is None else _duration_ns(d), p)
                 for d, p in model.durations[action])


def _state_prior(model, reading, times):
    """対数の前向きの表で指定時刻の状態を保持し、過去の証拠で平滑化する (N6)。"""
    logs = _np.full(len(model.D), -_np.inf)
    positive = model.D > 0
    logs[positive] = _np.log(model.D[positive])
    if model.Q is None:
        logs = _s4d_log_belief(model.D, [_log_likelihood(model.a[action], reading.n[action],
            learnable=action in model.learnable) for action in model.actions])
        paths = tuple((s,) for s in range(len(model.D)))
    else:
        events = {t: [] for t in times}
        for ns, _, _, _, action, outcome in reading.sequence:
            events.setdefault(ns, []).append(_log_A(model.a[action])[model.outcomes.index(outcome)])
        table, previous = logs[None, :], 0
        for ns in sorted(events):
            if ns < previous:
                raise ValueError("lookahead: measurement precedes the origin")
            if ns > previous:
                log_B = _s4d_log_transition(model.Q, (ns - previous) / 1e9)
                table = _logsumexp(_s4d_log_product(table[:, None, :], log_B[None, :, :]), axis=-1)
            for likelihood in events[ns]:
                table = _s4d_log_product(table, likelihood)
            if ns in times:
                captured = _np.full((len(table), len(model.D), len(model.D)), -_np.inf)
                states = _np.arange(len(model.D))
                captured[:, states, states] = table
                table = captured.reshape(-1, len(model.D))
            table = _s4d_normalize(table)[0]
            previous = ns
        logs = _logsumexp(table, axis=-1)
        paths = tuple(_product(range(len(model.D)), repeat=len(times)))
    return paths, tuple(map(float, _s4d_normalize(logs)[0]))


def _initial(view, candidates, resolved):
    """根の時間・候補・X・進行中の名札を確定する。全行動のδを検査 (R5)。"""
    from .agent import _one_step_time, _hand_times, ModelFalsified
    model, reading = view.model, view.reading
    if not model.durations:
        raise ValueError("lookahead: durations are required")
    if any(_duration_ns(d) <= 0 for action in model.actions
           for d, _ in model.durations[action] if d is not None):
        raise ValueError("lookahead: every finite duration must be positive in ns")
    time = _one_step_time(view)
    if reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    pending = sorted(reading.pending.items(), key=lambda pair: str(pair[0]))
    _, time["earlier_run_pending"] = _hand_times(view, pending)
    now, deadline = view.now_ns, view.now_ns + resolved.H_ns
    time["deadline_ns"] = deadline
    jobs, ranks = [], {}
    for ref, action in pending:
        starts, runs = reading.started[ref], reading._started_runs[ref]
        start = starts[0] if starts else now
        group = (action, start)
        rank = ranks.get(group, 0)
        ranks[group] = rank + 1
        label = ("pending", action, start - now, rank)
        observed = (reading.timeline.run_end_ns[runs[0]] if runs and
                    runs[0] != reading.timeline.runs[-1] else view.observed_ns)
        points = _remaining(_duration_points(model, action), max(0, observed - start) if starts else 0)
        jobs.append(Job(label, action, start, _log_points(points)))
    # 到着した時だけ次を始める。候補外の行動から時刻を増やさない。
    starts, todo, times = {now}, [now], set()
    while todo:
        start = todo.pop()
        for action in candidates:
            for d, _ in _duration_points(model, action):
                if d is not None and start + d <= deadline:
                    end = start + d
                    times.add(start if model.measures[action] == "start" else end)
                    if end not in starts:
                        starts.add(end)
                        todo.append(end)
    for job in jobs:
        for d, _ in job.points:
            if d is not None and job.start_ns + d <= deadline:
                times.add(job.start_ns if model.measures[job.action] == "start" else job.start_ns + d)
    times = tuple(sorted(times))
    try:
        paths, logs = _state_prior(model, reading, times)
    except _ModelViolation as exc:
        raise ModelFalsified("the model cannot explain the facts") from exc
    world = World(model, times, paths)
    belief = Belief(world, logs, tuple(tuple(map(int, reading.n[a])) for a in model.actions), tuple(jobs))
    return Context(now, now), belief, time


def _observed(belief, events, now_ns):
    """Eの報告を条件にする。極小でも有限のlog確率の枝と、Θの更新を残す。"""
    world, model = belief.world, belief.world.model
    logs, counts = _np.array(belief.log_x), [list(n) for n in belief.n]
    mass = 0.0
    jobs = {job.label: job for job in belief.jobs}
    for dt, label, action, outcome in events:
        i, o = model.actions.index(action), model.outcomes.index(outcome)
        a = _ledger(model.a[action], _np.array(counts[i])) if action in model.learnable else model.a[action]
        likelihood = _log_A(a)[o]
        ns = jobs[label].start_ns if model.measures[action] == "start" else now_ns + dt
        column = 0 if model.Q is None else world.times.index(ns)
        next_logs = _s4d_log_product(logs, _np.array([likelihood[path[column]] for path in world.paths]))
        total = float(_logsumexp(next_logs))
        if not _math.isfinite(total):
            return None
        mass = float(_s4d_log_product(mass, total))
        logs = _s4d_normalize(next_logs)[0]
        counts[i][o] += 1
    return mass, _replace(belief, log_x=tuple(map(float, logs)), n=tuple(map(tuple, counts)))


def branches(eta: Context, belief: Belief, action: str, deadline_ns: int) -> tuple[Branch, ...]:
    """(η,b,a,T)からEごとの枝を返す。t′は答え、所要の理由は観測でない (C9)。

    根のO₀・同時の報告・結果のない初手の間の報告も含む。子の未着は厳密な>。
    """
    model = belief.world.model
    label = ("new", len(eta.A))
    new = Job(label, action, eta.time_ns, _log_points(_duration_points(model, action)))
    jobs = (*belief.jobs, new)
    seen = {event[1] for event in eta.O}
    active = [job for job in jobs if job.label not in seen]
    grouped = {}
    for combination in _product(*(job.points for job in active)):
        duration = combination[-1][0]
        terminal = duration is None or eta.time_ns + duration > deadline_ns
        end = deadline_ns if terminal else eta.time_ns + duration
        skeleton = tuple(sorted(((job.start_ns + d - eta.now_ns, job.label, job.action)
            for job, (d, _) in zip(active, combination) if d is not None and job.start_ns + d <= end),
            key=lambda event: (event[0], _key(event[1]))))
        weight = float(_s4d_log_product(*(p for _, p in combination)))
        grouped.setdefault((skeleton, end, terminal), []).append((weight, combination))
    result = []
    for (skeleton, end, terminal), rows in grouped.items():
        normalized, mass = _s4d_normalize([weight for weight, _ in rows])
        post = {}
        for i, job in enumerate(active):
            points = []
            for d, _ in job.points:
                weights = [weight for weight, (_, combination) in zip(normalized, rows)
                           if combination[i][0] == d]
                if weights:
                    points.append((d, float(_logsumexp(weights))))
            post[job.label] = _replace(job, points=tuple(points))
        child = _replace(belief, jobs=tuple(post.get(job.label, job) for job in jobs))
        for outcomes in _product(model.outcomes, repeat=len(skeleton)):
            E = tuple((*event, outcome) for event, outcome in zip(skeleton, outcomes))
            update = _observed(child, E, eta.now_ns)
            if update is not None:
                log_q, posterior = update
                result.append(Branch(E, float(_s4d_log_product(mass, log_q)), posterior, end, terminal))
    return tuple(result)


def _advance(eta, action, branch):
    return Context(eta.now_ns, branch.t_end, eta.O + branch.E,
                   eta.A + ((eta.time_ns - eta.now_ns, ("new", len(eta.A)), action),), False)


@_dataclass(frozen=True, slots=True)
class Value:
    expected_cost: float
    information: float | None

    @property
    def J(self):
        return _math.inf if self.information is None else self.expected_cost - self.information


def _action_value(eta, belief, action, deadline_ns, candidates, resolved):
    """J=-I+ΣqV。費用は終端だけ。正の枝の禁止はunderflowでも落とさない (R1〜4)。"""
    costs, informations, undefined = [], [], False
    for branch in branches(eta, belief, action, deadline_ns):
        child = _advance(eta, action, branch)
        if branch.terminal:
            continuation = Value(_cost(resolved, _EvaluationInput(
                evaluation="lookahead", O=child.O, A=child.A)), 0.0)
        else:
            values = [_action_value(child, branch.belief, a, deadline_ns, candidates, resolved)
                      for a in candidates]
            try:
                rho = _policy([v.J for v in values], resolved.gamma)
            except NoAdmissibleCandidate:
                continuation = Value(_math.inf, None)
            else:
                continuation = Value(
                    _s4d_cost_sum(_s4d_weighted_cost(p, v.expected_cost) for p, v in zip(rho, values) if p > 0),
                    _s4d_fsum((p * v.information for p, v in zip(rho, values) if p > 0),
                               "expected information exceeds numerical range"))
        p = _math.exp(branch.log_probability)
        costs.append(_s4d_weighted_cost(p, continuation.expected_cost))
        if continuation.information is None:
            undefined = True
        else:
            informations.append(float(_s4d_finite(p * (branch.belief.kl(belief) + continuation.information),
                                                  "expected information exceeds numerical range")))
    return Value(_s4d_cost_sum(costs), None if undefined else
                 _s4d_fsum(informations, "expected information sum exceeds numerical range"))


def evaluate(view, candidates, resolved, *, u):
    """根の候補・好み・締切で木を評価し、未定義理由は候補順の配列にする (C8)。"""
    from .agent import Draft as _Draft
    from .records import Payload as _Payload
    from .s4d_contracts import DECISION as _DECISION
    eta, belief, time = _initial(view, candidates, resolved)
    values = [_action_value(eta, belief, a, time["deadline_ns"], candidates, resolved) for a in candidates]
    q_pi = _policy([v.J for v in values], resolved.gamma)
    encode = lambda v: "+inf" if v == _math.inf else float(v)
    content = {"evaluation": "lookahead", "items": [
        {"id": str(item.id), "rule": {"name": item.rule.name, "version": item.rule.version}}
        for item in resolved.items], "style": str(resolved.style), "H_ns": resolved.H_ns,
        "gamma": resolved.gamma, "candidates": list(candidates), "u": float(u),
        "chosen": candidates[_select(q_pi, u)], "J": [encode(v.J) for v in values],
        "q_pi": q_pi.tolist(), "expected_cost": [encode(v.expected_cost) for v in values],
        "information": [v.information for v in values], "time": time}
    if any(v.information is None for v in values):
        content["undefined_reason"] = ["no_admissible_continuation" if v.information is None else None
                                       for v in values]
    return _Draft(parents=view.frontier, belief=view.belief, content=_Payload.json(content),
                  contract=_DECISION, preference_inputs=tuple(item.id for item in resolved.items) + (resolved.style,))
