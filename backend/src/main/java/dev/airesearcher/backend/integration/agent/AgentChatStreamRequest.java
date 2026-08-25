package dev.airesearcher.backend.integration.agent;

import java.util.List;

public record AgentChatStreamRequest(String content, List<String> paperIds) {

    public AgentChatStreamRequest {
        paperIds = List.copyOf(paperIds);
    }
}
