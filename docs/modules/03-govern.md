# Governing agent actions with policy hooks and a human in the loop

**10:45 to 11:30.** A refusal the model cannot argue with, a human in the loop, a limit only a graph can see, and data the model never reads.

You leave with the control plane registered with your Arcade project and four things going wrong on your own build, all caught outside the model.

## What you build

1. **Start the control plane.** In `.env`, set `GATE_TOKEN` to the output of `openssl rand -hex 32`. Then, in its own terminal:

       uv run gate

   Leave it where you can see it: every listing, refusal, grant and redaction prints there as it happens, and goes to `.gate/audit.jsonl`.
2. **Expose it.** In another terminal, `ngrok http 8742`. Put the https address in `.env` as `GATE_PUBLIC_URL` and restart the gate; it prints the four URLs to register.
3. **Register it with Arcade.** In the dashboard, open **Contextual Access** and create a webhook extension with those endpoints (access, pre, post, health), Bearer authentication with your `GATE_TOKEN`, scoped to your project. Then turn on its hooks, set to **fail closed**: if the gate cannot be reached, calls are refused, not waved through. The contract is Arcade's [Contextual Access webhook reference](https://docs.arcade.dev/en/references/contextual-access-webhook-api). TODO(thierry): replace this step with screenshots, or with an API call if Arcade exposes one for extensions.
4. **The exercise** (`make start M=03`, in `gate/policy.json`). The starter has the access rule, the clearance rule and the three rules that guard `Decide`. Add:
   - a `pre` rule on `ApproveLoan`: `"when": {"group_exposure_exceeds_clearance": "amount"}`, escalating to `approve_loan`, with a `reason` the agent can act on;
   - a `post` rule on every tool (`"tools": ["*"]`) that redacts `bank_account_number` and `tax_id` when `clearance_below` is 250000;
   - a `post` rule that neutralizes `underwriter_notes`, `justification` and `note`.

   `make check M=03` runs the gate and the whole governed loop. Restart `uv run gate` after any edit.
5. **Run the acts**, as Alice unless it says otherwise:
   - **Refused, and told what to do.** `uv run ask "Approve the Northwind loan for the full $95K and double-check your work."` `LoanDesk_ApproveLoan` comes back with the hook's words and a `[ref …]` that matches the gate's audit line. The agent calls `LoanDesk_RequestApproval`; the request is routed to Charlie, the lowest clearance that covers $95K, never Alice and never Michael. The loan stays pending.
   - **You cannot approve your own request.** `uv run approve --as alice@bank.example APR-… approve` is refused by `pre.decide-not-by-the-requester`.
   - **The human decides.** `uv run approve --as charlie@bank.example` lists what is waiting on him; `uv run approve --as charlie@bank.example APR-… approve --note "Collateral checks out"`. No model is involved, and it is still a governed `LoanDesk_Decide` call.
   - **The retry passes, once.** Ask Alice's agent again. The gate prints `granted` with the request id, and the loan is approved. Ask a third time: refused.
   - **A small loan in a big group.** `uv run ask "Approve LN-2297 for Lakeside Bakehouse, $32,000."` Under her limit, refused anyway: with Two Rivers' $47.5K the group comes to $79.5K.
   - **Bob is never offered the tool.** `uv run ask --as bob@bank.example "Approve LN-2292 for 15500."` The access hook removed `ApproveLoan` from his list; there is nothing to refuse.
   - **What the model never reads.** "Read LN-2291 and quote its bank account number and tax id." `[REDACTED]` for Alice; the real values with `--as charlie@bank.example`. For both, the instruction pasted into its notes is gone.
6. **Optional: tell Charlie, with consent.** `uv run ask --confirm "Post the status of my LN-2291 request to Slack."` The `--confirm` hook (a Strands interrupt) stops before anything leaves the bank and asks you. That is consent. It is not authority: the hooks decide whether a call may run, whoever asked.

## What to look at

- `gate/policy.json`: every rule, keyed on the PascalCase tool name Arcade sends (`ApproveLoan`), with the refusal written for the model in the name it sees (`LoanDesk_RequestApproval`). The vocabulary is closed: an unknown tool or condition is refused at load.
- `gate/loan_gate/hooks.py`: the three hooks, each failing closed. A stranger to the graph gets nothing from the loan desk.
- `gate/loan_gate/directory.py`: who someone is comes from the graph on every call, so `uv run officers set-clearance` changes the answer with no restart. The grant is a `consumed_at` set atomically in Neo4j.
- `mcp/loan_desk/approvals.py`: the routing is deterministic, and a request id is a pointer, not a capability.

## Checkpoint

You have seen a refusal, an escalation routed to Charlie, a refused self-approval, a granted retry and a refused second retry, all in the gate's terminal.

## If you are behind

`make solve M=03`, restart the gate, and run the acts. `uv run seed --reset` puts the loan book back between runs.
