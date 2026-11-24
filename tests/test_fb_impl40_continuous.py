"""実装の係の小さい確かめ (K40 時計の部品、回転・幅・配分の連続の事前)。試験の係の試験ではない。紙 F-b K40 の定規のうち、連続の
事前の積分 (決定 7・13・14)・照会 (決定 15)・保証と作り直し・構造の 0 を、K38・K39 の試験の足場の上で確かめる。参照の値は
定規の閉じた式か、独立の数値積分 (scipy、照合の幅よりずっと小さい誤差) で作る。"""

from fractions import Fraction as Q
from math import exp

import pytest

from sui import fb, f_contracts as fc_, f_entry as fe, _fb_time as ft, _fb_clock as fc
from sui.rate import RateBudget
from test_fb_time_belief import script, E, T, assert_contains, rat, plus, minus, times, divide, expneg, negative_update
from test_fb_impl39_switch import mood, rig  # noqa: F401  (rig は fixture)
from test_fb_impl40_clock import clock, only_clock


def continuous(*, rotation=None, **kwargs):
    return clock(rotation=rotation, **kwargs)


def loose(tolerance=Q(1, 50), refinements=None, cells=None):
    return RateBudget(tolerance=tolerance, max_cells=cells, max_terms=None, max_refinements=refinements)


def sq(r, kind, budget=None, **kwargs):
    """スイッチの照会 (`fb.SwitchQuantity`) と時計の照会 (kind parameters・allocation は `fb.ClockQuantity`、部品 clk)。"""
    clock_kind = kind in ("parameters", "allocation")
    quantity = (fb.ClockQuantity(kind=kind, candidate=r.pool().members[0].id, family="f", part="clk", **kwargs)
                if clock_kind else fb.SwitchQuantity(kind=kind, candidate=r.pool().members[0].id, family="f", **kwargs))
    expression = r.expression()
    ask = r.host.query_clock_belief if clock_kind else r.host.query_switch_belief
    value = ask(belief=expression, quantity=quantity, budget=budget or loose())
    assert value.upper - value.lower <= (budget or loose()).tolerance
    assert r.host.verify_belief_value(belief=expression, value=value)
    return value


def first(r):
    r.observe(0)
    r.update()
    return r


def test_impl40_rotation_integral_matches_the_closed_form(rig):
    """定規「回転の積分が効く」: T = 1・m = 2・w = (1/2, 1/2)・f = (3/4, 1/4) は点、ρ は一様、時刻 1/2 の点の empty。時計オンの
    Z_on = e^{−R/4}·2(1 − e^{−R/2})/R (R = 1)、ρ = 0 に決め打ちした e^{−3/4} より大きい。時計オフは e^{−1/2}。"""
    r = first(only_clock(rig, script((2, 2, E)), parts=(continuous(),)).direct())
    on = times(expneg(Q(1, 4)), times(rat(2), minus(rat(1), expneg(Q(1, 2)))))
    assert_contains(sq(r, "switch", on=("clk",)), divide(on, plus(on, expneg(Q(1, 2)))))
    assert_contains(r.query("mass", tolerance=Q(1, 50)), divide(plus(on, expneg(Q(1, 2))), rat(2)))
    fixed = first(only_clock(rig, script((2, 2, E)), parts=(clock(),)).direct())
    assert sq(r, "switch", on=("clk",)).lower > sq(fixed, "switch", on=("clk",)).upper
    # 決定 14: 回転だけが連続なら、ρ を解析的に積分して指数多項式のまま厳密 (箱を作らない)
    spec = ft._spec(r.host._state, r.expression())
    W, _Z = ft.weights(spec)
    assert all(isinstance(w, ft.Poly) for w in W)


def test_impl40_zero_rate_makes_the_rotation_integral_exact(rig):
    """定規「回転の積分が効く」の R = 0: 率 0 の枝では尤度が θ によらず、積分は厳密に 1 (0/0 を作らない)。"""
    r = first(rig(script((2, 2, E)), parts=(continuous(),), rates=(Q(0), Q(0)), role=None, unit=Q(1, 4)).direct())
    assert r.query("mass").exact == 1
    assert sq(r, "switch", on=("clk",)).exact == Q(1, 2)


def test_impl40_width_integral_matches_an_independent_quadrature(rig):
    """定規「幅の積分が効く」: ρ = 0・f = (1/2, 1/2) は点、w_1 は [0, 1] の一様、時刻 1/2 の点の empty (R = 1)。参照は点検係 2 通目の
    別の式 Z = ∫_{1/2}^{1} [e^{−R/(4u)} + e^{−R} e^{R/(4u)}] du を独立に数値積分した値 (誤差 1e−10 以下)。"""
    ref, off = width_reference()
    r = first(only_clock(rig, script((2, 2, E)), parts=(width_part(),)).direct())
    value = sq(r, "switch", on=("clk",))
    assert float(value.lower) - 1e-9 <= ref / (ref + off) <= float(value.upper) + 1e-9


def test_impl40_a_full_turn_hides_every_continuous_shape_exactly(rig):
    """定規「1 周の終わりでは形が見えない」: 回転・幅・配分が全部連続でも、初期の件数 0・周期の終わりの 1 点の empty なら、どの θ
    でも尤度は e^{−RT} で、積分も厳密に e^{−RT} (時計の確信は事前のまま)。"""
    part = continuous(widths=None, kw=Q(1), shares=None, kf=Q(2), segments=((2, Q(1, 2)), (3, Q(1, 2))))
    r = first(only_clock(rig, script((4, 4, E)), parts=(part,)).direct())
    assert_contains(r.query("mass"), expneg(1))
    assert sq(r, "switch", on=("clk",)).exact == Q(1, 2)
    assert sq(r, "parameters", segments=(2,)).exact == Q(1, 2)


