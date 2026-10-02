package dev.airesearcher.backend.conversation;

import java.util.List;

public record ConversationScope(String type, String scopeId, List<String> paperIds) {
}
