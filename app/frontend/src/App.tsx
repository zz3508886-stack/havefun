// 应用外壳：侧边栏主导航（六个模块）+ 内容区渲染当前模块
// 做题模块自带套题树面板（QuizModule），其他模块不再显示套题树

import { useEffect, useState } from 'react'
import { Button, Layout, Menu, Typography, message } from 'antd'
import type { MenuProps } from 'antd'
import {
  BarChartOutlined,
  BookOutlined,
  CalendarOutlined,
  EditOutlined,
  FileProtectOutlined,
  FolderOpenOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import { api } from './api'
import QuizModule from './QuizModule'
import WrongBook from './WrongBook'
import PlanView from './PlanView'
import StatsView from './StatsView'
import KnowledgeView from './KnowledgeView'
import PolicyView from './PolicyView'
import type { QuizSet, SubmitResponse, Question, WrongPaperItem } from './types'

const { Header, Content, Sider } = Layout
const { Title } = Typography

type ModuleKey = 'quiz' | 'wrong' | 'plan' | 'stats' | 'kb' | 'policy'

const MODULES: { key: ModuleKey; label: string; icon: React.ReactNode }[] = [
  { key: 'quiz', label: '做题', icon: <EditOutlined /> },
  { key: 'wrong', label: '错题本', icon: <BookOutlined /> },
  { key: 'plan', label: '复习计划', icon: <CalendarOutlined /> },
  { key: 'stats', label: '学情', icon: <BarChartOutlined /> },
  { key: 'kb', label: '资料库', icon: <FolderOpenOutlined /> },
  { key: 'policy', label: '政策资讯', icon: <FileProtectOutlined /> },
]

const MODULE_TITLES: Record<ModuleKey, string> = {
  quiz: '做题',
  wrong: '错题本',
  plan: '复习计划',
  stats: '学情',
  kb: '资料库',
  policy: '政策资讯',
}

export default function App() {
  const [module, setModule] = useState<ModuleKey>('quiz')
  // 做题流程状态提升到 App：错题本的「重做/组卷」需要跨模块启动做题
  const [set, setCurrentSet] = useState<QuizSet | null>(null)
  const [resp, setResp] = useState<SubmitResponse | null>(null)
  const [wrongPaper, setWrongPaper] = useState<{
    title: string
    questions: Question[]
    items: WrongPaperItem[]
  } | null>(null)

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('sider-collapsed') === '1'
    } catch {
      return false // 隐私模式等取不到 localStorage 时按展开处理
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('sider-collapsed', collapsed ? '1' : '0')
    } catch {
      /* 存储失败不影响折叠功能 */
    }
  }, [collapsed])

  const startQuiz = (s: QuizSet) => {
    setCurrentSet(s)
    setResp(null)
    setModule('quiz') // 从错题本点套题时切回做题页，避免出现“选中的是做题内容、却停在错题本”
  }
  const backHome = () => {
    setCurrentSet(null)
    setResp(null)
  }
  const backFromPaper = () => {
    setWrongPaper(null)
    setResp(null)
    setModule('wrong')
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
      setModule('quiz')
    } catch (e) {
      message.error(String(e))
    }
  }

  const menuItems: MenuProps['items'] = MODULES.map((m) => ({
    key: m.key,
    icon: m.icon,
    label: m.label,
  }))

  return (
    <Layout style={{ height: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', gap: 12, paddingInline: 16 }}>
        <Button
          type="text"
          aria-label={collapsed ? '展开导航栏' : '折叠导航栏'}
          title={collapsed ? '展开导航栏' : '折叠导航栏'}
          onClick={() => setCollapsed((c) => !c)}
          style={{ color: '#fff' }}
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        />
        <Title level={4} style={{ color: '#fff', margin: 0 }}>
          复习管理系统
        </Title>
        <span style={{ color: 'rgba(255,255,255,.65)', fontSize: 13 }}>{MODULE_TITLES[module]}</span>
      </Header>
      <Layout style={{ flex: 1, minHeight: 0 }}>
        <Sider
          width={216}
          collapsedWidth={64}
          collapsed={collapsed}
          theme="light"
          style={{ borderRight: '1px solid #f0f0f0' }}
        >
          <Menu
            mode="inline"
            theme="light"
            selectedKeys={[module]}
            items={menuItems}
            onSelect={({ key }) => setModule(key as ModuleKey)}
            style={{ borderInlineEnd: 'none' }}
          />
        </Sider>
        <Content style={{ padding: 16, overflow: 'auto', minWidth: 0 }}>
          {module === 'quiz' && (
            <QuizModule
              quizSet={set}
              resp={resp}
              wrongPaper={wrongPaper}
              onStartQuiz={startQuiz}
              onBackHome={backHome}
              onBackFromPaper={backFromPaper}
              onSubmitted={setResp}
            />
          )}
          {module === 'wrong' && (
            <WrongBook
              onRedo={(item) => {
                startQuiz({
                  file_path: item.file_path,
                  section_title: item.section_title,
                  n_questions: 0,
                  has_key: true,
                })
              }}
              onMakePaper={makePaper}
              onRedoSet={(filePath, sectionTitle) => {
                startQuiz({
                  file_path: filePath,
                  section_title: sectionTitle,
                  n_questions: 0,
                  has_key: true,
                })
              }}
            />
          )}
          {module === 'plan' && <PlanView />}
          {module === 'stats' && <StatsView />}
          {module === 'kb' && <KnowledgeView />}
          {module === 'policy' && <PolicyView />}
        </Content>
      </Layout>
    </Layout>
  )
}
