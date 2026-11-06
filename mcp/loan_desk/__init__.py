"""The Loan Desk MCP server: one toolkit, `LoanDesk`, over a Neo4j loan graph.

Importing the package registers every tool on `app`, so `server.py` has them all before
`app.run()`.
"""

from loan_desk import approvals, loans
from loan_desk.app import app

__all__ = ["app", "approvals", "loans"]
