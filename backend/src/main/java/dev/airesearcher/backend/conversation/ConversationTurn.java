package dev.airesearcher.backend.conversation;

import java.time.OffsetDateTime;
import java.util.List;

public record ConversationTurn(
        String runId,
        String requestId,
        String assistantMessageId,
        String question,
        String answer,
        String answerMode,
        List<ConversationToolCall> tools,
        List<ConversationCitation> citations,
        OffsetDateTime createdAt,
        OffsetDateTime completedAt
) {
}
