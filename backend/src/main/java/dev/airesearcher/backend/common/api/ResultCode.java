package dev.airesearcher.backend.common.api;

import org.springframework.http.HttpStatus;

public enum ResultCode {
    SUCCESS("SUCCESS", "Success.", HttpStatus.OK, false),
    INVALID_REQUEST("INVALID_REQUEST", "Request validation failed.", HttpStatus.BAD_REQUEST, false),
    INTERNAL_ERROR("INTERNAL_ERROR", "An internal error occurred.", HttpStatus.INTERNAL_SERVER_ERROR, false),
    AGENT_UNAVAILABLE("AGENT_UNAVAILABLE", "Agent service is unavailable.", HttpStatus.BAD_GATEWAY, true),
    AGENT_TIMEOUT("AGENT_TIMEOUT", "Timed out while opening the Agent stream.", HttpStatus.GATEWAY_TIMEOUT, true),
    AGENT_ERROR("AGENT_ERROR", "Agent service failed to open the stream.", HttpStatus.BAD_GATEWAY, true);

    private final String code;
    private final String defaultMessage;
    private final HttpStatus httpStatus;
    private final boolean retryable;

    ResultCode(String code, String defaultMessage, HttpStatus httpStatus, boolean retryable) {
        this.code = code;
        this.defaultMessage = defaultMessage;
        this.httpStatus = httpStatus;
        this.retryable = retryable;
    }

    public String code() {
        return code;
    }

    public String defaultMessage() {
        return defaultMessage;
    }

    public HttpStatus httpStatus() {
        return httpStatus;
    }

    public boolean retryable() {
        return retryable;
    }
}
