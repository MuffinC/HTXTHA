"""In-process job queue and worker (CLAUDE.md section 4: concurrency 1).

``POST /api/jobs`` stores the job and enqueues its ID. One background task,
started in the FastAPI lifespan, takes jobs one at a time and runs each document
through stages 1-3, then stage 4 across the documents that succeeded. One local
model can only serve one request efficiently, so jobs never run in parallel.

Every status change is written to SQLite immediately, so the frontend's polling
shows live progress. A failure in one document marks that document ``failed``
and the job carries on (status ``partial``). Uploads are deleted once their
document is processed, unless ``RETAIN_UPLOADS=true``.

The queue lives in memory. On startup, jobs that were queued or running when the
backend stopped are marked ``failed`` (``INTERRUPTED``), so they do not show
"processing" forever (see ``recover_interrupted_jobs``).
"""

import asyncio
import contextlib
import logging
import time

from app.config import Settings
from app.errors import ErrorCode
from app.llm.base import LLMError, LLMProvider
from app.logging_config import log_context
from app.pipeline.analysis import DocumentFailure, analyse_document
from app.pipeline.consolidation import consolidate
from app.pipeline.extraction import extract_document
from app.pipeline.visual import analyse_visuals
from app.schemas.analysis import DocumentAnalysis
from app.schemas.common import Profile
from app.schemas.jobs import DocumentStatus, ErrorInfo, JobStatus
from app.storage.repository import DocumentRecord, Repository
from app.storage.uploads import UploadStore

logger = logging.getLogger(__name__)

INTERRUPTED = ErrorInfo(
    code=ErrorCode.INTERRUPTED,
    message="The backend restarted before this job finished. Please upload the files again.",
)
SINGLE_DOCUMENT = ErrorInfo(
    code="SINGLE_DOCUMENT",
    message="A consolidated report needs at least two successfully analysed documents.",
)


