"""SQLite persistence for jobs and documents.

Standard-library ``sqlite3`` only: the data model is two small tables and the
app serves one analyst, so an ORM or async driver would add dependencies
without benefit (DECISIONS D-033). Every status transition is written straight
away, so the frontend's polling always sees the current stage (spec section 6).

Concurrency: one connection shared by the event loop and the worker, guarded by
a lock. Statements are tiny (single-row updates), so blocking the loop for a
fraction of a millisecond is acceptable. WAL mode lets readers proceed while a
write is in progress.

Results (``DocumentAnalysis``, ``ConsolidatedReport``) are stored as JSON
produced by their Pydantic models, so the API returns exactly what was
validated.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.analysis import DocumentAnalysis
from app.schemas.common import DocumentWarning, Profile
from app.schemas.consolidated import ConsolidatedReport
from app.schemas.jobs import DocumentStatus, ErrorInfo, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    profile             TEXT NOT NULL,
    status              TEXT NOT NULL,
    error_code          TEXT,
    error_message       TEXT,
    consolidated_json   TEXT,
    consolidated_code   TEXT,
    consolidated_message TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id                  TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(id),
    position            INTEGER NOT NULL,
    filename            TEXT NOT NULL,
    size_bytes          INTEGER NOT NULL,
    page_count          INTEGER,
    status              TEXT NOT NULL,
    error_code          TEXT,
    error_message       TEXT,
    upload_warnings_json TEXT NOT NULL DEFAULT '[]',
    analysis_json       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_job ON documents(job_id, position);
"""

_FINAL_DOC = (DocumentStatus.COMPLETED, DocumentStatus.REJECTED, DocumentStatus.FAILED)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class NewDocument:
    """A document to insert when a job is created."""

    document_id: str
    filename: str  # already sanitised for display
    size_bytes: int
    page_count: int | None
    status: DocumentStatus  # QUEUED, or REJECTED for files that failed validation
    error: ErrorInfo | None = None
    upload_warnings: list[DocumentWarning] = field(default_factory=list)


@dataclass
class DocumentRecord:
    document_id: str
    job_id: str
    position: int
    filename: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    error: ErrorInfo | None
    upload_warnings: list[DocumentWarning]
    analysis: DocumentAnalysis | None


@dataclass
class JobRecord:
    job_id: str
    profile: Profile
    status: JobStatus
    error: ErrorInfo | None
    consolidated: ConsolidatedReport | None
    consolidated_error: ErrorInfo | None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentRecord]


