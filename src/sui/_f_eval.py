"""Finite mathematics over issued worlds only; no model or registry resolution."""
from __future__ import annotations
from ._f_handles import world_state
from .f import (
    ChooseNode,
    ComputationSpec,
    ContractValue,
    EndNode,
    EvidenceHistory,
    EvidenceLink,
    ExactReal,
    ExecuteNode,
    FCertificate,
    FEvaluation,
    FFrontierRow,
    FIncomplete,
    FInputError,
    FModelFalsified,
    FNodeValue,
    FNumericalRange,
    FOutsideEvaluationType,
    FPathResidual,
    FPathRow,
    FPathTable,
    FPathTerminal,
    FQuantity,
    FReplayMismatch,
    FRoot,
    FScope,
    FSpecificationMissing,
    InformationParts,
    EvaluationInput,
    ComputationInput,
    KnowledgeHistory,
    MeasurementId,
    NoDecision,
    NormalizationCertificate,
    PolicyPosition,
    PolicyReturn,
    PredicatePosition,
    PredicateSnapshot,
    ProofRef,
    RateBudget,
    RationalInterval,
    ResumePoint,
    Selected,
    TailCertificate,
    TailPrefix,
    TailInput,
    _ContractRef,
    _ExpressionWork,
    _Fraction,
    _add,
    _dataclass,
    _decode,
    _digest,
    _div,
    _dumps,
    _encode,
    _entropy,
    _freeze,
    _iadd,
    _kl,
    _log,
    _math,
    _mul,
    _neg,
    _r,
    _replace,
    _require,
)

_EVALUATIONS = {}

# §3-10-14-4/11 A. Any new root/evaluation entrance must be added here and to
# the static/dynamic gate checks; all listed entrances require an issued world.
WORLD_ENTRANCES = (
    'certify_f_scope','enumerate_f_paths','evaluate_f_enumerated',
    'evaluate_f_recursive','enumerate_f_prefix','evaluate_f_prefix',
    'certify_f_tail','certify_f_choice','evaluate_f','computation_information',
)

def certify_f_scope(root: FRoot, *, budget: RateBudget) -> FScope:
    """F-aで小さい世界の認証範囲を検査してFScopeの状態を返す。
    成功・未完了・意味不足・型の外・実行未認証を分ける。
    不正入力/改ざんはFInputError/FReplayMismatch。範囲外を成功へ広げない。
    """
    _require(root, FRoot)
    try:
        work = _FiniteWork(root, budget)
        _check_evaluation_contract(work)
        tree = _finite_tree(work)
        for candidate in root.candidates.candidates:
            if tree or root.scope.name == "finite_horizon":
                work.walk(work.state(candidate), candidate.id)
            else:
                _fixed_absorption(work, work.state(candidate), candidate)
        conditions = (ContractValue(contract=_ContractRef("static_target_entropy_bound", "1"), value={"targets": work.targets}),)
        return FScope(status="certified", method=root.method, reason=None, conditions=conditions)
    except FSpecificationMissing as exc:
        return FScope(status="missing_spec", method=root.method, reason=exc.reason, conditions=())
    except FIncomplete as exc:
        return FScope(status="incomplete", method=root.method, reason=exc.reason, conditions=())
    except FOutsideEvaluationType:
        return FScope(status="outside_evaluation", method=root.method, reason="OutsideEvaluationType", conditions=())


def enumerate_f_paths(root: FRoot, *, budget: RateBudget) -> FPathTable:
    """F-aで有限性を証明した全路だけを全列挙する。部分列を全路と呼ばない。
    未完了/予算切れFIncomplete、型の外FOutsideEvaluationType、
    不正入力FInputError、証明不一致FReplayMismatch。後続を平均信念へ潰さない。
    """
    work = _FiniteWork(root, budget)
    _check_evaluation_contract(work)
    if not _finite_tree(work) and root.scope.name != "finite_horizon":
        raise FIncomplete("certificate_incomplete", "cannot enumerate an infinite path set")
    table, _ = work.table()
    return table


def evaluate_f_enumerated(root: FRoot, paths: FPathTable, *,
                          budget: RateBudget) -> FEvaluation:
    """F-aで全路から共同信念・情報・路全体費用・J・確率を構成する。
    未完了FIncomplete、型の外FOutsideEvaluationType、
    別問題/不正入力FInputError、証明改ざんFReplayMismatch。
    後続のsoftmax平均をsoft minimumへ変えない。
    """
    work = _FiniteWork(root, budget)
    _check_evaluation_contract(work)
    if not _finite_tree(work) and root.scope.name != "finite_horizon":
        raise FIncomplete("certificate_incomplete")
    expected, values = work.table()
    if paths.problem_key != root.problem_key or paths.root_key != root.root_key:
        raise FInputError("shape", "table for another root")
    if _dumps(expected) != _dumps(paths):
        raise FReplayMismatch("result_mismatch", fields=("/paths",))
    costs, information = [], []
    # Independent leaf aggregation, rather than the recursive entropy increments.
    for value in values:
        costs.append(work.world.quantity(_add(*(_mul(leaf.mass, work.cost(leaf.state)) for leaf in value.leaves)), work.work))
        information.append(work.world.quantity(_observed_leaf_information(work, value.leaves), work.work))
    return _evaluation(work, tuple(costs), tuple(information), trace="enumerated")


def evaluate_f_recursive(root: FRoot, *, budget: RateBudget) -> FEvaluation:
    """F-aで全列挙とは独立の再帰から同じ評価を構成する。J=-d+ΣqV、
    選択節Vは後続Jのsoftmax平均。共同分布を保持し終端は根の路全体費用。
    未完了FIncomplete、型の外FOutsideEvaluationType、
    不正入力FInputError、証明改ざんFReplayMismatch。
    """
    return _evaluate_recursive(root, budget)


