package dev.airesearcher.backend.paper;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import dev.airesearcher.backend.common.request.RequestIdFilter;
import dev.airesearcher.backend.integration.agent.AgentFileClient;
import dev.airesearcher.backend.integration.agent.AgentFileResponse;
import dev.airesearcher.backend.integration.agent.AgentPaperClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class PaperControllerTest {

    @Mock
    private AgentPaperClient paperClient;

    @Mock
    private AgentFileClient fileClient;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new PaperController(paperClient, fileClient))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void wrapsOrdinaryAgentDtoInResultAndPreservesRequestId() throws Exception {
        IngestionSummary summary = new IngestionSummary(
                "job-001", "SUCCEEDED", "COMPLETED", 1, 3, false, null
        );
        Paper paper = new Paper(
                "paper-001",
                "Grounded Paper",
                List.of("Ada Example"),
                2026,
                "paper.pdf",
                1024,
                "uploads/paper.pdf",
                "AVAILABLE",
                "READY",
                true,
                2,
                OffsetDateTime.parse("2026-01-01T00:00:00Z"),
                OffsetDateTime.parse("2026-01-01T00:01:00Z"),
                summary
        );
        when(paperClient.list("req-list")).thenReturn(new PaperListData(List.of(paper), 1));

        mockMvc.perform(get("/api/v1/papers").header("X-Request-Id", "req-list"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", "req-list"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.requestId").value("req-list"))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].paperId").value("paper-001"))
                .andExpect(jsonPath("$.data.items[0].currentIngestion.stage").value("COMPLETED"));
    }

    @Test
    void rejectsMultipartWithUnexpectedFieldsBeforeCallingAgent() throws Exception {
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "paper.pdf",
                MediaType.APPLICATION_PDF_VALUE,
                "%PDF-test".getBytes()
        );

        mockMvc.perform(multipart("/api/v1/papers")
                        .file(file)
                        .param("unexpected", "value")
                        .header("X-Request-Id", "req-upload"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.data").doesNotExist());

        verify(paperClient, never()).upload(any(), any());
    }

    @Test
    void streamsPdfRangeWithoutResultWrapper() throws Exception {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PDF);
        headers.setContentLength(5);
        headers.set(HttpHeaders.CONTENT_RANGE, "bytes 5-9/15");
        headers.set(HttpHeaders.ACCEPT_RANGES, "bytes");
        headers.setETag("\"sha256-demo\"");
        headers.set("X-Request-Id", "req-file");
        when(fileClient.open("paper-001", "bytes=5-9", "req-file"))
                .thenReturn(new AgentFileResponse(
                        206,
                        headers,
                        new ByteArrayInputStream("01234".getBytes())
                ));

        MvcResult initial = mockMvc.perform(get("/api/v1/papers/paper-001/file")
                        .header("X-Request-Id", "req-file")
                        .header("Range", "bytes=5-9"))
                .andExpect(status().isPartialContent())
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(initial))
                .andExpect(status().isPartialContent())
                .andExpect(header().string("Content-Range", "bytes 5-9/15"))
                .andExpect(header().string("Content-Length", "5"))
                .andExpect(header().string("ETag", "\"sha256-demo\""))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PDF))
                .andExpect(content().bytes("01234".getBytes()));
    }

    @Test
    void returnsUnwrappedFileErrorBeforePdfStreamOpens() throws Exception {
        when(fileClient.open("paper-missing", null, "req-missing"))
                .thenThrow(new ApiException(
                        HttpStatus.NOT_FOUND,
                        "PAPER_NOT_FOUND",
                        "未找到指定论文。",
                        false
                ));

        mockMvc.perform(get("/api/v1/papers/paper-missing/file")
                        .header("X-Request-Id", "req-missing")
                        .accept(MediaType.APPLICATION_PDF, MediaType.APPLICATION_JSON))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.code").value("PAPER_NOT_FOUND"))
                .andExpect(jsonPath("$.requestId").value("req-missing"))
                .andExpect(jsonPath("$.retryable").value(false))
                .andExpect(jsonPath("$.data").doesNotExist());
    }
}
