package dev.airesearcher.backend.chat;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.hibernate.validator.constraints.UniqueElements;

import java.util.List;

public record ChatStreamRequest(
        @NotEmpty String content,
        @NotNull @UniqueElements List<@NotEmpty @Size(max = 128) String> paperIds
) {
    public ChatStreamRequest {
        paperIds = paperIds == null ? null : List.copyOf(paperIds);
    }
}
