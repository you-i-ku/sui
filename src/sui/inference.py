"""回数からの信念・帳面と、評価・選択の純粋な計算。"""

from collections.abc import Iterable as _Iterable

import numpy as _np
from scipy.special import betaln as _betaln
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

