"""Child process: reads file bytes on stdin, writes parsed JSON on stdout. Exit codes: 0 ok, 3 resource limit, 1 parse error."""
import os
import resource
import socket
import sys


def _lock_down(cpu: int, mem_mb: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _block_network() -> None:
    def _blocked(*a: object, **k: object) -> None:
        raise OSError("network disabled in parser sandbox")
    socket.socket = _blocked  # type: ignore[misc,assignment]  # belt and braces in addition to the empty network namespace
    socket.create_connection = _blocked  # type: ignore[assignment]


def main() -> int:
    kind, cpu, mem = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    data = sys.stdin.buffer.read()
    _lock_down(cpu, mem)  # limits first so imports are bounded too
    try:
        if kind != "__netprobe__":  # import everything BEFORE blocking sockets (ssl & friends subclass socket.socket)
            import docx  # noqa: F401
            import openpyxl  # noqa: F401
            import pypdf  # noqa: F401

            from app.core.config import Settings
            from app.ingestion.parsers import ParseLimitExceeded, parse
            from app.ingestion.sandbox import encode
        _block_network()
        if kind == "__netprobe__":  # test hook: prove the sandbox cannot open network connections
            try:
                socket.create_connection(("127.0.0.1", 9), 1)
                return 0
            except OSError:
                sys.stdout.write("blocked")
                return 0
        try:
            sys.stdout.buffer.write(encode(parse(kind, data, Settings())))
        except ParseLimitExceeded:
            return 3
        return 0
    except MemoryError:
        return 3
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"{type(e).__name__}\n")  # exception TYPE only (never content) for operator diagnostics
        return 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
