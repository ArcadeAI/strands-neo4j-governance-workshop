.PHONY: help setup test check verify-modules start solve status staff neo4j-up neo4j-down seed seed-cypher gate deploy-mcp

M ?=
CHECK_01 := tests/test_agent.py
CHECK_02 := tests/test_payments_desk.py
CHECK_03 := tests/test_aml_desk.py
CHECK_04 := tests/test_banker_desk.py tests/test_evals.py

help:
	@echo "make setup            install everything (uv sync)"
	@echo "make test             the whole credential-free test suite"
	@echo "make check M=02       the tests for one module"
	@echo "make start M=02       put a module's TODOs in place;  make solve M=02  its solution"
	@echo "make verify-modules   every starter fails its check and every solution passes it"
	@echo "make staff            who works at Bowser Capital, and what each person may do"
	@echo "make neo4j-up         a local Neo4j in Docker (or use Aura Free: docs/modules/00-setup.md)"
	@echo "make seed             load the Bowser Capital graph into NEO4J_URI, replacing what is there"
	@echo "make gate             run the control plane on :8742"
	@echo "make deploy-mcp       deploy the Bank MCP server to Arcade"

setup:
	uv sync

test:
	uv run pytest -q

check:
	@test -n "$(CHECK_$(M))" || (echo "usage: make check M=01|02|03|04" && exit 2)
	uv run pytest -q $(CHECK_$(M))

start:
	uv run python scripts/workshop.py start $(M)

solve:
	uv run python scripts/workshop.py solve $(M)

status:
	uv run python scripts/workshop.py status

verify-modules:
	uv run python scripts/verify_modules.py

staff:
	uv run staff

neo4j-up:
	docker compose up -d neo4j
	@echo "Neo4j Browser: http://localhost:7474  (bolt://localhost:7687)"

neo4j-down:
	docker compose down

seed:
	uv run seed --reset

seed-cypher:
	uv run seed --print > neo4j/seed.cypher

gate:
	uv run gate

deploy-mcp:
	cd mcp && arcade deploy -e server.py
