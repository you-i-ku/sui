"""S4b-2 v0.6: specification-derived fixtures using public constructors only.

Fixture purpose map (not implementation certification):
T01 declaration/malformed_pairs; T02/T03 exact MMPP: test_s4b2_rate.py;
T04 zero-count/wait + delayed/tick worlds; exact coverage/missing-law/time cases
in test_s4b2_rate.py (state-dependent coverage needs its own success case);
T05 POSTERIOR; T06 JOINT_MASS/eight report cells; T07/T08 independent rational
information bounds; T09 boundary_evaluation; T10 quantity_cases;
T11/T12/T14 public-roundtrip records; T13 scope_pairs; T15 refinement;
T16 millisecond_declaration/minute_declaration; T17 M0; T18 redelivery/shared clock;
T19 impulse; T20 nonempty preference; T21 wait;
T22 stationary change.
R01 point rates / R02 all-point declarations (old-path comparisons);
R03 fixed-theta M0/mark factorization and analytic Gamma ruler: test_s4b2_rate.py;
R04 zero-Q declaration (matching sources required);
R05 progress / R06 concentration; R07 tools/s4b2_golden.py.
"""

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction as F
import json
from math import factorial
import platform

from sui.action_types import FixedLabel
from sui.clock import FakeClock
from sui.clock_contracts import ClockSource, SOURCE
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind, SequentialIds
from sui.ledger import Ledger, SequentialSalts
from sui.preference import PreferenceView, current, resolve
from sui.rate import (RateBudget, RateContext, RationalInterval, Certificate,
                      CertifiedQuantity, RateEvaluation)
from sui.records import AttemptStarted, Observed, Payload, Producer, Record, Role
from sui.s1_contracts import ATTEMPT
from sui.s4_contracts import BOOT

NS = 1_000_000_000
CANDIDATES = ("read", "wait")
U, GAMMA = F(14, 25), F(1)
STANDARD_BUDGET = RateBudget(F(1, 10**9), 20000, 2000, 20000)
RATE_REPORT = ContractRef("sui.s4b.rate_report", "1")
MEMBRANE = Producer(component="test.s4b2", code_version="1")
# A deferred encoding, not a defect in the complete C1 schema.
CONTRACT_GAPS = {12: "general progress has no model.9 encoding; direct progress_scope deferred (v0.6 C12)"}


def canonical(value):
    """Canonical bytes for both mutable fixtures and public immutable JSON."""
    def plain(item):
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [plain(child) for child in item]
        return item
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def refinement_content(evaluation):
    """Encode public evaluation values under sections 3-10-5/7/8.

    A refinement carries numerical quantities and their proof, not a second
    choice. This fixture encodes only the documented public value fields.
    """
    def rational(value):
        return [value.numerator, value.denominator]

    def interval(value):
        return None if value is None else {
            "lower": rational(value.lower), "upper": rational(value.upper)}

    def certificate(value):
        if value is None:
            return None
        budget = value.budget
        return {"scheme": "sui.s4b.rate_certificate.1",
                "problem_key": value.problem_key,
                "method": {"name": value.method.name, "version": value.method.version},
                "arithmetic": {"name": value.arithmetic.name, "version": value.arithmetic.version},
                "budget": {"tolerance": rational(budget.tolerance),
                           "max_cells": budget.max_cells, "max_terms": budget.max_terms,
                           "max_refinements": budget.max_refinements},
                "trace": value.trace, "enclosures": value.enclosures,
                "residuals": value.residuals}

    def quantity(value):
        return {"status": value.status, "bounds": interval(value.bounds),
                "support": value.support, "log_bounds": interval(value.log_bounds),
                "reason": value.reason, "certificate": certificate(value.certificate)}

    fields = ("expected_cost", "information", "G", "J", "q_star")
    content = {"values": [
        {"candidate": candidate, **{field: quantity(getattr(evaluation, field)[index])
                                    for field in fields}}
        for index, candidate in enumerate(evaluation.candidates)
    ], "certificate": certificate(evaluation.certificate)}
    return json.loads(canonical(content))


