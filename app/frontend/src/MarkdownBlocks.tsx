// 结构化 markdown 块渲染器（mdview 后端契约）：table / list / p / code

import { Table, Typography } from 'antd'
import type { MdBlock } from './types'

const { Paragraph, Text } = Typography

export default function MarkdownBlocks({ blocks }: { blocks: MdBlock[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === 'table' && b.header && b.rows) {
          const columns = b.header.map((h, ci) => ({
            title: h,
            dataIndex: String(ci),
            ellipsis: true,
            render: (v: string | undefined) => (
              <span style={{ whiteSpace: 'pre-wrap' }}>{v ?? ''}</span>
            ),
          }))
          const data = b.rows.map((r) =>
            Object.fromEntries(r.map((v, ci) => [String(ci), v])),
          )
          return (
            <Table
              key={i}
              size="small"
              pagination={false}
              columns={columns}
              dataSource={data}
              style={{ margin: '8px 0' }}
            />
          )
        }
        if (b.type === 'list' && b.items) {
          const items = b.items.map((it, j) => (
            <li key={j} style={{ marginBottom: 2 }}>
              {it.checked === null ? null : it.checked ? '☑ ' : '☐ '}
              {it.text}
            </li>
          ))
          return b.ordered ? (
            <ol key={i} style={{ paddingLeft: 22 }}>
              {items}
            </ol>
          ) : (
            <ul key={i} style={{ paddingLeft: 22 }}>
              {items}
            </ul>
          )
        }
        if (b.type === 'p' && b.text) {
          return (
            <Paragraph key={i} style={{ marginBottom: 8 }}>
              {b.text}
            </Paragraph>
          )
        }
        if (b.type === 'code' && b.text) {
          return (
            <pre
              key={i}
              style={{
                background: '#f6f8fa',
                padding: 12,
                borderRadius: 6,
                overflow: 'auto',
              }}
            >
              <Text>{b.text}</Text>
            </pre>
          )
        }
        return null
      })}
    </>
  )
}
