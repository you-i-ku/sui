"""v0.14 facts-only dry-run fixtures. No E/K/context/root/alias compiler here.

Only Record/Payload/Contract DTOs and Ledger.append assemble primary facts.
Model outcome.available is a FUTURE kernel declaration, never K.available.
Calculation wrappers are separate from assembly. See SESSION_LOG at the end.
"""
from __future__ import annotations
from dataclasses import dataclass, fields, is_dataclass, replace
from collections.abc import Mapping
from fractions import Fraction as F
from hashlib import sha256
from pathlib import Path
from copy import deepcopy
from enum import Enum
import json

from sui import f, f_contracts as fc, f_facts as ff
from sui.clock import FakeClock
from sui.clock_contracts import ClockSource, SOURCE
from sui.s4_contracts import BOOT
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind, SequentialIds
from sui.ledger import Ledger, MemoryContents, SequentialSalts
from sui.records import (Record, Observed, Decided, Prediction, Preference, JobOpened,
                         AttemptStarted, Payload, Producer, Role, Category)
from sui.rate import RateBudget

SECOND = 10**9
BUDGET = RateBudget(tolerance=F(1,10**25), max_cells=4096, max_terms=4096, max_refinements=32)
FIXED = json.loads(Path(__file__).with_name('fixed_gate_f.json').read_bytes())['items']
GENERATOR = ContractRef('sui.f.explicit_candidates', '1')
METHOD = ContractRef('sui.f.finite_evaluation', '1')
CLOCK = ContractRef('sui.f.simulated_clock', '1')
MEASURING = ContractRef('sui.f.finite_measurement', '1')
QUALITY = ContractRef('sui.f.measured_quality', '1')
CURSOR = ContractRef('sui.f.sequence_cursor', '1')
TIME_PROJECTION = ContractRef('sui.f.value_only', '1')
GENERATION = ContractRef('sui.f.opportunity_step_slot', '1')
LEGACY_PREFERENCE = ContractRef('sui.s4d.preference', '1')
PRODUCER = Producer(component='fixture.gate_f_facts', code_version='v0.14')


def plain(value):
    if isinstance(value, Ref): return str(value)
    if isinstance(value, F): return [value.numerator, value.denominator]
    if isinstance(value, Enum): return value.value
    if isinstance(value, f.ExactReal):
        return {x.name: plain(getattr(value,x.name)) for x in fields(value) if getattr(value,x.name) is not None}
    if isinstance(value, f.MeasurementFrame):
        out = {x.name: plain(getattr(value,x.name)) for x in fields(value)}
        out['value'] = {'kind':'unavailable' if isinstance(value.value,f.Unavailable) else 'value','value':plain(value.value)}
        out['actual_time'] = {'kind':'unavailable' if isinstance(value.actual_time,f.Unavailable) else 'clock','value':plain(value.actual_time)}
        return out
    if is_dataclass(value): return {x.name:plain(getattr(value,x.name)) for x in fields(value)}
    if isinstance(value, Mapping): return {key:plain(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)): return [plain(item) for item in value]
    if isinstance(value,(set,frozenset)): return sorted((plain(item) for item in value),key=canonical)
    return value


def canonical(value):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(',',':'),allow_nan=False).encode('utf-8')


def digest(value): return 'sha256:'+sha256(canonical(value)).hexdigest()


def action(name, kernel, policy=None, *, never=False, path_action='default',
           proof_name='finite_option_proof', opportunity=None):
    return f.FActionDeclaration(id=name,
        family=f.ActionFamilyRef(name='finite_option',version='1'),
        args={'opportunity':name if opportunity is None else opportunity,
              'path_action':name if path_action == 'default' else path_action},
        start=predicate(True),policy=f.PolicyRef(name='finite_policy',version='1',args={'id':policy or name}),
        termination=f.PredicateRef(name='policy_end',version='1',args={}),
        termination_kind='may_never' if never else 'certain',
        prediction=f.KernelRef(name='finite_kernel',version='1',args={'id':kernel}),
        execution=ContractRef('sui.f.simulated_execution','1'),
        proof=f.ProofRef(name=proof_name,version='1',args={'operation':name}))


def declaration(kernels, actions, policies, *, states=None, targets=None, initial=None):
    return {'scheme':'sui.model.11','contract':plain(fc.FINITE_MODEL_V2),
        'units':{'record':'ns','duration':'ns','information':'nat','cost':'nat'},
        'targets':targets or ['x0','x1'],
        'states':states or [{'id':'s0','target':'x0'},{'id':'s1','target':'x1'}],
        'initial':plain([F(x) for x in initial] if initial is not None else [F(1,2)]*2),
        'kernels':kernels,'operations':plain(actions),'policies':policies,
        'certificate_capabilities':plain(tuple(ContractRef(name,'1') for name in
          ('finite_tree','fixed_policy_tail','static_target_entropy_bound','finite_terminal_cost')))}


def predicate(value):
    return f.PredicateRef(name='constant', version='1', args={'value': value})


def diagonal(values):
    return [[F(value) if i == j else F(0) for j in range(len(values))]
            for i, value in enumerate(values)]


def outcome(name, matrix, *, elapsed=SECOND, value=None, slot='m',
            completion=True, reveal=True, kind='measurement', computation=None):
    emission = None if value is None else {
        'slot': slot, 'kind': kind, 'value': value, 'measurement_contract': plain(MEASURING)}
    return {'id': name, 'elapsed_ns': elapsed, 'matrix': plain(matrix),
            'evidence': emission, 'available': {'reveal': [slot] if emission and reveal else [],
                                               'computation': computation},
            'completion': completion}


def bit_kernel(name, accuracy=F(1), *, elapsed=SECOND, slot='m'):
    return {'id': name, 'outcomes': [
        outcome('y0', diagonal((accuracy, 1 - accuracy)), elapsed=elapsed, value=0, slot=slot),
        outcome('y1', diagonal((1 - accuracy, accuracy)), elapsed=elapsed, value=1, slot=slot)]}


def idle_kernel(name='idle', *, n=2, elapsed=SECOND, completion=True, value=None):
    return {'id': name, 'outcomes': [outcome('done', diagonal([1] * n), elapsed=elapsed,
                                          completion=completion, value=value)]}


def execute(node, kernel, outcomes, next_node='end'):
    return {'id': node, 'kind': 'execute', 'kernel': kernel,
            'next': {name: next_node for name in outcomes}}


def policy(name, kernel, *, loop=False):
    return {'id': name, 'entry': 'run', 'nodes': [
        execute('run', kernel['id'], [o['id'] for o in kernel['outcomes']], 'run' if loop else 'end'),
        *([] if loop else [{'id': 'end', 'kind': 'end'}])]}


def finite_world(case_id, variant='default'):
    """Construct declared probability tables, without invoking any sui evaluator."""
    if case_id in ('FA11', 'FA12', 'FA13'):
        arrive = F(1, 4) if case_id == 'FA12' else F(3, 4)
        states = [{'id': f'x{x}-{phase}', 'target': f'x{x}'}
                  for x in (0, 1) for phase in ('pending', 'never', 'done')]
        mats = {key: [[F(0) for _ in states] for _ in states]
                for key in ('y0', 'y1', 'later')}
        for x in (0, 1):
            p, never, done = (3*x, 3*x+1, 3*x+2)
            mats[f'y{x}'][done][p] = F(1, 2)
            mats['later'][p][p] = F(1, 2)
            mats['later'][never][never] = mats['later'][done][done] = F(1)
        w = {'id': 'wait', 'outcomes': [
            outcome('y0', mats['y0'], value=0), outcome('y1', mats['y1'], value=1),
            outcome('later', mats['later'], completion=False)]}
        a = {'id': 'ask', 'outcomes': [
            outcome('y0', diagonal([F(1, 2)]*3 + [0]*3), elapsed=0, value=0),
            outcome('y1', diagonal([0]*3 + [F(1, 2)]*3), elapsed=0, value=1),
            outcome('none', diagonal([F(1, 2)]*6), elapsed=0)]}
        actions = (action('W', 'wait', never=True), action('A', 'ask'))
        wp = {'id': 'W', 'entry': 'run', 'nodes': [
            {'id': 'run', 'kind': 'execute', 'kernel': 'wait',
             'next': {'y0': 'end', 'y1': 'end', 'later': 'run'}}, {'id': 'end', 'kind': 'end'}]}
        return declaration([w, a], actions, [wp, policy('A', a)], states=states,
                           initial=[arrive/2, (1-arrive)/2, 0]*2), actions

    if case_id in ('FA02', 'FA03'):
        opened = {'id': 'open', 'outcomes': [
            outcome('none', diagonal((F(1, 2), F(1, 8))), value='no_arrival', kind='coverage'),
            outcome('arrived', diagonal((F(1, 2), F(7, 8))), value='arrival')]}
        closed = {'id': 'closed', 'outcomes': [
            outcome('done', diagonal((1, 1)), value='closed', kind='coverage')]}
        # §3-10-13-4: a real closed-coverage emission, never invent a record from null.
        actions = (action('Open', 'open'), action('Closed', 'closed'))
        d = declaration([opened, closed], actions, [policy('Open', opened), policy('Closed', closed)])
        if case_id == 'FA03':
            # One target, two persistent law hypotheses; joint order is law-a, law-b.
            d['targets'] = ['x']
            d['states'] = [{'id': 'law-a', 'target': 'x'}, {'id': 'law-b', 'target': 'x'}]
        return d, actions

    if case_id == 'FA04':
        m, q = bit_kernel('measure', F(3, 4)), idle_kernel('quiet')
        actions = (action('M', 'measure'), action('Q', 'quiet'))
        children = (action('M2', 'measure', path_action='M'), action('Q2', 'quiet', path_action='Q'))
        policies = []
        for op, kernel in zip(actions, (m, q)):
            nodes = [execute('first', kernel['id'], [o['id'] for o in kernel['outcomes']], 'choose'),
                     {'id': 'choose', 'kind': 'choose', 'operations': ['M2', 'Q2'],
                      'rule': plain(fc.SOFT_CHOICE), 'next': {'M2': 'end', 'Q2': 'end'}},
                     {'id': 'end', 'kind': 'end'}]
            policies.append({'id': op.id, 'entry': 'first', 'nodes': nodes})
        if variant in ('after_M_y0', 'after_Q'):
            policies = [policy('M', m), policy('Q', q)]
        prior = [F(3, 4), F(1, 4)] if variant == 'after_M_y0' else [F(1, 2)]*2
        return declaration([m, q], actions + children,
                           policies + [policy('M2', m), policy('Q2', q)], initial=prior), actions

    if case_id == 'FA06':
        compute = idle_kernel('compute', elapsed=0)
        # Reveal alone is specified (spec:414); no invented computation JSON.
        compute['outcomes'][0]['available'] = {'reveal': ['m'], 'computation': None}
        actions = (action('Compute', 'compute'),)
        return declaration([compute, bit_kernel('measure', F(3, 4))], actions,
                           [policy('Compute', compute)]), actions

    if case_id == 'FA14':
        q, m = idle_kernel('quiet', completion=False), bit_kernel('measure')
        actions = (action('Q', 'quiet', never=True), action('M', 'measure'))
        return declaration([q, m], actions, [policy('Q', q, loop=True), policy('M', m)]), actions

    if case_id == 'FA15':
        count = 100 if variant == 'hundred' else 1
        kernels = [bit_kernel(f'm{i}', slot=f'm{i}') for i in range(count)]
        actions = (action('M', 'm0'),)
        nodes = [execute(f'n{i}', k['id'], ['y0', 'y1'],
                         'end' if i+1 == count else f'n{i+1}') for i, k in enumerate(kernels)]
        return declaration(kernels, actions, [{'id': 'M', 'entry': 'n0',
                           'nodes': nodes + [{'id': 'end', 'kind': 'end'}]}]), actions

    if case_id == 'FA16' and variant in ('composite', 'split'):
        w, m = idle_kernel('wait'), bit_kernel('measure', elapsed=0)
        ops = tuple(action(name, kernel, policy_name, path_action=path,
                           opportunity=opportunity)
            for name, kernel, policy_name, path, opportunity in (
                ('W', 'wait', 'pW', 'W', {'fixture': 'FA16', 'physical_step': 'wait'}),
                ('M', 'measure', 'pM', 'M', {'fixture': 'FA16', 'physical_step': 'measure'}),
                ('C', 'wait', 'pC', None, {'fixture': 'FA16', 'wrapper': 'wait_then_measure'})))
        def call(node, operation, next_node):
            return {'id': node, 'kind': 'choose', 'operations': [operation],
                    'rule': plain(fc.SOFT_CHOICE), 'next': {operation: next_node}}
        policies = [
            {'id': 'pW', 'entry': 'wait', 'nodes': [
                execute('wait', 'wait', ['done'], 'w_finished'), {'id': 'w_finished', 'kind': 'end'}]},
            {'id': 'pM', 'entry': 'measure', 'nodes': [
                execute('measure', 'measure', ['y0', 'y1'], 'm_finished'), {'id': 'm_finished', 'kind': 'end'}]},
            {'id': 'pC', 'entry': 'callW', 'nodes': [
                call('callW', 'W', 'callM'), call('callM', 'M', 'c_finished'),
                {'id': 'c_finished', 'kind': 'end'}]},
            {'id': 'afterW', 'entry': 'callM', 'nodes': [
                call('callM', 'M', 'all_finished'), {'id': 'all_finished', 'kind': 'end'}]}]
        doc = declaration([w, m], ops, policies)
        doc['certificate_capabilities'] = plain(tuple(ContractRef(name, '1') for name in (
            'finite_option_proof', 'finite_tree', 'static_target_entropy_bound', 'finite_terminal_cost')))
        return doc, (ops[2] if variant == 'composite' else ops[0],)

    accuracy = F(3, 4) if case_id == 'FA05' else F(1)
    delay = 2*SECOND if case_id == 'FA16' and variant == 'at_2' else SECOND
    m, q = bit_kernel('measure', accuracy, elapsed=delay), idle_kernel('quiet', elapsed=0)
    if case_id in ('FA10', 'FA21'):
        q = idle_kernel('quiet', elapsed=0, value='constant')
    if case_id in ('FA07', 'FA21'):
        q = idle_kernel('quiet', elapsed=SECOND, value='constant')
    if case_id in ('FA08', 'FA09', 'FA19'):
        m = idle_kernel('measure', elapsed=0)
    actions = (action('Q', 'quiet'), action('M', 'measure'))
    if case_id in ('FA07', 'FA21'):
        actions = tuple(reversed(actions))
    d = declaration([q, m], actions, [policy('Q', q), policy('M', m)])
    return d, actions


