'use client'

// 员工档案「列设置」：按分组勾选要显示的列，提供「常用列 / 全部列」两个预设，选择持久化在本地。
// 此前没有任何列显隐控制，表格固定摊开 42 列（横向 4800px）。

import { useMemo, useState, useSyncExternalStore } from 'react'
import { Badge, Button, Checkbox, Dropdown, Tooltip, type MenuProps } from 'antd'
import { SettingOutlined } from '@ant-design/icons'

/** 列分组（key 与 columns.tsx 的列 key 一致；标题与表头一致） */
export const COLUMN_GROUPS: { title: string; keys: { key: string; label: string }[] }[] = [
  {
    title: '基本信息',
    keys: [
      { key: 'employee_number', label: '工号' }, { key: 'name', label: '姓名' }, { key: 'department', label: '部门' },
      { key: 'position', label: '岗位' }, { key: 'duty', label: '职务' }, { key: 'job_category', label: '职能分类' },
      { key: 'level', label: '职级' }, { key: 'report_grade', label: '岗位职级' },
      { key: 'status_category', label: '员工性质' }, { key: 'status', label: '状态' },
    ],
  },
  {
    title: '个人',
    keys: [
      { key: 'domain_account', label: '域账号' }, { key: 'gender', label: '性别' }, { key: 'age', label: '年龄' },
      { key: 'birth_date', label: '出生日期' }, { key: 'ethnicity', label: '民族' }, { key: 'native_place', label: '籍贯' },
      { key: 'marital_status', label: '婚姻状况' }, { key: 'household_type', label: '户口类型' },
    ],
  },
  {
    title: '学历',
    keys: [
      { key: 'education', label: '学历' }, { key: 'degree_type', label: '学位类型' }, { key: 'classification', label: '学习形式' },
      { key: 'school', label: '毕业院校' }, { key: 'major', label: '专业' }, { key: 'graduation_date', label: '毕业时间' },
      { key: 'hr_analysis', label: '人力资源分析' },
    ],
  },
  {
    title: '联系与证件',
    keys: [
      { key: 'phone', label: '联系电话' }, { key: 'current_address', label: '居住地址' },
      { key: 'id_card', label: '身份证号' }, { key: 'id_card_expiry', label: '身份证有效期' },
      { key: 'emergency_contact_name', label: '紧急联系人-姓名' },
      { key: 'emergency_contact_phone', label: '紧急联系人-联系电话' },
      { key: 'emergency_contact_relation', label: '紧急联系人-关系' },
    ],
  },
  {
    title: '工作与合同',
    keys: [
      { key: 'work_start_date', label: '参加工作时间' }, { key: 'hire_date', label: '入职日期' },
      { key: 'departure_date', label: '离职日期' }, { key: 'departure_reason', label: '离职原因' },
      { key: 'company_tenure', label: '司龄' }, { key: 'contract_start_date', label: '合同开始日期' },
      { key: 'contract_end_date', label: '合同结束日期' },
    ],
  },
  {
    title: '其他',
    keys: [
      { key: 'certificates', label: '证书' }, { key: 'transfer_history', label: '任命与岗位调动' },
    ],
  },
]

/** 全部列 key（操作列不在其中，恒显示） */
export const ALL_COLUMN_KEYS: string[] = COLUMN_GROUPS.flatMap(g => g.keys.map(k => k.key))

/** 默认视图「常用列」 */
export const COMMON_COLUMN_KEYS: string[] = [
  'employee_number', 'name', 'department', 'position', 'duty', 'level', 'status_category', 'status',
  'hire_date', 'education', 'phone',
]

const LS_KEY = 'hr_profile_columns_v1'

/** 默认视图下隐藏的列（「全部列」里不属于常用列的那些） */
const DEFAULT_HIDDEN: string[] = ALL_COLUMN_KEYS.filter(k => !COMMON_COLUMN_KEYS.includes(k))

function parseHidden(raw: string | null): string[] {
  if (!raw) return DEFAULT_HIDDEN
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT_HIDDEN
    const known = new Set(ALL_COLUMN_KEYS)
    // 只认当前仍存在的列（以后列有增删时自动忽略过期项）
    return parsed.filter((k): k is string => typeof k === 'string' && known.has(k))
  } catch {
    return DEFAULT_HIDDEN
  }
}

