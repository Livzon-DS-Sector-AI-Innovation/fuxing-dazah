'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Alert, App, Button, Modal, Spin } from 'antd'
import { DownloadOutlined, LinkOutlined, PrinterOutlined } from '@ant-design/icons'
import { checkCoaRender, coaPrintUrl, downloadCoaRender } from '@/lib/api/qa'
import type { CoaReport } from '@/types/qa'
import { describeSlot } from './coaTemplateBindingModel'

export interface CoaRenderModalProps {
  report: CoaReport
  /** 标准页靠产品码/模板码定位到这份标准（URL 参数），缺项处理完回去接着做 */
  productCode: string
  standardCode: string
  onClose: () => void
  /** 有字段没登记值：关闭本框去补录（打开编辑表单） */
  onEdit: () => void
}

const errorText = (error: unknown, fallback: string) =>
  error instanceof Error && error.message ? error.message : fallback

const UNBOUND_NOUN = { unbound_items: '个项目', unbound_batch: '项批次信息' } as const

export function CoaRenderModal({
  report,
  productCode,
  standardCode,
  onClose,
  onEdit,
}: CoaRenderModalProps) {
  const { message } = App.useApp()
  const router = useRouter()
  const queryClient = useQueryClient()
  const preflight = useMutation({ mutationFn: () => checkCoaRender(report.id) })
  const download = useMutation({
    mutationFn: async () => ({
      blob: await downloadCoaRender(report.id),
      filename: preflight.data?.filename ?? `${report.batch_no}_COA.docx`,
    }),
    onSuccess: ({ blob, filename }) => {
      // 下载走 <a download>：File System Access 的保存对话框不是跨浏览器基线
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      // 过早回收会让个别浏览器拿不到文件
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      // 出文件即留档：验证弹窗里的生成记录要能看到这一次
      void queryClient.invalidateQueries({ queryKey: ['qa', 'coa', 'renders'] })
      message.success(`已生成并留档 ${filename}`)
      onClose()
    },
  })
  // 新标签页里打开打印版：PDF 由浏览器阅读器显示，用它自带的打印按钮打印。window.open
  // 必须在点击事件里同步调用，否则会被弹窗拦截；返回 null 就是被拦了
  const openPrint = () => {
    const opened = window.open(coaPrintUrl(report.id), '_blank')
    if (!opened) {
      message.warning('浏览器拦截了新窗口，请允许本站弹出窗口后重试')
      return
    }
    opened.opener = null
  }

  const check = preflight.data
  const missing = check?.blocking.filter((b) => b.kind === 'missing') ?? []
  const stale = check?.blocking.filter((b) => b.kind === 'stale') ?? []
  const missingItems = missing.filter((b) => b.item).map((b) => b.label)
  const missingBatch = missing.filter((b) => !b.item).map((b) => b.label)
  const noEnglish = check?.warnings.filter((w) => w.kind === 'no_english') ?? []
  // 有登记值、但模板里没有标注位置的项目 / 批次信息（确认标注时认可的不写入）：提示而不拦
  const unbound = (check?.warnings ?? []).filter(
    (w) => w.kind === 'unbound_items' || w.kind === 'unbound_batch'
  )
  const goFixTemplate = () =>
    router.push(`/qa/coa/standards?product=${encodeURIComponent(productCode)}&standard=${encodeURIComponent(standardCode)}`)

  return (
    <Modal
      title={`生成 COA — 批号 ${report.batch_no}`}
      open
      onCancel={onClose}
      width={620}
      mask={{ closable: !download.isPending }}
      keyboard={!download.isPending}
      afterOpenChange={(open) => {
        if (open && !preflight.data && !preflight.isPending) preflight.mutate()
      }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button onClick={onClose} disabled={download.isPending}>
            关闭
          </Button>
          {missing.length > 0 && (
            <Button onClick={onEdit} disabled={download.isPending}>
              去补录
            </Button>
          )}
          {stale.length > 0 && (
            <Button icon={<LinkOutlined />} onClick={goFixTemplate}>
              去核对模板标注
            </Button>
          )}
          {check?.ok && (
            <>
              <Button icon={<PrinterOutlined />} onClick={openPrint} disabled={download.isPending}>
                快速打印
              </Button>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={download.isPending}
                onClick={() => download.mutate()}
              >
                下载 COA
              </Button>
            </>
          )}
        </div>
      }
    >
      {preflight.isPending && (
        <div style={{ display: 'grid', gap: 12, justifyItems: 'center', padding: '36px 0' }}>
          <Spin />
          <span style={{ color: 'var(--color-slate)', fontSize: 13 }}>正在预检…</span>
        </div>
      )}

      {preflight.isError && (
        <Alert
          type="error"
          showIcon
          title="这份报告现在不能生成 COA"
          description={errorText(preflight.error, '请稍后重试')}
          action={
            <Button size="small" icon={<LinkOutlined />} onClick={goFixTemplate}>
              去客户标准页处理
            </Button>
          }
        />
      )}

      {check && !check.ok && (
        <div style={{ display: 'grid', gap: 12 }}>
          {missing.length > 0 && (
            <Alert
              type="error"
              showIcon
              title={`有 ${missing.length} 个字段没有登记值，不能生成`}
              description={
                <div style={{ display: 'grid', gap: 4 }}>
                  <span>COA 上不许带着模板旧值或空白出报告。补录后重新生成。</span>
                  {missingItems.length > 0 && <span>检测结果：{missingItems.join('、')}</span>}
                  {missingBatch.length > 0 && <span>批次信息：{missingBatch.join('、')}</span>}
                </div>
              }
            />
          )}
          {stale.length > 0 && (
            <Alert
              type="error"
              showIcon
              title="输出里还能找到模板的旧批号/旧日期，不能生成"
              description={
                <div style={{ display: 'grid', gap: 4 }}>
                  <span>说明模板里有位置没标注到。请到客户标准里重新核对模板标注。</span>
                  {stale.map((item) => (
                    <span key={item.sample}>
                      旧值「{item.sample}」还留在：{item.found_in.map(describeSlot).join('、')}
                    </span>
                  ))}
                </div>
              }
            />
          )}
        </div>
      )}

      {check?.ok && download.isError && (
        <Alert
          type="error"
          showIcon
          title="生成失败"
          description={errorText(download.error, '请稍后重试')}
        />
      )}

      {check?.ok && (
        <div style={{ display: 'grid', gap: 12 }}>
          {/* 下载前先讲清楚：按哪份模板、写进去多少内容、出什么文件 */}
          <dl
            style={{
              display: 'grid',
              gridTemplateColumns: 'auto minmax(0, 1fr)',
              gap: '6px 16px',
              margin: 0,
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            <dt style={{ color: 'var(--color-steel)' }}>模板</dt>
            <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>
              {check.template || '（未记录文件名）'}
            </dd>
            <dt style={{ color: 'var(--color-steel)' }}>写入</dt>
            <dd style={{ margin: 0 }}>
              {check.written
                ? `${check.written.positions} 个位置（批次信息 ${check.written.batch} 项 · 检测结果 ${check.written.items} 项）`
                : '按已确认的模板标注'}
            </dd>
            <dt style={{ color: 'var(--color-steel)' }}>文件</dt>
            <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{check.filename}</dd>
            <dt style={{ color: 'var(--color-steel)' }}>打印</dt>
            <dd style={{ margin: 0 }}>
              在新标签页打开 PDF，用阅读器里的打印按钮打印；首次打开约需数秒
            </dd>
          </dl>
          {noEnglish.length > 0 && (
            <Alert
              type="warning"
              showIcon
              title="有判定词没有英文对照，COA 上只会出现中文"
              description={`${[...new Set(noEnglish.map((w) => w.text))].join('、')}。可在模板标注的「判定词英文对照」里补上后重新生成。`}
            />
          )}
          {unbound.map((warning) => (
            <Alert
              key={warning.kind}
              type="warning"
              showIcon
              title={`有 ${warning.count} ${UNBOUND_NOUN[warning.kind]}有登记值，但模板里没有标注位置`}
              description={`不会出现在 COA 上：${warning.labels.join('、')}${warning.count > warning.labels.length ? ' 等' : ''}。`}
            />
          ))}
        </div>
      )}
    </Modal>
  )
}
