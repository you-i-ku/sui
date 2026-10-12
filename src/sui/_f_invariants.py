"""Executable event invariants for F-a; not capability declarations.

Paths name authenticated nodes (record/value), linked nodes, or clock labels.
Spec v0.15 §3-10-17 is the source of truth; these rows are checked against it.
Each reference carries an edge kind (§3-10-17-4 T2, §3-10-17-9). Only edges that
use or acquire their target create availability-before-event comparisons; a
clock_provenance or attests_effective edge creates none. Declarations (derived
leaves) have no observed availability clock. UTC sender claims have no order edge.
``numeric`` links form the finite-update input closure; availability/adoption
links deliberately do not. Legacy model.10 generation has its own explicit
profile: its old opaque job payload is not measurement_job/1.
"""
from dataclasses import dataclass, replace
from typing import get_args, get_type_hints

from . import f_contracts as fc
from .clock_contracts import SOURCE
from .s4_contracts import BOOT
from .rate_entry import RATE_REPORT
from .s4b_contracts import RATE_ARRIVAL, RATE_JOB


@dataclass(frozen=True)
class TimeField:
    name: str
    run: str | None
    value: str
    domain: str = 'run_mono_ns'
    nullable: bool = False
    # Derived from the public DTO annotation; independent of null/absent.
    unavailable_paths: tuple[str, ...] = ()
    # Union branches (value DTO class names) where this field has this meaning.
    types: tuple[str, ...] = ()


@dataclass(frozen=True)
class Link:
    name: str
    path: str
    kind: str = 'point'
    contract: object = None
    body: str | None = None
    numeric: bool = True
    profiles: tuple[str, ...] = ('facts', 'legacy')
    context_dependent: bool = False
    # Empty sequences are legal; null/absent is legal only when stated here.
    nullable: bool = False
    event_kind: str | None = None
    category: str | None = None
    # §3-10-17-9 edge kind; see NO_AVAILABILITY_EDGES.
    edge: str = 'uses'
    event_times: tuple[str, ...] = ()
    required_known_times: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventInvariant:
    name: str
    contract: object = None
    body: str | None = None
    decoder: str = 'f'
    times: tuple[TimeField, ...] = ()
    orders: tuple[tuple[str, str], ...] = ()
    links: tuple[Link, ...] = ()
    equals: tuple[tuple[str, str], ...] = ()
    aligns: tuple[tuple[str, str], ...] = ()
    literals: tuple[tuple[str, object], ...] = ()
    required: tuple[str, ...] = ()
    specification_required: tuple[str, ...] = ()
    nonnegative: tuple[str, ...] = ()
    includes: tuple[tuple[str, str], ...] = ()
    inputs: tuple[str, ...] = ()
    boundary: str | None = None
    field: str | None = None
    declaration_times: tuple[str, ...] = ()
    align_context: bool = False
    actual_source: str = 'record.at.mono_ns'
    profiles: tuple[str, ...] = ('facts', 'legacy')
    activated_by: tuple[tuple[str, object], ...] = ()
    evidence: str = 'F:4301,4328,4476; P7 ROADMAP:144'
    # Indexed selectors name individual checks, not entire rows. Unlisted
    # checks are structural; links are revisited for each authenticated context.
    context_checks: tuple[str, ...] = ()
    payload_body: str | None = None
    payload_role: str | None = None
    payload_category: str | None = None
    payload_contracts: tuple[object, ...] = ()
    optional: tuple[str, ...] = ()
    intervals: tuple[tuple[str, str], ...] = ()
    # Separate whole-closure judgment bound. Only FACT records participate;
    # saved clock/context wrappers retain their real reading as the event time.
    scope_time: str | None = 'actual'
    availability: tuple[str, ...] = ()
    availability_contract: object = None
    event_times: tuple[str, ...] = ('actual',)
    available_times: tuple[str, ...] = ('actual',)
    temporal_exception: str | None = None
    # A-21: a broken correspondence between raw/Binding/Plan/generation is an
    # observation_binding_mismatch; other body/outer disagreements proof_mismatch.
    mismatch: str = 'proof_mismatch'
    # V-08/A-20: exact key set of a json-decoded body (missing or extra -> shape).
    keys: tuple[str, ...] = ()

    def __post_init__(self):
        checks = self.context_checks
        if self.align_context:
            checks += ('align_context',)
        if self.boundary is not None:
            checks += ('boundary',)
        object.__setattr__(self, 'context_checks', tuple(dict.fromkeys(checks)))
        if self.body in ('Prediction', 'Interpretation', 'Preference') or self.payload_body in ('Prediction', 'Preference'):
            object.__setattr__(self, 'event_times', ())
            object.__setattr__(self, 'available_times', ())
            object.__setattr__(self, 'temporal_exception',
                'F:4321-4328: mathematical declaration has no observed event/availability clock; '
                'Record.at is storage, not acquisition. Result availability is witnessed by ContentAcquired/ComputationCompleted.')
        if not self.temporal_exception and (not self.event_times or not self.available_times):
            raise ValueError('empty semantic clock policy needs an explicit exception reason')
        if self.contract is not None or self.payload_contracts:
            body = self.payload_body or self.body or 'Observed'
            role, category = {
                'Observed': ('MEMBRANE', 'FACT'),
                'Prediction': ('MODEL', 'PREDICTION'),
                'Decided': ('MODEL', 'FACT'),
                'JobOpened': ('MODEL', 'FACT'),
                'Preference': ('MODEL', 'PREFERENCE'),
            }[body]
            object.__setattr__(self, 'payload_body', body)
            object.__setattr__(self, 'payload_role', self.payload_role or role)
            object.__setattr__(self, 'payload_category', self.payload_category or category)
        for i, pair in enumerate(self.aligns):
            if '$clock_contract' in pair and f'aligns:{i}' not in checks:
                raise ValueError('context clock alignment must declare its phase')

    def depends_on_context(self, kind, index=None):
        return (kind if index is None else f'{kind}:{index}') in self.context_checks


