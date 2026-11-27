"""K41-h. Check timed readings at the two public boundaries that form a pool."""

from copy import deepcopy
from dataclasses import replace

import pytest

from gate_f_facts_cases import Reader, diagonal
from k41_world import FAIR, HALF, ONE_WAY, ORIGIN, ZERO, at_entry, generator, worlds
from sui import f, f_facts as ff, fb, fb_contracts as c
from sui.contracts import ContractRef
from test_fb_cycle import ORDER
from test_fb_pool import NEW, public_rounds, snapshot_records
from test_fb_time_belief import time_finish_activity


def omit_empty_outcome(document):
    # Its probability was already zero. Keep the one-outcome model and its
    # policy normalized, while the common execution cells still name t and e.
    peek = next(k for k in document["kernels"] if k["id"] == "peek")
    peek["outcomes"] = [o for o in peek["outcomes"] if o["id"] == "t"]
    policy = next(p for p in document["policies"] if p["id"] == "peek")
    del policy["nodes"][0]["next"]["e"]


def candidate(r, name, *, sensor=(1, 1), moving=False, omit_empty=False):
    component = replace(NEW, name=name, prior=r.time_prior, taken=diagonal(sensor),
                        empty=diagonal(tuple(1-p for p in sensor)), unavailable=None)
    saved = r.save_candidate(component, edit_document=omit_empty_outcome if omit_empty else None)
    law = replace(r.law(), state_process=generator(ONE_WAY) if moving else None)
    observation = replace(r.boot_input.declaration.observation_models[0].value, law=law)
    return replace(saved, observation_model=observation)


def add(r, member):
    return r.host.add_candidate(boot=r.boot(), candidate=member, alpha=HALF)


def names_shortfall(reason, prefix, field):
    # K41-h fixes the boundary and kernel prefix; the reason must name the
    # missing property. Only elapsed_ns has a specified complete reason.
    if field == "elapsed_ns":
        return reason == prefix + "measurement_unsupported:elapsed_ns"
    return reason.startswith(prefix) and field in reason[len(prefix):]


def rejected_addition(r, member, field):
    # The candidate's source model is an existing input, saved before this boundary.
    previous = r.pool()
    records = snapshot_records(r)
    with pytest.raises(fb.CandidateInputError) as caught:
        add(r, member)
    assert names_shortfall(caught.value.reason, "step_time:peek:", field), caught.value.reason
    assert snapshot_records(r) == records
    assert r.pool() == previous


def boot_shortage(r, kernel, field):
    r.start()
    # Run every offered stage of this finite thought. A pending Boot reason
    # alone does not show that the scheduler actually stopped the comparison.
    for _ in range(len(ORDER)+1):
        public_rounds(r)
        offers = [(q, body) for stage in ORDER for q in r.requests(stage)
                  for wid, body in r.launcher.attempts
                  if wid == q.value["desc"]["work_id"] and wid not in r.executed]
        if not offers:
            break
        r.invoke(*offers[0])
    else:
        pytest.fail("the single thought did not finish or block")
    status = r.host.window.status()
    assert any(row.kind == "missing_contract" and row.target == r.boot()
               and row.contract == c.BOOT_DECLARATION
               and names_shortfall(row.reason, f"execution:step_time:{kernel}:", field)
               for row in status.pending), [(row.kind, row.reason) for row in status.pending]
    observed = (len(r.requests("evaluation")), len(r.draw_calls), len(r.facts(c.SELECTION)),
                len(r.requests("execute_step")), len(r.actor.calls))
    assert observed == (0, 0, 0, 0, 0), "evaluation, draw, selection, step request, actor"


@pytest.mark.parametrize("omit_empty", [True, False], ids=["absent-e", "declared-zero-e"])
def test_addition_checks_the_incoming_kernel_before_saving(worlds, omit_empty):
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, measurement=at_entry()).start()
    selected = r.think()
    assert r.selected_value(selected).choice.id == "peek" and not r.actor.calls
    member = candidate(r, "later", omit_empty=omit_empty)
    if omit_empty:
        rejected_addition(r, member, "cells")
    else:
        added = add(r, member)
        assert r.pool().point == added.pool and r.pool().members[-1].model == member.model


@pytest.mark.parametrize("omit_empty", [True, False], ids=["padded-zero", "declared-zero"])
def test_first_moving_candidate_rechecks_existing_members_behind_the_sum(worlds, omit_empty):
    # Both static pools publicly expose the same two outcome blocks, including
    # a zero e block for the second member. Only one member actually declares e.
    r = worlds(process=None, prior=FAIR, measurement=at_entry()).start()
    static = candidate(r, "static", omit_empty=omit_empty)
    add(r, static)
    pool = r.pool()
    doc = r.read_stored(pool.model)[2].body.content.as_json()["document"]
    peek = next(k for k in doc["kernels"] if k["id"] == "peek")
    by_id = {o["id"]: o["matrix"] for o in peek["outcomes"]}
    assert set(by_id) == {"t", "e"}
    assert by_id["e"][0][0] == [1, 1]
    assert [row[2:] for row in by_id["e"][2:]] == [[[0, 1], [0, 1]]] * 2
    moving = candidate(r, "moving", moving=True)
    if omit_empty:
        rejected_addition(r, moving, "cells")
    else:
        added = add(r, moving)
        assert r.pool().point == added.pool and len(r.pool().members) == 3


