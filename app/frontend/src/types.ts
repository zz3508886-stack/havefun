// 与后端 /api/quiz/* 契约对齐的类型定义

export interface QuizSet {
  file_path: string
  section_title: string
  n_questions: number
  has_key: boolean
}

export interface QuestionOption {
  label: string
  text: string
}

export interface Question {
  qid: string
  q_type: string
  stem: string
  options: QuestionOption[]
  difficulty: string
}

export interface SetResponse {
  file_path: string
  section_title: string
  questions: Question[]
}

export interface ResultItem {
  qid: string
  key?: string
  file_path?: string
  section_title?: string
  q_type: string
  difficulty: string
  stem: string
  options: QuestionOption[]
  student: string | null
  is_correct: boolean | null
  eval_state: string
  error_type: string | null
  note: string | null
  correct_answer?: string
  explanation?: string
}

export interface Summary {
  total: number
  correct: number
  wrong: number
  pending: number
}

export interface SubmitResponse {
  batch_id: string
  results: ResultItem[]
  summary: Summary
  writeback: string
  warning?: string
}

export interface WrongItem {
  file_path: string
  qid: string
  section_title: string
  stem: string | null
  q_type: string | null
  last_at: string
  times: number
}

export interface FeedbackRequest {
  file_path: string
  section_title: string
  qid: string
  error_type?: string | null
  confused?: boolean
}

export interface ReviewRequest {
  batch_id: string
  file_path: string
  qid: string
  is_correct: boolean
  error_type?: string | null
}

export interface WrongPaperQuestion {
  qid: string
  real_qid: string
  file_path: string
  section_title: string
  q_type: string
  stem: string
  options: QuestionOption[]
  difficulty: string
}

export interface WrongPaperResponse {
  by: string
  value: string
  questions: WrongPaperQuestion[]
}

export interface WrongPaperItem {
  file_path: string
  qid: string
  section_title?: string
}

// R18 五类错因（与后端 ERROR_TYPES、错题本/README 一致）
export const ERROR_TYPES = [
  '概念不清',
  '计算失误',
  '思路错误',
  '审题偏差',
  '知识遗忘',
] as const

// ---- P4 复习计划 ----

// 节点状态（与 节点安排.md 节点总表状态列、plan_checkins.status 一致）
export const PLAN_STATUSES = ['⬜', '🟨', '✅'] as const
export type PlanStatus = (typeof PLAN_STATUSES)[number]

export const PLAN_STATUS_LABEL: Record<PlanStatus, string> = {
  '⬜': '未开始',
  '🟨': '进行中',
  '✅': '已完成',
}

export interface PlanNode {
  node_id: string
  name: string
  date_range: string
  stage: string
  status: PlanStatus // 文档状态列现值
  derived_status: PlanStatus // 由打卡明细推导（最近一次打卡）
  checkin_count: number
  last_checkin_at: string | null
}

export interface CheckinRequest {
  node_id: string
  status: PlanStatus
  notes?: string | null
}

export interface CheckinResponse {
  ok: boolean
  id: number
  node_id: string
  status: PlanStatus
  writeback: string // written / unchanged / conflict / precheck_failed / node_not_found
  warning?: string | null
}

export interface PlanCheckin {
  id: number
  node_id: string
  status: PlanStatus
  notes: string | null
  created_at: string
}

// ---- P5 学情统计 ----

export interface QuizOverview {
  total: number
  correct: number
  wrong: number
  pending: number
  judged: number
  accuracy: number
  batches: number
  questions: number
}

export interface StatsOverview {
  quiz: QuizOverview
  feedback: { total: number; confused: number }
  plan: {
    checkin_days: number
    streak_days: number
    last_checkin_at: string | null
    last_node: string | null
    last_status: PlanStatus | null
  }
}

export interface TrendPoint {
  date: string
  answered: number
  correct: number
  wrong: number
  pending: number
  accuracy: number
}

export interface TrendResponse {
  days: number
  series: TrendPoint[]
}

export interface SubjectStat {
  subject: string
  total: number
  correct: number
  wrong: number
  pending: number
  judged: number
  accuracy: number
}

export interface WeakSet {
  subject: string
  file_path: string
  section_title: string
  wrong: number
  pending: number
  last_at: string | null
}

export interface WeakQuestion {
  subject: string
  file_path: string
  qid: string
  stem: string
  q_type: string
  times: number
  last_at: string | null
}

export interface WeakResponse {
  sets: WeakSet[]
  questions: WeakQuestion[]
}

export interface ErrorTypeStat {
  error_type: string
  auto: number
  self: number
  total: number
}

export interface ErrorTypesResponse {
  types: ErrorTypeStat[]
  confused: number
}

// ---- P6 资料库 / 政策资讯 ----

export interface MdBlock {
  type: 'table' | 'list' | 'p' | 'code'
  header?: string[]
  rows?: string[][]
  ordered?: boolean
  items?: { text: string; checked: boolean | null }[]
  text?: string
}

export interface OutlineNode {
  level: number
  title: string
  blocks: MdBlock[]
}

export interface PolicyDoc {
  name: string
  path: string
  status: string
  category: string
  title: string
}

export interface PolicyDocDetail {
  path: string
  title: string
  meta: Record<string, string>
  outline: OutlineNode[]
}

export interface KeyDate {
  item: string
  time: string
  confirmed: string
}

export interface School {
  school: string
  level: string
  link: string
  checked: string
  following: string
}

export interface KnowledgeUnit {
  subject: string
  unit: string
  path: string
  has_qbank: boolean
  has_analysis: boolean
  has_catalog: boolean
  mastery: Record<string, number>
}

export interface KnowledgeUnitDetail {
  path: string
  title: string
  meta: Record<string, string>
  outline: OutlineNode[]
  qbank: { total: number; by_type: Record<string, number> } | null
  mastery: Record<string, number>
}

export interface Deck {
  name: string
  txt_path: string
  cards: number
  levels: string[]
  has_apkg: boolean
  apkg_size: number
  stale: boolean
  txt_mtime: number
  apkg_mtime: number | null
}
