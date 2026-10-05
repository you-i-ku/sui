"""Model.8 worker messages and immutable, host-held command bindings."""
from dataclasses import dataclass
from .action_types import DecisionReading, ActionInputError, ActionRuntimeUnverified
from .dispatch import build_command, command_json, DispatchNotice, ActionResult
from .action_model import load_canonical
from .records import AttemptStarted, Payload, Record, Role
from .ids import Ref, RefKind
from .s4b_action_contracts import ATTEMPT, RESERVATION, RECEIPT, DISPATCH, REPORT


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionDone:
    attempt: Ref
    result: ActionResult


def decision_json(decision):
    return dict(run=str(decision.run), reading_ns=decision.reading_ns,
                work=decision.work, parents=sorted(decision.parents))


def bind(work, draft, decision):
    if (not isinstance(decision, DecisionReading) or decision.work != work.work
            or decision.parents != work.view.frontier):
        raise ActionInputError(reason='schema', detail='decision reading differs from frozen Think')
    stages = [r.body.content.as_json()['command']['causal_stage']
              for r in work.view.reading._action_records
              if isinstance(r.body, AttemptStarted) and r.body.contract == ATTEMPT]
    position = int(work.work.split(':', 1)[1]) - 1
    return build_command(model=work.view.model, choice=draft.content.as_json()['chosen'],
        decision=decision, causal_stage=max(stages, default=-1)+1, causal_position=position)


def think(work, clock, planner):
    from .runtime import Thought
    try:
        draft = planner(work.view, work.candidates, u=work.u)
        decision = DecisionReading(run=clock.run, reading_ns=clock.mono_ns(),
                                   work=work.work, parents=work.view.frontier)
        command = bind(work, draft, decision)
        return Thought(work=work.work, draft=draft, decision_reading=decision, _command=command)
    except Exception as exc:
        return Thought(work=work.work, error=type(exc).__name__)


def execute(work, hand, dispatcher, post):
    from .runtime import Failed
    try:
        if dispatcher is None:
            raise ActionRuntimeUnverified(reason='dispatch_point', detail='a WaitDispatcher is required')
        result = dispatcher.execute(work, hand, emit=post)
        return ActionDone(attempt=work.attempt, result=result)
    except Exception as exc:
        return Failed(attempt=work.attempt, error=type(exc).__name__)


def completion(window, event, received_ns):
    result = event.result
    return window._observation(route=window.route, contract=REPORT,
        content=Payload.json(dict(outcome=result.outcome, effect_notice=result.effect_notice,
            measurement_reading_ns=result.measurement_reading_ns,
            completion_reading_ns=result.completion_reading_ns)),
        caused_by=event.attempt, received_ns=received_ns,
        source_id=f'{event.attempt}:report')


def confirmation(window, event, received_ns):
    value = dict(command=load_canonical(command_json(event.command)),
                 run=str(event.run), reading_ns=event.reading_ns)
    if event.kind == 'dispatch':
        value['point'] = dict(name=event.point.name, version=event.point.version)
    return window._observation(route=window.route,
        contract=RECEIPT if event.kind == 'receipt' else DISPATCH,
        content=Payload.json(value), caused_by=event.attempt, received_ns=received_ns,
        source_id=f'{event.attempt}:{event.kind}')


def start(window, job, action):
    from .runtime import Start, Act
    if job.id not in window.pledges.commands:
        raise ActionRuntimeUnverified(reason='clock_fit',
            detail='queued intent has no retained worker decision reading; reservation cannot be rebound')
    command, decision = window.pledges.commands[job.id]
    payload = Payload.json(dict(command=load_canonical(command_json(command)),
                                decision_reading=decision_json(decision)))
    attempt = Record(id=window.ids.new(RefKind.ATTEMPT), at=window.clock.now(),
        writer=Role.MEMBRANE, producer=window.membrane,
        body=AttemptStarted(job=job.id, contract=ATTEMPT, content=payload))
    reservation = window._observation(route=window.route, contract=RESERVATION,
        content=payload, caused_by=attempt.id, received_ns=window.clock.mono_ns(),
        source_id=f'{attempt.id}:reservation')
    return Start(job=job.id, attempt=attempt,
        act=Act(attempt=attempt.id, action=action, command=command), reservation=reservation)
