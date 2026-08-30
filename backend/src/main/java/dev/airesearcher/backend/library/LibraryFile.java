package dev.airesearcher.backend.library;

import dev.airesearcher.backend.paper.IngestionSummary;

import java.time.OffsetDateTime;

public record LibraryFile(
        String libraryFileId,
        String relativePath,
        String fileName,
        long fileSizeBytes,
        String sha256,
        String sourceStatus,
        String knowledgeStatus,
        String paperId,
        String paperTitle,
        boolean searchable,
        IngestionSummary currentIngestion,
        OffsetDateTime discoveredAt,
        OffsetDateTime lastSeenAt,
        OffsetDateTime updatedAt
) {
}
