"""FBS0-02: public construction only, paper v0.24.

No model, implementation source, conftest, or other test is read/imported.
Point strings below are *named raw claims*, not evidence of saved records.
Construction success never certifies a claim or a runnable Boot method.
Integration requires real saved Points. Historical gaps below are replaced by
construction/signature tests; they are not claims of implemented computation.
"""

from dataclasses import fields, make_dataclass, replace
from collections.abc import Mapping
from fractions import Fraction
from inspect import get_annotations, signature
from typing import Callable, Literal, get_args, get_origin, get_type_hints
from types import SimpleNamespace

import pytest

from sui import f, fb
from sui import fb_contracts as c
from sui import f_update2 as u2
from sui.clock import FakeClock
from sui.clock_contracts import ClockSource
from sui.contracts import ContractRef
from sui.ids import Ref, RefKind
from sui.ledger import Ledger, PreparedEntry, MemoryContents, SequentialSalts
from sui.store import MemoryEntries
from sui.rate import RateBudget


PAPER = "specs/関所F_Fb_今の約束.md"


class ContractGap(AssertionError):
    """A named missing public connection; never an xfail or a skip."""


# Historical gap descriptions, retained for traceability. Their resolution is
# checked in test_contract_gap_replacement; test_registry registers TEST methods.
GAPS = {
    "CG-ENV": (3181, 3238,
        "Ledger/Clock の構築と C/E の読取・故障注入の公開宣言が今回の読取範囲にない。"
        "Ledger.prepare/write の署名だけでは実置き場を構築できない。",
        "既存 Ledger constructor・Clock・ContentStore/EntryStore の公開宣言だけを追加提供する。"),
    "CG-METHOD": (2121, 2157,
        "Need・測る区間の継続・生成方法を解決する公開の呼出し契約と合法な設定例がない。"
        "MethodCall の名前だけを作っても合法な initial/Qgen/測定を実行できない。",
        "各方法の入力/返値/版/登録先を公開する。Need=1 や全 Received 即時更新を既定にしない。"),
    "CG-REGISTRY": (3232, 3245,
        "fb_registry_v1 の公開配置・factory 署名と段1で必要な方法の供給が未接続。"
        "FRegistry は factory 専用、registry=None は計算を開始できない。",
        "factory の配置と署名を段0で固定し、段1用宣言の供給方法を示す。"),
    "CG-LIVE-OUTPUT": (3040, 3050,
        "FWorkers.run は None、ctx は enter/post のみ、WorkOutputs.outputs は ContractValue(JSON)。"
        "FMathArtifact/VerifiedFiniteUpdate の生きた発行物を対応原報告と一緒に渡す口がない。",
        "保存する response と非保存の issued を分けた返却型または context の引渡し口を宣言する。"),
    "CG-VERIFY-ENTRY": (2959, 3050,
        "対象指定認証の契約名はあるが、公開の callable・TargetVerificationReturn・"
        "VerifiedFiniteUpdate と独立の実行/取得証拠の入力型が提供資料にない。",
        "reader/registry/EW/EA/budget を受ける factory と返答型を段0で宣言する。"),
    "CG-STATUS-VIEW": (1926, 1929,
        "FStatus の各項目に判定像と根拠の対応を付ける欄がない。"
        "表示対象の target だけではどの像で判定したか構築できない。",
        "公開の不変な判定像/根拠参照を各項目または共有の明示対応表に追加する。"),
    "CG-STATUS-PURPOSE": (1925, 1926,
        "PurposeStatus は obligation/purpose/target/handed_to/unmet のみ。"
        "元条件・過程・読み手・固定した対象部分と局所達成を区別して構築できない。",
        "元条件と PurposePart、過程/読み手、局所達成と未達を識別する公開値型を用意する。"),
    "CG-STATUS-RECEIVED": (1920, 1926,
        "ReceiptStatus は envelope/received_ns/slots のみ、SlotStatus.state に受信済みの枝がない。"
        "空 slots が未受付なのかの公開規約もない。Post 後 Accept 前の状態を一意に構築できない。",
        "受信済み枝または空 slots の意味と一意な slot 識別を明文化する。"),
    "CG-RUN-CODEC": (3247, 3247,
        "measurement_run/1 の Run codec が未確定。8枝の Frame を使えることだけでは"
        "独立一覧の Run 行を閉じられない。",
        "codec を決めるか、段1で非圧縮 Frame のみを使う既決の範囲根拠を紙に置く。"),
}

ORIGINAL_GAP_IDS = tuple(GAPS)
# Round 2: old messages remain history, not unconditional failing tests.
GAPS.update({
    "CG-NEED-STRUCTURAL": (2121, 3239,
        "Need の宣言は NEED_INPUT/QUANTITY_VALUE で構築できるが、F-a の能力呼出しの構造検査が"
        "この入出力契約を受け付ける対応は段1。実装の直接呼出しで代用しない。",
        "段1でF-aの構造検査を経たNeed呼出しを接続して閉じる。"
        "SEATS は QuantityValue.contract に置く量の契約。"
        "公開根拠: src/sui/fb_contracts.py:19-23、specs/関所F_今の約束.md:114。"),
    "CG-MATH-ISSUED": (2330, 2338,
        "Ep/Ee の全 bytes と発行物を照合する必要があるが、ctx.post の issued は"
        "VerifiedFiniteUpdate のみ。FMathArtifact を報告と結ぶ公開経路は未宣言。",
        "issued の用途別和型または数学発行物専用の受渡し口を宣言する。"),
    "CG-ISSUED-CONSTRUCTOR": (3040, 3050,
        "VerifiedFiniteUpdate() が通常の公開呼出しで生成できる。factory 専用の宣言と食い違う。",
        "通常の構築を拒み、実際の検査からの発行だけにする。"),
    "CG-LAUNCH-CUT": (316, 318,
        "ClaimStart/Launch/EnterWorker は別の歩で、確かな未入場の起動失敗と入場不明を"
        "別々に試す必要がある (§4 B7:3193、§5:3239/3256)。公開ホストの構築引数は"
        "ledger/clock/workers/registry のみ。workers.run が呼ばれる前の失敗を、公開の口から"
        "選んで起こし、未入場/不明を独立に観測する道が提供資料に無い。",
        "提案: 起動係の公開Protocolとconstructor注入を段0で宣言する。確かな未入場・"
        "入場不明・正常入場の契約と、通知/応答喪失の意味を紙で固定する。未実行。"),
})


