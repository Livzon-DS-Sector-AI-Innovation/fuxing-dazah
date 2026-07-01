'use client'

import { useState } from 'react'
import { App, Modal, Upload, Button, Space, Table, Typography, Alert } from 'antd'
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd'
import { downloadImportTemplate, importEquipments, type ImportResult, type ImportRowError } from '@/actions/equipment'

const { Dragger } = Upload
const { Text } = Typography

interface EquipmentImportModalProps {
  open: boolean
  onClose: () => void
  onImported: () => void
}

export function EquipmentImportModal({ open, onClose, onImported }: EquipmentImportModalProps) {
  const { message } = App.useApp()
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [result, setResult] = useState<ImportResult | null>(null)
  const [downloading, setDownloading] = useState(false)

  const handleDownloadTemplate = async () => {
    setDownloading(true)
    try {
      const base64 = await downloadImportTemplate()
      const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0))
      const blob = new Blob([bytes], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = '设备台账导入模板.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载模板失败')
    } finally {
      setDownloading(false)
    }
  }

  const handleUpload = async () => {
    if (fileList.length === 0) return
    setUploading(true)
    setResult(null)
    try {
      const formData = new FormData()
      formData.append('file', fileList[0].originFileObj as File)
      const res = await importEquipments(formData)
      setResult(res)
      if (res.imported > 0) {
        message.success(`成功导入 ${res.imported} 条记录`)
        onImported()
      }
    } catch (err: any) {
      message.error(err?.message || '导入失败')
    } finally {
      setUploading(false)
    }
  }

  const handleClose = () => {
    setFileList([])
    setResult(null)
    onClose()
  }

  const errorColumns = [
    { title: '行号', dataIndex: 'row', key: 'row', width: 70 },
    { title: '说明', dataIndex: 'message', key: 'message', ellipsis: true },
  ]

  const renderResultTable = (title: string, items: ImportRowError[], color: string) => {
    if (!items.length) return null
    return (
      <div style={{ marginTop: 12 }}>
        <Text strong style={{ color }}>{title}（{items.length}）</Text>
        <Table
          size="small"
          rowKey="row"
          columns={errorColumns}
          dataSource={items}
          pagination={false}
          style={{ marginTop: 4 }}
        />
      </div>
    )
  }

  return (
    <Modal
      title="导入设备台账"
      open={open}
      onCancel={handleClose}
      footer={
        <Space>
          <Button icon={<DownloadOutlined />} loading={downloading} onClick={handleDownloadTemplate}>
            下载模板
          </Button>
          <Button onClick={handleClose}>关闭</Button>
          <Button
            type="primary"
            loading={uploading}
            disabled={fileList.length === 0}
            onClick={handleUpload}
          >
            开始导入
          </Button>
        </Space>
      }
      width={640}
      destroyOnHidden
    >
      {result ? (
        <div>
          <Alert
            type={result.errors.length > 0 ? 'warning' : 'success'}
            title={`导入完成：成功 ${result.imported} 条，跳过 ${result.skipped} 条`}
            style={{ marginBottom: 12 }}
          />
          {renderResultTable('错误', result.errors, '#e03131')}
          {renderResultTable('警告', result.warnings, '#dd5b00')}
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <Button
              onClick={() => {
                setFileList([])
                setResult(null)
              }}
            >
              继续导入
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Alert
            type="info"
            title="请使用下载的模板文件填写数据后上传"
            description="必填列：设备编号、设备名称、设备分类、设备位置、归属部门、负责人。分类/位置/部门需在系统中存在，否则跳过。"
            style={{ marginBottom: 16 }}
          />
          <Dragger
            accept=".xlsx"
            maxCount={1}
            fileList={fileList}
            beforeUpload={(file) => {
              setFileList([{ uid: '-1', name: file.name, originFileObj: file as any }])
              return false
            }}
            onRemove={() => setFileList([])}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p style={{ color: '#787671' }}>点击或拖拽 .xlsx 文件到此区域上传</p>
          </Dragger>
        </div>
      )}
    </Modal>
  )
}