class JobWorker:
    """Owns the queue and the background task that processes it."""

    def __init__(
        self,
        repo: Repository,
        uploads: UploadStore,
        provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self._repo = repo
        self._uploads = uploads
        self._provider = provider
        self._settings = settings
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ lifecycle

    def recover_interrupted_jobs(self) -> None:
        """Fail jobs left queued/processing by a previous run and delete their uploads."""
        doc_ids = self._repo.fail_unfinished_jobs(INTERRUPTED)
        if doc_ids:
            logger.warning(
                "Marked interrupted jobs as failed",
                extra={"event": "startup_recovery", "count": len(doc_ids)},
            )
        if not self._settings.retain_uploads:
            for doc_id in doc_ids:
                self._uploads.delete(doc_id)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="job-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def enqueue(self, job_id: str) -> None:
        self._queue.put_nowait(job_id)

    # ------------------------------------------------------------------ processing

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                with log_context(job_id=job_id):
                    await self.process_job(job_id)
            except Exception:  # last line of defence: never let the worker die
                logger.exception("Job crashed", extra={"event": "job_crashed"})
                self._repo.set_job_status(
                    job_id,
                    JobStatus.FAILED,
                    ErrorInfo(
                        code=ErrorCode.INTERNAL_ERROR, message="An unexpected error occurred."
                    ),
                )
            finally:
                self._queue.task_done()

    async def process_job(self, job_id: str) -> None:
        """Run every queued document of the job, then the consolidated report."""
        job = self._repo.get_job(job_id)
        if job is None:  # pragma: no cover - enqueued IDs always exist
            return
        started = time.perf_counter()
        self._repo.set_job_status(job_id, JobStatus.PROCESSING)
        logger.info("Job started", extra={"event": "job_started", "count": len(job.documents)})

        queued = [d for d in job.documents if d.status is DocumentStatus.QUEUED]
        analyses: list[DocumentAnalysis] = []
        for doc in queued:
            with log_context(document_id=doc.document_id):
                analysis = await self._process_document(doc, job.profile)
            if analysis:
                analyses.append(analysis)

        consolidated_failed = await self._consolidate(job_id, analyses)

        if not analyses:
            status = JobStatus.FAILED
            error = ErrorInfo(code="NO_DOCUMENT_ANALYSED", message="No document could be analysed.")
        elif len(analyses) < len(queued) or consolidated_failed:
            status, error = JobStatus.PARTIAL, None
        else:
            status, error = JobStatus.COMPLETED, None
        self._repo.set_job_status(job_id, status, error)
        logger.info(
            "Job finished: %s",
            status.value,
            extra={"event": "job_finished", "duration_ms": _ms(started), "code": status.value},
        )

    async def _process_document(
        self, doc: DocumentRecord, profile: Profile
    ) -> DocumentAnalysis | None:
        """Stages 1-3 for one document. Returns ``None`` if it failed."""
        doc_id = doc.document_id
        settings = self._settings
        try:
            data = await asyncio.to_thread(self._uploads.load, doc_id)

            self._set_stage(doc_id, DocumentStatus.EXTRACTING)
            t = time.perf_counter()
            extracted = await asyncio.to_thread(extract_document, data, settings)
            self._log_stage("extracting", t)

            warnings = [*doc.upload_warnings, *extracted.warnings]
            visual_elements = []
            if extracted.visual_pages:
                self._set_stage(doc_id, DocumentStatus.ANALYSING_VISUALS)
                t = time.perf_counter()
                visuals = await analyse_visuals(
                    data, extracted, profile, self._provider, settings, document_id=doc_id
                )
                self._log_stage("analysing_visuals", t)
                visual_elements, warnings = visuals.elements, [*warnings, *visuals.warnings]

            self._set_stage(doc_id, DocumentStatus.ANALYSING)
            t = time.perf_counter()
            analysis = await analyse_document(
                document_id=doc_id,
                filename=doc.filename,
                extracted=extracted,
                visual_elements=visual_elements,
                warnings=warnings,
                profile=profile,
                provider=self._provider,
                settings=settings,
            )
            self._log_stage("analysing", t)
            self._repo.save_document_analysis(doc_id, analysis)
            return analysis
        except DocumentFailure as exc:
            self._fail_document(doc_id, ErrorInfo(code=exc.code, message=exc.message))
        except Exception:
            logger.exception("Document processing crashed", extra={"event": "document_crashed"})
            self._fail_document(
                doc_id,
                ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message="An unexpected error occurred."),
            )
        finally:
            if not settings.retain_uploads:
                self._uploads.delete(doc_id)
        return None

    async def _consolidate(self, job_id: str, analyses: list[DocumentAnalysis]) -> bool:
        """Stage 4. Returns True if it was attempted and failed."""
        if len(analyses) < 2:
            self._repo.save_consolidated(job_id, None, SINGLE_DOCUMENT if analyses else None)
            return False
        t = time.perf_counter()
        try:
            report = await consolidate(analyses, self._provider, self._settings)
        except LLMError as exc:
            logger.warning(
                "Consolidated report failed", extra={"stage": "consolidating", "code": exc.code}
            )
            self._repo.save_consolidated(
                job_id,
                None,
                ErrorInfo(
                    code=exc.code,
                    message="The consolidated report could not be produced. "
                    "Each document's own analysis is still available.",
                ),
            )
            return True
        self._log_stage("consolidating", t)
        self._repo.save_consolidated(job_id, report)
        return False

    # ------------------------------------------------------------------ helpers

    def _set_stage(self, doc_id: str, status: DocumentStatus) -> None:
        self._repo.set_document_status(doc_id, status)
        logger.info("Stage started", extra={"stage": status.value, "event": "stage_started"})

    def _fail_document(self, doc_id: str, error: ErrorInfo) -> None:
        logger.warning("Document failed", extra={"event": "document_failed", "code": error.code})
        self._repo.set_document_status(doc_id, DocumentStatus.FAILED, error)

    @staticmethod
    def _log_stage(stage: str, started: float) -> None:
        logger.info("Stage finished", extra={"stage": stage, "duration_ms": _ms(started)})


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
