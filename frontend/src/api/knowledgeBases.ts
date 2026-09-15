import { requestJson } from './papers';
import type {
  DeleteKnowledgeBaseData,
  KnowledgeBase,
  KnowledgeBaseMembersUpdate,
  KnowledgeBasePapersPage,
  KnowledgeBasesPage,
} from './types';

const base = '/api/v1/knowledge-bases';

export async function listKnowledgeBases(offset = 0, limit = 100, signal?: AbortSignal): Promise<KnowledgeBasesPage> {
  return (await requestJson<KnowledgeBasesPage>(`${base}?offset=${offset}&limit=${limit}`, { signal })).data;
}

export async function createKnowledgeBase(name: string): Promise<KnowledgeBase> {
  return (await requestJson<KnowledgeBase>(base, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  })).data;
}

export async function renameKnowledgeBase(id: string, name: string): Promise<KnowledgeBase> {
  return (await requestJson<KnowledgeBase>(`${base}/${encodeURIComponent(id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  })).data;
}

export async function deleteKnowledgeBase(id: string): Promise<DeleteKnowledgeBaseData> {
  return (await requestJson<DeleteKnowledgeBaseData>(`${base}/${encodeURIComponent(id)}`, { method: 'DELETE' })).data;
}

export async function listKnowledgeBasePapers(id: string, offset = 0, limit = 100, signal?: AbortSignal): Promise<KnowledgeBasePapersPage> {
  return (await requestJson<KnowledgeBasePapersPage>(`${base}/${encodeURIComponent(id)}/papers?offset=${offset}&limit=${limit}`, { signal })).data;
}

export async function updateKnowledgeBasePapers(id: string, addPaperIds: string[], removePaperIds: string[]): Promise<KnowledgeBaseMembersUpdate> {
  return (await requestJson<KnowledgeBaseMembersUpdate>(`${base}/${encodeURIComponent(id)}/papers`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ addPaperIds, removePaperIds }),
  })).data;
}
