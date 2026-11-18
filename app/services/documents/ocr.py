"""Seam for the later OCR milestone. The decision router does not import this module.

An extractor receives a document store and a file reference. It must not log file
bytes, filenames, or anything copied out of the document. Extracted text, if a
future milestone persists it, belongs in a dedicated table and not in the audit log.
"""

from __future__ import annotations

from typing import Protocol

from app.services.documents.store import DocumentStore


class DocumentTextExtractor(Protocol):
    def extract(self, store: DocumentStore, file_reference: str, mime_type: str) -> str:
        """Return extracted text. Implementations must not log the text."""
