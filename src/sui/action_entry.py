"""Certification and public Draft boundary for the first three S4b checkpoints."""
from dataclasses import asdict,replace
from fractions import Fraction as F
import math
import numpy as np
from .action_types import *
from .action_model import ActionModel,load_canonical,rational
from .action_joint import rebuild,fixed_duration,deterministic_delay,target_marginal,parameter_moment,hypothesis_weights
from .action_learning import measure
from .action_lookahead import evaluate_tree,midpoint,objective
from .action_reference import information_potential
from .clock_contracts import check_clock_sources
from .records import Payload,Observed,AttemptStarted
from .s4b_action_contracts import BELIEF,DECISION
from .inference import select
from .values import _thaw
from .agent import View, Reading, Draft
from .preference import Resolved


def _support(status,reason=None,model=None):
    learned=model is not None and bool(measure(model).beta)
    return ActionSupport(status=status,stage=("1b" if learned else "1a") if status=="certified" else None,reason=reason,
        method=("finite_dirichlet_path_mixture" if learned else "finite_rational_paths") if status=="certified" else None,
        conditions=(("column_dirichlet_product_mixture","known_marks_notice","single_trial_at_dispatch") if learned else ("known_laws",))+
        ("Q_zero","positive_fixed_completion","point_dispatch","explicit_labels","finite_depth") if status=="certified" else ())


def _model_support(model):
    d=load_canonical(model.declaration)
    if d["arrivals"]: return _support("incomplete","arrival_scope")
    if any(e["family"]["name"]!="start-impulse" for e in d["effects"].values()):
        return _support("incomplete","continuous_branches")
    from .action_finite import needed,scope
    if needed(model): return scope(model)
    clock=d["clock"]
    if clock["kind"]=="clock-process":
        if any(p["kind"]!="exact" for p in clock["candidates"]): return _support("incomplete","latent_label_envelope")
    elif any(p["name"]!="exact" for p in clock["measure"]["candidates"]): return _support("incomplete","latent_label_envelope")
    if clock["kind"]=="legacy-measure" and d["execution"]["family"]["name"]!="immediate-start": return _support("missing_spec","clock_process")
    try:
        for a in model.actions:
            duration=fixed_duration(model,a)
            if duration.denominator!=1: return _support("incomplete","continuous_timing")
        if d["execution"]["family"]["name"]=="wait-dispatch":
            ex=d["execution"]
            values=[deterministic_delay(ex[k],k) for k in ("think","receipt")]
            chi={deterministic_delay(p["delay"],"chi") for p in ex["chi"]["candidates"]}
            if len(chi)!=1: return _support("incomplete","algorithm_unavailable")
            values.extend(chi)
            if any(x.denominator!=1 for x in values): return _support("incomplete","continuous_timing")
            for law in ex["confirmations"].values():
                if law is not None and deterministic_delay(law,"confirmation")!=0: return _support("incomplete","algorithm_unavailable")
    except ActionIncomplete as exc: return _support("incomplete",exc.reason)
    except ActionOutsideEvaluationType as exc: return _support("incompatible",exc.reason)
    # In this family Q is known zero and work/dispatch are independent of B
    # and Theta. Each fixed latent state path contributes transition/emission
    # monomials only. JSON marks/notice are known tables, so marginalizing E
    # preserves a finite mixture of conjugate column products.
    return _support("certified",model=model)


def _candidates(model,candidates):
    try: values=tuple(candidates)
    except TypeError as exc: raise ActionInputError(reason="unknown_candidate",detail="candidate sequence required") from exc
    if not values or any(type(x) is not str or x not in model.choices for x in values):
        raise ActionInputError(reason="unknown_candidate",detail="nonempty known choice names required")
    return tuple(sorted(set(values)))


def certify_action_scope(view: View,candidates: tuple[str,...],resolved: Resolved,*,budget: ActionBudget) -> ActionSupport:
    if not isinstance(budget,ActionBudget): raise ActionInputError(reason="invalid_budget",detail="ActionBudget required")
    if not isinstance(view.model,ActionModel): raise ActionInputError(reason="schema",detail="ActionModel view required")
    _candidates(view.model,candidates)
    support=_model_support(view.model)
    if support.status!="certified": return support
    if view.now_ns is None or view.observed_ns is None or view.reading.timeline is None or not view.reading.timeline.runs:
        return _support("missing_spec","clock_process")
    if resolved.H_ns is not None:
        try: minimum=min(fixed_duration(view.model,a) for a in view.model.actions)
        except ActionIncomplete: minimum=None
        if minimum is not None and resolved.H_ns//minimum+1>budget.node_budget: return _support("incomplete","budget")
    return support


