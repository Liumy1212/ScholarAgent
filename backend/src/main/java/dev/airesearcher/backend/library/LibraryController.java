package dev.airesearcher.backend.library;

import dev.airesearcher.backend.common.api.Result;
import dev.airesearcher.backend.common.error.ApiException;
import dev.airesearcher.backend.common.request.RequestIds;
import dev.airesearcher.backend.integration.agent.AgentFileResponse;
import dev.airesearcher.backend.paper.Paper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
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
import org.springframework.web.bind.annotation.RequestParam;
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
public class LibraryController {

    private static final long MAX_PDF_BYTES = 50L * 1024L * 1024L;

    private final LibraryService libraryService;

    public LibraryController(LibraryService libraryService) {
        this.libraryService = libraryService;
    }

    @GetMapping(path = "/library", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<LibraryInfo>> getLibrary(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ok(libraryService.getLibrary(requestId), requestId);
    }

    @GetMapping(path = "/library/files", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<LibraryFilesPage>> listFiles(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(defaultValue = "100") @Min(1) @Max(200) int limit,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        validatePagination(offset, limit);
        return ok(libraryService.listFiles(offset, limit, requestId), requestId);
    }

    @PostMapping(
            path = "/library/files",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE,
            produces = MediaType.APPLICATION_JSON_VALUE
    )
    public ResponseEntity<Result<LibraryFileUploadData>> upload(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @RequestPart("file") MultipartFile file,
            MultipartHttpServletRequest multipartRequest
    ) {
        String requestId = requestId(suppliedRequestId, multipartRequest);
        validateUpload(file, multipartRequest);
        return ok(libraryService.upload(file, requestId), requestId);
    }

    @GetMapping(path = "/library/files/{libraryFileId}/file", produces = MediaType.APPLICATION_PDF_VALUE)
    public ResponseEntity<StreamingResponseBody> file(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @RequestHeader(value = HttpHeaders.RANGE, required = false) String range,
            @PathVariable @Size(min = 1, max = 128) String libraryFileId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        AgentFileResponse downstream = libraryService.openFile(libraryFileId, range, requestId);
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

    @PostMapping(
            path = "/library/files/{libraryFileId}/ingestion",
            produces = MediaType.APPLICATION_JSON_VALUE
    )
    public ResponseEntity<Result<LibraryFileIngestionData>> ingest(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String libraryFileId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ok(libraryService.ingest(libraryFileId, requestId), requestId);
    }

    @PostMapping(path = "/library/scans", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<LibraryScan>> createScan(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(libraryService.createScan(requestId), requestId));
    }

    @GetMapping(path = "/library/scans/{scanId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<LibraryScan>> getScan(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String scanId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ok(libraryService.getScan(scanId, requestId), requestId);
    }

    @GetMapping(path = "/library/scans/{scanId}/items", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<LibraryScanItemsPage>> listScanItems(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String scanId,
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(defaultValue = "100") @Min(1) @Max(200) int limit,
            @RequestParam(required = false) LibraryScanItemOutcome outcome,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        validatePagination(offset, limit);
        return ok(
                libraryService.listScanItems(scanId, offset, limit, outcome, requestId),
                requestId
        );
    }

    @PostMapping(path = "/papers/{paperId}/exclusion", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<Paper>> exclude(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String paperId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ok(libraryService.exclude(paperId, requestId), requestId);
    }

    @DeleteMapping(path = "/papers/{paperId}/exclusion", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Result<Paper>> restore(
            @RequestHeader(value = RequestIds.HEADER_NAME, required = false) String suppliedRequestId,
            @PathVariable @Size(min = 1, max = 128) String paperId,
            HttpServletRequest servletRequest
    ) {
        String requestId = requestId(suppliedRequestId, servletRequest);
        return ok(libraryService.restore(paperId, requestId), requestId);
    }

    private <T> ResponseEntity<Result<T>> ok(T data, String requestId) {
        return ResponseEntity.ok()
                .header(RequestIds.HEADER_NAME, requestId)
                .body(Result.success(data, requestId));
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

    private void validatePagination(int offset, int limit) {
        if (offset < 0 || limit < 1 || limit > 200) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_REQUEST",
                    "分页参数无效。",
                    false
            );
        }
    }

    private ApiException invalidUpload(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REQUEST", message, false);
    }
}
