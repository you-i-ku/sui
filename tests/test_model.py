from dataclasses import FrozenInstanceError, fields
from types import MappingProxyType

import numpy as np
import pytest

from sui.model import GenerativeModel
from worlds import _close, _model, _model_kwargs


def test_m1_valid_model_owns_readonly_float64_arrays():
    values = _model_kwargs()
    values["a"]["look1"] = values["a"]["look1"].astype(np.int64)
    model = GenerativeModel(**values)
    assert isinstance(model.a, MappingProxyType)
    for name in ("D", "log_C"):
        expected = values[name].copy()
        values[name][:] = 42
        _close(getattr(model, name), expected)
    expected = model.a["look1"].copy()
    values["a"]["look1"][:] = 42
    values["a"]["look2"] = np.ones((3, 2))
    _close(model.a["look1"], expected)
    _close(model.a["look2"], [[5, 1], [5, 9], [0, 0]])
    for array in [model.D, model.log_C, *model.a.values()]:
        assert array.dtype == np.float64
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array.flat[0] = 42
    with pytest.raises(TypeError):
        model.a["look1"] = np.ones((3, 2))
    with pytest.raises(FrozenInstanceError):
        model.gamma = 1.0
    assert not hasattr(model, "__dict__")
    assert GenerativeModel.__dataclass_params__.eq is False
    assert {field.name for field in fields(model)} == {
        "states", "outcomes", "actions", "a", "learnable", "D", "log_C", "gamma", "Q", "arrivals",
    }, ("Qを持つモデルはS4aの濾過を使い、learnableとの同時は拒む。"
        "変わる状態での学習はS4bで決め直す")


@pytest.mark.parametrize("name,value", [
    ("states", ()), ("outcomes", ()), ("actions", ()),
    ("states", ("s0", "s0")), ("outcomes", ("o0", "o0", "none")),
    ("actions", ("look1", "look1", "wait")), ("states", ("", "s1")),
    ("D", np.array([.9, .2])), ("D", np.array([1.1, -.1])),
    ("D", np.array([np.nan, .1])), ("D", np.array([np.inf, .1])),
    ("D", np.array([1.])), ("D", np.array([[.9, .1]])),
    ("log_C", np.array([0., 0., 0.])),
    ("log_C", np.array([-np.inf, np.log(.5), np.log(.5)])),
    ("log_C", np.array([np.nan, 0., 0.])),
    ("log_C", np.log(np.array([.5, .5]))),
    ("gamma", 0.0), ("gamma", -1.0), ("gamma", np.inf), ("gamma", np.nan),
    ("learnable", frozenset({"unknown"})),
    ("a", {}), ("a", {"look1": np.ones((3, 2))}),
])
def test_m2_invalid_model_values(name, value):
    with pytest.raises(ValueError):
        _model(**{name: value})


@pytest.mark.parametrize("counts", [
    np.ones((2, 3)), np.ones((3, 3)), np.ones(6), np.ones((3, 2, 1)),
    np.array([[9., 5.], [-1., 5.], [0., 0.]]),
    np.array([[0., 5.], [0., 5.], [0., 0.]]),
    np.array([[np.inf, 5.], [1., 5.], [0., 0.]]),
    np.array([[np.nan, 5.], [1., 5.], [0., 0.]]),
])
def test_m2_invalid_counts(counts):
    a = _model_kwargs()["a"]
    a["look1"] = counts
    with pytest.raises(ValueError):
        _model(a=a)


def test_m2_learnable_column_sums_must_be_finite():
    a = _model_kwargs()["a"]
    a["look1"] = np.full((3, 2), 1e308)
    with pytest.raises(ValueError):
        _model(a=a, learnable=frozenset({"look1"}))
    model = _model(a=a, learnable=frozenset())
    np.testing.assert_array_equal(model.a["look1"], a["look1"])


def test_m2_extra_action_key_and_absolute_normalization_tolerance():
    a = _model_kwargs()["a"]
    a["unknown"] = np.ones((3, 2))
    with pytest.raises(ValueError):
        _model(a=a)
    with pytest.raises(ValueError):
        _model(D=np.array([.9, .1000000001]))
    with pytest.raises(ValueError):
        _model(log_C=np.full(3, -np.log(3) + 1e-10))


@pytest.mark.parametrize("name,value", [
    ("gamma", True), ("gamma", 64), ("gamma", "64"),
    ("states", ["s0", "s1"]), ("outcomes", ["o0", "o1", "none"]),
    ("actions", ["look1", "look2", "wait"]), ("states", (1, "s1")),
    ("learnable", {"look1"}), ("learnable", frozenset({1})),
    ("a", []), ("a", {1: np.ones((3, 2))}),
    ("D", [.9, .1]), ("log_C", [-1., -1., -1.]),
])
def test_m3_invalid_model_types(name, value):
    with pytest.raises(TypeError):
        _model(**{name: value})


@pytest.mark.parametrize("name", ["log_C", "gamma"])
def test_m3_preferences_and_precision_have_no_defaults(name):
    values = _model_kwargs()
    del values[name]
    with pytest.raises(TypeError):
        GenerativeModel(**values)
