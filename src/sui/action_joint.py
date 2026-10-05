"""Exact finite paths with conditional products of column Dirichlet laws."""
from dataclasses import dataclass, replace, fields
from fractions import Fraction as F
from types import MappingProxyType
import hashlib
import math

from .action_types import *
from .action_model import ActionModel, load_canonical, rational, canonical, keys
from .dispatch import command_from_json, command_json, build_command, parse_ref
from .values import _thaw
from .records import Observed, AttemptStarted, JobOpened, Preference, Category
from .s4b_action_contracts import JOB, ATTEMPT, RESERVATION, RECEIPT, DISPATCH, REPORT
from .clock_contracts import SOURCE, check_clock_sources
from .ids import RefKind
from .action_learning import measure
from .agent import Reading


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class _ActionReading(Reading):
    """Value equality for model.8's immutable numpy count tables."""
    def __eq__(self, other):
        import numpy as np
        if not isinstance(other, _ActionReading):
            return NotImplemented
        return (self.n.keys() == other.n.keys()
            and all(np.array_equal(self.n[a], other.n[a]) for a in self.n)
            and all(getattr(self, f.name) == getattr(other, f.name)
                    for f in fields(Reading) if f.name != 'n'))


@dataclass(frozen=True, slots=True)
class _Event:
    command: Command
    dispatch_ns: F
    completion_ns: F
    report: str
    decision_ns: F | None = None
    receipt_ns: F | None = None
    work: F | None = None

    @property
    def key(self):
        return self.dispatch_ns,self.command.causal_stage,self.command.causal_position


@dataclass(frozen=True, slots=True)
class _Path:
    probability: F
    initial: int
    posts: tuple[int,...]
    counts: tuple[int,...]


@dataclass(frozen=True, slots=True)
class _Data:
    model: ActionModel
    events: tuple[_Event,...]
    paths: tuple[_Path,...]
    reports: object
    observations: tuple
    evidence: F
    origins: object
    node_origin: NodeOrigin | None


def _log(value):
    if value <= 0:
        raise ActionModelFalsified(reason="zero_evidence",detail="evidence has zero mass")
    return math.log(value.numerator)-math.log(value.denominator)


def _make(model,context,events,paths,reports,observations,status,log_evidence=0.,evidence=F(1),*,origins=None,node_origin=None):
    key=hashlib.sha256(canonical({"model":model.ref,"events":[{"command":command_json(e.command).decode(),
        "dispatch":[e.dispatch_ns.numerator,e.dispatch_ns.denominator],
        "completion":[e.completion_ns.numerator,e.completion_ns.denominator],"report":e.report} for e in events],
        "paths":[[p.initial,p.posts,p.counts,[p.probability.numerator,p.probability.denominator]] for p in paths],
        "observations":list(observations),"now":context.now_ns,"observed":context.observed_ns,
        "checks":_thaw(context.check_events),"source":None if context.clock_source is None else str(context.clock_source),
        "run":str(context.run)})).hexdigest()
    data=_Data(model,tuple(events),tuple(paths),MappingProxyType(dict(reports)),tuple(observations),evidence,
        MappingProxyType(dict(origins or {})),node_origin)
    return ActionBelief(model_ref=model.ref,context=context,evidence_key=key,status=status,
        log_evidence=Bounds(log_evidence,log_evidence,None),evidence_kind="mass",_data=data)


def read_jobs(model, records):
    from .action_persistence import intent
    jobs = {}
    for record in records:
        if isinstance(record.body, JobOpened) and record.body.contract == JOB:
            jobs[record.id] = intent(model, record.body.content.as_json())['action']
    return jobs


