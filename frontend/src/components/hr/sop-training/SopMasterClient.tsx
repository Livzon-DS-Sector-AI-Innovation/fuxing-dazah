'use client'

// SOP 培训总表（每年一张，菜单名「SOP培训登记表」）：登记要培训的 SOP 文件 →「转培训」把任务派发给
// 各涉及部门的二级表 → 各部门在二级表里生成培训材料。这页的主线是派发：进度列汇总各部门的生成进度，可直达二级表。
// 纸质登记表的 10 列在屏幕上收成 7 列两行单元格，1366 宽度下不横向滚动；
// 变更类型 / 进度 / 关键词筛选和计数都在前端算（单年数据量小，切筛选不再请求）。

import { useEffect, useMemo, useReducer, useState } from 'react'
import type { ReactNode } from 'react'
import Link from 'next/link'
import { App, Button, Dropdown, Empty, Input, Segmented, Select, Space, Table, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import {
  deleteSopTrainingRecord,
  downloadSopMasterMaterials,
  exportSopTrainingRecords,
  fetchQuestionBankCounts,
  fetchSopRecordYears,
  fetchSopTrainingAdmins,
  fetchSopTrainingEntries,
  fetchSopTrainingRecords,
  previewSopMasterMaterials,
  submitSopTrainingRecord,
} from '@/actions/hr'
import { downloadBase64File, SOP_CHANGE_TYPE_META } from '@/lib/hr'
import { useHasPermission } from '@/hooks/hr'
import type { SopEvaluationStats, SopMaterialsPreview, SopTrainingRecord } from '@/types/hr'
import PageHeader from '@/components/hr/PageHeader'
import SopRecordFormModal from './SopRecordFormModal'
import SopQaGenerateModal from './SopQaGenerateModal'
import SopMaterialsModal, { randomStats } from './SopMaterialsModal'
import {
  ChangeTypeFilter,
  DepartmentCell,
  FileCell,
  MethodTimeCell,
  SoftTag,
  changeTagMeta,
  formatCnDate,
  recordStatusTagMeta,
} from './cells'
import styles from './sop-training.module.css'

type ProgressFilter = 'all' | 'pending' | 'done'

/** 一条登记在各部门二级表的生成进度（只统计当前账号数据范围内看得到的记录） */
interface DispatchProgress {
  total: number
  done: number
}

const PAGE_SIZE = 20
const CHANGE_TYPES = Object.keys(SOP_CHANGE_TYPE_META)

// 行首色条：与变更标签同色（取色见 SOP_CHANGE_TYPE_META）
const ROW_CLASS: Record<string, string> = {
  新增: styles.rowAdd,
  修改: styles.rowModify,
  撤销: styles.rowRevoke,
}

function withCount(text: string, count: number): ReactNode {
  return (
    <span>
      {text}
      <span className={styles.segCount}>{count}</span>
    </span>
  )
}

/** 登记的全部文件：合并登记看 files，单文件回落 file_name/file_no 两列 */
function recordFiles(r: SopTrainingRecord): { file_name: string; file_no: string | null }[] {
  return r.files?.length ? r.files : [{ file_name: r.file_name, file_no: r.file_no }]
}

/** 考核方式没登记时按培训方式取默认（与后端 _effective_assessment 同口径） */
function effectiveAssessment(r: SopTrainingRecord): string {
  return r.assessment_method || (r.method === 'T' ? '问答' : r.method === 'R' ? '阅读并理解' : '')
}

export default function SopMasterClient() {
  const { message, modal } = App.useApp()
  const canManage = useHasPermission('hr:training:manage')
  const canGenerateDoc = useHasPermission('hr:training:document')
  const canUseAiExam = useHasPermission('hr:training:exam')

  const [years, setYears] = useState<string[]>([])
  const [year, setYear] = useState(() => String(new Date().getFullYear()))
  const [records, setRecords] = useState<SopTrainingRecord[]>([])
  const [dispatchProgress, setDispatchProgress] = useState<Record<string, DispatchProgress>>({})
  // 题库按 SOP 编号计数：问答/笔试的材料按编号带题，列表上先让人看见「哪些还没题」
  const [qaCounts, setQaCounts] = useState<Record<string, number>>({})
  const [qaCountsTick, bumpQaCounts] = useReducer((n: number) => n + 1, 0)
  const [qaOpen, setQaOpen] = useState(false)
  const [qaTarget, setQaTarget] = useState<SopTrainingRecord | null>(null)
  // 每次打开弹窗换 key：AI 出题弹窗整体重新挂载，上传/生成状态不用靠 effect 复位
  const [qaSeq, setQaSeq] = useState(0)
  const [loading, setLoading] = useState(true)
  const [progress, setProgress] = useState<ProgressFilter>('all')
  const [changeFilter, setChangeFilter] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)
  const [submittingId, setSubmittingId] = useState<string | null>(null)
  const [generatingId, setGeneratingId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<SopTrainingRecord | null>(null)
  // 每次打开弹窗换 key：表单弹窗整体重新挂载，初值/脏标记不用靠 effect 重置
  const [formSeq, setFormSeq] = useState(0)
  const [reloadSeq, bumpReload] = useReducer((n: number) => n + 1, 0)
  // 生成材料弹窗：先拉统计基数（应到/病产假）再让用户填或随机生成合格统计
  const [materialsTarget, setMaterialsTarget] = useState<SopTrainingRecord | null>(null)
  const [materialsBase, setMaterialsBase] = useState<SopMaterialsPreview | null>(null)
  const [materialsInit, setMaterialsInit] = useState<SopEvaluationStats | null>(null)
  // 每次打开弹窗换 key：统计弹窗整体重新挂载，初值不用靠 effect 复位
  const [materialsSeq, setMaterialsSeq] = useState(0)

  // 只按年份取数；其余筛选在前端做
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchSopTrainingRecords({ year })
        if (!cancelled) setRecords(r.data || [])
      } catch (e) {
        if (!cancelled) message.error(e instanceof Error ? e.message : '加载登记表失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
    // message 刻意不进依赖：App.useApp() 的实例进 effect 依赖会引发重复触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, reloadSeq])

  // 各部门二级表的生成进度，按登记记录归到总表每一行上（派发之后在这页看各部门做没做）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchSopTrainingEntries({})
        if (cancelled) return
        const map: Record<string, DispatchProgress> = {}
        for (const e of r.data || []) {
          if (!e.record_id) continue
          const p = (map[e.record_id] ??= { total: 0, done: 0 })
          p.total += 1
          if (e.status === '已生成') p.done += 1
        }
        setDispatchProgress(map)
      } catch {
        // 二级表进度拉不到不影响总表本身：进度列退成只显示「已转培训」
      }
    })()
    return () => { cancelled = true }
  }, [reloadSeq])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetchSopRecordYears()
        if (!cancelled) setYears(r.data || [])
      } catch {
        // 年份列表拉不到不影响主表：下拉退成只有当前年
      }
    })()
    return () => { cancelled = true }
  }, [])

  // 题库题数按编号批量拉一次；AI 出题入库后 bumpQaCounts 重拉
  useEffect(() => {
    const nos = [
      ...new Set(
        records
          .flatMap((r) => recordFiles(r).map((f) => (f.file_no ?? '').trim()))
          .filter(Boolean),
      ),
    ]
    let cancelled = false
    ;(async () => {
      const r = nos.length ? await fetchQuestionBankCounts(nos).catch(() => null) : null
      if (cancelled) return
      // 计数拉不到不影响主表，考核题库列退成占位
      setQaCounts(r?.data?.counts ?? {})
    })()
    return () => { cancelled = true }
  }, [records, qaCountsTick])

  const stats = useMemo(() => {
    const byChange: Record<string, number> = {}
    let pending = 0
    for (const r of records) {
      byChange[r.color] = (byChange[r.color] ?? 0) + 1
      if (r.status !== '已提交') pending += 1
    }
    return { total: records.length, pending, done: records.length - pending, byChange }
  }, [records])

  const kw = keyword.trim().toLowerCase()
  const visible = useMemo(
    () =>
      records.filter((r) => {
        if (changeFilter && r.color !== changeFilter) return false
        if (progress === 'pending' && r.status === '已提交') return false
        if (progress === 'done' && r.status !== '已提交') return false
        if (kw && !`${r.file_name}\n${r.file_no ?? ''}`.toLowerCase().includes(kw)) return false
        return true
      }),
    [records, changeFilter, progress, kw],
  )

  const changeCounts = useMemo(
    () => CHANGE_TYPES.map((name) => ({ name, count: stats.byChange[name] ?? 0 })),
    [stats],
  )

  const yearOptions = (years.length ? years : [year]).map((y) => ({ value: y, label: `${y}年` }))

  // 刷新按钮 / 保存 / 删除 / 转培训之后重新取数：进 loading 后让上面的 effect 再跑一次
  const refresh = () => {
    setLoading(true)
    bumpReload()
  }

  const changeYear = (next: string) => {
    setYear(next)
    setPage(1)
    setLoading(true)
  }

  const clearFilters = () => {
    setProgress('all')
    setChangeFilter(null)
    setKeyword('')
    setPage(1)
  }

  const openCreate = () => {
    setEditing(null)
    setFormSeq((s) => s + 1)
    setFormOpen(true)
  }

  const openEdit = (r: SopTrainingRecord) => {
    setEditing(r)
    setFormSeq((s) => s + 1)
    setFormOpen(true)
  }

  const confirmDelete = (r: SopTrainingRecord) => {
    modal.confirm({
      title: `删除「${r.file_name}」的登记？`,
      content:
        r.status === '已提交'
          ? '这条登记已转培训：各部门已生成材料的二级表记录会保留，还没生成的会一并删除。'
          : '删除后不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteSopTrainingRecord(r.id)
          message.success('已删除')
          refresh()
        } catch (e) {
          message.error(e instanceof Error ? e.message : '删除失败')
        }
      },
    })
  }

  const handleSubmit = async (r: SopTrainingRecord) => {
    setSubmittingId(r.id)
    let admins: string[] = []
    try {
      admins = (await fetchSopTrainingAdmins(r.id)).data?.admins || []
    } catch (e) {
      message.error(e instanceof Error ? e.message : '获取培训管理员失败')
      return
    } finally {
      setSubmittingId(null)
    }
    modal.confirm({
      title: `转培训：${r.file_name}`,
      width: 520,
      content: (
        <div className="space-y-3 pt-1">
          <div>
            转培训后，任务派发给以下 <b>{r.involved_departments.length}</b> 个部门的二级表：
            <div className="mt-2 flex flex-wrap gap-1.5">
              {r.involved_departments.map((d) => (
                <span key={d} className={styles.deptChip}>
                  {d}
                </span>
              ))}
            </div>
          </div>
          {admins.length > 0 ? (
            <div className="text-[13px]">
              并通过飞书通知培训管理员：<b>{admins.join('、')}</b>
            </div>
          ) : (
            <div className="text-[13px] text-[var(--color-steel)]">
              这些部门还没配置培训管理员：只派发给二级表，不发送通知。
            </div>
          )}
        </div>
      ),
      okText: '确认转培训',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await submitSopTrainingRecord(r.id)
          const notified: string[] = res.data?.notified_admins || []
          message.success(
            notified.length ? `已转培训，已通知 ${notified.join('、')}` : '已转培训，已派发给各部门二级表',
          )
          refresh()
        } catch (e) {
          message.error(e instanceof Error ? e.message : '转培训失败')
        }
      },
    })
  }

  // 点「下载全套培训材料」先拉统计基数（按钮转圈），到手后带着随机初值开弹窗；基数拉不到也开（可手填/无统计导出）
  const handleMaterials = async (r: SopTrainingRecord) => {
    setGeneratingId(r.id)
    let p: SopMaterialsPreview | null = null
    try {
      p = await previewSopMasterMaterials(r.id)
    } catch {
      // 基数拉不到不阻塞弹窗：统计手动填，或清空后按无统计导出
    }
    setMaterialsBase(p)
    setMaterialsInit(p && p.expected_count > 0 ? randomStats(p) : null)
    setMaterialsTarget(r)
    setMaterialsSeq((s) => s + 1)
    setGeneratingId(null)
  }

  const handleMaterialsExport = async (stats: SopEvaluationStats | null) => {
    if (!materialsTarget) return
    setGeneratingId(materialsTarget.id)
    try {
      const { base64, filename } = await downloadSopMasterMaterials(materialsTarget.id, stats)
      downloadBase64File(base64, filename || 'SOP全套培训材料.zip')
      message.success('全套材料已生成')
      setMaterialsTarget(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGeneratingId(null)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const { base64, filename } = await exportSopTrainingRecords(year)
      downloadBase64File(base64, filename)
      message.success('登记表已导出')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const columns: ColumnsType<SopTrainingRecord> = [
    {
      title: '培训日期',
      dataIndex: 'training_date',
      width: 80,
      render: (v: string | null) =>
        v ? (
          <span className={`${styles.num} whitespace-nowrap`}>{formatCnDate(v)}</span>
        ) : (
          <span className={styles.placeholder}>未填写</span>
        ),
    },
    {
      title: '培训文件',
      key: 'file',
      render: (_, r) => (
        <FileCell
          name={r.file_name}
          title={r.file_name}
          meta={
            <>
              <span className={styles.num}>{r.file_no || '无编号'}</span>
              {r.effective_date && <span> · 生效 {formatCnDate(r.effective_date)}</span>}
            </>
          }
        />
      ),
    },
    {
      title: '变更',
      key: 'change',
      width: 132,
      render: (_, r) => (
        <div className="min-w-0">
          <SoftTag meta={changeTagMeta(r.color)}>{r.color}</SoftTag>
          {r.change_note && (
            <div className={styles.cellSecondary} title={r.change_note}>
              {r.change_note}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '培训完成 / 培训师',
      key: 'complete',
      width: 176,
      render: (_, r) => (
        <MethodTimeCell
          method={r.method}
          completeTime={r.complete_time}
          footnote={
            r.trainer ? (
              <span title={r.trainees ? `培训对象：${r.trainees}` : undefined}>培训师 {r.trainer}</span>
            ) : undefined
          }
        />
      ),
    },
    {
      title: '涉及部门',
      key: 'departments',
      width: 176,
      render: (_, r) => (
        <DepartmentCell departments={r.involved_departments} initiator={r.initiator_department} />
      ),
    },
    {
      title: '进度',
      key: 'progress',
      width: 140,
      render: (_, r) => {
        const meta = recordStatusTagMeta(r.status)
        // 派发之后二级表里才有这条登记的记录
        const dp = r.status === '已提交' ? dispatchProgress[r.id] : undefined
        const seesAll = !!dp && dp.total >= r.involved_departments.length
        return (
          <div className="min-w-0">
            <SoftTag meta={meta}>{meta.label}</SoftTag>
            {dp && dp.total > 0 && (
              <Link
                href={`/hr/training/sop-secondary?record=${r.id}`}
                className={`${styles.progressLink} ${seesAll && dp.done === dp.total ? styles.progressDone : ''}`}
                title="在二级表里查看各部门的记录"
              >
                {seesAll ? `${dp.done}/${dp.total} 部门已生成材料` : `${dp.done} 个部门已生成`}
                <RightOutlined />
              </Link>
            )}
          </div>
        )
      },
    },
    {
      title: '考核题库',
      key: 'qabank',
      width: 96,
      render: (_, r) => {
        const assessment = effectiveAssessment(r)
        // 阅读并理解不消费题库
        if (assessment !== '问答' && assessment !== '笔试') {
          return <span className={styles.placeholder}>—</span>
        }
        const nos = recordFiles(r).map((f) => (f.file_no ?? '').trim()).filter(Boolean)
        const total = nos.reduce((sum, no) => sum + (qaCounts[no] ?? 0), 0)
        return total > 0 ? (
          <span
            className={styles.num}
            title={`题库按编号匹配：${nos.map((no) => `${no} ${qaCounts[no] ?? 0} 题`).join('、')}`}
          >
            {total} 题
          </span>
        ) : (
          <Tooltip
            title={
              nos.length
                ? '题库还没有这些编号的考题，用行上「AI 出题」入库后，生成的材料自动带题'
                : '登记没填 SOP 编号：题库按编号匹配不到，生成材料时留空白行手写'
            }
          >
            <span className={styles.placeholder}>尚无题</span>
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 268,
      fixed: 'right',
      render: (_, r) => {
        const moreItems: MenuProps['items'] = canManage
          ? [
              { key: 'edit', icon: <EditOutlined />, label: '编辑' },
              { type: 'divider' as const },
              { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true },
            ]
          : []
        return (
          <Space size={4}>
            {canManage && r.status !== '已提交' && (
              <Button
                size="small"
                color="primary"
                variant="outlined"
                loading={submittingId === r.id}
                onClick={() => { void handleSubmit(r) }}
              >
                转培训
              </Button>
            )}
            {canUseAiExam && effectiveAssessment(r) === '问答' && (
              <Tooltip title="AI 问答出题：上传培训文档生成题目，勾选后按 SOP 编号沉淀题库">
                <Button
                  type="text"
                  size="small"
                  onClick={() => {
                    setQaTarget(r)
                    setQaSeq((s) => s + 1)
                    setQaOpen(true)
                  }}
                >
                  AI出题
                </Button>
              </Tooltip>
            )}
            {canGenerateDoc && (
              <Button
                type="text"
                size="small"
                loading={generatingId === r.id}
                onClick={() => { void handleMaterials(r) }}
              >
                生成材料
              </Button>
            )}
            {moreItems.length > 0 && (
              <Dropdown
                trigger={['click']}
                menu={{
                  items: moreItems,
                  onClick: ({ key }) => {
                    if (key === 'edit') openEdit(r)
                    else if (key === 'delete') confirmDelete(r)
                  },
                }}
              >
                <Button type="text" size="small">更多</Button>
              </Dropdown>
            )}
          </Space>
        )
      },
    },
  ]

  const emptyText =
    records.length === 0 ? `${year} 年还没有培训文件登记` : '没有符合当前筛选条件的登记'

  return (
    <div className="space-y-4">
      <PageHeader
      title="SOP培训登记表"
      description="登记需要培训的 SOP 文件；「转培训」即派发给涉及部门的二级表，各部门的生成进度在这里汇总"
        actions={
          <Space>
            <Tooltip title={`导出 ${year} 年全部登记（Excel，不受筛选影响）`}>
              <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => { void handleExport() }}>
                导出登记表
              </Button>
            </Tooltip>
            {canManage && (
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                新增登记
              </Button>
            )}
          </Space>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="登记年份"
          value={year}
          onChange={changeYear}
          options={yearOptions}
          style={{ width: 104 }}
        />
        <Segmented
          value={progress}
          onChange={(v) => {
            setProgress(v as ProgressFilter)
            setPage(1)
          }}
          options={[
            { value: 'all', label: withCount('全部', stats.total) },
            { value: 'pending', label: withCount('待转培训', stats.pending) },
            { value: 'done', label: withCount('已转培训', stats.done) },
          ]}
        />
        <div className="ml-1 flex items-center border-l border-[var(--color-hairline)] pl-3">
          <ChangeTypeFilter
            counts={changeCounts}
            value={changeFilter}
            onChange={(next) => {
              setChangeFilter(next)
              setPage(1)
            }}
          />
        </div>
        <Input
          className="ml-auto"
          style={{ width: 240 }}
          allowClear
          prefix={<SearchOutlined className="text-[var(--color-stone)]" />}
          placeholder="搜索文件名称 / 编号"
          value={keyword}
          onChange={(e) => {
            setKeyword(e.target.value)
            setPage(1)
          }}
        />
        <Tooltip title="刷新">
          <Button aria-label="刷新" icon={<ReloadOutlined />} onClick={refresh} />
        </Tooltip>
      </div>

      <Table<SopTrainingRecord>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={visible}
        scroll={{ x: 1260 }}
        rowClassName={(r) => ROW_CLASS[r.color] ?? ''}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total: visible.length,
          showSizeChanger: false,
          showTotal: (t) => `共 ${t} 条登记`,
          onChange: setPage,
        }}
        locale={{
          emptyText: (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText}>
              {records.length === 0 ? (
                canManage && (
                  <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                    新增登记
                  </Button>
                )
              ) : (
                <Button type="link" style={{ padding: 0 }} onClick={clearFilters}>
                  清空筛选条件
                </Button>
              )}
            </Empty>
          ),
        }}
      />

      <SopRecordFormModal
        key={formSeq}
        open={formOpen}
        editing={editing}
        year={year}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setFormOpen(false)
          refresh()
        }}
      />

      <SopQaGenerateModal
        key={qaSeq}
        open={qaOpen}
        files={qaTarget ? recordFiles(qaTarget) : []}
        onClose={() => setQaOpen(false)}
        onSynced={() => bumpQaCounts()}
      />

      <SopMaterialsModal
        key={materialsSeq}
        open={materialsTarget !== null}
        base={materialsBase}
        initialStats={materialsInit}
        onClose={() => setMaterialsTarget(null)}
        onExport={(stats) => { void handleMaterialsExport(stats) }}
        loading={generatingId !== null}
      />
    </div>
  )
}
