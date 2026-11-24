'use client'

// 台账 Excel 导入弹窗（两步预检式）：上传 → 预检（统计+重复/错误明细）→
// 选择「跳过重复」或「覆盖重复」后落库。四个台账页共用，骨架参照
// meter/LedgerImportModal，交互按 HR 预检确认流程改造。

import { useState } from 'react'
import { App, Alert, Button, Descriptions, Modal, Space, Typography, Upload } from 'antd'
import { DownloadOutlined, InboxOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import type { LedgerImportLedger, LedgerImportPrecheck, LedgerImportResult } from '@/types/hr'
import { downloadLedgerTemplate, precheckLedgerImport, commitLedgerImport } from '@/actions/hr'
import { downloadBase64File } from '@/lib/hr'

const { Dragger } = Upload
const { Text } = Typography

interface Props {
  open: boolean
  ledger: LedgerImportLedger
  label: string
  onClose: () => void
  /** 导入成功后回调（一般用于刷新列表） */
  onSuccess?: () => void
}

export function LedgerImportModal({ open, ledger, label, onClose, onSuccess }: Props) {
  const { message } = App.useApp()
  const [file, setFile] = useState<File | null>(null)
  const [checking, setChecking] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [precheck, setPrecheck] = useState<LedgerImportPrecheck | null>(null)
  const [result, setResult] = useState<LedgerImportResult | null>(null)

  const handleDownloadTemplate = async () => {
    setDownloading(true)
    try {
      const { base64, filename } = await downloadLedgerTemplate(ledger)
      downloadBase64File(base64, filename)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '下载模板失败')
    } finally {
      setDownloading(false)
    }
  }

  const handlePrecheck = async () => {
    if (!file) {
      message.warning('请先选择文件')
      return
    }
    setChecking(true)
    try {
      const res = await precheckLedgerImport(ledger, file)
      setPrecheck(res.data)
      if (res.data.error_count > 0) {
        message.warning(`文件有 ${res.data.error_count} 行格式问题，这些行将被跳过`)
      }
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '预检失败')
    } finally {
      setChecking(false)
    }
  }

  const handleCommit = async (mode: 'overwrite' | 'skip') => {
    if (!file) return
    setCommitting(true)
    try {
      const res = await commitLedgerImport(ledger, file, mode)
      setResult(res.data)
      message.success(res.message || '导入完成')
      onSuccess?.()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '导入失败')
    } finally {
      setCommitting(false)
    }
  }

  const handleClose = () => {
    setFile(null)
    setPrecheck(null)
    setResult(null)
    setChecking(false)
    setCommitting(false)
    onClose()
  }

  const uploadProps: UploadProps = {
    beforeUpload: (f) => {
      const ext = f.name.split('.').pop()?.toLowerCase()
      if (ext !== 'xlsx') {
        message.error('仅支持 .xlsx 格式（旧版 .xls 请先用 Excel/WPS 另存为 .xlsx）')
        return Upload.LIST_IGNORE
      }
      if (f.size > 50 * 1024 * 1024) {
        message.error('文件大小不能超过 50MB')
        return Upload.LIST_IGNORE
      }
      setFile(f)
      setPrecheck(null) // 换文件后需重新预检
      setResult(null)
      return false // 阻止自动上传
    },
    onRemove: () => {
      setFile(null)
      setPrecheck(null)
      setResult(null)
    },
    maxCount: 1,
    fileList: file ? [{ uid: '-1', name: file.name, status: 'done' as const }] : [],
  }

  const hasDuplicates = (precheck?.duplicate_count ?? 0) > 0

  const footer = result ? (
    <Button type="primary" onClick={handleClose}>完成</Button>
  ) : precheck ? (
    <Space>
      <Button onClick={handleClose}>取消</Button>
      {hasDuplicates ? (
        <>
          <Button
            loading={committing}
            disabled={precheck.new_count === 0}
            onClick={() => handleCommit('skip')}
          >
            跳过重复，导入新增 {precheck.new_count} 条
          </Button>
          <Button
            type="primary"
            loading={committing}
            disabled={precheck.new_count + precheck.duplicate_count === 0}
            onClick={() => handleCommit('overwrite')}
          >
            覆盖重复导入 {precheck.new_count + precheck.duplicate_count} 条
          </Button>
        </>
      ) : (
        <Button
          type="primary"
          loading={committing}
          disabled={precheck.new_count === 0}
          onClick={() => handleCommit('skip')}
        >
          确认导入 {precheck.new_count} 条
        </Button>
      )}
    </Space>
  ) : (
    <Space>
      <Button onClick={handleClose}>取消</Button>
      <Button type="primary" loading={checking} disabled={!file} onClick={handlePrecheck}>
        上传预检
      </Button>
    </Space>
  )

  return (
    <Modal
      title={`导入${label}`}
      open={open}
      onCancel={handleClose}
      width={680}
      footer={footer}
      destroyOnHidden
    >
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<DownloadOutlined />} loading={downloading} onClick={handleDownloadTemplate}>
          下载导入模板
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          请按模板固定列头填写；第二行灰色为示例，导入前请删除
        </Text>
      </Space>

      <Dragger {...uploadProps}>
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此区域</p>
        <p className="ant-upload-hint">支持 .xlsx 格式，文件大小不超过 50MB</p>
      </Dragger>

      {precheck && !result && (
        <div style={{ marginTop: 16 }}>
          <Descriptions column={4} size="small" bordered>
            <Descriptions.Item label="新增">{precheck.new_count} 条</Descriptions.Item>
            <Descriptions.Item label="与库中重复">{precheck.duplicate_count} 条</Descriptions.Item>
            <Descriptions.Item label="格式错误">{precheck.error_count} 条</Descriptions.Item>
            <Descriptions.Item label="越权跳过">{precheck.skipped_scope} 条</Descriptions.Item>
          </Descriptions>

          {hasDuplicates && (
            <div style={{ marginTop: 12, maxHeight: 160, overflow: 'auto' }}>
              <Text type="warning" style={{ fontSize: 12, fontWeight: 600 }}>
                重复明细（查重口径：{precheck.dup_key_display}，前 {precheck.duplicates.length} 条
                {precheck.duplicate_count > precheck.duplicates.length ? `，共 ${precheck.duplicate_count} 条` : ''}）：
              </Text>
              {precheck.duplicates.map((d, i) => (
                <div key={i} style={{ fontSize: 12, color: '#fa8c16', marginTop: 4, lineHeight: '18px' }}>
                  第 {d.row} 行：{d.key}
                </div>
              ))}
              <Text type="secondary" style={{ fontSize: 12 }}>
                「覆盖重复」将以 Excel 非空值更新已有记录；「跳过重复」仅导入新增行
              </Text>
            </div>
          )}

          {precheck.error_count > 0 && (
            <div style={{ marginTop: 12, maxHeight: 140, overflow: 'auto' }}>
              <Text type="danger" style={{ fontSize: 12, fontWeight: 600 }}>
                错误明细（这些行将被跳过，前 {precheck.errors.length} 条）：
              </Text>
              {precheck.errors.map((e, i) => (
                <div key={i} style={{ fontSize: 12, color: '#cf1322', marginTop: 4, lineHeight: '18px' }}>
                  {e}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 16 }}>
          <Alert
            type={result.errors.length > 0 ? 'warning' : 'success'}
            showIcon
            title={`导入完成：新增 ${result.created} 条${result.updated ? `，覆盖更新 ${result.updated} 条` : ''}${result.skipped ? `，跳过重复 ${result.skipped} 条` : ''}${result.skipped_scope ? `，越权跳过 ${result.skipped_scope} 条` : ''}${result.errors.length ? `，失败 ${result.errors.length} 条` : ''}`}
          />
          {result.errors.length > 0 && (
            <div style={{ marginTop: 8, maxHeight: 140, overflow: 'auto' }}>
              {result.errors.map((e, i) => (
                <div key={i} style={{ fontSize: 12, color: '#cf1322', marginTop: 4, lineHeight: '18px' }}>
                  {e}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
