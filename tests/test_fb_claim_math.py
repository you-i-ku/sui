"""K28/Z56: the retained interval arithmetic enters U through a reader only.

No host, post, accept, worker, or acquisition is used in these four migrations.
CE1 probabilities come from the paper's eight law rows, not a host result.
"""

from copy import deepcopy

import pytest

from sui import fb_contracts as c, f_update2 as u
from gate_f_facts_cases import plain
from test_fb_update_entry import (
    world, claim, binding, request, compute, adopt, interval, point,
    FIRST, SECOND, DOUBLE,
)


@pytest.mark.parametrize("same_claim", (True, False))
def test_row5_repeated_claim_keeps_every_raw_delivery_without_recounting(same_claim):
    """Same key is redelivery; another key is new but its predicate is entailed.

    Counting the repeated or entailed predicate again changes FIRST/SECOND.
    Every raw delivery remains in this independent reader's record collection.
    """
    reader, w = world()
    q1 = request(reader, "original", w, ["b1"])
    first = compute(reader, q1)
    assert isinstance(first, u.IssuedUpdate) and plain(first.result) == FIRST
    a1 = adopt(reader, "original", w, q1, first)
    original = deepcopy(reader.record(point("report1")).body.content.as_json())
    claim(reader, "repeat-raw", w.k, "slot1" if same_claim else "new-slot", interval(0, 2))
    binding(reader, "repeat-binding", w.k, point("repeat-raw"), w.route)
    repeated_q = request(reader, "repeat", w, ["repeat-binding"], prior=a1)
    repeated = compute(reader, repeated_q)
    assert isinstance(repeated, u.IssuedUpdate) and plain(repeated.result) == FIRST
    if same_claim:
        assert repeated.application_digest == first.application_digest
    a2 = adopt(reader, "repeat", w, repeated_q, repeated, previous=a1)
    final = compute(reader, request(reader, "next", w, ["b2"], prior=a2))
    assert isinstance(final, u.IssuedUpdate) and plain(final.result) == SECOND
    assert plain(final.result) != DOUBLE
    assert reader.record(point("report1")).body.content.as_json() == original
    assert point("report1") != point("repeat-raw")
    assert {point("report1"), point("repeat-raw"), point("report2")} <= reader.records.keys()


def test_row5_later_interval_arriving_first_has_correct_intermediate_and_final_belief():
    """E2 then E1 has weights (1/8,1/32), then (1/16,1/128).

    Sorting interval time or double-counting their overlap fails the two answers.
    """
    reader, w = world()
    first_q = request(reader, "later-interval-first", w, ["b2"])
    first = compute(reader, first_q)
    assert isinstance(first, u.IssuedUpdate) and plain(first.result) == FIRST
    previous = adopt(reader, "later-interval-first", w, first_q, first)
    second = compute(reader, request(reader, "earlier-interval-second", w, ["b1"], prior=previous))
    assert isinstance(second, u.IssuedUpdate) and plain(second.result) == SECOND
    assert plain(second.result) not in (FIRST, DOUBLE)


def test_row5_delayed_reports_keep_their_interval_evidence_and_are_adopted():
    """CE1 interval likelihood uses event intervals, not the age of their receipt.

    Dropping old evidence or using its large received_ns changes FIRST/SECOND.
    This is U arithmetic; host reception is covered by acquisition-path tests.
    """
    reader, w = world()
    previous = None
    for number, expected in ((1, FIRST), (2, SECOND)):
        raw = reader.record(point(f"report{number}"))
        content = deepcopy(raw.body.content.as_json())
        raw.body.received_ns = 10**12 + number
        assert raw.body.received_ns - content["item"]["value"]["interval"]["end_ns"] > 10**11
        q = request(reader, f"delayed-{number}", w, [f"b{number}"], prior=previous)
        result = compute(reader, q)
        assert isinstance(result, u.IssuedUpdate) and plain(result.result) == expected
        assert reader.record(point(f"report{number}")).body.content.as_json() == content
        assert reader.record(point(f"report{number}")).body.received_ns == 10**12 + number
        previous = adopt(reader, f"delayed-{number}", w, q, result, previous=previous)


def test_rowU_model_zero_law_still_adopts_a_normal_claim_outside_the_forced_interval():
    """Forced N((0,1])=1, but P(N((1,2])=0|a,b)=(1/2,1/4).

    Rejecting the entire normalized law fails joint (2/3,1/3), mass 3/8.
    """
    reader, w = world()
    law = deepcopy(reader.record(w.law).body.content.as_json())
    law["rows"] = [
        {"marks": [{"channel": "arrivals", "time_ns": 1, "count": 1}],
         "mass": [[1, 2], [1, 4]]},
        {"marks": [{"channel": "arrivals", "time_ns": 1, "count": 1},
                   {"channel": "arrivals", "time_ns": 2, "count": 1}],
         "mass": [[1, 2], [3, 4]]},
    ]
    reader.put("law", c.FINITE_JOINT_COUNT_LAW, law)
    claim(reader, "outside", w.k, "outside", interval(1, 2))
    binding(reader, "outside-binding", w.k, point("outside"), w.route)
    result = compute(reader, request(reader, "outside-request", w, ["outside-binding"]))
    assert isinstance(result, u.IssuedUpdate)
    assert plain(result.result) == {"joint": [[2, 3], [1, 3]], "evidence_mass": [3, 8]}
