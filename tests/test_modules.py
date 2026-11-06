"""Every module's starter and solution stay in step with the code the rest of the suite tests.

Whether each starter really fails its check and each solution passes it is `make verify-modules`:
it runs the module's tests against both, so it is too slow to run on every test pass.
"""

import ast
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

from bank_gate.policy import parse_policy

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted(p for p in (ROOT / "modules").iterdir() if p.is_dir())


def files(module, kind):
    base = module / kind
    return sorted(p.relative_to(base) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def starter_policy(module, name):
    return parse_policy(json.loads((ROOT / "modules" / module / "starter/gate/policies" / name).read_text()))


def test_the_hands_on_modules_exist():
    assert [m.name for m in MODULES] == ["01-build", "02-payments", "03-aml", "04-banker"]


def test_every_module_has_a_check_and_every_check_exists():
    checks = dict(re.findall(r"^CHECK_(\d\d) := (.+)$", (ROOT / "Makefile").read_text(), re.MULTILINE))
    assert sorted(checks) == [m.name[:2] for m in MODULES]
    for paths in checks.values():
        assert all((ROOT / p).is_file() for p in paths.split()), paths


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_solution_is_the_code_under_test(module):
    for rel in files(module, "solution"):
        assert (module / "solution" / rel).read_text() == (ROOT / rel).read_text(), f"{rel} differs from {module.name}'s solution"


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.name)
def test_starter_is_a_real_exercise(module):
    assert files(module, "starter") == files(module, "solution")
    marker = f"TODO(module {module.name[:2]})"
    for rel in files(module, "starter"):
        text = (module / "starter" / rel).read_text()
        assert text != (module / "solution" / rel).read_text()
        assert marker in text, f"{rel} has no {marker}"
        if rel.suffix == ".py":
            ast.parse(text)
        else:
            parse_policy(json.loads(text))


def test_the_starter_policies_leave_the_graph_aware_rules_to_write():
    assert {r.id for r in starter_policy("02-payments", "02-payments.json").rules} == {
        "access.payments-writes-for-payments-ops", "pre.decide-releases-as-sanctions-officer"}
    aml = {r.id for r in starter_policy("03-aml", "03-aml.json").rules}
    assert "pre.no-tipping-off" not in aml and "pre.decide-not-the-case-owner" not in aml
    assert "pre.freeze-needs-four-eyes" in aml and "post.mask-pii" in aml
    assert {r.id for r in starter_policy("04-banker", "04-banker.json").rules} == {
        "pre.read-a-deal-only-over-the-wall", "pre.decide-crossings-in-the-control-room"}


def _workshop(root):
    spec = importlib.util.spec_from_file_location("workshop", ROOT / "scripts" / "workshop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.MODULES, module.BACKUP = root, root / "modules", root / ".workshop" / "backup"
    return module


def test_start_and_solve_round_trip_with_a_backup(tmp_path):
    shutil.copytree(ROOT / "modules", tmp_path / "modules")
    target = tmp_path / "agent/bank_agent/evals/checks.py"
    target.parent.mkdir(parents=True)
    target.write_text("# my own attempt\n")
    workshop = _workshop(tmp_path)

    workshop.place("04", "starter")
    assert "TODO(module 04)" in target.read_text()
    [backup] = (tmp_path / ".workshop/backup").rglob("checks.py")
    assert backup.read_text() == "# my own attempt\n"

    workshop.place("4", "solution")
    assert target.read_text() == (ROOT / "agent/bank_agent/evals/checks.py").read_text()
