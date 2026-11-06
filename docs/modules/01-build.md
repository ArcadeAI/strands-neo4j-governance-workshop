# Building an agent with Strands Agents

**9:15 to 9:45.** A model, a prompt and a tool: the agent loop, before anything touches the bank.

You leave with a Strands agent on Amazon Bedrock or Anthropic, answering from your terminal, calling a local tool you wrote, and an understanding of why that tool needs no governance and the next ones do.

## What you build

1. Put the exercise in place: `make start M=01`. It replaces three files with versions that have `TODO(module 01)` in them, and backs up what was there.
2. **The model** (`agent/loan_agent/models.py`). Fill in the two branches of `make_model`:
   - `BedrockModel(region_name=…, temperature=0.0)`, plus `model_id` only when `MODEL_ID` is set, so Strands' default applies otherwise.
   - `AnthropicModel(client_args={"api_key": …}, model_id=…, max_tokens=4096, params={"temperature": 0})`. Anthropic needs `max_tokens`.
3. **The agent** (`agent/loan_agent/agent.py`). Build the `Agent` in `build_agent`: the model, the tools, the instructions as `system_prompt`, the transcript hook, and `callback_handler=None`, because the CLI prints its own output.
4. **A local tool** (`agent/loan_agent/local_tools.py`). Decorate `loan_payment` with `@tool` and give it a docstring with an `Args:` section. Strands builds the tool's schema from the type hints and the docstring, and the docstring is all the model knows about it.
5. Check it: `make check M=01`.
6. Give it a model. In `.env`, either:

       MODEL_PROVIDER=bedrock
       AWS_REGION=us-east-1        # a region where your account has Bedrock model access

   or `ANTHROPIC_API_KEY=…`. Then:

       uv run ask "What's the monthly payment on 95k over 7 years at 8%?"

   The transcript shows `> loan_payment {...}` and the answer uses its result.
7. Ask it to approve a loan. It cannot: it has no tool that reaches the loan book, and says so.

## What to look at

- `agent/loan_agent/agent.py`: the whole agent is one `Agent(...)`. Nothing in it lists a loan desk tool; module 02 adds them from Arcade at run time.
- `agent/loan_agent/scripted.py`: a Strands `Model` that streams the same events a real one does, from a script. The tests drive every governed scenario through it.
- `agent/loan_agent/transcript.py`: a Strands hook on `AfterToolCallEvent`. Hooks are how you watch an agent; they are not where its limits go (see [`docs/faq.md`](../faq.md#why-not-put-the-limits-in-a-strands-hook)).

## Checkpoint

`make check M=01` passes, and `uv run ask` answers a payment question with a real model, or with the scripted one if you have none.

## If you are behind

`make solve M=01`. Nothing later depends on how you wrote it.