// 本地存储是只存在于浏览器的外部数据：服务端渲染只能用默认值，客户端首帧若直接读本地存储，
// 用户改过列以后每次刷新都会 hydration 不一致。走 useSyncExternalStore——
// 首帧用 getServerSnapshot（与 SSR 一致），挂载后再切到本地存储里的值。
// 快照须「同一份数据同一引用」，所以按读取结果缓存。
let hiddenSnapshot: string[] | null = null
const hiddenListeners = new Set<() => void>()

function readHidden(): string[] {
  if (hiddenSnapshot) return hiddenSnapshot
  let raw: string | null = null
  try { raw = localStorage.getItem(LS_KEY) } catch { /* 隐私模式等读取失败时用默认值 */ }
  hiddenSnapshot = parseHidden(raw)
  return hiddenSnapshot
}

function subscribeHidden(notify: () => void) {
  hiddenListeners.add(notify)
  // 其它标签页里改了列设置时跟着变
  const onStorage = (e: StorageEvent) => {
    if (e.key !== LS_KEY && e.key !== null) return
    hiddenSnapshot = null
    notify()
  }
  window.addEventListener('storage', onStorage)
  return () => { hiddenListeners.delete(notify); window.removeEventListener('storage', onStorage) }
}

function writeHidden(next: string[]) {
  hiddenSnapshot = next
  try { localStorage.setItem(LS_KEY, JSON.stringify(next)) } catch { /* 写入失败时仅本次会话内生效 */ }
  for (const notify of hiddenListeners) notify()
}

/** 列显隐状态 + 本地持久化 */
export function useProfileColumnSettings() {
  const hiddenKeys = useSyncExternalStore(subscribeHidden, readHidden, () => DEFAULT_HIDDEN)
  const hiddenSet = useMemo(() => new Set(hiddenKeys), [hiddenKeys])

  return {
    hiddenSet,
    hiddenCount: hiddenKeys.length,
    setHiddenKeys: writeHidden,
    showCommon: () => writeHidden(DEFAULT_HIDDEN),
    showAll: () => writeHidden([]),
  }
}

interface ColumnSettingsProps {
  hiddenSet: ReadonlySet<string>
  hiddenCount: number
  onChange: (nextHidden: string[]) => void
  onShowCommon: () => void
  onShowAll: () => void
}

export default function ColumnSettings({ hiddenSet, hiddenCount, onChange, onShowCommon, onShowAll }: ColumnSettingsProps) {
  // Dropdown 关闭后再卸载内容会丢勾选的即时反馈，这里用 open 受控保证勾选时面板不闪
  const [open, setOpen] = useState(false)

  const panel: MenuProps['items'] = [
    {
      key: 'presets',
      label: (
        <div className="flex items-center gap-2 py-1">
          <Button size="small" onClick={() => { onShowCommon(); setOpen(false) }}>常用列</Button>
          <Button size="small" onClick={() => { onShowAll(); setOpen(false) }}>全部列</Button>
          <span className="text-xs text-[var(--color-steel)]">已隐藏 {hiddenCount} 列</span>
        </div>
      ),
    },
    { key: 'divider', type: 'divider' },
    ...COLUMN_GROUPS.map(group => ({
      key: `group-${group.title}`,
      label: (
        <div className="py-1">
          <div className="text-xs text-[var(--color-steel)] mb-1">{group.title}</div>
          <Checkbox.Group
            value={group.keys.map(k => k.key).filter(k => !hiddenSet.has(k))}
            onChange={checked => {
              const visible = new Set(checked as string[])
              // 本组内：勾选=显示，取消=隐藏；其它组保持不变
              const others = [...hiddenSet].filter(k => !group.keys.some(g => g.key === k))
              const hiddenInGroup = group.keys.map(k => k.key).filter(k => !visible.has(k))
              onChange([...others, ...hiddenInGroup])
            }}
          >
            <div className="flex flex-col gap-1">
              {group.keys.map(k => (
                <Checkbox key={k.key} value={k.key}>
                  <span className="text-[13px]">{k.label}</span>
                </Checkbox>
              ))}
            </div>
          </Checkbox.Group>
        </div>
      ),
    })),
  ]

  return (
    <Dropdown
      open={open}
      onOpenChange={(next) => setOpen(next)}
      trigger={['click']}
      menu={{ items: panel, style: { maxHeight: '60vh', overflowY: 'auto', padding: 4 } }}
    >
      <Tooltip title="选择要显示的列">
        <Badge count={hiddenCount} size="small" offset={[-4, 2]}>
          <Button icon={<SettingOutlined />} aria-label="列设置">
            列设置
          </Button>
        </Badge>
      </Tooltip>
    </Dropdown>
  )
}
