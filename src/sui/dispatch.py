"""Command encoding and worker-side, clock-checked dispatch."""
from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol, TYPE_CHECKING
from threading import Lock
import math

from .action_types import *
from .action_model import ActionModel, load_canonical, canonical, keys, family, reservation, error
from .contracts import ContractRef
from .ids import Ref, RefKind
from .values import _thaw
from .clock import Clock

if TYPE_CHECKING:
    from .runtime import Act


def parse_ref(value, field, kind=None):
    try:
        prefix, name=value.split(":",1)
        ref=Ref(RefKind(prefix),name)
        if kind is not None and ref.kind!=kind: error("schema","wrong reference kind",field)
        return ref
    except (ValueError,TypeError,AttributeError) as exc:
        if isinstance(exc,ActionInputError): raise
        error("schema","invalid reference",field)


def build_command(*, model: ActionModel, choice: str, decision: DecisionReading,
                  causal_stage: int, causal_position: int) -> Command:
    d=load_canonical(model.declaration)
    if choice not in d["choices"]:
        raise ActionInputError(reason="unknown_candidate",detail="unknown choice",field="choice")
    if not isinstance(decision,DecisionReading): error("schema","DecisionReading required","decision")
    p=d["choices"][choice]; rule=p["reservation"]; kind=rule["kind"]
    s=(decision.reading_ns+rule["step_ns"] if kind=="next" else
       decision.reading_ns+rule["offset_ns"] if kind=="offset" else
       rule["not_before_ns"] if kind=="at" else None)
    command=Command(action=p["action"],choice=choice,run=decision.run,not_before_ns=s,
        reservation_rule=rule,dispatch=ContractRef(**d["execution"]["family"]),
        effect=ContractRef(**d["effects"][p["action"]]["family"]),late=d["execution"]["late"],
        causal_stage=causal_stage,causal_position=causal_position)
    command_json(command)
    return command


def _object(command):
    if not isinstance(command,Command): error("schema","Command required")
    return {"action":command.action,"choice":command.choice,"run":str(command.run),
        "not_before_ns":command.not_before_ns,"reservation_rule":_thaw(command.reservation_rule),
        "dispatch":{"name":command.dispatch.name,"version":command.dispatch.version},
        "effect":{"name":command.effect.name,"version":command.effect.version},"late":command.late,
        "causal_stage":command.causal_stage,"causal_position":command.causal_position}


def _validate(d):
    keys(d,"action choice run not_before_ns reservation_rule dispatch effect late causal_stage causal_position","command")
    for k in ("action","choice"):
        if type(d[k]) is not str or not d[k]: error("schema","nonempty name required",k)
    parse_ref(d["run"],"run",RefKind.RUN)
    family(d["dispatch"],"dispatch",{"wait-dispatch":"1","immediate-start":"1"})
    family(d["effect"],"effect",{"start-impulse":"2","response-wait":"1"})
    reservation(d["reservation_rule"],"reservation_rule")
    if d["dispatch"]["name"]=="immediate-start":
        if d["not_before_ns"] is not None or d["late"] is not None or d["reservation_rule"]["kind"]!="immediate": error("schema","immediate command requires null threshold/late")
    else:
        integer(d["not_before_ns"],field="not_before_ns")
        if d["late"]!="send_when_ready" or d["reservation_rule"]["kind"]=="immediate": error("schema","waiting command requires reservation and send_when_ready")
        if d["reservation_rule"]["kind"]=="at" and d["not_before_ns"]!=d["reservation_rule"]["not_before_ns"]: error("schema","at threshold must equal command threshold")
    integer(d["causal_stage"],field="causal_stage",minimum=0)
    integer(d["causal_position"],field="causal_position",minimum=0)


def command_json(command: Command) -> bytes:
    d=_object(command); _validate(d)
    return canonical(d)


def command_from_json(data: bytes) -> Command:
    d=load_canonical(data); _validate(d)
    return Command(**{**d,"run":parse_ref(d["run"],"run",RefKind.RUN),
        "dispatch":ContractRef(**d["dispatch"]),"effect":ContractRef(**d["effect"])})


@dataclass(frozen=True,slots=True,kw_only=True)
class ActionResult:
    outcome: str | None
    effect_notice: str | None
    measurement_reading_ns: int | None
    completion_reading_ns: int | None

    def __post_init__(self):
        for k in ("outcome","effect_notice"):
            v=getattr(self,k)
            if v is not None and (type(v) is not str or not v): error("schema","nonempty string or null required",k)
        for k in ("measurement_reading_ns","completion_reading_ns"):
            if getattr(self,k) is not None: integer(getattr(self,k),field=k)


