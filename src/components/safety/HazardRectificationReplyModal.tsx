'use client'

import { useState } from 'react'
import { Modal, Form, Input, Upload, App, Image } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { replyRectification, reworkRectification, uploadRectificationPhoto } from '@/actions/safety'
import type { HazardReport } from '@/types/safety'
import type { UploadFile } from 'antd/es/upload'

const { TextArea } = Input
const { Dragger } = Upload

// ── 图片后端基础 URL ──
const BACKEND_HOST = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
  .replace(/\/api\/v1$/, '')

interface Props {
  open: boolean
  record: HazardReport | null
  mode: 'reply' | 'rework'
  onClose: () => void
  onSuccess: (updated: HazardReport) => void
}

export default function HazardRectificationReplyModal({
  open,
  record,
  mode,
  onClose,
  onSuccess,
}: Props) {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [uploading, setUploading] = useState(false)
  const { message } = App.useApp()

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      // 上传所有待上传的文件
      const pendingFiles = fileList.filter((f) => !f.url && !f.status)
      const uploadedUrls: string[] = fileList
        .filter((f) => f.url)
        .map((f) => f.url!)

      if (pendingFiles.length > 0) {
        setUploading(true)
        for (const file of pendingFiles) {
          try {
            const response = await uploadRectificationPhoto(
              record!.id,
              file.originFileObj as File
            )
            if (response.code === 200 && response.data) {
              // 从返回数据中提取 rectification_photos
              const data = response.data as HazardReport
              if (data.rectification_photos) {
                // 获取最新上传的图片 URL
                try {
                  const photos = JSON.parse(data.rectification_photos)
                  const lastUrl = Array.isArray(photos) ? photos[photos.length - 1] : null
                  if (lastUrl) {
                    uploadedUrls.push(lastUrl)
                  }
                } catch { /* ignore parse error */ }
              }
            }
          } catch {
            message.error('图片上传失败')
          }
        }
        setUploading(false)
      }

      const data: { reply_content: string; rectification_photos?: string } = {
        reply_content: values.reply_content,
      }
      // 将上传后的 URL 列表转为 JSON 字符串
      if (uploadedUrls.length > 0) {
        data.rectification_photos = JSON.stringify(uploadedUrls)
      }

      const action = mode === 'reply' ? replyRectification : reworkRectification
      const response = await action(record!.id, data)
      if (response.code === 200) {
        message.success(mode === 'reply' ? '整改回复已提交' : '已重新提交整改回复')
        onSuccess(response.data!)
        form.resetFields()
        setFileList([])
        onClose()
      } else {
        message.error(response.message || '操作失败')
      }
    } catch {
      // validation error
    } finally {
      setSubmitting(false)
      setUploading(false)
    }
  }

  const title = mode === 'reply' ? '整改回复' : '重新整改'

  // 将现有记录中的整改照片转为 Upload 需要的 fileList 格式
  const existingPhotos: string[] = (() => {
    if (!record?.rectification_photos) return []
    try {
      const parsed = JSON.parse(record.rectification_photos)
      return Array.isArray(parsed) ? parsed : []
    } catch { return [] }
  })()

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={submitting || uploading}
      okText="提交"
      cancelText="取消"
      width={650}
      destroyOnHidden
    >
      {/* 隐患信息摘要 */}
      {record && (
        <div
          style={{
            background: '#faf9f7',
            padding: 12,
            borderRadius: 8,
            marginBottom: 16,
            fontSize: 13,
            lineHeight: 1.8,
          }}
        >
          <div>
            <strong>隐患编号：</strong>
            {record.hazard_no}
          </div>
          <div>
            <strong>隐患描述：</strong>
            {record.description}
          </div>
          <div>
            <strong>地点/部位：</strong>
            {record.location || '-'}
          </div>
          {record.rectification_responsible_person_name && (
            <div>
              <strong>责任人：</strong>
              {record.rectification_responsible_person_name}
            </div>
          )}
          {record.corrective_preventive_measures && (
            <div>
              <strong>整改要求：</strong>
              {record.corrective_preventive_measures}
            </div>
          )}
        </div>
      )}

      <Form form={form} layout="vertical">
        <Form.Item
          name="reply_content"
          label="整改实施情况"
          rules={[{ required: true, message: '请描述整改实施情况' }]}
        >
          <TextArea
            rows={4}
            placeholder="请详细描述整改实施情况，包括具体整改措施、实施过程、完成情况等"
          />
        </Form.Item>

        <Form.Item label="整改后照片">
          <Dragger
            multiple
            fileList={fileList}
            beforeUpload={(file) => {
              // 阻止自动上传，手动控制
              setFileList((prev) => [...prev, file as unknown as UploadFile])
              return false
            }}
            onRemove={(file) => {
              setFileList((prev) => prev.filter((f) => f.uid !== file.uid))
            }}
            accept="image/*"
            showUploadList={{ showPreviewIcon: true, showRemoveIcon: true }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽图片到此区域上传</p>
            <p className="ant-upload-hint">支持多张整改后照片（提交时统一上传）</p>
          </Dragger>
        </Form.Item>

        {/* 已有照片展示 */}
        {existingPhotos.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 8, color: '#5d5b54' }}>
              已有整改照片：
            </div>
            <Image.PreviewGroup>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {existingPhotos.map((url, i) => (
                  <Image
                    key={i}
                    src={url.startsWith('http') ? url : `${BACKEND_HOST}/${url.replace(/^\/+/, '')}`}
                    alt={`整改照片 ${i + 1}`}
                    width={80}
                    height={80}
                    style={{ objectFit: 'cover', borderRadius: 6, border: '1px solid #e5e3df' }}
                  />
                ))}
              </div>
            </Image.PreviewGroup>
          </div>
        )}

        {/* 新上传文件预览 */}
        {fileList.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 8, color: '#5d5b54' }}>
              待上传照片（{fileList.length} 张）：
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {fileList.map((file) => {
                const previewUrl = file.thumbUrl
                  || (file.originFileObj instanceof File
                    ? URL.createObjectURL(file.originFileObj)
                    : undefined)
                return (
                  <div key={file.uid} style={{ position: 'relative' }}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={previewUrl || ''}
                      alt={file.name}
                      style={{ width: 80, height: 80, objectFit: 'cover', borderRadius: 6, border: '1px solid #e5e3df' }}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </Form>
    </Modal>
  )
}
