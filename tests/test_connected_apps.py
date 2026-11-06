"""Tools found at run time through Tool Recommendation, OAuth links, and asking before sending."""

from bank_agent.agent import build_agent
from bank_agent.cli import run_with_confirmation
from bank_agent.config import Settings
from bank_agent.confirm import ConfirmActions
from bank_agent.scripted import Call, ScriptedModel, steps

ME = "attendee@company.example"
SETTINGS = Settings(user="pat@bank.example", connected_apps_user=ME)
FIND = Call("arcade_select_tools", {"tasks": ["send sana a slack dm"]})
SEND = Call("Slack_SendDmToUser", {"user_name": "sana.ortiz", "message": "APR waiting on you"})


def test_selected_tools_are_callable_on_the_next_step(arcade):
    arcade.authorize("Slack", ME)
    desk = build_agent(SETTINGS, model=ScriptedModel(steps(FIND, SEND)), engine=arcade)
    desk("tell sana")
    found, sent = desk.transcript.calls
    assert "Slack_SendDmToUser" in found.text
    assert not sent.refused
    assert "Slack_SendDmToUser" not in desk.agent.model.seen_tools[0]
    assert "Slack_SendDmToUser" in desk.agent.model.seen_tools[1]
    assert arcade.apps[0].sent == [{"tool": "SendDmToUser", "user_id": ME, "user_name": "sana.ortiz", "message": "APR waiting on you"}]


def test_first_use_returns_a_link_for_the_person(arcade):
    desk = build_agent(SETTINGS, model=ScriptedModel(steps(FIND, SEND)), engine=arcade)
    desk("tell sana")
    assert desk.transcript.calls[1].refused and "AUTHORIZATION REQUIRED" in desk.transcript.calls[1].text
    assert desk.links == [f"https://example.invalid/authorize/slack?user={ME}"]
    assert arcade.apps[0].sent == []


def test_nothing_new_found_is_said_plainly(arcade):
    desk = build_agent(SETTINGS, model=ScriptedModel(steps(Call("arcade_select_tools", {"tasks": ["order lunch"]}))), engine=arcade)
    desk("lunch?")
    assert "No new tools" in desk.transcript.calls[0].text


def _confirmed(arcade, answer):
    arcade.authorize("Slack", ME)
    desk = build_agent(SETTINGS, model=ScriptedModel(steps(FIND, SEND)), engine=arcade, hooks=[ConfirmActions()])
    asked = []
    run_with_confirmation(desk, "tell sana", lambda interrupt: asked.append(interrupt.reason) or answer)
    return desk, asked


def test_outbound_messages_wait_for_a_yes(arcade):
    _, asked = _confirmed(arcade, "y")
    assert asked == [{"tool": "Slack_SendDmToUser", "input": {"user_name": "sana.ortiz", "message": "APR waiting on you"}}]
    assert len(arcade.apps[0].sent) == 1


def test_a_no_means_nothing_is_sent(arcade):
    desk, _ = _confirmed(arcade, "n")
    assert arcade.apps[0].sent == []
    assert "declined" in desk.transcript.calls[-1].text


def test_bank_calls_are_not_interrupted(arcade):
    desk = build_agent(SETTINGS, model=ScriptedModel(), engine=arcade, hooks=[ConfirmActions()])
    result = run_with_confirmation(desk, "exceptions?", lambda _: (_ for _ in ()).throw(AssertionError("asked")))
    assert result.stop_reason == "end_turn"
