"""F-a v0.14 facts-only contract dry-run; assembly is not certification.

No skips/xfails. Skeleton NotImplementedError is deliberately visible.
Primary declarations/records are built independently of math calls. All success
oracles retain fixed_gate_f.json; no success is changed to certificate_incomplete.
"""
from copy import copy, deepcopy
from dataclasses import fields, replace
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
from pathlib import Path
import ast
import inspect
import json
import pytest

from sui import f, f_contracts as fc, f_facts as ff, f_model as fm
from sui.contracts import ContractRef, ContractBook
from sui.records import Category, Observed, Decided, Prediction, JobOpened, AttemptStarted, Payload
from sui.rate import RationalInterval
from gate_f_facts_cases import (
    BUDGET,FIXED,SECOND,METHOD,GENERATOR,PRODUCER,Reader,MissingBodyReader,FactsCase,
    K_STAGES,assemble,assemble_knowledge,assemble_c1,assemble_limit,add_observations,
    add_computation,add_draw,prepare,histories,bound,plain,canonical,digest,predicate,
    finite_world,diagonal,outcome,bit_kernel,idle_kernel,execute,policy,action,declaration,
    mixed_measure,limit_document,assemble_legacy_bridge,assemble_legacy_bridge_quadrant,prepare_bridge,
    review5_timed_case,review5_adoption_case,review5_pending_cost_case,
    review5_generation_case,review5_table_case,review5_table_coverage_case,review5_structural_branch_case,
    Review5ContextCase,review5_prior_context_case,review5_closure_primary_case,
    review5_closure_draw_case,review5_closure_route_case,
    review5_first_unknown_observed,review5_candidate_nonancestor_basis,
    review5_reference_acquisition_case,review5_reference_event_case,review5_unavailable_route_case,
)

def rational(value):
    return F(*value)

@lru_cache(maxsize=None)
def independent_log_bounds(value):
    """Fraction-only atanh series with a proved geometric remainder; no sui math."""
    value = F(value)
    assert value > 0
    if value == 1:
        return F(0), F(0)
    if value < 1:
        low, high = independent_log_bounds(1/value)
        return -high, -low
    # Reduce to [1,2], so z <= 1/3. 160 terms give far more than 100 digits.
    power = 0
    while value > 2:
        value /= 2
        power += 1
    z = (value-1)/(value+1)
    term, total = z, F(0)
    for k in range(160):
        total += 2*term/(2*k+1)
        term *= z*z
    remainder = 2*term/(321*(1-z*z))
    low, high = total, total+remainder
    if power:
        l2, h2 = independent_log_bounds(F(2))
        low, high = low+power*l2, high+power*h2
    return low, high

def reference_interval(value):
    if isinstance(value, dict):
        if 'coeffs' in value:
            low = high = F(0)
            for prime, coefficient in value['coeffs'].items():
                c = rational(coefficient)
                lo, hi = independent_log_bounds(F(prime))
                low += c*(lo if c >= 0 else hi)
                high += c*(hi if c >= 0 else lo)
            return low, high
        return tuple(F(x) for x in value['interval'])
    point = rational(value) if isinstance(value, (list, tuple)) else F(value)
    return point, point

def negate(value):
    if isinstance(value, dict) and 'coeffs' in value:
        return {'coeffs': {p: [-c[0], c[1]] for p, c in value['coeffs'].items()}}
    low, high = reference_interval(value)
    return {'interval': (str(-high), str(-low))}

def interval_product(left, right):
    products = [x*y for x in left for y in right]
    return min(products), max(products)

@lru_cache(maxsize=None)
def expression_bounds(expr):
    """Independently enclose the public expression grammar using outward rounding.

    Decimal ln/exp are correctly rounded; adjacent Decimal values bracket their
    exact result. Rational input conversion is directed before monotone functions.
    This only checks returned expressions, never generates a fixture's oracle.
    """
    if expr.op == 'rational':
        return F(expr.value), F(expr.value)
    if expr.op == 'neg':
        lo, hi = expression_bounds(expr.arg)
        return -hi, -lo
    if expr.op == 'add':
        parts = [expression_bounds(x) for x in expr.args]
        return sum((x[0] for x in parts), F(0)), sum((x[1] for x in parts), F(0))
    if expr.op == 'mul':
        result = (F(1), F(1))
        for arg in expr.args:
            result = interval_product(result, expression_bounds(arg))
        return result
    if expr.op == 'div':
        lo, hi = expression_bounds(expr.denominator)
        assert not lo <= 0 <= hi
        return interval_product(expression_bounds(expr.numerator), (1/hi, 1/lo))
    if expr.op in ('log', 'exp'):
        lo, hi = expression_bounds(expr.arg)
        if expr.op == 'log' and lo == hi:
            return independent_log_bounds(lo)
        if expr.op == 'exp' and lo == hi == 0:
            return F(1), F(1)
        result = []
        with localcontext() as ctx:
            ctx.prec = 110
            for point, rounding in ((lo, ROUND_FLOOR), (hi, ROUND_CEILING)):
                ctx.rounding = rounding
                d = Decimal(point.numerator)/Decimal(point.denominator)
                value = d.ln() if expr.op == 'log' else d.exp()
                result.append(F(value.next_minus() if rounding == ROUND_FLOOR else value.next_plus()))
        return tuple(result)
    raise AssertionError(f'unknown public ExactReal op: {expr.op!r}')

def exact_rational(expr):
    low, high = expression_bounds(expr)
    assert low == high, 'expected an exactly rational expression'
    return low

def assert_quantity(actual, expected, *, wrong=None):
    low, high = reference_interval(expected)
    assert actual.status == 'finite', actual
    assert actual.bounds is not None or actual.exact is not None
    if actual.bounds is not None:
        lo, hi = actual.bounds.lower, actual.bounds.upper
        # Enclosing an independently proved interval is sufficient to enclose truth.
        # No tolerance may repair a bound on the wrong side of the true value.
        assert lo <= low <= high <= hi, ('does not enclose oracle', lo, hi, low, high)
        if actual.exact is None:
            assert low-F(1, 10**24) <= lo and hi <= high+F(1, 10**24)
        else:
            assert hi-lo <= high-low + F(1, 10**20), 'vacuous bounds'
    if actual.exact is not None:
        elo, ehi = expression_bounds(actual.exact)
        # Expression identity is checked numerically against the independent oracle;
        # the returned bounds above have the stronger, directed containment check.
        assert elo <= high and low <= ehi, ('exact expression disagrees', elo, ehi, low, high)
        assert ehi-elo <= F(1, 10**90)
        if actual.bounds is not None:
            assert lo <= ehi and elo <= hi
        else:
            lo, hi = elo, ehi
    if wrong is not None:
        wlo, whi = reference_interval(wrong)
        assert hi < wlo or lo > whi, 'returned bounds still admit wrong_*'


FINITE_SCENES = (
    ('FA01','default',{}),('FA02','default',{}),('FA02','closed',{}),('FA03','default',{}),
    ('FA04','default',{}),('FA04','nonzero',{}),('FA05','default',{}),('FA05','independent',{}),
    ('FA06','default',{}),('FA07','default',{}),('FA07','first_action_cost',{}),
    ('FA08','default',{}),('FA08','alias-first',{}),('FA08','alias-last',{}),('FA08','alias-only',{}),
    ('FA08','unsupported',{}),('FA09','default',{}),('FA10','default',{}),
    ('FA11','default',{}),('FA11','finite',{'H':SECOND}),('FA12','default',{}),('FA13','default',{}),
    ('FA14','default',{}),('FA15','default',{}),('FA15','hundred',{}),
    ('FA16','default',{}),('FA16','at_2',{}),('FA16','at_2',{'H':SECOND}),
    ('FA16','composite',{}),('FA16','split',{}),('FA16','composite',{'scope_name':'one_step'}),
    ('FA16','split',{'scope_name':'one_step'}),('FA18','default',{}),('FA19','default',{}),('FA21','default',{}))
SCENE_IDS=[name+'-'+variant+('-'+str(args) if args else '') for name,variant,args in FINITE_SCENES]


def assert_raw_assembly(case):
    entries=case.ledger.entries(); assert entries
    for entry in entries:
        record=case.ledger.record(entry.cid)
        assert entry.id == record.id
        assert record.body.content.media_type=='application/json'
        for parent in entry.parents:assert case.ledger.record(parent).category in (Category.FACT,Category.PREFERENCE)
        assert record.body.contract not in (fc.DECISION_ATTEMPTED,fc.DECISION,fc.JOB)
        if isinstance(record.body,Observed) and record.body.caused_by is not None:
            started,=[e for e in entries if e.id==record.body.caused_by]
            assert isinstance(case.ledger.record(started.cid).body,AttemptStarted)
        if isinstance(record.body,JobOpened):
            decision,=[e for e in entries if e.id==record.body.decision]
            assert isinstance(case.ledger.record(decision.cid).body,Decided)
    if 'candidates' in case.points:
        assert len(case.candidate_value.input_order)==len(case.candidate_value.continuation.after)
        assert tuple(x.candidate for x in case.candidate_value.continuation.after)==case.candidate_value.input_order
        for operation in case.document['operations']:
            assert set(operation)=={'id','family','args','start','policy','termination','termination_kind','prediction','execution','proof'}
        assert case.fixed_parents==tuple(sorted(set(case.fixed_parents)))
        assert set(case.fixed_parents).issubset(e.cid for e in entries)


@pytest.mark.parametrize('name,variant,args',FINITE_SCENES,ids=SCENE_IDS)
def test_assembly_FA01_to_FA21_primary_records_only(name,variant,args):
    case=assemble(name,variant,**args);assert_raw_assembly(case)
    assert len(case.ledger.entries()) >= 8
    if name in ('FA01','FA08','FA10','FA14','FA15','FA19'):
        assert len(case.ledger.entries())==8
    assert case.ledger.record(case.points['model']).category is Category.PREDICTION
    assert case.ledger.record(case.points['origin']).body.content.as_json()=={'model':case.points['model']}
    context=case.ledger.record(case.points['context'])
    reading=case.ledger.record(case.points['judgment_clock']).body.content.as_json()['reading']
    assert context.at.mono_ns > reading['time_ns']
    assert 'available' not in case.__dict__ and 'incorporated' not in case.__dict__


@pytest.mark.parametrize('stage',K_STAGES)
def test_assembly_K_seven_distinct_original_histories(stage):
    case=assemble_knowledge(stage);assert_raw_assembly(case)
    contracts=[case.ledger.record(e.cid).body.contract for e in case.ledger.entries()]
    assert contracts.count(fc.MEASUREMENT)==1 and contracts.count(fc.OBSERVATION_BINDING)==1
    assert contracts.count(fc.KNOWLEDGE_ADOPTED)==int(stage in ('adopted','tampered-proof'))
    assert contracts.count(fc.COMPUTATION_COMPLETED)==int(stage in ('computed-unacquired','computed-acquired','adopted','tampered-proof'))
    expected_acquisitions=0 if stage in ('raw','legacy-missing') else 1+int(stage in ('computed-acquired','adopted','tampered-proof'))
    assert contracts.count(fc.CONTENT_ACQUIRED)==expected_acquisitions
    if case.computation:
        request=case.ledger.record(case.computation['request']).body.content.as_json()
        assert request['algorithm_draws']==[] and request['purpose']=='belief'
        assert set(case.raw+case.plans+case.bindings+[case.points['origin']])<=set(request['inputs'])
        result=case.ledger.record(case.computation['result']).body.content.as_json()
        assert result['output']=={'contract':plain(fc.FINITE_UPDATE_RESULT),'value':{'joint':[[3,4],[1,4]],'evidence_mass':[1,2]}}


@pytest.mark.parametrize('variant,label,midwindow,bad',[
    ('10','y0',False,None),('01','y0',False,None),('10','y1',False,None),
    ('10','y0',True,None),('10','y0',False,'saturated'),('10','y0',False,'gap')])
def test_assembly_FA20_C1_original_windows(variant,label,midwindow,bad):
    case=assemble_c1(variant,label=label,midwindow=midwindow,bad=bad);assert_raw_assembly(case)
    assert case.document['scheme']=='sui.model.9'
    assert ('read-report' in case.points) is not midwindow
    assert len(case.ledger.entries())==11 if midwindow else len(case.ledger.entries())==12


@pytest.mark.parametrize('both,proof',[(False,'valid'),(True,'valid'),(True,'none'),(True,'missing_checker')])
def test_assembly_FA15_FA17_limit_declaration_only(both,proof):
    case=assemble_limit(both=both,proof=proof);assert_raw_assembly(case)
    assert case.ledger.record(case.points['limit']).body.content.as_json()==limit_document(both=both,proof=proof)
    assert case.ledger.record(case.points['limit']).category is Category.PREDICTION
    assert len(case.ledger.entries())==1


def test_assembly_new_contracts_and_constructor_fields():
    book=ContractBook()
    for contract in fc.FACTS_DECLARATIONS:
        book.register(contract);assert book.get(contract.ref)==contract
    assert 'semantic_key' not in {x.name for x in fields(f.FActionDeclaration)}
    assert {x.name for x in fields(f.FCandidateDeclaration)}=={'model','input_order','measure','generation','continuation'}
    assert {x.name for x in fields(f.FFactsRequest)}=={'fixed_parents','model','candidates','preferences','scope','context','method'}


def read_call(case,fn=ff.read_f_histories_from_facts):
    return fn(case.reader,fixed_parents=case.fixed_parents,model_ref=case.points['model'],
        context_ref=case.points['context'],registry=f.builtin_f_registry(),budget=BUDGET)


@pytest.mark.parametrize('stage',K_STAGES)
def test_K_seven_cases_derive_available_adoption_proof_and_pending(stage):
    case=assemble_knowledge(stage)
    if stage=='legacy-missing':
        with pytest.raises(f.FReplayUnavailable) as err:histories(case)
        assert err.value.reason=='missing_input';return
    if stage=='tampered-proof':
        with pytest.raises(f.FInputError) as err:histories(case)
        assert err.value.reason=='proof_mismatch';return
    got=histories(case)
    assert len(got.E.links)==1 and got.E.links[0].measurement==case.measurements[0]
    assert set(got.E.links[0].records)=={case.ref(case.raw[0])}
    assert got.K.available==(() if stage=='raw' else (case.measurements[0],))
    adopted=stage=='adopted'
    assert got.K.incorporated==((case.measurements[0],) if adopted else ())
    assert got.K.belief==(case.ref(case.computation['result']) if adopted else None)
    assert got.K.query_proofs==()
    assert got.K.normalization_proofs==((case.ref(case.computation['proof']),) if stage in ('computed-acquired','adopted') else ())
    assert got.K.kernel_basis==(case.ref(case.bindings[0]),)
    assert bool(got.K.pending)==(stage in ('computed-unacquired','computed-acquired'))
    if got.K.pending:
        assert all(x.key.startswith('sha256:') for x in got.K.pending)
        assert all(case.ref(case.computation['request']) in x.basis for x in got.K.pending)
    context_record=case.ledger.record(case.points['context'])
    reading=case.ledger.record(case.points['judgment_clock']).body.content.as_json()['reading']
    assert got.context.now_ns==reading['time_ns'] != context_record.at.mono_ns


@pytest.mark.parametrize('bad',['unknown_version','bool_integer','unreduced','axis','unknown_key','duplicate'])
def test_FA01_model11_invalid_primary_declaration_rejected(bad):
    doc=deepcopy(finite_world('FA01')[0])
    if bad=='unknown_version':doc['contract']['version']='future'
    elif bad=='bool_integer':doc['kernels'][0]['outcomes'][0]['elapsed_ns']=True
    elif bad=='unreduced':doc['initial'][0]=[2,4]
    elif bad=='axis':doc['kernels'][0]['outcomes'][0]['matrix'].pop()
    elif bad=='unknown_key':doc['unexpected']=True
    data=canonical(doc)
    if bad=='duplicate':data=b'{"scheme":"sui.model.11",'+data[1:]
    with pytest.raises(f.FInputError):fm.f_model11_from_json(data)


def test_FA01_model11_and_mathematical_artifact_roundtrip():
    case=assemble('FA01');model=fm.f_model11_from_json(canonical(case.document))
    assert fm.f_model11_json(model)==canonical(case.document)
    assert fm.f_model11_ref(model)==digest(case.document)
    prepared,draw,root=bound(case)
    data=ff.f_math_json(root);assert data==root.canonical_bytes
    registry=f.builtin_f_registry()
    restored=ff.restore_f_root(data,reader=root.reader,registry=registry,budget=BUDGET)
    assert plain(restored)==plain(root.value)
    verified=ff.verify_f_math_result(data,reader=root.reader,registry=registry,budget=BUDGET)
    assert verified.kind=='math' and verified.root_key==root.value.root_key
    assert verified.artifact_digest==digest({'domain':'sui.f.math_artifact/2','artifact':json.loads(data)})  # 今の約束 E-05


@pytest.mark.parametrize('name,variant,expected,mass',[
    ('FA02','default',F(4,5),F(5,16)),('FA02','closed',F(1,2),F(1)),
    ('FA03','default',F(16,17),F(17,128)),('FA05','default',F(3,4),F(1,2)),
    ('FA05','independent',F(9,10),F(5,16))])
def test_FA02_FA03_FA05_finite_update_from_certified_observations(name,variant,expected,mass):
    case=assemble(name,variant);got=histories(case)
    model=got.model
    belief=f.initial_finite_belief(model)
    for obs in got.observations:
        belief=f.apply_f_observation(model,belief,observation=obs)
        assert f.apply_f_observation(model,belief,observation=obs)==belief
    assert belief.joint==(expected,1-expected) and belief.evidence_mass==mass
    assert expected != (F(1,2) if variant!='closed' else F(4,5))


def evaluation(case,*,u=F(1,2)):
    prepared,draw,root=bound(case,u=u)
    return root.value,f.evaluate_f_recursive(root.value,budget=BUDGET)


def assert_choice(selected,root,name,u):
    assert isinstance(selected,f.Selected)
    assert selected.chosen.id==name and selected.root.root_key==root.root_key
    assert plain(selected.root.selection_draw.value)=={'u':plain(u)}


@pytest.mark.parametrize('variant',['default','nonzero'])
def test_FA04_recursive_and_enumerated_child_choices_keep_fixed_numbers(variant):
    root,recursive=evaluation(assemble('FA04',variant))
    paths=f.enumerate_f_paths(root,budget=BUDGET)
    assert {tuple(x.args['path_action'] for x in row.actions) for row in paths.rows}=={('M','M'),('M','Q'),('Q','M'),('Q','Q')}
    oracle=FIXED['FA04_nonzero_path_cost' if variant=='nonzero' else 'FA04']
    for result in (recursive,f.evaluate_f_enumerated(root,paths,budget=BUDGET)):
        assert result.candidates==('M','Q')
        for i,name in enumerate(('M','Q')):
            for key,wrong in oracle.items():
                if key.startswith('wrong_'):assert_quantity(result.J[i],oracle['root']['J_'+name],wrong=wrong['J_'+name])
        assert_quantity(result.q_star[0],oracle['root']['q_M'])
    children=[node for node in paths.nodes if node.alternatives==('M2','Q2')]
    assert {x.candidate for x in children}=={'M','Q'}
    for node in children:
        row=oracle['after_first_M_y1' if node.candidate=='M' else 'after_first_Q']
        assert_quantity(node.q_star[0],row['q_M']);assert_quantity(node.V,row['V'])


@pytest.mark.parametrize('stage',['raw','acquired','adopted'])
def test_FA06_knowledge_progress_is_not_new_evidence(stage):
    case=assemble_knowledge(stage);root,result=evaluation(case)
    assert len(root.E.links)==1
    assert root.K.available==(() if stage=='raw' else (case.measurements[0],))
    assert root.K.incorporated==((case.measurements[0],) if stage=='adopted' else ())
    assert_quantity(result.information[0].additional,0)
    info=FIXED['FA05']['information_one']
    assert_quantity(result.J[0],0 if stage=='adopted' else negate(info))


@pytest.mark.parametrize('variant',['default','first_action_cost'])
def test_FA07_received_common_term_retains_value_at_H_zero(variant):
    root,result=evaluation(assemble('FA07',variant))
    oracle=FIXED['FA07_first_action_cost' if variant=='first_action_cost' else 'FA07']
    for i,name in enumerate(result.candidates):
        assert_quantity(result.information[i].already_received,oracle['already_received'])
        assert_quantity(result.information[i].additional,0)
        assert_quantity(result.J[i],oracle['J'][name] if variant=='first_action_cost' else oracle['old_G'])


@pytest.mark.parametrize('variant',['default','alias-first','alias-last','alias-only','unsupported'])
def test_FA08_primary_aliases_and_unsupported_candidate(variant):
    case=assemble('FA08',variant)
    if variant=='unsupported':
        # R06: high-level semantic failure is an artifact; low-level stays an exception.
        assert_review5_missing_contract(case,'proof','unregistered-proof')
        return
    root,result=evaluation(case)
    assert len(result.candidates)==2
    for q in result.q_star:assert_quantity(q,F(1,2),wrong=F(2,3))
    representative='Q-display' if variant in ('alias-first','alias-only') else 'Q'
    assert tuple(a.id for a in root.candidates.candidates)==(representative,'M')
    expected_aliases={'Q':'Q-display'} if variant=='alias-first' else ({'Q-display':'Q'} if variant=='alias-last' else {})
    assert dict(root.candidates.aliases)==expected_aliases
    assert not set(root.candidates.aliases)&{representative,'M'}


@pytest.mark.parametrize('cells',[1,2])
def test_FA09_primary_mixed_measure_partition_has_no_fake_root(cells):
    case=assemble('FA09')
    measure=case.candidate_value.measure
    part=f.MeasurePartition(atoms=('now',),cells=tuple(f.MeasureCell(component='later',lower=F(2*i,cells),upper=F(2*(i+1),cells)) for i in range(cells)))
    checked=f.check_f_measure_partition(measure,partition=part)
    assert checked.total==2 and checked.atom_masses[0].mass/checked.total==rational(FIXED['FA09']['now'])
    assert checked.cell_masses==(F(1,cells),)*cells
    result=prepare(case).value
    assert isinstance(result,f.NoDecision) and (result.outcome,result.reason) in (
        ('incomplete','normalization_unproved'),('incomplete','certificate_incomplete'))


def test_FA10_information_not_clock_tie():
    root,result=evaluation(assemble('FA10'))
    assert_quantity(result.information[0].additional,FIXED['FA10']['I_now'])
    assert_quantity(result.information[1].additional,FIXED['FA10']['I_later'])
    assert_quantity(result.q_star[1],FIXED['FA10']['q_later'],wrong=FIXED['FA10']['wrong_time_tie'])


