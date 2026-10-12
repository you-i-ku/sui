"""Independent relation tests, current contract only; no implementation source.

Run this new file only, --tb=no -n 2 (or fewer). Public diagnostics are captured
without tracebacks. Fixture construction uses Record/Payload/Ledger.append.
Each inventory relation has an independent legal and single-fault item.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sui import f, f_facts as ff, f_contracts as fc, f_entry as codec
from sui.clock import Instant
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind
from sui.records import (Record, Payload, Observed, Decided, JobOpened,
    AttemptStarted, Prediction, Interpretation, Preference, Intention, IntentionStatus, Role)
from gate_f_facts_cases import (FactsCase, Reader, BUDGET, PRODUCER, SECOND,
    finite_world, add_observations, add_draw, plain, canonical, auth_copy_primary,
    assemble_limit, prepare, histories)
from gate_f_auth_inventory import (NEW_RELATION_PAIRS, FIELD_TARGETS, BODY_FIELDS,
    FINITE, relation_counts, relation_surfaces, relation_bad_outcome, relation_rules,
    INDEPENDENT_RELATIONS, SURVIVOR_RELATION_PAIRS, SURVIVOR_EXCLUSIONS)
import test_gate_f_auth as old


UNKNOWN = ContractRef("auth.relation.unknown", "1")
EMPTY = Payload.json({})
BODY_META = {
    "Observed": (RefKind.OBSERVATION, Role.MEMBRANE),
    "Decided": (RefKind.DECISION, Role.MODEL),
    "JobOpened": (RefKind.JOB, Role.MODEL),
    "AttemptStarted": (RefKind.ATTEMPT, Role.MEMBRANE),
    "Intention": (RefKind.INTENTION, Role.MODEL),
    "Prediction": (RefKind.PREDICTION, Role.MODEL),
    "Interpretation": (RefKind.INTERPRETATION, Role.INTERPRETER),
    "Preference": (RefKind.PREFERENCE, Role.MODEL),
}


def put(case, key, body, *, parents=None, at=None):
    kind, writer = BODY_META[type(body).__name__]
    record = Record(id=case.ids.new(kind), at=case.clock.now() if at is None else at,
                    writer=writer, producer=PRODUCER, body=body)
    entry = case.ledger.append(record, case.ledger.heads() if parents is None else frozenset(parents))
    case.points[key] = entry.cid
    return entry.cid


def body(case, name, *, decision=None, job=None):
    common = dict(content=EMPTY, contract=UNKNOWN)
    if name == "Observed": return Observed(route="auth", received_ns=case.clock.mono_ns(), **common)
    if name == "Decided": return Decided(inputs=(), **common)
    if name == "JobOpened": return JobOpened(decision=case.ref(decision), step=0, **common)
    if name == "AttemptStarted": return AttemptStarted(job=case.ref(job), **common)
    if name == "Intention":
        return Intention(target=case.clock.run, operation="auth", status=IntentionStatus.CONFIRMED,
                         decided_in=case.ref(decision), **common)
    if name == "Prediction": return Prediction(target="future", about=(), basis=(), **common)
    if name == "Interpretation": return Interpretation(about=(), basis=(), **common)
    return Preference(basis=(), **common)


def finish(case, entry, *, explicit=(), events=()):
    """Make subjects reachable without treating a Prediction as an event parent."""
    if entry != "EL":
        case.context(events=events)
    else:
        declaration = assemble_limit()
        case.predict("limit", fc.LIMIT_DECLARATION,
            declaration.ledger.record(declaration.points["limit"]).body.content.as_json(),
            basis=tuple(explicit))
        old.refresh(case)
    if entry == "EP": old.add_predicate(case)
    case.fixed_parents = tuple(sorted(set((*case.fixed_parents, *explicit))))
    return case


def parent_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC", "EB") else "EN")
    name, column = pair.variant.split(".")
    decision = put(case, "support-decision", body(case, "Decided"))
    job = put(case, "support-job", body(case, "JobOpened", decision=decision))
    case.clock.advance(100)
    parent = put(case, "relation-parent", body(case, "Observed"))
    parent_at = case.ledger.record(parent).at
    child_at = case.clock.now()
    child_at = replace(child_at, mono_ns=parent_at.mono_ns)
    if bad:
        child_at = replace(child_at, **{column: {"mono_ns": parent_at.mono_ns-1,
            "seq": parent_at.seq, "run_index": parent_at.run_index+1}[column]})
    child_body = body(case, name, decision=decision, job=job)
    if name == "Observed": child_body = replace(child_body, received_ns=parent_at.mono_ns-1)
    if name == "Preference" and entry in ("EN", "EB"):
        # Preference selection needs a declared style. The unknown-contract
        # Body is independently covered at the other seven entrances.
        child_body = Preference(basis=(), content=Payload.json(
            {"kind":"style","H_ns":None,"gamma":1.0} if entry=="EB" else
            {"kind":"style","scope":{"name":"unbounded_total","version":"1","H_ns":None},"gamma":[1,1]}),
            contract=ContractRef("sui.s4d.preference","1") if entry=="EB" else fc.STYLE)
    child = put(case, "relation-child", child_body,
                parents=case.ledger.heads(), at=child_at)
    if name == "Preference" and entry in ("EN", "EB"):
        case.preferences.append(child)
        if entry=="EN": case.scope=replace(case.scope,source=case.ref(child))
    return finish(case, entry, explicit=(child,))


def body_use_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC", "EB") else "EN")
    decision = put(case, "support-decision", body(case, "Decided"))
    job = put(case, "support-job", body(case, "JobOpened", decision=decision))
    attempt = put(case, "support-attempt", body(case, "AttemptStarted", job=job))
    confirmed = put(case, "support-intention", body(case, "Intention", decision=decision))
    before = case.ledger.heads()
    name, field = pair.variant.split(".")
    target_name = {"inputs": "Observed", "basis": "Observed", "decision": "Decided", "job": "JobOpened",
                   "caused_by": "AttemptStarted", "decided_in": "Decided",
                   "supersedes": "Intention", "via": "AttemptStarted"}[field]
    target = put(case, "relation-target", body(case, target_name, decision=decision, job=job))
    consumer = body(case, name, decision=decision, job=job)
    if name=="Preference" and entry in ("EN","EB"):
        consumer=Preference(basis=(),content=Payload.json(
            {"kind":"style","H_ns":None,"gamma":1.0} if entry=="EB" else
            {"kind":"style","scope":{"name":"unbounded_total","version":"1","H_ns":None},"gamma":[1,1]}),
            contract=ContractRef("sui.s4d.preference","1") if entry=="EB" else fc.STYLE)
    updates = {field: (case.ref(target),) if field in ("inputs","basis") else case.ref(target)}
    if field == "supersedes": updates["status"] = IntentionStatus.WITHDRAWN
    if field == "via": updates.update(status=IntentionStatus.EXECUTED, supersedes=case.ref(confirmed))
    consumer = replace(consumer, **updates)
    used = put(case, "relation-use", consumer, parents=before if bad else case.ledger.heads())
    if name=="Preference" and entry in ("EN","EB"):
        case.preferences.append(used)
        if entry=="EN":case.scope=replace(case.scope,source=case.ref(used))
    # Joining both branches later must not retroactively authorize the use.
    return finish(case, entry, explicit=(target, used))


def leaf_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC", "EB") else "EN")
    leaf_name, form = pair.variant.split(".")
    parents = case.ledger.heads()
    target = put(case, "relation-target", body(case, "Observed"), parents=parents)
    leaf_parents = parents if bad or form == "describes" else case.ledger.heads()
    leaf_body = body(case, leaf_name)
    # Describes is a control: the sole change is about -> basis; no causality
    # is invented from a description in the legal member (A-03).
    leaf_body = replace(leaf_body, **{
        "about" if form == "describes" and not bad else "basis": (case.ref(target),)})
    leaf = put(case, "relation-leaf", leaf_body, parents=leaf_parents)
    if form == "nested":
        other = "Interpretation" if leaf_name == "Prediction" else "Prediction"
        leaf = put(case, "relation-leaf2", replace(body(case, other), basis=(case.ref(leaf),)), parents=leaf_parents)
    consumer_parents = parents if bad or form == "describes" else case.ledger.heads()
    used = put(case, "relation-use", Decided(inputs=(case.ref(leaf),), content=EMPTY,
                                              contract=UNKNOWN), parents=consumer_parents)
    return finish(case, entry, explicit=(target, leaf, used))


def computation(case, label, *, stage, observations=None, extra_inputs=(), joint=(Q(3,4), Q(1,4)),
                mass=Q(1,2), target="result", acquisition_ns=None, wrong_outer=False,
                separate_acquisition=False):
    """Independent, stoppable primary calculation. No later completion is in C.

    Stages: generated = result plus completion, no proof/acquisition;
    acquired = target acquired, no adoption; verified = proof present/acquired;
    adopted = verified and adopted. Proof targets necessarily include a proof.
    """
    inputs = tuple(dict.fromkeys((case.points["origin"], case.points["model"], case.points["boot"],
        case.points["clock_source"], case.points["route"], *case.plans, *case.raw, *case.bindings,
        *(p for k,p in case.points.items() if k.startswith(("measure-request", "measure-job", "measure-attempt"))),
        *extra_inputs)))
    started = case.reading(label+"-start")
    finished = case.reading(label+"-finish")
    request = case.decide(label+"-request", fc.COMPUTATION_REQUESTED,
        dict(origin=case.points["origin"], purpose="belief", method=plain(fc.FINITE_UPDATE),
             args=dict(model=case.points["model"], previous_result=None,
                       observations=list(case.bindings if observations is None else observations)),
             inputs=list(inputs), algorithm_draws=[], output_contract=plain(fc.FINITE_UPDATE_RESULT)),
        inputs=inputs[1:] if wrong_outer else inputs)
    result = case.predict(label+"-result", fc.COMPUTATION_RESULT,
        dict(request=request, output=dict(contract=plain(fc.FINITE_UPDATE_RESULT),
             value=dict(joint=plain(joint), evidence_mass=plain(mass)))),
        about=(request,), basis=(request, *inputs))
    proof = None
    if stage in ("verified", "adopted") or target == "proof":
        proof = case.predict(label+"-proof", fc.COMPUTATION_PROOF,
            dict(request=request, result=result, role="normalization",
                 statement=dict(contract=plain(fc.FINITE_UPDATE_STATEMENT),
                                value=dict(model=case.points["model"], request=request, result=result)),
                 checker=dict(name=fc.FINITE_UPDATE_REPLAY.name, version="1", args={})),
            about=(request,result), basis=(case.points["model"],request,result))
    completed = case.observe(label+"-completed", fc.COMPUTATION_COMPLETED,
        dict(request=request, result=result, proofs=[] if proof is None else [proof],
             started_clock=started, finished_clock=finished))
    acquired = None
    if stage != "generated":
        selected = ((proof,) if target=="proof" else (result,)) if separate_acquisition else (
            (proof,) if target == "proof" and stage == "acquired" else (result,) if proof is None else (result,proof))
        acquired = case.acquire(selected, clock=case.reading(label+"-acquisition-clock", acquisition_ns))
        case.points[label+"-acquired"] = acquired
        if separate_acquisition and stage in ("verified","adopted") and proof is not None:
            # Isolate exactly one target's g <= a relation. The companion
            # result/proof has its own legal acquisition clock at g.
            case.acquire((result if target=="proof" else proof,))
    if stage == "adopted":
        case.decide(label+"-adopted", fc.KNOWLEDGE_ADOPTED,
            dict(origin=case.points["origin"], previous=None, completion=completed),
            inputs=(case.points["origin"], completed))
    return dict(request=request, result=result, proof=proof, completed=completed, acquired=acquired)


def calculation_base(name, seqs=(1,)):
    case = FactsCase(finite_world("FA06")[0], name=name)
    add_observations(case, seqs=seqs)
    case.acquire(case.raw)
    case.candidate(("Compute",))
    return case


def witness_case(pair, entry, bad):
    case = calculation_base("rel-witness")
    target, form = pair.variant.split(".")
    # All times still satisfy storage/real-parent rules. Only g <= a differs.
    case.clock.advance(10)
    acquisition = case.clock.mono_ns() - int(bad)
    first = computation(case, "first", stage=pair.stage, target=target, acquisition_ns=acquisition,
                        separate_acquisition=True)
    case.clock.advance(10)
    extra = () if form == "unrelated" else (first["acquired"],)
    second = computation(case, "second", stage="generated", extra_inputs=extra)
    if form == "three_calculations":
        # A second acquired notice is also a legitimate input to a third job.
        notice = case.acquire((second["result"],))
        case.clock.advance(10)
        computation(case, "third", stage="generated", extra_inputs=(first["acquired"], notice))
    return finish(case, entry)


def generation_case(pair, entry, bad):
    branch = pair.variant
    if branch in ("gap", "closed", "no_arrival"):
        case = old.coverage_case("gap" if branch == "gap" else "claim")
        if branch == "no_arrival":
            case = FactsCase(finite_world("FA02")[0], name="rel-window")
            add_observations(case, closed=False)
            case.candidate(("Open", "Closed")); case.context()
        report = branch == "gap"
        def edit(key, record):
            if key.startswith(("measure-request", "measure-job", "measure-attempt")):
                record = replace(record, at=replace(record.at, mono_ns=3*SECOND//2 if report else int(bad)))
            if key in ("raw-0", "auth-coverage", "binding-0", "context", "observed_clock", "judgment_clock"):
                record = replace(record, at=replace(record.at, mono_ns=2*SECOND),
                                 body=replace(record.body, received_ns=2*SECOND))
                if key in ("observed_clock", "judgment_clock"):
                    value = deepcopy(record.body.content.as_json()); value["reading"]["time_ns"] = 2*SECOND
                    record = replace(record, body=replace(record.body, content=Payload.json(value)))
            if report and bad and key in ("raw-0", "auth-coverage"):
                record = replace(record, body=replace(record.body, received_ns=3*SECOND//2-1))
            return record
        # Keep declaration storage after the new event times too (A-05).
        def timed(key, record):
            r = edit(key, record)
            if key == "candidates": r = replace(r, at=replace(r.at, mono_ns=2*SECOND))
            return r
        case=auth_copy_primary(case, edit=timed)
        case.clock.advance(2*SECOND-case.clock.mono_ns())
        return finish(case,entry)
    case = calculation_base("rel-report")
    case.clock.advance(SECOND//2)
    decision = put(case, "report-request", body(case, "Decided"))
    job = put(case, "report-job", body(case, "JobOpened", decision=decision))
    attempt = put(case, "report-attempt", body(case, "AttemptStarted", job=job))
    caused_at = case.clock.mono_ns()
    case.clock.advance(SECOND//2)
    interval = dict(clock=str(case.clock.run), start_ns=0,
                    end_ns=3*SECOND if branch == "coverage_unproved" else SECOND, closure="(start,end]")
    value = dict(route_epoch="route-1", evidence=[])
    if branch == "measurement_unavailable": value.update(requested_interval=interval, reason="unavailable")
    else: value.update(interval=interval, missing_contracts=[])
    put(case, "report", Observed(route="route-1", contract=fc.COVERAGE,
        content=Payload.json(dict(kind=branch, value=value)), caused_by=case.ref(attempt),
        received_ns=caused_at-1 if bad else case.clock.mono_ns()))
    return finish(case, entry)


def closed_window_receipt_case(pair, entry, bad):
    """A-14: change only the completed window's end relative to its receipt.

    Both members retain the real Attempt at start=0, authentic evidence,
    Binding, and start <= end. No future CoverageUnproved window is converted
    to a completion claim. The negative changes exactly one payload scalar.
    """
    case = old.coverage_case(pair.variant)
    original = case.ledger.record(case.points["auth-coverage"])
    value = original.body.content.as_json()["value"]
    interval = value["interval"]
    attempt = case.ledger.record(case.points["measure-attempt-1"])
    receipt = original.body.received_ns
    assert attempt.at.mono_ns <= interval["start_ns"] <= interval["end_ns"] == receipt
    def edit(key, record):
        if record.id != original.id:
            return record
        payload = deepcopy(record.body.content.as_json())
        payload["value"]["interval"]["end_ns"] = receipt + int(bad)
        return replace(record, body=replace(record.body, content=Payload.json(payload)))
    case = auth_copy_primary(case, edit=edit)
    changed = case.ledger.record(case.points["auth-coverage"])
    expected = deepcopy(original.body.content.as_json())
    expected["value"]["interval"]["end_ns"] += int(bad)
    assert changed == replace(original, body=replace(original.body, content=Payload.json(expected)))
    return finish(case, entry)


def sequence_case(pair, entry, bad):
    form = pair.variant
    seqs = (1,1) if form == "redelivery" else (1,2) if form == "distinct_measurement" else (1,)
    case = calculation_base("rel-sequence", seqs)
    obs = tuple(case.bindings)
    if form == "binding_repeat": obs = (obs[0], obs[0])
    # From the declared diagonal likelihoods (3/4,1/4) and fair prior:
    # one distinct measurement -> (3/4,1/4), Z=1/2;
    # two distinct measurements -> (9/10,1/10), Z=5/16.
    twice = form == "distinct_measurement"
    if bad: twice = not twice
    calculation = computation(case, "sequence", stage=pair.stage, observations=obs,
        joint=(Q(9,10), Q(1,10)) if twice else (Q(3,4), Q(1,4)),
        mass=Q(5,16) if twice else Q(1,2))
    case.expected_joint = (Q(9,10),Q(1,10)) if form == "distinct_measurement" else (Q(3,4),Q(1,4))
    if form == "input_permutation":
        case = auth_copy_primary(case, edit=lambda k,r:
            old.content(r, inputs=list(reversed(r.body.content.as_json()["inputs"])))
            if k == "sequence-request" else r)
    return finish(case, entry)


def order_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC", "EB") else "EN")
    form = pair.variant
    parents = case.ledger.heads()
    if form == "clocks":
        a = case.reading("order-a"); b = case.reading("order-b")
        events = [("clock",a),("clock",b)]
    elif form == "mixed":
        a = put(case,"order-a",body(case,"Observed")); b=case.reading("order-b")
        events = [("fact",a),("clock",b)]
    else:
        a = put(case,"order-a",body(case,"Observed"))
        b = put(case,"order-b",body(case,"Observed"), parents=parents if form == "siblings_control" and not bad else None)
        events = [("fact",a),("fact",b)]
    if bad or form == "siblings_control": events.reverse()
    if form == "interleaved":
        c=case.reading("order-c"); events.insert(1,("clock",c))
        # c is independent of the two checks for ordering purposes only when
        # it precedes neither checked fact. Keep it last in the legal ordering.
        if not bad: events=[("fact",a),("fact",b),("clock",c)]
    case.expected_events = tuple(events)
    if entry=="EL": case.context(events=events)
    return finish(case, entry, events=events)


def boundary_case(pair, entry, bad):
    case = calculation_base("rel-boundary")
    computation(case,"boundary",stage=pair.stage,wrong_outer=bad)
    return finish(case,entry)


def survivor_generation_case(pair, entry, bad):
    """Raw cause/measured discriminator for survivor #1.

    The sole measurement is inside (0,1s], stored/received at 1s. Distinct
    Attempts have independently consistent Job/request chains. Checks 2-4
    remain in the inventory as N/A: F-a's opportunity must be a generator.
    """
    assert pair.variant == "measured_generated" and not pair.not_applicable
    document = finite_world("FA06")[0]
    material = FactsCase(document,name="survivor-generation")
    add_observations(material)
    case = FactsCase(document,name="survivor-generation")
    def payload(key):
        return deepcopy(material.ledger.record(material.points[key]).body.content.as_json())
    case.observe("route",fc.ROUTE_CONFIG,payload("route"))
    plan = case.predict("plan",fc.OBSERVATION_PLAN,payload("plan"),basis=(case.points["model"],))
    case.plans.append(plan)
    other = case.predict("other-plan",fc.OBSERVATION_PLAN,payload("plan"),basis=(case.points["model"],))
    def chain(label,plan_point,step,time_ns):
        case.clock.advance(time_ns-case.clock.mono_ns())
        decision = case.decide(label+"-request",fc.MEASUREMENT_REQUESTED,
            dict(plan=plan_point,step=step),inputs=(plan_point,))
        job = put(case,label+"-job",JobOpened(decision=case.ref(decision),step=step,
            content=Payload.json(dict(plan=plan_point,step=step)),contract=fc.MEASUREMENT_JOB))
        return put(case,label+"-attempt",AttemptStarted(job=case.ref(job),content=EMPTY,
            contract=ContractRef("sui.s1.attempt","1")))
    opportunity = chain("opportunity",plan,0,0)
    generated = chain("generated",plan,0,3*SECOND//4)
    measured = SECOND//2 if bad else 3*SECOND//4
    case.clock.advance(SECOND-case.clock.mono_ns())
    raw_value = payload("raw-0")
    raw_value["actual_time"]["value"]["time_ns"] = measured
    raw = case.observe("raw-0",fc.MEASUREMENT,raw_value,route="route-1",source_id="delivery-0",
        caused_by=case.ref(generated))
    if entry not in ("EN","EH","EP"):
        # No Binding: the raw MeasurementFrame's own cause/measured edge is
        # the only target, so an opportunity check cannot duplicate it.
        case.raw.append(raw)
        case.candidate(("Compute",))
        return finish(case,entry)
    binding = payload("binding-0")
    binding.update(plan=str(case.ref(plan)),records=[str(case.ref(raw))],
        opportunity=str(case.ref(generated)),
        generated_by=[str(case.ref(generated))])
    bound = case.observe("binding-0",fc.OBSERVATION_BINDING,binding,
        caused_by=case.ref(generated))
    case.raw.append(raw);case.bindings.append(bound)
    case.candidate(("Compute",))
    assert opportunity != generated
    return finish(case,entry)


def cause_receipt_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC","EB") else "EN")
    case.clock.advance(10)
    decision = put(case,"cause-request",body(case,"Decided"))
    job = put(case,"cause-job",body(case,"JobOpened",decision=decision))
    cause = put(case,"cause-attempt",body(case,"AttemptStarted",job=job))
    attempt_ns = case.clock.mono_ns()
    case.clock.advance(10)
    notice = put(case,"cause-notice",Observed(route="unknown",contract=UNKNOWN,content=EMPTY,
        caused_by=case.ref(cause),received_ns=attempt_ns-int(bad)))
    assert case.ledger.record(cause).at.mono_ns < case.ledger.record(notice).at.mono_ns
    return finish(case,entry)


def sibling_clock_case(pair, entry, bad):
    case = old.base_case(entry if entry in ("EC","EB") else "EN")
    case.clock.advance(10)
    now = case.clock.mono_ns()
    parents = case.ledger.heads()
    def reading(key,value):
        return put(case,key,Observed(route="clock",contract=fc.CLOCK_READING,received_ns=now,
            content=Payload.json(dict(source=case.points["clock_source"],
                reading=dict(run=str(case.clock.run),time_ns=value)))),parents=parents)
    lo = reading("sibling-low",now-2)
    hi = reading("sibling-high",now-1)
    entries = {e.cid:e for e in case.ledger.entries()}
    assert entries[lo].parents == entries[hi].parents
    if pair.variant == "checks_descend":
        events = (("clock",hi),("clock",lo)) if bad else (("clock",lo),("clock",hi))
        case.context(events=events)
    else:
        case.observe("context",fc.CONTEXT_OBSERVED,
            dict(knowledge_origin=case.points["origin"],observation_reading=hi if bad else lo,
                 judgment_reading=lo if bad else hi,check_events=[]))
        old.refresh(case)
    if entry=="EL": return finish(case,entry)
    if entry=="EP": old.add_predicate(case)
    return case


def context_revisit_case(pair, entry, bad):
    """One late receipt, used through a static candidate's generation basis.

    A later event consumer would itself be after j and add a second violation.
    A-11 permits late declaration storage. Local references are descriptions,
    an acquisition by a different origin, or checks in an earlier context.
    The unused origin's late management clock does not enter selected K.
    No private cache state or implementation traversal order is assumed.
    """
    case = FactsCase(finite_world("FA08")[0],name="survivor-context")
    selected_origin = case.points["origin"]
    other_origin = case.observe("other-origin",fc.KNOWLEDGE_ORIGIN,
        dict(model=case.points["model"]))
    case.clock.advance(20)
    case.context(observed_ns=9,judgment_ns=9)
    unknown = put(case,"cache-unknown",Observed(route="unknown",contract=UNKNOWN,content=EMPTY,
        received_ns=10 if bad else 9))
    if pair.variant == "acquired_direct":
        case.points["origin"] = other_origin
        case.acquire((unknown,))
        case.points["origin"] = selected_origin
    else:
        put(case,"cache-description",Prediction(target="description",about=(case.ref(unknown),),
            basis=(),content=EMPTY,contract=UNKNOWN))
    dependency = unknown
    if pair.variant == "owner_leaf":
        dependency = put(case,"cache-owner",Prediction(target="cache-owner",about=(),
            basis=(case.ref(unknown),),content=EMPTY,contract=UNKNOWN))
    if pair.variant == "two_contexts":
        case.context(observed_ns=10,judgment_ns=10,events=(("fact",unknown),))
        case.context(observed_ns=9,judgment_ns=9)
    case.candidate(("Q",))
    def edit(key,record):
        if key != "candidates": return record
        value = deepcopy(record.body.content.as_json())
        value["generation"]["basis"].append(dependency)
        return replace(record,body=replace(record.body,content=Payload.json(value),
            basis=(*record.body.basis,case.ref(dependency))))
    case = auth_copy_primary(case,edit=edit)
    old.refresh(case)
    if entry == "EL": return finish(case,entry)
    if entry == "EP": old.add_predicate(case)
    return case


def typed_point_alias_case(pair, entry, bad):
    """A-04 uses S(Points): equal outer Ref does not authenticate every CID.

    The extra model Record is byte-for-byte identical and non-event. It lives
    outside the actual frontier, reached as an explicit generation.basis Point.
    The negative reader changes only sealed_content for that alias CID.
    """
    case = old.finite_case()
    alternate = old.Ledger(salts=old.SequentialSalts(),contents=old.MemoryContents())
    alias = alternate.append(case.reader.record(case.points["model"]),()).cid
    assert alias != case.points["model"]
    def edit(key,record):
        if key != "candidates": return record
        value=deepcopy(record.body.content.as_json())
        value["generation"]["basis"].append(alias)
        return replace(record,body=replace(record.body,content=Payload.json(value)))
    case=auth_copy_primary(case,edit=edit)
    if entry=="EL": finish(case,entry,explicit=(case.points["candidates"],))
    elif entry=="EP": old.add_predicate(case)
    case.fixed_parents=tuple(sorted(set((*case.fixed_parents,case.points["candidates"]))))
    case.alias_good_reader=Reader(alternate)
    case.alias_reader=old.FaultReader(alternate,alias,"seal") if bad else case.alias_good_reader
    case.reader=old.Review4CombinedReader(case.reader,case.alias_reader)
    assert case.reader.record(alias)==case.ledger.record(case.points["model"])
    assert alias not in case.ledger.ancestors(case.fixed_parents)
    assert case.ref(case.points["model"]) in case.ledger.record(case.points["candidates"]).body.basis
    return case


BUILDERS = dict(parent_child=parent_case, body_use=body_use_case, leaf_use=leaf_case,
    target_witness=witness_case, generation_class=generation_case,
    closed_window_receipt=closed_window_receipt_case,
    sequence_set=sequence_case, check_order=order_case, stage_boundary=boundary_case,
    survivor_generation=survivor_generation_case,cause_receipt=cause_receipt_case,
    sibling_clock=sibling_clock_case,context_revisit=context_revisit_case,
    typed_point_alias=typed_point_alias_case)


def draw_subject(subject, *, evaluate=False, replay_root=False, bad=False):
    """A separate run keeps its own BOOT and ClockSource in the draw closure."""
    # A deterministic, terminating idle option needs no unacquired m or
    # numerical query. This control can actually reach Selected at ED.
    prefix=FactsCase(finite_world("FA08")[0],name="rel-draw-prefix")
    prefix.candidate(("Q",));prefix.context()
    prepared=prepare(prefix)
    assert isinstance(prepared.value,f.FProblem),old.diagnostic(prepared,None)
    seed=None
    if replay_root and bad and not hasattr(subject,"alias_reader"):
        seed_draw=add_draw(prefix,prepared.value.problem_key)
        seed=ff.bind_f_draw(prepared,seed_draw,reader=prefix.reader,budget=BUDGET)
    old.append_independent_primary_closure(prefix,subject,next(iter(subject.points)))
    if hasattr(subject,"alias_reader"):
        prefix.reader=old.Review4CombinedReader(prefix.reader,subject.alias_reader)
    # Authenticate leaves too, via a real event with all event ancestors.
    by_ref={str(prefix.ledger.record(e.cid).id):e.cid for e in prefix.ledger.entries()}
    points=tuple(by_ref[str(subject.ref(p))] for p in subject.fixed_parents)
    now=max(prefix.clock.mono_ns(),*(subject.ledger.record(e.cid).at.mono_ns for e in subject.ledger.entries()))+1
    prefix.clock.advance(now-prefix.clock.mono_ns())
    # The actual consumer lives in the subject's run. A prefix-run consumer
    # would invent a comparison of two unrelated monotonic clock domains.
    use_at=Instant(run=subject.clock.run,run_index=0,
        seq=max(subject.ledger.record(e.cid).at.seq for e in subject.ledger.entries())+1,
        mono_ns=now,wall_ns=0)
    put(prefix,"suffix-use",Decided(inputs=tuple(prefix.ref(p) for p in points),
        content=EMPTY,contract=UNKNOWN),at=use_at)
    draw=add_draw(prefix,prepared.value.problem_key)
    if replay_root:
        if hasattr(subject,"alias_reader"):
            # Issue over the same valid graph; the negative differs only in the
            # alias's transport bytes during replay, never in a stale claim.
            legal_reader=old.Review4CombinedReader(Reader(prefix.ledger),subject.alias_good_reader)
            saved=ff.bind_f_draw(prepared,draw,reader=legal_reader,budget=BUDGET).canonical_bytes
        elif bad:
            envelope=json.loads(seed.canonical_bytes)
            for call in envelope["calls"]:
                if call["op"]=="bind_draw": call["args"]["draw"]=draw
            saved=canonical(envelope)
        else:
            saved=ff.bind_f_draw(prepared,draw,reader=prefix.reader,budget=BUDGET).canonical_bytes
        return ff.restore_f_root(saved,reader=prefix.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    function=ff.evaluate_f_from_draw if evaluate else ff.bind_f_draw
    return function(prepared,draw,reader=prefix.reader,budget=BUDGET)


def replay_selected_relation(pair, bad, surface):
    """ER must rebuild selected-origin K before comparing the saved claim.

    E-01:350/352 return EH/EP DTOs, not separate artifact issuers. The EN
    artifact and its bound root exercise their common selected-origin K use.
    Only the targeted primary result or receipt changes; CIDs are regenerated.
    The stale claim is preserved so E-06's first failure is testable.
    """
    case = BUILDERS[pair.kind](pair,"EN",False)
    value,exc = old.call_observed(lambda:prepare(case))
    assert exc is None,"ER not reached: legal EN issuer prerequisite failed: "+str(old.diagnostic(value,exc))
    artifact = value
    assert isinstance(artifact.value,f.FProblem),old.diagnostic(artifact,None)
    if surface == "selected_restore_root":
        draw = add_draw(case,artifact.value.problem_key)
        artifact = ff.bind_f_draw(artifact,draw,reader=case.reader,budget=BUDGET)
        assert isinstance(artifact.value,f.FRoot),old.diagnostic(artifact,None)
    saved = artifact.canonical_bytes
    if bad:
        def edit(key,record):
            if pair.kind=="context_revisit":
                return replace(record,body=replace(record.body,received_ns=10)) if key=="cache-unknown" else record
            if key != "sequence-result": return record
            output = deepcopy(record.body.content.as_json()["output"])
            twice = pair.variant != "distinct_measurement"
            output["value"] = dict(joint=[[9,10],[1,10]] if twice else [[3,4],[1,4]],
                                   evidence_mass=[5,16] if twice else [1,2])
            return old.content(record,output=output)
        case = auth_copy_primary(case,edit=edit)
        def remap(value):
            if isinstance(value,str): return case.auth_point_map.get(value,value)
            if isinstance(value,list): return [remap(x) for x in value]
            if isinstance(value,dict): return {k:remap(v) for k,v in value.items()}
            return value
        envelope = json.loads(saved)
        envelope["input"] = remap(envelope["input"])
        envelope["input"]["value"]["fixed_parents"] = list(case.fixed_parents)
        envelope["calls"] = remap(envelope["calls"])
        saved = canonical(envelope)
    replay = {"selected_restore_math":ff.restore_f_math_result,
              "selected_verify":ff.verify_f_math_result,
              "selected_restore_root":ff.restore_f_root}[surface]
    if pair.kind=="context_revisit":
        local,local_exc=old.call_observed(lambda:old.invoke("EF",case))
        old.assert_legal(local,local_exc,"EF")
    return replay(saved,reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)


def invoke_relation(pair, entry, bad, surface="default"):
    if entry == "ER" and surface.startswith("selected_"):
        return replay_selected_relation(pair,bad,surface)
    independent = entry in ("EC","EB") and pair.kind in INDEPENDENT_RELATIONS
    construction_entry = "EL" if surface.startswith("limit_") else (
        "EN" if entry in ("ED","ER") or independent else entry)
    if pair.mutation_checks==(1,) and entry in ("ED","ER","EC","EB"):
        construction_entry="EF"  # raw-only discriminator; no duplicate opportunity check
    case = BUILDERS[pair.kind](pair,construction_entry,bad)
    if pair.kind=="context_revisit" and entry in ("EN","EH","EP"):
        # Public local authentication really succeeds before the bound entry.
        # This does not claim control of any private cache's visitation order.
        local,local_exc=old.call_observed(lambda:old.invoke("EF",case))
        old.assert_legal(local,local_exc,"EF")
    if independent:
        # Preserve the selected C1/legacy model and origin. A finite calculation
        # in another real branch must receive intrinsic authentication without
        # being converted into the selected model's numerical evidence/K.
        selected=old.base_case(entry)
        old.append_independent_primary_closure(selected,case,next(iter(case.points)))
        if hasattr(case,"alias_reader"):
            selected.reader=old.Review4CombinedReader(selected.reader,case.alias_reader)
            # A non-event declaration is an explicit authentication root here.
            declarations=tuple(e.cid for e in selected.ledger.entries()
                if selected.ledger.record(e.cid).body.contract==fc.CANDIDATE_DECLARATION)
            selected.fixed_parents=tuple(sorted(set((*selected.fixed_parents,*declarations))))
        case=selected
    if entry == "ED": return draw_subject(case,evaluate=surface=="evaluate")
    if entry == "ER":
        if pair.kind=="typed_point_alias":
            if surface=="restore_root": return draw_subject(case,replay_root=True,bad=bad)
            legal=typed_point_alias_case(pair,"EN",False)
            assert legal.fixed_parents==case.fixed_parents
            artifact=old.invoke("EF",legal)
            replay=ff.verify_f_math_result if surface=="verify" else ff.restore_f_math_result
            return replay(artifact.canonical_bytes,reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
        unused_numerical_result = pair.kind in ("sequence_set","context_revisit")
        if surface=="restore_root":
            return draw_subject(case,replay_root=True,bad=bad and not unused_numerical_result)
        replay=ff.verify_f_math_result if surface.endswith("verify") else ff.restore_f_math_result
        if not bad or unused_numerical_result:
            # M-02:267: these issuers do not derive K. An authentic artifact
            # over the wrong unused numeric result must itself be replayable;
            # an unrelated stale claim would add a second fault to this pair.
            artifact = old.invoke("EL" if surface.startswith("limit_") else "EF",case)
            return replay(artifact.canonical_bytes,reader=case.reader,
                                                registry=f.builtin_f_registry(),budget=BUDGET)
        # A fresh, structurally sound envelope with bad primary dependencies.
        # Its stale claim is deliberate: E-06 requires primary auth FIRST.
        seed = old.invoke("EF",old.finite_case())
        envelope = json.loads(seed.canonical_bytes)
        envelope["input"]["value"] = plain(f.FPreflightFacts(fixed_parents=case.fixed_parents,
            model=None, required_records=case.fixed_parents, required_capabilities=()))
        return replay(canonical(envelope),reader=case.reader,
                                       registry=f.builtin_f_registry(),budget=BUDGET)
    return old.invoke(entry,case)


REL_PARAMS = tuple(pytest.param(p,e,s,bad,
    id=f"{p.rules[0]}__{p.id}__{e}.{s}__{'bad' if bad else 'good'}")
    for p in NEW_RELATION_PAIRS if not p.not_applicable for e in p.entries if e not in p.pending_entries
    for s in relation_surfaces(p,e) for bad in (False,True))


@pytest.mark.parametrize("pair,entry,surface,bad",REL_PARAMS)
def test_relation_pair(pair,entry,surface,bad,record_property,monkeypatch):
    record_property("rules",",".join(relation_rules(pair,entry))); record_property("relation",pair.kind)
    record_property("entry",entry); record_property("stage",pair.stage)
    record_property("surface",surface)
    record_property("member","bad" if bad else "good")
    if pair.mutation_checks: record_property("mutation_checks",",".join(map(str,pair.mutation_checks)))
    outcome = relation_bad_outcome(pair,entry,surface) if bad else "accept"
    record_property("expected_outcome",outcome)
    numerical_calls=[]
    if pair.kind in ("stage_boundary","closed_window_receipt") and bad:
        native=f.builtin_f_registry()
        def forbidden(*,args,input,context):
            numerical_calls.append("numerical capability")
            raise AssertionError("C-05: numeric work reached before the malformed primary request was rejected")
        implementations=tuple(replace(i,implementation=forbidden,identity="auth.first-boundary/1")
            if i.kind in ("method","arithmetic","choice") or i.ref==fc.FINITE_UPDATE_REPLAY else i
            for i in native.implementations)
        registry=f.make_f_registry(declarations=native.declarations,implementations=implementations)
        monkeypatch.setattr(f,"builtin_f_registry",lambda:registry)
    value,exc = old.call_observed(lambda: invoke_relation(pair,entry,bad,surface))
    assert numerical_calls==[], "C-05: a registered numerical callback ran"
    if bad and pair.kind=="parent_child" and pair.variant.rsplit(".",1)[1] in ("seq","run_index"):
        # Public Ledger.append enforces this before a facts request can exist.
        # No forged reader is used to bypass that boundary. This is separately
        # labelled construction coverage, never an auth-entrance success.
        record_property("boundary","Ledger.append; facts entry not reached")
        from sui.clock import ClockError
        assert isinstance(exc,ClockError),old.diagnostic(value,exc)
    elif bad and outcome != "accept": old.assert_bad(value,exc,pair,entry)
    elif entry=="ED" and surface=="evaluate":
        assert exc is None,old.diagnostic(value,exc)
        assert isinstance(value.value,f.Selected),old.diagnostic(value,exc)
    else: old.assert_legal(value,exc,entry)
    if not bad and entry=="EH" and pair.kind in ("sequence_set","stage_boundary"):
        n=2 if pair.variant=="distinct_measurement" else 1
        assert len(value.K.available)==n
        assert len(value.K.incorporated)==(n if pair.stage=="adopted" else 0)
        assert (value.K.belief is not None)==(pair.stage=="adopted")
        assert not value.K.query_proofs, "A-04:166: F-a publishes no query proof semantics"
        if pair.stage in ("generated","acquired","verified"):
            assert value.K.pending, "stopping before adoption must preserve pending work"


def test_relation_inventory_has_separate_rows_and_complete_parameter_pairs():
    assert set(BUILDERS) == {p.kind for p in NEW_RELATION_PAIRS}
    assert len({p.id for p in NEW_RELATION_PAIRS}) == len(NEW_RELATION_PAIRS)
    expected = {(p.id,e,s,b) for p in NEW_RELATION_PAIRS if not p.not_applicable for e in p.entries if e not in p.pending_entries
                for s in relation_surfaces(p,e) for b in (False,True)}
    assert {(p.values[0].id,p.values[1],p.values[2],p.values[3]) for p in REL_PARAMS} == expected
    assert not any(p.pending_entries for p in NEW_RELATION_PAIRS)
    excluded = [p for p in NEW_RELATION_PAIRS if p.not_applicable]
    assert {p.mutation_checks for p in excluded} == {(2,),(3,),(4,)}
    assert sum(len(p.entries) for p in excluded) == 27
    assert {n for p in SURVIVOR_RELATION_PAIRS for n in p.mutation_checks} | {x[0] for x in SURVIVOR_EXCLUSIONS} == set(range(1,13))
    assert all(len(relation_rules(p,e))==len(set(relation_rules(p,e))) for p in NEW_RELATION_PAIRS for e in p.entries)
    assert sum(e in ("EC","EB") for p in NEW_RELATION_PAIRS if p.kind in ("target_witness","generation_class","sequence_set","stage_boundary")
               for e in p.entries)==86
    assert relation_counts()["row_kinds"]["field"] == 686
    report = old.coverage_report()
    query = [d for d in report["dispositions"] if d["target"] in {r.id for r in QUERY_ROWS}]
    assert len(query) == 54 and all(d["status"] == "not_applicable" for d in query)
    assert not report["unexpanded_field_entries"], report["unexpanded_field_entries"]
    assert not report["unexpanded_relation_entries"], report["unexpanded_relation_entries"]


BOOT_ROW=next(r for r in FIELD_TARGETS if r.contract=="sui.s4.boot" and r.field=="$contract")
QUERY_ROWS=tuple(r for r in FIELD_TARGETS if r.contract=="sui.f.computation_proof" and r.branch=="query")


@pytest.mark.parametrize("row,entry",tuple(pytest.param(r,e,id=r.field+"__"+e)
    for r in QUERY_ROWS for e in r.entries))
def test_query_missing_field_at_auth_boundary(row,entry,record_property):
    """Required-key negatives remain applicable; query success is outside F-a.

    A-04:166 explicitly publishes no query statement/checker in this slice.
    A-20 still unambiguously requires every outer schema key at every entrance.
    These 54 negatives do NOT count as query authentication-success examples;
    those 54 obligations stay in the inventory as not_applicable, not pending.
    """
    record_property("rules","A-20,A-21");record_property("relation","query_presence_negative_only")
    record_property("entry",entry);record_property("target",row.id)
    record_property("member","bad; query success outside F-a")
    request_row=next(r for r in FIELD_TARGETS if r.contract=="sui.f.computation_requested" and r.branch=="query")
    case,key=old.extra_specimen(request_row,"EF")
    request=case.points[key]
    inputs=case.ledger.record(request).body.content.as_json()["inputs"]
    result=case.predict("query-result",fc.COMPUTATION_RESULT,
        dict(request=request,output=dict(contract=plain(fc.FINITE_UPDATE_RESULT),
             value=dict(joint=[[3,4],[1,4]],evidence_mass=[1,2]))),about=(request,),basis=(request,*inputs))
    value=dict(request=request,result=result,role="query",
        statement=dict(contract=dict(name="auth.query_statement.unspecified",version="1"),value={}),
        checker=dict(name="auth.query_checker.unspecified",version="1",args={}))
    old.remove_field(value,row.field)
    proof=case.predict("query-proof",fc.COMPUTATION_PROOF,value,about=(request,result),basis=(request,result))
    finish(case,"EP" if entry=="EP" else "EN",explicit=(proof,))
    def run():
        if entry=="ED":return draw_subject(case)
        if entry=="ER":
            seed=old.invoke("EF",old.finite_case())
            envelope=json.loads(seed.canonical_bytes)
            envelope["input"]["value"]=plain(f.FPreflightFacts(fixed_parents=case.fixed_parents,
                model=None,required_records=case.fixed_parents,required_capabilities=()))
            return ff.restore_f_math_result(canonical(envelope),reader=case.reader,
                                           registry=f.builtin_f_registry(),budget=BUDGET)
        return old.invoke(entry,case)
    got,exc=old.call_observed(run)
    assert old.diagnostic(got,exc)[:2]==("FInputError","shape"),old.diagnostic(got,exc)
    old.assert_pointer(getattr(exc,"field",None),getattr(exc,"fields",()))


@pytest.mark.parametrize("bad",(False,True))
@pytest.mark.parametrize("surface",("bind","evaluate"))
def test_boot_contract_in_draw_added_closure(bad,surface,record_property):
    record_property("rules","V-08,A-19,E-02");record_property("relation","unexpanded_boot")
    record_property("entry","ED");record_property("target",BOOT_ROW.id)
    record_property("member","bad" if bad else "good")
    case=old.finite_case()
    if bad:
        case=auth_copy_primary(case,edit=lambda k,r:replace(r,body=replace(r.body,
            contract=ContractRef("sui.s4.boot","999"))) if k=="boot" else r)
    value,exc=old.call_observed(lambda:draw_subject(case,evaluate=surface=="evaluate"))
    if bad: assert old.diagnostic(value,exc)[:2]==("FInputError","unknown_version"),old.diagnostic(value,exc)
    elif surface=="bind":old.assert_legal(value,exc,"ED")
    else:
        assert exc is None,old.diagnostic(value,exc)
        assert isinstance(value.value,f.Selected),old.diagnostic(value,exc)


IDENTITY_CHILD = r'''
import json, sys
from dataclasses import replace
from sui import f, f_facts as ff
from gate_f_facts_cases import BareFactsCase, BUDGET
identity, order = sys.argv[1:]
registry = f.builtin_f_registry()
declarations = tuple(d for d in registry.declarations if d.kind in ('generator', 'quality'))
def versioned(*, args, input, context): return input
implementations = tuple(f.CapabilityImplementation(kind=d.kind, ref=d.ref,
    implementation=versioned, identity=identity) for d in declarations)
if order == 'reverse':
    # Constructing an unrelated registry first must not supply an ordinal ID.
    f.make_f_registry(declarations=(), implementations=())
    f.builtin_f_registry()
    declarations = tuple(reversed(declarations))
    implementations = tuple(reversed(implementations))
registry = f.make_f_registry(declarations=declarations, implementations=implementations)
case = BareFactsCase()
artifact = ff.check_f_preflight_from_facts(case.reader,
    f.FPreflightFacts(fixed_parents=(), model=None, required_records=(), required_capabilities=()),
    registry=registry, budget=BUDGET)
assert isinstance(artifact.value, f.PreflightReady)
print(json.dumps({'registry_key': json.loads(artifact.canonical_bytes)['environment']['registry_key'],
                  'declarations': len(declarations)}, sort_keys=True))
'''


def identity_process(identity, order="forward"):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(Path(__file__).parents[1]/"src"),
                                                   str(Path(__file__).parent))),
               PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable,"-B","-c",IDENTITY_CHILD,identity,order],
                          capture_output=True,text=True,encoding="utf-8",env=env,timeout=45)
    # Do not include child tracebacks: they can display forbidden source lines.
    assert proc.returncode == 0, f"identity child exit={proc.returncode}; public identity API did not complete"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("variant",("different", "same", "registration_order"))
def test_registry_identity_across_processes(variant,record_property):
    record_property("rules","V-11,E-05,E-06"); record_property("relation","implementation_identity")
    record_property("entry","EF")
    a=identity_process("auth.implementation/1")
    b=identity_process("auth.implementation/2" if variant=="different" else "auth.implementation/1",
                       "reverse" if variant=="registration_order" else "forward")
    assert a["declarations"] >= 2, "registration-order case requires at least two declarations"
    assert (a["registry_key"] != b["registry_key"]) == (variant=="different")


@pytest.mark.parametrize("identity",("",None,0,True,[],{},"auth.valid/1"),
                         ids=("empty","null","int","bool","array","object","valid"))
def test_registry_identity_registration_boundary(identity,record_property):
    record_property("rules","V-11,A-21");record_property("relation","implementation_identity")
    record_property("entry","registry")
    native=f.builtin_f_registry()
    decl=next(d for d in native.declarations if d.kind=="generator")
    def build():
        implementation=f.CapabilityImplementation(kind=decl.kind,ref=decl.ref,
            implementation=lambda *,args,input,context:input,identity=identity)
        return f.make_f_registry(declarations=(decl,),implementations=(implementation,))
    value,exc=old.call_observed(build)
    if identity=="auth.valid/1":
        assert exc is None,old.diagnostic(value,exc)
    else:
        assert old.diagnostic(value,exc)[:2]==("FInputError","shape"),old.diagnostic(value,exc)


def test_builtin_identity_and_independent_registry_key(record_property):
    from hashlib import sha256
    from gate_f_facts_cases import BareFactsCase
    record_property("rules","V-11,E-05");record_property("relation","implementation_identity")
    record_property("entry","EF")
    registry=f.builtin_f_registry()
    assert all(i.identity=="sui.f.native/1" for i in registry.implementations)
    implementations={(i.kind,i.ref):i for i in registry.implementations}
    capabilities=[]
    for d in sorted(registry.declarations,key=lambda d:(d.kind,d.ref.name,d.ref.version)):
        i=implementations.get((d.kind,d.ref))
        capabilities.append(dict(kind=d.kind,ref=plain(d.ref),declaration=plain(d),
                                 implemented=i is not None,implementation_id=None if i is None else i.identity))
    expected="sha256:"+sha256(canonical(dict(domain="sui.f.registry_view/1",capabilities=capabilities))).hexdigest()
    artifact=ff.check_f_preflight_from_facts(BareFactsCase().reader,
        f.FPreflightFacts(fixed_parents=(),model=None,required_records=(),required_capabilities=()),
        registry=registry,budget=BUDGET)
    assert json.loads(artifact.canonical_bytes)["environment"]["registry_key"]==expected


@pytest.fixture(scope="module")
def draft_wire_material():
    case=old.finite_case()
    problem=prepare(case)
    assert isinstance(problem.value,f.FProblem)
    draw=add_draw(case,problem.value.problem_key)
    root=ff.bind_f_draw(problem,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(root.value,f.FRoot)
    return case,problem,root


@pytest.mark.parametrize("name,entry",tuple(
    (name,entry) for name in ("prepare_world","problem","root","value")
    for entry in ("EX","ER.restore_math","ER.verify","ER.restore_root")
    if (entry=="EX" or name!="value") and not (name=="problem" and entry=="ER.restore_root")))
@pytest.mark.parametrize("version",("1","2","3"))
def test_unpublished_draft_versions_are_not_upgraded(name,version,entry,draft_wire_material,record_property):
    record_property("rules","V-08,E-05");record_property("relation","draft_version")
    record_property("entry",entry);record_property("member","good" if version=="3" else "bad")
    case,problem,root=draft_wire_material
    contract=ContractRef("sui.f."+name,version)
    source=problem if name=="problem" else root
    envelope=json.loads(source.canonical_bytes)
    if entry=="EX":
        if name=="prepare_world":
            # compiler is a field of math_artifact; there is no standalone
            # prepare_world DTO. Decode the actual public envelope instead.
            envelope["compiler"]["version"]=version
            data=canonical(envelope)
            contract=ContractRef("sui.f.math_artifact","2")
        elif name=="value":
            data=codec.f_json(f.ClockReading(run=case.clock.run,time_ns=0))
        else:
            value=deepcopy(envelope["claim"]["value"])
            value["contract"]["version"]=version
            data=canonical(value)
        fn=lambda:codec.f_from_json(data,contract=contract)
    else:
        if name=="prepare_world": envelope["compiler"]["version"]=version
        elif name in ("problem","root"):
            envelope["claim"]["value"]["contract"]["version"]=version
        data=canonical(envelope)
        function={"ER.restore_math":ff.restore_f_math_result,"ER.verify":ff.verify_f_math_result,
                  "ER.restore_root":ff.restore_f_root}[entry]
        fn=lambda:function(data,reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    value,exc=old.call_observed(fn)
    if version=="3": assert exc is None,old.diagnostic(value,exc)
    else: assert old.diagnostic(value,exc)[:2]==("FInputError","unknown_version"),old.diagnostic(value,exc)


# ---
# date: 2026-10-12
# project: sui
# tool: codex
# tags: [session, sui, gate-f, independent-auth, relation-tests]
# ---
# [[Projects/sui]] F-a independent relation tests, revision rel-2026-10-12-1.
# Codex session: 01a12d14-28a7-70f3-8b04-a69d4e4c494e.
# No other AI session was contacted. The user's review summary is information,
# not an implementation oracle or approval. No implementation source was read.
#
# 実施済み / 成果物:
# C:/Users/you11/Desktop/iku/sui/tests/gate_f_auth_inventory.py
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_auth.py (coverage reporting only,
# plus correction of the obsolete compiler/1-2 preservation comment)
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_auth_rel.py (this file)
# No src/specs/other tests/material helpers were edited; no commit was made.
# Authority read: specs/関所F_今の約束.md, relevant V/A/M/E/C sections, especially
# 114, 148-234, 238-254, 264-267, 342-355, 389-510; public declarations/signatures
# were extracted with AST without printing bodies. Earlier independent tests
# and allowed primary-record helper portions were read. No external Web source.
# Generic Home/Heat/shared logging rules/template were read for the log policy;
# project implementation notes/other reviewers' source were not used as oracles.
#
# 決めたこと / 理由:
# Each relation is a separate row; presence/identity folding cannot cover it.
# Inventory: 842 = fields 686 + relations 131 (old 36 + new 95) + supplements 25.
# New relation rows: parent_child 24; body_use 8; leaf_use 6; target_witness 18;
# generation_class 5; sequence_set 16; check_order 5; stage_boundary 4;
# implementation_identity 5; draft_version 4.
# ED covers bind/evaluate; ER covers restore_math/verify/restore_root.
# Result/proof acquisitions use separate clocks in the target-witness pairs,
# so changing a target's acquisition time does not also corrupt its companion.
# Observation values are independent exact calculations from the declared
# likelihoods: one distinct observation -> joint (3/4,1/4), mass 1/2;
# two -> (9/10,1/10), mass 5/16. Re-delivery/repetition adds no observation.
# No expectation was relaxed to match accepted bad input or rejected good input.
#
# 検証 / latest result per final collected node, NOT sum of repeated runs:
# 1998 executed = 1370 passed + 628 failed; no skips, no xfail.
# 192 passes are public Ledger.append construction rejections for seq/run_index,
# NOT successful facts authentication. 54 query passes are negatives only.
# relation                 rows  tests  pass  fail  entries
# parent_child               24    576   480    96  9
# body_use                    8    192   180    12  9
# leaf_use                    6    144    72    72  9
# target_witness             18    360   153   207  7 (+2 pending)
# generation_class            5    100    70    30  7 (+2 pending)
# sequence_set               16    320   184   136  7 (+2 pending)
# check_order                 5    120    60    60  9
# stage_boundary              4     80    80     0  7 (+2 pending)
# implementation_identity     5     11    11     0  EF and registration
# draft_version               4     36    21    15  ER/EX
# query negative-only                54    54     0  6
# BOOT draw closure                    4     4     0  ED bind/evaluate
# inventory                            1     1     0
# Main relations include A-19/A-21; rule-by-kind counts: relation_counts().
# Failed rule groups (counts are not additive across rule IDs):
# A-05/V-07 parent 96; A-03/A-06 Body use 12 (Preference.basis);
# A-03/A-06 leaf use 72; A-07/A-10/M-02 witness 207;
# A-05/A-14/A-15 generation 30; A-04/M-02/M-04 sequence 136;
# A-17 check order 60; V-08/E-05 draft version 15.
# Failed legal members: witness 120, Gap 10, repeated Binding 12.
# Bad-member failures: witness 87, parent 96, Body use 12, leaf 72, generation
# 20, sequence 124, check order 60, draft version 15. No other Python errors
# remain in the adopted test-result set. C-05 registered numeric guards: no calls
# in the 40 adopted negative stage-boundary cases. This observes public callbacks,
# not private evaluation counters.
#
# 実行 commands (all used -B, --tb=no, -p no:cacheprovider, UTF-8 Python IO,
# PYTHONPATH=src;tests; junit_family=legacy; pytest never exceeded -n 2):
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   --basetemp=$env:TEMP/sui-rel-final-20261012d
#   --junitxml=$env:TEMP/gate-f-auth-rel-final.xml
# -> then-current 1878: 1317 passed, 561 failed, 204.78 s, exit 1.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   -k 'target_witness or Preference.basis or test_relation_inventory or
#   ((generation_class or sequence_set or check_order or stage_boundary) and
#   (EC.default or EB.default or EL.default))'
#   --basetemp=$env:TEMP/sui-rel-expanded-20261012e
#   --junitxml=$env:TEMP/gate-f-auth-rel-expanded.xml
# -> 637: 213 passed, 424 failed, 59.49 s, exit 1. Of these, 172 EC/EB exploratory
# items were subsequently removed from executable parameters because their legal
# oracle depends on the A-18 scope question below; they are NOT converted to pass.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py --collect-only -q
# -> 1998 collected. PowerShell's redirected list is UTF-16, not UTF-8.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py::test_relation_inventory_has_separate_rows_and_complete_parameter_pairs -q
#   --junitxml=$env:TEMP/gate-f-auth-rel-meta.xml -> 1 passed, 1.21 s.
# Results were keyed by testcase name, latest run wins, then restricted to the
# final collected names. All 1998 final names have results. No full old suite,
# mutation run, old model/golden compatibility test or implementation test ran.
# Earlier probes caught fixture issues (old receipt=0 on a late cause; stale
# alias key for raw; a cross-run suffix consumer; incomplete Compute prefix).
# Those materials were corrected to obey the spec; the ED positive control now
# uses a deterministic terminating Q. The default pytest temp folder denied
# access; a task-specific temp directory resolved it without changing permissions.
#
# 未完了 / questions (no invented query proof or unapproved scope choice):
# Original unexpanded 55 -> 54: BOOT ED is covered; query's 9 fields x 6 entries
# have required-key negatives, but no declared closed query statement/checker
# and direct dependencies (A-04:164) for a nearest authenticated legal member.
# Added pending: 43 relation rows x EC/EB = 86 row/entry pairs. A different-run,
# different-model branch is intrinsically authenticatable, but whether A-18's
# selected-context run/j binds its otherwise unused events needs clarification.
# The exploratory legal samples returned clock_unaligned; they establish that
# observation only, not the intended scope. Pending entries remain in inventory.
# Total unexpanded: 140 = 54 fields + 86 new relations. Awaiting user/spec answer.
# VALUE/1-2 is tested at EX; ER has no external ContractRef parameter or declared
# standalone VALUE restore interface. Do not invent a VALUE artifact wrapper.
# Public declaration discrepancy: CapabilityContext (src/sui/f.py:1363) has
# numeric_work/cached_quantities/numeric_input/certified_input in addition to
# V-11's four fields. Actual callback exposure was not inspected or tested.
# CapabilityImplementation.identity is already present (src/sui/f.py:931),
# and all 11 identity tests pass; no pending implementation excuse is used.
#
# 再利用した知見と結果: prior independent fixture/remapping and diagnostic helpers
# were useful; their field-presence representatives do not cover relationships.
# No new Knowledge card was written. Obsidian Sessions/Projects/Knowledge/Heat
# are UNREFLECTED: this request explicitly restricts writes to the test files.
# This authorized local comment is the fallback session log, not a vault log.
# 次: Claude reviews failing rule/use/entry pairs, resolves the query/A-18/ER-VALUE
# specifications with ゆう, implements fixes, then reruns only affected new cases.

# --- 2026-10-12 continuation / second user request ---
# date: 2026-10-12
# project: sui
# tool: codex
# tags: [session, sui, gate-f, independent-auth, relation-tests]
# [[Projects/sui]]
# Session: 01a12d14-28a7-70f3-8b04-a69d4e4c494e
# This continuation supersedes the current-state/pending claims in the earlier
# log above; that first-round result is retained as history, not today's oracle.
# No direct Claude conversation was opened; the user's supplied report was input
# information, and the independent pytest results below are the verification.
#
# Authority read (relevant portions, not the entire document):
# specs/関所F_今の約束.md:114,148-179,189,214-235,266-267,344-405,435-472,499.
# A-04:166 makes the 54 query-success obligations not_applicable in F-a;
# required-key negatives still apply and do not count as successful auth.
# A-18:234 makes an unused separate run/origin intrinsic-only at EC/EB.
# M-02:267 requires numeric replay only for the selected origin's K.
# E-05:472 excludes standalone ER VALUE; compiler/problem/root claim tests cover
# the applicable ER type-version path. E-01:350,352 publish no separate EH/EP
# artifact issuers; EN artifacts and their roots test selected-origin K at ER.
# No implementation bodies, forbidden test expectations or external Web were read.
# Public fields only: CapabilityImplementation.identity at src/sui/f.py:940;
# CapabilityContext at 1366-1373 (AST declarations, no method bodies printed).
#
# Implemented (version: 2026-10-12 turn2):
# tests/gate_f_auth_inventory.py: explicit entry_uses and entry_rules; all 86
# EC/EB pairs enabled; query 54 obligations remain in the denominator as N/A.
# tests/test_gate_f_auth.py: coverage_report query status changed to N/A.
# tests/test_gate_f_auth_rel.py: unused wrong numeric results are accepted at
# EF/EL/EC/EB, ED suffix and ER preflight/limit/suffix; selected-origin EN/EH/EP
# and ER selected_* still require proof_mismatch. Added 160 ER pair members:
# limit_restore_math/limit_verify and selected_restore_math/selected_verify/
# selected_restore_root. Accepted replay uses a freshly issued artifact over
# its actual input, avoiding an unrelated stale-claim fault. Rejected selected
# replay changes one primary result, remaps authentic CIDs, keeps the stale claim
# and requires E-06 to expose primary proof_mismatch before claim comparison.
# No src/specs/other tests/material helpers were edited. No commit was made.
#
# Inventory: 842 rows = field 686 + relation 131 + supplement 25.
# Relation kinds: previous_pair 36; parent_child 24; body_use 8; leaf_use 6;
# target_witness 18; generation_class 5; sequence_set 16; check_order 5;
# stage_boundary 4; implementation_identity 5; draft_version 4.
# Unexpanded 0: 54 query-success obligations N/A, all 86 EC/EB pairs executed.
# Plan expansion is independent of pass/fail; old tests were not rerun.
#
# Verification (latest per node, no summing repeated executions):
# 2330 tests = 2159 passed, 171 failed; 0 skipped, 0 xfail.
# All prior 1998 cases pass, including the 112 corrected sequence_set controls.
# Added ER 160/160 pass. Enabled EC/EB 172: 1 passes, 171 fail.
# relation              tests passed failed entries
# parent_child            576    576      0       9
# body_use                192    192      0       9
# leaf_use                144    144      0       9
# target_witness          432    360     72       9
# generation_class        120    101     19       9
# sequence_set            544    480     64       9
# check_order             120    120      0       9
# stage_boundary           96     80     16       9
# implementation_identity  11     11      0  EF + registration
# draft_version            36     36      0   ER/EX
# query key negatives      54     54      0       6
# BOOT draw closure         4      4      0      ED
# inventory                 1      1      0     N/A
# Each main row also lists A-19/A-21; original rule groups are in the inventory.
# A-18 is entry-specific: witness 72, generation 20, sequence 64, stage 16;
# all have EC/EB only. relation_counts() exports exact rule/kind/entry counts.
# Identity by rule: V-11 11 (EF/registration), E-05 4 (EF), E-06 3 (EF),
# A-21 7 (registration). Draft V-08/E-05 36, entries EX and ER.
# 192 parent passes stop at public Ledger.append (seq/run_index), not facts auth.
# 54 query passes are key-missing negatives, not query-success specimens.
# C-05: the registered public numerical callback guard remained uncalled in all
# 48 negative stage tests; the EC/EB eight still fail the intended diagnostic.
#
# Open findings, not weakened expectations:
# A-18/A-19: every failed case is EC/EB with clock_unaligned at */boundary/run.
# Expected accepts: 86 legal members + 32 unused numeric-result controls.
# Wrong rejection diagnostic: 45 shape negatives + 8 proof_mismatch negatives.
# Counts by relation: target_witness 72 (EC36/EB36), generation_class 19
# (EC9/EB10), sequence_set 64 (EC32/EB32), stage_boundary 16 (EC8/EB8).
# A selected-context boundary leaking to an unused branch is suggested by the
# public diagnostic; implementation internals were not inspected to localize it.
# The separate branch has its own run, origin, context and actual parent graph
# (test_gate_f_auth_rel.py:434; test_gate_f_auth.py:764); the same legal materials
# authenticate at EF and the other already enabled entries.
# V-11 public declaration mismatch remains: CapabilityContext's additional
# numeric_work/cached_quantities/numeric_input/certified_input fields versus
# the four fields specified at specs/関所F_今の約束.md:114. Callback exposure untested.
# No unresolved test-oracle question remains for this requested change.
#
# Executed commands (PowerShell; PYTHONPATH=src;tests, PYTHONIOENCODING=utf-8,
# PYTHONDONTWRITEBYTECODE=1, PYTEST_ADDOPTS=''; never more than -n 2):
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q --tb=no
#   -p no:cacheprovider -o junit_family=legacy
#   --basetemp=$env:TEMP/sui-rel-turn2-20261012a
#   --junitxml=$env:TEMP/gate-f-auth-rel-turn2.xml
# -> 2159 passed, 171 failed, 280.24 s, exit 1.
# After adding the entry-specific A-18 metadata, reran the affected scope plus
# inventory (assertions/outcomes unchanged): same command with
#   -k '((target_witness or generation_class or sequence_set or stage_boundary)
#        and (EC.default or EB.default)) or test_relation_inventory'
#   --basetemp=$env:TEMP/sui-rel-turn2-scope-20261012b
#   --junitxml=$env:TEMP/gate-f-auth-rel-turn2-scope.xml
# -> 2 passed, 171 failed, 13.37 s, exit 1. Latest-node total remains 2330.
# JUnit directory: C:/Users/you11/AppData/Local/Temp/ (both XML files above).
# Not run: full old suite, mutants, model/golden compatibility, implementation
# inspection, runtime callback-field exposure. Source/spec changes are for Claude.
# Next: fix the EC/EB unused-branch boundary, review the V-11 public type mismatch,
# then rerun only the affected file/scope at no more than two pytest workers.
# Reused knowledge/result: independent primary-DAG copy and public diagnostics
# remain useful; spec amendments replaced the former 140 unresolved obligations.
# Obsidian Sessions/Projects/Knowledge/Heat remain UNREFLECTED, and heat.py was
# not run: the latest explicit write allowlist permits only these test files.
# This authorized local comment is the fallback log, not a completed vault update.

# --- 2026-10-12 / third request / survivor discrimination ---
# date: 2026-10-12
# project: sui
# tool: codex
# tags: [session, sui, gate-f, independent-auth, survivor-discrimination]
# [[Projects/sui]]
# Codex session: 01a12d14-28a7-70f3-8b04-a69d4e4c494e
# No direct Claude conversation was opened. The user's 142-mutant/12-survivor
# report was a task input, not independently verified mutant execution.
# Artifacts, version 2026-10-12 turn3:
# C:/Users/you11/Desktop/iku/sui/tests/gate_f_auth_inventory.py
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_auth.py
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_auth_rel.py
# No src/specs/other tests/material helpers were changed; no commit was made.
# Read scope: relevant portions of specs/関所F_今の約束.md (V-07..11,
# A-01..21, M-01..04, M-13, M-19, E-01/E-06, C-01..07 and entry-scope index),
# allowed primary fixtures and our previously authored tests. No implementation
# bodies, forbidden tests, mutation definitions, historical reviewer records or
# external Web were read. V-11:114 now explains the four extra CapabilityContext
# fields; the former declaration discrepancy is not re-reported as unexplained.
# Their runtime exposure was not tested in this turn.
#
# Implemented: 14 relation rows, 256 executable tests added. Inventory now
# 856 = field 686 + relation 145 + supplement 25. New row kinds:
# survivor_generation 4, cause_receipt 1, sibling_clock 2, context_revisit 4,
# typed_point_alias 1, closure_reachability 2. Every requested number 1..12
# remains represented, including pending/N/A forms; mutation_checks and
# discrimination_limits preserve the distinction from a verified mutant kill.
#
# Number / status / tests:
# 1 A-15: raw measured < cause.at <= interval.end, versus equality. 24 pass.
#   Raw-only EF/EL/EC/EB/ED/ER avoids a duplicate opportunity guard. EN/EH/EP
#   also need a Binding for finite interpretation; those members may reject via
#   either cause/measured or opportunity/measured and are not independent kills.
# 2..4 A-15: pending, 3 rows x 9 entries = 27 entry pairs (72 surface/member
#   tests not enabled). A legal opportunity outside generated_by with complete
#   generation evidence needs a declared contract. The null-caused_by candidate
#   was rejected even on its proposed legal side: unresolved_reference at
#   /measurement/record.body.caused_by. This observation is not a spec oracle.
#   The initial 96 generation failures (probe-a) are not implementation findings.
# 5 A-05: r < cause.at < storage, versus r=cause.at<storage. 24 pass.
# 6 A-17: sibling clock records, decreasing versus increasing check order. 24 pass.
# 7 A-17: sibling observation/judgment clocks, o>j versus o<=j. 24 pass.
# 8 A-18/A-19: described_direct and acquired_direct, 68 tests: 59 pass/9 fail.
# 9 A-18/A-19: owner_leaf, 34 pass.
# 10 A-18/A-19: two_contexts, 34 tests: 25 pass/9 fail.
#   These use r=9 (legal) or r=10 (bad), active j=9, and late static candidate
#   generation basis. A later event consumer would add a second j violation.
#   EF local authentication succeeds before bound EN/EH/EP/selected replay.
#   Descriptions, an unused-origin acquisition, or a past context reach the same
#   Point. Internal encounter order/cache reuse cannot be controlled or certified
#   through this API. Individual mutant killing is NOT verified.
# 11 A-06: exclusive-reachability single-fault form is N/A under A-17's actual
#   ancestor obligation: the valid target also has an Entry.parents path.
#   Invalidating ancestry and target together adds a second fault. Diagnostic
#   and finite-budget equivalence are not proved. The paper supplies no exact
#   closure-enumeration/duplicate-visit charging rule to set a budget threshold.
# 12 A-06: missing-outer-Ref plus bad target is a two-fault form, N/A as such.
#   A different valid form WAS added: A-04:153 preserves multiple CIDs for one
#   Record before projection to Ref. Outer basis retains the correct Ref while
#   generation.basis points to an additional authentic CID outside the frontier.
#   Change only that CID's sealed payload bytes -> A-01 result_mismatch. 24 pass.
#   ER reuses a genuine artifact over the SAME valid input, then changes reader
#   transport only; no unrelated stale-claim mismatch can satisfy this negative.
#   Both forms stay in the denominator. Whole-mutant equivalence is NOT claimed.
#
# Verification, latest result per final collected node:
# 2586 = 2568 passed + 18 failed, zero pytest skips/xfails. Previous 2330 all pass;
# new 256 = 238 pass + 18 fail. This independently confirms the previous suite,
# but the user's F-wide 6222 report was not rerun here.
# Failures are all A-18/A-19, context_revisit:
# acquired_direct: EN/EH/EP legal members rejected with shape at
# /acquisition/boundary/record.body.received_ns (unused origin, receipt=37, j=9).
# two_contexts: EN/EH/EP legal members rejected with shape at
# /closure/judgment/record.body.received_ns (unknown receipt=9, past context o/j=10,
# active o/j=9; each context's own checks are valid, late management is allowed).
# Thus 6 actual bound-entry failures. ER's remaining 12 test failures are
# not_run_ER: legal EN issuance fails, so restore/verify are NOT reached.
# Do not describe these 12 as independently reproduced restore/verify defects.
# Bad-member expectations were not weakened to match the implementation.
# Previous unexpanded query54/A18-86 dispositions remain closed. New unresolved
# entry pairs: 27 (#2..4). #11 budget/diagnostic equivalence also remains open.
#
# Commands (all Python -B, PYTHONDONTWRITEBYTECODE=1, PYTHONPATH=src;tests,
# PYTHONIOENCODING=utf-8, PYTEST_ADDOPTS='', --tb=no, -p no:cacheprovider,
# -o junit_family=legacy; pytest never exceeded -n 2):
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   -k 'survivor_generation or cause_receipt or sibling_clock or test_relation_inventory'
#   --basetemp=$env:TEMP/sui-rel-turn3-probe-a
#   --junitxml=$env:TEMP/gate-f-rel-turn3-probe-a.xml
# -> exploratory 73 pass/96 fail, 14.11s; absent cause made generation baselines
#   unsuitable. #1 was rebuilt with a real cause; #2..4 await legal-contract scope.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   -k 'survivor_generation or cause_receipt or sibling_clock or context_revisit or test_relation_inventory'
#   --basetemp=$env:TEMP/sui-rel-turn3-probe-b
#   --junitxml=$env:TEMP/gate-f-rel-turn3-probe-b.xml
# -> 215 pass/18 fail, 23.51s. Public API-only construction probes also verified
#    local EF acceptance and exposed the unused acquisition / old context cases.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   --basetemp=$env:TEMP/sui-rel-turn3-final-c
#   --junitxml=$env:TEMP/gate-f-rel-turn3-final.xml
# -> then-current 2562: 2544 pass/18 fail, 294.43s, exit 1.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   -k 'typed_point_alias or test_relation_inventory'
#   --basetemp=$env:TEMP/sui-rel-turn3-alias-d
#   --junitxml=$env:TEMP/gate-f-rel-turn3-alias.xml
# -> alias addition plus updated inventory: 25 pass, 3.89s, exit 0.
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py --collect-only -q
# -> final 2586 collected, 1.09s. XML testcase names (latest wins) were checked
#    to equal this collection exactly; no missing/extraneous/repeated-count items.
# Results directory: C:/Users/you11/AppData/Local/Temp/ (filenames above).
# Not run: mutation execution, finite-budget equivalence, old/full/F-wide tests,
# model/golden compatibility, implementation inspection. Twelve ER bodies were
# not reached due to the positive EN issuer prerequisite failure noted above.
#
# Outstanding user/spec questions (asked asynchronously, no answer assumed):
# #2..4: specify a generation contract and caused_by/opportunity/generated_by
# relationship admitting the proposed legal baseline, or decide the proposed
# form is inapplicable. A prototype's rejection alone does not prove equivalence.
# #11: specify finite-budget charging and expected public outcomes, or retain
# exclusive-edge N/A while leaving finite-budget equivalence unverified.
# Next: Claude reviews the two bound-context legal rejections; after the legal
# issuer works, the ER cases can actually run. Resolve #2..4 and #11's oracle,
# then use the user's authorized mutation workflow to verify actual kills.
# Reused knowledge/result: own primary-DAG, CombinedReader and fault-reader
# helpers were useful. The Ref/Point distinction exposed a valid #12 alias pair;
# field coverage and baseline passes alone are not evidence of mutant killing.
# Obsidian Sessions/Projects/Knowledge/Heat are UNREFLECTED; heat.py not run.
# The latest allowlist permits only test files, so this separate turn3 comment
# records the mutation-discrimination topic locally rather than writing a vault log.

# --- 2026-10-12 / final request / A-14 completed-window receipt ---
# date: 2026-10-12
# project: sui
# tool: codex
# tags: [session, sui, gate-f, independent-auth, completed-window]
# [[Projects/sui]]
# Codex session: 01a12d14-28a7-70f3-8b04-a69d4e4c494e
# This continuation supersedes the previous turn's pending #2..4/#11 and
# context_revisit failure status. No direct Claude messaging was performed.
# Artifacts updated: tests/gate_f_auth_inventory.py and tests/test_gate_f_auth_rel.py
# under C:/Users/you11/Desktop/iku/sui, version 2026-10-12 final request.
# No src/specs, helper semantics, other test files or mutation definitions changed.
# No commit made. Only allowed specifications/our tests/fixture material read;
# implementation bodies and forbidden existing test expectations were not read.
# Authority read: relevant portions of specs/関所F_今の約束.md, especially A-14:214,
# A-15:215/217/224, built-in generation declaration:133 and C-06:513, plus the
# user's explicit final dispositions. No external Web or historical reports read.
#
# Implemented: closed_window_receipt has two rows (CoverageClaim and Gap),
# end==received (legal) versus end==received+1ns (shape). The sole primary change
# is interval.end_ns; an assertion checks the complete changed Record against
# that one-scalar edit. Attempt<=start<=end, real causes/evidence and Binding stay
# intact. Stop at generation; no acquisition/computation is needed. CoverageUnproved
# is excluded from this completed-window relation and retains its existing control.
# Both members reach all 9 entrances: EN/EH/EC/EP/EF/EL/EB each 4 tests; ED bind/
# evaluate 8; ER restore_math/verify/restore_root 12; total 48. EC/EB use an unused
# finite branch; ED uses the draw suffix. C-05 guards numerical callbacks in bad
# members so a later numerical rejection cannot substitute for primary shape.
#
# #2..4: 3 rows x 9 entries remain in the denominator as NOT APPLICABLE, not
# pending and not counted as passes: F-a's sui.f.opportunity_step_slot/1 requires
# opportunity to be a generator. No legal opportunity-outside-generated_by pair
# exists in this slice. Removed the unexecutable null-caused_by prototype branches.
# Another generation contract belongs to a later slice, as explicitly directed.
# #11: exclusive check_events reachability is N/A since valid targets are actual
# ancestors too. Claim only the successful-input set with sufficient budget
# (C-06 dimension 1); diagnostics and finite-budget equivalence remain unverified.
# F-a does not norm budget accounting/expected public budget results in this task.
# #12's separate-CID executable pair and its double-fault N/A form remain intact.
#
# Final inventory: 858 = fields 686 + relations 147 + supplements 25.
# New relation kind closed_window_receipt: 2 rows, 48 tests, 9 entrances.
# Pending field/relation entry pairs: 0. Prior query54 N/A and A18-86 expansion
# remain closed. The newly closed 27 N/A entry pairs are not removed or executed.
#
# Executed with PYTHONPATH=src;tests, PYTHONDONTWRITEBYTECODE=1,
# PYTHONIOENCODING=utf-8, PYTEST_ADDOPTS='', Python -B, --tb=no,
# -p no:cacheprovider -o junit_family=legacy and at most -n 2:
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   -k 'closed_window_receipt or survivor_generation or test_relation_inventory'
#   --basetemp=$env:TEMP/sui-rel-final-a14-probe
#   --junitxml=$env:TEMP/gate-f-rel-final-a14-probe.xml
# -> 73 passed, exit 0 (48 new + 24 existing survivor #1 + inventory).
# .venv/Scripts/python -B -m pytest tests/test_gate_f_auth_rel.py -n 2 -q
#   --basetemp=$env:TEMP/sui-rel-final-a14-all
#   --junitxml=$env:TEMP/gate-f-rel-final-a14-all.xml
# -> 2634 passed, 0 failed/errors/skips/xfails, 333.46s, exit 0.
# Full XML test names are unique. closed_window_receipt48 and context_revisit136
# all pass, including the former 18 failures and their ER issuer prerequisites.
# XML and stdout are in C:/Users/you11/AppData/Local/Temp/ with those basenames.
# The two changed files also passed Python AST parsing.
# Not run: mutation execution/killing, diagnostic/finite-budget equivalence,
# other test files or the F-wide suite. No unsupported equivalence is inferred
# from these passes, and no expected outcome was weakened to fit implementation.
# Reused knowledge/result: own coverage_case and primary-copy helpers remained
# useful; single-scalar assertions preserve the distinguishing boundary.
# Outstanding user/spec questions: none for this final request.
# Obsidian Sessions/Projects/Knowledge/Heat remain UNREFLECTED; heat.py not run.
# The explicit test-file allowlist takes precedence; this allowed local comment
# is the fallback session record, not a completed vault update.
