package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;

import java.net.URI;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentPaperClientTest {

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void decodesDirectAgentDtoAndForwardsRequestId() {
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    requestId.set(request.requestHeaders().get("X-Request-Id"));
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("""
                                    {"items":[{"paperId":"paper-001","title":"Grounded Paper","authors":["Ada Example"],"publicationYear":2026,"fileName":"paper.pdf","fileSizeBytes":1024,"libraryRelativePath":"uploads/paper.pdf","sourceStatus":"AVAILABLE","status":"READY","searchable":true,"pageCount":2,"createdAt":"2026-01-01T00:00:00Z","updatedAt":"2026-01-01T00:01:00Z","currentIngestion":{"jobId":"job-001","status":"SUCCEEDED","stage":"COMPLETED","attempt":1,"maxAttempts":3,"canRetry":false,"failure":null}}],"total":1}
                                    """))
                            .then();
                })
                .bindNow();

        var result = client().list("req-paper-list");

        assertThat(requestId).hasValue("req-paper-list");
        assertThat(result.total()).isEqualTo(1);
        assertThat(result.items()).singleElement().satisfies(paper -> {
            assertThat(paper.paperId()).isEqualTo("paper-001");
            assertThat(paper.pageCount()).isEqualTo(2);
            assertThat(paper.currentIngestion().stage()).isEqualTo("COMPLETED");
        });
    }

    @Test
    void preservesSafeAgentClientErrorCodeAndHttpStatus() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(404)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"PAPER_NOT_FOUND","message":"未找到指定论文。","requestId":"req-missing","retryable":false}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().get("paper-missing", "req-missing"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status().value()).isEqualTo(404);
                    assertThat(exception.code()).isEqualTo("PAPER_NOT_FOUND");
                    assertThat(exception.retryable()).isFalse();
                });
    }

    private AgentPaperClient client() {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentPaperClient(
                WebClient.builder().baseUrl(baseUrl.toString()).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), Duration.ofSeconds(2))
        );
    }
}
