package dev.airesearcher.backend.conversation;

public record ConversationCitation(
        String citationId,
        String paperId,
        String paperTitle,
        int pageNumber,
        String quote,
        String chunkId
) {
}
