'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { CheckCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import type { BatchRelease, TestTaskListItem } from '@/types/quality'
import { fetchBatchReleases, createBatchRelease, releaseBatchRecord, fetchTestTasks } from '@/actions/quality'

const { Text } = Typography

/** 批放行记录：已完成检验任务发起放行（快照汇总）→ 专员放行留痕。 */
export default function BatchReleases() {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const canReview = hasPermission('quality:task:review')
  const [data, setData] = useState<BatchRelease[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [tasks, setTasks] = useState<TestTaskListItem[]>([])
  const [taskId, setTaskId] = useState<string | undefined>()
  const [createRemark, setCreateRemark] = useState('')
  const [detail, setDetail] = useState<BatchRelease | null>(null)
  const [releasing, setReleasing] = useState<string | null>(null)
  const [releaseRemark, setReleaseRemark] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchBatchReleases({ status: statusFilter })
      setData(res.data)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '获取放行记录失败')
    } finally {
      setLoading(false)
    }
  }, [message, statusFilter])

  useEffect(() => { (async () => { await load() })() }, [load])

  const openCreate = () => {
    setTaskId(undefined)
    setCreateRemark('')
    setCreateOpen(true)
    void fetchTestTasks(undefined, 'completed', 1).then((res) => setTasks(res.data)).catch(() => { /* 任务拉取失败 */ })
  }

  const onCreate = async () => {
    if (!taskId) {
      message.warning('请选择已完成检验任务')
      return
    }
    setCreating(true)
    try {
      const res = await createBatchRelease({ task_id: taskId, remark: createRemark || undefined })
      message.success(res.message)
      setCreateOpen(false)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '发起放行失败')
    } finally {
      setCreating(false)
    }
  }

  const onRelease = async (r: BatchRelease) => {
    setReleasing(r.id)
    try {
      const res = await releaseBatchRecord(r.id, { release_remark: releaseRemark || undefined })
      message.success(res.message)
      setReleaseRemark('')
      setDetail(null)
      load()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '放行失败')
    } finally {
      setReleasing(null)
    }
  }

  return (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          allowClear placeholder="状态" style={{ width: 110 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={[
            { value: 'pending', label: '待放行' },
            { value: 'released', label: '已放行' },
          ]}
        />
        {canReview && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>发起放行</Button>
        )}
      </Space>

      <Table
        rowKey="id" size="small" loading={loading} dataSource={data}
        scroll={{ x: 1000 }} pagination={{ pageSize: 20 }}
        columns={[
          { title: '批号', dataIndex: 'batch_no', width: 140, render: (v: string) => <Text code>{v}</Text> },
          { title: '产品', dataIndex: 'product_name', width: 170 },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (v: string) => (v === 'released' ? <Tag color="green">已放行</Tag> : <Tag color="orange">待放行</Tag>),
          },
          {
            title: '检验汇总', key: 'snapshot', width: 220,
            render: (_: unknown, r: BatchRelease) => r.snapshot ? (
              <Text style={{ fontSize: 12.5 }}>
                判定 {r.snapshot.filled}/{r.snapshot.total}
                {r.snapshot.all_pass === false && <Text type="danger">（有不合格）</Text>}
                ｜复核 {r.snapshot.reviewers.length} 人
                {r.snapshot.report_serials.length > 0 && <>｜报告单 {r.snapshot.report_serials.join('、')}</>}
              </Text>
            ) : '-',
          },
          {
            title: '放行信息', key: 'released', width: 170,
            render: (_: unknown, r: BatchRelease) => r.status === 'released'
              ? <Text style={{ fontSize: 12.5 }}>{r.released_at}｜{r.released_by_name ?? '-'}{r.release_remark ? `｜${r.release_remark}` : ''}</Text>
              : '-',
          },
          {
            title: '操作', key: 'actions', width: 130,
            render: (_: unknown, r: BatchRelease) => (
              <Space size="small">
                <Button size="small" type="link" onClick={() => { setDetail(r); setReleaseRemark('') }}>详情</Button>
                {canReview && r.status === 'pending' && (
                  <Button size="small" type="link" style={{ color: '#15803d' }} loading={releasing === r.id}
                    onClick={() => onRelease(r)}>放行</Button>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="发起批放行"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={onCreate}
        confirmLoading={creating}
        okText="创建放行记录"
        width={520}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          以已完成检验任务为基准生成放行记录，并快照当时的判定/复核/报告单/留样状态。
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="已完成检验任务" required>
            <Select
              showSearch optionFilterProp="label" placeholder="选择任务（产品+批号）"
              value={taskId} onChange={setTaskId}
              options={tasks.map((t) => ({ value: t.id, label: `${t.product_name}｜${t.batch_number}` }))}
            />
          </Form.Item>
          <Form.Item label="备注">
            <Input.TextArea rows={2} maxLength={200} value={createRemark}
              onChange={(e) => setCreateRemark(e.target.value)} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`放行记录 ${detail ? `${detail.batch_no}` : ''}`}
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={detail?.status === 'pending' && canReview ? (
          <Space>
            <Input placeholder="放行备注（可选）" value={releaseRemark} style={{ width: 260 }}
              onChange={(e) => setReleaseRemark(e.target.value)} />
            <Button type="primary" icon={<CheckCircleOutlined />} loading={releasing === detail.id}
              onClick={() => onRelease(detail)}>放行</Button>
          </Space>
        ) : null}
        width={560}
      >
        {detail?.snapshot && (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="产品 / 批号">{detail.product_name} / {detail.batch_no}</Descriptions.Item>
            <Descriptions.Item label="任务状态">{detail.snapshot.task_status}</Descriptions.Item>
            <Descriptions.Item label="判定">
              已判定 {detail.snapshot.filled}/{detail.snapshot.total}
              {detail.snapshot.all_pass === false && <Tag color="error" style={{ marginLeft: 8 }}>有不合格</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="复核人">{detail.snapshot.reviewers.length ? detail.snapshot.reviewers.join('、') : '-'}</Descriptions.Item>
            <Descriptions.Item label="报告单">{detail.snapshot.report_serials.length ? detail.snapshot.report_serials.join('、') : '-'}</Descriptions.Item>
            <Descriptions.Item label="留样">
              {detail.snapshot.retained
                ? `${detail.snapshot.retained.qty ?? '-'}｜${detail.snapshot.retained.location ?? '-'}｜销毁到期 ${detail.snapshot.retained.destroy_due_date ?? '-'}｜${detail.snapshot.retained.status === 'destroyed' ? '已销毁' : '在留'}`
                : '未登记留样'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </>
  )
}