@pytest.mark.parametrize('name,H,key',[('FA11',None,'unbounded'),('FA11',SECOND,'finite_H_1'),('FA12',None,None)])
def test_FA11_FA12_scope_and_permanent_nonarrival(name,H,key):
    root,result=evaluation(assemble(name,H=H))
    oracle=FIXED[name] if key is None else FIXED[name][key]
    for i,n in enumerate(('W','A')):assert_quantity(result.information[i].additional,oracle['I_'+n])
    assert_quantity(result.q_star[0],oracle['q_W'])
    assert_choice(f.certify_f_choice(result,u=F(1,2)),root,oracle['selected'],F(1,2))


@pytest.mark.parametrize('steps',[1,2])
def test_FA13_prefix_tail_preserves_nonzero_remainder(steps):
    _,_,artifact=bound(assemble('FA13'));root=artifact.value
    paths=f.enumerate_f_prefix(root,steps=steps,budget=BUDGET)
    tail=f.certify_f_tail(root,candidate='W',prefix=paths,budget=BUDGET)
    oracle=FIXED['FA13']['n'+str(steps)]
    assert_quantity(tail.residual_mass,F(1,4)+F(3,4*2**steps))
    assert_quantity(tail.information_prefix,oracle['I_W_lower']);assert_quantity(tail.information_remaining,oracle['tail_R'])
    result=f.evaluate_f_prefix(root,steps=steps,budget=BUDGET)
    lo,hi=map(reference_interval,oracle['q_W_interval'])
    assert result.q_star[0].bounds.lower<=lo[0] and result.q_star[0].bounds.upper>=hi[1]
    choice=f.certify_f_choice(result,u=F(1,2))
    if steps==2:assert_choice(choice,root,'W',F(1,2))
    else:assert isinstance(choice,f.NoDecision) and choice.reason=='selection_boundary'


def test_FA14_quiet_selected_is_not_incomplete_and_low_budget_replays():
    case=assemble('FA14');root,result=evaluation(case,u=F(1,6))
    for i,n in enumerate(('Q','M')):
        assert_quantity(result.G[i],FIXED['FA14']['G_'+n]);assert_quantity(result.q_star[i],FIXED['FA14']['q'][i])
    assert_choice(f.certify_f_choice(result,u=F(1,6)),root,'Q',F(1,6))
    tiny=replace(BUDGET,max_cells=1,max_terms=1,max_refinements=1)
    pending=f.evaluate_f(root,budget=tiny)
    assert isinstance(pending,f.NoDecision) and pending.outcome=='incomplete' and pending.attempt_id is None
    data=ff.f_math_json(pending)
    restored=ff.restore_f_math_result(data,reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    assert plain(restored.value)==plain(pending)


@pytest.mark.parametrize('variant,key',[('default','one_perfect_measurement'),('hundred','hundred_of_same_bit')])
def test_FA15_repeated_static_bit_saturates(variant,key):
    root,result=evaluation(assemble('FA15',variant))
    assert_quantity(result.information[0].additional,FIXED['FA15'][key],wrong=FIXED['FA15']['wrong_sum_hundred'])
    assert result.normalization.Z.lower <= 2 <= result.normalization.Z.upper


@pytest.mark.parametrize('both,proof',[(False,'valid'),(True,'valid'),(True,'none'),(True,'missing_checker')])
def test_FA15_FA17_limit_Point_needs_public_mathematical_issuance(both,proof):
    case=assemble_limit(both=both,proof=proof)
    expected=('rejected','undefined_infinite_difference' if both else 'information_divergent') if proof=='valid' else ('incomplete','certificate_incomplete')
    registry=f.builtin_f_registry()
    saved=ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=BUDGET)
    assert_no_decision(saved.value,*expected)
    assert_math_replay(saved,registry)
    data=json.loads(ff.f_math_json(saved))
    assert data['contract']=={'name':'sui.f.math_artifact','version':'2'}
    assert data['input']=={'kind':'limit','value':{'declaration':case.points['limit']}}
    assert data['calls']==[{'op':'limit','args':{'budget':plain(BUDGET)}}]
    assert data['output']==0


@pytest.mark.parametrize('variant,H,scope,key',[
    ('default',None,None,'unbounded'),('default',SECOND,None,'finite_H_1'),
    ('at_2',None,None,'unbounded'),('at_2',SECOND,None,'finite_H_1'),
    ('composite',None,None,'one_composite_wait_then_measure'),('split',None,None,'two_operations_wait_and_measure'),
    ('composite',None,'one_step','one_step_composite'),('split',None,'one_step','one_step_two_operations_first')])
def test_FA16_scope_and_primary_continuation_packaging(variant,H,scope,key):
    root,result=evaluation(assemble('FA16',variant,H=H,scope_name=scope))
    packaged=variant in ('composite','split')
    oracle=FIXED['FA16']['packaging' if packaged else ('arrive_at_2' if variant=='at_2' else 'arrive_at_1')]
    assert_quantity(result.information[0 if packaged else 1].additional,oracle[key])


@pytest.mark.parametrize('op,left,right',[(op,a,b) for op in ('and','or') for a,b in product(('true','false','unknown'),repeat=2)])
def test_FA18_cached_boolean_truth_table_from_predicate_Point(op,left,right):
    case=assemble('FA18')
    # §3-10-16-補5: direct PredicateRef JSON under PREDICATE.
    # Unknown uses an unacquired policy position, not a fabricated quantity interval.
    terms={'true':predicate(True),'false':predicate(False),
        'unknown':f.PredicateRef(name='policy_end',version='1',args={})}
    expression=f.PredicateRef(name=op,version='1',args={'terms':[plain(terms[left]),plain(terms[right])]})
    point=case.predict('predicate',fc.PREDICATE,expression,basis=(case.points['model'],))
    case.context()
    prepared=ff.prepare_f_predicate_from_facts(case.reader,fixed_parents=case.fixed_parents,
        model_ref=case.points['model'],context_ref=case.points['context'],predicate_ref=point,quantity_refs=(),
        registry=f.builtin_f_registry(),budget=BUDGET)
    before=case.ledger.entries()
    results=[f.check_predicate(prepared.predicate,snapshot=prepared.snapshot,resources=prepared.resources) for _ in range(100)]
    assert all(r.value==FIXED['FA18'][op][left+','+right] for r in results)
    assert all(r.work==results[0].work and r.missing==results[0].missing for r in results)
    assert case.ledger.entries()==before


def test_contract_FA18_quantity_Point_binding_is_required():
    case,pred,points=quantity_case()
    prepared=prepared_quantities(case,pred,points)
    bindings={b.point:b for b in prepared.quantity_bindings}
    assert set(bindings)==set(points)
    for point in points:
        binding=bindings[point]
        assert binding.record_digest.startswith('sha256:')
        assert binding.quantity.key==digest({'domain':'sui.f.quantity_point/1',
            'declaration':point,'record_digest':binding.record_digest})
        assert binding.quantity.key!=point
        quantity=prepared.snapshot.quantities[binding.quantity]
        assert quantity.proof.name=='sui.f.quantity' and quantity.proof.version=='2'
        proof=plain(quantity.proof.args)['binding']
        assert proof['declaration']==point and proof['record_digest']==binding.record_digest
        assert proof['unit']=='dimensionless'
        assert {d['point'] for d in proof['dependencies']}>=set(case.raw)
    assert prepared.predicate.args['left']['key']==bindings[points[0]].quantity.key
    assert prepared.predicate.args['right']['key']==bindings[points[1]].quantity.key
    result=f.check_predicate(prepared.predicate,snapshot=prepared.snapshot,resources=prepared.resources)
    assert result.value=='true' and not result.missing



def test_FA19_one_root_one_u_refinement_and_replay():
    case=assemble('FA19');prepared,draw,artifact=bound(case,u=F(1,2));root=artifact.value
    before=case.ledger.entries()
    for budget in (BUDGET,replace(BUDGET,tolerance=F(1,10**30))):
        result=f.evaluate_f_recursive(root,budget=budget)
        assert_choice(f.certify_f_choice(result,u=F(1,2)),root,'M',F(1,2))
        assert result.root.root_key==root.root_key and result.root.selection_draw==root.selection_draw
    data=ff.f_math_json(artifact)
    restored=ff.restore_f_root(data,reader=artifact.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    assert restored.root_key==root.root_key and restored.selection_draw==root.selection_draw
    assert case.ledger.entries()==before


def generated_candidate_case(u):
    doc,_=finite_world('FA19');case=FactsCase(doc,name='generated')
    generator=ContractRef('fixture.f.bit_order','1')
    request=f.FCandidateRequest(domain='sui.f.candidate_request/1',model=case.points['model'],
        generator=generator,args={},basis=(case.points['model'],))
    point=add_draw(case,digest(request),u=u,purpose='candidate_generation')
    case.candidate(('Q','M') if u<F(1,2) else ('M','Q'),generator=generator,draws=(point,))
    case.context()
    registry=f.builtin_f_registry()
    template=next(x for x in registry.declarations if x.kind=='generator' and x.ref==GENERATOR)
    # Explicit fixture.f.bit_order/1 law, spec §3-10-16-補8.
    # CandidateInput is compiler output; it is never fixture input to the factory.
    def check_order(*,args,input,context):
        def require(condition):
            if not condition:raise f.FInputError('invalid_draw',field='/generation')
        require(args=={} and len(input['draws'])==1)
        draw=input['draws'][0];request_value=draw['request']
        require(draw['purpose']=='candidate_generation' and request_value['purpose']=='candidate_generation')
        require(request_value['law']=={'name':'uniform_unit','version':'1'} and request_value['args']=={})
        require(draw['ordinal']==0 and request_value['ordinal']==0)
        require(draw['context_key']==digest(request) and request_value['context_key']==digest(request))
        require(set(draw['value'])=={'u'})
        actual_u=F(*draw['value']['u']);require(0<=actual_u<1)
        wanted=['Q','M'] if actual_u<F(1,2) else ['M','Q']
        require([x['id'] for x in input['actions']]==wanted)
        return input
    return case,f.make_f_registry(declarations=registry.declarations+(replace(template,ref=generator),),
        implementations=registry.implementations+(f.CapabilityImplementation(kind='generator',ref=generator,implementation=check_order,identity='fixture.check_order/1'),))


@pytest.mark.parametrize('u',[F(1,4),F(1,2),F(3,4)])
def test_assembly_FA19_candidate_generation_primary_draw_before_D(u):
    case,registry=generated_candidate_case(u);assert_raw_assembly(case)
    point,=case.candidate_value.generation.draws
    draw=case.ledger.record(point).body.content.as_json()
    assert draw['request']['purpose']=='candidate_generation'
    assert case.candidate_value.input_order==(('Q','M') if u<F(1,2) else ('M','Q'))
    assert len(case.ledger.entries())==9


@pytest.mark.parametrize('u',[F(1,4),F(1,2),F(3,4)])
def test_FA19_generation_and_selection_use_separate_primary_draws(u):
    case,registry=generated_candidate_case(u)
    prepared=prepare(case,registry=registry)
    assert isinstance(prepared.value,f.FProblem)
    generation,=case.candidate_value.generation.draws
    with pytest.raises(f.FInputError):ff.bind_f_draw(prepared,generation,reader=case.reader,budget=BUDGET)
    selection=add_draw(case,prepared.value.problem_key,u=F(1,2))
    assert generation!=selection
    artifact=ff.bind_f_draw(prepared,selection,reader=case.reader,budget=BUDGET)
    result=f.evaluate_f_recursive(artifact.value,budget=BUDGET)
    assert_choice(f.certify_f_choice(result,u=F(1,2)),artifact.value,case.candidate_value.input_order[1],F(1,2))
    for q in result.q_star:assert_quantity(q,F(1,2))
    before=case.ledger.entries()
    refined=f.evaluate_f_recursive(artifact.value,budget=replace(BUDGET,tolerance=F(1,10**30)))
    assert refined.root.root_key==artifact.value.root_key and refined.root.selection_draw==artifact.value.selection_draw
    assert case.ledger.entries()==before


@pytest.mark.parametrize('variant,label,delay',[('10','y0',0),('01','y0',0),('10','y1',0),('10','y0',SECOND)])
def test_FA20_C1_windows_are_not_management_record_times(variant,label,delay):
    from sui.rate_model import RateModel
    case=assemble_c1(variant,label=label,delay=delay)
    got=read_call(case,ff.read_c1_from_facts)
    assert [(x.start_ns,x.end_ns,x.count) for x in got.frames]==[(0,SECOND,int(variant[0])),(SECOND,2*SECOND,int(variant[1]))]
    assert got.frames[1].probe.label==label and got.frames[1].source_record==case.ref(case.points['read-report'])
    summary=f.initial_c1_summary(RateModel(declaration=canonical(case.document)),run=case.clock.run,origin_ns=0)
    for frame in got.frames:
        summary=f.update_c1_summary(summary,frame=frame)
        assert f.update_c1_summary(summary,frame=frame)==summary
    expected=rational(FIXED['FA20'][variant]['P_S2_state0'])
    assert f.c1_state_marginal(summary)==(expected,1-expected)
    assert (summary.N,summary.T_s,summary.end_ns)==(1,F(2),2*SECOND)
    assert dict(summary.probe_counts)=={'p':(1,0) if label=='y0' else (0,1)}


@pytest.mark.parametrize('bad',['saturated','gap'])
def test_FA20_unproved_window_remains_incomplete(bad):
    with pytest.raises(f.FIncomplete) as err:read_call(assemble_c1(bad=bad),ff.read_c1_from_facts)
    assert err.value.reason=='c1_closure_unproved'


def test_FA20_midwindow_clock_leaves_pending_without_zero_count():
    case=assemble_c1(midwindow=True)
    got=read_call(case,ff.read_c1_from_facts)
    assert [(x.start_ns,x.end_ns,x.count) for x in got.frames]==[(0,SECOND,1)]
    assert got.pending and all(isinstance(x,f.DependencyRef) for x in got.pending)
    assert case.ledger.record(case.points['judgment_clock']).body.content.as_json()['reading']['time_ns']==3*SECOND//2


def test_FA21_one_step_keeps_independent_legacy_numbers():
    root,result=evaluation(assemble('FA21'));oracle=FIXED['FA21_minimal_bridge']
    for i,name in enumerate(oracle['order']):
        assert_quantity(result.J[i],oracle['J'][name]);assert_quantity(result.q_star[i],oracle['q'][i])
    assert_choice(f.certify_f_choice(result,u=F(1,2)),root,oracle['selected'],F(1,2))


def test_contract_FA21_original_old_model_bridge_needs_facts_entry():
    case,model=assemble_legacy_bridge();registry=f.builtin_f_registry()
    prepared=prepare_bridge(case,registry=registry)
    assert isinstance(prepared.value,f.FLegacyBridgeProblem)
    draw=add_draw(case,prepared.value.problem_key,u=F(1,2))
    result=ff.evaluate_legacy_bridge_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    compared=result.value;assert isinstance(compared,f.LegacyComparison)
    oracle=FIXED['FA21_minimal_bridge']
    # Independent old public path, on a separate ledger so adopt cannot affect F.
    from sui.agent import Agent,plan
    from gate_f_cases import legacy_input
    old_model,ledger,hand=legacy_input()
    agent=Agent(model=old_model,lineage='facts-bridge-control')
    agent.adopt(ledger,clock=hand.clock,ids=hand.ids)
    old=plan(agent.view(now_ns=0,observed_ns=0),('M','Q'),u=.5).content.as_json()
    for i,name in enumerate(('M','Q')):
        assert_quantity(compared.new_J[i],oracle['J'][name])
        assert_quantity(compared.new_probabilities[i],oracle['q'][i])
        assert compared.old_J[i]==old['J'][i]
        assert compared.old_probabilities[i]==old['q_pi'][i]
        assert_quantity(compared.reconstructed_information[i],FIXED['FA15']['one_perfect_measurement'] if name=='M' else F(0))
    assert compared.old_choice==compared.new_choice==old['chosen']==oracle['selected']
    assumption=next(a.value for a in compared.assumptions if a.contract==ContractRef('sui.f.legacy_bridge_facts','1'))
    assumption=plain(assumption)
    assert assumption['request']==plain(prepared.value.request)
    assert assumption['problem_key']==prepared.value.problem_key and assumption['draw']==draw
    assert assumption['u']==[1,2] and assumption['measurement_time']=='report'
    assert assumption['targets']==['x0','x1']
    assert assumption['candidate_map']==[{'legacy':x,'finite':x} for x in ('M','Q')]
    assert assumption['durations']==[{'candidate':x,'ns':SECOND} for x in ('M','Q')]
    assert assumption['scope']['name']=='one_step'
    assert assumption['o0']=={'mode':'absent','source_attempts':[],'averaged_before_choice':True}
    assert_math_replay(result,registry)


@pytest.mark.parametrize('scene',['then-view','current-capability-only','lost-then-view'])
def test_past_prepare_missing_capability_uses_historical_read_image(scene):
    case=assemble('FA08');current=f.builtin_f_registry()
    old=f.make_f_registry(declarations=current.declarations,
        implementations=tuple(x for x in current.implementations if x.kind!='kernel'))
    saved=prepare(case,registry=old)
    assert isinstance(saved.value,f.NoDecision)
    assert (saved.value.outcome,saved.value.reason,saved.value.attempt_id)==('incomplete','algorithm_unavailable',None)
    data=ff.f_math_json(saved)
    if scene=='then-view':
        verified=ff.verify_f_math_result(data,reader=saved.reader,registry=old,budget=BUDGET)
        replay=ff.restore_f_math_result(data,reader=saved.reader,registry=old,budget=BUDGET)
        assert verified.kind=='math' and plain(replay.value)==plain(saved.value)
    else:
        # 今の約束 E-06 (2026-10-11): the image is bound by content; a lost image
        # means the current ledger differs (a later fact), not a re-made reader.
        if scene=='lost-then-view':case.observe('later-fact',ContractRef('fixture.f.later','1'),{})
        reader=saved.reader if scene=='current-capability-only' else Reader(case.ledger)
        registry=current if scene=='current-capability-only' else old
        for api in (ff.verify_f_math_result,ff.restore_f_math_result):
            with pytest.raises(f.FReplayUnavailable) as error:
                api(data,reader=reader,registry=registry,budget=BUDGET)
            assert error.value.reason==('method_unavailable' if scene=='current-capability-only' else 'missing_input')


@pytest.mark.parametrize('scene',['then-view','current-capability-only','lost-then-view'])
def test_past_preflight_requires_factory_for_historical_image(scene):
    case=assemble('FA08');current=f.builtin_f_registry()
    old=f.make_f_registry(declarations=current.declarations,
        implementations=tuple(x for x in current.implementations if x.kind!='kernel'))
    capability=f.RequiredCapability(kind='kernel',ref=ContractRef('finite_kernel','1'),implementation_required=True)
    request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=case.points['model'],
        required_records=(case.points['context'],),required_capabilities=(capability,))
    saved=ff.check_f_preflight_from_facts(case.reader,request,registry=old,budget=BUDGET)
    assert_no_decision(saved.value,'incomplete','algorithm_unavailable')
    audit=plain(saved.value.proof.args)
    assert saved.value.proof.name=='sui.f.preflight_facts' and saved.value.proof.version=='1'
    assert audit['request_digest']==digest(request)
    assert audit['model']['point']==case.points['model']
    assert audit['model']['entry_present'] and audit['model']['body_present']
    assert audit['model']['record_digest'].startswith('sha256:')
    assert [r['point'] for r in audit['records']]==[case.points['context']]
    assert audit['capabilities']==[{'kind':'kernel','ref':plain(capability.ref),'declared':True,'implemented':False}]
    assert len(audit['failures'])==1 and audit['failures'][0]['reason']=='algorithm_unavailable'
    data=ff.f_math_json(saved);wire=json.loads(data)
    assert wire['input']=={'kind':'preflight','value':plain(request)}
    assert wire['calls']==[{'op':'preflight','args':{'budget':plain(BUDGET)}}] and wire['output']==0
    if scene=='then-view':assert_math_replay(saved,old)
    else:
        # 今の約束 E-06 (2026-10-11): the image is bound by content; a lost image
        # means the current ledger differs (a later fact), not a re-made reader.
        if scene=='lost-then-view':case.observe('later-fact',ContractRef('fixture.f.later','1'),{})
        reader=saved.reader if scene=='current-capability-only' else Reader(case.ledger)
        registry=current if scene=='current-capability-only' else old
        for api in (ff.verify_f_math_result,ff.restore_f_math_result):
            with pytest.raises(f.FReplayUnavailable) as error:api(data,reader=reader,registry=registry,budget=BUDGET)
            assert error.value.reason==('method_unavailable' if scene=='current-capability-only' else 'missing_input')



# §3-10-16-14 structural A/B/C; no receipt/consumption B7 or C7 here.
def test_structure_A1_import_direction_only():
    # This is the only source inspection: imports, never function statements.
    path=Path(__file__).parents[1]/'src/sui/_f_eval.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    forbidden={'f_model','f_entry','f_facts','_f_world','ledger'}
    imports=[node for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))]
    for node in imports:
        if isinstance(node,ast.ImportFrom):
            assert not set((node.module or '').split('.')) & forbidden
            assert not {a.name for a in node.names} & {'FReader','f_model_from_json','f_model11_from_json','make_f_registry'}
        else:assert all(not set(a.name.split('.')) & forbidden for a in node.names)


def test_structure_A3_public_signatures_do_not_request_derived_inputs():
    expected={'prepare_f_from_facts','bind_f_draw','evaluate_f_from_draw','read_f_histories_from_facts',
              'read_c1_from_facts','prepare_f_predicate_from_facts','f_math_json','restore_f_root','verify_f_math_result','restore_f_math_result',
              'check_f_preflight_from_facts','diagnose_f_limit_from_facts','certify_f_limit_from_facts',
              'prepare_legacy_bridge_from_facts','evaluate_legacy_bridge_from_draw'}
    exported={name for name,value in vars(ff).items() if not name.startswith('_') and inspect.isfunction(value)}
    assert expected<=exported
    forbidden={'E','K','context','semantic_key','aliases','resolved','manifest','resources','records','facts','fact_ancestors','clock','ids','draws'}
    for name in expected:assert not set(inspect.signature(getattr(ff,name)).parameters)&forbidden
    assert set(inspect.signature(ff.prepare_f_from_facts).parameters)=={
        'reader','fixed_parents','model_ref','candidate_ref','preference_refs','scope_request','context_ref','registry','method','budget'}
    assert not {'begin_f_attempt','make_f_records','commit_f','FiringBook','DrawBook'}&exported
    assert set(f.FMathOpV1.__args__)=={'prepare','bind_draw','scope','enumerate','recursive','enumerated','prefix','prefix_evaluation','tail','choice','evaluate','preflight','limit_certificate','limit'}
    assert set(f.FMathOpV2.__args__)==set(f.FMathOpV1.__args__)|{'legacy_bridge_prepare','legacy_bridge'}
    assert f.FMathOp is f.FMathOpV2


