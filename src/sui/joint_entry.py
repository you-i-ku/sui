"""Integer-record boundary of the certified stage-1 calculation.

Continuous stage-2 quadrature variables never cross this boundary. Model validity
and certification are distinct. Old successful evaluators and belief schemas keep
their paths; this adapter is only the newly enabled/public progress path.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import math
import sys
import numpy as np

from .model import ProgressModel, _joint_model, _work_timed, _duration_ns
from .progress import CompletionSpec, INFINITE_WORK
from .joint import JointModel, JointBelief, WorkPrior, KnownWorkLaw, NameSpec, Attempt, Completed, NotArrived
from .quantity import IntegrationIncomplete, timing_context, HistoryKernel
from .inference import ModelViolation, NumericalRange
from .values import MeasureSpec, InformationBounds, _thaw
from .joint_lookahead import evaluate, one_step_conditioned, Interval, policy_bounds
from .lookahead import OutsideEvaluationType, _policy
from .preference import EvaluationInput, cost
from .s4b1c_contracts import DECISION


def _normalized(values):
    values = tuple(F(v) for v in values)
    total = sum(values)
    return tuple(v/total for v in values)


def _prob(value):
    result = float(value)
    if value and not result:
        raise NumericalRange("joint summary: positive probability cannot be represented")
    return result


def _work(model):
    return model.work_priors if isinstance(model, ProgressModel) else model.duration_priors


def _unit_spec(model):
    if isinstance(model, ProgressModel):
        return model.completion
    # An old duration is defined to be work at known unit speed.
    return CompletionSpec(name="progress", version="1", actions=model.actions, states=model.states,
        work_unit="ns", time_unit="ns", speed_unit="ns/ns", share="all_actions", max_speed=1,
        candidates=(tuple(tuple(1 for _ in model.states) for _ in model.actions),), weights=(1,))


def stage1_model(model, *, allow_zero_work=False):
    spec = _unit_spec(model)
    if _work_timed(model):
        if any(p.base.name != "atoms" for p in _work(model).values()):
            raise IntegrationIncomplete("stage1_work: finite atomic work law is not certified")
        candidates = model.measure.candidates
        if any(c.spec.name != "exact" or c.spec.params for c in candidates):
            raise IntegrationIncomplete("stage1_hidden_time: clock process does not certify true times")
        # Identical exact candidates are the same process and provide no label
        # information. Their prior conditional law is unchanged by evidence.
        work = {a: WorkPrior(F(p.alpha), tuple((INFINITE_WORK if w is None else w, m)
                    for (w, _), m in zip(p.base.params["points"],
                                        _normalized(m for _, m in p.base.params["points"]))))
                for a, p in _work(model).items()}
    else:
        if not model.durations:
            raise IntegrationIncomplete("stage1_work: a known completion law is required")
        work = {a: KnownWorkLaw(tuple((INFINITE_WORK if d is None else _duration_ns(d), m)
                    for (d, _), m in zip(points, _normalized(p for _, p in points))))
                for a, points in model.durations.items()}
    finite = [w for p in work.values() for w, _ in p.points if w is not INFINITE_WORK]
    if not allow_zero_work and any(p.points == ((0, F(1)),) for p in work.values()):
        raise OutsideEvaluationType("certain_zero_completion: infinite repetition is outside lookahead")
    if not allow_zero_work and finite and min(finite) <= 0:
        raise IntegrationIncomplete("stage1_lower_work: positive finite work bound is not certified")
    names = {}
    for action in model.actions:
        columns = []
        for column in model.a[action].T:
            columns.append(tuple(F(v) for v in column) if action in model.learnable else _normalized(column))
        names[action] = NameSpec(tuple(columns), action in model.learnable, model.measures.get(action, "report"))
    return JointModel(completion=spec, work=work, names=names, outcomes=model.outcomes,
        initial=_normalized(model.D), Q=np.zeros((len(model.states), len(model.states))) if model.Q is None else model.Q,
        # With no finite atoms every completion is absent; the positive integer
        # quantum is a vacuous lower-bound certificate, not a work prior.
        measure=MeasureSpec("exact", "1", {}), w_star_ns=min((w for w in finite if w > 0), default=1),
        allow_zero_work=allow_zero_work)


def rebuild(model, reading, *, now_ns=None, observed_ns=None, check_events=(), fact_ancestors=None, allow_zero_work=False):
    """Fact-only reconstruction, including unread names' timing and causal checks."""
    world = stage1_model(model, allow_zero_work=allow_zero_work)
    timing = reading.timing if _work_timed(model) else reading._joint_timing
    if reading._clock_issues:
        raise ModelViolation("joint timeline cannot explain the facts")
    if timing is None:
        raise IntegrationIncomplete("stage1_history: attempt timing is unavailable")
    if now_ns is None:
        now_ns = max((e.reading for e in timing.events.values() if e.reading is not None), default=0)
    if observed_ns is not None:
        if reading.timeline is None or not reading.timeline.runs:
            raise ValueError("joint context: adopted boot required")
        timing = timing_context(timing, run=reading.timeline.runs[-1], observed_ns=observed_ns,
            check_events=check_events, fact_ancestors=fact_ancestors)
    outcomes = {ref: outcome for _, _, _, ref, _, outcome in reading.sequence}
    attempts, facts, labels = [], [], {}
    for item in timing.attempts:
        if item.action is None or item.state == "unreadable":
            raise IntegrationIncomplete("stage1_history: attempt has an unreadable start/action")
        if item.state == "queued":
            label = str(item.job)
            attempts.append(Attempt(label, item.action, now_ns))
            labels[label] = ("pending", item.action, 0, len(labels))
            continue
        start = timing.events[item.start_event]
        if start.reading is None or start.reading > now_ns:
            raise IntegrationIncomplete("stage1_history: true start cannot be identified")
        label = str(item.attempt)
        attempts.append(Attempt(label, item.action, start.reading))
        labels[label] = ("pending", item.action, start.reading-now_ns, len(labels))
        for ref in item.check_events:
            event = timing.events[ref]
            if event.reading is None or event.run != start.run:
                raise IntegrationIncomplete("stage1_history: check time cannot be identified")
            if event.reading <= now_ns:
                facts.append(NotArrived(label, event.reading, inclusive=True))
        if item.report_event is not None:
            report = timing.events[item.report_event]
            if report.run != start.run:
                raise OutsideEvaluationType("after_run_delivery: delivery law requires S5")
            if report.reading is None:
                raise IntegrationIncomplete("stage1_history: true completion time cannot be identified")
            facts.append(Completed(label, report.reading, outcomes.get(item.report_event)))
        elif item.state == "pending" and observed_ns is not None:
            if start.run != reading.timeline.runs[-1]:
                raise OutsideEvaluationType("after_run_delivery: pending attempt requires S5")
            if not any(isinstance(f, NotArrived) and f.label == label and f.until_ns >= now_ns for f in facts):
                if start.reading < now_ns:
                    raise IntegrationIncomplete("joint_pending_context: nonarrival at evaluation time is not certified")
        elif item.state == "unknown":
            raise IntegrationIncomplete("stage1_history: abandoned completion time is not identified")
    root = JointBelief(model=world, attempts=tuple(attempts), facts=tuple(facts),
                      origin_ns=0, observed_ns=now_ns, transition_tolerance=1e-16,
                      history_kernel=HistoryKernel(timing, world.measure))
    root.target_marginal(())  # Distinguish zero evidence from unfinished computation.
    return root, labels


