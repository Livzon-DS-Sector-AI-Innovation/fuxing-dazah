'use client'

import { useEffect, useState } from 'react'
import { App, Button, Card, Table, Input, Select, Space, Tag, Upload, Popconfirm, Modal } from 'antd'
import { SearchOutlined, UploadOutlined, DeleteOutlined, ClearOutlined } from '@ant-design/icons'
import { fetchTrainersAction, uploadTrainersAction, deleteTrainerAction, clearTrainersAction } from '@/actions/hr'

export default function TrainersPage() {
  const { message, modal } = App.useApp()
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [dept, setDept] = useState<string | undefined>()
  const [depts, setDepts] = useState<{value:string,label:string}[]>([])

  useEffect(() => {
    fetchTrainersAction({ page_size: 200 })
      .then(res => {
        const dset = new Set<string>()
        ;(res.data || []).forEach((t: any) => { if (t.department) dset.add(t.department) })
        setDepts(Array.from(dset).map(d => ({ value: d, label: d })))
      })
      .catch(() => {})
  }, [])

  const load = async (p = 1) => {
    setLoading(true)
    try {
      const res = await fetchTrainersAction({
        keyword: keyword || undefined,
        department: dept,
        page: p,
        page_size: 50,
      })
      setData(res.data || [])
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载失败')
    } finally { setLoading(false) }
  }

  useEffect(() => { load(page) }, [page, dept])

  const handleDelete = async (id: string, name: string) => {
    try {
      await deleteTrainerAction(id)
      message.success(`已删除：${name}`)
      load(page)
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  const handleClear = async () => {
    try {
      await clearTrainersAction()
      message.success('已清空全部内训师记录')
      load(1)
    } catch (err: any) {
      message.error(err.message || '清空失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold">内训师台账</h1>
        <Space>
          <Upload accept=".xlsx,.xls" showUploadList={false} customRequest={async ({ file }) => {
            const fd = new FormData(); fd.append('file', file as File)
            try {
              const d = await uploadTrainersAction(fd)
              if (d.data?.errors && d.data.errors.length > 0) {
                modal.warning({
                  title: `上传完成：${d.message}，但有${d.data.errors.length}项出错`,
                  content: <ul style={{maxHeight:300, overflow:'auto', paddingLeft:18}}>{d.data.errors.map((e:string,i:number)=><li key={i}>{e}</li>)}</ul>,
                  width: 500,
                })
              } else {
                message.success(d.message)
              }
              load(1)
            } catch (err: any) { message.error(err.message || '上传失败') }
          }}>
            <Button icon={<UploadOutlined />}>上传内训师</Button>
          </Upload>
          <Popconfirm title="确认清空全部内训师记录？此操作不可恢复" onConfirm={handleClear}>
            <Button danger icon={<ClearOutlined />}>清空台账</Button>
          </Popconfirm>
        </Space>
      </div>
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
            {
              title: '操作', width: 80, render: (_: any, record: any) => (
                <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id, record.name)}>
                  <Button type="link" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              ),
            },
          ]} />
      </Card>
    </div>
  )
}
