"""S4b-1a v0.5 §6-5 の独立した固定値 (実装前の試験台本)。

格子 (今の状態, 数え上げ N) の前向きの計算と、道の総当たり × Polya を分数で比べ、
白紙 (好みの付箋 0 枚、1 歩、γ = 1) の 1 歩の G = −I の値と選ぶ確率を出す。
sui を import しない (独立の検算)。情報量の対数だけ浮動小数点。
"""
from fractions import Fraction as F
from itertools import product
import math


def B(t):
    """対称 2 状態・片道の率 log 2 / 2 の遷移 (整数秒)。B[to][from]。"""
    same = (1 + F(1, 2 ** t)) / 2
    return [[same, 1 - same], [1 - same, same]]


def harmonic(n):
    return sum(F(1, k) for k in range(1, n + 1))


def expected_entropy(beta):
    """整数の β の Dirichlet の下の E[H(Cat Θ)] = H_{β0} − Σ β_i/β0 H_{β_i}。"""
    b0 = sum(beta)
    return harmonic(b0) - sum(F(b, b0) * harmonic(b) for b in beta)


def entropy(p):
    return -sum(float(x) * log_fraction(F(x)) for x in p if x)


def lattice(D, alpha, fixed, sequence, until, *, transition=B, raw=False):
    """sequence = [(時刻, 行動, 観測)]。alpha[行動][状態][観測]、fixed[行動][状態][観測]。"""
    size = len(D)
    table = {(s, ()): D[s] for s in range(size) if D[s]}
    prev = 0

    def advance(table, dt):
        if dt == 0:
            return table
        M, new = transition(dt), {}
        for (s, N), w in table.items():
            for s2 in range(size):
                key = (s2, N)
                if w * M[s2][s]:
                    new[key] = new.get(key, F(0)) + w * M[s2][s]
        return new

    for t, act, o in sequence:
        table = advance(table, t - prev)
        prev = t
        new = {}
        for (s, N), w in table.items():
            counts = dict(N) if N else {}
            if act in alpha:
                c = counts.get((act, s), (0, 0))
                col = [alpha[act][s][v] + c[v] for v in range(2)]
                if alpha[act][s][o] == 0:
                    continue
                w2 = w * F(col[o], sum(col))
                c2 = list(c); c2[o] += 1
                counts[(act, s)] = tuple(c2)
            else:
                w2 = w * fixed[act][s][o]
            if w2:
                key = (s, tuple(sorted(counts.items())))
                new[key] = new.get(key, F(0)) + w2
        table = new
    table = advance(table, until - prev)
    if raw:
        return table
    total = sum(table.values())
    return {k: w / total for k, w in table.items()}


def one_step_info(table, alpha, fixed, action):
    """「今を測る」1 歩: 成分 r = (k, N) の予測 μ_r と e_r から I = H(q) − Σ ν e。"""
    q = [F(0), F(0)]
    cond = 0.0
    for (k, N), w in table.items():
        counts = dict(N)
        if action in alpha:
            c = counts.get((action, k), (0, 0))
            beta = [alpha[action][k][v] + c[v] for v in range(2)]
            mu = [F(b, sum(beta)) for b in beta]
            e = expected_entropy(beta)
        else:
            mu = fixed[action][k]
            e = entropy(mu)
        for y in range(2):
            q[y] += w * mu[y]
        cond += float(w) * e
    return entropy(q) - cond


def softmax_info(infos):
    m = max(infos)
    ws = [math.exp(i - m) for i in infos]
    return [w / sum(ws) for w in ws]


def brute(D, alpha, fixed, sequence, until, *, transition=B, raw=False):
    """道の総当たり × Polya で、最後の状態と N の同時の重みを作る (lattice の独立の検算)。"""
    # 最後の観測と until が同時なら余分な状態を列挙しない。L1 は 2**6 = 64 道。
    times = [0] + [t for t, _, _ in sequence]
    if until != times[-1]:
        times.append(until)
    out = {}
    for path in product(range(len(D)), repeat=len(times)):
        w = D[path[0]]
        for i in range(1, len(times)):
            w *= transition(times[i] - times[i - 1])[path[i]][path[i - 1]]
        counts = {}
        for (t, act, o), s in zip(sequence, path[1:]):
            if act in alpha:
                c = counts.get((act, s), (0, 0)); c = list(c); c[o] += 1
                counts[(act, s)] = tuple(c)
            else:
                w *= fixed[act][s][o]
        for (act, s), c in counts.items():
            num = F(1)
            for v in range(2):
                for i in range(c[v]):
                    num *= alpha[act][s][v] + i
            den = F(1)
            for i in range(sum(c)):
                den *= sum(alpha[act][s]) + i
            w *= num / den
        if w:
            key = (path[-1], tuple(sorted(counts.items())))
            out[key] = out.get(key, F(0)) + w
    if raw:
        return out
    total = sum(out.values())
    return {k: w / total for k, w in out.items()}


