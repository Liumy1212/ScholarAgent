package dev.airesearcher.backend.library;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import dev.airesearcher.backend.common.request.RequestIdFilter;
import dev.airesearcher.backend.integration.agent.AgentFileResponse;
import dev.airesearcher.backend.paper.IngestionJob;
import dev.airesearcher.backend.paper.IngestionSummary;
import dev.airesearcher.backend.paper.Paper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.ByteArrayInputStream;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class LibraryControllerTest {

    @Mock
    private LibraryService libraryService;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new LibraryController(libraryService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void wrapsLibraryPaginationAndPreservesRequestId() throws Exception {
        when(libraryService.listFiles(20, 10, null, "req-library-list"))
                .thenReturn(new LibraryFilesPage(List.of(libraryFile()), 21, 20, 10));

        mockMvc.perform(get("/api/v1/library/files")
                        .queryParam("offset", "20")
                        .queryParam("limit", "10")
                        .header("X-Request-Id", "req-library-list"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", "req-library-list"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.requestId").value("req-library-list"))
                .andExpect(jsonPath("$.data.total").value(21))
                .andExpect(jsonPath("$.data.offset").value(20))
                .andExpect(jsonPath("$.data.limit").value(10))
                .andExpect(jsonPath("$.data.items[0].libraryFileId").value("library-file-001"))
                .andExpect(jsonPath("$.data.items[0].knowledgeStatus").value("NOT_INGESTED"));
    }

    @Test
    void validatesAndForwardsLibraryState() throws Exception {
        for (LibraryStateFilter state : LibraryStateFilter.values()) {
            when(libraryService.listFiles(0, 100, state, "req-" + state.name()))
                    .thenReturn(new LibraryFilesPage(List.of(), 0, 0, 100));

            mockMvc.perform(get("/api/v1/library/files")
                            .queryParam("libraryState", state.name())
                            .header("X-Request-Id", "req-" + state.name()))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.data.total").value(0));

            verify(libraryService).listFiles(0, 100, state, "req-" + state.name());
        }
    }

    @Test
    void rejectsInvalidLibraryStateBeforeCallingService() throws Exception {
        mockMvc.perform(get("/api/v1/library/files")
                        .queryParam("libraryState", "missing")
                        .header("X-Request-Id", "req-invalid-library-state"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        verify(libraryService, never()).listFiles(
                org.mockito.ArgumentMatchers.anyInt(),
                org.mockito.ArgumentMatchers.anyInt(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @Test
    void returnsLibraryInfoAndUploadsWithoutStartingIngestion() throws Exception {
        LibraryInfo info = new LibraryInfo(
                "D:/papers",
                "D:/papers/originals",
                List.of(".pdf"),
                false,
                null
        );
        when(libraryService.getLibrary("req-library-info")).thenReturn(info);
        when(libraryService.upload(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.eq("req-library-upload")
        )).thenReturn(new LibraryFileUploadData(libraryFile(), false));
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "paper.pdf",
                MediaType.APPLICATION_PDF_VALUE,
                "%PDF-test".getBytes()
        );

        mockMvc.perform(get("/api/v1/library").header("X-Request-Id", "req-library-info"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.rootPath").value("D:/papers"))
                .andExpect(jsonPath("$.data.originalsPath").value("D:/papers/originals"))
                .andExpect(jsonPath("$.data.supportedExtensions[0]").value(".pdf"));

        mockMvc.perform(multipart("/api/v1/library/files")
                        .file(file)
                        .header("X-Request-Id", "req-library-upload"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.libraryFile.knowledgeStatus").value("NOT_INGESTED"))
                .andExpect(jsonPath("$.data.duplicate").value(false));

        verify(libraryService, never()).ingest(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {
            MediaType.APPLICATION_PDF_VALUE,
            MediaType.APPLICATION_OCTET_STREAM_VALUE
    })
    void acceptsContractPdfContentTypes(String contentType) throws Exception {
        when(libraryService.upload(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.eq("req-upload-content-type")
        )).thenReturn(new LibraryFileUploadData(libraryFile(), false));
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "paper.pdf",
                contentType,
                "%PDF-test".getBytes()
        );

        mockMvc.perform(multipart("/api/v1/library/files")
                        .file(file)
                        .header("X-Request-Id", "req-upload-content-type"))
                .andExpect(status().isOk());
    }

    @Test
    void rejectsInvalidExtensionEmptyFileUnsupportedMimeAndOversize() throws Exception {
        MockMultipartFile invalidExtension = new MockMultipartFile(
                "file", "paper.txt", MediaType.APPLICATION_PDF_VALUE, "%PDF-test".getBytes()
        );
        MockMultipartFile empty = new MockMultipartFile(
                "file", "paper.pdf", MediaType.APPLICATION_PDF_VALUE, new byte[0]
        );
        MockMultipartFile unsupportedMime = new MockMultipartFile(
                "file", "paper.pdf", MediaType.TEXT_PLAIN_VALUE, "%PDF-test".getBytes()
        );
        MockMultipartFile oversized = new MockMultipartFile(
                "file", "paper.pdf", MediaType.APPLICATION_PDF_VALUE, "%PDF-test".getBytes()
        ) {
            @Override
            public long getSize() {
                return 50L * 1024L * 1024L + 1L;
            }
        };

        mockMvc.perform(multipart("/api/v1/library/files").file(invalidExtension))
                .andExpect(status().isUnsupportedMediaType());
        mockMvc.perform(multipart("/api/v1/library/files").file(empty))
                .andExpect(status().isBadRequest());
        mockMvc.perform(multipart("/api/v1/library/files").file(unsupportedMime))
                .andExpect(status().isUnsupportedMediaType());
        mockMvc.perform(multipart("/api/v1/library/files").file(oversized))
                .andExpect(status().isPayloadTooLarge());

        verify(libraryService, never()).upload(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @Test
    void createsScanWithAcceptedStatus() throws Exception {
        when(libraryService.createScan("req-scan")).thenReturn(scan());

        mockMvc.perform(post("/api/v1/library/scans").header("X-Request-Id", "req-scan"))
                .andExpect(status().isAccepted())
                .andExpect(header().string("X-Request-Id", "req-scan"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.data.scanId").value("scan-001"))
                .andExpect(jsonPath("$.data.status").value("QUEUED"));
    }

    @Test
    void preservesActiveScanConflictCode() throws Exception {
        when(libraryService.createScan("req-active")).thenThrow(new ApiException(
                HttpStatus.CONFLICT,
                "LIBRARY_SCAN_ACTIVE",
                "原件库扫描正在进行。",
                true
        ));

        mockMvc.perform(post("/api/v1/library/scans").header("X-Request-Id", "req-active"))
                .andExpect(status().isConflict())
                .andExpect(header().string("X-Request-Id", "req-active"))
                .andExpect(jsonPath("$.code").value("LIBRARY_SCAN_ACTIVE"))
                .andExpect(jsonPath("$.message").value("原件库扫描正在进行。"))
                .andExpect(jsonPath("$.requestId").value("req-active"));
    }

    @Test
    void rejectsInvalidPaginationAndOutcomeBeforeCallingService() throws Exception {
        mockMvc.perform(get("/api/v1/library/scans/scan-001/items")
                        .queryParam("limit", "201")
                        .header("X-Request-Id", "req-invalid-limit"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        mockMvc.perform(get("/api/v1/library/scans/scan-001/items")
                        .queryParam("outcome", "UNKNOWN")
                        .header("X-Request-Id", "req-invalid-outcome"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        verify(libraryService, never()).listScanItems(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.anyInt(),
                org.mockito.ArgumentMatchers.anyInt(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @Test
    void rejectsUnexpectedUploadFieldsBeforeCallingService() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "paper.pdf",
                MediaType.APPLICATION_PDF_VALUE,
                "%PDF-test".getBytes()
        );

        mockMvc.perform(multipart("/api/v1/library/files")
                        .file(file)
                        .param("unexpected", "value")
                        .header("X-Request-Id", "req-library-upload"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        verify(libraryService, never()).upload(
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }

    @Test
    void streamsLibraryPdfRangeWithoutResultWrapper() throws Exception {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PDF);
        headers.setContentLength(5);
        headers.set(HttpHeaders.CONTENT_RANGE, "bytes 5-9/15");
        headers.set(HttpHeaders.ACCEPT_RANGES, "bytes");
        headers.setETag("\"sha256-library\"");
        headers.set("X-Request-Id", "req-library-file");
        when(libraryService.openFile(
                "library-file-001",
                "bytes=5-9",
                "req-library-file"
        )).thenReturn(new AgentFileResponse(
                206,
                headers,
                new ByteArrayInputStream("01234".getBytes())
        ));

        MvcResult initial = mockMvc.perform(get(
                                "/api/v1/library/files/library-file-001/file"
                        )
                        .header("X-Request-Id", "req-library-file")
                        .header("Range", "bytes=5-9"))
                .andExpect(status().isPartialContent())
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(initial))
                .andExpect(status().isPartialContent())
                .andExpect(header().string("Content-Range", "bytes 5-9/15"))
                .andExpect(header().string("Content-Length", "5"))
                .andExpect(header().string("ETag", "\"sha256-library\""))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PDF))
                .andExpect(content().bytes("01234".getBytes()));
    }

    @Test
    void returnsUnwrappedLibraryFileError() throws Exception {
        when(libraryService.openFile("library-file-missing", null, "req-file-missing"))
                .thenThrow(new ApiException(
                        HttpStatus.NOT_FOUND,
                        "LIBRARY_FILE_NOT_FOUND",
                        "未找到指定原件。",
                        false
                ));

        mockMvc.perform(get("/api/v1/library/files/library-file-missing/file")
                        .header("X-Request-Id", "req-file-missing")
                        .accept(MediaType.APPLICATION_PDF, MediaType.APPLICATION_JSON))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.code").value("LIBRARY_FILE_NOT_FOUND"))
                .andExpect(jsonPath("$.requestId").value("req-file-missing"))
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    @Test
    void proxiesManualIngestionExclusionAndRestoreAsOrdinaryResults() throws Exception {
        LibraryFileIngestionData ingestion = new LibraryFileIngestionData(
                ingestedLibraryFile(),
                paper(),
                ingestionJob(),
                false
        );
        when(libraryService.ingest("library-file-001", "req-ingest")).thenReturn(ingestion);
        when(libraryService.exclude("paper-001", "req-exclude")).thenReturn(paper());
        when(libraryService.restore("paper-001", "req-restore")).thenReturn(paper());

        mockMvc.perform(post("/api/v1/library/files/library-file-001/ingestion")
                        .header("X-Request-Id", "req-ingest"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ingestionJob.jobId").value("job-001"))
                .andExpect(jsonPath("$.data.duplicate").value(false));

        mockMvc.perform(post("/api/v1/papers/paper-001/exclusion")
                        .header("X-Request-Id", "req-exclude"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.paperId").value("paper-001"));

        mockMvc.perform(delete("/api/v1/papers/paper-001/exclusion")
                        .header("X-Request-Id", "req-restore"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.paperId").value("paper-001"));
    }

    private LibraryFile libraryFile() {
        OffsetDateTime timestamp = OffsetDateTime.parse("2026-08-30T00:00:00Z");
        return new LibraryFile(
                "library-file-001",
                "folder/paper.pdf",
                "paper.pdf",
                1024,
                "a".repeat(64),
                "AVAILABLE",
                "NOT_INGESTED",
                null,
                null,
                false,
                null,
                timestamp,
                timestamp,
                timestamp
        );
    }

    private LibraryScan scan() {
        return new LibraryScan(
                "scan-001",
                "QUEUED",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                OffsetDateTime.parse("2026-08-30T00:00:00Z"),
                null,
                null,
                null
        );
    }

    private LibraryFile ingestedLibraryFile() {
        OffsetDateTime timestamp = OffsetDateTime.parse("2026-08-30T00:00:00Z");
        IngestionSummary summary = new IngestionSummary(
                "job-001",
                "QUEUED",
                "QUEUED",
                0,
                3,
                false,
                null
        );
        return new LibraryFile(
                "library-file-001",
                "folder/paper.pdf",
                "paper.pdf",
                1024,
                "a".repeat(64),
                "AVAILABLE",
                "PROCESSING",
                "paper-001",
                "Paper",
                false,
                summary,
                timestamp,
                timestamp,
                timestamp
        );
    }

    private Paper paper() {
        OffsetDateTime timestamp = OffsetDateTime.parse("2026-08-30T00:00:00Z");
        return new Paper(
                "paper-001",
                "Paper",
                List.of(),
                null,
                "paper.pdf",
                1024,
                "folder/paper.pdf",
                "AVAILABLE",
                "PROCESSING",
                false,
                null,
                timestamp,
                timestamp,
                new IngestionSummary("job-001", "QUEUED", "QUEUED", 0, 3, false, null)
        );
    }

    private IngestionJob ingestionJob() {
        return new IngestionJob(
                "job-001",
                "paper-001",
                "QUEUED",
                "QUEUED",
                0,
                3,
                false,
                null,
                OffsetDateTime.parse("2026-08-30T00:00:00Z"),
                null,
                null
        );
    }
}
