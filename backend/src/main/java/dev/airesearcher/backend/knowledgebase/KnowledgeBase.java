package dev.airesearcher.backend.knowledgebase;

import java.time.OffsetDateTime;

public record KnowledgeBase(
        String knowledgeBaseId,
        String name,
        int paperCount,
        int searchablePaperCount,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt
) {
}