def contract(name, version="1"):
    return {"name": name, "version": version}


def named(name, params):
    return {**contract(name), "params": params}


def constant(value):
    return {"kind": "constant", "value": [value, 1]}


def scaled(variable, coefficient=1):
    return {"kind": "scaled_variable", "variable": variable,
            "coefficient": [coefficient, 1]}


def c1_declaration():
    """Exact complete v0.6 example, with fresh mutable values on each call."""
    return {'scheme': 'sui.model.9',
     'contract': {'name': 'sui.s4b.rate_model', 'version': '1'},
     'units': {'time': {'name': 'second', 'seconds': [1, 1]},
               'rate': 'second^-1',
               'record': 'ns',
               'information': 'nat',
               'cost': 'nat'},
     'state_space': {'states': ['0', '1'], 'initial': [[1, 1], [0, 1]]},
     'variables': [{'id': 'r',
                    'domain': {'kind': 'positive-real'},
                    'unit': 'second^-1',
                    'role': 'law',
                    'scope': 'model',
                    'prior': {'name': 'gamma',
                              'version': '1',
                              'params': {'shape': [2, 1], 'rate': [2, 1]}},
                    'generated_by': None},
                   {'id': 'p',
                    'domain': {'kind': 'simplex', 'labels': ['y0', 'y1']},
                    'unit': '1',
                    'role': 'law',
                    'scope': 'model',
                    'prior': {'name': 'dirichlet',
                              'version': '1',
                              'params': {'alpha': [[1, 1], [1, 1]]}},
                    'generated_by': None},
                   {'id': 'state',
                    'domain': {'kind': 'state-path', 'states': ['0', '1']},
                    'unit': '1',
                    'role': 'auxiliary',
                    'scope': 'run',
                    'prior': None,
                    'generated_by': 'state-process'},
                   {'id': 'arrivals',
                    'domain': {'kind': 'event-stream'},
                    'unit': '1',
                    'role': 'auxiliary',
                    'scope': 'run',
                    'prior': None,
                    'generated_by': 'arrival-process'},
                   {'id': 'measurement',
                    'domain': {'kind': 'finite', 'labels': ['y0', 'y1']},
                    'unit': '1',
                    'role': 'auxiliary',
                    'scope': 'attempt',
                    'prior': None,
                    'generated_by': 'probe'},
                   {'id': 'read-completion',
                    'domain': {'kind': 'event'},
                    'unit': '1',
                    'role': 'auxiliary',
                    'scope': 'attempt',
                    'prior': None,
                    'generated_by': 'read-done'},
                   {'id': 'wait-completion',
                    'domain': {'kind': 'event'},
                    'unit': '1',
                    'role': 'auxiliary',
                    'scope': 'attempt',
                    'prior': None,
                    'generated_by': 'wait-done'}],
     'processes': [{'id': 'state-process',
                    'family': {'name': 'finite-ctmc', 'version': '1'},
                    'parents': ['r'],
                    'outputs': ['state'],
                    'params': {'modes': ['fixed'],
                               'initial_mode': 'fixed',
                               'off_diagonal': {'fixed': [[{'kind': 'constant', 'value': [0, 1]},
                                                           {'kind': 'constant', 'value': [0, 1]}],
                                                          [{'kind': 'scaled_variable',
                                                            'variable': 'r',
                                                            'coefficient': [1, 1]},
                                                           {'kind': 'constant', 'value': [0, 1]}]]}}},
                   {'id': 'arrival-process',
                    'family': {'name': 'marked-arrival', 'version': '1'},
                    'parents': ['r', 'state'],
                    'outputs': ['arrivals'],
                    'params': {'state_process': 'state-process',
                               'route': 'c1',
                               'boundary': 'membrane',
                               'rates': {'fixed': [{'kind': 'scaled_variable',
                                                    'variable': 'r',
                                                    'coefficient': [1, 1]},
                                                   {'kind': 'scaled_variable',
                                                    'variable': 'r',
                                                    'coefficient': [2, 1]}]},
                               'marks': None}},
                   {'id': 'probe',
                    'family': {'name': 'shared-probe', 'version': '1'},
                    'parents': ['p', 'state'],
                    'outputs': ['measurement'],
                    'params': {'state_process': 'state-process',
                               'probability_variable': 'p',
                               'labels': ['y0', 'y1']}},
                   {'id': 'read-done',
                    'family': {'name': 'fixed-completion', 'version': '1'},
                    'parents': ['state', 'arrivals', 'measurement'],
                    'outputs': ['read-completion'],
                    'params': {'action': 'read',
                               'duration': [1, 1],
                               'effect': 'identity',
                               'probe': 'probe',
                               'count_record': 'read-report',
                               'constant_notice': None}},
                   {'id': 'wait-done',
                    'family': {'name': 'fixed-completion', 'version': '1'},
                    'parents': ['state'],
                    'outputs': ['wait-completion'],
                    'params': {'action': 'wait',
                               'duration': [1, 1],
                               'effect': 'identity',
                               'probe': None,
                               'count_record': None,
                               'constant_notice': 'done'}}],
     'controls': {'choices': [{'id': 'read',
                               'action': 'read',
                               'reservation': {'kind': 'immediate'},
                               'completion_process': 'read-done',
                               'observation_records': ['read-report']},
                              {'id': 'wait',
                               'action': 'wait',
                               'reservation': {'kind': 'immediate'},
                               'completion_process': 'wait-done',
                               'observation_records': ['wait-report']}],
                  'calendar': []},
     'records': [{'id': 'root-report',
                  'generator': 'arrival-process',
                  'kernel': {'name': 'saturating-count',
                             'version': '1',
                             'params': {'arrival_process': 'arrival-process',
                                        'cap': 3,
                                        'report_at': 'window_end',
                                        'clock': {'name': 'exact', 'version': '1', 'params': {}}}},
                  'experiment': 'root-window',
                  'clock': {'name': 'exact', 'version': '1', 'params': {}},
                  'alphabet': {'kind': 'finite',
                               'values': [{'arrival_count': {'kind': 'exact', 'value': 0},
                                           'outcome': None},
                                          {'arrival_count': {'kind': 'exact', 'value': 1},
                                           'outcome': None},
                                          {'arrival_count': {'kind': 'exact', 'value': 2},
                                           'outcome': None},
                                          {'arrival_count': {'kind': 'at_least', 'value': 3},
                                           'outcome': None}]},
                  'probe': None},
                 {'id': 'read-report',
                  'generator': 'read-done',
                  'kernel': {'name': 'saturating-count',
                             'version': '1',
                             'params': {'arrival_process': 'arrival-process',
                                        'cap': 3,
                                        'report_at': 'window_end',
                                        'clock': {'name': 'exact', 'version': '1', 'params': {}}}},
                  'experiment': 'read',
                  'clock': {'name': 'exact', 'version': '1', 'params': {}},
                  'alphabet': {'kind': 'finite',
                               'values': [{'arrival_count': {'kind': 'exact', 'value': 0},
                                           'outcome': 'y0'},
                                          {'arrival_count': {'kind': 'exact', 'value': 0},
                                           'outcome': 'y1'},
                                          {'arrival_count': {'kind': 'exact', 'value': 1},
                                           'outcome': 'y0'},
                                          {'arrival_count': {'kind': 'exact', 'value': 1},
                                           'outcome': 'y1'},
                                          {'arrival_count': {'kind': 'exact', 'value': 2},
                                           'outcome': 'y0'},
                                          {'arrival_count': {'kind': 'exact', 'value': 2},
                                           'outcome': 'y1'},
                                          {'arrival_count': {'kind': 'at_least', 'value': 3},
                                           'outcome': 'y0'},
                                          {'arrival_count': {'kind': 'at_least', 'value': 3},
                                           'outcome': 'y1'}]},
                  'probe': 'probe'},
                 {'id': 'wait-report',
                  'generator': 'wait-done',
                  'kernel': {'name': 'constant-report', 'version': '1', 'params': {'notice': 'done'}},
                  'experiment': 'wait',
                  'clock': {'name': 'exact', 'version': '1', 'params': {}},
                  'alphabet': {'kind': 'finite', 'values': [{'arrival_count': None, 'outcome': None}]},
                  'probe': None}],
     'coverage': {'intervals': [{'record': 'root-report',
                                 'start': [0, 1],
                                 'end': [1, 1],
                                 'source': {'kind': 'exogenous', 'id': 'root-window'}},
                                {'record': 'read-report',
                                 'start': [1, 1],
                                 'end': [2, 1],
                                 'source': {'kind': 'choice', 'id': 'read'}}],
                  'policy': {'name': 'choice-gated-window',
                             'version': '1',
                             'params': {'left': 'open', 'right': 'closed'}}},
     'order': {'time': 'declared_physical_time',
               'causal': 'declared_stage_position',
               'side': 'explicit',
               'ties': {'name': 'causal-ties', 'version': '1'}},
     'targets': {'laws': ['r', 'p'],
                 'state_positions': [{'record': 'read-report',
                                      'position': {'time': [2, 1],
                                                   'causal_stage': 0,
                                                   'causal_position': 0},
                                      'side': 'post'},
                                     {'record': 'wait-report',
                                      'position': {'time': [2, 1],
                                                   'causal_stage': 0,
                                                   'causal_position': 0},
                                      'side': 'post'}]},
     'measure': {'family': {'name': 'finite-record-counting', 'version': '1'}, 'conditioning': []},
     'certificate_capabilities': [{'name': 'sui.s4b.rate_fixed_mmpp', 'version': '1'},
                                  {'name': 'sui.s4b.rate_c1', 'version': '1'}]}


