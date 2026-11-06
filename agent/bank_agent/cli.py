"""The workshop's commands.

    uv run ask "What is 2,500 EUR in dollars?"                       # the module 01 assistant
    uv run ask --desk payments "Work PMT-5001"                       # as pat@bank.example
    uv run ask --desk aml "Investigate CASE-7001 and freeze the subject's account"   # as ava@bank.example
    uv run ask --desk banker "Brief me on Lakeside Bakehouse"        # as ian@bank.example
    uv run ask --desk banker --as mia@bank.example "Brief me on Lakeside Bakehouse"
    uv run approve --as sana@bank.example                            # the approvals routed to you
    uv run approve --as sana@bank.example APR-1A2B3C4D approve --note "Spoke to the originator"
    uv run approve --as cora@bank.example APR-... approve --hours 2  # a wall-crossing for two hours
    uv run tools --as ian@bank.example                               # what Arcade lists for you
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from bank_agent.arcade_tools import ArcadeEngine, ArcadeToolDef, Engine, Outcome
from bank_agent.config import DESKS, Settings, load_env
from bank_agent.transcript import print_call


def _settings(user: str | None, desk: str = "assistant") -> Settings:
    load_env()
    return Settings.from_env(user=user, desk=desk)


def _engine(settings: Settings) -> ArcadeEngine:
    if not settings.arcade_api_key:
        sys.exit("ARCADE_API_KEY is not set. Copy .env.example to .env and fill it in (docs/modules/02-payments.md, step 4).")
    return ArcadeEngine.connect(settings.arcade_api_key, settings.arcade_base_url)


def ask_terminal(interrupt: Any) -> str:
    reason = interrupt.reason or {}
    print(f"\n  The agent wants to run {reason.get('tool')} with:", file=sys.stderr)
    print("  " + json.dumps(reason.get("input"), indent=2).replace("\n", "\n  "), file=sys.stderr)
    return input("  Allow it? [y/N] ")


def run_with_confirmation(agent: Callable[[Any], Any], prompt: str, answer: Callable[[Any], str] = ask_terminal) -> Any:
    """Run one turn, stopping for the person whenever a hook interrupts, until the agent or desk finishes."""
    result = agent(prompt)
    while result.stop_reason == "interrupt":
        responses = [{"interruptResponse": {"interruptId": i.id, "response": answer(i)}} for i in result.interrupts]
        result = agent(responses)
    return result


def build(settings: Settings, *, confirm: bool = False, session: str | None = None) -> Any:
    """The assistant or a desk for `settings.desk`, as the CLI runs it."""
    if settings.desk == "assistant":
        from bank_agent.agent import build_agent

        hooks: list[Any] = []
        if confirm:
            from bank_agent.confirm import ConfirmActions

            hooks.append(ConfirmActions(internal=(settings.toolkit,)))
        manager = None
        if session:
            from strands.session.file_session_manager import FileSessionManager

            manager = FileSessionManager(session_id=session, storage_dir=".sessions")
        return build_agent(settings, hooks=hooks, session_manager=manager)
    from bank_agent.desks import builder

    return builder(settings.desk)(settings)


def ask(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ask", description="Ask Bowser Capital's assistant, or hand a task to a desk.")
    parser.add_argument("prompt", nargs="+")
    parser.add_argument("--desk", choices=DESKS, default="assistant", help="which desk takes the task (default: the assistant)")
    parser.add_argument("--as", dest="user", help="the employee the agents work for (default: BANK_USER, or the desk's usual employee)")
    parser.add_argument("--session", help="assistant only: keep the conversation across runs under this name")
    parser.add_argument("--confirm", action="store_true", help="assistant only: ask before anything is sent outside the bank")
    parser.add_argument("--trace", choices=["console", "otlp"], help="export OpenTelemetry spans")
    parser.add_argument("--quiet", action="store_true", help="do not print the tool calls")
    args = parser.parse_args(argv)

    from bank_agent.models import provider_of

    settings = _settings(args.user, args.desk)
    if args.trace:
        from bank_agent import telemetry

        telemetry.setup(args.trace)
    desk = build(settings, confirm=args.confirm, session=args.session)
    if not args.quiet:
        desk.transcript.echo = print_call
        connected = "connected to Arcade" if desk.toolbox else "no Arcade key: local tools only"
        print(f"[{settings.desk} | {settings.user} | model: {provider_of(settings)} | {connected}]", file=sys.stderr)

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


def approvals(engine: Engine, settings: Settings, request_id: str | None, decision: str | None, note: str | None,
              hours: int | None = None) -> Any:
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
    if hours is not None:
        inputs["hours"] = hours
    return _show(engine.execute(tool, inputs, settings.user))


def approve(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="approve", description="List or decide the approval requests routed to you.")
    parser.add_argument("request_id", nargs="?")
    parser.add_argument("decision", nargs="?", choices=["approve", "deny"])
    parser.add_argument("--as", dest="user", required=True, help="the officer deciding, for example sana@bank.example")
    parser.add_argument("--note", help="why, in a sentence the requester will read")
    parser.add_argument("--hours", type=int, help="for a wall-crossing: how long it lasts (default 4, at most 24)")
    args = parser.parse_args(argv)
    if args.request_id and not args.decision:
        parser.error("give a decision: approve or deny")
    settings = _settings(args.user)
    try:
        result = approvals(_engine(settings), settings, args.request_id, args.decision, args.note, args.hours)
    except (LookupError, ValueError) as exc:
        sys.exit(str(exc))
    print(json.dumps(result, indent=2, default=str))


def tools(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tools", description="What Arcade offers the agent, as one employee.")
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
