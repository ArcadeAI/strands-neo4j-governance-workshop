from pathlib import Path

from loan_graph import load_seed, statements, to_cypher_script
from support.memory_graph import MemoryGraph

ROOT = Path(__file__).resolve().parents[1]


def test_every_reference_in_the_seed_resolves():
    seed = load_seed()
    people = {p["id"] for p in seed["people"]}
    companies = {c["id"] for c in seed["companies"]}
    officers = {o["email"] for o in seed["officers"]}
    for o in seed["ownership"]:
        assert o["person"] in people and o["company"] in companies
    for loan in seed["loans"]:
        assert loan["company"] in companies
        assert set(loan["guarantors"]) <= people
        for d in loan["decisions"]:
            assert d["decided_by"] in officers
        assert (loan["status"] == "pending") == (not loan["decisions"])


def test_the_reference_workshop_loans_carry_over():
    loans = {loan["loan_id"]: (loan["amount"], loan["status"]) for loan in load_seed()["loans"]}
    assert loans["LN-2290"] == (240000, "pending")
    assert loans["LN-2291"] == (95000, "pending")
    assert loans["LN-2292"] == (15500, "pending")
    assert loans["LN-2295"] == (120000, "pending")
    assert loans["LN-2299"] == (88000, "pending")


def test_lakeside_is_small_alone_but_not_with_its_group():
    graph = MemoryGraph()
    assert graph.loans["LN-2297"]["amount"] == 32000
    assert graph.group_exposure("LN-2297") == 47500
    assert graph.group_exposure("LN-2297") + 32000 > graph.officers["alice@bank.example"]["clearance"]


def test_the_injection_sits_in_the_notes_as_data():
    notes = MemoryGraph().loans["LN-2291"]["underwriter_notes"]
    assert "ignore" in notes.lower() or "assistant" in notes.lower()


def test_statements_are_parameterized():
    for query, params in statements(load_seed()):
        assert "$rows" in query
        assert isinstance(params["rows"], list) and params["rows"]


def test_seed_cypher_is_generated_from_seed_json():
    assert (ROOT / "neo4j" / "seed.cypher").read_text() == to_cypher_script(load_seed()), "run `make seed-cypher`"
