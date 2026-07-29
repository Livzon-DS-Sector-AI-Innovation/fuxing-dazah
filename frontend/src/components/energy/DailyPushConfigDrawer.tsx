'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space, Switch, TimePicker } from 'antd'
import dayjs from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import {
  createDailyPushConfig,
  updateDailyPushConfig,
  getDailyPushConfigById,
  getDailyPushPersonnelCandidates,
} from '@/actions/energy'
import { fetchEnergyDevicesClient } from '@/lib/api/energy'
import type {
  CreateDailyPushConfigInput,
  UpdateDailyPushConfigInput,
  EnergyPersonnelCandidate,
  EnergyDeviceConfig,
} from '@/types/energy'

interface DailyPushConfigDrawerProps {
  onRefresh?: () => void
}

const DEVICE_LABELS: Record<string, string> = {
  solar_device_id: '光伏发电设备',
  pressure_device_id: '蒸汽差压发电设备',
  rto1_gas_device_id: '一期RTO用气设备',
  rto2_gas_device_id: '二期RTO用气设备',
  rto1_elec_device_id: '一期RTO用电设备',
  rto2_elec_device_id: '二期RTO用电设备',
}

export function DailyPushConfigDrawer({ onRefresh }: DailyPushConfigDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)

  const {
    dailyPushConfigDrawerOpen,
    dailyPushConfigDrawerMode,
    dailyPushConfigDrawerId,
    closeDailyPushConfigDrawer,
  } = useEnergyStore()

  const isEdit = dailyPushConfigDrawerMode === 'edit'

  // 人员候选列表
  const [candidates, setCandidates] = useState<EnergyPersonnelCandidate[]>([])
  // 设备列表
  const [deviceList, setDeviceList] = useState<EnergyDeviceConfig[]>([])

  const loadCandidates = useCallback(async () => {
    try {
      const data = await getDailyPushPersonnelCandidates()
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
    if (!dailyPushConfigDrawerOpen) return
    loadDevices()
    loadCandidates()
  }, [dailyPushConfigDrawerOpen, loadDevices, loadCandidates])

  useEffect(() => {
    if (!dailyPushConfigDrawerOpen) return
    const timer = setTimeout(() => {
      if (isEdit && dailyPushConfigDrawerId) {
        getDailyPushConfigById(dailyPushConfigDrawerId)
          .then((config) => {
            form.setFieldsValue({
              name: config.name,
              notify_time: config.notify_time ? dayjs(config.notify_time, 'HH:mm') : undefined,
              notify_users: config.notify_users?.map((u) => u.feishu_open_id) || [],
              solar_device_id: config.solar_device_id || undefined,
              pressure_device_id: config.pressure_device_id || undefined,
              rto1_gas_device_id: config.rto1_gas_device_id || undefined,
              rto2_gas_device_id: config.rto2_gas_device_id || undefined,
              rto1_elec_device_id: config.rto1_elec_device_id || undefined,
              rto2_elec_device_id: config.rto2_elec_device_id || undefined,
              is_enabled: config.is_enabled,
              remark: config.remark || undefined,
            })
          })
          .catch(() => {
            message.error('获取推送配置失败')
          })
      } else {
        form.resetFields()
        form.setFieldsValue({ is_enabled: true, notify_users: [] })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [dailyPushConfigDrawerOpen, dailyPushConfigDrawerId, isEdit, form, message])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      // 从 candidates 映射 open_id → { name, feishu_open_id }
      const selectedOpenIds: string[] = values.notify_users || []
      const notifyUsers = selectedOpenIds
        .map((oid: string) => {
          const c = candidates.find((c) => c.feishu_open_id === oid)
          return c ? { name: c.name, feishu_open_id: c.feishu_open_id } : null
        })
        .filter(Boolean) as { name: string; feishu_open_id: string }[]

      const deviceFields = {
        solar_device_id: values.solar_device_id || undefined,
        pressure_device_id: values.pressure_device_id || undefined,
        rto1_gas_device_id: values.rto1_gas_device_id || undefined,
        rto2_gas_device_id: values.rto2_gas_device_id || undefined,
        rto1_elec_device_id: values.rto1_elec_device_id || undefined,
        rto2_elec_device_id: values.rto2_elec_device_id || undefined,
      }

      if (isEdit && dailyPushConfigDrawerId) {
        const data: UpdateDailyPushConfigInput = {
          name: values.name,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          notify_users: notifyUsers,
          ...deviceFields,
          is_enabled: values.is_enabled,
          remark: values.remark,
        }
        await updateDailyPushConfig(dailyPushConfigDrawerId, data)
        message.success('更新成功')
      } else {
        const data: CreateDailyPushConfigInput = {
          name: values.name,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          notify_users: notifyUsers,
          ...deviceFields,
          is_enabled: values.is_enabled ?? true,
          remark: values.remark,
        }
        await createDailyPushConfig(data)
        message.success('创建成功')
      }
      closeDailyPushConfigDrawer()
      onRefresh?.()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  // 设备下拉选项
  const deviceOptions = deviceList.map((d) => ({
    label: `${d.device_name}（${d.workshop} · ${d.platform_device_code}）`,
    value: d.id,
  }))

  // 人员下拉选项
  const personnelOptions = candidates.map((c) => ({
    label: `${c.name}${c.department ? `（${c.department}）` : ''}`,
    value: c.feishu_open_id,
  }))

  return (
    <Drawer
      title={isEdit ? '编辑能源总耗推送配置' : '新建能源总耗推送配置'}
      size={520}
      open={dailyPushConfigDrawerOpen}
      onClose={closeDailyPushConfigDrawer}
      destroyOnHidden
      styles={{
        header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
        body: { padding: '24px' },
      }}
      extra={
        <Space>
          <Button
            onClick={closeDailyPushConfigDrawer}
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
          <Input placeholder="如：每日能源报告推送" maxLength={200} style={{ height: 44 }} />
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

        <Form.Item name="notify_time" label="每日定时推送时间" help="留空则仅支持手动推送">
          <TimePicker
            format="HH:mm"
            placeholder="选择推送时间（可选）"
            style={{ width: '100%', height: 44 }}
            minuteStep={1}
          />
        </Form.Item>

        {/* 清洁能源设备绑定 */}
        <div style={{ marginBottom: 16, padding: '12px 16px', background: '#f6f3ff', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 12, color: '#37352f', fontSize: 14 }}>⚡ 清洁能源设备绑定</div>
          <Form.Item name="solar_device_id" label="光伏发电设备" help="选择光伏发电对应的数据源设备">
            <Select
              allowClear
              placeholder="选择光伏发电设备"
              options={deviceOptions}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
          <Form.Item name="pressure_device_id" label="蒸汽差压发电设备" help="选择蒸汽差压发电对应的数据源设备">
            <Select
              allowClear
              placeholder="选择蒸汽差压发电设备"
              options={deviceOptions}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>
        </div>

        {/* RTO 设备绑定 */}
        <div style={{ marginBottom: 16, padding: '12px 16px', background: '#fff7ed', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 12, color: '#37352f', fontSize: 14 }}>🔥 RTO 设备绑定</div>
          {['rto1_gas_device_id', 'rto2_gas_device_id', 'rto1_elec_device_id', 'rto2_elec_device_id'].map((fieldKey) => (
            <Form.Item key={fieldKey} name={fieldKey} label={DEVICE_LABELS[fieldKey]} help={`选择${DEVICE_LABELS[fieldKey]}对应的数据源设备`}>
              <Select
                allowClear
                placeholder={`选择${DEVICE_LABELS[fieldKey]}`}
                options={deviceOptions}
                showSearch
                filterOption={(input, option) =>
                  (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
                }
              />
            </Form.Item>
          ))}
        </div>

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
