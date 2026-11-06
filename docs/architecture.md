# Architecture

```
 you ──> uv run ask ──> Strands Agent ──(model calls)──> Bedrock / Anthropic
                            │
                            │ every tool that touches the bank
                            ▼
                    Arcade Engine (project API key, user_id = the officer)
                     │        │  access / pre / post hooks (HTTPS, Bearer)
                     │        └──────────────> gate/  (on your laptop, behind ngrok)
                     │                            │ reads officers, requests, exposure
                     ▼                            ▼
       Loan Desk MCP server (Arcade cloud) ──> Neo4j (Aura, or Docker + tunnel)
       Slack / Gmail (Arcade's own toolkits, OAuth as you)
```

## The control points

| Hook | When Arcade calls it | What it does here |
|---|---|---|
| access | when it lists tools for a user | hides `ApproveLoan`, `DenyLoan` and `Decide` from credit analysts, and every loan desk tool from anyone who is not an officer |
| pre | before a tool runs | holds approvals to clearance and group exposure, finds and spends a single-use approval, guards `Decide` |
| post | after a tool runs, before the model sees the output | masks bank account numbers and tax ids below $250K clearance, strips instructions pasted into free text |

A fourth control is the routing itself (`mcp/loan_desk/approvals.py`): an approval request goes to the lowest clearance that covers the amount, never to the requester, and the agent cannot choose the approver.

`--confirm` adds a Strands interrupt before anything is sent outside the bank. That is the person's consent, not the bank's authority, and nothing in the governance depends on it.

## Who each call runs as

Every call goes to Arcade with the project API key and a `user_id`.

- **Loan desk tools** run as the persona: `LOAN_DESK_USER`, or `--as`. That is the email the hooks look up in the graph, and the actor `mcp/loan_desk/loans.py` records on a decision.
- **Slack and Gmail** run as `CONNECTED_APPS_USER`, your own Arcade email, when it is set. Arcade's built-in OAuth apps bind a grant to the Arcade account that authorized it, so they cannot run as `alice@bank.example`.

The persona is a workshop convenience: anyone with the project key can claim any `user_id`. Production replaces it with a verified identity ([`production.md`](./production.md)).

## The graph

```
(:Officer {email, name, role, clearance})
(:Person {id, name})-[:OWNS {pct}]->(:Company {id, name, contact_email, annual_revenue, years_in_business, bank_account_number, tax_id})
(:Company)-[:APPLIED_FOR]->(:Loan {id, amount, status, purpose, submitted_at, credit_score, underwriter_notes})
(:Person)-[:GUARANTEES]->(:Loan)
(:Decision {id, kind, amount, reason, decided_at, decided_by})-[:ON]->(:Loan)
(:Officer)-[:MADE]->(:Decision)
(:Officer)-[:REQUESTED]->(:ApprovalRequest {id, action, resource_id, amount, justification, status, requested_by, routed_to, decided_by, decided_at, note, consumed_at})-[:FOR]->(:Loan)
(:ApprovalRequest)-[:ROUTED_TO]->(:Officer)
```

The tools write loans, decisions and approval requests. The gate reads officers, requests and group exposure, and writes exactly one property: `consumed_at`, when it spends an approval. One database is how Charlie's approval through the tools becomes the grant the gate finds on Alice's retry.

## What lives where

| Path | Role |
|---|---|
| `agent/loan_agent/agent.py` | `build_agent`: one Strands `Agent` per person and run |
| `agent/loan_agent/arcade_tools.py` | the Arcade toolbox: pinned toolkit, Tool Rec selector, identity, results |
| `agent/loan_agent/models.py`, `scripted.py` | Bedrock, Anthropic, or the scripted model |
| `agent/loan_agent/cli.py` | `ask`, `approve`, `tools` |
| `agent/loan_agent/evals/` | dataset, checks and runner on Strands Evals |
| `mcp/loan_desk/` | the deployed tools and their Cypher |
| `gate/loan_gate/` | policy engine, hooks, directory, audit, server |
| `neo4j/loan_graph/` | seed data and loader |
| `tests/support/` | the in-memory graph and the fake Arcade Engine |
