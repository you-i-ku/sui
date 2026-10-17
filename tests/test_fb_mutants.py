"""Independent F-b mutations: v0.18 MG-06 plus historical v0.12/v0.15.

Targets were declared first in fb_mutants.py. Every case checks its identical
legal control first and stops the run on a legal-control violation. K-U cuts
retain ownership and histories; omitted continuation is not claimed complete.
Progress cases keep the target's full save/derive path. H-01..06 are excluded.
Only public signatures/docstrings/declarations and actual API outputs were
read; no CorrectWindow/Environment/checker implementation bodies were opened.
No environment variables, commit or Obsidian writes: current two-file limit
overrides the general log rule. Current measurements are in memory/stdout;
fb_mutants_results.json is immutable historical evidence.
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
    if '-M3-' in scene_id or '-M4-' in scene_id:
        return mg_prepared_scene(scene_id, boundary, allowed)
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
    if case.id.startswith('MG-'):
        return mg_actual_premise(case, scenario, graph, witness)
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
# FBM3-R04: only git-tracked files decide whether the record is current. The
# paper is not in git; --record-all keeps its digest as provenance only.
SOURCE_PATHS = (
    'tests/fb_check.py', 'tests/fb_machine.py',
    'tests/fb_scenes.py', 'tests/fb_mutants.py', 'tests/test_fb_mutants.py',
)
PAPER_PATH = 'specs/関所F_Fb_今の約束.md'
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
                  if line.startswith(('INV-', 'L-')) and ' | ' in line) + ('INV-2.g', 'INV-16.c')
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
    """Reuse the retained report rows and read ONLY the scene results JSON's observation record.

    Never import/execute test_fb_scenes or inspect its test bodies. The check2
    reports were session-temporary files (FBM3-R04): their verbatim rows/hashes
    are retained in the record and are never re-read from a fixed temp path.
    """
    evidence = {'check2_rows': [], 'issue_rows': [], 'scenes': [], 'sources': []}
    for destination in ('check2_rows', 'issue_rows'):
        assert previous.get(destination), f'missing retained evidence: {destination}'
        evidence[destination] = deepcopy(previous[destination])
        evidence['sources'].extend(dict(s, reread=False) for s in previous['sources']
                                   if s['kind'] == destination)
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
    assert {r['target'] for r in evidence['check2_rows']} == set(ROW_ORDER) - {'INV-2.g', 'INV-16.c'}
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
    if result.get('connection_status')=='unconnected':
        assert result['status']=='unreached_or_incomplete'
        return CONFIRMATION_LABELS[2]
    if result.get('execution')=='not_run':
        return result['confirmation_status']
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


def discrimination_class(target, branches, whole_scope=None):
    """v0.15:1620-1629: scope > confirmed miss > +/- success > other."""
    if (target in OUT_OF_SCOPE) if whole_scope is None else whole_scope:
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
                execution=result.get('execution','実行済み'), reached=result['premise']['holds'], complete=result['complete'],
                normative_result=result['normative_result'], checker_output=result['checker_output'],
                identification_result=result['identification_result'], legal_control=result['control'],
                source=f"cases/{result['id']}", detail=result.get('disposition_reason') or '同じE0・前段・Cutの正負対照。未到達/接続不足は成功にしない。'))
        if target=='INV-2.g':
            for identity, detail in (
                ('MG-01.atomic-birth','Publish effect is followed by Environment registration; only subsequent loss before Saved(CG) is injectable through the exposed drain. Known unconfirmed same-step contrast: paper 1937/1944/1946.'),
                ('MG-20.atomic-birth','The exposed boundary tests subsequent Ep-run loss; atomic omission at EQ PUB lacks a separated window-owned registration hook. Known unconfirmed same-step contrast: paper 1937/1946.')):
                branches.append(dict(id=identity,origin='public_hook_limit',confirmation_status=CONFIRMATION_LABELS[1],
                    execution='not_run: atomic omission contrast',reached=False,normative_result='unjudged: atomic omission not_run',
                    checker_output='not_run',identification_result='unestablished (not_run)',detail=detail,known_review_gap=True,source='MG06_TURN2_AUDIT'))
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
        # Preserve all 46 current public scene declarations not present in
        # the historical 193-scene JSON. A local mutant/control prefix is not
        # execution of the complete declared scene, nor its negative controls.
        historical_ids={s['id'] for s in evidence['scenes']}
        for declared in scenes.SCENES:
            if declared.id in historical_ids or target not in declared.row_ids:
                continue
            confirmation=(CONFIRMATION_LABELS[4] if declared.scope_class=='b' else
                CONFIRMATION_LABELS[2] if declared.blocker or declared.expected_missing_contract else CONFIRMATION_LABELS[1])
            branches.append(dict(id='current-scene:'+declared.id,origin='current_scene_declaration',
                confirmation_status=confirmation,execution='not_run: full scene; local mutant prefixes are separate',
                reached=False,normative_result='unjudged',checker_output='not_run',identification_result='unestablished',
                detail=declared.blocker or declared.expected_missing_contract or 'Current public declaration retained; no full-scene discrimination is claimed.',
                source='fb_scenes.SCENES/'+declared.id))
        whole_scope = target in OUT_OF_SCOPE
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
                detail=OUT_OF_SCOPE[target], source='specs/関所F_Fb_今の約束.md:1880,1891-1892'))
        status = discrimination_class(target, branches, whole_scope)
        confirmation = aggregate_confirmation(branches, whole_scope)
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
    assert len(rows) == len(ROW_ORDER) == 47 and {r['target'] for r in rows} == set(ROW_ORDER)
    expected = {r['target']: r for r in row_table(results, evidence)}
    for row in rows:
        target = row['target']
        assert row['confirmation_status'] in CONFIRMATION_LABELS, target
        assert all(b['confirmation_status'] in CONFIRMATION_LABELS for b in row['branches']), target
        assert sum(row['branch_counts'].values()) == len(row['branches']), target
        assert row == expected[target], f'{target}: row/branch classification differs from evidence'
        assert row['confirmation_status'] == aggregate_confirmation(row['branches'], target in OUT_OF_SCOPE), target
        assert not (row['confirmation_status'] == '確認済み' and any(
            b['confirmation_status'] in ('未確認', '未接続', '未完') for b in row['branches'])), target
    assert expected['INV-7.b']['status'] == 'out_of_scope', 'INV-7.b: paper (12)'
    for target in OUT_OF_SCOPE:
        assert all(b['confirmation_status'] == '範囲外★' for b in expected[target]['branches']), target


def measured_report(record):
    lines=[
        '1. Road: MG-06, M3/M4 finite model discrimination; before real F-a integration.',
        '2. New paper-absent assumptions: representation A-MG-WIRE (1); semantic additions 0. Inherited assumptions remain limited.',
        '3. Owner decisions pending: 0. MG-15 retained unconnected; atomic MG-01/MG-20 contrasts retained unconfirmed.',
        '4. Same family: first MG-06 round; no checker repair.',
        '5. Closure: 29 predeclared designs, 17 paper-only; individual dispositions below; 47 rows / 51 condition schemas.',
        '', 'Current evidence only; historical JSON is never promoted to a current pass.',
        'Rows: '+json.dumps(record['row_totals'],ensure_ascii=False),
        'Confirmation: '+json.dumps(record['confirmation_totals'],ensure_ascii=False),
        '', '| Row | Four-way result | Confirmation | Branches confirmed/unconfirmed/unconnected/incomplete/outside |',
        '|---|---|---|---|',
    ]
    for row in record['rows']:
        lines.append('| '+ ' | '.join((row['target'],row['label'],row['confirmation_status'],
            '/'.join(str(row['branch_counts'][k]) for k in CONFIRMATION_LABELS)))+' |')
    lines+=['','| Mutant | Target | Result | Control | States wrong/correct |','|---|---|---|---|---|']
    for r in record['cases']:
        lines.append('| '+' | '.join((r['id'],r['target'],STATUS_LABELS[r['status']],r['control'],
            str(r['states'])+'/'+str(r['control_states'])))+' |')
    lines+=['','| Condition schema | Confirmation | Finite contrasts |','|---|---|---|']
    for row in record.get('conditions',condition_table(record['cases'])):
        lines.append('| '+' | '.join((row['condition'],row['confirmation_status'],','.join(row['cases']) or 'not_run'))+' |')
    lines+=['',MG06_AUDIT,MG06_TURN2_AUDIT]
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
    if proof.get('connection_status')=='unconnected':
        result['connection_status']='unconnected'
        result['disposition_reason']=proof['reason']
        result['limitations']=tuple(result['limitations'])+(proof['reason'],)
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
    assert len(results) == len(CASES), f'record update requires ALL {len(CASES)} cases'
    assert [(r['id'], r['target']) for r in results] == [(c.id, c.target) for c in CASES], 'case identity/order differs'


def load_record():
    return json.loads(RESULTS_PATH.read_text(encoding='utf-8-sig'))



# MG-06 current measurements never write the immutable historical JSON.
LEGACY_CASES = CASES
MG_CASES = (
    Case('MG-01','INV-2.g',mutants.DelayEvaluationIssue,'SC-09-M3-generation-evaluation','after:PublishUnit:candidate',('Drain',)),
    Case('MG-02','INV-2.g',mutants.DropEvaluationIssue,'SC-09-M3-context-missing','',('Drain',)),
    Case('MG-03','INV-2.g',mutants.DropGenerationPurpose,'SC-09-M3-context-missing','',('Drain',)),
    Case('MG-04','INV-2.g',mutants.SaveWaitCreatesPurpose,'SC-09-M3-context-save-wait','',('Drain',)),
    Case('MG-05','INV-2.g',mutants.EvaluationClearsPurpose,'SC-09-M3-pG-after-EQ','before:PublishUnit:evaluation',('PublishUnit',)),
    Case('MG-06','INV-16.c',mutants.NoCandidatesMakesCandidate,'SC-15-M3-no-candidates','',('Drain',)),
    Case('MG-07','INV-16.c',mutants.FailureMakesCandidate,'SC-15-M3-failure','',('Drain',)),
    Case('MG-08','INV-16.c',mutants.UnknownMakesCandidate,'SC-15-M3-unknown','',('Drain',)),
    Case('MG-09','INV-16.c',mutants.GenerationArgsChanged,'SC-09-M3-generation-evaluation','before:EnterWorker:wg:wrapper:0',('EnterWorker',)),
    Case('MG-10','INV-16.c',mutants.GenerationDrawsErased,'SC-09-M3-D6-generation-draw'),
    Case('MG-11','INV-15.a',mutants.WorkFinishedEndsDraw,'SC-15-M4-D-workfinished','',('Drain',)),
    Case('MG-12','INV-15.b',mutants.LateDrawValueMakesFact,'SC-16-M4-D-failure-value','',('Drain',)),
    Case('MG-13','INV-2.g',mutants.GenerationRunClosed,'SC-09-M3-generation-evaluation','after:PublishUnit:initial',('Drain',)),
    Case('MG-14','INV-2.g',mutants.GenerationTerminalSaveClosed,'SC-09-M3-generation-evaluation','after:RecognizeTerminal:wg',('Drain',)),
    Case('MG-15','INV-2.g',mutants.GenerationHandleClosed,'SC-09-M3-generation-evaluation','after:RecognizeTerminal:wg',('Drain',)),
    Case('MG-16','INV-2.g',mutants.CandidateIssueClosed,'SC-09-M3-generation-evaluation','before:PublishUnit:candidate',('Drain',)),
    Case('MG-17','INV-2.g',mutants.CandidateSaveClosed,'SC-09-M3-generation-evaluation','after:PublishUnit:candidate',('Drain',)),
    Case('MG-18','INV-2.g',mutants.EvaluationSaveClosed,'SC-09-M3-generation-evaluation','after:PublishUnit:evaluation',('Drain',)),
    Case('MG-19','INV-2.g',mutants.EvaluationOmitsEp,'SC-09-M3-generation-evaluation','before:PublishUnit:evaluation',('PublishUnit',)),
    Case('MG-20','INV-2.g',mutants.EvaluationOmitsRun,'SC-09-M3-generation-evaluation','after:PublishUnit:evaluation',('Drain',)),
    Case('MG-21','INV-2.g',mutants.GenerationPurposeRebased,'SC-09-M3-context-missing','',('Drain',)),
    Case('MG-22','INV-2.g',mutants.GenerationPurposeTruncated,'SC-09-M3-context-missing','',('Drain',)),
    Case('MG-23','INV-16.c',mutants.GenerationReaderChanged,'SC-09-M3-generation-evaluation','before:EnterWorker:wg:wrapper:0',('EnterWorker',)),
    Case('MG-24','INV-16.c',mutants.GenerationInputChanged,'SC-09-M3-generation-evaluation','before:EnterWorker:wg:wrapper:0',('EnterWorker',)),
    Case('MG-25','INV-16.c',mutants.CandidateOrderChanged,'SC-09-M3-generation-evaluation','before:PublishUnit:candidate',('PublishUnit',)),
    Case('MG-26','INV-16.c',mutants.CandidateMeasureChanged,'SC-09-M3-generation-evaluation','before:PublishUnit:candidate',('PublishUnit',)),
    Case('MG-27','INV-16.c',mutants.EvaluationUsesGenerationView,'SC-09-M3-generation-evaluation','before:PublishUnit:evaluation',('PublishUnit',)),
    Case('MG-28','INV-16.c',mutants.EvaluationCandidatesChanged,'SC-09-M3-generation-evaluation','before:PublishUnit:evaluation',('PublishUnit',)),
    Case('MG-29','INV-16.c',mutants.GenerationLateValueOverwritesUnknown,'SC-16-M3-unknown-late-value','',('Drain',)),
)
CASES = LEGACY_CASES + MG_CASES
CURRENT_RESULTS = {}
CONDITION_ORDER = tuple(c.id for c in m.E0().completions)
OG_CONDITION_CASES = {
    'C-OG.run[Wg]': ('MG-13',), 'C-OG.save[T]': ('MG-14',),
    'C-OG.handle[Wg]': ('MG-15',), 'C-OG.issue[CG]': ('MG-16',),
    'C-OG.save[CG]': ('MG-17',), 'C-OG.issue[EQ]': ('MG-01','MG-02'),
    'C-OG.save[EQ]': ('MG-18',),
}


@lru_cache(None)
def mg_prepared_scene(scene_id, boundary, allowed):
    base_id = 'SC-16-M4-D-failure-unknown' if scene_id == 'SC-16-M4-D-failure-value' else scene_id
    scene = next(s for s in scenes.SCENES if s.id == base_id)
    if scene_id == 'SC-16-M4-D-failure-value':
        # Public E0 is changed BEFORE execution: same D, first Failure, late
        # Success instead of Unknown. This is a structural M4 scene, not IE/ID.
        programs=tuple(replace(p,replies=(p.replies[0],m.Outcome(m.OutcomeKind.RETURNED,
            m.obj(generator='finite',stream_id='s',purpose='selection',context_key='k',ordinal=0,law='finite',args=m.obj(),value=1))))
            if p.work=='d' else p for p in scene.e0.programs)
        df=m.RecordPlan('df',m.Contract('draw_fact','1'),'Event',next(p for p in programs if p.work=='d').replies[1].content)
        followup=m.AllowedPlan('late-draw','O-11',('d','draw_fact'),(df,),(),
            (m.Guard('first','d'),m.Guard('outcome','d',('Success','DrawValue'))))
        e0=replace(scene.e0,programs=programs,plans=scene.e0.plans+(followup,))
        obs=replace(e0.observation_declarations,plans=m.declare_observation_e0(e0).plans)
        scene=replace(scene,id=scene_id,e0=replace(e0,observation_declarations=obs))
    scenario, states, edges, _ = scenes.instantiate(scene)
    prefix=tuple(e.action for e in edges)
    if boundary:
        when, operation, target = boundary.split(':',2)
        edge=next(e for e in edges if e.action.operation==operation and e.action.target==(target,))
        index=edge.source if when=='before' else edge.target
        scenario=replace(scenario,initial=states[index])
        prefix=tuple(e.action for e in edges[:index])
    cut=m.Cut('MG-06 single boundary',OPERATIONS-frozenset(allowed)-{'Wait'},
        ('Only listed local operations; the same full legal prefix and ownership survive. Other continuations not tested.',))
    return replace(scenario,id=scene_id+':'+(boundary or 'tail'),cut=cut,max_states=200),prefix


def mg_purposes(custody):
    return tuple(x for w in custody.work for x in w.purposes if x.obligation_id=='O-G') + tuple(
        x for u in custody.units if u.generation for x in u.generation.shortages if x.obligation_id=='O-G')


def mg_actual_premise(case, scenario, graph, witness):
    if witness is None:
        return dict(holds=False,reason='declared mutation not exercised; no target pass')
    env=m.Environment(scenario.e0)
    ordinary=m.CorrectWindow(scenario.e0)
    for edge in graph.edges:
        if edge.source==edge.target:
            continue
        before=graph.states[edge.source]
        after=graph.states[edge.target]
        view=m.View(before.core,before.controls,before.evidence)
        good=ordinary.dispatch(view,edge.action)
        bad=case.window(scenario.e0).dispatch(view,edge.action)
        if good==bad:
            continue
        actual_changed=env.step(before,edge.action,ordinary).state!=after
        common=dict(action=action_text(edge.action),actual_public_state_changed=actual_changed,
                    paper_origin='C' if int(case.id[3:])<=12 else 'P')
        number=int(case.id[3:])
        if number in (1,2):
            key=next(c.key for c in good.custody.conditions if c.key.obligation=='O-G'
                     and c.key.kind=='issue' and getattr(c.key.target,'unit',None)=='evaluation')
            missing=not any(c.key==key for c in bad.custody.conditions)
            return dict(common,holds=actual_changed and missing,condition=repr(key),good_unmet=True,bad_missing=missing)
        if number in (3,5,21,22):
            a,b=mg_purposes(good.custody),mg_purposes(bad.custody)
            original={x.obligation_key for x in a}
            remaining={x.obligation_key for x in b}
            return dict(common,holds=actual_changed and bool(original-remaining),original_parts=tuple(map(repr,original)),
                        remaining_parts=tuple(map(repr,remaining)),good_carriers=len(a),bad_carriers=len(b))
        if number==4:
            plan=next(p for p in scenario.e0.plans if p.unit=='evaluation')
            ordinary_wait=any(g.kind=='saved' for g in plan.guards) and not any(g.kind=='generation_context' for g in plan.guards)
            return dict(common,holds=actual_changed and ordinary_wait and not mg_purposes(good.custody) and bool(mg_purposes(bad.custody)),
                        ordinary_predecessor_wait=ordinary_wait)
        if number in (6,7,8):
            row=next(w for w in before.core.p.work if w.descriptor.stage=='Wg')
            published=any(s.plan.contract.name=='candidate_declaration' for u in bad.custody.units for s in u.slots)
            eligible=row.knowledge.kind==m.OutcomeKind.RETURNED and row.knowledge.content.get('variant')=='Candidates'
            return dict(common,holds=actual_changed and published and not eligible,first_outcome=repr(row.knowledge),candidate_published=published)
        if number==15:
            receiver=next(c for c in good.custody.conditions if c.key.obligation=='O-G' and c.key.kind=='issue' and getattr(c.key.target,'unit',None)=='candidate')
            return dict(common,holds=False,connection_status='unconnected',
                reason='unconnected: Transfer acceptance not independently observable; live issue[CG] already has the same Wg carrier. C-05 same-P.work acceptance precedent is supplied technical information, not rerun evidence. Paper 1340,1586-1590,1943,1951: retain denominator, neither success nor violation.',
                candidate_receiver=repr(receiver.owner),requires_public_transfer_contract=True)
        if number in (13,14,16,17,18):
            kind,unit,work={13:('run',None,'wg'),14:('save','terminal:wg',None),15:('handle',None,'wg'),
                16:('issue','candidate',None),17:('save','candidate',None),18:('save','evaluation',None)}[number]
            c=next(c for c in good.custody.conditions if c.key.obligation=='O-G' and c.key.kind==kind
                and (unit is None or getattr(c.key.target,'unit',None)==unit)
                and (work is None or getattr(c.key.target,'work',None)==work))
            closed=not next(x for x in bad.custody.conditions if x.key==c.key).unmet
            saved=any(e.header.record.contract.name=={'terminal:wg':'sui.fb.work_terminal','candidate':'candidate_declaration',
                'evaluation':'sui.fb.evaluation_request'}.get(unit,'') for e in before.core.e)
            return dict(common,holds=actual_changed and bool(c.unmet) and closed and not saved,condition=repr(c.key),
                        originally_unmet=bool(c.unmet),closed=closed,target_already_saved=saved)
        if number==11:
            d=next(w for w in before.core.p.work if w.descriptor.stage=='D')
            wrong=next(w for w in bad.custody.work if w.descriptor.work_id==d.descriptor.work_id)
            return dict(common,holds=actual_changed and d.first is None and wrong.first is not None,
                        saved_workfinished=True,ordinary_first=d.first,wrong_first=wrong.first)
        if number==12:
            d=next(w for w in before.core.p.work if w.descriptor.stage=='D')
            notices=[e for e in before.evidence.eh.originals if e.event.kind=='DrawReturned']
            first_failure=d.knowledge.kind==m.OutcomeKind.FAILURE
            first_notice_failure=notices[0].event.fields.get('outcome').kind==m.OutcomeKind.FAILURE
            late_value=notices[-1].event.fields.get('outcome').kind==m.OutcomeKind.RETURNED
            published=any(s.plan.contract.name=='draw_fact' for u in after.core.p.units for s in u.slots)
            broken=actual_changed and first_failure and first_notice_failure and late_value and published
            return dict(common,holds=broken,window_violation=broken,
                        violated_paper_row='INV-15.b (paper 885/1969)',target_rule_violation=broken,
                        reason='paper 885/1969 fixes the first logical end kind: first Failure permits T only; a late DrawValue cannot authorize DF. Target was redeclared before this rerun.',
                        first_failure=first_failure,first_notice_failure=first_notice_failure,
                        late_value=late_value,draw_fact_published=published)
        if number in (9,23,24):
            correct=env.step(before,edge.action,ordinary).state
            expected=next(x.value for x in reversed(correct.evidence.observation_trace.events) if x.tag=='ReadInputs')
            observed=next(x.value for x in reversed(after.evidence.observation_trace.events) if x.tag=='ReadInputs')
            field={9:'args',23:'reader',24:'numerical_view'}[number]
            wanted=getattr(expected.descriptor,field) if number!=24 else expected.numerical_view
            actual=getattr(observed.descriptor,field) if number!=24 else observed.numerical_view
            return dict(common,holds=actual_changed and wanted!=actual,actual_observation='ReadInputs',field=field,
                expected=repr(wanted),observed=repr(actual),generation_reply_not_yet_reached=True)
        if number==29:
            original=next(w for w in before.core.p.work if w.descriptor.stage=='Wg')
            wrong=next(w for w in after.core.p.work if w.descriptor.stage=='Wg')
            cg=any(s.plan.contract.name=='candidate_declaration' for u in after.core.p.units for s in u.slots)
            return dict(common,holds=actual_changed and original.knowledge.kind==m.OutcomeKind.UNKNOWN
                and wrong.knowledge.kind==m.OutcomeKind.RETURNED and cg,first_unknown=True,late_value_makes_cg=cg)
        # For field correspondence, independently compare ordinary E0-driven
        # Decision with the requested effect actually performed. A single
        # descriptor/body field (or one declared atomic counterpart) differs.
        return dict(common,holds=actual_changed,wrong_public_decision=type(bad.result).__name__,
                    comparison='unchanged E0 / actual unchanged Program / altered public request or custody')
    return dict(holds=False,reason='no changed actual edge localized')


def mg_d6_result(case):
    scene=next(s for s in scenes.SCENES if s.id==case.scene)
    # R10 is explicitly missing. No positive executable pair can be claimed.
    with pytest.raises(m.MissingContract,match='R10'):
        scenes.instantiate(scene)
    result=dict(id=case.id,target=case.target,status='unreached_or_incomplete',detected=False,
        confirmation_status=CONFIRMATION_LABELS[2],execution='not_run',control='not_run: R10 missing',
        control_complete=False,complete=False,states=0,control_states=0,scene=case.scene,
        premise=dict(holds=False,reason='D6 / R10 generation draws have no connected legal control'),
        limitations=('unconnected: R10 generation draws; normalization hook is not reached',),control_limitations=(),
        normative_result='unjudged: no legal R10 prefix',checker_output='not_run',identification_result='unestablished',
        shortest=dict(trace=(),paired_trace=(),minimum='not_run'),seconds=0,control_seconds=0,
        other_rows=(),boundary_errors=(),checker_not_run=True,progress_complete=False)
    # Python source is ASCII for reliable PowerShell stdin transport.
    result['confirmation_status']=CONFIRMATION_LABELS[2]
    return result


def condition_table(results):
    indexed={r['id']:r for r in results}
    rows=[]
    for condition in CONDITION_ORDER:
        ids=OG_CONDITION_CASES.get(condition,())
        branches=[dict(id=i,confirmation_status=case_confirmation(indexed[i]),
            identification_result=indexed[i]['identification_result']) for i in ids if i in indexed]
        if condition=='C-OG.issue[EQ]':
            branches.append(dict(id='MG-01.atomic-birth',confirmation_status=CONFIRMATION_LABELS[1],identification_result='unestablished (not_run)'))
        rows.append(dict(condition=condition,cases=list(ids),branches=branches,
            confirmation_status=aggregate_confirmation(branches) if ids else CONFIRMATION_LABELS[1],
            execution='current finite contrasts' if branches else 'condition-specific contrast not_run; ordinary row checks may have run',
            scope='structural only; real F-a closures are not certified'))
    assert all(r['confirmation_status'] in CONFIRMATION_LABELS for r in rows)
    assert all(b['confirmation_status'] in CONFIRMATION_LABELS for r in rows for b in r['branches'])
    return rows


@pytest.fixture(scope='module',autouse=True)
def immutable_record_and_current_summary():
    before=RESULTS_PATH.read_bytes()
    yield
    assert RESULTS_PATH.read_bytes()==before, 'normal tests must never write the record'
    if not CURRENT_RESULTS:
        return
    results=[CURRENT_RESULTS[c.id] for c in CASES if c.id in CURRENT_RESULTS]
    evidence=load_record()['evidence']
    rows=row_table(results,evidence)
    validate_rows(rows,results,evidence)
    conditions=condition_table(results)
    payload=dict(state='current_in_memory_partial' if len(results)!=len(CASES) else 'current_in_memory_full',
        historical_record_is_current=load_record()['source_sha256']==source_hashes(),
        denominators=dict(rows=len(ROW_ORDER),conditions=len(CONDITION_ORDER),cases=len(CASES)),
        cases=results,rows=rows,conditions=conditions,
        row_totals=dict(Counter(r['label'] for r in rows)),
        confirmation_totals=dict(Counter(r['confirmation_status'] for r in rows)),
        record_unchanged=True)
    payload['cases']=[{k:r.get(k) for k in ('id','target','status','confirmation_status','control','states','control_states','prefix_steps','detected','premise','other_rows','shortest','boundary_errors')} for r in results]
    payload['rows']=[{k:r[k] for k in ('target','status','label','confirmation_status','branch_counts')} for r in rows]
    print('\nMG06_CURRENT_REPORT',json.dumps(payload,ensure_ascii=True),flush=True)


@pytest.mark.parametrize('case',MG_CASES,ids=lambda case:case.id)
def test_mg06_mutant(case,capsys,recorded):
    with capsys.disabled():
        result=mg_d6_result(case) if case.id=='MG-10' else measure_case(case)
        CURRENT_RESULTS[case.id]=result
        if recorded['source_sha256']==source_hashes():
            compare_case(next(r for r in recorded['cases'] if r['id']==case.id),result)
        print('MG06_CASE',json.dumps({k:result.get(k) for k in ('id','target','status','detected','control','states','control_states','prefix_steps','premise','other_rows','shortest','boundary_errors')},ensure_ascii=True),flush=True)
    if case.id=='MG-10':
        pytest.skip('D6: R10 unconnected; no runnable normalization contrast')
    if case.id=='MG-15':
        # An executed observation-limit experiment, never a semantic pass.
        assert result['control']=='zero violations' and result['control_complete']
        assert result['complete'] and not result['boundary_errors']
        assert not result['premise']['holds']
        assert result['status']=='unreached_or_incomplete'
        assert result['confirmation_status']==CONFIRMATION_LABELS[2]
        assert result['connection_status']=='unconnected'
        assert 'C-05' in result['disposition_reason'] and '1340' in result['disposition_reason']
        return
    assert_identified(result)


def test_current_denominators_do_not_promote_history(recorded):
    # No current contrast -> zero new confirmed/identified rows, even though
    # the historical JSON contains successes. All 47/51 identities survive.
    rows=row_table([],recorded['evidence'])
    assert len(rows)==47 and len({r['target'] for r in rows})==47
    assert all(r['status']!='identified' and r['confirmation_status']!=CONFIRMATION_LABELS[0] for r in rows)
    conditions=condition_table([])
    assert len(conditions)==51 and len({r['condition'] for r in conditions})==51
    assert set(OG_CONDITION_CASES)=={r['condition'] for r in conditions if r['condition'].startswith('C-OG.')}
    assert all(r['confirmation_status']!=CONFIRMATION_LABELS[0] for r in conditions)
    old_ids={s['id'] for s in recorded['evidence']['scenes']}
    new=[s for s in scenes.SCENES if s.id not in old_ids]
    assert len(scenes.SCENES)==239 and len(new)==46
    indexed={r['target']:r for r in rows}
    for declared in new:
        for target in declared.row_ids:
            branch=next(b for b in indexed[target]['branches'] if b['id']=='current-scene:'+declared.id)
            expected=(CONFIRMATION_LABELS[4] if target in OUT_OF_SCOPE or declared.scope_class=='b' else
                CONFIRMATION_LABELS[2] if declared.blocker or declared.expected_missing_contract else CONFIRMATION_LABELS[1])
            assert branch['confirmation_status']==expected
            assert branch['execution'].startswith('not_run') and not branch['reached']
    assert {s.id for s in new if s.blocker or s.expected_missing_contract}=={
        'SC-14-M3-Hung-D-cap1','SC-14-M3-Hung-D-cap2','SC-09-M3-D6-generation-draw'}
    validate_rows(rows,[],recorded['evidence'])
    wrong=deepcopy(rows)
    wrong[0]['branches'][0]['confirmation_status']='unknown-label'
    with pytest.raises(AssertionError):
        validate_rows(wrong,[],recorded['evidence'])
    atomic={b['id']:b for b in indexed['INV-2.g']['branches'] if b['origin']=='public_hook_limit'}
    assert set(atomic)=={'MG-01.atomic-birth','MG-20.atomic-birth'}
    assert all(b['confirmation_status']==CONFIRMATION_LABELS[1] and b['known_review_gap'] for b in atomic.values())
    assert all(b['execution'].startswith('not_run') and '1937' in b['detail'] for b in atomic.values())
    assert next(c for c in MG_CASES if c.id=='MG-12').target=='INV-15.b'
    assert len(LEGACY_CASES)==39 and len(MG_CASES)==29 and len(CASES)==68
    assert len({c.id for c in CASES})==68
    with pytest.raises(AssertionError,match='ALL 68'):
        assert_full_population(recorded['cases'][:39])


def test_record_is_current(recorded):
    assert recorded['source_sha256']==source_hashes(), 'HISTORICAL RECORD: not current 47 rows / 51 conditions; --record-all not authorized in MG-06'
    assert len(recorded['cases'])==len(CASES)
    assert len(recorded['rows'])==47

@pytest.fixture(scope='module')
def recorded():
    record = load_record()
    assert record['state'] == 'complete_full_measurement', 'run the explicit --record-all command first'
    # Immutable historical record; current contrasts still run independently.
    assert record['source_sha256'], 'missing historical source identity'
    return record


@pytest.mark.parametrize('case', LEGACY_CASES, ids=lambda case: case.id)
def test_mutant(case, capsys, recorded):
    with capsys.disabled():
        result = measure_case(case)
    CURRENT_RESULTS[case.id] = result
    if recorded['source_sha256'] == source_hashes():
        expected = next(r for r in recorded['cases'] if r['id'] == case.id)
        compare_case(expected, result)
    # Preserve the three unconnected red tests; recording never blesses them.
    assert_identified(result)


def test_recorded_population(recorded):
    assert len(recorded['cases']) == recorded['measurement']['cases']
    assert len(recorded['rows']) == sum(recorded['row_totals'].values())
    assert len({r['id'] for r in recorded['cases']}) == len(recorded['cases'])
    assert len({r['target'] for r in recorded['rows']}) == len(recorded['rows'])
    assert set(r['target'] for r in recorded['rows']) <= set(ROW_ORDER)
    for case in CASES:
        overrides = [n for n,v in vars(case.window).items() if callable(v) and hasattr(m.CorrectWindow,n)]
        assert len(overrides) == 1, case.id + ': not one public override'
    assert len(ROW_ORDER) == 47 and len(CONDITION_ORDER) == 51
    if recorded['source_sha256']==source_hashes():
        assert_full_population(recorded['cases'])
        validate_rows(recorded['rows'],recorded['cases'],recorded['evidence'])
        assert recorded['conditions']==condition_table(recorded['cases'])
        assert recorded['report_markdown']==measured_report(recorded)


def test_mixed_row_marked_confirmed_is_rejected(recorded):
    wrong = row_table(recorded['cases'], recorded['evidence'])
    row = next(r for r in wrong if r['target'] == 'INV-2.a')
    assert row['branch_counts']['確認済み'] and row['branch_counts']['未接続']
    row['confirmation_status'] = '確認済み'
    with pytest.raises(AssertionError, match='INV-2.a'):
        validate_rows(wrong, recorded['cases'], recorded['evidence'])


def test_7b_returned_to_unreached_is_rejected(recorded):
    wrong = row_table(recorded['cases'], recorded['evidence'])
    row = next(r for r in wrong if r['target'] == 'INV-7.b')
    row.update(status='unreached_or_incomplete', label='未到達・未完', confirmation_status='未確認')
    with pytest.raises(AssertionError, match='INV-7.b'):
        validate_rows(wrong, recorded['cases'], recorded['evidence'])
    wrong = row_table(recorded['cases'], recorded['evidence'])
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
        rows = row_table(recorded['cases'], recorded['evidence'])
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
    with pytest.raises(AssertionError, match='ALL'):
        assert_full_population(recorded['cases'][:-1])
    with pytest.raises(SystemExit):
        cli_parser().parse_args(['--record-all', '-k', 'M-2a'])

def cli_parser():
    parser = argparse.ArgumentParser(description='Explicit full measurement only; normal pytest never writes records.')
    parser.add_argument('--record-all', required=True, action='store_true', help='run ALL declared contrasts and replace the single results JSON')
    return parser


def record_all():
    """Only this explicit command writes; no checkpoint or partial merge."""
    before = source_hashes()
    old = load_record() if RESULTS_PATH.exists() else {}
    evidence = read_evidence(old.get('evidence', {}))
    started = now()
    start = perf_counter()
    legal_control.cache_clear()
    results = [mg_d6_result(case) if case.id=='MG-10' else measure_case(case) for case in CASES]
    assert_full_population(results)
    assert before == source_hashes(), 'target version changed during measurement; old record retained'
    rows = row_table(results, evidence)
    validate_rows(rows, results, evidence)
    paper = ROOT / PAPER_PATH
    record = dict(schema_version=3, state='complete_full_measurement', source_sha256=before,
        paper=dict(path=PAPER_PATH, sha256=sha256(paper.read_bytes()).hexdigest() if paper.exists() else None),
        command='.venv/Scripts/python.exe -B tests/test_fb_mutants.py --record-all',
        measurement=dict(started_at=started, finished_at=now(), seconds=round(perf_counter()-start, 3),
            cases=len(results), classes=len({c.window for c in CASES}),
            identified_cases=sum(r['status'] == 'identified' for r in results),
            missed_cases=sum(r['status'] == 'not_detected' for r in results),
            unresolved_cases=sum(r['status'] == 'unreached_or_incomplete' for r in results),
            max_states=max(max(r['states'], r['control_states']) for r in results),
            legal_control_violations=0, contract_violations=sum(len(r['boundary_errors']) for r in results)),
        denominators=dict(rows=47,conditions=51,cases=len(CASES)),
        evidence=evidence, cases=results, rows=rows, conditions=condition_table(results),
        row_totals={label: sum(r['status'] == key for r in rows) for key, label in STATUS_LABELS.items()},
        confirmation_totals={label: sum(r['confirmation_status'] == label for r in rows) for label in CONFIRMATION_LABELS},
        historical_snapshots=old.get('historical_snapshots', []) + ([{k:v for k,v in old.items() if k!='historical_snapshots'}] if old else []), audit=MG06_AUDIT+'\n'+MG06_TURN2_AUDIT,
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


MG06_AUDIT = """
TURN 1 HISTORICAL AUDIT; continuation decisions/results follow in MG06_TURN2_AUDIT.
2026-10-17 / MG-06 / paper v0.18 (2112 lines), SHA256
 a3605ac06bbb0657ec6a7078e4d1f7885f29ce257d40546c5f0b03064e8ffc6d.
