'use client'

import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  DatePicker,
  Tag,
  Row,
  Col,
  Segmented,
  Typography,
  App,
  Card,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  PlusOutlined,
  SearchOutlined,
  EditOutlined,
  DeleteOutlined,
  SendOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useSafetyStore } from '@/stores/safety'
import {
  getDailyRiskReports,
  createDailyRiskReport,
  updateDailyRiskReport,
  deleteDailyRiskReport,
  submitDailyRiskReport,
  approveDailyRiskReport,
  rejectDailyRiskReport,
} from '@/actions/safety'
import type { DailyRiskReport, DailyRiskReportFormData, HazardRiskOption } from '@/types/safety'
import { REPORT_STATUS_OPTIONS, RISK_LEVEL_OPTIONS, REPORT_TYPE_OPTIONS } from '@/types/safety'
import HazardSelectModal from './HazardSelectModal'
import dayjs from 'dayjs'

const { Text } = Typography
const { TextArea } = Input

export default function RiskReportPanel() {
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [rejectVisible, setRejectVisible] = useState(false)
  const [rejectId, setRejectId] = useState<string>('')
  const [rejectReason, setRejectReason] = useState('')
  const [editingRecord, setEditingRecord] = useState<DailyRiskReport | null>(null)
  const [searchText, setSearchText] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [reportTypeFilter, setReportTypeFilter] = useState<string | undefined>()
  const [hazardModalOpen, setHazardModalOpen] = useState(false)
  const [selectedHazard, setSelectedHazard] = useState<HazardRiskOption | null>(null)
  const { message } = App.useApp()

  const {
    dailyRiskReports,
    dailyRiskReportTotal,
    dailyRiskReportQueryParams,
    setDailyRiskReports,
    setDailyRiskReportTotal,
    setDailyRiskReportQueryParams,
    addDailyRiskReport,
    updateDailyRiskReport: updateInStore,
    removeDailyRiskReport,
  } = useSafetyStore()

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await getDailyRiskReports({
        ...dailyRiskReportQueryParams,
        status: statusFilter,
        report_type: reportTypeFilter,
        keyword: searchText || undefined,
      })
      if (response.code === 200) {
        setDailyRiskReports(response.data as DailyRiskReport[])
        setDailyRiskReportTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载每日风险作业报备列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [dailyRiskReportQueryParams.page, dailyRiskReportQueryParams.page_size, statusFilter, reportTypeFilter])

  const handleSearch = () => {
    setDailyRiskReportQueryParams({ page: 1 })
    loadData()
  }

  const handleAdd = () => {
    setEditingRecord(null)
    setSelectedHazard(null)
    form.resetFields()
    form.setFieldsValue({ report_type: 'regular' })
    setModalVisible(true)
  }

  const handleEdit = (record: DailyRiskReport) => {
    setEditingRecord(record)
    setSelectedHazard(null)
    editForm.setFieldsValue({
      ...record,
      report_date: record.report_date ? dayjs(record.report_date) : undefined,
      planned_start_time: record.planned_start_time ? dayjs(record.planned_start_time) : undefined,
      planned_end_time: record.planned_end_time ? dayjs(record.planned_end_time) : undefined,
    })
    setModalVisible(true)
  }

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该风险作业报备吗？',
      onOk: async () => {
        const response = await deleteDailyRiskReport(id)
        if (response.code === 200) { message.success('删除成功'); removeDailyRiskReport(id) }
        else { message.error(response.message || '删除失败') }
      },
    })
  }

  const handleHazardSelect = (hazard: HazardRiskOption) => {
    setSelectedHazard(hazard)
    // 回填：作业地点、作业内容、控制措施
    const activeForm = editingRecord ? editForm : form
    activeForm.setFieldsValue({
      hazard_identification_id: hazard.id,
      location: hazard.position || '',
      operation_description: hazard.specific_activity || '',
      control_measures: [
        hazard.existing_engineering_controls,
        hazard.existing_management_controls,
        hazard.existing_ppe,
        hazard.existing_emergency_measures,
      ].filter(Boolean).join('；'),
      risk_level: hazard.inherent_risk_level || '',
    })
    setHazardModalOpen(false)
  }

  const handleSubmit = async () => {
    try {
      const values = editingRecord ? await editForm.validateFields() : await form.validateFields()
      const formattedValues = {
        ...values,
        report_date: values.report_date ? values.report_date.toISOString() : undefined,
        planned_start_time: values.planned_start_time ? values.planned_start_time.toISOString() : undefined,
        planned_end_time: values.planned_end_time ? values.planned_end_time.toISOString() : undefined,
      }

      if (editingRecord) {
        // 编辑时不发送 report_type（不可修改）
        const { report_type, ...updateValues } = formattedValues
        const response = await updateDailyRiskReport(editingRecord.id, updateValues)
        if (response.code === 200) { message.success('更新成功'); updateInStore(editingRecord.id, response.data as DailyRiskReport); setModalVisible(false) }
        else { message.error(response.message || '更新失败') }
      } else {
        const response = await createDailyRiskReport(formattedValues as DailyRiskReportFormData)
        if (response.code === 200) { message.success('创建成功'); addDailyRiskReport(response.data as DailyRiskReport); setModalVisible(false); form.resetFields() }
        else { message.error(response.message || '创建失败') }
      }
    } catch { /* 表单验证失败 */ }
  }

  const handleSubmitFlow = async (id: string) => {
    const response = await submitDailyRiskReport(id)
    if (response.code === 200) { message.success('已提交'); updateInStore(id, response.data as DailyRiskReport) }
    else { message.error(response.message || '提交失败') }
  }

  const handleApprove = async (id: string) => {
    const response = await approveDailyRiskReport(id)
    if (response.code === 200) { message.success('已审批'); updateInStore(id, response.data as DailyRiskReport) }
    else { message.error(response.message || '审批失败') }
  }

  const handleOpenReject = (id: string) => {
    setRejectId(id)
    setRejectReason('')
    setRejectVisible(true)
  }

  const handleRejectConfirm = async () => {
    if (!rejectReason.trim()) { message.error('请填写驳回原因'); return }
    const response = await rejectDailyRiskReport(rejectId, rejectReason)
    if (response.code === 200) { message.success('已驳回'); updateInStore(rejectId, response.data as DailyRiskReport); setRejectVisible(false) }
    else { message.error(response.message || '驳回失败') }
  }

  const reportTypeFilterValue = Form.useWatch('report_type', editingRecord ? editForm : form)

  const columns: ColumnsType<DailyRiskReport> = [
    { title: '报备编号', dataIndex: 'report_no', key: 'report_no', width: 140 },
    {
      title: '作业日期', dataIndex: 'report_date', key: 'report_date', width: 110,
      render: (d: string) => d ? dayjs(d).format('YYYY-MM-DD') : '-',
    },
    {
      title: '报备类型', dataIndex: 'report_type', key: 'report_type', width: 100,
      render: (t: string) => {
        const opt = REPORT_TYPE_OPTIONS.find(o => o.value === t)
        return <Tag color={opt?.color}>{opt?.label || t}</Tag>
      },
    },
    { title: '部门', dataIndex: 'department', key: 'department', width: 100, ellipsis: true },
    { title: '作业描述', dataIndex: 'operation_description', key: 'operation_description', width: 200, ellipsis: true },
    {
      title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', width: 100,
      render: (r: string) => {
        const opt = RISK_LEVEL_OPTIONS.find(o => o.value === r)
        return <Tag color={opt?.color}>{opt?.label || r || '-'}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => {
        const opt = REPORT_STATUS_OPTIONS.find(x => x.value === s)
        return <Tag color={opt?.color}>{opt?.label || s}</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 260, fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          {record.status === 'draft' && (
            <Button type="link" size="small" icon={<SendOutlined />} onClick={() => handleSubmitFlow(record.id)}>提交</Button>
          )}
          {record.status === 'submitted' && (
            <>
              <Button type="link" size="small" icon={<CheckCircleOutlined />} onClick={() => handleApprove(record.id)}>审批</Button>
              <Button type="link" size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleOpenReject(record.id)}>驳回</Button>
            </>
          )}
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const renderForm = (isEdit: boolean) => {
    const activeForm = isEdit ? editForm : form
    const reportType = isEdit ? editingRecord?.report_type : reportTypeFilterValue

    return (
      <>
        {/* 报备类型 */}
        <div style={{ marginBottom: 24 }}>
          <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>报备类型</Text>
          <Form.Item name="report_type" noStyle rules={[{ required: true, message: '请选择报备类型' }]}>
            <Segmented
              options={[
                { value: 'regular', label: '常规作业' },
                { value: 'non_regular', label: '非常规作业' },
              ]}
              disabled={isEdit}
              block
            />
          </Form.Item>
          {isEdit && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
              报备类型创建后不可修改
            </Text>
          )}
        </div>

        {/* 基础信息 */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>基础信息</Text>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="report_no" label="报备编号" rules={[{ required: true, message: '请输入报备编号' }]}>
                <Input placeholder="请输入报备编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="report_date" label="作业日期" rules={[{ required: true, message: '请选择作业日期' }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="department" label="报备部门">
            <Input placeholder="请输入报备部门" />
          </Form.Item>
        </div>

        {/* 常规作业 */}
        {reportType === 'regular' && (
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>常规作业 — 关联危险源</Text>

            <Form.Item name="hazard_identification_id" label="关联危险源" rules={[{ required: true, message: '请选择关联的危险源' }]} hidden>
              <Input />
            </Form.Item>

            <Card
              size="small"
              style={{ marginBottom: 16, background: '#fafaf9', borderRadius: 8, border: '1px solid #e5e3df' }}
              styles={{ body: { padding: 12 } }}
            >
              {selectedHazard ? (
                <div>
                  <Text strong>{selectedHazard.hazard_id_no}</Text>
                  <Text type="secondary" style={{ marginLeft: 12 }}>{selectedHazard.specific_activity || '-'}</Text>
                  <Tag color="red" style={{ marginLeft: 8 }}>{selectedHazard.inherent_risk_label || selectedHazard.inherent_risk_level}</Tag>
                </div>
              ) : (
                <Text type="secondary">暂未选择危险源</Text>
              )}
              <Button type="link" size="small" onClick={() => setHazardModalOpen(true)} style={{ padding: 0, marginTop: 8 }}>
                选择危险源
              </Button>
            </Card>

            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
              选择危险源后自动回填作业地点、作业内容和控制措施
            </Text>

            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="location" label="作业地点">
                  <Input placeholder="自动回填" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="risk_level" label="风险等级">
                  <Select options={RISK_LEVEL_OPTIONS.map(o => ({ value: o.value, label: o.label }))} placeholder="自动回填" />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item name="operation_description" label="作业内容描述" rules={[{ required: true, message: '请输入作业内容描述' }]}>
              <TextArea rows={2} placeholder="自动回填" />
            </Form.Item>

            <Form.Item name="control_measures" label="控制措施">
              <TextArea rows={3} placeholder="自动回填" />
            </Form.Item>
          </div>
        )}

        {/* 非常规作业 */}
        {reportType === 'non_regular' && (
          <div style={{ marginBottom: 16 }}>
            <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>非常规作业</Text>

            <Form.Item name="operation_description" label="风险作业描述" rules={[{ required: true, message: '请输入风险作业描述' }]}>
              <TextArea rows={3} placeholder="请输入风险作业描述" />
            </Form.Item>

            <Form.Item name="operation_steps" label="作业步骤">
              <TextArea rows={3} placeholder="请输入作业步骤" />
            </Form.Item>

            <Form.Item name="control_measures" label="控制措施">
              <TextArea rows={3} placeholder="请输入控制措施" />
            </Form.Item>
          </div>
        )}

        {/* 人员与时间 */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 12 }}>人员与时间</Text>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="planned_start_time" label="计划开始时间">
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="planned_end_time" label="计划结束时间">
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="applicant_name" label="申请人">
                <Input placeholder="申请人" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="approver_name" label="审批人">
                <Input placeholder="审批人" />
              </Form.Item>
            </Col>
          </Row>
        </div>

        {/* 备注 */}
        <Form.Item name="notes" label="备注">
          <TextArea rows={2} placeholder="备注" />
        </Form.Item>
      </>
    )
  }

  return (
    <>
      {/* Filter Bar */}
      <Card
        style={{ marginBottom: 16, borderRadius: 12, border: '1px solid #e5e3df', background: '#f6f5f4' }}
        styles={{ body: { padding: '16px 20px' } }}
      >
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space wrap>
              <Input
                placeholder="搜索编号/作业描述/部门"
                prefix={<SearchOutlined />}
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                onPressEnter={handleSearch}
                style={{ width: 240 }}
                allowClear
              />
              <Select
                placeholder="报备类型"
                allowClear
                value={reportTypeFilter}
                onChange={v => { setReportTypeFilter(v); setDailyRiskReportQueryParams({ page: 1 }) }}
                style={{ width: 130 }}
                options={REPORT_TYPE_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
              />
              <Select
                placeholder="状态"
                allowClear
                value={statusFilter}
                onChange={v => { setStatusFilter(v); setDailyRiskReportQueryParams({ page: 1 }) }}
                style={{ width: 120 }}
                options={REPORT_STATUS_OPTIONS.map(o => ({ value: o.value, label: o.label }))}
              />
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>查询</Button>
            </Space>
          </Col>
          <Col>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新建报备</Button>
          </Col>
        </Row>
      </Card>

      {/* Table */}
      <Card style={{ borderRadius: 12, border: '1px solid #e5e3df' }} styles={{ body: { padding: 16 } }}>
        <Table
          columns={columns}
          dataSource={dailyRiskReports}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1100 }}
          pagination={{
            current: dailyRiskReportQueryParams.page,
            pageSize: dailyRiskReportQueryParams.page_size,
            total: dailyRiskReportTotal,
            showSizeChanger: true,
            showTotal: t => `共 ${t} 条`,
            onChange: (page, pageSize) => setDailyRiskReportQueryParams({ page, page_size: pageSize }),
          }}
        />
      </Card>

      {/* Create/Edit Modal */}
      <Modal
        title={editingRecord ? '编辑关键风险作业报备' : '新建关键风险作业报备'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={800}
        okText="确认保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={editingRecord ? editForm : form} layout="vertical">
          {renderForm(!!editingRecord)}
        </Form>
      </Modal>

      {/* Reject Modal */}
      <Modal
        title="驳回原因"
        open={rejectVisible}
        onOk={handleRejectConfirm}
        onCancel={() => setRejectVisible(false)}
        okText="确认驳回"
        cancelText="取消"
      >
        <TextArea rows={4} placeholder="请输入驳回原因" value={rejectReason} onChange={e => setRejectReason(e.target.value)} />
      </Modal>

      {/* Hazard Select Modal */}
      <HazardSelectModal
        open={hazardModalOpen}
        onSelect={handleHazardSelect}
        onClose={() => setHazardModalOpen(false)}
      />
    </>
  )
}
