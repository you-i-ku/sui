"""Gate F v0.11: public declarations and raw records, never evaluator state.

Initial assembly: 2026-10-08 / Codex, session 01a1189b-a16c-7ab0-890c-af27713927c6.
Only gate_f_cases.py and test_gate_f_contract.py are authorized for writing;
Obsidian Sessions/Projects/Heat are NOT updated. Reused knowledge: discrimination
and content assertions (../CLAUDE.md:122-175); applied, functional results pending.
Sources: specs/関所F_いつ動くか.md sections 3-0 through 3-10 (relevant sections),
tools/gate_f_fixed_values.py (full), tests/fixed_gate_f.json (relevant entries
inspected; the complete file was mechanically compared with the independent script).
src was inspected only as public declarations/signatures/docstrings via AST.
No implementation dialogue, evaluator, or private state supplies an oracle.

P1--P7 were replaced by section 3-10-12: versioned finite_* references,
semantic-field digest, explicit intervals/union JSON, Plan/Binding and
choose.next as the return address AFTER the child operation finishes.
R1--R8 are replaced by section 3-10-13; full legacy golden checks belong to Claude.
Stub failures
do not establish that assertions beyond the first factory have been exercised.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path

from sui import f, f_contracts as fc, f_entry as fe, f_facts as ff, f_model as fm
from gate_f_facts_cases import (FactsCase as _FactsCase, assemble as _facts_assemble, prepare as _facts_prepare,
    histories as _facts_histories, add_draw as _facts_add_draw, add_computation as _facts_add_computation,
    finite_world as _facts_world)
from sui.clock import FakeClock
from sui.contracts import ContractRef
from sui.f_model import FModel
from sui.ids import Ref, RefKind, SequentialIds
from sui.ledger import Ledger, MemoryContents, SequentialSalts
from sui.preference import PreferenceView, current, resolve, from_ledger
from sui.rate import RateBudget
from sui.records import (Observed, Payload, Preference, Producer, Record, Role,
                         Prediction, JobOpened, AttemptStarted, Category)


SECOND = 10**9
FIXED_DOCUMENT = json.loads(Path(__file__).with_name('fixed_gate_f.json').read_bytes())
FIXED = FIXED_DOCUMENT['items']
IDS = tuple(f'FA{i:02}' for i in range(1, 22))
BUDGET = RateBudget(tolerance=F(1, 10**25), max_cells=4096,
                    max_terms=4096, max_refinements=32)
# Normative capability names: spec §3-10-13-3/4, not fixture-local resolvers.
GENERATOR = ContractRef('sui.f.explicit_candidates', '1')
METHOD = ContractRef('sui.f.finite_evaluation', '1')
CLOCK = ContractRef('sui.f.simulated_clock', '1')
MEASURING = ContractRef('sui.f.finite_measurement', '1')
QUALITY = ContractRef('sui.f.measured_quality', '1')
CURSOR = ContractRef('sui.f.sequence_cursor', '1')
STYLE = fc.STYLE
LEGACY_PREFERENCE = ContractRef('sui.s4d.preference', '1')
PRODUCER = Producer(component='fixture.gate_f', code_version='1')
TIME_PROJECTION = ContractRef('sui.f.value_only', '1')
GENERATION = ContractRef('sui.f.opportunity_step_slot', '1')


def plain(value):
    """Encode fixture declarations only; never use f_json as an expectation."""
    if isinstance(value, Ref):
        return str(value)
    if isinstance(value, F):
        return [value.numerator, value.denominator]
    if isinstance(value, f.ExactReal):
        return {field.name: plain(getattr(value, field.name)) for field in fields(value)
                if getattr(value, field.name) is not None}
    if isinstance(value, f.MeasurementFrame):
        out = {field.name: plain(getattr(value, field.name)) for field in fields(value)}
        out['value'] = {'kind': 'unavailable' if isinstance(value.value, f.Unavailable) else 'value',
                        'value': plain(value.value)}
        # §3-10-13-2: clock/unavailable, including JSON null for optional fields.
        out['actual_time'] = {'kind': 'unavailable' if isinstance(value.actual_time, f.Unavailable)
                              else 'clock', 'value': plain(value.actual_time)}
        return out
    if is_dataclass(value):
        out = {field.name: plain(getattr(value, field.name)) for field in fields(value)}
        # §3-10-12-2: an empty structured-key mapping still uses the entry array.
        # Other empty mappings (args, fact_ancestors, etc.) remain JSON objects.
        if isinstance(value, f.PredicateSnapshot) and not value.quantities:
            out['quantities'] = []
        return out
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            return [{'key': plain(key), 'value': plain(item)}
                    for key, item in sorted(value.items(), key=lambda p: canonical(p[0]))]
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((plain(item) for item in value), key=canonical)
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def canonical(value):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def predicate(value):
    return f.PredicateRef(name='constant', version='1', args={'value': value})


def action(name, kernel, policy=None, *, never=False, path_action='default',
           proof_name='finite_option_proof', opportunity=None):
    values = dict(family=f.ActionFamilyRef(name='finite_option', version='1'),
                  args={'opportunity': name if opportunity is None else opportunity, 'path_action': name if path_action == 'default' else path_action},
                  start=predicate(True),
                  policy=f.PolicyRef(name='finite_policy', version='1', args={'id': policy or name}),
                  termination=f.PredicateRef(name='policy_end', version='1', args={}),
                  termination_kind='may_never' if never else 'certain',
                  prediction=f.KernelRef(name='finite_kernel', version='1', args={'id': kernel}),
                  execution=ContractRef('sui.f.simulated_execution', '1'),
                  proof=f.ProofRef(name=proof_name, version='1', args={'operation': name}))
    semantics = {key: value for key, value in values.items() if key != 'proof'}
    return f.ActionSpec(id=name, semantic_key='sha256:' + sha256(canonical(semantics)).hexdigest(),
                        **values)


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


def declaration(kernels, actions, policies, *, states=None, targets=None, initial=None):
    return {'scheme': 'sui.model.10', 'contract': plain(fc.FINITE_MODEL),
            'units': {'record': 'ns', 'duration': 'ns', 'information': 'nat', 'cost': 'nat'},
            'targets': targets or ['x0', 'x1'],
            'states': states or [{'id': 's0', 'target': 'x0'}, {'id': 's1', 'target': 'x1'}],
            'initial': plain([F(x) for x in initial] if initial is not None else [F(1, 2), F(1, 2)]),
            'kernels': kernels, 'operations': plain(actions), 'policies': policies,
            'certificate_capabilities': plain(tuple(ContractRef(name, '1') for name in
                ('finite_tree', 'fixed_policy_tail', 'static_target_entropy_bound', 'finite_terminal_cost')))}


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



class RetiredEntrance(RuntimeError):
    """2026-10-12: derived-input entrance removed from F-a (F04 / E-01)."""

@dataclass
class Case:
    id: str
    variant: str
    document: dict
    model: FModel
    actions: tuple[f.ActionSpec, ...]
    ledger: Ledger
    records: tuple[Record, ...]
    measurements: tuple[f.MeasurementId, ...]
    frames: tuple[f.MeasurementFrame, ...]
    clock: FakeClock
    ids: SequentialIds
    context: f.FContext
    scope: f.EvaluationScope
    raw_style: Record | None
    continuation: f.FContinuation | None = None
    raw: tuple[Record, ...] = ()
    plans: tuple[Record, ...] = ()
    bindings: tuple[Record, ...] = ()


def digest(value):
    return 'sha256:' + sha256(canonical(value)).hexdigest()


def append_record(ledger, clock, ids, body, *, parents=None):
    kinds = {Observed: RefKind.OBSERVATION, Prediction: RefKind.PREDICTION,
             Preference: RefKind.PREFERENCE, JobOpened: RefKind.JOB,
             AttemptStarted: RefKind.ATTEMPT}
    record = Record(id=ids.new(kinds[type(body)]), at=clock.now(),
        writer=Role.MEMBRANE if isinstance(body, (Observed, AttemptStarted)) else Role.MODEL,
        producer=PRODUCER, body=body)
    ledger.append(record, ledger.heads() if parents is None else parents)
    return record


def all_records(ledger):
    return tuple(ledger.record(entry.cid) for entry in ledger.entries())


def context_for(ledger, clock, *, observed_ns=None, clock_contract=CLOCK):
    # spec:1435: CID -> fact refs from real causal ancestry, never tuple position.
    ancestry = {}
    for entry in ledger.entries():
        cids = ledger.ancestors((entry.cid,)) | {entry.cid}
        ancestry[entry.cid] = frozenset(str(ledger.record(cid).id) for cid in cids
                                      if ledger.record(cid).category is Category.FACT)
    return f.FContext(run=clock.run, now_ns=clock.mono_ns(),
        observed_ns=clock.mono_ns() if observed_ns is None else observed_ns,
        clock_contract=clock_contract, check_events=(), fact_ancestors=ancestry)


def add_preference(case, value, contract=LEGACY_PREFERENCE, *, parents=None):
    record = append_record(case.ledger, case.clock, case.ids,
        Preference(basis=(), content=Payload.json(value), contract=contract), parents=parents)
    case.records = all_records(case.ledger)
    case.context = context_for(case.ledger, case.clock)
    return record


class LegacyCase(_FactsCase):
    """2026-10-12: the old Case attribute names over a facts-entrance case (E-01).
    E/K/candidates/preferences are read from the ledger by the entrance, never passed in.
    actions/model/continuation are plain attributes; records/frames are read from the ledger."""
    @property
    def records(self): return tuple(self.ledger.record(e.cid) for e in self.ledger.entries())
    @records.setter
    def records(self, value): raise RetiredEntrance('records are the ledger; the entrance reads them')
    @property
    def frames(self):
        return tuple(f_from_json_frame(self.ledger.record(p)) for p in self.raw)
    @frames.setter
    def frames(self, value): raise RetiredEntrance('frames are ledger records; the entrance reads them')


def f_from_json_frame(record):
    return fe.f_from_json(record.body.content.data, contract=fc.MEASUREMENT)


def make_case(case_id, variant='default', *, H=None, scope_name=None, style='f', gamma=F(1),
              document=None, order=None):
    """2026-10-12: a facts-entrance case under the old name (test bodies unchanged).
    document= replaces the declaration before the ledger is written (old tests mutated
    case.document after construction, which the entrance cannot see); order= the candidate order."""
    if style != 'f' or gamma != F(1):
        raise RetiredEntrance('legacy style via make_case: use assemble_legacy_bridge')
    # The declaration is the facts world's (model.11); the old actions only name the order.
    doc, actions = _facts_world(case_id, variant)[0], finite_world(case_id, variant)[1]
    if document is not None:
        doc = deepcopy(document)
    if order is None:
        order = [op['id'] for op in doc['operations']] if document is not None else [a.id for a in actions]
    case = _facts_assemble(case_id, variant, H=H, scope_name=scope_name, document=doc, order=order)
    case.__class__ = LegacyCase; case.id = case_id; case.variant = variant
    case.actions = actions
    case.model = fm.FModel11(declaration=canonical(case.document))
    case.continuation = continuation_for(actions,
        policy_id='afterW' if case_id == 'FA16' and variant == 'split' else None)
    return case


def _old_make_case(case_id, variant='default', *, H=None, scope_name=None, style='f', gamma=F(1)):
    """Assembly only: no F loader, registry, history, evaluator or factory handle."""
    clock = FakeClock(run=Ref(RefKind.RUN, 'gate-f-fixture'))
    ids = SequentialIds(prefix='gate-f')
    ledger = Ledger(salts=SequentialSalts(), contents=MemoryContents())
    document, actions = finite_world(case_id, variant)
    if case_id == 'FA07' and H is None:
        H = 0
    if case_id == 'FA21' and scope_name is None:
        scope_name = 'one_step'
    scope = f.EvaluationScope(name=scope_name or ('finite_horizon' if H is not None else 'unbounded_total'),
                             version='1', H_ns=H, source=None)
    case = Case(case_id, variant, document, FModel(declaration=canonical(document)), actions,
        ledger, (), (), (), clock, ids, context_for(ledger, clock), scope, None)
    case.continuation = continuation_for(actions,
        policy_id='afterW' if case_id == 'FA16' and variant == 'split' else None)
    if case_id in ('FA02', 'FA03', 'FA05', 'FA06', 'FA07', 'FA18'):
        add_observations(case)
    if H is not None or scope_name is not None or style == 'legacy':
        if style == 'legacy':
            value = {'kind': 'style', 'H_ns': H, 'gamma': float(gamma)}
            contract = LEGACY_PREFERENCE
        else:
            value = {'kind': 'style', 'scope': {'name': scope.name, 'version': '1', 'H_ns': H},
                     'gamma': plain(F(gamma))}
            contract = fc.STYLE
        case.raw_style = add_preference(case, value, contract)
        case.scope = replace(scope, source=case.raw_style.id)
    if case_id == 'FA04' and variant == 'nonzero':
        add_preference(case, FIXED['FA04_nonzero_path_cost']['preference_item'])
    if case_id == 'FA07' and variant == 'first_action_cost':
        add_preference(case, first_action_item())
    return case


def add_observations(case, *, coalesced=False, missing=False, mismatch=False, closed=False):
    """Raw -> plan -> opportunity -> bindings. No belief or root injection."""
    ledger, clock, ids = case.ledger, case.clock, case.ids
    coverage = case.id in ('FA02', 'FA03')
    kernel_id = ('closed' if closed else 'open') if coverage else 'measure'
    kernel = next(k for k in case.document['kernels'] if k['id'] == kernel_id)
    if coalesced:
        # Same visible value/timing, different latent outcomes; sum before conditioning.
        kernel['outcomes'] = [
            outcome('latent-a', diagonal((F(1, 2), 0)), value=0),
            outcome('latent-b', diagonal((F(1, 4), F(1, 4))), value=0),
            outcome('other', diagonal((F(1, 4), F(3, 4))), value=1)]
        # §3-10-3: every execute.next must cover its kernel's new outcome IDs.
        # Preserve the original visible-result continuation for each new branch.
        renamed_from = {'latent-a': 'y0', 'latent-b': 'y0', 'other': 'y1'}
        for declared_policy in case.document['policies']:
            for node in declared_policy['nodes']:
                if node['kind'] == 'execute' and node['kernel'] == kernel_id:
                    node['next'] = {new: node['next'][old]
                                    for new, old in renamed_from.items()}
        case.model = FModel(declaration=canonical(case.document))
    route = f.RouteConfig(route_epoch='route-1', origin='bootstrap', version='1',
        sampling_contract=MEASURING, clock_contract=CLOCK,
        loss_contract=ContractRef('fixture.f.lossless', '1'), args={},
        decision=None, execution=None)
    applied = {'config': plain(route), 'effective_from': {'kind': 'clock',
        'value': plain(f.ClockReading(run=clock.run, time_ns=clock.mono_ns()))},
        'execution': None, 'evidence': []}
    append_record(ledger, clock, ids, Observed(route='membrane', content=Payload.json(applied),
                                             contract=fc.ROUTE_CONFIG, received_ns=clock.mono_ns()))
    cells = []
    groups = {}
    for o in kernel['outcomes']:
        emission = o['evidence']
        if emission is None:
            continue  # No-record outcomes stay in the kernel, not in ObservationPlan.cells.
        val, kind = emission['value'], emission['kind']
        key = canonical({'kind': kind, 'value': val})
        groups.setdefault(key, []).append(o['id'])
    for i, (key, names) in enumerate(groups.items()):
        cells.append(f.ObservationCell(id=f'cell-{i}', observation=f.ObservationValue(**json.loads(key)),
                                       outcomes=tuple(names)))
    plan = f.ObservationPlan(model_ref=digest(case.document), route_epoch='route-1',
        measurement_contract=MEASURING, kernel=f.KernelRef(name='finite_kernel', version='1', args={'id': kernel_id}),
        cells=tuple(cells), time_projection=TIME_PROJECTION, generation_contract=GENERATION)
    plan_record = append_record(ledger, clock, ids, Prediction(target='gate-f-observations', about=(),
        basis=(), content=Payload.json(plain(plan)), contract=fc.OBSERVATION_PLAN))
    seqs = [1, 2] if case.id == 'FA03' or (case.id == 'FA05' and case.variant == 'independent') else (
        [1, 1] if case.id == 'FA05' else [1])
    opportunities, raw, bindings, mids, frames = {}, [], [], [], []
    for delivery, seq in enumerate(seqs):
        if seq not in opportunities:
            job = append_record(ledger, clock, ids, JobOpened(
                decision=Ref(RefKind.DECISION, 'fixture-input-opportunity'), step=seq-1,
                content=Payload.json({'opportunity': seq}), contract=ContractRef('fixture.f.opportunity', '1')))
            opportunities[seq] = append_record(ledger, clock, ids, AttemptStarted(job=job.id,
                content=Payload.json({}), contract=ContractRef('sui.s1.attempt', '1')))
        opportunity = opportunities[seq]
        clock.advance(SECOND)
        mid = f.MeasurementId(origin=clock.run, route_epoch='route-1', sample_seq=seq, component='value')
        value = ('closed' if closed else 'no_arrival') if coverage else 0
        interval = f.MeasurementInterval(clock=clock.run, start_ns=(seq-1)*SECOND,
                                         end_ns=seq*SECOND, closure='(start,end]')
        frame = f.MeasurementFrame(route_epoch='route-1', sample_seq=seq, measurement_id=mid,
            measurement_interval=interval, actual_time=f.ClockReading(run=clock.run, time_ns=seq*SECOND),
            value=value, quality=f.ContractValue(contract=QUALITY, value='measured'), gap=None,
            source_cursor=f.ContractValue(contract=CURSOR, value=seq))
        if coverage:
            claim = f.CoverageClaim(route_epoch='route-1', interval=interval, kind=value, contract=MEASURING, evidence=(opportunity.id,))
            payload, contract = {'kind': 'claim', 'value': plain(claim)}, fc.COVERAGE
        else:
            payload, contract = plain(frame), fc.MEASUREMENT
        record = append_record(ledger, clock, ids, Observed(route='route-1', content=Payload.json(payload),
            contract=contract, caused_by=opportunity.id, received_ns=clock.mono_ns(),
            source_id=f'delivery-{delivery}'))
        cell = next(c for c in cells if c.observation.value == value)
        binding = f.ObservationBinding(plan=plan_record.id, records=(record.id,), opportunity=opportunity.id,
            step=0, cell=(cells[-1].id if mismatch else cell.id),
            slots=() if coverage else (f.ObservationSlot(slot='m', measurement=mid),),
            generated_by=(opportunity.id,), derived_from=())
        if not missing:
            bindings.append(append_record(ledger, clock, ids, Observed(route='membrane',
                content=Payload.json(plain(binding)), contract=fc.OBSERVATION_BINDING,
                caused_by=opportunity.id, received_ns=clock.mono_ns())))
        raw.append(record); mids.append(mid); frames.append(frame)
    case.raw, case.plans, case.bindings = tuple(raw), (plan_record,), tuple(bindings)
    case.measurements, case.frames = tuple(mids), tuple(frames)
    case.records = all_records(ledger)
    case.context = context_for(ledger, clock)


def observation_case(*, kind='measurement', **kwargs):
    case = make_case('FA01')
    case.id = 'FA02' if kind == 'coverage' else 'FA05'
    case.document, case.actions = finite_world(case.id)
    case.model = FModel(declaration=canonical(case.document))
    add_observations(case, **kwargs)
    return case


def resources(case):
    """2026-10-12: resources are issued by the entrance (EP) for the case's ledger, never assembled."""
    if not isinstance(case, LegacyCase):
        raise RetiredEntrance('resources for a hand-assembled Case')
    if getattr(case, '_resources', None) is not None:
        return case._resources
    point = case.predict('resources-predicate-' + str(len(case.ledger.entries())), fc.PREDICATE, predicate(True))
    case.context()
    case._resources = ff.prepare_f_predicate_from_facts(case.reader, fixed_parents=case.fixed_parents,
        model_ref=case.points['model'], context_ref=case.points['context'], predicate_ref=point,
        quantity_refs=(), registry=f.builtin_f_registry(), budget=BUDGET).resources
    return case._resources


