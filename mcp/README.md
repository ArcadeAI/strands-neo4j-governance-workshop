# The Bank MCP server

One MCP server, one toolkit (`Bank`), seventeen typed tools over Bowser Capital's Neo4j graph, built with [`arcade-mcp-server`](https://docs.arcade.dev) and deployed to your Arcade project:

```
cd mcp
cp .env.example .env          # NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
arcade deploy -e server.py
```

`arcade deploy` uploads the secrets the tools declare. Each call reads them from its context, so no agent ever holds a database password. The deployed server runs in Arcade's cloud: the database must be reachable from the internet (Aura, or a tunnel to a local one).

| Tool (as the model sees it) | Desk | Does |
|---|---|---|
| `Bank_ListPaymentExceptions` | payments | the payments monitoring stopped for review |
| `Bank_GetPayment` | payments | one payment: amount, alert, reference, originator and beneficiary |
| `Bank_ScreenParty` | payments, AML | one name against the sanctions list and the PEP register (a name screen, nothing more) |
| `Bank_ReleasePayment` | payments | send a payment that is waiting for review |
| `Bank_HoldPayment` | payments | hold it, with a reason |
| `Bank_GetCase` | AML | one case: alert, owner, subject, accounts |
| `Bank_TraceFunds` | AML | follow `PAID` edges out of an account, up to a number of hops, with any cycles back |
| `Bank_TraceOwnership` | AML | owners and holdings up to four levels each way, with effective percentages and board seats |
| `Bank_FreezeAccount` | AML | freeze an account under an open case |
| `Bank_FileSar` | AML | file a SAR for an open case |
| `Bank_SearchCompanies` | banker | find companies by name or industry |
| `Bank_GetCompanyProfile` | banker | a company's profile for a meeting, including the deals it is part of |
| `Bank_ListDeals` | banker | the advisory deals in progress |
| `Bank_GetDeal` | banker | one deal, with its insiders |
| `Bank_RequestApproval` | all | ask for an approval, routed to the first person on the rota with the role the action needs, never the requester and never anyone linked to a case's subject |
| `Bank_ListApprovals` | all | the requests you made or were routed |
| `Bank_Decide` | approvers | approve or deny a request routed to you; an approved wall-crossing becomes a `WALL_CROSSED` edge with an expiry |

The tools know nothing about policy. Who the call is for is Arcade's `user_id`, recorded as the actor; whether that person may make it is decided before the tool runs, in [`gate/`](../gate/README.md). Every query is fixed and parameterized (`bank_tools/graph.py`). `tests/test_neo4j_live.py` holds every query to the in-memory graph's answers.

Running locally for a look: `uv run --project .. python server.py http` serves it on `http://127.0.0.1:8000` with the secrets from the environment. This is a separate project from the repository root so that `arcade deploy` packages only what the server needs.

Keep `from __future__ import annotations` out of the tool modules: `arcade-core` reads each parameter's annotation as a live type to find the context argument and build the schema.
