"""Independent F-b mutations: v0.12 designs, v0.15 reporting contract.

Targets were declared first in fb_mutants.py. Every case checks its identical
legal control first and stops the run on a legal-control violation. K-U cuts
retain ownership and histories; omitted continuation is not claimed complete.
Progress cases keep the target's full save/derive path. H-01..06 are excluded.
Only public signatures/docstrings/declarations and actual API outputs were
read; no CorrectWindow/Environment/checker implementation bodies were opened.
No environment variables, commit or Obsidian writes: latest three-file limit
overrides the general log rule. Measurements live in fb_mutants_results.json.
Normal: .venv/Scripts/python.exe -B -m pytest tests/test_fb_mutants.py -q -p no:cacheprovider
Explicit refresh: .venv/Scripts/python.exe -B tests/test_fb_mutants.py --record-all
-B prevents Python/pytest bytecode writes; no environment variable is used.
"""

import sys
sys.dont_write_bytecode = True
import json
from dataclasses import dataclass, replace, fields, is_dataclass
from functools import lru_cache
from time import perf_counter
import pytest
import fb_machine as m
import fb_check as check
import fb_scenes as scenes
import fb_mutants as mutants


@dataclass(frozen=True)
class Case:
    id: str
    target: str
    window: type
    scene: str
    boundary: str = ''
    allowed: tuple[str, ...] = ()


