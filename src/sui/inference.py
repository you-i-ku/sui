"""回数・時間つきの観測からの信念と、評価・選択の純粋な計算。"""

from collections.abc import Iterable as _Iterable
import math as _math
from itertools import product as _product

import numpy as _np
from scipy.special import betaln as _betaln
from scipy.special import digamma as _digamma
from scipy.special import logsumexp as _scipy_logsumexp
from scipy.linalg import expm as _expm

from .model import (
    _array, _counts, _log_preferences, _logsumexp, _positive_float, _probability,
    _generator,
)


class ModelViolation(ValueError):
    """モデル上で確率 0 の観測。"""


def remaining(duration_ns: tuple[tuple[int, float], ...],
              unseen_ns: int) -> tuple[tuple[int, float], ...]:
    """未到着を確かめた所までで絞り、総所要と正規化した重みを返す (E1・E3・E4)。"""
    points = tuple((ns, p) for ns, p in duration_ns if ns >= unseen_ns)
    if not points:
        raise ModelViolation("the hand's time model cannot explain the facts")
    total = _math.fsum(p for _, p in points)
    return tuple((ns, p / total) for ns, p in points)


def _hand_joint_log(D, Q, history, pending, candidate_ns):
    """観測の組×候補時の状態×現在の状態を対数で運ぶ (I1・I2・P1・F2)。

    過去の測定も後の証拠で平滑化し、最後だけ現在の状態を周辺化する。
    """
    events = {}
    for ns, likelihood in history:
        events.setdefault(ns, []).append(("history", likelihood))
    for ns, a in pending:
        events.setdefault(ns, []).append(("pending", _log_A(a)))
    events.setdefault(candidate_ns, []).append(("candidate", None))
    table = _np.full((1, 1, len(D)), -_np.inf)
    table[0, 0, D > 0] = _np.log(D[D > 0])
    previous = 0
    for ns in sorted(events):
        if type(ns) is not int or ns < previous:
            raise ValueError("hand: expected nonnegative integer measurement times")
        if ns > previous:
            B = transition(Q, (ns - previous) / 1e9)
            log_B = _np.full_like(B, -_np.inf)
            log_B[B > 0] = _np.log(B[B > 0])
            table = _scipy_logsumexp(
                table[:, :, None, :] + log_B[None, None, :, :], axis=-1)
        for kind, value in events[ns]:
            if kind == "history":
                table = table + value[None, None, :]
            elif kind == "pending":
                table = (table[:, None, :, :] + value[None, :, None, :]).reshape(
                    -1, table.shape[1], len(D))
            else:
                captured = _np.full((len(table), len(D), len(D)), -_np.inf)
                states = _np.arange(len(D))
                captured[:, states, states] = table[:, 0, :]
                table = captured
            maximum = table.max()
            if _np.isfinite(maximum):
                table = table - maximum
        previous = ns
    joint = _scipy_logsumexp(table, axis=-1)
    total = _scipy_logsumexp(joint)
    if not _np.isfinite(total):
        raise ModelViolation("the model cannot explain the facts")
    return joint - total


def _hand_efe(D, Q, history, pending, candidate, log_C):
    """所要の直積の枝ごとに評価し、risk・ambiguity・q_oを平均する (I1〜I3・E6)。"""
    a, candidate_times = candidate
    risk, ambiguity = 0.0, 0.0
    q_o = _np.zeros(a.shape[0])
    A = expected_A(a)
    for combination in _product(*(times for _, times in pending), candidate_times):
        weight = _math.prod(p for _, p in combination)
        measured = tuple((ns, waiting_a) for (waiting_a, _), (ns, _) in
                         zip(pending, combination[:-1]))
        joint = _hand_joint_log(D, Q, history, measured, combination[-1][0])
        masses = _scipy_logsumexp(joint, axis=1)
        for log_q, mass in zip(joint, masses):
            if _np.isfinite(mass):
                probability = weight * _math.exp(float(mass))
                r, amb, obs = efe(_log_probability(log_q), A, log_C)
                risk += probability * r
                ambiguity += probability * amb
                q_o += probability * obs
    return risk, ambiguity, 0.0, q_o


def _duration(value, name):
    if not isinstance(value, float):
        raise TypeError(f"{name}: expected float")
    if not _math.isfinite(value) or value < 0:
        raise ValueError(f"{name}: expected finite nonnegative float")


