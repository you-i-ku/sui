"""有限の状態・観測・行動を持つ生成モデル。"""

from collections.abc import Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field
from types import MappingProxyType as _MappingProxyType
import hashlib as _hashlib
import json as _json
import math as _math

import numpy as _np


Duration = tuple[tuple[float | None, float], ...]


def _duration_ns(seconds: float) -> int:
    """所要秒を偶数丸めでnsへ。非有限・負・あふれは拒む (M13)。"""
    if (not isinstance(seconds, float) or not _math.isfinite(seconds)
            or seconds < 0 or not _math.isfinite(seconds * 1e9)):
        raise ValueError("durations: expected finite nonnegative seconds convertible to ns")
    return round(seconds * 1e9)


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
    Q と学習の同時は S4b の格子。時間モデルのDは最初の起動時、arrivalsは状態と独立 (M10〜M12)。
    所要は全行動の有限な点と届かないNoneの分布、測る時刻はstartかreport (M13・N1)。
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
    durations: _Mapping[str, Duration] = _field(default_factory=dict)
    measures: _Mapping[str, str] = _field(default_factory=dict)
    duration_priors: _Mapping = _field(default_factory=dict)
    measure: object | None = None

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
        if not isinstance(self.durations, _Mapping) or not isinstance(self.measures, _Mapping):
            raise ValueError("durations/measures: expected mappings")
        if self.durations:
            if set(self.durations) != set(self.actions) or set(self.measures) != set(self.actions):
                raise ValueError("durations/measures: expected exactly the actions as keys")
        elif self.measures and not (self.duration_priors or isinstance(self, ProgressModel)):
            raise ValueError("measures: durations are required")
        if self.measures and (set(self.measures) != set(self.actions) or
                              any(m not in ("start", "report") for m in self.measures.values())):
            raise ValueError("measures: expected start or report for every action")
        durations = {}
        for action, points in self.durations.items():
            if not isinstance(points, tuple) or not points:
                raise ValueError("durations: expected a nonempty tuple of points")
            seen, probabilities = set(), []
            for point in points:
                if not isinstance(point, tuple) or len(point) != 2:
                    raise ValueError("durations: expected (seconds, probability) points")
                seconds, probability = point
                ns = None if seconds is None else _duration_ns(seconds)
                if ns in seen:
                    raise ValueError("durations: duplicate nanoseconds")
                seen.add(ns)
                if (not isinstance(probability, float) or not _math.isfinite(probability)
                        or probability <= 0 or probability > 1 + 1e-12):
                    raise ValueError("durations: expected finite positive probabilities")
                probabilities.append(probability)
            if abs(_math.fsum(probabilities) - 1) > 1e-12:
                raise ValueError("durations: probabilities must sum to one")
            if self.measures[action] not in ("start", "report"):
                raise ValueError("measures: expected start or report")
            durations[action] = tuple(sorted(points, key=lambda point: (point[0] is None, point[0])))
        object.__setattr__(self, "durations", _MappingProxyType(durations))
        object.__setattr__(self, "measures", _MappingProxyType(dict(self.measures)))
        if self.duration_priors:
            if self.durations:
                raise ValueError("duration_priors and durations cannot coexist")
            from .quantity import validate_model as _validate_quantity_model
            priors, measure = _validate_quantity_model(self.duration_priors, self.measure, self.actions)
            object.__setattr__(self, "duration_priors", priors)
            object.__setattr__(self, "measure", measure)
        else:
            if not isinstance(self.duration_priors, _Mapping):
                raise ValueError("duration_priors: expected Mapping")
            if self.measure is not None and not isinstance(self, ProgressModel):
                raise ValueError("measure: duration_priors are required")
            object.__setattr__(self, "duration_priors", _MappingProxyType({}))
        object.__setattr__(self, "a", _MappingProxyType(counts))
        object.__setattr__(self, "D", _readonly(prior))
        object.__setattr__(self, "log_C", _readonly(preferences))


@_dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ProgressModel(GenerativeModel):
    """model.7 world declaration, independent of the certified evaluator's scope.

    work_priors use the atomic/piecewise base encoding in the explicit work unit.
    The edges_ns/point integers are coordinates in that unit. CompletionSpec
    declares its relation to ns. General speeds/clock laws are valid declarations
    even when the public calculation cannot certify their hidden times.
    """
    completion: object
    work_priors: _Mapping

    def __post_init__(self):
        GenerativeModel.__post_init__(self)
        from .progress import CompletionSpec
        from .quantity import duration_prior, measure_prior
        if not isinstance(self.completion, CompletionSpec):
            raise ValueError("completion: expected CompletionSpec")
        if (self.completion.actions, self.completion.states) != (self.actions, self.states):
            raise ValueError("completion: action/state order differs from model")
        if self.durations or self.duration_priors:
            raise ValueError("progress: use work_priors, not duration fields")
        if not isinstance(self.work_priors, _Mapping) or set(self.work_priors) != set(self.actions):
            raise ValueError("work_priors: exactly one prior per action required")
        if set(self.measures) != set(self.actions):
            raise ValueError("progress: explicit start/report for every action required")
        object.__setattr__(self, "work_priors", _MappingProxyType({
            a: duration_prior(self.work_priors[a]) for a in self.actions}))
        object.__setattr__(self, "measure", measure_prior(self.measure))


