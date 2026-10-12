"""The single compiler for F worlds: resolve, canonicalize, certify, then seal.

Only this boundary reads model declarations or resolves capabilities by name.
The mathematical engine receives WorldData, containing immutable resolved values.
"""
from __future__ import annotations

from dataclasses import dataclass, replace, fields, is_dataclass
from types import MappingProxyType

from . import f as core, f_contracts as fc
from .f_model import FModel, FModel11, _parts, _model_ref as f_model_ref
from ._f_handles import issue, require_issued, attached_world
from .f_entry import build_histories, f_from_json
from .f import FContext, CandidateSet, FContinuation, FResources
from ._f_invariants import (NO_AVAILABILITY_EDGES, STRUCTURAL_INVARIANTS, EVENT_INVARIANTS,
                           GENERATION_INVARIANT, RELATION_INVARIANTS)


@dataclass(frozen=True)
class _WorldLedger:
    """Immutable reader of verified ledger points; exposes no writing API."""
    _entries: object
    _preferences: object
    _records: object
    _by_id: object
    _tick: object | None = None

    def entry(self, cid):
        return self._entries[cid]

    def ancestors(self, frontier):
        pending, seen = list(frontier), set()
        while pending:
            cid = pending.pop()
            if cid not in seen:
                if self._tick is not None:
                    self._tick()
                try:
                    entry = self._entries[cid]
                except KeyError as exc:
                    raise core.FReplayUnavailable('missing_input', cid, '/ledger') from exc
                pending.extend(entry.parents)
                seen.add(cid)
        return frozenset(seen)

    def between(self, old, new):
        selected = self.ancestors(new) - self.ancestors(old)
        # from_ledger sorts points and stores a set of relations. Receipt order
        # has no semantic effect; no arbitrary ordering is used to infer edges.
        return tuple(self._entries[cid] for cid in sorted(selected))

    def _preference_record(self, entry):
        return self._preferences[entry.cid]


@dataclass(frozen=True)
class _UnreadLedgerRecord:
    missing: bool
    detail: str = ''


@dataclass(frozen=True)
class FactsReader(_WorldLedger):
    """Factory snapshot of actual public reader ports, including unread bodies."""
    _sealed: object = None
    view_key: str = ''

    def entry(self, cid):
        return self._entries[cid]

    def entries(self):
        return tuple(self._entries[k] for k in sorted(self._entries))

    def record(self, cid):
        from ._f_identity import point
        return point(self, cid)[1]

    def sealed_content(self, cid):
        return self._sealed[cid]


_READ_IMAGES = {}
_READ_IMAGE_DIGESTS = {}


def _reader_material(reader):
    return {'entries':tuple({'cid':k,'header':reader._entries[k].header,
            'id':reader._entries[k].id,'parents':reader._entries[k].parents,
            'at':reader._entries[k].at,'writer':reader._entries[k].writer,
            'category':reader._entries[k].category,'seal':reader._entries[k].seal,
            'kind':reader._entries[k].body_type.__name__}
            for k in sorted(reader._entries)),
        'records':tuple((k,reader._records[k]) for k in sorted(reader._records)),
        'sealed':tuple((k,reader._sealed[k]) for k in sorted(reader._sealed)),
        'by_id':reader._by_id,'preferences':reader._preferences}


def captured_reader(reader):
    if type(reader) is FactsReader and _READ_IMAGES.get(id(reader)) is reader:
        if _READ_IMAGE_DIGESTS[id(reader)]!=core._digest(_reader_material(reader)):
            raise core.FReplayMismatch('result_mismatch',fields=('/reader',))
        return True
    return False


def check_points(points,field='/point'):
    import re
    for point in points:
        if type(point) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}',point) is None:
            raise core.FInputError('reference_kind',field=field)


def capture_reader(reader, budget):
    """Capture facts, not a caller-written availability table or ledger writer."""
    budget=core._decode(core._encode(budget),core.RateBudget)
    if not all(callable(getattr(reader,name,None)) for name in ('entry','entries','record','sealed_content')):
        raise core.FInputError('shape','FReader ports required','/reader')
    if captured_reader(reader):
        return reader
    from .ledger import entry_from_header, decode_record, seal
    from .records import Category
    from .snapshot import UnreadPreference
    entries, records, preferences, by_id, sealed = {}, {}, {}, {}, {}
    for number, supplied in enumerate(reader.entries(), 1):
        from ._f_handles import charge_verification
        charge_verification()
        if number > budget.max_cells:
            raise core.FIncomplete('budget_exhausted', 'reader capture', '/reader')
        try:
            actual = reader.entry(supplied.cid)
            rebuilt = entry_from_header(actual.cid, actual.header)
            if rebuilt != supplied or actual != rebuilt:
                raise core.FReplayMismatch('result_mismatch', fields=('/reader/header',))
            if rebuilt.cid in entries:
                raise core.FInputError('shape', 'duplicate CID', '/reader')
            entries[rebuilt.cid] = rebuilt
            by_id.setdefault(rebuilt.id, []).append(rebuilt.cid)
            try:
                salt, payload = reader.sealed_content(rebuilt.cid)
                if seal(payload, salt) != rebuilt.seal:
                    raise core.FReplayMismatch('result_mismatch', fields=('/reader/seal',))
                record = decode_record(rebuilt.header, payload)
                supplied_record = reader.record(rebuilt.cid)
                if core._digest(supplied_record) != core._digest(record):
                    raise core.FReplayMismatch('result_mismatch', fields=('/reader/content',))
                records[rebuilt.cid] = record
                sealed[rebuilt.cid] = (salt, payload)
            except (KeyError, core.FReplayUnavailable):
                try:
                    reader.record(rebuilt.cid)
                    detail='seal'
                except (KeyError,core.FReplayUnavailable):
                    detail='body'
                records[rebuilt.cid] = _UnreadLedgerRecord(missing=True,detail=detail)
            except (core.FReplayMismatch,ValueError,TypeError,UnicodeError):
                # A positive result depends only on its actual fixed closure.
                # Preserve corruption in the image and reject on dereference;
                # an unrelated late body cannot replace a fixed dependency.
                records[rebuilt.cid] = _UnreadLedgerRecord(missing=False,detail='content')
            if rebuilt.category is Category.PREFERENCE:
                value = records[rebuilt.cid]
                preferences[rebuilt.cid] = (UnreadPreference(id=rebuilt.id,at=rebuilt.at,reason='missing content')
                    if isinstance(value,_UnreadLedgerRecord) else value)
        except KeyError as exc:
            raise core.FReplayUnavailable('missing_input', supplied.cid, '/reader') from exc
        except (ValueError,TypeError,UnicodeError) as exc:
            raise core.FReplayMismatch('result_mismatch', fields=('/reader',)) from exc
    result = FactsReader(MappingProxyType(entries), MappingProxyType(preferences),
        MappingProxyType(records), MappingProxyType({k:tuple(v) for k,v in by_id.items()}),
        _sealed=MappingProxyType(sealed))
    digest=core._digest(_reader_material(result))
    result=replace(result,view_key=reader_view_key(result))
    _READ_IMAGES[id(result)] = result
    _READ_IMAGE_DIGESTS[id(result)] = digest
    return result


def reader_view_key(image):
    """今の約束 E-05: D("sui.f.reader_view/1", {entries}) over the captured image.

    One row per captured Entry in Point order. A body that could not be read
    keeps its sealed bytes when present but has no record_hex.
    """
    entries = []
    for cid in sorted(image._entries):
        record = image._records.get(cid)
        sealed = image._sealed.get(cid)
        readable = record is not None and not isinstance(record, _UnreadLedgerRecord)
        entries.append({'point': cid, 'header_hex': image._entries[cid].header.hex(),
            'body_present': sealed is not None,
            'salt_hex': None if sealed is None else sealed[0].hex(),
            'payload_media_type': None if sealed is None else sealed[1].media_type,
            'payload_hex': None if sealed is None else sealed[1].data.hex(),
            'record_hex': core._dumps(record).hex() if readable else None})
    return core._digest({'domain': 'sui.f.reader_view/1', 'entries': entries})


def registry_view_key(registry):
    """今の約束 E-05: D("sui.f.registry_view/1", {capabilities}) over every declaration."""
    rows = []
    for declaration in sorted(registry.declarations, key=lambda d: (d.kind, d.ref.name, d.ref.version)):
        implemented = any(i.kind == declaration.kind and i.ref == declaration.ref for i in registry.implementations)
        rows.append({'kind': declaration.kind, 'ref': declaration.ref, 'declaration': declaration,
            'implemented': implemented,
            'implementation_id': implementation_id(registry, declaration.kind, declaration.ref) if implemented else None})
    return core._digest({'domain': 'sui.f.registry_view/1', 'capabilities': rows})


def freeze_world_ledger(ledger):
    """Validate headers/seals using the ledger's facts, then detach its reader."""
    from .ledger import Ledger, entry_from_header, decode_record, seal
    from .records import Category
    from .snapshot import UnreadPreference
    if type(ledger) is not Ledger:
        raise core.FInputError('shape', 'Ledger required', '/ledger')
    entries, preferences, records, by_id = {}, {}, {}, {}
    try:
        supplied = ledger.entries()
        for entry in supplied:
            rebuilt = entry_from_header(entry.cid, entry.header)
            if rebuilt != entry:
                raise core.FReplayMismatch('result_mismatch', fields=('/preference_causality',))
            entries[entry.cid] = rebuilt
            by_id.setdefault(rebuilt.id, []).append(rebuilt.cid)
            try:
                salt, content = ledger.contents.get(rebuilt.seal)
                if seal(content, salt) != rebuilt.seal:
                    raise ValueError('record content seal differs')
                records[entry.cid] = decode_record(rebuilt.header, content)
            except KeyError:
                records[entry.cid] = _UnreadLedgerRecord(missing=True)
            except (ValueError, TypeError, UnicodeError):
                records[entry.cid] = _UnreadLedgerRecord(missing=False)
            if rebuilt.category is Category.PREFERENCE:
                value = records[entry.cid]
                preferences[entry.cid] = (UnreadPreference(id=rebuilt.id,at=rebuilt.at,
                    reason='missing content' if value.missing else 'corrupt content')
                    if isinstance(value, _UnreadLedgerRecord) else value)
    except KeyError as exc:
        raise core.FReplayUnavailable('missing_input', str(exc), '/preference_causality') from exc
    except (ValueError, TypeError, UnicodeError) as exc:
        raise core.FReplayMismatch('result_mismatch', fields=('/preference_causality',)) from exc
    if any(not entry.parents <= entries.keys() for entry in entries.values()):
        raise core.FReplayUnavailable('missing_input', 'ledger parent', '/preference_causality')
    return _WorldLedger(MappingProxyType(entries), MappingProxyType(preferences),
        MappingProxyType(records), MappingProxyType({ref:tuple(cids) for ref,cids in by_id.items()}))


@dataclass(frozen=True)
class _BoundCapability:
    declaration: core.CapabilityDeclaration
    implementation: core.CapabilityCallable

    def call(self, args, input, *, environment=None, model_ref=None, budget=None, numeric_work=None, numeric_input=None, cached_quantities=None, certified_input=None):
        d = self.declaration
        core._schema_check(d.args_contract, args)
        core._schema_check(d.input_contract, input)
        result = self.implementation(args=core._freeze(args), input=core._freeze(input),
            context=core.CapabilityContext(registry=None, resources=environment,
                model_ref=model_ref, budget=budget, numeric_work=numeric_work,
                numeric_input=numeric_input, cached_quantities=cached_quantities, certified_input=certified_input))
        try:
            core._schema_check(d.output_contract, result)
        except core.FInputError as exc:
            raise core.FInputError('capability_output_shape', exc.detail, exc.field) from exc
        return core._freeze(result)


@dataclass(frozen=True)
class WorldData:
    data: object
    kernels: object
    policies: object
    operations: object
    root_operations: object
    operation_policies: object
    after: object
    predicates: object
    choose_axes: object
    prior_joint: tuple
    initial_joint: tuple
    initial_O: tuple
    cost_rules: tuple
    arithmetic: _BoundCapability
    choice: _BoundCapability
    proofs: object
    method: _BoundCapability
    computation_method: _BoundCapability
    model_ref: str

    def predicate(self, predicate, snapshot):
        bound = self.predicates[core._dumps(predicate)]
        return core._decode(bound.call(predicate.args, core._encode(snapshot),
            environment=self, model_ref=self.model_ref, cached_quantities=snapshot.quantities), core.PredicateResult)

    def quantity(self, expression, work):
        return core._decode(self.arithmetic.call({}, core._encode(core.EnclosureInput(expression=expression)),
            budget=work.budget, numeric_work=work, numeric_input=core.EnclosureInput(expression=expression)), core.FQuantity)

    def soft_choice(self, J, masses, gamma, work):
        return core._decode(self.choice.call({}, core._encode(core.ChoiceInput(J=J, masses=masses, gamma=gamma)),
            budget=work.budget, numeric_work=work, numeric_input=core.ChoiceInput(J=J,masses=masses,gamma=gamma)), core.ChoiceOutput)

    def proof(self, name, value, budget):
        result = core._decode(self.proofs[name].call({}, core._encode(value),
            environment=self, model_ref=self.model_ref, budget=budget,
            certified_input=value), core.ProofCheck)
        if result.status == 'disproved':
            raise core.FInputError('proof_mismatch', name, '/proofs')
        return result

    def evaluate(self, root, budget, precision=None):
        from ._f_eval import _evaluation_from_output
        value = core.EvaluationInput(root=root,resume=None)
        output = self.method.call({},core._encode(value),environment=self,
            model_ref=self.model_ref,budget=budget,certified_input=value,numeric_input=precision)
        return _evaluation_from_output(output,root)

    def computation(self, root, computation, budget):
        value = core.ComputationInput(root=root,computation=computation)
        output = self.computation_method.call({},core._encode(value),environment=self,
            model_ref=self.model_ref,budget=budget,certified_input=value)
        return core._decode(output,core.InformationParts)

    def cost(self, O, A):
        from .preference import EvaluationInput
        value = EvaluationInput(evaluation='lookahead', O=O, A=A)
        terms = []
        for feature, probabilities, table in self.cost_rules:
            projection = core._dumps(feature(value))
            selected = next((v for k, v in table if k == projection), None)
            if selected is None or probabilities and selected == 0:
                raise core.FIncomplete('cost_certificate', 'path support not certified')
            terms.append(core._neg(core._log(selected)) if probabilities else core._r(-selected))
        return core._add(*terms)


_TIME_COLUMNS = None


def _time_column(label):
    """A-21: name the record column behind an order label (e.g. value.completion_ns)."""
    global _TIME_COLUMNS
    if _TIME_COLUMNS is None:
        _TIME_COLUMNS = {'actual': 'record.body.received_ns', 'at': 'record.at.mono_ns'}
        for row in (*STRUCTURAL_INVARIANTS, *EVENT_INVARIANTS):
            for item in row.times:
                _TIME_COLUMNS.setdefault(item.name, item.value)
    head, _, last = label.rpartition('.')
    column = _TIME_COLUMNS.get(last, last)
    return (head + '/' if head else '') + column