def g6():
    D = [F(1, 2), F(1, 2)]
    alpha = {"look": [[1, 1], [1, 1]]}                       # 学ぶ: 白紙の Beta(1,1)
    fixed = {"peek": [[F(3, 4), F(1, 4)], [F(1, 4), F(3, 4)]]}  # 固定: 状態を 3/4 で当てる
    frozen = {"look": [[F(1, 2), F(1, 2)], [F(1, 2), F(1, 2)]], **fixed}  # 学ばない形 (α の平均で固定)
    histories = {
        "0 件": [],
        "look を 3 件 (x, x, y)": [(1, "look", 0), (2, "look", 0), (3, "look", 1)],
        "look を 8 件": [(t, "look", o) for t, o in zip(range(1, 9), (0, 0, 1, 0, 1, 1, 0, 0))],
    }
    print("G6: 白紙の 1 歩 (γ = 1、G = −I)。候補 (look, peek)")
    for name, seq in histories.items():
        until = (seq[-1][0] if seq else 0) + 1
        table = lattice(D, alpha, fixed, seq, until)
        assert table == brute(D, alpha, fixed, seq, until), name
        evidence, _ = checked(D, alpha, fixed, seq, until)
        _, anchor = checked(D, alpha, fixed, seq, seq[-1][0] if seq else 0)
        emit("G6 inputs: " + name, inputs(D, alpha, fixed, seq, now=until),
             evidence=evidence, anchor_components=len(anchor), evaluation_components=len(table),
             next_look=prediction(table, alpha, fixed, "look"))
        infos = [one_step_info(table, alpha, fixed, a) for a in ("look", "peek")]
        # 学ばない形: look の表を α の平均に固定 (同じ観測で状態の信念だけ更新)
        table_f = lattice(D, {}, frozen, seq, until)
        infos_f = [one_step_info(table_f, {}, frozen, a) for a in ("look", "peek")]
        print(f"  {name}: 成分 {len(table)}  学ぶ: I = {infos[0]:.15f}, {infos[1]:.15f}  q_pi = "
              f"{[round(x, 15) for x in softmax_info(infos)]}")
        print(f"  {'':{len(name)}}  学ばない形: I = {infos_f[0]:.15f}, {infos_f[1]:.15f}  q_pi = "
              f"{[round(x, 15) for x in softmax_info(infos_f)]}")
    print("総当たりと格子: 全部の場面で分数で一致 (assert)")


# 以下も sui/numpy/scipy には依存しない。配列は [状態][観測]。
# 実装の model.a へ写す時だけ転置する。時刻・所要の単位は秒 (ns へは ×10**9)。
# fixed_counts のある例では、それを model.a に使う (極小の fixed_A をfloatにしない)。
# N の内部の疎な表現と、仕様 §4-2 の平坦なキーは別物。表示には後者も出す。
HALF = F(1, 2)
D_AB = (F(2, 5), F(3, 5))
ALPHA_AB = {"a": ((2, 1), (1, 3)), "b": ((1, 2), (3, 1))}
FIXED_AB = {"f": ((F(3, 4), F(1, 4)), (F(1, 4), F(3, 4)))}
Q_SYMMETRIC = "Q=[[-r,r],[r,-r]], r=log(2)/2; B(t)[s,s]=(1+2**(-t))/2"


def inputs(D, alpha, fixed, sequence=(), *, now=0, observed=None,
           durations=None, pending=(), Q=Q_SYMMETRIC, **extra):
    """コピー用の全入力。None は永久未着、観測の番号 0=x, 1=y。"""
    return dict(D=D, Q=Q, alpha=alpha, fixed_A=fixed, observations=sequence,
                durations={} if durations is None else durations,
                measures="all report (unless explicitly overridden)", pending=pending,
                now=now, observed=now if observed is None else observed,
                preference="blank: cost=0, gamma=1, H=None", **extra)


def emit(name, fixture, **values):
    print(f"\n{name}")
    print("  input =", repr(fixture))
    for key, value in values.items():
        print(f"  {key} = {value!r}")


def near(actual, expected):
    assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), (actual, expected)


def normalize(table):
    total = sum(table.values(), F(0))
    assert total > 0
    return {key: value / total for key, value in table.items() if value}


def checked(D, alpha, fixed, sequence=(), until=0, *, transition=B):
    left = lattice(D, alpha, fixed, sequence, until, transition=transition, raw=True)
    right = brute(D, alpha, fixed, sequence, until, transition=transition, raw=True)
    assert left == right, (left, right)
    return sum(left.values(), F(0)), normalize(left)


def marginal(table, size=2):
    return tuple(sum((w for (j, _), w in table.items() if j == s), F(0))
                 for s in range(size))


def prediction(table, alpha, fixed, action):
    q = [F(0), F(0)]
    for (s, N), w in table.items():
        if action in alpha:
            counts = dict(N).get((action, s), (0, 0))
            beta = [a + n for a, n in zip(alpha[action][s], counts)]
            mu = [F(a, sum(beta)) for a in beta]
        else:
            mu = fixed[action][s]
        for o in range(2):
            q[o] += w * mu[o]
    return tuple(q)


