"""K39 v5 + K39-b, requests117-120. Decisions6-8 were reread in 120.

Production files are not opened; traceback exposure is logged in k39_session119.json.
SwitchPart(id, kind, multipliers), where kind is mood or inert;
PoissonLaw(run, states, prior, rates, origin_ns, initial_count, time_unit,
           family=None, parts=(), a=None, b=None, state_role=None);
SwitchQuantity(kind, candidate, family, on=(), off=(), state=None,
                order=None, point=None), kinds switch/state/mass/p_mean/p_moment;
FThreadHost.query_switch_belief(*, belief, quantity, budget) -> BeliefValue;
FThreadHost.p_distribution(*, belief, candidate, family, budget) -> BetaMixture;
BetaMixture(root,candidate,family,parts,a,b,components,proof), with
BetaMixtureComponent(a,b,weight: BeliefValue). Equal Beta shapes may be grouped.
FThreadHost.verify_p_distribution(*, belief, distribution) -> bool;
resolve_belief_candidates(declaration, *, reader, registry) -> ResolvedBeliefPool
  with document, candidates, references. Each candidate has id, states, prior,
  rates, correspondence, knowledge_targets, references. The result is read-only.
  Unsupported declarations raise TimeBeliefError with named targets.
The host's saved model is resolution.document. Direct U must reproduce the
saved result from the request's record view, without the live host pool.

All switch/p queries condition on candidate and family, not pool probability.
SwitchQuantity.mass is P(h | M), without the pool prior weight P(M) (decision6).
The mixture points back to its belief root; numerical weights are certificates,
never a replacement for the canonical law/history. Unsupported p_cdf and
p_quantile requests use SwitchQuantity.point and are named refusals.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import fields, replace
from fractions import Fraction as Q
from itertools import product
import json

import pytest

from sui import fb, fb_contracts as c, f_update2 as u2
from sui.ids import RefKind
from sui.records import Payload, Prediction, Role
from test_fb_belief import BeliefSnapshotReader, belief1_clone
from test_fb_pool import public_rounds
from test_fb_cycle import T, E, NativeEntryObserver, world_document, contract, wire
from test_fb_time_belief import (TimeRig, script, budget, rat, plus, minus, times,
    divide, total, expneg, logarithm, first_empty, assert_contains, enclose,
    time_fact_at, time_direct_update, finite_ce1)


NEW_NAMES = ("SwitchPart", "PoissonLaw", "SwitchQuantity", "BetaMixture",
             "BetaMixtureComponent", "ResolvedBeliefPool", "resolve_belief_candidates")


def switch_api():
    missing = [n for n in NEW_NAMES if not hasattr(fb, n)]
    missing += ["FThreadHost."+n for n in
        ("query_switch_belief", "p_distribution", "verify_p_distribution")
        if not hasattr(fb.FThreadHost, n)]
    expected = {"family", "parts", "a", "b", "state_role", "rates"}
    missing += ["PoissonLaw."+n for n in sorted(expected-{f.name for f in fields(fb.PoissonLaw)})]
    assert not missing, "K39 public shape missing: "+", ".join(missing)


def rising(x, n):
    out = Q(1)
    for i in range(n): out *= x+i
    return out


def bit_prior(bits, a, b):
    m, k = sum(bits), len(bits)
    return rising(a, m)*rising(b, k-m)/rising(a+b, k)


class OracleJoint(dict):
    """Keep a proved marginal alongside positive-evidence fixture joint tables."""
    def __init__(self, entries, *, exact_state=None):
        super().__init__(entries)
        self.exact_state = exact_state


def joint_oracle(base, factors, a, b, *, interval=(1, 1), prior=(Q(1,2), Q(1,2)),
                 sensor=(Q(1),Q(1)), symbol=E, initial_count=0):
    """Finite sum of independent exact K38 expressions, not branch posteriors.

    Empty histories with increasing cursor-zero times reduce to the last empty.
    The tests explicitly retain the same z for all observations.
    """
    weights, rates = {}, {}
    before, after = interval
    for bits in product((0,1), repeat=len(factors)):
        resolved = tuple(base[s]*product_factors(factors, bits, s) for s in range(2))
        rates[bits] = resolved
        for state, rate in enumerate(resolved):
            likelihood = first_empty(rate, before, after)
            if symbol == T:
                likelihood = rat(1) if initial_count else minus(rat(1), likelihood)
            weights[bits,state] = times(rat(bit_prior(bits,a,b)*prior[state]*sensor[state]), likelihood)
    mass = total(weights.values())
    active={(bits,s) for bits,table in rates.items() for s,rate in enumerate(table)
            if not (symbol==T and not initial_count and rate==0)}
    # If each branch has the same likelihood for both states, then
    # W[z,s] = P(z) * prior[s] * sensor[s] * L[z]. Summing over z cancels
    # sum_z P(z)L[z] exactly, even when L differs between branches.
    # Keep all branch/cell expressions: only this proved state marginal is
    # reduced, without rounding, dropping a branch or assuming equal priors.
    state_normalizer=sum(prior[s]*sensor[s] for s in range(2))
    exact_state=(tuple(prior[s]*sensor[s]/state_normalizer for s in range(2))
        if state_normalizer and all(table[0]==table[1] for table in rates.values()) else None)
    constant_likelihood = ((symbol==T and initial_count>0) or
        len({rates[bits][s] for bits,s in active})==1)
    if constant_likelihood:
        normalizer=sum(bit_prior(bits,a,b)*prior[s]*sensor[s] for bits,s in active)
        values={(bits,s):rat(bit_prior(bits,a,b)*prior[s]*sensor[s]/normalizer if (bits,s) in active else 0)
                for bits in rates for s in range(2)}
    else:
        values={key:divide(value,mass) for key,value in weights.items()}
    return OracleJoint(values,exact_state=exact_state),mass,rates


def product_factors(factors, bits, state):
    out=Q(1)
    for bit, factor in zip(bits,factors,strict=True):
        if bit: out *= factor[state]
    return out


def branch_weight(joint, bits):
    if len(joint)==2:return rat(1)
    return total(joint[bits,s] for s in range(2))
def marginal_state(joint, s):
    if getattr(joint,"exact_state",None) is not None:return rat(joint.exact_state[s])
    return total(v for (bits,state),v in joint.items() if state==s)


def moment_oracle(joint, a, b, k, order):
    if not k:return rat(rising(a,order)/rising(a+b,order))
    return total(times(branch_weight(joint,bits),
        rat(rising(a+sum(bits),order)/rising(a+b+k,order)))
        for bits in product((0,1),repeat=k))


def selection_oracle(joint, rates, targets=("A","B")):
    """I(Y; (resolved-rate-table, original-target)); duplicate aliases merge."""
    groups=defaultdict(list)
    for (bits,s),weight in joint.items(): groups[rates[bits],targets[s]].append((s,weight))
    py=[total(times(w,rat(row[s])) for (bits,s),w in joint.items())
        for row in ((Q(1),Q(1,2)),(Q(0),Q(1,2)))]
    terms=[]
    for members in groups.values():
        pk=total(w for s,w in members)
        for y,row in enumerate(((Q(1),Q(1,2)),(Q(0),Q(1,2)))):
            cells=[times(w,rat(row[s])) for s,w in members if row[s]]
            if not cells: continue
            pyk=total(cells)
            terms.append(times(pyk,logarithm(divide(pyk,times(pk,py[y])))))
    information=total(terms)
    e=("exp",information)
    return information,divide(e,plus(rat(1),e))


class SwitchRig(TimeRig):
    def __init__(self, plan, *, base=(Q(1),Q(1)), factors=((Q(1),Q(2)),),
                 a=Q(1), b=Q(1), names=None, kinds=None, state_role="mood",
                 family="family", same_targets=False, **kwargs):
        switch_api()
        self.base,self.factors,self.a,self.b=tuple(base),tuple(factors),a,b
        self.part_names=tuple(names or ("mood",)+tuple(f"inert-{i}" for i in range(1,len(factors)))) if factors else ()
        self.kinds=tuple(kinds or ("mood",)+("inert",)*(len(factors)-1)) if factors else ()
        self.state_role,self.family=state_role,family
        self.targets=("same","same") if same_targets else ("A","B")
        super().__init__(plan, **kwargs)
        if same_targets:
            doc,_=world_document(prior=self.time_prior,targets=self.targets)
            model=self.record(Prediction(target="switch.same-targets",about=(),basis=(),
                content=Payload.json({"document":doc}),contract=contract("sui.f.model_source")),
                RefKind.PREDICTION,Role.MODEL)
            point=self.ledger.append(model,()).cid
            decl=self.boot_input.declaration
            self.boot_input=replace(self.boot_input,declaration=replace(decl,
                perception=replace(decl.perception,value=replace(decl.perception.value,model=point))))

    def law(self, *, rates=None, prior=None):
        return fb.PoissonLaw(run=self.clock.run,states=("A","B"),
            prior=self.time_prior if prior is None else prior,
            rates=self.base if rates is None else tuple(rates),
            origin_ns=self.origin,initial_count=self.initial_count,time_unit=self.unit,
            family=self.family,parts=tuple(fb.SwitchPart(id=name,kind=kind,multipliers=factor)
                for name,kind,factor in zip(self.part_names,self.kinds,self.factors,strict=True)),
            a=self.a,b=self.b,state_role=self.state_role)

    def candidate(self):
        member,=self.pool().members
        return member.id

    def add_time_candidate(self, *, law=None, prior=None, alpha=Q(1,3), **_):
        prior=self.time_prior if prior is None else prior
        doc,_=world_document(prior=prior,targets=self.targets)
        record=self.record(Prediction(target="switch.added",about=(),basis=(),
            content=Payload.json({"document":doc}),contract=contract("sui.f.model_source")),
            RefKind.PREDICTION,Role.MODEL)
        model=self.ledger.append(record,()).cid
        observation=replace(self.boot_input.declaration.observation_models[0].value,
            law=law or self.law(prior=prior))
        return self.host.add_candidate(boot=self.boot(),candidate=fb.BeliefCandidate(
            id="later",model=model,observation_model=observation,
            correspondence={"pairs":[["A","A"],["B","B"]]}),alpha=alpha)

    def sq(self, kind, *, candidate=None, expression=None, on=(), off=(), state=None,
           order=None, point=None, tolerance=Q(1,2**60)):
        expression=expression or self.expression()
        quantity=fb.SwitchQuantity(kind=kind,candidate=candidate or self.candidate(),
            family=self.family,on=tuple(on),off=tuple(off),state=state,order=order,point=point)
        value=self.host.query_switch_belief(belief=expression,quantity=quantity,budget=budget(tolerance))
        assert value.root==expression.root and value.quantity==quantity
        assert value.upper-value.lower<=tolerance
        assert self.host.verify_belief_value(belief=expression,value=value)
        return value

    def mixture(self, *, candidate=None, expression=None):
        expression=expression or self.expression()
        value=self.host.p_distribution(belief=expression,candidate=candidate or self.candidate(),
            family=self.family,budget=budget())
        assert value.root==expression.root and value.family==self.family
        assert value.candidate==(candidate or self.candidate())
        assert value.a==self.a and value.b==self.b and tuple(value.parts)==self.part_names
        assert self.host.verify_p_distribution(belief=expression,distribution=value)
        return value

    def check_mixture(self,joint):
        mixture=self.mixture(); expected=defaultdict(list)
        for bits in product((0,1),repeat=len(self.factors)):
            expected[self.a+sum(bits),self.b+len(bits)-sum(bits)].append(branch_weight(joint,bits))
        expected={shape:weights for shape,weights in expected.items()
                  if enclose(total(weights),64)!=(Q(0),Q(0))}
        actual=defaultdict(list)
        for component in mixture.components:
            if component.weight.lower==component.weight.upper==0:continue
            actual[component.a,component.b].append(component.weight)
        assert set(actual)==set(expected)
        for shape,weights in actual.items():
            # Repeated equal shapes are permitted, as is grouping by |z|.
            bounds=type("Bounds",(),{"lower":sum(w.lower for w in weights),
                "upper":sum(w.upper for w in weights)})()
            assert_contains(bounds,total(expected[shape]))
        assert sum(w.lower for v in actual.values() for w in v)<=1<=sum(w.upper for v in actual.values() for w in v)
        return mixture

    def check_selection_joint(self,selected,joint,rates):
        values=self.host.query_selection(selection=selected.cid,budget=budget())
        info,probability=selection_oracle(joint,rates,self.targets)
        assert values.belief_root==self.expression().root
        assert set(values.candidates)=={"peek","wait"}
        for i,action in enumerate(values.candidates):
            assert_contains(values.information[i],info if action=="peek" else rat(0))
            assert_contains(values.G[i],minus(rat(0),info) if action=="peek" else rat(0))
            assert_contains(values.probabilities[i],probability if action=="peek" else minus(rat(1),probability))


@pytest.fixture
def switches():
    active=[]
    def make(*args,**kwargs):
        switch_api();r=SwitchRig(*args,**kwargs);active.append(r);return r
    yield make
    for r in reversed(active):r.close()


def check_joint_queries(r,joint,mass):
    assert_contains(r.query("state",state="A"),marginal_state(joint,0))
    assert_contains(r.query("mass"),mass)
    for bits in product((0,1),repeat=len(r.factors)):
        on=[n for n,b in zip(r.part_names,bits) if b]
        off=[n for n,b in zip(r.part_names,bits) if not b]
        assert_contains(r.sq("switch",on=on,off=off),branch_weight(joint,bits))
        assert_contains(r.sq("state",on=on,off=off,state="A"),joint[bits,0])
    assert r.sq("p_moment",order=0).exact==1
    for order in (1,2,4):
        assert_contains(r.sq("p_moment",order=order),moment_oracle(joint,r.a,r.b,len(r.factors),order))
    assert_contains(r.sq("p_mean"),moment_oracle(joint,r.a,r.b,len(r.factors),1))
    r.check_mixture(joint)


def test_switch1_independent_beta_and_update_rulers():
    assert [bit_prior(z,Q(1),Q(1)) for z in product((0,1),repeat=2)]==[Q(1,3),Q(1,6),Q(1,6),Q(1,3)]
    assert [bit_prior(z,Q(1,2),Q(3,2)) for z in product((0,1),repeat=2)]==[Q(5,8),Q(1,8),Q(1,8),Q(1,8)]
    joint,mass,_=joint_oracle((Q(1),Q(1)),((Q(1),Q(2)),),Q(1),Q(1))
    x=expneg(1);w=divide(plus(rat(1),x),plus(rat(3),x))
    expected_mass=divide(plus(times(rat(3),x),times(x,x)),rat(4))
    pairs=[(mass,expected_mass),(branch_weight(joint,(1,)),w),
        (marginal_state(joint,0),divide(rat(2),plus(rat(3),x))),
        (moment_oracle(joint,Q(1),Q(1),1,1),divide(plus(rat(1),w),rat(3)))]
    for left,right in pairs:
        ll,lh=enclose(left,64);rl,rh=enclose(right,64)
        assert max(ll,rl)<=min(lh,rh) and max(lh-ll,rh-rl)<Q(1,2**100)
    for k in (0,1,2):
        factors=((Q(1),Q(2)),)+((Q(1),Q(1)),)*(k-1) if k else ()
        prior_joint,_,_=joint_oracle((Q(1),Q(1)),factors,Q(1,2),Q(3,2),interval=(0,0))
        for order in (1,2,4):
            expected=rising(Q(1,2),order)/rising(Q(2),order)
            assert enclose(moment_oracle(prior_joint,Q(1,2),Q(3,2),k,order),32)==(expected,expected)
    known,_,_=joint_oracle((Q(1),Q(1)),((Q(0),Q(0)),),Q(1),Q(1),symbol=T)
    assert enclose(branch_weight(known,(1,)),32)==(0,0)
    assert enclose(moment_oracle(known,Q(1),Q(1),1,1),32)==(Q(1,3),Q(1,3))
    assert enclose(moment_oracle(known,Q(1),Q(1),1,2),32)==(Q(1,6),Q(1,6))
    for prior in ((Q(1,2),Q(1,2)),(Q(1,3),Q(2,3))):
        symmetric,mass,_=joint_oracle((Q(1),Q(1)),((Q(0),Q(0)),),Q(1),Q(1),prior=prior)
        assert enclose(marginal_state(symmetric,0),32)==(prior[0],prior[0])
        assert enclose(branch_weight(symmetric,(1,)),64)[0]>Q(1,2)
        expected=times(rat(Q(1,2)),plus(rat(1),expneg(1)))
        low,high=enclose(mass,64);left,right=enclose(expected,64)
        assert max(low,left)<=min(high,right)
    conditioned,_,_=joint_oracle((Q(1),Q(1)),((Q(0),Q(0)),),Q(1),Q(1),
        prior=(Q(1,3),Q(2,3)),sensor=(Q(1),Q(1,2)))
    assert enclose(marginal_state(conditioned,0),32)==(Q(1,2),Q(1,2))
    assert finite_ce1(2)==(Q(4,5),Q(5,32)) and finite_ce1(3)==(Q(8,9),Q(9,128))


def test_switch1_K38_native_footing_control():
    r=TimeRig(script((1,1,E)))
    try:
        r.start();r.observe(0);r.update()
        assert_contains(r.query("state",state="A"),divide(rat(1),plus(rat(1),expneg(1))))
    finally:r.close()


@pytest.mark.parametrize('variant',['neutral-only','mood-only','mood-and-neutral','renamed-reordered'])
def test_switch1_gap120_knowledge_targets_merge_equal_rate_tables_and_separate_different_laws(switches,variant):
    """Decision7: compare equivalence classes, never opaque target spellings.

    The original states deliberately share one target. Consequently the only
    distinction left is the WHOLE resolved rate table, not the bit label or an
    individual state's scalar rate. Unequal Beta weights also distinguish an
    accidental regrouping of equal-rate cells from the correct law classes.
    """
    if variant=='neutral-only':
        factors=((Q(1),Q(1)),);kinds=('inert',);names=('unused-name',)
    elif variant=='mood-only':
        factors=((Q(1),Q(2)),);kinds=('mood',);names=('mood',)
    elif variant=='mood-and-neutral':
        factors=((Q(1),Q(2)),(Q(1),Q(1)));kinds=('mood','inert');names=('mood','neutral')
    else:
        factors=((Q(1),Q(1)),(Q(1),Q(2)));kinds=('inert','mood');names=('renamed-neutral','renamed-mood')
    r=switches(script((1,1,E)),factors=factors,kinds=kinds,names=names,
        a=Q(1,2),b=Q(3,2),same_targets=True,thinking=True).start()
    before=r.snapshot()
    resolved=fb.resolve_belief_candidates(r.boot(),
        reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in before}),registry=r.registry)
    assert r.snapshot()==before
    candidate,=resolved.candidates
    assert len(candidate.knowledge_targets)==len(candidate.states)==len(candidate.rates)==len(candidate.prior)
    groups=defaultdict(list)
    for target,rate,prior in zip(candidate.knowledge_targets,candidate.rates,candidate.prior,strict=True):
        groups[json.dumps(wire(target),sort_keys=True)].append((rate,prior))
    actual=sorted((tuple(sorted(rate for rate,prior in cells)),sum(prior for rate,prior in cells))
        for cells in groups.values())
    copies=2**(len(factors)-1)
    expected=([(tuple([Q(1)]*4),Q(1))] if variant=='neutral-only' else
        [(tuple([Q(1)]*(2*copies)),Q(3,4)),
         (tuple([Q(1)]*copies+[Q(2)]*copies),Q(1,4))])
    assert actual==sorted(expected)
    r.observe(0);r.update()
    joint,mass,rates=joint_oracle(r.base,r.factors,r.a,r.b)
    check_joint_queries(r,joint,mass)
    # Independent mutual information groups by resolved rate table and original
    # target. A neutral bit cannot create extra information or a smaller G.
    r.check_selection_joint(r.think(),joint,rates)


def derived_model_request_copy(r,q,model_point):
    """Keep the model named by Q*, its reader and observation plans coherent.

    The saved boot/pool declaration and the observed facts stay unchanged; they
    are precisely what U must resolve independently of the proposed model copy.
    """
    old_model=q.value['desc']['args']['model']
    value=deepcopy(q.value);value['desc']['args']['model']=model_point
    reader=time_fact_at(r,value['desc']['reader'])
    reading_value=deepcopy(reader.value)
    assert reading_value['model']==old_model
    reading_value['model']=model_point
    value['desc']['reader']=belief1_clone(r,reader,reading_value)
    for use in value['desc']['args']['observations']:
        reading=time_fact_at(r,use['reading']);plan=deepcopy(reading.value)
        assert plan['model']==old_model
        plan['model']=model_point
        args=plan['projection']['args']
        if 'correspondence' in args:
            correspondence=time_fact_at(r,args['correspondence'])
            pairs=deepcopy(correspondence.value)
            assert pairs['model']==old_model
            pairs['model']=model_point
            args['correspondence']=belief1_clone(r,correspondence,pairs)
        use['reading']=belief1_clone(r,reading,plan)
    points=set(r.snapshot())
    value['desc']['input_points']=sorted(set(value['desc']['input_points'])|points)
    value['desc']['numerical_view']['boundary']=sorted(set(value['desc']['numerical_view']['boundary'])|points)
    return time_direct_update(r,q,value)


@pytest.mark.parametrize('changed',['prior','knowledge-target'])
def test_switch1_gap120_U_rejects_a_saved_derived_model_different_from_resolution(switches,changed):
    """Decision8: both proposed model copies are valid finite documents.

    A different Point with identical contents must pass the positive control;
    refusal of the changed document cannot be credited to dangling references.
    """
    r=switches(script((1,1,E)),factors=((Q(1),Q(2)),(Q(1),Q(1)))).start()
    r.observe(0);r.update()
    check_model_copy_against_resolution(r,changed)


def check_model_copy_against_resolution(r,changed):
    saved=time_fact_at(r,r.expression().result);q=time_fact_at(r,saved.value['request'])
    model=time_fact_at(r,q.value['desc']['args']['model'])
    same_model=belief1_clone(r,model,deepcopy(model.value))
    assert same_model!=model.cid
    control=derived_model_request_copy(r,q,same_model)
    assert isinstance(control,u2.IssuedUpdate)
    # A new record Point need not have the same opaque root/digest. The
    # unchanged law/history must retain these public mathematical contents.
    for key in ('units','mass','entries','observations','terminal_ns'):
        assert wire(control.result[key])==saved.value['result'][key]

    altered=deepcopy(model.value);doc=altered['document']
    if changed=='prior':
        prior=[Q(*p) for p in doc['initial']];delta=min(prior[0],prior[1])/2
        assert delta>0
        prior[0]+=delta;prior[1]-=delta
        assert sum(prior)==1 and all(p>=0 for p in prior)
        doc['initial']=wire(prior)
    else:
        target='test:changed-knowledge-target'
        assert target not in doc['targets']
        doc['states'][0]['target']=target
        doc['targets']=list(dict.fromkeys(state['target'] for state in doc['states']))
    other_model=belief1_clone(r,model,altered)
    outcome=derived_model_request_copy(r,q,other_model)
    assert isinstance(outcome,u2.Rejected)
    # Pin a structured mismatch code, not exception prose or a generic failure.
    assert outcome.issues
    assert 'result_mismatch' in {issue.code for issue in outcome.issues}
    assert r.expression().result==saved.cid


@pytest.mark.parametrize('changed',['prior','knowledge-target'])
def test_switch1_gap120_model_copy_footing_has_valid_records_and_named_U_refusals(changed):
    """The K38 control reaches the copy/read-view mechanics before R2 exists."""
    r=TimeRig(script((1,1,E)))
    try:
        r.start();r.observe(0);r.update()
        check_model_copy_against_resolution(r,changed)
    finally:r.close()


def test_switch1_gap120_candidate_mass_is_likelihood_without_the_pool_prior(switches):
    """Decision6 conditions the mass query on M: P(h|M), not P(M)P(h|M)."""
    r=switches(script((1,1,E))).start();r.observe(0);r.update()
    first=r.candidate()
    r.add_time_candidate(law=replace(r.law(),rates=(Q(2),Q(2))),alpha=Q(1,4))
    r.update()
    old_mass=joint_oracle((Q(1),Q(1)),r.factors,r.a,r.b)[1]
    later_mass=joint_oracle((Q(2),Q(2)),r.factors,r.a,r.b)[1]
    overall=plus(times(rat(Q(3,4)),old_mass),times(rat(Q(1,4)),later_mass))
    later=r.sq('mass',candidate='later')
    assert_contains(later,later_mass)
    assert_contains(r.sq('mass',candidate=first),old_mass)
    assert_contains(r.query('mass'),overall)
    assert_contains(r.query('candidate',candidate='later'),divide(times(rat(Q(1,4)),later_mass),overall))
    assert later.lower>enclose(times(rat(Q(1,4)),later_mass),128)[1]


def test_switch1_CE1_still_uses_the_public_timed_belief_and_evaluation_entries():
    r=TimeRig(script((20,20,E),(30,30,E)),finite=True,thinking=True)
    try:
        r.direct()
        for i,end in enumerate((2,3)):
            r.observe(i);r.update();p,mass=finite_ce1(end)
            r.check(rat(p),rat(mass));r.check_selection(r.think(),rat(p),r.expression())
    finally:r.close()


@pytest.mark.parametrize("a,b",[(Q(1),Q(1)),(Q(1,2),Q(3,2))])
def test_switch1_beta_prior_is_per_bit_string_not_independent_or_binomial_twice(switches,a,b):
    r=switches(script((0,0,E)),factors=((Q(1),Q(2)),(Q(1),Q(1))),a=a,b=b).start()
    r.observe(0);r.update()
    assert r.candidate()==r.boot_input.declaration.perception.slot
    joint,mass,_=joint_oracle(r.base,r.factors,a,b,interval=(0,0))
    check_joint_queries(r,joint,mass)
    for bits in product((0,1),repeat=2):
        assert r.sq("switch",on=[n for n,z in zip(r.part_names,bits) if z],
            off=[n for n,z in zip(r.part_names,bits) if not z]).exact==bit_prior(bits,a,b)


@pytest.mark.parametrize("interval",[(1,1),(0,2)],ids=["point","uniform"])
def test_switch1_joint_update_changes_switch_p_state_and_native_evaluation(switches,interval):
    r=switches(script((*interval,E)),thinking=True).start();r.observe(0);r.update()
    joint,mass,rates=joint_oracle(r.base,r.factors,r.a,r.b,interval=interval)
    check_joint_queries(r,joint,mass)
    coarse=r.sq("switch",on=("mood",),tolerance=Q(1,16))
    assert_contains(coarse,branch_weight(joint,(1,)))
    assert coarse.upper>coarse.lower
    fine=r.sq("switch",on=("mood",),tolerance=min(Q(1,2**80),(coarse.upper-coarse.lower)/8))
    assert_contains(fine,branch_weight(joint,(1,)))
    assert 0<fine.upper-fine.lower<coarse.upper-coarse.lower
    r.check_selection_joint(r.think(),joint,rates)


@pytest.mark.parametrize("base",[(Q(1),Q(1)),(Q(1),Q(2))])
def test_switch1_k_zero_is_the_K38_law_and_p_stays_prior(switches,base):
    r=switches(script((1,1,E)),base=base,factors=(),a=Q(1,2),b=Q(3,2),thinking=True).start()
    r.observe(0);r.update();joint,mass,rates=joint_oracle(base,(),r.a,r.b)
    check_joint_queries(r,joint,mass);r.check_selection_joint(r.think(),joint,rates)
    assert r.sq("p_mean").exact==Q(1,4)
    native=TimeRig(script((1,1,E)),rates=base,thinking=True)
    try:
        native.start();native.observe(0);native.update()
        assert_contains(native.query("state",state="A"),marginal_state(joint,0))
        assert_contains(native.query("mass"),mass)
        native.check_selection(native.think(),marginal_state(joint,0),native.expression())
    finally:native.close()


@pytest.mark.parametrize("on",[False,True],ids=["all-off","all-on"])
@pytest.mark.parametrize("nonconstant",[False,True],ids=["common-base","state-dependent-base-with-inert-part"])
def test_switch1_conditioned_branches_reduce_to_fixed_rates(switches,on,nonconstant):
    kwargs=dict(base=(Q(1),Q(2)),factors=((Q(1),Q(1)),),kinds=("inert",)) if nonconstant else {}
    r=switches(script((2,2,E)),**kwargs).start();r.observe(0);r.update()
    joint,_,rates=joint_oracle(r.base,r.factors,r.a,r.b,interval=(2,2))
    branch=(int(on),);weight=branch_weight(joint,branch)
    q=rat(r.time_prior[0]) if rates[branch][0]==rates[branch][1] else divide(joint[branch,0],weight)
    fixed=TimeRig(script((2,2,E)),rates=rates[branch])
    try:
        fixed.start();fixed.observe(0);fixed.update()
        assert_contains(fixed.query("state",state="A"),q)
        name=r.part_names[0]
        assert_contains(r.sq("state",on=(name,) if on else (),off=() if on else (name,),state="A"),joint[branch,0])
    finally:fixed.close()


@pytest.mark.parametrize("initial,symbol",[(0,E),(1,T),(0,T)])
def test_switch1_zero_multiplier_keeps_the_branch_mass_and_existing_items(switches,initial,symbol):
    r=switches(script((1,1,symbol)),factors=((Q(0),Q(0)),),initial_count=initial).start()
    r.observe(0);r.update()
    joint,mass,_=joint_oracle(r.base,r.factors,r.a,r.b,symbol=symbol,initial_count=initial)
    check_joint_queries(r,joint,mass)
    if initial==0 and symbol==T:
        assert r.sq("switch",on=("mood",)).exact==0
        assert r.sq("p_mean").exact==Q(1,3)
        assert r.sq("p_moment",order=2).exact==Q(1,6)>Q(1,3)**2
    else:assert r.sq("switch",on=("mood",)).lower>0


def test_switch1_same_z_persists_and_beta_shapes_do_not_count_acquisitions(switches):
    r=switches(script((1,1,E),(3,3,E)),factors=((Q(1),Q(2)),(Q(1),Q(1)))).direct()
    r.observe(0);first=r.update();j1,z1,_=joint_oracle(r.base,r.factors,r.a,r.b)
    check_joint_queries(r,j1,z1)
    before=r.sq("switch",on=("mood",));mix1=r.mixture()
    r.host.rebuild_window()
    assert r.expression().root==first.root
    check_joint_queries(r,j1,z1)
    r.observe(1);second=r.update();j2,z2,_=joint_oracle(r.base,r.factors,r.a,r.b,interval=(3,3))
    check_joint_queries(r,j2,z2)
    after=r.sq("switch",on=("mood",));mix2=r.mixture()
    assert second.root!=first.root and after.upper<before.lower
    assert {(v.a,v.b) for v in mix1.components}=={(v.a,v.b) for v in mix2.components}
    assert all(v.a+v.b==r.a+r.b+2 for v in mix2.components)


@pytest.mark.parametrize("variant",["neutral","rename","reorder","same-law-alias"])
def test_switch1_aliases_and_inert_parts_do_not_inflate_information_or_change_p(switches,variant):
    factors=((Q(1),Q(2)),)
    kwargs={}
    if variant in ("neutral","reorder"): factors+=((Q(1),Q(1)),)
    if variant=="rename":kwargs['names']=("a-different-name",)
    if variant=="reorder":
        factors=tuple(reversed(factors));kwargs.update(names=("neutral","mood"),kinds=("inert","mood"))
    r=switches(script((1,1,E)),factors=factors,thinking=True,same_targets=True,**kwargs).start()
    r.observe(0);r.update();joint,mass,rates=joint_oracle(r.base,r.factors,r.a,r.b)
    check_joint_queries(r,joint,mass)
    # Integrating a neutral bit preserves p as well as S and predictions.
    base_joint,base_mass,base_rates=joint_oracle(r.base,((Q(1),Q(2)),),r.a,r.b)
    assert_contains(r.query("mass"),base_mass)
    for order in (1,2,4):assert_contains(r.sq("p_moment",order=order),moment_oracle(base_joint,r.a,r.b,1,order))
    if variant=="same-law-alias":
        r.check_selection_joint(r.think(),joint,rates)
        r.add_time_candidate(law=r.law(),prior=r.time_prior)
        r.update()
        assert len(r.pool().members)==2  # A mass-preserving split into identical laws.
    selected=r.think();r.check_selection_joint(selected,joint,rates)
    # same original target does NOT collapse different resolved rate tables.
    info,_=selection_oracle(base_joint,base_rates,r.targets)
    lo,_=enclose(info,128);assert lo>0


def test_switch1_neutral_switch_is_correlated_through_shared_p_without_direct_evidence(switches):
    r=switches(script((1,1,E)),factors=((Q(1),Q(2)),(Q(1),Q(1)))).start()
    r.observe(0);r.update();joint,mass,_=joint_oracle(r.base,r.factors,r.a,r.b)
    check_joint_queries(r,joint,mass)
    expected=total(w for (bits,s),w in joint.items() if bits[1])
    value=r.sq("switch",on=("inert-1",));assert_contains(value,expected)
    assert value.upper<Q(1,2)


def test_switch1_saved_mixture_weights_are_verified_against_the_root(switches):
    r=switches(script((1,1,E))).start();r.observe(0);expression=r.update()
    distribution=r.mixture();components=[]
    for i,component in enumerate(distribution.components):
        amount=Q(int(i==0))
        components.append(replace(component,weight=replace(component.weight,
            lower=amount,upper=amount,exact=amount)))
    changed=replace(distribution,components=tuple(components))
    # Save/read a TEST-owned copy; it has valid weights summing to one, but they
    # are not the root's mixture. The original proof/root are deliberately kept.
    record=r.record(Prediction(target="test.saved-mixture",about=(),basis=(),
        content=Payload.json(wire(changed)),contract=contract("test.saved_p_mixture")),RefKind.PREDICTION,Role.MODEL)
    point=r.ledger.append(record,()).cid
    stored=r.read_stored(point)[2].body.content.as_json()
    assert stored['root']==expression.root and sum(c.weight.exact for c in changed.components)==1
    assert r.host.verify_p_distribution(belief=expression,distribution=changed) is False
    assert r.host.verify_p_distribution(belief=expression,distribution=distribution)
    r.check_mixture(joint_oracle(r.base,r.factors,r.a,r.b)[0])


@pytest.mark.parametrize("first_step",[False,True],ids=["acquisition-first","step-first"])
def test_switch1_read_only_resolution_matches_host_and_direct_U_before_and_after_addition(switches,first_step):
    r=switches(script((3,3,E)),thinking=first_step,start_ns=1001)
    observer=NativeEntryObserver(fb.TimedBeliefUpdater(registry=r.registry))
    r.direct(worker_overrides={'belief_update':observer})
    if first_step:
        selected=r.think();r.enter_step(selection=selected.cid);r.finish_step(0,T);r.update()
    else:r.observe(0);r.update()
    for added in (False,True):
        if added:r.add_time_candidate(law=r.law(),prior=r.time_prior);r.update()
        before=r.snapshot();reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in before})
        declaration=r.pool().point if added else r.boot()
        resolved=fb.resolve_belief_candidates(declaration,reader=reader,registry=r.registry)
        assert r.snapshot()==before
        assert resolved.references<=set(before)
        assert {declaration,*(m.model for m in r.pool().members)}<=resolved.references
        assert {v.id for v in resolved.candidates}=={v.id for v in r.pool().members}
        for description in resolved.candidates:
            assert sum(description.prior)==1
            assert len(description.states)==len(description.prior)==len(description.rates)
            assert description.references<=resolved.references
        model=time_fact_at(r,r.pool().model)
        assert wire(resolved.document)==model.value['document']
        expression=r.expression();saved=time_fact_at(r,expression.result)
        q=time_fact_at(r,saved.value['request'])
        wid=q.value['desc']['work_id']
        # Reuse the actual native U job's public reader; never enlarge the Q*
        # input view to make the direct replay succeed.
        issued=u2.compute_timed_update(q.cid,reader=observer.contexts[wid].reader(),
            registry=r.registry,evidence=None)
        assert isinstance(issued,u2.IssuedUpdate)
        assert q.value['desc']['args']['model']==r.pool().model
        assert json.dumps(wire(issued.result),sort_keys=True)==json.dumps(saved.value['result'],sort_keys=True)
        assert issued.application_digest==saved.value['application_digest']
        assert r.snapshot()==before


@pytest.mark.parametrize("bad",['count-dependent','count-shifting'])
def test_switch1_noninterference_is_checked_before_calling_the_actor(switches,bad):
    r=switches(script((3,3,E)),thinking=True,start_ns=1001)
    decl=r.boot_input.declaration;execution=decl.execution
    reading=replace(r.state_reading,**({'independent_of_count':False} if bad=='count-dependent' else {'count_shift':-1}))
    r.boot_input=replace(r.boot_input,declaration=replace(decl,execution=replace(execution,
        value=replace(execution.value,source_readings={'peek':reading}))))
    try:
        r.start()
        if any(p.reason for p in r.host.window.status().pending):
            assert not r.actor.calls;return
        selected=r.think()
        q=r.request_where('execute_step',lambda q:q.value['desc']['args']['selection']==selected.cid)
        r.run_request(q,background=True)
        r.until(lambda:bool(r.actor.calls) or any(e.reason for e in r.host.window.status().executions)
            or any(w.purpose=='execute_step' and w.blocked_by for w in r.host.window.status().works))
    except fb.TimeBeliefError as error:
        assert error.kind in ('invalid','unsupported','unavailable') and error.reason
    except fb.StartInputError as error:assert error.reason
    assert not r.actor.calls


def test_switch1_candidate_conditional_queries_do_not_use_pool_joint_weights(switches):
    r=switches(script((1,1,E)),base=(Q(0),Q(0)),factors=((Q(1),Q(1)),),kinds=("inert",)).start()
    r.observe(0);r.update()
    r.add_time_candidate(law=r.law(),prior=r.time_prior,alpha=Q(1,4))
    r.update();later=next(m.id for m in r.pool().members if m.id=='later')
    candidate_weight=r.query('candidate',candidate=later)
    assert candidate_weight.exact==Q(1,4)
    assert r.sq('switch',candidate=later,on=(r.part_names[0],)).exact==Q(1,2)
    conditional=r.sq('state',candidate=later,state='A')
    assert conditional.exact==Q(1,2)
    assert candidate_weight.exact*conditional.exact==Q(1,8)
    assert r.query('state',state='A').exact==Q(1,2)
    with pytest.raises(fb.TimeBeliefError) as error:r.query('state',candidate=later,state='A')
    assert error.value.kind=='invalid' and error.value.field=='candidate'
    mixture=r.mixture(candidate=later)
    assert sum(x.weight.exact for x in mixture.components)==1
    assert r.sq('p_mean',candidate=later).exact==Q(1,2)


def test_switch1_K38_poisson_and_switch_family_share_the_calculation_kind(switches):
    r=switches(script((1,1,E))).start();r.observe(0);r.update()
    joint,old_mass,_=joint_oracle(r.base,r.factors,r.a,r.b)
    fixed=fb.PoissonLaw(run=r.clock.run,states=("A","B"),prior=r.time_prior,
        rates=(Q(3),Q(4)),origin_ns=r.origin,initial_count=0,time_unit=Q(1))
    r.add_time_candidate(law=fixed,alpha=Q(1,3));r.update()
    new_mass=times(rat(Q(1,2)),plus(expneg(3),expneg(4)))
    mass=plus(times(rat(Q(2,3)),old_mass),times(rat(Q(1,3)),new_mass))
    old_A=times(times(rat(Q(2,3)),old_mass),marginal_state(joint,0))
    new_A=times(rat(Q(1,6)),expneg(3))
    r.check(divide(plus(old_A,new_A),mass),mass)
    assert_contains(r.query('candidate',candidate='later'),divide(times(rat(Q(1,3)),new_mass),mass))
    result=time_fact_at(r,r.expression().result)
    assert isinstance(time_direct_update(r,time_fact_at(r,result.value['request'])),u2.IssuedUpdate)


def test_switch1_same_family_name_in_another_candidate_does_not_merge_beta_priors(switches):
    r=switches(script((1,1,E)),base=(Q(0),Q(0)),factors=((Q(1),Q(1)),),kinds=("inert",)).start()
    r.observe(0);r.update()
    later=replace(r.law(),a=Q(1,2),b=Q(3,2))
    r.add_time_candidate(law=later,alpha=Q(1,4));r.update()
    initial=next(m.id for m in r.pool().members if m.id!='later')
    assert r.sq('p_mean',candidate=initial).exact==Q(1,2)
    assert r.sq('p_mean',candidate='later').exact==Q(1,4)
    value=r.host.p_distribution(belief=r.expression(),candidate='later',family=r.family,budget=budget())
    assert value.a==Q(1,2) and value.b==Q(3,2)
    assert sum(v.weight.exact for v in value.components)==1


def test_switch1_zero_evidence_candidate_has_no_conditional_switch_or_p_distribution(switches):
    r=switches(script((1,1,T))).start();r.observe(0);r.update()
    zero=replace(r.law(),rates=(Q(0),Q(0)),parts=())
    r.add_time_candidate(law=zero,prior=r.time_prior);r.update()
    assert r.query('candidate',candidate='later').exact==0
    for operation in (lambda:r.sq('switch',candidate='later'),lambda:r.mixture(candidate='later')):
        with pytest.raises(fb.TimeBeliefError) as error:operation()
        assert error.value.reason and 'later' in error.value.targets


@pytest.mark.parametrize("kind",["p_cdf","p_quantile"])
def test_switch1_unsupported_distribution_queries_are_named_not_approximated(switches,kind):
    r=switches(script((0,0,E))).start();r.observe(0);r.update()
    with pytest.raises(fb.TimeBeliefError) as error:r.sq(kind,point=Q(1,2))
    assert error.value.kind=='unsupported' and error.value.reason
    assert r.family in error.value.targets


@pytest.mark.parametrize("bad",['missing-role','nonconstant-base','two-mood','unknown-kind'])
def test_switch1_unsupported_part_meanings_are_named(switches,bad):
    switch_api()
    kwargs={}
    if bad=='missing-role':kwargs['state_role']=None
    if bad=='nonconstant-base':kwargs['base']=(Q(1),Q(2))
    if bad=='two-mood':kwargs.update(factors=((Q(1),Q(2)),(Q(1),Q(3))),kinds=('mood','mood'))
    if bad=='unknown-kind':kwargs['kinds']=('undeclared-clock-part',)
    with pytest.raises(fb.TimeBeliefError) as error:
        r=switches(script((1,1,E)),**kwargs).start()
        reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in r.snapshot()})
        fb.resolve_belief_candidates(r.boot(),reader=reader,registry=r.registry)
    assert error.value.kind=='unsupported' and error.value.reason and error.value.targets
    assert {'family','mood','inert-1','state_role','rates'} & set(error.value.targets)
    if bad=='unknown-kind':assert 'mood' in error.value.targets


@pytest.mark.parametrize("field,value",[('a',Q(0)),('b',Q(0)),('a',Q(-1)),('b',Q(-1)),
    ('base',(Q(-1),Q(1))),('factors',((Q(1),Q(-1)),))])
def test_switch1_invalid_rational_declarations_are_rejected(switches,field,value):
    switch_api()
    with pytest.raises(fb.TimeBeliefError) as error:switches(script((1,1,E)),**{field:value})
    assert error.value.kind=='invalid' and error.value.reason and error.value.field


def test_switch1_review_R2_one_law_type_has_the_fixed_and_family_forms():
    switch_api()
    assert not hasattr(fb,'SwitchPoissonLaw')
    r=TimeRig(script((1,1,E)))
    try:
        law=r.law()
        assert (law.family,law.parts,law.a,law.b,law.state_role)==(None,(),None,None,None)
        assert {f.name for f in fields(fb.PoissonLaw)} == {
            'run', 'states', 'prior', 'rates', 'origin_ns', 'initial_count', 'time_unit',
            'family', 'parts', 'a', 'b', 'state_role', 'state_process'}
        assert law.state_process is None
    finally:r.close()


@pytest.mark.parametrize('bad',[
    {'a':Q(1)}, {'b':Q(1)}, {'parts':'inert'},
    *({'family':'family',field:value} for field in ('a','b')
      for value in (None,Q(0),Q(-1),True,0.5)),
],ids=['no-family-a','no-family-b','no-family-parts',
       'family-a-missing','family-a-zero','family-a-negative','family-a-bool','family-a-float',
       'family-b-missing','family-b-zero','family-b-negative','family-b-bool','family-b-float'])
def test_switch1_review_R2_family_parameters_must_match_the_declaration(bad):
    switch_api()
    r=TimeRig(script((1,1,E)))
    try:
        args=dict(run=r.clock.run,states=('A','B'),prior=(Q(1,2),Q(1,2)),
            rates=(Q(1),Q(1)),origin_ns=r.origin,initial_count=0,time_unit=Q(1))
        if 'family' in bad:args.update(family='family',a=Q(1,2),b=Q(3,2))
        changed=dict(bad)
        if changed.get('parts')=='inert':
            changed['parts']=(fb.SwitchPart(id='neutral',kind='inert',multipliers=(Q(1),Q(1))),)
        with pytest.raises(fb.TimeBeliefError) as error:fb.PoissonLaw(**(args|changed))
        assert error.value.kind in ('invalid','unsupported')
        assert error.value.reason and error.value.field
    finally:r.close()


def test_switch1_review_R3_K38_state_stays_marginal_and_candidate_is_invalid():
    r=TimeRig(script((1,1,E)))
    try:
        r.start();r.observe(0);r.update()
        assert_contains(r.query('state',state='A'),divide(rat(1),plus(rat(1),expneg(1))))
        with pytest.raises(fb.TimeBeliefError) as error:
            r.query('state',state='A',candidate=r.boot_input.declaration.perception.slot)
        assert error.value.kind=='invalid' and error.value.field=='candidate'
    finally:r.close()


@pytest.mark.parametrize('bad',['missing-role','nonconstant-base','two-mood','unknown-kind',None],
    ids=['mood-role','base-role','two-mood','unknown-kind','valid-control'])
def test_switch1_review_R1_birth_names_resolution_shortage_before_any_acquisition(switches,bad):
    kwargs={'thinking':True}
    if bad=='missing-role':kwargs['state_role']=None
    if bad=='nonconstant-base':kwargs['base']=(Q(1),Q(2))
    if bad=='two-mood':kwargs.update(factors=((Q(1),Q(2)),(Q(1),Q(3))),kinds=('mood','mood'))
    if bad=='unknown-kind':kwargs['kinds']=('undeclared-clock-part',)
    r=switches(script((1,1,E)),**kwargs).start();r.boot()
    public_rounds(r,count=16)
    assert not r.frame_reports() and not r.passive.calls and not r.actor.calls
    assert not r.facts(c.BELIEF_ADOPTED) and not r.facts(c.SELECTION) and not r.draw_calls
    if bad is None:
        r.until(lambda:bool(r.requests('candidate_generation')))
        return
    pending=r.host.window.status().pending
    assert any(p.reason and p.target is not None for p in pending)
    if bad=='missing-role':assert any('mood_role' in p.reason for p in pending)
    for stage in ('candidate_generation','evaluation_prepare','selection_draw','evaluation','belief_update','execute_step'):
        assert not r.requests(stage),stage
    assert not r.host.window.status().evaluations


def correspondence_views(r,pairs):
    """Read-only public resolver and U-only Q* copies with the SAME pairs.

    Only saved declaration/reading/request copies change. No synthetic prior,
    acquisition, or execution result is introduced into the host.
    """
    boot=time_fact_at(r,r.boot());saved=time_fact_at(r,r.expression().result)
    q=time_fact_at(r,saved.value['request'])
    boot_value=deepcopy(boot.value)
    boot_value['perception']['declaration']['value']['derivation']['method']['args']['correspondence']={'pairs':pairs}
    chosen_boot=belief1_clone(r,boot,boot_value)
    use=q.value['desc']['args']['observations'][0]
    reading=time_fact_at(r,use['reading']);projection=reading.value['projection']['args']
    correspondence=time_fact_at(r,projection['correspondence'])
    value=deepcopy(correspondence.value);value['pairs']=pairs
    chosen_correspondence=belief1_clone(r,correspondence,value)
    value=deepcopy(reading.value);value['projection']['args']['correspondence']=chosen_correspondence
    chosen_reading=belief1_clone(r,reading,value)
    value=deepcopy(q.value);value['desc']['args']['observations'][0]['reading']=chosen_reading
    points=set(r.snapshot())
    value['desc']['input_points']=sorted(set(value['desc']['input_points'])|points)
    value['desc']['numerical_view']['boundary']=sorted(set(value['desc']['numerical_view']['boundary'])|points)
    chosen_q=belief1_clone(r,q,value)
    reader=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in r.snapshot()})
    return chosen_boot,chosen_q,reader


@pytest.mark.parametrize('finite,pairs',[
    (False,[['X','A'],['B','B']]),(False,[]),
    (True,[['X','A'],['B','B']]),(True,[]),
],ids=['poisson-unknown-state','poisson-empty','finite-unknown-state','finite-empty'])
@pytest.mark.parametrize('entrance',['resolve','U'])
def test_switch1_review_R4_public_resolution_and_U_name_invalid_correspondence(finite,pairs,entrance):
    r=TimeRig(script((1,1,E)),finite=finite)
    try:
        r.start();r.observe(0);r.update()
        original=time_fact_at(r,time_fact_at(r,r.expression().result).value['request'])
        assert isinstance(time_direct_update(r,original),u2.IssuedUpdate)
        boot,q,reader=correspondence_views(r,pairs)
        if entrance=='resolve':
            with pytest.raises(fb.TimeBeliefError) as error:
                fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
            assert error.value.kind in ('invalid','unsupported') and error.value.reason
            assert error.value.targets or error.value.field
        else:
            try:outcome=u2.compute_timed_update(q,reader=reader,registry=r.registry,evidence=None)
            except u2.UpdateEntranceError as error:assert error.reason
            else:
                assert isinstance(outcome,u2.Rejected) and outcome.request==q
                assert outcome.issues and all(issue.code for issue in outcome.issues)
    finally:r.close()


@pytest.mark.parametrize('pairs',[[['A','A'],['B','B']],[['A','B'],['B','A']]],ids=['identity','swap'])
def test_switch1_review_R4_public_resolution_and_U_use_the_same_valid_correspondence(pairs):
    r=TimeRig(script((1,1,E)))
    try:
        r.start();r.observe(0);r.update()
        boot,q,reader=correspondence_views(r,pairs)
        resolved=fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
        candidate,=resolved.candidates
        expected={model:{'A':Q(1),'B':Q(2)}[law] for law,model in pairs}
        assert candidate.states==('A','B') and candidate.prior==(Q(1,2),Q(1,2))
        assert candidate.rates==tuple(expected[s] for s in candidate.states)
        assert set(candidate.correspondence)==set(map(tuple,pairs))
        issued=u2.compute_timed_update(q,reader=reader,registry=r.registry,evidence=None)
        assert isinstance(issued,u2.IssuedUpdate)
        units=issued.result['units']
        assert {unit['state'] for unit in units}==set(expected)
        for unit in units:
            assert Q(*unit['law']['rate'])==expected[unit['state']]
            assert Q(*unit['prior'])==Q(1,2)
    finally:r.close()