def transition(Q: _np.ndarray, dt: float) -> _np.ndarray:
    """列から行への遷移。dt=0は厳密な単位行列 (Q1・Q4b)。

    expmの微小な負値だけ0にし列を正規化。-1e-12未満は数値の失敗。
    """
    Q = _generator(Q)
    _duration(dt, "dt")
    if dt == 0:
        return _np.eye(len(Q))
    with _np.errstate(over="ignore", invalid="ignore", under="ignore"):
        B = _expm(Q * dt)
    if not _np.all(_np.isfinite(B)) or _np.any(B < -1e-12):
        raise FloatingPointError("transition: invalid exponential")
    B = _np.maximum(B, 0.0)
    totals = B.sum(axis=0)
    if _np.any(totals <= 0) or not _np.all(_np.isfinite(totals)):
        raise FloatingPointError("transition: invalid column sums")
    return B / totals


def reachable(D: _np.ndarray, Q: _np.ndarray) -> _np.ndarray:
    """Dの正の支持から正の辺を何段でもたどる (Q9・Q13)。"""
    D, Q = _probability(D, "D"), _generator(Q)
    if Q.shape != (len(D), len(D)):
        raise ValueError("Q: shape must match D")
    support = D > 0
    while True:
        extended = support | _np.any(Q[:, support] > 0, axis=1)
        if _np.array_equal(extended, support):
            return support
        support = extended


def _log_A(a):
    a = _counts(a)
    logs = _np.full_like(a, -_np.inf)
    positive = a > 0
    logs[positive] = _np.log(a[positive])
    return logs - _scipy_logsumexp(logs, axis=0)


def _log_predict(log_q, Q, dt):
    if dt == 0:
        return log_q.copy()
    B = transition(Q, dt)
    logs = _np.full_like(B, -_np.inf)
    positive = B > 0
    logs[positive] = _np.log(B[positive])
    return _scipy_logsumexp(logs + log_q[None, :], axis=1)


def _log_update(log_q, likelihood):
    positive = _np.isfinite(likelihood)
    if not _np.any(positive):
        return _np.full_like(log_q, -_np.inf)
    result = log_q + (likelihood - likelihood[positive].max())
    if _np.any(_np.isfinite(result)):
        result -= result.max()
    return result


def _log_probability(log_q):
    if not _np.any(_np.isfinite(log_q)):
        raise ModelViolation("observations: zero probability under every state")
    with _np.errstate(under="ignore"):
        weights = _np.exp(log_q - log_q.max())
    return weights / weights.sum()


def filter_log(D: _np.ndarray, Q: _np.ndarray,
               sequence: _Iterable[tuple[int, _np.ndarray]]) -> _np.ndarray:
    """(軸のns, 対数尤度)を前向きに濾過し、対数のまま返す (Q2〜Q4・Q10〜Q13)。

    途中で確率に戻さない。全状態が不可能なら全成分-inf。入力は変えない。
    """
    D, Q = _probability(D, "D"), _generator(Q)
    if Q.shape != (len(D), len(D)):
        raise ValueError("Q: shape must match D")
    logs = _np.full_like(D, -_np.inf)
    logs[D > 0] = _np.log(D[D > 0])
    previous = 0
    for ns, likelihood in sequence:
        if type(ns) is not int:
            raise TypeError("sequence: expected integer nanoseconds")
        if ns < previous:
            raise ValueError("sequence: times must not go backwards")
        if not isinstance(likelihood, _np.ndarray) or likelihood.dtype.kind not in "iuf":
            raise TypeError("sequence: expected numeric log likelihood")
        if (likelihood.shape != D.shape
                or not _np.all(_np.isfinite(likelihood) | _np.isneginf(likelihood))):
            raise ValueError("sequence: invalid log likelihood")
        logs = _log_update(_log_predict(logs, Q, (ns - previous) / 1e9), likelihood)
        previous = ns
    return logs


def arrival_posterior(prior, stats) -> tuple[float, float]:
    """Gammaの形にN、率のパラメータに見た秒数を足す (H1〜H8)。"""
    return prior.alpha + stats.N, prior.beta_s + stats.T_ns / 1e9


def arrival_within(alpha: float, beta_s: float, horizon_s: float) -> float:
    """次のh秒に1回以上届く確率。h=0は0 (H11)。

    極小hの桁落ちとh/βのあふれを避ける (H11・H11b)。
    """
    _positive_float(alpha, "alpha")
    _positive_float(beta_s, "beta_s")
    _duration(horizon_s, "horizon_s")
    log_ratio = (_math.log1p(horizon_s / beta_s) if horizon_s <= beta_s else
                 _math.log(horizon_s) - _math.log(beta_s) + _math.log1p(beta_s / horizon_s))
    return -_math.expm1(-alpha * log_ratio)


