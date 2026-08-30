package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentFileClientTest {

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void forwardsRangeAndPreservesPdfHeadersAndBody() throws Exception {
        AtomicReference<String> range = new AtomicReference<>();
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    range.set(request.requestHeaders().get("Range"));
                    requestId.set(request.requestHeaders().get("X-Request-Id"));
                    return response.status(206)
                            .header("Content-Type", "application/pdf")
                            .header("Content-Length", "5")
                            .header("Content-Range", "bytes 5-9/15")
                            .header("Accept-Ranges", "bytes")
                            .header("ETag", "\"sha256-demo\"")
                            .sendByteArray(Mono.just("01234".getBytes()))
                            .then();
                })
                .bindNow();

        AgentFileResponse response = client().open("paper-001", "bytes=5-9", "req-file");

        try (var body = response.body()) {
            assertThat(body.readAllBytes()).isEqualTo("01234".getBytes());
        }
        assertThat(range).hasValue("bytes=5-9");
        assertThat(requestId).hasValue("req-file");
        assertThat(response.statusCode()).isEqualTo(206);
        assertThat(response.headers().getFirst("Content-Range")).isEqualTo("bytes 5-9/15");
        assertThat(response.headers().getFirst("Content-Length")).isEqualTo("5");
        assertThat(response.headers().getETag()).isEqualTo("\"sha256-demo\"");
    }

    @Test
    void convertsAgentRangeErrorWithoutWrappingItAsPdf() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(416)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"INVALID_RANGE","message":"请求的 PDF 字节范围无效。","requestId":"req-range","retryable":false}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().open("paper-001", "bytes=99-100", "req-range"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status().value()).isEqualTo(416);
                    assertThat(exception.code()).isEqualTo("INVALID_RANGE");
                });
    }

    @Test
    void opensLibraryOriginalThroughItsDedicatedAgentPath() throws Exception {
        AtomicReference<String> path = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    path.set(request.uri());
                    return response.status(200)
                            .header("Content-Type", "application/pdf")
                            .header("Content-Length", "5")
                            .header("Accept-Ranges", "bytes")
                            .header("ETag", "\"sha256-library\"")
                            .sendByteArray(Mono.just("%PDF-".getBytes()))
                            .then();
                })
                .bindNow();

        AgentFileResponse response = client().openLibraryFile(
                "library-file-001",
                null,
                "req-library-file"
        );

        try (var body = response.body()) {
            assertThat(body.readAllBytes()).isEqualTo("%PDF-".getBytes());
        }
        assertThat(path).hasValue("/agent-api/v1/library/files/library-file-001/file");
        assertThat(response.headers().getFirst("Content-Length")).isEqualTo("5");
        assertThat(response.headers().getETag()).isEqualTo("\"sha256-library\"");
    }

    private AgentFileClient client() {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentFileClient(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), Duration.ofSeconds(2)),
                new ObjectMapper()
        );
    }
}
