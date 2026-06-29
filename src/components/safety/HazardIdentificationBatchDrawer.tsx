'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Drawer,
  Form,
  Input,
  Select,
  Button,
  Typography,
  Row,
  Col,
  App,
  Steps,
  Divider,
  Tag,
} from 'antd'
import {
  FileTextOutlined,
  ThunderboltOutlined,
  SaveOutlined,
  BankOutlined,
  NodeIndexOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import {
  createHazardIdentificationBatch,
  getRegulations,
} from '@/actions/safety'
import { DEPARTMENT_OPTIONS } from '@/types/safety'
import type { OperationRegulation } from '@/types/safety'
import StageSelector from './StageSelector'

const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
  onDone: () => void
}

export default function HazardIdentificationBatchDrawer({
  open,
  onClose,
  onDone,
}: Props) {
  const router = useRouter()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitType, setSubmitType] = useState<'save' | 'submit'>('save')
  const { message } = App.useApp()

  // Step tracking (0-indexed internally)
  const [currentStep, setCurrentStep] = useState(0)

  // Regulations
  const [regulations, setRegulations] = useState<OperationRegulation[]>([])
  const [regsLoading, setRegsLoading] = useState(false)

  // Selected stages
  const [selectedStages, setSelectedStages] = useState<string[]>([])
  const [selectedRegulationId, setSelectedRegulationId] = useState<string>('')

  const loadRegulations = useCallback(async () => {
    setRegsLoading(true)
    try {
      const res = await getRegulations({ page_size: 200 })
      if (res.code === 200) {
        setRegulations((res.data as OperationRegulation[]) || [])
      }
    } catch {
      // 静默
    } finally {
      setRegsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) loadRegulations()
  }, [open, loadRegulations])

  const handleRegulationChange = (regId: string) => {
    setSelectedRegulationId(regId)
    setSelectedStages([]) // 重置已选工段
    form.setFieldValue('regulation_id', regId)
  }

  const canProceedToNext = () => {
    if (currentStep === 0) return true // department + position always fillable
    if (currentStep === 1) return !!selectedRegulationId
    if (currentStep === 2) return selectedStages.length > 0
    return true
  }

  const handleNext = () => {
    if (currentStep === 0) {
      form.validateFields(['department', 'position']).then(
        () => setCurrentStep(1),
        () => {}
      )
      return
    }
    if (currentStep === 1 && selectedRegulationId) {
      setCurrentStep(2)
      return
    }
    if (currentStep === 2 && selectedStages.length > 0) {
      setCurrentStep(3)
      return
    }
  }

  const handlePrev = () => {
    setCurrentStep((s) => Math.max(0, s - 1))
  }

  const handleSubmit = async (saveOnly: boolean) => {
    try {
      const values = await form.validateFields()
      if (selectedStages.length === 0) {
        message.warning('请至少选择一个工艺阶段')
        return
      }

      setLoading(true)
      setSubmitType(saveOnly ? 'save' : 'submit')

      const res = await createHazardIdentificationBatch({
        department: values.department,
        position: values.position,
        regulation_id: selectedRegulationId,
        stage_names: selectedStages,
        notes: values.notes,
        auto_submit: !saveOnly,
      })

      if (res.code !== 200) {
        message.error(res.message || '批量创建失败')
        setLoading(false)
        return
      }

      const result = res.data
      message.success(
        saveOnly
          ? `已保存 ${result.created_count}/${result.total_stages} 条草稿`
          : `已创建 ${result.created_count} 条辨识记录，已提交进入AI流程`
      )

      form.resetFields()
      setSelectedStages([])
      setSelectedRegulationId('')
      setCurrentStep(0)
      onClose()
      onDone()

      if (!saveOnly && result.batch_id) {
        router.push(
          `/safety/hazard-identification?batch_id=${result.batch_id}`
        )
      }
    } catch {
      if (!loading) {
        message.error('请完善表单信息')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    if (loading) return
    form.resetFields()
    setSelectedStages([])
    setSelectedRegulationId('')
    setCurrentStep(0)
    onClose()
  }

  const regulationOptions = regulations.map((r) => ({
    value: r.id,
    label: `${r.regulation_no} — ${r.regulation_name}${r.position ? ` (${r.position})` : ''}`,
  }))

  const stepItems = [
    { title: '基础信息', icon: <BankOutlined /> },
    { title: '选择操规', icon: <FileTextOutlined /> },
    { title: '选择工段', icon: <NodeIndexOutlined /> },
    { title: '确认创建', icon: <CheckCircleOutlined /> },
  ]

  return (
    <Drawer
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <BankOutlined style={{ color: '#5645d4' }} />
          <span style={{ fontSize: 16, fontWeight: 600 }}>批量危险源辨识</span>
        </span>
      }
      open={open}
      onClose={handleClose}
      placement="right"
      size="large"
      destroyOnClose
      styles={{ body: { padding: '16px 24px 24px' } }}
    >
      {/* Steps indicator */}
      <Steps
        current={currentStep}
        size="small"
        style={{ marginBottom: 24 }}
        items={stepItems}
      />

      <div
        style={{
          borderRadius: 12,
          border: '1px solid #e5e3df',
          borderLeft: '4px solid #5645d4',
          padding: '20px 24px',
          background: '#ffffff',
        }}
      >
        <Form form={form} layout="vertical" initialValues={{ notes: '' }}>
          {/* Step 0: Department + Position */}
          {currentStep === 0 && (
            <>
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  填写部门与岗位，为所有辨识记录设置统一的基础信息
                </Text>
              </div>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="department"
                    label="部门"
                    rules={[{ required: true, message: '请选择部门' }]}
                  >
                    <Select
                      showSearch
                      placeholder="请选择部门"
                      options={DEPARTMENT_OPTIONS}
                      filterOption={(input, option) =>
                        (option?.label as string)?.includes(input)
                      }
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="position"
                    label="岗位"
                    rules={[{ required: true, message: '请输入岗位' }]}
                  >
                    <Input placeholder="如：离心操作岗" />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}

          {/* Step 1: Select regulation */}
          {currentStep === 1 && (
            <>
              <div style={{ marginBottom: 16 }}>
                <FileTextOutlined style={{ color: '#5645d4', marginRight: 6 }} />
                <Text strong style={{ fontSize: 14 }}>岗位安全操作规程</Text>
                <Text type="secondary" style={{ display: 'block', marginTop: 4, fontSize: 12 }}>
                  选择一份安全操作规程，其第7章「生产工艺流程」将作为辨识范围
                </Text>
              </div>
              <Form.Item name="regulation_id" noStyle>
                <Select
                  showSearch
                  allowClear
                  placeholder="搜索并选择岗位安全操作规程"
                  loading={regsLoading}
                  value={selectedRegulationId || undefined}
                  onChange={handleRegulationChange}
                  options={regulationOptions}
                  filterOption={(input, option) =>
                    (option?.label as string)?.includes(input)
                  }
                  notFoundContent={regsLoading ? '加载中...' : '无匹配操作规程'}
                />
              </Form.Item>
            </>
          )}

          {/* Step 2: Select stages */}
          {currentStep === 2 && selectedRegulationId && (
            <StageSelector
              regulationId={selectedRegulationId}
              value={selectedStages}
              onChange={setSelectedStages}
            />
          )}

          {/* Step 3: Confirm */}
          {currentStep === 3 && (
            <>
              <div style={{ marginBottom: 16 }}>
                <CheckCircleOutlined
                  style={{ color: '#52c41a', marginRight: 6, fontSize: 16 }}
                />
                <Text strong style={{ fontSize: 15 }}>
                  确认批量创建
                </Text>
              </div>

              <div
                style={{
                  background: '#fafaf8',
                  borderRadius: 8,
                  padding: '12px 16px',
                  marginBottom: 16,
                }}
              >
                <Row gutter={[8, 8]}>
                  <Col span={12}>
                    <Text type="secondary">部门</Text>
                    <div><Text strong>{form.getFieldValue('department')}</Text></div>
                  </Col>
                  <Col span={12}>
                    <Text type="secondary">岗位</Text>
                    <div><Text strong>{form.getFieldValue('position')}</Text></div>
                  </Col>
                  <Col span={24}>
                    <Text type="secondary">操规</Text>
                    <div>
                      <Text strong>
                        {regulations.find((r) => r.id === selectedRegulationId)
                          ?.regulation_name || selectedRegulationId}
                      </Text>
                    </div>
                  </Col>
                  <Col span={24}>
                    <Text type="secondary">
                      已选工艺阶段（{selectedStages.length} 个）
                    </Text>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {selectedStages.map((s) => (
                        <Tag key={s} color="blue">
                          {s}
                        </Tag>
                      ))}
                    </div>
                  </Col>
                </Row>
              </div>

              <Form.Item name="notes" label="备注">
                <Input.TextArea rows={2} placeholder="可选备注信息（共享到所有记录）" />
              </Form.Item>
            </>
          )}

          {/* Navigation */}
          <Divider style={{ margin: '16px 0' }} />
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
            }}
          >
            <div>
              {currentStep > 0 && (
                <Button onClick={handlePrev} disabled={loading}>
                  上一步
                </Button>
              )}
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <Button onClick={handleClose} disabled={loading}>
                取消
              </Button>
              {currentStep < 3 ? (
                <Button
                  type="primary"
                  onClick={handleNext}
                  disabled={!canProceedToNext()}
                >
                  下一步
                </Button>
              ) : (
                <>
                  <Button
                    icon={<SaveOutlined />}
                    loading={loading && submitType === 'save'}
                    onClick={() => handleSubmit(true)}
                  >
                    仅保存草稿
                  </Button>
                  <Button
                    type="primary"
                    icon={<ThunderboltOutlined />}
                    loading={loading && submitType === 'submit'}
                    onClick={() => handleSubmit(false)}
                  >
                    提交并进入AI流程
                  </Button>
                </>
              )}
            </div>
          </div>
        </Form>
      </div>
    </Drawer>
  )
}