def test_impl40_clock_queries_follow_the_switch_rules(rig):
    """決定 15 ①: P(T ∈ A, m ∈ B, 事象 | h, M)。周期の候補 2 つ、全部の候補の整数周の終わりの取得では周期の確信が動かない (定規
    「周期と位置の見分け」)。時計オフの枝の T は潜在で事前のまま。② 1 周の割合: 点の形 f = (3/4, 1/4) の [0, 1/2) は 3/4、オフは
    1/2、1 周をまたぐ [3/4, 1/4) は区間の長さ 1/2 の重み。宣言に無い候補・形の誤りは名指して断る。"""
    r = first(only_clock(rig, script((8, 8, E)), parts=(clock(periods=(Q(1), Q(2))),)).direct())
    assert sq(r, "parameters", periods=(Q(1),)).exact == Q(1, 2)
    assert sq(r, "parameters", periods=(Q(1),), on=("clk",)).exact == Q(1, 4)
    assert sq(r, "parameters", periods=(), on=()).exact == 0
    assert sq(r, "allocation", lower=Q(0), upper=Q(1, 2)).exact == Q(1, 2) * Q(3, 4) + Q(1, 2) * Q(1, 2)
    assert sq(r, "allocation", lower=Q(3, 4), upper=Q(1, 4)).exact == Q(1, 2) * Q(1, 2) + Q(1, 2) * Q(1, 2)
    for kwargs, field in ((dict(kind="parameters", periods=(Q(3),)), "periods"),
                          (dict(kind="parameters", segments=(7,)), "segments"),
                          (dict(kind="allocation", lower=Q(0), upper=Q(1)), "lower"),
                          (dict(kind="allocation", lower=Q(0), upper=Q(1, 2), on=("clk",)), "on"),
                          (dict(kind="parameters", part="mood"), "part")):
        quantity = fb.ClockQuantity(**{"candidate": r.pool().members[0].id, "family": "f", "part": "clk", **kwargs})
        with pytest.raises(fb.TimeBeliefError) as error:
            r.host.query_clock_belief(belief=r.expression(), quantity=quantity, budget=loose())
        assert error.value.kind == "invalid" and error.value.field == field
    with pytest.raises(fb.TimeBeliefError) as error:   # 同じ意味の口を 2 つ持たない: スイッチの照会の口は時計の照会を受けない
        r.host.query_switch_belief(belief=r.expression(), quantity=fb.ClockQuantity(
            kind="parameters", candidate=r.pool().members[0].id, family="f", part="clk"), budget=loose())
    assert error.value.field == "quantity"


def test_impl40_continuous_share_is_the_prior_mean_when_the_data_hide_the_shape(rig):
    """決定 15 ② と決定 3: 回転が一様なら、どの形でも 1 周の割合の事前の期待値は区間の長さ。形が見えない取得 (周期の終わりの点)
    では事後も事前のままなので、割合の照会は 1/3 を含む (積分の上下界で)。"""
    r = first(only_clock(rig, script((4, 4, E)), parts=(continuous(),)).direct())
    value = sq(r, "allocation", lower=Q(1, 3), upper=Q(2, 3))
    assert value.lower <= Q(1, 3) <= value.upper


def width_reference():
    """定規「幅の積分が効く」の参照 (点検係 2 通目の別の式を独立に数値積分、誤差 1e−10 以下) と、時計オフの尤度 e^{−1/2}。"""
    from scipy.integrate import quad
    ref, err = quad(lambda u: exp(-1 / (4 * u)) + exp(-1) * exp(1 / (4 * u)), 0.5, 1, epsabs=1e-13)
    assert err < 1e-10
    return ref, exp(-0.5)


def width_part():
    return continuous(rotation=Q(0), widths=None, kw=Q(1), shares=(Q(1, 2), Q(1, 2)))


def test_impl40_budget_gives_incomplete_and_more_budget_narrows_from_the_same_root(rig):
    """決定 7: 予算 (精度を上げる回数・箱の数) で届かない照会は incomplete (モデルの誤りではない)。予算を増やすと同じ根から幅が
    縮み、真の値 (幅の定規の参照) を含む。"""
    r = first(only_clock(rig, script((2, 2, E)), parts=(width_part(),)).direct())
    quantity = fb.SwitchQuantity(kind="switch", candidate=r.pool().members[0].id, family="f", on=("clk",))
    for budget in (loose(Q(1, 10**6), refinements=1), loose(Q(1, 10**6), cells=40)):
        with pytest.raises(fb.TimeBeliefError) as error:
            r.host.query_switch_belief(belief=r.expression(), quantity=quantity, budget=budget)
        assert error.value.kind == "incomplete"
    wide, narrow = (r.host.query_switch_belief(belief=r.expression(), quantity=quantity, budget=loose(t))
                    for t in (Q(1, 5), Q(1, 100)))
    assert wide.root == narrow.root and narrow.upper - narrow.lower < wide.upper - wide.lower
    ref, off = width_reference()
    for value in (wide, narrow):
        assert float(value.lower) - 1e-9 <= ref / (ref + off) <= float(value.upper) + 1e-9


def test_impl40_continuous_units_round_trip_and_rebuild(rig):
    """正本 (決定 5): 連続の事前の枝の units は事前の宣言を持ち、保存・作り直しで同じ。前向きの更新 (2 回目の取得) の後も、原記録
    から作り直した照会が合う (verify は根から作り直す)。"""
    r = first(only_clock(rig, script((2, 2, E), (3, 3, E)), parts=(continuous(rotation=Q(0), widths=None, kw=Q(2)),)).direct())
    spec = ft._spec(r.host._state, r.expression())
    assert ft.decode_spec(ft._json(ft.encode_spec(spec))) == spec
    on = [u for u in spec["units"] if ft.continuous(u)]
    assert len(on) == 2 and on[0]["law"]["clock"]["segments"] == 2
    r.observe(1)
    r.update()
    sq(r, "switch", on=("clk",), budget=loose(Q(1, 20)))
    resolved = fb.resolve_belief_candidates(r.boot(), reader=r.ledger, registry=r.registry).candidates[0]
    assert resolved.clocks == (None, None, (Q(1), ()), (Q(1), ()))


def test_impl40_structural_zero_is_proved_for_continuous_units(rig):
    """構造の 0 (決定 7・K38 決定 6): 初期の件数 0 で時刻 0 の点の taken は、どの θ でも尤度 0 で、積分も形で 0 (区間の下界 0 と
    分けて証明する)。採用されずに model_falsified。"""
    r = only_clock(rig, script((0, 0, T)), parts=(continuous(widths=None, kw=Q(1)),)).direct()
    r.observe(0)
    negative_update(r, falsified=True)


