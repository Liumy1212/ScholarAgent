package dev.airesearcher.backend.conversation;

import java.util.List;

public record ConversationDetail(
        ConversationSummary conversation,
        List<ConversationTurn> turns,
        int totalTurns,
        boolean truncated
) {
}
