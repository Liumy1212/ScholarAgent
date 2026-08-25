package dev.airesearcher.backend.chat;

import dev.airesearcher.backend.common.api.ResultCode;
import dev.airesearcher.backend.common.error.GlobalExceptionHandler;
import dev.airesearcher.backend.common.error.StreamOpenException;
import dev.airesearcher.backend.common.request.RequestIdFilter;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.integration.agent.AgentSseClient;
import dev.airesearcher.backend.integration.agent.AgentSseStream;
import dev.airesearcher.backend.support.ContractSseFixtures;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import reactor.core.publisher.Flux;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class ChatStreamingIntegrationTest {

    @Mock
    private AgentSseClient agentSseClient;

    private ObjectMapper objectMapper;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        ChatService chatService = new ChatService(
                agentSseClient,
                new SseEmitterFactory(),
                new SseProperties(Duration.ZERO),
                objectMapper
        );
        mockMvc = MockMvcBuilders.standaloneSetup(new ChatController(chatService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new RequestIdFilter())
                .build();
    }

    @Test
    void proxiesContractStreamWithoutChangingEventIdOrData() throws Exception {
        List<ServerSentEvent<String>> expectedEvents = ContractSseFixtures.completedEvents();
        when(agentSseClient.openStream(any(), any(), any()))
                .thenReturn(new AgentSseStream(Flux.fromIterable(expectedEvents)));

        MvcResult initial = mockMvc.perform(post("/api/v1/conversations/conv-demo-001/messages/stream")
                        .header(RequestIds.HEADER_NAME, "req-demo-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"question\",\"paperIds\":[]}"))
                .andExpect(status().isOk())
                .andExpect(header().string(RequestIds.HEADER_NAME, "req-demo-001"))
                .andExpect(header().string("Cache-Control", "no-cache"))
                .andExpect(request().asyncStarted())
                .andReturn();

        MvcResult completed = mockMvc.perform(asyncDispatch(initial))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andReturn();
        String actualText = completed.getResponse().getContentAsString(StandardCharsets.UTF_8);
        List<ServerSentEvent<String>> actualEvents = ContractSseFixtures.parse(actualText);

        assertThat(actualEvents).hasSameSizeAs(expectedEvents);
        for (int index = 0; index < expectedEvents.size(); index++) {
            ServerSentEvent<String> expected = expectedEvents.get(index);
            ServerSentEvent<String> actual = actualEvents.get(index);
            assertThat(actual.event()).isEqualTo(expected.event());
            assertThat(actual.id()).isEqualTo(expected.id());
            assertThat(actual.data()).isEqualTo(expected.data());
            assertThat(actual.comment()).isEqualTo(expected.comment());
        }
    }

    @Test
    void mapsFailureAfterOpenToContractRunFailedEvent() throws Exception {
        ServerSentEvent<String> started = ContractSseFixtures.failedEvents().getFirst();
        Flux<ServerSentEvent<String>> events = Flux.concat(
                Flux.just(started),
                Flux.error(new IllegalStateException("downstream connection reset"))
        );
        when(agentSseClient.openStream(any(), any(), any())).thenReturn(new AgentSseStream(events));

        MvcResult initial = mockMvc.perform(post("/api/v1/conversations/conv-demo-002/messages/stream")
                        .header(RequestIds.HEADER_NAME, "req-failed-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"question\",\"paperIds\":[]}"))
                .andExpect(status().isOk())
                .andExpect(request().asyncStarted())
                .andReturn();
        MvcResult completed = mockMvc.perform(asyncDispatch(initial)).andReturn();

        List<ServerSentEvent<String>> actualEvents = ContractSseFixtures.parse(
                completed.getResponse().getContentAsString(StandardCharsets.UTF_8)
        );
        assertThat(actualEvents).hasSize(2);
        assertThat(actualEvents.getFirst().data()).isEqualTo(started.data());
        ServerSentEvent<String> failed = actualEvents.getLast();
        JsonNode envelope = objectMapper.readTree(failed.data());
        assertThat(failed.event()).isEqualTo("run.failed");
        assertThat(failed.id()).isEqualTo(envelope.path("eventId").asText());
        assertThat(envelope.path("requestId").asText()).isEqualTo("req-failed-001");
        assertThat(envelope.path("runId").asText()).isEqualTo("run-failed-001");
        assertThat(envelope.path("sequence").asLong()).isEqualTo(1);
        assertThat(envelope.path("payload").path("code").asText()).isEqualTo("AGENT_STREAM_FAILURE");
        assertThat(envelope.path("payload").path("retryable").asBoolean()).isTrue();
    }

    @Test
    void mapsAgentUnavailableBeforeOpenToJsonError() throws Exception {
        when(agentSseClient.openStream(any(), any(), any()))
                .thenThrow(new StreamOpenException(ResultCode.AGENT_UNAVAILABLE));

        mockMvc.perform(post("/api/v1/conversations/conv-demo-001/messages/stream")
                        .header(RequestIds.HEADER_NAME, "req-unavailable-001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"question\",\"paperIds\":[]}"))
                .andExpect(status().isBadGateway())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string(RequestIds.HEADER_NAME, "req-unavailable-001"))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.code").value("AGENT_UNAVAILABLE"))
                .andExpect(jsonPath("$.requestId").value("req-unavailable-001"))
                .andExpect(jsonPath("$.retryable").value(true));
    }

    @Test
    void rejectsInvalidRequestWithUnwrappedStreamOpenError() throws Exception {
        MvcResult result = mockMvc.perform(post("/api/v1/conversations/conv-demo-001/messages/stream")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"\",\"paperIds\":[]}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(jsonPath("$.requestId").isString())
                .andExpect(jsonPath("$.data").doesNotExist())
                .andReturn();

        assertThat(result.getResponse().getHeader(RequestIds.HEADER_NAME))
                .isEqualTo(objectMapper.readTree(result.getResponse().getContentAsString())
                        .path("requestId").asText());
    }

    @Test
    void rejectsOverlongRequestIdAndReturnsGeneratedValidRequestId() throws Exception {
        String invalidRequestId = "x".repeat(RequestIds.MAX_LENGTH + 1);

        MvcResult result = mockMvc.perform(post("/api/v1/conversations/conv-demo-001/messages/stream")
                        .header(RequestIds.HEADER_NAME, invalidRequestId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM, MediaType.APPLICATION_JSON)
                        .content("{\"content\":\"question\",\"paperIds\":[]}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andReturn();

        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        String effectiveRequestId = body.path("requestId").asText();
        assertThat(effectiveRequestId).startsWith("req-").hasSizeLessThanOrEqualTo(RequestIds.MAX_LENGTH);
        assertThat(result.getResponse().getHeader(RequestIds.HEADER_NAME)).isEqualTo(effectiveRequestId);
    }
}