def first_action_item():
    return {'kind': 'item', 'rule': {'name': 'table', 'version': '1'},
            'args': {'feature': {'name': 'started_actions', 'version': '1'},
                     'probs': [[['M'], 0.75], [['Q'], 0.25]]}}


def limit_document(*, both=False, proof='valid'):
    process = {'name': 'iid_fair_bits', 'version': '1', 'args': {'index_origin': 0}}
    zero = {'op': 'rational', 'value': [0, 1]}
    ln2 = {'op': 'log', 'arg': {'op': 'rational', 'value': [2, 1]}}
    # §3-10-13-7: direct canonical process only, independently hashed with hashlib.
    check = {'name': 'iid_bits_limit' if proof != 'missing_checker' else 'uninstalled_limit',
             'version': '1', 'args': {'process_digest': digest(process),
                'information_slope': zero if proof == 'tampered' else ln2,
                'cost_slope': ln2 if both else zero}}
    return {'process': process, 'observations': {'name': 'reveal_next_bit', 'version': '1', 'args': {}},
        'information_target': 'entire_sequence',
        'cost': {'kind': 'prefix_log_loss', 'law': process} if both else {'kind': 'blank'},
        'scope': {'name': 'unbounded_total', 'version': '1', 'H_ns': None},
        'proof': None if proof == 'none' else check}


def mixed_measure():
    return f.CandidateMeasureRef(name='mixed', version='1', args={'atoms': [{'id': 'now', 'mass': [1, 1]}],
        'continuous': [{'id': 'later', 'variable': 'delay', 'unit': 'second',
            'distribution': {'name': 'uniform_interval', 'version': '1',
                             'args': {'lower': [0, 1], 'upper': [2, 1]}},
            'mass': [1, 1], 'prediction': plain(f.KernelRef(name='finite_kernel', version='1', args={'id': 'quiet'}))}]})


class Reader:
    """Public FReader adapter; no heads, append, caches or declared availability."""
    __slots__ = ('_ledger',)
    def __init__(self, ledger): self._ledger = ledger
    def entry(self, cid): return self._ledger.entry(cid)
    def entries(self): return self._ledger.entries()
    def record(self, cid): return self._ledger.record(cid)
    def ancestors(self, frontier): return self._ledger.ancestors(frontier)
    def sealed_content(self, cid): return self._ledger.contents.get(self._ledger.entry(cid).seal)


class FactsCase:
    def __init__(self, document, *, name='finite', clock_contract=CLOCK):
        self.document = deepcopy(document)
        self.clock = FakeClock(run=Ref(RefKind.RUN,'facts-'+name.lower()))
        self.ids = SequentialIds(prefix='facts-'+name.lower())
        self.ledger = Ledger(salts=SequentialSalts(), contents=MemoryContents())
        self.reader = Reader(self.ledger)
        self.points = {}; self.raw = []; self.bindings = []; self.plans = []; self.measurements = []
        self.preferences = []; self.computation = {}; self.scope = f.EvaluationScope(
            name='unbounded_total',version='1',H_ns=None,source=None)
        self.put('boot',Observed(route='membrane',content=Payload.json({}),contract=BOOT,received_ns=0))
        source = ClockSource(run=self.clock.run,provider='test.facts',implementation='FakeClock',
            python_version='3.12.10',resolution_s=F(1,SECOND),monotonic=True,adjustable=False,
            measurement=clock_contract)
        self.observe('clock_source',SOURCE,source.as_json())
        self.predict('model',fc.MODEL_SOURCE,f.FModelSource(document=self.document))
        self.observe('origin',fc.KNOWLEDGE_ORIGIN,f.KnowledgeOrigin(model=self.points['model']))

    def ref(self, point): return self.ledger.record(point).id

    def put(self, key, body, *, parents=None):
        kind = {Observed:RefKind.OBSERVATION,Decided:RefKind.DECISION,Prediction:RefKind.PREDICTION,
                Preference:RefKind.PREFERENCE,JobOpened:RefKind.JOB,AttemptStarted:RefKind.ATTEMPT}[type(body)]
        record = Record(id=self.ids.new(kind),at=self.clock.now(),
            writer=Role.MEMBRANE if isinstance(body,(Observed,AttemptStarted)) else Role.MODEL,
            producer=PRODUCER,body=body)
        entry = self.ledger.append(record,self.ledger.heads() if parents is None else parents)
        self.points[key] = entry.cid
        return entry.cid

    def observe(self,key,contract,value,*,caused_by=None,route='membrane',source_id=None,source_time_ns=None):
        return self.put(key,Observed(route=route,content=Payload.json(plain(value)),contract=contract,
            received_ns=self.clock.mono_ns(),caused_by=caused_by,source_id=source_id,source_time_ns=source_time_ns))

    def predict(self,key,contract,value,*,basis=(),about=()):
        return self.put(key,Prediction(target=key,about=tuple(self.ref(x) for x in about),
            basis=tuple(self.ref(x) for x in basis),content=Payload.json(plain(value)),contract=contract))

    def decide(self,key,contract,value,*,inputs):
        return self.put(key,Decided(inputs=tuple(self.ref(x) for x in inputs),
                                   content=Payload.json(plain(value)),contract=contract))

    def reading(self,key,time_ns=None):
        return self.observe(key,fc.CLOCK_READING,f.FClockReadingFact(source=self.points['clock_source'],
            reading=f.ClockReading(run=self.clock.run,time_ns=self.clock.mono_ns() if time_ns is None else time_ns)))

    def context(self,*,events=(),observed_ns=None,judgment_ns=None,save_delay_ns=17):
        self.reading('observed_clock',observed_ns)
        self.reading('judgment_clock',judgment_ns)
        value = f.FContextObserved(knowledge_origin=self.points['origin'],
            observation_reading=self.points['observed_clock'],judgment_reading=self.points['judgment_clock'],
            check_events=tuple(f.FContextCheckEvent(kind=k,record=p) for k,p in events))
        # The management record is saved after the actual reading; never the source of now_ns.
        self.clock.advance(save_delay_ns)
        self.observe('context',fc.CONTEXT_OBSERVED,value)
        self.fixed_parents = tuple(sorted(self.ledger.heads()))
        return self.points['context']

    def candidate(self,order,*,measure=None,after=None,generator=GENERATOR,args=None,draws=()):
        self.candidate_value = f.FCandidateDeclaration(model=self.points['model'],input_order=tuple(order),
            measure=measure,generation=f.FCandidateGeneration(generator=generator,args={} if args is None else args,
                basis=(self.points['model'],),draws=tuple(draws)),
            continuation=f.FContinuation(after=tuple(f.ContinuationAfter(candidate=n,
                policy=None if after is None else f.PolicyRef(name='finite_policy',version='1',args={'id':after})) for n in order)))
        return self.predict('candidates',fc.CANDIDATE_DECLARATION,self.candidate_value,basis=(self.points['model'],)+tuple(draws))

    def preference(self,value,contract=LEGACY_PREFERENCE):
        point = self.put('preference-'+str(len(self.preferences)),Preference(basis=(),content=Payload.json(plain(value)),contract=contract))
        self.preferences.append(point); return point

    def style(self,*,H=None,name=None):
        scope_name = name or ('unbounded_total' if H is None else 'finite_horizon')
        point = self.preference({'kind':'style','scope':{'name':scope_name,'version':'1','H_ns':H},'gamma':[1,1]},fc.STYLE)
        self.scope = f.EvaluationScope(name=scope_name,version='1',H_ns=H,source=self.ref(point))

    def acquire(self,contents,*,clock=None):
        # §今の約束 A-09〜A-11: the acquisition clock is read at the acquisition,
        # not borrowed from an earlier judgment reading.
        n=str(len(self.ledger.entries()))
        if clock is None:
            clock=self.reading('acquisition-clock-'+n)
        return self.observe('acquisition-'+n,fc.CONTENT_ACQUIRED,
            f.ContentAcquired(origin=self.points['origin'],contents=tuple(contents),clock=clock))


