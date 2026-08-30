package dev.airesearcher.backend.library;

import dev.airesearcher.backend.paper.IngestionJob;
import dev.airesearcher.backend.paper.Paper;

public record LibraryFileIngestionData(
        LibraryFile libraryFile,
        Paper paper,
        IngestionJob ingestionJob,
        boolean duplicate
) {
}
