"""Fails if the production (runtime) lock pins any package at a version different from the CI-tested lock.
Prevents shipping dependency versions that the test suite never ran against."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "services" / "api"


def pins(name: str) -> dict[str, str]:
    out = {}
    for line in (root / name).read_text().splitlines():
        if "==" in line and not line.startswith("#"):
            k, v = line.split("==", 1)
            out[k.strip().lower().replace("_", "-")] = v.strip()
    return out


runtime, tested = pins("requirements.runtime.lock.txt"), pins("requirements.lock.txt")
bad = {k: (v, tested.get(k)) for k, v in runtime.items() if tested.get(k) != v}
if bad:
    print("runtime lock differs from tested lock:", bad)
    sys.exit(1)
print(f"ok: {len(runtime)} runtime pins all match the tested lock")
