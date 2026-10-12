"""Black-box F-a authentication tests; expectations come only from the contract.

Run only this file, at most two workers. --tb=no avoids showing implementation
source in failure reports. Each bad/good member is an independent pytest item.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields as dataclass_fields, is_dataclass, replace
from enum import Enum
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import ast
import json
from pathlib import Path
import re
from typing import get_type_hints

import pytest

from sui import f, f_facts as ff, f_contracts as fc
from sui import f_entry as public_codec
from sui.clock import Instant
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind
from sui.records import (Record, Observed, Decided, JobOpened, AttemptStarted,
                         Prediction, Interpretation, Preference, Intention,
                         IntentionStatus, Payload, Role, StateRef)
from gate_f_facts_cases import (FactsCase, Reader, BareFactsCase, BUDGET, METHOD,
    CLOCK, PRODUCER, SECOND, plain, canonical, finite_world, add_observations,
    add_computation, add_draw, assemble_c1, assemble_legacy_bridge,
    assemble_limit, prepare, histories, prepare_bridge, auth_copy_primary)
from gate_f_auth_inventory import (INVENTORY, FIELD_TARGETS, BODY_FIELDS,
    CONTRACTS, PAIRS, ALL_ENTRIES, FINITE, CONTEXT, REPRESENTATIVES,
    presence_group, identity_group, CONSTRUCTION_BOUNDARIES)
from gate_f_auth_inventory import REVIEW4_PAIRS, REVIEW5_PAIRS
from gate_f_facts_cases import Ledger, MemoryContents, SequentialSalts


def content(record, **updates):
    value = deepcopy(record.body.content.as_json())
    value.update(updates)
    return replace(record, body=replace(record.body, content=Payload.json(value)))


def finite_case(*, observations=False, computation=None):
    case = FactsCase(finite_world('FA06')[0], name='auth')
    if observations or computation:
        add_observations(case)
    if computation:
        case.acquire(case.raw, clock=case.reading('raw-acquired'))
        add_computation(case, stage=computation)
    case.candidate(('Compute',))
    case.context()
    return case


def base_case(entry, *, observations=False, computation=None):
    if entry == 'EC':
        return assemble_c1()
    if entry == 'EB':
        return assemble_legacy_bridge()[0]
    if entry == 'EL':
        return assemble_limit()
    return finite_case(observations=observations, computation=computation)


def refresh(case):
    case.fixed_parents = tuple(sorted(case.ledger.heads()))
    return case


def context_again(case, **kwargs):
    case.context(**kwargs)
    return case


def add_predicate(case, value=None):
    case.predict('auth-predicate', fc.PREDICATE,
                 {'name': 'constant', 'version': '1', 'args': {'value': True}}
                 if value is None else value)
    return refresh(case)


def invoke(entry, case, *, prepared=None, draw=None, saved=None):
    registry = f.builtin_f_registry()
    if entry == 'EN':
        return prepare(case, registry=registry)
    if entry == 'EH':
        return histories(case, registry=registry)
    if entry in ('EC', 'EP'):
        args = dict(fixed_parents=case.fixed_parents, model_ref=case.points['model'],
                    context_ref=case.points['context'], registry=registry, budget=BUDGET)
        if entry == 'EC':
            return ff.read_c1_from_facts(case.reader, **args)
        return ff.prepare_f_predicate_from_facts(case.reader,
            predicate_ref=case.points['auth-predicate'], quantity_refs=(), **args)
    if entry == 'EF':
        return ff.check_f_preflight_from_facts(case.reader,
            f.FPreflightFacts(fixed_parents=case.fixed_parents, model=None,
                required_records=tuple(sorted(set(case.fixed_parents))), required_capabilities=()),
            registry=registry, budget=BUDGET)
    if entry == 'EL':
        return ff.certify_f_limit_from_facts(case.reader,
            declaration_ref=case.points['limit'], registry=registry, budget=BUDGET)
    if entry == 'EB':
        return prepare_bridge(case, registry=registry)
    if entry == 'ED':
        return ff.bind_f_draw(prepared, draw, reader=case.reader, budget=BUDGET)
    if entry == 'ER':
        return ff.restore_f_math_result(saved, reader=case.reader, registry=registry, budget=BUDGET)
    raise AssertionError(entry)


def call_observed(fn):
    """Record only public diagnostics, never traceback/source or private state."""
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def diagnostic(value, exc):
    if exc is not None:
        return type(exc).__name__, getattr(exc, 'reason', None), getattr(exc, 'field', None), getattr(exc, 'fields', ())
    result = getattr(value, 'value', value)
    if isinstance(result, f.NoDecision):
        return 'NoDecision:' + result.outcome, result.reason, result.field, ()
    return type(result).__name__, None, None, ()


def assert_pointer(field, fields=(), *, relevant=()):
    assert field is not None, 'A-21: a known offending field needs a diagnostic pointer'
    assert isinstance(field, str) and (field == '' or field.startswith('/')), f'not JSON Pointer: {field!r}'
    assert not re.search(r'~(?![01])', field), f'invalid JSON Pointer escape: {field!r}'
    if fields:
        assert isinstance(fields, tuple) and tuple(sorted(set(fields))) == fields
        assert field in fields
    if relevant:
        parts = tuple(p.replace('~1', '/').replace('~0', '~') for p in field.split('/')[1:])
        # A-21 does not standardize enclosing prefixes. A logical field such as
        # outer_inputs or record.body.inputs still identifies the inputs column.
        assert any(part == term or part.endswith('.'+term) or part.endswith('_'+term)
                   for part in parts for term in relevant), f'A-21: {field!r} does not identify {relevant!r}'


def assert_legal(value, exc, entry):
    observed = diagnostic(value, exc)
    assert exc is None, f'legal member rejected: {observed}'
    expected = {'EN': 'FProblem', 'EH': 'FHistoriesFromFacts', 'EC': 'C1Read',
                'EP': 'FPreparedPredicate', 'EF': 'PreflightReady', 'EL': 'LimitCertificate',
                'EB': 'FLegacyBridgeProblem', 'ED': 'FRoot'}
    if entry in expected:
        assert observed[0] == expected[entry], f'legal member must succeed: {observed}'
    else:
        assert not observed[0].startswith('NoDecision'), f'unexpected replay diagnostic: {observed}'


def assert_bad(value, exc, pair, entry):
    kind, reason, field, fields = diagnostic(value, exc)
    allowed = {pair.exception}
    if pair.exception == 'FIncomplete' and entry in ('EN', 'EF', 'EB'):
        allowed.add('NoDecision:incomplete')
    # A-20 explicitly allows a declared reference violation for non-null refs.
    reasons = {pair.reason}
    if pair.id == 'required-null':
        reasons.add('reference_kind')
    assert kind in allowed and reason in reasons, (
        f'{pair.rules}: expected {sorted(allowed)}/{sorted(reasons)}, got {(kind, reason, field)}')
    # Identity/missing-body diagnostics may identify the enclosing Point. There
    # is no uniquely specified leaf path for these in A-21.
    # A-21 fixes format and relevant fields, but defines no diagnostic object
    # namespace for relational comparisons (either endpoint can be reported).
    # Only the explicitly named outer correspondence/missing-key columns are
    # constrained here. This is independent of the implementation's path names.
    relevant = pair.fields if pair.rules[0] in ('A-03', 'A-04', 'A-20') else ()
    assert_pointer(field, fields, relevant=relevant)


class FaultReader(Reader):
    def __init__(self, ledger, point, fault):
        super().__init__(ledger)
        self.point, self.fault = point, fault

    def record(self, cid):
        if cid == self.point and self.fault == 'missing-body':
            raise KeyError(cid)
        return super().record(cid)

    def sealed_content(self, cid):
        if cid == self.point:
            if self.fault == 'missing-body':
                raise KeyError(cid)
            if self.fault == 'io':
                raise OSError('auth-test controlled I/O failure')
            if self.fault == 'seal':
                salt, payload = super().sealed_content(cid)
                return salt, Payload(media_type=payload.media_type, data=payload.data + b' ')
        return super().sealed_content(cid)


def add_unknown_cause(case, *, bad=False, use=False):
    # All records saved at the same later time; only r/use changes by one ns.
    case.clock.advance(100)
    request = case.decide('auth-cause-request', ContractRef('auth.request', '1'), {}, inputs=())
    job = case.put('auth-cause-job', JobOpened(decision=case.ref(request), step=0,
        content=Payload.json({}), contract=ContractRef('auth.job', '1')))
    attempt = case.put('auth-cause-attempt', AttemptStarted(job=case.ref(job),
        content=Payload.json({}), contract=ContractRef('auth.attempt', '1')))
    now = case.clock.mono_ns()
    observed = case.put('auth-notice', Observed(route='auth', content=Payload.json({}),
        contract=ContractRef('auth.unknown', '1'), caused_by=case.ref(attempt),
        received_ns=now if use else now-int(bad)))
    if use:
        case.decide('auth-use', ContractRef('auth.use', '1'), {}, inputs=(observed,))
    context_again(case)
    if use and bad:
        # Change the consumer event, keeping the notice's own r <= s valid.
        case = auth_copy_primary(case, edit=lambda k, r:
            replace(r, at=replace(r.at, mono_ns=now-1)) if k == 'auth-use' else r)
    return case


def add_sibling(case, bad):
    case.clock.advance(100)
    ancestors = case.ledger.heads()
    obs = case.observe('auth-sibling', ContractRef('auth.notice', '1'), {})
    case.put('auth-sibling-use', Decided(inputs=(case.ref(obs),),
        content=Payload.json({}), contract=ContractRef('auth.use', '1')),
        parents=ancestors if bad else case.ledger.heads())
    return context_again(case)


def prepare_pair(pair, entry, bad):
    """Return actual primary inputs, with exactly the specified semantic edit."""
    pid = pair.id
    computations = pid in ('result-acquisition', 'proof-acquisition', 'outer-result-about',
        'outer-proof-basis', 'proof-statement', 'adoption-sibling')
    observations = computations or pid in ('raw-acquisition', 'outer-inputs', 'job-step',
        'second-generator', 'measurement-generation', 'observation-bound') or pid.startswith(('window-', 'whole-window-'))
    case = base_case(entry, observations=observations,
        computation='unacquired' if computations else None)
    if entry == 'EP':
        add_predicate(case)

    if pid in ('seal', 'missing-body'):
        target = case.points['limit' if entry == 'EL' else 'model']
        if bad:
            case.reader = FaultReader(case.ledger, target, pid)
    elif pid == 'unknown-version':
        key = 'limit' if entry == 'EL' else 'model'
        if bad:
            case = auth_copy_primary(case, edit=lambda k, r: replace(r,
                body=replace(r.body, contract=ContractRef(r.body.contract.name, '999'))) if k == key else r)
    elif pid == 'fixed-duplicate':
        if bad:
            case.fixed_parents = case.fixed_parents + case.fixed_parents[:1]
    elif pid == 'used-sibling':
        case = add_sibling(case, bad)
    elif pid in ('cause-receipt', 'notification-use'):
        case = add_unknown_cause(case, bad=bad, use=pid == 'notification-use')
    elif pid in ('outer-inputs', 'outer-result-about', 'outer-proof-basis'):
        key, field = {'outer-inputs': ('measure-request-1', 'inputs'),
            'outer-result-about': ('compute-result', 'about'),
            'outer-proof-basis': ('compute-proof', 'basis')}[pid]
        case = auth_copy_primary(case, edit=lambda k, r:
            replace(r, body=replace(r.body, **{field: () if bad else tuple(reversed(getattr(r.body, field)))})) if k == key else r)
    elif pid == 'short-circuit':
        value = {'name': 'and', 'version': '1', 'args': {'terms': [
            {'name': 'constant', 'version': '1', 'args': {'value': False}},
            {'name': 'interval_compare', 'version': '1', 'args': {
                'left': {'key': 'not-a-CID'}, 'right': {'key': 'not-a-CID'},
                'relation': 'eq', 'provenance': []}} if bad else
            {'name': 'constant', 'version': '1', 'args': {'value': True}}]}}
        add_predicate(case, value)
        case.fixed_parents = tuple(sorted(set((*case.fixed_parents, case.points['auth-predicate']))))
    elif pid in ('raw-acquisition', 'result-acquisition', 'proof-acquisition', 'clock-notification', 'static-acquisition'):
        if pid == 'raw-acquisition':
            target = case.raw[0]
            boundary = case.ledger.record(target).body.received_ns
        elif pid in ('result-acquisition', 'proof-acquisition'):
            target = case.computation['result' if pid.startswith('result') else 'proof']
            boundary = case.ledger.record(case.points['computation-finish']).body.content.as_json()['reading']['time_ns']
        elif pid == 'static-acquisition':
            case.clock.advance(100)
            target = case.predict('auth-static', fc.MODEL_SOURCE, {'document': case.document})
            boundary = case.ledger.record(target).at.mono_ns
        else:
            case.clock.advance(100)
            target = case.reading('auth-clock-notice', time_ns=0)
            boundary = case.ledger.record(target).body.received_ns
        case.clock.advance(100)
        a = case.reading('auth-acquire-clock', time_ns=boundary-int(bad))
        case.acquire((target,), clock=a)
        context_again(case)
    elif pid in ('clock-reading-receipt', 'receipt-storage', 'required-null', 'required-missing'):
        case.clock.advance(100)
        point = case.reading('auth-reading')
        def edit(k, r):
            if k != 'auth-reading' or not bad:
                return r
            if pid == 'receipt-storage':
                return replace(r, body=replace(r.body, received_ns=r.at.mono_ns+1))
            value = deepcopy(r.body.content.as_json())
            if pid == 'clock-reading-receipt':
                value['reading']['time_ns'] += 1
            elif pid == 'required-null':
                value['source'] = None
            else:
                del value['source']
            return replace(r, body=replace(r.body, content=Payload.json(value)))
        context_again(case, events=(('clock', point),))
        case = auth_copy_primary(case, edit=edit)
    elif pid.startswith('window-'):
        branch = pid.removeprefix('window-')
        def edit(k, r):
            if k != 'raw-0':
                return r
            frame = deepcopy(r.body.content.as_json())
            interval = frame['measurement_interval']
            interval['end_ns'] = r.body.received_ns + int(bad)
            if branch == 'frame':
                return replace(r, body=replace(r.body, content=Payload.json(frame)))
            common = {'route_epoch': 'route-1', 'evidence': []}
            if branch == 'claim':
                value = dict(common, interval=interval, kind='closed', contract=plain(ContractRef('sui.f.finite_measurement', '1')))
            elif branch == 'gap':
                value = dict(common, interval=interval, sequence_range=[1, 2], reason='lost')
            else:
                value = dict(common, requested_interval=interval, reason='unavailable')
            return replace(r, body=replace(r.body, contract=fc.COVERAGE,
                content=Payload.json({'kind': branch, 'value': value})))
        # Coverage-only records do not claim a finite measurement Binding.
        if branch != 'frame':
            case = coverage_case(branch)
            def edit(k, r):
                if k != 'auth-coverage' or not bad:
                    return r
                value = deepcopy(r.body.content.as_json())
                value['value']['requested_interval' if branch == 'measurement_unavailable' else 'interval']['end_ns'] += 1
                return replace(r, body=replace(r.body, content=Payload.json(value)))
        case = auth_copy_primary(case, edit=edit)
        if entry == 'EP' and 'auth-predicate' not in case.points:
            add_predicate(case)
    elif pid in ('job-step', 'measurement-generation'):
        def edit(k, r):
            if pid == 'job-step' and k == 'measure-job-1' and bad:
                # Keep the Job's own outer/content correspondence valid;
                # isolate its disagreement with request/Binding (A-15).
                changed = content(r, step=1)
                return replace(changed, body=replace(changed.body, step=1))
            if pid == 'measurement-generation' and k == 'measure-attempt-1':
                return replace(r, at=replace(r.at, mono_ns=1))
            if pid == 'measurement-generation' and k == 'raw-0':
                value = deepcopy(r.body.content.as_json())
                value['actual_time']['value']['time_ns'] = 1-int(bad)
                value['measurement_interval']['start_ns'] = 0
                value['measurement_interval']['closure'] = '[start,end]'
                return replace(r, body=replace(r.body, content=Payload.json(value)))
            return r
        case = auth_copy_primary(case, edit=edit)
    elif pid.startswith('whole-window-'):
        kind = pid.removeprefix('whole-window-')
        case = FactsCase(finite_world('FA02')[0], name='auth-coverage-window')
        add_observations(case, closed=kind == 'closed')
        case.candidate(('Open', 'Closed'))
        case.context()
        if entry == 'EP':
            add_predicate(case)
        def edit(k, r):
            if k == 'raw-0':
                value = deepcopy(r.body.content.as_json())
                value['value']['interval']['start_ns'] = -int(bad)
                return replace(r, body=replace(r.body, content=Payload.json(value)))
            return r
        case = auth_copy_primary(case, edit=edit)
    elif pid == 'second-generator':
        case = FactsCase(finite_world('FA06')[0], name='auth-two-generators')
        add_observations(case, seqs=(1, 2))
        case.candidate(('Compute',))
        case.context()
        if entry == 'EP': add_predicate(case)
        first = case.ref(case.points['measure-attempt-1'])
        def edit(k, r):
            if k == 'measure-request-1': return content(r, step=1)
            if k == 'measure-job-1':
                changed = content(r, step=1)
                return replace(changed, body=replace(changed.body, step=1))
            if k == 'binding-0': return content(r, step=1)
            if k == 'binding-1' and bad:
                value = deepcopy(r.body.content.as_json())
                value['generated_by'].append(str(first))
                return replace(r, body=replace(r.body, content=Payload.json(value)))
            return r
        case = auth_copy_primary(case, edit=edit)
    elif pid == 'proof-statement':
        if bad:
            def edit(k, r):
                if k != 'compute-proof':
                    return r
                value = deepcopy(r.body.content.as_json())
                value['statement']['value']['result'] = value['statement']['value']['model']
                return replace(r, body=replace(r.body, content=Payload.json(value)))
            case = auth_copy_primary(case, edit=edit)
    elif pid == 'adoption-sibling':
        before = case.ledger.heads()
        case.acquire((case.computation['result'], case.computation['proof']),
                     clock=case.reading('auth-adoption-clock'))
        completion = case.computation['completed']
        case.put('auth-adopted', Decided(inputs=(case.ref(case.points['origin']), case.ref(completion)),
            content=Payload.json({'origin': case.points['origin'], 'previous': None, 'completion': completion}),
            contract=fc.KNOWLEDGE_ADOPTED), parents=before if bad else case.ledger.heads())
        context_again(case)
    elif pid.startswith('context-'):
        case.clock.advance(100)
        now = case.clock.mono_ns()
        if pid == 'context-order':
            low = case.reading('auth-low', time_ns=now-2)
            fact = case.observe('auth-fact', ContractRef('auth.fact', '1'), {})
            high = case.reading('auth-high', time_ns=now-1)
            context_again(case, events=(('clock', high if bad else low), ('fact', fact), ('clock', low if bad else high)))
        elif pid == 'context-o-j':
            context_again(case, observed_ns=now, judgment_ns=now-int(bad))
        elif pid == 'context-fact-bound':
            fact = case.observe('auth-fact', ContractRef('auth.fact', '1'), {})
            context_again(case, observed_ns=now-int(bad), judgment_ns=now, events=(('fact', fact),))
        else:
            context_again(case)
            if bad:
                def edit(k, r):
                    if k == 'observed_clock':
                        value = deepcopy(r.body.content.as_json())
                        value['reading']['run'] = str(Ref(RefKind.RUN, 'other-run'))
                        return replace(r, body=replace(r.body, content=Payload.json(value)))
                    return r
                case = auth_copy_primary(case, edit=edit)
    elif pid == 'observation-bound':
        now = case.ledger.record(case.raw[0]).body.received_ns
        context_again(case, observed_ns=now-int(bad), judgment_ns=case.clock.mono_ns())
    else:
        raise AssertionError('missing fixture for ' + pid)
    return case


def coverage_case(branch):
    if branch in ('claim', 'gap'):
        document = finite_world('FA02')[0]
        if branch == 'gap':
            for outcome in document['kernels'][0]['outcomes']:
                if outcome['evidence'] is not None:
                    outcome['evidence']['kind'] = 'gap'
        case = FactsCase(document, name='auth-coverage-'+branch)
        add_observations(case, closed=branch == 'claim')
        case.candidate(('Open', 'Closed'))
        case.context()
        if branch == 'gap':
            def edit(k, r):
                if k != 'raw-0': return r
                claim = r.body.content.as_json()['value']
                value = {'route_epoch': claim['route_epoch'], 'interval': claim['interval'],
                         'sequence_range': [1, 2], 'reason': 'no_arrival', 'evidence': claim['evidence']}
                return replace(r, body=replace(r.body, content=Payload.json({'kind': 'gap', 'value': value})))
            case = auth_copy_primary(case, edit=edit)
        case.points['auth-coverage'] = case.points['raw-0']
        return case
    case = finite_case(observations=True)
    case.clock.advance(100)
    now = case.clock.mono_ns()
    interval = {'clock': str(case.clock.run), 'start_ns': 0, 'end_ns': now, 'closure': '[start,end]'}
    common = {'route_epoch': 'route-1', 'evidence': []}
    if branch == 'claim':
        value = dict(common, interval=interval, kind='closed', contract=plain(ContractRef('sui.f.finite_measurement', '1')))
    elif branch == 'gap':
        value = dict(common, interval=interval, sequence_range=[0, 1], reason='lost')
    elif branch == 'measurement_unavailable':
        value = dict(common, requested_interval=interval, reason='unavailable')
    else:
        value = dict(common, interval=interval, missing_contracts=[])
    case.observe('auth-coverage', fc.COVERAGE, {'kind': branch, 'value': value}, route='route-1')
    return context_again(case)


def entry_pair(pair, entry, bad):
    if entry == 'ED':
        # Prepare a clean fixed problem first. Then add a disjoint, primary
        # closure containing the test subject. Old j does not bound this suffix.
        # Append the existing clean problem ancestry into the subject ledger.
        # Both fixtures use the same identities, so use one prefix and append
        # test records as the suffix below instead of merging distinct Records.
        if pair.id in ('seal', 'missing-body'):
            original = finite_case()
            prepared = invoke('EN', original)
            subject = original
            draw = add_draw(subject, prepared.value.problem_key)
            if bad:
                subject.reader = FaultReader(subject.ledger, draw, pair.id)
            return invoke('ED', subject, prepared=prepared, draw=draw)
        # A clean problem from exactly this fixture's earlier prefix is needed;
        # use preflight-free prefix records before adding the subject.
        # prepare subject itself only for its good member, never to authorize
        # malformed suffixes. The suffix-copy helper below retains clean prefix.
        return draw_suffix(pair, bad)
    if entry == 'ER':
        good = prepare_pair(pair, 'EN', False)
        saved = invoke('EN', good).canonical_bytes
        current = prepare_pair(pair, 'EN', bad)
        return invoke('ER', current, saved=saved)
    return invoke(entry, prepare_pair(pair, entry, bad))


def draw_suffix(pair, bad, *, subject=None, identity_fault=None, retain_source=False):
    # Capture a clean prefix, then keep its exact CID graph and append an
    # independent test closure under the draw. No fake FProblem is constructed.
    if subject is None:
        subject = prepare_pair(pair, 'EN', bad)
    declared_clock = subject.ledger.record(subject.points['clock_source']).body.content.as_json().get('measurement')
    prefix = FactsCase(finite_world('FA06')[0], name='auth-prefix',
                      clock_contract=CLOCK if declared_clock is None else ContractRef(**declared_clock))
    prefix.candidate(('Compute',))
    prefix.context()
    prepared = invoke('EN', prefix)
    # The suffix is a sibling branch until draw joins it. Its timestamps need
    # not follow the prefix's *storage* time; only actual parent edges matter.
    # Rename source Record IDs to avoid collisions while retaining typed Refs.
    # Done with public Record/Payload/append, never by editing an issued handle.
    roots = ('boot',) if retain_source else ('boot', 'clock_source')
    mapping = {subject.points[k]: prefix.points[k] for k in roots}
    refs = {str(subject.ledger.record(e.cid).id): str(Ref(subject.ledger.record(e.cid).id.kind,
            'suffix-' + subject.ledger.record(e.cid).id.value)) for e in subject.ledger.entries()}
    for key in roots:
        refs[str(subject.ref(subject.points[key]))] = str(prefix.ref(prefix.points[key]))
    ref_values = {str(subject.ledger.record(e.cid).id):
                  (prefix.ref(prefix.points['boot']) if e.cid == subject.points['boot'] else
                    prefix.ref(prefix.points['clock_source']) if not retain_source and e.cid == subject.points['clock_source'] else
                   Ref(subject.ledger.record(e.cid).id.kind, 'suffix-'+subject.ledger.record(e.cid).id.value))
                  for e in subject.ledger.entries()}
    def convert(v):
        if isinstance(v, str): return mapping.get(v, refs.get(v, v))
        if isinstance(v, list): return [convert(x) for x in v]
        if isinstance(v, dict): return {k: convert(x) for k, x in v.items()}
        return v
    pending = {e.cid: e for e in subject.ledger.entries() if e.cid not in mapping}
    max_seq = max(e.at.seq for e in (prefix.ledger.record(x.cid) for x in prefix.ledger.entries()))
    max_mono = prefix.clock.mono_ns()
    while pending:
        ready = [e for e in pending.values() if all(p in mapping for p in e.parents)]
        assert ready
        for e in sorted(ready, key=lambda x: subject.ledger.record(x.cid).at.seq):
            rec = subject.ledger.record(e.cid)
            b = rec.body
            kw = {'content': Payload.json(convert(b.content.as_json()))}
            for name in ('caused_by', 'decision', 'job', 'target', 'decided_in', 'supersedes', 'via'):
                old = getattr(b, name, None)
                if isinstance(old, Ref) and str(old) in refs:
                    kw[name] = ref_values[str(old)]
            for name in ('inputs', 'basis', 'about'):
                if hasattr(b, name):
                    kw[name] = tuple(ref_values[str(x)] if str(x) in refs else x for x in getattr(b, name))
            # Same declared M, with separate origin and valid later sequence.
            at = replace(rec.at, run=prefix.clock.run, seq=rec.at.seq+1000)
            max_seq, max_mono = max(max_seq, at.seq), max(max_mono, at.mono_ns)
            run_text = str(rec.at.run)
            payload = canonical(kw['content'].as_json()).decode().replace(run_text, str(at.run))
            kw['content'] = Payload.json(json.loads(payload))
            renamed = replace(rec, id=Ref(rec.id.kind, 'suffix-'+rec.id.value), at=at, body=replace(b, **kw))
            copied = prefix.ledger.append(renamed, frozenset(mapping[p] for p in e.parents))
            mapping[e.cid] = copied.cid
            del pending[e.cid]
    now = max_mono + 1
    # A non-event leaf is not a ledger head. Make the suffix's selected scope
    # explicit through a real consumer's typed inputs, retaining the leaf's
    # actual event parents instead of making the leaf an event parent itself.
    frontier_refs = tuple(dict.fromkeys(prefix.ledger.record(mapping[p]).id
                                       for p in subject.fixed_parents))
    scope_use = Record(id=Ref(RefKind.DECISION, 'auth-suffix-scope'),
        at=Instant(run=prefix.clock.run, run_index=0, seq=max_seq+1, mono_ns=now, wall_ns=0),
        writer=Role.MODEL, producer=PRODUCER,
        body=Decided(inputs=frontier_refs, content=Payload.json({}),
                     contract=ContractRef('auth.scope_use', '1')))
    prefix.ledger.append(scope_use, prefix.ledger.heads())
    draw_body = Observed(route='draw', contract=fc.DRAW_FACT, received_ns=now,
        content=Payload.json({'generator': {'name': 'sui.f.scripted_draw', 'version': '1'},
            'stream_id': 'auth-selection', 'request': {'purpose': 'selection',
                'context_key': prepared.value.problem_key, 'ordinal': 0,
                'law': {'name': 'uniform_unit', 'version': '1'}, 'args': {}}, 'value': {'u': [1, 2]}}))
    record = Record(id=Ref(RefKind.OBSERVATION, 'auth-draw-suffix'),
        at=Instant(run=prefix.clock.run, run_index=0, seq=max_seq+2, mono_ns=now, wall_ns=0),
        writer=Role.MEMBRANE, producer=PRODUCER, body=draw_body)
    draw = prefix.ledger.append(record, prefix.ledger.heads()).cid
    if identity_fault is not None:
        point, field = identity_fault
        prefix.reader = RecordColumnReader(prefix.ledger, mapping[point], field)
    return invoke('ED', prefix, prepared=prepared, draw=draw)


# Replay integrity has its own pairs below. Rebuilding a malformed graph changes
# CIDs and would test missing historical input, not the original temporal rule.
EXECUTABLE_PAIRS = PAIRS
DEFERRED_PAIR_ENTRIES = {}
DEFERRED_PAIR_ENTRIES.update({('receipt-storage', entry):
    '公開の構築で拒まれる: Record raises ValueError for r>s; constructor pair below; no bypass'
    for entry in CONTEXT})
PAIR_PARAMS = tuple(pytest.param(p, entry, bad,
    id=f'{p.rules[0]}__{p.id}__{entry}__{"bad" if bad else "good"}')
    for p in EXECUTABLE_PAIRS for entry in p.entries
    if entry != 'ER' and (p.id, entry) not in DEFERRED_PAIR_ENTRIES for bad in (False, True))


@pytest.mark.parametrize('pair,entry,bad', PAIR_PARAMS)
def test_auth_pair(pair, entry, bad, record_property):
    record_property('rules', ','.join(pair.rules))
    record_property('entry', entry)
    record_property('stage', pair.stage)
    record_property('member', 'bad' if bad else 'good')
    value, exc = call_observed(lambda: entry_pair(pair, entry, bad))
    if bad:
        assert_bad(value, exc, pair, entry)
    else:
        assert_legal(value, exc, entry)


def test_inventory_is_spec_based_and_unique():
    assert len({row.id for row in INVENTORY}) == len(INVENTORY)
    assert set(BODY_FIELDS) == {'Observed', 'Decided', 'JobOpened', 'AttemptStarted',
                              'Intention', 'Prediction', 'Interpretation', 'Preference'}
    # Read only public class field annotations; never read function bodies.
    source = Path(__file__).parents[1] / 'src/sui/records.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    declared = {node.name: {n.target.id for n in node.body if isinstance(n, ast.AnnAssign)}
                for node in tree.body if isinstance(node, ast.ClassDef) and node.name in BODY_FIELDS}
    expected = {name: {s.rstrip('?').removesuffix('[]') for s in fields.split()}
                for name, fields in BODY_FIELDS.items()}
    assert declared == expected


def test_public_compiler_version_matches_current_contract():
    # E-05 names the emitted compiler contract, not its Python constant name.
    assert emitted_compiler_contract() == {'name': 'sui.f.prepare_world', 'version': '3'}


# The selector map is merely a material recipe. Its keys never define the
# inventory denominator, and unmatched independent rows are reported below.
SPECIMENS = {
    'model_source': ('finite', 'model', 'default'),
    'candidate_declaration': ('finite', 'candidates', 'default'),
    'knowledge_origin': ('finite', 'origin', 'default'),
    'content_acquired': ('computation', '@acquisition', 'default'),
    'computation_requested': ('computation', 'compute-request', 'belief'),
    'computation_result': ('computation', 'compute-result', 'default'),
    'computation_proof': ('computation', 'compute-proof', 'normalization'),
    'computation_completed': ('computation', 'compute-completed', 'default'),
    'knowledge_adopted': ('computation', 'adopted', 'default'),
    'clock_reading': ('finite', 'observed_clock', 'default'),
    'context_observed': ('finite', 'context', 'empty'),
    'measurement_requested': ('raw', 'measure-request-1', 'default'),
    'measurement_job': ('raw', 'measure-job-1', 'default'),
    'observation_plan': ('raw', 'plan', 'default'),
    'observation_binding': ('raw', 'binding-0', 'default'),
    'measurement': ('raw', 'raw-0', 'clock/value'),
    'route_config': ('raw', 'route', 'bootstrap'),
    'sui.clock.source': ('finite', 'clock_source', 'default'),
    'sui.s4.boot': ('finite', 'boot', 'default'),
    'sui.s4b.rate_report': ('c1', 'read-report', 'count'),
    'sui.s4b.rate_job': ('c1', 'read-job', 'default'),
    'style': ('style', 'preference-0', 'default'),
    'sui.s4d.preference': ('legacy-style', 'preference-0', 'default'),
    'predicate': ('predicate', 'auth-predicate', 'default'),
    'quantity_declaration': ('quantity', 'auth-quantity', 'rational_constant'),
    'limit_declaration': ('limit', 'limit', 'blank'),
    'draw_fact': ('draw', '@draw', 'selection'),
}


def short_contract(name):
    return name.removeprefix('sui.f.')


def specimen(row, entry=None):
    if entry == 'EB' and row.contract in ('sui.s4b.rate_job', 'sui.s4b.rate_report'):
        subject, key = specimen(row, 'EF')
        return append_independent_primary_closure(base_case('EB'), subject, key)
    if entry == 'EL' and row.contract == 'sui.f.predicate':
        case = finite_case()
        add_predicate(case)
        declaration = assemble_limit()
        case.predict('limit', fc.LIMIT_DECLARATION,
            declaration.ledger.record(declaration.points['limit']).body.content.as_json(),
            basis=(case.points['auth-predicate'],))
        return refresh(case), 'auth-predicate'
    if entry == 'ED' and row.contract == 'sui.f.limit_declaration':
        case = finite_case()
        declaration = assemble_limit(both=row.branch == 'prefix_log_loss')
        case.predict('limit', fc.LIMIT_DECLARATION,
            declaration.ledger.record(declaration.points['limit']).body.content.as_json())
        return refresh(case), 'limit'
    if entry in ('EC', 'EB') and short_contract(row.contract) in (
            'draw_fact', 'style', 'sui.s4d.preference'):
        case = base_case(entry)
        name = short_contract(row.contract)
        if name == 'draw_fact':
            point = add_draw(case, 'sha256:'+'1'*64,
                purpose='selection' if row.branch == 'contract' else row.branch)
            key = next(k for k, p in case.points.items() if p == point)
        else:
            value = ({'kind': 'style', 'scope': {'name': 'one_step' if entry == 'EB' else 'unbounded_total', 'version': '1', 'H_ns': None},
                      'gamma': [1, 1]} if name == 'style' else
                     {'kind': 'style', 'H_ns': None, 'gamma': 1.0})
            key = 'auth-unused-preference'
            case.put(key, Preference(basis=(), content=Payload.json(value),
                contract=ContractRef(row.contract, row.version)))
            case.preferences.append(case.points[key])
        context_again(case)
        return case, key
    extra = extra_specimen(row, entry)
    if extra is not None:
        return extra
    if row.contract == 'sui.f.coverage':
        branch = 'claim' if row.branch == 'contract' else row.branch
        case, key = coverage_case(branch), 'auth-coverage'
        return case, key
    profile, key, _ = SPECIMENS[short_contract(row.contract)]
    if profile == 'c1':
        case = assemble_c1()
    elif profile == 'limit':
        case = assemble_limit()
        refresh(case)
    else:
        case = finite_case(observations=profile == 'raw',
                           computation='adopted' if profile == 'computation' else None)
        if key == '@acquisition':
            key = next(k for k in case.points if k.startswith('acquisition-'))
        if profile == 'style':
            case.style()
            context_again(case)
        elif profile == 'legacy-style':
            pref = case.preference({'kind': 'style', 'H_ns': None, 'gamma': 1.0})
            case.scope = f.EvaluationScope(name='one_step', version='1', H_ns=None, source=case.ref(pref))
            context_again(case)
        elif profile == 'predicate':
            add_predicate(case)
        elif profile == 'quantity':
            case.predict(key, fc.QUANTITY_DECLARATION,
                {'kind': 'rational_constant', 'value': [1, 1], 'unit': 'nat', 'provenance': []})
            refresh(case)
        elif profile == 'draw':
            purpose = 'selection' if row.branch == 'contract' else row.branch
            point = add_draw(case, 'sha256:'+'1'*64, purpose=purpose)
            key = next(k for k, p in case.points.items() if p == point)
            context_again(case)
        elif short_contract(row.contract) == 'context_observed' and row.branch in ('fact', 'clock'):
            point = case.reading('auth-check') if row.branch == 'clock' else case.points['origin']
            context_again(case, events=((row.branch, point),))
    if entry in ('EC', 'EB') and short_contract(row.contract) in (
            'model_source', 'knowledge_origin', 'clock_reading', 'context_observed',
            'sui.clock.source', 'sui.s4.boot'):
        case = base_case(entry)
        if short_contract(row.contract) == 'context_observed' and row.branch in ('fact', 'clock'):
            point = case.reading('auth-check') if row.branch == 'clock' else case.points['origin']
            context_again(case, events=((row.branch, point),))
    return case, key


def append_independent_primary_closure(case, subject, key):
    """Keep a second run/origin separate; explicitly authenticate its records.

    Only real public records are appended. The selected legacy request retains
    its original model/context; C1 records do not become legacy measurements.
    """
    mapping = {}
    def remap(value):
        if isinstance(value, str): return mapping.get(value, value)
        if isinstance(value, list): return [remap(v) for v in value]
        if isinstance(value, dict): return {k: remap(v) for k, v in value.items()}
        return value
    pending = {e.cid: e for e in subject.ledger.entries()}
    while pending:
        ready = [e for e in pending.values() if all(p in mapping for p in e.parents)]
        assert ready, 'fixture primary DAG must be acyclic'
        for e in sorted(ready, key=lambda e: subject.ledger.record(e.cid).at.seq):
            record = subject.ledger.record(e.cid)
            record = replace(record, body=replace(record.body,
                content=Payload.json(remap(record.body.content.as_json()))))
            mapping[e.cid] = case.ledger.append(record, frozenset(mapping[p] for p in e.parents)).cid
            del pending[e.cid]
    case.points['auth-independent-primary'] = mapping[subject.points[key]]
    refresh(case)
    return case, 'auth-independent-primary'


def extra_specimen(row, entry=None):
    """Selected branches described by V-08..10, using public raw records.

    Intrinsic-only samples do not invent finite numeric Bindings for unknown
    values, nor a finite-update proof for the query/certificate vocabulary.
    """
    name = short_contract(row.contract)
    if name == 'computation_requested' and row.branch in ('query', 'certificate'):
        # Request-only stage: finite_update supplies closed args/output types;
        # no result, normalization proof or adoption is re-labelled as query.
        case = finite_case(observations=True)
        inputs = tuple(dict.fromkeys(case.points[k] for k in (
            'origin', 'model', 'boot', 'clock_source', 'route',
            'plan', 'raw-0', 'binding-0', 'measure-request-1',
            'measure-job-1', 'measure-attempt-1')))
        case.acquire(inputs, clock=case.reading('auth-request-inputs-acquired'))
        case.decide('auth-request-only', fc.COMPUTATION_REQUESTED,
            {'origin': case.points['origin'], 'purpose': row.branch,
             'method': plain(fc.FINITE_UPDATE),
             'args': {'model': case.points['model'], 'previous_result': None,
                      'observations': list(case.bindings)},
             'inputs': list(inputs), 'algorithm_draws': [],
             'output_contract': plain(fc.FINITE_UPDATE_RESULT)}, inputs=inputs)
        return context_again(case), 'auth-request-only'
    if name == 'measurement' and row.branch in ('unavailable-time', 'unavailable-value', 'gap'):
        case = finite_case(observations=True)
        def edit(k, r):
            if k != 'raw-0': return r
            value = deepcopy(r.body.content.as_json())
            if row.branch.startswith('unavailable'):
                field = 'actual_time' if row.branch == 'unavailable-time' else 'value'
                value[field] = {'kind': 'unavailable', 'value': {'reason': 'not-measured', 'basis': []}}
            else:
                value['gap'] = {'route_epoch': value['route_epoch'], 'sequence_range': [0, 1],
                    'interval': deepcopy(value['measurement_interval']), 'reason': 'lost', 'evidence': []}
            return replace(r, body=replace(r.body, content=Payload.json(value)))
        return auth_copy_primary(case, edit=edit), 'raw-0'
    if name == 'observation_binding' and row.field.startswith('derived_from[].'):
        case = FactsCase(finite_world('FA06')[0], name='auth-derived')
        add_observations(case, seqs=(1, 2))
        case.candidate(('Compute',)); case.context()
        origin = case.ledger.record(case.raw[0]).body.content.as_json()['measurement_id']
        return auth_copy_primary(case, edit=lambda k, r: content(r, derived_from=[origin]) if k == 'binding-1' else r), 'binding-1'
    if name == 'route_config' and row.branch in ('selected', 'unavailable-effective'):
        case = base_case(entry) if entry in ('EC', 'EB') else finite_case()
        now = case.clock.mono_ns()
        decision = execution = None
        if row.branch == 'selected':
            d = case.decide('auth-route-decision', ContractRef('auth.route-decision', '1'), {}, inputs=())
            j = case.put('auth-route-job', JobOpened(decision=case.ref(d), step=0,
                content=Payload.json({}), contract=ContractRef('auth.route-job', '1')))
            a = case.put('auth-route-attempt', AttemptStarted(job=case.ref(j),
                content=Payload.json({}), contract=ContractRef('auth.route-attempt', '1')))
            decision, execution = str(case.ref(d)), str(case.ref(a))
        value = {'config': {'route_epoch': 'auth-unused-route', 'origin': 'selected' if decision else 'bootstrap',
            'version': '1', 'sampling_contract': plain(ContractRef('sui.f.finite_measurement', '1')),
            'clock_contract': deepcopy(case.ledger.record(case.points['clock_source']).body.content.as_json()['measurement']),
            'loss_contract': plain(ContractRef('auth.loss', '1')),
            'args': {}, 'decision': decision, 'execution': execution},
            'effective_from': {'kind': 'clock', 'value': {'run': str(case.clock.run), 'time_ns': now}}
                if decision else {'kind': 'unavailable', 'value': {'reason': 'unknown', 'basis': []}},
            'execution': execution, 'evidence': []}
        case.observe('auth-selected-route', fc.ROUTE_CONFIG, value)
        context_again(case)
        return case, 'auth-selected-route'
    if name == 'route_config' and entry in ('EC', 'EB'):
        # A separate, unused route is in the explicit authentication closure;
        # it does not replace the C1 or legacy consumer's numerical input.
        selected = replace(row, branch='selected')
        case, key = extra_specimen(selected, entry)
        def bootstrap(k, r):
            if k != key: return r
            value = deepcopy(r.body.content.as_json())
            value['config'].update(origin='bootstrap', decision=None, execution=None)
            value['execution'] = None
            return replace(r, body=replace(r.body, content=Payload.json(value)))
        return auth_copy_primary(case, edit=bootstrap), key
    if name == 'sui.s4b.rate_report' and row.branch in ('constant', 'wait'):
        case = assemble_c1()
        def edit(k, r):
            if k == 'read-request': return content(r, action='wait')
            if k == 'read-job':
                value = deepcopy(r.body.content.as_json())
                value.update(choice='wait', action='wait')
                value['execution']['completion_process'] = 'wait-done'
                return replace(r, body=replace(r.body, content=Payload.json(value)))
            return content(r, channel='wait-report', experiment='wait', window_start_ns=None,
                window_end_ns=None, arrival_count=None, outcome=None) if k == 'read-report' else r
        return auth_copy_primary(case, edit=edit), 'read-report'
    if name == 'sui.s4b.rate_arrival':
        case = base_case(entry) if entry in ('EC', 'EB') else assemble_c1()
        case.observe('auth-arrival', ContractRef('sui.s4b.rate_arrival', '1'),
            {'process': 'arrival-process', 'mark': None, 'event_ns': case.clock.mono_ns()}, route='c1')
        return context_again(case), 'auth-arrival'
    if name == 'limit_declaration' and row.branch == 'prefix_log_loss':
        case = assemble_limit(both=True)
        return refresh(case), 'limit'
    if name == 'math_artifact':
        case = finite_case()
        issued = invoke('EN', case)
        wire = json.loads(issued.canonical_bytes)
        # facts + prepare/budget belongs to both preserved envelope versions.
        wire['contract']['version'] = row.version
        case.predict('auth-artifact', ContractRef('sui.f.math_artifact', row.version), wire)
        return refresh(case), 'auth-artifact'
    if name == 'quantity_declaration' and row.branch == 'evaluation':
        case = FactsCase(finite_world('FA08')[0], name='auth-quantity-evaluation')
        case.candidate(('Q', 'M')); case.context()
        prepared = invoke('EN', case)
        draw = add_draw(case, prepared.value.problem_key)
        root = invoke('ED', case, prepared=prepared, draw=draw)
        evaluation = f.evaluate_f_recursive(root.value, budget=BUDGET)
        artifact = case.predict('auth-quantity-artifact', fc.MATH_ARTIFACT_V2,
            json.loads(ff.f_math_json(evaluation)))
        case.predict('auth-quantity', fc.QUANTITY_DECLARATION,
            {'kind': 'evaluation', 'result': artifact, 'field': 'Z', 'candidate': None}, basis=(artifact,))
        return context_again(case), 'auth-quantity'
    return None


def path_parts(path):
    return tuple(x for segment in path.split('.') for x in
                 ((segment[:-2], 0) if segment.endswith('[]') else (segment,)))


def remove_field(value, path):
    parts = list(path_parts(path))
    # A [] at the leaf means the field itself, not removal of an element.
    if parts[-1] == 0:
        parts.pop()
    cursor = value
    for part in parts[:-1]:
        cursor = cursor[part]
    del cursor[parts[-1]]


def field_available(row):
    # Decisions here are about declared fixture shape, never observed behavior.
    name = short_contract(row.contract)
    if name == 'computation_requested' and row.branch in ('query', 'certificate'):
        return True
    if name in ('math_artifact', 'sui.s4b.rate_arrival'):
        return True
    if name == 'quantity_declaration' and row.branch == 'evaluation':
        return True
    if name == 'measurement' and row.branch in ('unavailable-time', 'unavailable-value', 'gap'):
        return True
    if name == 'route_config' and row.branch in ('selected', 'unavailable-effective'):
        return True
    if name == 'sui.s4b.rate_report' and row.branch in ('constant', 'wait'):
        return True
    if name == 'limit_declaration' and row.branch == 'prefix_log_loss':
        return True
    if name == 'coverage':
        return True
    if name not in SPECIMENS:
        return False
    if row.branch not in (SPECIMENS[name][2], 'contract') and name not in ('draw_fact', 'context_observed'):
        return False
    # Empty legal sequences do not have active element fields in these samples.
    if row.field.startswith(('derived_from[].', 'slots[].')) and name == 'observation_binding':
        return True
    return True


SHAPE_ALL_ROWS = tuple(row for row in FIELD_TARGETS if row.contract != 'Record'
                   and not next((c.exclusion for c in CONTRACTS if c.name == row.contract and c.version == row.version), '')
                   and field_available(row))
SHAPE_ROWS = tuple({presence_group(row): row for row in reversed(SHAPE_ALL_ROWS)}.values())


def shape_entries(row):
    # Required-record authentication (EF) plus its independent actual consumer.
    # The remaining listed entrances are obligations reported by coverage_report.
    name = short_contract(row.contract)
    primary = 'EC' if name.startswith('sui.s4b.') else 'EL' if name == 'limit_declaration' else 'EH'
    if name in ('candidate_declaration', 'style', 'sui.s4d.preference'):
        primary = 'EN'
    if name in ('predicate', 'quantity_declaration'):
        primary = 'EF'  # quantity K-use is covered separately, not invented here.
    if name == 'draw_fact': primary = 'EF'
    if name == 'coverage' and row.branch in ('measurement_unavailable', 'coverage_unproved'):
        primary = 'EF'  # no numeric observation is fabricated from an unproved window
    result = set(('EF', primary))
    if name in ('model_source', 'knowledge_origin', 'clock_reading', 'context_observed', 'sui.clock.source', 'sui.s4.boot'):
        result.update(('EN', 'EH', 'EP', 'EC', 'EB'))
    elif not name.startswith('sui.s4b.') and name != 'limit_declaration':
        result.update(e for e in ('EN', 'EH', 'EP') if e in row.entries)
    if name not in ('sui.clock.source', 'sui.s4.boot', 'limit_declaration'):
        result.add('ED')
    if name == 'coverage' and row.branch in ('measurement_unavailable', 'coverage_unproved'):
        result = {'EF'}
    if (name == 'measurement' and row.branch in ('unavailable-time', 'unavailable-value', 'gap') or
        name == 'observation_binding' and row.field.startswith('derived_from[].') or
        name == 'sui.s4b.rate_report' and row.branch in ('constant', 'wait') or
        name == 'sui.s4b.rate_arrival'):
        result = {'EF', 'ED'}
    # Each entry remains independent; only redundant field-presence columns
    # within that entry are folded. These branches have explicit raw specimens.
    if name in ('measurement', 'observation_binding', 'coverage'):
        result.update(('EN', 'EH', 'EP', 'ED'))
    if name in ('route_config', 'draw_fact', 'style', 'sui.s4d.preference', 'sui.s4b.rate_arrival'):
        result.update(('EC', 'EB'))
    if name == 'sui.s4b.rate_report': result.add('EC')
    if name in ('sui.s4b.rate_report', 'sui.s4b.rate_job'): result.add('EB')
    if name == 'sui.clock.source': result.add('ED')
    if name == 'limit_declaration': result.add('ED')
    if name == 'predicate': result.add('EL')
    result.add('ER')
    return tuple(e for e in ALL_ENTRIES if e in result and e in row.entries)


def shape_parameters():
    # The identical legal graph is executed once per contract/branch/entry.
    # Every distinct negative representative still has an assertion of its own.
    legal_seen = set()
    for row in SHAPE_ROWS:
        for entry in shape_entries(row):
            legal = (row.contract, row.version, row.branch, entry)
            members = (True,) if legal in legal_seen else (False, True)
            legal_seen.add(legal)
            for bad in members:
                yield pytest.param(row, entry, bad,
                    id=f'{"V-08" if row.field == "$contract" else "A-20"}__{row.id}__{entry}__{"bad" if bad else "good"}')


SHAPE_PARAMS = tuple(shape_parameters())


def replay_with_primary_edit(saved, case, *, remap=None):
    """E-06: authentication precedes comparison of the saved claim.

    Remap real primary CIDs in a *structural envelope*, never fake an issued
    handle or forge a Record. A bad graph may also make the old claim stale;
    its intrinsic error must be diagnosed first. E-05:470 rejects unpublished
    compiler/1-2; those drafts cannot stand in for the compiler/3 audit.
    """
    value = json.loads(saved)
    if value['compiler'] != {'name': 'sui.f.prepare_world', 'version': '3'}:
        pytest.skip('not_run: current public issuer does not yet emit compiler/3; legacy semantics are not a substitute')
    def walk(v):
        if isinstance(v, str): return (remap or {}).get(v, v)
        if isinstance(v, list): return [walk(x) for x in v]
        if isinstance(v, dict): return {k: walk(x) for k, x in v.items()}
        return v
    value = walk(value)
    primary = value['input']['value']
    if value['input']['kind'] in ('facts', 'preflight', 'legacy_bridge'):
        # CIDs changed by a legal Ledger.append graph copy have a new lexical
        # order. Use the explicitly authored current frontier; preserve an
        # intentionally duplicated frontier for the A-02 negative member.
        primary['fixed_parents'] = list(case.fixed_parents)
    if value['input']['kind'] == 'preflight':
        primary['required_records'] = sorted(primary['required_records'])
    return invoke('ER', case, saved=canonical(value))


@lru_cache(maxsize=1)
def emitted_compiler_contract():
    # Probe a real public issuance once per worker. No saved handle is forged,
    # and retaining an old public constant does not falsely disable new tests.
    issued = invoke('EF', finite_case())
    return json.loads(issued.canonical_bytes)['compiler']


def require_current_replay_compiler():
    if emitted_compiler_contract() != {'name': 'sui.f.prepare_world', 'version': '3'}:
        pytest.skip('not_run: public issuer does not emit compiler/3; old compiler semantics are preserved')


@pytest.mark.parametrize('row,entry,bad', SHAPE_PARAMS)
def test_inventory_field_pair(row, entry, bad, record_property):
    rule = 'V-08' if row.field == '$contract' else 'A-20'
    record_property('rules', ','.join((rule, 'A-01', 'A-21', 'V-03')))
    record_property('entry', entry)
    record_property('target', row.id)
    record_property('member', 'bad' if bad else 'good')
    if entry == 'ER': require_current_replay_compiler()
    case, key = specimen(row, 'EF' if entry == 'ER' else entry)
    case.fixed_parents = tuple(sorted(set((*case.fixed_parents, case.points[key]))))
    saved = invoke('EF', case).canonical_bytes if entry == 'ER' else None
    if bad:
        def edit(k, r):
            if k != key:
                return r
            if row.field == '$contract':
                return replace(r, body=replace(r.body,
                    contract=ContractRef(r.body.contract.name, '999')))
            value = deepcopy(r.body.content.as_json())
            remove_field(value, row.field)
            return replace(r, body=replace(r.body, content=Payload.json(value)))
        case = auth_copy_primary(case, edit=edit)
    if entry == 'EP' and 'auth-predicate' not in case.points:
        add_predicate(case)
    case.fixed_parents = tuple(sorted(set((*case.fixed_parents, case.points[key]))))
    value, exc = call_observed(lambda: replay_with_primary_edit(saved, case,
        remap=getattr(case, 'auth_point_map', {}) if bad else {}) if entry == 'ER' else
        draw_suffix(None, False, subject=case, retain_source=row.contract == 'sui.clock.source')
            if entry == 'ED' else invoke(entry, case))
    if not bad:
        if row.contract == 'sui.f.style' and entry == 'EB':
            # A-21 + E-08: a well-formed new FStyle has no declared meaning in
            # the old pure calculation. Neither silently ignore nor translate it.
            assert exc is None, diagnostic(value, exc)
            assert diagnostic(value, exc)[:3] == (
                'NoDecision:rejected', 'missing_contract', '/preferences')
        elif row.contract == 'sui.f.measurement' and row.branch in ('unavailable-time', 'unavailable-value') and entry in ('EN', 'EH', 'EP'):
            # This specimen has a numeric Binding. A-20 permits Unavailable,
            # but this particular use needs its value/time (A-21 shortage).
            kind, reason, field, fields = diagnostic(value, exc)
            assert kind in ('FIncomplete', 'NoDecision:incomplete') and reason == 'certificate_incomplete', diagnostic(value, exc)
            assert_pointer(field, fields)
        else:
            assert_legal(value, exc, entry)
        return
    kind, reason, field, fields = diagnostic(value, exc)
    expected_reason = 'unknown_version' if row.field == '$contract' else 'shape'
    assert (kind, reason) == ('FInputError', expected_reason), (
        f'{rule}: {row.id}: expected FInputError/{expected_reason}, got {(kind, reason, field)}')
    # Missing nested keys may identify their containing object; the contract
    # does not fix the prefix. Root is a valid JSON Pointer by A-21.
    assert_pointer(field, fields)


def coverage_report():
    """Auditable plan, not a count of passing assertions.

    A represented field does not imply all rules on that field. The relation
    matrix stays separate, and a compiler/3 prerequisite is always explicit.
    """
    shapes = {(presence_group(r), e): r.id for r in SHAPE_ROWS for e in shape_entries(r)}
    identities = {(identity_group(p.values[0]), p.values[1]): p.values[0].id
                  for p in IDENTITY_PARAMS if p.values[2]}
    dispositions = []
    for row in FIELD_TARGETS:
        for entry in row.entries:
            rule = 'A-01' if row.contract == 'Record' else 'V-08' if row.field == '$contract' else 'A-20'
            item = dict(target=row.id, rule=rule, entry=entry, status='pending', representative=None, reason='not yet represented at this entry')
            if row.contract == 'Record':
                if row.field in ('writer', 'schema', 'status'):
                    name, exception, _ = CONSTRUCTION_BOUNDARIES[row.field]
                    item.update(status='constructor', representative='test_public_record_construction_boundary['+row.field+']',
                        reason=f'公開の構築で拒まれる: {name} / {exception}; no entry bypass')
                else:
                    rep = identities.get((identity_group(row), entry))
                    if rep:
                        item.update(status='direct' if row.id == rep else 'represented', representative=rep,
                            reason='same entry + public field kind/Body; A-01 only, not presence/time/use')
            elif row.contract.startswith('sui.'):
                exclusion = next((c.exclusion for c in CONTRACTS if c.name == row.contract and c.version == row.version), '')
                rep = shapes.get((presence_group(row), entry))
                if exclusion:
                    item.update(status='not_applicable' if row.contract.endswith('measurement_run') else 'wire_only', reason=exclusion,
                        representative=None if row.contract.endswith('measurement_run') else 'test_preserved_artifact_v1_wire_presence')
                elif rep:
                    item.update(status='direct' if row.id == rep else 'represented', representative=rep,
                        reason='same entry + contract/version/selected object/required-key presence; value/use rules separate')
                    if entry == 'ER': item['prerequisite'] = 'public compiler/3; not_run while unavailable'
                elif row.contract.endswith('computation_requested') and row.branch in ('query', 'certificate'):
                    item.update(status='structural_only', representative='test_request_purpose_branches_have_public_structural_schema',
                        reason='EX validates the branch; successful closed method semantics still need a separate case')
                elif row.contract.endswith('computation_proof') and row.branch == 'query':
                    item.update(status='not_applicable', representative='test_gate_f_auth_rel.test_query_missing_field_at_auth_boundary',
                        reason='A-04:166: 54 query authentication-success obligations are outside F-a (no published statement/checker). Retained in the denominator for a later contract slice; 54 required-key negatives remain, and EX syntax is not authentication success.')
                elif row.contract == 'sui.s4.boot' and entry == 'ED':
                    item.update(status='direct', representative='test_gate_f_auth_rel.test_boot_contract_in_draw_added_closure',
                        reason='separate run BOOT retained in added draw ancestry; bind and evaluate, /1 versus /999')
            elif row.contract in PRIMARY_FIELDS:
                root = row.field.split('.', 1)[0].removesuffix('[]')
                item.update(status='constructor', representative=f'test_primary_request_required_constructor_fields[{row.contract}-{root}]',
                    reason='required Python constructor keyword -> TypeError; nested DTO keys have their own constructor pairs')
                if entry == 'ER':
                    item.update(status='represented', representative=f'test_replay_primary_request_key_presence[{row.contract}.{root}]',
                        reason='same required root key; nested key deletion is not implied', prerequisite='compiler/3')
                    if '.' in row.field:
                        item.update(representative='test_replay_nested_primary_key_presence['+row.contract+'.'+row.field+']',
                            reason='exact nested selected key removal in a real issued compiler/3 envelope')
            elif row.contract.endswith('_request'):
                item.update(status='constructor', representative=f'test_public_entry_required_keyword_boundary[{entry}]',
                    reason='public function argument binding rejects missing required keyword with TypeError; intrinsic value tests remain separate')
            elif row.contract == 'C1CountFrame':
                item.update(status='not_applicable', reason=row.not_applicable)
            elif row.contract in ('At', 'When', 'ReservationDue'):
                item.update(status='public_declaration',
                    representative='test_named_public_due_declarations_exist['+row.contract+']',
                    reason=row.not_applicable)
            else:
                item.update(status='public_declaration_missing', representative='test_named_public_due_declarations_exist['+row.contract+']', reason=row.not_applicable)
            dispositions.append(item)
    semantic = []
    for pair in PAIRS:
        for entry in pair.entries:
            semantic.append(dict(pair=pair.id, rules=pair.rules, use=pair.stage, entry=entry,
                status='constructor' if pair.id == 'receipt-storage' else 'planned',
                representative='test_public_record_construction_boundary[receipt-storage]' if pair.id == 'receipt-storage'
                    else 'test_replay_intrinsic_rule_pairs' if entry == 'ER' else 'test_auth_pair',
                reason=DEFERRED_PAIR_ENTRIES.get((pair.id, entry), ''),
                prerequisite='compiler/3' if entry == 'ER' and pair.id != 'receipt-storage' else None))
    from collections import Counter
    from gate_f_auth_inventory import NEW_RELATION_PAIRS
    pending_relations = [dict(target=p.id, rules=p.rules, entry=e,
        status='pending_relation_scope', representative='test_gate_f_auth_rel.test_relation_pair',
        reason=p.pending_reason)
        for p in NEW_RELATION_PAIRS for e in p.pending_entries]
    pending_fields = [d for d in dispositions if d['status'] in
        ('pending', 'structural_only', 'negative_only', 'public_declaration_missing')]
    represented = {'direct', 'represented', 'constructor'}
    supplementary = tuple(r for r in INVENTORY if r.row_kind == 'supplement')
    return dict(inventory_rows=len(INVENTORY), field_rows=len(FIELD_TARGETS), relation_rows=sum(r.row_kind == 'relation' for r in INVENTORY),
        supplementary_rows=len(supplementary), supplementary_plan=[dict(target=row.id,
            rules=row.rules, entries=row.entries, representative=row.representative,
            status='planned; execution outcome is in JUnit') for row in supplementary],
        shape_representatives=len(SHAPE_ROWS), identity_representatives=len({r for r in identities.values()}),
        field_entry_status=dict(Counter(d['status'] for d in dispositions)), dispositions=dispositions,
        rows_with_some_pair=len({d['target'] for d in dispositions if d['status'] in represented}),
        rows_without_auth_pair=sorted({r.id for r in FIELD_TARGETS} - {d['target'] for d in dispositions if d['status'] in represented}),
        semantic_pairs=semantic, coverage_meaning='plan includes folds and public boundaries, not passing counts; ER compiler/3 remains a runtime prerequisite',
        unexpanded_field_entries=pending_fields, unexpanded_relation_entries=pending_relations,
        unexpanded=pending_fields + pending_relations)


@pytest.mark.parametrize('stage', ('raw', 'acquired', 'generated', 'verified', 'adopted'))
def test_stage_stops_are_distinct(stage, record_property):
    record_property('rules', 'A-07,A-09,A-10,A-16')
    record_property('entry', 'EH')
    record_property('stage', stage)
    case = FactsCase(finite_world('FA06')[0], name='auth-stage')
    add_observations(case)
    if stage != 'raw':
        case.acquire(case.raw, clock=case.reading('raw-clock'))
    if stage in ('generated', 'verified', 'adopted'):
        add_computation(case, stage='adopted' if stage == 'adopted' else 'unacquired')
    if stage == 'verified':
        case.acquire((case.computation['result'], case.computation['proof']),
                     clock=case.reading('proof-acquired'))
    case.context()
    got, exc = call_observed(lambda: invoke('EH', case))
    assert_legal(got, exc, 'EH')
    assert len(got.E.links) == 1
    assert len(got.K.available) == (0 if stage == 'raw' else 1)
    assert len(got.K.incorporated) == (1 if stage == 'adopted' else 0)
    assert (got.K.belief is None) == (stage != 'adopted')
    if stage in ('generated', 'verified'):
        assert got.K.pending, 'A-10: generated/verified is not already adopted'


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('use', ('past-reading', 'notification-at-receipt', 'notification-before-receipt'))
def test_same_clock_point_requires_use_specific_evidence(entry, use, record_property):
    record_property('rules', 'A-07,A-08,A-09,A-12,A-21')
    record_property('entry', entry)
    case = finite_case()
    case.clock.advance(100)
    receipt = case.clock.mono_ns()
    point = case.reading('auth-old-reading', time_ns=0)
    if use.startswith('notification'):
        a = case.reading('auth-use-clock', time_ns=receipt-int(use.endswith('before-receipt')))
        case.acquire((point,), clock=a)
    case.context(observed_ns=0 if use == 'past-reading' else receipt,
                 judgment_ns=receipt, events=(('clock', point),))
    if entry == 'EP': add_predicate(case)
    value, exc = call_observed(lambda: invoke(entry, case))
    if use != 'notification-before-receipt':
        assert_legal(value, exc, entry)
    else:
        p = next(x for x in PAIRS if x.id == 'clock-notification')
        assert_bad(value, exc, p, entry)


def shift_primary_times(case, delta, *, wall_only=False):
    def edit(k, r):
        if wall_only:
            return replace(r, at=replace(r.at, wall_ns=r.at.wall_ns + (-1 if r.at.seq % 2 else 1)*10**24))
        b = r.body
        v = deepcopy(b.content.as_json())
        contract_name = b.contract.name
        if contract_name == 'sui.f.clock_reading':
            v['reading']['time_ns'] += delta
        elif contract_name == 'sui.f.measurement':
            for n in ('start_ns', 'end_ns'): v['measurement_interval'][n] += delta
            if v['actual_time']['kind'] == 'clock': v['actual_time']['value']['time_ns'] += delta
        elif contract_name == 'sui.f.route_config' and v['effective_from']['kind'] == 'clock':
            v['effective_from']['value']['time_ns'] += delta
        elif contract_name == 'sui.f.coverage':
            interval = v['value'].get('interval', v['value'].get('requested_interval'))
            for n in ('start_ns', 'end_ns'): interval[n] += delta
        kw = {'content': Payload.json(v)}
        if isinstance(b, Observed) and b.received_ns is not None:
            kw['received_ns'] = b.received_ns + delta
        return replace(r, at=replace(r.at, mono_ns=r.at.mono_ns+delta), body=replace(b, **kw))
    return auth_copy_primary(case, edit=edit)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('variant', ('zero', 'negative-M', 'wall-only'))
def test_signed_monotonic_and_independent_wall(entry, variant, record_property):
    record_property('rules', 'V-04,A-05,A-13,A-18')
    record_property('entry', entry)
    case = finite_case(observations=True)
    if entry == 'EP': add_predicate(case)
    if variant != 'zero':
        case = shift_primary_times(case, -4*SECOND, wall_only=variant == 'wall-only')
    value, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(value, exc, entry)
    if entry == 'EH':
        expected = SECOND-4*SECOND if variant == 'negative-M' else SECOND
        assert value.context.now_ns == expected, 'V-04: negative readings must not be clamped'


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('variant', ('same-source', 'second-source', 'late-source'))
def test_clock_identity_is_not_notification_identity(entry, variant, record_property):
    record_property('rules', 'A-07,A-12,A-13,V-04')
    record_property('entry', entry)
    case = finite_case()
    if variant != 'same-source':
        if variant == 'late-source': case.clock.advance(100)
        value = case.ledger.record(case.points['clock_source']).body.content.as_json()
        source = case.observe('auth-second-source', ContractRef('sui.clock.source', '1'), value)
    else:
        source = case.points['clock_source']
    case.observe('auth-second-reading', fc.CLOCK_READING,
        {'source': source, 'reading': {'run': str(case.clock.run), 'time_ns': 0}})
    context_again(case, observed_ns=0, judgment_ns=0,
                  events=(('clock', case.points['auth-second-reading']),))
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)


def append_public_body(case, body, kind, writer):
    record = Record(id=case.ids.new(kind), at=case.clock.now(), writer=writer,
                    producer=PRODUCER, body=body)
    return case.ledger.append(record, case.ledger.heads()).cid


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('status', ('confirmed', 'withdrawn', 'executed'))
def test_legal_intention_branches_are_total(entry, status, record_property):
    record_property('rules', 'A-03,A-06,A-20,A-21,V-07')
    record_property('entry', entry)
    case = finite_case()
    decision = case.decide('auth-decision', ContractRef('auth.decision', '1'), {}, inputs=())
    job = case.put('auth-job', JobOpened(decision=case.ref(decision), step=0,
        content=Payload.json({}), contract=ContractRef('auth.job', '1')))
    attempt = case.put('auth-attempt', AttemptStarted(job=case.ref(job),
        content=Payload.json({}), contract=ContractRef('auth.attempt', '1')))
    base = Intention(target=case.clock.run, operation='auth', status=IntentionStatus.CONFIRMED,
        decided_in=case.ref(decision), content=Payload.json({}), contract=ContractRef('auth.intention', '1'))
    confirmed = append_public_body(case, base, RefKind.INTENTION, Role.MODEL)
    if status != 'confirmed':
        append_public_body(case, replace(base, status=IntentionStatus(status),
            supersedes=case.ref(confirmed), via=case.ref(attempt) if status == 'executed' else None),
            RefKind.INTENTION, Role.MODEL)
    context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)


@pytest.mark.parametrize('body_name,entry', tuple((body, entry)
    for body in ('Observed', 'Decided', 'JobOpened', 'AttemptStarted', 'Prediction', 'Interpretation', 'Preference')
    for entry in ('EN', 'EH', 'EP', 'EF') if (body, entry) != ('Preference', 'EN')))
def test_unknown_contract_free_json_is_not_reinterpreted(entry, body_name, record_property):
    record_property('rules', 'A-01,A-06,A-20,V-03')
    record_property('entry', entry)
    case = finite_case()
    # Deliberately resembles a malformed tagged clock. It is free JSON.
    payload = Payload.json({'kind': 'clock', 'value': {'run': 'not-a-Ref', 'time_ns': None}})
    contract = ContractRef('auth.free_json', '1')
    request = case.decide('auth-parent', ContractRef('auth.request', '1'), {}, inputs=())
    job = case.put('auth-job', JobOpened(decision=case.ref(request), step=0,
        content=Payload.json({}), contract=ContractRef('auth.job', '1')))
    common = dict(content=payload, contract=contract)
    choices = {
        'Observed': (Observed(route='auth', received_ns=case.clock.mono_ns(), **common), RefKind.OBSERVATION, Role.MEMBRANE),
        'Decided': (Decided(inputs=(), **common), RefKind.DECISION, Role.MODEL),
        'JobOpened': (JobOpened(decision=case.ref(request), step=0, **common), RefKind.JOB, Role.MODEL),
        'AttemptStarted': (AttemptStarted(job=case.ref(job), **common), RefKind.ATTEMPT, Role.MEMBRANE),
        'Prediction': (Prediction(target='future', about=(), basis=(), **common), RefKind.PREDICTION, Role.MODEL),
        'Interpretation': (Interpretation(about=(), basis=(), **common), RefKind.INTERPRETATION, Role.INTERPRETER),
        'Preference': (Preference(basis=(), **common), RefKind.PREFERENCE, Role.MODEL),
    }
    append_public_body(case, *choices[body_name])
    context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EC', 'EP', 'EF', 'EL', 'EB'))
def test_unexpected_io_failure_is_preserved(entry, record_property):
    record_property('rules', 'A-21')
    record_property('entry', entry)
    case = base_case(entry)
    if entry == 'EP': add_predicate(case)
    point = case.points['limit' if entry == 'EL' else 'model']
    case.reader = FaultReader(case.ledger, point, 'io')
    value, exc = call_observed(lambda: invoke(entry, case))
    assert isinstance(exc, OSError) and str(exc) == 'auth-test controlled I/O failure', diagnostic(value, exc)


@pytest.mark.parametrize('fields', (('/a', '/b'), ('/b', '/a'), ('/a', '/a')))
def test_diagnostic_fields_signature_and_validation(fields, record_property):
    record_property('rules', 'A-21')
    record_property('entry', 'exception-constructor')
    value, exc = call_observed(lambda: f.FReplayMismatch('result_mismatch', field='/a', fields=fields))
    if fields == ('/a', '/b'):
        assert exc is None, diagnostic(value, exc)
        assert value.reason == 'result_mismatch'
        assert_pointer(value.field, value.fields, relevant=('a',))
    else:
        assert isinstance(exc, f.FInputError) and exc.reason == 'shape', diagnostic(value, exc)


@pytest.mark.parametrize('source', ('EN', 'EF', 'EL', 'EB'))
@pytest.mark.parametrize('mode', ('same', 'reconstructed-copy', 'missing-body', 'seal'))
def test_replay_authenticates_primary_inputs(source, mode, record_property):
    record_property('rules', 'A-01,A-02,A-19,A-21')
    record_property('entry', 'ER')
    record_property('stage', 'replay')
    case = base_case(source)
    issued, exc = call_observed(lambda: invoke(source, case))
    assert_legal(issued, exc, source)
    if mode == 'reconstructed-copy':
        case = auth_copy_primary(case)
    elif mode in ('missing-body', 'seal'):
        target = case.points['limit' if source == 'EL' else 'model']
        case.reader = FaultReader(case.ledger, target, mode)
    got, error = call_observed(lambda: invoke('ER', case, saved=issued.canonical_bytes))
    if mode in ('same', 'reconstructed-copy'):
        assert_legal(got, error, 'ER')
        assert got.canonical_bytes == issued.canonical_bytes
    else:
        p = next(x for x in PAIRS if x.id == mode)
        assert_bad(got, error, p, 'ER')


class AbsentEntryReader(Reader):
    def __init__(self, ledger, excluded):
        super().__init__(ledger)
        self.excluded = frozenset(excluded)
    def entries(self):
        return tuple(e for e in super().entries() if e.cid not in self.excluded)
    def entry(self, cid):
        if cid in self.excluded: raise KeyError(cid)
        return super().entry(cid)
    def record(self, cid):
        if cid in self.excluded: raise KeyError(cid)
        return super().record(cid)
    def sealed_content(self, cid):
        if cid in self.excluded: raise KeyError(cid)
        return super().sealed_content(cid)


@pytest.mark.parametrize('view', ('historical', 'later', 'lost'))
def test_replay_keeps_historical_absence(view, record_property):
    record_property('rules', 'A-02,A-19,A-21')
    record_property('entry', 'ER')
    record_property('stage', 'replay')
    case = finite_case()
    fixed = case.fixed_parents
    future = case.observe('future', ContractRef('auth.future', '1'), {})
    past = AbsentEntryReader(case.ledger, (future,))
    registry = f.builtin_f_registry()
    request = f.FPreflightFacts(fixed_parents=fixed, model=None,
        required_records=(future,), required_capabilities=())
    issued, error = call_observed(lambda: ff.check_f_preflight_from_facts(past, request,
        registry=registry, budget=BUDGET))
    assert error is None, diagnostic(issued, error)
    kind, reason, field, _ = diagnostic(issued, None)
    assert (kind, reason) == ('NoDecision:incomplete', 'prerequisite_unavailable')
    assert_pointer(field)
    if view == 'historical':
        case.reader = issued.reader
    elif view == 'lost':
        case.reader = AbsentEntryReader(case.ledger, (future, case.points['boot']))
    got, exc = call_observed(lambda: invoke('ER', case, saved=issued.canonical_bytes))
    if view == 'historical':
        assert exc is None, diagnostic(got, exc)
        assert diagnostic(got, None)[:2] == (kind, reason)
        assert got.canonical_bytes == issued.canonical_bytes
    else:
        assert isinstance(exc, f.FReplayUnavailable) and exc.reason == 'missing_input', diagnostic(got, exc)
        assert_pointer(exc.field)


@pytest.mark.parametrize('case_name,entry', tuple((name, entry)
    for name in ('source-measurement-null', 'unknown-received-null',
                 'unused-route-unavailable', 'future-coverage-unproved', 'unavailable-reason-missing')
    for entry in ('EN', 'EH', 'EP', 'EF')
    if name != 'future-coverage-unproved' or entry == 'EF'))
def test_presence_and_unavailable_are_use_sensitive(entry, case_name, record_property):
    record_property('rules', 'A-07,A-12,A-14,A-20,A-21,V-03')
    record_property('entry', entry)
    # No actual measurement needs the unspecified clock or route contract.
    case = finite_case()
    if case_name == 'source-measurement-null':
        source = deepcopy(case.ledger.record(case.points['clock_source']).body.content.as_json())
        source['measurement'] = None
        case.observe('auth-unused-source', ContractRef('sui.clock.source', '1'), source)
        context_again(case)
    elif case_name == 'unknown-received-null':
        case.put('auth-null-receipt', Observed(route='auth', content=Payload.json({}),
            contract=ContractRef('auth.unused', '1'), received_ns=None))
        context_again(case)
    elif case_name in ('unused-route-unavailable', 'unavailable-reason-missing'):
        unavailable = {'reason': 'unknown-clock', 'basis': []}
        if case_name.endswith('missing'): del unavailable['reason']
        case.observe('auth-route', fc.ROUTE_CONFIG, {
            'config': {'route_epoch': 'unused', 'origin': 'bootstrap', 'version': '1',
                'sampling_contract': plain(ContractRef('sui.f.finite_measurement', '1')),
                'clock_contract': plain(CLOCK), 'loss_contract': plain(ContractRef('auth.loss', '1')),
                'args': {}, 'decision': None, 'execution': None},
            'effective_from': {'kind': 'unavailable', 'value': unavailable},
            'execution': None, 'evidence': []})
        context_again(case)
    else:
        case = coverage_case('coverage_unproved')
        def edit(k, r):
            if k != 'auth-coverage': return r
            value = deepcopy(r.body.content.as_json())
            value['value']['interval']['end_ns'] += 1000
            return replace(r, body=replace(r.body, content=Payload.json(value)))
        case = auth_copy_primary(case, edit=edit)
    if entry == 'EP': add_predicate(case)
    value, exc = call_observed(lambda: invoke(entry, case))
    if case_name.endswith('missing'):
        kind, reason, field, fields = diagnostic(value, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(value, exc)
        assert_pointer(field, fields)
    else:
        assert_legal(value, exc, entry)


@pytest.mark.parametrize('order', ('local-first', 'bound-first'))
def test_local_authentication_cannot_replace_fixed_boundary(order, record_property):
    record_property('rules', 'A-18,A-19,A-21')
    record_property('entry', 'EF,EH')
    case = finite_case(observations=True)
    now = case.ledger.record(case.raw[0]).body.received_ns
    context_again(case, observed_ns=now-1, judgment_ns=case.clock.mono_ns())
    sequence = ('EF', 'EH') if order == 'local-first' else ('EH', 'EF')
    for entry in sequence:
        got, exc = call_observed(lambda: invoke(entry, case))
        if entry == 'EF':
            assert_legal(got, exc, 'EF')
        else:
            assert_bad(got, exc, next(p for p in PAIRS if p.id == 'observation-bound'), 'EH')


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('selected', ('original', 'other'))
def test_origin_scopes_do_not_mix_pending_or_acquisition(entry, selected, record_property):
    record_property('rules', 'A-07,A-09,A-10,A-16,A-19')
    record_property('entry', entry)
    case = FactsCase(finite_world('FA06')[0], name='auth-origins')
    original = case.points['origin']
    other = case.observe('auth-other-origin', fc.KNOWLEDGE_ORIGIN, {'model': case.points['model']})
    add_observations(case)
    case.points['origin'] = other
    case.acquire(case.raw, clock=case.reading('auth-other-clock'))
    add_computation(case, stage='unacquired')
    case.points['origin'] = original if selected == 'original' else other
    case.candidate(('Compute',))
    case.context()
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)
    if entry == 'EH':
        assert len(got.K.available) == (0 if selected == 'original' else 1)
        assert bool(got.K.pending) == (selected == 'other')
        assert got.K.belief is None


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('previous_mode', ('null', 'prior-adoption'))
def test_readoption_preserves_single_application(entry, previous_mode, record_property):
    record_property('rules', 'A-10,A-16,A-21')
    record_property('entry', entry)
    record_property('member', 'good:' + previous_mode)
    case = finite_case(computation='adopted')
    original = invoke('EH', case).K
    assert len(original.incorporated) == 1
    request = case.reader.record(case.computation['request'])
    assert request.body.content.as_json()['args']['previous_result'] is None
    prior = case.computation['adopted']
    completion = case.computation['completed']
    previous = prior if previous_mode == 'prior-adoption' else None
    points = (case.points['origin'], completion) + ((prior,) if previous is not None else ())
    # A-16: previous names the state at this new adoption event; the original
    # derivation still has previous_result=null and is not computed/applied twice.
    case.decide('auth-readopted', fc.KNOWLEDGE_ADOPTED,
        {'origin': case.points['origin'], 'previous': previous, 'completion': completion},
        inputs=points)
    context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)
    # EN/EH expose K directly. EP/EF do not: observe the same records through EH
    # as an additional public assertion, never inspect a private prepared handle.
    after = got.K if entry == 'EH' else got.value.K if entry == 'EN' else invoke('EH', case).K
    assert after.incorporated == original.incorporated
    assert after.available == original.available
    assert after.belief == original.belief == case.ref(case.computation['result'])
    assert case.reader.record(case.computation['request']) == request


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('variant', ('clock', 'double-tag', 'unknown-tag', 'free-value'))
def test_union_branch_and_free_measurement_value(entry, variant, record_property):
    record_property('rules', 'V-03,A-20,A-21')
    record_property('entry', entry)
    case = finite_case(observations=True)
    def edit(k, r):
        if k != 'raw-0': return r
        value = deepcopy(r.body.content.as_json())
        if variant == 'double-tag':
            value['actual_time']['value'] = deepcopy(value['actual_time'])
        elif variant == 'unknown-tag':
            value['actual_time']['kind'] = 'future-clock'
        elif variant == 'free-value':
            # Use a free JSON field on an unknown Observed contract separately;
            # the finite model's numeric value remains the declared observation.
            return r
        return replace(r, body=replace(r.body, content=Payload.json(value)))
    case = auth_copy_primary(case, edit=edit)
    if variant == 'free-value':
        case.observe('auth-json', ContractRef('auth.free', '1'),
            {'kind': 'unavailable', 'value': {'not': 'an Unavailable'}})
        context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    if variant in ('clock', 'free-value'):
        assert_legal(got, exc, entry)
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(field, fields)


@pytest.mark.parametrize('bad', (False, True))
def test_c1_source_time_is_contract_specific_M(bad, record_property):
    record_property('rules', 'A-12,A-13,A-21,V-04')
    record_property('entry', 'EC')
    case = assemble_c1(delay=1)
    case = auth_copy_primary(case, edit=lambda k, r: replace(r,
        body=replace(r.body, received_ns=r.body.source_time_ns-int(bad))) if k == 'read-report' else r)
    got, exc = call_observed(lambda: invoke('EC', case))
    if not bad:
        assert_legal(got, exc, 'EC')
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(field, fields, relevant=('source_time_ns', 'completion_ns', 'received_ns', 'end_ns'))


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF'))
@pytest.mark.parametrize('source_time', (-10**24, 10**24))
def test_unknown_source_clock_remains_U(entry, source_time, record_property):
    record_property('rules', 'A-12,V-04')
    record_property('entry', entry)
    case = finite_case()
    case.observe('auth-sender', ContractRef('auth.sender', '1'), {}, source_time_ns=source_time)
    context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: invoke(entry, case))
    assert_legal(got, exc, entry)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EC', 'EP', 'EF', 'EL', 'EB'))
@pytest.mark.parametrize('bad', (False, True))
def test_record_name_is_not_a_point(entry, bad, record_property):
    record_property('rules', 'A-01,A-03,A-21,V-08')
    record_property('entry', entry)
    record_property('member', 'bad' if bad else 'good')
    case = base_case(entry)
    if entry == 'EP': add_predicate(case)
    key = 'limit' if entry == 'EL' else 'model'
    point = case.points[key]
    if entry == 'EF':
        request = f.FPreflightFacts(fixed_parents=case.fixed_parents, model=None,
            required_records=(str(case.ref(point)) if bad else point,), required_capabilities=())
        got, exc = call_observed(lambda: ff.check_f_preflight_from_facts(case.reader, request,
            registry=f.builtin_f_registry(), budget=BUDGET))
    else:
        if bad: case.points[key] = str(case.ref(point))
        got, exc = call_observed(lambda: invoke(entry, case))
    if not bad:
        assert_legal(got, exc, entry)
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'reference_kind'), diagnostic(got, exc)
        assert_pointer(field, fields)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EC', 'EP', 'EF', 'EB'))
@pytest.mark.parametrize('bad', (False, True))
def test_fixed_parent_sequence_is_canonical(entry, bad, record_property):
    record_property('rules', 'A-02,A-21')
    record_property('entry', entry)
    record_property('member', 'bad' if bad else 'good')
    case = base_case(entry)
    if entry == 'EP': add_predicate(case)
    parents = tuple(sorted((*case.fixed_parents, case.points['origin'])))
    case.fixed_parents = tuple(reversed(parents)) if bad else parents
    got, exc = call_observed(lambda: invoke(entry, case))
    if not bad:
        assert_legal(got, exc, entry)
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'noncanonical'), diagnostic(got, exc)
        assert_pointer(field, fields, relevant=('fixed_parents',))


RECORD_ALL_ROWS = tuple(row for row in FIELD_TARGETS
    if row.contract == 'Record' and row.field not in ('writer', 'schema', 'status'))
RECORD_INTEGRITY_ROWS = tuple({identity_group(row): row for row in reversed(RECORD_ALL_ROWS)}.values())


def record_specimen(row, entry='EF'):
    if entry == 'EL':
        # The limit lives in D. Its Record still has ordinary Record ancestry
        # and may explicitly cite authentic records of every public Body.
        case, point = record_specimen(row, 'EF')
        declaration = assemble_limit()
        case.predict('limit', fc.LIMIT_DECLARATION,
            declaration.ledger.record(declaration.points['limit']).body.content.as_json(),
            basis=(point,))
        refresh(case)
        return case, point
    case = base_case(entry, observations=True)
    keys = {'Observed': 'raw-0', 'Decided': 'measure-request-1',
            'JobOpened': 'measure-job-1', 'AttemptStarted': 'measure-attempt-1',
            'Prediction': 'model'}
    if entry in ('EC', 'EB'):
        keys['Observed'] = 'origin'
        if row.body in ('Decided', 'JobOpened', 'AttemptStarted', 'Intention'):
            if entry == 'EB': case = assemble_legacy_bridge(pending=True)[0]
            prefix = 'read' if entry == 'EC' else 'P'
            for dst, src in (('measure-request-1', prefix+'-request'),
                             ('measure-job-1', prefix+'-job'), ('measure-attempt-1', prefix+'-attempt')):
                case.points[dst] = case.points[src]
    if row.body == 'Interpretation':
        point = append_public_body(case, Interpretation(about=(), basis=(),
            content=Payload.json({'free': True}), contract=ContractRef('auth.interpretation', '1')),
            RefKind.INTERPRETATION, Role.INTERPRETER)
    elif row.body == 'Preference':
        point = case.preference({'kind': 'style', 'H_ns': None, 'gamma': 1.0},
            ContractRef('sui.s4d.preference', '1')) if entry == 'EB' else case.preference(
                {'kind': 'style', 'scope': {'name': 'unbounded_total', 'version': '1', 'H_ns': None},
                 'gamma': [1, 1]}, fc.STYLE)
        if entry == 'EN':
            case.scope = replace(case.scope, source=case.ref(point))
    elif row.body == 'Intention':
        base = Intention(target=case.clock.run, operation='auth', status=IntentionStatus.CONFIRMED,
            decided_in=case.ref(case.points['measure-request-1']),
            content=Payload.json({}), contract=ContractRef('auth.intention', '1'))
        point = append_public_body(case, base, RefKind.INTENTION, Role.MODEL)
        status = row.branch.split('-')[0]
        if status != 'confirmed':
            point = append_public_body(case, replace(base, status=IntentionStatus(status),
                supersedes=case.ref(point), via=case.ref(case.points['measure-attempt-1']) if status == 'executed' else None),
                RefKind.INTENTION, Role.MODEL)
    else:
        point = case.points[keys[row.body]]
    case.points['auth-integrity-target'] = point
    context_again(case)
    if entry == 'EP': add_predicate(case)
    # Include the present Producer.state branch without inventing a handle.
    case = auth_copy_primary(case, edit=lambda k, r: replace(r,
        producer=replace(r.producer, state=StateRef(lineage='auth-lineage', revision=0))))
    point = case.points['auth-integrity-target']
    # Interpretation is a non-event leaf and therefore not a ledger head.
    # Explicitly include the leaf in the fixed authentication scope (A-02),
    # without falsely making it an event parent (A-03).
    case.fixed_parents = tuple(sorted(set((*case.fixed_parents, point))))
    return case, point


def changed_record_column(record, field):
    def alternate(value, name):
        if isinstance(value, Ref): return Ref(value.kind, value.value+'-changed')
        if isinstance(value, Payload): return Payload(media_type=value.media_type, data=value.data+b' ')
        if isinstance(value, ContractRef): return ContractRef(value.name, value.version+'-changed')
        if isinstance(value, tuple): return value+(Ref(RefKind.OBSERVATION, 'auth-extra'),)
        if value is None:
            kinds = {'caused_by': RefKind.ATTEMPT, 'supersedes': RefKind.INTENTION, 'via': RefKind.ATTEMPT}
            if name in kinds: return Ref(kinds[name], 'auth-extra')
            return 'changed' if name == 'source_id' else 0
        if isinstance(value, StateRef): return None
        if isinstance(value, int): return value-1 if name == 'received_ns' else value+1
        if isinstance(value, bytes): return value+b' '
        if isinstance(value, str): return value+'-changed'
        raise AssertionError('no public field mutation for '+field)
    path = field.removesuffix('[]').split('.')
    target = record if path[0] in ('id', 'at', 'writer', 'producer', 'schema') else record.body
    def descend(value, parts):
        name = parts[0]
        old = getattr(value, name)
        new = alternate(old, name) if len(parts) == 1 else descend(old, parts[1:])
        return replace(value, **{name: new})
    changed = descend(target, path)
    return changed if target is record else replace(record, body=changed)


class RecordColumnReader(Reader):
    def __init__(self, ledger, point, field):
        super().__init__(ledger)
        self.point, self.field = point, field
    def record(self, cid):
        record = super().record(cid)
        return changed_record_column(record, self.field) if cid == self.point else record


def identity_parameters():
    for entry in ALL_ENTRIES:
        applicable = RECORD_ALL_ROWS
        reps = tuple({identity_group(r): r for r in reversed(applicable)}.values())
        legal_seen = set()
        for row in reps:
            legal = (row.body, row.branch.split('-')[0])
            members = (True,) if legal in legal_seen else (False, True)
            legal_seen.add(legal)
            for bad in members:
                yield pytest.param(row, entry, bad,
                    id=f'A-01__{row.id}__{entry}__{"bad" if bad else "good"}')


IDENTITY_PARAMS = tuple(identity_parameters())


@pytest.mark.parametrize('row,entry,bad', IDENTITY_PARAMS)
def test_whole_record_identity_covers_each_public_column(row, entry, bad, record_property):
    record_property('rules', 'A-01,A-19,A-21')
    record_property('entry', entry)
    record_property('target', row.id)
    record_property('member', 'bad' if bad else 'good')
    case, point = record_specimen(row, entry)
    saved = invoke('EF', case).canonical_bytes if entry == 'ER' else None
    if bad and entry != 'ED':
        case.reader = RecordColumnReader(case.ledger, point, row.field)
    got, exc = call_observed(lambda: draw_suffix(None, False, subject=case,
        identity_fault=(point, row.field) if bad else None) if entry == 'ED' else invoke(entry, case, saved=saved))
    if not bad:
        assert_legal(got, exc, entry)
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FReplayMismatch', 'result_mismatch'), diagnostic(got, exc)
        assert_pointer(field, fields)


@pytest.mark.parametrize('boundary,bad', tuple((name, bad)
    for name in CONSTRUCTION_BOUNDARIES for bad in (False, True)))
def test_public_record_construction_boundary(boundary, bad, record_property):
    record_property('rules', 'A-01,A-13,A-20,A-21')
    record_property('entry', 'Record-constructor')
    record_property('member', 'bad' if bad else 'good')
    case = finite_case()
    record = case.ledger.record(case.points['origin'])
    expected = CONSTRUCTION_BOUNDARIES[boundary][1]
    def construct():
        if boundary == 'status': return IntentionStatus('unknown' if bad else 'confirmed')
        if boundary == 'receipt-storage':
            return replace(record, body=replace(record.body,
                received_ns=record.at.mono_ns + int(bad)))
        if boundary == 'writer':
            return replace(record, writer=Role.MODEL if bad else Role.MEMBRANE)
        return replace(record, schema=999 if bad else 3)
    value, exc = call_observed(construct)
    if bad:
        assert type(exc).__name__ == expected, (boundary, diagnostic(value, exc))
    else:
        assert exc is None and isinstance(value, IntentionStatus if boundary == 'status' else Record), diagnostic(value, exc)


@pytest.mark.parametrize('name', ('At', 'When', 'ReservationDue'))
def test_named_public_due_declarations_exist(name, record_property):
    record_property('rules', 'V-03,V-08,A-13')
    record_property('entry', 'public-declaration')
    declaration = getattr(f, name, None)
    assert declaration is not None, f'V-08 line 88: public sui.f.{name} is missing'
    expected = {
        'At': ('run', 'time_ns', 'source'),
        'When': ('predicate',),
        'ReservationDue': ('reservation_id', 'firing_id', 'due', 'detected', 'execution', 'evidence'),
    }
    assert tuple(field.name for field in dataclass_fields(declaration)) == expected[name]
    if name in ('At', 'When'):
        assert get_type_hints(f.Reservation)['trigger'] == f.At | f.When
    else:
        hints = get_type_hints(declaration)
        assert hints['due'] == f.ClockReading | f.Unavailable
        assert hints['detected'] == f.ClockReading
        assert hints['execution'] == f.ClockReading | None


def primary_request(type_name):
    if type_name == 'FFactsRequest':
        case = finite_case()
        values = dict(fixed_parents=case.fixed_parents, model=case.points['model'],
            candidates=case.points['candidates'], preferences=(), scope=case.scope,
            context=case.points['context'], method=METHOD)
    elif type_name == 'FPreflightFacts':
        case = finite_case()
        values = dict(fixed_parents=case.fixed_parents, model=None,
                      required_records=(), required_capabilities=())
    else:
        case = base_case('EB')
        values = dict(fixed_parents=case.fixed_parents, model=case.points['model'],
            context=case.points['context'], preferences=tuple(case.preferences),
            candidates=('M', 'Q'), adapter=ContractRef('sui.f.legacy_bridge', '2'))
    return case, values


PRIMARY_FIELDS = {
    'FFactsRequest': ('fixed_parents', 'model', 'candidates', 'preferences', 'scope', 'context', 'method'),
    'FPreflightFacts': ('fixed_parents', 'model', 'required_records', 'required_capabilities'),
    'FLegacyBridgeRequest': ('fixed_parents', 'model', 'context', 'preferences', 'candidates', 'adapter'),
}


@pytest.mark.parametrize('type_name,missing', tuple((name, field)
    for name, fields in PRIMARY_FIELDS.items() for field in (None, *fields)))
def test_primary_request_required_constructor_fields(type_name, missing, record_property):
    record_property('rules', 'A-20,V-03')
    record_property('entry', 'request-constructor')
    record_property('target', type_name+':'+str(missing))
    _, values = primary_request(type_name)
    if missing is not None: del values[missing]
    got, exc = call_observed(lambda: getattr(f, type_name)(**values))
    if missing is None:
        assert exc is None, diagnostic(got, exc)
        assert type(got).__name__ == type_name
    else:
        assert isinstance(exc, TypeError), ('required constructor field', missing, diagnostic(got, exc))


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EC', 'EP', 'EF', 'EB'))
@pytest.mark.parametrize('bad', (False, True))
def test_primary_context_or_required_point_null(entry, bad, record_property):
    record_property('rules', 'A-03,A-20,A-21')
    record_property('entry', entry)
    case = base_case(entry)
    if entry == 'EP': add_predicate(case)
    if entry == 'EF':
        request = f.FPreflightFacts(fixed_parents=case.fixed_parents, model=None,
            required_records=(None if bad else case.points['origin'],), required_capabilities=())
        got, exc = call_observed(lambda: ff.check_f_preflight_from_facts(case.reader, request,
            registry=f.builtin_f_registry(), budget=BUDGET))
    else:
        if bad: case.points['context'] = None
        got, exc = call_observed(lambda: invoke(entry, case))
    if not bad:
        assert_legal(got, exc, entry)
    else:
        kind, reason, field, fields = diagnostic(got, exc)
        assert kind == 'FInputError' and reason in ('shape', 'reference_kind'), diagnostic(got, exc)
        assert_pointer(field, fields)


@pytest.mark.parametrize('pair,bad', tuple(pytest.param(p, bad,
    id=f'{p.rules[0]}__{p.id}__ER__{"bad" if bad else "good"}')
    for p in PAIRS if 'ER' in p.entries and p.id != 'receipt-storage'
    for bad in (False, True)))
def test_replay_intrinsic_rule_pairs(pair, bad, record_property):
    record_property('rules', ','.join(pair.rules))
    record_property('entry', 'ER')
    record_property('stage', 'replay-'+pair.stage)
    record_property('member', 'bad' if bad else 'good')
    require_current_replay_compiler()
    source = 'EN' if pair.id == 'observation-bound' else 'EF'
    good = prepare_pair(pair, source, False)
    saved, error = call_observed(lambda: invoke(source, good))
    assert_legal(saved, error, source)
    current = prepare_pair(pair, source, bad) if bad else good
    current_ids = {current.ledger.record(e.cid).id: e.cid for e in current.ledger.entries()}
    assert len(current_ids) == len(current.ledger.entries()), 'fixture needs unambiguous primary Record ids'
    remap = {e.cid: current_ids[good.ledger.record(e.cid).id] for e in good.ledger.entries()
             if good.ledger.record(e.cid).id in current_ids}
    got, exc = call_observed(lambda: replay_with_primary_edit(saved.canonical_bytes, current, remap=remap))
    if bad: assert_bad(got, exc, pair, 'ER')
    else: assert_legal(got, exc, 'ER')


@pytest.mark.parametrize('source,field,bad', tuple(pytest.param(source, field, bad,
    id=f'A-20__{name}.{field}__ER__{"bad" if bad else "good"}')
    for source, name in (('EN', 'FFactsRequest'), ('EF', 'FPreflightFacts'), ('EB', 'FLegacyBridgeRequest'))
    for field in PRIMARY_FIELDS[name] for bad in (False, True)))
def test_replay_primary_request_key_presence(source, field, bad, record_property):
    record_property('rules', 'A-20,A-21,V-03')
    record_property('entry', 'ER')
    require_current_replay_compiler()
    case = base_case(source)
    saved = invoke(source, case).canonical_bytes
    value = json.loads(saved)
    if value['compiler'] != {'name': 'sui.f.prepare_world', 'version': '3'}:
        pytest.skip('not_run: primary-request replay requires the specified compiler/3')
    if bad: del value['input']['value'][field]
    got, exc = call_observed(lambda: invoke('ER', case, saved=canonical(value)))
    if not bad:
        assert_legal(got, exc, 'ER')
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields, relevant=(field,))


@pytest.mark.parametrize('row,bad', tuple(pytest.param(row, bad,
    id=f'A-20__{row.contract}.{row.field}__ER__{"bad" if bad else "good"}')
    for row in FIELD_TARGETS if row.contract in PRIMARY_FIELDS and '.' in row.field
    for bad in (False, True)))
def test_replay_nested_primary_key_presence(row, bad, record_property):
    record_property('rules', 'A-20,A-21,V-03')
    record_property('entry', 'ER')
    record_property('target', row.id)
    require_current_replay_compiler()
    source = {'FFactsRequest': 'EN', 'FPreflightFacts': 'EF', 'FLegacyBridgeRequest': 'EB'}[row.contract]
    case = base_case(source)
    if source == 'EF':
        saved = ff.check_f_preflight_from_facts(case.reader,
            f.FPreflightFacts(fixed_parents=case.fixed_parents, model=None,
                required_records=tuple(sorted(set(case.fixed_parents))),
                required_capabilities=(f.RequiredCapability(kind='method', ref=METHOD,
                    implementation_required=False),)), registry=f.builtin_f_registry(), budget=BUDGET)
    else:
        saved = invoke(source, case)
    value = json.loads(saved.canonical_bytes)
    if value['compiler'] != {'name': 'sui.f.prepare_world', 'version': '3'}:
        pytest.skip('not_run: nested primary-request replay requires compiler/3')
    if bad: remove_field(value['input']['value'], row.field)
    got, exc = call_observed(lambda: invoke('ER', case, saved=canonical(value)))
    if not bad:
        assert_legal(got, exc, 'ER')
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('body_name,bad', tuple((name, bad) for name in BODY_FIELDS for bad in (False, True)))
def test_body_required_constructor_field(body_name, bad, record_property):
    from dataclasses import fields as public_fields
    record_property('rules', 'A-20,V-07')
    record_property('entry', 'Body-constructor')
    row = next(r for r in RECORD_ALL_ROWS if r.body == body_name)
    case, point = record_specimen(row)
    body = case.ledger.record(point).body
    kwargs = {field.name: getattr(body, field.name) for field in public_fields(body)}
    mandatory = {'Observed': 'route', 'Decided': 'inputs', 'JobOpened': 'decision',
        'AttemptStarted': 'job', 'Intention': 'target', 'Prediction': 'target',
        'Interpretation': 'about', 'Preference': 'basis'}[body_name]
    if bad: del kwargs[mandatory]
    got, exc = call_observed(lambda: type(body)(**kwargs))
    if bad: assert isinstance(exc, TypeError), diagnostic(got, exc)
    else: assert exc is None and got == body, diagnostic(got, exc)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF', 'ED'))
@pytest.mark.parametrize('target', ('request-inputs', 'result-about', 'proof-basis', 'candidate-basis', 'quantity-basis'))
@pytest.mark.parametrize('variant', ('duplicate', 'extra', 'reordered'))
def test_outer_reference_set_and_containment(entry, target, variant, record_property):
    record_property('rules', 'A-03,A-04,A-21')
    record_property('entry', entry)
    record_property('use', target+':'+variant)
    case = FactsCase(finite_world('FA06')[0], name='auth-outer')
    extra = case.predict('auth-unrelated', ContractRef('auth.evidence', '1'), {'value': 'unused'})
    add_observations(case)
    case.acquire(case.raw, clock=case.reading('raw-acquired'))
    add_computation(case, stage='unacquired')
    case.candidate(('Compute',))
    case.predict('auth-outer-quantity', fc.QUANTITY_DECLARATION,
        {'kind': 'rational_constant', 'value': [1, 1], 'unit': 'nat', 'provenance': [case.points['model']]},
        basis=(case.points['model'],))
    case.context()
    if entry == 'EP': add_predicate(case)
    # A-04 table lines 158..168: finite-update proof basis is set equality;
    # candidate and quantity bases are inclusion. The
    # authenticated extra is deliberately different from all required Refs.
    key, column = {'request-inputs': ('compute-request', 'inputs'),
        'result-about': ('compute-result', 'about'), 'proof-basis': ('compute-proof', 'basis'),
        'candidate-basis': ('candidates', 'basis'), 'quantity-basis': ('auth-outer-quantity', 'basis')}[target]
    def edit(k, record):
        if k != key: return record
        refs = getattr(record.body, column)
        if variant == 'extra': assert case.ref(extra) not in refs, 'fixture must add a distinct Ref, not a duplicate'
        changed = tuple(reversed(refs)) if variant == 'reordered' else refs + (
            refs[0] if variant == 'duplicate' else case.ref(extra),)
        return replace(record, body=replace(record.body, **{column: changed}))
    case = auth_copy_primary(case, edit=edit)
    case.fixed_parents = tuple(sorted(set((*case.fixed_parents, case.points[key]))))
    got, exc = call_observed(lambda: draw_suffix(None, False, subject=case) if entry == 'ED' else invoke(entry, case))
    legal = variant == 'reordered' or target in ('candidate-basis', 'quantity-basis') and variant == 'extra'
    if legal:
        assert_legal(got, exc, entry)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        # A-21 gives shape and false-correspondence categories, but does not
        # specify precedence for a duplicated outer Ref with an unchanged set.
        # Preserve both diagnoses for that overlap; do not fix unspecified text.
        reasons = ('shape', 'proof_mismatch') if variant == 'duplicate' else ('proof_mismatch',)
        assert kind == 'FInputError' and reason in reasons, diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('entry', ('EN', 'EH', 'EP', 'EF', 'ED'))
@pytest.mark.parametrize('required', (False, True))
def test_unknown_receipt_null_is_incomplete_only_when_used(entry, required, record_property):
    record_property('rules', 'A-07,A-08,A-20,A-21')
    record_property('entry', entry)
    case = finite_case()
    point = case.put('auth-null-receipt', Observed(route='auth', received_ns=None,
        contract=ContractRef('auth.notice', '1'), content=Payload.json({})))
    if required:
        case.decide('auth-null-receipt-use', ContractRef('auth.use', '1'), {}, inputs=(point,))
    context_again(case)
    if entry == 'EP': add_predicate(case)
    got, exc = call_observed(lambda: draw_suffix(None, False, subject=case) if entry == 'ED' else invoke(entry, case))
    if not required:
        assert_legal(got, exc, entry)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert kind in ('FIncomplete', 'NoDecision:incomplete') and reason == 'certificate_incomplete', diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('missing', (None, 'input', 'environment', 'claim'))
def test_preserved_artifact_v1_wire_presence(missing, record_property):
    record_property('rules', 'V-08,V-03,A-20,A-21')
    record_property('entry', 'EX')
    case = finite_case()
    value = json.loads(invoke('EN', case).canonical_bytes)
    value['contract']['version'] = '1'
    if missing: del value[missing]
    got, exc = call_observed(lambda: public_codec.f_from_json(canonical(value), contract=fc.MATH_ARTIFACT))
    if missing is None:
        assert exc is None, diagnostic(got, exc)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('purpose', ('query', 'certificate'))
@pytest.mark.parametrize('missing', (None, 'origin', 'method', 'output_contract'))
def test_request_purpose_branches_have_public_structural_schema(purpose, missing, record_property):
    record_property('rules', 'V-03,A-20,A-21')
    record_property('entry', 'EX')
    record_property('use', 'structural-only; not proof or authentication issuance')
    case = finite_case(computation='unacquired')
    value = deepcopy(case.ledger.record(case.computation['request']).body.content.as_json())
    value['purpose'] = purpose
    if missing: del value[missing]
    got, exc = call_observed(lambda: public_codec.f_from_json(canonical(value), contract=fc.COMPUTATION_REQUESTED))
    if missing is None: assert exc is None, diagnostic(got, exc)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('missing', (None, 'request', 'statement', 'checker'))
def test_query_proof_branch_is_structural_not_an_invented_finite_proof(missing, record_property):
    record_property('rules', 'V-03,A-20,A-21')
    record_property('entry', 'EX')
    case = finite_case(computation='unacquired')
    value = deepcopy(case.ledger.record(case.computation['proof']).body.content.as_json())
    value.update(role='query', statement={'contract': {'name': 'auth.undeclared_query_statement', 'version': '1'}, 'value': {}},
                 checker={'name': 'auth.undeclared_query_checker', 'version': '1', 'args': {}})
    if missing: del value[missing]
    got, exc = call_observed(lambda: public_codec.f_from_json(canonical(value), contract=fc.COMPUTATION_PROOF))
    if missing is None: assert exc is None, diagnostic(got, exc)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


ENTRY_CALL_SHAPES = {
    'EN': (ff.prepare_f_from_facts, 'reader fixed_parents model_ref candidate_ref preference_refs scope_request context_ref registry method budget'),
    'EH': (ff.read_f_histories_from_facts, 'reader fixed_parents model_ref context_ref registry budget'),
    'EC': (ff.read_c1_from_facts, 'reader fixed_parents model_ref context_ref registry budget'),
    'EP': (ff.prepare_f_predicate_from_facts, 'reader fixed_parents model_ref context_ref predicate_ref quantity_refs registry budget'),
    'EF': (ff.check_f_preflight_from_facts, 'reader request registry budget'),
    'EL': (ff.certify_f_limit_from_facts, 'reader declaration_ref registry budget'),
    'EB': (ff.prepare_legacy_bridge_from_facts, 'reader fixed_parents model_ref context_ref preference_refs candidates adapter registry budget'),
    'ED': (ff.bind_f_draw, 'prepared draw_record_ref reader budget'),
    'ER': (ff.restore_f_math_result, 'data reader registry budget'),
}


@pytest.mark.parametrize('entry', ALL_ENTRIES)
def test_public_entry_required_keyword_boundary(entry, record_property):
    import inspect
    record_property('rules', 'A-20')
    record_property('entry', entry)
    record_property('boundary', 'Python public-call binding, not intrinsic authentication')
    fn, names = ENTRY_CALL_SHAPES[entry]
    kwargs = {name: object() for name in names.split()}
    signature = inspect.signature(fn)
    signature.bind(**kwargs)  # legal call shape only, not an issued handle
    for name in names.split():
        omitted = {k: v for k, v in kwargs.items() if k != name}
        # Omitted required arguments are rejected before the function body.
        with pytest.raises(TypeError): fn(**omitted)


@pytest.mark.parametrize('bad', (False, True))
def test_preflight_capability_boolean_is_not_integer(bad, record_property):
    record_property('rules', 'A-20,A-21,V-03')
    record_property('entry', 'EF')
    case = finite_case()
    def run():
        requirement = f.RequiredCapability(kind='method', ref=METHOD,
            implementation_required=0 if bad else False)
        request = f.FPreflightFacts(fixed_parents=case.fixed_parents, model=None,
            required_records=(), required_capabilities=(requirement,))
        return ff.check_f_preflight_from_facts(case.reader, request, registry=f.builtin_f_registry(), budget=BUDGET)
    got, exc = call_observed(run)
    if not bad: assert_legal(got, exc, 'EF')
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FInputError', 'shape'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


@pytest.mark.parametrize('type_name,missing', tuple((name, missing)
    for name, keys in (('ContractRef', ('name', 'version')),
                       ('EvaluationScope', ('name', 'version', 'H_ns', 'source')),
                       ('RequiredCapability', ('kind', 'ref', 'implementation_required')))
    for missing in (None, *keys)))
def test_nested_primary_dto_constructor_presence(type_name, missing, record_property):
    record_property('rules', 'A-20,V-03')
    record_property('entry', 'nested-request-constructor')
    constructor, values = {
        'ContractRef': (ContractRef, dict(name='auth.contract', version='1')),
        'EvaluationScope': (f.EvaluationScope, dict(name='unbounded_total', version='1', H_ns=None, source=None)),
        'RequiredCapability': (f.RequiredCapability, dict(kind='method', ref=METHOD, implementation_required=False)),
    }[type_name]
    if missing: del values[missing]
    got, exc = call_observed(lambda: constructor(**values))
    if missing: assert isinstance(exc, TypeError), diagnostic(got, exc)
    else: assert exc is None, diagnostic(got, exc)


class Review4ClockCase(FactsCase):
    """Only one role uses the second ClockSource; other witnesses stay valid."""

    def __init__(self, use):
        super().__init__(finite_world('FA06')[0], name='auth-used-clock')
        self.reading_key = {'context': 'observed_clock',
                            'acquisition': 'computation-acquired',
                            'completion': 'computation-finish'}[use]
        source = self.reader.record(self.points['clock_source'])
        self.observe('auth-used-source', source.body.contract, source.body.content.as_json())

    def reading(self, key, time_ns=None):
        source = self.points['auth-used-source' if key == self.reading_key else 'clock_source']
        return self.observe(key, fc.CLOCK_READING,
            f.FClockReadingFact(source=source, reading=f.ClockReading(run=self.clock.run,
                time_ns=self.clock.mono_ns() if time_ns is None else time_ns)))


def review4_case(pair, entry, bad):
    if pair.id.startswith('generation-without-completion-'):
        case = finite_case(computation='unacquired')
        target_kind = pair.id.rsplit('-', 1)[-1]
        case.acquire((case.computation[target_kind],), clock=case.reading('auth-acquired'))
        context_again(case)
        def edit(key, record):
            if bad and key == 'compute-completed':
                # Keep the event/parents/times; remove only the completion claim.
                # No unreadable body, phantom acquisition or adoption is added.
                return replace(record, body=replace(record.body,
                    contract=ContractRef('auth.unrelated_notification', '1'), content=Payload.json({})))
            return record
    elif pair.id == 'candidate-required-basis':
        case = FactsCase(finite_world('FA06')[0], name='auth-candidate-inclusion')
        extra = case.predict('auth-extra-basis', ContractRef('auth.evidence', '1'), {'value': 'extra'})
        case.candidate(('Compute',))
        case.context()
        def edit(key, record):
            if key != 'candidates': return record
            # The good member is a strict superset. The bad member retains the
            # distinct extra Ref, so only inclusion (not duplicate/empty) is wrong.
            basis = (() if bad else record.body.basis) + (case.ref(extra),)
            return replace(record, body=replace(record.body, basis=basis))
    else:
        case = Review4ClockCase(pair.stage)
        if pair.stage != 'context':
            add_observations(case)
            case.acquire(case.raw, clock=case.reading('raw-acquired'))
            add_computation(case, stage='acquired')
        case.candidate(('Compute',))
        case.context()
        def edit(key, record):
            return content(record, measurement=None) if bad and key == 'auth-used-source' else record
    if entry == 'EP': add_predicate(case)
    original = case
    case = auth_copy_primary(case, edit=edit)
    # Declarations are not event heads. Explicitly make the candidate part of
    # the common fixed scope even for EH/EP/EF which need not use its mathematics.
    for current in (original, case):
        current.fixed_parents = tuple(sorted(set((*current.fixed_parents, current.points['candidates']))))
    if pair.id.startswith('generation-without-completion-'):
        assert all(r.body.contract != fc.KNOWLEDGE_ADOPTED
                   for r in (case.reader.record(e.cid) for e in case.reader.entries()))
        matches = [r for r in (case.reader.record(e.cid) for e in case.reader.entries())
                   if r.body.contract == fc.COMPUTATION_COMPLETED]
        assert bool(matches) == (not bad), 'fixture must change generation evidence, not its acquisition'
    return original, case


REVIEW4_PARAMS = tuple(pytest.param(pair, entry, bad,
    id=f'{pair.rules[0]}__{pair.id}__{entry}__{"bad" if bad else "good"}')
    for pair in REVIEW4_PAIRS for entry in pair.entries for bad in (False, True))


@pytest.mark.parametrize('pair,entry,bad', REVIEW4_PARAMS)
def test_review4_required_evidence_pair(pair, entry, bad, record_property):
    record_property('rules', ','.join(pair.rules))
    record_property('entry', entry)
    record_property('member', 'bad' if bad else 'good')
    record_property('use', pair.stage)
    original, case = review4_case(pair, entry, bad)
    if entry == 'ER' and pair.id == 'candidate-required-basis':
        if bad:
            saved = invoke('EF', original).canonical_bytes
            got, exc = call_observed(lambda: replay_with_primary_edit(saved, case,
                remap=case.auth_point_map))
        else:
            saved = invoke('EF', case).canonical_bytes
            got, exc = call_observed(lambda: invoke('ER', case, saved=saved))
    elif entry == 'ER':
        # A legitimate shortage/rejection is itself a replayable outcome. Use
        # its real issuer, not a forged successful claim whose hash mismatch
        # could conceal a missing authentication check.
        issued, exc = call_observed(lambda: invoke('EN', case))
        assert exc is None, diagnostic(issued, exc)
        if bad:
            expected = 'NoDecision:incomplete' if pair.rules[0] == 'A-10' else 'NoDecision:rejected'
            assert diagnostic(issued, None)[:2] == (expected, pair.reason)
        else:
            assert_legal(issued, None, 'EN')
        got, exc = call_observed(lambda: invoke('ER', case, saved=issued.canonical_bytes))
    else:
        got, exc = call_observed(lambda: draw_suffix(None, False, subject=case, retain_source=True)
            if entry == 'ED' else invoke(entry, case))
    if not bad:
        assert_legal(got, exc, entry)
        return
    kind, reason, pointer, fields = diagnostic(got, exc)
    expected_kinds = {'A-04': ('FInputError',),
        'A-10': ('FIncomplete', 'NoDecision:incomplete'),
        'A-20': ('FSpecificationMissing', 'NoDecision:rejected')}[pair.rules[0]]
    assert kind in expected_kinds and reason == pair.reason, diagnostic(got, exc)
    assert_pointer(pointer, fields, relevant=('basis',) if pair.rules[0] == 'A-04' else ())


def candidate_basis_case(entry):
    case = FactsCase(finite_world('FA06')[0], name='auth-candidate-basis')
    basis = case.predict('auth-generation-basis', fc.QUANTITY_DECLARATION,
        f.FQuantityConstantDeclaration(kind='rational_constant', value=Fraction(1),
            unit='dimensionless', provenance=()))
    case.candidate(('Compute',))
    declaration = replace(case.candidate_value, generation=replace(case.candidate_value.generation,
        basis=(*case.candidate_value.generation.basis, basis)))
    case.predict('candidates', fc.CANDIDATE_DECLARATION, declaration,
        basis=(case.points['model'], basis))
    case.context()
    if entry == 'EP': add_predicate(case)
    # EH/EP/EF also authenticate the candidate explicitly selected in the fixed
    # scope. The basis itself is reachable ONLY through that candidate's typed
    # Point/Ref edges, never through event ancestry or a direct request root.
    case.fixed_parents = tuple(sorted((*case.fixed_parents, case.points['candidates'])))
    return case


REVIEW5_PARAMS = tuple(pytest.param(pair, entry, bad,
    id=f'{pair.rules[0]}__{pair.id}__{entry}__{"bad" if bad else "good"}')
    for pair in REVIEW5_PAIRS for entry in pair.entries for bad in (False, True))


@pytest.mark.parametrize('pair,entry,bad', REVIEW5_PARAMS)
def test_candidate_generation_basis_authentication(pair, entry, bad, record_property):
    record_property('rules', ','.join(pair.rules))
    record_property('entry', entry)
    record_property('member', 'bad' if bad else 'good')
    record_property('use', pair.stage)
    original = candidate_basis_case(entry)
    saved = invoke('EF', original).canonical_bytes if entry == 'ER' else None
    def edit(key, record):
        if not bad or key != 'auth-generation-basis': return record
        if pair.id.endswith('unknown-version'):
            return replace(record, body=replace(record.body,
                contract=ContractRef(record.body.contract.name, '999')))
        if pair.id.endswith('missing-field'):
            value = deepcopy(record.body.content.as_json())
            del value['value']
            return replace(record, body=replace(record.body, content=Payload.json(value)))
        return record
    case = auth_copy_primary(original, edit=edit)
    point = case.points['auth-generation-basis']
    candidate = case.reader.record(case.points['candidates'])
    assert point not in case.fixed_parents
    assert point not in case.reader.ancestors(case.fixed_parents)
    assert point in candidate.body.content.as_json()['generation']['basis']
    assert case.ref(point) in candidate.body.basis
    identity_fault = bad and pair.id.endswith('identity')
    if identity_fault and entry != 'ED':
        case.reader = RecordColumnReader(case.ledger, point, 'producer.code_version')
    if entry == 'ED':
        got, exc = call_observed(lambda: draw_suffix(None, False, subject=case,
            identity_fault=(point, 'producer.code_version') if identity_fault else None))
    elif entry == 'ER':
        got, exc = call_observed(lambda: replay_with_primary_edit(saved, case, remap=case.auth_point_map))
    else:
        got, exc = call_observed(lambda: invoke(entry, case))
    if not bad:
        assert_legal(got, exc, entry)
        return
    kind, reason, pointer, fields = diagnostic(got, exc)
    assert (kind, reason) == (pair.exception, pair.reason), diagnostic(got, exc)
    # A-21 specifies valid field(s), but not a unique prefix for a recursively
    # discovered dependency; do not prescribe an implementation traversal path.
    assert_pointer(pointer, fields)


class Review4CombinedReader:
    """Two disjoint public Ledger.append histories, including two CIDs of one Record."""

    def __init__(self, main, alternate):
        self.main, self.alternate = main, alternate
        self.alternate_points = {entry.cid for entry in alternate.entries()}

    def owner(self, point):
        return self.alternate if point in self.alternate_points else self.main

    def entries(self):
        return self.main.entries() + self.alternate.entries()

    def entry(self, point):
        return self.owner(point).entry(point)

    def record(self, point):
        return self.owner(point).record(point)

    def sealed_content(self, point):
        return self.owner(point).sealed_content(point)

    def ancestors(self, frontier):
        return (self.main.ancestors(tuple(p for p in frontier if p not in self.alternate_points)) |
                self.alternate.ancestors(tuple(p for p in frontier if p in self.alternate_points)))


def review4_json(value):
    """V-01/V-02, for already public JSON values; no product hash/codec helpers."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def review4_D(domain, **fields):
    # E-05:452: fields are spread into the same object, not nested under 'fields'.
    return 'sha256:' + sha256(review4_json(dict(domain=domain, **fields))).hexdigest()


