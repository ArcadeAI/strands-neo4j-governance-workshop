"""The one server, and the one toolkit.

`MCPApp(name="bank")` is what `arcade deploy` reads off `initialize` and files the deployment
as, and `bank` PascalCased, `Bank`, is the toolkit name Arcade prefixes every tool with:
`Bank.ReleasePayment`, `Bank.TraceFunds`. The policies in `gate/policies/` name the same
toolkit, so a rule keyed on `ReleasePayment` matches the call Arcade makes.
"""

from __future__ import annotations

from arcade_mcp_server import MCPApp

app = MCPApp(
    name="bank",
    version="1.0.0",
    instructions=(
        "Larkspur Bank's desks over one Neo4j graph of customers, accounts, transfers, cases and deals. "
        "Payments: list_payment_exceptions, get_payment, screen_party, release_payment, hold_payment. "
        "AML: get_case, trace_funds, trace_ownership, freeze_account, file_sar. "
        "Corporate banking: search_companies, get_company_profile, list_deals, get_deal. "
        "request_approval asks the one person it routes to for an approval, list_approvals shows the requests "
        "a caller made or was asked to decide, and decide records that person's answer."
    ),
)

__all__ = ["app"]