def _evaluate_recursive(root, budget, precision=None):
    return world_state(root).evaluate(root,budget,precision=precision)


def _evaluation_from_output(raw, root):
    """A method's JSON output is accepted only with its live mathematical issuance."""
    digest = _digest(raw)
    for value, stamped in _EVALUATIONS.values():
        if stamped == digest and value.root is root:
            _validate_evaluation(value)
            return value
    raise FIncomplete('certificate_incomplete','evaluation method returned an unissued value','/method')


def _evaluate_recursive_math(root, budget, precision=None):
    work = _FiniteWork(root, budget, precision=precision)
    _check_evaluation_contract(work)
    tree = _finite_tree(work)
    costs, information = [], []
    for candidate in root.candidates.candidates:
        state = work.state(candidate)
        if tree or root.scope.name == "finite_horizon":
            value = work.walk(state, candidate.id)
            cost, info = value.cost, value.information
        else:
            try:
                value = work.walk(state, candidate.id)
                cost, info = value.cost, value.information
            except FIncomplete as exc:
                if exc.reason != "certificate_incomplete":
                    raise
                cost, info, _ = _fixed_absorption(work, state, candidate)
        costs.append(work.world.quantity(cost, work.work))
        information.append(work.world.quantity(info, work.work))
    return _evaluation(work, tuple(costs), tuple(information), trace="recursive")


def evaluate_f_prefix(root: FRoot, *, steps: int,
                      budget: RateBudget) -> FEvaluation:
    """F-aで途中の深さstepsまでと残りを明示する。stepsは評価範囲Hではない。
    非零の尾を保持。計算未完了FIncomplete、型の外FOutsideEvaluationType、
    不正なsteps/入力FInputError、証明改ざんFReplayMismatch。
    """
    table = enumerate_f_prefix(root, steps=steps, budget=budget)
    work = _FiniteWork(root, budget)
    tails = tuple(certify_f_tail(root, candidate=c.id, prefix=table, budget=budget) for c in root.candidates.candidates)
    costs, infos = [], []
    for tail in tails:
        if tail.cost_total.status != "finite" or tail.information_remaining.status != "finite":
            raise FIncomplete("cost_certificate" if tail.cost_total.status != "finite" else "certificate_incomplete")
        lo = tail.information_prefix.bounds.lower
        hi = tail.information_prefix.bounds.upper + tail.information_remaining.bounds.upper
        costs.append(tail.cost_total)
        infos.append(FQuantity(status="finite", exact=tail.information_prefix.exact if tail.information_remaining.exact == _r(0) else None,
            bounds=RationalInterval(lo, hi), proof=tail.proof, reason=None))
    return _evaluation(work, tuple(costs), tuple(infos), trace="prefix", tails=tails)


def certify_f_tail(root: FRoot, *, candidate: str,
                    prefix: FPathTable, budget: RateBudget) -> TailCertificate:
    """F-aでI_n<=I∞<=I_n+R_nと独立の費用保証を検査する。
    zeroは厳密な0、analytic/boundedも残りを保持。未証明はunprovedを区別。
    計算未完了FIncomplete、型の外FOutsideEvaluationType、
    不正入力FInputError、虚偽証明FReplayMismatch。
    """
    work = _FiniteWork(root, budget)
    name = 'finite_tree' if prefix.kind == 'complete' else 'fixed_policy_tail'
    value = root if name == 'finite_tree' else TailInput(root=root,candidate=candidate,prefix=prefix)
    checked = work.world.proof(name,value,budget)
    if checked.status != 'proved':
        raise FIncomplete('certificate_incomplete', name, '/proofs')
    return _certify_tail_unchecked(root,candidate=candidate,prefix=prefix,budget=budget)


def _certify_tail_unchecked(root, *, candidate, prefix, budget):
    """The mathematical tail checker, also used by the bound proof implementation."""
    work = _FiniteWork(root, budget)
    if prefix.problem_key != root.problem_key or prefix.root_key != root.root_key:
        raise FInputError("shape", "prefix for another root")
    if candidate not in prefix.candidates:
        raise FInputError("unresolved_reference", field="candidate")
    expected = enumerate_f_paths(root, budget=budget) if prefix.kind == "complete" else enumerate_f_prefix(root, steps=prefix.steps, budget=budget)
    if _dumps(prefix) != _dumps(expected):
        raise FReplayMismatch("result_mismatch", fields=("/prefix",))
    op = next(a for a in root.candidates.candidates if a.id == candidate)
    i_terms, remaining_terms = [], []
    for row in prefix.rows:
        if row.candidate == candidate:
            posterior = tuple(_ratio_rational(q, row.probability) for q in row.joint_target)
            i_terms.append(_mul(row.probability, _kl(posterior, work.initial_target)))
    frontier = tuple(row for row in prefix.frontier if row.candidate == candidate)
    for row in frontier:
        mass = _rational_expression(row.probability)
        joint = tuple(_rational_expression(q)/mass for q in row.joint_state)
        target = work.target(joint)
        i_terms.append(_mul(row.probability, _kl(target, work.initial_target)))
        state = _replace(work.state(op), joint=joint, position=row.position,
            E_trace=(row.E,), K_trace=(row.K,), actions=row.actions)
        if root.preferences:
            raise FIncomplete("cost_certificate", "infinite/prefix total cost not certified")
        _, future_info, _ = _fixed_absorption(work, state, op)
        remaining_terms.append(_mul(row.probability, future_info))
    if root.preferences and prefix.kind != "complete":
        raise FIncomplete("cost_certificate")
    cost = _r(0)
    if prefix.kind == "complete":
        _, values = work.table()
        cost = values[prefix.candidates.index(candidate)].cost
    remaining = _add(*remaining_terms)
    proof = ProofRef(name="fixed_policy_tail" if frontier else "finite_tree", version="1", args={})
    return TailCertificate(problem_key=root.problem_key, candidate=candidate,
        prefix=TailPrefix(table_digest=_digest(prefix), kind=prefix.kind, steps=prefix.steps, candidate=candidate),
        information_prefix=work.world.quantity(_add(*i_terms), work.work), information_remaining=work.world.quantity(remaining, work.work),
        cost_total=work.world.quantity(cost, work.work), residual_mass=next(r.mass for r in prefix.residual if r.candidate == candidate),
        closure="zero" if remaining == _r(0) else "bounded", proof=proof)