# CG-LAUNCH-CUT above is history. Its replacement and the real-host contrast
# scenarios below use the now-declared FLauncher injection, not monkeypatching.
class WitnessLauncher:
    """Test-owned launch cut, not a substitute for the host or ctx.enter.

    A launched callback is deliberately deferred until the test calls it.
    Neither a return value nor the attempt list is worker-entry evidence.
    """
    def __init__(self, outcome):
        self.outcome = outcome
        self.attempts = []

    def launch(self, work_id: str, body: Callable[[], None]) -> fb.LaunchResult:
        self.attempts.append((work_id, body, self.outcome))
        if self.outcome == "raises":
            raise OSError("test launch reply lost; entry is unknown to the host")
        return self.outcome


class DeclaredNeed:
    """TEST declaration: every work in this fixture requires one seat.

    This value is not a product default. Input is fixed work/resource JSON;
    it is deliberately independent of free capacity, phase, and FStatus.
    The keyword call convention is F-a paper V-11 (line 114).
    """
    def __call__(self, *, args, input, context):
        assert args == {}
        assert set(input) == {"work", "scope"}
        return {"contract": {"name": c.SEATS.name, "version": c.SEATS.version}, "value": 1}


class DeclaredWorkerMethod:
    """Declared test capability; actual measure/generator bodies are FWorkers.

    The descriptor is not a supplied candidate list or fabricated measurement.
    """
    def __call__(self, *, args, input, context):
        return {"args": args, "input": input}


def test_registry():
    """Build an actual immutable registry using explicit test declarations."""
    declarations, implementations = [], []
    for name, kind, callback, input_contract, output in (
        ("test.need", "method", DeclaredNeed(), c.NEED_INPUT, c.QUANTITY_VALUE),
        ("test.sampling", "measurement", DeclaredWorkerMethod(), contract("test.fixed_input"), c.SEGMENT_REPORT),
        ("test.generator", "generator", DeclaredWorkerMethod(), contract("test.fixed_input"), c.CANDIDATE_GENERATION),
        ("test.evaluation", "method", DeclaredWorkerMethod(), contract("test.fixed_input"), contract("sui.f.math_artifact")),
        ("test.clock", "clock", DeclaredWorkerMethod(), contract("test.fixed_input"), contract("sui.f.clock_reading")),
        ("test.loss", "measurement", DeclaredWorkerMethod(), contract("test.fixed_input"), c.SEGMENT_REPORT),
    ):
        declaration = f.CapabilityDeclaration(kind=kind, ref=contract(name),
            # F-a V-11: 引数契約は A(n)=sui.f.args.<n>/1 (test.empty_args は構造検査で missing_contract)
            args_contract=ContractRef(name="sui.f.args.empty", version="1"), input_contract=input_contract,
            output_contract=output, dependencies=(), conditions=())
        declarations.append(declaration)
        implementations.append(f.CapabilityImplementation(kind=kind, ref=declaration.ref,
            implementation=callback, identity="sui.fb.tests.stage0/2:" + name))
    return f.make_f_registry(declarations=tuple(declarations), implementations=tuple(implementations))


test_registry.__test__ = False


def real_components():
    contents, entries = MemoryContents(), MemoryEntries()
    return SimpleNamespace(contents=contents, entries=entries,
        ledger=Ledger(salts=SequentialSalts(), contents=contents, entries=entries),
        clock=FakeClock(run=ref(label="fb-stage1"), mono_ns=100), registry=test_registry())


def gap(name):
    first, last, missing, proposal = GAPS[name]
    raise ContractGap(f"{name} | {PAPER}:{first}-{last} | {missing} 案: {proposal}")


def ref(kind=RefKind.RUN, label="stage0"):
    return Ref(kind=kind, value=label)


def point(label):
    # Distinct syntactically valid CID-shaped raw names; not storage fixtures.
    from hashlib import sha256
    return "sha256:" + sha256(label.encode()).hexdigest()


def contract(name):
    return ContractRef(name=name, version="1")


def interval():
    return f.MeasurementInterval(clock=ref(), start_ns=10, end_ns=20,
                                 closure="(start,end]")


def source():
    return ClockSource(run=ref(), provider="test", implementation="manual",
                       python_version="test", resolution_s=Fraction(1, 10**9),
                       monotonic=True, adjustable=False, measurement=None)


def reading():
    return fb.ReadingClock(source=point("source"),
                           reading=f.ClockReading(run=ref(), time_ns=20))


def route():
    return f.RouteConfig(route_epoch="route-A", origin="bootstrap", version="1",
                         sampling_contract=contract("test.sampling"),
                         clock_contract=contract("test.clock"),
                         loss_contract=contract("test.loss"), args={},
                         decision=None, execution=None)


def method(name):
    return fb.MethodCall(contract=contract(name), args={})


def slot(name, kind, value):
    return fb.SlotValue(slot=name, contract=kind, value=value)


def budget():
    from fractions import Fraction
    from sui.rate import RateBudget
    return RateBudget(Fraction(1, 1000), 1000, 1000, 10)


def boot(initial=False):
    """Structure example, with explicitly unresolved test methods (CG-METHOD)."""
    def allocation(name):
        return slot(name, c.ALLOCATION, fb.Allocation(scope_slot="scope",
                    amount=fb.QuantityValue(contract=c.SEATS, value=1)))

    initial_value = None
    if initial:
        delta_args = {
            "process_slot": "thinking", "reader_slot": "reader",
            "purpose": "belief_update",
            **{name: {"contract": {"name": "test." + name, "version": "1"}, "args": {}}
               for name in ("condition", "trigger_slots", "inputs", "stage_slots", "grouping", "request")},
        }
        initial_value = slot("initial", c.INITIAL_PROCESS, fb.InitialProcess(
            process_slot="thinking", reader_slot="reader", model=point("model"),
            generator=method("test.generator"), method=method("test.evaluation"),
            draw=method("test.draw"), prepare_budget=budget(), evaluate_budget=budget(),
            allocation=allocation("thinking-allocation"),
            derivation=fb.SlottedMethod(slot="delta", method=fb.MethodCall(
                contract=c.RECEIVED_UPDATE, args=delta_args))))
    return fb.Boot(declaration=fb.BootDeclaration(
        capacity=fb.QuantityValue(contract=c.SEATS, value=2),
        scope=slot("scope", c.RESOURCE_SCOPE, fb.ResourceScope(
            quantity_contract=c.SEATS, need=method("test.need"))),
        routes=(slot("route", c.BOOTSTRAP_ROUTE, fb.BootstrapRoute(
            config=route(), process_slot="sensing", allocation=allocation("sensing-allocation"),
            reading_contract=c.FINITE_SEGMENT_PROJECTION)),),
        initial=initial_value,
        environment=slot("environment", c.ENVIRONMENT,
                         fb.Environment(data={"fixture": "shape-only"}))))