def test_impl40_p_moves_the_mood_bit_through_a_continuous_clock(rig):
    """定規「p と共同」(★ K39): 調子の部品と連続の時計 (回転が一様) の族。時刻 1/2 の empty は時計のオンを支持し
    (Z_on = e^{−R/4}·2(1 − e^{−R/2})/R > e^{−R/2})、p を通して調子のオンの見込みを上げる (手計算で約 0.385、時計の部品の無い
    族 = 決定 10 ① の K39 は約 0.362)。p の Beta の成分の数は取得の回数で増えない (2 部品 → 4 成分)。"""
    r = first(rig(script((2, 2, E)), rates=(Q(4), Q(4)), parts=(mood(), continuous()), unit=Q(1, 4)).direct())
    plain = first(rig(script((2, 2, E)), rates=(Q(4), Q(4)), parts=(mood(),), unit=Q(1, 4)).direct())
    assert sq(r, "switch", on=("c",), budget=loose(Q(1, 100))).lower > plain.sq("switch", on=("c",)).upper
    mixture = r.host.p_distribution(belief=r.expression(), candidate=r.pool().members[0].id, family="f",
                                    budget=loose(Q(1, 20)))
    assert [(c.a, c.b) for c in mixture.components] == [(1, 3), (2, 2), (2, 2), (3, 1)]


def test_impl40_integral_bounds_contain_and_narrow():
    """積分の上下界の部品 (決定 7・13): Beta の積の正規化定数、周辺の下側の確率の上界、箱を増やすと縮む上下界が真の値を含む。"""
    from math import gamma
    num = fc.Num(40)
    lo, hi = num.dirichlet_norm([Q(1, 2), Q(3, 2), Q(2)], [Q(1, 2), Q(3, 2), Q(2)])
    true = gamma(4) / (gamma(0.5) * gamma(1.5) * gamma(2))
    assert float(lo) <= true <= float(hi) and hi - lo < Q(1, 10**9)
    assert num.lower_tail(Q(1, 10), Q(1), Q(1)) >= Q(1, 10)
    def unit(**clock):
        return {"index": 0, "failure": None, "disconnection": None,
                "law": {"kind": "poisson", "rate": Q(1), "origin_ns": 0, "time_unit": Q(1, 10), "initial_count": 0,
                        "clock": {"period": Q(1), "segments": 2, "rotation": Q(0), "widths": [Q(1, 2), Q(1, 2)],
                                  "width_concentration": None, "shares": [Q(3, 4), Q(1, 4)], "share_concentration": None,
                                  **clock}}}
    entries = [{"kind": "acquisition", "before_ns": 5, "after_ns": 5, "cursor": 0, "symbol": "empty", "point": "x"}]
    rotation = fc.Integral(unit(rotation=None), entries, 5, None)   # 決定 14: 厳密
    lo, hi = rotation.table(fc.Num(64)).at(fc.FIRST_LEVEL)
    true = exp(-0.25) * 2 * (1 - exp(-0.5))
    assert rotation.exact is not None and hi - lo < Q(1, 10**18) and abs(float(lo) - true) < 1e-14
    integral = fc.Integral(unit(widths=None, width_concentration=Q(1), shares=[Q(1, 2), Q(1, 2)]), entries, 5, None)
    ref, _off = width_reference()
    widths, table = [], integral.table(fc.Num(64))
    for n in (32, 128, 512):
        lo, hi = table.at(n)
        assert float(lo) - 1e-12 <= ref <= float(hi) + 1e-12
        widths.append(hi - lo)
    assert widths[0] > widths[1] > widths[2]


def test_impl40_boxes_split_only_the_coordinates_the_integrand_reads():
    """決定 14 (解析的に先に計算できる所は先に): 被積分の量が依らない座標の箱を割らない。① ρ・w が点なら、f は読む位相で係数が
    同じ区切りの和だけが効き、和は Dirichlet(κ_f Σw) (集約): w = (1/3, 1/3, 1/3)・κ_f = 3/2・時刻 1/3 の点の empty は f_1 ~
    Beta(1/2, 1) の 1 次元 (尤度 e^{−f_1})。区間の中を読む取得に触れる区切りはまとめない。② 尤度が θ によらない (周期の終わりの点)
    なら、割合の照会は ρ が一様でどの w・f でも尤度 × 区間の長さで厳密。"""
    from scipy.integrate import quad

    def unit(**clock):
        return {"index": 0, "failure": None, "disconnection": None,
                "law": {"kind": "poisson", "rate": Q(1), "origin_ns": 0, "time_unit": Q(1, 30), "initial_count": 0,
                        "clock": {"period": Q(1), "segments": 3, "rotation": Q(0), "widths": [Q(1, 3)] * 3,
                                  "width_concentration": None, "shares": None, "share_concentration": Q(3, 2), **clock}}}

    def read(b, a, symbol="empty"):
        return {"kind": "acquisition", "before_ns": b, "after_ns": a, "cursor": 0, "symbol": symbol, "point": "x"}
    first = fc.Integral(unit(), [read(10, 10)], 10, None)
    assert first.groups == ((0,), (1, 2)) and first.dims == [("f", 0)]
    ref = quad(lambda x: x ** -0.5 * exp(-x), 0, 1, epsabs=1e-13)[0] / 2   # B(1/2, 1) = 2
    lo, hi = first.table(fc.Num(64)).at(512)
    assert float(lo) - 1e-12 <= ref <= float(hi) + 1e-12 and hi - lo < Q(1, 100)
    assert fc.Integral(unit(), [read(10, 10), read(13, 17)], 17, None).groups == ((0,), (1,), (2,))   # 区間が区切り 2 に触れる
    assert fc.Integral(unit(), [read(5, 5)], 5, None).groups == ((0,), (1, 2))   # 区切り 1 の中の点: 和 f_2 + f_3 だけ
    whole = unit(rotation=None, widths=None, width_concentration=Q(2, 3))
    share = fc.Integral(whole, [read(30, 30)], 30, ("share", Q(1, 17), Q(2, 17)))
    assert share.exact is not None and share.exact == ft.Poly({Q(1): Q(1, 17)})
    assert not share.blind and fc.Integral(whole, [read(30, 30)], 30, None).blind


