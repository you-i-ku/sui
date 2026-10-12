"""Independent F-a authentication inventory (2026-10-11 contract).

Authority: specs/関所F_今の約束.md, especially V-07..10, A-01..21,
C-01 and lines 595..652. No implementation rule table is imported.
Rows enumerate the specification, not the fixtures that happen to pass.
``test_gate_f_auth.coverage_report()`` reports unmatched rows. This inventory
reports explicit representatives, constructor boundaries and remaining gaps.
Representation of presence/identity never implies representation of a temporal
or use-dependent rule. Public declaration drift remains a failing obligation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

SPEC = "specs/関所F_今の約束.md"
ALL_ENTRIES = ("EN", "EH", "EC", "EP", "EF", "EL", "EB", "ED", "ER")
FINITE = ("EN", "EH", "EP", "EF", "ED", "ER")
CONTEXT = ("EN", "EH", "EC", "EP", "EF", "EB", "ED", "ER")


@dataclass(frozen=True)
class Contract:
    name: str
    version: str
    body: str
    branches: tuple[tuple[str, str], ...]
    entries: tuple[str, ...]
    line: int
    role: str = "MODEL"
    category: str = "PREDICTION"
    exclusion: str = ""


def contract(name, body, fields, line, *, entries=FINITE, role=None,
             category=None, branches=None, version="1", exclusion=""):
    return Contract(name if name.startswith("sui.") else "sui.f." + name,
                    version, body, tuple(branches or (("default", fields),)),
                    entries, line, role or ("MEMBRANE" if body == "Observed" else "MODEL"),
                    category or ("FACT" if body in ("Observed", "Decided", "JobOpened")
                                 else "PREFERENCE" if body == "Preference" else "PREDICTION"),
                    exclusion)


# A trailing ? means a required *key* whose selected value can be null.
# [] describes a sequence, not optional presence. Nested leaves are explicit.
CONTRACTS = (
    contract("model_source", "Prediction", "document", 57, entries=CONTEXT),
    contract("candidate_declaration", "Prediction", "model input_order[] measure? generation.generator.name generation.generator.version generation.args generation.basis[] generation.draws[] continuation.after[].candidate continuation.after[].policy?", 58),
    contract("knowledge_origin", "Observed", "model", 59, entries=CONTEXT),
    contract("content_acquired", "Observed", "origin contents[] clock", 60),
    contract("computation_requested", "Decided", "origin purpose method.name method.version args inputs[] algorithm_draws[] output_contract.name output_contract.version", 61,
             branches=tuple((p, "origin purpose method.name method.version args inputs[] algorithm_draws[] output_contract.name output_contract.version") for p in ("belief", "query", "certificate"))),
    contract("computation_result", "Prediction", "request output.contract.name output.contract.version output.value", 62),
    contract("computation_proof", "Prediction", "", 63, branches=tuple((p, "request result role statement.contract.name statement.contract.version statement.value checker.name checker.version checker.args") for p in ("normalization", "query"))),
    contract("computation_completed", "Observed", "request result proofs[] started_clock finished_clock", 64),
    contract("knowledge_adopted", "Decided", "origin previous? completion", 65),
    contract("clock_reading", "Observed", "source reading.run reading.time_ns", 66, entries=CONTEXT),
    contract("context_observed", "Observed", "knowledge_origin observation_reading judgment_reading check_events[]", 67, entries=CONTEXT,
             branches=(("empty", "knowledge_origin observation_reading judgment_reading check_events[]"),
                       ("fact", "knowledge_origin observation_reading judgment_reading check_events[].kind check_events[].record"),
                       ("clock", "knowledge_origin observation_reading judgment_reading check_events[].kind check_events[].record"))),
    contract("draw_fact", "Observed", "", 68, entries=CONTEXT,
             branches=tuple((p, "generator.name generator.version stream_id request.purpose request.context_key request.ordinal request.law.name request.law.version request.args value") for p in ("candidate_generation", "selection", "reservation", "algorithm"))),
    contract("measurement_requested", "Decided", "plan step", 69),
    contract("measurement_job", "JobOpened", "plan step", 70),
    contract("observation_plan", "Prediction", "model_ref route_epoch measurement_contract.name measurement_contract.version kernel.name kernel.version kernel.args cells[].id cells[].observation.kind cells[].observation.value cells[].outcomes[] time_projection.name time_projection.version generation_contract.name generation_contract.version", 107),
    contract("observation_binding", "Observed", "plan records[] opportunity step cell slots[].slot slots[].measurement.origin slots[].measurement.route_epoch slots[].measurement.sample_seq slots[].measurement.component generated_by[] derived_from[].origin derived_from[].route_epoch derived_from[].sample_seq derived_from[].component", 110),
    contract("measurement", "Observed", "", 93, branches=(
        ("clock/value", "route_epoch sample_seq measurement_id.origin measurement_id.route_epoch measurement_id.sample_seq measurement_id.component measurement_interval.clock measurement_interval.start_ns measurement_interval.end_ns measurement_interval.closure actual_time.kind actual_time.value.run actual_time.value.time_ns value.kind value.value quality.contract.name quality.contract.version quality.value gap? source_cursor.contract.name source_cursor.contract.version source_cursor.value"),
        ("unavailable-time", "actual_time.kind actual_time.value.reason actual_time.value.basis[]"),
        ("unavailable-value", "value.kind value.value.reason value.value.basis[]"),
        ("gap", "gap.route_epoch gap.sequence_range[] gap.interval.clock gap.interval.start_ns gap.interval.end_ns gap.interval.closure gap.reason gap.evidence[]"))),
    contract("measurement_run", "Observed", "", 74, exclusion="V-08: adopted codec and reversible columns are unspecified; do not invent a codec"),
    contract("coverage", "Observed", "", 96, branches=(
        ("claim", "kind value.route_epoch value.interval.clock value.interval.start_ns value.interval.end_ns value.interval.closure value.kind value.contract.name value.contract.version value.evidence[]"),
        ("gap", "kind value.route_epoch value.sequence_range[] value.interval.clock value.interval.start_ns value.interval.end_ns value.interval.closure value.reason value.evidence[]"),
        ("measurement_unavailable", "kind value.route_epoch value.requested_interval.clock value.requested_interval.start_ns value.requested_interval.end_ns value.requested_interval.closure value.reason value.evidence[]"),
        ("coverage_unproved", "kind value.route_epoch value.interval.clock value.interval.start_ns value.interval.end_ns value.interval.closure value.missing_contracts[] value.evidence[]"))),
    contract("route_config", "Observed", "", 76, entries=CONTEXT, branches=tuple((p, "config.route_epoch config.origin config.version config.sampling_contract.name config.sampling_contract.version config.clock_contract.name config.clock_contract.version config.loss_contract.name config.loss_contract.version config.args config.decision? config.execution? effective_from.kind effective_from.value execution? evidence[]") for p in ("bootstrap", "selected")) + (("unavailable-effective", "effective_from.kind effective_from.value.reason effective_from.value.basis[]"),)),
    contract("sui.s4.boot", "Observed", "", 77, entries=CONTEXT),
    contract("sui.clock.source", "Observed", "run provider implementation python_version resolution_s monotonic adjustable measurement?", 78, entries=CONTEXT),
    contract("sui.s4b.rate_report", "Observed", "", 79, entries=("EC", "EF", "EB", "ED", "ER"), branches=(
        ("count", "channel experiment window_start_ns window_end_ns arrival_count outcome? completion_ns"),
        ("constant", "channel experiment window_start_ns? window_end_ns? arrival_count? outcome completion_ns"),
        ("wait", "channel experiment window_start_ns? window_end_ns? arrival_count? outcome? completion_ns"))),
    contract("sui.s4b.rate_arrival", "Observed", "process mark? event_ns", 80, entries=("EC", "EF", "EB", "ED", "ER")),
    contract("sui.s4b.rate_job", "JobOpened", "choice action reservation_rule execution effect", 81, entries=("EC", "EF", "EB", "ED", "ER")),
    contract("style", "Preference", "kind scope.name scope.version scope.H_ns? gamma", 82, entries=("EN", "EF", "EB", "ED", "ER")),
    contract("sui.s4d.preference", "Preference", "kind H_ns? gamma", 82, entries=("EN", "EF", "EB", "ED", "ER")),
    contract("quantity_declaration", "Prediction", "", 83, branches=(
        ("rational_constant", "kind value unit provenance[]"),
        ("evaluation", "kind result field candidate?"))),
    contract("predicate", "Prediction", "name version args", 84, entries=FINITE+("EL",)),
    contract("limit_declaration", "Prediction", "", 85, entries=("EL", "EF", "ED", "ER"), branches=(
        ("blank", "process.name process.version process.args.index_origin observations.name observations.version observations.args information_target cost.kind scope.name scope.version scope.H_ns? proof?"),
        ("prefix_log_loss", "cost.kind cost.law.name cost.law.version cost.law.args.index_origin"))),
    *(contract("math_artifact", "Prediction" if v == '2' else 'wire envelope', "contract.name contract.version compiler.name compiler.version input.kind input.value environment.reader_view_key environment.registry_key calls[].op calls[].args output claim.type claim.value", 86, version=v,
        entries=("EP", "EF", "ED", "ER") if v == '2' else ('ER',),
        exclusion='' if v == '2' else 'V-08 specifies raw Prediction storage for /2 only; /1 has a preserved wire codec/replay, not an invented raw Body') for v in ("1", "2")),
)

BODY_FIELDS = {
    "Observed": "route content contract caused_by? source_id? source_time_ns? received_ns?",
    "Decided": "inputs[] content contract",
    "JobOpened": "decision step content contract",
    "AttemptStarted": "job content contract",
    "Intention": "target operation status decided_in supersedes? via? content contract",
    "Prediction": "target about[] basis[] content contract",
    "Interpretation": "about[] basis[] content contract",
    "Preference": "basis[] content contract",
}


@dataclass(frozen=True)
class AuthTarget:
    id: str
    body: str
    contract: str
    version: str
    branch: str
    field: str
    role: str
    domain: str
    run: str
    owner: str
    presence: str
    edge_use: str
    evidence: str
    consumer: str
    rules: tuple[str, ...]
    entries: tuple[str, ...]
    negative: str
    nearest_legal: str
    not_applicable: str
    source: str
    writer_category: str = "as declared by Body/contract"
    representative: str = "self; see REPRESENTATIVES for rule/use/entry-specific folding"
    row_kind: str = "field"
    relation_kind: str = ""
    # (entry, public surface/use, outcome for the numerical/relational bad member).
    # Entry membership alone does not mean the same semantic use at that entry.
    entry_uses: tuple[tuple[str, str, str], ...] = ()
    entry_rules: tuple[tuple[str, tuple[str, ...]], ...] = ()
    entry_members: tuple[tuple[str, str, str, str], ...] = ()
    entry_exclusions: tuple[tuple[str, str, str], ...] = ()
    mutation_checks: tuple[int, ...] = ()
    discrimination_limits: str = ""


def target(body, name, version, branch, field, entries, line, *, nullable=False,
           role="structural", rules=("A-01", "A-20", "A-21"), exclusion="",
           use="authenticate selected field", evidence="Record/CID/header/seal",
           consumer="entry's required closure", negative="remove required key",
           legal="same record with the key present"):
    leaf = field.rsplit(".", 1)[-1].replace("[]", "")
    domain, run = "not-time", "not-applicable"
    if leaf in ("mono_ns", "received_ns", "time_ns", "event_ns", "completion_ns", "start_ns", "end_ns", "window_start_ns", "window_end_ns"):
        domain, run = "M", "owner run / declared interval clock; A-05/A-12"
    if leaf in ("wall_ns", "source_time_ns"):
        domain, run = "U", "no cross-domain M comparison (rate_report D2 exception)"
    if leaf == "H_ns": domain, run = "D", "none"
    time_role = 'not-time'
    if domain == 'M':
        time_role = ('r' if leaf == 'received_ns' else 'i' if leaf in ('start_ns', 'end_ns', 'window_start_ns', 'window_end_ns')
                     else ('e' if body in ('Decided', 'JobOpened', 'AttemptStarted', 'Intention') else 's') if leaf == 'mono_ns'
                     else 'e (clock reading: role determined by its consumer a/o/j/g)')
    elif domain == 'U':
        time_role = 'u' if leaf == 'source_time_ns' else 's (wall reference only)'
    elif domain == 'D':
        time_role = 'd'
    if name == 'At' and field == 'time_ns':
        time_role = 'p'
    if name == 'ReservationDue' and field in ('due', 'detected', 'execution'):
        time_role = 'p' if field == 'due' else 'e'
        domain = {'due': 'M | Unavailable', 'detected': 'M', 'execution': 'M | null'}[field]
        run = 'selected ClockReading.run; no comparison for Unavailable/null'
    edge = leaf in ("origin", "model", "plan", "clock", "request", "result", "completion", "previous", "source", "records", "inputs", "proofs", "basis", "evidence", "generated_by", "opportunity", "decision", "job", "caused_by", "decided_in", "supersedes", "via", "record", "provenance", "draws", "contents", "observation_reading", "judgment_reading", "knowledge_origin", "started_clock", "finished_clock")
    more_rules = []
    if edge:
        use += "; typed identity/dependency (not automatic temporal use)"
        more_rules += ['A-03', 'A-06']
        evidence += '; resolve every typed Ref/Point and retain actual parents'
    if field.startswith('at.'):
        more_rules += ['A-05', 'V-04']
    if leaf == 'received_ns':
        more_rules += ['A-07', 'A-08', 'A-13']
        use, consumer = 'notification body use', 'using Decided/Job/Attempt/Intention event'
        evidence += '; r <= consumer event, r <= s'
    if leaf == 'source_time_ns': more_rules += ['A-12', 'V-04']
    if name == 'sui.f.content_acquired':
        more_rules += ['A-07', 'A-09', 'A-10', 'A-11', 'A-12', 'A-16']
        use, consumer = 'origin acquisition; evidence selected by target kind', 'acquisition clock a; later notification user separate'
        evidence += '; raw r / result-proof g / static s_D / notification r (distinct witnesses)'
    if name == 'sui.f.computation_completed':
        more_rules += ['A-10', 'A-13']
        evidence += '; started <= finished g <= notification r <= s'
    if name == 'sui.f.knowledge_adopted':
        more_rules += ['A-04', 'A-10', 'A-16']
        use, consumer = 'adoption (not mere reference)', 'adopted Record.at'
        evidence += '; same-origin acquired result/proof and completion notification are actual ancestors'
    if name in ('sui.f.computation_requested', 'sui.f.computation_result', 'sui.f.computation_proof'):
        more_rules += ['A-04', 'A-06', 'A-10']
    if name == 'sui.f.context_observed':
        more_rules += ['A-17', 'A-19']
        evidence += '; own o/j and check_events order (no later context repair)'
    if name == 'sui.f.clock_reading':
        more_rules += ['A-07', 'A-12', 'A-13']
        use = 'past reading as witness / notification contents as acquired input (separate uses)'
    if name == 'sui.f.measurement':
        more_rules += ['A-13', 'A-14', 'A-15', 'A-18']
        evidence += '; interval, source alignment, generating Attempt, receipt r and fixed o'
    if name == 'sui.f.coverage':
        if branch != 'coverage_unproved': more_rules += ['A-14']
        more_rules += ['A-15']
        evidence += ('; report cause <= r; future end allowed, not completed coverage'
                     if branch == 'coverage_unproved' else
                     '; finished interval end <= r; report/window classification per A-15')
    if name == 'sui.f.observation_binding':
        more_rules += ['A-04', 'A-15', 'A-18']
        evidence += '; every generator -> Job -> request; plan and step; all raw records'
    if name in ('sui.f.measurement_requested', 'sui.f.measurement_job'):
        more_rules += ['A-04', 'A-15']
    if name == 'sui.f.route_config': more_rules += ['A-06', 'A-13']
    if name in ('sui.f.model_source', 'sui.f.candidate_declaration', 'sui.f.observation_plan', 'sui.f.quantity_declaration', 'sui.f.predicate', 'sui.f.limit_declaration'):
        more_rules += ['A-11']
    if leaf in ('version', '$contract'): more_rules += ['V-08']
    return AuthTarget(f"{name}/{version}:{body}:{branch}:{field}", body, name, version,
        branch, field, time_role, domain, run, f"{body} Record / {name}/{version}",
        "required-key, nullable-value" if nullable else "required selected-branch key",
        use, evidence, consumer, tuple(dict.fromkeys((*rules, *more_rules))), entries,
        negative, legal, exclusion or "unselected union branches; absent legal null has no edge; entry must reach this object",
        f"{SPEC}:{line}", role)


def _inventory():
    for body, fields in BODY_FIELDS.items():
        branches = ("confirmed", "withdrawn", "executed") if body == "Intention" else ("default",)
        for branch in branches:
            for fld in ("id at.run at.run_index at.seq at.mono_ns at.wall_ns writer producer.component producer.code_version producer.state? schema " + fields).split():
                yield target(body, "Record", "3", branch, fld.rstrip("?"), ALL_ENTRIES, 38,
                             nullable=fld.endswith("?"), rules=("A-01", "A-20", "A-21", "V-04"),
                             negative='same CID with this Record column changed (A-01); missing-key A-20 obligation is separate',
                             legal='the original full Record, header and sealed payload agree')
            for fld in ('producer.state.lineage', 'producer.state.revision', 'contract.name', 'contract.version', 'content.media_type', 'content.data'):
                yield target(body, 'Record', '3', branch+'-present', fld, ALL_ENTRIES, 38,
                             rules=('A-01', 'A-20', 'A-21'),
                             negative='same CID with this Record column changed (A-01); missing-key A-20 obligation is separate',
                             legal='the original full Record, header and sealed payload agree')
    for c in CONTRACTS:
        # The whole contract has its own name/version row, including empty bodies.
        yield target(c.body, c.name, c.version, "contract", "$contract", c.entries, c.line,
                     role=f"{c.role}/{c.category}", rules=("A-01", "V-08", "A-21"),
                     exclusion=c.exclusion, negative="same known name, undeclared version",
                     legal="declared exact name and version")
        for branch, fields in c.branches:
            for fld in fields.split():
                yield target(c.body, c.name, c.version, branch, fld.rstrip("?"), c.entries, c.line,
                             nullable=fld.endswith("?"), role=f"{c.role}/{c.category}",
                             rules=("A-01", "A-20", "A-21", "V-03"), exclusion=c.exclusion)


PRIMARY_INPUTS = (
    ('FFactsRequest', 'fixed_parents[] model candidates preferences[] scope.name scope.version scope.H_ns? scope.source? context method.name method.version', ('EN', 'ER'), 375),
    ('FPreflightFacts', 'fixed_parents[] model? required_records[] required_capabilities[].kind required_capabilities[].ref.name required_capabilities[].ref.version required_capabilities[].implementation_required', ('EF', 'ER'), 378),
    ('FLegacyBridgeRequest', 'fixed_parents[] model context preferences[] candidates[] adapter.name adapter.version', ('EB', 'ER'), 380),
    ('histories_request', 'fixed_parents[] model_ref context_ref registry budget', ('EH', 'EC'), 348),
    ('predicate_request', 'fixed_parents[] model_ref context_ref predicate_ref quantity_refs[] registry budget', ('EP',), 350),
    ('limit_request', 'declaration_ref registry budget', ('EL',), 352),
    ('draw_request', 'prepared draw_record_ref reader budget', ('ED',), 347),
    ('At', 'run time_ns source', ('EX',), 88),
    ('When', 'predicate', ('EX',), 88),
    ('ReservationDue', 'reservation_id firing_id due detected execution? evidence[]', ('EX',), 88),
    ('C1CountFrame', 'measurement_id source_record delivery_records[] run origin_ns start_ns end_ns count probe? generated_by[]', ('EC', 'ER'), 100),
)
INPUT_TARGETS = tuple(target('public input/type (not a new Body)', name, 'type',
    'selected', field.rstrip('?'), entries, line, nullable=field.endswith('?'),
    rules=('V-03', 'V-04', 'A-20', 'A-21'),
    exclusion='C1CountFrame is a derived output; raw rate_report authentication is separate' if name == 'C1CountFrame'
              else 'V-08 public declaration only (test_named_public_due_declarations_exist); not a standalone Record/Body or facts request. P-02 reserves firing/storage operations for F-b; this does not cover temporal authentication of embedded reservation values.' if name in ('At', 'When', 'ReservationDue')
              else '',
    evidence='public sui.f declaration fields and selected union annotations' if name in ('At', 'When', 'ReservationDue') else 'Record/CID/header/seal',
    negative='missing or mismatched public declaration/field/union' if name in ('At', 'When', 'ReservationDue') else 'remove required key',
    legal='public declaration matches V-08; no operational success asserted' if name in ('At', 'When', 'ReservationDue') else 'same record with the key present')
    for name, fields, entries, line in PRIMARY_INPUTS for field in fields.split())
FIELD_TARGETS = tuple(_inventory()) + INPUT_TARGETS


@dataclass(frozen=True)
class Pair:
    id: str
    rules: tuple[str, ...]
    entries: tuple[str, ...]
    stage: str
    negative: str
    nearest_legal: str
    reason: str
    fields: tuple[str, ...]
    line: int
    exception: str = "FInputError"


def pair(id, rule, entries, stage, negative, legal, reason, fields, line, exception="FInputError"):
    return Pair(id, tuple(dict.fromkeys((rule, "A-21", "A-19"))), tuple(entries), stage,
                negative, legal, reason, tuple(fields.split()), line, exception)


# These cases are written from section 6, before running the implementation.
# No failure is changed to success merely because current code accepts it.
PAIRS = (
    pair("seal", "A-01", ALL_ENTRIES, "generated", "same CID, different payload bytes", "original payload", "result_mismatch", "seal content body", 520, "FReplayMismatch"),
    pair("missing-body", "A-01", ALL_ENTRIES, "generated", "required body physically missing", "body readable", "missing_input", "body model declaration required_records", 252, "FReplayUnavailable"),
    pair("unknown-version", "V-08", ALL_ENTRIES, "generated", "known name /999", "same name /1", "unknown_version", "contract version", 555),
    pair("fixed-duplicate", "A-02", ("EN", "EH", "EC", "EP", "EF", "EB"), "generated", "duplicate fixed CID", "one CID", "shape", "fixed_parents", 149),
    pair("used-sibling", "A-03", CONTEXT, "generated", "Decided uses earlier sibling without actual ancestry", "same Record is ancestor", "unresolved_reference", "inputs", 522),
    pair("outer-inputs", "A-04", FINITE, "generated", "measurement request missing outer plan Ref", "exact plan Ref", "proof_mismatch", "inputs plan", 157),
    pair("outer-result-about", "A-04", FINITE, "generated", "result about empty", "about contains request", "proof_mismatch", "about request", 160),
    pair("outer-proof-basis", "A-04", FINITE, "verified", "proof basis missing model", "model/request/result set in reverse order", "proof_mismatch", "basis model", 163),
    pair("cause-receipt", "A-05", CONTEXT, "generated", "unknown Observed r=Attempt.at-1", "r=Attempt.at", "shape", "received_ns caused_by", 524),
    pair("short-circuit", "A-06", ("EP", "EF", "ED"), "generated", "false and child with malformed typed quantity Point", "false and valid constant child", "reference_kind", "key left", 525),
    pair("notification-use", "A-08", CONTEXT, "generated", "Decided consumes Observed before received", "consumption at received", "shape", "received_ns inputs", 527),
    pair("raw-acquisition", "A-09", FINITE, "acquired", "raw.r=a+1, notification delayed", "raw.r=a, notification delayed", "shape", "clock received_ns contents time_ns", 528),
    pair("result-acquisition", "A-10", FINITE, "acquired", "g=a+1, acquisition r>g, no adoption", "g=a, no adoption", "shape", "clock contents finished_clock time_ns", 529),
    pair("proof-acquisition", "A-10", FINITE, "acquired", "proof g=a+1, acquisition r>g, no adoption", "proof g=a, no adoption", "shape", "clock contents finished_clock time_ns", 529),
    pair("static-acquisition", "A-11", FINITE, "acquired", "declaration recorded a+1, no independent issuance evidence", "s_D=a", "certificate_incomplete", "contents clock", 190, "FIncomplete"),
    pair("clock-notification", "A-12", FINITE, "acquired", "acquire clock notification before its receipt, despite old reading", "acquire at notification receipt", "shape", "clock received_ns contents time_ns", 205),
    pair("clock-reading-receipt", "A-13", CONTEXT, "generated", "reading=r+1", "reading=r with delayed storage", "shape", "time_ns reading received_ns", 211),
    pair("receipt-storage", "A-13", CONTEXT, "generated", "r=s+1", "r=s", "shape", "received_ns mono_ns", 211),
    *(pair("window-"+b, "A-14", FINITE, "generated", "completed window end=r+1", "end=r", "shape", "end_ns interval requested_interval", 212) for b in ("frame", "claim", "gap", "measurement_unavailable")),
    pair("measurement-generation", "A-15", FINITE, "generated", "Attempt=e+1", "Attempt=e", "shape", "actual_time time_ns generated_by", 213),
    pair("job-step", "A-15", FINITE, "generated", "job content.step differs from request", "all step=0", "observation_binding_mismatch", "step", 213),
    pair("second-generator", "A-15", FINITE, "generated", "second generating job has different step", "both generating jobs match", "observation_binding_mismatch", "step generated_by", 213),
    *(pair("whole-window-"+b, "A-15", FINITE, "generated", "Attempt=start+1", "Attempt=start", "shape", "start_ns interval generated_by", 222) for b in ("closed", "no_arrival")),
    pair("adoption-sibling", "A-16", FINITE, "adopted", "acquisition is sibling of adoption", "same acquisition is ancestor", "proof_mismatch", "completion contents inputs", 230),
    pair("proof-statement", "A-10", FINITE, "verified", "statement.result changed, no adoption", "correct statement, no adoption", "proof_mismatch", "result statement", 602),
    pair("context-order", "A-17", CONTEXT, "generated", "clock 2 -> fact -> clock 1", "clock 1 -> fact -> clock 2", "shape", "check_events", 231),
    pair("context-o-j", "A-17", CONTEXT, "generated", "o=j+1", "o=j", "shape", "observation_reading judgment_reading time_ns", 231),
    pair("context-clock-run", "A-17", CONTEXT, "generated", "o reading from other run", "same run", "clock_unaligned", "run observation_reading clock", 231),
    pair("context-fact-bound", "A-17", CONTEXT, "generated", "checked fact.r=o+1", "fact.r=o", "shape", "check_events received_ns", 231),
    pair("observation-bound", "A-18", ("EN", "EH", "EP", "ER"), "generated", "raw.r=o+1", "raw.r=o, context storage>j", "shape", "received_ns observation_reading observed", 232),
    pair("required-null", "A-20", CONTEXT, "generated", "clock.source=null", "source=Point", "shape", "source", 234),
    pair("required-missing", "A-20", CONTEXT, "generated", "clock source key absent", "source present", "shape", "source", 234),
)

RELATION_TARGETS = tuple(target("usage-dependent", "authentication", "2026-10-11", p.stage,
    p.id, p.entries, p.line, rules=p.rules, use=p.negative + " / " + p.nearest_legal,
    evidence="actual CID ancestry + selected contract's evidence", consumer=p.stage,
    negative=p.negative, legal=p.nearest_legal) for p in PAIRS)
INVENTORY = FIELD_TARGETS + RELATION_TARGETS

# Explicit open boundaries, never silently counted as covered or skipped success.
LIMITATIONS = {
    "measurement_run": "V-08 does not select a codec or enumerate columns (line 74).",
    "custom_generation": "A-15 requires a versioned report/window contract; no invented extension.",
    "field_prefix": "A-21 fixes JSON Pointer and relevant field, not every enclosing prefix.",
    "preparation_record": "E-05: facts preparation_input/2 is carried by math_artifact/2 input/calls plus input_key FFactsDependencies; no standalone issuer is required.",
}


def presence_group(row):
    """Only required-key presence, never value/edge/time semantics.

    A missing key in the same selected object has the same shape rule. Keep
    contract/version/branch, object depth and nullable-key class distinct.
    Do not fold an entry into a different entry or a branch into another branch.
    """
    if row.field == '$contract':
        return (row.contract, row.version, row.branch, '$contract', row.presence)
    parent = row.field.rsplit('.', 1)[0] if '.' in row.field else '$body'
    return (row.contract, row.version, row.branch, parent, row.presence)


def identity_group(row):
    """A-01's whole-Record identity: field kinds plus every Body/status.

    Header fields are shared Record/Instant/Producer types. Body serializers
    remain distinct. This fold does not stand in for A-03/05/08/20 semantics.
    """
    field = row.field
    if field == 'id': return ('header', 'RecordRef')
    if field.startswith('at.'):
        return ('header', 'run-Ref' if field == 'at.run' else 'Instant-integer')
    if field.startswith('producer.'):
        return ('header', 'nullable-StateRef' if field == 'producer.state' else
                'state-member' if field.startswith('producer.state.') else 'producer-text')
    if field in ('writer', 'schema'): return ('constructor', field)
    branch = row.branch.split('-')[0]
    body_branch = branch if row.body == 'Intention' else 'body'
    kind = ('reference-sequence' if field.endswith('[]') else
            'contract' if field.startswith('contract') else
            'payload' if field.startswith('content') else
            'nullable-reference' if field in ('caused_by', 'supersedes', 'via') else
            'reference' if field in ('target', 'decision', 'job', 'decided_in') else
            'nullable-time' if field in ('source_time_ns', 'received_ns') else
            'nullable-text' if field == 'source_id' else 'scalar')
    return (row.body, body_branch, kind)


@dataclass(frozen=True)
class Representative:
    row: str
    rule: str
    use: str
    entry: str
    representative: str
    reason: str


def representatives(rows, rule, grouping, entries):
    """Pure spec-side grouping; material availability is not the denominator."""
    rows = tuple(rows)
    selected = {}
    output = []
    for row in rows:
        for entry in entries(row):
            key = (entry, grouping(row))
            selected.setdefault(key, row.id)
            rep = selected[key]
            output.append(Representative(row.id, rule, 'whole-record identity' if rule == 'A-01'
                else 'required key presence / exact contract version', entry, rep,
                'self' if rep == row.id else '代表: '+rep+'; same entry and '+
                ('public field kind/Body; temporal and edge rules remain separate' if rule == 'A-01' else
                 'contract/version/selected branch/object/presence; value and use rules remain separate')))
    return tuple(output)


REPRESENTATIVES = (
    *representatives((r for r in FIELD_TARGETS if r.contract == 'Record'), 'A-01', identity_group, lambda r: r.entries),
    *representatives((r for r in FIELD_TARGETS if r.contract.startswith('sui.')), 'A-20/V-08', presence_group, lambda r: r.entries),
)

# User's 2026-10-11 second instruction: test the public boundary, no raw bypass.
CONSTRUCTION_BOUNDARIES = {
    'receipt-storage': ('Record', 'ValueError', 'r=s+1; legal r=s'),
    'writer': ('Record', 'WriterNotAllowed', 'Observed/MODEL; legal MEMBRANE'),
    'schema': ('Record', 'SchemaMismatch', 'schema=999; legal schema=3'),
    'status': ('IntentionStatus', 'ValueError', 'unknown enum name; legal confirmed/withdrawn/executed'),
}

def _annotated_targets():
    grouped = {}
    for fold in REPRESENTATIVES:
        if fold.row != fold.representative:
            grouped.setdefault(fold.row, {}).setdefault((fold.rule, fold.representative), []).append(fold.entry)
    for row in FIELD_TARGETS:
        descriptions = ['代表: '+rep+' ['+rule+'; '+','.join(entries)+']'
            for (rule, rep), entries in grouped.get(row.id, {}).items()]
        exclusion = row.not_applicable
        if row.contract == 'Record' and row.field in ('writer', 'schema', 'status'):
            constructor, exception, _ = CONSTRUCTION_BOUNDARIES[row.field]
            exclusion += f'; 公開の構築で拒まれる: {constructor} / {exception}; constructor boundary pair'
        yield replace(row, representative='; '.join(descriptions) or 'self (execution status is separate)',
                      not_applicable=exclusion)


FIELD_TARGETS = tuple(_annotated_targets())
RELATION_TARGETS = tuple(replace(row, not_applicable=
    '公開の構築で拒まれる: Record / ValueError (received_ns > Record.at.mono_ns); constructor boundary pair')
    if row.field == 'receipt-storage' else row for row in RELATION_TARGETS)
INVENTORY = FIELD_TARGETS + RELATION_TARGETS


REVIEW4_PAIRS = (
    *(pair('generation-without-completion-'+target_kind, 'A-10', FINITE,
        'acquired-'+target_kind, 'acquired '+target_kind+' has no matching completion anywhere in the fixed scope',
        'same acquisition with matching computation_completed and g <= a',
        'certificate_incomplete', 'contents', 187, 'FIncomplete')
      for target_kind in ('result', 'proof')),
    pair('candidate-required-basis', 'A-04', FINITE, 'declaration',
        'outer Prediction.basis lacks the Ref of a required generation.basis Point',
        'outer basis contains the required Ref and one distinct additional authenticated Ref',
        'proof_mismatch', 'basis', 165),
    *(pair('used-clock-null-'+use, 'A-20', FINITE, use,
        'used reading source has measurement=null', 'same reading source has its declared clock contract',
        'missing_contract', 'measurement source clock reading', 234, 'FSpecificationMissing')
      for use in ('context', 'acquisition', 'completion')),
)
REVIEW4_TARGETS = tuple(replace(target('usage-dependent', 'authentication-review4', '2026-10-12',
    p.stage, p.id, p.entries, p.line, rules=p.rules, use=p.stage,
    evidence='public Record/Body and actual acquisition/clock/basis dependencies',
    negative=p.negative, legal=p.nearest_legal),
    representative='test_review4_required_evidence_pair['+p.id+']') for p in REVIEW4_PAIRS)
INVENTORY += REVIEW4_TARGETS


REVIEW4_OUTPUT_CHECKS = (
    ('world_manifest', 421, ('EN', 'ED'), 'test_review4_world_manifest_dependencies',
     'wrong contract/compiler or unwrapped request', 'FWorldManifest3 with the exact ArtifactInput request'),
    ('dependencies.points', 412, ('EN', 'ED'), 'test_review4_world_manifest_dependencies',
     'Ref-only, missing availability or unsorted Point rows', 'all required Point/availability/Record/digest columns in Point order'),
    ('dependencies.points.record_digest', 414, ('EN', 'ED'), 'test_review4_manifest_record_digests',
     'digest differs from canonical whole Record', 'independently hash the V-02:28 whole Record, including the draw'),
    ('dependencies.models', 450, ('EN', 'ED'), 'test_review4_world_manifest_dependencies',
     'wrong model document digest or order', 'required model Points in order with independently hashed document'),
    ('dependencies.capabilities', 450, ('EN', 'ED'), 'test_review4_world_manifest_dependencies',
     'wrong capability order or inconsistent implementation availability', 'sorted kind/name/version and explicit implementation identity'),
    ('dependencies.ref_lookups', 450, ('EN', 'ED'), 'test_review4_world_manifest_dependencies',
     'drop one CID of the same Record Ref', 'all matching allowed CIDs, including two CIDs of one identical Record'),
    ('world_key', 458, ('EN', 'ED'), 'test_review4_problem_world_root_key_domains',
     'wrong world domain or hash fields', 'D(sui.f.world/3,{manifest})'),
    ('problem_key', 459, ('EN', 'ED'), 'test_review4_problem_world_root_key_domains',
     'wrong problem domain or omitted public field', 'D(sui.f.problem/3, all FProblem3 fields except problem_key)'),
    ('root_key', 460, ('ED',), 'test_review4_problem_world_root_key_domains',
     'wrong root domain or draw binding', 'D(sui.f.root/3, problem_key/draw_point/draw_record_digest/selection_draw)'),
    ('root_projection', 448, ('ED',), 'test_review4_problem_world_root_key_domains',
     'root changes any original problem projection', 'remove four added fields and restore problem/3 contract'),
    *((field, line, ('ER',), 'test_review4_verification_digest_domains',
       'wrong domain or digest material', 'independently recompute the E-05 equation from public values')
      for field, line in (('input_key', 461), ('input_digest', 462), ('artifact_digest', 463),
                          ('result_digest', 464), ('checked_calls.input_digest', 465),
                          ('checked_calls.output_digest', 466))),
)
REVIEW4_OUTPUT_TARGETS = tuple(replace(target('public issued output', 'E-05 output', '3', 'issued',
    field, entries, line, rules=('E-05', 'V-02'),
    evidence='public canonical_bytes/claim and original public Record reader; no internal hash helper',
    negative=negative, legal=legal), representative=test)
    for field, line, entries, test, negative, legal in REVIEW4_OUTPUT_CHECKS)
INVENTORY += REVIEW4_OUTPUT_TARGETS


REVIEW5_PAIRS = tuple(replace(pair('candidate-basis-'+fault, 'A-06', FINITE,
    'generation.basis declaration dependency', negative,
    'same nonancestor Prediction basis, with a valid quantity_declaration/1 and authentic Record',
    reason, '', 177, exception), rules=('A-06', related_rule, 'A-21', 'A-19'))
    for fault, related_rule, negative, reason, exception in (
        ('unknown-version', 'V-08', 'generation.basis Point has a known contract name with unknown version',
         'unknown_version', 'FInputError'),
        ('missing-field', 'A-20', 'generation.basis Point lacks required rational_constant.value',
         'shape', 'FInputError'),
        ('identity', 'A-01', 'generation.basis Point returns a Record with changed producer under the same CID',
         'result_mismatch', 'FReplayMismatch')))
REVIEW5_TARGETS = tuple(replace(target('Prediction', 'sui.f.candidate_declaration', '1',
    p.stage, 'generation.basis[]:'+p.id, p.entries, p.line, rules=p.rules,
    use='typed dependency authentication, not acquisition or numerical adoption',
    evidence='nonancestor basis Point and matching outer Ref; basis is not an explicit request root',
    negative=p.negative, legal=p.nearest_legal),
    representative='test_candidate_generation_basis_authentication['+p.id+']') for p in REVIEW5_PAIRS)
INVENTORY += REVIEW5_TARGETS


def counts():
    by_rule = Counter()
    entries = {}
    for row in INVENTORY:
        for rule in row.rules:
            by_rule[rule] += 1
            entries.setdefault(rule, set()).update(row.entries)
    return {"rows": len(INVENTORY), "fields": len(FIELD_TARGETS),
            "pairs": sum(r.row_kind == "relation" for r in INVENTORY),
            "supplements": sum(r.row_kind == "supplement" for r in INVENTORY), "rules": {r: {"rows": by_rule[r],
            "entry_count": len(entries[r]), "entries": sorted(entries[r])} for r in sorted(by_rule)}}


# 2026-10-12: relations are independent obligations, never inferred from a
# field's required-key/whole-Record representative (C-01, C-03, C-07).
@dataclass(frozen=True)
class RelationPair(Pair):
    kind: str = ""
    variant: str = ""
    pending_entries: tuple[str, ...] = ()
    mutation_checks: tuple[int, ...] = ()
    pending_reason: str = ""
    not_applicable: str = ""


def relation(kind, variant, rules, *, stage="generated", entries=ALL_ENTRIES,
             negative, legal, reason="shape", exception="FInputError", line):
    return RelationPair(id=f"{kind}.{variant}.{stage}", rules=tuple(dict.fromkeys((*rules,"A-19","A-21"))),
        entries=tuple(entries), stage=stage, negative=negative, nearest_legal=legal,
        reason=reason, fields=(), line=line, exception=exception, kind=kind, variant=variant)


NEW_RELATION_PAIRS = (
    *(relation("parent_child", body+"."+column, ("A-05", "V-07"),
        negative="actual same-run parent -> child violates only "+column,
        legal="same unknown-contract Body, parent seq < child seq, equal M and run_index",
        reason="clock_unaligned" if column == "run_index" else "shape", line=178)
      for body in BODY_FIELDS for column in ("mono_ns", "seq", "run_index")),
    *(relation("body_use", edge, ("A-03", "A-06"),
        negative="typed use resolves to an authentic sibling, not an actual ancestor",
        legal="same use and target, with an actual-parent path", reason="unresolved_reference", line=150)
      for edge in ("Decided.inputs", "JobOpened.decision", "AttemptStarted.job",
                   "Observed.caused_by", "Intention.decided_in", "Intention.supersedes", "Intention.via", "Preference.basis")),
    *(relation("leaf_use", leaf+"."+form, ("A-03", "A-06"),
        negative="leaf basis reaches an Observed sibling absent from the consumer's actual ancestry",
        legal="same basis and content, leaf and consumer have the observed target in their real ancestry",
        reason="unresolved_reference", line=150)
      for leaf in ("Prediction", "Interpretation") for form in ("direct", "nested", "describes")),
    *(relation("target_witness", target+"."+shape, ("A-07", "A-10", "M-02"), stage=stage,
        entries=ALL_ENTRIES, negative="only the target's completion finishes after its acquisition clock",
        legal="matching target completion finishes at acquisition; later unrelated completions do not become witnesses",
        line=189)
      for target in ("result", "proof") for shape in ("unrelated", "acquisition_input", "three_calculations")
      for stage in ("acquired", "verified", "adopted")),
    *(relation("generation_class", branch, ("A-05", "A-14", "A-15"), entries=ALL_ENTRIES,
        negative="report receipt is one ns before its cause" if branch in ("gap", "measurement_unavailable", "coverage_unproved")
                 else "window starts one ns before observing Attempt",
        legal="end < Attempt <= receipt for a report; Attempt = start for a whole-window claim",
        line=221 if branch in ("gap", "measurement_unavailable", "coverage_unproved") else 224)
      for branch in ("gap", "measurement_unavailable", "coverage_unproved", "closed", "no_arrival")),
    *(relation("sequence_set", form, ("A-04", "M-02", "M-04"), entries=ALL_ENTRIES, stage=stage,
        negative="wrong result/mass: reject when deriving selected-origin K; accept in an unused intrinsic-only branch",
        legal="unique inputs I; observations retains repetitions/order; same transition is no-op and distinct measurement applies again",
        reason="proof_mismatch", line=267)
      for form in ("binding_repeat", "redelivery", "distinct_measurement", "input_permutation")
      for stage in ("generated", "acquired", "verified", "adopted")),
    *(relation("check_order", form, ("A-17",), entries=ALL_ENTRIES,
        negative="check_events reverses known actual ancestry at equal ns",
        legal="ancestor before descendant; unrelated equal-ns siblings retain either declared order", line=233)
      for form in ("facts", "clocks", "mixed", "interleaved", "siblings_control")),
    *(relation("stage_boundary", stage, ("A-04", "A-10", "M-02", "C-05"), entries=ALL_ENTRIES,
        stage=stage, negative="request omits one required outer input; no later numeric evaluation is allowed",
        legal="same request with exact outer input set; stop at the named stage",
        reason="proof_mismatch", line=151)
      for stage in ("generated", "acquired", "verified", "adopted")),
    *(relation("closed_window_receipt", branch, ("A-14", "C-05", "C-06"),
        negative="only interval.end_ns changes to received_ns + 1; Attempt <= start <= end remains true",
        legal="same CoverageClaim/Gap, interval.end_ns == received_ns; no acquisition or computation required",
        line=214)
      for branch in ("claim", "gap")),
)

SURVIVOR_RELATION_PAIRS = (
    *(replace(relation("survivor_generation", variant, ("A-15", "C-06"),
        negative=negative, legal=legal, reason=reason, line=215), mutation_checks=(number,))
      for number,variant,negative,legal,reason in (
        (1,"measured_generated","raw measured < cause Attempt <= interval.end; no Binding in intrinsic-only entrances",
         "measured = cause Attempt; selected finite readers also receive the required Binding (not an independent opportunity discriminator)","shape"),
        (2,"measured_opportunity","generated_by contains an early Attempt; a separate opportunity is later than measured",
         "separate opportunity is at measured; no raw/Binding caused_by alias","shape"),
        (3,"opportunity_plan","only the separate opportunity Job/request has a different Plan Point",
         "opportunity Job/request and Binding use the same Plan Point","observation_binding_mismatch"),
        (4,"opportunity_step","only the separate opportunity Job/request has another consistent step",
         "opportunity Job/request and Binding have the same step","observation_binding_mismatch"))),
    replace(relation("cause_receipt", "received_before_storage", ("A-05", "C-06"),
        negative="receipt < cause Attempt < Observed storage; actual-parent chronology is valid",
        legal="receipt = cause Attempt < Observed storage", line=178), mutation_checks=(5,)),
    *(replace(relation("sibling_clock", variant, ("A-17", "C-06"),
        negative=negative, legal=legal, line=233), mutation_checks=(number,))
      for number,variant,negative,legal in (
        (6,"checks_descend","check_events clock readings decrease; both clocks are actual siblings",
         "same siblings, increasing clock-check order"),
        (7,"observation_after_judgment","observation reading > judgment reading; reading records are siblings",
         "same siblings, observation reading <= judgment reading"))),
    *(replace(relation("context_revisit", variant, ("A-18","A-19","C-06"),
        negative="unknown Observed receipt j+1, first acquired/described/checked locally then used by candidate generation basis",
        legal="same graph, unknown receipt exactly j; late static declarations and unused-origin management records are legal",
        line=235),mutation_checks=(number,))
      for number,variant in ((8,"described_direct"),(8,"acquired_direct"),(9,"owner_leaf"),(10,"two_contexts"))),
    replace(relation("typed_point_alias", "generation_basis_cid", ("A-01","A-03","A-04","A-06","C-06"),
        negative="only the second CID's sealed payload disagrees; outer basis still contains the correct shared Record Ref",
        legal="same Record has two authentic CIDs; generation.basis explicitly includes the second, outer basis projects to its Ref",
        reason="result_mismatch",exception="FReplayMismatch",line=153),mutation_checks=(12,)),
)
SURVIVOR_RELATION_PAIRS = tuple(replace(p,
    nearest_legal="No legal member in F-a: opportunity must be one of the generated_by Attempts.",
    not_applicable="Not applicable (no legal member): F-a's built-in sui.f.opportunity_step_slot/1 generation contract includes opportunity among the generators. A-15:217/M-06/M-19; confirmed by the user's final request. A separate opportunity/generator contract belongs to a later slice. Diagnostics and finite-budget equivalence remain unverified.")
    if p.mutation_checks[0] in (2,3,4) else p for p in SURVIVOR_RELATION_PAIRS)
NEW_RELATION_PAIRS = (*NEW_RELATION_PAIRS, *SURVIVOR_RELATION_PAIRS)

# Sixth request: use-sensitive obligations found after the earlier inventory.
# The rules/expectations below come from the paper and the explicit user table,
# not from the implementation's review4 regression tests.
REVIEW_RELATION_PAIRS = (
    *(relation("query_unpublished", form, ("A-04","A-10","A-21","C-01","C-07"),
        stage=stage, reason="missing_contract", exception="FSpecificationMissing", line=166,
        negative="add the query proof to this origin's ContentAcquired.contents; collect no invented query semantics",
        legal="same query proof, valid about/basis and completion evidence, remains unacquired; K.query_proofs is empty")
      for form in ("unknown_statement", "finite_statement_reuse")
      for stage in ("generated", "acquired", "verified", "adopted")),
    *(relation("cid_alias_use", edge+"."+count, ("A-03","A-04","C-01","C-07"),
        stage="consumer", reason="unresolved_reference", line=150,
        negative="same Ref has two authentic CIDs in scope, neither an actual ancestor of the using event",
        legal="one Ref, "+count+" authentic CID(s) among actual ancestors; the other in-scope CID cannot manufacture ambiguity")
      for edge in ("Decided.inputs","JobOpened.decision","AttemptStarted.job","Observed.caused_by",
                   "Intention.decided_in","Intention.supersedes","Intention.via","Preference.basis",
                   "Prediction.basis","Interpretation.basis")
      for count in ("one","two")),
    *(relation("origin_boundary", event, ("A-18","A-05","C-01","C-07"),
        stage=stage, line=234,
        negative="the sole event after j belongs to the selected origin",
        legal="same late event belongs to a different unused origin; earlier prerequisites and intrinsic chronology remain valid")
      for event,stage in (("request","requested"),("acquisition","acquired"),("adoption","adopted"))),
    *(relation("coverage_generation_contract", form, ("A-15","A-14","A-05","A-21","C-01","C-07"),
        stage=stage, line=228,
        negative=("built-in closed claim with Attempt > start" if stage=="classification" else
                  "undeclared claim kind/inner contract used as a measurement, with otherwise valid window generation"),
        legal=("undeclared claim at Attempt > start is legal to retain; semantic use still reports missing_contract"
               if stage=="classification" else "built-in closed claim with Attempt == start and declared measurement semantics"))
      for form in ("kind", "inner_contract") for stage in ("classification","meaning")),
    *(relation("coverage_generation_contract", form, ("A-15","A-14","A-05","A-21","M-02","C-01","C-03","C-07"),
        stage=mode+"."+stop, line=228,
        negative=("built-in closed claim with Attempt > start" if mode=="classification" else
                  "undeclared claim kind/inner contract used by a completed finite update"),
        legal=("undeclared claim at Attempt > start is legal intrinsically; selected K requires its missing meaning"
               if mode=="classification" else "built-in closed claim with Attempt == start and declared measurement semantics"))
      for form in ("kind","inner_contract") for mode in ("classification","meaning")
      for stop in ("generated","acquired","verified")),
    *(relation("coverage_generation_contract", form, ("A-15","A-14","A-05","A-21","C-01","C-07"),
        entries=("EF","EL","EC","EB","ED","ER"),stage="retained",line=228,
        negative="built-in closed with Attempt > start; stop before acquisition/computation/adoption",
        legal="undeclared claim kind/inner contract with Attempt > start, retained only; end and Attempt remain <= receipt")
      for form in ("kind","inner_contract")),
)
NEW_RELATION_PAIRS = (*NEW_RELATION_PAIRS, *REVIEW_RELATION_PAIRS)

# A-18:234 now closes all 86 EC/EB obligations. The independent finite branch
# keeps its own context; it is not numerical input to the selected C1/bridge.
# M-02:267 limits numerical replay to selected-origin K, unlike A-19 intrinsic
# authentication. Acceptance controls remain in the denominator and entry map.
INDEPENDENT_RELATIONS = ("target_witness", "generation_class", "sequence_set", "stage_boundary", "survivor_generation", "context_revisit", "typed_point_alias", "closed_window_receipt", "query_unpublished", "origin_boundary", "coverage_generation_contract")


def relation_rules(pair, entry):
    return tuple(dict.fromkeys(pair.rules + (("A-18",) if entry in ("EC", "EB") and pair.kind in INDEPENDENT_RELATIONS else ())))


def relation_surfaces(pair, entry):
    if entry == "ED":
        return ("bind", "evaluate")
    if entry == "ER":
        if pair.kind=="coverage_generation_contract" and pair.stage=="retained":
            return ("restore_math","verify","restore_root","limit_restore_math","limit_verify")
        if pair.kind in ("query_unpublished","coverage_generation_contract"):
            # Missing meaning can issue a genuine NoDecision math artifact,
            # but cannot issue a selected FRoot. Keep that exclusion in the row.
            return ("restore_math","verify","restore_root","limit_restore_math","limit_verify",
                    "selected_restore_math","selected_verify")
        return ("restore_math", "verify", "restore_root") + (
            ("limit_restore_math", "limit_verify", "selected_restore_math",
             "selected_verify", "selected_restore_root") if pair.kind in ("sequence_set","context_revisit","query_unpublished","origin_boundary","coverage_generation_contract") else ())
    return ("default",)


def relation_bad_outcome(pair, entry, surface="default"):
    selected = entry in ("EN","EH","EP") or (entry=="ER" and surface.startswith("selected_"))
    if pair.kind == "query_unpublished":
        return ("verified_missing_contract" if surface=="selected_verify" else "missing_contract") if selected else "accept"
    if pair.kind == "origin_boundary":
        return "shape" if selected else "accept"
    if pair.kind == "coverage_generation_contract":
        return "shape" if pair.stage.split(".")[0] in ("retained","classification") else (
            ("verified_missing_contract" if surface=="selected_verify" else "missing_contract") if selected else "accept")
    if pair.kind == "sequence_set":
        uses_k = entry in ("EN", "EH", "EP") or (entry == "ER" and surface.startswith("selected_"))
        return "proof_mismatch" if uses_k else "accept"
    if pair.kind == "context_revisit":
        bound = entry in ("EN","EH","EP") or (entry=="ER" and surface.startswith("selected_"))
        return "shape" if bound else "accept"
    return pair.reason


def relation_good_outcome(pair, entry, surface="default"):
    if pair.kind=="coverage_generation_contract" and pair.stage.split(".")[0]=="classification":
        selected = entry in ("EN","EH","EP") or (entry=="ER" and surface.startswith("selected_"))
        return ("verified_missing_contract" if surface=="selected_verify" else "missing_contract") if selected else "accept"
    return "accept"


def relation_surface_exclusions(pair, entry):
    if entry=="ER" and pair.kind=="coverage_generation_contract" and pair.stage=="retained":
        return tuple((entry,s,"This row stops at intrinsic retention; selected-origin semantic use is covered by classification/meaning rows.")
                     for s in ("selected_restore_math","selected_verify","selected_restore_root"))
    if entry=="ER" and pair.kind in ("query_unpublished","coverage_generation_contract"):
        return ((entry,"selected_restore_root",
            "The missing-contract member issues NoDecision, not FProblem, so no authentic selected FRoot exists. Replay/verify of its rejected math artifact and draw-suffix root authentication remain applicable."),)
    return ()


FIELD_TARGETS = tuple(replace(r,
    not_applicable="A-04:166: F-a publishes no query statement/checker; authentication-success obligation is outside F-a until a later contract slice. Required-key negatives remain applicable.")
    if r.contract == "sui.f.computation_proof" and r.branch == "query" else r for r in FIELD_TARGETS)

NEW_RELATION_TARGETS = tuple(replace(target("relation", "F-a relational authentication", "2026-10-12",
    p.stage, p.id, p.entries, p.line,
    rules=tuple(dict.fromkeys(rule for e in p.entries for rule in relation_rules(p,e))), use=p.variant,
    evidence=p.nearest_legal, consumer=p.stage, negative=p.negative, legal=p.nearest_legal),
    row_kind="relation", relation_kind=p.kind,
    mutation_checks=p.mutation_checks,
    discrimination_limits=((p.not_applicable or p.pending_reason) if p.not_applicable or p.pending_entries else
        "Raw-only EF/EL/EC/EB/ED/ER isolates the cause/measured edge; EN/EH/EP need a Binding and may also reject on the opportunity edge. No mutant was run."
        if p.mutation_checks==(1,) else
        "Only public local/bound authentication and repeated Point uses are observable; internal encounter order and individual mutant killing are unverified."
        if p.kind=="context_revisit" else
        "The one-ancestor row is the nearest legal pair; the two-ancestor row adds the required acceptance control with the same negative. CID identity and ancestry are preserved through public merge, including ED/ER. These repeats are not independent mutant kills."
        if p.kind=="cid_alias_use" else
        "Single-fault pair authored from the spec; mutant execution and finite-budget equivalence unverified."
        if "C-06" in p.rules else ""),
    entry_uses=tuple((e,s,"not_applicable" if p.not_applicable else relation_bad_outcome(p,e,s)) for e in p.entries for s in relation_surfaces(p,e)),
    entry_rules=tuple((e,relation_rules(p,e)) for e in p.entries),
    entry_members=tuple((e,s,"not_applicable" if p.not_applicable else relation_good_outcome(p,e,s),
        "not_applicable" if p.not_applicable else relation_bad_outcome(p,e,s))
        for e in p.entries for s in relation_surfaces(p,e)) + tuple(
            (e,s,"not_applicable","not_applicable") for entry in p.entries
            for e,s,_ in relation_surface_exclusions(p,entry)),
    entry_exclusions=tuple(item for e in p.entries for item in relation_surface_exclusions(p,e)),
    not_applicable=((p.not_applicable or p.pending_reason) if p.not_applicable or p.pending_entries else
        "Retention-only stop: EN/EH/EP selected measurement interpretation and ER selected-origin artifacts are exercised by the separate classification/meaning rows. EC/EB are unused branches; EF/EL/ED and their ER envelopes retain/authenticate without deriving this origin's K."
        if p.kind=="coverage_generation_contract" and p.stage=="retained" else
        "A-04/A-18/A-15: semantic/selected-origin rejection applies at EN/EH/EP and ER selected_*; EF/EL, EC/EB unused branch, ED suffix and ER preflight/limit/suffix are intrinsic retention controls. EH/EP have no standalone artifact issuer (E-01:350,352). For missing_contract, ER replays a genuinely issued NoDecision artifact; selected_root is N/A because NoDecision cannot issue FRoot (suffix-root remains covered). EX syntax cannot authenticate these relations."
        if p.kind in ("query_unpublished","origin_boundary","coverage_generation_contract") else
        "A-03: Prediction/Interpretation basis is exercised through an event consumer. Unknown Preference is intrinsic-only; selected EN/EB use the declared style contract. EX syntax cannot authenticate actual ancestry."
        if p.kind=="cid_alias_use" else
        "M-02:267: numerical rejection EN/EH/EP and ER selected_* only; EF/EL, EC/EB independent branch, ED suffix, ER preflight/limit/suffix are acceptance controls. EH/EP have no standalone artifact issuer (E-01:350,352)."
        if p.kind=="sequence_set" else
        "Ledger.append rejects seq/run_index before a facts graph exists; construction pair only, no bypass"
        if p.kind=="parent_child" and p.variant.rsplit(".",1)[1] in ("seq","run_index") else
        "unknown Preference has no selection semantics at EN/EB: declared style there, unknown Body at other entries"
        if p.kind in ("parent_child","body_use") and p.variant.startswith("Preference.") else
        "only the listed entry uses; EX decoding cannot authenticate a relation"),
    representative="not_applicable; no legal F-a pair" if p.not_applicable else
        "pending; public construction declaration requested" if p.pending_entries else
        "test_gate_f_auth_rel.test_relation_pair["+p.id+"]") for p in NEW_RELATION_PAIRS)

# Retain the old denominator and its obligations; do not rename supplemental
# output/presence checks into relation coverage retroactively.
RELATION_TARGETS = tuple(replace(r, row_kind="relation", relation_kind="previous_pair") for r in RELATION_TARGETS)
SUPPLEMENTARY_TARGETS = tuple(replace(r, row_kind="supplement") for r in
    (*REVIEW4_TARGETS, *REVIEW4_OUTPUT_TARGETS, *REVIEW5_TARGETS))
AUXILIARY_RELATIONS = (
    ("implementation_identity", "different", ("V-11","E-05","E-06"), ("EF",), 1, 114,
     "test_registry_identity_across_processes[different]", "different explicit identity gives different key"),
    ("implementation_identity", "same", ("V-11","E-05","E-06"), ("EF",), 1, 114,
     "test_registry_identity_across_processes[same]", "same identity gives the same key in separate processes"),
    ("implementation_identity", "registration_order", ("V-11","E-05","E-06"), ("EF",), 1, 114,
     "test_registry_identity_across_processes[registration_order]", "reverse registration order and unrelated registrations cannot alter key"),
    ("implementation_identity", "registration_shape", ("V-11","A-21"), ("registry",), 7, 114,
     "test_registry_identity_registration_boundary", "empty/non-string identity rejected at registration; nonempty str accepted"),
    ("implementation_identity", "native", ("V-11","E-05"), ("EF",), 1, 457,
     "test_builtin_identity_and_independent_registry_key", "native identity is sui.f.native/1; independently recompute registry key"),
    *(("draft_version", name, ("V-08","E-05"), ("EX",) if name=="value" else ("EX","ER"),
        3 if name=="value" else 9 if name=="problem" else 12, 472,
        "test_unpublished_draft_versions_are_not_upgraded["+name+"]",
        "reject /1 and /2 as unknown_version; nearest published /3 stays readable")
      for name in ("prepare_world","problem","root","value")),
)
AUXILIARY_RELATION_TARGETS = tuple(replace(target("relation","F-a public boundary","2026-10-12",
    "boundary",kind+"."+variant,entries,line,rules=rules,use=variant,evidence=description,
    negative=description,legal="corresponding declared identity or current /3"),
    row_kind="relation",relation_kind=kind,representative="test_gate_f_auth_rel."+test,
    not_applicable="E-05:472: ER standalone VALUE is not applicable; ER claim values are covered by the compiler/problem/root version rows (claim carries no separate VALUE ContractRef)" if variant=="value" else "")
    for kind,variant,rules,entries,_,line,test,description in AUXILIARY_RELATIONS)
SURVIVOR_EXCLUSIONS = (
    (11,"past_context_checks",("A-02","A-03","A-06","A-17","C-06"),233,
     "Not applicable in F-a: a valid past context's fact/clock check target is an actual ancestor, already reached through Entry.parents. Making it non-ancestor AND corrupt adds two faults. C-06 claim is limited to (1) the successful-input set with sufficient budget. Diagnostics and finite-budget equivalence remain unverified. The user's final request explicitly leaves budget accounting and expected public budget results outside F-a's normative scope."),
    (12,"candidate_generation_basis",("A-03","A-04","A-06","C-06"),167,
     "Only the proposed missing-outer-Ref form is N/A: omitting S(generation.basis) from outer basis AND corrupting the target adds two faults. This does NOT exclude another CID of the same Record: A-04:153 retains distinct Points before Ref projection, covered separately by typed_point_alias.generation_basis_cid. No whole-mutant equivalence claim; finite-budget/diagnostic equivalence unverified."),
)
SURVIVOR_EXCLUSION_TARGETS = tuple(replace(target("relation","F-a survivor discrimination","2026-10-12",
    "not_applicable_single_fault",str(number)+"."+name,ALL_ENTRIES,line,rules=rules,
    use="exclusive reachability",negative=reason,legal="no legal graph has the proposed exclusive edge"),
    row_kind="relation",relation_kind="closure_reachability",not_applicable=reason,
    mutation_checks=(number,),discrimination_limits=(
        "C-06 (1) successful-input-set equivalence only; diagnostics and finite-budget equivalence are unverified. F-a does not norm budget accounting or expected public budget results."
        if number==11 else "Only the proposed exclusive-edge single-fault form is N/A. C-06 diagnostic and finite-budget equivalence remain unverified."),
    representative="no single-fault exclusive-edge pair; C-06 diagnostics/budget not verified")
    for number,name,rules,line,reason in SURVIVOR_EXCLUSIONS)
INVENTORY = FIELD_TARGETS + RELATION_TARGETS + SUPPLEMENTARY_TARGETS + NEW_RELATION_TARGETS + AUXILIARY_RELATION_TARGETS + SURVIVOR_EXCLUSION_TARGETS


def relation_counts():
    """Number of planned items, not observed passes; each entry has both members."""
    groups = {}
    for p in NEW_RELATION_PAIRS:
        for rule in dict.fromkeys(rule for e in p.entries for rule in relation_rules(p,e)):
            applicable = tuple(e for e in p.entries if rule in relation_rules(p,e))
            g = groups.setdefault((rule, p.kind), {"rows": 0, "tests": 0, "entries": set(), "pending_entry_pairs":0, "not_applicable_entry_pairs":0})
            g["rows"] += 1
            if p.not_applicable:
                g["not_applicable_entry_pairs"] += len(applicable)
                continue
            g["tests"] += 2 * sum(len(relation_surfaces(p,e)) for e in applicable if e not in p.pending_entries)
            g["entries"].update(e for e in applicable if e not in p.pending_entries)
            g["pending_entry_pairs"]+=sum(e in p.pending_entries for e in applicable)
    for kind,_,rules,entries,n,_,_,_ in AUXILIARY_RELATIONS:
        for rule in rules:
            g=groups.setdefault((rule,kind),{"rows":0,"tests":0,"entries":set(),"pending_entry_pairs":0})
            g["rows"]+=1;g["tests"]+=n;g["entries"].update(entries)
    for _,_,rules,_,_ in SURVIVOR_EXCLUSIONS:
        for rule in rules:
            g=groups.setdefault((rule,"closure_reachability"),
                {"rows":0,"tests":0,"entries":set(),"pending_entry_pairs":0,"not_applicable_entry_pairs":0})
            g["rows"]+=1;g["not_applicable_entry_pairs"]+=len(ALL_ENTRIES)
    return {"rows": len(INVENTORY), "row_kinds": dict(Counter(r.row_kind for r in INVENTORY)),
        "relation_kinds": dict(Counter(r.relation_kind for r in INVENTORY if r.row_kind == "relation")),
        "rule_kind": [{"rule": rule, "kind": kind, **g, "entries": sorted(g["entries"]),
                       "entry_count": len(g["entries"])} for (rule, kind), g in sorted(groups.items())]}
