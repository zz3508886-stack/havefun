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