def read_action(model,records,*,unread_preferences=()):
    from .agent import Reading
    from .timeline import _facts,timeline,TimelineError
    import numpy as np
    records=tuple(r for r in _facts(records) if r.category in (Category.FACT,Category.INTENTION,Category.PREFERENCE))
    # A clock declaration records provenance, not a report/nonarrival checkpoint.
    axis=None; issues=()
    try: axis=timeline(tuple(r for r in records if not (isinstance(r.body,Observed) and r.body.contract==SOURCE)),unread_preferences=unread_preferences)
    except TimelineError as exc: issues=exc.clock_issues
    jobs=read_jobs(model,records)
    attempts={r.id:r.body.job for r in records if isinstance(r.body,AttemptStarted) and r.body.contract==ATTEMPT}
    done={r.body.caused_by for r in records if isinstance(r.body,Observed) and r.body.contract==REPORT}
    pending={job:action for job,action in jobs.items() if not any(at in done and j==job for at,j in attempts.items())}
    counts={a:np.zeros(len(model.outcomes),dtype=np.int64) for a in model.actions}
    seen=set()
    for r in records:
        if isinstance(r.body,Observed) and r.body.contract==REPORT and r.body.caused_by in attempts:
            tag=r.body.caused_by
            if tag in seen: continue
            seen.add(tag); a=jobs.get(attempts[r.body.caused_by]); y=r.body.content.as_json().get("outcome")
            if a is not None and y in model.outcomes: counts[a][model.outcomes.index(y)]+=1
    return _ActionReading(n=counts,unread={},pending=pending,timeline=axis,_clock_issues=issues,
        preferences=tuple(r for r in records if isinstance(r.body,Preference)),
        unread_preferences=tuple(unread_preferences),_action_records=records)


def fact_ancestors(ledger, frontier, reading):
    """Resolve only the frozen frontier; clock metadata is not a check event."""
    allowed={r.id for r in reading._action_records if not (
        isinstance(r.body,Observed) and r.body.contract==SOURCE)}
    result={}; pending=[(cid,False) for cid in sorted(frontier)]
    while pending:
        cid,ready=pending.pop()
        if cid in result: continue
        entry=ledger.entry(cid)
        if not ready:
            pending.append((cid,True))
            pending.extend((p,False) for p in sorted(entry.parents) if p not in result)
            continue
        refs=frozenset().union(*(result[p] for p in entry.parents))
        if entry.id in allowed: refs|={str(entry.id)}
        result[cid]=refs
    return MappingProxyType(result)


def fixed_duration(model,action):
    d=load_canonical(model.declaration); w=d["work"][action]
    if w["kind"]!="known":
        raise ActionIncomplete(reason="algorithm_unavailable",detail="work learning belongs to stage 1b")
    points=[(p,m) for p,m in w["points"] if rational(m,"work")]
    if len(points)!=1 or points[0][0] is None:
        raise ActionIncomplete(reason="algorithm_unavailable",detail="positive fixed work required")
    work=points[0][0]
    if work==0:
        raise ActionOutsideEvaluationType(reason="certain_zero_repetition",detail="certain zero work is outside finite-depth lookahead")
    c=d["completion"]; ai=model.actions.index(action)
    speeds={rational(x,"speed") for candidate in c["candidates"] for x in candidate[ai]}
    if len(speeds)!=1 or next(iter(speeds))<=0:
        raise ActionIncomplete(reason="algorithm_unavailable",detail="state-independent known positive speed required")
    unit={"ns":F(1),"s":F(1000000000)}.get(c["time_unit"])
    if unit is None: raise ActionIncomplete(reason="algorithm_unavailable",detail="time unit has no declared ns conversion")
    return F(work)*unit/next(iter(speeds))


def deterministic_delay(law,field):
    values=set()
    for row in law["rows"]:
        for value,p in row["points"]:
            if not rational(p,field): continue
            if value=="+inf": raise ActionIncomplete(reason="algorithm_unavailable",detail="finite deterministic delay required",field=field)
            values.add(rational(value,field)*1000000000)
    if len(values)!=1: raise ActionIncomplete(reason="algorithm_unavailable",detail="dispatch time is not a point mass",field=field)
    return next(iter(values))


def decision_time(model,now):
    d=load_canonical(model.declaration)
    return F(now)+(F(0) if d["execution"]["family"]["name"]=="immediate-start" else deterministic_delay(d["execution"]["think"],"think"))


def validate_command(model,command):
    d=load_canonical(model.declaration); ex=d["execution"]
    command_json(command)
    if command.choice not in d["choices"] or command.action!=d["choices"][command.choice]["action"]:
        raise ActionInputError(reason="unknown_candidate",detail="command choice/action differs from declaration")
    if _thaw(command.reservation_rule)!=d["choices"][command.choice]["reservation"]:
        raise ActionModelFalsified(reason="event_contradiction",detail="command reservation differs from chosen rule")
    if command.dispatch!=ContractRef(**ex["family"]) or command.effect!=ContractRef(**d["effects"][command.action]["family"]):
        raise ActionModelFalsified(reason="event_contradiction",detail="command family differs from model")
    return d


