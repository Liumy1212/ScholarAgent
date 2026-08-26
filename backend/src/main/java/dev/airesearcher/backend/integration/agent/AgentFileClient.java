package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.util.UriComponentsBuilder;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;

@Component
public class AgentFileClient {

    private static final int MAX_ERROR_BYTES = 64 * 1024;
    private static final List<String> FORWARDED_HEADERS = List.of(
            HttpHeaders.ACCEPT_RANGES,
            HttpHeaders.CONTENT_RANGE,
            HttpHeaders.CONTENT_LENGTH,
            HttpHeaders.CONTENT_TYPE,
            HttpHeaders.ETAG
    );

    private final java.net.http.HttpClient httpClient;
    private final AgentProperties properties;
    private final ObjectMapper objectMapper;

    public AgentFileClient(
            @Qualifier("agentFileHttpClient") java.net.http.HttpClient httpClient,
            AgentProperties properties,
            ObjectMapper objectMapper
    ) {
        this.httpClient = httpClient;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    public AgentFileResponse open(String paperId, String range, String requestId) {
        URI uri = UriComponentsBuilder.fromUri(properties.baseUrl())
                .pathSegment("agent-api", "v1", "papers", paperId, "file")
                .build()
                .encode()
                .toUri();
        HttpRequest.Builder request = HttpRequest.newBuilder(uri)
                .header(RequestIds.HEADER_NAME, requestId)
                .header(HttpHeaders.ACCEPT, MediaType.APPLICATION_PDF_VALUE)
                .GET();
        if (range != null && !range.isBlank()) {
            request.header(HttpHeaders.RANGE, range);
        }

        HttpResponse<InputStream> response;
        try {
            response = httpClient.send(request.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw unavailable(exception);
        } catch (IOException exception) {
            throw unavailable(exception);
        }

        if (response.statusCode() != 200 && response.statusCode() != 206) {
            throw downstreamError(response);
        }
        try {
            HttpHeaders headers = selectedHeaders(response);
            validatePdfHeaders(response.statusCode(), headers);
            headers.set(RequestIds.HEADER_NAME, requestId);
            return new AgentFileResponse(response.statusCode(), headers, response.body());
        } catch (RuntimeException exception) {
            closeQuietly(response.body());
            if (exception instanceof ApiException apiException) {
                throw apiException;
            }
            throw protocolError(exception);
        }
    }

    private ApiException downstreamError(HttpResponse<InputStream> response) {
        try (InputStream body = response.body()) {
            byte[] bytes = body.readNBytes(MAX_ERROR_BYTES + 1);
            AgentApiError error = bytes.length <= MAX_ERROR_BYTES ? decodeError(bytes) : null;
            int statusCode = response.statusCode();
            if (statusCode >= 400 && statusCode < 500) {
                HttpStatus status = HttpStatus.resolve(statusCode);
                return new ApiException(
                        status == null ? HttpStatus.BAD_REQUEST : status,
                        safe(error == null ? null : error.code(), "INVALID_REQUEST"),
                        safe(error == null ? null : error.message(), "Agent 拒绝了文件请求。"),
                        error != null && error.retryable()
                );
            }
            String code = statusCode == 503 ? "AGENT_UNAVAILABLE" : "AGENT_ERROR";
            String message = statusCode == 503 ? "Agent 服务暂时不可用。" : "Agent 文件代理失败。";
            return new ApiException(HttpStatus.BAD_GATEWAY, code, message, true);
        } catch (IOException exception) {
            return protocolError(exception);
        }
    }

    private AgentApiError decodeError(byte[] body) {
        try {
            return objectMapper.readValue(body, AgentApiError.class);
        } catch (JacksonException exception) {
            return null;
        }
    }

    private HttpHeaders selectedHeaders(HttpResponse<InputStream> response) {
        HttpHeaders headers = new HttpHeaders();
        for (String name : FORWARDED_HEADERS) {
            response.headers().firstValue(name).ifPresent(value -> headers.set(name, value));
        }
        return headers;
    }

    private void validatePdfHeaders(int statusCode, HttpHeaders headers) {
        MediaType contentType = headers.getContentType();
        if (contentType == null || !MediaType.APPLICATION_PDF.isCompatibleWith(contentType)) {
            throw protocolError();
        }
        if (headers.getFirst(HttpHeaders.CONTENT_LENGTH) == null
                || headers.getFirst(HttpHeaders.ACCEPT_RANGES) == null
                || headers.getETag() == null
                || (statusCode == 206 && headers.getFirst(HttpHeaders.CONTENT_RANGE) == null)) {
            throw protocolError();
        }
    }

    private ApiException protocolError() {
        return protocolError(null);
    }

    private ApiException protocolError(Throwable cause) {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "AGENT_ERROR",
                "Agent 返回了无效的 PDF 响应。",
                true,
                cause
        );
    }

    private ApiException unavailable(Throwable cause) {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "AGENT_UNAVAILABLE",
                "Agent 服务暂时不可用。",
                true,
                cause
        );
    }

    private String safe(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private void closeQuietly(InputStream stream) {
        try {
            stream.close();
        } catch (IOException ignored) {
            // The connection is already unusable; the safe API error remains the primary failure.
        }
    }
}