CASES = (
    Case('M-2a', 'INV-2.a', mutants.DrainRemovesPending, 'SC-04-DESC', 'ClaimStart', ('Drain',)),
    Case('M-2b', 'INV-2.b', mutants.PublishOmitsWork, 'SC-06-structure-verification-pending', 'PublishUnit:result', ('PublishUnit',)),
    Case('M-2c', 'INV-2.c', mutants.TerminalDropsSave, 'SC-04-DESC', '', ('RecognizeTerminal',)),
    Case('M-3b', 'INV-3.b', mutants.DescriptorChangesPurpose, 'SC-04-DESC', '', ('Drain',)),
    Case('M-3c', 'INV-3.c', mutants.DoubleRelease, 'SC-04-DESC', 'Release', ('Release',)),
    Case('M-4b', 'INV-4.b', mutants.PreparedSaltChanges, 'SC-03-normal', 'receipt-prepared', ('Drain',)),
    Case('M-4c', 'INV-4.c', mutants.FirstReceiptWrongReading, 'SC-03-normal'),
    Case('M-10a', 'INV-10.a', mutants.OverReserve, 'SC-04-DESC', 'ClaimStart', ('ClaimStart',)),
    Case('M-LR', 'L-RECEIPT', mutants.HideReceiptSave, 'SC-03-normal', 'receipt-prepared'),
    Case('M-1a', 'INV-1.a', mutants.DropReceiptAfterAck, 'SC-03-normal', 'receipt-ack', ('Drain',)),
    Case('M-1b', 'INV-1.b', mutants.ReacceptChangesReading, 'SC-03-normal'),
    Case('M-1c', 'INV-1.c', mutants.TwoReceiptSlots, 'SC-03-normal'),
    Case('M-2e', 'INV-2.e', mutants.HideHeldLaunch, 'M-minimal-held-launch', 'Launch'),
    Case('M-2f', 'INV-2.f', mutants.FalseResourceWait, 'SC-04-DESC', 'ClaimStart', ('Drain',)),
    Case('M-3a', 'INV-3.a', mutants.DoubleBodyEntry, 'SC-04-DESC', 'EnterWorker', ('EnterWorker',)),
    Case('M-4a', 'INV-4.a', mutants.SkipBodyWrite, 'SC-03-normal'),
    Case('M-8a', 'INV-8.a', mutants.DescriptorUsesLatest, 'SC-04-DESC', '', ('Drain',)),
    Case('M-8b', 'INV-8.b', mutants.ActualInputUsesLatest, 'SC-04-DESC', 'EnterWorker', ('EnterWorker',)),
    Case('M-10b', 'INV-10.b', mutants.ReleaseOnUnknown, 'SC-15-structure-Wr-no-stop', 'unknown-saved', ('RecognizeTerminal',)),
    Case('M-11a', 'INV-11.a', mutants.HideAccept, 'SC-03-normal'),
    Case('M-11b', 'INV-11.b', mutants.HideReceiptSave, 'SC-03-normal'),
    Case('M-15b', 'INV-15.b', mutants.UnknownBecomesSuccess, 'SC-15-structure-Wr-no-stop', 'unknown-saved', ('RecognizeTerminal',)),
    Case('M-5c', 'INV-5.c', mutants.PredictionAsParent, 'SC-06-structure-verification-pending', 'PublishUnit:completed', ('PublishUnit', 'PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite')),
    Case('M-6a', 'INV-6.a', mutants.CompletedUsesFinishAsStart, 'SC-06-structure-verification-pending', 'PublishUnit:completed', ('PublishUnit', 'PrepareOne', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite')),
    Case('M-9a', 'INV-9.a', mutants.VerificationResponseChanges, 'SC-06-structure-verification-pending', '', ('RecognizeTerminal',)),
    Case('M-2d', 'INV-2.d', mutants.HideDerivation, 'M-minimal-derive', 'PublishUnit:q-e1'),
    Case('M-LD', 'L-DERIVE', mutants.HideDerivation, 'M-minimal-derive', 'PublishUnit:q-e1'),
    Case('M-12b', 'INV-12.b', mutants.DrainRemovesPending, 'M-measure-owned', '', ('Drain',)),
    Case('M-13a', 'INV-13.a', mutants.EmptyInitialStartsCompute, 'SC-12-structure-measure-row', 'PublishUnit:segment', ('PublishUnit',)),
    Case('M-2e-claim', 'INV-2.e', mutants.HideClaimStart, 'SC-04-DESC', 'ClaimStart', ('ClaimStart',)),
    Case('M-5a', 'INV-5.a', mutants.PrepareUnsavedReference, 'SC-04-one-reference-missing', '', ('PrepareOne',)),
    Case('M-5b', 'INV-5.b', mutants.ClaimDuringRequestPreparation, 'SC-04-one-reference-missing', '', ('PrepareOne',)),
    Case('M-6b', 'INV-6.b', mutants.DoubleTerminalProcessing, 'SC-04-DESC', '', ('RecognizeTerminal','PrepareOne','PutBody','AddEntry')),
    Case('M-7c', 'INV-7.c', mutants.LateReceiptChangesRoot, 'SC-04-DESC', '', ('Drain',)),
    Case('M-11c', 'INV-11.c', mutants.HideAcceptWhileOccupied, 'SC-13-hung-receipt', 'ClaimStart', ('ClaimStart','Post','Accept','HostAck')),
    Case('M-13b', 'INV-13.b', mutants.NoInitialNoReception, 'M-empty-interval-receipt', 'interval-posted'),
    Case('M-15a', 'INV-15.a', mutants.ReceiptPreparationRecognizesEnd, 'SC-04-DESC', 'terminal-accepted', ('PrepareReceipt',)),
    Case('M-6c', 'INV-6.c', mutants.AcquisitionIntentCollapsed, 'M-two-acquisitions', 'Acquire', ('Acquire',)),
    Case('M-7a', 'INV-7.a', mutants.SingleReportMakesConflict, 'SC-04-DESC', '', ('RecognizeTerminal',)),
)

OPERATIONS = frozenset('''Post Accept HostAck PrepareReceipt PrepareOne PutBody
ConfirmBody AddEntry ConfirmWrite CompleteWrite BodyResponse EntryResponse
PublishUnit Recognize RecognizeTerminal ResolveWork ClaimStart Launch
LaunchResponse EnterWorker WorkerStep Stop Release Deliver DeliverBundle
HostUnknown Acquire Adopt HandoffPurpose Drain Wait RebuildWindow WindowFault
DuplicateWrapper IntervalEvent RequestInterval UndertakeInterval'''.split())


def action_text(a):
    def brief(x):
        if isinstance(x, m.Envelope):
            return f'{x.run}:{x.number}'
        if isinstance(x, m.Point):
            return x.cid[:12]
        return str(x)
    return f"{a.operation}({','.join(brief(x) for x in a.target)})/{a.outcome}"


def renamed_declaration(value, names):
    """Copy a public finite recipe under new identities, before execution."""
    if isinstance(value,str):
        return names.get(value,value)
    if is_dataclass(value):
        return replace(value,**{f.name:renamed_declaration(getattr(value,f.name),names) for f in fields(value)})
    if isinstance(value,tuple):
        return tuple(renamed_declaration(x,names) for x in value)
    if isinstance(value,frozenset):
        return frozenset(renamed_declaration(x,names) for x in value)
    return value


@lru_cache(None)
def prepared_scene(scene_id, boundary, allowed):
    base_id = {'M-minimal-derive':'SC-08-structure-e1-then-other','M-minimal-held-launch':'SC-13-hung-receipt','M-two-acquisitions':'SC-06-structure-verification-pending','M-measure-owned':'SC-12-structure-measure-row','M-empty-interval-receipt':'SC-20-empty-receipts-interval'}.get(scene_id,scene_id)
    scene = next(s for s in scenes.SCENES if s.id == base_id)
    if scene_id=='M-minimal-derive':
        # Declared before any prefix: omit the unrelated later e2 input only.
        # All histories/capabilities and the complete e1 declaration survive.
        obs=scene.e0.observation_declarations
        obs=replace(obs,derivations=tuple(b for b in obs.derivations if b.trigger_slot=='e1'))
        scene=replace(scene,e0=replace(scene.e0,postings=tuple(p for p in scene.e0.postings if p.id!='e2'),observation_declarations=obs))
    if scene_id=='M-minimal-held-launch':
        scene=replace(scene,e0=replace(scene.e0,postings=tuple(p for p in scene.e0.postings if p.id=='boot')))
    if scene_id=='M-empty-interval-receipt':
        receipt=next(s for s in scenes.SCENES if s.id=='SC-03-normal')
        scene=replace(scene,e0=replace(scene.e0,postings=receipt.e0.postings))
    if scene_id=='M-measure-owned':
        interval=scene.e0.intervals[0]
        key=m.CompletionKey('O-04',(interval.route_epoch,interval.id),'handle',m.WorkKey(interval.work))
        route=m.HandoffRoute(key,m.Owner('P.work',interval.work))
        scene=replace(scene,e0=replace(scene.e0,handoff_routes=(route,)))
    if scene_id=='M-two-acquisitions':
        e0=scene.e0
        first=e0.acquisitions[0]
        gplan=next(p for p in e0.plans if p.unit==first.record.unit)
        work=gplan.works[0].work_id
        names={first.id:first.id+'-second',gplan.unit:gplan.unit+'-second',work:work+'-second'}
        newplan=renamed_declaration(gplan,names)
        e0=replace(e0,acquisitions=e0.acquisitions+(renamed_declaration(first,names),),
                   plans=e0.plans+(newplan,),programs=e0.programs+tuple(renamed_declaration(p,names) for p in e0.programs if p.work==work))
        # Converter consumes declarations only. Retain the scene's independent
        # public artifact/interval/reference declarations; add the copied ports.
        obs=e0.observation_declarations
        extra=m.declare_observation_e0(e0)
        e0=replace(e0,observation_declarations=replace(obs,plans=extra.plans,descriptors=extra.descriptors,
                    acquisitions=extra.acquisitions,verifications=extra.verifications,completions=extra.completions))
        scene=replace(scene,e0=e0)
    scenario, states, edges, enabled = scenes.instantiate(scene)
    prefix = tuple(e.action for e in edges)
    if boundary == 'interval-posted':
        env=m.Environment(scenario.e0)
        state=env.initial()
        w=m.CorrectWindow(scenario.e0)
        prefix=()
        for op in ('RequestInterval','Post'):
            actions=env.actions(state)+w.enabled(m.View(state.core,state.controls,state.evidence))
            a=next(a for a in actions if a.operation==op and a.outcome=='normal')
            state=env.step(state,a,w).state
            prefix+=(a,)
        scenario=replace(scenario,initial=state)
    elif boundary == 'terminal-accepted':
        end = next(e.source for e in reversed(edges) if e.action.operation == 'PrepareReceipt')
        scenario = replace(scenario, initial=states[end])
        prefix = tuple(e.action for e in edges[:end])
    elif boundary == 'unknown-saved':
        env = m.Environment(scenario.e0)
        state = scenario.initial
        window = m.CorrectWindow(scenario.e0)
        for op in ('Accept', 'HostAck', 'PrepareReceipt', 'PutBody', 'AddEntry', 'ConfirmWrite', 'CompleteWrite'):
            view = m.View(state.core, state.controls, state.evidence)
            actions = env.actions(state) + window.enabled(view)
            action = next(a for a in actions if a.operation == op and a.outcome == 'normal')
            state = env.step(state, action, window).state
            prefix += (action,)
        scenario = replace(scenario, initial=state)
    elif boundary.startswith('receipt-'):
        env = m.Environment(scenario.e0)
        state = env.initial()
        window = m.CorrectWindow(scenario.e0)
        selected = []
        operations = ['Post', 'Accept', 'HostAck']
        if boundary == 'receipt-prepared':
            operations += ['PrepareReceipt']
        for op in operations:
            view = m.View(state.core, state.controls, state.evidence)
            actions = env.actions(state) + window.enabled(view)
            action = next(a for a in actions if a.operation == op and a.outcome == 'normal')
            state = env.step(state, action, window).state
            selected.append(action)
        scenario = replace(scenario, initial=state)
        prefix = tuple(selected)
    elif boundary:
        operation, _, target = boundary.partition(':')
        edge = next(e for e in edges if e.action.operation == operation
                    and (not target or e.action.target == (target,)))
        scenario = replace(scenario, initial=states[edge.source])
        prefix = tuple(e.action for e in edges[:edge.source])
    if scene_id=='M-minimal-derive':
        env=m.Environment(scenario.e0)
        state=scenario.initial
        window=m.CorrectWindow(scenario.e0)
        for op in ('ResolveWork','ClaimStart','Launch','EnterWorker'):
            actions=window.enabled(m.View(state.core,state.controls,state.evidence))
            a=next(a for a in actions if a.operation==op)
            state=env.step(state,a,window).state
            prefix+=(a,)
        scenario=replace(scenario,initial=state,cut=m.Cut('uncut'))
    if scene_id=='M-two-acquisitions':
        env=m.Environment(scenario.e0)
        w=m.CorrectWindow(scenario.e0)
        state=scenario.initial
        a=next(a for a in w.enabled(m.View(state.core,state.controls,state.evidence)) if a.operation=='Acquire' and a.target==(scenario.e0.acquisitions[0].id,))
        scenario=replace(scenario,initial=env.step(state,a,w).state)
        prefix+=(a,)
    if scene_id=='M-measure-owned':
        env=m.Environment(scenario.e0)
        w=m.CorrectWindow(scenario.e0)
        state=scenario.initial
        a=next(a for a in w.enabled(m.View(state.core,state.controls,state.evidence)) if a.operation=='HandoffPurpose')
        scenario=replace(scenario,initial=env.step(state,a,w).state)
        prefix+=(a,)
    if allowed:
        cut = m.Cut('K-U single boundary', OPERATIONS - frozenset(allowed) - {'Wait'},
                    ('Only named local boundary; other continuation untested; all ownership retained.',))
        scenario = replace(scenario, cut=cut)
    elif scene_id=='M-minimal-held-launch':
        scenario=replace(scenario,cut=m.Cut('uncut'))
    scenario = replace(scenario, id=f'{scene_id}:{boundary or "tail"}', max_states=25 if scene_id=='M-two-acquisitions' else 4999,
                       initial_connection=f'Public legal prefix: {len(prefix)} steps; {boundary or scene.prefix}')
    return scenario, prefix


def findings(report):
    return tuple(f for row in report.rows for f in row.violations)


@lru_cache(None)
def legal_control(scene_id, boundary, allowed):
    scenario, prefix = prepared_scene(scene_id, boundary, allowed)
    start = perf_counter()
    graph = m.explore(scenario, window=m.CorrectWindow(scenario.e0))
    report = check.check_exploration(scenario, graph)
    errors = findings(report)
    if errors or report.contract_violations:
        pytest.exit(f'STOP: legal control {scenario.id}: {errors!r}; boundary={report.contract_violations!r}', returncode=2)
    return scenario, prefix, graph, report, perf_counter() - start


def changed_boundary(case, graph, scenario):
    """Actual altered public decision; no marker is placed in model data."""
    ordinary, wrong = m.CorrectWindow(scenario.e0), case.window(scenario.e0)
    candidates = []
    if 'enabled' in case.window.__dict__:
        for index, state in enumerate(graph.states):
            view = m.View(state.core, state.controls, state.evidence)
            removed = set(ordinary.enabled(view)) - set(wrong.enabled(view))
            if removed:
                candidates.append((graph.trace(index), index, 'missing ' + ','.join(sorted(action_text(a) for a in removed))))
    else:
        for edge in graph.edges:
            state = graph.states[edge.source]
            view = m.View(state.core, state.controls, state.evidence)
            try:
                before = ordinary.dispatch(view, edge.action)
                after = wrong.dispatch(view, edge.action)
            except m.Disabled:
                continue
            if before != after:
                candidates.append((graph.trace(edge.source) + (edge.action,), edge.target, 'changed Decision'))
    return min(candidates, key=lambda x: (len(x[0]), tuple(action_text(a) for a in x[0]))) if candidates else None


def actual_premise(case, scenario, graph, witness):
    """Paper premises checked on reached public states/events, not row flags."""
    if witness is None:
        return dict(holds=False, reason='mutation was not exercised')
    if case.id in ('M-2d','M-LD'):
        statuses=check.derive_observation_status(scenario.e0.observation_declarations,
                                               graph.states[0].evidence.observation_trace)
        return dict(holds=False, reason='ReadyN/Match/Discharge connection is explicitly unavailable',
                    declared_statuses=tuple((s.eligible,s.published,s.discharged,s.unsupported) for s in statuses))
    if case.id=='M-2e':
        state=graph.states[0]
        row=next(w for w in state.core.p.work if w.phase=='Starting')
        points={e.point for e in state.core.e}
        resolved=dict(row.resolutions)
        saved=all((resolved.get(p,p) in points) for p in row.descriptor.required|row.descriptor.permissions)
        offered=m.CorrectWindow(scenario.e0).enabled(m.View(state.core,state.controls,state.evidence))
        return dict(holds=bool(row.held and row.token and saved and any(a.operation=='Launch' for a in offered)),
                    phase=row.phase, held=row.held, required_and_permissions_saved=saved,
                    token_present=bool(row.token), missing='Launch', checker_applicability_is_not_the_premise=True)
    edges=[e for e in graph.edges if e.source!=e.target]
    if case.id=='M-2c':
        for e in edges:
            before,after=graph.states[e.source],graph.states[e.target]
            for c in after.core.p.conditions:
                if c.key.kind=='save' and getattr(c.key.target,'unit','').startswith('terminal:') and not c.unmet:
                    was=next(x for x in before.core.p.conditions if x.key==c.key)
                    saved=any(x.header.record.contract.name=='sui.fb.work_terminal' for x in after.core.e)
                    return dict(holds=bool(was.unmet) and not saved, closed=repr(c.key), terminal_saved=saved)
    if case.id=='M-2f':
        for e in edges:
            before,after=graph.states[e.source],graph.states[e.target]
            reserves=[x for x in before.evidence.observation_trace.events if x.tag=='Reserve']
            for w in after.core.p.work:
                if w.purposes:
                    fits=all(n<=dict(scenario.e0.allocation)[resource] for resource,n in w.descriptor.need)
                    closed=any(c.key.kind=='run' and getattr(c.key.target,'work',None)==w.descriptor.work_id
                               and not c.unmet for c in after.core.p.conditions)
                    return dict(holds=not reserves and fits and closed, actual_prior_reservations=len(reserves),
                                need=w.descriptor.need, allocation=scenario.e0.allocation,
                                reason=w.purposes[0].reason_id, run_condition_closed=closed)
    if case.id=='M-3c':
        for e in edges:
            releases=[x for x in e.actual_events if x.tag=='Release']
            if len(releases)>1:
                return dict(holds=releases[0].key==releases[1].key,
                            release_count=len(releases), same_reservation=repr(releases[0].key))
    if case.id=='M-5b':
        for e in edges:
            after=graph.states[e.target]
            reserved=any(x.tag=='Reserve' for x in e.actual_events)
            for w in after.core.p.work:
                ref=w.descriptor.request
                slot=next((s for u in after.core.p.units if u.id==ref.unit for s in u.slots if s.plan.slot==ref.slot),None)
                if reserved and slot and slot.prepared:
                    saved=slot.prepared.point in {x.point for x in after.core.e}
                    return dict(holds=not saved and ref in w.descriptor.required, actual_reserve=True,
                                request_saved=saved, request=repr(ref), action=e.action.operation)
    if case.id=='M-6c':
        for e in edges:
            before,after=graph.states[e.source],graph.states[e.target]
            if e.action.operation=='Acquire' and len(after.evidence.ea.acquisitions)>len(before.evidence.ea.acquisitions):
                actual=after.evidence.ea.acquisitions[-1]
                requested=e.action.target[0]
                if actual.intent!=requested:
                    first,current=(next(i for i in scenario.e0.acquisitions if i.id==n) for n in (actual.intent,requested))
                    equal=(first.reader,first.targets)==(current.reader,current.targets)
                    return dict(holds=equal, requested_intent=requested, actual_intent=actual.intent,
                                equal_reader_and_targets=equal, actual_intents=tuple(a.intent for a in after.evidence.ea.acquisitions))
    if case.id=='M-7a':
        for state in graph.states:
            for u in state.core.p.units:
                for slot in u.slots:
                    if slot.plan.contract.name=='sui.fb.conflict':
                        reports=slot.plan.content.get('reports')
                        saved={e.point for e in state.core.e}
                        notices=[e for e in state.evidence.eh.originals if e.event.kind=='WorkFinished']
                        return dict(holds=len(set(reports))==1 and set(reports)<=saved and len(notices)==1,
                                    reports=len(set(reports)), work_notifications=len(notices),
                                    contract=slot.plan.contract.name, rule=slot.plan.content.get('rule'))
    if case.id=='M-9a':
        for state in graph.states:
            replies=dict(state.evidence.ea.replies)
            for u in state.core.p.units:
                for slot in u.slots:
                    if slot.plan.contract.name=='sui.fb.verification_result':
                        work=slot.plan.content.get('work')
                        actual=replies[work].response
                        issued=slot.plan.content.get('reply').response
                        return dict(holds=actual!=issued, work=work, actual_reply=actual, published_reply=issued)
    if case.id=='M-12b':
        for e in edges:
            before,after=graph.states[e.source],graph.states[e.target]
            for c in before.core.p.conditions:
                if c.key.obligation=='O-04' and c.key.kind=='handle' and c.owner.location=='P.work':
                    existed=any(w.descriptor.work_id==c.owner.key for w in before.core.p.work)
                    exists=any(w.descriptor.work_id==c.owner.key for w in after.core.p.work)
                    reports=[x for x in after.evidence.eh.originals if x.event.kind=='SegmentReport']
                    return dict(holds=existed and not exists and not reports,
                                owner_after_legal_handoff=repr(c.owner), owner_row_exists=exists,
                                unreported_cells=len(scenario.e0.intervals[0].cells), reports=len(reports))
    if case.id=='M-13a':
        for state in graph.states:
            for u in state.core.p.units:
                bootstrap=any(s.plan.content.get('origin')=='bootstrap' for s in u.slots)
                rows=[w for w in state.core.p.work if w.descriptor.work_id in u.works and w.descriptor.stage=='Wr']
                if bootstrap and rows:
                    return dict(holds=scenario.e0.initial is None, initial_none=scenario.e0.initial is None,
                                process_origin='bootstrap', issued_stage='Wr', work=rows[0].descriptor.work_id,
                                original_stage='MeasureSegment')
    if case.id=='M-13b':
        return dict(holds=True, initial_none=scenario.e0.initial is None, removed=witness[2],
                    interval_declared=bool(scenario.e0.intervals), relational_row_requires_a_cross_initial_pair=True)
    # For the remaining cases: the reached action changes actual public state,
    # or removes an ordinary enabled service. This is independent of findings.
    if 'enabled' in case.window.__dict__:
        return dict(holds=True, missing=witness[2], reached_state=witness[1])
    env=m.Environment(scenario.e0)
    ordinary=m.CorrectWindow(scenario.e0)
    for e in edges:
        if graph.trace(e.source)+(e.action,)==witness[0]:
            actual=graph.states[e.target]
            correct=env.step(graph.states[e.source],e.action,ordinary).state
            return dict(holds=actual!=correct, action=action_text(e.action), actual_public_state_changed=actual!=correct)
    return dict(holds=False, reason='no changed actual edge localized')


def shortest_finding(graph, hits, witness):
    """Shortest counterexample inside this BFS graph; prefix is kept separate."""
    candidates=[]
    for f in hits:
        loc=f.location
        if 'relation' in loc:
            k=loc.index('relation')
            a,b=graph.trace(loc[k+1]),graph.trace(loc[k+2])
            candidates.append((max(len(a),len(b)),a,b,f))
        elif 'edge' in loc:
            k=loc.index('edge')
            for e in graph.edges:
                if (e.source,e.target)==(loc[k+1],loc[k+2]):
                    path=graph.trace(e.source)+(e.action,)
                    candidates.append((len(path),path,(),f))
        elif 'state' in loc:
            k=loc.index('state')
            path=graph.trace(loc[k+1])
            candidates.append((len(path),path,(),f))
        elif loc==('graph',) and len(graph.states)==1:
            candidates.append((0,(),(),f))
    if candidates:
        _,path,other,f=min(candidates,key=lambda x:(x[0],tuple(action_text(a) for a in x[1]),repr(x[3].location)))
        return dict(trace=tuple(action_text(a) for a in path), paired_trace=tuple(action_text(a) for a in other),
                    location=f.location, message=f.message, minimum='BFS local graph; same fixed legal prefix')
    return dict(trace=tuple(action_text(a) for a in witness[0]) if witness else (), paired_trace=(),
                location=hits[0].location if hits else None, message=hits[0].message if hits else None,
                minimum='mutation boundary only; target finding not localized' if hits else 'shortest exercised wrong boundary; target not detected')


HISTORICAL_RESUMPTION_AUDIT = """
2通目の時点の監査。数値・ゆう待ち・自己書換えは当時。現在値は別JSONを参照。
Final commands: .venv/Scripts/python.exe -m pytest tests/test_fb_mutants.py -q
-p no:cacheprovider => 13 failed / 27 passed in 110.07 s (39 mutants + denominator).
Same command with -k recorded_population => 1 passed / 39 deselected, 0.73 s.
After the full run, re-import exposed an Envelope constructor in a recorded
Finding.location. Four-point record audit: (1) persistence must preserve the
observation, (2) typed location metadata, not a model predicate, was the target,
(3) full measurements were intact but fresh import failed, (4) recursive report
serialization was missing. report_data now stores typed locations as strings.
Fresh import and all 39 records/45 rows/one-public-override/BFS traces passed.
No mutation or checker result was changed by this report-format repair.
Serialization regression: same command with -k M-1b => 1 passed / 39 deselected
in 7.41 s; it produced a fresh typed Envelope location through the real checker
and checkpoint. A further -k recorded_population passed after fresh import.

Read boundary: paper and public declarations/signatures/docstrings, SCENES/E0/
instantiate, test_fb_scenes recorded result data, actual public calls. Never
opened CorrectWindow/Environment/checker predicate bodies or Claude's mutants.
During API inventory, model_seal's signature/docstring (not a predicate/body)
was also inspected; it is not in PUBLIC_SCENE_API. It was NOT called or reused.

Original 10 failures, four-point audit (meaning / target-route / +/- / missing):
M-2c (a -> c): dropping T's unit left save custody in P.work. Revised mutation
closes the actual T save condition before Saved(T). Same prefix/control zero.
M-3c (c): two actual Release events with the same WorkToken. 10.b catches it,
3.c does not. No checker repair, no successive guessing of its implementation.
M-LR (b -> identified): re-presentation omissions prevented the path check.
Legal Post/Accept/HostAck/PrepareReceipt prefix gives an uncut 1-state mutant,
5-state control; no omitted edge. Actual fair unsaved dead-end.
M-2e (c candidate): the reserved Starting row has its token, Held=Need, saved
required references/permissions and normal Launch offered by CorrectWindow.
Uncut 3-state control/1-state mutant still reports checker_reached=0. This
population omission must not be confused with physical premise non-reachability.
M-2e-claim separately checks the pre-reservation branch; one hit is not coverage
of all stage clauses. A row can be identified AND retain an undetected variant.
M-2f (a -> c): merely attaching an unused Excuse was insufficient. The revised
mutation actually closes run using B-RESOURCE with zero prior reservations
and Need<=allocation. Ownership is retained. Typed runtime fields are recorded.
M-9a (c): actual EA Success becomes Published V Rejected; 2.b catches the plan
difference, 9.a does not. This is the publication clause, not real F-a issuance.
M-2d/M-LD (b/connection): rerun without Cut, after a legal Hung start, with the
unrelated e2 input omitted from pre-run declarations. 10/1 states, no frontier.
ReadyN/Match/Discharge remain explicitly unconnected (/2/permission closure).
A diagnostic initially queried the generic E0 converter instead of the scene's
observation_declarations; this reference error was corrected, not hidden.
M-12b (a -> c): original H owner survived removal of MeasureSegment. The new E0
declares HandoffRoute; the public legal prefix saves k and transfers handle
to P.work. Drain removes that sole live owner with all four cells unreported.
M-13a (a -> c candidate): old boundary PublishUnit:interval did not exist.
Public trace identifies segment. The revised decision changes both actual
publication descriptor and live descriptor to Wr (initial=None, process
origin=bootstrap), not just a private window copy. Other 2.b/3.b/8.a findings
are recorded and are not substituted for 13.a.

Additional audits:
M-6b: duplicate Publish of the SAME unit was a retry, not proof of two logical
consumptions. Revised to two separately named ordinary T slots; full save
continuation detected 6.b (714 states/169.574 s). Removing unnecessary
ConfirmWrite/CompleteWrite gives 70 states/17.807 s with the same target hit.
M-6c: the first all-retry version hit a 25-state frontier and was NOT counted.
The revised dedup bug reuses the unique equal-target prior acquisition; after
two actual acquisitions it takes the ordinary path. Three states complete.
M-11c: a tail after ClaimStart lacked the comparison state. Start before Claim
and include Post/Accept/HostAck: the relation actually compares equal receipt
projections with different occupied seats; 11.c is detected.
M-13b: SC-03 alone has no interval; SC-20 has no Post. A declared combination
adds SC-03's opaque input to SC-20. A guessed operation spelling failed twice:
four-point stop/review identified the public operation RequestInterval (not
UndertakeInterval). Correct two-step prefix is RequestInterval, Post. The row
reports not_run; no relational discrimination is claimed.
An earlier full SC-20 + 200-state acquisition run was interrupted before a
complete report; it is NOT a completed measurement or a legal-control pass.

Recurrence: checker-fix cycles=0; undetected candidates are first-round
reproductions. Fixture revisions above were reviewed by the four points.
No fix to any checker/window/scene, no marker in model data, no env var, no
commit. Only the two authorized files are explicitly written. Each completed
case checkpoints its real results here BEFORE asserting the target.

Additional assumption A-M-XC (naming/representation only, meaning changes=0):
paper 1045's Xc fields use Object, reports tuple, and the existing model's
PATH-LINK-GENERATION/E/diagnostic reference spelling. No new conflict rule or
numeric meaning. Existing model assumptions are inherited, not recounted.

M-01: closed (45 predeclared rows plus explicit scope reasons in fb_mutants).
M-02: do NOT call closed solely because >=23 rows are identified. INV-7.b has
no implemented independent mutant/control yet; ReadyN and cross-initial
relationships remain unconnected. Report each candidate and retain red tests.
Shortest means BFS-shortest inside the named scene AFTER its fixed, actual
legal prefix. It does not claim global minimization from an empty machine.
The relation witness carries both paths. Every full prefix is stored.

Obsidian Sessions/Projects/Knowledge/Heat NOT updated: task-specific two-file
write restriction. This file is the allowed local session record; transcript
session id/path is unconfirmed. Reused knowledge: A-G failure taxonomy and
independent declarations/actual observations, applicable; no single-cause
inference. No external web sources. The preceding measured outcomes and
limitations, not another agent's approval, are the evidence.
"""


from pathlib import Path
from hashlib import sha256
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import argparse

ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / 'tests/fb_mutants_results.json'
SOURCE_PATHS = (
    'specs/関所F_Fb_今の約束.md', 'tests/fb_check.py', 'tests/fb_machine.py',
    'tests/fb_scenes.py', 'tests/fb_mutants.py', 'tests/test_fb_mutants.py',
)
REPORT_ROOT = Path('C:/Users/you11/AppData/Local/Temp/claude/C--Users-you11-Desktop-iku/'
                   '20f79958-a16a-4877-afea-6a0e83bffc56/scratchpad')
OUT_OF_SCOPE = {
    'INV-7.b': 'v0.15 (12):1887, (11):1876 (old :1509): SC-18全16枝は実装の段へ。合法IC/IG/IAとUseDeps対応をF-a実物へ接続する。',
    'INV-9.b': '866/1793/1876: SC-07a/bの合法採用・認証・現在系列をF-a実物へ接続する。',
    'INV-12.a': '872/1087/1799/1876: StartedだけではSupportにならない。生成契約別の意味・被覆を実装の段へ。',
    'INV-14.a': '876/1803/1876: 合法IE/IDとDraw要求・実入場の正負対照を実装の段へ。',
    'INV-14.b': '877/1804/1876: 合法Drawのfirst・Unknown・精密化継続を実装の段へ。',
    'INV-16.a': '880/1807/1876: 保存済み評価・認証Selectedの合法前段を実装の段へ。',
    'INV-16.b': '881/1808/1876: PR/Draw/problem/artifact/Selectedの全対応を実装の段へ。',
}
ROW_ORDER = tuple(line.split(' | ')[0] for line in mutants.__doc__.splitlines()
                  if line.startswith(('INV-', 'L-')) and ' | ' in line)
STATUS_LABELS = dict(identified='識別力確認済み', not_detected='検出できず',
                     unreached_or_incomplete='未到達・未完', out_of_scope='範囲外')
CONFIRMATION_LABELS = ('確認済み', '未確認', '未接続', '未完', '範囲外★')
REPORTED_UNCONNECTED = frozenset('''INV-2.a INV-2.b INV-2.c INV-2.d INV-2.e INV-2.f
INV-4.c INV-5.a INV-5.b INV-7.a INV-7.b INV-7.c INV-8.a INV-8.b INV-9.a INV-9.b
INV-12.a INV-12.b INV-13.b INV-14.a INV-14.b INV-15.b INV-16.a INV-16.b L-DERIVE'''.split())


def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')


def source_hashes():
    # Digest only; never display or interpret machine/checker implementation.
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def report_data(value):
    if is_dataclass(value):
        return repr(value)
    if isinstance(value, dict):
        return {k: report_data(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [report_data(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((report_data(v) for v in value), key=repr)
    return value


def read_evidence(previous):
    """Read supplied reports and ONLY the scene results JSON's observation record.

    Never import/execute test_fb_scenes or inspect its test bodies. If temporary
    reports expire, preserve their verbatim rows/hashes as a historical snapshot.
    """
    evidence = {'check2_rows': [], 'issue_rows': [], 'scenes': [], 'sources': []}
    for turn, destination in ((2, 'check2_rows'), (3, 'issue_rows')):
        path = REPORT_ROOT / f'fb_model_check2_turn{turn}_report.md'
        if not path.exists():
            assert previous.get(destination), f'missing public evidence: {path}'
            evidence[destination] = deepcopy(previous[destination])
            evidence['sources'].extend(dict(s, reread=False) for s in previous['sources']
                                       if s['kind'] == destination)
            continue
        raw = path.read_bytes()
        lines = raw.decode('utf-8-sig').splitlines()
        for number, line in enumerate(lines, 1):
            if not line.startswith('| '):
                continue
            columns = [part.strip() for part in line.strip('|').split('|')]
            if turn == 2 and columns[0] in ROW_ORDER:
                evidence[destination].append(dict(target=columns[0], kind=columns[1],
                    detail=columns[2], paper=columns[3], source=f'{path.as_posix()}:{number}'))
            if turn == 3 and columns[0].startswith('C-O'):
                evidence[destination].append(dict(condition=columns[0], detail=columns[1],
                    reference=columns[2], source=f'{path.as_posix()}:{number}'))
        evidence['sources'].append(dict(kind=destination, path=path.as_posix(),
            sha256=sha256(raw).hexdigest(), read_range=f'全文 1-{len(lines)}; tables retained', reread=True))
    path = ROOT / 'tests/fb_scenes_results.json'
    observed = json.loads(path.read_text(encoding='utf-8'))['records']['RECORDED_OBSERVATION_EVIDENCE']
    manifest = {s['id']: s for s in observed['manifest']}
    for result in observed['latest_reports']:
        declaration = manifest[result['id']]
        evidence['scenes'].append({
            'id': result['id'], 'scope_class': declaration['scope_class'],
            'scope_reason': declaration['scope_reason'], 'has_e0': declaration['has_e0'],
            'applicable': declaration['applicable'], 'execution': result['execution'],
            'capture': result.get('capture'), 'paper_version': result.get('paper_version', observed['paper_version']),
            'reach': result.get('reach', {}),
            'rows': {target: result.get('rows', {}).get(target, {}) for target in declaration['applicable']},
            'rerun_in_this_task': False,
        })
    evidence['sources'].append(dict(kind='scenes', path=path.relative_to(ROOT).as_posix(),
        sha256=sha256(path.read_bytes()).hexdigest(),
        read_range='records.RECORDED_OBSERVATION_EVIDENCE: full value only; migration/report not used',
        reread=True))
    assert {r['target'] for r in evidence['check2_rows']} == set(ROW_ORDER)
    assert {r['target'] for r in evidence['check2_rows'] if r['kind'] != '—'} == REPORTED_UNCONNECTED
    assert len(evidence['issue_rows']) == 8  # O12 EV/S retained in its full text.
    assert len(evidence['scenes']) == 193
    sc18 = [s for s in evidence['scenes'] if s['id'].startswith('SC-18-')]
    assert len(sc18) == 16 and all(s['scope_class'] == 'b' and not s['has_e0'] for s in sc18)
    return evidence


def limitation_status(message):
    lower = message.lower()
    if any(word in lower for word in ('未接続', '未対応', 'unconnected', 'unavailable', 'partial_observation_contract')):
        return '未接続'
    if any(word in lower for word in ('incomplete', 'frontier', '上限')):
        return '未完'
    return '未確認'


def case_confirmation(result):
    if result['status'] in ('identified', 'not_detected'):
        return '確認済み'
    if not result['complete'] or not result['control_complete']:
        return '未完'
    if any(limitation_status(reason) == '未接続' for reason in result['limitations']):
        return '未接続'
    return '未確認'


def aggregate_confirmation(branches, scope_out=False):
    if scope_out:
        return '範囲外★'
    statuses = {b['confirmation_status'] for b in branches} - {'範囲外★'}
    # Representative display only; all statuses/counts remain alongside.
    for status in ('未接続', '未完', '未確認'):
        if status in statuses:
            return status
    return '確認済み' if statuses == {'確認済み'} else '未確認'


def discrimination_class(target, branches):
    """v0.15:1620-1629: scope > confirmed miss > +/- success > other."""
    if target in OUT_OF_SCOPE:
        return 'out_of_scope'
    verified = [b for b in branches if b['confirmation_status'] == '確認済み']
    if any(b['identification_result'] == '違反対照の見逃し' for b in verified):
        return 'not_detected'
    if any(b['identification_result'] == '正負の対照による識別成功' for b in verified):
        return 'identified'
    return 'unreached_or_incomplete'

def row_table(results, evidence):
    rows = []
    for target in ROW_ORDER:
        cases = [r for r in results if r['target'] == target]
        branches = []
        for result in cases:
            branches.append(dict(id=result['id'], origin='current_mutant_contrast',
                scope=result['scene'], confirmation_status=case_confirmation(result),
                execution='実行済み', reached=result['premise']['holds'], complete=result['complete'],
                normative_result=result['normative_result'], checker_output=result['checker_output'],
                identification_result=result['identification_result'], legal_control=result['control'],
                source=f"cases/{result['id']}", detail='同じE0・前段・Cutの正負対照。未到達/接続不足は成功にしない。'))
        limits = {}
        for result in cases:
            for side, messages in (('mutant', result['limitations']), ('control', result['control_limitations'])):
                for message in messages:
                    limits.setdefault(message, []).append(f"{result['id']}:{side}")
        for message, sources in sorted(limits.items()):
            branches.append(dict(id='limitation:' + sha256(message.encode()).hexdigest()[:16],
                origin='public_check_output', confirmation_status=limitation_status(message),
                execution='公開報告を実行で取得', reached='この制約の対象枝は未確認',
                normative_result='未判定', checker_output=message, identification_result='判定未成立',
                detail=message, source=sources))
        for reported in evidence['check2_rows']:
            if reported['target'] == target and reported['kind'] != '—':
                branches.append(dict(id='check2:' + target, origin='checker_author_public_report',
                    confirmation_status='未接続', execution='今回の枝の実行はnot_run',
                    reached='出力/接続依存の一覧。全枝の実到達を主張しない',
                    normative_result='未判定', checker_output='未接続と報告', identification_result='判定未成立',
                    detail=reported['detail'], report_kind=reported['kind'], paper=reported['paper'], source=reported['source']))
        if target in ('INV-2.a', 'INV-2.c'):
            for issue in evidence['issue_rows']:
                branches.append(dict(id='issue:' + issue['condition'], origin='checker_author_issue_report',
                    confirmation_status='未接続', execution='当係では全枝を実行していない',
                    reached='有限接続済み枝と未接続の残りを区別', normative_result='未判定',
                    checker_output='limitationsへ未接続と報告', identification_result='判定未成立',
                    detail=issue['detail'], source=issue['source'], reference=issue['reference']))
        for scene in evidence['scenes']:
            if target not in scene['applicable']:
                continue
            prior = scene['rows'].get(target, {})
            classification = prior.get('classification', '')
            if scene['scope_class'] == 'b':
                status = '範囲外★'
            elif '未完' in classification or '未完' in scene['execution']:
                status = '未完'
            elif '未接続' in classification:
                status = '未接続'
            else:
                status = '未確認'  # historical positives are not current +/- evidence
            branches.append(dict(id='scene:' + scene['id'], origin='historical_scene_output',
                confirmation_status=status, execution='今回not_run', previous_execution=scene['execution'],
                previous_classification=classification, capture=scene['capture'], paper_version=scene['paper_version'],
                reached=scene['reach'], normative_result='今回未判定', checker_output=prior,
                identification_result='範囲外' if status == '範囲外★' else '判定未成立',
                detail=scene['scope_reason'], source='evidence/scenes/' + scene['id']))
        if target in OUT_OF_SCOPE:
            # The owner's decision applies to this WHOLE row. Keep the old
            # public connection status as evidence, not its current scope.
            for branch in branches:
                branch['source_confirmation_status'] = branch['confirmation_status']
                branch['confirmation_status'] = '範囲外★'
                branch['current_scope_basis'] = OUT_OF_SCOPE[target]
            branches.append(dict(id='scope:' + target, origin='owner_paper_decision',
                confirmation_status='範囲外★', execution='not_run', reached=False,
                normative_result='今回範囲外', checker_output='評価対象外', identification_result='範囲外',
                detail=OUT_OF_SCOPE[target], source='specs/関所F_Fb_今の約束.md:1876,1887-1888'))
        status = discrimination_class(target, branches)
        confirmation = aggregate_confirmation(branches, target in OUT_OF_SCOPE)
        reasons = [dict(branch=b['id'], confirmation_status=b['confirmation_status'], reason=b['detail'])
                   for b in branches if b['confirmation_status'] != '確認済み']
        rows.append(dict(target=target, status=status, label=STATUS_LABELS[status],
            confirmation_status=confirmation, branches=branches,
            branch_counts={k: sum(b['confirmation_status'] == k for b in branches) for k in CONFIRMATION_LABELS},
            cases=[r['id'] for r in cases], missed_cases=[r['id'] for r in cases if r['status'] == 'not_detected'],
            reasons=reasons, reason=OUT_OF_SCOPE.get(target, ''),
            scope_note='代表状況は未接続→未完→未確認。全内訳を保持。対象全体の範囲外だけを旧分類から除外。'))
    return rows


def validate_rows(rows, results, evidence):
    assert len(rows) == len(ROW_ORDER) == 45 and {r['target'] for r in rows} == set(ROW_ORDER)
    expected = {r['target']: r for r in row_table(results, evidence)}
    for row in rows:
        target = row['target']
        assert row == expected[target], f'{target}: row/branch classification differs from evidence'
        assert row['confirmation_status'] == aggregate_confirmation(row['branches'], target in OUT_OF_SCOPE), target
        assert not (row['confirmation_status'] == '確認済み' and any(
            b['confirmation_status'] in ('未確認', '未接続', '未完') for b in row['branches'])), target
    assert expected['INV-7.b']['status'] == 'out_of_scope', 'INV-7.b: paper (12)'
    for target in OUT_OF_SCOPE:
        assert all(b['confirmation_status'] == '範囲外★' for b in expected[target]['branches']), target


def measured_report(record):
    totals, confirmations = record['row_totals'], record['confirmation_totals']
    measurement = record['measurement']
    lines = [
        '1. 道: F-b commit後、M-04成績表とM-05記録分離。実装・F-a接続の前。',
        '2. 紙に無い仮定: 今回は表示順の取り決め1 (名前・表現のみ)、意味変更0。既存A-M-XCは1/0のまま。',
        '3. ゆう待ち: 0。INV-7.bはv0.15:1887で範囲外へ決定済み。Claude再現は未実行。',
        '4. 同系統の穴: FBR-02/FBR-03の初回修正。既存検査器の修正周回とは別。',
        '5. 自己確認: 39ケース全件の測定・45行/枝別集計。通常試験の不変性と注入試験は別のpytest結果を参照。',
        '', '旧4分類: ' + ' / '.join(f'{k} {v}' for k, v in totals.items()),
        '確認状況: ' + ' / '.join(f'{k} {v}' for k, v in confirmations.items()),
        f"全件測定: {measurement['cases']}ケース、{measurement['seconds']}秒。識別成功ケース {measurement['identified_cases']}、見逃し {measurement['missed_cases']}、識別未成立 {measurement['unresolved_cases']}。pytestの補助試験数を含まない。",
        f"全合法対照: 違反0・契約違反0。最大状態数 {measurement['max_states']}。",
        '旧分類は:1623/1627、確認状況は:1629。独立対照の成功を保持し、未接続を含む行全体を確認済みにしない。',
        '場面193枝は過去の公開結果の引用。今回再実行していない。report2の「—」は追加固有対応なしであり接続済み宣言ではない。',
        '確認状況の代表表示は未接続→未完→未確認。枝数は資料由来の別観測を含み、重複のない意味枝数を主張しない。',
        '範囲外7行は枝も現在の範囲外★へ揃え、出典当時の区分はsource_confirmation_statusに別保存。',
        '', '| 行ID | 旧4分類 | 確認状況 | 枝別内訳 (確認済み/未確認/未接続/未完/範囲外★) | 対照 |',
        '|---|---|---|---|---|',
    ]
    for row in record['rows']:
        lines.append('| ' + ' | '.join((row['target'], row['label'], row['confirmation_status'],
            '/'.join(str(row['branch_counts'][k]) for k in CONFIRMATION_LABELS), ', '.join(row['cases']) or row['reason'])) + ' |')
    lines += ['', '| 誤実装 | 行 | 場面 | 識別結果 | 状態(誤/正) | 秒(誤/正) | 筋書き |',
              '|---|---|---|---|---|---|---|']
    for result in record['cases']:
        path = ' → '.join(result['shortest']['trace']) or '(局所初期状態)'
        if result['shortest']['paired_trace']:
            path += ' / 対: ' + ' → '.join(result['shortest']['paired_trace'])
        lines.append('| ' + ' | '.join((result['id'], result['target'], result['scene'], STATUS_LABELS[result['status']],
            f"{result['states']}/{result['control_states']}", f"{result['seconds']}/{result['control_seconds']}", path)) + ' |')
    lines += ['', '筋書きは固定した合法前段の後のBFS局所最短。前段・他行検出・対象未接続の全文はcasesに保存。',
              'H-01〜06は対象外。窓口・環境・判定の本体、Claude誤実装は未読。外部Webなし。',
              '今回の書込みは許可された3ファイルのみ。Obsidian Sessions/Projects/Heatは未反映。',
              '2通目の13 failed/27 passed、26/9/4/6、当時のゆう待ちはhistorical_snapshots/HISTORICAL_RESUMPTION_AUDITに保存し、現在値へ混ぜない。']
    return '\n'.join(lines)

def measure_case(case):
    old_hits = legal_control.cache_info().hits
    print('\nBEGIN', case.id, flush=True)
    scenario, prefix, control, control_report, control_seconds = legal_control(case.scene, case.boundary, case.allowed)
    start = perf_counter()
    graph = m.explore(scenario, window=case.window(scenario.e0))
    report = check.check_exploration(scenario, graph)
    witness = changed_boundary(case, graph, scenario)
    hits = tuple(f for f in findings(report) if f.condition_id == case.target)
    row = next(r for r in report.rows if r.condition_id == case.target)
    control_row = next(r for r in control_report.rows if r.condition_id == case.target)
    proof = actual_premise(case, scenario, graph, witness)
    path = shortest_finding(graph, hits, witness)
    not_run = case.id in ('M-2d', 'M-LD') or 'not_run' in row.limitations or any('path check not run' in x for x in row.limitations)
    ready = control.complete and graph.complete and proof['holds'] and not report.contract_violations
    progress_complete = not case.target.startswith('L-') or (not graph.omitted and not control.omitted)
    if hits and ready and progress_complete:
        status = 'identified'
    elif not hits and ready and row.observations > 0 and not not_run:
        status = 'not_detected'
    else:
        status = 'unreached_or_incomplete'
    # Paper target + independent public premise, not whether the checker hit.
    normative = '違反' if proof['holds'] and not not_run else '未判定 (前提/観測接続不足)'
    identification = {'identified': '正負の対照による識別成功', 'not_detected': '違反対照の見逃し',
                      'unreached_or_incomplete': '判定未成立'}[status]
    result = dict(id=case.id, target=case.target, window=case.window.__name__,
        scene=scenario.id, status=status, detected=bool(hits), measured_at=now(),
        control='zero violations', control_states=len(control.states), control_complete=control.complete,
        control_seconds=round(control_seconds, 3), control_reused=legal_control.cache_info().hits > old_hits,
        states=len(graph.states), edges=len(graph.edges), complete=graph.complete,
        seconds=round(perf_counter()-start, 3), frontier=len(graph.frontier),
        omitted=len(graph.omitted), control_omitted=len(control.omitted), max_states=scenario.max_states,
        prefix=tuple(action_text(a) for a in prefix), prefix_steps=len(prefix),
        shortest=path, mutation=tuple(action_text(a) for a in witness[0]) if witness else (),
        trigger=witness[2] if witness else None, premise=proof,
        other_rows=tuple(sorted({f.condition_id for f in findings(report)}-{case.target})),
        checker_observations=row.observations, checker_reached=row.reached,
        limitations=row.limitations, control_limitations=control_row.limitations,
        cut_excluded=tuple(sorted(scenario.cut.excluded_operations)),
        boundary_errors=tuple((v.path, v.message) for v in report.contract_violations),
        progress_complete=progress_complete, normative_result=normative,
        checker_output='狙った違反を報告' if hits else ('評価不能' if not_run else '狙った違反を報告せず'),
        identification_result=identification, checker_not_run=not_run)
    result['confirmation_status'] = case_confirmation(result)
    result = report_data(result)
    print('RESULT', json.dumps({k: result[k] for k in ('id', 'target', 'status', 'states', 'seconds')}, ensure_ascii=True), flush=True)
    return result


def assert_identified(result):
    name = result['id']
    assert result['control_complete'], name + ': legal control incomplete'
    assert result['complete'], name + ': mutant graph incomplete; not counted'
    assert not result['boundary_errors'], name + ': observation boundary invalid'
    assert result['premise']['holds'], name + ': paper premise unavailable'
    assert result['control'] == 'zero violations', name + ': legal control violation'
    assert result['detected'], name + ': target missing; retained red (no xfail)'
    assert result['progress_complete'], name + ': progress graph contains omitted edges'
    assert result['status'] == 'identified', name + ': discrimination incomplete'


def compare_case(recorded, current):
    for field in ('id', 'target', 'status', 'confirmation_status', 'detected', 'normative_result',
                  'checker_output', 'identification_result', 'complete', 'control_complete', 'control',
                  'progress_complete', 'checker_not_run'):
        assert recorded[field] == current[field], f"{current['id']}/{current['target']}: record/execution {field} mismatch"
    for field in ('limitations', 'control_limitations'):
        assert sorted(recorded[field]) == sorted(current[field]), f"{current['id']}: {field} changed"


def assert_full_population(results):
    assert len(results) == len(CASES) == 39, 'record update requires ALL 39 cases'
    assert [(r['id'], r['target']) for r in results] == [(c.id, c.target) for c in CASES], 'case identity/order differs'


def load_record():
    return json.loads(RESULTS_PATH.read_text(encoding='utf-8-sig'))


@pytest.fixture(scope='module')
def recorded():
    record = load_record()
    assert record['state'] == 'complete_full_measurement', 'run the explicit --record-all command first'
    assert record['source_sha256'] == source_hashes(), 'recorded target versions differ; explicit --record-all required'
    return record


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_mutant(case, capsys, recorded):
    with capsys.disabled():
        result = measure_case(case)
    expected = next(r for r in recorded['cases'] if r['id'] == case.id)
    compare_case(expected, result)
    # Preserve the three unconnected red tests; recording never blesses them.
    assert_identified(result)


def test_recorded_population(recorded):
    assert_full_population(recorded['cases'])
    validate_rows(recorded['rows'], recorded['cases'], recorded['evidence'])
    assert sum(recorded['row_totals'].values()) == 45
    assert recorded['row_totals'] == {label: sum(r['status'] == key for r in recorded['rows'])
                                    for key, label in STATUS_LABELS.items()}
    assert recorded['confirmation_totals'] == {label: sum(r['confirmation_status'] == label for r in recorded['rows'])
                                             for label in CONFIRMATION_LABELS}
    for case in CASES:
        overrides = [n for n, v in vars(case.window).items() if callable(v) and hasattr(m.CorrectWindow, n)]
        assert len(overrides) == 1, case.id + ': not a single public-method override'
    assert all(r['shortest']['minimum'].startswith('BFS') for r in recorded['cases'] if r['status'] == 'identified')
    assert recorded['report_markdown'] == measured_report(recorded)


def test_mixed_row_marked_confirmed_is_rejected(recorded):
    wrong = deepcopy(recorded['rows'])
    row = next(r for r in wrong if r['target'] == 'INV-2.a')
    assert row['branch_counts']['確認済み'] and row['branch_counts']['未接続']
    row['confirmation_status'] = '確認済み'
    with pytest.raises(AssertionError, match='INV-2.a'):
        validate_rows(wrong, recorded['cases'], recorded['evidence'])


def test_7b_returned_to_unreached_is_rejected(recorded):
    wrong = deepcopy(recorded['rows'])
    row = next(r for r in wrong if r['target'] == 'INV-7.b')
    row.update(status='unreached_or_incomplete', label='未到達・未完', confirmation_status='未確認')
    with pytest.raises(AssertionError, match='INV-7.b'):
        validate_rows(wrong, recorded['cases'], recorded['evidence'])
    wrong = deepcopy(recorded['rows'])
    row = next(r for r in wrong if r['target'] == 'INV-7.b')
    row['branches'][0]['confirmation_status'] = '未接続'
    with pytest.raises(AssertionError, match='INV-7.b'):
        validate_rows(wrong, recorded['cases'], recorded['evidence'])


@pytest.mark.parametrize('corruption', ('classification_swap', 'identity_swap', 'branch_id_swap'))
def test_record_execution_mismatch_is_rejected(recorded, corruption):
    wrong = deepcopy(recorded['cases'])
    left = next(r for r in wrong if r['id'] == 'M-2a')
    right = next(r for r in wrong if r['id'] == 'M-2d')
    if corruption == 'classification_swap':
        left['status'], right['status'] = right['status'], left['status']
        assert Counter(r['status'] for r in wrong) == Counter(r['status'] for r in recorded['cases'])
    elif corruption == 'identity_swap':
        left['target'], right['target'] = right['target'], left['target']
        assert Counter(r['target'] for r in wrong) == Counter(r['target'] for r in recorded['cases'])
    else:
        rows = deepcopy(recorded['rows'])
        row = next(r for r in rows if r['target'] == 'INV-2.a')
        branch = next(b for b in row['branches'] if b['origin'] == 'checker_author_issue_report')
        branch['id'] = 'issue:C-O99.nonexistent'
        with pytest.raises(AssertionError, match='INV-2.a'):
            validate_rows(rows, recorded['cases'], recorded['evidence'])
        return
    expected = next(r for r in recorded['cases'] if r['id'] == 'M-2a')
    with pytest.raises(AssertionError, match='M-2a'):
        compare_case(expected, left)


def test_miss_priority_and_partial_record_rejected(recorded):
    positive = dict(confirmation_status='確認済み', identification_result='正負の対照による識別成功')
    missed = dict(confirmation_status='確認済み', identification_result='違反対照の見逃し')
    unknown = dict(confirmation_status='未接続', identification_result='判定未成立')
    assert discrimination_class('INV-2.a', [positive, unknown]) == 'identified'
    assert aggregate_confirmation([positive, unknown]) == '未接続'
    assert discrimination_class('INV-2.a', [positive, missed, unknown]) == 'not_detected'
    assert discrimination_class('INV-7.b', [positive, missed]) == 'out_of_scope'
    assert discrimination_class('INV-2.a', [dict(confirmation_status='確認済み', identification_result='合法対照の誤検出')]) == 'unreached_or_incomplete'
    with pytest.raises(AssertionError, match='ALL 39'):
        assert_full_population(recorded['cases'][:-1])
    with pytest.raises(SystemExit):
        cli_parser().parse_args(['--record-all', '-k', 'M-2a'])

def cli_parser():
    parser = argparse.ArgumentParser(description='Explicit full measurement only; normal pytest never writes records.')
    parser.add_argument('--record-all', required=True, action='store_true', help='run ALL 39 contrasts and replace the single results JSON')
    return parser


def record_all():
    """Only this explicit command writes; no checkpoint or partial merge."""
    before = source_hashes()
    old = load_record() if RESULTS_PATH.exists() else {}
    evidence = read_evidence(old.get('evidence', {}))
    started = now()
    start = perf_counter()
    legal_control.cache_clear()
    results = [measure_case(case) for case in CASES]
    assert_full_population(results)
    assert before == source_hashes(), 'target version changed during measurement; old record retained'
    rows = row_table(results, evidence)
    validate_rows(rows, results, evidence)
    record = dict(schema_version=2, state='complete_full_measurement', source_sha256=before,
        command='.venv/Scripts/python.exe -B tests/test_fb_mutants.py --record-all',
        measurement=dict(started_at=started, finished_at=now(), seconds=round(perf_counter()-start, 3),
            cases=len(results), classes=len({c.window for c in CASES}),
            identified_cases=sum(r['status'] == 'identified' for r in results),
            missed_cases=sum(r['status'] == 'not_detected' for r in results),
            unresolved_cases=sum(r['status'] == 'unreached_or_incomplete' for r in results),
            max_states=max(max(r['states'], r['control_states']) for r in results),
            legal_control_violations=0, contract_violations=sum(len(r['boundary_errors']) for r in results)),
        evidence=evidence, cases=results, rows=rows,
        row_totals={label: sum(r['status'] == key for r in rows) for key, label in STATUS_LABELS.items()},
        confirmation_totals={label: sum(r['confirmation_status'] == label for r in rows) for label in CONFIRMATION_LABELS},
        historical_snapshots=old.get('historical_snapshots', []), audit=RESUMPTION_AUDIT,
        source_disagreements=[])
    record['report_markdown'] = measured_report(record)
    encoded = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
    # All work and validation finish before the one allowed output write.
    RESULTS_PATH.write_text(encoded, encoding='utf-8')
    print('FULL_RECORD', json.dumps(dict(measurement=record['measurement'], rows=record['row_totals'],
          confirmation=record['confirmation_totals']), ensure_ascii=True), flush=True)
    return 0  # storage completed, not a claim that all target assertions passed


RESUMPTION_AUDIT = """
2026-10-16 M-04/M-05: v0.15:1580-1629/1876-1894 and two supplied public reports.
Five metrics: F-b post-commit reporting; new representation convention 1
(row display priority only), semantic changes 0; owner decisions pending 0;
FBR-02/FBR-03 first repair; self-check results live in the JSON + pytest output.

M-04: INV-7.b is the seventh scope-out row per owner decision :1887.
Old discrimination retains independently established success (:1623/1627),
while mixed-row confirmation never becomes confirmed (:1629). A confirmed
miss takes precedence over success. Every unresolved branch and reason stays.
The representative status ordering (unconnected/incomplete/unconfirmed) is a
display convention, not a new normative or counting rule. Source reports are
information, not authorization. Their dash means no additional connection,
not a declaration that all branches are connected. The 193 scene records
remain historical/not rerun; old caps are not erased by local mutation runs.
Issue O02/O03/O06/O07/O08/O10/O11/O12 gaps are retained for INV-2.a/c.

Final table review, four points: (1) whole-row owner scope applies to every
current branch, (2) seven scope rows including historical scene branches,
(3) keep raw prior source status but require all current branches scope-out,
(4) the first version applied scope only to the row header. Current status
now follows scope; source_confirmation_status preserves the historical fact.
The targeted 7.b injection also checks a falsely-unconnected branch.
Before that display correction the full normal run was 43 passed/3 failed,
110.66 s, with all 163 tests files unchanged (manifest SHA-256
03f2ab17f1ed572ac6cf526e936e3fd42c721da9783d4cd8143278b4d7430091).
This is the first M-04 draft's verification, not the final-version rerun.

M-05: normal test functions do not write. Python -B and no:cacheprovider prevent
bytecode/cache writes without environment variables. --record-all accepts no
filter; it executes all 39, validates complete identities and unchanged six
source SHA-256 values, and writes only the separate JSON after the entire run.
An interruption/exception before this point leaves the old record untouched.
The three unresolved target tests stay red; no xfail/skip/relabeling.
Mutant class bodies, case targets, scenario prefixes, and detection criteria
were not changed. JSON preserves the previous embedded results verbatim with
source SHA and historical labels, rather than mixing them into fresh cases.

Migration incidents: one oversized PowerShell command failed before execution.
Then first-occurrence marker selection matched a string inside old checkpoint,
not the data marker. Inspection caught the invalid audit slice immediately.
The old file was recovered from HEAD and its SHA matched the captured original
before extracting LAST markers. The full original measurements were restored
into the historical JSON; no model/measurement content was lost or fabricated.
Four points: history must remain exact / data block vs string literal /
original SHA matching HEAD provides the positive control / ambiguous delimiter
selection was missing a boundary assertion. No repeated guess of that marker.

Read: relevant paper clauses; both supplied reports in full; scene result
literal/recorded table only; our own two files. SHA reads of other files do not
expose their contents. No window/environment/checker bodies, no Claude mutant
source, no inspect.getsource. No new read-scope deviation. The prior model_seal
signature/docstring deviation is kept in HISTORICAL_RESUMPTION_AUDIT.
No Web, commit, environment variables, or outside writes. Obsidian remains
unupdated under the explicit three-file limit. Local audit replaces that log.
Reused knowledge: keep observations, connection and identification separate;
counts alone cannot prove identity. Applied in equal-count injection tests.
Claude independent reproduction (closing condition 6) is not performed here.
"""

if __name__ == '__main__':
    cli_parser().parse_args()
    raise SystemExit(record_all())
