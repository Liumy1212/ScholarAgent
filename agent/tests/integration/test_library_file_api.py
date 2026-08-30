import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from tests.support import RecordingVectorStore, runtime_settings, sqlite_database

from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.library_lifecycle import LibraryLifecycleService
from airesearcher_agent.application.library_scans import LibraryScanService
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.application.runtime import RuntimeServices
from airesearcher_agent.application.stream_chat import StreamChatUseCase
from airesearcher_agent.domain.papers import IngestionJobStatus, IngestionStage, PaperStatus
from airesearcher_agent.main import create_app
from airesearcher_agent.persistence.models import IngestionJobRecord, PaperRecord
from airesearcher_agent.providers.fake import FakeChatProvider
from airesearcher_agent.worker.library_scan import LibraryScanWorker


def test_library_upload_list_and_range_preview_do_not_start_ingestion(tmp_path: Path) -> None:
    async def exercise() -> None:
        settings = runtime_settings(tmp_path)
        database = sqlite_database()
        library_files = LibraryFileService(database=database, settings=settings)
        vectors = RecordingVectorStore()
        lifecycle = LibraryLifecycleService(
            database=database,
            settings=settings,
            vector_store=vectors,
            library_file_service=library_files,
        )
        provider = FakeChatProvider()
        runtime = RuntimeServices(
            settings=settings,
            database=database,
            library_file_service=library_files,
            library_lifecycle_service=lifecycle,
            library_scan_service=LibraryScanService(
                database=database,
                settings=settings,
                library_file_service=library_files,
            ),
            paper_service=PaperService(
                database=database,
                settings=settings,
                vector_store=vectors,
                library_file_service=library_files,
                library_lifecycle_service=lifecycle,
            ),
            stream_chat=StreamChatUseCase(provider),
        )
        transport = ASGITransport(app=create_app(provider, runtime=runtime))
        headers = {"X-Request-Id": "req-library-stage2"}
        content = b"%PDF-1.7\nrange-preview"
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            uploaded = await client.post(
                "/agent-api/v1/library/files",
                headers=headers,
                files={"file": ("api-paper.pdf", content, "application/pdf")},
            )
            listed = await client.get(
                "/agent-api/v1/library/files?offset=0&limit=25",
                headers=headers,
            )
            library_file_id = uploaded.json()["libraryFile"]["libraryFileId"]
            preview = await client.get(
                f"/agent-api/v1/library/files/{library_file_id}/file",
                headers={**headers, "Range": "bytes=5-11"},
            )
            queued_scan = await client.post("/agent-api/v1/library/scans", headers=headers)
            active_scan = await client.post("/agent-api/v1/library/scans", headers=headers)
            library_info = await client.get("/agent-api/v1/library", headers=headers)
            scan_id = queued_scan.json()["scanId"]
            scan_worker = LibraryScanWorker(
                database=database,
                settings=settings,
                worker_id="api-scan-worker",
            )
            assert scan_worker.run_once() is True
            completed_scan = await client.get(
                f"/agent-api/v1/library/scans/{scan_id}",
                headers=headers,
            )
            scan_items = await client.get(
                f"/agent-api/v1/library/scans/{scan_id}/items?outcome=UNCHANGED",
                headers=headers,
            )

        assert uploaded.status_code == 200
        assert uploaded.headers["X-Request-Id"] == "req-library-stage2"
        assert uploaded.json()["libraryFile"]["knowledgeStatus"] == "NOT_INGESTED"
        assert uploaded.json()["libraryFile"]["paperId"] is None
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["relativePath"] == "uploads/api-paper.pdf"
        assert preview.status_code == 206
        assert preview.content == content[5:12]
        assert preview.headers["Content-Range"] == f"bytes 5-11/{len(content)}"
        assert preview.headers["ETag"].startswith('"sha256-')
        assert queued_scan.status_code == 202
        assert active_scan.status_code == 409
        assert active_scan.json()["code"] == "LIBRARY_SCAN_ACTIVE"
        assert library_info.json()["scanInProgress"] is True
        assert completed_scan.json()["status"] == "SUCCEEDED"
        assert scan_items.json()["total"] == 1
        assert scan_items.json()["items"][0]["outcome"] == "UNCHANGED"
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(PaperRecord)) == 0
            assert session.scalar(select(func.count()).select_from(IngestionJobRecord)) == 0

    asyncio.run(exercise())


def test_manual_ingestion_exclusion_and_restore_api(tmp_path: Path) -> None:
    async def exercise() -> None:
        settings = runtime_settings(tmp_path)
        database = sqlite_database()
        library_files = LibraryFileService(database=database, settings=settings)
        vectors = RecordingVectorStore()
        lifecycle = LibraryLifecycleService(
            database=database,
            settings=settings,
            vector_store=vectors,
            library_file_service=library_files,
        )
        provider = FakeChatProvider()
        runtime = RuntimeServices(
            settings=settings,
            database=database,
            library_file_service=library_files,
            library_lifecycle_service=lifecycle,
            library_scan_service=LibraryScanService(
                database=database,
                settings=settings,
                library_file_service=library_files,
            ),
            paper_service=PaperService(
                database=database,
                settings=settings,
                vector_store=vectors,
                library_file_service=library_files,
                library_lifecycle_service=lifecycle,
            ),
            stream_chat=StreamChatUseCase(provider),
        )
        transport = ASGITransport(app=create_app(provider, runtime=runtime))
        headers = {"X-Request-Id": "req-library-stage4"}
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            uploaded = await client.post(
                "/agent-api/v1/library/files",
                headers=headers,
                files={
                    "file": (
                        "lifecycle-api.pdf",
                        b"%PDF-1.7\nlifecycle-api",
                        "application/pdf",
                    )
                },
            )
            library_file_id = uploaded.json()["libraryFile"]["libraryFileId"]
            ingested = await client.post(
                f"/agent-api/v1/library/files/{library_file_id}/ingestion",
                headers=headers,
            )
            repeated = await client.post(
                f"/agent-api/v1/library/files/{library_file_id}/ingestion",
                headers=headers,
            )
            paper_id = ingested.json()["paper"]["paperId"]
            job_id = ingested.json()["ingestionJob"]["jobId"]

            with database.transaction() as session:
                job = session.get(IngestionJobRecord, job_id)
                paper = session.get(PaperRecord, paper_id)
                assert job is not None and paper is not None
                job.status = IngestionJobStatus.SUCCEEDED.value
                job.active_key = None
                job.stage = IngestionStage.COMPLETED.value
                paper.status = PaperStatus.READY.value

            excluded = await client.post(
                f"/agent-api/v1/papers/{paper_id}/exclusion",
                headers=headers,
            )
            restored = await client.delete(
                f"/agent-api/v1/papers/{paper_id}/exclusion",
                headers=headers,
            )

        assert ingested.status_code == 200
        assert ingested.headers["X-Request-Id"] == "req-library-stage4"
        assert ingested.json()["libraryFile"]["knowledgeStatus"] == "PROCESSING"
        assert ingested.json()["duplicate"] is False
        assert repeated.status_code == 200
        assert repeated.json()["duplicate"] is True
        assert repeated.json()["paper"]["paperId"] == paper_id
        assert excluded.status_code == 200
        assert excluded.json()["status"] == "EXCLUDED"
        assert excluded.json()["searchable"] is False
        assert restored.status_code == 200
        assert restored.json()["status"] == "PROCESSING"
        assert restored.json()["currentIngestion"]["status"] == "QUEUED"
        assert vectors.deleted_papers == [paper_id, paper_id]

    asyncio.run(exercise())