@dataclass(frozen=True, slots=True)
class Summary:
    status: str
    reason: str | None
    theta: object
    work: object
    speeds: object
    measure: object
    components: int | None


def derive(model, reading):
    """Native model.7 joint marginal summary; unsupported facts stay in the ledger."""
    if not reading.timing.events and not reading.timing.attempts and not reading._clock_issues:
        theta = {a: np.array([list(map(_prob, _normalized(c))) for c in model.a[a].T]).T.tolist()
                 for a in model.learnable}
        def masses(p):
            if p.base.name == "atoms":
                return [m for _, m in p.base.params["points"] if m]
            params = p.base.params
            return [*params["masses"], params["tail"]["mass"], params["p_inf"]]
        return np.array(model.D), dict(model.a), Summary("prior", None, theta,
            {a: masses(p) for a, p in _work(model).items()}, list(map(float, _unit_spec(model).weights)),
            [c.weight for c in model.measure.candidates], 1)
    try:
        root, _ = rebuild(model, reading, allow_zero_work=True)
        marginal = root.target_marginal((root.observed_ns,))
        states = [F(0)]*len(model.states)
        for row, p in marginal.state_probabilities().items():
            states[row[0]] += p
        theta = {}
        for action in model.learnable:
            columns = []
            for s, original in enumerate(model.a[action].T):
                active = [i for i, v in enumerate(original) if v]
                values = marginal.mean(("names", action, s))
                column = [0.]*len(model.outcomes)
                for i, v in zip(active, values):
                    column[i] = _prob(v)
                columns.append(column)
            theta[action] = np.array(columns).T.tolist()
        work = {a: list(map(_prob, marginal.mean(("work", a)))) for a in model.actions}
        spec = _unit_spec(model)
        summary = Summary("prior" if not root.attempts else "complete", None, theta, work,
            list(map(float, spec.weights)), [c.weight for c in model.measure.candidates], len(marginal.components))
        return np.array(list(map(_prob, states))), dict(model.a), summary
    except ModelViolation:
        status, reason, components = "unexplained", "zero_joint_evidence", 0
    except (IntegrationIncomplete, OutsideEvaluationType) as exc:
        status, reason, components = "incomplete", str(exc), None
    if reading._clock_issues:
        status, reason, components = "no_axis", "timeline_unavailable", None
    return None, dict(model.a), Summary(status, reason, None, None, None, None, components)