@dataclass(frozen=True,slots=True,kw_only=True)
class DispatchNotice:
    kind: str
    attempt: Ref
    command: Command
    run: Ref
    reading_ns: int
    point: ContractRef | None

    def __post_init__(self):
        reference(self.attempt,RefKind.ATTEMPT,field="attempt"); reference(self.run,RefKind.RUN,field="run")
        if not isinstance(self.command,Command): error("schema","Command required","command")
        integer(self.reading_ns,field="reading_ns")
        if self.kind not in ("receipt","dispatch") or self.run!=self.command.run:
            error("schema","invalid dispatch notice")
        if (self.kind=="receipt" and self.point is not None) or (self.kind=="dispatch" and not isinstance(self.point,ContractRef)):
            error("schema","receipt has no point; dispatch requires point")


class DispatchHand(Protocol):
    def resources(self, action: str) -> frozenset[str]: ...
    def send(self, action: str, *, on_dispatched: Callable[[int],None]) -> ActionResult: ...


class WaitDispatcher:
    def __init__(self, *, clock: Clock, wait: Callable[[float],None], point: ContractRef) -> None:
        if not callable(wait) or not isinstance(point,ContractRef): error("schema","wait callback and declared point required")
        self._clock,self._wait,self._point=clock,wait,point

    def execute(self, act: "Act", hand: DispatchHand, *, emit: Callable[[DispatchNotice],None]) -> ActionResult:
        command=act.command
        command_json(command)
        reference(act.attempt,RefKind.ATTEMPT,field="attempt")
        if act.action!=command.action: error("schema","act and command actions differ","action")
        if command.dispatch!=ContractRef("wait-dispatch","1"):
            raise ActionIncompatible(reason="family_requirement",detail="WaitDispatcher requires wait-dispatch/1")
        if not callable(emit): error("schema","notice callback required","emit")

        def read():
            if self._clock.run!=command.run:
                raise ActionOutsideEvaluationType(reason="restart_delivery_law",detail="dispatcher clock run differs from command")
            value=self._clock.mono_ns()
            integer(value,field="clock.reading_ns")
            return value

        receipt=read()
        emit(DispatchNotice(kind="receipt",attempt=act.attempt,command=command,
            run=command.run,reading_ns=receipt,point=None))
        send=getattr(hand,'send',None)
        if not callable(send):
            raise ActionRuntimeUnverified(reason='dispatch_point',detail='a point-confirming DispatchHand.send adapter is required')
        ready=receipt
        while ready<command.not_before_ns:
            try: seconds=(command.not_before_ns-ready)/1000000000
            except OverflowError as exc:
                raise ActionNumericalRange(reason='overflow',detail='requested wait exceeds float range') from exc
            if not math.isfinite(seconds):
                raise ActionNumericalRange(reason='overflow',detail='requested wait exceeds float range')
            if not seconds:
                raise ActionNumericalRange(reason='positive_underflow',detail='positive requested wait disappeared')
            self._wait(seconds)
            value=read()
            if value<ready:
                raise ActionRuntimeUnverified(reason="clock_fit",detail="clock moved backwards during wait")
            ready=value
        confirmed=False
        lock=Lock()

        def on_dispatched(reading_ns):
            nonlocal confirmed
            integer(reading_ns,field="dispatch.reading_ns")
            with lock:
                if confirmed:
                    raise ActionRuntimeUnverified(reason="dispatch_point",detail="adapter confirmed dispatch more than once")
                current=read()
                if reading_ns<ready or reading_ns<command.not_before_ns or reading_ns>current:
                    raise ActionRuntimeUnverified(reason="dispatch_point",detail="adapter confirmation contradicts the shared clock or threshold")
                confirmed=True
            emit(DispatchNotice(kind="dispatch",attempt=act.attempt,command=command,
                run=command.run,reading_ns=reading_ns,point=self._point))

        # An adapter exception deliberately propagates. Already emitted notices
        # survive, and execute never retries a send after an ambiguous failure.
        result=send(act.action,on_dispatched=on_dispatched)
        if not confirmed:
            raise ActionRuntimeUnverified(reason="dispatch_point",detail="adapter returned without confirming its declared point")
        if not isinstance(result,ActionResult): error("schema","ActionResult required","result")
        return result
