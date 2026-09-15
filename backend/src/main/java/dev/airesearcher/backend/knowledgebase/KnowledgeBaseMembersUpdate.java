package dev.airesearcher.backend.knowledgebase;

import java.util.List;

public record KnowledgeBaseMembersUpdate(
        KnowledgeBase knowledgeBase,
        List<String> addedPaperIds,
        List<String> removedPaperIds
) {
    public KnowledgeBaseMembersUpdate {
        addedPaperIds = List.copyOf(addedPaperIds);
        removedPaperIds = List.copyOf(removedPaperIds);
    }
}
