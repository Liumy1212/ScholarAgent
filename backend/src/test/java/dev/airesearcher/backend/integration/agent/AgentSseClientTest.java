package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.api.ResultCode;
import dev.airesearcher.backend.common.error.StreamOpenException;
import dev.airesearcher.backend.support.ContractSseFixtures;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentSseClientTest {

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void forwardsRequestIdAndDecodesContractSseFields() throws Exception {
        AtomicReference<String> receivedRequestId = new AtomicReference<>();
        AtomicReference<String> receivedBody = new AtomicReference<>();
        String contractStream = ContractSseFixtures.completedStreamText();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> request.receive().aggregate().asString()
                        .flatMap(body -> {
                            receivedRequestId.set(request.requestHeaders().get("X-Request-Id"));
                            receivedBody.set(body);
                            return response.status(200)
                                    .header("Content-Type", "text/event-stream")
                                    .header("X-Request-Id", "req-demo-001")
                                    .sendString(Mono.just(contractStream))
                                    .then();
                        }))
                .bindNow();
        AgentSseClient client = client(Duration.ofSeconds(1));

        AgentSseStream stream = client.openStream(
                "conv-demo-001",
                new AgentChatStreamRequest("question", List.of("paper-demo-001")),
                "req-demo-001"
        );
        List<ServerSentEvent<String>> events = stream.events().collectList().block(Duration.ofSeconds(2));

        assertThat(receivedRequestId).hasValue("req-demo-001");
        assertThat(receivedBody.get()).contains("\"content\":\"question\"")
                .contains("\"paperIds\":[\"paper-demo-001\"]");
        assertThat(events).isNotNull();
        List<ServerSentEvent<String>> dataEvents = events.stream()
                .filter(event -> event.data() != null)
                .toList();
        assertThat(dataEvents).hasSize(6);
        assertThat(dataEvents.get(1).event()).isEqualTo("tool.status");
        assertThat(dataEvents.get(2).event()).isEqualTo("tool.status");
        assertThat(dataEvents.get(3).event()).isEqualTo("message.delta");
        assertThat(dataEvents.get(3).id()).isEqualTo("evt-demo-002");
        assertThat(dataEvents.get(3).data()).contains("\"type\":\"message.delta\"");
    }

    @Test
    void mapsAgent503BeforeOpenToBadGateway() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(503)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"PROVIDER_UNAVAILABLE","message":"unavailable","requestId":"req-503","retryable":true}
                                """))
                        .then())
                .bindNow();
        AgentSseClient client = client(Duration.ofSeconds(1));

        assertThatThrownBy(() -> client.openStream(
                "conv-001",
                new AgentChatStreamRequest("question", List.of()),
                "req-503"
        )).isInstanceOfSatisfying(StreamOpenException.class, exception ->
                assertThat(exception.resultCode()).isEqualTo(ResultCode.AGENT_UNAVAILABLE));
    }

    @Test
    void preservesAgent400ValidationDetails() throws Exception {
        String openError = ContractSseFixtures.streamOpenErrorText();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(400)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just(openError))
                        .then())
                .bindNow();
        AgentSseClient client = client(Duration.ofSeconds(1));

        assertThatThrownBy(() -> client.openStream(
                "conv-001",
                new AgentChatStreamRequest("question", List.of()),
                "req-open-error-001"
        )).isInstanceOfSatisfying(StreamOpenException.class, exception -> {
            assertThat(exception.resultCode()).isEqualTo(ResultCode.INVALID_REQUEST);
            assertThat(exception.getMessage()).isEqualTo("Request validation failed.");
            assertThat(exception.details()).singleElement()
                    .satisfies(detail -> assertThat(detail.field()).isEqualTo("content"));
        });
    }

    @Test
    void mapsOpenTimeoutToGatewayTimeout() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> Mono.delay(Duration.ofMillis(250))
                        .then(Mono.defer(() -> response.status(200)
                                .header("Content-Type", "text/event-stream")
                                .sendString(Mono.just("event: run.started\n\n"))
                                .then())))
                .bindNow();
        AgentSseClient client = client(Duration.ofMillis(50));

        assertThatThrownBy(() -> client.openStream(
                "conv-001",
                new AgentChatStreamRequest("question", List.of()),
                "req-timeout-001"
        )).isInstanceOfSatisfying(StreamOpenException.class, exception ->
                assertThat(exception.resultCode()).isEqualTo(ResultCode.AGENT_TIMEOUT));
    }

    @Test
    void rejectsSuccessfulResponseWithWrongContentTypeBeforeOpen() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(200)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("{}"))
                        .then())
                .bindNow();
        AgentSseClient client = client(Duration.ofSeconds(1));

        assertThatThrownBy(() -> client.openStream(
                "conv-001",
                new AgentChatStreamRequest("question", List.of()),
                "req-content-type-001"
        )).isInstanceOfSatisfying(StreamOpenException.class, exception ->
                assertThat(exception.resultCode()).isEqualTo(ResultCode.AGENT_ERROR));
    }

    private AgentSseClient client(Duration openTimeout) {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentSseClient(
                WebClient.builder().baseUrl(baseUrl.toString()).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), openTimeout),
                new ObjectMapper()
        );
    }
}