_KNOWN_RECORD_CONTRACTS = None


def _check_contract_version(record, field):
    """V-08: a known contract name is read only at a version it declares."""
    global _KNOWN_RECORD_CONTRACTS
    if _KNOWN_RECORD_CONTRACTS is None:
        from .clock_contracts import SOURCE
        from .s4_contracts import BOOT
        from .s4b_contracts import RATE_REPORT, RATE_ARRIVAL, RATE_JOB
        from .s4d_contracts import PREFERENCE
        known = {SOURCE, BOOT, RATE_REPORT, RATE_ARRIVAL, RATE_JOB, PREFERENCE,
                 fc.STYLE, fc.MODEL_SOURCE, fc.CANDIDATE_DECLARATION, fc.KNOWLEDGE_ORIGIN,
                 fc.CONTENT_ACQUIRED, fc.COMPUTATION_REQUESTED, fc.COMPUTATION_RESULT,
                 fc.COMPUTATION_PROOF, fc.COMPUTATION_COMPLETED, fc.KNOWLEDGE_ADOPTED,
                 fc.CLOCK_READING, fc.CONTEXT_OBSERVED, fc.DRAW_FACT, fc.MEASUREMENT_REQUESTED,
                 fc.MEASUREMENT_JOB, fc.OBSERVATION_PLAN, fc.OBSERVATION_BINDING, fc.MEASUREMENT,
                 fc.MEASUREMENT_RUN, fc.COVERAGE, fc.ROUTE_CONFIG, fc.QUANTITY_DECLARATION,
                 fc.PREDICATE, fc.LIMIT_DECLARATION, fc.MATH_ARTIFACT, fc.MATH_ARTIFACT_V2}
        _KNOWN_RECORD_CONTRACTS = frozenset(known), frozenset(c.name for c in known)
    contract = getattr(record.body, 'contract', None)
    versions, names = _KNOWN_RECORD_CONTRACTS
    if contract is not None and contract.name in names and contract not in versions:
        raise core.FInputError('unknown_version', 'known contract at an undeclared version', field + '/contract')


def _payload_record(record, contract, *, field='/point'):
    """One body/Role/Category gate, after CID/Record authentication.

    Dedicated decoders may interpret the payload only after this gate. Opaque
    contracts keep the old Observed default; named contracts use table data.
    """
    actual = getattr(record.body, 'contract', None)
    if actual != contract:
        reason = 'unknown_version' if actual is not None and actual.name == contract.name else 'unresolved_reference'
        raise core.FInputError(reason, field=field + '/contract')
    row = next((r for r in (*EVENT_INVARIANTS, *STRUCTURAL_INVARIANTS)
                if r.contract == contract or contract in r.payload_contracts), None)
    shape = ('Observed', 'MEMBRANE', 'FACT') if row is None else (
        row.payload_body, row.payload_role, row.payload_category)
    if (type(record.body).__name__, record.writer.name, record.category.name) != shape:
        raise core.FInputError('shape', field=field + '/role')
    return record


class _WorldCompiler:
    _problem_contract = fc.PROBLEM_FACTS
    _problem_domain = None

    def _setup(self, resources, budget):
        core._require(resources, core.FResources)
        self.resources = resources
        self.registry = resources.registry
        self.budget = core._decode(core._encode(budget), core.RateBudget)
        self.by_record = {r.id: r for r in resources.records}
        self.ledger = resources.preference_ledger
        self.verified_records = set()
        self.visible_cids = frozenset()
        self.visible_ready = False
        self.models, self.records, self.capabilities = {}, {}, {}
        self.bound = {}
        self.cells = 0
        self.preference_view = None
        self.preference_causality = None

    def tick(self):
        from ._f_handles import charge_verification
        charge_verification()
        self.cells += 1
        if self.cells > self.budget.max_cells:
            raise core.FIncomplete('budget_exhausted', 'world graph', '/world')

    def point(self,cid):
        from ._f_identity import point
        self.tick()
        entry,record,binding = point(self.image,cid)
        # §3-10-17-4 G1: derived leaves (Prediction, Interpretation) are not
        # event parents; they qualify by their own parents. Events must be visible.
        if entry.is_event and cid not in self.visible_cids:
            raise core.FInputError('unresolved_reference','point outside fixed parents','/point')
        if not entry.parents <= self.visible_cids:
            raise core.FInputError('unresolved_reference','declaration has later parents','/point')
        self.records[record.id] = core.FRecordDependency(ref=record.id,digest=binding.digest)
        return record

    def payload(self, cid, contract):
        return _payload_record(self.point(cid), contract)

    def content(self,cid,contract):
        record = self.payload(cid, contract)
        return f_from_json(record.body.content.data,contract=contract)

    def _initial_joint(self,belief):return belief.joint

    def _initial_O(self,values):return values

    def snapshot(self):
        return core.FResourceSnapshot(
            models=tuple(self.models[k] for k in sorted(self.models)),
            records=tuple(self.records[k] for k in sorted(self.records, key=str)),
            capabilities=tuple(self.capabilities[k] for k in sorted(self.capabilities)))

    def preference_input(self, *, expected=None):
        """Rebuild from the frozen ledger, never from a caller's relation."""
        from .preference import from_ledger, PreferenceView
        from .records import Category
        ledger = self.resources.preference_ledger
        if ledger is None:
            if self.request.parents or any(r.category is Category.PREFERENCE for r in self.resources.records):
                raise core.FReplayUnavailable('missing_input', 'preference ledger', '/preference_causality')
            view = PreferenceView()
        else:
            view = from_ledger(replace(ledger,_tick=self.tick), self.request.parents)
        for point in view.points:
            self.tick()
            if point.record is None or point.unread is not None:
                raise core.FReplayUnavailable('missing_input', point.cid, '/preference_causality')
            if self.record(point.id) != point.record:
                raise core.FReplayMismatch('result_mismatch', fields=('/preference_causality',))
        causality = core.FPreferenceCausality(
            points=tuple(core.FPreferencePoint(cid=p.cid,record=p.id) for p in view.points),
            before=tuple(sorted(view.before,key=lambda pair:(str(pair[0]),str(pair[1])))))
        for _ in causality.before:
            self.tick()
        if expected is not None and core._dumps(causality) != core._dumps(expected):
            raise core.FReplayMismatch('result_mismatch', fields=('/preference_causality',))
        self.preference_view, self.preference_causality = view, causality
        return view

    def capability(self, kind, ref, args=None):
        key = kind, ref.name, ref.version
        if key in self.bound:
            if args is not None:
                core._schema_check(self.bound[key].declaration.args_contract,args)
            return self.bound[key]
        registry = self.registry
        declaration = next((d for d in registry.declarations if d.kind == kind and d.ref == ref), None)
        implementation = next((i for i in registry.implementations if i.kind == kind and i.ref == ref), None)
        self.capabilities[key] = core.FCapabilityDependency(kind=kind, ref=ref,
            declaration=declaration, implemented=implementation is not None)
        if declaration is None:
            if any(d.kind == kind and d.ref.name == ref.name for d in registry.declarations):
                raise core.FInputError('unknown_version', ref.name, '/capabilities/' + kind)
            raise core.FSpecificationMissing('missing_contract', ref.name, '/capabilities/' + kind)
        if implementation is None:
            raise core.FIncomplete('algorithm_unavailable', ref.name, '/capabilities/' + kind)
        if args is not None:
            core._schema_check(declaration.args_contract, args)
        value = _BoundCapability(declaration, implementation.implementation)
        self.bound[key] = value
        return value

    def record(self, ref):
        record = self.by_record.get(ref)
        self.records[ref] = core.FRecordDependency(ref=ref, digest=None if record is None else core._digest(record))
        if record is None:
            raise core.FReplayUnavailable('missing_input', str(ref), '/records')
        if ref not in self.verified_records:
            if self.ledger is None or ref not in self.ledger._by_id:
                raise core.FReplayUnavailable('missing_input', str(ref), '/ledger')
            self.visible_input()
            cids = tuple(cid for cid in self.ledger._by_id[ref] if cid in self.visible_cids)
            if not cids:
                cids = tuple(cid for cid in self.ledger._by_id[ref]
                    if self.ledger._entries[cid].parents <= self.visible_cids)
            if not cids:
                raise core.FReplayUnavailable('missing_input', str(ref), '/ledger')
            for cid in cids:
                self.tick()
            from ._f_identity import bind_record
            bind_record(self.ledger,record,cids=cids)
            self.verified_records.add(ref)
        return record

    def visible_input(self):
        if not self.visible_ready:
            if self.ledger is not None:
                self.visible_cids = replace(self.ledger, _tick=self.tick).ancestors(self.request.parents)
            self.visible_ready = True

    def fact_input(self, records):
        """Authenticate the selected FACT set and caller's ancestry against CIDs."""
        from .records import Category
        if self.ledger is None:
            if self.request.parents or records:
                raise core.FReplayUnavailable('missing_input', 'ledger', '/ledger')
            visible = frozenset()
        else:
            ledger = replace(self.ledger, _tick=self.tick)
            visible = self.visible_cids
        def facts(cids):
            return frozenset(str(self.ledger._entries[cid].id) for cid in cids
                if self.ledger._entries[cid].category is Category.FACT)
        actual = facts(visible)
        for cid in sorted(visible):
            entry = self.ledger._entries[cid]
            if entry.category is Category.FACT:
                self.record(entry.id)
        supplied = frozenset(str(r.id) for r in records if r.category is Category.FACT)
        if supplied != actual:
            raise core.FInputError('unresolved_reference', 'FACT set differs from ledger ancestry', '/records')
        context = self.request.context
        if not self.request.parents <= context.fact_ancestors.keys():
            raise core.FInputError('unresolved_reference', field='/context/fact_ancestors')
        for cid, claimed in context.fact_ancestors.items():
            if self.ledger is None:
                raise core.FReplayUnavailable('missing_input', cid, '/ledger')
            if claimed != facts(ledger.ancestors((cid,))):
                raise core.FInputError('unresolved_reference', 'FACT ancestry differs from ledger', '/context/fact_ancestors')

    def tracking_registry(self):
        # Resolution performed by existing raw readers is part of the same
        # manifest. Bound world callbacks retain the original callable instead.
        implementations = []
        for implementation in self.registry.implementations:
            def tracked(*,args,input,context,implementation=implementation):
                self.capability(implementation.kind,implementation.ref,args)
                return implementation.implementation(args=args,input=input,context=context)
            implementations.append(replace(implementation,implementation=tracked))
        return core.make_f_registry(declarations=self.registry.declarations,
            implementations=tuple(implementations))

    def compile(self):
        from . import f_entry as entry
        from .preference import BUILTINS
        model, records, frozen, values = self._material()
        request = self.request
        data, declared_kernels, declared_policies, declared_operations = _parts(model)
        kernels, policies, operations, op_policies, predicates, choose_axes = {}, {}, {}, {}, {}, {}
        pending_policies = []
        def resolve(kind, ref, values, typ):
            self.tick()
            bound = self.capability(kind, core._ContractRef(ref.name, ref.version), ref.args)
            result = bound.call(ref.args,core._encode(core.ModelInput(model_ref=request.model_ref)),
                environment=frozen,model_ref=request.model_ref,budget=self.budget)
            decoded = core._decode(result, typ)
            if decoded.id not in values:
                raise core.FInputError('unresolved_reference', field='/' + kind)
            if core._dumps(decoded) != core._dumps(values[decoded.id]):
                raise core.FInputError('proof_mismatch', 'resolved declaration differs from model', '/' + kind)
            return decoded
        def kernel(ref):
            value = resolve('kernel', ref, declared_kernels, core.FiniteKernel)
            kernels[value.id] = value
            return value
        def policy(ref):
            value = resolve('policy', ref, declared_policies, core.FinitePolicy)
            if value.id not in policies:
                policies[value.id] = value
                pending_policies.append(value.id)
            return value
        def predicate(ref):
            key = core._dumps(ref)
            if key in predicates:
                return
            self.tick()
            predicates[key] = self.capability('predicate', core._ContractRef(ref.name, ref.version), ref.args)
            if ref.name in ('and', 'or'):
                children = core._decode(ref.args['terms'], tuple[core.PredicateRef, ...])
            elif ref.name == 'not':
                children = (core._decode(ref.args['term'], core.PredicateRef),)
            else:
                children = ()
            for child in children:
                predicate(child)
        def operation_proof(op):
            self.capability('proof', core._ContractRef(op.proof.name, op.proof.version), op.proof.args)
            if op.proof.name == 'finite_option_proof' and op.proof.version == '1':
                from types import SimpleNamespace
                core._check_option(SimpleNamespace(policies=declared_policies, operations=declared_operations), op)
            checked = core._decode(core._call_capability('proof', core._ContractRef(op.proof.name, op.proof.version),
                args=op.proof.args, input=core._encode(core.ModelInput(model_ref=request.model_ref)),
                resources=frozen, registry=frozen.registry, model_ref=request.model_ref, budget=self.budget), core.ProofCheck)
            if checked.status == 'disproved':
                raise core.FInputError('proof_mismatch', field='/proof')
            if checked.status != 'proved':
                raise core.FIncomplete('certificate_incomplete', field='/proof')
        def operation(op):
            if op.id in operations:
                if operations[op.id] != op:
                    raise core.FInputError('proof_mismatch', field='/operations')
                return operations[op.id]
            self.tick()
            canonical = core.canonical_action(op, registry=frozen.registry)
            self.capability('action', core._ContractRef(op.family.name, op.family.version), op.args)
            p = policy(op.policy)
            k = kernel(op.prediction)
            op_policies[op.id] = p
            predicate(op.start); predicate(op.termination)
            self.capability('execution', op.execution, {})
            if op.execution != core._ContractRef('sui.f.simulated_execution', '1'):
                raise core.FIncomplete('runtime_unverified')
            binding = core._call_capability('execution', op.execution, args={}, input=core._encode(op),
                resources=frozen, registry=frozen.registry, model_ref=request.model_ref, budget=self.budget)
            if core._decode(binding, core.SimulationBinding) != core.SimulationBinding(operation=op.id, policy=op.policy, prediction=op.prediction):
                raise core.FInputError('proof_mismatch', field='/execution')
            operation_proof(op)
            operations[op.id] = canonical
            return canonical
        roots = {}
        for candidate in request.candidates.candidates:
            declared = next((a for a in declared_operations.values() if a.semantic_key == candidate.semantic_key), None)
            if declared is None:
                raise core.FInputError('unresolved_reference', field='/candidates')
            roots[candidate.id] = operation(declared)
            # An alias must itself use the same contracts, not just a copied key.
            if core.canonical_action(candidate, registry=frozen.registry).semantic_key != declared.semantic_key:
                raise core.FInputError('proof_mismatch', field='/candidates')
            if candidate != declared:
                operation_proof(candidate)
        after = {}
        for continuation in request.continuation.after:
            after[continuation.candidate] = None if continuation.policy is None else policy(continuation.policy).id
            after[roots[continuation.candidate].id] = after[continuation.candidate]
        visited = set()
        while pending_policies:
            pid = pending_policies.pop(0)
            if pid in visited:
                continue
            visited.add(pid)
            p = policies[pid]
            nodes = []
            for node in p.nodes:
                self.tick()
                if isinstance(node, core.ExecuteNode):
                    k = kernel(core.KernelRef(name='finite_kernel', version='1', args={'id':node.kernel}))
                    for o in k.outcomes:
                        if o.available.computation is not None:
                            raise core.FIncomplete('certificate_incomplete', 'unproved_computation', '/kernels')
                        if o.evidence is not None:
                            for kind, ref in (('measurement',o.evidence.measurement_contract),
                                ('projection',core._ContractRef('sui.f.value_only','1')),
                                ('generation',core._ContractRef('sui.f.opportunity_step_slot','1')),
                                ('clock',core._ContractRef('sui.f.simulated_clock','1'))):
                                self.capability(kind, ref, {})
                    core._check_control_kernel(k, node)
                    by_evidence = {}
                    for outcome in k.outcomes:
                        if not any(q for row in outcome.matrix for q in row):
                            continue
                        by_evidence.setdefault(core._dumps(outcome.evidence),set()).add(outcome.available.reveal)
                    if any(len(reveals) > 1 for reveals in by_evidence.values()):
                        raise core.FIncomplete('certificate_incomplete','unproved_K_projection','/kernels')
                    if len({o.elapsed_ns for o in k.outcomes if any(q for row in o.matrix for q in row)}) > 1:
                        raise core.FIncomplete('certificate_incomplete','unproved_time_projection','/kernels')
                elif isinstance(node, core.ChooseNode):
                    self.capability('choice', node.rule, {})
                    reps, aliases, returns = [], {}, {}
                    for name in node.operations:
                        op = operation(declared_operations[name])
                        key = op.semantic_key
                        destination = (pid, node.next[name])
                        if key in returns:
                            representative, previous_return = returns[key]
                            if destination != previous_return:
                                raise core.FInputError('alias_continuation_conflict', field='/policies/' + pid + '/' + node.id)
                            aliases[name] = representative
                        else:
                            returns[key] = (name, destination)
                            reps.append(name)
                    node = replace(node, operations=tuple(reps), next=MappingProxyType({name:node.next[name] for name in reps}))
                    choose_axes[pid,node.id] = (tuple(reps),MappingProxyType(aliases),core.CandidateMeasureRef(name='counting',version='1',args={}))
                nodes.append(node)
            policies[pid] = replace(p, nodes=tuple(nodes))
        op_policies = {name:policies[p.id] for name,p in op_policies.items()}
        op_policies.update({name:op_policies[op.id] for name,op in roots.items()})
        self.capability('generator', request.candidates.generator, {})
        if request.candidates.measure is None:
            raise core.FIncomplete('candidate_measure_missing')
        if request.candidates.measure != core.CandidateMeasureRef(name='counting', version='1', args={}):
            raise core.FIncomplete('normalization_unproved', 'continuous execution is not certified')
        method = self.capability('method', request.method, {})
        computation_method = self.capability('method', core._ContractRef('sui.f.computation_information','1'), {})
        if request.method != core._ContractRef('sui.f.finite_evaluation','1'):
            raise core.FIncomplete('algorithm_unavailable')
        arithmetic = self.capability('arithmetic', core._ContractRef('sui.f.exact_expression','1'), {})
        choice = self.capability('choice', fc.SOFT_CHOICE, {})
        proofs = {name:self.capability('proof', core._ContractRef(name,'1'), {}) for name in
            ('finite_tree','fixed_policy_tail','static_target_entropy_bound','finite_terminal_cost')}
        prior = self._prior_joint(data)
        belief = core.initial_finite_belief(model)
        for observation in entry.read_f_observations(model, records, resources=frozen):
            belief = core.apply_f_observation(model, belief, observation=observation)
        initial_O = []
        for i, link in enumerate(request.E.links):
            value = None if not link.records else entry.f_from_json(self.record(link.records[0]).body.content.data, contract=fc.MEASUREMENT).value
            initial_O.append((0, ('received',i), '', value))
        costs = []
        for ref in request.resolved.items:
            raw = self.record(ref).body.content.as_json()
            if raw['rule'] != {'name':'table','version':'1'}:
                raise core.FIncomplete('cost_certificate', 'unsupported path rule')
            args = raw['args']; feature = args['feature']
            key = ('feature',feature['name'],feature['version'])
            if key not in BUILTINS or feature['name'] == 'candidate_outcome':
                raise core.FIncomplete('cost_certificate', 'unsupported path feature')
            probability = 'probs' in args
            table = tuple((core._dumps(k), core._Fraction(v)) for k,v in args.get('probs',args.get('log_probs')))
            if probability and (sum(v for _,v in table) != 1 or min(v for _,v in table) < 0):
                raise core.FInputError('normalization', field='/resolved/items')
            costs.append((BUILTINS[key], probability, table))
        self._zero_cycles(policies, kernels, operations, roots, after)
        state = WorldData(data=core._freeze({'targets':data['targets'],'states':data['states']}),
            kernels=MappingProxyType(kernels), policies=MappingProxyType(policies), operations=MappingProxyType(operations),
            root_operations=MappingProxyType(roots), operation_policies=MappingProxyType(op_policies), after=MappingProxyType(after),
            predicates=MappingProxyType(predicates), choose_axes=MappingProxyType(choose_axes), prior_joint=prior, initial_joint=self._initial_joint(belief),
            initial_O=self._initial_O(tuple(initial_O)), cost_rules=tuple(costs), arithmetic=arithmetic, choice=choice,
            proofs=MappingProxyType(proofs), method=method, computation_method=computation_method, model_ref=request.model_ref)
        manifest = self._manifest()
        world = issue(core._handle(core.FCertifiedWorld, authority=state,
            world_key=core._digest({'domain':self._world_domain,'manifest':manifest}), manifest=manifest,
            model_ref=request.model_ref, scope=request.resolved.scope, candidates=request.candidates,
            continuation=request.continuation, E=request.E, K=request.K))
        values.update(world_key=world.world_key, world_manifest=manifest)
        values = {'contract': self._problem_contract, **values}
        # 今の約束 E-05: problem/3's key is D("sui.f.problem/3", all fields but the key).
        key = core._digest(values if self._problem_domain is None else {'domain': self._problem_domain, **values})
        return issue(core._handle(core.FProblem, authority=world, problem_key=key, **values))

    def _zero_cycles(self, policies, kernels, operations, roots, after):
        # Summarize a finite zero-time return at each call site. A callee's end
        # must never acquire all callers' return addresses: that creates false
        # cycles for two successive calls of the same zero-time operation.
        def entry(op):
            p = policies[op.policy.args['id']]
            return op.id,p.id,p.entry
        contexts = {(op.id,op.policy.args['id']) for op in operations.values()}
        contexts.update((None,pid) for pid in after.values() if pid is not None)
        nodes = {(oid,pid,n.id):n for oid,pid in sorted(contexts,key=repr) for n in policies[pid].nodes}
        nullable = set()
        for key,node in nodes.items():
            oid,_,_ = key
            if isinstance(node,core.EndNode) and (oid is None or not (
                operations[oid].termination.name == 'constant' and not operations[oid].termination.args['value'])):
                nullable.add(key)
        changed = True
        while changed:
            changed = False
            for key,node in nodes.items():
                if key in nullable or isinstance(node,core.EndNode):
                    continue
                self.tick()
                oid,pid,_ = key
                if isinstance(node,core.ChooseNode):
                    value = any(entry(operations[name]) in nullable and (oid,pid,node.next[name]) in nullable for name in node.operations)
                else:
                    stops = oid is not None and operations[oid].termination.name == 'constant' and operations[oid].termination.args['value']
                    value = any(o.elapsed_ns == 0 and any(q for row in o.matrix for q in row) and
                        (stops or (oid,pid,node.next[o.id]) in nullable) for o in kernels[node.kernel].outcomes)
                if value:
                    nullable.add(key); changed = True
        zero, reachable = {}, {}
        for key,node in nodes.items():
            oid,pid,_ = key
            self.tick()
            edges,all_edges = zero.setdefault(key,set()),reachable.setdefault(key,set())
            if isinstance(node,core.ChooseNode):
                for name in node.operations:
                    child,destination = entry(operations[name]),(oid,pid,node.next[name])
                    edges.add(child); all_edges.update((child,destination))
                    if child in nullable:
                        edges.add(destination)
            elif isinstance(node,core.ExecuteNode):
                stops = oid is not None and operations[oid].termination.name == 'constant' and operations[oid].termination.args['value']
                for outcome in kernels[node.kernel].outcomes:
                    if not stops and any(q for row in outcome.matrix for q in row):
                        target = oid,pid,node.next[outcome.id]
                        all_edges.add(target)
                        if outcome.elapsed_ns == 0:
                            edges.add(target)
        pending = [entry(op) for op in roots.values()]
        pending += [(None,pid,policies[pid].entry) for pid in after.values() if pid is not None]
        seen = set()
        while pending:
            key = pending.pop()
            if key not in seen:
                seen.add(key); pending.extend(reachable.get(key,()))
        # Iterative DFS avoids an accidental Python recursion limit on a finite
        # zero-nanosecond chain. Only graph work consumes the compiler budget.
        color = {}
        for start in sorted(seen,key=repr):
            if color.get(start) == 2:
                continue
            stack = [(start,False)]
            while stack:
                key,leaving = stack.pop()
                if leaving:
                    color[key] = 2
                    continue
                if color.get(key) == 1:
                    raise core.FIncomplete('certificate_incomplete','zero_time_cycle','/policies')
                if color.get(key) == 2:
                    continue
                color[key] = 1
                stack.append((key,True))
                stack.extend((child,False) for child in sorted(zero.get(key,()),key=repr,reverse=True))

