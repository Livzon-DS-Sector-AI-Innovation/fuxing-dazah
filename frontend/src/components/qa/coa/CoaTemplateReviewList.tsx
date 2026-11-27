'use client'

import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert,
  App,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Segmented,
  Select,
  Switch,
  Tag,
  Tooltip,
} from 'antd'
import {
  AimOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import type {
  CoaTemplateBindingView,
  CoaTemplateField,
  CoaTemplateFmt,
  CoaTemplateResidue,
  CoaTemplateSlot,
} from '@/types/qa'
import {
  BUILTIN_VERDICTS,
  DATE_PATTERN_OPTIONS,
  describeFmt,
  describeSlot,
  fieldKindLabel,
  fmtForKind,
  JOINER_OPTIONS,
  mergeVerdicts,
  needsConfirm,
  offeredKinds,
  type ReviewFilter,
  type VerdictSource,
  visibleFields,
} from './coaTemplateBindingModel'
import styles from './CoaTemplateBindingDrawer.module.css'

export interface CoaTemplateReviewListProps {
  view: CoaTemplateBindingView
  /** 上传/标注/保存进行中：清单只读 */
  disabled: boolean
  filter: ReviewFilter
  onFilterChange: (filter: ReviewFilter) => void
  onFocusField: (field: string | null) => void
  pickingField: string | null
  onStartPick: (field: string) => void
  onCancelPick: () => void
  onChangeField: (field: string, patch: Partial<CoaTemplateField>) => void
  onChangeSlot: (field: string, sid: string, patch: Partial<CoaTemplateSlot>) => void
  onRemoveSlot: (field: string, sid: string) => void
  onUnbind: (field: string) => void
  onDismissFlags: (field: string) => void
  onMarkStatic: (sid: string) => void
  onBindResidue: (sid: string, field: string) => void
  onChangeVerdicts: (verdicts: Record<string, string>) => void
  /** 让左侧预览滚到这个数据位（点清单上的位置时） */
  onLocate: (sid: string) => void
}

const KIND_LABEL: Record<CoaTemplateFmt['kind'], string> = {
  number: '数值',
  date: '日期',
  text: '文字',
}

/** 字段名后面的补充信息：英文名、单位（标准原文在下一行的「所在行」里能看到）。 */
function fieldMeta(field: CoaTemplateField): string {
  if (field.kind === 'batch') {
    return [field.label_en, field.type === 'date' ? '日期' : null].filter(Boolean).join(' · ')
  }
  return [field.label_en, field.unit ? `单位 ${field.unit}` : null].filter(Boolean).join(' · ')
}

function omitKey(record: Record<string, string>, key: string): Record<string, string> {
  return Object.fromEntries(Object.entries(record).filter(([k]) => k !== key))
}

const fieldOptionLabel = (field: CoaTemplateField) =>
  field.kind === 'item' ? field.label_cn : `批次信息 · ${field.label_cn}`

/** 数据位的格式规则：数值（位数 + 单位后缀）/ 日期（写法）/ 文字（补英文）。 */
function FmtEditor({
  field,
  fmt,
  defaults,
  disabled,
  onChange,
}: {
  field: CoaTemplateField
  fmt: CoaTemplateFmt
  defaults: CoaTemplateBindingView['defaults']
  disabled: boolean
  onChange: (fmt: CoaTemplateFmt) => void
}) {
  const kinds = offeredKinds(field, fmt)
  const patternOptions = DATE_PATTERN_OPTIONS.some((option) => option.value === fmt.pattern)
    ? DATE_PATTERN_OPTIONS
    : // 模板样例里学到的写法不在常用清单里：原样列为第一项，不被 Select 吃掉
      [{ value: fmt.pattern ?? '', label: fmt.pattern ?? '' }, ...DATE_PATTERN_OPTIONS]
  const joiner = fmt.joiner === ' ' || fmt.joiner === '\n' ? fmt.joiner : ''
  return (
    <div className={styles.fmt}>
      {kinds.length > 1 ? (
        <Segmented<CoaTemplateFmt['kind']>
          size="small"
          disabled={disabled}
          value={fmt.kind}
          options={kinds.map((kind) => ({ value: kind, label: KIND_LABEL[kind] }))}
          onChange={(kind) => onChange(fmtForKind(kind, fmt, field, defaults))}
        />
      ) : (
        <span className={styles.fmtStatic}>{KIND_LABEL[fmt.kind]}</span>
      )}

      {fmt.kind === 'number' && (
        <>
          <InputNumber
            size="small"
            controls={false}
            min={0}
            max={6}
            precision={0}
            disabled={disabled}
            value={fmt.decimals}
            onChange={(decimals) => onChange({ ...fmt, decimals: typeof decimals === 'number' ? decimals : 0 })}
            aria-label="小数位数"
            style={{ width: 52 }}
          />
          <span>位小数</span>
        </>
      )}

      {fmt.kind === 'date' && (
        <Select
          size="small"
          disabled={disabled}
          value={fmt.pattern}
          options={patternOptions}
          onChange={(pattern) => onChange({ kind: 'date', pattern })}
          aria-label="日期格式"
          style={{ width: 136 }}
        />
      )}

      {(fmt.kind === 'number' || fmt.kind === 'text') && (
        <>
          <Input
            size="small"
            disabled={disabled}
            value={fmt.suffix ?? ''}
            onChange={(event) => onChange({ ...fmt, suffix: event.target.value })}
            placeholder="无"
            aria-label="单位后缀"
            style={{ width: 88 }}
          />
          <span>后缀</span>
          <Tooltip title="登记成文字判定时（符合规定、未检出）按「判定词对照」在后面补英文">
            <Switch
              size="small"
              disabled={disabled}
              checked={Boolean(fmt.bilingual)}
              onChange={(bilingual) => onChange({ ...fmt, bilingual })}
              aria-label="补英文"
            />
          </Tooltip>
          <span>补英文</span>
          {fmt.bilingual && (
            <Select<'' | ' ' | '\n'>
              size="small"
              disabled={disabled}
              value={joiner}
              options={JOINER_OPTIONS}
              onChange={(next) => onChange({ ...fmt, joiner: next })}
              aria-label="中英文之间的连接方式"
              style={{ width: 96 }}
            />
          )}
        </>
      )}
    </div>
  )
}

function SlotRow({
  field,
  slot,
  defaults,
  removable,
  picking,
  disabled,
  onChange,
  onRemove,
  onLocate,
}: {
  field: CoaTemplateField
  slot: CoaTemplateSlot
  defaults: CoaTemplateBindingView['defaults']
  removable: boolean
  picking: boolean
  disabled: boolean
  onChange: (patch: Partial<CoaTemplateSlot>) => void
  onRemove: () => void
  onLocate: () => void
}) {
  const position = describeSlot(slot.sid)
  const sample = slot.sample.trim()
  const inplace = slot.mode === 'inplace'
  return (
    // 摘要是整行：点行上的空白处展开/收起格式；行里的按钮各管各的（下面的 onClick 里拦掉）
    <details className={`${styles.slot} ${picking ? styles.slotPicking : ''}`}>
      <summary
        className={styles.slotRow}
        // 摘要的可访问名称只说它管的事（这一格的格式），不把整行文字再念一遍
        aria-label={`${position} 的格式：${describeFmt(slot.fmt)}`}
        onClick={(event) => {
          if ((event.target as HTMLElement).closest('button, input, a, label')) event.preventDefault()
        }}
      >
        <button
          type="button"
          className={styles.locate}
          title={`${slot.sid}（点击在左侧预览里定位）`}
          aria-label={`在预览中定位：${position}`}
          onClick={onLocate}
        >
          <AimOutlined aria-hidden />
          {position}
        </button>
        <span className={styles.slotContext} title={slot.context}>
          <span className={styles.slotContextLabel}>所在行：</span>
          {slot.context}
        </span>
        <code
          className={`${styles.slotSample} ${sample ? '' : styles.slotSampleEmpty}`}
          title={inplace ? `只替换这一段文字，前后的文字不动：${sample}` : sample}
        >
          {sample || '空位'}
        </code>
        <span className={styles.fmtCell} title="点击这一行修改格式">
          <span className={styles.fmtText}>{describeFmt(slot.fmt)}</span>
          <DownOutlined className={styles.fmtChevron} aria-hidden />
        </span>
        {removable && (
          <Button
            type="text"
            size="small"
            disabled={disabled}
            icon={<CloseOutlined />}
            aria-label={`取消位置 ${position}`}
            onClick={onRemove}
          />
        )}
      </summary>
      <div className={styles.slotEditor}>
        {inplace && (
          // 值夹在固定文字中间（标题行流水号）：要替换的那段原文可以改
          <Input
            size="small"
            disabled={disabled}
            value={slot.sample}
            onChange={(event) => onChange({ sample: event.target.value })}
            placeholder="要替换的文字"
            aria-label={`${position} 要替换的文字`}
            style={{ width: 240 }}
          />
        )}
        <FmtEditor
          field={field}
          fmt={slot.fmt}
          defaults={defaults}
          disabled={disabled}
          onChange={(fmt) => onChange({ fmt })}
        />
      </div>
    </details>
  )
}

function FieldRow({
  field,
  index,
  labels,
  defaults,
  disabled,
  pickingField,
  onFocusField,
  onStartPick,
  onCancelPick,
  onChangeField,
  onChangeSlot,
  onRemoveSlot,
  onUnbind,
  onDismissFlags,
  onLocate,
}: {
  field: CoaTemplateField
  index: number
  labels: Record<string, string>
  defaults: CoaTemplateBindingView['defaults']
  disabled: boolean
  pickingField: string | null
  onFocusField: CoaTemplateReviewListProps['onFocusField']
  onStartPick: CoaTemplateReviewListProps['onStartPick']
  onCancelPick: CoaTemplateReviewListProps['onCancelPick']
  onChangeField: CoaTemplateReviewListProps['onChangeField']
  onChangeSlot: CoaTemplateReviewListProps['onChangeSlot']
  onRemoveSlot: CoaTemplateReviewListProps['onRemoveSlot']
  onUnbind: CoaTemplateReviewListProps['onUnbind']
  onDismissFlags: CoaTemplateReviewListProps['onDismissFlags']
  onLocate: CoaTemplateReviewListProps['onLocate']
}) {
  const flagged = field.flags.length > 0
  const picking = pickingField === field.field
  const unbound = field.slots.length === 0
  const meta = fieldMeta(field)
  const cardClass = [
    styles.card,
    flagged ? styles.cardFlagged : '',
    picking ? styles.cardPicking : '',
    unbound ? styles.cardUnbound : '',
  ].join(' ')
  return (
    <li
      className={cardClass}
      onMouseEnter={() => onFocusField(field.field)}
      onMouseLeave={() => onFocusField(null)}
      onFocusCapture={() => onFocusField(field.field)}
      onBlurCapture={(event) => {
        // 焦点离开整张卡片才取消高亮（卡片内部控件之间跳不算）
        const next = event.relatedTarget
        if (!(next instanceof Node) || !event.currentTarget.contains(next)) onFocusField(null)
      }}
    >
      <div className={styles.cardHead}>
        <span className={styles.index} aria-hidden="true">
          {String(index).padStart(2, '0')}
        </span>
        <span
          className={`${styles.kindTag} ${field.kind === 'batch' ? styles.kindBatch : styles.kindItem}`}
        >
          {fieldKindLabel(field)}
        </span>
        <span className={styles.fieldName} title={field.label_cn}>
          {field.label_cn}
        </span>
        {meta && (
          <span className={styles.fieldMeta} title={meta}>
            {meta}
          </span>
        )}
        {field.flags.map((flag) => (
          <Tag key={flag} color="warning" variant="filled">
            {labels[flag] ?? flag}
          </Tag>
        ))}
        {/* 操作区整块靠右；标记多、一行放不下时整块换行，不把「必填」和按钮挤到折行或切掉 */}
        <span className={styles.cardActions}>
          {!unbound && (
            <Checkbox
              disabled={disabled}
              checked={field.required}
              onChange={(event) => onChangeField(field.field, { required: event.target.checked })}
            >
              必填
            </Checkbox>
          )}
          {flagged && !unbound && (
            <Button
              size="small"
              disabled={disabled}
              icon={<CheckOutlined />}
              onClick={() => onDismissFlags(field.field)}
            >
              确认无误
            </Button>
          )}
          <Button
            size="small"
            disabled={disabled || (pickingField !== null && !picking)}
            onClick={picking ? onCancelPick : () => onStartPick(field.field)}
          >
            {picking ? '取消挑位置' : unbound ? '标注位置' : '改位置'}
          </Button>
          {!unbound && (
            <Button size="small" type="text" disabled={disabled} onClick={() => onUnbind(field.field)}>
              不写入
            </Button>
          )}
        </span>
      </div>
      {picking && (
        <p className={styles.cardHint}>在左侧预览里点选「{field.label_cn}」要写入的位置。</p>
      )}
      {unbound && (
        <p className={styles.cardHint}>
          没标注到模板里的位置：不会出现在 COA 上，不影响保存；需要写入就点「标注位置」。
        </p>
      )}
      {!unbound &&
        field.slots.map((slot) => (
          <SlotRow
            key={slot.sid}
            field={field}
            slot={slot}
            defaults={defaults}
            removable={field.slots.length > 1}
            picking={picking}
            disabled={disabled}
            onChange={(patch) => onChangeSlot(field.field, slot.sid, patch)}
            onRemove={() => onRemoveSlot(field.field, slot.sid)}
            onLocate={() => onLocate(slot.sid)}
          />
        ))}
    </li>
  )
}

/** 结果列里待处理的格子：绑定到一个字段，或确认它是固定文字。 */
function ResidueItem({
  item,
  fields,
  disabled,
  onBind,
  onMarkStatic,
}: {
  item: CoaTemplateResidue
  fields: CoaTemplateField[]
  disabled: boolean
  onBind: (field: string) => void
  onMarkStatic: () => void
}) {
  const { message } = App.useApp()
  const [choosing, setChoosing] = useState(false)
  const unbound = fields.filter((field) => field.slots.length === 0)
  const candidates = unbound.length > 0 ? unbound : fields
  return (
    <li className={`${styles.item} ${styles.itemResidue}`}>
      <span className={styles.slotSample} title={item.sid}>
        {describeSlot(item.sid)}
      </span>
      <code className={styles.slotSample}>{item.text}</code>
      <span className={styles.itemText} title={item.context}>
        所在行：{item.context}
      </span>
      <span className={styles.itemSpacer} />
      {choosing ? (
        <>
          <Select
            size="small"
            showSearch={{ optionFilterProp: 'label' }}
            placeholder="选择检测项目"
            options={candidates.map((field) => ({ value: field.field, label: fieldOptionLabel(field) }))}
            onChange={(field) => onBind(field)}
            style={{ width: 220 }}
          />
          <Button size="small" onClick={() => setChoosing(false)}>
            取消
          </Button>
        </>
      ) : (
        <>
          <Button size="small" disabled={disabled} onClick={() => setChoosing(true)}>
            绑定到项目
          </Button>
          <Button
            size="small"
            disabled={disabled}
            onClick={() => {
              onMarkStatic()
              message.info('已记为固定文字，生成 COA 时保持模板原文')
            }}
          >
            固定文字，保持原文
          </Button>
        </>
      )}
    </li>
  )
}

const VERDICT_SOURCE_LABEL: Record<VerdictSource, string> = {
  builtin: '内置',
  custom: '自定义',
  override: '覆盖内置',
}

/** 对照表最后那一行：加一条对照。中文和内置的相同，就是给这份标准换一种英文写法。 */
function AddVerdictRow({
  disabled,
  onAdd,
}: {
  disabled: boolean
  onAdd: (cn: string, en: string) => void
}) {
  const [cn, setCn] = useState('')
  const [en, setEn] = useState('')
  const key = cn.trim()
  const value = en.trim()
  const ready = key !== '' && value !== ''
  const overridesBuiltIn = BUILTIN_VERDICTS.some(([name]) => name === key)
  const submit = () => {
    if (!ready || disabled) return
    onAdd(key, value)
    setCn('')
    setEn('')
  }
  return (
    <tr className={styles.verdictAdd}>
      <td>
        <Input
          size="small"
          disabled={disabled}
          value={cn}
          onChange={(event) => setCn(event.target.value)}
          onPressEnter={submit}
          placeholder="中文判定词"
          aria-label="中文判定词"
        />
      </td>
      <td>
        <div className={styles.verdictAddCell}>
          <Input
            size="small"
            disabled={disabled}
            value={en}
            onChange={(event) => setEn(event.target.value)}
            onPressEnter={submit}
            placeholder="英文对照"
            aria-label="英文对照"
          />
          <Button size="small" icon={<PlusOutlined />} disabled={disabled || !ready} onClick={submit}>
            添加
          </Button>
        </div>
      </td>
      <td>
        {ready && overridesBuiltIn && (
          <span className={styles.verdictSource} data-source="override">
            将覆盖内置
          </span>
        )}
      </td>
      <td />
    </tr>
  )
}

function EmptyList({
  icon,
  title,
  hint,
  action,
}: {
  icon: ReactNode
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className={styles.empty}>
      <span className={styles.emptyIcon} aria-hidden="true">
        {icon}
      </span>
      <span className={styles.emptyTitle}>{title}</span>
      {hint && <p className={styles.emptyHint}>{hint}</p>}
      {action}
    </div>
  )
}

export function CoaTemplateReviewList({
  view,
  disabled,
  filter,
  onFilterChange,
  onFocusField,
  pickingField,
  onStartPick,
  onCancelPick,
  onChangeField,
  onChangeSlot,
  onRemoveSlot,
  onUnbind,
  onDismissFlags,
  onMarkStatic,
  onBindResidue,
  onChangeVerdicts,
  onLocate,
}: CoaTemplateReviewListProps) {
  const [query, setQuery] = useState('')
  const labels = view.flag_labels
  const flaggedCount = view.fields.filter(needsConfirm).length
  const unboundCount = view.fields.filter((f) => f.slots.length === 0).length
  const rows = visibleFields(view, filter, query)
  // 对照表 = 内置 + 这份标准的自定义，取值顺序和生成 COA 时一致（同一个中文以自定义为准）
  const verdictRows = mergeVerdicts(view.verdicts)
  const ownVerdicts = verdictRows.filter((row) => row.source !== 'builtin').length
  const pickingLabel = view.fields.find((f) => f.field === pickingField)?.label_cn ?? ''
  const keyword = query.trim()
  // 清单要换一批内容：上一批里悬停高亮的字段可能已经不在了，先撤掉预览里的高亮
  const changeFilter = (next: ReviewFilter) => {
    onFocusField(null)
    onFilterChange(next)
  }
  const changeQuery = (next: string) => {
    onFocusField(null)
    setQuery(next)
  }

  return (
    <div className={styles.reviewScroll}>
      <div className={styles.reviewHead}>
        <Segmented<ReviewFilter>
          size="small"
          aria-label="核对清单筛选"
          value={filter}
          options={[
            { value: 'review', label: `需确认 ${flaggedCount}` },
            { value: 'all', label: `全部 ${view.fields.length}` },
            { value: 'unbound', label: `未标注 ${unboundCount}` },
          ]}
          onChange={changeFilter}
        />
        <Input
          className={styles.search}
          size="small"
          allowClear
          disabled={disabled}
          prefix={<SearchOutlined aria-hidden />}
          placeholder="搜索字段、位置或当前值"
          aria-label="搜索字段"
          value={query}
          onChange={(event) => changeQuery(event.target.value)}
        />
      </div>

      {pickingField !== null && (
        <div role="status" className={styles.pickBanner}>
          <AimOutlined aria-hidden />
          <span>
            正在为「{pickingLabel}」挑位置：在左侧预览里点选要写入的位置。
          </span>
          <span className={styles.pickBannerSpacer} />
          <Button size="small" onClick={onCancelPick}>
            取消挑位置
          </Button>
        </div>
      )}

      {view.problems.length > 0 && (
        <Alert
          className={styles.notice}
          type="warning"
          showIcon
          title={`有 ${view.problems.length} 条 AI 绑定没有采用`}
          description={
            <ul className={styles.problems}>
              {view.problems.map((problem, index) => (
                // 同一条原因可能重复出现（几个字段都标到了同一格）
                <li key={`${index}-${problem}`}>{problem}</li>
              ))}
            </ul>
          }
        />
      )}

      {view.residue.length > 0 && (
        <section>
          <h4 className={styles.sectionLabel}>
            结果列里待处理的格子（{view.residue.length}）
            <small>填过值的模板上，这里可能残留旧结果</small>
          </h4>
          <ul className={styles.itemList}>
            {view.residue.map((item) => (
              <ResidueItem
                key={item.sid}
                item={item}
                fields={view.fields}
                disabled={disabled}
                onBind={(field) => onBindResidue(item.sid, field)}
                onMarkStatic={() => onMarkStatic(item.sid)}
              />
            ))}
          </ul>
        </section>
      )}

      {rows.length === 0 ? (
        <EmptyList
          icon={
            keyword ? (
              <SearchOutlined />
            ) : filter === 'all' ? undefined : (
              <CheckCircleOutlined />
            )
          }
          title={
            keyword
              ? `没有匹配「${keyword}」的字段`
              : filter === 'review'
                ? '没有需要确认的字段'
                : filter === 'unbound'
                  ? '所有字段都标注了位置'
                  : '这份标准还没有可标注的字段'
          }
          hint={
            keyword
              ? '可以搜字段的中英文名、位置上的现有文字，或「表 2」这样的位置。'
              : filter === 'review'
                ? 'AI 的标注都通过了自动校验。保存前建议在「全部」里抽查几项位置和格式。'
                : undefined
          }
          action={
            keyword ? (
              <Button size="small" onClick={() => changeQuery('')}>
                清除搜索
              </Button>
            ) : filter === 'review' ? (
              <Button size="small" onClick={() => changeFilter('all')}>
                查看全部 {view.fields.length} 项
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className={styles.list}>
          {rows.map((field, index) => (
            <FieldRow
              key={field.field}
              field={field}
              index={index + 1}
              labels={labels}
              defaults={view.defaults}
              disabled={disabled}
              pickingField={pickingField}
              onFocusField={onFocusField}
              onStartPick={onStartPick}
              onCancelPick={onCancelPick}
              onChangeField={onChangeField}
              onChangeSlot={onChangeSlot}
              onRemoveSlot={onRemoveSlot}
              onUnbind={onUnbind}
              onDismissFlags={onDismissFlags}
              onLocate={onLocate}
            />
          ))}
        </ul>
      )}

      <details className={styles.verdicts}>
        <summary className={styles.verdictSummary}>
          <span>判定词英文对照</span>
          <span className={styles.verdictMeta}>
            内置 {BUILTIN_VERDICTS.length} 条 · 自定义 {ownVerdicts} 条 ·
            开了「补英文」的位置按这张表补英文
          </span>
          <DownOutlined className={styles.fmtChevron} aria-hidden />
        </summary>
        <div className={styles.verdictBody}>
          <table className={styles.verdictTable}>
            <caption className="sr-only">判定词英文对照：内置与这份标准的自定义，同一个中文以自定义为准</caption>
            <colgroup>
              <col className={styles.verdictColCn} />
              <col />
              <col className={styles.verdictColSource} />
              <col className={styles.verdictColAction} />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">中文判定词</th>
                <th scope="col">英文</th>
                <th scope="col">来源</th>
                <th scope="col" className={styles.verdictActionHead}>
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {verdictRows.map((row) => (
                <tr key={row.cn}>
                  <th scope="row" className={styles.verdictName} title={row.cn}>
                    {row.cn}
                  </th>
                  <td>
                    {row.source === 'builtin' ? (
                      <span className={styles.verdictEnglish}>{row.en}</span>
                    ) : (
                      <Input
                        size="small"
                        disabled={disabled}
                        value={row.en}
                        aria-label={`「${row.cn}」的英文对照`}
                        onChange={(event) =>
                          onChangeVerdicts({ ...view.verdicts, [row.cn]: event.target.value })
                        }
                      />
                    )}
                  </td>
                  <td>
                    <span className={styles.verdictSource} data-source={row.source}>
                      {VERDICT_SOURCE_LABEL[row.source]}
                    </span>
                  </td>
                  <td className={styles.verdictAction}>
                    {row.source !== 'builtin' && (
                      <Button
                        type="text"
                        size="small"
                        disabled={disabled}
                        icon={<CloseOutlined />}
                        // 覆盖内置的那条删掉就回到内置英文，按钮要说清楚
                        aria-label={
                          row.source === 'override'
                            ? `删除「${row.cn}」的覆盖，恢复内置英文`
                            : `删除「${row.cn}」的对照`
                        }
                        title={
                          row.source === 'override'
                            ? '删除后恢复内置英文'
                            : '删除这条对照'
                        }
                        onClick={() => onChangeVerdicts(omitKey(view.verdicts, row.cn))}
                      />
                    )}
                  </td>
                </tr>
              ))}
              <AddVerdictRow
                disabled={disabled}
                onAdd={(cn, en) => onChangeVerdicts({ ...view.verdicts, [cn]: en })}
              />
            </tbody>
          </table>
          <p className={styles.verdictHint}>
            内置对照所有标准通用。模板里有表外的判定词，就在这里加一条；
            用同一个中文再加一条，这份标准改用你填的英文，删掉后恢复内置。
          </p>
        </div>
      </details>
    </div>
  )
}
