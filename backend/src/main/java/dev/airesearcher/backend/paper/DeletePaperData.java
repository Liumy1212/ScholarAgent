package dev.airesearcher.backend.paper;

public record DeletePaperData(String paperId, boolean deleted) {
    public DeletePaperData {
        if (paperId == null || paperId.isBlank()) {
            throw new IllegalArgumentException("paperId must not be blank");
        }
        if (!deleted) {
            throw new IllegalArgumentException("deleted must be true");
        }
    }
}