def c1_model_bytes():
    return canonical(c1_declaration())


def count_cell(count, outcome=None):
    if type(count) is not int or count not in range(4):
        raise ValueError("count must be a bin 0, 1, 2 or saturation bin 3")
    return {"arrival_count": {"kind": "at_least" if count == 3 else "exact", "value": count},
            "outcome": outcome}


def report_content(experiment, count=None, outcome=None, *, boot_ns=0):
    """Raw ns remain run-clock readings, not BOOT-relative seconds."""
    if experiment not in ("root-window", "read", "wait"):
        raise ValueError("unknown experiment")
    if experiment == "read" and outcome not in ("y0", "y1"):
        raise ValueError("read requires one measurement")
    if experiment != "read" and outcome is not None:
        raise ValueError("only read observes a probe")
    if experiment == "wait" and count is not None:
        raise ValueError("wait observes no count, including zero")
    end = boot_ns + (NS if experiment == "root-window" else 2 * NS)
    counted = experiment != "wait"
    cell = count_cell(count, outcome) if counted else {"arrival_count": None, "outcome": None}
    return {"channel": "root-report" if experiment == "root-window" else experiment+"-report",
            "experiment": experiment, "window_start_ns": end-NS if counted else None,
            "window_end_ns": end if counted else None, **cell, "completion_ns": end}


