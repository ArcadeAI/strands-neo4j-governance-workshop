# Connecting the agent to a graph with Arcade and just-in-time authorization

**9:45 to 10:30.** Who the agent is when it calls a tool, where the data lives, and how it gets permission at the moment it needs it.

You leave with the loan book seeded in Neo4j, the Loan Desk MCP server deployed to your Arcade project, the agent calling it as Alice through Arcade's Engine, and Slack authorized as yourself the first time the agent needed it.

## What you build

1. **Seed the graph.** In `.env`, set `NEO4J_URI`, `NEO4J_USERNAME` and `NEO4J_PASSWORD` (Aura: `neo4j+s://<id>.databases.neo4j.io`; Docker: `bolt://localhost:7687` after `make neo4j-up`). Then:

       uv run seed
       uv run officers list

   Or paste [`neo4j/seed.cypher`](../../neo4j/seed.cypher) into Neo4j Browser or the Aura query editor.
2. **See the graph.** Open Neo4j Browser (Aura's "Query" tab, or http://localhost:7474) and run:

       MATCH (c:Company)-[:APPLIED_FOR]->(l:Loan {id: 'LN-2297'})
       MATCH (c)<-[:OWNS]-(p:Person)-[:OWNS]->(other:Company)-[:APPLIED_FOR]->(ol:Loan)
       RETURN c, p, other, ol

   Lakeside Bakehouse's $32K looks small. Its owner, Elena Brandt, also owns Northwind Bakery and Two Rivers Brewing. Keep that picture for module 03.
3. **Deploy the tools.** The Loan Desk MCP server holds the only Neo4j credentials anywhere near the agent:

       cd mcp
       cp .env.example .env     # the same three NEO4J_ values
       arcade deploy -e server.py
       cd ..

   `arcade deploy` uploads the secrets the tools declare (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`) to your project. The server runs in Arcade's cloud, so the database has to be reachable from the internet. With Docker, that means a TCP tunnel to port 7687 (for example `ngrok tcp 7687`, then `NEO4J_URI=bolt://<host>:<port>` in `mcp/.env` only). TODO(thierry): confirm ngrok TCP endpoints on the free plan for the room, or standardize on Aura.
4. **Connect the agent.** Set `ARCADE_API_KEY` in the root `.env`, then:

       uv run tools
       uv run ask "Which loans are pending?"

   `uv run tools` is what Arcade lists for Alice: eight `LoanDesk_*` tools. The ask runs `LoanDesk_SearchLoans` through the Engine as `alice@bank.example`, and the tool reads Neo4j with the secrets Arcade holds.
5. **The exercise** (`make start M=02`, in `agent/loan_agent/arcade_tools.py`):
   - `identity_for`: the loan desk runs as the persona; every other toolkit runs as `CONNECTED_APPS_USER`.
   - `strands_tool`'s `run`: call `engine.execute`, keep any authorization link, and hand the model the result.

   `make check M=02` tests both against a fake Engine.
6. **Authorize at first use.** Set `CONNECTED_APPS_USER` to the email you sign in to Arcade with, and ask:

       uv run ask "Find LN-2292 and DM me a one-line summary on Slack."

   The agent calls `arcade_select_tools`, Tool Recommendation finds Slack's tools, and they become callable on the agent's next step. The first Slack call comes back with a link instead of a result. Open it, allow it as yourself, and ask again. Nothing in the code names a token.
7. **Try another persona.** `uv run ask --as bob@bank.example "Which loans are pending?"` works, because Bob reads. Module 03 is what stops him writing.

## What to look at

- `agent/loan_agent/arcade_tools.py`: the pinned toolkit (`GET /v1/tools?toolkit=LoanDesk` as the persona), `arcade_select_tools` registering what Tool Rec finds on the running agent, and every call going through `tools.execute` with a `user_id`. Strands re-reads its tool registry on every loop, which is what makes mid-run registration work.
- `mcp/loan_desk/graph.py`: every query is fixed and parameterized. The model supplies values, never Cypher.
- `mcp/loan_desk/loans.py`: `actor_of(context)` is who the decision is recorded as, taken from Arcade's `user_id`, never from a tool argument.
- Why two identities: Arcade's built-in Slack and Gmail OAuth apps bind a grant to the Arcade account that authorized it, so they run as you. The loan desk runs as the persona the hooks govern. In production both are one signed-in person ([`docs/production.md`](../production.md)).

## Checkpoint

`uv run tools` lists the eight loan desk tools, `uv run ask` answers from Neo4j through Arcade, and you have authorized Slack as yourself once.

## If you are behind

`make solve M=02`. If the deploy is the blocker, the tests (`make check M=02`) still exercise the same code against the fake Engine. Arcade authorizations survive restarts.
