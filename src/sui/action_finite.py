"""Finite clock/dispatch hypotheses and time-ordered state/mode skeletons.

Only actual world transitions are sampled. Query labels are inserted by Markov
bridges; they do not create B trials. Known CTMC exponentials use the existing
known-Q numerical primitive (floating rounding is outside the certificate).
"""
from dataclasses import dataclass, replace
from fractions import Fraction as F
from functools import lru_cache
from types import MappingProxyType
import hashlib
import math
import numpy as np

from .action_types import *
from .action_model import load_canonical, canonical, rational
from .action_learning import measure
from .inference import transition
from .dispatch import command_json
from .values import _thaw

NS=1000000000


def needed(model):
    d=load_canonical(model.declaration)
    a=d['activity']; ex=d['execution']; clock=d['clock']
    return (any(x for q in a['Q_by_mode'].values() for row in q for x in row)
        or len(a['modes'])>1 or bool(a['calendar'])
        or (clock['kind']=='clock-process' and any(c['kind']!='exact' for c in clock['candidates']))
        or any(len(set(rational(x,'speed') for x in row))>1 for c in d['completion']['candidates'] for row in c)
        or any(w['kind']=='known' and len(w['points'])>1 for w in d['work'].values())
        or (ex['family']['name']=='wait-dispatch' and
            (len(ex['chi']['candidates'])>1 or any(law is not None and
                (law['given'] or len(law['rows'][0]['points'])!=1 or law['rows'][0]['points'][0]!=[[0,1],[1,1]])
                for law in [ex['think'],ex['receipt'],*[c['delay'] for c in ex['chi']['candidates']],*ex['confirmations'].values()]))))


def scope(model):
    d=load_canonical(model.declaration); c=d['clock']; ex=d['execution']; a=d['activity']
    def stop(reason): return ActionSupport(status='incomplete',stage=None,reason=reason,method=None,conditions=())
    if c['kind']=='legacy-measure' and any(x['name']!='exact' for x in c['measure']['candidates']): return stop('continuous_timing')
    if c['kind']=='clock-process' and any(x['phase_ns']=='uniform' for x in c['candidates']): return stop('continuous_timing')
    for action,w in d['work'].items():
        if w['kind']!='known': return stop('algorithm_unavailable')
        zero=sum((rational(p,'work') for value,p in w['points'] if value==0),F(0))
        if zero==1: return ActionSupport(status='incompatible',stage=None,reason='certain_zero_repetition',method=None,conditions=())
        if zero: return stop('algorithm_unavailable')
        ai=model.actions.index(action)
        varying=any(len(set(map(tuple,candidate[ai])))>1 for candidate in d['completion']['candidates'])
        if varying and any(x for q in a['Q_by_mode'].values() for row in q for x in row):
            # A finite ruler is possible when all state-changing modes begin only
            # after this job has completed. Prove it from the declaration.
            reachable=set(a['modes'])
            active={m for m in reachable if any(x for row in a['Q_by_mode'][m] for x in row)}
            initial={m for i,m in enumerate(a['modes']) if any(rational(x,'mode') for x in a['initial_given_state'][i])}
            dispatched={d['effects'][action]['mode_on_dispatch'][m] for m in initial}
            if active & dispatched or a['calendar']: return stop('continuous_timing')
    if d['completion']['time_unit'] not in ('s','ns'): return stop('continuous_timing')
    if any(law is not None and set(law['given']) & {'state','mode'} for law in ex['confirmations'].values()):
        return ActionSupport(status='missing_spec',stage=None,reason='notification_kernel',method=None,conditions=())
    stage='3' if ex['family']['name']=='wait-dispatch' and (
        any(x['kind']!='exact' for x in c.get('candidates',())) or len(ex['chi']['candidates'])>1 or
        any(law['given'] or len(law['rows'][0]['points'])!=1 for law in [ex['think'],ex['receipt'],*[x['delay'] for x in ex['chi']['candidates']]])) else '2'
    return ActionSupport(status='certified',stage=stage,reason=None,method='finite_state_mode_clock_mixture',
        conditions=('known_Q_time_order','finite_dispatch_clock_support','column_dirichlet_product_mixture','single_trial_at_dispatch','finite_depth'))


