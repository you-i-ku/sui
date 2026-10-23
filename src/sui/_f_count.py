"""有限の同時件数の法則と、件数の述語の連言による条件づけ (紙 F-b §2-5-19-1・19-6・19-8)。

入口 U (`f_update2.compute_finite_update`) の数学の芯。台帳・読み手・発行物を知らない純粋な計算で、
引数は U が一次事実から復号して照合した値。適用済みの状態は**主張の述語の連言そのもの** (M07)。
細分のセルと、連言を満たす行の集合は (法則, 述語) から作り直せる導出物で、ここでも持たない。
"""

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction
from itertools import product as _product

from .f import FInputError, FModelFalsified


@_dataclass(frozen=True, slots=True)
class Span:
    """件数を数える有限の区間。clock は時計の識別 (別の時計の同じ整数を同じ時刻にしない)。"""
    clock: str
    start_ns: int
    end_ns: int
    closure: str   # "[start,end)" / "(start,end]" / "[start,end]" / "(start,end)"

    def contains(self, t: int) -> bool:
        low = self.start_ns <= t if self.closure[0] == "[" else self.start_ns < t
        high = t <= self.end_ns if self.closure[-1] == "]" else t < self.end_ns
        return low and high

    def covers(self, other: "Span") -> bool:
        """other の全点が self に入るか (端点の開閉を含めて)。"""
        if other.clock != self.clock:
            return False
        lo_ok = (self.contains(other.start_ns) if other.closure[0] == "["
                 else self.start_ns <= other.start_ns)
        hi_ok = (self.contains(other.end_ns) if other.closure[-1] == "]"
                 else other.end_ns <= self.end_ns)
        return lo_ok and hi_ok


@_dataclass(frozen=True, slots=True)
class Predicate:
    """`lower ≤ Σ N(cell) ≤ upper` (§19-1 CountPredicate)。"""
    channel: str
    span: Span
    lower: int
    upper: int


@_dataclass(frozen=True, slots=True)
class Law:
    """検査済みの `sui.fb.finite_joint_count_law/1` の表。carriers は mass の列の順 (carrier 名の重複を除いた
    正準順 = 辞書順)。rows は正準 marks ((channel, time_ns, count) の昇順、同じ位置は合算) と carrier ごとの質量。"""
    carriers: tuple[str, ...]
    domains: dict
    rows: tuple[tuple[tuple, tuple], ...]


def check_law(carrier_by_state, channels, rows) -> Law:
    """法則の表を正規化して検査する。channels は {id: Span (domain)}、rows は [(marks, mass)]、
    marks は [(channel, time_ns, count)]。不正は FInputError (不足や独立へ丸めない)。"""
    carriers = tuple(sorted(set(carrier_by_state)))
    if not carriers:
        raise FInputError("shape", "no carrier", "/carrier_by_state")
    merged = {}
    for marks, mass in rows:
        if len(mass) != len(carriers) or any(not isinstance(q, _Fraction) or q < 0 for q in mass):
            raise FInputError("normalization", "mass", "/rows/mass")
        position = {}
        for channel, t, count in marks:
            domain = channels.get(channel)
            if domain is None or not domain.contains(t):
                raise FInputError("shape", "mark outside a declared channel domain", "/rows/marks")
            if type(count) is not int or count < 1:
                raise FInputError("shape", "count", "/rows/marks/count")
            position[(channel, t)] = position.get((channel, t), 0) + count
        key = tuple(sorted((c, t, n) for (c, t), n in position.items()))
        old = merged.get(key, (_Fraction(0),) * len(carriers))
        merged[key] = tuple(a + b for a, b in zip(old, mass))
    for i in range(len(carriers)):
        if sum((m[i] for m in merged.values()), _Fraction(0)) != 1:
            raise FInputError("normalization", "carrier mass does not sum to 1", "/rows/mass")
    return Law(carriers=carriers, domains=dict(channels), rows=tuple(sorted(merged.items())))


def check_predicate(law: Law, predicate: Predicate) -> None:
    domain = law.domains.get(predicate.channel)
    if domain is None or not domain.covers(predicate.span):
        raise FInputError("shape", "claim interval outside the channel domain", "/predicate")
    if type(predicate.lower) is not int or type(predicate.upper) is not int \
            or not 0 <= predicate.lower <= predicate.upper:
        raise FInputError("shape", "lower/upper", "/predicate")


def _noop(_kind, _domain=None):
    return None


