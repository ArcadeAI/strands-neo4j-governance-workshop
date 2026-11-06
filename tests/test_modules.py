"""Every module's starter and solution stay in step with the code the rest of the suite tests."""

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from loan_gate.policy import apply_post, parse_policy

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted(p for p in (ROOT / "modules").iterdir() if p.is_dir())


def files(module, kind):
    base = module / kind
    return sorted(p.relative_to(base) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_the_hands_on_modules_exist():
    assert [m.name for m in MODULES] == ["01-build", "02-connect", "03-govern", "04-ship"]


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


def test_the_starter_policy_leaves_the_post_rules_to_write():
    starter = parse_policy(json.loads((ROOT / "modules/03-govern/starter/gate/policy.json").read_text()))
    _, applied = apply_post(starter, "GetLoan", {"email": "alice@bank.example", "clearance": 50000}, {"tax_id": "1"})
    assert applied == []


def _workshop(root):
    spec = importlib.util.spec_from_file_location("workshop", ROOT / "scripts" / "workshop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT, module.MODULES, module.BACKUP = root, root / "modules", root / ".workshop" / "backup"
    return module


def test_start_and_solve_round_trip_with_a_backup(tmp_path):
    shutil.copytree(ROOT / "modules", tmp_path / "modules")
    target = tmp_path / "agent/loan_agent/evals/checks.py"
    target.parent.mkdir(parents=True)
    target.write_text("# my own attempt\n")
    workshop = _workshop(tmp_path)

    workshop.place("04", "starter")
    assert "TODO(module 04)" in target.read_text()
    [backup] = (tmp_path / ".workshop/backup").rglob("checks.py")
    assert backup.read_text() == "# my own attempt\n"

    workshop.place("4", "solution")
    assert target.read_text() == (ROOT / "agent/loan_agent/evals/checks.py").read_text()