def flat_key(s, N, alpha, size=2):
    counts = dict(N)
    return s, tuple(counts.get((a, j), (0, 0))[o]
                    for a in sorted(alpha) for o in range(2) for j in range(size))


def l1():
    alpha = {"a": ALPHA_AB["a"]}
    fixed = {"f": ((F(1), F(0)), (F(1, 4), F(3, 4)))}
    seq = ((1, "a", 0), (1, "a", 1), (2, "f", 1), (4, "a", 0), (4, "a", 1))
    evidence, table = checked(D_AB, alpha, fixed, seq, 4)
    assert evidence == F(387, 35840)
    assert marginal(table) == (F(63, 172), F(109, 172))
    emit("L1 (64 paths, including zero-weight paths)",
         inputs(D_AB, alpha, fixed, seq, now=4), evidence=evidence,
         q=marginal(table), next_a=prediction(table, alpha, fixed, "a"),
         weights=sorted((flat_key(s, N, alpha), w) for (s, N), w in table.items()))


def events(history, pending, capture):
    """同時刻は history → pending (仕事の ID 順) → capture。"""
    assert list(pending) == sorted(pending, key=lambda p: p[0])
    result = [(t, 0, i, a, o) for i, (t, a, o) in enumerate(history)]
    result += [(t, 1, i, a, None) for i, (_, a, t) in enumerate(pending) if t is not None]
    result.append((capture, 2, 0, None, None))
    return sorted(result)


def hand_lattice(D, alpha, fixed, history, pending, capture, *, transition=B):
    """独立の拡張格子。正規化前の W(z,k,j,N) を返す。Y は足さない。"""
    table = {(tuple(None for _ in pending), None, s, ()): p
             for s, p in enumerate(D) if p}
    previous = 0
    for t, kind, index, action, outcome in events(history, pending, capture):
        matrix, advanced = transition(t - previous), {}
        for (z, k, j, N), w in table.items():
            for s in range(len(D)):
                key = z, k, s, N
                if w * matrix[s][j]:
                    advanced[key] = advanced.get(key, F(0)) + w * matrix[s][j]
        previous, table = t, {}
        for (z, k, s, N), w in advanced.items():
            if kind == 2:
                key = z, s, s, N
                table[key] = table.get(key, F(0)) + w
                continue
            for o in (range(2) if kind == 1 else (outcome,)):
                counts = dict(N)
                if action in alpha:
                    c = counts.get((action, s), (0, 0))
                    if not alpha[action][s][o]:
                        continue
                    beta = [a + n for a, n in zip(alpha[action][s], c)]
                    p = F(beta[o], sum(beta))
                    updated = list(c)
                    updated[o] += 1
                    counts[action, s] = tuple(updated)
                else:
                    p = fixed[action][s][o]
                values = list(z)
                if kind == 1:
                    values[index] = o
                key = tuple(values), k, s, tuple(sorted(counts.items()))
                if w * p:
                    table[key] = table.get(key, F(0)) + w * p
    return table


def hand_brute(D, alpha, fixed, history, pending, capture, *, transition=B):
    """別の計算法: 各時刻の状態の道 × 全 z × 列ごとの Polya 積分。"""
    times = sorted({0, capture, *(t for t, _, _ in history),
                    *(t for _, _, t in pending if t is not None)})
    lookup = {t: i for i, t in enumerate(times)}
    out = {}
    for path in product(range(len(D)), repeat=len(times)):
        path_weight = D[path[0]]
        for i in range(1, len(times)):
            path_weight *= transition(times[i] - times[i - 1])[path[i]][path[i - 1]]
        if not path_weight:
            continue
        for z in product(*((None,) if t is None else (0, 1) for _, _, t in pending)):
            w, counts = path_weight, {}
            reports = list(history) + [(t, a, o) for (_, a, t), o in zip(pending, z) if t is not None]
            for t, action, o in reports:
                state = path[lookup[t]]
                if action in alpha:
                    c = counts.setdefault((action, state), [0, 0])
                    c[o] += 1
                else:
                    w *= fixed[action][state][o]
            for (action, state), c in counts.items():
                # batch integration, not the lattice's sequential predictive ratio
                numerator, denominator = F(1), F(1)
                for o, count in enumerate(c):
                    for n in range(count):
                        numerator *= alpha[action][state][o] + n
                for n in range(sum(c)):
                    denominator *= sum(alpha[action][state]) + n
                w *= numerator / denominator
            if w:
                N = tuple(sorted((key, tuple(value)) for key, value in counts.items()))
                key = tuple(z), path[lookup[capture]], path[-1], N
                out[key] = out.get(key, F(0)) + w
    return out


def checked_hand(D, alpha, fixed, history, pending, capture, *, transition=B):
    left = hand_lattice(D, alpha, fixed, history, pending, capture, transition=transition)
    right = hand_brute(D, alpha, fixed, history, pending, capture, transition=transition)
    assert left == right
    return normalize(left)


