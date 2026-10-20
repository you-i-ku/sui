"""F-b の値を正準 JSON の値へ写す (F-a V-01〜V-03・F-b §2-5)。

和型は `{kind, value}` (既に kind を持つ型に二重のタグを足さない)。SlotValue は
`{slot, declaration: {contract, value}}`、FixedView は `{boundary, environment: {...}}`。
集合は正準 JSON の bytes の順に並べる。F-a の DTO は F-a の符号化 (`f._encode`) に任せる。
"""

import json as _json
from dataclasses import fields as _fields, is_dataclass as _is_dataclass

from . import f as _f
from . import fb as _fb


def dumps(value: object) -> bytes:
    return _json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False).encode("utf-8")


_SEGMENT_TAGS = {
    _f.MeasurementFrame: "frame", _f.Gap: "gap",
    _f.MeasurementUnavailable: "measurement_unavailable",
    _f.CoverageClaim: "claim", _f.CoverageUnproved: "coverage_unproved",
}
_OUTCOME_TAGS = {
    _fb.WorkOutputs: ("outputs", "outputs"), _fb.WorkFailure: ("failure", "failure"),
    _fb.WorkUnknown: ("unknown", "unknown"), _fb.DrawValue: ("value", "value"),
    _fb.DrawFailure: ("failure", "failure"), _fb.DrawUnknown: ("unknown", "unknown"),
}


def reading(value) -> object:
    """ReadingEvidence: clock 枝と unavailable 枝。"""
    if isinstance(value, _f.Unavailable):
        return {"kind": "unavailable", "value": encode(value)}
    if isinstance(value, _fb.ReadingClock):
        return {"kind": "clock", "value": {"source": value.source, "reading": encode(value.reading)}}
    raise TypeError("ReadingEvidence expected")


def segment_item(value) -> object:
    if isinstance(value, _fb.SegmentBoundary):
        return {"kind": value.kind, "value": {"work": value.work, "reading": reading(value.reading),
                                              "reason": value.reason, "evidence": encode(value.evidence)}}
    if isinstance(value, _fb.RouteAppliedItem):
        return {"kind": "route_applied", "value": {"config": value.config, "reading": reading(value.reading),
                                                   "reason": value.reason, "evidence": encode(value.evidence)}}
    tag = _SEGMENT_TAGS.get(type(value))
    if tag is None:
        raise TypeError("SegmentItem expected")
    return {"kind": tag, "value": _f._encode(value)}


def encode(value) -> object:
    if isinstance(value, _fb.SlotValue):
        return {"slot": value.slot, "declaration": {"contract": encode(value.contract), "value": encode(value.value)}}
    if isinstance(value, _fb.FixedView):
        return {"boundary": encode(value.boundary), "environment": {
            "reader_view_key": value.reader_view_key, "registry_key": value.registry_key}}
    if isinstance(value, _fb.ReadingClock):
        return reading(value)
    if isinstance(value, _fb.GenerationPair):
        return {"started": reading(value.started), "finished": reading(value.finished)}
    if isinstance(value, _fb.FailureInfo):
        return {"failure_kind": value.failure_kind, "content": encode(value.content),
                "readings": [reading(r) for r in value.readings], "basis": encode(value.basis)}
    if isinstance(value, _fb.SegmentReport):
        return {"segment": value.segment, "item_slot": value.item_slot, "item": segment_item(value.item)}
    if isinstance(value, _fb.WorkFinished):
        return {"work": value.work, "started": reading(value.started), "finished": reading(value.finished),
                "outcome": encode(value.outcome)}
    if isinstance(value, _fb.DrawReturned):
        return {"work": value.work, "outcome": encode(value.outcome)}
    tag = _OUTCOME_TAGS.get(type(value))
    if tag is not None:
        return {"kind": tag[0], "value": encode(getattr(value, tag[1]))}
    if type(value).__module__ == _fb.__name__ and _is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in _fields(value)}
    if isinstance(value, dict) or hasattr(value, "items"):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((encode(item) for item in value), key=dumps)
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    return _f._encode(value)
