"""事実の集合から作る受け取りの時間軸と、見ていた区間。"""

from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from dataclasses import dataclass as _dataclass
from types import MappingProxyType as _MappingProxyType

from .ids import Ref as _Ref
from .records import Record as _Record, Observed as _Observed, representative as _representative
from .s4_contracts import BOOT as _BOOT, LISTEN as _LISTEN
from .snapshot import UnreadPreference as _UnreadPreference


def _facts(records):
    """台帳と共通の規則で代表を選ぶ (T10・T10b)。"""
    return _representative(records)


def _membrane(record, contract):
    return (isinstance(record.body, _Observed) and record.body.route == "membrane"
            and record.body.caused_by is None and record.body.contract == contract)


def _data(record):
    try:
        return record.body.content.as_json()
    except (ValueError, UnicodeError):
        return None


def _listen(record):
    if not _membrane(record, _LISTEN):
        return None
    value = _data(record)
    if (isinstance(value, dict) and set(value) == {"route", "open"}
            and isinstance(value["route"], str) and value["route"]
            and value["route"] != "membrane" and type(value["open"]) is bool):
        return value
    return None


class TimelineError(ValueError):
    """同じ run_index の別runは直列化しない (T3)。"""

    def __init__(self, clock_issues):
        self.clock_issues = tuple(clock_issues)
        super().__init__("timeline: concurrent runs")


@_dataclass(frozen=True, slots=True, kw_only=True)
class Timeline:
    origin: _Ref | None
    runs: tuple[_Ref, ...]
    received_ns: _Mapping[_Ref, int]
    run_end_ns: _Mapping[_Ref, int]
    clock_issues: tuple[dict, ...]
    _offsets: _Mapping[_Ref, int]

    def __post_init__(self):
        for name in ("received_ns", "run_end_ns", "_offsets"):
            object.__setattr__(self, name, _MappingProxyType(dict(getattr(self, name))))
        object.__setattr__(self, "clock_issues", tuple(
            _MappingProxyType(dict(issue)) for issue in self.clock_issues))

    def to_axis(self, run: _Ref, mono_ns: int) -> int:
        """単調時計を軸へ写す。起動の無いrunは KeyError (T1・T7)。"""
        return self._offsets[run] + mono_ns


def timeline(records: _Iterable[_Record], *,
             unread_preferences: _Iterable[_UnreadPreference] = ()) -> Timeline:
    """出来事だけからrun内は単調時計、run間は実時刻でつなぐ (T1〜T10・J6)。

    入力は出来事の集合。信念などの葉は採用側で除く (J6)。
    負の間隔は0と印、最初の起動受信が原点。終端は観測の受信だけ (H4)。
    同じ名札は一度。起動の重複は最小seqを使い印を残す。
    本文の無い好みも時刻をつなぐ。受信とrun_endは増やさない (C2b)。
    """
    records = _facts(records)
    grouped, indexes = {}, {}
    for record in records:
        grouped.setdefault(record.at.run, []).append(record)
        indexes.setdefault(record.at.run_index, set()).add(record.at.run)
    event_times = {run: list(items) for run, items in grouped.items()}
    for point in unread_preferences:
        if not isinstance(point, _UnreadPreference):
            raise TypeError("unread_preferences: expected UnreadPreference")
        event_times.setdefault(point.at.run, []).append(point)
        indexes.setdefault(point.at.run_index, set()).add(point.at.run)
    issues = [{"kind": "concurrent_runs", "run_index": index,
               "runs": tuple(sorted(map(str, runs)))}
              for index, runs in sorted(indexes.items()) if len(runs) > 1]
    if issues:
        raise TimelineError(issues)
    boots = {}
    for run, items in grouped.items():
        candidates = sorted((r for r in items if _membrane(r, _BOOT)
                             and _data(r) == {} and r.body.received_ns is not None),
                            key=lambda r: (r.at.seq, str(r.id)))
        if candidates:
            boots[run] = candidates[0]
            issues.extend({"kind": "extra_boot", "run": str(run), "id": str(r.id)}
                          for r in candidates[1:])
    runs = tuple(sorted(boots, key=lambda run: boots[run].at.run_index))
    offsets, received, ends = {}, {}, {}
    previous = None
    for run in runs:
        boot = boots[run]
        delay = boot.at.mono_ns - boot.body.received_ns
        if previous is None:
            base = delay
        else:
            last = max(event_times[previous], key=lambda r: (r.at.seq, str(r.id)))
            gap = boot.at.wall_ns - delay - last.at.wall_ns
            if gap < 0:
                issues.append({"kind": "negative_wall_gap", "run": str(run), "gap_ns": gap})
            base = offsets[previous] + last.at.mono_ns + max(0, gap) + delay
        offsets[run] = base - boot.at.mono_ns
        for record in grouped[run]:
            if isinstance(record.body, _Observed) and record.body.received_ns is not None:
                received[record.id] = offsets[run] + record.body.received_ns
        ends[run] = max(received[r.id] for r in grouped[run] if r.id in received)
        previous = run
    issues.sort(key=lambda issue: (issue["kind"], issue.get("run", ""), issue.get("id", "")))
    return Timeline(origin=boots[runs[0]].id if runs else None, runs=runs,
                    received_ns=received, run_end_ns=ends, clock_issues=tuple(issues),
                    _offsets=offsets)


@_dataclass(frozen=True, slots=True, kw_only=True)
class ArrivalStats:
    N: int
    T_ns: int
    outside: tuple[_Ref, ...] = ()


def _arrivals(records, axis, routes):
    stats, counted = {}, set()
    for route in sorted(routes):
        intervals = {}
        for run in axis.runs:
            changes = sorted((r for r in records if r.at.run == run
                              and r.id in axis.received_ns and _listen(r) is not None
                              and _listen(r)["route"] == route),
                             key=lambda r: (axis.received_ns[r.id], r.at.seq))
            opened, spans = None, []
            for record in changes:
                t = axis.received_ns[record.id]
                if _listen(record)["open"]:
                    if opened is None:
                        opened = t
                elif opened is not None:
                    spans.append((opened, t))
                    opened = None
            if opened is not None:
                spans.append((opened, axis.run_end_ns[run]))
            intervals[run] = spans
        outside, number = [], 0
        for record in records:
            body = record.body
            if (isinstance(body, _Observed) and body.caused_by is None
                    and body.route == route and record.id in axis.received_ns):
                t = axis.received_ns[record.id]
                if any(start <= t <= end for start, end in intervals.get(record.at.run, ())):
                    number += 1
                    counted.add(record.id)
                else:
                    outside.append(record.id)
        stats[route] = ArrivalStats(N=number,
            T_ns=sum(end - start for spans in intervals.values() for start, end in spans),
            outside=tuple(sorted(outside, key=str)))
    return stats, counted
