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
    # TODO(module 01): convert through USD_PER. Accept lower-case codes, raise ValueError naming any
    # code with no reference rate, and return {"amount", "from", "to", "rate", "converted"}, with the
    # converted amount rounded to cents.
    raise NotImplementedError("fx_convert")
