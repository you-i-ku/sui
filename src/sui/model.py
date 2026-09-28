"""有限の状態・観測・行動を持つ生成モデル。"""

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from types import MappingProxyType as _MappingProxyType

import numpy as _np


def _array(value: _np.ndarray, name: str, ndim: int) -> _np.ndarray:
    if not isinstance(value, _np.ndarray) or value.dtype.kind not in "iuf":
        raise TypeError(f"{name}: expected a real numeric ndarray")
    result = _np.array(value, dtype=_np.float64, copy=True)
    if result.ndim != ndim or 0 in result.shape or not _np.all(_np.isfinite(result)):
        raise ValueError(f"{name}: expected nonempty finite {ndim}-dimensional array")
    return result


def _probability(value: _np.ndarray, name: str) -> _np.ndarray:
    result = _array(value, name, 1)
    with _np.errstate(over="ignore"):
        total = result.sum()
    if _np.any(result < 0) or not _np.isclose(total, 1.0, atol=1e-12, rtol=0):
        raise ValueError(f"{name}: expected nonnegative probabilities summing to 1")
    return result


def _counts(value: _np.ndarray) -> _np.ndarray:
    result = _array(value, "a", 2)
    if _np.any(result < 0) or not _np.all(_np.any(result > 0, axis=0)):
        raise ValueError("a: expected nonnegative counts with positive column sums")
    return result


def _logsumexp(value: _np.ndarray) -> float:
    maximum = value.max()
    with _np.errstate(over="ignore", under="ignore"):
        return float(maximum + _np.log(_np.exp(value - maximum).sum()))


def _log_preferences(value: _np.ndarray) -> _np.ndarray:
    result = _array(value, "log_C", 1)
    if not _np.isclose(_logsumexp(result), 0.0, atol=1e-12, rtol=0):
        raise ValueError("log_C: expected logsumexp equal to 0")
    return result


def _positive_float(value: float, name: str) -> None:
    if not isinstance(value, float):
        raise TypeError(f"{name}: expected float")
    if not _np.isfinite(value) or value <= 0:
        raise ValueError(f"{name}: expected finite positive float")


def _readonly(value: _np.ndarray) -> _np.ndarray:
    result = _np.array(value, dtype=_np.float64, copy=True)
    result.setflags(write=False)
    return result


def _names(value: tuple[str, ...], name: str) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{name}: expected tuple")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name}: expected str items")
    if not value or any(not item for item in value) or len(set(value)) != len(value):
        raise ValueError(f"{name}: expected nonempty unique names")


@_dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class GenerativeModel:
    """名前つきの軸と、初期の数え上げ・信念・好み。"""

    states: tuple[str, ...]
    outcomes: tuple[str, ...]
    actions: tuple[str, ...]
    a: _Mapping[str, _np.ndarray]
    learnable: frozenset[str]
    D: _np.ndarray
    log_C: _np.ndarray
    gamma: float

    def __post_init__(self) -> None:
        for name in ("states", "outcomes", "actions"):
            _names(getattr(self, name), name)
        if not isinstance(self.a, _Mapping):
            raise TypeError("a: expected Mapping")
        if any(not isinstance(key, str) for key in self.a):
            raise TypeError("a: expected str keys")
        if set(self.a) != set(self.actions):
            raise ValueError("a: expected exactly the actions as keys")
        if not isinstance(self.learnable, frozenset):
            raise TypeError("learnable: expected frozenset")
        if any(not isinstance(action, str) for action in self.learnable):
            raise TypeError("learnable: expected str items")
        if not self.learnable.issubset(self.actions):
            raise ValueError("learnable: expected a subset of actions")
        counts = {}
        for action in self.actions:
            value = _counts(self.a[action])
            if value.shape != (len(self.outcomes), len(self.states)):
                raise ValueError("a: expected shape (outcomes, states)")
            counts[action] = _readonly(value)
        prior = _probability(self.D, "D")
        preferences = _log_preferences(self.log_C)
        if len(prior) != len(self.states) or len(preferences) != len(self.outcomes):
            raise ValueError("D/log_C: length does not match the named axis")
        _positive_float(self.gamma, "gamma")
        object.__setattr__(self, "a", _MappingProxyType(counts))
        object.__setattr__(self, "D", _readonly(prior))
        object.__setattr__(self, "log_C", _readonly(preferences))
