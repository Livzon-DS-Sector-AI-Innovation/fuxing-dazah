'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { App, Button, Empty, Form, Input, InputNumber, Modal, Popconfirm, Segmented, Select, Space, Switch, Table, Tooltip } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, UndoOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { createTypeConfig, deleteTypeConfig, getTypeConfigs, updateTypeConfig } from '@/actions/energy'
import { EnergyPageFrame } from './EnergyPageFrame'
import { PageHeading } from '@/components/shared/PageHeading'
import type { CreateTypeConfigInput, EnergyTypeConfig, PaginatedResponse, UpdateTypeConfigInput } from '@/types/energy'
import styles from './ConfigPages.module.css'

const PALETTE = ['#0075de', '#1aae39', '#dd5b00', '#722ed1', '#2f54eb', '#eb2f96', '#13c2c2', '#f5222d', '#7cb305', '#9254de']

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请稍后重试'
}

function TypeConfigModal({ record, existingColors, onClose, onSaved }: { record: EnergyTypeConfig | null; existingColors: string[]; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp()
  const [form] = Form.useForm<CreateTypeConfigInput>()
  const [submitting, setSubmitting] = useState(false)
  const isEdit = record !== null

  // 编辑时原样回填（color 为 null 就留空，不能替用户选色）；仅新建时随机补一个未使用的颜色。
  const initialValues = useMemo(() => (record ? {
    type_code: record.type_code,
    display_name: record.display_name,
    unit: record.unit,
    sort_order: record.sort_order,
    is_enabled: record.is_enabled,
    collect_granularity: record.collect_granularity || 'hourly',
    color: record.color || '',
    remark: record.remark ?? '',
  } : {
    type_code: '',
    display_name: '',
    unit: '',
    sort_order: 0,
    is_enabled: true,
    collect_granularity: 'hourly',
    color: PALETTE.find((color) => !existingColors.includes(color)) ?? PALETTE[0],
    remark: '',
  }), [existingColors, record])

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      if (record) {
        const updateData: UpdateTypeConfigInput = {
          display_name: values.display_name,
          unit: values.unit,
          sort_order: values.sort_order,
          is_enabled: values.is_enabled,
          collect_granularity: values.collect_granularity,
          color: values.color || null,
          remark: values.remark || null,
        }
        await updateTypeConfig(record.id, updateData)
        message.success('能源类型已更新')
      } else {
        await createTypeConfig({
          ...values,
          sort_order: values.sort_order ?? 0,
          is_enabled: values.is_enabled ?? true,
          collect_granularity: values.collect_granularity || 'hourly',
          color: values.color || null,
          remark: values.remark || null,
        })
        message.success('能源类型已创建')
      }
      onSaved()
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return
      message.error(`保存失败：${getErrorMessage(error)}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      key={record?.id ?? 'create'}
      title={isEdit ? '编辑能源类型' : '新增能源类型'}
      open
      onCancel={onClose}
      onOk={() => void handleSubmit()}
      confirmLoading={submitting}
      okText={isEdit ? '保存修改' : '创建类型'}
      cancelText="取消"
      destroyOnHidden
    >
      <p className={styles.drawerHint}>能源类型用于统一统计口径。创建后编码不可修改，请使用稳定、易读的英文标识。</p>
      <Form form={form} layout="vertical" initialValues={initialValues} requiredMark={false}>
        <Form.Item name="type_code" label="类型编码" rules={[{ required: true, message: '请输入唯一编码' }, { max: 50 }]} extra="例如 electricity、water，仅支持创建时设置。">
          <Input placeholder="electricity" disabled={isEdit} />
        </Form.Item>
        <Form.Item name="display_name" label="展示名称" rules={[{ required: true, message: '请输入展示名称' }, { max: 100 }]}>
          <Input placeholder="例如：电力" />
        </Form.Item>
        <div className={styles.formRow}>
          <Form.Item name="unit" label="计量单位" rules={[{ required: true, message: '请输入单位' }, { max: 20 }]}><Input placeholder="kWh" /></Form.Item>
          <Form.Item name="color" label="展示颜色" rules={[{ max: 20 }]}><Input placeholder="#5645d4" /></Form.Item>
          <Form.Item name="sort_order" label="显示排序"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
        </div>
        <Form.Item name="collect_granularity" label="采集粒度" rules={[{ required: true, message: '请选择采集粒度' }]}>
          <Segmented block options={[{ label: '逐小时采集', value: 'hourly' }, { label: '按日汇总', value: 'daily' }]} />
        </Form.Item>
        <Form.Item name="remark" label="备注" rules={[{ max: 500 }]}><Input.TextArea rows={3} placeholder="可选说明" /></Form.Item>
        <Form.Item name="is_enabled" label="启用该类型" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
      </Form>
    </Modal>
  )
}

export function EnergyTypeConfigPage() {
  const { message } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<'enabled' | 'disabled' | undefined>()
  const [editingRecord, setEditingRecord] = useState<EnergyTypeConfig | null | undefined>(undefined)
  const { data, isLoading, error, refetch, isFetching } = useQuery({ queryKey: ['energy', 'type-configs', 'page'], queryFn: () => getTypeConfigs() })
  const response = data as PaginatedResponse<EnergyTypeConfig> | undefined
  const items = useMemo(() => response?.items ?? [], [response])
  const filteredData = useMemo(() => items.filter((item) => {
    const matchesKeyword = !keyword || [item.display_name, item.type_code, item.unit, item.remark ?? ''].some((value) => value.toLowerCase().includes(keyword.trim().toLowerCase()))
    const matchesStatus = !status || (status === 'enabled' ? item.is_enabled : !item.is_enabled)
    return matchesKeyword && matchesStatus
  }), [items, keyword, status])
  const hasFilters = Boolean(keyword || status)

  const handleDelete = async (record: EnergyTypeConfig) => {
    try {
      await deleteTypeConfig(record.id)
      message.success('能源类型已删除')
      void refetch()
    } catch (deleteError) {
      message.error(`删除失败：${getErrorMessage(deleteError)}`)
    }
  }

  const columns: TableColumnsType<EnergyTypeConfig> = [
    { title: '能源类型', key: 'name', width: 230, render: (_, record) => <div className={styles.typeName}><span className={styles.colorDot} style={{ background: record.color || '#bbb8b1' }} /><div><div>{record.display_name}</div><span className={styles.code}>{record.type_code}</span></div></div> },
    { title: '计量单位', dataIndex: 'unit', width: 110 },
    { title: '采集粒度', dataIndex: 'collect_granularity', width: 130, render: (value: EnergyTypeConfig['collect_granularity']) => <span className={styles.pill}>{value === 'daily' ? '按日汇总' : '逐小时采集'}</span> },
    { title: '排序', dataIndex: 'sort_order', width: 80 },
    { title: '状态', dataIndex: 'is_enabled', width: 110, render: (enabled: boolean) => <span className={`${styles.status} ${enabled ? styles.statusEnabled : ''}`}>{enabled ? '已启用' : '已停用'}</span> },
    { title: '备注', dataIndex: 'remark', ellipsis: true, render: (remark: string | null) => remark || <span className={styles.muted}>—</span> },
    { title: '操作', key: 'actions', width: 112, align: 'right', render: (_, record) => <Space size={0}><Tooltip title="编辑"><Button type="text" icon={<EditOutlined />} onClick={() => setEditingRecord(record)} aria-label={`编辑 ${record.display_name}`} /></Tooltip><Popconfirm title="删除能源类型？" description="删除后，相关数据源可能无法正常展示。" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={() => void handleDelete(record)}><Tooltip title="删除"><Button type="text" danger icon={<DeleteOutlined />} aria-label={`删除 ${record.display_name}`} /></Tooltip></Popconfirm></Space> },
  ]

  return (
    <EnergyPageFrame>
      <PageHeading title="能源类型" subtitle="维护计量单位、采集粒度与展示规则，统一能源数据的统计口径。" actions={<Button type="primary" icon={<PlusOutlined />} onClick={() => setEditingRecord(null)}>新增能源类型</Button>} />
      <section className={styles.toolbar} aria-label="能源类型筛选">
        <Input className={styles.filterControl} placeholder="搜索名称、编码或单位" prefix={<SearchOutlined />} value={keyword} allowClear onChange={(event) => setKeyword(event.target.value)} />
        <Select className={styles.filterSelect} placeholder="使用状态" value={status} allowClear onChange={setStatus} options={[{ label: '已启用', value: 'enabled' }, { label: '已停用', value: 'disabled' }]} />
        {hasFilters && <Button className={styles.resetButton} type="text" icon={<UndoOutlined />} onClick={() => { setKeyword(''); setStatus(undefined) }}>重置筛选</Button>}
        <span className={styles.toolbarMeta}>{isFetching ? '正在更新…' : `显示 ${filteredData.length} / ${items.length} 种类型`}</span>
        <div className={styles.toolbarActions}><Button icon={<ReloadOutlined />} loading={isFetching} onClick={() => void refetch()}>刷新</Button></div>
      </section>
      <section className={styles.tableCard} aria-live="polite">
        {error ? <div className={styles.empty}><Empty description={`加载失败：${getErrorMessage(error)}`}><Button onClick={() => void refetch()}>重新加载</Button></Empty></div> : !isLoading && filteredData.length === 0 ? <div className={styles.empty}><Empty description={hasFilters ? '没有符合筛选条件的能源类型' : '暂未配置能源类型'}><Button type="primary" icon={<PlusOutlined />} onClick={() => setEditingRecord(null)}>新增能源类型</Button></Empty></div> : <Table rowKey="id" columns={columns} dataSource={filteredData} loading={isLoading} scroll={{ x: 820 }} pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }} />}
      </section>
      {editingRecord !== undefined && <TypeConfigModal record={editingRecord} existingColors={items.map((item) => item.color).filter((color): color is string => Boolean(color))} onClose={() => setEditingRecord(undefined)} onSaved={() => { setEditingRecord(undefined); void refetch() }} />}
    </EnergyPageFrame>
  )
}
