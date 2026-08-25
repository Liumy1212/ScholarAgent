package dev.airesearcher.backend.integration.agent;

import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

public record AgentSseStream(Flux<ServerSentEvent<String>> events) {
}
