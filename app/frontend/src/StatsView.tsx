// P5 学情仪表盘：总览卡片 + 每日趋势（ECharts）+ 学科掌握度 + 薄弱点榜单 + 错因分布
// 数字全部来自 /api/stats/*，与 stats 模块聚合一致（pytest 对齐）

import { useEffect, useState } from 'react'
import { Alert, Card, Col, Empty, Row, Statistic, Table, Tag } from 'antd'
import ReactECharts from 'echarts-for-react'
import { api } from './api'
import type {
  StatsOverview,
  TrendResponse,
  SubjectStat,
  WeakResponse,
  ErrorTypesResponse,
} from './types'

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

function TrendChart({ trend }: { trend: TrendResponse }) {
  const dates = trend.series.map((s) => s.date.slice(5)) // MM-DD
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['答对', '答错', '待复核', '正确率'] },
    grid: { left: 48, right: 48, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: '题数', minInterval: 1 },
      { type: 'value', name: '正确率', min: 0, max: 1, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%` } },
    ],
    series: [
      { name: '答对', type: 'bar', stack: 'q', data: trend.series.map((s) => s.correct), itemStyle: { color: '#52c41a' } },
      { name: '答错', type: 'bar', stack: 'q', data: trend.series.map((s) => s.wrong), itemStyle: { color: '#ff4d4f' } },
      { name: '待复核', type: 'bar', stack: 'q', data: trend.series.map((s) => s.pending), itemStyle: { color: '#faad14' } },
      {
        name: '正确率',
        type: 'line',
        yAxisIndex: 1,
        data: trend.series.map((s) => s.accuracy),
        smooth: true,
        itemStyle: { color: '#1677ff' },
      },
    ],
  }
  return <ReactECharts option={option} style={{ height: 300 }} notMerge />
}

function ErrorTypeChart({ data }: { data: ErrorTypesResponse }) {
  const option = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        name: '错因分布',
        type: 'pie',
        radius: ['40%', '70%'],
        data: data.types
          .filter((t) => t.total > 0)
          .map((t) => ({ name: t.error_type, value: t.total })),
      },
    ],
  }
  if (!data.types.some((t) => t.total > 0)) {
    return <Empty style={{ padding: 24 }} description="暂无错因数据" />
  }
  return <ReactECharts option={option} style={{ height: 280 }} notMerge />
}

export default function StatsView() {
  const [overview, setOverview] = useState<StatsOverview | null>(null)
  const [trend, setTrend] = useState<TrendResponse | null>(null)
  const [subjects, setSubjects] = useState<SubjectStat[]>([])
  const [weak, setWeak] = useState<WeakResponse>({ sets: [], questions: [] })
  const [errors, setErrors] = useState<ErrorTypesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      api.statsOverview(),
      api.statsTrend(30),
      api.statsSubjects(),
      api.statsWeak(10),
      api.statsErrorTypes(),
    ])
      .then(([ov, tr, sub, wk, er]) => {
        setOverview(ov)
        setTrend(tr)
        setSubjects(sub)
        setWeak(wk)
        setErrors(er)
      })
      .catch((e) => setError(String(e)))
  }, [])

  if (error)
    return <Alert type="error" message="加载学情数据失败" description="请确认后端已启动（8000 端口）。" />
  if (!overview || !trend || !errors) return <Empty style={{ marginTop: 48 }} description="加载中…" />

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto' }}>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="累计答题" value={overview.quiz.total} suffix="题" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="正确率（已判）"
              value={overview.quiz.accuracy}
              formatter={(v) => pct(Number(v))}
            />
            <div style={{ fontSize: 12, color: '#999' }}>
              对 {overview.quiz.correct} / 错 {overview.quiz.wrong} / 待复核 {overview.quiz.pending}
            </div>
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="涉及套题/题目" value={`${overview.quiz.batches} 卷 · ${overview.quiz.questions} 题`} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="打卡天数" value={overview.plan.checkin_days} suffix="天" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="连续打卡" value={overview.plan.streak_days} suffix="天" />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="解析没看懂" value={overview.feedback.confused} suffix="次" />
          </Card>
        </Col>
      </Row>

      <Card size="small" title={`每日趋势（近 ${trend.days} 天）`} style={{ marginBottom: 12 }}>
        <TrendChart trend={trend} />
      </Card>

      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col span={14}>
          <Card size="small" title="薄弱套题榜（错题数降序）">
            {weak.sets.length ? (
              <Table
                size="small"
                rowKey={(r) => `${r.file_path}#${r.section_title}`}
                dataSource={weak.sets}
                pagination={false}
                columns={[
                  { title: '学科', dataIndex: 'subject', width: 90 },
                  { title: '套题', dataIndex: 'section_title' },
                  { title: '错题', dataIndex: 'wrong', width: 64 },
                  { title: '待复核', dataIndex: 'pending', width: 80 },
                ]}
              />
            ) : (
              <Empty description="暂无薄弱套题" />
            )}
          </Card>
        </Col>
        <Col span={10}>
          <Card size="small" title="错因分布（R18 五类）">
            <ErrorTypeChart data={errors} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col span={12}>
          <Card size="small" title="学科掌握度">
            {subjects.length ? (
              <Table
                size="small"
                rowKey="subject"
                dataSource={subjects}
                pagination={false}
                columns={[
                  { title: '学科', dataIndex: 'subject' },
                  { title: '已判', dataIndex: 'judged', width: 64 },
                  { title: '错题', dataIndex: 'wrong', width: 64 },
                  {
                    title: '正确率',
                    dataIndex: 'accuracy',
                    width: 96,
                    render: (v: number) => pct(v),
                  },
                ]}
              />
            ) : (
              <Empty description="暂无做题数据" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="重复错题榜（出现次数）">
            {weak.questions.length ? (
              <Table
                size="small"
                rowKey={(r) => `${r.file_path}#${r.qid}`}
                dataSource={weak.questions}
                pagination={false}
                columns={[
                  {
                    title: '题目',
                    dataIndex: 'stem',
                    ellipsis: true,
                    render: (v: string, r) => `${r.qid} ${r.q_type ? `[${r.q_type}] ` : ''}${v || ''}`,
                  },
                  { title: '次数', dataIndex: 'times', width: 64 },
                ]}
              />
            ) : (
              <Empty description="暂无错题" />
            )}
          </Card>
        </Col>
      </Row>

      {overview.plan.last_checkin_at ? (
        <div style={{ marginTop: 12, fontSize: 12, color: '#999' }}>
          最近打卡：{overview.plan.last_checkin_at.slice(0, 19)} ·{' '}
          {overview.plan.last_node ? <Tag>{overview.plan.last_node}</Tag> : null}
          {overview.plan.last_status ?? ''}
        </div>
      ) : null}
    </div>
  )
}