def test_impl40_thinking_side_evaluates_the_continuous_belief(rig):
    """決定 12: 考える側 (F-a の評価・選択) が連続の事前の信念を使う。joint は積分を含む比 (版つきの積分の式 integral) で、選択の
    情報量・G・方策の確率を、保存した厳密式から作り直して上下界に包める。一歩の結果は状態だけを読むので、情報量は
    I(Q; Y | h) = h((1 + p)/2) − (1 − p) log 2 (p = P(A | h)、知る対象は状態ごとに違う)。式は積分を値で名指す (ハッシュだけでない)。"""
    from math import log
    part = continuous(rotation=Q(0), widths=None, kw=Q(2))
    r = rig(script((2, 2, E)), parts=(part,), rates=(Q(1), Q(2)), role=None, unit=Q(1, 4), thinking=True).direct()
    r.observe(0)
    expression = r.update()
    spec = ft._spec(r.host._state, expression)
    q = ft.joint(spec)
    assert any(isinstance(x, ft.IntegralRatio) and x.num.leaves for x in q)
    formula = next(x for x in q if isinstance(x, ft.IntegralRatio) and x.num.leaves).exact_real()
    assert all(x in str(formula) for x in ('"name":"sui.fb.clock_integral"', '"version":"1"', '"entries"'))
    selected = r.think()
    values = r.host.query_selection(selection=selected.cid, budget=loose(Q(1, 20)))
    assert values.belief_root == expression.root
    p = r.query("state", state="A", tolerance=Q(1, 20))

    def info(x):
        y = (1 + x) / 2
        return -(y * log(y) + (1 - y) * log(1 - y)) - (1 - x) * log(2)
    grid = [info(float(p.lower) + (float(p.upper) - float(p.lower)) * k / 50) for k in range(51)]
    peek = values.candidates.index("peek")
    value = values.information[peek]
    assert float(value.lower) - 1e-9 <= max(grid) and min(grid) <= float(value.upper) + 1e-9


def rotation_spec(targets, at_ns):
    """Codex sui-open-world 12 通目 F1 の反例の正本: 状態 A・B の率 (1, 2)、時計オンの枝で w = (1/2, 1/2)・f = (3/4, 1/4) は点、
    回転 ρ は一様、初期の件数 0 から時刻 at_ns/10 の点の empty。"""
    def law(rate):
        return {"kind": "poisson", "rate": rate, "origin_ns": 0, "time_unit": Q(1, 10), "initial_count": 0,
                "clock": {"period": Q(1), "segments": 2, "rotation": None, "widths": [Q(1, 2), Q(1, 2)],
                          "width_concentration": None, "shares": [Q(3, 4), Q(1, 4)], "share_concentration": None}}
    units = [{"index": i, "candidate": "m", "state": s, "prior": Q(1, 2), "law": law(rate), "failure": None,
              "disconnection": None, "branch": [1]}
             for i, (s, rate) in enumerate((("A", Q(1)), ("B", Q(2))))]
    entries = [{"kind": "acquisition", "before_ns": at_ns, "after_ns": at_ns, "cursor": 0, "symbol": "empty",
                "point": "x"}]
    return {"units": units, "entries": entries, "terminal_ns": at_ns}


def peek_information(spec, targets, tolerance):
    """結果が状態を名指す一歩 (Y = S) の I(Q; Y | h) を、考える側の評価器 (`_fb_time.information`) の式から包む。"""
    from sui import f
    q = ft.joint(spec)
    expr = ft.information(targets, [(q[0], Q(0)), (Q(0), q[1])])
    return expr, f._ExpressionWork(loose(tolerance), precision=tolerance).enclose(expr)


def f1_reference():
    """F1 の反例の I(Q; Y | h) の独立の数値積分 (scipy): 半周の高い区切りとの重なりで累積の率 x(ρ) は [1/4, 3/4] の一様 (密度 2)、
    L_A = e^{−x}、L_B = e^{−2x}。I = h(P(A | h)) − E_ρ[h(P(A | ρ, h))]。"""
    from math import exp, log
    from scipy.integrate import quad
    A, B = (lambda x: exp(-x) / 2), (lambda x: exp(-2 * x) / 2)
    Z = quad(lambda x: 2 * (A(x) + B(x)), 0.25, 0.75, epsabs=1e-14)[0]
    p = quad(lambda x: 2 * A(x), 0.25, 0.75, epsabs=1e-14)[0] / Z
    phi = (lambda a, b: (a + b) * log(a + b) - a * log(a) - b * log(b))
    return -(p * log(p) + (1 - p) * log(1 - p)) - quad(lambda x: 2 * phi(A(x), B(x)), 0.25, 0.75, epsabs=1e-14)[0] / Z


def test_impl40_rotation_only_lumped_target_information_is_the_theta_integral():
    """Codex 12 通目 F1 (high) の反例を値で: 回転だけ連続・元の知る対象が A・B をまとめる・半周期後の empty。尤度の積分は厳密な
    指数多項式に戻るが、P(S | ρ, h) は ρ に依るので、I(Q; Y | h) は θ の積分 (情報量の積分の項) で、有限の重みに畳んだ形
    (知る対象 1 つ → 0) より厳密に大きい。精度を上げると同じ式から幅が縮む。"""
    lumped = rotation_spec(("x", "x"), 5)
    assert all(isinstance(w, ft.Poly) for w in ft.weights(lumped)[0])   # 照会の数は指数多項式のまま (決定 14)
    ref = f1_reference()
    widths = []
    for tolerance in (Q(1, 2**10), Q(1, 2**20)):
        expr, value = peek_information(lumped, ("x", "x"), tolerance)
        assert '"name":"sui.fb.clock_information"' in str(expr)
        assert float(value.lower) - 1e-12 <= ref <= float(value.upper) + 1e-12
        widths.append(value.upper - value.lower)
    assert value.lower > 0 and widths[1] < widths[0] and widths[1] <= Q(1, 2**20)


