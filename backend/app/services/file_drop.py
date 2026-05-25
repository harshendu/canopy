"""Watched shared storage for file-drop ingest (Phase 4).

canopy can poll a shared location for export files and ingest them through `file_ingest`. The
layout is `<root>/<connection_id>/*.{json,csv}`; a processed file is moved to a `processed/`
sibling (or `failed/` with an `.error` note) so the poll is idempotent without a tracking table.

Two backends, chosen by config (`FILE_DROP_BACKEND`): `local` (a directory — always available)
and `s3` (a bucket — needs the optional `[s3]` extra / boto3). The poll is disabled when no
backend is configured; the upload endpoint works regardless.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.integration import Connection
from app.services import file_ingest

_DATA_EXTS = (".json", ".csv")


@dataclass(frozen=True)
class DropFile:
    connection_id: int
    name: str  # base filename
    key: str  # backend-specific locator (absolute path / S3 key)


class DropStorage(ABC):
    @abstractmethod
    def list_pending(self) -> list[DropFile]: ...

    @abstractmethod
    def read(self, drop: DropFile) -> bytes: ...

    @abstractmethod
    def mark_processed(self, drop: DropFile) -> None: ...

    @abstractmethod
    def mark_failed(self, drop: DropFile, error: str) -> None: ...


class LocalDropStorage(DropStorage):
    def __init__(self, root: Path) -> None:
        self.root = root

    def list_pending(self) -> list[DropFile]:
        drops: list[DropFile] = []
        if not self.root.is_dir():
            return drops
        for sub in sorted(self.root.iterdir()):
            if not (sub.is_dir() and sub.name.isdigit()):
                continue
            for path in sorted(sub.iterdir()):
                # Only files directly in the connection dir; processed/ & failed/ are subdirs.
                if path.is_file() and path.suffix.lower() in _DATA_EXTS:
                    drops.append(DropFile(int(sub.name), path.name, str(path)))
        return drops

    def read(self, drop: DropFile) -> bytes:
        return Path(drop.key).read_bytes()

    def _move(self, drop: DropFile, subdir: str) -> Path:
        dest_dir = Path(drop.key).parent / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / drop.name
        Path(drop.key).replace(dest)
        return dest

    def mark_processed(self, drop: DropFile) -> None:
        self._move(drop, "processed")

    def mark_failed(self, drop: DropFile, error: str) -> None:
        dest = self._move(drop, "failed")
        dest.with_suffix(dest.suffix + ".error").write_text(error[:2000])


class _S3Like(Protocol):
    def list_objects(self, bucket: str, prefix: str) -> list[str]: ...
    def get(self, bucket: str, key: str) -> bytes: ...
    def move(self, bucket: str, src: str, dst: str) -> None: ...
    def put(self, bucket: str, key: str, data: bytes) -> None: ...


class S3DropStorage(DropStorage):
    def __init__(self, bucket: str, prefix: str, client: _S3Like) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = client

    def list_pending(self) -> list[DropFile]:
        drops: list[DropFile] = []
        for key in self.client.list_objects(self.bucket, f"{self.prefix}/"):
            rel = key[len(self.prefix) + 1 :]
            parts = rel.split("/")
            # Exactly <connection_id>/<file> — anything deeper is processed/ or failed/.
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            if not parts[1].lower().endswith(_DATA_EXTS):
                continue
            drops.append(DropFile(int(parts[0]), parts[1], key))
        return drops

    def read(self, drop: DropFile) -> bytes:
        return self.client.get(self.bucket, drop.key)

    def mark_processed(self, drop: DropFile) -> None:
        self.client.move(
            self.bucket, drop.key, f"{self.prefix}/{drop.connection_id}/processed/{drop.name}"
        )

    def mark_failed(self, drop: DropFile, error: str) -> None:
        base = f"{self.prefix}/{drop.connection_id}/failed/{drop.name}"
        self.client.move(self.bucket, drop.key, base)
        self.client.put(self.bucket, f"{base}.error", error[:2000].encode())


class _Boto3S3:
    """Adapts a boto3 S3 client to `_S3Like` (kept thin so `S3DropStorage` stays testable)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def list_objects(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            keys.extend(obj["Key"] for obj in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return keys

    def get(self, bucket: str, key: str) -> bytes:
        return bytes(self._client.get_object(Bucket=bucket, Key=key)["Body"].read())

    def move(self, bucket: str, src: str, dst: str) -> None:
        self._client.copy_object(Bucket=bucket, CopySource={"Bucket": bucket, "Key": src}, Key=dst)
        self._client.delete_object(Bucket=bucket, Key=src)

    def put(self, bucket: str, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=bucket, Key=key, Body=data)


def get_drop_storage() -> DropStorage | None:
    """The configured drop backend, or None when file-drop polling is disabled."""
    backend = settings.FILE_DROP_BACKEND.lower()
    if backend == "local":
        if not settings.FILE_DROP_LOCAL_DIR:
            return None
        return LocalDropStorage(Path(settings.FILE_DROP_LOCAL_DIR))
    if backend == "s3":
        if not settings.FILE_DROP_S3_BUCKET:
            return None
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on the [s3] extra
            raise RuntimeError("FILE_DROP_BACKEND=s3 requires the [s3] extra (boto3)") from exc
        return S3DropStorage(
            settings.FILE_DROP_S3_BUCKET, settings.FILE_DROP_S3_PREFIX, _Boto3S3(boto3.client("s3"))
        )
    return None


async def process_drops(session: AsyncSession, storage: DropStorage) -> dict[str, dict]:
    """Ingest every pending dropped file, moving each to processed/ or failed/. Idempotent: the
    ingest itself dedups via ExternalRef, and processed files are moved out of the pending set."""
    summary: dict[str, dict] = {}
    for drop in storage.list_pending():
        connection = await session.get(Connection, drop.connection_id)
        if connection is None:
            storage.mark_failed(drop, f"unknown connection {drop.connection_id}")
            summary[drop.name] = {"error": "unknown connection"}
            continue
        try:
            data = storage.read(drop)
            result = await file_ingest.ingest_file(session, connection, drop.name, data)
            storage.mark_processed(drop)
            summary[drop.name] = {
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
            }
        except Exception as exc:  # one bad file shouldn't stall the rest
            storage.mark_failed(drop, str(exc))
            summary[drop.name] = {"error": str(exc)}
    return summary
