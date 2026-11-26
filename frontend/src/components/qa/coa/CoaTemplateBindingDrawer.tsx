'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, ConfigProvider, Drawer, Skeleton, Spin, Tag, Tooltip, Upload } from 'antd'
import type { ThemeConfig } from 'antd'
import { FileWordOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import {
  annotateCoaTemplate,
  fetchCoaTemplate,
  saveCoaTemplateBinding,
  uploadCoaTemplate,
} from '@/lib/api/qa'
import type {
  CoaTemplateBindingView,
  CoaTemplateField,
  CoaTemplateSlot,
} from '@/types/qa'
import { confirmAsync, DANGER_OK_PROPS } from './CoaShared'
import { CoaTemplateGridPreview, type BoundSlot } from './CoaTemplateGridPreview'
import { CoaTemplateReviewList } from './CoaTemplateReviewList'
import {
  bindingStatus,
  bindSlotToField,
  defaultFilter,
  detachSlots,
  indexGrid,
  toBindingPayload,
  type ReviewFilter,
} from './coaTemplateBindingModel'
import styles from './CoaTemplateBindingDrawer.module.css'

export interface CoaTemplateBindingDrawerProps {
  standardId: string
  /** 标题用，如「3205 USP 客户标准」 */
  standardLabel: string
  /** 带过来的 docx（导入建完标准时的那份，包括当时没接着标注、留在页面上的那份）：
   * 抽屉一挂载就上传成模板，再直接开始标注。标准此时不该已有别的模板。 */
  pendingFile?: File | null
  onClose: () => void
  /** 标注确认保存后（调用方刷新列表） */
  onSaved: () => void
}

const errorText = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback

/** 这个抽屉里数据位多（一份标准几十个位置）：控件比全站默认小一档，只作用于抽屉内部。 */
const COMPACT_THEME: ThemeConfig = {
  token: { controlHeight: 32, controlHeightSM: 28 },
  components: {
    Button: { controlHeight: 32 },
    Input: { controlHeight: 32 },
    Select: { controlHeight: 32 },
  },
}

const formatTime = (iso: string) =>
  new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(iso))