def histories(case, *, available=(), incorporated=(), resource=None):
    if available or incorporated:
        raise RetiredEntrance('E/K are derived by the entrance; stage the ledger instead (assemble_knowledge)')
    read = _facts_histories(case)
    return read.E, read.K


def observations(case):
    return _facts_histories(case).observations


def candidates(case, *, actions=None, measure=None, draws=(), registry=None):
    return f.canonical_candidates(case.actions if actions is None else actions,
        measure=measure or f.CandidateMeasureRef(name='counting', version='1', args={}),
        generator=GENERATOR, basis=tuple(r.id for r in case.records), draws=draws,
        registry=registry if registry is not None else f.builtin_f_registry())


def make_problem(case, *, available=(), incorporated=(), action_list=None, measure=None,
                 generation_draws=(), resource=None):
    """2026-10-12: prepare through the facts entrance; knobs become ledger facts."""
    if resource is not None:
        raise RetiredEntrance('resources are built by the entrance from the ledger')
    if available or incorporated or action_list is not None or measure is not None or generation_draws:
        if available: case.acquire(case.raw)
        if incorporated: _facts_add_computation(case)
        if action_list is not None or measure is not None or generation_draws:
            order = [a.id for a in (case.actions if action_list is None else action_list)]
            case.candidate(order, measure=measure, draws=tuple(generation_draws))
        case.context()
    artifact = _facts_prepare(case)
    if not isinstance(artifact.value, f.FProblem):
        _raise_no_decision(artifact.value)
    return artifact.value