def event_for(model,command,now,report):
    d=validate_command(model,command); ex=d['execution']
    if command.dispatch.name=="immediate-start": dispatch=F(now)
    else:
        receipt=decision_time(model,now)+deterministic_delay(ex["receipt"],"receipt")
        delays={deterministic_delay(p["delay"],"chi") for p in ex["chi"]["candidates"]}
        if len(delays)!=1: raise ActionIncomplete(reason="algorithm_unavailable",detail="chi does not certify point dispatch")
        dispatch=max(F(command.not_before_ns),receipt)+next(iter(delays))
    return _Event(command,dispatch,dispatch+fixed_duration(model,command.action),report)


def _label(event,position,side,model):
    m=load_canonical(model.declaration)["effects"][event.command.action]["measure"]
    time=event.dispatch_ns if position=="measurement" and m["at"]=="start" else event.completion_ns
    return FixedLabel(time_s=time/1000000000,causal_stage=event.command.causal_stage,
        causal_position=event.command.causal_position,side=side)


def _resolve(data,target):
    if isinstance(target,FixedLabel): return target
    if not isinstance(target,TargetRef): raise ActionInputError(reason="schema",detail="unknown target type")
    if target.attempt not in data.reports:
        raise ActionInputError(reason="shape",detail="unknown report target",field=target.attempt)
    return _label(data.reports[target.attempt],target.position,target.side,data.model)


def _state_at(path,events,label):
    key=(label.time_s*1000000000,label.causal_stage,label.causal_position,0 if label.side=="pre" else 1)
    state=path.initial
    for i,event in enumerate(events):
        if (*event.key,1)<=key: state=path.posts[i]
        else: break
    return state


def _extend(model,events,paths,event,budget):
    if events and event.key<=events[-1].key:
        raise ActionSpecificationMissing(reason="causal_order",detail="dispatch order must be explicit and increasing")
    product=measure(model)
    rows=[]
    for path in paths:
        pre=path.posts[-1] if path.posts else path.initial
        for post in range(len(model.states)):
            p,counts=product.observe("B",event.command.action,pre,post,path.counts)
            if p: rows.append(_Path(path.probability*p,path.initial,path.posts+(post,),counts))
    if len(rows)>budget.node_budget: raise ActionIncomplete(reason="budget",detail="path enumeration exceeds node budget")
    return tuple(rows)


def _notice_probability(model,event,path,events,notice):
    if notice is None: return F(1)
    e=load_canonical(model.declaration)["effects"][event.command.action]
    if e["notice"] is None or notice not in e["notice"]["labels"]:
        raise ActionModelFalsified(reason="event_contradiction",detail="unmodeled effect notice")
    i=events.index(event); pre=path.initial if i==0 else path.posts[i-1]; post=path.posts[i]
    y=e["notice"]["labels"].index(notice)
    return sum((rational(e["marks"]["probability"][k][post][pre],"marks")*
        rational(e["notice"]["probability"][y][k][post][pre],"notice") for k in range(len(e["marks"]["labels"]))),F(0))


def _observation(model,event,path,events,outcome,notice):
    probability=_notice_probability(model,event,path,events,notice)
    counts=path.counts
    if outcome is not None:
        if outcome not in model.outcomes: raise ActionModelFalsified(reason="event_contradiction",detail="unknown outcome")
        d=load_canonical(model.declaration); m=d["effects"][event.command.action]["measure"]
        state=_state_at(path,events,_label(event,"measurement",m["side"],model))
        factor,counts=measure(model).observe("Theta",event.command.action,state,model.outcomes.index(outcome),counts)
        probability*=factor
    return probability,counts


def observation_probability(model,event,path,events,outcome,notice):
    return _observation(model,event,path,events,outcome,notice)[0]


