"""F-b の受理条件: 出来事の外側 (型・欄の型・nullable) だけを確かめる (紙 F-b §2-4-7)。

中身の bytes・送り手の主張・報告の値の正しさ・知らない要求や区間への言及では断らない
(P1: 事実は先に残す)。誤りは FbInputError(reason="shape", field=JSON Pointer)。
"""

import math as _math
import typing as _typing
from collections.abc import Mapping as _Mapping
from dataclasses import fields as _fields, is_dataclass as _is_dataclass
from fractions import Fraction as _Fraction
from types import UnionType as _UnionType

from . import fb as _fb
from .contracts import ContractRef as _ContractRef
from .ids import Ref as _Ref

# SlotValue.value の型は、それを置く欄が決める (§2-5-3)。
_SLOT_VALUE = {
    ("BootDeclaration", "scope"): _fb.ResourceScope,
    ("BootDeclaration", "routes"): _fb.BootstrapRoute,
    ("BootDeclaration", "initial"): _fb.InitialProcess,
    ("BootDeclaration", "environment"): _fb.Environment,
    ("BootstrapRoute", "allocation"): _fb.Allocation,
    ("InitialProcess", "allocation"): _fb.Allocation,
}


def _fail(path: str):
    raise _fb.FbInputError(reason="shape", field=path or "/")


def _json(value, path):
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        return
    if type(value) is float:
        if not _math.isfinite(value):
            _fail(path)
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _json(item, f"{path}/{i}")
        return
    if isinstance(value, _Mapping):
        for key, item in value.items():
            if type(key) is not str:
                _fail(path)
            _json(item, f"{path}/{key}")
        return
    _fail(path)


def _check(value, hint, path, owner=None):
    if hint is _fb.ImmutableJSON or hint == _fb.ImmutableJSON:
        return _json(value, path)
    if hint is object:
        return
    origin = _typing.get_origin(hint)
    args = _typing.get_args(hint)
    if origin in (_typing.Union, _UnionType):
        for option in args:
            try:
                _check(value, option, path, owner)
                return
            except _fb.FbInputError:
                continue
        _fail(path)
    if origin is _typing.Literal:
        if value not in args or type(value) is not type(args[list(args).index(value)]):
            _fail(path)
        return
    if origin is tuple:
        if type(value) is not tuple:
            _fail(path)
        if len(args) == 2 and args[1] is Ellipsis:
            items = args[:1] * len(value)
        elif len(value) == len(args):
            items = args   # 固定長 (tuple[int, int] など) は要素の数も型の一部 (R26)
        else:
            _fail(path)
        for i, (element, item) in enumerate(zip(value, items)):
            _check(element, item, f"{path}/{i}", owner)
        return
    if origin is _Mapping or origin is dict:
        if not isinstance(value, _Mapping):
            _fail(path)
        for key, element in value.items():
            _check(key, args[0], path, owner)
            _check(element, args[1], f"{path}/{key}", owner)
        return
    if origin is frozenset:
        if type(value) is not frozenset:
            _fail(path)
        for element in value:
            _check(element, args[0], path, owner)
        return
    if hint is type(None):
        if value is not None:
            _fail(path)
        return
    if hint in (str, bool, bytes):
        if type(value) is not hint:
            _fail(path)
        return
    if hint is int:
        if type(value) is not int:
            _fail(path)
        return
    if hint is _Fraction:
        if type(value) is not _Fraction:
            _fail(path)
        return
    if hint in (_Ref, _ContractRef):
        if type(value) is not hint:
            _fail(path)
        return
    if isinstance(hint, type) and _is_dataclass(hint):
        if type(value) is not hint:
            _fail(path)
        if hint is _fb.SlotValue:
            _check(value.slot, str, path + "/slot")
            _check(value.contract, _ContractRef, path + "/contract")
            expected = _SLOT_VALUE.get(owner) if owner else None
            if expected is not None:
                _check(value.value, expected, path + "/value")
            return
        # 生の注釈 (ImmutableJSON の別名をそのまま見分ける)。文字列の注釈 (F-a の
        # `from __future__ import annotations`) はその型の模様で解決する。
        raw = {field.name: field.type for field in _fields(hint)}
        if any(isinstance(item, str) for item in raw.values()):
            raw = _typing.get_type_hints(hint)
        for field in _fields(hint):
            _check(getattr(value, field.name), raw[field.name], f"{path}/{field.name}",
                   (hint.__name__, field.name))
        return
    if isinstance(hint, (str, _typing.ForwardRef)):  # 前方参照 (ImmutableJSON の中身)
        return _json(value, path)
    _fail(path)


def check_event(event) -> None:
    """event が出来事 6 つのどれかで、外側が正しいことを確かめる。"""
    if type(event) not in (_fb.Boot, _fb.ClockDeclared, _fb.Received, _fb.SegmentReport,
                           _fb.WorkFinished, _fb.DrawReturned):
        _fail("/")
    _check(event, type(event), "")


def check_contract_value(ref, raw) -> None:
    """F-b の構造契約の JSON を確かめる (F-a の能力の呼出しの構造検査から呼ばれる、V-11)。
    NEED_INPUT = {"work": Desc の正準 JSON, "scope": ResourceScope の正準 JSON}、
    QUANTITY_VALUE = {"contract": {name, version}, "value": その量の契約の値}。この版の量の契約は
    SEATS だけで、値は非負整数 (bool 不可)。知らない名前は missing_contract、形の誤りは shape。"""
    from . import f as _f
    from . import fb_contracts as _c

    def keys(value, names):
        if not isinstance(value, _Mapping) or set(value) != set(names):
            raise _f.FInputError("shape", "keys " + ",".join(names))

    if ref == _c.NEED_INPUT:
        keys(raw, ("work", "scope"))
        if not isinstance(raw["work"], _Mapping):
            raise _f.FInputError("shape", "work")
        keys(raw["scope"], ("quantity_contract", "need"))
        return
    if ref == _c.QUANTITY_VALUE:
        keys(raw, ("contract", "value"))
        keys(raw["contract"], ("name", "version"))
        contract = _ContractRef(name=raw["contract"]["name"], version=raw["contract"]["version"])
        if contract != _c.SEATS:
            raise _f.FSpecificationMissing("missing_contract", "quantity contract " + contract.name)
        if type(raw["value"]) is not int or raw["value"] < 0:
            raise _f.FInputError("shape", "seats must be a non-negative int")
        return
    raise _f.FSpecificationMissing("missing_contract", "unknown F-b schema " + ref.name)
