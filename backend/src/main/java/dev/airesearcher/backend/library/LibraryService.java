package dev.airesearcher.backend.library;

import dev.airesearcher.backend.integration.agent.AgentFileClient;
import dev.airesearcher.backend.integration.agent.AgentFileResponse;
import dev.airesearcher.backend.integration.agent.AgentLibraryClient;
import dev.airesearcher.backend.paper.Paper;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

@Service
public class LibraryService {

    private final AgentLibraryClient libraryClient;
    private final AgentFileClient fileClient;

    public LibraryService(AgentLibraryClient libraryClient, AgentFileClient fileClient) {
        this.libraryClient = libraryClient;
        this.fileClient = fileClient;
    }

    public LibraryInfo getLibrary(String requestId) {
        return libraryClient.getLibrary(requestId);
    }

    public LibraryFilesPage listFiles(
            int offset,
            int limit,
            LibraryStateFilter libraryState,
            String requestId
    ) {
        return libraryClient.listFiles(offset, limit, libraryState, requestId);
    }

    public LibraryFileUploadData upload(MultipartFile file, String requestId) {
        return libraryClient.upload(file, requestId);
    }

    public AgentFileResponse openFile(String libraryFileId, String range, String requestId) {
        return fileClient.openLibraryFile(libraryFileId, range, requestId);
    }

    public LibraryFileIngestionData ingest(String libraryFileId, String requestId) {
        return libraryClient.ingest(libraryFileId, requestId);
    }

    public LibraryScan createScan(String requestId) {
        return libraryClient.createScan(requestId);
    }

    public LibraryScan getScan(String scanId, String requestId) {
        return libraryClient.getScan(scanId, requestId);
    }

    public LibraryScanItemsPage listScanItems(
            String scanId,
            int offset,
            int limit,
            LibraryScanItemOutcome outcome,
            String requestId
    ) {
        return libraryClient.listScanItems(scanId, offset, limit, outcome, requestId);
    }

    public Paper exclude(String paperId, String requestId) {
        return libraryClient.exclude(paperId, requestId);
    }

    public Paper restore(String paperId, String requestId) {
        return libraryClient.restore(paperId, requestId);
    }
}
