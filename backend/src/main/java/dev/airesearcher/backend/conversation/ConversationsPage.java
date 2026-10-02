package dev.airesearcher.backend.conversation;

import java.util.List;

public record ConversationsPage(
        List<ConversationSummary> items,
        int total,
        int offset,
        int limit
) {
}
