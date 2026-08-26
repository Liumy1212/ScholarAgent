import { useState } from 'react';
import { ConfigProvider, Layout, Menu, Typography, theme } from 'antd';
import { ChatPage } from './pages/ChatPage';
import { KnowledgeBasePage } from './pages/KnowledgeBasePage';

type PageKey = 'chat' | 'knowledge';

const menuItems = [
  { key: 'knowledge', label: '知识库' },
  { key: 'chat', label: '论文问答' },
];

export function App() {
  const [page, setPage] = useState<PageKey>('knowledge');

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#3157d5',
          borderRadius: 10,
          colorBgLayout: '#f5f7fb',
          fontFamily:
            "Inter, 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
        },
      }}
    >
      <Layout className="app-layout">
        <Layout.Header className="app-header">
          <div className="brand" aria-label="AIResearcher 首页">
            <span className="brand-mark" aria-hidden="true">
              AR
            </span>
            <Typography.Text className="brand-name">
              AIResearcher
            </Typography.Text>
          </div>
          <Menu
            aria-label="主导航"
            className="main-menu"
            theme="dark"
            mode="horizontal"
            selectedKeys={[page]}
            items={menuItems}
            onClick={({ key }) => setPage(key as PageKey)}
          />
        </Layout.Header>
        <Layout.Content>
          {page === 'chat' ? <ChatPage /> : <KnowledgeBasePage />}
        </Layout.Content>
        <Layout.Footer className="app-footer">
          AIResearcher · Single-paper Demo v0.1
        </Layout.Footer>
      </Layout>
    </ConfigProvider>
  );
}
