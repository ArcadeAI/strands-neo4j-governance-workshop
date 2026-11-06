"""Tools that run inside the agent's own process.

A local tool touches nothing but its arguments, so there is nothing to govern: no credential,
no record, no person on the other end. The moment a tool reads or changes the loan book, or
sends a message as someone, it belongs behind Arcade instead (module 02).
"""

from __future__ import annotations

from strands import tool


@tool
def loan_payment(principal: float, annual_rate_pct: float, years: int) -> dict:
    """Monthly payment, total paid and total interest for a fixed-rate, fully amortizing loan.

    Args:
        principal: The amount borrowed.
        annual_rate_pct: The annual interest rate in percent, for example 7.5.
        years: The term in years.
    """
    if principal <= 0 or years <= 0:
        raise ValueError("principal and years must be positive")
    months = years * 12
    rate = annual_rate_pct / 100 / 12
    payment = principal / months if rate == 0 else principal * rate / (1 - (1 + rate) ** -months)
    return {
        "monthly_payment": round(payment, 2),
        "total_paid": round(payment * months, 2),
        "total_interest": round(payment * months - principal, 2),
    }
