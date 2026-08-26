package dev.airesearcher.backend.paper;

public record IngestionSummary(
        String jobId,
        String status,
        String stage,
        int attempt,
        int maxAttempts,
        boolean canRetry,
        IngestionFailure failure
) {
}
