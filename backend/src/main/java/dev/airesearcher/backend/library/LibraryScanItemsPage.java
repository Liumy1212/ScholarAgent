package dev.airesearcher.backend.library;

import java.util.List;

public record LibraryScanItemsPage(
        List<LibraryScanItem> items,
        long total,
        int offset,
        int limit
) {
    public LibraryScanItemsPage {
        items = List.copyOf(items);
    }
}