def summarize_hand(table, alpha, fixed, action, *, use_last=False, uniform_z=False):
    groups = {}
    for (z, k, j, N), w in table.items():
        key = (j if use_last else k), N
        group = groups.setdefault(z, {})
        group[key] = group.get(key, F(0)) + w
    q, information, details = [F(0), F(0)], 0.0, []
    for z, group in sorted(groups.items(), key=lambda item: repr(item[0])):
        rho = sum(group.values(), F(0))
        nu = normalize(group)
        predicted = prediction(nu, alpha, fixed, action)
        info = one_step_info(nu, alpha, fixed, action)
        weight = F(1, len(groups)) if uniform_z else rho
        q = [p + weight * v for p, v in zip(q, predicted)]
        information += float(weight) * info
        details.append(dict(z=z, rho=rho, q=predicted, information=info))
    return tuple(q), information, details


def g1_g3():
    alpha = {"a": ((1, 1), (1, 1)), "b": ((1, 1), (1, 1))}
    fair = {"f": ((HALF, HALF), (HALF, HALF))}
    _, table = checked((HALF, HALF), alpha, fair, until=1)
    good = one_step_info(table, alpha, fair, "f")
    bad = one_step_info(table, {**alpha, "f": ((1, 1), (1, 1))}, {}, "f")
    near(good, 0)
    near(bad, .1931471805599453)
    emit("G1", inputs((HALF, HALF), alpha, fair, now=1), correct=good, wrong_Dirichlet=bad)
    for pending_action, expected in (("a", .13651416829481278), ("b", .1931471805599453)):
        pending = (("job1", pending_action, 0),)
        joint = checked_hand((F(1), F(0)), alpha, {}, (), pending, 0)
        q, info, details = summarize_hand(joint, alpha, {}, "a")
        near(info, expected)
        emit("G2 pending=" + pending_action, inputs((F(1), F(0)), alpha, {}, pending=pending),
             candidate="a", q=q, information=info, branches=details)
    perfect = {"past": ((F(1), F(0)), (F(0), F(1))),
               "candidate": ((F(1), F(0)), (F(0), F(1)))}

    def transition_08(dt):
        same = (1 + F(3, 5) ** dt) / 2
        return ((same, 1 - same), (1 - same, same))

    pending = (("job1", "past", 0),)
    table = checked_hand((HALF, HALF), alpha, perfect, (), pending, 1, transition=transition_08)
    wrong = checked_hand((HALF, HALF), alpha, perfect, (), (("job1", "past", 1),), 1,
                         transition=transition_08)
    q, info, detail = summarize_hand(table, alpha, perfect, "candidate")
    _, bad, _ = summarize_hand(wrong, alpha, perfect, "candidate")
    near(info, .5004024235381879)
    near(bad, 0)
    emit("G3", inputs((HALF, HALF), alpha, perfect, now=1, pending=pending,
         durations={"past": ((2, F(1)),), "candidate": ((0, F(1)),),
                    "a": ((1, F(1)),), "b": ((1, F(1)),)},
         Q="symmetric r=log(5/3)/2", measure_override={"past": "start"}),
         candidate="candidate", q=q, correct=info, wrong_report_at_now=bad, branches=detail)


def remaining(points, start, boundary):
    eligible = {d: p for d, p in points if d is None or d >= boundary - start}
    return normalize(eligible)


def g4_g5():
    durations = {"a": ((1, HALF), (5, HALF)), "b": ((1, F(1, 3)), (3, F(1, 3)), (None, F(1, 3))),
                 "f": ((0, F(1)),)}
    for case, history, now, pending_action, boundary in (
            ("G4 / A", ((1, "a", 0), (2, "f", 1)), 2, "a", 2),
            ("G5 / B", ((1, "a", 0), (4, "f", 1)), 4, "b", 2)):
        points = remaining(durations[pending_action], 0, boundary)
        qx, info, rows = F(0), 0.0, []
        for d, pd in points.items():
            for cd, pc in durations["a"]:
                capture = now + cd
                pending = (("job1", pending_action, d),)
                table = checked_hand(D_AB, ALPHA_AB, FIXED_AB, history, pending, capture)
                q, value, details = summarize_hand(table, ALPHA_AB, FIXED_AB, "a")
                qx += pd * pc * q[0]
                info += float(pd * pc) * value
                rows.append(dict(pending_time=d, capture=capture, mass=pd * pc,
                                 q=q, information=value, z=details))
                if case.startswith("G4") and capture == 3:
                    bad_q, bad_i, _ = summarize_hand(table, ALPHA_AB, FIXED_AB, "a", use_last=True)
                    assert bad_q[0] == F(323, 635)
                    near(bad_i, .138100404451086)
                    rows[-1]["wrong_last_state"] = (bad_q, bad_i)
        if case.startswith("G4"):
            assert qx == F(2551, 5080)
            near(info, .184034572312090)
        else:
            assert qx == F(10651, 21880)
            near(info, .202695429073511)
            assert remaining(durations["b"], 0, now) == {None: F(1)}
            assert remaining(durations["b"], 0, 3) == {3: HALF, None: HALF}
            rows.append(dict(wrong_current_run_boundary=remaining(durations["b"], 0, now),
                wrong_information=sum(row["information"] for row in rows if row["pending_time"] is None) / 2,
                equality_boundary_3=remaining(durations["b"], 0, 3)))
        emit(case, inputs(D_AB, ALPHA_AB, FIXED_AB, history, now=now, durations=durations,
             pending=(("job1", pending_action, "start=0"),), run_end_boundary=boundary),
             candidate="a", pending_remaining=points, q_x=qx, information=info, branches=rows)