def certify_f_choice(evaluation: FEvaluation, *,
                      u: _Fraction | float) -> Selected | NoDecision:
    """F-aで入力・版・根と累積保証を検査してSelectedを返す。
    previous.upper<=u<current.lower、厳密等値は半開区間。未分離は
    NoDecision(incomplete,selection_boundary)で同uを保持。
    floatは二進有理数へ正確に移す。不正入力FInputError、改ざんFReplayMismatch。
    未完了/型の外はNoDecision。中点や引き直しで選ばない。
    """
    _require(evaluation.root, FRoot)
    _validate_evaluation(evaluation)
    if type(u) is float and _math.isfinite(u):
        u = _Fraction(u)
    if type(u) is not _Fraction or not 0 <= u < 1:
        raise FInputError("shape", "u must be Fraction or finite float in [0,1)")
    if u != _decode(evaluation.root.selection_draw.value["u"], _Fraction):
        raise FInputError("shape", "u differs from the root selection draw")
    for i, (previous, current) in enumerate(zip(evaluation.cumulative, evaluation.cumulative[1:])):
        if previous.upper <= u < current.lower:
            return Selected(root=evaluation.root, evaluation=evaluation, index=i,
                choice=evaluation.root.candidates.candidates[i], u=u,
                previous=previous, current=current, certificate=evaluation.certificate)
    return _no_decision(evaluation.root, FIncomplete("selection_boundary"), progress=evaluation)


def evaluate_f(root: FRoot, *, budget: RateBudget,
                resume: ResumePoint | None = None) -> Selected | NoDecision:
    """F-a で検査済み根から選択保証が確定した時点で Selected を返す。
    手作り・構造復号の同名欄を認証としない。純数学の NoDecision.attempt_id は None。
    意味不足は rejected/missing_contract、反証は rejected/model_falsified、型の外は rejected。
    全候補許容不能は rejected/NoAdmissibleCandidate、能力/予算/境界は incomplete と進捗・再開。
    数値範囲は failed/NumericalRange。情報発散・無限差は証明に応じ負の理由を保つ。
    実行未認証は incomplete/runtime_unverified。完了しない one_step の detail は
    nonterminating_one_step。形不正 FInputError、改ざん FReplayMismatch と予期しない
    Python/I/O 例外を数学の結論へ薄めず、同 u を保持し tolerance を待って遅らせない。"""
    _require(root, FRoot)
    if resume is not None:
        if resume.root_key != root.root_key or resume.method != root.method or resume.state_digest != _digest(resume.state_payload):
            raise FReplayMismatch("result_mismatch", fields=("/resume",))
    progress = None
    try:
        work = _FiniteWork(root, budget)
        _check_evaluation_contract(work)
        u = _decode(root.selection_draw.value["u"], _Fraction)
        if _finite_tree(work) or root.scope.name == "finite_horizon":
            precision = _Fraction(1, 10**24)
            for _ in range(budget.max_refinements):
                from ._f_handles import charge_verification
                charge_verification('refinements')
                progress = _evaluate_recursive(root, budget, precision)
                result = certify_f_choice(progress, u=u)
                if isinstance(result, Selected):
                    return result
                # Refine only the numerical enclosure; J and the frozen u stay fixed.
                precision /= 2**16
            return _no_decision(root, FIncomplete("selection_boundary"), progress=progress)
        # The execution budget bounds refinement; depth never changes the scope.
        for steps in range(1, budget.max_refinements+1):
            from ._f_handles import charge_verification
            charge_verification('refinements')
            progress = evaluate_f_prefix(root, steps=steps, budget=budget)
            result = certify_f_choice(progress, u=u)
            if isinstance(result, Selected):
                return result
        return _no_decision(root, FIncomplete("budget_exhausted"), progress=progress)
    except (FIncomplete, FSpecificationMissing, FModelFalsified, FOutsideEvaluationType, FNumericalRange) as exc:
        return _no_decision(root, exc, progress=progress)


def computation_information(root: FRoot, *,
                              computation: ComputationSpec,
                              budget: RateBudget) -> InformationParts:
    """F-aで全入力Y,v,Uを条件に純粋計算のadditional=0を認証する。
    Eを増やさずKは進み、将来行動を含むJは変わりうる。
    入力不足/証明未完了FIncomplete、型の外FOutsideEvaluationType、
    不正入力FInputError、虚偽証明FReplayMismatch。
    """
    world = world_state(root)
    return world.computation(root,computation,budget)


def _computation_information_math(root, *, computation, budget):
    work = _FiniteWork(root, budget)
    if computation.method != _ContractRef("sui.f.computation_information", "1"):
        raise FSpecificationMissing("missing_contract")
    measurements = {l.measurement for l in root.E.links}
    records = {r for l in root.E.links for r in l.records}
    if not measurements <= set(computation.input_measurements) or not records <= set(computation.input_records):
        raise FIncomplete("certificate_incomplete", "full input conditioning not proved")
    if any(d.purpose != "algorithm" for d in computation.algorithm_draws):
        raise FInputError("shape", "computation draw purpose")
    already = work.world.quantity(work.already, work.work)
    return InformationParts(already_received=already, additional=work.world.quantity(_r(0), work.work), total_information=already)


