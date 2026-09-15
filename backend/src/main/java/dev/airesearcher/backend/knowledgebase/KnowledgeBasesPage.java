package dev.airesearcher.backend.knowledgebase;

import java.util.List;

public record KnowledgeBasesPage(List<KnowledgeBase> items, int total, int offset, int limit) {
    public KnowledgeBasesPage { items = List.copyOf(items); }
}
