"""有限の同時件数の法則と、件数の述語の連言による条件づけ (紙 F-b §2-5-19-1)。

信念の更新の入口 U の数学の芯。台帳・読み手・発行物を知らない純粋な計算で、引数は U が保存した
事実から復号した値。適用済みの状態は**主張の述語の連言そのもの**で、同じ証拠や重なる区間を
独立な尤度の積にしない (CE1)。連言を満たす行の集合は (法則, 述語) から毎回作り直す。
"""

from dataclasses import dataclass as _dataclass
from fractions import Fraction as _Fraction

from .f import FInputError


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
        """other の全点が self に入るか (端点の開閉を含めて)。別の時計の区間は入らない。"""
        if other.clock != self.clock:
            return False
        lo_ok = (self.contains(other.start_ns) if other.closure[0] == "["
                 else self.start_ns <= other.start_ns)
        hi_ok = (self.contains(other.end_ns) if other.closure[-1] == "]"
                 else other.end_ns <= self.end_ns)
        return lo_ok and hi_ok


@_dataclass(frozen=True, slots=True)
class Predicate:
    """`lower ≤ (span の中の channel の件数の和) ≤ upper` (§19-1 CountPredicate)。"""
    channel: str
    span: Span
    lower: int
    upper: int


@_dataclass(frozen=True, slots=True)
class Law:
    """検査済みの法則の表。carriers は mass の列の順 (carrier 名の重複を除いた辞書順)。rows は
    正準 marks ((channel, time_ns, count) の昇順、同じ位置は合算) と carrier ごとの質量。"""
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
    for marks, mass_row in rows:
        if len(mass_row) != len(carriers) or any(not isinstance(q, _Fraction) or q < 0 for q in mass_row):
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
        merged[key] = tuple(a + b for a, b in zip(old, mass_row))
    for i in range(len(carriers)):
        if sum((m[i] for m in merged.values()), _Fraction(0)) != 1:
            raise FInputError("normalization", "carrier mass does not sum to 1", "/rows/mass")
    return Law(carriers=carriers, domains=dict(channels), rows=tuple(sorted(merged.items())))


def check_predicate(law: Law, predicate: Predicate) -> None:
    """述語の区間が channel の domain の中にあり、0 ≤ lower ≤ upper の整数であること。"""
    domain = law.domains.get(predicate.channel)
    if domain is None or not domain.covers(predicate.span):
        raise FInputError("shape", "claim interval outside the channel domain", "/predicate")
    if type(predicate.lower) is not int or type(predicate.upper) is not int \
            or not 0 <= predicate.lower <= predicate.upper:
        raise FInputError("shape", "lower/upper", "/predicate")


def holds(marks, predicate: Predicate) -> bool:
    """1 つの行 (marks) が述語を満たすか。"""
    total = sum(n for c, t, n in marks if c == predicate.channel and predicate.span.contains(t))
    return predicate.lower <= total <= predicate.upper


def mass(law: Law, predicates) -> tuple[_Fraction, ...]:
    """Z_c(連言): carrier ごとの、全部の述語を満たす行の質量。空の連言は全部 1。"""
    out = [_Fraction(0)] * len(law.carriers)
    for marks, row in law.rows:
        if all(holds(marks, p) for p in predicates):
            out = [a + b for a, b in zip(out, row)]
    return tuple(out)


def condition(joint, evidence_mass, carrier_by_state, law: Law, applied, new: Predicate):
    """連言 A (applied) の下の joint に、新しい述語 E を条件づけて (joint, evidence_mass) を返す。
    状態 s の重みは q_s · Z_c(A∧E) / Z_c(A) (c は s の carrier)。A で質量 0 の carrier に重みが
    残っていれば FInputError (0/0 で重みを復活させない)。条件づけの後の全体の質量が 0 の場合
    (論理の矛盾か、モデルが質量 0 を置いたかの区別) は最初の輪の 1 周目では扱わない。"""
    check_predicate(law, new)
    index = {c: i for i, c in enumerate(law.carriers)}
    before, after = mass(law, applied), mass(law, (*applied, new))
    weights = []
    for q, carrier in zip(joint, carrier_by_state, strict=True):
        i = index[carrier]
        if before[i] == 0:
            if q != 0:
                raise FInputError("normalization", "state weight on a carrier the applied claims exclude", "/joint")
            weights.append(_Fraction(0))
        else:
            weights.append(q * after[i] / before[i])
    z = sum(weights, _Fraction(0))
    if z == 0:
        # ★ 一覧 §3「モデルではありえない報告」: 論理の矛盾とモデルの質量 0 を分ける (§19-6) のは 1 周の後
        raise NotImplementedError("zero evidence mass: 論理の矛盾とモデルの質量 0 の区別は最初の輪の 1 周の後")
    return tuple(w / z for w in weights), evidence_mass * z
