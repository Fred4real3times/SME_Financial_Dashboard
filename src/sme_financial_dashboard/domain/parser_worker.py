"""Subprocess worker for wall-clock-bounded statement parsing."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sme_financial_dashboard.domain.import_parsing import (
    MAX_UPLOAD_BYTES,
    ImportFileError,
    inspect_statement,
    list_xlsx_worksheets,
)


def _encode_cell(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__sme_type__": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"__sme_type__": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"__sme_type__": "time", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__sme_type__": "decimal", "value": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _document_payload(document) -> dict[str, Any]:
    return {
        "file_type": document.file_type,
        "extraction_method": document.extraction_method,
        "headers": list(document.headers),
        "source_page_count": document.source_page_count,
        "worksheet_name": document.worksheet_name,
        "rows": [
            {
                "source_row_number": row.source_row_number,
                "values": [_encode_cell(value) for value in row.values],
                "source_page_number": row.source_page_number,
                "source_table_index": row.source_table_index,
            }
            for row in document.rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("operation", choices=("inspect", "worksheets"))
    parser.add_argument("--file-name", default="statement.xlsx")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--worksheet-name")
    args = parser.parse_args()

    try:
        file_bytes = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise ImportFileError("FILE_TOO_LARGE", "Uploaded file exceeds the 10 MiB limit.")
        if args.operation == "worksheets":
            payload = {"ok": True, "worksheets": list(list_xlsx_worksheets(file_bytes))}
        else:
            document = inspect_statement(
                file_bytes,
                args.file_name,
                delimiter=args.delimiter,
                encoding=args.encoding,
                worksheet_name=args.worksheet_name,
            )
            payload = {"ok": True, "document": _document_payload(document)}
    except ImportFileError as exc:
        payload = {"ok": False, "code": exc.code, "message": exc.message}
    except Exception:
        payload = {
            "ok": False,
            "code": "PARSER_WORKER_FAILED",
            "message": "The parser worker could not process this file safely.",
        }

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
