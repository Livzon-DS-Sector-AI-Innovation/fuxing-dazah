'use client'

import { useId, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Alert, App, Button, Input, Modal, Space, Spin, Table, Tag, Typography, Upload } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownloadOutlined,
  ExclamationCircleFilled,
  FileWordOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import { downloadCoaRenderFile, fetchCoaRenders, verifyCoaRender } from '@/lib/api/qa'
import type { CoaRenderRecord, CoaVerifyResult, CoaVerifySlot } from '@/types/qa'
import { describeSlot } from './coaTemplateBindingModel'
import {
  differenceLine,
  formatVerifyTime,
  hasSlotDetail,
  scopeNote,
  slotProblem,
  VERDICT_META,
  verdictExplanation,
  verdictTitle,
  type VerdictTone,
} from './coaVerifyModel'
import styles from './CoaVerifyModal.module.css'

const { Text } = Typography
const Dragger = Upload.Dragger

const VERDICT_ICON: Record<VerdictTone, React.ReactNode> = {
  success: <CheckCircleFilled />,
  warning: <ExclamationCircleFilled />,
  error: <CloseCircleFilled />,
}

/** 下载走 <a download>：File System Access 的保存对话框不是跨浏览器基线（同 CoaRenderModal）。 */
function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  // 过早回收会让个别浏览器拿不到文件
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const RECORD_PAGE_SIZE = 20

