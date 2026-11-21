"""Temporary storage for uploaded PDFs, keyed by generated document ID.

The user's filename is never used in a path (CLAUDE.md section 7): files live
at ``<DATA_DIR>/uploads/<uuid>.pdf``. They are deleted once their document is
processed, unless ``RETAIN_UPLOADS=true``.
"""

import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class UploadStore:
    """Save, load and delete uploaded PDFs."""

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, document_id: str) -> Path:
        """Path for a document. Rejects anything that is not a UUID (no path tricks)."""
        return self.root / f"{uuid.UUID(document_id)}.pdf"

    def save(self, document_id: str, data: bytes) -> None:
        self.path(document_id).write_bytes(data)

    def load(self, document_id: str) -> bytes:
        return self.path(document_id).read_bytes()

    def delete(self, document_id: str) -> None:
        """Delete if present. Never raises: cleanup must not fail a job."""
        try:
            self.path(document_id).unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not delete upload",
                extra={"event": "upload_cleanup", "document_id": document_id},
            )
