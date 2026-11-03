"""Small, controlled local benchmark (dev auth). Reports measured latencies only; not a capacity claim."""
import asyncio
import statistics as st
import time

import httpx

API = "http://localhost:8000/api/v1"
USERS = ["owner@northwind-demo.example.com", "manager@northwind-demo.example.com", "approver@northwind-demo.example.com", "staff@northwind-demo.example.com"]


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        heads = []
        for u in USERS:
            t = (await c.post(f"{API}/auth/dev-token", json={"email": u, "mfa": True})).json()["access_token"]
            me = (await c.get(f"{API}/me", headers={"Authorization": f"Bearer {t}"})).json()
            heads.append({"Authorization": f"Bearer {t}", "X-Org-ID": me["memberships"][0]["org_id"]})
        for path, per_user in (("/overview/kpis", 90), ("/insights?limit=20", 90), ("/search?q=Acme", 15)):
            lat: list[float] = []
            codes: dict[int, int] = {}
            sem = asyncio.Semaphore(16)

            async def one(h: dict[str, str]) -> None:
                async with sem:
                    t0 = time.perf_counter()
                    r = await c.get(API + path, headers=h)
                    lat.append((time.perf_counter() - t0) * 1000)
                    codes[r.status_code] = codes.get(r.status_code, 0) + 1
            t0 = time.perf_counter()
            await asyncio.gather(*(one(h) for h in heads for _ in range(per_user)))
            wall = time.perf_counter() - t0
            lat.sort()
            print(f"{path:22s} n={len(lat)} conc=16 p50={lat[len(lat)//2]:.1f}ms p95={lat[int(len(lat)*.95)]:.1f}ms max={lat[-1]:.1f}ms "
                  f"rps={len(lat)/wall:.0f} status={codes} mean={st.mean(lat):.1f}ms")


asyncio.run(main())
