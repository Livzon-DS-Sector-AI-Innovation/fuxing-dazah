'use client'

import { useEffect, useRef, useState, type ClipboardEvent } from 'react'
import { App, Button, Form, Image, Input, Segmented } from 'antd'
import { usePathname } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { submitFeedback, uploadFeedbackAttachment } from '@/actions/feedback'
import { feedbackKeys } from '@/lib/api/feedback'
import {
  FEEDBACK_MAX_ATTACHMENTS,
  FEEDBACK_TYPE_OPTIONS,
  type FeedbackType,
} from '@/types/feedback'
import { FeedbackTypeTag } from './FeedbackCells'
import {
  FeedbackImagePicker,
  acceptImageFiles,
  releasePendingImages,
  uploadFileName,
  type PendingImage,
} from './FeedbackImagePicker'

interface FormValues {
  type: FeedbackType
  content: string
}

/**
 * 提交反馈表单：类型 + 内容 + 可选截图（最多 3 张，可点选/拖放/直接粘贴），
 * 当前页面路径自动附带。用户提交后不能修改内容，因此提交前弹确认框回显。
 * 截图在反馈创建成功后逐张上传；个别失败不回滚反馈，提示到「我的反馈」补传。
 */
export function FeedbackForm({ onSubmitted }: { onSubmitted?: () => void }) {
  const { message, modal } = App.useApp()
  const pathname = usePathname()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [images, setImages] = useState<PendingImage[]>([])

  // Drawer 用 destroyOnHidden，关闭时会直接卸载表单；离开前释放未提交截图的 blob URL。
  const imagesRef = useRef(images)
  useEffect(() => {
    imagesRef.current = images
  }, [images])
  useEffect(() => () => releasePendingImages(imagesRef.current), [])

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const files = Array.from(event.clipboardData?.files ?? []).filter((file) =>
      file.type.startsWith('image/'),
    )
    if (files.length === 0) return
    // 剪贴板同时带文字（如从 Word/微信复制图文）时不拦截，否则正文会被吞掉
    if (!event.clipboardData?.getData('text/plain').trim()) {
      event.preventDefault()
    }
    const { next, errors } = acceptImageFiles(images, files)
    errors.forEach((text) => message.warning(text))
    if (next.length !== images.length) setImages(next)
  }

  const uploadImages = async (
    feedbackId: string,
  ): Promise<{ failed: number; error: string | null }> => {
    let failed = 0
    let error: string | null = null
    for (const image of images) {
      const formData = new FormData()
      formData.append('file', image.file, uploadFileName(image.file))
      const result = await uploadFeedbackAttachment(feedbackId, formData)
      if (!result.success) {
        failed += 1
        error ??= result.error
      }
    }
    return { failed, error }
  }

  const doSubmit = async (values: FormValues) => {
    setSubmitting(true)
    try {
      const result = await submitFeedback({
        type: values.type,
        content: values.content,
        page_path: pathname,
      })
      if (!result.success || !result.data) {
        message.error(result.success ? '提交失败，请重试' : result.error)
        return
      }
      const { failed, error } = images.length
        ? await uploadImages(result.data.id)
        : { failed: 0, error: null }
      if (failed > 0) {
        // 反馈已处理时后端会 409 冻结截图，直接透出真实原因，避免引导到不可用的补传入口
        message.warning(`已提交，但 ${failed} 张截图上传失败：${error ?? '请稍后重试'}`)
      } else {
        message.success(images.length ? '感谢反馈，已提交（含截图）' : '感谢反馈，已提交')
      }
      releasePendingImages(images)
      setImages([])
      form.resetFields()
      void queryClient.invalidateQueries({ queryKey: feedbackKeys.all })
      onSubmitted?.()
    } finally {
      setSubmitting(false)
    }
  }

  const handleFinish = (values: FormValues) => {
    modal.confirm({
      title: '确认提交反馈？',
      width: 520,
      content: (
        <div className="flex flex-col gap-2 pt-1">
          <div>
            <FeedbackTypeTag type={values.type} />
          </div>
          <div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-[var(--color-surface)] p-3 text-[13px] text-[var(--color-ink)]">
            {values.content}
          </div>
          {images.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[12px] text-[var(--color-slate)]">附 {images.length} 张截图</span>
              <div className="flex gap-1">
                {images.map((image) => (
                  <Image
                    key={image.uid}
                    src={image.url}
                    alt=""
                    width={28}
                    height={28}
                    preview={false}
                    style={{ objectFit: 'cover', borderRadius: 4 }}
                  />
                ))}
              </div>
            </div>
          )}
          <p className="m-0 text-[12px] text-[var(--color-slate)]">
            提交后不可修改内容或撤回；将附带当前页面路径 <code>{pathname}</code>。
          </p>
        </div>
      ),
      okText: '确认提交',
      cancelText: '返回修改',
      onOk: () => doSubmit(values),
    })
  }

  return (
    <div onPaste={handlePaste}>
      <Form<FormValues>
        form={form}
        layout="vertical"
        initialValues={{ type: 'bug' }}
        onFinish={handleFinish}
        requiredMark={false}
      >
        <Form.Item name="type" label="反馈类型" rules={[{ required: true, message: '请选择反馈类型' }]}>
          <Segmented block options={FEEDBACK_TYPE_OPTIONS} />
        </Form.Item>
        <Form.Item
          name="content"
          label="反馈内容"
          rules={[
            { required: true, whitespace: true, message: '请填写反馈内容' },
            { max: 2000, message: '最多 2000 字' },
          ]}
        >
          <Input.TextArea
            rows={6}
            maxLength={2000}
            showCount
            placeholder="描述你遇到的问题、希望优化的体验或想要的新功能……"
          />
        </Form.Item>
        <Form.Item
          label={`截图（可选，最多 ${FEEDBACK_MAX_ATTACHMENTS} 张，支持直接 Ctrl+V 粘贴）`}
        >
          <FeedbackImagePicker value={images} onChange={setImages} disabled={submitting} />
        </Form.Item>
        <p className="m-0 mb-3 text-[12px] text-[var(--color-slate)]">
          提交时会自动附带当前页面路径 <code>{pathname}</code>，方便定位问题。
        </p>
        <div className="flex justify-end">
          <Button type="primary" htmlType="submit" loading={submitting}>
            提交反馈
          </Button>
        </div>
      </Form>
    </div>
  )
}
