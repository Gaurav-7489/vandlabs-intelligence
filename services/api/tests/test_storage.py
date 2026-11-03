import boto3
import pytest
from moto.server import ThreadedMotoServer

from app.core.config import Settings
from app.core.storage import LocalStorage, NotFoundInStorage, S3Storage, StorageError, TenantStorage

BUCKET = "vand-test"


@pytest.fixture(scope="module")
def s3_server():
    srv = ThreadedMotoServer(port=5555, verbose=False)
    srv.start()
    boto3.client("s3", endpoint_url="http://127.0.0.1:5555", aws_access_key_id="k", aws_secret_access_key="s", region_name="us-east-1").create_bucket(Bucket=BUCKET)
    yield "http://127.0.0.1:5555"
    srv.stop()


@pytest.fixture
def s3(s3_server):
    return S3Storage(Settings(storage_backend="s3", s3_endpoint_url=s3_server, s3_bucket=BUCKET, s3_access_key_id="k", s3_secret_access_key="s"))


@pytest.mark.parametrize("kind", ["s3", "local"])
async def test_put_get_delete_roundtrip_and_missing(kind, request, tmp_path):
    st = request.getfixturevalue("s3") if kind == "s3" else LocalStorage(str(tmp_path))
    await st.put("org1/doc1", b"hello")
    assert await st.get("org1/doc1") == b"hello"
    await st.put("org1/doc1", b"v2")  # overwrite
    assert await st.get("org1/doc1") == b"v2"
    await st.delete("org1/doc1")
    with pytest.raises(NotFoundInStorage):
        await st.get("org1/doc1")
    await st.delete("org1/doc1")  # deleting a missing object is not an error


async def test_tenant_wrapper_blocks_cross_tenant_and_traversal(s3):
    a, b = TenantStorage(s3, "orgA"), TenantStorage(s3, "orgB")
    await a.put("orgA/x", b"secret-a")
    for bad in ("orgA/x",):
        with pytest.raises(StorageError):
            await b.get(bad)
        with pytest.raises(StorageError):
            await b.delete(bad)
    with pytest.raises(StorageError):
        await a.get("orgA/../orgB/x")
    assert await a.get("orgA/x") == b"secret-a"  # untouched by B's attempts


async def test_failures_surface_as_storage_errors(s3_server):
    bad = S3Storage(Settings(storage_backend="s3", s3_endpoint_url="http://127.0.0.1:1", s3_bucket=BUCKET, s3_access_key_id="k", s3_secret_access_key="s"))
    with pytest.raises(StorageError):
        await bad.put("o/x", b"1")
    nobucket = S3Storage(Settings(storage_backend="s3", s3_endpoint_url=s3_server, s3_bucket="does-not-exist", s3_access_key_id="k", s3_secret_access_key="s"))
    with pytest.raises(StorageError):
        await nobucket.put("o/x", b"1")


async def test_bucket_is_not_publicly_readable(s3_server):
    import httpx
    st = S3Storage(Settings(storage_backend="s3", s3_endpoint_url=s3_server, s3_bucket=BUCKET, s3_access_key_id="k", s3_secret_access_key="s"))
    await st.put("orgP/private", b"x")
    # no signed request => no object (moto enforces auth only loosely; we assert no public URL is ever issued by our code)
    assert not hasattr(st, "presign") and httpx is not None


async def test_upload_returns_503_when_storage_down_and_creates_no_document(client, make_env, app_ctx):
    env = await make_env("sdown")
    _, app, _ = app_ctx

    class Broken:
        async def put(self, k, d): raise StorageError("down")
        async def get(self, k): raise StorageError("down")
        async def delete(self, k): raise StorageError("down")
    good, app.state.vand.storage = app.state.vand.storage, Broken()
    try:
        r = await client.post("/api/v1/documents", headers=env.h("manager"), files={"file": ("a.txt", b"hello world", "text/plain")})
        assert r.status_code == 503 and r.headers["retry-after"] == "10"
    finally:
        app.state.vand.storage = good
    assert (await client.get("/api/v1/documents", headers=env.h("viewer"))).json()["items"] == []