def add_observations(case,seqs=(1,),*,closed=False,route_effective_unavailable=False):
    coverage = any(k['id']=='open' for k in case.document['kernels'])
    kernel_id = ('closed' if closed else 'open') if coverage else 'measure'
    kernel = next(k for k in case.document['kernels'] if k['id']==kernel_id)
    route = f.RouteConfig(route_epoch='route-1',origin='bootstrap',version='1',sampling_contract=MEASURING,
        clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),args={},decision=None,execution=None)
    case.observe('route',fc.ROUTE_CONFIG,{'config':plain(route),
        'effective_from':({'kind':'unavailable','value':plain(f.Unavailable(reason='clock_unavailable',basis=()))}
            if route_effective_unavailable else
            {'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=case.clock.mono_ns()))}),
        'execution':None,'evidence':[]})
    groups = {}
    for item in kernel['outcomes']:
        if item['evidence'] is not None:
            e=item['evidence'];groups.setdefault(canonical({'kind':e['kind'],'value':e['value']}),[]).append(item['id'])
    cells=tuple(f.ObservationCell(id=f'cell-{i}',observation=f.ObservationValue(**json.loads(key)),outcomes=tuple(names))
                for i,(key,names) in enumerate(groups.items()))
    plan=f.ObservationPlan(model_ref=digest(case.document),route_epoch='route-1',measurement_contract=MEASURING,
        kernel=f.KernelRef(name='finite_kernel',version='1',args={'id':kernel_id}),cells=cells,
        time_projection=TIME_PROJECTION,generation_contract=GENERATION)
    plan_point=case.predict('plan',fc.OBSERVATION_PLAN,plan,basis=(case.points['model'],));case.plans.append(plan_point)
    opportunities={}
    for delivery,seq in enumerate(seqs):
        if seq not in opportunities:
            request=case.decide(f'measure-request-{seq}',fc.MEASUREMENT_REQUESTED,
                f.MeasurementRequested(plan=plan_point,step=0),inputs=(plan_point,))
            job=case.put(f'measure-job-{seq}',JobOpened(decision=case.ref(request),step=0,
                content=Payload.json(plain(f.MeasurementJob(plan=plan_point,step=0))),contract=fc.MEASUREMENT_JOB))
            attempt=case.put(f'measure-attempt-{seq}',AttemptStarted(job=case.ref(job),content=Payload.json({}),
                contract=ContractRef('sui.s1.attempt','1')))
            opportunities[seq]=attempt
        opportunity=opportunities[seq]
        case.clock.advance(max(0,seq*SECOND-case.clock.mono_ns()))
        mid=f.MeasurementId(origin=case.clock.run,route_epoch='route-1',sample_seq=seq,component='value')
        interval=f.MeasurementInterval(clock=case.clock.run,start_ns=(seq-1)*SECOND,end_ns=seq*SECOND,closure='(start,end]')
        value=('closed' if closed else 'no_arrival') if coverage else 0
        if coverage:
            payload={'kind':'claim','value':plain(f.CoverageClaim(route_epoch='route-1',interval=interval,kind=value,
                                                                contract=MEASURING,evidence=(case.ref(opportunity),)))}
            contract=fc.COVERAGE
        else:
            payload=plain(f.MeasurementFrame(route_epoch='route-1',sample_seq=seq,measurement_id=mid,
                measurement_interval=interval,actual_time=f.ClockReading(run=case.clock.run,time_ns=seq*SECOND),
                value=value,quality=f.ContractValue(contract=QUALITY,value='measured'),gap=None,
                source_cursor=f.ContractValue(contract=CURSOR,value=seq)))
            contract=fc.MEASUREMENT
        raw=case.observe(f'raw-{delivery}',contract,payload,caused_by=case.ref(opportunity),route='route-1',source_id=f'delivery-{delivery}')
        cell=next(c for c in cells if c.observation.value==value)
        binding=f.ObservationBinding(plan=case.ref(plan_point),records=(case.ref(raw),),opportunity=case.ref(opportunity),
            step=0,cell=cell.id,slots=() if coverage else (f.ObservationSlot(slot='m',measurement=mid),),
            generated_by=(case.ref(opportunity),),derived_from=())
        bp=case.observe(f'binding-{delivery}',fc.OBSERVATION_BINDING,binding,caused_by=case.ref(opportunity))
        case.raw.append(raw);case.bindings.append(bp)
        if not coverage:case.measurements.append(mid)


def add_computation(case,*,stage='adopted',tampered=False,joint=(F(3,4),F(1,4)),mass=F(1,2),omit_input=None,extra_inputs=(),completion_received_ns=None):
    started=case.reading('computation-start')
    finished=case.reading('computation-finish')
    # The complete original evidence/generation closure is explicit, never an E/K table.
    input_points=tuple(dict.fromkeys((case.points['origin'],case.points['model'],case.points['boot'],case.points['clock_source'],case.points['route'],
        *case.plans,*case.raw,*case.bindings,*extra_inputs,
        *(p for key,p in case.points.items() if key.startswith(('measure-request','measure-job','measure-attempt'))))))
    if omit_input is not None:
        assert omit_input in input_points
        input_points=tuple(p for p in input_points if p!=omit_input)
    args=f.FiniteUpdateArgs(model=case.points['model'],previous_result=None,observations=tuple(case.bindings))
    request=case.decide('compute-request',fc.COMPUTATION_REQUESTED,
        f.ComputationRequested(origin=case.points['origin'],purpose='belief',method=fc.FINITE_UPDATE,args=plain(args),
            inputs=input_points,algorithm_draws=(),output_contract=fc.FINITE_UPDATE_RESULT),inputs=input_points)
    result=case.predict('compute-result',fc.COMPUTATION_RESULT,
        f.ComputationResult(request=request,output=f.ContractValue(contract=fc.FINITE_UPDATE_RESULT,
            value=plain(f.FiniteUpdateResult(joint=tuple(joint),evidence_mass=mass)))),basis=(request,)+input_points,about=(request,))
    statement=f.FiniteUpdateStatement(model=case.points['model'],request=request,result=result)
    if tampered: statement=replace(statement,result=case.points['model'])
    proof=case.predict('compute-proof',fc.COMPUTATION_PROOF,
        f.ComputationProof(request=request,result=result,role='normalization',
            statement=f.ContractValue(contract=fc.FINITE_UPDATE_STATEMENT,value=plain(statement)),
            checker=f.ProofRef(name=fc.FINITE_UPDATE_REPLAY.name,version='1',args={})),
        basis=(request,result,case.points['model']),about=(request,result))
    completed=case.put('compute-completed',Observed(route='membrane',contract=fc.COMPUTATION_COMPLETED,
        received_ns=case.clock.mono_ns() if completion_received_ns is None else completion_received_ns,
        content=Payload.json(plain(f.ComputationCompleted(request=request,result=result,proofs=(proof,),
            started_clock=started,finished_clock=finished)))))
    case.computation.update(request=request,result=result,proof=proof,completed=completed)
    if stage in ('acquired','adopted'):
        # §3-10-17-3: the acquisition clock is read after the generation finished
        # (g <= a.clock.reading); an earlier judgment reading would predate it.
        case.acquire((result,proof),clock=case.reading('computation-acquired'))
    if stage=='adopted':
        adopted=case.decide('adopted',fc.KNOWLEDGE_ADOPTED,
            f.KnowledgeAdopted(origin=case.points['origin'],previous=None,completion=completed),
            inputs=(case.points['origin'],completed))
        case.computation['adopted']=adopted


def assemble(case_id='FA08',variant='default',*,H=None,scope_name=None,document=None,order=None):
    doc,actions=finite_world(case_id,variant)
    if document is not None:doc=deepcopy(document)
    if case_id=='FA14':
        doc['operations'][0]['termination']=plain(predicate(False))
    if order is None:order=[x.id for x in actions]
    if case_id=='FA08' and variant in ('alias-first','alias-last','alias-only','unsupported'):
        alias=deepcopy(doc['operations'][0]);alias['id']='Q-display'
        if variant=='unsupported':alias['proof']['name']='unregistered-proof'
        doc['operations'].append(alias)
        order=({'alias-first':['Q-display','Q','M'],'alias-last':['Q','M','Q-display'],
                'alias-only':['Q-display','M'],'unsupported':['Q','M','Q-display']})[variant]
    case=FactsCase(doc,name=case_id)
    if case_id in ('FA02','FA03','FA05','FA06','FA07','FA18'):
        seqs=(1,2) if case_id=='FA03' or case_id=='FA05' and variant=='independent' else ((1,1) if case_id=='FA05' else (1,))
        add_observations(case,seqs,closed=variant=='closed')
    if case_id=='FA07' and H is None:H=0
    if case_id=='FA21' and scope_name is None:scope_name='one_step'
    if H is not None or scope_name is not None:case.style(H=H,name=scope_name)
    if case_id=='FA04' and variant=='nonzero':case.preference(FIXED['FA04_nonzero_path_cost']['preference_item'])
    if case_id=='FA07' and variant=='first_action_cost':case.preference(first_action_item())
    case.candidate(order,measure=mixed_measure() if case_id=='FA09' else None,
        after='afterW' if case_id=='FA16' and variant=='split' else None)
    case.context()
    return case


K_STAGES=('raw','acquired','computed-unacquired','computed-acquired','adopted','tampered-proof','legacy-missing')


def assemble_knowledge(stage):
    case=assemble('FA06')
    if stage!='raw' and stage!='legacy-missing':
        case.acquire(case.raw)
    if stage in ('computed-unacquired','computed-acquired','adopted','tampered-proof'):
        add_computation(case,stage={'computed-unacquired':'unacquired','computed-acquired':'acquired'}.get(stage,'adopted'),
                        tampered=stage=='tampered-proof')
    if stage!='raw':case.context()
    if stage=='legacy-missing':
        missing=case.points['origin']
        case.reader=MissingBodyReader(case.ledger,missing)
    return case


class MissingBodyReader(Reader):
    def __init__(self,ledger,missing):super().__init__(ledger);self.missing=missing
    def record(self,cid):
        if cid==self.missing:raise KeyError(cid)
        return super().record(cid)
    def sealed_content(self,cid):
        if cid==self.missing:raise KeyError(cid)
        return super().sealed_content(cid)


def add_draw(case,problem_key,*,u=F(1,2),purpose='selection',ordinal=0,parents=None):
    value=f.FDrawFact(generator=ContractRef('sui.f.scripted_draw','1'),stream_id='facts-'+purpose,
        request=f.DrawRequest(purpose=purpose,context_key=problem_key,ordinal=ordinal,
            law=ContractRef('uniform_unit','1'),args={}),value={'u':plain(u)})
    return case.put('draw-'+str(len(case.ledger.entries())),Observed(route='draw',content=Payload.json(plain(value)),
        contract=fc.DRAW_FACT,received_ns=case.clock.mono_ns()),parents=parents)


def prepare(case,*,registry=None,budget=BUDGET):
    return ff.prepare_f_from_facts(case.reader,fixed_parents=case.fixed_parents,model_ref=case.points['model'],
        candidate_ref=case.points['candidates'],preference_refs=tuple(case.preferences),scope_request=case.scope,
        context_ref=case.points['context'],registry=f.builtin_f_registry() if registry is None else registry,method=METHOD,budget=budget)


def histories(case,*,registry=None,budget=BUDGET):
    return ff.read_f_histories_from_facts(case.reader,fixed_parents=case.fixed_parents,model_ref=case.points['model'],
        context_ref=case.points['context'],registry=f.builtin_f_registry() if registry is None else registry,budget=budget)


def bound(case,*,u=F(1,2),budget=BUDGET):
    prepared=prepare(case,budget=budget)
    assert isinstance(prepared.value,f.FProblem), 'mathematical success cannot be weakened to NoDecision'
    draw=add_draw(case,prepared.value.problem_key,u=u)
    root=ff.bind_f_draw(prepared,draw,reader=case.reader,budget=budget)
    assert isinstance(root.value,f.FRoot)
    return prepared,draw,root


class BareFactsCase(FactsCase):
    # A limit declaration has no finite model, knowledge origin or synthetic root.
    def __init__(self):
        self.clock=FakeClock(run=Ref(RefKind.RUN,'facts-limit'))
        self.ids=SequentialIds(prefix='facts-limit')
        self.ledger=Ledger(salts=SequentialSalts(),contents=MemoryContents())
        self.reader=Reader(self.ledger);self.points={}


def assemble_limit(*,both=False,proof='valid'):
    case=BareFactsCase()
    case.predict('limit',fc.LIMIT_DECLARATION,limit_document(both=both,proof=proof))
    return case


def assemble_c1(variant='10',*,label='y0',bad=None,midwindow=False,delay=0,context_delay_ns=17,read_delivery=0):
    doc=json.loads(Path(__file__).with_name('s4b2_c1_declaration.json').read_bytes())
    case=FactsCase(doc,name='C1',clock_contract=ContractRef('exact','1'))
    def report(experiment,count,outcome=None):
        end=SECOND if experiment=='root-window' else 2*SECOND
        return {'channel':'root-report' if experiment=='root-window' else 'read-report','experiment':experiment,
            'window_start_ns':end-SECOND,'window_end_ns':end,'completion_ns':end,
            'arrival_count':{'kind':'exact','value':count},'outcome':outcome}
    case.clock.advance(SECOND)
    case.observe('root-report',ContractRef('sui.s4b.rate_report','1'),report('root-window',int(variant[0])),
                 route='c1',source_id='c1-root',source_time_ns=SECOND)
    # A real Decided exists; no dangling fixture-input ID and no Selected is fabricated.
    request=case.decide('read-request',ContractRef('fixture.c1.request','1'),{'action':'read'},inputs=(case.points['model'],))
    read=next(x for x in doc['controls']['choices'] if x['id']=='read')
    value={'choice':'read','action':'read','reservation_rule':read['reservation'],
        'execution':{'family':{'name':'immediate-start','version':'1'},'completion_process':'read-done',
            'start':{'time':[1,1],'causal_stage':0,'causal_position':0}},'effect':'identity'}
    job=case.put('read-job',JobOpened(decision=case.ref(request),step=0,content=Payload.json(value),contract=ContractRef('sui.s4b.rate_job','1')))
    attempt=case.put('read-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),contract=ContractRef('sui.s1.attempt','1')))
    case.clock.advance(SECOND//2 if midwindow else SECOND+delay)
    if not midwindow:
        value=report('read',int(variant[1]),label)
        if bad=='saturated':value['arrival_count']={'kind':'at_least','value':3}
        if bad=='gap':value['window_start_ns']+=SECOND//2
        # Alternate delivery IDs retain the exact same physical generation and body.
        for _ in range(read_delivery):case.ids.new(RefKind.OBSERVATION)
        case.observe('read-report',ContractRef('sui.s4b.rate_report','1'),value,route='c1',
            source_id='c1-read',source_time_ns=2*SECOND,caused_by=case.ref(attempt))
    case.context(save_delay_ns=context_delay_ns)
    return case


def assemble_legacy_bridge(*,pending=False,nonzero=False):
    """FA21 primary old model; never build Reading, Resolved, or a finite root."""
    import numpy as np
    from sui.model import GenerativeModel, model_json
    perfect=np.array([[1.,0.],[0.,1.],[0.,0.]])
    quiet=np.array([[0.,0.],[0.,0.],[1.,1.]])
    model=GenerativeModel(states=('x0','x1'),outcomes=('y0','y1','constant'),
        actions=('M','Q','P') if pending else ('M','Q'),
        a={'M':perfect,'Q':quiet,**({'P':perfect.copy()} if pending else {})},learnable=frozenset(),
        D=np.array([.5,.5]),log_C=np.log(np.array([1/3]*3)),gamma=1.,
        durations={name:((1.,1.),) for name in (('M','Q','P') if pending else ('M','Q'))},
        measures={name:'report' for name in (('M','Q','P') if pending else ('M','Q'))})
    case=FactsCase(json.loads(model_json(model)),name='legacy')
    if pending:
        from sui.s1_contracts import ACTION,ATTEMPT
        request=case.decide('P-request',ContractRef('fixture.legacy.request','1'),{'action':'P'},inputs=(case.points['model'],))
        job=case.put('P-job',JobOpened(decision=case.ref(request),step=0,content=Payload.json({'action':'P'}),contract=ACTION))
        case.put('P-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),contract=ATTEMPT))
        if nonzero:case.preference(first_action_item())
        case.preference({'kind':'style','H_ns':0,'gamma':1.0})
        case.clock.advance(SECOND)
    case.context(observed_ns=0,judgment_ns=SECOND if pending else 0)
    return case,model


def assemble_legacy_bridge_quadrant(*,received,pending):
    """FA21 without pending P; FA07 with pending P; received Q adds a real report."""
    import numpy as np
    from sui.model import GenerativeModel,model_json
    from sui.s1_contracts import ACTION,ATTEMPT,OUTCOME
    perfect=np.array([[1.,0.],[0.,1.],[0.,0.]])
    quiet=np.array([[0.,0.],[0.,0.],[1.,1.]])
    names=('M','Q','P') if pending else ('M','Q')
    model=GenerativeModel(states=('x0','x1'),outcomes=('y0','y1','constant'),
        actions=names,a={'M':perfect,'Q':quiet,**({'P':perfect.copy()} if pending else {})},learnable=frozenset(),
        D=np.array([.5,.5]),log_C=np.log(np.array([1/3]*3)),gamma=1.,
        durations={name:((1.,1.),) for name in names},
        measures={name:'report' for name in names})
    case=FactsCase(json.loads(model_json(model)),name='legacy-quadrants')
    def start(name):
        request=case.decide(name+'-request',ContractRef('fixture.legacy.request','1'),{'action':name},inputs=(case.points['model'],))
        job=case.put(name+'-job',JobOpened(decision=case.ref(request),step=0,content=Payload.json({'action':name}),contract=ACTION))
        return case.put(name+'-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),contract=ATTEMPT))
    if received:attempt=start('Q')
    if pending:start('P')
    if received or pending:case.clock.advance(SECOND)
    if received:case.observe('Q-report',OUTCOME,{'outcome':'constant'},route='executor',caused_by=case.ref(attempt))
    if pending:
        case.preference(first_action_item())
        case.preference({'kind':'style','H_ns':0,'gamma':1.0})
    # FA21 uses white preferences and the current reading; FA07 marginalizes pending O0.
    case.context(observed_ns=0 if pending else case.clock.mono_ns(),judgment_ns=case.clock.mono_ns())
    return case,model


def prepare_bridge(case,*,registry=None):
    return ff.prepare_legacy_bridge_from_facts(case.reader,fixed_parents=case.fixed_parents,
        model_ref=case.points['model'],context_ref=case.points['context'],
        preference_refs=tuple(case.preferences),candidates=('M','Q'),
        adapter=ContractRef('sui.f.legacy_bridge','2'),
        registry=f.builtin_f_registry() if registry is None else registry,budget=BUDGET)


def auth_copy_primary(case, *, edit=None, parent_edit=None):
    """Copy primary records through public Ledger.append, recomputing every seal.

    Added for the independent 2026-10-11 authentication tests. ``edit`` receives
    (fixture key, Record), after earlier Point references have been remapped.
    It must return a Record. Ref identities are retained. No derived histories,
    implementation cache or authenticated handles are copied or manufactured.
    The source fixture and all existing fixture helpers retain their meaning.
    """
    from copy import copy
    result = copy(case)
    result.ledger = Ledger(salts=SequentialSalts(), contents=MemoryContents())
    result.reader = Reader(result.ledger)
    point_map = {}
    names = {point: name for name, point in case.points.items()}

    def remap(value):
        if isinstance(value, str):
            return point_map.get(value, value)
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, tuple):
            return tuple(remap(v) for v in value)
        return value

    pending = {entry.cid: entry for entry in case.ledger.entries()}
    while pending:
        ready = [entry for entry in pending.values()
                 if all(p in point_map for p in entry.parents)]
        if not ready:
            raise ValueError('source fixture has cyclic or missing primary parents')
        # Append order has no authentication authority. Preserve source sequence.
        ready.sort(key=lambda entry: (case.ledger.record(entry.cid).at.seq, entry.cid))
        for entry in ready:
            old = case.ledger.record(entry.cid)
            body = replace(old.body, content=Payload.json(remap(old.body.content.as_json())))
            record = replace(old, body=body)
            key = names.get(entry.cid, str(old.id))
            if edit is not None:
                record = edit(key, record)
            parents = frozenset(point_map[p] for p in entry.parents)
            if parent_edit is not None:
                parents = frozenset(parent_edit(key, parents, point_map))
            new = result.ledger.append(record, parents)
            point_map[entry.cid] = new.cid
            del pending[entry.cid]
    for attr in ('points', 'raw', 'bindings', 'plans', 'preferences', 'computation', 'fixed_parents'):
        if hasattr(case, attr):
            setattr(result, attr, remap(getattr(case, attr)))
    result.auth_point_map = point_map
    return result


def review5_timed_case(event):
    """Primary events at a known boundary, with earlier prerequisites for isolation."""
    case=FactsCase(finite_world('FA06')[0],name='review5-'+event)
    add_observations(case)
    if event=='adoption':
        case.reading('judgment_clock');case.acquire(case.raw)
        add_computation(case,stage='acquired')
    if event!='measurement':case.clock.advance(1)
    if event=='acquisition':
        case.reading('judgment_clock');case.acquire(case.raw)
    elif event=='adoption':
        case.decide('adopted',fc.KNOWLEDGE_ADOPTED,
            f.KnowledgeAdopted(origin=case.points['origin'],previous=None,completion=case.computation['completed']),
            inputs=(case.points['origin'],case.computation['completed']))
    case.candidate(('Compute',))
    case.context(observed_ns=case.clock.mono_ns(),judgment_ns=case.clock.mono_ns())
    return case


def review5_adoption_case(*,late_acquisition=False,inputs='correct'):
    """Only acquisition/adoption order or outer inputs differ; all bodies are real."""
    case=assemble_knowledge('computed-unacquired')
    required=(case.computation['result'],case.computation['proof'],*case.raw)
    if not late_acquisition:
        case.reading('judgment_clock');case.acquire(required)
    refs=(case.points['origin'],case.computation['completed'])
    if inputs=='empty':refs=()
    elif inputs=='missing-completion':refs=refs[:1]
    elif inputs=='wrong-point':refs=(case.points['origin'],case.points['model'])
    case.decide('adopted',fc.KNOWLEDGE_ADOPTED,
        f.KnowledgeAdopted(origin=case.points['origin'],previous=None,completion=case.computation['completed']),inputs=refs)
    if late_acquisition:
        case.clock.advance(SECOND);case.reading('judgment_clock');case.acquire(required)
    case.context()
    return case


def review5_pending_cost_case(*,pending):
    """GF-M13: real received evidence and a declared P, optionally in progress."""
    from sui.s1_contracts import ACTION,ATTEMPT
    doc,_=finite_world('FA07')
    doc['operations'].append(plain(action('P','measure')))
    doc['policies'].append(policy('P',bit_kernel('measure')))
    case=FactsCase(doc,name='review5-cost')
    if pending:
        request=case.decide('P-request',ContractRef('fixture.f.request','1'),{'action':'P'},inputs=(case.points['model'],))
        job=case.put('P-job',JobOpened(decision=case.ref(request),step=0,content=Payload.json({'action':'P'}),contract=ACTION))
        case.put('P-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),contract=ATTEMPT))
    add_observations(case)
    case.style(H=0);case.preference(first_action_item());case.candidate(('M','Q'));case.context()
    return case


def review5_generation_case(*,fault=None,source_time_ns=None,document=None,adopted=True):
    """R08/R09: one primary generation chain; no invariant-table imports.

    Request/job at 0; attempt exactly at the 1s measurement; receipt at 1s+1ns.
    Faults change one semantic field, retaining required redundant encodings.
    The spare 1ns before receipt isolates an attempt 1ns after the measurement.
    """
    case=FactsCase(finite_world('FA06')[0] if document is None else document,name='generation')
    route=f.RouteConfig(route_epoch='route-1',origin='bootstrap',version='1',sampling_contract=MEASURING,
        clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),args={},decision=None,execution=None)
    case.observe('route',fc.ROUTE_CONFIG,{'config':plain(route),
        'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=0))},
        'execution':None,'evidence':[]})
    cells=tuple(f.ObservationCell(id='cell-'+str(i),observation=f.ObservationValue(kind='measurement',value=i),
                                 outcomes=('y'+str(i),)) for i in (0,1))
    plan=f.ObservationPlan(model_ref=digest(case.document),route_epoch='route-1',measurement_contract=MEASURING,
        kernel=f.KernelRef(name='finite_kernel',version='1',args={'id':'measure'}),cells=cells,
        time_projection=TIME_PROJECTION,generation_contract=GENERATION)
    plan_point=case.predict('plan',fc.OBSERVATION_PLAN,plan,basis=(case.points['model'],))
    case.plans.append(plan_point)
    request_plan=case.points['model'] if fault=='request-plan' else plan_point
    request=case.decide('measure-request-1',fc.MEASUREMENT_REQUESTED,
        f.MeasurementRequested(plan=request_plan,step=1 if fault=='request-step' else 0),
        inputs=() if fault=='request-inputs' else (request_plan,))
    job_step=1 if fault=='job-step' else 0
    job=case.put('measure-job-1',JobOpened(decision=case.ref(request),
        step=1 if fault=='job-header-step' else job_step,
        content=Payload.json(plain(f.MeasurementJob(
            plan=case.points['model'] if fault=='job-plan' else plan_point,step=job_step))),contract=fc.MEASUREMENT_JOB))
    case.clock.advance(SECOND+(1 if fault=='attempt-after-measurement' else 0))
    attempt=case.put('measure-attempt-1',AttemptStarted(job=case.ref(job),content=Payload.json({}),
        contract=ContractRef('sui.s1.attempt','1')))
    case.clock.advance(SECOND+1-case.clock.mono_ns())
    mid=f.MeasurementId(origin=case.clock.run,route_epoch='route-1',sample_seq=1,component='value')
    frame=f.MeasurementFrame(route_epoch='route-1',sample_seq=1,measurement_id=mid,
        measurement_interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,end_ns=SECOND,closure='(start,end]'),
        actual_time=f.ClockReading(run=case.clock.run,time_ns=SECOND+2 if fault=='measurement-after-receipt' else SECOND),
        value=0,quality=f.ContractValue(contract=QUALITY,value='measured'),gap=None,
        source_cursor=f.ContractValue(contract=CURSOR,value=1))
    raw=case.put('raw-0',Observed(route='route-1',contract=fc.MEASUREMENT,content=Payload.json(plain(frame)),
        caused_by=case.ref(attempt),source_id='delivery-0',source_time_ns=source_time_ns,
        received_ns=SECOND+2 if fault=='receipt-after-record' else SECOND+1))
    binding=f.ObservationBinding(plan=case.ref(case.points['model'] if fault=='binding-plan' else plan_point),
        records=(case.ref(raw),),opportunity=case.ref(attempt),step=1 if fault=='binding-step' else 0,
        cell='cell-0',slots=(f.ObservationSlot(slot='m',measurement=mid),),generated_by=(case.ref(attempt),),derived_from=())
    bound_point=case.observe('binding-0',fc.OBSERVATION_BINDING,binding,caused_by=case.ref(attempt))
    case.raw.append(raw);case.bindings.append(bound_point);case.measurements.append(mid)
    if adopted:
        case.reading('judgment_clock');case.acquire(case.raw);add_computation(case)
    case.candidate(('Compute',));case.context()
    return case


def review5_table_coverage_case(*,generated_after_end=False):
    """Coverage has a window end but no measured instant: isolate T07."""
    case=FactsCase(finite_world('FA02')[0],name='table-coverage')
    observe=case.observe
    extra=[]
    def with_extra_generation(key,contract,value,**kwargs):
        if key=='raw-0':
            plan=case.plans[0]
            request=case.decide('measure-request-2',fc.MEASUREMENT_REQUESTED,
                f.MeasurementRequested(plan=plan,step=0),inputs=(plan,))
            job=case.put('measure-job-2',JobOpened(decision=case.ref(request),step=0,
                content=Payload.json(plain(f.MeasurementJob(plan=plan,step=0))),contract=fc.MEASUREMENT_JOB))
            case.clock.advance(1 if generated_after_end else 0)
            extra.append(case.put('measure-attempt-2',AttemptStarted(job=case.ref(job),content=Payload.json({}),
                contract=ContractRef('sui.s1.attempt','1'))))
            case.clock.advance(SECOND+2-case.clock.mono_ns())
        elif key=='binding-0':
            value=replace(value,generated_by=(*value.generated_by,case.ref(extra[0])))
        return observe(key,contract,value,**kwargs)
    case.observe=with_extra_generation
    add_observations(case)
    case.observe=observe
    case.candidate(('Open','Closed'));case.context()
    return case


def review5_table_case(*,measured_ns=SECOND,end_ns=SECOND+2,
        opportunity_ns=SECOND,generated_ns=SECOND,job_ns=0,
        request_plan='same',job_plan='same',generated_plan='same',generated_step=0,
        binding_plan='same',binding_step=0,unknown_run=False,extra_input=False,
        acquire_extra=False,extra_request_plan=None,acquired_only=False,initial_case=None,
        standalone_measured_ns=None,binding_cause_missing=False):
    """Two real generators, distinct valid Plan CIDs and optional extra evidence.

    Only primary records are assembled. Parameters change one semantic edge;
    redundant step encodings in a request/Job are kept mutually consistent.
    A measurement's instant and window end are deliberately independent.
    """
    case=FactsCase(finite_world('FA06')[0],name='table-edges') if initial_case is None else initial_case
    route=f.RouteConfig(route_epoch='route-1',origin='bootstrap',version='1',sampling_contract=MEASURING,
        clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),args={},decision=None,execution=None)
    case.observe('route',fc.ROUTE_CONFIG,{'config':plain(route),
        'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=0))},
        'execution':None,'evidence':[]})
    cells=tuple(f.ObservationCell(id='cell-'+str(i),observation=f.ObservationValue(kind='measurement',value=i),
        outcomes=('y'+str(i),)) for i in (0,1))
    plan=f.ObservationPlan(model_ref=digest(case.document),route_epoch='route-1',measurement_contract=MEASURING,
        kernel=f.KernelRef(name='finite_kernel',version='1',args={'id':'measure'}),cells=cells,
        time_projection=TIME_PROJECTION,generation_contract=GENERATION)
    plans={key:case.predict('plan-'+key,fc.OBSERVATION_PLAN,plan,basis=(case.points['model'],))
           for key in ('same','other')}
    plans['model']=case.points['model']
    case.plans.extend((plans['same'],plans['other']))

    def put_at(key,body,time_ns,*,foreign=False):
        # Public Record/Ledger allow authentic saved facts with contradictory
        # cross-record chronology; F, not a forged reader, must reject them.
        kind={Observed:RefKind.OBSERVATION,JobOpened:RefKind.JOB,AttemptStarted:RefKind.ATTEMPT}[type(body)]
        at=replace(case.clock.now(),mono_ns=time_ns,
            run=Ref(RefKind.RUN,'foreign-table') if foreign else case.clock.run)
        record=Record(id=case.ids.new(kind),at=at,writer=Role.MODEL if isinstance(body,JobOpened) else Role.MEMBRANE,
            producer=PRODUCER,body=body)
        point=case.ledger.append(record,case.ledger.heads()).cid
        case.points[key]=point
        return point

    # 2026-10-12 (今の約束 A-05): every request/Job first, then the Attempts.
    # The old order made Attempt 1 (1s) the actual parent of request 2 (0s),
    # an unintended parent->child clock reversal in every control.
    attempts=[];jobs=[]
    specs=((request_plan,job_plan,0,opportunity_ns),(generated_plan,generated_plan,generated_step,generated_ns))
    for index,(req_plan,used_plan,step,started) in enumerate(specs,1):
        request=case.decide('measure-request-'+str(index),fc.MEASUREMENT_REQUESTED,
            f.MeasurementRequested(plan=plans[req_plan],step=step),inputs=(plans[req_plan],))
        jobs.append(put_at('measure-job-'+str(index),JobOpened(decision=case.ref(request),step=step,
            content=Payload.json(plain(f.MeasurementJob(plan=plans[used_plan],step=step))),contract=fc.MEASUREMENT_JOB),
            job_ns if index==1 else 0))
    for index,(job,(_,_,_,started)) in enumerate(zip(jobs,specs),1):
        attempts.append(put_at('measure-attempt-'+str(index),AttemptStarted(job=case.ref(job),
            content=Payload.json({}),contract=ContractRef('sui.s1.attempt','1')),started))
    receipt=max(SECOND+3,measured_ns,end_ns,opportunity_ns,generated_ns,job_ns)
    case.clock.advance(receipt)
    mid=f.MeasurementId(origin=case.clock.run,route_epoch='route-1',sample_seq=1,component='value')
    raw=case.observe('raw-0',fc.MEASUREMENT,f.MeasurementFrame(route_epoch='route-1',sample_seq=1,measurement_id=mid,
        measurement_interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,end_ns=end_ns,closure='(start,end]'),
        actual_time=f.ClockReading(run=case.clock.run,time_ns=measured_ns),value=0,
        quality=f.ContractValue(contract=QUALITY,value='measured'),gap=None,
        source_cursor=f.ContractValue(contract=CURSOR,value=1)),caused_by=case.ref(attempts[0]),route='route-1')
    binding=case.observe('binding-0',fc.OBSERVATION_BINDING,f.ObservationBinding(
        plan=case.ref(plans[binding_plan]),records=(case.ref(raw),),opportunity=case.ref(attempts[0]),step=binding_step,
        cell='cell-0',slots=(f.ObservationSlot(slot='m',measurement=mid),),
        generated_by=tuple(case.ref(p) for p in attempts),derived_from=()),
        caused_by=None if binding_cause_missing else case.ref(attempts[0]))
    case.raw.append(raw);case.bindings.append(binding);case.measurements.append(mid)
    extras=()
    if extra_input or acquired_only:
        if 'extra-evidence' in case.points:
            extras=tuple(case.points[key] for key in ('extra-evidence','source-request','source-job','source-attempt'))
        else:
            extras=(put_at('extra-evidence',Observed(route='membrane',contract=ContractRef('fixture.f.extra_evidence','1'),
                content=Payload.json({'value':7}),received_ns=receipt),receipt,foreign=unknown_run),)
    if extra_request_plan is not None:
        extras=(*extras,case.decide('extra-request',fc.MEASUREMENT_REQUESTED,
            f.MeasurementRequested(plan=plans[extra_request_plan],step=0),inputs=(plans[extra_request_plan],)))
    case.reading('judgment_clock');case.acquire((*case.raw,*(extras if acquire_extra else ())))
    if standalone_measured_ns is not None:
        # T02: an additional input Frame has no Binding. Its cause and window
        # stay fixed; only measured changes across the chronology boundary.
        attempt_record=Record(id=case.ids.new(RefKind.ATTEMPT),
            at=replace(case.clock.now(),mono_ns=SECOND+1),writer=Role.MEMBRANE,producer=PRODUCER,
            body=AttemptStarted(job=case.ref(case.points['measure-job-2']),content=Payload.json({}),
                contract=ContractRef('sui.s1.attempt','1')))
        # 2026-10-12 (今の約束 A-05): its actual parent is Job 2, not the later
        # heads saved after SECOND+3; that was an unintended clock reversal.
        spare_attempt=case.ledger.append(attempt_record,frozenset({case.points['measure-job-2']})).cid
        case.points['standalone-attempt']=spare_attempt
        value=case.ledger.record(raw).body.content.as_json()
        value['measurement_interval']['end_ns']=SECOND+2
        value['actual_time']['value']['time_ns']=standalone_measured_ns
        value['sample_seq']=2;value['measurement_id']['sample_seq']=2;value['source_cursor']['value']=2
        spare=case.observe('standalone-frame',fc.MEASUREMENT,value,route='route-1',
            caused_by=case.ref(spare_attempt))
        extras=(*extras,spare_attempt,spare)
    add_computation(case,extra_inputs=() if acquired_only else extras)
    case.candidate(('Compute',));case.context()
    return case


def review5_structural_branch_case(branch,*,foreign=False):
    """T25 acquired-only / T27 source provenance then numeric input.

    The only positive/negative difference is the extra Observed's run. All
    clocks, causal records, authenticated Points and input lists are real.
    No internal validator/cache is imported, preseeded or directly called.
    """
    if branch=='T25':
        return review5_table_case(acquired_only=True,acquire_extra=True,unknown_run=foreign)
    assert branch=='T27'

    class SourceEvidenceCase(FactsCase):
        def observe(self,key,contract,value,**kwargs):
            if key=='clock_source':
                at=self.clock.now()
                if foreign:at=replace(at,run=Ref(RefKind.RUN,'foreign-table'))
                record=Record(id=self.ids.new(RefKind.OBSERVATION),at=at,writer=Role.MEMBRANE,producer=PRODUCER,
                    body=Observed(route='membrane',contract=ContractRef('fixture.f.extra_evidence','1'),
                        content=Payload.json({'value':7}),received_ns=at.mono_ns))
                extra=self.ledger.append(record,self.ledger.heads()).cid
                self.points['extra-evidence']=extra
                request=self.decide('source-request',ContractRef('fixture.f.source_request','1'),
                    {'purpose':'clock-source'},inputs=(extra,))
                job=self.put('source-job',JobOpened(decision=self.ref(request),step=0,
                    content=Payload.json({'purpose':'clock-source'}),contract=ContractRef('fixture.f.source_job','1')))
                attempt=self.put('source-attempt',AttemptStarted(job=self.ref(job),content=Payload.json({}),
                    contract=ContractRef('sui.s1.attempt','1')))
                kwargs['caused_by']=self.ref(attempt)
            return super().observe(key,contract,value,**kwargs)

    case=SourceEvidenceCase(finite_world('FA06')[0],name='table-edges')
    return review5_table_case(initial_case=case,extra_input=True)


def review5_prior_context_case(*,reversed_by_ns=0):
    """T22: only a clock-source causal request refers to the prior context."""
    case=review5_table_case();now=case.clock.mono_ns()
    prior=case.context(observed_ns=now,judgment_ns=now-reversed_by_ns)
    case.points.update(prior_context=prior,prior_observed=case.points['observed_clock'],
        prior_judgment=case.points['judgment_clock'])
    request=case.decide('provenance-request',ContractRef('fixture.f.provenance_request','1'),{},
        inputs=(case.bindings[0],case.computation['adopted'],prior))
    job=case.put('provenance-job',JobOpened(decision=case.ref(request),step=0,
        content=Payload.json({}),contract=ContractRef('fixture.f.provenance_job','1')))
    attempt=case.put('provenance-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),
        contract=ContractRef('sui.s1.attempt','1')))
    value=case.ledger.record(case.points['clock_source']).body.content.as_json()
    case.points['clock_source']=case.observe('provenance-source',SOURCE,value,caused_by=case.ref(attempt))
    case.context(events=(('fact',case.bindings[0]),('fact',case.computation['adopted'])))
    return case


def review5_cause(case,inputs=(),*,foreign_job=False):
    """Real Decided/Job/Attempt chain; only the Job side's run can differ."""
    request_body=Decided(inputs=tuple(case.ref(p) for p in inputs),content=Payload.json({}),
        contract=ContractRef('fixture.f.draw_request','1'))
    def put(key,body,kind):
        if not foreign_job:return case.put(key,body)
        record=Record(id=case.ids.new(kind),at=replace(case.clock.now(),run=Ref(RefKind.RUN,'draw-foreign-job')),
            writer=Role.MODEL,producer=PRODUCER,body=body)
        point=case.ledger.append(record,case.ledger.heads()).cid;case.points[key]=point
        return point
    request=put('draw-cause-request',request_body,RefKind.DECISION)
    job=put('draw-cause-job',JobOpened(decision=case.ref(request),step=0,content=Payload.json({}),
        contract=ContractRef('fixture.f.draw_job','1')),RefKind.JOB)
    return case.put('draw-cause-attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),
        contract=ContractRef('sui.s1.attempt','1')))


