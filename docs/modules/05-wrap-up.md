# Production and wrap-up

**12:30 to 1:00.** The whole bank once more, end to end, what changes on the way to production, how this compares with AgentCore Policy, and questions.

## The whole bank in one run (about 10 minutes)

Reset the graph (`uv run seed --reset`), keep the gate's terminal in view, and run the three desks back to back:

    uv run ask --desk payments "Work PMT-5001"
    uv run ask --desk aml "Investigate CASE-7001, then email rita@bank.example to ask about Victor Hale's companies."
    uv run ask --desk banker "Brief me on Lakeside Bakehouse before my call."

Watch the audit log: one graph, one control plane, three different multi-agent shapes, and the same three hooks deciding every call. Then change one thing on stage, in the graph rather than the code. For example, end Daniel Voss's board seat at Orlov Maritime:

    MATCH (:Person {name: 'Daniel Voss'})-[d:DIRECTOR_OF]->(:Company {name: 'Orlov Maritime Ltd'}) DELETE d

and PMT-5001 releases on the next run. `uv run seed --reset` puts it back.

## Going to production (about 10 minutes)

[`docs/production.md`](../production.md) is the checklist. The four things that change:

- **Identity.** `--as` is a workshop convenience. In production the `user_id` comes from a verified token: your IdP behind an Arcade MCP gateway, or AgentCore Runtime's inbound auth mapped to the Arcade user.
- **The gate** runs where Arcade can reach it without a tunnel, with its token in a secret store, health-checked, and fail closed.
- **Neo4j**: separate database users for the tools and the gate, each with only the privileges its queries need, and the tools' credentials only in Arcade's secrets.
- **Connected apps**: your own OAuth apps for Gmail and Slack, with a custom user verifier, so your employees need no Arcade account.

The same agents run on Amazon Bedrock AgentCore Runtime (`agent/bank_agent/agentcore_app.py`, `uv sync --extra prod`). The hooks run in Arcade, so a deployed desk is held to exactly what the laptop one was.

## How this compares with AgentCore Policy (about 5 minutes)

[`docs/production.md`](../production.md#how-this-compares-with-agentcore-policy) has the comparison. In one line: Cedar is the right home for static rules ("only payments operations may call ReleasePayment"), and a graph-aware hook is the right home for rules whose answer depends on relationships that change every day ("no release to anyone three hops from a listed entity"). The two can run together.

## What you take home

- **The desks**: three Strands multi-agent patterns (a Graph with conditional edges, a Swarm inside a Graph with an interrupt, agents as tools), none of whose instructions state a rule.
- **The Arcade toolbox**: `agent/bank_agent/arcade_tools.py`, drop-in for any Strands agent: a pinned toolkit, Tool Recommendation at run time, and every call through Arcade as one employee.
- **The tools**: `mcp/bank_tools/`, typed tools over a Neo4j graph, deployed to your Arcade project with the credentials in Arcade.
- **The control plane**: `gate/`, policy files and three hooks with a closed vocabulary of graph questions, which govern every call in your Arcade project whichever agent or client makes it.
- **The evals**: a dataset and checks for what policy cannot name.

## Make it yours

Replace Larkspur Bank with your own system of record: swap `neo4j/bank_graph/seed.json` and the queries in `mcp/bank_tools/graph.py`, keep the tool signatures typed so a policy can read them, and add graph questions to `gate/bank_gate/directory.py` (with the same answer in `tests/support/memory_graph.py`, which `tests/test_neo4j_live.py` holds to the real Cypher).

For a finale or a stretch module, see [`docs/bold-bets.md`](../bold-bets.md).

## Further reading

- [`docs/architecture.md`](../architecture.md), [`docs/production.md`](../production.md), [`docs/faq.md`](../faq.md).
- [Strands Agents](https://strandsagents.com), [Arcade docs](https://docs.arcade.dev), [Neo4j Cypher manual](https://neo4j.com/docs/cypher-manual/current/).
