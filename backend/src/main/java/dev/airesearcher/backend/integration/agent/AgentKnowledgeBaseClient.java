package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.knowledgebase.DeleteKnowledgeBaseData;
import dev.airesearcher.backend.knowledgebase.KnowledgeBase;
import dev.airesearcher.backend.knowledgebase.KnowledgeBaseMembersRequest;
import dev.airesearcher.backend.knowledgebase.KnowledgeBaseMembersUpdate;
import dev.airesearcher.backend.knowledgebase.KnowledgeBaseNameRequest;
import dev.airesearcher.backend.knowledgebase.KnowledgeBasePapersPage;
import dev.airesearcher.backend.knowledgebase.KnowledgeBasesPage;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;

import java.util.concurrent.TimeoutException;

@Component
public class AgentKnowledgeBaseClient {
    private final WebClient webClient;
    private final AgentProperties properties;

    public AgentKnowledgeBaseClient(WebClient agentWebClient, AgentProperties properties) {
        this.webClient = agentWebClient;
        this.properties = properties;
    }

    public KnowledgeBasesPage list(int offset, int limit, String requestId) {
        return await(webClient.get().uri(builder -> builder.path("/agent-api/v1/knowledge-bases")
                .queryParam("offset", offset).queryParam("limit", limit).build())
                .header(RequestIds.HEADER_NAME, requestId).accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, KnowledgeBasesPage.class)));
    }

    public KnowledgeBase create(KnowledgeBaseNameRequest body, String requestId) {
        return await(webClient.post().uri("/agent-api/v1/knowledge-bases")
                .header(RequestIds.HEADER_NAME, requestId).contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body).exchangeToMono(response -> decode(response, KnowledgeBase.class)));
    }

    public KnowledgeBase get(String id, String requestId) {
        return await(webClient.get().uri("/agent-api/v1/knowledge-bases/{id}", id)
                .header(RequestIds.HEADER_NAME, requestId)
                .exchangeToMono(response -> decode(response, KnowledgeBase.class)));
    }

    public KnowledgeBase rename(String id, KnowledgeBaseNameRequest body, String requestId) {
        return await(webClient.patch().uri("/agent-api/v1/knowledge-bases/{id}", id)
                .header(RequestIds.HEADER_NAME, requestId).contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body).exchangeToMono(response -> decode(response, KnowledgeBase.class)));
    }

    public DeleteKnowledgeBaseData delete(String id, String requestId) {
        return await(webClient.delete().uri("/agent-api/v1/knowledge-bases/{id}", id)
                .header(RequestIds.HEADER_NAME, requestId)
                .exchangeToMono(response -> decode(response, DeleteKnowledgeBaseData.class)));
    }

    public KnowledgeBasePapersPage papers(String id, int offset, int limit, String requestId) {
        return await(webClient.get().uri(builder -> builder
                .path("/agent-api/v1/knowledge-bases/{id}/papers")
                .queryParam("offset", offset).queryParam("limit", limit).build(id))
                .header(RequestIds.HEADER_NAME, requestId)
                .exchangeToMono(response -> decode(response, KnowledgeBasePapersPage.class)));
    }

    public KnowledgeBaseMembersUpdate updateMembers(
            String id, KnowledgeBaseMembersRequest body, String requestId
    ) {
        return await(webClient.patch().uri("/agent-api/v1/knowledge-bases/{id}/papers", id)
                .header(RequestIds.HEADER_NAME, requestId).contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body)
                .exchangeToMono(response -> decode(response, KnowledgeBaseMembersUpdate.class)));
    }

    private <T> Mono<T> decode(ClientResponse response, Class<T> type) {
        if (response.statusCode().is2xxSuccessful()) {
            MediaType contentType = response.headers().contentType().orElse(null);
            if (contentType == null || !MediaType.APPLICATION_JSON.isCompatibleWith(contentType)) {
                return response.releaseBody().then(Mono.error(protocolError()));
            }
            return response.bodyToMono(type).switchIfEmpty(Mono.error(protocolError()))
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
            if (result == null) throw protocolError();
            return result;
        } catch (ApiException error) {
            throw error;
        } catch (WebClientRequestException error) {
            throw unavailable(error);
        } catch (RuntimeException error) {
            if (hasTimeoutCause(error)) {
                throw new ApiException(HttpStatus.GATEWAY_TIMEOUT, "AGENT_TIMEOUT", "Agent 请求超时。", true, error);
            }
            throw unavailable(error);
        }
    }

    private ApiException protocolError() {
        return new ApiException(HttpStatus.BAD_GATEWAY, "AGENT_ERROR", "Agent 返回了无法解析的响应。", true);
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

    private ApiException unavailable(Throwable cause) {
        return new ApiException(HttpStatus.BAD_GATEWAY, "AGENT_UNAVAILABLE", "Agent 服务暂时不可用。", true, cause);
    }

    private boolean hasTimeoutCause(Throwable throwable) {
        for (Throwable current = throwable; current != null; current = current.getCause()) {
            if (current instanceof TimeoutException || current.getClass().getSimpleName().contains("TimeoutException")) return true;
        }
        return false;
    }

    private String safe(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}
