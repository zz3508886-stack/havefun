import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Input,
  Radio,
  Space,
  Spin,
  Typography,
} from 'antd'
import { api } from './api'
import type { Question, QuizSet, SetResponse, SubmitResponse } from './types'

const { Paragraph, Text } = Typography

function AnswerInput({
  q,
  value,
  onChange,
}: {
  q: Question
  value?: string
  onChange: (v: string) => void
}) {
  if (q.q_type === '判断题') {
    return (
      <Radio.Group
        value={value}
        onChange={(e) => onChange(e.target.value)}
        optionType="button"
        buttonStyle="solid"
      >
        <Radio.Button value="正确">正确</Radio.Button>
        <Radio.Button value="错误">错误</Radio.Button>
      </Radio.Group>
    )
  }
  // 单选形态：带标准选项（≥2 个）即按单选渲染，不挑题型名
  //（选择题 / 单项选择 / 字音·多音字 等摸底卷细分题型一视同仁）
  if ((q.options || []).length >= 2) {
    const opts = (q.options || []).map((o: any) => {
      const label = typeof o === 'string' ? o : o?.label
      const text = typeof o === 'string' ? '' : o?.text ?? ''
      return {
        label: text ? `${label}. ${text}` : label,
        value: String(label).toUpperCase(),
      }
    })
    return (
      <Radio.Group
        value={value}
        onChange={(e) => onChange(e.target.value)}
        optionType="button"
        buttonStyle="solid"
      >
        {opts.map((o) => (
          <Radio.Button key={o.value} value={o.value}>
            {o.label}
          </Radio.Button>
        ))}
      </Radio.Group>
    )
  }
  if (q.q_type === '解答题') {
    return (
      <Input.TextArea
        rows={3}
        value={value}
        placeholder="写下你的解答…"
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  // 填空题等
  return (
    <Input
      value={value}
      placeholder="填写答案…"
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

export default function QuizView({
  quizSet,
  onSubmitted,
  onBack,
  questions: questionsProp,
  submit: submitProp,
}: {
  quizSet: QuizSet
  onSubmitted: (resp: SubmitResponse) => void
  onBack: () => void
  questions?: Question[]
  submit?: (answers: Record<string, string>) => Promise<SubmitResponse>
}) {
  const [data, setData] = useState<SetResponse | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(questionsProp ? false : true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (questionsProp) {
      setData({
        file_path: quizSet.file_path,
        section_title: quizSet.section_title,
        questions: questionsProp,
      })
      setLoading(false)
      return
    }
    let alive = true
    setLoading(true)
    api
      .set(quizSet.file_path, quizSet.section_title)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [quizSet, questionsProp])

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const resp = submitProp
        ? await submitProp(answers)
        : await api.submit(quizSet.file_path, quizSet.section_title, answers)
      onSubmitted(resp)
    } catch (e) {
      setError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <Spin style={{ margin: 24 }} />
  if (error) return <Alert type="error" message={error} />

  return (
    <div style={{ maxWidth: 860, margin: '0 auto' }}>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={onBack}>← 返回套题列表</Button>
        <Text type="secondary">
          {quizSet.section_title}（共 {data?.questions.length ?? 0} 题）
        </Text>
      </Space>
      {data?.questions.map((q, i) => (
        <Card key={q.qid} style={{ marginBottom: 12 }} size="small">
          <Paragraph strong>
            {i + 1}. [{q.q_type}] {q.stem}
            {q.difficulty ? <Text type="secondary"> {q.difficulty}</Text> : null}
          </Paragraph>
          <AnswerInput
            q={q}
            value={answers[q.qid]}
            onChange={(v) => setAnswers((p) => ({ ...p, [q.qid]: v }))}
          />
        </Card>
      ))}
      <Button type="primary" block loading={submitting} onClick={submit}>
        交卷判分
      </Button>
      {error ? <Alert style={{ marginTop: 12 }} type="error" message={error} /> : null}
    </div>
  )
}
