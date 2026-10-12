"""F-a v0.14 §3-10-15/16 and supplement: facts-only mathematical interface.

一次CIDから認証世界を作り、既存数学の結果と再構築手順を発行する。
compiler・評価・C1・極限・数量の既存アルゴリズムは変更しない。
F-b の ticket・受付・乱数消費・保存操作はこの公開一覧に含めない。
"""

from __future__ import annotations

from .contracts import ContractRef
from . import f as core, f_contracts as fc
from ._f_handles import issue, require_issued, seed_math, math_source
from .f import (
    C1Read, EvaluationScope, FHistoriesFromFacts, FMathArtifact, FMathArtifactJSON,
    FMathOutputValue, FPreflightFacts, FPreflightFactsAudit, PreflightReady,
    LimitCertificate, FLegacyBridgeRequest, FLegacyBridgeProblem, LegacyComparison,
    FFiniteUpdateModel, FQuantityFactsBinding,
    FPreparedPredicate, FProblem, FReader, FRegistry, FRoot, NoDecision,
    Point, RateBudget, Selected, VerifiedMathResult,
)


__all__ = (
    "prepare_f_from_facts", "bind_f_draw", "evaluate_f_from_draw",
    "read_f_histories_from_facts", "read_c1_from_facts",
    "prepare_f_predicate_from_facts", "f_math_json", "restore_f_root",
    "verify_f_math_result", "restore_f_math_result", "FMathArtifact",
    "FMathArtifactJSON", "VerifiedMathResult", "FReader",
    "FHistoriesFromFacts", "FPreparedPredicate",
    "check_f_preflight_from_facts", "diagnose_f_limit_from_facts",
    "certify_f_limit_from_facts", "prepare_legacy_bridge_from_facts",
    "evaluate_legacy_bridge_from_draw", "FPreflightFactsAudit",
    "FLegacyBridgeRequest", "FLegacyBridgeProblem", "FFiniteUpdateModel",
    "FQuantityFactsBinding",
)


def prepare_f_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point,
    candidate_ref: Point, preference_refs: tuple[Point, ...],
    scope_request: EvaluationScope, context_ref: Point,
    registry: FRegistry, method: ContractRef, budget: RateBudget,
) -> FMathArtifact[FProblem | NoDecision]:
    """§3-10-16-7: 一次CID/宣言から問題または根なしNoDecisionを作る。

    親の閉包と実CID/header/seal/本文を読み、E/K/context/好み/正準候補/
    worldを共通compiler内で導く。派生物を入力として受け取らず、現在heads・
    builtin能力・壁時計で補わない。reader/registryを不変に捕捉する。
    budgetは価値/H/problem_keyではない。取得と採用を混同しない。
    形不正FInputError、改変FReplayMismatch、必須原記録欠落FReplayUnavailable。
    意味不足/能力不足/証明不足/予算不足は既存の低/高水準診断を保つ。
    ID/時計/乱数の取得、台帳書込み、受付の実施は行わない。
    """
    request=core.FFactsRequest(fixed_parents=fixed_parents,model=model_ref,candidates=candidate_ref,
        preferences=preference_refs,scope=scope_request,context=context_ref,method=method)
    request=core._decode(core._encode(request),core.FFactsRequest)
    from ._f_world import _Compiler,capture_reader,check_points
    check_points((*request.fixed_parents,request.model,request.candidates,request.context,*request.preferences))
    core._unique(request.fixed_parents,'/fixed_parents')
    core._unique(request.preferences,'/preferences')
    if request.fixed_parents!=tuple(sorted(request.fixed_parents)):raise core.FInputError('noncanonical',field='/fixed_parents')
    image=capture_reader(reader,budget)
    try:
        compiler=_Compiler(request,reader=image,registry=registry,budget=budget)
        value=compiler.compile()
    except (core.FSpecificationMissing,core.FIncomplete,core.FOutsideEvaluationType,core.FModelFalsified,core.FNumericalRange) as exc:
        from ._f_eval import _no_decision
        value=_no_decision(None,exc)
    return _artifact(value,input={'kind':'facts','value':request},reader=image,registry=registry,
        op='prepare',args={'budget':budget})


def bind_f_draw(
    prepared: FMathArtifact[FProblem], draw_record_ref: Point, *,
    reader: FReader, budget: RateBudget,
) -> FMathArtifact[FRoot]:
    """§3-10-16-8: 発行問題へselection drawの実CID/本文を結ぶ。

    用途/law/u/問題キーとdrawの実祖先を検査。数学のfixed_parentsは変更せず、
    後続の測定/紙/計算を加えない。同根精密化は同Point/同u。
    一回の乱数消費や実行の時系列はF-b。手組み問題を受理しない。
    """
    require_issued(prepared,core.FMathArtifact)
    problem=prepared.value
    from ._f_handles import attached_world
    world=attached_world(problem)
    from ._f_world import read_draw,capture_reader,check_points
    check_points((draw_record_ref,),'/draw')
    from ._f_identity import point
    image=capture_reader(reader,budget)
    request=world.manifest.request.value  # FWorldManifest3: ArtifactInput {kind, value}
    draw=read_draw(image,draw_record_ref,budget=budget,parents=problem.parents,
        additional_roots=(request.model,request.context,request.candidates,*request.preferences),
        context=problem.context,purpose='selection',context_key=problem.problem_key)
    _,_,binding=point(image,draw_record_ref)
    values={field.name:getattr(problem,field.name) for field in core._fields(problem)}
    values['contract']=fc.ROOT_FACTS  # 今の約束 E-05 root/3
    root=issue(core._handle(core.FRoot,authority=world,**values,selection_draw=draw,
        draw_point=draw_record_ref,draw_record_digest=binding.digest,
        root_key=core._digest({'domain':'sui.f.root/3','problem_key':problem.problem_key,
            'draw_point':draw_record_ref,'draw_record_digest':binding.digest,'selection_draw':draw})))
    source=math_source(problem)
    node={'op':'bind_draw','args':{'draw':draw_record_ref,'budget':budget},
        'inputs':{'problem_step':source},'value':root}
    node['environment']=dict(_base(source)['environment'],reader=image)
    seed_math(root,node)
    return _wrap(root)


def evaluate_f_from_draw(
    prepared: FMathArtifact[FProblem], draw_record_ref: Point, *,
    reader: FReader, budget: RateBudget,
) -> FMathArtifact[Selected | NoDecision]:
    """固定問題と認証drawから既存数学を評価する。§3-10-16-7/8。

    bindと同じfactoryを通し、根と数学手順/予算を出力へ結合する。
    出力のattempt_idはnull。実際の保存/作用/受付を数学の成功と呼ばない。
    予期しないPython例外は元の例外。
    """
    root=bind_f_draw(prepared,draw_record_ref,reader=reader,budget=budget).value
    return _wrap(core.evaluate_f(root,budget=budget))


