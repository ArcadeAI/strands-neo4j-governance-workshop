# The AML case team

**10:40 to 11:35.** Several agents on one case, a person who consents before anything drastic, and three controls a prompt cannot hold: no tipping off, four eyes on what hurts a customer, and no approver with a stake in the subject.

You leave with a Strands Swarm of investigators inside a Graph with a lead, an interrupt before every freeze, SAR or outbound message, and the control plane refusing an email to the subject's relationship manager and routing a freeze past a conflicted BSA officer.

## The desk

```
┌──────────── investigation (Swarm) ────────────┐
│ funds_tracer ─handoff─▶ ownership_tracer ─handoff─▶ screener │ ──▶ lead
└───────────────────────────────────────────────┘
```

`agent/bank_agent/desks/aml.py`. The three investigators hand the case along with Strands' `handoff_to_agent`, each with read-only tools: the funds tracer follows `PAID` edges out of the subject's account, the ownership tracer walks `OWNS` and `DIRECTOR_OF`, the screener checks every name against the list and the PEP register. The Swarm is one node of a Graph; the lead runs on what it found and holds the tools that act: `Bank_FreezeAccount`, `Bank_FileSar`, `Bank_RequestApproval`, and `arcade_select_tools` to find Gmail or Slack at run time.

The lead carries a Strands interrupt hook (`agent/bank_agent/confirm.py`): before a freeze, a SAR or any outbound message, the run stops and asks the investigator. That is Ava's consent. The bank's authority is separate, in the control plane, and holds whatever Ava answers.

CASE-7001, planted in the graph: Victor Hale, a former deputy mayor (a PEP), moves $24,000 round three retail accounts opened this year and back to himself within five days; the same accounts then pay Lumen Supply Co, which Hale owns through Greyline Ventures, just under $10,000 each. Rita Patel manages the relationship with Harborview Holdings, which Greyline controls. Marco Silva, the deputy BSA officer, sits on Greyline's board.

## The exercise (about 20 minutes)

`make start M=03` puts two TODOs in place:

- **The team** (`agent/bank_agent/desks/aml.py`). `build_team`: a `Swarm` of the three investigators that starts with the funds tracer, bounded by `max_handoffs`, `max_iterations`, `execution_timeout` and `node_timeout`. `build_graph`: the Swarm is the node `investigation`, the lead is `lead`, one edge between them, and the investigation is the entry point. A Swarm is a valid Graph node because both are Strands `MultiAgentBase`.
- **The case-team controls** (`gate/policies/03-aml.json`). Three pre rules:
  - `pre.no-tipping-off` on `Gmail.SendEmail` and `Slack.SendDmToUser`: `recipient_near_case_subject: 2`, refused when the recipient is within two hops of the subject of an open case. It is checked on the recipient, so it holds whoever sends and through whichever app.
  - `pre.decide-not-the-case-owner` on `Decide`, for `freeze_account` and `file_sar`: `caller_owns_case: true`.
  - `pre.decide-without-a-link-to-the-subject` on the same: `caller_linked_to_subject: 3`, refused when the approver has a path to the subject within three hops. The graph is the conflict-of-interest register.

  Four eyes itself (`pre.freeze-needs-four-eyes`, `pre.sar-needs-four-eyes`) and PII masking (`post.mask-pii`) are already in the file: read them.

`make check M=03` runs `tests/test_aml_desk.py`. Restart the gate after editing a policy file.

## Run it (about 25 minutes)

1. **Investigate and freeze.**

       uv run ask --desk aml "Investigate CASE-7001 and freeze ACC-HALE."

   Watch the handoffs: the funds tracer finds the cycle `ACC-HALE > ACC-REED > ACC-MENDEZ > ACC-PARK > ACC-HALE`, the ownership tracer finds Greyline, Harborview and Lumen, the screener finds Hale is a PEP. The lead asks you before the freeze (answer `y`), and the control plane refuses it: "freezing ACC-HALE needs a second person's sign-off." The lead files the request. It goes to Dana, not Marco: routing skips anyone the graph links to Hale.

       uv run approve --as marco@bank.example APR-… approve     # refused: 3 hops from Victor Hale, a conflict of interest
       uv run approve --as dana@bank.example APR-… approve --note "Cycle and PEP status confirmed."

   Ask again and the freeze goes through, once.
2. **Masked before any model reads it.** The case file `Bank_GetCase` returns shows Hale's SSN, date of birth and account numbers as `[MASKED]`, for everyone, including the BSA officer. No investigator needs the digits, and a SAR links to the subject in the graph, not to digits a model copied.
3. **Tipping off.** Set `CONNECTED_APPS_USER` in `.env` to the email you sign in to Arcade with, then:

       uv run ask --desk aml "Investigate CASE-7001, then email rita@bank.example to ask about Victor Hale's companies."

   The lead calls `arcade_select_tools`, Tool Recommendation finds Gmail's tools, and they become callable on its next step. The first Gmail call may come back with an authorization link instead of a result: open it, allow it as yourself, and ask again. Then the email is refused before it is sent:

       DENIED: rita@bank.example is 2 hops from Victor Hale, the subject of open case CASE-7001:
       Rita Patel - Harborview Holdings Inc - Victor Hale. Telling them could tip off the subject ...

   31 U.S.C. 5318(g)(2) forbids disclosing a SAR to anyone involved in the transaction; the bank's rule is wider on purpose, and checked before any SAR exists.
4. **What the policy cannot name.** Ask the lead to email `omar@bank.example`, who has no path to Hale, and to ask him to find out from Rita whether Hale knows. The policy lets it through, correctly: Omar is not near the subject. The message has still tipped off the subject. Module 04's evals catch that.

## What to look at

- `gate/bank_gate/directory.py`: `CASE_SUBJECT_NEAR` (matched on an email or a Slack handle) and `LINKED`, over `HOLDS`, `OWNS`, `DIRECTOR_OF`, `MANAGES` and `IS`. An employee who is also a person in the graph (Marco) is joined to that person with an `IS` edge, which is how his board seat reaches the conflict check.
- `mcp/bank_tools/approvals.py`: the same conflict check is applied when routing, so the request never lands with Marco; the pre hook on `Decide` holds even if someone calls it directly.
- `agent/bank_agent/confirm.py`: the interrupt names the tool and its arguments; `uv run ask` asks you on the terminal and resumes the Graph with your answer.
- `tests/support/fake_arcade.py`: in the tests, Gmail and Slack calls go through the pre hook like Bank calls. TODO(arcade): confirm that a project's pre hook is called for Arcade-hosted toolkits such as Gmail and Slack, and with which input names.

## Checkpoint

`make check M=03` passes. With everything connected, the freeze waits for Dana and is refused for Marco, and the email to Rita is refused as tipping off.

## If you are behind

`make solve M=03`. Gmail is optional: `make check M=03` exercises the tipping-off rule on both Gmail and Slack against the fake Arcade.
