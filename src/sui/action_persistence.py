"""Model.8 preparation, fact-only restoration and decision replay."""
from .records import Record, Decided, JobOpened, Prediction, Preference, Payload, Role
from .ids import RefKind
from .s4b_action_contracts import BELIEF, DECISION, JOB
from .action_types import ActionInputError, ActionBudget
from .action_model import keys, load_canonical


def intent(model, data):
    keys(data, 'action choice reservation_rule dispatch effect', 'intent')
    declaration = load_canonical(model.declaration)
    choice = declaration['choices'].get(data['choice'])
    if choice is None:
        raise ActionInputError(reason='unknown_candidate', detail='unknown intent choice')
    expected = dict(action=choice['action'], choice=data['choice'],
        reservation_rule=choice['reservation'], dispatch=declaration['execution']['family'],
        effect=declaration['effects'][choice['action']]['family'])
    if data != expected:
        raise ActionInputError(reason='schema', detail='intent differs from the evaluated model choice')
    return expected


def prepare(agent, draft, clock, ids):
    from .agent import Commit
    if draft.contract != DECISION:
        raise ActionInputError(reason='schema', detail='a certified model.8 Draft is required')
    data = draft.content.as_json()
    job_content = intent(agent._model, data['intent'])
    if data['chosen'] != job_content['choice'] or data['root'] != dict(
            belief=str(draft.belief), parents=sorted(draft.parents)):
        raise ActionInputError(reason='schema', detail='Draft root or chosen intent differs')
    decided = Record(id=ids.new(RefKind.DECISION), at=clock.now(), writer=Role.MODEL,
        producer=agent.producer, body=Decided(inputs=(draft.belief, *draft.preference_inputs),
            contract=DECISION, content=draft.content))
    job = Record(id=ids.new(RefKind.JOB), at=clock.now(), writer=Role.MODEL,
        producer=agent.producer, body=JobOpened(decision=decided.id, step=0,
            contract=JOB, content=Payload.json(job_content)))
    return Commit(parents=draft.parents, decided=decided, job=job)


def commit(agent, prepared, ledger):
    from .ledger import UnknownEntry
    if not isinstance(prepared.decided.body, Decided) or prepared.decided.body.contract != DECISION:
        raise ActionInputError(reason='schema', detail='action decision required')
    if not isinstance(prepared.job.body, JobOpened) or prepared.job.body.contract != JOB:
        raise ActionInputError(reason='schema', detail='action job required')
    data = prepared.decided.body.content.as_json()
    expected_intent = intent(agent._model, data['intent'])
    if (prepared.job.body.decision != prepared.decided.id or prepared.job.body.step != 0
            or prepared.job.body.content != Payload.json(expected_intent)
            or data['chosen'] != expected_intent['choice']):
        raise ActionInputError(reason='schema', detail='job differs from the decision intent')
    for cid in prepared.parents:
        try:
            parent = ledger.entry(cid)
        except UnknownEntry as exc:
            raise ValueError('commit: missing parent') from exc
        if not parent.is_event:
            raise ValueError('commit: parents must be events')
    inputs = prepared.decided.body.inputs
    if not inputs:
        raise ValueError('commit: one belief is required')
    if data['root'] != dict(belief=str(inputs[0]), parents=sorted(prepared.parents)):
        raise ActionInputError(reason='schema', detail='decision root differs from frozen parents')
    preferences = [item['id'] for item in data['items']]
    if data['style'] is not None:
        preferences.append(data['style'])
    if list(map(str, inputs[1:])) != preferences:
        raise ValueError('commit: preference inputs differ')
    ancestors = ledger.ancestors(prepared.parents)
    if any(not any(e.cid in ancestors and e.body_type is Preference
                   for e in ledger.entries_of(ref)) for ref in inputs[1:]):
        raise ValueError("commit: preference inputs must belong to the draft's parents")
    if not any(isinstance(ledger.record(e.cid).body, Prediction)
               and ledger.record(e.cid).body.target == 'belief'
               and ledger.record(e.cid).body.contract == BELIEF
               and e.parents == prepared.parents for e in ledger.entries_of(inputs[0])):
        raise ValueError('commit: belief parents differ')
    entry = ledger.append(prepared.decided, prepared.parents)
    ledger.append(prepared.job, {entry.cid})


def restore(cls, *, model, lineage, ledger, belief, component):
    from .agent import read, _preference_view, RebuildMismatch, ModelMismatch
    from .action_entry import derive
    from .action_joint import fact_ancestors
    entry, record = ledger.entry(belief), ledger.record(belief)
    if not isinstance(record.body, Prediction) or record.body.target != 'belief':
        raise ValueError('belief: expected Prediction with target belief')
    if record.body.contract != BELIEF or record.producer.state is None:
        raise ValueError('belief: incompatible contract or missing producer.state')
    data = record.body.content.as_json()
    if data.get('model') != model.ref:
        raise ModelMismatch('belief: model reference differs')
    snapshot = ledger.snapshot(entry.parents)
    reading = read(model, snapshot.records, unread_preferences=snapshot.unread_preferences)
    q, a, content = derive(model, reading)
    differences = tuple(sorted(key for key in set(content) | set(data)
        if key not in content or key not in data or Payload.json(content[key]) != Payload.json(data[key])))
    if differences:
        raise RebuildMismatch(fields=differences)
    subject = cls(model=model, lineage=lineage, component=component)
    subject._frontier, subject._reading = entry.parents, reading
    subject._q, subject._a, subject._lattice = q, a, content
    subject._revision, subject._belief = record.producer.state.revision, record
    subject._preferences = _preference_view(ledger, entry.parents)
    subject._fact_ancestors = fact_ancestors(ledger, entry.parents, reading)
    return subject


def replay(*, model, ledger, decision):
    from .agent import Agent, RebuildMismatch
    from .action_entry import public_evaluate
    from .preference import current, resolve
    entry, record = ledger.entry(decision), ledger.record(decision)
    if not isinstance(record.body, Decided):
        raise ValueError('decision: expected Decided')
    if record.body.contract != DECISION:
        raise RebuildMismatch(fields=('contract',))
    if not record.body.inputs:
        raise RebuildMismatch(fields=('inputs',))
    beliefs = [e for e in ledger.entries_of(record.body.inputs[0])
               if e.parents == entry.parents and e.body_type is Prediction]
    if not beliefs:
        raise RebuildMismatch(fields=('inputs',))
    subject = Agent.restore(model=model, lineage='replay', ledger=ledger,
        belief=min(beliefs, key=lambda e: e.cid).cid)
    data = record.body.content.as_json()
    try:
        time = data['time']
        view = subject.view(now_ns=time['now_ns'], observed_ns=time['observed_ns'],
                            check_events=time['check_events'])
        draft = public_evaluate(view, tuple(data['candidates']), resolve(current(view.preferences), view),
            u=data['u'], budget=ActionBudget(**data['budget']))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise RebuildMismatch(fields=('content',)) from exc
    differences = []
    if (draft.belief, *draft.preference_inputs) != record.body.inputs:
        differences.append('inputs')
    rebuilt = draft.content.as_json()
    if draft.content != record.body.content:
        differences.extend(sorted(key for key in set(data) | set(rebuilt)
            if key not in data or key not in rebuilt or Payload.json(data[key]) != Payload.json(rebuilt[key])))
    if differences:
        raise RebuildMismatch(fields=tuple(differences))
    return draft
