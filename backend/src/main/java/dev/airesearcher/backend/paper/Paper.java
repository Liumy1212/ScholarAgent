package dev.airesearcher.backend.paper;

import java.time.OffsetDateTime;
import java.util.List;

public record Paper(
        String paperId,
        String title,
        List<String> authors,
        Integer publicationYear,
        String fileName,
        long fileSizeBytes,
        String libraryRelativePath,
        String sourceStatus,
        String status,
        boolean searchable,
        Integer pageCount,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt,
        IngestionSummary currentIngestion
) {
}
