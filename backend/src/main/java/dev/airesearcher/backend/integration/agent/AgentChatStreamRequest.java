package dev.airesearcher.backend.integration.agent;

import java.util.List;

public record AgentChatStreamRequest(String content, List<String> paperIds, String knowledgeBaseId) {

    public AgentChatStreamRequest {
        paperIds = List.copyOf(paperIds);
    }

    public AgentChatStreamRequest(String content, List<String> paperIds) {
        this(content, paperIds, null);
    }
}
