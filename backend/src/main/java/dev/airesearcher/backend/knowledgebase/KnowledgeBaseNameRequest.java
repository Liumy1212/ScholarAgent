package dev.airesearcher.backend.knowledgebase;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record KnowledgeBaseNameRequest(@NotBlank @Size(max = 100) String name) {
}