# Shared structural rows also cover older/opaque contracts. They do not guess
# Point strings in payloads. UTC is signed (pre-1970 is legal in S0), untrusted,
# and never ordered against a local Instant or a declaration duration.
STRUCTURAL_INVARIANTS = (
    EventInvariant('Record header (all body kinds)',
        times=(TimeField('at', 'record.at.run', 'record.at.mono_ns'),
               TimeField('wall_utc', None, 'record.at.wall_ns', 'utc_ns', nullable=True)),
        evidence='S0:192-201; F:4308-4310,4476'),
    EventInvariant('Observed', body='Observed',
        # A-20: a legal null receipt is unknown; it is insufficient only where
        # some use needs it (orders then return certificate_incomplete).
        times=(TimeField('received', 'record.at.run', 'record.body.received_ns', nullable=True),
               TimeField('source_utc', None, 'record.body.source_time_ns', 'utc_ns', nullable=True)),
        orders=(('received', 'at'), ('cause.at', 'received')),
        optional=('received',),
        links=(Link('cause', 'record.body.caused_by', 'ref', body='AttemptStarted', nullable=True),),
        align_context=True,
        actual_source='record.body.received_ns',
        evidence='S0:128,192-201,340,343,355; S4a:48; F:4315-4319,4476-4478'),
    EventInvariant('Decided', body='Decided',
        links=(Link('outer_inputs', 'record.body.inputs', 'ref', numeric=False),),
        align_context=True,
        evidence='S0:341; F:4320,4377'),
    # A-03/A-06: basis is what the leaf actually used, so every basis target
    # is in the leaf's real ancestry; a consumer of the leaf then reaches it
    # through the leaf's parents. about only describes and is not a use.
    EventInvariant('Prediction', body='Prediction',
        links=(Link('basis', 'record.body.basis', 'used_ref', numeric=False),),
        evidence='F:4321-4328,4377 (about/basis checked by the named contract); 今の約束 A-03'),
    EventInvariant('JobOpened', body='JobOpened',
        links=(Link('decision', 'record.body.decision', 'ref', body='Decided',
                    profiles=('facts',)),),
        orders=(('decision.at', 'at'),), align_context=True, evidence='S0:342; F:4769,5433'),
    EventInvariant('AttemptStarted', body='AttemptStarted',
        links=(Link('job', 'record.body.job', 'ref', body='JobOpened'),),
        orders=(('job.at', 'at'),), align_context=True, evidence='F:4299,4476,4769-4771,5433'),
    EventInvariant('Preference', body='Preference', payload_contracts=(fc.STYLE,),
        links=(Link('basis', 'record.body.basis', 'used_ref', numeric=False),),
        evidence='F:4763; P7 ROADMAP:144; 今の約束 A-03'),
    # §3-10-17-2 (R21): every legal Body has a row. Intention.target may name a
    # run/individual rather than a record, so it is not a Point link.
    EventInvariant('Intention', body='Intention',
        links=(Link('decided_in', 'record.body.decided_in', 'ref', body='Decided', numeric=False),
               Link('supersedes', 'record.body.supersedes', 'ref', body='Intention', numeric=False, nullable=True),
               Link('via', 'record.body.via', 'ref', body='AttemptStarted', numeric=False, nullable=True)),
        align_context=True, evidence='F §3-10-17-2,-6; records.py:210-237'),
    EventInvariant('Interpretation', body='Interpretation',
        links=(Link('basis', 'record.body.basis', 'used_ref', numeric=False),),
        evidence='F §3-10-17-2 (about/basis checked by the named contract; derived leaf like Prediction); 今の約束 A-03'),
)

