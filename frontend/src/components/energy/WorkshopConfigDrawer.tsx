'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space, Switch, TimePicker } from 'antd'
import dayjs from 'dayjs'
import { useEnergyStore } from '@/stores/energy'
import {
  createWorkshopConfig,
  updateWorkshopConfig,
  getWorkshopConfigById,
  getWorkshopPersonnelCandidates,
  getAvailableRules,
  getWorkshopOptions,
} from '@/actions/energy'
import { fetchEnabledTypeConfigsClient } from '@/lib/api/energy'
import type {
  CreateWorkshopConfigInput,
  UpdateWorkshopConfigInput,
  EnergyPersonnelCandidate,
  AlertRuleCandidate,
  WorkshopOption,
  EnergyTypeConfig,
} from '@/types/energy'

interface WorkshopConfigDrawerProps {
  onRefresh?: () => void
}

export function WorkshopConfigDrawer({ onRefresh }: WorkshopConfigDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [submitting, setSubmitting] = useState(false)

  const {
    workshopConfigDrawerOpen,
    workshopConfigDrawerMode,
    workshopConfigDrawerId,
    closeWorkshopConfigDrawer,
  } = useEnergyStore()

  const isEdit = workshopConfigDrawerMode === 'edit'

  const [candidates, setCandidates] = useState<EnergyPersonnelCandidate[]>([])

  // 可选预警规则
  const [availableRules, setAvailableRules] = useState<AlertRuleCandidate[]>([])

  // 可选设备配置（供车间名称下拉框，按能源类型过滤）
  const [workshopOptions, setWorkshopOptions] = useState<WorkshopOption[]>([])

  // 能源类型筛选（仅 UI 过滤，不存储到表单）
  const [filterEnergyType, setFilterEnergyType] = useState<string | undefined>(undefined)

  // 能源类型配置列表（供能源类型下拉框使用）
  const [typeConfigs, setTypeConfigs] = useState<EnergyTypeConfig[]>([])

  const loadAvailableRules = useCallback(async () => {
    try {
      const rules = await getAvailableRules()
      setAvailableRules(rules)
    } catch {
      // 静默失败，下拉框显示空
    }
  }, [])

  const loadCandidates = useCallback(async () => {
    try {
      const data = await getWorkshopPersonnelCandidates()
      setCandidates(data)
    } catch {
      message.error('获取人员列表失败')
    }
  }, [message])

  const loadWorkshopOptions = useCallback(async (energyType?: string) => {
    try {
      const options = await getWorkshopOptions(energyType)
      setWorkshopOptions(options)
    } catch (err) {
      console.error('加载车间选项失败:', err)
      message.error('加载车间选项失败')
    }
  }, [message])

  useEffect(() => {
    if (!workshopConfigDrawerOpen) return
    loadAvailableRules()
    loadWorkshopOptions()
    loadCandidates()
    fetchEnabledTypeConfigsClient().then(setTypeConfigs).catch(() => {})
    setFilterEnergyType(undefined)
    const timer = setTimeout(() => {
      if (isEdit && workshopConfigDrawerId) {
        getWorkshopConfigById(workshopConfigDrawerId)
          .then((config) => {
            form.setFieldsValue({
              workshop: config.workshop,
              heads: config.heads?.map((h) => h.feishu_open_id) || [],
              alert_rule_id: config.alert_rule_id || undefined,
              notify_time: config.notify_time ? dayjs(config.notify_time, 'HH:mm') : undefined,
              auto_notify_enabled: config.auto_notify_enabled,
              is_enabled: config.is_enabled,
            })
          })
          .catch(() => {
            message.error('获取车间配置失败')
          })
      } else {
        form.resetFields()
        form.setFieldsValue({
          auto_notify_enabled: true,
          is_enabled: true,
          heads: [],
        })
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [workshopConfigDrawerOpen, workshopConfigDrawerId, isEdit, form, message, loadAvailableRules, loadWorkshopOptions, loadCandidates])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      // 从 candidates 映射 open_id → { name, feishu_open_id }
      const selectedOpenIds: string[] = values.heads || []
      const heads = selectedOpenIds
        .map((oid: string) => {
          const c = candidates.find((c) => c.feishu_open_id === oid)
          return c ? { name: c.name, feishu_open_id: c.feishu_open_id } : null
        })
        .filter(Boolean) as { name: string; feishu_open_id: string }[]

      if (isEdit && workshopConfigDrawerId) {
        const data: UpdateWorkshopConfigInput = {
          workshop: values.workshop,
          heads: heads,
          alert_rule_id: values.alert_rule_id || undefined,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          auto_notify_enabled: values.auto_notify_enabled,
          is_enabled: values.is_enabled,
        }
        await updateWorkshopConfig(workshopConfigDrawerId, data)
        message.success('更新成功')
      } else {
        const data: CreateWorkshopConfigInput = {
          workshop: values.workshop,
          heads: heads,
          alert_rule_id: values.alert_rule_id || undefined,
          notify_time: values.notify_time ? values.notify_time.format('HH:mm') : undefined,
          auto_notify_enabled: values.auto_notify_enabled ?? true,
          is_enabled: values.is_enabled ?? true,
        }
        await createWorkshopConfig(data)
        message.success('创建成功')
      }
      closeWorkshopConfigDrawer()
      onRefresh?.()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) message.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const personnelOptions = candidates.map((c) => ({
    label: `${c.name}${c.department ? `（${c.department}）` : ''}`,
    value: c.feishu_open_id,
  }))

  return (
      <Drawer
        title={isEdit ? '编辑车间预警配置' : '新建车间预警配置'}
        size={520}
        open={workshopConfigDrawerOpen}
        onClose={closeWorkshopConfigDrawer}
        destroyOnHidden
        styles={{
          header: { borderBottom: '1px solid #e5e3df', padding: '16px 24px' },
          body: { padding: '24px' },
        }}
        extra={
          <Space>
            <Button
              onClick={closeWorkshopConfigDrawer}
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
          <Form.Item label="能源类型" help="选择能源类型后，车间名称将仅显示配置了该类型的数据源">
            <Select
              allowClear
              placeholder="选择能源类型以筛选数据源（可选）"
              value={filterEnergyType}
              onChange={(val) => {
                setFilterEnergyType(val)
                form.setFieldValue('workshop', undefined)
                loadWorkshopOptions(val)
              }}
              options={typeConfigs.map((tc) => ({
                label: `${tc.display_name}（${tc.type_code}）`,
                value: tc.type_code,
              }))}
              style={{ width: '100%' }}
              size="large"
            />
          </Form.Item>

          <Form.Item name="workshop" label="车间名称" rules={[{ required: true, message: '请选择数据源' }]}>
            <Select
              key={`workshop-${workshopOptions.length}-${filterEnergyType || 'all'}`}
              placeholder="选择数据源"
              options={workshopOptions.map((w) => ({
                label: w.device_name,
                value: w.workshop,
                key: `${w.device_name}__${w.workshop}`,
              }))}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
              style={{ width: '100%' }}
              size="large"
              notFoundContent={filterEnergyType ? '该能源类型下暂无已启用的设备配置' : '暂无已启用的设备配置'}
            />
          </Form.Item>

          <Form.Item name="heads" label="预警负责人">
            <Select
              mode="multiple"
              placeholder="选择预警负责人"
              options={personnelOptions}
              showSearch
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
              }
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item name="alert_rule_id" label="关联预警规则" help="选择一条自定义规则后将替代系统自动生成的规则">
            <Select
              allowClear
              placeholder="选择已配置的预警规则（可选）"
              options={availableRules.map((r) => ({
                label: `${r.rule_name}（${r.energy_type} · ${r.alert_level}）`,
                value: r.id,
              }))}
              style={{ width: '100%' }}
            />
          </Form.Item>

          <Form.Item name="notify_time" label="每日通知时间" help="设置后将在每天此时通过飞书推送预警通知；留空则使用全局默认时间">
            <TimePicker
              format="HH:mm"
              placeholder="选择通知时间（可选）"
              style={{ width: '100%', height: 44 }}
              minuteStep={5}
            />
          </Form.Item>

          <div style={{ display: 'flex', gap: 32 }}>
            <Form.Item name="auto_notify_enabled" label="自动通知" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="is_enabled" label="启用配置" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>

          <div style={{ padding: '12px 16px', background: '#f6f3ff', borderRadius: 8, color: '#787671', fontSize: 13, lineHeight: 1.6, marginTop: 8 }}>
            关联自定义规则后，系统将按所选规则的阈值和等级进行评估，不再自动生成系统规则。未关联时，系统将在每日定时检查该车间昨日各类能耗是否超过近 30 天均值的 115%。
          </div>
        </Form>
      </Drawer>
  )
}
