"""S4b-2 v0.13 public contracts and specification-derived fixtures.

Tests assert independent fixture content and the implemented public loader.
The phase-4 public roundtrip now runs without an expected-failure marker.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
from hashlib import sha256
from inspect import signature
from pathlib import Path
import json
from typing import get_type_hints

import pytest

from sui import rate, rate_entry, rate_model
from sui.action_types import FixedLabel
from sui.agent import Agent, View, plan
from sui.clock_contracts import SOURCE
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind
from sui.preference import current, resolve
from sui.records import Record, Observed, Payload
from sui.s1_contracts import ATTEMPT
from sui.s4_contracts import BOOT
from s4b2_worlds import (
    NS, CANDIDATES, U, STANDARD_BUDGET, RATE_REPORT, CONTRACT_GAPS,
    POSTERIOR, JOINT_MASS, ROOT_OVERFLOW, Q_READ, Q_WITHOUT_ARRIVALS,
    c1_declaration, c1_model_bytes, c1_world, canonical, count_cell,
    report_content, command, start_attempt, completion_report, observation,
    four_rate_declaration, independent_arrival_declaration, tick_declaration,
    millisecond_declaration, reduction_declaration, malformed_pairs, scope_pairs,
    boundary_evaluation, quantity_cases, posterior_by_integration, joint_mass_by_formula,
)


def test_declaration_matches_complete_normative_example():
    """G item 1: compare all values against the distributed normative fixture.

    Markdown specifications are not distributed. Their examples are checked
    against this fixture separately where the specifications are available.
    """
    path = Path(__file__).with_name("s4b2_c1_declaration.json")
    example = json.loads(path.read_text(encoding="utf-8"))
    assert c1_declaration() == example
    assert c1_model_bytes() == canonical(example)
    assert set(example) == set(rate_model.KEYS) == {
        "scheme", "contract", "units", "state_space", "variables", "processes",
        "controls", "records", "coverage", "order", "targets", "measure",
        "certificate_capabilities",
    }
    assert rate_model.CONTRACT == ContractRef("sui.s4b.rate_model","1")
    assert b"fixture." not in c1_model_bytes()
    assert set(CONTRACT_GAPS) == {12}


def test_ids_scopes_parents_outputs_Q_orientation_and_shared_probe():
    """G items 1/2: all graph edges and ordering are semantic input."""
    d=c1_declaration()
    variables={v["id"]:v for v in d["variables"]}
    assert tuple(variables)==("r","p","state","arrivals","measurement","read-completion","wait-completion")
    assert tuple(p["id"] for p in d["processes"])==("state-process","arrival-process","probe","read-done","wait-done")
    assert [v["scope"] for v in variables.values()]==["model","model","run","run","attempt","attempt","attempt"]
    assert d["targets"]["laws"]==["r","p"]
    for process in d["processes"]:
        for out in process["outputs"]:
            assert variables[out]["generated_by"]==process["id"]
        assert process["parents"]==[vid for vid in variables if vid in process["parents"]]
    matrix=d["processes"][0]["params"]["off_diagonal"]["fixed"]
    zero={"kind":"constant","value":[0,1]}
    assert matrix==[[zero,zero],[{"kind":"scaled_variable","variable":"r","coefficient":[1,1]},zero]]
    arrival=d["processes"][1]
    assert arrival["params"]["rates"]["fixed"]==[
        {"kind":"scaled_variable","variable":"r","coefficient":[1,1]},
        {"kind":"scaled_variable","variable":"r","coefficient":[2,1]}]
    probe=d["processes"][2]
    assert probe["parents"]==["p","state"]
    assert probe["params"]=={"state_process":"state-process","probability_variable":"p","labels":["y0","y1"]}
    assert d["records"][1]["probe"]==d["processes"][3]["params"]["probe"]=="probe"
    independent=independent_arrival_declaration()
    assert independent["variables"][0]["prior"]==independent["variables"][1]["prior"]
    assert independent["processes"][1]["parents"]==["r_arrival","state"]
    assert canonical(independent)!=c1_model_bytes()


def test_alphabet_all_cells_and_wait_has_no_count_coverage():
    """G item 3/H1: absent observation is different from observed zero."""
    d=c1_declaration()
    root,read,wait=d["records"]
    assert [r["id"] for r in d["records"]]==["root-report","read-report","wait-report"]
    assert root["alphabet"]=={"kind":"finite","values":[count_cell(n) for n in range(4)]}
    assert read["alphabet"]=={"kind":"finite","values":[count_cell(n,y) for n in range(4) for y in ("y0","y1")]}
    assert wait["alphabet"]=={"kind":"finite","values":[{"arrival_count":None,"outcome":None}]}
    for r in d["records"]:
        assert set(r)=={"id","generator","kernel","experiment","clock","alphabet","probe"}
        assert r["clock"]=={"name":"exact","version":"1","params":{}}
        if "clock" in r["kernel"]["params"]:
            assert r["clock"]==r["kernel"]["params"]["clock"]
    assert d["controls"]["choices"][1]["observation_records"]==["wait-report"]
    assert d["coverage"]["intervals"]==[
        {"record":"root-report","start":[0,1],"end":[1,1],"source":{"kind":"exogenous","id":"root-window"}},
        {"record":"read-report","start":[1,1],"end":[2,1],"source":{"kind":"choice","id":"read"}}]
    assert d["coverage"]["policy"]["params"]=={"left":"open","right":"closed"}
    with pytest.raises(ValueError,match="no count"):
        report_content("wait",0)


@pytest.mark.parametrize("n",range(4))
@pytest.mark.parametrize("boot_ns,receive,recorded",[(0,0,0),(7*NS,11,19)])
def test_boot_source_root_clock_and_CID_ancestry(n,boot_ns,receive,recorded):
    """G item 4/D2-01: SOURCE is provenance, never an extra observed silence."""
    w=c1_world(n,boot_ns=boot_ns,run_index=3,received_delay_ns=receive,recorded_delay_ns=recorded)
    assert [r.body.contract for r in w.records]==[BOOT,SOURCE,RATE_REPORT]
    assert all(r.id.kind==RefKind.OBSERVATION and r.at.run==w.context.run and r.at.run_index==3 for r in w.records)
    assert w.context.run.kind==RefKind.RUN
    assert w.boot.at.seq<w.source.at.seq<w.root.at.seq
    assert w.boot.at.mono_ns==w.source.at.mono_ns==boot_ns
    assert w.root.body.content.as_json()==report_content("root-window",n,boot_ns=boot_ns)
    assert (w.root.body.source_time_ns,w.root.body.received_ns,w.root.at.mono_ns)==(
        boot_ns+NS,boot_ns+NS+receive,boot_ns+NS+receive+recorded)
    assert w.context.now_ns==w.root.at.mono_ns
    assert w.context.observed_ns==w.root.body.received_ns
    assert w.context.clock_source==w.source.id!=w.root.id
    assert w.context.check_events==({"fact":str(w.root.id)},)
    entries=[w.ledger.entries_of(r.id)[0] for r in w.records]
    boot_ref,root_ref=str(w.boot.id),str(w.root.id)
    assert w.context.fact_ancestors=={
        entries[0].cid:frozenset({boot_ref}),
        entries[1].cid:frozenset({boot_ref}),
        entries[2].cid:frozenset({boot_ref,root_ref})}
    assert all(cid.startswith("sha256:") for cid in w.context.fact_ancestors)
    assert str(w.source.id) not in set().union(*w.context.fact_ancestors.values())
    assert w.ledger.heads()==frozenset({entries[2].cid})
    assert all(w.ledger.record(e.cid)==r for e,r in zip(entries,w.records))
    payload=w.source.body.content.as_json()
    assert payload["measurement"]=={"name":"exact","version":"1"}
    assert (w.resolved.items,w.resolved.style,w.resolved.H_ns,w.resolved.gamma)==((),None,None,1.0)
    assert w.target==FixedLabel(time_s=F(2),causal_stage=0,causal_position=0,side="post")
    assert w.root.body.content.as_json()["completion_ns"]-w.boot.at.mono_ns==NS


@pytest.mark.parametrize("action,count,outcome",
    [("read",n,y) for n in range(4) for y in ("y0","y1")]+[("wait",None,None)])
def test_alternative_completion_records_use_public_attempt(action,count,outcome):
    """Each alternative has its own world; job Ref is a construction-only input."""
    w=c1_world()
    attempt=start_attempt(w,Ref(RefKind.JOB,action+"-job"))
    result=completion_report(w,attempt,action,count,outcome,received_delay_ns=7,recorded_delay_ns=11)
    assert attempt.body.contract==ATTEMPT
    assert attempt.body.content.as_json()=={}
    assert attempt.id.kind==RefKind.ATTEMPT and attempt.body.job.kind==RefKind.JOB
    assert attempt.at.mono_ns==NS
    assert result.body.caused_by==attempt.id
    assert result.body.contract==RATE_REPORT
    assert result.body.content.as_json()==report_content(action,count,outcome)
    assert (result.body.source_time_ns,result.body.received_ns,result.at.mono_ns)==(2*NS,2*NS+7,2*NS+18)
    assert len({r.at.seq for r in (*w.records,attempt,result)})==5
    assert command(action)["execution"]["start"]=={"time":[1,1],"causal_stage":0,"causal_position":0}


def test_redelivery_same_source_and_shared_clock_are_one_physical_report():
    w=c1_world()
    attempt=start_attempt(w,Ref(RefKind.JOB,"read-job"))
    first=completion_report(w,attempt,"read",0,"y0",source_id="physical-1")
    again=completion_report(w,attempt,"read",0,"y0",received_delay_ns=20,recorded_delay_ns=3,source_id="physical-1")
    assert first.id!=again.id and first.body.source_id==again.body.source_id
    assert first.body.content.data==again.body.content.data
    assert first.body.source_time_ns==again.body.source_time_ns
    assert first.at.seq<again.at.seq


def test_scope_fixtures_keep_order_and_clock_provenance_consistent():
    d=four_rate_declaration()
    laws=[v["id"] for v in d["variables"] if v["role"]=="law"]
    assert laws==d["targets"]["laws"]==["q01","q10","lambda0","lambda1","p"]
    for process in d["processes"]:
        assert process["parents"]==[v["id"] for v in d["variables"] if v["id"] in process["parents"]]
    tick=tick_declaration()
    w=c1_world(declaration=tick)
    assert w.source.body.content.as_json()["measurement"]=={"name":"tick","version":"1"}
    for r in tick["records"]:
        assert r["clock"]==tick["records"][0]["clock"]
        if "clock" in r["kernel"]["params"]: assert r["clock"]==r["kernel"]["params"]["clock"]
    assert {p.name:p.expected for p in scope_pairs()}=={
        "four-independent-rates":(("RateIncomplete","rate_prior_scope"),),
        "latent-clock":(("RateIncomplete","latent_clock"),),
        "deep-tree":(("RateIncomplete","depth_scope"),)}


def test_malformed_fixture_changes_relevant_contents():
    pairs={p.name:p for p in malformed_pairs()}
    assert all(p.valid!=p.changed for p in pairs.values())
    assert "probe" not in json.loads(pairs["missing-probe"].changed)["records"][0]
    assert len(json.loads(pairs["missing-cell"].changed)["records"][1]["alphabet"]["values"])==7
    dup=json.loads(pairs["duplicate-cell"].changed)["records"][1]["alphabet"]["values"]
    assert len(dup)==8 and dup[0]==dup[-1]
    assert pairs["general-progress"].expected==(("RateSpecificationMissing","missing_kernel"),)
    assert pairs["nonreduced-rational"].expected==(("RateInputError","noncanonical"),)


def test_units_and_reduction_inputs_preserve_raw_records():
    seconds=c1_world()
    ms=c1_world(declaration=millisecond_declaration())
    assert [r.body.content.data for r in seconds.records]==[r.body.content.data for r in ms.records]
    d=json.loads(ms.declaration)
    assert d["variables"][0]["prior"]["params"]["rate"]==[2000,1]
    assert d["targets"]["state_positions"][0]["position"]["time"]==[2000,1]
    assert ms.target==seconds.target
    assert reduction_declaration("point-rates")["variables"][0]["prior"]["params"]=={"value":[1,1]}
    assert reduction_declaration("all-point")["variables"][1]["prior"]["params"]=={"value":[[1,2],[1,2]]}
    assert reduction_declaration("zero-Q")["processes"][0]["parents"]==[]


def test_budget_ContractRef_and_extended_quantity_public_types():
    assert rate.default_rate_budget()==STANDARD_BUDGET
    assert get_type_hints(rate.Certificate)["method"] is ContractRef
    assert get_type_hints(rate.Certificate)["arithmetic"] is ContractRef
    assert get_type_hints(rate.LikelihoodCertificate)["measure"] is ContractRef
    assert get_type_hints(rate.RateScope)["method"]==ContractRef|None
    values=quantity_cases()
    assert [q.support for q in values]==["positive","zero","unproved","unproved","positive"]
    assert values[0].bounds.lower>0 and values[1].bounds.upper==0
    assert values[2].status=="uncertified" and values[2].bounds.lower==0
    assert values[3].bounds is None and values[4].status=="positive_infinity"


@pytest.mark.parametrize("name",[
    "RateInputError","RateSpecificationMissing","RateIncomplete","RateOutsideEvaluationType",
    "RateModelFalsified","RateNumericalRange","RateNoAdmissibleCandidate","RateReplayUnavailable",
    "RateReplayMismatch","RateRuntimeUnverified"])
def test_exception_fields_and_display(name):
    cls=getattr(rate,name)
    error=cls(reason="fixture",detail="dry run",field="record.clock")
    assert (error.reason,error.detail,error.field)==("fixture","dry run","record.clock")
    assert str(error)=="fixture: dry run"
    assert str(cls(reason="fixture"))=="fixture"
    if name=="RateReplayMismatch":
        error=cls("selection","different u",field="root.u",fields=("selection","inputs"))
        assert error.fields==("selection","inputs")
        assert error.field=="root.u" and str(error)=="selection: different u"


def test_model_constructor_and_selection_public_argument_shapes():
    direct = rate_model.RateModel(declaration=c1_model_bytes())
    loaded = rate_model.rate_model_from_json(data=c1_model_bytes())
    assert direct.declaration == loaded.declaration == c1_model_bytes()
    assert direct.ref == loaded.ref
    bound = signature(rate.certify_choice).bind(evaluation=boundary_evaluation(), u=F(1, 2))
    assert tuple(bound.arguments) == ("evaluation", "u")


@pytest.mark.parametrize("n", range(3))
def test_nine_posterior_rationals_and_twenty_four_masses_match_spec_formulas(n):
    """T05/T06 oracle preparation: integrate the specified joint likelihood."""
    assert posterior_by_integration(n) == POSTERIOR[n]
    assert joint_mass_by_formula(n) == JOINT_MASS[n]
    assert all(cell > 0 for pair in JOINT_MASS[n] for cell in pair)
    assert sum(sum(pair) for pair in JOINT_MASS[n]) == POSTERIOR[n][0]
    # Each read bin adds the shared Dirichlet(1,1) probe's two equiprobable labels.
    assert sum(sum(pair) / POSTERIOR[n][0] / 2 for pair in JOINT_MASS[n] for _ in range(2)) == 1
    assert sum(row[0] for row in POSTERIOR) + ROOT_OVERFLOW == 1


def _log_bounds(value):
    """28-term atanh series; exact range reduction to [1,2]."""
    def series(m):
        z = (m - 1) / (m + 1)
        lower = 2 * sum(z**(2*j+1) / (2*j+1) for j in range(28))
        remainder = 2 * z**57 / (57 * (1-z*z))
        return lower, lower + remainder
    value = F(value)
    exponent = 0
    while value < 1:
        value *= 2
        exponent -= 1
    while value > 2:
        value /= 2
        exponent += 1
    lo, hi = series(value)
    l2, h2 = series(F(2))
    return (lo + exponent*l2, hi + exponent*h2) if exponent >= 0 else (
        lo + exponent*h2, hi + exponent*l2)


def _entropy_bounds(probabilities):
    lo = hi = F(0)
    for p in probabilities:
        if p:
            loglo, loghi = _log_bounds(p)
            lo -= p * loghi
            hi -= p * loglo
    return lo, hi


def _exp_bounds(x):
    """48th-degree Taylor polynomial with geometric bound on remaining terms."""
    assert 0 <= x < 50
    term = total = F(1)
    for k in range(1, 49):
        term *= x / k
        total += term
    return total, total + term*x/49/(1-x/50)


def _sigmoid_bounds(lo, hi):
    elo = _exp_bounds(lo)[0]
    ehi = _exp_bounds(hi)[1]
    return elo/(1+elo), ehi/(1+ehi)


@pytest.mark.parametrize("n", range(3))
def test_q_interval_from_independent_entropy_bounds_certifies_read(n):
    """§6-4: rational log/exp remainders, no float-derived certification."""
    z = POSTERIOR[n][0]
    joint = tuple(tuple(x/z for x in row) for row in JOINT_MASS[n])
    hc = _entropy_bounds(tuple(sum(row) for row in joint))
    hs = _entropy_bounds(tuple(sum(row[s] for row in joint) for s in range(2)))
    hsc = _entropy_bounds(tuple(x for row in joint for x in row))
    lp, hp = _log_bounds(F(2))
    lower_info = lp-F(1, 2) + hc[0]+hs[0]-hsc[1]
    upper_info = hp-F(1, 2) + hc[1]
    lower_q, upper_q = _sigmoid_bounds(lower_info, upper_info)
    assert Q_READ[n].lower <= lower_q <= upper_q <= Q_READ[n].upper
    assert F(0) <= U < Q_READ[n].lower  # F[0].upper <= u < F[1].lower
    lower_without, upper_without = _sigmoid_bounds(lp-F(1, 2), hp-F(1, 2))
    assert Q_WITHOUT_ARRIVALS.lower <= lower_without <= upper_without <= Q_WITHOUT_ARRIVALS.upper
    assert Q_WITHOUT_ARRIVALS.upper <= U < 1  # same u now selects wait




def test_phase1_model_loader_roundtrip_and_public_axes():
    model=rate_model.rate_model_from_json(c1_model_bytes())
    assert (model.states,model.outcomes,model.actions,model.choices)==(
        ("0","1"),("y0","y1"),("read","wait"),("read","wait"))
    assert rate_model.rate_model_json(model)==model.declaration==c1_model_bytes()
    assert rate_model.rate_model_ref(model)==model.ref=="sha256:"+sha256(c1_model_bytes()).hexdigest()
    assert not any(hasattr(model,name) for name in ("Q","a","D","arrivals","durations","learnable"))


@pytest.mark.parametrize("pair",malformed_pairs(),ids=lambda p:p.name)
def test_phase1_loader_rejects_declared_mutations(pair):
    cls_name,reason=pair.expected[0]
    with pytest.raises(getattr(rate,cls_name)) as caught:
        rate_model.rate_model_from_json(pair.changed)
    assert caught.value.reason==reason


def test_phase1_independent_equal_priors_are_a_different_valid_model():
    shared=rate_model.rate_model_from_json(c1_model_bytes())
    independent=rate_model.rate_model_from_json(canonical(independent_arrival_declaration()))
    assert shared.ref!=independent.ref
    assert rate_model.rate_model_json(independent)==canonical(independent_arrival_declaration())


@pytest.mark.parametrize("n",range(3))
def test_phase2_posterior_and_branch_probabilities_from_real_records(n):
    w=c1_world(n)
    model=rate_model.rate_model_from_json(w.declaration)
    reading=rate_entry.read_rate(model,w.records)
    belief=rate.rebuild_rate_belief(model,reading,context=w.context,budget=w.budget)
    z,mean,p_zero=POSTERIOR[n]
    assert belief.evidence.value.lower<=z<=belief.evidence.value.upper
    moment=rate.parameter_moment(belief,powers=(("r",1),),budget=w.budget)
    assert moment.bounds.lower<=mean<=moment.bounds.upper
    marginal=dict(rate.state_marginal(belief,targets=(FixedLabel(
        time_s=F(1),causal_stage=0,causal_position=0,side="post"),),budget=w.budget))
    assert marginal[("0",)].bounds.lower<=p_zero<=marginal[("0",)].bounds.upper
    branches=rate.rate_branches(belief,choice="read",budget=w.budget)
    assert len(branches)==8
    actual={canonical(b.report):b for b in branches}
    for k in range(4):
        for y in ("y0","y1"):
            branch=actual[canonical(report_content("read",k,y))]
            expected=sum(JOINT_MASS[n][k])/z/2
            assert branch.probability.bounds.lower<=expected<=branch.probability.bounds.upper
    wait=rate.rate_branches(belief,choice="wait",budget=w.budget)
    assert len(wait)==1 and wait[0].probability.bounds==rate.RationalInterval(F(1),F(1))


def test_phase3_exact_boundary_selects_next_candidate():
    chosen=rate.certify_choice(boundary_evaluation(),u=F(1,2))
    assert (chosen.index,chosen.choice,chosen.u)==(1,"wait",F(1,2))


def test_phase3_uncertain_boundary_is_incomplete():
    with pytest.raises(rate.RateIncomplete) as caught:
        rate.certify_choice(boundary_evaluation(uncertain=True),u=F(1,2))
    assert caught.value.reason=="selection_boundary"


@pytest.mark.parametrize("u",[True,F(1),float("nan")],ids=["bool","one","nan"])
def test_phase3_invalid_u_is_not_silently_converted(u):
    with pytest.raises(rate.RateInputError) as caught:
        rate.certify_choice(boundary_evaluation(),u=u)
    assert caught.value.reason=="invalid_u"


def _public_root(world,budget):
    if "rate_budget" not in signature(Agent).parameters:
        raise NotImplementedError("PHASE4: the public Agent rate_budget argument is not implemented")
    model=rate_model.rate_model_from_json(world.declaration)
    # Exercise the public belief prerequisite before the later Agent integration.
    reading=rate_entry.read_rate(model,world.records)
    derived=rate.rebuild_rate_belief(model,reading,context=world.context,budget=budget)
    assert derived.model_ref==model.ref
    agent=Agent(model=model,lineage="c1",rate_budget=budget)
    belief=agent.adopt(world.ledger,clock=world.clock,ids=world.ids)
    view=agent.view(now_ns=world.context.now_ns,observed_ns=world.context.observed_ns,
                    check_events=world.context.check_events)
    return model,agent,belief,view,resolve(current(view.preferences),view)


@pytest.mark.parametrize("name",["unknown-version","missing-probe","general-progress"])
def test_phase4_common_model_loader_preserves_rate_exception_types(name):
    # Public model loader shape is also documented by tools/s4b_action_golden.py.
    from sui.model import model_from_json
    rate_model.rate_model_from_json(c1_model_bytes())  # real supported baseline first
    pair=next(pair for pair in malformed_pairs() if pair.name==name)
    cls_name,reason=pair.expected[0]
    with pytest.raises(getattr(rate,cls_name)) as caught:
        model_from_json(pair.changed)
    assert caught.value.reason==reason


@pytest.mark.parametrize("pair",scope_pairs(),ids=lambda p:p.name)
def test_phase3_scope_pairs_use_real_View_and_Resolved(pair):
    declaration=None if pair.name=="deep-tree" else json.loads(pair.changed)
    w=c1_world(declaration=declaration)
    model=rate_model.rate_model_from_json(w.declaration)
    reading=rate_entry.read_rate(model,w.records)
    # Scope is queried before requesting a posterior for an unsupported prior.
    # This low-level View holds an opaque belief identity, not a persisted
    # belief record; the Agent/ledger roundtrip is tested separately in phase 4.
    view=View(model=model,frontier=w.ledger.heads(),belief=Ref(RefKind.INTERPRETATION,"scope-query"),
        reading=reading,now_ns=w.context.now_ns,observed_ns=w.context.observed_ns,
        check_events=w.context.check_events,fact_ancestors=w.context.fact_ancestors)
    resolved=resolve(current(view.preferences),view)
    if pair.name=="deep-tree":
        resolved=replace(resolved,H_ns=pair.changed)
    cls_name,reason=pair.expected[0]
    scope=rate_entry.certify_rate_scope(view,w.candidates,resolved,budget=w.budget)
    assert (scope.status,scope.reason)==("incomplete",reason)
    before=w.ledger.entries()
    with pytest.raises(getattr(rate,cls_name)) as caught:
        rate.evaluate_rate(view,w.candidates,resolved,budget=w.budget)
    assert caught.value.reason==reason and w.ledger.entries()==before


def test_phase4_public_roundtrip_injected_budget_prepare_retry_and_future_report():
    w=c1_world()
    budget=rate.RateBudget(F(1,10**8),21000,2100,21000)
    model,agent,belief,view,resolved=_public_root(w,budget)
    assert agent.rate_budget==budget
    before=w.ledger.entries()
    evaluation=rate.evaluate_rate(view,w.candidates,resolved,budget=budget)
    assert evaluation.certificate.budget==budget
    draft=rate_entry.public_evaluate(view,w.candidates,resolved,u=w.u,budget=budget)
    assert draft==plan(view,w.candidates,u=w.u,rate_budget=budget)
    assert w.ledger.entries()==before
    content=draft.content.as_json()
    assert content["intent"]==command("read")
    prepared=agent.prepare(draft,clock=w.clock,ids=w.ids)
    assert w.ledger.entries()==before
    bad_decided=replace(prepared.decided,body=replace(prepared.decided.body,
        content=Payload.json({**content,"u":[1,1]})))
    with pytest.raises((rate.RateInputError,rate.RateReplayMismatch)):
        agent.commit(replace(prepared,decided=bad_decided),ledger=w.ledger)
    assert w.ledger.entries()==before
    agent.commit(prepared,ledger=w.ledger)
    committed=w.ledger.entries()
    agent.commit(prepared,ledger=w.ledger)
    assert w.ledger.entries()==committed
    assert prepared.job.body.decision==prepared.decided.id
    assert prepared.job.body.content.as_json()==command("read")
    decision_cid=w.ledger.entries_of(prepared.decided.id)[0].cid
    assert rate_entry.verify_rate_decision(model=model,ledger=w.ledger,decision=decision_cid,budget=budget)==draft
    attempt=start_attempt(w,prepared.job.id)
    w.ledger.accept(attempt)
    result=completion_report(w,attempt,"read",0,"y0")
    w.ledger.accept(result)
    agent.adopt(w.ledger,clock=w.clock,ids=w.ids)
    assert rate_entry.verify_rate_decision(model=model,ledger=w.ledger,decision=decision_cid,budget=budget)==draft
    restored=Agent.restore(model=model,lineage="restored",ledger=w.ledger,
        belief=w.ledger.entries_of(belief.id)[0].cid,rate_budget=budget)
    assert restored.view().belief==belief.id
