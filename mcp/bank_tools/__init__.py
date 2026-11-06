"""The Bank MCP server: one toolkit, `Bank`, over Bowser Capital's Neo4j graph.

Importing the package registers every tool on `app`, so `server.py` has them all before
`app.run()`.
"""

from bank_tools import aml, approvals, banker, payments
from bank_tools.app import app

__all__ = ["aml", "app", "approvals", "banker", "payments"]
