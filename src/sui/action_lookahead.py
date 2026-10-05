"""Finite observation branches and total-information recursion for stages 1a/b."""
from dataclasses import replace
from types import MappingProxyType
from fractions import Fraction as F
import math
from .action_types import *
from .action_model import load_canonical
from .action_joint import (_make,_extend,_condition,_resolve,_state_at,event_for,
    observation_probability,decision_time,_log)
from .action_reference import report_name,report_bundle,information_potential
from .dispatch import build_command,command_json
from .records import Record,Observed,Payload,Role,Producer
from .clock import Instant
from .ids import RefKind,derive
from .dispatch import parse_ref
from .s4b_action_contracts import REPORT
from .preference import cost,EvaluationInput
from .lookahead import _policy
from .inference import NumericalRange,select


def branches(node: ActionNode, command: Command, *, deadline_ns: int,
             certificate: ActionSupport, budget: ActionBudget) -> BranchMeasure:
    check_budget(budget)
    require_certificate(certificate); integer(deadline_ns,field="deadline_ns")
    if getattr(node.belief._data,'finite',False):
        from .action_finite import branches as finite_branches
        return finite_branches(node,command,deadline_ns,certificate,budget)
    data=node.belief._data
    if node.terminal: raise ActionInputError(reason="schema",detail="terminal node has no branches")
    if command.run!=node.belief.context.run: raise ActionOutsideEvaluationType(reason="restart_delivery_law",detail="command run differs")
    if node.controls and command.causal_stage<=node.controls[-1].causal_stage:
        raise ActionIncomplete(reason="noninterference_unproved",
            detail="sequential branches require a new causal stage; multiple controls in one stage need a joint certificate")
    attempt=derive(RefKind.ATTEMPT,"s4b.action.predicted_attempt",command_json(command).decode("utf-8"))
    origin=node._next_origin()
    origins={**data.origins,(command.causal_stage,command.causal_position):origin}
    event=event_for(data.model,command,node.belief.context.now_ns,report_name(command))
    for target in node.targets:
        label=_resolve(data,target)
        if (label.time_s*1000000000,label.causal_stage,label.causal_position,0 if label.side=="pre" else 1)>=(*event.key,1):
            raise ActionIncomplete(reason="noninterference_unproved",detail="command may change an existing target")
    controls=node.controls+(command,)
    if event.dispatch_ns>deadline_ns:
        belief=replace(node.belief,_data=replace(data,origins=MappingProxyType(origins)))
        child=replace(node,belief=belief,controls=controls,terminal=True)
        return BranchMeasure(atoms=(BranchAtom(probability=rational_bounds(F(1)),records=(),child=child),),
            total_mass=rational_bounds(F(1)),certificate=certificate)
    paths=_extend(data.model,data.events,data.paths,event,budget); events=data.events+(event,)
    reports={**data.reports,event.report:event}
    if event.completion_ns>deadline_ns:
        context=replace(node.belief.context,now_ns=deadline_ns,observed_ns=deadline_ns)
        belief=_make(data.model,context,events,paths,reports,data.observations,"complete",node.belief.log_evidence.lower,data.evidence,origins=origins)
        child=ActionNode(belief=belief,controls=controls,targets=node.targets,terminal=True,trigger=node.trigger)
        return BranchMeasure(atoms=(BranchAtom(probability=rational_bounds(F(1)),records=(),child=child),),
            total_mass=rational_bounds(F(1)),certificate=certificate)
    if event.completion_ns.denominator!=1:
        raise ActionIncomplete(reason="continuous_timing",detail="public branch context requires integer clock readings")
    d=load_canonical(data.model.declaration); e=d["effects"][command.action]
    notices=(None,) if e["notice"] is None else tuple(e["notice"]["labels"])
    atoms=[]
    for outcome in data.model.outcomes:
        for notice in notices:
            mass=sum((p.probability*observation_probability(data.model,event,p,events,outcome,notice) for p in paths),F(0))
            if not mass: continue
            bundle=report_bundle(data.model,event,outcome,notice)
            branch_event=replace(event,report=report_name(command,bundle))
            branch_events=data.events+(branch_event,)
            owner=planned_attempt(command)
            branch_reports={**data.reports,branch_event.report:branch_event,str(attempt):branch_event,owner:branch_event}
            conditioned,_=_condition(data.model,branch_events,paths,((branch_event,outcome,notice),))
            now=int(event.completion_ns); context=replace(node.belief.context,now_ns=now,observed_ns=now)
            observations=data.observations+((branch_event.report,outcome,notice),)
            belief=_make(data.model,context,branch_events,conditioned,branch_reports,observations,"complete",
                _log(data.evidence*mass),data.evidence*mass,origins=origins,node_origin=NodeOrigin(attempts=(owner,)))
            trigger=TargetRef(attempt=owner,position="completion",side="post")
            targets=node.targets+(TargetRef(attempt=owner,position="measurement",side=e["measure"]["side"]),trigger)
            child=ActionNode(belief=belief,controls=controls,targets=targets,terminal=now>=deadline_ns,trigger=trigger)
            measure=event.dispatch_ns if e["measure"]["at"]=="start" else event.completion_ns
            if measure.denominator!=1: raise ActionIncomplete(reason="continuous_timing",detail="measurement clock reading is not integer")
            # A deterministic name identifies the observed bundle, not a path.
            ref=parse_ref(branch_event.report,"predicted_report",RefKind.OBSERVATION)
            record=Record(id=ref,at=Instant(run=command.run,run_index=0,seq=1,mono_ns=now,wall_ns=now),
                writer=Role.MEMBRANE,producer=Producer(component="sui.action_prediction",code_version="1"),
                body=Observed(route=command.action,contract=REPORT,received_ns=now,caused_by=attempt,
                    content=Payload.json(bundle)))
            atoms.append(BranchAtom(probability=rational_bounds(mass),records=(record,),child=child))
    total=sum((a.probability.exact for a in atoms),F(0))
    if total!=1: raise ActionNumericalRange(reason="invalid_interval",detail="branch mass is not one")
    return BranchMeasure(atoms=tuple(atoms),total_mass=rational_bounds(total),certificate=certificate)