def _joint_model(model):
    if _is_action_model(model) or _is_rate_model(model):
        return False
    return isinstance(model, ProgressModel) or bool(model.duration_priors and (model.Q is not None or model.measures))


def _work_timed(model):
    if _is_action_model(model) or _is_rate_model(model):
        return False
    return isinstance(model, ProgressModel) or bool(model.duration_priors)


def _is_action_model(model):
    from .action_model import ActionModel
    return isinstance(model, ActionModel)


def _is_rate_model(model):
    from .rate_model import RateModel
    return isinstance(model, RateModel)


@_dataclass(frozen=True, slots=True)
class EvaluationTiming:
    """公開の照会結果。評価に必要な軸・受信境界・確かめの出どころ。"""
    needs_axis: bool
    needs_receipt_boundary: bool
    needs_check_events: bool


def evaluation_timing(model):
    """採用したモデルの時間の条件を返す（台帳の最新を読まない）。"""
    if _is_action_model(model) or _is_rate_model(model):
        return EvaluationTiming(True, True, True)
    work_timed = _work_timed(model)
    receipt = bool(model.durations) or work_timed
    return EvaluationTiming(model.Q is not None or receipt, receipt, work_timed)


def _completion_json(spec):
    rational = lambda f: [f.numerator, f.denominator]
    return {"name": spec.name, "version": spec.version, "actions": list(spec.actions),
        "states": list(spec.states), "work_unit": spec.work_unit, "time_unit": spec.time_unit,
        "speed_unit": spec.speed_unit, "candidates": [[[rational(r) for r in row] for row in c]
            for c in spec.candidates], "weights": [rational(w) for w in spec.weights],
        "share": spec.share, "max_speed": rational(spec.max_speed)}


