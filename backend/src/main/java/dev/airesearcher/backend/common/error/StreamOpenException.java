package dev.airesearcher.backend.common.error;

import dev.airesearcher.backend.common.api.ResultCode;

import java.util.List;

public class StreamOpenException extends RuntimeException {

    private final ResultCode resultCode;
    private final List<ErrorDetail> details;

    public StreamOpenException(ResultCode resultCode) {
        this(resultCode, resultCode.defaultMessage(), null, null);
    }

    public StreamOpenException(ResultCode resultCode, String message, List<ErrorDetail> details) {
        this(resultCode, message, details, null);
    }

    public StreamOpenException(ResultCode resultCode, Throwable cause) {
        this(resultCode, resultCode.defaultMessage(), null, cause);
    }

    private StreamOpenException(
            ResultCode resultCode,
            String message,
            List<ErrorDetail> details,
            Throwable cause
    ) {
        super(message, cause);
        this.resultCode = resultCode;
        this.details = details == null ? null : List.copyOf(details);
    }

    public ResultCode resultCode() {
        return resultCode;
    }

    public List<ErrorDetail> details() {
        return details;
    }
}