29 proposals were saved in fb_mutants.py BEFORE implementation. P=17/29;
C=12 supplied examples. One public override per subclass, no data marker.
Inherited A-M-XC and row-display conventions remain historical; new naming
assumption A-MG-WIRE (1): finite conditional DF slot/key and late-value wire.
Semantic additions=0. The finite D prefix does not certify real PR/IE/ID.

Actual public observations drive the premise. In particular ReadInputs must
show the changed args/reader/view; changing a window-owned copy alone is not
enough. CG body changes keep the actual Program and E0 unchanged. E0, actual
EH/EW/EL and observation contracts are never modified after execution starts.
Cuts are local safety checks, not whole-path/progress certification. All
outside continuations/atomic-hook limits remain in reports. The control uses
identical E0, full legal prefix, initial State, Cut and operation availability.
D6/R10 has no legal runnable control: the ordinary public scene raises
MissingContract before entry; the normalization mutant is not_run/unconnected.
This is not a successful zero-violation R10 pair and not a 58-condition claim.

First design audits and repairs (not checker repairs):
- Publish Decision does not yet include environment-installed condition births.
  MG-01/MG-20 therefore test loss after PUB through drain, and keep the original
  atomic omission clauses explicitly unconfirmed. No automatic-birth pass is
  claimed from these loss tests.
