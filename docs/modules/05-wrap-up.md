# Q&A and wrap-up

**12:30 to 1:00.** The whole story once more, end to end, and what you take home.

Reset the book (`uv run seed --reset`), keep the gate's terminal in view, and run it as Alice:

> Approve the Northwind loan for the full $95K and double-check your work.

Watch the gate. Access hid the decision tools from Bob earlier; pre refuses Alice and the refusal routes her to Charlie; Charlie decides from `uv run approve` and her retry passes once; post masks the identifiers and strips the pasted note. Then change one thing on stage, either a rule in `gate/policy.json` (restart the gate) or a clearance with `uv run officers set-clearance`, and run the prompt again.

## What you take home

- **The agent**: a Strands agent whose instructions carry no limits, with an Arcade toolbox you can drop into any Strands agent (`agent/loan_agent/arcade_tools.py`).
- **The tools**: `mcp/loan_desk/`, deployed to your Arcade project, typed tools over a Neo4j graph, with the credentials in Arcade.
- **The control plane**: `gate/`, a policy file and three hooks, which govern every call in your Arcade project whichever agent or client makes it.
- **The evals**: a dataset and checks for what policy cannot catch.

## Make it yours

Replace the loan book with your own system of record: swap `neo4j/loan_graph/seed.json` and the queries in `mcp/loan_desk/graph.py`, keep the tool signatures typed so the policy can read them, and keep `gate/` as it is. The tests in `tests/test_governed_loop.py` are the contract to keep green.

## Further reading

- [`docs/architecture.md`](../architecture.md), [`docs/production.md`](../production.md), [`docs/faq.md`](../faq.md).
- [Strands Agents](https://strandsagents.com), [Arcade docs](https://docs.arcade.dev), [Neo4j Cypher manual](https://neo4j.com/docs/cypher-manual/current/).