def review5_closure_primary_case(kind,*,bad=False):
    if kind=='R16':return review5_table_case(binding_cause_missing=bad)
    case=assemble('FA08')
    case.clock.advance((2 if kind.startswith('R14') else 1)*SECOND-case.clock.mono_ns())
    if kind.startswith('R14'):
        event_kind=kind.split('-')[1];moment=2*SECOND if bad else SECOND
        checked=case.reading('prior-check',moment) if event_kind=='clock' else case.put('prior-check',
            Observed(route='membrane',received_ns=moment,content=Payload.json({}),
                contract=ContractRef('fixture.f.prior_fact','1')))
        prior=case.context(events=((event_kind,checked),),observed_ns=SECOND,judgment_ns=SECOND,save_delay_ns=0)
        case.points['prior-context']=prior
        attempt=review5_cause(case,(prior,))
    else:
        assert kind=='R15';attempt=review5_cause(case)
    source=case.put('new-source',Observed(route='membrane',received_ns=0 if kind=='R15' and bad else case.clock.mono_ns(),
        caused_by=case.ref(attempt),content=case.ledger.record(case.points['clock_source']).body.content,contract=SOURCE))
    case.points['clock_source']=source;case.context(save_delay_ns=0)
    return case


def review5_foreign_history(case,*,share_origin=False):
    """Copy an independently recorded history using public Record/Point refs."""
    foreign=FactsCase(case.document,name='post-draw-foreign')
    add_observations(foreign);foreign.candidate(('Compute',));foreign.context()
    foreign.acquire(foreign.raw);add_computation(foreign)
    mapped={foreign.points[k]:case.points[k] for k in ('model','origin')} if share_origin else {}
    ids={foreign.ref(foreign.points[k]):case.ref(case.points[k]) for k in ('model','origin')} if share_origin else {}
    def remap(value):
        if isinstance(value,str):return mapped.get(value,'route-post-foreign' if value=='route-1' else value)
        if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list):return [remap(v) for v in value]
        return value
    for entry in sorted(foreign.ledger.entries(),key=lambda e:foreign.ledger.record(e.cid).at.seq):
        if entry.cid in mapped:continue
        record=foreign.ledger.record(entry.cid);body=record.body
        changes={name:tuple(ids.get(ref,ref) for ref in getattr(body,name))
                 for name in ('about','basis','inputs') if hasattr(body,name)}
        record=replace(record,body=replace(body,**changes,content=Payload.json(remap(body.content.as_json()))))
        mapped[entry.cid]=case.ledger.append(record,case.ledger.heads()).cid
    return {k:mapped[v] for k,v in foreign.computation.items()},mapped[foreign.points['origin']]


