import { requestJson } from './papers';
import type {
  LibraryFileIngestionData,
  LibraryFilesPage,
  LibraryFileUploadData,
  LibraryInfo,
  LibraryScan,
  LibraryScanItemOutcome,
  LibraryScanItemsPage,
  LibraryStateFilter,
  Paper,
} from './types';

export async function getLibraryInfo(signal?: AbortSignal): Promise<LibraryInfo> {
  return (await requestJson<LibraryInfo>('/api/v1/library', { signal })).data;
}

export async function listLibraryFiles(
  offset: number,
  limit: number,
  libraryState?: LibraryStateFilter,
  signal?: AbortSignal,
): Promise<LibraryFilesPage> {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (libraryState) {
    query.set('libraryState', libraryState);
  }
  return (
    await requestJson<LibraryFilesPage>(`/api/v1/library/files?${query}`, {
      signal,
    })
  ).data;
}

export async function uploadLibraryFile(file: File): Promise<LibraryFileUploadData> {
  const form = new FormData();
  form.append('file', file, file.name);
  return (
    await requestJson<LibraryFileUploadData>('/api/v1/library/files', {
      method: 'POST',
      body: form,
    })
  ).data;
}

export async function ingestLibraryFile(
  libraryFileId: string,
): Promise<LibraryFileIngestionData> {
  return (
    await requestJson<LibraryFileIngestionData>(
      `/api/v1/library/files/${encodeURIComponent(libraryFileId)}/ingestion`,
      { method: 'POST' },
    )
  ).data;
}

export async function createLibraryScan(): Promise<LibraryScan> {
  return (
    await requestJson<LibraryScan>('/api/v1/library/scans', {
      method: 'POST',
    })
  ).data;
}

export async function getLibraryScan(
  scanId: string,
  signal?: AbortSignal,
): Promise<LibraryScan> {
  return (
    await requestJson<LibraryScan>(
      `/api/v1/library/scans/${encodeURIComponent(scanId)}`,
      { signal },
    )
  ).data;
}

export async function listLibraryScanItems(
  scanId: string,
  offset: number,
  limit: number,
  outcome?: LibraryScanItemOutcome,
): Promise<LibraryScanItemsPage> {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (outcome) {
    query.set('outcome', outcome);
  }
  return (
    await requestJson<LibraryScanItemsPage>(
      `/api/v1/library/scans/${encodeURIComponent(scanId)}/items?${query}`,
    )
  ).data;
}

export async function excludePaper(paperId: string): Promise<Paper> {
  return (
    await requestJson<Paper>(
      `/api/v1/papers/${encodeURIComponent(paperId)}/exclusion`,
      { method: 'POST' },
    )
  ).data;
}

export async function restorePaper(paperId: string): Promise<Paper> {
  return (
    await requestJson<Paper>(
      `/api/v1/papers/${encodeURIComponent(paperId)}/exclusion`,
      { method: 'DELETE' },
    )
  ).data;
}

export function libraryFileUrl(libraryFileId: string, page?: number): string {
  const path = `/api/v1/library/files/${encodeURIComponent(libraryFileId)}/file`;
  return page === undefined ? path : `${path}#page=${page}`;
}