def make_record(clock, ids, kind, body, *, writer=Role.MEMBRANE):
    return Record(id=ids.new(kind), at=clock.now(), writer=writer,
                  producer=MEMBRANE, body=body)


def observation(clock, ids, content, *, contract_ref=RATE_REPORT, route="c1",
                caused_by=None, source_id=None, source_ns=None, received_ns=None):
    return make_record(clock, ids, RefKind.OBSERVATION,
        Observed(route=route, content=Payload.json(content), contract=contract_ref,
                 caused_by=caused_by, source_id=source_id, source_time_ns=source_ns,
                 received_ns=received_ns))


@dataclass
class C1World:
    declaration: bytes
    clock: FakeClock
    ids: SequentialIds
    ledger: Ledger
    boot: Record
    source: Record
    root: Record
    context: RateContext
    resolved: object
    target: FixedLabel
    budget: RateBudget = STANDARD_BUDGET
    candidates: tuple = CANDIDATES
    u: F = U

    @property
    def records(self):
        return (self.boot, self.source, self.root)


def c1_world(n=0, *, boot_ns=0, run_index=0, received_delay_ns=0,
             recorded_delay_ns=0, declaration=None):
    """Three real ledger records, one clock; CID -> observed fact Ref ancestry."""
    declaration = c1_declaration() if declaration is None else deepcopy(declaration)
    run = Ref(RefKind.RUN, "c1")
    clock = FakeClock(run=run, run_index=run_index, mono_ns=boot_ns)
    ids, ledger = SequentialIds("c1"), Ledger(salts=SequentialSalts())
    boot = observation(clock, ids, {}, contract_ref=BOOT, route="membrane", received_ns=boot_ns)
    ledger.accept(boot)
    clock_spec = declaration["records"][0]["clock"]
    provenance = ClockSource(run=run, provider="test.c1", implementation="FakeClock",
        python_version=platform.python_version(), resolution_s=F(1, NS),
        monotonic=True, adjustable=False,
        measurement=ContractRef(clock_spec["name"], clock_spec["version"]))
    source = observation(clock, ids, provenance.as_json(), contract_ref=SOURCE,
                         route="membrane", received_ns=boot_ns)
    ledger.accept(source)
    clock.advance(NS+received_delay_ns+recorded_delay_ns)
    event_ns = boot_ns+NS
    root = observation(clock, ids, report_content("root-window", n, boot_ns=boot_ns),
        source_id=f"c1-root-{n}", source_ns=event_ns, received_ns=event_ns+received_delay_ns)
    ledger.accept(root)
    ancestry = {}
    for entry in ledger.entries():
        cids = ledger.ancestors((entry.cid,)) | {entry.cid}
        ancestry[entry.cid] = frozenset(str(ledger.record(cid).id) for cid in cids
            if ledger.record(cid).body.contract in (BOOT, RATE_REPORT))
    context = RateContext(run=run, now_ns=clock.mono_ns(),
        observed_ns=root.body.received_ns, check_events=({"fact": str(root.id)},),
        fact_ancestors=ancestry, clock_source=source.id)
    return C1World(canonical(declaration), clock, ids, ledger, boot, source, root,
        context, resolve(current(PreferenceView()), None),
        FixedLabel(time_s=F(2), causal_stage=0, causal_position=0, side="post"))


