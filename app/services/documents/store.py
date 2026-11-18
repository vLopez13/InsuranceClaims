"""Abstract file store. OCR later opens a reference; it does not read a blob column."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

_REFERENCE = re.compile(r"^docstore://claims/([A-Za-z0-9]+)/([A-Za-z0-9]+)$")


@dataclass(frozen=True)
class StoredObject:
    file_reference: str
    content_sha256: str
    byte_size: int


class DocumentStore(Protocol):
    def save(self, *, claim_id: int, content: bytes) -> StoredObject: ...

    def open(self, file_reference: str) -> bytes: ...


class LocalDocumentStore:
    """Development store. ``file_reference`` is an opaque URI, not a filesystem path."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def save(self, *, claim_id: int, content: bytes) -> StoredObject:
        token = uuid4().hex
        reference = f"docstore://claims/{claim_id}/{token}"
        destination = self._path_for(reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return StoredObject(
            file_reference=reference,
            content_sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(content),
        )

    def open(self, file_reference: str) -> bytes:
        return self._path_for(file_reference).read_bytes()

    def _path_for(self, file_reference: str) -> Path:
        match = _REFERENCE.fullmatch(file_reference)
        if match is None:
            raise ValueError("invalid_reference")
        claim_part, token = match.groups()
        return self.root / claim_part / token