def enumerate_f_prefix(root: FRoot, *, steps: int, budget: RateBudget) -> FPathTable:
    """F-a で非負 steps (0も含む) まで展開し未展開共同状態を frontier に保持する。
    steps は H と別。手作り根を信用しない。予算切れ FIncomplete(budget_exhausted)、
    型の外 FOutsideEvaluationType、不正入力 FInputError、証明不一致 FReplayMismatch。"""
    if type(steps) is not int or steps < 0:
        raise FInputError("shape", field="steps")
    work = _FiniteWork(root, budget)
    _check_evaluation_contract(work)
    return work.table(steps=steps)[0]


@_dataclass(frozen=True)
class _PathState:
    joint: tuple
    E_trace: tuple
    K_trace: tuple
    actions: tuple
    position: PolicyPosition
    O: tuple = ()
    A: tuple = ()
    slots: tuple = ()
    depth: int = 0
    executed: int = 0
    entry_depth: int = 0
    caller_depths: tuple = ()


@_dataclass(frozen=True)
class _Leaf:
    mass: ExactReal
    state: _PathState
    kind: str


@_dataclass(frozen=True)
class _WalkValue:
    cost: ExactReal
    information: ExactReal
    leaves: tuple


class _FiniteWork:
    """Conditional joint kernels; only known observations may steer a choice."""
    def __init__(self, root, budget, *, precision=None):
        self.world = world_state(root)
        self.root, self.budget = root, budget
        self.data = self.world.data
        self.kernels, self.policies, self.operations = self.world.kernels, self.world.policies, self.world.operations
        self.work = _ExpressionWork(budget, precision=precision)
        self.nodes, self.cells = [], 0
        self.targets = tuple(self.data["targets"])
        self.prior_joint = self.world.prior_joint
        self.initial_joint = self.world.initial_joint
        self.initial_target = self.target(self.initial_joint)
        self.already = _kl(self.initial_target, self.target(self.prior_joint))
        self.after = self.world.after
        self.initial_O = self.world.initial_O
        self.proof_cache = {}

    def target(self, joint):
        return tuple(sum((p for p, s in zip(joint, self.data["states"]) if s["target"] == t), _Fraction(0)) for t in self.targets)

    def state(self, candidate):
        operation = self.operation_for(candidate)
        p = self.world.operation_policies[operation.id]
        actions = () if candidate.args["path_action"] is None else (candidate,)
        A = () if not actions else ((0, ("action", 0), candidate.args["path_action"]),)
        return _PathState(joint=self.initial_joint, E_trace=(self.root.E,), K_trace=(self.root.K,), actions=actions,
            position=PolicyPosition(policy=p.id, node=p.entry, operation=operation.id,
                first_completed=False, stack=(), elapsed_ns=0), O=self.initial_O, A=A)

    def operation_for(self, candidate):
        return self.world.root_operations[candidate.id]

    def cost(self, state):
        return self.world.cost(state.O, state.A)

    def terminal(self, state, kind="ended"):
        return _WalkValue(cost=self.cost(state), information=_r(0), leaves=(_Leaf(_r(1), state, kind),))

    def transition(self, state, outcomes, next_node):
        joint = tuple(sum(o.matrix[i][j]*state.joint[j] for o in outcomes for j in range(len(state.joint))) for i in range(len(state.joint)))
        mass = sum(joint)
        if not mass:
            return None
        o = outcomes[0]
        elapsed = state.position.elapsed_ns + o.elapsed_ns
        E, K = state.E_trace[-1], state.K_trace[-1]
        slots, O = dict(state.slots), state.O
        if o.evidence is not None:
            op = self.operations[state.position.operation] if state.position.operation else None
            opportunity = op.args["opportunity"] if op is not None else {"kernel": next(n for n in self.policies[state.position.policy].nodes if n.id == state.position.node).kernel}
            epoch = _digest({"opportunity": opportunity})
            seq = 1 + sum(l.measurement.route_epoch == epoch for l in E.links)
            mid = MeasurementId(origin=self.root.context.run, route_epoch=epoch, sample_seq=seq, component=o.evidence.slot)
            link = EvidenceLink(measurement=mid, records=(), generated_by=(), derived_from=(), contract=o.evidence.measurement_contract)
            E = EvidenceHistory(key=_digest({"links": E.links + (link,), "coverage": E.coverage, "gaps": E.gaps,
                "observations": O + ((elapsed, o.evidence.kind, o.evidence.value),)}),
                links=E.links + (link,), coverage=E.coverage, gaps=E.gaps)
            slots[o.evidence.slot] = mid
            path_action = None if op is None else op.args["path_action"]
            O += ((elapsed, ("predicted", seq), path_action or "", o.evidence.value),)
        available = list(K.available)
        for slot in o.available.reveal:
            mid = slots.get(slot)
            if mid is None:
                matches = tuple(l.measurement for l in E.links if l.measurement.component == "value")
                if len(matches) == 1:
                    mid = matches[0]
                else:
                    raise FIncomplete("certificate_incomplete", "unresolved reveal slot")
            if mid not in available:
                available.append(mid)
        kvals = dict(available=tuple(available), incorporated=K.incorporated, belief=K.belief,
            kernel_basis=K.kernel_basis, normalization_proofs=K.normalization_proofs,
            query_proofs=K.query_proofs, pending=K.pending)
        known = tuple((link, O[i]) for i, link in enumerate(E.links) if link.measurement in available)
        K = KnowledgeHistory(key=_digest({"knowledge": kvals, "available_evidence": known})
            if tuple(available) != state.K_trace[-1].available else state.K_trace[-1].key, **kvals)
        pos = _replace(state.position, node=next_node, elapsed_ns=elapsed)
        return mass, _replace(state, joint=tuple(q/mass for q in joint), E_trace=state.E_trace+(E,),
            K_trace=state.K_trace+(K,), position=pos, O=O, slots=tuple(slots.items()),
            depth=state.depth+1, executed=state.executed+1)

    def walk(self, state, candidate, *, steps=None, active=()):
        from ._f_handles import charge_verification
        charge_verification()
        self.cells += 1
        if self.cells > self.budget.max_cells:
            raise FIncomplete("budget_exhausted", "policy cells")
        if len(active) > 256:
            raise FIncomplete("budget_exhausted", "recursive policy stack")
        pos = state.position
        policy = self.policies[pos.policy]
        node = next(n for n in policy.nodes if n.id == pos.node)
        terminate = False
        if pos.operation is not None and state.depth > state.entry_depth:
            op = self.operations[pos.operation]
            snapshot = PredicateSnapshot(model_ref=self.root.model_ref, E=state.E_trace[-1], K=state.K_trace[-1],
                quantities={}, dependencies=(), policy_position=PredicatePosition(policy=pos.policy, node=pos.node))
            check = self.world.predicate(op.termination, snapshot)
            if check.value == "unknown":
                raise FIncomplete("certificate_incomplete", "termination predicate unknown")
            terminate = check.value == "true"
        if steps is not None and state.depth >= steps and not isinstance(node, EndNode) and not terminate:
            return _WalkValue(_r(0), _r(0), (_Leaf(_r(1), state, "frontier"),))
        marker = (pos.policy, pos.node, pos.operation, pos.stack,
                  pos.elapsed_ns if self.root.scope.name == "finite_horizon" else None)
        if steps is None and marker in active:
            raise FIncomplete("certificate_incomplete", "infinite policy requires a tail checker")
        active += (marker,)
        if isinstance(node, EndNode) or terminate:
            terminated = pos.operation is None
            if pos.operation is not None:
                operation = self.operations[pos.operation]
                predicate = operation.termination
                if predicate.name == "policy_end":
                    terminated = state.depth > state.entry_depth and isinstance(node, EndNode)
                elif predicate.name == "constant":
                    terminated = predicate.args["value"] and state.depth > state.entry_depth
                else:
                    terminated = terminate
            if not terminated:
                raise FIncomplete("certificate_incomplete", "end does not imply psi")
            if pos.stack:
                ret = pos.stack[-1]
                restored = _replace(pos, policy=ret.policy, node=ret.return_node,
                    operation=ret.operation, stack=pos.stack[:-1])
                return self.walk(_replace(state, position=restored, entry_depth=state.caller_depths[-1],
                    caller_depths=state.caller_depths[:-1]), candidate, steps=steps, active=active)
            if not pos.first_completed and pos.operation is not None:
                after = self.after[candidate]
                pos = _replace(pos, first_completed=True)
                if self.root.scope.name != "one_step" and after is not None:
                    p = self.policies[after]
                    pos = _replace(pos, policy=p.id, node=p.entry, operation=None)
                    return self.walk(_replace(state, position=pos), candidate, steps=steps, active=active)
            return self.terminal(_replace(state, position=pos))
        if isinstance(node, ChooseNode):
            if node.rule != _ContractRef("sui.f.soft_choice", "1"):
                raise FSpecificationMissing("missing_contract", "choice rule")
            if set(l.measurement for l in state.E_trace[-1].links) - set(state.K_trace[-1].available):
                raise FIncomplete("certificate_incomplete", "choice with unread E needs a K-conditional joint kernel")
            alternatives, values = [], []
            for name in node.operations:
                operation = self.operations[name]
                snapshot = PredicateSnapshot(model_ref=self.root.model_ref, E=state.E_trace[-1],
                    K=state.K_trace[-1], quantities={}, dependencies=(),
                    policy_position=PredicatePosition(policy=pos.policy, node=pos.node))
                if self.world.predicate(operation.start, snapshot).value != "true":
                    raise FIncomplete("prerequisite_unavailable")
                p = self.world.operation_policies[operation.id]
                position = PolicyPosition(policy=p.id, node=p.entry, operation=name,
                    first_completed=pos.first_completed, elapsed_ns=pos.elapsed_ns,
                    stack=pos.stack+(PolicyReturn(policy=pos.policy, return_node=node.next[name], operation=pos.operation),))
                child = _replace(state, position=position, entry_depth=state.depth,
                    caller_depths=state.caller_depths+(state.entry_depth,))
                if operation.args["path_action"] is not None:
                    child = _replace(child, actions=child.actions+(operation,),
                        A=child.A+((pos.elapsed_ns, ("action", len(child.A)), operation.args["path_action"]),))
                alternatives.append(name)
                values.append(self.walk(child, candidate, steps=steps, active=active))
            Js = tuple(self.world.quantity(_add(v.cost, _neg(v.information)), self.work) for v in values)
            choice = self.world.soft_choice(Js, tuple(_Fraction(1) for _ in values), self.root.gamma, self.work)
            V = _add(*(_mul(q.exact, j.exact) for q, j in zip(choice.q_star, Js)))
            self.nodes.append(FNodeValue(key=_digest({"position": pos, "K": state.K_trace[-1].key}),
                candidate=candidate, position=pos, knowledge_key=state.K_trace[-1].key,
                alternatives=tuple(alternatives), J=Js, q_star=choice.q_star, V=self.world.quantity(V, self.work)))
            return _WalkValue(_add(*(_mul(q.exact, v.cost) for q, v in zip(choice.q_star, values))),
                _add(*(_mul(q.exact, v.information) for q, v in zip(choice.q_star, values))),
                tuple(_Leaf(_mul(q.exact, leaf.mass), leaf.state, leaf.kind)
                      for q, v in zip(choice.q_star, values) for leaf in v.leaves))
        kernel = self.kernels[node.kernel]
        groups = {}
        for outcome in kernel.outcomes:
            key = _dumps((outcome.elapsed_ns, outcome.evidence, outcome.available.reveal, node.next[outcome.id]))
            groups.setdefault(key, []).append(outcome)
        transitions = []
        for outcomes in groups.values():
            dt = outcomes[0].elapsed_ns
            if self.root.scope.name == "finite_horizon" and pos.elapsed_ns + dt > self.root.scope.H_ns:
                # In this certified range no unobserved pre-horizon event carries information.
                transitions.append((_Fraction(1), self.terminal(state, "horizon")))
                if len(groups) > 1:
                    if len({o.elapsed_ns for o in kernel.outcomes}) != 1:
                        raise FIncomplete("certificate_incomplete", "partial duration event")
                    break
                continue
            changed = self.transition(state, outcomes, node.next[outcomes[0].id])
            if changed is None:
                continue
            mass, child = changed
            transitions.append((mass, self.walk(child, candidate, steps=steps, active=active)))
        # Π_E is independent of the internal control position and K projection.
        # Sum the unnormalized kernels in each evidence cell before conditioning.
        immediate = _r(0)
        if not (self.root.scope.name == "finite_horizon" and all(pos.elapsed_ns+o.elapsed_ns > self.root.scope.H_ns for o in kernel.outcomes)):
            projected = []
            evidence_cells = {}
            for outcome in kernel.outcomes:
                evidence_cells.setdefault(_dumps(outcome.evidence), []).append(outcome)
            for outcomes in evidence_cells.values():
                joint = tuple(sum(o.matrix[i][j]*state.joint[j] for o in outcomes for j in range(len(state.joint))) for i in range(len(state.joint)))
                mass = sum(joint)
                if mass:
                    projected.append(_mul(_r(mass), _entropy(self.target(tuple(q/mass for q in joint)))))
            immediate = _add(_entropy(self.target(state.joint)), _neg(_add(*projected)))
        return _WalkValue(_add(*(_mul(_r(m), v.cost) for m, v in transitions)),
            _add(immediate, *(_mul(_r(m), v.information) for m, v in transitions)),
            tuple(_Leaf(_mul(_r(m), leaf.mass), leaf.state, leaf.kind) for m, v in transitions for leaf in v.leaves))

    def table(self, *, steps=None):
        rows, frontier, residual, values = [], [], [], []
        for candidate in self.root.candidates.candidates:
            value = self.walk(self.state(candidate), candidate.id, steps=steps)
            values.append(value)
            masses = []
            for leaf in value.leaves:
                s, p = leaf.state, leaf.mass
                if leaf.kind == "frontier":
                    frontier.append(FFrontierRow(candidate=candidate.id, probability=p,
                        joint_state=tuple(_mul(p, _r(q)) for q in s.joint), E=s.E_trace[-1], K=s.K_trace[-1],
                        actions=s.actions, position=s.position))
                    masses.append(p)
                else:
                    rows.append(FPathRow(candidate=candidate.id, probability=p,
                        joint_target=tuple(_mul(p, _r(q)) for q in self.target(s.joint)),
                        E_trace=s.E_trace, K_trace=s.K_trace, actions=s.actions,
                        terminal=FPathTerminal(kind=leaf.kind, position=s.position)))
            residual.append(FPathResidual(candidate=candidate.id, mass=self.world.quantity(_add(*masses), self.work)))
        names = tuple(c.id for c in self.root.candidates.candidates)
        Js = tuple(self.world.quantity(_add(v.cost, _neg(v.information), _neg(self.already)), self.work) for v in values)
        choice = self.world.soft_choice(Js, tuple(_Fraction(1) for _ in names), self.root.gamma, self.work)
        V = _add(*(_mul(q.exact, j.exact) for q, j in zip(choice.q_star, Js)))
        first = self.state(self.root.candidates.candidates[0])
        self.nodes.append(FNodeValue(key=self.root.root_key, candidate=names[0], position=first.position,
            knowledge_key=self.root.K.key, alternatives=names, J=Js, q_star=choice.q_star, V=self.world.quantity(V, self.work)))
        return FPathTable(problem_key=self.root.problem_key, root_key=self.root.root_key,
            kind="complete" if steps is None else "prefix", steps=steps, candidates=names,
            rows=tuple(rows), frontier=tuple(frontier), residual=tuple(residual), nodes=tuple(self.nodes)), tuple(values)


