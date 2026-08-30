import argparse
import logging
import os
import socket
import time
from collections.abc import Callable
from uuid import uuid4

from airesearcher_agent.config import Settings
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.worker.library_scan import LibraryScanWorker
from airesearcher_agent.worker.service import IngestionWorker


def build_ingestion_worker(settings: Settings, *, worker_id: str) -> IngestionWorker:
    from airesearcher_agent.ingestion.pdf import PdfParser
    from airesearcher_agent.retrieval.local_models import BgeM3EmbeddingProvider
    from airesearcher_agent.retrieval.qdrant_store import QdrantVectorStore

    return IngestionWorker(
        database=Database(settings.database_url),
        parser=PdfParser(
            max_pages=settings.upload_max_pages,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        ),
        embedding=BgeM3EmbeddingProvider(settings),
        vector_store=QdrantVectorStore.from_settings(settings),
        settings=settings,
        worker_id=worker_id,
    )


def build_scan_worker(settings: Settings, *, worker_id: str) -> LibraryScanWorker:
    return LibraryScanWorker(
        database=Database(settings.database_url),
        settings=settings,
        worker_id=worker_id,
    )


class CompositeWorker:
    def __init__(
        self,
        *,
        scan_worker: LibraryScanWorker,
        ingestion_factory: Callable[[], IngestionWorker],
    ) -> None:
        self._scan_worker = scan_worker
        self._ingestion_factory = ingestion_factory
        self._ingestion_worker: IngestionWorker | None = None

    def run_once(self) -> bool:
        if self._scan_worker.run_once():
            return True
        if self._ingestion_worker is None:
            self._ingestion_worker = self._ingestion_factory()
        return self._ingestion_worker.run_once()


def main() -> None:
    parser = argparse.ArgumentParser(description="AIResearcher leased ingestion worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--scan-only",
        action="store_true",
        help="process library scans without loading embedding or vector providers",
    )
    mode.add_argument(
        "--ingestion-only",
        action="store_true",
        help="process only ingestion jobs",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
    if arguments.scan_only:
        worker: LibraryScanWorker | IngestionWorker | CompositeWorker = build_scan_worker(
            settings,
            worker_id=worker_id,
        )
    elif arguments.ingestion_only:
        worker = build_ingestion_worker(settings, worker_id=worker_id)
    else:
        scan_worker = build_scan_worker(settings, worker_id=worker_id)
        worker = CompositeWorker(
            scan_worker=scan_worker,
            ingestion_factory=lambda: build_ingestion_worker(settings, worker_id=worker_id),
        )
    if arguments.once:
        worker.run_once()
        return
    while True:
        if not worker.run_once():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