@dataclass(frozen=True)
class FiniteModelAuthority:
    model: object
    source: str
    resources: object


class _FactsOrder:
    """One facts boundary for clock domains, receipt order and actual ancestry.

    A reading or receipt may precede its saved Record.at. That delay is never
    added to elapsed time. A Decided event has its actual decision Instant;
    later acquisitions cannot change what was available at that decision.
    """
    def __init__(self, compiler):
        self.compiler = compiler
        self.context = None
        self._context_key = None
        self._ancestors = {}
        self._clocks = {}
        self._measurement_routes = None
        self.acquisitions = {}
        self.profile = 'facts'
        self._nodes = {}
        self._validated = set()
        self._validating = set()
        self._memoize = False
        self.enforce_boundary = True
        self.closed_points = None

    @staticmethod
    def select(value, path):
        """Read only declared paths; absent optional/union fields yield no value."""
        if not path:
            return (value,)
        key, _, rest = path.partition('.')
        if isinstance(value, (tuple, list)):
            return tuple(item for child in value for item in _FactsOrder.select(child, path))
        child = value.get(key) if isinstance(value, core._Mapping) else getattr(value, key, None)
        if child is None:
            return ()
        return _FactsOrder.select(child, rest)

    @staticmethod
    def has_null(value, path):
        """Unlike select, distinguish a null field from an empty sequence."""
        if not path:
            return value is None
        if isinstance(value, (tuple, list)):
            return any(_FactsOrder.has_null(child, path) for child in value)
        key, _, rest = path.partition('.')
        child = value.get(key) if isinstance(value, core._Mapping) else getattr(value, key, None)
        return _FactsOrder.has_null(child, rest)

    @staticmethod
    def time(run, value, domain='run_mono_ns'):
        return (run, value, domain)

    def node(self, cid):
        if cid not in self._nodes:
            record = self.compiler.point(cid)
            row = next((r for r in STRUCTURAL_INVARIANTS
                        if r.body == type(record.body).__name__), STRUCTURAL_INVARIANTS[0])
            values = self.select({'record':record}, row.actual_source)
            actual = values[0] if values else None
            self._nodes[cid] = dict(cid=cid, record=record, value=None,
                at=self.time(record.at.run, record.at.mono_ns),
                actual=self.time(record.at.run, actual))
        return self._nodes[cid]

    def enabled(self, rule, kind, index=None):
        if kind == 'boundary' and not self.enforce_boundary:
            return False
        return self.context is not None or not rule.depends_on_context(kind, index)

    def constraints(self, rule, env, field):
        if self.profile not in rule.profiles and not any(
                value == contract for path, contract in rule.activated_by
                for value in self.select(env, path)):
            return
        # A-05/A-18: another run's record keeps its intrinsic checks but is not
        # compared with this context unless a use requires it.
        other_run = isinstance(env, dict) and env.get('other_run')
        def enabled(kind, index=None):
            return self.enabled(rule, kind, index) and not (other_run and rule.depends_on_context(kind, index))
        if self.context is not None:
            env = {**env, '$clock_contract': self.context.clock_contract}
        def values(path):
            if any(link.name == path.partition('.')[0] and self.profile not in link.profiles
                   for link in rule.links):
                return ()
            found = self.select(env, path)
            if not found and self.has_null(env, path) and path not in rule.optional:
                if path.endswith('source.value.measurement'):
                    # A-20: a legal null clock contract is unknown, not a
                    # contradiction; this use needs it (A-21 missing_contract).
                    raise core.FSpecificationMissing('missing_contract', 'used reading has no clock contract', field + '/' + path)
                raise core.FInputError('shape', 'required comparison endpoint is null or absent', field + '/' + path)
            return found
        for i, path in enumerate(rule.required):
            if not enabled('required', i): continue
            if not self.select(env, path):
                raise core.FInputError('unresolved_reference', 'required generation field absent', field + '/' + path)
        for i, path in enumerate(rule.specification_required):
            if not enabled('specification_required', i): continue
            if not self.select(env, path):
                raise core.FSpecificationMissing('missing_contract', field=field + '/' + path)
        for i, path in enumerate(rule.nonnegative):
            if not enabled('nonnegative', i): continue
            for reading in self.select(env, path):
                if reading[1] < 0:
                    raise core.FInputError('unit', field=field + '/' + path)
        for i, (left, right) in enumerate(rule.equals):
            if not enabled('equals', i): continue
            lhs, rhs = values(left), values(right)
            if any(a != b for a in lhs for b in rhs):
                raise core.FInputError(rule.mismatch, 'event bindings disagree', field + '/' + left)
        for i, (left, right) in enumerate(rule.aligns):
            if not enabled('aligns', i): continue
            for a in values(left):
                for b in values(right):
                    self.aligned(a, b, field + '/' + left)
        for i, (path, expected) in enumerate(rule.literals):
            if not enabled('literals', i): continue
            actual_values = self.select(env, path)
            if (not actual_values and expected is not None) or any(value != expected for value in actual_values):
                raise core.FInputError('shape', 'event literal disagrees with contract', field + '/' + path)
        for i, (left, right) in enumerate(rule.includes):
            if not enabled('includes', i): continue
            rhs = tuple(v for group in self.select(env, right)
                        for v in (group if isinstance(group, (tuple, list)) else (group,)))
            if not set(self.select(env, left)) <= set(rhs):
                raise core.FInputError(rule.mismatch, 'generation opportunity absent', field + '/' + right)
        for i, (left, right) in enumerate(rule.orders):
            if not enabled('orders', i): continue
            # Clock labels are atomic triples; linked node lists are expanded
            # before reading the label, not inside its value.
            for earlier in values(left):
                for later in values(right):
                    if isinstance(earlier, core.Unavailable) or isinstance(later, core.Unavailable):
                        continue
                    if earlier[1] is None or later[1] is None:
                        # A-20: a legal unknown time that this use needs.
                        raise core.FIncomplete('certificate_incomplete','unknown time needed',field)
                    if earlier[2] != later[2] or earlier[2] == 'utc_ns':
                        raise core.FInputError('clock_unaligned', field=field + '/domain')
                    self.aligned(earlier[0], later[0], field + '/run')
                    self.ordered(earlier[1], later[1], field + '/' + _time_column(left))

    def relation(self, name, env, field):
        rule = next(row for row in RELATION_INVARIANTS if row.name == name)
        self.constraints(rule, env, field)

    def add_times(self, node, rule):
        for item in rule.times:
            if item.types and type(node.get('value')).__name__ not in item.types:
                continue
            unknown = tuple(v for path in item.unavailable_paths for v in self.select(node, path)
                            if isinstance(v, core.Unavailable))
            if unknown:
                node[item.name] = unknown[0]
                continue
            values = self.select(node, item.value)
            if not values:
                if not item.nullable and self.has_null(node,item.value):
                    raise core.FInputError('shape','required clock field is null or absent','/chronology/' + item.name)
                continue
            runs = (None,) if item.run is None else self.select(node, item.run)
            if len(values) != 1 or len(runs) != 1:
                raise core.FInputError('shape', field='/chronology/' + item.name)
            core._decode(values[0], int, '/chronology/' + item.name)
            node[item.name] = self.time(runs[0], values[0], item.domain)

    def basic(self, cid, field):
        node = self.node(cid)
        record = node['record']
        _check_contract_version(record, field)
        # A-05: every actual same-run parent -> child, whatever the Body or
        # contract, keeps the known monotonic clock non-decreasing. Ledger
        # order (seq) is a different relation and does not stand in for it.
        for parent in sorted(self.compiler.image.entry(cid).parents):
            before = self.node(parent)['record'].at
            if before.run == record.at.run and before.mono_ns > record.at.mono_ns:
                raise core.FInputError('shape', 'parent saved after child', field + '/record/at/mono_ns')
        for rule in STRUCTURAL_INVARIANTS:
            if rule.body is not None and rule.body != type(record.body).__name__:
                continue
            if rule.align_context and self.enabled(rule, 'align_context') and record.at.run != self.context.run:
                # A-05/A-18: another run's event is legal; it is compared with
                # this context only where a use needs it (then clock_unaligned).
                node['other_run'] = True
            self.add_times(node, rule)
            # Linked endpoints are checked only after all of this row's links
            # have been populated, never treated as absent during decoding.
            if not rule.links:
                self.constraints(rule, node, field + '/record')
        return node

    def provenance(self, cid, contract):
        """Only the target event's ancestors in its run, never current closure."""
        run = self.node(cid)['record'].at.run
        candidates = tuple(p for p in self.ancestors(cid)
            if getattr(self.node(p)['record'].body, 'contract', None) == contract
            and self.node(p)['record'].at.run == run)
        if not candidates:
            raise core.FReplayUnavailable('missing_input', 'clock provenance', '/measurement/clock')
        # BOOT semantics select the first run origin. Equivalent ClockSource
        # redeliveries name the same declaration; contradictions are not chosen.
        if contract.name == 'sui.clock.source':
            # A-20: measurement=null is "unknown", so it never contradicts a
            # known declaration; only two different known declarations conflict.
            declared = [self.node(p)['record'].body.content.as_json() for p in candidates]
            known = {core._dumps(d) for d in declared if d.get('measurement') is not None}
            rest = {core._dumps({k: v for k, v in d.items() if k != 'measurement'}) for d in declared}
            if len(known) > 1 or len(rest) != 1:
                raise core.FInputError('clock_unaligned', 'conflicting source declarations', '/measurement/clock')
        return (min(candidates, key=lambda p: self.node(p)['record'].at.seq),)

    def link_points(self, cid, node, link):
        if link.path == '@routes':
            return self.measurement_clock(cid, node['value'].route_epoch)
        if link.path == '@sources':
            from .clock_contracts import SOURCE
            return self.provenance(cid, SOURCE)
        if link.path == '@boot':
            from .s4_contracts import BOOT
            return self.provenance(cid, BOOT)
        if link.path == '@derived':
            mids = set(node['value'].derived_from)
            if not mids:
                return ()
            found = {}
            for point in self.ancestors(cid):
                record = self.node(point)['record']
                if getattr(record.body, 'contract', None) == fc.MEASUREMENT:
                    mid = self.compiler.content(point, fc.MEASUREMENT).measurement_id
                    if mid in mids:
                        found.setdefault(mid, []).append(point)
            if mids - found.keys():
                raise core.FInputError('unresolved_reference', 'derived measurement unavailable', '/measurement/derived_from')
            raw = {p for points in found.values() for p in points}
            bindings = []
            for point in self.ancestors(cid):
                record = self.node(point)['record']
                if getattr(record.body, 'contract', None) == fc.OBSERVATION_BINDING:
                    binding = self.compiler.content(point, fc.OBSERVATION_BINDING)
                    if any(slot.measurement in mids for slot in binding.slots):
                        bindings.append(point)
            return tuple(sorted(raw | set(bindings)))
        values = self.select(node, link.path)
        if not link.nullable and self.has_null(node, link.path):
            raise core.FInputError('unresolved_reference', 'required reference is null or absent', '/chronology/' + link.name)
        if link.event_kind is not None:
            values = tuple(event.record for group in values for event in group if event.kind == link.event_kind)
        # A terminal sequence field denotes all its members, whereas a clock
        # triple is only read by constraints, never by the reference resolver.
        values = tuple(v for value in values for v in (value if isinstance(value, (tuple, list)) else (value,)))
        if link.kind == 'used_ref':
            return tuple(p for v in values for p in self.used_points(cid, v, '/chronology/' + link.name))
        return tuple(self.ref_point(v, '/chronology/' + link.name) if link.kind == 'ref' else v for v in values)

    def used_points(self, owner, ref, field):
        """A-03: a Ref the owner used names a Record that may have several CIDs.
        Every instance in the owner's real ancestry is a use; none is chosen."""
        cids = self.ref_points(ref, field)
        ancestors = self.ancestors(owner)
        used = tuple(c for c in cids if (c in ancestors if self.compiler.image.entry(c).is_event
                                          else self.compiler.image.entry(c).parents <= ancestors))
        if not used:
            raise core.FInputError('unresolved_reference', 'input unavailable at event', field)
        return used

    def validate(self, cid, field='/chronology'):
        # None is structural certification. A context digest certifies the
        # complete declared reference graph under that exact immutable context.
        if self.closed_points is not None and cid not in self.closed_points:
            raise core.FInputError('unresolved_reference', 'record outside certified closure', field)
        key = cid, self._context_key
        if key in self._validated:
            return self.node(cid)
        if key in self._validating:
            raise core.FInputError('proof_mismatch', 'event reference cycle', field)
        self._validating.add(key)
        try:
            node = self._validate(cid, field)
            if self._memoize:
                self._validated.add(key)
            return node
        finally:
            self._validating.remove(key)

    def _validate(self, cid, field):
        node = self.node(cid)
        record = node['record']
        contract = getattr(record.body, 'contract', None)
        named = next((r for r in EVENT_INVARIANTS if r.contract == contract), None)
        if named is not None and named.field is not None:
            field = named.field
        self.basic(cid, field)
        rules = tuple(r for r in STRUCTURAL_INVARIANTS if r.body is None or r.body == type(record.body).__name__)
        if named is not None:
            record = self.compiler.payload(cid, contract)
            from .clock_contracts import SOURCE, clock_source_from_json
            if named.decoder == 'clock_source':
                from .action_types import ActionInputError
                try:
                    node['value'] = clock_source_from_json(record.body.content.as_json())
                except ActionInputError as exc:
                    raise core.FInputError('shape', exc.detail, '/clock/source') from exc
            elif named.decoder == 'json':
                node['value'] = record.body.content.as_json()
                if named.keys:
                    value = node['value']
                    if not isinstance(value, dict):
                        raise core.FInputError('shape', 'body is not an object', field + '/content')
                    odd = sorted(set(named.keys) ^ set(value))
                    if odd:
                        raise core.FInputError('shape', 'body key set differs from its contract', field + '/' + odd[0])
            else:
                node['value'] = self.compiler.content(cid, contract)
            rules += (named,)
            self.add_times(node, named)
        for rule in rules:
            for link in rule.links:
                if self.profile not in link.profiles or (link.context_dependent and self.context is None):
                    continue
                points = self.link_points(cid, node, link)
                linked = []
                for point in points:
                    self.reference(cid, point, field + '/' + link.name)
                    dependency = self.node(point)
                    dep_record = dependency['record']
                    if link.contract is not None and getattr(dep_record.body, 'contract', None) != link.contract:
                        actual_contract = getattr(dep_record.body, 'contract', None)
                        reason = 'unknown_version' if actual_contract is not None and actual_contract.name == link.contract.name else 'unresolved_reference'
                        raise core.FInputError(reason, 'reference contract mismatch', field + '/' + link.name)
                    if link.body is not None and type(dep_record.body).__name__ != link.body:
                        raise core.FInputError('unresolved_reference', 'reference body mismatch', field + '/' + link.name)
                    if link.category is not None and dep_record.category.name != link.category:
                        raise core.FInputError('shape', 'check event must be a fact', '/check_events')
                    linked.append(self.validate(point, field + '/' + link.name))
                node[link.name] = tuple(linked)
            self.constraints(rule, node, field)
            for label, interval_path in rule.intervals:
                # Typed unknown is separate from null/absent optionality.
                for reading in self.select(node, label):
                    if isinstance(reading, core.Unavailable): continue
                    for interval in self.select(node, interval_path):
                        self.aligned(reading[0], interval.clock, field + '/interval/run')
                        lower = reading[1] >= interval.start_ns if interval.closure.startswith('[') else reading[1] > interval.start_ns
                        upper = reading[1] <= interval.end_ns if interval.closure.endswith(']') else reading[1] < interval.end_ns
                        if not lower or not upper:
                            raise core.FInputError('shape', 'measurement outside its declared interval', field + '/interval')
            if rule.inputs and self.enabled(rule, 'inputs'):
                points = tuple(v for path in rule.inputs for v in self.select(node, path))
                points = tuple(p for group in points for p in (group if isinstance(group, (tuple, list)) else (group,)))
                self.decided(cid, points, field + '/inputs')
            if (rule.boundary is not None and self.enabled(rule, 'boundary') and not node.get('other_run')
                    and not self.unused(cid, node)):
                bound = self.context.observed_ns if rule.boundary == 'observed' else self.context.now_ns
                self.event(cid, boundary=bound, field=field)
        if contract in (fc.COMPUTATION_RESULT, fc.COMPUTATION_PROOF,
                        fc.CANDIDATE_DECLARATION, fc.QUANTITY_DECLARATION):
            self.outer_references(cid, contract, field)
        self.paper_shape(cid, contract, field)
        if contract == fc.OBSERVATION_BINDING:
            self.constraints(GENERATION_INVARIANT, {**node, '$measurement_job': fc.MEASUREMENT_JOB}, field + '/generation')
        if contract in (fc.CONTENT_ACQUIRED, fc.COMPUTATION_COMPLETED):
            # A-12/A-20: a clock reading used as a time witness needs its clock
            # contract at every entrance; null there is a needed unknown.
            for name in ('clock', 'start', 'finish'):
                for reading in node.get(name, ()):
                    for source in reading.get('source', ()):
                        if source['value'].measurement is None:
                            raise core.FSpecificationMissing('missing_contract',
                                'used reading has no clock contract', field + '/' + name + '/source/measurement')
        if contract == fc.CONTEXT_OBSERVED:
            # A-17: the array is the actual check order; clock readings in it
            # never go backwards (equal readings keep their recorded order, U-04).
            previous = None
            for event in node.get('clock_events', ()):
                reading = event['reading']
                if previous is not None:
                    self.aligned(previous[0], reading[0], field + '/check_events/run')
                    self.ordered(previous[1], reading[1], field + '/check_events')
                previous = reading
            self.causal_order(tuple(event.record for event in node['value'].check_events),
                              field + '/check_events')
        # Semantic labels can belong to another row (context.judgment and
        # acquisition.clock). Populate every link before applying defaults.
        for rule in rules:
            for link in rule.links:
                for dependency in node.get(link.name, ()):
                    self.reference_times(node, link, dependency, field + '/' + link.name)
        return node

    def paper_shape(self, cid, contract, field):
        """A-19/A-20: the shape of a preference paper or math artifact is an
        intrinsic check, applied even where no entrance reads its meaning."""
        from .s4d_contracts import PREFERENCE
        from .preference import _parse
        if contract == PREFERENCE:
            try:
                _parse(self.compiler.point(cid))
            except ValueError as exc:
                raise core.FInputError('shape', str(exc), field + '/content') from exc
        elif contract in (fc.STYLE, fc.MATH_ARTIFACT, fc.MATH_ARTIFACT_V2):
            try:
                f_from_json(self.compiler.point(cid).body.content.data, contract=contract)
            except core.FInputError as exc:
                raise core.FInputError('shape', exc.detail, field + '/content' + (exc.field or '')) from exc

    def outer_references(self, cid, contract, field):
        """A-04: body Points and Prediction.about/basis name the same objects.

        "Set" columns are order-free with no repeated Ref; "contains" columns
        may carry further real grounds. This is intrinsic, so every entrance
        (not only the one that replays the computation) applies it.
        """
        body = self.compiler.point(cid).body
        value = self.compiler.content(cid, contract)
        ref = lambda point: self.compiler.point(point).id
        for name in ('about', 'basis'):
            column = getattr(body, name)
            if len(set(column)) != len(column):
                raise core.FInputError('shape', 'repeated outer reference', field + '/' + name)
        about, basis = set(body.about), set(body.basis)
        def same(actual, expected, name):
            if actual != expected:
                raise core.FInputError('proof_mismatch', 'outer references disagree with the body', field + '/' + name)
        def contains(expected, name):
            if not expected <= basis:
                raise core.FInputError('proof_mismatch', 'outer basis lacks a body ground', field + '/' + name)
        def unique(points, name):
            if len(set(points)) != len(points):
                raise core.FInputError('shape', 'repeated body ground', field + '/' + name)
        if contract == fc.COMPUTATION_RESULT:
            request = self.compiler.content(value.request, fc.COMPUTATION_REQUESTED)
            same(about, {ref(value.request)}, 'about')
            same(basis, {ref(value.request), *(ref(p) for p in request.inputs)}, 'basis')
        elif contract == fc.COMPUTATION_PROOF:
            grounds = {ref(value.request), ref(value.result)}
            same(about, grounds, 'about')
            if value.statement.contract == fc.FINITE_UPDATE_STATEMENT:
                # A-10/A-04: the statement names the same request, result and
                # model as the body and the request; checked at every entrance.
                statement = core._decode(value.statement.value, core.FiniteUpdateStatement)
                request = self.compiler.content(value.request, fc.COMPUTATION_REQUESTED)
                model = (core._decode(request.args, core.FiniteUpdateArgs).model
                         if request.method == fc.FINITE_UPDATE else statement.model)
                if (statement.request, statement.result, statement.model) != (value.request, value.result, model):
                    raise core.FInputError('proof_mismatch', 'statement names other objects', field + '/statement')
                same(basis, grounds | {ref(statement.model)}, 'basis')
            else:
                contains(grounds, 'basis')
        elif contract == fc.CANDIDATE_DECLARATION:
            unique(value.generation.basis, 'generation/basis')
            contains({ref(p) for p in value.generation.basis}, 'generation/basis')
        elif value.kind == 'rational_constant':
            unique(value.provenance, 'provenance')
            contains({ref(p) for p in value.provenance}, 'provenance')
        else:
            contains({ref(value.result)}, 'result')

    @staticmethod
    def temporal_row(node):
        """Semantic clock policy depends on the record, never the traversal path."""
        record = node['record']
        return next((r for r in EVENT_INVARIANTS
                     if r.contract == getattr(record.body, 'contract', None)),
                    next(r for r in STRUCTURAL_INVARIANTS if r.body == type(record.body).__name__))

    def reference_times(self, owner, link, dependency, field):
        for label in link.required_known_times:
            if any(isinstance(value, core.Unavailable) for value in self.select(dependency, label)):
                raise core.FIncomplete('certificate_incomplete', 'used route activation clock unavailable', field)
        if link.edge == 'acquires':
            self.acquired_content(owner, dependency, field)
            return
        owner_rule, target_rule = self.temporal_row(owner), self.temporal_row(dependency)
        if link.edge in NO_AVAILABILITY_EDGES or owner_rule.temporal_exception or target_rule.temporal_exception:
            return
        events = link.event_times or owner_rule.event_times
        for available in target_rule.available_times:
            for event in events:
                # Use the same required/null and domain/run/order interpreter
                # for every reference. Unknown is a typed endpoint, not null.
                earlier, later = self.select(dependency, available), self.select(owner, event)
                if not earlier or not later:
                    raise core.FInputError('shape', 'required semantic clock absent', field)
                for a in earlier:
                    for b in later:
                        self.relation('reference availability', dict(available=a, event=b), field)

    def acquired_content(self, owner, dependency, field):
        """available(x, acquire, witness, a) for one ContentAcquired (A-09〜A-12).

        a is the acquisition clock reading. The witness depends on what x is:
        a computation output needs its generation completion g <= a (A-10), a
        static declaration its own record s <= a (A-11), and every notification,
        including clock and context notices, its receipt r <= a (A-08/A-12).
        Adoption is a separate later use and never stands in for these.
        """
        from .records import Observed, Prediction, Interpretation
        acquired = owner['clock'][0]['reading']
        record = dependency['record']
        contract = getattr(record.body, 'contract', None)
        if contract in (fc.COMPUTATION_RESULT, fc.COMPUTATION_PROOF):
            scope = self.closed_points if self.closed_points is not None else self.compiler.visible_cids
            found = False
            for point in sorted(scope):
                if getattr(self.node(point)['record'].body, 'contract', None) != fc.COMPUTATION_COMPLETED:
                    continue
                # A-07/A-10: only a completion naming this target is its witness.
                # Validating unrelated completions first would follow their own
                # inputs back here and invent a cycle absent from the graph.
                try:
                    named = self.compiler.content(point, fc.COMPUTATION_COMPLETED)
                except core.FInputError:
                    named = None  # undecodable: let validation report it
                if named is not None and dependency['cid'] not in (named.result, *named.proofs):
                    continue
                completion = self.validate(point, field + '/generation')
                value = completion['value']
                if dependency['cid'] not in (value.result, *value.proofs):
                    continue
                found = True
                self.relation('generation before acquisition', dict(
                    finish=completion['finish'][0]['reading'], acquired=acquired), field + '/generation')
            if not found:
                raise core.FIncomplete('certificate_incomplete', 'generation evidence absent', field + '/generation')
        elif isinstance(record.body, Observed):
            self.relation('reference availability', dict(available=dependency['actual'], event=acquired), field)
        elif isinstance(record.body, (Prediction, Interpretation)):
            saved = dependency['at']
            if saved[0] != acquired[0] or saved[1] > acquired[1]:
                raise core.FIncomplete('certificate_incomplete', 'declaration recorded after acquisition', field)
        else:
            self.relation('reference availability', dict(available=dependency['actual'], event=acquired), field)

    def numerical_inputs(self, roots):
        """Follow the table's numeric edges, independent of request.inputs."""
        required, pending = set(), list(roots)
        while pending:
            point = pending.pop()
            if point in required:
                continue
            required.add(point)
            node = self.validate(point, '/measurement')
            record = node['record']
            rows = tuple(r for r in STRUCTURAL_INVARIANTS if r.body is None or r.body == type(record.body).__name__)
            rows += tuple(r for r in EVENT_INVARIANTS if r.contract == getattr(record.body, 'contract', None))
            for row in rows:
                for link in row.links:
                    if link.numeric and self.profile in link.profiles:
                        pending.extend(child['cid'] for child in node.get(link.name, ()))
        return required

    def ancestors(self, cid):
        if cid not in self._ancestors:
            self.compiler.tick()
            self._ancestors[cid] = self.compiler.image.ancestors(
                self.compiler.image.entry(cid).parents)
        return self._ancestors[cid]

    def unused(self, cid, node):
        """A-18: the fixed problem's run/j bound applies to the events it uses.
        Another origin's K records, other contexts and clock readings (bounded
        by their own uses, A-12/A-17) stay legal in range without being used."""
        contract = getattr(node['record'].body, 'contract', None)
        origin = getattr(self.compiler, 'origin_point', None)
        selected_context = getattr(self.compiler, 'context_point', None)
        value = node.get('value')
        if contract == fc.CONTEXT_OBSERVED:
            return selected_context is not None and cid != selected_context
        if contract == fc.CLOCK_READING:
            return True
        if origin is None or value is None:
            return False
        if contract in (fc.CONTENT_ACQUIRED, fc.KNOWLEDGE_ADOPTED, fc.COMPUTATION_REQUESTED):
            return value.origin != origin
        if contract == fc.COMPUTATION_COMPLETED:
            return self.node(value.request)['value'].origin != origin
        return False

    def aligned(self, run, expected, field):
        if run != expected:
            raise core.FInputError('clock_unaligned', field=field)

    def ordered(self, earlier, later, field):
        if earlier > later:
            raise core.FInputError('shape', 'event chronology contradicts its readings', field)

    def bind_boundaries(self, context):
        self.context = core._decode(core._encode(context), core.FContext)
        self._context_key = core._digest(self.context)
        self.relation('boundaries', dict(
            observed=self.time(context.run, context.observed_ns),
            now=self.time(context.run, context.now_ns)), '/context/reading')

    def ref_point(self, ref, field):
        """Resolve a versioned Ref to an authenticated, unambiguous ledger CID."""
        cids = self.ref_points(ref, field)
        if len(cids) != 1:
            raise core.FIncomplete('certificate_incomplete', 'record CID not uniquely determined', field)
        return cids[0]

    def ref_points(self, ref, field):
        """Every authenticated CID of a versioned Ref in the allowed range."""
        record = self.compiler.record(ref)
        image = self.compiler.image
        cids = tuple(cid for cid in image._by_id.get(ref, ())
            if cid in self.compiler.visible_cids or
            (not image.entry(cid).is_event and
             image.entry(cid).parents <= self.compiler.visible_cids))
        for cid in cids:
            if core._digest(self.compiler.point(cid)) != core._digest(record):
                raise core.FReplayMismatch('result_mismatch', fields=(field,))
        return cids

    def event(self, cid, *, moments=(), boundary=None, field='/chronology'):
        node = self.basic(cid, field)
        for run, time_ns in moments:
            self.relation('event receipt', dict(moment=self.time(run, time_ns),
                actual=node['actual']), field + '/receipt')
        # A-18: the fixed problem's run/j bound applies to events it uses; a
        # record of another run is legal on its own (A-05) until some use needs it.
        if boundary is not None and not node.get('other_run'):
            self.relation('event boundary', dict(actual=node['actual'],
                boundary=self.time(self.context.run, boundary)), field + '/boundary')
        return node['actual'][1]

    def reference(self, owner, dependency, field):
        """Point was authenticated first; Ref labels only locate that content."""
        record = self.compiler.point(dependency)
        entry = self.compiler.image.entry(dependency)
        ancestors = self.ancestors(owner)
        # §3-10-17-4 G1: a derived leaf (Prediction, Interpretation) is checked
        # by its own parents; an event must be an actual ancestor.
        if ((entry.is_event and dependency not in ancestors)
                or not entry.parents <= ancestors):
            raise core.FInputError('unresolved_reference', 'input unavailable at event', field)
        owner_record = self.compiler.point(owner)
        if record.at.run == owner_record.at.run:
            self.relation('reference saved order', dict(
                dependency=self.time(record.at.run, record.at.mono_ns),
                owner=self.time(owner_record.at.run, owner_record.at.mono_ns)), field + '/record')

    def decided(self, cid, points, field):
        from .records import Decided
        record = self.compiler.point(cid)
        if type(record.body) is not Decided:
            raise core.FInputError('shape', field=field)
        expected = tuple(self.compiler.point(p).id for p in points)
        core._unique(record.body.inputs, field)
        # A-04: Decided.inputs is an order-free set without repeats.
        matches = len(record.body.inputs) == len(expected) and set(record.body.inputs) == set(expected)
        if not matches:
            raise core.FInputError('proof_mismatch', 'body Points and Decided.inputs disagree', field)
        for point in points:
            self.reference(cid, point, field)
        self.event(cid, boundary=None if self.context is None or not self.enforce_boundary else self.context.now_ns, field=field)

    def clock(self, cid):
        node = self.validate(cid, '/clock')
        if cid not in self._clocks:
            value = node['value']
            source = node['source'][0]['value']
            self._clocks[cid] = value.reading, source.measurement
        reading, contract = self._clocks[cid]
        if self.context is not None:
            self.relation('clock/context alignment', dict(run=reading.run,
                context_run=self.context.run, contract=contract,
                context_contract=self.context.clock_contract), '/clock')
        return reading, contract

    def bind_context(self, value, context):
        self.bind_boundaries(context)
        self.validate(self.compiler.context_point, '/context')
        self.check_events(value.check_events, owner=self.compiler.context_point)

    def check_events(self, events, *, owner=None):
        from .records import Category
        for event in events:
            if self.compiler.point(event.record).category is not Category.FACT:
                raise core.FInputError('shape', field='/check_events')
            if owner is not None:
                self.reference(owner, event.record, '/check_events')
            if event.kind == 'clock':
                reading, _ = self.clock(event.record)
                self.relation('clock check event', dict(reading=self.time(reading.run, reading.time_ns),
                    now=self.time(self.context.run, self.context.now_ns)), '/check_events/clock')
            else:
                self.event(event.record, boundary=self.context.observed_ns, field='/check_events/fact')
        self.causal_order(tuple(event.record for event in events), '/check_events')

    def causal_order(self, points, field):
        """A-17: the array is the order actually checked. Equal times keep it,
        but a later item may not be a known actual ancestor of an earlier one."""
        for index, point in enumerate(points):
            ancestors = self.ancestors(point)
            if any(later in ancestors for later in points[index + 1:]):
                raise core.FInputError('shape', 'check order reverses known causality', field)

    def measurement_clock(self, cid, route_epoch):
        if self._measurement_routes is None:
            self._measurement_routes = {}
        key = cid, route_epoch
        if key not in self._measurement_routes:
            routes = []
            for point in sorted(self.ancestors(cid)):
                record = self.node(point)['record']
                if getattr(record.body, 'contract', None) != fc.ROUTE_CONFIG:
                    continue
                payload = record.body.content.as_json()
                config = payload.get('config') if isinstance(payload, dict) else None
                if isinstance(config, dict) and config.get('route_epoch') == route_epoch:
                    routes.append((point, self.compiler.content(point, fc.ROUTE_CONFIG)))
            self._measurement_routes[key] = tuple(routes)
        routes = self._measurement_routes[key]
        if not routes:
            raise core.FReplayUnavailable('missing_input', 'measurement clock contract', '/measurement/clock')
        for point, value in routes:
            self.reference(cid, point, '/measurement/clock')
        return tuple(point for point, _ in routes)

    def measurements(self):
        from .rate_entry import RATE_REPORT
        for cid in sorted(self.compiler.visible_cids):
            record = self.compiler.point(cid)
            contract = getattr(record.body, 'contract', None)
            if contract in (fc.MEASUREMENT, fc.COVERAGE, fc.OBSERVATION_BINDING, RATE_REPORT):
                self.validate(cid, '/measurement')

    def acquire(self, cid, value):
        self.validate(cid, '/acquisition')
        reading, _ = self.clock(value.clock)
        received = self.event(cid, moments=((reading.run, reading.time_ns),),
                              boundary=self.context.now_ns, field='/acquisition')
        core._unique(value.contents, '/contents')
        for point in value.contents:
            self.reference(cid, point, '/acquisition/contents')
        self.acquisitions[cid] = value, reading.time_ns, received

    def completed(self, cid, value):
        self.validate(cid, '/completion')
        self.clock(value.started_clock)
        finish, _ = self.clock(value.finished_clock)
        for acquisition, _, received in self.acquisitions.values():
            if set(acquisition.contents) & {value.result, *value.proofs}:
                self.relation('generation before acquisition', dict(
                    finish=self.time(finish.run, finish.time_ns),
                    acquired=self.time(self.context.run, received)), '/acquisition/generation')

    def acquired_before(self, cid):
        ancestors = self.ancestors(cid)
        event_time = self.event(cid, boundary=self.context.now_ns, field='/adoption')
        points = set()
        for acquisition, (value, reading, received) in self.acquisitions.items():
            if acquisition in ancestors:
                self.relation('available at adoption', dict(
                    reading=self.time(self.context.run, reading),
                    received=self.time(self.context.run, received),
                    adopted=self.time(self.context.run, event_time)), '/adoption/acquisition')
                points.update(value.contents)
        return frozenset(points)


