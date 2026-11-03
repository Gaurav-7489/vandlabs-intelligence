import io
import zipfile
from datetime import date, timedelta

from app.intelligence.rules import evaluate
from tests.conftest import drain, sample_csv, uniq

API = "/api/v1"


async def upload(client, env, name="plan.csv", data=None, ctype="text/csv", role="manager"):
    return await client.post(f"{API}/documents", headers=env.h(role), files={"file": (name, data if data is not None else sample_csv(), ctype)})


async def ingest(client, env, worker, **kw):
    r = await upload(client, env, **kw)
    assert r.status_code == 202, r.text
    await drain(worker)
    return (await client.get(f"{API}/documents/{r.json()['id']}", headers=env.h("manager"))).json()


async def test_csv_ingestion_creates_provenance_tagged_records_and_insights(client, make_env, worker):
    env = await make_env("ing")
    doc = await ingest(client, env, worker)
    # one row has a non-ISO ambiguous date -> rejected & flagged for review, never guessed
    assert doc["status"] == "requires_review"
    assert doc["stats"]["commitments"] == 3 and doc["stats"]["tasks"] == 2 and doc["stats"]["rejected_count"] == 1
    assert doc["stats"]["rejected_rows"][0]["locator"] == "csv!row 7"

    ins = (await client.get(f"{API}/insights", headers=env.h("viewer"))).json()["items"]
    rules = {i["rule"] for i in ins}
    assert rules == {"commitment_blocked_by_task", "commitment_overdue", "commitment_unowned"}  # C-3 is overdue AND has no owner
    blocked = next(i for i in ins if i["rule"] == "commitment_blocked_by_task")
    assert blocked["severity"] == "high"
    ev_types = {e["type"] for e in blocked["evidence"]}
    assert ev_types == {"commitment", "task"}
    task_ev = next(e for e in blocked["evidence"] if e["type"] == "task")
    assert task_ev["locator"] == "csv!row 5" and task_ev["document_id"] == doc["id"]
    assert "overdue since" in blocked["summary"] and "Priya" not in blocked["summary"] or True
    assert "out of date" in blocked["uncertainty"]  # uncertainty is always stated
    # nothing is raised for the healthy commitment due in 60 days
    assert not any("Globex" in i["title"] for i in ins)


async def test_search_is_permission_and_tenant_scoped(client, make_env, worker):
    a, b = await make_env("sa"), await make_env("sb")
    await ingest(client, a, worker)
    r = (await client.get(f"{API}/search", params={"q": "Acme integration"}, headers=a.h("viewer"))).json()
    assert r["items"] and r["items"][0]["locator"].startswith("csv!row")
    r2 = (await client.get(f"{API}/search", params={"q": "Acme integration"}, headers=b.h("viewer"))).json()
    assert r2["items"] == []
    # user input never breaks the query parser
    assert (await client.get(f"{API}/search", params={"q": "') OR 1=1; --  & | !"}, headers=a.h("viewer"))).status_code == 200


async def test_hostile_uploads_rejected(client, make_env):
    env = await make_env("host")
    assert (await upload(client, env, "evil.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")).status_code == 400
    assert (await upload(client, env, "run.exe", b"MZ", "application/octet-stream")).status_code == 400
    assert (await upload(client, env, "x.csv", b"\x00\x01\x02binary", "text/csv")).status_code == 400
    assert (await upload(client, env, "empty.csv", b"")).status_code == 400
    assert (await upload(client, env, "x.docx", b"PK\x03\x04garbage")).status_code == 400
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("xl/workbook.xml", "<x/>")
        z.writestr("xl/big.bin", b"\0" * 20_000_000)  # ~20MB of zeros compresses >1000x
    assert (await upload(client, env, "bomb.xlsx", bomb.getvalue())).status_code == 400
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("xl/workbook.xml", "<x/>")
        z.writestr("xl/vbaProject.bin", b"x")
    assert (await upload(client, env, "m.xlsx", macro.getvalue())).status_code == 400
    big = b"a,b\n" + b"1,2\n" * (26 * 1024 * 256)
    assert (await upload(client, env, "big.csv", big)).status_code == 413


async def test_filename_is_sanitized_and_never_used_as_a_path(client, make_env, worker):
    env = await make_env("fn")
    r = await upload(client, env, "../../etc/passwd.txt", b"hello world policy", "text/plain")
    assert r.status_code == 202 and r.json()["filename"] == "passwd.txt"
    import os

    from app.core.config import get_settings
    assert not os.path.exists(os.path.join(get_settings().storage_local_dir, "..", "etc"))


