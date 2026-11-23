"""K39-d (paper v2.02 :3583), read in full for requests122-124.

Only public saved declarations, candidate addition, U and host status are used.
Production files are not opened. Name cases retain two matrix positions.
Cardinality cases use valid one/two-state laws and normalized kernels.
"""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q

import pytest

from sui import fb, fb_contracts as c, f_update2 as u2
from test_fb_belief import (
    BeliefRig, BeliefSnapshotReader, CORRESPONDENCE, belief1_clone,
)
from test_fb_cycle import CycleRig, T, WATCHDOG, wire
from test_fb_pool import OLD, PoolRig, snapshot_records
from test_fb_time_belief import time_fact_at


def declared_name_case(r, side):
    """The same model/observation/pairs feed each of the three entrances.

    Save copies through the ordinary ledger. Nothing is injected into the host
    as an observation, prior, or worker report.
    """
    original_model=r.boot_input.declaration.perception.value.model
    model=time_fact_at(r,original_model)
    value=deepcopy(model.value)
    observation=r.boot_input.declaration.observation_models[0].value
    if side=='observation':
        observation=replace(observation,states=('A','A'))
        pairs=[['A','A'],['A','B']]
    elif side=='model':
        value['document']['states'][1]['id']='A'
        pairs=[['A','A'],['B','A']]
    elif side=='model-pairs':
        pairs=[['A','A'],['B','A']]
    elif side=='model-list':
        for state in value['document']['states']:state['id']=[state['id']]
        pairs=[['A','A'],['B','B']]
    elif side=='observation-list':
        observation=replace(observation,states=(['A'],['B']))
        pairs=[['A','A'],['B','B']]
    else:
        pairs=[['A','A'],['B','B']]
    model_point=belief1_clone(r,model,value)
    candidate=fb.BeliefCandidate(id='review2',model=model_point,
        observation_model=observation,correspondence={'pairs':pairs})
    return declared_candidate_views(r,candidate)


def declared_candidate_views(r,candidate):
    model_point=candidate.model
    observation=candidate.observation_model
    pairs=candidate.correspondence['pairs']

    boot=time_fact_at(r,r.boot());declaration=deepcopy(boot.value)
    perception=declaration['perception']
    perception['slot']=candidate.id
    perception['declaration']['value']['model']=model_point
    perception['declaration']['value']['derivation']['method']['args']['correspondence']={'pairs':pairs}
    declaration['observation_models'][0]['declaration']['value']=wire(observation)
    chosen_boot=belief1_clone(r,boot,declaration)

    saved=time_fact_at(r,r.belief().result);q=time_fact_at(r,saved.value['request'])
    request=deepcopy(q.value);request['desc']['args']['model']=model_point
    reader=time_fact_at(r,request['desc']['reader']);reader_value=deepcopy(reader.value)
    reader_value['model']=model_point
    request['desc']['reader']=belief1_clone(r,reader,reader_value)
    for use in request['desc']['args']['observations']:
        reading=time_fact_at(r,use['reading']);plan=deepcopy(reading.value)
        plan['model']=model_point;projection=plan['projection']['args']
        observed=time_fact_at(r,projection['observation_model']);observed_value=deepcopy(observed.value)
        observed_value['value']=wire(observation)
        observed_point=belief1_clone(r,observed,observed_value)
        correspondence=time_fact_at(r,projection['correspondence'])
        correspondence_value=deepcopy(correspondence.value)
        correspondence_value.update(model=model_point,observation_model=observed_point,pairs=pairs)
        projection['observation_model']=observed_point
        projection['correspondence']=belief1_clone(r,correspondence,correspondence_value)
        use['reading']=belief1_clone(r,reading,plan)
    points=set(r.snapshot())
    request['desc']['input_points']=sorted(set(request['desc']['input_points'])|points)
    request['desc']['numerical_view']['boundary']=sorted(set(request['desc']['numerical_view']['boundary'])|points)
    chosen_request=belief1_clone(r,q,request)
    records=BeliefSnapshotReader({p:r.read_stored(p)[2] for p in r.snapshot()})
    return candidate,chosen_boot,chosen_request,records


@pytest.mark.parametrize('entrance',['resolve','add','U'])
@pytest.mark.parametrize('side',['observation','model','model-pairs',None],
    ids=['duplicate-observation-names','duplicate-model-names','duplicate-model-pair-target','unique-control'])