def implementation_id(registry, kind, ref):
    """今の約束 V-11・E-05: the explicitly registered, immutable implementation identity."""
    implementation = next((i for i in registry.implementations if i.kind == kind and i.ref == ref), None)
    return None if implementation is None else implementation.identity


def facts_dependencies(facts, users):
    """今の約束 E-05 FFactsDependencies from the compiler's captured image.

    Points are the authenticated closure (entry and body present), models the
    declared model Point and document digest, capabilities what the users
    called, ref_lookups every Ref resolved with all matching CIDs (P7).
    """
    points = tuple(core.FFactsPointDependency(point=cid, entry_present=True, body_present=True,
        record=facts.image._records[cid].id, record_digest=core._digest(facts.image._records[cid]))
        for cid in sorted(facts.selected))
    models = (core.FFactsModelDependency(point=facts.source, model_ref=facts.model_key),)
    called = {}
    for user in users:
        for dependency in user.capabilities.values():
            called[(dependency.kind, dependency.ref.name, dependency.ref.version)] = dependency
    capabilities = tuple(core.FFactsCapabilityDependency(kind=d.kind, ref=d.ref, declaration=d.declaration,
        implemented=d.implemented, implementation_id=implementation_id(facts.registry, d.kind, d.ref) if d.implemented else None)
        for _, d in sorted(called.items()))
    lookups = tuple(core.FFactsRefLookup(ref=ref, points=points_)
        for ref, points_ in sorted(facts.ref_lookups.items(), key=lambda item: core._dumps(item[0])))
    return core.FFactsDependencies(points=points, models=models, capabilities=capabilities,
        ref_lookups=lookups, absence_environment=None)


