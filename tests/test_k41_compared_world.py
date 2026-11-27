"""K41-i through K41-k. Exercise the compared world and its belief through the birth entry."""

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q

import pytest

from gate_f_facts_cases import diagonal, execute, outcome, plain
from k41_world import (
    BOTH, FAIR, ONE, ONE_WAY, ORIGIN, adopt, at_entry, expneg, minus, rat, scaled, worlds,
)
from sui import fb_contracts as c
from test_fb_cycle import E, T, next_cell_document
from test_fb_time_belief import assert_contains, logarithm, script
from test_k41_pool_time import boot_shortage
from test_k41_propagation import spectral_bounds


@pytest.mark.parametrize("position", ["first", "continuation"])
@pytest.mark.parametrize("process,elapsed", [(ONE_WAY, 1), (ONE_WAY, 0), (None, 1)],
                         ids=["moving-duration", "moving-instant", "static-duration"])
def test_compared_policy_checks_duration_without_an_external_actor(worlds, position, process, elapsed):
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, process=process, measurement=at_entry())
    doc = deepcopy(r.document)
    # Both outcomes have positive mass in every state. Their names are local
    # to the finite policy. No execution actor, reading or no_effect is declared for pause.
    pause = {"id": "pause", "outcomes": [outcome(name, diagonal(FAIR), elapsed=elapsed)
                                         for name in ("left", "right")]}
    doc["kernels"].append(pause)
    policy = next(p for p in doc["policies"] if p["id"] == "wait")
    run = execute("pause-node", "pause", ("left", "right"), "end")
    if position == "first":
        operation = next(op for op in doc["operations"] if op["id"] == "wait")
        operation["prediction"]["args"]["id"] = "pause"
        policy["nodes"][0] = run
        policy["entry"] = run["id"]
    else:
        policy["nodes"][0]["next"]["done"] = run["id"]
        policy["nodes"].insert(1, run)
    r.replace_model(doc)
    execution = r.boot_input.declaration.execution.value
    assert all("pause" not in field for field in (execution.actors, execution.source_readings,
                                                   execution.cells, execution.no_effect))
    if process is not None and elapsed:
        boot_shortage(r, "pause", "elapsed_ns")
    else:
        r.start()
        pick = r.think()
        assert set(r.selected_value(pick).evaluation.candidates) == {"peek", "wait"}
        assert [s.cid for s in r.facts(c.SELECTION)] == [pick.cid]


@pytest.mark.parametrize("end", [1, 8], ids=["ruler-one", "longer-interval"])
def test_uniform_empty_enclosure_includes_the_positive_poisson_tail(worlds, end):
    r = worlds(script((0, end, E)), process=ONE_WAY, rates=(0, 1), family=None).start()
    belief = adopt(r)
    # P(N(u)=0)=(1+u)exp(-u). Average this over the uniform read time.
    # With nu=1 the embedded chain is A0 -> B0 -> B+ -> B+. For any n>=1,
    # exactly two of the n+1 possible read positions still give empty.
    # Thus *every* finite truncation leaves positive mass above its partial sum.
    z = scaled(Q(1, end), minus(rat(2), scaled(end+2, expneg(end))))
    value = r.query("mass", expression=belief, tolerance=Q(1, 8))
    assert_contains(value, z)


def test_coarse_point_empty_enclosure_includes_the_spectral_ruler(worlds):
    r = worlds(script((1, 1, E)), process=BOTH, rates=(0, 2), family=None).start()
    value = r.query("mass", expression=adopt(r), tolerance=Q(1, 8))
    # Independent positive series for exp(-2)(cosh(sqrt(2))+sqrt(2)sinh(sqrt(2))).
    for terms in (24, 48, 96, 192):
        lo, hi = spectral_bounds(terms)
        if value.lower <= lo <= hi <= value.upper:
            return
        assert value.lower <= hi and lo <= value.upper, "closed form outside the reported interval"
    pytest.fail("could not separate the reference from the query endpoints")