def test_structure_A2_raw_readers_and_registry_unavailable_after_bind(monkeypatch):
    case=assemble('FA13');_,_,artifact=bound(case);root=artifact.value
    def forbidden(*args,**kwargs):raise AssertionError('evaluation returned to raw facts/resolution')
    with monkeypatch.context() as patch:
        patch.setattr(Reader,'record',forbidden)
        patch.setattr(fm,'f_model11_from_json',forbidden)
        patch.setattr(f,'builtin_f_registry',forbidden)
        scope=f.certify_f_scope(root,budget=BUDGET)
        prefix=f.enumerate_f_prefix(root,steps=2,budget=BUDGET)
        tail=f.certify_f_tail(root,candidate='W',prefix=prefix,budget=BUDGET)
        result=f.evaluate_f_recursive(root,budget=BUDGET)
        assert scope and tail.prefix.steps==2
        assert_choice(f.certify_f_choice(result,u=F(1,2)),root,'W',F(1,2))
    # A finite model also exercises complete enumeration from the same issued world.
    _,_,finite=bound(assemble('FA04'))
    with monkeypatch.context() as patch:
        patch.setattr(Reader,'record',forbidden);patch.setattr(fm,'f_model11_from_json',forbidden)
        paths=f.enumerate_f_paths(finite.value,budget=BUDGET)
        got=f.evaluate_f_enumerated(finite.value,paths,budget=BUDGET)
        assert_quantity(got.q_star[0],FIXED['FA04']['root']['q_M'])


@pytest.mark.parametrize('mode',['handmade','decoded','changed','foreign'])
def test_structure_A4_B2_uncertified_and_foreign_roots_rejected(mode):
    from sui import f_entry as codec
    case=assemble('FA08');_,_,artifact=bound(case)
    root=artifact.value
    if mode=='decoded':bad=codec.f_from_json(codec.f_json(root),contract=fc.ROOT_FACTS)
    elif mode=='changed':
        with pytest.raises(TypeError):replace(root,gamma=F(2))
        bad=copy(root)
        object.__setattr__(bad,'gamma',F(2))
        assert bad is not root and bad.gamma==2 and root.gamma==1
    elif mode=='handmade':
        public_fields={x.name:getattr(root,x.name) for x in fields(root)}
        with pytest.raises(TypeError):f.FRoot(**public_fields)
        # Negative input only: bypass construction without reading private state.
        bad=object.__new__(f.FRoot)
        for name,value in public_fields.items():object.__setattr__(bad,name,value)
        assert bad is not root and plain(bad)==plain(root)
    else:
        _,_,other=bound(assemble('FA10'));foreign=f.enumerate_f_prefix(other.value,steps=1,budget=BUDGET)
        with pytest.raises((f.FInputError,f.FReplayMismatch)):
            f.certify_f_tail(root,candidate='Q',prefix=foreign,budget=BUDGET)
        return
    for call in (lambda:f.certify_f_scope(bad,budget=BUDGET),lambda:f.enumerate_f_paths(bad,budget=BUDGET),
                 lambda:f.evaluate_f_recursive(bad,budget=BUDGET),lambda:f.enumerate_f_prefix(bad,steps=0,budget=BUDGET)):
        with pytest.raises(f.FInputError):call()


@pytest.mark.parametrize('change',['manifest','missing-body','other-input','late-fact'])
def test_structure_A5_B4_restore_rebuilds_from_same_primary_facts(change):
    case=assemble('FA08');_,_,artifact=bound(case);data=ff.f_math_json(artifact)
    if change=='manifest':
        wire=json.loads(data);wire['claim']['value']['world_manifest']['request']['model_ref']='sha256:'+'0'*64
        with pytest.raises(f.FReplayMismatch):
            ff.verify_f_math_result(canonical(wire),reader=artifact.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    elif change=='missing-body':
        with pytest.raises(f.FReplayUnavailable):
            ff.restore_f_root(data,reader=MissingBodyReader(case.ledger,case.points['model']),registry=f.builtin_f_registry(),budget=BUDGET)
    elif change=='other-input':
        other=assemble('FA10')
        with pytest.raises((f.FReplayUnavailable,f.FReplayMismatch)):
            ff.verify_f_math_result(data,reader=other.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    else:
        before=plain(artifact.value)
        case.observe('late',ContractRef('fixture.late_fact','1'),{'later':True})
        restored=ff.restore_f_root(data,reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
        assert plain(restored)==before and case.ref(case.points['late']) not in restored.facts


@pytest.mark.parametrize('fault',['root-proof','child-proof','continuation','alias-continuation','generator','predicate','implementation'])
def test_structure_B1_B2_every_deep_primary_declaration_is_checked(fault):
    doc,ops=finite_world('FA04')
    if fault in ('root-proof','child-proof'):
        doc['operations'][0 if fault=='root-proof' else 2]['proof']['name']='absent-proof'
    elif fault=='continuation':doc['policies'][2]['nodes'][0]['kernel']='absent-kernel'
    elif fault=='predicate':doc['operations'][2]['start']['name']='absent-predicate'
    if fault=='alias-continuation':
        alias=deepcopy(doc['operations'][2]);alias['id']='M2-copy';doc['operations'].append(alias)
        choose=doc['policies'][0]['nodes'][1];choose['operations'].append('M2-copy');choose['next']['M2-copy']='first'
    case=assemble('FA04',document=doc)
    if fault=='generator':
        cv=replace(case.candidate_value,generation=replace(case.candidate_value.generation,generator=ContractRef('absent-generator','1')))
        case.predict('candidates',fc.CANDIDATE_DECLARATION,cv,basis=(case.points['model'],));case.context()
    if fault=='implementation':
        reg=f.builtin_f_registry();reg=f.make_f_registry(declarations=reg.declarations,implementations=tuple(i for i in reg.implementations if i.kind!='kernel'))
        got=prepare(case,registry=reg).value
        assert isinstance(got,f.NoDecision) and (got.outcome,got.reason)==('incomplete','algorithm_unavailable')
    elif fault in ('root-proof','child-proof','generator','predicate'):
        # R06: do not encode the old, reversed expectation at the prepare boundary.
        kind='proof' if fault.endswith('proof') else fault
        assert_review5_missing_contract(case,kind,'absent-'+kind)
    else:
        with pytest.raises((f.FSpecificationMissing,f.FInputError)) as err:prepare(case)
        assert err.value.reason in ('missing_contract','unresolved_reference','alias_continuation_conflict')


@pytest.mark.parametrize('field',['q_star','Z','bounds','different-u'])
def test_structure_B3_choice_cannot_reuse_changed_evaluation(field):
    case=assemble('FA08');root,result=evaluation(case)
    if field=='different-u':
        with pytest.raises(f.FInputError):f.certify_f_choice(result,u=F(1,10))
        return
    fake=f.FQuantity(status='finite',exact=f.ExactReal(op='rational',value=F(1)),bounds=RationalInterval(F(1),F(1)),proof=None,reason=None)
    if field=='q_star':bad=replace(result,q_star=(fake,)+result.q_star[1:])
    elif field=='Z':bad=replace(result,normalization=replace(result.normalization,Z=RationalInterval(F(1),F(1))))
    else:bad=replace(result,q_star=(replace(result.q_star[0],bounds=RationalInterval(F(0),F(0))),)+result.q_star[1:])
    with pytest.raises((f.FInputError,f.FReplayMismatch)):f.certify_f_choice(bad,u=F(1,2))


def quantity_case(*,acquired=True,unit='dimensionless',logical=False):
    case=assemble('FA18')
    if acquired:case.acquire(case.raw)
    points=[]
    for name,value in [('left',F(1)),('right',F(2))]:
        points.append(case.predict('quantity-'+name,fc.QUANTITY_DECLARATION,
            f.FQuantityConstantDeclaration(kind='rational_constant',value=value,unit=unit if name=='left' else 'dimensionless',
                provenance=tuple(case.raw)),basis=tuple(case.raw)))
    if acquired:case.acquire(points)
    # §3-10-16-補5: the primary key is a declaration Point; compiler assigns internal keys.
    expression=f.PredicateRef(name='interval_compare',version='1',args={
        'left':{'key':points[0]},'relation':'lt','right':{'key':points[1]},
        'provenance':[str(case.ref(p)) for p in case.raw]})
    if logical:expression=f.PredicateRef(name='not',version='1',args={'term':plain(expression)})
    predicate_point=case.predict('predicate',fc.PREDICATE,expression,basis=tuple(points))
    case.context()
    return case,predicate_point,tuple(points)


def prepared_quantities(case,predicate_point,points):
    return ff.prepare_f_predicate_from_facts(case.reader,fixed_parents=case.fixed_parents,model_ref=case.points['model'],
        context_ref=case.points['context'],predicate_ref=predicate_point,quantity_refs=points,
        registry=f.builtin_f_registry(),budget=BUDGET)


@pytest.mark.parametrize('acquired',[False,True])
def test_assembly_FA18_quantity_provenance_and_predicate_points(acquired):
    case,pred,points=quantity_case(acquired=acquired);assert_raw_assembly(case)
    value=case.ledger.record(pred).body.content.as_json()
    assert value['args']['left']['key']==points[0] and value['args']['right']['key']==points[1]
    for point in points:
        content=case.ledger.record(point).body.content.as_json()
        assert content['provenance']==case.raw and content['kind']=='rational_constant'


@pytest.mark.parametrize('acquired',[False,True])
def test_FA18_quantity_primary_provenance_and_cached_only_result(acquired):
    case,pred,points=quantity_case(acquired=acquired)
    prepared=prepared_quantities(case,pred,points)
    before=case.ledger.entries()
    results=[f.check_predicate(prepared.predicate,snapshot=prepared.snapshot,resources=prepared.resources) for _ in range(100)]
    assert {x.value for x in results}==({'true'} if acquired else {'unknown'})
    assert all(x.work==results[0].work for x in results)
    assert case.ledger.entries()==before
    if not acquired:assert results[0].work is not None and results[0].missing


@pytest.mark.parametrize('field',['result','proof','query','unit','logical-child'])
def test_structure_B5_C8_quantity_changes_cannot_transfer_authentication(field):
    case,pred,points=quantity_case(logical=field=='logical-child')
    prepared=prepared_quantities(case,pred,points)
    original=prepared.snapshot
    values=dict(original.quantities)
    key=next(iter(values));quantity=values[key]
    if field in ('result','logical-child'):
        values[key]=replace(quantity,bounds=RationalInterval(F(5),F(5)),exact=f.ExactReal(op='rational',value=F(5)))
    elif field=='proof':values[key]=replace(quantity,proof=None)
    elif field=='query':
        values[f.QuantityRef(key='different-query')]=values.pop(key)
    else:
        # A declaration of a different dimension must not authenticate the old query.
        other,pred,points=quantity_case(unit='nat');before=other.ledger.entries()
        with pytest.raises(f.FInputError) as error:prepared_quantities(other,pred,points)
        assert error.value.reason=='quantity_binding_conflict'
        assert other.ledger.entries()==before;return
    altered=replace(original,quantities=values)
    try:result=f.check_predicate(prepared.predicate,snapshot=altered,resources=prepared.resources)
    except (f.FInputError,f.FReplayMismatch):return
    assert result.value=='unknown'


@pytest.mark.parametrize('mode',['redelivery','conflict','independent','past-window'])
def test_structure_B6_C1_deduplication_uses_real_generation(mode):
    """Distinct generation outside fixed C1 coverage must not become redelivery."""
    # Keep both start-time cases in the independent parameter (272 collected cases).
    for start_offset_ns in ((0,17) if mode=='independent' else (17,)):
        case=assemble_c1('10',context_delay_ns=start_offset_ns)
        original=case.ledger.record(case.points['root-report' if mode=='past-window' else 'read-report'])
        if mode=='independent':
            # A new Job/Attempt is independent, but its (2,3] window is outside C1.
            request=case.decide('read2-request',ContractRef('fixture.c1.request','1'),{'action':'read'},inputs=(case.points['model'],))
            old_job=case.ledger.record(case.points['read-job']).body
            assert case.clock.mono_ns()==2*SECOND+start_offset_ns
            content=old_job.content.as_json();content['execution']['start']['time']=[2,1]
            job=case.put('read2-job',replace(old_job,decision=case.ref(request),content=Payload.json(content)))
            attempt=case.put('read2-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),contract=ContractRef('sui.s1.attempt','1')))
            value=original.body.content.as_json();value.update(window_start_ns=2*SECOND,window_end_ns=3*SECOND,completion_ns=3*SECOND)
            case.clock.advance(3*SECOND-case.clock.mono_ns())
            case.observe('new-report',original.body.contract,value,route='c1',source_id='independent-read',source_time_ns=3*SECOND,caused_by=case.ref(attempt))
        else:
            value=original.body.content.as_json()
            if mode=='conflict':value['arrival_count']['value']=1
            case.put('redelivery',replace(original.body,content=Payload.json(value),received_ns=case.clock.mono_ns()))
        case.context()
        before=case.ledger.entries()
        if mode=='independent':
            expected_error=f.FInputError if start_offset_ns else f.FIncomplete
            expected_reason='measurement_conflict' if start_offset_ns else 'c1_closure_unproved'
            with pytest.raises(expected_error) as err:read_call(case,ff.read_c1_from_facts)
            assert err.value.reason==expected_reason
        elif mode=='conflict':
            with pytest.raises(f.FInputError) as err:read_call(case,ff.read_c1_from_facts)
            assert err.value.reason=='measurement_conflict'
        else:
            got=read_call(case,ff.read_c1_from_facts)
            assert len(got.frames)==2
            assert [(v.start_ns,v.end_ns,v.count) for v in got.frames]==[(0,SECOND,1),(SECOND,2*SECOND,0)]
            assert len(set(frame.measurement_id for frame in got.frames))==len(got.frames)
        assert case.ledger.entries()==before


def hidden_model(split=False,reverse=False):
    h=idle_kernel('hidden')
    if split:
        h['outcomes']=[outcome('inside-0',diagonal((1,0)),completion=True),
                       outcome('inside-1',diagonal((0,1)),completion=True)]
        if reverse:h['outcomes'].reverse()
    q=idle_kernel('quiet');ops=(action('H','hidden'),action('Q','quiet'))
    return declaration([h,q],ops,[policy('H',h),policy('Q',q)])


@pytest.mark.parametrize('reverse',[False,True])
def test_structure_C1_C2_unobservable_split_and_label_order_preserve_math(reverse):
    results=[]
    for split in (False,True):
        doc=hidden_model(split,reverse)
        case=FactsCase(doc,name='hidden');case.candidate(('H','Q'));case.context()
        root,result=evaluation(case,u=F(3,5));results.append(result)
        assert_quantity(result.information[0].additional,FIXED['review_F09_unobservable_branches']['information_H'],
                        wrong=FIXED['review_F09_unobservable_branches']['wrong_split_by_latent_outcome']['information_H'])
        for q in result.q_star:assert_quantity(q,F(1,2))
        assert_choice(f.certify_f_choice(result,u=F(3,5)),root,'Q',F(3,5))
    # The independent observed partition has one empty observation, hence zero MI.
    assert len(results)==2


def test_structure_C3_acquisition_does_not_count_as_fresh_measurement():
    acquired=assemble_knowledge('acquired');fresh=assemble('FA05','independent')
    aroot,ae=evaluation(acquired);froot,fe=evaluation(fresh)
    assert len(aroot.E.links)==1 and len(froot.E.links)==2
    assert len(aroot.K.available)==1 and froot.K.available==()
    assert_quantity(ae.information[0].additional,0)
    assert len(set(link.measurement for link in froot.E.links))==2
    # Fresh physical evidence and acquiring an existing item are distinguishable inputs.
    assert aroot.E.key!=froot.E.key


@pytest.mark.parametrize('depth',[1,3])
def test_structure_C4_aliases_at_each_choose_preserve_local_axis(depth):
    doc,ops=finite_world('FA04')
    for level in range(1,depth):
        parent='M2' if level==1 else 'deep'+str(level-1)
        child='deep'+str(level)
        source=next(p for p in doc['policies'] if p['id']==parent)
        end=next(x for x in source['nodes'] if x['kind']=='end')
        end.update(kind='choose',operations=[child],rule=plain(fc.SOFT_CHOICE),next={child:'after-deep'})
        source['nodes'].append({'id':'after-deep','kind':'end'})
        op=action(child,'measure');doc['operations'].append(plain(op));doc['policies'].append(policy(child,bit_kernel('measure',F(3,4))))
    aliased=deepcopy(doc)
    for pol in aliased['policies']:
        for node in pol['nodes']:
            if node['kind']!='choose':continue
            first=node['operations'][0];alias=first+'-alias'
            original=next(x for x in aliased['operations'] if x['id']==first)
            if not any(x['id']==alias for x in aliased['operations']):aliased['operations'].append(dict(original,id=alias))
            node['operations'].append(alias);node['next'][alias]=node['next'][first]
    base=evaluation(assemble('FA04',document=doc))[1]
    changed=evaluation(assemble('FA04',document=aliased))[1]
    assert base.candidates==changed.candidates==('M','Q')
    for left,right in zip(base.q_star,changed.q_star,strict=True):
        l=expression_bounds(left.exact);r=expression_bounds(right.exact)
        assert l[0]<=r[1] and r[0]<=l[1] and max(l[1]-l[0],r[1]-r[0])<F(1,10**90)


def test_structure_C5_same_value_new_opportunity_is_not_redelivery():
    same=histories(assemble('FA05'));independent=histories(assemble('FA05','independent'))
    assert len(same.E.links)==1 and len(independent.E.links)==2
    assert len(same.E.links[0].records)==2
    assert len({o.transition_key for o in same.observations})==1
    assert len({o.transition_key for o in independent.observations})==2


@pytest.mark.parametrize('mode',['finite-zero','closed-zero','positive-forever'])
def test_structure_C6_zero_duration_chain_cycle_and_quiet(mode):
    doc,ops=finite_world('FA14')
    if mode=='finite-zero':
        doc,ops=finite_world('FA16','composite')
        for kernel in doc['kernels']:
            for row in kernel['outcomes']:row['elapsed_ns']=0
        case=assemble('FA16','composite',document=doc)
    else:
        if mode=='closed-zero':
            for row in doc['kernels'][0]['outcomes']:row['elapsed_ns']=0
        case=assemble('FA14',document=doc)
    if mode=='closed-zero':
        result=prepare(case).value
        assert isinstance(result,f.NoDecision) and result.reason=='certificate_incomplete'
        assert 'zero_time_cycle' in result.detail
    else:
        root,result=evaluation(case,u=F(1,6))
        assert_choice(f.certify_f_choice(result,u=F(1,6)),root,'C' if mode=='finite-zero' else 'Q',F(1,6))


def test_structure_C9_common_cost_from_preference_scales_Z_not_q():
    base=assemble('FA08');shifted=assemble('FA08')
    shifted.preference({'kind':'item','rule':{'name':'table','version':'1'},
        'args':{'feature':{'name':'started_actions','version':'1'},'probs':[[['Q'],0.5],[['M'],0.5]]}})
    shifted.context()
    a=evaluation(base)[1];b=evaluation(shifted)[1]
    for q in a.q_star+b.q_star:assert_quantity(q,F(1,2))
    for j in a.J:assert_quantity(j,0)
    for j in b.J:assert_quantity(j,FIXED['FA15']['one_perfect_measurement'])
    assert a.normalization.Z.lower<=2<=a.normalization.Z.upper
    assert b.normalization.Z.lower<=1<=b.normalization.Z.upper
    # c=+ln2 here: inverse of fixed z_shift_property's c=-ln2, factor two in both directions.
    factor=rational(FIXED['z_shift_property']['Z_shifted'])/rational(FIXED['z_shift_property']['Z_base'])
    assert factor==2
    assert b.normalization.Z.lower*factor<=a.normalization.Z.upper
    assert a.normalization.Z.lower<=b.normalization.Z.upper*factor


def test_independent_oracle_rejects_midpoint_that_does_not_enclose_ln2():
    lo,hi=reference_interval(FIXED['FA15']['one_perfect_measurement']);mid=(lo+hi)/2
    wrong=f.FQuantity(status='finite',exact=None,bounds=RationalInterval(mid,mid),proof=None,reason=None)
    with pytest.raises(AssertionError):assert_quantity(wrong,FIXED['FA15']['one_perfect_measurement'])



def test_contract_FA02_finite_update_uses_issued_model_handle():
    case=assemble('FA02');got=histories(case)
    assert isinstance(got.model,f.FFiniteUpdateModel)
    assert got.model.source==case.points['model'] and got.model.model_ref==digest(case.document)
    assert got.model.authority_key.startswith('sha256:')
    belief=f.initial_finite_belief(got.model)
    assert belief.joint==(F(1,2),F(1,2)) and belief.evidence_mass==1 and belief.applied==()
    for observation in got.observations:belief=f.apply_f_observation(got.model,belief,observation=observation)
    assert belief.joint==(F(4,5),F(1,5)) and belief.evidence_mass==F(5,16)
    assert belief.model_ref==got.model.model_ref and belief.applied



@pytest.mark.parametrize('split,reverse',[(False,False),(True,False),(True,True)])
def test_assembly_structure_C1_C2_hidden_kernel_axes(split,reverse):
    doc=hidden_model(split,reverse);case=FactsCase(doc,name='hidden');case.candidate(('H','Q'));case.context()
    assert_raw_assembly(case)
    kernel=doc['kernels'][0]
    for column in range(2):
        assert sum(F(*o['matrix'][row][column]) for o in kernel['outcomes'] for row in range(2))==1
    assert all(o['evidence'] is None for o in kernel['outcomes'])
    assert set(doc['policies'][0]['nodes'][0]['next'])=={o['id'] for o in kernel['outcomes']}


@pytest.mark.parametrize('fault',['root-proof','child-proof','kernel'])
def test_assembly_structure_B1_invalidity_is_only_in_primary_declaration(fault):
    doc,_=finite_world('FA04');bad=deepcopy(doc)
    if fault=='kernel':bad['policies'][2]['nodes'][0]['kernel']='absent-kernel'
    else:bad['operations'][0 if fault=='root-proof' else 2]['proof']['name']='absent-proof'
    case=assemble('FA04',document=bad);assert_raw_assembly(case)
    assert case.ledger.record(case.points['model']).body.content.as_json()['document']==bad
    assert case.candidate_value.model==case.points['model']


# v0.14 supplemental contracts. Factory calls remain separate from raw assembly.
def assert_no_decision(value,outcome,reason):
    assert isinstance(value,f.NoDecision)
    assert (value.outcome,value.reason)==(outcome,reason)
    assert value.attempt_id is None and value.root_key is None
    assert value.progress is None and value.resume is None


def assert_math_replay(saved,registry):
    data=ff.f_math_json(saved)
    verified=ff.verify_f_math_result(data,reader=saved.reader,registry=registry,budget=BUDGET)
    restored=ff.restore_f_math_result(data,reader=saved.reader,registry=registry,budget=BUDGET)
    assert verified.kind=='math' and verified.artifact_digest==digest({'domain':'sui.f.math_artifact/2','artifact':json.loads(data)})  # 今の約束 E-05
    assert plain(restored.value)==plain(saved.value)
    assert ff.f_math_json(restored)==data


class FaultReader(Reader):
    """Only a public reader port is changed; never alter Ledger internals."""
    def __init__(self,ledger,point,mode):super().__init__(ledger);self.point=point;self.mode=mode
    def entry(self,cid):
        if cid==self.point and self.mode=='missing-entry':raise KeyError(cid)
        return super().entry(cid)
    def entries(self):
        values=super().entries()
        return tuple(e for e in values if e.cid!=self.point) if self.mode=='missing-entry' else values
    def record(self,cid):
        if cid==self.point and self.mode in ('missing-entry','missing-body'):raise KeyError(cid)
        value=super().record(cid)
        if cid==self.point and self.mode=='changed-record':
            return replace(value,body=replace(value.body,content=Payload.json({'substituted':True})))
        return value
    def sealed_content(self,cid):
        if cid==self.point and self.mode in ('missing-entry','missing-body','missing-seal'):raise KeyError(cid)
        salt,payload=super().sealed_content(cid)
        if cid==self.point:
            if self.mode=='changed-salt':salt=salt+b'changed'
            if self.mode=='changed-payload':payload=Payload.json({'substituted':True})
        return salt,payload


@pytest.mark.parametrize('kind',['finite','limit','quantity','legacy','C1'])
def test_assembly_v014_reader_supplies_original_seal_material(kind):
    if kind=='finite':case=assemble('FA08')
    elif kind=='limit':case=assemble_limit()
    elif kind=='quantity':case,_,_=quantity_case()
    elif kind=='legacy':case,_=assemble_legacy_bridge()
    else:case=assemble_c1()
    for entry in case.reader.entries():
        salt,payload=case.reader.sealed_content(entry.cid)
        assert isinstance(salt,bytes) and salt
        assert payload==case.reader.record(entry.cid).body.content
    case.ledger.verify()


@pytest.mark.parametrize('mode',['missing-seal','changed-salt','changed-payload','changed-record'])
@pytest.mark.parametrize('entry',['prepare','histories','preflight','limit','predicate','C1','legacy'])
def test_v014_seal_material_is_required_and_authenticated(mode,entry):
    if entry=='limit':case=assemble_limit();point=case.points['limit']
    elif entry=='predicate':case,pred,quantities=quantity_case();point=quantities[0]
    elif entry=='C1':case=assemble_c1();point=case.points['root-report']
    elif entry=='legacy':case,_=assemble_legacy_bridge();point=case.points['model']
    else:case=assemble('FA08');point=case.points['model']
    case.reader=FaultReader(case.ledger,point,mode)
    registry=f.builtin_f_registry()
    expected=f.FReplayUnavailable if mode=='missing-seal' else f.FReplayMismatch
    with pytest.raises(expected) as error:
        if entry=='prepare':prepare(case)
        elif entry=='histories':histories(case)
        elif entry=='predicate':prepared_quantities(case,pred,quantities)
        elif entry=='C1':read_call(case,ff.read_c1_from_facts)
        elif entry=='legacy':prepare_bridge(case)
        elif entry=='limit':ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=point,registry=registry,budget=BUDGET)
        else:
            request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=point,required_records=(),required_capabilities=())
            ff.check_f_preflight_from_facts(case.reader,request,registry=registry,budget=BUDGET)
    assert error.value.reason==('missing_input' if mode=='missing-seal' else 'result_mismatch')


@pytest.mark.parametrize('missing',['fixed-parent','requested-entry','requested-body'])
def test_v014_preflight_missing_parent_is_not_missing_requested_record(missing):
    case=assemble('FA08');registry=f.builtin_f_registry()
    fixed=case.fixed_parents
    # A syntactically valid Point with a genuine Record, hidden only at the reader port.
    point=fixed[0] if missing=='fixed-parent' else case.points['model']
    reader=FaultReader(case.ledger,point,'missing-body' if missing=='requested-body' else 'missing-entry')
    request=f.FPreflightFacts(fixed_parents=fixed,model=None,required_records=(point,),required_capabilities=())
    if missing=='fixed-parent':
        with pytest.raises(f.FReplayUnavailable) as error:
            ff.check_f_preflight_from_facts(reader,request,registry=registry,budget=BUDGET)
        assert error.value.reason=='missing_input'
    else:
        saved=ff.check_f_preflight_from_facts(reader,request,registry=registry,budget=BUDGET)
        assert_no_decision(saved.value,'incomplete','prerequisite_unavailable')
        audit=plain(saved.value.proof.args)
        assert audit['model'] is None and audit['records']==[{'point':point,
            'entry_present':missing=='requested-body','body_present':False,'record_digest':None}]
        assert len(audit['failures'])==1 and audit['failures'][0]['reason']=='prerequisite_unavailable'
        assert_math_replay(saved,registry)


def test_v014_preflight_positive_control_has_no_failure_and_no_root():
    case=assemble('FA08');registry=f.builtin_f_registry()
    request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=case.points['model'],
        required_records=(case.points['context'],),required_capabilities=(
            f.RequiredCapability(kind='kernel',ref=ContractRef('finite_kernel','1'),implementation_required=True),))
    saved=ff.check_f_preflight_from_facts(case.reader,request,registry=registry,budget=BUDGET)
    assert isinstance(saved.value,f.PreflightReady) and saved.value.input_key.startswith('sha256:')
    assert_math_replay(saved,registry)


@pytest.mark.parametrize('api',[ff.diagnose_f_limit_from_facts,ff.certify_f_limit_from_facts])
def test_v014_limit_false_certificate_is_not_an_incomplete_result(api):
    case=assemble_limit(proof='tampered')
    with pytest.raises(f.FInputError) as error:
        api(case.reader,declaration_ref=case.points['limit'],registry=f.builtin_f_registry(),budget=BUDGET)
    assert error.value.reason=='proof_mismatch'


def test_v014_limit_uses_supplied_registry_instead_of_builtin_fallback():
    case=assemble_limit();current=f.builtin_f_registry()
    checker=ContractRef('iid_bits_limit','1')
    removed=tuple(x for x in current.implementations if x.ref==checker)
    assert removed
    registry=f.make_f_registry(declarations=current.declarations,
        implementations=tuple(x for x in current.implementations if x.ref!=checker))
    saved=ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=BUDGET)
    assert_no_decision(saved.value,'incomplete','certificate_incomplete')
    assert_math_replay(saved,registry)


