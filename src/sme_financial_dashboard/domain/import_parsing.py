"""Bounded, non-executing parsers for CSV, XLSX and digital PDF statements."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from openpyxl import load_workbook

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_XLSX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_IMPORT_ROWS = 10_000
PREVIEW_SAMPLE_ROWS = 20
PARSER_VERSION = "1.0.0"


class ImportFileError(ValueError):
    """Raised when an uploaded statement is unsafe, malformed or unsupported."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedRow:
    source_row_number: int
    values: tuple[Any, ...]
    source_page_number: int | None = None
    source_table_index: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    file_type: str
    extraction_method: str
    headers: tuple[str, ...]
    rows: tuple[ParsedRow, ...]
    source_page_count: int | None = None
    worksheet_name: str | None = None


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _headers(values: tuple[Any, ...] | list[Any]) -> tuple[str, ...]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values, start=1):
        label = _cell_text(value) or f"Column {index}"
        counts[label] = counts.get(label, 0) + 1
        if counts[label] > 1:
            label = f"{label} ({counts[label]})"
        result.append(label[:120])
    if not result:
        raise ImportFileError("HEADER_MISSING", "The file has no header row.")
    return tuple(result)


def _check_size(file_bytes: bytes) -> None:
    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise ImportFileError("FILE_EMPTY", "The uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ImportFileError(
            "FILE_TOO_LARGE",
            f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB upload limit.",
        )


