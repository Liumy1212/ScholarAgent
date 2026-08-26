import asyncio

import pytest

from airesearcher_agent.application.ports import ChatProviderError
from airesearcher_agent.domain.chat import ChatPrompt, Citation, ProviderEvent
from airesearcher_agent.providers.fake import FAKE_FAILURE_CONTENT, FakeChatProvider


async def _collect(prompt: ChatPrompt) -> list[ProviderEvent]:
    return [event async for event in FakeChatProvider().stream(prompt)]


def test_fake_provider_is_deterministic_and_creates_selected_paper_citations() -> None:
    prompt = ChatPrompt(
        run_id="run-test-001",
        conversation_id="conv-test-001",
        assistant_message_id="msg-test-001",
        content="比较方法",
        paper_ids=("paper-001", "paper-002"),
    )

    first = asyncio.run(_collect(prompt))
    second = asyncio.run(_collect(prompt))

    assert first == second
    citations = [event for event in first if isinstance(event, Citation)]
    assert [citation.paper_id for citation in citations] == ["paper-001", "paper-002"]
    assert all(citation.page_number >= 1 for citation in citations)


def test_fake_provider_creates_default_synthetic_citation() -> None:
    events = asyncio.run(
        _collect(
            ChatPrompt(
                run_id="run-test-002",
                conversation_id="conv-test-002",
                assistant_message_id="msg-test-002",
                content="概括观点",
                paper_ids=(),
            )
        )
    )

    citations = [event for event in events if isinstance(event, Citation)]
    assert len(citations) == 1
    assert citations[0].paper_id == "paper-demo-001"


def test_fake_provider_exposes_deterministic_failure_flow() -> None:
    async def consume_failure() -> None:
        prompt = ChatPrompt(
            run_id="run-test-failure",
            conversation_id="conv-test-failure",
            assistant_message_id="msg-test-failure",
            content=FAKE_FAILURE_CONTENT,
            paper_ids=(),
        )
        async for _event in FakeChatProvider().stream(prompt):
            pass

    with pytest.raises(ChatProviderError) as captured:
        asyncio.run(consume_failure())

    assert captured.value.code == "PROVIDER_FAILURE"
    assert captured.value.retryable is True
