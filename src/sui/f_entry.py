"""関所 F の共通の値 codec と、事実の入口 (f_facts) が内部で使う読み手。

公開の入口は f_facts.__all__ だけ (今の約束 E-01)。派生物を受け取る入口と
F-b の記録・受付の層は 2026-10-12 に外した (写し: Desktop/sui_fb_material_20261012)。

F-a で検査する: 原記録・proof・外部参照とハンドルの発行元。
構造 DTO/JSON の復号は認証でなく、手作り同名欄を検査済みと受け付けない。
構造の検査と数学の再計算を実装する。F-b のホスト接続は骨組みのまま。
"""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from typing import Literal as _Literal, TypeAlias as _TypeAlias

from .agent import View as _View
from .clock import Clock as _Clock
from .contracts import ContractRef as _ContractRef
from .f import (
    ActionSpec, C1Read, CandidateSet, CapabilityKind, ClockReading, ComputationState, ContractValue,
    DependencyRef, DrawRecord, EvidenceHistory, EvaluationScope, FCertificate, FContext, FEvaluation,
    FBeliefContent, FProblem, FQuantity, FRegistry, FResolved, FResources, FRoot, FPreflight, FLimitProblem,
    FContinuation,
    FiniteObservation, KnowledgeHistory, LegacyComparison, MeasurementId, NoDecision,
    NormalizationCertificate, Reservation, ReservationDue, ResumePoint, RouteConfig,
    Selected, TailCertificate, Unavailable, _FValue,
    limit_problem_from_json,
)
from .f_model import FModel
from .ids import IdSource as _IdSource, Ref as _Ref
from .ledger import Ledger as _Ledger
from .preference import PreferenceView as _PreferenceView, Resolved as _Resolved
from .rate import RateBudget, RationalInterval
from .rate_model import RateModel
from .records import Producer as _Producer, Record as _Record


