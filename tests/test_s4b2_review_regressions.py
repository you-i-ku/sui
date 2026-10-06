"""Review R1-R3: public selection, physical time, and saved belief replay.

Expectations come from S4b-2 sections 3-0-4, 3-10-2/4/7/8, 6-4 and 7.
Only public constructors, records and entry points are used.
"""
from dataclasses import replace
from fractions import Fraction as F
import json

import pytest

from sui import rate, rate_entry
from sui.agent import Agent, plan
from sui.contracts import ContractRef
from sui.records import Payload
from s4b2_worlds import (
    CANDIDATES, NS, STANDARD_BUDGET, U, c1_declaration, c1_world, command,
    millisecond_declaration, minute_declaration,
)
from test_s4b2_integration import budget_json, ledger_image, root


TINY = rate.RateBudget(F(1, 10**9), 1, 1, 1)
LARGER = replace(STANDARD_BUDGET, max_cells=40000, max_terms=4000,
                 max_refinements=40000)
RESTORE_BUDGETS = [TINY, None, STANDARD_BUDGET, LARGER]
RESTORE_IDS = ["same", "default", "standard", "larger"]


@pytest.mark.parametrize("budget", [
    replace(STANDARD_BUDGET, max_refinements=2),
    replace(STANDARD_BUDGET, max_cells=8, max_refinements=2),
], ids=["two-refinements", "eight-cells-two-refinements"])
@pytest.mark.parametrize("entry", ["public_evaluate", "plan", "decide"])
def test_R1_initial_enclosure_selects_read_with_small_budget(entry, budget):
    """C1 h0 already proves 0 <= 14/25 < F1.lower (section 6-4).

    Eight cells admit the initial joint state/count table. The small resource
    limits must not force diagnostic narrowing before an already proved act.
    """
    f = root(budget=budget)
    before = ledger_image(f.w.ledger)
    if entry == "public_evaluate":
        draft = rate_entry.public_evaluate(f.view, CANDIDATES, f.resolved,
                                          u=U, budget=budget)
        content = draft.content.as_json()
    elif entry == "plan":
        draft = plan(f.view, CANDIDATES, u=U, rate_budget=budget)
        content = draft.content.as_json()
    else:
        decided, job = f.agent.decide(
            CANDIDATES, u=U, clock=f.w.clock, ids=f.w.ids, ledger=f.w.ledger,
            now_mono_ns=NS, observed_mono_ns=NS,
            check_events=f.view.check_events, rate_budget=budget,
        )
        content = decided.body.content.as_json()
        assert job.body.content.as_json() == command("read")
        assert job.body.decision == decided.id
        for record in (decided, job):
            cid = f.w.ledger.entries_of(record.id)[0].cid
            assert f.w.ledger.record(cid) == record
    selection = content["selection"]
    assert (selection["index"], selection["chosen"]) == (0, "read")
    assert content["u"] == [14, 25]
    assert F(*selection["previous"][1]) <= U < F(*selection["current"][0])
    assert content["intent"] == command("read")
    assert content["certificate"]["budget"] == budget_json(budget)
    assert all(step["operation"] != "split" for step in content["certificate"]["trace"])
    after = ledger_image(f.w.ledger)
    assert {cid: after[cid] for cid in before} == before
    if entry != "decide":
        assert after == before


