"""Lock and ownership operations built on metadata CAS."""

from __future__ import annotations

from datetime import timedelta

from src.kernel.metadata import SQLiteMetadataStore
from src.kernel.models import CasConflict, FileMeta, FileState, LockDenied, utcnow


class LockClient:
    """CAS-based distributed lock client.

    All lock operations are atomic CAS updates on the metadata store.
    No central lock service required.
    """

    def __init__(self, store: SQLiteMetadataStore, node_id: str, lease_seconds: float = 30.0) -> None:
        self.store = store
        self.node_id = node_id
        self.lease = timedelta(seconds=lease_seconds)

    def acquire_read(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.state == FileState.ARCHIVED or meta.write_holder is not None:
            raise LockDenied(f"read lock denied for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {"read_count": meta.read_count + 1},
            "write_holder IS NULL AND state != ?",
            (FileState.ARCHIVED.value,),
        )

    def release_read(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.read_count <= 0:
            raise LockDenied(f"no read lock to release for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {"read_count": meta.read_count - 1},
            "read_count > 0",
        )

    def acquire_write(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.owner_id != self.node_id:
            raise LockDenied(f"{self.node_id} does not own {file_id}")
        if meta.state != FileState.CREATED or meta.write_holder is not None or meta.read_count != 0:
            raise LockDenied(f"write lock denied for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {
                "write_holder": self.node_id,
                "state": FileState.PROCESSING,
                "lease_expire": utcnow() + self.lease,
            },
            "owner_id = ? AND write_holder IS NULL AND read_count = 0 AND state = ?",
            (self.node_id, FileState.CREATED.value),
        )

    def release_write(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.write_holder != self.node_id:
            raise LockDenied(f"{self.node_id} does not hold write lock for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {
                "write_holder": None,
                "state": FileState.CREATED,
                "lease_expire": None,
            },
            "write_holder = ?",
            (self.node_id,),
        )

    def transfer_ownership(self, file_id: str, new_owner_id: str | None) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.owner_id != self.node_id:
            raise LockDenied(f"{self.node_id} does not own {file_id}")
        if meta.write_holder is not None or meta.read_count != 0:
            raise LockDenied(f"ownership transfer denied for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {"owner_id": new_owner_id},
            "owner_id = ? AND write_holder IS NULL AND read_count = 0",
            (self.node_id,),
        )

    def claim_free(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.owner_id is not None or meta.state != FileState.CREATED:
            raise LockDenied(f"claim denied for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {"owner_id": self.node_id},
            "owner_id IS NULL AND write_holder IS NULL AND state = ?",
            (FileState.CREATED.value,),
        )

    def archive(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.owner_id != self.node_id:
            raise LockDenied(f"{self.node_id} does not own {file_id}")
        if meta.write_holder is not None or meta.read_count != 0:
            raise LockDenied(f"archive denied for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {
                "state": FileState.ARCHIVED,
                "write_holder": None,
                "read_count": 0,
                "owner_id": None,
                "lease_expire": None,
            },
            "owner_id = ? AND write_holder IS NULL AND read_count = 0",
            (self.node_id,),
        )

    def recover_expired_write(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.lease_expire is None or meta.lease_expire >= utcnow():
            raise LockDenied(f"lease is not expired for {file_id}")
        return self.store.cas_update(
            file_id,
            meta.version,
            {
                "write_holder": None,
                "state": FileState.CREATED,
                "lease_expire": None,
            },
            "lease_expire IS NOT NULL AND lease_expire < ?",
            (utcnow().isoformat(),),
        )

    def renew_write(self, file_id: str) -> FileMeta:
        meta = self.store.get(file_id)
        if meta.write_holder != self.node_id:
            raise LockDenied(f"{self.node_id} does not hold write lock for {file_id}")
        try:
            return self.store.cas_update(
                file_id,
                meta.version,
                {"lease_expire": utcnow() + self.lease},
                "write_holder = ?",
                (self.node_id,),
            )
        except CasConflict:
            raise
