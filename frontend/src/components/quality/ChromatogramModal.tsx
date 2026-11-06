'use client'

import { useState } from 'react'
import { App, Button, DatePicker, Input, InputNumber, Modal, Select, Space, Spin, Table, Typography, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchLcTemplateConfigs, parseChromatogram, submitCalcFill } from '@/actions/quality'
import type { ChromatogramPeak, LcTemplateConfig } from '@/types/quality'

interface Props {
  open: boolean
  taskId: string
  title?: string
  onClose: () => void
  onFilled: () => void
}

/** 图谱解析：上传截图/PDF → MinerU 解析峰表预览（峰名/面积可改）→ 确认后走计算表填入链路。 */
export default function ChromatogramModal({ open, taskId, title, onClose, onFilled }: Props) {
  const { message } = App.useApp()
  const [parsing, setParsing] = useState(false)
  const [peaks, setPeaks] = useState<ChromatogramPeak[]>([])
  const [configs, setConfigs] = useState<LcTemplateConfig[]>([])
  const [tableNo, setTableNo] = useState<string | undefined>()
  const [recordDate, setRecordDate] = useState<Dayjs>(dayjs())
  const [submitting, setSubmitting] = useState(false)

  const onUpload = async (file: File) => {
    setParsing(true)
    setPeaks([])
    try {
      const res = await parseChromatogram(file)
      setPeaks(res.data.peaks.map((p) => ({ ...p })))
      if (!configs.length) {
        const cfg = await fetchLcTemplateConfigs()
        setConfigs(cfg.data)
      }
      if (!res.data.peaks.length) {
        message.warning('未识别到峰表，请确认截图内容为色谱图谱（峰名+面积），或换更清晰的图')
      }
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '图谱解析失败')
    } finally {
      setParsing(false)
    }
    return false // 阻止 antd 默认上传行为
  }

  const updatePeak = (index: number, patch: Partial<ChromatogramPeak>) => {
    setPeaks((prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  const removePeak = (index: number) => {
    setPeaks((prev) => prev.filter((_, i) => i !== index))
  }

  const onConfirm = async () => {
    const values = peaks
      .filter((p) => p.name.trim() && p.area !== null && p.area !== undefined)
      .map((p) => ({ item_name: p.name.trim(), value: p.area as number }))
    if (!values.length) {
      message.warning('没有可填入的峰数据，请先解析或检查数值')
      return
    }
    setSubmitting(true)
    try {
      const res = await submitCalcFill(taskId, {
        table_no: tableNo,
        record_date: recordDate.format('YYYY-MM-DD'),
        values,
      })
      if (res.data.unmatched.length) {
        message.warning(`已填入 ${res.data.filled.length} 项；未匹配：${res.data.unmatched.join('、')}（可在峰名里改成任务项目名后重试）`)
      } else {
        message.success(`已填入 ${res.data.filled.length} 项`)
      }
      onFilled()
      onClose()
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '填入失败')
    } finally {
      setSubmitting(false)
    }
  }

  const columns: TableColumnsType<ChromatogramPeak> = [
    {
      title: '峰名（可改，需匹配任务项目名）', dataIndex: 'name', width: 260,
      render: (v: string, _, index) => (
        <Input value={v} onChange={(e) => updatePeak(index, { name: e.target.value })} maxLength={64} />
      ),
    },
    {
      title: '面积（保留两位）', dataIndex: 'area', width: 150,
      render: (v: number | null, _, index) => (
        <InputNumber
          value={v} precision={2} style={{ width: '100%' }}
          onChange={(nv) => updatePeak(index, { area: nv === null ? null : Number(nv) })}
        />
      ),
    },
    {
      title: '操作', key: 'actions', width: 70,
      render: (_: unknown, __: ChromatogramPeak, index: number) => (
        <Button size="small" type="link" danger onClick={() => removePeak(index)}>删除</Button>
      ),
    },
  ]

  return (
    <Modal
      title={title || '图谱解析填计算表'}
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnClose
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          <Button type="primary" loading={submitting} disabled={!peaks.length} onClick={onConfirm}>
            确认填入
          </Button>
        </Space>
      }
    >
      <Upload.Dragger
        accept=".jpg,.jpeg,.png,.webp,.bmp,.pdf"
        showUploadList={false}
        beforeUpload={onUpload}
        disabled={parsing}
        style={{ marginBottom: 12 }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽图谱截图/PDF 到此区域</p>
        <p className="ant-upload-hint">解析结果仅为预填草稿，确认后才会按判定填入任务</p>
      </Upload.Dragger>

      {parsing && (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin tip="正在解析图谱（约 10-60 秒）…" />
        </div>
      )}

      {!parsing && peaks.length > 0 && (
        <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Select
              allowClear placeholder="计算表表号（可选，用于合并规则）" style={{ width: 280 }}
              value={tableNo}
              onChange={(v) => setTableNo(v)}
              options={configs.map((c) => ({ value: c.table_no, label: c.table_no }))}
              showSearch optionFilterProp="label"
            />
            <DatePicker value={recordDate} allowClear={false} onChange={(v) => v && setRecordDate(v)} />
            <Typography.Text type="secondary">共 {peaks.length} 个峰</Typography.Text>
          </Space>
          <Table
            rowKey={(_, index) => String(index)}
            size="small"
            dataSource={peaks}
            columns={columns}
            pagination={false}
            scroll={{ y: 320 }}
          />
        </>
      )}
    </Modal>
  )
}