def test_corr1_both_name_sets_must_be_unique_for_a_bijection(entrance,side):
    """K39-d 2-R1: a sorted multiset match cannot establish a bijection."""
    r=PoolRig(thinking=False)
    try:
        r.start();r.start_last_passive();r.complete_last_passive(T);r.adopt(1)
        r.assert_joint((T,))
        candidate,boot,q,reader=declared_name_case(r,side)
        before=snapshot_records(r)
        if entrance=='U':
            outcome=u2.compute_finite_update(q,reader=reader,registry=r.registry,evidence=None)
            if side is None:
                assert isinstance(outcome,u2.IssuedUpdate)
                assert wire(outcome.result)=={'joint':[[2,3],[1,3]],'evidence_mass':[3,4]}
            else:
                assert isinstance(outcome,u2.Rejected) and outcome.request==q
                # K39-d pins a named refusal, not U's particular issue-code
                # spelling. Both shape and measurement conflict are public
                # invalid-declaration codes; fields/evidence must name it.
                assert outcome.issues and all(issue.code in ('shape','measurement_conflict') for issue in outcome.issues)
                assert all(issue.fields or issue.evidence for issue in outcome.issues)
        elif entrance=='resolve':
            if side is None:
                resolved=fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                description,=resolved.candidates
                assert description.states==('A','B')
                assert set(description.correspondence)=={('A','A'),('B','B')}
            else:
                with pytest.raises(fb.TimeBeliefError) as error:
                    fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                assert error.value.reason=='correspondence' and candidate.id in error.value.targets
        else:
            if side is None:
                addition=r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
                assert isinstance(addition,fb.CandidateAddition)
                assert candidate.id in {m.id for m in r.pool().members}
            else:
                try:
                    r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
                except fb.TimeBeliefError as error:
                    assert error.reason=='correspondence' and candidate.id in error.targets
                except fb.CandidateInputError as error:
                    # Duplicate IDs make the finite source model itself
                    # invalid. Its public input guard may reject it before
                    # candidate resolution; do not count this as a phi visit.
                    assert side=='model' and error.field=='/candidate/model'
                    assert error.reason
                else:pytest.fail('non-bijective declaration was accepted')
        if side is not None or entrance!='add':assert snapshot_records(r)==before
    finally:r.close()


@pytest.mark.parametrize('pairs,expected',[
    ([['A']], 'delta:correspondence'),
    ([['A',1]], 'delta:correspondence'),
    ([['A','A'],['A','B']], 'candidate'),
    ([['A','A']], 'candidate'),
    ([['A','A'],['B','B']], 'valid'),
],ids=['short-pair','non-string-name','well-shaped-duplicate','well-shaped-missing','valid-control'])
def test_corr1_pair_shape_holds_at_delta_but_content_is_a_boot_shortage(pairs,expected):
    """K39-d 2-R2: reject shape before the shared content resolution."""
    def mutate(model,args):
        args['correspondence']={'pairs':deepcopy(pairs)}
        return model,args
    r=BeliefRig(symbols=(T,),mutate=mutate,defer_boot=True)
    try:
        candidate='perception:candidate:correspondence:'+r.boot_input.declaration.perception.slot
        reason=candidate if expected=='candidate' else expected
        def ready():
            if expected=='valid':return bool(r.facts(CORRESPONDENCE)) and bool(r.facts(c.OBSERVATION_PLAN_2))
            return any(p.reason==reason for p in r.host.window.status().pending)
        r.until(ready)
        boot=r.one(c.BOOT_DECLARATION).cid;status=r.host.window.status()
        named=[p.reason for p in status.pending if p.target==boot]
        if expected=='valid':
            assert not any(s.startswith(('delta:','perception:candidate:')) for s in named)
        else:
            assert reason in named
            if expected=='candidate':assert 'delta:correspondence' not in named
            else:assert not any(s.startswith('perception:candidate:') for s in named)
            assert not r.facts(CORRESPONDENCE) and not r.facts(c.OBSERVATION_PLAN_2)
        assert not r.requests('belief_update')
        assert not r.facts(c.BELIEF_ADOPTED) and not r.facts(c.UPDATE_RESULT)
        assert r.host.halted is None and not r.host.interruptions()
    finally:r.close()


def boot_name_case(r,side):
    """Prepare the malformed first declaration before calling native start.

    Change only model IDs or observation state names. Observation matrices,
    dimensions, string pairs, targets and probabilities retain their values.
    """
    def edit(document):
        if side=='model-list':
            for state in document['states']:state['id']=[state['id']]
    candidate=r.save_candidate(OLD,edit_document=edit)
    if side=='observation-list':
        candidate=replace(candidate,observation_model=replace(
            candidate.observation_model,states=(['A'],['B'])))
    install_boot_candidate(r,candidate)


