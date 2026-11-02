"""Deterministic mapping of tabular rows to commitments / tasks. No LLM involved; every record keeps its source locator."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.ingestion.parsers import Table

ALIASES: dict[str, set[str]] = {
    "key": {"id", "key", "ref", "reference", "commitment id", "task id", "commitment_id", "task_id"},
    "title": {"title", "name", "commitment", "task", "description", "summary"},
    "customer": {"customer", "client", "account"},
    "owner": {"owner", "assignee", "responsible", "owner name", "assigned to"},
    "owner_email": {"owner email", "owner_email", "email", "assignee email"},
    "due": {"due", "due date", "due_date", "deadline", "target date"},
    "status": {"status", "state"},
    "depends": {"depends on", "depends_on", "dependencies", "blocked by", "blocked_by"},
    "type": {"type", "record type", "record_type", "kind"},
}
_DONE = {"done", "complete", "completed", "closed", "delivered", "shipped", "resolved"}
_PROG = {"in progress", "in_progress", "wip", "started", "ongoing"}
_BLOCKED = {"blocked", "on hold", "stuck"}
_CANCEL = {"cancelled", "canceled", "dropped", "withdrawn"}


@dataclass
class Extracted:
    commitments: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)  # {"locator", "reason"}
    unmapped_tables: list[str] = field(default_factory=list)


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h).strip().lower().replace("_", " ")) if h else ""


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:120]


def parse_date(v: Any) -> date | None:
    """Accepts real date cells and ISO yyyy-mm-dd only. Ambiguous formats (e.g. 03/04/2026) are rejected, not guessed."""
    if v is None or str(v).strip() == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip()[:10]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", str(v).strip()) else _raise()
    except ValueError:
        raise ValueError(f"unparseable date {str(v)[:30]!r}") from None


def _raise() -> date:
    raise ValueError("non-ISO date")


def norm_status(raw: Any, kind: str) -> str:
    v = _norm(str(raw or ""))
    if v in _DONE:
        return "done"
    if v in _CANCEL:
        return "cancelled"
    if kind == "task":
        return "blocked" if v in _BLOCKED else "in_progress" if v in _PROG else "todo"
    return "open"


def _cell_getter(col: dict[str, int], cells: list[Any]) -> Any:
    def cell(name: str) -> Any:
        i = col.get(name)
        return cells[i] if i is not None and i < len(cells) else None
    return cell


def extract(tables: list[Table]) -> Extracted:
    out = Extracted()
    for t in tables:
        col: dict[str, int] = {}
        for idx, h in enumerate(t.headers):
            for canon, names in ALIASES.items():
                if _norm(h) in names and canon not in col:
                    col[canon] = idx
        if "title" not in col:
            out.unmapped_tables.append(t.name)
            continue
        default_kind = "commitment" if "commit" in t.name.lower() else "task" if "task" in t.name.lower() else None
        for rownum, cells in t.rows:
            loc = f"{t.name}!row {rownum}"

            cell = _cell_getter(col, cells)

            title = str(cell("title") or "").strip()
            if not title:
                out.rejected.append({"locator": loc, "reason": "missing title"})
                continue
            kind = _norm(str(cell("type") or "")) or default_kind
            if kind not in ("commitment", "task"):
                kind = "commitment" if ("customer" in col or "commitment" in _norm(t.headers[col["title"]])) else "task"
            try:
                due = parse_date(cell("due"))
            except ValueError as e:
                out.rejected.append({"locator": loc, "reason": str(e)})
                continue
            key = str(cell("key") or "").strip() or _slug(title)
            rec: dict[str, Any] = {
                "external_key": key[:200], "title": title[:500], "owner_name": (str(cell("owner")).strip() or None) if cell("owner") else None,
                "owner_email": (str(cell("owner_email")).strip().lower() or None) if cell("owner_email") else None,
                "due_date": due, "status": norm_status(cell("status"), kind), "source_locator": loc[:120]}
            if kind == "commitment":
                rec["customer"] = (str(cell("customer")).strip() or None) if cell("customer") else None
                rec["depends_on"] = [d.strip() for d in re.split(r"[;,]", str(cell("depends") or "")) if d.strip()]
                out.commitments.append(rec)
            else:
                out.tasks.append(rec)
    return out
