import argparse
import logging
import os
import socket
import time
from uuid import uuid4

from airesearcher_agent.config import Settings
from airesearcher_agent.ingestion.pdf import PdfParser
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.retrieval.local_models import BgeM3EmbeddingProvider
from airesearcher_agent.retrieval.qdrant_store import QdrantVectorStore
from airesearcher_agent.worker.service import IngestionWorker


def build_worker(settings: Settings) -> IngestionWorker:
    worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
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


def main() -> None:
    parser = argparse.ArgumentParser(description="AIResearcher leased ingestion worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    worker = build_worker(settings)
    if arguments.once:
        worker.run_once()
        return
    while True:
        if not worker.run_once():
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
