# Going to production

What the workshop simplifies, and what replaces each simplification. Items marked TODO are not exercised by this repository and need checking against the current product docs before you rely on them.

## Identity

The workshop takes the officer from `LOAN_DESK_USER` or `--as`. Anyone with the project API key can claim any `user_id`, so in production the `user_id` has to come from a verified sign-in:

- **Through an Arcade MCP gateway**, with your IdP as its user source: the person signs in at your IdP, and Arcade calls the tools and the hooks as that person. The agent then reaches the tools through the gateway instead of the Engine with the project key. TODO(arcade): document the Strands side of this (Strands' MCP client against the gateway URL, and how the person's token reaches it).
- **On Amazon Bedrock AgentCore Runtime**, with inbound auth (a JWT authorizer on your IdP): take the verified subject from the request context and pass it as the Arcade `user_id`. Never take the user from the request body, as `agentcore_app.py` still does. TODO(agentcore): wire the verified identity through `BedrockAgentCoreApp`'s request context.

Then `LOAN_DESK_USER` and `CONNECTED_APPS_USER` collapse into one identity.

## Connected apps

Arcade's built-in Slack and Gmail apps use Arcade's own user verification, which needs each end user to be a signed-in member of your Arcade project. For your own users, register your own OAuth apps in Arcade and a custom user verifier, so your users need no Arcade account.

## The control plane

- Host `gate/` where Arcade can reach it without a tunnel, with TLS, behind its Bearer token (from a secret store, rotated), or mTLS if your extension is configured for it.
- Keep the hooks **fail closed**, and alert on `/hooks/health`.
- Arcade caches access hook results, so a role change can take a while to show in a tool list. The pre hook is checked on every call, which is why the limits are enforced there as well, not only by hiding tools. TODO(arcade): document the cache lifetime.
- Ship the audit log (`.gate/audit.jsonl`) to your log pipeline. Each refusal's `[ref …]` is the Arcade execution id.
- `neutralize_text` is a keyword heuristic to show where the control sits. Use a real classifier there.

## Neo4j

- Give the tools and the gate separate database users with only the privileges their queries need (fine-grained privileges need Neo4j Enterprise or Aura), and keep the tools' credentials only in Arcade's secrets.
- `consumed_at` is set with a conditional `SET`, so two retries racing for one approval cannot both spend it. Keep that property if you move the grant elsewhere.
- Back up the graph. Decisions and approval requests are the record of who decided what.

## The agent

- Pin `MODEL_ID` (and for Bedrock, the inference profile your region supports), so an upgrade is a deliberate change your evals gate.
- Run `uv run evals` in CI against a staging Arcade project and a staging graph.
- Export traces with `--trace otlp`, or set up `StrandsTelemetry` in your own entrypoint.
- Session state (`--session`) is a local file. In a service, use a shared session store.

## AgentCore

`agent/loan_agent/agentcore_app.py` is the same agent behind `BedrockAgentCoreApp`. TODO(agentcore): the build and deploy commands (the AgentCore starter toolkit's `agentcore configure` and `agentcore launch`) are not exercised here; follow the current AgentCore Runtime docs, and load `ARCADE_API_KEY` from Secrets Manager rather than the image.
