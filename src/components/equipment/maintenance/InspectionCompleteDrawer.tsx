'use client'

import { useEffect } from 'react'
import { App, Drawer, Form, Input, Select, Button, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEquipmentStore } from '@/stores/equipment'
import { completeInspection } from '@/actions/equipment'
import { InspectionRecordItem, InspectionTemplateItem } from '@/types/equipment'

const { Text } = Typography

interface InspectionCompleteDrawerProps {
  onRefresh?: () => void
}

interface InspectionRow extends InspectionTemplateItem {
  result: '正常' | '异常' | '跳过'
  actual_value: string
  remark: string
}

export function InspectionCompleteDrawer({ onRefresh }: InspectionCompleteDrawerProps) {
  const { message } = App.useApp()
  const {
    inspectionCompleteDrawerOpen, completingWorkOrderId, completingTemplateName, completingTemplateItems,
    closeInspectionCompleteDrawer,
  } = useEquipmentStore()

  const [form] = Form.useForm<{ records: InspectionRow[] }>()
  const records = Form.useWatch(['records'], form) as InspectionRow[] | undefined

  useEffect(() => {
    if (inspectionCompleteDrawerOpen && completingTemplateItems.length > 0) {
      form.setFieldsValue({
        records: completingTemplateItems.map((item) => ({
          ...item,
          result: '正常' as const,
          actual_value: '',
          remark: '',
        })),
      })
    }
  }, [inspectionCompleteDrawerOpen, completingTemplateItems, form])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const records: InspectionRecordItem[] = values.records.map((row) => ({
        item_id: row.id,
        result: row.result,
        actual_value: row.actual_value || undefined,
        remark: row.remark || undefined,
      }))
      await completeInspection(completingWorkOrderId!, { records })
      message.success('巡检完成')
      closeInspectionCompleteDrawer()
      onRefresh?.()
    } catch (error: any) {
      if (error?.message) message.error(error.message)
    }
  }

  const columns: ColumnsType<InspectionRow> = [
    {
      title: '检查项', dataIndex: 'item_name', key: 'item_name', width: 150,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '预期结果', dataIndex: 'expected_result', key: 'expected_result', width: 140,
      render: (v: string | null) => v || '-',
    },
    {
      title: '检查方法', dataIndex: 'check_method', key: 'check_method', width: 140,
      render: (v: string | null) => v || '-',
    },
    {
      title: '检查结果', key: 'result', width: 120,
      render: (_: unknown, __: InspectionRow, index: number) => (
        <Form.Item name={['records', index, 'result']} noStyle>
          <Select
            options={[
              { label: '正常', value: '正常' },
              { label: '异常', value: '异常' },
              { label: '跳过', value: '跳过' },
            ]}
            style={{ width: 100 }}
          />
        </Form.Item>
      ),
    },
    {
      title: '实际值', key: 'actual_value', width: 150,
      render: (_: unknown, __: InspectionRow, index: number) => (
        <Form.Item name={['records', index, 'actual_value']} noStyle>
          <Input placeholder="实际值" />
        </Form.Item>
      ),
    },
    {
      title: '备注', key: 'remark', width: 180,
      render: (_: unknown, __: InspectionRow, index: number) => (
        <Form.Item name={['records', index, 'remark']} noStyle>
          <Input placeholder="备注" />
        </Form.Item>
      ),
    },
  ]

  return (
    <Drawer
      title={`巡检完成 - ${completingTemplateName || ''}`}
      size={900}
      open={inspectionCompleteDrawerOpen}
      onClose={closeInspectionCompleteDrawer}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={closeInspectionCompleteDrawer}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>提交巡检</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Table
          columns={columns}
          dataSource={records || []}
          rowKey="id"
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={false}
        />
      </Form>
    </Drawer>
  )
}
