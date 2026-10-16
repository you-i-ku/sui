"""F-b scene tests: short checks and the heavy denominator run.

Short route: run these two commands sequentially from the repository root.
  .venv/Scripts/python.exe -B -m pytest tests/test_fb_scenes.py -q -p no:cacheprovider -k "test_paper_denominator_is_preserved or test_all_paper_scenes_and_rows_remain_in_final_report"
  .venv/Scripts/python.exe -B -m pytest tests/test_fb_scenes.py -q -p no:cacheprovider -k "SC-04-DESC or SC-04-publish-Q-Wr or SC-04-publish-R-Wp"
2026-10-16 S-06 pre-migration measurements in this conversation: bookkeeping
1 failed / 1 passed / 202 deselected in 0.69 s; representatives 3 passed /
201 deselected in 78.33 s (allow about 80 seconds on this PC).
The final denominator gate intentionally stays red with
"45-row verdict remains incomplete" while required coverage is absent.

Heavy route (about 65 minutes; Claude runs this after the cleanup):
  .venv/Scripts/python.exe -B -m pytest tests/test_fb_scenes.py -q -p no:cacheprovider -k "not SC-01-same-rebuild and not SC-01-different-rebuild"
This excludes the two 50,000-state SC-01 rebuild families (4 parameterized cases).
Source: the 2026-10-16 S-06 user request reports Claude's prior result as
14 failed / 77 passed / 109 skipped / 4 deselected. The duration estimate and
these full-run totals are supplied evidence, not measurements by this cleanup.
Failures are state limits, mandatory reachability not established, and the
intentionally red final denominator gate.

Every paper branch remains in the report, including skipped/unconnected ones.
Historical records are read from fb_scenes_results.json; normal tests never
refresh them. Their original capture and paper_version remain unchanged.
-B and no:cacheprovider prevent bytecode/cache writes without environment changes.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import pytest

from fb_machine import Exploration, OutcomeKind, explore
from fb_check import check_exploration
import fb_check as public_check
from fb_scenes import (
    CONDITION_TABLE, FAIRNESS_TABLE, HUMAN_ROWS, IDENTIFICATION_TABLE, PAPER_PATH,
    ROWS_BY_LINE, SC_TABLE, SCENES, UNSPECIFIED_ROWS, ABSTRACT_FAIRNESS_CASES, instantiate,
)


REPORTS = []
PRINTED_CONNECTIONS = set()
CLASSIFICATIONS = ("確認済み", "識別力未確認", "未接続 (入口不足)", "未接続 (実装の段へ)", "未完 (上限)")


def _receipt_entries(state):
    contracts = {"sui.fb.received", "sui.fb.segment_report", "sui.fb.work_report", "sui.fb.draw_report",
                 "sui.s4.boot", "sui.fb.boot_declaration"}
    # Reachability of actual C/E, not a Saved assertion. Integrity is checked by
    # check_exploration; receipt.completion flags never supply expected content.
    seals = {body.seal for body in state.core.c}
    return tuple(e for e in state.core.e if e.header.record.contract.name in contracts and e.header.seal in seals)


def _saved(state, scene):
    expected_slots = sum(2 if p.event.kind == "Boot" else 1 for p in scene.e0.postings)
    return bool(expected_slots) and len(state.evidence.eh.originals) == len(scene.e0.postings) and len(_receipt_entries(state)) == expected_slots


def _held(state):
    return any(any(n for _, n in w.held) and not w.released for w in state.core.p.work)


def _has_unsaved_original(state):
    real = {entry.point for entry in _receipt_entries(state)}
    for original in state.evidence.eh.originals:
        receipt = next((r for r in state.core.p.receipts if r.envelope.key == original.key), None)
        if receipt is None:
            return True
        slots = {slot.plan.slot: slot for slot in receipt.unit.slots}
        required = ("boot", "declaration") if original.event.kind == "Boot" else ("receipt",)
        if any(name not in slots or slots[name].prepared is None or slots[name].prepared.point not in real for name in required):
            return True
    return False


def _tied_originals(state, work, unknown_first):
    """Observe EH, matching independently declared provenance and order."""
    sources = ("host:unknown-" + work, "worker:" + work)
    expected_kinds = (OutcomeKind.UNKNOWN, OutcomeKind.RETURNED)
    if not unknown_first:
        sources, expected_kinds = tuple(reversed(sources)), tuple(reversed(expected_kinds))
    originals = tuple(sorted((e for e in state.evidence.eh.originals if e.source in sources),
                             key=lambda e: e.receipt_seq))
    if len(originals) != 2:
        return ()
    first, second = originals
    if (first.run != second.run or first.r != second.r or first.number == second.number
            or first.receipt_seq >= second.receipt_seq
            or tuple(e.source for e in originals) != sources
            or tuple(e.event.fields.get("outcome").kind for e in originals) != expected_kinds):
        return ()
    return originals


def _saved_receipt_point(state, envelope):
    actual = {entry.point for entry in _receipt_entries(state)}
    for receipt in state.core.p.receipts:
        if receipt.envelope == envelope:
            for slot in receipt.unit.slots:
                if slot.plan.slot == "receipt" and slot.prepared is not None and slot.prepared.point in actual:
                    return slot.prepared.point
    return None


def _state_probe(goal, state, scene):
    p = state.core.p
    if goal.probe.startswith("tie_"):
        work, unknown_first = goal.args
        originals = _tied_originals(state, work, unknown_first)
        if not originals:
            return False
        first, second = originals
        if goal.probe == "tie_order":
            return first.run == scene.e0.run
        if goal.probe == "tie_retry":
            for envelope in originals:
                accepted = [e.value for e in state.evidence.observation_trace.events
                            if e.tag == "Accept" and e.value.envelope.key == envelope.key]
                if len(accepted) < 2 or any(a != accepted[0] or a.envelope != envelope for a in accepted):
                    return False
            return True
        if goal.probe == "tie_wait":
            return (_saved_receipt_point(state, first) is None
                    and _saved_receipt_point(state, second) is not None
                    and not any(e.tag == "Publish" and e.key.unit == "terminal:" + work
                                for e in state.evidence.observation_trace.events))
        if goal.probe == "tie_terminal":
            point = _saved_receipt_point(state, first)
            kind = OutcomeKind.UNKNOWN if unknown_first else OutcomeKind.RETURNED
            bodies = {body.seal for body in state.core.c}
            return point is not None and any(
                entry.header.seal in bodies
                and entry.header.record.contract.name == "sui.fb.work_terminal"
                and entry.header.record.content.get("work") == work
                and entry.header.record.content.get("first_receipt") == point
                and entry.header.record.content.get("terminal_kind") == kind
                for entry in state.core.e)
    probe = goal.probe
    if probe == "publish_kind":
        unit, work = goal.args
        real = {entry.point for entry in state.core.e}
        return any(u.id == unit and any(slot.prepared is None or slot.prepared.point not in real
                   for slot in u.slots) for u in p.units) and (
                   not work or any(w.descriptor.work_id == work for w in p.work))
    if probe == "work_entered":
        return any(r.descriptor_read is not None and r.descriptor_read.work_id == goal.args[0]
                   for r in state.core.runners)
    if probe == "work_wrappers":
        tokens = {w.token for w in p.work if w.descriptor.work_id == goal.args[0] and w.token is not None}
        return any(sum(wrapper.token == token for wrapper in state.core.wrappers) == 2 for token in tokens)
    if probe == "record_only":
        return any(u.id == goal.args[0] for u in p.units) and {w.descriptor.work_id for w in p.work} == {"wr"}
    if probe == "tag":
        return any(e.tag == goal.args[0] for e in state.evidence.observation_trace.events)
    if probe == "measure_row":
        return any(w.descriptor.stage == "MeasureSegment" for w in p.work)
    if probe == "stage_entered":
        return any(r.descriptor_read is not None and r.descriptor_read.stage == goal.args[0] for r in state.core.runners)
    if probe == "unreported":
        return any(c.key.obligation == "O-04" and c.key.kind == "handle" and c.unmet for c in p.conditions) and not any(
            e.header.record.contract.name == "sui.fb.segment_report" for e in state.core.e)
    if probe == "unknown_held":
        return any(e.source == "host:unknown-wr" for e in state.evidence.eh.originals) and _held(state)
    if probe == "work_reports":
        return sum(e.header.record.contract.name == "sui.fb.work_report" for e in _receipt_entries(state)) == goal.args[0]
    if probe == "prediction_parents":
        records = {e.point: e for e in state.core.e}
        predictions = [e for e in state.core.e if e.header.record.contract.name in ("computation_result", "computation_proof")]
        return len(predictions) == 2 and all(e.header.parents and all(p in records and
            records[p].header.record.contract.name == "computation_requested" for p in e.header.parents) for e in predictions)
    if probe == "acquired":
        return any(a.intent == "acquire-rp" and len(a.targets) == 2 and len(a.contents) == 2 for a in state.evidence.ea.acquisitions)
    if probe == "adopt_ancestor":
        records = {entry.point for entry in state.core.e}
        actual_g = {slot.prepared.point for unit in p.units if unit.id == "acquisition"
                    for slot in unit.slots if slot.plan.slot == "g" and slot.prepared is not None
                    and slot.prepared.point in records}
        return bool(actual_g) and any(event.tag == "Adopt" and actual_g <= event.value.actual_ancestors
                                      for event in state.evidence.observation_trace.events)
    if probe == "received_count":
        return sum(e.header.record.contract.name == "sui.fb.received" for e in _receipt_entries(state)) == goal.args[0]
    if probe == "derived_count":
        return sum(e.header.record.contract.name == "computation_requested" and e.header.record.name.startswith("q-e") for e in state.core.e) == goal.args[0]
    if probe == "saved_slots":
        unit, *names = goal.args
        real = {entry.point for entry in state.core.e}
        return any(u.id == unit and all(any(s.plan.slot == name and s.prepared is not None
                   and s.prepared.point in real for s in u.slots) for name in names) for u in p.units)
    if probe == "c_blocked_before_p":
        real = {entry.point for entry in state.core.e}
        proof = next((unit for unit in p.units if unit.id == "proof"), None)
        if proof is None:
            return False
        saved = {slot.plan.slot for slot in proof.slots
                 if slot.prepared is not None and slot.prepared.point in real}
        return {"started", "finished"} <= saved and "p" not in saved and not any(
            slot.prepared is not None for unit in p.units if unit.id == "completed" for slot in unit.slots)
    if probe == "wp_wait":
        return any(w.descriptor.work_id == "wp" and not w.held for w in p.work) and not any(
            e.header.record.contract.name == "computation_result" for e in state.core.e)
    if probe == "wp_ready":
        return any(w.descriptor.work_id == "wp" and w.held for w in p.work) and any(
            e.header.record.contract.name == "computation_result" for e in state.core.e)
    if probe == "one_completed":
        return sum(e.header.record.contract.name == "computation_completed" for e in state.core.e) == 1
    if probe == "post_pending":
        accepted = {r.envelope.key for r in p.receipts}
        return any(e.key not in accepted for e in state.core.h.queue)
    if probe == "accepted_pending_ack":
        return any(r.envelope.key not in state.evidence.eh.acknowledgements for r in p.receipts)
    if probe == "receipts_saved":
        return _saved(state, scene)
    if probe == "body_only":
        return bool(state.core.c) and not state.core.e
    if probe == "boot_partial":
        contracts = [e.header.record.contract.name for e in _receipt_entries(state)]
        return sum(c in ("sui.s4.boot", "sui.fb.boot_declaration") for c in contracts) == 1
    if probe == "prepared":
        return bool(state.evidence.ep.first_preparations)
    if probe == "published_unsaved":
        return any(u.id == "initial" and all(s.prepared is None for s in u.slots) for u in p.units) and bool(p.work)
    if probe == "one_missing":
        for u in p.units:
            if u.id == "initial":
                real = {e.point for e in state.core.e}
                return sum(s.prepared is None or s.prepared.point not in real for s in u.slots) == 1 and bool(p.work)
        return False
    if probe == "resolved":
        return any(w.resolutions for w in p.work)
    if probe == "held_n":
        return _held(state) and not state.core.wrappers and not state.core.runners
    if probe == "held_r":
        return _held(state) and bool(state.core.wrappers) and not state.core.runners
    if probe == "entered":
        return _held(state) and bool(state.core.runners)
    if probe == "end_known":
        return any(w.knowledge is not None and w.first is not None for w in p.work)
    if probe == "released":
        actual = {e.tag for e in state.evidence.observation_trace.events}
        return any(w.stopped and w.released for w in p.work) and {"Stop", "Release"} <= actual
    if probe == "double-wrapper":
        return len(state.core.wrappers) == 2 and len({w.token for w in state.core.wrappers}) == 1
    if probe == "start-unknown":
        return any(w.start_unknown and w.held for w in p.work)
    if probe == "hung_receipt":
        return _saved(state, scene) and _held(state) and bool(state.core.runners) and not any(w.stopped for w in p.work)
    if probe == "resource_triple":
        occ = sum(n for w in p.work if not w.released for r, n in w.held if r == "think")
        return (occ, dict(scene.e0.allocation)["think"], dict(scene.e0.capacity)["think"]) == goal.args
    if probe == "undertaken":
        return bool(state.core.h.interval_requests) and any(c.key.obligation == "O-04" and c.unmet for c in p.conditions)
    if probe == "no_computation":
        return (_saved(state, scene) and all(w.descriptor.stage == "MeasureSegment" for w in p.work)
                and all(r.descriptor_read is not None and r.descriptor_read.stage == "MeasureSegment" for r in state.core.runners))
    return False


def _edge_probe(goal, edge, before, after, scene):
    op = edge.action.operation
    probe = goal.probe
    if probe == "reaccept":
        return op == "Accept" and bool(edge.action.target) and any(
            r.envelope == edge.action.target[0] and r.envelope.key not in before.evidence.eh.acknowledgements
            for r in before.core.p.receipts)
    if probe == "rebuild":
        return op == "RebuildWindow" and _has_unsaved_original(before)
    if probe == "rebuild_unconfirmed":
        real = {entry.point for entry in _receipt_entries(before)}
        return op == "RebuildWindow" and any(slot.prepared is not None and slot.prepared.point in real
            and not slot.entry_confirmed for receipt in before.core.p.receipts for slot in receipt.unit.slots)
    if probe == "io_retry":
        # A prior actual I/O to the same target is required; a first call does
        # not count merely because PreparedEntry exists.
        return op in ("PutBody", "AddEntry") and any(
            event.tag == "IORequest" and event.key.operation == op
            and (event.key.slot.unit, event.key.slot.slot) == edge.action.target
            for event in before.evidence.observation_trace.events)
    if probe == "fault":
        mode = goal.args[0]
        wanted = "AddEntry" if mode.startswith("entry-") else "PutBody"
        return op == wanted and edge.action.outcome != "normal" and (
            edge.action.outcome == "lost_response" if "precommit" not in mode else edge.action.outcome != "lost_response")
    if probe == "drain":
        # Drain is enumeration: a self-edge can be traversed twice unchanged.
        return op == "Drain" and before.core.p.work and before == after
    if probe == "not-started-retry":
        return op == "Launch" and before.controls.budget.launch_failures == 0 and _held(before) and bool(before.evidence.ew.events)
    if probe == "held_operation":
        return op == goal.args[0] and _held(before) and _held(after)
    if probe == "wait_pending":
        return op == "Wait" and bool(before.evidence.eh.originals) and not _saved(before, scene)
    if probe == "wait_saved":
        return op == "Wait" and _saved(before, scene)
    return False


def _reachability(scene, graph, prefix_states, prefix_edges, prefix_enabled):
    found = {}
    for label, states, edges, offered in (("prefix", prefix_states, prefix_edges, prefix_enabled),
                                         ("graph", graph.states, graph.edges, graph.enabled)):
        for index, state in enumerate(states):
            for goal in scene.goals:
                if goal.id not in found and _state_probe(goal, state, scene):
                    if goal.probe == "c_blocked_before_p" and (index >= len(offered) or any(
                        action.operation in ("PublishUnit", "PrepareOne") and action.target
                        and action.target[0] == "completed" for action in offered[index])):
                        continue
                    if goal.probe == "tie_wait" and (index >= len(offered) or any(
                        action.operation == "RecognizeTerminal" and action.target == (goal.args[0],)
                        for action in offered[index])):
                        continue
                    found[goal.id] = {"where": label, "state": index}
        for index, edge in enumerate(edges):
            for goal in scene.goals:
                if goal.id not in found and _edge_probe(goal, edge, states[edge.source], states[edge.target], scene):
                    found[goal.id] = {"where": label, "edge": index, "state": edge.target}
    result = {}
    for goal in scene.goals:
        if goal.id in found:
            witness = found[goal.id]
            if witness["where"] == "graph":
                if "edge" in witness:
                    edge = graph.edges[witness["edge"]]
                    actions = graph.trace(edge.source) + (edge.action,)
                else:
                    actions = graph.trace(witness["state"])
                witness["path"] = [repr(a) for a in actions]
            else:
                witness["path"] = [repr(e.action) for e in prefix_edges[:witness["state"]]]
            result[goal.id] = {"status": "到達した", "text": goal.text, "witness": witness}
        else:
            result[goal.id] = {"status": "未確認" if goal.probe == "unconnected" or not graph.complete else "しなかった",
                               "text": goal.text, "reason": goal.args if goal.probe == "unconnected" else ()}
    return result


def _findings(report, phase, graph):
    result = []
    for f in report.violations:
        item = {"row": f.condition_id, "phase": phase, "location": str(f.location),
                "message": f.message, "target": repr(f.target)[:600],
                "triage": "未切分け: 窓口/紙/行/場面。実装本体は未読。"}
        # Keep a small representative path, not a generated expected E0.
        location = f.location
        if isinstance(location, int) and 0 <= location < len(graph.states):
            item["path"] = [repr(a) for a in graph.trace(location)]
        result.append(item)
    return result


def _row_results(scene, reports, reachability, complete):
    rows = {}
    all_reached = all(r["status"] == "到達した" for r in reachability.values())
    for condition, line in CONDITION_TABLE.items():
        observations = [next(r for r in report.rows if r.condition_id == condition) for report in reports]
        violations = sum(len(r.violations) for r in observations)
        limitations = sorted({str(limit) for r in observations for limit in r.limitations})
        connected = all(r.observation_connection == "約束接続・部分判定" for r in observations)
        seen = sum(r.observations for r in observations)
        if condition in scene.applicable_rows and not complete:
            classification = "未完 (上限)"
        elif (condition not in scene.applicable_rows or not all_reached or not connected or not seen
              or "target_not_reached" in limitations
              or any(limit.startswith("約束の未接続:") for limit in limitations)):
            classification = "未接続 (入口不足)"
        else:
            # This is positive structural observation, never full row coverage.
            # Violations stay separate and prevent a pass; all limitations and
            # the 32 unspecified contrasts remain in the 45-row aggregate.
            classification = "識別力未確認"
        rows[condition] = {"paper_line": line, "classification": classification, "violations": violations,
                           "observations": seen, "limitations": limitations, "connected": connected,
                           "identification": "未具体化" if condition in UNSPECIFIED_ROWS else "条件差具体化済み・負の対照未実行"}
    return rows


def _print_report(result, capsys):
    compact = {key: result.get(key) for key in ("id", "paper", "initial", "cut", "max_states", "states", "edges",
                                               "seconds", "check_seconds", "execution", "counts", "applicable")}
    compact["reach"] = {key: value["status"] for key, value in result["reach"].items()}
    compact["H-01..06"] = "未点検"
    with capsys.disabled():
        print("\nSCENE " + json.dumps(compact, ensure_ascii=False), flush=True)
        connection = result.get("connection", "")
        if connection.startswith("{") and connection not in PRINTED_CONNECTIONS:
            PRINTED_CONNECTIONS.add(connection)
            snapshot = json.loads(connection)
            kept = {key: snapshot[key] for key in ("actions", "records", "work", "unmet", "EH", "EW", "EA", "EI")}
            print("  CONNECTION " + json.dumps({"scene": result["id"], **kept}, ensure_ascii=False), flush=True)
        for key, goal in result["reach"].items():
            if "witness" in goal:
                witness = dict(goal["witness"])
                if witness["where"] == "prefix":
                    witness["connection_prefix_steps"] = len(witness.pop("path"))
                print("  REACHED " + json.dumps({"scene": result["id"], "goal": key, **witness}, ensure_ascii=False), flush=True)
        if result.get("error"):
            print("  ERROR " + result["error"], flush=True)
        unique = {}
        for finding in result.get("findings", ()):
            signature = (finding["row"], finding["message"])
            unique.setdefault(signature, finding)
        for finding in unique.values():
            print("  FINDING " + json.dumps(finding, ensure_ascii=False), flush=True)
        if result.get("contract_violations"):
            print("  CONTRACT " + repr(result["contract_violations"]), flush=True)
        if "rows" in result:
            limits = sorted({v for r in result["rows"].values() for v in r["limitations"]})
            rows = {key: {**r, "limitations": [limits.index(v) for v in r["limitations"]]}
                    for key, r in result["rows"].items()}
            print("  ROWS " + json.dumps({"id": result["id"], "rows": rows, "limit_notes": limits,
                "unconnected": result.get("unconnected", ())}, ensure_ascii=False), flush=True)


def test_paper_denominator_is_preserved(capsys):
    assert len(SC_TABLE) == 22  # SC-07a and SC-07b are separate.
    assert len(IDENTIFICATION_TABLE) == 13
    assert len(FAIRNESS_TABLE) == 6
    assert len(CONDITION_TABLE) == 45
    assert len(UNSPECIFIED_ROWS) == 32
    assert {s.paper_id for s in SCENES} == set(SC_TABLE) | set(IDENTIFICATION_TABLE) | set(FAIRNESS_TABLE)
    assert len({s.id for s in SCENES}) == len(SCENES)
    assert all(0 < s.max_states <= 200_000 for s in SCENES)
    assert all(s.e0 is not None or s.blocker for s in SCENES)
    assert len(SCENES) == 193
    assert all(s.scope_class in ("a", "b", "c") and s.scope_reason for s in SCENES)
    assert len(next(s for s in SCENES if s.id == "SC-04-other-publish-kinds").parts) == 9
    assert all(s.goals and s.applicable_rows for s in SCENES)
    tied = [s for s in SCENES if s.id.startswith("SC-15-") and "-tie-" in s.id]
    assert len(tied) == 12 and Counter(s.scope_class for s in tied) == {"a": 6, "b": 6}
    for stage in ("Wr", "Wp", "Wv"):
        pair = [next(s for s in tied if s.id == "SC-15-" + stage + "-tie-" + order)
                for order in ("unknown-first", "value-first")]
        # Between the two independent input declarations only delivery order
        # changes; generation, actual replies and normative plans stay fixed.
        assert replace(pair[0].e0, delivery_bundles=pair[1].e0.delivery_bundles) == pair[1].e0
        assert {g.id for g in pair[0].goals} <= {g.id for g in pair[1].goals}
    # A replaced audit must preserve every declaration and every checker row;
    # these bookkeeping assertions do not certify its recorded model results.
    assert {m["id"] for m in RECORDED_OBSERVATION_EVIDENCE["manifest"]} == {s.id for s in SCENES}
    assert {r["id"] for r in RECORDED_OBSERVATION_EVIDENCE["latest_reports"]} == {s.id for s in SCENES}
    assert {r["id"] for r in RECORDED_OBSERVATION_EVIDENCE["row_aggregate"]} == set(CONDITION_TABLE)
    assert all(sum(r["counts"].values()) == 45 for r in RECORDED_OBSERVATION_EVIDENCE["latest_reports"]
               if "counts" in r)
    if RECORDED_OBSERVATION_EVIDENCE["schema_version"] >= 3:
        assert all(set(r["counts"]) == set(CLASSIFICATIONS)
                   for r in RECORDED_OBSERVATION_EVIDENCE["latest_reports"])
        assert len(RECORDED_OBSERVATION_EVIDENCE["publish_reports"]) == 9
        assert RECORDED_OBSERVATION_EVIDENCE["metrics"]["denominator_branches"] == 193
        assert sum(RECORDED_OBSERVATION_EVIDENCE["metrics"]["row_counts"].values()) == 45
    with capsys.disabled():
        notes = tuple(dict.fromkeys(text for s in SCENES for text in (s.blocker, *s.remaining, *s.assumptions) if text))
        print("\nMANIFEST-NOTES " + json.dumps(notes, ensure_ascii=False), flush=True)
        print("\nMANIFEST " + json.dumps([{
            "id": s.id, "paper_id": s.paper_id, "paper": s.lines, "initial": s.initial_id,
            "cut": s.cut.id, "excluded": sorted(s.cut.excluded_operations), "max_states": s.max_states,
            "has_e0": s.e0 is not None, "applicable": s.applicable_rows,
            "goals": {g.id: g.text for g in s.goals}, "blocker_note": notes.index(s.blocker) if s.blocker else None,
            "remaining_notes": [notes.index(v) for v in s.remaining],
            "assumption_notes": [notes.index(v) for v in s.assumptions],
            "scope_class": s.scope_class, "scope_reason": s.scope_reason,
            "implementation_scope": s.implementation_scope,
            "parts": [{"id": part.id, "scope_class": part.scope_class, "scope_reason": part.scope_reason,
                       "initial": part.initial_id, "paper": part.lines, "cut": part.cut.id,
                       "max_states": part.max_states, "has_e0": part.e0 is not None,
                       "goals": {g.id: g.text for g in part.goals}} for part in s.parts]} for s in SCENES], ensure_ascii=False), flush=True)


def _abstract_case(scene, result):
    """Paper candidate declarations, never a fabricated reachable State."""
    started = perf_counter()
    if scene.paper_id == "SC-05-CYCLE":
        observed = public_check.acyclic({"a": frozenset(("b",)), "b": frozenset()})
        expected = True
        result.update(states=2, edges=1, abstract={"positive_acyclic": observed, "negative_cycle": "not_run"})
    else:
        case = next(c for c in ABSTRACT_FAIRNESS_CASES if c.id == scene.id)
        index = {v.id: i for i, v in enumerate(case.vertices)}
        edges = tuple((index[a], index[b], label) for a, b, label in case.candidate_edges)
        enabled = {index[node]: frozenset(labels) for node, labels in case.enabled}
        if "-T" in case.id:
            candidates = public_check.progress_counterexamples((0,), edges, enabled)
            fair = public_check.fair_cycle((0,), edges, enabled)
            observed = (fair, bool(candidates))
            expected = (False, False) if case.id.endswith("T1") else (True, True)
        else:
            unpublished = {index[v.id] for v in case.vertices if v.unpublished}
            ready = {index[v.id] for v in case.vertices if ("o", True) in v.ready_n}
            pending = {index[v.id] for v in case.vertices if v.phase == "P"}
            discharged = {index[v.id] for v in case.vertices if v.phase.startswith("S")}
            formula = public_check.derive_progress(unpublished, ready, pending, discharged, edges, enabled,
                                                   environment_ready=set(index.values()))
            observed = None if formula is None else (bool(formula["N"]), bool(formula["P"]))
            expected = (case.id.endswith("N4"), False)
        result.update(states=len(case.vertices), edges=len(edges),
                      abstract={"observed": observed, "expected": expected, "paper_expected": case.expected,
                                "full_enabled": repr(enabled), "full_edges": repr(case.full_edges),
                                "candidate_edges": repr(edges), "vertices": repr(case.vertices),
                                "normal_window_credit": False, "INV-2.d": "not_run" if case.id.endswith("N4") else "not_applicable"})
    result["abstract"]["normal_window_credit"] = False
    result.update(execution="抽象入力実行", seconds=round(perf_counter()-started, 6), check_seconds=0.0)
    result["reach"] = {"candidate-formula": {"status": "到達した" if observed == expected else "しなかった",
                                           "text": "紙が定めた候補の分類（実模型の到達ではない）"}}
    return observed == expected


@pytest.mark.parametrize("scene", [part for scene in SCENES for part in (scene.parts or (scene,))], ids=lambda s: s.id)
def test_scene(scene, capsys):
    result = {"id": scene.id, "paper_id": scene.paper_id, "paper": list(scene.lines),
              "initial": scene.initial_id, "cut": scene.cut.id, "max_states": scene.max_states,
              "states": None, "edges": None, "seconds": None, "check_seconds": None,
              "execution": "未実行", "applicable": scene.applicable_rows,
              "assumptions": scene.assumptions, "remaining": scene.remaining,
              "negative_controls": scene.negative_controls, "human": dict(HUMAN_ROWS),
              "reach": {g.id: {"status": "未確認", "text": g.text} for g in scene.goals},
              "counts": {name: 45 if name == "未接続 (入口不足)" else 0 for name in CLASSIFICATIONS},
              "blocker": scene.blocker, "findings": []}
    result.update(scope_class=scene.scope_class, scope_reason=scene.scope_reason,
                  implementation_scope=scene.implementation_scope)
    REPORTS.append(result)
    if scene.paper_id in FAIRNESS_TABLE or scene.paper_id == "SC-05-CYCLE":
        matched = _abstract_case(scene, result)
        _print_report(result, capsys)
        with capsys.disabled():
            print("  ABSTRACT " + json.dumps({"id": scene.id, **result["abstract"]}, ensure_ascii=False), flush=True)
        assert matched, "public abstract clause differs from paper expectation"
        return
    if scene.e0 is None:
        if scene.scope_class == "b":
            result["execution"] = "範囲外 (実装の段へ)"
            result["counts"] = {name: len(scene.applicable_rows) if name == "未接続 (実装の段へ)" else
                                45 - len(scene.applicable_rows) if name == "未接続 (入口不足)" else 0
                                for name in CLASSIFICATIONS}
        _print_report(result, capsys)
        pytest.skip(scene.blocker)
    try:
        scenario, prefix_states, prefix_edges, prefix_enabled = instantiate(scene)
        result["connection"] = scenario.initial_connection
        frozen_expected = scene.e0.observation_declarations
        graph = explore(scenario)
        result.update(states=len(graph.states), edges=len(graph.edges), seconds=round(graph.elapsed_seconds, 6),
                      execution="完走" if graph.complete else "探索未完", omitted=len(graph.omitted), frontier=list(graph.frontier))
        with capsys.disabled():
            print(f"\nEXPLORED {scene.id}: states={len(graph.states)} edges={len(graph.edges)} "
                  f"seconds={graph.elapsed_seconds:.6f} complete={graph.complete}; checking all rows", flush=True)
        started = perf_counter()
        report = check_exploration(scenario, graph)
        reports = [report]
        findings = _findings(report, "exploration", graph)
        if prefix_states:
            # The prefix is a path, not a complete graph. All actual Enabled
            # sets are retained, and complete=False prevents a liveness pass.
            prefix = Exploration(scene.id + "/prefix", prefix_states, prefix_edges, prefix_enabled,
                                 False, (len(prefix_states)-1,), (), 0.0,
                                 (None,) + tuple((i, edge.action) for i, edge in enumerate(prefix_edges)),
                                 ("合法な前置経路だけ。別順序は未探索。",))
            prefix_report = check_exploration(scenario, prefix)
            reports.append(prefix_report)
            findings.extend(_findings(prefix_report, "prefix", prefix))
        result["check_seconds"] = round(perf_counter()-started, 6)
        result["reach"] = _reachability(scene, graph, prefix_states, prefix_edges, prefix_enabled)
        result["rows"] = _row_results(scene, reports, result["reach"], graph.complete)
        counts = Counter(row["classification"] for row in result["rows"].values())
        result["counts"] = {name: counts[name] for name in CLASSIFICATIONS}
        result["checker_counts"] = report.counts
        result["findings"] = findings
        if any(f["row"] == "INV-9.a" for f in findings):
            # Diagnostic observations only; never fed back into E0 declarations.
            actual = sorted({(event.tag, repr(event.key), repr(getattr(event.value, "verification", None)),
                              repr(getattr(event.value, "acquisitions", None)),
                              repr(getattr(event.value, "actual_ancestors", None)))
                             for state in graph.states for event in state.evidence.observation_trace.events
                             if event.tag in ("Acquire", "VerifyCall", "VerifyReply", "Adopt")})
            result["adoption_diagnostic"] = {"declared": repr(frozen_expected.adoptions),
                                              "verification": repr(frozen_expected.verifications), "actual": actual}
            with capsys.disabled():
                print("  ADOPTION-DIAGNOSTIC " + json.dumps({"id": scene.id, **result["adoption_diagnostic"]}, ensure_ascii=False), flush=True)
        if any(f["row"] in ("INV-5.a", "INV-7.b") for f in findings):
            result["reference_declarations"] = [
                {"contract": repr(record.contract), "references": repr(record.references),
                 "actual_saved_references": sorted({repr(entry.header.record.references) for state in graph.states
                                                     for entry in state.core.e if entry.header.record.contract == record.contract}),
                 "field_roles": [repr(role) for role in scene.e0.field_roles if role.record_contract == record.contract],
                 "observation_bindings": [repr(binding) for binding in frozen_expected.references
                                          if binding.record_contract == record.contract]}
                for plan in scene.e0.plans for record in plan.records if record.references]
            with capsys.disabled():
                print("  DECLARED-REFERENCES " + json.dumps(result["reference_declarations"], ensure_ascii=False), flush=True)
        result["contract_violations"] = [repr(v) for r in reports for v in r.contract_violations]
        result["unconnected"] = sorted({repr(v) for r in reports for v in r.unconnected_observations})
        assert scene.e0.observation_declarations == frozen_expected, "E0 changed during execution"
        assert {r.condition_id for r in report.rows} == set(CONDITION_TABLE), "checker denominator differs from paper"
        assert sum(result["counts"].values()) == 45
    except Exception as error:
        # Do not expose or inspect the forbidden implementation in tracebacks.
        result["execution"] = "実行エラー"
        result["error"] = f"{type(error).__name__}: {error}"
        _print_report(result, capsys)
        pytest.fail(result["error"], pytrace=False)
    _print_report(result, capsys)
    problems = []
    if not graph.complete:
        problems.append("state limit reached; not a normal terminal")
    missing = [key for key, value in result["reach"].items() if value["status"] != "到達した"]
    if missing:
        problems.append("required states unreached/unconfirmed: " + ",".join(missing))
    if result["findings"] or result["contract_violations"]:
        problems.append("correct-window report contains violations; scene expectations retained")
    if problems:
        pytest.fail("; ".join(problems), pytrace=False)


def test_same_r_wv_historical_view_regression(capsys):
    """解消済みP-10: 後のV保存が過去のT.viewに漏れ込む誤検出の回帰。"""
    try:
        _same_r_wv_historical_view_regression(capsys)
    except Exception as error:
        pytest.fail(f"{type(error).__name__}: {error}", pytrace=False)


def _same_r_wv_historical_view_regression(capsys):
    """Resolved P-10 false-positive regression through the public adapter.

    Keep the original first-receipt-body-only boundary and unchanged E0.
    T is prepared before V is Saved: later storage cannot change the view
    used at issuance (paper 1044; PUBLIC_CHECK_CONTRACTS trace_at).
    This finite path is not a new denominator branch or complete exploration.
    """
    from fb_machine import Action, CorrectWindow, Edge, Environment, View, receipt_unit_id
    scene = next(s for s in SCENES if s.id == "SC-15-Wv-tie-value-first")
    scene = replace(scene, prefix="v2:tie:wv")
    scenario, prefix_states, _, _ = instantiate(scene)
    state = prefix_states[-1]
    first = next(e for e in state.evidence.eh.originals if e.source == "worker:wv")
    unit = receipt_unit_id(first.run, first.number)  # actual routing only
    path = (Action("AddEntry", (unit, "receipt")), Action("RecognizeTerminal", ("wv",)),
            Action("PrepareOne", ("terminal:wv", "T")), Action("PrepareOne", ("verification:wv", "V")),
            Action("PutBody", ("verification:wv", "V")), Action("AddEntry", ("verification:wv", "V")))
    env, window = Environment(scene.e0), CorrectWindow(scene.e0)
    states, edges, enabled = [state], [], []
    for action in path:
        offered = tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(env.actions(state))
        assert action in offered
        enabled.append(offered)
        step = env.step(state, action, window)
        edges.append(Edge(len(states)-1, len(states), action, step.events, step.result))
        states.append(step.state)
        state = step.state
    enabled.append(tuple(window.enabled(View(state.core, state.controls, state.evidence))) + tuple(env.actions(state)))
    graph = Exploration(scene.id + "/historical-view-regression", tuple(states), tuple(edges), tuple(enabled), False,
        (len(states)-1,), (), 0.0, (None,) + tuple((i, e.action) for i, e in enumerate(edges)),
        ("解消済みP-10の6歩の回帰。主場面とは別のT準備→V保存順序だけ。",))
    report = check_exploration(scenario, graph)
    edge = edges[-1]
    before, after = states[-2:]
    before_unit = next(u for u in before.core.p.units if u.id == "terminal:wv")
    after_unit = next(u for u in after.core.p.units if u.id == "terminal:wv")
    slot = next(s for s in after_unit.slots if s.plan.slot == "T")
    declared_t = next(p for p in scene.e0.publication_plans if p.unit == "terminal:wv").records[0]
    # Independent E0 projection at the actual Publish root, used for triage
    # only. It never changes the scene, a normative plan, or its pass criteria.
    projected = public_check.publication_value(scene.e0.observation_declarations,
        states[1].evidence.observation_trace, "terminal:wv", declared_t.content)
    prepared_content = slot.prepared.record.content
    changed_fields = sorted(key for key in {k for k, _ in projected.items} | {k for k, _ in prepared_content.items}
                            if prepared_content.get(key) != projected.get(key))
    diagnostic = {"scene": scene.id, "graph_complete": graph.complete,
        "states": len(graph.states), "edges": len(graph.edges), "seconds": graph.elapsed_seconds,
        "edge": [edge.source, edge.target], "action": repr(edge.action),
        "path": [repr(a) for a in path],
        "declared_content": repr(next(p for p in scene.e0.publication_plans if p.unit == "terminal:wv").records[0].content),
        "prepared_view": repr(slot.prepared.record.content.get("view")) if slot.prepared else None,
        "issued_view": repr(before_unit.issued_view),
        "prepared_view_equals_publish_view": prepared_content.get("view") == before_unit.issued_view,
        "prepared_content_equals_independent_publish_projection": prepared_content == projected,
        "prepared_content_differs_from_independent_publish_projection": changed_fields,
        "violations": _findings(report, "regression-path", graph),
        "limitations": sorted({str(v) for row in report.rows for v in row.limitations})}
    with capsys.disabled():
        print("\nTERMINAL-REGRESSION " + json.dumps(diagnostic, ensure_ascii=False), flush=True)
    assert diagnostic["prepared_view_equals_publish_view"]
    assert diagnostic["prepared_content_equals_independent_publish_projection"]
    if report.violations:
        pytest.fail("resolved P-10 regression has public edge violations; expectations retained", pytrace=False)


def _paper_aggregate(reports):
    """One item per paper row. Partial positive observations are not full rows.

    A row may have several deficits; all branch lists remain visible. The
    exclusive displayed category uses limit > implementation > entry > contrast.
    Abstract negative candidates never contribute correct-window credit.
    """
    by_id = {r["id"]: r for r in reports}
    aggregate = []
    for row, line in CONDITION_TABLE.items():
        limits, implementation, entry, positive = [], [], [], []
        # A checker violation outside this scene's paper index must not vanish
        # from the 45-row report (P-09 observes first preparation of T).
        violations = [f for report in by_id.values() for f in report.get("findings", ()) if f["row"] == row]
        for parent in SCENES:
            if row not in parent.applicable_rows:
                continue
            for scene in parent.parts or (parent,):
                report = by_id.get(scene.id)
                if scene.scope_class == "b":
                    implementation.append(scene.id)
                elif scene.scope_class == "c" or report is None:
                    entry.append(scene.id)
                elif report["execution"] == "探索未完":
                    limits.append(scene.id)
                elif report["execution"] != "完走" or any(
                    (g["status"] if isinstance(g, dict) else g) != "到達した" for g in report["reach"].values()):
                    entry.append(scene.id)
                elif report.get("rows", {}).get(row, {}).get("classification") == "識別力未確認":
                    positive.append(scene.id)
                else:
                    entry.append(scene.id)
        status = ("未完 (上限)" if limits else "未接続 (実装の段へ)" if implementation else
                  "未接続 (入口不足)" if entry else "識別力未確認")
        aggregate.append({"id": row, "paper_line": line, "classification": status,
            "limit_branches": limits, "implementation_branches": implementation,
            "entry_or_observation_branches": entry, "positive_structural_branches": positive,
            "violations": violations, "identification": "未具体化" if row in UNSPECIFIED_ROWS else
            "条件差具体化済み・負の対照未実行"})
    return aggregate


def _aggregate_disjoint_breakdown(aggregate):
    """Partition each displayed category by ALL outstanding reason families.

    'SC-01 50,000 only' refers to the state-limit cause, not to all reasons:
    implementation-stage and observation deficits remain explicit booleans.
    Every one of the 45 rows appears in exactly one group.
    """
    retained_sc01 = {"SC-01-" + content + "-rebuild" + rebuild
                    for content in ("same", "different") for rebuild in ("0", "1")}
    groups = {}
    for row in aggregate:
        limits = set(row["limit_branches"])
        limit_kind = ("SC-01 50,000のみ" if limits and limits <= retained_sc01 else
                      "SC-01 50,000と他の上限" if limits & retained_sc01 else
                      "他の上限のみ" if limits else "上限なし")
        key = (row["classification"], limit_kind, bool(row["implementation_branches"]),
               bool(row["entry_or_observation_branches"]))
        groups.setdefault(key, []).append(row["id"])
    return [{"classification": key[0], "limit_cause": key[1], "implementation_deficit": key[2],
             "entry_or_observation_deficit": key[3], "count": len(rows), "rows": rows}
            for key, rows in groups.items()]


def test_all_paper_scenes_and_rows_remain_in_final_report(capsys):
    # An audit replay is explicitly labelled; it is never model execution.
    records = {r["id"]: r for r in RECORDED_OBSERVATION_EVIDENCE["latest_reports"]}
    records.update({r["id"]: r for r in RECORDED_OBSERVATION_EVIDENCE.get("publish_reports", ())})
    records.update({r["id"]: r for r in REPORTS})
    rows = _paper_aggregate(tuple(records.values()))
    if not REPORTS and RECORDED_OBSERVATION_EVIDENCE["schema_version"] >= 4:
        assert rows == RECORDED_OBSERVATION_EVIDENCE["row_aggregate"], "recorded row aggregation is stale"
        assert _aggregate_disjoint_breakdown(rows) == RECORDED_OBSERVATION_EVIDENCE["disjoint_breakdown"]
    with capsys.disabled():
        print("\nPAPER: 193 branches / 45 rows; SC-04 has 9 named subcases, not 9 additional denominator branches.")
        print("AGGREGATE " + json.dumps(rows, ensure_ascii=False), flush=True)
        print("COUNTS " + json.dumps({name: sum(r["classification"] == name for r in rows)
                                     for name in CLASSIFICATIONS}, ensure_ascii=False), flush=True)
        print("DISJOINT " + json.dumps(_aggregate_disjoint_breakdown(rows), ensure_ascii=False), flush=True)
        print("Recorded data not rerun in this invocation retain their capture/version; H-01..06: 未点検.")
    assert len(rows) == 45
    if any(r["classification"] != "確認済み" or r["violations"] for r in rows):
        pytest.fail("45-row verdict remains incomplete: finite/implementation/connection limits, "
                    "32 unspecified contrasts, all negative controls and H-01..06 remain in the denominator.", pytrace=False)


# Historical execution audit only; not used by E0, reach probes or behavioral oracles.
# Bookkeeping tests still cross-check the recorded denominator and aggregation.
_RECORDED_RESULTS = json.loads(
    Path(__file__).with_name("fb_scenes_results.json").read_text(encoding="utf-8")
)["records"]
RECORDED_RUN_REPORT_MARKDOWN = _RECORDED_RESULTS["RECORDED_RUN_REPORT_MARKDOWN"]
RECORDED_OBSERVATION_EVIDENCE = _RECORDED_RESULTS["RECORDED_OBSERVATION_EVIDENCE"]
