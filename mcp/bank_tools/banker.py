"""The corporate banker's tools: find a company, read its profile, and, over the wall, the deals.

`get_company_profile` returns everything the graph knows about a company, including any deal
it is a party to. Whether the caller may read a deal's details is the information barrier's
question, answered by the control plane: the access hook hides the deal tools from the public
side, and the post hook masks each deal record the caller is not over the wall for, whichever
tool returns it (gate/policies/04-banker.json).
"""

# No `from __future__ import annotations` here: see common.py.

from typing import Annotated, Any

from arcade_core.errors import ToolExecutionError
from arcade_mcp_server import Context

from bank_tools.app import app
from bank_tools.common import READ, actor_of, graph_call
from bank_tools.graph import SECRETS, book_for

__all__ = ["get_company_profile", "get_deal", "list_deals", "search_companies"]


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def search_companies(
    context: Context,
    query: Annotated[str, "Part of a company's name or industry, for example lakeside or bakery."],
) -> Annotated[dict[str, Any], "The matching companies' IDs, names, industries and headquarters."]:
    """Find companies in the bank's graph by part of their name or industry. Each hit carries the company ID that get_company_profile takes."""
    actor_of(context)
    if not query.strip():
        raise ToolExecutionError("Give part of a name or an industry to search for.")
    companies = await book_for(context).search_companies(query)
    return {"count": len(companies), "companies": companies}


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def get_company_profile(
    context: Context,
    company_id: Annotated[str, "The company's ID, in the form C-NAME, for example C-LAKESIDE."],
) -> Annotated[dict[str, Any], "The company's profile, coverage, owners and any deals it is party to."]:
    """Read one company's profile for a client meeting: industry, headquarters, revenue, the public description, who covers it at the bank, who owns it, and every advisory deal it is a party to (codename, its role, the counterparty, stage, valuation and terms)."""
    actor_of(context)
    return await graph_call(book_for(context).company_profile(company_id), "company")


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def list_deals(context: Context) -> Annotated[dict[str, Any], "Every advisory deal the bank is working on."]:
    """List the advisory deals the bank is working on: codename, target, acquirer, stage, valuation and terms."""
    actor_of(context)
    deals = await book_for(context).list_deals()
    return {"count": len(deals), "deals": deals}


@app.tool(requires_secrets=SECRETS, metadata=READ)
async def get_deal(
    context: Context,
    deal_id: Annotated[str, "The deal's ID, in the form DL-NAME, for example DL-FALCON."],
) -> Annotated[dict[str, Any], "The deal's full record, with the insiders on it."]:
    """Read one advisory deal: codename, target, acquirer, stage, valuation, terms, and the bankers who are insiders on it."""
    actor_of(context)
    return await graph_call(book_for(context).get_deal(deal_id), "deal")
