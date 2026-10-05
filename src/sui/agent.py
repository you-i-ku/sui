"""事実から信念と帳面を作り、決定を記録する主体。"""

from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from dataclasses import dataclass as _dataclass, field as _field
from types import MappingProxyType as _MappingProxyType
import math as _math
from itertools import product as _product

import numpy as _np

from .clock import Clock as _Clock
from .ids import IdSource as _IdSource, Ref as _Ref, RefKind as _RefKind
from .inference import (
    ModelViolation as _ModelViolation, belief as _belief, efe as _efe, expected_A as _expected_A, ledger as _ledger,
    log_likelihood as _log_likelihood, novelty as _novelty,
    policy_posterior as _policy_posterior, select as _select,
    reachable as _reachable, filter_log as _filter_log, arrival_posterior as _arrival_posterior,
    _log_A, _log_predict, _log_probability, _log_update,
    remaining as _remaining, _hand_efe,
    _hand_joint_log,
    NumericalRange, _s4d_log_product, _s4d_normalize, _s4d_log_belief,
    _s4d_log_predict, _s4d_filter_log, _s4d_hand_joint_log, _s4d_novelty, _s4d_likelihood,
    _s4d_finite, _s4d_weighted_cost, _s4d_cost_sum,
)
from .s1_contracts import ACTION, BELIEF, DECISION, ATTEMPT as _ATTEMPT, OUTCOME as _OUTCOME
from .s3_contracts import ABANDON as _ABANDON
from .s4_contracts import BOOT as _BOOT, LISTEN as _LISTEN, BELIEF as _TIME_BELIEF, DECISION as _TIME_DECISION
from .s4_contracts import HAND_BELIEF as _HAND_BELIEF, HAND_DECISION as _HAND_DECISION
from .s4d_contracts import BELIEF as _S4D_BELIEF, DECISION as _S4D_DECISION
from .s4b_contracts import (BELIEF as _S4B_BELIEF, QUANTITY_BELIEF as _QUANTITY_BELIEF,
                            DECISION as _QUANTITY_DECISION)
from .s4b1c_contracts import BELIEF as _JOINT_BELIEF, DECISION as _JOINT_DECISION
from .model import _joint_model, _work_timed, _is_action_model
from .lattice import (learn as _learn, hand_table as _lattice_hand_table,
                      one_step_components as _lattice_components)
from .preference import (PreferenceView as _PreferenceView, from_ledger as _preference_view,
                         current as _current_preference, resolve as _resolve_preference,
                         cost, EvaluationInput as _EvaluationInput)
from .lookahead import OutsideEvaluationType, _policy as _s4d_policy
from .contracts import ContractRef as _ContractRef
from .snapshot import UnreadPreference as _UnreadPreference
from .timeline import (Timeline as _Timeline, TimelineError as _TimelineError,
                       ArrivalStats as _ArrivalStats, timeline as _timeline,
                       _facts, _membrane, _listen, _arrivals)
from .model import (GenerativeModel as _GenerativeModel, model_ref as _model_ref,
                    _readonly, _duration_ns, _has_unreachable)
from .ledger import Ledger as _Ledger, DerivedParent as _DerivedParent, UnknownEntry as _UnknownEntry
from .records import (
    AttemptStarted as _AttemptStarted, Decided as _Decided,
    JobOpened as _JobOpened, Observed as _Observed, Payload as _Payload,
    Prediction as _Prediction, Producer as _Producer, Record as _Record,
    Role as _Role, StateRef as _StateRef, Category as _Category,
    Preference as _Preference,
)


CODE_VERSION = "s3"


class ModelMismatch(ValueError):
    """保存されたモデルの参照が異なる。"""


class RebuildMismatch(ValueError):
    def __init__(self, *, fields: tuple[str, ...]) -> None:
        self.fields = fields
        super().__init__(f"rebuilt content differs in {fields!r}")


class ModelFalsified(ValueError):
    """読めた事実の組をモデルのどの仮説も説明できない。"""


@_dataclass(frozen=True, slots=True, kw_only=True)
class Reading:
    n: _Mapping[str, _np.ndarray]
    unread: _Mapping[_Ref, str]
    pending: _Mapping[_Ref, str]
    timeline: _Timeline | None = None
    sequence: tuple[tuple[int, int, int, _Ref, str, str], ...] = ()
    arrivals: _Mapping[str, _ArrivalStats] = _field(default_factory=dict)
    _clock_issues: tuple[dict, ...] = ()
    started: _Mapping[_Ref, tuple[int, ...]] = _field(default_factory=dict)
    _started_runs: _Mapping[_Ref, tuple[_Ref, ...]] = _field(default_factory=dict)
    _event_ns: _Mapping[_Ref, int] = _field(default_factory=dict)
    preferences: tuple[_Record, ...] = ()
    unread_preferences: tuple[_UnreadPreference, ...] = ()
    timing: object | None = None
    _joint_timing: object | None = None
    _action_records: tuple = ()

    def __post_init__(self) -> None:
        counts = {}
        for action, value in self.n.items():
            copy = _np.array(value, dtype=_np.int64, copy=True)
            copy.setflags(write=False)
            counts[action] = copy
        object.__setattr__(self, "n", _MappingProxyType(counts))
        object.__setattr__(self, "unread", _MappingProxyType(dict(self.unread)))
        object.__setattr__(self, "pending", _MappingProxyType(dict(self.pending)))
        object.__setattr__(self, "arrivals", _MappingProxyType(dict(self.arrivals)))
        for name in ("started", "_started_runs"):
            object.__setattr__(self, name, _MappingProxyType(
                {key: tuple(value) for key, value in getattr(self, name).items()}))
        object.__setattr__(self, "_event_ns", _MappingProxyType(dict(self._event_ns)))
        object.__setattr__(self, "preferences", tuple(self.preferences))
        object.__setattr__(self, "unread_preferences", tuple(self.unread_preferences))
        object.__setattr__(self, "_clock_issues", tuple(
            _MappingProxyType(dict(issue)) for issue in self._clock_issues))


def _json_content(content: _Payload):
    try:
        return content.as_json()
    except (ValueError, UnicodeError):
        return None


def _named_content(content, key):
    data = _json_content(content)
    if isinstance(data, dict) and set(data) == {key} and isinstance(data[key], str):
        return data[key]
    return None


def _read_jobs(model: _GenerativeModel, records: _Iterable[_Record]) -> dict[_Ref, str]:
    if _is_action_model(model):
        from .action_joint import read_jobs
        return read_jobs(model, records)
    jobs = {}
    for record in records:
        if isinstance(record.body, _JobOpened) and record.body.contract == ACTION:
            action = _named_content(record.body.content, "action")
            if action in model.actions:
                jobs[record.id] = action
    return jobs


