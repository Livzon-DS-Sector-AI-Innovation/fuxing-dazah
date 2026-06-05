'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  Upload,
  message,
  Tag,
  Card,
  Row,
  Col,
  Typography,
  Tabs,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UploadProps } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  EyeOutlined,
  DeleteOutlined,
  EditOutlined,
  UploadOutlined,
  CheckCircleOutlined,
  LinkOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import {
  getHazardIdentifications,
  deleteHazardIdentification,
  getHazardRevisionRecords,
  createHazardRevisionRecord,
  updateHazardRevisionRecord,
  deleteHazardRevisionRecord,
  approveHazardRevision,
  uploadHazardRevisionDocument,
  linkRevisionToArchive,
  getHazardRevisionArchives,
  createHazardRevisionArchive,
  updateHazardRevisionArchive,
  deleteHazardRevisionArchive,
  getRevisions,
} from '@/actions/safety'
import type {
  HazardIdentification,
  HazardRevisionRecord,
  HazardRevisionRecordFormData,
  HazardRevisionArchive,
  HazardRevisionArchiveFormData,
  RegulationRevision,
} from '@/types/safety'
import {
  AI_NODE_PROGRESS_OPTIONS,
  OVERALL_STATUS_OPTIONS_HI,
  RISK_LEVEL_OPTIONS,
  IDENTIFICATION_TYPE_OPTIONS,
  REVIEW_OPINION_OPTIONS,
  ARCHIVE_STATUS_OPTIONS,
} from '@/types/safety'
import dayjs from 'dayjs'
import { useSafetyStore } from '@/stores/safety'

const { Text } = Typography

