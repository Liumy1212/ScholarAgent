package dev.airesearcher.backend.common.error;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.List;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record StreamOpenError(
        String schemaVersion,
        String code,
        String message,
        String requestId,
        boolean retryable,
        List<ErrorDetail> details
) {
    public static final String SCHEMA_VERSION = "1.0";

    public StreamOpenError {
        details = details == null ? null : List.copyOf(details);
    }
}
