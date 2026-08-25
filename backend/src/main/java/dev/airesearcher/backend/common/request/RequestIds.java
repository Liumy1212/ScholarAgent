package dev.airesearcher.backend.common.request;

import jakarta.servlet.http.HttpServletRequest;

import java.util.UUID;

public final class RequestIds {

    public static final String HEADER_NAME = "X-Request-Id";
    public static final String ATTRIBUTE_NAME = RequestIds.class.getName() + ".value";
    public static final int MAX_LENGTH = 128;

    private RequestIds() {
    }

    public static String resolve(String suppliedRequestId) {
        if (isValid(suppliedRequestId)) {
            return suppliedRequestId;
        }
        return "req-" + UUID.randomUUID();
    }

    public static boolean isValid(String suppliedRequestId) {
        return suppliedRequestId != null
                && !suppliedRequestId.isBlank()
                && suppliedRequestId.length() <= MAX_LENGTH;
    }

    public static String current(HttpServletRequest request) {
        Object value = request.getAttribute(ATTRIBUTE_NAME);
        if (value instanceof String requestId) {
            return requestId;
        }
        String requestId = resolve(request.getHeader(HEADER_NAME));
        request.setAttribute(ATTRIBUTE_NAME, requestId);
        return requestId;
    }
}
