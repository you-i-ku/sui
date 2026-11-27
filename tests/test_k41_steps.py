"""K41 decisions 3, 6 and 7. Native records for acquisition, decision and entry."""
from copy import deepcopy
from fractions import Fraction as Q

import pytest

from sui import fb, fb_contracts as c, f_update2 as u2
from test_fb_belief import belief1_clone
from test_fb_cycle import E, T, WATCHDOG, wire
from test_fb_pool import public_rounds
from test_fb_time_belief import assert_contains, script, time_direct_update, time_fact_at, time_finish_activity
from k41_world import (
    FAIR, HALF, INDEPENDENT, ONE, ORIGIN, RECORDED, X, adopt, at_entry, call, complement,
    divide, entropy, expneg, logarithm, minus, plus, rat, refined, scaled, selection, times, worlds,
)


def replay(r, expr):
    saved = time_fact_at(r, expr.result)
    request = time_fact_at(r, saved.value["request"])
    issued = time_direct_update(r, request)
    assert isinstance(issued, u2.IssuedUpdate)
    assert wire(issued.result) == saved.value["result"]
    assert issued.application_digest == saved.value["application_digest"]
    return request


def project_saved_step(r, request, *, remove_basis):
    # Each test-only reference must point to the same alternate declaration.
    # The two snapshots retain the actor's actual raw times, result and kernel.
    use, = request.value["desc"]["args"]["observations"]
    reading = time_fact_at(r, use["reading"])
    args = reading.value["projection"]["args"]
    declaration = time_fact_at(r, args["execution_declaration"])
    alternative = deepcopy(declaration.value)
    if remove_basis:
        alternative["value"]["source_readings"]["peek"]["time_basis"] = None
    points = {declaration.cid: belief1_clone(r, declaration, alternative)}

    def rebind(value):
        if isinstance(value, list):
            return [rebind(item) for item in value]
        if isinstance(value, dict):
            return {key: rebind(item) for key, item in value.items()}
        return points.get(value, value)

    for fact in (reading, time_fact_at(r, use["binding"])):
        points[fact.cid] = belief1_clone(r, fact, rebind(fact.value),
            parents=tuple(rebind(p) for p in fact.parents))
    q = rebind(request.value)
    q["desc"]["input_points"] = sorted(q["desc"]["input_points"])
    view = q["desc"]["numerical_view"]
    view["boundary"] = sorted(set(view["boundary"]).union(points.values()))
    return time_direct_update(r, request, q)


def test_static_step_record_replay_control(worlds):
    r = worlds(process=None, prior=FAIR, thinking=True, start_ns=ORIGIN).start()
    pick = r.think()
    r.enter_step(selection=pick.cid)
    r.finish_step(0, T)
    expr = r.update()
    assert_contains(r.query("state", state="B"), ONE)
    request = replay(r, expr)
    assert isinstance(project_saved_step(r, request, remove_basis=False), u2.IssuedUpdate)


def test_native_policy_adopts_once_then_reads_next_record_and_rebuilds(worlds):
    r = worlds(script((1, 1, E), (1, 2, E)), thinking=True, measurement=at_entry()).start()
    first = adopt(r)
    chosen = r.think()
    selection(r, chosen, first, logarithm(rat(2)), rat(Q(2, 3)))
    _, action = r.enter_step(selection=chosen.cid)
    assert action.action.id == "peek"
    r.finish_step(0, T)
    step = r.update()
    assert_contains(r.query("state", state="B"), ONE)
    assert_contains(r.query("mass"), X)
    selection(r, r.think(), step, rat(0), rat(HALF))
    last = adopt(r, 1)
    # Given B and zero count at 1, the next empty likelihood is int_0^1 exp(-u) du.
    z = times(X, complement(X))
    assert_contains(r.query("mass"), z)
    assert_contains(r.query("count", count=0), divide(X, complement(X)))
    assert_contains(r.query("state", state="B"), ONE)
    selection(r, r.think(), last, rat(0), rat(HALF))
    assert len({first.root, step.root, last.root}) == 3
    assert len(set(last.observations)) == len(last.observations) == 3
    assert r.passive.calls == [0, 0] and len(r.actor.calls) == 1
    replay(r, last)
    value = r.query("mass")
    r.host.rebuild_window()
    rebuilt = r.expression()
    assert rebuilt.root == last.root and rebuilt.observations == last.observations
    assert r.host.same_belief(left=last, right=rebuilt)
    assert r.host.verify_belief_value(belief=rebuilt, value=value)
    selection(r, chosen, first, logarithm(rat(2)), rat(Q(2, 3)))
    assert len(r.actor.calls) == 1


