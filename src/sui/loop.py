"""決定・実行・観測を同期で一歩ずつつなぐ。"""

from collections.abc import Iterable as _Iterable
from dataclasses import dataclass as _dataclass
from typing import TYPE_CHECKING as _TYPE_CHECKING, Protocol as _Protocol

from .clock import Clock as _Clock
from .contracts import ContractRef as _ContractRef
from .ids import IdSource as _IdSource, RefKind as _RefKind
from .records import (
    BODY_KIND as _BODY_KIND, AttemptStarted as _AttemptStarted, Coverage as _Coverage,
    Observed as _Observed, Payload as _Payload, Producer as _Producer,
    Record as _Record, Role as _Role,
)

if _TYPE_CHECKING:
    from .agent import Agent as _Agent


OUTCOME = _ContractRef("sui.s1.outcome", "1")
ATTEMPT = _ContractRef("sui.s1.attempt", "1")


class Executor(_Protocol):
    """行動を実行し、観測の名前を返す係。"""

    def execute(self, action: str) -> str: ...


@_dataclass(frozen=True, slots=True, kw_only=True)
class StepRecords:
    """一歩で作った記録。"""

    decided: _Record
    job: _Record
    attempt: _Record
    observed: _Record
    belief: _Record | None

    def __post_init__(self) -> None:
        for name in ("decided", "job", "attempt", "observed", "belief"):
            value = getattr(self, name)
            if name == "belief" and value is None:
                continue
            if not isinstance(value, _Record):
                raise TypeError(f"{name}: expected Record")


def run_step(agent: "_Agent", executor: Executor, candidates: _Iterable[str], *, u: float,
             clock: _Clock, ids: _IdSource, ledger: list[_Record], ledger_name: str,
             membrane: _Producer) -> StepRecords:
    """一歩を実行し、成功した記録だけを順番に台帳へ足す。"""
    basis = _Coverage(as_of=clock.now(), ledger=ledger_name, through=len(ledger),
                      complete=frozenset(_BODY_KIND))
    decided, job = agent.decide(candidates, u=u, clock=clock, ids=ids, basis=basis)
    attempt = _Record(
        id=ids.new(_RefKind.ATTEMPT), at=clock.now(), writer=_Role.MEMBRANE,
        producer=membrane,
        body=_AttemptStarted(job=job.id, content=_Payload.json({}), contract=ATTEMPT),
    )
    agent.started(attempt)
    outcome = executor.execute(job.body.content.as_json()["action"])
    observed = _Record(
        id=ids.new(_RefKind.OBSERVATION), at=clock.now(), writer=_Role.MEMBRANE,
        producer=membrane,
        body=_Observed(route="executor", caused_by=attempt.id,
                       content=_Payload.json({"outcome": outcome}), contract=OUTCOME),
    )
    belief = agent.observe(observed, clock=clock, ids=ids)
    result = StepRecords(decided=decided, job=job, attempt=attempt,
                         observed=observed, belief=belief)
    ledger.extend([decided, job, attempt, observed])
    if belief is not None:
        ledger.append(belief)
    return result
