# The loan desk graph

[`loan_graph/seed.json`](./loan_graph/seed.json) is the one source of truth: four officers, seven people, nine companies, their ownership, nine loan applications with guarantors and decisions. Three ways to load it:

```
uv run seed                 # into NEO4J_URI; MERGE, so safe to run twice
uv run seed --reset         # delete the workshop's nodes first: puts the book back after a run
```

or paste [`seed.cypher`](./seed.cypher) into Neo4j Browser or the Aura query editor. `seed.cypher` is generated (`make seed-cypher`), and a test fails if it drifts from `seed.json`.

`uv run officers list`, `uv run officers set-clearance <email> <amount>` and `uv run officers set-role <email> <role>` change who may do what, live: the control plane reads the officers from the graph on every call.

For a local database, `make neo4j-up` starts Neo4j 5.26 Community in Docker with `NEO4J_PASSWORD` from `.env` (Browser on http://localhost:7474, Bolt on 7687).

The loans are the same as in Arcade's original loan desk workshop, plus LN-2297: Lakeside Bakehouse, $32K, owned by the same person as Northwind Bakery and Two Rivers Brewing. LN-2291's underwriter notes end in a pasted instruction aimed at the model, which the control plane strips. Every email uses the reserved `.example` domain; every account number and tax id is synthetic.
