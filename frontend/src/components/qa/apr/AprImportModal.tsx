'use client'

import { useState } from 'react'
import { App, Alert, Button, Modal, Radio, Space, Table, Typography, Upload } from 'antd'
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd'
import { aprImportTemplateUrl, importAprSectionValues } from '@/lib/api/qa-apr'
import type { AprImportCellError, AprImportMode, AprImportResult } from '@/types/qa-apr'

const { Dragger } = Upload
const { Text } = Typography

const MAX_SIZE_MB = 10

interface AprImportModalProps {
  open: boolean
  onClose: () => void
  onImported: () => void
  sectionId: string | null
  sectionName: string | null
  year: number
}

const MODE_HINTS: Record<AprImportMode, string> = {
  merge: '文件里非空的格才写入，空白格保留系统已有值；分批、分列导入都安全，不会误删数据。',
  replace: '与录入页保存同语义：文件中出现的批次整批覆盖，空白格即删除，必填列空白会整单拒绝。',
}

/** Excel 批量导入录入值：下载模板 → 双模式选择 → 上传 → 行级错误报告。 */
export function AprImportModal({
  open,
  onClose,
  onImported,
  sectionId,
  sectionName,
  year,
}: AprImportModalProps) {
  const { message } = App.useApp()
  const [mode, setMode] = useState<AprImportMode>('merge')
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<AprImportResult | null>(null)

  const handleUpload = async () => {
    if (!sectionId || fileList.length === 0) return
    setUploading(true)
    try {
      const res = await importAprSectionValues(
        sectionId,
        year,
        mode,
        fileList[0].originFileObj as File
      )
      if (res.ok) {
        message.success(
          `已导入 ${res.batches} 个批次（其中 ${res.registered} 批为新登记）、${res.cells} 个数据格`
        )
        onImported()
        reset()
        onClose()
      } else {
        setResult(res)
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导入失败')
    } finally {
      setUploading(false)
    }
  }

  const reset = () => {
    setFileList([])
    setResult(null)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const errorColumns = [
    {
      title: '行号',
      dataIndex: 'row',
      key: 'row',
      width: 70,
      render: (row: number) => (row === 0 ? '文件' : row),
    },
    { title: '列', dataIndex: 'column', key: 'column', width: 120 },
    { title: '原因', dataIndex: 'message', key: 'message' },
  ]

  return (
    <Modal
      title={`导入 Excel${sectionName ? `：${sectionName}` : ''}（${year} 年度）`}
      open={open}
      onCancel={handleClose}
      footer={
        <Space>
          <Button
            icon={<DownloadOutlined />}
            href={sectionId ? aprImportTemplateUrl(sectionId, year) : undefined}
            disabled={!sectionId}
          >
            下载模板
          </Button>
          <Button onClick={handleClose}>关闭</Button>
          <Button
            type="primary"
            loading={uploading}
            disabled={!sectionId || fileList.length === 0}
            onClick={() => void handleUpload()}
          >
            开始导入
          </Button>
        </Space>
      }
      width={720}
      destroyOnHidden
    >
      {result ? (
        <div>
          <Alert
            type="warning"
            title={`导入被拒绝：共 ${result.total_errors} 处错误，未写入任何数据`}
            description="按下表修复 Excel 后重新上传；所有错误修完才会一次性写入。"
            style={{ marginBottom: 12 }}
          />
          <Table<AprImportCellError>
            size="small"
            rowKey={(r) => `${r.row}-${r.column ?? ''}-${r.message}`}
            columns={errorColumns}
            dataSource={result.errors}
            pagination={false}
            scroll={{ y: 260 }}
          />
          {result.errors.length < result.total_errors && (
            <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              还有 {result.total_errors - result.errors.length} 条错误未展示，修复已列出的条目后重传即可继续暴露。
            </Text>
          )}
          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <Button onClick={reset}>重新选择文件</Button>
          </div>
        </div>
      ) : (
        <div>
          <Alert
            type="info"
            title="按当前模板段生成列头，新批号会自动登记为本段批次"
            description="数值列填数字或列注允许的文字结果（如 未检出）；文字列填文字；留空格在「非空覆盖」下保留系统已有值。文件中未登记的批号自动创建批次（结果会报告新登记数），任一格不合法都会整单拒绝并给出定位。"
            style={{ marginBottom: 16 }}
          />
          <Text strong style={{ display: 'block', marginBottom: 6 }}>
            覆盖方式
          </Text>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value as AprImportMode)}
            options={[
              { label: '非空覆盖（默认）', value: 'merge' },
              { label: '整批替换', value: 'replace' },
            ]}
            optionType="button"
          />
          <Text type="secondary" style={{ display: 'block', marginTop: 6, marginBottom: 16, fontSize: 12 }}>
            {MODE_HINTS[mode]}
          </Text>
          <Dragger
            accept=".xlsx"
            maxCount={1}
            fileList={fileList}
            beforeUpload={(file) => {
              if (file.size > MAX_SIZE_MB * 1024 * 1024) {
                message.error(`文件大小不能超过 ${MAX_SIZE_MB}MB`)
                return Upload.LIST_IGNORE
              }
              setFileList([{ uid: '-1', name: file.name, originFileObj: file as never }])
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