def review5_causal_draw(case,prepared,attempt):
    value=f.FDrawFact(generator=ContractRef('sui.f.scripted_draw','1'),stream_id='facts-selection',
        request=f.DrawRequest(purpose='selection',context_key=prepared.value.problem_key,ordinal=0,
            law=ContractRef('uniform_unit','1'),args={}),value={'u':[1,4]})
    return case.observe('closure-draw',fc.DRAW_FACT,value,route='draw',caused_by=case.ref(attempt))


def review5_closure_draw_case(edge,*,bad=False,actual_unavailable=False):
    """Prepare first; later facts authenticate only the draw, not E/K inputs."""
    case=assemble_knowledge('adopted') if edge in ('T20','T21') else assemble('FA08')
    prepared=prepare(case);assert isinstance(prepared.value,f.FProblem)
    case.clock.advance(2*SECOND+20-case.clock.mono_ns());inputs=()
    if edge in ('T20','T21'):
        foreign,origin=review5_foreign_history(case,share_origin=edge=='T21') if bad else (case.computation,case.points['origin'])
        previous=foreign['adopted'] if edge=='T21' else None
        completion=foreign['completed'] if edge=='T20' else case.computation['completed']
        origin=case.points['origin'] if edge=='T21' else origin
        inputs=tuple(p for p in (origin,previous,completion) if p is not None)
        adoption=case.decide('post-draw-adoption',fc.KNOWLEDGE_ADOPTED,
            f.KnowledgeAdopted(origin=origin,previous=previous,completion=completion),inputs=inputs)
        case.points['post-completion']=completion
        if previous is not None:case.points['post-previous']=previous
        inputs=(adoption,)
    if edge=='T23':
        source=case.points['clock_source']
        if bad:
            foreign=FactsCase(case.document,name='post-clock-foreign')
            for key in ('boot','clock_source'):
                point=case.ledger.append(foreign.ledger.record(foreign.points[key]),case.ledger.heads()).cid
                case.points['foreign-'+key]=point
            source=case.points['foreign-clock_source']
        inputs=(case.observe('post-reading',fc.CLOCK_READING,f.FClockReadingFact(source=source,
            reading=f.ClockReading(run=case.clock.run,time_ns=case.clock.mono_ns()))),)
    attempt=review5_cause(case,inputs,foreign_job=edge=='T01' and bad)
    if edge=='T03':
        case.points['post-measure-attempt']=attempt
        route=f.RouteConfig(route_epoch='route-post',origin='bootstrap',version='1',sampling_contract=MEASURING,
            clock_contract=CLOCK,loss_contract=ContractRef('fixture.f.lossless','1'),args={},decision=None,execution=None)
        case.observe('post-route',fc.ROUTE_CONFIG,{'config':plain(route),
            'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,time_ns=0))},
            'execution':None,'evidence':[]})
        raw=case.observe('post-raw',fc.MEASUREMENT,f.MeasurementFrame(route_epoch='route-post',sample_seq=1,
            measurement_id=f.MeasurementId(origin=case.clock.run,route_epoch='route-post',sample_seq=1,component='value'),
            measurement_interval=f.MeasurementInterval(clock=case.clock.run,start_ns=0,
                end_ns=SECOND+2 if bad else case.clock.mono_ns(),closure='(start,end]'),
            actual_time=(f.Unavailable(reason='clock_unavailable',basis=()) if actual_unavailable
                else f.ClockReading(run=case.clock.run,time_ns=case.clock.mono_ns())),value=0,
            quality=f.ContractValue(contract=QUALITY,value='measured'),gap=None,
            source_cursor=f.ContractValue(contract=CURSOR,value=1)),caused_by=case.ref(attempt),route='route-post')
        attempt=review5_cause(case,(raw,))
    return case,prepared,review5_causal_draw(case,prepared,attempt)


