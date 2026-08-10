'use client'

import { useEffect, useMemo, useState } from 'react'
import { App, Drawer, Form, Input, Select, InputNumber, Button, Space, Switch, TimePicker } from 'antd'
import dayjs from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import { createAlertRule, updateAlertRule, getAlertRuleById } from '@/actions/energy'
import { CreateRuleInput, UpdateRuleInput, MonitorMetric, ThresholdType, AlertLevel, NotifyFrequency, EffectiveTimeType, EnergyTypeMeta } from '@/types/energy'
import { fetchEnabledTypeConfigsClient } from '@/lib/api/energy'

const { TextArea } = Input

interface AlertConfigDrawerProps {
  onRefresh?: () => void
}

const monitorMetricOptions = [
  { label: '瞬时值', value: 'instant' },
  { label: '日累计', value: 'daily_total' },
  { label: '月累计', value: 'monthly_total' },
]

const thresholdTypeOptions = [
  { label: '大于', value: 'greater_than' },
  { label: '小于', value: 'less_than' },
  { label: '等于', value: 'equal' },
]

const alertLevelOptions = [
  { label: '信息', value: 'info' },
  { label: '警告', value: 'warning' },
  { label: '严重', value: 'critical' },
  { label: '紧急', value: 'emergency' },
]

const notifyMethodOptions = [
  { label: '飞书消息', value: 'lark' },
  { label: '邮件', value: 'email' },
  { label: '短信', value: 'sms' },
]

const notifyFrequencyOptions = [
  { label: '仅首次', value: 'first' },
  { label: '每次触发', value: 'every' },
  { label: '每日汇总', value: 'daily_summary' },
]

const effectiveTimeOptions = [
  { label: '全天', value: 'all_day' },
  { label: '自定义时段', value: 'custom' },
]

const DEFAULT_VALUES = {
  energy_type: 'electricity',
  monitor_metric: 'instant' as MonitorMetric,
  threshold_type: 'greater_than' as ThresholdType,
  alert_level: 'warning' as AlertLevel,
  notify_method: ['lark'],
  notify_frequency: 'every' as NotifyFrequency,
  effective_time: 'all_day' as EffectiveTimeType,
  is_enabled: true,
}