def _likelihood(value: _np.ndarray, states: int) -> _np.ndarray:
    result = _array(value, "A", 2)
    with _np.errstate(over="ignore"):
        totals = result.sum(axis=0)
    if (result.shape[1] != states or _np.any(result < 0)
            or not _np.allclose(totals, 1.0, atol=1e-12, rtol=0)):
        raise ValueError("A: expected column probabilities matching q")
    return result


def _observation_counts(n: _np.ndarray, outcomes: int) -> tuple[_np.ndarray, int]:
    result = _array(n, "n", 1)
    if (result.shape != (outcomes,) or _np.any(result < 0)
            or _np.any(result != _np.floor(result))):
        raise ValueError("n: expected nonnegative integer counts matching outcomes")
    total = sum(int(value) for value in result)
    if total > 2**53 - 1:
        raise ValueError("n: total exceeds 2**53 - 1")
    return result, total


def _log_beta(x: float, n: float) -> float:
    # 非正規化数を betaln に直接渡さず、漸化式で一度だけ移す。
    if x < 1:
        return _betaln(x + 1, n) + _np.log(x + n) - _np.log(x)
    return _betaln(x, n)


def expected_A(a: _np.ndarray) -> _np.ndarray:
    """数え上げを列ごとの確率にする。"""
    a = _counts(a)
    # 大きな有限の数え上げでも、列の和をあふれさせない。
    scaled = a / a.max(axis=0)
    return scaled / scaled.sum(axis=0)


def log_likelihood(a: _np.ndarray, n: _np.ndarray, *, learnable: bool) -> _np.ndarray:
    """行動一つの回数の、状態によらない定数を除いた対数尤度。

    学ぶ行動は事前 a の Dirichlet-多項、学ばない行動は列の平均を固定した A。
    起こりえない状態は -inf。状態が時間で変わらないモデルで厳密 (S1c)。
    """
    a = _counts(a)
    n, total = _observation_counts(n, a.shape[0])
    if not isinstance(learnable, bool):
        raise TypeError("learnable: expected bool")
    if learnable:
        with _np.errstate(over="ignore"):
            column_totals = a.sum(axis=0)
            updated_totals = column_totals + total
        if not (_np.all(_np.isfinite(column_totals))
                and _np.all(_np.isfinite(updated_totals))):
            raise ValueError("a: learnable column sums and sums plus N must be finite")
    result = _np.zeros(a.shape[1], dtype=_np.float64)
    if total == 0:
        return result
    observed = n > 0
    with _np.errstate(over="ignore", invalid="ignore", under="ignore"):
        for state in range(a.shape[1]):
            column = a[:, state]
            if _np.any(column[observed] == 0):
                result[state] = -_np.inf
                continue
            if learnable:
                result[state] = _log_beta(column_totals[state], total) - sum(
                    _log_beta(x, count) for x, count in zip(column[observed], n[observed])
                )
            else:
                log_total = _logsumexp(_np.log(column[column > 0]))
                result[state] = _np.sum(n[observed] * (_np.log(column[observed]) - log_total))
            if not _np.isfinite(result[state]):
                raise FloatingPointError("log_likelihood: nonfinite value on possible support")
    return result


def belief(D: _np.ndarray, log_likelihoods: _Iterable[_np.ndarray]) -> _np.ndarray:
    """事前 D と行動ごとの対数尤度から、対数の上で状態の事後を計算する。

    共通の支持が空なら ModelViolation、支持上の数値の失敗は FloatingPointError。
    """
    D = _probability(D, "D")
    likelihoods = []
    support = D > 0
    for value in log_likelihoods:
        if not isinstance(value, _np.ndarray) or value.dtype.kind not in "iuf":
            raise TypeError("log_likelihood: expected a real numeric ndarray")
        value = _np.array(value, dtype=_np.float64, copy=True)
        if (value.shape != D.shape
                or not _np.all(_np.isfinite(value) | _np.isneginf(value))):
            raise ValueError("log_likelihood: expected matching shape and finite values or -inf")
        support &= _np.isfinite(value)
        likelihoods.append(value)
    if not _np.any(support):
        raise ModelViolation("observations: zero probability under every supported state")
    total = _np.zeros(int(support.sum()), dtype=_np.float64)
    with _np.errstate(over="ignore"):
        for value in likelihoods:
            supported = value[support]
            total += supported - supported.max()
    if not _np.all(_np.isfinite(total)):
        raise FloatingPointError("belief: nonfinite sum on possible support")
    log_joint = (total - total.max()) + _np.log(D[support])
    with _np.errstate(under="ignore"):
        weights = _np.exp(log_joint - log_joint.max())
    result = _np.zeros_like(D)
    result[support] = weights / weights.sum()
    return result