def evaluation_root(world):
    """Public View for evaluation, without the phase-4 persisted Agent path.

    The belief Ref is a query identity; Reading retains the real BOOT, clock
    provenance and root report. No internal RateBelief is manufactured.
    """
    from sui.agent import View
    from sui.rate_entry import read_rate
    from sui.rate_model import rate_model_from_json

    model = rate_model_from_json(world.declaration)
    view = View(model=model, frontier=world.ledger.heads(),
        belief=Ref(RefKind.INTERPRETATION, "evaluation-query"),
        reading=read_rate(model, world.records), now_ns=world.context.now_ns,
        observed_ns=world.context.observed_ns, check_events=world.context.check_events,
        fact_ancestors=world.context.fact_ancestors)
    return view, resolve(current(view.preferences), view)


def command(action):
    """Full command/intent with the planned start independent of prepare time."""
    if action not in CANDIDATES:
        raise ValueError("unknown action")
    return {"choice": action, "action": action, "reservation_rule": {"kind": "immediate"},
            "execution": {"family": contract("immediate-start"),
                          "completion_process": action+"-done",
                          "start": {"time": [1, 1], "causal_stage": 0, "causal_position": 0}},
            "effect": "identity"}


def start_attempt(world, job):
    """job is a JOB Ref; integrated tests must pass prepared.job.id."""
    return make_record(world.clock, world.ids, RefKind.ATTEMPT,
        AttemptStarted(job=job, content=Payload.json({}), contract=ATTEMPT))


