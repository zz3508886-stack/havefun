// P6 资料库页：知识点单元索引（四件套/题型/掌握标记）+ Anki 卡组索引

import { useEffect, useState } from 'react'
import { Alert, Button, Card, Drawer, Empty, Space, Table, Tag, Typography } from 'antd'
import { api } from './api'
import MarkdownBlocks from './MarkdownBlocks'
import type { Deck, KnowledgeUnit, KnowledgeUnitDetail } from './types'

const { Text } = Typography

function SuiteTag({ ok, label }: { ok: boolean; label: string }) {
  return <Tag color={ok ? 'success' : 'default'}>{label}</Tag>
}

export default function KnowledgeView() {
  const [units, setUnits] = useState<KnowledgeUnit[]>([])
  const [decks, setDecks] = useState<Deck[]>([])
  const [detail, setDetail] = useState<KnowledgeUnitDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.kbUnits(), api.kbDecks()])
      .then(([us, ds]) => {
        setUnits(us)
        setDecks(ds)
      })
      .catch((e) => setError(String(e)))
  }, [])

  const openUnit = async (path: string) => {
    try {
      setDetail(await api.kbUnit(path))
      setDrawerOpen(true)
    } catch (e) {
      setError(String(e))
    }
  }

  if (error)
    return <Alert type="error" message="加载资料库失败" description="请确认后端已启动（8000 端口）。" />

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Card
        size="small"
        title="知识点单元"
        style={{ marginBottom: 12 }}
        extra={<Text type="secondary">点击行查看梳理大纲</Text>}
      >
        {units.length ? (
          <Table<KnowledgeUnit>
            size="small"
            rowKey="path"
            dataSource={units}
            pagination={false}
            onRow={(u) => ({ onClick: () => openUnit(u.path), style: { cursor: 'pointer' } })}
            columns={[
              { title: '学科', dataIndex: 'subject', width: 90 },
              { title: '单元', dataIndex: 'unit', width: 130 },
              { title: '文档', dataIndex: 'path', ellipsis: true },
              {
                title: '四件套',
                width: 220,
                render: (_: unknown, u) => (
                  <Space size={4}>
                    <SuiteTag ok={u.has_qbank} label="题库" />
                    <SuiteTag ok={u.has_analysis} label="解析" />
                    <SuiteTag ok={u.has_catalog} label="目录" />
                  </Space>
                ),
              },
              {
                title: '自评标记',
                width: 170,
                render: (_: unknown, u) => (
                  <Space size={4}>
                    <Tag>⬜ {u.mastery['⬜'] ?? 0}</Tag>
                    <Tag color="warning">🟨 {u.mastery['🟨'] ?? 0}</Tag>
                    <Tag color="success">✅ {u.mastery['✅'] ?? 0}</Tag>
                  </Space>
                ),
              },
            ]}
          />
        ) : (
          <Empty description="暂无知识点单元" />
        )}
      </Card>

      <Card size="small" title="Anki 卡组（源文件 + 打包对照）">
        {decks.length ? (
          <Table<Deck>
            size="small"
            rowKey="name"
            dataSource={decks}
            pagination={false}
            columns={[
              { title: '牌组', dataIndex: 'name', width: 160 },
              { title: '卡片数', dataIndex: 'cards', width: 80 },
              {
                title: '层级',
                dataIndex: 'levels',
                width: 140,
                render: (v: string[]) =>
                  v.length ? v.map((l) => <Tag key={l}>{l}</Tag>) : <span>—</span>,
              },
              {
                title: 'apkg',
                width: 110,
                render: (_: unknown, d) =>
                  d.has_apkg ? <Tag color="success">已打包</Tag> : <Tag color="default">未打包</Tag>,
              },
              {
                title: '状态',
                width: 220,
                render: (_: unknown, d) =>
                  d.stale ? (
                    <Tag color="error">源文件已更新，待跑 build_decks.py</Tag>
                  ) : (
                    <Tag color="success">最新</Tag>
                  ),
              },
            ]}
          />
        ) : (
          <Empty description="暂无卡组" />
        )}
      </Card>

      <Drawer
        title={detail?.title ?? '单元详情'}
        width={720}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={<Button onClick={() => setDrawerOpen(false)}>关闭</Button>}
      >
        {detail ? (
          <div>
            <Space wrap style={{ marginBottom: 12 }}>
              {Object.entries(detail.meta).map(([k, v]) => (
                <Tag key={k}>
                  {k}：{v}
                </Tag>
              ))}
              {detail.qbank ? (
                <Tag color="blue">
                  题库 {detail.qbank.total} 题（
                  {Object.entries(detail.qbank.by_type)
                    .map(([t, n]) => `${t} ${n}`)
                    .join('，')}
                  ）
                </Tag>
              ) : (
                <Tag>暂无题库</Tag>
              )}
            </Space>
            {detail.outline.map((node, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <Typography.Title
                  level={(Math.min(node.level + 1, 5) as 1 | 2 | 3 | 4 | 5)}
                  style={{ marginBottom: 4 }}
                >
                  {node.title}
                </Typography.Title>
                <MarkdownBlocks blocks={node.blocks} />
              </div>
            ))}
          </div>
        ) : null}
      </Drawer>
    </div>
  )
}
