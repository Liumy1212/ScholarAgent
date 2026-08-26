package dev.airesearcher.backend.paper;

public record PaperUploadData(Paper paper, IngestionJob ingestionJob, boolean duplicate) {
}
