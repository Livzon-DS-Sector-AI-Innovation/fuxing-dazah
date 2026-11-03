'use client'

import { useState } from 'react'
import { App, Image, Upload } from 'antd'
import { CloseOutlined, LoadingOutlined, PlusOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { deleteFeedbackAttachment, uploadFeedbackAttachment } from '@/actions/feedback'
import { feedbackAttachmentUrl, feedbackKeys } from '@/lib/api/feedback'
import {
  FEEDBACK_ATTACHMENT_ACCEPT,
  FEEDBACK_MAX_ATTACHMENTS,
  type Feedback,
} from '@/types/feedback'
import { uploadFileName, validateImageFile } from './FeedbackImagePicker'

interface Props {
  feedback: Feedback
  /** 本人在未处理前可补传。 */
  allowUpload?: boolean
  /** 本人在未处理前可删；管理员随时可删（处置误传的敏感内容）。 */
  allowDelete?: boolean
  size?: number
}

/** 已存截图的缩略图条：点开放大；按权限显示删除 × 与「+」补传瓦片（即传即刷）。 */
export function FeedbackAttachmentStrip({
  feedback,
  allowUpload = false,
  allowDelete = false,
  size = 44,
}: Props) {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const [busy, setBusy] = useState(false)
  const attachments = feedback.attachments ?? []

  const refresh = () => void queryClient.invalidateQueries({ queryKey: feedbackKeys.all })

  const upload = async (files: File[]) => {
    const room = FEEDBACK_MAX_ATTACHMENTS - attachments.length
    if (files.length > room) {
      message.warning(`最多 ${FEEDBACK_MAX_ATTACHMENTS} 张截图，已忽略多余文件`)
    }
    setBusy(true)
    try {
      for (const file of files.slice(0, room)) {
        const problem = validateImageFile(file)
        if (problem) {
          message.warning(problem)
          continue
        }
        const formData = new FormData()
        formData.append('file', file, uploadFileName(file))
        const result = await uploadFeedbackAttachment(feedback.id, formData)
        if (!result.success) message.error(result.error)
      }
      refresh()
    } finally {
      setBusy(false)
    }
  }

  const remove = (attachmentId: string, fileName: string) => {
    modal.confirm({
      title: '删除这张截图？',
      content: fileName,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const result = await deleteFeedbackAttachment(feedback.id, attachmentId)
        if (!result.success) {
          message.error(result.error)
          return
        }
        message.success('已删除')
        refresh()
      },
    })
  }

  if (attachments.length === 0 && !allowUpload) {
    return <span className="text-[var(--color-slate)]">—</span>
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Image.PreviewGroup>
        {attachments.map((attachment) => (
          <div
            key={attachment.id}
            className="relative overflow-hidden rounded-md border border-[var(--color-hairline)]"
            style={{ width: size, height: size }}
          >
            <Image
              src={feedbackAttachmentUrl(feedback.id, attachment.id)}
              alt={attachment.file_name}
              width={size}
              height={size}
              style={{ objectFit: 'cover' }}
            />
            {allowDelete && (
              <button
                type="button"
                aria-label="删除截图"
                disabled={busy}
                onClick={() => remove(attachment.id, attachment.file_name)}
                className="absolute right-0 top-0 flex h-4 w-4 items-center justify-center rounded-bl-md bg-black/60 text-white"
              >
                <CloseOutlined style={{ fontSize: 9 }} />
              </button>
            )}
          </div>
        ))}
      </Image.PreviewGroup>
      {allowUpload && attachments.length < FEEDBACK_MAX_ATTACHMENTS && (
        <Upload
          accept={FEEDBACK_ATTACHMENT_ACCEPT}
          multiple
          showUploadList={false}
          disabled={busy}
          beforeUpload={(file, fileList) => {
            if (fileList[0] === file) void upload(fileList)
            return Upload.LIST_IGNORE
          }}
        >
          <button
            type="button"
            aria-label="补传截图"
            disabled={busy}
            className="flex items-center justify-center rounded-md border border-dashed border-[var(--color-hairline-strong)] bg-[var(--color-surface)] text-[var(--color-slate)]"
            style={{ width: size, height: size }}
          >
            {busy ? <LoadingOutlined /> : <PlusOutlined />}
          </button>
        </Upload>
      )}
    </div>
  )
}
