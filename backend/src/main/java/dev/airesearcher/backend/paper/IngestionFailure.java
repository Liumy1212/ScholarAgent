package dev.airesearcher.backend.paper;

public record IngestionFailure(String code, String message, boolean retryable) {
}
