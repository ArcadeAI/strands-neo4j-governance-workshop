# The control plane

Arcade's Contextual Access hooks for Larkspur Bank: one small FastAPI service (`uv run gate`, port 8742) and one policy file per desk. Arcade calls it on every tool listing and every tool call in your project. Nothing is hosted for you; it runs on your laptop behind a tunnel.

```
uv run gate                         # GATE_TOKEN and NEO4J_* from .env
uv run gate --port 9000 --policy my-policies/
```

| Endpoint | Auth | Answers |
|---|---|---|
| `POST /hooks/access` | Bearer `GATE_TOKEN` | `{}` or `{"deny": {"Bank": {"tools": {"ReleasePayment": [...]}}}}` |
| `POST /hooks/pre` | Bearer | `{"code": "OK"}` or `{"code": "CHECK_FAILED", "error_message": "..."}` |
| `POST /hooks/post` | Bearer | `{"code": "OK"}`, with `"override": {"output": ...}` when a rule changed the output |
| `GET /hooks/health` | none | `{"status": "healthy"}` when the graph answers |
| `GET /audit` | Bearer | the most recent audit rows |

The request and response shapes follow Arcade's [Contextual Access webhook reference](https://docs.arcade.dev/en/references/contextual-access-webhook-api). Every handler fails closed: a caller the graph does not know gets nothing from the bank, and an error in a pre or post hook refuses the call. Calls to toolkits no rule names pass through, with an audit line.

## The policy

[`policies/`](./policies) holds one file per desk, loaded in name order: `00-baseline.json` (approvals and prompt-injection stripping), `02-payments.json`, `03-aml.json`, `04-banker.json`. Each file names the toolkit (`Bank`) and lists rules. A rule has an `id`, a `hook` (`access`, `pre` or `post`), the `tools` it covers (Bank tools in PascalCase as Arcade sends them, `Gmail.SendEmail` or `Slack.SendDmToUser` for outbound messages, or `["*"]`), and a `when` made of conditions that must all hold. Most conditions are a question to the graph:

| Condition | Value | Holds when |
|---|---|---|
| `role_in`, `role_not_in` | list of roles | the caller's role (from the graph) is, or is not, in the list |
| `always` | true | always: for a control that only an approval lifts |
| `beneficiary_near_sanctioned` | hops | the payment's beneficiary account is within that many `HOLDS`, `OWNS` or `DIRECTOR_OF` hops of a listed entity |
| `structuring` | `{floor, threshold, window_days, min_count}` | the beneficiary account has received at least `min_count` payments between `floor` and `threshold` in the window before this one |
| `recipient_near_case_subject` | hops | the message's recipient (an email or a Slack handle) is within that many hops of the subject of an open case |
| `request_not_pending` | true | the approval request named by `request_id` is missing or already decided |
| `caller_is_requester` | true | the caller made that request |
| `request_action_in` | list of actions | that request is for one of these actions |
| `caller_owns_case` | true | the caller owns the case the request is about |
| `caller_linked_to_subject` | hops | the caller has a path to that case's subject within that many hops |
| `not_over_wall` | true | the caller is not over the wall for the deal in question (an `INSIDER_ON` edge, or a `WALL_CROSSED` edge that has not expired); with no deal in question, for any deal |

- **access** rules hide their tools from callers they match.
- **pre** rules run in file order; the first match refuses with its `reason`, a template filled from the call's inputs and the graph's answer (`{{payment_id}}`, `{{hops}}`, `{{listed}}`, `{{chain}}`, `{{count}}`, `{{senders}}`, `{{recipient}}`, `{{subject}}`, `{{case_id}}`, `{{deal_id}}`, `{{request_id}}`, …). The reason is what the agent reads, so it says what to call next. A rule with `"escalate": "<action>"` and `"resource": "<input>"` lets the call through if the caller holds an approved, unspent request for exactly this action and resource, decided by someone else. That approval is then spent.
- **post** rules `redact` fields (replaced by `replacement`) or `neutralize` free-text fields (instructions aimed at a model are removed). With `"per_record": "deal_id"`, the rule is checked once for every object in the output that carries a `deal_id`, so one answer can mask one deal and show another.

The vocabulary is closed. An unknown tool, an unknown condition, a post rule that changes nothing, a denying rule with no reason, or a rule on an outbound tool outside the pre hook is refused at load, because a rule that silently matches nothing reads like a rule that permits. Restart the gate after editing.

Who someone is lives in the graph, not here: `uv run staff set-role <email> <role>` changes what this policy allows on the next call, and so does any edit to ownership, board seats, coverage or cases.

## Registering it with Arcade

`uv run gate` prints the URLs to register under your tunnel's address (`GATE_PUBLIC_URL`). In the Arcade dashboard, under Contextual Access, create a webhook extension with those endpoints and Bearer auth set to `GATE_TOKEN`, then enable its access, pre and post hooks, failing closed.
