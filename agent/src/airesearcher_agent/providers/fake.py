from collections.abc import AsyncIterator
from uuid import NAMESPACE_URL, uuid5

from airesearcher_agent.application.ports import ChatProviderError
from airesearcher_agent.domain.chat import (
    AnswerCompleted,
    ChatPrompt,
    Citation,
    MessageDelta,
    ProviderEvent,
)

FAKE_FAILURE_CONTENT = "__FAKE_PROVIDER_FAILURE__"


class FakeChatProvider:
    """Deterministic Phase 0 provider with no external dependencies."""

    async def stream(self, prompt: ChatPrompt) -> AsyncIterator[ProviderEvent]:
        if prompt.content == FAKE_FAILURE_CONTENT:
            raise ChatProviderError(
                code="PROVIDER_FAILURE",
                message="Synthetic provider failure for contract validation.",
                retryable=True,
            )

        yield MessageDelta("这是 Phase 0 的确定性模拟回答。")
        yield MessageDelta(f"收到的问题是: {prompt.content}")

        paper_ids = prompt.paper_ids or ("paper-demo-001",)
        for position, paper_id in enumerate(paper_ids, start=1):
            citation_seed = f"{prompt.content}\0{paper_id}\0{position}"
            citation_id = f"citation-{uuid5(NAMESPACE_URL, citation_seed).hex}"
            yield Citation(
                citation_id=citation_id,
                paper_id=paper_id,
                paper_title=f"Synthetic Research Paper {position}",
                page_number=position,
                quote=f"Synthetic, redistributable evidence for {paper_id}.",
                chunk_id=f"chunk-demo-{position:03d}",
            )
        yield AnswerCompleted("KNOWLEDGE_BASE")
