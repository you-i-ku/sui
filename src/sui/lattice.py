"""測った時刻の状態と、学ぶ表の整数の数え上げの結合。"""

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field
from types import MappingProxyType as _MappingProxyType
import math as _math

import numpy as _np

from .inference import (
    _log_A, _s4d_finite, _s4d_log_prior, _s4d_log_product,
    _s4d_log_transition, _s4d_normalize, _s4d_novelty, _s4d_fsum,
    _s4d_cost_sum, _s4d_weighted_cost,
)
from .model import GenerativeModel as _GenerativeModel


Key = tuple[int, tuple[int, ...]]


@_dataclass(frozen=True, slots=True, kw_only=True)
class LatticeStats:
    """同時に保持したキーの最大数・評価した枝・最後の成分の数。"""

    max_keys: int
    evaluated_branches: int
    final_keys: int


def _normalize(table, *, key=None):
    """作業中の表を正準の順で正規化する。大きな共通の値は先に引く。"""
    keys = sorted(table, key=key)
    weights, _ = _s4d_normalize([table[key] for key in keys])
    for key, value in zip(keys, weights):
        if _math.isfinite(value):
            table[key] = float(value)
        else:
            del table[key]
    return table


def _column(model, counts, action, state):
    """行動・観測・状態の順の整数から、その列の事後を作る。"""
    states, outcomes = len(model.states), len(model.outcomes)
    offset = sorted(model.learnable).index(action) * outcomes * states
    additions = _np.array([counts[offset + outcome * states + state]
                           for outcome in range(outcomes)], dtype=float)
    with _np.errstate(over="ignore"):
        result = model.a[action][:, state] + additions
    return _s4d_finite(result, "lattice counts exceed numerical range")


@_dataclass(frozen=True, slots=True, kw_only=True)
class LatticeBelief:
    """正準のキーの対数の重み。平均は説明用で、更新の代わりにはしない。"""

    log_w: _Mapping[Key, float]
    stats: LatticeStats
    _model: _GenerativeModel = _field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "log_w", _MappingProxyType(dict(sorted(self.log_w.items()))))

    def marginal_state(self) -> _np.ndarray:
        """今の状態の対数の周辺。"""
        logs = _np.full(len(self._model.states), -_np.inf)
        for (state, _), weight in self.log_w.items():
            logs[state] = _np.logaddexp(logs[state], weight)
        return _s4d_normalize(logs)[0]

    def theta_mean(self) -> dict[str, _np.ndarray]:
        """学ぶ表の全列の無条件の事後の期待値。仮説ごとの帳面とは別。"""
        model = self._model
        result = {}
        for action in sorted(model.learnable):
            logs = _np.full_like(model.a[action], -_np.inf)
            for (_, counts), weight in self.log_w.items():
                for state in range(len(model.states)):
                    column = _column(model, counts, action, state)
                    mean = _log_A(column[:, None])[:, 0]
                    logs[:, state] = _np.logaddexp(
                        logs[:, state], _s4d_log_product(weight, mean))
            with _np.errstate(under="ignore"):
                result[action] = _np.exp(logs)
        return result

    def components(self) -> int:
        return len(self.log_w)


def _add(table, key, weight):
    if _math.isfinite(weight):
        table[key] = float(_np.logaddexp(table.get(key, -_math.inf), weight))


def _predict(table, transition):
    result = {}
    for (state, counts), weight in sorted(table.items()):
        for following in range(len(transition)):
            _add(result, (following, counts),
                 float(_s4d_log_product(weight, transition[following, state])))
    return result


def _emission(model, counts, action, outcome, state, fixed):
    """一つの状態・割り振りでの尤度と更新後の整数の回数。"""
    if action not in model.learnable:
        return fixed[state], counts
    if model.a[action][outcome, state] == 0:
        return -_math.inf, counts
    column = _column(model, counts, action, state)
    likelihood = _log_A(column[:, None])[outcome, 0]
    offset = (sorted(model.learnable).index(action) * len(model.outcomes) + outcome)
    offset = offset * len(model.states) + state
    updated = list(counts)
    updated[offset] += 1
    return likelihood, tuple(updated)


def _observe(model, table, action, outcome):
    result = {}
    fixed = None if action in model.learnable else _log_A(model.a[action])[outcome]
    for (state, counts), weight in sorted(table.items()):
        likelihood, counts = _emission(model, counts, action, outcome, state, fixed)
        _add(result, (state, counts), float(_s4d_log_product(weight, likelihood)))
    return result


