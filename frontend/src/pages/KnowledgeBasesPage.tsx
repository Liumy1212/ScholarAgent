import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Empty, Flex, Input, List, Modal, Pagination, Popconfirm, Select, Space, Tag, Typography } from 'antd';
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBasePapers,
  listKnowledgeBases,
  renameKnowledgeBase,
  updateKnowledgeBasePapers,
} from '../api/knowledgeBases';
import { listPapers, PaperApiError } from '../api/papers';
import type { KnowledgeBase, Paper } from '../api/types';

const PAGE_SIZE = 20;

function errorText(error: unknown): string {
  return error instanceof PaperApiError ? `${error.message}（${error.code}）`
    : error instanceof Error ? error.message : '请求失败。';
}

export function KnowledgeBasesPage() {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [members, setMembers] = useState<Paper[]>([]);
  const [memberTotal, setMemberTotal] = useState(0);
  const [memberOffset, setMemberOffset] = useState(0);
  const [allPapers, setAllPapers] = useState<Paper[]>([]);
  const [chosenIds, setChosenIds] = useState<string[]>([]);
  const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([]);
  const [name, setName] = useState('');
  const [editName, setEditName] = useState('');
  const [editing, setEditing] = useState<KnowledgeBase>();
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const selected = bases.find((item) => item.knowledgeBaseId === selectedId);

  const loadBases = useCallback(async () => {
    const page = await listKnowledgeBases();
    setBases(page.items);
    setSelectedId((current) => current && page.items.some((item) => item.knowledgeBaseId === current) ? current : page.items[0]?.knowledgeBaseId);
  }, []);

  const loadMembers = useCallback(async (id: string, offset: number) => {
    const page = await listKnowledgeBasePapers(id, offset, PAGE_SIZE);
    setMembers(page.items); setMemberTotal(page.total); setSelectedMemberIds([]);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listKnowledgeBases(0, 100, controller.signal), listPapers(controller.signal)])
      .then(([basePage, papers]) => {
        setBases(basePage.items); setAllPapers(papers.items);
        setSelectedId(basePage.items[0]?.knowledgeBaseId); setError(undefined);
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(errorText(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedId) { setMembers([]); setMemberTotal(0); return; }
    void loadMembers(selectedId, memberOffset).catch((reason: unknown) => setError(errorText(reason)));
  }, [loadMembers, memberOffset, selectedId]);

  const availableOptions = useMemo(() => {
    const memberIds = new Set(members.map((paper) => paper.paperId));
    return allPapers.filter((paper) => !memberIds.has(paper.paperId)).map((paper) => ({
      value: paper.paperId, label: `${paper.title} · ${paper.status}`,
    }));
  }, [allPapers, members]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(undefined);
    try { await action(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(false); }
  };

  return <main className="page-shell page-shell-wide" aria-labelledby="knowledge-bases-title">
    <Space direction="vertical" size={24} className="full-width">
      <div><Tag color="purple">逻辑论文集合</Tag><Typography.Title id="knowledge-bases-title" level={2}>知识库</Typography.Title>
        <Typography.Paragraph type="secondary">知识库只保存论文成员关系，不对应文件夹，也不会复制 PDF、chunk 或向量。</Typography.Paragraph></div>
      {error ? <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} /> : null}
      <Card title="创建知识库">
        <Flex gap={12}><Input aria-label="知识库名称" maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="输入知识库名称" />
          <Button type="primary" loading={busy} disabled={!name.trim()} onClick={() => void run(async () => { const created = await createKnowledgeBase(name); setName(''); await loadBases(); setSelectedId(created.knowledgeBaseId); })}>创建</Button></Flex>
      </Card>
      <Card title={`知识库列表（${bases.length}）`} loading={loading}>
        {bases.length === 0 ? <Empty description="还没有知识库" /> : <List dataSource={bases} renderItem={(base) => <List.Item
          className={base.knowledgeBaseId === selectedId ? 'selected-library' : undefined}
          actions={[
            <Button key="open" type="link" onClick={() => { setMemberOffset(0); setSelectedId(base.knowledgeBaseId); }}>管理成员</Button>,
            <Button key="rename" type="link" onClick={() => { setEditing(base); setEditName(base.name); }}>重命名</Button>,
            <Popconfirm key="delete" title="删除该知识库？" description="只删除集合和成员关系，论文知识与 PDF 均保留。" onConfirm={() => void run(async () => { await deleteKnowledgeBase(base.knowledgeBaseId); await loadBases(); })}><Button danger type="link">删除</Button></Popconfirm>,
          ]}><List.Item.Meta title={base.name} description={`${base.paperCount} 篇成员 · ${base.searchablePaperCount} 篇可检索`} /></List.Item>} />}
      </Card>
      <Card title={selected ? `${selected.name} · 成员管理` : '成员管理'}>
        {!selected ? <Empty description="请先创建或选择知识库" /> : <Space direction="vertical" size={16} className="full-width">
          <Flex gap={12} wrap><Select aria-label="添加论文" mode="multiple" className="member-picker" value={chosenIds} options={availableOptions} onChange={setChosenIds} placeholder="选择要添加的论文" />
            <Button disabled={chosenIds.length === 0} loading={busy} onClick={() => void run(async () => { await updateKnowledgeBasePapers(selected.knowledgeBaseId, chosenIds, []); setChosenIds([]); await Promise.all([loadBases(), loadMembers(selected.knowledgeBaseId, memberOffset)]); })}>添加所选论文</Button>
            <Button danger disabled={selectedMemberIds.length === 0} loading={busy} onClick={() => void run(async () => { await updateKnowledgeBasePapers(selected.knowledgeBaseId, [], selectedMemberIds); await Promise.all([loadBases(), loadMembers(selected.knowledgeBaseId, memberOffset)]); })}>移除所选成员</Button></Flex>
          {members.length === 0 ? <Empty description="该知识库暂无成员" /> : <List dataSource={members} renderItem={(paper) => <List.Item actions={[<input key="select" aria-label={`选择 ${paper.title}`} type="checkbox" checked={selectedMemberIds.includes(paper.paperId)} onChange={(event) => setSelectedMemberIds((current) => event.target.checked ? [...current, paper.paperId] : current.filter((id) => id !== paper.paperId))} />]}><List.Item.Meta title={paper.title} description={<Space><Tag color={paper.searchable ? 'success' : 'default'}>{paper.searchable ? '可检索' : '不可检索'}</Tag><span>{paper.status} · {paper.sourceStatus}</span></Space>} /></List.Item>} />}
          {memberTotal > PAGE_SIZE ? <Pagination current={memberOffset / PAGE_SIZE + 1} pageSize={PAGE_SIZE} total={memberTotal} showSizeChanger={false} onChange={(page) => setMemberOffset((page - 1) * PAGE_SIZE)} /> : null}
        </Space>}
      </Card>
    </Space>
    <Modal title="重命名知识库" open={Boolean(editing)} confirmLoading={busy} okButtonProps={{ disabled: !editName.trim() }} onCancel={() => { setEditing(undefined); setEditName(''); }} onOk={() => editing && void run(async () => { await renameKnowledgeBase(editing.knowledgeBaseId, editName); setEditing(undefined); setEditName(''); await loadBases(); })}><Input aria-label="新知识库名称" maxLength={100} value={editName} onChange={(event) => setEditName(event.target.value)} /></Modal>
  </main>;
}
