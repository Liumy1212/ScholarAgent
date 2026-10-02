package dev.airesearcher.backend.conversation;

import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import dev.airesearcher.backend.common.request.RequestIdFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.net.URI;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class ConversationControllerTest {

    @Mock
    private ConversationService service;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new ConversationController(service))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void wrapsConversationPageAndPreservesRequestId() throws Exception {
        var summary = new ConversationSummary(
                "conversation-001",
                "First question",
                "Latest answer",
                new ConversationScope("ALL", null, List.of()),
                2,
                OffsetDateTime.parse("2026-01-01T00:00:00Z"),
                OffsetDateTime.parse("2026-01-01T00:01:00Z")
        );
        when(service.list(5, 20, "req-conversations"))
                .thenReturn(new ConversationsPage(List.of(summary), 1, 5, 20));

        mockMvc.perform(get("/api/v1/conversations")
                        .queryParam("offset", "5")
                        .queryParam("limit", "20")
                        .header("X-Request-Id", "req-conversations"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", "req-conversations"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.requestId").value("req-conversations"))
                .andExpect(jsonPath("$.data.items[0].conversationId").value("conversation-001"))
                .andExpect(jsonPath("$.data.items[0].scope.type").value("ALL"));

        verify(service).list(5, 20, "req-conversations");
    }

    @Test
    void rejectsPaginationOutsideContractBounds() throws Exception {
        mockMvc.perform(get("/api/v1/conversations")
                        .queryParam("offset", "-1")
                        .queryParam("limit", "201")
                        .header("X-Request-Id", "req-invalid-page"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.requestId").value("req-invalid-page"));

        verifyNoInteractions(service);
    }

    @Test
    void wrapsConversationDetailAndPreservesRequestId() throws Exception {
        var summary = new ConversationSummary(
                "conversation-001",
                "First question",
                "Latest answer",
                new ConversationScope("PAPERS", null, List.of("paper-1")),
                1,
                OffsetDateTime.parse("2026-01-01T00:00:00Z"),
                OffsetDateTime.parse("2026-01-01T00:01:00Z")
        );
        var turn = new ConversationTurn(
                "run-001",
                null,
                "message-001",
                "历史问题",
                "历史回答",
                "KNOWLEDGE_BASE",
                List.of(new ConversationToolCall("tool-001", "knowledge_base_search", "COMPLETED", null)),
                List.of(new ConversationCitation("citation-001", null, "Synthetic", 3, "evidence", "chunk-001")),
                OffsetDateTime.parse("2026-01-01T00:00:00Z"),
                OffsetDateTime.parse("2026-01-01T00:01:00Z")
        );
        when(service.get("conversation-001", "req-conv-detail"))
                .thenReturn(new ConversationDetail(summary, List.of(turn), 1, false));

        mockMvc.perform(get("/api/v1/conversations/conversation-001")
                        .header("X-Request-Id", "req-conv-detail"))
                .andExpect(status().isOk())
                .andExpect(header().string("X-Request-Id", "req-conv-detail"))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.requestId").value("req-conv-detail"))
                .andExpect(jsonPath("$.data.conversation.conversationId").value("conversation-001"))
                .andExpect(jsonPath("$.data.totalTurns").value(1))
                .andExpect(jsonPath("$.data.truncated").value(false))
                .andExpect(jsonPath("$.data.turns[0].runId").value("run-001"))
                .andExpect(jsonPath("$.data.turns[0].answerMode").value("KNOWLEDGE_BASE"))
                .andExpect(jsonPath("$.data.turns[0].citations[0].pageNumber").value(3));

        verify(service).get("conversation-001", "req-conv-detail");
    }

    @Test
    void rejectsBlankConversationIdBeforeServiceCall() throws Exception {
        mockMvc.perform(get(URI.create("/api/v1/conversations/%20%20%20"))
                        .header("X-Request-Id", "req-blank-conversation"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.requestId").value("req-blank-conversation"));

        verifyNoInteractions(service);
    }

    @Test
    void rejectsOversizedConversationIdBeforeServiceCall() throws Exception {
        mockMvc.perform(get("/api/v1/conversations/" + "a".repeat(129))
                        .header("X-Request-Id", "req-oversized-conversation"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.requestId").value("req-oversized-conversation"));

        verifyNoInteractions(service);
    }
}
