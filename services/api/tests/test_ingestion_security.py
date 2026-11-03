import asyncio
import io
import zipfile
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.ingestion.extract import extract
from app.ingestion.parsers import ParseLimitExceeded
from app.ingestion.sandbox import isolation_available, run_sandboxed
from app.ingestion.scan import ClamdScanner
from app.ingestion.validate import detect_type
from tests import fixtures as fx
from tests.conftest import drain

API = "/api/v1"
S = Settings()


# ---------------- real format fixtures through the sandbox ----------------
def test_pdf_text_and_pages_with_provenance():
    p = run_sandboxed("pdf", fx.make_pdf(["Contract with Acme", "Delivery due 2026-12-01"]), S)
    assert [loc for _, loc in p.chunks] == ["page 1 part 1", "page 2 part 1"]
    assert "Acme" in p.chunks[0][0] and "2026-12-01" in p.chunks[1][0]


def test_docx_paragraphs_and_tables():
    p = run_sandboxed("docx", fx.make_docx(["Kickoff notes", "Owner: Priya"], table=[["Task", "Owner", "Due Date"], ["Write spec", "Priya", "2026-12-05"]]), S)
    assert "Kickoff notes" in p.chunks[0][0]
    t = p.tables[0]
    assert t.headers == ["Task", "Owner", "Due Date"] and t.rows[0][1] == ["Write spec", "Priya", "2026-12-05"]
    assert extract(p.tables).tasks[0]["title"] == "Write spec"


def test_xlsx_sheets_dates_blank_rows_and_no_formula_evaluation():
    due, tdue = date.today() + timedelta(days=4), date.today() - timedelta(days=2)
    p = run_sandboxed("xlsx", fx.make_xlsx(due, tdue), S)
    ex = extract(p.tables)
    assert [t.name for t in p.tables] == ["Commitments", "Tasks"]
    c, t = ex.commitments[0], ex.tasks[0]
    assert c["due_date"] == due and c["depends_on"] == ["T-9"] and c["source_locator"] == "Commitments!row 2"
    assert t["status"] == "blocked" and t["due_date"] == tdue and t["source_locator"] == "Tasks!row 2"
    assert len(ex.tasks) == 1 and ex.rejected == []  # blank row skipped, not rejected


def test_csv_and_txt():
    p = run_sandboxed("csv", b"title,due date\nA,2026-01-02\n", S)
    assert p.tables[0].rows == [(2, ["A", "2026-01-02"])]
    t = run_sandboxed("txt", ("para one\n\n" + "x" * 3000).encode(), S)
    assert len(t.chunks) >= 3 and all(len(c) <= 1200 for c, _ in t.chunks)


# ---------------- hostile / malformed input ----------------
def test_validation_rejects_wrong_extension_empty_unsupported():
    with pytest.raises(Exception, match="match its extension"):
        detect_type("a.pdf", fx.make_docx(["x"]), S)
    with pytest.raises(Exception, match="match its extension"):
        detect_type("a.docx", fx.make_pdf(["x"]), S)
    with pytest.raises(Exception, match="empty"):
        detect_type("a.txt", b"", S)
    with pytest.raises(Exception, match="Unsupported"):
        detect_type("a.exe", b"MZ", S)


def test_nested_archive_inside_docx_is_never_expanded():
    data = fx.make_docx(["safe text"], nested_zip=True)
    assert len(data) < 200_000  # nested 5MB of zeros compresses tiny; outer validation passes
    assert detect_type("n.docx", data, S) == "docx"
    p = run_sandboxed("docx", data, S)  # parser reads document.xml only; nested archive stays inert
    assert p.chunks[0][0] == "safe text"


def test_corrupted_and_malformed_files_fail_in_the_child_not_the_worker():
    for kind, blob in (("pdf", b"%PDF-1.4 garbage"), ("xlsx", b"PK\x03\x04 not really"), ("docx", b"PK\x03\x04 nope")):
        with pytest.raises(ValueError, match="parser failed"):
            run_sandboxed(kind, blob, S)
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("xl/workbook.xml", "<not-closed")
    with pytest.raises(ValueError):
        run_sandboxed("xlsx", broken.getvalue(), S)


def test_row_limit_enforced_in_sandbox():
    big = b"title,due date\n" + b"a,2026-01-01\n" * 60_000
    with pytest.raises(ParseLimitExceeded):
        run_sandboxed("csv", big, S)


def test_timeout_kills_runaway_parser():
    with pytest.raises(ParseLimitExceeded, match="timed out"):
        run_sandboxed("xlsx", fx.make_xlsx(date.today(), date.today()), Settings(parser_timeout_seconds=0.05))