@pytest.fixture(scope='module')
def review4_issued():
    case = FactsCase(finite_world('FA06')[0], name='auth-manifest')
    extra = case.predict('auth-manifest-extra', ContractRef('auth.evidence', '1'), {'note': '時計'})
    another_model = case.predict('auth-another-model', fc.MODEL_SOURCE, f.FModelSource(document=case.document))
    case.candidate(('Compute',))
    case.context()
    case = auth_copy_primary(case, edit=lambda key, record:
        replace(record, body=replace(record.body,
            basis=record.body.basis + (case.ref(extra), case.ref(another_model))))
        if key == 'candidates' else record)
    alternate = Ledger(salts=SequentialSalts(), contents=MemoryContents())
    alias = alternate.append(case.reader.record(case.points['model']), ()).cid
    assert alias != case.points['model']
    def include_alias(key, record):
        if key != 'candidates': return record
        value = deepcopy(record.body.content.as_json())
        value['generation']['basis'].append(alias)
        return replace(record, body=replace(record.body, content=Payload.json(value)))
    case = auth_copy_primary(case, edit=include_alias)
    case.reader = Review4CombinedReader(case.reader, Reader(alternate))
    # Both alias Points are explicit declaration dependencies. Keep only actual
    # FACT heads in the frontier: a Prediction cannot become a draw event parent.
    allowed = tuple(sorted(e.cid for e in case.reader.entries()))
    prepared = invoke('EN', case)
    assert_legal(prepared, None, 'EN')
    problem = json.loads(prepared.canonical_bytes)
    draw = add_draw(case, prepared.value.problem_key)
    root = ff.bind_f_draw(prepared, draw, reader=case.reader, budget=BUDGET)
    assert_legal(root, None, 'ED')
    rooted = json.loads(root.canonical_bytes)
    return dict(case=case, allowed=allowed, alias=alias, draw=draw,
                problem=(prepared, problem), root=(root, rooted))