def _condition(model,events,paths,observations):
    result=[]
    for path in paths:
        p=path.probability
        counts=path.counts
        for event,outcome,notice in observations:
            probability,counts=_observation(model,event,replace(path,counts=counts),events,outcome,notice)
            p*=probability
        if p: result.append(replace(path,probability=p,counts=counts))
    mass=sum((p.probability for p in result),F(0))
    if not mass: raise ActionModelFalsified(reason="zero_evidence",detail="no path explains adopted observations")
    return tuple(replace(p,probability=p.probability/mass) for p in result),mass


def validate_context(model,reading,context,budget):
    records=reading._action_records
    if len(records)>budget.node_budget:
        raise ActionIncomplete(reason="budget",detail="fact reconstruction exceeds node budget")
    sources=check_clock_sources(records)
    if context.clock_source is not None and (context.run not in sources or sources[context.run][1]!=context.clock_source):
        raise ActionInputError(reason="schema",detail="clock source does not belong to frozen facts")
    if reading._clock_issues: raise ActionModelFalsified(reason="clock_contradiction",detail="timeline cannot explain facts")
    if reading.timeline is not None and context.run not in reading.timeline.runs:
        raise ActionInputError(reason="schema",detail="context run has no adopted BOOT")
    if context.observed_ns>context.now_ns: raise ActionInputError(reason="schema",detail="observed_ns exceeds now_ns")
    byid={str(r.id):r for r in records}
    for source in context.check_events:
        if set(source)=={"fact"}:
            r=byid.get(source["fact"])
            if r is None or not isinstance(r.body,Observed) or r.body.received_ns!=context.observed_ns or r.at.run!=context.run or r.body.contract==SOURCE:
                raise ActionInputError(reason="schema",detail="check fact is not a receipt at observed_ns")
        elif set(source)=={"unrecorded"}:
            v=source["unrecorded"]
            if set(v)!={"kind","reading","after"} or v["kind"] not in ("tick","thought") or type(v["reading"]) is not int or v["reading"]!=context.observed_ns or not isinstance(v["after"],tuple) or any(type(k) is not str or k not in context.fact_ancestors for k in v["after"]) or list(v["after"])!=sorted(set(v["after"])):
                raise ActionInputError(reason="schema",detail="invalid unrecorded check provenance")
        else: raise ActionInputError(reason="schema",detail="unknown check source shape")
    return records