def g7():
    D, alpha = (F(1), F(0)), {"a": ((1, 1), (1, 1))}
    base = checked_hand(D, alpha, {}, (), (), 0)
    q, info, _ = summarize_hand(base, alpha, {}, "a")
    # a: 候補そのものを、独立な次の観測の前の仮の報告として数えてしまう誤り。
    wrong = checked_hand(D, alpha, {}, (), (("candidate_as_pending", "a", 0),), 0)
    bad_q, bad_info, _ = summarize_hand(wrong, alpha, {}, "a")
    assert abs(info - bad_info) > .01
    emit("G7a", inputs(D, alpha, {}), candidate="a", correct=(q, info),
         wrong_add_candidate_Y=(bad_q, bad_info))
    # b の主試験は公開 plan ではなく表の関数を直接呼ぶ。重みをそのままにして
    # Nだけ増やす変異を分離する。同じaを候補にする公開planはNoneを理由に拒否する。
    bottom = checked_hand(D, alpha, {}, (), (("job1", "a", None),), 0)
    wrong_bottom = {}
    for (z, k, j, N), w in bottom.items():
        assert N == ()
        wrong_bottom[z, k, j, ((('a', j), (1, 0)),)] = w
    good_bottom = summarize_hand(bottom, alpha, {}, "a")
    bad_bottom = summarize_hand(wrong_bottom, alpha, {}, "a")
    assert good_bottom[0] == (HALF, HALF) and bad_bottom[0] == (F(2, 3), F(1, 3))
    near(good_bottom[1], .1931471805599453)
    near(bad_bottom[1], .13651416829481278)
    emit("G7b direct table (N-only mutation)", inputs(D, alpha, {},
         durations={"a": ((1, HALF), (None, HALF))}, pending=(("job1", "a", None),),
         capture=0, measure_override={"a": "start"}), candidate="a",
         correct=good_bottom, wrong_increment_N_on_bottom=bad_bottom,
         scope="direct hand_table/components only; public plan rejects candidate a with None")
    # b: b の ⊥ を x@now として数える誤り。候補 a は有限所要なので API でも有効。
    table = checked_hand(D_AB, ALPHA_AB, {}, (), (("job1", "b", None),), 3)
    good_b = summarize_hand(table, ALPHA_AB, {}, "a")
    wrong = checked_hand(D_AB, ALPHA_AB, {}, ((2, "b", 0),), (("job1", "b", None),), 3)
    bad_b = summarize_hand(wrong, ALPHA_AB, {}, "a")
    assert good_b[0] != bad_b[0] and abs(good_b[1] - bad_b[1]) > 1e-4
    assert all(not N for (_, _, _, N) in table)
    emit("G7b additional API-valid contrast", inputs(D_AB, ALPHA_AB, {}, now=2,
         durations={"a": ((1, F(1)),), "b": ((1, HALF), (None, HALF))},
         pending=(("job1", "b", "start=0; remaining=None"),)), candidate="a",
         correct=good_b, wrong_count_bottom_as_x_at_now=bad_b)
    # c: z=(x,y) の確率が (2/3,1/3)。枝内で正規化して質量を捨てると変わる。
    alpha = {"a": ((2, 1), (2, 1))}
    pending = (("job1", "a", 0),)
    table = checked_hand(D, alpha, {}, (), pending, 0)
    good = summarize_hand(table, alpha, {}, "a")
    bad = summarize_hand(table, alpha, {}, "a", uniform_z=True)
    assert good[0] != bad[0] and abs(good[1] - bad[1]) > 1e-4
    emit("G7c", inputs(D, alpha, {}, pending=pending), candidate="a", correct=good,
         wrong_normalize_each_z_equally=bad)
    # d: b は候補の所要1/3秒を半々。候補 f の予測は3/4と9/16で異なる。
    alpha = {"a": ((1, 1), (1, 1))}
    fixed = {"f": ((F(1), F(0)), (F(0), F(1)))}
    history = ((0, "a", 0),)
    mixed, good_info, rows = {}, 0.0, []
    for capture in (1, 3):
        table = checked_hand(D, alpha, fixed, history, (), capture)
        predicted, value, _ = summarize_hand(table, alpha, fixed, "f")
        rows.append((capture, predicted, value))
        good_info += float(HALF) * value
        for key, w in table.items():
            mixed[key] = mixed.get(key, F(0)) + HALF * w
    mixed_q, bad_info, _ = summarize_hand(mixed, alpha, fixed, "f")
    assert rows[0][1] != rows[1][1] and abs(good_info - bad_info) > .01
    emit("G7d", inputs(D, alpha, fixed, history,
         durations={"a": ((0, F(1)),), "f": ((1, HALF), (3, HALF))}), candidate="f",
         branches=rows, correct_information=good_info, wrong_mix_b_first=(mixed_q, bad_info))


