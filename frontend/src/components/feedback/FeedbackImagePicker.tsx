'use client'

import { App, Image, Upload } from 'antd'
import { CloseOutlined, PlusOutlined } from '@ant-design/icons'
import {
  FEEDBACK_ATTACHMENT_ACCEPT,
  FEEDBACK_ATTACHMENT_MAX_BYTES,
  FEEDBACK_ATTACHMENT_MIME_TYPES,
  FEEDBACK_MAX_ATTACHMENTS,
} from '@/types/feedback'

/** 提交前暂存在浏览器里的截图；url 是 objectURL，移除/提交后要 revoke。 */
export interface PendingImage {
  uid: string
  file: File
  url: string
}

const MIME_EXTENSION: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
  'image/gif': 'gif',
}

/** 单个文件预检；返回错误文案或 null。服务端仍按魔数终裁。 */
export function validateImageFile(file: File): string | null {
  const label = file.name || '剪贴板图片'
  if (!(FEEDBACK_ATTACHMENT_MIME_TYPES as readonly string[]).includes(file.type)) {
    return `${label}：仅支持 PNG、JPG、WEBP、GIF`
  }
  if (file.size > FEEDBACK_ATTACHMENT_MAX_BYTES) {
    return `${label}：单张不能超过 5MB`
  }
  return null
}

/** 剪贴板图片可能没有文件名；后端按扩展名校验，这里按 MIME 补一个。 */
export function uploadFileName(file: File): string {
  const extension = MIME_EXTENSION[file.type] ?? 'png'
  if (file.name && /\.(png|jpe?g|webp|gif)$/i.test(file.name)) return file.name
  return `screenshot.${extension}`
}

export function acceptImageFiles(
  current: PendingImage[],
  incoming: File[],
): { next: PendingImage[]; errors: string[] } {
  const errors: string[] = []
  const next = [...current]
  for (const file of incoming) {
    if (next.length >= FEEDBACK_MAX_ATTACHMENTS) {
      errors.push(`最多 ${FEEDBACK_MAX_ATTACHMENTS} 张截图，已忽略多余文件`)
      break
    }
    const problem = validateImageFile(file)
    if (problem) {
      errors.push(problem)
      continue
    }
    next.push({
      uid: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      url: URL.createObjectURL(file),
    })
  }
  return { next, errors }
}

export function releasePendingImages(items: PendingImage[]): void {
  items.forEach((item) => URL.revokeObjectURL(item.url))
}

interface Props {
  value: PendingImage[]
  onChange: (next: PendingImage[]) => void
  disabled?: boolean
}

/** 截图选择器：点选/拖放到「+」瓦片；粘贴由表单层捕获后经 acceptImageFiles 喂入同一状态。 */
export function FeedbackImagePicker({ value, onChange, disabled }: Props) {
  const { message } = App.useApp()

  const addFiles = (files: File[]) => {
    const { next, errors } = acceptImageFiles(value, files)
    errors.forEach((text) => message.warning(text))
    if (next.length !== value.length) onChange(next)
  }

  const remove = (uid: string) => {
    const target = value.find((item) => item.uid === uid)
    if (target) URL.revokeObjectURL(target.url)
    onChange(value.filter((item) => item.uid !== uid))
  }

  const canAdd = !disabled && value.length < FEEDBACK_MAX_ATTACHMENTS

  return (
    <div className="flex flex-wrap gap-2">
      <Image.PreviewGroup>
        {value.map((item) => (
          <div
            key={item.uid}
            className="relative h-16 w-16 overflow-hidden rounded-lg border border-[var(--color-hairline)]"
          >
            <Image
              src={item.url}
              alt={item.file.name || '截图'}
              width={64}
              height={64}
              style={{ objectFit: 'cover' }}
            />
            {!disabled && (
              <button
                type="button"
                aria-label="移除截图"
                onClick={() => remove(item.uid)}
                className="absolute right-0.5 top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white"
              >
                <CloseOutlined style={{ fontSize: 10 }} />
              </button>
            )}
          </div>
        ))}
      </Image.PreviewGroup>
      {canAdd && (
        <Upload
          accept={FEEDBACK_ATTACHMENT_ACCEPT}
          multiple
          showUploadList={false}
          beforeUpload={(file, fileList) => {
            // 多选时 antd 对每个文件各调一次并传入整批；只在首个文件时处理整批
            if (fileList[0] === file) addFiles(fileList)
            return Upload.LIST_IGNORE
          }}
        >
          <button
            type="button"
            className="flex h-16 w-16 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[var(--color-hairline-strong)] bg-[var(--color-surface)] text-[12px] text-[var(--color-slate)]"
          >
            <PlusOutlined />
            截图
          </button>
        </Upload>
      )}
    </div>
  )
}
