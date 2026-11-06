"""Move between a module's starting point and its solution.

    uv run python scripts/workshop.py list
    uv run python scripts/workshop.py start 01    # put module 01's TODOs in place (your files are backed up first)
    uv run python scripts/workshop.py solve 01    # put module 01's solution in place
    uv run python scripts/workshop.py status      # which files match a starter, a solution, or neither

`make start M=01`, `make solve M=01` and `make check M=01` wrap the same commands.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "modules"
BACKUP = ROOT / ".workshop" / "backup"


def modules() -> dict[str, Path]:
    return {path.name[:2]: path for path in sorted(MODULES.iterdir()) if path.is_dir() and path.name[:2].isdigit()}


def files(module: Path, kind: str) -> list[Path]:
    base = module / kind
    return sorted(p.relative_to(base) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def module_for(number: str) -> Path:
    found = modules().get(number.zfill(2))
    if found is None:
        sys.exit(f"No module {number}. Try: {', '.join(modules())}")
    return found


def place(number: str, kind: str) -> None:
    module = module_for(number)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for rel in files(module, kind):
        target = ROOT / rel
        source = module / kind / rel
        if target.exists() and target.read_bytes() != source.read_bytes():
            backup = BACKUP / stamp / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"  {kind:<8} {rel}")
    if BACKUP.joinpath(stamp).exists():
        print(f"Your previous versions are in {BACKUP.joinpath(stamp).relative_to(ROOT)}/")


def status() -> None:
    for number, module in modules().items():
        for rel in files(module, "solution"):
            live = (ROOT / rel).read_bytes() if (ROOT / rel).exists() else b""
            if live == (module / "solution" / rel).read_bytes():
                state = "solved"
            elif (module / "starter" / rel).exists() and live == (module / "starter" / rel).read_bytes():
                state = "starter"
            else:
                state = "edited"
            print(f"  {number}  {state:<8} {rel}")


def main(argv: list[str]) -> None:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return
    command, rest = argv[0], argv[1:]
    if command == "list":
        for number, module in modules().items():
            print(f"  {number}  {module.name}: {', '.join(str(p) for p in files(module, 'starter'))}")
    elif command in {"start", "solve"} and rest:
        place(rest[0], "starter" if command == "start" else "solution")
    elif command == "status":
        status()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
