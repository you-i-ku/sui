"""件数の述語の連言による条件づけ (`sui._f_count`) の試験。段 3 の最初の輪の 1 本目。

答え合わせの相手は紙 F-b の CE1 (:3497「期待は (8/9, 1/9; 9/128)」) の数。2 つの重なる「到着なし」の
報告を、独立な尤度の積にせず、述語の連言で条件づける。
"""

from fractions import Fraction as F

import pytest

from sui import _f_count as count
from sui.f import FInputError

CLOCK = "run-1"
DOMAIN = count.Span(CLOCK, 0, 3, "(start,end]")
# carrier a は 3 つの時刻の到着が一様 (各行 1/8)、carrier b は各時刻で独立に確率 3/4 で到着
CE1_ROWS = (
    ((0, 0, 0), F(1, 8), F(1, 64)),
    ((0, 0, 1), F(1, 8), F(3, 64)),
    ((0, 1, 0), F(1, 8), F(3, 64)),
    ((0, 1, 1), F(1, 8), F(9, 64)),
    ((1, 0, 0), F(1, 8), F(3, 64)),
    ((1, 0, 1), F(1, 8), F(9, 64)),
    ((1, 1, 0), F(1, 8), F(9, 64)),
    ((1, 1, 1), F(1, 8), F(27, 64)),
)
STATES = ("a", "b")
PRIOR = (F(1, 2), F(1, 2))
E1 = count.Predicate("arrivals", count.Span(CLOCK, 0, 2, "(start,end]"), 0, 0)   # 時刻 1・2 に到着なし
E2 = count.Predicate("arrivals", count.Span(CLOCK, 1, 3, "(start,end]"), 0, 0)   # 時刻 2・3 に到着なし (E1 と重なる)
FIRST = ((F(4, 5), F(1, 5)), F(5, 32))
SECOND = ((F(8, 9), F(1, 9)), F(9, 128))
DOUBLE = ((F(16, 17), F(1, 17)), F(17, 512))   # 誤り: 2 つの報告を独立な尤度として掛けた値


def ce1_law():
    rows = [([("arrivals", i + 1, n) for i, n in enumerate(bits) if n], (a, b)) for bits, a, b in CE1_ROWS]
    return count.check_law(STATES, {"arrivals": DOMAIN}, rows)


def test_ce1_two_overlapping_reports_condition_on_the_conjunction():
    """1 回目は (4/5, 1/5; 5/32)、2 回目は (8/9, 1/9; 9/128)。重なりを二重に数えた値や、2 回目を
    無視した値にならない。"""
    law = ce1_law()
    first = count.condition(PRIOR, F(1), STATES, law, (), E1)
    assert first == FIRST
    second = count.condition(*first, STATES, law, (E1,), E2)
    assert second == SECOND
    assert second != DOUBLE and second != FIRST


def test_ignoring_the_applied_claims_gives_the_double_counted_value():
    """適用済みの述語を渡さない (= 独立に掛ける) と DOUBLE になる。condition が applied を使っている
    ことの対照。"""
    law = ce1_law()
    assert count.condition(*FIRST, STATES, law, (), E2) == DOUBLE


def test_order_of_the_two_reports_does_not_change_the_result():
    law = ce1_law()
    other = count.condition(PRIOR, F(1), STATES, law, (), E2)
    assert count.condition(*other, STATES, law, (E2,), E1) == SECOND


def test_same_report_applied_twice_changes_nothing():
    """同じ述語をもう一度条件づけても joint も evidence_mass も変わらない (同じ証拠を 2 回数えない)。"""
    law = ce1_law()
    assert count.condition(*FIRST, STATES, law, (E1,), E1) == FIRST


def test_states_sharing_a_carrier_keep_their_relative_weights():
    """状態と carrier は別。同じ carrier の 2 状態は同じ比で動き、別の carrier の状態だけ比が変わる。"""
    law = ce1_law()
    states = ("a", "b", "a")
    joint, evidence = count.condition((F(1, 4), F(1, 2), F(1, 4)), F(1), states, law, (), E1)
    assert evidence == F(5, 32)
    assert joint == (F(2, 5), F(1, 5), F(2, 5))


def test_empty_conjunction_has_full_mass_and_mass_uses_every_predicate():
    law = ce1_law()
    assert count.mass(law, ()) == (F(1), F(1))
    assert count.mass(law, (E1,)) == (F(1, 4), F(1, 16))
    assert count.mass(law, (E2,)) == (F(1, 4), F(1, 16))
    assert count.mass(law, (E1, E2)) == (F(1, 8), F(1, 64))


