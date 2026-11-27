"""K41-f. Numerical and ordering consequences visible at the host boundary."""

from dataclasses import replace
from fractions import Fraction as Q

import pytest

from sui import fb, fb_contracts as c
from k41_world import (
    FAIR, HALF, ONE, ONE_WAY, ORIGIN, X, ZERO, adopt, at_entry, call, complement,
    entropy, generator, minus, rat, scaled, worlds,
)
from test_fb_cycle import E, T, U, WATCHDOG
from test_fb_pool import public_rounds
from test_fb_time_belief import assert_contains, script, time_fact_at, time_finish_activity


@pytest.mark.parametrize("read_b", [Q(1), HALF], ids=["perfect", "one-half"])
def test_called_failure_keeps_the_step_inside_the_acquisition(worlds, read_b):
    p = Q(1, 4)
    r = worlds(script((0, 2, U)), failure=p, start_ns=ORIGIN, thinking=True,
               measurement=at_entry(), sensor=(0, read_b)).start()
    pick = r.think()
    r.run("measure_segment", background=True)
    assert r.passive.gates[0].entered.wait(WATCHDOG)
    r.clock.set(ORIGIN+1)
    r.enter_step(selection=pick.cid)
    r.finish_step(0, T)
    r.sense(0, U)
    r.exercise_available_updates()
    r.until(lambda: len(r.expression().observations) == 2)
    frame, = r.frame_reports()
    reading = frame.value["item"]["value"]
    span = reading["measurement_interval"]
    assert (span["start_ns"], span["end_ns"]) == (ORIGIN, ORIGIN+2)
    assert reading["value"]["value"]["source_called"] is True
    assert reading["value"]["value"]["result"]["kind"] == "unavailable"
    assert r.actor.entered_ns == [ORIGIN+1] and r.passive.calls == [0]
    assert r.expression().terminal_ns == ORIGIN+2
    # T proves B at entry. A second application of the noisy sensor would
    # multiply the evidence by read_b again, even though B is absorbing.
    assert_contains(r.query("mass"), scaled(p*read_b, complement(X)))
    a = r.query("state", state="A")
    assert a.lower == a.upper == 0


@pytest.mark.parametrize("delay", [0, 1], ids=["origin", "one-unit-later"])
def test_first_evaluation_predicts_from_the_declared_origin(worlds, delay):
    r = worlds(thinking=True, start_ns=ORIGIN+delay, rates=(0, 0), measurement=at_entry()).start()
    assert not r.facts(c.BELIEF_ADOPTED)
    selected = r.think()
    row, = [x for x in r.host.window.status().evaluations if x.outcome == "selected"]
    context = time_fact_at(r, row.context)
    judgment = time_fact_at(r, context.value["judgment_reading"])
    assert judgment.value["reading"]["time_ns"] == ORIGIN+delay
    answer = r.selected_value(selected).evaluation
    i = answer.candidates.index("peek")
    expected = entropy(X) if delay else rat(0)
    for v, reference in ((answer.information[i].additional.bounds, expected),
                         (answer.G[i].bounds, minus(rat(0), expected))):
        assert v.upper-v.lower <= Q(1, 512)
        assert_contains(v, reference)
    assert not r.facts(c.BELIEF_ADOPTED) and not r.passive.calls and not r.actor.calls


@pytest.mark.parametrize("defect,field", [
    ("valid", None), ("missing", "measurement"), ("at-finish", "measurement"),
    ("no-basis", "time_basis"),
])
def test_reading_shortfall_stops_comparison_before_any_selection(worlds, defect, field):
    reading = at_entry()
    if defect == "missing":
        reading.pop("measurement")
    elif defect == "at-finish":
        reading["measurement"] = call("finish_observation", {})
    elif defect == "no-basis":
        reading["time_basis"] = None
    r = worlds(thinking=True, measurement=reading)
    if field is None:
        r.start()
        pick = r.think()
        assert {s.cid for s in r.facts(c.SELECTION)} == {pick.cid}
        assert set(r.selected_value(pick).evaluation.candidates) == {"peek", "wait"}
        return
    try:
        r.start()
        public_rounds(r, run_generation=True)
        status = r.host.window.status()
        details = [str(x.residual) for x in status.evaluations]
        details += [str((x.reason, x.target)) for x in status.pending]
        if not any("peek" in d and field in d for d in details):
            terminal = time_finish_activity(r)
            details.append(str(terminal.residual))
    except (fb.StartInputError, fb.TimeBeliefError) as exc:
        details = [str(tuple(getattr(exc, k, None) for k in ("reason", "field", "targets")))]
    assert any("peek" in d and field in d for d in details), details
    assert not r.draw_calls and not r.facts(c.SELECTION) and not r.actor.calls


def test_zero_generator_requires_role_while_omission_accepts_the_same_law(worlds):
    options = dict(state_role=None, family=None, prior=FAIR, rates=(0, 0))
    omitted = worlds(process=None, **options).start()
    adopt(omitted)
    assert_contains(omitted.query("mass"), ONE)
    assert_contains(omitted.query("state", state="A"), rat(HALF))
    explicit = worlds(process=ZERO, **options)
    with pytest.raises(fb.TimeBeliefError) as caught:
        explicit.start()
        explicit.resolved(explicit.boot())
    assert caught.value.kind == "unsupported"
    assert "state_role" in (*caught.value.targets, caught.value.field)


@pytest.mark.parametrize("overlap", ["undeclared", "state_preserving"])
def test_step_entered_before_candidate_addition_keeps_its_ordering_status(worlds, overlap):
    r = worlds(script((0, 0, E), (0, 2, E)), process=None, rates=(0, 0),
               prior=FAIR, thinking=True, start_ns=ORIGIN, measurement=at_entry())
    decl = r.boot_input.declaration
    execution = decl.execution
    r.boot_input = replace(r.boot_input, declaration=replace(decl, execution=replace(execution,
        value=replace(execution.value, source_overlap=overlap, actor_overlap=overlap))))
    r.start()
    first = adopt(r)
    assert r.passive.gates[1].entered.wait(WATCHDOG)
    r.clock.set(ORIGIN+1)
    selected = r.think()
    _, entered = r.enter_step(selection=selected.cid)
    added = r.add_law(replace(r.law(), state_process=generator(ONE_WAY)))
    rebuilt = r.update()
    assert rebuilt.observations == first.observations and r.pool().point == added.pool
    assert entered.model != r.pool().model
    before = {x.cid for x in r.facts(c.BELIEF_ADOPTED)}
    r.sense(1, E)
    frames = [x.value["item"]["value"]["measurement_interval"] for x in r.frame_reports()]
    frame, = [span for span in frames if span["end_ns"] == ORIGIN+2]
    assert frame["start_ns"] < r.actor.entered_ns[0] < frame["end_ns"]
    assert not r.actor.returned_ns
    r.exercise_available_updates()
    if overlap == "undeclared":
        assert {x.cid for x in r.facts(c.BELIEF_ADOPTED)} == before
    else:
        r.until(lambda: len(r.expression().observations) == 2)
    r.finish_step(0, T)
    assert len(r.actor.calls) == 1 and r.passive.calls == [0, 0]
    if overlap == "undeclared":
        r.until(lambda: any(x.execution == entered and x.reason == "observation_order_unknown"
                            for x in r.host.window.status().executions))
        assert {x.cid for x in r.facts(c.BELIEF_ADOPTED)} == before
    else:
        r.exercise_available_updates()
        r.until(lambda: len(r.expression().observations) == 3)
