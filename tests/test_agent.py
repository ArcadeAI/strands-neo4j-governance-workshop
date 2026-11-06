"""The Strands agent itself: model choice, the scripted model, local tools, and what it is offered."""

import pytest

from loan_agent.agent import build_agent
from loan_agent.config import Settings
from loan_agent.local_tools import loan_payment
from loan_agent.models import make_model, provider_of
from loan_agent.scripted import Call, Say, ScriptedModel, steps


def test_settings_read_the_environment():
    settings = Settings.from_env({"LOAN_DESK_USER": "Bob@Bank.Example", "ARCADE_TOOLS_PER_TASK": "3", "MODEL_PROVIDER": "Anthropic"})
    assert settings.user == "bob@bank.example" and settings.tools_per_task == 3 and settings.model_provider == "anthropic"
    assert Settings.from_env({}, user="charlie@bank.example").user == "charlie@bank.example"


@pytest.mark.parametrize(
    ("env", "provider"),
    [({}, "scripted"), ({"ANTHROPIC_API_KEY": "placeholder"}, "anthropic"), ({"MODEL_PROVIDER": "bedrock"}, "bedrock"),
     ({"MODEL_PROVIDER": "scripted", "ANTHROPIC_API_KEY": "placeholder"}, "scripted")],
)
def test_provider_choice(env, provider):
    assert provider_of(Settings.from_env(env)) == provider


def test_unknown_provider_is_an_error():
    with pytest.raises(ValueError, match="MODEL_PROVIDER"):
        provider_of(Settings.from_env({"MODEL_PROVIDER": "openai"}))


def test_anthropic_needs_its_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        make_model(Settings.from_env({"MODEL_PROVIDER": "anthropic"}))


def test_models_build_without_calling_anyone():
    from strands.models.anthropic import AnthropicModel
    from strands.models.bedrock import BedrockModel

    anthropic = make_model(Settings.from_env({"ANTHROPIC_API_KEY": "placeholder", "MODEL_ID": "some-model"}))
    assert isinstance(anthropic, AnthropicModel) and anthropic.get_config()["model_id"] == "some-model"
    bedrock = make_model(Settings.from_env({"MODEL_PROVIDER": "bedrock", "AWS_REGION": "us-west-2"}))
    assert isinstance(bedrock, BedrockModel) and bedrock.get_config()["model_id"]
    assert isinstance(make_model(Settings.from_env({})), ScriptedModel)


def test_loan_payment():
    result = loan_payment._tool_func(principal=100000, annual_rate_pct=6, years=10)
    assert result["monthly_payment"] == pytest.approx(1110.21, abs=0.01)
    assert loan_payment._tool_func(principal=1200, annual_rate_pct=0, years=1)["monthly_payment"] == 100


def test_without_arcade_the_agent_has_only_local_tools_and_says_so():
    desk = build_agent(Settings.from_env({}))
    assert desk.agent.tool_names == ["loan_payment"]
    assert "not connected" in desk.agent.system_prompt
    assert "scripted model" in str(desk("Which loans are pending?"))


def test_the_scripted_model_calls_a_local_tool():
    model = ScriptedModel(steps(Call("loan_payment", {"principal": 12000, "annual_rate_pct": 0, "years": 1})))
    desk = build_agent(Settings.from_env({}), model=model)
    result = desk("What would 12k over a year at 0% cost per month?")
    assert desk.transcript.names() == ["loan_payment"]
    assert '"monthly_payment": 1000.0' in str(result)


def test_the_default_script_lists_pending_loans(arcade):
    desk = build_agent(Settings.from_env({}), model=ScriptedModel(), engine=arcade)
    result = desk("anything")
    assert desk.transcript.names() == ["LoanDesk_SearchLoans"]
    assert "LN-2299" in str(result)


def test_the_instructions_say_nothing_about_limits():
    from loan_agent.agent import INSTRUCTIONS

    for figure in ("50,000", "50000", "250,000", "250000", "clearance"):
        assert figure not in INSTRUCTIONS


def test_say_ends_the_turn():
    desk = build_agent(Settings.from_env({}), model=ScriptedModel(steps(Say("done"))))
    assert str(desk("hi")).strip() == "done"