def rebuild(model,reading,*,context,budget):
    from .action_entry import _model_support
    response=any(e['family']['name']=='response-wait' for e in load_canonical(model.declaration)['effects'].values())
    if response:
        from .action_response import reconstruction_support
        require_certificate(reconstruction_support(model))
    else: require_certificate(_model_support(model))
    records=validate_context(model,reading,context,budget)
    from .action_finite import needed,boot_reading,rebuild as rebuild_finite
    if response or needed(model) or boot_reading(reading,context.run)!=0 or any(isinstance(r.body,AttemptStarted) and r.body.contract==ATTEMPT for r in records):
        return rebuild_finite(model,reading,context=context,budget=budget)
    d=load_canonical(model.declaration)
    paths=tuple(_Path(rational(p,"D"),i,(),measure(model).zero) for i,p in enumerate(d["D"]) if rational(p,"D"))
    attempts={}; confirmations={}; reports={}; commands={}; observed=[]; seen={}
    for r in records:
        b=r.body
        if isinstance(b,AttemptStarted) and b.contract==ATTEMPT:
            value=b.content.as_json(); keys(value,"command decision_reading","attempt")
            command=command_from_json(canonical(value["command"]))
            if command.run!=context.run:
                raise ActionOutsideEvaluationType(reason="restart_delivery_law",detail="action history crosses runs")
            decision=value["decision_reading"]; keys(decision,"run reading_ns work parents","decision_reading")
            if decision["run"]!=str(command.run): raise ActionModelFalsified(reason="event_contradiction",detail="decision run differs")
            bound=build_command(model=model,choice=command.choice,decision=DecisionReading(run=command.run,
                reading_ns=decision["reading_ns"],work=decision["work"],parents=frozenset(decision["parents"])),
                causal_stage=command.causal_stage,causal_position=command.causal_position)
            if bound!=command: raise ActionModelFalsified(reason="event_contradiction",detail="saved command differs from rule")
            attempts[r.id]=(r,command,decision); commands[r.id]=command
        elif isinstance(b,Observed) and b.contract in (RESERVATION,RECEIPT,DISPATCH,REPORT):
            observed.append(r)
    for r in observed:
        b=r.body; value=b.content.as_json()
        if b.caused_by not in attempts: raise ActionModelFalsified(reason="event_contradiction",detail="action observation has no adopted attempt")
        if b.source_id is not None:
            tag=(b.caused_by,b.contract,b.source_id)
            if tag in seen:
                if seen[tag]!=value: raise ActionModelFalsified(reason="event_contradiction",detail="same source confirmation differs")
                continue
            seen[tag]=value
        command=commands[b.caused_by]
        if b.contract==REPORT:
            keys(value,"outcome effect_notice measurement_reading_ns completion_reading_ns","report")
            if b.caused_by in reports:
                if reports[b.caused_by][1]!=value: raise ActionModelFalsified(reason="event_contradiction",detail="multiple differing completions")
                continue
            reports[b.caused_by]=(r,value)
        else:
            keys(value,"command decision_reading" if b.contract==RESERVATION else "command run reading_ns point" if b.contract==DISPATCH else "command run reading_ns","confirmation")
            if command_from_json(canonical(value["command"]))!=command:
                raise ActionModelFalsified(reason="event_contradiction",detail="confirmation command differs from secured attempt")
            if b.contract==RESERVATION:
                if value["decision_reading"]!=attempts[b.caused_by][2]: raise ActionModelFalsified(reason="event_contradiction",detail="reservation decision evidence differs")
            else:
                if value["run"]!=str(command.run) or type(value["reading_ns"]) is not int:
                    raise ActionModelFalsified(reason="clock_contradiction",detail="confirmation clock differs")
                if b.contract==RECEIPT:
                    ex=d["execution"]
                    expected_receipt=F(attempts[b.caused_by][2]["reading_ns"])+deterministic_delay(ex["receipt"],"receipt")
                    if value["reading_ns"]!=expected_receipt:
                        raise ActionModelFalsified(reason="clock_contradiction",detail="receipt reading contradicts declared kernel")
                if b.contract==DISPATCH:
                    keys(value["point"],"name version","dispatch.point")
                    if b.caused_by in confirmations and confirmations[b.caused_by]!=value["reading_ns"]:
                        raise ActionModelFalsified(reason="event_contradiction",detail="dispatch happened at conflicting readings")
                    confirmations[b.caused_by]=value["reading_ns"]
    events=[]; likelihoods=[]; reportmap={}
    for at,(r,command,decision) in attempts.items():
        # A recorded dispatch is evidence, never a replacement control value.
        if command.dispatch.name=="immediate-start":
            start=F(decision["reading_ns"])
        else:
            ex=d["execution"]; receipt=F(decision["reading_ns"])+deterministic_delay(ex["receipt"],"receipt")
            start=max(F(command.not_before_ns),receipt)+deterministic_delay(ex["chi"]["candidates"][0]["delay"],"chi")
        pair=reports.get(at)
        event=_Event(command,start,start+fixed_duration(model,command.action),str(pair[0].id) if pair else str(at))
        if at in confirmations and confirmations[at]!=event.dispatch_ns:
            raise ActionModelFalsified(reason="clock_contradiction",detail="dispatch reading contradicts declared kernel")
        # Reconstruction stops at this frozen clock reading. A deterministic
        # reservation/receipt before dispatch is not a B sample. This does not
        # certify planning from a pending root (certify_action_scope still stops).
        if pair is None:
            if event.dispatch_ns<=context.now_ns: events.append(event)
            continue
        report,rv=pair
        m=d["effects"][command.action]["measure"]
        expected_measure=event.dispatch_ns if m["at"]=="start" else event.completion_ns
        for k,expected in (("measurement_reading_ns",expected_measure),("completion_reading_ns",event.completion_ns)):
            if rv[k] is not None and (type(rv[k]) is not int or rv[k]!=expected):
                raise ActionModelFalsified(reason="clock_contradiction",detail="report reading contradicts model",field=k)
        if event.completion_ns>context.now_ns:
            raise ActionModelFalsified(reason="clock_contradiction",detail="adopted completion is in the future")
        events.append(event); reportmap[event.report]=event; likelihoods.append((event,rv["outcome"],rv["effect_notice"]))
    events.sort(key=lambda e:e.key)
    done=[]
    for event in events:
        paths=_extend(model,tuple(done),paths,event,budget); done.append(event)
    paths,mass=_condition(model,tuple(events),paths,likelihoods)
    obs=tuple(sorted((event.report,y,n) for event,y,n in likelihoods))
    return _make(model,context,events,paths,reportmap,obs,
        "pending" if reading.pending else "complete" if events else "prior",_log(mass),mass)


