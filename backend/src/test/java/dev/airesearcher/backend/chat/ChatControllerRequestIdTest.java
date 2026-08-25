package dev.airesearcher.backend.chat;

import dev.airesearcher.backend.common.request.RequestIds;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatControllerRequestIdTest {

    @Mock
    private ChatService chatService;

    @Test
    void generatesAndReturnsRequestIdWhenHeaderIsMissing() {
        ChatController controller = new ChatController(chatService);
        MockHttpServletRequest servletRequest = new MockHttpServletRequest();
        ChatStreamRequest request = new ChatStreamRequest("question", List.of());
        when(chatService.streamMessage(eq("conv-001"), eq(request), any()))
                .thenReturn(new SseEmitter(0L));

        ResponseEntity<SseEmitter> response = controller.streamMessage(null, "conv-001", request, servletRequest);

        ArgumentCaptor<String> requestId = ArgumentCaptor.forClass(String.class);
        verify(chatService).streamMessage(eq("conv-001"), eq(request), requestId.capture());
        assertThat(requestId.getValue()).startsWith("req-").hasSize(40);
        assertThat(response.getHeaders().getFirst(RequestIds.HEADER_NAME)).isEqualTo(requestId.getValue());
    }

    @Test
    void acceptsAndForwardsSuppliedRequestId() {
        ChatController controller = new ChatController(chatService);
        MockHttpServletRequest servletRequest = new MockHttpServletRequest();
        servletRequest.addHeader(RequestIds.HEADER_NAME, "req-browser-001");
        ChatStreamRequest request = new ChatStreamRequest("question", List.of("paper-001"));
        when(chatService.streamMessage(eq("conv-001"), eq(request), any()))
                .thenReturn(new SseEmitter(0L));

        ResponseEntity<SseEmitter> response = controller.streamMessage(
                "req-browser-001",
                "conv-001",
                request,
                servletRequest
        );

        verify(chatService).streamMessage("conv-001", request, "req-browser-001");
        assertThat(response.getHeaders().getFirst(RequestIds.HEADER_NAME)).isEqualTo("req-browser-001");
    }
}
