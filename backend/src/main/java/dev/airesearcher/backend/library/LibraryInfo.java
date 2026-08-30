package dev.airesearcher.backend.library;

import java.util.List;

public record LibraryInfo(
        String rootPath,
        List<String> supportedExtensions,
        boolean scanInProgress,
        LibraryScan latestScan
) {
    public LibraryInfo {
        supportedExtensions = List.copyOf(supportedExtensions);
    }
}
