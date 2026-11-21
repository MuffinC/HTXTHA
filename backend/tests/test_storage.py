"""Tests for the SQLite repository and upload store."""

from pathlib import Path

import pytest

from app.schemas.jobs import DocumentStatus, ErrorInfo, JobStatus
from app.storage.repository import NewDocument, Repository
from app.storage.uploads import UploadStore

JOB = "11111111-0000-4000-8000-000000000000"
DOC_A = "aaaaaaaa-0000-4000-8000-000000000001"
DOC_B = "bbbbbbbb-0000-4000-8000-000000000002"


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    repo = Repository(tmp_path / "test.sqlite3")
    repo.create_job(
        JOB,
        "general",
        [
            NewDocument(DOC_A, "a.pdf", 100, 2, DocumentStatus.QUEUED),
            NewDocument(
                DOC_B,
                "b.pdf",
                0,
                None,
                DocumentStatus.REJECTED,
                ErrorInfo(code="ENCRYPTED_PDF", message="Encrypted."),
            ),
        ],
    )
    return repo


def test_job_round_trip(repo: Repository) -> None:
    job = repo.get_job(JOB)

    assert job is not None
    assert job.status is JobStatus.QUEUED
    assert [d.document_id for d in job.documents] == [DOC_A, DOC_B]  # upload order kept
    assert job.documents[1].error == ErrorInfo(code="ENCRYPTED_PDF", message="Encrypted.")
    assert repo.get_job("missing") is None


def test_status_transitions_are_persisted(repo: Repository) -> None:
    repo.set_job_status(JOB, JobStatus.PROCESSING)
    repo.set_document_status(DOC_A, DocumentStatus.ANALYSING_VISUALS)

    job = repo.get_job(JOB)
    assert job is not None
    assert job.status is JobStatus.PROCESSING
    assert job.documents[0].status is DocumentStatus.ANALYSING_VISUALS


def test_unfinished_jobs_are_failed_on_recovery(repo: Repository) -> None:
    repo.set_job_status(JOB, JobStatus.PROCESSING)
    repo.set_document_status(DOC_A, DocumentStatus.ANALYSING)
    reason = ErrorInfo(code="INTERRUPTED", message="Restarted.")

    failed_docs = repo.fail_unfinished_jobs(reason)

    job = repo.get_job(JOB)
    assert job is not None
    assert failed_docs == [DOC_A]  # the rejected document is left as it was
    assert job.status is JobStatus.FAILED and job.error == reason
    assert job.documents[0].status is DocumentStatus.FAILED
    assert job.documents[1].status is DocumentStatus.REJECTED


def test_finished_jobs_are_left_alone_on_recovery(repo: Repository) -> None:
    repo.set_job_status(JOB, JobStatus.COMPLETED)
    assert repo.fail_unfinished_jobs(ErrorInfo(code="INTERRUPTED", message="x")) == []
    job = repo.get_job(JOB)
    assert job is not None and job.status is JobStatus.COMPLETED


def test_upload_store_uses_uuid_paths_only(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)
    store.save(DOC_A, b"%PDF-1.7")

    assert store.path(DOC_A) == tmp_path / "uploads" / f"{DOC_A}.pdf"
    assert store.load(DOC_A) == b"%PDF-1.7"
    with pytest.raises(ValueError):
        store.path("../../etc/passwd")
    store.delete(DOC_A)
    store.delete(DOC_A)  # deleting twice is fine
    assert not store.path(DOC_A).exists()
