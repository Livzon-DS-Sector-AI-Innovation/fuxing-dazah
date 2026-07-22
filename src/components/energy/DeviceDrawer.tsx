'use client'

import { useEffect, useState, useRef } from 'react'
import {
  App,
  Drawer,
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Button,
  Space,
  Spin,
  TimePicker,
} from 'antd'
import dayjs from 'dayjs'
import {
  ApiOutlined,
  EnvironmentOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useEnergyStore } from '@/stores/energy'
import {
  createEnergyDevice,
  updateEnergyDevice,
  getEnergyDeviceById,
} from '@/actions/energy'
import { fetchPlatformsClient } from '@/lib/api/energy'

const { TextArea } = Input

interface PlatformOption {
  code: string
  name: string
}

interface DeviceDrawerProps {
  onRefresh: () => void
}

const DEFAULT_VALUES = {
  platform_code: 'zhiheng',
  energy_type: 'electricity',
  unit: 'kWh',
  collection_interval: 1,  // 小时
  monitor_level: 'normal',
  is_enabled: true,
}

const DAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7]

/** 判断平台是否已接入（非 "待接入" 即视为已接入） */
function isPlatformReady(name: string): boolean {
  return !name.includes('待接入')
}

/** 分组标题组件 */
function SectionLabel({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 12,
        paddingBottom: 10,
        borderBottom: '1px solid #ede9e4',
        color: '#37352f',
        fontSize: 14,
        fontWeight: 600,
        lineHeight: 1.5,
      }}
    >
      <span style={{ color: '#787671', fontSize: 15 }}>{icon}</span>
      {text}
    </div>
  )
}

