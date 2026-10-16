"""Independent F-b mutants, paper v0.12 (bacff105a33c6acb).

M-01: PREDECLARED population, before writing any mutant implementation.
All line numbers below refer to specs/関所F_Fb_今の約束.md.
Each row has a proposed SINGLE broken promise. All controls mean the SAME
Scenario, E0, legal prefix and Cut with CorrectWindow; no changed declaration.
The final column states the behavior required of that nearest legal control.
SC names without a concrete suffix are proposed minimal structural scenes,
not claims that the existing numerical branch can be run. Actual mappings and
results are in test_fb_mutants.py. Proposals are not discrimination evidence.

ID | paper row; mapping | proposed wrong behavior | scene | nearest legal control
INV-1.a | 839;1399 | Accept acknowledges custody but drops the unsaved receipt | minimal receipt | receipt retained through HostAck
INV-1.b | 840;1400 | same envelope reacceptance changes r in its retained original | SC-02 | exact original retained
INV-1.c | 841;1401 | Accept creates two receipt slots for one ordinary envelope | minimal receipt | exactly one slot
INV-2.a | 842;1402 | drain removes a still-Pending work row | SC-04 | drain only enumerates
INV-2.b | 843;1403 | Publish records but omits the promised Wp row | SC-04-publish-R-Wp | records and Wp installed atomically
INV-2.c | 844;1404 | end recognition closes T saving custody before T is Saved | SC-04-DESC terminal | T saving condition remains unmet
INV-2.d | 845;1405 | hide PublishMatching despite saved eligible Received | SC-08-structure-e1-then-other | publish offered
INV-2.e | 846;1406 | hide Launch after reservation with Held resources | SC-04 | Launch offered with existing reservation
INV-2.f | 847;1407 | close run using resource wait for Pending work with sufficient free capacity | SC-04 before ClaimStart | no resource exemption
INV-3.a | 848;1408 | request body entry twice using the same start token | SC-04-double-wrapper | one body entry
INV-3.b | 849;1409 | change one fixed descriptor argument when draining | SC-04-DESC | descriptor unchanged
INV-3.c | 850;1410 | request release of one reservation twice | SC-04-RELEASE | one release history entry
INV-4.a | 851;1411 | PutBody writes the point instead of the body | minimal receipt | point has matching saved body
INV-4.b | 852;1412 | retry PutBody changes the fixed salt | SC-03-RETRY minimal receipt | same first salt
INV-4.c | 853;1413 | initial receipt preparation changes r while retaining it on retries | SC-03-FIRST minimal receipt | r equals host original
INV-5.a | 854;1414 | prepare a record with an unresolved required Point | SC-05-structure-r-published | wait for dependency
INV-5.b | 855;1415 | ClaimStart before the required request Point is saved | SC-04-one-reference-missing | wait until request Saved
INV-5.c | 856;1416 | prepare child with saved Prediction as a parent | SC-05-PARENT or minimal parent scene | saved Event parent
INV-6.a | 857;1417 | completed preparation swaps Wr start clock for Wp finish clock | SC-05-COMPLETE | same-request actual clocks
INV-6.b | 858;1418 | issue two separately named T records for one work ending | SC-04-DESC terminal | one saved terminal record
INV-6.c | 859;1419 | merge distinct item_slots OR distinct acquisition intents with equal targets | SC-11 same-content-other-slot / M-two-acquisitions | preserve both identities
INV-7.a | 860;1420;1045 | invent Xc from a singleton terminal report (no incompatible pair) | SC-04-DESC terminal | T only, no Xc
INV-7.b | 861;1421 | enter a launched body after an upstream conflicting report is saved | SC-18 minimal structural conflict | entry blocked; evidence saving continues
INV-7.c | 862;1422 | late report rewrites an already fixed terminal | SC-15 tie local | original terminal unchanged
INV-8.a | 863;1423 | replace a work's frozen numerical root with current Saved points | SC-04-DESC | descriptor keeps original root
INV-8.b | 864;1424 | EnterWorker reads current Saved points instead of its frozen input | SC-04 pending local | actual read uses fixed input
INV-9.a | 865;1425 | V publication changes the actual verification response | SC-06-structure-verification-pending | V equals observed response
INV-9.b | 866;1426 | Adopt after previous_result no longer matches current adoption | SC-07a | Stale, no adoption; real legal IA is implementation-stage
INV-10.a | 867;1427 | reserve more resource than the effective allocation | SC-14-LIMIT | actual occupancy <= allocation
INV-10.b | 868;1428 | release held resources at Unknown without Stop | SC-15-structure-Wr-no-stop | hold until confirmed Stop
INV-11.a | 869;1429 | hide eligible Accept | minimal receipt | eligible Accept offered
INV-11.b | 870;1430 | hide PutBody while body capability is available | minimal receipt | next storage operation offered
INV-11.c | 871;1431 | hide receipt service only while a computation occupies a seat | SC-13-hung-receipt | equal receipt projection, equal services
INV-12.a | 872;1432 | treat Started alone as positive coverage | SC-12-started-only | Started contributes no covered cells; Support meaning implementation-stage
INV-12.b | 873;1433 | remove MeasureSegment after legal H-to-work cell handoff | M-measure-owned from SC-12-structure-measure-row | cells remain under live work custody
INV-13.a | 874;1434 | publish bootstrap computation with initial=None | minimal empty bootstrap | no bootstrap computation
INV-13.b | 875;1435 | hide receipt service because initial=None | SC-20 minimal receipt | same reception service with/without initial
INV-14.a | 876;1436 | enter same Draw request body twice | minimal declared D | one request, one entry; real IE/ID legality implementation-stage
INV-14.b | 877;1437 | reissue same Draw after Unknown | minimal declared D Unknown | retain unknown; no redraw; numerical refinement implementation-stage
INV-15.a | 878;1438 | recognize a terminal before first receipt is Saved | SC-15-Wr-tie-unknown-first | wait for earliest saved receipt
INV-15.b | 879;1439 | Unknown recognition stores Success as terminal knowledge | SC-15-structure-Wr-no-stop | first Unknown retained
INV-16.a | 880;1440 | publish selection for NoDecision | SC-09 structural evaluation | save terminal only; authenticated Selected implementation-stage
INV-16.b | 881;1441 | substitute another problem in selection | SC-10 | same EQ/PR/Draw/artifact; real artifact closure implementation-stage
L-RECEIPT | 882;1442,1455-1456 | hide next save step forever after Accept | minimal receipt | complete fair save; abstract T2 is not reachability evidence
L-DERIVE | 883;1443,1460 | hide PublishMatching while ReadyN stays true | SC-08-structure-e1-then-other | publish and save matching Q

Scope: H-01..H-06 are OUTSIDE this automated task (891-896). Numerical
legality, /2 projection, contract-specific Support and actual issued F-a
certificates/artifact closure remain implementation-stage (1509); no symbolic
pass certifies them. A row can gain STRUCTURAL discrimination while retaining
these limitations. Six previously unconnected rows are not silently removed.

Final scope disposition (proposals above remain in the 45-row denominator):
- INV-9.b: implementation-stage (866,1426,1509). SC-07a/b has no executable
  legal E0 for adoption/certificate/current-series; no invented IA control.
- INV-12.a: implementation-stage (872,1087,1432,1509). Contract-specific
  Support/generation/coverage is not supplied by the structural interval API.
- INV-14.a/14.b: implementation-stage (876-877,944,1366,1436-1437,1509).
  D branches require legal IE/ID and a fixed actual Draw request. An ordinary
  Wr renamed D would not establish that positive control.
- INV-16.a/16.b: implementation-stage (880-881,1440-1441,1509). The public
  structural artifact-issued scene does not provide saved authenticated
  evaluation/PR/Draw/Selected correspondence or actual artifact closure.
- INV-7.b: NOT declared out of scope. Independent mutant/control still
  unimplemented: SC-18 declarations have E0=None and scope b. A legal
  structural IX prefix with explicit UseDeps/EvidenceRefs and affected keys
  is needed. Its proposal remains above; do not silently remove this row.
- Other numerical portions of every row remain implementation-stage (1509).
  Structural identification of one case is not whole-row or numeric coverage.

The initial plan table was written before the first implementations. Revisions
above specify the narrower actual wrong behavior after the public four-point
audit in test_fb_mutants.py; targets have never been changed to a side finding.
One added representation assumption A-M-XC: paper 1045's logical four fields
use Object/reports tuple and the model's existing reference spelling. This is
naming/wire only (1); no extra semantic or numerical assumption (0).

Read boundary: inspect.signature/getdoc and public dataclass declarations,
SCENES/E0/instantiate, and actual public calls only. No implementation source
of CorrectWindow, Environment or checker predicates was opened.
Session logging: latest instruction permits only these two new files, so
Obsidian Sessions/Projects/Heat updates are intentionally NOT performed.
Reused knowledge: Obsidian/Knowledge/確かめる係の設計_すり抜けの型と環境の真実_2026-10-13.md;
applicable: keep A-G failure mechanisms and independent E0/actual observations
separate; no single-cause inference and no fingerprint marker in model state.
"""