def test_impl40_information_falls_back_to_finite_weights_only_when_proved():
    """評価器の特別な場合: 知る対象が状態ごとに違う (Q が S を決める)、または 1 周の終わりの empty (尤度が θ によらないと証明
    できる) なら、P(Y | Q, h) は θ によらず、評価器は有限の重みの形に落ちる (`information` が None)。まとめた知る対象で尤度が
    θ に依る時だけ積分の項になる。知る対象の周辺だけを持つ道 (路の表・尾・吸収) の入口は、その時だけ名指して止める。"""
    def cells(spec):
        q = ft.joint(spec)
        assert all(isinstance(x, ft.IntegralRatio) and x.num.leaves for x in q)   # θ とのつながりを持ったまま渡す (決定 12)
        return q, [(q[0], Q(0)), (Q(0), q[1])]
    q, c = cells(rotation_spec(("x", "y"), 5))
    assert ft.information(("x", "y"), c) is None and not ft.lumped(("x", "y"), q)
    q, c = cells(rotation_spec(("x", "x"), 10))
    assert ft.information(("x", "x"), c) is None and not ft.lumped(("x", "x"), q)
    q, c = cells(rotation_spec(("x", "x"), 5))
    assert ft.information(("x", "x"), c) is not None and ft.lumped(("x", "x"), q)
    # 結果が状態を見分けない一歩 (列が比例) は、まとめていても P(Y | Q, h) が θ によらない
    assert ft.information(("x", "x"), [(q[0] * Q(1, 2), q[1] * Q(1, 2)), (q[0] * Q(1, 2), q[1] * Q(1, 2))]) is None


def test_impl40_width_continuous_lumped_information_is_bounded_by_boxes():
    """幅が連続 (w・f は箱) の時も同じ評価器: 箱ごとに事前の質量 × [φ(c の下端), φ(c の上端)] で包み、箱を増やすと縮む。値は
    0 と log 2 の間で、有限の重みに畳んだ形 (0) より大きいことを箱の下界で示せる。"""
    from math import log
    from sui import _fb_clock as fc
    spec = rotation_spec(("x", "x"), 5)
    for u in spec["units"]:
        u["law"]["clock"] = {**u["law"]["clock"], "rotation": Q(0), "widths": None, "width_concentration": Q(1)}
    q = ft.joint(spec)
    expr = ft.information(("x", "x"), [(q[0], Q(0)), (Q(0), q[1])])
    formula = next(x for x in _nodes(expr) if x.op == "integral" and "clock_information" in x.formula).formula
    integral = ft._formula_integral(formula)
    assert isinstance(integral, fc.Information) and not integral.rotation and integral.positive()
    coarse, fine = integral.table(fc.Num(64)).at(32), integral.table(fc.Num(64)).at(1024)
    assert 0 <= coarse[0] <= fine[0] <= fine[1] <= coarse[1] <= log(2) and fine[0] > 0
    assert fine[1] - fine[0] < coarse[1] - coarse[0]


def _nodes(expr):
    yield expr
    for name in ("arg", "numerator", "denominator"):
        child = getattr(expr, name, None)
        if child is not None:
            yield from _nodes(child)
    for child in getattr(expr, "args", None) or ():
        yield from _nodes(child)


@pytest.mark.parametrize("case", ["structural-zero", "structural-positive", "identity", "separated", "unproved"])
def test_impl40_compare_exact_separates_proofs_from_the_budgeted_unproved(case):
    """決定 12 の比較の 4 つの区別 (`f.compare_exact`): 幅の積分の項 I (θ を積分した証拠の分の重み) について、構造の 0 (0 × I)・
    構造の正 (exp(I) > 0)・同じ正準な式 (JSON から戻した写し)・数値で分けた大小 (I > I の下界の半分)・予算 (箱 1 つ) の中で
    分けられない (unproved は 0 や偽の証明にしない)。"""
    from sui import f
    spec = rotation_spec(("x", "y"), 5)
    for u in spec["units"]:   # 幅を連続の事前に (積分の項が残る形)
        u["law"]["clock"] = {**u["law"]["clock"], "rotation": Q(0), "widths": None, "width_concentration": Q(1)}
    q = ft.joint(spec)
    assert all(isinstance(x, ft.IntegralRatio) for x in q)
    I = q[0].exact_real()
    zero = f.ExactReal(op="rational", value=Q(0))
    roomy = RateBudget(tolerance=Q(1, 2**16), max_cells=None, max_terms=None, max_refinements=None)
    left, right, budget, expected = I, zero, roomy, ("separated", 1)
    if case == "structural-zero":
        left, expected = f.ExactReal(op="mul", args=(zero, I)), ("structural", 0)
    elif case == "structural-positive":
        left, expected = f.ExactReal(op="exp", arg=I), ("structural", 1)
    elif case == "identity":
        right = fe.f_from_json(fe.f_json(I), contract=fc_.VALUE_FACTS)
        expected = ("identity", 0)
    else:
        right = f.ExactReal(op="rational", value=Q(1, 4))   # 率の小さい A の重みが大きいので q_A ≥ 1/2 > 1/4
        if case == "unproved":
            budget = RateBudget(tolerance=Q(1, 2**160), max_cells=1, max_terms=1, max_refinements=1)
            expected = ("unproved", None)
    answer = f.compare_exact(left, right, reader=None, registry=None, budget=budget)
    assert isinstance(answer, f.ExactComparison) and (answer.kind, answer.order) == expected
    assert (answer.proof is None) == (answer.kind == "unproved")


