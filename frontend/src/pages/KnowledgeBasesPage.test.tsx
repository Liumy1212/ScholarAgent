import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { KnowledgeBasesPage } from './KnowledgeBasesPage';

function result(init: RequestInit | undefined, data: unknown, status = 200): Response {
  const requestId = new Headers(init?.headers).get('X-Request-Id') ?? '';
  return new Response(JSON.stringify({ code: 'SUCCESS', message: 'Success.', requestId, data }), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId },
  });
}

function paper(paperId: string, title: string, searchable: boolean) {
  return {
    paperId, title, authors: ['Synthetic Author'], publicationYear: 2026,
    fileName: `${paperId}.pdf`, fileSizeBytes: 1024,
    libraryRelativePath: `uploads/${paperId}.pdf`, sourceStatus: 'AVAILABLE',
    status: searchable ? 'READY' : 'PROCESSING', searchable,
    pageCount: searchable ? 2 : null,
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:01:00Z',
    currentIngestion: null,
  };
}

it('完成知识库创建、重命名、批量添加、批量移除和删除流程', async () => {
  const papers = [paper('paper-001', 'Paper One', true), paper('paper-002', 'Paper Two', false)];
  const createdBase = {
    knowledgeBaseId: 'kb-001', name: '初始知识库', paperCount: 1, searchablePaperCount: 1,
    createdAt: '2026-01-01T00:00:00Z', updatedAt: '2026-01-01T00:01:00Z',
  };
  let bases: typeof createdBase[] = [];
  const members = new Set<string>();
  const memberBodies: unknown[] = [];

  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === '/api/v1/papers') return result(init, { items: papers, total: papers.length });
    if (path.includes('/papers?')) {
      const items = papers.filter((item) => members.has(item.paperId));
      return result(init, { items, total: items.length, offset: 0, limit: 20 });
    }
    if (path.endsWith('/papers') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as { addPaperIds: string[]; removePaperIds: string[] };
      memberBodies.push(body);
      body.addPaperIds.forEach((id) => members.add(id));
      body.removePaperIds.forEach((id) => members.delete(id));
      bases[0] = { ...bases[0]!, paperCount: members.size, searchablePaperCount: members.has('paper-001') ? 1 : 0 };
      return result(init, { knowledgeBase: bases[0], addedPaperIds: body.addPaperIds, removedPaperIds: body.removePaperIds });
    }
    if (path === '/api/v1/knowledge-bases' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as { name: string };
      bases = [{ ...createdBase, name: body.name, paperCount: 0, searchablePaperCount: 0 }];
      return result(init, bases[0], 201);
    }
    if (path === '/api/v1/knowledge-bases?offset=0&limit=100') {
      return result(init, { items: bases, total: bases.length, offset: 0, limit: 100 });
    }
    if (path.endsWith('/kb-001') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as { name: string };
      bases[0] = { ...bases[0]!, name: body.name };
      return result(init, bases[0]);
    }
    if (path.endsWith('/kb-001') && init?.method === 'DELETE') {
      bases = [];
      return result(init, { knowledgeBaseId: 'kb-001', deleted: true });
    }
    throw new Error(`unexpected request: ${init?.method ?? 'GET'} ${path}`);
  }));

  render(<KnowledgeBasesPage />);
  expect(await screen.findByText('还没有知识库')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('知识库名称'), { target: { value: '初始知识库' } });
  fireEvent.click(screen.getByRole('button', { name: /创\s*建/ }));
  expect(await screen.findByText('初始知识库')).toBeTruthy();

  fireEvent.mouseDown(screen.getByRole('combobox', { name: '添加论文' }));
  fireEvent.click(await screen.findByText('Paper One · READY'));
  fireEvent.click(await screen.findByText('Paper Two · PROCESSING'));
  fireEvent.click(screen.getByRole('button', { name: '添加所选论文' }));
  await waitFor(() => expect(memberBodies).toContainEqual({ addPaperIds: ['paper-001', 'paper-002'], removePaperIds: [] }));
  expect(await screen.findByText('Paper One')).toBeTruthy();
  expect(await screen.findByText('Paper Two')).toBeTruthy();

  fireEvent.click(screen.getByLabelText('选择 Paper One'));
  fireEvent.click(screen.getByRole('button', { name: '移除所选成员' }));
  await waitFor(() => expect(memberBodies).toContainEqual({ addPaperIds: [], removePaperIds: ['paper-001'] }));

  fireEvent.click(screen.getByRole('button', { name: '重命名' }));
  fireEvent.change(screen.getByLabelText('新知识库名称'), { target: { value: '重命名知识库' } });
  fireEvent.click(screen.getByRole('button', { name: 'OK' }));
  expect(await screen.findByText('重命名知识库')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /删\s*除/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'OK' }));
  expect(await screen.findByText('还没有知识库')).toBeTruthy();
});