def rebuild_action_belief(model: ActionModel,reading: Reading,*,context: ActionTimeContext,budget: ActionBudget) -> ActionBelief:
    if not isinstance(budget,ActionBudget): raise ActionInputError(reason="invalid_budget",detail="ActionBudget required")
    return rebuild(model,reading,context=context,budget=budget)


def _context(view):
    sources=check_clock_sources(view.reading._action_records)
    run=view.reading.timeline.runs[-1]
    return ActionTimeContext(run=run,now_ns=view.now_ns,observed_ns=view.observed_ns,
        check_events=view.check_events,fact_ancestors=view.fact_ancestors,
        clock_source=None if run not in sources else sources[run][1])


def public_evaluate(view: View,candidates: tuple[str,...],resolved: Resolved,*,u:float,budget:ActionBudget) -> Draft:
    if type(u) not in (int,float) or not math.isfinite(u) or not 0<=u<1:
        raise ActionInputError(reason="invalid_u",detail="finite u in [0,1) required")
    choices=_candidates(view.model,candidates)
    certificate=certify_action_scope(view,choices,resolved,budget=budget); require_certificate(certificate)
    if not view.check_events:
        raise ActionInputError(reason="schema",detail="a receipt/check source at observed_ns is required",field="check_events")
    root=rebuild_action_belief(view.model,view.reading,context=_context(view),budget=budget)
    for refinement in range(budget.refinement_budget):
        local=replace(budget,tolerance=budget.tolerance/(4**refinement))
        _,_,values,q,q_bounds=evaluate_tree(root,choices,resolved,certificate,local)
        intervals=[box for c,i,r in values for box in (c,i,objective(c,i)) if box is not None]+list(q_bounds)
        if all(box.lower==box.upper or box.upper-box.lower<=budget.tolerance for box in intervals): break
    else: raise ActionIncomplete(reason="accuracy",detail="root decision intervals exceed requested width")
    chosen=choices[select(np.asarray(q),u)]
    d=load_canonical(view.model.declaration); choice=d["choices"][chosen]; action=choice["action"]
    encode=lambda x:"+inf" if x==math.inf else float(x)
    C=[encode(midpoint(c)) for c,i,r in values]; I=[None if i is None else midpoint(i) for c,i,r in values]
    J=["+inf" if c=="+inf" or i is None else c-i for c,i in zip(C,I)]
    bounds=lambda box:None if box is None else [encode(box.lower),encode(box.upper)]
    time={"run":str(root.context.run),"now_ns":view.now_ns,"observed_ns":view.observed_ns,
        "deadline_ns":None if resolved.H_ns is None else view.now_ns+resolved.H_ns,
        "check_events":[_thaw(x) for x in view.check_events],
        "clock_source":None if root.context.clock_source is None else str(root.context.clock_source)}
    content={"evaluation":"one_step" if resolved.H_ns is None else "lookahead",
        "items":[{"id":str(item.id),"rule":{"name":item.rule.name,"version":item.rule.version}} for item in resolved.items],
        "style":None if resolved.style is None else str(resolved.style),"H_ns":resolved.H_ns,"gamma":resolved.gamma,
        "candidates":list(choices),"u":float(u),"chosen":chosen,"expected_cost":C,"information":I,"J":J,"q_pi":list(q),
        "expected_cost_bounds":[bounds(c) for c,i,r in values],"information_bounds":[bounds(i) for c,i,r in values],
        "J_bounds":[bounds(objective(c,i)) for c,i,r in values],"q_pi_bounds":list(map(bounds,q_bounds)),"undefined_reason":[r for c,i,r in values],
        "root":{"belief":str(view.belief),"parents":sorted(view.frontier)},"time":time,
        "intent":{"action":action,"choice":chosen,"reservation_rule":choice["reservation"],
            "dispatch":d["execution"]["family"],"effect":d["effects"][action]["family"]},
        "algorithm":{"name":certificate.method,"version":"1","stage":certificate.stage},
        "budget":asdict(budget),"guarantee":"certified_truncation_without_floating_rounding"}
    return Draft(parents=view.frontier,belief=view.belief,content=Payload.json(content),contract=DECISION,
        preference_inputs=tuple(item.id for item in resolved.items)+(() if resolved.style is None else (resolved.style,)))