def test_impl40_entropy_bound_proof_rests_on_the_state_reading_kernel():
    """K40-R3 (commit 前のレビュー 1 通目): static_target_entropy_bound の証明の根拠は「知る対象が有限」ではなく、一歩の結果の核が
    有限の状態 S だけを読む (θ を持たない S の上の有理数の行列、決定 9 の非干渉) こと: Y ⟂ Q | S から I(Q; Y | h) ≤ H(S | h)。
    共同の信念が θ の積分 (連続の Q) でも、核が S の上の有理数の行列なら proved で、根拠は S の一覧と S だけを読む核。核の値が
    θ に依る (有理数でない)・S の上の行列でない時は proved にしない (前提を確かめずに出さない)。"""
    from types import SimpleNamespace
    from sui import f
    spec = rotation_spec(("x", "x"), 5)
    joint = tuple(ft.joint(spec))
    assert all(isinstance(x, ft.IntegralRatio) for x in joint)   # 連続の Q を評価する信念

    def work(matrix):
        outcome = SimpleNamespace(matrix=matrix)
        return SimpleNamespace(data={"states": [{"id": "a", "target": "x"}, {"id": "b", "target": "x"}]},
                               initial_joint=joint, kernels={"peek": SimpleNamespace(outcomes=(outcome,))})
    evidence = {}
    assert f._state_reading_bound(work(((Q(1), Q(0)), (Q(0), Q(1)))), evidence)
    assert evidence == {"states": ("a", "b"), "state_reading_kernels": ("peek",)}
    assert not f._state_reading_bound(work(((joint[0], Q(0)), (Q(0), Q(1)))), {})   # 核が θ に依る
    assert not f._state_reading_bound(work(((Q(1),),)), {})                          # S の上の行列でない


def test_impl40_log_lower_bound_never_exceeds_the_true_log():
    """K40-R1 (commit 前のレビュー 1 通目) の反例: u = 2^−20、z = u − u³/3 + u⁵/15、x = (1 + z)/(1 − z) の ln x = 2 atanh(z)。前の
    手書きの級数は上に丸めた項を下界にも足し、下界 2u = 2^−19 (真の値より大きい) を返した。参照は試験の中の独立の有理数の級数
    2 Σ_{k<4} z^{2k+1}/(2k+1) と剰余の上界 2 z⁹ / (9 (1 − z²)) (真の値は [2S, 2(S + 剰余)] の中)。時計の log は F-a の数の仕組み
    (`Num`) で、精度を上げても下界は真の値を超えない。"""
    u = Q(1, 2**20)
    z = u - u**3 / 3 + u**5 / 15
    x = (1 + z) / (1 - z)
    S = sum(z**(2 * k + 1) / (2 * k + 1) for k in range(4))
    true_lower, true_upper = 2 * S, 2 * (S + z**9 / (9 * (1 - z * z)))
    assert true_upper < Q(1, 2**19)   # 前の実装の下界 2u は真の値の外
    for bits in (64, 128):
        lo, hi = fc.Num(bits).log(x)
        assert lo <= true_upper and true_lower <= hi and hi - lo <= Q(1, 2**(bits - 8))


def exp_series(x, terms):
    """試験の中の独立の有理数の級数: 0 < x ≤ 1 の exp(x) の [Σ_{k<n} x^k/k!, 同じ和 + 剰余の上界 x^n/n! / (1 − x/(n+1))]。"""
    term, total = Q(1), Q(0)
    for k in range(terms):
        total += term
        term = term * x / (k + 1)
    return total, total + term / (1 - x / (terms + 1))


def test_impl40_exp_lower_bound_never_exceeds_the_true_exp():
    """K40-R1 (各項・和・剰余が最後の丸めの前から真の値を包む) の exp: 引数は格子 2^−(bits+8) に外向きに丸めてから F-a の exp
    へ渡す (下界は下へ・上界は上へ)。格子の点のすぐ上の引数 x = 点 + 2^−(bits+8)/1000 では、上に丸めると引数がほぼ格子 1 つ分
    大きくなり、exp の下界が真の値を超えうる (F-a の和の格子 2^−(bits+4) の点が exp(x) と exp(上に丸めた x) の間に入る時)。
    1/2・3/4 の近くの格子の点 64 個ずつで、下界は真の値 (独立の級数の上界) を超えず、上界は真の値 (級数の下界) を下回らない。"""
    for bits in (40, 64):
        step = Q(1, 2**(bits + 8))
        num = fc.Num(bits)
        for base in (Q(1, 2), Q(3, 4)):
            for k in range(64):
                x = base + k * step + step / 1000
                lo, hi = num.exp(x)
                true_lower, true_upper = exp_series(x, 90)
                assert lo <= true_upper and true_lower <= hi and hi - lo <= Q(1, 2**(bits - 2)), (bits, base, k)


def test_impl40_tiny_beta_normalizer_raises_precision_instead_of_dividing_by_zero(rig):
    """K40-R2 (commit 前のレビュー 1 通目) の反例: T = 1・m = 2・ρ = 0・f = (1/2, 1/2) は点、w ~ Dirichlet(100, 100)、基準の率 1、
    初期の件数 0、時刻 1/2 の点の empty。B(100, 100) ≤ 2^−198 で、前の 64 bit 固定の精度では下界が 0 になり、その下界で割って
    ZeroDivisionError になった。今は正の下界が証明できるまで予算の中で精度を上げ (`Num.inverse` → `_EnclosureShort`)、照会は値か
    incomplete を返す。数の部品でも、64 bit では精度の不足を名指し、精度を上げると B の正の下界が真の値 (lgamma) を包む。"""
    from math import lgamma, log
    from sui.f import _EnclosureShort
    with pytest.raises(_EnclosureShort):
        fc.Num(64).inverse(*fc.Num(64).beta(Q(100), Q(100)))
    lo, hi = fc.Num(fc.precision_bits(Q(1, 50), 2)).beta(Q(100), Q(100))
    true = 2 * lgamma(100) - lgamma(200)
    assert 0 < lo and log(lo) - 1e-9 <= true <= log(hi) + 1e-9
    part = continuous(rotation=Q(0), widths=None, kw=Q(100), shares=(Q(1, 2), Q(1, 2)))
    r = first(only_clock(rig, script((2, 2, E)), parts=(part,)).direct())
    quantities = ((r.host.query_belief, fb.BeliefQuantity(kind="mass")),
                  (r.host.query_switch_belief, fb.SwitchQuantity(kind="switch", candidate=r.pool().members[0].id,
                                                                 family="f", on=("clk",))))
    answered = 0
    for ask, quantity in quantities:
        try:
            value = ask(belief=r.expression(), quantity=quantity, budget=loose(Q(1, 10), refinements=3))
        except fb.TimeBeliefError as error:
            assert error.kind == "incomplete"
            continue
        answered += 1
        assert value.upper - value.lower <= Q(1, 10)
    assert answered   # 予算の中で精度を上げて、少なくとも 1 つは値で答える (0 で割って止まらない)


