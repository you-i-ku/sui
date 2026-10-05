"""S4b action contracts. Registration is explicit, as for older contracts."""
from .contracts import Contract, ContractRef

BELIEF=ContractRef("sui.s4b.action_belief","1")
DECISION=ContractRef("sui.s4b.action_decision","1")
JOB=ContractRef("sui.s4b.action_job","1")
ATTEMPT=ContractRef("sui.s4b.action_attempt","1")
RESERVATION=ContractRef("sui.s4b.reservation","1")
RECEIPT=ContractRef("sui.s4b.receipt","1")
DISPATCH=ContractRef("sui.s4b.dispatch","1")
REPORT=ContractRef("sui.s4b.action_report","1")

_MEANINGS={
    BELIEF:'Prediction target=belief; content has exactly model,states,outcomes,status,reason,context,evidence,q,theta_mean,B_mean,rho_weights,lambda_weights,chi_weights,pending,unread. Rebuild joint posterior from facts; summaries are not learning inputs.',
    DECISION:'Decided content has exactly evaluation,items,style,H_ns,gamma,candidates,u,chosen,expected_cost,information,J,q_pi,expected_cost_bounds,information_bounds,J_bounds,q_pi_bounds,undefined_reason,root,time,intent,algorithm,budget,guarantee. intent is chosen rule, not future measured r_d or command. Uncertified computation returns no Draft.',
    JOB:'JobOpened payload={action,choice,reservation_rule,dispatch,effect}. Choice names and physical actions differ.',
    ATTEMPT:'AttemptStarted payload={command,decision_reading:{run,reading_ns,work,parents}}. Securing an attempt is not B application; unchanged schema 3.',
    RESERVATION:'Observed caused_by=attempt payload={command,decision_reading:{run,reading_ns,work,parents}}. Same command as attempt, not independent duplicate evidence.',
    RECEIPT:'Observed caused_by=attempt payload={command,run,reading_ns}. Payload reading is event; received_ns is host receipt; Record.at is creation.',
    DISPATCH:'Observed caused_by=attempt payload={command,run,reading_ns,point:{name,version}}. Adapter confirms a named actual dispatch point once; no claim that world response completed.',
    REPORT:'Observed caused_by=attempt payload={outcome,effect_notice,measurement_reading_ns,completion_reading_ns}. Null means unobserved; never fill null with Record.at. Report does not reapply B.'}

DECLARATIONS=tuple(Contract(ref=ref,meaning=meaning,
    unit='integer ns readings; rational true seconds; probability mass; information nat',
    state_owner='sui.agent' if ref in (BELIEF,DECISION,JOB) else 'sui.runtime',
    persistence='Canonical content; retain accepted facts and fixed command; fact-only rebuild',
    failure='Keep receipt/dispatch/failure separately; contradictory evidence falsifies adoption, not reception',
    cancel='Abandon stops waiting for result; does not undo physical action',
    redelivery='Record/source identity prevents duplicate likelihood or trials; B trial once at family-defined application')
    for ref,meaning in _MEANINGS.items())
