'use client'

import { useEffect, useState } from 'react'
import { Table, Input, Select, Card, Space, Upload, Button, App } from 'antd'
import { SearchOutlined, UploadOutlined } from '@ant-design/icons'
import { fetchSopCatalog } from '@/lib/api/hr'

export default function SopCatalogPage() {
  const { message } = App.useApp()
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [dept, setDept] = useState<string | undefined>()
  const [departments, setDepartments] = useState<{ value: string; label: string }[]>([])
  const [categories, setCategories] = useState<{ value: string; label: string }[]>([])
  const [cat, setCat] = useState<string | undefined>()

  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

  // 部门列表（一次性加载）
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/hr/sop-catalog/departments`).then(r => r.json()).then(res => {
      setDepartments((res.data || []).map((d: string) => ({ value: d, label: d })))
    })
  }, [])

  // 分类列表（按部门筛选，级联）
  useEffect(() => {
    const url = dept
      ? `${API_BASE}/api/v1/hr/sop-catalog/categories?department=${encodeURIComponent(dept)}`
      : `${API_BASE}/api/v1/hr/sop-catalog/categories`
    fetch(url).then(r => r.json()).then(res => {
      setCategories((res.data || []).map((c: string) => ({ value: c, label: c })))
    })
  }, [dept])

  const load = async (p = 1) => {
    setLoading(true)
    try {
      const res = await fetchSopCatalog({ page: p, page_size: 50, keyword: keyword || undefined, department: dept, category: cat })
      setData(res.data || [])
      setTotal(res.meta?.total || 0)
    } finally { setLoading(false) }
  }

  useEffect(() => { load(page) }, [page, dept, cat])

  const columns = [
    { title: '文件名称', dataIndex: 'file_name', width: 350, fixed: 'left' as const, ellipsis: true },
    { title: 'SOP编号', dataIndex: 'sop_number', width: 150 },
    { title: '培训类别', dataIndex: 'category', width: 200 },
    { title: '所属部门', dataIndex: 'department', width: 180 },
  ]

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold">SOP 目录</h1>
        <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({ file }) => {
          const fd = new FormData(); fd.append('file', file as File)
          try {
            const res = await fetch(`${API_BASE}/api/v1/hr/sop-catalog/upload`, { method: 'POST', body: fd, credentials: 'include' })
            const d = await res.json()
            if (res.ok) message.success(`上传完成：新增${d.data.created}，更新${d.data.updated}`)
            else message.error(d.message || '上传失败')
            load(1)
          } catch { message.error('上传失败') }
        }}>
          <Button icon={<UploadOutlined />}>上传SOP目录</Button>
        </Upload>
      </div>
      <Card>
        <Space className="mb-4" wrap>
          <Input prefix={<SearchOutlined />} placeholder="搜索文件名称" value={keyword}
            onChange={e => setKeyword(e.target.value)} onPressEnter={() => load(1)} style={{ width: 260 }} />
          <Select placeholder="筛选部门" allowClear value={dept} onChange={v => { setDept(v); setCat(undefined); setPage(1) }}
            options={departments} style={{ width: 200 }} />
          <Select placeholder="筛选类别" allowClear value={cat} onChange={v => { setCat(v); setPage(1) }}
            options={categories} style={{ width: 240 }} />
        </Space>
        <Table columns={columns} dataSource={data} rowKey="id" loading={loading} scroll={{ x: 900 }}
          pagination={{ current: page, pageSize: 50, total, onChange: (p) => setPage(p), showSizeChanger: false }} />
      </Card>
    </div>
  )
}
