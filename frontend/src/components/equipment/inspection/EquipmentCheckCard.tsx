'use client'

// EquipmentCheckCard 已内嵌在 InspectionExecuteView.tsx 中
// 此文件为单独导出，供需要的场景使用

import { useState } from 'react'
import { App, Button, Card, Form, Input, Select, Space, Tag, Typography } from 'antd'
import { CheckOutlined, CameraOutlined } from '@ant-design/icons'
import { InspectionTemplateItem } from '@/types/equipment'
import { InspectionRecordItem } from '@/types/inspection'
import { PhotoPreviewGroup } from './PhotoPreviewGroup'
import { PhotoUploadButton } from './PhotoUploadButton'

const { Text } = Typography

interface EquipmentCheckCardProps {
  equipmentId: string
  equipmentName: string
  equipmentNo?: string
  templateItems: InspectionTemplateItem[]
  photos: File[]
  onAddPhoto: (file: File) => void
  onRemovePhoto: (index: number) => void
  onSubmit: (records: InspectionRecordItem[]) => Promise<void>
  disabled?: boolean
}

export function EquipmentCheckCard({
  equipmentName,
  equipmentNo,
  templateItems,
  photos,
  onAddPhoto,
  onRemovePhoto,
  onSubmit,
  disabled,
}: EquipmentCheckCardProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const records: InspectionRecordItem[] = (values.records || []).map(
        (row: { result: string; actual_value?: string; remark?: string }, idx: number) => ({
          template_item_id: templateItems[idx].id,
          result: row.result || '正常',
          actual_value: row.actual_value,
          remark: row.remark,
        })
      )
      setLoading(true)
      await onSubmit(records)
      form.resetFields()
    } catch (err: unknown) {
      if ((err as { errorFields?: unknown[] })?.errorFields) return
      message.error((err as Error).message || '提交失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card
      title={
        <Space>
          <Text strong style={{ fontSize: 16 }}>{equipmentName}</Text>
          {equipmentNo && (
            <Tag style={{
              borderRadius: 4,
              color: '#787671',
              background: '#f0eeec',
              border: 'none',
            }}>
              {equipmentNo}
            </Tag>
          )}
        </Space>
      }
      style={{ borderRadius: 12, border: '1px solid #e5e3df' }}
    >
      {/* 到位照片 */}
      <div style={{
        marginBottom: 20,
        padding: 16,
        background: '#fafaf9',
        borderRadius: 8,
        border: '1px dashed #c8c4be',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: photos.length > 0 ? 12 : 0,
        }}>
          <Text strong style={{ fontSize: 14 }}>
            <CameraOutlined style={{ marginRight: 6 }} />
            到位照片
            {photos.length > 0 && (
              <Tag style={{
                marginLeft: 6,
                borderRadius: 4,
                background: '#d9f3e1',
                color: '#1aae39',
                border: 'none',
                fontSize: 12,
              }}>
                {photos.length} 张
              </Tag>
            )}
          </Text>
          <PhotoUploadButton
            onFileSelected={onAddPhoto}
            disabled={disabled}
          />
        </div>
        <PhotoPreviewGroup
          photos={photos}
          onRemove={onRemovePhoto}
          editable={!disabled}
        />
      </div>

      {/* 检查清单 */}
      <Form form={form} layout="vertical">
        {templateItems.map((item, idx) => (
          <Card
            key={item.id}
            size="small"
            style={{
              marginBottom: 8,
              borderRadius: 8,
              border: '1px solid #ede9e4',
              background: '#fafaf9',
            }}
          >
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: 8,
            }}>
              <div>
                <Text strong style={{ fontSize: 14 }}>{item.item_name}</Text>
                {item.expected_result && (
                  <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
                    标准值/预期: {item.expected_result}
                  </Text>
                )}
              </div>
              <Form.Item name={['records', idx, 'result']} initialValue="正常" noStyle>
                <Select
                  size="small"
                  disabled={disabled}
                  style={{ width: 100 }}
                  options={[
                    { label: '✅ 正常', value: '正常' },
                    { label: '⚠️ 异常', value: '异常' },
                    { label: '⏭ 跳过', value: '跳过' },
                  ]}
                />
              </Form.Item>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Form.Item name={['records', idx, 'actual_value']} style={{ flex: 1, marginBottom: 0 }}>
                <Input size="small" placeholder="记录实际值" disabled={disabled} style={{ borderRadius: 6 }} />
              </Form.Item>
              <Form.Item name={['records', idx, 'remark']} style={{ flex: 1, marginBottom: 0 }}>
                <Input size="small" placeholder="备注" disabled={disabled} style={{ borderRadius: 6 }} />
              </Form.Item>
            </div>
          </Card>
        ))}
      </Form>

      <div style={{ marginTop: 16, textAlign: 'right' }}>
        <Button
          type="primary"
          onClick={handleSubmit}
          loading={loading}
          disabled={disabled}
          icon={<CheckOutlined />}
          style={{ borderRadius: 8 }}
        >
          {disabled ? '已完成检查' : '提交本设备检查'}
        </Button>
      </div>
    </Card>
  )
}