def holds(marks, predicate: Predicate, work=_noop) -> bool:
    """work は論理の仕事の出来事を受ける口 (logical_work/1: 比較・加算を 1 回ずつ。規則の表 BUDGET_EVENT_KINDS)。"""
    total = 0
    for c, t, n in marks:
        # channel の一致は識別子の比較で、整数・有理数の算術ではない = logical_work/1 の出来事に数えない (規則の表の計数の規約)
        if c != predicate.channel:
            continue
        work("exact_compare", "integer"); work("exact_compare", "integer")   # 区間の両端 (時刻の整数)
        if predicate.span.contains(t):
            work("exact_add", "integer")
            total += n
    work("exact_compare", "integer"); work("exact_compare", "integer")
    return predicate.lower <= total <= predicate.upper


def mass(law: Law, predicates, work=_noop) -> tuple[_Fraction, ...]:
    """Z_c(連言): carrier ごとの、全部の述語を満たす行の質量。空の連言は全部 1。"""
    out = [_Fraction(0)] * len(law.carriers)
    for marks, row in law.rows:
        if all(holds(marks, p, work) for p in predicates):
            for _ in row:
                work("exact_add", "rational")
            out = [a + b for a, b in zip(out, row)]
    return tuple(out)


def satisfiable(predicates, work=_noop) -> bool:
    """件数の述語の連言に非負整数の割当があるか (§19-6、論理の矛盾とモデルの質量 0 を分ける)。
    channel ごとに端点で細分した点セル・開区間セルの件数を、そのセルを含む述語の upper の最小値を上限に
    厳密に探索する。別の channel の述語は件数を共有しないので独立に解ける。"""
    by_channel = {}
    for p in predicates:
        by_channel.setdefault((p.channel, p.span.clock), []).append(p)
    for group in by_channel.values():
        points = sorted({t for p in group for t in (p.span.start_ns, p.span.end_ns)})
        cells = [("point", t, t) for t in points] + [("open", a, b) for a, b in zip(points, points[1:])]
        cover = [[i for i, (kind, a, b) in enumerate(cells)
                  if (p.span.contains(a) if kind == "point" else p.span.start_ns <= a and b <= p.span.end_ns)]
                 for p in group]
        used = sorted({i for c in cover for i in c})
        bound = {i: min(p.upper for p, c in zip(group, cover) if i in c) for i in used}
        found = False
        for value in _product(*(range(bound[i] + 1) for i in used)):
            for _ in used:
                work("integer_extension")   # 候補の一座標への整数 1 個の割当と制約判定
            ok = True
            for p, c in zip(group, cover):
                for _ in c:
                    work("exact_add", "integer")
                work("exact_compare", "integer"); work("exact_compare", "integer")
                if not p.lower <= sum(value[used.index(i)] for i in c) <= p.upper:
                    ok = False
                    break
            if ok:
                found = True
                break
        if not found:
            return False
    return True


def condition(joint, evidence_mass, carrier_by_state, law: Law, applied, new: Predicate, work=_noop):
    """連言 A (applied) の下の joint に、新しい述語 E を条件づける (§19-1 の条件づけ)。
    L_c = Z_c(A∧E) / Z_c(A)。Z_c(A) = 0 の carrier は正しく再構成した既状態でも重み 0 のはずで、
    0/0 で重みを復活させない。全体の質量 0 は、連言が論理的に矛盾なら FInputError(measurement_conflict)、
    両立するのにモデルが質量 0 を置いたなら FModelFalsified (§19-6)。"""
    check_predicate(law, new)
    index = {c: i for i, c in enumerate(law.carriers)}
    before, after = mass(law, applied, work), mass(law, (*applied, new), work)
    weights = []
    for q, carrier in zip(joint, carrier_by_state):
        i = index[carrier]
        work("exact_compare", "rational")
        if before[i] == 0:
            work("exact_compare", "rational")
            if q != 0:
                raise FInputError("normalization", "state weight on a carrier the applied claims exclude", "/joint")
            weights.append(_Fraction(0))
        else:
            work("exact_multiply", "rational"); work("exact_divide", "rational")
            weights.append(q * after[i] / before[i])
    for _ in weights:
        work("exact_add", "rational")
    z = sum(weights, _Fraction(0))
    work("exact_compare", "rational")
    if z == 0:
        if not satisfiable((*applied, new), work):
            raise FInputError("measurement_conflict", "count claims are logically incompatible", "/observations")
        raise FModelFalsified("zero_evidence", "the model assigns zero mass to compatible claims")
    for _ in weights:
        work("exact_divide", "rational")
    work("exact_multiply", "rational")
    return tuple(w / z for w in weights), evidence_mass * z
