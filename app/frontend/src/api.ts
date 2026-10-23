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
}