def read_f_histories_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point,
    context_ref: Point, registry: FRegistry, budget: RateBudget,
) -> FHistoriesFromFacts:
    """狭い原記録reader。§3-10-16-4/5/7。

    KnowledgeOrigin/取得/計算/証明/採用/時計からE/K/context/観測を導く。
    available/incorporated/belief/proofs/祖先表を引数にしない。
    取得はavailableだけを進め、K未読を推測で補わず競合採用を勝手に選ばない。
    FRoot/候補/draw不要。補7: got.modelは発行専用FFiniteUpdateModelで、
    initial_finite_belief/got.observationsのapply_f_observationへ渡せる契約。
    宣言DTO/同authority_keyの復号物で代用しない。導出は共通compilerで行う。
    """
    from ._f_world import FactsCompiler
    return FactsCompiler(reader,fixed_parents=fixed_parents,model_ref=model_ref,
        context_ref=context_ref,registry=registry,budget=budget).histories()


def read_c1_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point,
    context_ref: Point, registry: FRegistry, budget: RateBudget,
) -> C1Read:
    """C1の狭い原記録reader。§3-10-16-5/7。

    管理用FACT/時計の読みとrate_reportの実測窓を区別する。窓途中の
    未完成はpending、count=0を作らない。既存の生成/時計/閉包検査を保持。
    外部FContextや偽のFRootを要求しない。
    補8: KnowledgeOriginはC1/model.9のmodel_sourceを指せる。管理用の
    origin/時計/contextを計数/probe/被覆へ加えず、有限更新modelを要求しない。
    contextの保存遅れを実測窓へ足さない。
    """
    from ._f_world import FactsCompiler
    compiler=FactsCompiler(reader,fixed_parents=fixed_parents,model_ref=model_ref,
        context_ref=context_ref,registry=registry,budget=budget)
    from .rate_model import RateModel
    from .f_entry import read_c1_frames
    from .records import Observed
    if type(compiler.model) is not RateModel: raise core.FInputError('shape',field='/model')
    management={fc.KNOWLEDGE_ORIGIN,fc.CONTENT_ACQUIRED,fc.COMPUTATION_REQUESTED,fc.COMPUTATION_RESULT,
        fc.COMPUTATION_PROOF,fc.COMPUTATION_COMPLETED,fc.KNOWLEDGE_ADOPTED,fc.CLOCK_READING,
        fc.CONTEXT_OBSERVED,fc.MODEL_SOURCE,fc.CANDIDATE_DECLARATION,fc.DRAW_FACT,fc.PREDICATE,fc.QUANTITY_DECLARATION}
    # A-20/A-21: a record whose contract C1 does not read is left untouched;
    # it is missing_contract only when a C1 record needs its meaning (cause).
    from .records import AttemptStarted
    from .clock_contracts import SOURCE
    from .s1_contracts import ATTEMPT
    from .s4_contracts import BOOT
    from .s4b_contracts import RATE_REPORT
    # M-16: the C1 closure reads report windows; arrivals are not among its
    # four statistics, so they stay untouched rather than being re-interpreted.
    c1_names={c.name for c in (BOOT,SOURCE,RATE_REPORT)}
    candidates=tuple(r for r in compiler.resources.records if getattr(r.body,'contract',None) not in management)
    kept=tuple(r for r in candidates if not isinstance(r.body,Observed) or r.body.contract.name in c1_names)
    causes={r.body.caused_by for r in kept if isinstance(r.body,Observed)}
    kept=tuple(r for r in kept if not isinstance(r.body,AttemptStarted)
        or r.body.contract==ATTEMPT or r.id in causes)
    unread=tuple(r.id for r in candidates if r not in kept)
    resources=core._handle(core.FResources,authority=core._require(compiler.resources,core.FResources),
        models=compiler.resources.models,registry=compiler.resources.registry,preference_ledger=compiler.image,
        records=kept)
    records=tuple(r for r in resources.records if r.at.run==compiler.context.run
        and r.at.mono_ns<=compiler.context.now_ns and
        (not isinstance(r.body,Observed) or r.body.received_ns is None or r.body.received_ns<=compiler.context.observed_ns))
    result=read_c1_frames(compiler.model,records,context=compiler.context,resources=resources)
    return core._replace(result,untouched_records=tuple(dict.fromkeys(result.untouched_records+unread+
        tuple(r.id for r in compiler.resources.records if getattr(r.body,'contract',None) in management))))


