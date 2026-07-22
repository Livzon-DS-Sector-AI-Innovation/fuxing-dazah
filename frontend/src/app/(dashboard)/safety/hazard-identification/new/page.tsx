'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Typography,
  Row,
  Col,
  Steps,
  App,
} from 'antd'
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  ThunderboltOutlined,
  SaveOutlined,
  BankOutlined,
} from '@ant-design/icons'
import {
  createHazardIdentification,
  submitHazardIdentification,
  getRegulations,
} from '@/actions/safety'
import { DEPARTMENT_OPTIONS } from '@/types/safety'
import type { OperationRegulation } from '@/types/safety'

const { Text } = Typography

export default function NewHazardIdentificationPage() {
  const router = useRouter()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitType, setSubmitType] = useState<'save' | 'submit'>('save')
  const { message } = App.useApp()

  // 安全操作规程列表
  const [regulations, setRegulations] = useState<OperationRegulation[]>([])
  const [regsLoading, setRegsLoading] = useState(false)

  const loadRegulations = useCallback(async () => {
    setRegsLoading(true)
    try {
      const res = await getRegulations({ page_size: 200 })
      if (res.code === 200) {
        setRegulations((res.data as OperationRegulation[]) || [])
      }
    } catch {
      // 静默失败
    } finally {
      setRegsLoading(false)
    }
  }, [])

  useEffect(() => { loadRegulations() }, [loadRegulations])

  const handleSubmit = async (saveOnly: boolean) => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      setSubmitType(saveOnly ? 'save' : 'submit')

      const createRes = await createHazardIdentification({
        department: values.department,
        position: values.position,
        regulation_id: values.regulation_id || undefined,
        notes: values.notes,
      })

      if (createRes.code !== 200) {
        message.error(createRes.message || '创建失败')
        setLoading(false)
        return
      }

      const recordId = createRes.data.id

      if (!saveOnly) {
        const submitRes = await submitHazardIdentification(recordId)
        if (submitRes.code !== 200) {
          message.error(submitRes.message || '提交失败')
          setLoading(false)
          return
        }
      }

      message.success(saveOnly ? '草稿已保存' : '提交成功，进入AI辨识流程')
      router.push(`/safety/hazard-identification/${recordId}`)
    } catch {
      if (!loading) {
        message.error('请完善表单信息')
      }
    } finally {
      setLoading(false)
    }
  }

  const regulationOptions = regulations.map((r) => ({
    value: r.id,
    label: `${r.regulation_no} — ${r.regulation_name}${r.position ? ` (${r.position})` : ''}`,
  }))

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      {/* 返回 */}
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => router.push('/safety/hazard-identification')}
        style={{ marginBottom: 24 }}
      >
        返回列表
      </Button>

      {/* 步骤引导 */}
      <Card
        style={{ marginBottom: 24, borderRadius: 12, border: '1px solid #e5e3df' }}
        styles={{ body: { padding: '16px 24px' } }}
      >
        <Steps
          current={0}
          size="small"
          items={[
            { title: '填写基础信息', icon: <FileTextOutlined /> },
            { title: '引用岗位操作规程', icon: <FileTextOutlined /> },
            { title: '提交进入AI流程', icon: <ThunderboltOutlined /> },
          ]}
        />
      </Card>

      {/* 表单卡片 — 与隐患登记 HazardInspectionForm 视觉对齐 */}
      <Card
        style={{
          borderRadius: 12,
          border: '1px solid #e5e3df',
          borderLeft: '4px solid #5645d4',
        }}
        styles={{ body: { padding: '20px 24px' } }}
      >
        {/* 表单头部 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginBottom: 24,
            paddingBottom: 16,
            borderBottom: '1px solid #ede9e4',
          }}
        >
          <BankOutlined style={{ color: '#5645d4', fontSize: 18 }} />
          <div>
            <span style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>
              登记危险源基础信息
            </span>
            <Text type="secondary" style={{ display: 'block', fontSize: 13, color: '#5d5b54' }}>
              填写岗位基本信息并引用安全操作规程，AI 将自动辨识危险源
            </Text>
          </div>
        </div>

        <Form
          form={form}
          layout="vertical"
          initialValues={{ notes: '' }}
        >
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

          {/* 引用安全操作规程 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <FileTextOutlined style={{ color: '#5645d4', fontSize: 14 }} />
              <Text strong style={{ fontSize: 14 }}>岗位安全操作规程</Text>
            </div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
              从安全操作规程台账中引用，AI 将据此解析识别危险源（可选）
            </Text>

            <Form.Item name="regulation_id" noStyle>
              <Select
                showSearch
                allowClear
                placeholder="搜索并选择岗位安全操作规程"
                loading={regsLoading}
                options={regulationOptions}
                filterOption={(input, option) =>
                  (option?.label as string)?.includes(input)
                }
                notFoundContent={regsLoading ? '加载中...' : '无匹配操作规程'}
              />
            </Form.Item>
          </div>

          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="可选备注信息" />
          </Form.Item>

          {/* 操作按钮 */}
          <div
            style={{
              display: 'flex',
              gap: 12,
              justifyContent: 'flex-end',
              paddingTop: 16,
              borderTop: '1px solid #e5e3df',
            }}
          >
            <Button onClick={() => router.push('/safety/hazard-identification')}>
              取消
            </Button>
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
          </div>
        </Form>
      </Card>
    </div>
  )
}
