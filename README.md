# Strands Agents Loan Desk with Arcade and Neo4j

A hands-on workshop: build a loan desk agent with [Strands Agents](https://strandsagents.com), give it a loan book that lives in a [Neo4j](https://neo4j.com) graph, and govern every tool call it makes with [Arcade](https://arcade.dev), so its limits hold however the prompt is worded.

A loan officer asks the agent, in plain language, to approve a $95K loan for a second bakery location. The agent searches the loan book, reads the file and calls the approval tool as her. Arcade sends that call to this repo's control plane before it runs, and the control plane refuses it: $95K is over her $50K approval authority. The refusal tells the agent how to escalate. The request lands with the one approver with enough authority, he approves it from his own terminal, and her retry goes through, once. A $32K loan she *could* approve on its own is refused too, because the graph shows its owner's other businesses already carry approved exposure. Every decision is a line in the gate's audit log.

## Why we built this

An agent that writes to a real business system needs limits the model cannot reason around. The thesis is one sentence: **treat the LLM as an adversary, and put the controls somewhere it cannot reason around.**

A limit written into a system prompt is a suggestion. So the agent's instructions carry no limits at all (a test keeps it that way), and every control lives outside the model: in hooks Arcade calls on every tool call, keyed on who the call is for, reading who that person is from the graph. The model never gets a vote.

## The workshop

| Time | Module | You end with |
|---|---|---|
| 9:00 to 9:15 | [00 Welcome and setup](./docs/modules/00-setup.md) | The repo installed, the tests green, a Neo4j database and an Arcade project ready. |
| 9:15 to 9:45 | [01 Build a Strands agent](./docs/modules/01-build.md) | A Strands agent on Bedrock or Anthropic with a local tool, answering from the terminal. |
| 9:45 to 10:30 | [02 Connect: Arcade, Neo4j and just-in-time auth](./docs/modules/02-connect.md) | The loan graph seeded, the Loan Desk MCP server deployed to Arcade, the agent calling it as Alice, and Slack authorized at first use. |
| 10:30 to 10:45 | Break | |
| 10:45 to 11:30 | [03 Govern: policy hooks and a human in the loop](./docs/modules/03-govern.md) | The control plane registered with Arcade: a refusal, an escalation, Charlie's approval, a single-use retry, redaction and a stripped prompt injection. |
| 11:30 to 12:30 | [04 Observe, evaluate, and go to production](./docs/modules/04-ship.md) | Traces, an eval suite that catches what policy cannot, and the production checklist. |
| 12:30 to 1:00 | [05 Q&A and wrap-up](./docs/modules/05-wrap-up.md) | The whole story once more, end to end, and what you take home. |

Modules 01 to 04 each have a hands-on exercise. `make start M=01` puts that module's TODOs in place, `make check M=01` runs its tests, and `make solve M=01` puts the solution in if you fall behind. The repository as cloned is the solved state, so every module also runs without doing the exercise.

## Prerequisites

- **Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)**. `make` is optional; every target is one `uv run` command.
- **A model**, one of:
  - **Amazon Bedrock** (the Strands default): an AWS account with Bedrock access to an Anthropic Claude model in your region, and credentials in your usual chain (`aws configure`, `aws sso login`, or `AWS_PROFILE`). Set `MODEL_PROVIDER=bedrock` and `AWS_REGION`.
  - **Anthropic**: an API key. Set `ANTHROPIC_API_KEY` (and `MODEL_PROVIDER=anthropic`, or leave it empty).
  - Neither, to start: the agent runs on a scripted model with no key until you give it one.