def segment_items():
    evidence = (ref(RefKind.OBSERVATION, "raw"),)
    common = dict(work="measure-A", reading=reading(), reason="reported", evidence=evidence)
    return {
        "started": fb.SegmentBoundary(kind="started", **common),
        "ended": fb.SegmentBoundary(kind="ended", **common),
        "route_applied": fb.RouteAppliedItem(config=point("route"), reading=reading(),
                                              reason="applied", evidence=evidence),
        "frame": f.MeasurementFrame(route_epoch="route-A", sample_seq=0,
            measurement_id=f.MeasurementId(origin=ref(), route_epoch="route-A",
                                            sample_seq=0, component="sensor"),
            measurement_interval=interval(), actual_time=f.ClockReading(run=ref(), time_ns=20),
            value=0, quality=f.ContractValue(contract=contract("sui.f.measured_quality"), value="measured"),
            gap=None, source_cursor=f.ContractValue(contract=contract("sui.f.sequence_cursor"), value=0)),
        "gap": f.Gap(route_epoch="route-A", sequence_range=(0, 1), interval=interval(),
                     reason="lost", evidence=evidence),
        "measurement_unavailable": f.MeasurementUnavailable(route_epoch="route-A",
            requested_interval=interval(), reason="unavailable", evidence=evidence),
        "claim": f.CoverageClaim(route_epoch="route-A", interval=interval(), kind="no_arrival",
                                 contract=c.NO_ARRIVAL, evidence=evidence),
        "coverage_unproved": f.CoverageUnproved(route_epoch="route-A", interval=interval(),
                                                missing_contracts=(c.BOOTSTRAP_GENERATION,), evidence=evidence),
    }


def work_outcomes():
    return {
        "outputs": fb.WorkOutputs(outputs=f.ContractValue(contract=c.CANDIDATE_GENERATION,
                                value={"kind": "no_candidates", "value": {}})),
        "failure": fb.WorkFailure(failure=fb.FailureInfo(failure_kind="test_failure", content={},
                                                        readings=(reading(),), basis=())),
        "unknown": fb.WorkUnknown(unknown=fb.UnknownInfo(reason="lost response", basis=())),
    }


def draw_outcomes():
    return {
        "value": fb.DrawValue(value="1/2"),
        "failure": fb.DrawFailure(failure=fb.FailureInfo(failure_kind="rejected", content={},
                                                        readings=(), basis=())),
        "unknown": fb.DrawUnknown(unknown=fb.UnknownInfo(reason="lost response", basis=())),
    }


def view():
    return fb.FixedView(boundary=frozenset({point("boundary")}),
                        reader_view_key="fixture-view", registry_key="fixture-registry")


def args_by_stage():
    return {
        "measure_segment": fb.SegmentArgs(route=point("route"), requested=interval(), start_reason="bootstrap"),
        "candidate_generation": fb.CandidateArgs(model=point("model"), generator_args={}, basis=()),
        "belief_update": fb.UpdateArgs(model=point("model"), prior=None,
            observations=(point("segment-report"),)),
        "evaluation_prepare": fb.EvaluationPrepareArgs(input=f.FFactsRequest(
            fixed_parents=(point("boundary"),), model=point("model"), candidates=point("CG"),
            preferences=(), scope=f.EvaluationScope(name="one_step", version="1", H_ns=None, source=None),
            context=point("context"), method=contract("test.evaluation")), compiler=contract("test.compiler"),
            budget=budget()),
        "selection_draw": fb.DrawArgs(prepared=point("PR"), stream_id="stream-A", request=f.DrawRequest(
            purpose="selection", context_key="problem-A", ordinal=0,
            law=contract("sui.f.uniform_unit"), args={})),
        "evaluation": fb.EvaluationArgs(evaluation_request=point("EQ"), prepared=point("PR"), draw=point("DF"),
                                        budget=budget()),
    }


def desc(stage):
    boot_ref = fb.BootSlot(declaration=point("boot"), slot="sensing" if stage == "measure_segment" else "thinking")
    return fb.Desc(work_id="work-" + stage, process=boot_ref,
        trigger=frozenset({fb.Trigger(point=point("trigger"), slot="initial")}),
        purpose=stage, stage_slot=stage, reader=None if stage == "measure_segment" else point("reader"),
        method=contract("test." + stage), output_contract=contract("test.output." + stage),
        args=args_by_stage()[stage], input_points=frozenset({point("input")}),
        numerical_view=None if stage == "measure_segment" else view(),
        allocation=fb.BootSlot(declaration=point("boot"), slot="allocation"), permissions=frozenset({boot_ref}))


def status_examples():
    unsaved = fb.Unsaved(plan="accepted-plan")
    evidence = fb.StatusBasis(view=view(), basis=(point("basis"), unsaved))
    return dict(
        receipts=(fb.ReceiptStatus(envelope=7, received_ns=20, state="accepted", slots=(fb.SlotStatus(
            contract=c.RECEIVED, state="accepted", target=unsaved, evidence=evidence),)),),
        works=(fb.WorkStatus(work_id="measure-A", request=point("request"), purpose="measure_segment",
            phase="running", startable=False, blocked_by=(), knowledge="unknown",
            stop_confirmed=False, held=fb.QuantityValue(contract=c.SEATS, value=1), evidence=evidence),),
        readings=(fb.ReadingStatus(target=point("R"), reader=point("reader"), reached="generated",
            response="insufficient", adopted=None, stale=None, selected=None, evidence=evidence),),
        pending=(fb.PendingStatus(kind="missing_contract", target=unsaved, contract=contract("test.need"),
                                  reason="method not supplied", evidence=evidence),),
        segments=(fb.SegmentStatus(segment=point("request"), cells=(fb.CellStatus(
            interval=interval(), reports=(), certified=False, evidence=evidence),), ended=True, evidence=evidence),),
        purposes=(fb.PurposeStatus(obligation=unsaved, o_id="O-14", condition="stop", role="measurement",
            process=fb.BootSlot(declaration=point("boot"), slot="sensing"), reader=None,
            target=point("request"), part=interval(), handled=True, handed_to=unsaved,
            unmet=True, evidence=evidence),),
    )


@pytest.mark.parametrize("initial", [False, True], ids=["none", "present"])
def test_boot_nested_shape(initial):
    event = boot(initial)
    assert (event.declaration.initial is not None) == initial
    assert event.declaration.routes[0].value.config.origin == "bootstrap"
    assert event.declaration.capacity.value == 2


@pytest.mark.parametrize("branch", tuple(segment_items()))
def test_segment_eight_branches(branch):
    item = segment_items()[branch]
    event = fb.SegmentReport(segment=point("request"), item_slot="item-A", item=item)
    assert event.item == item
    assert isinstance(item, get_args(fb.SegmentItem))