- Enter's public effect is (work-id, token, NumericalView), not a Descriptor.
  Actual DescriptorRead/ReadInputs observe returned window custody; MG-09/23
  were corrected before final population execution after this public probe.
- pG also lives in GenerationContinuation.purpose. MG-03 initially erased only
  diagnostic excuses, leaving that carrier. The final mutant erases the pG
  purpose/target payload there too. MG-21/22 change every retained pG carrier.
- A made-up DF without an E0 followup did not establish the originating Draw.
  Final MG-12 declares a finite conditional plan before execution, with a
  fixed late-value body. Its single fault uses that late value despite first
  Failure. A Source(first outcome) version had generic plan-difference hits;
  that does NOT prove discrimination of the first-Failure clause. The final
  fixed-body version is the relevant measurement.
- MG-29 now includes CG authorized by the same wrong late-success first-end
  choice. Its earlier knowledge-only form reached INV-15.b but no 16.c chain;
  that earlier result was a target-route design limit, not a 16.c hole.
- MG-12 target audit: paper 885 explicitly owns the first-kind/DF prohibition
  in INV-15.b; paper 887 does not make this same-Draw example a different
  problem/purpose/context/value. The declared 16.b target is NOT retargeted to
  its 15.b collateral hit. Mark target design unestablished, keep the old real
  16.b scope bridge, and do not call this a checker hole.
