"""Run untrusted-file parsing in a separate, resource-limited, network-isolated subprocess.

Controls: wall-clock timeout; RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE / RLIMIT_NOFILE; empty network namespace via `unshare -rn`
(when the kernel permits) plus an in-process socket block; scratch cwd; minimal environment; output size cap. A crash or limit
breach kills only the child. NOT a full container/seccomp sandbox: deploy the worker as a non-root user in a locked-down container."""
import datetime as dt
import json
import os
import shutil
import subprocess  # noqa: S404
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.ingestion.parsers import Parsed, ParseLimitExceeded, Table

API_ROOT = str(Path(__file__).resolve().parents[2])
MAX_OUTPUT = 64 * 1024 * 1024


def _default(o: Any) -> Any:
    if isinstance(o, dt.datetime):
        return {"__dt": o.isoformat()}
    if isinstance(o, dt.date):
        return {"__d": o.isoformat()}
    return str(o)


def _hook(d: dict[str, Any]) -> Any:
    if "__dt" in d:
        return dt.datetime.fromisoformat(d["__dt"])
    if "__d" in d:
        return dt.date.fromisoformat(d["__d"])
    return d


def encode(p: Parsed) -> bytes:
    return json.dumps({"chunks": p.chunks, "notes": p.notes, "tables": [{"name": t.name, "headers": t.headers, "rows": t.rows} for t in p.tables]},
                      default=_default).encode()


def decode(b: bytes) -> Parsed:
    d = json.loads(b, object_hook=_hook)
    return Parsed(chunks=[tuple(c) for c in d["chunks"]], notes=d["notes"],
                  tables=[Table(t["name"], t["headers"], [(r[0], r[1]) for r in t["rows"]]) for t in d["tables"]])


def isolation_available() -> bool:
    if shutil.which("unshare") is None:
        return False
    return subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0  # noqa: S603, S607


def run_sandboxed(kind: str, data: bytes, s: Settings, *, child_args: list[str] | None = None) -> Parsed:
    cmd = [sys.executable, "-s", "-m", "app.ingestion.sandbox_child", kind, str(s.parser_cpu_seconds), str(s.parser_memory_mb), *(child_args or [])]
    if s.parser_isolate_network and isolation_available():
        cmd = ["unshare", "-rn", *cmd]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": API_ROOT, "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    with tempfile.TemporaryDirectory(prefix="vand-parse-") as scratch:
        try:
            r = subprocess.run(cmd, input=data, capture_output=True, timeout=s.parser_timeout_seconds, cwd=scratch, env=env)  # noqa: S603
        except subprocess.TimeoutExpired:
            raise ParseLimitExceeded("parser timed out") from None
    if r.returncode == 3:
        raise ParseLimitExceeded("parser exceeded a resource limit")
    if r.returncode != 0:
        raise ValueError("parser failed")
    if len(r.stdout) > MAX_OUTPUT:
        raise ParseLimitExceeded("parser output too large")
    return decode(r.stdout)