@pytest.mark.parametrize('stage', ('problem', 'root'))
def test_review4_world_manifest_dependencies(review4_issued, stage, record_property):
    record_property('rules', 'E-05,V-02,A-03')
    record_property('entry', 'EN' if stage == 'problem' else 'ED')
    data = review4_issued
    case, envelope = data['case'], data[stage][1]
    manifest = envelope['claim']['value']['world_manifest']
    assert set(manifest) == {'contract', 'compiler', 'request', 'dependencies', 'preference_causality'}
    assert manifest['contract'] == {'name': 'sui.f.world_manifest', 'version': '3'}
    assert manifest['compiler'] == envelope['compiler'] == {'name': 'sui.f.prepare_world', 'version': '3'}
    request = dict(kind='facts', value=dict(fixed_parents=list(case.fixed_parents),
        model=case.points['model'], candidates=case.points['candidates'], preferences=[],
        scope=plain(case.scope), context=case.points['context'], method=plain(METHOD)))
    assert manifest['request'] == envelope['input'] == request
    deps = manifest['dependencies']
    assert set(deps) == {'points', 'models', 'capabilities', 'ref_lookups', 'absence_environment'}
    points = [p['point'] for p in deps['points']]
    assert points == sorted(set(points)) == list(data['allowed'])
    for point in deps['points']:
        assert set(point) == {'point', 'entry_present', 'body_present', 'record', 'record_digest'}
        assert point['entry_present'] is True and point['body_present'] is True
        assert point['record'] == str(case.reader.record(point['point']).id)
        assert re.fullmatch('sha256:[0-9a-f]{64}', point['record_digest'])
    assert data['draw'] not in points, 'E-05: draw must not rewrite the original world manifest'
    models = deps['models']
    assert [m['point'] for m in models] == sorted({m['point'] for m in models})
    assert case.points['model'] in {m['point'] for m in models}
    for model in models:
        assert set(model) == {'point', 'model_ref'}
        document = case.reader.record(model['point']).body.content.as_json()['document']
        assert model['model_ref'] == 'sha256:' + sha256(review4_json(document)).hexdigest()
    caps = deps['capabilities']
    cap_keys = [(c['kind'], c['ref']['name'], c['ref']['version']) for c in caps]
    assert len(cap_keys) > 1 and cap_keys == sorted(set(cap_keys))
    for cap in caps:
        assert set(cap) == {'kind', 'ref', 'declaration', 'implemented', 'implementation_id'}
        assert type(cap['implemented']) is bool
        assert bool(cap['implementation_id']) if cap['implemented'] else cap['implementation_id'] is None
        if cap['declaration'] is not None:
            assert cap['declaration']['kind'] == cap['kind']
            assert cap['declaration']['ref'] == cap['ref']
    lookups = deps['ref_lookups']
    refs = [row['ref'] for row in lookups]
    assert refs == sorted(set(refs), key=review4_json)
    # Prediction.basis necessarily uses this Ref; both original CIDs must remain.
    model_ref = str(case.reader.record(case.points['model']).id)
    assert model_ref in refs
    for row in lookups:
        assert set(row) == {'ref', 'points'}
        expected = sorted(p for p in data['allowed'] if str(case.reader.record(p).id) == row['ref'])
        assert row['points'] == expected
    assert len(next(row['points'] for row in lookups if row['ref'] == model_ref)) == 2
    assert deps['absence_environment'] is None


