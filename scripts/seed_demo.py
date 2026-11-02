"""Seeds TWO SYNTHETIC demo organizations through the real API (local/dev auth mode only).

All names, people and figures are fictional. Never run against a real client environment.
Usage: python scripts/seed_demo.py [--api http://localhost:8000] [--admin platform@vandlabs.example.com]
Prereq: `python -m app.cli create-platform-admin <admin email>` (from services/api).
"""
import argparse
from datetime import date, timedelta

import httpx

ORGS = [
    {"name": "Northwind Demo Co (synthetic)", "slug": "northwind-demo", "owner": "owner@northwind-demo.example.com",
     "members": {"manager@northwind-demo.example.com": "manager", "approver@northwind-demo.example.com": "manager", "staff@northwind-demo.example.com": "staff"},
     "plan": "Acme"},
    {"name": "Harbor Logistics Demo (synthetic)", "slug": "harbor-demo", "owner": "owner@harbor-demo.example.com",
     "members": {"manager@harbor-demo.example.com": "manager", "approver@harbor-demo.example.com": "manager"}, "plan": "Beacon"},
]


def plan_csv(customer: str, today: date) -> bytes:
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    rows = ["type,id,title,customer,owner,owner email,due date,status,depends on",
            f"commitment,C-1,Deliver {customer} integration,{customer} Ltd,Priya Shah,priya@demo.example.com,{d(5)},in progress,T-1",
            f"commitment,C-2,Quarterly report for {customer},{customer} Ltd,Sam Lee,sam@demo.example.com,{d(60)},open,",
            f"commitment,C-3,Legacy migration for {customer},{customer} Ltd,,,{d(-3)},open,",
            f"task,T-1,Finish API adapter,,Dev Rao,dev@demo.example.com,{d(-4)},in progress,",
            f"task,T-2,Prepare reporting data,,Sam Lee,sam@demo.example.com,{d(30)},todo,"]
    return ("\n".join(rows) + "\n").encode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--admin", default="platform@vandlabs.example.com")
    a = ap.parse_args()
    c = httpx.Client(base_url=f"{a.api}/api/v1", timeout=30)

    def tok(email: str) -> dict[str, str]:
        r = c.post("/auth/dev-token", json={"email": email, "mfa": True})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    for o in ORGS:
        r = c.post("/platform/organizations", headers=tok(a.admin), json={"name": o["name"], "slug": o["slug"], "owner_email": o["owner"]})
        if r.status_code == 409:
            print(f"exists: {o['slug']}")
            continue
        r.raise_for_status()
        org = r.json()["id"]
        h = {**tok(o["owner"]), "X-Org-ID": org}
        for email, role in o["members"].items():
            c.post("/members", headers=h, json={"email": email, "role": role}).raise_for_status()
        mh = {**tok(f"manager@{o['slug']}.example.com"), "X-Org-ID": org}
        c.post("/documents", headers=mh, files={"file": (f"{o['slug']}-commitments.csv", plan_csv(o["plan"], date.today()), "text/csv")}).raise_for_status()
        print(f"seeded {o['slug']} ({org}); run the worker to ingest")


if __name__ == "__main__":
    main()