def l16():
    alpha, fixed = {"a": ALPHA_AB["a"]}, FIXED_AB
    D = (F(1), F(0))
    seq = ((1, "a", 0),)
    _, good = checked(D, alpha, fixed, seq, 1)
    _, bad = checked(D, alpha, fixed, ((0, "a", 0),), 0)
    assert marginal(good) != marginal(bad)
    emit("L16 initial transition", inputs(D, alpha, fixed, seq, now=1),
         correct_q=marginal(good), wrong_q=marginal(bad),
         correct_next=prediction(good, alpha, fixed, "a"), wrong_next=prediction(bad, alpha, fixed, "a"))
    # run1 origin=0, observed at1; run2 boot=3, observed at4. 軸は途切れない。
    seq = ((1, "a", 0), (4, "f", 1))
    _, good = checked(D_AB, alpha, fixed, seq, 4)
    _, first = checked(D_AB, alpha, fixed, seq[:1], 1)
    # 誤りは run2 の状態だけを D に戻す。N の周辺は保持するのでリセット原因を分離。
    counts_marginal = {}
    for (s, N), w in first.items():
        counts_marginal[N] = counts_marginal.get(N, F(0)) + w
    _, restarted = checked(D_AB, {}, fixed, ((1, "f", 1),), 1)
    bad = {(s, N): w * wn for (s, _), w in restarted.items() for N, wn in counts_marginal.items()}
    assert marginal(good) != marginal(bad)
    emit("L16 run boundary", inputs(D_AB, alpha, fixed, seq, now=4, runs=((0, 2), (3, 4))),
         correct_q=marginal(good), wrong_reset_state_q=marginal(bad),
         correct_next=prediction(good, alpha, fixed, "a"), wrong_next=prediction(bad, alpha, fixed, "a"))
    # 同じ attempt に x@1 が2件: 両方を ambiguous_attempt として列から除く。
    _, good = checked(D_AB, alpha, fixed, ((2, "f", 1),), 2)
    _, bad = checked(D_AB, alpha, fixed, ((1, "a", 0), (2, "f", 1)), 2)
    assert prediction(good, alpha, fixed, "a") != prediction(bad, alpha, fixed, "a")
    emit("L16 duplicate", inputs(D_AB, alpha, fixed, ((2, "f", 1),), now=2,
         raw_reports=(("attempt1", 1, "a", "x"), ("attempt1", 1, "a", "x"),
                      ("attempt2", 2, "f", "y"))), correct_q=marginal(good),
         wrong_keep_first_q=marginal(bad), correct_next=prediction(good, alpha, fixed, "a"),
         wrong_keep_first_next=prediction(bad, alpha, fixed, "a"))


def log_fraction(value):
    """普通の確率が0に丸まっても、整数の対数の差なら大きさを読める。"""
    return -math.inf if not value else math.log(value.numerator) - math.log(value.denominator)


def forbidden_cost(probabilities, forbidden=(1,)):
    # テストの期待値だけを作る。sui の例外・決定を実行したとは主張しない。
    return math.inf if any(probabilities[o] > 0 for o in forbidden) else F(0)


