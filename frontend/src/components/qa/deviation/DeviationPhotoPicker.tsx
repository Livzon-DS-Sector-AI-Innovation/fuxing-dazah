'use client'

import { App, Image, Upload } from 'antd'
import { CloseOutlined, PictureOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { photoOverlayButtonStyle } from './shared'

/** 与后端 `_ATTACHMENT_MIME` 的图片子集对齐（jpg/jpeg/png）。 */
export const PHOTO_ACCEPT = '.jpg,.jpeg,.png'
export const PHOTO_MAX_BYTES = 20 * 1024 * 1024
export const DEVIATION_MAX_PHOTOS = 9

const MIME_EXTENSION: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
}

/** 提交前暂存在浏览器里的现场照片；url 是 objectURL，移除/提交后要 revoke。 */
export interface PendingPhoto {
  uid: string
  file: File
  url: string
}

/** 单张预检；返回错误文案或 null。IM 拖出的图 type 可能为空，扩展名兜底；服务端仍按扩展名+魔数终裁。 */
export function validatePhotoFile(file: File): string | null {
  const label = file.name || '粘贴的截图'
  const typeOk = file.type === 'image/jpeg' || file.type === 'image/png'
  const extensionOk = /\.(jpe?g|png)$/i.test(file.name)
  if (!typeOk && !extensionOk) {
    return `${label}：现场照片仅支持 JPG、PNG`
  }
  if (file.size > PHOTO_MAX_BYTES) {
    return `${label}：单张不能超过 20MB`
  }
  return null
}

/** IM 拖出/粘贴的图片常无规范文件名，而后端按扩展名校验；有合法扩展名保留原名，否则按 MIME 补名（含随机尾防同秒重名）。 */
export function photoUploadName(file: File): string {
  if (/\.(jpe?g|png)$/i.test(file.name)) return file.name
  const extension = MIME_EXTENSION[file.type] ?? 'png'
  const stamp = `${dayjs().format('YYYYMMDD-HHmmss')}-${Math.random().toString(36).slice(2, 5)}`
  return `现场照片-${stamp}.${extension}`
}

export function acceptPhotoFiles(
  current: PendingPhoto[],
  incoming: File[],
): { next: PendingPhoto[]; errors: string[] } {
  const errors: string[] = []
  const next = [...current]
  for (const file of incoming) {
    if (next.length >= DEVIATION_MAX_PHOTOS) {
      errors.push(`最多 ${DEVIATION_MAX_PHOTOS} 张现场照片，已忽略多余文件`)
      break
    }
    const problem = validatePhotoFile(file)
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

export function releasePendingPhotos(items: PendingPhoto[]): void {
  items.forEach((item) => URL.revokeObjectURL(item.url))
}

interface Props {
  value: PendingPhoto[]
  onChange: (next: PendingPhoto[]) => void
  disabled?: boolean
}

const { Dragger } = Upload

/** 现场照片选择器：点选或拖入（含 IM 直接拖图）虚线区；粘贴由弹窗层捕获后经 acceptPhotoFiles 喂入同一状态。 */
export function DeviationPhotoPicker({ value, onChange, disabled }: Props) {
  const { message } = App.useApp()

  const addFiles = (files: File[]) => {
    const { next, errors } = acceptPhotoFiles(value, files)
    errors.forEach((text) => message.warning(text))
    if (next.length !== value.length) onChange(next)
  }

  const remove = (uid: string) => {
    const target = value.find((item) => item.uid === uid)
    if (target) URL.revokeObjectURL(target.url)
    onChange(value.filter((item) => item.uid !== uid))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {value.length > 0 && (
        <Image.PreviewGroup>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {value.map((item) => (
              <div
                key={item.uid}
                style={{ position: 'relative', width: 64, height: 64, borderRadius: 8, overflow: 'hidden' }}
              >
                <Image
                  src={item.url}
                  alt={item.file.name || '现场照片'}
                  width={64}
                  height={64}
                  style={{ objectFit: 'cover' }}
                />
                {!disabled && (
                  <button
                    type="button"
                    aria-label="移除照片"
                    onClick={() => remove(item.uid)}
                    style={photoOverlayButtonStyle}
                  >
                    <CloseOutlined style={{ fontSize: 10 }} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </Image.PreviewGroup>
      )}
      <Dragger
        multiple
        accept={PHOTO_ACCEPT}
        showUploadList={false}
        disabled={disabled || value.length >= DEVIATION_MAX_PHOTOS}
        beforeUpload={(file, fileList) => {
          // 多选/多拖时 antd 对每个文件各调一次并传入整批；只在首个文件时处理整批
          if (fileList[0] === file) addFiles(fileList as File[])
          return Upload.LIST_IGNORE
        }}
      >
        <p className="ant-upload-drag-icon">
          <PictureOutlined />
        </p>
        <p className="ant-upload-text">{value.length >= DEVIATION_MAX_PHOTOS ? '已达 9 张上限' : '拖入或点击上传现场照片'}</p>
        <p className="ant-upload-hint">支持从微信 / 飞书直接拖图或 Ctrl+V 粘贴截图；JPG / PNG，单张 ≤ 20MB</p>
      </Dragger>
    </div>
  )
}
