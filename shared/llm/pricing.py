from __future__ import annotations

from decimal import Decimal

_USD_PER_1M_TOKENS: dict[str, dict[str, Decimal]] = {
    "claude-opus-4-7": {"input": Decimal("15"), "output": Decimal("75")},
    "claude-sonnet-4-6": {"input": Decimal("3"), "output": Decimal("15")},
    "claude-haiku-4-5": {"input": Decimal("1"), "output": Decimal("5")},
}

_FALLBACK = {"input": Decimal("3"), "output": Decimal("15")}


def cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    rates = _USD_PER_1M_TOKENS.get(model, _FALLBACK)
    million = Decimal("1000000")
    return (
        rates["input"] * Decimal(input_tokens) / million
        + rates["output"] * Decimal(output_tokens) / million
    ).quantize(Decimal("0.000001"))