def completion_report(world, attempt, action, count=None, outcome=None, *,
                      received_delay_ns=0, recorded_delay_ns=0, source_id="completion-1"):
    end = world.boot.at.mono_ns+2*NS
    recorded = end+received_delay_ns+recorded_delay_ns
    world.clock.advance(recorded-world.clock.mono_ns())
    return observation(world.clock, world.ids,
        report_content(action, count, outcome, boot_ns=world.boot.at.mono_ns),
        caused_by=attempt.id, source_id=source_id, source_ns=end,
        received_ns=end+received_delay_ns)


def tick_declaration():
    declaration = c1_declaration()
    clock = named("tick", {"width_ns": 10, "phase": "uniform", "check": "uniform_in_tick"})
    for record in declaration["records"]:
        record["clock"] = deepcopy(clock)
        if "clock" in record["kernel"]["params"]:
            record["kernel"]["params"]["clock"] = deepcopy(clock)
    return declaration


def four_rate_declaration():
    declaration = c1_declaration()
    rate = declaration["variables"][0]
    ids = ("q01", "q10", "lambda0", "lambda1")
    declaration["variables"] = [{**deepcopy(rate), "id": vid} for vid in ids] + declaration["variables"][1:]
    state, arrival = declaration["processes"][:2]
    state["parents"] = ["q01", "q10"]
    state["params"]["off_diagonal"]["fixed"] = [[constant(0), scaled("q10")], [scaled("q01"), constant(0)]]
    arrival["parents"] = ["lambda0", "lambda1", "state"]
    arrival["params"]["rates"]["fixed"] = [scaled("lambda0"), scaled("lambda1")]
    declaration["targets"]["laws"] = [*ids, "p"]
    return declaration


def independent_arrival_declaration():
    declaration = c1_declaration()
    declaration["variables"].insert(1, {**deepcopy(declaration["variables"][0]), "id": "r_arrival"})
    arrival = declaration["processes"][1]
    arrival["parents"] = ["r_arrival", "state"]
    arrival["params"]["rates"]["fixed"] = [scaled("r_arrival"), scaled("r_arrival", 2)]
    declaration["targets"]["laws"] = ["r", "r_arrival", "p"]
    return declaration


def millisecond_declaration():
    declaration = c1_declaration()
    declaration["units"]["time"] = {"name": "ms", "seconds": [1, 1000]}
    declaration["units"]["rate"] = "ms^-1"
    declaration["variables"][0]["unit"] = "ms^-1"
    declaration["variables"][0]["prior"]["params"]["rate"] = [2000, 1]
    for process in declaration["processes"]:
        if process["family"]["name"] == "fixed-completion":
            process["params"]["duration"] = [1000, 1]
    for window in declaration["coverage"]["intervals"]:
        for edge in ("start", "end"): window[edge][0] *= 1000
    for target in declaration["targets"]["state_positions"]:
        target["position"]["time"][0] *= 1000
    return declaration