def derive(model,reading):
    d=load_canonical(model.declaration)
    axis=reading.timeline
    context=None; belief=None; reason=None; status="prior"
    try:
        if not reading._action_records:
            require_certificate(_model_support(model))
            q=np.array([rational_bounds(rational(x,"D")).lower for x in d["D"]])
        elif axis is None or not axis.runs:
            status="no_axis"; q=None
        else:
            run=axis.runs[-1]
            from .clock_contracts import SOURCE
            observed=max((r.body.received_ns for r in reading._action_records if isinstance(r.body,Observed)
                and r.body.contract!=SOURCE and r.at.run==run and r.body.received_ns is not None),default=0)
            sources=check_clock_sources(reading._action_records)
            context=ActionTimeContext(run=run,now_ns=observed,observed_ns=observed,check_events=(),
                fact_ancestors={},clock_source=None if run not in sources else sources[run][1])
            belief=rebuild_action_belief(model,reading,context=context,budget=default_budget()); status=belief.status
            from .action_finite import boot_reading
            model_now=observed-boot_reading(reading,run) if getattr(belief._data,'finite',False) else observed
            label=FixedLabel(time_s=F(model_now,1000000000),causal_stage=max((e.command.causal_stage for e in belief._data.events),default=0)+1,
                causal_position=0,side="post")
            cells={row:p.lower for row,p in target_marginal(belief,(label,),budget=default_budget()).cells}
            q=np.array([cells.get((s,),0.) for s in model.states])
    except ActionModelFalsified as exc: status="unexplained"; reason=exc.reason; q=None
    except (ActionIncomplete,ActionIncompatible,ActionOutsideEvaluationType,ActionSpecificationMissing) as exc:
        status="incomplete"; reason=exc.reason; q=None
    from .s4b_action_contracts import ATTEMPT
    from .s3_contracts import ENDED
    attempts={job:tuple(r.id for r in reading._action_records if isinstance(r.body,AttemptStarted)
        and r.body.contract==ATTEMPT and r.body.job==job) for job in reading.pending}
    failed={r.body.caused_by for r in reading._action_records if isinstance(r.body,Observed) and r.body.contract==ENDED}
    content={"model":model.ref,"states":list(model.states),"outcomes":list(model.outcomes),"status":status,"reason":reason,
        "context":None if context is None else {"run":str(context.run),"now_ns":context.now_ns,"observed_ns":context.observed_ns,
            "check_events":[],"clock_source":None if context.clock_source is None else str(context.clock_source)},
        "evidence":None if belief is None else {"kind":belief.evidence_kind,"log_bounds":[belief.log_evidence.lower,belief.log_evidence.upper]},
        "q":None if q is None else q.tolist(),"theta_mean":None,"B_mean":None,
        "rho_weights":None,"lambda_weights":None,"chi_weights":None,
        "pending":[{"job":str(job),"attempt":str(attempts[job][0]) if len(attempts[job])==1 else None,
            "action":a,"phase":"result_unknown" if len(attempts[job])==1 and attempts[job][0] in failed else None}
            for job,a in sorted(reading.pending.items(),key=lambda p:str(p[0]))],
        "unread":[{"id":str(ref),"reason":reason} for ref,reason in sorted(reading.unread.items(),key=lambda p:str(p[0]))]}
    if q is not None:
        def means(parameter,action,rows):
            values=[]; product=measure(model)
            for row in range(rows):
                result=[]
                for column in range(len(model.states)):
                    powers=tuple(tuple(int((i,j)==(row,column)) for j in range(len(model.states))) for i in range(rows))
                    result.append(parameter_moment(belief,parameter=parameter,action=action,powers=powers,budget=default_budget()).lower
                        if belief is not None else rational_bounds(product.observe(parameter,action,column,row,product.zero)[0]).lower)
                values.append(result)
            return values
        content["theta_mean"]={a:means("Theta",a,len(model.outcomes)) for a in model.actions}
        content["B_mean"]={a:means("B",a,len(model.states)) for a in model.actions}
        content["rho_weights"]=[rational_bounds(rational(x,"rho")).lower for x in d["completion"]["weights"]]
        clock=d["clock"]; content["lambda_weights"]=[rational_bounds(rational(p["weight"],"lambda")).lower for p in (clock["candidates"] if clock["kind"]=="clock-process" else clock["measure"]["candidates"])]
        content["chi_weights"]=[] if d["execution"]["chi"] is None else [rational_bounds(rational(p["weight"],"chi")).lower for p in d["execution"]["chi"]["candidates"]]
        if belief is not None:
            for parameter in ('rho','lambda','chi'):
                content[parameter+'_weights']=[p.lower for p in hypothesis_weights(belief,parameter=parameter,budget=default_budget())]
    return q,{},content
