'use client'

import { useEffect, useState } from 'react'
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Select,
  Spin,
  Upload,
} from 'antd'
import type { UploadFile } from 'antd'
import { InboxOutlined } from '@ant-design/icons'

import { createURS, uploadUrsDocument } from '@/actions/safety'
import type { ParseUrsDocumentResponse, URSParsedPoint } from '@/types/safety'
import { T } from '../shared-styles'

const { Dragger } = Upload

interface Props {
  open: boolean
  onClose: () => void
  onCreated?: () => void
}

export function URSRegisterDrawer({ open, onClose, onCreated }: Props) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [parsing, setParsing] = useState(false)
  const [attachmentPath, setAttachmentPath] = useState<string>()
  const [parsedPoints, setParsedPoints] = useState<URSParsedPoint[]>([])

  useEffect(() => {
    if (open) {
      form.resetFields()
      setFileList([])
      setAttachmentPath(undefined)
      setParsedPoints([])
    }
  }, [open, form])

  const handleUpload = async (file: File) => {
    setParsing(true)
    try {
      const res = await uploadUrsDocument(file)
      if (res.code >= 200 && res.code < 300) {
        const data = res.data
        if (data) {
          form.setFieldsValue({
            equipment_name: data.equipment_name || undefined,
            equipment_category: data.equipment_category || undefined,
            department: data.department || undefined,
            procurement_purpose: data.procurement_purpose || undefined,
            urs_content: data.urs_content || undefined,
          })
          setAttachmentPath(data.attachment_path || undefined)
          setParsedPoints(data.structured_points || [])
          message.success('解析完成，已自动回填表单')
        }
      } else {
        message.error(res.message || '解析失败')
        setFileList([])
      }
    } catch {
      message.error('解析失败，请检查文件格式')
      setFileList([])
    } finally {
      setParsing(false)
    }
  }

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    const res = await createURS({ ...values, attachment_path: attachmentPath })
    setSaving(false)
    if (res.code >= 200 && res.code < 300) {
      message.success(`已创建 ${res.data?.urs_no ?? ''}，草稿状态`)
      onCreated?.()
    } else {
      message.error(res.message || '创建失败')
    }
  }

  return (
    <Drawer title="新建 URS 智能审核" width={560} open={open} onClose={onClose}
      footer={
        <div style={{ textAlign: 'right' }}>
          <Button onClick={onClose} style={{ marginRight: 8 }}>取消</Button>
          <Button type="primary" loading={saving} onClick={handleOk} style={{ background: T.primary, borderColor: T.primary }}>保存草稿</Button>
        </div>
      }>
      <Form form={form} layout="vertical">
        <Form.Item label="URS 附件" extra="上传后自动解析并回填下方字段（支持 docx/pdf/xlsx/txt，也可手填）">
          <Dragger
            beforeUpload={(file) => {
              void handleUpload(file as File)
              return false
            }}
            accept=".docx,.pdf,.doc,.txt,.xlsx,.xls,.md"
            maxCount={1}
            fileList={fileList}
            disabled={parsing}
            onChange={({ fileList: fl }) => setFileList(fl)}
            onRemove={() => {
              setFileList([])
              setAttachmentPath(undefined)
              setParsedPoints([])
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            {parsing ? (
              <>
                <Spin size="small" style={{ marginRight: 8 }} />
                <p className="ant-upload-text">AI 正在解析文档...</p>
              </>
            ) : (
              <>
                <p className="ant-upload-text">点击或拖拽 URS 文档到此区域</p>
                <p className="ant-upload-hint">支持 DOCX / PDF / XLSX / TXT，上传后自动解析回填</p>
              </>
            )}
          </Dragger>
        </Form.Item>

        <Form.Item name="equipment_name" label="设备名称" rules={[{ required: true, message: '请输入设备名称' }]}>
          <Input placeholder="如：沉降菌/浮游菌自动采样系统" />
        </Form.Item>
        <Form.Item name="equipment_category" label="设备类别">
          <Select placeholder="选择设备类别" allowClear options={[
            { value: '采样系统', label: '采样系统' }, { value: '反应釜', label: '反应釜' },
            { value: '泵', label: '泵' }, { value: '离心机', label: '离心机' },
            { value: '干燥设备', label: '干燥设备' }, { value: '储罐', label: '储罐' },
            { value: '实验室仪器', label: '实验室仪器' }, { value: '其他', label: '其他' },
          ]} />
        </Form.Item>
        <Form.Item name="department" label="申请部门">
          <Input placeholder="如：质量部" />
        </Form.Item>
        <Form.Item name="applicant_name" label="申请人">
          <Input placeholder="申请人姓名" />
        </Form.Item>
        <Form.Item name="procurement_purpose" label="采购用途">
          <Select placeholder="选择采购用途" allowClear options={[
            { value: '新增', label: '新增' }, { value: '更换', label: '更换' }, { value: '技术改造', label: '技术改造' },
          ]} />
        </Form.Item>

        {parsedPoints.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 8, color: '#393936' }}>
              解析要点
            </div>
            {parsedPoints.map((point, idx) => (
              <div key={idx} style={{ marginBottom: 8, padding: '8px 12px', background: '#f7f7f5', borderRadius: 8 }}>
                <div style={{ fontWeight: 500, color: T.primary }}>{point.category}</div>
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {point.items.map((item, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#56534d' }}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        <Form.Item name="urs_content" label="URS 正文" extra="完整原文将作为 AI 审核依据，可编辑">
          <Input.TextArea rows={8} placeholder="上传附件后自动填充完整原文，也可手动粘贴" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
