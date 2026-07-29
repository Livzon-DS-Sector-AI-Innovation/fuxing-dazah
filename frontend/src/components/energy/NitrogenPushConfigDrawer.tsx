'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space, Switch, TimePicker, InputNumber } from 'antd'
import dayjs from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import {
  createNitrogenPushConfig,
  updateNitrogenPushConfig,
  getNitrogenPushConfigById,
  getNitrogenPushPersonnelCandidates,
} from '@/actions/energy'
import { fetchEnergyDevicesClient } from '@/lib/api/energy'
import type {
  CreateNitrogenPushConfigInput,
  UpdateNitrogenPushConfigInput,
  EnergyPersonnelCandidate,
  EnergyDeviceConfig,
} from '@/types/energy'

interface NitrogenPushConfigDrawerProps {
  onRefresh?: () => void
}

export function NitrogenPushConfigDrawer({ onRefresh }: NitrogenPushConfigDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)

  const {
    nitrogenPushConfigDrawerOpen,
    nitrogenPushConfigDrawerMode,
    nitrogenPushConfigDrawerId,
    closeNitrogenPushConfigDrawer,
  } = useEnergyStore()

  const isEdit = nitrogenPushConfigDrawerMode === 'edit'

  const [candidates, setCandidates] = useState<EnergyPersonnelCandidate[]>([])
  const [deviceList, setDeviceList] = useState<EnergyDeviceConfig[]>([])

  const loadCandidates = useCallback(async () => {
    try {
      const data = await getNitrogenPushPersonnelCandidates()
      setCandidates(data)
    } catch {
      // 静默失败
    }
  }, [])

  const loadDevices = useCallback(async () => {
    try {
      const result = await fetchEnergyDevicesClient({ is_enabled: true, page_size: 100 })
      setDeviceList(result.items || [])
    } catch (err) {
      console.error('获取设备列表失败:', err)
      message.error('获取设备列表失败：' + (err instanceof Error ? err.message : String(err)))
    }
  }, [message])

  useEffect(() => {
    if (!nitrogenPushConfigDrawerOpen) return
    loadDevices()
    loadCandidates()
  }, [nitrogenPushConfigDrawerOpen, loadDevices, loadCandidates])

  useEffect(() => {
    if (!nitrogenPushConfigDrawerOpen) return
    const timer = setTimeout(() => {
      if (isEdit && nitrogenPushConfigDrawerId) {
        getNitrogenPushConfigById(nitrogenPushConfigDrawerId)
          .then((config) => {
            form.setFieldsValue({
              name: config.name,
              notify_time: config.notify_time ? dayjs(config.notify_time, 'HH:mm') : undefined,
              notify_users: config.notify_users?.map((u) => u.feishu_open_id) || [],
              nitrogen_device_ids: config.nitrogen_device_ids || [],
              monthly_guaranteed_consumption: config.monthly_guaranteed_consumption,
              is_enabled: config.is_enabled,
              remark: config.remark || undefined,
            })
          })
          .catch(() => {
            message.error('获取推送配置失败')
          })
      } else {
        form.resetFields()
        form.setFieldsValue({ is_enabled: true, notify_users: [], nitrogen_device_ids: [] })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [nitrogenPushConfigDrawerOpen, nitrogenPushConfigDrawerId, isEdit, form, message])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      const selectedOpenIds: string[] = values.notify_users || []
      const notifyUsers = selectedOpenIds
        .map((oid: string) => {
          const c = candidates.find((c) => c.feishu_open_id === oid)
          return c ? { name: c.name, feishu_open_id: c.feishu_open_id } : null
        })
        .filter(Boolean) as { name: string; feishu_open_id: string }[]

      const nitrogenDeviceIds: string[] = values.nitrogen_device_ids || []

      if (isEdit && nitrogenPushConfigDrawerId) {
        const data: UpdateNitrogenPushConfigInput = {
          name: values.name,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          notify_users: notifyUsers,
          nitrogen_device_ids: nitrogenDeviceIds,
          monthly_guaranteed_consumption: Number(values.monthly_guaranteed_consumption),
          is_enabled: values.is_enabled,
          remark: values.remark,
        }
        await updateNitrogenPushConfig(nitrogenPushConfigDrawerId, data)
        message.success('更新成功')
      } else {
        const data: CreateNitrogenPushConfigInput = {
          name: values.name,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          notify_users: notifyUsers,
          nitrogen_device_ids: nitrogenDeviceIds,
          monthly_guaranteed_consumption: Number(values.monthly_guaranteed_consumption),
          is_enabled: values.is_enabled ?? true,
          remark: values.remark,
        }
        await createNitrogenPushConfig(data)
        message.success('创建成功')
      }
      closeNitrogenPushConfigDrawer()
      onRefresh?.()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const deviceOptions = deviceList.map((d) => ({
    label: `${d.device_name}（${d.workshop} · ${d.platform_device_code}）`,
    value: d.id,
  }))

  const personnelOptions = candidates.map((c) => ({
    label: `${c.name}${c.department ? `（${c.department}）` : ''}`,
    value: c.feishu_open_id,
  }))

  return (
    <Drawer
      title={isEdit ? '编辑氮气月度推送配置' : '新建氮气月度推送配置'}
      size={520}
      open={nitrogenPushConfigDrawerOpen}
      onClose={closeNitrogenPushConfigDrawer}
      destroyOnHidden
      styles={{
        header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
        body: { padding: '24px' },
      }}
      extra={
        <Space>
          <Button
            onClick={closeNitrogenPushConfigDrawer}
            style={{ color: '#37352f', borderColor: '#c8c4be', borderRadius: 8, height: 36, fontSize: 14, fontWeight: 500 }}
          >
            取消
          </Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={handleSubmit}
            style={{ background: '#5645d4', borderColor: '#5645d4', borderRadius: 8, height: 36, fontSize: 14, fontWeight: 500, boxShadow: 'none' }}
          >
            {isEdit ? '保存' : '创建'}
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入配置名称' }]}>
          <Input placeholder="如：氮气月度用量报告推送" maxLength={200} style={{ height: 44 }} />
        </Form.Item>

        <Form.Item name="notify_users" label="推送接收人">
          <Select
            mode="multiple"
            placeholder="选择推送接收人"
            options={personnelOptions}
            showSearch
            filterOption={(input, option) =>
              (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
            }
            style={{ width: '100%' }}
          />
        </Form.Item>

        <Form.Item name="notify_time" label="每月定时推送时间" help="留空则仅支持手动推送">
          <TimePicker
            format="HH:mm"
            placeholder="选择推送时间（可选）"
            style={{ width: '100%', height: 44 }}
            minuteStep={1}
          />
        </Form.Item>

        <div style={{ marginBottom: 16, padding: '12px 16px', background: '#f0f5ff', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 12, color: '#37352f', fontSize: 14 }}>🧪 氮气设备绑定</div>
          <Form.Item
            name="nitrogen_device_ids"
            label="氮气设备"
            help="选择用于统计月度氮气用量的设备（可多选）"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="选择氮气设备"
              options={deviceOptions}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
        </div>

        <Form.Item
          name="monthly_guaranteed_consumption"
          label="月度保底消费量"
          rules={[{ required: true, message: '请输入月度保底消费量' }]}
        >
          <InputNumber
            min={0}
            placeholder="请输入月度保底消费量"
            style={{ width: '100%', height: 44 }}
            precision={4}
          />
        </Form.Item>

        <Form.Item name="remark" label="备注">
          <Input.TextArea placeholder="备注信息（可选）" maxLength={500} rows={3} />
        </Form.Item>

        <Form.Item name="is_enabled" label="启用配置" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