@pytest.mark.parametrize('stage', ('problem', 'root'))
def test_review4_manifest_record_digests(review4_issued, stage, record_property):
    record_property('rules', 'E-05,V-02')
    record_property('entry', 'EN' if stage == 'problem' else 'ED')
    data = review4_issued
    claim = data[stage][1]['claim']['value']
    mismatches = []
    for row in claim['world_manifest']['dependencies']['points']:
        record = data['case'].reader.record(row['point'])
        expected = review4_record_digest(record)
        if row['record_digest'] != expected:
            mismatches.append(dict(field='world_manifest.dependencies.points.record_digest',
                point=row['point'], record=str(record.id), body=type(record.body).__name__,
                expected=expected, actual=row['record_digest']))
    if stage == 'root':
        expected = review4_record_digest(data['case'].reader.record(data['draw']))
        if claim['draw_record_digest'] != expected:
            mismatches.append(dict(field='draw_record_digest', point=data['draw'],
                expected=expected, actual=claim['draw_record_digest']))
    # Check every Record and the draw before reporting, so an early mismatch
    # cannot silently leave the independently specified draw digest untested.
    assert not mismatches, json.dumps(mismatches, ensure_ascii=False, sort_keys=True)


def review4_record_digest(record):
    # V-02:28 specifies this wire object explicitly, including Body's type tag,
    # Payload's byte array, present nulls and Record.schema (V-07).
    # Neither the production encoder nor a production digest is the oracle.
    def encode(value):
        if isinstance(value, Ref): return str(value)
        if isinstance(value, Enum): return value.value
        if isinstance(value, Payload):
            return {'media_type': value.media_type, 'data': list(value.data)}
        if is_dataclass(value):
            return {field.name: encode(getattr(value, field.name)) for field in dataclass_fields(value)}
        if isinstance(value, tuple): return [encode(item) for item in value]
        assert value is None or type(value) in (str, int, bool), type(value)
        return value
    value = {'id': str(record.id), 'at': encode(record.at),
             'writer': encode(record.writer), 'producer': encode(record.producer),
             'body': {'type': type(record.body).__name__, 'value': encode(record.body)},
             'schema': record.schema}
    return 'sha256:' + sha256(review4_json(value)).hexdigest()