@pytest.mark.parametrize("span", [False, True], ids=["point-empty", "uniform-empty"])
def test_arrival_then_transition_after_the_count_read_reaches_the_only_joint_cell(worlds, span):
    # A -> B has rate 1, arrivals have rate 1 in A only, and B is absorbing.
    # A point empty at the end leaves no time for even one subsequent arrival.
    first = (0 if span else 1, 1, E)
    plan = script(first, (1, 1, T), (1, 1, E)) if span else script(first)
    r = worlds(plan, process=ONE_WAY, rates=(1, 0), family=None, thinking=True,
               measurement=at_entry()).start()
    initial = adopt(r)
    cell = r.query("count", expression=initial, state="B", count=1, tolerance=Q(1, 512))
    if not span:
        assert cell.lower == cell.upper == 0
        return
    assert cell.lower > 0
    # At the same endpoint, taken at cursor 0 then empty at cursor 1 pins N=1.
    # A perfect step at entry pins S=B. Only (B,1) can explain the full history.
    adopt(r, 1)
    adopt(r, 2)
    pick = r.think()
    _, step = r.enter_step(selection=pick.cid)
    assert step.action.id == "peek"
    r.finish_step(0, T)
    final = r.update()
    assert r.actor.entered_ns == r.actor.returned_ns == [ORIGIN+1]
    assert r.passive.calls == [0, 0, 1] and len(final.observations) == 4
    mass = r.query("mass", expression=final, tolerance=Q(1, 512))
    assert mass.lower > 0
    # For read time u and jump time v, u<v<1: exactly one arrival in (u,v)
    # and none before u has probability (v-u)exp(-v). The jump density is exp(-v).
    # Integrating in u, then v, gives (1-5exp(-2))/8.
    assert_contains(mass, scaled(Q(1, 8), minus(ONE, scaled(5, expneg(2)))))
    assert_contains(r.query("count", expression=final, state="B", count=1), ONE)


def comparison_only_peek(worlds, process, outcomes, *, targets=("A", "B")):
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, process=process, targets=targets)
    doc = deepcopy(r.document)
    peek = next(k for k in doc["kernels"] if k["id"] == "peek")
    peek["outcomes"] = outcomes
    policy = next(p for p in doc["policies"] if p["id"] == "peek")
    policy["nodes"][0]["next"] = {item["id"]: "end" for item in outcomes}
    r.replace_model(doc)
    decl = r.boot_input.declaration
    slot = decl.execution
    execution = replace(slot.value, actors={}, source_readings={}, cells={})
    assert "peek" not in execution.no_effect
    r.boot_input = replace(r.boot_input, declaration=replace(decl, execution=replace(slot, value=execution)))
    return r


def compare_and_select(r):
    r.start()
    pick = r.think()
    evaluation = r.selected_value(pick).evaluation
    assert set(evaluation.candidates) == {"peek", "wait"}
    assert [s.cid for s in r.facts(c.SELECTION)] == [pick.cid]
    assert not r.actor.calls
    return evaluation


@pytest.mark.parametrize("late_mass", [Q(0), Q(1, 2**40)], ids=["zero-matrix", "positive-mass"])
def test_only_possible_outcomes_constrain_compared_duration(worlds, late_mass):
    r = comparison_only_peek(worlds, ONE_WAY, [
        outcome("now", diagonal((1-late_mass, 1-late_mass)), elapsed=0),
        outcome("late", diagonal((late_mass, late_mass)), elapsed=1),
    ])
    if late_mass == 0:
        compare_and_select(r)
    else:
        boot_shortage(r, "peek", "elapsed_ns")


@pytest.mark.parametrize("process,t_in_b", [(ONE_WAY, Q(3, 4)), (ONE_WAY, Q(1, 4)), (None, Q(3, 4))],
                         ids=["moving-varies", "moving-invariant", "static-varies"])
def test_comparison_only_peek_needs_a_read_instant_if_its_evidence_varies(worlds, process, t_in_b):
    t_in_a = Q(1, 4)
    r = comparison_only_peek(worlds, process, [
        outcome("yes", diagonal((t_in_a, t_in_b)), value=T, elapsed=0),
        outcome("no", diagonal((1-t_in_a, 1-t_in_b)), value=E, elapsed=0),
    ])
    if process is not None and t_in_a != t_in_b:
        boot_shortage(r, "peek", "measurement_missing")
    else:
        compare_and_select(r)


@pytest.mark.parametrize("second_value", [T, E], ids=["same-evidence", "different-evidence"])
def test_compared_read_instant_uses_the_sum_for_each_evidence_value(worlds, second_value):
    # Each split row varies on A -> B. Grouped as T they give 1/2 in both
    # states. Changing only the second emission leaves P(T|A)=1/8, P(T|B)=3/8.
    r = comparison_only_peek(worlds, ONE_WAY, [
        outcome("first", diagonal((Q(1, 8), Q(3, 8))), value=T, elapsed=0),
        outcome("second", diagonal((Q(3, 8), Q(1, 8))), value=second_value, elapsed=0),
        outcome("other", diagonal(FAIR), value=E, elapsed=0),
    ])
    if second_value == T:
        evaluation = compare_and_select(r)
        info = evaluation.information[evaluation.candidates.index("peek")].additional
        assert_contains(info.bounds, rat(0))
    else:
        boot_shortage(r, "peek", "measurement_missing")


