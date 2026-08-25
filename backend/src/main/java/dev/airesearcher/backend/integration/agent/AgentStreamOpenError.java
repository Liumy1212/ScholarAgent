package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ErrorDetail;

import java.util.List;

record AgentStreamOpenError(
        String schemaVersion,
        String code,
        String message,
        String requestId,
        boolean retryable,
        List<ErrorDetail> details
) {
}
