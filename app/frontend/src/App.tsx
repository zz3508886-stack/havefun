import { useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import { Alert, Empty, Input, Layout, Spin, Tabs, Tree, Typography, message } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { api } from './api'
import QuizView from './QuizView'
import ResultView from './ResultView'
import WrongBook from './WrongBook'
import type { QuizSet, SubmitResponse, Question, WrongPaperItem } from './types'

const { Header, Content, Sider } = Layout
const { Title } = Typography

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

export default function App() {
  const [tab, setTab] = useState<'quiz' | 'wrong'>('quiz')
  const [set, setCurrentSet] = useState<QuizSet | null>(null)
  const [resp, setResp] = useState<SubmitResponse | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [wrongPaper, setWrongPaper] = useState<{
    title: string
    questions: Question[]
    items: WrongPaperItem[]
  } | null>(null)

  const startQuiz = (s: QuizSet) => {
    setCurrentSet(s)
    setResp(null)
  }
  const backHome = () => {
    setCurrentSet(null)
    setResp(null)
  }
  const backFromPaper = () => {
    setWrongPaper(null)
    setResp(null)
    setTab('wrong')
  }
  const makePaper = async (by: string, value: string) => {
    try {
      const paper = await api.wrongPaper(by, value)
      if (!paper.questions.length) {
        message.warning('该口径下暂无错题')
        return
      }
      setWrongPaper({
        title: value,
        questions: paper.questions,
        items: paper.questions.map((q) => ({
          file_path: q.file_path,
          qid: q.real_qid,
          section_title: q.section_title,
        })),
      })
      setCurrentSet(null)
      setResp(null)
      setTab('quiz')
    } catch (e) {
      message.error(String(e))
    }
  }

  const quizPanel =
    resp && (set || wrongPaper) ? (
      <ResultView
        quizSet={
          set ?? {
            file_path: '',
            section_title: wrongPaper?.title ?? '',
            n_questions: 0,
            has_key: true,
          }
        }
        resp={resp}
        onBack={wrongPaper ? backFromPaper : backHome}
      />
    ) : set || wrongPaper ? (
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
          onSubmitted={setResp}
          onBack={backFromPaper}
        />
      ) : (
        <QuizView quizSet={set!} onSubmitted={setResp} onBack={backHome} />
      )
    ) : (
      <Empty style={{ marginTop: 64 }} description="从左侧选择一套题开始练习" />
    )

  return (
    <Layout style={{ height: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <Title level={4} style={{ color: '#fff', margin: 0 }}>
          复习管理系统
        </Title>
      </Header>
      <Layout style={{ flex: 1, minHeight: 0 }}>
        {tab === 'quiz' ? (
          <Sider
            width={280}
            collapsible
            collapsed={collapsed}
            onCollapse={setCollapsed}
            theme="light"
            style={{ borderRight: '1px solid #f0f0f0' }}
          >
            <SetsTree onPick={startQuiz} />
          </Sider>
        ) : null}
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Tabs
            activeKey={tab}
            onChange={(k) => setTab(k as 'quiz' | 'wrong')}
            items={[
              {
                key: 'quiz',
                label: '做题',
                children: quizPanel,
              },
              {
                key: 'wrong',
                label: '错题本',
                children: (
                  <WrongBook
                    onRedo={(item) => {
                      startQuiz({
                        file_path: item.file_path,
                        section_title: item.section_title,
                        n_questions: 0,
                        has_key: true,
                      })
                      setTab('quiz')
                    }}
                    onMakePaper={makePaper}
                    onRedoSet={(filePath, sectionTitle) => {
                      startQuiz({
                        file_path: filePath,
                        section_title: sectionTitle,
                        n_questions: 0,
                        has_key: true,
                      })
                      setTab('quiz')
                    }}
                  />
                ),
              },
            ]}
          />
        </Content>
      </Layout>
    </Layout>
  )
}
