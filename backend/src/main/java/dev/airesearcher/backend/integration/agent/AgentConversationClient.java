package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.conversation.ConversationDetail;
import dev.airesearcher.backend.conversation.ConversationsPage;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;

import java.util.concurrent.TimeoutException;

@Component
public class AgentConversationClient {
    private final WebClient webClient;
    private final AgentProperties properties;

    public AgentConversationClient(WebClient agentWebClient, AgentProperties properties) {
        this.webClient = agentWebClient;
        this.properties = properties;
    }

    public ConversationsPage list(int offset, int limit, String requestId) {
        return await(webClient.get()
                .uri(builder -> builder.path("/agent-api/v1/conversations")
                        .queryParam("offset", offset)
                        .queryParam("limit", limit)
                        .build())
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, ConversationsPage.class)));
    }

    public ConversationDetail get(String conversationId, String requestId) {
        return await(webClient.get()
                .uri("/agent-api/v1/conversations/{conversationId}", conversationId)
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, ConversationDetail.class)));
    }

    private <T> Mono<T> decode(ClientResponse response, Class<T> type) {
        if (response.statusCode().is2xxSuccessful()) {
            MediaType contentType = response.headers().contentType().orElse(null);
            if (contentType == null || !MediaType.APPLICATION_JSON.isCompatibleWith(contentType)) {
                return response.releaseBody().then(Mono.error(protocolError()));
            }
            return response.bodyToMono(type)
                    .switchIfEmpty(Mono.error(protocolError()))
                    .onErrorMap(error -> error instanceof ApiException ? error : protocolError());
        }
        return response.bodyToMono(AgentApiError.class)
                .onErrorReturn(defaultDownstreamError())
                .defaultIfEmpty(defaultDownstreamError())
                .flatMap(error -> Mono.error(mapDownstream(response.statusCode().value(), error)));
    }

    private <T> T await(Mono<T> operation) {
        try {
            T result = operation.timeout(properties.openTimeout()).block();
            if (result == null) {
                throw protocolError();
            }
            return result;
        } catch (ApiException error) {
            throw error;
        } catch (WebClientRequestException error) {
            throw unavailable(error);
        } catch (RuntimeException error) {
            if (hasTimeoutCause(error)) {
                throw new ApiException(
                        HttpStatus.GATEWAY_TIMEOUT,
                        "AGENT_TIMEOUT",
                        "Agent 请求超时。",
                        true,
                        error
                );
            }
            throw unavailable(error);
        }
    }

    private ApiException mapDownstream(int statusCode, AgentApiError error) {
        if (statusCode >= 400 && statusCode < 500) {
            HttpStatus status = HttpStatus.resolve(statusCode);
            return new ApiException(
                    status == null ? HttpStatus.BAD_REQUEST : status,
                    safe(error.code(), "INVALID_REQUEST"),
                    safe(error.message(), "Agent 拒绝了请求。"),
                    error.retryable()
            );
        }
        String code = statusCode == 503 ? "AGENT_UNAVAILABLE" : "AGENT_ERROR";
        String message = statusCode == 503 ? "Agent 服务暂时不可用。" : "Agent 服务执行失败。";
        return new ApiException(HttpStatus.BAD_GATEWAY, code, message, true);
    }

    private AgentApiError defaultDownstreamError() {
        return new AgentApiError(null, null, null, null, false, null);
    }

    private ApiException protocolError() {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "AGENT_ERROR",
                "Agent 返回了无法解析的响应。",
                true
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

    private boolean hasTimeoutCause(Throwable throwable) {
        for (Throwable current = throwable; current != null; current = current.getCause()) {
            if (current instanceof TimeoutException
                    || current.getClass().getSimpleName().contains("TimeoutException")) {
                return true;
            }
        }
        return false;
    }

    private String safe(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}