EVENT_INVARIANTS = (
    EventInvariant('measurement', fc.MEASUREMENT,
        event_times=('measured', 'actual'),
        times=(TimeField('start', 'value.measurement_interval.clock', 'value.measurement_interval.start_ns'),
               TimeField('end', 'value.measurement_interval.clock', 'value.measurement_interval.end_ns'),
               TimeField('measured', 'value.actual_time.run', 'value.actual_time.time_ns'),
               # §3-10-17-12 D1: the gap of a frame is part of the completed window.
               TimeField('gap_end', 'value.gap.interval.clock', 'value.gap.interval.end_ns', nullable=True)),
        orders=(('start', 'end'), ('end', 'actual'), ('gap_end', 'actual'),
                ('cause.at', 'measured'), ('cause.at', 'end'), ('measured', 'actual'),
                ('routes.effective', 'measured')),
        links=(Link('routes', '@routes', nullable=True, edge='attests_effective'),
               Link('sources', '@sources', contract=SOURCE, profiles=('facts',), edge='clock_provenance'),
               Link('gap_evidence', 'value.gap.evidence', 'ref', nullable=True)),
        optional=('measured', 'gap_end'), intervals=(('measured', 'value.measurement_interval'),),
        boundary='observed', field='/measurement', evidence='F:4410,4476,4767-4773,5432-5434'),
    EventInvariant('coverage/gap/unavailable/unproved', fc.COVERAGE,
        times=(TimeField('start', 'value.interval.clock', 'value.interval.start_ns', nullable=True),
               # The window end is not a generation bound for every branch (A-15):
               # named apart so a Binding's raw.end means a measurement frame only.
               TimeField('interval_end', 'value.interval.clock', 'value.interval.end_ns', nullable=True),
               # A-15: a CoverageClaim is a whole-window claim, observed from its start.
               TimeField('window_start', 'value.interval.clock', 'value.interval.start_ns', nullable=True,
                         types=('CoverageClaim',)),
               TimeField('requested_start', 'value.requested_interval.clock', 'value.requested_interval.start_ns', nullable=True),
               TimeField('requested_end', 'value.requested_interval.clock', 'value.requested_interval.end_ns', nullable=True),
               # §3-10-17-12 D1: CoverageClaim and Gap report a completed window;
               # CoverageUnproved states the current lack of proof (no end bound).
               TimeField('completed_end', 'value.interval.clock', 'value.interval.end_ns', nullable=True,
                         types=('CoverageClaim', 'Gap'))),
        # A-15: a gap/unavailable/unproved report needs only Attempt <= receipt
        # (the Observed row); a whole-window claim needs Attempt <= start.
        orders=(('start', 'interval_end'), ('completed_end', 'actual'),
                ('cause.at', 'window_start'),
                ('requested_start', 'requested_end'), ('requested_end', 'actual'),
                ('routes.effective', 'start')),
        links=(Link('routes', '@routes', nullable=True, edge='attests_effective'),
               Link('sources', '@sources', contract=SOURCE, profiles=('facts',), edge='clock_provenance'),
               Link('evidence', 'value.evidence', 'ref')),
        optional=('start', 'interval_end', 'window_start', 'requested_start', 'requested_end', 'completed_end'),
        boundary='observed', field='/measurement', evidence='F:4410,4476,4767-4773,5432-5434'),
    EventInvariant('ObservationPlan', fc.OBSERVATION_PLAN,
        payload_body='Prediction',
        evidence='F:4410,4771,5432; value/cell/kernel/projection: f_entry:301-400'),
    EventInvariant('ObservationBinding', fc.OBSERVATION_BINDING,
        links=(Link('plan', 'value.plan', 'ref', fc.OBSERVATION_PLAN),
               Link('opportunity', 'value.opportunity', 'ref', body='AttemptStarted'),
               Link('raw', 'value.records', 'ref'),
               Link('generated', 'value.generated_by', 'ref', body='AttemptStarted'),
                Link('derived', '@derived', nullable=True)),
        orders=(('opportunity.at', 'raw.measured'), ('opportunity.at', 'raw.end'),
                ('generated.at', 'raw.measured'), ('generated.at', 'raw.end'),
                ('opportunity.at', 'raw.window_start'), ('generated.at', 'raw.window_start'),
                ('raw.actual', 'actual')),
        equals=(('record.body.caused_by', 'opportunity.record.id'),
                ('raw.record.body.caused_by', 'opportunity.record.id'),
                ('raw.value.route_epoch', 'plan.value.route_epoch')),
        required=('record.body.caused_by', 'raw.record.body.caused_by'),
        optional=('raw.measured', 'raw.end', 'raw.window_start'), mismatch='observation_binding_mismatch',
        boundary='observed', field='/measurement', evidence='F:4377,4410,4476,4769-4771,5432-5437'),
    EventInvariant('measurement_requested', fc.MEASUREMENT_REQUESTED,
        payload_body='Decided',
        links=(Link('plan', 'value.plan', contract=fc.OBSERVATION_PLAN),),
        inputs=('value.plan',), boundary='now', evidence='F:4377,4769-4771,5433'),
    EventInvariant('measurement_job', fc.MEASUREMENT_JOB,
        payload_body='JobOpened', mismatch='observation_binding_mismatch',
        links=(Link('plan', 'value.plan', contract=fc.OBSERVATION_PLAN),
               Link('request', 'record.body.decision', 'ref', fc.MEASUREMENT_REQUESTED)),
        orders=(('request.at', 'at'),),
        equals=(('record.body.step', 'value.step'), ('value.step', 'request.value.step'),
                ('value.plan', 'request.value.plan')),
        evidence='F:4769-4771,5433'),
    EventInvariant('KnowledgeOrigin', fc.KNOWLEDGE_ORIGIN,
        links=(Link('model', 'value.model', contract=fc.MODEL_SOURCE),),
        boundary='now', evidence='F:4379,4411,4760,5431'),
    EventInvariant('ContentAcquired', fc.CONTENT_ACQUIRED,
        event_times=('clock.reading', 'actual'),
        field='/acquisition',
        links=(Link('origin', 'value.origin', contract=fc.KNOWLEDGE_ORIGIN, numeric=False),
               Link('clock', 'value.clock', contract=fc.CLOCK_READING, numeric=False),
               # §今の約束 A-07〜A-12: availability for acquisition depends on
               # what each content is, never on a later adoption.
               Link('contents', 'value.contents', numeric=False, edge='acquires')),
        orders=(('clock.reading', 'actual'),), boundary='now',
        evidence='F:4351-4353,4411,4424-4425,4476'),
    EventInvariant('ComputationRequested', fc.COMPUTATION_REQUESTED,
        payload_body='Decided',
        links=(Link('origin', 'value.origin', contract=fc.KNOWLEDGE_ORIGIN),
               Link('inputs', 'value.inputs', numeric=False), Link('draws', 'value.algorithm_draws', contract=fc.DRAW_FACT)),
        inputs=('value.inputs',), boundary='now', evidence='F:4354-4359,4377,4395,4427,5420-5445'),
    EventInvariant('ComputationResult', fc.COMPUTATION_RESULT,
        payload_body='Prediction',
        links=(Link('request', 'value.request', contract=fc.COMPUTATION_REQUESTED),),
        evidence='F:4360-4362,4377,4397 (about/basis/output replay: calculate)'),
    EventInvariant('ComputationProof', fc.COMPUTATION_PROOF,
        payload_body='Prediction',
        links=(Link('request', 'value.request', contract=fc.COMPUTATION_REQUESTED),
               Link('result', 'value.result', contract=fc.COMPUTATION_RESULT)),
        equals=(('value.request', 'result.value.request'),),
        evidence='F:4363-4367,4377,4397 (about/basis/statement/checker: calculate)'),
    EventInvariant('ComputationCompleted', fc.COMPUTATION_COMPLETED,
        event_times=('finish.reading', 'actual'),
        links=(Link('request', 'value.request', contract=fc.COMPUTATION_REQUESTED, numeric=False),
               Link('result', 'value.result', contract=fc.COMPUTATION_RESULT, numeric=False),
               Link('proofs', 'value.proofs', contract=fc.COMPUTATION_PROOF, numeric=False),
               Link('start', 'value.started_clock', contract=fc.CLOCK_READING, numeric=False),
               Link('finish', 'value.finished_clock', contract=fc.CLOCK_READING, numeric=False)),
        orders=(('request.at', 'start.reading'), ('start.reading', 'finish.reading'),
                ('finish.reading', 'actual')),
        equals=(('value.request', 'result.value.request'), ('value.request', 'proofs.value.request'),
                ('value.result', 'proofs.value.result')),
        boundary='now', evidence='F:4368-4371,4424-4425,4476,5443'),
    EventInvariant('KnowledgeAdopted', fc.KNOWLEDGE_ADOPTED,
        field='/adoption',
        payload_body='Decided',
        links=(Link('origin', 'value.origin', contract=fc.KNOWLEDGE_ORIGIN, numeric=False),
                Link('previous', 'value.previous', contract=fc.KNOWLEDGE_ADOPTED, numeric=False, nullable=True),
               Link('completion', 'value.completion', contract=fc.COMPUTATION_COMPLETED, numeric=False)),
        orders=(('completion.actual', 'at'), ('previous.at', 'at')),
        equals=(('value.origin', 'completion.request.value.origin'),
                ('value.origin', 'previous.value.origin')),
        availability=('completion.value.result', 'completion.value.proofs'),
        availability_contract=fc.CONTENT_ACQUIRED,
        inputs=('value.origin', 'value.previous', 'value.completion'),
        boundary='now', evidence='F:4372-4377,4425-4426 (inputs/acquired chain: histories)'),
    EventInvariant('clock_reading', fc.CLOCK_READING,
        event_times=('reading',), available_times=('reading',),
        scope_time='reading',
        times=(TimeField('reading', 'value.reading.run', 'value.reading.time_ns'),),
        # §3-10-17-3 (R22): the ClockSource receipt is the arrival of a provenance
        # notice, not the start of the clock; run/source alignment is checked instead.
        links=(Link('source', 'value.source', contract=SOURCE, edge='clock_provenance'),),
        orders=(('reading', 'actual'),),
        aligns=(('value.reading.run', 'source.value.run'),),
        evidence='F:4438,4448-4451,4476-4478'),
    EventInvariant('context', fc.CONTEXT_OBSERVED,
        event_times=('judgment.reading',), available_times=('judgment.reading',),
        scope_time='judgment.reading',
        links=(Link('origin', 'value.knowledge_origin', contract=fc.KNOWLEDGE_ORIGIN, numeric=False),
               Link('observation', 'value.observation_reading', contract=fc.CLOCK_READING, numeric=False),
               Link('judgment', 'value.judgment_reading', contract=fc.CLOCK_READING, numeric=False),
                Link('events', 'value.check_events.record', numeric=False),
                Link('clock_events', 'value.check_events', contract=fc.CLOCK_READING,
                     numeric=False, event_kind='clock', category='FACT'),
                Link('fact_events', 'value.check_events', numeric=False,
                     event_kind='fact', category='FACT', event_times=('observation.reading',))),
        orders=(('observation.reading', 'judgment.reading'), ('judgment.reading', 'actual'),
                ('clock_events.reading', 'judgment.reading'),
                ('fact_events.actual', 'observation.reading')),
        aligns=(('observation.source.value.measurement', 'judgment.source.value.measurement'),
                ('clock_events.source.value.measurement', 'judgment.source.value.measurement')),
        evidence='F:4452-4478 (ordered check events: check_events)'),
    EventInvariant('RouteApplied', fc.ROUTE_CONFIG,
        event_times=('effective', 'actual'),
        context_checks=('aligns:0',),
        times=(TimeField('effective', 'value.effective_from.run', 'value.effective_from.time_ns'),),
        links=(Link('decision', 'value.config.decision', 'ref', nullable=True),
                Link('execution', 'value.config.execution', 'ref', nullable=True), Link('evidence', 'value.evidence', 'ref')),
        aligns=(('value.config.clock_contract', '$clock_contract'),),
        orders=(('effective', 'actual'),), evidence='F:4476,5434; f:832-845; f_entry:194-200'),
    EventInvariant('BOOT', BOOT,
        decoder='json',
        literals=(('value', {}), ('record.body.route', 'membrane'), ('record.body.caused_by', None)),
        evidence='F:4438,4760,5434; s4_contracts:13-18'),
    EventInvariant('ClockSource', SOURCE,
        context_checks=('aligns:1',),
        # A-12/A-18: a provenance notice, judged by its role, not by the fixed
        # problem's judgment bound (a late ClockSource notice is legal).
        scope_time=None,
        decoder='clock_source',
        links=(Link('boot', '@boot', contract=BOOT, profiles=('facts',)),),
        # A-20: measurement=null is legal until a used reading needs the
        # contract (clock() then returns missing_contract).
        aligns=(('value.run', 'record.at.run'), ('value.measurement', '$clock_contract')),
        optional=('value.measurement',),
        declaration_times=('resolution_s is rational seconds, not a run timestamp',),
        evidence='F:4438,4760,5434; clock_contracts:10-16'),
    EventInvariant('rate_report', RATE_REPORT,
        event_times=('completion', 'actual'),
        decoder='json',
        keys=('channel', 'experiment', 'window_start_ns', 'window_end_ns', 'arrival_count', 'outcome', 'completion_ns'),
        # A-20: constant/wait reports legally carry a null window.
        times=(TimeField('window_end', 'record.at.run', 'value.window_end_ns', nullable=True),
               TimeField('completion', 'record.at.run', 'value.completion_ns')),
        orders=(('window_end', 'actual'), ('completion', 'actual'), ('cause.at', 'completion')),
        required=('value.completion_ns',), optional=('window_end',),
        boundary='observed', evidence='F:4476-4480; C1 contract-specific source clock checks remain in f_entry'),
    EventInvariant('rate_arrival', RATE_ARRIVAL, decoder='json',
        keys=('process', 'mark', 'event_ns'),
        evidence='今の約束 V-08 (rate_arrival の欄); model.9 meaning: rate_entry'),
    EventInvariant('rate_job', RATE_JOB, decoder='json', payload_body='JobOpened',
        keys=('choice', 'action', 'reservation_rule', 'execution', 'effect'),
        evidence='今の約束 V-08 (rate_job の欄); model.9 meaning: rate_entry'),
    EventInvariant('draw_fact', fc.DRAW_FACT,
        evidence='F:4542,4764 (law/request/value: read_draw; selection parents: after problem)'),
    EventInvariant('model_source', fc.MODEL_SOURCE,
        payload_body='Prediction',
        declaration_times=('model.11 document.units.duration=ns; kernel.outcomes.elapsed_ns is a duration; older models retain their own declared units; model parser validates, no Instant conversion',),
        evidence='F:4531,5431 (document digest distinct from Point)'),
    EventInvariant('candidate_declaration', fc.CANDIDATE_DECLARATION,
        payload_body='Prediction',
        links=(Link('model', 'value.model', contract=fc.MODEL_SOURCE),
               Link('basis', 'value.generation.basis'), Link('draws', 'value.generation.draws', contract=fc.DRAW_FACT)),
        evidence='F:4531-4542 (basis/draw/generator/continuation: _Compiler)'),
    EventInvariant('quantity_declaration', fc.QUANTITY_DECLARATION,
        payload_body='Prediction',
        links=(Link('provenance', 'value.provenance', nullable=True), Link('result', 'value.result', nullable=True)),
        evidence='F:4399; quantity factory authenticates evaluation/proof/unit'),
    EventInvariant('limit_declaration', fc.LIMIT_DECLARATION,
        payload_body='Prediction',
        declaration_times=('process/cost sequence index units belong to their declared contracts, not Record.at',),
        evidence='F:4873 (declared process times; no local clock conversion; limit verifier)'),
    EventInvariant('predicate_declaration', fc.PREDICATE,
        payload_body='Prediction',
        evidence='F:4882 (declaration/capability/quantity binding: predicate factory)'),
    EventInvariant('math_artifact/1 (legacy envelope)', fc.MATH_ARTIFACT, decoder='json',
        evidence='F:4873-4885 (static saved mathematical claim; typed replay validates all input/calls/output)'),
    EventInvariant('math_artifact/2', fc.MATH_ARTIFACT_V2, decoder='json',
        payload_body='Prediction',
        evidence='F:4873-4885; f_facts:237-245,730 (quantity result Point and typed mathematical replay; no new measurement)'),
)