def l11_l15():
    tiny = F(1, 10**200)
    D, alpha = (HALF, HALF), {"a": ((1, 1), (1, 1))}
    history = ((0, "a", 0),)
    # N5(1): model.a の有限な2数から直接 log A。普通の平均を経由すると0になる。
    rare = tiny / (10**200 + tiny)
    fixed = {"probe": ((1 - rare, rare), (1 - rare, rare)),
             "safe": ((F(1), F(0)), (F(1), F(0)))}
    _, table = checked(D, alpha, fixed, history, 1)
    q = prediction(table, alpha, fixed, "probe")
    assert q[1] == rare and float(rare) == 0.0  # IEEE の丸めを診断する箇所だけ変換
    assert forbidden_cost(q) == math.inf
    emit("L11 candidate / N5", inputs(D, alpha, fixed, history, now=1,
         fixed_counts={"probe": ((10**200, tiny),) * 2}, forbidden="y"),
         q_y="1/(10**400+1)", log_q_y=log_fraction(q[1]), float_q_y=float(q[1]),
         expected_cost="+inf", only_probe="NoAdmissibleCandidate")

    # N5(2): 同時刻の2回の観測で、小さい状態の重みを作る。学習済みNも運ぶ。
    fixed = {"sense": ((F(1), F(0)), (tiny, 1 - tiny)),
             "probe": ((F(1), F(0)), (F(0), F(1)))}
    history = ((0, "a", 0), (0, "sense", 0), (0, "sense", 0))
    pending = (("job1", "probe", 0),)
    joint = checked_hand(D, alpha, fixed, history, pending, 0)
    # Dirichlet の巨大な事前は不要。小さくなった w の支えだけが問題。
    q, info, branches = summarize_hand(joint, alpha, fixed, "probe")
    rare_branch = next(row for row in branches if row["z"] == (1,))
    assert rare_branch["rho"] == rare and float(rare_branch["rho"]) == 0
    assert rare_branch["q"] == (F(0), F(1))
    assert forbidden_cost(rare_branch["q"]) == math.inf
    emit("L11 pending / N5", inputs(D, alpha, fixed, history, pending=pending, forbidden="y"),
         rare_z="y", rho="1/(10**400+1)", log_rho=log_fraction(rare),
         conditional_q=rare_branch["q"], branch_cost="+inf", aggregate_cost="+inf")

    # 所要の直積: 二つの小さい正の点を掛けると b 自体が0に丸まる。
    # 集計結果だけでは他の禁止枝に隠れるので、この b の保持と費用を直接検査する。
    durations = {"a": ((0, 1 - tiny), (1, tiny)), "probe": ((0, 1 - tiny), (1, tiny))}
    weights = {(dp, dc): pp * pc for dp, pp in durations["a"] for dc, pc in durations["probe"]}
    assert sum(weights.values()) == 1 and weights[1, 1] == tiny**2
    duration_fixed = {"probe": fixed["probe"]}
    duration_rows = []
    for (dp, dc), weight in weights.items():
        joint = checked_hand(D, alpha, duration_fixed, (), (("job1", "a", dp),), dc)
        q, _, _ = summarize_hand(joint, alpha, duration_fixed, "probe")
        duration_rows.append(((dp, dc), log_fraction(weight), forbidden_cost(q)))
    assert forbidden_cost(q) == math.inf
    emit("L11 duration branch", inputs(D, alpha, duration_fixed, durations=durations,
         pending=(("job1", "a", "start=0"),), forbidden="y"), candidate="probe",
         inspected_b=(1, 1), mass="1e-400", log_mass=log_fraction(weights[1, 1]),
         float_mass=float(weights[1, 1]), branch_cost="+inf", aggregate_cost="+inf",
         branch_log_weights_and_costs=duration_rows,
         test_target="assert this b is retained; aggregate +inf alone cannot detect dropping it")

    # L12: gamma=0 でも禁止を除いてから一様化。0*inf は計算しない。
    emit("L12", inputs(D, alpha, {"probe": ((1 - rare, rare),) * 2,
         "safe": ((F(1), F(0)),) * 2}, ((0, "a", 0),), now=1,
         style={"gamma": 0, "H_ns": None}, forbidden="y",
         fixed_counts={"probe": ((10**200, tiny),) * 2}),
         costs=("+inf", F(0)), q_pi=(F(0), F(1)), only_probe="NoAdmissibleCandidate")

    # N10: 付箋の確率の対数は有限。和の2e308はbinary64の最大を越える。
    import sys
    overflow = 2 * 10**308
    assert F(overflow) > F(sys.float_info.max)
    fixed = {"probe": ((F(9, 10), F(1, 10)),) * 2, "safe": ((F(1), F(0)),) * 2}
    _, table = checked(D, alpha, fixed, ((0, "a", 0),), 1)
    assert prediction(table, alpha, fixed, "probe") == (F(9, 10), F(1, 10))
    emit("L13 / N10", inputs(D, alpha, fixed, ((0, "a", 0),), now=1,
         items=({"log_probs": (("x", 0), ("y", -10**308))},) * 2,
         style={"gamma": 0, "H_ns": None}), exact_cost_y="2e308",
         mathematical_expected_cost="2e307 (but intermediate cost is unrepresentable)",
         expected="NumericalRange", decision_records=0, job_records=0,
         control="two -1e307 entries: cost_y=2e307, expected=2e306, q_pi=(1/2,1/2)")

    # N8: 更新直後の格子の二つの (s,N) が同じ重み。
    _, table = checked(D, alpha, {}, ((0, "a", 0),), 0)
    assert sorted(table.values()) == [HALF, HALF]
    perfect = {"f": ((F(1), F(0)), (F(0), F(1)))}
    near(one_step_info(table, alpha, perfect, "f"), math.log(2))
    for shift in (-1e16, -1e300):
        good_logs = (-math.log(2), -math.log(2))
        bad_logs = (shift - (shift + math.log(2)),) * 2
        assert bad_logs == (0., 0.)
        emit("L14 / N8", inputs(D, alpha, perfect, ((0, "a", 0),),
             unnormalized_log_weights=[(flat_key(s, N, alpha), shift) for s, N in table]),
             normalized_weights=(HALF, HALF), normalized_logs=good_logs,
             wrong_restore_common_offset_logs=bad_logs, wrong_total=2,
             candidate="f", uniform_preference_cost=math.log(2), information=math.log(2), J=0)

    # 本当の0ならキーを持たず、小さい正は普通の数が0でもキーを持つ。
    zero_fixed = {"sense": ((F(1), F(0)), (F(0), F(1)))}
    positive_fixed = {"sense": ((F(1), F(0)), (tiny, 1 - tiny))}
    seq = ((0, "a", 0), (0, "sense", 0), (0, "sense", 0))
    _, positive = checked(D, alpha, positive_fixed, seq, 0)
    _, zero = checked(D, alpha, zero_fixed, seq, 0)
    assert marginal(positive)[1] == rare and marginal(zero)[1] == 0
    assert len(positive) == 2 and len(zero) == 1
    emit("L15", inputs(D, alpha, positive_fixed, seq, zero_control_A=zero_fixed),
         positive_components=len(positive), zero_components=len(zero),
         positive_log_q1=log_fraction(rare), zero_log_q1=-math.inf,
         note="positive ordinary probability and true zero both display as 0.0")
    l11_n6()