from dataclasses import replace

import fb_machine as m
from fb_machine import CorrectWindow


def map_slots(custody, fn):
    """Map window-owned slots only; never edit environment observations."""
    def unit(u):
        return replace(u, slots=tuple(fn(u, s) for s in u.slots))
    return replace(custody, units=tuple(unit(u) for u in custody.units),
                   receipts=tuple(replace(r, unit=unit(r.unit)) for r in custody.receipts))


def field(value, name, replacement):
    return m.Object(tuple((k, replacement if k == name else v) for k, v in value.items))


class DropReceiptAfterAck(CorrectWindow):
    """INV-1.a / 839: discard the receipt after H has acknowledged custody."""
    def drain(self, view):
        d = super().drain(view)
        acknowledged = set(view.actual.eh.acknowledgements)
        receipts = tuple(r for r in d.custody.receipts
                         if (r.envelope.run, r.envelope.number) not in acknowledged
                         or all(s.completed for s in r.unit.slots))
        return replace(d, custody=replace(d.custody, receipts=receipts))


class ReacceptChangesReading(CorrectWindow):
    """INV-1.b / 840: a retry replaces the retained original reading."""
    def accept(self, view, envelope):
        d = super().accept(view, envelope)
        if any(r.envelope == envelope for r in view.core.p.receipts):
            receipts = tuple(replace(r, envelope=replace(envelope, r=replace(envelope.r, rank=envelope.r.rank + 1)))
                             if r.envelope == envelope else r for r in d.custody.receipts)
            return replace(d, custody=replace(d.custody, receipts=receipts))
        return d