- MG-15 is STOPPED for interpretation/observation: after EndKnown the same
  live Wg already owns issue[CG]. Clearing handle's unmet flag alone does not
  prove that a permitted same-owner Transfer is absent. No loss is inferred
  from that flag. Need a public acceptance contract/observation to distinguish
  legal Transfer from abandonment (paper 1943-1944,1951,1961). No forced choice.

- Report transport audit: PowerShell stdin converted some newly written
  Japanese status literals to question marks. Final code uses the existing
  CONFIRMATION_LABELS constants. validate_rows checks every branch label and
  sum(branch_counts)==len(branches), preventing silent loss from counts.
  The initial full run is superseded by the final rerun after this repair.

- Current 239-scene public manifest is retained: 193 historical observations
  plus 46 current declarations. Full-scene execution is not_run here, separate
  from the local mutant prefixes. Hung-D cap1/cap2 and D6 stay unconnected;
  the other new declarations remain unconfirmed, never promoted from another
  agent's reported 43 passes. The final focused reporting tests check this.

Read boundary: paper 1580-1630,1918-1973 and related row clauses; our two test
files; public model contracts/AllowedPlan docstring, dataclass declarations,
CorrectWindow/Environment signatures/docstrings, Scene E0/script/instantiate
and actual public API outputs. Existing local Obsidian knowledge was read in
relevant portions (A-G taxonomy in full); historical reports are information,
not permission. Public scene result JSON is historical, not rerun here.
External web sources: none. No test_fb_scenes.py full execution.
Self-declared deviation: the first AST API inventory also printed signatures
and docstrings of non-underscore checker helper/predicate functions. No body
of CorrectWindow, Environment or checker was printed/read. This exposure
prevents claiming perfect read-boundary compliance; paper remains the source
of expected outcomes. Subsequent reads were narrowed to declared interfaces.
SHA256-only file reads do not expose implementation content.