def review5_reference_acquisition_case(*,clock_ns=SECOND,received_ns=SECOND):
    """Acquisition saved late; event/read clocks can independently be stale."""
    case=assemble('FA06')
    clock=case.reading('reference-acquisition-clock',clock_ns)
    case.put('reference-acquisition',Observed(route='membrane',received_ns=received_ns,
        contract=fc.CONTENT_ACQUIRED,content=Payload.json(plain(f.ContentAcquired(
            origin=case.points['origin'],contents=tuple(case.raw),clock=clock)))))
    case.context(save_delay_ns=0)
    return case


def review5_reference_event_case(kind,*,bad=False):
    """Non-acquisition references with late storage; one event time changes."""
    case=assemble('FA06' if kind=='completion' else 'FA08')
    case.clock.advance(max(0,SECOND-case.clock.mono_ns()))
    if kind=='completion':
        case.acquire(case.raw)
        # All computation clocks are exactly now; completion's receipt alone
        # moves back. Result/proof are ordinary primary declarations.
        now=case.clock.mono_ns()
        add_computation(case,stage='unacquired',completion_received_ns=now-1 if bad else now)
        point=case.computation['completed'];dependency=case.points['computation-finish']
        case.context(save_delay_ns=0)
    elif kind=='context':
        observed=case.reading('reference-observed');judgment=case.reading('reference-judgment')
        value=f.FContextObserved(knowledge_origin=case.points['origin'],
            observation_reading=observed,judgment_reading=judgment,check_events=())
        case.clock.advance(17)
        point=case.put('context',Observed(route='membrane',received_ns=SECOND-1 if bad else SECOND,
            contract=fc.CONTEXT_OBSERVED,content=Payload.json(plain(value))))
        dependency=judgment;case.fixed_parents=tuple(sorted(case.ledger.heads()))
    else:
        assert kind=='route-evidence'
        dependency=case.observe('reference-route-evidence',ContractRef('fixture.f.route_evidence','1'),{'ready':True})
        config=f.RouteConfig(route_epoch='reference-unused',origin='bootstrap',version='1',
            sampling_contract=MEASURING,clock_contract=CLOCK,loss_contract=QUALITY,args={},decision=None,execution=None)
        case.clock.advance(17)
        point=case.put('reference-route',Observed(route='membrane',received_ns=SECOND,
            contract=fc.ROUTE_CONFIG,content=Payload.json({'config':plain(config),
                'effective_from':{'kind':'clock','value':plain(f.ClockReading(run=case.clock.run,
                    time_ns=SECOND-1 if bad else SECOND))},
                'execution':None,'evidence':[str(case.ref(dependency))]})))
        case.context(save_delay_ns=0)
    case.points.update(reference_owner=point,reference_dependency=dependency)
    return case


