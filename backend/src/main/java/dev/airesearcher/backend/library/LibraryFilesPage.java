package dev.airesearcher.backend.library;

import java.util.List;

public record LibraryFilesPage(
        List<LibraryFile> items,
        long total,
        int offset,
        int limit
) {
    public LibraryFilesPage {
        items = List.copyOf(items);
    }
}
