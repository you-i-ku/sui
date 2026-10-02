"""値の型に依らない、信念と照会の差し込み口 (S4b-1b §3-9)。"""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Protocol, runtime_checkable


def _freeze(value):
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("params: expected string keys")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("params: expected finite JSON values")


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ValueSpace:
    kind: str
    version: str

    def __post_init__(self):
        if type(self.kind) is not str or not self.kind or type(self.version) is not str or not self.version:
            raise ValueError("value space: expected nonempty kind and version")


@dataclass(frozen=True, slots=True)
class MeasureSpec:
    name: str
    version: str
    params: Mapping

    def __post_init__(self):
        if type(self.name) is not str or not self.name or type(self.version) is not str or not self.version:
            raise ValueError("measure: expected nonempty name and version")
        if not isinstance(self.params, Mapping):
            raise ValueError("measure params: expected mapping")
        object.__setattr__(self, "params", _freeze(self.params))

    def as_json(self):
        return {"name": self.name, "version": self.version, "params": _thaw(self.params)}


@dataclass(frozen=True, slots=True)
class InformationBounds:
    """計算の打ち切り・求積の誤差の幅。浮動小数点の丸めは含めない。"""

    lower: float
    upper: float

    def __post_init__(self):
        if (not math.isfinite(self.lower) or not math.isfinite(self.upper)
                or self.lower > self.upper):
            raise ValueError("information: expected finite ordered bounds")

    @property
    def midpoint(self):
        return self.lower + (self.upper - self.lower) / 2


@runtime_checkable
class ValueBelief(Protocol):
    value_space: ValueSpace
    condition_keys: tuple

    def predictive(self, query): ...

    def information(self, target, evidence, given) -> InformationBounds: ...