@pytest.mark.parametrize('mode',['missing','extra','duplicate','nonquantity-Point','internal-key-as-Point','hidden-child'])
def test_v014_quantity_Point_collection_cannot_be_replaced_by_caller_list(mode):
    case,pred,points=quantity_case()
    if mode=='missing':points=points[:1]
    elif mode=='extra':
        extra=case.predict('extra-quantity',fc.QUANTITY_DECLARATION,
            f.FQuantityConstantDeclaration(kind='rational_constant',value=F(3),unit='dimensionless',provenance=tuple(case.raw)))
        points=points+(extra,);case.context()
    elif mode=='duplicate':points=points+(points[0],)
    else:
        value=case.ledger.record(pred).body.content.as_json()
        if mode=='nonquantity-Point':value['args']['left']['key']=case.points['model']
        elif mode=='internal-key-as-Point':
            issued=prepared_quantities(case,pred,points)
            value['args']['left']['key']=issued.quantity_bindings[0].quantity.key
        else:
            value={'name':'and','version':'1','args':{'terms':[plain(predicate(False)),value]}}
            points=points[:1]
        pred=case.predict('bad-predicate',fc.PREDICATE,value);case.context()
    with pytest.raises(f.FInputError):prepared_quantities(case,pred,points)


def test_v014_quantity_unit_conflict_is_rejected_before_cached_check():
    case,pred,points=quantity_case(unit='nat')
    with pytest.raises(f.FInputError) as error:prepared_quantities(case,pred,points)
    assert error.value.reason=='quantity_binding_conflict'


@pytest.mark.parametrize('mode',['Point-as-internal-key','foreign-resources','foreign-quantity'])
def test_v014_quantity_issued_binding_cannot_be_transferred(mode):
    case,pred,points=quantity_case();issued=prepared_quantities(case,pred,points)
    expression=issued.predicate;snapshot=issued.snapshot;resources=issued.resources
    if mode=='Point-as-internal-key':
        value=plain(expression);value['args']['left']['key']=points[0]
        expression=f.PredicateRef(**value)
    else:
        other,other_pred,other_points=quantity_case()
        # A genuinely different raw history, even with equal numerical constants.
        add_observations(other,(2,))
        # The foreign proof must be issued from valid facts: the new measurement
        # is at 2s, after the old judgment clock. Only proof transfer is invalid.
        acquired_clock=other.reading('foreign-acquisition-clock')
        acquisition=other.acquire(other.raw,clock=acquired_clock);other.context()
        assert other.ledger.record(acquisition).body.content.as_json()['clock']==acquired_clock
        assert other.ledger.record(acquired_clock).body.content.as_json()['reading']['time_ns']==2*SECOND
        assert other.ledger.record(other.raw[-1]).body.received_ns==2*SECOND
        foreign=prepared_quantities(other,other_pred,other_points)
        assert foreign.snapshot.E!=issued.snapshot.E
        if mode=='foreign-resources':resources=foreign.resources
        else:
            values=dict(snapshot.quantities)
            old=issued.quantity_bindings[0].quantity;new=foreign.quantity_bindings[0].quantity
            values[old]=foreign.snapshot.quantities[new];snapshot=replace(snapshot,quantities=values)
    try:result=f.check_predicate(expression,snapshot=snapshot,resources=resources)
    except (f.FInputError,f.FReplayMismatch):return
    assert result.value=='unknown' and result.missing


@pytest.mark.parametrize('omission',['Plan','Decided','JobOpened','AttemptStarted'])
def test_v014_finite_update_inputs_must_include_independent_dependency_closure(omission):
    case=assemble('FA06');case.acquire(case.raw)
    if omission=='Plan':point=case.plans[0]
    else:
        cls={'Decided':Decided,'JobOpened':JobOpened,'AttemptStarted':AttemptStarted}[omission]
        point=next(p for k,p in case.points.items() if k.startswith('measure-') and isinstance(case.ledger.record(p).body,cls))
    add_computation(case,omit_input=point);case.context()
    body=case.ledger.record(case.computation['request']).body.content.as_json()
    assert point not in body['inputs'] and case.reader.record(point)
    with pytest.raises(f.FInputError) as error:histories(case)
    assert error.value.reason=='unresolved_reference' and error.value.field=='/inputs'


def test_v014_C1_management_records_do_not_become_counts_or_extend_windows():
    case=assemble_c1();before=read_call(case,ff.read_c1_from_facts)
    # Same actual observation and judgment readings; extra management FACTs only.
    for i in range(3):case.context(observed_ns=2*SECOND,judgment_ns=2*SECOND)
    after=read_call(case,ff.read_c1_from_facts)
    assert after.frames==before.frames and after.pending==before.pending
    new_management={case.ref(case.points[k]) for k in ('context','observed_clock','judgment_clock')}
    assert new_management<=set(after.untouched_records)
    assert [(v.start_ns,v.end_ns,v.count) for v in after.frames]==[(0,SECOND,1),(SECOND,2*SECOND,0)]
    assert not after.pending


def forbid_legacy_effects(monkeypatch):
    from sui import clock,ids
    from sui.ledger import Ledger
    import time
    def forbidden(*args,**kwargs):raise AssertionError('facts bridge wrote or acquired an ID/clock')
    monkeypatch.setattr(Ledger,'append',forbidden)
    for module,names in ((clock,('now','mono_ns')),(ids,('new',))):
        for name,cls in vars(module).items():
            if name.startswith('_') or not inspect.isclass(cls):continue
            for method in names:
                if callable(getattr(cls,method,None)):monkeypatch.setattr(cls,method,forbidden)
    for name in ('time','time_ns','monotonic','monotonic_ns','perf_counter','perf_counter_ns'):
        monkeypatch.setattr(time,name,forbidden)


@pytest.mark.parametrize('phase',['prepare','evaluate'])
def test_v014_legacy_bridge_is_pure_even_for_temporary_ledgers(monkeypatch,phase):
    case,_=assemble_legacy_bridge()
    if phase=='evaluate':
        prepared=prepare_bridge(case);assert isinstance(prepared.value,f.FLegacyBridgeProblem)
        draw=add_draw(case,prepared.value.problem_key,u=F(1,2))
    before=case.ledger.entries()
    with monkeypatch.context() as patch:
        forbid_legacy_effects(patch)
        result=prepare_bridge(case) if phase=='prepare' else ff.evaluate_legacy_bridge_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(result.value,f.FLegacyBridgeProblem if phase=='prepare' else f.LegacyComparison)
    assert case.ledger.entries()==before


def test_v014_legacy_nonbinary_draw_cannot_be_rounded_to_claim_same_u():
    case,_=assemble_legacy_bridge();prepared=prepare_bridge(case)
    assert isinstance(prepared.value,f.FLegacyBridgeProblem)
    draw=add_draw(case,prepared.value.problem_key,u=F(1,3))
    result=ff.evaluate_legacy_bridge_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert_no_decision(result.value,'incomplete','algorithm_unavailable')


@pytest.mark.parametrize('fault',['purpose','context','order','range'])
def test_v014_FA19_fixture_generator_law_rejects_bad_original_draws(fault):
    case,_=generated_candidate_case(F(1,2))
    # Rebuild the primary records, never a CandidateInput/semantic axis.
    generator=ContractRef('fixture.f.bit_order','1')
    request=f.FCandidateRequest(domain='sui.f.candidate_request/1',model=case.points['model'],generator=generator,args={},basis=(case.points['model'],))
    point=add_draw(case,'wrong-context' if fault=='context' else digest(request),
        purpose='selection' if fault=='purpose' else 'candidate_generation',u=F(1) if fault=='range' else F(1,2))
    case.candidate(('Q','M') if fault=='order' else ('M','Q'),generator=generator,draws=(point,));case.context()
    _,registry=generated_candidate_case(F(1,2))
    with pytest.raises(f.FInputError):prepare(case,registry=registry)


@pytest.mark.parametrize('both',[False,True])
def test_v014_limit_certificate_uses_same_original_Point_as_diagnosis(both):
    case=assemble_limit(both=both);registry=f.builtin_f_registry()
    saved=ff.certify_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=BUDGET)
    cert=saved.value;assert isinstance(cert,f.LimitCertificate)
    assert cert.checker==ContractRef('iid_bits_limit','1')
    assert cert.conclusion==('undefined_infinite_difference' if both else 'information_divergent')
    assert cert.information.bound=='diverges' and cert.cost.bound==('diverges' if both else 'zero')
    assert cert.information.prefix.name==cert.cost.prefix.name=='linear'
    low,high=reference_interval(FIXED['FA15']['one_perfect_measurement'])
    slope_low,slope_high=expression_bounds(cert.information.prefix.args.slope)
    assert slope_low<=high and low<=slope_high and slope_high-slope_low<F(1,10**90)
    assert expression_bounds(cert.information.prefix.args.intercept)==(F(0),F(0))
    assert expression_bounds(cert.cost.prefix.args.intercept)==(F(0),F(0))
    if both:assert cert.cost.prefix.args.slope==cert.information.prefix.args.slope
    else:assert expression_bounds(cert.cost.prefix.args.slope)==(F(0),F(0))
    assert json.loads(ff.f_math_json(saved))['calls']==[{'op':'limit_certificate','args':{'budget':plain(BUDGET)}}]
    assert_math_replay(saved,registry)


def test_v014_preflight_collects_all_failures_before_issuing_audit():
    case=assemble('FA08');registry=f.builtin_f_registry()
    missing=case.points['candidates'];reader=FaultReader(case.ledger,missing,'missing-body')
    unknown=f.RequiredCapability(kind='kernel',ref=ContractRef('fixture.absent','1'),implementation_required=True)
    absent_impl=f.RequiredCapability(kind='kernel',ref=ContractRef('finite_kernel','1'),implementation_required=True)
    registry=f.make_f_registry(declarations=registry.declarations,
        implementations=tuple(x for x in registry.implementations if x.kind!='kernel'))
    request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=case.points['model'],
        required_records=(missing,),required_capabilities=(absent_impl,unknown))
    saved=ff.check_f_preflight_from_facts(reader,request,registry=registry,budget=BUDGET)
    assert_no_decision(saved.value,'incomplete','prerequisite_unavailable')
    audit=plain(saved.value.proof.args)
    assert audit['model']['body_present']
    assert audit['records']==[{'point':missing,'entry_present':True,'body_present':False,'record_digest':None}]
    assert audit['capabilities']==[
        {'kind':'kernel','ref':plain(absent_impl.ref),'declared':True,'implemented':False},
        {'kind':'kernel','ref':plain(unknown.ref),'declared':False,'implemented':False}]
    assert [(x['outcome'],x['reason']) for x in audit['failures']]==[
        ('incomplete','prerequisite_unavailable'),('incomplete','algorithm_unavailable'),('rejected','missing_contract')]
    assert all(x['field'] for x in audit['failures'])


def test_v014_FA18_cached_check_never_returns_to_raw_reader(monkeypatch):
    case,pred,points=quantity_case();prepared=prepared_quantities(case,pred,points)
    def forbidden(*args,**kwargs):raise AssertionError('cached predicate performed preparation work')
    before=case.ledger.entries()
    with monkeypatch.context() as patch:
        patch.setattr(Reader,'record',forbidden);patch.setattr(Reader,'sealed_content',forbidden)
        patch.setattr(ff,'verify_f_math_result',forbidden);patch.setattr(ff,'prepare_f_predicate_from_facts',forbidden)
        results=[f.check_predicate(prepared.predicate,snapshot=prepared.snapshot,resources=prepared.resources) for _ in range(100)]
    assert all(x.value=='true' and not x.missing and x.work==results[0].work for x in results)
    assert case.ledger.entries()==before


def evaluation_quantity_case(u):
    case=assemble('FA08');prepared=prepare(case)
    assert isinstance(prepared.value,f.FProblem)
    draw=add_draw(case,prepared.value.problem_key,u=u)
    artifact=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(artifact.value,f.Selected)
    # Only the public serializer writes this mathematical result as a raw Prediction.
    result=case.predict('math-result',fc.MATH_ARTIFACT_V2,json.loads(ff.f_math_json(artifact)),basis=(draw,))
    left=case.predict('evaluation-quantity',fc.QUANTITY_DECLARATION,
        f.FQuantityEvaluationDeclaration(kind='evaluation',result=result,field='q_star',candidate='Q'),basis=(result,))
    right=case.predict('one',fc.QUANTITY_DECLARATION,
        f.FQuantityConstantDeclaration(kind='rational_constant',value=F(1),unit='dimensionless',provenance=(result,)),basis=(result,))
    case.acquire((result,left,right))
    expression=f.PredicateRef(name='interval_compare',version='1',args={
        'left':{'key':left},'relation':'lt','right':{'key':right},'provenance':[str(case.ref(result))]})
    pred=case.predict('predicate',fc.PREDICATE,expression,basis=(left,right));case.context()
    return case,artifact,prepared_quantities(case,pred,(left,right)),left


@pytest.mark.parametrize('change',['proof','whole-quantity'])
def test_v014_FA18_quantity_guarantee_cannot_move_between_distinct_roots(change):
    case,artifact,issued,left=evaluation_quantity_case(F(1,4))
    other,foreign_artifact,foreign,foreign_left=evaluation_quantity_case(F(3,4))
    assert artifact.value.root.root_key!=foreign_artifact.value.root.root_key
    own_key=next(b.quantity for b in issued.quantity_bindings if b.point==left)
    foreign_key=next(b.quantity for b in foreign.quantity_bindings if b.point==foreign_left)
    original=issued.snapshot.quantities[own_key];replacement=foreign.snapshot.quantities[foreign_key]
    assert_quantity(original,F(1,2));assert_quantity(replacement,F(1,2))
    assert f.check_predicate(issued.predicate,snapshot=issued.snapshot,resources=issued.resources).value=='true'
    values=dict(issued.snapshot.quantities)
    values[own_key]=replace(original,proof=replacement.proof) if change=='proof' else replacement
    altered=replace(issued.snapshot,quantities=values)
    try:result=f.check_predicate(issued.predicate,snapshot=altered,resources=issued.resources)
    except (f.FInputError,f.FReplayMismatch):return
    assert result.value=='unknown' and result.missing


@pytest.mark.parametrize('mode',['handmade','changed-source','foreign-observation'])
def test_v014_finite_update_descriptor_is_not_issuance_authority(mode):
    case=assemble('FA02');got=histories(case)
    if mode=='foreign-observation':
        other=assemble('FA03');foreign=histories(other)
        model=got.model;observation=foreign.observations[-1]
        belief=f.initial_finite_belief(model)
        with pytest.raises(f.FInputError):f.apply_f_observation(model,belief,observation=observation)
    else:
        descriptor={x.name:getattr(got.model,x.name) for x in fields(got.model)}
        if mode=='changed-source':descriptor['source']=case.points['context']
        with pytest.raises((f.FInputError,TypeError)):
            model=f.FFiniteUpdateModel(**descriptor)
            f.initial_finite_belief(model)

# Mutation regressions through facts-only preparation (request 12).
@pytest.mark.parametrize('entry',[ff.bind_f_draw,ff.evaluate_f_from_draw],ids=['bind','evaluate'])
@pytest.mark.parametrize('fault',['foreign-problem','unknown-problem','missing-ancestors','candidate-purpose','algorithm-purpose'])
def test_facts_mutation_selection_draw_binds_problem_and_ancestors(entry,fault):
    """§3-10-16-8: purpose, context and actual ancestry are independent checks."""
    case=assemble('FA08');prepared=prepare(case)
    assert isinstance(prepared.value,f.FProblem)
    fixed=case.fixed_parents;model=case.points['model']
    case.context();other=prepare(case)
    assert isinstance(other.value,f.FProblem)
    assert model==case.points['model'] and prepared.value.problem_key!=other.value.problem_key
    key=prepared.value.problem_key
    good=add_draw(case,key,u=F(1,2))
    bad_key=other.value.problem_key if fault=='foreign-problem' else ('sha256:'+'0'*64 if fault=='unknown-problem' else key)
    purpose={'candidate-purpose':'candidate_generation','algorithm-purpose':'algorithm'}.get(fault,'selection')
    good_body=case.ledger.record(good).body
    raw=good_body.content.as_json();raw['request']['context_key']=bad_key;raw['request']['purpose']=purpose
    bad=case.put('bad-selection-draw',replace(good_body,content=Payload.json(raw)),parents=() if fault=='missing-ancestors' else None)
    expected=good_body.content.as_json()
    if fault in ('foreign-problem','unknown-problem'):expected['request']['context_key']=bad_key
    elif fault.endswith('purpose'):expected['request']['purpose']=purpose
    assert raw==expected  # law/args/u/generator/stream/ordinal never change.
    if fault=='missing-ancestors':
        assert raw==good_body.content.as_json()
        assert not set(fixed).issubset(set(case.ledger.ancestors((bad,))))
    else:assert set(fixed).issubset(set(case.ledger.ancestors((bad,))))
    before=case.ledger.entries()
    valid=entry(prepared,good,reader=case.reader,budget=BUDGET).value
    if entry is ff.bind_f_draw:
        assert isinstance(valid,f.FRoot) and valid.problem_key==key
        assert plain(valid.selection_draw.value)=={'u':[1,2]}
    else:
        assert isinstance(valid,f.Selected)
        assert valid.root.problem_key==key
        assert_choice(valid,valid.root,'M',F(1,2))
    with pytest.raises(f.FInputError) as err:entry(prepared,bad,reader=case.reader,budget=BUDGET)
    assert err.value.reason=='invalid_draw'
    assert case.ledger.entries()==before