@pytest.mark.parametrize("varies_in", ["static", "moving"])
def test_entry_time_depends_on_variation_within_the_moving_member(worlds, varies_in):
    # Neither member omits an outcome. Only variation along a possible
    # transition needs a time of measurement (K41 decision 6).
    constant, varies = (HALF, HALF), (0, 1)
    old, new = (varies, constant) if varies_in == "static" else (constant, varies)
    r = worlds(process=None, prior=FAIR, sensor=old,
               measurement={"time_basis": at_entry()["time_basis"]}).start()
    member = candidate(r, "moving", sensor=new, moving=True)
    if varies_in == "moving":
        rejected_addition(r, member, "measurement")
    else:
        added = add(r, member)
        assert r.pool().point == added.pool and len(r.pool().members) == 2


@pytest.mark.parametrize("referenced_by_orphan", [False, True], ids=["unused-kernel", "unused-policy"])
@pytest.mark.parametrize("has_basis", [False, True], ids=["missing-basis", "complete"])
def test_boot_checks_declared_readings_even_outside_the_compared_policies(
        worlds, referenced_by_orphan, has_basis):
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, measurement=at_entry())
    doc = deepcopy(r.document)
    peek = next(k for k in doc["kernels"] if k["id"] == "peek")
    doc["kernels"].append(dict(deepcopy(peek), id="unused"))
    orphan = deepcopy(next(p for p in doc["policies"] if p["id"] == "peek"))
    orphan["id"] = "orphan"
    if referenced_by_orphan:
        orphan["nodes"][0]["kernel"] = "unused"
    doc["policies"].append(orphan)
    r.replace_model(doc)
    decl = r.boot_input.declaration
    slot = decl.execution
    ex = slot.value
    reading = ex.source_readings["peek"]
    ex = replace(ex, actors={**ex.actors, "unused": ex.actors["peek"]},
                 cells={**ex.cells, "unused": ex.cells["peek"]},
                 source_readings={**ex.source_readings,
                                  "unused": reading if has_basis else replace(reading, time_basis=None)})
    r.boot_input = replace(r.boot_input, declaration=replace(decl, execution=replace(slot, value=ex)))
    if has_basis:
        r.start()
        pick = r.think()
        assert set(r.selected_value(pick).evaluation.candidates) == {"peek", "wait"}
        assert [v.cid for v in r.facts(c.SELECTION)] == [pick.cid]
    else:
        boot_shortage(r, "unused", "time_basis")


@pytest.mark.parametrize("elapsed", [0, 1], ids=["instantaneous", "same-positive-duration"])
def test_boot_names_elapsed_ns_when_all_outcomes_have_duration(worlds, elapsed):
    r = worlds(prior=FAIR, thinking=True, start_ns=ORIGIN, measurement=at_entry())
    doc = deepcopy(r.document)
    peek = next(k for k in doc["kernels"] if k["id"] == "peek")
    for outcome in peek["outcomes"]:
        outcome["elapsed_ns"] = elapsed
    r.replace_model(doc)
    if elapsed:
        boot_shortage(r, "peek", "elapsed_ns")
    else:
        r.start()
        assert "peek" in r.selected_value(r.think()).evaluation.candidates


@pytest.mark.parametrize("process", [None, ZERO], ids=["omitted", "declared-zero"])
def test_static_pool_leaves_null_policies_to_the_original_model_check(worlds, process):
    r = worlds(process=process, state_role=None if process is None else "mood", family=None,
               prior=FAIR, thinking=True, start_ns=ORIGIN)
    r.replace_model(dict(r.document, policies=None))
    r.start()
    public_rounds(r, run_generation=True)
    request, = r.requests("evaluation_prepare")
    assert not any("step_time" in row.reason for row in r.host.window.status().pending)
    # The ordinary F-a preparation function names the field. The saved K32
    # worker failure exposes the error type, not the exception's prose.
    args = request.value["desc"]["args"]["input"]
    assert args["model"] == r.model_point
    with pytest.raises(f.FInputError) as caught:
        ff.prepare_f_from_facts(Reader(r.ledger), fixed_parents=frozenset(args["fixed_parents"]),
            model_ref=args["model"], candidate_ref=args["candidates"],
            preference_refs=tuple(args["preferences"]), scope_request=f.EvaluationScope(**args["scope"]),
            context_ref=args["context"], method=ContractRef(**args["method"]), registry=r.registry,
            budget=r.boot_input.declaration.initial.value.prepare_budget)
    assert (caught.value.reason, caught.value.field) == ("shape", "/policies")
    assert time_finish_activity(r).outcome == "failure"
    terminal, = [v.value for v in r.facts(c.WORK_TERMINAL) if v.value["request"] == request.cid]
    assert terminal["terminal_kind"] == "failure"
    assert terminal["basis"]["failure"]["content"]["error_type"] == "FInputError"
    assert r.host.halted is None and not r.draw_calls and not r.facts(c.SELECTION) and not r.actor.calls