def _raise_no_decision(value):
    """Old callers expected the typed exception; the entrance records it as NoDecision."""
    kinds = {'rejected': f.FInputError, 'incomplete': f.FIncomplete,
             'missing_contract': f.FSpecificationMissing}
    exc = f.FSpecificationMissing if value.reason == 'missing_contract' else kinds.get(value.outcome, f.FInputError)
    raise exc(value.reason, value.detail or '', value.field)


def _old_make_problem(case, *, available=(), incorporated=(), action_list=None, measure=None,
                 generation_draws=(), resource=None):
    resource = resource if resource is not None else resources(case)
    E, K = histories(case, available=available, incorporated=incorporated, resource=resource)
    cs = candidates(case, actions=action_list, measure=measure, draws=generation_draws, registry=resource.registry)
    continuation = case.continuation if action_list is None else continuation_for(cs.candidates)
    resolved = fe.resolve_f_preferences(from_ledger(case.ledger, case.ledger.heads()), resources=resource)
    raise RetiredEntrance('prepare_f_problem')
    return fe.prepare_f_problem(model=case.model, parents=case.ledger.heads(), records=case.records,
        E=E, K=K, context=case.context, resolved=resolved, candidates=cs, continuation=continuation, method=METHOD, resources=resource, budget=BUDGET)


class ScriptedSource:
    """A test input source, not an evaluator; calls expose consumption, not randomness."""
    def __init__(self, values):
        self.values = tuple(values)
        self.calls = []

    def draw(self, request):
        value = self.values[len(self.calls)]
        self.calls.append(request)
        return value


def draw_request(problem_key, *, purpose='selection', ordinal=0):
    return f.DrawRequest(purpose=purpose, context_key=problem_key, ordinal=ordinal,
                          law=ContractRef('uniform_unit', '1'), args={})


def make_root(case, *, u=F(1, 2), **kwargs):
    problem = make_problem(case, **kwargs)
    prepared = _facts_prepare(case)
    draw = _facts_add_draw(case, prepared.value.problem_key, u=F(u))
    return ff.bind_f_draw(prepared, draw, reader=case.reader, budget=BUDGET).value


def _old_make_root(case, *, u=F(1, 2), **kwargs):
    problem = make_problem(case, **kwargs)
    source = ScriptedSource(({'u': plain(F(u))},))
    draw = draw_book({'selection': source}).for_selection(problem, request_id='fixture-root')
    raise RetiredEntrance('freeze_root')


def first_action_item():
    return {'kind': 'item', 'rule': {'name': 'table', 'version': '1'},
            'args': {'feature': {'name': 'started_actions', 'version': '1'},
                     'probs': [[['M'], 0.75], [['Q'], 0.25]]}}


