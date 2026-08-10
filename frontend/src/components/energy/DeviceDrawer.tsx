'use client'

import { useEffect, useState, useRef } from 'react'
import {
  App,
  Drawer,
  Form,
  Input,
  Select,
  Switch,
  Button,
  Space,
  Spin,
  Radio,
} from 'antd'
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
import { fetchPlatformsClient, fetchEnabledTypeConfigsClient } from '@/lib/api/energy'

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
  monitor_level: 'normal',
  is_enabled: true,
  is_region_level: false,
  stat_role: 'normal',
}

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

  // 能源类型选项（动态加载）
  const [energyTypeOptions, setEnergyTypeOptions] = useState<{ label: string; value: string }[]>([])

  const {
    deviceDrawerOpen,
    deviceDrawerMode,
    deviceDrawerId,
    closeDeviceDrawer,
  } = useEnergyStore()

  const isEdit = deviceDrawerMode === 'edit'
  const selectedPlatform = Form.useWatch('platform_code', form)
  const watchIsRegionLevel = Form.useWatch('is_region_level', form)

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
      fetchEnabledTypeConfigsClient().then(configs => {
        setEnergyTypeOptions(configs.map(c => ({ label: c.display_name, value: c.type_code })))
      }).catch(() => {})
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
      form.setFieldsValue({ ...device })
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
                options={energyTypeOptions}
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

            {/* 区域级别开关 */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '12px 16px',
                marginBottom: 16,
                borderRadius: 8,
                background: '#f6f5f4',
              }}
            >
              <div>
                <div style={{ fontSize: 14, fontWeight: 500, color: '#1a1a1a', lineHeight: 1.5 }}>
                  区域级别
                </div>
                <div style={{ fontSize: 12, color: '#787671', lineHeight: 1.4 }}>
                  开启后该数据源归为区域级别，需填写所属区域
                </div>
              </div>
              <Form.Item name="is_region_level" valuePropName="checked" style={{ marginBottom: 0 }}>
                <Switch
                  onChange={(checked) => {
                    if (!checked) {
                      form.setFieldValue('production_line', null)
                    }
                  }}
                />
              </Form.Item>
            </div>

            {watchIsRegionLevel && (
              <Form.Item
                name="production_line"
                label={
                  <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                    所属区域
                  </span>
                }
                rules={[{ required: true, message: '区域级别必须填写所属区域' }]}
                style={{ marginBottom: 24 }}
              >
                <Input
                  placeholder="如：A 区"
                  style={{ height: 44, borderRadius: 8 }}
                />
              </Form.Item>
            )}

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

            <Form.Item
              name="stat_role"
              label={
                <span style={{ fontSize: 13, fontWeight: 500, color: '#5d5b54' }}>
                  统计角色
                </span>
              }
              style={{ marginBottom: 16 }}
            >
              <Radio.Group
                optionType="button"
                buttonStyle="solid"
                size="middle"
                options={[
                  { label: '参与统计', value: 'normal' },
                  { label: '不参与', value: 'excluded' },
                  { label: '作为总耗', value: 'total' },
                ]}
              />
            </Form.Item>

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