class TwoReceiptSlots(CorrectWindow):
    """INV-1.c / 841: one ordinary acceptance promises its slot twice."""
    def accept(self, view, envelope):
        d = super().accept(view, envelope)
        if not any(r.envelope == envelope for r in view.core.p.receipts):
            receipts = tuple(replace(r, unit=replace(r.unit, slots=r.unit.slots * 2))
                             if r.envelope == envelope else r for r in d.custody.receipts)
            return replace(d, custody=replace(d.custody, receipts=receipts))
        return d


class DrainRemovesPending(CorrectWindow):
    """INV-2.a / 282,842: enumerate and remove not-yet-started work."""
    def drain(self, view):
        d = super().drain(view)
        return replace(d, custody=replace(d.custody, work=tuple(w for w in d.custody.work if w.phase != 'Pending')))


class PublishOmitsWork(CorrectWindow):
    """INV-2.b / 610,843: publish records without newly promised work rows."""
    def publish_unit(self, view, plan_id):
        d = super().publish_unit(view, plan_id)
        old = {w.descriptor.work_id for w in view.core.p.work}
        return replace(d, custody=replace(d.custody, work=tuple(w for w in d.custody.work if w.descriptor.work_id in old)))


class TerminalDropsSave(CorrectWindow):
    """INV-2.c / 844: EndKnown abandons its newly published T save custody."""
    def recognize_terminal(self, view, work):
        d = super().recognize_terminal(view, work)
        terminals = {u.id for u in d.custody.units if any(s.plan.contract.name == 'sui.fb.work_terminal' for s in u.slots)}
        return replace(d, custody=replace(d.custody, conditions=tuple(
            replace(c, unmet=frozenset()) if c.key.kind == 'save' and getattr(c.key.target, 'unit', None) in terminals else c
            for c in d.custody.conditions)))


class HideDerivation(CorrectWindow):
    """INV-2.d / 845, L-DERIVE / 1460: ReadyN remains true, publish hidden."""
    def enabled(self, view):
        actions = super().enabled(view)
        units = {p.unit for p in self.e0.plans if p.obligation_id == 'O-03'}
        return tuple(a for a in actions if not (a.operation == 'PublishUnit' and a.target[0] in units))


