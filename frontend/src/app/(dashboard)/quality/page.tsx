'use client'

import { Suspense, useState } from 'react'
import { usePermission } from '@/hooks/usePermission'
import { Typography, Divider, Empty, Button, Space, Table, Tag, Modal, InputNumber, App, Tabs, Skeleton } from 'antd'
import { ExperimentOutlined, FileTextOutlined, HistoryOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { LcUploader, LcReportView, LcHistoryList } from '@/components/quality'
import { confirmTaskResult } from '@/actions/quality'
import type { UploadLcResponse } from '@/types/quality'

const { Title, Paragraph } = Typography

interface ConfirmItem {
  result_id: string
  item_name: string
  result_value: number | null
  is_pass: boolean | null
  draft: number | null
  done: boolean
}

export default function QualityPage() {
  const { hasPermission } = usePermission()
  const canUpload = hasPermission('quality:lc:upload')
  const [result, setResult] = useState<UploadLcResponse | null>(null)
  const [confirmItems, setConfirmItems] = useState<ConfirmItem[]>([])
  const [confirming, setConfirming] = useState(false)
  const [activeTab, setActiveTab] = useState('parse')
  const { message } = App.useApp()
  const router = useRouter()

  const onUploadResult = (r: UploadLcResponse) => {
    setResult(r)
    const items = r.task_link?.items
    if (items && items.length) {
      setConfirmItems(items.map((it) => ({
        result_id: it.result_id, item_name: it.item_name,
        result_value: it.result_value, is_pass: it.is_pass,
        draft: it.result_value, done: false,
      })))
    } else {
      setConfirmItems([])
    }
  }

  const doConfirm = async (item: ConfirmItem) => {
    if (!result?.task_link?.task_id) return
    await confirmTaskResult(result.task_link.task_id, item.result_id, item.draft ?? undefined)
    setConfirmItems((prev) => prev.map((x) => (x.result_id === item.result_id ? { ...x, done: true } : x)))
  }

  const confirmAllAndEnter = async () => {
    if (!result?.task_link?.task_id) return
    setConfirming(true)
    try {
      for (const it of confirmItems) {
        if (!it.done) await doConfirm(it)
      }
      message.success('已全部确认归入')
      setConfirmItems([])
      router.push(`/quality/task/${result.task_link.task_id}`)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '归入失败')
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div>
      <Modal
        title="逐项确认归入检验填报"
        open={confirmItems.length > 0}
        onCancel={() => { setConfirmItems([]); if (result?.task_link?.task_id) router.push(`/quality/task/${result.task_link.task_id}`) }}
        footer={[
          <Button key="later" onClick={() => { setConfirmItems([]); if (result?.task_link?.task_id) router.push(`/quality/task/${result.task_link.task_id}`) }}>
            稍后到任务里确认
          </Button>,
          <Button key="ok" type="primary" loading={confirming} onClick={confirmAllAndEnter}
            disabled={confirmItems.every((x) => x.done)}>
            全部归入并进入任务
          </Button>,
        ]}
      >
        <Paragraph type="secondary">
          解析值已暂存任务（待确认）。可逐项修正数值后确认归入（按标准限度重新判定），或全部归入后进入任务继续填报。
        </Paragraph>
        <Table
          size="small"
          rowKey="result_id"
          pagination={false}
          dataSource={confirmItems}
          columns={[
            { title: '项目', dataIndex: 'item_name', key: 'item_name', width: 180 },
            {
              title: '数值（可改）', key: 'value', width: 150,
              render: (_: unknown, it: ConfirmItem) => (
                <InputNumber size="small" precision={2} value={it.draft}
                  onChange={(v) => setConfirmItems((prev) => prev.map((x) => (x.result_id === it.result_id ? { ...x, draft: v === null ? null : Number(v) } : x)))}
                  style={{ width: '100%' }} />
              ),
            },
            {
              title: '解析判定', key: 'judge', width: 90,
              render: (_: unknown, it: ConfirmItem) => it.is_pass === null ? <Tag>未判定</Tag>
                : it.is_pass ? <Tag color="success">合格</Tag> : <Tag color="error">不合格</Tag>,
            },
            {
              title: '操作', key: 'actions', width: 100,
              render: (_: unknown, it: ConfirmItem) => it.done
                ? <Tag color="green">已归入</Tag>
                : (
                  <Button size="small" type="primary"
                    onClick={async () => {
                      try { await doConfirm(it); message.success('已归入') }
                      catch (err: unknown) { message.error((err instanceof Error ? err.message : String(err)) || '确认失败') }
                    }}>
                    确认归入
                  </Button>
                ),
            },
          ]}
        />
      </Modal>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'parse',
            label: '液相解析',
            children: (
              <>
      <Title level={3} style={{ marginBottom: 4 }}>
        <ExperimentOutlined /> 液相计算表解析
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        上传液相计算表 Excel，自动解析峰面积、计算结果和质量标准，执行合格/超趋势判定。
      </Paragraph>

      {canUpload ? (
        <LcUploader onResult={onUploadResult} />
      ) : (
        <Paragraph type="secondary">没有上传液相计算表的权限</Paragraph>
      )}

      {result && result.record_id && result.task_link?.task_id && (
        <Space style={{ marginTop: 12 }}>
          <Link href={`/quality/task/${result.task_link.task_id}`}>
            <Button type="primary" icon={<FileTextOutlined />}>
              去任务确认归入（已自动填入待确认）
            </Button>
          </Link>
          <Button icon={<HistoryOutlined />} onClick={() => setActiveTab('history')}>历史记录</Button>
        </Space>
      )}
      {result && result.record_id && !result.task_link?.task_id && (
        <Space style={{ marginTop: 12 }}>
          <Link href="/quality/task">
            <Button type="primary" icon={<FileTextOutlined />}>
              去检验填报建任务归入
            </Button>
          </Link>
          <Button icon={<HistoryOutlined />} onClick={() => setActiveTab('history')}>历史记录</Button>
        </Space>
      )}
      {result && result.record_id && !result.task_link?.task_id && (
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          未找到同批号任务：建任务后重新上传计算表（或在任务详情上传）即可自动归入；报告单在任务填报完成并复核通过后生成。
        </Paragraph>
      )}

      {result && (
        <>
          <Divider />
          {result.components ? (
            <div>
              <Paragraph strong>解析组分结果（模板配置驱动）</Paragraph>
              <Table
                rowKey="name"
                size="small"
                pagination={false}
                dataSource={(result.components || []).map((c) => ({ ...c, key: c.name }))}
                columns={[
                  { title: '组分', dataIndex: 'name', key: 'name' },
                  {
                    title: '报告值', dataIndex: 'report_value', key: 'report_value',
                    render: (v: number | null) => v != null ? `${v}%` : <Tag color="orange">未检出/未填</Tag>,
                  },
                ]}
              />
            </div>
          ) : (
            <LcReportView report={result.report} />
          )}
        </>
      )}

      {!result && (
        <div style={{ marginTop: 48, textAlign: 'center' }}>
          <Empty description="请上传液相计算表 Excel 文件开始解析" />
        </div>
      )}
              </>
            ),
          },
          {
            key: 'history',
            label: '检验历史',
            children: (
              <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}>
                <LcHistoryList />
              </Suspense>
            ),
          },
        ]}
      />
    </div>
  )
}