def install_boot_candidate(r,candidate):
    declaration=r.boot_input.declaration
    perception=declaration.perception
    derivation=perception.value.derivation
    args=dict(derivation.method.args)
    args['correspondence']=deepcopy(candidate.correspondence)
    perception=replace(perception,value=replace(perception.value,
        model=candidate.model,derivation=replace(derivation,
            method=replace(derivation.method,args=args))))
    observation=replace(declaration.observation_models[0],value=candidate.observation_model)
    r.boot_input=replace(r.boot_input,declaration=replace(declaration,
        perception=perception,observation_models=(observation,)))


@pytest.mark.parametrize('entrance',['resolve','start','add'])
@pytest.mark.parametrize('side',['model-list','observation-list',None],
    ids=['list-model-ids','list-observation-names','string-control'])
def test_corr1_nonstring_state_names_are_named_refusals_at_public_entrances(entrance,side):
    """K39-d 3-R1: do not hash an unvalidated JSON name or leak TypeError."""
    r=PoolRig(thinking=entrance=='start')
    try:
        if entrance=='start':
            boot_name_case(r,side)
            CycleRig.start(r)  # Native fb.start, without a helper swallowing input errors.
            try:
                r.host.run_until(lambda _state:bool(r.facts(c.BOOT_DECLARATION)),timeout=WATCHDOG)
            except fb.FbInputError as error:
                # Inline observation names violate Boot's typed input shape.
                # This counterpart can be constructed in Python, but cannot
                # reach the saved Boot/plan; a saved model Point can and must.
                assert side=='observation-list'
                assert error.reason=='shape' and error.field=='/declaration/observation_models/0/value'
                assert not r.facts(c.BOOT_DECLARATION)
                assert not r.requests('belief_update') and not r.facts(c.BELIEF_ADOPTED)
                assert not r.passive.calls and not r.actor.calls
                assert r.host.halted is None and not r.host.interruptions()
                return
            assert r.facts(c.BOOT_DECLARATION)
            reason='perception:candidate:correspondence:'+r.boot_input.declaration.perception.slot
            if side is None:
                r.until(lambda:bool(r.requests('candidate_generation')))
                assert not any(p.reason.startswith('perception:candidate:') for p in r.host.window.status().pending)
            else:
                r.until(lambda:any(p.reason==reason for p in r.host.window.status().pending))
                boot=r.boot()
                assert any(p.reason==reason and p.target==boot for p in r.host.window.status().pending)
                assert not any(p.reason.startswith('delta:') and p.target==boot for p in r.host.window.status().pending)
                for stage in ('candidate_generation','evaluation_prepare','selection_draw','evaluation','belief_update','execute_step'):
                    assert not r.requests(stage),stage
                assert not r.facts(c.BELIEF_ADOPTED) and not r.facts(c.UPDATE_RESULT)
            assert not r.passive.calls and not r.actor.calls
            assert r.host.halted is None and not r.host.interruptions()
            return

        r.start();r.start_last_passive();r.complete_last_passive(T);r.adopt(1)
        candidate,boot,_q,reader=declared_name_case(r,side)
        before=snapshot_records(r)
        if entrance=='resolve':
            if side is None:
                resolved=fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                description,=resolved.candidates
                assert description.states==('A','B')
            else:
                with pytest.raises(fb.TimeBeliefError) as error:
                    fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                assert error.value.reason=='correspondence' and candidate.id in error.value.targets
        elif side is None:
            added=r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
            assert isinstance(added,fb.CandidateAddition)
            assert candidate.id in {m.id for m in r.pool().members}
        else:
            try:r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
            except fb.TimeBeliefError as error:
                assert error.reason=='correspondence' and candidate.id in error.targets
            except fb.CandidateInputError as error:
                # A model rejected at the public input guard cannot reach the
                # common resolution; preserve that distinction in the report.
                expected={'model-list':'/candidate/model',
                    'observation-list':'/candidate/observation_model'}[side]
                assert error.field==expected and error.reason
            else:pytest.fail('non-string state names were accepted')
        if side is not None or entrance!='add':assert snapshot_records(r)==before
        assert r.host.halted is None and not r.host.interruptions()
    finally:r.close()


