'use client'

import { useEffect, useState } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space, Upload } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload'
import { useEquipmentStore } from '@/stores/equipment'
import { createWorkOrder, uploadWorkOrderImages } from '@/actions/equipment'
import { CreateWorkOrderInput, FailureCode, Maintainer } from '@/types/equipment'
import { fetchAllUsersClient } from '@/lib/api/equipment-client'

const { TextArea } = Input

interface RepairDrawerProps {
  equipments: { id: string; equipment_no: string; name: string; importance?: string; responsible_person_id?: string | null }[]
  symptoms?: FailureCode[]
  onRefresh?: () => void
}

export function RepairDrawer({ equipments, symptoms, onRefresh }: RepairDrawerProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [maintainers, setMaintainers] = useState<Maintainer[]>([])
  const { repairDrawerOpen, repairEquipmentId, closeRepairDrawer } = useEquipmentStore()

  const selectedEquipment = equipments.find(e => e.id === repairEquipmentId)

  useEffect(() => {
    if (repairDrawerOpen) {
      form.resetFields()
      const defaultPriority = selectedEquipment?.importance ?? '中'
      form.setFieldsValue({
        equipment_id: repairEquipmentId,
        order_type: '故障维修',
        priority: defaultPriority,
      })
      setFileList([])
      fetchAllUsersClient().then(setMaintainers).catch(() => {})
      // 默认填入设备责任人
      if (selectedEquipment?.responsible_person_id) {
        form.setFieldsValue({ responsible_person_id: selectedEquipment.responsible_person_id })
      }
    }
  }, [repairDrawerOpen, repairEquipmentId, form, selectedEquipment?.importance])

  const handleSubmit = async () => {
    try {
      setSubmitting(true)
      const values = await form.validateFields()
      const data: CreateWorkOrderInput = {
        equipment_id: repairEquipmentId!,
        order_type: '故障维修',
        priority: values.priority,
        fault_symptom_id: values.fault_symptom_id || undefined,
        fault_description: values.fault_description || undefined,
        responsible_person_id: values.responsible_person_id,
      }
      const result = await createWorkOrder(data)
      const workOrderId = (result as { id?: string } | null)?.id

      if (!workOrderId) {
        message.error('工单创建失败，请稍后重试')
        return
      }

      if (fileList.length > 0) {
        const formData = new FormData()
        fileList.forEach((file) => {
          if (file.originFileObj) {
            formData.append('files', file.originFileObj)
          }
        })
        await uploadWorkOrderImages(workOrderId, formData)
      }

      message.success('报修工单已提交')
      closeRepairDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      title="报故障维修"
      size={480}
      open={repairDrawerOpen}
      onClose={closeRepairDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeRepairDrawer}>取消</Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            提交工单
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve={false}>
        <Form.Item name="equipment_id" label="关联设备">
          <div style={{ padding: '8px 12px', background: '#f5f4f2', borderRadius: 6, fontSize: 14, color: '#37352f' }}>
            {selectedEquipment ? `${selectedEquipment.equipment_no} - ${selectedEquipment.name}` : '-'}
          </div>
        </Form.Item>
        <Form.Item name="order_type" label="工单类型">
          <div style={{ padding: '8px 12px', background: '#f5f4f2', borderRadius: 6, fontSize: 14, color: '#dd5b00', fontWeight: 500 }}>
            故障维修
          </div>
        </Form.Item>
        <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
          <Select
            options={[
              { label: '紧急', value: '紧急' },
              { label: '高', value: '高' },
              { label: '中', value: '中' },
              { label: '低', value: '低' },
            ]}
          />
        </Form.Item>
        <Form.Item name="fault_symptom_id" label="故障现象">
          <Select
            placeholder="选择故障现象（可选）"
            allowClear
            showSearch
            optionFilterProp="label"
            options={(symptoms || []).map((s) => ({ label: `${s.code} - ${s.name}`, value: s.id }))}
          />
        </Form.Item>
        <Form.Item name="fault_description" label="故障描述">
          <TextArea placeholder="请描述故障情况" rows={4} maxLength={500} showCount />
        </Form.Item>
        <Form.Item name="responsible_person_id" label="责任人" rules={[{ required: true, message: '请选择责任人' }]}>
          <Select
            placeholder="选择责任人"
            showSearch
            optionFilterProp="label"
            options={maintainers.map((m) => ({
              label: `${m.name} (${m.employee_no || '-'})`,
              value: m.user_id,
            }))}
          />
        </Form.Item>
        <Form.Item label="故障图片">
          <Upload
            listType="picture-card"
            fileList={fileList}
            onChange={({ fileList: newList }) => setFileList(newList)}
            beforeUpload={() => false}
            maxCount={9}
            accept="image/*"
          >
            {fileList.length < 9 && (
              <div>
                <PlusOutlined />
                <div style={{ marginTop: 8 }}>上传</div>
              </div>
            )}
          </Upload>
        </Form.Item>
      </Form>
    </Drawer>
  )
}
