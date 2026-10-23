import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Collapse, Empty, Segmented, Space, Spin, Table, Tag } from 'antd'
import { api } from './api'
import type { WrongItem } from './types'

type Mode = 'quiz' | 'sub' | 'cat'

interface Group {
  key: string
  label: string
  set?: { file_path: string; section_title: string }
  items: WrongItem[]
}

function groupKeyOf(r: WrongItem, mode: Mode): string {
  if (mode === 'quiz') return `${r.file_path}#${r.section_title}`
  if (mode === 'sub') return r.section_title || '未分类'
  return r.file_path.split('/')[0] || '未分类'
}

function groupLabel(r: WrongItem, mode: Mode): string {
  if (mode === 'quiz') return r.section_title || r.file_path
  if (mode === 'sub') return r.section_title || '未分类'
  return r.file_path.split('/')[0] || '未分类'
}

export default function WrongBook({
  onRedo,
  onRedoSet,
  onMakePaper,
}: {
  onRedo: (item: WrongItem) => void
  onRedoSet: (filePath: string, sectionTitle: string) => void
  onMakePaper: (by: Mode, value: string) => void
}) {
  const [rows, setRows] = useState<WrongItem[]>([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<Mode>('quiz')

  const load = () => {
    setLoading(true)
    api
      .wrong()
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, Group>()
    for (const r of rows) {
      const k = groupKeyOf(r, mode)
      let g = map.get(k)
      if (!g) {
        g = { key: k, label: groupLabel(r, mode), items: [] }
        if (mode === 'quiz') {
          g.set = { file_path: r.file_path, section_title: r.section_title }
        }
        map.set(k, g)
      }
      g.items.push(r)
    }
    return Array.from(map.values()).sort((a, b) => b.items.length - a.items.length)
  }, [rows, mode])

  if (loading) return <Spin style={{ margin: 24 }} />
  if (!rows.length)
    return <Empty style={{ marginTop: 48 }} description="暂无错题——做错题会自动收录到这里" />

  const columns = [
    { title: '题号', dataIndex: 'qid', width: 80 },
    { title: '题型', dataIndex: 'q_type', width: 90 },
    {
      title: '来源',
      key: 'src',
      render: (_: unknown, r: WrongItem) =>
        `${r.file_path.split('/')[0]} · ${r.section_title}`,
    },
    {
      title: '题干',
      dataIndex: 'stem',
      ellipsis: true,
      render: (v: string | null) => v || '—',
    },
    {
      title: '错次',
      dataIndex: 'times',
      width: 70,
      render: (v: number) => <Tag color="red">{v}</Tag>,
    },
    { title: '最近', dataIndex: 'last_at', width: 160 },
    {
      title: '操作',
      width: 80,
      render: (_: unknown, r: WrongItem) => (
        <Button size="small" type="link" onClick={() => onRedo(r)}>
          重做
        </Button>
      ),
    },
  ]

  return (
    <Card
      style={{ maxWidth: 1000, margin: '0 auto' }}
      title={`错题本（自动收录 · 共 ${rows.length} 题）`}
      extra={
        <Segmented<Mode>
          value={mode}
          onChange={setMode}
          options={[
            { label: '按测验', value: 'quiz' },
            { label: '按小类别', value: 'sub' },
            { label: '按大类别', value: 'cat' },
          ]}
        />
      }
    >
      <Collapse
        defaultActiveKey={groups.map((g) => g.key)}
        items={groups.map((g) => ({
          key: g.key,
          label: `${g.label} · ${g.items.length} 题`,
          extra: (
            <Space size="small">
              {mode === 'quiz' && g.set ? (
                <Button
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation()
                    onRedoSet(g.set!.file_path, g.set!.section_title)
                  }}
                >
                  重做整套
                </Button>
              ) : null}
              <Button
                size="small"
                type="primary"
                onClick={(e) => {
                  e.stopPropagation()
                  onMakePaper(mode, g.key)
                }}
              >
                生成试卷
              </Button>
            </Space>
          ),
          children: (
            <Table<WrongItem>
              rowKey={(r) => `${r.file_path}#${r.qid}`}
              dataSource={g.items}
              columns={columns}
              pagination={false}
              size="small"
            />
          ),
        }))}
      />
    </Card>
  )
}
