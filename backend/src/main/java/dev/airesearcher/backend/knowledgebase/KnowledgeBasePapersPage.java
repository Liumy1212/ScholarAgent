package dev.airesearcher.backend.knowledgebase;

import dev.airesearcher.backend.paper.Paper;
import java.util.List;

public record KnowledgeBasePapersPage(List<Paper> items, int total, int offset, int limit) {
    public KnowledgeBasePapersPage { items = List.copyOf(items); }
}
