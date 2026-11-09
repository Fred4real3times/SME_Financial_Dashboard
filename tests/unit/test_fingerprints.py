from datetime import date
from decimal import Decimal
from uuid import uuid4

from sme_financial_dashboard.domain.fingerprints import transaction_fingerprint


def _fingerprint(amount: Decimal, *, counterparty: str = "  Client   A "):
    return transaction_fingerprint(
        company_id=uuid4(),
        transaction_date=date(2026, 1, 1),
        amount=amount,
        currency="XAF",
        direction="INFLOW",
        reference="REF-1",
        counterparty=counterparty,
    )


def test_decimal_scale_does_not_change_transaction_fingerprint():
    company_id = uuid4()

    def calculate(amount: Decimal):
        return transaction_fingerprint(
            company_id=company_id,
            transaction_date=date(2026, 1, 1),
            amount=amount,
            currency="XAF",
            direction="INFLOW",
            reference="REF-1",
            counterparty="Client A",
        )

    assert calculate(Decimal("100")) == calculate(Decimal("100.0"))
    assert calculate(Decimal("100.00")) == calculate(Decimal("100.000000"))


def test_text_fingerprint_normalizes_unicode_whitespace_and_case():
    company_id = uuid4()
    common = {
        "company_id": company_id,
        "transaction_date": date(2026, 1, 1),
        "amount": Decimal("100.00"),
        "currency": "XAF",
        "direction": "INFLOW",
        "reference": "  REF-1 ",
    }
    one = transaction_fingerprint(**common, counterparty="Client A")
    two = transaction_fingerprint(**common, counterparty="  CLIENT   A ")
    assert one == two


def test_fingerprint_is_company_scoped():
    shared = {
        "transaction_date": date(2026, 1, 1),
        "amount": Decimal("100"),
        "currency": "XAF",
        "direction": "INFLOW",
        "reference": "REF-1",
        "counterparty": "Client",
    }
    assert transaction_fingerprint(company_id=uuid4(), **shared) != transaction_fingerprint(
        company_id=uuid4(), **shared
    )
