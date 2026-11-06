"""The same agent behind an Amazon Bedrock AgentCore Runtime entrypoint (module 04, optional).

    uv sync --extra prod
    uv run python -m loan_agent.agentcore_app          # serves POST /invocations on :8080 locally
    curl -s localhost:8080/invocations -H 'content-type: application/json' \
         -d '{"prompt": "Which loans are pending?"}'

Nothing about governance moves when the agent does: the hooks run in Arcade's control plane,
so the deployed agent is held to exactly what the laptop one was.

TODO(agentcore): the deploy step (`agentcore configure` / `agentcore launch` from the
bedrock-agentcore-starter-toolkit) is not exercised by this repo; follow the AgentCore Runtime
docs for the current commands, and pass ARCADE_API_KEY from Secrets Manager, not the image.

TODO(identity): here the officer comes from LOAN_DESK_USER, the same as on the laptop. In
production it must come from a verified token: configure AgentCore inbound auth (a JWT
authorizer on your IdP) and map the token's subject to the Arcade user_id, and never take the
user from the request body.
"""

from __future__ import annotations

from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from loan_agent.agent import build_agent
from loan_agent.config import Settings, load_env

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    load_env()
    settings = Settings.from_env()
    desk = build_agent(settings)
    result = desk(str(payload.get("prompt") or ""))
    return {"result": str(result).strip(), "tools": desk.transcript.names(), "links": desk.links}


if __name__ == "__main__":
    app.run()