class HideHeldLaunch(CorrectWindow):
    """INV-2.e / 846: existing reservation wrongly prevents Launch."""
    def enabled(self, view):
        return tuple(a for a in super().enabled(view) if a.operation != 'Launch')


class FalseResourceWait(CorrectWindow):
    """INV-2.f / 847: declare a resource exemption without a shortage."""
    def drain(self, view):
        d = super().drain(view)
        def changed(w):
            if w.phase != 'Pending':
                return w
            excuse = m.Excuse('O-05', ('work', w.descriptor.work_id), 'B-RESOURCE',
                             w.descriptor.work_id, frozenset(e.point for e in view.core.e), ('C-O05.run[Wr]',))
            return replace(w, purposes=(excuse,))
        pending = {w.descriptor.work_id for w in d.custody.work if w.phase == 'Pending'}
        return replace(d, custody=replace(d.custody, work=tuple(changed(w) for w in d.custody.work),
            conditions=tuple(replace(c,unmet=frozenset()) if c.key.kind=='run' and getattr(c.key.target,'work',None) in pending else c
                             for c in d.custody.conditions)))


class DoubleBodyEntry(CorrectWindow):
    """INV-3.a / 848: issue the actual Enter request twice with one token."""
    def enter_worker(self, view, wrapper):
        d = super().enter_worker(view, wrapper)
        return replace(d, effects=tuple(e for x in d.effects for e in ((x, x) if x.kind == 'Enter' else (x,))))


class DescriptorChangesPurpose(CorrectWindow):
    """INV-3.b / 849,1379: one fixed field changes during its lifetime."""
    def drain(self, view):
        d = super().drain(view)
        return replace(d, custody=replace(d.custody, work=tuple(
            replace(w, descriptor=replace(w.descriptor, purpose=w.descriptor.stage_slot)) for w in d.custody.work)))


class DoubleRelease(CorrectWindow):
    """INV-3.c / 850,1380: release the same reservation twice in one step."""
    def release(self, view, work):
        d = super().release(view, work)
        return replace(d, effects=tuple(e for x in d.effects for e in ((x, x) if x.kind == 'Release' else (x,))))


class SkipBodyWrite(CorrectWindow):
    """INV-4.a / 851: execute point addition in place of its body write."""
    def put_body(self, view, key, mode):
        d = super().put_body(view, key, mode)
        return replace(d, effects=tuple(replace(x, kind='AddEntry') if x.kind == 'PutBody' else x for x in d.effects))


class PreparedSaltChanges(CorrectWindow):
    """INV-4.b / 852: lose the fixed salt between preparation and storage.

    The salt is replaced by the existing payload bytes, not a mutant marker.
    This is idempotent and makes no direct edit to C/E or EP.
    """
    def drain(self, view):
        d = super().drain(view)
        return replace(d, custody=map_slots(d.custody, lambda u, s:
            replace(s, prepared=replace(s.prepared, salt=s.prepared.payload))
            if s.prepared and not s.completed else s))


class FirstReceiptWrongReading(CorrectWindow):
    """INV-4.c / 853,1382: freeze the wrong received_ns from the first plan.

    Preparation/codec stays entirely on the ordinary public path afterwards.
    """
    def accept(self, view, envelope):
        d = super().accept(view, envelope)
        wrong = replace(envelope.r, rank=envelope.r.rank + 1)
        custody = map_slots(d.custody, lambda u, s:
            replace(s, plan=replace(s.plan, content=field(s.plan.content, 'received_ns', wrong)))
            if any(r.unit.id == u.id and r.envelope == envelope for r in d.custody.receipts) else s)
        return replace(d, custody=custody)


class ActualInputUsesLatest(CorrectWindow):
    """INV-8.b / 864: body reads all current points instead of frozen input."""
    def enter_worker(self, view, wrapper):
        d = super().enter_worker(view, wrapper)
        effects = tuple(replace(e, value=(e.value[0], e.value[1],
                            replace(e.value[2], points=frozenset(x.point for x in view.core.e))))
                        if e.kind == 'Enter' else e for e in d.effects)
        return replace(d, effects=effects)


