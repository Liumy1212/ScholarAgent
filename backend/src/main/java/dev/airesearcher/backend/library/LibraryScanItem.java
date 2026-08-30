package dev.airesearcher.backend.library;

public record LibraryScanItem(
        String relativePath,
        String outcome,
        String libraryFileId,
        String paperId,
        String code,
        String message
) {
}
