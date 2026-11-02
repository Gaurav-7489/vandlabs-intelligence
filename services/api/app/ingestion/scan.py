"""Malware scanning. Statuses are truthful: `clean` only when a scanner actually returned OK; otherwise `unavailable`/`not_performed`."""
import asyncio
import struct
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


@dataclass
class ScanResult:
    status: str  # clean | infected | unavailable
    detail: str = ""


class Scanner(Protocol):
    async def scan(self, data: bytes) -> ScanResult: ...


class NoScanner:
    async def scan(self, data: bytes) -> ScanResult:
        return ScanResult("unavailable", "no scanner configured")


class ClamdScanner:
    """clamd INSTREAM protocol over TCP. Fails closed: any error => `unavailable` (never `clean`)."""

    def __init__(self, host: str, port: int, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout

    async def scan(self, data: bytes) -> ScanResult:
        try:
            return await asyncio.wait_for(self._scan(data), self.timeout)
        except Exception as e:  # noqa: BLE001
            return ScanResult("unavailable", f"scanner error: {type(e).__name__}")

    async def _scan(self, data: bytes) -> ScanResult:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(b"zINSTREAM\0")
            for i in range(0, len(data), 1 << 20):
                chunk = data[i:i + (1 << 20)]
                writer.write(struct.pack("!I", len(chunk)) + chunk)
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            reply = (await reader.readuntil(b"\0")).rstrip(b"\0").decode(errors="replace")
        finally:
            writer.close()
        if reply.endswith("OK"):
            return ScanResult("clean")
        if reply.endswith("FOUND"):
            return ScanResult("infected", reply.split(":", 1)[-1].replace("FOUND", "").strip()[:120])
        return ScanResult("unavailable", f"unexpected scanner reply: {reply[:60]}")


def make_scanner(s: Settings) -> Scanner:
    return ClamdScanner(s.clamd_host, s.clamd_port) if s.scanner_backend == "clamd" else NoScanner()
