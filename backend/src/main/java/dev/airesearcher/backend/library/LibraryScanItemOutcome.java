package dev.airesearcher.backend.library;

public enum LibraryScanItemOutcome {
    REGISTERED,
    UNCHANGED,
    MOVED,
    DUPLICATE,
    EXCLUDED,
    SKIPPED,
    FAILED
}
