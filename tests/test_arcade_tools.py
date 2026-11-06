"""The Arcade side of the agent: schemas, the arcadepy adapter over a mocked HTTP API, identity."""

import json

import httpx
import pytest
from arcadepy import Arcade

from bank_agent.arcade_tools import ArcadeEngine, ArcadeToolbox, ArcadeToolDef, Outcome, json_schema, model_name, toolkit_of


def test_model_names_are_what_the_refusals_name():
    assert model_name("Bank.RequestApproval@1.0.0") == "Bank_RequestApproval"
    assert toolkit_of("Bank_ReleasePayment") == "Bank"
    assert toolkit_of("Slack.SendDmToUser@2.0.0") == "Slack"


def test_arcade_parameters_become_json_schema():
    schema = json_schema([
        {"name": "status", "required": False, "description": "  Only   these. ", "value_schema": {"val_type": "string", "enum": ["a", "b"]}},
        {"name": "amount", "required": True, "value_schema": {"val_type": "number"}},
        {"name": "ids", "required": False, "value_schema": {"val_type": "array", "inner_val_type": "integer"}},
        {"name": "extra", "value_schema": {"val_type": "json"}},
    ])
    assert schema == {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["a", "b"], "description": "Only these."},
            "amount": {"type": "number"},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "extra": {"type": "object"},
        },
        "required": ["amount"],
    }
    assert json_schema({"type": "object", "properties": {}}) == {"type": "object", "properties": {}}
    assert json_schema(None) == {"type": "object", "properties": {}}


def definition(name="Bank.ListPaymentExceptions", version="1.0.0"):
    toolkit, _, short = name.partition(".")
    return {
        "fully_qualified_name": f"{name}@{version}", "qualified_name": name, "name": short, "description": f"{short}.",
        "toolkit": {"name": toolkit, "version": version},
        "input": {"parameters": [{"name": "status", "required": False, "value_schema": {"val_type": "string"}}]},
    }


class FakeAPI:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.execute_reply = {"success": True, "output": {"value": {"count": 1}}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/v1/tools":
            items = [definition(), definition("Bank.GetPayment"), definition("Slack.SendDmToUser")]
            return httpx.Response(200, json={"items": items, "total_count": 3, "offset": 0})
        if request.method == "GET" and path.startswith("/v1/tools/"):
            return httpx.Response(200, json=definition(path.rsplit("/", 1)[-1], "2.1.0"))
        if path == "/v1/tools/select":
            return httpx.Response(200, json={"query_id": "q-7", "results": [{"suggestions": [
                {"tool_name": "Slack.SendDmToUser", "description": "DM.", "input_schema": {"type": "object"}, "version": "2.0.0"}]}]})
        if path == "/v1/tools/execute":
            return httpx.Response(200, json=self.execute_reply)
        if path == "/v1/tools/authorize":
            return httpx.Response(200, json={"status": "pending", "url": "https://auth.example/slack"})
        return httpx.Response(404, json={"message": "no route"})


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture
def engine(api):
    client = Arcade(api_key="test-key", base_url="http://arcade.test", http_client=httpx.Client(transport=httpx.MockTransport(api)))
    return ArcadeEngine(client)


def test_list_keeps_only_the_toolkit_and_asks_as_the_user(engine, api):
    tools = engine.list_toolkit("Bank", "pat@bank.example")
    assert [t.qualified for t in tools] == ["Bank.ListPaymentExceptions", "Bank.GetPayment"]
    assert tools[0].version == "1.0.0"
    assert api.requests[0].url.params["user_id"] == "pat@bank.example"
    assert "test-key" in api.requests[0].headers["authorization"]


def test_select_sends_tool_rec_and_refreshes_from_the_catalog(engine, api):
    query_id, tools = engine.select(["DM sana on slack"], "pat@bank.example", 5)
    assert query_id == "q-7"
    assert tools[0].qualified == "Slack.SendDmToUser" and tools[0].version == "2.1.0"
    body = json.loads(api.requests[0].content)
    assert body == {"tasks": ["DM sana on slack"], "top_k": 10, "user_id": "pat@bank.example"}


def test_execute_passes_version_user_and_query(engine, api):
    tool = ArcadeToolDef("Bank.ListPaymentExceptions", "Bank", version="1.0.0")
    assert engine.execute(tool, {"status": "pending"}, "pat@bank.example", "q-1") == Outcome(value={"count": 1})
    body = json.loads(api.requests[0].content)
    assert body["tool_name"] == "Bank.ListPaymentExceptions" and body["tool_version"] == "1.0.0"
    assert body["user_id"] == "pat@bank.example" and body["query_id"] == "q-1"


def test_a_refusal_comes_back_as_the_hooks_words(engine, api):
    api.execute_reply = {"success": False, "output": {"error": {"message": "HELD: near a listed entity", "kind": "TOOL_RUNTIME_FATAL", "can_retry": False}}}
    outcome = engine.execute(ArcadeToolDef("Bank.ReleasePayment", "Bank"), {}, "pat@bank.example")
    assert outcome.error == "HELD: near a listed entity"


def test_authorization_needed_returns_the_link(engine, api):
    api.execute_reply = {"success": False, "output": {"authorization": {"status": "pending", "url": "https://auth.example/slack"}}}
    outcome = engine.execute(ArcadeToolDef("Slack.SendDmToUser", "Slack"), {}, "me@example.com")
    assert outcome.auth_url == "https://auth.example/slack"


def test_an_http_error_is_an_answer_not_a_crash(api):
    client = Arcade(api_key="k", base_url="http://arcade.test", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"message": "engine down"}))))
    outcome = ArcadeEngine(client).execute(ArcadeToolDef("Bank.GetPayment", "Bank"), {}, "pat@bank.example")
    assert outcome.error == "engine down"


class Recorder:
    def __init__(self):
        self.calls = []

    def list_toolkit(self, toolkit, user_id):
        return [ArcadeToolDef("Bank.GetPayment", "Bank", "Get.", [])]

    def select(self, tasks, user_id, limit):
        return "q", []

    def execute(self, tool, inputs, user_id, query_id=""):
        self.calls.append((tool.qualified, user_id))
        return Outcome(value="ok")


def test_connected_apps_run_as_your_own_arcade_account():
    toolbox = ArcadeToolbox(Recorder(), persona="pat@bank.example", connected_apps_user="me@company.example")
    assert toolbox.identity_for(ArcadeToolDef("Bank.GetPayment", "Bank")) == "pat@bank.example"
    assert toolbox.identity_for(ArcadeToolDef("Slack.SendDmToUser", "Slack")) == "me@company.example"
    alone = ArcadeToolbox(Recorder(), persona="pat@bank.example")
    assert alone.identity_for(ArcadeToolDef("Slack.SendDmToUser", "Slack")) == "pat@bank.example"


def test_pinned_tools_are_strands_tools_named_for_the_model():
    recorder = Recorder()
    toolbox = ArcadeToolbox(recorder, persona="pat@bank.example")
    [tool] = toolbox.pinned()
    assert tool.tool_name == "Bank_GetPayment"
    assert tool.tool_spec["inputSchema"]["json"] == {"type": "object", "properties": {}}