def belief_fields(model, reading, summary):
    return {"status": summary.status, "reason": summary.reason, "theta_mean": summary.theta,
        "work_mean": summary.work, "speed_weights": summary.speeds, "measure_weights": summary.measure,
        "components": summary.components, "pending": [{"job": str(job), "action": action}
            for job, action in sorted(reading.pending.items(), key=lambda row: str(row[0]))]}


def check_belief_content(data, model):
    from .agent import _check_belief_content
    keys = {"model", "states", "outcomes", "q", "n", "unread", "time", "arrivals", "joint"}
    if not isinstance(data, dict) or set(data) != keys:
        raise ValueError("joint belief: expected exactly schema keys")
    ordinary = {k: v for k, v in data.items() if k != "joint"}
    ordinary["a"] = {a: model.a[a].tolist() for a in model.actions}
    _check_belief_content(ordinary, timed=True)
    summary = data["joint"]
    if not isinstance(summary, dict) or set(summary) != {"status", "reason", "theta_mean", "work_mean", "speed_weights", "measure_weights", "pending", "components"}:
        raise ValueError("joint belief: invalid summary fields")
    if summary["status"] not in ("prior", "complete", "incomplete", "unexplained", "no_axis"):
        raise ValueError("joint belief: invalid status")
    if summary["reason"] is not None and type(summary["reason"]) is not str:
        raise ValueError("joint belief: invalid reason")
    c = summary["components"]
    if c is not None and (type(c) is not int or c < 0):
        raise ValueError("joint belief: invalid component count")
    if not isinstance(summary["pending"], list) or any(not isinstance(p, dict) or set(p) != {"job", "action"}
            or type(p["job"]) is not str or p["action"] not in model.actions for p in summary["pending"]):
        raise ValueError("joint belief: invalid pending jobs")
    good = summary["status"] in ("prior", "complete")
    for key in ("theta_mean", "work_mean", "speed_weights", "measure_weights"):
        if good == (summary[key] is None):
            raise ValueError("joint belief: posterior fields disagree with status")
    if good:
        def probability(row):
            return isinstance(row, list) and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in row) and math.isclose(math.fsum(row), 1., abs_tol=1e-12)
        if not isinstance(summary["theta_mean"], dict) or not isinstance(summary["work_mean"], dict) or set(summary["theta_mean"]) != model.learnable or set(summary["work_mean"]) != set(model.actions):
            raise ValueError("joint belief: marginal action keys differ")
        if any(not probability(row) for row in summary["work_mean"].values()) or not probability(summary["speed_weights"]) or not probability(summary["measure_weights"]):
            raise ValueError("joint belief: invalid probability marginal")
        if len(summary["speed_weights"]) != len(_unit_spec(model).weights) or len(summary["measure_weights"]) != len(model.measure.candidates):
            raise ValueError("joint belief: candidate marginal lengths differ")
        for action, table in summary["theta_mean"].items():
            if not isinstance(table, list) or len(table) != len(model.outcomes) or any(not isinstance(row, list) or len(row) != len(model.states) for row in table) or any(not probability(list(column)) for column in zip(*table)):
                raise ValueError("joint belief: invalid theta_mean")
    if good != (data["q"] is not None) or (good and (c is None or c < 1)):
        raise ValueError("joint belief: state/status disagreement")


