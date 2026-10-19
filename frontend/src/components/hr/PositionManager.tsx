'use client'

import { useEffect, useState } from 'react'
import { Card, Tag, Button, Input, Popconfirm, message, Select, Space, Table, InputNumber } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'

import { fetchPositions, createPosition, deletePositionByName, updatePositionHeadcount } from '@/actions/hr'

interface PositionRow { department: string; name: string; categories?: string[]; headcount: number | null }

export default function PositionManager() {
  const [positions, setPositions] = useState<PositionRow[]>([])
  const [loading, setLoading] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDept, setNewDept] = useState('')
  const [filterDept, setFilterDept] = useState<string | undefined>()

  const loadData = async () => {
    setLoading(true)
    try {
      const data = await fetchPositions(filterDept)
      setPositions(data.map((p) => ({ department: p.department, name: p.name, categories: p.categories || [], headcount: p.headcount ?? null })))
    } catch { setPositions([]) }
    finally { setLoading(false) }
  }

  const handleAdd = async () => {
    const name = newName.trim(); const dept = newDept.trim()
    if (!name || !dept) { message.warning('请填写部门和岗位'); return }
    try {
      await createPosition({ department: dept, name, headcount: null }).catch(() => {})
      message.success('已添加')
      setNewName(''); loadData()
    } catch { message.error('添加失败') }
  }

  const handleDelete = async (dept: string, name: string) => {
    try {
      await deletePositionByName(name, dept).catch(() => {})
      message.success('已删除')
      loadData()
    } catch { message.error('删除失败') }
  }

  const deptOptions = [...new Set(positions.map(p => p.department))].map(d => ({ value: d, label: d }))

  useEffect(() => { loadData() }, [filterDept])

  return (
    <div className="space-y-4">
      <Card size="small">
        <div className="flex items-center justify-between mb-3">
          <Space wrap>
            <Select placeholder="按部门筛选" allowClear style={{ width: 180 }}
              value={filterDept} onChange={setFilterDept} options={deptOptions} />
            <Input placeholder="部门" style={{ width: 150 }}
              value={newDept} onChange={e => setNewDept(e.target.value)}
              list="dept-list" />
            <datalist id="dept-list">{deptOptions.map(d => <option key={d.value} value={d.value} />)}</datalist>
          <Input placeholder="岗位名称" style={{ width: 150 }}
            value={newName} onChange={e => setNewName(e.target.value)}
            onPressEnter={handleAdd} />
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增岗位</Button>
          </Space>
        </div>
        <Table
          rowKey={(r: PositionRow) => `${r.department}:${r.name}`}
          loading={loading} dataSource={positions} size="small"
          pagination={{ pageSize: 20, showTotal: t => `共 ${t} 个岗位` }}
          columns={[
            { title: '部门', dataIndex: 'department', width: 200, filters: deptOptions.map(d => ({ text: d.label, value: d.value })), onFilter: (v, r: PositionRow) => r.department === v,
              render: (v: string) => <Tag color="blue">{v}</Tag> },
            { title: '岗位名称', dataIndex: 'name' },
            { title: '编制人数', dataIndex: 'headcount', width: 160,
              render: (v: number | null, r: PositionRow) => (
                <InputNumber
                  size="small"
                  min={0}
                  placeholder="未设置"
                  value={v ?? null}
                  onBlur={async (e) => {
                    const val = e.target.value.trim()
                    const num = val === '' ? null : Number(val)
                    if (num !== null && (Number.isNaN(num) || num < 0)) { message.warning('请输入非负整数'); return }
                    if (num === (r.headcount ?? null)) return
                    try {
                      await updatePositionHeadcount(r.department, r.name, num)
                      message.success('编制人数已更新')
                      loadData()
                    } catch { message.error('编制人数更新失败') }
                  }}
                />
              ),
            },
            { title: '关联培训大类', dataIndex: 'categories', width: 300,
              render: (cats: string[]) => cats?.length ? cats.map(c => <Tag key={c} className="mb-1">{c}</Tag>) : <span className="text-gray-400">-</span> },
            {
              title: '操作', width: 80, align: 'center',
              render: (_: any, r: PositionRow) => (
                <Popconfirm title={`删除「${r.name}」？`} onConfirm={() => handleDelete(r.department, r.name)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
