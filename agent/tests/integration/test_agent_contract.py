import asyncio
import json
from pathlib import Path
from typing import Any, cast

from httpx import ASGITransport, AsyncClient, Response
from jsonschema import Draft202012Validator, FormatChecker
from tests.helpers import ParsedSseEvent, assert_valid_lifecycle, parse_sse

from airesearcher_agent.main import create_app
from airesearcher_agent.providers.fake import FAKE_FAILURE_CONTENT, FakeChatProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SSE_CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "sse" / "v1"
AGENT_ROUTE = "/agent-api/v1/conversations/conv-integration-001/messages/stream"


def _load_schema(filename: str) -> dict[str, Any]:
    content = (SSE_CONTRACT_ROOT / filename).read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(content))


def _assert_events_match_contract(events: list[ParsedSseEvent]) -> None:
    schema = _load_schema("sse-event.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for event in events:
        validator.validate(event.data)


def _post(
    *,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> Response:
    async def send() -> Response:
        transport = ASGITransport(app=create_app(FakeChatProvider()))
        async with AsyncClient(transport=transport, base_url="http://agent.test") as client:
            return await client.post(AGENT_ROUTE, headers=headers, json=body)

    return asyncio.run(send())


def test_normal_stream_matches_sse_contract_and_echoes_request_id() -> None:
    response = _post(
        headers={"X-Request-Id": "req-integration-001"},
        body={"content": "请概括知识库中的主要观点。", "paperIds": []},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-integration-001"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Content-Type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    assert [event.event for event in events] == [
        "run.started",
        "message.delta",
        "message.delta",
        "citation.created",
        "run.completed",
    ]
    assert_valid_lifecycle(events)
    _assert_events_match_contract(events)


def test_selected_papers_create_only_matching_synthetic_citations() -> None:
    response = _post(
        headers={"X-Request-Id": "req-integration-002"},
        body={
            "content": "比较这两篇论文的方法。",
            "paperIds": ["paper-demo-001", "paper-demo-002"],
        },
    )

    events = parse_sse(response.text)
    citations = [event.data["payload"] for event in events if event.event == "citation.created"]
    assert [citation["paperId"] for citation in citations] == [
        "paper-demo-001",
        "paper-demo-002",
    ]
    assert_valid_lifecycle(events)
    _assert_events_match_contract(events)


def test_provider_failure_is_a_single_contract_valid_terminal_event() -> None:
    response = _post(
        headers={"X-Request-Id": "req-integration-failed"},
        body={"content": FAKE_FAILURE_CONTENT, "paperIds": []},
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [event.event for event in events] == ["run.started", "run.failed"]
    assert events[-1].data["payload"] == {
        "code": "PROVIDER_FAILURE",
        "message": "Synthetic provider failure for contract validation.",
        "retryable": True,
    }
    assert_valid_lifecycle(events)
    _assert_events_match_contract(events)


def test_invalid_body_uses_contract_open_error_instead_of_422() -> None:
    response = _post(
        headers={"X-Request-Id": "req-invalid-001"},
        body={"content": "", "paperIds": [], "unexpected": True},
    )

    assert response.status_code == 400
    assert response.headers["X-Request-Id"] == "req-invalid-001"
    body = response.json()
    assert body["requestId"] == "req-invalid-001"
    assert body["code"] == "INVALID_REQUEST"
    schema = _load_schema("stream-open-error.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(body)


def test_missing_request_id_gets_contract_valid_open_error_trace_id() -> None:
    response = _post(body={"content": "valid", "paperIds": []})

    assert response.status_code == 400
    body = response.json()
    assert body["requestId"] == response.headers["X-Request-Id"]
    schema = _load_schema("stream-open-error.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(body)


def test_duplicate_paper_ids_are_rejected_before_stream_opens() -> None:
    response = _post(
        headers={"X-Request-Id": "req-invalid-duplicates"},
        body={"content": "valid", "paperIds": ["paper-001", "paper-001"]},
    )

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