def _path(eta, labels):
    def named(value):
        return labels[value] if value in labels else ("new", int(value.split(":")[1])-len(labels))
    return EvaluationInput(evaluation="lookahead", O=tuple((ns, named(l), a, y) for ns, l, a, y in eta.O),
        A=tuple((ns, named(l), a) for ns, l, a in eta.A))


def _empty_window(model, reading, resolved):
    """Prove no report fits the ORIGINAL zero window, including clock bins.

    Positive true duration alone is insufficient: it may still produce the
    same tick reading. W/M at least every possible clock-bin width proves the
    next record is beyond the root reading, without identifying hidden phase.
    """
    if resolved.H_ns != 0 or reading.pending:
        return False
    if isinstance(model, ProgressModel) and model.completion.time_unit != "ns":
        return False
    if _work_timed(model):
        finite = []
        for prior in _work(model).values():
            if prior.base.name != "atoms" or any(w == 0 and p > 0 for w, p in prior.base.params["points"]):
                return False
            finite.extend(w for w, p in prior.base.params["points"] if w is not None and p > 0)
        if reading.timing.attempts:
            return False
        width = max(c.spec.params["width_ns"] if c.spec.name == "tick" else 1
                    for c in model.measure.candidates)
        bound = _unit_spec(model).max_speed
        return not finite or bound == 0 or min(finite) >= bound*width
    return False