def prepare_f_predicate_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...], model_ref: Point,
    context_ref: Point, predicate_ref: Point, quantity_refs: tuple[Point, ...],
    registry: FRegistry, budget: RateBudget,
) -> FPreparedPredicate:
    """一次述語/数量宣言CIDとKからcached-only入力を作る。

    §3-10-16-7/13。述語の子と数量の結果/証明/照会先/単位を準備側で検査。
    PredicateSnapshot/数量保証の自己申告やFRootを要求しない。
    補5: predicate_refはsui.f.predicate/1のPrediction/MODEL/PREDICTION。
    本文はPredicateRefの直JSON {name,version,args}。interval_compareの
    left/right.keyは数量宣言Pointで、既存snapshotのQuantityRef.keyとは別。
    全子から独立収集したPoint集合とquantity_refsの一致を要求し、重複/
    余分/漏れはFInputError。compilerがH({domain:sui.f.quantity_point/1,
    declaration,record_digest})を作り、発行述語を内部キーへ置換する。
    出力quantity_bindingsはpoint/record_digest/quantity:{key}の診断対応。
    ProofRef sui.f.quantity/2 args={binding:FQuantityFactsBinding}は出力証拠。
    quantity/1の保証とreaderは保持し、復号だけで発行しない。
    取得前/未証明はUnknown。同じ仕事記述を返しcheck_predicateで再読/
    精密化/書込みを始めない。evaluation宣言はmath_artifact/2を再認証する。
    Zはcandidate=null、q_star/Zはdimensionless、他はnat。単位違いは
    quantity_binding_conflict。別根/別E/Kへの付替えは拒否。
    """
    from ._f_world import FactsCompiler,check_points
    check_points((predicate_ref,*quantity_refs))
    from ._f_identity import point as authenticated
    from ._f_quantity import certify_facts
    from types import MappingProxyType
    compiler=FactsCompiler(reader,fixed_parents=fixed_parents,model_ref=model_ref,context_ref=context_ref,
        registry=registry,budget=budget,extra_points=(predicate_ref,*quantity_refs))
    predicate=compiler.content(predicate_ref,fc.PREDICATE)
    wanted=set()
    def visit(expression):
        compiler.capability('predicate',ContractRef(expression.name,expression.version),expression.args)
        if expression.name in ('and','or'):
            for child in core._decode(expression.args['terms'],tuple[core.PredicateRef,...]):visit(child)
        elif expression.name=='not':visit(core._decode(expression.args['term'],core.PredicateRef))
        elif expression.name=='interval_compare':
            for side in ('left','right'):
                ref=core._decode(expression.args[side],core.QuantityRef)
                from ._f_quantity import _ISSUED
                if any(issued[2].key==ref.key for issued in _ISSUED.values()):
                    raise core.FInputError('quantity_binding_conflict','internal key used as Point','/quantity/key')
                compiler.content(ref.key,fc.QUANTITY_DECLARATION);wanted.add(ref.key)
    visit(predicate)
    core._unique(quantity_refs,'/quantity_refs')
    if wanted!=set(quantity_refs):raise core.FInputError('unresolved_reference','quantity Point set','/quantity_refs')
    compiler.selected.update((predicate_ref,*quantity_refs));compiler._expand();compiler._resources()
    histories=compiler.histories()
    snapshot=core.PredicateSnapshot(model_ref=compiler.model_key,E=histories.E,K=histories.K,
        quantities=MappingProxyType({}),dependencies=histories.K.pending,policy_position=None)
    bindings=[]; quantities={}; keys={}; units={}
    for point in sorted(wanted):
        declaration=compiler.content(point,fc.QUANTITY_DECLARATION)
        record_digest=authenticated(compiler.image,point)[2].digest
        evaluation=None
        if type(declaration) is core.FQuantityConstantDeclaration:
            dependencies=tuple(core.FQuantityFactsDependency(point=p,record_digest=authenticated(compiler.image,p)[2].digest)
                for p in declaration.provenance)
            definition=core.FQuantityDefinition(kind='rational_constant',value=declaration.value,unit=declaration.unit,
                provenance=tuple(compiler.point(p).id for p in declaration.provenance))
            unit=declaration.unit
            acquired=point in compiler.acquired and set(declaration.provenance)<=compiler.acquired
        else:
            result_record=compiler.point(declaration.result)
            if result_record.body.contract!=fc.MATH_ARTIFACT_V2:raise core.FInputError('unresolved_reference',field='/quantity/result')
            compiler.payload(declaration.result, fc.MATH_ARTIFACT_V2)
            restored=restore_f_math_result(result_record.body.content.data,reader=compiler.image,registry=registry,budget=budget)
            result=restored.value
            if type(result) is core.Selected:evaluation=result.evaluation
            elif type(result) is core.FEvaluation:evaluation=result
            else:raise core.FInputError('quantity_binding_conflict',field='/quantity/result')
            unit='dimensionless' if declaration.field in ('q_star','Z') else 'nat'
            definition=core.FQuantityDefinition(kind='evaluation',root_key=evaluation.root.root_key,
                field=declaration.field,candidate=declaration.candidate)
            dependency_points={declaration.result}
            for ref in evaluation.root.facts:
                dependency_points.update(compiler.image._by_id[ref])
            dependencies=tuple(core.FQuantityFactsDependency(point=p,record_digest=authenticated(compiler.image,p)[2].digest)
                for p in sorted(dependency_points))
            acquired=point in compiler.acquired and declaration.result in compiler.acquired
        binding=core.FQuantityFactsBinding(declaration=point,record_digest=record_digest,definition=definition,
            dependencies=dependencies,unit=unit)
        key=core.QuantityRef(key=core._digest({'domain':fc.QUANTITY_POINT_DOMAIN,'declaration':point,'record_digest':record_digest}))
        keys[point]=key;units[point]=unit
        bindings.append(core.FPreparedQuantityBinding(point=point,record_digest=record_digest,quantity=key))
        if acquired:
            ref,quantity=certify_facts(binding=binding,evaluation=evaluation,resources=compiler.resources,snapshot=snapshot)
            quantities[ref]=quantity
    def rewrite(expression):
        args=dict(expression.args)
        if expression.name in ('and','or'):
            args['terms']=[core._encode(rewrite(c)) for c in core._decode(args['terms'],tuple[core.PredicateRef,...])]
        elif expression.name=='not':args['term']=core._encode(rewrite(core._decode(args['term'],core.PredicateRef)))
        elif expression.name=='interval_compare':
            left,right=(args[side]['key'] for side in ('left','right'))
            if units[left]!=units[right]:raise core.FInputError('quantity_binding_conflict','incompatible units')
            args['left']=core._encode(keys[left]);args['right']=core._encode(keys[right])
        return core.PredicateRef(name=expression.name,version=expression.version,args=core._freeze(args))
    return core._handle(core.FPreparedPredicate,authority=compiler.resources,predicate=rewrite(predicate),
        snapshot=core._replace(snapshot,quantities=MappingProxyType(quantities)),resources=compiler.resources,
        quantity_bindings=tuple(bindings))


def f_math_json(value_or_artifact: FMathArtifact | FMathOutputValue) -> bytes:
    """発行済み入力/手順/出力の正準math_artifact bytesを作る。

    §3-10-16-10/補2。新包みはmath_artifact/2。v1の意味を変更しない。
    構造DTO/復号値だけを検査済みに昇格させない。
    op/args/先行step/戻り型/全claim欄を固定する。
    """
    if type(value_or_artifact) is core.FMathArtifact:
        require_issued(value_or_artifact,core.FMathArtifact)
        return value_or_artifact.canonical_bytes
    from typing import get_args
    if type(value_or_artifact) not in get_args(core.FMathOutputValue):
        raise core.FInputError('shape',field='/value')
    return _math_bytes(value_or_artifact)


def restore_f_root(
    data: bytes, *, reader: FReader, registry: FRegistry, budget: RateBudget,
) -> FRoot:
    """新署名の根復元。§3-10-16-10/11。

    原facts→共通compiler→別範囲draw認証→保存手順を再実行して全bytes照合。
    claimのE/K/manifestを発行根拠にしない。過去の不在は実際の不変viewへ
    戻し、現在の能力で補わない。旧resources=入口へfallbackしない。
    """
    result=restore_f_math_result(data,reader=reader,registry=registry,budget=budget)
    if type(result.value) is core.FRoot: return result.value
    if type(result.value) in (core.FEvaluation,core.Selected): return result.value.root
    raise core.FInputError('shape','root output required','/claim')


def verify_f_math_result(
    data: bytes, *, reader: FReader, registry: FRegistry, budget: RateBudget,
) -> VerifiedMathResult:
    """正準数学結果を事実から再構築して照合する発行専用入口。

    §3-10-16-10/11。検証budgetと保存された実行budgetを分け、当時の
    不足のreader/registry像を失えばFReplayUnavailable。全一致後だけ発行。
    ticket/受付/保存成功/乱数消費の証明は含めない。
    """
    result,checks,input_key=_replay(data,reader=reader,registry=registry,budget=budget)
    raw=core._load_json(data)
    value=result.value
    # 今の約束 E-05: every key is D(domain, fields) with the listed domain.
    input_digest=core._digest({'domain':'sui.f.math_execution/2','input_key':input_key,
        'calls':raw['calls'],'output':raw['output']})
    result_digest=core._digest({'domain':'sui.f.math_result/2','compiler':raw['compiler'],'claim':raw['claim']})
    artifact_digest=core._digest({'domain':'sui.f.math_artifact/2','artifact':raw})
    root=value if type(value) is core.FRoot else getattr(value,'root',None)
    root_key=getattr(root,'root_key',getattr(value,'root_key',None))
    certificate=core.FMathVerificationCertificate(contract=fc.MATH_VERIFICATION,
        value=core.FMathVerificationContent(artifact_digest=artifact_digest,input_digest=input_digest,
            result_digest=result_digest,checked_calls=tuple(checks)))
    return issue(core._handle(core.VerifiedMathResult,authority=result,kind='math',input_key=input_key,
        input_digest=input_digest,root_key=root_key,result_digest=result_digest,artifact_digest=artifact_digest,
        method=fc.PREPARE_FACTS,certificate=certificate))