# These cross-node constraints apply to the new primary generation contract.
# Legacy bytes carry opaque opportunity jobs; they retain chronology, raw/cause
# and ancestor checks but do not acquire a made-up measurement_requested body.
GENERATION_INVARIANT = EventInvariant('primary generation (facts profile)',
    profiles=('facts',),
    activated_by=(('opportunity.job.record.body.contract', fc.MEASUREMENT_JOB),
                  ('generated.job.record.body.contract', fc.MEASUREMENT_JOB)),
    equals=(('opportunity.job.record.body.contract', '$measurement_job'),
            ('generated.job.record.body.contract', '$measurement_job'),
            ('plan.cid', 'opportunity.job.value.plan'),
            ('plan.cid', 'generated.job.value.plan'),
            ('value.step', 'opportunity.job.value.step'),
            ('value.step', 'generated.job.value.step')),
    required=('opportunity.job.value.plan', 'generated.job.value.plan'),
    includes=(('value.opportunity', 'value.generated_by'),),
    mismatch='observation_binding_mismatch',
    evidence='F:4769-4771,5432-5437; P7 ROADMAP:144')

# Relations between separate events that cannot be encoded as a single owner
# edge. Call sites supply only authenticated labels/times to the same evaluator.
RELATION_INVARIANTS = (
    EventInvariant('boundaries', orders=(('observed', 'now'),),
                   context_checks=('orders:0',),
                   evidence='F:4476'),
    EventInvariant('generation before acquisition', orders=(('finish', 'acquired'),),
                   evidence='F:4425,4476'),
    EventInvariant('available at adoption', orders=(('reading', 'adopted'), ('received', 'adopted')),
                   evidence='F:4425 (acquisition must also be an actual ancestor)'),
    EventInvariant('event receipt', orders=(('moment', 'actual'),), evidence='F:4476'),
    EventInvariant('event boundary', orders=(('actual', 'boundary'),),
                   context_checks=('orders:0',), evidence='F:4476'),
    EventInvariant('reference saved order', orders=(('dependency', 'owner'),), evidence='F:4301,4476'),
    EventInvariant('reference availability', orders=(('available', 'event'),),
                   evidence='F:4351-4353,4411,4476; S0:128,343,355'),
    EventInvariant('clock/context alignment', aligns=(('run', 'context_run'), ('contract', 'context_contract')),
                   context_checks=('aligns:0', 'aligns:1'),
                   evidence='F:4476'),
    EventInvariant('clock check event', orders=(('reading', 'now'),),
                   context_checks=('orders:0',), evidence='F:4463-4476'),
)