def public_evaluate(view, candidates, resolved, *, u):
    from .agent import Draft, ModelFalsified, _one_step_time
    from .records import Payload
    if isinstance(u, bool) or not isinstance(u, (float, int)) or not 0 <= u < 1:
        raise ValueError("u: expected a number in [0, 1)")
    time = _one_step_time(view)
    if view.reading._clock_issues:
        raise ModelFalsified("the timeline cannot explain the facts")
    if _work_timed(view.model):
        if not view.check_events:
            raise ValueError("plan: check_events must identify the receipt at observed_ns")
        # Validate source/after even on the certified zero-window shortcut.
        timing_context(view.reading.timing, run=view.reading.timeline.runs[-1], observed_ns=view.observed_ns,
                       check_events=view.check_events, fact_ancestors=view.fact_ancestors)
        time["check_events"] = [_thaw(s) for s in view.check_events]
    time["earlier_run_pending"] = []
    if resolved.H_ns is not None and _work_timed(view.model) and any(
            p.base.name == "atoms" and all(w == 0 for w, m in p.base.params["points"] if m > 0)
            for p in _work(view.model).values()):
        raise OutsideEvaluationType("certain_zero_completion: infinite repetition is outside lookahead")
    if resolved.H_ns is None and _work_timed(view.model):
        priors, spec = _work(view.model), _unit_spec(view.model)
        for action in candidates:
            p = priors[action]
            if p.base.p_inf > 0:
                raise OutsideEvaluationType("one_step requires every candidate to return a result")
            index = view.model.actions.index(action)
            positive_work = p.base.name != "atoms" or any(w is not None and w > 0 and m > 0 for w, m in p.base.params["points"])
            if positive_work and any(not any(c[index]) for c in spec.candidates):
                raise OutsideEvaluationType("one_step requires every candidate to return a result")
    tolerance = 1e-9
    if _empty_window(view.model, view.reading, resolved):
        C = tuple(Interval(cost(resolved, EvaluationInput(evaluation="lookahead", A=((0, ("new", 0), a),))),
                           cost(resolved, EvaluationInput(evaluation="lookahead", A=((0, ("new", 0), a),)))) for a in candidates)
        I = tuple(InformationBounds(0., 0.) for _ in candidates)
        J = C
        q = tuple(map(float, _policy([c.midpoint for c in C], resolved.gamma)))
        qb = policy_bounds(J, resolved.gamma)
        chosen = candidates[next(i for i in range(len(q)) if u < math.fsum(q[:i+1]))]
        reasons = ["forbidden_terminal" if c.upper == math.inf else None for c in C]
        algorithm = "constant_empty_window"
    else:
        try:
            root, labels = rebuild(view.model, view.reading, now_ns=view.now_ns, observed_ns=view.observed_ns,
                check_events=view.check_events, fact_ancestors=view.fact_ancestors, allow_zero_work=resolved.H_ns is None)
            if resolved.H_ns is None:
                if any(w is INFINITE_WORK for a in candidates for w, _ in root.model.work[a].points):
                    raise OutsideEvaluationType("one_step requires every candidate to return a result")
                values = tuple(one_step_conditioned(root, a,
                    outcome_cost=lambda y: cost(resolved, EvaluationInput(evaluation="one_step", candidate_outcome=y)),
                    tolerance=tolerance, series_budget=2000, node_budget=20000) for a in candidates)
                C, I, J = tuple(v.expected_cost for v in values), tuple(v.information for v in values), tuple(v.J_bounds for v in values)
                q = tuple(map(float, _policy([v.J for v in values], resolved.gamma)))
                qb = policy_bounds(J, resolved.gamma)
                if any(b.upper-b.lower > tolerance for b in qb):
                    raise IntegrationIncomplete("joint_one_step_policy_accuracy: q width not reached")
                chosen = candidates[next(i for i in range(len(q)) if u < math.fsum(q[:i+1]))]
                reasons = [v.reason for v in values]
            else:
                deadline = view.now_ns+resolved.H_ns
                # Every Completed here is already in the adopted facts, even
                # when its name was unreadable. Not-yet-ingested reports are
                # the pending attempts: branches includes their arrivals in
                # the first E, including those at/before now certified by K.
                result = evaluate(root, candidates=candidates, deadline_ns=deadline, gamma=resolved.gamma, u=u,
                    terminal_cost=lambda eta: cost(resolved, _path(eta, labels)), cost_bound=sys.float_info.max,
                    tolerance=tolerance, series_budget=2000, node_budget=20000, refinement_budget=5)
                C = tuple(a.expected_cost for a in result.root.actions)
                I = tuple(a.information for a in result.root.actions)
                J = tuple(a.J_bounds for a in result.root.actions)
                q, qb, chosen = result.root.q, result.root.q_bounds, result.chosen
                reasons = [a.reason for a in result.root.actions]
            algorithm = "joint_stage1"
        except ModelViolation as exc:
            raise ModelFalsified("the model cannot explain the facts") from exc
    encode = lambda v: "+inf" if v == math.inf else float(v)
    box = lambda v: None if v is None else [encode(v.lower), encode(v.upper)]
    c, i = [encode(v.midpoint) for v in C], [None if v is None else v.midpoint for v in I]
    j = ["+inf" if v is None or c0 == "+inf" else c0-v.midpoint for c0, v in zip(c, I)]
    time["deadline_ns"] = None if resolved.H_ns is None else view.now_ns+resolved.H_ns
    content = {"evaluation": "one_step" if resolved.H_ns is None else "lookahead", "items": [
        {"id": str(item.id), "rule": {"name": item.rule.name, "version": item.rule.version}} for item in resolved.items],
        "style": None if resolved.style is None else str(resolved.style), "H_ns": resolved.H_ns,
        "gamma": resolved.gamma, "candidates": list(candidates), "u": float(u), "chosen": chosen,
        "expected_cost": c, "information": i, "J": j, "q_pi": list(q), "time": time,
        "expected_cost_bounds": list(map(box, C)), "information_bounds": list(map(box, I)),
        "J_bounds": list(map(box, J)), "q_pi_bounds": list(map(box, qb)), "undefined_reason": reasons,
        "root": {"belief": str(view.belief), "parents": sorted(view.frontier)},
        "algorithm": {"name": algorithm, "version": "1", "stage": "1"}, "tolerance": tolerance,
        "guarantee": "certified_truncation_without_floating_rounding"}
    return Draft(parents=view.frontier, belief=view.belief, content=Payload.json(content), contract=DECISION,
                 preference_inputs=tuple(item.id for item in resolved.items) + (() if resolved.style is None else (resolved.style,)))