def certify_closure(compiler, *, roots, context, profile='facts', post_problem=False):
    """Authenticate one immutable reachable set, then apply every applicable row.

    Its read accounting is deliberately separate from mathematical input/manifest
    accounting. A draw extension has the real context's run/clock, but cannot use
    the old judgment as a maximum timestamp for legitimate later draw ancestors.
    No validation memo survives this closure or is imported from context decoding.
    """
    audit = _WorldCompiler()
    audit.image = audit.ledger = compiler.image
    audit.budget = compiler.budget
    audit.tick = compiler.tick
    audit.records = {}
    audit.verified_records = set()
    audit.visible_ready = True
    audit.visible_cids = compiler.visible_cids
    audit.by_record = dict(compiler.by_record)
    audit.selected = set(audit.visible_cids) | set(roots)
    audit.origin_point = getattr(compiler, 'origin_point', None)
    audit.context_point = getattr(compiler, 'context_point', None)
    audit._closure_profile = profile
    authenticated_points = {}
    point_reader = audit.point
    identity = None if context is None else core._digest(context)
    def closure_point(cid):
        key = cid, identity
        if key not in authenticated_points:
            authenticated_points[key] = point_reader(cid)
        return authenticated_points[key]
    audit.point = closure_point
    FactsCompiler._expand(audit)
    identities = {}
    for point in sorted(audit.selected):
        record = audit.point(point)
        if record.id in identities and core._digest(identities[record.id]) != core._digest(record):
            raise core.FReplayMismatch('result_mismatch',fields=('/records',))
        identities[record.id] = record
    audit.by_record = identities
    order = _FactsOrder(audit)
    order.profile = profile
    order.enforce_boundary = not post_problem
    if context is not None:
        order.bind_boundaries(context)
    order.closed_points = frozenset(audit.selected)
    order._memoize = True
    # V-08 before any use: a later reader must not fall back to "absent" for a
    # known contract written at an undeclared version.
    for point in sorted(order.closed_points):
        _check_contract_version(order.node(point)['record'], '/records')
    for point in sorted(order.closed_points):
        order.validate(point)
    # Relations that quantify over explicit acquired contents are also part of
    # the set predicate, including adoptions reached only through a later draw.
    for point in sorted(order.closed_points):
        node = order.node(point)
        contract = getattr(node['record'].body,'contract',None)
        for row in EVENT_INVARIANTS:
            if row.contract != contract or not row.availability:
                continue
            required = set(v for path in row.availability for group in order.select(node,path)
                           for v in (group if isinstance(group,(tuple,list)) else (group,)))
            acquired = set()
            for ancestor in sorted(order.ancestors(point)):
                candidate = order.node(ancestor)
                if getattr(candidate['record'].body,'contract',None) != row.availability_contract:
                    continue
                value = candidate['value']
                if value.origin != node['value'].origin or not required.intersection(value.contents):
                    continue
                order.relation('available at adoption', dict(reading=candidate['clock'][0]['reading'],
                    received=candidate['actual'],adopted=node['at']), '/adoption/acquisition')
                # g <= a for this acquisition is checked once for every
                # acquisition (acquired_content, 今の約束 A-10), not per use.
                acquired.update(value.contents)
            if not required <= acquired:
                raise core.FInputError('proof_mismatch','adoption lacks ancestral acquisition','/adoption')
    if context is not None and not post_problem:
        # This is a predicate over the entire set, separate from each context's
        # intrinsic check_events. Do not compare wrapper save delays to readings.
        from .records import Category
        for point in sorted(order.closed_points):
            node = order.node(point)
            if node['record'].category is not Category.FACT:
                continue
            contract = getattr(node['record'].body, 'contract', None)
            row = next((r for r in EVENT_INVARIANTS if r.contract == contract), STRUCTURAL_INVARIANTS[0])
            if row.scope_time is None or node.get('other_run') or order.unused(point, node):
                continue
            for moment in order.select(node, row.scope_time):
                if isinstance(moment, tuple) and moment[1] is None:
                    continue  # A-20: unknown, and not needed by this bound
                order.relation('event boundary', dict(actual=moment,
                    boundary=order.time(context.run, context.now_ns)), '/closure/judgment')
    return order