@pytest.mark.parametrize("entry", ["public_evaluate", "plan", "decide"])
@pytest.mark.parametrize("u, index, chosen", [
    (F(3, 5), 0, "read"),
    (F(61, 100), 1, "wait"),
], ids=["read-side", "wait-side"])
def test_R1_public_selection_refines_ambiguous_initial_enclosure(entry, u, index, chosen):
    """Both sides of C1's boundary require refinement (sections 3-0-4, 6-4).

    An early, read-only selection at 14/25 exposes the initial enclosure
    through the public payload. Each tested u lies inside that enclosure;
    the requested entry must narrow it enough to prove its selected act.
    """
    f = root(budget=STANDARD_BUDGET)
    before = ledger_image(f.w.ledger)
    initial = rate_entry.public_evaluate(
        f.view, CANDIDATES, f.resolved, u=U, budget=STANDARD_BUDGET,
    ).content.as_json()
    assert initial["selection"]["chosen"] == "read"
    assert all(step["operation"] != "split" for step in initial["certificate"]["trace"])
    initial_lower, initial_upper = (F(*bound) for bound in initial["selection"]["current"])
    assert initial_lower < u < initial_upper
    assert ledger_image(f.w.ledger) == before

    if entry == "public_evaluate":
        content = rate_entry.public_evaluate(
            f.view, CANDIDATES, f.resolved, u=u, budget=STANDARD_BUDGET,
        ).content.as_json()
    elif entry == "plan":
        content = plan(f.view, CANDIDATES, u=u,
                       rate_budget=STANDARD_BUDGET).content.as_json()
    else:
        decided, job = f.agent.decide(
            CANDIDATES, u=u, clock=f.w.clock, ids=f.w.ids, ledger=f.w.ledger,
            now_mono_ns=NS, observed_mono_ns=NS,
            check_events=f.view.check_events, rate_budget=STANDARD_BUDGET,
        )
        content = decided.body.content.as_json()
        assert job.body.content.as_json() == command(chosen)
        assert job.body.decision == decided.id
        for record in (decided, job):
            cid = f.w.ledger.entries_of(record.id)[0].cid
            assert f.w.ledger.record(cid) == record

    selection = content["selection"]
    assert (selection["index"], selection["chosen"]) == (index, chosen)
    assert content["u"] == [u.numerator, u.denominator]
    assert F(*selection["previous"][1]) <= u < F(*selection["current"][0])
    boundary = selection["current" if chosen == "read" else "previous"]
    assert F(*boundary[1]) - F(*boundary[0]) < initial_upper - initial_lower
    assert content["intent"] == command(chosen)
    assert content["certificate"]["budget"] == budget_json(STANDARD_BUDGET)
    after = ledger_image(f.w.ledger)
    assert {cid: after[cid] for cid in before} == before
    if entry != "decide":
        assert after == before


def state_probabilities(summary):
    """Read the persisted public axes and bounds, without rebuilding a belief."""
    assert (summary["status"], summary["reason"]) == ("complete", None)
    marginal = summary["state_marginal"]
    assert marginal["targets"] == [
        {"time_s": [1, 1], "causal_stage": 0, "causal_position": 0, "side": "post"}
    ]
    assert summary["states"] == ["0", "1"]
    values = {}
    for row in marginal["values"]:
        quantity = row["quantity"]
        assert (quantity["status"], quantity["support"]) == ("finite", "positive")
        bounds = quantity["bounds"]
        values[tuple(row["states"])] = (F(*bounds["lower"]), F(*bounds["upper"]))
    assert set(values) == {("0",), ("1",)}
    for state, expected in [("0", F(2, 3)), ("1", F(1, 3))]:
        lower, upper = values[(state,)]
        assert lower <= expected <= upper
        assert upper-lower <= STANDARD_BUDGET.tolerance
    return values


@pytest.mark.parametrize("declaration", [
    c1_declaration, millisecond_declaration, minute_declaration,
], ids=["seconds", "milliseconds", "minutes"])
@pytest.mark.parametrize("boot_ns", [0, 7*NS], ids=["zero-boot", "shifted-boot"])
def test_R2_adopt_restore_summary_uses_same_physical_time(declaration, boot_ns):
    reference_world = c1_world(0, boot_ns=boot_ns)
    world = c1_world(0, boot_ns=boot_ns, declaration=declaration())
    assert world.records == reference_world.records
    assert ledger_image(world.ledger) == ledger_image(reference_world.ledger)
    reference = root(world=reference_world, budget=STANDARD_BUDGET)
    f = root(world=world, budget=STANDARD_BUDGET)
    assert f.belief.body.contract == ContractRef("sui.s4b.rate_belief", "1")
    expected = state_probabilities(reference.belief.body.content.as_json())
    summary = f.belief.body.content.as_json()
    assert summary["context"]["now_ns"] == boot_ns+NS
    assert summary["context"]["observed_ns"] == boot_ns+NS
    actual = state_probabilities(summary)
    # Enclosures may differ in rounding across units, but must enclose the
    # same exact probabilities at the same physical target, with narrow width.
    for state in expected:
        assert max(actual[state][0], expected[state][0]) <= min(actual[state][1], expected[state][1])
    cid = world.ledger.entries_of(f.belief.id)[0].cid
    before = ledger_image(world.ledger)
    restored = Agent.restore(model=f.model, lineage="unit-restored", ledger=world.ledger,
                             belief=cid, rate_budget=STANDARD_BUDGET)
    assert restored.view().belief == f.belief.id
    assert restored.view().reading == f.view.reading
    assert ledger_image(world.ledger) == before
    assert world.ledger.record(cid).body.content.as_json() == summary
    # Materialize the restored summary through the public belief_record entry.
    again = restored.belief_record(ledger=world.ledger, clock=world.clock, ids=world.ids)
    assert state_probabilities(again.body.content.as_json()) == actual
    after = ledger_image(world.ledger)
    assert {key: after[key] for key in before} == before