def read(model: _GenerativeModel, records: _Iterable[_Record], *,
         unread_preferences: _Iterable[_UnreadPreference] = ()) -> Reading:
    """事実の集合から読む。順番待ちも pending、観測は約束を問わず終端。

    ABANDON は対応する仕事だけを pending から外す。
    静的な読みはS3のまま。時間の読みは受信順・到達可能性・開閉から
    作り直す。時刻不明を補わず、Qなしの結果は回数として読む。
    到着の本文は問わない (T7・T7b・Q9〜Q13・H1〜H10)。
    所要ありは測定時刻順と試みの時刻の組を事実から作る (F1〜F3・J9・J15)。
    好みは別に持ち、本文が無い時も時刻だけは軸につなぐ (C2・C2b)。
    """
    if _is_action_model(model):
        from .action_joint import read_action
        return read_action(model, records, unread_preferences=unread_preferences)
    records = _facts(records)
    unread_preferences = tuple(unread_preferences)
    if model.durations or _work_timed(model):
        records = tuple(r for r in records if r.category in (
            _Category.FACT, _Category.INTENTION, _Category.PREFERENCE))
    timed = _timed(model)
    axis, issues, arrivals, counted = None, (), {}, set()
    if timed:
        try:
            axis = _timeline(records, unread_preferences=unread_preferences)
            arrivals, counted = _arrivals(records, axis, model.arrivals)
        except _TimelineError as exc:
            issues = exc.clock_issues
            arrivals = {route: _ArrivalStats(N=0, T_ns=0) for route in model.arrivals}
    support = model.D > 0 if model.Q is None else _reachable(model.D, model.Q)
    jobs = _read_jobs(model, records)
    arrived = {r.body.caused_by for r in records if isinstance(r.body, _Observed)}
    finished = {r.body.job for r in records
                if isinstance(r.body, _AttemptStarted) and r.id in arrived}
    abandoned = {r.body.inputs[0] for r in records
                 if isinstance(r.body, _Decided) and r.body.contract == _ABANDON
                 and len(r.body.inputs) == 1
                 and _named_content(r.body.content, "job") == str(r.body.inputs[0])}
    attempts = {}
    for record in records:
        if isinstance(record.body, _AttemptStarted):
            body = record.body
            attempts[record.id] = (jobs.get(body.job)
                                   if body.contract == _ATTEMPT and
                                   _json_content(body.content) == {} else None)
    n = {action: _np.zeros(len(model.outcomes), dtype=_np.int64) for action in model.actions}
    unread, readable = {}, {}
    by_id = {record.id: record for record in records}
    for record in records:
        if not isinstance(record.body, _Observed):
            continue
        body, reason = record.body, None
        if timed:
            if ((_membrane(record, _BOOT) and _json_content(body.content) != {})
                    or (_membrane(record, _LISTEN) and _listen(record) is None)):
                unread[record.id] = "content"
                continue
            needs_time = ((model.Q is not None and body.caused_by is not None)
                          or _membrane(record, _BOOT) or _membrane(record, _LISTEN)
                          or (body.caused_by is None and body.route in model.arrivals))
            if needs_time:
                if body.received_ns is None:
                    unread[record.id] = "no_receipt_time"
                    continue
                if axis is None or record.at.run not in axis.runs:
                    unread[record.id] = "no_clock"
                    continue
            if _membrane(record, _BOOT) or _membrane(record, _LISTEN):
                continue
            if record.id in counted:
                continue
        outcome = _named_content(body.content, "outcome")
        action = attempts.get(body.caused_by)
        if body.caused_by is None:
            reason = "no_attempt"
        elif body.caused_by not in attempts:
            reason = "unknown_attempt"
        elif action is None:
            reason = "unreadable_attempt"
        elif body.contract != _OUTCOME:
            reason = "contract"
        elif outcome is None:
            reason = "content"
        elif outcome not in model.outcomes:
            reason = "unknown_outcome"
        elif not _np.any(support & (model.a[action][model.outcomes.index(outcome)] > 0)):
            reason = "impossible"
        if reason is not None:
            unread[record.id] = reason
        else:
            readable.setdefault(body.caused_by, []).append((record.id, action, outcome))
    sequence = []
    for observations in readable.values():
        if len(observations) > 1:
            for ref, _, _ in observations:
                unread[ref] = "ambiguous_attempt"
        else:
            ref, action, outcome = observations[0]
            measured_ns = axis.received_ns.get(ref) if axis is not None else None
            if (model.durations or _joint_model(model)) and model.measures.get(action) == "start":
                attempt = by_id[by_id[ref].body.caused_by]
                if axis is None or attempt.at.run not in axis.runs:
                    if model.Q is not None:
                        unread[ref] = "no_clock"
                        continue
                    measured_ns = None
                else:
                    measured_ns = axis.to_axis(attempt.at.run, attempt.at.mono_ns)
            n[action][model.outcomes.index(outcome)] += 1
            if measured_ns is not None:
                record = by_id[ref]
                sequence.append((measured_ns, record.at.run_index, record.at.seq,
                                 ref, action, outcome))
    pending = {j: action for j, action in jobs.items() if j not in finished and j not in abandoned}
    started, started_runs, event_ns = {}, {}, {}
    if model.durations or _work_timed(model):
        started = {job: [] for job in pending}
        started_runs = {job: [] for job in pending}
        for record in records:
            on_axis = axis is not None and record.at.run in axis.runs
            if on_axis:
                ns = axis.to_axis(record.at.run, record.at.mono_ns)
                event_ns[record.at.run] = max(event_ns.get(record.at.run, ns), ns)
            if isinstance(record.body, _AttemptStarted) and record.body.job in pending:
                job = record.body.job
                started_runs[job].append(record.at.run)
                if on_axis:
                    started[job].append(ns)
        started = {job: tuple(sorted(times)) for job, times in started.items()}
        started_runs = {job: tuple(sorted(runs, key=str)) for job, runs in started_runs.items()}
        for point in unread_preferences:
            if axis is not None and point.at.run in axis.runs:
                ns = axis.to_axis(point.at.run, point.at.mono_ns)
                event_ns[point.at.run] = max(event_ns.get(point.at.run, ns), ns)
    timing = None
    if _work_timed(model):
        from .quantity import read_timing as _read_timing
        timing = _read_timing(records, axis, jobs, attempts, pending)
    joint_timing = timing
    if model.durations and model.Q is not None and model.learnable:
        from .quantity import read_timing as _read_timing
        joint_timing = _read_timing(records, axis, jobs, attempts, pending)
    return Reading(n=n, unread=unread, pending=pending,
                   timeline=axis, sequence=tuple(sorted(sequence, key=lambda item:
                       (item[0], item[1], item[2], str(item[3])))),
                   arrivals=arrivals, _clock_issues=issues, started=started,
                   _started_runs=started_runs, _event_ns=event_ns,
                   preferences=tuple(r for r in records if isinstance(r.body, _Preference)),
                   unread_preferences=unread_preferences, timing=timing, _joint_timing=joint_timing)


@_dataclass(frozen=True, slots=True, kw_only=True)
class View:
    model: _GenerativeModel
    frontier: frozenset[str]
    belief: _Ref
    reading: Reading
    now_ns: int | None = None
    observed_ns: int | None = None
    preferences: _PreferenceView = _field(default_factory=_PreferenceView)
    check_events: tuple = ()
    fact_ancestors: object = _field(default_factory=dict)

    def __post_init__(self):
        from .values import _freeze
        object.__setattr__(self, "check_events", tuple(_freeze(source) for source in self.check_events))
        object.__setattr__(self, "fact_ancestors", _MappingProxyType({
            cid: frozenset(refs) for cid, refs in self.fact_ancestors.items()}))


@_dataclass(frozen=True, slots=True, kw_only=True)
class Draft:
    parents: frozenset[str]
    belief: _Ref
    content: _Payload
    contract: _ContractRef | None = None
    preference_inputs: tuple[_Ref, ...] = ()


@_dataclass(frozen=True, slots=True, kw_only=True)
class Commit:
    parents: frozenset[str]
    decided: _Record
    job: _Record


def _derive(model, n):
    try:
        q = _belief(model.D, [
            _log_likelihood(model.a[action], n[action], learnable=action in model.learnable)
            for action in model.actions
        ])
    except _ModelViolation:
        q = None
    a = {action: (_ledger(model.a[action], n[action])
                  if action in model.learnable else model.a[action])
         for action in model.actions}
    return q, a


def _timed(model):
    if _is_action_model(model):
        return True
    return model.Q is not None or bool(model.arrivals) or bool(model.durations) or _work_timed(model)


def _belief_contract(model):
    if _is_action_model(model):
        from .s4b_action_contracts import BELIEF as action_belief
        return action_belief
    if _joint_model(model):
        return _JOINT_BELIEF
    if model.duration_priors:
        return _QUANTITY_BELIEF
    if _learning_changing(model):
        return _S4B_BELIEF
    if _has_unreachable(model):
        return _S4D_BELIEF
    return _HAND_BELIEF if model.durations else (_TIME_BELIEF if _timed(model) else BELIEF)


def _anchor(reading):
    axis = reading.timeline
    if axis is None or axis.origin is None:
        return None, None
    if reading.sequence:
        return reading.sequence[-1][3], reading.sequence[-1][0]
    return axis.origin, axis.received_ns[axis.origin]


def _model_anchor(model, reading):
    if _joint_model(model):
        events = [e for e in reading.timing.events.values() if e.reading is not None]
        if not events:
            return None, None
        event = max(events, key=lambda e: (e.reading, e.run_index, e.seq, str(e.id)))
        return event.id, event.reading
    if model.durations and model.Q is None:
        axis = reading.timeline
        if axis is None or axis.origin is None:
            return None, None
        return axis.origin, axis.received_ns[axis.origin]
    return _anchor(reading)


def _evaluation_ns(reading, run, now_ns):
    """評価は取り込み済みの今のrunの出来事まで。葉も新しい時計も使わない (J7・J10)。"""
    return max(now_ns, reading._event_ns.get(run, now_ns))


def _hand_times(view, pending):
    """開始とrunごとの未到着から測る時刻の枝を作る (E1〜E6・J12・J14・J15)。"""
    model, reading = view.model, view.reading
    axis = reading.timeline
    run = axis.runs[-1]
    branches, earlier = [], []
    for job, action in pending:
        starts = reading.started[job]
        runs = reading._started_runs[job]
        if len(runs) > 1:
            raise ModelFalsified("a pending job with several attempts needs S5")
        if len(starts) != len(runs):
            raise ModelFalsified("a pending attempt has no clock")
        start = starts[0] if starts else view.now_ns
        if start > view.now_ns:
            raise ValueError("plan: now_ns precedes a pending attempt")
        observed = view.observed_ns
        if runs and runs[0] != run:
            observed = axis.run_end_ns[runs[0]]
            earlier.append(str(job))
        unseen = max(0, observed - start) if starts else 0
        try:
            points = _remaining(tuple((None if d is None else _duration_ns(d), p)
                                      for d, p in model.durations[action]), unseen)
        except _ModelViolation as exc:
            raise ModelFalsified("the hand's time model cannot explain the facts") from exc
        branches.append((model.a[action], tuple(
            (None if d is None else start if model.measures[action] == "start" else start + d, p)
            for d, p in points)))
    return tuple(branches), earlier


