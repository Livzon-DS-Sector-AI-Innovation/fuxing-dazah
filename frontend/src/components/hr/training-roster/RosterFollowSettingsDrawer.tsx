'use client'

// 培训人员名单「跟随设置」抽屉（系统配置权限）。名单人员始终随员工档案进出，
// 这里配置名单上的信息在多大程度上跟随档案，三层规则按优先级从低到高：
// ① 字段跟随（对所有人生效）：打开的字段每轮同步用档案值覆盖，名单上不可手改；
// ② 部门例外：按名单上的体现部门，把整个部门设为「全部跟随档案」或「全部手动」；
// ③ 人员例外：个别人单独设置，优先于部门例外。
// 保存前先预览影响（覆盖多少人、各字段多少个值），确认后才落库。
// 父级按打开状态条件渲染本组件：每次打开都是干净状态，关闭即卸载。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Drawer, Select, Space, Spin, Switch, Table, Tag, Tooltip, Typography } from 'antd'
import { DeleteOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  fetchTrainingRoster,
  fetchTrainingRosterFollowConfig,
  saveTrainingRosterFollowConfig,
} from '@/actions/hr'
import type { TrainingRosterRow } from '@/actions/hr'
import { useDebouncedCallback, useUnsavedConfirm } from '@/hooks/hr'
import type {
  RosterFollowConfig, RosterFollowConfigInput, RosterFollowDepartmentException,
  RosterFollowException, RosterFollowMode, RosterFollowPreview,
} from '@/types/hr'

const { Text } = Typography

type Mode = Exclude<RosterFollowMode, ''>

const MODE_OPTIONS: { value: Mode; label: string }[] = [
  { value: 'manual', label: '全部手动' },
  { value: 'follow', label: '全部跟随档案' },
]

/** 新增例外的默认模式：例外多是「这个人/这个部门不跟随」 */
const DEFAULT_MODE: Mode = 'manual'

function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback
}

/** 规则的「指纹」：与已保存的配置比对，判断有没有未保存的改动 */
function signature(
  fields: string[],
  deptRules: RosterFollowDepartmentException[],
  exceptions: RosterFollowException[],
): string {
  return JSON.stringify({
    fields: [...fields].sort(),
    departments: deptRules.map((d) => [d.department, d.mode]).sort(),
    modes: exceptions.map((e) => [e.employee_number, e.mode]).sort(),
  })
}

function toModes<T extends { mode: Mode }>(
  items: T[], keyOf: (item: T) => string,
): Record<string, Mode> {
  return Object.fromEntries(items.map((item) => [keyOf(item), item.mode]))
}

/** 预览统计 → 一句话（按人数排序的前几个字段） */
function summarize(p: RosterFollowPreview, labelOf: (attr: string) => string): string {
  const total = Object.values(p.field_changes).reduce((sum, n) => sum + n, 0)
  const entries = Object.entries(p.field_changes).sort((a, b) => b[1] - a[1])
  const parts = entries.slice(0, 6).map(([attr, n]) => `${labelOf(attr)} ${n}`)
  const rest = entries.length - parts.length
  return `将覆盖 ${p.changed} 人的名单信息（共 ${total} 个字段值）`
    + (parts.length ? `：${parts.join('、')}` : '')
    + (rest > 0 ? ` 等 ${rest} 个字段…` : '')
}

interface PickerOption {
  value: string
  label: string
  row: TrainingRosterRow
}