Normal pytest never writes results JSON. An explicit --record-all remains the
sole future writer and includes every case/disposition plus 47/51 identity;
it was NOT executed for MG-06. Historical 39/45 results are not current passes.
Obsidian Sessions/Projects/Knowledge/Heat are NOT updated under the two-file
limit. This audit is the permitted local note; no artifact copied to vault.
Reused knowledge: A-G taxonomy and independent declarations vs actual facts,
applicable; it prevented counting redundant-carrier deletion and generic plan
mismatch as the requested discrimination.
Own Codex session: C:/Users/you11/.codex/sessions/2026/10/17/
rollout-2026-10-17T03-14-39-01a145ec-596f-7ca2-a5f4-bb9998e77de5.jsonl.
No direct Claude exchange; supplied handoff names were information only.
"""

MG06_LAST_RUN_NOTE = """
2026-10-17 MG-06 TURN 1 HISTORICAL result; superseded by MG06_TURN2_AUDIT.
This note is NOT a test oracle.
9 failed, 67 passed, 1 skipped in 140.38 s; all 68 dispositions; 67 runnable controls zero violations; MG-10 not_run
New MG cases: 23 identified; 3 target misses (09/23/24); 2 target-design/observation limits (12/15); 1 not_run (10/R10).
All 67 runnable positive controls: zero violations and zero observation-contract violations. D6 has no runnable control.
Final full command: .venv/Scripts/python.exe -B -m pytest tests/test_fb_mutants.py -q -s --tb=line -p no:cacheprovider
Failure partition: MG-09/23/24 target misses; MG-12 wrong target; MG-15 Transfer unestablished;
 M-2d/M-LD/M-13b prior unconnected cases; stale-record guard (expected under no-record-write instruction).