def inspect_statement(
    file_bytes: bytes,
    file_name: str,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    worksheet_name: str | None = None,
) -> ParsedDocument:
    """Inspect an allowlisted file without persisting rows or executing embedded content."""
    _check_size(file_bytes)
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".pdf"}:
        raise ImportFileError("FILE_TYPE_UNSUPPORTED", "Only .csv, .xlsx and .pdf are supported.")

    if suffix == ".csv":
        if file_bytes.startswith((b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
            raise ImportFileError("FILE_SIGNATURE_MISMATCH", "The file content does not match .csv.")
        if len(delimiter) != 1 or delimiter in {"\r", "\n", '"'}:
            raise ImportFileError("CSV_DELIMITER_INVALID", "CSV delimiter must be one safe character.")
        if encoding not in {"utf-8-sig", "utf-8", "cp1252", "latin-1"}:
            raise ImportFileError("CSV_ENCODING_UNSUPPORTED", "Choose UTF-8, Windows-1252 or Latin-1.")
        try:
            text = file_bytes.decode(encoding, errors="strict")
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            matrix = list(reader)
        except UnicodeDecodeError as exc:
            raise ImportFileError("CSV_ENCODING_INVALID", "File cannot be decoded with the selected encoding.") from exc
        except csv.Error as exc:
            raise ImportFileError("CSV_MALFORMED", "CSV structure is malformed.") from exc
        if not matrix:
            raise ImportFileError("HEADER_MISSING", "CSV has no rows.")
        header = _headers(matrix[0])
        rows: list[ParsedRow] = []
        for row_number, values in enumerate(matrix[1:], start=2):
            if len(rows) >= MAX_IMPORT_ROWS:
                raise ImportFileError("ROW_LIMIT_EXCEEDED", "CSV exceeds the 10,000-row limit.")
            padded = tuple(values[: len(header)]) + tuple("" for _ in range(max(0, len(header) - len(values))))
            rows.append(ParsedRow(row_number, padded))
        return ParsedDocument("CSV", "CSV_ROWS", header, tuple(rows))

    if suffix == ".xlsx":
        if not file_bytes.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(io.BytesIO(file_bytes)):
            raise ImportFileError("FILE_SIGNATURE_MISMATCH", "The file is not a valid XLSX ZIP container.")
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                infos = archive.infolist()
                expanded_size = sum(item.file_size for item in infos)
                if expanded_size > MAX_XLSX_EXPANDED_BYTES:
                    raise ImportFileError("XLSX_EXPANSION_LIMIT", "Expanded workbook exceeds 50 MiB.")
                if any(item.file_size > 0 and item.compress_size == 0 for item in infos):
                    raise ImportFileError("XLSX_INVALID_ARCHIVE", "Workbook contains an invalid ZIP entry.")
                if any(
                    item.compress_size > 0 and item.file_size / item.compress_size > 200
                    for item in infos
                ):
                    raise ImportFileError("XLSX_COMPRESSION_RATIO", "Workbook compression ratio is unsafe.")
            workbook = load_workbook(
                io.BytesIO(file_bytes), read_only=True, data_only=False, keep_links=False
            )
        except ImportFileError:
            raise
        except Exception as exc:
            raise ImportFileError("XLSX_MALFORMED", "XLSX workbook could not be opened safely.") from exc
        try:
            names = workbook.sheetnames
            if worksheet_name is None:
                if len(names) != 1:
                    raise ImportFileError(
                        "XLSX_SHEET_REQUIRED",
                        "Select a worksheet explicitly when the workbook contains multiple sheets.",
                    )
                worksheet_name = names[0]
            if worksheet_name not in names:
                raise ImportFileError("XLSX_SHEET_NOT_FOUND", "Selected worksheet does not exist.")
            sheet = workbook[worksheet_name]
            iterator = sheet.iter_rows(values_only=False)
            try:
                first = next(iterator)
            except StopIteration:
                raise ImportFileError("HEADER_MISSING", "Selected worksheet is empty.") from None
            header = _headers([cell.value for cell in first])
            rows = []
            for excel_row_number, cells in enumerate(iterator, start=2):
                if len(rows) >= MAX_IMPORT_ROWS:
                    raise ImportFileError("ROW_LIMIT_EXCEEDED", "Worksheet exceeds the 10,000-row limit.")
                values: list[Any] = []
                for cell in cells[: len(header)]:
                    value = cell.value
                    if isinstance(value, str) and value.startswith("="):
                        raise ImportFileError(
                            "XLSX_FORMULA_UNSUPPORTED",
                            "Formula cells are not imported; export the calculated values first.",
                        )
                    values.append(value)
                values.extend([""] * (len(header) - len(values)))
                rows.append(ParsedRow(excel_row_number, tuple(values)))
            return ParsedDocument("XLSX", "XLSX_SHEET", header, tuple(rows), worksheet_name=worksheet_name)
        finally:
            workbook.close()

    if not file_bytes.startswith(b"%PDF-"):
        raise ImportFileError("FILE_SIGNATURE_MISMATCH", "The file content does not match .pdf.")
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if getattr(pdf, "is_encrypted", False):
                raise ImportFileError("PDF_ENCRYPTED", "Password-protected PDFs are not supported.")
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ImportFileError("PDF_PAGE_LIMIT_EXCEEDED", "PDF exceeds the 100-page limit.")
            headers: tuple[str, ...] | None = None
            rows: list[ParsedRow] = []
            text_seen = False
            table_seen = False
            row_counter = 0
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                text_seen = text_seen or bool(page_text.strip())
                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables, start=1):
                    cleaned = [tuple(_cell_text(v) for v in row) for row in table if row]
                    cleaned = [row for row in cleaned if any(value for value in row)]
                    if not cleaned:
                        continue
                    table_seen = True
                    if headers is None:
                        headers = _headers(cleaned[0])
                        data_rows = cleaned[1:]
                    elif tuple(cleaned[0]) == headers:
                        data_rows = cleaned[1:]
                    else:
                        data_rows = cleaned
                    for values in data_rows:
                        if len(rows) >= MAX_IMPORT_ROWS:
                            raise ImportFileError("ROW_LIMIT_EXCEEDED", "PDF exceeds the 10,000-row limit.")
                        row_counter += 1
                        padded = tuple(values[: len(headers)]) + tuple(
                            "" for _ in range(max(0, len(headers) - len(values)))
                        )
                        rows.append(ParsedRow(row_counter, padded, page_number, table_index))
            if table_seen and headers is not None and rows:
                return ParsedDocument("PDF", "PDF_TABLE", headers, tuple(rows), len(pdf.pages))

            if not text_seen:
                raise ImportFileError(
                    "PDF_SCANNED_UNSUPPORTED",
                    "This PDF has no extractable text layer. Scanned/image-only PDFs are unsupported in the MVP.",
                )
            text_rows: list[tuple[int, tuple[str, ...]]] = []
            for page_number, page in enumerate(pdf.pages, start=1):
                for line in (page.extract_text() or "").splitlines():
                    columns = tuple(part.strip() for part in re.split(r"\s{2,}", line.strip()) if part.strip())
                    if len(columns) >= 2:
                        text_rows.append((page_number, columns))
            if len(text_rows) < 2:
                raise ImportFileError(
                    "PDF_UNSTRUCTURED_TEXT",
                    "PDF text was found, but no reliable multi-column table could be extracted.",
                )
            headers = _headers(text_rows[0][1])
            rows = []
            for page_number, values in text_rows[1:]:
                if len(rows) >= MAX_IMPORT_ROWS:
                    raise ImportFileError("ROW_LIMIT_EXCEEDED", "PDF exceeds the 10,000-row limit.")
                row_counter += 1
                padded = tuple(values[: len(headers)]) + tuple(
                    "" for _ in range(max(0, len(headers) - len(values)))
                )
                rows.append(ParsedRow(row_counter, padded, page_number, None))
            return ParsedDocument("PDF", "PDF_TEXT", headers, tuple(rows), len(pdf.pages))
    except ImportFileError:
        raise
    except Exception as exc:
        raise ImportFileError("PDF_MALFORMED", "PDF could not be parsed safely.") from exc
