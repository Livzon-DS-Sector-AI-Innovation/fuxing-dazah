'use client'

import { useState } from 'react'
import {
  App,
  Button,
  ConfigProvider,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { antdTheme } from '@/lib/antd-theme'
import { fetchIntermediateTypesClient } from '@/lib/api/production-client'
import {
  createIntermediateType,
  updateIntermediateType,
  deleteIntermediateType,
} from '@/actions/production'
import type { IntermediateType } from '@/types/production'
import { ProductionQueryProvider } from '../ProductionQueryProvider'

// ── Modal 独立组件：form 实例与 Form 元素始终在同一组件内 ──

interface FormModalProps {
  open: boolean
  editItem: IntermediateType | null
  onClose: () => void
  onSaved: () => void
}

function IntermediateTypeFormModal({ open, editItem, onClose, onSaved }: FormModalProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()

  useEffect(() => {
    if (open) {
      form.setFieldsValue(
        editItem ?? { code: '', name: '', category: '', default_unit: '', description: '' },
      )
    }
  }, [open, editItem, form])

  const handleOk = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    let result
    if (editItem) {
      result = await updateIntermediateType(editItem.id, values)
    } else {
      result = await createIntermediateType(values as Parameters<typeof createIntermediateType>[0])
    }
    if (result.success) {
      message.success(editItem ? '中间体已更新' : '中间体已创建')
      onSaved()
    } else {
      message.error(result.error)
    }
  }

  return (
    <Modal
      title={editItem ? '编辑中间体' : '新增中间体'}
      open={open}
      onOk={handleOk}
      onCancel={onClose}
      destroyOnHidden
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="code"
          label="编码"
          rules={[{ required: true, message: '请输入编码' }]}
        >
          <Input maxLength={50} disabled={!!editItem} />
        </Form.Item>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: '请输入名称' }]}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item name="category" label="分类">
          <Input maxLength={100} placeholder="如：发酵液、结晶粉、湿品" />
        </Form.Item>
        <Form.Item name="default_unit" label="默认单位">
          <Input maxLength={20} placeholder="如：kg、L" />
        </Form.Item>
        <Form.Item name="description" label="说明">
          <Input.TextArea rows={2} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ── 表格主体 ──

function IntermediateTypesTable() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [modalOpen, setModalOpen] = useState(false)
  const [editItem, setEditItem] = useState<IntermediateType | null>(null)
  const [keyword, setKeyword] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['intermediate-types', keyword],
    queryFn: () => fetchIntermediateTypesClient({ keyword, page_size: 100 }),
  })

  const deleteMut = useMutation({
    mutationFn: deleteIntermediateType,
    onSuccess: () => {
      message.success('中间体已删除')
      queryClient.invalidateQueries({ queryKey: ['intermediate-types'] })
    },
    onError: (e: Error) => message.error(e.message),
  })

  const columns: ColumnsType<IntermediateType> = [
    { title: '编码', dataIndex: 'code', width: 150 },
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '分类', dataIndex: 'category', width: 120, render: v => v || '-' },
    { title: '默认单位', dataIndex: 'default_unit', width: 100, render: v => v || '-' },
    { title: '说明', dataIndex: 'description', ellipsis: true, render: v => v || '-' },
    {
      title: '操作',
      width: 140,
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" onClick={() => { setEditItem(r); setModalOpen(true) }}>
            编辑
          </Button>
          <Popconfirm
            title={`确定删除「${r.name}」?`}
            onConfirm={() => deleteMut.mutate(r.id)}
          >
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, fontWeight: 600, margin: '0 0 4px', color: '#1a1a1a' }}>
          中间体字典
        </h2>
        <span style={{ color: '#787671', fontSize: 14 }}>
          管理全局中间体编码，供工艺路线节点引用
        </span>
      </div>
      <div style={{ background: '#fff', borderRadius: 8, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
          <Input.Search
            placeholder="搜索编码或名称"
            allowClear
            style={{ width: 280 }}
            onSearch={v => setKeyword(v)}
          />
          <Button type="primary" onClick={() => { setEditItem(null); setModalOpen(true) }}>
            新增中间体
          </Button>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={isLoading}
          pagination={false}
          size="middle"
        />
      </div>
      <IntermediateTypeFormModal
        open={modalOpen}
        editItem={editItem}
        onClose={() => { setModalOpen(false); setEditItem(null) }}
        onSaved={() => {
          setModalOpen(false)
          setEditItem(null)
          queryClient.invalidateQueries({ queryKey: ['intermediate-types'] })
        }}
      />
    </div>
  )
}

export function IntermediateTypesPage() {
  return (
    <ProductionQueryProvider>
      <ConfigProvider theme={antdTheme} locale={zhCN}>
        <App>
          <IntermediateTypesTable />
        </App>
      </ConfigProvider>
    </ProductionQueryProvider>
  )
}