def _policy_checked(values,gamma):
    try: return tuple(map(float,_policy(values,gamma)))
    except NoAdmissibleCandidate as exc:
        raise ActionNoAdmissibleCandidate(reason="all_forbidden",detail="every candidate has infinite cost") from exc
    except (NumericalRange,OverflowError) as exc:
        raise ActionNumericalRange(reason="overflow",detail="policy exceeds numerical range") from exc


def midpoint(box):
    return box.lower if box.lower==box.upper else box.lower+(box.upper-box.lower)/2


def objective(c,i):
    if i is None or c.lower==math.inf: return Bounds(math.inf,math.inf,None)
    lower,upper=c.lower-i.upper,c.upper-i.lower
    if not math.isfinite(lower) or not math.isfinite(upper):
        raise ActionNumericalRange(reason="overflow",detail="finite objective exceeds numerical range")
    return Bounds(lower,upper,None)


def _weighted(probabilities,values):
    """Enclose an expectation with nonnegative probability intervals.

    Ignoring their sum constraint only widens this enclosure. In particular a
    zero policy weight removes a forbidden branch without forming 0 * inf.
    """
    lower=[]; upper=[]
    for p,v in zip(probabilities,values):
        if p.upper==0: continue
        if v.lower==math.inf:
            lower.append(math.inf if p.lower else 0.); upper.append(math.inf); continue
        terms=(p.lower*v.lower,p.lower*v.upper,p.upper*v.lower,p.upper*v.upper)
        if any(not math.isfinite(t) for t in terms):
            raise ActionNumericalRange(reason="overflow",detail="finite expectation product exceeds numerical range")
        lower.append(min(terms)); upper.append(max(terms))
    try:
        lo=math.inf if math.inf in lower else math.fsum(lower)
        hi=math.inf if math.inf in upper else math.fsum(upper)
    except (OverflowError,ValueError) as exc:
        raise ActionNumericalRange(reason="overflow",detail="finite expectation sum exceeds numerical range") from exc
    return Bounds(lo,hi,None)


def _policy_intervals(values,gamma):
    estimates=tuple(midpoint(v) for v in values)
    q=_policy_checked(estimates,gamma); intervals=[]
    for i,value in enumerate(values):
        if value.lower==math.inf: intervals.append(Bounds(0.,0.,None)); continue
        # Softmax decreases with its own J and increases with every other J.
        low=tuple(v.upper if j==i else v.lower for j,v in enumerate(values))
        high=tuple(v.lower if j==i else v.upper for j,v in enumerate(values))
        intervals.append(Bounds(_policy_checked(low,gamma)[i],_policy_checked(high,gamma)[i],None))
    return q,tuple(intervals)