@pytest.mark.parametrize("budget", RESTORE_BUDGETS, ids=RESTORE_IDS)
def test_R3_incomplete_belief_restores_with_any_sufficient_budget(budget):
    f = root(budget=TINY)
    summary = f.belief.body.content.as_json()
    assert (summary["status"], summary["reason"], summary["evidence"]) == (
        "incomplete", "budget", None)
    assert summary["state_marginal"] is None
    cid = f.w.ledger.entries_of(f.belief.id)[0].cid
    before = ledger_image(f.w.ledger)
    kwargs = {} if budget is None else {"rate_budget": budget}
    restored = Agent.restore(model=f.model, lineage="budget-restored", ledger=f.w.ledger,
                             belief=cid, **kwargs)
    assert restored.rate_budget == (STANDARD_BUDGET if budget is None else budget)
    assert restored.view().belief == f.belief.id
    assert restored.view().reading == f.view.reading
    assert ledger_image(f.w.ledger) == before
    assert f.w.ledger.record(cid).body.content.as_json() == summary
    if budget != TINY:
        # A new mathematical query can complete using the restored raw input;
        # the saved incomplete summary is still the original derived record.
        improved = rate.rebuild_rate_belief(
            f.model, restored.view().reading, context=f.w.context,
            budget=restored.rate_budget,
        )
        assert improved.evidence.support == "positive"
        assert improved.evidence.value.lower <= F(3, 8) <= improved.evidence.value.upper
    assert ledger_image(f.w.ledger) == before
    for record in f.w.records:
        assert f.w.ledger.record(f.w.ledger.entries_of(record.id)[0].cid) == record


@pytest.mark.parametrize("field", ["states", "context", "status", "reason", "state_marginal"])
@pytest.mark.parametrize("budget", RESTORE_BUDGETS, ids=RESTORE_IDS)
def test_R3_incomplete_summary_tampering_is_still_a_replay_mismatch(field, budget):
    f = root(budget=TINY)
    content = f.belief.body.content.as_json()
    if field == "states":
        content[field] = ["1", "0"]
    elif field == "context":
        content[field]["now_ns"] += NS
    elif field == "status":
        content[field] = "complete"
    elif field == "reason":
        content[field] = "history_scope"
    else:
        content[field] = root(budget=STANDARD_BUDGET).belief.body.content.as_json()[field]
    altered = replace(f.belief, body=replace(f.belief.body, content=Payload.json(content)))
    original = f.w.ledger.entries_of(f.belief.id)[0]
    parents = tuple(json.loads(original.header)["parents"])
    # Keep the raw root but not the genuine belief with the same Record ID;
    # otherwise Ledger correctly rejects the conflict before restore runs.
    ledger = c1_world().ledger
    entry = ledger.append(altered, parents)
    before = ledger_image(ledger)
    kwargs = {} if budget is None else {"rate_budget": budget}
    with pytest.raises(rate.RateReplayMismatch):
        Agent.restore(model=f.model, lineage="tampered", ledger=ledger,
                      belief=entry.cid, **kwargs)
    assert ledger_image(ledger) == before
