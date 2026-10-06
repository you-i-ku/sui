"""S4b-2 section 16: canonical bytes of C1 evaluation and public selection."""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import fields
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from sui import rate, rate_entry
from sui.contracts import ContractRef
from s4b2_worlds import CANDIDATES, c1_world, evaluation_root


EVALUATION_SHA256 = "b801dd7937f6b076ad0a8e1a33403b77fca7571d795c6df2ab9c19042975d38e"
CERTIFICATE_SHA256 = "31096989f6481b89e7e0f72ab7ab67240b13662773101696e712940ff6c0aade"
DECISION_SHA256 = "32aedf535310238c328c9cbc8f3f63895176c84d2a9ac1699992581d74fd5460"


def json_value(value):
    """Encode the public types and certificate scheme from section 3-10."""
    if isinstance(value, F):
        return [value.numerator, value.denominator]
    if isinstance(value, (rate.RationalInterval, rate.RateBudget,
                          rate.CertifiedQuantity, rate.Certificate, ContractRef)):
        result = {field.name: json_value(getattr(value, field.name))
                  for field in fields(value)}
        if isinstance(value, rate.Certificate):
            result["scheme"] = "sui.s4b.rate_certificate.1"
        return result
    if isinstance(value, Mapping):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(type(value))


def canonical(value):
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def evaluation_json(evaluation):
    names = ("expected_cost", "information", "G", "J", "q_star")
    return {
        "values": [
            {"candidate": candidate,
             **{name: json_value(getattr(evaluation, name)[index]) for name in names}}
            for index, candidate in enumerate(evaluation.candidates)
        ],
        "certificate": json_value(evaluation.certificate),
    }


def fixed_input():
    # Clock provenance contributes to ledger references; it is fixed fixture
    # data, independent of the Python version running this test.
    with patch("s4b2_worlds.platform.python_version", return_value="3.12.10"):
        return evaluation_root(c1_world(0))


def assert_sha256(value, expected):
    assert hashlib.sha256(canonical(value)).hexdigest() == expected


def test_c1_n0_evaluation_and_certificate_canonical_bytes():
    view, resolved = fixed_input()
    evaluation = rate.evaluate_rate(
        view, CANDIDATES, resolved, budget=rate.default_rate_budget(),
    )
    payload = evaluation_json(evaluation)
    certificate = payload["certificate"]
    assert json_value(evaluation.cumulative) == certificate["enclosures"]["cumulative"]
    assert_sha256(payload, EVALUATION_SHA256)
    assert_sha256(certificate, CERTIFICATE_SHA256)

    changed = deepcopy(payload)
    bounds = changed["values"][0]["q_star"]["bounds"]
    bounds["upper"] = json_value(F(*bounds["upper"]) + F(1, 2**80))
    with pytest.raises(AssertionError):
        assert_sha256(changed, EVALUATION_SHA256)

    changed = deepcopy(certificate)
    changed["trace"][0], changed["trace"][1] = changed["trace"][1], changed["trace"][0]
    with pytest.raises(AssertionError):
        assert_sha256(changed, CERTIFICATE_SHA256)


def test_c1_n0_public_selection_canonical_bytes():
    view, resolved = fixed_input()
    content = rate_entry.public_evaluate(
        view, CANDIDATES, resolved, u=F(3, 5), budget=rate.default_rate_budget(),
    ).content.as_json()
    assert_sha256(content, DECISION_SHA256)

    changed = json_value(content)
    boundary = changed["selection"]["current"]
    boundary[1] = json_value(F(*boundary[1]) + F(1, 2**80))
    with pytest.raises(AssertionError):
        assert_sha256(changed, DECISION_SHA256)


FALLBACK_SCRIPT = r'''
import importlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path[:0] = [str(root / "src"), str(root / "tests")]
assert not any(name == "sui" or name.startswith("sui.") for name in sys.modules)
assert not any(name == "gmpy2" or name.startswith("gmpy2.") for name in sys.modules)
sys.modules["gmpy2"] = None

def assert_gmpy2_unavailable():
    assert sys.modules.get("gmpy2") is None
    assert not any(name.startswith("gmpy2.") for name in sys.modules)
    try:
        importlib.import_module("gmpy2")
    except ModuleNotFoundError as error:
        assert error.name == "gmpy2"
    else:
        raise AssertionError("gmpy2 was importable in the fallback process")

assert_gmpy2_unavailable()
from test_s4b2_bytes import (
    test_c1_n0_evaluation_and_certificate_canonical_bytes,
    test_c1_n0_public_selection_canonical_bytes,
)
assert_gmpy2_unavailable()
test_c1_n0_evaluation_and_certificate_canonical_bytes()
assert_gmpy2_unavailable()
test_c1_n0_public_selection_canonical_bytes()
assert_gmpy2_unavailable()
print("gmpy2 unavailable; evaluation, certificate and decision bytes verified")
'''


def test_c1_n0_canonical_bytes_without_gmpy2():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", FALLBACK_SCRIPT, str(root)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "gmpy2 unavailable; evaluation, certificate and decision bytes verified"
    )