def certify_reader_closure(image, *, roots, budget, visible=None, context=None, post_problem=False):
    """The same set predicate for entries without a mathematical world compiler."""
    compiler = _WorldCompiler()
    compiler.image = compiler.ledger = image
    compiler.budget = budget
    compiler.cells = 0
    compiler.records = {}
    compiler.verified_records = set()
    compiler.visible_ready = True
    compiler.visible_cids = image.ancestors(roots) if visible is None else visible
    compiler.by_record = {r.id:r for r in image._records.values() if not isinstance(r,_UnreadLedgerRecord)}
    return certify_closure(compiler, roots=roots, context=context, post_problem=post_problem)


class FactsCompiler(_WorldCompiler):
    """Required primary closure shared by all facts-only readers and factories."""
    def __init__(self, reader, *, fixed_parents, model_ref, context_ref, registry, budget, extra_points=()):
        from types import SimpleNamespace
        core._require(registry,core.FRegistry)
        budget=core._decode(core._encode(budget),core.RateBudget)
        check_points((*fixed_parents,model_ref,context_ref))
        core._unique(fixed_parents,'/fixed_parents')
        if tuple(sorted(fixed_parents)) != tuple(fixed_parents):
            raise core.FInputError('noncanonical',field='/fixed_parents')
        self.image = capture_reader(reader,budget)
        self.ref_lookups = {}
        self.request = SimpleNamespace(parents=frozenset(fixed_parents))
        records = tuple(r for r in self.image._records.values() if not isinstance(r,_UnreadLedgerRecord))
        resources = core._handle(core.FResources,authority=MappingProxyType({}),models=(),
            records=records,registry=registry,preference_ledger=self.image)
        self._setup(resources,budget)
        self.visible_input()
        self.source = model_ref
        self.context_point = context_ref
        for cid in sorted(self.visible_cids):
            self.point(cid)
        source = self.content(model_ref,fc.MODEL_SOURCE)
        from .f_model import f_model11_from_json
        document = core._dumps(source.document)
        scheme = source.document.get('scheme')
        if scheme == 'sui.model.11':
            self.model = f_model11_from_json(document)
            self.model_key = f_model_ref(self.model)
        else:
            from .model import model_from_json, model_ref as legacy_ref
            self.model = model_from_json(document)
            self.model_key = legacy_ref(self.model)
        self.models[self.model_key] = core.FModelDependency(ref=self.model_key,present=True)
        # Expand only references reachable from fixed facts and requested declarations.
        self.selected = set(self.visible_cids) | {model_ref,context_ref}
        self._expand()
        self._resources()
        self.order = _FactsOrder(self)
        self.context = self._context()
        self.order = certify_closure(self, roots=(*self.selected, *extra_points), context=self.context)
        self.order.measurements()
        self.acquired = self._acquisitions()

    def _expand(self):
        point_fields={
            core.KnowledgeOrigin:('model',),core.ContentAcquired:('origin','contents','clock'),
            core.ComputationRequested:('origin','inputs','algorithm_draws'),
            core.ComputationResult:('request',),core.ComputationProof:('request','result'),
            core.ComputationCompleted:('request','result','proofs','started_clock','finished_clock'),
            core.KnowledgeAdopted:('origin','completion','previous'),
            core.FClockReadingFact:('source',),
            core.FContextObserved:('knowledge_origin','observation_reading','judgment_reading'),
            core.FContextCheckEvent:('record',),core.FCandidateDeclaration:('model',),
            core.FCandidateGeneration:('basis','draws'),
            core.FiniteUpdateArgs:('model','previous_result','observations'),
            core.FiniteUpdateStatement:('model','request','result'),
            core.MeasurementRequested:('plan',),core.MeasurementJob:('plan',),
            core.FQuantityConstantDeclaration:('provenance',),
            core.FQuantityEvaluationDeclaration:('result',)}
        def add_point(value):
            if value is None:return
            if isinstance(value,(tuple,list)):
                for p in value:add_point(p)
                return
            import re
            if type(value) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}',value) is None:
                raise core.FInputError('reference_kind',field='/point')
            self.point(value);self.selected.add(value)
        def references(value):
            if isinstance(value,core._Ref):
                from .ids import RefKind
                if value.kind in (RefKind.RUN,RefKind.INDIVIDUAL):return
                if value not in self.image._by_id:
                    raise core.FReplayUnavailable('missing_input',str(value),'/reference')
                eligible=[]
                for cid in self.image._by_id[value]:
                    entry=self.image._entries[cid]
                    if cid in self.visible_cids or (not entry.is_event and entry.parents <= self.visible_cids):
                        eligible.append(cid)
                if not eligible:raise core.FReplayUnavailable('missing_input',str(value),'/reference')
                if getattr(self,'ref_lookups',None) is not None:
                    self.ref_lookups[value]=tuple(sorted(eligible))
                self.selected.update(eligible)
            elif type(value) is core.PredicateRef:
                # A-06/M-11: every child of a predicate is resolved before any
                # evaluation; short-circuiting never hides a malformed child.
                def walk(node):
                    name,args=(node.name,node.args) if type(node) is core.PredicateRef else (node.get('name'),node.get('args') or {})
                    if name=='interval_compare':
                        import re
                        for side in ('left','right'):
                            key=(args.get(side) or {}).get('key')
                            if key is None:continue
                            if type(key) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}',key) is None:
                                raise core.FInputError('reference_kind','predicate key is not a Point','/predicate/args/'+side+'/key')
                            # Whether it names a quantity Point is M-12's question
                            # (quantity_refs); a non-Point digest is not resolved here.
                            if key in self.image._entries:add_point(key)
                    for child in (args.get('terms') or ()):walk(child)
                    if args.get('term') is not None:walk(args['term'])
                walk(value)
            elif is_dataclass(value):
                for field in point_fields.get(type(value),()):add_point(getattr(value,field))
                if type(value) is core.ComputationRequested and value.method==fc.FINITE_UPDATE:
                    references(core._decode(value.args,core.FiniteUpdateArgs))
                if type(value) is core.ComputationProof and value.statement.contract==fc.FINITE_UPDATE_STATEMENT:
                    references(core._decode(value.statement.value,core.FiniteUpdateStatement))
                for field in fields(value):
                    if field.name not in ('id','at','producer','route','source_id'):
                        references(getattr(value,field.name))
            elif isinstance(value,core._Mapping):
                for v in value.values(): references(v)
            elif isinstance(value,(tuple,list,frozenset)):
                for v in value: references(v)
        from .f_entry import _wire_types
        schemas,_=_wire_types()
        done = set()
        while self.selected - done:
            for cid in sorted(self.selected - done):
                record = self.point(cid)
                references(record.body)
                contract=getattr(record.body,'contract',None)
                # Only declared reference fields are followed. Arbitrary payload
                # strings, model meaning keys and artifact claims are not CIDs.
                if contract in schemas and contract not in (fc.MATH_ARTIFACT,fc.MATH_ARTIFACT_V2,fc.MODEL_SOURCE):
                    references(self.content(cid, contract))
                done.add(cid)

    def _resources(self):
        records = tuple(self.point(cid) for cid in sorted(self.selected))
        identities={}
        for record in records:
            digest=core._digest(record)
            if record.id in identities and identities[record.id]!=digest:
                raise core.FReplayMismatch('result_mismatch',fields=('/records',))
            identities[record.id]=digest
        self.resources = core._handle(core.FResources,authority=MappingProxyType({self.model_key:self.model}),
            models=(self.model,),records=records,registry=self.tracking_registry(),preference_ledger=self.image)
        self.by_record = {r.id:r for r in records}

    def _reading(self,cid):
        # Decode the context's declared clocks without walking its provenance.
        # The fresh closure predicate below validates that entire graph exactly
        # once, with the resulting context already fixed.
        from .clock_contracts import SOURCE, clock_source_from_json
        from .action_types import ActionInputError
        value = self.content(cid,fc.CLOCK_READING)
        record = self.payload(value.source,SOURCE)
        try:
            source = clock_source_from_json(record.body.content.as_json())
        except ActionInputError as exc:
            raise core.FInputError('shape',exc.detail,'/clock/source') from exc
        return value.reading,source.measurement

    def _context(self):
        from .records import Category
        value = self.content(self.context_point,fc.CONTEXT_OBSERVED)
        self.origin_point = value.knowledge_origin
        origin = self.content(self.origin_point,fc.KNOWLEDGE_ORIGIN)
        if origin.model != self.source:
            raise core.FInputError('unresolved_reference',field='/knowledge_origin/model')
        observed,oc = self._reading(value.observation_reading)
        now,nc = self._reading(value.judgment_reading)
        ancestors = {cid:frozenset(str(self.image._entries[c].id) for c in self.image.ancestors((cid,))
            if self.image._entries[c].category is Category.FACT) for cid in sorted(self.visible_cids)}
        events=[]
        for event in value.check_events:
            record = self.point(event.record)
            if event.kind == 'clock':
                reading,_ = self._reading(event.record)
                events.append({'kind':'clock','value':core._encode(reading)})
            else:
                if record.category is not Category.FACT: raise core.FInputError('shape',field='/check_events')
                events.append({'kind':'fact','value':str(record.id)})
        context = core.FContext(run=now.run,now_ns=now.time_ns,observed_ns=observed.time_ns,
            clock_contract=nc,check_events=tuple(core._freeze(e) for e in events),fact_ancestors=MappingProxyType(ancestors))
        return context

    def _acquisitions(self):
        acquired=set()
        for cid in sorted(self.visible_cids):
            record=self.point(cid)
            if getattr(record.body,'contract',None) == fc.CONTENT_ACQUIRED:
                value=self.content(cid,fc.CONTENT_ACQUIRED)
                if value.origin != self.origin_point: continue
                self.order.acquire(cid, value)
                for point in value.contents:
                    self.point(point); acquired.add(point)
        return frozenset(acquired)

    def histories(self):
        from .f_entry import read_f_observations
        from .records import Category
        observations=read_f_observations(self.model,self.resources.records,resources=self.resources)
        by_id=self.by_record
        links,coverage,gaps={},[],[]
        for observation in observations:
            binding=f_from_json(by_id[observation.binding].body.content.data,contract=fc.OBSERVATION_BINDING)
            for ref in observation.records:
                raw=by_id[ref]
                if raw.body.contract==fc.COVERAGE:
                    value=f_from_json(raw.body.content.data,contract=fc.COVERAGE)
                    if isinstance(value,core.CoverageClaim) and value not in coverage: coverage.append(value)
                    elif isinstance(value,core.Gap) and value not in gaps: gaps.append(value)
                    continue
                frame=f_from_json(raw.body.content.data,contract=fc.MEASUREMENT)
                old=links.get(frame.measurement_id)
                links[frame.measurement_id]=core.EvidenceLink(measurement=frame.measurement_id,
                    records=tuple(sorted(set((() if old is None else old.records)+(ref,)),key=str)),
                    generated_by=tuple(sorted(set((() if old is None else old.generated_by)+binding.generated_by),key=str)),
                    derived_from=binding.derived_from,contract=f_from_json(by_id[binding.plan].body.content.data,contract=fc.OBSERVATION_PLAN).measurement_contract)
        values=dict(links=tuple(links.values()),coverage=tuple(coverage),gaps=tuple(gaps))
        E=core.EvidenceHistory(key=core._digest(values),**values)
        available=tuple(m for m,link in links.items() if any(cid in self.acquired for ref in link.records for cid in self.image._by_id[ref]))
        obs_by_ref={o.binding:o for o in observations}
        completed={}; computed={}; normalization=[]; queries=[]; pending=[]; proved_normalization=set()
        all_requests={cid:self.content(cid,fc.COMPUTATION_REQUESTED) for cid in sorted(self.visible_cids)
            if getattr(self.point(cid).body,'contract',None)==fc.COMPUTATION_REQUESTED}
        requests={cid:value for cid,value in all_requests.items() if value.origin==self.origin_point}
        for cid,request in requests.items():
            # Pending requests are real events too, even before any result is
            # available. The outer binding/order is independent of the method.
            self.order.validate(cid, '/request')
        for cid in sorted(self.visible_cids):
            if getattr(self.point(cid).body,'contract',None)!=fc.COMPUTATION_COMPLETED: continue
            value=self.content(cid,fc.COMPUTATION_COMPLETED)
            if value.request not in all_requests: raise core.FInputError('unresolved_reference',field='/completion/request')
            if value.request not in requests: continue
            self.order.completed(cid,value)
            core._unique(value.proofs,'/completion/proofs')
            if value.request in completed: raise core.FIncomplete('certificate_incomplete','competing_completions')
            completed[value.request]=(cid,value)
        visiting=set()
        def calculate(request_point):
            if request_point in computed: return computed[request_point]
            if request_point in visiting: raise core.FInputError('proof_mismatch',field='/computation/cycle')
            visiting.add(request_point)
            request=requests[request_point]
            if request.origin!=self.origin_point: raise core.FInputError('unresolved_reference',field='/request/origin')
            if request.method!=fc.FINITE_UPDATE:
                if request.method.name==fc.FINITE_UPDATE.name:
                    raise core.FInputError('unknown_version',field='/request/method')
                raise core.FIncomplete('algorithm_unavailable',field='/request/method')
            args=core._decode(request.args,core.FiniteUpdateArgs)
            if args.model!=self.source or request.output_contract!=fc.FINITE_UPDATE_RESULT or request.algorithm_draws:
                raise core.FInputError('proof_mismatch',field='/request')
            # M-02: inputs I is a set; observations is the application sequence,
            # where a repeated transition is a no-op (M-04), not a malformed list.
            core._unique(request.inputs,'/inputs')
            necessary={self.origin_point,self.source}
            necessary.update(self.order.numerical_inputs(args.observations))
            if args.previous_result is not None:
                previous=self.content(args.previous_result,fc.COMPUTATION_RESULT)
                if (previous.request not in requests or previous.request not in completed
                        or completed[previous.request][1].result!=args.previous_result):
                    raise core.FInputError('proof_mismatch',field='/previous_result')
                oldcid,oldcompletion=completed[previous.request]
                necessary.update((args.previous_result,previous.request,oldcid,*oldcompletion.proofs,
                    *requests[previous.request].inputs))
            if not necessary<=set(request.inputs):
                raise core.FInputError('unresolved_reference','incomplete finite_update inputs','/inputs')
            input_refs=tuple(self.point(point).id for point in request.inputs)
            request_record=self.point(request_point)
            if args.previous_result is None: belief=core.initial_finite_belief(self.model)
            else:
                previous=self.content(args.previous_result,fc.COMPUTATION_RESULT)
                belief=calculate(previous.request)
            for point in args.observations:
                ref=self.point(point).id
                if ref not in obs_by_ref: raise core.FInputError('unresolved_reference',field='/observations')
                belief=core.apply_f_observation(self.model,belief,observation=obs_by_ref[ref])
            # finite_update/1 is a closed primary method of compiler/2. Its
            # replay calls explicitly supplied finite_kernel implementations
            # through apply_f_observation, without filling in capabilities.
            for kernel in _parts(self.model)[1]:
                self.capability('kernel',core._ContractRef('finite_kernel','1'),{'id':kernel})
            if request_point not in completed: raise core.FIncomplete('certificate_incomplete',field='/completion')
            _,completion=completed[request_point]
            result=self.content(completion.result,fc.COMPUTATION_RESULT)
            result_record=self.point(completion.result)
            if result_record.body.about!=(request_record.id,) or set(result_record.body.basis)!={request_record.id,*input_refs}:
                raise core.FInputError('proof_mismatch',field='/result/basis')
            expected=core.FiniteUpdateResult(joint=belief.joint,evidence_mass=belief.evidence_mass)
            if result.request!=request_point or result.output.contract!=request.output_contract or core._dumps(result.output.value)!=core._dumps(expected):
                raise core.FInputError('proof_mismatch',field='/result')
            for point in completion.proofs:
                proof=self.content(point,fc.COMPUTATION_PROOF)
                proof_record=self.point(point)
                if set(proof_record.body.about)!={request_record.id,result_record.id} or set(proof_record.body.basis)!={request_record.id,result_record.id,self.point(self.source).id}:
                    raise core.FInputError('proof_mismatch',field='/proof/basis')
                expected_statement=core.FiniteUpdateStatement(model=self.source,request=request_point,result=completion.result)
                if (proof.request!=request_point or proof.result!=completion.result or proof.statement.contract!=fc.FINITE_UPDATE_STATEMENT
                    or core._dumps(proof.statement.value)!=core._dumps(expected_statement)):
                    raise core.FInputError('proof_mismatch',field='/proof')
                if proof.checker.name==fc.FINITE_UPDATE_REPLAY.name and proof.checker.version!=fc.FINITE_UPDATE_REPLAY.version:
                    raise core.FInputError('unknown_version',field='/proof/checker')
                if (proof.checker.name,proof.checker.version)!=('sui.f.finite_update_replay','1') or proof.checker.args:
                    raise core.FIncomplete('certificate_incomplete',field='/proof/checker')
                # Equality was independently established by replay above;
                # no boolean assertion in the supplied proof is trusted.
                if proof.role=='normalization':proved_normalization.add(request_point)
                if point in self.acquired:
                    (normalization if proof.role=='normalization' else queries).append(self.point(point).id)
            computed[request_point]=belief
            visiting.remove(request_point)
            return belief
        adoptions={cid:self.content(cid,fc.KNOWLEDGE_ADOPTED) for cid in sorted(self.visible_cids)
            if getattr(self.point(cid).body,'contract',None)==fc.KNOWLEDGE_ADOPTED}
        adoptions={cid:value for cid,value in adoptions.items() if value.origin==self.origin_point}
        for cid,adoption in adoptions.items():
            self.order.validate(cid, '/adoption')
            completion=self.content(adoption.completion,fc.COMPUTATION_COMPLETED)
            if completion.request not in requests:
                raise core.FInputError('proof_mismatch',field='/adoption/origin')
            if adoption.previous is not None and adoption.previous not in adoptions:
                raise core.FInputError('proof_mismatch',field='/adoption/previous')
        # A-16 (履歴 §3-10-17-5 K3, R04): adopting one derivation again is a new
        # adoption event, not a new application. Identical (completion,
        # previous) adoptions are one link; a re-adoption chained on the earlier
        # adoption keeps the chain logic below (applied once).
        first,alias={},{}
        for cid in sorted(adoptions,key=lambda c:(self.point(c).at.run_index,self.point(c).at.seq,c)):
            key=(adoptions[cid].completion,adoptions[cid].previous)
            if key in first:alias[cid]=first[key]
            else:first[key]=cid
        adoptions={cid:(core._replace(a,previous=alias[a.previous]) if a.previous in alias else a)
            for cid,a in adoptions.items() if cid not in alias}
        for point in completed:
            try:calculate(point)
            except core.FIncomplete:
                # An unverified, unrelated cache cannot become K.belief, but
                # does not by itself invalidate otherwise usable knowledge.
                visiting.clear()
        leaves=set(adoptions)-{a.previous for a in adoptions.values() if a.previous is not None}
        if len(leaves)>1: raise core.FIncomplete('certificate_incomplete','competing_adoptions')
        belief_ref=None; incorporated=()
        self.knowledge_joint=core._decode(_parts(self.model)[0]['initial'],tuple[core._Fraction,...])
        if leaves:
            point=next(iter(leaves)); chain=[]; seen=set()
            while point is not None:
                if point in seen or point not in adoptions: raise core.FInputError('proof_mismatch',field='/adoption/previous')
                seen.add(point); chain.append((point,adoptions[point])); point=adoptions[point].previous
            previous_result=None; previous_completion=None
            for cid,adoption in reversed(chain):
                if adoption.origin!=self.origin_point: raise core.FInputError('proof_mismatch',field='/adoption/origin')
                completion=self.content(adoption.completion,fc.COMPUTATION_COMPLETED)
                request=requests[completion.request]; args=core._decode(request.args,core.FiniteUpdateArgs)
                belief=calculate(completion.request)
                if completion.request not in proved_normalization:
                    raise core.FIncomplete('certificate_incomplete','normalization proof missing','/adoption/proof')
                # Re-adopting the same authenticated derivation does not run a
                # second update or reinterpret its original previous_result.
                if adoption.completion!=previous_completion and args.previous_result!=previous_result:
                    raise core.FInputError('proof_mismatch',field='/adoption/previous')
                acquired=self.order.acquired_before(cid)
                if completion.result not in acquired or not set(completion.proofs)<=acquired:
                    raise core.FInputError('proof_mismatch','unacquired adoption','/adoption')
                historical_available={m for m,link in links.items() if any(
                    point in acquired for ref in link.records for point in self.image._by_id[ref])}
                if not {m for applied in belief.applied for m in applied.measurements}<=historical_available:
                    raise core.FInputError('proof_mismatch','unacquired adopted measurements','/adoption/measurements')
                previous_result=completion.result
                previous_completion=adoption.completion
            belief_ref=self.point(previous_result).id
            self.knowledge_joint=belief.joint
            incorporated=tuple(dict.fromkeys(m for a in belief.applied for m in a.measurements))
            if not set(incorporated)<=set(available): raise core.FInputError('proof_mismatch',field='/adoption/measurements')
        adopted_requests={self.content(a.completion,fc.COMPUTATION_COMPLETED).request for a in adoptions.values()}
        for point,request in requests.items():
            if point in adopted_requests: continue
            completion=completed.get(point)
            stage=('result' if completion is None else
                'acquisition' if completion[1].result not in self.acquired else
                'proof' if point not in proved_normalization or not set(completion[1].proofs)<=self.acquired else 'adoption')
            required=() if completion is None else (completion[1].result,*completion[1].proofs)
            description=core.FKnowledgeDependency(domain=fc.KNOWLEDGE_DEPENDENCY_DOMAIN,request=point,stage=stage,required=required)
            pending.append(core.DependencyRef(key=core._digest(description),basis=(self.point(point).id,)))
        values=dict(available=available,incorporated=incorporated,belief=belief_ref,
            kernel_basis=tuple(sorted(obs_by_ref,key=str)),normalization_proofs=tuple(dict.fromkeys(normalization)),
            query_proofs=tuple(dict.fromkeys(queries)),pending=tuple(pending))
        K=core.KnowledgeHistory(key=core._digest(values),**values)
        descriptor=issue(core._handle(core.FFiniteUpdateModel,authority=FiniteModelAuthority(self.model,self.source,self.resources),
            source=self.source,model_ref=self.model_key,compiler=fc.PREPARE_FACTS,
            authority_key=core._digest({'model':self.source,'record':self.point(self.source),'E':E,'K':K})))
        return issue(core._handle(core.FHistoriesFromFacts,authority=self.resources,model=descriptor,E=E,K=K,
            context=self.context,observations=observations))