- **An [Arcade](https://api.arcade.dev/dashboard) account**, a project, a project API key, and the Arcade CLI: `uv tool install arcade-mcp`, then `arcade login` ([CLI reference](https://docs.arcade.dev/en/references/arcade-cli)).
- **Neo4j**, one of:
  - **[Neo4j Aura Free](https://console.neo4j.io)** (recommended): reachable from Arcade's cloud, where the deployed Loan Desk tools run.
  - **Docker**: `make neo4j-up` starts Neo4j 5.26 Community on your laptop. The deployed tools then need a TCP tunnel to reach it ([02-connect](./docs/modules/02-connect.md)).
- **[ngrok](https://ngrok.com)** (free account), so Arcade can call the control plane on your laptop.
- **Optional, a Slack workspace** you can authorize, for the "tell Charlie" step.

## Quickstart

```sh
git clone <this repository> strands-loan-desk && cd strands-loan-desk
uv sync
make test                       # credential-free: model, Arcade and Neo4j are all faked
cp .env.example .env            # fill it in block by block as the modules reach each one
uv run ask "Which loans are pending?"
```

With nothing in `.env`, that last command answers from the scripted model and says the loan desk is not connected. The modules connect it one piece at a time:

1. **Model** (01): `MODEL_PROVIDER` and its credentials. `uv run ask "What's the monthly payment on 95k over 7 years at 8%?"` uses the local `loan_payment` tool.
2. **Graph** (02): `NEO4J_URI`, `NEO4J_PASSWORD`, then `uv run seed`. Or paste [`neo4j/seed.cypher`](./neo4j/seed.cypher) into Neo4j Browser.
3. **Tools** (02): `cd mcp && cp .env.example .env` (the same Neo4j values), `arcade deploy -e server.py`, then `ARCADE_API_KEY` in the root `.env`. `uv run tools` lists what Arcade offers Alice.
4. **Control plane** (03): `GATE_TOKEN=$(openssl rand -hex 32)` in `.env`, `uv run gate`, `ngrok http 8742`, and register the four URLs it prints in the Arcade dashboard under Contextual Access.
5. **Ask**: `uv run ask "Approve the Northwind loan for the full $95K and double-check your work."` The refusal, the escalation and the approval are in [03-govern](./docs/modules/03-govern.md).

## Try it out

- **Above her authority.** As Alice (the default), ask for the $95K approval. The transcript shows `LoanDesk_ApproveLoan` refused with the hook's own words, "DENIED: approving LN-2291 for 95000 exceeds your approval authority of 50000. To proceed, call LoanDesk_RequestApproval…", and the agent calling `LoanDesk_RequestApproval` because the refusal told it to. Nothing in its instructions mentions escalating.
- **The human in the loop.** `uv run approve --as charlie@bank.example` lists what is waiting on Charlie; `uv run approve --as charlie@bank.example APR-… approve --note "Collateral checks out"` decides it. That is itself a governed tool call, checked for Charlie's clearance and refused for the requester. Ask Alice's agent again: the retry passes on a single-use grant, and a second retry is refused.
- **What only a graph shows.** Ask for LN-2297, Lakeside Bakehouse, $32K: under Alice's $50K, and refused anyway, because its owner also owns Two Rivers Brewing ($47.5K approved). The hook walks the ownership graph on every call.
- **Bob never sees the button.** `uv run ask --as bob@bank.example "Approve LN-2292"`. Bob is a credit analyst; the access hook removes the approval tools from his list, so there is nothing to refuse.
- **What the model never reads.** Ask Alice's agent for Northwind's bank account number and tax id: `[REDACTED]`, masked in the post hook before the output reached the model. As Charlie they come through. For everyone, the instruction someone pasted into LN-2291's underwriter notes is stripped.
- **Change the graph, not the code.** `uv run officers set-clearance alice@bank.example 250000`, and the same prompts pass. `uv run seed --reset` puts everything back.

## How Neo4j is wired in, and why not the Neo4j MCP server

The loan book is a graph: officers, companies, the people who own them, loans, guarantees, decisions and approval requests. The agent reaches it only through **typed tools in a Loan Desk MCP server deployed to Arcade** (`LoanDesk_SearchLoans`, `LoanDesk_GetBorrowerNetwork`, `LoanDesk_ApproveLoan`, …). Each one runs a fixed, parameterized Cypher query with Neo4j credentials held as Arcade secrets. The control plane reads the same database to decide each call.

We considered the official [Neo4j MCP server](https://github.com/neo4j/mcp) (`get-schema`, `read-cypher`, `write-cypher`) and chose not to put it in the agent's hands. The reasons are the governance story:

1. **A policy needs arguments it can read.** "Approve no more than your clearance" is a check on `ApproveLoan(loan_id, amount)`. On `write-cypher(query)` the amount is somewhere inside a string the model wrote, and a policy that has to parse Cypher to find it has already lost.
2. **The model should not write the business logic.** With free-form Cypher, the model decides what "approve" means. With a typed tool, the bank does, once, in reviewed code.
3. **Credentials stay out of the agent.** The deployed tools read their Neo4j secrets from Arcade at call time; the agent and the laptop never hold a database password.

The Neo4j MCP server is still a good tool for a person exploring the graph read-only, from Claude Desktop or Neo4j's own tooling. Module 02 uses Neo4j Browser for that.

## Compared with the LangChain workshop

This is the Strands Agents and Neo4j counterpart of Arcade's [deep-agents-governance](https://github.com/ArcadeAI/deep-agents-governance) workshop. It follows that workshop's agenda, loan desk, cast (Alice, Bob, Charlie, Michael) and control points. What changes:

| | LangChain workshop | This workshop |
|---|---|---|
| Agent | LangChain Deep Agent on Managed Deep Agents, `ArcadeMiddleware` | Strands `Agent`, an Arcade toolbox in [`arcade_tools.py`](./agent/loan_agent/arcade_tools.py) |
| Model | the room's model key | Amazon Bedrock or Anthropic, or scripted |
| System of record | a loan REST API with SQLite | a Neo4j graph, reached through typed tools |
| Identity | Okta sign-in, the ID token's email | a persona (`--as`), with the production path in [`docs/production.md`](./docs/production.md) |
| Approver's side | an approval web page | `uv run approve`, the same governed tool call with no model in it |
| Observe | LangSmith | OpenTelemetry from Strands, and Strands Evals |

## Repository layout

| Path | What it is |
|---|---|
| [`agent/`](./agent/README.md) | The Strands agent (`loan_agent`): model choice, Arcade toolbox, CLI, evals, an optional AgentCore entrypoint. |
| [`mcp/`](./mcp/README.md) | The Loan Desk MCP server, deployed to Arcade with `arcade deploy`: eight typed tools over Neo4j. |
| [`gate/`](./gate/README.md) | The control plane: [`policy.json`](./gate/policy.json) and the access, pre and post hooks Arcade calls. |
| [`neo4j/`](./neo4j/README.md) | The graph's seed data, the loader, and the paste-able `seed.cypher`. |
| [`modules/`](./modules) | Each hands-on module's `starter/` and `solution/` files. |
| [`docs/`](./docs/architecture.md) | One page per module, plus architecture, production and FAQ. |
| [`tests/`](./tests) | The credential-free suite, and an optional live Neo4j contract test. |

## Tests

```sh
make test          # or: uv run pytest -q
make check M=03    # one module's tests
```

The suite needs no credentials and no network. It replaces the model with a scripted Strands model, Arcade with a fake Engine that calls the real control plane over HTTP and runs the real Loan Desk tool functions, and Neo4j with an in-memory graph loaded from the same seed. It refuses to read `.env`. With a Neo4j you can wipe, `NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=… uv run pytest tests/test_neo4j_live.py` runs the Cypher itself against the database.

## Further reading

- [`docs/architecture.md`](./docs/architecture.md): the control points, who each call runs as, and what lives where.
- [`docs/production.md`](./docs/production.md): what changes between the laptop and production: identity, hosting the gate, Neo4j, AgentCore.
- [`docs/faq.md`](./docs/faq.md): why the limits live in hooks, why not Strands hooks or Bedrock Guardrails for policy, why typed tools over the Neo4j MCP server, using another model.
- [`gate/README.md`](./gate/README.md): the policy vocabulary and the hook contract.

## License

MIT, see [`LICENSE`](./LICENSE).