def test_facts_mutation_01_compute_preserves_E_and_has_zero_information():
    """§3-3 / FA06: advancing K cannot create a measurement or information."""
    case=assemble_knowledge('acquired');before_history=histories(case)
    prepared,draw,root=bound(case)
    before=case.ledger.entries()
    computation=f.ComputationSpec(method=ContractRef('sui.f.computation_information','1'),
        input_measurements=tuple(case.measurements),input_records=tuple(case.ref(p) for p in case.raw),
        algorithm_draws=(),output_contract=fc.BELIEF)
    info=f.computation_information(root.value,computation=computation,budget=BUDGET)
    assert_quantity(info.additional,0)
    selected=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET).value
    assert_choice(selected,root.value,'Compute',F(1,2))
    assert_quantity(selected.evaluation.information[0].additional,0)
    assert selected.root.E==before_history.E and case.ledger.entries()==before
    add_computation(case,stage='adopted');case.context()
    after_history=histories(case)
    assert after_history.E==before_history.E
    assert tuple(x.measurement for x in after_history.E.links)==tuple(case.measurements)
    assert before_history.K.incorporated==() and after_history.K.incorporated==tuple(case.measurements)


@pytest.mark.parametrize('nonzero',[False,True])
def test_facts_mutation_02_pending_P_is_not_a_new_started_action(nonzero):
    """§3-10-12 FA07 bridge (1956-1970), §3-10-16-補6: A excludes pending P."""
    case,model=assemble_legacy_bridge(pending=True,nonzero=nonzero)
    prepared=prepare_bridge(case)
    assert isinstance(prepared.value,f.FLegacyBridgeProblem)
    draw=add_draw(case,prepared.value.problem_key,u=F(1,2));before=case.ledger.entries()
    compared=ff.evaluate_legacy_bridge_from_draw(prepared,draw,reader=case.reader,budget=BUDGET).value
    assert isinstance(compared,f.LegacyComparison)
    expected_J=({'2':1,'3':-1},{'2':1}) if nonzero else ({'2':-1},{'2':-1})
    for got,terms in zip(compared.new_J,expected_J):
        assert_quantity(got,{'coeffs':{prime:[coefficient,1] for prime,coefficient in terms.items()}})
    for got,want in zip(compared.new_probabilities,(F(3,4),F(1,4)) if nonzero else (F(1,2),F(1,2))):assert_quantity(got,want)
    assert compared.old_choice==compared.new_choice==('M' if nonzero else 'Q')
    assert case.ledger.entries()==before


@pytest.mark.parametrize('both',[False,True])
def test_facts_mutation_03_finite_budget_failure_is_not_divergence(both):
    """FA15-17 / §3-10-16-補4: a finite failed computation proves no limit."""
    case=assemble_limit(both=both);registry=f.builtin_f_registry()
    tiny=replace(BUDGET,max_terms=1,max_cells=1,max_refinements=1)
    before=case.ledger.entries()
    result=ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=tiny).value
    assert_no_decision(result,'incomplete','budget_exhausted')
    with pytest.raises(f.FIncomplete) as err:
        ff.certify_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=tiny)
    assert err.value.reason=='budget_exhausted'
    positive=ff.certify_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=BUDGET).value
    assert positive.conclusion==('undefined_infinite_difference' if both else 'information_divergent')
    assert positive.information.bound=='diverges'
    assert case.ledger.entries()==before


@pytest.mark.parametrize('node,expected',[('end','false'),('finished-7','true')])
def test_facts_mutation_04_policy_end_uses_node_kind(node,expected):
    """§3-10-12-3: node IDs are not node kinds; same facts-issued model is used."""
    doc,_=finite_world('FA08');p=next(p for p in doc['policies'] if p['id']=='Q')
    p['entry']='end';p['nodes']=[execute('end','quiet',['done'],'finished-7'),{'id':'finished-7','kind':'end'}]
    case=assemble('FA08',document=doc)
    point=case.predict('policy-end',fc.PREDICATE,f.PredicateRef(name='policy_end',version='1',args={}),basis=(case.points['model'],))
    case.context();prepared=prepared_quantities(case,point,())
    # The public predicate position selects a node in the model just authenticated from facts.
    snapshot=replace(prepared.snapshot,policy_position=f.PredicatePosition(policy='Q',node=node))
    before=case.ledger.entries()
    result=f.check_predicate(prepared.predicate,snapshot=snapshot,resources=prepared.resources)
    assert result.value==expected and result.missing==() and result.work is None
    assert case.ledger.entries()==before


def test_facts_mutation_05_float_selection_keeps_exact_binary_rational():
    """§3-10-2 (274): float 0.1 means its binary rational, not decimal 1/10."""
    case=assemble('FA19');binary=F.from_float(0.1)
    assert binary!=F(1,10)
    prepared,draw,root=bound(case,u=binary);before=case.ledger.entries()
    selected=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET).value
    assert_choice(selected,root.value,'Q',binary)
    assert_choice(f.certify_f_choice(selected.evaluation,u=0.1),root.value,'Q',binary)
    with pytest.raises(f.FInputError):f.certify_f_choice(selected.evaluation,u=F(1,10))
    assert case.ledger.entries()==before


@pytest.mark.parametrize('reverse',[False,True])
def test_facts_mutation_06_observation_cell_sums_all_hidden_outcomes(reverse):
    """§3-10-14-6: T_e is a sum, not the first latent branch of the cell."""
    measure=bit_kernel('measure',F(3,4))
    split=[outcome('latent-a',diagonal((F(3,4),0)),value=0),
           outcome('latent-b',diagonal((0,F(1,4))),value=0)]
    if reverse:split.reverse()
    measure['outcomes']=split+[measure['outcomes'][1]]
    quiet=idle_kernel('quiet');ops=(action('Q','quiet'),)
    doc=declaration([quiet,measure],ops,[policy('Q',quiet)])
    case=FactsCase(doc,name='coalesced');add_observations(case);case.candidate(('Q',));case.context()
    before=case.ledger.entries();got=histories(case)
    belief=f.initial_finite_belief(got.model)
    assert len(got.observations)==1
    updated=f.apply_f_observation(got.model,belief=belief,observation=got.observations[0])
    assert updated.joint==(F(3,4),F(1,4)) and updated.evidence_mass==F(1,2)
    assert case.ledger.entries()==before
    root,result=evaluation(case)
    assert_quantity(result.information[0].already_received,FIXED['FA05']['information_one'])
    assert_quantity(result.information[0].additional,0)


@pytest.mark.parametrize('revealed',[False,True])
def test_facts_mutation_07_execute_next_must_be_measurable_in_K(revealed):
    """§3-10-3 / §3-10-14-6 / F01: ExecuteNode.next also obeys K-measurability."""
    noisy=bit_kernel('noisy',F(3,4))
    for o in noisy['outcomes']:o['available']['reveal']=['m'] if revealed else []
    perfect=bit_kernel('perfect',slot='perfect');op=action('branching','noisy')
    branch=execute('first','noisy',['y0','y1']);branch['next']['y1']='perfect'
    p={'id':'branching','entry':'first','nodes':[branch,execute('perfect','perfect',['y0','y1']),{'id':'end','kind':'end'}]}
    case=FactsCase(declaration([noisy,perfect],(op,),[p]),name='F01');case.candidate(('branching',));case.context()
    before=case.ledger.entries();prepared=prepare(case)
    assert case.ledger.entries()==before
    if not revealed:assert_no_decision(prepared.value,'incomplete','certificate_incomplete')
    else:
        assert isinstance(prepared.value,f.FProblem)
        draw=add_draw(case,prepared.value.problem_key);before=case.ledger.entries()
        selected=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET).value
        assert_choice(selected,selected.root,'branching',F(1,2))
        assert case.ledger.entries()==before


@pytest.mark.parametrize('label',['y0','y1'])
def test_facts_mutation_08_10_C1_other_delivery_extends_only_provenance(label):
    """§3-10-14-8 / §3-10-16-14 B6: content identity excludes source_record."""
    from sui.rate_model import RateModel
    first=assemble_c1(label=label);second=assemble_c1(label=label,read_delivery=1)
    old=first.ledger.record(first.points['read-report']);new=second.ledger.record(second.points['read-report'])
    assert old.id!=new.id and plain(old.body)==plain(new.body)
    assert first.ledger.record(first.points['read-attempt'])==second.ledger.record(second.points['read-attempt'])
    before=(first.ledger.entries(),second.ledger.entries())
    a=read_call(first,ff.read_c1_from_facts);b=read_call(second,ff.read_c1_from_facts)
    assert len(a.frames)==len(b.frames)==2
    assert a.frames[1].source_record==old.id and b.frames[1].source_record==new.id
    assert a.frames[1].measurement_id==b.frames[1].measurement_id
    summary=f.initial_c1_summary(RateModel(declaration=canonical(first.document)),run=first.clock.run,origin_ns=0)
    for frame in a.frames:summary=f.update_c1_summary(summary,frame=frame)
    updated=f.update_c1_summary(summary,frame=b.frames[1])
    for field in ('N','T_s','A0','A1','probe_counts','measurement_ids','probe_measurements','end_ns'):
        assert getattr(updated,field)==getattr(summary,field)
    assert set(updated.source_records)==set(summary.source_records)|{new.id}
    assert new.id not in summary.source_records and old.id in updated.source_records
    assert f.c1_state_marginal(updated)==f.c1_state_marginal(summary)
    assert f.update_c1_summary(updated,frame=b.frames[1])==updated
    assert (first.ledger.entries(),second.ledger.entries())==before


@pytest.mark.parametrize('mode',['decoded-json','handmade'])
def test_facts_mutation_09_unissued_quantity_cannot_supply_comparison_bounds(mode):
    """FA18 / §3-10-14-10 / §3-10-16-補5: decoding is not issuance."""
    from sui import f_entry as codec
    case,pred,points=quantity_case();prepared=prepared_quantities(case,pred,points)
    before=case.ledger.entries()
    positive=f.check_predicate(prepared.predicate,snapshot=prepared.snapshot,resources=prepared.resources)
    assert positive.value=='true' and positive.missing==() and positive.work is None
    forged={}
    for key,value in prepared.snapshot.quantities.items():
        forged[key]=codec.f_from_json(codec.f_json(value),contract=fc.VALUE_FACTS) if mode=='decoded-json' else f.FQuantity(**{field.name:getattr(value,field.name) for field in fields(value)})
        assert plain(forged[key])==plain(value) and forged[key] is not value
    altered=replace(prepared.snapshot,quantities=forged)
    result=f.check_predicate(prepared.predicate,snapshot=altered,resources=prepared.resources)
    assert result.value=='unknown' and result.missing and result.work is not None
    assert case.ledger.entries()==before


@pytest.mark.parametrize('received,pending',[(False,False),(True,False),(False,True),(True,True)],
    ids=['neither-FA21','received-only-outside-scope','pending-only-FA07','both-outside-scope'])
def test_facts_mutation_02_legacy_bridge_certification_scope(received,pending):
    """Spec:1942-1952,5261: prior received Q is outside FA21/FA07 bridge scope."""
    from sui.s1_contracts import OUTCOME
    case,model=assemble_legacy_bridge_quadrant(received=received,pending=pending)
    reports=[e for e in case.ledger.entries() if getattr(case.ledger.record(e.cid).body,'contract',None)==OUTCOME]
    assert len(reports)==int(received)
    assert ('P-job' in case.points)==pending and ('P' in model.actions)==pending
    if pending:assert case.ledger.record(case.points['P-job']).body.content.as_json()=={'action':'P'}
    if received:
        report=case.ledger.record(case.points['Q-report'])
        assert report.body.content.as_json()=={'outcome':'constant'}
        assert report.body.caused_by==case.ref(case.points['Q-attempt'])
        if pending:assert report.body.caused_by!=case.ref(case.points['P-attempt'])
    before=case.ledger.entries();prepared=prepare_bridge(case)
    assert case.ledger.entries()==before
    assert isinstance(prepared.value,f.FLegacyBridgeProblem)
    draw=add_draw(case,prepared.value.problem_key,u=F(1,2));before=case.ledger.entries()
    result=ff.evaluate_legacy_bridge_from_draw(prepared,draw,reader=case.reader,budget=BUDGET).value
    assert case.ledger.entries()==before
    if received:
        # Spec:1942-1952,5261: FA21 has no prior received history; FA07 covers pending P.
        # Received Q, with or without pending P, is outside scope: typed incompleteness.
        assert_no_decision(result,'incomplete','algorithm_unavailable')
        return
    assert isinstance(result,f.LegacyComparison),plain(result)
    assert len(result.new_J)==len(result.new_probabilities)==len(result.reconstructed_information)==2
    ln2=FIXED['FA07']['already_received']
    expected_information=(ln2,ln2 if pending else 0)
    expected_J=({'coeffs':{'2':[1,1],'3':[-1,1]}},{'coeffs':{'2':[1,1]}}) if pending else (negate(ln2),0)
    expected_q=(F(3,4),F(1,4)) if pending else (F(2,3),F(1,3))
    for info,expected in zip(result.reconstructed_information,expected_information):assert_quantity(info,expected)
    for j,expected in zip(result.new_J,expected_J):assert_quantity(j,expected)
    for q,expected in zip(result.new_probabilities,expected_q):assert_quantity(q,expected)
    assert result.old_choice==result.new_choice=='M'
    facts=plain(next(a.value for a in result.assumptions if a.contract==ContractRef('sui.f.legacy_bridge_facts','1')))
    assert facts['o0']=={'mode':'pending_marginalized' if pending else 'absent',
                         'source_attempts':[case.points['P-attempt']] if pending else [],
                         'averaged_before_choice':True}


# Review 5 regressions: spec v0.14 §3-10-16-3/4/5/9 and supplement 4.
# Primary-input recipes come from the review report; no implementation bodies.
def assert_review5_missing_contract(case,kind,name):
    registry=f.builtin_f_registry()
    saved=prepare(case,registry=registry)
    assert_no_decision(saved.value,'rejected','missing_contract')
    assert_math_replay(saved,registry)
    # Low-level semantic validation (canonicalization alone need not use a proof).
    # The legacy prepare API and the facts predicate API have exception results.
    from sui import f_entry as fe
    import gate_f_cases as legacy
    if kind=='predicate':
        control=assemble('FA08')
        point=control.predict('predicate',fc.PREDICATE,f.PredicateRef(name=name,version='1',args={}))
        control.context()
        call=lambda:ff.prepare_f_predicate_from_facts(control.reader,fixed_parents=control.fixed_parents,
            model_ref=control.points['model'],context_ref=control.points['context'],
            predicate_ref=point,quantity_refs=(),registry=registry,budget=BUDGET)
    else:
        # 2026-10-12: the derived-input entrance is gone; the declaration is a ledger fact.
        doc,actions=finite_world('FA04')
        if kind=='proof':
            doc['operations'][0]['proof']['name']=name
            control=assemble('FA04',document=doc)
        else:
            control=assemble('FA04')
            control.candidate([a.id for a in actions],generator=ContractRef(name,'1'));control.context()
        call=lambda:legacy.make_problem(control)
    with pytest.raises(f.FSpecificationMissing) as err:call()
    assert err.value.reason=='missing_contract'


def review5_selected_roundtrip(case):
    """Exercise the entire public success route, returning the inspected artifact."""
    registry=f.builtin_f_registry()
    prepared=prepare(case,registry=registry)
    assert isinstance(prepared.value,f.FProblem)
    draw=add_draw(case,prepared.value.problem_key,u=F(1,4))
    saved=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(saved.value,f.Selected)
    data=ff.f_math_json(saved)
    verified=ff.verify_f_math_result(data,reader=saved.reader,registry=registry,budget=BUDGET)
    restored=ff.restore_f_root(data,reader=saved.reader,registry=registry,budget=BUDGET)
    assert verified.kind=='math' and verified.root_key==saved.value.root.root_key
    assert verified.artifact_digest==digest({'domain':'sui.f.math_artifact/2','artifact':json.loads(data)})  # 今の約束 E-05
    assert plain(restored)==plain(saved.value.root)
    assert plain(f.evaluate_f_recursive(restored,budget=BUDGET))==plain(saved.value.evaluation)
    return saved


def assert_review5_rejected_facts(case,witness,*,reason,field):
    """Bad facts cannot mint a root, including replay of a claimed Selected.

    The negative replay envelope deliberately rebinds a legitimate Selected's
    input to the bad primary facts. It is never presented as an issued artifact.
    Require the original input error, not an unrelated digest/draw mismatch.
    """
    for call in (lambda:histories(case),lambda:prepare(case)):
        with pytest.raises(f.FInputError) as err:call()
        # 今の約束 A-21 (2026-10-11): the pointer may name the column under this prefix.
        assert err.value.reason==reason and err.value.field.startswith(field)
    wire=json.loads(ff.f_math_json(witness))
    wire['input']['value'].update(context=case.points['context'],fixed_parents=list(case.fixed_parents))
    for api in (ff.verify_f_math_result,ff.restore_f_root):
        with pytest.raises(f.FInputError) as err:
            api(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
        # 今の約束 A-21 (2026-10-11): the pointer may name the column under this prefix.
        assert err.value.reason==reason and err.value.field.startswith(field)


@pytest.mark.parametrize('event',['measurement','acquisition','adoption'])
@pytest.mark.parametrize('after_ns',[0,1],ids=['at-judgment','one-ns-after'])
def test_review5_R01_future_event_cannot_become_verified_knowledge(event,after_ns):
    # Kills accepting future measurements/acquisitions/adoptions in a past root;
    # equality remains legal. Only the judgment reading changes in the bad input.
    case=review5_timed_case(event)
    witness=review5_selected_roundtrip(case)
    root=witness.value.root
    assert tuple(x.measurement for x in root.E.links)==tuple(case.measurements)
    assert root.K.available==(tuple(case.measurements) if event!='measurement' else ())
    assert root.K.incorporated==(tuple(case.measurements) if event=='adoption' else ())
    if after_ns:
        case.context(observed_ns=root.context.now_ns-after_ns,judgment_ns=root.context.now_ns-after_ns)
        field={'measurement':'/measurement/boundary','acquisition':'/acquisition/boundary',
               'adoption':'/adoption/inputs/boundary'}[event]
        assert_review5_rejected_facts(case,witness,reason='shape',field=field)


def test_review5_R02_later_acquisition_does_not_repair_past_adoption():
    # Kills a closure-wide acquisition union used to justify an earlier adoption.
    good=review5_adoption_case();witness=review5_selected_roundtrip(good)
    assert witness.value.root.K.incorporated==tuple(good.measurements)
    bad=review5_adoption_case(late_acquisition=True)
    adoption=bad.points['adopted']
    acquisitions=[p for p in bad.ledger.entries() if bad.ledger.record(p.cid).body.contract==fc.CONTENT_ACQUIRED]
    late=acquisitions[-1].cid
    assert late not in bad.reader.ancestors((adoption,))
    assert bad.ledger.record(late).at.mono_ns>bad.ledger.record(adoption).at.mono_ns
    assert_review5_rejected_facts(bad,witness,reason='proof_mismatch',field='/adoption')


@pytest.mark.parametrize('inputs',['empty','missing-completion','wrong-point'])
def test_review5_R03_adoption_body_and_outer_inputs_must_agree(inputs):
    # Kills checking only the body Points while ignoring Decided.inputs (P7).
    good=review5_adoption_case();witness=review5_selected_roundtrip(good)
    bad=review5_adoption_case(inputs=inputs)
    assert good.ledger.record(good.points['adopted']).body.content.as_json()==bad.ledger.record(bad.points['adopted']).body.content.as_json()
    assert_review5_rejected_facts(bad,witness,reason='proof_mismatch',field='/adoption/inputs')


@pytest.mark.parametrize('world',['FA06','FA05'])
def test_review5_R04_readoption_preserves_single_application(world):
    # Kills refusing a same-result adoption, or applying its measurement twice.
    case=FactsCase(finite_world(world)[0],name='readoption-'+world)
    add_observations(case);case.reading('judgment_clock');case.acquire(case.raw)
    add_computation(case);case.candidate(('Compute',) if world=='FA06' else ('Q','M'));case.context()
    first=review5_selected_roundtrip(case)
    previous=case.computation['adopted']
    case.decide('readopted',fc.KNOWLEDGE_ADOPTED,
        f.KnowledgeAdopted(origin=case.points['origin'],previous=previous,completion=case.computation['completed']),
        inputs=(case.points['origin'],previous,case.computation['completed']))
    case.context();again=review5_selected_roundtrip(case)
    for saved in (first,again):
        root=saved.value.root
        assert root.K.incorporated==root.K.available==tuple(case.measurements)
        assert root.K.belief==case.ref(case.computation['result'])
        assert root.K.normalization_proofs==(case.ref(case.computation['proof']),)
        assert root.K.pending==()
        assert len(root.E.links)==1 and root.E.links[0].measurement==case.measurements[0]
    assert first.value.root.K==again.value.root.K
    for field in ('expected_cost','information','J','q_star'):
        assert plain(getattr(first.value.evaluation,field))==plain(getattr(again.value.evaluation,field))
    if world=='FA05':
        # Posterior 3/4, next noisy bit 3/4: H(5/8)-H(3/4), not the
        # double-applied posterior 9/10's H(7/10)-H(3/4).
        expected={'coeffs':{'2':[1,1],'3':[3,8],'5':[-5,8]}}
        wrong={'coeffs':{'2':[-1,1],'3':[9,20],'5':[1,1],'7':[-7,10]}}
        idx=again.value.evaluation.candidates.index('M')
        assert_quantity(again.value.evaluation.information[idx].additional,expected,wrong=wrong)


@pytest.mark.parametrize('old_stage',['adopted','computed-unacquired'])
def test_review5_R05_unselected_origin_cannot_contaminate_selected_series(old_stage):
    # Kills scanning every origin's requests/completions/adoptions/pending as K.
    case=assemble_knowledge(old_stage)
    old_origin=case.points['origin'];old_request=case.computation['request']
    case.observe('origin',fc.KNOWLEDGE_ORIGIN,f.KnowledgeOrigin(model=case.points['model']))
    case.context();fresh=review5_selected_roundtrip(case)
    k=fresh.value.root.K
    assert k.available==k.incorporated==k.normalization_proofs==k.query_proofs==k.pending==()
    assert k.belief is None
    assert len(fresh.value.root.E.links)==1
    assert_quantity(fresh.value.evaluation.J[0],negate(FIXED['FA05']['information_one']))
    # Positive control: selecting the old series again still exposes that series.
    case.points['origin']=old_origin;case.context();old=review5_selected_roundtrip(case)
    assert old.value.root.K.available==tuple(case.measurements)
    if old_stage=='adopted':
        assert old.value.root.K.incorporated==tuple(case.measurements)
        assert old.value.root.K.belief==case.ref(case.computation['result'])
    else:
        assert old.value.root.K.incorporated==() and old.value.root.K.pending
        assert all(case.ref(old_request) in dep.basis for dep in old.value.root.K.pending)


@pytest.mark.parametrize('pending',[False,True],ids=['declared-only','in-progress'])
def test_review5_GF_M13_pending_P_is_not_a_new_started_action(pending):
    # Kills adding P to the cost table's started_actions merely because E exists.
    case=review5_pending_cost_case(pending=pending)
    saved=review5_selected_roundtrip(case);result=saved.value.evaluation
    assert {op['id'] for op in case.document['operations']}=={'M','Q','P'}
    assert len(saved.value.root.E.links)==1
    if pending:
        attempt=case.ledger.record(case.points['P-attempt'])
        assert attempt.body.job==case.ref(case.points['P-job'])
        assert case.ledger.record(case.points['P-job']).body.content.as_json()=={'action':'P'}
    oracle=FIXED['FA07_first_action_cost']
    assert set(result.candidates)=={'M','Q'}
    for i,name in enumerate(result.candidates):
        assert_quantity(result.expected_cost[i],{'coeffs':{'2':[2,1],'3':[-1,1]}} if name=='M' else {'coeffs':{'2':[2,1]}})
        assert_quantity(result.J[i],oracle['J'][name])
        assert_quantity(result.q_star[i],F(3,4) if name=='M' else F(1,4))


@pytest.mark.parametrize('both',[False,True],ids=['blank-cost','both-diverge'])
def test_review5_GF_M25_independent_checker_does_not_turn_finite_failure_into_divergence(both):
    # Kills GF-M25 on the new entry: an independently registered checker proves
    # the math, but unsupported downstream certification is still incomplete.
    # Merely removing the built-in checker stops earlier and cannot test this path.
    case=assemble_limit(both=both);doc=limit_document(both=both)
    ref=ContractRef('fixture.independent_limit','1');doc['proof']['name']=ref.name
    case.predict('limit',fc.LIMIT_DECLARATION,doc)
    builtin=f.builtin_f_registry();checked=[]
    declaration=replace(next(d for d in builtin.declarations if d.ref.name=='iid_bits_limit'),
        ref=ref,output_contract=ContractRef('sui.f.schema.proof_check','1'))
    def independent_checker(*,args,input,context):
        assert plain(input)==doc and plain(args)==doc['proof']['args']
        problem=f.limit_problem_from_json(canonical(input))
        cert=f.certify_f_limit(replace(problem,proof=replace(problem.proof,name='iid_bits_limit')),budget=context.budget)
        assert cert.information.bound=='diverges'
        assert cert.cost.bound==('diverges' if both else 'zero')
        checked.append(cert.conclusion)
        return plain(f.ProofCheck(status='proved',reason=None,evidence=(),missing=()))
    registry=f.make_f_registry(declarations=builtin.declarations+(declaration,),
        implementations=builtin.implementations+(f.CapabilityImplementation(kind='proof',ref=ref,implementation=independent_checker,identity='fixture.independent_checker/1'),))
    saved=ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=registry,budget=BUDGET)
    assert checked==['undefined_infinite_difference' if both else 'information_divergent']
    assert_no_decision(saved.value,'incomplete','certificate_incomplete')
    assert_math_replay(saved,registry)
    # Control: changing only the declared proof name back reaches actual divergence.
    doc['proof']['name']='iid_bits_limit';case.predict('limit',fc.LIMIT_DECLARATION,doc)
    positive=ff.diagnose_f_limit_from_facts(case.reader,declaration_ref=case.points['limit'],registry=builtin,budget=BUDGET)
    assert_no_decision(positive.value,'rejected','undefined_infinite_difference' if both else 'information_divergent')
    assert_math_replay(positive,builtin)


