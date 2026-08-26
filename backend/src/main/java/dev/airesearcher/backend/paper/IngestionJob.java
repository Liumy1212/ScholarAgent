package dev.airesearcher.backend.paper;

import java.time.OffsetDateTime;

public record IngestionJob(
        String jobId,
        String paperId,
        String status,
        String stage,
        int attempt,
        int maxAttempts,
        boolean canRetry,
        IngestionFailure failure,
        OffsetDateTime createdAt,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt
) {
}
