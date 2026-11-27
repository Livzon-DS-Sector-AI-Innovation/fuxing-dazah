'use client'

// 员工档案「离职材料」页签（一人一事一档）：这个人的离职办理进度、证明、签收、交接都在这一页看。
// 还没发起办理的，在这里直接发起；办过的直接打开办理抽屉接着办。

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Alert, App as AntdApp, Button, Descriptions, Space, Spin, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { downloadOffboardingCertificate, fetchOffboardingCaseByEmployee } from '@/actions/hr'
import { useHasPermission } from '@/hooks/hr'
import {
  downloadBase64File,
  NEXT_STEP_HINT,
  OFFBOARDING_STATUS_TAG_COLORS,
  signWayLabel,
  STEPPER_STAGES,
  stepperIndex,
} from '@/lib/hr'
import type { Employee, OffboardingCaseByEmployee } from '@/types/hr'
import OffboardingCaseDrawer from '@/components/hr/OffboardingCaseDrawer'
import OffboardingNewCaseModal, { type OffboardingCasePrefill } from '@/components/hr/OffboardingNewCaseModal'

export default function EmployeeOffboardingPanel({ employee }: { employee: Employee }) {
  const { message } = AntdApp.useApp()
  const router = useRouter()
  const canManage = useHasPermission('hr:departure:manage')
  const [data, setData] = useState<OffboardingCaseByEmployee | null>(null)
  const [failed, setFailed] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [startOpen, setStartOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const load = useCallback(async () => {
    try {
      setData(await fetchOffboardingCaseByEmployee(employee.employee_number))
    } catch {
      setFailed(true)
    }
  }, [employee.employee_number])

  useEffect(() => {
    // 加载函数里的写状态都在 await 之后，不在 effect 里同步触发级联渲染（与仓库其它页面同一写法）
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  if (failed) return <Alert type="error" showIcon title="离职材料加载失败，请稍后再试" />
  if (!data) return <Spin className="block py-6" />

  const offboarding = data.case
  const mayStart = canManage && data.startable && employee.status !== '离职'
  // 从档案发起：不挂台账行，离职日期和类型可以直接改
  const prefill: OffboardingCasePrefill = {
    employeeId: employee.id,
    employeeNumber: employee.employee_number || '',
    label: `${employee.employee_number} ${employee.name}（${employee.department} / ${employee.position || '-'}）`,
    offboardingDate: '',
    offboardingType: '辞职',
    ledgerSynced: false,
  }
  const afterCreated = (id: string) => {
    setStartOpen(false)
    // 接着到离职管理页办：那边会直接打开这张办理单
    router.push(`/hr/departure?case=${id}`)
  }

  if (!offboarding) {
    return (
      <div className="space-y-3 py-2">
        <div className="text-[13px] text-[var(--color-slate)]">
          {employee.status === '离职'
            ? '这位员工已是离职状态，但没有在系统里办过离职流程（历史记录）。需要补开证明请到「离职管理 → 离职台账」。'
            : '还没有发起离职办理。要给这位员工办离职，点下面的按钮：提交审批、清退会签、开具证明和送达会一步步带着走。'}
        </div>
        {mayStart && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setStartOpen(true)}>
            发起离职办理
          </Button>
        )}
        <OffboardingNewCaseModal
          open={startOpen}
          prefill={prefill}
          onClose={() => setStartOpen(false)}
          onCreated={afterCreated}
        />
      </div>
    )
  }

  const stepper = stepperIndex(offboarding.status)
  const finished = offboarding.status === 'closed'
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Tag color={OFFBOARDING_STATUS_TAG_COLORS[offboarding.status] || 'default'}>{offboarding.status_label}</Tag>
        <span className="text-[13px] text-[var(--color-slate)]">申请编号 {offboarding.case_no}</span>
        <span className="text-[13px] text-[var(--color-ink)]">{NEXT_STEP_HINT[offboarding.status]}</span>
        <Button type="primary" size="small" onClick={() => setDrawerOpen(true)}>
          {finished ? '查看办理记录' : '打开办理'}
        </Button>
      </div>

      {/* 七步进度：与离职办理抽屉同一套节点和位置 */}
      <ol className="m-0 flex list-none flex-wrap gap-2 p-0">
        {STEPPER_STAGES.map((stage, idx) => {
          const done = idx < stepper.current || stepper.status === 'finish'
          const current = idx === stepper.current && stepper.status !== 'finish'
          return (
            <li
              key={stage.key}
              className={`rounded-[var(--rounded-sm)] border px-2 py-1 text-[12px] ${
                current
                  ? 'border-[var(--color-ink)] bg-[var(--color-surface)] font-medium text-[var(--color-ink)]'
                  : done
                    ? 'border-[var(--color-hairline)] bg-[var(--color-canvas)] text-[var(--color-slate)]'
                    : 'border-[var(--color-hairline)] text-[var(--color-steel)]'
              }`}
            >
              {done ? `✓ ${stage.title}` : stage.title}
            </li>
          )
        })}
      </ol>

      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, sm: 2 }}
        items={[
          { key: 'date', label: '离职日期', children: offboarding.offboarding_date },
          { key: 'type', label: '离职类型', children: offboarding.offboarding_type },
          { key: 'reason', label: '离职原因', children: offboarding.reason || '-' },
          {
            key: 'cert',
            label: '离职证明',
            children: offboarding.cert_issued_at ? `已开具${offboarding.cert_issued_by ? `（${offboarding.cert_issued_by}）` : ''}` : '未开具',
          },
          {
            key: 'sign',
            label: '员工签收',
            children: ['closed', 'signed'].includes(offboarding.status)
              ? signWayLabel(offboarding.delivery_channel)
              : '未签收',
          },
          {
            key: 'handover',
            label: '交接人 / 部门办事员',
            children: [offboarding.handover_to, offboarding.dept_clerk].filter(Boolean).join(' / ') || '-',
          },
        ]}
      />

      <Space wrap>
        {offboarding.cert_issued_at && (
          <Button
            loading={downloading}
            onClick={() => {
              setDownloading(true)
              downloadOffboardingCertificate(offboarding.id, offboarding.case_no)
                .then((file) => downloadBase64File(file.base64, file.filename))
                .catch((err) => message.error(err instanceof Error ? err.message : '下载证明失败'))
                .finally(() => setDownloading(false))
            }}
          >
            下载离职证明
          </Button>
        )}
        {offboarding.status === 'canceled' && mayStart && (
          <Button icon={<PlusOutlined />} onClick={() => setStartOpen(true)}>重新发起</Button>
        )}
      </Space>

      <OffboardingCaseDrawer
        open={drawerOpen}
        caseId={offboarding.id}
        onClose={() => setDrawerOpen(false)}
        onChanged={() => void load()}
      />
      <OffboardingNewCaseModal
        open={startOpen}
        prefill={prefill}
        onClose={() => setStartOpen(false)}
        onCreated={afterCreated}
      />
    </div>
  )
}