def legacy_input(*, pending=False, nonzero=False, gamma=1.0):
    """Spec:1942-1970. Declaration/record assembly; no adoption or evaluation."""
    import numpy as np
    from sui.model import GenerativeModel
    from worlds import HandHistory
    names = ('M', 'Q', 'P') if pending else ('M', 'Q')
    perfect = np.array([[1., 0.], [0., 1.], [0., 0.]])
    quiet = np.array([[0., 0.], [0., 0.], [1., 1.]])
    model = GenerativeModel(states=('x0', 'x1'), outcomes=('y0', 'y1', 'constant'),
        actions=names, a={name: quiet.copy() if name == 'Q' else perfect.copy() for name in names},
        learnable=frozenset(), D=np.array([.5, .5]), log_C=np.log(np.array([1/3]*3)),
        gamma=gamma, durations={name: ((1., 1.),) for name in names},
        measures={name: 'report' for name in names})
    hand = HandHistory(run='gate-f-legacy')
    hand.boot()
    if pending:
        hand.start('P', 0)
        if nonzero:
            hand.add(Preference(basis=(), content=Payload.json(first_action_item()),
                                contract=LEGACY_PREFERENCE), 0)
        hand.add(Preference(basis=(), content=Payload.json({'kind': 'style', 'H_ns': 0, 'gamma': gamma}),
                            contract=LEGACY_PREFERENCE), 0)
        hand.at(1)
    ledger = Ledger(salts=SequentialSalts())
    for record in hand.records:
        ledger.append(record, ledger.heads())
    return model, ledger, hand


def legacy_case(*, pending=False, nonzero=False, gamma=1.0):
    """Public raw records -> Agent.adopt -> View, no Reading injection."""
    from sui.agent import Agent
    model, ledger, hand = legacy_input(pending=pending, nonzero=nonzero, gamma=gamma)
    agent = Agent(model=model, lineage='gate-f-legacy')
    agent.adopt(ledger, clock=hand.clock, ids=hand.ids)
    view = agent.view(now_ns=SECOND if pending else 0, observed_ns=0)
    return model, ledger, hand, agent, view, resolve(current(view.preferences), view)


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