export default function HazardIdentificationPage() {
  const router = useRouter()
  const [activeTab, setActiveTab] = useState('ai-list')

  // ========== AI List States ==========
  const [aiLoading, setAiLoading] = useState(false)
  const [aiData, setAiData] = useState<HazardIdentification[]>([])
  const [aiTotal, setAiTotal] = useState(0)
  const [aiPage, setAiPage] = useState(1)
  const [aiPageSize, setAiPageSize] = useState(20)
  const [aiKeyword, setAiKeyword] = useState('')
  const [aiStatusFilter, setAiStatusFilter] = useState<string | undefined>()
  const [aiProgressFilter, setAiProgressFilter] = useState<string | undefined>()

  // ========== Revision Record States ==========
  const [recordForm] = Form.useForm()
  const [recordEditForm] = Form.useForm()
  const [recordModalVisible, setRecordModalVisible] = useState(false)
  const [editingRecord, setEditingRecord] = useState<HazardRevisionRecord | null>(null)

  // ========== Archive States ==========
  const [archiveForm] = Form.useForm()
  const [archiveEditForm] = Form.useForm()
  const [archiveModalVisible, setArchiveModalVisible] = useState(false)
  const [editingArchive, setEditingArchive] = useState<HazardRevisionArchive | null>(null)

  // ========== Link Modal ==========
  const [linkModalVisible, setLinkModalVisible] = useState(false)
  const [linkingRecordId, setLinkingRecordId] = useState<string | null>(null)
  const [archivesForLink, setArchivesForLink] = useState<HazardRevisionArchive[]>([])

  // ========== Form data caches ==========
  const [revisionsForSelect, setRevisionsForSelect] = useState<RegulationRevision[]>([])

  // ========== Store (for revision + archive) ==========
  const {
    hazardRevisionRecords,
    hazardRevisionRecordTotal,
    hazardRevisionRecordQueryParams,
    setHazardRevisionRecords,
    setHazardRevisionRecordTotal,
    setHazardRevisionRecordQueryParams,
    addHazardRevisionRecord,
    updateHazardRevisionRecord: updateRecordInStore,
    removeHazardRevisionRecord,

    hazardRevisionArchives,
    hazardRevisionArchiveTotal,
    hazardRevisionArchiveQueryParams,
    setHazardRevisionArchives,
    setHazardRevisionArchiveTotal,
    setHazardRevisionArchiveQueryParams,
    addHazardRevisionArchive,
    updateHazardRevisionArchive: updateArchiveInStore,
    removeHazardRevisionArchive,
  } = useSafetyStore()

  // Local filters for revision tab
  const [recordSearchText, setRecordSearchText] = useState('')
  const [recordTypeFilter, setRecordTypeFilter] = useState<string | undefined>()
  const [recordOpinionFilter, setRecordOpinionFilter] = useState<string | undefined>()

  // Local filters for archive tab
  const [archiveSearchText, setArchiveSearchText] = useState('')
  const [archiveStatusFilter, setArchiveStatusFilter] = useState<string | undefined>()

  // ========== AI List Handlers ==========

  const loadAiData = async () => {
    setAiLoading(true)
    try {
      const response = await getHazardIdentifications({
        page: aiPage,
        page_size: aiPageSize,
        overall_status: aiStatusFilter,
        ai_node_progress: aiProgressFilter,
        keyword: aiKeyword || undefined,
      })
      if (response.code === 200) {
        setAiData(response.data)
        setAiTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载危险源辨识列表失败')
    } finally {
      setAiLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'ai-list') loadAiData()
  }, [aiPage, aiPageSize, aiStatusFilter, aiProgressFilter, activeTab])

  // ========== Revision Handlers ==========

  const loadRecords = async () => {
    try {
      const response = await getHazardRevisionRecords({
        ...hazardRevisionRecordQueryParams,
        keyword: recordSearchText || undefined,
        identification_type: recordTypeFilter,
        review_opinion: recordOpinionFilter,
      })
      if (response.code === 200) {
        setHazardRevisionRecords(response.data)
        setHazardRevisionRecordTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载辨识修订记录失败')
    }
  }

  useEffect(() => {
    if (activeTab === 'records') loadRecords()
  }, [
    hazardRevisionRecordQueryParams.page,
    hazardRevisionRecordQueryParams.page_size,
    recordTypeFilter,
    recordOpinionFilter,
    activeTab,
  ])

  const loadRevisionsForSelect = async () => {
    try {
      const response = await getRevisions({ page: 1, page_size: 500 })
      if (response.code === 200) setRevisionsForSelect(response.data)
    } catch { /* silent */ }
  }

  useEffect(() => { loadRevisionsForSelect() }, [])

  // ========== Archive Handlers ==========

  const loadArchives = async () => {
    try {
      const response = await getHazardRevisionArchives({
        ...hazardRevisionArchiveQueryParams,
        keyword: archiveSearchText || undefined,
        status: archiveStatusFilter,
      })
      if (response.code === 200) {
        setHazardRevisionArchives(response.data)
        setHazardRevisionArchiveTotal(response.meta?.total || 0)
      }
    } catch {
      message.error('加载存档列表失败')
    }
  }

  useEffect(() => {
    if (activeTab === 'archives') loadArchives()
  }, [
    hazardRevisionArchiveQueryParams.page,
    hazardRevisionArchiveQueryParams.page_size,
    archiveStatusFilter,
    activeTab,
  ])

  // ========== AI List Actions ==========

  const handleAiSearch = () => {
    setAiPage(1)
    loadAiData()
  }

  const handleAiDelete = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这条危险源辨识记录吗？',
      onOk: async () => {
        try {
          const response = await deleteHazardIdentification(id)
          if (response.code === 200) {
            message.success('删除成功')
            loadAiData()
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const getProgressTag = (value: string) => {
    const opt = AI_NODE_PROGRESS_OPTIONS.find((o) => o.value === value)
    return <Tag color={opt?.color}>{opt?.label || value}</Tag>
  }

  const getStatusTag = (value: string) => {
    const opt = OVERALL_STATUS_OPTIONS_HI.find((o) => o.value === value)
    return <Tag color={opt?.color}>{opt?.label || value}</Tag>
  }

  const getRiskTag = (level?: string, label?: string) => {
    if (!level) return '-'
    const opt = RISK_LEVEL_OPTIONS.find((o) => o.value === level)
    return <Tag color={opt?.color}>{label || level}</Tag>
  }

  // ========== Revision Record Actions ==========

  const handleRecordSearch = () => {
    setHazardRevisionRecordQueryParams({ page: 1 })
    loadRecords()
  }

  const handleAddRecord = () => {
    setEditingRecord(null)
    recordForm.resetFields()
    setRecordModalVisible(true)
  }

  const handleEditRecord = (record: HazardRevisionRecord) => {
    setEditingRecord(record)
    recordEditForm.setFieldsValue(record)
    setRecordModalVisible(true)
  }

  const handleDeleteRecord = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个辨识记录吗？',
      onOk: async () => {
        try {
          const response = await deleteHazardRevisionRecord(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeHazardRevisionRecord(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleRecordSubmit = async () => {
    try {
      const values = editingRecord
        ? await recordEditForm.validateFields()
        : await recordForm.validateFields()

      if (editingRecord) {
        const response = await updateHazardRevisionRecord(editingRecord.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateRecordInStore(editingRecord.id, response.data)
          setRecordModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createHazardRevisionRecord(values as HazardRevisionRecordFormData)
        if (response.code === 200) {
          message.success('创建成功')
          addHazardRevisionRecord(response.data)
          setRecordModalVisible(false)
          recordForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  const handleApproveRecord = async (id: string) => {
    Modal.confirm({
      title: '确认审核',
      content: '确定要审核通过这个辨识记录吗？',
      onOk: async () => {
        try {
          const response = await approveHazardRevision(id)
          if (response.code === 200) {
            message.success('审核通过')
            loadRecords()
          } else {
            message.error(response.message || '审核失败')
          }
        } catch {
          message.error('审核失败')
        }
      },
    })
  }

  const handleUploadHazardDoc = async (recordId: string, file: File) => {
    try {
      const response = await uploadHazardRevisionDocument(recordId, file)
      if (response.code === 200) {
        message.success('文档上传成功')
        loadRecords()
      } else {
        message.error(response.message || '上传失败')
      }
    } catch {
      message.error('上传失败')
    }
  }

  const hazardUploadProps = (recordId: string): UploadProps => ({
    showUploadList: false,
    beforeUpload: async (file) => {
      await handleUploadHazardDoc(recordId, file)
      return false
    },
  })

  const handleOpenLink = async (recordId: string) => {
    setLinkingRecordId(recordId)
    setLinkModalVisible(true)
    try {
      const response = await getHazardRevisionArchives({ page: 1, page_size: 500 })
      if (response.code === 200) setArchivesForLink(response.data)
    } catch { /* silent */ }
  }

  const handleLinkToArchive = async (archiveId: string) => {
    if (!linkingRecordId) return
    try {
      const response = await linkRevisionToArchive(linkingRecordId, archiveId)
      if (response.code === 200) {
        message.success('关联成功')
        setLinkModalVisible(false)
        setLinkingRecordId(null)
        loadRecords()
      } else {
        message.error(response.message || '关联失败')
      }
    } catch {
      message.error('关联失败')
    }
  }

  const getReviewOpinionColor = (opinion: string) => {
    const opt = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return opt?.color || 'default'
  }

  const getReviewOpinionLabel = (opinion: string) => {
    const opt = REVIEW_OPINION_OPTIONS.find((o) => o.value === opinion)
    return opt?.label || opinion
  }

  // ========== Archive Actions ==========

  const handleArchiveSearch = () => {
    setHazardRevisionArchiveQueryParams({ page: 1 })
    loadArchives()
  }

  const handleAddArchive = () => {
    setEditingArchive(null)
    archiveForm.resetFields()
    setArchiveModalVisible(true)
  }

  const handleEditArchive = (archive: HazardRevisionArchive) => {
    setEditingArchive(archive)
    archiveEditForm.setFieldsValue(archive)
    setArchiveModalVisible(true)
  }

  const handleDeleteArchive = (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个存档吗？',
      onOk: async () => {
        try {
          const response = await deleteHazardRevisionArchive(id)
          if (response.code === 200) {
            message.success('删除成功')
            removeHazardRevisionArchive(id)
          } else {
            message.error(response.message || '删除失败')
          }
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleArchiveSubmit = async () => {
    try {
      const values = editingArchive
        ? await archiveEditForm.validateFields()
        : await archiveForm.validateFields()

      if (editingArchive) {
        const response = await updateHazardRevisionArchive(editingArchive.id, values)
        if (response.code === 200) {
          message.success('更新成功')
          updateArchiveInStore(editingArchive.id, response.data)
          setArchiveModalVisible(false)
        } else {
          message.error(response.message || '更新失败')
        }
      } else {
        const response = await createHazardRevisionArchive(
          values as unknown as HazardRevisionArchiveFormData
        )
        if (response.code === 200) {
          message.success('创建成功')
          addHazardRevisionArchive(response.data)
          setArchiveModalVisible(false)
          archiveForm.resetFields()
        } else {
          message.error(response.message || '创建失败')
        }
      }
    } catch {
      console.error('表单验证失败')
    }
  }

  // ========== Table Columns ==========

  const aiColumns: ColumnsType<HazardIdentification> = [
    { title: '危险源编号', dataIndex: 'hazard_id_no', key: 'hazard_id_no', width: 140 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 110 },
    { title: '岗位', dataIndex: 'position', key: 'position', width: 110, ellipsis: true },
    { title: '生产步骤', dataIndex: 'production_step', key: 'production_step', width: 180, ellipsis: true },
    {
      title: '固有风险',
      key: 'inherent_risk',
      width: 120,
      render: (_: unknown, record: HazardIdentification) =>
        getRiskTag(record.inherent_risk_level, record.inherent_risk_label),
    },
    {
      title: 'AI进度',
      dataIndex: 'ai_node_progress',
      key: 'ai_node_progress',
      width: 120,
      render: (v: string) => getProgressTag(v),
    },
    {
      title: '状态',
      dataIndex: 'overall_status',
      key: 'overall_status',
      width: 85,
      render: (v: string) => getStatusTag(v),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 115,
      render: (d: string) => dayjs(d).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      fixed: 'right',
      render: (_: unknown, record: HazardIdentification) => (
        <Space size="small">
          <Button
            type="link" size="small" icon={<EyeOutlined />}
            onClick={() => router.push(`/safety/hazard-identification/${record.id}`)}
          >
            查看
          </Button>
          <Button
            type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleAiDelete(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const recordColumns: ColumnsType<HazardRevisionRecord> = [
    { title: '辨识编号', dataIndex: 'hazard_revision_no', key: 'hazard_revision_no', width: 140 },
    { title: '操规名称', dataIndex: 'regulation_name', key: 'regulation_name', width: 160, ellipsis: true },
    {
      title: '类型',
      dataIndex: 'identification_type',
      key: 'identification_type',
      width: 90,
      render: (type: string) => {
        const opt = IDENTIFICATION_TYPE_OPTIONS.find((o) => o.value === type)
        return <Tag color={opt?.color}>{opt?.label || type}</Tag>
      },
    },
    { title: '辨识人', dataIndex: 'identifier_name', key: 'identifier_name', width: 90, render: (n: string) => n || '-' },
    {
      title: '时间',
      dataIndex: 'identification_time',
      key: 'identification_time',
      width: 105,
      render: (d: string) => (d ? dayjs(d).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '范围',
      dataIndex: 'identification_scope',
      key: 'identification_scope',
      width: 110,
      render: (scope: string) => {
        if (!scope) return <Tag color="default">未分析</Tag>
        return (
          <Space size={2} wrap>
            {scope.split(',').map((s) => (
              <Tag key={s.trim()} color="blue" style={{ fontSize: 11 }}>{s.trim()}</Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '审核',
      dataIndex: 'review_opinion',
      key: 'review_opinion',
      width: 80,
      render: (opinion: string) => (
        <Tag color={getReviewOpinionColor(opinion)}>{getReviewOpinionLabel(opinion)}</Tag>
      ),
    },
    {
      title: '存档',
      dataIndex: 'linked_hazard_archive_id',
      key: 'linked_hazard_archive_id',
      width: 85,
      render: (id: string) => (id ? <Tag color="success">已关联</Tag> : <Tag color="default">未关联</Tag>),
    },
    {
      title: '操作',
      key: 'action',
      width: 300,
      fixed: 'right',
      render: (_: unknown, record: HazardRevisionRecord) => (
        <Space size="small" wrap>
          {record.review_opinion === 'pending' && (
            <Button type="link" size="small" icon={<CheckCircleOutlined />}
              onClick={() => handleApproveRecord(record.id)} style={{ color: '#52c41a' }}>
              审核
            </Button>
          )}
          <Upload {...hazardUploadProps(record.id)}>
            <Button type="link" size="small" icon={<UploadOutlined />}>上传</Button>
          </Upload>
          {!record.linked_hazard_archive_id && (
            <Button type="link" size="small" icon={<LinkOutlined />}
              onClick={() => handleOpenLink(record.id)}>
              关联存档
            </Button>
          )}
          {record.hazard_document_path && (
            <Button type="link" size="small" icon={<EyeOutlined />}>查看</Button>
          )}
          <Button type="link" size="small" icon={<EditOutlined />}
            onClick={() => handleEditRecord(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDeleteRecord(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const archiveColumns: ColumnsType<HazardRevisionArchive> = [
    { title: '操规名称', dataIndex: 'regulation_name', key: 'regulation_name', width: 180, ellipsis: true },
    {
      title: '文档',
      dataIndex: 'hazard_document_path',
      key: 'hazard_document_path',
      width: 180, ellipsis: true,
      render: (path: string, record: HazardRevisionArchive) =>
        path ? (
          <Space size="small">
            <FileTextOutlined className="text-blue-500" />
            <Text ellipsis style={{ maxWidth: 100 }}>{record.hazard_document_original_name || path}</Text>
          </Space>
        ) : (<Tag color="default">未上传</Tag>),
    },
    {
      title: '日期', dataIndex: 'identification_date', key: 'identification_date', width: 105,
      render: (d: string) => (d ? dayjs(d).format('YYYY-MM-DD') : '-'),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (status: string) => {
        const opt = ARCHIVE_STATUS_OPTIONS.find((o) => o.value === status)
        return <Tag color={opt?.color}>{opt?.label || status}</Tag>
      },
    },
    {
      title: '备注', dataIndex: 'notes', key: 'notes', width: 130, ellipsis: true,
      render: (notes: string) => notes || '-',
    },
    {
      title: '操作', key: 'action', width: 160, fixed: 'right',
      render: (_: unknown, record: HazardRevisionArchive) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />}
            onClick={() => handleEditArchive(record)}>编辑</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDeleteArchive(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  // ========== Tab Items ==========

  const tabItems = [
    {
      key: 'ai-list',
      label: 'AI辨识',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={6}>
              <Input placeholder="搜索编号/部门/岗位/步骤" prefix={<SearchOutlined />}
                value={aiKeyword} onChange={(e) => setAiKeyword(e.target.value)} onPressEnter={handleAiSearch} />
            </Col>
            <Col span={4}>
              <Select placeholder="整体状态" allowClear value={aiStatusFilter}
                onChange={(v) => { setAiStatusFilter(v); setAiPage(1) }} style={{ width: '100%' }}
                options={OVERALL_STATUS_OPTIONS_HI.map((o) => ({ value: o.value, label: o.label }))} />
            </Col>
            <Col span={4}>
              <Select placeholder="AI进度" allowClear value={aiProgressFilter}
                onChange={(v) => { setAiProgressFilter(v); setAiPage(1) }} style={{ width: '100%' }}
                options={AI_NODE_PROGRESS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleAiSearch}>查询</Button>
            </Col>
          </Row>
          <Table columns={aiColumns} dataSource={aiData} rowKey="id" loading={aiLoading}
            scroll={{ x: 1150 }}
            pagination={{
              current: aiPage, pageSize: aiPageSize, total: aiTotal,
              showSizeChanger: true, showQuickJumper: true,
              showTotal: (t: number) => `共 ${t} 条`,
              onChange: (p: number, ps: number) => { setAiPage(p); setAiPageSize(ps) },
            }} />
        </>
      ),
    },
    {
      key: 'records',
      label: '修订记录',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input placeholder="搜索辨识编号/操规名称" prefix={<SearchOutlined />}
                value={recordSearchText} onChange={(e) => setRecordSearchText(e.target.value)} onPressEnter={handleRecordSearch} />
            </Col>
            <Col span={3}>
              <Select placeholder="辨识类型" allowClear value={recordTypeFilter}
                onChange={(v) => { setRecordTypeFilter(v); setHazardRevisionRecordQueryParams({ page: 1 }) }}
                style={{ width: '100%' }}
                options={IDENTIFICATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </Col>
            <Col span={3}>
              <Select placeholder="审核状态" allowClear value={recordOpinionFilter}
                onChange={(v) => { setRecordOpinionFilter(v); setHazardRevisionRecordQueryParams({ page: 1 }) }}
                style={{ width: '100%' }}
                options={REVIEW_OPINION_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleRecordSearch}>查询</Button>
            </Col>
          </Row>
          <Table columns={recordColumns} dataSource={hazardRevisionRecords} rowKey="id"
            scroll={{ x: 1250 }}
            pagination={{
              current: hazardRevisionRecordQueryParams.page,
              pageSize: hazardRevisionRecordQueryParams.page_size,
              total: hazardRevisionRecordTotal,
              showSizeChanger: true, showQuickJumper: true,
              showTotal: (t: number) => `共 ${t} 条`,
              onChange: (p: number, ps: number) => setHazardRevisionRecordQueryParams({ page: p, page_size: ps }),
            }} />
        </>
      ),
    },
    {
      key: 'archives',
      label: '辨识存档',
      children: (
        <>
          <Row gutter={16} className="mb-4">
            <Col span={5}>
              <Input placeholder="搜索操规名称" prefix={<SearchOutlined />}
                value={archiveSearchText} onChange={(e) => setArchiveSearchText(e.target.value)} onPressEnter={handleArchiveSearch} />
            </Col>
            <Col span={3}>
              <Select placeholder="状态" allowClear value={archiveStatusFilter}
                onChange={(v) => { setArchiveStatusFilter(v); setHazardRevisionArchiveQueryParams({ page: 1 }) }}
                style={{ width: '100%' }}
                options={ARCHIVE_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </Col>
            <Col span={3}>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleArchiveSearch}>查询</Button>
            </Col>
          </Row>
          <Table columns={archiveColumns} dataSource={hazardRevisionArchives} rowKey="id"
            scroll={{ x: 820 }}
            pagination={{
              current: hazardRevisionArchiveQueryParams.page,
              pageSize: hazardRevisionArchiveQueryParams.page_size,
              total: hazardRevisionArchiveTotal,
              showSizeChanger: true, showQuickJumper: true,
              showTotal: (t: number) => `共 ${t} 条`,
              onChange: (p: number, ps: number) => setHazardRevisionArchiveQueryParams({ page: p, page_size: ps }),
            }} />
        </>
      ),
    },
  ]

  // ========== Render ==========

  const getExtraButton = () => {
    switch (activeTab) {
      case 'ai-list':
        return (
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => router.push('/safety/hazard-identification/new')}>
            新建辨识
          </Button>
        )
      case 'records':
        return (
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAddRecord}>
            新建记录
          </Button>
        )
      case 'archives':
        return (
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAddArchive}>
            新建存档
          </Button>
        )
    }
  }

  return (
    <div className="p-6">
      <Card title="危险源辨识" extra={getExtraButton()}>
        <Tabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} items={tabItems} />
      </Card>

      {/* Record Modal */}
      <Modal
        title={editingRecord ? '编辑辨识记录' : '新建辨识记录'}
        open={recordModalVisible}
        onOk={handleRecordSubmit}
        onCancel={() => setRecordModalVisible(false)}
        width={650}
        okText="确认" cancelText="取消"
      >
        <Form form={editingRecord ? recordEditForm : recordForm} layout="vertical"
          initialValues={editingRecord || undefined}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="hazard_revision_no" label="辨识编号"
                rules={[{ required: true, message: '请输入辨识编号' }]}>
                <Input placeholder="请输入辨识编号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="identification_type" label="辨识类型"
                rules={[{ required: true, message: '请选择辨识类型' }]}>
                <Select options={IDENTIFICATION_TYPE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="regulation_revision_id" label="关联修订记录">
            <Select showSearch allowClear placeholder="选择关联修订记录（可选）"
              filterOption={(input, option) =>
                (option?.label as string)?.toLowerCase().includes(input.toLowerCase())}
              options={revisionsForSelect.map((r) => ({
                value: r.id,
                label: `${r.revision_no} - ${r.regulation_name}`,
              }))} />
          </Form.Item>
          <Form.Item name="regulation_name" label="操规名称"
            rules={[{ required: true, message: '请输入操规名称' }]}>
            <Input placeholder="请输入操规名称" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="identifier_id" label="辨识人ID">
                <Input placeholder="请输入辨识人ID" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="identifier_name" label="辨识人姓名">
                <Input placeholder="请输入辨识人姓名" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="process_change_content" label="工艺变更内容">
            <Input.TextArea rows={3} placeholder="描述工艺变更内容，用于辨识范围分析" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Archive Modal */}
      <Modal
        title={editingArchive ? '编辑存档' : '新建存档'}
        open={archiveModalVisible}
        onOk={handleArchiveSubmit}
        onCancel={() => setArchiveModalVisible(false)}
        width={550}
        okText="确认" cancelText="取消"
      >
        <Form form={editingArchive ? archiveEditForm : archiveForm} layout="vertical"
          initialValues={editingArchive || undefined}>
          <Form.Item name="regulation_name" label="操规名称"
            rules={[{ required: true, message: '请输入操规名称' }]}>
            <Input placeholder="请输入操规名称" />
          </Form.Item>
          <Form.Item name="hazard_document_original_name" label="文档原名">
            <Input placeholder="请输入原始文档名称" />
          </Form.Item>
          <Form.Item name="hazard_document_path" label="文档路径">
            <Input placeholder="文档存储路径" />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={3} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Link to Archive Modal */}
      <Modal
        title="选择关联存档"
        open={linkModalVisible}
        onCancel={() => { setLinkModalVisible(false); setLinkingRecordId(null) }}
        footer={null}
        width={600}
      >
        <Table
          dataSource={archivesForLink} rowKey="id" size="small" pagination={false}
          columns={[
            { title: '操规名称', dataIndex: 'regulation_name', key: 'regulation_name', ellipsis: true },
            { title: '文档', dataIndex: 'hazard_document_original_name', key: 'document', ellipsis: true,
              render: (name: string) => name || '-' },
            { title: '状态', dataIndex: 'status', key: 'status', width: 80,
              render: (status: string) => {
                const opt = ARCHIVE_STATUS_OPTIONS.find((o) => o.value === status)
                return <Tag color={opt?.color}>{opt?.label || status}</Tag>
              }},
            {
              title: '操作', key: 'action', width: 80,
              render: (_: unknown, archive: HazardRevisionArchive) => (
                <Button type="link" size="small" icon={<LinkOutlined />}
                  onClick={() => handleLinkToArchive(archive.id)}>关联</Button>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  )
}
