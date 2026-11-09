"""Versioned, deterministic transaction fingerprints for import deduplication."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from uuid import UUID

FINGERPRINT_VERSION = 1


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def transaction_fingerprint(
    *,
    company_id: UUID,
    transaction_date: date,
    amount: Decimal,
    currency: str,
    direction: str,
    reference: str | None,
    counterparty: str | None,
) -> str:
    """Hash only normalized business fields; caller handles reference-less ambiguity."""
    payload = [
        str(company_id),
        transaction_date.isoformat(),
        format(amount, "f"),
        currency.upper(),
        direction.upper(),
        normalize_text(reference),
        normalize_text(counterparty),
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
