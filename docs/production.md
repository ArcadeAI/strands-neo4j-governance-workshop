# Going to production

What the workshop simplifies, and what replaces each simplification. Items marked TODO are not exercised by this repository and need checking against the current product docs before you rely on them.

## Identity

The workshop takes the employee from `BANK_USER` or `--as`. Anyone with the project API key can claim any `user_id`, so in production the `user_id` has to come from a verified sign-in:

- **Through an Arcade MCP gateway**, with your IdP as its user source: the employee signs in at your IdP, and Arcade calls the tools and the hooks as that person. The agents then reach the tools through the gateway instead of the Engine with the project key. TODO(arcade): document the Strands side of this (Strands' MCP client against the gateway URL, and how the employee's token reaches it).
- **On Amazon Bedrock AgentCore Runtime**, with inbound auth (a JWT authorizer on your IdP): take the verified subject from the request context and pass it as the Arcade `user_id`. Never take the employee from the request body. TODO(agentcore): wire the verified identity through `BedrockAgentCoreApp`'s request context in `agentcore_app.py`.

Then `BANK_USER` and `CONNECTED_APPS_USER` collapse into one identity, and the tipping-off rule's recipient check and the sender's identity are both real.

## Connected apps

Arcade's built-in Gmail and Slack apps use Arcade's own user verification, which needs each end user to be a signed-in member of your Arcade project. For your own employees, register your own OAuth apps in Arcade and a custom user verifier, so they need no Arcade account. TODO(arcade): confirm that a project's pre hook is called for Arcade-hosted toolkits and with which input names; the tipping-off rule depends on it, and `tests/support/fake_arcade.py` assumes it.

## The control plane

- Host `gate/` where Arcade can reach it without a tunnel, with TLS, behind its Bearer token (from a secret store, rotated), or mTLS if your extension is configured for it.
- Keep the hooks **fail closed**, and alert on `/hooks/health`.
- Arcade caches access hook results, so a role change can take a while to show in a tool list. Every control that matters is also a pre rule, checked on every call, which is why the deal tools are both hidden and refused. TODO(arcade): document the cache lifetime.
- Ship the audit log (`.gate/audit.jsonl`) to your log pipeline. Each refusal's `[ref …]` is the Arcade execution id.
- `neutralize_text` is a keyword heuristic to show where the control sits. Use a real classifier there.
- The graph questions are bounded (`MAX_HOPS` in `directory.py`) and use `shortestPath`, so a hook answers in milliseconds on this graph. On a production graph, index the lookup properties, keep hop bounds small, and load-test the pre hook: it is on the path of every governed call.

## Neo4j

- Give the tools and the gate separate database users with only the privileges their queries need (fine-grained privileges need Neo4j Enterprise or Aura), and keep the tools' credentials only in Arcade's secrets.
- The gate writes exactly one property: `consumed_at`, with a conditional `SET`, so two retries racing for one approval cannot both spend it. Keep that property if you move the grant elsewhere.
- The sanctions list, the PEP register, ownership and board seats are loaded from synthetic data here. In production they come from your screening vendor and your KYC records, refreshed on their own schedule; the policy reads whatever is in the graph at the moment of the call.
- Back up the graph. Decisions, approval requests, freezes, SARs and wall-crossings are the record of who decided what.

## The agents

- Pin `MODEL_ID` (and for Bedrock, the inference profile your region supports), so an upgrade is a deliberate change your evals gate.
- Run `uv run evals` for every experiment in CI against a staging Arcade project and a staging graph.
- Export traces with `--trace otlp`, or set up `StrandsTelemetry` in your own entrypoint.
- Session state (`--session`) is a local file. In a service, use a shared session store.
- The investigator's consent interrupt is the agent owner's control. Keep it, and keep in mind that the bank's controls do not depend on it.

## AgentCore Runtime

`agent/bank_agent/agentcore_app.py` serves any desk behind `BedrockAgentCoreApp`. TODO(agentcore): the build and deploy commands (the AgentCore starter toolkit's `agentcore configure` and `agentcore launch`) are not exercised here; follow the current AgentCore Runtime docs, and load `ARCADE_API_KEY` from Secrets Manager rather than the image.

## How this compares with AgentCore Policy

Amazon Bedrock AgentCore Policy evaluates tool calls that pass through an AgentCore Gateway against policies written in [Cedar](https://www.cedarpolicy.com), AWS's open-source authorization language. TODO(agentcore): confirm the current feature set (it was in preview when this was written), in particular what context a policy can see and whether any external attribute source can feed it.

Cedar is built for rules whose answer is in the request and a known set of entities: a principal, an action, a resource, their attributes and their hierarchy, all supplied with the request. That makes it a good home for the static rules in this workshop:

| Rule here | In Cedar |
|---|---|
| Only payments operations may call `ReleasePayment` | `permit` on the action for principals in the role |
| Only a BSA officer decides a freeze or a SAR | `permit` with a condition on the request's action and the principal's role |
| A freeze always needs a second person | `forbid` unless the context carries an approval |

It is a poor home for the rules this workshop is about, because their answer is a walk over relationships that change daily, and Cedar does not query a database while it evaluates:

| Rule here | Why it needs the graph at call time |
|---|---|
| Hold a release within 3 hops of a listed entity | the path runs through ownership and board seats that were not in the request |
| Hold the sixth payment just under $10,000 in 14 days | the count is over transfers that are not in the request |
| No message to anyone within 2 hops of an open case's subject | the recipient's links to the subject are in the graph, and the case may have opened an hour ago |
| No approver with a path to the subject | the conflict-of-interest register is the graph itself |
| Deal details masked unless over the wall, until the crossing expires | the crossing is an edge with an expiry, read on every call |

You could precompute those answers and hand them to Cedar as attributes, but then the precomputation is the policy, and it is stale the moment the graph changes. Arcade's hooks ask the graph at the moment of the call, and the post hook can also change what a tool returns (masking PII and deal records), which an allow or deny decision cannot.

The two compose. Static rules can sit in Cedar at an AgentCore Gateway and graph-aware rules in Arcade's hooks, both fail closed; a call has to pass both. Keep one owner for each rule, so a rule is never half in one place and half in the other.