def evaluate_tree(root,candidates,resolved,certificate,budget):
    model=root._data.model; spent=0; root_time=root.context.now_ns
    def path_cost(node,outcomes,actions):
        try:
            if getattr(node.belief._data,'finite',False):
                from .action_finite import terminal_cost
                return terminal_cost(node,resolved,root_time)
            return cost(resolved,EvaluationInput(evaluation="one_step" if resolved.H_ns is None else "lookahead",
                O=outcomes,A=actions,candidate_outcome=outcomes[-1][3] if outcomes else None))
        except (NumericalRange,OverflowError) as exc:
            raise ActionNumericalRange(reason="overflow",detail="finite preference cost exceeds numerical range") from exc
    def visit(node,outcomes,actions,depth=0):
        nonlocal spent
        spent+=1
        if spent>budget.node_budget: raise ActionIncomplete(reason="budget",detail="finite tree exceeds node budget")
        if node.terminal:
            c=path_cost(node,outcomes,actions)
            return Bounds(c,c,None),rational_bounds(F(0)),None,None,None
        if depth>200:
            # Recursive execution has a finite implementation stack. Stop, do not truncate.
            raise ActionIncomplete(reason="algorithm_unavailable",detail="recursive tree stack limit")
        base=information_potential(root,node,certificate=certificate,budget=budget)
        values=[]
        finite=getattr(node.belief._data,'finite',False)
        if finite:
            from .action_finite import decision_reading,one_step_deadline
            dtime=decision_reading(node.belief._data,budget)
        else: dtime=decision_time(model,node.belief.context.now_ns)
        if dtime.denominator!=1: raise ActionIncomplete(reason="continuous_timing",detail="decision clock reading is not integer")
        stage=max((e.command.causal_stage for e in node.belief._data.events),default=-1)+1
        for choice in candidates:
            command=build_command(model=model,choice=choice,decision=DecisionReading(run=root.context.run,
                reading_ns=int(dtime),work="prediction",parents=frozenset()),causal_stage=stage,causal_position=0)
            deadline=(one_step_deadline(node.belief._data,command,budget) if finite else
                int(event_for(model,command,node.belief.context.now_ns,report_name(command)).completion_ns)) if resolved.H_ns is None else root_time+resolved.H_ns
            measure=branches(node,command,deadline_ns=deadline,certificate=certificate,budget=budget)
            probabilities=[]; costs=[]; infos=[]; potentials=[]; undefined=False
            event=None if finite else event_for(model,command,node.belief.context.now_ns,report_name(command))
            new_actions=actions if finite else actions+((int(event.dispatch_ns)-root_time,("new",len(actions)),command.action),)
            for atom in measure.atoms:
                p=atom.probability
                child=atom.child
                new_outcomes=outcomes
                if atom.records and not finite:
                    y=atom.records[0].body.content.as_json()["outcome"]
                    new_outcomes=outcomes+((int(event.completion_ns)-root_time,("new",len(actions)),command.action,y),)
                potential=information_potential(root,child,certificate=certificate,budget=budget)
                if resolved.H_ns is None: child=replace(child,terminal=True)
                try: c,i,_,_,_=visit(child,new_outcomes,new_actions,depth+1)
                except ActionNoAdmissibleCandidate:
                    c,i=Bounds(math.inf,math.inf,None),rational_bounds(F(0)); undefined=True
                probabilities.append(p); costs.append(c); infos.append(i); potentials.append(potential)
            C=_weighted(probabilities,costs)
            potential=_weighted(probabilities,potentials); future=_weighted(probabilities,infos)
            I=Bounds(potential.lower-base.upper+future.lower,potential.upper-base.lower+future.upper,None)
            if not math.isfinite(I.lower) or not math.isfinite(I.upper):
                raise ActionNumericalRange(reason="overflow",detail="information sum exceeds range")
            values.append((C,None if undefined else I,"no_continuation" if undefined else "forbidden_terminal" if C.lower==math.inf else None))
        J=tuple(objective(c,i) for c,i,_ in values)
        q,q_bounds=_policy_intervals(J,resolved.gamma)
        C=_weighted(q_bounds,tuple(c for c,i,_ in values))
        I=_weighted(q_bounds,tuple(i if i is not None else rational_bounds(F(0)) for c,i,_ in values))
        return C,I,tuple(values),q,q_bounds
    node=ActionNode(belief=root,controls=(),targets=(),terminal=False)
    return visit(node,(),())
