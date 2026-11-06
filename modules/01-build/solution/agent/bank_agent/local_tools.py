"""Tools that run inside the agent's own process.

A local tool touches nothing but its arguments, so there is nothing to govern: no credential,
no record, no person on the other end. The moment a tool reads a payment or a case, or sends a
message as someone, it belongs behind Arcade instead (module 02).
"""

from __future__ import annotations

from strands import tool

# Synthetic reference rates, US dollars per unit. A workshop prop, not market data.
USD_PER = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "MXN": 0.055, "JPY": 0.0067}


@tool
def fx_convert(amount: float, from_currency: str, to_currency: str = "USD") -> dict:
    """Convert an amount between currencies at the bank's synthetic reference rates.

    Args:
        amount: The amount to convert.
        from_currency: ISO code of the amount's currency, for example EUR.
        to_currency: ISO code to convert to; US dollars when left out.
    """
    source, target = from_currency.strip().upper(), to_currency.strip().upper()
    unknown = [c for c in (source, target) if c not in USD_PER]
    if unknown:
        raise ValueError(f"No reference rate for {', '.join(unknown)}; known: {', '.join(sorted(USD_PER))}")
    rate = USD_PER[source] / USD_PER[target]
    return {"amount": amount, "from": source, "to": target, "rate": round(rate, 6), "converted": round(amount * rate, 2)}