function ModeSelect({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  return <Select<Mode> size="small" value={value} options={MODE_OPTIONS} style={{ width: 136 }} onChange={onChange} />
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <Button type="text" size="small" danger aria-label={label} icon={<DeleteOutlined />} onClick={onClick} />
}

interface RosterFollowSettingsDrawerProps {
  onClose: () => void
  /** 保存并应用后：名单上的跟随字段 / 例外模式已变，父级刷新列表 */
  onApplied: () => void
}

export default function RosterFollowSettingsDrawer({
  onClose, onApplied,
}: RosterFollowSettingsDrawerProps) {
  const { message, modal } = App.useApp()
  const [config, setConfig] = useState<RosterFollowConfig | null>(null)
  const [loadError, setLoadError] = useState('')
  // 加载失败后的「重试」：序号变化即重跑加载
  const [attempt, setAttempt] = useState(0)
  const [fields, setFields] = useState<string[]>([])
  const [deptRules, setDeptRules] = useState<RosterFollowDepartmentException[]>([])
  const [exceptions, setExceptions] = useState<RosterFollowException[]>([])
  const [preview, setPreview] = useState<RosterFollowPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)

  // 挂载即拉规则（inline promise：不在 effect 里调具名 loader）
  useEffect(() => {
    let cancelled = false
    fetchTrainingRosterFollowConfig()
      .then((r) => {
        if (cancelled) return
        setConfig(r.data)
        setFields(r.data.fields)
        setDeptRules(r.data.department_exceptions)
        setExceptions(r.data.exceptions)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(errText(err, '加载名单跟随规则失败'))
      })
    return () => { cancelled = true }
  }, [attempt])

  const dirty = config !== null && (
    signature(fields, deptRules, exceptions)
    !== signature(config.fields, config.department_exceptions, config.exceptions)
  )
  const guardClose = useUnsavedConfirm(dirty, onClose)

  const labelOf = useMemo(() => {
    const map = new Map<string, string>()
    config?.followable.forEach((o) => map.set(o.attr, o.label))
    return (attr: string) => map.get(attr) ?? attr
  }, [config])

  /** 规则一改，上一次的预览就过期了 */
  const updateFields = (next: string[]) => { setFields(next); setPreview(null) }
  const updateDeptRules = (next: RosterFollowDepartmentException[]) => { setDeptRules(next); setPreview(null) }
  const updateExceptions = (next: RosterFollowException[]) => { setExceptions(next); setPreview(null) }

  /** 组装入参：预览 / 保存前复核 / 应用三处共用，避免漏带某一层规则 */
  const buildInput = (apply: boolean): RosterFollowConfigInput => ({
    fields,
    member_modes: toModes(exceptions, (e) => e.employee_number),
    department_modes: toModes(deptRules, (d) => d.department),
    apply,
  })

  // ── 部门例外：从名单上出现过的体现部门里选 ──
  // 可选清单 = 接口下发的可选部门 ∪ 已配置的部门（后者移除规则后要能重新选到）
  const allDepartments = useMemo(() => {
    const counts = new Map<string, number>()
    config?.departments.forEach((d) => counts.set(d.name, d.count))
    config?.department_exceptions.forEach((d) => counts.set(d.department, d.count))
    return [...counts]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [config])
  const deptNames = useMemo(() => new Set(deptRules.map((d) => d.department)), [deptRules])
  const deptOptions = allDepartments
    .filter((d) => !deptNames.has(d.name))
    .map((d) => ({ value: d.name, label: `${d.name}（${d.count} 人）` }))

  const addDepartment = (name: string) => {
    if (!name || deptNames.has(name)) return
    const count = allDepartments.find((d) => d.name === name)?.count ?? 0
    updateDeptRules([...deptRules, { department: name, mode: DEFAULT_MODE, count }])
  }

  const deptColumns: ColumnsType<RosterFollowDepartmentException> = [
    { title: '部门', dataIndex: 'department' },
    {
      title: '名单当前人数', dataIndex: 'count', width: 200,
      // 体现部门改名或人员调走后规则会匹配不到人：人数为 0 时点明「不生效」
      render: (count: number) => (count > 0 ? `${count} 人` : (
        <Tooltip title="名单上已没有体现部门为该部门的人（部门改名或人员调走），这条规则目前不生效">
          <Text type="warning">0 人 · 规则不生效</Text>
        </Tooltip>
      )),
    },
    {
      title: '模式', key: 'mode', width: 150,
      render: (_: unknown, d) => (
        <ModeSelect
          value={d.mode}
          onChange={(mode) => updateDeptRules(
            deptRules.map((x) => (x.department === d.department ? { ...x, mode } : x)),
          )}
        />
      ),
    },
    {
      title: '', key: 'action', width: 44,
      render: (_: unknown, d) => (
        <RemoveButton
          label="移除部门例外"
          onClick={() => updateDeptRules(deptRules.filter((x) => x.department !== d.department))}
        />
      ),
    },
  ]

  // ── 人员例外：远程搜索名单选人 ──
  const [candidates, setCandidates] = useState<TrainingRosterRow[]>([])
  const [searching, setSearching] = useState(false)
  const searchSeq = useRef(0)

  const searchRoster = useCallback(async (kw: string) => {
    // 请求序号守卫：慢请求晚归时丢弃，避免旧结果覆盖新关键词的结果
    const seq = ++searchSeq.current
    setSearching(true)
    try {
      const res = await fetchTrainingRoster({ keyword: kw || undefined, page: 1, page_size: 20 })
      if (seq !== searchSeq.current) return
      setCandidates(res.data || [])
    } catch {
      if (seq === searchSeq.current) setCandidates([])
    } finally {
      if (seq === searchSeq.current) setSearching(false)
    }
  }, [])

  const { run: debouncedSearch } = useDebouncedCallback(
    (kw: string) => { void searchRoster(kw) }, 250,
  )

  const exceptionNos = useMemo(() => new Set(exceptions.map((e) => e.employee_number)), [exceptions])
  const pickerOptions: PickerOption[] = candidates
    .filter((r) => !exceptionNos.has(r.employee_number))
    .map((r) => ({
      value: r.employee_number,
      // 同名员工靠工号区分
      label: `${r.name}（${r.employee_number}）`,
      row: r,
    }))

  const addException = (number: string) => {
    if (!number || exceptionNos.has(number)) return
    const row = candidates.find((r) => r.employee_number === number)
    updateExceptions([...exceptions, {
      employee_number: number, mode: DEFAULT_MODE,
      name: row?.name ?? null, department: row?.department ?? null,
    }])
  }

  const exceptionColumns: ColumnsType<RosterFollowException> = [
    { title: '工号', dataIndex: 'employee_number', width: 110 },
    {
      title: '姓名', dataIndex: 'name', width: 110,
      render: (v: string | null) => v ?? (
        // 已移出名单的人保留例外：重新进名单时仍生效
        <Tooltip title="已移出培训名单；重新进入名单时例外仍然生效">
          <span className="text-[var(--color-stone)]">已移出名单</span>
        </Tooltip>
      ),
    },
    {
      title: '体现部门', dataIndex: 'department', ellipsis: true,
      render: (v: string | null) => v || '-',
    },
    {
      title: '模式', key: 'mode', width: 150,
      render: (_: unknown, e) => (
        <ModeSelect
          value={e.mode}
          onChange={(mode) => updateExceptions(
            exceptions.map((x) => (x.employee_number === e.employee_number ? { ...x, mode } : x)),
          )}
        />
      ),
    },
    {
      title: '', key: 'action', width: 44,
      render: (_: unknown, e) => (
        <RemoveButton
          label="移除例外"
          onClick={() => updateExceptions(exceptions.filter((x) => x.employee_number !== e.employee_number))}
        />
      ),
    },
  ]

  // ── 预览 / 保存 ──

  const runPreview = async () => {
    if (previewing || saving) return
    setPreviewing(true)
    try {
      const r = await saveTrainingRosterFollowConfig(buildInput(false))
      setPreview(r.data.preview)
    } catch (err) {
      message.error(errText(err, '预览失败'))
    } finally {
      setPreviewing(false)
    }
  }

  const apply = async () => {
    setSaving(true)
    try {
      const r = await saveTrainingRosterFollowConfig(buildInput(true))
      message.success(r.message || '规则已保存并生效')
      onApplied()
      onClose()
    } catch (err) {
      message.error(errText(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleSave = async () => {
    if (saving || previewing || !config) return
    setSaving(true)
    let stats: RosterFollowPreview
    try {
      // 页面上的预览可能已过期（之后又改过规则）：保存前按当前规则重新取影响数
      const r = await saveTrainingRosterFollowConfig(buildInput(false))
      stats = r.data.preview
    } catch (err) {
      message.error(errText(err, '保存失败'))
      setSaving(false)
      return
    }
    setSaving(false)
    setPreview(stats)
    if (stats.changed === 0) {
      await apply()
      return
    }
    modal.confirm({
      title: '保存并立即应用？',
      content: `${summarize(stats, labelOf)}。被覆盖的名单值无法恢复。`,
      okText: '保存并应用',
      cancelText: '再想想',
      onOk: () => { void apply() },
    })
  }

  const renderBody = () => {
    if (loadError) {
      return (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <span className="text-[14px] text-[var(--color-steel)]">{loadError}</span>
          <Button onClick={() => { setLoadError(''); setAttempt((n) => n + 1) }}>重试</Button>
        </div>
      )
    }
    if (!config) {
      return <div className="flex justify-center py-16"><Spin /></div>
    }
    return (
      <div className="space-y-7">
        <section>
          <h4 className="mb-1 text-[14px] font-semibold text-[var(--color-ink)]">字段跟随（对所有人生效）</h4>
          <p className="mb-3 text-[13px] leading-relaxed text-[var(--color-steel)]">
            打开的字段在每轮员工档案同步（每小时）后用档案值覆盖，名单上不可再手动修改；未打开的字段由培训管理独立维护。
          </p>
          <div className="grid grid-cols-2 gap-x-8">
            {config.followable.map((o) => (
              <div
                key={o.attr}
                className="flex h-10 items-center justify-between gap-3 border-b border-[var(--color-hairline-soft)] text-[14px] text-[var(--color-charcoal)]"
              >
                <span>{o.label}</span>
                <Switch
                  size="small"
                  aria-label={`${o.label}跟随员工档案`}
                  checked={fields.includes(o.attr)}
                  onChange={(checked) => updateFields(
                    checked ? [...fields, o.attr] : fields.filter((f) => f !== o.attr),
                  )}
                />
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2 text-[13px] text-[var(--color-steel)]">
            <Switch size="small" checked disabled />
            <span>
              「{config.locked.map((o) => o.label).join('、')}」始终跟随档案（病假/产假/离职统计依赖），不可关闭。
            </span>
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-[var(--color-stone)]">
            只能在名单维护（员工档案没有对应字段）：{config.unsupported.map((o) => o.label).join('、')}。
          </p>
        </section>

        <section>
          <h4 className="mb-1 text-[14px] font-semibold text-[var(--color-ink)]">部门例外（优先于字段开关，低于人员例外）</h4>
          <p className="mb-3 text-[13px] leading-relaxed text-[var(--color-steel)]">
            按名单上的「体现部门」匹配，对整个部门的人生效（如「某部门全部跟随档案」）。同一个人在下方人员例外里另有设置时，以人员例外为准。
          </p>
          <Select<string, { value: string; label: string }>
            showSearch={{ filterOption: (input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase()) }}
            placeholder="选择部门（括号内为名单上当前人数）"
            style={{ width: '100%' }}
            // 受控空值：选中即加入例外并清空（传 undefined 会被当成非受控，残留选中项）
            value={null}
            options={deptOptions}
            notFoundContent="没有可选的部门（都已配置）"
            popupMatchSelectWidth={false}
            onSelect={(value) => addDepartment(value)}
          />
          <Table<RosterFollowDepartmentException>
            className="mt-3"
            size="small"
            rowKey="department"
            columns={deptColumns}
            dataSource={deptRules}
            pagination={false}
            locale={{ emptyText: '还没有部门例外：各部门默认按上面的字段规则。' }}
          />
        </section>

        <section>
          <h4 className="mb-1 text-[14px] font-semibold text-[var(--color-ink)]">人员例外（优先于部门例外和字段开关）</h4>
          <p className="mb-3 text-[13px] leading-relaxed text-[var(--color-steel)]">
            个别的人可单独设为「全部跟随档案」或「全部手动」，不受上面规则的影响（如借调、兼任的人，名单上的部门要与档案不同）。「全部手动」的人，人员状态仍跟随档案。
          </p>
          <Select<string, PickerOption>
            showSearch={{ filterOption: false, onSearch: debouncedSearch }}
            placeholder="输入姓名或工号，从名单中选人"
            style={{ width: '100%' }}
            // 受控空值：选中即加入例外并清空搜索框（传 undefined 会被当成非受控，残留选中项）
            value={null}
            options={pickerOptions}
            loading={searching}
            notFoundContent={searching ? <Spin size="small" /> : '没有匹配的人员'}
            popupMatchSelectWidth={false}
            optionRender={(opt) => (
              <div className="flex items-baseline gap-2">
                <span className="font-medium">{opt.data.row.name}</span>
                <span className="text-[12px] text-[var(--color-stone)] tabular-nums">{opt.data.row.employee_number}</span>
                <span className="ml-auto pl-6 text-[12px] text-[var(--color-steel)]">
                  {[opt.data.row.department, opt.data.row.position].filter(Boolean).join(' / ')}
                </span>
              </div>
            )}
            onSelect={(value) => addException(value)}
          />
          <Table<RosterFollowException>
            className="mt-3"
            size="small"
            rowKey="employee_number"
            columns={exceptionColumns}
            dataSource={exceptions}
            pagination={false}
            locale={{ emptyText: '还没有例外：所有人默认按上面的规则。' }}
          />
        </section>

        {preview && (
          <Alert
            type={preview.changed > 0 ? 'warning' : 'success'}
            showIcon
            title={preview.changed > 0 ? '按当前规则，保存后将覆盖' : '按当前规则，名单已与档案一致'}
            description={preview.changed > 0
              ? `${summarize(preview, labelOf)}。保存后会立即执行，之后每轮同步持续生效。`
              : '保存不会改动任何人的名单信息。'}
          />
        )}
      </div>
    )
  }

  return (
    <Drawer
      open
      onClose={guardClose}
      size={640}
      // 窄屏（平板）上不超过视口宽度，否则抽屉会横向溢出
      styles={{ wrapper: { maxWidth: '100vw' } }}
      title={
        <span className="inline-flex items-center gap-2">
          跟随设置
          <Tag>名单随员工档案</Tag>
        </span>
      }
      footer={
        <div className="flex items-center justify-between">
          <Button onClick={guardClose}>关闭</Button>
          <Space>
            <Button
              icon={<SearchOutlined />} loading={previewing} disabled={!config || saving}
              onClick={() => { void runPreview() }}
            >
              预览影响
            </Button>
            <Tooltip title={dirty ? undefined : '没有未保存的改动'}>
              <Button
                type="primary" icon={<SaveOutlined />} loading={saving}
                disabled={!config || !dirty || previewing}
                onClick={() => { void handleSave() }}
              >
                保存并应用
              </Button>
            </Tooltip>
          </Space>
        </div>
      }
    >
      {renderBody()}
    </Drawer>
  )
}
