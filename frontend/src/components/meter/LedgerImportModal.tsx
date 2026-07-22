'use client'

import { useState } from 'react'
import { App, Button, Modal, Upload, Space, Alert, Descriptions, Typography } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { LedgerImportResult } from '@/types/meter'
import { importInstrumentLedger as apiImportInstrumentLedger, importGasDetectorLedger as apiImportGasDetectorLedger } from '@/lib/api/meter'

const { Dragger } = Upload
const { Text } = Typography

interface Props {
  open: boolean
  source: 'instrument' | 'gas_detector'
  onClose: () => void
}

export function LedgerImportModal({ open, source, onClose }: Props) {
  const { message } = App.useApp()
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<LedgerImportResult | null>(null)

  const sourceLabel = source === 'instrument' ? '标准计量器具' : '有毒有害可燃探测器'

  const handleImport = async () => {
    if (!file) {
      message.warning('请先选择文件')
      return
    }
    setImporting(true)
    try {
      const fn = source === 'instrument' ? apiImportInstrumentLedger : apiImportGasDetectorLedger
      const res = await fn(file)
      setResult(res)
      const warnCount = res.warnings?.length ?? 0
      if (warnCount > 0) {
        message.success(`导入完成：新增 ${res.imported_count} 条，${warnCount} 条字段缺失提醒`)
      } else {
        message.success(`导入完成：新增 ${res.imported_count} 条记录`)
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '导入失败')
    } finally {
      setImporting(false)
    }
  }

  const handleClose = () => {
    setFile(null)
    setResult(null)
    setImporting(false)
    onClose()
  }

  const uploadProps: UploadProps = {
    beforeUpload: (f) => {
      const ext = f.name.split('.').pop()?.toLowerCase()
      if (!ext || !['et', 'xlsx', 'xls'].includes(ext)) {
        message.error('仅支持 .et 和 .xlsx 文件')
        return Upload.LIST_IGNORE
      }
      if (f.size > 50 * 1024 * 1024) {
        message.error('文件大小不能超过 50MB')
        return Upload.LIST_IGNORE
      }
      setFile(f)
      setResult(null)
      return false // 阻止自动上传
    },
    onRemove: () => {
      setFile(null)
      setResult(null)
    },
    maxCount: 1,
    fileList: file ? [{ uid: '-1', name: file.name, status: 'done' as const }] : [],
  }

  return (
    <Modal
      title={`导入${sourceLabel}台账`}
      open={open}
      onCancel={handleClose}
      width={700}
      footer={
        <Space>
          <Button onClick={handleClose}>关闭</Button>
          <Button type="primary" onClick={handleImport} loading={importing} disabled={!file}>
            开始导入
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <Alert
        title="注意：导入将全量替换现有数据"
        description={`上传 Excel 文件后，系统将清空所有现有${sourceLabel}记录，再用文件内容重新填充。此操作不可撤销，请谨慎操作。`}
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Dragger {...uploadProps}>
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此区域</p>
        <p className="ant-upload-hint">支持 .et (WPS) 和 .xlsx 格式，文件大小不超过 50MB</p>
      </Dragger>

      {result && (
        <div style={{ marginTop: 16 }}>
          <Descriptions column={3} size="small" bordered>
            <Descriptions.Item label="清空旧记录">{result.deleted_count} 条</Descriptions.Item>
            <Descriptions.Item label="成功导入">{result.imported_count} 条</Descriptions.Item>
            <Descriptions.Item label="处理 Sheet">{result.sheet_count} 个</Descriptions.Item>
          </Descriptions>

          {(result.sheet_details?.length ?? 0) > 0 && (
            <div style={{ marginTop: 12, maxHeight: 150, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 6, padding: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>Sheet 详情：</Text>
              {result.sheet_details.map((s, i) => (
                <div key={i} style={{ fontSize: 12, color: '#666', lineHeight: '20px' }}>
                  [{s.sheet_name}] {s.department ? `${s.department} — ` : ''}{s.rows} 条
                </div>
              ))}
            </div>
          )}

          {(result.warnings?.length ?? 0) > 0 && (
            <div style={{ marginTop: 12, maxHeight: 200, overflow: 'auto' }}>
              <Text type="warning" style={{ fontSize: 12, fontWeight: 600 }}>
                字段缺失提醒（{result.warnings.length} 条）：
              </Text>
              <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                以下字段为空，建议在系统中补充
              </Text>
              {result.warnings.slice(0, 20).map((w, i) => (
                <div key={i} style={{ fontSize: 12, color: '#fa8c16', marginTop: 4, lineHeight: '18px' }}>
                  [{w.sheet}] 第{w.row}行：{w.message}
                </div>
              ))}
              {result.warnings.length > 20 && (
                <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                  ... 还有 {result.warnings.length - 20} 条类似提醒
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
