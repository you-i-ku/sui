"""Public records/context builder for S4b time fixtures; no production internals.

All physical scenarios are declared by the caller. Integer values passed here
are CLOCK READINGS, not inferred physical times. A check fact is chosen by
received_ns equality, never by Record.at or list position. Facts are appended
in their explicit causal order, with a public in-memory ledger frontier.
"""
from fractions import Fraction as F
import json

from s4b_action_cases import NS, api, budget, load_model


def targets(record):
    """v0.22: identify the attempt and position, never the report record ID."""
    cls = api("action_types").TargetRef
    assert record.body.caused_by is not None
    return tuple(cls(attempt=str(record.body.caused_by), position=p, side="post")
                 for p in ("measurement", "completion"))


class FactWorld:
    def __init__(self, declaration):
        from sui.ledger import Ledger, SequentialSalts
        from worlds import HandHistory
        self.d = declaration
        self.model = load_model(declaration)
        self.h = HandHistory(run="s4b-time-ruler")
        self.ledger = Ledger(salts=SequentialSalts())
        boot = self.h.boot()
        self.ledger.append(boot, self.ledger.heads())

    @property
    def records(self):
        return self.h.records

    def append(self, body, reading_ns):
        record = self.h.add(body, F(reading_ns, NS))
        self.ledger.append(record, self.ledger.heads())
        return record

    def start(self, choice, reading_ns, *, stage=0, position=0):
        from sui.contracts import ContractRef
        from sui.ids import Ref, RefKind
        from sui.records import JobOpened, AttemptStarted, Payload
        decision = api("action_types").DecisionReading(run=self.h.clock.run,
            reading_ns=reading_ns, work="specified-clock-reading", parents=frozenset(self.ledger.heads()))
        cmd = api("dispatch").build_command(model=self.model, choice=choice, decision=decision,
                                             causal_stage=stage, causal_position=position)
        data = json.loads(api("dispatch").command_json(cmd))
        job = self.append(JobOpened(decision=Ref(RefKind.DECISION, "forced-control"), step=stage,
            content=Payload.json({k: data[k] for k in ("action", "choice", "reservation_rule", "dispatch", "effect")}),
            contract=ContractRef("sui.s4b.action_job", "1")), reading_ns)
        payload = {"command": data, "decision_reading": {"run": str(self.h.clock.run),
            "reading_ns": reading_ns, "work": decision.work, "parents": sorted(decision.parents)}}
        attempt = self.append(AttemptStarted(job=job.id, content=Payload.json(payload),
            contract=ContractRef("sui.s4b.action_attempt", "1")), reading_ns)
        return cmd, attempt

    def report(self, attempt, reading_ns, *, outcome="0", source_id=None):
        return self.observe("action_report", attempt, reading_ns, {
            "outcome": outcome, "effect_notice": None, "measurement_reading_ns": reading_ns,
            "completion_reading_ns": reading_ns}, source_id=source_id)

    def observe(self, name, attempt, received_ns, payload, *, source_id=None, recorded_ns=None):
        from sui.contracts import ContractRef
        from sui.records import Observed, Payload
        return self.append(Observed(route="executor", contract=ContractRef("sui.s4b."+name, "1"),
            content=Payload.json(payload), caused_by=attempt.id, received_ns=received_ns,
            source_id=source_id), received_ns if recorded_ns is None else recorded_ns)

    def confirmation(self, kind, command, attempt, reading_ns, *, source_id=None):
        payload = {"command": json.loads(api("dispatch").command_json(command)),
                   "run": str(self.h.clock.run), "reading_ns": reading_ns}
        if kind == "dispatch":
            payload["point"] = {"name": "test.named-send-point", "version": "1"}
        return self.observe(kind, attempt, reading_ns, payload, source_id=source_id)

    def belief(self, *, records=None, now_ns=None):
        from sui.agent import read
        from sui.records import Observed
        records = tuple(self.records if records is None else records)
        now = records[-1].at.mono_ns if now_ns is None else now_ns
        observed = max(r.body.received_ns for r in records if isinstance(r.body, Observed))
        witness = next(r for r in reversed(records)
                       if isinstance(r.body, Observed) and r.body.received_ns == observed)
        ancestors, seen = {}, set()
        for record in records:
            key = str(record.id)
            if key not in seen:
                ancestors[key] = frozenset(seen)
                seen.add(key)
        context = api("action_types").ActionTimeContext(run=self.h.clock.run, now_ns=now,
            observed_ns=observed, check_events=({"fact": str(witness.id)},),
            fact_ancestors=ancestors, clock_source=None)
        return api("action_entry").rebuild_action_belief(self.model, read(self.model, records),
                                                        context=context, budget=budget())

    def root(self, H_ns, *, candidates=("act",)):
        from test_lookahead import _rig
        from sui.preference import current, resolve
        from sui.records import Observed
        now = self.records[-1].at.mono_ns
        observed = max(r.body.received_ns for r in self.records if isinstance(r.body, Observed))
        witness = next(r for r in reversed(self.records)
                       if isinstance(r.body, Observed) and r.body.received_ns == observed)
        r = _rig(model=self.model, history=self.h, H=H_ns, gamma=1., items=())
        view = r.agent.view(now_ns=now, observed_ns=observed,
                            check_events=({"fact": str(witness.id)},))
        cert = api("action_entry").certify_action_scope(view, candidates,
            resolve(current(view.preferences), view), budget=budget())
        assert cert.status == "certified", cert
        return self.belief(), cert

    def node(self, *, controls=(), registered=(), records=None):
        records = tuple(self.records if records is None else records)
        reports = [r for r in records if getattr(getattr(r.body, "contract", None),
                   "name", None) == "sui.s4b.action_report"]
        trigger = targets(reports[-1])[-1] if reports else None
        return api("action_types").ActionNode(belief=self.belief(records=records),
            controls=tuple(controls), targets=tuple(registered), terminal=False, trigger=trigger)


def potential(root, node, cert):
    return api("action_reference").information_potential(root, node, certificate=cert, budget=budget())


def reference(root, node, query, cert):
    handle = api("action_reference").reference_target(root, node, tuple(query),
                                                       certificate=cert, budget=budget())
    return api("action_reference").reference_state_marginal(handle, budget=budget())


def marginal(node, query):
    return api("action_joint").target_marginal(node.belief, tuple(query), budget=budget())