def minute_declaration():
    """The same physical C1 in minutes; raw record clocks remain integer ns."""
    declaration = c1_declaration()
    declaration["units"]["time"] = {"name": "min", "seconds": [60, 1]}
    declaration["units"]["rate"] = "min^-1"
    declaration["variables"][0]["unit"] = "min^-1"
    declaration["variables"][0]["prior"]["params"]["rate"] = [1, 30]
    for process in declaration["processes"]:
        if process["family"]["name"] == "fixed-completion":
            duration = F(*process["params"]["duration"])/60
            process["params"]["duration"] = [duration.numerator, duration.denominator]
    for window in declaration["coverage"]["intervals"]:
        for edge in ("start", "end"):
            value = F(*window[edge])/60
            window[edge] = [value.numerator, value.denominator]
    for target in declaration["targets"]["state_positions"]:
        value = F(*target["position"]["time"])/60
        target["position"]["time"] = [value.numerator, value.denominator]
    return declaration


def reduction_declaration(kind):
    declaration = c1_declaration()
    if kind in ("point-rates", "all-point"):
        declaration["variables"][0]["prior"] = named("point", {"value": [1, 1]})
    if kind == "all-point":
        declaration["variables"][1]["prior"] = named("point", {"value": [[1, 2], [1, 2]]})
    if kind == "zero-Q":
        declaration["processes"][0]["parents"] = []
        declaration["processes"][0]["params"]["off_diagonal"]["fixed"] = [
            [constant(0), constant(0)], [constant(0), constant(0)]]
    return declaration


POSTERIOR = ((F(3, 8), F(7, 12), F(2, 3)),
             (F(17, 64), F(15, 17), F(8, 17)),
             (F(5, 32), F(47, 40), F(3, 10)))
JOINT_MASS = (
    ((F(1, 9), F(2, 27)), (F(1, 27), F(7, 108)),
     (F(1, 108), F(19, 486)), (F(7, 2700), F(1799, 48600))),
    ((F(1, 27), F(5, 108)), (F(1, 54), F(1, 18)),
     (F(1, 162), F(125, 2916)), (F(23, 10125), F(331877, 5832000))),
    ((F(1, 108), F(5, 243)), (F(1, 162), F(185, 5832)),
     (F(5, 1944), F(175, 5832)), (F(1453, 1215000), F(266063, 4860000))),
)
ROOT_OVERFLOW = F(13, 64)
Q_READ = tuple(RationalInterval(F(lo, 10**12), F(hi, 10**12)) for lo, hi in (
    (568715423935, 801730166610), (566316269521, 826264248943),
    (560976508051, 824555333240)))
Q_WITHOUT_ARRIVALS = RationalInterval(F(548137238122, 10**12), F(548137238123, 10**12))


def a(n):
    return F(2 ** (n + 1) - 1, n + 1)


def posterior_by_integration(n):
    """Integrate 4r exp(-2r) times §6-4's state-specific likelihoods."""
    def integral(power):
        return F(4 * factorial(power + 1), 4 ** (power + 2) * factorial(n))
    zero, one = integral(n), a(n) * integral(n + 1)
    z = zero + one
    return z, (integral(n + 1) + a(n) * integral(n + 2)) / z, zero / z


def joint_mass_by_formula(n):
    """§6-4 G/T formulas, independent of the literal 24-cell table."""
    cells = tuple((F(4 * factorial(n+k+1), factorial(n)*factorial(k)*6**(n+k+2)),
                   F(4 * factorial(n+k+2), factorial(n)*factorial(k)*6**(n+k+3))
                   * (2**k * a(n) + a(k))) for k in range(3))
    t0 = F(4 * factorial(n+1), factorial(n)*5**(n+2))
    t1 = posterior_by_integration(n)[0] - t0
    return cells + ((t0 - sum(c[0] for c in cells), t1 - sum(c[1] for c in cells)),)


@dataclass(frozen=True)
class FailurePair:
    name: str
    valid: object
    changed: object
    expected: tuple
    status: str = "specified public-boundary expectation"


