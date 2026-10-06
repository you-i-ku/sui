"""S4b-2 §6-5: ten built-in pre-change model.8 regression scenarios.

Capture: --source PATH --capture [tests/golden_s4b2.json]
Check:   --source PATH --check tests/golden_s4b2.json
PATH may be an isolated checkout or its src directory. Capture is exclusive;
check never updates the baseline. Temporary SQLite files live outside the repo.
No git, pip, tests helper imports, or current-tree sui fallback are used.

Fixture construction follows tests/s4b_action_cases.py:53, test_s4b_action_stage1b.py:29,
test_s4b_action_stage2.py:131, test_s4b_action_integration.py:245, and the public
record recipe in s4b_action_time_cases.py:42. Only public sui constructors/calls.
Regression outputs are captured, never treated as independent mathematical truth.
Input/source-isolation tests and public rejection tests protect these recipes.
Claude will capture from the isolated 62af688 source.

Rejection audit (2026-10-06, fourth request): existing model.8 assertions cover
continuous scope refusal (test_s4b_action_stage2.py:131-157), malformed JSON and
versions (test_s4b_action_contracts.py:103-150), and exception inheritance/reasons
(same file:39-48,243). No existing input test uniquely asserted outside evaluation:
review_regressions.py:84-93 permits incomplete OR incompatible, and 62af688 returns
incomplete there. Public probes of 62af688 established zero-work repetition below.
Table construction follows test_lookahead.py:375-414: omitted rows are forbidden;
explicit probability zero is unreadable, and finite horizons use outcome_multiset.
The other exact categories below were verified through the isolated public APIs,
not inferred from the exception-name registry or production implementation bodies.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import importlib.metadata
import json
from types import MappingProxyType
from pathlib import Path
import platform
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sui.s4b2.golden.1"
NS = 1_000_000_000


def _plain(value):
    # 読み取り専用の辞書 (mappingproxy) をふつうの辞書として書く (Claude 2026-10-06、採取の時の TypeError)
    if isinstance(value, MappingProxyType):
        return dict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_plain,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=nonfinite)


def source_manifest(source):
    """Hash the whole source tree as opaque bytes; do not inspect algorithms."""
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            files[path.relative_to(source).as_posix()] = digest(path.read_bytes())
    if "sui/model.py" not in files:
        raise ValueError("--source must be a src directory containing sui/model.py")
    return {"files": files, "tree_sha256": digest(canonical(files))}



def select_source(path, *, capture):
    selected=path.resolve()
    source=selected if (selected/"sui/model.py").is_file() else selected/"src"
    if not (source/"sui/model.py").is_file():
        raise ValueError("--source must be a checkout or src containing sui/model.py")
    if capture and source.is_relative_to(ROOT):
        raise ValueError("capture requires an isolated pre-change source outside this workspace")
    return source.resolve()


def assert_source(source):
    for name,module in tuple(sys.modules.items()):
        if name=="sui" or name.startswith("sui."):
            filename=getattr(module,"__file__",None)
            if filename and not Path(filename).resolve().is_relative_to(source):
                raise RuntimeError(f"mixed sui source: {name} from {filename}")


def load_source(source):
    sys.dont_write_bytecode=True
    assert_source(source)  # Reject an already imported foreign sui, not silently replace it.
    sys.path[:]=[str(source)]+[p for p in sys.path if Path(p or ".").resolve() not in
                              {source,ROOT/"src",ROOT}]
    import sui.model
    assert_source(source)
    if Path(sui.model.__file__).resolve().parent.parent!=source:
        raise RuntimeError("requested source was not imported")


def rational(value):
    value=F(value)
    return [value.numerator,value.denominator]


def table(rows):
    return [[rational(x) for x in row] for row in rows]


def delay():
    return {"given":[],"rows":[{"when":[],"points":[[[0,1],[1,1]]]}]}


def model8_declaration():
    """Complete known-law fixture; copied input shape, not a numeric implementation."""
    return {
        "scheme":"sui.model.8","states":["0","1"],"outcomes":["0","1"],"actions":["a"],
        "a":{"a":table([[1,0],[0,1]])},"learnable":[],
        "D":[[1,2],[1,2]],"log_C":[0.0,0.0],"gamma":1.0,
        "work":{"a":{"kind":"known","points":[[NS,[1,1]]]}},
        "completion":{"name":"progress","version":"1","actions":["a"],"states":["0","1"],
            "work_unit":"ns","time_unit":"ns","speed_unit":"ns/ns",
            "candidates":[[[[1,1],[1,1]]]],"weights":[[1,1]],
            "share":"all_actions","max_speed":[1,1]},
        "clock":{"kind":"clock-process","version":"1","share":"run",
            "candidates":[{"weight":[1,1],"kind":"exact","width_ns":None,"phase_ns":None}]},
        "activity":{"modes":["idle"],"initial_given_state":[[[1,1],[1,1]]],
                    "Q_by_mode":{"idle":[[0.0,0.0],[0.0,0.0]]},"calendar":[]},
        "effects":{"a":{"family":{"name":"start-impulse","version":"2"},
            "B":{"kind":"known","values":table([[F(1,2),F(1,2)],[F(1,2),F(1,2)]])},
            "marks":None,"notice":None,"measure":{"at":"report","side":"post"},
            "mode_on_dispatch":{"idle":"idle"},"mode_on_completion":{"idle":"idle"},
            "response_rate_s":None,"progress_start":"dispatch"}},
        "execution":{"family":{"name":"wait-dispatch","version":"1"},"late":"send_when_ready",
            "think":delay(),"receipt":delay(),
            "chi":{"share":"all_actions","candidates":[{"weight":[1,1],"delay":delay()}]},
            "confirmations":{"reservation":None,"receipt":None,"dispatch":None}},
        "choices":{"a":{"action":"a","reservation":{"kind":"at","not_before_ns":0}}},
        "arrivals":{}}


def scenarios():
    """All ten recipes; failure reasons are checked before they can enter a golden."""
    base=model8_declaration()
    def case(name, *, horizon=NS, operation="plan", errors=(), reasons=()):
        return {"name":name,"model":deepcopy(base),"H_ns":horizon,"operation":operation,
                "items":[],"impossible_report":False,"u":0.25,"candidates":["a"],
                "expected_errors":list(errors),"expected_reasons":list(reasons)}
    rows=[case("known_laws"),case("learned_B_Theta"),case("reservation",horizon=2*NS)]
    learned=rows[1]["model"]
    learned["effects"]["a"]["B"]={"kind":"dirichlet","values":table([[1,1],[1,1]])}
    learned["learnable"]=["a"]
    learned["a"]["a"]=table([[1,1],[1,1]])
    rows[2]["model"]["choices"]["a"]["reservation"]={"kind":"offset","offset_ns":NS//4}
    incomplete=case("incomplete",horizon=2*NS,errors=("ActionIncomplete",),
                    reasons=("continuous_branches",))
    incomplete["model"]["effects"]["a"].update(
        family={"name":"response-wait","version":"1"},response_rate_s=[1.0,1.0],progress_start="response")
    rows.append(incomplete)
    unexplained=case("unexplained",errors=("ActionModelFalsified",),
                      reasons=("zero_evidence",))
    unexplained["model"]["D"]=[[1,1],[0,1]]
    unexplained["model"]["effects"]["a"]["B"]["values"]=table([[1,0],[0,1]])
    unexplained["impossible_report"]=True  # known identity in state 0, but observed 1
    rows.append(unexplained)
    # Infinite work with H=None is algorithm_unavailable on 62af688, not outside.
    # Zero work makes certain zero-time repetition outside the finite evaluation.
    outside=case("outside_evaluation",errors=("ActionOutsideEvaluationType",),
                 reasons=("certain_zero_repetition",))
    outside["model"]["work"]["a"]["points"]=[[0,[1,1]]]
    rows.append(outside)
    forbidden=case("all_forbidden",errors=("ActionNoAdmissibleCandidate",),
                   reasons=("all_forbidden",))
    forbidden["model"]["a"]["a"]=table([[1,1],[0,0]])
    forbidden["items"]=[{"kind":"item","rule":{"name":"table","version":"1"},
        "args":{"feature":{"name":"outcome_multiset","version":"1"},
                "probs":[[[["a","1"]],1.0]]}}]
    rows.append(forbidden)
    rows.append(case("noncanonical",operation="load",errors=("ActionInputError",),
                     reasons=("noncanonical",)))
    unknown=case("unknown_version",operation="load",errors=("ActionInputError",),
                 reasons=("unknown_version",))
    unknown["model"]["effects"]["a"]["family"]["version"]="999"
    rows.append(unknown)
    rows.append(case("synchronous_refusal",operation="decide",
        errors=("ActionIncomplete",), reasons=("algorithm_unavailable",)))
    assert len(rows)==len({r["name"] for r in rows})==10
    return tuple(rows)


def ledger_bytes(ledger):
    rows = []
    for entry in ledger.entries():
        salt, payload = ledger.contents.get(entry.seal)
        rows.append({"cid": entry.cid, "header_hex": entry.header.hex(),
                     "salt_hex": salt.hex(), "payload_hex": payload.data.hex(),
                     "payload_media_type": payload.media_type})
    return rows



def build_inputs(recipe, model):
    """Assemble raw records without adopting a belief or evaluating an action."""
    from sui.clock import FakeClock
    from sui.contracts import ContractRef
    from sui.ids import Ref,RefKind,SequentialIds
    from sui.ledger import Ledger,SequentialSalts
    from sui.records import Record,Observed,Preference,Payload,Producer,Role,JobOpened,AttemptStarted
    from sui.s4_contracts import BOOT
    from sui.s4d_contracts import PREFERENCE
    clock=FakeClock(run=Ref(RefKind.RUN,"s4b2-baseline"),wall_ns=100*NS)
    ids=SequentialIds("s4b2-baseline")
    ledger=Ledger(salts=SequentialSalts())
    def append(kind,body,writer=Role.MEMBRANE):
        record=Record(id=ids.new(kind),at=clock.now(),writer=writer,
            producer=Producer(component="test.s4b2.golden",code_version="1"),body=body)
        ledger.append(record,ledger.heads())
        return record
    boot=append(RefKind.OBSERVATION,Observed(route="membrane",content=Payload.json({}),
                contract=BOOT,received_ns=0))
    witness=boot
    if recipe["impossible_report"]:
        # Same public command/record recipe as s4b_action_time_cases.FactWorld.
        from sui.action_types import DecisionReading
        from sui.dispatch import build_command,command_json
        reading=DecisionReading(run=clock.run,reading_ns=0,work="specified-clock-reading",
                                parents=frozenset(ledger.heads()))
        cmd=build_command(model=model,choice="a",decision=reading,causal_stage=0,causal_position=0)
        data=json.loads(command_json(cmd))
        job=append(RefKind.JOB,JobOpened(decision=Ref(RefKind.DECISION,"forced-control"),step=0,
            content=Payload.json({k:data[k] for k in ("action","choice","reservation_rule","dispatch","effect")}),
            contract=ContractRef("sui.s4b.action_job","1")),Role.MODEL)
        attempt=append(RefKind.ATTEMPT,AttemptStarted(job=job.id,contract=ContractRef("sui.s4b.action_attempt","1"),
            content=Payload.json({"command":data,"decision_reading":{"run":str(clock.run),
                "reading_ns":0,"work":reading.work,"parents":sorted(reading.parents)}})))
        clock.advance(NS)
        witness=append(RefKind.OBSERVATION,Observed(route="executor",caused_by=attempt.id,
            contract=ContractRef("sui.s4b.action_report","1"),received_ns=NS,source_id="impossible-1",
            content=Payload.json({"outcome":"1","effect_notice":None,
                                 "measurement_reading_ns":NS,"completion_reading_ns":NS})))
    for content in (*recipe["items"],{"kind":"style","H_ns":recipe["H_ns"],"gamma":1.0}):
        append(RefKind.PREFERENCE,Preference(basis=(),contract=PREFERENCE,
               content=Payload.json(content)),Role.MODEL)
    return ledger,clock,ids,witness


def build_root(recipe, model):
    """One clock/ID source, public records and public Agent.adopt only."""
    from sui.agent import Agent
    ledger,clock,ids,witness=build_inputs(recipe,model)
    agent=Agent(model=model,lineage="s4b2-baseline")
    agent.adopt(ledger,clock=clock,ids=ids)
    view=agent.view(now_ns=clock.mono_ns(),observed_ns=witness.body.received_ns,
                    check_events=({"fact":str(witness.id)},))
    return agent,view,ledger,clock,ids


def rejection(recipe,error):
    if type(error).__name__ not in recipe["expected_errors"]:
        raise AssertionError(f"wrong failure category for {recipe['name']}: {type(error).__name__}: {error}") from error
    reason=getattr(error,"reason",None)
    if reason not in recipe["expected_reasons"]:
        raise AssertionError(f"wrong failure reason for {recipe['name']}: {reason}") from error
    return {"exception":type(error).__name__,"message":str(error),"reason":reason,
            "field":getattr(error,"field",None),"fields":list(getattr(error,"fields",())),
            "gate":getattr(error,"gate",None)}


def capture_case(recipe):
    from sui.agent import Agent,plan,replay_decision
    from sui.ledger import Ledger,SequentialSalts
    from sui.model import model_from_json,model_json,model_ref
    from sui.store import SqliteStore
    raw=canonical(recipe["model"])
    if recipe["name"]=="noncanonical": raw=b" "+raw
    inputs={"recipe":recipe,"model_json":raw.decode()}
    try:
        model=model_from_json(raw)
    except Exception as error:
        if recipe["operation"]!="load": raise
        return {"input":inputs,"input_sha256":digest(canonical(inputs)),"rejection":rejection(recipe,error)}
    if recipe["operation"]=="load":
        raise AssertionError(f"invalid input accepted: {recipe['name']}")
    assert model_json(model)==raw
    # Setup errors cannot masquerade as the plan/decide rejection.
    agent,view,ledger,clock,ids=build_root(recipe,model)
    before=ledger_bytes(ledger)
    inputs.update(ledger=before,now_ns=clock.mono_ns(),observed_ns=view.observed_ns,
                  check_events=list(view.check_events))
    try:
        if recipe["operation"]=="decide":
            agent.decide(recipe["candidates"],u=recipe["u"],clock=clock,ids=ids,ledger=ledger,
                now_mono_ns=clock.mono_ns(),observed_mono_ns=view.observed_ns,check_events=view.check_events)
            raise AssertionError("model.8 synchronous decide unexpectedly succeeded")
        draft=plan(view,recipe["candidates"],u=recipe["u"])
    except Exception as error:
        assert ledger_bytes(ledger)==before, "rejected operation changed ledger"
        return {"input":inputs,"input_sha256":digest(canonical(inputs)),
                "rejection":rejection(recipe,error),"ledger_unchanged":True}
    if recipe["expected_errors"]: raise AssertionError(f"expected rejection absent: {recipe['name']}")
    assert ledger_bytes(ledger)==before
    belief_entry,=ledger.entries_of(view.belief)
    belief_content=ledger.record(belief_entry.cid).body.content.data
    prepared=agent.prepare(draft,clock=clock,ids=ids)
    assert ledger_bytes(ledger)==before
    agent.commit(prepared,ledger=ledger)
    committed=ledger_bytes(ledger)
    agent.commit(prepared,ledger=ledger)
    assert ledger_bytes(ledger)==committed
    decision,=ledger.entries_of(prepared.decided.id)
    assert replay_decision(model=model,ledger=ledger,decision=decision.cid)==draft
    with tempfile.TemporaryDirectory(prefix="sui_s4b2_golden_") as temp:
        path=Path(temp)/"store"
        with SqliteStore.open(path,create=True) as store:
            ref=store.models.put(model)
            for entry in ledger.entries():
                salt,payload=ledger.contents.get(entry.seal)
                store.contents.put(entry.seal,salt,payload)
                store.entries.add(entry.cid,entry.header)
        with SqliteStore.open(path,readonly=True) as store:
            saved=Ledger(salts=SequentialSalts(),entries=store.entries,contents=store.contents)
            recovered=store.models.get(ref)
            assert model_json(recovered)==raw and model_ref(recovered)==ref
            restored=Agent.restore(model=recovered,lineage="restored",ledger=saved,belief=belief_entry.cid)
            entry,=saved.entries_of(restored.view().belief)
            assert saved.record(entry.cid).body.content.data==belief_content
            assert replay_decision(model=recovered,ledger=saved,decision=decision.cid)==draft
            assert ledger_bytes(saved)==committed
            saved.verify()
    return {"input":inputs,"input_sha256":digest(canonical(inputs)),"model_ref":model_ref(model),
            "model_json":raw.decode(),"belief_content":belief_content.decode(),
            "decision_content":draft.content.data.decode(),
            "decision_contract":{"name":draft.contract.name,"version":draft.contract.version},
            "persisted_ledger":committed,"prepare_pure":True,"retry_idempotent":True,
            "roundtrip":True,"restore":True,"replay":True}


def capture_rows():
    return {case["name"]:capture_case(case) for case in scenarios()}


def provenance(source,manifest,recipes):
    files=[Path(__file__),ROOT/"specs/S4b2_変わる速さと届き方を学ぶ.md",ROOT/"pyproject.toml"]
    old=[ROOT/"tests"/("golden_s4b1"+x+".json") for x in "abc"]+[ROOT/"tests/golden_s4b_action.json"]
    return {"source":str(source),"source_manifest":manifest,"python":platform.python_version(),
            "dependencies":{n:importlib.metadata.version(n) for n in ("numpy","scipy","pytest")},
            "script_and_input_files_sha256":{str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in files},
            "existing_golden_sha256":{str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in old},
            "recipes_sha256":digest(canonical(recipes))}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture",nargs="?",const=ROOT/"tests/golden_s4b2.json",type=Path)
    mode.add_argument("--check",type=Path)
    parser.add_argument("--source",type=Path,required=True,help="isolated checkout or src directory")
    args=parser.parse_args(argv)
    if args.capture and args.capture.exists(): parser.error("refusing to overwrite an existing golden")
    source=select_source(args.source,capture=bool(args.capture))
    before=source_manifest(source)
    recipes=scenarios()
    if args.check:
        frozen=read_json(args.check)
        if frozen["schema"]!=SCHEMA: parser.error("unknown baseline schema")
        if frozen["recipes"]!=list(recipes): parser.error("scenario inputs changed")
        if digest(canonical(frozen["pre_implementation"]))!=frozen["rows_sha256"]:
            parser.error("baseline row hash mismatch")
    load_source(source)
    rows=capture_rows()
    assert_source(source)
    if source_manifest(source)!=before: raise AssertionError("source changed during verification")
    if args.check:
        if canonical(rows)!=canonical(frozen["pre_implementation"]):
            raise SystemExit("FAIL: model.8 baseline bytes or rejection changed")
        print(f"PASS: 3 successes, 7 rejections; model.8; source={source}")
    else:
        if canonical(rows)!=canonical(capture_rows()): raise AssertionError("nondeterministic capture")
        assert_source(source)
        if source_manifest(source)!=before: raise AssertionError("source changed during repeat capture")
        payload={"schema":SCHEMA,"provenance":provenance(source,before,recipes),"recipes":recipes,
                 "pre_implementation":rows,"rows_sha256":digest(canonical(rows))}
        data=canonical(payload)+b"\n"
        with args.capture.open("xb") as stream: stream.write(data)
        print(f"CREATED {args.capture}; sha256={digest(data)}; source={source}")


if __name__=="__main__":
    main()