export function AlertConfigDrawer({ onRefresh }: AlertConfigDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)

  // 动态能源类型选项
  const [typeConfigs, setTypeConfigs] = useState<EnergyTypeMeta[]>([])

  const energyTypeOptions = useMemo(
    () => typeConfigs.map((c) => ({ label: c.display_name, value: c.type_code })),
    [typeConfigs],
  )

  const {
    alertConfigDrawerOpen,
    alertConfigDrawerMode,
    alertConfigDrawerId,
    closeAlertConfigDrawer,
  } = useEnergyStore()

  const isEdit = alertConfigDrawerMode === 'edit'

  // 监听生效时间，控制自定义时段字段显示
  const effectiveTime = Form.useWatch('effective_time', form)

  useEffect(() => {
    if (!alertConfigDrawerOpen) return
    const timer = setTimeout(() => {
      // 加载能源类型选项
      fetchEnabledTypeConfigsClient().then(configs => {
        const metas: EnergyTypeMeta[] = configs.map(c => ({
          type_code: c.type_code,
          display_name: c.display_name,
          unit: c.unit,
          color: c.color,
          icon: c.icon,
        }))
        setTypeConfigs(metas)
        if (isEdit && alertConfigDrawerId) {
          getAlertRuleById(alertConfigDrawerId)
            .then((rule) => {
              form.setFieldsValue({
                rule_name: rule.rule_name,
                rule_description: rule.rule_description,
                energy_type: rule.energy_type,
                monitor_metric: rule.monitor_metric,
                threshold_type: rule.threshold_type,
                threshold_value: rule.threshold_value,
                alert_level: rule.alert_level,
                notify_method: rule.notify_method,
                notify_frequency: rule.notify_frequency,
                effective_time: rule.effective_time,
                custom_time_start: rule.custom_time_start ? dayjs(rule.custom_time_start, 'HH:mm') : undefined,
                custom_time_end: rule.custom_time_end ? dayjs(rule.custom_time_end, 'HH:mm') : undefined,
                is_enabled: rule.is_enabled,
              })
            })
            .catch(() => {
              message.error('获取规则详情失败')
            })
        } else {
          form.resetFields()
          const defaultType = metas.length > 0 ? metas[0].type_code : undefined
          form.setFieldsValue({
            ...DEFAULT_VALUES,
            energy_type: defaultType,
          })
        }
      }).catch(() => {})
    }, 0)
    return () => clearTimeout(timer)
  }, [alertConfigDrawerOpen, alertConfigDrawerId, isEdit, form, message])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      const customTimeStart = values.custom_time_start ? values.custom_time_start.format('HH:mm') : undefined
      const customTimeEnd = values.custom_time_end ? values.custom_time_end.format('HH:mm') : undefined

      if (isEdit && alertConfigDrawerId) {
        const data: UpdateRuleInput = {
          rule_name: values.rule_name,
          rule_description: values.rule_description || undefined,
          energy_type: values.energy_type,
          monitor_metric: values.monitor_metric,
          threshold_type: values.threshold_type,
          threshold_value: values.threshold_value,
          alert_level: values.alert_level,
          notify_method: values.notify_method,
          notify_frequency: values.notify_frequency,
          effective_time: values.effective_time,
          custom_time_start: customTimeStart,
          custom_time_end: customTimeEnd,
          is_enabled: values.is_enabled,
        }
        await updateAlertRule(alertConfigDrawerId, data)
        message.success('更新成功')
      } else {
        const data: CreateRuleInput = {
          rule_name: values.rule_name,
          rule_description: values.rule_description || undefined,
          energy_type: values.energy_type,
          monitor_metric: values.monitor_metric,
          threshold_type: values.threshold_type,
          threshold_value: values.threshold_value,
          alert_level: values.alert_level,
          notify_method: values.notify_method,
          notify_users: [],
          notify_frequency: values.notify_frequency,
          effective_time: values.effective_time,
          custom_time_start: customTimeStart,
          custom_time_end: customTimeEnd,
          is_enabled: values.is_enabled,
        }
        await createAlertRule(data)
        message.success('创建成功')
      }
      closeAlertConfigDrawer()
      onRefresh?.()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title={isEdit ? '编辑预警规则' : '新建预警规则'}
      size={480}
      open={alertConfigDrawerOpen}
      onClose={closeAlertConfigDrawer}
      destroyOnHidden
      styles={{
        header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
        body: { padding: '24px' },
      }}
      extra={
        <Space>
          <Button
            onClick={closeAlertConfigDrawer}
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
        <Form.Item name="rule_name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
          <Input placeholder="如：发酵部门电力超限预警" style={{ height: 44, borderRadius: 8 }} />
        </Form.Item>

        <Form.Item name="rule_description" label="规则描述">
          <TextArea placeholder="可选描述" rows={2} style={{ borderRadius: 8 }} />
        </Form.Item>

        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="energy_type" label="能源类型" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select options={energyTypeOptions} style={{ height: 44 }} />
          </Form.Item>
          <Form.Item name="monitor_metric" label="监控指标" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select options={monitorMetricOptions} style={{ height: 44 }} />
          </Form.Item>
        </div>

        <div style={{ display: 'flex', gap: 16 }}>
          <Form.Item name="threshold_type" label="阈值类型" rules={[{ required: true }]} style={{ flex: 1 }}>
            <Select options={thresholdTypeOptions} style={{ height: 44 }} />
          </Form.Item>
          <Form.Item name="threshold_value" label="阈值" rules={[{ required: true, message: '请输入阈值' }]} style={{ flex: 1 }}>
            <InputNumber min={0} style={{ width: '100%', height: 44 }} placeholder="数值" />
          </Form.Item>
        </div>

        <Form.Item name="alert_level" label="预警级别" rules={[{ required: true }]}>
          <Select options={alertLevelOptions} style={{ height: 44 }} />
        </Form.Item>

        <Form.Item name="notify_method" label="通知方式" rules={[{ required: true, message: '请选择通知方式' }]}>
          <Select mode="multiple" options={notifyMethodOptions} style={{ minHeight: 44 }} />
        </Form.Item>

        <Form.Item name="notify_frequency" label="通知频率" rules={[{ required: true }]}>
          <Select options={notifyFrequencyOptions} style={{ height: 44 }} />
        </Form.Item>

        <Form.Item name="effective_time" label="生效时间" rules={[{ required: true }]}>
          <Select options={effectiveTimeOptions} style={{ height: 44 }} />
        </Form.Item>

        {effectiveTime === 'custom' && (
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item
              name="custom_time_start"
              label="开始时间"
              rules={[{ required: true, message: '请选择开始时间' }]}
              style={{ flex: 1 }}
            >
              <TimePicker format="HH:mm" placeholder="开始时间" style={{ width: '100%', height: 44 }} minuteStep={5} />
            </Form.Item>
            <Form.Item
              name="custom_time_end"
              label="结束时间"
              rules={[{ required: true, message: '请选择结束时间' }]}
              style={{ flex: 1 }}
            >
              <TimePicker format="HH:mm" placeholder="结束时间" style={{ width: '100%', height: 44 }} minuteStep={5} />
            </Form.Item>
          </div>
        )}

        <Form.Item name="is_enabled" label="启用状态" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
