package dev.airesearcher.backend.chat;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.hibernate.validator.constraints.UniqueElements;

import java.util.List;

public record ChatStreamRequest(
        @NotEmpty String content,
        @NotNull @Size(max = 100) @UniqueElements List<@NotEmpty @Size(max = 128) String> paperIds,
        @Size(min = 1, max = 128) String knowledgeBaseId
) {
    public ChatStreamRequest {
        paperIds = paperIds == null ? null : List.copyOf(paperIds);
    }

    public ChatStreamRequest(String content, List<String> paperIds) {
        this(content, paperIds, null);
    }

    @AssertTrue(message = "knowledgeBaseId and paperIds are mutually exclusive")
    public boolean isScopeValid() {
        return knowledgeBaseId == null || paperIds == null || paperIds.isEmpty();
    }
}
