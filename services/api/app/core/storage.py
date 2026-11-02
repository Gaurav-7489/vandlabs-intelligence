"""Private object storage. Keys are server-generated; user-supplied names are never used as paths."""
import asyncio
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings


class Storage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class StorageError(Exception):
    pass


class NotFoundInStorage(StorageError):
    pass


class TenantStorage:
    """Wraps any Storage and refuses keys outside `<org_id>/`: defense in depth on top of DB-level authorization."""

    def __init__(self, inner: "Storage", org_id: object):
        self.inner, self.prefix = inner, f"{org_id}/"

    def _ok(self, key: str) -> str:
        if not key.startswith(self.prefix) or ".." in key:
            raise StorageError("key outside tenant scope")
        return key

    async def put(self, key: str, data: bytes) -> None:
        await self.inner.put(self._ok(key), data)

    async def get(self, key: str) -> bytes:
        return await self.inner.get(self._ok(key))

    async def delete(self, key: str) -> None:
        await self.inner.delete(self._ok(key))


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # path traversal guard
            raise ValueError("invalid storage key")
        return p

    async def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError:
            raise NotFoundInStorage(key) from None

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


class S3Storage:
    """S3-compatible storage (Cloudflare R2 in staging/production). Verified at protocol level against a moto S3 server;
    NOT yet verified against a real R2 bucket. Retries/timeouts are bounded; the bucket must be private."""

    def __init__(self, s: Settings, client: Any = None):
        import boto3  # lazy: optional dependency
        from botocore.config import Config
        self.bucket = s.s3_bucket
        self.client = client or boto3.client(
            "s3", endpoint_url=s.s3_endpoint_url or None, aws_access_key_id=s.s3_access_key_id, aws_secret_access_key=s.s3_secret_access_key,
            region_name="auto", config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=30))

    async def put(self, key: str, data: bytes) -> None:
        try:
            await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"put failed: {type(e).__name__}") from None

    async def get(self, key: str) -> bytes:
        try:
            obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
            return await asyncio.to_thread(obj["Body"].read)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "response", {}).get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFoundInStorage(key) from None
            raise StorageError(f"get failed: {type(e).__name__}") from None

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"delete failed: {type(e).__name__}") from None


def make_storage(s: Settings) -> Storage:
    return S3Storage(s) if s.storage_backend == "s3" else LocalStorage(s.storage_local_dir)
