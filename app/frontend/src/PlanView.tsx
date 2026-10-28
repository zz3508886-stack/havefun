// P4 复习计划页：节点总表（文档状态 + 打卡推导状态）+ 节点打卡 + 最近打卡明细

import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { api } from './api'
import { PLAN_STATUSES, PLAN_STATUS_LABEL } from './types'
import type { PlanNode, PlanStatus, CheckinResponse, PlanCheckin } from './types'

const { Text } = Typography

function StatusTag({ status }: { status: PlanStatus }) {
  const color = status === '✅' ? 'success' : status === '🟨' ? 'warning' : 'default'
  return (
    <Tag color={color}>
      {status} {PLAN_STATUS_LABEL[status]}
    </Tag>
  )
}

export default function PlanView() {
  const [nodes, setNodes] = useState<PlanNode[]>([])
  const [checkins, setCheckins] = useState<PlanCheckin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 打卡表单
  const [nodeId, setNodeId] = useState<string | undefined>(undefined)
  const [status, setStatus] = useState<PlanStatus>('🟨')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(() => {
    setLoading(true)
    Promise.all([api.planNodes(), api.planCheckins()])
      .then(([ns, cs]) => {
        setNodes(ns)
        setCheckins(cs)
        setError(null)
        // 默认选中首个节点（已选则不覆盖）
        setNodeId((prev) => prev ?? (ns.length ? ns[0].node_id : undefined))
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(refresh, [refresh])

  const submit = async () => {
    if (!nodeId) {
      message.warning('先选择一个节点')
      return
    }
    setSubmitting(true)
    try {
      const resp: CheckinResponse = await api.planCheckin({
        node_id: nodeId,
        status,
        notes: notes.trim() || null,
      })
      if (resp.writeback === 'written' || resp.writeback === 'unchanged') {
        message.success(`已打卡：${nodeId} → ${PLAN_STATUS_LABEL[resp.status]}`)
        setNotes('')
      } else {
        // 冲突/过检失败：打卡明细已存，仅回写降级
        message.warning(`打卡已记录，但节点表回写${resp.writeback === 'conflict' ? '冲突' : '未通过校验'}（${resp.warning ?? ''}）`)
      }
      refresh()
    } catch (e) {
      message.error(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading && !nodes.length) return <Empty style={{ marginTop: 48 }} description="加载中…" />
  if (error)
    return (
      <Alert
        type="error"
        message="加载复习计划失败"
        description="请确认后端已启动（8000 端口）且仓库中存在 复习计划/节点安排.md。"
      />
    )

  const current = nodes.find((n) => n.node_id === nodeId)

  return (
    <div style={{ maxWidth: 960, margin: '0 auto' }}>
      <Card size="small" style={{ marginBottom: 12 }} title="节点打卡">
        <Space wrap align="center">
          <Text type="secondary">节点：</Text>
          <Segmented
            value={nodeId}
            onChange={(v) => setNodeId(v as string)}
            options={nodes.map((n) => ({ label: n.node_id, value: n.node_id }))}
          />
          <Text type="secondary">状态：</Text>
          <Segmented
            value={status}
            onChange={(v) => setStatus(v as PlanStatus)}
            options={PLAN_STATUSES.map((s) => ({
              label: `${s} ${PLAN_STATUS_LABEL[s]}`,
              value: s,
            }))}
          />
        </Space>
        <div style={{ marginTop: 8 }}>
          <Input.TextArea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="备注（可选）：今天对该节点做了什么、卡点是什么"
            autoSize={{ minRows: 1, maxRows: 4 }}
            allowClear
          />
        </div>
        <div style={{ marginTop: 8 }}>
          <Space>
            <Button type="primary" loading={submitting} onClick={submit}>
              提交打卡
            </Button>
            {current ? (
              <Text type="secondary">
                当前推导状态：{current.derived_status} {PLAN_STATUS_LABEL[current.derived_status]}（打卡{' '}
                {current.checkin_count} 次）
              </Text>
            ) : null}
          </Space>
        </div>
      </Card>

      <Table<PlanNode>
        size="small"
        style={{ marginBottom: 12 }}
        rowKey="node_id"
        dataSource={nodes}
        pagination={false}
        columns={[
          { title: '节点', dataIndex: 'node_id', width: 64 },
          { title: '名称', dataIndex: 'name' },
          { title: '起止日期', dataIndex: 'date_range', width: 220 },
          { title: '阶段', dataIndex: 'stage', width: 140 },
          {
            title: '文档状态',
            dataIndex: 'status',
            width: 120,
            render: (v: PlanStatus) => <StatusTag status={v} />,
          },
          {
            title: '推导状态',
            dataIndex: 'derived_status',
            width: 120,
            render: (v: PlanStatus) => <StatusTag status={v} />,
          },
          { title: '打卡次数', dataIndex: 'checkin_count', width: 88 },
        ]}
      />

      <Card size="small" title="最近打卡">
        {checkins.length ? (
          <Table<PlanCheckin>
            size="small"
            rowKey="id"
            dataSource={checkins.slice(0, 20)}
            pagination={false}
            columns={[
              { title: '时间', dataIndex: 'created_at', width: 180 },
              { title: '节点', dataIndex: 'node_id', width: 72 },
              {
                title: '状态',
                dataIndex: 'status',
                width: 120,
                render: (v: PlanStatus) => <StatusTag status={v} />,
              },
              { title: '备注', dataIndex: 'notes', render: (v: string | null) => v || '—' },
            ]}
          />
        ) : (
          <Empty description="还没有打卡记录" />
        )}
      </Card>
    </div>
  )
}