class DescriptorUsesLatest(CorrectWindow):
    """INV-8.a / 863: frozen numerical root replaced by the current root."""
    def drain(self, view):
        d = super().drain(view)
        return replace(d, custody=replace(d.custody, work=tuple(
            replace(w, descriptor=replace(w.descriptor, numerical_view=replace(w.descriptor.numerical_view,
                points=frozenset(e.point for e in view.core.e)))) for w in d.custody.work)))


class OverReserve(CorrectWindow):
    """INV-10.a / 867: actual reservation exceeds its declared allocation."""
    def claim_start(self, view, work):
        d = super().claim_start(view, work)
        allocation = dict(self.e0.allocation)
        return replace(d, effects=tuple(replace(e, value=field(e.value, 'resources',
            tuple((resource, allocation[resource] + 1) for resource, _ in e.value.get('resources'))))
            if e.kind == 'Reserve' else e for e in d.effects))


class ReleaseOnUnknown(CorrectWindow):
    """INV-10.b / 868: recognizing Unknown releases a still-running body."""
    def recognize_terminal(self, view, work):
        d = super().recognize_terminal(view, work)
        row = next(w for w in d.custody.work if w.descriptor.work_id == work)
        if row.knowledge and str(row.knowledge.kind) in ('Unknown', 'OutcomeKind.UNKNOWN') and row.held and not row.stopped:
            return replace(d, effects=d.effects + (m.Effect('Release', work, row.held),),
                custody=replace(d.custody, work=tuple(replace(w, held=(), released=True)
                    if w.descriptor.work_id == work else w for w in d.custody.work)))
        return d


class HideAccept(CorrectWindow):
    """INV-11.a / 869: eligible receipt cannot be accepted."""
    def enabled(self, view):
        return tuple(a for a in super().enabled(view) if a.operation != 'Accept')


class HideReceiptSave(CorrectWindow):
    """INV-11.b / 870 and L-RECEIPT / 882: next PutBody is never offered."""
    def enabled(self, view):
        units = {r.unit.id for r in view.core.p.receipts}
        return tuple(a for a in super().enabled(view)
                     if not (a.operation == 'PutBody' and a.target[0] in units))


class UnknownBecomesSuccess(CorrectWindow):
    """INV-15.b / 879: store Success for the first Unknown notification."""
    def recognize_terminal(self, view, work):
        d = super().recognize_terminal(view, work)
        return replace(d, custody=replace(d.custody, work=tuple(
            replace(w, knowledge=replace(w.knowledge, kind=m.OutcomeKind.RETURNED))
            if w.descriptor.work_id == work and w.knowledge and w.knowledge.kind == m.OutcomeKind.UNKNOWN
            else w for w in d.custody.work)))


def change_publication(decision, transform):
    """Change the actual published unit, not E0 or the environment's history."""
    changed = {e.value[0].id: transform(e.value[0]) for e in decision.effects if e.kind == 'Publish'}
    return replace(decision,
        custody=replace(decision.custody, units=tuple(changed.get(u.id, u) for u in decision.custody.units)),
        effects=tuple(replace(e, value=(changed[e.value[0].id], e.value[1])) if e.kind == 'Publish' else e
                      for e in decision.effects))


class CompletedUsesFinishAsStart(CorrectWindow):
    """INV-6.a / 857,1417: use Wp finish clock as the Wr start clock."""
    def publish_unit(self, view, plan_id):
        d = super().publish_unit(view, plan_id)
        def change(u):
            slots = []
            for s in u.slots:
                if s.plan.contract.name == 'computation_completed':
                    finish = s.plan.content.get('finished_clock')
                    plan = replace(s.plan, content=field(s.plan.content, 'started_clock', finish),
                        references=tuple(replace(r, ref=finish) if r.path == ('started_clock',) else r for r in s.plan.references))
                    s = replace(s, plan=plan)
                slots.append(s)
            return replace(u, slots=tuple(slots))
        return change_publication(d, change)


class PredictionAsParent(CorrectWindow):
    """INV-5.c / 856,1383: a saved Prediction is used as a causal parent."""
    def prepare_one(self, view, key):
        d = super().prepare_one(view, key)
        predictions = sorted((e.point for e in view.core.e if e.header.record.category == 'Prediction'), key=lambda p: p.cid)
        if not predictions:
            return d
        prepared = next(e.value for e in d.effects if e.kind == 'Prepare')
        parents = prepared.parents | {predictions[0]}
        header = replace(prepared.header, parents=parents)
        # Public hash/encode API. Check its correspondence on the ordinary
        # value before using it; this is not a copied checker predicate.
        assert m.Point(m.digest(prepared.header)) == prepared.point
        bad = replace(prepared, parents=parents, header=header, point=m.Point(m.digest(header)))
        return replace(d, custody=map_slots(d.custody, lambda u, s:
            replace(s, prepared=bad) if (u.id, s.plan.slot) == key else s),
            effects=tuple(replace(e, value=bad) if e.kind == 'Prepare' else e for e in d.effects), result=bad)


