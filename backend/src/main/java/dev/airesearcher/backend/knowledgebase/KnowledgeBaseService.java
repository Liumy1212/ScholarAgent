package dev.airesearcher.backend.knowledgebase;

import dev.airesearcher.backend.integration.agent.AgentKnowledgeBaseClient;
import org.springframework.stereotype.Service;

@Service
public class KnowledgeBaseService {
    private final AgentKnowledgeBaseClient client;

    public KnowledgeBaseService(AgentKnowledgeBaseClient client) { this.client = client; }
    public KnowledgeBasesPage list(int offset, int limit, String requestId) { return client.list(offset, limit, requestId); }
    public KnowledgeBase create(KnowledgeBaseNameRequest body, String requestId) { return client.create(body, requestId); }
    public KnowledgeBase get(String id, String requestId) { return client.get(id, requestId); }
    public KnowledgeBase rename(String id, KnowledgeBaseNameRequest body, String requestId) { return client.rename(id, body, requestId); }
    public DeleteKnowledgeBaseData delete(String id, String requestId) { return client.delete(id, requestId); }
    public KnowledgeBasePapersPage papers(String id, int offset, int limit, String requestId) { return client.papers(id, offset, limit, requestId); }
    public KnowledgeBaseMembersUpdate updateMembers(String id, KnowledgeBaseMembersRequest body, String requestId) { return client.updateMembers(id, body, requestId); }
}