def _completion_from_json(value):
    from fractions import Fraction
    from .progress import CompletionSpec
    keys = {"name", "version", "actions", "states", "work_unit", "time_unit", "speed_unit",
            "candidates", "weights", "share", "max_speed"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("completion: unexpected keys")
    def rational(pair):
        if not isinstance(pair, list) or len(pair) != 2 or any(type(v) is not int for v in pair) or pair[1] <= 0:
            raise ValueError("completion: expected integer numerator/positive denominator")
        return Fraction(*pair)
    return CompletionSpec(**{**value, "actions": tuple(value["actions"]), "states": tuple(value["states"]),
        "candidates": tuple(tuple(tuple(rational(r) for r in row) for row in c) for c in value["candidates"]),
        "weights": tuple(rational(w) for w in value["weights"]), "max_speed": rational(value["max_speed"])})


def _has_unreachable(model: GenerativeModel) -> bool:
    return any(seconds is None for points in model.durations.values() for seconds, _ in points)


def model_json(model: GenerativeModel) -> bytes:
    """モデルの全入力を、参照の材料となる正準 JSON にする。"""
    from .rate_model import RateModel, rate_model_json
    if isinstance(model, RateModel):
        return rate_model_json(model)
    if _is_action_model(model):
        from .action_model import action_model_json
        return action_model_json(model)
    material = {
        "scheme": "sui.model.1", "states": list(model.states),
        "outcomes": list(model.outcomes), "actions": list(model.actions),
        "a": {action: value.tolist() for action, value in model.a.items()},
        "learnable": sorted(model.learnable), "D": model.D.tolist(),
        "log_C": model.log_C.tolist(), "gamma": float(model.gamma),
    }
    if model.Q is not None or model.arrivals or model.durations:
        material.update(scheme="sui.model.2", Q=None if model.Q is None else model.Q.tolist(),
                        arrivals={route: {"alpha": prior.alpha, "beta_s": prior.beta_s}
                                  for route, prior in model.arrivals.items()})
    if model.durations:
        material.update(scheme="sui.model.4" if _has_unreachable(model) else "sui.model.3",
                        durations=dict(model.durations),
                        measures=dict(model.measures))
    if model.Q is not None and model.learnable:
        material.update(scheme="sui.model.5", durations=dict(model.durations),
                        measures=dict(model.measures))
    if model.duration_priors:
        material.update(scheme="sui.model.6", Q=None if model.Q is None else model.Q.tolist(),
                        arrivals={route: {"alpha": prior.alpha, "beta_s": prior.beta_s}
                                  for route, prior in model.arrivals.items()},
                        durations={}, measures=dict(model.measures),
                        duration_priors={action: prior.as_json()
                                         for action, prior in model.duration_priors.items()},
                        measure=model.measure.as_json())
    if _joint_model(model):
        if isinstance(model, ProgressModel):
            completion, work = model.completion, model.work_priors
            measures = dict(model.measures)
        else:
            from .progress import CompletionSpec
            # Legacy duration semantics specify unit speed. This is an embedding
            # of that known law, not a default for a new progress declaration.
            completion = CompletionSpec(name="progress", version="1", actions=model.actions,
                states=model.states, work_unit="ns", time_unit="ns", speed_unit="ns/ns",
                candidates=(tuple(tuple(1 for _ in model.states) for _ in model.actions),),
                weights=(1,), share="all_actions", max_speed=1)
            work, measures = model.duration_priors, {a: model.measures.get(a, "report") for a in model.actions}
        material.update(scheme="sui.model.7", Q=None if model.Q is None else model.Q.tolist(),
            arrivals={r: {"alpha": p.alpha, "beta_s": p.beta_s} for r, p in model.arrivals.items()},
            durations={}, duration_priors={}, measures=measures, measure=model.measure.as_json(),
            completion=_completion_json(completion), work_priors={a: p.as_json() for a, p in work.items()})
    return _json.dumps(material, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")


def model_from_json(data: bytes) -> GenerativeModel:
    """正準 JSON を値を変えずに戻す。非正準の入力も拒む。"""
    try:
        if not isinstance(data, bytes):
            raise ValueError("model: expected bytes")
        value = _json.loads(data)
        if isinstance(value, dict) and value.get("scheme") == "sui.model.9":
            from .rate_model import rate_model_from_json
            return rate_model_from_json(data)
        if isinstance(value, dict) and value.get("scheme") == "sui.model.8":
            from .action_model import action_model_from_json
            return action_model_from_json(data)
        if isinstance(value, dict) and value.get("scheme") == "sui.model.7":
            keys = {"scheme", "states", "outcomes", "actions", "a", "learnable", "D", "log_C", "gamma",
                    "Q", "arrivals", "durations", "measures", "duration_priors", "measure", "completion", "work_priors"}
            if set(value) != keys or value["durations"] != {} or value["duration_priors"] != {}:
                raise ValueError("progress: unexpected keys or duration aliases")
            model = ProgressModel(states=tuple(value["states"]), outcomes=tuple(value["outcomes"]),
                actions=tuple(value["actions"]), a={k: _np.array(v, dtype=float) for k, v in value["a"].items()},
                learnable=frozenset(value["learnable"]), D=_np.array(value["D"], dtype=float),
                log_C=_np.array(value["log_C"], dtype=float), gamma=float(value["gamma"]),
                Q=None if value["Q"] is None else _np.array(value["Q"], dtype=float),
                arrivals={k: ArrivalPrior(**v) for k, v in value["arrivals"].items()},
                measures=value["measures"], measure=value["measure"],
                completion=_completion_from_json(value["completion"]), work_priors=value["work_priors"])
            if model_json(model) != data:
                raise ValueError("model: expected canonical encoding")
            return model
        if isinstance(value, dict) and value.get("scheme") == "sui.model.6" and value.get("Q") is not None:
            raise ValueError("duration_priors with Q is outside model.6")
        if isinstance(value, dict) and value.get("scheme") == "sui.model.6" and value.get("measures"):
            raise ValueError("measures: durations are required")
        keys = {"scheme", "states", "outcomes", "actions", "a", "learnable",
                "D", "log_C", "gamma"}
        if isinstance(value, dict) and value.get("scheme") in ("sui.model.2", "sui.model.3", "sui.model.4", "sui.model.5", "sui.model.6"):
            keys |= {"Q", "arrivals"}
        if isinstance(value, dict) and value.get("scheme") in ("sui.model.3", "sui.model.4", "sui.model.5", "sui.model.6"):
            keys |= {"durations", "measures"}
        if isinstance(value, dict) and value.get("scheme") == "sui.model.6":
            keys |= {"duration_priors", "measure"}
        if not isinstance(value, dict) or set(value) != keys:
            raise ValueError("model: unexpected keys")
        if value["scheme"] not in ("sui.model.1", "sui.model.2", "sui.model.3", "sui.model.4", "sui.model.5", "sui.model.6"):
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
            durations={action: tuple(tuple(point) for point in points)
                       for action, points in value.get("durations", {}).items()},
            measures=value.get("measures", {}),
            duration_priors=value.get("duration_priors", {}), measure=value.get("measure"),
        )
        if model_json(model) != data:
            raise ValueError("model: expected canonical encoding")
        return model
    except (TypeError, KeyError, AttributeError, OverflowError, ValueError) as exc:
        from .rate import RateInputError, RateSpecificationMissing, RateOutsideEvaluationType
        if isinstance(exc, (RateInputError, RateSpecificationMissing, RateOutsideEvaluationType)):
            raise
        from .action_types import _ActionFailure
        if isinstance(exc, _ActionFailure):
            raise
        raise ValueError(f"invalid model: {exc}") from exc


def model_ref(model: GenerativeModel) -> str:
    return "sha256:" + _hashlib.sha256(model_json(model)).hexdigest()