def restore_f_math_result(
    data: bytes, *, reader: FReader, registry: FRegistry, budget: RateBudget,
) -> FMathArtifact:
    """verifyと同じfactoryでreadonly value/bytes/readerを復元する。

    不正な形/版/手順参照、欠落、改変、当時の不足を区別する。
    構造復号だけで発行しない。F-bの実保存復旧ではない。
    """
    return _replay(data,reader=reader,registry=registry,budget=budget)[0]


def check_f_preflight_from_facts(
    reader: FReader, request: FPreflightFacts, *,
    registry: FRegistry, budget: RateBudget,
) -> FMathArtifact[PreflightReady | NoDecision]:
    """補3: 一次検査要求から当時の可否を発行する公開入口。

    形/CID/重複/固定親を検査し実reader/registry像を不変に捕捉。model、
    Point順records、kind/name/version順capabilitiesを全件検査してauditを導く。
    可否/資源/world/E/Kの自己申告を入力にしない。完了後だけ発行し、
    未取得はprerequisite_unavailable、未宣言はmissing_contract、必要実装
    不足はalgorithm_unavailable。不足NoDecisionのproofはpreflight_facts/1
    args=FPreflightFactsAudit。固定親欠落はFReplayUnavailable、改変は
    FReplayMismatch、捕捉/全件検査前の予算不足はFIncompleteで部分発行なし。
    v2 input=preflight、call.args={budget}。当時の像/能力を失った再読は
    missing_input/method_unavailable。現在能力や同view_keyだけで補わない。
    ホスト例外を不足へ変換しない。
    """
    from ._f_world import capture_reader,_UnreadLedgerRecord,check_points
    request=core._decode(core._encode(request),core.FPreflightFacts)
    core._unique(request.fixed_parents,'/fixed_parents')
    if request.fixed_parents!=tuple(sorted(request.fixed_parents)): raise core.FInputError('noncanonical',field='/fixed_parents')
    check_points((*request.fixed_parents,*request.required_records,*(() if request.model is None else (request.model,))))
    core._unique(request.required_records,'/required_records')
    core._unique(tuple((c.kind,c.ref) for c in request.required_capabilities),'/required_capabilities')
    image=capture_reader(reader,budget)
    image.ancestors(request.fixed_parents)
    failures=[]; cells=len(image.entries())
    def tick():
        nonlocal cells
        from ._f_handles import charge_verification
        charge_verification()
        cells+=1
        if cells>budget.max_cells: raise core.FIncomplete('budget_exhausted',field='/preflight')
    def audit(point,field):
        tick()
        entry=image._entries.get(point)
        record=image._records.get(point)
        if isinstance(record,_UnreadLedgerRecord) and record.detail=='seal':
            raise core.FReplayUnavailable('missing_input',point,'/seal')
        if isinstance(record,_UnreadLedgerRecord) and not record.missing:
            raise core.FReplayMismatch('result_mismatch',fields=(field,))
        body=entry is not None and not isinstance(record,_UnreadLedgerRecord)
        if not body: failures.append(core.FPreflightFailure(outcome='incomplete',reason='prerequisite_unavailable',field=field))
        if body:
            from ._f_identity import point as authenticated
            authenticated(image,point)
        return core.FPreflightRecordAudit(point=point,entry_present=entry is not None,body_present=body,
            record_digest=core._digest(record) if body else None)
    model=None if request.model is None else audit(request.model,'/model')
    if model is not None and model.body_present:
        record=image.record(model.point)
        if record.body.contract!=fc.MODEL_SOURCE: raise core.FInputError('unresolved_reference',field='/model')
        from ._f_world import _payload_record
        _payload_record(record, fc.MODEL_SOURCE, field='/model')
        source=core._decode(record.body.content.as_json(),core.FModelSource)
        if source.document['scheme']=='sui.model.11':
            from .f_model import f_model11_from_json
            f_model11_from_json(core._dumps(source.document))
        else:
            from .model import model_from_json
            model_from_json(core._dumps(source.document))
    records=tuple(audit(p,'/required_records/'+str(i)) for i,p in enumerate(sorted(request.required_records)))
    from ._f_world import certify_reader_closure
    available=tuple(a.point for a in (() if model is None else (model,))+records if a.body_present)
    try:
        certify_reader_closure(image, roots=(*request.fixed_parents,*available), budget=budget)
    except core.FReplayUnavailable as exc:
        # A negative preflight certifies the recorded absence, never a world or
        # a valid closure. Keep its specified diagnostic for that exact request;
        # an unavailable fixed parent or an unrequested dependency still fails.
        missing={a.point for a in (() if model is None else (model,))+records
                 if not a.body_present and a.point not in request.fixed_parents}
        if exc.reason!='missing_input' or exc.detail not in missing:
            raise
    capabilities=[]
    core._require(registry,core.FRegistry)
    for i,c in enumerate(sorted(request.required_capabilities,key=lambda c:(c.kind,c.ref.name,c.ref.version))):
        tick(); declared=any(d.kind==c.kind and d.ref==c.ref for d in registry.declarations)
        implemented=any(d.kind==c.kind and d.ref==c.ref for d in registry.implementations)
        capabilities.append(core.FPreflightCapabilityAudit(kind=c.kind,ref=c.ref,declared=declared,implemented=implemented))
        if not declared: failures.append(core.FPreflightFailure(outcome='rejected',reason='missing_contract',field='/required_capabilities/'+str(i)))
        elif c.implementation_required and not implemented: failures.append(core.FPreflightFailure(outcome='incomplete',reason='algorithm_unavailable',field='/required_capabilities/'+str(i)))
    result=core.FPreflightFactsAudit(request_digest=core._digest(request),model=model,records=records,
        capabilities=tuple(capabilities),failures=tuple(failures))
    proof=core.ProofRef(name=fc.PREFLIGHT_FACTS.name,version=fc.PREFLIGHT_FACTS.version,args=core._encode(result))
    if failures:
        value=core.NoDecision(attempt_id=None,root_key=None,outcome=failures[0].outcome,reason=failures[0].reason,
            detail='',field=failures[0].field,proof=proof,progress=None,resume=None)
    else:
        value=core.PreflightReady(input_key=core._digest({'request':request,'audit':result}))
    return _artifact(value,input={'kind':'preflight','value':request},reader=image,registry=registry,
        op='preflight',args={'budget':budget})


def diagnose_f_limit_from_facts(
    reader: FReader, *, declaration_ref: Point,
    registry: FRegistry, budget: RateBudget,
) -> FMathArtifact[NoDecision]:
    """補4: limit_declaration/1のPointから診断を発行する。

    本文は直FLimitProblem。CID/header/seal/本文/指定registryの検査器を
    共通factoryで認証し、既存数学の未完了/負の診断だけNoDecisionへ写す。
    proof=null/検査器なしはcertificate_incomplete、白紙費用の発散は
    information_divergent、両発散はundefined_infinite_difference。
    虚偽はproof_mismatch、不正はFInputError、欠落はFReplayUnavailable。
    budget不足はincomplete/budget_exhausted。fixed_parents/BOOT/時計/K/
    FRoot/draw不要。v2 input=limit、op=limit args={budget}。再読で現在の
    証明/組込検査器を補わず保存予算と検証予算を区別する。
    """
    return _limit(reader,declaration_ref,registry,budget,False)


