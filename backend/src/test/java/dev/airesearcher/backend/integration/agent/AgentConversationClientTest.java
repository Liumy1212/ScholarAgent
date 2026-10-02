package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;

import java.net.URI;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentConversationClientTest {

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void forwardsPaginationAndRequestIdAndDecodesDirectDto() {
        AtomicReference<String> requestLine = new AtomicReference<>();
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    requestLine.set(request.method().name() + " " + request.uri());
                    requestId.set(request.requestHeaders().get("X-Request-Id"));
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("""
                                    {"items":[{"conversationId":"conversation-001","title":"Question","preview":"Answer","scope":{"type":"ALL","scopeId":null,"paperIds":[]},"turnCount":1,"createdAt":"2026-01-01T00:00:00Z","updatedAt":"2026-01-01T00:01:00Z"}],"total":1,"offset":5,"limit":20}
                                    """))
                            .then();
                })
                .bindNow();

        var result = client().list(5, 20, "req-conversations");

        assertThat(requestLine).hasValue("GET /agent-api/v1/conversations?offset=5&limit=20");
        assertThat(requestId).hasValue("req-conversations");
        assertThat(result.items()).singleElement().satisfies(summary -> {
            assertThat(summary.conversationId()).isEqualTo("conversation-001");
            assertThat(summary.scope().type()).isEqualTo("ALL");
        });
    }

    @Test
    void decodesConversationDetailSuccessAndPreservesRequestId() {
        AtomicReference<String> requestLine = new AtomicReference<>();
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    requestLine.set(request.method().name() + " " + request.uri());
                    requestId.set(request.requestHeaders().get("X-Request-Id"));
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("""
                                    {"conversation":{"conversationId":"conversation-001","title":"Question","preview":"Answer","scope":{"type":"PAPERS","scopeId":null,"paperIds":["paper-1"]},"turnCount":1,"createdAt":"2026-01-01T00:00:00Z","updatedAt":"2026-01-01T00:01:00Z"},"turns":[{"runId":"run-001","requestId":"req-turn","assistantMessageId":"message-001","question":"历史问题","answer":"历史回答","answerMode":"KNOWLEDGE_BASE","tools":[{"toolCallId":"tool-001","toolName":"knowledge_base_search","status":"COMPLETED","errorCode":null}],"citations":[{"citationId":"citation-001","paperId":"paper-1","paperTitle":"Synthetic","pageNumber":3,"quote":"evidence","chunkId":"chunk-001"}],"createdAt":"2026-01-01T00:00:00Z","completedAt":"2026-01-01T00:01:00Z"}],"totalTurns":1,"truncated":false}
                                    """))
                            .then();
                })
                .bindNow();

        var result = client().get("conversation-001", "req-detail");

        assertThat(requestLine).hasValue("GET /agent-api/v1/conversations/conversation-001");
        assertThat(requestId).hasValue("req-detail");
        assertThat(result.conversation().conversationId()).isEqualTo("conversation-001");
        assertThat(result.totalTurns()).isEqualTo(1);
        assertThat(result.truncated()).isFalse();
        assertThat(result.turns()).singleElement().satisfies(turn -> {
            assertThat(turn.runId()).isEqualTo("run-001");
            assertThat(turn.answerMode()).isEqualTo("KNOWLEDGE_BASE");
            assertThat(turn.citations()).singleElement().satisfies(citation -> {
                assertThat(citation.paperId()).isEqualTo("paper-1");
                assertThat(citation.pageNumber()).isEqualTo(3);
            });
        });
    }

    @Test
    void preservesConversationNotFoundFromAgent() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(404)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"CONVERSATION_NOT_FOUND","message":"未找到会话。","requestId":"req-missing","retryable":false}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().get("missing", "req-missing"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status()).isEqualTo(HttpStatus.NOT_FOUND);
                    assertThat(exception.code()).isEqualTo("CONVERSATION_NOT_FOUND");
                    assertThat(exception.retryable()).isFalse();
                });
    }

    @Test
    void mapsConversationDatabaseFailureToRetryableAgentUnavailable() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(503)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"DATABASE_UNAVAILABLE","message":"会话数据库暂时不可用。","requestId":"req-database","retryable":true}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().list(0, 50, "req-database"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status()).isEqualTo(HttpStatus.BAD_GATEWAY);
                    assertThat(exception.code()).isEqualTo("AGENT_UNAVAILABLE");
                    assertThat(exception.retryable()).isTrue();
                });
    }

    @Test
    void mapsMalformedSuccessfulResponseToProtocolError() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(200)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("not-json"))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().get("conversation-001", "req-protocol"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status()).isEqualTo(HttpStatus.BAD_GATEWAY);
                    assertThat(exception.code()).isEqualTo("AGENT_ERROR");
                });
    }

    private AgentConversationClient client() {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentConversationClient(
                WebClient.builder().baseUrl(baseUrl.toString()).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), Duration.ofSeconds(2))
        );
    }
}
