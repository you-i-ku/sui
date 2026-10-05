"""S4b v0.19 §3-1:202 and §3-10-8; source substitution, not real-time precision.

No measurements of the host's resolution are interpreted as an exact clock or
dispatch-latency bound. Existing run bytes remain covered by the model.7 golden.
"""
from dataclasses import fields, is_dataclass
from fractions import Fraction as F
import inspect
import json
import os
import subprocess
import sys
import time

import pytest

from s4b_action_cases import api

CLOCK_FIELDS = {"run", "provider", "implementation", "python_version", "resolution_s",
                "monotonic", "adjustable", "measurement"}


def test_system_clock_both_reads_use_same_perf_counter_provider():
    # Patch the public time provider before clock is imported: this also supports
    # an implementation using a from-import alias, without reading its body or
    # guessing a private patch target. A child process avoids reloading shared types.
    code = '''
import json, time
values = iter((101,307,911))
calls = []
def perf():
    value = next(values)
    calls.append(value)
    return value
def old_source():
    raise AssertionError("SystemClock used monotonic_ns")
time.perf_counter_ns = perf
time.monotonic_ns = old_source
time.time_ns = lambda: 12345
from sui.clock import SystemClock
from sui.ids import Ref, RefKind
clock = SystemClock(run=Ref(RefKind.RUN,"clock-source-test"), run_index=0)
mono = clock.mono_ns()
a,b = clock.now(),clock.now()
print(json.dumps([mono,[a.mono_ns,a.wall_ns,a.seq],[b.mono_ns,b.wall_ns,b.seq],calls]))
'''
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [101, [307, 12345, 1], [911, 12345, 2], [101, 307, 911]]


def test_fakeclock_still_advances_only_explicitly_and_rejects_cross_run():
    from sui.clock import FakeClock, elapsed_ns, CrossRunError
    from sui.ids import Ref, RefKind
    clock = FakeClock(run=Ref(RefKind.RUN, "fake-old"), mono_ns=-10, wall_ns=-20)
    first = clock.now()
    assert clock.mono_ns() == -10
    second = clock.now()
    assert second.mono_ns == -10 and second.seq == first.seq+1
    clock.advance(7)
    third = clock.now()
    assert (third.mono_ns, third.wall_ns) == (-3, -13)
    clock.set_wall(500)
    fourth = clock.now()
    assert elapsed_ns(first, fourth) == 7
    assert fourth.wall_ns == 500
    with pytest.raises(CrossRunError):
        elapsed_ns(first, FakeClock(run=Ref(RefKind.RUN, "fake-new")).now())
    assert (first.mono_ns, first.wall_ns) == (-10, -20)


def test_clock_source_public_fields_and_immutability():
    from sui.ids import Ref, RefKind
    cls = api("clock_contracts").ClockSource
    actual = ({field.name for field in fields(cls) if not field.name.startswith("_")}
              if is_dataclass(cls) else set(inspect.get_annotations(cls)))
    assert actual == CLOCK_FIELDS
    source = cls(run=Ref(RefKind.RUN, "source"), provider="python.time.perf_counter_ns",
        implementation="test source", python_version="test", resolution_s=F(1, 10_000_000),
        monotonic=True, adjustable=False, measurement=None)
    assert source.measurement is None
    with pytest.raises((AttributeError, TypeError)):
        source.provider = "changed"


def test_threadhost_records_source_separately_and_boot_payload_stays_empty(monkeypatch):
    """ThreadHost is the public producer from §3-10-7; no hand is dispatched."""
    from sui.agent import Agent
    from sui.clock import SystemClock
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.records import Producer, Observed
    from sui.runtime import ThreadHost, Tick, Window
    from sui.s4_contracts import BOOT
    from worlds import _model, GatedHand, ScriptDrive

    monkeypatch.setattr(time, "perf_counter_ns", lambda: 123)
    monkeypatch.setattr(time, "time_ns", lambda: 100_000_000_000)
    run = Ref(RefKind.RUN, "s4b-source-record")
    clock = SystemClock(run=run, run_index=0)
    source = api("clock_contracts").ClockSource(run=run,
        provider="python.time.perf_counter_ns", implementation="test perf",
        python_version="test version", resolution_s=F(1, 10_000_000),
        monotonic=True, adjustable=False, measurement=None)
    ledger, ids = Ledger(salts=SequentialSalts()), SequentialIds(prefix="clock")
    model = _model()
    agent = Agent(model=model, lineage="clock")
    agent.belief_record(clock=clock, ids=ids, ledger=ledger)
    hand = GatedHand({action: set() for action in model.actions}, {})
    drive = ScriptDrive(lambda status, event: ())

    def make_window(pledges):
        return Window(agent=agent, ledger=ledger, clock=clock, ids=ids, hand=hand,
            route="test.clock", drive=drive, capacity={"think": 1}, pledges=pledges,
            membrane=Producer(component="test.clock", code_version="1"))

    host = ThreadHost(make_window, clock=clock, clock_source=source)
    host.post(Tick(mono_ns=123))
    assert host.run_until(lambda status: any(e.body_type is Observed and
        ledger.record(e.cid).body.contract.name == "sui.clock.source"
        for e in ledger.entries()), timeout=.1)
    records = [ledger.record(e.cid) for e in ledger.entries() if e.body_type is Observed]
    boots = [r for r in records if r.body.contract == BOOT]
    sources = [r for r in records if r.body.contract.name == "sui.clock.source"]
    assert len(boots) == len(sources) == 1
    boot, declaration = boots[0], sources[0]
    assert boot.body.content.as_json() == {}
    assert declaration.body.contract.version == "1"
    assert boot.at.seq < declaration.at.seq
    expected = {"run": str(run), "provider": "python.time.perf_counter_ns",
        "implementation": "test perf", "python_version": "test version",
        "resolution_s": [1, 10_000_000], "monotonic": True,
        "adjustable": False, "measurement": None}
    assert declaration.body.content.as_json() == expected
    assert set(expected) == CLOCK_FIELDS
    before = tuple(ledger.entries())
    assert host.run_until(lambda status: True, timeout=.1)
    assert tuple(ledger.entries()) == before  # no duplicate declaration on polling
    assert not hand.calls


def test_clock_declaration_roundtrips_as_separate_record_without_rewriting_old_run():
    from sui.agent import read
    from sui.clock import FakeClock
    from sui.contracts import ContractRef
    from sui.ids import Ref, RefKind, SequentialIds
    from sui.ledger import Ledger, SequentialSalts
    from sui.records import Record, Observed, Payload, Role, Producer
    from sui.s4_contracts import BOOT
    from worlds import _model
    ledger, ids = Ledger(salts=SequentialSalts()), SequentialIds(prefix="old-run")
    clock = FakeClock(run=Ref(RefKind.RUN, "legacy"), mono_ns=-17, wall_ns=100)
    old = Record(id=ids.new(RefKind.OBSERVATION), at=clock.now(), writer=Role.MEMBRANE,
        producer=Producer(component="test", code_version="1"), body=Observed(route="membrane",
            contract=BOOT, content=Payload.json({}), received_ns=-17))
    saved = ledger.append(old, ledger.heads())
    original = (saved.header, ledger.contents.get(saved.seal))
    read(_model(), (old,))
    assert (saved.header, ledger.contents.get(saved.seal)) == original
    assert old.at.mono_ns == old.body.received_ns == -17
    assert old.at.wall_ns == 100
    assert not any(ledger.record(e.cid).body.contract == ContractRef("sui.clock.source", "1")
                   for e in ledger.entries())
