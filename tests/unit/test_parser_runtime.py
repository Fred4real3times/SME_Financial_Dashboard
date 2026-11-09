from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook

from sme_financial_dashboard.domain.import_parsing import ImportFileError
from sme_financial_dashboard.domain.parser_runtime import (
    _run_parser_worker,
    inspect_statement_bounded,
    list_xlsx_worksheets_bounded,
)


def test_csv_is_parsed_in_a_bounded_worker():
    document = inspect_statement_bounded(
        b"Date,Amount,Currency,Direction\n2026-01-01,125.50,XAF,INFLOW\n",
        "statement.csv",
    )
    assert document.file_type == "CSV"
    assert document.headers == ("Date", "Amount", "Currency", "Direction")
    assert document.rows[0].values == ("2026-01-01", "125.50", "XAF")


def test_xlsx_worksheet_discovery_uses_a_bounded_worker():
    workbook = Workbook()
    workbook.active.title = "January"
    workbook.create_sheet("February")
    output = BytesIO()
    workbook.save(output)

    assert list_xlsx_worksheets_bounded(output.getvalue()) == ("January", "February")


def test_parser_timeout_stops_the_worker_and_returns_a_stable_error():
    with pytest.raises(ImportFileError) as error:
        _run_parser_worker(
            "inspect",
            b"Date,Amount,Currency,Direction\n2026-01-01,1.00,XAF,INFLOW\n",
            file_name="statement.csv",
            timeout_seconds=0.001,
        )
    assert error.value.code == "PARSER_TIMEOUT"
    assert "time limit" in error.value.message


def test_parser_worker_preserves_safe_parser_error_codes():
    with pytest.raises(ImportFileError) as error:
        inspect_statement_bounded(b"not a pdf", "statement.pdf")
    assert error.value.code == "FILE_SIGNATURE_MISMATCH"
