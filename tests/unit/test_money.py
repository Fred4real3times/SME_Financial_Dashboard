from decimal import Decimal

import pytest

from sme_financial_dashboard.domain.money import (
    Direction,
    MoneyValidationError,
    calculate_cashflow,
    parse_amount,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("100", Decimal("100")),
        ("12.340000", Decimal("12.340000")),
        (7, Decimal("7")),
    ],
)
def test_parse_amount_exact_values(value, expected):
    assert parse_amount(value) == expected


@pytest.mark.parametrize(
    "value",
    [0, "0", -1, "-3.20", "NaN", "Infinity", "1.0000001", 0.1, True],
)
def test_parse_amount_rejects_invalid_or_unsafe_values(value):
    with pytest.raises(MoneyValidationError):
        parse_amount(value)


def test_cashflow_is_partitioned_by_currency():
    totals = calculate_cashflow(
        [
            (Decimal("100"), Direction.INFLOW, "XAF"),
            (Decimal("25"), Direction.OUTFLOW, "XAF"),
            (Decimal("50"), Direction.INFLOW, "EUR"),
        ]
    )
    assert totals["XAF"].inflows == Decimal("100")
    assert totals["XAF"].outflows == Decimal("25")
    assert totals["XAF"].net == Decimal("75")
    assert totals["EUR"].net == Decimal("50")
    assert set(totals) == {"EUR", "XAF"}


def test_cashflow_rejects_invalid_currency_or_direction():
    with pytest.raises(MoneyValidationError):
        calculate_cashflow([(Decimal("1"), "TRANSFER", "XAF")])
    with pytest.raises(MoneyValidationError):
        calculate_cashflow([(Decimal("1"), Direction.INFLOW, "X")])
