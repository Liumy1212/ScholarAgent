package dev.airesearcher.backend.common.api;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record Result<T>(String code, String message, T data, String requestId) {

    public static <T> Result<T> success(T data, String requestId) {
        return new Result<>(ResultCode.SUCCESS.code(), ResultCode.SUCCESS.defaultMessage(), data, requestId);
    }

    public static Result<Void> failure(ResultCode resultCode, String message, String requestId) {
        return new Result<>(resultCode.code(), message, null, requestId);
    }
}
