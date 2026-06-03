'use client'

import { App, Drawer, Descriptions, Tag, Timeline, Button, Space, Select, Input, Modal } from 'antd'
import {
  ClockCircleOutlined, UserOutlined, ToolOutlined,
  CheckCircleOutlined, CloseCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useEquipmentStore } from '@/stores/equipment'
import { assignWorkOrder, startWorkOrder, completeWorkOrder, verifyWorkOrder, closeWorkOrder } from '@/actions/equipment'
import { WorkOrderStatus, WorkOrderPriority } from '@/types/equipment'

const { TextArea } = Input

const statusConfig: Record<WorkOrderStatus, { color: string; label: string }> = {
  '待处理': { color: '#e03131', label: '待处理' },
  '已指派': { color: '#5645d4', label: '已指派' },
  '维修中': { color: '#dd5b00', label: '维修中' },
  '待验收': { color: '#d4b106', label: '待验收' },
  '已完成': { color: '#1aae39', label: '已完成' },
  '已关闭': { color: '#787671', label: '已关闭' },
}

const priorityConfig: Record<WorkOrderPriority, { color: string }> = {
  '紧急': { color: '#e03131' },
  '高': { color: '#dd5b00' },
  '中': { color: '#5645d4' },
  '低': { color: '#787671' },
}

function formatDuration(minutes: number | null): string {
  if (minutes === null || minutes === undefined) return '-'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins > 0 ? `${hours}小时${mins}分` : `${hours}小时`
}

