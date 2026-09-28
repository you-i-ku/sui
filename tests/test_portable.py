import ast
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from sui import agent, loop, s1_contracts
from sui.clock import FakeClock
from sui.contracts import ContractBook, ContractRef, UnknownContract
from sui.ids import Ref, RefKind, SequentialIds
from sui.records import Producer
from sui.ledger import Ledger, SequentialSalts, RECORD_SCHEMA
from worlds import ScriptedWorld, _model


ROOT = Path(__file__).resolve().parents[1]


def _actual_records():
    subject = agent.Agent(model=_model(learnable=frozenset({"look1"})), lineage="portable")
    clock = FakeClock(run=Ref(RefKind.RUN, "portable"))
    ids = SequentialIds()
    records = Ledger(salts=SequentialSalts())
    subject.belief_record(clock=clock, ids=ids, ledger=records)
    loop.run_step(subject, ScriptedWorld({"look1": ["o1"]}), ["look1"], u=.5,
                  clock=clock, ids=ids, ledger=records,
                  membrane=Producer(component="test.executor", code_version="1"))
    return [records.record(e.cid) for e in records.entries()]


def test_c1_all_actual_record_contracts_are_declared_and_resolvable():
    expected = {("sui.s1.belief", "3"), ("sui.s1.decision", "2"),
                ("sui.s1.action", "1"), ("sui.s1.outcome", "2"), ("sui.s1.attempt", "1")}
    assert {(c.ref.name, c.ref.version) for c in s1_contracts.DECLARATIONS} == expected
    assert len(s1_contracts.DECLARATIONS) == 5
    assert isinstance(s1_contracts.DECLARATIONS, tuple)
    assert [c.ref.name for c in s1_contracts.DECLARATIONS] == [
        "sui.s1.belief", "sui.s1.decision", "sui.s1.action", "sui.s1.outcome", "sui.s1.attempt",
    ]
    book = ContractBook()
    for declaration in s1_contracts.DECLARATIONS:
        book.register(declaration)
        assert book.get(declaration.ref) is declaration
    assert RECORD_SCHEMA.ref == ContractRef("sui.record", "2")
    book.register(RECORD_SCHEMA)
    assert book.get(RECORD_SCHEMA.ref) is RECORD_SCHEMA
    records = _actual_records()
    assert len(records) == 6
    assert {(r.body.contract.name, r.body.contract.version) for r in records} == expected
    for record in records:
        assert book.get(record.body.contract).ref == record.body.contract
    for omitted in s1_contracts.DECLARATIONS:
        partial = ContractBook()
        for declaration in s1_contracts.DECLARATIONS:
            if declaration is not omitted:
                partial.register(declaration)
        affected = [record for record in records if record.body.contract == omitted.ref]
        assert affected
        for record in affected:
            with pytest.raises(UnknownContract):
                partial.get(record.body.contract)
    old_book = ContractBook()
    old_book.register(replace(book.get(ContractRef("sui.s1.belief", "3")),
                              ref=ContractRef("sui.s1.belief", "1")))
    with pytest.raises(UnknownContract):
        old_book.get(records[0].body.contract)


def test_c1_contract_aliases_are_the_same_objects():
    assert agent.BELIEF is s1_contracts.BELIEF
    assert agent.DECISION is s1_contracts.DECISION
    assert agent.ACTION is s1_contracts.ACTION
    assert loop.OUTCOME is s1_contracts.OUTCOME
    assert loop.ATTEMPT is s1_contracts.ATTEMPT


def test_c1_importing_agent_does_not_import_loop():
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", 'import sys; import sui.agent; assert "sui.loop" not in sys.modules'],
        cwd=ROOT / "src", capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_c1_meanings_describe_content_shapes():
    keys = {
        "sui.s1.belief": {"model", "states", "outcomes", "q", "a", "n", "unread"},
        "sui.s1.decision": {"candidates", "risk", "ambiguity", "novelty", "G", "q_o", "q_pi", "gamma", "u", "chosen"},
        "sui.s1.action": {"action"}, "sui.s1.outcome": {"outcome"}, "sui.s1.attempt": {"{}"},
    }
    for declaration in s1_contracts.DECLARATIONS:
        for key in keys[declaration.ref.name]:
            assert key in declaration.meaning
    belief = next(declaration for declaration in s1_contracts.DECLARATIONS
                  if declaration.ref == ContractRef("sui.s1.belief", "3"))
    assert "D の 0" in belief.meaning
    assert "事前の 0 は 0 のまま" in belief.meaning


def test_c2_dependencies_match_requirements_and_external_imports():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = dict(item.split("==") for item in project["dependencies"])
    requirements = dict(line.strip().split("==") for line in
                        (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.lstrip().startswith("#"))
    assert {name: dependencies[name] for name in ("numpy", "scipy")} == {
        name: requirements[name] for name in ("numpy", "scipy")
    }
    external = set()
    for path in (ROOT / "src" / "sui").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                external.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                external.add(node.module.split(".")[0])
    external -= sys.stdlib_module_names | {"sui"}
    assert external == {"numpy", "scipy"}
    assert external <= dependencies.keys()


def test_c3_core_and_tests_do_not_depend_on_backup():
    for directory in (ROOT / "src" / "sui", ROOT / "tests"):
        for path in directory.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                assert not any(name.startswith(("sui_backup", "backup")) for name in names), path
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
    assert "backup" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