@pytest.mark.parametrize("moving", [False, True], ids=["static-footing", "moves"])
def test_judgment_predicts_without_changing_adoption_and_entry_uses_actual_time(worlds, moving):
    options = {"measurement": at_entry()} if moving else {"process": None}
    r = worlds(thinking=True, **options).start()
    first = adopt(r)
    assert first.terminal_ns == ORIGIN+1
    r.clock.set(ORIGIN+2)
    chosen = r.think()
    activity, = [row for row in r.host.window.status().evaluations if row.outcome == "selected"]
    context = time_fact_at(r, activity.context)
    judgment = time_fact_at(r, context.value["judgment_reading"])
    assert judgment.value["reading"]["time_ns"] == ORIGIN+2
    # P(A at j)=exp(-1)/2 after the first point empty. No intervening empty record.
    info = entropy(scaled(HALF, X)) if moving else rat(0)
    selection(r, chosen, first, info)
    assert r.expression().root == first.root and r.expression().terminal_ns == ORIGIN+1
    assert_contains(r.query("state", state="A"), rat(HALF) if moving else ONE)
    r.clock.set(ORIGIN+3)
    r.enter_step(selection=chosen.cid)
    r.clock.set(ORIGIN+4)
    r.finish_step(0, E)  # Saw A at entered, after which A can still change.
    step = r.update()
    assert r.actor.entered_ns == [ORIGIN+3] and r.actor.returned_ns == [ORIGIN+4]
    assert step.terminal_ns == ORIGIN+4
    assert_contains(r.query("mass"), expneg(3) if moving else ONE)
    assert_contains(r.query("state", state="A"), X if moving else ONE)
    replay(r, step)
    selection(r, chosen, first, info)


@pytest.mark.parametrize("span", [False, True], ids=["point", "entered-inside-acquisition"])
@pytest.mark.parametrize("moving", [False, True], ids=["static-footing", "moves"])
def test_entry_inside_source_history_counts_both_observations_once(worlds, span, moving):
    setup = {"measurement": at_entry()} if moving else {"process": None, "prior": (Q(0), Q(1))}
    r = worlds(script((0 if span else 2, 2, E)), thinking=True, unit=HALF,
               start_ns=ORIGIN, **setup).start()
    chosen = r.think()
    if span:
        r.run("measure_segment", background=True)
        assert r.passive.gates[0].entered.wait(WATCHDOG)
    r.clock.set(ORIGIN+1)
    r.enter_step(selection=chosen.cid)
    r.finish_step(0, T)
    if span:
        r.sense(0, E)
    else:
        r.update()
        r.clock.set(ORIGIN+2)
        r.observe(0)
    r.exercise_available_updates()
    r.until(lambda: len(r.expression().observations) == 2)
    assert r.actor.entered_ns == [ORIGIN+1] and r.passive.calls == [0]
    assert r.expression().terminal_ns == ORIGIN+2
    no_arrivals = scaled(HALF, X) if moving else X
    z = no_arrivals
    if span:
        # Integrate x+1-exp(x-1) against exp(-x) dx for 0<=x<=1/2,
        # the first jump x when S(1/2)=B. U may lie on either side of the step.
        z = (minus(minus(rat(2), scaled(Q(5, 2), expneg(HALF))), scaled(HALF, X))
             if moving else complement(X))
    refined(lambda tol: r.query("mass", tolerance=tol), z)
    assert_contains(r.query("state", state="B"), ONE)
    assert_contains(r.query("count", count=0), divide(no_arrivals, z) if span else ONE)