def test_memory_limit_kills_parser_without_harming_caller():
    with pytest.raises(ParseLimitExceeded, match="resource limit"):
        run_sandboxed("txt", b"a" * 40_000_000, Settings(parser_memory_mb=64, max_parse_chars=10**9))


def test_sandbox_has_no_network():
    out = __import__("subprocess").run(
        ["python3", "-s", "-m", "app.ingestion.sandbox_child", "__netprobe__", "5", "512"], input=b"", capture_output=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]), env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"})
    assert out.stdout == b"blocked"
    assert isolation_available() in (True, False)  # reported honestly; the in-process socket block applies regardless


# ---------------- scanner (fake clamd speaking INSTREAM) ----------------
class FakeClamd:
    def __init__(self):
        self.server = None
        self.port = 0
        self.mode = "ok"  # ok | garbage

    async def start(self):
        async def handle(r, w):
            assert await r.readexactly(10) == b"zINSTREAM\0"
            data = b""
            while True:
                n = int.from_bytes(await r.readexactly(4), "big")
                if n == 0:
                    break
                data += await r.readexactly(n)
            if self.mode == "garbage":
                w.write(b"WAT\0")
            else:
                w.write(b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in data else b"stream: OK\0")
            await w.drain()
            w.close()
        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
async def clamd():
    c = FakeClamd()
    await c.start()
    yield c
    await c.stop()


async def test_clamd_client_protocol_and_fail_closed(clamd):
    sc = ClamdScanner("127.0.0.1", clamd.port)
    assert (await sc.scan(b"hello")).status == "clean"
    r = await sc.scan(fx.EICAR)
    assert r.status == "infected" and "Eicar" in r.detail
    clamd.mode = "garbage"
    assert (await sc.scan(b"hello")).status == "unavailable"  # unexpected reply is never treated as clean
    assert (await ClamdScanner("127.0.0.1", 1).scan(b"x")).status == "unavailable"  # unreachable => unavailable


def _use_scanner(worker, port, required):
    worker.s = Settings(scanner_backend="clamd", clamd_port=port, scan_required=required)
    worker.scanner = ClamdScanner("127.0.0.1", port, timeout=3)


async def test_infected_file_is_quarantined_never_indexed(client, make_env, worker, clamd):
    env = await make_env("av1")
    _use_scanner(worker, clamd.port, True)
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("bad.txt", fx.EICAR + b" invoice acme", "text/plain")})
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["status"] == "quarantined" and d["scan_status"] == "infected" and d["chunk_count"] == 0
    assert (await client.get(f"{API}/search", params={"q": "invoice acme"}, headers=env.h("viewer"))).json()["items"] == []
    acts = [e["action"] for e in (await client.get(f"{API}/audit", headers=env.h("auditor"))).json()["items"]]
    assert "document.quarantined" in acts


async def test_clean_file_marked_clean_and_indexed(client, make_env, worker, clamd):
    env = await make_env("av2")
    _use_scanner(worker, clamd.port, True)
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("ok.txt", b"quarterly zephyr plan", "text/plain")})
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["scan_status"] == "clean" and d["status"] in ("completed", "requires_review") and d["chunk_count"] == 1


async def test_scanner_outage_holds_file_unindexed_then_recovers(client, make_env, worker, clamd, worker_sql):
    env = await make_env("av3")
    _use_scanner(worker, 1, True)  # nothing listens on port 1
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("held.txt", b"held content zephyr", "text/plain")})
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["status"] == "scan_pending" and d["scan_status"] == "unavailable" and d["chunk_count"] == 0
    assert (await client.get(f"{API}/search", params={"q": "held content"}, headers=env.h("viewer"))).json()["items"] == []
    # scanner comes back; job retries
    worker_sql.execute(text("UPDATE jobs SET run_at = now() WHERE status='retry_scheduled'"))
    worker_sql.connection.commit()
    _use_scanner(worker, clamd.port, True)
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["scan_status"] == "clean" and d["chunk_count"] == 1


async def test_without_scanner_in_dev_status_is_not_performed_never_clean(client, make_env, worker):
    env = await make_env("av4")
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("dev.txt", b"dev file", "text/plain")})
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["scan_status"] == "not_performed"


async def test_xlsx_end_to_end_through_api(client, make_env, worker):
    env = await make_env("xl")
    due = date.today() + timedelta(days=4)
    r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": ("plan.xlsx", fx.make_xlsx(due, date.today() - timedelta(days=2)), "application/octet-stream")})
    assert r.status_code == 202
    await drain(worker)
    d = (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("viewer"))).json()
    assert d["stats"]["commitments"] == 1 and d["stats"]["tasks"] == 1
    ins = (await client.get(f"{API}/insights", headers=env.h("viewer"))).json()["items"]
    assert any(i["rule"] == "commitment_blocked_by_task" and "Provision Zephyr tenant" in i["summary"] for i in ins)