@pytest.mark.parametrize('stage', ('problem', 'root'))
def test_review4_problem_world_root_key_domains(review4_issued, stage, record_property):
    record_property('rules', 'E-05,V-02')
    record_property('entry', 'EN' if stage == 'problem' else 'ED')
    problem = review4_issued['problem'][1]['claim']['value']
    assert problem['contract'] == {'name': 'sui.f.problem', 'version': '3'}
    expected_fields = set('contract problem_key world_key world_manifest model_ref parents facts E K context preferences style scope gamma candidates continuation measurement_contracts execution_contracts method'.split())
    assert set(problem) == expected_fields
    assert problem['world_key'] == review4_D('sui.f.world/3', manifest=problem['world_manifest'])
    expected_problem_key = review4_D('sui.f.problem/3', **{k: v for k, v in problem.items() if k != 'problem_key'})
    assert problem['problem_key'] == expected_problem_key
    if stage == 'root':
        root = review4_issued['root'][1]['claim']['value']
        extras = {'root_key', 'selection_draw', 'draw_point', 'draw_record_digest'}
        assert set(root) == expected_fields | extras
        assert root['contract'] == {'name': 'sui.f.root', 'version': '3'}
        projected = {k: v for k, v in root.items() if k not in extras}
        projected['contract'] = {'name': 'sui.f.problem', 'version': '3'}
        assert projected == problem
        assert root['draw_point'] == review4_issued['draw']
        assert root['root_key'] == review4_D('sui.f.root/3', problem_key=expected_problem_key,
            draw_point=root['draw_point'], draw_record_digest=root['draw_record_digest'],
            selection_draw=root['selection_draw'])


