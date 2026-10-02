package dev.airesearcher.backend.conversation;

import dev.airesearcher.backend.integration.agent.AgentConversationClient;
import org.springframework.stereotype.Service;

@Service
public class ConversationService {
    private final AgentConversationClient client;

    public ConversationService(AgentConversationClient client) {
        this.client = client;
    }

    public ConversationsPage list(int offset, int limit, String requestId) {
        return client.list(offset, limit, requestId);
    }

    public ConversationDetail get(String conversationId, String requestId) {
        return client.get(conversationId, requestId);
    }
}
