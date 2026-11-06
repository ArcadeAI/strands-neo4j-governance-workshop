# Welcome and setup

**9:00 to 9:15.** The agenda, the bank, the cast, and a laptop that can run the rest.

You leave with the repository installed and its tests green, a Neo4j database you can reach, an Arcade project with a key, and a model, or the decision to start on the scripted one.

## Before the workshop

- **Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)**.
- **An [Arcade](https://api.arcade.dev/dashboard) account.** Use the default project it makes, and create an API key in it ([Get an API key](https://docs.arcade.dev/en/get-started/setup/api-keys)). Install the CLI and log in to the same project:

      uv tool install arcade-mcp
      arcade login

- **A Neo4j database.** [Aura Free](https://console.neo4j.io) is the easy path: create a free instance and keep the connection URI (`neo4j+s://…`), the username and the generated password it shows once. The deployed Bank tools run in Arcade's cloud, and Aura is reachable from there. Docker works too (`make neo4j-up`), with a tunnel in module 02.
- **A model.** Amazon Bedrock with access to an Anthropic Claude model in your region, with AWS credentials on the laptop (`aws sts get-caller-identity` works), or an Anthropic API key. Neither is needed to start.
- **An [ngrok](https://ngrok.com) account**, for module 02.

## What you build

1. Install and run the tests:

       git clone <this repository> bowser-capital && cd bowser-capital
       uv sync
       make test

   Every test passes with no credentials: the models, Arcade and Neo4j are all faked (`tests/support/`).
2. Copy the environment file: `cp .env.example .env`. Fill in only what you have; each module says which block it needs.
3. Ask the assistant something:

       uv run ask "What is 2,500 EUR in dollars?"

   It answers from the scripted model, and says the bank is not connected yet. That is the point to start from.

## The bank and the cast

Bowser Capital is synthetic, and so is everything in it: names, accounts, SSNs (900- area numbers, which are never issued) and the sanctions list, `SYN-SDN`, which is shaped like a real list and is not one. Its staff live in the graph, each with a role:

| Employee | Role | Desk |
|---|---|---|
| `pat@bank.example` | `payments_ops` | Payments operations: works the exceptions queue (module 02) |
| `sana@bank.example` | `sanctions_officer` | Sanctions compliance: decides held releases |
| `ava@bank.example` | `aml_investigator` | Financial intelligence unit: owns CASE-7001 (module 03) |
| `marco@bank.example` | `bsa_officer` | Deputy BSA officer, and a director of Greyline Ventures, Victor Hale's holding company |
| `dana@bank.example` | `bsa_officer` | BSA officer: decides freezes and SARs |
| `rita@bank.example` | `relationship_manager` | Covers Harborview Holdings, which Hale controls |
| `omar@bank.example` | `relationship_manager` | Covers Northwind, Cedar and Harborline; no link to Hale |
| `ian@bank.example` | `corporate_banker` | Public-side coverage for Lakeside and Kestrel (module 04) |
| `mia@bank.example` | `mna_banker` | Private-side M&A, insider on Projects Falcon and Heron |
| `cora@bank.example` | `compliance_officer` | The control room: decides wall-crossings |

You play all of them with `--as`. Each desk has a usual employee (Pat for payments, Ava for AML, Ian for the banker desk); `BANK_USER` in `.env` overrides it. `uv run staff list` prints the table from the graph once it is seeded.

The terminology is US: a SAR is a Suspicious Activity Report under the Bank Secrecy Act, filed with FinCEN, and the BSA officer is the person accountable for the AML program.

## What to look at

- [`README.md`](../../README.md): the story and the agenda.
- [`agent/bank_agent/instructions.md`](../../agent/bank_agent/instructions.md): what the assistant is told. It names no rule, no threshold and no person; `tests/test_agent.py` checks every desk's prompts the same way.

## Checkpoint

`make test` is green and `uv run ask` answers.

## If you are behind

Everything after this needs only `uv sync`. Fill in `.env` as each module asks.