def target_marginal(belief: ActionBelief, targets: tuple[FixedLabel|TargetRef,...], *, budget: ActionBudget) -> DiscreteMarginal:
    check_budget(budget)
    if getattr(belief._data,'finite',False):
        from .action_finite import marginal
        return marginal(belief,tuple(targets),budget)
    data=belief._data; targets=tuple(targets)
    labels=tuple(_resolve(data,t) for t in targets)
    cells={}
    if len(data.paths)>budget.node_budget: raise ActionIncomplete(reason="budget",detail="marginal exceeds path budget")
    for path in data.paths:
        row=tuple(data.model.states[_state_at(path,data.events,label)] for label in labels)
        cells[row]=cells.get(row,F(0))+path.probability
    # A one-state query exposes the whole declared axis, including structural zeros.
    if len(targets)==1:
        for state in data.model.states: cells.setdefault((state,),F(0))
    return DiscreteMarginal(targets=targets,cells=tuple((row,rational_bounds(p)) for row,p in sorted(cells.items())))


def parameter_moment(belief: ActionBelief, *, parameter: str, action: str,
                     powers: tuple[tuple[int,...],...], budget: ActionBudget) -> Bounds:
    check_budget(budget)
    d=load_canonical(belief._data.model.declaration)
    if parameter not in ("B","Theta") or action not in d["actions"]:
        raise ActionInputError(reason="shape",detail="unknown parameter/action")
    t=d["effects"][action]["B"]["values"] if parameter=="B" else d["a"][action]
    if not isinstance(powers,(tuple,list)) or len(powers)!=len(t) or any(not isinstance(p,(tuple,list)) or len(p)!=len(row) for p,row in zip(powers,t)) or any(type(v) is not int or v<0 for row in powers for v in row):
        raise ActionInputError(reason="shape",detail="nonnegative integer powers must match table")
    if sum(v for row in powers for v in row)>budget.node_budget:
        raise ActionIncomplete(reason="budget",detail="parameter moment powers exceed arithmetic budget")
    product=measure(belief._data.model); increment=list(product.zero); known=F(1)
    for row,(values,row_powers) in enumerate(zip(t,powers)):
        for column,(x,power) in enumerate(zip(values,row_powers)):
            if not power: continue
            coordinate=product.indexes.get((parameter,action,column,row))
            if (parameter,action,column) not in product.groups: known*=rational(x,"parameter")**power
            elif coordinate is None: return rational_bounds(F(0))
            else: increment[coordinate]=power
    if len(belief._data.paths)>budget.node_budget:
        raise ActionIncomplete(reason="budget",detail="parameter moment exceeds path budget")
    value=known*sum((path.probability*product.moment(tuple(a+b for a,b in zip(path.counts,increment)))/
        product.moment(path.counts) for path in belief._data.paths),F(0))
    return rational_bounds(value)


def hypothesis_weights(belief: ActionBelief, *, parameter: str, budget: ActionBudget) -> tuple[Bounds,...]:
    check_budget(budget)
    if getattr(belief._data,'finite',False):
        from .action_finite import weights
        return weights(belief,parameter,budget)
    d=load_canonical(belief._data.model.declaration)
    if parameter=="rho": values=d["completion"]["weights"]
    elif parameter=="lambda":
        clock=d["clock"]; values=[p["weight"] for p in (clock["candidates"] if clock["kind"]=="clock-process" else clock["measure"]["candidates"])]
    elif parameter=="chi": values=[] if d["execution"]["chi"] is None else [p["weight"] for p in d["execution"]["chi"]["candidates"]]
    else: raise ActionInputError(reason="shape",detail="unknown hypothesis parameter")
    return tuple(rational_bounds(rational(v,"weight")) for v in values)