def review5_unavailable_route_case(*,used=False,unknown=False):
    if used:
        document,actions=finite_world('FA06');case=FactsCase(document,name='FA06')
        add_observations(case,route_effective_unavailable=unknown)
        case.candidate(tuple(x.id for x in actions));case.context()
        point=case.points['route']
    else:
        case=assemble('FA08')
        config=f.RouteConfig(route_epoch='unused-route',origin='bootstrap',version='1',
            sampling_contract=MEASURING,clock_contract=CLOCK,loss_contract=QUALITY,args={},decision=None,execution=None)
        point=case.observe('unused-route',fc.ROUTE_CONFIG,{'config':plain(config),
            'effective_from':{'kind':'unavailable' if unknown else 'clock',
                'value':plain(f.Unavailable(reason='clock_unavailable',basis=()) if unknown
                    else f.ClockReading(run=case.clock.run,time_ns=0))},'execution':None,'evidence':[]})
        case.context(save_delay_ns=0)
    case.points['reference_route']=point
    return case


def review5_first_unknown_observed(*,bad=False):
    """Authentic four-record closure; nonce 0 makes the observation first by CID."""
    case=BareFactsCase();case.clock.advance(SECOND)
    request=case.decide('request',ContractRef('fixture.probe.request','1'),{},inputs=())
    job=case.put('job',JobOpened(decision=case.ref(request),step=0,content=Payload.json({}),
        contract=ContractRef('fixture.probe.job','1')))
    attempt=case.put('attempt',AttemptStarted(job=case.ref(job),content=Payload.json({}),
        contract=ContractRef('sui.s1.attempt','1')))
    point=case.put('isolated',Observed(route='membrane',contract=ContractRef('fixture.probe.unknown','1'),
        content=Payload.json({'nonce':0}),caused_by=case.ref(attempt),received_ns=0 if bad else SECOND),
        parents=(attempt,))
    return case,point


def review5_candidate_nonancestor_basis():
    """A declaration Point is a derived leaf, not a causal parent."""
    case=assemble('FA08')
    basis=case.predict('basis-constant',fc.QUANTITY_DECLARATION,
        f.FQuantityConstantDeclaration(kind='rational_constant',value=F(1),unit='dimensionless',provenance=()))
    declaration=replace(case.candidate_value,generation=replace(case.candidate_value.generation,basis=(basis,)))
    # 今の約束 A-04: the outer basis contains every generation.basis Point.
    owner=case.predict('outside-basis-candidate',fc.CANDIDATE_DECLARATION,declaration,basis=(case.points['model'],basis))
    return case,owner,basis


def review5_closure_route_case(path,*,bad=False):
    """Identical bad Point before choosing any of the five reachability paths."""
    case=assemble('FA08');prepared=prepare(case)
    case.clock.advance(SECOND-case.clock.mono_ns());attempt=review5_cause(case)
    point=case.put('route-evidence',Observed(route='membrane',received_ns=SECOND-1 if bad else SECOND,
        caused_by=case.ref(attempt),content=Payload.json({'value':7}),contract=ContractRef('fixture.f.route_evidence','1')))
    if path=='draw':
        attempt=review5_cause(case,(point,));draw=review5_causal_draw(case,prepared,attempt)
        return case,prepared,point,draw
    if path=='clock':
        attempt=review5_cause(case,(point,))
        case.points['clock_source']=case.observe('route-source',SOURCE,
            case.ledger.record(case.points['clock_source']).body.content.as_json(),caused_by=case.ref(attempt))
    if path=='past-context':
        prior=case.context(events=(('fact',point),),save_delay_ns=0);case.points['route-prior']=prior
        attempt=review5_cause(case,(prior,))
        case.points['clock_source']=case.observe('route-source',SOURCE,
            case.ledger.record(case.points['clock_source']).body.content.as_json(),caused_by=case.ref(attempt))
    if path!='preflight':
        case.context(save_delay_ns=0)
        if path=='prepare':case.fixed_parents=tuple(sorted((*case.fixed_parents,point)))
    return case,prepared,point,None


