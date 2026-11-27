'use client'

// 招聘岗位信息表单弹窗：给一个岗位保存「岗位职责 / 任职要求」，配置一次长期复用。
// 两处复用——招聘岗位信息页逐个岗位配置；新建岗位需求时选中的岗位还没配置，就地配置。

import { useEffect, useState } from 'react'
import { Alert, App, Button, Form, Input, Modal, Spin } from 'antd'
import { fetchRecruitmentPositionInfo, saveRecruitmentPositionInfo } from '@/actions/hr'
import { useUnsavedConfirm } from '@/hooks/hr'
import type { RecruitmentPositionInfo } from '@/types/hr'

/** 要配置的岗位（岗位库里的一行） */
export interface RecruitmentPositionTarget {
  id: string
  department: string
  name: string
}

interface FormValues {
  duties?: string
  requirements?: string
}

interface RecruitmentPositionInfoModalProps {
  open: boolean
  /** 打开时必须有值；关闭后调用方先别清，否则淡出动画期间弹窗里是空的 */
  position: RecruitmentPositionTarget | null
  /** 没有招聘管理权限时只读：只能看，不能保存 */
  readOnly?: boolean
  onClose: () => void
  /** 保存成功后回调，带上保存后的内容（调用方可直接拿去回填别的表单） */
  onSaved?: (info: RecruitmentPositionInfo) => void
}

const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback)

export default function RecruitmentPositionInfoModal(props: RecruitmentPositionInfoModalProps) {
  // 换了岗位就整块重建：表单、未保存标记、已读取的内容都从零开始，不用写复位逻辑
  return <ModalBody key={props.position?.id ?? 'none'} {...props} />
}

function ModalBody({ open, position, readOnly = false, onClose, onSaved }: RecruitmentPositionInfoModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [loading, setLoading] = useState(open)
  const [loadFailed, setLoadFailed] = useState(false)
  const [retryTick, setRetryTick] = useState(0)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const positionId = position?.id

  // 每次打开都重新读一遍：别处可能刚改过。请求写在 effect 内部
  useEffect(() => {
    if (!open || !positionId) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetchRecruitmentPositionInfo(positionId)
        if (cancelled) return
        form.setFieldsValue({ duties: res.data.duties ?? '', requirements: res.data.requirements ?? '' })
        setLoadFailed(false)
      } catch {
        if (!cancelled) setLoadFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, positionId, form, retryTick])

  // 关闭动画结束后复位：下次打开重新读取、重新转圈，未保存标记也不带到下一次
  const handleAfterOpenChange = (isVisible: boolean) => {
    if (isVisible) return
    setDirty(false)
    setLoading(true)
    setLoadFailed(false)
  }

  // 只在弹窗打开且确有改动时拦，放弃/保存后复位 dirty
  const guardClose = useUnsavedConfirm(dirty && open, () => {
    setDirty(false)
    onClose()
  })

  const submit = async () => {
    if (!position) return
    // 两项都不是必填，校验不会失败；取值即可
    const values = form.getFieldsValue() as FormValues
    setSaving(true)
    try {
      const res = await saveRecruitmentPositionInfo(position.id, {
        duties: values.duties?.trim() || null,
        requirements: values.requirements?.trim() || null,
      })
      message.success(`已保存「${position.name}」的招聘岗位信息`)
      setDirty(false)
      onSaved?.(res.data)
      onClose()
    } catch (err) {
      message.error(errText(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const unreachable = loading || loadFailed
  const footer = readOnly
    ? <Button onClick={guardClose}>关闭</Button>
    : undefined

  return (
    <Modal
      title="招聘岗位信息"
      open={open}
      width={720}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: unreachable }}
      onOk={() => { void submit() }}
      onCancel={guardClose}
      afterOpenChange={handleAfterOpenChange}
      footer={footer}
      mask={{ closable: false }}
      destroyOnHidden
    >
      {position && (
        <div className="mt-4 space-y-4">
          <div>
            <div className="text-[16px] font-semibold leading-tight text-[var(--color-ink)]">{position.name}</div>
            <div className="mt-0.5 text-[13px] text-[var(--color-steel)]">{position.department}</div>
          </div>

          <Alert
            type="info"
            showIcon
            title="配置一次，长期复用"
            description="新建该岗位的招聘需求时会自动带出下面两段内容，可按当次需要再改。"
          />

          {loadFailed ? (
            <Alert
              type="error"
              showIcon
              title="读取失败"
              description="没读到已保存的内容。直接保存会覆盖原有内容，建议先重试。"
              action={<Button size="small" onClick={() => { setLoadFailed(false); setLoading(true); setRetryTick((n) => n + 1) }}>重试</Button>}
            />
          ) : loading ? (
            <div className="flex items-center gap-2 text-[13px] text-[var(--color-steel)]">
              <Spin size="small" /> 正在读取已保存的内容…
            </div>
          ) : null}

          <Form<FormValues>
            form={form}
            layout="vertical"
            disabled={readOnly || unreachable}
            onValuesChange={() => setDirty(true)}
          >
            <Form.Item
              name="duties"
              label="岗位职责"
              extra="新建招聘需求时填入「岗位职责」，也是胜任度分析报告的依据。"
            >
              <Input.TextArea
                rows={8}
                autoSize={{ minRows: 8, maxRows: 16 }}
                maxLength={20000}
                placeholder={'例如：\n1. 负责原料药生产车间的日常管理，包括排班调度、生产进度跟踪\n2. 监督车间 GMP 合规执行，确保生产过程符合相关标准\n3. …'}
              />
            </Form.Item>
            <Form.Item
              name="requirements"
              label="任职要求"
              extra="新建招聘需求时填入「岗位要求」，AI 简历初筛按它打分。"
            >
              <Input.TextArea
                rows={8}
                autoSize={{ minRows: 8, maxRows: 16 }}
                maxLength={20000}
                placeholder={'例如：\n1. 本科及以上学历，药学、化学、制药工程等相关专业\n2. 5 年以上相关工作经验\n3. …'}
              />
            </Form.Item>
          </Form>
        </div>
      )}
    </Modal>
  )
}
