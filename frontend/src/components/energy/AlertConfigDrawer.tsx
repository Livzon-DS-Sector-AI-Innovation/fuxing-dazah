'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, InputNumber, Button, Space } from 'antd'
import { useEnergyStore } from '@/stores/energy'
import { createAlertRule, updateAlertRule, getAlertRuleById } from '@/actions/energy'
import { CreateRuleInput, UpdateRuleInput, EnergyType, MonitorMetric, ThresholdType, AlertLevel, NotifyFrequency, EffectiveTimeType } from '@/types/energy'

const { TextArea } = Input

interface AlertConfigDrawerProps {
  onRefresh?: () => void
}

const energyTypeOptions = [
  { label: '电耗数据',   value: 'electricity' },
  { label: '水耗数据',   value: 'water' },
  { label: '蒸汽数据',   value: 'steam' },
  { label: '冷量数据',   value: 'cooling' },
  { label: '压缩空气数据', value: 'compressed_air' },
  { label: '氮气数据',   value: 'nitrogen' },
  { label: '天然气数据', value: 'natural_gas' },
]

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
  energy_type: 'electricity' as EnergyType,
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

  const {
    alertConfigDrawerOpen,
    alertConfigDrawerMode,
    alertConfigDrawerId,
    closeAlertConfigDrawer,
  } = useEnergyStore()

  const isEdit = alertConfigDrawerMode === 'edit'

  useEffect(() => {
    if (!alertConfigDrawerOpen) return
    const timer = setTimeout(() => {
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
              unit: rule.unit,
              alert_level: rule.alert_level,
              notify_method: rule.notify_method,
              notify_frequency: rule.notify_frequency,
              effective_time: rule.effective_time,
              is_enabled: rule.is_enabled,
            })
          })
          .catch(() => {
            message.error('获取规则详情失败')
          })
      } else {
        form.resetFields()
        form.setFieldsValue(DEFAULT_VALUES)
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [alertConfigDrawerOpen, alertConfigDrawerId, isEdit, form, message])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      if (isEdit && alertConfigDrawerId) {
        const data: UpdateRuleInput = {
          rule_name: values.rule_name,
          rule_description: values.rule_description || undefined,
          energy_type: values.energy_type,
          monitor_metric: values.monitor_metric,
          threshold_type: values.threshold_type,
          threshold_value: values.threshold_value,
          unit: values.unit,
          alert_level: values.alert_level,
          notify_method: values.notify_method,
          notify_frequency: values.notify_frequency,
          effective_time: values.effective_time,
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
          unit: values.unit,
          alert_level: values.alert_level,
          notify_method: values.notify_method,
          notify_users: [],
          notify_frequency: values.notify_frequency,
          effective_time: values.effective_time,
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

        <Form.Item name="unit" label="单位" rules={[{ required: true, message: '请输入单位' }]}>
          <Input placeholder="如：kWh、m³" style={{ height: 44, borderRadius: 8 }} />
        </Form.Item>

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

        <Form.Item name="is_enabled" label="启用状态" valuePropName="checked" hidden>
          <Input />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