class Review5ContextCase(FactsCase):
    """R11-R13: provenance-only FA08, or one authentic wrong-kind payload.

    No E/K, internal invariant rows or validator caches are constructed.
    Record payload JSON is preserved when its public body kind/Role is changed.
    """
    def __init__(self,*,scenario='ordinary',foreign=False,wrong_kind=None):
        self.scenario=scenario;self.foreign=foreign;self.wrong_kind=wrong_kind
        self.foreign_run=Ref(RefKind.RUN,'context-foreign')
        super().__init__(finite_world('FA08')[0],name='context-review')
        self.candidate(('Q','M'));self.context()

    def put(self,key,body,*,parents=None):
        if key=='clock_source' and self.scenario in ('R11','T01'):
            inputs=()
            if self.scenario=='R11':
                extra=self.observe('source-extra',ContractRef('fixture.f.extra_evidence','1'),{'value':7})
                inputs=(extra,)
            request=self.decide('source-request',ContractRef('fixture.f.source_request','1'),
                {'purpose':'clock-source'},inputs=inputs)
            job=self.put('source-job',JobOpened(decision=self.ref(request),step=0,
                content=Payload.json({'purpose':'clock-source'}),contract=ContractRef('fixture.f.source_job','1')))
            attempt=self.put('source-attempt',AttemptStarted(job=self.ref(job),content=Payload.json({}),
                contract=ContractRef('sui.s1.attempt','1')))
            body=replace(body,caused_by=self.ref(attempt))
        if key=='clock_source' and self.scenario=='T23' and self.foreign:
            value=body.content.as_json();value['run']=str(self.foreign_run)
            body=replace(body,content=Payload.json(value))
        if key==self.wrong_kind or self.wrong_kind=='draw' and key.startswith('draw-'):
            if isinstance(body,Observed):
                body=Prediction(target=key,about=(),basis=(),content=body.content,contract=body.contract)
            else:
                assert isinstance(body,Prediction)
                body=Observed(route='membrane',content=body.content,contract=body.contract,
                    received_ns=self.clock.mono_ns())
        foreign_keys={'R11':('source-extra',),'T01':('source-request','source-job'),
                      'T23':('boot','clock_source')}.get(self.scenario,())
        if self.foreign and key in foreign_keys:
            kind={Observed:RefKind.OBSERVATION,Decided:RefKind.DECISION,JobOpened:RefKind.JOB}[type(body)]
            record=Record(id=self.ids.new(kind),at=replace(self.clock.now(),run=self.foreign_run),
                writer=Role.MEMBRANE if isinstance(body,Observed) else Role.MODEL,producer=PRODUCER,body=body)
            point=self.ledger.append(record,self.ledger.heads() if parents is None else parents).cid
            self.points[key]=point
            return point
        return super().put(key,body,parents=parents)


# ---
# date: 2026-10-09
# project: sui
# tool: codex
# tags: [session, sui, gate-f, facts, dry-run]
# ---
# Session log: F-a B+C v0.13 original-record dry run. [[Projects/sui]]
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3 (environment confirmed).
# No Claude dialogue was sent. Other-agent reports were information, not approval.
# Artifacts: C:/Users/you11/Desktop/iku/sui/tests/gate_f_facts_cases.py and
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_facts.py (v0.13, uncommitted).
# Read: specs/関所F_いつ動くか.md 3-10-15-1..4 and 3-10-16-1..16 in full;
# remaining 3-10-15 mapping tables not fully read. fixed_gate_f.json items read;
# old gate_f test declarations/recipes/oracles read in the relevant portions only.
# Public F DTO/signature/docstring inspection used AST filtering; A1 read _f_eval
# imports only. ClockSource location search accidentally returned clock_contracts.py
# lines 58/71 of its body; those lines were not used as a fixture or numerical oracle.
# No evaluator/private function body supplied an expectation. External Web: none.
# 実施済み: primary B/D/T/P/U/A/C/O records via Record/Payload/Ledger.append.
# No E/K, semantic_key, aliases, resolved, manifest, FRoot or Selected is built by
# positive fixtures. Model FUTURE outcome.available is a primary declaration.
# Prediction is never a parent. Preference is a permitted causal category, not FACT.
# MeasurementRequested/MeasurementJob point to an actual Decided and AttemptStarted.
# Stage K: raw, acquired, computed-unacquired, computed-acquired, adopted,
# tampered-proof, legacy-origin-missing. Full finite-update input closure is explicit.
# B+C stop conditions: preflight issuance/historical image cannot be exercised;
# FA18 quantity Point -> PredicateRef QuantityRef binding is not specified;
# FA21 actual old-model bridge still requires derived View/Resolved inputs.
# Additional gaps: limit Point -> FMathArtifact issuance missing; finite update APIs
# annotate FModel only, while new declarations are unrelated FModel11 DTOs.
# 仮に決めた: a predicate record uses PREDICATE and direct PredicateRef payload;
# QuantityRef.key is the quantity declaration Point. This addresses source facts
# without a fake root; BC-G03 stays open until that interpretation is specified.
# 仮に決めた: fixture.f.bit_order/1 uses one generation u to choose Q/M vs M/Q
# input order. It reuses the public generator capability wire contract and checks
# compiler inputs; it creates no semantic keys/aliases. Separate selection U is used.
# 仮に決めた: C1 also writes KnowledgeOrigin because ContextObserved requires it;
# finite_update.inputs includes origin/model/raw/Plan/Binding and generation/clock
# provenance. Exact compiler acceptance is unverified until the body exists.
# K.pending stage.required Point membership/order is unspecified; tests check real
# request provenance and absence/presence, not an invented exact dependency digest.
# Verification command:
# .venv/Scripts/python -B -m pytest -q -p no:cacheprovider tests/test_gate_f_facts.py
# PYTEST_ADDOPTS=--tb=line; PYTHONDONTWRITEBYTECODE=1; 180-second process ceiling.
# Final: 66 passed / NotImplementedError('F-a reshape') 123 / other 10;
# pytest: 133 failed, 66 passed in 2.86s, exit 1. No skip/xfail.
# The 66 passes comprise 63 original-record/DTO assembly cases and A1/A3/oracle checks.
# Other failures individually:
# 1 limit False-valid: no Point-based issuance, expected information_divergent.
# 2 limit True-valid: no Point-based issuance, expected undefined_infinite_difference.
# 3 limit True-none: no issuance for missing proof / certificate_incomplete.
# 4 limit True-missing_checker: no issuance for unavailable checker / certificate_incomplete.
# 5 FA18 quantity Point binding: declaration-to-predicate mapping unspecified.
# 6 FA21 bridge: public API requires View/Resolved instead of primary facts.
# 7 preflight then-view: no public FPreflightFacts factory to capture the image.
# 8 preflight current-capability-only: same missing factory prevents separate replay test.
# 9 preflight lost-then-view: same missing factory prevents unavailable-image test.
# 10 FA02 model11: public finite-update signatures still accept only FModel.
# Limits: NotImplementedError stops most tests before their numerical/replay assertions;
# those assertions, cached-only guarantees, full canonical axes, and A2/A4/A5 runtime
# paths are NOT verified. A1 is an import check, not a proof of all dynamic dependencies.
# Existing successes retain fixed mathematical oracles, never certificate_incomplete.
# C9 uses +ln2 cost from an actual Preference; its Z factor is the inverse of the
# fixed z_shift_property -ln2 example, with the same independent factor two.
# 再利用した知見と結果: [[Knowledge/失敗の再検証では不足していた依存を足さない]]
# read in full; old snapshot-exclusion recipe is out of scope after v0.13 replaces it
# with the real historical reader/registry image. No old snapshot was fabricated.
# ハマった点: lowercase Ref labels, public ContinuationAfter type, and Preference
# parent category fixed in fixtures. Windows subprocess required python.exe path.
# 未実行: old contract suite, all-repository tests, mutations, commit, implementation.
# 次: return BC-G01/02/03/05/06 to Claude/ゆう; specify missing public paths/types,
# then rerun this same command before treating B+C adoption or math as confirmed.
# Scope: only the two NEW facts test files were written. Existing contract/cases
# were unchanged. Vault Sessions/Projects/Knowledge/Heat not updated; local log only.


# ---
# date: 2026-10-09
# project: sui
# tool: codex
# tags: [session, sui, gate-f, facts, dry-run, v0.14]
# ---
# Continuation: B+C second dry run, v0.14. [[Projects/sui]]
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3.
# No messages sent to Claude; its reports were information, not authorization.
# Artifacts (implemented, uncommitted):
# C:/Users/you11/Desktop/iku/sui/tests/gate_f_facts_cases.py
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_facts.py
# Supersedes the v0.13 contract-gap conclusions above for the new public entries.
# Implemented: Reader.sealed_content; replace missing_entry gates with preflight,
# limit diagnosis/certification, quantity Point binding, old-model bridge, and
# finite update through got.model. Preserve V1 ops and check V2 additions.
# Added original-record negative cases: seal loss/tamper, preflight fixed parents
# versus absent required records, quantity Point/internal key/unit/foreign root,
# omitted Plan/Decided/JobOpened/AttemptStarted, C1 management FACT exclusion,
# bridge no append/clock/ID effects, explicit generator boundary and invalid laws.
# No new provisional contract chosen. The three former provisional fixtures now
# follow spec 5384-5439; compiler owns quantity keys and candidate semantics.
# Verification (executed):
# .venv/Scripts/python -B -m pytest -q -p no:cacheprovider tests/test_gate_f_facts.py
# PYTEST_ADDOPTS=--tb=line (avoid displaying implementation bodies), 180s cap.
# Final: 272 total; 72 passed; 200 NotImplementedError('F-a reshape'); other 0.
# pytest exit 1, elapsed 4.63s. Earlier run: 72 passed / 191 NI / other 0.
# Test-writing/dry-run completed; mathematical assertions after stubs NOT verified.
# A fixture-only inspection initially lacked src on sys.path; rerun with src/tests
# resolved import and confirmed fair initial distributions. No test expectation
# was weakened to accept certificate_incomplete; no xfail/skip introduced.
# Stop audit (§3-10-16-15): no remaining missing-entry/derived-fixture requirement
# identified by construction. This is NOT proof that all seven conditions are
# satisfied by the implementation: replay, math, canonicalization and cached-only
# behavior remain behind the stub. No user value decision newly identified.
# Read scope: spec v0.14 4914-5471 in full; related spec excerpts 1920-1972,
# 4080-4100, 4790-4835 and searched cross-references. Source: public signatures,
# annotations and docstrings extracted by AST; implementation bodies not read.
# Tests/helper relevant portions and fixed values read; no external web sources.
# Reused knowledge: Projects/sui current status and prior facts test/log.
# Applicable to entry migration; runtime conclusions remain unverified.
# Old tests/test_gate_f_contract.py not edited or run; no commit/mutant run.
# Old contract test SHA256 at completion:
# 6e3274c8fbfba32f0d5603e0a9e4444c06d250f57a3d8fd2bba8fb446eab7e0d
# Next: implement facts compiler, rerun these 272 cases, then inspect any concrete
# disagreement; do not replace mathematical successes by incomplete outcomes.
# Vault Session/Projects/Knowledge and Heat remain UNREFLECTED: the current task
# restricts writes to the facts test files. This comment is the local fallback
# session log, not a claim that Obsidian was updated.