def cardinality_candidate(r,case):
    """Each side is a valid finite law; only the proposed bijection can fail.

    One-state kernels use the sum of a normalized departure column for each
    outcome. Summing the outcome probabilities is therefore exactly one.
    """
    one_model=case in ('two-observation-one-model','one-to-one')
    one_observation=case in ('one-observation-two-model','one-to-one')
    def edit(document):
        if not one_model:return
        original=document['states'][0]
        document['states']=[{'id':'X','target':original['target']}]
        document['targets']=[original['target']]
        document['initial']=wire((Q(1),))
        for kernel in document['kernels']:
            for outcome in kernel['outcomes']:
                probability=sum((Q(*row[0]) for row in outcome['matrix']),Q(0))
                outcome['matrix']=wire(((probability,),))
    candidate=r.save_candidate(OLD,edit_document=edit)
    observation=candidate.observation_model
    if one_observation:
        controls=[]
        for control in observation.controls:
            outcomes=tuple(replace(outcome,matrix=((sum(
                (row[0] for row in outcome.matrix),Q(0)),),))
                for outcome in control.kernel.outcomes)
            controls.append(replace(control,kernel=replace(control.kernel,outcomes=outcomes)))
        args=dict(observation.independence.args)
        args['weights_by_initial_state']=wire((args['weights_by_initial_state'][0],))
        observation=replace(observation,states=('Y',),controls=tuple(controls),
            independence=replace(observation.independence,args=args))
    pairs={
        'two-observation-one-model':[['A','X'],['B','X']],
        'one-observation-two-model':[['Y','A'],['Y','B']],
        'one-to-one':[['Y','X']],
        'two-to-two':[['A','A'],['B','B']],
    }[case]
    return replace(candidate,id='review-cardinality',observation_model=observation,
        correspondence={'pairs':pairs})


@pytest.mark.parametrize('entrance',['resolve','start','add'])
@pytest.mark.parametrize('case',[
    'two-observation-one-model','one-observation-two-model','one-to-one','two-to-two'])
def test_corr1_different_state_counts_cannot_form_a_bijection(entrance,case):
    """K39-d 2-R1: a surjection or a one-to-many relation is not a bijection."""
    invalid=case in ('two-observation-one-model','one-observation-two-model')
    r=PoolRig(thinking=entrance=='start')
    try:
        if entrance=='start':
            candidate=cardinality_candidate(r,case)
            install_boot_candidate(r,candidate)
            CycleRig.start(r)
            r.host.run_until(lambda _state:bool(r.facts(c.BOOT_DECLARATION)),timeout=WATCHDOG)
            boot=r.boot()
            reason='perception:candidate:correspondence:'+r.boot_input.declaration.perception.slot
            if invalid:
                r.until(lambda:any(p.reason==reason for p in r.host.window.status().pending))
                assert any(p.reason==reason and p.target==boot for p in r.host.window.status().pending)
                assert not any(p.reason.startswith('delta:') and p.target==boot for p in r.host.window.status().pending)
                for stage in ('candidate_generation','evaluation_prepare','selection_draw','evaluation','belief_update','execute_step'):
                    assert not r.requests(stage),stage
                assert not r.facts(c.BELIEF_ADOPTED) and not r.facts(c.UPDATE_RESULT)
            else:
                r.until(lambda:bool(r.requests('candidate_generation')))
                assert not any(p.reason.startswith('perception:candidate:') for p in r.host.window.status().pending)
            assert not r.passive.calls and not r.actor.calls
            assert r.host.halted is None and not r.host.interruptions()
            return

        r.start();r.start_last_passive();r.complete_last_passive(T);r.adopt(1)
        candidate=cardinality_candidate(r,case)
        candidate,boot,_q,reader=declared_candidate_views(r,candidate)
        before=snapshot_records(r)
        if entrance=='resolve':
            if invalid:
                with pytest.raises(fb.TimeBeliefError) as error:
                    fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                assert error.value.reason=='correspondence' and candidate.id in error.value.targets
            else:
                resolved=fb.resolve_belief_candidates(boot,reader=reader,registry=r.registry)
                description,=resolved.candidates
                assert description.states==(('X',) if case=='one-to-one' else ('A','B'))
                assert sum(description.prior)==1
                assert set(description.correspondence)==set(map(tuple,candidate.correspondence['pairs']))
        elif invalid:
            with pytest.raises(fb.TimeBeliefError) as error:
                r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
            assert error.value.reason=='correspondence' and candidate.id in error.value.targets
        else:
            added=r.host.add_candidate(boot=r.boot(),candidate=candidate,alpha=Q(1,2))
            assert isinstance(added,fb.CandidateAddition)
            assert candidate.id in {m.id for m in r.pool().members}
        if invalid or entrance!='add':assert snapshot_records(r)==before
        assert r.host.halted is None and not r.host.interruptions()
    finally:r.close()
