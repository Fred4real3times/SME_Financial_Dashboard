"""Exact cash-flow calculations using Decimal only."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

MAX_SCALE = 6
MAX_AMOUNT = Decimal("99999999999999.999999")
SIX_PLACES = Decimal("0.000001")


class Direction(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class MoneyValidationError(ValueError):
    """Raised when a financial amount cannot be represented by the MVP contract."""


def parse_amount(value: str | int | Decimal) -> Decimal:
    """Parse a positive amount without binary-float conversion or silent rounding."""
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyValidationError(
            "Amount must be provided as text, integer or Decimal; floats are forbidden"
        )
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise MoneyValidationError("Amount is not a valid decimal number") from exc

    if not amount.is_finite():
        raise MoneyValidationError("Amount must be finite")
    if amount <= 0:
        raise MoneyValidationError("Amount must be greater than zero")
    if amount > MAX_AMOUNT:
        raise MoneyValidationError("Amount exceeds NUMERIC(20,6) capacity")
    try:
        if amount != amount.quantize(SIX_PLACES):
            raise MoneyValidationError(f"Amount supports at most {MAX_SCALE} decimal places")
    except InvalidOperation as exc:
        raise MoneyValidationError("Amount exceeds supported decimal precision") from exc
    return amount


@dataclass(frozen=True, slots=True)
class CashflowTotals:
    currency: str
    inflows: Decimal
    outflows: Decimal
    net: Decimal


def calculate_cashflow(
    rows: Iterable[tuple[Decimal, Direction | str, str]],
) -> dict[str, CashflowTotals]:
    """Calculate totals independently per currency; never aggregate across currencies."""
    totals: dict[str, list[Decimal]] = {}
    for raw_amount, raw_direction, raw_currency in rows:
        amount = parse_amount(raw_amount)
        try:
            direction = Direction(raw_direction)
        except ValueError as exc:
            raise MoneyValidationError(
                f"Unsupported transaction direction: {raw_direction}"
            ) from exc
        currency = raw_currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise MoneyValidationError(f"Invalid ISO 4217 alpha-3 currency code: {raw_currency}")
        bucket = totals.setdefault(currency, [Decimal("0"), Decimal("0")])
        bucket[0 if direction is Direction.INFLOW else 1] += amount

    return {
        currency: CashflowTotals(currency, inflows, outflows, inflows - outflows)
        for currency, (inflows, outflows) in sorted(totals.items())
    }