def _finite_tree(work):
    if 'finite_tree' not in work.proof_cache:
        work.proof_cache['finite_tree'] = work.world.proof('finite_tree',work.root,work.budget)
    return work.proof_cache['finite_tree'].status == 'proved' and _finite_tree_unchecked(work)


def _finite_tree_unchecked(work):
    visited, active = set(), set()
    def visit(policy, node):
        key = policy, node
        if key in active:
            return False
        if key in visited:
            return True
        active.add(key)
        value = next(n for n in work.policies[policy].nodes if n.id == node)
        children = []
        if not isinstance(value, EndNode):
            children.extend((policy, next_node) for next_node in value.next.values())
            if isinstance(value, ChooseNode):
                for name in value.operations:
                    op = work.operations[name]
                    p = work.world.operation_policies[op.id]
                    children.append((p.id, p.entry))
        if not all(visit(*child) for child in children):
            return False
        active.remove(key)
        visited.add(key)
        return True
    for op in work.root.candidates.candidates:
        p = work.world.operation_policies[op.id]
        if not visit(p.id, p.entry):
            return False
        if op.termination.name == "constant" and not op.termination.args["value"]:
            return False
        after = work.after[op.id]
        if work.root.scope.name != "one_step" and after is not None:
            p = work.policies[after]
            if not visit(p.id, p.entry):
                return False
    return True


