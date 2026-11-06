# Building an agent with Strands Agents

**9:15 to 9:35.** A model, a prompt and a tool: the Strands agent loop, before anything touches the bank.

You leave with a Strands agent on Amazon Bedrock or Anthropic, answering from your terminal and calling a local tool you finished, and the reason that tool needs no governance while every tool after it does.

## What you build

1. Put the exercise in place: `make start M=01`. It replaces two files with versions that have `TODO(module 01)` in them, and backs up what was there.
2. **A local tool** (`agent/bank_agent/local_tools.py`). `fx_convert` is already a `@tool` with a docstring; Strands builds the tool's schema from the type hints and the `Args:` section, and the docstring is all the model knows about it. Write its body: convert through the synthetic `USD_PER` rates, accept lower-case codes, and raise a `ValueError` that names an unknown code. A tool that raises comes back to the model as an error result, which it can read and recover from.
3. **The agent's tools** (`agent/bank_agent/agent.py`). In `build_agent`, give the agent `fx_convert` and, when the Arcade toolbox is connected, every tool it lists for this employee. With no `ARCADE_API_KEY` there is no toolbox, and the agent says the bank is not connected.
4. Check it: `make check M=01`.
5. Give it a model. In `.env`, either:

       MODEL_PROVIDER=bedrock
       AWS_REGION=us-east-1        # a region where your account has Bedrock model access

   or `ANTHROPIC_API_KEY=…`. Then:

       uv run ask "A supplier invoice is 2,500 EUR. What is that in dollars?"

   The transcript shows `> fx_convert {...}` and the answer uses its result.
6. Ask it to release a payment. It cannot: it has no tool that reaches the bank, and says so.

## What to look at

- `agent/bank_agent/agent.py`: the whole assistant is one `Agent(...)`. Every desk in modules 02 to 04 is built from the same parts, in `agent/bank_agent/desks/common.py`: a model, the tools Arcade lists for one employee, and the transcript hook.
- `agent/bank_agent/models.py`: `BedrockModel` or `AnthropicModel`, chosen by `MODEL_PROVIDER`, with temperature 0.
- `agent/bank_agent/scripted.py`: a Strands `Model` that streams the same events a real one does, from a script. Every desk has a default script per agent, so the whole workshop runs, and the tests drive every governed scenario, with no key.
- `agent/bank_agent/transcript.py`: a Strands hook on `AfterToolCallEvent`, recording which agent called what. Hooks are how you watch an agent; they are not where the bank's controls go (see [`docs/faq.md`](../faq.md#why-not-put-the-controls-in-a-strands-hook)).

## Checkpoint

`make check M=01` passes, and `uv run ask` answers a currency question with a real model, or with the scripted one if you have none.

## If you are behind

`make solve M=01`. Nothing later depends on how you wrote it.
