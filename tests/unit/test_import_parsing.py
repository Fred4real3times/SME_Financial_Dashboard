from __future__ import annotations

from io import BytesIO
import zipfile

import pytest
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from sme_financial_dashboard.domain.import_parsing import (
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    MAX_PDF_PAGES,
    MAX_UPLOAD_BYTES,
    MAX_XLSX_ARCHIVE_ENTRIES,
    ImportFileError,
    inspect_statement,
)


def _pdf_with_table() -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output)
    table = Table(
        [
            ["Date", "Amount", "Currency", "Direction"],
            ["2026-01-01", "250.00", "XAF", "INFLOW"],
        ],
        colWidths=[100, 100, 100, 100],
    )
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black)]))
    document.build([table])
    return output.getvalue()


def _pdf_without_text() -> bytes:
    from reportlab.pdfgen import canvas

    output = BytesIO()
    page = canvas.Canvas(output)
    page.rect(30, 30, 200, 100, stroke=1, fill=0)
    page.showPage()
    page.save()
    return output.getvalue()


def test_csv_inspection_preserves_header_and_source_row_numbers():
    content = b"Date;Amount;Currency\n2026-01-01;100.00;XAF\n"
    document = inspect_statement(content, "statement.csv", delimiter=";")
    assert document.file_type == "CSV"
    assert document.headers == ("Date", "Amount", "Currency")
    assert document.rows[0].source_row_number == 2
    assert document.rows[0].values == ("2026-01-01", "100.00", "XAF")


def test_csv_rejects_extra_columns_instead_of_silently_dropping_them():
    content = b"Date,Amount\n2026-01-01,100,unexpected\n"
    with pytest.raises(ImportFileError, match="extra columns"):
        inspect_statement(content, "statement.csv")


def test_csv_rejects_wrong_content_signature():
    with pytest.raises(ImportFileError) as error:
        inspect_statement(b"%PDF-1.7\n", "statement.csv")
    assert error.value.code == "FILE_SIGNATURE_MISMATCH"


def test_xlsx_requires_explicit_sheet_when_multiple_sheets_exist():
    workbook = Workbook()
    workbook.active.append(["Date", "Amount"])
    workbook.create_sheet("Second")
    output = BytesIO()
    workbook.save(output)
    with pytest.raises(ImportFileError) as error:
        inspect_statement(output.getvalue(), "statement.xlsx")
    assert error.value.code == "XLSX_SHEET_REQUIRED"


def test_xlsx_formula_cells_are_not_imported_or_evaluated():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Amount"])
    sheet.append(["2026-01-01", "=1+1"])
    output = BytesIO()
    workbook.save(output)
    with pytest.raises(ImportFileError) as error:
        inspect_statement(output.getvalue(), "statement.xlsx")
    assert error.value.code == "XLSX_FORMULA_UNSUPPORTED"


def test_pdf_table_extraction_retains_page_and_table_provenance():
    document = inspect_statement(_pdf_with_table(), "statement.pdf")
    assert document.file_type == "PDF"
    assert document.extraction_method == "PDF_TABLE"
    assert document.source_page_count == 1
    assert document.headers == ("Date", "Amount", "Currency", "Direction")
    assert document.rows[0].source_page_number == 1
    assert document.rows[0].source_table_index == 1
    assert document.rows[0].values[2] == "XAF"


def test_scanned_or_image_only_pdf_is_rejected_without_ocr():
    with pytest.raises(ImportFileError) as error:
        inspect_statement(_pdf_without_text(), "scan.pdf")
    assert error.value.code == "PDF_SCANNED_UNSUPPORTED"


@pytest.mark.parametrize(
    ("file_name", "payload", "code"),
    [
        ("statement.xls", b"not a file", "FILE_TYPE_UNSUPPORTED"),
        ("statement.pdf", b"not a pdf", "FILE_SIGNATURE_MISMATCH"),
        ("statement.csv", b"", "FILE_EMPTY"),
    ],
)
def test_unsupported_or_malformed_files_have_stable_issue_codes(file_name, payload, code):
    with pytest.raises(ImportFileError) as error:
        inspect_statement(payload, file_name)
    assert error.value.code == code