def _solve_linear(matrix, rhs):
    n = len(rhs)
    rows = [list(row) + [value] for row, value in zip(matrix, rhs)]
    for col in range(n):
        pivot = next((i for i in range(col, n) if rows[i][col]), None)
        if pivot is None:
            raise FIncomplete("certificate_incomplete", "singular transient system")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        for i in range(n):
            if i != col and rows[i][col]:
                factor = rows[i][col]
                rows[i] = [a-factor*b for a, b in zip(rows[i], rows[col])]
    return tuple(row[-1] for row in rows)


def _fixed_absorption(work, state, operation):
    """Small fixed silent loops, including closed permanent nonarrival classes.

    A finite Krylov-space test proves that arrival time conveys no information
    in addition to its emission cell. No singular recurrent block is inverted.
    """
    if work.root.preferences:
        raise FIncomplete("cost_certificate", "infinite total cost not proved")
    policy = work.policies[state.position.policy]
    node = next(n for n in policy.nodes if n.id == state.position.node)
    if isinstance(node, EndNode):
        return _r(0), _r(0), _Fraction(0)
    if not isinstance(node, ExecuteNode) or state.position.stack or work.after[operation.id] is not None:
        raise FIncomplete("certificate_incomplete", "tail is not a simple fixed continuation")
    kernel = work.kernels[node.kernel]
    nodes = {n.id: n for n in policy.nodes}
    # Step counts identify wall times only in this proven duration range.
    # Unequal hidden delays require a different observation/tail proof.
    silent_times = {o.elapsed_ns for o in kernel.outcomes if node.next[o.id] == node.id}
    end_times = {o.elapsed_ns for o in kernel.outcomes if node.next[o.id] != node.id}
    if len(silent_times) > 1 or len(end_times) > 1:
        raise FIncomplete("certificate_incomplete", "variable tail timing not certified")
    n = len(state.joint)
    silent = [[_Fraction(0) for _ in range(n)] for _ in range(n)]
    emissions = {}
    for outcome in kernel.outcomes:
        next_node = nodes[node.next[outcome.id]]
        if next_node.id == node.id:
            if outcome.evidence is not None:
                raise FIncomplete("certificate_incomplete", "repeated emitting tail")
            for i in range(n):
                for j in range(n):
                    silent[i][j] += outcome.matrix[i][j]
        elif isinstance(next_node, EndNode) and operation.termination.name == "policy_end":
            key = _dumps(outcome.evidence if outcome.evidence is not None else {"completion": True})
            matrix = emissions.setdefault(key, [[_Fraction(0) for _ in range(n)] for _ in range(n)])
            for i in range(n):
                for j in range(n):
                    matrix[i][j] += outcome.matrix[i][j]
        else:
            raise FIncomplete("certificate_incomplete", "tail topology not certified")
    # States which can reach an emission are transient in this substochastic chain.
    transient = {j for j in range(n) if sum(silent[i][j] for i in range(n)) < 1}
    while True:
        expanded = transient | {j for j in range(n) if any(silent[i][j] for i in transient)}
        if expanded == transient:
            break
        transient = expanded
    axis = tuple(sorted(transient))
    system = [[_Fraction(i == j)-silent[i][j] for j in axis] for i in axis]
    visits = _solve_linear(system, tuple(state.joint[j] for j in axis)) if axis else ()
    eventual = []
    for matrix in emissions.values():
        joint = tuple(sum(matrix[i][j]*v for j, v in zip(axis, visits)) for i in range(n))
        if sum(joint):
            eventual.append(joint)
    initial_target = work.target(state.joint)
    absorbed_target = tuple(sum(work.target(j)[i] for j in eventual) for i in range(len(work.targets)))
    never_target = tuple(a-b for a, b in zip(initial_target, absorbed_target))
    never_mass = sum(never_target)
    if never_mass < 0:
        raise FInputError("normalization", "invalid absorption mass")
    if work.root.scope.name == "one_step" and never_mass:
        raise FOutsideEvaluationType("OutsideEvaluationType", "nonterminating_one_step")
    # For each cell, posterior target is constant over all finite arrival times.
    # Checking n powers suffices by Cayley-Hamilton for this n-state matrix.
    for matrix in emissions.values():
        sequence, vector = [], state.joint
        for _ in range(n):
            joint = tuple(sum(matrix[i][j]*vector[j] for j in range(n)) for i in range(n))
            targets = work.target(joint)
            if sum(targets):
                sequence.append(tuple(q/sum(targets) for q in targets))
            vector = tuple(sum(silent[i][j]*vector[j] for j in range(n)) for i in range(n))
        if sequence and any(p != sequence[0] for p in sequence):
            raise FIncomplete("certificate_incomplete", "arrival timing is informative beyond the cell")
    conditional_entropies = [_mul(_r(sum(joint)), _entropy(tuple(q/sum(joint) for q in work.target(joint)))) for joint in eventual]
    if never_mass:
        conditional_entropies.append(_mul(_r(never_mass), _entropy(tuple(q/never_mass for q in never_target))))
    info = _add(_entropy(initial_target), _neg(_add(*conditional_entropies)))
    return _r(0), info, never_mass


