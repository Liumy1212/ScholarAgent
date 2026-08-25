package dev.airesearcher.backend.chat;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import org.springframework.http.codec.ServerSentEvent;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

final class SseStreamState {

    private static final String SCHEMA_VERSION = "1.0";

    private final String requestId;
    private final String conversationId;
    private final ObjectMapper objectMapper;

    private String runId;
    private String assistantMessageId;
    private long lastSequence = -1;
    private boolean terminal;

    SseStreamState(String requestId, String conversationId, ObjectMapper objectMapper) {
        this.requestId = requestId;
        this.conversationId = conversationId;
        this.objectMapper = objectMapper;
    }

    synchronized void observe(ServerSentEvent<String> event) {
        if (event.data() == null) {
            return;
        }
        try {
            JsonNode envelope = objectMapper.readTree(event.data());
            if (!envelope.isObject()) {
                return;
            }
            if (envelope.hasNonNull("runId")) {
                runId = envelope.get("runId").asText();
            }
            if (envelope.hasNonNull("assistantMessageId")) {
                assistantMessageId = envelope.get("assistantMessageId").asText();
            }
            if (envelope.path("sequence").canConvertToLong()) {
                lastSequence = envelope.get("sequence").asLong();
            }
            String type = envelope.path("type").asText();
            terminal = "run.completed".equals(type) || "run.failed".equals(type);
        } catch (JacksonException ignored) {
            // The BFF forwards the downstream envelope verbatim. Parsing is only for failure continuity.
        }
    }

    synchronized boolean isTerminal() {
        return terminal;
    }

    synchronized List<ServerSentEvent<String>> failureEvents(String code, String message) {
        if (terminal) {
            return List.of();
        }
        List<ServerSentEvent<String>> events = new ArrayList<>(2);
        ensureIdentifiers();
        if (lastSequence < 0) {
            ServerSentEvent<String> started = event("run.started", 0, objectMapper.createObjectNode());
            events.add(started);
            lastSequence = 0;
        }

        ObjectNode payload = objectMapper.createObjectNode();
        payload.put("code", code);
        payload.put("message", message);
        payload.put("retryable", true);
        ServerSentEvent<String> failed = event("run.failed", lastSequence + 1, payload);
        events.add(failed);
        lastSequence++;
        terminal = true;
        return List.copyOf(events);
    }

    private void ensureIdentifiers() {
        if (runId == null || runId.isBlank()) {
            runId = "run-bff-" + UUID.randomUUID();
        }
        if (assistantMessageId == null || assistantMessageId.isBlank()) {
            assistantMessageId = "msg-bff-" + UUID.randomUUID();
        }
    }

    private ServerSentEvent<String> event(String type, long sequence, ObjectNode payload) {
        String eventId = "evt-bff-" + UUID.randomUUID();
        ObjectNode envelope = objectMapper.createObjectNode();
        envelope.put("schemaVersion", SCHEMA_VERSION);
        envelope.put("type", type);
        envelope.put("eventId", eventId);
        envelope.put("requestId", requestId);
        envelope.put("runId", runId);
        envelope.put("conversationId", conversationId);
        envelope.put("assistantMessageId", assistantMessageId);
        envelope.put("sequence", sequence);
        envelope.put("timestamp", Instant.now().toString());
        envelope.set("payload", payload);
        return ServerSentEvent.<String>builder(writeEnvelope(envelope))
                .event(type)
                .id(eventId)
                .build();
    }

    private String writeEnvelope(ObjectNode envelope) {
        try {
            return objectMapper.writeValueAsString(envelope);
        } catch (JacksonException exception) {
            throw new IllegalStateException("Unable to serialize the SSE failure envelope", exception);
        }
    }
}
