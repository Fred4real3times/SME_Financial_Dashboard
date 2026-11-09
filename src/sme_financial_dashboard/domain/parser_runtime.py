"""Wall-clock-bounded entry points for untrusted statement parsing."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sme_financial_dashboard.domain.import_parsing import (
    MAX_UPLOAD_BYTES,
    ImportFileError,
    ParsedDocument,
    ParsedRow,
)

PARSER_TIMEOUT_SECONDS = 30
MAX_PARSER_RESPONSE_BYTES = 64 * 1024 * 1024
_WORKER_MODULE = "sme_financial_dashboard.domain.parser_worker"


def _restore_cell(value: Any) -> Any:
    if not isinstance(value, dict) or "__sme_type__" not in value:
        return value
    kind = value.get("__sme_type__")
    raw = value.get("value")
    if not isinstance(raw, str):
        raise ValueError("Invalid parser worker value.")
    if kind == "datetime":
        return datetime.fromisoformat(raw)
    if kind == "date":
        return date.fromisoformat(raw)
    if kind == "time":
        return time.fromisoformat(raw)
    if kind == "decimal":
        return Decimal(raw)
    raise ValueError("Unknown parser worker value type.")


def _run_parser_worker(
    operation: str,
    file_bytes: bytes,
    *,
    file_name: str = "statement.xlsx",
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    worksheet_name: str | None = None,
    timeout_seconds: float = PARSER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise ImportFileError("FILE_EMPTY", "The uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ImportFileError("FILE_TOO_LARGE", "File exceeds the 10 MiB upload limit.")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("Parser timeout must be a positive finite number.")

    command = [
        sys.executable,
        "-m",
        _WORKER_MODULE,
        operation,
        f"--file-name={file_name}",
        f"--delimiter={delimiter}",
        f"--encoding={encoding}",
    ]
    if worksheet_name is not None:
        command.append(f"--worksheet-name={worksheet_name}")

    try:
        completed = subprocess.run(
            command,
            input=file_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            close_fds=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise ImportFileError(
            "PARSER_TIMEOUT",
            f"Statement parsing exceeded the {int(PARSER_TIMEOUT_SECONDS)}-second time limit. "
            "The parsing worker was stopped; check the file or use a smaller statement.",
        ) from exc
    except OSError as exc:
        raise ImportFileError(
            "PARSER_WORKER_UNAVAILABLE",
            "The isolated parser process could not be started on this computer.",
        ) from exc

    if len(completed.stdout) > MAX_PARSER_RESPONSE_BYTES:
        raise ImportFileError(
            "PARSER_OUTPUT_LIMIT_EXCEEDED",
            "The parser result exceeds the safe response-size limit.",
        )
    if completed.returncode != 0:
        raise ImportFileError(
            "PARSER_WORKER_FAILED",
            "The isolated parser process ended unexpectedly.",
        )
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFileError(
            "PARSER_WORKER_FAILED",
            "The isolated parser returned an invalid response.",
        ) from exc

    if not isinstance(response, dict) or response.get("ok") is not True:
        code = response.get("code") if isinstance(response, dict) else None
        message = response.get("message") if isinstance(response, dict) else None
        raise ImportFileError(
            code if isinstance(code, str) else "PARSER_WORKER_FAILED",
            message if isinstance(message, str) else "The parser worker could not process this file.",
        )
    return response


def inspect_statement_bounded(
    file_bytes: bytes,
    file_name: str,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    worksheet_name: str | None = None,
) -> ParsedDocument:
    """Inspect a file in a disposable process with a strict wall-clock deadline."""
    response = _run_parser_worker(
        "inspect",
        file_bytes,
        file_name=file_name,
        delimiter=delimiter,
        encoding=encoding,
        worksheet_name=worksheet_name,
    )
    try:
        document = response["document"]
        rows = tuple(
            ParsedRow(
                source_row_number=int(row["source_row_number"]),
                values=tuple(_restore_cell(value) for value in row["values"]),
                source_page_number=row.get("source_page_number"),
                source_table_index=row.get("source_table_index"),
            )
            for row in document["rows"]
        )
        return ParsedDocument(
            file_type=str(document["file_type"]),
            extraction_method=str(document["extraction_method"]),
            headers=tuple(str(value) for value in document["headers"]),
            rows=rows,
            source_page_count=document.get("source_page_count"),
            worksheet_name=document.get("worksheet_name"),
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ImportFileError(
            "PARSER_WORKER_FAILED",
            "The isolated parser returned an invalid document structure.",
        ) from exc


def list_xlsx_worksheets_bounded(file_bytes: bytes) -> tuple[str, ...]:
    """List workbook sheets in the same time-bounded process used for parsing."""
    response = _run_parser_worker("worksheets", file_bytes)
    worksheets = response.get("worksheets")
    if not isinstance(worksheets, list) or any(not isinstance(name, str) for name in worksheets):
        raise ImportFileError(
            "PARSER_WORKER_FAILED",
            "The isolated parser returned an invalid worksheet list.",
        )
    return tuple(worksheets)