def _filtered(model, reading):
    logs = {action: _log_A(model.a[action]) for action in model.actions}
    return _filter_log(model.D, model.Q,
        ((ns, logs[action][model.outcomes.index(outcome)])
         for ns, _, _, _, action, outcome in reading.sequence))


def _derive_reading(model, reading):
    if _learning_changing(model):
        q, a, _ = _derive_state(model, reading)
        return q, a
    if model.Q is None:
        q, a = _derive(model, reading.n)
    else:
        a = dict(model.a)
        try:
            q = _log_probability(_filtered(model, reading))
        except _ModelViolation:
            q = None
    if reading._clock_issues:
        q = None
    return q, a


def _learning_changing(model):
    if _is_action_model(model):
        return False
    return model.Q is not None and bool(model.learnable)


@_dataclass(frozen=True, slots=True, kw_only=True)
class _LatticeSummary:
    """記録の説明用。次の計算は平均からではなく事実から作り直す。"""
    theta_mean: _Mapping[str, _np.ndarray] | None
    components: int | None


@_dataclass(frozen=True, slots=True)
class _QuantitySummary:
    weights: tuple | None
    partitions: int | None


def _derive_state(model, reading):
    """保存に渡す要約も同じ読みから作る。主体は書き換えない。"""
    if _is_action_model(model):
        from .action_entry import derive
        return derive(model, reading)
    if _joint_model(model):
        from .joint_entry import derive
        return derive(model, reading)
    if model.duration_priors:
        from .quantity import posterior, _normalized_positive
        q, a = _derive(model, reading.n)
        if reading._clock_issues:
            return q, a, _QuantitySummary(None, None)
        if not reading.timing.attempts:
            return q, a, _QuantitySummary(tuple(c.weight for c in model.measure.candidates), 1)
        try:
            quantity = posterior(model.duration_priors, model.measure, reading.timing)
            summary = _QuantitySummary(tuple(_normalized_positive(p, 0.) for p in quantity.measure_weights),
                                       quantity.stats.partitions)
        except _ModelViolation:
            summary = _QuantitySummary(None, 0)
        return q, a, summary
    if not _learning_changing(model):
        q, a = _derive_reading(model, reading)
        return q, a, None
    if reading._clock_issues:
        return None, dict(model.a), _LatticeSummary(theta_mean=None, components=None)
    _, anchor_ns = _anchor(reading)
    try:
        lattice = _learn(model, reading.sequence, until_ns=anchor_ns)
        q = _log_probability(lattice.marginal_state())
        summary = _LatticeSummary(theta_mean=lattice.theta_mean(), components=lattice.components())
    except _ModelViolation:
        q, summary = None, _LatticeSummary(theta_mean=None, components=0)
    return q, dict(model.a), summary


def plan_s4c(view: View, candidates: _Iterable[str], *, u: float) -> Draft:
    """model.1〜3だけを旧の計算に渡す。contentはS4cと同じ (C5・P5)。"""
    if view.model.duration_priors:
        raise ValueError("plan_s4c: learned durations are not supported")
    if _joint_model(view.model):
        raise ValueError("plan_s4c: progress models are not supported")
    if _learning_changing(view.model):
        raise ValueError("plan_s4c: learning under a changing state is not supported")
    if _has_unreachable(view.model):
        raise ValueError("plan_s4c: sui.model.4 is not supported")
    return _plan_s4c(view, candidates, u=u)


def _plan_s4c(view: View, candidates: _Iterable[str], *, u: float) -> Draft:
    """予測の枝で成分ごとに平均し、その G から一度だけ選ぶ純粋な計算。

    仮の回数を事実にせず、到着はモデルどおり必ず起こると仮定する。
    進行中なしは S1c と同じ計算順。失敗は例外、状態は持たない。
    P3・P3b・P4・P5・P6・P7・P8・P9、W1・W5。
    Qあり・所要なしはanchorからnowへ進め、枝は今を測る近似として記す (Q1・Q6・Q11)。
    所要ありは測定時刻ごとの対数の表。静的なら所要の検査後S3の計算 (I1〜I3・P2)。
    Qも所要もなければ起動もnowも要らず、timeを加えない (T7b)。
    """
    model = view.model
    time = None
    if model.Q is not None or model.durations:
        anchor, anchor_ns = _model_anchor(model, view.reading)
        if anchor is None:
            raise ValueError("plan: an adopted boot is required")
        if type(view.now_ns) is not int:
            raise ValueError("plan: now_ns is required in integer nanoseconds")
        if view.now_ns < anchor_ns:
            raise ValueError("plan: now_ns precedes anchor")
        time = {"anchor": str(anchor), "anchor_ns": anchor_ns,
                "now_ns": view.now_ns, "dt_s": (view.now_ns - anchor_ns) / 1e9,
                "pending_measures": "now"}
        if model.durations:
            if type(view.observed_ns) is not int or view.observed_ns > view.now_ns:
                raise ValueError("plan: integer observed_ns must not follow now_ns")
            time.pop("pending_measures")
            time.update(observed_ns=view.observed_ns, measures="model", start_is="attempt_record",
                        candidate_start="now", queued_start="now")
    unique = set()
    for action in candidates:
        if not isinstance(action, str):
            raise TypeError("candidate: expected str")
        if action not in model.actions:
            raise ValueError("candidate: unknown or empty action")
        unique.add(action)
    if not unique:
        raise ValueError("candidates: expected at least one action")
    actions = sorted(unique)
    pending = sorted(view.reading.pending.items(), key=lambda item: str(item[0]))
    hand_pending = None
    if model.durations:
        hand_pending, time["earlier_run_pending"] = _hand_times(view, pending)

    def expectation(n, index, action):
        q, a = _derive(model, n)
        if q is None:
            raise ModelFalsified("the model cannot explain the facts")
        if index == len(pending):
            risk, ambiguity, q_o = _efe(q, _expected_A(a[action]), model.log_C)
            novelty = _novelty(q, a[action]) if action in model.learnable else 0.0
            return risk, ambiguity, novelty, q_o
        waiting_action = pending[index][1]
        _, _, predicted = _efe(q, _expected_A(a[waiting_action]), model.log_C)
        risk, ambiguity, novelty = 0.0, 0.0, 0.0
        q_o = _np.zeros(len(model.outcomes))
        for outcome, probability in enumerate(predicted):
            if probability > 0:
                branch = dict(n)
                branch[waiting_action] = n[waiting_action].copy()
                branch[waiting_action][outcome] += 1
                r, a_value, nov, obs = expectation(branch, index + 1, action)
                risk += probability * r
                ambiguity += probability * a_value
                novelty += probability * nov
                q_o += probability * obs
        return risk, ambiguity, novelty, q_o

    def changing_expectation(log_q, index, action):
        try:
            q = _log_probability(log_q)
        except _ModelViolation as exc:
            raise ModelFalsified("the model cannot explain the facts") from exc
        if index == len(pending):
            risk, ambiguity, q_o = _efe(q, _expected_A(model.a[action]), model.log_C)
            return risk, ambiguity, 0.0, q_o
        waiting = pending[index][1]
        _, _, predicted = _efe(q, _expected_A(model.a[waiting]), model.log_C)
        likelihoods = _log_A(model.a[waiting])
        risk, ambiguity = 0.0, 0.0
        q_o = _np.zeros(len(model.outcomes))
        for outcome, probability in enumerate(predicted):
            if probability > 0:
                r, a_value, _, obs = changing_expectation(
                    _log_update(log_q, likelihoods[outcome]), index + 1, action)
                risk += probability * r
                ambiguity += probability * a_value
                q_o += probability * obs
        return risk, ambiguity, 0.0, q_o

    if view.reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    if model.Q is not None and not model.durations:
        now_log = _log_predict(_filtered(model, view.reading), model.Q, time["dt_s"])

    if model.Q is not None and model.durations:
        logs = {action: _log_A(model.a[action]) for action in model.actions}
        history = tuple((ns, logs[action][model.outcomes.index(outcome)])
                        for ns, _, _, _, action, outcome in view.reading.sequence)

    risks, ambiguities, novelties, outcomes = [], [], [], []
    for action in actions:
        if model.Q is not None and model.durations:
            candidate = (model.a[action], tuple(
                (view.now_ns if model.measures[action] == "start" else view.now_ns + _duration_ns(d), p)
                for d, p in model.durations[action]))
            try:
                risk, ambiguity, novelty, q_o = _hand_efe(
                    model.D, model.Q, history, hand_pending, candidate, model.log_C)
            except _ModelViolation as exc:
                raise ModelFalsified("the model cannot explain the facts") from exc
        else:
            risk, ambiguity, novelty, q_o = (expectation(view.reading.n, 0, action)
                if model.Q is None else changing_expectation(now_log, 0, action))
        risks.append(risk)
        ambiguities.append(ambiguity)
        novelties.append(novelty)
        outcomes.append(q_o.tolist())
    G = _np.array(risks) + _np.array(ambiguities) - _np.array(novelties)
    q_pi = _policy_posterior(G, model.gamma)
    chosen = actions[_select(q_pi, u)]
    content = {
        "candidates": actions, "risk": risks, "ambiguity": ambiguities,
        "novelty": novelties, "G": G.tolist(), "q_o": outcomes,
        "q_pi": q_pi.tolist(), "gamma": float(model.gamma), "u": float(u),
        "chosen": chosen,
        "pending": [{"job": str(j), "action": action} for j, action in pending],
    }
    if time is not None:
        content["time"] = time
    return Draft(parents=view.frontier, belief=view.belief, content=_Payload.json(content))


