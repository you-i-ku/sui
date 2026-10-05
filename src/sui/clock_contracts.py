"""Run-scoped clock provenance; a source declaration is not a measurement."""
from dataclasses import dataclass
from fractions import Fraction
from .contracts import Contract, ContractRef
from .ids import Ref, RefKind, expect
from .action_types import ActionInputError, ActionModelFalsified, reference
from .action_model import keys, rational
from .dispatch import parse_ref

SOURCE=ContractRef("sui.clock.source","1")
DECLARATIONS=(Contract(ref=SOURCE,
    meaning='Observed payload={run,provider,implementation,python_version,resolution_s,monotonic,adjustable,measurement}. Same run has one source; null measurement is undeclared. BOOT stays {}. No world-state target or nonarrival check is added.',
    unit='resolution_s reduced rational seconds; readings integer ns',state_owner='sui.clock',
    persistence='Keep each old run and reading unchanged; declarations follow BOOT',
    failure='Conflicting declarations falsify the clock model; source alone never certifies exact timing',
    cancel='none',redelivery='Identical declaration is idempotent'),)


@dataclass(frozen=True,slots=True,kw_only=True)
class ClockSource:
    run: Ref
    provider: str
    implementation: str
    python_version: str
    resolution_s: Fraction
    monotonic: bool
    adjustable: bool
    measurement: ContractRef | None

    def __post_init__(self):
        reference(self.run,RefKind.RUN,field="run")
        if any(type(getattr(self,k)) is not str or not getattr(self,k) for k in ("provider","implementation","python_version")):
            raise ActionInputError(reason="schema",detail="clock source names required")
        if not isinstance(self.resolution_s,Fraction) or self.resolution_s<=0:
            raise ActionInputError(reason="unit",detail="positive Fraction seconds resolution required")
        if type(self.monotonic) is not bool or type(self.adjustable) is not bool or (self.measurement is not None and not isinstance(self.measurement,ContractRef)):
            raise ActionInputError(reason="schema",detail="clock flags/measurement types")

    def as_json(self):
        return {"run":str(self.run),"provider":self.provider,"implementation":self.implementation,
            "python_version":self.python_version,"resolution_s":[self.resolution_s.numerator,self.resolution_s.denominator],
            "monotonic":self.monotonic,"adjustable":self.adjustable,
            "measurement":None if self.measurement is None else {"name":self.measurement.name,"version":self.measurement.version}}


def system_clock_source(clock):
    """Provenance of a new SystemClock run, without an exact measurement claim."""
    import platform
    import time
    info = time.get_clock_info('perf_counter')
    return ClockSource(run=clock.run, provider='python.time.perf_counter_ns',
        implementation=info.implementation, python_version=platform.python_version(),
        resolution_s=Fraction(str(info.resolution)), monotonic=info.monotonic,
        adjustable=info.adjustable, measurement=None)


def clock_source_from_json(d):
    keys(d,"run provider implementation python_version resolution_s monotonic adjustable measurement","clock_source")
    m=d["measurement"]
    if m is not None: keys(m,"name version","measurement")
    return ClockSource(**{**d,"run":parse_ref(d["run"],"run",RefKind.RUN),
        "resolution_s":rational(d["resolution_s"],"resolution_s",positive=True),
        "measurement":None if m is None else ContractRef(**m)})


def check_clock_sources(records):
    from .records import Observed
    found={}
    for r in records:
        if isinstance(r.body,Observed) and r.body.contract==SOURCE:
            source=clock_source_from_json(r.body.content.as_json())
            if r.at.run!=source.run:
                raise ActionModelFalsified(reason="clock_contradiction",detail="source belongs to another run")
            if source.run in found and found[source.run][0]!=source:
                raise ActionModelFalsified(reason="clock_contradiction",detail="different source declarations in one run")
            if source.run not in found or str(r.id)<str(found[source.run][1]): found[source.run]=(source,r.id)
    return found
