'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { ReloadOutlined, TeamOutlined } from '@ant-design/icons'
import { usePermission } from '@/hooks/usePermission'
import type { Employee, TitleReviewApplication, TitleReviewJudge } from '@/types/hr'
import {
  assignTitleJudges,
  fetchEmployeesAction, fetchTitleApplication, fetchTitleApplications,
  fetchTitleDefaultJudges,
  finalizeTitleVotes,
} from '@/actions/hr'
import TitleReviewProfile from './TitleReviewProfile'
import TitleReviewWorkValue from './TitleReviewWorkValue'

const APP_STATUS_META: Record<string, { label: string; color: string }> = {
  submitted: { label: '待评审', color: 'blue' },
  voting: { label: '投票中', color: 'processing' },
  passed: { label: '投票通过', color: 'success' },
  failed: { label: '投票未通过', color: 'error' },
  final_passed: { label: '终审通过', color: 'success' },
  final_failed: { label: '终审驳回', color: 'error' },
  invalid: { label: '员工未匹配', color: 'warning' },
}

const JUDGE_ROLES = ['技术专家', '部门经理', '人力资源']

interface Props {
  activityId: string
  activityStatus?: string
}

export default function TitleReviewApplicationTab({ activityId, activityStatus }: Props) {
  const { message } = App.useApp()
  const { hasPermission } = usePermission()
  const [rows, setRows] = useState<TitleReviewApplication[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<(TitleReviewApplication & { judges: TitleReviewJudge[] }) | null>(null)
  const [judgeModal, setJudgeModal] = useState<TitleReviewApplication | null>(null)
  const [selectedJudges, setSelectedJudges] = useState<{ employee_id: string; name: string; employee_no?: string; role: string }[]>([])
  const [employeeOptions, setEmployeeOptions] = useState<Employee[]>([])
  const [employeeSearching, setEmployeeSearching] = useState(false)
  const [saving, setSaving] = useState(false)

  const canManage = hasPermission('hr:title:manage')
  const reviewOpen = activityStatus === 'open' || activityStatus === 'reviewing'

  const load = useCallback(() => {
    setLoading(true)
    fetchTitleApplications(activityId, { page, page_size: 20 })
      .then((d) => {
        setRows(d?.data || [])
        setTotal(d?.meta?.total || 0)
      })
      .catch((err: any) => message.error(err.message || '加载申报列表失败'))
      .finally(() => setLoading(false))
  }, [activityId, page, message])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = async (application: TitleReviewApplication) => {
    try {
      const d = await fetchTitleApplication(application.id)
      setDetail(d.data)
    } catch (err: any) {
      message.error(err.message || '加载详情失败')
    }
  }

  const openJudgeModal = async (application: TitleReviewApplication) => {
    setJudgeModal(application)
    setSaving(false)
    try {
      const [detailD, defaults, empList] = await Promise.all([
        fetchTitleApplication(application.id),
        fetchTitleDefaultJudges(application.id),
        fetchEmployeesAction({ status: '在职', page: 1, page_size: 200 }),
      ])
      const current = detailD?.data?.judges || []
      // 已指定的保留（编号/角色），默认小组作为补充候选
      const merged = [...current.map((j) => ({
        employee_id: j.judge_employee_id,
        name: j.judge_name,
        employee_no: j.judge_employee_no,
        role: j.judge_role || '技术专家',
      }))]
      for (const m of defaults?.data || []) {
        if (!merged.some((x) => x.employee_id === m.employee_id)) {
          merged.push({ employee_id: m.employee_id, name: m.name, employee_no: m.employee_no, role: '技术专家' })
        }
      }
      setSelectedJudges(merged)
      setEmployeeOptions(empList?.data || [])
    } catch (err: any) {
      message.error(err.message || '加载评委信息失败')
      setJudgeModal(null)
    }
  }

  // 员工远程搜索（在职员工 1200+，仅前端过滤前 200 条会搜不到）
  const searchEmployees = async (keyword: string) => {
    setEmployeeSearching(true)
    try {
      const d = await fetchEmployeesAction({
        status: '在职',
        keyword: keyword || undefined,
        page: 1,
        page_size: keyword ? 50 : 200,
      })
      setEmployeeOptions(d?.data || [])
    } catch (err: any) {
      message.error(err.message || '搜索员工失败')
    } finally {
      setEmployeeSearching(false)
    }
  }

  const handleAssign = async () => {
    if (!judgeModal) return
    if (!selectedJudges.length) {
      message.warning('请至少选择一位评委')
      return
    }
    setSaving(true)
    try {
      const d = await assignTitleJudges(
        judgeModal.id,
        selectedJudges.map((j) => ({ employee_id: j.employee_id, role: j.role }))
      )
      message.success(d.message || '评委指定成功')
      setJudgeModal(null)
      load()
    } catch (err: any) {
      message.error(err.message || '指定评委失败')
    } finally {
      setSaving(false)
    }
  }

  const runAction = async (fn: (id: string) => Promise<any>, id: string, successMsg: string) => {
    try {
      const d = await fn(id)
      message.success(d.message || successMsg)
      setDetail(null)
      load()
    } catch (err: any) {
      message.error(err.message || '操作失败')
    }
  }

  const columns = [
    { title: '姓名', dataIndex: 'name', key: 'name', width: 90 },
    { title: '工号', dataIndex: 'employee_no', key: 'employee_no', width: 110 },
    { title: '部门', dataIndex: 'department', key: 'department', width: 110, ellipsis: true },
    { title: '序列/职级', key: 'level', width: 150, render: (_: unknown, r: TitleReviewApplication) => `${r.sequence || '-'} · ${r.apply_level || '-'}` },
    { title: '现任职级', dataIndex: 'current_level', key: 'current_level', width: 100, render: (v: string) => v || '-' },
    { title: '学历', key: 'education', width: 80, render: (_: unknown, r: TitleReviewApplication) => r.profile?.['学历'] || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => <Tag color={APP_STATUS_META[s]?.color}>{APP_STATUS_META[s]?.label || s}</Tag>,
    },
    {
      title: '票数(同意/反对/弃权)', key: 'votes', width: 140,
      render: (_: unknown, r: TitleReviewApplication) =>
        r.status === 'submitted' || r.status === 'invalid'
          ? '-'
          : `${r.agree_votes}/${r.oppose_votes}/${r.abstain_votes}`,
    },
    {
      title: '操作', key: 'actions', width: 260,
      render: (_: unknown, r: TitleReviewApplication) => (
        <Space size={4} wrap>
          <Button size="small" onClick={() => openDetail(r)}>详情</Button>
          {reviewOpen && canManage && r.status === 'voting' && (
            <Button size="small" icon={<TeamOutlined />} onClick={() => openJudgeModal(r)}>指定评委</Button>
          )}
          {reviewOpen && canManage && r.status === 'voting' && (
            <Button size="small" type="primary" onClick={() => runAction(finalizeTitleVotes, r.id, '已按票数判定')}>按当前票数判定</Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Typography.Text type="secondary">
          申报记录自动同步自飞书申报表（约 5 分钟内）；员工申报先经飞书审批（部门负责人→HR），通过后进入投票
        </Typography.Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </div>

      <Table
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1100 }}
        pagination={{
          current: page,
          pageSize: 20,
          total,
          onChange: setPage,
          showTotal: (t) => `共 ${t} 条`,
        }}
      />

      <Drawer
        title={detail ? `${detail.name}（${detail.employee_no}）申报详情` : '申报详情'}
        open={!!detail}
        width={640}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <div className="space-y-4">
            <div>
              <Typography.Text strong>申报信息</Typography.Text>
              <Descriptions column={2} size="small" bordered className="mt-2">
                <Descriptions.Item label="部门">{detail.department || '-'}</Descriptions.Item>
                <Descriptions.Item label="申报序列">{detail.sequence || '-'}</Descriptions.Item>
                <Descriptions.Item label="申报职级">{detail.apply_level || '-'}</Descriptions.Item>
                <Descriptions.Item label="现任职级">{detail.current_level || '-'}</Descriptions.Item>
                <Descriptions.Item label="是否破格">{detail.is_exception ? '是' : '否'}</Descriptions.Item>
                <Descriptions.Item label="申报时间">
                  {detail.created_at ? new Date(detail.created_at).toLocaleString('zh-CN', { hour12: false }) : '-'}
                </Descriptions.Item>
              </Descriptions>
            </div>
            <div className="flex items-center gap-6">
              <div>
                <Typography.Text type="secondary" className="text-[12px]">流程状态</Typography.Text>
                <div className="mt-1">
                  <Tag color={APP_STATUS_META[detail.status]?.color}>
                    {APP_STATUS_META[detail.status]?.label || detail.status}
                  </Tag>
                </div>
              </div>
              {!['submitted', 'invalid'].includes(detail.status) && (
                <div>
                  <Typography.Text type="secondary" className="text-[12px]">票数（同意/反对/弃权）</Typography.Text>
                  <div className="mt-1 text-[14px]">
                    {`${detail.agree_votes} / ${detail.oppose_votes} / ${detail.abstain_votes}`}
                  </div>
                </div>
              )}
            </div>
            {detail.exception_reason && (
              <Typography.Paragraph><Typography.Text strong>破格理由：</Typography.Text>{detail.exception_reason}</Typography.Paragraph>
            )}
            <TitleReviewProfile profile={detail.profile} />
            {detail.self_evaluations && Object.keys(detail.self_evaluations).length > 0 && (
              <div>
                <Typography.Text strong>自我评价</Typography.Text>
                <Descriptions column={1} size="small" bordered className="mt-2">
                  {Object.entries(detail.self_evaluations).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>
                  ))}
                </Descriptions>
              </div>
            )}
            {detail.work_statements && Object.keys(detail.work_statements).length > 0 && (
              <div>
                <Typography.Text strong>业绩陈述</Typography.Text>
                <Descriptions column={1} size="small" bordered className="mt-2">
                  {Object.entries(detail.work_statements).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      <TitleReviewWorkValue name={k} value={v} />
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </div>
            )}
            {detail.attachments && (
              <div>
                <Typography.Text strong>附件材料</Typography.Text>
                <div className="mt-2 space-y-1">
                  {Object.entries(detail.attachments).map(([k, files]) => (
                    <div key={k} className="text-[13px]">
                      {k}：{(files || []).map((f: any) => f.name).join('、') || '无'}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.judges.length > 0 && (
              <div>
                <Typography.Text strong>评委（编号匿名，投票表可见）</Typography.Text>
                <div className="mt-2 space-x-1">
                  {detail.judges.map((j) => (
                    <Tag key={j.id} color={j.vote_result ? 'success' : 'default'}>
                      {j.judge_code} {j.judge_name}（{j.judge_role || '-'}）
                      {j.vote_result ? ` · ${j.vote_result}` : ' · 未投'}
                    </Tag>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>

      <Modal
        title={judgeModal ? `指定评委：${judgeModal.name}（${judgeModal.employee_no}）` : '指定评委'}
        open={!!judgeModal}
        width={680}
        confirmLoading={saving}
        onCancel={() => setJudgeModal(null)}
        onOk={handleAssign}
        okText="保存评委"
      >
        <div className="mt-4 space-y-2">
          <Typography.Text type="secondary">
            默认带出部门评定小组成员；已投票的评委不可撤换；评委在投票表以匿名编号（P1/P2…）显示。
          </Typography.Text>
          {selectedJudges.map((j, idx) => (
            <div key={j.employee_id} className="flex items-center gap-2">
              <Typography.Text style={{ width: 180 }} ellipsis>
                {j.name}（{j.employee_no || '-'}）
              </Typography.Text>
              <Select
                style={{ width: 130 }}
                value={j.role}
                options={JUDGE_ROLES.map((r) => ({ value: r, label: r }))}
                onChange={(v) =>
                  setSelectedJudges(selectedJudges.map((x, i) => (i === idx ? { ...x, role: v } : x)))
                }
              />
              <Button
                size="small"
                danger
                onClick={() => setSelectedJudges(selectedJudges.filter((_, i) => i !== idx))}
              >
                移除
              </Button>
            </div>
          ))}
          <Select
            style={{ width: '100%' }}
            placeholder="输入姓名/工号远程搜索添加评委（在职员工）"
            showSearch
            filterOption={false}
            loading={employeeSearching}
            onSearch={searchEmployees}
            value={null as any}
            options={employeeOptions
              .filter((e) => !selectedJudges.some((j) => j.employee_id === e.id))
              .map((e) => ({ value: e.id, label: `${e.name}（${e.employee_number} · ${e.department}）` }))}
            onChange={(id: string) => {
              const emp = employeeOptions.find((x) => x.id === id)
              if (emp) {
                setSelectedJudges([...selectedJudges, { employee_id: emp.id, name: emp.name, employee_no: emp.employee_number, role: '技术专家' }])
              }
            }}
          />
        </div>
      </Modal>
    </div>
  )
}
