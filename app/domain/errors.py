"""Domain failures. Messages stay static so they cannot carry PHI."""

from __future__ import annotations


class ClaimNotFound(Exception):
    """No claim with the requested id."""


class IdempotencyConflict(Exception):
    """The idempotency key was reused with a different request body."""


class IllegalTransition(Exception):
    """The state machine rejected the status change."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__("illegal_transition")


class InvalidReference(Exception):
    """A foreign key target does not exist. ``field`` is a schema name, not a value."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(field)


class DomainValidation(Exception):
    """A business validation failure identified by a static error type."""

    def __init__(self, field: str, error_type: str) -> None:
        self.field = field
        self.error_type = error_type
        super().__init__(error_type)


class FinalizedClaim(Exception):
    """A document was sent for a claim that already has a final status."""


class VersionConflict(Exception):
    """The caller’s expected row version does not match the locked row."""


class IdempotencyKeyRequired(Exception):
    """The Idempotency-Key header is missing or empty."""


class RequestInProgress(Exception):
    """The same idempotency key is already being processed."""


class PayloadTooLarge(Exception):
    """A document is larger than 20 MiB."""


class UnsupportedMedia(Exception):
    """A document's magic bytes are missing or not an allowed type."""


class MissingActor(Exception):
    """A required actor header is absent."""
