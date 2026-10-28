// 做题模块：左侧套题树（上下文面板，可单独折叠）+ 右侧做题流程
// 套题树从全局侧边栏降级为本模块内部导航——其他模块不再显示它

import { useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import { Alert, Button, Empty, Input, Layout, Spin, Tree } from 'antd'
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import type { DataNode } from 'antd/es/tree'
import { api } from './api'
import QuizView from './QuizView'
import ResultView from './ResultView'
import type { QuizSet, SubmitResponse, Question, WrongPaperItem } from './types'

const { Content, Sider } = Layout

export interface WrongPaperState {
  title: string
  questions: Question[]
  items: WrongPaperItem[]
}

function SetsTree({ onPick }: { onPick: (s: QuizSet) => void }) {
  const [sets, setSets] = useState<QuizSet[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([])

  useEffect(() => {
    api
      .sets()
      .then(setSets)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const treeData = useMemo<DataNode[]>(() => {
    const kw = filter.trim().toLowerCase()
    const shown = kw
      ? sets.filter(
          (s) =>
            s.file_path.toLowerCase().includes(kw) ||
            s.section_title.toLowerCase().includes(kw),
        )
      : sets
    const setByKey = new Map<string, QuizSet>()
    const root: Record<string, any> = {}
    for (const s of shown) {
      const key = `${s.file_path}#${s.section_title}`
      setByKey.set(key, s)
      const parts = s.file_path.split('/')
      // sentinel 包裹，避免把 children 属性名写进 root 本身
      let node: Record<string, any> = { children: root }
      for (const p of parts) {
        node.children = node.children || {}
        node.children[p] = node.children[p] || {}
        node = node.children[p]
      }
      node.children = node.children || {}
      node.children[s.section_title] = { __set: key }
    }
    const toNodes = (obj: Record<string, any>, prefix: string): DataNode[] =>
      Object.entries(obj).map(([title, v]) => {
        const pathKey = prefix ? `${prefix}/${title}` : title
        if (v.__set && setByKey.has(v.__set)) {
          return { key: v.__set as string, title, isLeaf: true }
        }
        return {
          key: `dir::${pathKey}`,
          title,
          selectable: false,
          children: toNodes(v.children || {}, `dir::${pathKey}`),
        }
      })
    return toNodes(root, '')
  }, [sets, filter])

  // 数据就绪后默认展开全部目录，避免 defaultExpandAll 在数据异步到达后失效
  useEffect(() => {
    const all: Key[] = []
    const walk = (nodes: DataNode[]) =>
      nodes.forEach((n) => {
        if (n.children && n.children.length) {
          all.push(n.key)
          walk(n.children)
        }
      })
    walk(treeData)
    setExpandedKeys(all)
  }, [treeData])

  if (loading) return <Spin style={{ margin: 24 }} />
  if (error)
    return (
      <Alert
        type="error"
        message="加载套题失败"
        description="请确认后端已启动（8000 端口）且已完成索引构建。"
      />
    )
  if (!sets.length)
    return <Empty style={{ marginTop: 48 }} description="暂无已索引套题，先运行索引构建" />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: 8 }}>
        <Input.Search
          placeholder="筛选试卷 / 章节"
          allowClear
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '0 8px 8px' }}>
        <Tree
          treeData={treeData}
          expandedKeys={expandedKeys}
          onExpand={setExpandedKeys}
          autoExpandParent={false}
          blockNode
          onSelect={(keys) => {
            const k = keys[0] as string
            if (k && !k.startsWith('dir::')) {
              const s = sets.find((x) => `${x.file_path}#${x.section_title}` === k)
              if (s) onPick(s)
            }
          }}
        />
      </div>
    </div>
  )
}

export default function QuizModule({
  quizSet,
  resp,
  wrongPaper,
  onStartQuiz,
  onBackHome,
  onBackFromPaper,
  onSubmitted,
}: {
  quizSet: QuizSet | null
  resp: SubmitResponse | null
  wrongPaper: WrongPaperState | null
  onStartQuiz: (s: QuizSet) => void
  onBackHome: () => void
  onBackFromPaper: () => void
  onSubmitted: (r: SubmitResponse) => void
}) {
  // 面板折叠状态：做题页内部独立，与全局侧边栏折叠互不影响
  const [treeCollapsed, setTreeCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('quiz-tree-collapsed') === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('quiz-tree-collapsed', treeCollapsed ? '1' : '0')
    } catch {
      /* 存储失败不影响折叠功能 */
    }
  }, [treeCollapsed])

  const quizPanel =
    resp && (quizSet || wrongPaper) ? (
      <ResultView
        quizSet={
          quizSet ?? {
            file_path: '',
            section_title: wrongPaper?.title ?? '',
            n_questions: 0,
            has_key: true,
          }
        }
        resp={resp}
        onBack={wrongPaper ? onBackFromPaper : onBackHome}
      />
    ) : quizSet || wrongPaper ? (
      wrongPaper ? (
        <QuizView
          quizSet={{
            file_path: '',
            section_title: wrongPaper.title,
            n_questions: wrongPaper.questions.length,
            has_key: true,
          }}
          questions={wrongPaper.questions}
          submit={(answers) => api.submitWrong(wrongPaper.items, answers)}
          onSubmitted={onSubmitted}
          onBack={onBackFromPaper}
        />
      ) : (
        <QuizView quizSet={quizSet!} onSubmitted={onSubmitted} onBack={onBackHome} />
      )
    ) : (
      <Empty style={{ marginTop: 64 }} description="从左侧选择一套题开始练习" />
    )

  return (
    <Layout style={{ height: '100%', background: 'transparent' }}>
      <Sider
        width={264}
        collapsedWidth={0}
        collapsed={treeCollapsed}
        trigger={null}
        theme="light"
        style={{
          background: '#fff',
          borderRadius: 8,
          border: '1px solid #f0f0f0',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <span style={{ fontWeight: 600, fontSize: 13 }}>套题列表</span>
          <Button
            type="text"
            size="small"
            aria-label={treeCollapsed ? '展开套题列表' : '折叠套题列表'}
            title={treeCollapsed ? '展开套题列表' : '折叠套题列表'}
            onClick={() => setTreeCollapsed((c) => !c)}
            icon={treeCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          />
        </div>
        <SetsTree onPick={onStartQuiz} />
      </Sider>
      <Content style={{ padding: '0 0 0 12px', overflow: 'auto', minWidth: 0 }}>
        {/* 折叠态下 Sider 宽度为 0（内部按钮被裁切），展开入口必须放在 Sider 外，
            否则折叠后无法再次展开；状态虽入 localStorage，也不能依赖它兜底 */}
        {treeCollapsed && (
          <div style={{ marginBottom: 8 }}>
            <Button
              type="text"
              size="small"
              aria-label="展开套题列表"
              title="展开套题列表"
              onClick={() => setTreeCollapsed(false)}
              icon={<MenuUnfoldOutlined />}
            >
              套题列表
            </Button>
          </div>
        )}
        {quizPanel}
      </Content>
    </Layout>
  )
}
