'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Card, Empty, Select, Space, Input, DatePicker, Switch, Tag, Typography } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { DepartmentTrainingPosition, Employee, TrainingCandidate } from '@/types/hr'
import { downloadBase64File } from '@/lib/hr'
import {
  fetchTrainingCandidates,
  fetchOnboardingFilterOptionsAction,
  fetchTrainingPositionsByDepartment,
  fetchTrainers,
  downloadPrejobTrainingPlan,
  downloadEmployeeTrainingRecord,
  downloadWorkPermit,
  checkExistingTrainingLedgers,
  createTrainingLedger,
} from '@/actions/hr'

const CELL = { border: '1px solid #999', padding: '6px 10px', fontSize: '13px' } as const
const LABEL = { ...CELL, background: '#f5f5f5', fontWeight: 600, textAlign: 'center' as const, width: '15%' }
const VALUE = { ...CELL }

// 本人岗位名常与 SOP 目录里的培训岗位不同（如「万古纯化」对「工艺员」）。
// 完全一致时自动选中；否则只有唯一一个「互相包含」的候选才自动选中，多个候选交给人判断
const matchTrainingPosition = (positions: DepartmentTrainingPosition[], employeePosition: string) => {
  const exact = positions.find((p) => p.position_name === employeePosition)
  if (exact) return exact
  if (!employeePosition) return undefined
  const fuzzy = positions.filter(
    (p) => p.position_name.includes(employeePosition) || employeePosition.includes(p.position_name),
  )
  return fuzzy.length === 1 ? fuzzy[0] : undefined
}

