'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Typography, Table, Button, Modal, Form, Input, InputNumber, Select,
  Space, App, Popconfirm, Upload, Card, Row, Col,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, UploadOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import {
  fetchStandardDocuments, createStandardDocument, updateStandardDocument, deleteStandardDocument,
  fetchStandardItems, createStandardItem, updateStandardItem, deleteStandardItem,
  importStandardDoc,
  type StandardDocument, type StandardItem,
} from '@/actions/quality'

const { Title, Paragraph } = Typography

export default function StandardsPage() {
  const { message } = App.useApp()
  const [docs, setDocs] = useState<StandardDocument[]>([])
  const [selectedDoc, setSelectedDoc] = useState<StandardDocument | null>(null)
  const [items, setItems] = useState<StandardItem[]>([])
  const [loading, setLoading] = useState(false)

  const [docModalOpen, setDocModalOpen] = useState(false)
  const [editingDoc, setEditingDoc] = useState<StandardDocument | null>(null)
  const [docForm] = Form.useForm()

  const [itemModalOpen, setItemModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<StandardItem | null>(null)
  const [itemForm] = Form.useForm()

  const loadDocs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchStandardDocuments()
      setDocs(res.data || [])
    } catch (err: any) {
      message.error(err.message || '加载标准文档失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  const loadItems = useCallback(async (docId: string) => {
    try {
      const res = await fetchStandardItems(docId)
      setItems(res.data || [])
    } catch (err: any) {
      message.error(err.message || '加载标准行失败')
    }
  }, [message])

  useEffect(() => { loadDocs() }, [loadDocs])
  useEffect(() => {
    if (selectedDoc) loadItems(selectedDoc.id)
  }, [selectedDoc, loadItems])

  const openDocModal = (doc?: StandardDocument) => {
    setEditingDoc(doc || null)
    docForm.resetFields()
    if (doc) docForm.setFieldsValue(doc)
    setDocModalOpen(true)
  }

  const handleDocSave = async () => {
    const values = await docForm.validateFields()
    try {
      if (editingDoc) {
        await updateStandardDocument(editingDoc.id, values)
        message.success('标准文档已更新')
      } else {
        const res = await createStandardDocument(values)
        message.success('标准文档已创建')
        setSelectedDoc({ ...values, id: res.data.id } as StandardDocument)
      }
      setDocModalOpen(false)
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '保存失败')
    }
  }

  const handleDocDelete = async (id: string) => {
    try {
      await deleteStandardDocument(id)
      message.success('已删除')
      if (selectedDoc?.id === id) setSelectedDoc(null)
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleImport = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importStandardDoc(fd)
      message.success(res.message || '导入完成')
      loadDocs()
    } catch (err: any) {
      message.error(err.message || '导入失败')
    }
    return false
  }

  const openItemModal = (item?: StandardItem) => {
    setEditingItem(item || null)
    itemForm.resetFields()
    if (item) itemForm.setFieldsValue(item)
    setItemModalOpen(true)
  }

  const handleItemSave = async () => {
    if (!selectedDoc) return
    const values = await itemForm.validateFields()
    try {
      if (editingItem) {
        await updateStandardItem(editingItem.id, values)
        message.success('标准行已更新')
      } else {
        await createStandardItem(selectedDoc.id, values)
        message.success('标准行已添加')
      }
      setItemModalOpen(false)
      loadItems(selectedDoc.id)
    } catch (err: any) {
      message.error(err.message || '保存失败')
    }
  }

  const handleItemDelete = async (id: string) => {
    try {
      await deleteStandardItem(id)
      message.success('已删除')
      if (selectedDoc) loadItems(selectedDoc.id)
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const docColumns: ColumnsType<StandardDocument> = [
    { title: '文件编号', dataIndex: 'file_no', key: 'file_no', width: 170 },
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name', ellipsis: true },
    { title: '代号', dataIndex: 'product_code', key: 'product_code', width: 80, render: (v: string | null) => v || '-' },
    { title: '版本', dataIndex: 'version', key: 'version', width: 70, render: (v: string | null) => v || '-' },
    { title: '操作', key: 'actions', width: 140,
      render: (_: any, d: StandardDocument) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openDocModal(d)} />
          <Popconfirm title="确认删除该标准文档及其全部标准行?" onConfirm={() => handleDocDelete(d.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const itemColumns: ColumnsType<StandardItem> = [
    { title: '序号', dataIndex: 'seq', key: 'seq', width: 60 },
    { title: '大类', dataIndex: 'category', key: 'category', width: 110, render: (v: string | null) => v || '-' },
    { title: '子项目', dataIndex: 'item_name', key: 'item_name', width: 170, ellipsis: true },
    { title: 'SOP号', dataIndex: 'sop_no', key: 'sop_no', width: 130 },
    { title: '标准', dataIndex: 'standard_text', key: 'standard_text', width: 200, ellipsis: true },
    { title: '来源', dataIndex: 'method_source', key: 'method_source', width: 110, render: (v: string | null) => v || '-' },
    { title: '备注', dataIndex: 'remark', key: 'remark', width: 140, ellipsis: true },
    { title: '操作', key: 'actions', width: 110,
      render: (_: any, it: StandardItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openItemModal(it)} />
          <Popconfirm title="确认删除?" onConfirm={() => handleItemDelete(it.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div>
        <Title level={3}><FileTextOutlined /> 质量标准库</Title>
        <Paragraph type="secondary">
          一份标准文档 = 一个产品代号；项目行以 SOP 号为匹配键（同名项目不同 SOP 互不串）。纯文字标准不收录。
        </Paragraph>
      </div>

      <Card size="small" title="标准文档" extra={
        <Space>
          <Upload accept=".doc,.docx" showUploadList={false} beforeUpload={handleImport}>
            <Button icon={<UploadOutlined />}>导入 .doc/.docx</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openDocModal()}>新建文档</Button>
        </Space>
      }>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={docColumns}
          dataSource={docs}
          pagination={false}
          onRow={(d) => ({
            onClick: () => setSelectedDoc(d),
            style: { cursor: 'pointer', background: selectedDoc?.id === d.id ? '#e6f4ff' : undefined },
          })}
        />
      </Card>

      {selectedDoc && (
        <Card size="small" title={`标准项目行 —— ${selectedDoc.file_no}（${selectedDoc.product_name}）`} extra={
          <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => openItemModal()}>添加标准行</Button>
        }>
          <Table
            rowKey="id"
            size="small"
            columns={itemColumns}
            dataSource={items}
            pagination={false}
            scroll={{ x: 1100 }}
          />
        </Card>
      )}

      <Modal
        title={editingDoc ? '编辑标准文档' : '新建标准文档'}
        open={docModalOpen}
        onCancel={() => setDocModalOpen(false)}
        onOk={handleDocSave}
        okText="保存"
        width={600}
      >
        <Form form={docForm} layout="vertical" className="mt-4">
          <Row gutter={12}>
            <Col span={12}><Form.Item name="file_no" label="文件编号" rules={[{ required: true, message: '请输入文件编号' }]}><Input placeholder="SOP.02.3292.003" /></Form.Item></Col>
            <Col span={12}><Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请输入产品名称' }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="product_code" label="产品代号"><Input placeholder="HAS" /></Form.Item></Col>
            <Col span={8}><Form.Item name="product_internal_code" label="产品代码"><Input placeholder="30205" /></Form.Item></Col>
            <Col span={8}><Form.Item name="version" label="版本"><Input placeholder="003" /></Form.Item></Col>
            <Col span={8}><Form.Item name="specification" label="规格"><Input placeholder="5kg/听" /></Form.Item></Col>
            <Col span={8}><Form.Item name="valid_years" label="有效期"><Input placeholder="36个月" /></Form.Item></Col>
            <Col span={8}><Form.Item name="effective_date" label="生效日期"><Input placeholder="2026年07月27日" /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title={editingItem ? '编辑标准行' : '添加标准行'}
        open={itemModalOpen}
        onCancel={() => setItemModalOpen(false)}
        onOk={handleItemSave}
        okText="保存"
        width={640}
      >
        <Form form={itemForm} layout="vertical" className="mt-4">
          <Row gutter={12}>
            <Col span={8}><Form.Item name="seq" label="序号"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={16}><Form.Item name="category" label="检验项目大类"><Input placeholder="性状 / 有关物质" /></Form.Item></Col>
            <Col span={12}><Form.Item name="item_name" label="子项目名称" rules={[{ required: true, message: '请输入子项目名称' }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="sop_no" label="SOP号（匹配键）" rules={[{ required: true, message: '请输入 SOP 号' }]}><Input placeholder="SOP.03.5214" /></Form.Item></Col>
            <Col span={24}><Form.Item name="standard_text" label="合格标准原文" rules={[{ required: true, message: '请输入标准' }]}><Input placeholder="≤3.0%" /></Form.Item></Col>
            <Col span={8}>
              <Form.Item name="operator" label="运算符" initialValue="≤">
                <Select options={[{ value: '≤', label: '≤' }, { value: '≥', label: '≥' }, { value: '<', label: '<' }, { value: '>', label: '>' }, { value: '范围', label: '范围' }]} />
              </Form.Item>
            </Col>
            <Col span={8}><Form.Item name="limit_min" label="下限"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="limit_max" label="上限"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="method_source" label="方法来源"><Input placeholder="IP / Ph.Eur. / 内部" /></Form.Item></Col>
            <Col span={12}><Form.Item name="remark" label="备注"><Input /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}
