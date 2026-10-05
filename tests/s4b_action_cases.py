"""Specification-owned fixtures for S4b action v0.19, not implementation output.

Default (§3-10-2:523): states 0/1, D fair, Q=0, known fair B,
known work=1e9 ns at speed 1 ns/ns (one second), exact shared clock,
wait-dispatch/1 with zero think/receipt/chi delays and at=0. Mathematical
fixtures do not observe confirmations (all three null), so branches go to the
specified report; contract variants explicitly enable zero-delay confirmations.
No root pending work. Report measurement is post; completion is after the
impulse and before the next choice. H includes its endpoint. Law parameters
are known unless a test explicitly changes them. Empty preferences mean
terminal cost 0; gamma=1, u=1/4. Forced commands are not policy evaluations.

Imports of new production modules occur only while tests run. Missing modules
are normal failures, never skip/xfail, and do not prevent collect-only.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as F
import importlib
import json
from pathlib import Path

NS = 1_000_000_000
I = [[1, 0], [0, 1]]
C = [[1, 1], [0, 0]]
FLIP = [[0, 1], [1, 0]]
FAIR = [[F(1, 2), F(1, 2)], [F(1, 2), F(1, 2)]]


def api(module):
    return importlib.import_module("sui." + module)


def rational(x):
    x = F(x)
    return [x.numerator, x.denominator]


def table(rows):
    return [[rational(x) for x in row] for row in rows]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def delay(value=F(0)):
    return {"given": [], "rows": [{"when": [], "points": [[rational(value), [1, 1]]]}]}


def declaration(actions=("a",), *, kernels=None, observed=True,
                initial=(F(1, 2), F(1, 2)), confirmations=False):
    actions = list(actions)
    kernels = kernels or {a: FAIR for a in actions}
    return {
        "scheme": "sui.model.8", "states": ["0", "1"], "outcomes": ["0", "1"],
        "actions": actions, "a": {a: table(I if observed else C) for a in actions},
        "learnable": [], "D": [rational(x) for x in initial], "log_C": [0., 0.], "gamma": 1.,
        "work": {a: {"kind": "known", "points": [[NS, [1, 1]]]} for a in actions},
        "completion": {"name": "progress", "version": "1", "actions": actions,
            "states": ["0", "1"], "work_unit": "ns", "time_unit": "ns", "speed_unit": "ns/ns",
            "candidates": [[[rational(1), rational(1)] for _ in actions]], "weights": [[1, 1]],
            "share": "all_actions", "max_speed": [1, 1]},
        "clock": {"kind": "clock-process", "version": "1", "share": "run", "candidates": [
            {"weight": [1, 1], "kind": "exact", "width_ns": None, "phase_ns": None}]},
        "activity": {"modes": ["idle"], "initial_given_state": [[[1, 1], [1, 1]]],
            "Q_by_mode": {"idle": [[0., 0.], [0., 0.]]}, "calendar": []},
        "effects": {a: {"family": {"name": "start-impulse", "version": "2"},
            "B": {"kind": "known", "values": table(kernels[a])}, "marks": None, "notice": None,
            "measure": {"at": "report", "side": "post"}, "mode_on_dispatch": {"idle": "idle"},
            "mode_on_completion": {"idle": "idle"}, "response_rate_s": None,
            "progress_start": "dispatch"} for a in actions},
        "execution": {"family": {"name": "wait-dispatch", "version": "1"},
            "late": "send_when_ready", "think": delay(), "receipt": delay(),
            "chi": {"share": "all_actions", "candidates": [{"weight": [1, 1], "delay": delay()}]},
            "confirmations": {k: delay() if confirmations else None
                              for k in ("reservation", "receipt", "dispatch")}},
        "choices": {a: {"action": a, "reservation": {"kind": "at", "not_before_ns": 0}}
                    for a in actions}, "arrivals": {}}


def contract_variants():
    """Valid declarations cover all explicitly encoded Spec variants and keys.

    Validation success is not a claim that evaluation supports these models.
    """
    base = declaration(confirmations=True)
    result = {"known_exact_wait": base}
    d = deepcopy(base)
    d["work"]["a"] = {"kind": "dp", "alpha": [2, 1], "base": {
        "name": "atoms", "version": "1", "params": {"points": [[NS, [1, 2]], [None, [1, 2]]]}}}
    result["dp_atoms"] = d
    d = deepcopy(base)
    d["work"]["a"] = {"kind": "dp", "alpha": [2, 1], "base": {
        "name": "piecewise", "version": "1", "params": {
            "edges_ns": [0, NS, 2*NS], "masses": [[1, 4], [1, 4]],
            "tail": {"kind": "pareto", "kappa": [2, 1], "mass": [1, 4]}, "p_inf": [1, 4]}}}
    result["dp_piecewise"] = d
    for phase in ([0, 1], "uniform"):
        d = deepcopy(base)
        d["clock"]["candidates"][0].update(kind="tick", width_ns=NS, phase_ns=phase)
        result["clock_tick_" + str(phase)] = d
    for name, params in (("exact", {}), ("tick", {"width_ns": NS,
            "phase": {"point_ns": 0}, "check": "uniform_in_tick"}),
            ("tick", {"width_ns": NS, "phase": "uniform", "check": "uniform_in_tick"})):
        d = deepcopy(base)
        d["clock"] = {"kind": "legacy-measure", "measure": {"share": "all_actions",
            "candidates": [{"name": name, "version": "1", "params": params, "weight": [1, 1]}]}}
        d["execution"] = {"family": {"name": "immediate-start", "version": "1"},
            "late": None, "think": None, "receipt": None, "chi": None,
            "confirmations": {k: None for k in ("reservation", "receipt", "dispatch")}}
        d["choices"]["a"]["reservation"] = {"kind": "immediate"}
        result["legacy_" + name + str(params.get("phase", ""))] = d
    for rule in ({"kind": "next", "step_ns": 1}, {"kind": "offset", "offset_ns": NS}):
        d = deepcopy(base)
        d["choices"]["a"]["reservation"] = rule
        result[rule["kind"]] = d
    d = deepcopy(base)
    effect = d["effects"]["a"]
    effect["B"] = {"kind": "dirichlet", "values": table([[1, 2], [3, 4]])}
    effect["marks"] = {"labels": ["e"], "probability": [table([[1, 1], [1, 1]])]}
    effect["notice"] = {"labels": ["y"], "probability": [[table([[1, 1], [1, 1]])]]}
    d["learnable"] = ["a"]
    d["a"]["a"] = table([[1, 2], [3, 4]])
    d["execution"]["receipt"] = {"given": ["state", "mode", "rho", "lambda"],
        "rows": [{"when": [s, "idle", 0, 0], "points": [[[0, 1], [1, 2]], ["+inf", [1, 2]]]}
                 for s in ("0", "1")]}
    d["activity"]["calendar"] = [{"at_s": [1, 2], "mode": "idle"}]
    d["arrivals"] = {"route": {"alpha": 2., "beta_s": 1.}}
    result["learned_marks_conditional_delays"] = d
    d = deepcopy(base)
    d["effects"]["a"].update(family={"name": "response-wait", "version": "1"},
        response_rate_s=[1., 2.], progress_start="response")
    result["response_wait"] = d
    return result


def object_paths(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from object_paths(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from object_paths(child, path + (index,))


def at_path(value, path):
    for key in path:
        value = value[key]
    return value


def budget():
    return api("action_types").ActionBudget(tolerance=1e-9, node_budget=20000,
        series_budget=2000, refinement_budget=5, envelope_budget=20000)


def load_model(d):
    return api("action_model").action_model_from_json(encoded(d))


def rig(d, *, H=NS):
    from test_lookahead import _rig
    return _rig(model=load_model(d), H=H, gamma=1., items=())


def view_of(r):
    return r.agent.view(now_ns=0, observed_ns=0,
        check_events=({"fact": str(r.h.records[0].id)},))


def root_case(d, *, H=NS):
    types, entry = api("action_types"), api("action_entry")
    r = rig(d, H=H)
    view = view_of(r)
    from sui.preference import current, resolve
    support = entry.certify_action_scope(view, tuple(sorted(d["choices"])),
                                        resolve(current(view.preferences), view), budget=budget())
    assert support.status == "certified", support
    context = types.ActionTimeContext(run=r.clock.run, now_ns=0, observed_ns=0,
        check_events=view.check_events, fact_ancestors=view.fact_ancestors, clock_source=None)
    belief = entry.rebuild_action_belief(r.model, view.reading, context=context, budget=budget())
    node = types.ActionNode(belief=belief, controls=(), targets=(), terminal=False, trigger=None)
    return r, belief, node, support


def command(r, choice, *, reading_ns=0, stage=0, position=0):
    t = api("action_types")
    decision = t.DecisionReading(run=r.clock.run, reading_ns=reading_ns,
                                work="spec-fixture", parents=frozenset(r.agent.frontier))
    return api("dispatch").build_command(model=r.model, choice=choice, decision=decision,
        causal_stage=stage, causal_position=position)


def fixed(identifier, key):
    data = json.loads(Path(__file__).with_name("fixed_s4b_action.json").read_bytes())
    return data["items"][identifier]["values"][key]


def assert_bounds(box, expected, *, exact=False, width=1e-9):
    """Spec §7 excludes floating rounding; 4e-14 only for float reference comparison."""
    if exact:
        assert box.exact == F(expected)
    value = float(expected)
    assert box.lower - 4e-14 <= value <= box.upper + 4e-14
    assert box.lower <= box.upper
    assert box.upper - box.lower <= width


def distribution(marginal):
    assert len({cell for cell, _ in marginal.cells}) == len(marginal.cells)
    return dict(marginal.cells)


def assert_distribution(marginal, expected, *, exact=True):
    cells = distribution(marginal)
    assert set(expected) <= set(cells)
    for key, box in cells.items():
        assert_bounds(box, expected.get(key, F(0)), exact=exact)


def outcome_of(atom):
    rows = [record.body.content.as_json() for record in atom.records
            if getattr(record.body, "contract", None) is not None
            and record.body.contract.name == "sui.s4b.action_report"]
    assert len(rows) == 1
    return rows[0]["outcome"]
