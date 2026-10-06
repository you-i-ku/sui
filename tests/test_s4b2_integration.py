"""Specification v0.13: T11/T12/T14/T15/T18/T20 and R01/R07 boundaries.

Only public inputs/outputs and existing public test doubles are used. Replay
negatives change one saved field at a time; an overlap is not a proof (M19).
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from functools import lru_cache
from inspect import signature
from types import SimpleNamespace

import pytest

from sui import rate, rate_entry
from sui.agent import Agent, plan, read, replay_decision
from sui.contracts import ContractRef
from sui.ids import RefKind, SequentialIds
from sui.ledger import Ledger, MemoryContents, SequentialSalts
from sui.model import model_from_json, model_json, model_ref
from sui.preference import current, resolve
from sui.records import Decided, JobOpened, Payload, Prediction, Preference, Role
from sui.runtime import Pledges, Reconsider, Think, Window
from sui.s4d_contracts import PREFERENCE
from sui.store import MemoryEntries, MemoryModels, SqliteStore, StorageFull
from s4b2_worlds import (
    CANDIDATES, MEMBRANE, NS, STANDARD_BUDGET, U, canonical, c1_world,
    command, completion_report, make_record, observation, reduction_declaration,
    refinement_content,
    start_attempt,
)
from worlds import FlakyContents, FlakyEntries, GatedHand, ManualHost, ScriptDrive


INJECTED = rate.RateBudget(F(1, 100), 21000, 2100, 21000)
LARGER = rate.RateBudget(F(1, 10**9), 42000, 4200, 42000)
RATE_REFINEMENT = ContractRef("sui.s4b.rate_refinement", "1")


def root(*, world=None, budget=INJECTED):
    if "rate_budget" not in signature(Agent).parameters:
        raise NotImplementedError("PHASE4: Agent rate_budget is not connected")
    w = c1_world() if world is None else world
    model = model_from_json(w.declaration)
    assert model_json(model) == w.declaration
    assert read(model, w.records) == rate_entry.read_rate(model, w.records)
    agent = Agent(model=model, lineage="c1", rate_budget=budget)
    belief = agent.adopt(w.ledger, clock=w.clock, ids=w.ids)
    view = agent.view(now_ns=w.context.now_ns, observed_ns=w.context.observed_ns,
                      check_events=w.context.check_events)
    return SimpleNamespace(w=w, model=model, agent=agent, belief=belief, view=view,
                           resolved=resolve(current(view.preferences), view), budget=budget)


@lru_cache(maxsize=1)
def prepared_template():
    """One genuine immutable Commit for the identical C1 root in negatives."""
    f = root()
    draft = plan(f.view, CANDIDATES, u=U, rate_budget=f.budget)
    prepared = f.agent.prepare(draft, clock=f.w.clock, ids=f.w.ids)
    return f.belief, draft, prepared


def planned():
    f = root()
    belief, f.draft, f.prepared = prepared_template()
    assert f.belief == belief
    assert f.draft.parents == f.view.frontier and f.draft.belief == f.view.belief
    # Each case has its own clock/ledger. Advance that same public clock past
    # the template's records; future records use a fresh public ID namespace.
    last_seq = max(f.prepared.decided.at.seq, f.prepared.job.at.seq)
    while f.w.clock.now().seq <= last_seq:
        pass
    f.w.ids = SequentialIds("phase4-followup")
    return f


@lru_cache(maxsize=1)
def committed_template():
    f = planned()
    f.agent.commit(f.prepared, ledger=f.w.ledger)
    return f.w.ledger


def saved():
    f = planned()
    # merge reads the certified template and preserves all CIDs and payloads;
    # no test mutates the template or another case's ledger.
    f.w.ledger.merge(committed_template())
    f.cid = f.w.ledger.entries_of(f.prepared.decided.id)[0].cid
    return f


def ledger_image(ledger):
    """Compare IDs, headers AND payloads, not merely the number of records."""
    return {e.cid: (e.header, ledger.contents.get(e.seal)) for e in ledger.entries()}


def assert_extension(ledger, before):
    after = ledger_image(ledger)
    assert {cid: after[cid] for cid in before} == before


def budget_json(budget):
    return {"tolerance": [budget.tolerance.numerator, budget.tolerance.denominator],
            "max_cells": budget.max_cells, "max_terms": budget.max_terms,
            "max_refinements": budget.max_refinements}


def verify(f, *, ledger=None, decision=None, budget=None):
    return rate_entry.verify_rate_decision(model=f.model,
        ledger=f.w.ledger if ledger is None else ledger,
        decision=f.cid if decision is None else decision,
        budget=f.budget if budget is None else budget)


def altered_saved(f, *, edit=None, decided_edit=None, job_edit=None):
    """A separate valid ledger envelope around one untrusted saved claim."""
    ledger = Ledger(salts=SequentialSalts())
    ledger.merge(f.w.ledger)
    decided, job = f.prepared.decided, f.prepared.job
    if edit is not None:
        content = decided.body.content.as_json()
        edit(content)
        decided = replace(decided, body=replace(decided.body, content=Payload.json(content)))
    if decided_edit is not None:
        decided = replace(decided, body=decided_edit(decided.body))
    if job_edit is not None:
        job = replace(job, body=job_edit(job.body))
    entry = ledger.append(decided, f.prepared.parents)
    ledger.append(job, (entry.cid,))
    return ledger, entry.cid


def posterior(f, reading=None, context=None):
    belief = rate.rebuild_rate_belief(f.model,
        f.view.reading if reading is None else reading,
        context=f.w.context if context is None else context, budget=f.budget)
    return (belief.evidence.value,
            rate.parameter_moment(belief, powers=(("r", 1),), budget=f.budget).bounds,
            rate.parameter_moment(belief, powers=(("p", "y0", 1),), budget=f.budget).bounds)


@pytest.mark.parametrize("boot_ns", [0, 7*NS])
def test_T14_public_roundtrip_keeps_injected_budget_and_planned_start(boot_ns):
    f = root(world=c1_world(boot_ns=boot_ns))
    w, agent = f.w, f.agent
    assert agent.rate_budget == INJECTED
    before, frontier, revision = ledger_image(w.ledger), agent.frontier, agent.revision
    draft = plan(f.view, CANDIDATES, u=U, rate_budget=INJECTED)
    assert draft == rate_entry.public_evaluate(f.view, CANDIDATES, f.resolved, u=U, budget=INJECTED)
    content = draft.content.as_json()
    assert set(content) == {"root", "candidates", "u", "values", "display", "selection", "intent", "certificate"}
    assert content["certificate"]["budget"] == budget_json(INJECTED)
    assert content["u"] == [14, 25] and content["display"] is None
    assert set(content["root"]) == {"model", "belief", "parents", "facts", "context",
                                   "items", "style", "evaluation", "H_ns", "gamma"}
    assert content["root"]["model"] == model_ref(f.model)
    assert content["root"]["belief"] == str(f.belief.id)
    assert content["root"]["parents"] == sorted(f.view.frontier)
    assert content["root"]["gamma"] == [1, 1]
    assert content["intent"] == command("read")
    assert content["selection"]["index"] == 0 and content["selection"]["chosen"] == "read"
    previous, current = content["selection"]["previous"], content["selection"]["current"]
    assert F(*previous[1]) <= U < F(*current[0])
    # Delaying prepare must not move the command's planned physical position.
    w.clock.advance(37)
    prepared = agent.prepare(draft, clock=w.clock, ids=w.ids)
    assert ledger_image(w.ledger) == before
    assert (agent.frontier, agent.revision) == (frontier, revision)
    assert prepared.job.body.content.as_json() == command("read")
    assert prepared.job.body.decision == prepared.decided.id and prepared.job.body.step == 0
    agent.commit(prepared, ledger=w.ledger)
    cid = w.ledger.entries_of(prepared.decided.id)[0].cid
    assert rate_entry.verify_rate_decision(model=f.model, ledger=w.ledger, decision=cid, budget=LARGER) == draft
    assert replay_decision(model=f.model, ledger=w.ledger, decision=cid) == draft
    belief_cid = w.ledger.entries_of(f.belief.id)[0].cid
    restored = Agent.restore(model=f.model, lineage="restored", ledger=w.ledger,
                             belief=belief_cid, rate_budget=INJECTED)
    assert restored.rate_budget == INJECTED and restored.view().belief == f.belief.id
    restored_view = restored.view(now_ns=f.view.now_ns, observed_ns=f.view.observed_ns,
                                  check_events=f.view.check_events)
    assert plan(restored_view, CANDIDATES, u=U, rate_budget=INJECTED) == draft


@pytest.mark.parametrize("override", [None, LARGER], ids=["agent-budget", "explicit-budget"])
def test_T14_decide_budget_precedence_and_same_public_plan(override):
    f = root()
    selected = f.budget if override is None else override
    expected = plan(f.view, CANDIDATES, u=U, rate_budget=selected)
    kwargs = {} if override is None else {"rate_budget": override}
    decided, job = f.agent.decide(CANDIDATES, u=U, clock=f.w.clock, ids=f.w.ids,
        ledger=f.w.ledger, now_mono_ns=f.view.now_ns, observed_mono_ns=f.view.observed_ns,
        check_events=f.view.check_events, **kwargs)
    assert decided.body.content == expected.content
    assert decided.body.content.as_json()["certificate"]["budget"] == budget_json(selected)
    assert job.body.content.as_json() == command("read")
    assert f.agent.rate_budget == INJECTED


def test_T14_runtime_Think_and_real_worker_keep_issued_budget(monkeypatch):
    f = root()
    hand = GatedHand({"read": set(), "wait": set()}, {"read": [], "wait": []})
    pledges = Pledges(requests=[Reconsider(candidates=CANDIDATES, u=U)],
        latest_ns=(f.w.clock.run, f.view.now_ns), latest_check_events=f.view.check_events)
    window = Window(agent=f.agent, ledger=f.w.ledger, clock=f.w.clock, ids=f.w.ids,
        membrane=MEMBRANE, route="c1", hand=hand, drive=ScriptDrive(lambda status, event: ()),
        capacity={"think": 1}, pledges=pledges)
    window.settle()
    work, = window.drain()
    assert isinstance(work, Think) and work.rate_budget == INJECTED
    monkeypatch.setattr(rate, "default_rate_budget", lambda: LARGER)
    # ManualHost.finish invokes the actual worker through the existing fixture.
    host = ManualHost(lambda p: window, clock=f.w.clock)
    host.work.append((work, hand))
    before = ledger_image(f.w.ledger)
    event = host.finish(work)
    assert event.error is None and event.draft is not None
    assert event.draft.content.as_json()["certificate"]["budget"] == budget_json(INJECTED)
    assert event.draft == plan(work.view, work.candidates, u=work.u, rate_budget=INJECTED)
    assert ledger_image(f.w.ledger) == before and hand.calls == []


@pytest.mark.parametrize("store_kind", ["entries", "contents"])
@pytest.mark.parametrize("fail_offset", [1, 2])
def test_T14_partial_save_retries_exact_Commit_without_new_u_or_job(store_kind, fail_offset):
    f = planned()
    entries, contents = FlakyEntries(MemoryEntries()), FlakyContents(MemoryContents())
    ledger = Ledger(salts=SequentialSalts(), entries=entries, contents=contents)
    ledger.merge(f.w.ledger)
    before = ledger_image(ledger)
    getattr(SimpleNamespace(entries=entries, contents=contents), store_kind).fail_next(fail_offset)
    with pytest.raises(StorageFull):
        f.agent.commit(f.prepared, ledger=ledger)
    visible = {ledger.record(e.cid).id for e in ledger.entries()}
    assert (f.prepared.decided.id in visible) == (fail_offset == 2)
    assert f.prepared.job.id not in visible
    f.agent.commit(f.prepared, ledger=ledger)
    complete = ledger_image(ledger)
    assert_extension(ledger, before)
    assert len(ledger.entries_of(f.prepared.decided.id)) == 1
    assert len(ledger.entries_of(f.prepared.job.id)) == 1
    assert ledger.record(ledger.entries_of(f.prepared.decided.id)[0].cid) == f.prepared.decided
    assert ledger.record(ledger.entries_of(f.prepared.job.id)[0].cid) == f.prepared.job
    f.agent.commit(f.prepared, ledger=ledger)
    assert ledger_image(ledger) == complete


@pytest.mark.parametrize("change,field", [
    ("u", "selection"), ("job-command", "intent"), ("inputs", "inputs"),
    ("interval", "interval")])
def test_T14_commit_checks_everything_before_first_save(change, field):
    f = planned()
    p = f.prepared
    if change == "u":
        data = p.decided.body.content.as_json()
        data["u"] = [99, 100]
        p = replace(p, decided=replace(p.decided, body=replace(p.decided.body, content=Payload.json(data))))
    elif change == "job-command":
        p = replace(p, job=replace(p.job, body=replace(p.job.body, content=Payload.json(command("wait")))))
    elif change == "inputs":
        p = replace(p, decided=replace(p.decided, body=replace(p.decided.body, inputs=())))
    else:
        data = p.decided.body.content.as_json()
        change_claim(data, "overlapping-false-interval")
        p = replace(p, decided=replace(p.decided, body=replace(p.decided.body, content=Payload.json(data))))
    before = ledger_image(f.w.ledger)
    with pytest.raises(rate.RateReplayMismatch) as caught:
        f.agent.commit(p, ledger=f.w.ledger)
    assert field in caught.value.fields
    assert ledger_image(f.w.ledger) == before


def test_T12_M18_later_report_changes_posterior_but_not_saved_replay():
    f = saved()
    before = ledger_image(f.w.ledger)
    old = posterior(f)
    attempt = start_attempt(f.w, f.prepared.job.id)
    f.w.ledger.accept(attempt)
    result = completion_report(f.w, attempt, "read", 0, "y0")
    f.w.ledger.accept(result)
    f.agent.adopt(f.w.ledger, clock=f.w.clock, ids=f.w.ids)
    new_view = f.agent.view(now_ns=2*NS, observed_ns=2*NS, check_events=({"fact": str(result.id)},))
    context = replace(f.w.context, now_ns=2*NS, observed_ns=2*NS,
        check_events=new_view.check_events, fact_ancestors=new_view.fact_ancestors)
    new = posterior(f, new_view.reading, context)
    assert old[2].lower <= F(1, 2) <= old[2].upper
    assert new[2].lower <= F(2, 3) <= new[2].upper
    assert old[2].upper < new[2].lower
    assert verify(f) == f.draft
    assert_extension(f.w.ledger, before)
    # Explicitly inserting this future fact into the saved root is a mismatch.
    g = planned()
    bad, cid = altered_saved(g, edit=lambda data: data["root"]["facts"].append(str(result.id)))
    bad.accept(attempt)
    bad.accept(result)
    with pytest.raises(rate.RateReplayMismatch) as caught:
        verify(g, ledger=bad, decision=cid)
    assert "evidence" in caught.value.fields


def change_claim(data, name):
    if name == "u":
        data["u"] = [99, 100]
    elif name == "candidate-order":
        data["candidates"].reverse()
    elif name == "reservation":
        data["intent"]["reservation_rule"] = {"kind": "offset", "offset_ns": 1}
        data["candidates"][0]["command"] = deepcopy(data["intent"])
    elif name == "candidate-command":
        data["candidates"][0]["command"]["execution"]["completion_process"] = "wait-done"
    elif name == "overlapping-false-interval":
        bounds = data["values"][0]["q_star"]["bounds"]
        lo, hi = F(*bounds["lower"]), F(*bounds["upper"])
        assert lo < hi
        # A singleton strictly inside the genuine interval always overlaps it;
        # it was not proved by the saved trace. Even if it accidentally equals
        # the true value, its alleged derivation still cannot be replayed.
        value = (2*lo+hi)/3
        q = [value.numerator, value.denominator]
        complement = 1-value
        other = [complement.numerator, complement.denominator]
        replacements = ((bounds, {"lower": q, "upper": q}),
            (data["values"][1]["q_star"]["bounds"], {"lower": other, "upper": other}))
        def aliases(node):
            for old, new in replacements:
                if node == old:
                    return deepcopy(new)
                if node == [old["lower"], old["upper"]]:
                    return [new["lower"], new["upper"]]
            if isinstance(node, dict):
                return {key: aliases(child) for key, child in node.items()}
            if isinstance(node, list):
                return [aliases(child) for child in node]
            return node
        # Forge the same numerical claim in values, cumulative selection and
        # every certificate enclosure. Merely comparing those untrusted copies
        # with each other must not pass as replaying the saved derivation.
        changed = aliases(data)
        assert changed["certificate"]["enclosures"] != data["certificate"]["enclosures"]
        assert changed["certificate"]["trace"] == data["certificate"]["trace"]
        assert changed["selection"]["current"] == [q, q]
        assert changed["values"][0]["q_star"]["bounds"] == {"lower": q, "upper": q}
        assert value > F(*data["u"])
        data.clear()
        data.update(changed)
    elif name == "trace":
        assert data["certificate"]["trace"]
        assert data["certificate"]["trace"][0]["operation"] != "select"
        data["certificate"]["trace"][0]["operation"] = "select"
    else:
        raise AssertionError(name)


@pytest.mark.parametrize("name,field", [
    ("u", "selection"), ("candidate-order", "root"), ("reservation", "intent"),
    ("candidate-command", "intent"), ("overlapping-false-interval", "interval"),
    ("trace", "interval")])
def test_T12_M19_M20_replay_rejects_one_changed_claim_with_fields(name, field):
    f = planned()
    job_edit = None
    if name == "reservation":
        intent = f.prepared.job.body.content.as_json()
        intent["reservation_rule"] = {"kind": "offset", "offset_ns": 1}
        job_edit = lambda body: replace(body, content=Payload.json(intent))
    bad, cid = altered_saved(f, edit=lambda data: change_claim(data, name), job_edit=job_edit)
    before = ledger_image(bad)
    with pytest.raises(rate.RateReplayMismatch) as caught:
        verify(f, ledger=bad, decision=cid)
    assert field in caught.value.fields
    assert ledger_image(bad) == before


@pytest.mark.parametrize("name", ["decision-contract", "method", "arithmetic", "missing-reference"])
def test_T12_unavailable_is_distinct_from_mismatch_and_incomplete(name):
    f = planned()
    if name == "decision-contract":
        bad, cid = altered_saved(f, decided_edit=lambda body: replace(body,
            contract=ContractRef(body.contract.name, "999")))
    elif name == "missing-reference":
        bad, cid = altered_saved(f)
        bad.contents.discard(bad.entries_of(f.w.root.id)[0].seal)
    else:
        def edit(data):
            data["certificate"][name]["version"] = "999"
        bad, cid = altered_saved(f, edit=edit)
    with pytest.raises(rate.RateReplayUnavailable) as caught:
        verify(f, ledger=bad, decision=cid)
    assert caught.value.reason == ("missing_reference" if name == "missing-reference" else "unknown_version")


def test_T12_replay_budget_is_resource_limit_and_does_not_replace_saved_budget():
    f = saved()
    before = ledger_image(f.w.ledger)
    assert verify(f, budget=LARGER) == f.draft
    with pytest.raises(rate.RateIncomplete) as caught:
        verify(f, budget=rate.RateBudget(F(1, 10**9), 1, 1, 1))
    assert caught.value.reason in {"budget", "accuracy", "tail_bound", "proof_unavailable"}
    assert ledger_image(f.w.ledger) == before
    assert verify(f).content.as_json()["certificate"]["budget"] == budget_json(INJECTED)


def test_T12_changed_model_bytes_are_not_a_compatible_replay():
    f = saved()
    # Decode the public canonical bytes, never inspect model internals.
    import json
    declaration = json.loads(model_json(f.model))
    declaration["variables"][0]["prior"]["params"]["rate"] = [3, 1]
    other = model_from_json(canonical(declaration))
    assert model_ref(other) != model_ref(f.model)
    with pytest.raises(rate.RateReplayMismatch) as caught:
        rate_entry.verify_rate_decision(model=other, ledger=f.w.ledger, decision=f.cid, budget=INJECTED)
    assert "root" in caught.value.fields


def test_T11_real_budget_exhaustion_keeps_raw_facts_and_writes_no_decision_or_job():
    f = root()
    before = ledger_image(f.w.ledger)
    with pytest.raises(rate.RateIncomplete):
        f.agent.decide(CANDIDATES, u=U, clock=f.w.clock, ids=f.w.ids, ledger=f.w.ledger,
            now_mono_ns=NS, observed_mono_ns=NS, check_events=f.view.check_events,
            rate_budget=rate.RateBudget(F(1, 10**9), 1, 1, 1))
    assert ledger_image(f.w.ledger) == before
    assert f.w.ledger.record(f.w.ledger.entries_of(f.w.root.id)[0].cid) == f.w.root


def test_T11_adopt_with_small_budget_keeps_facts_and_incomplete_summary():
    w = c1_world()
    raw = ledger_image(w.ledger)
    f = root(world=w, budget=rate.RateBudget(F(1, 10**9), 1, 1, 1))
    summary = f.belief.body.content.as_json()
    assert summary["status"] == "incomplete" and summary["reason"] is not None
    assert_extension(w.ledger, raw)
    before = ledger_image(w.ledger)
    with pytest.raises(rate.RateIncomplete):
        f.agent.decide(CANDIDATES, u=U, clock=w.clock, ids=w.ids, ledger=w.ledger,
            now_mono_ns=NS, observed_mono_ns=NS, check_events=f.view.check_events)
    assert ledger_image(w.ledger) == before


def test_G2_default_budget_is_read_only_and_direct_plan_uses_it():
    f = root(budget=None)
    assert f.agent.rate_budget == STANDARD_BUDGET
    with pytest.raises(AttributeError):
        f.agent.rate_budget = INJECTED
    draft = plan(f.view, CANDIDATES, u=U)
    assert draft.content.as_json()["certificate"]["budget"] == budget_json(STANDARD_BUDGET)


def test_G2_legacy_agent_keeps_None_and_rejects_non_None_budget():
    from test_s4b2_golden import golden
    model = model_from_json(golden.canonical(golden.scenarios()[0]["model"]))
    agent = Agent(model=model, lineage="legacy")
    assert agent.rate_budget is None
    with pytest.raises(ValueError):
        Agent(model=model, lineage="legacy", rate_budget=INJECTED)


@pytest.mark.parametrize("reason", ["tail_bound", "accuracy", "budget", "proof_unavailable"])
def test_T11_public_evaluator_failure_never_partially_writes(monkeypatch, reason):
    """Inject a public exception to test transactional handling, not numerics."""
    f = root()
    assert plan(f.view, CANDIDATES, u=U, rate_budget=INJECTED).content.as_json()["intent"] == command("read")
    before = ledger_image(f.w.ledger)
    def unavailable(*args, **kwargs):
        raise rate.RateIncomplete(reason, "public fault injection")
    monkeypatch.setattr(rate_entry, "public_evaluate", unavailable)
    with pytest.raises(rate.RateIncomplete) as caught:
        f.agent.decide(CANDIDATES, u=U, clock=f.w.clock, ids=f.w.ids, ledger=f.w.ledger,
            now_mono_ns=NS, observed_mono_ns=NS, check_events=f.view.check_events)
    assert caught.value.reason == reason
    assert ledger_image(f.w.ledger) == before


def test_T20_nonempty_preference_stops_with_cost_certificate():
    w = c1_world()
    pref = make_record(w.clock, w.ids, RefKind.PREFERENCE,
        Preference(basis=(), contract=PREFERENCE, content=Payload.json({"kind": "item",
            "rule": {"name": "table", "version": "1"},
            "args": {"feature": {"name": "constant", "version": "1"}, "probs": [[None, 1.0]]}})),
        writer=Role.MODEL)
    w.ledger.append(pref, w.ledger.heads())
    f = root(world=w)
    assert tuple(item.id for item in f.resolved.items) == (pref.id,)
    before = ledger_image(w.ledger)
    for evaluate in (lambda: plan(f.view, CANDIDATES, u=U, rate_budget=f.budget),
                     lambda: f.agent.decide(CANDIDATES, u=U, clock=w.clock, ids=w.ids,
                         ledger=w.ledger, now_mono_ns=NS, observed_mono_ns=NS,
                         check_events=f.view.check_events)):
        with pytest.raises(rate.RateIncomplete) as caught:
            evaluate()
        assert caught.value.reason == "cost_certificate"
        assert ledger_image(w.ledger) == before


@pytest.mark.parametrize("transport", ["same-record", "same-source", "shared-time-fields"])
def test_T18_M31_transport_and_shared_clock_do_not_add_evidence(transport):
    f = root()
    original = posterior(f)
    w = f.w
    if transport == "same-record":
        before = ledger_image(w.ledger)
        w.ledger.accept(w.root)
        assert ledger_image(w.ledger) == before
    elif transport == "same-source":
        duplicate = observation(w.clock, w.ids, w.root.body.content.as_json(),
            source_id=w.root.body.source_id, source_ns=NS,
            received_ns=NS)
        w.ledger.accept(duplicate)
    else:
        # All four fields are copies of this one shared exact reading. Their
        # presence must not multiply the likelihood of the physical report.
        content = w.root.body.content.as_json()
        assert content["completion_ns"] == content["window_end_ns"] == NS
        assert w.root.body.source_time_ns == w.root.body.received_ns == NS
    f.agent.adopt(w.ledger, clock=w.clock, ids=w.ids)
    view = f.agent.view(now_ns=NS, observed_ns=NS, check_events=f.view.check_events)
    assert posterior(f, view.reading) == original
    assert original[0].lower <= F(3, 8) <= original[0].upper
    assert original[1].lower <= F(7, 12) <= original[1].upper
    assert original[2].lower <= F(1, 2) <= original[2].upper
    assert plan(view, CANDIDATES, u=U, rate_budget=f.budget).content.as_json()["intent"] == command("read")


def test_v013_unrecorded_after_list_and_tuple_freeze_to_same_context():
    f = root()
    after = tuple(sorted(f.w.ledger.heads()))
    histories = []
    for value in (after, list(after)):
        event = {"unrecorded": {"kind": "tick", "reading": NS, "after": value}}
        view = f.agent.view(now_ns=NS, observed_ns=NS, check_events=(event,))
        context = replace(f.w.context, check_events=view.check_events, fact_ancestors=view.fact_ancestors)
        histories.append(rate_entry.rate_history(f.model, view.reading, context=context))
    assert histories[0].context == histories[1].context
    assert histories[0].evidence_key == histories[1].evidence_key
    assert isinstance(histories[1].context.check_events[0]["unrecorded"]["after"], tuple)
    assert histories[1].context.check_events[0]["unrecorded"]["after"] == after


def test_R01_point_rates_stop_explicitly_outside_initial_certifier():
    f = root(world=c1_world(declaration=reduction_declaration("point-rates")))
    before = ledger_image(f.w.ledger)
    with pytest.raises(rate.RateIncomplete) as caught:
        plan(f.view, CANDIDATES, u=U, rate_budget=f.budget)
    assert caught.value.reason == "rate_prior_scope"
    assert ledger_image(f.w.ledger) == before


def test_T14_store_preserves_model_bytes_facts_posterior_and_replay(tmp_path):
    f = saved()
    w = f.w
    expected, original = ledger_image(w.ledger), posterior(f)
    memory = MemoryModels()
    assert memory.put(f.model) == model_ref(f.model)
    assert model_json(memory.get(model_ref(f.model))) == w.declaration
    source = tmp_path/"source"
    with SqliteStore.open(source, create=True) as store:
        ref = store.models.put(f.model)
        for entry in w.ledger.entries():
            salt, payload = w.ledger.contents.get(entry.seal)
            store.contents.put(entry.seal, salt, payload)
            store.entries.add(entry.cid, entry.header)
    with SqliteStore.open(source, readonly=True) as store:
        ledger = Ledger(salts=SequentialSalts(), entries=store.entries, contents=store.contents)
        ledger.verify()
        assert ledger_image(ledger) == expected
        model = store.models.get(ref)
        assert model_json(model) == w.declaration and model_ref(model) == model_ref(f.model)
        restored = Agent.restore(model=model, lineage="backup", ledger=ledger,
            belief=ledger.entries_of(f.belief.id)[0].cid, rate_budget=INJECTED)
        view = restored.view(now_ns=NS, observed_ns=NS, check_events=f.view.check_events)
        assert posterior(f, view.reading) == original
        assert verify(f, ledger=ledger) == f.draft


def refinement_record(f, values, certificate):
    return make_record(f.w.clock, f.w.ids, RefKind.PREDICTION,
        Prediction(target="decision_refinement", about=(f.prepared.decided.id,),
            basis=(f.prepared.decided.id,), contract=RATE_REFINEMENT,
            content=Payload.json({"decision": f.cid, "problem_key": certificate["problem_key"],
                                 "values": values, "certificate": certificate})), writer=Role.MODEL)


def test_T15_M21_valid_narrower_refinement_is_derived_and_keeps_original_decision():
    f = saved()
    before, original = ledger_image(f.w.ledger), posterior(f)
    all_records = tuple(f.w.ledger.record(e.cid) for e in f.w.ledger.entries())
    direct_before = rate_entry.read_rate(f.model, all_records)
    history_before = rate_entry.rate_history(f.model, direct_before, context=f.w.context)
    # Request diagnostic precision with no u. Public selection stops as soon
    # as the original u is certified, even when given a larger budget (R1).
    # Only numerical values/proof enter the refinement, never a new decision.
    finer = refinement_content(rate.evaluate_rate(
        f.view, CANDIDATES, f.resolved, budget=LARGER))
    old = f.draft.content.as_json()
    assert finer["certificate"]["problem_key"] == old["certificate"]["problem_key"]
    coarse = old["values"][0]["q_star"]["bounds"]
    narrow = finer["values"][0]["q_star"]["bounds"]
    lo, hi = F(*coarse["lower"]), F(*coarse["upper"])
    a, b = F(*narrow["lower"]), F(*narrow["upper"])
    assert lo <= a <= b <= hi and b-a < hi-lo
    refinement = refinement_record(f, finer["values"], finer["certificate"])
    entry = f.w.ledger.append(refinement, f.w.ledger.heads())
    rate_entry.verify_rate_refinement(model=f.model, ledger=f.w.ledger,
                                     refinement=entry.cid, budget=LARGER)
    # Bypass snapshot filtering: read_rate itself must exclude derived evidence
    # (§3-10-8), even when its caller supplies every physical ledger record.
    all_records = tuple(f.w.ledger.record(e.cid) for e in f.w.ledger.entries())
    assert refinement in all_records
    direct_after = rate_entry.read_rate(f.model, all_records)
    assert direct_after.rate_records == direct_before.rate_records
    history_after = rate_entry.rate_history(f.model, direct_after, context=f.w.context)
    assert history_after.fact_ids == history_before.fact_ids
    assert history_after.evidence_key == history_before.evidence_key
    assert posterior(f, direct_after) == posterior(f, direct_before)
    f.agent.adopt(f.w.ledger, clock=f.w.clock, ids=f.w.ids)
    view = f.agent.view(now_ns=NS, observed_ns=NS, check_events=f.view.check_events)
    assert refinement.id not in {r.id for r in view.reading.rate_records}
    assert posterior(f, view.reading) == original
    assert verify(f) == f.draft
    assert_extension(f.w.ledger, before)
    decisions = {record.id: record for e in f.w.ledger.entries()
                 if e.body_type in (Decided, JobOpened)
                 for record in (f.w.ledger.record(e.cid),)}
    assert decisions == {f.prepared.decided.id: f.prepared.decided,
                         f.prepared.job.id: f.prepared.job}


def test_T15_nonintersecting_refinement_is_a_mismatch():
    f = saved()
    data = f.draft.content.as_json()
    values = deepcopy(data["values"])
    assert F(1, 3) < F(*values[0]["q_star"]["bounds"]["lower"])
    values[0]["q_star"]["bounds"] = {"lower": [1, 4], "upper": [1, 3]}
    entry = f.w.ledger.append(refinement_record(f, values, data["certificate"]), f.w.ledger.heads())
    before = ledger_image(f.w.ledger)
    with pytest.raises(rate.RateReplayMismatch) as caught:
        rate_entry.verify_rate_refinement(model=f.model, ledger=f.w.ledger,
                                         refinement=entry.cid, budget=INJECTED)
    assert "interval" in caught.value.fields
    assert ledger_image(f.w.ledger) == before
