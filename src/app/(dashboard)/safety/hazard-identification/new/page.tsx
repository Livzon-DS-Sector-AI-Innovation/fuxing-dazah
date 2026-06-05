'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Card,
  Form,
  Input,
  Button,
  message,
  Typography,
  Row,
  Col,
  Space,
  Upload,
} from 'antd'
import { ArrowLeftOutlined, UploadOutlined } from '@ant-design/icons'
import {
  createHazardIdentification,
  submitHazardIdentification,
  uploadHazardAttachment,
} from '@/actions/safety'

const { Title } = Typography

export default function NewHazardIdentificationPage() {
  const router = useRouter()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitType, setSubmitType] = useState<'save' | 'submit'>('save')

  const handleSubmit = async (saveOnly: boolean) => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      setSubmitType(saveOnly ? 'save' : 'submit')

      // 创建记录
      const createRes = await createHazardIdentification({
        hazard_id_no: values.hazard_id_no,
        department: values.department,
        position: values.position,
        production_step: values.production_step,
        notes: values.notes,
      })

      if (createRes.code !== 200) {
        message.error(createRes.message || '创建失败')
        setLoading(false)
        return
      }

      const recordId = createRes.data.id

      // 如果有附件，上传
      if (values.attachment?.length > 0) {
        const file = values.attachment[0].originFileObj
        if (file) {
          await uploadHazardAttachment(recordId, file)
        }
      }

      if (!saveOnly) {
        // 提交进入AI流程
        const submitRes = await submitHazardIdentification(recordId)
        if (submitRes.code !== 200) {
          message.error(submitRes.message || '提交失败')
          setLoading(false)
          return
        }
      }

      message.success(saveOnly ? '保存成功' : '提交成功，进入AI辨识流程')
      router.push(`/safety/hazard-identification/${recordId}`)
    } catch {
      if (!loading) {
        message.error('请完善表单信息')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Space className="mb-4">
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push('/safety/hazard-identification')}
        >
          返回列表
        </Button>
      </Space>

      <Title level={4} className="mb-2">
        新建危险源辨识
      </Title>

      <Card>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            hazard_id_no: `HI-${Date.now().toString(36).toUpperCase()}`,
          }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="hazard_id_no"
                label="危险源编号"
                rules={[{ required: true, message: '请输入编号' }]}
              >
                <Input placeholder="自动生成或手动输入" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="department"
                label="部门"
                rules={[{ required: true, message: '请输入部门' }]}
              >
                <Input placeholder="如：提取一车间" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="position"
                label="岗位"
                rules={[{ required: true, message: '请输入岗位' }]}
              >
                <Input placeholder="如：离心操作岗" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="production_step"
            label="生产步骤"
            rules={[{ required: true, message: '请输入生产步骤' }]}
          >
            <Input.TextArea
              rows={3}
              placeholder="详细描述生产步骤，包括操作名称、操作过程、涉及的设备设施和原辅料等"
            />
          </Form.Item>

          <Form.Item
            name="attachment"
            label="岗位资料附件"
            extra="上传岗位操作规程、SOP等资料，AI将据此解析识别危险源"
            valuePropName="fileList"
            getValueFromEvent={(e: unknown) =>
              Array.isArray(e) ? e : (e as { fileList?: unknown[] })?.fileList ?? []
            }
          >
            <Upload
              maxCount={1}
              beforeUpload={() => false}
              accept=".pdf,.docx,.xlsx,.xls,.txt,.md"
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
          </Form.Item>

          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="可选备注信息" />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              loading={loading && submitType === 'submit'}
              onClick={() => handleSubmit(false)}
            >
              提交并进入AI流程
            </Button>
            <Button
              loading={loading && submitType === 'save'}
              onClick={() => handleSubmit(true)}
            >
              仅保存草稿
            </Button>
            <Button onClick={() => router.push('/safety/hazard-identification')}>
              取消
            </Button>
          </Space>
        </Form>
      </Card>
    </div>
  )
}