@pytest.mark.parametrize('stage', ('problem', 'root'))
@pytest.mark.parametrize('digest_name', ('input_key', 'input_digest', 'artifact_digest', 'result_digest', 'checked_calls'))
def test_review4_verification_digest_domains(review4_issued, stage, digest_name, record_property):
    record_property('rules', 'E-05,E-06,V-02')
    record_property('entry', 'ER')
    record_property('use', stage+':'+digest_name)
    data = review4_issued
    issued, envelope = data[stage]
    verified = ff.verify_f_math_result(issued.canonical_bytes, reader=data['case'].reader,
        registry=f.builtin_f_registry(), budget=BUDGET)
    # E-05:470: every envelope uses the FIRST call's captured dependencies.
    # The subsequent bind_draw remains in calls, never in input_key's image.
    dependencies = data['problem'][1]['claim']['value']['world_manifest']['dependencies']
    input_key = review4_D('sui.f.math_input/2', compiler=envelope['compiler'],
        input=envelope['input'], dependencies=dependencies)
    if stage == 'root':
        assert envelope['calls'][1]['args']['draw'] == data['draw']
        assert data['draw'] not in {row['point'] for row in dependencies['points']}
    expected = dict(input_key=input_key,
        input_digest=review4_D('sui.f.math_execution/2', input_key=input_key,
            calls=envelope['calls'], output=envelope['output']),
        artifact_digest=review4_D('sui.f.math_artifact/2', artifact=envelope),
        result_digest=review4_D('sui.f.math_result/2', compiler=envelope['compiler'], claim=envelope['claim']))
    if digest_name != 'checked_calls':
        assert getattr(verified, digest_name) == expected[digest_name]
        if digest_name != 'input_key':
            assert getattr(verified.certificate.value, digest_name) == expected[digest_name]
        return
    checked = verified.certificate.value.checked_calls
    assert [call.index for call in checked] == list(range(len(envelope['calls'])))
    outputs = {}
    for index, (call, audit) in enumerate(zip(envelope['calls'], checked)):
        assert audit.op == call['op']
        assert call['op'] == ('prepare' if index == 0 else 'bind_draw')
        previous = [] if index == 0 else [dict(index=0, output_digest=outputs[0])]
        value = data['problem' if index == 0 else 'root'][1]['claim']['value']
        outputs[index] = review4_D('sui.f.math_call_output/2', compiler=envelope['compiler'],
            index=index, op=call['op'], value=value)
        assert audit.output_digest == outputs[index]
        assert audit.input_digest == review4_D('sui.f.math_call_input/2', input_key=input_key,
            index=index, op=call['op'], args=call['args'], previous=previous)