def clock_read(clock,t,origin=0):
    if t is None: return None
    value=t if clock['kind']=='exact' else clock['width_ns']*((t-rational(clock['phase_ns'],'phase'))//clock['width_ns'])
    if F(value).denominator!=1:
        raise ActionIncomplete(reason='continuous_timing',detail='event clock reading is not an integer')
    return origin+int(value)


def boundary(clock,s,origin=0):
    s-=origin
    if clock['kind']=='exact': return F(s)
    return F(clock['width_ns'])*(-(-s//clock['width_ns']))+rational(clock['phase_ns'],'phase')


def _clock(d,i):
    if d['clock']['kind']=='clock-process': return d['clock']['candidates'][i]
    return {'kind':'exact'}


@dataclass(frozen=True,slots=True)
class Knot:
    key: tuple
    state: int
    mode: str
    response: str | None = None


@dataclass(frozen=True,slots=True)
class Path:
    probability: F
    initial: int
    counts: tuple
    hypotheses: tuple
    knots: tuple
    events: tuple=()
    node_ns: F=F(0)
    reference_ns: F | None = None
    clock_origin_ns: int = 0


@dataclass(frozen=True,slots=True)
class Data:
    model: object
    events: tuple
    paths: tuple
    reports: object
    observations: tuple
    evidence: F
    origins: object
    node_origin: NodeOrigin | None
    finite: bool=True
    reference_paths: tuple | None = None


@dataclass(frozen=True,slots=True)
class ReportPosition:
    command: Command
    measurement_ns: F | None
    completion_ns: F | None
    fixed: bool
    attempt: str | None = None
    measurement_labels: tuple = ()
    completion_labels: tuple = ()


def report_position(model,paths,command,attempt):
    """Freeze the actual experiment's label support when adopting a report."""
    at=load_canonical(model.declaration)['effects'][command.action]['measure']['at']
    events=[next(e for e in p.events if e.command==command) for p in paths]
    measurement=tuple(sorted({e.dispatch_ns if at=='start' else e.completion_ns for e in events}))
    completion=tuple(sorted({e.completion_ns for e in events}))
    return ReportPosition(command,measurement[0] if len(measurement)==1 else None,
        completion[0] if len(completion)==1 else None,len(measurement)==len(completion)==1,
        attempt,measurement,completion)


def joined_origin(previous,attempt,paths):
    if previous is not None and all(all(next(e.completion_ns for e in p.events if e.report==a)==p.node_ns
        for a in previous.attempts) for p in paths):
        return NodeOrigin(attempts=previous.attempts+(attempt,))
    return NodeOrigin(attempts=(attempt,))


def make(model,context,paths,reports,observations,status,evidence=F(1),*,origins=None,node_origin=None,reference_paths=None):
    from .action_joint import _log
    events=max((p.events for p in paths),key=len,default=())
    def fraction(x): return None if x is None else [x.numerator,x.denominator]
    body={'model':model.ref,'now':context.now_ns,'observed':context.observed_ns,'run':str(context.run),
        'paths':[[fraction(p.probability),p.counts,p.hypotheses,
            [[fraction(k.key[0]),*k.key[1:],k.state,k.mode,k.response] for k in p.knots],
            [[command_json(e.command).decode(),fraction(e.dispatch_ns),fraction(e.completion_ns),e.report,fraction(e.decision_ns),fraction(e.receipt_ns),fraction(e.work)] for e in p.events],fraction(p.node_ns),p.clock_origin_ns] for p in paths],
        'observations':observations,'checks':_thaw(context.check_events),
        'origins':[[list(k),None if v is None else list(v.attempts)] for k,v in sorted((origins or {}).items())],
        'node_origin':None if node_origin is None else list(node_origin.attempts),
        'source':None if context.clock_source is None else str(context.clock_source)}
    key=hashlib.sha256(canonical(body)).hexdigest()
    data=Data(model,events,tuple(paths),MappingProxyType(dict(reports)),tuple(observations),evidence,
        MappingProxyType(dict(origins or {})),node_origin,reference_paths=reference_paths)
    return ActionBelief(model_ref=model.ref,context=context,evidence_key=key,status=status,
        log_evidence=Bounds(_log(evidence),_log(evidence),None),evidence_kind='mass',_data=data)


def as_finite(belief,budget):
    """Embed the exact Q=0 representation when a later real history needs it.

    This preserves the frozen root's law. Inactive finite hypotheses are
    expanded with their own prior weights, rather than learned from current.
    """
    if getattr(belief._data,'finite',False): return belief
    from .ids import derive,RefKind
    data=belief._data; model=data.model; d=load_canonical(model.declaration)
    if needed(model): raise ActionInputError(reason='schema',detail='finite model has an incompatible root representation')
    rows=[]; hypotheses=prior(model); events=[]; reports={}
    for e in data.events:
        attempt=next((name for name,position in data.reports.items() if name.startswith(('plan:','attempt:')) and position.command==e.command),
            str(derive(RefKind.ATTEMPT,'s4b.action.predicted_attempt',command_json(e.command).decode())))
        events.append(replace(e,report=attempt))
    for p in data.paths:
        for h in hypotheses:
            if h.initial!=p.initial: continue
            knots=h.knots; state=p.initial; mode=knots[0].mode
            for i,e in enumerate(events):
                knots+=(Knot((*e.key,0),state,mode),Knot((*e.key,1),p.posts[i],mode))
                state=p.posts[i]
            rows.append(Path(p.probability*h.probability/rational(d['D'][p.initial],'D'),p.initial,p.counts,
                h.hypotheses,knots,tuple(events),F(belief.context.now_ns)))
    paths=_guard(rows,budget)
    for name,e in data.reports.items():
        attempt=next(v.report for v in events if v.command==e.command)
        position=report_position(model,paths,e.command,attempt)
        reports[name]=position; reports[attempt]=position
    result=make(model,belief.context,paths,reports,data.observations,belief.status,data.evidence,
        origins=data.origins,node_origin=data.node_origin)
    return replace(result,evidence_key=belief.evidence_key)


def boot_reading(reading,run):
    from .timeline import _membrane,_data
    from .s4_contracts import BOOT
    boots=[r for r in reading._action_records if r.at.run==run and _membrane(r,BOOT)
        and _data(r)=={} and r.body.received_ns is not None]
    return min(boots,key=lambda r:(r.at.seq,str(r.id))).body.received_ns if boots else 0


def prior(model,origin=0):
    d=load_canonical(model.declaration); a=d['activity']; c=d['clock']
    clocks=c['candidates'] if c['kind']=='clock-process' else c['measure']['candidates']
    chi=d['execution']['chi']; chis=[{'weight':[1,1]}] if chi is None else chi['candidates']
    result=[]
    for s,p in enumerate(d['D']):
        for mi,m in enumerate(a['modes']):
            for r,rw in enumerate(d['completion']['weights']):
                for l,lc in enumerate(clocks):
                    for ch,cc in enumerate(chis):
                        mass=rational(p,'D')*rational(a['initial_given_state'][mi][s],'mode')*rational(rw,'rho')*rational(lc['weight'],'lambda')*rational(cc['weight'],'chi')
                        if mass: result.append(Path(mass,s,measure(model).zero,(r,l,ch),(Knot((F(0),-3,0,1),s,m),),clock_origin_ns=origin))
    return tuple(result)


def _guard(paths,budget):
    if len(paths)>budget.node_budget: raise ActionIncomplete(reason='budget',detail='finite state/mode/hypothesis enumeration exceeds budget')
    return tuple(paths)


@lru_cache(maxsize=512)
def matrix(model,mode,elapsed):
    d=load_canonical(model.declaration); q=np.asarray(d['activity']['Q_by_mode'][mode],dtype=float)
    if not np.any(q) or not elapsed:
        return tuple(tuple(F(int(i==j)) for j in range(len(q))) for i in range(len(q)))
    try: dt=float(elapsed/NS)
    except OverflowError as exc:
        raise ActionNumericalRange(reason='overflow',detail='CTMC interval exceeds float range') from exc
    if not math.isfinite(dt): raise ActionNumericalRange(reason='overflow',detail='CTMC interval exceeds float range')
    if dt==0: raise ActionNumericalRange(reason='positive_underflow',detail='positive CTMC duration disappeared')
    try: p=transition(q,dt)
    except (ValueError,FloatingPointError,OverflowError) as exc:
        raise ActionNumericalRange(reason='invalid_interval',detail='known-Q exponential failed') from exc
    reachable=q>0
    np.fill_diagonal(reachable,True)
    for k in range(len(q)): reachable|=reachable[:,k,None]&reachable[None,k,:]
    if np.any(reachable & (p==0)):
        raise ActionNumericalRange(reason='positive_underflow',detail='positive CTMC transition disappeared')
    # Exact normalization of the computed columns avoids artificial mass loss.
    columns=[tuple(F(float(p[i,j])) for i in range(len(q))) for j in range(len(q))]
    return tuple(tuple(columns[j][i]/sum(columns[j]) for j in range(len(q))) for i in range(len(q)))


def _step(model,paths,key,budget,mode_change=None):
    result=[]
    for path in paths:
        last=path.knots[-1]
        if key<last.key: raise ActionSpecificationMissing(reason='causal_order',detail='finite timeline is not ordered')
        p=world_matrix(model,last.mode,last.response,key[0]-last.key[0])
        n=len(model.states)
        for index in range(len(p)):
            s=index%n; response=last.response if index<n else None
            mass=p[index][last.state]
            if mass:
                mode=last.mode if mode_change is None else mode_change(last.mode)
                result.append(replace(path,probability=path.probability*mass,knots=path.knots+(Knot(key,s,mode,response),)))
    return _guard(result,budget)


@lru_cache(maxsize=512)
def world_matrix(model,mode,response,elapsed):
    if response is None: return matrix(model,mode,elapsed)
    from .action_response import _transition,_generator
    try: dt=float(elapsed/NS)
    except OverflowError as exc:
        raise ActionNumericalRange(reason='overflow',detail='response interval exceeds float range') from exc
    if not math.isfinite(dt): raise ActionNumericalRange(reason='overflow',detail='response interval exceeds float range')
    if elapsed and dt==0: raise ActionNumericalRange(reason='positive_underflow',detail='positive response duration disappeared')
    p=_transition(model,response,mode,elapsed/NS)
    if elapsed:
        reachable=_generator(model,response,mode)>0
        np.fill_diagonal(reachable,True)
        for k in range(len(p)): reachable|=reachable[:,k,None]&reachable[None,k,:]
        if np.any(reachable & (p==0)):
            raise ActionNumericalRange(reason='positive_underflow',detail='positive response transition disappeared')
    columns=[tuple(F(float(p[i,j])) for i in range(len(p))) for j in range(len(p))]
    return tuple(tuple(columns[j][i]/sum(columns[j]) for j in range(len(p))) for i in range(len(p)))


def advance(model,paths,key,budget):
    d=load_canonical(model.declaration); result=[]
    for path in paths:
        # A zero-duration reconstruction checkpoint cannot order a later
        # command ahead of another position in the same physical/causal stage.
        while (len(path.knots)>1 and path.knots[-1].key[3]==-4
                and path.knots[-1].key[0]==path.knots[-2].key[0]
                and key<path.knots[-1].key):
            path=replace(path,knots=path.knots[:-1])
        switches=[]
        for c in d['activity']['calendar']:
            t=rational(c['at_s'],'calendar')*NS
            ck=(t,-2,0,1)
            if path.knots[-1].key<ck<=key: switches.append((ck,lambda m,c=c:c['mode']))
        for e in path.events:
            if e.completion_ns is None: continue
            ck=(e.completion_ns,e.command.causal_stage,e.command.causal_position,1)
            if path.knots[-1].key<ck<=key:
                mapping=d['effects'][e.command.action]['mode_on_completion']
                if any(rational(c['at_s'],'calendar')*NS==e.completion_ns and mapping[c['mode']]!=c['mode'] for c in d['activity']['calendar']):
                    raise ActionSpecificationMissing(reason='causal_order',detail='simultaneous calendar and completion mode changes do not commute')
                switches.append((ck,lambda m,mapping=mapping:mapping[m]))
        rows=(path,)
        for ck,change in sorted(switches,key=lambda pair:pair[0]): rows=_step(model,rows,ck,budget,change)
        if rows[0].knots[-1].key!=key: rows=_step(model,rows,key,budget)
        result.extend(rows)
    return _guard(result,budget)


def delays(model,path,law):
    d=load_canonical(model.declaration); k=path.knots[-1]; r,l,ch=path.hypotheses
    context={'state':model.states[k.state],'mode':k.mode,'rho':r,'lambda':l}
    when=[context[a] for a in law['given']]
    row=next(row for row in law['rows'] if row['when']==when)
    return tuple((None if x=='+inf' else rational(x,'delay')*NS,rational(p,'delay')) for x,p in row['points'] if rational(p,'delay'))


def _delay_step(model,paths,law,time_of,key_of,budget):
    result=[]
    for path in paths:
        for dt,p in delays(model,path,law):
            if dt is None: result.append((replace(path,probability=path.probability*p),None)); continue
            t=time_of(path)+dt
            result.extend((q,t) for q in advance(model,(replace(path,probability=path.probability*p),),key_of(t),budget))
    if len(result)>budget.node_budget: raise ActionIncomplete(reason='budget',detail='delay support exceeds budget')
    return result


def dispatch_paths(model,paths,command,budget,*,decision_reading=None,decision_done=False):
    """Generate Td, Tin and tau; saved rd is likelihood, not a control."""
    from .action_joint import _Event,validate_command
    d=validate_command(model,command); ex=d['execution']; stage,pos=command.causal_stage,command.causal_position
    result=[]
    for path in paths:
        if path.node_ns is None:
            result.append((path,_Event(command,None,None,'')))
            continue
        if ex['family']['name']=='immediate-start': candidates=[(path,path.node_ns)]
        else:
            thought=[(path,path.node_ns)] if decision_done else _delay_step(model,(path,),ex['think'],lambda p:p.node_ns,lambda t:(t,stage,pos,-3),budget)
            receipts=[]
            for p,td in thought:
                if td is None:
                    if decision_reading is None: receipts.append((p,None))
                    continue
                clock=_clock(d,p.hypotheses[1])
                if decision_reading is not None and clock_read(clock,td,p.clock_origin_ns)!=decision_reading: continue
                p=replace(p,node_ns=td)
                receipts.extend(_delay_step(model,(p,),ex['receipt'],lambda p,td=td:td,lambda t:(t,stage,pos,-2),budget))
            candidates=[]
            for p,tin in receipts:
                if tin is None: candidates.append((p,None)); continue
                clock=_clock(d,p.hypotheses[1]); base=max(tin,boundary(clock,command.not_before_ns,p.clock_origin_ns))
                ready=advance(model,(p,),(base,stage,pos,-1),budget)
                for q in ready:
                    law=ex['chi']['candidates'][q.hypotheses[2]]['delay']
                    candidates.extend(_delay_step(model,(q,),law,lambda p,base=base:base,lambda t:(t,stage,pos,0),budget))
        for p,t in candidates:
            tin=next((k.key[0] for k in p.knots if k.key[1:]==(stage,pos,-2)),None)
            result.append((p,_Event(command,t,None,'',p.node_ns,tin)))
    if len(result)>budget.node_budget: raise ActionIncomplete(reason='budget',detail='dispatch support exceeds budget')
    return tuple(result)


def normalize(paths):
    mass=sum((p.probability for p in paths),F(0))
    if not mass: raise ActionModelFalsified(reason='zero_evidence',detail='no finite world explains the adopted evidence')
    return tuple(replace(p,probability=p.probability/mass) for p in paths),mass


def observe_report(model,paths,command,bundle,budget):
    d=load_canonical(model.declaration); e=d['effects'][command.action]; result=[]
    for path in paths:
        event=next(v for v in path.events if v.command==command)
        if event.completion_ns is None: continue
        clock=_clock(d,path.hypotheses[1]); mtime=event.dispatch_ns if e['measure']['at']=='start' else event.completion_ns
        if any(bundle[k] is not None and bundle[k]!=clock_read(clock,t,path.clock_origin_ns) for k,t in
            (('measurement_reading_ns',mtime),('completion_reading_ns',event.completion_ns))): continue
        completion=FixedLabel(time_s=event.completion_ns/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side='post')
        rows=insert(model,path,completion,budget)
        label=FixedLabel(time_s=mtime/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side=e['measure']['side'])
        for q in rows:
            for p in insert(model,q,label,budget):
                counts=p.counts; mass=F(1)
                if bundle['outcome'] is not None:
                    if bundle['outcome'] not in model.outcomes: raise ActionModelFalsified(reason='event_contradiction',detail='unknown outcome')
                    mass,counts=measure(model).observe('Theta',command.action,state_at(p,label),model.outcomes.index(bundle['outcome']),counts)
                notice=bundle['effect_notice']
                if notice is not None:
                    if e['notice'] is None or notice not in e['notice']['labels']:
                        raise ActionModelFalsified(reason='event_contradiction',detail='unknown effect notice')
                    pre=state_at(p,FixedLabel(time_s=event.dispatch_ns/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side='pre'))
                    post=state_at(p,FixedLabel(time_s=event.dispatch_ns/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side='post'))
                    y=e['notice']['labels'].index(notice)
                    mass*=sum((rational(e['marks']['probability'][k][post][pre],'marks')*rational(e['notice']['probability'][y][k][post][pre],'notice') for k in range(len(e['marks']['labels']))),F(0))
                if mass: result.append(replace(p,probability=p.probability*mass,counts=counts,node_ns=event.completion_ns))
    return _guard(result,budget)


def checkpoint(model,paths,reading_ns,stage,budget):
    """Map a known exact reading to model time, retaining BOOT's origin."""
    d=load_canonical(model.declaration); rows=[]
    for p in paths:
        if _clock(d,p.hypotheses[1])['kind']!='exact':
            raise ActionIncomplete(reason='continuous_timing',detail='a frozen tick checkpoint needs a physical-time law')
        t=F(reading_ns-p.clock_origin_ns); key=(t,stage,0,-4)
        label=FixedLabel(time_s=t/NS,causal_stage=stage,causal_position=0,side='post')
        points=advance(model,(p,),key,budget) if key>=p.knots[-1].key else insert(model,p,label,budget)
        rows.extend(replace(q,node_ns=t) for q in points)
    return _guard(rows,budget)


def nonarrival(model,paths,commands,reading_ns):
    """A receipt/check excludes earlier arrivals, without observing a label.

    Equal readings retain the receipt's causal ordering, as in 1c. Repeated
    checks intersect support rather than multiplying independent survivals.
    """
    d=load_canonical(model.declaration)
    return normalize(tuple(p for p in paths if all(
        e.completion_ns is None or clock_read(_clock(d,p.hypotheses[1]),e.completion_ns,p.clock_origin_ns)>=reading_ns
        for e in p.events if e.command in commands)))


def rebuild(model,reading,*,context,budget):
    from .records import Observed,AttemptStarted,JobOpened,Decided
    from .s4b_action_contracts import ATTEMPT,RESERVATION,RECEIPT,DISPATCH,REPORT,DECISION
    from .clock_contracts import SOURCE
    from .s4_contracts import BOOT
    from .s3_contracts import ENDED
    from .dispatch import command_from_json,build_command
    from .action_model import keys
    d=load_canonical(model.declaration); paths=prior(model,boot_reading(reading,context.run)); evidence=F(1); reports={}; observations=[]
    # This broader law has no report/decision/confirmation likelihoods. It
    # contains every root-reference world needed by the noninterference proof.
    reference_paths=paths
    attempts={}; seen={}; done={}; failed=set(); confirmed={}; origins={}; node_origin=None
    jobs={r.id:r.body for r in reading._action_records if isinstance(r.body,JobOpened)}
    decisions={r.id:r for r in reading._action_records if isinstance(r.body,Decided) and r.body.contract==DECISION}
    # _facts deliberately sorts IDs for canonical reading. Recover causality
    # from the frozen ancestry rather than treating that order as world time.
    record_ids={str(r.id) for r in reading._action_records}
    def predecessors(record):
        rid=str(record.id)
        if rid in context.fact_ancestors: return set(context.fact_ancestors[rid]) & record_ids
        containing=[set(v) for v in context.fact_ancestors.values() if rid in v]
        return ((min(containing,key=len)-{rid}) & record_ids if containing else
            {str(r.id) for r in reading._action_records if r.at.run==record.at.run and r.at.seq<record.at.seq})

    def check(sources,frozen_refs=None):
        nonlocal paths,evidence
        for source in sources:
            if 'fact' in source: continue  # the receipt is applied in causal order below
            value=source['unrecorded']
            prior_refs=(set().union(*(context.fact_ancestors[cid] for cid in value['after']))
                if all(cid in context.fact_ancestors for cid in value['after']) else frozen_refs)
            if prior_refs is None:
                raise ActionInputError(reason='schema',detail='saved check has no frozen ancestry')
            commands=tuple(cmd for at,(cmd,rd) in attempts.items() if str(at) in prior_refs and at not in done and at not in failed)
            if commands:
                paths,mass=nonarrival(model,paths,commands,value['reading']); evidence*=mass
    remaining=list(reading._action_records); ordered=[]; adopted=set()
    while remaining:
        ready=[r for r in remaining if predecessors(r)<=adopted]
        if not ready: raise ActionInputError(reason='schema',detail='frozen fact ancestry is cyclic')
        def rank(r):
            b=r.body
            if isinstance(b,AttemptStarted) and b.contract==ATTEMPT:
                c=b.content.as_json()['command']; return (c['causal_stage'],0,c['causal_position'])
            if isinstance(b,Observed) and b.contract in (RESERVATION,RECEIPT,DISPATCH,REPORT):
                at=next((a for a in reading._action_records if a.id==b.caused_by and isinstance(a.body,AttemptStarted)),None)
                if at is not None:
                    c=at.body.content.as_json()['command']; return (c['causal_stage'],1,c['causal_position'])
            return (-1,-1,0)
        ready.sort(key=rank)
        r=ready[0]; ordered.append(r); adopted.add(str(r.id)); remaining.remove(r)
    for record in ordered:
        body=record.body
        if (isinstance(body,Observed) and body.contract not in (SOURCE,BOOT) and body.received_ns is not None):
            prior_refs=predecessors(record)
            commands=tuple(cmd for at,(cmd,rd) in attempts.items() if str(at) in prior_refs and at not in done and at not in failed and at!=body.caused_by)
            if commands:
                paths,mass=nonarrival(model,paths,commands,body.received_ns); evidence*=mass
        if isinstance(body,Observed) and body.contract==ENDED:
            failed.add(body.caused_by)
        if isinstance(body,AttemptStarted) and body.contract==ATTEMPT:
            v=body.content.as_json(); keys(v,'command decision_reading','attempt')
            cmd=command_from_json(canonical(v['command'])); rd=v['decision_reading']
            keys(rd,'run reading_ns work parents','decision_reading')
            if cmd.run!=context.run: raise ActionOutsideEvaluationType(reason='restart_delivery_law',detail='history crosses runs')
            if rd['run']!=str(cmd.run): raise ActionModelFalsified(reason='clock_contradiction',detail='decision run differs')
            bound=build_command(model=model,choice=cmd.choice,decision=DecisionReading(run=cmd.run,reading_ns=rd['reading_ns'],work=rd['work'],parents=frozenset(rd['parents'])),causal_stage=cmd.causal_stage,causal_position=cmd.causal_position)
            if bound!=cmd: raise ActionModelFalsified(reason='event_contradiction',detail='command differs from saved decision')
            key=(cmd.causal_stage,cmd.causal_position)
            if key in origins:
                raise ActionSpecificationMissing(reason='causal_order',detail='attempt causal positions must be unique within the evaluation root')
            origins[key]=node_origin
            job=jobs.get(body.job); decision=None if job is None else decisions.get(job.decision)
            if decision is not None:
                saved=decision.body.content.as_json()
                if saved['root']['parents']!=rd['parents'] or saved['time']['run']!=str(cmd.run):
                    raise ActionModelFalsified(reason='event_contradiction',detail='attempt differs from its frozen decision root')
                check(saved['time']['check_events'],predecessors(decision))
                paths=checkpoint(model,paths,saved['time']['now_ns'],cmd.causal_stage,budget)
                if node_origin is None:
                    reference_paths=checkpoint(model,reference_paths,saved['time']['now_ns'],cmd.causal_stage,budget)
            if node_origin is not None:
                origin_commands=tuple(attempts[next(at for at in attempts if str(at)==name)][0] for name in node_origin.attempts)
                reference_paths=trigger_paths(model,reference_paths,origin_commands,budget)
            unconditioned=[]
            for p,e in dispatch_paths(model,reference_paths,cmd,budget):
                unconditioned.extend(apply(model,p,replace(e,report=str(record.id)),budget))
            reference_paths=_guard(unconditioned,budget)
            rows=[]
            for p,e in dispatch_paths(model,paths,cmd,budget,decision_reading=rd['reading_ns']): rows.extend(apply(model,p,replace(e,report=str(record.id)),budget))
            paths,mass=normalize(rows); evidence*=mass; attempts[record.id]=(cmd,rd)
        elif isinstance(body,Observed) and body.contract in (RESERVATION,RECEIPT,DISPATCH,REPORT):
            if body.caused_by not in attempts: raise ActionModelFalsified(reason='event_contradiction',detail='observation has no adopted attempt')
            v=body.content.as_json(); tag=(body.caused_by,body.contract,body.source_id if body.source_id is not None else str(record.id))
            if tag in seen:
                if seen[tag]!=v: raise ActionModelFalsified(reason='event_contradiction',detail='redelivery content differs')
                if body.contract==REPORT:
                    cmd=attempts[body.caused_by][0]
                    reports[str(record.id)]=report_position(model,paths,cmd,str(body.caused_by))
                continue
            seen[tag]=v; cmd,rd=attempts[body.caused_by]
            if body.contract==REPORT:
                keys(v,'outcome effect_notice measurement_reading_ns completion_reading_ns','report')
                if body.caused_by in done:
                    if done[body.caused_by]!=v: raise ActionModelFalsified(reason='event_contradiction',detail='completion content differs')
                    reports[str(record.id)]=report_position(model,paths,cmd,str(body.caused_by))
                    reports[str(body.caused_by)]=reports[str(record.id)]
                    continue
                done[body.caused_by]=v
                paths,mass=normalize(observe_report(model,paths,cmd,v,budget)); evidence*=mass
                reports[str(record.id)]=report_position(model,paths,cmd,str(body.caused_by))
                reports[str(body.caused_by)]=reports[str(record.id)]
                node_origin=joined_origin(node_origin,str(body.caused_by),paths)
                observations.append((str(record.id),v['outcome'],v['effect_notice']))
            else:
                keys(v,'command decision_reading' if body.contract==RESERVATION else 'command run reading_ns point' if body.contract==DISPATCH else 'command run reading_ns','confirmation')
                if command_from_json(canonical(v['command']))!=cmd: raise ActionModelFalsified(reason='event_contradiction',detail='confirmation command differs')
                if body.contract==RESERVATION:
                    if v['decision_reading']!=rd: raise ActionModelFalsified(reason='event_contradiction',detail='reservation reading differs')
                elif v['run']!=str(cmd.run) or type(v['reading_ns']) is not int: raise ActionModelFalsified(reason='clock_contradiction',detail='confirmation clock differs')
                if body.contract==DISPATCH:
                    keys(v['point'],'name version','point')
                physical=(body.caused_by,body.contract)
                if physical in confirmed:
                    if confirmed[physical]!=v: raise ActionModelFalsified(reason='event_contradiction',detail='second confirmation differs')
                    continue
                confirmed[physical]=v
                kind='dispatch' if body.contract==DISPATCH else 'receipt' if body.contract==RECEIPT else 'reservation'
                law=d['execution']['confirmations'][kind]
                if law is None: raise ActionModelFalsified(reason='event_contradiction',detail='confirmation is unobserved in this experiment')
                rows=[]
                for p in paths:
                    event=next(e for e in p.events if e.command==cmd)
                    t=event.dispatch_ns if kind=='dispatch' else event.receipt_ns if kind=='receipt' else event.decision_ns
                    event_reading=rd['reading_ns'] if kind=='reservation' else v['reading_ns']
                    if t is None or clock_read(_clock(d,p.hypotheses[1]),t,p.clock_origin_ns)!=event_reading: continue
                    for delay,weight in delays(model,p,law):
                        if delay is None: continue
                        arrival=t+delay
                        if clock_read(_clock(d,p.hypotheses[1]),arrival,p.clock_origin_ns)==body.received_ns:
                            conditioned=replace(p,probability=p.probability*weight,node_ns=arrival)
                            key=(arrival,cmd.causal_stage,cmd.causal_position,2)
                            rows.extend(advance(model,(conditioned,),key,budget) if key>=p.knots[-1].key else (conditioned,))
                paths,mass=normalize(rows); evidence*=mass
    check(context.check_events)
    # now is propagation, not an additional nonarrival observation.
    if all(_clock(d,p.hypotheses[1])['kind']=='exact' for p in paths):
        stage=max((e.command.causal_stage for p in paths for e in p.events),default=-1)+1
        paths=checkpoint(model,paths,context.now_ns,stage,budget)
        if node_origin is None:
            reference_paths=checkpoint(model,reference_paths,context.now_ns,stage,budget)
    return make(model,context,paths,reports,observations,'complete' if reports else 'prior',evidence,
        origins=origins,node_origin=node_origin,reference_paths=reference_paths)


def apply(model,path,event,budget):
    """One B trial, then one work draw; no trial for unsent commands."""
    d=load_canonical(model.declaration); effect=d['effects'][event.command.action]
    if event.dispatch_ns is None: return (replace(path,events=path.events+(event,)),)
    t=event.dispatch_ns; key=(t,event.command.causal_stage,event.command.causal_position,0)
    if any(rational(c['at_s'],'calendar')*NS==t and effect['mode_on_dispatch'][c['mode']]!=c['mode'] for c in d['activity']['calendar']):
        raise ActionSpecificationMissing(reason='causal_order',detail='simultaneous calendar and dispatch mode changes do not commute')
    rows=advance(model,(path,),key,budget); result=[]; product=measure(model)
    for p in rows:
        pre=p.knots[-1]
        responding=effect['family']['name']=='response-wait'
        if responding and pre.response is not None:
            raise ActionIncomplete(reason='continuous_branches',detail='multiple simultaneous response waits need a larger auxiliary generator')
        for post in range(len(model.states)):
            mass,counts=(F(int(post==pre.state)),p.counts) if responding else product.observe('B',event.command.action,pre.state,post,p.counts)
            if not mass: continue
            mode=effect['mode_on_dispatch'][pre.mode]
            q=replace(p,probability=p.probability*mass,counts=counts,knots=p.knots+(Knot((*key[:3],1),post,mode,event.command.action if responding else pre.response),))
            # A later impulse can change a running job's speed. Recompute its
            # first passage from the SAME work draw and the full accumulated
            # progress, never from W at zero or from the original speed.
            old_events=[]
            unit={'ns':F(1),'s':F(NS)}[d['completion']['time_unit']]
            for old in q.events:
                if old.dispatch_ns is None or old.work is None or (old.completion_ns is not None and old.completion_ns<=t):
                    old_events.append(old); continue
                rates=[rational(x,'speed') for x in d['completion']['candidates'][q.hypotheses[0]][model.actions.index(old.command.action)]]
                if len(set(rates))==1:
                    old_events.append(old); continue
                knots=[k for k in q.knots if old.dispatch_ns<=k.key[0]<=t]
                if any(any(x for row in d['activity']['Q_by_mode'][k.mode] for x in row) for k in knots) or any(x for row in d['activity']['Q_by_mode'][mode] for x in row):
                    raise ActionIncomplete(reason='continuous_timing',detail='running progress depends on unobserved continuous jumps')
                consumed=sum(((right.key[0]-left.key[0])*rates[left.state]/unit for left,right in zip(knots,knots[1:])),F(0))
                remaining=old.work-consumed
                if remaining<0: raise ActionNumericalRange(reason='invalid_interval',detail='progress crossed completion before its declared event')
                end=None if not rates[post] else t+remaining*unit/rates[post]
                old_events.append(replace(old,completion_ns=end))
            q=replace(q,events=tuple(old_events))
            speed=rational(d['completion']['candidates'][q.hypotheses[0]][model.actions.index(event.command.action)][post],'speed')
            for work,pw in d['work'][event.command.action]['points']:
                pw=rational(pw,'work')
                if not pw: continue
                end=None if work is None or not speed else t+F(work)*unit/speed
                if end is not None and any(x for row in d['activity']['Q_by_mode'][mode] for x in row):
                    speeds=d['completion']['candidates'][q.hypotheses[0]][model.actions.index(event.command.action)]
                    if len(set(map(tuple,speeds)))>1:
                        raise ActionIncomplete(reason='continuous_timing',detail='CTMC-driven progress completion has continuous support')
                if end is not None and any(t<rational(c['at_s'],'calendar')*NS<end for c in d['activity']['calendar']):
                    speeds=d['completion']['candidates'][q.hypotheses[0]][model.actions.index(event.command.action)]
                    if len(set(map(tuple,speeds)))>1:
                        raise ActionIncomplete(reason='continuous_timing',detail='changing activity and state-dependent progress require the continuous ruler')
                e=replace(event,completion_ns=end,work=None if work is None else F(work))
                result.append(replace(q,probability=q.probability*pw,events=q.events+(e,)))
    return _guard(result,budget)


def label_for(data,path,target):
    if isinstance(target,FixedLabel): return target
    if target.attempt not in data.reports: raise ActionInputError(reason='shape',detail='unknown report target',field=target.attempt)
    position=data.reports[target.attempt]; command=position.command
    if isinstance(position,ReportPosition) and position.fixed:
        t=position.measurement_ns if target.position=='measurement' else position.completion_ns
        if t is not None: return FixedLabel(time_s=t/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side=target.side)
    event=next(e for e in path.events if e.command==command)
    effect=load_canonical(data.model.declaration)['effects'][command.action]
    t=event.dispatch_ns if target.position=='measurement' and effect['measure']['at']=='start' else event.completion_ns
    if t is None: raise ActionIncomplete(reason='latent_label_envelope',detail='unreported event has no state label')
    return FixedLabel(time_s=t/NS,causal_stage=command.causal_stage,causal_position=command.causal_position,side=target.side)


def insert(model,path,label,budget):
    key=(label.time_s*NS,label.causal_stage,label.causal_position,0 if label.side=='pre' else 1)
    if key>=path.knots[-1].key: return advance(model,(path,),key,budget)
    left=None; right=None; index=0
    for index,k in enumerate(path.knots):
        if k.key==key: return (path,)
        if k.key>key: right=k; break
        left=k
    if left is None: raise ActionInputError(reason='shape',detail='target precedes model origin')
    a=world_matrix(model,left.mode,left.response,key[0]-left.key[0]); n=len(model.states)
    def bridge(index):
        response=left.response if index<n else None
        b=world_matrix(model,left.mode,response,right.key[0]-key[0])
        dest=right.state+(n if response is not None and right.response is None else 0)
        return F(0) if response is None and right.response is not None else b[dest][index%n]
    total=sum((a[index][left.state]*bridge(index) for index in range(len(a))),F(0))
    if not total: raise ActionNumericalRange(reason='invalid_interval',detail='Markov bridge has no support')
    rows=[]
    for candidate in range(len(a)):
        p=a[candidate][left.state]*bridge(candidate)/total
        if p: rows.append(replace(path,probability=path.probability*p,knots=path.knots[:index]+(Knot(key,candidate%n,left.mode,left.response if candidate<n else None),)+path.knots[index:]))
    return _guard(rows,budget)


def queried(data,targets,budget):
    rows=[]
    for path in data.paths:
        labels=tuple(label_for(data,path,t) for t in targets); paths=(path,)
        for label in sorted(set(labels),key=lambda l:(l.time_s,l.causal_stage,l.causal_position,l.side=='post')):
            paths=_guard([q for p in paths for q in insert(data.model,p,label,budget)],budget)
        for p in paths:
            states=tuple(data.model.states[state_at(p,label)] for label in labels)
            rows.append((p,states))
    if len(rows)>budget.node_budget: raise ActionIncomplete(reason='budget',detail='joint target support exceeds budget')
    return tuple(rows)


def state_at(path,label):
    key=(label.time_s*NS,label.causal_stage,label.causal_position,0 if label.side=='pre' else 1)
    return next(k.state for k in reversed(path.knots) if k.key<=key)


def marginal(belief,targets,budget):
    data=belief._data; cells={}
    for p,states in queried(data,targets,budget): cells[states]=cells.get(states,F(0))+p.probability
    if len(targets)==1:
        for s in data.model.states: cells.setdefault((s,),F(0))
    d=load_canonical(data.model.declaration)
    approximate=(any(x for q in d['activity']['Q_by_mode'].values() for row in q for x in row)
        or any(e['family']['name']=='response-wait' and any(e['response_rate_s']) for e in d['effects'].values()))
    return DiscreteMarginal(targets=tuple(targets),cells=tuple((row,replace(rational_bounds(p),exact=None) if approximate else rational_bounds(p)) for row,p in sorted(cells.items())))


def weights(belief,parameter,budget):
    d=load_canonical(belief._data.model.declaration)
    axes={'rho':(0,len(d['completion']['weights'])),'lambda':(1,len(d['clock']['candidates']) if d['clock']['kind']=='clock-process' else len(d['clock']['measure']['candidates'])),
        'chi':(2,0 if d['execution']['chi'] is None else len(d['execution']['chi']['candidates']))}
    if parameter not in axes: raise ActionInputError(reason='shape',detail='unknown hypothesis parameter')
    axis,n=axes[parameter]
    return tuple(rational_bounds(sum((p.probability for p in belief._data.paths if p.hypotheses[axis]==i),F(0))) for i in range(n))


def decision_reading(data,budget):
    d=load_canonical(data.model.declaration); readings=set()
    for p in data.paths:
        law=d['execution']['think']
        options=((F(0),F(1)),) if law is None else delays(data.model,p,law)
        for dt,mass in options:
            if dt is None: raise ActionIncomplete(reason='algorithm_unavailable',detail='decision can remain unfinished')
            readings.add(clock_read(_clock(d,p.hypotheses[1]),p.node_ns+dt,p.clock_origin_ns))
    if len(readings)!=1:
        raise ActionIncomplete(reason='algorithm_unavailable',detail='policy before multiple decision readings requires decision-observation branches')
    return F(next(iter(readings)))


def one_step_deadline(data,command,budget):
    ends=[]
    for p,e in dispatch_paths(data.model,data.paths,command,budget):
        for q in apply(data.model,p,e,budget):
            end=q.events[-1].completion_ns
            if end is None: raise ActionOutsideEvaluationType(reason='one_step_nonreturn',detail='one-step action may never complete')
            if end.denominator!=1: raise ActionIncomplete(reason='continuous_timing',detail='one-step horizon has no integer physical boundary')
            ends.append(int(end)+q.clock_origin_ns)
    return max(ends)


def terminal_cost(node,resolved,root_time):
    from .preference import cost,EvaluationInput
    values=[]; data=node.belief._data
    for path in data.paths:
        actions=[]; outcomes=[]
        for index,command in enumerate(node.controls):
            event=next(e for e in path.events if e.command==command)
            if event.dispatch_ns is not None:
                if event.dispatch_ns.denominator!=1: raise ActionIncomplete(reason='continuous_timing',detail='preference action axis requires integer ns')
                actions.append((int(event.dispatch_ns)+path.clock_origin_ns-root_time,('new',index),command.action))
            for name,y,notice in data.observations:
                if data.reports[name].command!=command: continue
                if event.completion_ns.denominator!=1: raise ActionIncomplete(reason='continuous_timing',detail='preference outcome axis requires integer ns')
                outcomes.append((int(event.completion_ns)+path.clock_origin_ns-root_time,('new',index),command.action,y))
        value=cost(resolved,EvaluationInput(evaluation='one_step' if resolved.H_ns is None else 'lookahead',O=tuple(outcomes),A=tuple(actions),candidate_outcome=outcomes[-1][3] if outcomes else None))
        if value==math.inf: return math.inf
        values.append(rational_bounds(path.probability).lower*value)
    result=math.fsum(values)
    if not math.isfinite(result): raise ActionNumericalRange(reason='overflow',detail='finite preference expectation exceeds range')
    return result


def target_labels(data,target):
    if isinstance(target,FixedLabel): return (target,)
    if target.attempt not in data.reports:
        raise ActionInputError(reason='shape',detail='unknown report target',field=target.attempt)
    position=data.reports[target.attempt]
    times=position.measurement_labels if target.position=='measurement' else position.completion_labels
    if not times:
        times=tuple(sorted({label_for(data,p,target).time_s*NS for p in data.paths}))
    return tuple(FixedLabel(time_s=t/NS,causal_stage=position.command.causal_stage,
        causal_position=position.command.causal_position,side=target.side) for t in times)


def identical_variable(data,labels,budget):
    """Certify equality of fixed-label variables on every supported world.

    Querying their joint distribution includes bridges and the *used* modes.
    A nonzero Q in an unrelated mode therefore cannot reject this proof.
    """
    if len(labels)<2: return
    if any(len(set(states))>1 for path,states in queried(data,labels,budget) if path.probability):
        raise ActionIncomplete(reason='latent_label_envelope',detail='fixed label candidates do not identify the same state variable; general g_mon is required')


def origin_paths(model,paths,origin,current,budget):
    """Replay a node's trigger under the root law, without trigger evidence."""
    if origin is None or not origin.attempts:
        return tuple(replace(p,node_ns=p.reference_ns) for p in paths)
    commands=[]
    for attempt in origin.attempts:
        event=next((e for e in current.belief._data.events if e.report==attempt),None)
        if event is None:
            position=current.belief._data.reports.get(attempt)
            if position is None:
                position=next((v for v in current.belief._data.reports.values() if v.attempt==attempt),None)
            if position is None: raise ActionInputError(reason='shape',detail='unknown node origin attempt',field=attempt)
            commands.append(position.command)
        else: commands.append(event.command)
    return trigger_paths(model,paths,commands,budget)


def trigger_paths(model,paths,commands,budget):
    """Restore completion-trigger times in each unconditioned world."""
    rows=[]
    for p in paths:
        events=[next((e for e in p.events if e.command==c),None) for c in commands]
        if any(e is None for e in events):
            raise ActionInputError(reason='shape',detail='node origin is not in the root or preceding controls')
        if any(e.completion_ns is None for e in events):
            rows.append(replace(p,node_ns=None))
            continue
        event=max(events,key=lambda e:(e.completion_ns,e.command.causal_stage,e.command.causal_position))
        label=FixedLabel(time_s=event.completion_ns/NS,causal_stage=event.command.causal_stage,
            causal_position=event.command.causal_position,side='post')
        rows.extend(replace(q,node_ns=event.completion_ns) for q in insert(model,p,label,budget))
    return _guard(rows,budget)


def reference(root,current,targets,certificate,budget):
    from .action_reference import report_name
    controls=current.controls; data=root._data
    paths=tuple(replace(p,reference_ns=p.node_ns) for p in data.paths); reports=dict(data.reports)
    adopted={data.reports[name].attempt for name,_,_ in data.observations}
    for command,origin in zip(controls,current.origins):
        if command.run!=root.context.run: raise ActionOutsideEvaluationType(reason='restart_delivery_law',detail='reference command crosses runs')
        if origin is not None and set(origin.attempts)<=adopted: origin=None
        paths=origin_paths(data.model,paths,origin,current,budget); rows=[]
        for p,e in dispatch_paths(data.model,paths,command,budget): rows.extend(apply(data.model,p,replace(e,report=report_name(command)),budget))
        paths=_guard(rows,budget)
    belief=make(data.model,root.context,paths,reports,data.observations,root.status,data.evidence)
    for target in targets:
        if not isinstance(target,TargetRef): continue
        position=current.belief._data.reports.get(target.attempt)
        if position is None: raise ActionInputError(reason='shape',detail='unknown current report target',field=target.attempt)
        if not any(e.command==position.command for e in belief._data.events):
            raise ActionInputError(reason='shape',detail='target attempt is not in the root or controls')
        labels=target_labels(current.belief._data,target)
        identical_variable(current.belief._data,labels,budget)
        identical_variable(belief._data,labels,budget)
        # Resolve against labels frozen in the actual experiment, never against
        # the reference world's own completion. Singleton label positions (and
        # certified equal candidates) have an ordinary fixed-label marginal.
        frozen=reports.get(target.attempt,position)
        time=labels[0].time_s*NS
        reports[target.attempt]=replace(frozen,fixed=True,
            **({'measurement_ns':time} if target.position=='measurement' else {'completion_ns':time}))
    belief=make(data.model,root.context,paths,reports,data.observations,root.status,data.evidence)
    return ReferenceMarginal(root_key=root.evidence_key,controls=controls,targets=targets,certificate=certificate,_data=belief)


def information(root,current,certificate,budget):
    ref=reference(root,current,current.targets,certificate,budget)
    if measure(root._data.model).beta:
        from .action_learning import joint_information
        return joint_information(root,current.belief,ref._data,current.targets,budget)
    def cells(data):
        result={}
        for p,row in queried(data,current.targets,budget):
            key=(p.hypotheses,row); result[key]=result.get(key,F(0))+p.probability
        return result
    b=cells(current.belief._data); r=cells(ref._data._data)
    if b==r: return rational_bounds(F(0))
    terms=[]
    for row,p in b.items():
        if not p: continue
        q=r.get(row,F(0))
        if not q: raise ActionNumericalRange(reason='invalid_interval',detail='posterior outside reference support')
        ratio=p/q; terms.append(rational_bounds(p).lower*(math.log(ratio.numerator)-math.log(ratio.denominator)))
    value=math.fsum(terms)
    if not math.isfinite(value): raise ActionNumericalRange(reason='overflow',detail='finite joint information exceeds range')
    return Bounds(value,value,None)


def branches(node,command,deadline,certificate,budget):
    from .action_reference import report_name
    from .records import Record,Observed,Payload,Role,Producer
    from .clock import Instant
    from .ids import derive,RefKind
    from .dispatch import parse_ref
    from .s4b_action_contracts import REPORT,RESERVATION,RECEIPT,DISPATCH
    if node.terminal: raise ActionInputError(reason='schema',detail='terminal node has no branches')
    if command.run!=node.belief.context.run: raise ActionOutsideEvaluationType(reason='restart_delivery_law',detail='command crosses runs')
    from .action_joint import validate_command
    validate_command(node.belief._data.model,command)
    data=node.belief._data; d=load_canonical(data.model.declaration)
    deadline-=data.paths[0].clock_origin_ns
    if any((e.command.causal_stage,e.command.causal_position)==(command.causal_stage,command.causal_position) for e in data.events):
        raise ActionInputError(reason='shape',detail='new command must have a unique causal position')
    attempt=derive(RefKind.ATTEMPT,'s4b.action.predicted_attempt',command_json(command).decode())
    predicted=[]
    dispatched=dispatch_paths(data.model,data.paths,command,budget)
    labels=[label for target in node.targets for label in target_labels(data,target)]
    if labels:
        latest=max((l.time_s*NS,l.causal_stage,l.causal_position,l.side=='post') for l in labels)
        if any(e.dispatch_ns is not None and (*e.key,1)<=latest for p,e in dispatched):
            raise ActionIncomplete(reason='noninterference_unproved',detail='new impulse support is not after all old label candidates')
    # The posterior may exclude the early-trigger worlds which the root law
    # still supports. Prove ordering on the broader, evidence-free law too.
    reference_paths=data.reference_paths
    if reference_paths is None:
        if node.controls or data.events:
            raise ActionIncomplete(reason='noninterference_unproved',detail='root-reference support is unavailable')
        reference_paths=data.paths
    reference_paths=tuple(replace(p,reference_ns=p.node_ns) for p in reference_paths)
    reference_paths=origin_paths(data.model,reference_paths,node._next_origin(),node,budget)
    reference_dispatched=dispatch_paths(data.model,reference_paths,command,budget)
    if labels and any(e.dispatch_ns is not None and (*e.key,1)<=latest for p,e in reference_dispatched):
        raise ActionIncomplete(reason='noninterference_unproved',detail='root-reference impulse support is not after all old label candidates')
    reference_paths=_guard([q for p,e in reference_dispatched for q in
        apply(data.model,p,replace(e,report=str(attempt)),budget)],budget)
    for p,e in dispatched: predicted.extend(apply(data.model,p,replace(e,report=str(attempt)),budget))
    def notifications(path,event,cutoff):
        rows=[(path,())]
        for kind,time in (('reservation',event.decision_ns),('receipt',event.receipt_ns),('dispatch',event.dispatch_ns)):
            law=d['execution']['confirmations'][kind]
            if law is None or time is None: continue
            next_rows=[]
            for p,visible in rows:
                clock=_clock(d,p.hypotheses[1]); reading=clock_read(clock,time,p.clock_origin_ns)
                payload={'command':load_canonical(command_json(command))}
                if kind=='reservation': payload['decision_reading']={'run':str(command.run),'reading_ns':reading,'work':'prediction','parents':[]}
                else:
                    payload.update(run=str(command.run),reading_ns=reading)
                    if kind=='dispatch': payload['point']={'name':'sui.action.predicted-dispatch','version':'1'}
                for delay,weight in delays(data.model,p,law):
                    shown=visible
                    if delay is not None and time+delay<=cutoff:
                        shown+=((time+delay,kind,payload,clock_read(clock,time+delay,p.clock_origin_ns)),)
                    next_rows.append((replace(p,probability=p.probability*weight),shown))
            if len(next_rows)>budget.node_budget: raise ActionIncomplete(reason='budget',detail='confirmation support exceeds budget')
            rows=next_rows
        return rows

    adopted={(data.reports[name].command.causal_stage,data.reports[name].command.causal_position) for name,_,_ in data.observations}
    groups={}
    for path in predicted:
        event=path.events[-1]
        pending=[e for e in path.events if (e.command.causal_stage,e.command.causal_position) not in adopted
            and e.completion_ns is not None and e.completion_ns<=deadline]
        cutoff=min((e.completion_ns for e in pending),default=F(deadline))
        completing=sorted((e for e in pending if e.completion_ns==cutoff),key=lambda e:(e.command.causal_stage,e.command.causal_position))
        for p,notices in notifications(path,event,cutoff):
            alternatives=[((),(p,))]
            # All jobs participate in the same next-report race. Reports at
            # the same true time are adopted together before another choice.
            for completed in completing:
                next_alternatives=[]; effect=d['effects'][completed.command.action]
                clock=_clock(d,p.hypotheses[1]); t=completed.dispatch_ns if effect['measure']['at']=='start' else completed.completion_ns
                for bundles,rows in alternatives:
                    for outcome in data.model.outcomes:
                        for notice in (None,) if effect['notice'] is None else effect['notice']['labels']:
                            bundle={'outcome':outcome,'effect_notice':notice,'measurement_reading_ns':clock_read(clock,t,p.clock_origin_ns),'completion_reading_ns':clock_read(clock,completed.completion_ns,p.clock_origin_ns)}
                            conditioned=observe_report(data.model,rows,completed.command,bundle,budget)
                            if conditioned: next_alternatives.append((bundles+((command_json(completed.command).decode(),completed.report,bundle),),conditioned))
                alternatives=next_alternatives
                if sum(len(rows) for _,rows in alternatives)>budget.node_budget:
                    raise ActionIncomplete(reason='budget',detail='simultaneous report support exceeds budget')
            for bundles,rows in alternatives:
                if not rows: continue
                shown=[(time,kind,payload,received,str(attempt),command_json(command).decode()) for time,kind,payload,received in notices]
                for encoded_command,owner,bundle in bundles:
                    shown.append((cutoff,'report',bundle,bundle['completion_reading_ns'],owner,encoded_command))
                shown.sort(key=lambda n:(n[0],('reservation','receipt','dispatch','report').index(n[1])))
                # The observed bundle, including transported event readings and
                # separate notification arrivals, groups hidden world paths.
                visible=tuple((kind,payload,received,owner,encoded_command) for _,kind,payload,received,owner,encoded_command in shown)
                key=canonical({'visible':visible,'reports':bundles})
                groups.setdefault(key,[]).extend(rows)
    atoms=[]
    for encoded,paths in groups.items():
        paths,mass=normalize(paths); reports=dict(data.reports); records=(); targets=node.targets; observations=data.observations
        group=load_canonical(encoded); bundles=group['reports']; node_origin=data.node_origin; trigger=node.trigger
        if not bundles:
            now=deadline+data.paths[0].clock_origin_ns; terminal=True
        else:
            from .dispatch import command_from_json
            for encoded_command,owner,bundle in bundles:
                completed_command=command_from_json(encoded_command.encode())
                name=report_name(completed_command,bundle); effect=d['effects'][completed_command.action]
                reports[name]=report_position(data.model,paths,completed_command,owner)
                reports[owner]=reports[name]
                observations+=((name,bundle['outcome'],bundle['effect_notice']),)
                stable=planned_attempt(completed_command) if completed_command in node.controls+(command,) else owner
                reports[stable]=reports[name]
                targets+=(TargetRef(attempt=stable,position='measurement',side=effect['measure']['side']),TargetRef(attempt=stable,position='completion',side='post'))
            trigger=targets[-1]
            node_origin=NodeOrigin(attempts=tuple(t.attempt for t in targets[-2*len(bundles):] if t.position=='completion'))
            now=bundles[-1][2]['completion_reading_ns']; terminal=all(p.node_ns>=deadline for p in paths)
        observed_records=[]
        contracts={'report':REPORT,'reservation':RESERVATION,'receipt':RECEIPT,'dispatch':DISPATCH}
        for index,(kind,payload,received,owner,encoded_command) in enumerate(group['visible']):
            from .dispatch import command_from_json
            source_command=command_from_json(encoded_command.encode())
            ref=(parse_ref(report_name(source_command,payload),'report',RefKind.OBSERVATION) if kind=='report' else
                derive(RefKind.OBSERVATION,'s4b.action.predicted_confirmation',canonical([command_json(command).decode(),kind,payload,received]).decode()))
            observed_records.append(Record(id=ref,at=Instant(run=command.run,run_index=0,seq=index+1,mono_ns=received,wall_ns=received),writer=Role.MEMBRANE,
                producer=Producer(component='sui.action_prediction',code_version='1'),body=Observed(route=source_command.action,contract=contracts[kind],received_ns=received,caused_by=parse_ref(owner,'attempt',RefKind.ATTEMPT),content=Payload.json(payload))))
        records=tuple(observed_records)
        context=replace(node.belief.context,now_ns=now,observed_ns=now)
        origins={**data.origins,(command.causal_stage,command.causal_position):node._next_origin()}
        belief=make(data.model,context,paths,reports,observations,'complete',data.evidence*mass,
            origins=origins,node_origin=node_origin,reference_paths=reference_paths)
        child=ActionNode(belief=belief,controls=node.controls+(command,),targets=targets,terminal=terminal,
            trigger=trigger)
        atoms.append(BranchAtom(probability=rational_bounds(mass),records=records,child=child))
    total=sum((a.probability.exact for a in atoms),F(0))
    if total!=1: raise ActionNumericalRange(reason='invalid_interval',detail='finite branch mass is not one')
    return BranchMeasure(atoms=tuple(atoms),total_mass=rational_bounds(total),certificate=certificate)
