# FAQ

## Why do the controls live in hooks, and not in the prompt?

A rule in a system prompt is a request the model may or may not honour, and the wording of a user's message can move it ("compliance pre-cleared this by phone"). No desk's instructions here state a rule, a threshold or a person (`tests/test_agent.py` checks every prompt), and each refusal tells the agent what to do next. The models are free to try anything; the hooks decide.

## Why not put the controls in a Strands hook?

Strands hooks (`BeforeToolCallEvent` can cancel a tool or raise an interrupt) run inside the agent's process. They are the right place for what the agent's owner wants, such as the AML lead's consent interrupt or the transcript. They are the wrong place for the bank's authority: anyone who runs a different agent, or calls Arcade directly with the project key, skips them. Arcade's hooks run on every call in the project, whichever client makes it, and across every agent in a Graph or Swarm.

## Why not Amazon Bedrock Guardrails?

Bedrock Guardrails filter content: topics, harmful text, PII patterns in what goes in and out of the model. They do not know that Brightwater's owner sits on Orlov Maritime's board, that Rita manages Hale's holding company, or that Ian crossed the wall two hours ago. Use them alongside this, not instead of it.

## Why not AgentCore Policy?

Use it for the static rules, and keep the graph-aware ones here. [`production.md`](./production.md#how-this-compares-with-agentcore-policy) has the comparison.

## Why typed Arcade tools over the Neo4j MCP server?

The [README](../README.md#how-neo4j-is-wired-in-and-why-not-the-neo4j-mcp-server) has the full answer. In short, a policy has to read `payment_id` on `ReleasePayment(payment_id)`, and cannot read it reliably inside `write-cypher(query)`. With typed tools, the bank writes the business logic, not the model, and the database credentials stay in Arcade.

## Why a graph, and not a relational database?

Every control in this workshop is a question about paths: how many ownership or board hops separate a beneficiary from a listed entity, whether a recipient is linked to a case's subject, whether an approver is. In Cypher each is one bounded `shortestPath`; the hop limit is a number in the policy file. The same questions over join tables are recursive queries whose depth is fixed in SQL, and they get rewritten every time someone adds a kind of relationship.

## Why is there an approval request at all, and not just "ask Sana"?

The approval has to be something the control plane can check: an approved request for exactly this action and resource, made by the caller, decided by someone else with the right role and no conflict, used once. A message to Sana is not that. In the AML desk it would also be the kind of message the tipping-off rule exists for.

## Is the sanctions list real?

No. `SYN-SDN` is invented and shaped like a list; every name, account, SSN (900- area numbers, never issued) and address is synthetic. The three-hop hold is a risk-based review rule, stricter than the OFAC 50 Percent Rule on purpose, to show a control a name screen cannot make.

## Why US terminology?

SAR, BSA officer and FinCEN are what most attendees will know, and 31 U.S.C. 5318(g)(2) is the clearest statement of why tipping off matters. The controls do not depend on the jurisdiction: in the UK the same desk would file a SAR with the NCA under a MLRO, and the tipping-off offence is in POCA section 333A.

## How does this compare with the LangChain workshop?

Arcade's LangChain workshop governs one Deep Agent on one loan desk, and its policy checks amounts against a clearance. This one keeps the skeleton (timed modules, Arcade's hooks, a human in the loop, evals, credential-free tests) and changes what is governed: three Strands multi-agent desks at one bank, whose controls are questions about paths in a Neo4j graph. Observability is OpenTelemetry and Strands Evals instead of LangSmith, and identity is a persona rather than an Okta sign-in, to keep setup inside the workshop's time.

## Can I use another model?

Strands supports many providers. Add a branch to `make_model` in `agent/bank_agent/models.py`, or pass a model per agent (`models={"lead": …}`) to any desk. Nothing about governance depends on the model: the same calls reach the same hooks.

## Why does the scripted model exist?

So the first run needs no key, and so the tests can drive every governed scenario through the real Strands Graph, Swarm and agents-as-tools loops deterministically. It implements Strands' `Model` interface and streams the same events a real model does. Each desk's default scripts are deliberately naive (the screener only screens names), which is what makes the controls visible.

## Where does Tool Recommendation fit?

The Bank toolkit is pinned: Arcade lists it for the employee at the start of each run, after the access hook. Gmail and Slack are found at run time by the AML lead with `arcade_select_tools`, which calls Arcade's Tool Recommendation and registers what it finds on the running agent. The hooks govern every call either way.
