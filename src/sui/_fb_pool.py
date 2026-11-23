"""候補の並びと、候補を足す口 (紙 F-b K37 決定 1〜8)。公開の口は `FThreadHost.add_candidate`・`belief_pool`・`pool_belief`。

見立ては、起動の宣言が置いた候補の並びに対する 1 つの同時の信念 (候補 × 候補の中の状態)。起動の宣言の 1 枚は候補が
1 つの並び (並びの記録は起動の宣言そのもの、モデルは感じる側のモデル)。候補を足すと、新しい並び (前の並び ⊕ 新しい
候補) の記録と、その直和のモデル・読み手と、足した決定を保存する (前の記録は書き換えない)。今効いている並びは、
因果の境目に見える「足した」決定の鎖から、この 1 か所 (`resolve`) で解き、見立てを直す・考える・一歩を読む所が同じ
解決を使う。比べられない 2 つの足し・読めない記録は理由つきで止まり、前の並びへ黙って戻らない。
"""

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from numbers import Rational as _Rational

from . import f as _f
from . import fb as _fb
from . import fb_contracts as _c
from . import f_update2 as _u
from ._fb_boot import _front, _record
from ._fb_wire import encode as _encode
from .f_contracts import KNOWLEDGE_ORIGIN as _KNOWLEDGE_ORIGIN, MODEL_SOURCE as _MODEL_SOURCE
from .ids import RefKind as _RefKind
from .records import Decided as _Decided, Observed as _Observed, Payload as _Payload, \
    Prediction as _Prediction, Role as _Role


@_dataclass(frozen=True)
class Pool:
    """解いた並び。members は候補ごとの記述 (`f_update2.describe_candidate` の値に offset を足したもの、並びの順)。
    route は並びの観測を読む口 (感じる側の δ が名指す口の宣言の位置。どの候補の観測モデルもこの口のもの、K37 決定 6)、
    lineage は前の並びのモデル (古い順)、records は要求の入力に入れる並びとその参照の閉包 (`_closure`)、decision は
    足した決定 (最初の並びは None)。"""
    point: str
    model: str
    origin: str
    route: str | None
    members: tuple
    lineage: tuple
    records: frozenset
    decision: str | None

    @property
    def initial(self) -> bool:
        return self.decision is None


# 並びの候補の観測の見込みの型 (有限の核 K26 / 時刻を読む K38)。どちらで読むかは感じる側の δ が決める
_KINDS = {_c.SAVED_ACQUISITION_UPDATE: _fb.AcquisitionObservationModel,
          _c.SAVED_TIMED_ACQUISITION_UPDATE: _fb.TimedAcquisitionModel}


def _read(state, point):
    """記録の本文 (JSON)。読めなければ並びを解けない (名指しつき、待っても解けない)。"""
    try:
        return _u._json(state.ledger.record(point).body.content.as_json())
    except KeyError:
        raise _fb.CandidatePoolError(reason="unreadable_record", targets=(point,), retryable=False) from None


def _boot(state, point):
    plan = next((p for p in state.plans.values() if p.d == point), None)
    if plan is None or plan.declaration.perception is None or plan.points.get("origin") is None:
        raise _fb.CandidateInputError(reason="boot", field="/boot")
    return plan


def _seen(state, boundary):
    """境目 (保存済みの点の集合。None は今の置き場の頭) に因果的に見える点。"""
    if boundary is None:
        boundary = state.ledger.heads()
    try:
        boundary = frozenset(boundary)
        return state.ledger.ancestors(boundary) | boundary
    except (KeyError, TypeError):
        raise _fb.CandidateInputError(reason="boundary", field="/boundary") from None


DERIVED = "perception_model"   # 起動の計画の歩の名前: 最初の候補を展開した派生のモデル (K39 決定 8)


