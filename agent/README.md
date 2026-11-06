# The Bowser Capital agents

[Strands Agents](https://strandsagents.com) agents (`bank_agent`) whose every tool that touches the bank, or leaves it, runs through Arcade: a module 01 assistant and three desks.

```
uv run ask "What is 2,500 EUR in dollars?"                           # the assistant
uv run ask --desk payments "Work PMT-5001"                           # a Graph: screen, then release or hold
uv run ask --desk aml "Investigate CASE-7001 and freeze ACC-HALE."    # a Swarm inside a Graph, with an interrupt
uv run ask --desk banker --as mia@bank.example "Brief me on Lakeside Bakehouse."   # agents as tools
uv run ask --trace console --desk payments "Work PMT-5003"           # OpenTelemetry spans to the terminal
uv run approve --as sana@bank.example                                # the human side: list, then decide
uv run tools --as ian@bank.example                                   # what Arcade lists for Ian
uv run evals --experiment aml                                        # the eval suite, against the real thing
```

## Models

`MODEL_PROVIDER` in `.env`:

- `bedrock`: `BedrockModel` with your AWS credentials and `AWS_REGION`. With no `MODEL_ID`, Strands' default Claude model on Bedrock (a cross-region inference profile). TODO(thierry): pick and pin the model id the room uses, and confirm the regions it is available in.
- `anthropic`: `AnthropicModel` with `ANTHROPIC_API_KEY`; `MODEL_ID` defaults to `claude-sonnet-5-5`.
- `scripted`, or nothing set and no Anthropic key: a scripted Strands `Model` that needs no key. Every agent in every desk has a default script, so the whole workshop runs without one.

Every agent in a desk uses the same provider. The desk builders also take `models={"lead": …}` to set one agent's model, which is how the tests script each agent separately.

## Tools

- `fx_convert`: a local `@tool`. It touches nothing but its arguments, so there is nothing to govern.
- The `Bank` toolkit, listed by Arcade for the employee at the start of each run, after the access hook (`ArcadeToolbox.pinned`). Each desk agent picks only the tools its job needs (`ArcadeToolbox.pick`).
- `arcade_select_tools`: Arcade's Tool Recommendation, on the assistant and the AML lead. What it finds is registered on the running agent and offered to the model on its next step.

Calls go through `tools.execute` with the project key. Bank calls carry the employee's email as `user_id`; other toolkits carry `CONNECTED_APPS_USER` when set. A refusal is the tool's result, in the control plane's words.

## Layout

| File | |
|---|---|
| `agent.py` | `build_agent`: the module 01 assistant |
| `instructions.md` | the assistant's system prompt; names no rule |
| `desks/common.py` | building one desk agent; `Desk` and `Reply` |
| `desks/payments.py`, `desks/aml.py`, `desks/banker.py` | the three desks, their prompts and default scripts |
| `arcade_tools.py` | the Arcade engine adapter and toolbox |
| `models.py`, `scripted.py` | model choice, and the scripted model |
| `transcript.py`, `confirm.py`, `telemetry.py` | hooks for the transcript (which agent called what) and consent, OpenTelemetry |
| `local_tools.py` | `fx_convert` |
| `cli.py` | `ask`, `approve`, `tools` |
| `evals/` | dataset, checks, runner (Strands Evals) |
| `agentcore_app.py` | optional: any desk behind a Bedrock AgentCore Runtime entrypoint (`uv sync --extra prod`) |
