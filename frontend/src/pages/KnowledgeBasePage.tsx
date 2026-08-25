import { Card, Empty, Space, Tag, Typography } from 'antd';

export function KnowledgeBasePage() {
  return (
    <main className="page-shell" aria-labelledby="knowledge-base-title">
      <Space direction="vertical" size={24} className="full-width">
        <div>
          <Tag color="blue">Phase 0</Tag>
          <Typography.Title id="knowledge-base-title" level={2}>
            论文知识库
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            管理论文、解析状态和索引的能力将在后续阶段接入。
          </Typography.Paragraph>
        </div>

        <Card className="surface-card">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <Space direction="vertical" size={4}>
                <Typography.Text strong>知识库功能正在准备中</Typography.Text>
                <Typography.Text type="secondary">
                  Phase 0 先验证 React → Java BFF → Python Agent 的流式问答链路。
                </Typography.Text>
              </Space>
            }
          />
        </Card>
      </Space>
    </main>
  );
}
