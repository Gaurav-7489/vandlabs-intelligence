"""Upload validation: extension allowlist, magic-byte signature, archive-bomb guard, filename sanitation."""
import io
import re
import unicodedata
import zipfile

from app.core.config import Settings
from app.core.errors import AppError, PayloadTooLarge

ALLOWED = {"pdf", "docx", "csv", "xlsx", "txt"}
_MAX_UNCOMPRESSED = 300 * 1024 * 1024
_MAX_ZIP_MEMBERS = 5_000


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "upload").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", name).strip(". ") or "upload"
    return name[:200]


def detect_type(filename: str, data: bytes, s: Settings) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise AppError("Unsupported file type", allowed=sorted(ALLOWED))
    if len(data) == 0:
        raise AppError("File is empty")
    if len(data) > s.max_upload_bytes:
        raise PayloadTooLarge("File exceeds the maximum upload size")
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise AppError("File content does not match its extension")
    elif ext in ("docx", "xlsx"):
        _check_zip(data, ext, s)
    else:  # csv / txt: must be text; NUL bytes indicate binary content
        if b"\x00" in data[:8192]:
            raise AppError("File content does not match its extension")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AppError("Text files must be UTF-8 encoded") from None
    return ext


def _check_zip(data: bytes, ext: str, s: Settings) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise AppError("File content does not match its extension")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except zipfile.BadZipFile:
        raise AppError("File is corrupt") from None
    total = sum(i.file_size for i in infos)
    if len(infos) > _MAX_ZIP_MEMBERS or total > _MAX_UNCOMPRESSED or total > len(data) * s.max_zip_expansion_ratio:
        raise AppError("File rejected: unsafe archive structure")
    names = {i.filename for i in infos}
    if any(n.startswith("/") or ".." in n.split("/") for n in names):
        raise AppError("File rejected: unsafe archive structure")
    marker = "word/document.xml" if ext == "docx" else "xl/workbook.xml"
    if "[Content_Types].xml" not in names or marker not in names:
        raise AppError("File content does not match its extension")
    if any(n.endswith("vbaProject.bin") for n in names):
        raise AppError("Macro-enabled content is not accepted")