class _Compiler(FactsCompiler):
    """Normal compiler accepts only primary requests and authenticated Points."""
    _world_domain='sui.f.world/3'
    _problem_contract=fc.PROBLEM_FACTS
    _problem_domain='sui.f.problem/3'

    def __init__(self, request, *, reader, registry, budget):
        self.facts_request=core._decode(core._encode(request),core.FFactsRequest)
        super().__init__(reader,fixed_parents=request.fixed_parents,model_ref=request.model,
            context_ref=request.context,registry=registry,budget=budget,
            extra_points=(request.candidates,*request.preferences))

    def _material(self):
        from types import SimpleNamespace
        from .f_entry import resolve_f_preferences
        from .records import Category
        if type(self.model) is not FModel11: raise core.FInputError('shape','model.11 required','/model')
        request=self.facts_request
        declaration=self.content(request.candidates,fc.CANDIDATE_DECLARATION)
        if declaration.model!=request.model: raise core.FInputError('unresolved_reference',field='/candidates/model')
        self.selected.add(request.candidates); self._expand(); self._resources()
        histories=self.histories()
        view=self.preference_input()
        specified={self.point(p).id for p in request.preferences}
        if specified!={p.id for p in view.points}: raise core.FInputError('unresolved_reference','preference Point set','/preferences')
        resolved=resolve_f_preferences(view,resources=self.resources)
        if resolved.scope!=request.scope: raise core.FInputError('scope_mismatch',field='/scope')
        _,kernels,_,operations=_parts(self.model)
        core._unique(declaration.input_order,'/input_order',nonempty=True)
        if not set(declaration.input_order)<=operations.keys(): raise core.FInputError('unresolved_reference',field='/input_order')
        if tuple(a.candidate for a in declaration.continuation.after)!=declaration.input_order: raise core.FInputError('shape',field='/continuation')
        generation=declaration.generation
        for p in generation.basis:self.point(p)
        draws=tuple(read_draw(self.image,p,budget=self.budget,parents=self.request.parents,
            context=self.context,certified_order=self.order,purpose='candidate_generation',context_key=core._digest(core.FCandidateRequest(domain=fc.CANDIDATE_REQUEST_DOMAIN,
                model=self.source,generator=generation.generator,args=generation.args,basis=generation.basis))) for p in generation.draws)
        actions=tuple(operations[n] for n in declaration.input_order)
        self.capability('generator',generation.generator,generation.args)
        generated=core._call_capability('generator',generation.generator,args=generation.args,
            input=core._encode(core.CandidateInput(actions=actions,basis=tuple(self.point(p).id for p in generation.basis),draws=draws)),
            resources=self.resources,registry=self.resources.registry,budget=self.budget)
        expected=core.CandidateInput(actions=actions,basis=tuple(self.point(p).id for p in generation.basis),draws=draws)
        if core._dumps(generated)!=core._dumps(expected): raise core.FInputError('proof_mismatch',field='/generation')
        measure=declaration.measure
        if measure is None and generation.generator==core._ContractRef('sui.f.explicit_candidates','1'):
            if generation.draws: raise core.FInputError('invalid_draw',field='/generation')
            measure=core.CandidateMeasureRef(name='counting',version='1',args={})
        if measure is None and generation.generator.name=='fixture.f.bit_order':
            measure=core.CandidateMeasureRef(name='counting',version='1',args={})
        candidates=core.canonical_candidates(actions,measure=measure,generator=generation.generator,
            basis=expected.basis,draws=draws,registry=self.resources.registry)
        after={}; canonical=[]
        for value in declaration.continuation.after:
            representative=candidates.aliases.get(value.candidate,value.candidate)
            if representative in after and after[representative]!=value.policy:
                raise core.FInputError('alias_continuation_conflict',field='/continuation')
            after[representative]=value.policy
        for action in candidates.candidates:canonical.append(core.ContinuationAfter(candidate=action.id,policy=after[action.id]))
        continuation=core.FContinuation(after=tuple(canonical))
        # Every primary alias proof is checked even when its meaning collapses.
        for action in actions:
            self.capability('proof',core._ContractRef(action.proof.name,action.proof.version),action.proof.args)
            checked=core._decode(core._call_capability('proof',core._ContractRef(action.proof.name,action.proof.version),
                args=action.proof.args,input=core._encode(core.ModelInput(model_ref=self.model_key)),resources=self.resources,
                registry=self.resources.registry,model_ref=self.model_key,budget=self.budget),core.ProofCheck)
            if checked.status!='proved': raise core.FInputError('proof_mismatch',field='/candidates/proof')
        self.request=SimpleNamespace(model_ref=self.model_key,parents=frozenset(request.fixed_parents),
            records=tuple(r.id for r in self.resources.records),E=histories.E,K=histories.K,context=histories.context,
            resolved=resolved,candidates=candidates,continuation=continuation,method=request.method)
        values=dict(model_ref=self.model_key,parents=self.request.parents,
            facts=tuple(sorted((r.id for r in self.resources.records if r.category is Category.FACT),key=str)),
            E=histories.E,K=histories.K,context=histories.context,preferences=resolved.items,style=resolved.style,
            scope=resolved.scope,gamma=resolved.gamma,candidates=candidates,continuation=continuation,
            measurement_contracts=tuple(sorted({o.evidence.measurement_contract for k in kernels.values() for o in k.outcomes if o.evidence is not None},key=lambda c:(c.name,c.version))),
            execution_contracts=tuple(dict.fromkeys(a.execution for a in candidates.candidates)),method=request.method)
        return self.model,self.resources.records,self.resources,values

    def _manifest(self):
        return core.FWorldManifest3(contract=fc.WORLD_MANIFEST_FACTS,compiler=fc.PREPARE_FACTS,
            request=core.FMathFactsInput(kind='facts',value=self.facts_request),
            dependencies=facts_dependencies(self,(self,)),preference_causality=self.preference_causality)

    def _prior_joint(self,data):
        return self.knowledge_joint