def l11_n6():
    """N6のCTMCは有理数ではないので、交代級数の上下界を分数で証明する。

    r=1e-200, dt=1, 0→1→2 (同じ率), 2は吸収。
    p2=1-(1+r)exp(-r)=Σ[n>=2] (-1)^n(n-1)r^n/n!。
    5項/4項の打切りは下/上界。0<r<=1なので項の絶対値が減少する。
    正確なCTMCの分数値だと偽らない。両端の行列で格子と総当たりを照合し、
    真の遷移の log p2 の両端が、公表値と1e-12以内になることを確認する。
    """
    r = F(1, 10**200)
    exp_bound = lambda n: sum(((-r)**k / math.factorial(k) for k in range(n + 1)), F(0))
    p2_bound = lambda n: sum(((-1)**k * (k - 1) * r**k / math.factorial(k)
                             for k in range(2, n + 1)), F(0))
    elo, ehi = exp_bound(5), exp_bound(4)
    plo, phi = p2_bound(5), p2_bound(4)
    assert 0 < plo < phi and phi - plo < r**5
    assert phi - plo == r**5 / 30
    D = (F(1), F(0), F(0))
    alpha = {"a": ((1, 1),) * 3}
    fixed = {"probe": ((F(1), F(0)), (F(1), F(0)), (F(0), F(1)))}
    totals = []
    for label, ee, jump, pp in (("lower", elo, 1 - ehi, plo), ("upper", ehi, 1 - elo, phi)):
        matrix = ((ee, F(0), F(0)), (r * ee, ee, F(0)), (pp, jump, F(1)))

        def transition(dt):
            assert dt in (0, 1)
            return matrix if dt else tuple(tuple(F(i == j) for j in range(3)) for i in range(3))

        left = lattice(D, alpha, fixed, ((0, "a", 0),), 1, transition=transition, raw=True)
        right = brute(D, alpha, fixed, ((0, "a", 0),), 1, transition=transition, raw=True)
        assert left == right
        # P(history)=1/2が厳密に既知なので、区間行列の質量を1に再正規化しない。
        rare_mass = sum(w for (s, _), w in left.items() if s == 2) / HALF
        assert rare_mass == pp
        totals.append(log_fraction(rare_mass))
    near(totals[0], -921.7271843781782)
    near(totals[1], -921.7271843781782)
    # 同じ格子・総当たりで二つの本当の0の対照も計算する。
    zero_controls = []
    for dt in (0, 1):
        # dt=1は2本目の率が0。吸収先s1までの指数を同じ上下界で運ぶ。
        for ee in (elo, ehi):
            matrix = ((ee, F(0), F(0)), (1 - ee, F(1), F(0)), (F(0), F(0), F(1)))
            def disconnected(delta):
                return matrix if delta else tuple(tuple(F(i == j) for j in range(3)) for i in range(3))
            _, control = checked(D, alpha, fixed, ((0, "a", 0),), dt, transition=disconnected)
            assert prediction(control, alpha, fixed, "probe") == (F(1), F(0))
            zero_controls.append(forbidden_cost(prediction(control, alpha, fixed, "probe")))
    assert zero_controls == [F(0)] * 4
    emit("L11 / N6 rational enclosure", inputs(D, alpha, fixed, ((0, "a", 0),), now=1,
         Q="[[-r,0,0],[r,-r,0],[0,r,0]], r=1e-200", forbidden="y"),
         log_endpoint_values=tuple(totals), leading_term="r**2/2 = 5e-401",
         endpoint_note="rational probability bounds are certified; printed logs have binary64 rounding",
         certified_absolute_interval_width="r**5/30 < 1e-1001",
         expected_cost="+inf", only_probe="NoAdmissibleCandidate",
         controls="second rate=0 OR dt=0: q_y=0 exactly, finite cost=0")


def main():
    l1()
    l11_l15()
    l16()
    g1_g3()
    g4_g5()
    g6()  # Claude の既存の3場面・総当たり×Polyaのassertを保持
    g7()
    print("\nAll independent exact lattice/path assertions and published constants passed.")
    print("P8 exception names are expected implementation behavior, not executed sui exceptions.")


if __name__ == "__main__":
    main()
