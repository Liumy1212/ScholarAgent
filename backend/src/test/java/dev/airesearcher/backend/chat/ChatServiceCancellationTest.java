package dev.airesearcher.backend.chat;

import dev.airesearcher.backend.integration.agent.AgentSseClient;
import dev.airesearcher.backend.integration.agent.AgentSseStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.publisher.Flux;
import tools.jackson.databind.ObjectMapper;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatServiceCancellationTest {

    @Mock
    private AgentSseClient agentSseClient;

    @Mock
    private SseEmitterFactory emitterFactory;

    @Mock
    private SseEmitter emitter;

    private ChatService chatService;

    @BeforeEach
    void setUp() {
        chatService = new ChatService(
                agentSseClient,
                emitterFactory,
                new SseProperties(Duration.ZERO),
                new ObjectMapper()
        );
        when(emitterFactory.create(anyLong())).thenReturn(emitter);
    }

    @Test
    void cancelsDownstreamWhenBrowserConnectionErrors() {
        AtomicBoolean cancelled = new AtomicBoolean();
        AtomicReference<Consumer<Throwable>> errorCallback = new AtomicReference<>();
        Flux<org.springframework.http.codec.ServerSentEvent<String>> events = Flux
                .<org.springframework.http.codec.ServerSentEvent<String>>never()
                .doOnCancel(() -> cancelled.set(true));
        when(agentSseClient.openStream(any(), any(), any())).thenReturn(new AgentSseStream(events));
        doAnswer(invocation -> {
            errorCallback.set(invocation.getArgument(0));
            return null;
        }).when(emitter).onError(any());

        chatService.streamMessage(
                "conv-demo-001",
                new ChatStreamRequest("question", List.of()),
                "req-demo-001"
        );
        errorCallback.get().accept(new IllegalStateException("browser disconnected"));

        assertThat(cancelled).isTrue();
    }

    @Test
    void cancelsDownstreamWhenEmitterCompletes() {
        AtomicBoolean cancelled = new AtomicBoolean();
        AtomicReference<Runnable> completionCallback = new AtomicReference<>();
        Flux<org.springframework.http.codec.ServerSentEvent<String>> events = Flux
                .<org.springframework.http.codec.ServerSentEvent<String>>never()
                .doOnCancel(() -> cancelled.set(true));
        when(agentSseClient.openStream(any(), any(), any())).thenReturn(new AgentSseStream(events));
        doAnswer(invocation -> {
            completionCallback.set(invocation.getArgument(0));
            return null;
        }).when(emitter).onCompletion(any());

        chatService.streamMessage(
                "conv-demo-001",
                new ChatStreamRequest("question", List.of()),
                "req-demo-001"
        );
        completionCallback.get().run();

        assertThat(cancelled).isTrue();
    }
}
