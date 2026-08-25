package dev.airesearcher.backend.chat;

import tools.jackson.databind.ObjectMapper;
import dev.airesearcher.backend.integration.agent.AgentChatStreamRequest;
import dev.airesearcher.backend.integration.agent.AgentSseClient;
import dev.airesearcher.backend.integration.agent.AgentSseStream;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.publisher.BaseSubscriber;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
public class ChatService {

    private static final String STREAM_FAILURE_CODE = "AGENT_STREAM_FAILURE";
    private static final String STREAM_FAILURE_MESSAGE = "Agent stream failed after it was opened.";
    private static final String STREAM_INTERRUPTED_CODE = "AGENT_STREAM_INTERRUPTED";
    private static final String STREAM_INTERRUPTED_MESSAGE = "Agent stream ended before a terminal event.";
    private static final MediaType APPLICATION_JSON_UTF8 =
            new MediaType(MediaType.APPLICATION_JSON, StandardCharsets.UTF_8);

    private final AgentSseClient agentSseClient;
    private final SseEmitterFactory emitterFactory;
    private final SseProperties properties;
    private final ObjectMapper objectMapper;

    public ChatService(
            AgentSseClient agentSseClient,
            SseEmitterFactory emitterFactory,
            SseProperties properties,
            ObjectMapper objectMapper
    ) {
        this.agentSseClient = agentSseClient;
        this.emitterFactory = emitterFactory;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    public SseEmitter streamMessage(
            String conversationId,
            ChatStreamRequest request,
            String requestId
    ) {
        AgentChatStreamRequest agentRequest = new AgentChatStreamRequest(request.content(), request.paperIds());
        AgentSseStream agentStream = agentSseClient.openStream(conversationId, agentRequest, requestId);

        SseEmitter emitter = emitterFactory.create(properties.emitterTimeout().toMillis());
        DownstreamSubscription cancellation = new DownstreamSubscription();
        SseStreamState state = new SseStreamState(requestId, conversationId, objectMapper);
        AtomicBoolean finished = new AtomicBoolean();

        emitter.onCompletion(cancellation::cancel);
        emitter.onTimeout(cancellation::cancel);
        emitter.onError(ignored -> cancellation.cancel());

        AgentEventSubscriber subscriber = new AgentEventSubscriber(
                emitter,
                cancellation,
                state,
                finished
        );
        cancellation.set(subscriber);
        agentStream.events().subscribe(subscriber);
        return emitter;
    }

    private final class AgentEventSubscriber extends BaseSubscriber<ServerSentEvent<String>> {

        private final SseEmitter emitter;
        private final DownstreamSubscription cancellation;
        private final SseStreamState state;
        private final AtomicBoolean finished;

        private AgentEventSubscriber(
                SseEmitter emitter,
                DownstreamSubscription cancellation,
                SseStreamState state,
                AtomicBoolean finished
        ) {
            this.emitter = emitter;
            this.cancellation = cancellation;
            this.state = state;
            this.finished = finished;
        }

        @Override
        protected void hookOnSubscribe(org.reactivestreams.Subscription subscription) {
            request(1);
        }

        @Override
        protected void hookOnNext(ServerSentEvent<String> event) {
            if (finished.get() || cancellation.isCancelled()) {
                cancel();
                return;
            }
            try {
                send(emitter, event);
                state.observe(event);
                if (state.isTerminal()) {
                    finishNormally();
                } else {
                    request(1);
                }
            } catch (IOException | IllegalStateException exception) {
                if (finished.compareAndSet(false, true)) {
                    cancellation.cancel();
                    emitter.completeWithError(exception);
                }
            }
        }

        @Override
        protected void hookOnError(Throwable throwable) {
            finishWithFailure(STREAM_FAILURE_CODE, STREAM_FAILURE_MESSAGE);
        }

        @Override
        protected void hookOnComplete() {
            if (state.isTerminal()) {
                finishNormally();
            } else {
                finishWithFailure(STREAM_INTERRUPTED_CODE, STREAM_INTERRUPTED_MESSAGE);
            }
        }

        private void finishNormally() {
            if (finished.compareAndSet(false, true)) {
                emitter.complete();
                cancellation.cancel();
            }
        }

        private void finishWithFailure(String code, String message) {
            if (!finished.compareAndSet(false, true) || cancellation.isCancelled()) {
                return;
            }
            try {
                List<ServerSentEvent<String>> failureEvents = state.failureEvents(code, message);
                for (ServerSentEvent<String> failureEvent : failureEvents) {
                    send(emitter, failureEvent);
                }
                emitter.complete();
            } catch (IOException | IllegalStateException exception) {
                emitter.completeWithError(exception);
            } finally {
                cancellation.cancel();
            }
        }
    }

    private void send(SseEmitter emitter, ServerSentEvent<String> event) throws IOException {
        SseEmitter.SseEventBuilder builder = SseEmitter.event();
        if (event.comment() != null) {
            builder.comment(event.comment());
        }
        if (event.event() != null) {
            builder.name(event.event());
        }
        if (event.id() != null) {
            builder.id(event.id());
        }
        if (event.data() != null) {
            builder.data(event.data(), APPLICATION_JSON_UTF8);
        }
        emitter.send(builder);
    }
}