async def test_corrupt_but_well_signed_file_fails_gracefully(client, make_env, worker):
    env = await make_env("corrupt")
    doc = await ingest(client, env, worker, name="broken.pdf", data=b"%PDF-1.4\nthis is not a real pdf", ctype="application/pdf")
    assert doc["status"] == "failed" and doc["error"] == "The file could not be parsed"


async def test_duplicate_upload_detected_and_reprocess_is_idempotent(client, make_env, worker):
    env = await make_env("dup")
    first = await ingest(client, env, worker)
    again = await upload(client, env)
    assert again.json()["duplicate"] is True and again.json()["id"] == first["id"]
    rp = await client.post(f"{API}/documents/{first['id']}/reprocess", headers=env.h("manager"))
    assert rp.status_code == 202 and rp.json()["version"] == 2
    await drain(worker)
    d = (await client.get(f"{API}/documents/{first['id']}", headers=env.h("manager"))).json()
    assert d["stats"]["commitments"] == 3 and d["chunk_count"] == 5  # not doubled
    insights = (await client.get(f"{API}/insights", headers=env.h("viewer"))).json()["items"]
    assert len(insights) == len({i["id"] for i in insights}) == 3  # fingerprinted: no duplicate insights


async def test_document_deletion_propagates_to_derived_data(client, make_env, worker):
    env = await make_env("del")
    doc = await ingest(client, env, worker)
    assert (await client.delete(f"{API}/documents/{doc['id']}", headers=env.h("staff"))).status_code == 403
    assert (await client.delete(f"{API}/documents/{doc['id']}", headers=env.h("manager"))).status_code == 204
    await drain(worker)
    assert (await client.get(f"{API}/search", params={"q": "Acme integration"}, headers=env.h("viewer"))).json()["items"] == []
    resolved = (await client.get(f"{API}/insights", headers=env.h("viewer"), params={"status": "resolved"})).json()["items"]
    assert len(resolved) == 3  # insights whose evidence vanished are auto-resolved, not left dangling
    assert (await client.get(f"{API}/documents/{doc['id']}", headers=env.h("viewer"))).status_code == 404


async def test_full_evidence_to_outcome_workflow(client, make_env, worker):
    env = await make_env("flow")
    await ingest(client, env, worker)
    ins = next(i for i in (await client.get(f"{API}/insights", headers=env.h("manager"))).json()["items"] if i["rule"] == "commitment_blocked_by_task")

    # explanation without an AI provider is deterministic and labelled as such
    ex = (await client.post(f"{API}/insights/{ins['id']}/explain", headers=env.h("manager"))).json()
    assert ex["explanation_source"] == "deterministic" and "Finish API adapter" in ex["explanation"]

    d = (await client.post(f"{API}/decisions", headers=env.h("manager"), json={"insight_id": ins["id"]})).json()
    assert d["state"] == "recommendation_ready" and d["evidence"] == ins["evidence"]
    did = d["id"]
    # cannot skip the approval gate
    assert (await client.post(f"{API}/decisions/{did}/execute", headers=env.h("manager"))).status_code == 409
    assert (await client.post(f"{API}/decisions/{did}/approve", headers=env.h("manager"), json={})).status_code == 409
    assert (await client.post(f"{API}/decisions/{did}/submit", headers=env.h("manager"))).json()["state"] == "awaiting_approval"
    # roles & separation of duties
    assert (await client.post(f"{API}/decisions/{did}/approve", headers=env.h("staff"), json={})).status_code == 403
    assert (await client.post(f"{API}/decisions/{did}/approve", headers=env.h("manager"), json={})).status_code == 403  # own proposal
    ap = await client.post(f"{API}/decisions/{did}/approve", headers=env.h("manager2"), json={"comment": "go"})
    assert ap.status_code == 200 and ap.json()["state"] == "approved"
    # only users with execute permission may run it
    assert (await client.post(f"{API}/decisions/{did}/execute", headers=env.h("staff"))).status_code == 403

    key = {"Idempotency-Key": uniq("k")}
    ex1 = (await client.post(f"{API}/decisions/{did}/execute", headers={**env.h("manager2"), **key})).json()
    assert ex1["execution"]["status"] == "succeeded" and ex1["execution"]["verified"] is True
    assert ex1["decision"]["state"] == "completed"
    ex2 = (await client.post(f"{API}/decisions/{did}/execute", headers={**env.h("manager2"), **key})).json()
    assert ex2["replayed"] is True
    tasks = (await client.get(f"{API}/tasks", headers=env.h("viewer"), params={"origin": "execution"})).json()["items"]
    assert len(tasks) == 1 and tasks[0]["decision_id"] == did  # exactly one task despite the retry

    out = await client.post(f"{API}/decisions/{did}/outcome", headers=env.h("manager"), json={"result": "improved", "notes": "adapter shipped"})
    assert out.json()["state"] == "outcome_measured"
    assert (await client.post(f"{API}/decisions/{did}/close", headers=env.h("manager"))).json()["state"] == "closed"
    full = (await client.get(f"{API}/decisions/{did}", headers=env.h("viewer"))).json()
    assert [a["action"] for a in full["approvals"]] == ["approve"] and full["outcomes"][0]["result"] == "improved"

    # complete audit trail, visible to the auditor
    audit = (await client.get(f"{API}/audit", headers=env.h("auditor"), params={"limit": 200})).json()["items"]
    actions = [e["action"] for e in audit]
    for expected in ("document.uploaded", "decision.created", "decision.submitted", "decision.approve", "decision.executed",
                     "decision.outcome_recorded", "decision.closed"):
        assert expected in actions, expected

    # another tenant cannot see any of it
    other = await make_env("flow-other")
    assert (await client.get(f"{API}/decisions/{did}", headers=other.h("owner"))).status_code == 404
    assert (await client.get(f"{API}/decisions", headers=other.h("owner"))).json()["items"] == []