def boot_shortfall(ledger, d):
    """起動の宣言 d の最初の候補を候補の解決で解く (K39 決定 8・K39-b R1)。(候補の記述, None) か、解けなければ (None, 起動の
    計画の不足の語)。不足の語は "perception:candidate:<理由の語>:<名指し>..."。起動の計画はこれを、感じる側・考える側・
    一歩のどれより先に示す (派生のモデル・読み手を作らない)。"""
    try:
        return _u.initial_candidate(ledger, d), None
    except _u.Unresolved as exc:
        return None, ":".join(("perception:candidate", exc.reason, *exc.named))
    except _u._Issue as issue:
        return None, "perception:candidate:" + issue.code


def initial_model(plan):
    """最初の並びのモデル (K36 新しい決定 2・K39 決定 8): 起動の計画が派生のモデルを保存する歩を持てばその記録、無ければ起動の
    宣言の感じる側のモデル。並びのモデルを起動から読むのはここだけ (今効いている並びは `resolve`、最初の並びは
    `initial_pool` がこれを使う)。派生のモデルの歩がまだ保存されていなければ KeyError (宣言のモデルへ黙って戻らない)。"""
    if any(step.name == DERIVED for step in plan.steps):
        return plan.points[DERIVED]
    return plan.declaration.perception.value.model


def initial_pool(state, boot) -> Pool:
    """最初の並び = 起動の宣言の 1 枚 (候補が 1 つ)。候補は保存した起動の宣言から候補の解決 (`f_update2.initial_candidate`、
    入口 U と同じ 1 か所、K39 決定 8) で作る。点は起動の宣言、モデルは `initial_model`、読み手は起動の origin。保存済みの
    記録だけから決まる不変の値なので、起動ごとに 1 回だけ作る。"""
    known = state.initial_pools.get(boot.d)
    if known is not None:
        return known
    member, missing = boot_shortfall(state.ledger, boot.d)
    if member is None:   # 起動の計画が不足として示した宣言 (origin を作らないので、ふつうはここへ来ない)
        raise _fb.CandidatePoolError(reason=missing, targets=(boot.d,), retryable=False)
    args = _u._json(boot.declaration.perception.value.derivation.method.args)
    route = args.get("route") if isinstance(args, dict) else None
    model = initial_model(boot)
    pool = Pool(point=boot.d, model=model, origin=boot.points["origin"], route=route if isinstance(route, str) else None,
                members=(member,), lineage=(), records=frozenset({model}) | member["references"], decision=None)
    state.initial_pools[boot.d] = pool
    return pool


def _reason(issue) -> str:
    return "unreadable_record" if issue.code == "unresolved_reference" else issue.code


def resolve(state, boot, boundary) -> Pool:
    """境目に見える、その起動の「足した」決定の鎖から、今効いている並びを解く (K37 決定 3)。並びどうしの前後は、足した
    決定が名指す前の並び (足した時の境目で解いた並び) で決まる。同じ並びに足した決定が 2 つ見えれば比べられない
    (到着順・保存順・番号の大小で勝ちを作らない)。読めない記録は名指して止まる。"""
    added = [p for d, p in state.additions if d == boot.d]
    seen = _seen(state, boundary) if added else frozenset()   # 足した決定が無ければ境目の祖先をたどらない
    decisions = {p: _read(state, p) for p in added if p in seen}
    current, chain = boot.d, []
    while True:
        kids = sorted(p for p, value in decisions.items() if value["previous"] == current)
        if not kids:
            break
        if len(kids) > 1:
            raise _fb.CandidatePoolError(reason="incomparable_additions", targets=tuple(kids), retryable=False)
        chain.append(kids[0])
        current = decisions[kids[0]]["pool"]
    if not chain:
        return initial_pool(state, boot)
    try:   # 入口 U の `_pools` と同じ候補の解決 (K39 決定 8)
        content, members = _u.pool_candidates(state.ledger, current)
    except _u._Issue as issue:
        raise _fb.CandidatePoolError(reason=_reason(issue), targets=tuple(sorted(x for x in issue.evidence if isinstance(x, str))) or (current,),
                                     retryable=False) from None
    return Pool(point=current, model=content["model"], origin=content["origin"], route=content["route"],
                members=tuple(members), lineage=tuple(content["lineage"]),
                records=_closure(state, chain, decisions), decision=chain[-1])