def learn(model, sequence, *, until_ns=None, _log_transition=None) -> LatticeBelief:
    """Reading.sequenceを起点0から濾過する。時刻はns、差し替える遷移の引数は秒。

    最後の観測 (空なら0) で止め、until_nsがあればそこまで予測する。
    全成分が不可能ならModelViolation。枝の数による打ち切りはしない。
    """
    states = len(model.states)
    counts = (0,) * (len(model.learnable) * len(model.outcomes) * states)
    table = _normalize({(state, counts): float(weight)
                        for state, weight in enumerate(_s4d_log_prior(model.D))
                        if _math.isfinite(weight)})
    maximum, previous = len(table), 0
    generator = _np.zeros((states, states)) if model.Q is None else model.Q
    transition = (_log_transition if _log_transition is not None else
                  lambda dt: _s4d_log_transition(generator, dt))

    def replace_table(updated):
        nonlocal table, maximum
        # 更新中は前後の表を同時に持つ。正規化では表を増やさない。
        maximum = max(maximum, len(table) + len(updated))
        table = _normalize(updated)

    for ns, _, _, _, action, outcome in sequence:
        if type(ns) is not int or ns < previous:
            raise ValueError("sequence: expected nondecreasing integer times")
        if ns > previous:
            replace_table(_predict(table, transition((ns - previous) / 1e9)))
        replace_table(_observe(model, table, action, model.outcomes.index(outcome)))
        previous = ns
    if until_ns is not None:
        if type(until_ns) is not int or until_ns < previous:
            raise ValueError("until_ns: expected an integer not before the last observation")
        if until_ns > previous:
            replace_table(_predict(table, transition((until_ns - previous) / 1e9)))
    # 最後の作業表と、LatticeBelief内の写しも同時に保持する。
    maximum = max(maximum, 2 * len(table))
    return LatticeBelief(log_w=table, _model=model,
        stats=LatticeStats(max_keys=maximum, evaluated_branches=0, final_keys=len(table)))


HandKey = tuple[tuple[int | None, ...], int, tuple[int, ...]]


def _hand_key(key):
    # 報告はmodel.outcomesの番号順。永久未着のNoneは最後。
    return (tuple((outcome is None, outcome) for outcome in key[0]), *key[1:])


@_dataclass(frozen=True, slots=True, kw_only=True)
class HandTable:
    """(報告の組z, 候補の測定時の状態k, N)の正規化した結合。zは観測の番号。"""

    log_w: _Mapping[HandKey, float]
    stats: LatticeStats

    def __post_init__(self):
        object.__setattr__(self, "log_w", _MappingProxyType(
            {key: self.log_w[key] for key in sorted(self.log_w, key=_hand_key)}))


def hand_table(model, history, pending, candidate, *, capture_ns) -> HandTable:
    """所要の一枝を、起点0から測定順に作り直す。最後の状態jは周辺化する。

    historyは(ns, 行動, 観測名)、pendingは(仕事の名札, 行動, ns|None)。
    同時刻は履歴・名札順の仮の報告・候補の写し取り。候補とNoneはNを増やさない。
    """
    if candidate not in model.actions:
        raise ValueError("candidate: unknown action")
    events = {}

    def event(ns, kind, value):
        if type(ns) is not int or ns < 0:
            raise ValueError("hand: expected nonnegative integer measurement times")
        events.setdefault(ns, []).append((kind, value))

    for ns, action, outcome in history:
        event(ns, "history", (action, model.outcomes.index(outcome)))
    pending = tuple(sorted(pending, key=lambda item: str(item[0])))
    for index, (_, action, ns) in enumerate(pending):
        if ns is not None:
            event(ns, "pending", (index, action))
    event(capture_ns, "candidate", None)

    states = len(model.states)
    counts = (0,) * (len(model.learnable) * len(model.outcomes) * states)
    reports = (None,) * len(pending)
    table = _normalize({(reports, -1, state, counts): float(weight)
                        for state, weight in enumerate(_s4d_log_prior(model.D))
                        if _math.isfinite(weight)}, key=_hand_key)
    maximum, previous = len(table), 0
    generator = _np.zeros((states, states)) if model.Q is None else model.Q
    fixed = {action: _log_A(model.a[action]) for action in model.actions
             if action not in model.learnable}

    def replace_table(updated):
        nonlocal table, maximum
        maximum = max(maximum, len(table) + len(updated))
        table = _normalize(updated, key=_hand_key)

    for ns in sorted(events):
        if ns > previous:
            transition = _s4d_log_transition(generator, (ns - previous) / 1e9)
            updated = {}
            for z, captured, state, counts in sorted(table, key=_hand_key):
                weight = table[z, captured, state, counts]
                for following in range(states):
                    _add(updated, (z, captured, following, counts),
                         float(_s4d_log_product(weight, transition[following, state])))
            replace_table(updated)
        for kind, value in events[ns]:
            updated = {}
            for z, captured, state, counts in sorted(table, key=_hand_key):
                weight = table[z, captured, state, counts]
                if kind == "candidate":
                    _add(updated, (z, state, state, counts), weight)
                    continue
                if kind == "history":
                    action, outcome = value
                    choices = ((z, outcome),)
                else:
                    index, action = value
                    choices = ((z[:index] + (outcome,) + z[index + 1:], outcome)
                               for outcome in range(len(model.outcomes)))
                for reports, outcome in choices:
                    likelihood, incremented = _emission(model, counts, action, outcome, state,
                        None if action in model.learnable else fixed[action][outcome])
                    _add(updated, (reports, captured, state, incremented),
                         float(_s4d_log_product(weight, likelihood)))
            replace_table(updated)
        previous = ns
    # 今の状態jを足し合わせ、写し取ったkと全証拠を反映したNを残す。
    updated = {}
    for z, captured, state, counts in sorted(table, key=_hand_key):
        _add(updated, (z, captured, counts), table[z, captured, state, counts])
    replace_table(updated)
    # 作業表から不変の結果へ写す瞬間も、learnと同じ尺度で数える。
    maximum = max(maximum, 2 * len(table))
    return HandTable(log_w=table, stats=LatticeStats(max_keys=maximum,
        evaluated_branches=len({z for z, _, _ in table}), final_keys=len(table)))


