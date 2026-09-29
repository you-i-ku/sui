"""有限の状態・観測・行動を持つ生成モデル。"""

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field
from types import MappingProxyType as _MappingProxyType
import hashlib as _hashlib
import json as _json

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


def _generator(value: _np.ndarray) -> _np.ndarray:
    result = _array(value, "Q", 2)
    if result.shape[0] != result.shape[1]:
        raise ValueError("Q: expected a square matrix")
    off = result.copy()
    _np.fill_diagonal(off, 0.0)
    with _np.errstate(over="ignore", invalid="ignore"):
        totals = off.sum(axis=0)
        sums = result.sum(axis=0)
    if (_np.any(off < 0) or not _np.all(_np.isfinite(totals))
            or not _np.all(_np.abs(sums) <= 1e-12 * _np.maximum(1.0, totals))
            or not _np.any(result)):
        raise ValueError("Q: expected nonzero generator with nonnegative off-diagonals and zero column sums")
    return result


@_dataclass(frozen=True, slots=True, kw_only=True)
class ArrivalPrior:
    """状態・自分の行動によらない到着率の Gamma 事前 (M10・H1)。"""

    alpha: float
    beta_s: float

    def __post_init__(self) -> None:
        _positive_float(self.alpha, "alpha")
        _positive_float(self.beta_s, "beta_s")


@_dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class GenerativeModel:
    """名前つきの軸と、初期の数え上げ・信念・好み。

    Q が無ければ回数から厳密に学ぶ (S1c)。Q は列から行への率で、
    Q と学習の同時は S4b。時間モデルのDは最初の起動時、arrivalsは状態と独立 (M10〜M12)。
    """

    states: tuple[str, ...]
    outcomes: tuple[str, ...]
    actions: tuple[str, ...]
    a: _Mapping[str, _np.ndarray]
    learnable: frozenset[str]
    D: _np.ndarray
    log_C: _np.ndarray
    gamma: float
    Q: _np.ndarray | None = None
    arrivals: _Mapping[str, ArrivalPrior] = _field(default_factory=dict)

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
            if action in self.learnable:
                with _np.errstate(over="ignore"):
                    totals = value.sum(axis=0)
                if not _np.all(_np.isfinite(totals)):
                    raise ValueError("a: learnable column sums must be finite")
            counts[action] = _readonly(value)
        prior = _probability(self.D, "D")
        preferences = _log_preferences(self.log_C)
        if len(prior) != len(self.states) or len(preferences) != len(self.outcomes):
            raise ValueError("D/log_C: length does not match the named axis")
        _positive_float(self.gamma, "gamma")
        if self.Q is not None:
            generator = _generator(self.Q)
            if generator.shape != (len(self.states), len(self.states)):
                raise ValueError("Q: shape must match states")
            if self.learnable:
                raise ValueError("learning under a changing state is S4b")
            object.__setattr__(self, "Q", _readonly(generator))
        if not isinstance(self.arrivals, _Mapping):
            raise TypeError("arrivals: expected Mapping")
        for route, prior_value in self.arrivals.items():
            if not isinstance(route, str):
                raise TypeError("arrivals: expected str routes")
            if not route or route == "membrane":
                raise ValueError("arrivals: expected nonempty non-membrane routes")
            if not isinstance(prior_value, ArrivalPrior):
                raise TypeError("arrivals: expected ArrivalPrior")
        object.__setattr__(self, "arrivals", _MappingProxyType(dict(self.arrivals)))
        object.__setattr__(self, "a", _MappingProxyType(counts))
        object.__setattr__(self, "D", _readonly(prior))
        object.__setattr__(self, "log_C", _readonly(preferences))


def model_json(model: GenerativeModel) -> bytes:
    """モデルの全入力を、参照の材料となる正準 JSON にする。"""
    material = {
        "scheme": "sui.model.1", "states": list(model.states),
        "outcomes": list(model.outcomes), "actions": list(model.actions),
        "a": {action: value.tolist() for action, value in model.a.items()},
        "learnable": sorted(model.learnable), "D": model.D.tolist(),
        "log_C": model.log_C.tolist(), "gamma": float(model.gamma),
    }
    if model.Q is not None or model.arrivals:
        material.update(scheme="sui.model.2", Q=None if model.Q is None else model.Q.tolist(),
                        arrivals={route: {"alpha": prior.alpha, "beta_s": prior.beta_s}
                                  for route, prior in model.arrivals.items()})
    return _json.dumps(material, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")


def model_from_json(data: bytes) -> GenerativeModel:
    """正準 JSON を値を変えずに戻す。非正準の入力も拒む。"""
    try:
        if not isinstance(data, bytes):
            raise ValueError("model: expected bytes")
        value = _json.loads(data)
        keys = {"scheme", "states", "outcomes", "actions", "a", "learnable",
                "D", "log_C", "gamma"}
        if isinstance(value, dict) and value.get("scheme") == "sui.model.2":
            keys |= {"Q", "arrivals"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("model: unexpected keys")
        if value["scheme"] not in ("sui.model.1", "sui.model.2"):
            raise ValueError("model: unsupported scheme")
        model = GenerativeModel(
            states=tuple(value["states"]), outcomes=tuple(value["outcomes"]),
            actions=tuple(value["actions"]),
            a={key: _np.array(array, dtype=_np.float64) for key, array in value["a"].items()},
            learnable=frozenset(value["learnable"]),
            D=_np.array(value["D"], dtype=_np.float64),
            log_C=_np.array(value["log_C"], dtype=_np.float64), gamma=float(value["gamma"]),
            Q=None if value.get("Q") is None else _np.array(value["Q"], dtype=_np.float64),
            arrivals={route: ArrivalPrior(**prior) for route, prior in value.get("arrivals", {}).items()},
        )
        if model_json(model) != data:
            raise ValueError("model: expected canonical encoding")
        return model
    except (TypeError, KeyError, AttributeError, OverflowError, ValueError) as exc:
        raise ValueError(f"invalid model: {exc}") from exc


def model_ref(model: GenerativeModel) -> str:
    return "sha256:" + _hashlib.sha256(model_json(model)).hexdigest()
