"""The one server, and the one toolkit.

`MCPApp(name="loan_desk")` is what `arcade deploy` reads off `initialize` and files the
deployment as, and `loan_desk` PascalCased, `LoanDesk`, is the toolkit name Arcade prefixes
every tool with: `LoanDesk.SearchLoans`, `LoanDesk.ApproveLoan`. The policy in
`gate/policy.json` names the same toolkit, so a rule keyed on `ApproveLoan` matches the call
Arcade makes. The name is underscores only: MCPApp rejects a hyphen.
"""

from __future__ import annotations

from arcade_mcp_server import MCPApp

app = MCPApp(
    name="loan_desk",
    version="1.0.0",
    instructions=(
        "Loan desk for a small-business lender, backed by a Neo4j graph. Loan applications are "
        "identified by IDs of the form LN-0000: search_loans finds applications, get_loan reads one "
        "in full, get_borrower_network walks the graph from a loan to the people who own the borrower "
        "and the other companies and loans they are behind. approve_loan and deny_loan record a "
        "decision. request_approval asks the one officer it routes to for an approval, list_approvals "
        "shows the requests a caller made or was asked to decide, and decide records that officer's answer."
    ),
)

__all__ = ["app"]
