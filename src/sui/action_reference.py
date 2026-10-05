"""A single-world reference under fixed controls, without new evidence."""
from fractions import Fraction as F
import math
from dataclasses import replace
from .action_types import *
from .action_joint import _extend,_make,event_for,target_marginal
from .ids import derive,RefKind
from .dispatch import command_json
from .action_model import canonical, load_canonical


def report_bundle(model, event, outcome, notice):
    measure=load_canonical(model.declaration)["effects"][event.command.action]["measure"]
    reading=event.dispatch_ns if measure["at"]=="start" else event.completion_ns
    return {"outcome":outcome,"effect_notice":notice,
            "measurement_reading_ns":int(reading),"completion_reading_ns":int(event.completion_ns)}


def report_name(command, bundle=None):
    seed=command_json(command).decode("utf-8")
    if bundle is not None: seed+=canonical(bundle).decode("utf-8")
    return str(derive(RefKind.OBSERVATION,"s4b.action.branch",seed))


def reference_target(root: ActionBelief, current: ActionNode, targets: tuple[FixedLabel|TargetRef,...],
                     *, certificate: ActionSupport, budget: ActionBudget) -> ReferenceMarginal:
    check_budget(budget)
    require_certificate(certificate)
    if not isinstance(current,ActionNode) or current.belief.model_ref!=root.model_ref:
        raise ActionInputError(reason="schema",detail="matching current ActionNode required")
    controls=current.controls
    if getattr(root._data,'finite',False) or getattr(current.belief._data,'finite',False):
        from .action_finite import reference,as_finite
        current=replace(current,belief=as_finite(current.belief,budget))
        return reference(as_finite(root,budget),current,tuple(targets),certificate,budget)
    data=root._data; events=data.events; paths=data.paths; reports=dict(data.reports); now=root.context.now_ns
    stage=None; next_now=now
    for command,origin in zip(controls,current.origins):
        if command.run!=root.context.run:
            raise ActionOutsideEvaluationType(reason="restart_delivery_law",detail="reference command belongs to another run")
        if origin is not None and origin.attempts:
            triggers=[]
            for attempt in origin.attempts:
                position=current.belief._data.reports.get(attempt)
                if position is None: raise ActionInputError(reason="shape",detail="unknown node origin attempt",field=attempt)
                trigger=next((e for e in events if e.command==position.command),None)
                if trigger is None: raise ActionInputError(reason="shape",detail="node origin is not in the root or preceding controls")
                triggers.append(trigger.completion_ns)
            now=max(triggers)
        elif stage is not None and command.causal_stage!=stage:
            now=next_now
        stage=command.causal_stage
        event=event_for(data.model,command,now,report_name(command))
        paths=_extend(data.model,events,paths,event,budget)
        events=events+(event,); reports[event.report]=event; next_now=max(next_now,event.completion_ns)
        # Labels identify a predicted observation bundle. Register all bundle
        # aliases without conditioning this single-world reference on a result.
        notice=load_canonical(data.model.declaration)["effects"][command.action]["notice"]
        for outcome in data.model.outcomes:
            for label in (None,) if notice is None else notice["labels"]:
                reports[report_name(command,report_bundle(data.model,event,outcome,label))]=event
    # Only the alias and fixed-label correspondence comes from current. No
    # posterior paths, counts, probabilities or observation factors are copied.
    for target in targets:
        if isinstance(target,TargetRef) and target.attempt in current.belief._data.reports:
            reports[target.attempt]=current.belief._data.reports[target.attempt]
    belief=_make(data.model,root.context,events,paths,reports,root._data.observations,root.status,
        root.log_evidence.lower,data.evidence)
    return ReferenceMarginal(root_key=root.evidence_key,controls=tuple(controls),targets=tuple(targets),
        certificate=certificate,_data=belief)


def reference_state_marginal(reference: ReferenceMarginal, *, budget: ActionBudget) -> DiscreteMarginal:
    check_budget(budget)
    require_certificate(reference.certificate)
    return target_marginal(reference._data,reference.targets,budget=budget)


def information_potential(root: ActionBelief,current: ActionNode, *, certificate: ActionSupport,budget: ActionBudget) -> Bounds:
    check_budget(budget)
    require_certificate(certificate)
    if root.model_ref!=current.belief.model_ref:
        raise ActionInputError(reason="schema",detail="root/current model differ")
    if getattr(root._data,'finite',False) or getattr(current.belief._data,'finite',False):
        from .action_finite import information,as_finite
        return information(as_finite(root,budget),replace(current,belief=as_finite(current.belief,budget)),certificate,budget)
    ref=reference_target(root,current,current.targets,certificate=certificate,budget=budget)
    from .action_learning import measure,joint_information
    if measure(root._data.model).beta:
        return joint_information(root,current.belief,ref._data,current.targets,budget)
    b={row:p.exact for row,p in target_marginal(current.belief,current.targets,budget=budget).cells}
    r={row:p.exact for row,p in reference_state_marginal(ref,budget=budget).cells}
    if b==r: return rational_bounds(F(0))
    terms=[]
    for row,p in b.items():
        if not p: continue
        q=r.get(row,F(0))
        if not q: raise ActionNumericalRange(reason="invalid_interval",detail="posterior is outside reference support")
        ratio=p/q
        terms.append(rational_bounds(p).lower*(math.log(ratio.numerator)-math.log(ratio.denominator)))
    value=math.fsum(terms)
    if not math.isfinite(value): raise ActionNumericalRange(reason="overflow",detail="KL exceeds numerical range")
    # Closed finite sum: no truncation error; floating rounding is not certified.
    return Bounds(value,value,None)
