"""好みの原記録を、採用した因果の範囲から読む。"""

from dataclasses import dataclass as _dataclass
from collections.abc import Callable as _Callable, Mapping as _Mapping
from types import MappingProxyType as _MappingProxyType
import json as _json
import math as _math

from .clock import Instant as _Instant
from .contracts import ContractRef as _ContractRef
from .ids import Ref as _Ref, RefKind as _RefKind
from .inference import _s4d_finite
from .records import (Category as _Category, Record as _Record,
                      representative as _representative)
from .s4d_contracts import PREFERENCE as _PREFERENCE
from .snapshot import UnreadPreference as _UnreadPreference


class PreferenceUnreadable(ValueError):
    """好みを読めない。白紙として決めない (C2・C7)。"""


class AmbiguousPreference(ValueError):
    """決め方の紙を一枚に定められない (C2・C7)。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreferencePoint:
    cid: str
    id: _Ref
    at: _Instant
    record: _Record | None
    unread: str | None = None


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreferenceView:
    """点と実際の祖先関係を固定する。IDの経路を継ぎ足さない (C2)。"""

    points: tuple[PreferencePoint, ...] = ()
    before: frozenset[tuple[_Ref, _Ref]] = frozenset()
    frontier: frozenset[str] = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "points", tuple(self.points))
        object.__setattr__(self, "before", frozenset(self.before))
        object.__setattr__(self, "frontier", frozenset(self.frontier))


def from_ledger(ledger, target) -> PreferenceView:
    """targetの下だけを読む。他種の出来事を挟む祖先も固定する (C2・C3)。"""
    target = frozenset(target)
    entries = tuple(entry for entry in ledger.between((), target)
                    if entry.category is _Category.PREFERENCE)
    names = {entry.cid: entry.id for entry in entries}
    points, before = [], set()
    for entry in entries:
        value = ledger._preference_record(entry)
        unread = isinstance(value, _UnreadPreference)
        points.append(PreferencePoint(cid=entry.cid, id=entry.id, at=entry.at,
            record=None if unread else value, unread=value.reason if unread else None))
        before.update((names[cid], entry.id)
                      for cid in ledger.ancestors(entry.parents) if cid in names)
    return PreferenceView(points=tuple(sorted(points, key=lambda p: (str(p.id), p.cid))),
                          before=frozenset(before), frontier=target)


def _parse(record):
    if record.body.contract != _PREFERENCE:
        raise PreferenceUnreadable("unknown preference contract")
    try:
        data = record.body.content.as_json()
        if not isinstance(data, dict):
            raise ValueError("preference: expected object")
        kind = data.get("kind")
        if kind == "item":
            if set(data) != {"kind", "rule", "args"} or not isinstance(data["args"], dict):
                raise ValueError("item: expected rule and args")
            rule = data["rule"]
            if not isinstance(rule, dict) or set(rule) != {"name", "version"}:
                raise ValueError("rule: expected name and version")
            _ContractRef(rule["name"], rule["version"])
        elif kind == "withdraw":
            if set(data) != {"kind", "items"} or not isinstance(data["items"], list):
                raise ValueError("withdraw: expected items")
            for name in data["items"]:
                if not isinstance(name, str) or not name.startswith("preference:"):
                    raise ValueError("withdraw: expected Preference ID")
                _Ref(_RefKind.PREFERENCE, name[len("preference:"):])
        elif kind == "style":
            if set(data) != {"kind", "H_ns", "gamma"}:
                raise ValueError("style: expected H_ns and gamma")
            horizon, gamma = data["H_ns"], data["gamma"]
            if horizon is not None and (type(horizon) is not int or horizon < 0):
                raise ValueError("H_ns: expected nonnegative integer or null")
            if (type(gamma) not in (int, float) or gamma < 0
                    or not _math.isfinite(gamma)):
                raise ValueError("gamma: expected finite nonnegative number")
        else:
            raise ValueError("unknown preference kind")
        return data
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise PreferenceUnreadable(str(exc)) from exc


@_dataclass(frozen=True, slots=True, kw_only=True)
class Current:
    items: tuple[_Record, ...]
    style: _Record | None
    unread: tuple[tuple[_Ref, str], ...] = ()
    ambiguous: tuple[_Ref, ...] = ()

    def check(self) -> None:
        """評価の入口でだけ読めない印と紙の矛盾を例外にする (C2・C7)。"""
        if self.unread:
            raise PreferenceUnreadable("; ".join(f"{ref}: {reason}"
                                                for ref, reason in self.unread))
        if self.ambiguous:
            raise AmbiguousPreference(", ".join(map(str, self.ambiguous)))


def _sink_styles(styles, before):
    # 相互に到達できる点が強連結成分。他成分へ出る成分だけを除く。
    edges = {ref: set() for ref in styles}
    for left, right in before:
        if left in edges and right in edges:
            edges[left].add(right)
    reachable = {}
    for ref in edges:
        seen, todo = {ref}, [ref]
        while todo:
            for next_ref in edges[todo.pop()] - seen:
                seen.add(next_ref)
                todo.append(next_ref)
        reachable[ref] = seen
    return tuple(sorted((ref for ref in edges
                         if all(ref in reachable[other] for other in reachable[ref])), key=str))


def current(view: PreferenceView) -> Current:
    """名札で一度数え、祖先だけをはがす。紙は末尾の強連結成分 (C2)。

    読めない点を飛ばして白紙にせず印を残す。取り込み順に依らない。
    """
    records = _representative(point.record for point in view.points if point.record is not None)
    unread = {(point.id, point.unread) for point in view.points if point.unread is not None}
    parsed, by_id = {}, {record.id: record for record in records}
    for record in records:
        try:
            parsed[record.id] = _parse(record)
        except PreferenceUnreadable as exc:
            unread.add((record.id, str(exc)))
    items = {ref for ref, data in parsed.items() if data["kind"] == "item"}
    removed = set()
    for ref, data in parsed.items():
        if data["kind"] != "withdraw":
            continue
        for name in data["items"]:
            item = _Ref(_RefKind.PREFERENCE, name[len("preference:"):])
            if item not in items or (item, ref) not in view.before:
                unread.add((ref, f"withdraw: not an ancestor item: {item}"))
            else:
                removed.add(item)
    styles = _sink_styles({ref for ref, data in parsed.items() if data["kind"] == "style"},
                          view.before)
    return Current(items=tuple(by_id[ref] for ref in sorted(items - removed, key=str)),
                   style=by_id[styles[0]] if len(styles) == 1 else None,
                   unread=tuple(sorted(unread, key=lambda pair: (str(pair[0]), pair[1]))),
                   ambiguous=styles if len(styles) > 1 else ())


def _key(value):
    return _json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)


def _named(data, definitions, kind, extra=frozenset()):
    if not isinstance(data, dict) or set(data) != {"name", "version"} | extra:
        raise ValueError("descriptor: expected name, version and its arguments")
    ref = _ContractRef(data["name"], data["version"])
    key = (kind, ref.name, ref.version)
    if key not in definitions:
        raise PreferenceUnreadable(f"unknown name or version: {ref.name} {ref.version}")
    return ref, definitions[key]


def _constant(value):
    return None


def _candidate_outcome(value):
    candidate = value.candidate_outcome
    if not isinstance(candidate, str) or not candidate:
        raise ValueError("candidate_outcome: a one-step outcome is required")
    return candidate


def _outcome_multiset(value):
    return sorted([action, outcome] for _, _, action, outcome in value.O)


def _outcome_groups(value):
    groups = {}
    for ns, _, action, outcome in value.O:
        groups.setdefault(ns, []).append([action, outcome])
    return [sorted(groups[ns]) for ns in sorted(groups)]


def _started_actions(value):
    return [action for _, _, action in sorted(value.A, key=lambda event: event[1][1])]


def _counts(value):
    return [len(value.O), len(value.A)]


def _timed_path(value):
    return {
        "O": [[ns, list(label), action, outcome] for ns, label, action, outcome
              in sorted(value.O, key=lambda event: (event[0], _key(event[1])))],
        "A": [[ns, list(label), action] for ns, label, action
              in sorted(value.A, key=lambda event: event[1][1])],
    }


@_dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationInput:
    """評価の型と路を一つの値に固定する。名札も可変の列を残さない (K6)。"""

    evaluation: str
    O: tuple = ()
    A: tuple = ()
    candidate_outcome: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "O", tuple((ns, tuple(label), action, outcome)
            for ns, label, action, outcome in self.O))
        object.__setattr__(self, "A", tuple((ns, tuple(label), action)
            for ns, label, action in self.A))


@_dataclass(frozen=True, slots=True, kw_only=True)
class Feature:
    """特徴の関数を固定する。O・Aは根からの相対nsと固定済み名札 (C1・C6)。"""

    ref: _ContractRef
    evaluations: frozenset[str]
    _project: _Callable

    def __post_init__(self):
        object.__setattr__(self, "evaluations", frozenset(self.evaluations))

    def __call__(self, value: EvaluationInput):
        """指定のJSON値へ射影する。到着の同時性と名札の番号を保つ (C1・C9)。"""
        return self._project(value)


def _feature(data, definitions):
    return _named(data, definitions, "feature")[1]


@_dataclass(frozen=True, slots=True, kw_only=True)
class _LogTable:
    _values: _Mapping[str, float]

    def __post_init__(self):
        object.__setattr__(self, "_values", _MappingProxyType(dict(self._values)))

    def __call__(self, value):
        return self._values.get(_key(value), -_math.inf)


def _log_table(data):
    if not isinstance(data, dict) or set(data) not in ({"probs"}, {"log_probs"}):
        raise ValueError("table: exactly one of probs or log_probs is required")
    logarithmic = "log_probs" in data
    points = data["log_probs" if logarithmic else "probs"]
    if not isinstance(points, list) or not points:
        raise ValueError("table: expected nonempty list of pairs")
    values = {}
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("table: expected [value, number]")
        value, number = point
        if (type(number) not in (int, float) or not _math.isfinite(number)
                or (not logarithmic and number <= 0)):
            raise ValueError("table: expected finite log probability or positive probability")
        key = _key(value)
        if key in values:
            raise ValueError("table: duplicate canonical JSON key")
        values[key] = float(number) if logarithmic else _math.log(number)
    maximum = max(values.values())
    total = maximum + _math.log(_math.fsum(_math.exp(value - maximum)
                                          for value in values.values()))
    if abs(total) > 1e-12:
        raise ValueError("table: logsumexp must be zero within 1e-12")
    return _LogTable(_values=values)


def _table(h, args, definitions):
    if not isinstance(args, dict) or set(args) not in (
            {"feature", "probs"}, {"feature", "log_probs"}):
        raise ValueError("table: expected feature and one probability table")
    return _feature(args["feature"], definitions), _log_table(
        {key: value for key, value in args.items() if key != "feature"})


def _observed_count(h, descriptor):
    action, outcome = descriptor["action"], descriptor["outcome"]
    if not isinstance(action, str) or not action or not isinstance(outcome, str) or not outcome:
        raise ValueError("observed_count: expected action and outcome names")
    counts = h.reading.n.get(action)
    if counts is None or outcome not in h.model.outcomes:
        return 0
    return int(counts[h.model.outcomes.index(outcome)])


def _by_experience(h, args, definitions):
    if not isinstance(args, dict) or set(args) != {"feature", "experience", "cap", "tables"}:
        raise ValueError("by_experience: expected feature, experience, cap and tables")
    cap, tables = args["cap"], args["tables"]
    if type(cap) is not int or cap < 1:
        raise ValueError("cap: expected positive integer")
    if not isinstance(tables, dict) or set(tables) != {str(n) for n in range(cap + 1)}:
        raise ValueError("tables: expected every integer key from 0 through cap")
    feature = _feature(args["feature"], definitions)
    _, count = _named(args["experience"], definitions, "experience",
                     frozenset({"action", "outcome"}))
    resolved = {n: _log_table(tables[str(n)]) for n in range(cap + 1)}
    index = min(count(h, args["experience"]), cap)
    return feature, resolved[index]


# 同じ参照の意味は置き換えない。変更は新しい版を追加する (K6)。
BUILTINS = _MappingProxyType({
    ("rule", "table", "1"): _table,
    ("rule", "by_experience", "1"): _by_experience,
    ("experience", "observed_count", "1"): _observed_count,
    **{("feature", name, "1"): Feature(ref=_ContractRef(name, "1"),
        evaluations=frozenset(evaluations), _project=project)
       for name, project, evaluations in (
           ("constant", _constant, ("one_step", "lookahead")),
           ("candidate_outcome", _candidate_outcome, ("one_step",)),
           ("outcome_multiset", _outcome_multiset, ("lookahead",)),
           ("outcome_groups", _outcome_groups, ("lookahead",)),
           ("started_actions", _started_actions, ("lookahead",)),
           ("counts", _counts, ("lookahead",)),
           ("timed_path", _timed_path, ("lookahead",)),
       )},
})


@_dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedItem:
    id: _Ref
    rule: _ContractRef
    feature: Feature
    log_probability: _Callable


@_dataclass(frozen=True, slots=True, kw_only=True)
class Resolved:
    items: tuple[ResolvedItem, ...]
    style: _Ref | None
    H_ns: int | None
    gamma: float

    def __post_init__(self):
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: str(item.id))))


def resolve(current: Current, h, *, definitions=None) -> Resolved:
    """各決まりを根で一度解く。対数のまま固定し、白紙はHなし・γ=1 (C1・C6)。

    未知の名前・版や不正な表はPreferenceUnreadable。表を再正規化しない。
    hはモデルの観測名とReadingの読めた回数を持つview。
    定義集は入れ子の検索まで共通。無い版を別の版で補わない (K6)。
    """
    current.check()
    definitions = BUILTINS if definitions is None else definitions
    try:
        items = []
        for record in sorted(current.items, key=lambda record: str(record.id)):
            data = _parse(record)
            ref, rule = _named(data["rule"], definitions, "rule")
            feature, log_probability = rule(h, data["args"], definitions)
            items.append(ResolvedItem(id=record.id, rule=ref, feature=feature,
                                      log_probability=log_probability))
        style = None if current.style is None else _parse(current.style)
        return Resolved(items=tuple(items), style=None if style is None else current.style.id,
                        H_ns=None if style is None else style["H_ns"],
                        gamma=1.0 if style is None else float(style["gamma"]))
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise PreferenceUnreadable(str(exc)) from exc


def cost(resolved: Resolved, value: EvaluationInput) -> float:
    """名札順に費用を足す。真の-log P=+∞だけ禁止、有限のあふれは拒む (C2・C6・N10)。"""
    total = 0.0
    for item in resolved.items:
        log_probability = item.log_probability(item.feature(value))
        if log_probability == -_math.inf:
            return _math.inf
        total = float(_s4d_finite(total - log_probability, "preference cost sum exceeds numerical range"))
    return total