def _candidate_names(model, candidates):
    unique = set()
    for action in candidates:
        if not isinstance(action, str):
            raise TypeError("candidate: expected str")
        if action not in model.actions:
            raise ValueError("candidate: unknown or empty action")
        unique.add(action)
    if not unique:
        raise ValueError("candidates: expected at least one action")
    return tuple(sorted(unique))


def _one_step_time(view):
    model = view.model
    if model.Q is None and not model.durations and not _work_timed(model):
        return None
    anchor, anchor_ns = _model_anchor(model, view.reading)
    if anchor is None:
        raise ValueError("plan: an adopted boot is required")
    if type(view.now_ns) is not int:
        raise ValueError("plan: now_ns is required in integer nanoseconds")
    if view.now_ns < anchor_ns:
        raise ValueError("plan: now_ns precedes anchor")
    time = {"anchor": str(anchor), "anchor_ns": anchor_ns,
            "now_ns": view.now_ns, "dt_s": (view.now_ns - anchor_ns) / 1e9,
            "pending_measures": "now"}
    if model.durations or _work_timed(model):
        if type(view.observed_ns) is not int or view.observed_ns > view.now_ns:
            raise ValueError("plan: integer observed_ns must not follow now_ns")
        time.pop("pending_measures")
        time.update(observed_ns=view.observed_ns, measures="model", start_is="attempt_record",
                    candidate_start="now", queued_start="now")
    return time


def _one_step_components(log_q, a, learnable, costs):
    from scipy.special import logsumexp as _logsumexp
    log_q = _s4d_normalize(log_q)[0]
    log_A = _log_A(a)
    joint = _s4d_log_product(log_A, log_q[None, :])
    predicted = _logsumexp(joint, axis=1)
    supported = _np.isfinite(predicted)
    if _np.any(supported & _np.isposinf(costs)):
        expected = _math.inf
    else:
        with _np.errstate(over="ignore", invalid="ignore"):
            weighted = _np.exp(predicted[supported]) * costs[supported]
            _s4d_finite(weighted, "weighted cost exceeds numerical range")
            expected = float(_s4d_finite(_np.sum(weighted), "expected cost sum exceeds numerical range"))
    positive = _np.isfinite(joint)
    ambiguity = -float(_np.sum(_np.exp(joint[positive]) * log_A[positive]))
    entropy = -float(_np.sum(_np.exp(predicted[supported]) * predicted[supported]))
    information = entropy - ambiguity + (_s4d_novelty(log_q, a) if learnable else 0.0)
    return expected, information


def _average_components(branches):
    expected, information = 0.0, 0.0
    for log_probability, (branch_cost, branch_information) in branches:
        probability = _math.exp(log_probability)
        # 正の枝の重みが0に丸まっても禁止は取り消さない。
        expected = _s4d_cost_sum((expected, _s4d_weighted_cost(probability, branch_cost)))
        information = float(_s4d_finite(information + probability * branch_information,
                                       "expected information exceeds numerical range"))
    return expected, information


def _one_step(view, actions, resolved):
    """外の費用と条件つき情報を分ける。Noneの報告を仮の観測にしない (N3・C4・C5)。"""
    from scipy.special import logsumexp as _logsumexp
    model, reading = view.model, view.reading
    time = _one_step_time(view)
    pending = sorted(reading.pending.items(), key=lambda item: str(item[0]))
    hand_pending = None
    if model.durations:
        hand_pending, time["earlier_run_pending"] = _hand_times(view, pending)
    if reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    costs = _np.array([cost(resolved, _EvaluationInput(evaluation="one_step",
        candidate_outcome=outcome)) for outcome in model.outcomes])
    if _learning_changing(model):
        return _lattice_one_step(view, actions, pending, hand_pending, costs), time

    def static(n, index, action):
        log_q = _s4d_log_belief(model.D, [_s4d_likelihood(model.a[name], n[name],
            learnable=name in model.learnable) for name in model.actions])
        a = {name: _ledger(model.a[name], n[name]) if name in model.learnable else model.a[name]
             for name in model.actions}
        if index == len(pending):
            return _one_step_components(log_q, a[action], action in model.learnable, costs)
        waiting = pending[index][1]
        present, absent = 0.0, -_math.inf
        if hand_pending is not None:
            points = hand_pending[index][1]
            present = float(_logsumexp([_math.log(p) for ns, p in points if ns is not None]))
            absent = float(_logsumexp([_math.log(p) for ns, p in points if ns is None]))
        branches = []
        if _math.isfinite(absent):
            branches.append((absent, static(n, index + 1, action)))
        if _math.isfinite(present):
            predicted = _logsumexp(_s4d_log_product(_log_A(a[waiting]), log_q[None, :]), axis=1)
            for outcome, probability in enumerate(predicted):
                if _np.isfinite(probability):
                    branch = dict(n)
                    branch[waiting] = n[waiting].copy()
                    branch[waiting][outcome] += 1
                    branches.append((float(_s4d_log_product(present, probability)),
                                     static(branch, index + 1, action)))
        return _average_components(branches)

    def changing(log_q, index, action):
        log_q = _s4d_normalize(log_q)[0]
        if index == len(pending):
            return _one_step_components(log_q, model.a[action], False, costs)
        waiting = pending[index][1]
        likelihoods = _log_A(model.a[waiting])
        predicted = _logsumexp(_s4d_log_product(likelihoods, log_q[None, :]), axis=1)
        return _average_components((probability, changing(
            _s4d_log_product(log_q, likelihoods[outcome]), index + 1, action))
            for outcome, probability in enumerate(predicted) if _np.isfinite(probability))

    def hand(action):
        from scipy.special import logsumexp as _branch_logsumexp
        logs = {name: _log_A(model.a[name]) for name in model.actions}
        history = tuple((ns, logs[name][model.outcomes.index(outcome)])
                        for ns, _, _, _, name, outcome in reading.sequence)
        times = tuple((view.now_ns if model.measures[action] == "start" else
                       view.now_ns + _duration_ns(d), p) for d, p in model.durations[action])
        branches = []
        for combination in _product(*(points for _, points in hand_pending), times):
            weight = _math.fsum(_math.log(p) for _, p in combination)
            measured = tuple((ns, a) for (a, _), (ns, _) in zip(hand_pending, combination[:-1])
                             if ns is not None)
            joint = _s4d_hand_joint_log(model.D, model.Q, history, measured, combination[-1][0])
            for log_q, mass in zip(joint, _branch_logsumexp(joint, axis=1)):
                if _np.isfinite(mass):
                    branches.append((float(_s4d_log_product(weight, mass)),
                        _one_step_components(log_q, model.a[action], False, costs)))
        return _average_components(branches)

    try:
        logs = {name: _log_A(model.a[name]) for name in model.actions}
        now_log = (_s4d_log_predict(_s4d_filter_log(model.D, model.Q,
            ((ns, logs[name][model.outcomes.index(outcome)])
             for ns, _, _, _, name, outcome in reading.sequence)), model.Q, time["dt_s"])
                   if model.Q is not None and not model.durations else None)
        components = [hand(action) if model.Q is not None and model.durations else
                      static(reading.n, 0, action) if model.Q is None else
                      changing(now_log, 0, action) for action in actions]
    except _ModelViolation as exc:
        raise ModelFalsified("the model cannot explain the facts") from exc
    return components, time


