package dev.airesearcher.backend.conversation;

import java.time.OffsetDateTime;

public record ConversationSummary(
        String conversationId,
        String title,
        String preview,
        ConversationScope scope,
        int turnCount,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt
) {
}
