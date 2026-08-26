package dev.airesearcher.backend.paper;

import dev.airesearcher.backend.common.api.Result;
import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.integration.agent.AgentFileClient;
import dev.airesearcher.backend.integration.agent.AgentFileResponse;
import dev.airesearcher.backend.integration.agent.AgentPaperClient;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.multipart.MultipartHttpServletRequest;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.InputStream;
import java.util.List;

@Validated
@RestController
@RequestMapping("/api/v1")
public class PaperController {

    private static final long MAX_PDF_BYTES = 50L * 1024L * 1024L;

    private final AgentPaperClient paperClient;
    private final AgentFileClient fileClient;

    public PaperController(AgentPaperClient paperClient, AgentFileClient fileClient) {
        this.paperClient = paperClient;
        this.fileClient = fileClient;
    }

    @PostMapping(
            path = "/papers",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE
    )
    public ResponseEntity<Result<PaperUploadData>> upload(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @RequestPart("file") MultipartFile file,
            MultipartHttpServletRequest multipartRequest
    ) {
        String requestId = requestId(suppliedRequestId, multipartRequest);
        validateUpload(file, multipartRequest);
        PaperUploadData data = paperClient.upload(file, requestId);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(data, requestId));
    }

    @GetMapping(path = "/papers", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<PaperListData>> list(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(paperClient.list(requestId), requestId));
    }

    @GetMapping(path = "/papers/{paperId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<Paper>> get(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String paperId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(paperClient.get(paperId, requestId), requestId));
    }

    @DeleteMapping(path = "/papers/{paperId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<DeletePaperData>> delete(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String paperId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(paperClient.delete(paperId, requestId), requestId));
    }

    @GetMapping(path = "/ingestion-jobs/{jobId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<IngestionJob>> getJob(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String jobId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(paperClient.getJob(jobId, requestId), requestId));
    }

    @PostMapping(path = "/ingestion-jobs/{jobId}/retry", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<IngestionJob>> retryJob(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String jobId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(paperClient.retryJob(jobId, requestId), requestId));
    }

    @GetMapping(path = "/papers/{paperId}/file", produces = MediaType.APPLICATION_PDF_VALUE)
    public ResponseEntity<StreamingResponseBody> file(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @RequestHeader(value = HttpHeaders.RANGE, required = false) String range,
            @PathVariable @Size(min = 1, max = 128) String paperId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        AgentFileResponse downstream = fileClient.open(paperId, range, requestId);
        StreamingResponseBody body = output -> {
            try (InputStream input = downstream.body()) {
                input.transferTo(output);
                output.flush();
            }
        };
        return ResponseEntity.status(downstream.statusCode())
                .headers(downstream.headers())
                .body(body);
    }

    private String requestId(String suppliedRequestId, HttpServletRequest request) {
        if (suppliedRequestId != null && !RequestIds.isValid(suppliedRequestId)) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_REQUEST",
                    "X-Request-Id 必须包含 1 到 128 个字符。",
                    false
            );
        }
        return RequestIds.current(request);
    }

    private void validateUpload(MultipartFile file, MultipartHttpServletRequest request) {
        List<MultipartFile> files = request.getMultiFileMap().get("file");
        int totalFiles = request.getMultiFileMap().values().stream().mapToInt(List::size).sum();
        if (files == null || files.size() != 1 || totalFiles != 1 || !request.getParameterMap().isEmpty()) {
            throw invalidUpload("请求必须且只能包含一个名为 file 的 PDF。");
        }
        String filename = file.getOriginalFilename();
        if (filename == null || filename.isBlank() || !filename.toLowerCase().endsWith(".pdf")) {
            throw new ApiException(
                    HttpStatus.UNSUPPORTED_MEDIA_TYPE,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "只支持 PDF 文件。",
                    false
            );
        }
        if (!MediaType.APPLICATION_PDF_VALUE.equalsIgnoreCase(file.getContentType())) {
            throw new ApiException(
                    HttpStatus.UNSUPPORTED_MEDIA_TYPE,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "只支持 application/pdf 文本型 PDF。",
                    false
            );
        }
        if (file.isEmpty()) {
            throw invalidUpload("PDF 文件不能为空。");
        }
        if (file.getSize() > MAX_PDF_BYTES) {
            throw new ApiException(
                    HttpStatus.PAYLOAD_TOO_LARGE,
                    "PDF_TOO_LARGE",
                    "PDF 不能超过 50 MB。",
                    false
            );
        }
    }

    private ApiException invalidUpload(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", message, false);
    }
}
