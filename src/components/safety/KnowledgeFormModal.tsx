'use client'

import { useState } from 'react'
import {
  Modal,
  Form,
  Input,
  Select,
  DatePicker,
  Upload,
  Button,
  Row,
  Col,
  message,
  Space,
} from 'antd'
import { InboxOutlined, UploadOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload'
import {
  createKnowledgeArticle,
  updateKnowledgeArticle,
  uploadKnowledgeAttachment,
  checkDuplicateArticle,
} from '@/actions/safety'
import type {
  SafetyKnowledgeArticle,
  SafetyKnowledgeArticleFormData,
} from '@/types/safety'
import { KNOWLEDGE_CATEGORY_OPTIONS } from '@/types/safety'
import dayjs from 'dayjs'

const { Dragger } = Upload

interface Props {
  open: boolean
  editingRecord: SafetyKnowledgeArticle | null
  onClose: () => void
  onSuccess: () => void
}

export default function KnowledgeFormModal({
  open,
  editingRecord,
  onClose,
  onSuccess,
}: Props) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])

  const isEdit = !!editingRecord

  const resetForm = () => {
    form.resetFields()
    setFileList([])
    setSaving(false)
  }

  const handleClose = () => {
    resetForm()
    onClose()
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)

      // Duplicate check for new articles
      if (!isEdit) {
        try {
          const dupRes = await checkDuplicateArticle({
            title: values.title,
            content: values.content,
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
          // Duplicate check failed silently
        }
      }

      const formData: SafetyKnowledgeArticleFormData = {
        article_no: values.article_no || undefined,
        title: values.title,
        category: values.category,
        summary: values.summary,
        content: values.content,
        tags: values.tags,
        source: values.source,
        author: values.author,
        publish_date: values.publish_date
          ? dayjs(values.publish_date).toISOString()
          : undefined,
        notes: values.notes,
      }

      let response
      if (isEdit) {
        response = await updateKnowledgeArticle(editingRecord!.id, formData)
      } else {
        response = await createKnowledgeArticle(formData)
      }

      if (response.code === 200) {
        // Upload attachment if file selected (for new articles)
        if (!isEdit && fileList.length > 0 && response.data) {
          const file = fileList[0].originFileObj as File | undefined
          if (file) {
            try {
              await uploadKnowledgeAttachment(response.data.id, file)
            } catch {
              // Attachment upload failed silently — article is saved
            }
          }
        }
        message.success(isEdit ? '更新成功' : '创建成功')
        resetForm()
        onSuccess()
      } else {
        message.error(response.message || '保存失败')
      }
    } catch {
      // Form validation error
    } finally {
      setSaving(false)
    }
  }

  // Pre-fill form when editing
  const afterOpenChange = (visible: boolean) => {
    if (visible && editingRecord) {
      form.setFieldsValue({
        ...editingRecord,
        publish_date: editingRecord.publish_date
          ? dayjs(editingRecord.publish_date)
          : undefined,
      })
    }
    if (visible && !editingRecord) {
      form.resetFields()
      setFileList([])
    }
  }

  return (
    <Modal
      title={isEdit ? '编辑文档' : '新建文档'}
      open={open}
      onOk={handleSubmit}
      onCancel={handleClose}
      width={800}
      okText="确认"
      cancelText="取消"
      confirmLoading={saving}
      afterOpenChange={afterOpenChange}
    >
      <Form form={form} layout="vertical">
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item
              name="article_no"
              label="文档编号"
              extra="留空自动生成"
            >
              <Input placeholder="自动生成" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="category"
              label="知识分类"
              rules={[{ required: true, message: '请选择分类' }]}
            >
              <Select
                options={KNOWLEDGE_CATEGORY_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
                placeholder="请选择分类"
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="publish_date"
              label="发布日期"
            >
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="title"
          label="文档标题"
          rules={[{ required: true, message: '请输入标题' }]}
        >
          <Input placeholder="请输入文档标题" />
        </Form.Item>

        <Form.Item name="summary" label="摘要">
          <Input.TextArea rows={2} placeholder="请输入摘要" />
        </Form.Item>

        <Form.Item name="content" label="正文内容">
          <Input.TextArea rows={6} placeholder="请输入正文内容" />
        </Form.Item>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="tags" label="标签">
              <Input placeholder="多个以逗号分隔" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="source" label="来源">
              <Input placeholder="来源/出处" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="author" label="作者/发布单位">
              <Input placeholder="作者或发布单位" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="notes" label="备注">
              <Input placeholder="请输入备注" />
            </Form.Item>
          </Col>
        </Row>

        {/* File upload — only for new articles */}
        {!isEdit && (
          <Form.Item label="附件（可选）">
            <Dragger
              beforeUpload={() => false}
              maxCount={1}
              fileList={fileList}
              onChange={({ fileList: fl }) => setFileList(fl)}
              onRemove={() => setFileList([])}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">点击或拖拽附件到此区域</p>
              <p className="ant-upload-hint">
                支持 PDF、DOCX、图片等格式
              </p>
            </Dragger>
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