After full run: reporting-only preservation of the 46 current scene declarations; 8 reporting tests passed / 69 deselected in 0.63 s.
Full scene suite NOT run; 239 declaration identities retained (193 old records + 46 current not_run declarations).
New blockers retained: SC-14-M3-Hung-D-cap1/cap2; SC-09-M3-D6-generation-draw.
JSON unchanged SHA256 612cb775b8f86fe22055f8f8498739e84e15ca802b0c1924daa28843bb47de91; --record-all was NOT run.
Rows 47: identified=36, not_detected=1, unreached_or_incomplete=3, out_of_scope=7.
Row confirmation: unconnected=40, outside=7; independently confirmed contrasts do not certify whole rows.
Conditions 51: confirmed finite slices=5, unconfirmed=45 (old44 + issue[EQ] atomic-birth clause), unconnected=1 (handle).
MG-01/MG-20 test post-Publish loss; original atomic omission contrasts remain not_run/unconfirmed.

Individual new cases: id | target | result | states wrong/control | legal prefix steps
MG-01 | INV-2.g | identified | 2/1 | 49
MG-02 | INV-2.g | identified | 2/1 | 54
MG-03 | INV-2.g | identified | 2/1 | 54
MG-04 | INV-2.g | identified | 2/1 | 54
MG-05 | INV-2.g | identified | 2/2 | 60
MG-06 | INV-16.c | identified | 2/1 | 48
MG-07 | INV-16.c | identified | 2/1 | 48
MG-08 | INV-16.c | identified | 2/1 | 48
MG-09 | INV-16.c | not_detected | 2/2 | 32
MG-10 | INV-16.c | unreached_or_incomplete | 0/0 | not_run
MG-11 | INV-15.a | identified | 2/1 | 41
MG-12 | INV-16.b | unreached_or_incomplete | 2/1 | 57
MG-13 | INV-2.g | identified | 2/1 | 14
MG-14 | INV-2.g | identified | 2/1 | 43
MG-15 | INV-2.g | unreached_or_incomplete | 2/1 | 43
MG-16 | INV-2.g | identified | 2/1 | 48
MG-17 | INV-2.g | identified | 2/1 | 49
MG-18 | INV-2.g | identified | 2/1 | 55
MG-19 | INV-2.g | identified | 2/2 | 54
MG-20 | INV-2.g | identified | 2/1 | 55
MG-21 | INV-2.g | identified | 2/1 | 54
MG-22 | INV-2.g | identified | 2/1 | 54
MG-23 | INV-16.c | not_detected | 2/2 | 32
MG-24 | INV-16.c | not_detected | 2/2 | 32
MG-25 | INV-16.c | identified | 2/2 | 48
MG-26 | INV-16.c | identified | 2/2 | 48
MG-27 | INV-16.c | identified | 2/2 | 54
MG-28 | INV-16.c | identified | 2/2 | 54
MG-29 | INV-16.c | identified | 2/1 | 57

