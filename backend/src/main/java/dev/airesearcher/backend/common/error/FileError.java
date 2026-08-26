package dev.airesearcher.backend.common.error;

public record FileError(
        String schemaVersion,
        String code,
        String message,
        String requestId,
        boolean retryable
) {
    public static final String SCHEMA_VERSION = "1.0";
}
