package dev.airesearcher.backend.integration.agent;

import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.paper.DeletePaperData;
import dev.airesearcher.backend.paper.IngestionJob;
import dev.airesearcher.backend.paper.Paper;
import dev.airesearcher.backend.paper.PaperListData;
import dev.airesearcher.backend.paper.PaperUploadData;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Component;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;

import java.util.concurrent.TimeoutException;

@Component
public class AgentPaperClient {

    private final WebClient webClient;
    private final AgentProperties properties;

    public AgentPaperClient(WebClient agentWebClient, AgentProperties properties) {
        this.webClient = agentWebClient;
        this.properties = properties;
    }

    public PaperUploadData upload(MultipartFile file, String requestId) {
        MultipartBodyBuilder multipart = new MultipartBodyBuilder();
        Resource resource = file.getResource();
        multipart.part("file", resource)
                .filename(file.getOriginalFilename() == null ? "paper.pdf" : file.getOriginalFilename())
                .contentType(MediaType.APPLICATION_PDF);
        return await(webClient.post()
                .uri("/agent-api/v1/papers")
                .header(RequestIds.HEADER_NAME, requestId)
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .accept(MediaType.APPLICATION_JSON)
                .body(BodyInserters.fromMultipartData(multipart.build()))
                .exchangeToMono(response -> decode(response, PaperUploadData.class)));
    }

    public PaperListData list(String requestId) {
        return await(webClient.get()
                .uri("/agent-api/v1/papers")
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, PaperListData.class)));
    }

    public Paper get(String paperId, String requestId) {
        return await(webClient.get()
                .uri("/agent-api/v1/papers/{paperId}", paperId)
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, Paper.class)));
    }

    public DeletePaperData delete(String paperId, String requestId) {
        DeletePaperData deleted = await(webClient.delete()
                .uri("/agent-api/v1/papers/{paperId}", paperId)
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, DeletePaperData.class)));
        if (!paperId.equals(deleted.paperId())) {
            throw protocolError();
        }
        return deleted;
    }

    public IngestionJob getJob(String jobId, String requestId) {
        return await(webClient.get()
                .uri("/agent-api/v1/ingestion-jobs/{jobId}", jobId)
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, IngestionJob.class)));
    }

    public IngestionJob retryJob(String jobId, String requestId) {
        return await(webClient.post()
                .uri("/agent-api/v1/ingestion-jobs/{jobId}/retry", jobId)
                .header(RequestIds.HEADER_NAME, requestId)
                .accept(MediaType.APPLICATION_JSON)
                .exchangeToMono(response -> decode(response, IngestionJob.class)));
    }

    private <T> Mono<T> decode(ClientResponse response, Class<T> responseType) {
        if (response.statusCode().is2xxSuccessful()) {
            MediaType contentType = response.headers().contentType().orElse(null);
            if (contentType == null || !MediaType.APPLICATION_JSON.isCompatibleWith(contentType)) {
                return response.releaseBody().then(Mono.error(protocolError()));
            }
            return response.bodyToMono(responseType)
                    .switchIfEmpty(Mono.error(protocolError()))
                    .onErrorMap(error -> error instanceof ApiException ? error : protocolError(error));
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
        } catch (ApiException exception) {
            throw exception;
        } catch (WebClientRequestException exception) {
            throw unavailable(exception);
        } catch (RuntimeException exception) {
            if (hasTimeoutCause(exception)) {
                throw new ApiException(
                        HttpStatus.GATEWAY_TIMEOUT,
                        "AGENT_TIMEOUT",
                        "Agent 请求超时。",
                        true,
                        exception
                );
            }
            throw unavailable(exception);
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
        return protocolError(null);
    }

    private ApiException protocolError(Throwable cause) {
        return new ApiException(
                HttpStatus.BAD_GATEWAY,
                "AGENT_ERROR",
                "Agent 返回了无法解析的响应。",
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

    private boolean hasTimeoutCause(Throwable throwable) {
        Throwable current = throwable;
        while (current != null) {
            if (current instanceof TimeoutException
                    || current.getClass().getSimpleName().contains("TimeoutException")) {
                return true;
            }
            current = current.getCause();
        }
        return false;
    }
}
