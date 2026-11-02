"""Private object storage. Keys are server-generated; user-supplied names are never used as paths."""
import asyncio
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class Storage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


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
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


class S3Storage:
    """S3-compatible (Cloudflare R2). NOT yet verified against a live bucket in this repository's CI."""

    def __init__(self, s: Settings):
        import boto3  # lazy: optional dependency
        self.bucket = s.s3_bucket
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint_url or None, aws_access_key_id=s.s3_access_key_id,
                                   aws_secret_access_key=s.s3_secret_access_key, region_name="auto")

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return await asyncio.to_thread(obj["Body"].read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


def make_storage(s: Settings) -> Storage:
    return S3Storage(s) if s.storage_backend == "s3" else LocalStorage(s.storage_local_dir)