def certify_f_limit_from_facts(
    reader: FReader, *, declaration_ref: Point,
    registry: FRegistry, budget: RateBudget,
) -> FMathArtifact[LimitCertificate]:
    """補4: 診断と同じPoint/registry認証からlimit証明を発行する。

    固定親/K/時計/FRoot/drawは要求しない。数学の不成立は既存の低水準
    例外、予算不足はFIncomplete。不正/改変を未完了へ薄めない。
    v2 input=limit、op=limit_certificate args={budget}。
    """
    return _limit(reader,declaration_ref,registry,budget,True)


def prepare_legacy_bridge_from_facts(
    reader: FReader, *, fixed_parents: tuple[Point, ...],
    model_ref: Point, context_ref: Point, preference_refs: tuple[Point, ...],
    candidates: tuple[str, ...], adapter: ContractRef,
    registry: FRegistry, budget: RateBudget,
) -> FMathArtifact[FLegacyBridgeProblem | NoDecision]:
    """補6: 旧モデルの一次factsから比較問題を固定する。

    model_sourceは旧model_jsonそのもの。候補は旧操作ID列、adapterは
    legacy_bridge/2。固定親のraw/紙/時計を読み、旧の純粋な読取り/導出/
    好み解決を共用。fixtureへView/Resolved/FModel11/E/Kを要求しない。
    管理FACTは旧測定へ加えない。Agent.adopt、ID/時計取得、append、
    偽belief Record/一時台帳を使わず対応する有限認証世界を内部生成する。
    最小直接橋とO0/初手費用の認証範囲を保持し一般model.9へ広げない。
    problem_keyへ保存budget/後のselection drawを含めない。v2 inputは
    legacy_bridge、op=legacy_bridge_prepare args={budget}。不正/欠落/
    改変は既存例外、型外/能力不足は既存未完了。
    """
    from ._f_world import FactsCompiler,capture_reader,check_points
    from .agent import View,read
    from .preference import resolve,current
    from .model import GenerativeModel
    request=core.FLegacyBridgeRequest(fixed_parents=fixed_parents,model=model_ref,context=context_ref,
        preferences=preference_refs,candidates=candidates,adapter=adapter)
    request=core._decode(core._encode(request),core.FLegacyBridgeRequest)
    check_points((*request.fixed_parents,request.model,request.context,*request.preferences))
    core._unique(request.fixed_parents,'/fixed_parents')
    if request.fixed_parents!=tuple(sorted(request.fixed_parents)):
        raise core.FInputError('noncanonical',field='/fixed_parents')
    image=capture_reader(reader,budget)
    try:
        compiler=FactsCompiler(image,fixed_parents=fixed_parents,model_ref=model_ref,context_ref=context_ref,
            registry=registry,budget=budget,extra_points=preference_refs)
        if adapter!=fc.LEGACY_BRIDGE_V2:raise core.FInputError('unknown_version',field='/adapter')
        if type(compiler.model) is not GenerativeModel:raise core.FOutsideEvaluationType('OutsideEvaluationType','direct static bridge only')
        view=compiler.preference_input()
        if {compiler.point(p).id for p in preference_refs}!={p.id for p in view.points}:
            raise core.FInputError('unresolved_reference',field='/preferences')
        management={fc.KNOWLEDGE_ORIGIN,fc.CONTENT_ACQUIRED,fc.COMPUTATION_REQUESTED,fc.COMPUTATION_RESULT,
            fc.COMPUTATION_PROOF,fc.COMPUTATION_COMPLETED,fc.KNOWLEDGE_ADOPTED,fc.CLOCK_READING,
            fc.CONTEXT_OBSERVED,fc.MODEL_SOURCE,fc.CANDIDATE_DECLARATION,fc.DRAW_FACT,ContractRef('sui.clock.source','1')}
        records=tuple(r for r in compiler.resources.records if getattr(r.body,'contract',None) not in management)
        reading=read(compiler.model,records)
        # No belief record is forged or adopted for this mathematical comparison.
        oldview=View(model=compiler.model,frontier=frozenset(fixed_parents),belief=None,reading=reading,
            now_ns=compiler.context.now_ns,observed_ns=compiler.context.observed_ns,preferences=view,
            check_events=compiler.context.check_events,fact_ancestors=compiler.context.fact_ancestors)
        from .preference import PreferenceUnreadable
        try:resolved=resolve(current(view),oldview)
        except PreferenceUnreadable as exc:
            # A-21/E-08: the old pure computation has no meaning for a newer
            # paper (e.g. FStyle). Not ignored (P1), reported as a typed lack.
            raise core.FSpecificationMissing('missing_contract',str(exc),'/preferences') from exc
        if candidates!=('M','Q'):raise core.FInputError('shape',field='/candidates')
        authority=(compiler,oldview,resolved,request)
        value=issue(core._handle(core.FLegacyBridgeProblem,authority=authority,problem_key=core._digest({'domain':'sui.f.legacy_bridge/2','request':request}),
            request=request,legacy_model_ref=compiler.model_key,adapter=adapter))
    except (core.FSpecificationMissing,core.FIncomplete,core.FOutsideEvaluationType,core.FModelFalsified) as exc:
        from ._f_eval import _no_decision
        value=_no_decision(None,exc)
    return _artifact(value,input={'kind':'legacy_bridge','value':request},reader=image,registry=registry,
        op='legacy_bridge_prepare',args={'budget':budget})