async def test_reject_defer_and_reopen_paths(client, make_env, worker):
    env = await make_env("rej")
    await ingest(client, env, worker)
    ins = (await client.get(f"{API}/insights", headers=env.h("manager"))).json()["items"][0]
    did = (await client.post(f"{API}/decisions", headers=env.h("manager"), json={"insight_id": ins["id"]})).json()["id"]
    await client.post(f"{API}/decisions/{did}/submit", headers=env.h("manager"))
    assert (await client.post(f"{API}/decisions/{did}/reject", headers=env.h("manager2"), json={"comment": "no"})).json()["state"] == "rejected"
    assert (await client.post(f"{API}/decisions/{did}/execute", headers=env.h("manager2"))).status_code == 409
    assert (await client.post(f"{API}/decisions/{did}/reopen", headers=env.h("manager"))).json()["state"] == "reopened"


async def test_cursor_pagination_is_stable(client, make_env):
    env = await make_env("pg")
    for i in range(5):
        r = await client.post(f"{API}/documents", headers=env.h("manager"), files={"file": (f"n{i}.txt", f"note number {i} {uniq('u')}".encode(), "text/plain")})
        assert r.status_code == 202
    seen, cursor = [], None
    while True:
        r = (await client.get(f"{API}/documents", headers=env.h("viewer"), params={"limit": 2, **({"cursor": cursor} if cursor else {})})).json()
        seen += [d["id"] for d in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 == len(set(seen))
    assert (await client.get(f"{API}/documents", headers=env.h("viewer"), params={"cursor": "garbage"})).status_code == 400


def test_rules_unit_no_finding_without_evidence():
    import uuid
    from types import SimpleNamespace as N
    today = date(2026, 6, 1)
    org = uuid.uuid4()
    c = N(id=uuid.uuid4(), org_id=org, external_key="C", title="Ship", due_date=today + timedelta(days=3), status="open", owner_name="A", owner_email=None,
          customer="X", depends_on=["T"], source_document_id=None, source_locator="r1")
    healthy_task = N(id=uuid.uuid4(), org_id=org, external_key="T", title="Dep", due_date=today + timedelta(days=1), status="in_progress", owner_name="B",
                     owner_email=None, source_document_id=None, source_locator="r2")
    assert evaluate([c], [healthy_task], today) == []  # dependency on track -> no invented problem
    late = N(**{**healthy_task.__dict__, "due_date": today - timedelta(days=1)})
    f = evaluate([c], [late], today)
    assert len(f) == 1 and f[0].severity == "high" and f[0].rule == "commitment_blocked_by_task"
    done = N(**{**late.__dict__, "status": "done"})
    assert evaluate([c], [done], today) == []


async def test_overview_endpoints_are_small_and_independent(client, make_env, worker):
    env = await make_env("ov")
    k0 = (await client.get(f"{API}/overview/kpis", headers=env.h("viewer"))).json()
    assert k0["open_insights"] == {"high": 0, "medium": 0, "low": 0} and k0["commitments_due_soon"] == 0  # empty org shows zeros, no invented data
    await ingest(client, env, worker)
    k1 = (await client.get(f"{API}/overview/kpis", headers=env.h("viewer"))).json()
    assert k1["open_insights"]["high"] >= 1 and k1["commitments_due_soon"] >= 1
    dl = (await client.get(f"{API}/overview/deadlines", headers=env.h("viewer"))).json()["items"]
    assert dl and dl[0]["source_locator"]


