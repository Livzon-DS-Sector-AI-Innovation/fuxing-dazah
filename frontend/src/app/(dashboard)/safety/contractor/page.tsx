'use client'

import { useEffect, useState } from 'react'
import {
  Table, Button, Space, Input, Select, Modal, Form, DatePicker, InputNumber, message, Tag, Card, Row, Col, Typography, Tabs,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined, SearchOutlined, EditOutlined, DeleteOutlined, StopOutlined, CheckCircleOutlined, TeamOutlined,
} from '@ant-design/icons'
import {
  getContractors, createContractor, updateContractor, deleteContractor,
  blacklistContractor, activateContractor, updateContractorTraining,
} from '@/actions/safety'
import type { Contractor, ContractorFormData, QualificationTypeEnum } from '@/types/safety'
import {
  CONTRACTOR_STATUS_OPTIONS, QUALIFICATION_TYPE_OPTIONS, QUALIFICATION_LEVEL_OPTIONS, CONTRACTOR_TRAINING_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'


export default function ContractorPage() {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<Contractor | null>(null)
  const [data, setData] = useState<Contractor[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [trainingFilter, setTrainingFilter] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [tab, setTab] = useState('list')

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getContractors({
        page, page_size: pageSize, status: statusFilter,
        qualification_type: typeFilter, training_status: trainingFilter, keyword: keyword || undefined,
      })
      if (response.code === 200) {
        setData(response.data)
        setTotal(response.meta?.total || 0)
      }
    } catch { message.error('加载承包商列表失败') } finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [page, pageSize, statusFilter, typeFilter, trainingFilter])

  const handleAdd = () => { setEditingRecord(null); form.resetFields(); setModalVisible(true) }

  const handleEdit = (record: Contractor) => {
    setEditingRecord(record)
    form.setFieldsValue({ ...record })
    setModalVisible(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingRecord) {
        const response = await updateContractor(editingRecord.id, values)
        if (response.code === 200) { message.success('更新成功'); setModalVisible(false); loadData() }
        else message.error(response.message || '更新失败')
      } else {
        const response = await createContractor(values as ContractorFormData)
        if (response.code === 200) { message.success('创建成功'); setModalVisible(false); form.resetFields(); loadData() }
        else message.error(response.message || '创建失败')
      }
    } catch { /* validation error */ }
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除', content: '确定要删除这个承包商吗？',
      onOk: async () => {
        const response = await deleteContractor(id)
        if (response.code === 200) { message.success('删除成功'); loadData() }
        else message.error(response.message || '删除失败')
      },
    })
  }

  const handleBlacklist = async (id: string) => {
    const response = await blacklistContractor(id)
    if (response.code === 200) { message.success('已加入黑名单'); loadData() }
    else message.error(response.message || '操作失败')
  }

  const handleActivate = async (id: string) => {
    const response = await activateContractor(id)
    if (response.code === 200) { message.success('已激活'); loadData() }
    else message.error(response.message || '操作失败')
  }

  const handleTrainingUpdate = async (id: string, trainingStatus: string) => {
    const response = await updateContractorTraining(id, trainingStatus)
    if (response.code === 200) { message.success('培训状态已更新'); loadData() }
    else message.error(response.message || '操作失败')
  }

  const columns: ColumnsType<Contractor> = [
    { title: '编号', dataIndex: 'contractor_no', key: 'contractor_no', width: 130 },
    { title: '公司名称', dataIndex: 'company_name', key: 'company_name', width: 180, ellipsis: true },
    { title: '资质类型', dataIndex: 'qualification_type', key: 'qualification_type', width: 100,
      render: (t: QualificationTypeEnum) => {
        const opt = QUALIFICATION_TYPE_OPTIONS.find(o => o.value === t)
        return <Tag>{opt?.label || t}</Tag>
      },
    },
    { title: '联系人', dataIndex: 'contact_person', key: 'contact_person', width: 100 },
    { title: '培训状态', dataIndex: 'training_status', key: 'training_status', width: 90,
      render: (s: string) => {
        const opt = CONTRACTOR_TRAINING_STATUS_OPTIONS.find(o => o.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    { title: '安全绩效', dataIndex: 'safety_performance_score', key: 'score', width: 90,
      render: (s: number | undefined) => s !== undefined && s !== null ? `${s}分` : '-',
    },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const opt = CONTRACTOR_STATUS_OPTIONS.find(o => o.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    { title: '操作', key: 'action', width: 320, fixed: 'right',
      render: (_, r) => (
        <Space size="small">
          {r.status !== 'blacklisted' && (
            <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => handleBlacklist(r.id)}>拉黑</Button>
          )}
          {r.status !== 'active' && (
            <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleActivate(r.id)}>激活</Button>
          )}
          {r.training_status !== 'passed' && (
            <Button type="link" size="small" icon={<TeamOutlined />} onClick={() => handleTrainingUpdate(r.id, 'passed')}>培训合格</Button>
          )}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="p-6">
      <Card
        title="承包商管理"
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建承包商</Button>}
      >
        <Row gutter={16} className="mb-4">
          <Col span={4}><Input placeholder="搜索" prefix={<SearchOutlined />} value={keyword} onChange={e => setKeyword(e.target.value)} onPressEnter={loadData} /></Col>
          <Col span={4}><Select placeholder="状态" allowClear value={statusFilter} onChange={v => { setStatusFilter(v); setPage(1) }} style={{ width: '100%' }} options={CONTRACTOR_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} /></Col>
          <Col span={4}><Select placeholder="资质类型" allowClear value={typeFilter} onChange={v => { setTypeFilter(v); setPage(1) }} style={{ width: '100%' }} options={QUALIFICATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} /></Col>
          <Col span={4}><Select placeholder="培训状态" allowClear value={trainingFilter} onChange={v => { setTrainingFilter(v); setPage(1) }} style={{ width: '100%' }} options={CONTRACTOR_TRAINING_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))} /></Col>
          <Col span={3}><Button type="primary" icon={<SearchOutlined />} onClick={loadData}>查询</Button></Col>
        </Row>

        <Table columns={columns} dataSource={data} rowKey="id" loading={loading} scroll={{ x: 1400 }}
          pagination={{ current: page, pageSize, total, showSizeChanger: true, showQuickJumper: true, showTotal: (t) => `共 ${t} 条`, onChange: (p, ps) => { setPage(p); setPageSize(ps) } }} />
      </Card>

      <Modal title={editingRecord ? '编辑承包商' : '新建承包商'} open={modalVisible} onOk={handleSubmit} onCancel={() => setModalVisible(false)} width={900} okText="确认" cancelText="取消">
        <Form form={form} layout="vertical" initialValues={editingRecord || { qualification_type: 'other' }}>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="contractor_no" label="承包商编号" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="company_name" label="公司名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="qualification_type" label="资质类型" rules={[{ required: true }]}><Select options={QUALIFICATION_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="legal_representative" label="法定代表人"><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="contact_person" label="联系人" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={8}><Form.Item name="contact_phone" label="联系电话"><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="business_scope" label="经营范围"><Input.TextArea rows={2} /></Form.Item>
          <Row gutter={16}>
            <Col span={6}><Form.Item name="qualification_level" label="资质等级"><Select options={QUALIFICATION_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} /></Form.Item></Col>
            <Col span={6}><Form.Item name="qualification_cert_no" label="资质证书编号"><Input /></Form.Item></Col>
            <Col span={6}><Form.Item name="qualification_expiry" label="资质有效期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={6}><Form.Item name="safety_license_no" label="安全许可证"><Input /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="safety_license_expiry" label="安全许可证有效期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="insurance_expiry" label="保险有效期"><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="insurance_info" label="保险信息"><Input /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="safety_officer_name" label="安全负责人"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="safety_officer_phone" label="安全负责人电话"><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
