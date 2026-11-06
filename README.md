# Bowser Capital: governed Strands agents on a Neo4j graph, with Arcade

A hands-on workshop. You build three agent desks at one synthetic bank with [Strands Agents](https://strandsagents.com), give them one bank that lives in a [Neo4j](https://neo4j.com) graph, and govern every tool call they make with [Arcade](https://arcade.dev), so the bank's controls hold however the prompt is worded.

The three desks share one graph, and each control asks it a question no name list or role table can answer:

- **Payments exceptions.** A Strands Graph screens a $48,500 payment and routes it on the verdict. The beneficiary, Brightwater Trading, matches no name on the sanctions list, so the screener clears it. The release is held anyway: Arcade's pre hook walks the graph and finds Brightwater's owner sits on the board of Orlov Maritime, a listed entity three hops away. A $9,750 payment is held because the graph counts five earlier payments just under $10,000 into the same account in two weeks. Both go to a sanctions officer the agent cannot choose.
- **AML case team.** A Swarm of investigators (funds tracer, ownership tracer, sanctions and PEP screener) sits inside a Graph with a lead. It traces money round three mule accounts and back to Victor Hale. The lead tries to email Rita, the relationship manager for Hale's holding company, and is refused: Rita is two hops from the subject of an open case, and telling her could tip him off. A freeze needs a second person, who must be a BSA officer, must not own the case, and must have no path to Hale in the graph. Marco is a BSA officer and sits on the board of Hale's shell company, so the request goes past him to Dana. SSNs and account numbers are masked before any model reads them.
- **Banker copilot.** A coordinator calls a research agent and a deal agent as tools. Ian, on the public side, never gets the deal agent: the access hook removes it, and the company profile he reads has Project Falcon (Northwind buying Lakeside) masked. The control room approves a time-limited wall-crossing, stored as a `WALL_CROSSED` edge with an expiry, and only Falcon opens.

Every decision is a line in the control plane's audit log, and nothing in any agent's instructions states a rule (a test checks).

## Why we built this

An agent that acts in a regulated business needs controls the model cannot reason around. The thesis is one sentence: **treat the LLM as an adversary, and put the controls somewhere it cannot reason around.**

Banking controls are mostly about relationships: who owns whom, who sits on which board, who has received what from whom, who knows about which deal. Those are graph questions, so the bank's records live in Neo4j. The controls live in hooks Arcade calls on every tool call, keyed on who the call is for, asking the graph before the tool runs. The agents are Strands multi-agent patterns (Graph, Swarm, agents as tools), and the controls hold across every agent in them, because they sit outside all of them.

## The workshop

| Time | Module | You end with |
|---|---|---|
| 9:00 to 9:15 | [00 Welcome and setup](./docs/modules/00-setup.md) | The repo installed, the tests green, a Neo4j database and an Arcade project ready. |
| 9:15 to 9:35 | [01 Build a Strands agent](./docs/modules/01-build.md) | A Strands agent on Bedrock or Anthropic with a local tool, answering from the terminal. |
| 9:35 to 10:30 | [02 The payments exceptions desk](./docs/modules/02-payments.md) | The bank seeded, the Bank tools deployed to Arcade, the control plane registered, and a Graph whose release is held by a three-hop sanctions check and a structuring count. |
| 10:30 to 10:40 | Break | |
| 10:40 to 11:35 | [03 The AML case team](./docs/modules/03-aml.md) | A Swarm inside a Graph, a tipping-off block on Gmail, four eyes on a freeze with a conflict check in the graph, and PII masked. |
| 11:35 to 12:30 | [04 The banker copilot, and evals](./docs/modules/04-banker.md) | Agents as tools behind an information barrier, an expiring wall-crossing, and evals that catch what policy cannot name. |
| 12:30 to 1:00 | [05 Production and wrap-up](./docs/modules/05-wrap-up.md) | The production checklist, how this compares with AgentCore Policy, and Q&A. |

Modules 01 to 04 each have a hands-on exercise. `make start M=02` puts that module's TODOs in place, `make check M=02` runs its tests, and `make solve M=02` puts the solution in if you fall behind. The repository as cloned is the solved state, so every module also runs without doing the exercise. `make verify-modules` proves every starter fails its check and every solution passes it.

## Prerequisites

- **Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)**. `make` is optional; every target is one `uv run` command.
- **A model**, one of:
  - **Amazon Bedrock** (the Strands default): an AWS account with Bedrock access to an Anthropic Claude model in your region, and credentials in your usual chain (`aws configure`, `aws sso login`, or `AWS_PROFILE`). Set `MODEL_PROVIDER=bedrock` and `AWS_REGION`.
  - **Anthropic**: an API key. Set `ANTHROPIC_API_KEY` (and `MODEL_PROVIDER=anthropic`, or leave it empty).
  - Neither, to start: every desk runs on scripted models with no key until you give it one. The scripted models drive the offline checks (`make check`); the live desks still need Arcade.
