"""The Arcade side of the agent: schemas, the arcadepy adapter over a mocked HTTP API, identity."""

import json

import httpx
import pytest
from arcadepy import Arcade

from loan_agent.arcade_tools import ArcadeEngine, ArcadeToolbox, ArcadeToolDef, Outcome, json_schema, model_name, toolkit_of


def test_model_names_are_what_the_refusals_name():
    assert model_name("LoanDesk.RequestApproval@1.0.0") == "LoanDesk_RequestApproval"
    assert toolkit_of("LoanDesk_ApproveLoan") == "LoanDesk"
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


def definition(name="LoanDesk.SearchLoans", version="1.0.0"):
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
            items = [definition(), definition("LoanDesk.GetLoan"), definition("Slack.SendDmToUser")]
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
    tools = engine.list_toolkit("LoanDesk", "alice@bank.example")
    assert [t.qualified for t in tools] == ["LoanDesk.SearchLoans", "LoanDesk.GetLoan"]
    assert tools[0].version == "1.0.0"
    assert api.requests[0].url.params["user_id"] == "alice@bank.example"
    assert "test-key" in api.requests[0].headers["authorization"]


def test_select_sends_tool_rec_and_refreshes_from_the_catalog(engine, api):
    query_id, tools = engine.select(["DM charlie on slack"], "alice@bank.example", 5)
    assert query_id == "q-7"
    assert tools[0].qualified == "Slack.SendDmToUser" and tools[0].version == "2.1.0"
    body = json.loads(api.requests[0].content)
    assert body == {"tasks": ["DM charlie on slack"], "top_k": 10, "user_id": "alice@bank.example"}


def test_execute_passes_version_user_and_query(engine, api):
    tool = ArcadeToolDef("LoanDesk.SearchLoans", "LoanDesk", version="1.0.0")
    assert engine.execute(tool, {"status": "pending"}, "alice@bank.example", "q-1") == Outcome(value={"count": 1})
    body = json.loads(api.requests[0].content)
    assert body["tool_name"] == "LoanDesk.SearchLoans" and body["tool_version"] == "1.0.0"
    assert body["user_id"] == "alice@bank.example" and body["query_id"] == "q-1"


def test_a_refusal_comes_back_as_the_hooks_words(engine, api):
    api.execute_reply = {"success": False, "output": {"error": {"message": "DENIED: over your limit", "kind": "TOOL_RUNTIME_FATAL", "can_retry": False}}}
    outcome = engine.execute(ArcadeToolDef("LoanDesk.ApproveLoan", "LoanDesk"), {}, "alice@bank.example")
    assert outcome.error == "DENIED: over your limit"


def test_authorization_needed_returns_the_link(engine, api):
    api.execute_reply = {"success": False, "output": {"authorization": {"status": "pending", "url": "https://auth.example/slack"}}}
    outcome = engine.execute(ArcadeToolDef("Slack.SendDmToUser", "Slack"), {}, "me@example.com")
    assert outcome.auth_url == "https://auth.example/slack"


def test_an_http_error_is_an_answer_not_a_crash(api):
    client = Arcade(api_key="k", base_url="http://arcade.test", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"message": "engine down"}))))
    outcome = ArcadeEngine(client).execute(ArcadeToolDef("LoanDesk.GetLoan", "LoanDesk"), {}, "alice@bank.example")
    assert outcome.error == "engine down"


class Recorder:
    def __init__(self):
        self.calls = []

    def list_toolkit(self, toolkit, user_id):
        return [ArcadeToolDef("LoanDesk.GetLoan", "LoanDesk", "Get.", [])]

    def select(self, tasks, user_id, limit):
        return "q", []

    def execute(self, tool, inputs, user_id, query_id=""):
        self.calls.append((tool.qualified, user_id))
        return Outcome(value="ok")


def test_connected_apps_run_as_your_own_arcade_account():
    toolbox = ArcadeToolbox(Recorder(), persona="alice@bank.example", connected_apps_user="me@company.example")
    assert toolbox.identity_for(ArcadeToolDef("LoanDesk.GetLoan", "LoanDesk")) == "alice@bank.example"
    assert toolbox.identity_for(ArcadeToolDef("Slack.SendDmToUser", "Slack")) == "me@company.example"
    alone = ArcadeToolbox(Recorder(), persona="alice@bank.example")
    assert alone.identity_for(ArcadeToolDef("Slack.SendDmToUser", "Slack")) == "alice@bank.example"


def test_pinned_tools_are_strands_tools_named_for_the_model():
    recorder = Recorder()
    toolbox = ArcadeToolbox(recorder, persona="alice@bank.example")
    [tool] = toolbox.pinned()
    assert tool.tool_name == "LoanDesk_GetLoan"
    assert tool.tool_spec["inputSchema"]["json"] == {"type": "object", "properties": {}}
