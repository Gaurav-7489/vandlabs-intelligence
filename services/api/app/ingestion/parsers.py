"""Safe parsing into text chunks and tables. No uploaded content is ever executed. Hard row/char ceilings apply."""
import csv
import io
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings

CHUNK_CHARS = 1200


@dataclass
class Table:
    name: str
    headers: list[str]
    rows: list[tuple[int, list[Any]]]  # (1-based source row number, cell values)


@dataclass
class Parsed:
    chunks: list[tuple[str, str]] = field(default_factory=list)  # (text, locator)
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class ParseLimitExceeded(Exception):
    pass


def _chunk_text(text: str, locator_prefix: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    buf = ""
    for para in [p.strip() for p in text.replace("\r", "").split("\n") if p.strip()]:
        if buf and len(buf) + len(para) + 1 > CHUNK_CHARS:
            out.append((buf, f"{locator_prefix} part {len(out) + 1}"))
            buf = ""
        while len(para) > CHUNK_CHARS:
            out.append((para[:CHUNK_CHARS], f"{locator_prefix} part {len(out) + 1}"))
            para = para[CHUNK_CHARS:]
        buf = f"{buf}\n{para}".strip()
    if buf:
        out.append((buf, f"{locator_prefix} part {len(out) + 1}"))
    return out


def parse(kind: str, data: bytes, s: Settings) -> Parsed:
    fn = {"csv": _csv, "txt": _txt, "xlsx": _xlsx, "docx": _docx, "pdf": _pdf}[kind]
    return fn(data, s)


def _txt(data: bytes, s: Settings) -> Parsed:
    text = data.decode("utf-8-sig")
    if len(text) > s.max_parse_chars:
        raise ParseLimitExceeded("text too large")
    return Parsed(chunks=_chunk_text(text, "text"))


def _csv(data: bytes, s: Settings) -> Parsed:
    text = data.decode("utf-8-sig")
    rows: list[tuple[int, list[Any]]] = []
    reader = csv.reader(io.StringIO(text))
    headers: list[str] = []
    for i, row in enumerate(reader, start=1):
        if i == 1:
            headers = [c.strip() for c in row]
            continue
        if not any(c.strip() for c in row):
            continue
        if len(rows) >= s.max_parse_rows:
            raise ParseLimitExceeded("too many rows")
        rows.append((i, row))
    return Parsed(tables=[Table("csv", headers, rows)])


def _xlsx(data: bytes, s: Settings) -> Parsed:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # data_only: never evaluate formulas
    parsed = Parsed()
    total = 0
    try:
        for ws in wb.worksheets:
            headers: list[str] = []
            rows: list[tuple[int, list[Any]]] = []
            for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if i == 1:
                    headers = ["" if c is None else str(c).strip() for c in row]
                    continue
                if all(c is None or str(c).strip() == "" for c in row):
                    continue
                total += 1
                if total > s.max_parse_rows:
                    raise ParseLimitExceeded("too many rows")
                rows.append((i, list(row)))
            parsed.tables.append(Table(ws.title, headers, rows))
    finally:
        wb.close()
    return parsed


def _docx(data: bytes, s: Settings) -> Parsed:
    from docx import Document
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    if len(text) > s.max_parse_chars:
        raise ParseLimitExceeded("text too large")
    parsed = Parsed(chunks=_chunk_text(text, "document"))
    for ti, t in enumerate(doc.tables, start=1):
        grid = [[c.text.strip() for c in r.cells] for r in t.rows]
        if len(grid) > 1:
            parsed.tables.append(Table(f"table {ti}", grid[0], [(i + 2, r) for i, r in enumerate(grid[1:])]))
    return parsed


def _pdf(data: bytes, s: Settings) -> Parsed:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return Parsed(notes=["PDF is encrypted; content not extracted"])
    parsed = Parsed()
    total = 0
    for pno, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        total += len(text)
        if total > s.max_parse_chars:
            raise ParseLimitExceeded("text too large")
        parsed.chunks.extend(_chunk_text(text, f"page {pno}"))
    if not parsed.chunks:
        parsed.notes.append("No extractable text. OCR is not configured, so scanned documents cannot be read.")
    return parsed