function formatTime(time: string | null): string {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

interface WorkOrderDetailDrawerProps {
  onRefresh?: () => void
}

export function WorkOrderDetailDrawer({ onRefresh }: WorkOrderDetailDrawerProps) {
  const { message, modal } = App.useApp()
  const { workOrderDetailOpen, viewingWorkOrder, closeWorkOrderDetail } = useEquipmentStore()

  if (!viewingWorkOrder) return null

  const wo = viewingWorkOrder
  const statusCfg = statusConfig[wo.status]
  const priorityCfg = priorityConfig[wo.priority]

  const handleAssign = () => {
    let assigneeId = ''
    modal.confirm({
      title: '指派维修人',
      content: (
        <div style={{ marginTop: 16 }}>
          <Select
            placeholder="输入维修人ID"
            style={{ width: '100%' }}
            onChange={(val) => { assigneeId = val }}
            options={[]}
          />
          <div style={{ marginTop: 8, fontSize: 12, color: '#787671' }}>请输入维修人员的用户ID</div>
        </div>
      ),
      okText: '确认指派',
      cancelText: '取消',
      onOk: async () => {
        if (!assigneeId) { message.warning('请输入维修人ID'); throw new Error() }
        try {
          await assignWorkOrder(wo.id, { assignee_id: assigneeId })
          message.success('指派成功')
          onRefresh?.()
        } catch (error: any) {
          message.error(error?.message || '指派失败')
          throw error
        }
      },
    })
  }

  const handleStart = async () => {
    try {
      await startWorkOrder(wo.id)
      message.success('已开始维修')
      onRefresh?.()
    } catch (error: any) {
      message.error(error?.message || '操作失败')
    }
  }

  const handleComplete = () => {
    let repairDetail = ''
    modal.confirm({
      title: '提交维修完成',
      content: (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8, fontSize: 14, color: '#37352f' }}>维修过程描述 *</div>
          <TextArea
            placeholder="请详细描述维修过程和处理措施"
            rows={4}
            maxLength={1000}
            showCount
            onChange={(e) => { repairDetail = e.target.value }}
          />
        </div>
      ),
      okText: '提交',
      cancelText: '取消',
      onOk: async () => {
        if (!repairDetail.trim()) { message.warning('请填写维修过程描述'); throw new Error() }
        try {
          await completeWorkOrder(wo.id, { repair_detail: repairDetail })
          message.success('已提交验收')
          onRefresh?.()
        } catch (error: any) {
          message.error(error?.message || '操作失败')
          throw error
        }
      },
    })
  }

  const handleVerify = (result: '合格' | '不合格') => {
    let remark = ''
    modal.confirm({
      title: result === '合格' ? '验收通过' : '验收不通过',
      content: (
        <div style={{ marginTop: 16 }}>
          {result === '不合格' && <div style={{ marginBottom: 8, fontSize: 14, color: '#37352f' }}>不通过原因 *</div>}
          <TextArea
            placeholder={result === '合格' ? '验收备注（可选）' : '请说明不通过的原因'}
            rows={3} maxLength={500} showCount
            onChange={(e) => { remark = e.target.value }}
          />
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      okButtonProps: result === '不合格' ? { danger: true } : {},
      onOk: async () => {
        if (result === '不合格' && !remark.trim()) { message.warning('请填写不通过原因'); throw new Error() }
        try {
          await verifyWorkOrder(wo.id, { result, remark: remark || undefined })
          message.success(result === '合格' ? '验收通过' : '已打回重修')
          onRefresh?.()
        } catch (error: any) {
          message.error(error?.message || '操作失败')
          throw error
        }
      },
    })
  }

  const handleClose = async () => {
    try {
      await closeWorkOrder(wo.id)
      message.success('工单已关闭')
      onRefresh?.()
    } catch (error: any) {
      message.error(error?.message || '操作失败')
    }
  }

  const timelineItems = []
  if (wo.reported_at) {
    timelineItems.push({
      color: '#e03131',
      icon: <ClockCircleOutlined style={{ fontSize: 14 }} />,
      children: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>报修</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.reported_at)}</div>
        </div>
      ),
    })
  }
  if (wo.assigned_at) {
    timelineItems.push({
      color: '#5645d4',
      icon: <UserOutlined style={{ fontSize: 14 }} />,
      children: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>已指派</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.assigned_at)}</div>
        </div>
      ),
    })
  }
  if (wo.started_at) {
    timelineItems.push({
      color: '#dd5b00',
      icon: <ToolOutlined style={{ fontSize: 14 }} />,
      children: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>开始维修</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.started_at)}</div>
        </div>
      ),
    })
  }
  if (wo.completed_at) {
    timelineItems.push({
      color: '#d4b106',
      icon: <CheckCircleOutlined style={{ fontSize: 14 }} />,
      children: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>提交完成</div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.completed_at)}</div>
          {wo.repair_detail && <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 4 }}>维修描述: {wo.repair_detail}</div>}
        </div>
      ),
    })
  }
  if (wo.verified_at) {
    timelineItems.push({
      color: wo.verification_result === '合格' ? '#1aae39' : '#e03131',
      icon: wo.verification_result === '合格'
        ? <CheckCircleOutlined style={{ fontSize: 14 }} />
        : <CloseCircleOutlined style={{ fontSize: 14 }} />,
      children: (
        <div>
          <div style={{ fontWeight: 500, color: '#1a1a1a' }}>
            验收 - <Tag color={wo.verification_result === '合格' ? 'success' : 'error'}>{wo.verification_result}</Tag>
          </div>
          <div style={{ fontSize: 13, color: '#787671' }}>{formatTime(wo.verified_at)}</div>
          {wo.verification_remark && <div style={{ fontSize: 13, color: '#5d5b54', marginTop: 4 }}>备注: {wo.verification_remark}</div>}
        </div>
      ),
    })
  }
  if (wo.status === '已关闭') {
    timelineItems.push({
      color: '#787671',
      icon: <StopOutlined style={{ fontSize: 14 }} />,
      children: <div><div style={{ fontWeight: 500, color: '#1a1a1a' }}>已关闭</div></div>,
    })
  }

  return (
    <Drawer
      title={
        <div className="flex items-center gap-3">
          <span style={{ fontWeight: 600 }}>{wo.work_order_no}</span>
          <Tag style={{ color: statusCfg.color, background: statusCfg.color + '18', border: 'none', borderRadius: 4, fontWeight: 500 }}>
            {statusCfg.label}
          </Tag>
        </div>
      }
      size={520}
      open={workOrderDetailOpen}
      onClose={closeWorkOrderDetail}
      destroyOnHidden
    >
      <Descriptions column={2} size="small" styles={{ label: { color: '#787671', fontSize: 13 }, content: { color: '#1a1a1a', fontSize: 14 } }}>
        <Descriptions.Item label="工单类型">
          <Tag style={{
            color: wo.order_type === '故障维修' ? '#dd5b00' : '#5645d4',
            background: wo.order_type === '故障维修' ? '#fff7e6' : '#ede9f7',
            border: 'none', borderRadius: 4,
          }}>{wo.order_type}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="优先级">
          <span style={{ color: priorityCfg.color, fontWeight: 500 }}>{wo.priority}</span>
        </Descriptions.Item>
        <Descriptions.Item label="关联设备" span={2}>{wo.equipment_name || wo.equipment_id}</Descriptions.Item>
        <Descriptions.Item label="故障现象" span={2}>{wo.symptom_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="故障描述" span={2}>{wo.fault_description || '-'}</Descriptions.Item>
        <Descriptions.Item label="报修时间">{formatTime(wo.reported_at)}</Descriptions.Item>
        <Descriptions.Item label="维修耗时">{formatDuration(wo.actual_duration)}</Descriptions.Item>
      </Descriptions>

      <div style={{ marginTop: 24, marginBottom: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#1a1a1a', marginBottom: 16 }}>工单进度</div>
        <Timeline items={timelineItems} />
      </div>

      <div style={{ borderTop: '1px solid #ede9e4', paddingTop: 16 }}>
        <Space wrap>
          {wo.status === '待处理' && <Button type="primary" onClick={handleAssign}>指派维修人</Button>}
          {wo.status === '已指派' && <Button type="primary" onClick={handleStart}>开始维修</Button>}
          {wo.status === '维修中' && <Button type="primary" onClick={handleComplete}>提交完成</Button>}
          {wo.status === '待验收' && (
            <>
              <Button type="primary" onClick={() => handleVerify('合格')}>验收通过</Button>
              <Button danger onClick={() => handleVerify('不合格')}>打回重修</Button>
            </>
          )}
          {wo.status === '已完成' && <Button onClick={handleClose}>关闭工单</Button>}
        </Space>
      </div>
    </Drawer>
  )
}