def c1_case(variant='10', *, outcome_label='y0', boot_ns=0, delay_ns=0, bad=None, midwindow=False):
    """Spec:1713-1747, official JSON plus allowed raw recipe, no certified-decision forgery."""
    from s4b2_worlds import c1_world, start_attempt, completion_report
    from sui.rate_model import RateModel
    doc = json.loads(Path(__file__).with_name('s4b2_c1_declaration.json').read_bytes())
    first, second = map(int, variant)
    world = c1_world(n=first, boot_ns=boot_ns, declaration=doc)
    # midwindow exercises actual reader with clock advance and NO second report.
    read = next(c for c in doc['controls']['choices'] if c['id'] == 'read')
    job_value = {'choice': 'read', 'action': 'read', 'reservation_rule': read['reservation'],
        'execution': {'family': {'name': 'immediate-start', 'version': '1'},
                      'completion_process': 'read-done',
                      'start': {'time': [1, 1], 'causal_stage': 0, 'causal_position': 0}},
        'effect': 'identity'}
    job = append_record(world.ledger, world.clock, world.ids, JobOpened(
        decision=Ref(RefKind.DECISION, 'fixture-c1-input'), step=0,
        content=Payload.json(job_value), contract=ContractRef('sui.s4b.rate_job', '1')))
    attempt = start_attempt(world, job.id)
    world.ledger.accept(attempt)
    report = None
    if midwindow:
        world.clock.advance(SECOND//2)
    else:
        report = completion_report(world, attempt, 'read', second, outcome_label,
                                   received_delay_ns=delay_ns)
        if bad in ('saturated', 'gap'):
            value = report.body.content.as_json()
            if bad == 'saturated': value['arrival_count'] = {'kind': 'at_least', 'value': 3}
            else: value['window_start_ns'] += SECOND//2
            report = replace(report, body=replace(report.body, content=Payload.json(value)))
        world.ledger.accept(report)
    model = RateModel(declaration=canonical(doc))
    ctx = context_for(world.ledger, world.clock, observed_ns=world.clock.mono_ns(),
                      clock_contract=ContractRef('exact', '1'))
    return world, model, all_records(world.ledger), ctx, report


# This session's scope permits only gate_f test files. No Obsidian write, source
# edit, commit, full suite or cross-agent conversation access is performed.

# Historical handoff (superseded below): 2026-10-08, v0.9 second dry run, session
# 01a1189b-a16c-7ab0-890c-af27713927c6. Sources read: specification relevant
# sections including all of 3-10-12; independent fixed-value script (full);
# fixed/golden JSON relevant entries; approved input recipe bodies; src public
# declarations/signatures/docstrings only (AST filtering and inspect.signature).
# No external Web source or other agent's conversation was read.
# Implemented: FA01--FA21 and extra fixtures 1--12 to their public boundary.
# At that time R1--R8 failed with ContractGap; rootless finished and FA16 split
# were incomplete. v0.10 replaces them; full golden checks now belong to Claude.
# Provisional bindings: R1 checker/provenance contracts, R2 replay string=CID,
# R5 sha256(canonical(process)), R7 actual_time clock/unavailable union tags.
# Verification (PYTEST_ADDOPTS=--tb=line, to avoid implementation source excerpts):
# .venv/Scripts/python -B -m pytest -q -p no:cacheprovider tests/test_gate_f_contract.py
# 293 collected: 159 passed, 126 NotImplementedError, 8 ContractGap, 0 other;
# pytest exit 1, 1.25 seconds. 34 assembly checks and 125 old-API checks pass.
# New mathematical/serialization/record assertions beyond stubs are UNEXECUTED.
# Old independent plan checks: FA21, FA07 blank, FA07 first-action cost pass.
# Golden: 103 saved model bodies plus 3 action model bodies roundtrip; model.8
# success 3 decision-byte replays and 6 rejection scenes pass; action loader
# 7 rejection scenes pass. This is NOT full all-scene golden output regression.
# Independent --check tests/fixed_gate_f.json: PASS, 20 canonical items.
# Public-call signature binding audit: 0 mismatches (does not validate values).
# Corrected fixture bugs found in first run: kw-only F DTO constructors and
# non-membrane records must use Ledger.append, not Ledger.accept.
# Reused knowledge: assert content and separate wrong_* oracles, applied;
# mathematical correctness remains unverified while implementations are stubs.
# Historical next steps were superseded by the explicit v0.10 instruction.
# No tests are hidden with skip/xfail or marked as passing.
# Obsidian Sessions/Projects/Heat not updated under the explicit write scope.


def continuation_for(actions, *, policy_id=None):
    return f.FContinuation(after=tuple(f.ContinuationAfter(candidate=a.id,
        policy=None if policy_id is None else f.PolicyRef(
            name='finite_policy', version='1', args={'id': policy_id})) for a in actions))


def draw_binding(purpose, source):
    # Test-owned deterministic source identity; not a claim of statistical independence.
    raise RetiredEntrance('DrawSourceBinding')
    return fr.DrawSourceBinding(generator=ContractRef('fixture.draw.' + purpose, '1'),
                                stream_id='fixture-stream-' + purpose, source=source)


def draw_book(sources):
    raise RetiredEntrance('DrawBook')
    return fr.DrawBook(sources={purpose: draw_binding(purpose, source)
                               for purpose, source in sources.items()})


# Transcribed from spec §3-10-13-3 table (2233-2260), snake names per §13-補.
# Seven columns, including every dependency/condition; never imported from src.
BUILTIN_ROWS = """
action|finite_option|finite_option|action_spec|action_spec|finite_policy,finite_kernel|
kernel|finite_kernel|id|model_input|finite_kernel||declared_reference
policy|finite_policy|id|model_input|finite_policy||declared_reference
predicate|constant|constant|predicate_snapshot|predicate_result||cached_only
predicate|fact_present|fact_present|predicate_snapshot|predicate_result||cached_only
predicate|interval_compare|interval_compare|predicate_snapshot|predicate_result||cached_only
predicate|and|terms|predicate_snapshot|predicate_result||cached_only
predicate|or|terms|predicate_snapshot|predicate_result||cached_only
predicate|not|term|predicate_snapshot|predicate_result||cached_only
predicate|policy_end|empty|predicate_snapshot|predicate_result|finite_policy|cached_only,declared_reference
proof|finite_option_proof|operation|model_input|proof_check|finite_policy,finite_kernel|declared_reference
proof|finite_tree|empty|f_root|proof_check|finite_option_proof|finite_tree
proof|fixed_policy_tail|empty|tail_input|proof_check|finite_option_proof|fixed_continuation
proof|static_target_entropy_bound|empty|f_root|proof_check|finite_kernel|static_finite_target
proof|finite_terminal_cost|empty|f_root|proof_check|finite_tree|finite_terminal_cost
proof|iid_bits_limit|iid_bits_limit|f_limit_problem|limit_certificate||iid_fair_bits
method|sui.f.finite_evaluation|empty|evaluation_input|f_evaluation|finite_tree,fixed_policy_tail,static_target_entropy_bound,finite_terminal_cost,sui.f.exact_expression,sui.f.soft_choice|static_finite_target
method|sui.f.computation_information|empty|computation_input|information_parts|sui.f.exact_expression|full_input_conditioning
arithmetic|sui.f.exact_expression|empty|enclosure_input|f_quantity||
choice|sui.f.soft_choice|empty|choice_input|choice_output|sui.f.exact_expression|
execution|sui.f.simulated_execution|empty|action_spec|simulation_binding|finite_option_proof|simulation_only
measurement|sui.f.finite_measurement|empty|observation_input|observation_value|sui.f.measured_quality,sui.f.sequence_cursor|
projection|sui.f.value_only|empty|observation_input|observation_value|sui.f.finite_measurement|value_only
generation|sui.f.opportunity_step_slot|empty|generation_input|generation_output||recorded_generation
clock|sui.f.simulated_clock|empty|clock_input|clock_reading||same_run,simulation_only
quality|sui.f.measured_quality|empty|contract_value|contract_value||
cursor|sui.f.sequence_cursor|empty|cursor_input|contract_value||
generator|sui.f.explicit_candidates|empty|candidate_input|candidate_input||
""".strip()


def builtin_declarations():
    result = []
    for row in BUILTIN_ROWS.splitlines():
        kind, name, args, input_name, output_name, deps, checks = row.split('|')
        conditions = () if not checks else (f.ContractValue(
            contract=ContractRef('sui.f.capability_conditions', '1'),
            value={'checks': checks.split(',')}),)
        result.append(f.CapabilityDeclaration(kind=kind, ref=ContractRef(name, '1'),
            args_contract=ContractRef('sui.f.args.' + args, '1'),
            input_contract=ContractRef('sui.f.schema.' + input_name,
                '2' if input_name in ('f_root', 'tail_input', 'evaluation_input', 'computation_input') else '1'),
            output_contract=ContractRef('sui.f.schema.' + output_name, '2' if output_name == 'f_evaluation' else '1'),
            dependencies=tuple(ContractRef(dep, '1') for dep in deps.split(',') if dep),
            conditions=conditions))
    return tuple(result)


def callback_declaration():
    return f.CapabilityDeclaration(kind='predicate', ref=ContractRef('fixture.cached', '1'),
        args_contract=ContractRef('sui.f.args.constant', '1'),
        input_contract=ContractRef('sui.f.schema.predicate_snapshot', '1'),
        output_contract=ContractRef('sui.f.schema.predicate_result', '1'), dependencies=(),
        conditions=(f.ContractValue(contract=ContractRef('sui.f.capability_conditions', '1'),
                                    value={'checks': ['cached_only']}),))


def policy_end_case(*, other_model=False):
    case = make_case('FA01')
    p = case.document['policies'][0]  # Q in this fixture; IDs deliberately mislead.
    if other_model:
        p['entry'] = 'run'
        p['nodes'] = [execute('run', 'quiet', ['done'], 'end'), {'id': 'end', 'kind': 'end'}]
    else:
        p['entry'] = 'end'
        p['nodes'] = [execute('end', 'quiet', ['done'], 'finished-7'),
                      {'id': 'finished-7', 'kind': 'end'}]
    case.model = FModel(declaration=canonical(case.document))
    return case


UNION_CASES = ('frame_clock', 'frame_unavailable', 'route_unavailable', 'due_unavailable',
    'coverage_claim', 'coverage_gap', 'coverage_measurement_unavailable', 'coverage_unproved',
    'reservation_at', 'reservation_when',  # context_preflight / status_* were F-b types (removed 2026-10-12)
    'policy_own_kind', 'limit_own_kind', 'exact_own_op')


def union_case(name):
    case = make_case('FA05')
    frame = case.frames[0]
    unavailable = f.Unavailable(reason='not_measured', basis=())
    auxiliary = True
    contract = fc.VALUE_FACTS
    if name.startswith('frame_'):
        value = frame if name == 'frame_clock' else replace(frame, actual_time=unavailable, value=unavailable)
        wire, auxiliary, contract = plain(value), False, fc.MEASUREMENT
    elif name == 'route_unavailable':
        config = f.RouteConfig(route_epoch='r', origin='bootstrap', version='1',
            sampling_contract=MEASURING, clock_contract=CLOCK,
            loss_contract=ContractRef('fixture.f.lossless', '1'), args={}, decision=None, execution=None)
        value = fe.RouteApplied(config=config, effective_from=unavailable, execution=None, evidence=())
        wire = {**plain(value), 'effective_from': {'kind': 'unavailable', 'value': plain(unavailable)}}
        auxiliary, contract = False, fc.ROUTE_CONFIG
    elif name == 'due_unavailable':
        value = f.ReservationDue(reservation_id='r', firing_id='f', due=unavailable,
            detected=f.ClockReading(run=case.clock.run, time_ns=SECOND), execution=None, evidence=())
        wire = {**plain(value), 'due': {'kind': 'unavailable', 'value': plain(unavailable)}}
    elif name.startswith('coverage_'):
        values = {
            'coverage_claim': ('claim', f.CoverageClaim(route_epoch='r', interval=frame.measurement_interval,
                kind='closed', contract=MEASURING, evidence=())),
            'coverage_gap': ('gap', f.Gap(route_epoch='r', sequence_range=(1, 2),
                interval=frame.measurement_interval, reason='lost', evidence=())),
            'coverage_measurement_unavailable': ('measurement_unavailable', f.MeasurementUnavailable(
                route_epoch='r', requested_interval=frame.measurement_interval, reason='unavailable', evidence=())),
            'coverage_unproved': ('coverage_unproved', f.CoverageUnproved(route_epoch='r',
                interval=frame.measurement_interval, missing_contracts=(MEASURING,), evidence=()))}
        kind, value = values[name]
        wire, auxiliary, contract = {'kind': kind, 'value': plain(value)}, False, fc.COVERAGE
    elif name.startswith('reservation_'):
        trigger = f.At(run=case.clock.run, time_ns=SECOND, source=case.raw[0].id) if name.endswith('_at') else f.When(predicate=predicate(True))
        value = f.Reservation(id='r', policy_generation='g', selected=Ref(RefKind.DECISION, 'd'),
            root_key='sha256:'+'0'*64, trigger=trigger, operation=case.actions[0], reservation_draw=None)
        wire = {**plain(value), 'trigger': {'kind': 'at' if isinstance(trigger, f.At) else 'when', 'value': plain(trigger)}}
    elif name == 'context_preflight':
        raise RetiredEntrance('FResultContext')
        value = fe.FResultContext(attempt=None, input=f.FPreflight(parents=frozenset(), model_ref=None,
            required_records=(), required_capabilities=()))
        wire = plain(value)
    elif name.startswith('status_'):
        raise RetiredEntrance('Status')
        value = fr.Status(frontier=frozenset(), pending=(), awaiting=(), queued=(), thinking=0,
                          waiting=0, used={}, capacity={}, computations=() if name.endswith('_available') else unavailable)
        wire = plain(value)
        for key in ('belief', 'perception', 'computations', 'routes', 'schedules', 'pledges'):
            part = getattr(value, key)
            wire[key] = {'kind': 'unavailable' if isinstance(part, f.Unavailable) else 'available', 'value': plain(part)}
        auxiliary, contract = False, fc.STATUS
    elif name == 'policy_own_kind':
        value = f.FinitePolicy(id='p', entry='arbitrary-end', nodes=(f.EndNode(id='arbitrary-end', kind='end'),))
        wire = plain(value)
    elif name == 'limit_own_kind':
        value = f.FLimitProblem(
            process=f.LimitProcess(name='iid_fair_bits', version='1', args=f.LimitProcessArgs(index_origin=0)),
            observations=f.LimitObservations(name='reveal_next_bit', version='1', args={}),
            information_target='entire_sequence', cost=f.BlankLimitCost(kind='blank'),
            scope=f.LimitScope(name='unbounded_total', version='1', H_ns=None), proof=None)
        wire, auxiliary, contract = plain(value), False, fc.LIMIT_PROBLEM
    else:
        value = f.ExactReal(op='rational', value=F(1, 2))
        wire = plain(value)
    return value, contract, {'type': type(value).__name__, 'value': wire} if auxiliary else wire


# Current handoff: 2026-10-08, spec v0.10 third dry run.
# Codex session: 01a1189b-a16c-7ab0-890c-af27713927c6 (CODEX_THREAD_ID checked).
# Written only: tests/gate_f_cases.py and tests/test_gate_f_contract.py.
# Sources: spec sections 3-10-13-1 through -9 and supplement (full relevant text);
# updated src public shapes/docstrings/signatures only; expressly permitted 28-row
# declaration DATA only, no capability/private function bodies. Independent FA16
# fixed JSON entry read. No Web/external dialogue, source edit, commit, full suite.
# R1--R8 construction gaps are replaced by concrete public calls / assertions;
# R4 full golden --check work explicitly belongs to Claude. Existing old checks kept.
# Added all eight discrimination groups in 3-10-13-9, exact canonical digest inputs,
# FA16 C and W+afterW using the same normative model; no fresh provisional contract.
# Scoped pytest: 393 collected; 182 passed, 209 NotImplementedError,
# 0 ContractGap, 2 other failures (exit 1). No skip/xfail.
# Other failures (spec:2128): FReplayMismatch(field='/root').fields is (),
# and fields=('not-a-json-pointer',) does not raise FInputError(shape).
# Kept both failures visible; source constructor body was not inspected or edited.
# Public signature audit: 312 direct calls + 5 ** expansions + 52 book-method calls,
# 0 mismatches. This is call binding, not proof of every runtime argument type.
# Public declaration data matches all 28 independent expected rows / seven fields.
# New behavior beyond NotImplementedError remains UNVERIFIED; old API tests pass.
# Assessment: ContractGap/signature criteria met, but two non-stub exception-contract
# failures prevent an unconditional close. Proposed next step: implementation owner
# corrects the exception constructor and repeats the same contract-file command.
# Reused knowledge: independent fixed values and content/wrong_* assertions remain
# applicable; separating constructor assembly from calculation exposed the exception
# inconsistency. Obsidian Sessions/Projects/Heat not updated (explicit write scope).


# F-a stage-1 fixture correction handoff: 2026-10-08, specification v0.10.
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3 (CODEX_THREAD_ID).
# Written only: tests/gate_f_cases.py and tests/test_gate_f_contract.py; no commit.
# Read: specification relevant passages 390-418, 1225-1265, 2134-2160,
# 2784-2793; test/fixture relevant portions; public Mapping field annotations
# extracted with AST from src/sui/f*.py. No implementation bodies were viewed.
# No external sources or other AI conversations were accessed.
# Applied: coalesced kernel renaming updates every referring execute.next,
# preserving the original visible outcome's continuation; empty snapshot
# quantities becomes [] while other empty mappings remain {}. One Frame.value
# rejection became raw-JSON preservation/roundtrip; outer unknown tags and
# other double wrappers retain their rejection assertions.
# Verification: .venv/Scripts/python -B -m pytest -q -p no:cacheprovider
# tests/test_gate_f_contract.py; subprocess timeout=120 seconds,
# PYTEST_ADDOPTS=--tb=line (avoid source excerpts), PYTHONDONTWRITEBYTECODE=1.
# Result: 393 tests, 356 passed, 37 NotImplementedError, 0 other, exit 1, 42.53s.
# All 37 exception diagnostics were NotImplementedError. The initial parser
# misclassified truncated FAILED lines; the exception diagnostics establish
# the corrected counts above. No failure was suppressed with skip/xfail.
# Additional in-memory checks passed: [] vs {}, nonempty structured-key order,
# coalesced next coverage, and both edited files' syntax.
# Environment: normal command/node startup failed (setup refresh errors);
# reviewed escalated exec worked. First subprocess launch omitted .exe and
# did not start pytest; explicit python.exe executable resolved it.
# Reused knowledge: public-boundary/content assertions applied successfully;
# old intrinsic-drive knowledge was unrelated to this serialization correction.
# Remaining: stage-2 behavior behind 37 stubs is unverified; implementation owner
# can continue stage 2 and rerun this suite. No user decision is outstanding.
# Obsidian Sessions/Projects/Heat remain unmodified under the explicit two-file
# write scope; this is the local record pending the owner's integration.


# F-a mutation-gap tests: 2026-10-08, spec v0.10, continuation in Codex session
# 01a11967-1136-7233-bb4c-74e1807cdef3. Existing tests retained; no commit.
# Added 6 cases in tests/test_gate_f_contract.py (1842, 1890, 1912, 1941):
# GF-M23: constant(false)/may_never quiet Q, u=1/6 selects Q; u=2/3 selects M.
# Both assert G and q=(1/3,2/3) against the independent FA14 fixed JSON entry.
# GF-M41: Selected and rootless attempts, both start and finish preparations;
# append a late fact before each commit, require exact PreparedRecord.parents,
# exclude late fact even from ancestry, preserve records and idempotent retry.
# GF-M42: a declared predicate with no implementation; correct
# algorithm_unavailable verifies, substituted prerequisite_unavailable and
# missing_contract claims each raise FReplayMismatch(result_mismatch).
# Sources read: spec relevant text 79-87, 1751-1807, 2439-2555 and searched
# contract lines 333/1149/1333; fixed_gate_f.json FA14 entry only; relevant test
# fixtures; AST-filtered public fields/signatures/docstrings for ActionSpec,
# NoDecision, PreparedRecord, PreparedFRecords, make_f_records, commit_f and
# Ledger/Entry. No implementation bodies or mutation replacement bodies read.
# No external Web sources or other AI conversations accessed.
# Initial focused check: 5 passed, 1 failed due to test-only nonempty-parent
# assumption; removed it because rootless initial parents may validly be empty.
# Full verification: .venv/Scripts/python -B -m pytest -q -p no:cacheprovider
# tests/test_gate_f_contract.py, subprocess timeout=120, PYTEST_ADDOPTS=--tb=line,
# PYTHONDONTWRITEBYTECODE=1: 399 passed, 0 failed/other, exit 0, 85.81 seconds.
# AST syntax/unique function names/no pytest skip-xfail call checks passed.
# Actual GF-M23/M41/M42 mutation runs NOT performed; Claude can rerun expect
# prefixes on the added tests. Passing the original code is not a KILLED result.
# Reused knowledge: mutation-gap distinction and input-preservation assertions
# (Obsidian/Knowledge/変異が生き残ったら同値か試験の穴かを分ける.md), applied.
# Written only the two gate_f test files. Obsidian Sessions/Projects/Heat remain
# pending integration because this request restricts writes to those two files.


# F-a pre-commit review regressions F01-F07: 2026-10-08, specification v0.10.
# Codex session 01a11967-1136-7233-bb4c-74e1807cdef3 (same continuation).
# Input report: C:/Users/you11/.claude/codex-dialogues/
# sui-gate-f-a-review.turn1.json, report.report_markdown read in full; source
# links were not followed. Used reported inputs/expectations, not implementation.
# Other sources: spec relevant passages/search hits (275, 416, 529, 545, 622,
# 712, 755, 1333, 2305, 2487-2531); fixed_gate_f.json relevant oracle entries;
# existing test fixtures; AST-filtered public NormalizationCertificate,
# FCertificate, Selected and FEvaluation annotations/docstrings; public results.
# No private function/body inspection or external Web material.
# Added 17 cases in tests/test_gate_f_contract.py under test_review_F01_..F07_:
# F01 unread execute branches reject, identical revealed input selects.
# F02 missing child proof / mismatched prediction reject like initial actions;
# coherent forged Selected DTOs are rejected by verify_f_result. Valid Selected
# verifies first. A legitimate verified NoDecision certifies rejection only.
# F03 duplicate CandidateSet rejected through DTO and JSON (early decode allowed).
# F04 equal nonzero J retains Z=2 / Z=4; F05 changed u rejects, float 0.5 matches.
# F06 alias-only/alias-first/original-first all evaluate with masses 1/2,1/2.
# F07 assert_quantity requires actual bounds to CONTAIN independent oracle bounds.
# Log coefficients use Fraction atanh series (160 terms, positive geometric tail)
# with scaling/sign reversal. Returned ExactReal expressions use independent
# rational intervals and outward Decimal ln/exp at 110 digits, not sui's evaluator.
# Interval-only fixed entries retain their independent saved oracle intervals.
# Width limits are separate from containment: no epsilon repairs an inward bound.
# Path/expression consistency uses interval differences; rational values are exact.
# Old API bare-float compatibility retains its old tolerance, per spec:275; these
# are explicitly not F guaranteed bounds. No existing test removed or weakened.
# F07 rejects midpoint point bounds and narrow intervals entirely below/above ln2,
# including a midpoint forged from real FA15 output; mixed-sign/zero oracles checked.
# Initial focused run exposed test assumptions (NoDecision can verify rejection;
# malformed JSON can reject early; propagated widths need not equal term tolerance).
# Corrected these against the public contracts. Focused set: 19 passed.
# Final: .venv/Scripts/python -B -m pytest -q -p no:cacheprovider
# tests/test_gate_f_contract.py, subprocess timeout=150 seconds,
# PYTEST_ADDOPTS=--tb=line and PYTHONDONTWRITEBYTECODE=1:
# 416 passed, 0 failed/NotImplementedError/other, exit 0, 94.28 seconds.
# Previous full run before final path-assertion strengthening: 416 passed, 98.20s.
# No skip/xfail added, no commit. Old implementation / actual mutants NOT rerun;
# Claude can confirm mutation kills independently using test_review_F01_..F07_.
# Reused knowledge: independent input preservation and mutation-gap distinction
# (Obsidian/Knowledge/変異が生き残ったら同値か試験の穴かを分ける.md), applied.
# Written only the two gate_f test files. Obsidian Sessions/Projects/Heat remain
# unmodified under this request's explicit scope; this local record awaits integration.


def world_request(case, *, resource=None, action_list=None, measure=None):
    """v0.11 request DTO from public histories/preferences, before certification."""
    resource = resource or resources(case)
    E, K = histories(case, resource=resource)
    resolved = fe.resolve_f_preferences(from_ledger(case.ledger, case.ledger.heads()), resources=resource)
    cs = candidates(case, actions=action_list, measure=measure, registry=resource.registry)
    raise RetiredEntrance('FWorldRequest')
    return f.FWorldRequest(model_ref=f_model_digest(case), parents=case.ledger.heads(),
        records=tuple(r.id for r in case.records), E=E, K=K, context=case.context,
        resolved=f.FWorldResolved(**{field.name: getattr(resolved, field.name) for field in fields(resolved)}),
        candidates=cs, continuation=case.continuation if action_list is None else continuation_for(cs.candidates),
        method=METHOD)


def f_model_digest(case):
    # Model declaration canonical bytes, independent from the model loader.
    return digest(case.document)


def prepare_case(case, **kwargs):
    """2026-10-12: (artifact, value) from the facts entrance."""
    if kwargs:
        raise RetiredEntrance('prepare_case knobs')
    artifact = _facts_prepare(case)
    return artifact, artifact.value


def review5_primary_generation_legacy(*,fault=None):
    """Old model.10 entry with explicit measurement_requested/measurement_job.

    Its positive input uses the same public primary-generation records as the
    facts tests; the old opaque fixture job cannot test the typed Plan/step rule.
    """
    from gate_f_facts_cases import review5_generation_case
    case=make_case('FA06')
    primary=review5_generation_case(document=case.document,adopted=False,fault=fault)
    return replace(case,ledger=primary.ledger,clock=primary.clock,ids=primary.ids,
        records=all_records(primary.ledger),context=context_for(primary.ledger,primary.clock),
        raw=tuple(primary.ledger.record(p) for p in primary.raw),
        plans=tuple(primary.ledger.record(p) for p in primary.plans),
        bindings=tuple(primary.ledger.record(p) for p in primary.bindings),measurements=tuple(primary.measurements))


# ---
# date: 2026-10-08
# project: iku/sui
# tool: codex
# tags: [session, gate-f, tests, structural-contract]
# ---
# Session log: F-a v0.11 structural tests. [[Projects/iku]]
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3.
# Review input: C:/Users/you11/.claude/codex-dialogues/sui-gate-f-a-review.turn2.json,
# report.report_markdown (full report read; only inputs/expected behavior used;
# no linked src bodies opened). No message was sent to another agent.
# 実施済み: Adapted the original 416 cases to required budget, ledger resources,
# v2 wire contracts, preparation failures, certified quantity prerequisites.
# Added 83 cases: review F09-F16, section 3-10-14-11 A/B/C1-9, and preference
# causality. Existing mathematical expectations and independent bounds retained.
# Artifacts (v0.11): C:/Users/you11/Desktop/iku/sui/tests/gate_f_cases.py and
# C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_contract.py. No other edits.
# Read: specs/関所F_いつ動くか.md relevant v0.11 sections, full 3-10-14;
# fixed_gate_f.json relevant entries (including both new independent oracles);
# src public definitions/signatures/docstrings only, plus import statements for
# evaluator dependency checks. No private implementation bodies or web sources.
# A: all 10 mathematical entries inventoried; compiled-world operation under
# disabled model readers/resolvers; 9 root entrances reject unissued roots;
# choice rejects unissued/modified evaluation; restored paths rechecked;
# cross-world/tampered values and fixed-dependency loss rejected.
# B: every row of the negative-input table mapped at the end of the test module.
# C: invisible split/merge/rename/completion; new evidence vs reveal; root/deep
# aliases at depths 0,1,3; redelivery vs independent equal values; zero-time
# finite/cyclic and positive forever; generated FiringBook operation sequences;
# quantity value/key/root/provenance binding; common J shift preserves q, scales Z.
# Preference: causal styles, withdrawal, conflict NoDecision save/replay,
# points/before tampering, same-CID changed parents, duplicate Record/CIDs without
# invented transitive ancestry, frozen parents vs later styles, missing inputs.
# 検証: final full suite with subprocess timeout=180 seconds:
# .venv/Scripts/python -B -m pytest -q -p no:cacheprovider -n 2 tests/test_gate_f_contract.py
# PYTEST_ADDOPTS=--tb=line; PYTHONDONTWRITEBYTECODE=1; Python 3.12.10;
# installed pytest-xdist, two processes. 497 passed, 2 failed, 499 collected,
# 0 NotImplementedError, no skip/xfail; exit 1; pytest duration 161.98 seconds.
# Earlier full checkpoints: 491 passed/5 failed (106.56s), then 494/2 (102.23s).
# Three wire expectation failures were migrated using verify_f_result's PUBLIC
# v2 docstring: preflight/limit certificate now contains preparation_input:null.
# New unissued-root inventory: 9 passed (5.57s). Final comments only were added
# after the last run; AST excluding module docstrings remains identical.
# 未解決: invalid PredicateSnapshot.quantities=[] raises AttributeError, not
# FInputError (test:1399-1402; spec:2989). Continuation finite_policy/999 with
# existing args.id='afterW' raises shape at /continuation/after/0/policy, not
# unknown_version (test:2336-2349; spec:2990). Expectations were NOT weakened.
# ハマった点: decoded valid path tables may be rechecked and accepted (spec:3030),
# while altered/foreign tables reject. Preference tamper tests recompute the
# manifest's own world_key so they reach causal comparison rather than hash error.
# Ledger.append deduplicates a Record locally; two independent Ledger branches
# plus public merge construct the legitimate two-CID fixture. No private state.
# 再利用した知見と結果: [[Knowledge/好みの因果はCIDの祖先から復元する]] was effective:
# the public prepare/restore tests retain both CIDs and do not infer false edges.
# 未実行: old implementation rollback, mutation runs, repository-wide suite,
# final sequential full run, commit. Mutation kills are not claimed.
# 次: implementation owner to fix the two public error classifications, then
# rerun the same full command; Claude can independently rerun structural mutants.
# Vault Sessions/Projects/Knowledge/Heat were NOT written: latest instruction
# permits gate_f test files only. This local log awaits vault integration.


# ---
# date: 2026-10-09
# project: sui
# tool: codex
# tags: [session, sui, gate-f, tests, replay]
# ---
# Session log: review 3 F17-F19 regression tests. [[Projects/sui]]
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3 (CODEX_THREAD_ID confirmed).
# Review input: C:/Users/you11/.claude/codex-dialogues/sui-gate-f-a-review.turn3.json,
# report.report_markdown read in full; used only inputs and expected behavior.
# No src links followed, no private function bodies read, no other-agent messages.
# Specification: specs/関所F_いつ動くか.md v0.11, relevant 3-10-14-3/4/supplement;
# public definitions/signatures/docstrings inspected with AST filtering only.
# External Web: none. Project note read at current-status section (rest not read).
# 実施済み: Added 36 parametrized cases, retaining the previous 499 unchanged.
# Artifact: C:/Users/you11/Desktop/iku/sui/tests/test_gate_f_contract.py:3175 onward.
# F17 (26): DTO/JSON, omitted FACT+empty claimed ancestors and substituted
# MEASUREMENT/OBSERVATION_BINDING bodies with same IDs, prepare/restore/verify;
# honest ledger/records succeed, absent/empty ledger -> missing_input.
# Honest numerical control ledgers build the altered-history results; forged
# roots rebind only the claimed frontier/context and recompute public digests.
# Digest formulas are checked against an unchanged public root; refusals must
# identify records/facts/ancestry, not merely another malformed hash/choice.
# F18 (4): only public candidate proof changed, normal model kept byte-identical;
# prepare raises missing_contract, forged Selected cannot verify; ID-only alias
# succeeds and preserves independent q=1/2,1/2, through DTO and JSON.
# F19 (6): kernel missing -> algorithm_unavailable; verify/bind with old and new
# registry preserve exact saved preparation/input/result digests; attempt records
# committed with missing kernel replay after the implementation is added.
# Tampered implemented flag/declaration rejects; bound input cannot be replaced;
# fresh binding rejects a declaration inconsistent with current fixed resources.
# 検証: focused F17/F18/F19: 36 passed, 499 deselected, 26.76 seconds.
# Final full command (subprocess timeout=180 seconds):
# .venv/Scripts/python -B -m pytest -q -p no:cacheprovider -n 2 tests/test_gate_f_contract.py
# PYTEST_ADDOPTS=--tb=line; PYTHONDONTWRITEBYTECODE=1; Python 3.12.10.
# 535 passed, 0 failed/errors/NotImplementedError/skip/xfail; 109.59 seconds, exit 0.
# The preceding F-STRUCT-01/02 tests also pass; no expectation was weakened.
# ハマった点: VALUE carries Selected/NoDecision, not the persisted DECISION schema;
# Frame.value retains its kind/value wrapper. Reconstructed ledgers use source
# sequence order, not the order returned by entries(). Corrected these fixtures.
# FReplayMismatch may report fields without field; inspect the supplied locations.
# 再利用した知見と結果: [[Knowledge/失敗の再検証では不足していた依存を足さない]]
# was effective, independently confirmed by F19 verify/bind/attempt replay tests.
# [[Knowledge/好みの因果はCIDの祖先から復元する]] informed the ledger controls.
# 未実行: prior implementation rollback, mutations, repository-wide full suite,
# commit. A pre-fix failure / mutation-kill count is not claimed.
# 次: Claude may independently run the old-input mutants and review these tests.
# Writes limited to the two authorized gate_f test files. Vault Sessions/Projects/
# Knowledge/Heat were not changed; this local log awaits integration.


# ---
# date: 2026-10-09
# project: sui
# tool: codex
# tags: [session, sui, gate-f, tests, identity]
# ---
# Session log: review 4 F20-F23 / v0.11 supplement 2. [[Projects/sui]]
# Codex session: 01a11967-1136-7233-bb4c-74e1807cdef3.
# Review input: C:/Users/you11/.claude/codex-dialogues/sui-gate-f-a-review.turn4.json,
# report.report_markdown read in full, using inputs and expected results only.
# Linked src bodies and identity-audit scratchpad were not opened. No AI messages sent.
# Normative source: specs/関所F_いつ動くか.md:3341-3349, supplement read in full;
# related public definitions/signatures/docstrings read through AST filtering.
# External Web: none. Obsidian Home/Heat/Projects/sui current portions read;
# Knowledge/記録の参照と台帳の認証を分ける.md read in full.
# 実施済み: kept the existing 535 cases and numerical expectations unchanged;
# added 28 DTO/JSON cases in tests/test_gate_f_contract.py:3460 onward.
# Existing tickets already use public factories and automatically carry started_digest.
# New tickets come from begin_f_attempt; entire Record digests checked independently.
# F20: resource started/ticket belong to a different honest same-ID attempt from the
# actual ledger; verify_result, verify_records and bind_result_context must reject.
# F21: destination has a different same-ID dependency; commit must reject before writes.
# F22: finished Record contents unchanged, actual parents altered; both replay APIs reject.
# F23: equal attempt ID and input/result digests, different request/firing/ticket;
# foreign finish must raise FInputError(firing_result_conflict), not just any exception.
# One P7 property covers ticket, dependency, parents and receipt finish together.
# Positive controls: public restore, valid saves, same Prepared retry, copy, late FACT,
# finish/redelivery, storage failure before the second write or after the first write.
# Fixtures share immutable public certificates but use fresh ledgers/books/clocks/IDs.
# JSON decoding alone does not issue live handles: restore_f_root and verify_f_result
# reissue them through public APIs; decoded bytes are asserted equal before reuse.
# Baseline command: .venv/Scripts/python -B -m pytest -q -p no:cacheprovider -n 2 tests/test_gate_f_contract.py
# Baseline: 535 passed in 122.30 seconds, exit 0 (180-second timeout).
# Focused development runs exposed and corrected JSON fixture handle issuance errors.
# Final verification result recorded below.
# 再利用した知見と結果: identity Knowledge was applicable to CID/digest comparisons;
# tests distinguish content mismatches from normal ledger copies and later facts.
# 未実行: pre-fix implementation rollback, mutations, repository-wide suite, commit.
# No pre-fix failure or mutation kill count is claimed without executing that version.
# Writes restricted to gate_f test files; Vault Sessions/Projects/Knowledge/Heat remain
# unchanged. This local session log awaits integration, not claimed as Vault-written.
# Final full command: .venv/Scripts/python -B -m pytest -q -p no:cacheprovider -n 2 tests/test_gate_f_contract.py
# Executed with subprocess timeout=180, PYTEST_ADDOPTS=--tb=line,
# PYTHONDONTWRITEBYTECODE=1; 559 passed, 4 failed, 147.25 seconds, exit 1.
# No NotImplementedError, errors, skip or xfail. All prior 535 still pass;
# new cases: 24 passed, 4 failed (F23 dedicated and P7 property, DTO/JSON each).
# Finding F23-RETURN: foreign request/firing is rejected with FReplayMismatch
# (result_mismatch), whereas supplement 2 line 3346 requires FInputError
# (firing_result_conflict). Evidence: test_gate_f_contract.py:3651 and :3739.
# This is a return-contract mismatch, not observed acceptance of a foreign result.
# F20/F21/F22 and normal save/retry/copy/late-fact/receipt controls all pass.
# 次: implementation owner should align F23's exception with the normative contract;
# rerun the same whole-file command afterwards. Expected exception was not relaxed.