def assert_review5_primary_rejected(case,witness,*,reason_only=False,error_type=f.FInputError):
    """Spec §3-10-16-9: contradictory primary facts are input errors, not claims.

    Diagnostics need not have an invented table-specific reason; the low/high
    and saved-result entrances must identify the same contradictory input.
    """
    diagnostics=[]
    wire=json.loads(ff.f_math_json(witness))
    wire['input']['value'].update(model=case.points['model'],candidates=case.points['candidates'],
        context=case.points['context'],fixed_parents=list(case.fixed_parents),preferences=list(case.preferences))
    for call in (
        lambda:histories(case),lambda:prepare(case),
        lambda:ff.verify_f_math_result(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
        lambda:ff.restore_f_root(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
    ):
        with pytest.raises(error_type) as err:call()
        assert err.value.reason
        if not reason_only:assert err.value.field
        diagnostics.append((err.value.reason,err.value.field))
    if reason_only:
        assert [item[0] for item in diagnostics]==[diagnostics[0][0]]*4
    else:assert diagnostics==[diagnostics[0]]*4
    return diagnostics[0]


@pytest.mark.parametrize('fault',[None,'attempt-after-measurement','request-plan','job-plan',
    'request-step','job-step','job-header-step','binding-step','request-inputs','binding-plan'],
    ids=['at-start','attempt-after-measurement','request-plan','job-plan','request-step','job-step',
         'job-header-step','binding-step','request-inputs','binding-plan'])
def test_review5_R08_generation_requires_matching_plan_step_and_start(fault):
    # Kills authenticating a future generator, wrong Plan contract, or mismatched
    # request/job/binding steps merely because every referenced record exists.
    good=review5_generation_case();witness=review5_selected_roundtrip(good)
    raw=good.ledger.record(good.raw[0]);attempt=good.ledger.record(good.points['measure-attempt-1'])
    assert raw.body.content.as_json()['actual_time']['value']['time_ns']==attempt.at.mono_ns==SECOND
    assert raw.body.received_ns==SECOND+1
    assert witness.value.root.K.available==witness.value.root.K.incorporated==tuple(good.measurements)
    assert witness.value.root.K.belief==good.ref(good.computation['result'])
    assert witness.value.root.K.pending==()
    assert_quantity(witness.value.evaluation.J[0],0)
    if fault is not None:
        bad=review5_generation_case(fault=fault)
        assert bad.raw[0] in bad.reader.ancestors(bad.fixed_parents)
        assert_review5_primary_rejected(bad,witness)


@pytest.mark.parametrize('source_time_ns',[None,1790000000000000000,-1],ids=['no-utc','large-utc','negative-utc'])
def test_review5_R09_source_UTC_does_not_change_monotonic_math(source_time_ns):
    # Kills treating source UTC as nonnegative run time, or using it in E/K/choice.
    base=review5_generation_case();control=review5_selected_roundtrip(base)
    case=review5_generation_case(source_time_ns=source_time_ns);saved=review5_selected_roundtrip(case)
    assert case.ledger.record(case.raw[0]).body.source_time_ns==source_time_ns
    assert plain(saved.value.root.E)==plain(control.value.root.E)
    assert plain(saved.value.root.K)==plain(control.value.root.K)
    assert saved.value.choice.id==control.value.choice.id=='Compute'
    assert saved.value.u==control.value.u==F(1,4)
    for field in ('expected_cost','information','J','q_star'):
        assert plain(getattr(saved.value.evaluation,field))==plain(getattr(control.value.evaluation,field))


@pytest.mark.parametrize('fault',['measurement-after-receipt','receipt-after-record'])
def test_review5_R09_monotonic_order_is_still_required(fault):
    # Kills fixing UTC by deleting real measured<=received<=recorded checks.
    good=review5_generation_case(source_time_ns=-1);witness=review5_selected_roundtrip(good)
    if fault=='receipt-after-record':
        # Record's public constructor rejects this shape before ledger insertion;
        # no authentic saved artifact of this input exists to replay.
        with pytest.raises(ValueError,match='received_ns: must not follow the record time'):
            review5_generation_case(fault=fault,source_time_ns=-1)
        return
    bad=review5_generation_case(fault=fault,source_time_ns=-1)
    assert_review5_primary_rejected(bad,witness)


@pytest.mark.parametrize('kind',['clock_source','route','boot'])
def test_review5_R10_unreferenced_late_provenance_is_not_a_past_input(kind):
    # Kills adding all visible same-contract records to a past computation's
    # required inputs, instead of following that observation's actual dependencies.
    case=assemble_knowledge('adopted');before=review5_selected_roundtrip(case)
    requested=case.ledger.record(case.computation['request']).body.content.as_json()
    body=case.ledger.record(case.points[kind]).body
    case.clock.advance(1)
    late=case.put('unreferenced-'+kind,replace(body,received_ns=case.clock.mono_ns()))
    case.context();after=review5_selected_roundtrip(case)
    assert late not in requested['inputs']
    assert late not in case.reader.ancestors((case.computation['request'],))
    assert case.ledger.record(case.computation['request']).body.content.as_json()==requested
    assert before.value.root.E==after.value.root.E
    assert before.value.root.K==after.value.root.K
    assert after.value.root.K.incorporated==tuple(case.measurements)
    assert after.value.root.K.belief==case.ref(case.computation['result'])
    assert after.value.choice.id==before.value.choice.id=='Compute' and after.value.u==before.value.u==F(1,4)
    assert_quantity(after.value.evaluation.J[0],0)
    # Also preserve the old artifact when the reader can now see the extra record.
    data=ff.f_math_json(before);registry=f.builtin_f_registry()
    assert ff.verify_f_math_result(data,reader=case.reader,registry=registry,budget=BUDGET).root_key==before.value.root.root_key
    assert ff.restore_f_root(data,reader=case.reader,registry=registry,budget=BUDGET).K==before.value.root.K


def test_review5_R10_referenced_clock_source_cannot_be_missing():
    # Kills treating missing used provenance as harmless merely because unrelated
    # later provenance may be ignored. Missing body is not an empty dependency set.
    case=assemble_knowledge('adopted');witness=review5_selected_roundtrip(case)
    missing=case.points['clock_source']
    assert missing in case.ledger.record(case.computation['request']).body.content.as_json()['inputs']
    case.reader=MissingBodyReader(case.ledger,missing)
    data=ff.f_math_json(witness);registry=f.builtin_f_registry()
    for call in (
        lambda:histories(case),lambda:prepare(case),
        lambda:ff.verify_f_math_result(data,reader=case.reader,registry=registry,budget=BUDGET),
        lambda:ff.restore_f_root(data,reader=case.reader,registry=registry,budget=BUDGET),
    ):
        with pytest.raises(f.FReplayUnavailable) as err:call()
        assert err.value.reason=='missing_input'


@pytest.mark.parametrize('edge,control,change,diagnostic',[
    ('T06',{},dict(generated_ns=SECOND+1),('shape','/measurement')),
    # 今の約束 A-21 (2026-10-11): a raw/Binding/Plan/generation disagreement is
    # observation_binding_mismatch, no longer the generic proof_mismatch.
    ('T11',{},dict(generated_plan='other'),('observation_binding_mismatch','/measurement/generation/plan.cid')),
    ('T12',{},dict(request_plan='other'),('observation_binding_mismatch','/measurement/cause/job/value.plan')),
    ('T16',{},dict(generated_step=1),('observation_binding_mismatch','/measurement/generation/value.step')),
],ids=['T06-extra-after-measured','T11-extra-plan-cid','T12-request-plan-cid',
        'T16-extra-job-step'])
def test_review5_table_independent_generation_edges(edge,control,change,diagnostic):
    # Kills omitting the named edge while opportunity remains valid. T06
    # separates measured from end instead of assuming their equality.
    good=review5_table_case(**control);witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id=='Compute' and witness.value.u==F(1,4)
    assert witness.value.root.K.available==witness.value.root.K.incorporated==tuple(good.measurements)
    assert witness.value.root.K.belief==good.ref(good.computation['result'])
    assert_quantity(witness.value.evaluation.J[0],0)
    bad=review5_table_case(**dict(control,**change))
    value=lambda key:bad.ledger.record(bad.points[key]).body.content.as_json()
    binding=value('binding-0');raw=value('raw-0')
    assert binding['opportunity']==str(bad.ref(bad.points['measure-attempt-1']))
    assert binding['generated_by']==[str(bad.ref(bad.points['measure-attempt-'+str(i)])) for i in (1,2)]
    assert raw['actual_time']['value']['time_ns']==control.get('measured_ns',SECOND)
    assert raw['measurement_interval']['end_ns']==control.get('end_ns',SECOND+2)
    assert bad.points['plan-same']!=bad.points['plan-other']
    assert value('plan-same')==value('plan-other')  # same correct contract/body, different authenticated CID
    assert bad.ledger.record(bad.points['plan-other']).body.contract==fc.OBSERVATION_PLAN
    if edge=='T06':
        extra=bad.ledger.record(bad.points['measure-attempt-2']).at.mono_ns
        assert extra==SECOND+1
        assert min(raw['actual_time']['value']['time_ns'],raw['measurement_interval']['end_ns'])<extra
        assert extra<max(raw['actual_time']['value']['time_ns'],raw['measurement_interval']['end_ns'])
    elif edge=='T11':
        assert value('measure-request-2')['plan']==value('measure-job-2')['plan']==bad.points['plan-other']
        assert value('measure-job-1')['plan']==bad.points['plan-same']
    elif edge=='T12':
        assert value('measure-request-1')['plan']==bad.points['plan-other']
        assert value('measure-job-1')['plan']==bad.points['plan-same']
    else:
        assert value('measure-request-2')['step']==value('measure-job-2')['step']==1
        assert value('measure-job-1')['step']==binding['step']==0
    # T12's reason is fixed, but the spec does not fix the first closure path.
    if edge=='T12':assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]==diagnostic[0]
    else:
        # 今の約束 A-21 (2026-10-11): the pointer may name the column under this prefix.
        reason,field=assert_review5_primary_rejected(bad,witness)
        assert reason==diagnostic[0] and field.startswith(diagnostic[1])


@pytest.mark.parametrize('acquire_extra',[False,True],ids=['request-input','acquired-and-request-input'])
def test_review5_table_T25_unknown_observed_keeps_structural_checks(acquire_extra):
    # Kills exempting unknown named contracts from shared Observed constraints.
    # The same Point is read as a numeric request input, optionally first acquired;
    # Repeated public calls/replay must still reject. This older combined-fault
    # test does not isolate the initial/cached paths within one public call.
    args=dict(extra_input=True,acquire_extra=acquire_extra)
    good=review5_table_case(**args);witness=review5_selected_roundtrip(good)
    plain_control=review5_selected_roundtrip(review5_table_case())
    assert witness.value.root.E==plain_control.value.root.E
    assert witness.value.root.K.available==witness.value.root.K.incorporated==tuple(good.measurements)
    assert witness.value.choice.id==plain_control.value.choice.id=='Compute'
    assert witness.value.u==plain_control.value.u==F(1,4)
    assert_quantity(witness.value.evaluation.J[0],0)
    bad=review5_table_case(**args,unknown_run=True)
    extra=bad.points['extra-evidence'];record=bad.ledger.record(extra)
    assert record.body.contract==ContractRef('fixture.f.extra_evidence','1')
    assert record.at.run!=bad.clock.run and record.body.received_ns==record.at.mono_ns
    request=bad.ledger.record(bad.computation['request'])
    assert extra in request.body.content.as_json()['inputs'] and record.id in request.body.inputs
    for _ in range(2):
        reason,field=assert_review5_primary_rejected(bad,witness)
        assert reason=='clock_unaligned' and field.endswith('/run')


# 2026-10-12: T07 (coverage generator <= window end) retired. 今の約束 A-15
# (U-06) makes the builtin whole-window claim Attempt <= start, and a gap
# report Attempt <= receipt only; its old control (Attempt at the window end)
# is now illegal. The stronger relation is test_gate_f_auth_rel
# generation_class.{closed,no_arrival,gap} (independent test role).


def test_review5_table_T08_standalone_request_still_requires_plan_contract():
    # Kills deleting request.plan's contract check: a legitimate extra numeric
    # input need not have a Job whose Plan comparison could catch the bad type.
    good=review5_table_case(extra_request_plan='same');witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id=='Compute' and witness.value.u==F(1,4)
    assert witness.value.root.K.incorporated==tuple(good.measurements)
    assert_quantity(witness.value.evaluation.J[0],0)
    bad=review5_table_case(extra_request_plan='model')
    point=bad.points['extra-request'];record=bad.ledger.record(point)
    assert record.body.content.as_json()=={'plan':bad.points['model'],'step':0}
    assert record.body.inputs==(bad.ref(bad.points['model']),)
    assert point in bad.ledger.record(bad.computation['request']).body.content.as_json()['inputs']
    assert all(not isinstance(bad.reader.record(e.cid).body,JobOpened) or
               bad.reader.record(e.cid).body.decision!=record.id for e in bad.reader.entries())
    # §3-10-17-8: the field points at the causing field; the traversal prefix
    # that reached it is not specified (it moves when the closure order moves).
    reason,field=assert_review5_primary_rejected(bad,witness)
    assert reason=='unresolved_reference' and field.endswith('/outer_inputs/plan')


def assert_review5_structural_branch_control(good,bad):
    """Same authenticated input shape; only the extra Observed's run differs."""
    good_record=good.ledger.record(good.points['extra-evidence'])
    bad_record=bad.ledger.record(bad.points['extra-evidence'])
    assert good_record.at.run==good.clock.run
    assert bad_record.at.run!=bad.clock.run
    assert replace(bad_record.at,run=good_record.at.run)==good_record.at
    assert replace(bad_record,at=good_record.at)==good_record
    assert good_record.body.contract==ContractRef('fixture.f.extra_evidence','1')
    assert good_record.body.received_ns==good_record.at.mono_ns
    saved=review5_selected_roundtrip(good)
    assert saved.value.choice.id=='Compute' and saved.value.u==F(1,4)
    assert tuple(link.measurement for link in saved.value.root.E.links)==tuple(good.measurements)
    assert saved.value.root.K.available==saved.value.root.K.incorporated==tuple(good.measurements)
    assert saved.value.root.K.belief==good.ref(good.computation['result'])
    assert saved.value.root.K.pending==()
    assert_quantity(saved.value.evaluation.J[0],0)
    return saved


def test_review5_GF_T25_initial_structural_check_on_acquired_only_observed():
    # Kills GF-T25: first-read structural validation is required even when this
    # unknown Observed is only acquired, with no request-input reread to rescue it.
    good=review5_structural_branch_case('T25')
    bad=review5_structural_branch_case('T25',foreign=True)
    witness=assert_review5_structural_branch_control(good,bad)
    for case in (good,bad):
        extra=case.points['extra-evidence']
        records=[case.reader.record(entry.cid) for entry in case.reader.entries()]
        acquisitions=[record.body.content.as_json()['contents'] for record in records
                      if getattr(record.body,'contract',None)==fc.CONTENT_ACQUIRED]
        assert [contents for contents in acquisitions if extra in contents]==[[*case.raw,extra]]
        requested=case.ledger.record(case.computation['request'])
        assert extra not in requested.body.content.as_json()['inputs']
        assert case.ref(extra) not in requested.body.inputs
        assert case.ledger.record(case.points['clock_source']).body.caused_by is None
    assert assert_review5_primary_rejected(bad,witness)==('clock_unaligned','/acquisition/contents/run')


def test_review5_GF_T27_structural_check_after_precontext_read_of_same_point():
    # Kills GF-T27: source provenance reaches this Point before context is bound;
    # numeric request inputs revisit the SAME Point with that context in one call.
    # A precontext read must not exempt the later use from run alignment.
    good=review5_structural_branch_case('T27')
    bad=review5_structural_branch_case('T27',foreign=True)
    witness=assert_review5_structural_branch_control(good,bad)
    for case in (good,bad):
        extra=case.points['extra-evidence']
        source=case.ledger.record(case.points['clock_source'])
        attempt=case.ledger.record(case.points['source-attempt'])
        job=case.ledger.record(case.points['source-job'])
        decision=case.ledger.record(case.points['source-request'])
        assert source.body.caused_by==attempt.id
        assert attempt.body.job==job.id and job.body.decision==decision.id
        assert decision.body.inputs==(case.ref(extra),)
        assert extra in case.reader.ancestors((case.points['clock_source'],))
        requested=case.ledger.record(case.computation['request'])
        assert extra in requested.body.content.as_json()['inputs']
        assert case.ref(extra) in requested.body.inputs
        context=case.ledger.record(case.points['context']).body.content.as_json()
        for reading in (context['observation_reading'],context['judgment_reading']):
            assert case.ledger.record(reading).body.content.as_json()['source']==case.points['clock_source']
        assert all(extra not in case.reader.record(entry.cid).body.content.as_json()['contents']
                   for entry in case.reader.entries()
                   if getattr(case.reader.record(entry.cid).body,'contract',None)==fc.CONTENT_ACQUIRED)
    # Spec 4476/4628 fixes clock_unaligned, not the path of the first failing
    # visit. Spec 3300 requires refusal at the first boundary, before evaluation.
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='clock_unaligned'


def assert_review5_context_success(case):
    saved=review5_selected_roundtrip(case)
    assert saved.value.choice.id=='Q' and saved.value.u==F(1,4)
    assert saved.value.root.E.links==()
    assert saved.value.root.K.available==saved.value.root.K.incorporated==()
    assert saved.value.root.K.belief is None and saved.value.root.K.pending==()
    assert len(saved.value.evaluation.J)==2
    for value in saved.value.evaluation.J:assert_quantity(value,0)
    return saved


def test_review5_R11_context_rechecks_provenance_only_foreign_observed():
    # Kills treating a precontext visit as final: the extra Point occurs ONLY
    # in clock provenance, never as an acquisition, numeric input or check event.
    good=Review5ContextCase(scenario='R11');bad=Review5ContextCase(scenario='R11',foreign=True)
    witness=assert_review5_context_success(good)
    good_extra=good.ledger.record(good.points['source-extra'])
    bad_extra=bad.ledger.record(bad.points['source-extra'])
    assert replace(bad_extra,at=good_extra.at)==good_extra
    assert replace(bad_extra.at,run=good_extra.at.run)==good_extra.at
    assert good_extra.at.run==good.clock.run and bad_extra.at.run!=bad.clock.run
    for case in (good,bad):
        source=case.ledger.record(case.points['clock_source'])
        attempt=case.ledger.record(case.points['source-attempt'])
        job=case.ledger.record(case.points['source-job'])
        decision=case.ledger.record(case.points['source-request'])
        assert source.body.caused_by==attempt.id and attempt.body.job==job.id
        assert job.body.decision==decision.id and decision.body.inputs==(case.ref(case.points['source-extra']),)
        assert case.points['source-extra'] in case.reader.ancestors((case.points['clock_source'],))
        assert case.ledger.record(case.points['context']).body.content.as_json()['check_events']==[]
        assert case.computation=={} and case.raw==[]
        assert not any(getattr(case.reader.record(e.cid).body,'contract',None) in
                       (fc.CONTENT_ACQUIRED,fc.COMPUTATION_REQUESTED) for e in case.reader.entries())
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='clock_unaligned'


def test_review5_R13_GF_T01_foreign_job_cannot_start_local_clock_source_attempt():
    # Regression for the T01 counterexample: equal numeric timestamps cannot
    # establish Job<=Attempt when the Job/decision and Attempt use different runs.
    good=Review5ContextCase(scenario='T01');bad=Review5ContextCase(scenario='T01',foreign=True)
    witness=assert_review5_context_success(good)
    for case in (good,bad):
        job=case.ledger.record(case.points['source-job'])
        decision=case.ledger.record(case.points['source-request'])
        attempt=case.ledger.record(case.points['source-attempt'])
        source=case.ledger.record(case.points['clock_source'])
        assert job.at.mono_ns==decision.at.mono_ns==attempt.at.mono_ns==source.at.mono_ns==0
        assert job.body.decision==decision.id and attempt.body.job==job.id and source.body.caused_by==attempt.id
        assert job.at.run==decision.at.run
        assert attempt.at.run==source.at.run==case.clock.run
        assert (job.at.run==attempt.at.run)==(case is good)
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='clock_unaligned'


def test_review5_R13_GF_T23_local_reading_cannot_use_foreign_boot_and_source():
    # Regression for the T23 counterexample: a real foreign BOOT/SOURCE pair
    # does not align a local reading merely by having the same numeric time.
    good=Review5ContextCase(scenario='T23');bad=Review5ContextCase(scenario='T23',foreign=True)
    witness=assert_review5_context_success(good)
    for case in (good,bad):
        source=case.ledger.record(case.points['clock_source']);boot=case.ledger.record(case.points['boot'])
        assert isinstance(source.body,Observed) and isinstance(boot.body,Observed)
        assert source.at.run==boot.at.run
        assert source.body.content.as_json()['run']==str(source.at.run)
        assert case.points['boot'] in case.reader.ancestors((case.points['clock_source'],))
        for key in ('observed_clock','judgment_clock'):
            reading=case.ledger.record(case.points[key]);value=reading.body.content.as_json()
            assert value['source']==case.points['clock_source']
            assert value['reading']=={'run':str(case.clock.run),'time_ns':0}
            assert reading.at.run==case.clock.run
        assert (source.at.run==case.clock.run)==(case is good)
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='clock_unaligned'


@pytest.mark.parametrize('key',['clock_source','context','observed_clock','model','boot'],
    ids=['R12-clock-source','context','clock-reading','model-source','boot'])
def test_review5_R12_decoder_requires_declared_body_role_category(key):
    # Kills trusting authenticated contract+JSON while accepting its wrong body
    # kind/Role/Category. A predicted BOOT instead means no factual BOOT exists.
    good=Review5ContextCase();bad=Review5ContextCase(wrong_kind=key)
    witness=assert_review5_context_success(good)
    real=good.ledger.record(good.points[key]);fake=bad.ledger.record(bad.points[key])
    assert real.body.content.data==fake.body.content.data
    assert real.body.contract==fake.body.contract
    assert type(real.body)!=type(fake.body) and real.writer!=fake.writer and real.category!=fake.category
    assert isinstance(fake.body,Observed if key=='model' else Prediction)
    if key!='observed_clock':
        assert not any(isinstance(bad.reader.record(e.cid).body,type(real.body)) and
                       getattr(bad.reader.record(e.cid).body,'contract',None)==real.body.contract
                       for e in bad.reader.entries())
    exception=f.FReplayUnavailable if key=='boot' else f.FInputError
    reason='missing_input' if key=='boot' else 'shape'
    assert assert_review5_primary_rejected(bad,witness,reason_only=True,error_type=exception)[0]==reason


def test_review5_R12_draw_decoder_rejects_prediction_with_same_draw_json():
    # Kills the dedicated draw decoder accepting a model prediction of u as a
    # membrane draw. Preparation is legal; binding/evaluation and replay reject.
    case=Review5ContextCase();prepared=prepare(case)
    witness=assert_review5_context_success(case)
    # Use the actual primary draw Point from the fixture, not a fabricated root.
    draw_point=next(point for key,point in case.points.items() if key.startswith('draw-'))
    record=case.ledger.record(draw_point)
    fake=case.predict('predicted-draw',fc.DRAW_FACT,record.body.content.as_json())
    bad_record=case.ledger.record(fake)
    assert bad_record.body.content.data==record.body.content.data
    assert isinstance(bad_record.body,Prediction) and bad_record.writer!=record.writer
    for api in (ff.bind_f_draw,ff.evaluate_f_from_draw):
        with pytest.raises(f.FInputError) as err:api(prepared,fake,reader=case.reader,budget=BUDGET)
        assert err.value.reason=='invalid_draw'
    wire=json.loads(ff.f_math_json(witness))
    found=0
    for call in wire['calls']:
        if call['op']=='bind_draw':
            assert call['args']['draw']==draw_point
            call['args']['draw']=fake;found+=1
    assert found==1
    for api in (ff.verify_f_math_result,ff.restore_f_root):
        with pytest.raises(f.FInputError) as err:
            api(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET)
        assert err.value.reason=='invalid_draw'


@pytest.mark.parametrize('delta',[1,2],ids=['one-ns','two-ns'])
def test_review5_GF_T22_prior_context_in_clock_provenance_keeps_reading_order(delta):
    # Kills applying observation<=judgment only to the authoritative context:
    # its valid boundaries cannot constrain a different, prior context's pair.
    good=review5_prior_context_case();bad=review5_prior_context_case(reversed_by_ns=delta)
    witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id=='Compute' and witness.value.u==F(1,4)
    assert witness.value.root.K.available==witness.value.root.K.incorporated==tuple(good.measurements)
    assert witness.value.root.K.belief==good.ref(good.computation['result'])
    assert_quantity(witness.value.evaluation.J[0],0)
    old_good=good.ledger.record(good.points['prior_judgment'])
    old_bad=bad.ledger.record(bad.points['prior_judgment'])
    value=old_bad.body.content.as_json()
    value['reading']['time_ns']+=delta
    assert replace(old_bad,body=replace(old_bad.body,content=Payload.json(value)))==old_good
    for case in (good,bad):
        prior=case.points['prior_context'];current=case.points['context']
        assert prior!=current
        previous=case.ledger.record(prior).body.content.as_json()
        authoritative=case.ledger.record(current).body.content.as_json()
        read=lambda point:case.ledger.record(point).body.content.as_json()['reading']['time_ns']
        assert read(previous['observation_reading'])-read(previous['judgment_reading'])==(0 if case is good else delta)
        assert read(authoritative['observation_reading'])==read(authoritative['judgment_reading'])
        assert read(previous['observation_reading'])<read(authoritative['observation_reading'])
        source=case.ledger.record(case.points['clock_source'])
        attempt=case.ledger.record(case.points['provenance-attempt'])
        job=case.ledger.record(case.points['provenance-job'])
        request=case.ledger.record(case.points['provenance-request'])
        assert source.body.caused_by==attempt.id and attempt.body.job==job.id and job.body.decision==request.id
        assert request.body.inputs==(case.ref(case.bindings[0]),case.ref(case.computation['adopted']),case.ref(prior))
        assert prior in case.reader.ancestors((case.points['clock_source'],))
        numeric=case.ledger.record(case.computation['request'])
        assert prior not in numeric.body.content.as_json()['inputs'] and case.ref(prior) not in numeric.body.inputs
        assert prior not in [event['record'] for event in authoritative['check_events']]
        for entry in case.reader.entries():
            record=case.reader.record(entry.cid)
            if getattr(record.body,'contract',None)==fc.CONTENT_ACQUIRED:
                assert prior not in record.body.content.as_json()['contents']
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='shape'


def test_review5_GF_T02_standalone_frame_cause_after_measurement_is_input_error():
    # Kills weakening contradictory cause<=measured into missing_contract when
    # no Binding exists. The equality control itself is rootless NoDecision.
    good=review5_table_case(standalone_measured_ns=SECOND+1)
    bad=review5_table_case(standalone_measured_ns=SECOND)
    witness=prepare(good)
    assert_no_decision(witness.value,'rejected','missing_contract')
    assert_math_replay(witness,f.builtin_f_registry())
    real=good.ledger.record(good.points['standalone-frame'])
    changed=bad.ledger.record(bad.points['standalone-frame'])
    value=changed.body.content.as_json();value['actual_time']['value']['time_ns']+=1
    assert replace(changed,body=replace(changed.body,content=Payload.json(value)))==real
    for case in (good,bad):
        point=case.points['standalone-frame'];record=case.ledger.record(point)
        frame=record.body.content.as_json();attempt=case.ledger.record(case.points['standalone-attempt'])
        assert record.body.caused_by==attempt.id and attempt.at.mono_ns==SECOND+1
        assert frame['measurement_interval']['end_ns']==SECOND+2
        assert frame['actual_time']['value']['time_ns']==SECOND+(case is good)
        assert frame['actual_time']['value']['time_ns']<=attempt.at.mono_ns<frame['measurement_interval']['end_ns']
        request=case.ledger.record(case.computation['request'])
        assert point in request.body.content.as_json()['inputs'] and record.id in request.body.inputs
        bindings=[case.reader.record(e.cid).body.content.as_json() for e in case.reader.entries()
                  if getattr(case.reader.record(e.cid).body,'contract',None)==fc.OBSERVATION_BINDING]
        assert bindings and all(str(record.id) not in binding['records'] for binding in bindings)
    # Rootless replay needs its historical reader image. For a false success
    # claim instead rebind a real Selected; do not fake that image or its cache.
    selected=review5_selected_roundtrip(review5_table_case())
    assert selected.value.choice.id=='Compute'
    assert assert_review5_primary_rejected(bad,selected,reason_only=True)[0]=='shape'
    wire=json.loads(ff.f_math_json(selected))
    wire['input']['value'].update(model=bad.points['model'],candidates=bad.points['candidates'],
        context=bad.points['context'],fixed_parents=list(bad.fixed_parents),preferences=list(bad.preferences))
    # Every claimed root input must exist; a missing good-case candidate would
    # test replay availability instead of the standalone Frame's chronology.
    for key in ('model','candidates','context'):
        assert bad.reader.entry(wire['input']['value'][key]) is not None
    with pytest.raises(f.FInputError) as err:
        ff.restore_f_math_result(canonical(wire),reader=bad.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    assert err.value.reason=='shape'


def review5_closure_draw_roundtrip(case,prepared,draw):
    root=ff.bind_f_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(root.value,f.FRoot)
    saved=ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET)
    assert isinstance(saved.value,f.Selected) and saved.value.u==F(1,4)
    assert saved.value.root.E==prepared.value.E
    assert saved.value.root.K==prepared.value.K
    assert plain(saved.value.root.context)==plain(prepared.value.context)
    assert plain(root.value)==plain(saved.value.root)
    wire=ff.f_math_json(saved)
    verified=ff.verify_f_math_result(wire,reader=saved.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    restored=ff.restore_f_root(wire,reader=saved.reader,registry=f.builtin_f_registry(),budget=BUDGET)
    assert verified.kind=='math' and verified.artifact_digest==digest({'domain':'sui.f.math_artifact/2','artifact':json.loads(wire)})  # 今の約束 E-05
    assert plain(restored)==plain(saved.value.root)
    assert plain(f.evaluate_f_recursive(restored,budget=BUDGET))==plain(saved.value.evaluation)
    return saved


def assert_review5_closure_draw_rejected(case,prepared,draw,witness,reason):
    wire=json.loads(ff.f_math_json(witness));calls=[c for c in wire['calls'] if c['op']=='bind_draw']
    assert len(calls)==1;calls[0]['args']['draw']=draw
    for key in ('model','candidates','context'):assert case.reader.entry(wire['input']['value'][key]) is not None
    for call in (
        lambda:ff.bind_f_draw(prepared,draw,reader=case.reader,budget=BUDGET),
        lambda:ff.evaluate_f_from_draw(prepared,draw,reader=case.reader,budget=BUDGET),
        lambda:ff.verify_f_math_result(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
        lambda:ff.restore_f_root(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
    ):
        with pytest.raises(f.FInputError) as err:call()
        assert err.value.reason==reason


@pytest.mark.parametrize('kind,reason',[
    ('R14-clock','shape'),('R14-fact','shape'),('R15','shape'),('R16','unresolved_reference')])
def test_review5_closure_R14_R15_R16_primary_invariants(kind,reason):
    # Kills accepting past check_events against today's boundary, receipt before
    # its cause starts, or a null Binding cause that skips mandatory equality.
    good=review5_closure_primary_case(kind);bad=review5_closure_primary_case(kind,bad=True)
    witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id==('Compute' if kind=='R16' else 'Q') and witness.value.u==F(1,4)
    assert_quantity(witness.value.evaluation.J[0],0)
    key='binding-0' if kind=='R16' else ('new-source' if kind=='R15' else 'prior-check')
    real=good.ledger.record(good.points[key]);changed=bad.ledger.record(bad.points[key])
    if kind=='R16':
        assert changed.body.caused_by is None and real.body.caused_by==good.ref(good.points['measure-attempt-1'])
        assert replace(changed,body=replace(changed.body,caused_by=real.body.caused_by))==real
        assert witness.value.root.K.incorporated==tuple(good.measurements)
        assert len(witness.value.root.E.links)==1
        assert bad.ledger.record(bad.raw[0]).body.caused_by==bad.ref(bad.points['measure-attempt-1'])
    elif kind=='R15':
        assert changed.body.received_ns==0 and real.body.received_ns==SECOND
        assert real.at.mono_ns==changed.at.mono_ns==SECOND
        assert bad.ledger.record(bad.points['draw-cause-attempt']).at.mono_ns==SECOND
        assert replace(changed,body=replace(changed.body,received_ns=real.body.received_ns))==real
    else:
        if kind=='R14-clock':
            content=changed.body.content.as_json();content['reading']['time_ns']=SECOND
            assert replace(changed,body=replace(changed.body,content=Payload.json(content)))==real
        else:assert replace(changed,body=replace(changed.body,received_ns=SECOND))==real
        for case in (good,bad):
            prior=case.ledger.record(case.points['prior-context']).body.content.as_json()
            now=case.ledger.record(case.points['context']).body.content.as_json()
            assert prior['check_events']==[{'kind':kind.split('-')[1],'record':case.points['prior-check']}]
            read=lambda point:case.ledger.record(point).body.content.as_json()['reading']['time_ns']
            assert read(prior['observation_reading'])==read(prior['judgment_reading'])==SECOND
            assert read(now['judgment_reading'])==2*SECOND
            assert case.ref(case.points['prior-context']) in case.ledger.record(case.points['draw-cause-request']).body.inputs
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]==reason


def assert_review5_closure_edge_shape(case,edge,bad):
    if edge=='T01':
        job=case.ledger.record(case.points['draw-cause-job']);attempt=case.ledger.record(case.points['draw-cause-attempt'])
        assert job.at.mono_ns==attempt.at.mono_ns and (job.at.run!=attempt.at.run)==bad
        assert attempt.body.job==job.id
    elif edge=='T03':
        raw=case.ledger.record(case.points['post-raw']);value=raw.body.content.as_json()
        attempt=case.ledger.record(case.points['post-measure-attempt'])
        assert raw.body.caused_by==attempt.id
        assert value['actual_time']['value']['time_ns']==attempt.at.mono_ns==2*SECOND+20
        assert value['measurement_interval']['end_ns']==(SECOND+2 if bad else 2*SECOND+20)
        assert not any(getattr(case.reader.record(e.cid).body,'contract',None)==fc.OBSERVATION_BINDING
                       for e in case.reader.entries())
    elif edge=='T23':
        value=case.ledger.record(case.points['post-reading']).body.content.as_json()
        source=case.ledger.record(value['source'])
        assert (str(source.at.run)!=value['reading']['run'])==bad
        assert source.body.content.as_json()['run']==str(source.at.run)
    else:
        adoption=case.ledger.record(case.points['post-draw-adoption'])
        other=case.ledger.record(case.points['post-completion' if edge=='T20' else 'post-previous'])
        assert (adoption.at.run!=other.at.run)==bad
        field='completion' if edge=='T20' else 'previous'
        assert adoption.body.content.as_json()[field]==case.points['post-completion' if edge=='T20' else 'post-previous']
        assert other.id in adoption.body.inputs


@pytest.mark.parametrize('edge',['T01','T03','T20','T21','T23'])
def test_review5_closure_draw_GF_edges_after_prepare(edge):
    # Kills trusting later draw ancestors merely because the fixed problem was
    # already prepared. Valid late records must leave its E/K/context unchanged.
    good,prepared,draw=review5_closure_draw_case(edge)
    witness=review5_closure_draw_roundtrip(good,prepared,draw)
    assert witness.value.choice.id==('Compute' if edge in ('T20','T21') else 'Q')
    bad,bad_prepared,bad_draw=review5_closure_draw_case(edge,bad=True)
    assert plain(prepared.value)==plain(bad_prepared.value)
    for case,is_bad in ((good,False),(bad,True)):assert_review5_closure_edge_shape(case,edge,is_bad)
    assert_review5_closure_draw_rejected(bad,bad_prepared,bad_draw,witness,'shape' if edge=='T03' else 'clock_unaligned')


def review5_preflight_request(point):
    return f.FPreflightFacts(fixed_parents=(point,),model=None,required_records=(point,),required_capabilities=())


def review5_preflight_roundtrip(case,request):
    saved=ff.check_f_preflight_from_facts(case.reader,request,registry=f.builtin_f_registry(),budget=BUDGET)
    assert isinstance(saved.value,f.PreflightReady) and saved.value.input_key.startswith('sha256:')
    assert_math_replay(saved,f.builtin_f_registry())
    return saved


def assert_review5_preflight_rejected(case,request,witness,reason):
    wire=json.loads(ff.f_math_json(witness));wire['input']['value']=plain(request)
    for call in (
        lambda:ff.check_f_preflight_from_facts(case.reader,request,registry=f.builtin_f_registry(),budget=BUDGET),
        lambda:ff.verify_f_math_result(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
        lambda:ff.restore_f_math_result(canonical(wire),reader=case.reader,registry=f.builtin_f_registry(),budget=BUDGET),
    ):
        with pytest.raises(f.FInputError) as err:call()
        assert err.value.reason==reason


@pytest.mark.parametrize('edge',['T01','T03','T21','T23'])
def test_review5_closure_preflight_GF_edges_without_selected_context(edge):
    # Kills omitting these edges when preflight authenticates the closure with
    # no selected context. PreflightReady is a distinct successful result.
    good,_,draw=review5_closure_draw_case(edge)
    request=review5_preflight_request(draw);witness=review5_preflight_roundtrip(good,request)
    bad,_,bad_draw=review5_closure_draw_case(edge,bad=True)
    for case,is_bad in ((good,False),(bad,True)):assert_review5_closure_edge_shape(case,edge,is_bad)
    assert_review5_preflight_rejected(bad,review5_preflight_request(bad_draw),witness,
        'shape' if edge=='T03' else 'clock_unaligned')


@pytest.mark.parametrize('path',['prepare','draw','clock','past-context','preflight'])
def test_review5_closure_same_bad_point_is_rejected_on_every_path(path):
    # Kills path-dependent certification: precisely the same authentic Point
    # has a receipt 1ns before its cause, irrespective of how the input reaches it.
    good,prepared,point,draw=review5_closure_route_case(path)
    bad,bad_prepared,bad_point,bad_draw=review5_closure_route_case(path,bad=True)
    canonical_case,_,canonical_point,_=review5_closure_route_case('preflight',bad=True)
    assert bad_point==canonical_point
    assert bad.ledger.record(bad_point)==canonical_case.ledger.record(canonical_point)
    real=good.ledger.record(point);changed=bad.ledger.record(bad_point)
    assert real.body.received_ns==SECOND and changed.body.received_ns==SECOND-1
    assert replace(changed,body=replace(changed.body,received_ns=SECOND))==real
    if path=='preflight':
        witness=review5_preflight_roundtrip(good,review5_preflight_request(point))
        assert_review5_preflight_rejected(bad,review5_preflight_request(bad_point),witness,'shape')
    elif path=='draw':
        assert bad_point in bad.reader.ancestors((bad_draw,))
        assert bad.ref(bad_point) in bad.ledger.record(bad.points['draw-cause-request']).body.inputs
        witness=review5_closure_draw_roundtrip(good,prepared,draw)
        assert_review5_closure_draw_rejected(bad,bad_prepared,bad_draw,witness,'shape')
    else:
        witness=review5_selected_roundtrip(good)
        assert witness.value.choice.id=='Q' and witness.value.u==F(1,4)
        if path=='prepare':assert bad_point in bad.fixed_parents
        else:
            assert bad_point in bad.reader.ancestors((bad.points['route-source'],))
            linked=bad_point if path=='clock' else bad.points['route-prior']
            assert bad.ref(linked) in bad.ledger.record(bad.points['draw-cause-request']).body.inputs
            if path=='past-context':
                assert bad.ledger.record(linked).body.content.as_json()['check_events']==[{'kind':'fact','record':bad_point}]
        assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='shape'


def test_review5_GF_T03_unavailable_actual_still_checks_attempt_before_interval_end():
    # Kills dropping cause.at <= interval.end: Unavailable removes the measured
    # clock comparison that masked this edge in the previous T03 witness.
    good,_,point=review5_closure_draw_case('T03',actual_unavailable=True)
    bad,_,bad_point=review5_closure_draw_case('T03',bad=True,actual_unavailable=True)
    good_raw=good.ledger.record(good.points['post-raw'])
    bad_raw=bad.ledger.record(bad.points['post-raw'])
    good_value=good_raw.body.content.as_json();bad_value=bad_raw.body.content.as_json()
    for case,record,value in ((good,good_raw,good_value),(bad,bad_raw,bad_value)):
        attempt=case.ledger.record(case.points['post-measure-attempt'])
        assert record.body.caused_by==attempt.id
        assert attempt.at.mono_ns==2*SECOND+20
        assert value['actual_time']=={'kind':'unavailable','value':{'reason':'clock_unavailable','basis':[]}}
        assert record.body.received_ns==record.at.mono_ns==attempt.at.mono_ns
        assert not any(getattr(case.reader.record(e.cid).body,'contract',None)==fc.OBSERVATION_BINDING
                       for e in case.reader.entries())
    assert good_value['measurement_interval']['end_ns']==2*SECOND+20
    assert bad_value['measurement_interval']['end_ns']==SECOND+2
    repaired=deepcopy(bad_value);repaired['measurement_interval']['end_ns']=2*SECOND+20
    assert repaired==good_value
    assert replace(bad_raw,body=replace(bad_raw.body,content=Payload.json(repaired)))==good_raw
    witness=review5_preflight_roundtrip(good,review5_preflight_request(point))
    assert_review5_preflight_rejected(bad,review5_preflight_request(bad_point),witness,'shape')


def test_review5_GF_K05_first_cid_unknown_observed_checks_cause_before_receipt():
    # Kills skipping the first CID in the closure. No named F contract is
    # needed for the common Attempt start <= receipt <= recording invariant.
    good,point=review5_first_unknown_observed()
    bad,bad_point=review5_first_unknown_observed(bad=True)
    for case,record_point,is_bad in ((good,point,False),(bad,bad_point,True)):
        assert record_point==min(case.reader.ancestors((record_point,)))
        assert case.reader.ancestors((record_point,))==frozenset(case.points.values())
        record=case.ledger.record(record_point);attempt=case.ledger.record(case.points['attempt'])
        assert record.body.contract==ContractRef('fixture.probe.unknown','1')
        assert record.body.content.as_json()=={'nonce':0}
        assert record.body.caused_by==attempt.id
        assert record.body.received_ns==(0 if is_bad else SECOND)
        assert record.at.mono_ns==attempt.at.mono_ns==SECOND
    real=good.ledger.record(point);changed=bad.ledger.record(bad_point)
    assert replace(changed,body=replace(changed.body,received_ns=SECOND))==real
    witness=review5_preflight_roundtrip(good,review5_preflight_request(point))
    assert_review5_preflight_rejected(bad,review5_preflight_request(bad_point),witness,'shape')


def test_review5_GF_K04_candidate_basis_may_be_a_nonancestor_prediction():
    # Kills over-restricting generation.basis Points to causal ancestors.
    # F §3-10-16-6 declares Point references; §3-10-16-2 expressly separates
    # Prediction references from causal parents (Prediction cannot be a parent).
    case,owner,basis=review5_candidate_nonancestor_basis()
    record=case.ledger.record(owner);basis_record=case.ledger.record(basis)
    ancestors=case.reader.ancestors((owner,))
    assert basis not in ancestors
    assert case.reader.entry(basis).parents<=ancestors
    assert isinstance(record.body,Prediction) and isinstance(basis_record.body,Prediction)
    assert record.body.content.as_json()['generation']['basis']==[basis]
    # 今の約束 A-04 (2026-10-11): the outer basis contains generation.basis.
    assert record.body.basis==(case.ref(case.points['model']),case.ref(basis))
    assert basis_record.body.contract==fc.QUANTITY_DECLARATION
    assert basis_record.body.content.as_json()=={
        'kind':'rational_constant','value':[1,1],'unit':'dimensionless','provenance':[]}
    # Existing model basis is a control with the same non-ancestor leaf shape.
    control=review5_preflight_roundtrip(case,review5_preflight_request(case.points['candidates']))
    witness=review5_preflight_roundtrip(case,review5_preflight_request(owner))
    assert witness.value.input_key!=control.value.input_key


@pytest.mark.parametrize('fault',['clock','receipt','clock-and-receipt'])
def test_review5_R17_acquisition_cannot_predate_received_measurement(fault):
    # Kills certifying past acquisition by relying on its later Record.at.
    # Each individual time is isolated; the combined case retains R17's input.
    good=review5_reference_acquisition_case()
    bad=review5_reference_acquisition_case(clock_ns=0 if 'clock' in fault else SECOND,
        received_ns=0 if 'receipt' in fault else SECOND)
    for case in (good,bad):
        raw=case.ledger.record(case.raw[0]);value=raw.body.content.as_json()
        assert raw.body.received_ns==value['actual_time']['value']['time_ns']==SECOND
        acquisition=case.ledger.record(case.points['reference-acquisition'])
        assert acquisition.at.mono_ns>raw.at.mono_ns
        assert acquisition.body.content.as_json()['contents']==case.raw
    real_clock=good.ledger.record(good.points['reference-acquisition-clock'])
    fake_clock=bad.ledger.record(bad.points['reference-acquisition-clock'])
    repaired_clock=fake_clock.body.content.as_json();repaired_clock['reading']['time_ns']=SECOND
    assert replace(fake_clock,body=replace(fake_clock.body,content=Payload.json(repaired_clock)))==real_clock
    real=good.ledger.record(good.points['reference-acquisition'])
    fake=bad.ledger.record(bad.points['reference-acquisition'])
    repaired=fake.body.content.as_json();repaired['clock']=good.points['reference-acquisition-clock']
    assert replace(fake,body=replace(fake.body,received_ns=SECOND,content=Payload.json(repaired)))==real
    witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id=='Compute' and witness.value.u==F(1,4)
    assert witness.value.root.K.available==tuple(good.measurements)
    assert witness.value.root.K.incorporated==() and witness.value.root.K.belief is None
    assert witness.value.root.E.links[0].measurement==good.measurements[0]
    assert set(witness.value.root.E.links[0].records)=={good.ref(good.raw[0])}
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='shape'


@pytest.mark.parametrize('kind',['completion','context','route-evidence'])
def test_review5_R17_reference_time_rule_applies_beyond_acquisition(kind):
    # Kills applying temporal reference checks only to ContentAcquired:
    # completion -> finish clock, context -> reading, route -> evidence fact.
    good=review5_reference_event_case(kind);bad=review5_reference_event_case(kind,bad=True)
    real=good.ledger.record(good.points['reference_owner'])
    fake=bad.ledger.record(bad.points['reference_owner'])
    dependency=good.ledger.record(good.points['reference_dependency'])
    assert good.points['reference_dependency']==bad.points['reference_dependency']
    if kind=='route-evidence':
        repaired=fake.body.content.as_json()
        assert repaired['effective_from']['value']['time_ns']==SECOND-1
        repaired['effective_from']['value']['time_ns']=SECOND
        assert replace(fake,body=replace(fake.body,content=Payload.json(repaired)))==real
    else:
        assert fake.body.received_ns==real.body.received_ns-1
        assert replace(fake,body=replace(fake.body,received_ns=real.body.received_ns))==real
    value=real.body.content.as_json();dep=dependency.body.content.as_json()
    if kind=='completion':
        assert value['finished_clock']==good.points['reference_dependency']
        assert dep['reading']['time_ns']==real.body.received_ns
    elif kind=='context':
        assert value['judgment_reading']==good.points['reference_dependency']
        assert dep['reading']['time_ns']==real.body.received_ns
    else:
        assert value['evidence']==[str(dependency.id)]
        assert dependency.body.received_ns==real.body.received_ns
        assert value['effective_from']['value']['time_ns']==dependency.body.received_ns==SECOND
    witness=review5_selected_roundtrip(good)
    assert witness.value.choice.id==('Compute' if kind=='completion' else 'Q')
    assert witness.value.u==F(1,4)
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='shape'


def test_review5_R18_unused_route_allows_unavailable_effective_time():
    # Kills treating a legal ClockReading|Unavailable branch as a missing field.
    # An unrelated route does not require a usable effective clock for selection.
    known=review5_unavailable_route_case();unknown=review5_unavailable_route_case(unknown=True)
    original=known.ledger.record(known.points['reference_route'])
    changed=unknown.ledger.record(unknown.points['reference_route'])
    repaired=changed.body.content.as_json()
    assert repaired['effective_from']=={'kind':'unavailable','value':{'reason':'clock_unavailable','basis':[]}}
    repaired['effective_from']=original.body.content.as_json()['effective_from']
    assert replace(changed,body=replace(changed.body,content=Payload.json(repaired)))==original
    selected=[]
    for case in (known,unknown):
        assert case.raw==[]
        saved=review5_selected_roundtrip(case);selected.append(saved.value)
        assert saved.value.choice.id=='Q' and saved.value.u==F(1,4)
        assert saved.value.root.E.links==() and saved.value.root.K.available==()
        request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=case.points['model'],
            required_records=(case.points['reference_route'],),required_capabilities=())
        review5_preflight_roundtrip(case,request)
    assert plain(selected[0].root.E)==plain(selected[1].root.E)
    assert plain(selected[0].root.K)==plain(selected[1].root.K)
    assert plain(selected[0].evaluation.J)==plain(selected[1].evaluation.J)


def test_review5_R18_used_route_unavailable_is_incomplete_not_shape_or_success():
    # Kills calling legal missing time a shape error, or silently assuming time
    # zero for a route whose measurement is needed. No root is issued.
    known=review5_unavailable_route_case(used=True)
    unknown=review5_unavailable_route_case(used=True,unknown=True)
    witness=review5_selected_roundtrip(known)
    assert witness.value.choice.id=='Compute' and witness.value.u==F(1,4)
    for case in (known,unknown):
        assert case.ledger.record(case.raw[0]).body.content.as_json()['route_epoch']=='route-1'
        assert case.ledger.record(case.points['reference_route']).body.content.as_json()['config']['route_epoch']=='route-1'
    original=known.ledger.record(known.points['reference_route'])
    changed=unknown.ledger.record(unknown.points['reference_route'])
    repaired=changed.body.content.as_json()
    assert repaired['effective_from']=={'kind':'unavailable','value':{'reason':'clock_unavailable','basis':[]}}
    repaired['effective_from']=original.body.content.as_json()['effective_from']
    assert replace(changed,body=replace(changed.body,content=Payload.json(repaired)))==original
    with pytest.raises(f.FIncomplete) as error:histories(unknown)
    assert error.value.reason=='certificate_incomplete'
    saved=prepare(unknown)
    assert_no_decision(saved.value,'incomplete','certificate_incomplete')
    assert_math_replay(saved,f.builtin_f_registry())


# ---------------------------------------------------------------------------
# §3-10-17 (spec v0.15) — written by Claude from the spec text before the
# implementation change (2026-10-10, Codex unavailable; ゆう 15:0x). Each test
# names the §3-10-17 rule and the wrong implementation it kills.

def auth_result_acquisition_case(*,clock_offset_ns=0):
    """R20: raw acquired with a correct clock; result/proof acquired separately.

    Only the result/proof acquisition clock moves relative to the completion's
    finished_clock reading, so R17 (raw receipt <= acquisition) cannot mask it.
    """
    case=assemble_knowledge('computed-unacquired')
    finish=case.ledger.record(case.points['computation-finish']).body.content.as_json()['reading']['time_ns']
    case.clock.advance(SECOND)
    raw_clock=case.reading('auth-raw-clock')
    case.acquire(tuple(case.raw),clock=raw_clock)
    result_clock=case.reading('auth-result-clock',finish+clock_offset_ns)
    case.acquire((case.computation['result'],case.computation['proof']),clock=result_clock)
    case.decide('adopted',fc.KNOWLEDGE_ADOPTED,
        f.KnowledgeAdopted(origin=case.points['origin'],previous=None,completion=case.computation['completed']),
        inputs=(case.points['origin'],case.computation['completed']))
    case.context()
    return case,finish


@pytest.mark.parametrize('offset',[0,1],ids=['clock-at-finish','clock-after-finish'])
def test_auth_17_3_result_acquired_at_or_after_generation_is_adoptable(offset):
    # §3-10-17-3: g <= a.clock.reading. Equality and later clocks are legal.
    # Kills an over-strict rule (a.clock < g required, or receipt compared to g).
    case,finish=auth_result_acquisition_case(clock_offset_ns=offset)
    clock=case.ledger.record(case.points['auth-result-clock'])
    assert clock.body.content.as_json()['reading']['time_ns']==finish+offset
    assert clock.body.received_ns>finish+offset   # the notice itself is late
    saved=review5_selected_roundtrip(case)
    assert saved.value.root.K.incorporated==tuple(case.measurements)


def test_auth_17_3_R20_result_acquired_before_generation_cannot_be_adopted():
    # §3-10-17-3 / §3-10-17-5 K2 (R20): finished_clock.reading <= acquisition
    # clock reading is required; comparing only the acquisition receipt (which
    # is late here) to the finish reading must not repair it.
    good,finish=auth_result_acquisition_case()
    bad,_=auth_result_acquisition_case(clock_offset_ns=-1)
    clock=bad.ledger.record(bad.points['auth-result-clock'])
    assert clock.body.content.as_json()['reading']['time_ns']==finish-1
    acquisition=[e.cid for e in bad.ledger.entries()
                 if getattr(bad.ledger.record(e.cid).body,'contract',None)==fc.CONTENT_ACQUIRED][-1]
    assert bad.ledger.record(acquisition).body.received_ns>=finish
    witness=review5_selected_roundtrip(good)
    assert assert_review5_primary_rejected(bad,witness,reason_only=True)[0]=='shape'


def auth_put(case,key,body,kind):
    from sui.records import Record, Role
    record=Record(id=case.ids.new(kind),at=case.clock.now(),writer=Role.MODEL,producer=PRODUCER,body=body)
    case.points[key]=case.ledger.append(record,case.ledger.heads()).cid
    return case.points[key]


@pytest.mark.parametrize('body',['intention','interpretation'])
def test_auth_17_2_R21_every_legal_body_has_a_total_rule(body):
    # §3-10-17-2 / §3-10-17-8 (R21): Intention and Interpretation are legal
    # Bodies; a Decided that uses one is authenticated by the structural rules,
    # never by a StopIteration from an incomplete table. Kills a table that
    # omits a Body kind (lookup failure leaking out of prepare/preflight).
    from sui.ids import RefKind
    from sui.records import Intention, IntentionStatus, Interpretation
    case=assemble('FA08')
    marker=ContractRef('fixture.auth.marker','1')
    if body=='intention':
        decision=case.decide('auth-intent-decision',marker,{},inputs=())
        point=auth_put(case,'auth-body',Intention(target=case.ref(case.points['model']),operation='remember',
            status=IntentionStatus.CONFIRMED,decided_in=case.ref(decision),content=Payload.json({}),contract=marker),
            RefKind.INTENTION)
    else:
        point=auth_put(case,'auth-body',Interpretation(about=(case.ref(case.points['model']),),basis=(),
            content=Payload.json({}),contract=marker),RefKind.INTERPRETATION)
    case.decide('auth-user',marker,{},inputs=(point,))
    case.context(save_delay_ns=0)
    saved=review5_selected_roundtrip(case)
    assert saved.value.choice.id=='Q'
    request=f.FPreflightFacts(fixed_parents=case.fixed_parents,model=case.points['model'],
        required_records=(case.points['auth-user'],),required_capabilities=())
    review5_preflight_roundtrip(case,request)


def auth_late_source_case(*,source_ns):
    """R22: measured at 1s; the run's only ClockSource notice arrives at
    source_ns; the measurement record (and Binding) are received/saved at 2s."""
    from copy import deepcopy as _deepcopy
    from sui.clock import FakeClock
    from sui.clock_contracts import ClockSource, SOURCE
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, MemoryContents, SequentialSalts
    from sui.s4_contracts import BOOT
    from gate_f_facts_cases import CLOCK
    document,actions=finite_world('FA06')
    case=FactsCase.__new__(FactsCase)
    case.document=_deepcopy(document);case.clock=FakeClock(run=Ref(RefKind.RUN,'facts-auth-late-source'))
    case.ids=SequentialIds(prefix='facts-auth-late-source')
    case.ledger=Ledger(salts=SequentialSalts(),contents=MemoryContents());case.reader=Reader(case.ledger)
    case.points={};case.raw=[];case.bindings=[];case.plans=[];case.measurements=[]
    case.preferences=[];case.computation={}
    case.scope=f.EvaluationScope(name='unbounded_total',version='1',H_ns=None,source=None)
    case.put('boot',Observed(route='membrane',content=Payload.json({}),contract=BOOT,received_ns=0))
    case.predict('model',fc.MODEL_SOURCE,f.FModelSource(document=case.document))
    case.observe('origin',fc.KNOWLEDGE_ORIGIN,f.KnowledgeOrigin(model=case.points['model']))
    source=ClockSource(run=case.clock.run,provider='test.facts',implementation='FakeClock',
        python_version='3.12.10',resolution_s=F(1,SECOND),monotonic=True,adjustable=False,measurement=CLOCK)
    real_observe=case.observe
    def observe(key,contract,value,**kw):
        if contract==fc.MEASUREMENT:
            case.clock.advance(source_ns-case.clock.mono_ns())
            real_observe('clock_source',SOURCE,source.as_json())
            case.clock.advance(2*SECOND-case.clock.mono_ns())
        return real_observe(key,contract,value,**kw)
    case.observe=observe
    add_observations(case)            # attempt before 1s; frame actual_time 1s
    case.observe=real_observe
    raw=case.ledger.record(case.raw[0])
    case.candidate(tuple(x.id for x in actions));case.context()
    return case,raw


def test_auth_17_3_R22_clock_provenance_notice_after_measurement_is_legal():
    # §3-10-17-3 / T2 (R22): ClockSource.received is the arrival of a provenance
    # notice, not the start of the clock. The clock_provenance edge creates no
    # notice-receipt <= measurement comparison. Kills the default availability
    # rule applied to provenance (a 1.5s re-notice rejecting a 1s measurement).
    case,raw=auth_late_source_case(source_ns=SECOND+SECOND//2)
    renotice=case.ledger.record(case.points['clock_source'])
    value=raw.body.content.as_json()
    assert value['actual_time']['value']['time_ns']==SECOND
    assert renotice.body.received_ns==SECOND+SECOND//2>value['actual_time']['value']['time_ns']
    assert raw.body.received_ns==2*SECOND and case.points['clock_source'] in case.reader.ancestors((case.raw[0],))
    saved=review5_selected_roundtrip(case)
    assert saved.value.root.E.links[0].measurement==case.measurements[0]


def auth_coverage_record(case,kind,*,end_ns):
    from gate_f_facts_cases import CLOCK, MEASURING
    route=f.RouteConfig(route_epoch='route-1',origin='bootstrap',version='1',sampling_contract=MEASURING,
        clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),
        args={},decision=None,execution=None)
    case.observe('auth-route',fc.ROUTE_CONFIG,{'config':plain(route),
        'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=0))},
        'execution':None,'evidence':[]})
    interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,end_ns=end_ns,closure='(start,end]')
    if kind=='coverage_unproved':
        value=f.CoverageUnproved(route_epoch='route-1',interval=interval,missing_contracts=(),evidence=())
    elif kind=='claim':
        value=f.CoverageClaim(route_epoch='route-1',interval=interval,kind='no_arrival',
                              contract=MEASURING,evidence=())
    else:
        value=f.Gap(route_epoch='route-1',sequence_range=(1,2),interval=interval,reason='lost',evidence=())
    return case.observe('auth-coverage',fc.COVERAGE,{'kind':kind,'value':plain(value)})


@pytest.mark.parametrize('kind',['claim','gap'])
def test_auth_17_12_D1_completed_window_claim_cannot_end_after_its_receipt(kind):
    # §3-10-17-12 D1: CoverageClaim and Gap report a completed observation
    # window, so interval.end <= that report's receipt. End == receipt is legal.
    # Kills dropping the completed-window rule for these kinds.
    for end,ok in ((0,True),(1,False)):
        case=assemble('FA08');case.clock.advance(SECOND)
        point=auth_coverage_record(case,kind,end_ns=case.clock.mono_ns()+end)
        record=case.ledger.record(point)
        assert record.body.received_ns==case.clock.mono_ns()
        request=review5_preflight_request(point)
        if ok:
            review5_preflight_roundtrip(case,request)
        else:
            with pytest.raises(f.FInputError) as err:
                ff.check_f_preflight_from_facts(case.reader,request,registry=f.builtin_f_registry(),budget=BUDGET)
            assert err.value.reason=='shape'


def test_auth_17_12_D1_coverage_unproved_may_extend_past_its_receipt():
    # §3-10-17-12 D1: CoverageUnproved states the current lack of proof; it
    # asserts no future event, so no end <= receipt rule. Kills applying the
    # completed-window rule to every coverage kind.
    case=assemble('FA08');case.clock.advance(SECOND)
    point=auth_coverage_record(case,'coverage_unproved',end_ns=case.clock.mono_ns()+2*SECOND)
    assert case.ledger.record(point).body.received_ns==case.clock.mono_ns()
    review5_preflight_roundtrip(case,review5_preflight_request(point))


def auth_gap_frame(case,*,gap_end_ns):
    from gate_f_facts_cases import CLOCK, MEASURING, QUALITY, CURSOR
    route=f.RouteConfig(route_epoch='route-1',origin='bootstrap',version='1',sampling_contract=MEASURING,
        clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),args={},decision=None,execution=None)
    case.observe('auth-route',fc.ROUTE_CONFIG,{'config':plain(route),
        'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=0))},
        'execution':None,'evidence':[]})
    now=case.clock.mono_ns()
    mid=f.MeasurementId(origin=case.clock.run,route_epoch='route-1',sample_seq=1,component='value')
    gap=f.Gap(route_epoch='route-1',sequence_range=(1,2),
        interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,end_ns=gap_end_ns,closure='(start,end]'),
        reason='lost',evidence=())
    frame=f.MeasurementFrame(route_epoch='route-1',sample_seq=1,measurement_id=mid,
        measurement_interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,end_ns=now,closure='(start,end]'),
        actual_time=f.Unavailable(reason='clock_unavailable',basis=()),value=f.Unavailable(reason='lost',basis=()),
        quality=f.ContractValue(contract=QUALITY,value='measured'),gap=gap,
        source_cursor=f.ContractValue(contract=CURSOR,value=1))
    return case.observe('auth-gap-frame',fc.MEASUREMENT,frame,route='route-1')


def test_auth_17_12_D1_frame_gap_is_part_of_the_completed_window():
    # §3-10-17-12 D1: MeasurementFrame reports a completed window including its
    # gap, so gap.interval.end <= the frame's receipt. Equality is legal.
    # Kills omitting the gap interval from the completed-window rule.
    for extra,ok in ((0,True),(1,False)):
        case=assemble('FA08');case.clock.advance(SECOND)
        point=auth_gap_frame(case,gap_end_ns=case.clock.mono_ns()+extra)
        assert case.ledger.record(point).body.received_ns==case.clock.mono_ns()
        request=review5_preflight_request(point)
        if ok:
            review5_preflight_roundtrip(case,request)
        else:
            with pytest.raises(f.FInputError) as err:
                ff.check_f_preflight_from_facts(case.reader,request,registry=f.builtin_f_registry(),budget=BUDGET)
            assert err.value.reason=='shape'
