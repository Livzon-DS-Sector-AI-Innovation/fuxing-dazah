'use client'

// 定时任务配置编辑抽屉：启停 / 执行时间 / 发送对象（飞书群聊单选）/ 补发截止
// 「发送对象」初始值 = DB 覆写，缺省时回退生效值（env / 代码默认），保证所见即生效

import { useCallback, useEffect, useState } from 'react'
import {
  App,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Switch,
} from 'antd'

import { fetchFeishuGroups, fetchFeishuPersons, updateScheduledTask } from '@/actions/safety'
import type { FeishuGroup, FeishuPerson, ScheduledTask } from '@/types/safety'
import { WEEK_OPTIONS, UI } from './schedulerConfigConstants'

/** 发送对象空值选项（存储为 null = 无推送目标） */
const NONE_TARGET = '__none__'

interface ScheduledTaskEditDrawerProps {
  open: boolean
  task: ScheduledTask | null
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  enabled: boolean
  hour: number
  minute: number
  dow: number[]
  target_chat_id?: string
  target_chat_name?: string
  retry_until_hour?: number | null
  retry_until_minute?: number | null
}

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: UI.slate,
  marginBottom: 6,
}

export default function ScheduledTaskEditDrawer({ open, task, onClose, onSaved }: ScheduledTaskEditDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm<FormValues>()
  const [groups, setGroups] = useState<FeishuGroup[]>([])
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupsError, setGroupsError] = useState<string | null>(null)
  const [persons, setPersons] = useState<FeishuPerson[]>([])
  const [personsLoading, setPersonsLoading] = useState(false)
  const [personsError, setPersonsError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const loadGroups = useCallback(async () => {
    setGroupsLoading(true)
    setGroupsError(null)
    try {
      const res = await fetchFeishuGroups()
      if (res.code >= 200 && res.code < 300 && res.data) {
        setGroups(res.data.items ?? [])
        if (res.data.warning) setGroupsError(res.data.warning)
      } else {
        setGroupsError(res.message || '加载群聊失败')
      }
    } finally {
      setGroupsLoading(false)
    }
  }, [])

  const loadPersons = useCallback(async () => {
    setPersonsLoading(true)
    setPersonsError(null)
    try {
      const res = await fetchFeishuPersons()
      if (res.code >= 200 && res.code < 300 && res.data) {
        setPersons(res.data ?? [])
      } else {
        setPersonsError(res.message || '加载人员失败')
      }
    } finally {
      setPersonsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open || !task) return
    void loadGroups()
    void loadPersons()
    const dow = task.dow != null && task.dow >= 0 && task.dow <= 6 ? [task.dow] : []
    form.setFieldsValue({
      enabled: task.enabled,
      hour: task.hour ?? 8,
      minute: task.minute ?? 0,
      dow,
      // 发送对象唯一来源：后端 DB 配置；无目标时显示「不推送」空值选项
      target_chat_id: task.target_chat_id ?? NONE_TARGET,
      target_chat_name: task.target_chat_name ?? undefined,
      retry_until_hour: task.retry_until_hour ?? undefined,
      retry_until_minute: task.retry_until_minute ?? undefined,
    })
  }, [open, task, form, loadGroups, loadPersons])

  const handleSubmit = async () => {
    if (!task) return
    const values = await form.validateFields()
    // 空值选项（__none__）→ 后端存 null = 无推送目标
    const isNone = values.target_chat_id === NONE_TARGET
    setSubmitting(true)
    try {
      const res = await updateScheduledTask(task.job_name, {
        enabled: values.enabled,
        hour: values.hour ?? null,
        minute: values.minute ?? null,
        dow: values.dow && values.dow.length === 1 ? values.dow[0] : null,
        target_chat_id: isNone ? null : (values.target_chat_id ?? null),
        target_chat_name: isNone ? null : (values.target_chat_name ?? null),
        retry_until_hour: values.retry_until_hour ?? null,
        retry_until_minute: values.retry_until_minute ?? null,
      })
      if (res.code >= 200 && res.code < 300) {
        message.success('定时任务配置已保存，下个调度周期生效')
        onSaved()
        onClose()
      } else {
        message.error(res.message || '保存失败')
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  // 发送对象类型：个人（DM）/ 群聊；无目标时取任务默认类型
  const personMode = (task?.target_type ?? (task?.target_chat_id ?? '').startsWith('ou_') ? 'person' : 'group') === 'person'
  const noneLabel = personMode ? '不推送（无目标）' : '不推送群聊（无目标）'
  const targetOptions = personMode
    ? [
        { value: NONE_TARGET, label: noneLabel },
        ...persons.map((p) => ({
          value: p.open_id,
          label: p.department ? `${p.name}（${p.department}）` : p.name,
        })),
      ]
    : [
        { value: NONE_TARGET, label: noneLabel },
        ...groups.map((g) => ({
          value: g.chat_id,
          label: g.name ? `${g.name}（${g.chat_id}）` : g.chat_id,
        })),
      ]

  return (
    <Drawer
      title={<span style={{ fontSize: 15, fontWeight: 600, color: UI.ink }}>{task ? `编辑定时任务 · ${task.job_name}` : '编辑定时任务'}</span>}
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        {/* ── 启停 ── */}
        <Form.Item name="enabled" label="启用任务" valuePropName="checked" style={{ marginBottom: 20 }}>
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>

        {/* ── 执行时间 ── */}
        <div style={fieldLabelStyle}>执行时间</div>
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Form.Item name="hour" noStyle rules={[{ required: true, message: '请输入小时' }]}>
              <InputNumber min={0} max={23} style={{ width: '100%' }} placeholder="时" />
            </Form.Item>
          </div>
          <div style={{ width: 14, display: 'flex', alignItems: 'center', justifyContent: 'center', color: UI.muted, fontSize: 14 }}>:</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Form.Item name="minute" noStyle rules={[{ required: true, message: '请输入分钟' }]}>
              <InputNumber min={0} max={59} style={{ width: '100%' }} placeholder="分" />
            </Form.Item>
          </div>
          <div style={{ flex: 2, minWidth: 0 }}>
            <Form.Item name="dow" noStyle>
              <Checkbox.Group
                options={WEEK_OPTIONS}
                style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}
              />
            </Form.Item>
          </div>
        </div>

        {/* ── 发送对象（群聊 / 个人 DM 按任务类型区分）── */}
        <Form.Item
          name="target_chat_id"
          label={personMode ? '发送对象（个人 DM）' : '发送对象（飞书群聊）'}
          style={{ marginBottom: 8 }}
        >
          <Select
            showSearch
            optionFilterProp="label"
            placeholder={personMode ? '选择接收人（私发卡片将 DM 给该人）' : '选择群聊后保存即生效；可选「不推送群聊」清除目标'}
            loading={personMode ? personsLoading : groupsLoading}
            options={targetOptions}
            onChange={(value?: string) => {
              if (value === NONE_TARGET) {
                form.setFieldValue('target_chat_name', undefined)
                return
              }
              if (personMode) {
                const picked = persons.find((p) => p.open_id === value)
                form.setFieldValue('target_chat_name', picked?.name ?? undefined)
              } else {
                const picked = groups.find((g) => g.chat_id === value)
                form.setFieldValue('target_chat_name', picked?.name ?? undefined)
              }
            }}
            notFoundContent={
              personMode ? (
                personsLoading ? (
                  <Skeleton active paragraph={{ rows: 2 }} />
                ) : personsError ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={personsError} />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到已绑定飞书的用户" />
                )
              ) : groupsLoading ? (
                <Skeleton active paragraph={{ rows: 2 }} />
              ) : groupsError ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={groupsError} />
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="机器人未加入任何群聊" />
              )
            }
          />
        </Form.Item>
        <Form.Item name="target_chat_name" hidden>
          <Input />
        </Form.Item>

        {/* ── 补发截止 ── */}
        <div style={fieldLabelStyle}>补发截止（可选，留空用默认）</div>
        <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Form.Item name="retry_until_hour" noStyle>
              <InputNumber min={0} max={23} style={{ width: '100%' }} placeholder="默认" />
            </Form.Item>
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Form.Item name="retry_until_minute" noStyle>
              <InputNumber min={0} max={59} style={{ width: '100%' }} placeholder="默认" />
            </Form.Item>
          </div>
        </div>
        <div style={{ fontSize: 12, color: UI.muted }}>
          {personMode
            ? '个人卡片将私发（DM）到所选用户；群聊列表来自飞书机器人已加入的群（后端 5 分钟缓存）。'
            : '群聊列表来自飞书机器人已加入的群（后端 5 分钟缓存）。'}
          保存后无需重启服务，下个调度周期生效。
        </div>
      </Form>
    </Drawer>
  )
}