class BridgeCompiler(_WorldCompiler):
    """Pure certified correspondence from legacy facts; no synthetic ledger."""
    _world_domain='sui.f.world/3'
    _problem_contract=fc.PROBLEM_FACTS
    _problem_domain='sui.f.problem/3'

    def __init__(self, facts, request, finite, actions, resolved, budget, bit=None):
        from types import SimpleNamespace
        self.facts,self.primary_request,self.model,self.bit=facts,request,finite,bit
        self.request=SimpleNamespace(parents=frozenset(request.fixed_parents))
        self._setup(core._handle(core.FResources,authority=MappingProxyType({f_model_ref(finite):finite}),
            models=(finite,),records=facts.resources.records,registry=facts.registry,preference_ledger=facts.image),budget)
        self.visible_input()
        self.preference_causality=facts.preference_causality
        self.resolved=core._handle(core.FResolved,authority=self.resources,items=tuple(i.id for i in resolved.items),
            style=resolved.style,scope=core.EvaluationScope(name='finite_horizon' if bit is not None else 'one_step',
                version='1',H_ns=resolved.H_ns,source=resolved.style),gamma=core._Fraction(resolved.gamma),
            item_contracts=tuple(facts.by_record[i.id].body.contract for i in resolved.items),proofs=())
        candidates=core.canonical_candidates(actions,measure=core.CandidateMeasureRef(name='counting',version='1',args={}),
            generator=core._ContractRef('sui.f.explicit_candidates','1'),basis=(facts.point(facts.source).id,),draws=(),registry=facts.registry)
        E=core.EvidenceHistory(key=core._digest({'links':(),'coverage':(),'gaps':()}),links=(),coverage=(),gaps=())
        kvals=dict(available=(),incorporated=(),belief=None,kernel_basis=(),normalization_proofs=(),query_proofs=(),pending=())
        K=core.KnowledgeHistory(key=core._digest(kvals),**kvals)
        self.request=SimpleNamespace(model_ref=f_model_ref(finite),parents=frozenset(request.fixed_parents),
            E=E,K=K,context=facts.context,resolved=self.resolved,candidates=candidates,
            continuation=core.FContinuation(after=tuple(core.ContinuationAfter(candidate=a.id,policy=None) for a in actions)),
            method=core._ContractRef('sui.f.finite_evaluation','1'))

    def _material(self):
        from .records import Category
        request=self.request
        values=dict(model_ref=request.model_ref,parents=request.parents,
            facts=tuple(sorted((r.id for r in self.resources.records if r.category is Category.FACT),key=str)),
            E=request.E,K=request.K,context=request.context,preferences=self.resolved.items,style=self.resolved.style,
            scope=self.resolved.scope,gamma=self.resolved.gamma,candidates=request.candidates,continuation=request.continuation,
            measurement_contracts=(core._ContractRef('sui.f.finite_measurement','1'),),
            execution_contracts=tuple(dict.fromkeys(a.execution for a in request.candidates.candidates)),method=request.method)
        self.models[request.model_ref]=core.FModelDependency(ref=request.model_ref,present=True)
        self.records.update(self.facts.records)
        return self.model,(),self.resources,values

    def _prior_joint(self,data):return core._decode(data['initial'],tuple[core._Fraction,...])

    def _initial_joint(self,belief):
        return belief.joint if self.bit is None else tuple(core._Fraction(int(i==self.bit)) for i in range(2))

    def _initial_O(self,values):
        # Conditional O0 branches are integrated before choice, not written as facts.
        return values if self.bit is None else ((0,('hypothetical_O0',self.bit),'P',self.bit),)

    def _manifest(self):
        return core.FWorldManifest3(contract=fc.WORLD_MANIFEST_FACTS,compiler=fc.PREPARE_FACTS,
            request=core.FMathLegacyBridgeInput(kind='legacy_bridge',value=self.primary_request),
            dependencies=facts_dependencies(self.facts,(self.facts,self)),preference_causality=self.preference_causality)


def read_draw(reader,point,*,budget,parents,purpose,context_key,context=None,certified_order=None,additional_roots=()):
    from ._f_identity import point as authenticated
    from .records import Observed,Role,Category
    image=capture_reader(reader,budget)
    entry,record,binding=authenticated(image,point)
    if purpose=='selection' and not set(parents)<=image.ancestors(entry.parents): raise core.FInputError('invalid_draw',field='/draw/parents')
    try:
        _payload_record(record, fc.DRAW_FACT, field='/draw')
    except core.FInputError as exc:
        raise core.FInputError('invalid_draw', field='/draw') from exc
    # Draw has its own post-problem causal scope, but the same Observed clock
    # and declared-reference table. This adapter only reads authenticated bytes.
    if certified_order is None:
        order = certify_reader_closure(image, roots=(point,*additional_roots), budget=budget, context=context,
                                       post_problem=purpose=='selection')
    else:
        # Candidate generation draws already belong to this exact prepared set.
        # Reuse only that closure, never an earlier context or a draw extension.
        if (purpose!='candidate_generation' or certified_order.compiler.image is not image
                or certified_order._context_key != core._digest(context)):
            raise core.FInputError('proof_mismatch',field='/draw/closure')
        order = certified_order
    value = order.validate(point, '/draw')['value']
    request=value.request
    draw=core.DrawRecord(id=core._digest({'domain':'sui.f.draw/1','generator':value.generator,'stream_id':value.stream_id,
        'purpose':request.purpose,'context_key':request.context_key,'ordinal':request.ordinal}),purpose=request.purpose,
        generator=value.generator,stream_id=value.stream_id,request=request,context_key=request.context_key,ordinal=request.ordinal,value=value.value)
    core._validate_draw(draw)
    if request.purpose!=purpose or request.context_key!=context_key: raise core.FInputError('invalid_draw',field='/draw/request')
    return draw


def _validate_problem_input(*, model: FModel, parents: frozenset[str],
                      records: tuple[_Record, ...], E: EvidenceHistory,
                      K: KnowledgeHistory, context: FContext, resolved: FResolved,
                      candidates: CandidateSet, continuation: FContinuation,
                      method: _ContractRef,
                       resources: FResources, capability, preference_view) -> dict:
    """F-a で固定原記録・親・E/K・好み・候補・明示 continuation から draw のない問題を作る。
    continuation は必須で正準候補と同順/同件数、問題 digest に含める。
    one_step は初手 ψ まで、unbounded_total は終了後 after へ一度入る。
    null でも既存経路/残りの測定を切らず、未指定の続き・人の H/割引を補わない。
    scope/source/紙の H/gamma/items 不一致 FInputError(scope_mismatch)。
    source=None は白紙の unbounded_total に限定。旧の橋も範囲の紙を明示する。
    手組みを認証せず、不正入力 FInputError、意味不足 FSpecificationMissing、
    原記録不足 FReplayUnavailable、能力不足 FIncomplete、型外 FOutsideEvaluationType。"""
    from . import f as core, f_contracts as fc
    from .f_model import f_model_ref, _parts
    from .records import Category
    core._require(resources, FResources)
    model_ref = f_model_ref(model)
    core._resource_model(resources, model_ref)
    records_by_id = {r.id: r for r in resources.records}
    for record in records:
        if records_by_id.get(record.id) != record:
            raise core.FReplayUnavailable("missing_input", str(record.id))
    context = core._decode(core._encode(context), FContext)
    candidates = core._decode(core._encode(candidates), CandidateSet)
    continuation = core._decode(core._encode(continuation), FContinuation)
    # The compiler already authenticated these records and the full FACT set
    # against ledger CIDs. Caller-supplied ancestry is never its authority.
    facts = tuple(sorted((r.id for r in records if r.category is Category.FACT), key=str))
    rebuilt_E, rebuilt_K = build_histories(model, records, available=K.available,
        incorporated=K.incorporated, belief=K.belief, proofs=K.normalization_proofs, resources=resources)
    if E != rebuilt_E or K != rebuilt_K:
        raise core.FInputError("shape", "histories must be derived from frozen records")
    if resolved.scope.source != resolved.style or (resolved.scope.name == "finite_horizon" and resolved.style is None):
        raise core.FInputError("scope_mismatch")
    if resolved.style is not None:
        if resolved.style not in records_by_id:
            raise core.FInputError("scope_mismatch", "style unavailable")
        record = records_by_id[resolved.style]
        if record.body.contract == fc.STYLE:
            _payload_record(record, fc.STYLE)
            style = f_from_json(record.body.content.data, contract=fc.STYLE)
            name, horizon, gamma = style.scope.name, style.scope.H_ns, style.gamma
        else:
            from .preference import _parse
            style = _parse(record)
            name, horizon, gamma = ("one_step" if style["H_ns"] is None else "finite_horizon"), style["H_ns"], core._Fraction(style["gamma"])
        if (name, horizon, gamma) != (resolved.scope.name, resolved.scope.H_ns, resolved.gamma):
            raise core.FInputError("scope_mismatch")
    elif resolved.scope.name != "unbounded_total" or resolved.gamma != 1:
        raise core.FInputError("scope_mismatch")
    from .f_entry import resolve_f_preferences
    preferences = tuple(r for r in records if r.category is Category.PREFERENCE)
    if {r.id for r in preferences} != {p.id for p in preference_view.points}:
        raise core.FInputError('unresolved_reference','frozen preferences differ from parent ancestry','/records')
    actual = resolve_f_preferences(preference_view,resources=resources)
    if core._dumps(actual) != core._dumps(resolved):
        raise core.FInputError('scope_mismatch','resolved preferences differ from frozen records','/resolved')
    for action in candidates.candidates:
        capability('action',core._ContractRef(action.family.name,action.family.version),action.args)
    canonical = core.canonical_candidates(candidates.candidates, measure=candidates.measure,
        generator=candidates.generator, basis=candidates.basis, draws=candidates.draws,
        registry=resources.registry)
    if canonical.candidates != candidates.candidates:
        raise core.FInputError("noncanonical", "candidates differ from their canonical representatives",'/candidates')
    names = tuple(a.id for a in candidates.candidates)
    if tuple(a.candidate for a in continuation.after) != names:
        raise core.FInputError("shape", "continuation axis mismatch")
    _, kernels, policies, operations = _parts(model)
    values = dict(model_ref=model_ref, parents=parents, facts=facts, E=E, K=K, context=context,
        preferences=resolved.items, style=resolved.style, scope=resolved.scope, gamma=resolved.gamma,
        candidates=candidates, continuation=continuation,
        measurement_contracts=tuple(sorted({o.evidence.measurement_contract for k in kernels.values() for o in k.outcomes if o.evidence is not None}, key=lambda c: (c.name, c.version))),
        execution_contracts=tuple(dict.fromkeys(a.execution for a in candidates.candidates)), method=method)
    return values
