from dataclasses import dataclass
from datetime import datetime

from airesearcher_agent.domain.papers import PaperView


@dataclass(frozen=True, slots=True)
class KnowledgeBaseView:
    knowledge_base_id: str
    name: str
    paper_count: int
    searchable_paper_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeBasesPageView:
    items: tuple[KnowledgeBaseView, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class KnowledgeBasePapersPageView:
    items: tuple[PaperView, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class KnowledgeBaseMembersUpdateView:
    knowledge_base: KnowledgeBaseView
    added_paper_ids: tuple[str, ...]
    removed_paper_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeleteKnowledgeBaseView:
    knowledge_base_id: str
    deleted: bool = True


@dataclass(frozen=True, slots=True)
class ResolvedChatScope:
    scope_type: str
    scope_key: str
    scope_id: str | None
    paper_ids: tuple[str, ...]
