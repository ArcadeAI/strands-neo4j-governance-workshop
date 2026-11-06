# The loan desk agent

A [Strands Agents](https://strandsagents.com) agent (`loan_agent`) whose every tool that touches the bank runs through Arcade.

```
uv run ask "Which loans are pending?"
uv run ask --as charlie@bank.example "Read LN-2291"
uv run ask --confirm "Post my LN-2291 status to Slack"     # ask before anything leaves the bank
uv run ask --session alice-1 "..."                         # keep the conversation under .sessions/
uv run ask --trace console "..."                           # OpenTelemetry spans to the terminal
uv run approve --as charlie@bank.example                   # the human side: list, then decide
uv run tools --as bob@bank.example                         # what Arcade lists for Bob
uv run evals                                               # the eval suite, against the real thing
```

## Model

`MODEL_PROVIDER` in `.env`:

- `bedrock`: `BedrockModel` with your AWS credentials and `AWS_REGION`. With no `MODEL_ID`, Strands' default Claude model on Bedrock (a cross-region inference profile). TODO(thierry): pick and pin the model id the room uses, and confirm the regions it is available in.
- `anthropic`: `AnthropicModel` with `ANTHROPIC_API_KEY`; `MODEL_ID` defaults to `claude-sonnet-5-5`.
- `scripted`, or nothing set and no Anthropic key: a scripted Strands `Model` that needs no key. With the loan desk connected it lists the pending loans; without, it says what to set.

## Tools

- `loan_payment`: a local `@tool`. It touches nothing but its arguments, so there is nothing to govern.
- The `LoanDesk` toolkit, listed by Arcade for the officer at the start of each run, after the access hook (`arcade_tools.ArcadeToolbox.pinned`).
- `arcade_select_tools`: Arcade's Tool Recommendation. What it finds is registered on the running agent and offered to the model on its next step.

Calls go through `tools.execute` with the project key. Loan desk calls carry the officer's email as `user_id`; other toolkits carry `CONNECTED_APPS_USER` when set. A refusal is the tool's result, in the control plane's words.

## Layout

| File | |
|---|---|
| `agent.py` | `build_agent`: model, tools, instructions, hooks |
| `instructions.md` | the system prompt; names no limit |
| `arcade_tools.py` | the Arcade engine adapter and toolbox |
| `models.py`, `scripted.py` | model choice, and the scripted model |
| `transcript.py`, `confirm.py`, `telemetry.py` | hooks for the transcript and consent, OpenTelemetry |
| `cli.py` | `ask`, `approve`, `tools` |
| `evals/` | dataset, checks, runner (Strands Evals) |
| `agentcore_app.py` | optional: the agent behind a Bedrock AgentCore Runtime entrypoint (`uv sync --extra prod`) |
