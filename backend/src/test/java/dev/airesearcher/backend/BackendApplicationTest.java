package dev.airesearcher.backend;

import dev.airesearcher.backend.chat.ChatController;
import dev.airesearcher.backend.integration.agent.AgentSseClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class BackendApplicationTest {

    @Autowired
    private ChatController chatController;

    @Autowired
    private AgentSseClient agentSseClient;

    @Test
    void loadsMvcBffContext() {
        assertThat(chatController).isNotNull();
        assertThat(agentSseClient).isNotNull();
    }
}