class _Turns:
    """照会をスレッドで走らせ、割り込みの順を試験の中で決める (スレッドの時刻に頼らない)。名前つきの照会は、積分の箱の評価
    (`_fb_clock.Integral._evaluate`) の stop 回目で止まり、試験が進めるまで待つ。動くのはいつも 1 つだけ。"""

    def __init__(self, monkeypatch):
        import threading
        self.local, self.stops, self.calls, self.seen = threading.local(), {}, {}, {}
        original = fc.Integral._evaluate

        def hooked(integral, *args):
            name = getattr(self.local, "name", None)
            if name is not None:
                self.seen.setdefault(name, set()).add(id(integral))
                self.calls[name] = self.calls.get(name, 0) + 1
                stop, here, go = self.stops[name]
                if self.calls[name] == stop:
                    here.set()
                    assert go.wait(120)
            return original(integral, *args)
        monkeypatch.setattr(fc.Integral, "_evaluate", hooked)

    def start(self, name, ask, stop=0):
        """照会 ask を名前 name で始め、stop 回目の評価で止まるか終わるまで待つ。返すのは、進めて答え (値なら (lower, upper)、
        incomplete なら理由) を受け取る関数。ほかの例外 (ValueError など) はそこで上げる。"""
        import threading
        here, go, box = threading.Event(), threading.Event(), {}
        self.stops[name] = (stop, here, go)

        def run():
            self.local.name = name
            try:
                value = ask()
                box["answer"] = value.lower, value.upper
            except fb.TimeBeliefError as error:
                box["answer"] = (error.kind, error.reason)
            except BaseException as error:
                box["error"] = error
            finally:
                here.set()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        assert here.wait(120)

        def finish():
            go.set()
            thread.join(120)
            if "error" in box:
                raise box["error"]
            return box["answer"]
        return finish