export default function OnboardingPrejobClient() {
  const { message, modal } = App.useApp()
  const [employees, setEmployees] = useState<TrainingCandidate[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null)
  // 已选员工单独保存：再次搜索会整体替换 employees，不能只靠 employees.find 取当前员工
  const [selectedEmployee, setSelectedEmployee] = useState<TrainingCandidate | null>(null)
  // 与入职台账页同口径：默认只列当年的在职员工（入职年份或最近职位变动年份命中）；
  // 已完成入职培训的默认隐藏。转岗/晋升者由后端自动重置回待培训名单
  const [hireYear, setHireYear] = useState<number | undefined>(new Date().getFullYear())
  const [showCompleted, setShowCompleted] = useState(false)
  const [hireYears, setHireYears] = useState<number[]>([])
  const [downloadingWord, setDownloadingWord] = useState(false)
  const [downloadingRecord, setDownloadingRecord] = useState(false)
  const [downloadingPermit, setDownloadingPermit] = useState(false)
  const [selectedSops, setSelectedSops] = useState<any[]>([])
  // 培训岗位：按员工部门从 SOP 目录带出供选择（匹配规则见 matchTrainingPosition）
  const [trainingPositions, setTrainingPositions] = useState<DepartmentTrainingPosition[]>([])
  const [trainingPosition, setTrainingPosition] = useState<string | undefined>(undefined)
  const [positionsLoading, setPositionsLoading] = useState(false)
  const [trainers, setTrainers] = useState<{value:string,label:string}[]>([])

  // 请求序号守卫：慢响应回来时若已有更新的查询，丢弃旧结果
  const loadSeq = useRef(0)
  const keywordRef = useRef<string | undefined>(undefined)
  // 已选员工的同步镜像：刷新名单时要把它保留在选项里，但不能因此触发重新查询
  const selectedRef = useRef<TrainingCandidate | null>(null)

  // 转岗/晋升员工按最近一次异动的目标部门/岗位取培训口径（transfers 降序，[0] 最近一次）。
  // 异动记录不回写员工档案，档案同步跟进前以异动目标为准
  const latestTransfer = selectedEmployee?.transfers[0] ?? null
  const effectiveDepartment = latestTransfer?.to_department || selectedEmployee?.department || ''
  const effectivePosition = latestTransfer?.to_position || selectedEmployee?.position || ''

  const loadEmployees = useCallback(async (keyword?: string) => {
    keywordRef.current = keyword
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      const d = await fetchTrainingCandidates({ keyword, year: hireYear, includeCompleted: showCompleted })
      if (seq !== loadSeq.current) return
      const list = d.data || []
      // 已选员工不在新名单里（写入台账后被隐藏、或搜索词不匹配）时保留其选项，否则下拉框只能显示原始 id
      const sel = selectedRef.current
      setEmployees(sel && !list.some((e) => e.id === sel.id) ? [sel, ...list] : list)
    } catch (err) {
      if (seq === loadSeq.current) {
        message.error('加载失败: ' + (err instanceof Error ? err.message : '未知错误'))
      }
    } finally { if (seq === loadSeq.current) setLoading(false) }
  }, [hireYear, showCompleted, message])

  // 首次加载及年份/开关变化时重新查询，沿用当前搜索词
  useEffect(() => { loadEmployees(keywordRef.current) }, [loadEmployees])

  const handleSearch = async (keyword: string) => {
    loadEmployees(keyword.trim() || undefined)
  }

  // 把某个培训岗位的培训大类装进计划表：每个大类一行
  const applyTrainingPosition = (position: DepartmentTrainingPosition, department: string) => {
    setTrainingPosition(position.position_name)
    setSelectedSops(position.categories.map((c) => ({
      id: c.training_category,
      sop_number: '',
      file_name: c.training_category,
      department,
      category: c.training_category,
      trainer: c.trainer,
      training_method: c.training_method,
    })))
  }

  // 选中员工后，按其（异动后）部门取培训岗位；岗位能对上则自动选中并加载培训内容
  useEffect(() => {
    if (!selectedEmployee) return
    const dept = effectiveDepartment
    const pos = effectivePosition

    // 员工再次切换后丢弃上一次请求的响应，避免把上一名员工的培训内容填进来
    // （加载态在 handleSelectEmployee 里进入，effect 只负责回填结果）
    let outdated = false
    fetchTrainingPositionsByDepartment(dept)
      .then(res => {
        if (outdated) return
        const positions = res.data || []
        setTrainingPositions(positions)
        const matched = matchTrainingPosition(positions, pos)
        if (!matched) {
          // 对不上时留空让人选，表格里有提示
          setTrainingPosition(undefined)
          setSelectedSops([])
          return
        }
        applyTrainingPosition(matched, dept)
        message.success(`已按培训岗位「${matched.position_name}」加载 ${matched.categories.length} 个培训大类`)
      })
      .catch((err) => {
        if (outdated) return
        message.error('加载培训岗位失败: ' + (err instanceof Error ? err.message : '未知错误'))
      })
      .finally(() => { if (!outdated) setPositionsLoading(false) })
    return () => { outdated = true }
  }, [selectedEmployeeId])

  // 加载培训师列表
  useEffect(() => {
    fetchTrainers({ page_size: 200 })
      .then(res => setTrainers((res.data||[]).map((t:any) => ({value:t.name,label:`${t.name}(${t.department})`}))))
      .catch(() => {})
  }, [])

  // 入职年份候选项（与入职台账页同源聚合）
  useEffect(() => {
    fetchOnboardingFilterOptionsAction().then(res => setHireYears(res.years || [])).catch(() => {})
  }, [])

  const [sopMethods, setSopMethods] = useState<Record<string, string>>({})
  const [sopTrainers, setSopTrainers] = useState<Record<string, string>>({})
  const [sopPlanDates, setSopPlanDates] = useState<Record<string, string>>({})

  // 切换员工：清空上一名员工残留的培训方式/培训师/完成期限及培训明细
  const handleSelectEmployee = (id: string) => {
    const emp = employees.find((e) => e.id === id) || null
    setSelectedEmployeeId(emp ? id : null)
    setSelectedEmployee(emp)
    selectedRef.current = emp
    setSelectedSops([])
    setTrainingPositions([])
    setTrainingPosition(undefined)
    // 选中即进入「加载培训岗位」状态，结果由下面的 effect 回填
    setPositionsLoading(!!emp)
    setSopMethods({})
    setSopTrainers({})
    setSopPlanDates({})
  }

  // 切换培训岗位：培训内容整体换成该岗位的大类，上一岗位填过的培训方式/培训师/完成期限一并清空
  const handleTrainingPositionChange = (name: string) => {
    const position = trainingPositions.find((p) => p.position_name === name)
    if (!position || !selectedEmployee) return
    applyTrainingPosition(position, effectiveDepartment)
    setSopMethods({})
    setSopTrainers({})
    setSopPlanDates({})
  }

  const updateSopMethod = (sopId: string, method: string) => {
    setSopMethods(prev => ({ ...prev, [sopId]: method }))
  }

  const toggleSop = (sop: any) => {
    setSelectedSops(prev => {
      const exists = prev.find(s => s.id === sop.id)
      if (exists) return prev.filter(s => s.id !== sop.id)
      return [...prev, sop]
    })
  }

  const buildItems = () => selectedSops.map(s => ({
    sop_number: s.sop_number || '',
    file_name: s.file_name || '',
    content: s.file_name || '',
    method: sopMethods[s.id] || '',
    trainer: sopTrainers[s.id] || '',
    plan_date: sopPlanDates[s.id] || '',
  }))

  const handleExportPlan = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingWord(true)
    try {
      const r = await downloadPrejobTrainingPlan(
        selectedEmployee.employee_id || selectedEmployee.id,
        selectedEmployee.name || 'employee',
        buildItems(),
        trainingPosition,
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingWord(false) }
  }

  const handleExportRecord = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingRecord(true)
    try {
      const items = buildItems()
      const r = await downloadEmployeeTrainingRecord(
        selectedEmployee.employee_number,
        selectedEmployee.name,
        items,
        trainingPosition,
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
      // 与培训台账联动：导出的培训记录顺势写入台账（此前纯下载零联动）
      const ledgerItems = items.filter((it) => it.plan_date && it.content)
      const skipped = items.length - ledgerItems.length
      if (ledgerItems.length === 0) {
        if (items.length > 0) {
          message.info('培训内容均未填「完成期限」，无法写入培训台账（台账需培训日期）')
        }
        return
      }
      // 写入前查重：同日期同主题已有记录的条目不再创建（创建接口本身不查重，重复导出会产生重复记录）
      const dupKeys = new Set<string>()
      const groups = Array.from(new Set(ledgerItems.map((it) => `${it.plan_date}\u0000${it.content}`)))
      try {
        const checks = await Promise.all(groups.map(async (g) => {
          const [training_date, training_subject] = g.split('\u0000')
          const r = await checkExistingTrainingLedgers({
            training_date, training_subject, employee_numbers: [selectedEmployee.employee_number],
          })
          return r.data?.employee_numbers?.length ? g : null
        }))
        checks.filter((g): g is string => !!g).forEach((g) => dupKeys.add(g))
      } catch {
        // 查重失败不阻断流程（按「无重复」继续）
      }
      const freshItems = ledgerItems.filter((it) => !dupKeys.has(`${it.plan_date}\u0000${it.content}`))
      if (freshItems.length === 0) {
        message.info('这些培训记录当天已在培训台账中，无需重复写入')
        return
      }
      const dupCount = ledgerItems.length - freshItems.length

      modal.confirm({
        title: '写入培训台账',
        content: `是否将本次导出的 ${freshItems.length} 条培训记录写入培训台账？${
          skipped > 0 ? `（${skipped} 条缺完成期限将跳过）` : ''
        }${dupCount > 0 ? `（${dupCount} 条当天已有同主题记录，将跳过）` : ''}`,
        okText: '写入台账',
        cancelText: '仅导出',
        onOk: async () => {
          let ok = 0
          for (const it of freshItems) {
            try {
              await createTrainingLedger({
                employee_number: selectedEmployee.employee_number,
                training_date: it.plan_date,
                training_subject: it.content,
                training_method: it.method || undefined,
                trainer: it.trainer || undefined,
                source_type: 'prejob_export',
                remarks: '入职培训记录表导出写入',
              })
              ok += 1
            } catch { /* 逐条容错，失败汇总 */ }
          }
          if (ok === freshItems.length) {
            message.success(`已写入培训台账 ${ok} 条；该员工已完成入职培训，默认不再出现在待培训名单`)
          } else {
            message.warning(`写入台账 ${ok}/${freshItems.length} 条，失败的条目请到台账页手动补录`)
          }
          // 写入即视为完成入职培训：刷新名单使其默认隐藏（已选员工仍保留在选项里，可继续导出）
          if (ok > 0) loadEmployees(keywordRef.current)
        },
      })
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingRecord(false) }
  }

  const handleExportPermit = async () => {
    if (!selectedEmployee) return message.warning('请先选择员工')
    setDownloadingPermit(true)
    try {
      const r = await downloadWorkPermit(
        selectedEmployee.employee_number,
        selectedEmployee.name,
        buildItems(),
      )
      downloadBase64File(r.base64, r.filename)
      message.success('导出成功')
    } catch (err) { message.error((err as Error)?.message || '导出失败') }
    finally { setDownloadingPermit(false) }
  }

  return (
    <div className="space-y-4">
      <Card>
        <Space wrap size="middle">
          <Select
            showSearch
            placeholder="输入工号或姓名搜索员工"
            value={selectedEmployeeId || undefined}
            onChange={handleSelectEmployee}
            options={employees.map((e) => ({
              value: e.id,
              label: (
                <span className="flex items-center gap-1.5">
                  {/* 文字可截断，标签固定在右侧，不会被行尾省略号吞掉 */}
                  <span className="min-w-0 flex-1 truncate">
                    {`${e.employee_number} - ${e.name} (${e.department}) [${e.source || '新入职'}]`}
                  </span>
                  {/* 转岗/晋升等职位变动后需重新培训：异动员工在待培训名单里带标记 */}
                  {!e.prejob_completed && e.transfers.length > 0 && (
                    <Tag color="orange" style={{ marginInlineEnd: 0 }}>{e.transfers[0].transfer_type}重训</Tag>
                  )}
                  {e.prejob_completed && <Tag color="green" style={{ marginInlineEnd: 0 }}>已完成</Tag>}
                </span>
              ),
            }))}
            onSearch={handleSearch}
            loading={loading}
            filterOption={false}
            // 固定宽度：只设最小宽度时会随选中项文字长度变宽，工具栏跟着跳行
            style={{ width: 320 }}
          />
          <Select
            placeholder="年份"
            allowClear
            value={hireYear}
            onChange={setHireYear}
            // 年份语义：入职年份或最近职位变动年份（异动重训的老员工按异动年份命中）
            options={Array.from(new Set([new Date().getFullYear(), ...hireYears]))
              .sort((a, b) => b - a)
              .map((y) => ({ value: y, label: `${y} 年` }))}
            style={{ width: 130 }}
          />
          <label className="flex items-center gap-1.5 whitespace-nowrap text-sm">
            <Switch size="small" checked={showCompleted} onChange={setShowCompleted} />
            显示已完成培训
          </label>
          <Button type="primary" icon={<DownloadOutlined />} onClick={handleExportPlan} loading={downloadingWord} disabled={!selectedEmployee}>导出岗前培训计划</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportRecord} loading={downloadingRecord} disabled={!selectedEmployee}>导出培训记录</Button>
          <Button icon={<DownloadOutlined />} onClick={handleExportPermit} loading={downloadingPermit} disabled={!selectedEmployee}>导出上岗证</Button>
        </Space>
      </Card>

      {/* 选中员工有职位变动时提示需重新培训（transfers 按生效日期降序，[0] 为最近一次；打印时隐藏） */}
      {selectedEmployee && selectedEmployee.transfers.length > 0 && (
        <Alert
          className="no-print"
          type="warning"
          showIcon
          message={`该员工于 ${selectedEmployee.transfers[0].effective_date || '—'} 由 ${selectedEmployee.transfers[0].from_department || '—'} / ${selectedEmployee.transfers[0].from_position || '—'} ${selectedEmployee.transfers[0].transfer_type}至 ${selectedEmployee.transfers[0].to_department || '—'} / ${selectedEmployee.transfers[0].to_position || '—'}，按新岗位需重新参加入职培训。`}
        />
      )}

      {/* 未选员工时的空状态（打印时隐藏） */}
      {!selectedEmployee && (
        <Card className="no-print">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请先选择员工" />
        </Card>
      )}

      {selectedEmployee && (
        <div id="print-area" className="space-y-6">
          {/* ===== Part I: 员工概况 (匹配模板) ===== */}
          <Card className="no-print-padding">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: '16%' }} /><col style={{ width: '17%' }} />
                <col style={{ width: '16%' }} /><col style={{ width: '17%' }} />
                <col style={{ width: '16%' }} /><col style={{ width: '18%' }} />
              </colgroup>
              <tbody>
                <tr>
                  <td colSpan={6} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第一部分：员工概况 Part I: Description of the employee
                  </td>
                </tr>
                <tr>
                  <td style={LABEL}>姓名<br/>Name</td><td style={VALUE}>{selectedEmployee.name}</td>
                  <td style={LABEL}>学历<br/>Education</td><td style={VALUE}>{selectedEmployee.education || ''}</td>
                  <td style={LABEL}>类别<br/>Type</td><td style={VALUE}>{latestTransfer ? latestTransfer.transfer_type : (selectedEmployee.source || '新入职')}</td>
                </tr>
                <tr>
                  <td style={LABEL}>毕业院校<br/>Graduation school</td><td style={VALUE}>{selectedEmployee.school || ''}</td>
                  <td style={LABEL}></td><td style={VALUE}></td>
                  <td style={LABEL}>毕业时间<br/>Graduation time</td><td style={VALUE}>{selectedEmployee.graduation_date || ''}</td>
                </tr>
                <tr>
                  <td style={LABEL}>部门<br/>Dept.</td><td style={VALUE}>{effectiveDepartment}</td>
                  {/* 与导出文件一致：选了培训岗位写培训岗位，否则写实际岗位 */}
                  <td style={LABEL}>拟定岗位<br/>Intended post</td><td style={VALUE}>{trainingPosition || effectivePosition}</td>
                  <td style={LABEL}>职称<br/>Title</td><td style={VALUE}></td>
                </tr>
                <tr>
                  <td style={LABEL}>报到日期<br/>Entry date</td><td style={VALUE}>{selectedEmployee.hire_date || ''}</td>
                  <td style={LABEL}>预定培训期<br/>Training period</td><td style={{...VALUE}} colSpan={3}></td>
                </tr>
              </tbody>
            </table>
          </Card>

          {/* ===== Part II & IV: 培训计划 + 完成确认 (匹配模板) ===== */}
          <Card className="no-print-padding">
            {/* 培训岗位：员工实际岗位名常与 SOP 目录里的培训岗位不同，按部门选择 */}
            <div className="no-print mb-3 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">培训岗位</span>
              <Select
                showSearch
                placeholder={trainingPositions.length ? '请选择培训岗位' : '该部门暂无培训岗位'}
                value={trainingPosition}
                onChange={handleTrainingPositionChange}
                loading={positionsLoading}
                disabled={!trainingPositions.length}
                options={trainingPositions.map((p) => ({ value: p.position_name, label: p.position_name }))}
                optionFilterProp="label"
                style={{ width: 200 }}
              />
              <Typography.Text type="secondary">
                {latestTransfer
                  ? `按异动后岗位培训：${effectivePosition || '-'}（${effectiveDepartment}）`
                  : `本人岗位：${selectedEmployee.position || '-'}（${selectedEmployee.department}）`}
              </Typography.Text>
              {trainingPositions.length > 0 && !trainingPosition && (
                <Typography.Text type="warning">本人岗位未匹配到培训内容，请选择培训岗位</Typography.Text>
              )}
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <colgroup>
                <col style={{ width: '4%' }} /><col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
                <col style={{ width: '8%' }} /><col style={{ width: '8%' }} /><col style={{ width: '8%' }} />
                <col style={{ width: '10%' }} /><col style={{ width: '10%' }} /><col style={{ width: '10%' }} />
              </colgroup>
              <tbody>
                {/* 标题行 */}
                <tr>
                  <td colSpan={10} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第二部分：培训计划/内容 Part II: Training plans/content
                  </td>
                  <td colSpan={3} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第四部分：培训完成情况确认 Part IV: Training completion
                  </td>
                </tr>
                {/* 表头 */}
                <tr style={{ background: '#f5f5f5' }}>
                  <td style={CELL}></td>
                  <td style={CELL} colSpan={4}>培训内容 Training items</td>
                  <td style={CELL} colSpan={2}>计划完成期限 Plan date</td>
                  <td style={CELL} colSpan={2}>培训师 Trainer</td>
                  <td style={CELL}>培训方式 Method</td>
                  <td style={CELL}>培训日期 Date</td>
                  <td style={CELL}>员工/日期</td>
                  <td style={CELL}>培训师/日期</td>
                </tr>
                {/* 培训明细行 */}
                {selectedSops.length > 0 ? selectedSops.map((item, i) => (
                  <tr key={i}>
                    <td style={{...CELL, textAlign: 'center'}}>{i + 1}</td>
                    <td style={CELL} colSpan={4}>{item.sop_number ? `${item.sop_number} ` : ''}{item.file_name || ''}</td>
                    <td style={CELL} colSpan={2}>
                      <DatePicker size="small" style={{ width: '100%' }} placeholder="完成期限"
                        value={sopPlanDates[item.id] ? dayjs(sopPlanDates[item.id]) : null}
                        onChange={(d) => setSopPlanDates(prev => ({...prev, [item.id]: d ? d.format('YYYY-MM-DD') : ''}))} />
                    </td>
                    <td style={CELL} colSpan={2}>
                      <Select size="small" value={sopTrainers[item.id] || undefined}
                        onChange={v => setSopTrainers(prev => ({...prev, [item.id]: v}))}
                        options={trainers} placeholder="选培训师" style={{ width: '100%' }}
                        showSearch filterOption={(input, option) => (option?.label||'').toLowerCase().includes(input.toLowerCase())} />
                    </td>
                    <td style={CELL}>
                      <Select size="small" value={sopMethods[item.id] || undefined}
                        onChange={v => updateSopMethod(item.id, v)}
                        options={[{value:'面授',label:'面授'},{value:'自学',label:'自学'},{value:'自学+面授',label:'自学+面授'}]}
                        placeholder="选择" style={{ width: '100%' }} />
                    </td>
                    <td style={CELL}></td><td style={CELL}></td><td style={CELL}></td>
                  </tr>
                )) : (
                  <tr><td style={CELL} colSpan={13}>
                    {positionsLoading
                      ? '正在加载培训岗位…'
                      : trainingPositions.length
                        ? '请选择培训岗位，加载对应的培训内容'
                        : `「${effectiveDepartment}」暂无培训岗位，请先在 SOP 目录中配置该部门的适用岗位`}
                  </td></tr>
                )}
                {/* Part III: 审核批准 */}
                <tr>
                  <td colSpan={10} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    第三部分：培训计划审核批准 Part III: Training plans review and approval
                  </td>
                  <td colSpan={3} style={{...CELL, textAlign: 'center', fontWeight: 700, background: '#e8e8e8'}}>
                    备注 Remarks
                  </td>
                </tr>
                <tr>
                  <td style={LABEL} colSpan={3}>部门/日期<br/>Dept./Date</td>
                  <td style={VALUE} colSpan={2}></td>
                  <td style={LABEL} colSpan={2}>HR/日期<br/>HR/Date</td>
                  <td style={VALUE} colSpan={3}></td>
                  <td style={LABEL}>QA/日期<br/>QA/Date</td>
                  <td style={VALUE} colSpan={2}></td>
                  <td style={VALUE} colSpan={3}></td>
                </tr>
              </tbody>
            </table>
          </Card>
        </div>
      )}
      <style>{`
        @media print {
          .no-print { display: none !important; }
          .no-print-padding .ant-card-body { padding: 0 !important; }
        }
      `}</style>
    </div>
  )
}
