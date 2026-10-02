package dev.airesearcher.backend.conversation;

import dev.airesearcher.backend.common.api.Result;
import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/conversations")
public class ConversationController {
    private final ConversationService service;

    public ConversationController(ConversationService service) {
        this.service = service;
    }

    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<ConversationsPage>> list(
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(defaultValue = "50") @Min(1) @Max(200) int limit,
            HttpServletRequest request
    ) {
        if (offset < 0 || limit < 1 || limit > 200) {
            throw invalidRequest("分页参数必须满足 offset >= 0 且 1 <= limit <= 200。");
        }
        String requestId = RequestIds.current(request);
        return ok(service.list(offset, limit, requestId), requestId);
    }

    @GetMapping(path = "/{conversationId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<ConversationDetail>> get(
            @PathVariable @Size(min = 1, max = 128) String conversationId,
            HttpServletRequest request
    ) {
        if (conversationId.isBlank() || conversationId.length() > 128) {
            throw invalidRequest("conversationId 长度必须在 1 到 128 个字符之间。");
        }
        String requestId = RequestIds.current(request);
        return ok(service.get(conversationId, requestId), requestId);
    }

    private <T> ResponseEntity<Result<T>> ok(T data, String requestId) {
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(data, requestId));
    }

    private ApiException invalidRequest(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", message, false);
    }
}