class Repository:
    """All database access for the app."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: autocommit; each statement is its own transaction
        # unless wrapped in an explicit BEGIN (see create_job).
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ writes

    def create_job(self, job_id: str, profile: Profile, documents: list[NewDocument]) -> None:
        """Insert a job and its documents atomically, with status ``queued``."""
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO jobs (id, profile, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (job_id, profile, JobStatus.QUEUED.value, now, now),
                )
                for position, doc in enumerate(documents):
                    self._conn.execute(
                        "INSERT INTO documents (id, job_id, position, filename, size_bytes, "
                        "page_count, status, error_code, error_message, upload_warnings_json, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            doc.document_id,
                            job_id,
                            position,
                            doc.filename,
                            doc.size_bytes,
                            doc.page_count,
                            doc.status.value,
                            doc.error.code if doc.error else None,
                            doc.error.message if doc.error else None,
                            json.dumps([w.model_dump(mode="json") for w in doc.upload_warnings]),
                            now,
                            now,
                        ),
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def set_job_status(
        self, job_id: str, status: JobStatus, error: ErrorInfo | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error_code = ?, error_message = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    status.value,
                    error.code if error else None,
                    error.message if error else None,
                    _now(),
                    job_id,
                ),
            )

    def set_document_status(
        self, document_id: str, status: DocumentStatus, error: ErrorInfo | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET status = ?, error_code = ?, error_message = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    status.value,
                    error.code if error else None,
                    error.message if error else None,
                    _now(),
                    document_id,
                ),
            )
            self._touch_job_of(document_id)

    def save_document_analysis(self, document_id: str, analysis: DocumentAnalysis) -> None:
        """Store the result and mark the document ``completed``."""
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET analysis_json = ?, status = ?, updated_at = ? WHERE id = ?",
                (analysis.model_dump_json(), DocumentStatus.COMPLETED.value, _now(), document_id),
            )
            self._touch_job_of(document_id)

    def save_consolidated(
        self,
        job_id: str,
        report: ConsolidatedReport | None,
        error: ErrorInfo | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET consolidated_json = ?, consolidated_code = ?, "
                "consolidated_message = ?, updated_at = ? WHERE id = ?",
                (
                    report.model_dump_json() if report else None,
                    error.code if error else None,
                    error.message if error else None,
                    _now(),
                    job_id,
                ),
            )

    def fail_unfinished_jobs(self, error: ErrorInfo) -> list[str]:
        """Mark every queued/processing job, and its unfinished documents, as failed.

        Called on startup: the in-memory queue does not survive a restart, so
        these jobs would otherwise show "processing" forever.

        Returns:
            IDs of the documents that were failed (their uploads can be deleted).
        """
        unfinished = (JobStatus.QUEUED.value, JobStatus.PROCESSING.value)
        final_docs = tuple(s.value for s in _FINAL_DOC)
        now = _now()
        with self._lock:
            job_ids = [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM jobs WHERE status IN (?, ?)", unfinished
                ).fetchall()
            ]
            if not job_ids:
                return []
            marks = ",".join("?" * len(job_ids))
            doc_ids = [
                r["id"]
                for r in self._conn.execute(
                    f"SELECT id FROM documents WHERE job_id IN ({marks}) "  # noqa: S608 - only '?' placeholders
                    "AND status NOT IN (?, ?, ?)",
                    (*job_ids, *final_docs),
                ).fetchall()
            ]
            self._conn.execute("BEGIN")
            self._conn.execute(
                f"UPDATE documents SET status = ?, error_code = ?, error_message = ?, "  # noqa: S608
                f"updated_at = ? WHERE job_id IN ({marks}) AND status NOT IN (?, ?, ?)",
                (
                    DocumentStatus.FAILED.value,
                    error.code,
                    error.message,
                    now,
                    *job_ids,
                    *final_docs,
                ),
            )
            self._conn.execute(
                f"UPDATE jobs SET status = ?, error_code = ?, error_message = ?, "  # noqa: S608
                f"updated_at = ? WHERE id IN ({marks})",
                (JobStatus.FAILED.value, error.code, error.message, now, *job_ids),
            )
            self._conn.execute("COMMIT")
        return doc_ids

    # ------------------------------------------------------------------ reads

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            job = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return None
            docs = self._conn.execute(
                "SELECT * FROM documents WHERE job_id = ? ORDER BY position", (job_id,)
            ).fetchall()
        return JobRecord(
            job_id=job["id"],
            profile=job["profile"],
            status=JobStatus(job["status"]),
            error=_error(job["error_code"], job["error_message"]),
            consolidated=(
                ConsolidatedReport.model_validate_json(job["consolidated_json"])
                if job["consolidated_json"]
                else None
            ),
            consolidated_error=_error(job["consolidated_code"], job["consolidated_message"]),
            created_at=datetime.fromisoformat(job["created_at"]),
            updated_at=datetime.fromisoformat(job["updated_at"]),
            documents=[_document(d) for d in docs],
        )

    # ------------------------------------------------------------------ helpers

    def _touch_job_of(self, document_id: str) -> None:
        """Bump the parent job's ``updated_at`` (caller holds the lock)."""
        self._conn.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = (SELECT job_id FROM documents WHERE id = ?)",
            (_now(), document_id),
        )


def _error(code: str | None, message: str | None) -> ErrorInfo | None:
    return ErrorInfo(code=code, message=message or "") if code else None


def _document(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        document_id=row["id"],
        job_id=row["job_id"],
        position=row["position"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        page_count=row["page_count"],
        status=DocumentStatus(row["status"]),
        error=_error(row["error_code"], row["error_message"]),
        upload_warnings=[
            DocumentWarning.model_validate(w) for w in json.loads(row["upload_warnings_json"])
        ],
        analysis=(
            DocumentAnalysis.model_validate_json(row["analysis_json"])
            if row["analysis_json"]
            else None
        ),
    )