def _lattice_one_step(view, actions, pending, hand_pending, costs):
    """所要の枝ごとに格子の情報を求めてから平均する。"""
    model = view.model
    history = tuple((ns, action, outcome) for ns, _, _, _, action, outcome in view.reading.sequence)
    points = (tuple(times for _, times in hand_pending) if hand_pending is not None else
              tuple(((view.now_ns, 1.),) for _ in pending))

    def components(action):
        times = (tuple((view.now_ns if model.measures[action] == "start" else
                        view.now_ns + _duration_ns(d), p) for d, p in model.durations[action])
                 if model.durations else ((view.now_ns, 1.),))
        for combination in _product(*points, times):
            weight = _math.fsum(_math.log(p) for _, p in combination)
            measured = tuple((job, name, ns) for (job, name), (ns, _) in zip(pending, combination[:-1]))
            table = _lattice_hand_table(model, history, measured, action, capture_ns=combination[-1][0])
            yield weight, _lattice_components(model, table, action, costs)

    try:
        return [_average_components(components(action)) for action in actions]
    except _ModelViolation as exc:
        raise ModelFalsified("the model cannot explain the facts") from exc


def plan(view: View, candidates: _Iterable[str], *, u: float) -> Draft:
    """採用した好みだけで決める。白紙は知る価値だけ、モデルのC・γは読まない (C4)。"""
    if _is_action_model(view.model):
        from .action_entry import public_evaluate, _candidates
        from .action_types import default_budget, ActionIncompatible
        actions = _candidates(view.model, candidates)
        resolved = _resolve_preference(_current_preference(view.preferences), view)
        evaluation = "one_step" if resolved.H_ns is None else "lookahead"
        if any(evaluation not in item.feature.evaluations for item in resolved.items):
            raise ActionIncompatible(reason="family_requirement", detail="feature is outside the evaluation type")
        return public_evaluate(view, actions, resolved, u=u, budget=default_budget())
    resolved = _resolve_preference(_current_preference(view.preferences), view)
    actions = _candidate_names(view.model, candidates)
    one_step = resolved.H_ns is None
    if not one_step and _learning_changing(view.model) and not _joint_model(view.model):
        if not view.model.durations or any(_duration_ns(d) <= 0 for points in view.model.durations.values() for d, _ in points if d is not None):
            raise OutsideEvaluationType("lookahead with learning under a changing state is 1d")
    for item in resolved.items:
        if ("one_step" if one_step else "lookahead") not in item.feature.evaluations:
            raise OutsideEvaluationType("the feature is outside this evaluation type")
    if not one_step:
        from .lookahead import evaluate as _evaluate_lookahead
        return _evaluate_lookahead(view, actions, resolved, u=u)
    if _joint_model(view.model):
        from .joint_entry import public_evaluate
        return public_evaluate(view, actions, resolved, u=u)
    if view.model.duration_priors:
        return _quantity_one_step(view, actions, resolved, u=u)
    if any(d is None for action in actions for d, _ in view.model.durations.get(action, ())):
        raise OutsideEvaluationType("one_step requires every candidate to return a result")
    components, time = _one_step(view, actions, resolved)
    expected, information = zip(*components)
    values = [c - i for c, i in components]
    probabilities = _s4d_policy(values, resolved.gamma)
    chosen = actions[_select(probabilities, u)]
    encode = lambda value: "+inf" if value == _math.inf else float(value)
    content = {"evaluation": "one_step", "items": [
        {"id": str(item.id), "rule": {"name": item.rule.name, "version": item.rule.version}}
        for item in resolved.items], "style": None if resolved.style is None else str(resolved.style),
        "H_ns": None, "gamma": resolved.gamma, "candidates": list(actions), "u": float(u),
        "chosen": chosen, "J": list(map(encode, values)), "q_pi": probabilities.tolist(),
        "expected_cost": list(map(encode, expected)), "information": list(map(float, information))}
    if time is not None:
        content["time"] = time
    inputs = tuple(item.id for item in resolved.items) + (() if resolved.style is None else (resolved.style,))
    return Draft(parents=view.frontier, belief=view.belief, content=_Payload.json(content),
                 contract=_S4D_DECISION, preference_inputs=inputs)


def _quantity_one_step(view, actions, resolved, *, u):
    from .quantity import posterior, timing_context, FutureRecordsQuery, one_step_values
    from .names import NameBelief
    from .values import _thaw
    model, reading = view.model, view.reading
    if any(model.duration_priors[action].base.p_inf > 0 for action in actions):
        raise OutsideEvaluationType("one_step requires every candidate to return a result")
    if reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    time = _one_step_time(view)
    run = reading.timeline.runs[-1]
    pending = tuple(sorted(reading.pending.items(), key=lambda item: str(item[0])))
    earlier = []
    for job, _ in pending:
        runs = reading._started_runs[job]
        if len(runs) > 1:
            raise ModelFalsified("a pending job with several attempts needs S5")
        if len(reading.started[job]) != len(runs):
            raise ModelFalsified("a pending attempt has no clock")
        if reading.started[job] and reading.started[job][0] > view.now_ns:
            raise ValueError("plan: now_ns precedes a pending attempt")
        if runs and runs[0] != run:
            earlier.append(str(job))
    sources = view.check_events
    if not sources:
        raise ValueError("plan: check_events must identify the receipt at observed_ns")
    time.update(check_events=[_thaw(source) for source in sources], earlier_run_pending=earlier)
    context = timing_context(reading.timing, run=run, observed_ns=view.observed_ns,
                             check_events=sources, fact_ancestors=view.fact_ancestors)
    costs = _np.array([cost(resolved, _EvaluationInput(evaluation="one_step", candidate_outcome=outcome))
                       for outcome in model.outcomes])
    tolerance = 1e-12
    try:
        quantity = posterior(model.duration_priors, model.measure, context, tolerance=tolerance / 8)
        names = NameBelief(model, reading)
        components = [one_step_values(quantity, names, pending, FutureRecordsQuery(action, view.now_ns, run),
                                      costs, tolerance=tolerance) for action in actions]
    except _ModelViolation as exc:
        raise ModelFalsified("the model cannot explain the facts") from exc
    information = [item.information.midpoint for item in components]
    expected = [item.expected_cost for item in components]
    values = [_s4d_cost_sum((c, -i)) for c, i in zip(expected, information)]
    probabilities = _s4d_policy(values, resolved.gamma)
    chosen = actions[_select(probabilities, u)]
    encode = lambda value: "+inf" if value == _math.inf else float(value)
    content = {"evaluation": "one_step", "items": [
        {"id": str(item.id), "rule": {"name": item.rule.name, "version": item.rule.version}}
        for item in resolved.items], "style": None if resolved.style is None else str(resolved.style),
        "H_ns": None, "gamma": resolved.gamma, "candidates": list(actions), "u": float(u), "chosen": chosen,
        "J": list(map(encode, values)), "q_pi": probabilities.tolist(),
        "expected_cost": list(map(encode, expected)), "information": information, "time": time,
        "information_parts": [{"names": item.names_information,
            "durations": [item.durations_information.lower, item.durations_information.upper]} for item in components],
        "information_bounds": [[item.information.lower, item.information.upper] for item in components],
        "tolerance": tolerance}
    inputs = tuple(item.id for item in resolved.items) + (() if resolved.style is None else (resolved.style,))
    return Draft(parents=view.frontier, belief=view.belief, content=_Payload.json(content),
                 contract=_QUANTITY_DECISION, preference_inputs=inputs)