def evaluate_legacy_bridge_from_draw(
    prepared: FMathArtifact[FLegacyBridgeProblem], draw_record_ref: Point, *,
    reader: FReader, budget: RateBudget,
) -> FMathArtifact[LegacyComparison | NoDecision]:
    """補6: 固定した旧橋へ後のselection drawを結ぶ公開入口。

    draw_factの用途selection/context=problem_key/law=uniform_unit/1と
    固定親の祖先を検査。draw側の後着事実を混ぜず旧新数学を比較する。
    float(u)で同じ既約uを表せなければalgorithm_unavailable、丸めない。
    O0はpendingの可能報告を選択前に周辺化しE/Kに仮の実測を書かない。
    assumptionsへlegacy_bridge_facts/1の全対応欄を内部生成。旧floatを
    新保証区間へ昇格しない。v2 op=legacy_bridge args={problem_step,draw,
    budget}。draw保存/実消費はF-b。
    """
    require_issued(prepared,core.FMathArtifact)
    problem=prepared.value
    compiler,view,resolved,request=require_issued(problem,core.FLegacyBridgeProblem)
    from ._f_world import read_draw,BridgeCompiler,capture_reader
    from ._f_handles import attached_world,trace_math
    from .records import AttemptStarted
    from ._f_identity import point
    image=capture_reader(reader,budget)
    draw=read_draw(image,draw_record_ref,budget=budget,parents=request.fixed_parents,
        additional_roots=(request.model,request.context,*request.preferences),
        context=compiler.context,purpose='selection',context_key=problem.problem_key)
    u=core._decode(draw.value['u'],core._Fraction)
    def evaluator(model,actions,oldview,actual,unused_u,execution_budget,bit):
        finite=BridgeCompiler(compiler,request,model,actions,actual,execution_budget,bit).compile()
        values={field.name:getattr(finite,field.name) for field in core._fields(finite)}
        values['problem_key']=problem.problem_key
        values['contract']=fc.ROOT_FACTS
        draw_digest=point(image,draw_record_ref)[2].digest
        root=issue(core._handle(core.FRoot,authority=attached_world(finite),**values,selection_draw=draw,
            draw_point=draw_record_ref,draw_record_digest=draw_digest,
            root_key=core._digest({'problem_key':problem.problem_key,'world_key':finite.world_key,
                'draw':draw_record_ref,'record_digest':point(image,draw_record_ref)[2].digest})))
        return core.evaluate_f_recursive(root,budget=execution_budget)
    try:
        from .f_entry import _compare_legacy_bridge
        value=_compare_legacy_bridge(view,request.candidates,resolved,u=u,budget=budget,evaluator=evaluator)
        assumptions=core.FLegacyBridgeFactsContent(request=request,problem_key=problem.problem_key,
            targets=tuple(compiler.model.states),candidate_map=tuple(core.FLegacyCandidateMap(legacy=a,finite=a) for a in request.candidates),
            durations=tuple(core.FLegacyDuration(candidate=a,ns=10**9) for a in request.candidates),measurement_time='report',
            scope=core.EvaluationScope(name='finite_horizon' if view.reading.pending else 'one_step',version='1',H_ns=resolved.H_ns,source=resolved.style),
            o0=core.FLegacyO0(mode='pending_marginalized' if view.reading.pending else 'absent',
                source_attempts=tuple(sorted(cid for cid in compiler.visible_cids
                    if isinstance(compiler.point(cid).body,AttemptStarted)
                    and compiler.point(cid).body.job in view.reading.pending)),averaged_before_choice=True),
            draw=draw_record_ref,u=u)
        value=core._replace(value,assumptions=value.assumptions+(core.ContractValue(contract=fc.LEGACY_BRIDGE_FACTS,value=core._encode(assumptions)),))
    except (core.FSpecificationMissing,core.FIncomplete,core.FOutsideEvaluationType,core.FModelFalsified,core.FNumericalRange) as exc:
        from ._f_eval import _no_decision
        value=_no_decision(None,exc)
    trace_math(value,'legacy_bridge',inputs={'problem_step':problem},args={'draw':draw_record_ref,'budget':budget})
    # The captured draw scope is independent of the fixed mathematical facts.
    math_source(value)['environment']=dict(_base(math_source(problem))['environment'],reader=image)
    return _wrap(value)


def _registry_key(registry):
    """今の約束 E-05 registry_key (implementation identity lives in _f_world)."""
    core._require(registry,core.FRegistry)
    from ._f_world import registry_view_key
    return registry_view_key(registry)


def _base(node):
    while node.get('inputs'):
        node=next(iter(node['inputs'].values()))
    return node


def _artifact(value,*,input,reader,registry,op,args):
    node={'op':op,'args':args,'inputs':{},'value':value,'input':input,
        'environment':{'reader':reader,'registry':registry,'registry_key':_registry_key(registry)}}
    seed_math(value,node)
    return _wrap(value)


def _wrap(value):
    node=math_source(value); base=_base(node)
    def image(n):
        if 'environment' in n: return n['environment']['reader']
        return image(next(iter(n['inputs'].values())))
    reader=image(node)
    return issue(core._handle(core.FMathArtifact,authority=node,value=value,
        canonical_bytes=_math_bytes(value),reader=reader))


def _math_bytes(value):
    node=math_source(value); base=_base(node)
    calls=[]; indices={}
    def walk(n):
        identity=id(n)
        if identity in indices:return indices[identity]
        args=dict(n['args'])
        for name,previous in n['inputs'].items(): args[name]=walk(previous)
        index=len(calls);calls.append({'op':n['op'],'args':args});indices[identity]=index
        return index
    output=walk(node)
    def image(n):
        if 'environment' in n:return n['environment']['reader']
        return image(next(iter(n['inputs'].values())))
    raw={'contract':fc.MATH_ARTIFACT_V2,'compiler':fc.PREPARE_FACTS,'input':base['input'],
        'environment':{'reader_view_key':image(node).view_key,'registry_key':base['environment']['registry_key']},
        'calls':calls,'output':output,'claim':{'type':type(value).__name__,'value':value}}
    return core._dumps(raw)


def _limit(reader,point,registry,budget,certificate):
    from ._f_world import capture_reader,check_points,_payload_record
    core._require(registry,core.FRegistry)
    check_points((point,),'/declaration')
    from ._f_identity import point as authenticated
    from .records import Prediction,Role
    image=capture_reader(reader,budget)
    _,record,_=authenticated(image,point)
    try:
        _payload_record(record, fc.LIMIT_DECLARATION, field='/declaration')
    except core.FInputError as exc:
        # V-08/A-21: a known name at another version keeps its own reason.
        if exc.reason == 'unknown_version':
            raise
        raise core.FInputError('unresolved_reference',field='/declaration') from exc
    from ._f_world import certify_reader_closure
    certify_reader_closure(image, roots=(point,), budget=budget)
    problem=core.limit_problem_from_json(record.body.content.data)
    ref=None if problem.proof is None else ContractRef(problem.proof.name,problem.proof.version)
    supported=ref is not None and any(d.kind=='proof' and d.ref==ref for d in registry.declarations) and any(i.kind=='proof' and i.ref==ref for i in registry.implementations)
    if not supported:
        exc=core.FIncomplete('certificate_incomplete',field='/proof')
        if certificate:raise exc
        from ._f_eval import _no_decision
        value=_no_decision(None,exc)
    else:
        # The supplied checker is resolved here; the core certifies the exact law.
        try:
            checked=core._call_capability('proof',ref,args=problem.proof.args,input=core._encode(problem),
                registry=registry,budget=budget)
            if ref==ContractRef('iid_bits_limit','1'):
                core._decode(checked,core.LimitCertificate)
                proved=True
            else:
                checked=core._decode(checked,core.ProofCheck)
                if checked.status=='disproved':raise core.FInputError('proof_mismatch',field='/proof')
                proved=checked.status=='proved'
            if not proved:raise core.FIncomplete('certificate_incomplete')
            value=(core.certify_f_limit if certificate else core.diagnose_f_limit)(problem,budget=budget)
        except (core.FIncomplete,core.FSpecificationMissing) as exc:
            if certificate:raise
            from ._f_eval import _no_decision
            value=_no_decision(None,exc)
    return _artifact(value,input={'kind':'limit','value':{'declaration':point}},reader=image,registry=registry,
        op='limit_certificate' if certificate else 'limit',args={'budget':budget})


_CALL_ARGS={
    'prepare':core.FPrepareCallArgs,'bind_draw':core.FBindDrawCallArgs,
    'scope':core.FRootCallArgs,'enumerate':core.FRootCallArgs,'recursive':core.FRootCallArgs,
    'enumerated':core.FEnumeratedCallArgs,'prefix':core.FPrefixCallArgs,
    'prefix_evaluation':core.FPrefixEvaluationCallArgs,'tail':core.FTailCallArgs,
    'choice':core.FChoiceCallArgs,'evaluate':core.FEvaluateCallArgs,
    'preflight':core.FPreflightFactsCallArgs,'limit':core.FPrepareCallArgs,
    'limit_certificate':core.FPrepareCallArgs,'legacy_bridge_prepare':core.FPrepareCallArgs,
    'legacy_bridge':core.FLegacyBridgeCallArgs}

