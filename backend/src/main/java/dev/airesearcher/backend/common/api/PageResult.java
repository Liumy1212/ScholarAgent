package dev.airesearcher.backend.common.api;

import java.util.List;

public record PageResult<T>(List<T> items, long total, int page, int size) {

    public PageResult {
        items = List.copyOf(items);
        if (total < 0 || page < 0 || size < 1) {
            throw new IllegalArgumentException("Invalid pagination values");
        }
    }
}