@pytest.mark.parametrize("branch", ("outputs", "failure", "unknown"))
def test_work_outcome_branches(branch):
    event = fb.WorkFinished(work="work-A", started=reading(), finished=reading(), outcome=work_outcomes()[branch])
    assert isinstance(event.outcome, get_args(fb.WorkOutcome))


@pytest.mark.parametrize("branch", ("value", "failure", "unknown"))
def test_draw_outcome_branches(branch):
    event = fb.DrawReturned(work="draw-A", outcome=draw_outcomes()[branch])
    assert isinstance(event.outcome, get_args(fb.DrawOutcome))


@pytest.mark.parametrize("event", [boot(), fb.ClockDeclared(declaration=source()),
    fb.Received(route_epoch="unknown", media_type="application/octet-stream", data=b"\x00\xff", claims={}),
    fb.SegmentReport(segment=point("unknown"), item_slot="x", item=segment_items()["gap"]),
    fb.WorkFinished(work="unknown", started=reading(), finished=reading(), outcome=work_outcomes()["unknown"]),
    fb.DrawReturned(work="unknown", outcome=draw_outcomes()["unknown"])], ids=lambda e: type(e).__name__)
def test_six_events_and_envelope(event):
    envelope = fb.Envelope(number=7, event=event, received_ns=20)
    assert envelope.event is event
    assert isinstance(event, get_args(fb.FEvent))


@pytest.mark.parametrize("stage", tuple(args_by_stage()))
def test_six_work_uses(stage):  # v0.25 §6-6: belief_update 1 つ (前は 8 用途)
    assert set(get_args(fb.Stage)) == set(args_by_stage())
    assert set(get_args(fb.FWork)) == {fb.MeasureSegment, fb.Compute, fb.Draw}
    d = desc(stage)
    cls = fb.MeasureSegment if stage == "measure_segment" else fb.Draw if stage == "selection_draw" else fb.Compute
    work = cls(request=point("request-" + stage), desc=d)
    assert work.desc.purpose == stage
    assert len(fields(fb.Desc)) == 13
    assert isinstance(d.args, get_args(fb.WorkArgs))


@pytest.mark.parametrize("meaning", tuple(status_examples()))
def test_six_status_shape_representatives(meaning):
    result = fb.FStatus(**status_examples())
    assert getattr(result, meaning)
    assert result.works[0].knowledge == "unknown"
    assert not result.works[0].stop_confirmed
    assert result.segments[0].ended  # reported end and actual stop are distinct fields


def test_public_entry_signatures():
    assert set(signature(fb.FThreadHost).parameters) == {"ledger", "clock", "workers", "registry", "launcher"}
    assert signature(fb.FThreadHost).parameters["launcher"].default is None
    assert set(get_args(get_type_hints(fb.FThreadHost.__init__)["launcher"])) == {fb.FLauncher, type(None)}
    assert set(signature(fb.FLauncher.launch).parameters) == {"self", "work_id", "body"}
    assert get_type_hints(fb.FLauncher.launch)["work_id"] is str
    body_type = get_type_hints(fb.FLauncher.launch)["body"]
    assert get_origin(body_type) is get_origin(Callable[[], None])
    body_args, body_return = get_args(body_type)
    assert body_args == []
    assert body_return in (None, type(None))  # equivalent annotation spellings
    assert get_type_hints(fb.FLauncher.launch)["return"] == fb.LaunchResult
    assert set(get_args(fb.LaunchResult)) == {"launched", "not_started", "unknown"}
    assert set(signature(fb.FThreadHost.run_until).parameters) == {"self", "done", "timeout"}
    assert set(signature(fb.FThreadHost.rebuild_window).parameters) == {"self"}
    assert set(signature(fb.FThreadHost.post).parameters) == {"self", "event"}
    assert set(signature(fb.FWorkers.run).parameters) == {"self", "work", "ctx"}
    assert set(signature(fb.FWorkContext.enter).parameters) == {"self"}
    assert set(signature(fb.FWorkContext.post).parameters) == {"self", "event", "issued"}
    assert set(signature(fb.FWorkContext.evidence).parameters) == {"self"}
    assert set(signature(fb.FWorkContext.read).parameters) == {"self", "point"}
    assert get_type_hints(fb.FWorkContext.read) == {"point": str, "return": bytes}
    assert set(signature(fb.FWorkContext.monitored).parameters) == {"self", "interval"}
    assert get_type_hints(fb.FWorkContext.monitored) == {"interval": f.MeasurementInterval, "return": type(None)}
    # v0.26 §6-9 H5: 対象を限った読み取り
    assert set(signature(fb.FWorkContext.reader).parameters) == {"self"}
    assert get_type_hints(fb.FWorkContext.reader) == {"return": f.FReader | None}
    assert set(signature(fb.FWorkContext.prepared).parameters) == {"self"}
    assert get_type_hints(fb.FWorkContext.prepared) == {"return": f.FMathArtifact | None}
    assert fb.LaunchResult == u2.LaunchResult
    assert signature(fb.FThreadHost).parameters["registry"].default is signature(fb.FThreadHost).empty
    assert set(signature(fb.FWindow.accept).parameters) == {"self", "envelope"}
    for name in ("settle", "status", "drain"):
        assert set(signature(getattr(fb.FWindow, name)).parameters) == {"self"}
    assert set(signature(Ledger.prepare).parameters) == {"self", "record", "parents"}
    assert set(signature(Ledger.write).parameters) == {"self", "prepared"}
    assert tuple(x.name for x in fields(PreparedEntry)) == ("record", "parents", "salt", "header", "cid")


def issued_kwargs():
    """IssuedUpdate の全欄 (v0.25 §6-3)。説明値から発行物を作れないことの確かめにだけ使う。"""
    fixed = u2.FixedViewValue(boundary=frozenset({point("boundary")}), reader_view_key="view", registry_key="registry")
    return dict(request=point("Q"), result={"joint": ["8/9", "1/9"], "evidence_mass": "9/128"},
                application_digest=point("application"), numerical_view=fixed, registry_key="registry")


def fixture_budget():
    return RateBudget(tolerance=Fraction(1, 100), max_cells=10, max_terms=10, max_refinements=10)