Exclusive row groups (confirmation unconnected except out_of_scope rows):
identified: INV-1.a, INV-1.b, INV-1.c, INV-2.a, INV-2.b, INV-2.c, INV-2.e, INV-2.f, INV-3.a, INV-3.b, INV-3.c, INV-4.a, INV-4.b, INV-4.c, INV-5.a, INV-5.b, INV-5.c, INV-6.a, INV-6.b, INV-6.c, INV-7.a, INV-7.c, INV-8.a, INV-8.b, INV-9.a, INV-10.a, INV-10.b, INV-11.a, INV-11.b, INV-11.c, INV-12.b, INV-13.a, INV-15.a, INV-15.b, L-RECEIPT, INV-2.g
unreached_or_incomplete: INV-2.d, INV-13.b, L-DERIVE
out_of_scope: INV-7.b, INV-9.b, INV-12.a, INV-14.a, INV-14.b, INV-16.a, INV-16.b
not_detected: INV-16.c

Scope decisions: paper v0.18:1880,1891-1892; original seven implementation-stage bridges remain.
MG-12 is a paper-885/1969 first-kind fault, detected under INV-15.b. Its predeclared 16.b target was not silently retargeted.
MG-15: stopped; the same live Wg already owns issue[CG]. Need public Transfer acceptance evidence; no owner meaning was forced.
MG-09/23/24 actual ReadInputs differ from fixed Qgen; INV-16.c does not report them in the declared entry-local Cut.
 Existing INV-8.b detects all three, so these are target-row discrimination gaps, not whole-checker escapes. CG/EQ continuation of these cases is untested.
Only the two permitted Python files written; no commit, environment variable, vault/Heat or record write.
Reuse: independent actual inputs vs window copies and alternate carriers (A-G taxonomy) were effective.
Read-scope deviation is declared in MG06_AUDIT; no implementation bodies were displayed.
"""

MG06_TURN2_AUDIT = """
2026-10-17 MG-06 continuation 2; NOT a test oracle.
Position: F-b finite-model discrimination, before real F-a integration.
Paper-absent assumptions: A-MG-WIRE representation 1, semantic additions 0;
no additional assumption introduced by this continuation. Owner decisions 0.
Same family: initial MG-06 investigation, second continuation measurement.