def _closure(state, chain, decisions) -> frozenset:
    """並びとその参照の閉包 (要求の入力に入れるもの。入口 U は入力の中の並びの記録を全部、この中身で確かめる、K37 決定 3)。
    鎖の各並びについて: 足した決定・候補の記録・並びの記録・その直和のモデル・読み手・候補のモデル。仕事の読み手は親の
    閉包しか追わない (Prediction の参照を自動では追わない) ので、並びが参照するものはここで全部名指す。"""
    out = set()
    for decision in chain:
        point = decisions[decision]["pool"]
        content = _read(state, point)
        out |= {decision, decisions[decision]["candidate"], point, content["model"], content["origin"],
                *(m["model"] for m in content["members"])}
    return frozenset(out)


def public(pool) -> "_fb.BeliefPool":
    return _fb.BeliefPool(
        point=pool.point, model=pool.model,
        members=tuple(_fb.PoolMember(id=m["id"], model=m["model"], prior_weight=m["weight"], law=m["law"])
                      for m in pool.members),
        states=tuple(_fb.PoolState(candidate=m["id"], state=s["id"], target=s["target"], law=m["law"])
                     for m in pool.members for s in m["document"]["states"]))


def belief_pool(state, boot, boundary):
    with state.lock:
        return public(resolve(state, _boot(state, boot), boundary))


def pool_belief(state, boot, boundary):
    """境目の並びの最新の採用から、同時の信念・証拠の質量・候補ごとの重みと条件つきの見立てを返す (K37 決定 3〜5)。
    その並びの系列が境目に見える観測で止まっていれば理由と名指しつきで止まる (待っても解けない)。足した並びの作り直しが
    まだ採用されていなければ、待てば解ける止まり。最初の並びでまだ採用が無ければ、宣言の事前 (証拠の質量 1)。"""
    from . import _fb_update
    with state.lock:
        plan = _boot(state, boot)
        seen = _seen(state, boundary)
        pool = resolve(state, plan, boundary)
        update = next((p for p in state.updates.values() if p.boot is plan), None)
        stop = _fb_update.pool_stop(state, update, pool, seen) if update is not None else None
        if stop is not None:
            raise _fb.CandidatePoolError(reason=stop[0], targets=stop[1], retryable=False)
        head = _fb_update.pool_head(update, pool, seen) if update is not None else None
        if head is None:
            if not pool.initial:
                raise _fb.CandidatePoolError(reason="replay_pending", targets=(pool.point,), retryable=True)
            member, = pool.members
            joint = _f._decode(member["document"]["initial"], tuple[_f._Fraction, ...])
            mass, result = _Fraction(1), None
        else:
            result = _read(state, head)["result"]
            value = _read(state, result)["result"]
            from ._fb_time import is_result
            if is_result(value):   # 時刻を読む信念は有理数の joint を持たない。正本の照会の口で読む (K38 決定 5)
                raise _fb.TimeBeliefError(kind="unsupported", reason="a timed belief is read by belief_expression",
                                          targets=(result,))
            joint = _f._decode(value["joint"], tuple[_f._Fraction, ...])
            mass = _f._decode(value["evidence_mass"], _f._Fraction)
        candidates = []
        for m in pool.members:
            block = joint[m["offset"]:m["offset"] + m["size"]]
            weight = sum(block, _Fraction(0))
            candidates.append(_fb.CandidatePosterior(candidate=m["id"], weight=weight,
                                                     conditional=tuple(x / weight for x in block) if weight else None))
        return _fb.PoolBelief(pool=pool.point, adoption=head, result=result, joint=tuple(joint), evidence_mass=mass,
                              candidates=tuple(candidates))