_CALL_OUTPUTS={
    'prepare':('FProblem','NoDecision'),'bind_draw':('FRoot',),
    'scope':('FScope',),'enumerate':('FPathTable',),'recursive':('FEvaluation',),
    'enumerated':('FEvaluation',),'prefix':('FPathTable',),
    'prefix_evaluation':('FEvaluation',),'tail':('TailCertificate',),
    'choice':('Selected','NoDecision'),'evaluate':('Selected','NoDecision'),
    'preflight':('PreflightReady','NoDecision'),'limit':('NoDecision',),
    'limit_certificate':('LimitCertificate',),
    'legacy_bridge_prepare':('FLegacyBridgeProblem','NoDecision'),
    'legacy_bridge':('LegacyComparison','NoDecision')}


def _call_plan(raw):
    """Validate the whole call graph before opening any primary input."""
    initial={'facts':'prepare','preflight':'preflight','limit':None,
        'legacy_bridge':'legacy_bridge_prepare'}
    kind=raw['input']['kind']
    if type(kind) is not str or kind not in initial:raise core.FInputError('shape',field='/input/kind')
    types={'facts':core.FFactsRequest,'preflight':core.FPreflightFacts,
        'limit':core.FLimitFactsRequest,'legacy_bridge':core.FLegacyBridgeRequest}
    core._decode(raw['input']['value'],types[kind],'/input/value')
    plans=[]; used=set()
    for i,call in enumerate(raw['calls']):
        core._keys(call,('op','args'))
        op=call['op']
        if type(op) is not str or op not in _CALL_ARGS:raise core.FInputError('shape',field='/calls/op')
        args=core._decode(call['args'],_CALL_ARGS[op],'/calls/'+str(i)+'/args')
        is_initial=op in ('prepare','preflight','limit','limit_certificate','legacy_bridge_prepare')
        if (i==0)!=is_initial or (i==0 and ((kind=='limit' and op not in ('limit','limit_certificate'))
            or (kind!='limit' and op!=initial[kind]))):
            raise core.FInputError('shape',field='/calls/initial')
        expected={}
        if hasattr(args,'root_step'):expected['root_step']='FRoot'
        if hasattr(args,'problem_step'):expected['problem_step']='FLegacyBridgeProblem' if op=='legacy_bridge' else 'FProblem'
        if hasattr(args,'paths_step'):expected['paths_step']='FPathTable'
        if hasattr(args,'prefix_step'):expected['prefix_step']='FPathTable'
        if hasattr(args,'evaluation_step'):expected['evaluation_step']='FEvaluation'
        if getattr(args,'resume_step',None) is not None:expected['resume_step']='NoDecision'
        for field,wanted in expected.items():
            index=getattr(args,field)
            if type(index) is not int or not 0<=index<i or wanted not in _CALL_OUTPUTS[plans[index][0]]:
                raise core.FInputError('shape',field='/calls/'+str(i)+'/args/'+field)
            used.add(index)
        plans.append((op,args))
    if used!=set(range(len(plans)-1)):raise core.FInputError('shape','unused mathematical step','/calls')
    if type(raw['claim']['type']) is not str or raw['claim']['type'] not in _CALL_OUTPUTS[plans[-1][0]]:
        raise core.FInputError('shape',field='/claim/type')
    return plans


def _input_dependencies(first,raw,image,registry,negative):
    """今の約束 E-05 FFactsDependencies for the mathematical input_key.

    A facts problem carries its world's image; a bridge problem its facts
    compiler's. Otherwise (preflight, limit, a refused preparation) the image
    is read from the primary request's Points. Absence used as a ground adds
    the captured reader/registry keys.
    """
    from ._f_world import facts_dependencies,_UnreadLedgerRecord,implementation_id
    if type(first) is core.FProblem:
        dependencies=first.world_manifest.dependencies
    elif type(first) is core.FLegacyBridgeProblem:
        compiler=first._authority[1][0]
        dependencies=facts_dependencies(compiler,(compiler,))
    else:
        value=raw['input']['value']; kind=raw['input']['kind']
        names={'facts':('fixed_parents','model','candidates','preferences','context'),
            'preflight':('fixed_parents','model','required_records'),'limit':('declaration',),
            'legacy_bridge':('fixed_parents','model','context','preferences')}[kind]
        wanted=set()
        for name in names:
            item=value.get(name)
            wanted.update(item if isinstance(item,list) else () if item is None else (item,))
        points=[]
        for cid in sorted(wanted):
            record=image._records.get(cid)
            readable=record is not None and not isinstance(record,_UnreadLedgerRecord)
            points.append(core.FFactsPointDependency(point=cid,entry_present=cid in image._entries,
                body_present=readable,record=image._entries[cid].id if cid in image._entries else None,
                record_digest=core._digest(record) if readable else None))
        required=tuple(core._decode(c,core.RequiredCapability) for c in value.get('required_capabilities',()))
        capabilities=[]
        for need in sorted(required,key=lambda c:(c.kind,c.ref.name,c.ref.version)):
            declaration=next((d for d in registry.declarations if d.kind==need.kind and d.ref==need.ref),None)
            ident=implementation_id(registry,need.kind,need.ref)
            capabilities.append(core.FFactsCapabilityDependency(kind=need.kind,ref=need.ref,declaration=declaration,
                implemented=ident is not None,implementation_id=ident))
        dependencies=core.FFactsDependencies(points=tuple(points),models=(),capabilities=tuple(capabilities),
            ref_lookups=(),absence_environment=None)
    if negative:
        dependencies=core._replace(dependencies,absence_environment=core.FFactsAbsenceEnvironment(
            reader_view_key=raw['environment']['reader_view_key'],registry_key=raw['environment']['registry_key']))
    return dependencies


def _replay(data,*,reader,registry,budget):
    from ._f_handles import verification_budget,VerificationBudgetExceeded
    budget=core._decode(core._encode(budget),core.RateBudget)
    try:
        with verification_budget(budget):
            return _replay_saved(data,reader=reader,registry=registry,budget=budget)
    except VerificationBudgetExceeded as exc:
        raise core.FIncomplete('budget_exhausted',str(exc),'/verification') from exc


