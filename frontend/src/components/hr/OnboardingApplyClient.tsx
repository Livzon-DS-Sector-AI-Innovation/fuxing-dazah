'use client'

import { useEffect, useState } from 'react'
import { Button, Space, Table, Tabs, Tag, message, Modal } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, SendOutlined } from '@ant-design/icons'
import { API_BASE } from '@/lib/api/hr'

export default function OnboardingApplyClient() {
  const [onboardingApps, setOnboardingApps] = useState<any[]>([])
  const [offboardingApps, setOffboardingApps] = useState<any[]>([])

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [onbRes, offbRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/hr/onboarding-applications`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/v1/hr/offboarding-applications`, { credentials: 'include' }).then(r => r.json()),
      ])
      setOnboardingApps(onbRes.data || [])
      setOffboardingApps(offbRes.data || [])
    } catch { /* ignore */ }
  }

  const handleApprove = async (type: 'onboarding' | 'offboarding', appId: string, status: string) => {
    const prefix = type === 'onboarding' ? 'onboarding' : 'offboarding'
    Modal.confirm({
      title: status === '已通过' ? '确认通过' : '确认拒绝',
      content: status === '已通过'
        ? (type === 'onboarding' ? '通过后将自动转为试用期员工并创建入职台账' : '通过后员工状态将变更为离职')
        : '拒绝此申请？',
      onOk: async () => {
        try {
          const res = await fetch(`${API_BASE}/api/v1/hr/${prefix}-applications/${appId}/approve`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status }),
            credentials: 'include',
          })
          if (!res.ok) throw new Error('操作失败')
          message.success(status === '已通过' ? '审批通过' : '已拒绝')
          loadData()
        } catch (err: any) { message.error(err.message || '操作失败') }
      },
    })
  }

  const statusColor: Record<string, string> = { '待审批': 'processing', '已通过': 'success', '已拒绝': 'error' }

  const makeTable = (data: any[], type: 'onboarding' | 'offboarding') => (
    <Table dataSource={data} rowKey="id" size="small"
      columns={type === 'onboarding' ? [
        { title: '工号', dataIndex: 'employee_number', width: 100 },
        { title: '姓名', dataIndex: 'name', width: 80 },
        { title: '部门', dataIndex: 'department', width: 140, ellipsis: true },
        { title: '岗位', dataIndex: 'position', width: 120, ellipsis: true },
        { title: '入职日期', dataIndex: 'hire_date', width: 100 },
        { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag> },
        { title: '申请时间', dataIndex: 'created_at', width: 100, render: (v: string) => v?.split('T')[0] },
        { title: '操作', width: 140, render: (_: any, r: any) => r.status === '待审批' ? (
            <Space size="small">
              <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => handleApprove(type, r.id, '已通过')}>通过</Button>
              <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleApprove(type, r.id, '已拒绝')}>拒绝</Button>
            </Space>
          ) : null },
      ] : [
        { title: '工号', dataIndex: 'employee_number', width: 100 },
        { title: '姓名', dataIndex: 'name', width: 80 },
        { title: '部门', dataIndex: 'department', width: 140, ellipsis: true },
        { title: '岗位', dataIndex: 'position', width: 120, ellipsis: true },
        { title: '离职日期', dataIndex: 'offboarding_date', width: 100 },
        { title: '类型', dataIndex: 'offboarding_type', width: 80 },
        { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag> },
        { title: '原因', dataIndex: 'reason', width: 160, ellipsis: true, render: (v: string) => v || '-' },
        { title: '操作', width: 140, render: (_: any, r: any) => r.status === '待审批' ? (
            <Space size="small">
              <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => handleApprove(type, r.id, '已通过')}>通过</Button>
              <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => handleApprove(type, r.id, '已拒绝')}>拒绝</Button>
            </Space>
          ) : null },
      ]} />
  )

  const onbPending = onboardingApps.filter(a => a.status === '待审批').length
  const offbPending = offboardingApps.filter(a => a.status === '待审批').length

  return (
    <div className="space-y-4">
      <Tabs defaultActiveKey="onboarding" items={[
        { key: 'onboarding', label: `入职审批 (${onbPending})`, children: makeTable(onboardingApps, 'onboarding') },
        { key: 'offboarding', label: `离职审批 (${offbPending})`, children: makeTable(offboardingApps, 'offboarding') },
      ]} />
    </div>
  )
}
