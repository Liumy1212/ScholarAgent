package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.library.LibraryScanItemOutcome;
import dev.airesearcher.backend.library.LibraryStateFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;

import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentLibraryClientTest {

    private static final String LIBRARY_FILE_JSON = """
            {"libraryFileId":"library-file-001","relativePath":"folder/paper.pdf","fileName":"paper.pdf","fileSizeBytes":1024,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sourceStatus":"AVAILABLE","knowledgeStatus":"NOT_INGESTED","paperId":null,"paperTitle":null,"searchable":false,"currentIngestion":null,"discoveredAt":"2026-08-30T00:00:00Z","lastSeenAt":"2026-08-30T00:00:00Z","updatedAt":"2026-08-30T00:00:00Z"}
            """;
    private static final String PAPER_JSON = """
            {"paperId":"paper-001","title":"Paper","authors":[],"publicationYear":null,"fileName":"paper.pdf","fileSizeBytes":1024,"libraryRelativePath":"folder/paper.pdf","sourceStatus":"AVAILABLE","status":"PROCESSING","searchable":false,"pageCount":null,"createdAt":"2026-08-30T00:00:00Z","updatedAt":"2026-08-30T00:00:00Z","currentIngestion":{"jobId":"job-001","status":"QUEUED","stage":"QUEUED","attempt":0,"maxAttempts":3,"canRetry":false,"failure":null}}
            """;
    private static final String INGESTED_LIBRARY_FILE_JSON = """
            {"libraryFileId":"library-file-001","relativePath":"folder/paper.pdf","fileName":"paper.pdf","fileSizeBytes":1024,"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sourceStatus":"AVAILABLE","knowledgeStatus":"PROCESSING","paperId":"paper-001","paperTitle":"Paper","searchable":false,"currentIngestion":{"jobId":"job-001","status":"QUEUED","stage":"QUEUED","attempt":0,"maxAttempts":3,"canRetry":false,"failure":null},"discoveredAt":"2026-08-30T00:00:00Z","lastSeenAt":"2026-08-30T00:00:00Z","updatedAt":"2026-08-30T00:00:00Z"}
            """;
    private static final String JOB_JSON = """
            {"jobId":"job-001","paperId":"paper-001","status":"QUEUED","stage":"QUEUED","attempt":0,"maxAttempts":3,"canRetry":false,"failure":null,"createdAt":"2026-08-30T00:00:00Z","startedAt":null,"completedAt":null}
            """;

    private DisposableServer server;

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.disposeNow();
        }
    }

    @Test
    void forwardsLibraryFilePaginationAndRequestId() {
        AtomicReference<String> uri = new AtomicReference<>();
        AtomicReference<String> requestId = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    uri.set(request.uri());
                    requestId.set(request.requestHeaders().get("X-Request-Id"));
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("{\"items\":[" + LIBRARY_FILE_JSON
                                    + "],\"total\":21,\"offset\":20,\"limit\":10}"))
                            .then();
                })
                .bindNow();

        var page = client().listFiles(20, 10, null, "req-library-list");

        assertThat(uri).hasValue("/agent-api/v1/library/files?offset=20&limit=10");
        assertThat(requestId).hasValue("req-library-list");
        assertThat(page.total()).isEqualTo(21);
        assertThat(page.offset()).isEqualTo(20);
        assertThat(page.limit()).isEqualTo(10);
        assertThat(page.items()).singleElement().satisfies(item -> {
            assertThat(item.libraryFileId()).isEqualTo("library-file-001");
            assertThat(item.knowledgeStatus()).isEqualTo("NOT_INGESTED");
        });
    }

    @Test
    void forwardsLibraryStateWithoutRecomputingThePage() {
        AtomicReference<String> uri = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    uri.set(request.uri());
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("{\"items\":[],\"total\":7,\"offset\":0,\"limit\":25}"))
                            .then();
                })
                .bindNow();

        var page = client().listFiles(
                0,
                25,
                LibraryStateFilter.ORIGINAL_MISSING,
                "req-filtered-library-list"
        );

        assertThat(uri).hasValue(
                "/agent-api/v1/library/files?offset=0&limit=25&libraryState=ORIGINAL_MISSING"
        );
        assertThat(page.total()).isEqualTo(7);
    }

    @Test
    void decodesOriginalsPathFromLibraryInfo() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(200)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"rootPath":"D:/papers","originalsPath":"D:/papers/originals","supportedExtensions":[".pdf"],"scanInProgress":false,"latestScan":null}
                                """))
                        .then())
                .bindNow();

        var info = client().getLibrary("req-library-info");

        assertThat(info.rootPath()).isEqualTo("D:/papers");
        assertThat(info.originalsPath()).isEqualTo("D:/papers/originals");
    }

    @Test
    void rejectsLibraryInfoWithoutOriginalsPathAsProtocolError() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(200)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"rootPath":"D:/papers","supportedExtensions":[".pdf"],"scanInProgress":false,"latestScan":null}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().getLibrary("req-library-info"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status().value()).isEqualTo(502);
                    assertThat(exception.code()).isEqualTo("AGENT_ERROR");
                });
    }

    @Test
    void uploadsOnlyToTheLibraryFileEndpoint() {
        AtomicReference<String> requestLine = new AtomicReference<>();
        AtomicReference<String> contentType = new AtomicReference<>();
        AtomicReference<String> body = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    requestLine.set(request.method().name() + " " + request.uri());
                    contentType.set(request.requestHeaders().get("Content-Type"));
                    return request.receive().aggregate().asString().flatMap(received -> {
                        body.set(received);
                        return response.status(200)
                                .header("Content-Type", "application/json")
                                .sendString(Mono.just("{\"libraryFile\":" + LIBRARY_FILE_JSON
                                        + ",\"duplicate\":false}"))
                                .then();
                    });
                })
                .bindNow();
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "paper.pdf",
                MediaType.APPLICATION_OCTET_STREAM_VALUE,
                "%PDF-test".getBytes()
        );

        var uploaded = client().upload(file, "req-library-upload");

        assertThat(requestLine).hasValue("POST /agent-api/v1/library/files");
        assertThat(contentType.get()).startsWith("multipart/form-data");
        assertThat(body.get()).contains("Content-Type: application/pdf");
        assertThat(uploaded.duplicate()).isFalse();
        assertThat(uploaded.libraryFile().knowledgeStatus()).isEqualTo("NOT_INGESTED");
    }

    @Test
    void forwardsScanItemOutcomeFilter() {
        AtomicReference<String> uri = new AtomicReference<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    uri.set(request.uri());
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just("""
                                    {"items":[],"total":0,"offset":5,"limit":25}
                                    """))
                            .then();
                })
                .bindNow();

        var page = client().listScanItems(
                "scan-001",
                5,
                25,
                LibraryScanItemOutcome.FAILED,
                "req-scan-items"
        );

        assertThat(uri).hasValue(
                "/agent-api/v1/library/scans/scan-001/items?offset=5&limit=25&outcome=FAILED"
        );
        assertThat(page.items()).isEmpty();
    }

    @Test
    void preservesActiveScanConflictCodeAndStatus() {
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> response.status(409)
                        .header("Content-Type", "application/json")
                        .sendString(Mono.just("""
                                {"schemaVersion":"1.0","code":"LIBRARY_SCAN_ACTIVE","message":"原件库扫描正在进行。","requestId":"req-scan","retryable":true}
                                """))
                        .then())
                .bindNow();

        assertThatThrownBy(() -> client().createScan("req-scan"))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.status().value()).isEqualTo(409);
                    assertThat(exception.code()).isEqualTo("LIBRARY_SCAN_ACTIVE");
                    assertThat(exception.retryable()).isTrue();
                });
    }

    @Test
    void forwardsManualIngestionExclusionAndRestoreMethods() {
        List<String> requests = new ArrayList<>();
        server = HttpServer.create()
                .host("127.0.0.1")
                .port(0)
                .handle((request, response) -> {
                    requests.add(request.method().name() + " " + request.uri());
                    String body = request.uri().contains("/library/files/")
                            ? "{\"libraryFile\":" + INGESTED_LIBRARY_FILE_JSON
                                    + ",\"paper\":" + PAPER_JSON
                                    + ",\"ingestionJob\":" + JOB_JSON
                                    + ",\"duplicate\":false}"
                            : PAPER_JSON;
                    return response.status(200)
                            .header("Content-Type", "application/json")
                            .sendString(Mono.just(body))
                            .then();
                })
                .bindNow();

        var ingestion = client().ingest("library-file-001", "req-ingest");
        var excluded = client().exclude("paper-001", "req-exclude");
        var restored = client().restore("paper-001", "req-restore");

        assertThat(ingestion.ingestionJob().jobId()).isEqualTo("job-001");
        assertThat(excluded.paperId()).isEqualTo("paper-001");
        assertThat(restored.paperId()).isEqualTo("paper-001");
        assertThat(requests).containsExactly(
                "POST /agent-api/v1/library/files/library-file-001/ingestion",
                "POST /agent-api/v1/papers/paper-001/exclusion",
                "DELETE /agent-api/v1/papers/paper-001/exclusion"
        );
    }

    private AgentLibraryClient client() {
        URI baseUrl = URI.create("http://127.0.0.1:" + server.port());
        return new AgentLibraryClient(
                WebClient.builder().baseUrl(baseUrl.toString()).build(),
                new AgentProperties(baseUrl, Duration.ofSeconds(1), Duration.ofSeconds(2))
        );
    }
}