@pytest.mark.parametrize("closure, expected", [
    ("(start,end]", (False, True, True)),
    ("[start,end)", (True, True, False)),
    ("[start,end]", (True, True, True)),
    ("(start,end)", (False, True, False)),
])
def test_span_endpoints_follow_the_closure(closure, expected):
    span = count.Span(CLOCK, 1, 3, closure)
    assert (span.contains(1), span.contains(2), span.contains(3)) == expected
    assert not span.contains(0) and not span.contains(4)


def test_holds_counts_only_the_predicates_channel_and_interval():
    marks = (("arrivals", 1, 2), ("arrivals", 3, 1), ("other", 2, 5))
    inside = count.Span(CLOCK, 0, 2, "(start,end]")
    assert count.holds(marks, count.Predicate("arrivals", inside, 2, 2))
    assert not count.holds(marks, count.Predicate("arrivals", inside, 0, 1))
    assert not count.holds(marks, count.Predicate("arrivals", inside, 3, 9))
    assert count.holds(marks, count.Predicate("other", inside, 5, 5))


def test_span_covers_respects_clock_and_open_ends():
    assert DOMAIN.covers(count.Span(CLOCK, 0, 3, "(start,end]"))
    assert not DOMAIN.covers(count.Span(CLOCK, 0, 3, "[start,end]"))   # 0 は domain の外
    assert not DOMAIN.covers(count.Span(CLOCK, 1, 4, "(start,end]"))
    assert not DOMAIN.covers(count.Span("run-2", 1, 2, "(start,end]"))


@pytest.mark.parametrize("rows, reason", [
    ([([], (F(1, 2), F(1)))], "normalization"),                      # carrier a の質量の和が 1 でない
    ([([], (F(1), F(1), F(0)))], "normalization"),                   # 列の数が carrier の数と違う
    ([([("arrivals", 4, 1)], (F(1), F(1)))], "shape"),               # domain の外の印
    ([([("arrivals", 1, 0)], (F(1), F(1)))], "shape"),               # 件数 0 の印
    ([([("nowhere", 1, 1)], (F(1), F(1)))], "shape"),                # 宣言の無い channel
])
def test_check_law_rejects_malformed_tables(rows, reason):
    with pytest.raises(FInputError) as error:
        count.check_law(STATES, {"arrivals": DOMAIN}, rows)
    assert error.value.reason == reason


def test_check_law_merges_marks_at_the_same_position():
    rows = [([("arrivals", 1, 1), ("arrivals", 1, 2)], (F(1), F(1)))]
    law = count.check_law(STATES, {"arrivals": DOMAIN}, rows)
    assert law.rows == (((("arrivals", 1, 3),), (F(1), F(1))),)


@pytest.mark.parametrize("predicate", [
    count.Predicate("arrivals", count.Span(CLOCK, 0, 4, "(start,end]"), 0, 0),   # domain をはみ出す
    count.Predicate("nowhere", count.Span(CLOCK, 0, 2, "(start,end]"), 0, 0),    # 宣言の無い channel
    count.Predicate("arrivals", count.Span(CLOCK, 0, 2, "(start,end]"), 2, 1),   # lower > upper
    count.Predicate("arrivals", count.Span(CLOCK, 0, 2, "(start,end]"), -1, 1),  # 負の下限
])
def test_condition_rejects_predicates_outside_the_law(predicate):
    with pytest.raises(FInputError) as error:
        count.condition(PRIOR, F(1), STATES, ce1_law(), (), predicate)
    assert error.value.reason == "shape"


def test_weight_on_an_excluded_carrier_is_an_input_error():
    """適用済みの述語が質量 0 にした carrier に重みが残っている joint は、作り直した状態ではありえない。"""
    rows = [([], (F(1), F(0))), ([("arrivals", 1, 1)], (F(0), F(1)))]   # a は必ず到着なし、b は必ず到着
    law = count.check_law(STATES, {"arrivals": DOMAIN}, rows)
    none = count.Predicate("arrivals", count.Span(CLOCK, 0, 1, "(start,end]"), 0, 0)
    assert count.condition(PRIOR, F(1), STATES, law, (), none) == ((F(1), F(0)), F(1, 2))
    with pytest.raises(FInputError) as error:
        count.condition(PRIOR, F(1), STATES, law, (none,), none)
    assert error.value.reason == "normalization"


def test_zero_evidence_is_loud_and_not_yet_classified():
    """全体の質量が 0 になる条件づけは、成功にも小さい数にもせず止まる (区別は 1 周の後の ★)。"""
    rows = [([("arrivals", 1, 1)], (F(1), F(1)))]   # どの carrier でも必ず到着する
    law = count.check_law(STATES, {"arrivals": DOMAIN}, rows)
    none = count.Predicate("arrivals", count.Span(CLOCK, 0, 1, "(start,end]"), 0, 0)
    with pytest.raises(NotImplementedError):
        count.condition(PRIOR, F(1), STATES, law, (), none)