def _rational_expression(expr):
    if expr.op == "rational":
        return expr.value
    if expr.op == "mul":
        value = _Fraction(1)
        for t in expr.args:
            value *= _rational_expression(t)
        return value
    if expr.op == "add":
        return sum(_rational_expression(t) for t in expr.args)
    if expr.op == "div":
        return _rational_expression(expr.numerator)/_rational_expression(expr.denominator)
    raise FIncomplete("certificate_incomplete", "symbolic prefix weights need a general tail checker")


def _ratio_rational(joint, probability):
    if joint.op == probability.op == "rational":
        return joint.value/probability.value
    raise FIncomplete("certificate_incomplete", "symbolic prefix posterior")


def _evaluation(work, costs, additional, *, trace, tails=()):
    root = work.root
    already = work.world.quantity(work.already, work.work)
    parts = tuple(InformationParts(already_received=already, additional=i,
        total_information=FQuantity(status="finite", exact=_add(work.already, i.exact) if i.exact is not None else None,
            bounds=_iadd(already.bounds, i.bounds), proof=None, reason=None)) for i in additional)
    Js = []
    for cost, part in zip(costs, parts):
        bounds = RationalInterval(cost.bounds.lower-part.total_information.bounds.upper,
                                  cost.bounds.upper-part.total_information.bounds.lower)
        exact = _add(cost.exact, _neg(part.total_information.exact)) if cost.exact is not None and part.total_information.exact is not None else None
        Js.append(FQuantity(status="finite", exact=exact, bounds=bounds, proof=None, reason=None))
    choice = work.world.soft_choice(tuple(Js), tuple(_Fraction(1) for _ in Js), root.gamma, work.work)
    names = tuple(a.id for a in root.candidates.candidates)
    normalization = NormalizationCertificate(problem_key=root.problem_key, measure=root.candidates.measure,
        admissible=names, excluded=(), Z=choice.Z.bounds,
        proof=ProofRef(name="finite_tree" if _finite_tree(work) else "fixed_policy_tail", version="1", args={}))
    conditions = (ContractValue(contract=_ContractRef("finite_tree" if trace != "prefix" and _finite_tree(work) else "fixed_policy_tail", "1"), value={"path": trace}),
        ContractValue(contract=_ContractRef("static_target_entropy_bound", "1"), value={"targets": work.targets}),
        ContractValue(contract=_ContractRef("finite_terminal_cost", "1"), value={"items": root.preferences}))
    certificate = FCertificate(problem_key=root.problem_key, root_key=root.root_key,
        method=root.method, arithmetic=_ContractRef("sui.f.exact_expression", "1"), budget=work.budget,
        trace=conditions, enclosures=_freeze({"J": _encode(tuple(Js)), "q": _encode(choice.q_star)}),
        residuals=tuple(_freeze(_encode(t)) for t in tails))
    evaluation = FEvaluation(root=root, candidates=names, expected_cost=costs, information=parts,
        G=tuple(Js), J=tuple(Js), q_star=choice.q_star, cumulative=choice.cumulative,
        normalization=normalization, tails=tails, certificate=certificate)
    _EVALUATIONS[id(evaluation)] = evaluation, _digest(evaluation)
    return evaluation


