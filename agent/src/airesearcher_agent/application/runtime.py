from dataclasses import dataclass

from airesearcher_agent.application.library_files import LibraryFileService
from airesearcher_agent.application.library_lifecycle import LibraryLifecycleService
from airesearcher_agent.application.library_scans import LibraryScanService
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.application.runs import AgentRunStore
from airesearcher_agent.application.stream_chat import StreamChatUseCase
from airesearcher_agent.config import Settings
from airesearcher_agent.persistence.database import Database
from airesearcher_agent.providers.deepseek import DeepSeekToolCallingProvider
from airesearcher_agent.providers.deepseek_client import DeepSeekHttpClient
from airesearcher_agent.retrieval.local_models import BgeM3EmbeddingProvider, BgeReranker
from airesearcher_agent.retrieval.qdrant_store import QdrantVectorStore
from airesearcher_agent.retrieval.tools import RetrievalTools


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    settings: Settings
    database: Database
    library_file_service: LibraryFileService
    library_lifecycle_service: LibraryLifecycleService
    library_scan_service: LibraryScanService
    paper_service: PaperService
    stream_chat: StreamChatUseCase


def build_runtime(settings: Settings | None = None) -> RuntimeServices:
    selected = settings or Settings()
    database = Database(selected.database_url)
    vector_store = QdrantVectorStore.from_settings(selected)
    embedding = BgeM3EmbeddingProvider(selected)
    reranker = BgeReranker(selected)
    retrieval_tools = RetrievalTools(
        database=database,
        embedding=embedding,
        reranker=reranker,
        vector_store=vector_store,
        settings=selected,
    )
    gateway = DeepSeekHttpClient(
        base_url=selected.deepseek_base_url,
        api_key=selected.deepseek_api_key.get_secret_value(),
        model=selected.deepseek_model,
        timeout_seconds=selected.deepseek_timeout_seconds,
    )
    provider = DeepSeekToolCallingProvider(
        gateway=gateway,
        tools=retrieval_tools,
        run_store=AgentRunStore(database),
        settings=selected,
    )
    library_file_service = LibraryFileService(database=database, settings=selected)
    library_scan_service = LibraryScanService(
        database=database,
        settings=selected,
        library_file_service=library_file_service,
    )
    library_lifecycle_service = LibraryLifecycleService(
        database=database,
        settings=selected,
        vector_store=vector_store,
        library_file_service=library_file_service,
    )
    return RuntimeServices(
        settings=selected,
        database=database,
        library_file_service=library_file_service,
        library_lifecycle_service=library_lifecycle_service,
        library_scan_service=library_scan_service,
        paper_service=PaperService(
            database=database,
            settings=selected,
            vector_store=vector_store,
            library_file_service=library_file_service,
            library_lifecycle_service=library_lifecycle_service,
        ),
        stream_chat=StreamChatUseCase(provider),
    )
