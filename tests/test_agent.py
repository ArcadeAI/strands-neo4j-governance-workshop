"""The Strands agent itself: model choice, the scripted model, local tools, and what it is offered."""

import pytest

from bank_agent.agent import build_agent
from bank_agent.config import Settings
from bank_agent.local_tools import fx_convert
from bank_agent.models import make_model, provider_of
from bank_agent.scripted import Call, Say, ScriptedModel, steps


def test_settings_read_the_environment():
    settings = Settings.from_env({"BANK_USER": "Ava@Bank.Example", "ARCADE_TOOLS_PER_TASK": "3", "MODEL_PROVIDER": "Anthropic"})
    assert settings.user == "ava@bank.example" and settings.tools_per_task == 3 and settings.model_provider == "anthropic"
    assert Settings.from_env({}, user="sana@bank.example").user == "sana@bank.example"


def test_each_desk_has_its_usual_employee():
    assert [Settings.from_env({}, desk=d).user for d in ("assistant", "payments", "aml", "banker")] == [
        "pat@bank.example", "pat@bank.example", "ava@bank.example", "ian@bank.example"]
    with pytest.raises(ValueError, match="desk"):
        Settings.from_env({}, desk="loans")


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


def test_fx_convert():
    assert fx_convert._tool_func(amount=2500, from_currency="eur")["converted"] == 2700.0
    assert fx_convert._tool_func(amount=100, from_currency="USD", to_currency="GBP")["converted"] == pytest.approx(78.74, abs=0.01)
    with pytest.raises(ValueError, match="No reference rate"):
        fx_convert._tool_func(amount=1, from_currency="XYZ")


def test_without_arcade_the_agent_has_only_local_tools_and_says_so():
    desk = build_agent(Settings.from_env({}))
    assert desk.agent.tool_names == ["fx_convert"]
    assert "not connected" in desk.agent.system_prompt
    assert "scripted model" in str(desk("Which payments are waiting?"))


def test_the_scripted_model_calls_a_local_tool():
    model = ScriptedModel(steps(Call("fx_convert", {"amount": 1000, "from_currency": "EUR"})))
    desk = build_agent(Settings.from_env({}), model=model)
    result = desk("What is 1,000 EUR in dollars?")
    assert desk.transcript.names() == ["fx_convert"]
    assert '"converted": 1080.0' in str(result)


def test_the_default_script_lists_payment_exceptions(arcade):
    desk = build_agent(Settings.from_env({}), model=ScriptedModel(), engine=arcade)
    result = desk("anything")
    assert desk.transcript.names() == ["Bank_ListPaymentExceptions"]
    assert "PMT-5002" in str(result)


def test_with_arcade_the_agent_sees_what_arcade_lists_for_its_employee(arcade):
    pat = build_agent(Settings(user="pat@bank.example"), model=ScriptedModel(), engine=arcade).agent.tool_names
    ian = build_agent(Settings(user="ian@bank.example"), model=ScriptedModel(), engine=arcade).agent.tool_names
    assert "Bank_ReleasePayment" in pat and "Bank_ReleasePayment" not in ian
    assert "Bank_GetDeal" not in pat and "Bank_GetDeal" not in ian
    assert "Bank_FreezeAccount" not in pat and "arcade_select_tools" in pat


def test_no_prompt_states_a_rule_the_control_plane_enforces():
    from bank_agent.agent import INSTRUCTIONS

    from bank_agent.desks import aml, banker, common, payments

    prompts = [INSTRUCTIONS, common.GOVERNED, payments.SCREEN_PROMPT, payments.RELEASE_PROMPT, payments.HOLD_PROMPT,
               aml.FUNDS_PROMPT, aml.OWNERSHIP_PROMPT, aml.SCREENER_PROMPT, aml.LEAD_PROMPT,
               banker.RESEARCH_PROMPT, banker.DEAL_PROMPT, banker.COORDINATOR_PROMPT]
    for prompt in prompts:
        for figure in ("10,000", "10000", "hops", "three hops", "two hops", "SYN-SDN", "Orlov", "Rita", "Falcon"):
            assert figure not in prompt


def test_say_ends_the_turn():
    desk = build_agent(Settings.from_env({}), model=ScriptedModel(steps(Say("done"))))
    assert str(desk("hi")).strip() == "done"
