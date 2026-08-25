import json
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class ParsedSseEvent:
    event: str
    event_id: str
    data: dict[str, Any]


def parse_sse(stream: str) -> list[ParsedSseEvent]:
    parsed: list[ParsedSseEvent] = []
    for block in stream.strip().split("\n\n"):
        lines = block.splitlines()
        if all(line.startswith(":") for line in lines):
            continue
        assert len(lines) == 3
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("id: ")
        assert lines[2].startswith("data: ")
        event = lines[0].removeprefix("event: ")
        event_id = lines[1].removeprefix("id: ")
        data = cast(dict[str, Any], json.loads(lines[2].removeprefix("data: ")))
        assert data["type"] == event
        assert data["eventId"] == event_id
        parsed.append(ParsedSseEvent(event=event, event_id=event_id, data=data))
    return parsed


def assert_valid_lifecycle(events: list[ParsedSseEvent]) -> None:
    assert events
    assert events[0].event == "run.started"
    assert [event.data["sequence"] for event in events] == list(range(len(events)))
    assert len({event.event_id for event in events}) == len(events)

    terminal_types = {"run.completed", "run.failed"}
    terminals = [event for event in events if event.event in terminal_types]
    assert len(terminals) == 1
    assert events[-1] == terminals[0]

    for field in ("requestId", "runId", "conversationId", "assistantMessageId"):
        assert len({event.data[field] for event in events}) == 1
