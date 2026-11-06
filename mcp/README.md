# The Loan Desk MCP server

One MCP server, one toolkit (`LoanDesk`), eight typed tools over the Neo4j loan graph, built with [`arcade-mcp-server`](https://docs.arcade.dev) and deployed to your Arcade project:

```
cd mcp
cp .env.example .env          # NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD
arcade deploy -e server.py
```

`arcade deploy` uploads the three secrets the tools declare. Each call reads them from its context, so the agent never holds a database password. The deployed server runs in Arcade's cloud: the database must be reachable from the internet (Aura, or a tunnel to a local one).

| Tool (as the model sees it) | Does |
|---|---|
| `LoanDesk_SearchLoans` | list applications by status and amount range |
| `LoanDesk_GetLoan` | one application's full file |
| `LoanDesk_GetBorrowerNetwork` | the borrower's owners, their other companies and loans, and the group's exposure |
| `LoanDesk_ApproveLoan` | approve an application for an amount |
| `LoanDesk_DenyLoan` | decline an application with a reason |
| `LoanDesk_RequestApproval` | ask the lowest-clearance officer who can cover the amount (never the requester) to approve an action |
| `LoanDesk_ListApprovals` | the requests you made or were routed |
| `LoanDesk_Decide` | approve or deny a request routed to you |

The tools know nothing about policy. Who the call is for is Arcade's `user_id`, recorded as the actor; whether that person may make it is decided before the tool runs, in [`gate/`](../gate/README.md). Every query is fixed and parameterized (`loan_desk/graph.py`).

Running locally for a look: `uv run --project .. python server.py http` serves it on `http://127.0.0.1:8000` with the secrets from the environment. This is a separate project from the repository root so that `arcade deploy` packages only what the server needs.

Keep `from __future__ import annotations` out of the tool modules: `arcade-core` reads each parameter's annotation as a live type to find the context argument and build the schema.
