'use client'

import { useState } from 'react'
import { App, Button, Image, Timeline, Tooltip, Upload } from 'antd'
import { CloseOutlined, DeleteOutlined, DownloadOutlined, PaperClipOutlined, UploadOutlined } from '@ant-design/icons'
import { deleteDeviationAttachment, uploadDeviationAttachment } from '@/actions/qa-deviation'
import { deviationAttachmentUrl } from '@/lib/api/qa-deviation'
import { DEVIATION_ACTION_LABEL, DEVIATION_STATUS_LABEL, type DeviationDetail, type DeviationStatus, type StatusLog } from '@/types/qa-deviation'
import { SectionCard } from './DeviationSections'
import { actionError, fmtBytes, fmtDateTime, photoOverlayButtonStyle } from './shared'

const ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png'

/** 图片附件走缩略图墙；与后端 _ATTACHMENT_MIME 的图片白名单一致。 */
const IMAGE_MIME = new Set(['image/jpeg', 'image/png'])

/** 偏差附件：批记录复印件、校验标签照片、COA 等；PDF/图片可直接预览。 */
export function AttachmentsCard({
  detail,
  canEdit,
  onChanged,
}: {
  detail: DeviationDetail
  canEdit: boolean
  onChanged: () => void
}) {
  const { message, modal } = App.useApp()
  const [uploading, setUploading] = useState(false)

  const upload = async (file: File) => {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await uploadDeviationAttachment(detail.id, formData)
      if (!result.success) {
        message.error(actionError(result))
        return
      }
      message.success(`已上传 ${file.name}`)
      onChanged()
    } finally {
      setUploading(false)
    }
  }

  const remove = (attachmentId: string, fileName: string) => {
    modal.confirm({
      title: '删除附件',
      content: `确认删除「${fileName}」？删除后无法恢复。`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        const result = await deleteDeviationAttachment(detail.id, attachmentId)
        if (!result.success) {
          message.error(actionError(result))
          return
        }
        message.success('附件已删除')
        onChanged()
      },
    })
  }

  const images = detail.attachments.filter((attachment) => IMAGE_MIME.has(attachment.mime_type))
  const others = detail.attachments.filter((attachment) => !IMAGE_MIME.has(attachment.mime_type))

  return (
    <SectionCard
      title="附件"
      hint="设备使用记录、培训资料、校验标签、批记录复印件、COA 等"
      extra={
        canEdit && (
          <Upload
            accept={ACCEPT}
            maxCount={1}
            showUploadList={false}
            beforeUpload={(file) => {
              void upload(file as File)
              return false
            }}
          >
            <Button size="small" icon={<UploadOutlined />} loading={uploading}>上传附件</Button>
          </Upload>
        )
      }
    >
      {detail.attachments.length === 0 ? (
        <div style={{ color: '#a4a097', fontSize: 13 }}>暂无附件（支持 PDF、Word、Excel、JPG、PNG，单个 ≤ 20MB）</div>
      ) : (
        <>
          {images.length > 0 && (
            <Image.PreviewGroup>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: others.length > 0 ? 12 : 0 }}>
                {images.map((attachment) => (
                  <Tooltip
                    key={attachment.id}
                    title={`${attachment.file_name} · ${fmtBytes(attachment.file_size)} · ${attachment.uploaded_by_name || '—'} · ${fmtDateTime(attachment.created_at)}`}
                  >
                    <div style={{ position: 'relative', width: 80, height: 80, borderRadius: 8, overflow: 'hidden' }}>
                      <Image
                        src={deviationAttachmentUrl(detail.id, attachment.id)}
                        alt={attachment.file_name}
                        width={80}
                        height={80}
                        loading="lazy"
                        style={{ objectFit: 'cover' }}
                      />
                      <a
                        href={deviationAttachmentUrl(detail.id, attachment.id, true)}
                        aria-label="下载照片"
                        style={{ ...photoOverlayButtonStyle, left: 2, right: 'auto', top: 'auto', bottom: 2 }}
                      >
                        <DownloadOutlined style={{ fontSize: 10 }} />
                      </a>
                      {canEdit && (
                        <button
                          type="button"
                          aria-label="删除照片"
                          onClick={() => remove(attachment.id, attachment.file_name)}
                          style={photoOverlayButtonStyle}
                        >
                          <CloseOutlined style={{ fontSize: 10 }} />
                        </button>
                      )}
                    </div>
                  </Tooltip>
                ))}
              </div>
            </Image.PreviewGroup>
          )}
          {others.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {others.map((attachment) => (
                <div
                  key={attachment.id}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', border: '1px solid #ede9e4', borderRadius: 8 }}
                >
                  <PaperClipOutlined style={{ color: '#787671' }} />
                  <a
                    href={deviationAttachmentUrl(detail.id, attachment.id)}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: '#0075de', fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {attachment.file_name}
                  </a>
                  <span style={{ color: '#787671', fontSize: 12, whiteSpace: 'nowrap' }}>
                    {fmtBytes(attachment.file_size)} · {attachment.uploaded_by_name || '—'} · {fmtDateTime(attachment.created_at)}
                  </span>
                  <Button
                    type="text"
                    size="small"
                    icon={<DownloadOutlined />}
                    href={deviationAttachmentUrl(detail.id, attachment.id, true)}
                    aria-label="下载"
                  />
                  {canEdit && (
                    <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => remove(attachment.id, attachment.file_name)} aria-label="删除" />
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </SectionCard>
  )
}

const ACTION_COLOR: Record<string, string> = {
  create: '#787671',
  start_investigation: '#0075de',
  submit_assessment: '#dd5b00',
  close: '#1aae39',
  extend: '#7b3ff2',
  start: '#0075de',
  complete: '#7b3ff2',
  start_evaluation: '#dd5b00',
}

function statusLabel(value: string | null): string | null {
  if (!value) return null
  return (DEVIATION_STATUS_LABEL as Record<string, string>)[value as DeviationStatus] ?? value
}

/** 流转历史：谁在何时做了什么，替代纸质表上的逐级签字。 */
export function TimelineCard({ logs, statusLabels }: { logs: StatusLog[]; statusLabels?: Record<string, string> }) {
  const resolve = (value: string | null) => (statusLabels ? (value ? statusLabels[value] ?? value : null) : statusLabel(value))
  return (
    <SectionCard title="流转历史" hint="每个动作记录操作人与时间">
      {logs.length === 0 ? (
        <div style={{ color: '#a4a097', fontSize: 13 }}>暂无记录</div>
      ) : (
        <Timeline
          items={logs.map((log) => {
            const from = resolve(log.from_status)
            const to = resolve(log.to_status)
            const transition = from && to && from !== to ? `${from} → ${to}` : to
            return {
              key: log.id,
              color: ACTION_COLOR[log.action] ?? '#787671',
              content: (
                <div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600 }}>{DEVIATION_ACTION_LABEL[log.action] ?? log.action}</span>
                    {transition && <span style={{ color: '#787671', fontSize: 12 }}>{transition}</span>}
                  </div>
                  <div style={{ color: '#787671', fontSize: 12 }}>
                    {log.operator_name || '系统'} · {fmtDateTime(log.created_at)}
                  </div>
                  {log.comment && <div style={{ marginTop: 4, color: '#37352f', whiteSpace: 'pre-wrap' }}>{log.comment}</div>}
                </div>
              ),
            }
          })}
        />
      )}
    </SectionCard>
  )
}
