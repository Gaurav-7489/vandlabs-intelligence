"""Programmatically-built real files (no binary blobs committed)."""
import io
import zipfile
from datetime import date

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def make_pdf(pages: list[str]) -> bytes:
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, text in enumerate(pages):
        content_obj = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_obj} 0 R /Resources << /Font << /F1 {3 + 2 * n} 0 R >> >> >>".encode())
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None, nested_zip: bool = False) -> bytes:
    from docx import Document
    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, v in enumerate(row):
                t.cell(r, c).text = v
    buf = io.BytesIO()
    d.save(buf)
    if not nested_zip:
        return buf.getvalue()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in zin.infolist():
            zout.writestr(i, zin.read(i.filename))
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big.bin", b"\0" * 5_000_000)
        zout.writestr("word/embeddings/nested.zip", inner.getvalue())
    return out.getvalue()


def make_xlsx(commitments_due: date, task_due: date) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Commitments"
    ws.append(["ID", "Commitment", "Customer", "Owner", "Due Date", "Status", "Depends On"])
    ws.append(["C-9", "Ship Zephyr portal", "Zephyr Inc", "Ana Cruz", commitments_due, "In Progress", "T-9"])
    ws2 = wb.create_sheet("Tasks")
    ws2.append(["ID", "Task", "Owner", "Due Date", "Status"])
    ws2.append(["T-9", "Provision Zephyr tenant", "Lee Park", task_due, "Blocked"])
    ws2.append([None, None, None, None, None])  # blank row is skipped
    ws2["F2"] = "=1+1"  # formula must never be evaluated
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
