package dev.airesearcher.backend.chat;

import dev.airesearcher.backend.common.api.ResultCode;
import dev.airesearcher.backend.common.error.ErrorDetail;
import dev.airesearcher.backend.common.error.StreamOpenException;
import dev.airesearcher.backend.common.request.RequestIds;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Size;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.nio.charset.StandardCharsets;
import java.util.List;

@Validated
@RestController
@RequestMapping("/api/v1/conversations")
public class ChatController {

    private static final MediaType TEXT_EVENT_STREAM_UTF8 =
            new MediaType(MediaType.TEXT_EVENT_STREAM, StandardCharsets.UTF_8);

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping(
            path = "/{conversationId}/messages/stream",
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE
    )
    public ResponseEntity<SseEmitter> streamMessage(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String conversationId,
            @Valid @RequestBody ChatStreamRequest request,
            HttpServletRequest servletRequest
    ) {
        if (suppliedRequestId != null && !RequestIds.isValid(suppliedRequestId)) {
            throw new StreamOpenException(
                    ResultCode.INVALID_REQUEST,
                    ResultCode.INVALID_REQUEST.defaultMessage(),
                    List.of(new ErrorDetail(RequestIds.HEADER_NAME, "must contain 1 to 128 characters"))
            );
        }
        String requestId = RequestIds.current(servletRequest);
        SseEmitter emitter = chatService.streamMessage(conversationId, request, requestId);
        return ResponseEntity.ok()
                .contentType(TEXT_EVENT_STREAM_UTF8)
                .cacheControl(CacheControl.noCache())
                .header(RequestIds.HEADER_NAME, requestId)
                .body(emitter);
    }
}
