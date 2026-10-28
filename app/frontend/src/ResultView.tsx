import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd'
import { api } from './api'
import { ERROR_TYPES } from './types'
import type { QuizSet, ResultItem, ReviewRequest, SubmitResponse } from './types'

const { Paragraph, Text } = Typography

function StatusTag({ r }: { r: ResultItem }) {
  if (r.is_correct === true) return <Tag color="success">正确</Tag>
  if (r.is_correct === false)
    return (
      <Tag color="error">
        错误{typeof r.correct_answer === 'string' ? ` · 正确答案 ${r.correct_answer}` : ''}
      </Tag>
    )
  return r.eval_state === 'pending_manual' ? (
    <Tag color="warning">待人工复核</Tag>
  ) : (
    <Tag color="processing">评判中</Tag>
  )
}

function FeedbackRow({
  quizSet,
  r,
}: {
  quizSet: QuizSet
  r: ResultItem
}) {
  const [errorType, setErrorType] = useState<string | undefined>(undefined)
  const [confused, setConfused] = useState(false)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)

  if (r.is_correct === true) return null // 正确的题无需错因反馈

  const send = async () => {
    setLoading(true)
    try {
      await api.feedback({
        file_path: r.file_path ?? quizSet.file_path,
        section_title: r.section_title ?? quizSet.section_title,
        qid: r.qid,
        error_type: errorType ?? null,
        confused,
      })
      setDone(true)
      message.success(confused ? '已记录，并累加至疑难点' : '已记录反馈')
    } catch (e) {
      message.error(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space wrap style={{ marginTop: 8 }}>
      <Text type="secondary">错因：</Text>
      <Select
        allowClear
        placeholder="选错因（可选）"
        style={{ width: 150 }}
        value={errorType}
        onChange={setErrorType}
        options={ERROR_TYPES.map((t) => ({ label: t, value: t }))}
      />
      <Text type="secondary">解析没看懂：</Text>
      <Switch checked={confused} onChange={setConfused} />
      <Button size="small" type="link" loading={loading} onClick={send} disabled={done}>
        {done ? '已反馈' : '提交反馈'}
      </Button>
    </Space>
  )
}

export default function ResultView({
  quizSet,
  resp,
  onBack,
}: {
  quizSet: QuizSet
  resp: SubmitResponse
  onBack: () => void
}) {
  const [results, setResults] = useState<ResultItem[]>(resp.results)
  const { writeback, warning } = resp
  const summary = useMemo(() => {
    const total = results.length
    const correct = results.filter((r) => r.is_correct === true).length
    const pending = results.filter((r) => r.is_correct === null).length
    return { total, correct, wrong: total - correct - pending, pending }
  }, [results])

  const handleReview = async (keyVal: string, file_path: string, isCorrect: boolean) => {
    try {
      const req: ReviewRequest = {
        batch_id: resp.batch_id,
        file_path,
        qid: keyVal.includes('#') ? keyVal.split('#').slice(1).join('#') : keyVal,
        is_correct: isCorrect,
      }
      await api.review(req)
      setResults((prev) =>
        prev.map((r) =>
          (r.key ?? r.qid) === keyVal
            ? { ...r, is_correct: isCorrect, eval_state: 'done' }
            : r,
        ),
      )
      message.success(isCorrect ? '已判为正确' : '已判为错误')
    } catch (e) {
      message.error(String(e))
    }
  }
  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={onBack}>← 返回套题列表</Button>
        <Tag color="blue">
          得分 {summary.correct}/{summary.total}
        </Tag>
        <Tag>正确 {summary.correct}</Tag>
        <Tag color="error">错误 {summary.wrong}</Tag>
        <Tag color="warning">待复核 {summary.pending}</Tag>
        {writeback === 'written' ? (
          <Tag color="green">已回写题库</Tag>
        ) : writeback === 'conflict' ? (
          <Tag color="orange">回写冲突（判分已存）</Tag>
        ) : (
          <Tag color="red">回写未通过校验</Tag>
        )}
      </Space>

      {warning ? (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={warning} />
      ) : null}

      {results.map((r, i) => {
        const correctLetter = (r.correct_answer || '').toUpperCase()
        const yourLetter = (r.student || '').toUpperCase()
        return (
          <Card key={r.key ?? r.qid} style={{ marginBottom: 12 }} size="small">
            <Paragraph strong style={{ whiteSpace: 'pre-wrap' }}>
              {i + 1}. [{r.q_type}]
              {r.difficulty ? ` ${r.difficulty} ` : ' '}
              {r.stem}
            </Paragraph>

            {/* 单选形态：列出选项并标注「你选的」「正确的」（不挑题型名） */}
            {r.options?.length ? (
              <div style={{ margin: '8px 0' }}>
                {r.options.map((o) => {
                  const letter = (o.label || '').toUpperCase()
                  const isCorrect = letter === correctLetter
                  const isChosen = letter === yourLetter
                  const bg = isCorrect
                    ? '#f6ffed'
                    : isChosen
                    ? '#fff1f0'
                    : 'transparent'
                  return (
                    <div
                      key={o.label}
                      style={{
                        padding: '4px 8px',
                        borderRadius: 4,
                        background: bg,
                        marginBottom: 4,
                      }}
                    >
                      {o.label}. {o.text}
                      {isCorrect ? '  ✓正确' : ''}
                      {isChosen && !isCorrect ? '  ✗你选' : ''}
                    </div>
                  )
                })}
              </div>
            ) : null}

            <Space wrap>
              <StatusTag r={r} />
              <Text type="secondary">你的作答：{r.student || '（未作答）'}</Text>
              {r.correct_answer ? (
                <Text type="success">正确答案 {r.correct_answer}</Text>
              ) : null}
              {r.error_type ? <Tag>{r.error_type}</Tag> : null}
            </Space>

            {r.explanation ? (
              <Alert
                style={{ marginTop: 8 }}
                type="info"
                showIcon
                message="解析"
                description={
                  <span style={{ whiteSpace: 'pre-wrap' }}>{r.explanation}</span>
                }
              />
            ) : null}

            {r.is_correct === null && r.eval_state === 'pending_manual' ? (
              <Space wrap style={{ marginTop: 8 }}>
                <Text type="secondary">人工复核：</Text>
                <Button
                  size="small"
                  type="primary"
                  onClick={() => handleReview(r.key ?? r.qid, r.file_path ?? quizSet.file_path, true)}
                >
                  判对
                </Button>
                <Button
                  size="small"
                  danger
                  onClick={() => handleReview(r.key ?? r.qid, r.file_path ?? quizSet.file_path, false)}
                >
                  判错
                </Button>
              </Space>
            ) : null}

            <FeedbackRow quizSet={quizSet} r={r} />
          </Card>
        )
      })}
    </div>
  )
}