def _validate_evaluation(evaluation):
    world_state(evaluation.root)
    old = _EVALUATIONS.get(id(evaluation))
    if old is None or old[0] is not evaluation or old[1] != _digest(evaluation):
        raise FReplayMismatch("result_mismatch", "evaluation requires mathematical verification", fields=("/evaluation",))


def _no_decision(root, exc, *, progress=None):
    if isinstance(exc, FSpecificationMissing):
        outcome, reason = "rejected", "missing_contract"
    elif isinstance(exc, FModelFalsified):
        outcome, reason = "rejected", "model_falsified"
    elif isinstance(exc, FOutsideEvaluationType):
        outcome, reason = "rejected", exc.reason if exc.reason in ("NoAdmissibleCandidate", "information_divergent", "undefined_infinite_difference") else "OutsideEvaluationType"
    elif isinstance(exc, FNumericalRange):
        outcome, reason = "failed", "NumericalRange"
    else:
        outcome, reason = "incomplete", exc.reason
    if root is None:
        return NoDecision(attempt_id=None, root_key=None, outcome=outcome, reason=reason, detail=exc.detail, field=exc.field, proof=None, progress=None, resume=None)
    payload = _freeze({"root_key": root.root_key, "path": "recompute"})
    resume = ResumePoint(root_key=root.root_key, method=root.method, arithmetic=_ContractRef("sui.f.exact_expression", "1"),
        stage="f-a-recompute/1", trace_prefix=() if progress is None else _freeze(_encode(progress.certificate.trace)),
        state_digest=_digest(payload), state_payload=payload,
        previous_certificate=None if progress is None else progress.certificate)
    return NoDecision(attempt_id=None, root_key=root.root_key, outcome=outcome, reason=reason,
        detail=exc.detail, field=exc.field, proof=None, progress=progress, resume=resume if outcome == "incomplete" else None)


def _check_evaluation_contract(work):
    starts = tuple(work.world.predicate(op.start, PredicateSnapshot(model_ref=work.root.model_ref,
        E=work.root.E, K=work.root.K, quantities={}, dependencies=(), policy_position=None)).value
        for op in work.root.candidates.candidates)
    if all(v == "false" for v in starts):
        raise FOutsideEvaluationType("NoAdmissibleCandidate", "all starts proved false")
    if any(v != "true" for v in starts):
        raise FIncomplete("prerequisite_unavailable", "mixed admissibility needs an exclusion certificate")
    for name in ('static_target_entropy_bound','finite_terminal_cost'):
        if name not in work.proof_cache:
            work.proof_cache[name] = work.world.proof(name,work.root,work.budget)
        if work.proof_cache[name].status != 'proved':
            raise FIncomplete('certificate_incomplete',name,'/proofs')


def _observed_leaf_information(work, leaves):
    # Sum unnormalized joint laws in each E cell before conditioning.
    groups = {}
    for leaf in leaves:
        key = leaf.state.E_trace[-1].key
        mass, joint, posteriors = groups.setdefault(key, ([], [[] for _ in work.targets], []))
        mass.append(leaf.mass)
        target = work.target(leaf.state.joint)
        posteriors.append(target)
        for terms, q in zip(joint, target):
            terms.append(_mul(leaf.mass, _r(q)))
    terms = []
    for masses, joint, posteriors in groups.values():
        mass = _add(*masses)
        if all(p == posteriors[0] for p in posteriors):
            terms.append(_mul(mass, _kl(posteriors[0],work.initial_target)))
            continue
        posterior = tuple(_div(_add(*values), mass) for values in joint)
        # Symbolic soft-choice weights cancel within a conditional E cell.
        prior = work.initial_target
        kl = _add(*(_mul(p, ExactReal(op="log",arg=_div(p,_r(q)))) for p,q in zip(posterior,prior) if q and p != _r(0)))
        terms.append(_mul(mass, kl))
    return _add(*terms)

