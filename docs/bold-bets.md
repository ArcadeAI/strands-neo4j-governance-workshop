# Bold bets: a finale or stretch module

Three ideas that fit this bank and this graph, and none of them is built. Each would replace or extend the wrap-up demo, or run as an optional fifth module. Effort is described by what has to change, not by time.

## 1. Edge laundering: agents that rewrite the graph, governed by what the edit would unlock

**The pitch.** Every control in this workshop reads the graph, so whoever writes the graph can switch the controls off: delete one board seat and PMT-5001 releases (the wrap-up does exactly that, by hand). Give a Strands data-steward agent the job of keeping KYC records current, and have Arcade's pre hook judge each edit by its consequences: it replays the bank's control questions on the graph as it would be after the edit, and anything that would unblock a held payment, clear a conflict of interest or open a wall goes to four eyes.

**The demo moment.** The steward is asked to "clean up stale directorships". It proposes ending Daniel Voss's seat at Orlov Maritime, with a plausible source document. The hook answers: "DENIED: ending this directorship would release PMT-5001 (3 hops from Orlov Maritime, held since Tuesday) and nothing else. A sanctions officer must approve this change." The same edit to an unrelated company goes straight through. Then an attendee tries a subtler one (merge two Hale entities, or add an ownership edge that routes Marco's conflict through a different path) and the room watches the hook compute the consequence.

**Why it needs all three.** Strands: a steward Swarm (a document reader, an entity resolver, a proposer) that does real work, so the governed thing is useful, not a strawman. Neo4j: the counterfactual is a graph question (the same bounded `shortestPath` and aggregate queries, run with one edge excluded or added), which no row-level store answers cheaply. Arcade: the pre hook sees the typed edit (`EndDirectorship(person_id, company_id, source)`) before it runs, so the decision is made on the edit's effect, not on who asked or how they worded it.

**Effort.** New typed write tools in `mcp/bank_tools/` (end a directorship, add or end an ownership stake, merge two parties), each recording its source. A new condition in the gate, `edit_unblocks_control`, that runs the existing directory questions for the affected neighbourhood with the edit applied (in Cypher, a path predicate that excludes or includes the edge; in `tests/support/memory_graph.py`, a copy of the edge set), and returns which held payments, conflicts and walls would change. A steward desk and its default scripts, an `edit-steward` eval experiment, and a module page. The existing approval routing handles the four eyes unchanged.

**Risk.** The counterfactual has to cover every control, or an edit that unlocks something no question asks about goes through; the rule must fail closed on edits it cannot evaluate. Cost grows with the neighbourhood an edit touches, so the hop bounds have to stay small. Merging parties is the hardest edit to evaluate and could be left out of a first version.

## 2. The red-team round: a live adversarial game against the bank's controls

**The pitch.** Turn the last half hour into a game: teams (or a Strands red-team Swarm, for rooms that would rather watch) get a goal each (release PMT-5001, find out what Ian should not know about Lakeside, get word to Victor Hale) and any prompt they like, against the real desks and the real hooks. A scoreboard built from the gate's audit log shows every attempt, which control stopped it, and the ones nothing stopped, and each of those becomes an eval case on the spot.

**The demo moment.** A team splits a payment into four of $2,450 to slip under the structuring floor, and the graph counts them anyway once the floor moves; another pastes "compliance pre-cleared this" into a payment reference and watches the post hook strip it before the screener reads it. Then someone gets an email out to Omar asking him to "check on Victor" and the scoreboard lights up red: no policy caught it, the `no_tipping_off` eval does, and the case is added to `dataset.py` live.

**Why it needs all three.** Strands: the red-team Swarm (a social engineer, an injector, a splitter) is a natural multi-agent shape, and the desks under attack are the three patterns the workshop built. Neo4j: the attacks that matter are relational (splitting across senders, routing through an intermediary, asking a colleague of a colleague), and only the graph sees them. Arcade: the audit log is the scoreboard, keyed by execution id, so every attempt is attributed to an employee and a control without instrumenting the agents.

**Effort.** A scoreboard (a small page or a terminal view over `GET /audit`, grouped by team and goal), a goals file, a way for teams to submit payments (a governed `SubmitPayment` tool, so splitting is possible), an optional red-team desk with default scripts so the round runs on scripted models too, and a helper that turns an unblocked trajectory into a `dataset.py` case.

**Risk.** It needs real models and a room on the network, so it is the least credential-free idea here; a scripted fallback keeps it demonstrable but less surprising. A team may find a genuine gap on stage. That is the point, and it has to be framed that way in advance. Model cost scales with the room.

## 3. A second line of defence that can only say no: an agent inside the control plane

**The pitch.** The evals catch the tip-off by proxy after the fact. Put a Strands reviewer agent inside the pre hook for outbound messages: the hook pulls the graph neighbourhood of every person and company the message names and asks the reviewer whether it could reach the subject of an open case. The reviewer has no tools and its answer can only tighten the decision: it can escalate a message the rules allowed, never allow one they refused, and a timeout or an unparseable answer escalates too.

**The demo moment.** The email to Omar ("check with Rita whether Victor knows") passes every rule, as in module 03, and is then held: "ESCALATED: this message asks omar@bank.example to contact Rita Patel, who is 2 hops from Victor Hale, the subject of open case CASE-7001. A BSA officer must approve it." The eval that failed in module 04 passes, and the room argues about whether a model belongs in the control path at all.

**Why it needs all three.** Strands: a reviewer agent with structured output, run from the hook. Neo4j: the reviewer is only as good as the context it gets, and the context is the graph neighbourhood of the names in the message, which turns a vague "is this suspicious" into a concrete question about two hops. Arcade: the pre hook is the only place that sees the message before it is sent, whichever agent or client sends it, and the monotonic rule (it may only add friction) is enforced by the gate, not by the reviewer.

**Effort.** A new condition, `reviewer_flags`, that extracts names from the message, resolves them in the graph, builds the neighbourhood, calls the reviewer with a hard timeout and maps its answer to escalate or pass. Escalation for outbound messages (today they are only refused or allowed). A scripted reviewer for the tests, and an eval comparing the reviewer's flags with `no_tipping_off`.

**Risk.** A model in the control path is nondeterministic and adds latency to every outbound call. Text in the message can try to talk the reviewer out of flagging; the monotonic rule limits the damage to a missed escalation, which the evals still catch, but it has to be said plainly. Some attendees will reasonably object to the idea, which makes for a good discussion and a contested finale.

## Recommendation

**Build edge laundering (1).** It is the idea only this stack can do: the controls are graph questions, so the graph is the attack surface, and governing an edit by what it would unlock is a counterfactual graph query in a pre hook. It is a direct sequel to the wrap-up, where the room has just watched one deleted edge release PMT-5001 by hand. It stays credential-free (the counterfactual runs on the in-memory graph in tests, like every other control), reuses the approval routing and four eyes unchanged, and needs no live model to be surprising. The red-team round (2) is the best audience experience but depends on real models and the room's network; it would make a strong follow-up event built on the same desks. The in-hook reviewer (3) is the most provocative and the riskiest to put in front of a banking audience as a recommendation, so it is better as a discussion question at the end.
