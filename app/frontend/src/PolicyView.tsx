// P6 政策资讯页：关键时间节点 + 目标院校 + 政策文档结构化阅读

import { useEffect, useState } from 'react'
import { Alert, Card, Col, Empty, Row, Segmented, Table, Tag, Typography } from 'antd'
import { api } from './api'
import MarkdownBlocks from './MarkdownBlocks'
import type { KeyDate, PolicyDoc, PolicyDocDetail, School } from './types'

const { Title } = Typography

function ConfirmTag({ v }: { v: string }) {
  if (!v) return <span>—</span>
  const color = v.includes('✅') ? 'success' : v.includes('⬜') ? 'default' : 'warning'
  return <Tag color={color}>{v}</Tag>
}

export default function PolicyView() {
  const [docs, setDocs] = useState<PolicyDoc[]>([])
  const [keyDates, setKeyDates] = useState<KeyDate[]>([])
  const [schools, setSchools] = useState<School[]>([])
  const [detail, setDetail] = useState<PolicyDocDetail | null>(null)
  const [selected, setSelected] = useState<string | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.policyDocs(), api.policyKeyDates(), api.policySchools()])
      .then(([ds, kd, sc]) => {
        setDocs(ds)
        setKeyDates(kd)
        setSchools(sc)
        if (ds.length) setSelected(ds[0].path)
      })
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!selected) return
    api
      .policyDoc(selected)
      .then(setDetail)
      .catch((e) => setError(String(e)))
  }, [selected])

  if (error)
    return <Alert type="error" message="加载政策资讯失败" description="请确认后端已启动（8000 端口）。" />
  if (!docs.length && !detail) return <Empty style={{ marginTop: 48 }} description="暂无政策文档" />

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Card size="small" title="报名关键时间节点" style={{ marginBottom: 12 }}>
        {keyDates.length ? (
          <Table<KeyDate>
            size="small"
            rowKey="item"
            dataSource={keyDates}
            pagination={false}
            columns={[
              { title: '事项', dataIndex: 'item', width: 200 },
              { title: '预计时间', dataIndex: 'time' },
              {
                title: '确认状态',
                dataIndex: 'confirmed',
                width: 120,
                render: (v: string) => <ConfirmTag v={v} />,
              },
            ]}
          />
        ) : (
          <Empty description="暂无时间节点" />
        )}
      </Card>

      <Card size="small" title="目标院校简章核对" style={{ marginBottom: 12 }}>
        {schools.length ? (
          <Table<School>
            size="small"
            rowKey={(r) => r.school + r.level}
            dataSource={schools}
            pagination={false}
            columns={[
              { title: '院校', dataIndex: 'school', width: 200 },
              { title: '层次', dataIndex: 'level', width: 100 },
              {
                title: '简章链接',
                dataIndex: 'link',
                render: (v: string) =>
                  v ? (
                    <a href={v} target="_blank" rel="noreferrer">
                      {v}
                    </a>
                  ) : (
                    '—'
                  ),
              },
              {
                title: '已核对',
                dataIndex: 'checked',
                width: 100,
                render: (v: string) => <ConfirmTag v={v} />,
              },
              {
                title: '关注状态',
                dataIndex: 'following',
                width: 100,
                render: (v: string) => <ConfirmTag v={v} />,
              },
            ]}
          />
        ) : (
          <Empty description="暂无目标院校（待填写）" />
        )}
      </Card>

      <Card
        size="small"
        title="政策文档"
        extra={
          docs.length > 1 ? (
            <Segmented
              value={selected}
              onChange={(v) => setSelected(v as string)}
              options={docs.map((d) => ({ label: d.name, value: d.path }))}
            />
          ) : null
        }
      >
        {detail ? (
          <div>
            <Row gutter={8} align="middle" style={{ marginBottom: 8 }}>
              <Col>
                <Title level={5} style={{ margin: 0 }}>
                  {detail.title}
                </Title>
              </Col>
              {Object.entries(detail.meta).map(([k, v]) => (
                <Col key={k}>
                  <Tag>
                    {k}：{v}
                  </Tag>
                </Col>
              ))}
            </Row>
            {detail.outline.map((node, i) => (
              <div key={i} style={{ marginBottom: 12 }}>
                <Title level={(Math.min(node.level + 1, 5) as 1 | 2 | 3 | 4 | 5)} style={{ marginBottom: 4 }}>
                  {node.title}
                </Title>
                <MarkdownBlocks blocks={node.blocks} />
              </div>
            ))}
          </div>
        ) : (
          <Empty description="选择一篇政策文档" />
        )}
      </Card>
    </div>
  )
}
