# FAQ

## Why do the limits live in hooks, and not in the prompt?

A limit in a system prompt is a request the model may or may not honour, and the wording of a user's message can move it. The agent's instructions here carry no limits at all (`tests/test_agent.py` checks), and the refusal itself tells the agent what to do next. The model is free to try anything; the hooks decide.

## Why not put the limits in a Strands hook?

Strands hooks (`BeforeToolCallEvent` can cancel a tool) run inside the agent's process. They are the right place for things the agent's owner wants, such as the `--confirm` interrupt or the transcript. They are the wrong place for the bank's authority: anyone who runs a different agent, or calls Arcade directly with the project key, skips them. Arcade's hooks run on every call in the project, whichever client makes it.

## Why not Amazon Bedrock Guardrails?

Bedrock Guardrails filter content: topics, harmful text, PII patterns in what goes in and out of the model. They do not know who Alice is, what her clearance is, or that LN-2297's owner already has $47.5K approved. Use them alongside this, not instead of it.

## Why typed Arcade tools over the Neo4j MCP server?

The [README](../README.md#how-neo4j-is-wired-in-and-why-not-the-neo4j-mcp-server) has the full answer. In short, a policy has to read the amount on `ApproveLoan(loan_id, amount)`, and cannot read it reliably inside `write-cypher(query)`. With typed tools, the bank writes the business logic, not the model, and the database credentials stay in Arcade.

## Why is there an approval request at all, and not just "ask Charlie"?

The approval has to be something the control plane can check: an approved request for exactly this action, loan and amount, made by the caller, decided by someone else, used once. A message to Charlie is not that. The agent may still tell Charlie in Slack; that is information, and carries no authority.

## Can the agent approve less than the requested amount to slip under the limit?

The tools allow approving an application for less, because banks do. So the policy cannot tell a deliberate partial approval from a workaround. That is what the `amount-workaround` eval and its `escalation_discipline` check catch (module 04): evals cover what policy cannot name.

## How does this compare with the LangChain workshop?

The governance is the same: the same hooks, the same policy shape, the same cast, the same loans. The agent is a Strands `Agent` instead of a LangChain Deep Agent, the Arcade integration is a small toolbox (`agent/loan_agent/arcade_tools.py`) instead of `ArcadeMiddleware`, the system of record is a Neo4j graph instead of a REST API over SQLite, and observability is OpenTelemetry and Strands Evals instead of LangSmith. Identity is a persona rather than an Okta sign-in, to keep setup inside the workshop's time.

## Can I use another model?

Strands supports many providers. Add a branch to `make_model` in `agent/loan_agent/models.py`. Nothing about governance depends on the model: the same calls reach the same hooks.

## Why does the scripted model exist?

So the first run needs no key, and so the tests can drive every governed scenario through the real Strands loop deterministically. It implements Strands' `Model` interface and streams the same events a real model does.

## Where does Tool Recommendation fit?

The loan desk toolkit is pinned: Arcade lists it for the persona at the start of each run, after the access hook. Everything else (Slack, Gmail) is found at run time with `arcade_select_tools`, which calls Arcade's Tool Recommendation and registers what it finds on the running agent. The hooks govern every call either way.
