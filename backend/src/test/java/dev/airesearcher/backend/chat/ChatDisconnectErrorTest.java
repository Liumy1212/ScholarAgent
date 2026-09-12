package dev.airesearcher.backend.chat;

import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.async.AsyncRequestNotUsableException;

import java.io.IOException;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ChatDisconnectErrorTest {
    @Test
    void doesNotAppendJsonToAnUnusableSseResponse() throws Exception {
        MockMvcBuilders.standaloneSetup(new DisconnectedController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .build()
                .perform(post("/api/v1/conversations/synthetic/messages/stream"))
                .andExpect(status().isOk())
                .andExpect(content().string(": heartbeat\n\n"));
    }

    @RestController
    static class DisconnectedController {
        @PostMapping("/api/v1/conversations/synthetic/messages/stream")
        void stream(HttpServletResponse response) throws IOException {
            response.setContentType("text/event-stream");
            response.getWriter().write(": heartbeat\n\n");
            response.flushBuffer();
            throw new AsyncRequestNotUsableException("Synthetic client disconnect");
        }
    }
}
