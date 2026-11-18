"""Money and score helpers. Floats are rejected so binary rounding cannot sneak in."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MONEY = Decimal("0.01")
SCORE = Decimal("0.0001")
MONEY_MAX = Decimal("99999999.99")


def parse_money(value: object, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("invalid_amount")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise ValueError("invalid_amount") from exc
    if amount.is_nan() or amount.is_infinite():
        raise ValueError("invalid_amount")
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("invalid_amount")
    quantized = amount.quantize(MONEY, rounding=ROUND_HALF_UP)
    if quantized > MONEY_MAX:
        raise ValueError("invalid_amount")
    if quantized < 0 or (quantized == 0 and not allow_zero):
        raise ValueError("invalid_amount")
    return quantized


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(SCORE, rounding=ROUND_HALF_UP)
