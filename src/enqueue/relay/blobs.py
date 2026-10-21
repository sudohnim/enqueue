"""Where the hosted relay keeps object bytes: Cloudflare R2, through its S3 API.

The relay's SQLite file keeps the index (names, cursors, sizes, libraries); with R2
configured the bytes themselves live in a bucket, so a library can hold far more than
the Railway volume. A self-hosted relay sets none of this and keeps its bytes in the
SQLite file as before.

Every object is already sealed and padded on the device, so R2 holds ciphertext under
keys that are hashes; it learns sizes and timing, as the relay does.

R2 is on only when all four of `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY` and `R2_BUCKET` are set. Some but not all is refused at start,
so a typo never quietly fills the volume instead.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Protocol

log = logging.getLogger("enqueue.relay.blobs")

R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


class BlobStoreError(Exception):
    """The blob store could not be reached or refused the request."""


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> int: ...


class R2BlobStore:
    """Objects in one R2 bucket. boto3's client is thread-safe; one is shared."""

    def __init__(self, bucket: str, client) -> None:
        self.bucket = bucket
        self._client = client

    @classmethod
    def connect(cls, account_id: str, access_key: str, secret_key: str, bucket: str):
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
                max_pool_connections=32,
                # Integrity comes from Content-MD5, which R2 checks on every PUT; the
                # newer default checksum headers are not needed on top of it.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        return cls(bucket, client)

    def _call(self, what: str, fn, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return fn(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                return None
            raise BlobStoreError(f"blob store {what} failed: {code or exc}") from exc
        except BotoCoreError as exc:
            raise BlobStoreError(f"blob store {what} failed: {exc}") from exc

    def put(self, key: str, data: bytes) -> None:
        md5 = base64.b64encode(hashlib.md5(data).digest()).decode()  # noqa: S324 - integrity
        self._call(
            "put",
            self._client.put_object,
            Key=key,
            Body=data,
            ContentMD5=md5,
            ContentType="application/octet-stream",
        )

    def get(self, key: str) -> bytes | None:
        res = self._call("get", self._client.get_object, Key=key)
        if res is None:
            return None
        try:
            return res["Body"].read()
        except Exception as exc:  # noqa: BLE001 - a cut connection mid-body
            raise BlobStoreError(f"blob store get failed: {exc}") from exc

    def delete(self, key: str) -> None:
        self._call("delete", self._client.delete_object, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under `prefix`, a page of up to 1000 at a time."""
        gone = 0
        token = None
        while True:
            extra = {"ContinuationToken": token} if token else {}
            page = self._call("list", self._client.list_objects_v2, Prefix=prefix, **extra) or {}
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                res = self._call(
                    "delete",
                    self._client.delete_objects,
                    Delete={"Objects": keys, "Quiet": True},
                )
                errors = (res or {}).get("Errors") or []
                if errors:
                    raise BlobStoreError(f"blob store delete failed for {len(errors)} objects")
                gone += len(keys)
            if not page.get("IsTruncated"):
                return gone
            token = page.get("NextContinuationToken")


def from_env() -> BlobStore | None:
    """R2 when all four R2_* variables are set, None when none is; else refuse."""
    values = {name: os.getenv(name, "").strip() for name in R2_VARS}
    if not any(values.values()):
        return None
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"R2 is half configured: set {', '.join(missing)} too, or none")
    log.info("relay object bytes go to R2 bucket %s", values["R2_BUCKET"])
    return R2BlobStore.connect(
        values["R2_ACCOUNT_ID"],
        values["R2_ACCESS_KEY_ID"],
        values["R2_SECRET_ACCESS_KEY"],
        values["R2_BUCKET"],
    )
