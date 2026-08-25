package dev.airesearcher.backend.chat;

import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SseStreamStateTest {

    @Test
    void createsStartedAndFailedTerminalEventsWhenAgentFailsBeforeFirstDataEvent() {
        ObjectMapper objectMapper = new ObjectMapper();
        SseStreamState state = new SseStreamState("req-001", "conv-001", objectMapper);

        List<ServerSentEvent<String>> events = state.failureEvents("AGENT_STREAM_FAILURE", "stream failed");

        assertThat(events).extracting(ServerSentEvent::event)
                .containsExactly("run.started", "run.failed");
        JsonNode started = objectMapper.readTree(events.getFirst().data());
        JsonNode failed = objectMapper.readTree(events.getLast().data());
        assertThat(started.path("sequence").asLong()).isZero();
        assertThat(failed.path("sequence").asLong()).isEqualTo(1);
        assertThat(failed.path("runId").asText()).isEqualTo(started.path("runId").asText());
        assertThat(failed.path("assistantMessageId").asText())
                .isEqualTo(started.path("assistantMessageId").asText());
        assertThat(failed.path("requestId").asText()).isEqualTo("req-001");
        assertThat(failed.path("conversationId").asText()).isEqualTo("conv-001");
        assertThat(events.getLast().id()).isEqualTo(failed.path("eventId").asText());
        assertThat(state.isTerminal()).isTrue();
    }
}