@pytest.mark.parametrize('variant', ('record-digest', 'lookup-alias', 'world-key', 'problem-key', 'root-key'))
@pytest.mark.parametrize('bad', (False, True))
def test_review4_saved_manifest_and_key_pairs(review4_issued, variant, bad, record_property):
    record_property('rules', 'E-05,E-06,A-21')
    record_property('entry', 'ER')
    record_property('member', 'bad' if bad else 'good')
    record_property('use', variant)
    data = review4_issued
    stage = 'root' if variant == 'root-key' else 'problem'
    envelope = deepcopy(data[stage][1])
    if bad:
        claim = envelope['claim']['value']
        if variant == 'record-digest':
            row = claim['world_manifest']['dependencies']['points'][0]
            row['record_digest'] = 'sha256:' + '0' * 64
        elif variant == 'lookup-alias':
            rows = claim['world_manifest']['dependencies']['ref_lookups']
            row = next(row for row in rows if len(row['points']) == 2)
            row['points'] = row['points'][:1]
        else:
            key = variant.replace('-', '_')
            # Valid sha256 syntax, but a different, explicitly forbidden domain.
            claim[key] = review4_D('auth.wrong-domain/1', value=claim[key])
    got, exc = call_observed(lambda: ff.verify_f_math_result(review4_json(envelope),
        reader=data['case'].reader, registry=f.builtin_f_registry(), budget=BUDGET))
    if not bad:
        assert exc is None and isinstance(got, f.VerifiedMathResult), diagnostic(got, exc)
    else:
        kind, reason, pointer, fields = diagnostic(got, exc)
        assert (kind, reason) == ('FReplayMismatch', 'result_mismatch'), diagnostic(got, exc)
        assert_pointer(pointer, fields)


def test_fold_links_preserve_entry_branch_and_use():
    rows = {row.id: row for row in FIELD_TARGETS}
    for fold in REPRESENTATIVES:
        source, target = rows[fold.row], rows[fold.representative]
        assert fold.entry in source.entries and fold.entry in target.entries
        group = identity_group if fold.rule == 'A-01' else presence_group
        assert group(source) == group(target)
        if fold.row != fold.representative: assert fold.reason.startswith('代表: ')