@pytest.mark.parametrize("name", ORIGINAL_GAP_IDS)
def test_contract_gap_replacement(name):
    if name == "CG-ENV":
        x = real_components()
        assert x.entries.load() == () and x.contents.seals() == frozenset()
        assert x.clock.mono_ns() == 100
        assert x.ledger.entries() == ()
    elif name == "CG-METHOD":
        registry = test_registry()
        need = next(d for d in registry.declarations if d.ref == contract("test.need"))
        assert (c.NEED_INPUT.name, c.NEED_INPUT.version) == ("sui.fb.need_input", "1")
        assert (c.SEATS.name, c.SEATS.version) == ("sui.fb.seats", "1")
        assert (c.QUANTITY_VALUE.name, c.QUANTITY_VALUE.version) == ("sui.fb.quantity_value", "1")
        assert c.QUANTITY_VALUE != c.SEATS
        assert (need.kind, need.input_contract, need.output_contract) == ("method", c.NEED_INPUT, c.QUANTITY_VALUE)
    elif name == "CG-REGISTRY":
        assert test_registry().declarations
        assert not signature(u2.fb_registry_v1).parameters
    elif name == "CG-LIVE-OUTPUT":
        hints = get_type_hints(fb.FWorkContext.post)
        assert u2.IssuedUpdate in get_args(hints["issued"])
        assert get_type_hints(fb.FWorkContext.evidence)["return"] is u2.TargetEvidence
        assert set(get_args(hints["issued"])) == {f.FMathArtifact, u2.IssuedUpdate, type(None)}
        assert signature(fb.FWorkContext.post).parameters["issued"].default is None
    elif name == "CG-VERIFY-ENTRY":
        # v0.25 §6-3: 対象指定認証をやめ、入口 U が一次事実から計算して発行する。joint を受ける引数は無い
        issue = u2.RejectedIssue(code="shape", fields=("/request",), evidence=frozenset(), message="bad shape")
        response = u2.Rejected(request=point("Q"), issues=(issue,))
        assert response.request == point("Q") and isinstance(response, get_args(u2.UpdateReturn))
        assert set(signature(u2.compute_finite_update).parameters) == {"request", "reader", "registry", "evidence", "budget"}
    elif name == "CG-STATUS-VIEW":
        status = fb.FStatus(**status_examples())
        for item in (status.receipts[0].slots[0], status.works[0], status.readings[0], status.pending[0],
                     status.segments[0], status.segments[0].cells[0], status.purposes[0]):
            assert item.evidence.view == view()
            assert isinstance(item.evidence.basis[1], fb.Unsaved)
    elif name == "CG-STATUS-PURPOSE":
        item = status_examples()["purposes"][0]
        assert item.handled and item.unmet and item.condition == "stop"
        assert item.part == interval() and item.process.slot == "sensing"
    elif name == "CG-STATUS-RECEIVED":
        received = fb.ReceiptStatus(envelope=7, received_ns=20, state="received", slots=())
        accepted = status_examples()["receipts"][0]
        assert received.state != accepted.state and received.slots == () and accepted.slots
    elif name == "CG-RUN-CODEC":
        assert f.Run not in get_args(fb.SegmentItem)
        assert "frame" in segment_items()  # paper:3247 explicitly excludes Run


@pytest.mark.parametrize("kind", ("rejected", "insufficient"))
def test_update_return_shapes(kind):
    """U の確定の返答 (v0.25 §6-2)。成功の枝は発行物だけで、手で作れない (下の試験)。"""
    if kind == "rejected":
        response = u2.Rejected(request=point("Q"), issues=(u2.RejectedIssue(
            code="shape", fields=("/request",), evidence=frozenset(), message="shape"),))
    else:
        need = u2.VerificationNeed(kind="budget", value={"phase": "computation"})
        response = u2.Insufficient(request=point("Q"), issues=(u2.InsufficientIssue(
            code="budget_exhausted", fields=("/budget",), missing=(need,), evidence=frozenset(), message="budget"),))
    assert isinstance(response, get_args(u2.UpdateReturn)) and not isinstance(response, u2.IssuedUpdate)


@pytest.mark.parametrize("kwargs", ({}, issued_kwargs()), ids=("empty", "all_fields"))
def test_issued_update_cannot_be_hand_constructed(kwargs):
    with pytest.raises(TypeError):
        u2.IssuedUpdate(**kwargs)


@pytest.mark.parametrize("outcome", ("not_started", "unknown", "raises", "launched"))
def test_launch_failure_cut_is_publicly_controllable(outcome):
    """CG-LAUNCH-CUT replacement; B:316-318, no guessed thread patching.

    This proves only the test-side cut and its public signature, not host
    behavior. The real host/worker contrast cases are in test_fb_stage1.py.
    """
    launcher = WitnessLauncher(outcome)
    entered = []
    body = lambda: entered.append("actual callback")
    if outcome == "raises":
        with pytest.raises(OSError):
            launcher.launch("work-fixture", body)
    else:
        assert launcher.launch("work-fixture", body) == outcome
    assert launcher.attempts == [("work-fixture", body, outcome)]
    assert entered == []  # even launched is not an EnterWorker observation
    if outcome == "launched":
        launcher.attempts[0][1]()
        assert entered == ["actual callback"]