class VerificationResponseChanges(CorrectWindow):
    """INV-9.a / 865: change actual Success to Rejected when publishing V."""
    def recognize_terminal(self, view, work):
        d = super().recognize_terminal(view, work)
        def change(u):
            def slot(s):
                if s.plan.contract.name != 'sui.fb.verification_result':
                    return s
                # The complete, ordinary response is a public VerificationReply.
                def value(v):
                    return replace(v, response='Rejected') if isinstance(v, m.VerificationReply) else v
                content = m.Object(tuple((k, value(v)) for k, v in s.plan.content.items))
                return replace(s, plan=replace(s.plan, content=content))
            return replace(u, slots=tuple(slot(s) for s in u.slots))
        return change_publication(d, change)


class EmptyInitialStartsCompute(CorrectWindow):
    """INV-13.a / 874: publish computation in place of measurement with no initial."""
    def publish_unit(self, view, plan_id):
        d = super().publish_unit(view, plan_id)
        if self.e0.initial is not None:
            return d
        old = {w.descriptor.work_id for w in view.core.p.work}
        rows = tuple(replace(w, descriptor=replace(w.descriptor, stage='Wr'))
                     if w.descriptor.work_id not in old else w for w in d.custody.work)
        return replace(d, custody=replace(d.custody, work=rows), effects=tuple(
            replace(e,value=(e.value[0],tuple(replace(desc,stage='Wr') for desc in e.value[1]))) if e.kind=='Publish' else e
            for e in d.effects))


class HideAcceptWhileOccupied(CorrectWindow):
    """INV-11.c / 871: use computation occupancy as the reception guard."""
    def enabled(self, view):
        actions = super().enabled(view)
        return tuple(a for a in actions if not (a.operation == 'Accept' and any(w.held for w in view.core.p.work)))


class HideClaimStart(CorrectWindow):
    """INV-2.e / 846: hide the pre-reservation operation with free capacity."""
    def enabled(self, view):
        return tuple(a for a in super().enabled(view) if a.operation != 'ClaimStart')


class PrepareUnsavedReference(CorrectWindow):
    """INV-5.a / 854: one typed body reference points to this unsaved candidate.

    Only the reference is substituted. Codec mismatch is collateral, not a
    synthetic error tag; the old candidate CID is an ordinary actual value.
    """
    def prepare_one(self, view, key):
        d = super().prepare_one(view, key)
        prepared = next((e.value for e in d.effects if e.kind == 'Prepare'), None)
        if prepared is None or not prepared.record.references:
            return d
        reference = prepared.record.references[0]
        record = replace(prepared.record, references=(replace(reference, ref=prepared.point),) + prepared.record.references[1:])
        bad = replace(prepared, record=record, header=replace(prepared.header, record=record))
        return replace(d, custody=map_slots(d.custody, lambda u,s: replace(s, prepared=bad) if (u.id,s.plan.slot)==key else s),
                       effects=tuple(replace(e,value=bad) if e.kind=='Prepare' else e for e in d.effects), result=bad)


class ClaimDuringRequestPreparation(CorrectWindow):
    """INV-5.b / 855: preparation of Q incorrectly also reserves its worker.

    Reserve uses the ordinary descriptor/resources and a digest of that
    descriptor as the token. The request's actual candidate is not Saved.
    """
    def prepare_one(self, view, key):
        d = super().prepare_one(view, key)
        prepared = next((e.value for e in d.effects if e.kind == 'Prepare'), None)
        if prepared is None:
            return d
        target = next((w for w in d.custody.work if w.phase == 'Pending' and w.descriptor.request == m.PlanRef(*key)), None)
        if target is None:
            return d
        token = m.digest(target.descriptor)
        row = replace(target, phase='Starting', token=token, held=target.descriptor.need)
        effect = m.Effect('Reserve', target.descriptor.work_id,
                          m.obj(descriptor=target.descriptor, resources=target.descriptor.need, token=token))
        return replace(d, effects=d.effects+(effect,), custody=replace(d.custody, work=tuple(row if w==target else w for w in d.custody.work)))