def _alpha(alpha) -> _Fraction:
    """最初の重み α (K37 決定 8): 新しい並びの起点での新しい候補の事前確率。0 < α < 1 の有理数だけ (0 は育たない構造の 0、
    1 は前からの候補を 0 にする = S10 の操作)。隠れた既定値は置かない。"""
    if isinstance(alpha, bool) or not isinstance(alpha, _Rational):
        raise _fb.CandidateInputError(reason="alpha", field="/alpha")
    alpha = _Fraction(alpha)
    if not 0 < alpha < 1:
        raise _fb.CandidateInputError(reason="alpha", field="/alpha")
    return alpha


def _candidate(state, candidate, kind):
    """足す候補の形 (中身の読めるかは、その候補で観測を読む時に確かめる)。(モデルの document, 対応の pairs)。観測の見込みは
    感じる側の δ の読み方の型 kind (時刻を読む並びには時刻を読む見込みだけ、K38)。"""
    if not isinstance(candidate, _fb.BeliefCandidate) or not isinstance(candidate.id, str) or not candidate.id:
        raise _fb.CandidateInputError(reason="candidate", field="/candidate")
    if not isinstance(candidate.observation_model, kind):
        raise _fb.CandidateInputError(reason="candidate", field="/candidate/observation_model")
    correspondence = _u._json(candidate.correspondence)
    if not isinstance(correspondence, dict) or set(correspondence) != {"pairs"} \
            or not isinstance(correspondence["pairs"], list) \
            or any(not isinstance(p, list) or len(p) != 2 or not all(isinstance(x, str) for x in p)
                   for p in correspondence["pairs"]):
        raise _fb.CandidateInputError(reason="candidate", field="/candidate/correspondence")
    try:
        record = state.ledger.record(candidate.model)
    except (KeyError, TypeError):
        raise _fb.CandidateInputError(reason="candidate", field="/candidate/model") from None
    if not isinstance(record.body, _Prediction) or record.body.contract != _MODEL_SOURCE:
        raise _fb.CandidateInputError(reason="candidate", field="/candidate/model")
    document = _u._json(record.body.content.as_json()).get("document")
    try:
        from .f_model import f_model11_from_json
        f_model11_from_json(_f._dumps(document))
    except (_f.FInputError, _f.FSpecificationMissing):
        raise _fb.CandidateInputError(reason="candidate", field="/candidate/model") from None
    return document, correspondence["pairs"]