export function CoaVerifyModal({
  productId,
  onClose,
}: {
  /** 留档清单按当前产品筛；没有产品时清单留空 */
  productId: string | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const titleId = useId()
  const [file, setFile] = useState<File | null>(null)
  const [showAll, setShowAll] = useState(false)
  // 批号筛选：输入框的值和已提交的筛选词分开存，输到一半不去打接口
  const [batchInput, setBatchInput] = useState('')
  const [batchFilter, setBatchFilter] = useState('')

  // 选文件是事件回调里发起的：不走挂载 effect（StrictMode 下 mutation 会卡在 pending）
  const verify = useMutation({
    mutationFn: ({ picked, reportId }: { picked: File; reportId?: string }) =>
      verifyCoaRender(picked, reportId),
  })
  const records = useQuery({
    queryKey: ['qa', 'coa', 'renders', productId, batchFilter],
    queryFn: () =>
      fetchCoaRenders({ product_id: productId, batch_no: batchFilter, page_size: RECORD_PAGE_SIZE }),
    enabled: productId !== null,
  })

  const run = (picked: File, reportId?: string) => {
    if (!/\.docx$/i.test(picked.name)) {
      message.error('只支持 .docx 文件；PDF 或旧版 .doc 请先用 Word 另存为 .docx')
      return
    }
    setFile(picked)
    setShowAll(false)
    verify.mutate({ picked, reportId })
  }

  const download = async (record: CoaRenderRecord) => {
    try {
      saveBlob(await downloadCoaRenderFile(record.id), record.filename)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '下载系统原件失败')
    }
  }

  const result = verify.isError || verify.isPending ? null : (verify.data ?? null)
  const problems = result ? result.slots.filter((slot) => slotProblem(slot) !== null) : []
  const shown = showAll ? (result?.slots ?? []) : problems
  const compact = file !== null

  const slotColumns: ColumnsType<CoaVerifySlot> = [
    {
      title: '位置',
      key: 'where',
      width: 170,
      render: (_, row) => describeSlot(row.sid),
    },
    { title: '项目', dataIndex: 'label', key: 'label', width: 170 },
    {
      title: '系统原件',
      key: 'expected',
      render: (_, row) => row.expected || <span className={styles.emptyValue}>（空）</span>,
    },
    {
      title: '这份文件里',
      key: 'actual',
      render: (_, row) => {
        if (row.actual == null) return <span className={styles.emptyValue}>找不到这一处</span>
        // 被改掉的值标红：一眼看到差在哪
        return row.status === 'differs' ? (
          <span className={styles.changedValue}>{row.actual}</span>
        ) : (
          row.actual
        )
      },
    },
    {
      title: '问题',
      key: 'problem',
      width: 200,
      render: (_, row) => {
        const problem = slotProblem(row)
        return problem ? (
          <span className={styles.problem}>{problem}</span>
        ) : (
          <span className={styles.fine}>一致</span>
        )
      },
    },
  ]

  const recordColumns: ColumnsType<CoaRenderRecord> = [
    {
      title: '生成时间',
      key: 'created_at',
      width: 126,
      render: (_, row) => formatVerifyTime(row.created_at),
    },
    {
      title: '批号',
      key: 'batch',
      render: (_, row) => (
        <div>
          <div className={styles.recordPrimary}>
            {row.batch_no}
            {row.report_voided && (
              <Tag style={{ marginInlineStart: 6 }} color="default">
                登记已作废
              </Tag>
            )}
          </div>
          <div className={styles.recordSecondary}>
            模板 {row.standard_code} · {row.actor_name || '—'}
          </div>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 168,
      render: (_, row) => (
        <Space size={0}>
          <Button
            type="link"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => void download(row)}
          >
            下载原件
          </Button>
          <Button
            type="link"
            size="small"
            disabled={!file || verify.isPending}
            onClick={() => file && run(file, row.report_id)}
          >
            跟这份比
          </Button>
        </Space>
      ),
    },
  ]

  const renderResult = (value: CoaVerifyResult) => {
    const meta = VERDICT_META[value.verdict]
    const record = value.record
    const note = scopeNote(value)
    return (
      <div
        className={styles.verdict}
        data-tone={meta.tone}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <div className={styles.verdictHead}>
          <span className={styles.verdictIcon} aria-hidden="true">
            {VERDICT_ICON[meta.tone]}
          </span>
          <span className={styles.verdictTitle}>{verdictTitle(value.verdict)}</span>
          {record && (
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => void download(record)}
            >
              下载系统原件
            </Button>
          )}
        </div>
        <p className={styles.verdictText}>{verdictExplanation(value)}</p>
        {record && (
          <dl className={styles.verdictMeta}>
            <dt>批号</dt>
            <dd>{record.batch_no}</dd>
            <dt>模板</dt>
            <dd>{record.standard_code}</dd>
            <dt>生成于</dt>
            <dd>{formatVerifyTime(record.created_at)}</dd>
            <dt>生成人</dt>
            <dd>{record.actor_name || '—'}</dd>
          </dl>
        )}
        {record && value.other_records.length > 0 && (
          <div className={styles.older}>
            <span>此前还生成过 {value.other_records.length} 次：</span>
            {value.other_records.map((old) => (
              <span key={old.id}>
                {formatVerifyTime(old.created_at)} · {old.actor_name || '—'}
                <Button type="link" size="small" onClick={() => void download(old)}>
                  下载
                </Button>
              </span>
            ))}
          </div>
        )}
        {note && <p className={styles.note}>{note}</p>}
        {record && (
          <div className={styles.hash}>
            原件 SHA-256{' '}
            <Text className={styles.hash} copyable={{ text: record.file_sha256 }}>
              {record.file_sha256.slice(0, 16)}…
            </Text>
          </div>
        )}
      </div>
    )
  }

  return (
    <Modal
      title="COA 验证"
      open
      width={820}
      centered
      onCancel={onClose}
      mask={{ closable: !verify.isPending }}
      keyboard={!verify.isPending}
      styles={{ body: { maxHeight: 'calc(100vh - 200px)', overflowY: 'auto' } }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button onClick={onClose} disabled={verify.isPending}>
            关闭
          </Button>
        </div>
      }
    >
      <p className={styles.lead}>
        交一份 COA 文件上来，系统对着留档比对：是不是系统出的、生成之后有没有被改过。
      </p>
      <Dragger
        className={compact ? `${styles.drop} ${styles.dropCompact}` : styles.drop}
        accept=".docx"
        maxCount={1}
        showUploadList={false}
        disabled={verify.isPending}
        beforeUpload={(picked) => {
          run(picked)
          return Upload.LIST_IGNORE // 请求由验证接口自己发，不走 Upload 的上传流程
        }}
      >
        {file ? (
          <div className={styles.fileBar}>
            <FileWordOutlined className={styles.fileIcon} aria-hidden="true" />
            <span className={styles.fileName}>{file.name}</span>
            <span className={styles.fileHint}>点击或拖拽可更换文件</span>
          </div>
        ) : (
          <div className={styles.dropInner}>
            <InboxOutlined className={styles.dropIcon} aria-hidden="true" />
            <p className={styles.dropText}>点击或把 COA 文件拖到这里</p>
            <p className={styles.dropHint}>只支持 .docx；选好后自动比对，文件不会保存</p>
          </div>
        )}
      </Dragger>

      {verify.isPending && (
        <div className={styles.pending} aria-busy="true">
          <Spin size="small" />
          正在比对…
        </div>
      )}
      {verify.isError && (
        <Alert
          style={{ marginTop: 12 }}
          type="error"
          showIcon
          title="验证失败"
          description={verify.error instanceof Error ? verify.error.message : '请稍后重试'}
        />
      )}
      {result && renderResult(result)}

      {result && hasSlotDetail(result.verdict) && (
        <div role="group" aria-labelledby={`${titleId}-slots`} className={styles.section}>
          <div id={`${titleId}-slots`} className={styles.sectionHead}>
            <span className={styles.sectionTitle}>系统填写的位置</span>
            <span className={styles.sectionMeta}>{result.compared} 处</span>
            {problems.length > 0 && (
              <span className={styles.sectionBad}>对不上 {problems.length} 处</span>
            )}
          </div>
          {shown.length > 0 && (
            <Table<CoaVerifySlot>
              rowKey={(row) => `${row.field}:${row.sid}`}
              size="small"
              columns={slotColumns}
              dataSource={shown}
              pagination={false}
            />
          )}
          {result.other_differences.length > 0 && (
            <>
              <div className={styles.sectionHead} style={{ marginTop: 12 }}>
                <span className={styles.sectionTitle}>系统没填写的位置</span>
                <span className={styles.sectionBad}>
                  {result.other_differences.length} 处不同
                </span>
              </div>
              <ul role="list" className={styles.differences}>
                {result.other_differences.map((item, index) => (
                  <li key={`${item.where}:${item.sid}:${index}`}>
                    {differenceLine(item, describeSlot)}
                  </li>
                ))}
              </ul>
            </>
          )}
          {result.slots.length > problems.length && (
            <Button
              style={{ paddingInline: 0, marginTop: 8 }}
              type="link"
              size="small"
              aria-expanded={showAll}
              onClick={() => setShowAll((current) => !current)}
            >
              {showAll ? '只看对不上的' : `显示全部 ${result.slots.length} 处比对`}
            </Button>
          )}
        </div>
      )}

      <div role="region" aria-labelledby={`${titleId}-records`} className={styles.section}>
        <div id={`${titleId}-records`} className={styles.sectionHead}>
          <span className={styles.sectionTitle}>生成留档</span>
          <span className={styles.sectionMeta}>没有留档的文件不算系统出具</span>
          <Input.Search
            className={styles.recordSearch}
            size="small"
            allowClear
            placeholder="按批号查留档"
            aria-label="按批号查生成留档"
            value={batchInput}
            onChange={(event) => setBatchInput(event.target.value)}
            onSearch={(value) => setBatchFilter(value.trim())}
          />
        </div>
        {!file && (
          <p className={`${styles.note} ${styles.recordSecondary}`}>
            选好文件后，可以指定跟某一条留档比对。
          </p>
        )}
        {/* 不给表格单独设滚动区：嵌在弹窗的滚动区里会并排出现两条滚动条 */}
        <Table<CoaRenderRecord>
          rowKey="id"
          size="small"
          loading={records.isLoading}
          columns={recordColumns}
          dataSource={records.data?.items ?? []}
          pagination={false}
          locale={{ emptyText: batchFilter ? `没有批号含「${batchFilter}」的生成记录` : '还没有生成记录' }}
        />
      </div>
    </Modal>
  )
}