@pytest.mark.parametrize("process,swap,p_taken,shortfall", [
    pytest.param(ONE_WAY, True, (1, 0), "measurement_unsupported:matrix", id="moving-swap-reveals-state"),
    pytest.param(None, True, (1, 0), None, id="static-same-swap"),
    pytest.param(ONE_WAY, False, (1, 0), "measurement_missing", id="diagonal-reveals-state"),
    pytest.param(ONE_WAY, True, FAIR, "measurement_unsupported:matrix", id="moving-swap-fair"),
    pytest.param(ONE_WAY, False, FAIR, None, id="moving-diagonal-fair"),
])
def test_compared_kernel_checks_state_changes_within_one_target(worlds, process, swap, p_taken, shortfall):
    # Columns are starting states. Swapping the destination rows keeps every
    # outcome probability fixed. With (1,0) this yields the review's T and E.
    taken = diagonal(p_taken)
    empty = diagonal(tuple(1-p for p in p_taken))
    if swap:
        taken.reverse()
        empty.reverse()
    r = comparison_only_peek(worlds, process, [
        outcome("t", taken, value=T, elapsed=0),
        outcome("e", empty, value=E, elapsed=0),
    ], targets=("same", "same"))
    if shortfall is not None:
        boot_shortage(r, "peek", shortfall)
    else:
        compare_and_select(r)


@pytest.mark.parametrize("fine_invariant,entry_declared", [
    pytest.param(False, False, id="only-the-execution-cell-is-invariant"),
    pytest.param(True, False, id="each-evidence-slot-is-invariant"),
    pytest.param(False, True, id="read-at-entry"),
])
def test_external_peek_checks_evidence_slots_inside_one_execution_cell(worlds, fine_invariant, entry_declared):
    reading = at_entry()
    if not entry_declared:
        del reading["measurement"]  # Keep the declared basis for the actual timestamps.
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, process=ONE_WAY, measurement=reading)
    doc = next_cell_document(ambiguous=False)
    peek = next(k for k in doc["kernels"] if k["id"] == "peek")
    t0, t1 = (next(o for o in peek["outcomes"] if o["id"] == name) for name in ("t0", "t1"))
    assert (t0["evidence"]["slot"], t1["evidence"]["slot"]) == ("m0", "m1")
    if fine_invariant:
        for o in (t0, t1):
            o["matrix"] = plain(diagonal((Q(1, 4), Q(1, 4))))
    r.replace_model(doc)
    decl = r.boot_input.declaration
    slot = decl.execution
    cells = tuple(replace(cell, outcomes=("t0", "t1")) if cell.id == T else cell
                  for cell in slot.value.cells["peek"])
    taken, = [cell for cell in cells if cell.id == T]
    assert t0["evidence"]["value"] == t1["evidence"]["value"] == taken.observation.value
    execution = replace(slot.value, cells={**slot.value.cells, "peek": cells})
    r.boot_input = replace(r.boot_input, declaration=replace(decl, execution=replace(slot, value=execution)))

    if not fine_invariant and not entry_declared:
        boot_shortage(r, "peek", "measurement_missing")
        return
    evaluation = compare_and_select(r)
    info = evaluation.information[evaluation.candidates.index("peek")].additional
    # With the split state-dependent slots, m0 or m1 reveals the fair state
    # on half the trials. The actor's T cell combines both slots and has kernel I/2.
    expected = rat(0) if fine_invariant else scaled(Q(1, 2), logarithm(rat(2)))
    assert_contains(info.bounds, expected)
    selected, = r.facts(c.SELECTION)
    assert r.selected_value(selected).choice.id == "peek"
    r.enter_step(selection=selected.cid)
    r.finish_step(0, T)
    belief = r.update()
    assert r.actor.entered_ns == r.actor.returned_ns == [ORIGIN]
    assert len(belief.observations) == 1
    assert_contains(r.query("mass", expression=belief), rat(Q(1, 2)))
    assert_contains(r.query("state", state="A", expression=belief), rat(Q(1, 2)))