def add(state, boot, candidate, alpha, boundary):
    """候補を 1 つ足す (K37 決定 2・3・8)。入力 (α・候補の形・境目) を先に全部確かめ、合わなければ何も保存せずに
    CandidateInputError。足す候補が候補の解決で解けなければ TimeBeliefError (名指し、`_fb_time.unresolved_error`)。
    境目で前の並びを解き (解けなければ CandidatePoolError)、新しい並びの直和のモデルを作れる時だけ、
    候補の記録 → 直和のモデル → 読み手 → 並びの記録 → 足した決定 を 1 点ずつ保存する。足したことは観測に数えない
    (見立ての作り直しは更新の計画が足した決定をきっかけに行う)。"""
    alpha = _alpha(alpha)
    with state.lock:
        plan = _boot(state, boot)
        kind = _KINDS.get(plan.declaration.perception.value.derivation.method.contract)
        if kind is None:
            raise _fb.CandidateInputError(reason="perception", field="/boot")   # 並びで読めるのは取りに行きの列だけ
        document, pairs = _candidate(state, candidate, kind)
        seen_boundary = frozenset(state.ledger.heads() if boundary is None else boundary)
        _seen(state, seen_boundary)
        previous = resolve(state, plan, seen_boundary)
        if candidate.id in {m["id"] for m in previous.members}:
            raise _fb.CandidateInputError(reason="candidate_id", field="/candidate/id")
        members = [{**m, "weight": m["weight"] * (1 - alpha)} for m in previous.members]
        try:   # 足す候補も同じ候補の解決で解く。解けなければ名指して何も保存しない (K39 決定 8・K39-b R1)
            members.append(_u.describe_candidate(id=candidate.id, model=candidate.model, document=document,
                                                 observation=candidate.observation_model, pairs=pairs, weight=alpha))
        except _u.Unresolved as exc:   # 公開の解決の口と同じ名指し (何も保存しない)
            from ._fb_time import unresolved_error
            raise unresolved_error(exc) from None
        try:
            model_document = _u.direct_sum(members)
            from .f_model import f_model11_from_json
            f_model11_from_json(_f._dumps(model_document))
        except ValueError as exc:
            raise _fb.CandidateInputError(reason="pool:" + str(exc), field="/candidate") from None
        except (_f.FInputError, _f.FSpecificationMissing):
            raise _fb.CandidateInputError(reason="pool:model", field="/candidate") from None
        ledger = state.ledger
        parents = _front(ledger, seen_boundary | {plan.d})

        def save(body, kind, writer, parents):
            prepared = ledger.prepare(_record(state, body, kind, writer), parents)
            return ledger.write(prepared).cid

        def ids(points):   # 名札は点から (本文を読まない: 境目の保存の確認待ちの点を読みに行かない)
            return tuple(ledger.entry(p).id for p in sorted(points))
        cand = save(_Prediction(target="belief_candidate", about=ids({candidate.model}), basis=ids({candidate.model, plan.d}),
                                content=_Payload.json({"boot": plan.d, "candidate": _encode(candidate)}),
                                contract=_c.BELIEF_CANDIDATE), _RefKind.PREDICTION, _Role.MODEL, parents)
        model = save(_Prediction(target="belief_pool_model", about=ids({cand}),
                                 basis=ids({cand, *(m["model"] for m in members)}),
                                 content=_Payload.json({"document": model_document}), contract=_MODEL_SOURCE),
                     _RefKind.PREDICTION, _Role.MODEL, parents)
        from ._fb_core import mono_ns
        origin = save(_Observed(route="fb", content=_Payload.json({"model": model}), contract=_KNOWLEDGE_ORIGIN,
                                received_ns=mono_ns(state.clock)), _RefKind.OBSERVATION, _Role.MEMBRANE, parents)
        content = {"boot": plan.d, "previous": previous.point, "model": model, "origin": origin,
                   "route": previous.route, "lineage": [*previous.lineage, previous.model],
                   "members": [{"id": m["id"], "model": m["model"], "observation_model": _encode(m["observation"]),
                                "correspondence": {"pairs": m["pairs"]}, "prior_weight": _f._encode(m["weight"]),
                                "law": m["law"]} for m in members]}
        pool = save(_Prediction(target="belief_pool", about=ids({model}), basis=ids({cand, model, origin}),
                                content=_Payload.json(content), contract=_c.BELIEF_POOL),
                    _RefKind.PREDICTION, _Role.MODEL, _front(ledger, {origin}))
        uses = {cand, pool, model, origin, previous.point, candidate.model} | _front(ledger, seen_boundary)
        decision = save(_Decided(inputs=ids(uses), content=_Payload.json({
            "boot": plan.d, "candidate": cand, "pool": pool, "previous": previous.point, "alpha": _f._encode(alpha),
            "boundary": sorted(seen_boundary)}), contract=_c.CANDIDATE_ADDED),
            _RefKind.DECISION, _Role.MODEL, _front(ledger, seen_boundary | {plan.d, origin}))
        state.additions.append((plan.d, decision))
        return _fb.CandidateAddition(candidate=cand, pool=pool, decision=decision)
