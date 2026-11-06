"""One row per decision the gate makes, in a file, in memory, and on the terminal.

The terminal is the workshop's live view: leave `uv run gate` in a window you can see, and
every access listing, refusal, grant and redaction lands there as it happens. The same rows
go to `.gate/audit.jsonl` and to `GET /audit`, which the evals read.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COLOURS = {"allowed": "32", "granted": "36", "denied": "31", "hidden": "33", "redacted": "35", "passed": "90"}


class AuditLog:
    def __init__(self, path: Path | str | None = None, *, echo: bool = True, keep: int = 1000) -> None:
        self.rows: deque[dict[str, Any]] = deque(maxlen=keep)
        self._path = Path(path) if path else None
        self._echo = echo
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **row: Any) -> dict[str, Any]:
        row = {"ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"), **row}
        self.rows.append(row)
        if self._path:
            with self._path.open("a") as f:
                f.write(json.dumps(row) + "\n")
        if self._echo:
            outcome = row.get("outcome", "")
            colour = COLOURS.get(outcome, "0")
            rule = f" [{row['rule']}]" if row.get("rule") else ""
            detail = f" {row['detail']}" if row.get("detail") else ""
            line = f"\033[{colour}m{row.get('hook', ''):>6} {outcome:<8}\033[0m {row.get('user_id', '-')} {row.get('tool', '')}{rule}{detail}"
            print(line, file=sys.stderr, flush=True)
        return row

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.rows)[-limit:]
