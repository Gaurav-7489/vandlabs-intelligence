import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path

import jwt
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

PG = "localhost:5432/vand_test"
os.environ.update({
    "VAND_ENV": "test", "VAND_AUTH_MODE": "dev",
    "VAND_DATABASE_URL": f"postgresql+asyncpg://vand_app:dev_app_pw@{PG}",
    "VAND_WORKER_DATABASE_URL": f"postgresql+asyncpg://vand_worker:dev_worker_pw@{PG}",
    "VAND_MIGRATION_DATABASE_URL": f"postgresql+psycopg://vand_owner:dev_owner_pw@{PG}",
    "VAND_REDIS_URL": "redis://localhost:6379/15", "VAND_STORAGE_LOCAL_DIR": "/tmp/vand-test-objects",
    "VAND_ANTHROPIC_API_KEY": "", "VAND_OPENAI_API_KEY": ""})

from app.ai.gateway import AIGateway, Completion  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.db import Database, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.worker import Worker  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated() -> None:
    get_settings.cache_clear()
    eng = create_engine(os.environ["VAND_MIGRATION_DATABASE_URL"], isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, check=True)


@pytest.fixture
def owner_sql():
    eng = create_engine(os.environ["VAND_MIGRATION_DATABASE_URL"])
    with eng.begin() as c:
        yield c


@pytest.fixture
def admin_sql():
    """Superuser connection for privileged-invariant tests. CI sets VAND_TEST_ADMIN_URL (postgres service container superuser);
    locally falls back to `su postgres`. Skips only when neither is available."""
    url = os.environ.get("VAND_TEST_ADMIN_URL")
    if url:
        eng = create_engine(url, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            yield lambda sql: c.execute(text(sql))
        return
    import shutil
    import subprocess
    if shutil.which("su") is None or subprocess.run(["su", "postgres", "-c", "true"], capture_output=True).returncode != 0:
        pytest.skip("no superuser access (set VAND_TEST_ADMIN_URL)")

    def run(sql: str):
        r = subprocess.run(["su", "postgres", "-c", f"psql -d vand_test -v ON_ERROR_STOP=1 -c \"{sql}\""], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode()[:200])
    yield run


@pytest.fixture
def worker_sql():
    """Sync connection as the worker role (the only role with cross-tenant visibility, and only on `jobs`)."""
    eng = create_engine(os.environ["VAND_WORKER_DATABASE_URL"].replace("+asyncpg", "+psycopg"))
    with eng.begin() as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _flush_redis() -> None:
    r = aioredis.from_url(os.environ["VAND_REDIS_URL"])
    await r.flushdb()
    await r.aclose()


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self) -> None:
        self.calls = 0
        self.reply: str = "{}"
        self.tokens = (100, 50)

    async def complete(self, system: str, user: str, max_tokens: int, timeout: float) -> Completion:
        self.calls += 1
        return Completion(self.reply, self.name, self.model, *self.tokens)


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest_asyncio.fixture
async def app_ctx(fake: FakeProvider):
    s = Settings()
    gateway = AIGateway(s, providers=[])
    app = create_app(s, ai=gateway)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            gateway.fake = fake  # type: ignore[attr-defined]
            yield client, app, gateway


@pytest.fixture
def client(app_ctx):
    return app_ctx[0]


@pytest.fixture
def gateway(app_ctx):
    return app_ctx[2]


@pytest_asyncio.fixture
async def worker() -> AsyncIterator[Worker]:
    w = Worker(db=Database(make_engine(get_settings().worker_database_url)))
    yield w
    await w.db.dispose()


async def drain(w: Worker, limit: int = 50) -> int:
    n = 0
    while n < limit and await w.run_one():
        n += 1
    return n


def token(email: str, mfa: bool = True, sub: str | None = None, verified: bool = True, exp_delta: int = 3600) -> str:
    import time
    payload = {"sub": sub or f"sub-{email}", "email": email, "email_verified": verified, "aud": "vand-dev",
               "exp": int(time.time()) + exp_delta, "amr": ["pwd", "mfa"] if mfa else ["pwd"]}
    return jwt.encode(payload, get_settings().dev_jwt_secret, algorithm="HS256")


def hdr(email: str, org: str | None = None, mfa: bool = True) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token(email, mfa)}"}
    if org:
        h["X-Org-ID"] = org
    return h


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Env:
    """A provisioned organization with one user per role."""

    def __init__(self, client: AsyncClient, org_id: str, users: dict[str, str]):
        self.client, self.org_id, self.users = client, org_id, users

    def h(self, role: str, mfa: bool = True) -> dict[str, str]:
        return hdr(self.users[role], self.org_id, mfa)


@pytest.fixture
def make_env(client, owner_sql):
    async def _make(name: str = "org") -> Env:
        admin = f"{uniq('platform')}@vand.example.com"
        owner_sql.execute(text("INSERT INTO users (email, is_platform_admin) VALUES (:e, true)"), {"e": admin})
        owner_sql.connection.commit()
        slug = uniq(name)
        users = {r: f"{uniq(r)}@{slug}.example.com" for r in ("owner", "admin", "manager", "manager2", "staff", "viewer", "auditor")}
        r = await client.post("/api/v1/platform/organizations", headers=hdr(admin), json={"name": name.title(), "slug": slug, "owner_email": users["owner"]})
        assert r.status_code == 201, r.text
        org_id = r.json()["id"]
        for role, email in users.items():
            if role == "owner":
                continue
            real = "manager" if role == "manager2" else role
            rr = await client.post("/api/v1/members", headers=hdr(users["owner"], org_id), json={"email": email, "role": real})
            assert rr.status_code == 201, rr.text
        return Env(client, org_id, users)
    return _make


def sample_csv(today: date | None = None) -> bytes:
    """Commitment due in 5 days depends on an overdue task -> must produce a HIGH 'blocked' insight."""
    today = today or date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
    rows = [
        "type,id,title,customer,owner,owner email,due date,status,depends on",
        f"commitment,C-1,Deliver Acme integration,Acme Corp,Priya Shah,priya@x.example.com,{d(5)},in progress,T-1",
        f"commitment,C-2,Quarterly report to Globex,Globex,Sam Lee,sam@x.example.com,{d(60)},open,",
        f"commitment,C-3,Legacy migration for Initech,Initech,,,{d(-3)},open,",
        f"task,T-1,Finish API adapter,,Dev Rao,dev@x.example.com,{d(-4)},in progress,",
        f"task,T-2,Prepare Globex data,,Sam Lee,sam@x.example.com,{d(30)},todo,",
        "task,T-3,Bad date row,,Sam Lee,sam@x.example.com,03/04/2026,todo,",
    ]
    return ("\n".join(rows) + "\n").encode()