# Independent field/type expectations: paper B §2-5-3/5/6/7/16/19-9,
# §2-4-11 M1; the authorized public Python declarations fix DTO spellings,
# tuple/frozenset representation and the nonserialized observation types.
# This table is handwritten, never generated from production annotations.
FB_FIELD_SPEC = {
    # B:468/3231 retains the OLD envelope (its public event annotation is object).
    # The six accepted event branches are fixed separately by FEvent below.
    "Envelope": "number:int;event:object;received_ns:int",
    "MethodCall": "contract:ContractRef;args:ImmutableJSON",
    "QuantityValue": "contract:ContractRef;value:int",
    "SlotValue": "slot:str;contract:ContractRef;value:object",
    "SlottedMethod": "slot:str;method:MethodCall",
    "BootSlot": "declaration:Point;slot:str",
    "FixedView": "boundary:frozenset[Point];reader_view_key:str;registry_key:str|None",
    "ResourceScope": "quantity_contract:ContractRef;need:MethodCall",
    "Allocation": "scope_slot:str;amount:QuantityValue",
    "BootstrapRoute": "config:RouteConfig;process_slot:str;allocation:SlotValue;reading_contract:ContractRef|None",
    "InitialProcess": "process_slot:str;reader_slot:str;model:Point;generator:MethodCall;method:MethodCall;draw:MethodCall;prepare_budget:RateBudget;evaluate_budget:RateBudget;allocation:SlotValue;derivation:SlottedMethod",  # v0.26 §6-9 H3・H4
    "Environment": "data:ImmutableJSON",
    "BootDeclaration": "capacity:QuantityValue;scope:SlotValue;routes:tuple[SlotValue,...];initial:SlotValue|None;environment:SlotValue",
    "ReadingClock": "source:Point;reading:ClockReading",
    "GenerationPair": "started:ReadingEvidence;finished:ReadingEvidence",
    "FailureInfo": "failure_kind:str;content:ImmutableJSON;readings:tuple[ReadingEvidence,...];basis:tuple[Ref,...]",
    "UnknownInfo": "reason:str;basis:tuple[Ref,...]",
    "WorkOutputs": "outputs:ContractValue",
    "WorkFailure": "failure:FailureInfo",
    "WorkUnknown": "unknown:UnknownInfo",
    "DrawValue": "value:ImmutableJSON",
    "DrawFailure": "failure:FailureInfo",
    "DrawUnknown": "unknown:UnknownInfo",
    "SegmentBoundary": "kind:Literal['started','ended'];work:str;reading:ReadingEvidence;reason:str;evidence:tuple[Ref,...]",
    "RouteAppliedItem": "config:Point;reading:ReadingEvidence;reason:str;evidence:tuple[Ref,...]",
    "Boot": "declaration:BootDeclaration",
    "ClockDeclared": "declaration:ClockSource",
    "Received": "route_epoch:str;media_type:str;data:bytes;claims:ImmutableJSON",
    "SegmentReport": "segment:Point;item_slot:str;item:SegmentItem",
    "WorkFinished": "work:str;started:ReadingEvidence;finished:ReadingEvidence;outcome:WorkOutcome",
    "DrawReturned": "work:str;outcome:DrawOutcome",
    "Trigger": "point:Point;slot:str",
    "Ongoing": "clock:Ref",
    "SegmentArgs": "route:Point;requested:MeasurementInterval|Ongoing;start_reason:str",
    "CandidateArgs": "model:Point;generator_args:ImmutableJSON;basis:tuple[Point,...]",
    "UpdateArgs": "model:Point;prior:Point|None;observations:tuple[Point,...]",
    "EvaluationPrepareArgs": "input:FFactsRequest;compiler:ContractRef;budget:RateBudget",  # v0.26 §6-9 H3
    "DrawArgs": "prepared:Point;stream_id:str;request:DrawRequest",
    "EvaluationArgs": "evaluation_request:Point;prepared:Point;draw:Point;budget:RateBudget",  # v0.26 §6-9 H3
    "Desc": "work_id:str;process:BootSlot;trigger:frozenset[Trigger];purpose:Stage;stage_slot:str;reader:Point|None;method:ContractRef;output_contract:ContractRef;args:WorkArgs;input_points:frozenset[Point];numerical_view:FixedView|None;allocation:BootSlot;permissions:frozenset[BootSlot]",
    "MeasureSegment": "request:Point;desc:Desc",
    "Compute": "request:Point;desc:Desc",
    "Draw": "request:Point;desc:Desc",
    "Unsaved": "plan:str",
    "StatusBasis": "view:FixedView|None;basis:tuple[Held,...]",
    "SlotStatus": "contract:ContractRef;state:Literal['accepted','awaiting_confirmation','saved','unconfirmed'];target:Held;evidence:StatusBasis",
    "ReceiptStatus": "envelope:int;received_ns:int;state:Literal['received','accepted'];slots:tuple[SlotStatus,...]",
    "WorkStatus": "work_id:str;request:Held;purpose:Stage;phase:Literal['pending','starting','running','stopped'];startable:bool;blocked_by:tuple[Held,...];knowledge:Literal['none','success','failure','unknown'];stop_confirmed:bool;held:QuantityValue|None;evidence:StatusBasis",
    "ReadingStatus": "target:Held;reader:Point|None;reached:Literal['none','generated','acquired','verified','adopted'];response:Literal['none','rejected','insufficient','no_decision','no_candidates','failure','unknown'];adopted:Point|None;stale:Point|None;selected:Point|None;evidence:StatusBasis",
    "PendingStatus": "kind:Literal['unchecked','awaiting_evidence','missing_contract','conflict'];target:Held|None;contract:ContractRef|None;reason:str;evidence:StatusBasis",
    "CellStatus": "interval:MeasurementInterval;reports:tuple[Literal['frame','gap','measurement_unavailable','claim','coverage_unproved'],...];certified:bool;evidence:StatusBasis",
    "SegmentStatus": "segment:Held;cells:tuple[CellStatus,...];ended:bool;evidence:StatusBasis",
    "PurposeStatus": "obligation:Held;o_id:str;condition:Literal['issue','save','run','handle','stop'];role:str;process:BootSlot|None;reader:Point|None;target:Held|None;part:MeasurementInterval|None;handled:bool;handed_to:Held|None;unmet:bool;evidence:StatusBasis",
    "FStatus": "receipts:tuple[ReceiptStatus,...];works:tuple[WorkStatus,...];readings:tuple[ReadingStatus,...];pending:tuple[PendingStatus,...];segments:tuple[SegmentStatus,...];purposes:tuple[PurposeStatus,...]",
}

FA_FIELD_SPEC = {
    "CapabilityDeclaration": "kind:CapabilityKind;ref:ContractRef;args_contract:ContractRef;input_contract:ContractRef;output_contract:ContractRef;dependencies:tuple[ContractRef,...];conditions:tuple[ContractValue,...]",
    "CapabilityImplementation": "kind:CapabilityKind;ref:ContractRef;implementation:CapabilityCallable;identity:str",
    "CapabilityContext": "registry:FRegistry|None;resources:object|None;model_ref:str|None;budget:RateBudget|None;numeric_work:object|None;cached_quantities:object|None;numeric_input:object|None;certified_input:object|None",
    "FRegistry": "declarations:tuple[CapabilityDeclaration,...];implementations:tuple[CapabilityImplementation,...]",
    "Unavailable": "reason:str;basis:tuple[Ref,...]",
    "ContractValue": "contract:ContractRef;value:ImmutableJSON",
    "ClockReading": "run:Ref;time_ns:int",
    "MeasurementInterval": "clock:Ref;start_ns:int;end_ns:int;closure:Literal['[start,end)','(start,end]','[start,end]','(start,end)']",
    "MeasurementId": "origin:Ref;route_epoch:str;sample_seq:int;component:str",
    "MeasurementFrame": "route_epoch:str;sample_seq:int;measurement_id:MeasurementId;measurement_interval:MeasurementInterval;actual_time:ClockReading|Unavailable;value:ImmutableJSON|Unavailable;quality:ContractValue;gap:Gap|None;source_cursor:ContractValue",
    "Gap": "route_epoch:str;sequence_range:tuple[int,int];interval:MeasurementInterval;reason:str;evidence:tuple[Ref,...]",
    "MeasurementUnavailable": "route_epoch:str;requested_interval:MeasurementInterval;reason:str;evidence:tuple[Ref,...]",
    "CoverageClaim": "route_epoch:str;interval:MeasurementInterval;kind:str;contract:ContractRef;evidence:tuple[Ref,...]",
    "CoverageUnproved": "route_epoch:str;interval:MeasurementInterval;missing_contracts:tuple[ContractRef,...];evidence:tuple[Ref,...]",
    "RouteConfig": "route_epoch:str;origin:Literal['bootstrap','selected'];version:str;sampling_contract:ContractRef;clock_contract:ContractRef;loss_contract:ContractRef;args:ImmutableJSON;decision:Ref|None;execution:Ref|None",
}