export function DeviceDrawer({ onRefresh }: DeviceDrawerProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [platforms, setPlatforms] = useState<PlatformOption[]>([])
  const [platformsLoading, setPlatformsLoading] = useState(false)
  const [departments, setDepartments] = useState<{ id: string; name: string }[]>([])
  const [departmentsLoading, setDepartmentsLoading] = useState(false)

  // 关联设备下拉
  const [equipmentOptions, setEquipmentOptions] = useState<{ label: string; value: string }[]>([])
  const [equipmentLoading, setEquipmentLoading] = useState(false)
  const equipmentNameMap = useRef<Map<string, string>>(new Map())

  const {
    deviceDrawerOpen,
    deviceDrawerMode,
    deviceDrawerId,
    closeDeviceDrawer,
  } = useEnergyStore()

  const isEdit = deviceDrawerMode === 'edit'
  const selectedPlatform = Form.useWatch('platform_code', form)
  const watchInterval = Form.useWatch('collection_interval', form)

  // 获取平台列表
  const loadPlatforms = async () => {
    setPlatformsLoading(true)
    try {
      const data = await fetchPlatformsClient()
      setPlatforms(data)
    } catch {
      setPlatforms([
        { code: 'zhiheng', name: '智恒水耗平台' },
        { code: 'platform_b', name: '智能电气系统' },
        { code: 'platform_c', name: '平台C（待接入）' },
      ])
    } finally {
      setPlatformsLoading(false)
    }
  }

  const loadDepartments = async () => {
    setDepartmentsLoading(true)
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/energy/departments`
      )
      const json = await res.json()
      setDepartments(json.data ?? [])
    } catch {
      setDepartments([])
    } finally {
      setDepartmentsLoading(false)
    }
  }

  // 关联设备搜索（防抖）
  const equipmentSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleEquipmentSearch = (keyword: string) => {
    if (equipmentSearchTimer.current) clearTimeout(equipmentSearchTimer.current)
    if (!keyword) {
      setEquipmentOptions([])
      return
    }
    equipmentSearchTimer.current = setTimeout(async () => {
      setEquipmentLoading(true)
      try {
        const params = new URLSearchParams({ keyword, page_size: '20' })
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/energy/equipments?${params}`
        )
        const json = await res.json()
        const items = json.data?.items ?? json.data ?? []
        const opts = items.map((item: any) => {
          const label = `${item.name} (${item.equipment_no})`
          equipmentNameMap.current.set(item.id, item.name)
          return { label, value: item.id }
        })
        setEquipmentOptions(opts)
      } catch {
        setEquipmentOptions([])
      } finally {
        setEquipmentLoading(false)
      }
    }, 300)
  }

  const handleEquipmentChange = (value: string | undefined) => {
    if (value) {
      form.setFieldsValue({ equipment_name: equipmentNameMap.current.get(value) || '' })
    } else {
      form.setFieldsValue({ equipment_id: null, equipment_name: null })
    }
  }

  // 打开抽屉时预加载设备列表（用于编辑时显示已选设备名称）
  const loadEquipmentOption = async (equipmentId: string) => {
    try {
      const params = new URLSearchParams({ page_size: '1' })
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'}/api/v1/energy/equipments?${params}`
      )
      const json = await res.json()
      const items = json.data?.items ?? json.data ?? []
      // 如果已选的设备不在第一页，尝试直接通过 ID 构建选项（从已有 equipment_name 展示）
      const found = items.find((item: any) => item.id === equipmentId)
      if (found) {
        equipmentNameMap.current.set(found.id, found.name)
        setEquipmentOptions([{ label: `${found.name} (${found.equipment_no})`, value: found.id }])
      }
    } catch {
      // 忽略加载失败
    }
  }

  useEffect(() => {
    if (deviceDrawerOpen) {
      loadPlatforms()
      loadDepartments()
      if (isEdit && deviceDrawerId) {
        loadDeviceData(deviceDrawerId)
      } else {
        form.resetFields()
        setEquipmentOptions([])
        equipmentNameMap.current.clear()
      }
    }
  }, [deviceDrawerOpen, deviceDrawerId, isEdit, form])

  const loadDeviceData = async (id: string) => {
    try {
      const device = await getEnergyDeviceById(id)
      // 采集间隔：后端存分钟，前端展示小时
      const formData: Record<string, unknown> = { ...device }
      if (device.collection_interval) {
        formData.collection_interval = +(device.collection_interval / 60).toFixed(2)
      }
      // TimePicker 需要 dayjs 对象，后端返回 "HH:mm" 字符串
      if (device.daily_collect_time && typeof device.daily_collect_time === 'string') {
        formData.daily_collect_time = dayjs(device.daily_collect_time, 'HH:mm')
      }
      form.setFieldsValue(formData)
      // 编辑时，如果有已关联设备，预加载下拉选项
      if (device.equipment_id) {
        loadEquipmentOption(device.equipment_id)
      }
    } catch {
      message.error('获取数据源信息失败')
    }
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      // 采集间隔：前端小时 → 后端分钟
      if (values.collection_interval != null) {
        values.collection_interval = Math.round(values.collection_interval * 60)
      }
      // TimePicker 返回值转为 HH:mm 字符串
      if (values.daily_collect_time) {
        if (typeof values.daily_collect_time === 'object' && values.daily_collect_time.format) {
          values.daily_collect_time = values.daily_collect_time.format('HH:mm')
        }
      } else {
        values.daily_collect_time = null
      }
      setLoading(true)

      if (isEdit && deviceDrawerId) {
        await updateEnergyDevice(deviceDrawerId, values)
        message.success('更新成功')
      } else {
        await createEnergyDevice(values)
        message.success('创建成功')
      }

      closeDeviceDrawer()
      onRefresh()
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return
      if (err instanceof Error) {
        message.error(err.message)
      } else {
        message.error('操作失败')
      }
    } finally {
      setLoading(false)
    }
  }

  // 当前选中平台信息
  const currentPlatform = platforms.find((p) => p.code === selectedPlatform)
  const platformReady = currentPlatform ? isPlatformReady(currentPlatform.name) : false

  return (
    <Drawer
      title={isEdit ? '编辑数据源' : '新增数据源'}
      size={480}
      open={deviceDrawerOpen}
      onClose={closeDeviceDrawer}
      destroyOnHidden
      styles={{
        header: {
          borderBottom: '1px solid #e5e3df',
          padding: '16px 24px',
        },
        body: { padding: '24px' },
      }}
      extra={
        <Space>
          <Button
            onClick={closeDeviceDrawer}
            style={{
              color: '#37352f',
              borderColor: '#c8c4be',
              borderRadius: 8,
              height: 36,
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            取消
          </Button>
          <Button
            type="primary"
            onClick={handleSubmit}
            loading={loading}
            style={{
              background: '#5645d4',
              borderColor: '#5645d4',
              borderRadius: 8,
              height: 36,
              fontSize: 14,
              fontWeight: 500,
              boxShadow: 'none',
            }}
          >
            确定
          </Button>
        </Space>
      }
    >
      <Spin spinning={platformsLoading}>
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            initialValues={DEFAULT_VALUES}
            style={{ maxWidth: '100%' }}
          >
            {/* ── 平台连接 ── */}
            <SectionLabel icon={<ApiOutlined />} text="平台连接" />

            <Form.Item
              name="platform_code"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  平台
                </span>
              }
              rules={[{ required: true, message: '请选择平台' }]}
              style={{ marginBottom: 16 }}
            >
              <Select
                placeholder="选择数据来源平台"
                options={platforms.map((p) => ({
                  label: p.name,
                  value: p.code,
                }))}
                style={{ height: 44 }}
              />
            </Form.Item>

            {/* 平台状态指示 */}
            {selectedPlatform && currentPlatform && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '10px 12px',
                  marginBottom: 16,
                  marginTop: -8,
                  borderRadius: 8,
                  background: platformReady ? '#d9f3e1' : '#ffe8d4',
                  fontSize: 13,
                  lineHeight: 1.4,
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: platformReady ? '#1aae39' : '#dd5b00',
                    flexShrink: 0,
                  }}
                />
                <span style={{ color: platformReady ? '#18732e' : '#793400', fontWeight: 500 }}>
                  {platformReady ? '已接入' : '待接入'}
                </span>
                <span style={{ color: '#787671' }}>— {currentPlatform.name}</span>
              </div>
            )}

            <Form.Item
              name="platform_device_code"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  平台接入编码
                </span>
              }
              rules={[{ required: true, message: '请输入平台接入编码' }]}
              extra={
                <span style={{ fontSize: 12, color: '#a4a097' }}>
                  支持公式：多个水表 ID 用 + - 连接，如 202022001507+202503170001
                </span>
              }
              style={{ marginBottom: 24 }}
            >
              <Input
                placeholder="单个水表/电表 ID 或公式"
                style={{ height: 44, borderRadius: 8 }}
              />
            </Form.Item>

            {/* ── 数据源信息 ── */}
            <SectionLabel icon={<EnvironmentOutlined />} text="数据源信息" />

            <Form.Item
              name="equipment_id"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  关联设备
                </span>
              }
              style={{ marginBottom: 16 }}
            >
              <Select
                placeholder="搜索并选择设备台账中的设备"
                showSearch
                allowClear
                filterOption={false}
                onSearch={handleEquipmentSearch}
                options={equipmentOptions}
                loading={equipmentLoading}
                onChange={handleEquipmentChange}
                style={{ height: 44 }}
              />
            </Form.Item>

            {/* 隐藏的 equipment_name 字段 */}
            <Form.Item name="equipment_name" hidden>
              <Input />
            </Form.Item>

            <Form.Item
              name="device_name"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  数据源名称
                </span>
              }
              rules={[{ required: true, message: '请输入数据源名称' }]}
              style={{ marginBottom: 16 }}
            >
              <Input
                placeholder="如：办公楼、发酵部门、提炼一部"
                style={{ height: 44, borderRadius: 8 }}
              />
            </Form.Item>

            <Form.Item
              name="energy_type"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  能源类型
                </span>
              }
              rules={[{ required: true, message: '请选择能源类型' }]}
              style={{ marginBottom: 16 }}
            >
              <Select
                options={[
                  { label: '电耗数据',   value: 'electricity' },
                  { label: '水耗数据',   value: 'water' },
                  { label: '蒸汽数据',   value: 'steam' },
                  { label: '冷量数据',   value: 'cooling' },
                  { label: '压缩空气数据', value: 'compressed_air' },
                  { label: '氮气数据',   value: 'nitrogen' },
                  { label: '天然气数据', value: 'natural_gas' },
                ]}
                style={{ height: 44 }}
              />
            </Form.Item>

            <Form.Item
              name="workshop"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  所属部门
                </span>
              }
              rules={[{ required: true, message: '请选择所属部门' }]}
              style={{ marginBottom: 16 }}
            >
              <Select
                placeholder="选择部门"
                loading={departmentsLoading}
                showSearch
                options={departments.map((d) => ({
                  label: d.name,
                  value: d.name,
                }))}
                style={{ height: 44 }}
              />
            </Form.Item>

            <Form.Item
              name="production_line"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  所属区域
                </span>
              }
              style={{ marginBottom: 24 }}
            >
              <Input
                placeholder="可选，如：A 区"
                style={{ height: 44, borderRadius: 8 }}
              />
            </Form.Item>

            {/* ── 采集设置 ── */}
            <SectionLabel icon={<SettingOutlined />} text="采集设置" />

            <Form.Item
              name="unit"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  计量单位
                </span>
              }
              rules={[{ required: true, message: '请选择计量单位' }]}
              style={{ marginBottom: 16 }}
            >
              <Select
                options={[
                  { label: 'kWh（千瓦时）', value: 'kWh' },
                  { label: 'm³（立方米）', value: 'm³' },
                  { label: 't（吨）', value: 't' },
                  { label: 'L（升）', value: 'L' },
                ]}
                style={{ height: 44 }}
              />
            </Form.Item>

            <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
              <Form.Item
                name="collection_interval"
                label={
                  <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                    采集间隔
                  </span>
                }
                rules={[{ required: true, message: '必填' }]}
                style={{ flex: 1, marginBottom: 0 }}
                extra={
                  <span style={{ fontSize: 12, color: '#a4a097' }}>
                    {watchInterval >= 24
                      ? `每 ${Math.round(watchInterval / 24)} 天自动采集一次汇总数据`
                      : '自动采集开启后，按此间隔检查并拉取数据'}
                  </span>
                }
              >
                {watchInterval >= 24 ? (
                  <div>
                    <Select
                      placeholder="选择天数"
                      options={DAY_OPTIONS.map(d => ({ label: `${d} 天`, value: d * 24 }))}
                      style={{ height: 44 }}
                    />
                    <Button
                      type="link"
                      size="small"
                      style={{ padding: 0, fontSize: 12, marginTop: 4 }}
                      onClick={() => {
                        form.setFieldValue('collection_interval', 1)
                        form.setFieldValue('daily_collect_time', null)
                      }}
                    >
                      切换为按小时采集
                    </Button>
                  </div>
                ) : (
                  <div>
                    <InputNumber
                      min={0.25}
                      max={23.75}
                      step={0.25}
                      placeholder="1"
                      suffix="小时"
                      style={{ width: '100%', height: 44 }}
                    />
                    <Button
                      type="link"
                      size="small"
                      style={{ padding: 0, fontSize: 12, marginTop: 4 }}
                      onClick={() => {
                        form.setFieldValue('collection_interval', 24)
                        form.setFieldValue('daily_collect_time', null)
                      }}
                    >
                      切换为按天采集
                    </Button>
                  </div>
                )}
              </Form.Item>

              {watchInterval >= 24 && (
                <Form.Item
                  name="daily_collect_time"
                  label={
                    <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                      每日采集时间
                    </span>
                  }
                  style={{ flex: 1, marginBottom: 0 }}
                  extra={
                    <span style={{ fontSize: 12, color: '#a4a097' }}>
                      每天定时将过去 N 天的数据汇总输出
                    </span>
                  }
                >
                  <TimePicker
                    format="HH:mm"
                    minuteStep={30}
                    placeholder="08:00"
                    style={{ width: '100%', height: 44 }}
                  />
                </Form.Item>
              )}

              <Form.Item
                name="monitor_level"
                label={
                  <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                    监控级别
                  </span>
                }
                style={{ flex: 1, marginBottom: 0 }}
              >
                <Select
                  options={[
                    { label: '普通', value: 'normal' },
                    { label: '重要', value: 'important' },
                    { label: '紧急', value: 'urgent' },
                  ]}
                  style={{ height: 44 }}
                />
              </Form.Item>
            </div>

            {/* ── 备注 ── */}
            <div style={{ marginBottom: 16 }} />

            <Form.Item
              name="remark"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  备注
                </span>
              }
              style={{ marginBottom: 16 }}
            >
              <TextArea
                rows={2}
                placeholder="可选备注信息"
                style={{ borderRadius: 8 }}
              />
            </Form.Item>

            {/* ── 启用开关 ── */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 16px',
                borderRadius: 8,
                background: '#f6f5f4',
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', lineHeight: 1.5 }}>
                  启用采集
                </div>
                <div style={{ fontSize: 12, color: '#787671', lineHeight: 1.4 }}>
                  开启后将按设定的间隔自动拉取数据
                </div>
              </div>
              <Form.Item name="is_enabled" valuePropName="checked" style={{ marginBottom: 0 }}>
                <Switch />
              </Form.Item>
            </div>

            {/* api_endpoint 隐藏字段 */}
            <Form.Item name="api_endpoint" hidden>
              <Input />
            </Form.Item>
          </Form>
        </Spin>
    </Drawer>
  )
}
