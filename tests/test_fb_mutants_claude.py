"""F-b model mutants written by Claude (M-03), paper v0.12 (bacff105a33c6acb).

Paper §2-4-10 (:564): at least half of the mutants are written by Codex from
the paper only, in a separate conversation (tests/fb_mutants.py and
tests/test_fb_mutants.py, conversation `sui-fb-model-mutants`). This file is
the smaller remainder written by Claude, who HAS read the CorrectWindow and
checker bodies; therefore the Codex mutant writer must not read this file, and
these cases are not independent evidence in the sense of :564.

Rows taken here are those the Codex writer had not implemented when its
conversation stopped at the usage limit (2026-10-14 13:16): INV-5.a, INV-5.b,
INV-7.c, INV-15.a. Each mutant changes ONE belief of the window and overrides
ONE public step; it places no marker in model data (札E):

- counted_as_saved: a prepared record whose body/entry are not yet confirmed
  is treated as Saved (INV-5.a at PrepareOne, INV-5.b at ClaimStart, INV-15.a
  at RecognizeTerminal). The environment's C/E are never edited; only the
  window's view of them is.
- LateRewritesTerminal: the published T is rewritten at preparation from the
  latest saved notification instead of the first (INV-7.c, paper 862).

Pass criteria (paper 432, 1447): target row declared first; the target row is
reported on the mutant; CorrectWindow on the same scene and prefix is complete
with zero violations; the mutant graph is complete (no frontier counted).

Measured 2026-10-14 17:2x (4 passed, 221 s; counts are states):
| case | row | scene | control | mutant | rows reported | first finding |
|---|---|---|---|---|---|---|
| C-5a | INV-5.a | SC-04-initial-publish:reader-prepared (K-U local) | 85, 0 violations | 461 | INV-4.c, INV-5.a | PrepareOne(initial,q) at the first edge |
| C-5b | INV-5.b | SC-04-one-reference-missing | 89, 0 | 202 | INV-3.b, INV-5.b | ClaimStart(wr) |
| C-7c | INV-7.c | SC-15-Wr-tie-unknown-first | 64, 0 | 64 | INV-4.c, INV-7.c | PrepareOne(terminal:wr,T) |
| C-15a | INV-15.a | SC-15-Wr-tie-unknown-first | 64, 0 | 113 | INV-15.a | state 2 (first notice not materialized) |
Not counted: overriding resolve_work alone (instead of claim_start) never
reaches a ClaimStart with Q unsaved; it reported only INV-3.b.
"""

import sys
sys.dont_write_bytecode = True
from dataclasses import dataclass, replace
from functools import lru_cache
from time import perf_counter

import pytest

import fb_check as check
import fb_machine as m
import fb_scenes as scenes


def counted_as_saved(view):
    """The one wrong belief: a prepared (not yet confirmed) record is Saved."""
    core = view.core
    bodies, entries = list(core.c), list(core.e)
    for unit in m._units(core.p):
        for s in unit.slots:
            pe = s.prepared
            if pe is None or m._saved(core, pe.point):
                continue
            bodies.append(m.Body(pe.seal, pe.salt, pe.payload))
            entries.append(m.Entry(pe.point, pe.header))
    return replace(view, core=replace(core, c=tuple(bodies), e=tuple(entries)))


class PrepareOnUnsaved(m.CorrectWindow):
    """INV-5.a / 854: PrepareOne resolves a reference whose record is only prepared."""
    def prepare_one(self, view, key):
        return super().prepare_one(counted_as_saved(view), key)


class ClaimOnUnsaved(m.CorrectWindow):
    """INV-5.b / 855: ClaimStart fixes and uses a required Point that is only prepared."""
    def claim_start(self, view, work):
        fake = counted_as_saved(view)
        row = m._work(fake.core.p, work)
        pairs = tuple(sorted(((r, m._resolve(fake.core, r)) for r in m._descriptor_refs(row.descriptor)
                              if isinstance(r, m.PlanRef)), key=m.encode))
        fake = replace(fake, core=replace(fake.core, p=m._with_work(fake.core.p, replace(row, resolutions=pairs))))
        return super().claim_start(fake, work)


class RecognizeOnUnsaved(m.CorrectWindow):
    """INV-15.a / 878: the first notification counts as Saved while only prepared."""
    def recognize_terminal(self, view, work):
        return super().recognize_terminal(counted_as_saved(view), work)


def _later_saved_generation(view, work):
    """The most recent SAVED notification of this work, by (r, receipt_seq)."""
    found = []
    for r in view.core.p.receipts:
        g = m._generation_for(view.core, r.envelope)
        if g is not None and g.work == work and m._receipt_saved(view.core, r):
            found.append(((r.envelope.r.rank, r.envelope.receipt_seq), g))
    return max(found, key=lambda x: x[0])[1] if found else None


