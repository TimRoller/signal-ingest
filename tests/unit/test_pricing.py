from __future__ import annotations

from decimal import Decimal

from shared.llm.pricing import cost_usd


def test_sonnet_4_6_pricing() -> None:
    # 1M input + 1M output = $3 + $15 = $18.
    assert cost_usd(
        model="claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000
    ) == Decimal("18.000000")


def test_haiku_4_5_pricing() -> None:
    assert cost_usd(
        model="claude-haiku-4-5", input_tokens=1_000_000, output_tokens=1_000_000
    ) == Decimal("6.000000")


def test_small_call_rounded_to_six_decimals() -> None:
    cost = cost_usd(model="claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert cost == Decimal("0.010500")


def test_unknown_model_falls_back_to_sonnet_rates() -> None:
    fallback = cost_usd(model="some-future-model", input_tokens=1000, output_tokens=500)
    sonnet = cost_usd(model="claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
    assert fallback == sonnet
