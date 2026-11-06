# Architecture

```
 you ──> uv run ask --desk … ──> Strands Graph / Swarm / agents as tools ──(model calls)──> Bedrock / Anthropic
                                     │
                                     │ every tool that touches the bank, or leaves it
                                     ▼
                     Arcade Engine (project API key, user_id = the employee)
                      │        │  access / pre / post hooks (HTTPS, Bearer)
                      │        └──────────────> gate/  (on your laptop, behind ngrok)
                      │                            │ asks the graph: hops, counts, links, walls
                      ▼                            ▼
        Bank MCP server (Arcade cloud) ──────> Neo4j (Aura, or Docker + tunnel)
        Gmail / Slack (Arcade's own toolkits, OAuth as you)
```

## The desks

| Desk | Strands pattern | Agents | Acts with |
|---|---|---|---|
| Payments exceptions (module 02) | `GraphBuilder` graph with conditional edges | `screen`, `release`, `hold` | `Bank_ReleasePayment` (release node only), `Bank_HoldPayment` |
| AML case team (module 03) | a `Swarm` as one node of a Graph, an interrupt hook on the lead | `funds_tracer`, `ownership_tracer`, `screener` in the Swarm; `lead` | `Bank_FreezeAccount`, `Bank_FileSar`, Gmail or Slack found at run time |
| Banker copilot (module 04) | agents as tools (`Agent.as_tool`) | `coordinator`, `company_research`, `deal_desk` (only if Arcade lists deal tools) | `Bank_RequestApproval` for a wall-crossing |

Each agent gets only the Bank tools its job needs, picked by name from what Arcade lists for the employee (`ArcadeToolbox.pick`). An agent that should not release a payment does not hold the tool. That is least privilege inside the desk; the bank's controls are outside it.

## The control points

| Hook | When Arcade calls it | What it does here |
|---|---|---|
| access | when it lists tools for a user | hides release and hold from anyone outside payments operations, the case tools from anyone outside the AML team, the deal tools from anyone over the wall for no deal, `Decide` from anyone who approves nothing, and every Bank tool from someone the graph does not know |
| pre | before a tool runs | holds a release near a listed entity or into a structuring pattern; refuses a message to anyone near an open case's subject; needs a second person for a freeze or a SAR; refuses an approver who is the requester, owns the case, or has a path to the subject; refuses a deal read across the wall; finds and spends a single-use approval |
| post | after a tool runs, before a model sees the output | masks SSNs, dates of birth and account numbers for everyone; masks each deal record the caller is not over the wall for; strips instructions pasted into free text |

The rules are in [`gate/policies/`](../gate/policies), one file per desk, loaded in order. A fourth control is the routing itself (`mcp/bank_tools/approvals.py`): a request goes to the first employee on the rota with the role the action needs, never the requester and, for a case, never anyone with a path to the subject. The agent cannot choose its approver.

The AML lead's interrupt (`agent/bank_agent/confirm.py`) stops the run before a freeze, a SAR or anything outbound and asks the investigator. That is the person's consent, not the bank's authority, and nothing in the governance depends on it.

## Who each call runs as

Every call goes to Arcade with the project API key and a `user_id`.

- **Bank tools** run as the employee: `BANK_USER`, `--as`, or the desk's usual employee. That is the email the hooks look up in the graph, and the actor the tools record on a release, a freeze or a decision.
- **Gmail and Slack** run as `CONNECTED_APPS_USER`, your own Arcade email, when it is set. Arcade's built-in OAuth apps bind a grant to the Arcade account that authorized it, so they cannot run as `ava@bank.example`. The tipping-off rule checks the recipient, so it holds whoever sends.

The employee is a workshop convenience: anyone with the project key can claim any `user_id`. Production replaces it with a verified identity ([`production.md`](./production.md)).

## The graph

```
(:Employee {email, name, role, desk, slack, rota})
(:Party:Person {id, name, dob, ssn, pep, pep_detail})       (:Party:Company {id, name, ein, industry, hq, annual_revenue, public_profile})
(:Party:Sanctioned {list_entry, list, aliases, program})    a label on a listed Person or Company
(:Party)-[:HOLDS]->(:Account {id, number, bank, kind, status})
(:Party)-[:OWNS {pct}]->(:Company)          (:Person)-[:DIRECTOR_OF]->(:Company)
(:Employee)-[:MANAGES]->(:Company)          (:Employee)-[:IS]->(:Person)
(:Account)-[:PAID {id, amount, at}]->(:Account)
(:Payment {id, amount, currency, created_at, status, alert, reference})-[:FROM|TO]->(:Account)
(:Case {id, status, opened_at, alert, owner})-[:SUBJECT]->(:Party)      (:Case)-[:ASSIGNED_TO]->(:Employee)
(:Deal {id, codename, stage, valuation, terms})-[:TARGET|ACQUIRER]->(:Company)
(:Employee)-[:INSIDER_ON]->(:Deal)          (:Employee)-[:WALL_CROSSED {expires_at, approved_by, request_id, granted_at}]->(:Deal)
(:ApprovalRequest {id, action, resource_id, case_id, justification, status, requested_by, routed_to, decided_by, decided_at, note, consumed_at})
(:Sar {id, narrative, filed_by, filed_at})-[:FOR]->(:Case)
```

The graph questions the gate asks, all bounded `shortestPath` or aggregate queries in `gate/bank_gate/directory.py`:

| Question | Relationships walked |
|---|---|
| How far is this payment's beneficiary from a listed entity? | `HOLDS`, `OWNS`, `DIRECTOR_OF` |
| How many payments just under the threshold has this account received in the window, from how many senders? | `PAID` |
| Is this recipient near the subject of an open case? | `HOLDS`, `OWNS`, `DIRECTOR_OF`, `MANAGES`, `IS` |
| Is this approver linked to the case's subject? | the same |
| Which deals is this employee over the wall for, now? | `INSIDER_ON`, `WALL_CROSSED` with `expires_at` in the future |

The tools write payments' status, freezes, SARs, approval requests and wall-crossings. The gate reads everything and writes exactly one property: `consumed_at`, when it spends an approval. One database is how Sana's approval through the tools becomes the grant the gate finds on Pat's retry.

## What lives where

| Path | Role |
|---|---|
| `agent/bank_agent/agent.py` | `build_agent`: the module 01 assistant |
| `agent/bank_agent/desks/` | the three desks, their prompts and their default scripts; `common.py` builds an agent from a model, tools and the transcript |
| `agent/bank_agent/arcade_tools.py` | the Arcade toolbox: pinned toolkit, Tool Rec selector, identity, results |
| `agent/bank_agent/models.py`, `scripted.py` | Bedrock, Anthropic, or the scripted model |
| `agent/bank_agent/cli.py` | `ask`, `approve`, `tools` |
| `agent/bank_agent/evals/` | dataset, checks and runner on Strands Evals |
| `mcp/bank_tools/` | the deployed tools and their Cypher |
| `gate/bank_gate/`, `gate/policies/` | policy engine, hooks, directory, audit, server; the rules |
| `neo4j/bank_graph/` | seed data and loader |
| `tests/support/` | the in-memory graph and the fake Arcade Engine |
