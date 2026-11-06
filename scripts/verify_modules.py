"""Every module's starter fails its check and every solution passes it.

    uv run python scripts/verify_modules.py          # all modules
    uv run python scripts/verify_modules.py 02 03    # some of them

For each module: put the starter in place and run `make check M=NN`'s tests, which must fail;
put the solution in place and run them again, which must pass. Your working files are put back
afterwards, whatever happens.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"


def checks() -> dict[str, list[str]]:
    found = re.findall(r"^CHECK_(\d\d) := (.+)$", (ROOT / "Makefile").read_text(), re.MULTILINE)
    return {number: paths.split() for number, paths in found}


def files(module: Path, kind: str) -> list[Path]:
    base = module / kind
    return sorted(p.relative_to(base) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def place(module: Path, kind: str) -> None:
    for rel in files(module, kind):
        shutil.copy2(module / kind / rel, ROOT / rel)


def passes(tests: list[str]) -> bool:
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
                         cwd=ROOT, capture_output=True, text=True, check=False)
    return run.returncode == 0


def verify(number: str, tests: list[str]) -> list[str]:
    module = next(MODULES.glob(f"{number}-*"))
    problems = []
    with tempfile.TemporaryDirectory() as saved:
        for rel in files(module, "solution"):
            (Path(saved) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, Path(saved) / rel)
        try:
            place(module, "starter")
            if passes(tests):
                problems.append(f"{module.name}: the starter passes {' '.join(tests)}")
            place(module, "solution")
            if not passes(tests):
                problems.append(f"{module.name}: the solution fails {' '.join(tests)}")
        finally:
            for rel in files(module, "solution"):
                shutil.copy2(Path(saved) / rel, ROOT / rel)
    print(f"  {module.name:<12} {'ok' if not problems else 'FAILED'}")
    return problems


def main(argv: list[str]) -> None:
    wanted = checks()
    numbers = [n.zfill(2) for n in argv] or sorted(wanted)
    problems = [p for number in numbers for p in verify(number, wanted[number])]
    if problems:
        sys.exit("\n".join(problems))
    print("Every starter fails its check and every solution passes it.")


if __name__ == "__main__":
    main(sys.argv[1:])
