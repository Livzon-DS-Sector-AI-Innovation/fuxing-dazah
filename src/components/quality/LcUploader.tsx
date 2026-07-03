'use client'

import { useState, useCallback } from 'react'
import { Upload, App, Space, Typography } from 'antd'
import { InboxOutlined, FileExcelOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd'
import { uploadLcExcel } from '@/actions/quality'
import type { UploadLcResponse } from '@/types/quality'

const { Dragger } = Upload
const { Text } = Typography

interface Props {
  onResult: (data: UploadLcResponse) => void
}

export default function LcUploader({ onResult }: Props) {
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const { message } = App.useApp()

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const result = await uploadLcExcel(formData)
      message.success(`解析成功：${result.report.product_name} / ${result.report.batch_number}`)
      onResult(result)
    } catch (err: any) {
      message.error(err.message || '解析失败')
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd 默认上传行为
  }, [onResult, message])

  return (
    <div style={{ maxWidth: 600 }}>
      <Dragger
        accept=".xlsx,.xls"
        maxCount={1}
        fileList={fileList}
        beforeUpload={(file) => {
          // 限制文件大小
          if (file.size > 10 * 1024 * 1024) {
            message.error('文件大小不能超过 10MB')
            return false
          }
          // 限制文件类型
          const ext = file.name.split('.').pop()?.toLowerCase()
          if (ext !== 'xlsx' && ext !== 'xls') {
            message.error('仅支持 .xlsx 或 .xls 格式')
            return false
          }
          setFileList([file as UploadFile])
          handleUpload(file)
          return false
        }}
        onRemove={() => setFileList([])}
        disabled={uploading}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">
          {uploading ? '正在解析...' : '点击或拖拽液相计算表到此区域'}
        </p>
        <p className="ant-upload-hint">
          支持 .xlsx / .xls 格式，文件大小不超过 10MB
        </p>
      </Dragger>

      {uploading && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <Text type="secondary">
            <FileExcelOutlined /> 正在解析 Excel 计算表...
          </Text>
        </div>
      )}
    </div>
  )
}
