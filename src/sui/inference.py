"""信念・評価・選択・数え上げの純粋な計算。"""

import numpy as _np
from scipy.special import digamma as _digamma

from .model import (
    _array, _counts, _log_preferences, _logsumexp, _positive_float, _probability,
)


class ModelViolation(ValueError):
    """モデル上で確率 0 の観測。"""


def _likelihood(value: _np.ndarray, states: int) -> _np.ndarray:
    result = _array(value, "A", 2)
    with _np.errstate(over="ignore"):
        totals = result.sum(axis=0)
    if (result.shape[1] != states or _np.any(result < 0)
            or not _np.allclose(totals, 1.0, atol=1e-12, rtol=0)):
        raise ValueError("A: expected column probabilities matching q")
    return result


def _outcome(outcome: int, size: int) -> None:
    if not isinstance(outcome, int) or isinstance(outcome, bool):
        raise TypeError("outcome: expected int, not bool")
    if not 0 <= outcome < size:
        raise ValueError("outcome: outside the outcome axis")


def expected_A(a: _np.ndarray) -> _np.ndarray:
    """数え上げを列ごとの確率にする。"""
    a = _counts(a)
    # 大きな有限の数え上げでも、列の和をあふれさせない。
    scaled = a / a.max(axis=0)
    return scaled / scaled.sum(axis=0)


def posterior(q: _np.ndarray, A: _np.ndarray, outcome: int) -> _np.ndarray:
    """構造上の 0 を保ち、対数でベイズ更新する。"""
    q = _probability(q, "q")
    A = _likelihood(A, len(q))
    _outcome(outcome, A.shape[0])
    support = (q > 0) & (A[outcome] > 0)
    if not _np.any(support):
        raise ModelViolation("outcome: zero probability under the current belief")
    log_joint = _np.log(q[support]) + _np.log(A[outcome, support])
    result = _np.zeros_like(q)
    result[support] = _np.exp(log_joint - _logsumexp(log_joint))
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


def learn(a: _np.ndarray, q_post: _np.ndarray, outcome: int) -> _np.ndarray:
    """構造上の 0 を守り、事後の信念を観測の行に足す。"""
    a = _counts(a)
    q_post = _probability(q_post, "q_post")
    _outcome(outcome, a.shape[0])
    if len(q_post) != a.shape[1]:
        raise ValueError("q_post: length does not match states")
    if _np.any((a[outcome] == 0) & (q_post > 0)):
        raise ValueError("q_post: positive probability at a structural zero")
    a[outcome] += q_post
    return a
