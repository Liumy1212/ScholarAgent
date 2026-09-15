package dev.airesearcher.backend.knowledgebase;

import dev.airesearcher.backend.common.api.Result;
import dev.airesearcher.backend.common.request.RequestIds;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@Validated
@RestController
@RequestMapping("/api/v1/knowledge-bases")
public class KnowledgeBaseController {
    private final KnowledgeBaseService service;

    public KnowledgeBaseController(KnowledgeBaseService service) { this.service = service; }

    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBasesPage>> list(
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(defaultValue = "100") @Min(1) @Max(200) int limit,
            HttpServletRequest request
    ) {
        String requestId = RequestIds.current(request);
        return ok(service.list(offset, limit, requestId), requestId);
    }

    @PostMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBase>> create(@Valid @RequestBody KnowledgeBaseNameRequest body, HttpServletRequest request) {
        String requestId = RequestIds.current(request);
        return ResponseEntity.status(HttpStatus.CREATED).header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(service.create(body, requestId), requestId));
    }

    @GetMapping(path = "/{knowledgeBaseId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBase>> get(@PathVariable @Size(min=1,max=128) String knowledgeBaseId, HttpServletRequest request) {
        String requestId = RequestIds.current(request); return ok(service.get(knowledgeBaseId, requestId), requestId);
    }

    @PatchMapping(path = "/{knowledgeBaseId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBase>> rename(@PathVariable @Size(min=1,max=128) String knowledgeBaseId, @Valid @RequestBody KnowledgeBaseNameRequest body, HttpServletRequest request) {
        String requestId = RequestIds.current(request); return ok(service.rename(knowledgeBaseId, body, requestId), requestId);
    }

    @DeleteMapping(path = "/{knowledgeBaseId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<DeleteKnowledgeBaseData>> delete(@PathVariable @Size(min=1,max=128) String knowledgeBaseId, HttpServletRequest request) {
        String requestId = RequestIds.current(request); return ok(service.delete(knowledgeBaseId, requestId), requestId);
    }

    @GetMapping(path = "/{knowledgeBaseId}/papers", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBasePapersPage>> papers(@PathVariable @Size(min=1,max=128) String knowledgeBaseId, @RequestParam(defaultValue="0") @Min(0) int offset, @RequestParam(defaultValue="100") @Min(1) @Max(200) int limit, HttpServletRequest request) {
        String requestId = RequestIds.current(request); return ok(service.papers(knowledgeBaseId, offset, limit, requestId), requestId);
    }

    @PatchMapping(path = "/{knowledgeBaseId}/papers", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<KnowledgeBaseMembersUpdate>> updateMembers(@PathVariable @Size(min=1,max=128) String knowledgeBaseId, @Valid @RequestBody KnowledgeBaseMembersRequest body, HttpServletRequest request) {
        String requestId = RequestIds.current(request); return ok(service.updateMembers(knowledgeBaseId, body, requestId), requestId);
    }

    private <T> ResponseEntity<Result<T>> ok(T data, String requestId) {
        return ResponseEntity.ok().header(RequestIds.HEADER_NAME, requestId).body(Result.success(data, requestId));
    }
}