def replay_decision(*, model: _GenerativeModel, ledger: _Ledger, decision: str) -> Draft:
    """約束とモデルの方式を確かめ、親から全欄とinputsを完全照合する (C8・P5)。"""
    if _is_action_model(model):
        from .action_persistence import replay
        return replay(model=model, ledger=ledger, decision=decision)
    entry, record = ledger.entry(decision), ledger.record(decision)
    if not isinstance(record.body, _Decided):
        raise ValueError("decision: expected Decided")
    contract = record.body.contract
    if contract not in (_JOINT_DECISION, _S4D_DECISION, _QUANTITY_DECISION, DECISION, _TIME_DECISION, _HAND_DECISION):
        raise ValueError("decision: incompatible contract")
    legacy_contract = (_HAND_DECISION if model.durations else
                       _TIME_DECISION if model.Q is not None else DECISION)
    if _joint_model(model) and contract != _JOINT_DECISION:
        raise RebuildMismatch(fields=("contract",))
    if model.duration_priors and contract not in (_JOINT_DECISION, _QUANTITY_DECISION):
        raise RebuildMismatch(fields=("contract",))
    if not model.duration_priors and contract == _QUANTITY_DECISION:
        raise RebuildMismatch(fields=("contract",))
    if _learning_changing(model) and contract not in (_JOINT_DECISION, _S4D_DECISION):
        raise RebuildMismatch(fields=("contract",))
    if contract not in (_JOINT_DECISION, _S4D_DECISION, _QUANTITY_DECISION) and contract != legacy_contract:
        raise RebuildMismatch(fields=("contract",))
    if not record.body.inputs:
        raise RebuildMismatch(fields=("inputs",))
    beliefs = [e for e in ledger.entries_of(record.body.inputs[0])
               if e.parents == entry.parents and e.body_type is _Prediction]
    if not beliefs:
        raise RebuildMismatch(fields=("inputs",))
    subject = Agent.restore(model=model, lineage="replay", ledger=ledger,
                            belief=min(beliefs, key=lambda e: e.cid).cid)
    data = _json_content(record.body.content)
    if not isinstance(data, dict):
        raise RebuildMismatch(fields=("content",))
    try:
        time = data.get("time", {})
        options = {"check_events": time.get("check_events", ())} if _work_timed(model) else {}
        view = subject.view(now_ns=time.get("now_ns"), observed_ns=time.get("observed_ns"), **options)
        draft = (plan if contract in (_JOINT_DECISION, _S4D_DECISION, _QUANTITY_DECISION) else plan_s4c)(
            view, data["candidates"], u=data["u"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RebuildMismatch(fields=("content",)) from exc
    differences = []
    if (draft.belief, *draft.preference_inputs) != record.body.inputs:
        differences.append("inputs")
    rebuilt = draft.content.as_json()
    if draft.content != record.body.content:
        differences.extend(sorted(key for key in set(data) | set(rebuilt)
                                  if data.get(key) != rebuilt.get(key)))
        if not differences:
            differences.append("content")
    if differences:
        raise RebuildMismatch(fields=tuple(differences))
    return draft


_REASONS = frozenset({"no_attempt", "unknown_attempt", "unreadable_attempt", "contract",
                      "content", "unknown_outcome", "impossible", "ambiguous_attempt",
                      "no_clock", "no_receipt_time"})


def _check_belief_content(data, *, timed=False, lattice_model=None, quantity_model=None, joint_model=None) -> None:
    if joint_model is not None:
        from .joint_entry import check_belief_content
        check_belief_content(data, joint_model)
        return
    if quantity_model is not None:
        _check_quantity_content(data, quantity_model)
        return
    if lattice_model is not None:
        _check_lattice_content(data, lattice_model)
        return
    def numbers(values, *, integers=False):
        return isinstance(values, list) and all(
            (type(value) is int and value >= 0) if integers else
            (type(value) in (int, float) and _math.isfinite(value)) for value in values)

    def names(values):
        return isinstance(values, list) and all(isinstance(value, str) for value in values)

    keys = {"model", "states", "outcomes", "q", "a", "n", "unread"}
    if timed:
        keys |= {"time", "arrivals"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("belief content: expected exactly the schema keys")
    if timed:
        time, arrivals = data["time"], data["arrivals"]
        if (not isinstance(time, dict) or set(time) != {"anchor", "anchor_ns", "clock_issues"}
                or not (time["anchor"] is None or isinstance(time["anchor"], str))
                or not (time["anchor_ns"] is None or type(time["anchor_ns"]) is int)
                or (time["anchor"] is None) != (time["anchor_ns"] is None)
                or not isinstance(time["clock_issues"], list)
                or any(not isinstance(issue, dict) for issue in time["clock_issues"])):
            raise ValueError("belief content: invalid time")
        if not isinstance(arrivals, dict):
            raise ValueError("belief content: invalid arrivals")
        for route, stats in arrivals.items():
            if (not isinstance(route, str) or not isinstance(stats, dict)
                    or set(stats) != {"N", "T_ns", "alpha", "beta_s", "outside"}
                    or any(type(stats[k]) is not int or stats[k] < 0 for k in ("N", "T_ns"))
                    or any(type(stats[k]) is not float or not _math.isfinite(stats[k])
                           or stats[k] <= 0 for k in ("alpha", "beta_s"))
                    or not names(stats["outside"])):
                raise ValueError("belief content: invalid arrival statistics")
    if not isinstance(data["model"], str) or not names(data["states"]) or not names(data["outcomes"]):
        raise ValueError("belief content: invalid model or named axes")
    if data["q"] is not None and not numbers(data["q"]):
        raise ValueError("belief content: q must be a numeric list or null")
    if data["q"] is not None and len(data["q"]) != len(data["states"]):
        raise ValueError("belief content: q must match the states axis")
    if not isinstance(data["n"], dict) or any(
            not isinstance(key, str) or not numbers(value, integers=True) for key, value in data["n"].items()):
        raise ValueError("belief content: invalid n")
    if not isinstance(data["a"], dict) or any(
            not isinstance(key, str) or not isinstance(value, list) or
            any(not numbers(row) for row in value) for key, value in data["a"].items()):
        raise ValueError("belief content: invalid a")
    if any(len(value) != len(data["outcomes"]) for value in data["n"].values()):
        raise ValueError("belief content: n must match the outcomes axis")
    if any(len(value) != len(data["outcomes"]) or
           any(len(row) != len(data["states"]) for row in value)
           for value in data["a"].values()):
        raise ValueError("belief content: a must match the outcomes and states axes")
    if not isinstance(data["unread"], list):
        raise ValueError("belief content: unread must be a list")
    for item in data["unread"]:
        if (not isinstance(item, dict) or set(item) != {"id", "reason"}
                or not isinstance(item["id"], str) or not isinstance(item["reason"], str)
                or item["reason"] not in _REASONS):
            raise ValueError("belief content: invalid unread item")
        try:
            kind, value = item["id"].split(":", 1)
            ref = _Ref(_RefKind(kind), value)
            if ref.kind is not _RefKind.OBSERVATION:
                raise ValueError("unread id must be an observation")
        except ValueError as exc:
            raise ValueError("belief content: invalid unread id") from exc


def _check_quantity_content(data, model):
    additions = {"durations", "measure", "quantity"}
    if not isinstance(data, dict) or not additions <= data.keys():
        raise ValueError("belief content: missing quantity fields")
    _check_belief_content({k: v for k, v in data.items() if k not in additions}, timed=True)
    counts = data["durations"]
    states = {"complete", "pending", "queued", "unknown", "unreadable"}
    if (not isinstance(counts, dict) or set(counts) != set(model.actions) or
            any(not isinstance(row, dict) or set(row) != states or
                any(type(n) is not int or n < 0 for n in row.values()) for row in counts.values())):
        raise ValueError("belief content: invalid duration counts")
    measure, quantity = data["measure"], data["quantity"]
    if not isinstance(measure, dict) or set(measure) != {"weights"}:
        raise ValueError("belief content: invalid measure")
    weights = measure["weights"]
    if weights is not None and (not isinstance(weights, list) or len(weights) != len(model.measure.candidates) or
            any(type(w) not in (float, int) or not _math.isfinite(w) or w < 0 for w in weights) or
            not _math.isclose(_math.fsum(weights), 1., rel_tol=1e-12, abs_tol=1e-12)):
        raise ValueError("belief content: invalid measure weights")
    if (not isinstance(quantity, dict) or set(quantity) != {"partitions"} or
            (quantity["partitions"] is not None and
             (type(quantity["partitions"]) is not int or quantity["partitions"] < 0))):
        raise ValueError("belief content: invalid quantity partitions")


def _check_lattice_content(data, model):
    """新しい表紙では平均と固定の表を区別して検査する。"""
    keys = {"model", "states", "outcomes", "q", "theta_mean", "fixed", "n",
            "lattice", "unread", "time", "arrivals"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("belief content: expected exactly the schema keys")
    theta, fixed, summary = data["theta_mean"], data["fixed"], data["lattice"]
    if (not isinstance(fixed, dict) or set(fixed) != set(model.actions) - model.learnable
            or (theta is not None and (not isinstance(theta, dict) or set(theta) != model.learnable))
            or (theta is None) != (data["q"] is None)):
        raise ValueError("belief content: invalid theta_mean or fixed actions")
    if (not isinstance(summary, dict) or set(summary) != {"components"}
            or not (summary["components"] is None or
                    type(summary["components"]) is int and summary["components"] >= 0)):
        raise ValueError("belief content: invalid lattice components")
    if (data["q"] is None) != (summary["components"] in (None, 0)):
        raise ValueError("belief content: lattice support differs from q")
    ordinary = {key: value for key, value in data.items() if key not in ("theta_mean", "fixed", "lattice")}
    ordinary["a"] = {**fixed, **({} if theta is None else theta)}
    _check_belief_content(ordinary, timed=True)


def _quantity_fact_ancestors(ledger, frontier, reading):
    """固定した親の下だけから、CIDを量の出来事へ解決する。"""
    result = {}
    pending = [(cid, False) for cid in sorted(frontier)]
    while pending:
        cid, ready = pending.pop()
        if cid in result:
            continue
        entry = ledger.entry(cid)
        if not ready:
            pending.append((cid, True))
            pending.extend((parent, False) for parent in sorted(entry.parents) if parent not in result)
            continue
        refs = frozenset().union(*(result[parent] for parent in entry.parents))
        if entry.id in reading.timing.events:
            refs |= {entry.id}
        result[cid] = refs
    return _MappingProxyType(result)


class Agent:
    """一つのスレッドで信念と帳面の版を管理する。

    正となる状態は先端。読み・信念・帳面はその下の事実の集合から作り直す。
    """

    def __init__(self, *, model: _GenerativeModel, lineage: str,
                 component: str = "sui.agent") -> None:
        if _is_action_model(model):
            from .action_entry import derive
            _Producer(component=component, code_version=CODE_VERSION,
                      state=_StateRef(lineage=lineage, revision=0))
            self._model, self._lineage, self._component = model, lineage, component
            self._frontier = frozenset()
            self._model_ref = _model_ref(model)
            self._reading = read(model, ())
            self._preferences = _PreferenceView()
            self._fact_ancestors = _MappingProxyType({})
            self._q, self._a, self._lattice = derive(model, self._reading)
            self._revision, self._belief = 0, None
            return
        if not isinstance(model, _GenerativeModel):
            raise TypeError("model: expected GenerativeModel")
        _Producer(component=component, code_version=CODE_VERSION,
                  state=_StateRef(lineage=lineage, revision=0))
        self._model = model
        self._lineage = lineage
        self._component = component
        self._frontier: frozenset[str] = frozenset()
        self._model_ref = _model_ref(model)
        self._reading = read(model, ())
        self._preferences = _PreferenceView()
        self._fact_ancestors = _MappingProxyType({})
        self._q, self._a, self._lattice = _derive_state(model, self._reading)
        self._revision = 0
        self._belief: _Record | None = None

    @property
    def frontier(self) -> frozenset[str]:
        return self._frontier

    @property
    def model_ref(self) -> str:
        return self._model_ref

    @property
    def unread(self) -> tuple[tuple[_Ref, str], ...]:
        return tuple(sorted(self._reading.unread.items(), key=lambda item: str(item[0])))

    @property
    def q(self) -> _np.ndarray:
        """今の信念を読み取り専用のコピーで返す。"""
        if self._q is None:
            if _is_action_model(self._model):
                from .action_types import ActionIncomplete, ActionModelFalsified
                if self._lattice["status"] == "unexplained":
                    raise ActionModelFalsified(reason=self._lattice["reason"], detail="action facts cannot be explained")
                raise ActionIncomplete(reason=self._lattice["reason"] or "algorithm_unavailable",
                                       detail="action posterior is not available")
            if _joint_model(self._model) and self._lattice.status == "incomplete":
                from .quantity import IntegrationIncomplete
                raise IntegrationIncomplete(self._lattice.reason)
            raise ModelFalsified("the model cannot explain the facts")
        return _readonly(self._q)

    def counts(self, action: str) -> _np.ndarray:
        """行動の数え上げを読み取り専用のコピーで返す。"""
        if _is_action_model(self._model):
            raise ValueError("counts: action posterior has no single ledger")
        if _joint_model(self._model) or _learning_changing(self._model):
            raise ValueError("counts: no single ledger under a changing state")
        if not isinstance(action, str):
            raise TypeError("action: expected str")
        if action not in self._a:
            raise ValueError("action: unknown action")
        return _readonly(self._a[action])

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def producer(self) -> _Producer:
        return self._producer(self._revision)

    def _producer(self, revision: int) -> _Producer:
        return _Producer(component=self._component, code_version=CODE_VERSION,
                         state=_StateRef(lineage=self._lineage, revision=revision))

    def _content(self, reading, q, a, *, lattice=None) -> dict:
        if _is_action_model(self._model):
            return lattice
        content = {
            "model": self.model_ref, "states": list(self._model.states),
            "outcomes": list(self._model.outcomes), "q": None if q is None else q.tolist(),
            "a": {action: counts.tolist() for action, counts in a.items()},
            "n": {action: counts.tolist() for action, counts in reading.n.items()},
            "unread": [{"id": str(ref), "reason": reason}
                       for ref, reason in sorted(reading.unread.items(), key=lambda item: str(item[0]))],
        }
        if _learning_changing(self._model) and not _joint_model(self._model):
            content.pop("a")
            content["theta_mean"] = (None if lattice.theta_mean is None else
                {action: mean.tolist() for action, mean in lattice.theta_mean.items()})
            content["fixed"] = {action: self._model.a[action].tolist()
                                for action in self._model.actions if action not in self._model.learnable}
            content["lattice"] = {"components": lattice.components}
        if self._model.duration_priors and not _joint_model(self._model):
            kinds = ("complete", "pending", "queued", "unknown", "unreadable")
            content["durations"] = {action: {kind: sum(a.action == action and a.state == kind
                for a in reading.timing.attempts) for kind in kinds} for action in self._model.actions}
            content["measure"] = {"weights": None if lattice.weights is None else list(lattice.weights)}
            content["quantity"] = {"partitions": lattice.partitions}
        if _joint_model(self._model):
            from .joint_entry import belief_fields
            content.pop("a")
            content["joint"] = belief_fields(self._model, reading, lattice)
        if _timed(self._model):
            anchor, ns = _model_anchor(self._model, reading)
            issues = reading._clock_issues if reading.timeline is None else reading.timeline.clock_issues
            content["time"] = {"anchor": None if anchor is None else str(anchor),
                               "anchor_ns": ns, "clock_issues": [
                                   {key: list(value) if isinstance(value, tuple) else value
                                    for key, value in issue.items()} for issue in issues]}
            content["arrivals"] = {}
            for route, stats in reading.arrivals.items():
                alpha, beta = _arrival_posterior(self._model.arrivals[route], stats)
                content["arrivals"][route] = {"N": stats.N, "T_ns": stats.T_ns,
                    "alpha": alpha, "beta_s": beta, "outside": list(map(str, stats.outside))}
        return content

    def _belief_record(self, reading, q, a, revision, *, clock, ids, lattice=None) -> _Record:
        return _Record(
            id=ids.new(_RefKind.PREDICTION), at=clock.now(), writer=_Role.MODEL,
            producer=self._producer(revision),
            body=_Prediction(target="belief", about=(), basis=(),
                             contract=_belief_contract(self._model),
                             content=_Payload.json(self._content(reading, q, a, lattice=lattice))),
        )

    def belief_record(self, *, clock: _Clock, ids: _IdSource, ledger: _Ledger) -> _Record:
        """現在の信念を葉として書き、成功した時だけ最新の記録にする。"""
        record = self._belief_record(self._reading, self._q, self._a, self.revision,
                                     clock=clock, ids=ids, lattice=self._lattice)
        ledger.append(record, self.frontier)
        self._belief = record
        return record

    def view(self, *, now_ns: int | None = None, observed_ns: int | None = None, check_events=()) -> View:
        """今の先端を固定する。保存qがNoneでも説明の可否は各評価入口で決める (N6)。"""
        if self._belief is None:
            raise ValueError("view: a belief record is required")
        return View(model=self._model, frontier=self.frontier,
                    belief=self._belief.id, reading=self._reading, now_ns=now_ns,
                    observed_ns=observed_ns, preferences=self._preferences, check_events=tuple(check_events),
                    fact_ancestors=self._fact_ancestors)

    def prepare(self, draft: Draft, *, clock: _Clock, ids: _IdSource) -> Commit:
        """両記録を作るだけ。見た親を保ち、台帳・主体を変えない (P10・K4・W12)。"""
        if _is_action_model(self._model):
            from .action_persistence import prepare
            return prepare(self, draft, clock, ids)
        decided = _Record(
            id=ids.new(_RefKind.DECISION), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_Decided(inputs=(draft.belief, *draft.preference_inputs),
                          contract=(draft.contract if draft.contract is not None else
                                    _HAND_DECISION if self._model.durations else
                                    _TIME_DECISION if self._model.Q is not None else DECISION),
                          content=draft.content),
        )
        job = _Record(
            id=ids.new(_RefKind.JOB), at=clock.now(), writer=_Role.MODEL,
            producer=self.producer,
            body=_JobOpened(decision=decided.id, step=0, contract=ACTION,
                            content=_Payload.json({"action": draft.content.as_json()["chosen"]})),
        )
        return Commit(parents=draft.parents, decided=decided, job=job)

    def commit(self, prepared: Commit, *, ledger: _Ledger) -> None:
        """親と信念の親を先に検査し、決定→仕事を書く。主体は変えない。

        検査失敗は無書き込み。同じ Commit の再試行で途中から続く (P10・K4・W12)。
        """
        if _is_action_model(self._model):
            from .action_persistence import commit
            return commit(self, prepared, ledger)
        for cid in prepared.parents:
            try:
                parent = ledger.entry(cid)
            except _UnknownEntry as exc:
                raise ValueError("commit: missing parent") from exc
            if not parent.is_event:
                raise ValueError("commit: parents must be events")
        inputs = prepared.decided.body.inputs
        if not inputs or (prepared.decided.body.contract not in (_JOINT_DECISION, _S4D_DECISION, _QUANTITY_DECISION) and len(inputs) != 1):
            raise ValueError("commit: one belief is required")
        if prepared.decided.body.contract in (_JOINT_DECISION, _S4D_DECISION, _QUANTITY_DECISION):
            data = prepared.decided.body.content.as_json()
            expected = [item["id"] for item in data["items"]]
            if data["style"] is not None:
                expected.append(data["style"])
            if list(map(str, inputs[1:])) != expected:
                raise ValueError("commit: preference inputs differ")
            ancestors = ledger.ancestors(prepared.parents)
            if any(not any(entry.cid in ancestors and entry.body_type is _Preference
                           for entry in ledger.entries_of(ref)) for ref in inputs[1:]):
                raise ValueError("commit: preference inputs must belong to the draft's parents")
        beliefs = ledger.entries_of(inputs[0])
        if not beliefs or not any(
                isinstance(ledger.record(entry.cid).body, _Prediction)
                and ledger.record(entry.cid).body.target == "belief"
                and ledger.record(entry.cid).body.contract ==
                    _belief_contract(self._model)
                and entry.parents == prepared.parents for entry in beliefs):
            raise ValueError("commit: belief parents differ")
        entry = ledger.append(prepared.decided, prepared.parents)
        ledger.append(prepared.job, {entry.cid})

    def decide(self, candidates: _Iterable[str], *, u: float, clock: _Clock,
               ids: _IdSource, ledger: _Ledger,
               now_mono_ns: int | None = None,
               observed_mono_ns: int | None = None, check_events=()) -> tuple[_Record, _Record]:
        """同期も新しい入口を通す。好みは取り込み済みのviewで固定 (C3・C4)。"""
        return self._decide(candidates, planner=plan, u=u, clock=clock, ids=ids, ledger=ledger,
                            now_mono_ns=now_mono_ns, observed_mono_ns=observed_mono_ns, check_events=check_events)

    def decide_s4c(self, candidates: _Iterable[str], *, u: float, clock: _Clock,
                   ids: _IdSource, ledger: _Ledger,
                   now_mono_ns: int | None = None,
                   observed_mono_ns: int | None = None) -> tuple[_Record, _Record]:
        """互換の入口で旧の約束とcontentを作る (C5・P5)。"""
        if self._model.duration_priors:
            raise ValueError("plan_s4c: learned durations are not supported")
        if _joint_model(self._model):
            raise ValueError("plan_s4c: progress models are not supported")
        return self._decide(candidates, planner=plan_s4c, u=u, clock=clock, ids=ids, ledger=ledger,
                            now_mono_ns=now_mono_ns, observed_mono_ns=observed_mono_ns)

    def _decide(self, candidates, *, planner, u, clock, ids, ledger,
                now_mono_ns=None, observed_mono_ns=None, check_events=()):
        """同期も同じ計算。所要ありの既定observedは取り込み済みの受信まで (J11)。

        既定は同じ受信の道を順番どおり抜けなく取り込む場合に使う。
        Qか所要ありは今のrunの起動とnowが要る (T5・T7b・J4・J8)。
        """
        if _is_action_model(self._model):
            from .action_types import ActionIncomplete
            raise ActionIncomplete(reason="algorithm_unavailable", detail="action synchronous execution belongs to public integration")
        now, observed = None, None
        if self._model.Q is not None or self._model.durations or _work_timed(self._model):
            axis = self._reading.timeline
            if axis is None or clock.run not in axis.runs or type(now_mono_ns) is not int:
                raise ValueError("decide: current run boot and now_mono_ns are required")
            now = axis.to_axis(clock.run, now_mono_ns)
            if self._model.durations or _work_timed(self._model):
                now = _evaluation_ns(self._reading, clock.run, now)
                if observed_mono_ns is not None and type(observed_mono_ns) is not int:
                    raise ValueError("decide: observed_mono_ns must be integer nanoseconds")
                observed = (axis.run_end_ns[clock.run] if observed_mono_ns is None else
                            axis.to_axis(clock.run, observed_mono_ns))
                if _work_timed(self._model) and observed_mono_ns is None and not check_events:
                    receipts = [e for e in self._reading.timing.events.values()
                                if e.run == clock.run and e.kind != "start" and e.reading is not None]
                    if not receipts:
                        raise ValueError("decide: an existing receipt is required")
                    last = max(receipts, key=lambda e: (e.run_index, e.seq, str(e.id)))
                    check_events = ({"fact": str(last.id)},)
        prepared = self.prepare(planner(self.view(now_ns=now, observed_ns=observed, check_events=check_events), candidates, u=u),
                                clock=clock, ids=ids)
        self.commit(prepared, ledger=ledger)
        return prepared.decided, prepared.job

    def adopt(self, ledger: _Ledger, *, clock: _Clock, ids: _IdSource,
              through: _Iterable[str] | None = None) -> _Record | None:
        """先端の下の事実を読み直し、葉の保存後にだけ全状態を採用する。"""
        target = ledger.heads() if through is None else ledger.maximal(through)
        for cid in target:
            if not ledger.entry(cid).is_event:
                raise _DerivedParent(cid)
        new, old = ledger.ancestors(target), ledger.ancestors(self.frontier)
        if not old <= new:
            raise ValueError("adopt: cannot move behind the current frontier")
        if new == old:
            return None
        snapshot = ledger.snapshot(target)
        reading = read(self._model, snapshot.records,
                       unread_preferences=snapshot.unread_preferences)
        preferences = _preference_view(ledger, target)
        fact_ancestors = (_quantity_fact_ancestors(ledger, target, reading)
                          if _work_timed(self._model) else None)
        if _is_action_model(self._model):
            from .action_joint import fact_ancestors as _action_fact_ancestors
            fact_ancestors = _action_fact_ancestors(ledger, target, reading)
        q, a, lattice = _derive_state(self._model, reading)
        revision = self.revision + 1
        record = self._belief_record(reading, q, a, revision, clock=clock, ids=ids, lattice=lattice)
        ledger.append(record, target)
        self._frontier, self._reading, self._q, self._a, self._revision, self._belief, self._preferences = (
            target, reading, q, a, revision, record, preferences)
        self._lattice = lattice
        if _work_timed(self._model):
            self._fact_ancestors = fact_ancestors
        elif _is_action_model(self._model):
            self._fact_ancestors = fact_ancestors
        return record

    @classmethod
    def restore(cls, *, model: _GenerativeModel, lineage: str, ledger: _Ledger,
                belief: str, component: str = "sui.agent") -> "Agent":
        """葉の親とモデルから復元し、保存値の全キーと完全一致で照合する。"""
        if _is_action_model(model):
            from .action_persistence import restore
            return restore(cls, model=model, lineage=lineage, ledger=ledger, belief=belief, component=component)
        entry = ledger.entry(belief)
        record = ledger.record(belief)
        if not isinstance(record.body, _Prediction) or record.body.target != "belief":
            raise ValueError("belief: expected Prediction with target belief")
        if record.body.contract != _belief_contract(model):
            raise ValueError("belief: incompatible contract")
        if record.producer.state is None:
            raise ValueError("belief: producer.state is required")
        data = _json_content(record.body.content)
        _check_belief_content(data, timed=_timed(model), lattice_model=model if _learning_changing(model) else None,
                              quantity_model=model if model.duration_priors else None,
                              joint_model=model if _joint_model(model) else None)
        subject = cls(model=model, lineage=lineage, component=component)
        if data["model"] != subject.model_ref:
            raise ModelMismatch("belief: model reference differs")
        snapshot = ledger.snapshot(entry.parents)
        reading = read(model, snapshot.records, unread_preferences=snapshot.unread_preferences)
        preferences = _preference_view(ledger, entry.parents)
        q, a, lattice = _derive_state(model, reading)
        rebuilt = subject._content(reading, q, a, lattice=lattice)
        differences = tuple(sorted(key for key in set(rebuilt) | set(data) if rebuilt.get(key) != data.get(key)
            or (key in ("time", "arrivals")
                and _Payload.json(rebuilt[key]) != _Payload.json(data[key]))
            or ((_learning_changing(model) or _work_timed(model))
                and _Payload.json(rebuilt[key]) != _Payload.json(data[key]))))
        if differences:
            raise RebuildMismatch(fields=differences)
        subject._frontier, subject._reading, subject._q, subject._a = entry.parents, reading, q, a
        subject._revision, subject._belief = record.producer.state.revision, record
        subject._preferences = preferences
        subject._lattice = lattice
        if _work_timed(model):
            subject._fact_ancestors = _quantity_fact_ancestors(ledger, entry.parents, reading)
        return subject