@_dataclass(frozen=True, slots=True, kw_only=True)
class RouteApplied:
    """F-b互換（v0.13の通常F-a公開面から退避）: F-a で検査する: ROUTE_CONFIG の実適用記録。F-b で提案と有効化を分ける。"""
    config: RouteConfig
    effective_from: ClockReading | Unavailable
    execution: _Ref | None
    evidence: tuple[_Ref, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class RecordAvailability:
    """PreflightInput.availability.records の要素。名前は §3-10-13-補で採用済み。
    F-a で検査する: 固定 resources の存在証跡。自己申告を認証にしない。"""
    ref: _Ref
    present: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityAvailability:
    """PreflightInput.availability.capabilities の要素。名前は §3-10-13-補で採用済み。
    F-a で検査する: 同 registry の宣言と実装を別々に確認する。"""
    kind: CapabilityKind
    ref: _ContractRef
    declared: bool
    implemented: bool


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreflightAvailability:
    """PreflightInput.availability の値。名前は §3-10-13-補で採用済み。
    F-a で検査する: モデル不要なら null、それ以外は同 resources の存在証跡。"""
    model_present: bool | None
    records: tuple[RecordAvailability, ...]
    capabilities: tuple[CapabilityAvailability, ...]


@_dataclass(frozen=True, slots=True, kw_only=True)
class PreflightInput:
    """F-a で検査する: 前提入力と検査器が固定 resources から作る証跡。
    呼出側の自己申告は受けず、後で増えた資源を以前の不足の証跡へ置換しない。"""
    request: FPreflight
    availability: PreflightAvailability


# Python の資源/実装/係の依存口は JSON 値に含めない。
FPublicValue: _TypeAlias = (
    _FValue | RouteApplied
    | RecordAvailability | CapabilityAvailability | PreflightAvailability | PreflightInput
)


def make_f_resources(*, models: tuple[FModel | RateModel, ...],
                     records: tuple[_Record, ...], registry: FRegistry,
                     ledger: _Ledger | None = None) -> FResources:
    """F-a でモデル digest・原記録参照・検査器を解決する不変資源を作る。
    同 ID 衝突/不正参照 FInputError、欠けた宣言 FSpecificationMissing、未実装能力 FIncomplete。
    原記録が読めない場合 FReplayUnavailable。固定入力だけを使い latest を読まない。
    ledger は検証した点/原記録の本文の不変 reader に切り離す。writer は保持しない。
    空でない親の因果を compiler が読むには ledger の指定が必要。"""
    from . import f as core
    from .f_model import f_model_ref, f_model_json
    from .rate_model import rate_model_ref, rate_model_json
    core._require(registry, core.FRegistry)
    if type(models) is not tuple or type(records) is not tuple:
        raise core.FInputError("shape", "tuples required")
    seen_models, seen_records, model_index = {}, {}, {}
    for model in models:
        if type(model) is FModel:
            key, data = f_model_ref(model), f_model_json(model)
        elif type(model) is RateModel:
            key, data = rate_model_ref(model), rate_model_json(model)
        else:
            raise core.FInputError("shape", field="models")
        if key in seen_models and seen_models[key] != data:
            raise core.FInputError("shape", "model digest conflict")
        seen_models[key] = data
        model_index[key] = model
    for record in records:
        if type(record) is not _Record:
            raise core.FInputError("shape", field="records")
        if record.id in seen_records and seen_records[record.id] != record:
            raise core.FInputError("measurement_conflict", "record ID conflict")
        seen_records[record.id] = record
    from ._f_world import freeze_world_ledger
    preference_ledger = None if ledger is None else freeze_world_ledger(ledger)
    return core._handle(FResources, authority=core._MappingProxyType(model_index),
        models=models, records=tuple(seen_records.values()), registry=registry,
        preference_ledger=preference_ledger)


def read_f_observations(model: FModel, records: tuple[_Record, ...], *,
                        resources: FResources) -> tuple[FiniteObservation, ...]:
    """F-a で固定モデル・Plan/Binding と raw を公開の測定/投影/生成契約で照合する。
    finite_measurement/1 は Frame の実値、CoverageClaim.kind、Gap.reason を射影する。
    value_only/1 は時刻/quality が追加情報を与えない条件を検査、未証明は FIncomplete(certificate_incomplete)。
    opportunity_step_slot/1 は plan/opportunity/step の正準 digest と原測定 ID を照合。
    evidence=None の outcome を閉区間や no_arrival の原記録へ変換しない。
    同観測へ写る核をまとめ、必要な Binding 欠落 FSpecificationMissing(observation_binding_missing)、
    矛盾 FInputError(observation_binding_mismatch)、quality/cursor 不正 FInputError(shape)、
    raw 不足 FReplayUnavailable(missing_input)、能力不足 FIncomplete。受信時刻を実測時刻にしない。"""
    from . import f as core, f_contracts as fc
    from .f_model import _model_ref as f_model_ref, _parts
    from .records import Observed, Prediction, Role
    core._require(resources, FResources)
    model_ref = f_model_ref(model)
    core._resource_model(resources, model_ref)
    _, kernels, _, _ = _parts(model)
    resources_by_id = {r.id: r for r in resources.records}
    selected_ids = {r.id for r in records}
    for record in records:
        if resources_by_id.get(record.id) != record:
            raise core.FReplayUnavailable("missing_input", str(record.id))
    # finite_measurement/1 projects only a Frame value, CoverageClaim.kind and
    # Gap.reason. MeasurementUnavailable and CoverageUnproved report the absence
    # of a value or proof (V-09, A-14): no cell can receive them, so they need
    # no Binding. They stay in E and never enter K as an observation.
    def projectable(r):
        contract = getattr(r.body, "contract", None)
        if contract == fc.MEASUREMENT:
            return True
        if contract != fc.COVERAGE:
            return False
        value = r.body.content.as_json()
        return not (isinstance(value, dict) and value.get("kind") in ("measurement_unavailable", "coverage_unproved"))
    raw_ids = {r.id for r in records if projectable(r)}
    found, covered, measurements, generations = [], set(), {}, {}
    for record in records:
        if getattr(record.body, "contract", None) != fc.OBSERVATION_BINDING:
            continue
        if not isinstance(record.body, Observed) or record.writer != Role.MEMBRANE:
            raise core.FInputError("observation_binding_mismatch", "Binding must be Observed/MEMBRANE")
        binding = f_from_json(record.body.content.data, contract=fc.OBSERVATION_BINDING)
        if binding.plan not in resources_by_id:
            raise core.FSpecificationMissing("observation_binding_missing", "plan missing")
        plan_record = resources_by_id[binding.plan]
        if not isinstance(plan_record.body, Prediction) or plan_record.writer != Role.MODEL or plan_record.body.contract != fc.OBSERVATION_PLAN:
            raise core.FInputError("observation_binding_mismatch", "Plan must be Prediction/MODEL")
        plan = f_from_json(plan_record.body.content.data, contract=fc.OBSERVATION_PLAN)
        if plan.model_ref != model_ref:
            continue
        if binding.opportunity not in resources_by_id or any(r not in resources_by_id for r in binding.generated_by):
            raise core.FReplayUnavailable("missing_input", "generation record missing")
        if not binding.records or any(r not in resources_by_id for r in binding.records):
            raise core.FReplayUnavailable("missing_input", "raw record missing")
        if not set(binding.records) <= selected_ids:
            continue
        kernel = core._decode(core._call_capability('kernel',_ContractRef(plan.kernel.name,plan.kernel.version),
            args=plan.kernel.args,input=core._encode(core.ModelInput(model_ref=model_ref)),
            registry=resources.registry,resources=resources,model_ref=model_ref),core.FiniteKernel)
        if kernel.id not in kernels or core._dumps(kernel) != core._dumps(kernels[kernel.id]):
            raise core.FInputError('proof_mismatch','plan kernel resolution differs from model','/plan/kernel')
        _check_plan(plan, kernel)
        value = _observation_value(plan, binding, resources)
        for kind, ref in (("measurement", plan.measurement_contract), ("projection", plan.time_projection)):
            projected = core._call_capability(kind, ref, args={},
                input=core._encode(core.ObservationInput(plan=plan, binding=binding)),
                registry=resources.registry, resources=resources, model_ref=model_ref)
            if core._decode(projected, core.ObservationValue) != value:
                raise core.FInputError("observation_binding_mismatch", "projection disagrees with raw record")
        generation = core._decode(core._call_capability("generation", plan.generation_contract,
            args={}, input=core._encode(core.GenerationInput(plan=plan, binding=binding)),
            registry=resources.registry, resources=resources, model_ref=model_ref), core.GenerationOutput)
        matches = tuple(c for c in plan.cells if c.observation == value)
        if len(matches) != 1 or matches[0].id != binding.cell:
            raise core.FInputError("observation_binding_mismatch", "raw cell mismatch")
        slots = {o.evidence.slot for o in kernel.outcomes if o.id in matches[0].outcomes}
        # Coverage bindings can be measurement-free; frames require their declared slot.
        frames = []
        for ref in binding.records:
            raw = resources_by_id[ref]
            if raw.body.contract == fc.MEASUREMENT:
                frame = f_from_json(raw.body.content.data, contract=fc.MEASUREMENT)
                frames.append(frame)
                if frame.measurement_id in measurements and measurements[frame.measurement_id] != frame:
                    raise core.FInputError("measurement_conflict")
                measurements[frame.measurement_id] = frame
        actual_mids = tuple(s.measurement for s in binding.slots)
        for slot in binding.slots:
            key = (binding.plan, binding.opportunity, binding.step, slot.slot)
            if not binding.derived_from and slot.measurement in generations and generations[slot.measurement] != key:
                raise core.FInputError("measurement_conflict", "same measurement has different generation")
            if not binding.derived_from:
                generations[slot.measurement] = key
        if frames and (set(s.slot for s in binding.slots) != slots or set(actual_mids) != {f.measurement_id for f in frames}):
            raise core.FInputError("observation_binding_mismatch", "slot mismatch")
        transition = core._digest({"plan": binding.plan, "opportunity": binding.opportunity, "step": binding.step})
        if generation.transition_key != transition or generation.slots != binding.slots:
            raise core.FInputError("observation_binding_mismatch", "generation mismatch")
        from ._f_identity import resource_bindings
        from ._f_handles import issue
        resource_bindings(resources,(record.id,binding.plan,binding.opportunity,*binding.records,*binding.generated_by))
        observation = issue(core._handle(FiniteObservation, authority=resources, model_ref=model_ref,
            transition_key=transition, kernel=kernel.id, outcomes=matches[0].outcomes,
            measurements=actual_mids, records=binding.records, binding=record.id))
        found.append(observation)
        covered.update(binding.records)
    if raw_ids - covered:
        raise core.FSpecificationMissing("observation_binding_missing", "raw record lacks binding")
    def order(obs):
        return min((resources_by_id[r].at.run_index, resources_by_id[r].at.mono_ns,
                    resources_by_id[r].at.seq, str(r)) for r in obs.records)
    return tuple(sorted(found, key=order))


def build_histories(model: FModel, records: tuple[_Record, ...], *,
                    available: tuple[MeasurementId, ...],
                    incorporated: tuple[MeasurementId, ...], belief: _Ref | None,
                    proofs: tuple[_Ref, ...], resources: FResources
                    ) -> tuple[EvidenceHistory, KnowledgeHistory]:
    """F-a で raw と資源の生成宣言・Binding・証明から E/K を構築する。
    全配送の原記録を保持し同測定は一つ、available と incorporated を区別。
    衝突 FInputError(measurement_conflict)、対応欠落 FSpecificationMissing(observation_binding_missing)、
    原記録不足 FReplayUnavailable、未認証 FIncomplete、型の外 FOutsideEvaluationType。"""
    from . import f as core, f_contracts as fc
    observations = read_f_observations(model, records, resources=resources)
    by_id = {r.id: r for r in resources.records}
    links, coverage, gaps = {}, [], []
    for observation in observations:
        binding = f_from_json(by_id[observation.binding].body.content.data, contract=fc.OBSERVATION_BINDING)
        for ref in observation.records:
            raw = by_id[ref]
            if raw.body.contract == fc.COVERAGE:
                value = f_from_json(raw.body.content.data, contract=fc.COVERAGE)
                if isinstance(value, core.CoverageClaim) and value not in coverage:
                    coverage.append(value)
                elif isinstance(value, core.Gap) and value not in gaps:
                    gaps.append(value)
                continue
            frame = f_from_json(raw.body.content.data, contract=fc.MEASUREMENT)
            mid = frame.measurement_id
            old = links.get(mid)
            links[mid] = core.EvidenceLink(measurement=mid,
                records=tuple(sorted(set((() if old is None else old.records) + (ref,)), key=str)),
                generated_by=tuple(sorted(set((() if old is None else old.generated_by) + binding.generated_by), key=str)),
                derived_from=binding.derived_from,
                contract=f_from_json(by_id[binding.plan].body.content.data, contract=fc.OBSERVATION_PLAN).measurement_contract)
    available = core._decode(core._encode(available), tuple[core.MeasurementId, ...])
    incorporated = core._decode(core._encode(incorporated), tuple[core.MeasurementId, ...])
    core._unique(available, "available")
    core._unique(incorporated, "incorporated")
    if not set(incorporated) <= set(available) or not set(available) <= links.keys():
        raise core.FInputError("unresolved_reference", "K must reference E")
    if belief is not None and belief not in by_id or any(p not in by_id for p in proofs):
        raise core.FReplayUnavailable("missing_input", "belief/proof missing")
    from ._f_identity import resource_bindings
    resource_bindings(resources, (() if belief is None else (belief,)) + proofs)
    link_values = tuple(links.values())
    E = EvidenceHistory(key=core._digest({"links": link_values, "coverage": tuple(coverage), "gaps": tuple(gaps)}),
        links=link_values, coverage=tuple(coverage), gaps=tuple(gaps))
    values = dict(available=available, incorporated=incorporated, belief=belief,
        kernel_basis=tuple(sorted({o.binding for o in observations}, key=str)),
        normalization_proofs=proofs, query_proofs=proofs, pending=())
    K = KnowledgeHistory(key=core._digest(values), **values)
    return E, K


def resolve_f_preferences(view: _PreferenceView, *, resources: FResources,
                          legacy_view: _View | None = None) -> FResolved:
    """F-a で current の因果的取消規則を保ち旧紙・F の紙・白紙を解決する。
    白紙は unbounded_total/gamma=1、style/source=None。旧 H=null は one_step、整数 H は finite_horizon。
    旧 gamma は Fraction(float) の二進有理数。費用は宣言された確率・log の意味から再構築。
    旧 parser/resolve が FStyle を読めたとはせず、current の取消・因果規則を継承する。
    style が並存して整合しない場合 FSpecificationMissing(style_conflict)、形不正 FInputError、
    費用証明不足 FIncomplete(cost_certificate)。一般の無限路へ好みを延長しない。"""
    from . import f as core, f_contracts as fc
    from .preference import _parse, _sink_styles
    from .s4d_contracts import PREFERENCE
    core._require(resources, FResources)
    if type(view) is not _PreferenceView:
        raise core.FInputError("shape", field="view")
    records, parsed = {}, {}
    by_id = {r.id: r for r in resources.records}
    for point in view.points:
        if point.unread is not None or point.record is None:
            raise core.FReplayUnavailable("missing_input", "preference unread")
        record = point.record
        actual = by_id.get(record.id)
        if actual is None:
            raise core.FReplayUnavailable("missing_input", str(record.id))
        if core._digest(actual) != core._digest(record):
            raise core.FReplayMismatch("result_mismatch", fields=("/preferences",))
        from ._f_identity import resource_record
        resource_record(resources, record.id)
        records[record.id] = record
        if record.body.contract == fc.STYLE:
            style = f_from_json(record.body.content.data, contract=fc.STYLE)
            if style.gamma < 0:
                raise core.FInputError("shape", "negative gamma")
            parsed[record.id] = {"kind": "style", "style": style}
        elif record.body.contract == PREFERENCE:
            try:
                parsed[record.id] = _parse(record)
            except ValueError as exc:
                # A-20: a missing/extra key of the declared paper is a shape error.
                raise core.FInputError("shape", str(exc), "/preferences/content") from exc
        else:
            raise core.FSpecificationMissing("missing_contract", "unknown preference")
    items = {ref for ref, p in parsed.items() if p["kind"] == "item"}
    removed = set()
    for ref, p in parsed.items():
        if p["kind"] == "withdraw":
            for name in p["items"]:
                item = core._decode(name, core._Ref)
                if item not in items or (item, ref) not in view.before:
                    raise core.FInputError("unresolved_reference", "withdraw must target ancestor item")
                removed.add(item)
    styles = _sink_styles({r for r, p in parsed.items() if p["kind"] == "style"}, view.before)
    if len(styles) > 1:
        raise core.FSpecificationMissing("style_conflict")
    source = styles[0] if styles else None
    if source is None:
        scope = EvaluationScope(name="unbounded_total", version="1", H_ns=None, source=None)
        gamma = core._Fraction(1)
    elif "style" in parsed[source]:
        style = parsed[source]["style"]
        scope = EvaluationScope(name=style.scope.name, version=style.scope.version, H_ns=style.scope.H_ns, source=source)
        gamma = style.gamma
    else:
        style = parsed[source]
        scope = EvaluationScope(name="one_step" if style["H_ns"] is None else "finite_horizon",
            version="1", H_ns=style["H_ns"], source=source)
        gamma = core._Fraction(style["gamma"])
    refs = tuple(sorted(items - removed, key=str))
    return core._handle(FResolved, authority=resources, items=refs, style=source,
        scope=scope, gamma=gamma, item_contracts=tuple(records[r].body.contract for r in refs), proofs=())


def read_c1_frames(model: RateModel, records: tuple[_Record, ...], *,
                   context: FContext, resources: FResources) -> C1Read:
    """F-a で原 rate_report・route/job/attempt・completion・時計/被覆から C1 の実窓を検査する。
    最小は root-window→read の二窓、count=0/1/2。同 run・原点・連続性を要求。
    時計だけ/窓途中は frames=空で pending。wait 完了を count=0 や第二計数にしない。
    原値と p の実測・生成元を保存。飽和3以上/隙間/順序不明/一般率は
    FIncomplete(c1_closure_unproved)、衝突 FInputError(measurement_conflict)、
    意味不足 FSpecificationMissing、原記録不足 FReplayUnavailable。手作り窓を認証しない。"""
    from . import f as core
    from . import rate_entry as re
    from ._f_handles import issue
    from .rate import RateIncomplete, RateInputError, RateSpecificationMissing, RateModelFalsified
    from .rate_model import rate_model_ref
    from .records import Observed, AttemptStarted, Role
    cfg = core._c1_checked_config(model)
    models = core._require(resources, FResources)
    ref = rate_model_ref(model)
    if ref not in models:
        raise core.FReplayUnavailable("missing_input", ref)
    context = core._decode(core._encode(context), FContext)
    if context.clock_contract != _ContractRef("exact", "1"):
        raise core.FIncomplete("c1_closure_unproved", "C1 requires measured exact windows")
    by_id = {r.id:r for r in resources.records}
    if type(records) is not tuple:
        raise core.FInputError("shape", "records must be a tuple")
    for record in records:
        if record.id not in by_id:
            raise core.FReplayUnavailable("missing_input", str(record.id))
        if by_id[record.id] != record:
            raise core.FInputError("measurement_conflict", "raw record differs from fixed resource")
        if (record.at.run != context.run or record.at.mono_ns > context.now_ns or
            getattr(record.body,"received_ns",None) is not None and record.body.received_ns > context.observed_ns):
            raise core.FInputError("shape","selected C1 record lies beyond the fixed context")
    raw = tuple(r for r in resources.records if r.at.run == context.run and r.at.mono_ns <= context.now_ns
        and (not isinstance(r.body, Observed) or r.body.received_ns is None or r.body.received_ns <= context.observed_ns))
    sources = tuple(r for r in raw if getattr(r.body,"contract",None) == re.SOURCE)
    try:
        reading = re.read_rate(model, raw)
        # C1's F reader consumes measured count windows. It does not require a
        # synthetic Thought/check merely because the receipt boundary advanced.
        history = _c1_raw_history(cfg,reading.rate_records,context,sources)
        origin = history._boot_ns
        specs = {s["id"]:s for s in cfg["records"]}
        windows = {w["record"]:w for w in cfg["coverage"]["intervals"]}
        unit_ns = _Fraction(*cfg["units"]["time"]["seconds"])*10**9
        # A gap cannot be promoted to a zero-count sample, even when the rest
        # of the report's clock and alphabet are valid.
        for record in raw:
            if getattr(record.body,"contract",None) != re.RATE_REPORT:
                continue
            value = record.body.content.as_json()
            if value["channel"] in windows:
                window = windows[value["channel"]]
                expected = (origin+unit_ns*_Fraction(*window["start"]), origin+unit_ns*_Fraction(*window["end"]))
                if (value["window_start_ns"],value["window_end_ns"]) != expected:
                    raise core.FIncomplete("c1_closure_unproved", "count window has a gap or undeclared coverage")
                if value["arrival_count"]["kind"] != "exact" or value["arrival_count"]["value"] not in (0,1,2):
                    raise core.FIncomplete("c1_closure_unproved", "saturated counts are outside the density closure")
        re._fixed_events(cfg, history)
    except RateIncomplete as exc:
        raise core.FIncomplete("c1_closure_unproved", exc.detail, exc.field) from exc
    except RateSpecificationMissing as exc:
        raise core.FSpecificationMissing("missing_contract", exc.detail, exc.field) from exc
    except RateInputError as exc:
        raise core.FInputError(exc.reason, exc.detail, exc.field) from exc
    except RateModelFalsified as exc:
        raise core.FInputError("measurement_conflict", exc.detail, exc.field) from exc
    from ._f_identity import resource_bindings
    resource_bindings(resources,tuple(r.id for r in raw))
    frames, untouched, seen = [], [], {}
    ordered_windows = sorted(windows, key=lambda name:_Fraction(*windows[name]["start"]))
    for record in records:
        body = record.body
        if not isinstance(body, Observed) or body.contract != re.RATE_REPORT:
            untouched.append(record.id)
            continue
        if record.writer != Role.MEMBRANE:
            raise core.FInputError("measurement_conflict", "count report writer")
        value = body.content.as_json()
        if value["channel"] not in windows:
            untouched.append(record.id)
            continue
        channel = value["channel"]
        ordinal = ordered_windows.index(channel)
        mid = core.MeasurementId(origin=context.run, route_epoch=body.route, sample_seq=ordinal, component="count")
        generated = (body.caused_by, by_id[body.caused_by].body.job) if body.caused_by else tuple(r.id for r in raw if getattr(r.body,"contract",None) == re.BOOT)
        probe = None
        if specs[channel]["probe"] is not None:
            variable = cfg["_probability"]["id"]
            probe = core.C1Probe(measurement_id=core.MeasurementId(origin=context.run, route_epoch=body.route,
                sample_seq=ordinal, component=variable), variable=variable, label=value["outcome"])
        frame = issue(core._handle(core.C1CountFrame, authority=ref, measurement_id=mid, source_record=record.id, delivery_records=(record.id,),
            run=context.run, origin_ns=origin, start_ns=value["window_start_ns"], end_ns=value["window_end_ns"],
            count=value["arrival_count"]["value"], probe=probe, generated_by=generated))
        if mid in seen:
            old = frames[seen[mid]]
            if core._c1_measurement_content(old,ref) != core._c1_measurement_content(frame,ref) or old.probe != frame.probe:
                raise core.FInputError("measurement_conflict")
            values = {f.name:getattr(old,f.name) for f in core._fields(old)}
            values["delivery_records"] = tuple(dict.fromkeys(old.delivery_records+(record.id,)))
            frames[seen[mid]] = issue(core._handle(core.C1CountFrame,authority=ref,**values))
        else:
            seen[mid] = len(frames)
            frames.append(frame)
    frames.sort(key=lambda f:(f.start_ns,f.end_ns,str(f.source_record)))
    if any(a.end_ns != b.start_ns for a,b in zip(frames,frames[1:])):
        raise core.FIncomplete("c1_closure_unproved", "count history is not contiguous")
    completed = {r.body.caused_by for r in raw if getattr(r.body,"contract",None) == re.RATE_REPORT}
    pending = tuple(DependencyRef(key=str(r.id),basis=(r.id,r.body.job)) for r in records
        if isinstance(r.body,AttemptStarted) and r.id not in completed)
    return C1Read(frames=tuple(frames), pending=pending, untouched_records=tuple(untouched))


def _compare_legacy_bridge(view, candidates, resolved, *, u, budget, evaluator):
    """F-a で旧入力から対応する F 宣言と新計算を作り、対象・候補・所要・時刻・範囲・
    好み・O0 の ContractValue を assumptions に記録し値を照合する。
    FA21 は一回 M/Q、FA07 は受信済みで K 未使用の O0 と初手費用を区別する。
    旧経路の bytes は変更しない。未認証モデル FIncomplete(algorithm_unavailable)、
    型外 FOutsideEvaluationType、意味不足 FSpecificationMissing、形不正 FInputError、
    不一致 FReplayMismatch。旧 plan_s4c を白紙 F の代用にしない。"""
    from . import f as core, f_contracts as fc
    from .agent import plan
    from .model import GenerativeModel
    from .preference import current,resolve
    if not isinstance(view,_View) or not isinstance(resolved,_Resolved):
        raise core.FInputError("shape","View and Resolved required")
    model = view.model
    if type(model) is not GenerativeModel:
        raise core.FOutsideEvaluationType("OutsideEvaluationType","direct bridge requires the static legacy model")
    if type(u) is float and core._math.isfinite(u):
        u = _Fraction(u)
    if type(u) is not _Fraction or not 0<=u<1 or candidates != ("M","Q"):
        raise core.FInputError("shape","direct bridge candidate axis M,Q and a draw in [0,1) required")
    if _Fraction(float(u)) != u:
        raise core.FIncomplete("algorithm_unavailable","the legacy float API cannot represent this same exact draw")
    pending = bool(view.reading.pending)
    expected_actions = ("M","Q","P") if pending else ("M","Q")
    perfect,quiet = ((1,0),(0,1),(0,0)), ((0,0),(0,0),(1,1))
    supported = (model.actions == expected_actions and len(model.states)==2 and len(model.outcomes)==3
        and tuple(_Fraction(float(v)) for v in model.D)==(_Fraction(1,2),_Fraction(1,2))
        and not model.learnable and model.Q is None and not model.arrivals and not model.duration_priors
        and all(tuple(tuple(float(v) for v in row) for row in model.a[a])==(quiet if a=="Q" else perfect) for a in model.actions)
        and all(model.durations.get(a)==((1.0,1.0),) and model.measures.get(a)=="report" for a in model.actions)
        and not view.reading.unread and all(not values.any() for values in view.reading.n.values())
        and resolved.gamma==1 and resolved.H_ns==(0 if pending else None))
    if pending:
        supported = supported and tuple(view.reading.pending.values())==("P",) and view.now_ns==10**9 and view.observed_ns==0
        supported = supported and all(view.reading.started.get(ref)==(0,) for ref in view.reading.pending)
    elif view.now_ns not in (None,0) or view.observed_ns not in (None,0):
        supported = False
    actual = resolve(current(view.preferences),view)
    # The legacy DTO contains callable features/log tables; compare every
    # immutable field, rather than treating its item references as identity.
    if actual != resolved:
        raise core.FReplayMismatch("result_mismatch",fields=("/preferences",))
    if not supported:
        raise core.FIncomplete("algorithm_unavailable","direct bridge certifies only the FA21/FA07 static declarations")
    from .preference import _parse
    by_ref = {r.id:r for r in view.reading.preferences}
    for item in actual.items:
        raw = _parse(by_ref[item.id])
        if (not pending or raw["rule"] != {"name":"table","version":"1"}
            or raw["args"] != {"feature":{"name":"started_actions","version":"1"},"probs":[[["M"],0.75],[["Q"],0.25]]}):
            raise core.FIncomplete("algorithm_unavailable","direct bridge preference feature is outside the certified mapping")
    declaration, actions = _bridge_declaration(model)
    fmodel = FModel(declaration=core._dumps(declaration))
    evaluations = tuple(evaluator(fmodel,actions,view,actual,u,budget,bit)
        for bit in ((0,1) if pending else (None,)))
    # O0 is integrated under its original common law before selecting an
    # action. Each F branch has E present and K empty; no outcome is leaked.
    count = len(evaluations)
    information, J = [], []
    for i in range(2):
        information.append(core._quantity(core._mul(core._r(_Fraction(1,count)),
            core._add(*(e.information[i].total_information.exact for e in evaluations))),budget))
        J.append(core._quantity(core._mul(core._r(_Fraction(1,count)),core._add(*(e.J[i].exact for e in evaluations))),budget))
    choice = core._soft_choice(tuple(J),(_Fraction(1),_Fraction(1)),_Fraction(1),budget)
    index = next((i for i,(left,right) in enumerate(zip(choice.cumulative,choice.cumulative[1:])) if left.upper<=u<right.lower),None)
    if index is None:
        raise core.FIncomplete("selection_boundary","the bridge draw is not separated by certified cumulative bounds")
    old_draft = plan(view,candidates,u=float(u))
    old = old_draft.content.as_json()
    if old["chosen"] != candidates[index]:
        raise core.FReplayMismatch("result_mismatch",fields=("/chosen",))
    assumptions = (ContractValue(contract=_ContractRef("sui.f.legacy_bridge","1"),value={
        "legacy_contract":core._encode(old_draft.contract),
        "model":declaration,"candidate_correspondence":[[a,a] for a in candidates],"duration_ns":10**9,
        "measurement_time":"report","scope":"finite_horizon" if pending else "one_step","H_ns":actual.H_ns,
        "gamma":[1,1],"u":core._encode(u),"preferences":[core._encode(_parse(by_ref[i.id])) for i in actual.items],
        "O0":{"legacy":"pending at root" if pending else "absent","F":"received E, unavailable K" if pending else "absent",
            "law":[[1,2],[1,2]] if pending else [],"averaged_before_choice":True},
        "roots":[core._encode(e.root) for e in evaluations]}),)
    return LegacyComparison(legacy_contract=old_draft.contract,assumptions=assumptions,
        old_information=tuple(old["information"]),reconstructed_information=tuple(information),old_J=tuple(old["J"]),new_J=tuple(J),
        old_probabilities=tuple(old["q_pi"]),new_probabilities=choice.q_star,old_choice=old["chosen"],new_choice=candidates[index])


def _bridge_declaration(legacy):
    from . import f as core, f_contracts as fc
    kernels,policies,actions = [],[],[]
    for name in legacy.actions:
        outcomes = []
        for k,label in enumerate(legacy.outcomes):
            weights = tuple(_Fraction(float(v)) for v in legacy.a[name][k])
            if not any(weights):
                continue
            outcomes.append(core.FiniteOutcome(id=label,elapsed_ns=10**9,
                evidence=core.EvidenceEmission(slot="m",kind="measurement",value=k,
                    measurement_contract=_ContractRef("sui.f.finite_measurement","1")),
                available=core.AvailabilityChange(reveal=("m",),computation=None),completion=True,
                matrix=tuple(tuple(w if i==j else _Fraction(0) for j,w in enumerate(weights)) for i in range(2))))
        kernels.append(core.FiniteKernel(id=name,outcomes=tuple(outcomes)))
        policies.append(core.FinitePolicy(id=name,entry="run",nodes=(core.ExecuteNode(id="run",kind="execute",kernel=name,
            next={o.id:"end" for o in outcomes}),core.EndNode(id="end",kind="end"))))
        fields = dict(family=core.ActionFamilyRef(name="finite_option",version="1"),args={"opportunity":name,"path_action":name},
            start=core.PredicateRef(name="constant",version="1",args={"value":True}),
            policy=core.PolicyRef(name="finite_policy",version="1",args={"id":name}),
            termination=core.PredicateRef(name="policy_end",version="1",args={}),termination_kind="certain",
            prediction=core.KernelRef(name="finite_kernel",version="1",args={"id":name}),execution=_ContractRef("sui.f.simulated_execution","1"))
        actions.append(core.ActionSpec(id=name,semantic_key=core._digest(fields),**fields,
            proof=core.ProofRef(name="finite_option_proof",version="1",args={"operation":name})))
    declaration = {"scheme":"sui.model.10","contract":core._encode(fc.FINITE_MODEL),
        "units":{"record":"ns","duration":"ns","information":"nat","cost":"nat"},
        "targets":list(legacy.states),"states":[{"id":s,"target":s} for s in legacy.states],
        "initial":core._encode(tuple(_Fraction(float(v)) for v in legacy.D)),"kernels":core._encode(kernels),
        "operations":core._encode(actions),"policies":core._encode(policies),
        "certificate_capabilities":core._encode(tuple(_ContractRef(name,"1") for name in
            ("finite_tree","fixed_policy_tail","static_target_entropy_bound","finite_terminal_cost")))}
    return declaration,tuple(actions[:2])


def f_json(value: FPublicValue) -> bytes:
    """F-a で確定した公開値の全欄を正準 UTF-8 JSON にする。キー整列・空白なし、
    ensure_ascii=False/allow_nan=False、Ref=str、tuple=配列、Fraction=既約R、区間={lower:R,upper:R}。
    型固定 content は直の形。補助 VALUE は {type:公開型名,value:全欄}、動的 import 禁止。
    包みは必要な二型の和だけ: clock/unavailable、Frame.value の value/unavailable、
    COVERAGE の claim/gap/measurement_unavailable/coverage_unproved、at/when、selected/no_decision、
    追加状態の available/unavailable。None は null で札なし、単独の ClockReading は包まない。
    FinitePolicy.kind、FLimitProblem.cost.kind、ExactReal.op は直の識別子で二重包装しない。
    構造キー Mapping は正準 key bytes 順の配列。
    不正/未知札 FInputError(shape)、未知版 FInputError(unknown_version)。資源/関数と未確定 F-b 仕事、
    未知 columns の Run を F-a の検査済み受理対象へ拡大しない。保存/復号を認証としない。"""
    from . import f as core
    table, public = _wire_types()
    if type(value) not in public.values():
        raise core.FInputError("shape", "not a public F value")
    raw = core._encode(value)
    core._decode(raw, type(value))
    if isinstance(value, (core.FQuantityConstantDeclaration, core.FQuantityEvaluationDeclaration)):
        return core._dumps(raw)
    if type(value) in table.values():
        return core._dumps(raw)
    if isinstance(value, (core.CoverageClaim, core.Gap, core.MeasurementUnavailable, core.CoverageUnproved)):
        return core._dumps({"kind": core._tag(value), "value": raw})
    return core._dumps({"type": type(value).__name__, "value": raw})


def f_from_json(data: bytes, *, contract: _ContractRef) -> FPublicValue:
    """F-a で確定した契約・正準 bytes・全欄と §3-10-13-2 の札を検査して構造を復号する。
    clock/unavailable、value/unavailable、coverage 四種、at/when、selected/no_decision、
    available/unavailable を使い、None は null。自身の kind/op を持つ型を二重包装しない。
    VALUE.type は公開名のみ。未知札/型/二重包装 FInputError(shape)、未知版 FInputError(unknown_version)。
    schema/noncanonical/rational 等も FInputError。proof/外部参照/発行元は認証しない。
    JSON の VerifiedMathResult は構造値であり、再検査せずハンドルに戻さない。ROOT は f_facts.restore_f_root。
    資源・callable・未確定 F-b 型を自動受理しない。"""
    from . import f as core, f_contracts as fc
    table, public = _wire_types()
    raw = core._load_json(data)
    # V-08 / E-05: a known name at an unregistered version (the unpublished
    # drafts problem/root/value/1-2 and compiler/1-2 included) is unknown_version.
    if contract not in table and contract not in (fc.VALUE_FACTS, fc.COVERAGE):
        if contract.name in {r.name for r in (*table, fc.VALUE_FACTS, fc.COVERAGE)}:
            raise core.FInputError("unknown_version", field="contract/version")
    if contract == fc.VALUE_FACTS:
        core._keys(raw, ("type", "value"))
        if raw["type"] not in public:
            raise core.FInputError("shape", "unknown VALUE type", "/type")
        return core._decode(raw["value"], public[raw["type"]], "/value")
    if contract == fc.COVERAGE:
        core._keys(raw, ("kind", "value"))
        choices = {"claim": core.CoverageClaim, "gap": core.Gap,
                   "measurement_unavailable": core.MeasurementUnavailable, "coverage_unproved": core.CoverageUnproved}
        if raw["kind"] not in choices:
            raise core.FInputError("shape", field="/kind")
        return core._decode(raw["value"], choices[raw["kind"]], "/value")
    if contract not in table:
        raise core.FSpecificationMissing("missing_contract")
    value = core._decode(raw, table[contract])
    if contract in (fc.MATH_ARTIFACT, fc.MATH_ARTIFACT_V2) and value.compiler != fc.PREPARE_FACTS:
        raise core.FInputError("unknown_version", field="/compiler")
    return value


def _wire_types():
    from . import f as core, f_contracts as fc
    import typing
    public = {t.__name__: t for t in typing.get_args(FPublicValue)}
    table = {fc.PREDICATE: core.PredicateRef, fc.CANDIDATE_SET: core.CandidateSet,
        fc.EVIDENCE_HISTORY: core.EvidenceHistory,
        fc.CERTIFICATE: core.FCertificate, fc.RESUME_POINT: core.ResumePoint,
        fc.OBSERVATION_PLAN: core.ObservationPlan,
        fc.OBSERVATION_BINDING: core.ObservationBinding, fc.STYLE: core.FStyle,
        fc.MEASUREMENT: core.MeasurementFrame, fc.DRAW: core.DrawRecord,
        fc.EVALUATION: core.FEvaluation, fc.BELIEF: core.FBeliefContent,
        fc.ROUTE_CONFIG: RouteApplied,
        fc.LIMIT_PROBLEM: core.FLimitProblem, fc.LIMIT_CERTIFICATE: core.LimitCertificate}
    table.update({fc.ROOT_FACTS: core.FRoot,fc.PROBLEM_FACTS: core.FProblem,
        fc.KNOWLEDGE_ORIGIN: core.KnowledgeOrigin,
        fc.CONTENT_ACQUIRED: core.ContentAcquired,
        fc.COMPUTATION_REQUESTED: core.ComputationRequested,
        fc.COMPUTATION_RESULT: core.ComputationResult,
        fc.COMPUTATION_PROOF: core.ComputationProof,
        fc.COMPUTATION_COMPLETED: core.ComputationCompleted,
        fc.KNOWLEDGE_ADOPTED: core.KnowledgeAdopted,
        fc.CLOCK_READING: core.FClockReadingFact,
        fc.CONTEXT_OBSERVED: core.FContextObserved,
        fc.MODEL_SOURCE: core.FModelSource,
        fc.CANDIDATE_DECLARATION: core.FCandidateDeclaration,
        fc.DRAW_FACT: core.FDrawFact,
        fc.MEASUREMENT_REQUESTED: core.MeasurementRequested,
        fc.MEASUREMENT_JOB: core.MeasurementJob,
        fc.LIMIT_DECLARATION: core.FLimitProblem,
        fc.QUANTITY_DECLARATION: core.FQuantityDeclaration,
        fc.FINITE_UPDATE_RESULT: core.FiniteUpdateResult,
        fc.FINITE_UPDATE_STATEMENT: core.FiniteUpdateStatement,
        fc.MATH_ARTIFACT: core.FMathArtifactJSONV1,
        fc.MATH_ARTIFACT_V2: core.FMathArtifactJSONV2,
        fc.LEGACY_BRIDGE_FACTS: core.FLegacyBridgeFactsContent,
        fc.MATH_VERIFICATION: core.FMathVerificationCertificate})
    return table, public


def _check_plan(plan, kernel):
    from . import f as core
    core._unique(tuple(c.id for c in plan.cells), "plan/cells", nonempty=True)
    covered = []
    for cell in plan.cells:
        core._unique(cell.outcomes, "plan/cells/outcomes", nonempty=True)
        selected = tuple(o for o in kernel.outcomes if o.id in cell.outcomes)
        if len(selected) != len(cell.outcomes):
            raise core.FInputError("observation_binding_mismatch", "unknown outcome")
        if any(o.evidence is None or (o.evidence.kind, o.evidence.value) != (cell.observation.kind, cell.observation.value)
               or o.evidence.measurement_contract != plan.measurement_contract for o in selected):
            raise core.FInputError("observation_binding_mismatch", "emission projection mismatch")
        if len({o.elapsed_ns for o in selected}) != 1:
            raise core.FIncomplete("certificate_incomplete", "discarded timing distinguishes latent outcomes")
        covered.extend(cell.outcomes)
    core._unique(tuple(covered), "plan/cells/outcomes")
    if set(covered) != {o.id for o in kernel.outcomes if o.evidence is not None}:
        raise core.FInputError("observation_binding_mismatch", "emitting outcomes not partitioned")


def _observation_value(plan, binding, resources):
    from . import f as core, f_contracts as fc
    from .records import Observed, Role
    values = []
    by_id = {r.id: r for r in resources.records}
    for ref in binding.records:
        if ref not in by_id:
            raise core.FReplayUnavailable("missing_input", str(ref))
        record = by_id[ref]
        if not isinstance(record.body, Observed) or record.writer != Role.MEMBRANE or record.body.caused_by != binding.opportunity:
            raise core.FInputError("observation_binding_mismatch", "raw generation mismatch")
        if record.body.contract == fc.MEASUREMENT:
            frame = f_from_json(record.body.content.data, contract=fc.MEASUREMENT)
            if frame.route_epoch != plan.route_epoch or (frame.measurement_id.route_epoch, frame.measurement_id.sample_seq) != (frame.route_epoch, frame.sample_seq):
                raise core.FInputError("observation_binding_mismatch", "route/measurement mismatch")
            if isinstance(frame.value, core.Unavailable) or isinstance(frame.actual_time, core.Unavailable):
                raise core.FIncomplete("certificate_incomplete", "measurement unavailable",
                                       "/measurement/value" if isinstance(frame.value, core.Unavailable) else "/measurement/actual_time")
            quality = core._decode(core._call_capability("quality", frame.quality.contract, args={}, input=core._encode(frame.quality),
                registry=resources.registry, resources=resources),core.ContractValue)
            cursor = core._decode(core._call_capability("cursor", frame.source_cursor.contract, args={}, input=core._encode(core.CursorInput(cursor=frame.source_cursor, sample_seq=frame.sample_seq)),
                registry=resources.registry, resources=resources),core.ContractValue)
            if quality != frame.quality or cursor != frame.source_cursor:
                raise core.FInputError('observation_binding_mismatch','quality/cursor output differs from raw measurement','/measurement')
            route_records = tuple(r for r in resources.records if getattr(r.body, "contract", None) == fc.ROUTE_CONFIG)
            routes = tuple(f_from_json(r.body.content.data, contract=fc.ROUTE_CONFIG) for r in route_records)
            config = next((r.config for r in routes if r.config.route_epoch == frame.route_epoch), None)
            if config is None:
                raise core.FReplayUnavailable("missing_input", "route config missing")
            reading = core._decode(core._call_capability("clock", config.clock_contract, args={}, input=core._encode(core.ClockInput(reading=frame.actual_time, interval=frame.measurement_interval)),
                registry=resources.registry, resources=resources),core.ClockReading)
            if reading != frame.actual_time:
                raise core.FInputError('observation_binding_mismatch','clock output differs from measured time','/measurement/actual_time')
            if frame.measurement_id.origin != frame.measurement_interval.clock:
                raise core.FInputError("observation_binding_mismatch", "measurement origin")
            values.append(core.ObservationValue(kind="measurement", value=frame.value))
        elif record.body.contract == fc.COVERAGE:
            coverage = f_from_json(record.body.content.data, contract=fc.COVERAGE)
            if isinstance(coverage, core.CoverageClaim):
                values.append(core.ObservationValue(kind="coverage", value=coverage.kind))
            elif isinstance(coverage, core.Gap):
                values.append(core.ObservationValue(kind="gap", value=coverage.reason))
            else:
                raise core.FIncomplete("certificate_incomplete", "coverage not measured")
        else:
            raise core.FInputError("observation_binding_mismatch", "not raw measurement")
    if not values or any(v != values[0] for v in values):
        raise core.FInputError("observation_binding_mismatch", "inconsistent raw values")
    for kind, ref in (("measurement", plan.measurement_contract), ("projection", plan.time_projection), ("generation", plan.generation_contract)):
        if not any(d.kind == kind and d.ref == ref for d in resources.registry.declarations):
            raise core.FSpecificationMissing("missing_contract", ref.name)
        if not any(i.kind == kind and i.ref == ref for i in resources.registry.implementations):
            raise core.FIncomplete("algorithm_unavailable", ref.name)
    return values[0]


def _c1_raw_history(cfg,raw,context,sources):
    from . import f as core, rate_entry as re
    from .records import Observed,Role,JobOpened,AttemptStarted
    from types import SimpleNamespace
    boots = tuple(r for r in raw if getattr(r.body,"contract",None)==re.BOOT)
    if not boots or not sources:
        raise core.FReplayUnavailable("missing_input","C1 requires BOOT and measured clock source")
    origins = {r.at.mono_ns for r in boots}
    if len(origins)!=1:
        raise core.FInputError("measurement_conflict","conflicting origins")
    origin = next(iter(origins))
    if context.observed_ns>context.now_ns or context.observed_ns<origin:
        raise core.FInputError("shape","receipt boundary outside origin/now")
    for record in sources:
        p = record.body.content.as_json()
        core._keys(p,("run","provider","implementation","python_version","resolution_s","monotonic","adjustable","measurement"))
        if (record.writer != Role.MEMBRANE or p["run"] != str(context.run) or p["measurement"] != {"name":"exact","version":"1"}
            or p["monotonic"] is not True or type(p["adjustable"]) is not bool
            or any(type(p[k]) is not str or not p[k] for k in ("provider","implementation","python_version"))):
            raise core.FInputError("measurement_conflict","clock source/declared exact clock mismatch")
        if core._decode(p["resolution_s"],_Fraction)<=0:
            raise core.FInputError("shape","clock resolution")
        if record.body.content.data != sources[0].body.content.data:
            raise core.FInputError("measurement_conflict","conflicting clock sources")
    for record in raw:
        if record.at.run != context.run or record.at.mono_ns > context.now_ns:
            raise core.FInputError("shape","raw count history outside fixed context")
        if isinstance(record.body,Observed) and record.body.contract != re.SOURCE:
            if record.body.received_ns is None:
                raise core.FReplayUnavailable("missing_input","receipt reading missing")
            if not origin <= record.body.received_ns <= min(context.observed_ns,record.at.mono_ns):
                raise core.FInputError("measurement_conflict","receipt chronology")
    by_id = {r.id:r for r in raw}
    specs = {r["id"]:r for r in cfg["records"]}
    processes = {p["id"]:p for p in cfg["processes"]}
    unit_ns = _Fraction(*cfg["units"]["time"]["seconds"])*10**9
    for record in raw:
        if isinstance(record.body,AttemptStarted):
            job = by_id.get(record.body.job)
            if job is None:
                raise core.FReplayUnavailable("missing_input",str(record.body.job))
            if not isinstance(job.body,JobOpened) or job.body.contract != re.RATE_JOB:
                raise core.FInputError("measurement_conflict","C1 attempt has no declared job")
            start = job.body.content.as_json()["execution"]["start"]
            if origin+unit_ns*core._decode(start["time"],_Fraction) != record.at.mono_ns or job.at.mono_ns > record.at.mono_ns:
                raise core.FInputError("measurement_conflict","job start and actual attempt disagree")
        if isinstance(record.body,Observed) and record.body.contract==re.RATE_REPORT:
            value = record.body.content.as_json()
            generator = processes[specs[value["channel"]]["generator"]]
            if generator["family"]["name"] == "fixed-completion":
                attempt = by_id.get(record.body.caused_by)
                if attempt is None:
                    raise core.FReplayUnavailable("missing_input",str(record.body.caused_by))
                if not isinstance(attempt.body,AttemptStarted):
                    raise core.FInputError("measurement_conflict","report cause is not an attempt")
                job = by_id.get(attempt.body.job)
                if job is None:
                    raise core.FReplayUnavailable("missing_input",str(attempt.body.job))
                if job.body.content.as_json()["execution"]["completion_process"] != generator["id"]:
                    raise core.FInputError("measurement_conflict","report generator differs from its job")
    return SimpleNamespace(_boot_ns=origin,_records=raw,context=context)


# Facts-only entries are also reachable here for convenience.
from .f_facts import (
    prepare_f_from_facts, bind_f_draw, evaluate_f_from_draw,
    read_f_histories_from_facts, read_c1_from_facts,
    prepare_f_predicate_from_facts, f_math_json,
    restore_f_root,
    verify_f_math_result, restore_f_math_result,
    check_f_preflight_from_facts, diagnose_f_limit_from_facts,
    certify_f_limit_from_facts, prepare_legacy_bridge_from_facts,
    evaluate_legacy_bridge_from_draw,
    FMathArtifact, FMathArtifactJSON, VerifiedMathResult,
)

F_A_FACTS_ENTRIES = (
    "sui.f_facts.prepare_f_from_facts", "sui.f_facts.bind_f_draw",
    "sui.f_facts.evaluate_f_from_draw", "sui.f_facts.read_f_histories_from_facts",
    "sui.f_facts.read_c1_from_facts", "sui.f_facts.prepare_f_predicate_from_facts",
    "sui.f_facts.f_math_json", "sui.f_facts.restore_f_root",
    "sui.f_facts.verify_f_math_result", "sui.f_facts.restore_f_math_result",
    "sui.f_facts.check_f_preflight_from_facts",
    "sui.f_facts.diagnose_f_limit_from_facts", "sui.f_facts.certify_f_limit_from_facts",
    "sui.f_facts.prepare_legacy_bridge_from_facts",
    "sui.f_facts.evaluate_legacy_bridge_from_draw",
)
# Versioned derived-input adapters: model.10 / world.1 / problem.2 / root.2.
# These remain callable for old data and fixtures; the facts compiler never
# calls them to certify its inputs. F-b adapters are listed separately above.
F_A_SHARED_READERS = ("read_f_observations", "resolve_f_preferences", "read_c1_frames")