def ledger(a: _np.ndarray, n: _np.ndarray) -> _np.ndarray:
    """仮説ごとの帳面: 正の升目に回数を足し、構造上の 0 は保つ。"""
    a = _counts(a)
    n, _ = _observation_counts(n, a.shape[0])
    with _np.errstate(over="ignore"):
        result = _np.where(a > 0, a + n[:, None], 0.0)
    if not _np.all(_np.isfinite(result)):
        raise ValueError("ledger: counts must remain finite")
    return result


def efe(q: _np.ndarray, A: _np.ndarray,
        log_C: _np.ndarray) -> tuple[float, float, _np.ndarray]:
    """一回の観測のリスク・曖昧さ・予測分布を返す。"""
    q = _probability(q, "q")
    A = _likelihood(A, len(q))
    log_C = _log_preferences(log_C)
    if len(log_C) != A.shape[0]:
        raise ValueError("log_C: length does not match outcomes")
    q_o = A @ q
    positive = q_o > 0
    risk = _np.sum(q_o[positive] * (_np.log(q_o[positive]) - log_C[positive]))
    terms = _np.zeros_like(A)
    positive = A > 0
    terms[positive] = -A[positive] * _np.log(A[positive])
    ambiguity = terms.sum(axis=0) @ q
    return float(risk), float(ambiguity), q_o


def _g_series(inverse):
    """1/x から g(x) の大きな x 向け級数を計算する。"""
    square = inverse * inverse
    return inverse / 2 - square * (1 / 12 - square * (1 / 120 - square / 252))


def novelty(q: _np.ndarray, a: _np.ndarray) -> float:
    """状態が分かった時の、数え上げの期待情報利得を nat で返す。"""
    q = _probability(q, "q")
    a = _counts(a)
    if len(q) != a.shape[1]:
        raise ValueError("q: length does not match states")
    result = 0.0
    # 極小の重み・級数の項が 0 に丸まることは許す。
    with _np.errstate(under="ignore"):
        A = expected_A(a)
        for state in range(len(q)):
            support = a[:, state] > 0
            column = a[support, state]
            if len(column) == 1:
                continue  # 正の支持が一つの列は点質量。
            log_column = _np.log(column)
            log_total = _logsumexp(log_column)
            g = _np.empty_like(column)
            small = column < 1000
            g[small] = _digamma(column[small] + 1) - log_column[small]
            g[~small] = _g_series(1 / column[~small])
            if log_total < _np.log(1000):
                g_total = _digamma(_np.exp(log_total) + 1) - log_total
            else:
                g_total = _g_series(_np.exp(-log_total))
            kl = _np.maximum(g - g_total, 0.0)
            result += float(q[state] * (A[support, state] @ kl))
    return result


def policy_posterior(G: _np.ndarray, gamma: float) -> _np.ndarray:
    """桁あふれ時は計算順を変え、softmax を求める。"""
    G = _array(G, "G", 1)
    _positive_float(gamma, "gamma")
    minimum = G.min()
    with _np.errstate(over="ignore", under="ignore", invalid="ignore"):
        distances = (G - minimum) * gamma
        nonfinite = ~_np.isfinite(distances)
        if _np.any(nonfinite):
            alternative = gamma * G[nonfinite] - gamma * minimum
            distances[nonfinite] = _np.where(_np.isfinite(alternative), alternative, _np.inf)
        weights = _np.exp(-distances)
    return weights / weights.sum()


def select(probabilities: _np.ndarray, u: float) -> int:
    """累積和を厳密に超える最初の候補を選ぶ。"""
    probabilities = _probability(probabilities, "probabilities")
    if not isinstance(u, float):
        raise TypeError("u: expected float")
    if not 0 <= u < 1:
        raise ValueError("u: expected 0 <= u < 1")
    cumulative = 0.0
    for index, probability in enumerate(probabilities):
        cumulative += probability
        if u < cumulative:
            return index
    return int(_np.flatnonzero(probabilities > 0)[-1])
