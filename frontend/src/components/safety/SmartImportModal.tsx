'use client'

import { useState } from 'react'
import {
  Modal,
  Upload,
  Button,
  Spin,
  Form,
  Input,
  Select,
  DatePicker,
  message,
  Row,
  Col,
  Steps,
  Result,
} from 'antd'
import type { UploadFile } from 'antd/es/upload'
import {
  InboxOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import {
  parseKnowledgeDocument,
  createKnowledgeArticle,
  checkDuplicateArticle,
} from '@/actions/safety'
import type { ParseDocumentResponse, SafetyKnowledgeArticleFormData } from '@/types/safety'
import { KNOWLEDGE_CATEGORY_OPTIONS } from '@/types/safety'
import dayjs from 'dayjs'

const { Dragger } = Upload

interface Props {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

export default function SmartImportModal({ open, onClose, onSuccess }: Props) {
  const [form] = Form.useForm()
  const [step, setStep] = useState<'upload' | 'parsing' | 'review' | 'success'>('upload')
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [parseResult, setParseResult] = useState<ParseDocumentResponse | null>(null)
  const [saving, setSaving] = useState(false)

  const resetAll = () => {
    form.resetFields()
    setFileList([])
    setParseResult(null)
    setStep('upload')
    setSaving(false)
  }

  const handleClose = () => {
    resetAll()
    onClose()
  }

  const handleParse = async () => {
    const file = fileList[0]?.originFileObj as File | undefined
    if (!file) {
      message.warning('请先选择文件')
      return
    }
    setStep('parsing')
    try {
      const response = await parseKnowledgeDocument(file)
      if (response.code === 200 && response.data) {
        const data = response.data
        setParseResult(data)
        // Pre-fill form
        form.setFieldsValue({
          title: data.title,
          category: data.category,
          summary: data.summary,
          tags: data.tags,
          source: data.source,
          author: data.author,
          publish_date: data.publish_date ? dayjs(data.publish_date) : undefined,
        })
        setStep('review')
        message.success('文档解析完成，请审核信息')
      } else {
        message.error(response.message || '解析失败')
        setStep('upload')
      }
    } catch {
      message.error('文档解析失败，请检查文件格式')
      setStep('upload')
    }
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // Check duplicates before saving
      if (parseResult) {
        try {
          const dupRes = await checkDuplicateArticle({
            title: values.title,
            content: parseResult.full_content?.slice(0, 1000),
          })
          if (dupRes.code === 200 && dupRes.data?.has_duplicates) {
            const confirmed = window.confirm(
              `发现 ${dupRes.data.duplicates.length} 篇相似文档：\n` +
                dupRes.data.duplicates.map((d) => `• ${d.title}`).join('\n') +
                '\n\n确定继续保存吗？'
            )
            if (!confirmed) {
              setSaving(false)
              return
            }
          }
        } catch {
          // Duplicate check failed silently — proceed with save
        }
      }

      const formData: SafetyKnowledgeArticleFormData = {
        title: values.title,
        category: values.category,
        summary: values.summary,
        content: parseResult?.full_content || '',
        tags: values.tags,
        source: values.source,
        author: values.author,
        publish_date: values.publish_date
          ? dayjs(values.publish_date).toISOString()
          : undefined,
        notes: values.notes,
      }

      const response = await createKnowledgeArticle(formData)
      if (response.code === 200) {
        setStep('success')
      } else {
        message.error(response.message || '保存失败')
      }
    } catch {
      message.error('表单验证失败')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    setParseResult(null)
    form.resetFields()
    setFileList([])
    setStep('upload')
  }

  // ── Render ──────────────────────────────────────────

  return (
    <Modal
      title="智能导入文档"
      open={open}
      onCancel={handleClose}
      width={800}
      footer={null}
      destroyOnHidden
    >
      {/* Step indicator */}
      <Steps
        current={step === 'upload' ? 0 : step === 'parsing' ? 0 : step === 'review' ? 1 : 2}
        items={[
          { title: '上传文件', icon: step === 'parsing' ? <Spin size="small" /> : <InboxOutlined /> },
          { title: '审核信息', icon: <FileTextOutlined /> },
          { title: '完成', icon: <CheckCircleOutlined /> },
        ]}
        style={{ marginBottom: 24 }}
      />

      {/* Step: Upload */}
      {step === 'upload' && (
        <div>
          <Dragger
            beforeUpload={() => false}
            accept=".pdf,.docx,.doc,.txt,.xlsx,.xls,.md"
            maxCount={1}
            fileList={fileList}
            onChange={({ fileList: fl }) => setFileList(fl)}
            onRemove={() => setFileList([])}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽文件到此区域</p>
            <p className="ant-upload-hint">
              支持 PDF、DOCX、TXT、XLSX、MD 格式
            </p>
          </Dragger>

          <div style={{ textAlign: 'right', marginTop: 16 }}>
            <Button onClick={handleClose} style={{ marginRight: 8 }}>
              取消
            </Button>
            <Button
              type="primary"
              onClick={handleParse}
              disabled={fileList.length === 0}
            >
              开始解析
            </Button>
          </div>
        </div>
      )}

      {/* Step: Parsing */}
      {step === 'parsing' && (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <Spin size="large" />
          <p style={{ marginTop: 16, color: '#787671' }}>
            AI 正在分析文档内容，提取关键信息...
          </p>
          <p style={{ color: '#a4a097', fontSize: 12 }}>
            解析可能需要 10-30 秒，请耐心等待
          </p>
        </div>
      )}

      {/* Step: Review */}
      {step === 'review' && parseResult && (
        <div>
          <div style={{ marginBottom: 12, padding: '8px 12px', background: '#f6f5f4', borderRadius: 8 }}>
            <FileTextOutlined style={{ marginRight: 8 }} />
            AI 已自动提取以下信息，请审核修改后保存
          </div>

          <Form form={form} layout="vertical">
            <Row gutter={16}>
              <Col span={14}>
                <Form.Item name="title" label="文档标题" rules={[{ required: true }]}>
                  <Input placeholder="请输入文档标题" />
                </Form.Item>
              </Col>
              <Col span={10}>
                <Form.Item name="category" label="知识分类" rules={[{ required: true }]}>
                  <Select
                    options={KNOWLEDGE_CATEGORY_OPTIONS.map((o) => ({
                      value: o.value,
                      label: o.label,
                    }))}
                  />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item name="summary" label="摘要">
              <Input.TextArea rows={2} placeholder="AI 生成的摘要" />
            </Form.Item>

            <Form.Item name="tags" label="标签">
              <Input placeholder="多个以逗号分隔" />
            </Form.Item>

            {parseResult.content_preview && (
              <div
                style={{
                  marginBottom: 16,
                  padding: 12,
                  background: '#fafaf9',
                  border: '1px solid #e5e3df',
                  borderRadius: 8,
                  maxHeight: 150,
                  overflow: 'auto',
                }}
              >
                <div style={{ fontSize: 12, color: '#a4a097', marginBottom: 4 }}>
                  正文预览（前500字）
                </div>
                <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                  {parseResult.content_preview}
                </div>
              </div>
            )}

            <Row gutter={16}>
              <Col span={8}>
                <Form.Item name="source" label="来源">
                  <Input placeholder="来源/出处" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="author" label="作者/发布单位">
                  <Input placeholder="作者或发布单位" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="publish_date" label="发布日期">
                  <DatePicker style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item name="notes" label="备注">
              <Input.TextArea rows={2} placeholder="请输入备注" />
            </Form.Item>
          </Form>

          <div style={{ textAlign: 'right', marginTop: 8 }}>
            <Button onClick={handleReset} style={{ marginRight: 8 }}>
              重新上传
            </Button>
            <Button onClick={handleClose} style={{ marginRight: 8 }}>
              取消
            </Button>
            <Button type="primary" onClick={handleSave} loading={saving}>
              确认保存
            </Button>
          </div>
        </div>
      )}

      {/* Step: Success */}
      {step === 'success' && (
        <Result
          status="success"
          title="文档导入成功"
          subTitle="文档已保存到知识库，可在列表中查看"
          extra={[
            <Button key="list" onClick={() => { resetAll(); onSuccess() }}>
              返回列表
            </Button>,
            <Button key="new" type="primary" onClick={handleReset}>
              继续导入
            </Button>,
          ]}
        />
      )}
    </Modal>
  )
}
