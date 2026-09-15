package dev.airesearcher.backend.knowledgebase;

import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import dev.airesearcher.backend.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class KnowledgeBaseControllerTest {

    @Mock
    private KnowledgeBaseService service;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new KnowledgeBaseController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void wrapsListAndPreservesRequestId() throws Exception {
        KnowledgeBase base = new KnowledgeBase(
                "kb-001", "合成知识库", 2, 1,
                OffsetDateTime.parse("2026-01-01T00:00:00Z"),
                OffsetDateTime.parse("2026-01-01T00:01:00Z")
        );
        when(service.list(0, 20, "req-kb-list"))
                .thenReturn(new KnowledgeBasesPage(List.of(base), 1, 0, 20));

        mockMvc.perform(get("/api/v1/knowledge-bases")
                        .queryParam("limit", "20")
                        .header("X-Request-Id", "req-kb-list"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", "req-kb-list"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.data.items[0].knowledgeBaseId").value("kb-001"))
                .andExpect(jsonPath("$.data.items[0].searchablePaperCount").value(1));
    }

    @Test
    void rejectsOverlappingMemberChangesBeforeServiceCall() throws Exception {
        mockMvc.perform(patch("/api/v1/knowledge-bases/kb-001/papers")
                        .header("X-Request-Id", "req-kb-members")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"addPaperIds\":[\"paper-001\"],\"removePaperIds\":[\"paper-001\"]}"))
                .andExpect(status().isBadRequest())
                .andExpect(header().string("X-Request-Id", "req-kb-members"))
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));

        verify(service, never()).updateMembers(
                org.mockito.ArgumentMatchers.anyString(),
                org.mockito.ArgumentMatchers.any(),
                org.mockito.ArgumentMatchers.anyString()
        );
    }
}