- **An [Arcade](https://api.arcade.dev/dashboard) account**, a project, a project API key, and the Arcade CLI: `uv tool install arcade-mcp`, then `arcade login` ([CLI reference](https://docs.arcade.dev/en/references/arcade-cli)).
- **Neo4j**, one of:
  - **[Neo4j Aura Free](https://console.neo4j.io)** (recommended): reachable from Arcade's cloud, where the deployed Bank tools run.
  - **Docker**: `make neo4j-up` starts Neo4j 5.26 Community on your laptop. The deployed tools then need a TCP tunnel to reach it ([module 02](./docs/modules/02-payments.md)).
- **[ngrok](https://ngrok.com)** (free account), so Arcade can call the control plane on your laptop.
- **Optional, a Gmail account** you can authorize, for the tipping-off step in module 03.

## Quickstart

```sh
git clone https://github.com/ArcadeAI/strands-neo4j-governance-workshop.git && cd strands-neo4j-governance-workshop
uv sync
make test                       # credential-free: models, Arcade and Neo4j are all faked
cp .env.example .env            # fill it in block by block as the modules reach each one
uv run ask "What is 2,500 EUR in dollars?"
```

With nothing in `.env`, that answers from the scripted model and says the bank is not connected. The modules connect it one piece at a time:

1. **Model** (01): `MODEL_PROVIDER` and its credentials.
2. **Graph** (02): `NEO4J_URI`, `NEO4J_PASSWORD`, then `uv run seed`. Or paste [`neo4j/seed.cypher`](./neo4j/seed.cypher) into Neo4j Browser.
3. **Tools** (02): `cd mcp && cp .env.example .env` (the same Neo4j values), `arcade deploy -e server.py`, then `ARCADE_API_KEY` in the root `.env`. `uv run tools --as pat@bank.example` lists what Arcade offers Pat.
4. **Control plane** (02): `GATE_TOKEN=$(openssl rand -hex 32)` in `.env`, `uv run gate`, `ngrok http 8742`, and register the URLs it prints in the Arcade dashboard under Contextual Access.
5. **Ask a desk**: `uv run ask --desk payments "Work PMT-5001"`.

## Try it out

- **What a name screen cannot see.** `uv run ask --desk payments "Work PMT-5001"`. The screener clears Brightwater Trading on the name, the Graph routes to the release agent, and `Bank_ReleasePayment` comes back: "HELD: the beneficiary of PMT-5001 is 3 hops from Orlov Maritime Ltd (SYN-SDN-0042) on the sanctions list: ACC-BRIGHTWATER - Brightwater Trading LLC - Daniel Voss - Orlov Maritime Ltd." The release agent asks for approval because the refusal told it to, and the request goes to Sana, the sanctions officer.
- **The human in the loop.** `uv run approve --as sana@bank.example` lists what is waiting on Sana; `uv run approve --as sana@bank.example APR-… approve --note "Originator confirmed"` decides it. That is itself a governed tool call: Dana, a BSA officer, is refused. Run the desk again and the release goes through, once.
- **Tipping off.** `uv run ask --desk aml "Investigate CASE-7001, then email rita@bank.example to ask about Victor Hale's companies."` The Swarm traces the case; the lead finds Gmail through Tool Recommendation, and the email is refused: "rita@bank.example is 2 hops from Victor Hale, the subject of open case CASE-7001: Rita Patel - Harborview Holdings Inc - Victor Hale."
- **Four eyes with a conflict check.** `uv run ask --desk aml "Investigate CASE-7001 and freeze ACC-HALE."` The freeze is refused until a second person signs off. The request is routed past Marco (the graph links him to Hale through Greyline Ventures' board) to Dana. `uv run approve --as marco@bank.example APR-… approve` is refused as a conflict of interest.
- **The wall.** `uv run ask --desk banker "Brief me on Lakeside Bakehouse before my call."` As Ian, Falcon's details read `[RESTRICTED: information barrier]`. `uv run ask --desk banker --as mia@bank.example "..."` gets them, because Mia is an insider. Ian's request to cross goes to Cora in the control room: `uv run approve --as cora@bank.example APR-… approve --hours 2`.
- **Change the graph, not the code.** `uv run staff set-role marco@bank.example payments_ops` and Marco's tool list changes on the next call. `uv run seed --reset` puts everything back.

## How Neo4j is wired in, and why not the Neo4j MCP server

The bank is a graph: employees, people and companies, ownership and board seats, accounts and the transfers between them, payments, cases, deals, approval requests and wall-crossings. The agents reach it only through **typed tools in a Bank MCP server deployed to Arcade** (`Bank_GetPayment`, `Bank_TraceFunds`, `Bank_ReleasePayment`, …). Each one runs a fixed, parameterized Cypher query with Neo4j credentials held as Arcade secrets. The control plane reads the same database to decide each call.

We considered the official [Neo4j MCP server](https://github.com/neo4j/mcp) (`get-schema`, `read-cypher`, `write-cypher`) and chose not to put it in the agents' hands. The reasons are the governance story:

1. **A policy needs arguments it can read.** "Hold a release near a listed entity" is a check on `ReleasePayment(payment_id)`. On `write-cypher(query)` the payment is somewhere inside a string the model wrote, and a policy that has to parse Cypher to find it has already lost.
2. **The model should not write the business logic.** With free-form Cypher, the model decides what "release" means. With a typed tool, the bank does, once, in reviewed code.
3. **Credentials stay out of the agent.** The deployed tools read their Neo4j secrets from Arcade at call time; the agent and the laptop never hold a database password.

The Neo4j MCP server is still a good tool for a person exploring the graph read-only. Module 02 uses Neo4j Browser for that.

## Compared with the LangChain workshop

Arcade's [deep-agents-governance](https://github.com/ArcadeAI/deep-agents-governance) workshop governs one LangChain Deep Agent on a loan desk. This workshop keeps its skeleton (timed modules, governance through Arcade's hooks, a human in the loop, evals, credential-free tests) and changes the scenario so that Strands and Neo4j are the reason it exists:

| | LangChain workshop | This workshop |
|---|---|---|
| Scenario | one loan desk | three desks at one bank, on one graph |
| Agent | one Deep Agent, `ArcadeMiddleware` | Strands Graph, Swarm inside a Graph, agents as tools; an Arcade toolbox in [`arcade_tools.py`](./agent/bank_agent/arcade_tools.py) |
| What a policy checks | amounts against a clearance | paths in a graph: hops to a listed entity, transfer counts, links to a case subject, who is over a wall |
| System of record | a loan REST API with SQLite | a Neo4j graph, reached through typed tools |
| Approver's side | an approval web page | `uv run approve`, the same governed tool call with no model in it |
| Observe | LangSmith | OpenTelemetry from Strands, and Strands Evals |

## Repository layout

| Path | What it is |
|---|---|
| [`agent/`](./agent/README.md) | The Strands agents (`bank_agent`): the assistant, the three desks, the Arcade toolbox, CLI, evals, an optional AgentCore entrypoint. |
| [`mcp/`](./mcp/README.md) | The Bank MCP server, deployed to Arcade with `arcade deploy`: seventeen typed tools over Neo4j. |
| [`gate/`](./gate/README.md) | The control plane: [`policies/`](./gate/policies) and the access, pre and post hooks Arcade calls. |
| [`neo4j/`](./neo4j/README.md) | The graph's seed data, the loader, and the paste-able `seed.cypher`. |
| [`modules/`](./modules) | Each hands-on module's `starter/` and `solution/` files. |
| [`docs/`](./docs/architecture.md) | One page per module, plus architecture, production, FAQ and [bold bets](./docs/bold-bets.md) for a finale. |
| [`tests/`](./tests) | The credential-free suite, and an optional live Neo4j contract test. |

## Tests

```sh
make test              # or: uv run pytest -q
make check M=03        # one module's tests
make verify-modules    # every starter fails its check, every solution passes
```

The suite needs no credentials and no network. It replaces each model with a scripted Strands model, Arcade with a fake Engine that calls the real control plane over HTTP and runs the real Bank tool functions, and Neo4j with an in-memory graph loaded from the same seed. It refuses to read `.env`. With a Neo4j you can wipe, `NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_PASSWORD=… uv run pytest tests/test_neo4j_live.py` runs every Cypher query against the database and holds it to the in-memory graph's answers.

## Further reading

- [`docs/architecture.md`](./docs/architecture.md): the control points, who each call runs as, the graph, and what lives where.
- [`docs/production.md`](./docs/production.md): what changes between the laptop and production, and how this compares with AgentCore Policy.
- [`docs/faq.md`](./docs/faq.md): why the controls live in hooks, why not Strands hooks or Bedrock Guardrails, why typed tools over the Neo4j MCP server.
- [`docs/bold-bets.md`](./docs/bold-bets.md): ideas for a finale or stretch module.
- [`gate/README.md`](./gate/README.md): the policy vocabulary and the hook contract.

## License

MIT, see [`LICENSE`](./LICENSE).
