package dev.airesearcher.backend.common.error;

import dev.airesearcher.backend.common.api.Result;
import dev.airesearcher.backend.common.api.ResultCode;
import dev.airesearcher.backend.common.request.RequestIds;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;

import java.util.List;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(StreamOpenException.class)
    public ResponseEntity<Object> handleStreamOpenException(
            StreamOpenException exception,
            HttpServletRequest request
    ) {
        return errorResponse(
                exception.resultCode(),
                exception.getMessage(),
                exception.details(),
                request,
                true
        );
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException exception,
            HttpServletRequest request
    ) {
        List<ErrorDetail> details = exception.getBindingResult().getFieldErrors().stream()
                .map(error -> new ErrorDetail(error.getField(), defaultReason(error.getDefaultMessage())))
                .distinct()
                .toList();
        return errorResponse(
                ResultCode.INVALID_REQUEST,
                ResultCode.INVALID_REQUEST.defaultMessage(),
                details,
                request,
                isStreamingRequest(request)
        );
    }

    @ExceptionHandler({HandlerMethodValidationException.class, ConstraintViolationException.class})
    public ResponseEntity<Object> handleMethodValidation(Exception exception, HttpServletRequest request) {
        return errorResponse(
                ResultCode.INVALID_REQUEST,
                ResultCode.INVALID_REQUEST.defaultMessage(),
                null,
                request,
                isStreamingRequest(request)
        );
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Object> handleUnreadableBody(
            HttpMessageNotReadableException exception,
            HttpServletRequest request
    ) {
        return errorResponse(
                ResultCode.INVALID_REQUEST,
                ResultCode.INVALID_REQUEST.defaultMessage(),
                null,
                request,
                isStreamingRequest(request)
        );
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Object> handleUnexpected(Exception exception, HttpServletRequest request) {
        log.error("Unhandled request failure", exception);
        return errorResponse(
                ResultCode.INTERNAL_ERROR,
                ResultCode.INTERNAL_ERROR.defaultMessage(),
                null,
                request,
                isStreamingRequest(request)
        );
    }

    private ResponseEntity<Object> errorResponse(
            ResultCode resultCode,
            String message,
            List<ErrorDetail> details,
            HttpServletRequest request,
            boolean streaming
    ) {
        String requestId = RequestIds.current(request);
        HttpHeaders headers = new HttpHeaders();
        headers.set(RequestIds.HEADER_NAME, requestId);
        headers.setContentType(MediaType.APPLICATION_JSON);
        Object body = streaming
                ? new StreamOpenError(
                        StreamOpenError.SCHEMA_VERSION,
                        resultCode.code(),
                        message,
                        requestId,
                        resultCode.retryable(),
                        details
                )
                : Result.failure(resultCode, message, requestId);
        return new ResponseEntity<>(body, headers, resultCode.httpStatus());
    }

    private boolean isStreamingRequest(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return uri.startsWith("/api/v1/conversations/") && uri.endsWith("/messages/stream");
    }

    private String defaultReason(String reason) {
        return reason == null ? "invalid value" : reason;
    }
}
