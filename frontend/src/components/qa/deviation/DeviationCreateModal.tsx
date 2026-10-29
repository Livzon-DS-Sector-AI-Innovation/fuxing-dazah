'use client'

import { useEffect, useRef, useState, type ClipboardEvent } from 'react'
import { App, Form, Modal } from 'antd'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { createDeviation, uploadDeviationAttachment } from '@/actions/qa-deviation'
import {
  DeviationReportFields,
  reportFormInitialValues,
  reportFormToPayload,
  useQaDepartments,
  type ReportFormValues,
} from './DeviationReportFields'
import {
  DEVIATION_MAX_PHOTOS,
  DeviationPhotoPicker,
  acceptPhotoFiles,
  photoUploadName,
  releasePendingPhotos,
  type PendingPhoto,
} from './DeviationPhotoPicker'
import { actionError } from './shared'

/** QA 登记偏差：保存后自动生成 DE 编号并跳转到详情页继续调查；可一并携带现场照片。 */
export function DeviationCreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { message } = App.useApp()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<ReportFormValues>()
  const departments = useQaDepartments()
  const [submitting, setSubmitting] = useState(false)
  const [photos, setPhotos] = useState<PendingPhoto[]>([])
  // null=不在照片上传阶段；数字=正在上传第几张，用于 okText 进度提示。
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null)

  // 弹窗内容由 destroyOnHidden 销毁，但本组件由台账页常驻渲染（DeviationLedgerPage），
  // 卸载 cleanup 只在离开页面时兜底；取消关闭必须显式释放未提交照片的 blob URL。
  const photosRef = useRef(photos)
  useEffect(() => {
    photosRef.current = photos
  }, [photos])
  useEffect(() => () => releasePendingPhotos(photosRef.current), [])

  const handleCancel = () => {
    releasePendingPhotos(photos)
    setPhotos([])
    onClose()
  }

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    if (submitting) return
    const files = Array.from(event.clipboardData?.files ?? []).filter((file) =>
      file.type.startsWith('image/'),
    )
    if (files.length === 0) return
    // 剪贴板同时带文字（如从 Word/微信复制图文）时不拦截，否则正文会被吞掉
    if (!event.clipboardData?.getData('text/plain').trim()) {
      event.preventDefault()
    }
    const { next, errors } = acceptPhotoFiles(photos, files)
    errors.forEach((text) => message.warning(text))
    if (next.length !== photos.length) setPhotos(next)
  }

  const handleOk = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      const result = await createDeviation(reportFormToPayload(values, departments))
      if (!result.success || !result.data) {
        message.error(actionError(result))
        return
      }
      const detail = result.data
      let failed = 0
      let firstError: string | null = null
      for (let index = 0; index < photos.length; index += 1) {
        setUploadingIndex(index + 1)
        const formData = new FormData()
        formData.append('file', photos[index].file, photoUploadName(photos[index].file))
        try {
          const uploaded = await uploadDeviationAttachment(detail.id, formData)
          if (!uploaded.success) {
            failed += 1
            firstError ??= uploaded.error
          }
        } catch {
          // 传输层失败（server action 网络中断）同样计入失败：偏差本体已落库，
          // 不能让弹窗停留在可再次提交的状态，否则会重复创建记录。
          failed += 1
          firstError ??= '网络错误'
        }
      }
      if (failed > 0) {
        // 偏差本体已落库不回滚；draft 状态在详情页附件区仍可补传
        message.warning(
          `偏差 ${detail.deviation_no} 已登记，但 ${failed} 张照片上传失败（${firstError ?? '请稍后重试'}），可在详情页附件区补传`,
        )
      } else {
        message.success(`偏差 ${detail.deviation_no} 已登记${photos.length ? '（含现场照片）' : ''}`)
      }
      releasePendingPhotos(photos)
      setPhotos([])
      form.resetFields()
      onClose()
      // revalidatePath 只清 Next 缓存；React Query 的台账缓存要显式失效。
      void queryClient.invalidateQueries({ queryKey: ['qa', 'deviations'] })
      router.push(`/qa/deviation/${detail.id}`)
    } finally {
      setSubmitting(false)
      setUploadingIndex(null)
    }
  }

  return (
    <Modal
      title="登记偏差"
      open={open}
      onCancel={handleCancel}
      onOk={handleOk}
      okText={uploadingIndex != null ? `上传照片中 (${uploadingIndex}/${photos.length})…` : '登记并生成编号'}
      cancelText="取消"
      confirmLoading={submitting}
      maskClosable={!submitting}
      keyboard={!submitting}
      cancelButtonProps={{ disabled: submitting }}
      width={880}
      destroyOnHidden
      styles={{ body: { maxHeight: 'calc(100vh - 240px)', overflowY: 'auto', paddingRight: 4 } }}
    >
      <div onPaste={handlePaste}>
        <Form form={form} layout="vertical" initialValues={reportFormInitialValues()} style={{ marginTop: 12 }}>
          <DeviationReportFields departments={departments} />
          <Form.Item
            label={`现场照片（可选，最多 ${DEVIATION_MAX_PHOTOS} 张，支持拖拽 / 粘贴）`}
            style={{ marginTop: 24, marginBottom: 0 }}
          >
            <DeviationPhotoPicker value={photos} onChange={setPhotos} disabled={submitting} />
          </Form.Item>
        </Form>
      </div>
    </Modal>
  )
}
