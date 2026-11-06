# The control plane

Arcade's Contextual Access hooks for the loan desk: one small FastAPI service (`uv run gate`, port 8742) and one policy file. Arcade calls it on every tool listing and every tool call in your project. Nothing is hosted for you; it runs on your laptop behind a tunnel.

```
uv run gate                     # GATE_TOKEN and NEO4J_* from .env
uv run gate --port 9000 --policy my-policy.json
```

| Endpoint | Auth | Answers |
|---|---|---|
| `POST /hooks/access` | Bearer `GATE_TOKEN` | `{}` or `{"deny": {"LoanDesk": {"tools": {"ApproveLoan": [...]}}}}` |
| `POST /hooks/pre` | Bearer | `{"code": "OK"}` or `{"code": "CHECK_FAILED", "error_message": "..."}` |
| `POST /hooks/post` | Bearer | `{"code": "OK"}`, with `"override": {"output": ...}` when a rule changed the output |
| `GET /hooks/health` | none | `{"status": "healthy"}` when the graph answers |
| `GET /audit` | Bearer | the most recent audit rows |

The request and response shapes follow Arcade's [Contextual Access webhook reference](https://docs.arcade.dev/en/references/contextual-access-webhook-api). Every handler fails closed: a caller the graph does not know gets nothing from the loan desk, and an error in a pre or post hook refuses the call. Calls to other toolkits pass through, with an audit line.

## The policy

[`policy.json`](./policy.json) lists rules. Each has an `id`, a `hook` (`access`, `pre` or `post`), the `tools` it covers (PascalCase names as Arcade sends them, or `["*"]`), and a `when` made of conditions that must all hold:

| Condition | Value | Holds when |
|---|---|---|
| `role_in` | list of roles | the caller's role (from the graph) is in the list |
| `input_exceeds_clearance` | input name | that input (a dollar amount) is above the caller's clearance |
| `group_exposure_exceeds_clearance` | input name | the borrower's ownership group's approved loans, plus that input, are above the caller's clearance |
| `clearance_below` | number | the caller's clearance is below it |
| `caller_is_requester` | true/false | the caller made the approval request named by `request_id` |
| `request_exceeds_clearance` | true/false | that request's amount is above the caller's clearance |
| `request_not_pending` | true/false | that request is missing or already decided |

- **access** rules hide their tools from callers they match.
- **pre** rules run in file order; the first match refuses with its `reason`, a template that can use `{{loan_id}}`, `{{amount}}`, `{{clearance}}`, `{{exposure}}`, `{{routed_to}}` and `{{request_amount}}`. A rule with `"escalate": "approve_loan"` lets the call through if the caller holds an approved, unused request for exactly this action, loan and amount, decided by someone else. That approval is then spent.
- **post** rules `redact` fields (replaced by `replacement`) or `neutralize` free-text fields (instructions aimed at a model are removed).

The vocabulary is closed. An unknown tool, an unknown condition, a post rule that changes nothing or a denying rule with no reason is refused at load, because a rule that silently matches nothing reads like a rule that permits. Restart the gate after editing.

Who someone is lives in the graph, not here: `uv run officers set-clearance alice@bank.example 250000` changes what this policy allows on the next call.

## Registering it with Arcade

`uv run gate` prints the four URLs to register under your tunnel's address (`GATE_PUBLIC_URL`). In the Arcade dashboard, under Contextual Access, create a webhook extension with those endpoints and Bearer auth set to `GATE_TOKEN`, then enable its access, pre and post hooks, failing closed.
