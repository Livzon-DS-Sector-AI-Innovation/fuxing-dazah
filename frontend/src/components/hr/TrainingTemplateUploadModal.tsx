'use client'

// 上传新模板向导：选文件 → 自动识别 {占位符} → 选目标导出（按板块分组）
// → 对照提示缺哪些必填 / 哪些不被识别 → 填备注上传生效。
// 目标导出即映射：每个导出固定一个模板槽位，上传即成为该导出的当前模板。

import { useMemo, useState } from 'react'
import { Alert, App, Button, Form, Input, Modal, Select, Spin, Tag, Upload } from 'antd'
import { InboxOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  autofillTrainingExportTemplate,
  inspectTrainingExportTemplate,
  uploadTrainingExportTemplate,
} from '@/actions/hr/training'
import type { TrainingTemplateDef } from '@/types/hr/trainingTemplates'

interface Props {
  open: boolean
  templates: TrainingTemplateDef[]
  onClose: () => void
  onUploaded: () => void | Promise<void>
}

/** 占位符命中：精确相等，或目标标记的日期过滤器变体（{入职日期| customDate:'…'}） */
function markerMatches(detected: string, name: string): boolean {
  return detected === name || detected.startsWith(`{${name.slice(1, -1)}|`)
}

export default function TrainingTemplateUploadModal({ open, templates, onClose, onUploaded }: Props) {
  const { message } = App.useApp()
  const [file, setFile] = useState<File | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [detected, setDetected] = useState<string[] | null>(null)
  const [targetKey, setTargetKey] = useState<string | null>(null)
  const [remark, setRemark] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [autofilling, setAutofilling] = useState(false)
  const [placements, setPlacements] = useState<{ marker: string; where: string }[]>([])

  const reset = () => {
    setFile(null)
    setDetected(null)
    setTargetKey(null)
    setRemark('')
    setPlacements([])
  }

  const close = () => {
    reset()
    onClose()
  }

  const groupedOptions = useMemo(() => {
    const bySection = new Map<string, TrainingTemplateDef[]>()
    for (const t of templates) {
      const list = bySection.get(t.section) ?? []
      list.push(t)
      bySection.set(t.section, list)
    }
    return Array.from(bySection.entries()).map(([section, defs]) => ({
      label: section,
      options: defs.map((d) => ({ label: d.name, value: d.key })),
    }))
  }, [templates])

  const target = templates.find((t) => t.key === targetKey) ?? null

  const handlePickFile = async (picked: File) => {
    setFile(picked)
    setDetected(null)
    setInspecting(true)
    try {
      const fd = new FormData()
      fd.append('file', picked)
      const r = await inspectTrainingExportTemplate(fd)
      setDetected(r.data?.markers ?? [])
    } catch (e) {
      message.error(e instanceof Error ? e.message : '识别占位符失败')
      setFile(null)
    } finally {
      setInspecting(false)
    }
  }

  // 对照结果（选了目标后才计算）
  const missingRequired = target && detected
    ? target.markers.filter((m) => m.required && !detected.some((d) => markerMatches(d, m.name)))
    : []
  const unrecognized = target && detected
    ? detected.filter((d) => !target.markers.some((m) => markerMatches(d, m.name)))
    : []
  const canSubmit = !!file && !!targetKey && detected !== null && missingRequired.length === 0 && !submitting

  const handleAutofill = async () => {
    if (!file || !targetKey) return
    setAutofilling(true)
    try {
      const fd = new FormData()
      fd.append('key', targetKey)
      fd.append('file', file)
      const r = await autofillTrainingExportTemplate(targetKey, fd)
      const { file_base64: base64, placements: placed, missing: stillMissing } = r.data || {}
      if (!base64) {
        message.warning(r.data?.message || '没有找到可以自动生成占位符的标签格')
        return
      }
      // 用生成后的文件替换当前文件，占位符清单合并已插入的部分
      const bin = atob(base64)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      setFile(new File([bytes], file.name, { type: file.type || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
      setPlacements(placed)
      const placedNames = placed.map((p) => p.marker)
      setDetected((prev) => Array.from(new Set([...(prev ?? []), ...placedNames])))
      message.success(r.data?.message || `已生成 ${placed.length} 个占位符`)
      if (stillMissing.length > 0) {
        message.warning(`仍有 ${stillMissing.length} 个必填标记放不进对应标签格，请在 Word 里手动补：${stillMissing.join('、')}`)
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '自动生成占位符失败')
    } finally {
      setAutofilling(false)
    }
  }

  const handleSubmit = async () => {
    if (!file || !targetKey) return
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('remark', remark)
      const r = await uploadTrainingExportTemplate(targetKey, fd)
      message.success(r.message || '已上传并生效')
      await onUploaded()
      close()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="上传新模板"
      open={open}
      onCancel={close}
      onOk={() => void handleSubmit()}
      okText="上传并生效"
      okButtonProps={{ disabled: !canSubmit, loading: submitting }}
      width={640}
      destroyOnHidden
    >
      <div className="space-y-4">
        <Upload.Dragger
          accept=".docx"
          showUploadList={false}
          beforeUpload={(f) => {
            void handlePickFile(f)
            return false
          }}
          disabled={inspecting}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          {file ? (
            <p className="ant-upload-text">已选择：{file.name}（点击可重新选择）</p>
          ) : (
            <>
              <p className="ant-upload-text">点击或拖拽 Word 模板（.docx）到此处</p>
              <p className="ant-upload-hint">选好后自动识别文件里的占位符</p>
            </>
          )}
        </Upload.Dragger>

        {inspecting && <div className="flex justify-center py-2"><Spin tip="正在识别占位符…" /></div>}

        {detected !== null && (
          <div>
            <div className="mb-1 text-[13px] text-[var(--color-steel)]">
              识别到 <b>{detected.length}</b> 个占位符
            </div>
            {detected.length === 0 ? (
              <Alert type="warning" showIcon title="文件里没有识别到任何 {占位符}，这样的模板导出时不会带出数据" />
            ) : (
              <div className="flex flex-wrap gap-1">
                {detected.map((m) => <Tag key={m}><code>{m}</code></Tag>)}
              </div>
            )}
          </div>
        )}

        <Form layout="vertical" className="mb-0">
          <Form.Item label="映射到哪个导出文件" required className="mb-3">
            <Select
              placeholder="按板块选择导出文件"
              options={groupedOptions}
              value={targetKey ?? undefined}
              onChange={(v) => setTargetKey(v)}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item label="备注（可选）" className="mb-0">
            <Input
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
              maxLength={200}
              placeholder="如：改了表头样式 / 调整注意事项文案"
            />
          </Form.Item>
        </Form>

        {target && (
          <div className="space-y-2">
            <div className="text-[13px] text-[var(--color-steel)]">
              用于：{target.usages.join('、')}
            </div>
            {detected !== null && missingRequired.length > 0 && (
              <Alert
                type="error"
                showIcon
                title={`缺少必填标记：${missingRequired.map((m) => m.name).join('、')}`}
                description={
                  <div className="space-y-2">
                    <span>可在 Word 里手动补，或让系统按表格标签自动生成（识别「培训内容」「姓名」这类标签格，把标记写进旁边空白格）。</span>
                    <div>
                      <Button
                        size="small"
                        type="primary"
                        icon={<ThunderboltOutlined />}
                        loading={autofilling}
                        onClick={() => void handleAutofill()}
                      >
                        自动生成占位符
                      </Button>
                    </div>
                  </div>
                }
              />
            )}
            {placements.length > 0 && (
              <Alert
                type="success"
                showIcon
                title={`已按标签自动生成 ${placements.length} 个占位符（以生成后的文件为准）`}
                description={
                  <ul className="list-disc pl-5 m-0 text-[13px] leading-6">
                    {placements.map((p) => (
                      <li key={`${p.marker}${p.where}`}><code>{p.marker}</code> ← {p.where}</li>
                    ))}
                  </ul>
                }
              />
            )}
            {detected !== null && unrecognized.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`有 ${unrecognized.length} 个标记不被该导出识别（导出时会被清除）：${unrecognized.join('、')}`}
              />
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
