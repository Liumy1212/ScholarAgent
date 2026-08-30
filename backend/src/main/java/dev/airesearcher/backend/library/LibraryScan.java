package dev.airesearcher.backend.library;

import java.time.OffsetDateTime;

public record LibraryScan(
        String scanId,
        String status,
        int discoveredCount,
        int registeredCount,
        int unchangedCount,
        int duplicateCount,
        int excludedCount,
        int skippedCount,
        int failedCount,
        OffsetDateTime createdAt,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt,
        LibraryScanFailure failure
) {
}
