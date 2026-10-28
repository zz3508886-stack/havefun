// 轻量 API 客户端：封装 /api/quiz/* 的请求与错误抛出

import type {
  QuizSet,
  SetResponse,
  SubmitResponse,
  WrongItem,
  FeedbackRequest,
  ReviewRequest,
  WrongPaperResponse,
  WrongPaperItem,
  PlanNode,
  CheckinRequest,
  CheckinResponse,
  PlanCheckin,
  StatsOverview,
  TrendResponse,
  SubjectStat,
  WeakResponse,
  ErrorTypesResponse,
  PolicyDoc,
  PolicyDocDetail,
  KeyDate,
  School,
  KnowledgeUnit,
  KnowledgeUnitDetail,
  Deck,
} from './types'

async function getJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`GET ${url} → ${resp.status}`)
  return (await resp.json()) as T
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`POST ${url} → ${resp.status} ${detail}`)
  }
  return (await resp.json()) as T
}

export const api = {
  sets: () => getJSON<QuizSet[]>('/api/quiz/sets'),
  set: (filePath: string, sectionTitle: string) =>
    getJSON<SetResponse>(
      `/api/quiz/set?file_path=${encodeURIComponent(filePath)}&section_title=${encodeURIComponent(sectionTitle)}`,
    ),
  submit: (filePath: string, sectionTitle: string, answers: Record<string, string>) =>
    postJSON<SubmitResponse>('/api/quiz/submit', {
      file_path: filePath,
      section_title: sectionTitle,
      answers,
    }),
  feedback: (req: FeedbackRequest) => postJSON<{ id: number; ynd_appended: boolean }>('/api/quiz/feedback', req),
  review: (req: ReviewRequest) =>
    postJSON<{ ok: boolean; qid: string; is_correct: boolean; updated: number }>('/api/quiz/review', req),
  wrongPaper: (by: string, value: string) =>
    getJSON<WrongPaperResponse>(
      `/api/quiz/wrong-paper?by=${encodeURIComponent(by)}&value=${encodeURIComponent(value)}`,
    ),
  submitWrong: (items: WrongPaperItem[], answers: Record<string, string>) =>
    postJSON<SubmitResponse>('/api/quiz/submit-wrong', { items, answers }),
  wrong: () => getJSON<WrongItem[]>('/api/quiz/wrong'),
  planNodes: () => getJSON<PlanNode[]>('/api/plan/nodes'),
  planCheckin: (req: CheckinRequest) => postJSON<CheckinResponse>('/api/plan/checkin', req),
  planCheckins: () => getJSON<PlanCheckin[]>('/api/plan/checkins'),
  statsOverview: () => getJSON<StatsOverview>('/api/stats/overview'),
  statsTrend: (days = 30) => getJSON<TrendResponse>(`/api/stats/trend?days=${days}`),
  statsSubjects: () => getJSON<SubjectStat[]>('/api/stats/subjects'),
  statsWeak: (limit = 10) => getJSON<WeakResponse>(`/api/stats/weak?limit=${limit}`),
  statsErrorTypes: () => getJSON<ErrorTypesResponse>('/api/stats/error-types'),
  policyDocs: () => getJSON<PolicyDoc[]>('/api/policy/docs'),
  policyDoc: (path: string) =>
    getJSON<PolicyDocDetail>(`/api/policy/doc?path=${encodeURIComponent(path)}`),
  policyKeyDates: () => getJSON<KeyDate[]>('/api/policy/key-dates'),
  policySchools: () => getJSON<School[]>('/api/policy/schools'),
  kbUnits: () => getJSON<KnowledgeUnit[]>('/api/knowledge/units'),
  kbUnit: (path: string) =>
    getJSON<KnowledgeUnitDetail>(`/api/knowledge/unit?path=${encodeURIComponent(path)}`),
  kbDecks: () => getJSON<Deck[]>('/api/knowledge/decks'),
}
