'use client'

import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, DatePicker, Input, InputNumber, Modal, Select, Space, Spin, Table, Tag, Typography, Upload } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchLcTemplateConfigs, parseChromatogram, submitCalcFill } from '@/actions/quality'
import { mapPeaksToInputs } from '@/lib/quality/peak-mapping'
import type { ChromatogramPeak, LcTemplateConfig } from '@/types/quality'

interface Props {
  open: boolean
  taskId: string
  title?: string
  onClose: () => void
  onFilled: () => void
  /** 预填在线计算表：把映射好的引擎 inputs + 确认后的峰表快照灌进任务页计算表弹窗，
   * 检验员核对实时 % 后提交（峰表随提交落库，供审核机审做峰面积比对） */
  onPrefill?: (inputs: Record<string, number>, tableNo: string, peaks: ChromatogramPeak[]) => void
}

type Slot = 1 | 2

/**
 * 图谱解析填计算表：上传截图/PDF（一图一针，双份各传一张）→ MinerU 解析峰表预览
 * （峰名/面积可改，保留时间只读核对）→ 按表号 calc 配置映射为引擎 inputs →
 * 「预填计算表」交给任务页在线计算表核对提交；无计算配置的表号保留直填结果值路径。
 */
export default function ChromatogramModal({ open, taskId, title, onClose, onFilled, onPrefill }: Props) {
  const { message } = App.useApp()
  const [parsingSlot, setParsingSlot] = useState<Slot | null>(null)
  const [peaks1, setPeaks1] = useState<ChromatogramPeak[]>([])
  const [peaks2, setPeaks2] = useState<ChromatogramPeak[]>([])
  const [configs, setConfigs] = useState<LcTemplateConfig[]>([])
  const [tableNo, setTableNo] = useState<string | undefined>()
  const [recordDate, setRecordDate] = useState<Dayjs>(dayjs())
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open && !configs.length) {
      fetchLcTemplateConfigs()
        .then((res) => setConfigs(res.data))
        .catch(() => { /* 表号拉取失败仍可直填 */ })
    }
  }, [open, configs.length])

  const activeCalcCfg = configs.find((c) => c.table_no === tableNo)?.config.calc
  const isNorm = activeCalcCfg?.mode === 'normalization'

  // 映射预览：仅归一化配置 + 已解析第一份时计算（纯函数，峰名改动即时重映射）
  const mapping = useMemo(() => {
    if (!isNorm || !activeCalcCfg || !peaks1.length) return null
    return mapPeaksToInputs(activeCalcCfg, peaks1, peaks2.length ? peaks2 : undefined)
  }, [isNorm, activeCalcCfg, peaks1, peaks2])

  const onUpload = async (file: File, slot: Slot) => {
    setParsingSlot(slot)
    try {
      const res = await parseChromatogram(file, taskId)
      const peaks = res.data.peaks.map((p) => ({ ...p }))
      if (slot === 1) setPeaks1(peaks)
      else setPeaks2(peaks)
      if (!res.data.peaks.length) {
        message.warning('未识别到峰表，请确认截图内容为色谱图谱（峰名+面积），或换更清晰的图')
      }
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '图谱解析失败')
    } finally {
      setParsingSlot(null)
    }
    return false // 阻止 antd 默认上传行为
  }

  const setPeaks = (slot: Slot, updater: (prev: ChromatogramPeak[]) => ChromatogramPeak[]) => {
    if (slot === 1) setPeaks1(updater)
    else setPeaks2(updater)
  }

  const updatePeak = (slot: Slot, index: number, patch: Partial<ChromatogramPeak>) => {
    setPeaks(slot, (prev) => prev.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  const removePeak = (slot: Slot, index: number) => {
    setPeaks(slot, (prev) => prev.filter((_, i) => i !== index))
  }

  // 预填路径：映射 inputs 交给任务页计算表（人工核对实时 % 后再提交引擎）
  const onPrefillClick = () => {
    if (!mapping || !tableNo || !onPrefill) return
    if (mapping.inputs['total_peak_1'] == null || mapping.inputs['main_peak_1'] == null) {
      message.warning('第一份缺总峰面积或主峰面积（峰名未匹配上配置项目，可在峰表里改成计算表项目名后重试）')
      return
    }
    onPrefill(mapping.inputs, tableNo, [...peaks1, ...(peaks2.length ? peaks2 : [])])
    onClose()
  }

  // 直填路径（兼容无计算配置的表号）：峰面积作为结果值直接提交（走待确认人工确认链路）
  const onConfirm = async () => {
    const values = peaks1
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

  const peakColumns = (slot: Slot): TableColumnsType<ChromatogramPeak> => [
    {
      title: '峰名（可改，需匹配计算表项目名）', dataIndex: 'name', width: 230,
      render: (v: string, _, index) => (
        <Input value={v} onChange={(e) => updatePeak(slot, index, { name: e.target.value })} maxLength={64} />
      ),
    },
    {
      title: '保留时间', dataIndex: 'rt', width: 90,
      render: (v: number | null | undefined) => v != null ? v : '-',
    },
    {
      title: '面积（保留两位）', dataIndex: 'area', width: 140,
      render: (v: number | null, _, index) => (
        <InputNumber
          value={v} precision={2} style={{ width: '100%' }}
          onChange={(nv) => updatePeak(slot, index, { area: nv === null ? null : Number(nv) })}
        />
      ),
    },
    {
      title: '操作', key: 'actions', width: 70,
      render: (_: unknown, __: ChromatogramPeak, index: number) => (
        <Button size="small" type="link" danger onClick={() => removePeak(slot, index)}>删除</Button>
      ),
    },
  ]

  const uploadSlot = (slot: Slot) => (
    <div style={{ flex: 1, minWidth: 280 }}>
      <Typography.Text strong>
        {slot === 1 ? '第一份图谱' : '第二份图谱（可选，双份平均）'}
      </Typography.Text>
      <Upload.Dragger
        accept=".jpg,.jpeg,.png,.webp,.bmp,.pdf"
        showUploadList={false}
        beforeUpload={(f) => { void onUpload(f, slot); return false }}
        disabled={parsingSlot !== null}
        style={{ marginBottom: 8, marginTop: 4 }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">{(slot === 1 ? peaks1 : peaks2).length ? '重新上传（覆盖当前峰表）' : '点击或拖拽一张图谱'}</p>
        <p className="ant-upload-hint">一图一针；原图自动归档为任务附件留痕</p>
      </Upload.Dragger>
      {parsingSlot === slot && (
        <div style={{ textAlign: 'center', padding: 16 }}>
          <Spin tip="正在解析图谱（约 10-60 秒）…" />
        </div>
      )}
      {parsingSlot !== slot && (slot === 1 ? peaks1 : peaks2).length > 0 && (
        <Table
          rowKey={(_, index) => String(index)}
          size="small"
          dataSource={slot === 1 ? peaks1 : peaks2}
          columns={peakColumns(slot)}
          pagination={false}
          scroll={{ y: 260 }}
        />
      )}
    </div>
  )

  const mappedColumns: TableColumnsType<{ key: string; label: string; isMain: boolean; a1: number | null; a2: number | null }> = [
    { title: '计算表项目', dataIndex: 'label', width: 200,
      render: (v: string, r) => r.isMain ? <Typography.Text strong>{v}（主峰）</Typography.Text> : v },
    { title: '第一份面积', dataIndex: 'a1', width: 120, render: (v) => v != null ? v : <Tag color="orange">缺</Tag> },
    { title: '第二份面积', dataIndex: 'a2', width: 120, render: (v) => v != null ? v : <Tag>未传</Tag> },
  ]

  return (
    <Modal
      title={title || '图谱解析填计算表'}
      open={open}
      onCancel={onClose}
      width={920}
      centered
      destroyOnClose
      styles={{ body: { maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' } }}
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          {isNorm ? (
            <Button type="primary" disabled={!mapping} onClick={onPrefillClick}>
              预填计算表
            </Button>
          ) : (
            <Button type="primary" loading={submitting} disabled={!peaks1.length} onClick={onConfirm}>
              确认填入
            </Button>
          )}
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Select
          placeholder="计算表表号（必选，映射引擎输入用）" style={{ width: 300 }}
          value={tableNo}
          onChange={(v) => setTableNo(v)}
          options={configs.map((c) => ({
            value: c.table_no,
            label: `${c.table_no}${c.config.calc ? (c.config.calc.mode === 'normalization' ? '（可图谱预填）' : '（暂不支持图谱预填）') : ''}`,
          }))}
          showSearch optionFilterProp="label"
        />
        {tableNo && activeCalcCfg && activeCalcCfg.mode !== 'normalization' && (
          <>
            <DatePicker value={recordDate} allowClear={false} onChange={(v) => v && setRecordDate(v)} />
            <Typography.Text type="warning">该表号非归一化法，暂不支持图谱预填，走直填结果值</Typography.Text>
          </>
        )}
      </Space>

      <div style={{ display: 'flex', gap: 12, alignItems: 'stretch' }}>
        {uploadSlot(1)}
        {uploadSlot(2)}
      </div>

      {mapping && (
        <div style={{ marginTop: 12 }}>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
            映射预览（总峰面积=该份全部峰面积之和；删掉溶剂峰等无关行后再预填）。点「预填计算表」后到在线计算表核对实时计算百分比再提交。
          </Typography.Paragraph>
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={mapping.rows}
            columns={mappedColumns}
          />
          {mapping.unmatchedNames.length > 0 && (
            <Alert
              style={{ marginTop: 8 }}
              type="warning"
              showIcon
              message={`未匹配到计算表项目的峰：${mapping.unmatchedNames.join('、')}`}
              description="这些峰仍计入总峰面积（归一化分母），但不会单独算百分比；峰名若能与计算表项目名对上，改峰名后映射自动更新。"
            />
          )}
        </div>
      )}
    </Modal>
  )
}
