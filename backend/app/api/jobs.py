"""Job routes: upload documents, poll status and results, list profiles.

``POST /api/jobs`` validates every file synchronously (stage 0) before the job
is accepted. Valid files are stored under generated UUIDs and queued; invalid
ones are reported per file with their error code. Rejected files are also
stored as ``rejected`` documents, so ``GET /api/jobs/{id}`` tells the whole
story. If no file is valid, the job is not created (400 ``NO_VALID_FILES``).
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import get_repo, get_uploads, get_worker
from app.config import Settings, get_settings
from app.errors import ApiError, ErrorCode
from app.pipeline.validation import check_file_count, sanitize_filename, validate_file
from app.pipeline.worker import JobWorker
from app.profiles import PROFILES, is_available
from app.schemas.common import Profile
from app.schemas.errors import ErrorEnvelope
from app.schemas.jobs import (
    AcceptedDocument,
    DocumentResult,
    DocumentStatus,
    ErrorInfo,
    JobCreatedResponse,
    JobResponse,
    ProfileInfo,
)
from app.schemas.validation import AcceptedFile, RejectedFile
from app.storage.repository import JobRecord, NewDocument, Repository
from app.storage.uploads import UploadStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])

_READ_CHUNK = 1024 * 1024
_ERRORS = {400: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}}


@router.get("/profiles", response_model=list[ProfileInfo])
async def list_profiles() -> list[ProfileInfo]:
    """Analysis profiles, with a one-line description each."""
    return PROFILES


@router.post(
    "/jobs",
    status_code=202,
    response_model=JobCreatedResponse,
    responses=_ERRORS,
)
async def create_job(
    files: list[UploadFile] = File(..., description="One or more PDF files (repeat the field)"),
    profile: Profile = Form("general"),
    settings: Settings = Depends(get_settings),
    repo: Repository = Depends(get_repo),
    uploads: UploadStore = Depends(get_uploads),
    worker: JobWorker = Depends(get_worker),
) -> JobCreatedResponse:
    """Validate the uploaded PDFs and queue the valid ones for analysis."""
    if not is_available(profile):
        raise ApiError(
            ErrorCode.UNSUPPORTED_PROFILE,
            f"The '{profile}' profile is not available yet.",
            details={"available": [p.id for p in PROFILES if p.available]},
        )
    check_file_count(len(files), settings)

    job_id = str(uuid.uuid4())
    accepted: list[AcceptedDocument] = []
    rejected: list[RejectedFile] = []
    new_docs: list[NewDocument] = []

    for upload in files:
        result, data = await _validate_upload(upload, settings)
        document_id = str(uuid.uuid4())
        if isinstance(result, AcceptedFile):
            await asyncio.to_thread(uploads.save, document_id, data)
            accepted.append(
                AcceptedDocument(
                    document_id=document_id,
                    filename=result.filename,
                    page_count=result.page_count,
                    warnings=result.warnings,
                )
            )
            new_docs.append(
                NewDocument(
                    document_id=document_id,
                    filename=result.filename,
                    size_bytes=result.size_bytes,
                    page_count=result.page_count,
                    status=DocumentStatus.QUEUED,
                    upload_warnings=result.warnings,
                )
            )
        else:
            rejected.append(result)
            new_docs.append(
                NewDocument(
                    document_id=document_id,
                    filename=result.filename,
                    size_bytes=0,
                    page_count=None,
                    status=DocumentStatus.REJECTED,
                    error=ErrorInfo(code=result.code, message=result.message),
                )
            )

    if not accepted:
        raise ApiError(
            ErrorCode.NO_VALID_FILES,
            "None of the uploaded files could be accepted.",
            details={"rejected": [r.model_dump(mode="json") for r in rejected]},
        )

    repo.create_job(job_id, profile, new_docs)
    worker.enqueue(job_id)
    logger.info(
        "Job created: %d accepted, %d rejected",
        len(accepted),
        len(rejected),
        extra={"event": "job_created", "job_id": job_id},
    )
    return JobCreatedResponse(job_id=job_id, accepted=accepted, rejected=rejected)


@router.get("/jobs/{job_id}", response_model=JobResponse, responses={404: {"model": ErrorEnvelope}})
async def get_job(job_id: str, repo: Repository = Depends(get_repo)) -> JobResponse:
    """Job status, per-document status, and results as they become available."""
    job = repo.get_job(job_id)
    if job is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No job with this ID.", status_code=404)
    return to_response(job)


def to_response(job: JobRecord) -> JobResponse:
    """Build the API response from stored records."""
    return JobResponse(
        job_id=job.job_id,
        profile=job.profile,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
        documents=[
            DocumentResult(
                document_id=d.document_id,
                filename=d.filename,
                status=d.status,
                page_count=d.page_count,
                error=d.error,
                analysis=d.analysis,
            )
            for d in job.documents
        ],
        consolidated=job.consolidated,
        consolidated_error=job.consolidated_error,
    )


async def _validate_upload(
    upload: UploadFile, settings: Settings
) -> tuple[AcceptedFile | RejectedFile, bytes]:
    """Read the upload (stopping once it passes ``MAX_FILE_MB``) and run stage-0 validation.

    Reading stops as soon as the limit is passed, so an oversized file is never
    held in memory in full.

    Returns:
        The validation result and the bytes read (empty for an oversized file).
    """
    limit = settings.max_file_mb * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(_READ_CHUNK):
        size += len(chunk)
        if size > limit:
            rejected = RejectedFile(
                filename=sanitize_filename(upload.filename),
                code=ErrorCode.FILE_TOO_LARGE,
                message=f"File is larger than the {settings.max_file_mb} MB limit.",
            )
            return rejected, b""
        chunks.append(chunk)
    data = b"".join(chunks)
    # PyMuPDF work is CPU-bound; keep the event loop free for status polling.
    result = await asyncio.to_thread(validate_file, upload.filename, data, settings)
    return result, data
