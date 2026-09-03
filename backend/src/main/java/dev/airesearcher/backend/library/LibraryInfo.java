package dev.airesearcher.backend.library;

import java.util.List;

public record LibraryInfo(
        String rootPath,
        String originalsPath,
        List<String> supportedExtensions,
        boolean scanInProgress,
        LibraryScan latestScan
) {
    public LibraryInfo {
        if (rootPath == null || rootPath.isBlank()) {
            throw new IllegalArgumentException("rootPath must not be blank");
        }
        if (originalsPath == null || originalsPath.isBlank()) {
            throw new IllegalArgumentException("originalsPath must not be blank");
        }
        supportedExtensions = List.copyOf(supportedExtensions);
    }
}
