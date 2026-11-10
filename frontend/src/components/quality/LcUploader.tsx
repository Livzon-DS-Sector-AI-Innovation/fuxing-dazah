'use client'

import { useState, useCallback } from 'react'
import { Upload, App, Typography, Input } from 'antd'
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
  // 加密计算表密码由用户按需输入（不预填，密码不出现在代码仓库）
  const [password, setPassword] = useState('')
  const { message } = App.useApp()

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      if (password) formData.append('password', password)

      const result = await uploadLcExcel(formData)
      if (result.task_link) {
        message.success(
          `解析成功并已自动关联检验任务：填入 ${result.task_link.filled.length} 项` +
          (result.task_link.unmatched.length ? `，未匹配 ${result.task_link.unmatched.length} 项` : ''),
          5,
        )
      } else {
        message.success(`解析成功：${result.report.product_name} / ${result.report.batch_number}`)
      }
      onResult(result)
    } catch (err: unknown) {
      message.error((err instanceof Error ? err.message : String(err)) || '解析失败')
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd 默认上传行为
  }, [onResult, message, password])

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
      <div style={{ marginTop: 8 }}>
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          文件有密码？（Excel 加密保护的计算表需填写；密码仅用于本次解析，不保存）
        </Typography.Text>
        <Input.Password
          placeholder="文件密码（无密码可留空）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ maxWidth: 260, marginTop: 4 }}
          autoComplete="new-password"
        />
      </div>

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