The population amendment in fb_mutants.py was saved BEFORE code/target changes.
MG-12 now targets INV-15.b, paper 885/1969: the first logical end kind is fixed;
first Failure permits only T, so the later value must not authorize DF.
The old INV-16.b declaration was a design error (paper 887 requires a different
problem/purpose/context/Point/value). The mutant is unchanged. A fresh rerun,
not a relabelled old collateral hit, is required to establish discrimination.
MG-15 is unconnected, not a semantic pass/violation. Independent same-Wg Transfer
acceptance remains unavailable; existing issue[CG] is an alternate live carrier.
C-05 is supplied technical precedent, not independently rerun evidence.
Paper 1340,1586-1590,1943,1951 requires retaining this unknown in the denominator.
MG-01/MG-20 post-Publish loss contrasts remain; atomic omission contrasts are
not_run/unconfirmed known review gaps, paper 1937/1944/1946. No same-step pass.
MG-09/23/24: checker changes are user-supplied information. Only public outputs
of a fresh measurement can confirm INV-16.c; checker internals remain unread.

Read scope this continuation: paper selected sections (885/887,1334-1342,
1584-1600,1931-1969); own two test modules; public SCENES/E0/execution outputs;
Obsidian Home/Heat, sui project excerpt, relevant session excerpts. Historical
A-G taxonomy reused for alternate-carrier/premise distinction; it is applicable.
No implementation bodies of window, Environment or checker read this turn.
Prior turn signature/docstring inventory overreach remains disclosed in the
historical audit, not erased. No external web sources. No direct Claude message.
No commit, --record-all, environment variable, vault/Heat or other file write.
Explicit two-file permission overrides common vault log writing; this permitted
module holds the audit pending later authorized vault transcription.
Codex session: C:/Users/you11/.codex/sessions/2026/10/17/rollout-2026-10-17T03-14-39-01a145ec-596f-7ca2-a5f4-bb9998e77de5.jsonl
Fresh continuation-2 execution (manual audit, NOT a test oracle):
Targeted MG-09/12/15/23/24 + denominator helper: 6 passed, 71 deselected, 3.96s.
Full normal pytest: 4 failed, 72 passed, 1 skipped, 137.66s (exit 1).
Command: .venv/Scripts/python.exe -B -m pytest tests/test_fb_mutants.py -q -s --tb=line -p no:cacheprovider
Only stdout was filtered in PowerShell; no output file or JSON record write.
New 29: 27 identified; MG-10 R10 not_run/unconnected; MG-15 executed/unconnected.
All 68 cases: 63 identified, 5 unestablished (old M-2d/M-LD/M-13b, MG-10/MG-15).
All 67 runnable legal controls: zero findings and zero observation-contract violations;
same E0, legal prefix, initial State and Cut. MG-10 has no runnable legal control.
MG-15 pytest pass confirms retained unconnected disposition, never semantic correctness.
MG-09/23/24 independently hit INV-16.c and retain collateral INV-8.b findings.
MG-12 unchanged mutant was freshly detected at the redeclared INV-15.b target.
Remaining failures: M-2d/M-LD paper premise unavailable (ReadyN/Match/Discharge);
 M-13b cross-initial relational row not_run / target absent; stale-record guard.
No confirmed new target misses. No checker fix was performed.
Rows 47: identified=37, not_detected=0, unreached_or_incomplete=3, out_of_scope=7.
Row confirmation: unconnected=40, outside=7; finite identification is not whole-row certification.
Condition schemas 51: confirmed finite slices=5, unconfirmed=45, unconnected=1.
Old 44 condition schemas remain unconfirmed here. issue[EQ] remains unconfirmed
 because atomic birth is not_run; handle remains unconnected. MG-20 atomic run
 obligation contrast also remains explicitly unconfirmed under INV-2.g branches.
Historical record did not match current sources; it was NOT refreshed.
JSON before/after SHA256: 612cb775b8f86fe22055f8f8498739e84e15ca802b0c1924daa28843bb47de91
Closure: all new individual dispositions settled with reasons; executable positive
 controls zero; JSON unchanged. Full CLI remains red for the four failures above.

Individual fresh cases: id | target | result | states wrong/control | legal prefix steps
MG-01 | INV-2.g | identified | 2/1 | 49
MG-02 | INV-2.g | identified | 2/1 | 54
MG-03 | INV-2.g | identified | 2/1 | 54
MG-04 | INV-2.g | identified | 2/1 | 54
MG-05 | INV-2.g | identified | 2/2 | 60
MG-06 | INV-16.c | identified | 2/1 | 48
MG-07 | INV-16.c | identified | 2/1 | 48
MG-08 | INV-16.c | identified | 2/1 | 48
MG-09 | INV-16.c | identified | 2/2 | 32
MG-10 | INV-16.c | unreached_or_incomplete (not_run/unconnected) | 0/0 | not_run
MG-11 | INV-15.a | identified | 2/1 | 41
MG-12 | INV-15.b | identified | 2/1 | 57
MG-13 | INV-2.g | identified | 2/1 | 14
MG-14 | INV-2.g | identified | 2/1 | 43
MG-15 | INV-2.g | unreached_or_incomplete (executed/unconnected) | 2/1 | 43
MG-16 | INV-2.g | identified | 2/1 | 48
MG-17 | INV-2.g | identified | 2/1 | 49
MG-18 | INV-2.g | identified | 2/1 | 55
MG-19 | INV-2.g | identified | 2/2 | 54
MG-20 | INV-2.g | identified | 2/1 | 55
MG-21 | INV-2.g | identified | 2/1 | 54
MG-22 | INV-2.g | identified | 2/1 | 54
MG-23 | INV-16.c | identified | 2/2 | 32
MG-24 | INV-16.c | identified | 2/2 | 32
MG-25 | INV-16.c | identified | 2/2 | 48
MG-26 | INV-16.c | identified | 2/2 | 48
MG-27 | INV-16.c | identified | 2/2 | 54
MG-28 | INV-16.c | identified | 2/2 | 54
MG-29 | INV-16.c | identified | 2/1 | 57

Exclusive fresh row groups (confirmation unconnected except outside rows):
identified: INV-1.a, INV-1.b, INV-1.c, INV-2.a, INV-2.b, INV-2.c, INV-2.e, INV-2.f, INV-3.a, INV-3.b, INV-3.c, INV-4.a, INV-4.b, INV-4.c, INV-5.a, INV-5.b, INV-5.c, INV-6.a, INV-6.b, INV-6.c, INV-7.a, INV-7.c, INV-8.a, INV-8.b, INV-9.a, INV-10.a, INV-10.b, INV-11.a, INV-11.b, INV-11.c, INV-12.b, INV-13.a, INV-15.a, INV-15.b, L-RECEIPT, INV-2.g, INV-16.c
not_detected: (none)
unreached_or_incomplete: INV-2.d, INV-13.b, L-DERIVE
out_of_scope: INV-7.b, INV-9.b, INV-12.a, INV-14.a, INV-14.b, INV-16.a, INV-16.b

Next: Claude can review these known limits and independently decide whether to
 execute the explicit record-all flow after overall confirmation. It was not run here.
Vault Session/Projects/Knowledge/Heat updates remain unperformed under the two-file limit.
Reusable knowledge result: alternate carriers and actual-observation premises were useful.
"""

if __name__ == '__main__':
    cli_parser().parse_args()
    raise SystemExit(record_all())
