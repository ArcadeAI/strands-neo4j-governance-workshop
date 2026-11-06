"""What every Bank tool shares: who is calling, tool metadata, and turning graph errors into answers."""

# No `from __future__ import annotations` in a tools module: arcade-core reads each parameter's
# annotation as a live type to find the context argument and build the tool's schema.

from collections.abc import Awaitable
from typing import Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context
from arcade_mcp_server.metadata import Behavior, Operation, ToolMetadata

from bank_tools.graph import Conflict, NotFound

READ = ToolMetadata(
    behavior=Behavior(operations=[Operation.READ], read_only=True, destructive=False, idempotent=True, open_world=False),
)
WRITE = ToolMetadata(
    behavior=Behavior(operations=[Operation.UPDATE], read_only=False, destructive=False, idempotent=False, open_world=False),
)


def actor_of(context: Context) -> str:
    """Who Arcade executed this call as. A call with nobody behind it does nothing."""
    actor = (context.user_id or "").strip().lower()
    if not actor:
        raise ToolExecutionError(
            "Arcade did not say who is calling, so nothing was read or written.",
            developer_message="context.user_id was empty.",
        )
    return actor


async def graph_call(call: Awaitable[Any], what: str) -> Any:
    """Await one graph operation, with a missing node or a refused write as the tool's own error."""
    try:
        return await call
    except NotFound as exc:
        raise ToolExecutionError(f"There is no {what} {exc.args[0]}.") from exc
    except Conflict as exc:
        raise ToolExecutionError(str(exc)) from exc