def malformed_pairs():
    base = c1_declaration()
    changes = []
    def add(name, edit, reason, exception="RateInputError"):
        changed = deepcopy(base)
        edit(changed)
        changes.append(FailurePair(name, canonical(base), canonical(changed), ((exception, reason),)))
    add("unknown-version", lambda d: d["contract"].update(version="999"), "unknown_version")
    add("missing-key", lambda d: d.pop("coverage"), "schema")
    add("unknown-key", lambda d: d.update(unexpected=None), "schema")
    add("nonreduced-rational", lambda d: d["variables"][0]["prior"]["params"].update(shape=[4, 2]), "noncanonical")
    add("bool-rational", lambda d: d["variables"][0]["prior"]["params"].update(shape=[True, 1]), "schema")
    add("missing-probe", lambda d: d["records"][0].pop("probe"), "schema")
    add("clock-disagreement", lambda d: d["records"][0].update(clock=named("tick", {"width_ns":10,"phase":"uniform","check":"uniform_in_tick"})), "shape")
    add("missing-cell", lambda d: d["records"][1]["alphabet"]["values"].pop(), "shape")
    add("duplicate-cell", lambda d: d["records"][1]["alphabet"]["values"].__setitem__(7,deepcopy(d["records"][1]["alphabet"]["values"][0])), "shape")
    add("wait-count", lambda d: d["records"][2]["alphabet"]["values"][0].update(arrival_count={"kind":"exact","value":0}), "shape")
    add("wrong-probe-id", lambda d: d["records"][1].update(probe="arrival-process"), "shape")
    add("wrong-probe-labels", lambda d: d["processes"][2]["params"].update(labels=["y1","y0"]), "shape")
    add("general-progress", lambda d: d["processes"][3].update(family=contract("unregistered-progress")), "missing_kernel", "RateSpecificationMissing")
    changes += [FailurePair("noncanonical",canonical(base),b" "+canonical(base),(("RateInputError","noncanonical"),)),
                FailurePair("duplicate-key",canonical(base),b'{"scheme":"sui.model.9",'+canonical(base)[1:],(("RateInputError","schema"),))]
    return tuple(changes)


def scope_pairs():
    return (FailurePair("four-independent-rates",c1_model_bytes(),canonical(four_rate_declaration()),(("RateIncomplete","rate_prior_scope"),)),
            FailurePair("latent-clock",c1_model_bytes(),canonical(tick_declaration()),(("RateIncomplete","latent_clock"),)),
            FailurePair("deep-tree",None,2*NS,(("RateIncomplete","depth_scope"),)))


def failure_pairs():
    return malformed_pairs()+scope_pairs()+tuple(
        FailurePair(name,U,value,(("RateInputError","invalid_u"),))
        for name,value in (("bool-u",True),("one-u",F(1)),("nan-u",float("nan"))))


def quantity_cases():
    return tuple(CertifiedQuantity(status,bounds,support,None,reason,None)
        for status,bounds,support,reason in (
            ("finite",RationalInterval(F(1,10**100),F(1,10**100)),"positive",None),
            ("finite",RationalInterval(F(0),F(0)),"zero",None),
            ("uncertified",RationalInterval(F(0),F(1)),"unproved","evidence_lower_bound"),
            ("uncertified",None,"unproved","budget"),
            ("positive_infinity",None,"positive",None)))


def boundary_evaluation(*, uncertain=False, budget=STANDARD_BUDGET):
    """Public boundary value fixture, NOT a verified certificate."""
    half=RationalInterval(F(49,100),F(51,100)) if uncertain else RationalInterval(F(1,2),F(1,2))
    zero,one=RationalInterval(F(0),F(0)),RationalInterval(F(1),F(1))
    cert=Certificate("boundary-fixture",ContractRef("sui.s4b.rate_c1","1"),
        ContractRef("rational-series","1"),budget,(),(),())
    q=CertifiedQuantity("finite",zero,"zero",None,None,cert)
    prob=CertifiedQuantity("finite",half,"positive",None,None,cert)
    return RateEvaluation(CANDIDATES,(q,q),(q,q),(q,q),(q,q),(prob,prob),(zero,half,one),cert)