class LateRewritesTerminal(m.CorrectWindow):
    """INV-7.c / 862: a late report rewrites the already published T at preparation."""
    def prepare_one(self, view, key):
        if not key[0].startswith("terminal:"):
            return super().prepare_one(view, key)
        s = m._slot(view.core.p, key)
        late = _later_saved_generation(view, key[0].split(":", 1)[1])
        content = s.plan.content
        if late is None or late.outcome.kind == content.get("terminal_kind"):
            return super().prepare_one(view, key)
        o = late.outcome
        basis = (late if o.kind == m.OutcomeKind.FAILURE
                 else o.content if o.kind == m.OutcomeKind.UNKNOWN else None)
        changed = {"terminal_kind": o.kind, "returned": o.content, "basis": basis}
        rewritten = m.Object(tuple((k, changed.get(k, v)) for k, v in content.items))
        p = m._with_slot(view.core.p, key, replace(s, plan=replace(s.plan, content=rewritten)))
        return super().prepare_one(replace(view, core=replace(view.core, p=p)), key)


@dataclass(frozen=True)
class Case:
    id: str
    target: str
    window: type
    scene: str


STORAGE = frozenset({"PrepareOne", "PutBody", "AddEntry", "ConfirmBody", "ConfirmWrite", "CompleteWrite",
                     "BodyResponse", "EntryResponse", "Drain", "Wait"})
OPERATIONS = frozenset("""Post Accept HostAck PrepareReceipt PrepareOne PutBody ConfirmBody AddEntry
ConfirmWrite CompleteWrite BodyResponse EntryResponse PublishUnit Recognize RecognizeTerminal ResolveWork
ClaimStart Launch LaunchResponse EnterWorker WorkerStep Stop Release Deliver DeliverBundle HostUnknown
Acquire Adopt HandoffPurpose Drain Wait RebuildWindow WindowFault DuplicateWrapper IntervalEvent
UndertakeInterval""".split())


def _reader_prepared(scenario):
    """SC-04-initial-publish, then (legal, CorrectWindow) Publish(initial), save
    `process`, prepare `reader`. q references reader (origin/args.model/inputs[0]).
    The whole SC-04-initial-publish graph is incomplete at its 5,000 limit, so
    only the storage of the initial unit is explored from here (K-U local)."""
    env, win = m.Environment(scenario.e0), m.CorrectWindow(scenario.e0)
    state = scenario.initial

    def step(op, target):
        view = m.View(state.core, state.controls, state.evidence)
        action = next(a for a in env.actions(state) + win.enabled(view)
                      if a.operation == op and a.outcome == "normal" and a.target == target)
        return env.step(state, action, win).state

    state = step("PublishUnit", ("initial",))
    for op in ("PrepareOne", "PutBody", "AddEntry", "ConfirmWrite", "CompleteWrite"):
        state = step(op, ("initial", "process"))
    state = step("PrepareOne", ("initial", "reader"))
    cut = m.Cut("K-U local: storage of the initial unit", OPERATIONS - STORAGE,
                ("Only storage of the initial unit after reader is prepared; other continuation untested.",))
    return replace(scenario, id=scenario.id + ":reader-prepared", initial=state, cut=cut, max_states=2000)


CASES = (
    Case("C-5a", "INV-5.a", PrepareOnUnsaved, "SC-04-initial-publish:reader-prepared"),
    Case("C-5b", "INV-5.b", ClaimOnUnsaved, "SC-04-one-reference-missing"),
    Case("C-7c", "INV-7.c", LateRewritesTerminal, "SC-15-Wr-tie-unknown-first"),
    Case("C-15a", "INV-15.a", RecognizeOnUnsaved, "SC-15-Wr-tie-unknown-first"),
)


def _findings(report):
    return tuple(f for row in report.rows for f in row.violations)


@lru_cache(None)
def _scenario(scene_id):
    base, _, local = scene_id.partition(":")
    scene = next(s for s in scenes.SCENES if s.id == base)
    scenario, *_ = scenes.instantiate(scene)
    return _reader_prepared(scenario) if local == "reader-prepared" else scenario


@lru_cache(None)
def _control(scene_id):
    scenario = _scenario(scene_id)
    graph = m.explore(scenario, window=m.CorrectWindow(scenario.e0))
    return graph, check.check_exploration(scenario, graph)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_mutant(case, capsys):
    scenario = _scenario(case.scene)
    control, control_report = _control(case.scene)
    assert control.complete and not _findings(control_report), "legal control must pass"
    start = perf_counter()
    graph = m.explore(scenario, window=case.window(scenario.e0))
    report = check.check_exploration(scenario, graph)
    found = _findings(report)
    hits = tuple(f for f in found if f.condition_id == case.target)
    with capsys.disabled():
        print("\nRESULT", case.id, case.target, case.scene, "control", len(control.states),
              "mutant", len(graph.states), graph.complete, round(perf_counter() - start, 1),
              sorted({f.condition_id for f in found}), hits[:1])
    assert graph.complete
    assert hits