class DoubleTerminalProcessing(CorrectWindow):
    """INV-6.b / 858: create two terminal records for the same logical ending."""
    def recognize_terminal(self, view, work):
        d = super().recognize_terminal(view, work)
        def twice(u):
            terminal=tuple(s for s in u.slots if s.plan.contract.name=='sui.fb.work_terminal')
            return replace(u,slots=u.slots+tuple(replace(s,plan=replace(s.plan,slot=s.plan.slot+':1')) for s in terminal))
        return change_publication(d,twice)


class LateReceiptChangesRoot(CorrectWindow):
    """INV-7.c / 862: replace the old fixed root after a later receipt is saved."""
    def drain(self, view):
        d = super().drain(view)
        points = frozenset(e.point for e in view.core.e)
        return replace(d, custody=replace(d.custody, work=tuple(
            replace(w, descriptor=replace(w.descriptor, numerical_view=replace(w.descriptor.numerical_view,points=points)))
            for w in d.custody.work)))


class NoInitialNoReception(CorrectWindow):
    """INV-13.b / 875: initial=None incorrectly removes the reception service."""
    def enabled(self, view):
        return tuple(a for a in super().enabled(view) if self.e0.initial is not None or a.operation != 'Accept')


class ReceiptPreparationRecognizesEnd(CorrectWindow):
    """INV-15.a / 878: EndKnown is fixed when first receipt is only prepared."""
    def prepare_receipt(self, view, key):
        d = super().prepare_receipt(view, key)
        receipt = next((r for r in d.custody.receipts if r.unit.id==key[0]), None)
        if receipt is None or receipt.envelope.event.kind != 'WorkFinished':
            return d
        content = receipt.envelope.event.fields
        work = content.get('work')
        outcome = content.get('outcome')
        if not isinstance(outcome, m.Outcome):
            return d
        first = (receipt.envelope.run,receipt.envelope.number)
        return replace(d, custody=replace(d.custody, work=tuple(
            replace(w, knowledge=outcome, first=first) if w.descriptor.work_id==work else w for w in d.custody.work)))


class AcquisitionIntentCollapsed(CorrectWindow):
    """INV-6.c / 859,334: equal targets incorrectly reuse another intent.

    The actual Acquire effect carries the first ordinary intent's identity.
    No evidence/history is edited and no marker is introduced.
    """
    def acquire(self, view, intent):
        d=super().acquire(view,intent)
        if len(view.actual.ea.acquisitions)!=1:
            return d
        earlier=view.actual.ea.acquisitions[0]
        first=next(i for i in self.e0.acquisitions if i.id==earlier.intent)
        current=next(i for i in self.e0.acquisitions if i.id==intent)
        if (first.reader,first.targets)!=(current.reader,current.targets):
            return d
        return replace(d,effects=tuple(replace(e,key=earlier.intent,value=replace(e.value,id=earlier.intent))
                                      if e.kind=='Acquire' else e for e in d.effects))


class SingleReportMakesConflict(CorrectWindow):
    """INV-7.a / 593,860,1045: invent Xc from one ordinary terminal report.

    Clashes requires a pair of incompatible reports; a singleton cannot
    satisfy that promise. The four Xc fields are exactly paper 1045's fields.
    """
    def recognize_terminal(self, view, work):
        d=super().recognize_terminal(view,work)
        def add_conflict(u):
            terminal=next((s for s in u.slots if s.plan.contract.name=='sui.fb.work_terminal'),None)
            if terminal is None:
                return u
            receipt=terminal.plan.content.get('first_receipt')
            content=m.obj(reports=(receipt,),rule='CMP-22',affected=frozenset({(work,)}),
                          view=frozenset(e.point for e in view.core.e))
            plan=m.RecordPlan('Xc',m.Contract('sui.fb.conflict','1'),'Event',content,
                (m.TypedReference('PATH-LINK-GENERATION',('reports',0),receipt,'E','diagnostic'),),frozenset({receipt}))
            return replace(u,slots=u.slots+(m.Slot(plan),))
        return change_publication(d,add_conflict)