UPDATE_FIELD_SPEC = {
    "FixedViewValue": "boundary:frozenset[Point];reader_view_key:str;registry_key:str|None",
    "VerificationNeed": "kind:Literal['capability','evidence','budget'];value:ImmutableJSON",
    "RejectedIssue": "code:Literal['schema','shape','noncanonical','rational','unit','unknown_version','normalization','unresolved_reference','reference_kind','observation_binding_mismatch','measurement_conflict','clock_unaligned','missing_contract','model_falsified','outside_evaluation_type','result_mismatch'];fields:tuple[str,...];evidence:frozenset[Point];message:str",
    "InsufficientIssue": "code:Literal['algorithm_unavailable','budget_exhausted','prerequisite_unavailable','clock_unaligned'];fields:tuple[str,...];missing:tuple[VerificationNeed,...];evidence:frozenset[Point];message:str",
    "IssuedUpdate": "request:Point;result:ImmutableJSON;application_digest:str;numerical_view:FixedViewValue;registry_key:str",
    "Rejected": "request:Point;issues:tuple[RejectedIssue,...]",
    "Insufficient": "request:Point;issues:tuple[InsufficientIssue,...]",
    "ReportObservation": "envelope:int;received_ns:int;point:Point|None",
    "ExecutionObservation": "work_id:str;launches:tuple[LaunchResult,...];entered:int;stopped:bool;reports:tuple[ReportObservation,...]",
    "UseObservation": "work_id:str;point:Point;used_ns:int",
    "IntervalObservation": "work_id:str;interval:MeasurementInterval",
    "AcquisitionObservation": "origin:Point;contents:frozenset[Point];acquired_ns:int",
    "TargetEvidence": "executions:tuple[ExecutionObservation,...];uses:tuple[UseObservation,...];intervals:tuple[IntervalObservation,...];acquisitions:tuple[AcquisitionObservation,...]",
}

FB_ALIAS_SPEC = {
    "ReadingEvidence": "ReadingClock|Unavailable",
    "WorkOutcome": "WorkOutputs|WorkFailure|WorkUnknown",
    "DrawOutcome": "DrawValue|DrawFailure|DrawUnknown",
    # Two literal boundary kinds plus these six types give eight wire branches.
    "SegmentItem": "SegmentBoundary|RouteAppliedItem|MeasurementFrame|Gap|MeasurementUnavailable|CoverageClaim|CoverageUnproved",
    "FEvent": "Boot|ClockDeclared|Received|SegmentReport|WorkFinished|DrawReturned",
    "Stage": "Literal['measure_segment','candidate_generation','belief_update','evaluation_prepare','selection_draw','evaluation']",
    "WorkArgs": "SegmentArgs|CandidateArgs|UpdateArgs|EvaluationPrepareArgs|DrawArgs|EvaluationArgs",
    "FWork": "MeasureSegment|Compute|Draw",
    "Held": "Point|Unsaved",
    "LaunchResult": "Literal['launched','not_started','unknown']",
}
UPDATE_ALIAS_SPEC = {
    "LaunchResult": "Literal['launched','not_started','unknown']",
    "UpdateReturn": "IssuedUpdate|Rejected|Insufficient",
}
FA_ALIAS_SPEC = {
    # Public recursive JSON definition (F-a V-01, public declarations L46).
    "ImmutableJSON": "str|int|float|bool|None|tuple['ImmutableJSON',...]|Mapping[str,'ImmutableJSON']",
    "Point": "str",
    "CapabilityKind": "Literal['action','predicate','kernel','policy','execution','proof','method','arithmetic','choice','measurement','projection','generation','clock','quality','cursor','generator']",
}


def test_public_export_names_are_exact():
    assert set(fb.__all__) == set(FB_FIELD_SPEC) | set(FB_ALIAS_SPEC) | {
        "FbInputError", "FbHostFault", "FWorkContext", "FWorkers", "FLauncher", "FWindow", "FThreadHost"}
    assert set(u2.__all__) == set(UPDATE_FIELD_SPEC) | set(UPDATE_ALIAS_SPEC) | {
        "fb_registry_v1", "compute_finite_update"}


def declaration_names(surface=fb):
    """Resolve public type identities only; expectations remain the tables above."""
    names = dict(Point=str, Ref=Ref, ContractRef=ContractRef, ImmutableJSON=f.ImmutableJSON,
                 ProofRef=f.ProofRef, FFactsRequest=f.FFactsRequest, DrawRequest=f.DrawRequest,
                 RateBudget=RateBudget, ClockSource=ClockSource, Literal=Literal,
                 CapabilityCallable=f.CapabilityCallable, Mapping=Mapping)
    for module, table in ((f, FA_FIELD_SPEC), (surface, FB_FIELD_SPEC), (u2, UPDATE_FIELD_SPEC)):
        names.update({name: getattr(module, name) for name in table})
    names.update({name: getattr(surface, name) for name in FB_ALIAS_SPEC})
    names.update({name: getattr(u2, name) for name in UPDATE_ALIAS_SPEC})
    names.update({name: getattr(f, name) for name in FA_ALIAS_SPEC})
    return names


def assert_exact_fields(actual, declaration, names):
    expected = {name: eval(annotation, names) for name, annotation in
                (field.split(":", 1) for field in declaration.split(";"))}
    assert {field.name for field in fields(actual)} == set(expected), actual.__name__
    # Evaluate one annotation layer only. get_type_hints unfolds recursive JSON
    # differently for runtime annotations and future annotations. That unfolding
    # depth is not a field contract. No product private alias value is inspected:
    # _Literal's spelling in the supplied public annotation means typing.Literal.
    public_names = dict(names, _Literal=Literal, _Ref=Ref, _ContractRef=ContractRef)
    actual_hints = {name: eval(value, public_names) if isinstance(value, str) else value
                    for name, value in get_annotations(actual, eval_str=False).items()}
    assert actual_hints == expected, (actual.__name__, {
        name: (actual_hints.get(name), value) for name, value in expected.items()
        if actual_hints.get(name) != value})


