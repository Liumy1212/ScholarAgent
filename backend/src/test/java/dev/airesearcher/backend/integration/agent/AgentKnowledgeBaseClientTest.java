package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.knowledgebase.KnowledgeBaseMembersRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;

import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class AgentKnowledgeBaseClientTest {

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void forwardsOnlyContractFieldsForMemberUpdate() {
        AtomicReference<String> requestBody = new AtomicReference<>();
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> request.receive().aggregate().asString()
                        .flatMap(body -> {
                            requestBody.set(body);
                            requestId.set(request.requestHeaders().get("X-Request-Id"));
                            return response.status(200)
                                    .header("Content-Type", "application/json")
                                    .sendString(Mono.just("""
                                            {"knowledgeBase":{"knowledgeBaseId":"kb-001","name":"Synthetic","paperCount":1,"searchablePaperCount":1,"createdAt":"2026-01-01T00:00:00Z","updatedAt":"2026-01-01T00:01:00Z"},"addedPaperIds":["paper-001"],"removedPaperIds":[]}
                                            """))
                                    .then();
                        }))
                .bindNow();

        AgentKnowledgeBaseClient client = client();
        var result = client.updateMembers(
                "kb-001",
                new KnowledgeBaseMembersRequest(List.of("paper-001"), List.of()),
                "req-kb-members"
        );

        assertThat(requestId).hasValue("req-kb-members");
        assertThat(requestBody).hasValue(
                "{\"addPaperIds\":[\"paper-001\"],\"removePaperIds\":[]}"
        );
        assertThat(result.addedPaperIds()).containsExactly("paper-001");
    }

    private AgentKnowledgeBaseClient client() {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentKnowledgeBaseClient(
                WebClient.builder().baseUrl(baseUrl.toString()).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), Duration.ofSeconds(2))
        );
    }
}
