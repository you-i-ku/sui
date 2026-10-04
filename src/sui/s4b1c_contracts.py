"""Public progress belief and certified joint decision contracts (§3-10)."""
from .contracts import Contract, ContractRef

BELIEF = ContractRef("sui.s4b.joint_belief", "1")
DECISION = ContractRef("sui.s4b.joint_decision", "1")
DECLARATIONS = (
    Contract(ref=BELIEF,
        meaning='model.7 Prediction target=belief. Keys model,states,outcomes,q,n,unread,time,arrivals,joint. joint={status,reason,theta_mean,work_mean,speed_weights,measure_weights,pending,components}. status is prior/complete/incomplete/unexplained/no_axis. Marginals are summaries of a joint posterior, never independent factors.',
        unit='q and other marginals are probabilities; time is integer ns; counts and components are integers',
        state_owner='sui.agent', persistence='Rebuild every field from model and parent facts; never learn from summaries',
        failure='Unexplained joint evidence has all posterior summaries null and components 0. Uncertified calculation/no axis has null summaries and components null. Before boot use the explicit prior. NumericalRange prevents writing.',
        cancel='none', redelivery='Canonical fact-set rebuild; accepted facts remain on incomplete evaluation'),
    Contract(ref=DECISION,
        meaning='Certified joint one_step or total-information lookahead. Candidate-order expected_cost,information,J,q_pi and corresponding *_bounds have equal lengths. root={belief,parents}, time, items/style, u, algorithm={name,version,stage}, tolerance, undefined_reason, guarantee. Finite C/I use interval midpoints; J=C-I and q_pi=softmax(-gamma J), never midpoint q_bounds.',
        unit='information nat; cost/J preference cost; q_pi probability; time integer ns',
        state_owner='sui.agent', persistence='Existing prepare/commit; replay fixes parents/model/preferences/time/check_events/u and compares all fields',
        failure='+inf means proven forbidden cost or no admissible continuation, with reason. information=null only for undefined continuation. Incomplete is an exception, never a record or zero information. Bounds certify truncation/integration, not floating rounding or selection stability.',
        cancel='Existing decision cancellation', redelivery='Exact replay content equality'),
)
