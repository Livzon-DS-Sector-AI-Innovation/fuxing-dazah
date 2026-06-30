'use client'

import { useEffect, useState } from 'react'
import { Card, Table, Input, Select, Space, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

export default function TrainersPage() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [dept, setDept] = useState<string | undefined>()
  const [depts, setDepts] = useState<{value:string,label:string}[]>([])

  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`).then(r => r.json())
      .then(res => setDepts((res.data||[]).map((d:string) => ({value:d,label:d}))))
  }, [])

  const load = async (p = 1) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(p), page_size: '50' })
      if (keyword) params.set('keyword', keyword)
      if (dept) params.set('department', dept)
      const res = await fetch(`${API_BASE}/api/v1/hr/trainers?${params.toString()}`)
      const d = await res.json()
      setData(d.data || [])
      setTotal(d.meta?.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { load(page) }, [page, dept])

  return (
    <div className="space-y-4">
      <h1 className="text-[22px] font-semibold">内训师台账</h1>
      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input prefix={<SearchOutlined />} placeholder="搜索姓名" value={keyword}
            onChange={e => setKeyword(e.target.value)} onPressEnter={() => load(1)} style={{ width: 200 }} />
          <Select placeholder="部门" allowClear value={dept} onChange={v => { setDept(v); setPage(1) }}
            options={depts} style={{ width: 200 }} />
        </Space>
        <Table dataSource={data} rowKey="id" loading={loading}
          pagination={{ current: page, pageSize: 50, total, onChange: p => setPage(p) }}
          columns={[
            { title: '姓名', dataIndex: 'name', width: 100 },
            { title: '部门', dataIndex: 'department', width: 150 },
            { title: '可培训部门', dataIndex: 'trainable_departments', width: 150 },
            { title: '资格范围', dataIndex: 'qualification_scope', width: 250, ellipsis: true },
            { title: '培训管理员', dataIndex: 'admin', width: 100 },
            { title: '一级培训师', dataIndex: 'is_level1', width: 120,
              render: (v: boolean) => v ? <Tag color="blue">一级培训师</Tag> : <Tag>-</Tag> },
          ]} />
      </Card>
    </div>
  )
}