def test_parser_rejects_upload_above_ten_mib_limit():
    with pytest.raises(ImportFileError) as error:
        inspect_statement(b"x" * (MAX_UPLOAD_BYTES + 1), "oversized.csv")
    assert error.value.code == "FILE_TOO_LARGE"



def _encrypted_pdf() -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output, encrypt="unit-test-password")
    page.drawString(72, 720, "Confidential statement")
    page.showPage()
    page.save()
    return output.getvalue()


def _pdf_with_pages(page_count: int) -> bytes:
    output = BytesIO()
    page = canvas.Canvas(output)
    for number in range(page_count):
        page.drawString(72, 720, f"Page {number + 1}")
        page.showPage()
    page.save()
    return output.getvalue()


def test_csv_row_limit_is_enforced_while_streaming():
    header = b"Date,Amount,Currency,Direction\n"
    row = b"2026-01-01,1.00,XAF,INFLOW\n"
    content = header + row * (MAX_IMPORT_ROWS + 1)
    with pytest.raises(ImportFileError) as error:
        inspect_statement(content, "large.csv")
    assert error.value.code == "ROW_LIMIT_EXCEEDED"


def test_csv_column_limit_is_enforced():
    header = ",".join(f"Column {index}" for index in range(MAX_IMPORT_COLUMNS + 1))
    with pytest.raises(ImportFileError) as error:
        inspect_statement(header.encode(), "wide.csv")
    assert error.value.code == "COLUMN_LIMIT_EXCEEDED"


def test_xlsx_column_limit_is_enforced():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([f"Column {index}" for index in range(MAX_IMPORT_COLUMNS + 1)])
    output = BytesIO()
    workbook.save(output)
    with pytest.raises(ImportFileError) as error:
        inspect_statement(output.getvalue(), "wide.xlsx")
    assert error.value.code == "COLUMN_LIMIT_EXCEEDED"


def test_encrypted_pdf_has_stable_unsupported_error_code():
    with pytest.raises(ImportFileError) as error:
        inspect_statement(_encrypted_pdf(), "encrypted.pdf")
    assert error.value.code == "PDF_ENCRYPTED"


def test_pdf_page_limit_is_enforced():
    with pytest.raises(ImportFileError) as error:
        inspect_statement(_pdf_with_pages(MAX_PDF_PAGES + 1), "too-many-pages.pdf")
    assert error.value.code == "PDF_PAGE_LIMIT_EXCEEDED"



def test_xlsx_archive_entry_limit_is_enforced():
    workbook = Workbook()
    workbook.active.append(["Date", "Amount"])
    original = BytesIO()
    workbook.save(original)
    expanded = BytesIO()
    with zipfile.ZipFile(BytesIO(original.getvalue())) as source:
        with zipfile.ZipFile(expanded, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for member in source.infolist():
                target.writestr(member.filename, source.read(member.filename))
            for index in range(MAX_XLSX_ARCHIVE_ENTRIES):
                target.writestr(f"extra/{index}.txt", b"")
    with pytest.raises(ImportFileError) as error:
        inspect_statement(expanded.getvalue(), "entry-bomb.xlsx")
    assert error.value.code == "XLSX_ENTRY_LIMIT_EXCEEDED"


def test_pdf_table_rejects_rows_with_missing_columns(monkeypatch):
    class FakePage:
        def extract_text(self):
            return "Date Amount Currency"

        def extract_tables(self):
            return [
                [
                    ["Date", "Amount", "Currency"],
                    ["2026-01-01", "100.00"],
                ]
            ]

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        "sme_financial_dashboard.domain.import_parsing.pdfplumber.open",
        lambda *_args, **_kwargs: FakePdf(),
    )
    with pytest.raises(ImportFileError) as error:
        inspect_statement(b"%PDF-1.7\nplaceholder", "broken-table.pdf")
    assert error.value.code == "PDF_TABLE_LAYOUT_AMBIGUOUS"