def test_impl40_queries_at_different_precisions_do_not_share_a_table(rig, monkeypatch):
    """K40-R5 (commit 前のレビュー 2 通目) の割り込みの順: T = 1・m = 2・ρ = 0・w ~ Dirichlet(1, 1)・f = (1/2, 1/2)、時刻 1/2 の点の
    empty の根で、数の精度の違う 2 つの mass の照会 (A は精度 1/50 = 64 bit から、B は 2^−50 = 68 bit からで予算の中では届かず
    incomplete) が同じ積分を使う。A を箱の評価の途中 (1 回目・半ば・最後) で止め、① B を終わりまで進めてから A を進める、② B も
    最初の評価で止めたまま A を終わらせてから B を進める。どの順でも、どちらも値か incomplete で (ValueError などで止まらない)、
    答えは 1 つずつ回した時と同じ (紙 F-b K40-k: ある精度の照会が別の精度の表を消さない・途中で止まった表を他の照会が使わない)。"""
    part = continuous(rotation=Q(0), widths=None, kw=Q(1), shares=(Q(1, 2), Q(1, 2)))
    r = first(only_clock(rig, script((2, 2, E)), parts=(part,)).direct())
    expression = r.expression()

    def ask(budget):
        return lambda: r.host.query_belief(belief=expression, quantity=fb.BeliefQuantity(kind="mass"), budget=budget)
    queries = {"A": ask(loose(Q(1, 50))), "B": ask(loose(Q(1, 2**50), refinements=1))}
    turns = _Turns(monkeypatch)
    alone = {}
    for name, query in queries.items():   # 1 つずつ (計算表の控えを空にしてから)
        ft._INTEGRALS.clear()
        alone[name] = turns.start(name, query)()
    calls = turns.calls["A"]
    assert alone["A"][0] <= alone["A"][1] and alone["B"] == ("incomplete", "precision not reached within the budget")
    assert calls >= 4   # A は箱を分けて答える (割り込む所がある)
    for stop in sorted({1, calls // 2, calls}):
        for b_waits in (False, True):
            ft._INTEGRALS.clear()
            turns.calls.clear()
            turns.seen.clear()
            finish_a = turns.start("A", queries["A"], stop)
            finish_b = turns.start("B", queries["B"], 1 if b_waits else 0)
            answers = {"A": finish_a(), "B": finish_b()} if b_waits else {"B": finish_b(), "A": finish_a()}
            assert answers == alone, (stop, b_waits)
            assert turns.seen["A"] & turns.seen["B"]   # 2 つの照会は同じ積分を使った


def beta_mean_of_exp(a, cumulative):
    """独立の数値積分 (scipy): x ~ Beta(a, a) の E[exp(−cumulative(x))] (誤差 1e−10 以下)。密度は lgamma で正規化する。"""
    from math import lgamma, log
    from scipy.integrate import quad
    norm = 2 * lgamma(a) - lgamma(2 * a)
    value, err = quad(lambda x: exp((a - 1) * (log(x) + log(1 - x)) - norm - cumulative(x)), 0, 1, points=[0.5],
                      epsabs=1e-13, limit=200)
    assert err < 1e-10
    return value


def contains_float(value, ref):
    assert float(value.lower) - 1e-9 <= ref <= float(value.upper) + 1e-9, (float(value.lower), ref, float(value.upper))


def test_impl40_tiny_share_normalizer_names_the_precision_shortage_at_the_boundary_box(rig):
    """K40-R2 (正の量の逆数は正の下界が証明できてから、できなければ精度の不足) の、f の境界の箱: T = 1・m = 2・ρ = 0・
    w = (1/2, 1/2) は点、f ~ Dirichlet(100, 100) (κ_f = 200)、基準の率 1、初期の件数 0、時刻 1/2 の点の empty。尤度は e^{−f_1}。
    f の箱が単体の境目に触れると、質量の上界は周辺の Beta の下側の確率 (`Integral._tail_sup`) で、そこに 1/B(100, 100) が入る。
    64 bit では B の下界が 0 なので、積分は精度の不足 (`_EnclosureShort`) を名指し (0 で割らない)、128 bit では真の値
    E[e^{−f_1}] (独立の数値積分) を包む。照会は予算の中で精度を上げ、mass = (on + off)/2 と switch = on/(on + off)
    (off = e^{−1/2}) の真の値を包む (精度の不足を途中までの和で答えない)。"""
    from sui.f import _EnclosureShort
    on = beta_mean_of_exp(100, lambda x: x)
    off = exp(-0.5)
    law = {"kind": "poisson", "rate": Q(1), "origin_ns": 0, "time_unit": Q(1, 10), "initial_count": 0,
           "clock": {"period": Q(1), "segments": 2, "rotation": Q(0), "widths": [Q(1, 2), Q(1, 2)],
                     "width_concentration": None, "shares": None, "share_concentration": Q(200)}}
    entries = [{"kind": "acquisition", "before_ns": 5, "after_ns": 5, "cursor": 0, "symbol": "empty", "point": "x"}]
    integral = fc.Integral({"index": 0, "failure": None, "disconnection": None, "law": law}, entries, 5, None)
    assert integral.dims == [("f", 0)] and integral.exact is None
    with pytest.raises(_EnclosureShort):
        integral.table(fc.Num(64)).at(fc.FIRST_LEVEL)
    lo, hi = integral.table(fc.Num(128)).at(fc.FIRST_LEVEL)
    assert 0 < lo and float(lo) - 1e-12 <= on <= float(hi) + 1e-12
    part = continuous(rotation=Q(0), widths=(Q(1, 2), Q(1, 2)), shares=None, kf=Q(200))
    r = first(only_clock(rig, script((2, 2, E)), parts=(part,)).direct())
    budget = loose(Q(1, 10), refinements=3)
    mass = r.host.query_belief(belief=r.expression(), quantity=fb.BeliefQuantity(kind="mass"), budget=budget)
    contains_float(mass, (on + off) / 2)
    contains_float(sq(r, "switch", on=("clk",), budget=budget), on / (on + off))


def test_impl40_precision_shortage_is_not_answered_with_a_partial_sum(rig):
    """K40-R2 (commit 前のレビュー 1 通目の反例そのまま): T = 1・m = 2・ρ = 0・f = (1/2, 1/2) は点、w ~ Dirichlet(100, 100)、
    基準の率 1、初期の件数 0、時刻 1/2 の点の empty。64 bit では Dirichlet の正規化の 1/B(100, 100) の下界が証明できず、積分を
    含む量の上下界は「無し」(精度の不足) で、積分の項を落とした途中までの和 (時計オフの枝だけ) を上下界にしない。照会は精度を
    上げて、mass = (on + off)/2 と switch = on/(on + off) の真の値を包む。on = E[e^{−Λ(w_1)}] (独立の数値積分)、Λ(w_1) は
    w_1 ≥ 1/2 で 1/(4 w_1)、w_1 < 1/2 で 1/2 + (1/2 − w_1)/(2 (1 − w_1))。off = e^{−1/2}。"""
    on = beta_mean_of_exp(100, lambda u: 1 / (4 * u) if u >= 0.5 else 0.5 + (0.5 - u) / (2 * (1 - u)))
    off = exp(-0.5)
    part = continuous(rotation=Q(0), widths=None, kw=Q(100), shares=(Q(1, 2), Q(1, 2)))
    r = first(only_clock(rig, script((2, 2, E)), parts=(part,)).direct())
    spec = ft._spec(r.host._state, r.expression())
    n, d = ft._quantity(spec, fb.BeliefQuantity(kind="mass"))
    integrals = ft._integrals(n, d)
    assert integrals and not n.poly.zero   # 積分の項と、時計オフの枝の指数多項式の両方を持つ
    assert ft._enclose_form(n, integrals, ft._num(Q(1, 10), 0), fc.FIRST_LEVEL) == (None, None)
    budget = loose(Q(1, 10), refinements=3)
    mass = r.host.query_belief(belief=r.expression(), quantity=fb.BeliefQuantity(kind="mass"), budget=budget)
    contains_float(mass, (on + off) / 2)
    contains_float(sq(r, "switch", on=("clk",), budget=budget), on / (on + off))


def test_impl40_denominator_lower_bound_zero_is_a_precision_shortage(rig):
    """K40-R2 (比の分母は正の下界が証明できてから): 基準の率 200 で、T = 1・m = 2・ρ = 0・w ~ Dirichlet(1, 1)・f = (1/2, 1/2)、
    時刻 1/2 の点の empty (期待の件数 100、長い記録で尤度が小さくなるのと同じ形)。時計オフの枝の尤度 e^{−100} ≈ 2^−144 は、64 bit
    の照会の `_exp_neg` の格子 2^−96 より小さく下界が 0、時計オンの積分の下界も 0 (箱の中の尤度の差の上界 F·min(1, D) が e^{−50}
    程度の値を覆う)。スイッチの照会の分母 Z_M の下界はちょうど 0 (精度の不足の None ではない) で、比は「無し」(0 で割らない)。
    照会は予算の中で精度を上げ、届かなければ incomplete (ZeroDivisionError で止まらない)。率 100 (e^{−50} ≈ 2^−72) では
    オフの枝の下界が正で、分母の下界 0 は作れない。"""
    part = continuous(rotation=Q(0), widths=None, kw=Q(1), shares=(Q(1, 2), Q(1, 2)))
    r = first(rig(script((2, 2, E)), rates=(Q(200), Q(200)), role=None, unit=Q(1, 4), parts=(part,)).direct())
    quantity = fb.SwitchQuantity(kind="switch", candidate=r.pool().members[0].id, family="f", on=("clk",))
    spec = ft._spec(r.host._state, r.expression())
    n, d = ft._quantity(spec, quantity)
    integrals = ft._integrals(n, d)
    num = ft._num(Q(1, 10), 0)
    assert integrals and not d.poly.zero
    assert ft._enclose_form(d, integrals, num, fc.FIRST_LEVEL)[0] == 0   # 下界 0 (精度の不足の None ではない)
    assert ft._ratio_forms(n, d, integrals, fc.FIRST_LEVEL, num) == (None, None)
    with pytest.raises(fb.TimeBeliefError) as error:
        r.host.query_switch_belief(belief=r.expression(), quantity=quantity, budget=loose(Q(1, 10), refinements=1))
    assert error.value.kind == "incomplete"
