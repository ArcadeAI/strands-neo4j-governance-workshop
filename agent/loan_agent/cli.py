"""The workshop's commands.

    uv run ask "Which loans are pending?"                 # as LOAN_DESK_USER (alice@bank.example)
    uv run ask --as bob@bank.example "Approve LN-2292"     # as somebody else
    uv run approve --as charlie@bank.example               # the approvals routed to you
    uv run approve --as charlie@bank.example APR-1A2B3C4D approve --note "Collateral checks out"
    uv run tools --as alice@bank.example                   # what Arcade lists for you
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from loan_agent.arcade_tools import ArcadeEngine, ArcadeToolDef, Engine, Outcome
from loan_agent.config import Settings, load_env
from loan_agent.transcript import print_call


def _settings(user: str | None) -> Settings:
    load_env()
    return Settings.from_env(user=user)


def _engine(settings: Settings) -> ArcadeEngine:
    if not settings.arcade_api_key:
        sys.exit("ARCADE_API_KEY is not set. Copy .env.example to .env and fill it in (docs/modules/00-setup.md).")
    return ArcadeEngine.connect(settings.arcade_api_key, settings.arcade_base_url)


def ask_terminal(interrupt: Any) -> str:
    reason = interrupt.reason or {}
    print(f"\n  The agent wants to run {reason.get('tool')} with:", file=sys.stderr)
    print("  " + json.dumps(reason.get("input"), indent=2).replace("\n", "\n  "), file=sys.stderr)
    return input("  Allow it? [y/N] ")


def run_with_confirmation(agent: Callable[[Any], Any], prompt: str, answer: Callable[[Any], str] = ask_terminal) -> Any:
    """Run one turn, stopping for the person whenever a hook interrupts, until the agent finishes."""
    result = agent(prompt)
    while result.stop_reason == "interrupt":
        responses = [{"interruptResponse": {"interruptId": i.id, "response": answer(i)}} for i in result.interrupts]
        result = agent(responses)
    return result


def ask(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ask", description="Ask the loan desk agent something.")
    parser.add_argument("prompt", nargs="+")
    parser.add_argument("--as", dest="user", help="the officer the agent works for (default: LOAN_DESK_USER)")
    parser.add_argument("--session", help="keep the conversation across runs under this name")
    parser.add_argument("--confirm", action="store_true", help="ask before anything is sent outside the bank")
    parser.add_argument("--trace", choices=["console", "otlp"], help="export OpenTelemetry spans")
    parser.add_argument("--quiet", action="store_true", help="do not print the tool calls")
    args = parser.parse_args(argv)

    from loan_agent.agent import build_agent
    from loan_agent.models import provider_of

    settings = _settings(args.user)
    if args.trace:
        from loan_agent import telemetry

        telemetry.setup(args.trace)
    hooks: list[Any] = []
    if args.confirm:
        from loan_agent.confirm import ConfirmOutbound

        hooks.append(ConfirmOutbound(internal=(settings.toolkit,)))
    session = None
    if args.session:
        from strands.session.file_session_manager import FileSessionManager

        session = FileSessionManager(session_id=args.session, storage_dir=".sessions")

    desk = build_agent(settings, hooks=hooks, session_manager=session)
    if not args.quiet:
        desk.transcript.echo = print_call
        connected = "connected to Arcade" if desk.toolbox else "no Arcade key: local tools only"
        print(f"[{settings.user} | model: {provider_of(settings)} | {connected}]", file=sys.stderr)

    result = run_with_confirmation(desk, " ".join(args.prompt))
    print()
    print(str(result).strip())
    for link in desk.links:
        print(f"\nAuthorize here, then ask again: {link}")


def _find(engine: Engine, settings: Settings, name: str) -> ArcadeToolDef | None:
    for definition in engine.list_toolkit(settings.toolkit, settings.user):
        if definition.qualified.split(".", 1)[-1] == name:
            return definition
    return None


def _show(outcome: Outcome) -> Any:
    if outcome.auth_url:
        sys.exit(f"Authorize first: {outcome.auth_url}")
    if outcome.error is not None:
        sys.exit(f"Refused: {outcome.error}")
    value = outcome.value
    return json.loads(value) if isinstance(value, str) and value[:1] in "[{" else value


def approvals(engine: Engine, settings: Settings, request_id: str | None, decision: str | None, note: str | None) -> Any:
    """The human side of the loop, through the same Arcade tools and the same hooks, with no model in between."""
    if request_id is None:
        tool = _find(engine, settings, "ListApprovals")
        if tool is None:
            raise LookupError(f"Arcade lists no {settings.toolkit}.ListApprovals for {settings.user}.")
        return _show(engine.execute(tool, {"status": "pending"}, settings.user))
    tool = _find(engine, settings, "Decide")
    if tool is None:
        raise LookupError(f"Arcade lists no {settings.toolkit}.Decide for {settings.user}: the access policy hides it from you.")
    answer = {"approve": "approved", "approved": "approved", "deny": "denied", "denied": "denied"}.get((decision or "").lower())
    if answer is None:
        raise ValueError("The decision is approve or deny.")
    inputs: dict[str, Any] = {"request_id": request_id, "decision": answer}
    if note:
        inputs["note"] = note
    return _show(engine.execute(tool, inputs, settings.user))


def approve(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="approve", description="List or decide the approval requests routed to you.")
    parser.add_argument("request_id", nargs="?")
    parser.add_argument("decision", nargs="?", choices=["approve", "deny"])
    parser.add_argument("--as", dest="user", help="the officer deciding (default: LOAN_DESK_USER)")
    parser.add_argument("--note", help="why, in a sentence the requester will read")
    args = parser.parse_args(argv)
    if args.request_id and not args.decision:
        parser.error("give a decision: approve or deny")
    settings = _settings(args.user)
    try:
        result = approvals(_engine(settings), settings, args.request_id, args.decision, args.note)
    except (LookupError, ValueError) as exc:
        sys.exit(str(exc))
    print(json.dumps(result, indent=2, default=str))


def tools(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tools", description="What Arcade offers the agent, as one officer.")
    parser.add_argument("task", nargs="*", help="also ask Tool Recommendation for this task")
    parser.add_argument("--as", dest="user")
    args = parser.parse_args(argv)
    settings = _settings(args.user)
    engine = _engine(settings)
    print(f"{settings.toolkit}, as listed for {settings.user}:")
    for definition in engine.list_toolkit(settings.toolkit, settings.user):
        print(f"  {definition.model_name}")
    if args.task:
        query_id, found = engine.select([" ".join(args.task)], settings.user, settings.tools_per_task)
        print(f"\nTool Recommendation (query {query_id or '-'}):")
        for definition in found:
            print(f"  {definition.model_name}")