def bit_record(mode):
    """Enumerate the toy world's joint raw outcomes. Y=0 uses the taken cell."""
    records = {}
    for s in (0, 1):
        for u in (0, 1):
            for tick in range(4):
                d = tick % 2
                if mode == "state-delay":
                    d = int(tick >= (3 if s == 0 else 1))
                    y = 0
                else:
                    y = s ^ (d if mode == "shared" else u)
                key = (s, d, y)
                records[key] = records.get(key, Q(0)) + Q(1, 16)
    return records


@pytest.mark.parametrize("mode,p_a", [("shared", Q(1)), ("independent", HALF), ("state-delay", Q(3, 4))])
def test_raw_timing_rulers_enumerate_joint_not_marginals(mode, p_a):
    rows = bit_record(mode)
    a = rows.get((0, 0, 0), 0)
    b = rows.get((1, 0, 0), 0)
    assert a/(a+b) == p_a
    assert sum(rows.values()) == 1


def named_stop(r, condition):
    """Drive native workers to a reported shortage; inspect only diagnostic fields."""
    def diagnostics():
        st = r.host.window.status()
        groups = [x.residual for x in st.evaluations]
        groups += [(x.reason, x.target) for x in st.pending if x.reason]
        groups += [(x.reason, x.execution.u) for x in st.executions if x.reason]
        groups += [x.reasons for x in st.updates]
        return [" ".join(str(v) for v in group if v is not None) for group in groups]

    def names(items):
        terms = ("elapsed_ns", "duration", "所要") if condition == "elapsed" else (condition,)
        return any("peek" in item and any(term in item for term in terms) for item in items)

    try:
        r.start()
        public_rounds(r)
        if not names(diagnostics()):
            terminal = time_finish_activity(r)
            if terminal.outcome == "selected":
                pick, = r.facts(c.SELECTION)
                args = r.selected_value(pick)
                assert args.choice.id == "peek", "unsupported peek was silently removed"
                r.run("execute_step", background=True)
                r.until(lambda: names(diagnostics()) or bool(r.actor.calls))
            assert names(diagnostics()), diagnostics()
    except (fb.TimeBeliefError, fb.StartInputError) as error:
        assert names([str(tuple(getattr(error, key, "") for key in ("targets", "field", "reason")))])
    assert not r.actor.calls and not r.facts(c.BELIEF_ADOPTED)
    picks = r.facts(c.SELECTION)
    assert len(picks) <= 1
    assert all(r.selected_value(pick).choice.id == "peek" for pick in picks)


@pytest.mark.parametrize("mode", ["shared", "independent", "state-delay"])
def test_step_time_factor_requires_the_joint_record_and_accepts_independent_noise(worlds, mode):
    # Both timestamps are fixed in this observed draw: D=0, Y=0. The full law is
    # specified by bit_record, not a joint-delay model supplied to production.
    sensor = (Q(1), Q(1)) if mode == "state-delay" else FAIR
    basis = INDEPENDENT if mode == "independent" else None
    r = worlds(prior=FAIR, rates=(0, 0), thinking=True, start_ns=ORIGIN, sensor=sensor,
               measurement=at_entry(basis))
    if basis is None:
        named_stop(r, "time_basis")
        return
    r.start()
    chosen = r.think()
    r.enter_step(selection=chosen.cid)
    r.finish_step(0, T)
    expr = r.update()
    assert r.actor.entered_ns == r.actor.returned_ns == [ORIGIN]
    assert len(expr.observations) == len(r.actor.calls) == 1
    assert_contains(r.query("state", state="A"), rat(HALF))
    replay(r, expr)