def public_unavailable_fields():
    """Inventory public DTO annotations, without inferring union/null semantics."""
    from . import f as core
    from .f_entry import _wire_types
    schemas, public = _wire_types()
    classes = set(public.values()) | set(schemas.values())
    # Nested public DTOs (including ReservationDue) are reached by annotation.
    pending = list(classes)
    inventory = []
    while pending:
        cls = pending.pop()
        if not isinstance(cls, type) or not hasattr(cls, '__dataclass_fields__'):
            continue
        for name, annotation in get_type_hints(cls).items():
            members = get_args(annotation) or (annotation,)
            if core.Unavailable in members:
                inventory.append((cls.__name__, name))
            for member in members:
                for child in (get_args(member) or (member,)):
                    if isinstance(child, type) and hasattr(child, '__dataclass_fields__') and child not in classes:
                        classes.add(child)
                        pending.append(child)
    return tuple(sorted(set(inventory)))


def _unknown_paths(schema, path):
    """Find an annotated Unavailable union along a value clock selector."""
    from . import f as core
    current = (schema,)
    prefix = 'value'
    paths = []
    for part in path.split('.')[1:]:
        children = []
        prefix += '.' + part
        for cls in current:
            if not isinstance(cls, type): continue
            annotation = get_type_hints(cls).get(part)
            if annotation is None: continue
            members = get_args(annotation) or (annotation,)
            if core.Unavailable in members: paths.append(prefix)
            children.extend(m for m in members if isinstance(m, type) and m is not core.Unavailable)
        current = tuple(children)
    return tuple(paths)


