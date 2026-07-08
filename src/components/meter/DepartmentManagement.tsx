'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Table, Button, Space, Modal, Input, Select, Popconfirm, Switch, Tabs, Tag, Checkbox, Tooltip, TimePicker } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, UserAddOutlined } from '@ant-design/icons'
import type { TableColumnsType } from 'antd'
import { DepartmentItem, DepartmentHead, PersonnelCandidate } from '@/types/meter'
import {
  getDepartments,
  createDepartment,
  updateDepartment,
  deleteDepartment,
  getPersonnelCandidates,
  toggleDepartmentAutoNotify,
  getMeterSettings,
  updateMeterSettings,
} from '@/actions/meter'
import dayjs, { Dayjs } from 'dayjs'

export function DepartmentManagement() {
  const { message } = App.useApp()
  const [departments, setDepartments] = useState<DepartmentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [source, setSource] = useState<'instrument' | 'gas_detector'>('instrument')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<DepartmentItem | null>(null)
  const [formName, setFormName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 负责人多选
  const [candidates, setCandidates] = useState<PersonnelCandidate[]>([])
  const [personnelModalOpen, setPersonnelModalOpen] = useState(false)
  const [personnelSearch, setPersonnelSearch] = useState('')
  const [selectingDept, setSelectingDept] = useState<DepartmentItem | null>(null)
  const [selectedHeads, setSelectedHeads] = useState<DepartmentHead[]>([])

  // 全局提醒时间
  const [notifyTime, setNotifyTime] = useState<Dayjs | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getDepartments(source)
      setDepartments(data)
    } catch {
      message.error('获取部门列表失败')
    } finally {
      setLoading(false)
    }
  }, [source, message])

  useEffect(() => { fetchData() }, [fetchData])

  // 加载全局提醒时间
  useEffect(() => {
    getMeterSettings()
      .then((s) => {
        const [h, m] = s.notify_time.split(':')
        setNotifyTime(dayjs().hour(Number(h)).minute(Number(m)).second(0))
      })
      .catch(() => {})
  }, [])

  const handleTimeChange = async (time: Dayjs | null) => {
    if (!time) return
    setNotifyTime(time)
    const val = time.format('HH:mm')
    try {
      await updateMeterSettings(val)
      message.success(`提醒时间已更新为 ${val}`)
    } catch {
      message.error('更新提醒时间失败')
    }
  }

  const loadCandidates = useCallback(async () => {
    try {
      const data = await getPersonnelCandidates()
      setCandidates(data)
    } catch {
      message.error('获取人员列表失败')
    }
  }, [message])

  const openCreate = () => {
    setEditing(null)
    setFormName('')
    setModalOpen(true)
  }

  const openEdit = (record: DepartmentItem) => {
    setEditing(record)
    setFormName(record.name)
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    if (!formName.trim()) return
    setSubmitting(true)
    try {
      if (editing) {
        await updateDepartment(editing.id, {
          name: formName.trim(),
          heads: editing.heads,
        })
        message.success('部门已更新')
      } else {
        await createDepartment({
          source,
          name: formName.trim(),
        })
        message.success('部门已新增')
      }
      setModalOpen(false)
      fetchData()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败'
      message.error(msg)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (record: DepartmentItem) => {
    try {
      await deleteDepartment(record.id)
      message.success('部门已删除')
      fetchData()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败'
      message.error(msg)
    }
  }

  const handleToggleAutoNotify = async (record: DepartmentItem) => {
    try {
      const updated = await toggleDepartmentAutoNotify(record.id)
      setDepartments((prev) =>
        prev.map((d) => (d.id === record.id ? { ...d, auto_notify_enabled: updated.auto_notify_enabled } : d))
      )
      message.success(updated.auto_notify_enabled ? '已开启自动提醒' : '已关闭自动提醒')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '操作失败'
      message.error(msg)
    }
  }

  const openPersonnelSelect = async (record: DepartmentItem) => {
    setSelectingDept(record)
    setSelectedHeads([...record.heads])
    setPersonnelSearch('')
    if (candidates.length === 0) {
      await loadCandidates()
    }
    setPersonnelModalOpen(true)
  }

  const handlePersonnelConfirm = async () => {
    if (!selectingDept) return
    try {
      await updateDepartment(selectingDept.id, {
        name: selectingDept.name,
        heads: selectedHeads,
      })
      message.success(`已设置 ${selectedHeads.length} 位负责人`)
      setPersonnelModalOpen(false)
      fetchData()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '设置失败'
      message.error(msg)
    }
  }

  const toggleCandidate = (c: PersonnelCandidate, checked: boolean) => {
    if (checked) {
      setSelectedHeads((prev) => {
        if (prev.some((h) => h.feishu_open_id === c.feishu_open_id)) return prev
        return [...prev, { name: c.name, feishu_open_id: c.feishu_open_id }]
      })
    } else {
      setSelectedHeads((prev) => prev.filter((h) => h.feishu_open_id !== c.feishu_open_id))
    }
  }

  const removeHead = async (record: DepartmentItem, head: DepartmentHead) => {
    const newHeads = record.heads.filter((h) => h.feishu_open_id !== head.feishu_open_id)
    try {
      await updateDepartment(record.id, { name: record.name, heads: newHeads })
      message.success(`已移除负责人：${head.name}`)
      fetchData()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '移除失败'
      message.error(msg)
    }
  }

  const filteredCandidates = personnelSearch
    ? candidates.filter(
        (c) =>
          c.name.includes(personnelSearch) ||
          (c.department || '').includes(personnelSearch)
      )
    : candidates

  const columns: TableColumnsType<DepartmentItem> = [
    { title: '部门名称', dataIndex: 'name', width: 180, ellipsis: true },
    {
      title: '部门负责人',
      dataIndex: 'heads',
      width: 240,
      render: (heads: DepartmentHead[], record: DepartmentItem) => (
        <Space wrap>
          {heads.map((h) => (
            <Tag
              key={h.feishu_open_id}
              closable
              onClose={(e) => {
                e.preventDefault()
                removeHead(record, h)
              }}
            >
              {h.name}
            </Tag>
          ))}
          <Button
            size="small"
            type="dashed"
            icon={<UserAddOutlined />}
            onClick={() => openPersonnelSelect(record)}
          >
            {heads.length === 0 ? '添加' : ''}
          </Button>
        </Space>
      ),
    },
    {
      title: '自动提醒',
      dataIndex: 'auto_notify_enabled',
      width: 100,
      align: 'center',
      render: (v: boolean, record: DepartmentItem) => (
        <Switch
          checked={v}
          onChange={() => handleToggleAutoNotify(record)}
        />
      ),
    },
    {
      title: '关联记录数', dataIndex: 'record_count', width: 100, align: 'center',
      render: (v: number) => v > 0 ? v : '-',
    },
    {
      title: '操作', width: 150,
      render: (_: unknown, record: DepartmentItem) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm
            title="确定删除此部门？"
            description={record.record_count > 0 ? '该部门仍有关联记录，无法删除' : undefined}
            onConfirm={() => handleDelete(record)}
            okText="确定"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} disabled={record.record_count > 0}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <h2>部门管理</h2>

      <Tabs
        activeKey={source}
        onChange={(k) => setSource(k as 'instrument' | 'gas_detector')}
        items={[
          { key: 'instrument', label: '标准计量器具部门' },
          { key: 'gas_detector', label: '探测器部门' },
        ]}
      />

      <div style={{ marginBottom: 16 }}>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增部门</Button>
          <span style={{ color: '#888' }}>
            <span style={{ marginRight: 8 }}>每日提醒时间：</span>
            <TimePicker
              format="HH:mm"
              value={notifyTime}
              onChange={handleTimeChange}
              minuteStep={5}
              allowClear={false}
            />
          </span>
        </Space>
        <span style={{ marginLeft: 16, color: '#888' }}>
          改名时自动联动更新表中所有匹配记录
        </span>
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={departments}
        loading={loading}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个部门` }}
      />

      {/* 新增/编辑部门 Modal */}
      <Modal
        title={editing ? '编辑部门' : '新增部门'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={submitting}
        okText="确定"
        cancelText="取消"
      >
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8 }}>来源</div>
          <Select
            value={editing ? editing.source : source}
            disabled={!!editing}
            style={{ width: '100%', marginBottom: 16 }}
            options={[
              { label: '标准计量器具', value: 'instrument' },
              { label: '探测器', value: 'gas_detector' },
            ]}
          />
          <div style={{ marginBottom: 8 }}>部门名称</div>
          <Input
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder="请输入部门名称"
            maxLength={200}
            onPressEnter={handleSubmit}
          />
        </div>
      </Modal>

      {/* 多选负责人 Modal */}
      <Modal
        title={`选择部门负责人 — ${selectingDept?.name || ''}`}
        open={personnelModalOpen}
        onCancel={() => setPersonnelModalOpen(false)}
        onOk={handlePersonnelConfirm}
        okText={`确定 (已选 ${selectedHeads.length} 人)`}
        cancelText="取消"
        width={500}
      >
        <Input
          placeholder="搜索姓名或部门..."
          value={personnelSearch}
          onChange={(e) => setPersonnelSearch(e.target.value)}
          style={{ marginBottom: 12 }}
          allowClear
        />
        <div style={{ maxHeight: 400, overflow: 'auto' }}>
          {filteredCandidates.slice(0, 200).map((c) => (
            <div
              key={c.feishu_open_id}
              style={{
                padding: '6px 12px',
                borderBottom: '1px solid #f0f0f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Checkbox
                checked={selectedHeads.some((h) => h.feishu_open_id === c.feishu_open_id)}
                onChange={(e) => toggleCandidate(c, e.target.checked)}
              >
                <span style={{ fontWeight: 500 }}>{c.name}</span>
                <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>{c.department || '—'}</span>
              </Checkbox>
            </div>
          ))}
          {filteredCandidates.length === 0 && (
            <div style={{ textAlign: 'center', color: '#bbb', padding: 24 }}>无匹配人员</div>
          )}
        </div>
      </Modal>
    </div>
  )
}