@pytest.mark.parametrize("mode", ["shared", "state-delay"])
def test_saved_raw_step_without_time_factor_is_named_at_update(worlds, mode):
    # The same D=0,Y=0 record is possible in both worlds. The unsupported
    # world can supply the same marginal E_y, but cannot supply the certificate.
    sensor = FAIR if mode == "shared" else (Q(1), Q(1))
    r = worlds(prior=FAIR, rates=(0, 0), thinking=True, start_ns=ORIGIN, sensor=sensor,
               measurement=at_entry(INDEPENDENT)).start()
    pick = r.think()
    r.enter_step(selection=pick.cid)
    r.finish_step(0, T)
    expr = r.update()
    assert r.actor.entered_ns == r.actor.returned_ns == [ORIGIN]
    request = replay(r, expr)
    allowed = project_saved_step(r, request, remove_basis=False)
    assert isinstance(allowed, u2.IssuedUpdate)
    assert_contains(r.query("state", state="A"), rat(HALF))
    try:
        refused = project_saved_step(r, request, remove_basis=True)
    except (fb.TimeBeliefError, u2.UpdateEntranceError) as error:
        detail = str((error.reason, getattr(error, "field", None), getattr(error, "targets", ())))
    else:
        assert isinstance(refused, u2.Rejected)
        detail = str(wire(refused.issues))
    assert "peek" in detail and "time_basis" in detail
    assert r.expression().root == expr.root and len(r.actor.calls) == 1


@pytest.mark.parametrize("invariant", [True, False])
def test_unspecified_read_instant_requires_invariance_on_reachable_edges(worlds, invariant):
    r = worlds(rates=(0, 0), thinking=True, start_ns=ORIGIN, sensor=FAIR if invariant else (0, 1),
               measurement={"time_basis": call(RECORDED, {})})
    if not invariant:
        named_stop(r, "measurement")
        return
    r.start()
    chosen = r.think()
    r.clock.set(ORIGIN+1)
    r.enter_step(selection=chosen.cid)
    r.finish_step(0, T)
    r.update()
    assert_contains(r.query("state", state="A"), X)
    assert_contains(r.query("mass"), rat(HALF))


@pytest.mark.parametrize("defect", ["duration", "read-at-finish", "count-dependent", "consumes"])
def test_outside_step_measurement_is_named_before_actor_call(worlds, defect):
    options = at_entry()
    condition = "measurement"
    if defect == "read-at-finish":
        options["measurement"] = call("finish_observation", {})
    elif defect == "count-dependent":
        condition = "independent_of_count"
        options[condition] = False
    elif defect == "consumes":
        condition = "count_shift"
        options[condition] = -1
    r = worlds(thinking=True, measurement=options)
    if defect == "duration":
        doc = deepcopy(r.document)
        peek, = [k for k in doc["kernels"] if k["id"] == "peek"]
        for outcome in peek["outcomes"]:
            outcome["elapsed_ns"] = 1
        r.replace_model(doc)
        condition = "elapsed"
    named_stop(r, condition)


@pytest.mark.parametrize("return_rate", [Q(0), Q(1, 2**12)], ids=["absorbing", "can-return"])
def test_support_follows_the_observation_sequence_to_the_known_point(worlds, return_rate):
    # A uniform acquisition in [0,1] found an item. The point sensor then sees
    # A at 1. Without a positive B->A edge the two observations cannot coexist.
    r = worlds(script((0, 1, T)), thinking=True, process=((-1, 1), (return_rate, -return_rate)),
               measurement=at_entry()).start()
    first = adopt(r)
    selected = r.think()
    _, execution = r.enter_step(selection=selected.cid)
    r.finish_step(0, E)
    assert r.actor.entered_ns == r.actor.returned_ns == [ORIGIN+1]
    if return_rate:
        second = r.update()
        assert len(second.observations) == 2
        assert r.query("mass", tolerance=Q(1, 2**40)).lower > 0
        assert_contains(r.query("state", state="A"), ONE)
        assert_contains(r.query("count", count=1, at_least=True), ONE)
    else:
        request, _ = r.offered("belief_update")
        rejected = time_direct_update(r, request)
        assert isinstance(rejected, u2.Rejected)
        assert "model_falsified" in {issue.code for issue in rejected.issues}
        r.run_request(request)
        r.until(lambda: any(row.execution == execution and row.outcome == "model_zero"
                            for row in r.host.window.status().executions))
        assert [fact.cid for fact in r.facts(c.BELIEF_ADOPTED)] == [first.adoption]
