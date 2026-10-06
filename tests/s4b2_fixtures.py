"""Shared, session-scoped specification oracles for S4b-2 tests."""
from fractions import Fraction as F

import pytest

from s4b2_information_oracle import certified_information


@pytest.fixture(scope="session")
def s4b2_independent_information():
    """Compute all four roots once, preserving the original error guarantees."""
    before = certified_information.cache_info()
    values, diagnostics = certified_information()
    after = certified_information.cache_info()
    assert after.misses - before.misses == (0 if before.currsize else 1)
    assert diagnostics["head_upper"] > 0 and diagnostics["tail_upper"] > 0
    assert all(width <= F(1, 10**10) for width in diagnostics["quadrature_widths"])
    yield values
    # Any future direct caller must reuse this same cached calculation too.
    assert certified_information.cache_info().misses == after.misses