def _replay_saved(data,*,reader,registry,budget):
    raw=core._load_json(data)
    core._keys(raw,('contract','compiler','input','environment','calls','output','claim'))
    if core._decode(raw['contract'],ContractRef)!=fc.MATH_ARTIFACT_V2 or core._decode(raw['compiler'],ContractRef)!=fc.PREPARE_FACTS:
        raise core.FInputError('unknown_version',field='/contract')
    core._keys(raw['environment'],('reader_view_key','registry_key'))
    core._keys(raw['claim'],('type','value'))
    core._keys(raw['input'],('kind','value'))
    core._array(raw['calls'],'/calls')
    if type(raw['output']) is not int or raw['output']!=len(raw['calls'])-1 or not raw['calls']:
        raise core.FInputError('shape',field='/output')
    for key in ('reader_view_key','registry_key'):
        core._decode(raw['environment'][key],str,'/environment/'+key)
    plans=_call_plan(raw)
    # Incomplete/environmental absence needs the real issuer-captured image.
    claimed=raw['claim']['value']
    # V-08 / E-05: the claim's own contract must be the registered version
    # before any reconstruction (compiler/1-2, problem/root/1-2 are unpublished).
    if raw['claim']['type'] in ('FProblem','FRoot'):
        expected=fc.PROBLEM_FACTS if raw['claim']['type']=='FProblem' else fc.ROOT_FACTS
        if type(claimed) is not dict or core._decode(claimed.get('contract'),ContractRef,'/claim/value/contract')!=expected:
            raise core.FInputError('unknown_version',field='/claim/value/contract')
    negative=(raw['claim']['type']=='NoDecision' and type(claimed) is dict and
        (claimed.get('reason') in ('algorithm_unavailable','missing_contract','prerequisite_unavailable')
         or (raw['input']['kind']=='limit' and claimed.get('reason')=='certificate_incomplete'
             and claimed.get('field')=='/proof')))
    # E-06: a negative claim is reproduced only with the historical image and
    # registry. Both are bound by content (reader_view_key, registry_key), never
    # by object identity: an identical reader is the same image.
    if negative:
        from ._f_world import capture_reader as _capture
        if _capture(reader,budget).view_key!=raw['environment']['reader_view_key']:
            raise core.FReplayUnavailable('missing_input','historical reader image','/environment')
        if _registry_key(registry)!=raw['environment']['registry_key']:
            raise core.FReplayUnavailable('method_unavailable','historical implementation bundle','/environment')
    from ._f_world import capture_reader
    image=capture_reader(reader,budget)
    outputs=[]; checks=[]; used=set(); referenced=[]; input_key=None
    def prior(index,expected):
        if type(index) is not int or not 0<=index<len(outputs):raise core.FInputError('shape',field='/calls/step')
        value=outputs[index]
        if type(value) is not expected:raise core.FInputError('shape','wrong preceding output type','/calls/step')
        used.add(index);referenced.append(index);return value
    for index,call in enumerate(raw['calls']):
        op,args=plans[index]
        saved=getattr(args,'budget',None)
        from ._f_handles import charge_verification
        charge_verification()
        if op in ('prepare','preflight','limit','limit_certificate','legacy_bridge_prepare'):
            if index!=0:raise core.FInputError('shape',field='/calls/initial')
            kind=raw['input']['kind']; input=raw['input']['value']
            if op=='prepare':
                if kind!='facts':raise core.FInputError('shape',field='/input/kind')
                request=core._decode(input,core.FFactsRequest)
                artifact=prepare_f_from_facts(image,fixed_parents=request.fixed_parents,model_ref=request.model,
                    candidate_ref=request.candidates,preference_refs=request.preferences,scope_request=request.scope,
                    context_ref=request.context,registry=registry,method=request.method,budget=saved)
            elif op=='preflight':
                if kind!='preflight':raise core.FInputError('shape',field='/input/kind')
                artifact=check_f_preflight_from_facts(image,core._decode(input,core.FPreflightFacts),registry=registry,budget=saved)
            elif op in ('limit','limit_certificate'):
                if kind!='limit':raise core.FInputError('shape',field='/input/kind')
                request=core._decode(input,core.FLimitFactsRequest)
                artifact=_limit(image,request.declaration,registry,saved,op=='limit_certificate')
            else:
                if kind!='legacy_bridge':raise core.FInputError('shape',field='/input/kind')
                request=core._decode(input,core.FLegacyBridgeRequest)
                artifact=prepare_legacy_bridge_from_facts(image,fixed_parents=request.fixed_parents,model_ref=request.model,
                    context_ref=request.context,preference_refs=request.preferences,candidates=request.candidates,
                    adapter=request.adapter,registry=registry,budget=saved)
            value=artifact.value
        elif op=='bind_draw':
            problem=prior(args.problem_step,core.FProblem)
            value=bind_f_draw(_wrap(problem),args.draw,reader=image,budget=saved).value
        elif op=='legacy_bridge':
            problem=prior(args.problem_step,core.FLegacyBridgeProblem)
            value=evaluate_legacy_bridge_from_draw(_wrap(problem),args.draw,reader=image,budget=saved).value
        elif op=='choice':
            result=prior(args.evaluation_step,core.FEvaluation)
            value=core.certify_f_choice(result,u=core._decode(result.root.selection_draw.value['u'],core._Fraction))
        else:
            root=prior(args.root_step,core.FRoot)
            if op=='scope':value=core.certify_f_scope(root,budget=saved)
            elif op=='enumerate':value=core.enumerate_f_paths(root,budget=saved)
            elif op=='recursive':value=core.evaluate_f_recursive(root,budget=saved)
            elif op=='enumerated':value=core.evaluate_f_enumerated(root,prior(args.paths_step,core.FPathTable),budget=saved)
            elif op=='prefix':value=core.enumerate_f_prefix(root,steps=args.steps,budget=saved)
            elif op=='prefix_evaluation':
                prefix=prior(args.prefix_step,core.FPathTable)
                if prefix.root_key!=root.root_key:raise core.FInputError('shape',field='/prefix/root')
                value=core.evaluate_f_prefix(root,steps=prefix.steps,budget=saved)
            elif op=='tail':value=core.certify_f_tail(root,candidate=args.candidate,prefix=prior(args.prefix_step,core.FPathTable),budget=saved)
            elif op=='evaluate':
                resume=None if args.resume_step is None else prior(args.resume_step,core.NoDecision).resume
                if args.resume_step is not None and resume is None:raise core.FInputError('shape',field='/resume')
                value=core.evaluate_f(root,budget=saved,resume=resume)
            else:raise core.FInputError('shape',field='/calls/op')
        outputs.append(value)
        if index==0:
            input_key=core._digest({'domain':'sui.f.math_input/2','compiler':raw['compiler'],'input':raw['input'],
                'dependencies':_input_dependencies(value,raw,image,registry,negative)})
        def output_digest(i,v):
            return core._digest({'domain':'sui.f.math_call_output/2','compiler':raw['compiler'],
                'index':i,'op':plans[i][0],'value':v})
        checks.append(core.FCheckedMathCall(index=index,op=op,
            input_digest=core._digest({'domain':'sui.f.math_call_input/2','input_key':input_key,'index':index,
                'op':op,'args':call['args'],'previous':[{'index':i,'output_digest':output_digest(i,outputs[i])}
                    for i in sorted(set(referenced))]}),
            output_digest=output_digest(index,value)))
        referenced.clear()
    if used!=set(range(len(outputs)-1)):raise core.FInputError('shape','unused mathematical step','/calls')
    value=outputs[-1]
    if raw['claim']['type']!=type(value).__name__ or core._dumps(raw['claim']['value'])!=core._dumps(value):
        raise core.FReplayMismatch('result_mismatch',fields=('/claim',))
    # Preserve the exact historical envelope after checking every claim byte;
    # a reader with later facts is a replay resource, not a new original view.
    artifact=issue(core._handle(core.FMathArtifact,authority=math_source(value),
        value=value,canonical_bytes=data,reader=image))
    return artifact,checks,input_key