export function CoaTemplateBindingDrawer({
  standardId,
  standardLabel,
  pendingFile,
  onClose,
  onSaved,
}: CoaTemplateBindingDrawerProps) {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const queryKey = ['qa', 'coa', 'template', standardId] as const
  const templateQuery = useQuery({
    queryKey,
    queryFn: () => fetchCoaTemplate(standardId),
    // 打开时拿最新状态；保存/上传后由调用方失效缓存
    staleTime: 0,
  })
  // 工作副本：AI 提案，或用户开始修改后的已保存标注；null=还没有可编辑的标注
  const [draft, setDraft] = useState<CoaTemplateBindingView | null>(null)
  // 清单看哪一页：null=还没人点过筛选。已保存的标注带着要确认的字段（如确认之后
  // 类型/单位变了）就先看它们，否则直接看全部
  const [pickedFilter, setFilter] = useState<ReviewFilter | null>(null)
  // 核对清单里正在看的字段：它的位置在预览里高亮
  const [focusField, setFocusField] = useState<string | null>(null)
  // 正在为哪个字段挑位置（null=不在挑）：预览里的段落变成可点
  const [pickingField, setPickingField] = useState<string | null>(null)
  // 要在预览里滚到的数据位（点清单上的位置时）
  const [locate, setLocate] = useState<{ sid: string; tick: number } | null>(null)

  const annotate = useMutation({
    mutationFn: () => annotateCoaTemplate(standardId),
    onSuccess: (proposal) => {
      setDraft(proposal)
      setPickingField(null)
      // 有 AI 没把握的字段先看它们；都通过了校验就直接看全部——保存前要人工过目
      setFilter(defaultFilter(proposal))
    },
    onError: (error) => message.error(errorText(error, 'AI 标注失败，请稍后重试')),
  })
  const upload = useMutation({
    mutationFn: (file: File) => uploadCoaTemplate(standardId, file),
    onSuccess: (state) => {
      queryClient.setQueryData(queryKey, state)
      setDraft(null)
      annotate.mutate()
    },
    onError: (error) => message.error(errorText(error, '模板上传失败，请稍后重试')),
  })
  const save = useMutation({
    mutationFn: (view: CoaTemplateBindingView) =>
      saveCoaTemplateBinding(standardId, toBindingPayload(view)),
    onSuccess: () => {
      message.success('模板标注已保存，这份标准的报告可以生成 COA 了')
      onSaved()
      onClose()
    },
    onError: (error) => message.error(errorText(error, '保存模板标注失败，请稍后重试')),
  })

  const busy = upload.isPending
    ? 'upload'
    : annotate.isPending
      ? 'annotate'
      : save.isPending
        ? 'save'
        : null

  const template = templateQuery.data
  const grid = template?.grid ?? []
  const gridIndex = indexGrid(grid)
  const resultColumns = template?.result_columns ?? {}
  // 没有改动时直接展示已保存的标注；一动就落到 draft 上
  const view = draft ?? template?.binding ?? null
  const status = view ? bindingStatus(view) : null
  // 存好的标注和当前字段配置对不上的地方（确认之后字段有增删、类型/单位变了）：
  // 清单上方逐条列出，并不改别的也能直接重新确认保存
  const drift = template?.drift ?? null
  const filter: ReviewFilter = pickedFilter ?? (view ? defaultFilter(view) : 'all')
  const canSave = status?.canSave ?? false
  const saveBlocker = status?.reason ?? ''
  const bound = new Map<string, BoundSlot>()
  for (const field of view?.fields ?? []) {
    for (const slot of field.slots) {
      bound.set(slot.sid, { field: field.field, label: field.label_cn, slot })
    }
  }
  const staticSids = new Set(view?.static_slots ?? [])
  const residueSids = new Set(view?.residue.map((r) => r.sid) ?? [])
  const pickingLabel = view?.fields.find((f) => f.field === pickingField)?.label_cn ?? ''

  const commit = (change: (current: CoaTemplateBindingView) => CoaTemplateBindingView) => {
    if (view) setDraft(change(view))
  }
  const patchField = (fieldKey: string, patch: Partial<CoaTemplateField>) =>
    commit((current) => ({
      ...current,
      fields: current.fields.map((field) =>
        field.field === fieldKey ? { ...field, ...patch } : field
      ),
    }))
  const patchSlot = (fieldKey: string, sid: string, patch: Partial<CoaTemplateSlot>) =>
    commit((current) => ({
      ...current,
      fields: current.fields.map((field) =>
        field.field === fieldKey
          ? {
              ...field,
              slots: field.slots.map((slot) =>
                slot.sid === sid ? { ...slot, ...patch } : slot
              ),
            }
          : field
      ),
    }))
  const unbind = (fieldKey: string) =>
    commit((current) =>
      detachSlots(
        current,
        fieldKey,
        current.fields.find((f) => f.field === fieldKey)?.slots.map((s) => s.sid) ?? [],
        resultColumns
      )
    )

  const bindSlot = (fieldKey: string, sid: string) => {
    commit((current) => bindSlotToField(current, fieldKey, sid, gridIndex, resultColumns))
    setPickingField(null)
  }

  const handlePick = (sid: string) => {
    if (pickingField) bindSlot(pickingField, sid)
  }

  const startAnnotate = () => {
    // 已经有一份核对结果（提案或已保存的标注）时，重新标注会把它整个换掉
    if (!view) {
      annotate.mutate()
      return
    }
    confirmAsync(modal, {
      title: '重新让 AI 标注？',
      content: '当前的核对结果（包括做过的修改）会被新的提案替换；已保存的标注在你再次保存前不受影响。',
      okText: '重新标注',
      cancelText: '取消',
      onOk: () => annotate.mutate(),
    })
  }

  /** 关抽屉：有没保存的核对结果时先确认，免得一下点丢。 */
  const requestClose = () => {
    if (busy !== null) return
    if (!draft) {
      onClose()
      return
    }
    confirmAsync(modal, {
      title: '放弃还没保存的核对结果？',
      content: '关掉后这次的核对与修改不会保留；已保存的标注不受影响。',
      okText: '放弃并关闭',
      cancelText: '继续核对',
      okButtonProps: DANGER_OK_PROPS,
      onOk: onClose,
    })
  }

  const replaceTemplate = (file: File) => {
    confirmAsync(modal, {
      title: '替换模板文件？',
      content: '标注是针对具体文件的：换文件后已保存的标注作废，需要重新标注并确认。',
      okText: '替换并重新标注',
      cancelText: '取消',
      onOk: () => upload.mutate(file),
    })
  }

  const statusTag =
    template?.template.status === 'bound' ? (
      <Tag color="success" variant="filled">
        标注已确认
      </Tag>
    ) : template?.template.status === 'stale' ? (
      <Tag color="warning" variant="filled">
        需重新核对
      </Tag>
    ) : template?.template.status === 'unbound' ? (
      <Tag color="warning" variant="filled">
        待标注
      </Tag>
    ) : null

  return (
    <ConfigProvider theme={COMPACT_THEME}>
      <Drawer
        className={styles.container}
        title={
          <div>
            <div>模板标注 — {standardLabel}</div>
            <div className={styles.headerFile}>
              {template?.template.filename && (
                <span className={styles.headerName} title={template.template.filename}>
                  {template.template.filename}
                </span>
              )}
              {statusTag}
              {template?.template.bound_at && (
                <span className={styles.headerTime}>确认于 {formatTime(template.template.bound_at)}</span>
              )}
            </div>
          </div>
        }
        open
        size="min(1600px, 100vw)"
        onClose={requestClose}
        afterOpenChange={(open) => {
          // 带着文件打开：抽屉一开就把文件上传成模板，接着自动标注。
          // 必须走这个事件而不是挂载后的 effect：开发模式会把挂载 effect 连跑两遍，
          // 期间 TanStack 会摘掉这次上传的订阅且装回时不再挂上，上传状态会永远停在「进行中」。
          if (open && pendingFile) upload.mutate(pendingFile)
        }}
        mask={{ closable: busy === null }}
        keyboard={busy === null}
        styles={{
          header: { padding: '14px 24px', borderBlockEnd: '1px solid var(--color-hairline-soft)' },
          // 内边距交给里面的面板：滚动条贴抽屉边缘
          body: { padding: 0 },
          footer: { padding: '10px 24px', borderBlockStart: '1px solid var(--color-hairline-soft)' },
        }}
        footer={
          <div className={styles.toolbar}>
            {template?.template.status !== 'none' && (
              <Tooltip title="换文件后已保存的标注作废">
                <Upload
                  accept=".docx"
                  maxCount={1}
                  showUploadList={false}
                  beforeUpload={(file) => {
                    replaceTemplate(file)
                    return false
                  }}
                >
                  <Button size="small" icon={<UploadOutlined />} disabled={busy !== null}>
                    替换模板文件
                  </Button>
                </Upload>
              </Tooltip>
            )}
            <span className={styles.toolbarSpacer} />
            {status && view && (
              // 进度挨着保存按钮：看完就知道还差什么才能保存
              <span className={styles.toolbarStats}>
                <span>
                  已标注 <b>{status.boundCount}</b>/{view.fields.length}
                </span>
                {status.flagged.length > 0 && (
                  <span className={styles.toolbarAttention}>
                    待确认 <b>{status.flagged.length}</b>
                  </span>
                )}
                {status.unhandled > 0 && (
                  <span className={styles.toolbarAttention}>
                    待处理格子 <b>{status.unhandled}</b>
                  </span>
                )}
              </span>
            )}
            <Button onClick={requestClose} disabled={busy !== null}>
              关闭
            </Button>
            {view && (
              <>
                <Button icon={<ReloadOutlined />} disabled={busy !== null} onClick={startAnnotate}>
                  {draft ? '重新标注' : '重新让 AI 标注'}
                </Button>
                <Tooltip title={draft && !canSave ? saveBlocker : undefined}>
                  <Button
                    type="primary"
                    loading={save.isPending}
                    // 没改动也能保存：字段配置变了的时候，重新确认一次就是在保存当前这份标注
                    disabled={busy !== null || (draft === null && !drift) || !canSave}
                    onClick={() => view && save.mutate(view)}
                  >
                    {template?.template.status === 'unbound' ? '确认标注并保存' : '保存修改'}
                  </Button>
                </Tooltip>
              </>
            )}
          </div>
        }
      >
        {templateQuery.isError ? (
          <div className={styles.uploadBody}>
            <div className={styles.uploadBox}>
              <Alert
                type="error"
                showIcon
                title="模板信息加载失败"
                description={errorText(templateQuery.error, '请稍后重试')}
                action={
                  <Button size="small" onClick={() => void templateQuery.refetch()}>
                    重新加载
                  </Button>
                }
              />
            </div>
          </div>
        ) : templateQuery.isLoading ? (
          <div className={styles.uploadBody}>
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        ) : template?.template.status === 'none' ? (
          <div className={styles.uploadBody}>
            <div className={styles.uploadBox}>
              <h3 className={styles.uploadTitle}>这份标准还没有 COA 模板</h3>
              <p className={styles.uploadHint}>
                上传这份客户标准对应的 docx：可以是没填值的空白模板，也可以是一份填过数据的历史 COA。
                上传后 AI 会自动标出数据位置，再由你核对。
              </p>
              {upload.isError && (
                <Alert
                  className={styles.notice}
                  type="error"
                  showIcon
                  title="模板上传失败"
                  description={errorText(upload.error, '请稍后重试')}
                />
              )}
              {upload.isPending ? (
                <Alert className={styles.notice} type="info" showIcon title="正在上传模板…" />
              ) : (
                <Upload.Dragger
                  accept=".docx"
                  maxCount={1}
                  showUploadList={false}
                  className={styles.dropzone}
                  beforeUpload={(file) => {
                    upload.mutate(file)
                    return false
                  }}
                >
                  <FileWordOutlined className={styles.dropIcon} />
                  <span className={styles.dropTitle}>拖入 COA 模板 docx</span>
                  <span className={styles.dropHint}>或点击选择文件（仅支持 .docx）</span>
                </Upload.Dragger>
              )}
            </div>
          </div>
        ) : (
          <div className={styles.root}>
            <div className={styles.previewPane}>
              <div className={styles.previewHead}>
                <span className={styles.previewTitle}>
                  模板预览
                  {pickingField && (
                    <Tag color="processing" variant="filled">
                      请点选「{pickingLabel}」的位置
                    </Tag>
                  )}
                </span>
                <span className={styles.legend}>
                  {bound.size > 0 && (
                    <span className={styles.legendItem}>
                      <span className={`${styles.legendSwatch} ${styles.legendBound}`} />
                      已标注的数据位
                    </span>
                  )}
                  {residueSids.size > 0 && (
                    <span className={styles.legendItem}>
                      <span className={`${styles.legendSwatch} ${styles.legendResidue}`} />
                      待处理
                    </span>
                  )}
                  {staticSids.size > 0 && (
                    <span className={styles.legendItem}>
                      <span className={`${styles.legendSwatch} ${styles.legendStatic}`} />
                      保持原文
                    </span>
                  )}
                </span>
              </div>
              <CoaTemplateGridPreview
                grid={grid}
                index={gridIndex}
                bound={bound}
                staticSids={staticSids}
                residueSids={residueSids}
                focusField={focusField}
                pickingField={pickingField}
                pickingLabel={pickingLabel}
                locate={locate}
                onPick={handlePick}
              />
            </div>
            {annotate.isPending ? (
              <div className={styles.reviewPane}>
                <div className={styles.busy}>
                  <Spin size="small" />
                  <span>AI 正在标注模板里的数据位，通常十几秒到一分钟…</span>
                </div>
                {/* 占位行的形状贴近标完后的清单：先占住位置，标完时内容不会跳 */}
                <ul className={styles.placeholders} aria-hidden="true">
                  {[38, 30, 44, 34, 28, 40, 32, 36].map((width, index) => (
                    <li key={index} className={styles.placeholder}>
                      <div className={styles.placeholderBar} style={{ inlineSize: `${width}%` }} />
                      <div className={styles.placeholderBar} style={{ inlineSize: "94%" }} />
                    </li>
                  ))}
                </ul>
              </div>
            ) : view ? (
              // 偏差提示固定在清单上方，不随清单滚动：它是这次要重新核对的原因
              <div className={styles.reviewWithNotice}>
                {drift && (
                  <Alert
                    className={styles.driftNotice}
                    type="warning"
                    showIcon
                    title="标注确认后字段配置有变化，重新保存后才能生成 COA"
                    description={
                      <ul className={styles.problems}>
                        {drift.lines.map((line, index) => (
                          // 同一句话可能出现多次（早先没记名字的条目都叫「已移除的检测项目」）
                          <li key={`${index}-${line}`}>{line}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
                <CoaTemplateReviewList
                  view={view}
                  disabled={busy !== null}
                  filter={filter}
                  onFilterChange={setFilter}
                  pickingField={pickingField}
                  onFocusField={setFocusField}
                  onStartPick={setPickingField}
                  onCancelPick={() => setPickingField(null)}
                  onChangeField={patchField}
                  onChangeSlot={patchSlot}
                  onRemoveSlot={(fieldKey, sid) => {
                    // 最后一处也取消 = 这个字段不再写入模板
                    if ((view.fields.find((f) => f.field === fieldKey)?.slots.length ?? 0) <= 1) {
                      unbind(fieldKey)
                    } else {
                      commit((current) => detachSlots(current, fieldKey, [sid], resultColumns))
                    }
                  }}
                  onUnbind={unbind}
                  onDismissFlags={(fieldKey) => {
                    const slots = view.fields.find((f) => f.field === fieldKey)?.slots ?? []
                    patchField(fieldKey, { flags: [], slots: slots.map((s) => ({ ...s, flags: [] })) })
                  }}
                  onMarkStatic={(sid) =>
                    commit((current) => ({
                      ...current,
                      residue: current.residue.filter((r) => r.sid !== sid),
                      static_slots: [...current.static_slots, sid],
                    }))
                  }
                  onBindResidue={bindSlot}
                  onChangeVerdicts={(verdicts) => commit((current) => ({ ...current, verdicts }))}
                  onLocate={(sid) => setLocate({ sid, tick: Date.now() })}
                />
              </div>
            ) : (
              <div className={styles.reviewPane}>
                {annotate.isError && (
                  <Alert
                    className={styles.notice}
                    type="error"
                    showIcon
                    title="上一次 AI 标注没有完成"
                    description={errorText(annotate.error, '请稍后重试')}
                  />
                )}
                <ol className={styles.steps} role="list">
                  <li className={styles.step}>
                    <span className={styles.stepNum}>1</span>
                    <div>
                      <div className={styles.stepTitle}>AI 标注</div>
                      <p className={styles.stepText}>
                        模型找出批号、流水号和每个检测结果应该写进模板的哪个位置，通常十几秒。
                      </p>
                    </div>
                  </li>
                  <li className={styles.step}>
                    <span className={styles.stepNum}>2</span>
                    <div>
                      <div className={styles.stepTitle}>人工核对</div>
                      <p className={styles.stepText}>
                        左边是模板预览，右边是清单。鼠标移到一条上，预览会标出它的位置；点位置可以让预览滚过去。
                        位置不对点「改位置」，格式不对点那一行修改。
                      </p>
                    </div>
                  </li>
                  <li className={styles.step}>
                    <span className={styles.stepNum}>3</span>
                    <div>
                      <div className={styles.stepTitle}>确认保存</div>
                      <p className={styles.stepText}>
                        保存后这份标准的报告才能生成 COA。AI 没把握的字段会带标记，逐个确认后才能保存。
                      </p>
                    </div>
                  </li>
                </ol>
                <div>
                  <Button type="primary" disabled={busy !== null} onClick={startAnnotate}>
                    开始 AI 标注
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </ConfigProvider>
  )
}