@pytest.mark.parametrize("group,name", [
    (group, name) for group, table in (("fb", FB_FIELD_SPEC), ("f", FA_FIELD_SPEC), ("update", UPDATE_FIELD_SPEC))
    for name in table
])
def test_public_fields_and_annotations_are_exact(group, name):
    module, table = {"fb": (fb, FB_FIELD_SPEC), "f": (f, FA_FIELD_SPEC), "update": (u2, UPDATE_FIELD_SPEC)}[group]
    assert_exact_fields(getattr(module, name), table[name], declaration_names())


@pytest.mark.parametrize("group,name", [(group, name) for group, table in
                         (("fb", FB_ALIAS_SPEC), ("update", UPDATE_ALIAS_SPEC), ("f", FA_ALIAS_SPEC)) for name in table])
def test_public_union_branches_are_exact(group, name):
    module, table = {"fb": (fb, FB_ALIAS_SPEC), "update": (u2, UPDATE_ALIAS_SPEC), "f": (f, FA_ALIAS_SPEC)}[group]
    assert getattr(module, name) == eval(table[name], declaration_names()), name


@pytest.mark.parametrize("mutation", ("nullable_data", "extra_event_branch"))
def test_exact_checks_reject_temporary_declaration_copies(mutation):
    """R04: in-memory public-declaration copies only; original module untouched."""
    original_received, original_event = fb.Received, fb.FEvent
    copy = SimpleNamespace(**{name: getattr(fb, name) for name in (*FB_FIELD_SPEC, *FB_ALIAS_SPEC)})
    assert_exact_fields(copy.Received, FB_FIELD_SPEC["Received"], declaration_names(copy))
    assert copy.FEvent == eval(FB_ALIAS_SPEC["FEvent"], declaration_names(copy))
    if mutation == "nullable_data":
        copy.Received = make_dataclass("ReceivedCopy", [("route_epoch", str), ("media_type", str),
            ("data", bytes | None), ("claims", f.ImmutableJSON)])
        with pytest.raises(AssertionError):
            assert_exact_fields(copy.Received, FB_FIELD_SPEC["Received"], declaration_names(copy))
    else:
        copy.FEvent = copy.FEvent | int
        with pytest.raises(AssertionError):
            assert copy.FEvent == eval(FB_ALIAS_SPEC["FEvent"], declaration_names(copy))
    assert fb.Received is original_received and fb.FEvent is original_event


@pytest.mark.parametrize("contrast", ("monitoring", "report_origin", "acquisition_order"))
def test_stage3_independent_evidence_contrasts_are_constructible(contrast):
    """B:2085-2096,752-756; construction of inputs, NOT verifier execution.

    Every pair has the same raw reports and call/target. Only its independent
    history changes, so copying Started/Ended/Claim or WorkId cannot decide it.
    """
    wid, input_point = "measure-A", point("measured-content")
    raw = tuple(fb.SegmentReport(segment=point("segment"), item_slot=tag, item=segment_items()[tag])
                for tag in ("started", "ended", "claim"))
    raw = (replace(raw[0], item=replace(raw[0].item,
        reading=replace(reading(), reading=f.ClockReading(run=ref(), time_ns=10)))), *raw[1:])
    raw_points = tuple(point("saved-raw-" + tag) for tag in ("started", "ended", "claim"))
    reports = tuple(u2.ReportObservation(envelope=101 + index, received_ns=21 + index, point=saved)
                    for index, saved in enumerate(raw_points))
    execution = u2.ExecutionObservation(work_id=wid, launches=("launched",), entered=1,
                                         stopped=True, reports=reports)
    reader_work = "belief-result-A"
    legal = u2.TargetEvidence(executions=(execution, u2.ExecutionObservation(
        work_id=reader_work, launches=("launched",), entered=1, stopped=True, reports=())),
        uses=(u2.UseObservation(work_id=reader_work, point=input_point, used_ns=30),),
        intervals=(u2.IntervalObservation(work_id=wid, interval=interval()),),
        acquisitions=(u2.AcquisitionObservation(origin=point("origin"),
            contents=frozenset({input_point}), acquired_ns=25),))
    if contrast == "monitoring":
        illegal = replace(legal, intervals=(
            u2.IntervalObservation(work_id=wid, interval=replace(interval(), end_ns=14)),
            u2.IntervalObservation(work_id=wid, interval=replace(interval(), start_ns=16))))
        assert legal.intervals[0].interval == raw[2].item.interval
        assert illegal.intervals[0].interval.end_ns < illegal.intervals[1].interval.start_ns
    elif contrast == "report_origin":
        # The target saved Ended report names the same WorkId in both cases.
        # Keep work-mouth envelope numbers/r unchanged; only its saved-Point
        # association differs. Another raw report can have identical body/WorkId
        # yet a different Point. These are named construction inputs, not saves.
        target_report = raw_points[1]
        other_report = point("saved-raw-ended-duplicate")
        same_work_reports = {target_report: raw[1], other_report: raw[1]}
        bad_reports = (reports[0], replace(reports[1], point=other_report), reports[2])
        illegal = replace(legal, executions=(replace(execution, reports=bad_reports), legal.executions[1]))
        external = u2.ReportObservation(envelope=202, received_ns=22, point=target_report)
        assert same_work_reports[target_report].item.work == same_work_reports[other_report].item.work == wid
        assert [(report.envelope, report.received_ns) for report in reports] == [
            (report.envelope, report.received_ns) for report in bad_reports]
        assert target_report in {report.point for report in legal.executions[0].reports}
        assert external.point == target_report
        assert target_report not in {report.point for report in illegal.executions[0].reports}
        unconfirmed = replace(reports[1], point=None)
        assert unconfirmed.point is None and unconfirmed.point != target_report
    else:
        illegal = replace(legal, acquisitions=(replace(legal.acquisitions[0], acquired_ns=35),))
        assert legal.acquisitions[0].acquired_ns < legal.uses[0].used_ns
        assert illegal.uses[0].used_ns < illegal.acquisitions[0].acquired_ns
    components = real_components()
    ledger = components.ledger
    reader = SimpleNamespace(entry=ledger.entry, entries=ledger.entries, record=ledger.record,
        ancestors=ledger.ancestors, sealed_content=lambda cid: (
            components.contents.get(ledger.entry(cid).seal)[0], ledger.record(cid).body.content))
    call = dict(request=point("Q"), reader=reader, registry=test_registry(), budget=fixture_budget())
    good_call, bad_call = dict(call, evidence=legal), dict(call, evidence=illegal)
    signature(u2.compute_finite_update).bind(**good_call)
    signature(u2.compute_finite_update).bind(**bad_call)
    good_input, bad_input = (raw, good_call), (raw, bad_call)
    assert good_input[0] is bad_input[0] and legal != illegal
    for key in ("request", "reader", "registry", "budget"):
        assert good_call[key] is bad_call[key]