def one_step_components(model, table, candidate, costs) -> tuple[float, float]:
    """一つの所要の枝bの費用・情報を、報告の組zの確率で平均する。"""
    costs = _np.asarray(costs, dtype=float)
    if (costs.shape != (len(model.outcomes),)
            or _np.any(_np.isnan(costs) | _np.isneginf(costs))):
        raise ValueError("costs: expected one finite cost or positive infinity per outcome")
    groups = {}
    keys = sorted(table.log_w, key=_hand_key)
    normalized, _ = _s4d_normalize([table.log_w[key] for key in keys])
    for (z, state, counts), weight in zip(keys, normalized):
        if _math.isfinite(weight):
            groups.setdefault(z, []).append((state, counts, float(weight)))
    expected, information = [], []
    learning = candidate in model.learnable
    for group in groups.values():
        conditional, mass = _s4d_normalize([weight for _, _, weight in group])
        components = []
        predicted = _np.full(len(model.outcomes), -_np.inf)
        for (state, counts, _), weight in zip(group, conditional):
            column = (_column(model, counts, candidate, state) if learning
                      else model.a[candidate][:, state])[:, None]
            mean = _log_A(column)[:, 0]
            joint = _s4d_log_product(weight, mean)
            predicted = _np.logaddexp(predicted, joint)
            novelty = _s4d_novelty(_np.array([0.]), column) if learning else 0.0
            components.append((float(weight), mean, joint, novelty))
        support = _np.isfinite(predicted)
        if _np.any(support & _np.isposinf(costs)):
            branch_cost = _math.inf
        else:
            branch_cost = _s4d_cost_sum(
                _s4d_weighted_cost(_math.exp(float(probability)), cost)
                for probability, cost in zip(predicted[support], costs[support]))
        # I = E_r[KL(mu_r || q) + H(mu_r) - e_r]。固定の候補にはnoveltyを足さない。
        terms = []
        for weight, mean, joint, novelty in components:
            support = _np.isfinite(mean)
            with _np.errstate(over="ignore", invalid="ignore", under="ignore"):
                values = _np.exp(joint[support]) * (mean[support] - predicted[support])
            _s4d_finite(values, "lattice information exceeds numerical range")
            terms.extend(map(float, values))
            terms.append(_math.exp(weight) * novelty)
        branch_information = _s4d_fsum(terms, "lattice information exceeds numerical range")
        # 正のrhoが普通の数では0に丸まっても、その枝の禁止は消さない。
        expected.append(_s4d_weighted_cost(_math.exp(mass), branch_cost))
        information.append(_math.exp(mass) * branch_information)
    return (_s4d_cost_sum(expected),
            _s4d_fsum(information, "expected information exceeds numerical range"))
