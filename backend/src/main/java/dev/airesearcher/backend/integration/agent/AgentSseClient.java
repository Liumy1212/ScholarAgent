package dev.airesearcher.backend.integration.agent;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import dev.airesearcher.backend.common.api.ResultCode;
import dev.airesearcher.backend.common.error.StreamOpenException;
import dev.airesearcher.backend.common.request.RequestIds;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Flux;

import java.util.concurrent.TimeoutException;

@Component
public class AgentSseClient {

    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<>() {
            };

    private final WebClient webClient;
    private final AgentProperties properties;
    private final ObjectMapper objectMapper;

    public AgentSseClient(WebClient agentWebClient, AgentProperties properties, ObjectMapper objectMapper) {
        this.webClient = agentWebClient;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    public AgentSseStream openStream(
            String conversationId,
            AgentChatStreamRequest request,
            String requestId
    ) {
        try {
            ResponseEntity<Flux<ServerSentEvent<String>>> response = webClient.post()
                    .uri("/agent-api/v1/conversations/{conversationId}/messages/stream", conversationId)
                    .header(RequestIds.HEADER_NAME, requestId)
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .bodyValue(request)
                    .retrieve()
                    .toEntityFlux(SSE_TYPE)
                    .block(properties.openTimeout());

            if (response == null || response.getBody() == null) {
                throw new StreamOpenException(ResultCode.AGENT_ERROR);
            }
            MediaType contentType = response.getHeaders().getContentType();
            if (contentType == null || !MediaType.TEXT_EVENT_STREAM.isCompatibleWith(contentType)) {
                throw new StreamOpenException(ResultCode.AGENT_ERROR);
            }
            return new AgentSseStream(response.getBody());
        } catch (StreamOpenException exception) {
            throw exception;
        } catch (WebClientResponseException exception) {
            throw mapResponseFailure(exception);
        } catch (WebClientRequestException exception) {
            throw new StreamOpenException(ResultCode.AGENT_UNAVAILABLE, exception);
        } catch (RuntimeException exception) {
            if (hasTimeoutCause(exception)) {
                throw new StreamOpenException(ResultCode.AGENT_TIMEOUT, exception);
            }
            throw new StreamOpenException(ResultCode.AGENT_UNAVAILABLE, exception);
        }
    }

    private StreamOpenException mapResponseFailure(WebClientResponseException exception) {
        if (exception.getStatusCode().value() == 400) {
            AgentStreamOpenError downstreamError = readDownstreamError(exception);
            if (downstreamError != null && downstreamError.message() != null
                    && !downstreamError.message().isBlank()) {
                return new StreamOpenException(
                        ResultCode.INVALID_REQUEST,
                        downstreamError.message(),
                        downstreamError.details()
                );
            }
            return new StreamOpenException(ResultCode.INVALID_REQUEST);
        }
        if (exception.getStatusCode().value() == 503) {
            return new StreamOpenException(ResultCode.AGENT_UNAVAILABLE, exception);
        }
        return new StreamOpenException(ResultCode.AGENT_ERROR, exception);
    }

    private AgentStreamOpenError readDownstreamError(WebClientResponseException exception) {
        try {
            return objectMapper.readValue(exception.getResponseBodyAsByteArray(), AgentStreamOpenError.class);
        } catch (JacksonException ignored) {
            return null;
        }
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