def _public_time_types(rows):
    from .f_entry import _wire_types
    schemas, _ = _wire_types()
    return tuple(replace(row, times=tuple(replace(t, unavailable_paths=
        _unknown_paths(schemas[row.contract], t.value))
        if row.contract in schemas and t.value.startswith('value.') else t
        for t in row.times)) for row in rows)


EVENT_INVARIANTS = _public_time_types(EVENT_INVARIANTS)
# Used routes need a known activation instant. Unused routes retain a legal
# unknown activation reading; this requirement belongs to the consuming edge.
EVENT_INVARIANTS = tuple(replace(row, links=tuple(replace(link,
    required_known_times=('effective',)) if link.path == '@routes' else link
    for link in row.links)) for row in EVENT_INVARIANTS)
PUBLIC_UNAVAILABLE_FIELDS = public_unavailable_fields()

# §3-10-17-9 edge kinds that create no availability-before-event comparison.
NO_AVAILABILITY_EDGES = frozenset({'describes', 'clock_provenance', 'attests_effective'})
EDGE_KINDS = NO_AVAILABILITY_EDGES | {'uses', 'acquires', 'adopts'}


def _check_totality():
    """§3-10-17-2/-8 (R21): every legal Body has exactly one structural row and
    every link names a known edge kind; found at import, not after an input."""
    from .records import Body
    bodies = {cls.__name__ for cls in get_args(Body)}
    rows = [r.body for r in STRUCTURAL_INVARIANTS if r.body is not None]
    if sorted(rows) != sorted(bodies):
        raise ValueError(f'structural rows {sorted(rows)} != Body {sorted(bodies)}')
    for row in (*STRUCTURAL_INVARIANTS, *EVENT_INVARIANTS):
        for link in row.links:
            if link.edge not in EDGE_KINDS:
                raise ValueError(f'{row.name}.{link.name}: unknown edge kind {link.edge}')


_check_totality()
