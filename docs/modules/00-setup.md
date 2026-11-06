# Welcome and setup

**9:00 to 9:15.** The agenda, the cast, and a laptop that can run the rest.

You leave with the repository installed and its tests green, a Neo4j database you can reach, an Arcade project with a key, and a model, or the decision to start on the scripted one.

## Before the workshop

- **Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)**.
- **An [Arcade](https://api.arcade.dev/dashboard) account.** Use the default project it makes, and create an API key in it ([Get an API key](https://docs.arcade.dev/en/get-started/setup/api-keys)). Install the CLI and log in to the same project:

      uv tool install arcade-mcp
      arcade login

- **A Neo4j database.** [Aura Free](https://console.neo4j.io) is the easy path: create a free instance and keep the connection URI (`neo4j+s://…`), the username and the generated password it shows once. The deployed Loan Desk tools run in Arcade's cloud, and Aura is reachable from there. Docker works too (`make neo4j-up`), with a tunnel in module 02.
- **A model.** Amazon Bedrock with access to an Anthropic Claude model in your region, with AWS credentials on the laptop (`aws sts get-caller-identity` works), or an Anthropic API key. Neither is needed to start.
- **An [ngrok](https://ngrok.com) account**, for module 03.

## What you build

1. Install and run the tests:

       git clone <this repository> strands-loan-desk && cd strands-loan-desk
       uv sync
       make test

   Every test passes with no credentials: the model, Arcade and Neo4j are all faked (`tests/support/`).
2. Copy the environment file: `cp .env.example .env`. Fill in only what you have; each module says which block it needs.
3. Ask the agent something:

       uv run ask "Which loans are pending?"

   It answers from the scripted model, and says the loan desk is not connected yet. That is the point to start from.

## The cast

The loan book's officers live in the graph, with a role and an approval authority (clearance):

| Officer | Role | Clearance |
|---|---|---|
| `alice@bank.example` | loan officer | $50,000 |
| `bob@bank.example` | credit analyst | none |
| `charlie@bank.example` | VP credit | $250,000 |
| `michael@bank.example` | chief credit officer | $5,000,000 |

You play all of them with `--as`. Alice is the default (`LOAN_DESK_USER`).

## What to look at

- [`README.md`](../../README.md): the story and the agenda.
- [`agent/loan_agent/instructions.md`](../../agent/loan_agent/instructions.md): what the agent is told. It names no limit and no amount; `tests/test_agent.py` keeps it that way.

## Checkpoint

`make test` is green and `uv run ask` answers.

## If you are behind

Everything after this needs only `uv sync`. Fill in `.env` as each module asks.
