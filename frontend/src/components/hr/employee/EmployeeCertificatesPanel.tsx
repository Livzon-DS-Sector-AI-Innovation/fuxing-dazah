'use client'

import { useCallback, useEffect, useState } from 'react'
import { App, Alert, Button, DatePicker, Drawer, Empty, Form, Input, Modal, Select, Spin, Switch, Tag, Upload } from 'antd'
import { EyeOutlined, HistoryOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  CERTIFICATE_CATEGORY_LABELS,
  type CertificateCategory,
  type CertificateCategoryView,
  type EmployeeCertificatesView,
} from '@/types/hr'
import {
  deleteEmployeeCertificate,
  downloadCertificateFile,
  fetchEmployeeCertificates,
  parseCertificateFile,
  previewCertificateFile,
  updateEmployeeCertificate,
  uploadEmployeeCertificate,
} from '@/actions/hr'
import { usePermission } from '@/hooks/usePermission'
import { downloadBase64File, base64ToObjectUrl } from '@/lib/hr/download'

const DAY = 24 * 60 * 60 * 1000

function fmtSize(size: number): string {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)}MB`
  return `${Math.max(1, Math.round(size / 1024))}KB`
}

function expiryTag(cert: NonNullable<CertificateCategoryView['current']>): string {
  if (cert.is_permanent) return '长期有效'
  if (cert.expiry_date) {
    const left = Math.ceil((new Date(cert.expiry_date).getTime() - Date.now()) / DAY)
    return left < 0 ? `已过期 ${Math.abs(left)} 天` : `剩余 ${left} 天`
  }
  return '未登记有效期'
}

/** 员工证件档案区：六类分组（当前版本 + 历史折叠 + 待补交标注 + 上传/换证） */
export default function EmployeeCertificatesPanel({ employeeId }: { employeeId: string }) {
  const { message: msg, modal } = App.useApp()
  const { hasPermission } = usePermission()
  const canManage = hasPermission('hr:certificate:manage')

  const [view, setView] = useState<EmployeeCertificatesView | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  // 上传/换证
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadTarget, setUploadTarget] = useState<CertificateCategoryView | null>(null)
  const [uploading, setUploading] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [parsing, setParsing] = useState(false)
  const [parsedInfo, setParsedInfo] = useState<'ok' | 'fail' | null>(null)
  const [form] = Form.useForm()

  // 预览
  const [previewInfo, setPreviewInfo] = useState<{ url: string; type: string; name: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const r = await fetchEmployeeCertificates(employeeId)
      setView(r.data)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '加载证件失败')
    } finally {
      setLoading(false)
    }
  }, [employeeId, msg])

  useEffect(() => { void load() }, [load])

  useEffect(() => () => {
    if (previewInfo) window.URL.revokeObjectURL(previewInfo.url)
  }, [previewInfo])

  const openUpload = (cat: CertificateCategoryView) => {
    setUploadTarget(cat)
    setFile(null)
    setParsedInfo(null)
    form.resetFields()
    form.setFieldsValue({
      certificate_name: cat.current?.certificate_name ?? undefined,
      certificate_no: undefined,
      issue_date: undefined,
      expiry_date: undefined,
      is_permanent: false,
    })
    setUploadOpen(true)
  }

  /** 选文件后自动识别回填（视觉模型，仅预填——以人工核对为准） */
  const handleFilePicked = async (f: File) => {
    setFile(f)
    setParsedInfo(null)
    setParsing(true)
    try {
      const r = await parseCertificateFile(f)
      const d = r.data
      form.setFieldsValue({
        certificate_name: d.certificate_name ?? undefined,
        certificate_no: d.certificate_no ?? undefined,
        issue_date: d.issue_date ? dayjs(d.issue_date) : undefined,
        expiry_date: (!d.is_permanent && d.expiry_date) ? dayjs(d.expiry_date) : undefined,
        is_permanent: d.is_permanent,
      })
      setParsedInfo('ok')
    } catch {
      setParsedInfo('fail')
    } finally {
      setParsing(false)
    }
  }

  const handleUpload = async () => {
    if (!file) { msg.warning('请选择证件扫描件（图片/PDF）'); return }
    const v = await form.validateFields()
    setUploading(true)
    try {
      const r = await uploadEmployeeCertificate(employeeId, {
        category: uploadTarget!.category,
        certificate_name: v.certificate_name,
        certificate_no: v.certificate_no,
        issue_date: v.issue_date?.format('YYYY-MM-DD'),
        expiry_date: v.is_permanent ? undefined : v.expiry_date?.format('YYYY-MM-DD'),
        is_permanent: !!v.is_permanent,
        remark: v.remark,
      }, file)
      msg.success(r.message || '已归档')
      setUploadOpen(false)
      void load()
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handlePreview = async (certId: string, contentType: string, filename: string) => {
    try {
      const r = await previewCertificateFile(certId)
      const type = contentType === 'application/pdf' ? 'application/pdf'
        : contentType.startsWith('image/') ? contentType : 'application/octet-stream'
      setPreviewInfo({ url: base64ToObjectUrl(r.base64, type), type, name: filename })
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '获取原件失败')
    }
  }

  const handleDownload = async (certId: string, filename: string) => {
    try {
      const r = await downloadCertificateFile(certId)
      downloadBase64File(r.base64, r.filename || filename)
    } catch (e) {
      msg.error(e instanceof Error ? e.message : '下载失败')
    }
  }

  const handleEdit = (cert: NonNullable<CertificateCategoryView['current']>) => {
    // 复用上传弹窗做要素更正（无文件时走 PUT）
    modal.confirm({
      title: `更正「${CERTIFICATE_CATEGORY_LABELS[cert.category]}」登记要素`,
      content: '在弹窗中修改发证日期/有效期等要素，不影响已上传的原件。',
      okText: '继续',
      onOk: () => openEditModal(cert),
    })
  }

  const openEditModal = (cert: NonNullable<CertificateCategoryView['current']>) => {
    setUploadTarget(null)
    setFile(null)
    form.resetFields()
    form.setFieldsValue({
      certificate_name: cert.certificate_name ?? undefined,
      certificate_no: undefined,
      is_permanent: cert.is_permanent,
      remark: cert.remark ?? undefined,
    })
    setUploadOpen(true)
    setEditTargetId(cert.id)
  }

  const [editTargetId, setEditTargetId] = useState<string | null>(null)

  const handleDelete = (cert: NonNullable<CertificateCategoryView['current']>) => {
    modal.confirm({
      title: `删除「${CERTIFICATE_CATEGORY_LABELS[cert.category]}」v${cert.version_no}？`,
      content: '软删除；若删除的是当前版本，最新历史版本将自动顶替。',
      okText: '删除', okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteEmployeeCertificate(cert.id)
          msg.success('已删除')
          void load()
        } catch (e) { msg.error(e instanceof Error ? e.message : '删除失败') }
      },
    })
  }

  if (loading) return <div className="text-center py-8"><Spin /></div>
  if (!view) return <Empty description="未加载到证件档案" className="py-6" />

  const missingSet = new Set(view.missing.map(m => m.category))

  return (
    <div className="space-y-3">
      {view.missing.length > 0 && (
        <div className="rounded-md border border-orange-300 bg-orange-50 px-3 py-2 text-[13px] text-orange-700">
          待补交 {view.missing.length} 项：
          {view.missing.map(m => (
            <Tag key={m.category} color="orange" style={{ marginInlineStart: 8 }}>{m.label}</Tag>
          ))}
          <span className="text-xs text-orange-500 ml-1">（应交清单按{view.employee.is_key_position ? '重点岗位' : '一般岗位'}口径计算）</span>
        </div>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {view.categories.map(cat => (
          <div key={cat.category}
            className={`rounded-md border p-3 ${missingSet.has(cat.category) ? 'border-dashed border-orange-300' : 'border-[var(--color-hairline)]'}`}>
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2 min-w-0">
                <b className="text-[14px]">{cat.label}</b>
                {cat.required && <Tag style={{ fontSize: 10, margin: 0 }}>应交</Tag>}
                {missingSet.has(cat.category) && <Tag color="orange" style={{ fontSize: 10, margin: 0 }}>待补交</Tag>}
              </div>
              {canManage && (
                <Button size="small" icon={cat.current
                  ? <HistoryOutlined /> : <PlusOutlined />}
                  onClick={() => openUpload(cat)}>
                  {cat.current ? '换证/补交新版本' : '上传'}
                </Button>
              )}
            </div>
            {cat.current ? (
              <div className="text-[13px] space-y-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-gray-700">{cat.current.certificate_name || '（未填证件名称）'}</span>
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>v{cat.current.version_no} 当前版</Tag>
                  <span className="text-gray-500">{expiryTag(cat.current)}</span>
                  {cat.current.certificate_no && (
                    <span className="text-gray-400 font-mono text-xs">证号 {cat.current.certificate_no}</span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-400">
                  {cat.current.issue_date && <span>发证 {cat.current.issue_date}</span>}
                  {cat.current.expiry_date && <span>有效期至 {cat.current.expiry_date}</span>}
                  <span>{cat.current.filename} · {fmtSize(cat.current.size)}</span>
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <Button size="small" icon={<EyeOutlined />}
                    onClick={() => handlePreview(cat.current!.id, cat.current!.content_type, cat.current!.filename)}>
                    查看
                  </Button>
                  <Button size="small" onClick={() => handleDownload(cat.current!.id, cat.current!.filename)}>下载</Button>
                  {canManage && <Button size="small" type="text" onClick={() => handleEdit(cat.current!)}>更正要素</Button>}
                  {canManage && <Button size="small" type="text" danger onClick={() => handleDelete(cat.current!)}>删除</Button>}
                </div>
                {cat.history.length > 0 && (
                  <div className="pt-1">
                    <Button size="small" type="link" className="!px-0"
                      onClick={() => setExpanded(p => ({ ...p, [cat.category]: !p[cat.category] }))}>
                      历史版本（{cat.history.length}）{expanded[cat.category] ? '收起' : '展开'}
                    </Button>
                    {expanded[cat.category] && (
                      <div className="space-y-1 pt-1">
                        {cat.history.map(h => (
                          <div key={h.id} className="flex items-center justify-between gap-2 text-xs text-gray-500 rounded bg-[var(--color-bg-gray, #f5f5f5)] px-2 py-1">
                            <span className="truncate">v{h.version_no} · {h.certificate_name || h.filename} · {h.issue_date || '未登记发证日期'}</span>
                            <span className="flex items-center gap-1 shrink-0">
                              <Button size="small" type="text" onClick={() => handlePreview(h.id, h.content_type, h.filename)}>查看</Button>
                              <Button size="small" type="text" onClick={() => handleDownload(h.id, h.filename)}>下载</Button>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-[13px] text-gray-400 py-1">尚未归档{cat.required ? '，属应交证件' : ''}</div>
            )}
          </div>
        ))}
      </div>

      <Modal
        title={editTargetId
          ? `更正证件要素 — ${uploadTarget ? uploadTarget.label : ''}`
          : `上传证件 — ${uploadTarget?.label || ''}${uploadTarget?.current ? `（当前 v${uploadTarget.current.version_no}，将升为新版本）` : ''}`}
        open={uploadOpen}
        onOk={async () => {
          if (editTargetId) {
            const v = await form.validateFields()
            try {
              await updateEmployeeCertificate(editTargetId, {
                certificate_name: v.certificate_name,
                certificate_no: v.certificate_no,
                issue_date: v.issue_date?.format('YYYY-MM-DD'),
                expiry_date: v.is_permanent ? undefined : v.expiry_date?.format('YYYY-MM-DD'),
                is_permanent: !!v.is_permanent,
                remark: v.remark,
              })
              msg.success('已更正')
              setUploadOpen(false)
              void load()
            } catch (e) { msg.error(e instanceof Error ? e.message : '更正失败') }
          } else {
            await handleUpload()
          }
        }}
        okText={editTargetId ? '保存更正' : '上传归档'}
        confirmLoading={uploading}
        onCancel={() => { setUploadOpen(false); setEditTargetId(null) }}
      >
        <Form form={form} layout="vertical" className="mt-2">
          {!editTargetId && (
            <>
              <Form.Item label="证件扫描件" required rules={[{ required: true, message: '' }]}>
                <Upload accept=".jpg,.jpeg,.png,.webp,.bmp,.pdf" maxCount={1} showUploadList
                  beforeUpload={(f) => { void handleFilePicked(f); return false }}>
                  <Button icon={<UploadOutlined />}>选择文件（图片/PDF，≤20MB）</Button>
                </Upload>
              </Form.Item>
              {parsing && (
                <Alert type="info" showIcon className="mb-3"
                  message="正在自动识别证件要素…" />
              )}
              {parsedInfo === 'ok' && (
                <Alert type="success" showIcon className="mb-3" closable
                  message="已自动识别并回填要素，请核对无误后上传（识别结果仅供参考）" />
              )}
              {parsedInfo === 'fail' && (
                <Alert type="warning" showIcon className="mb-3" closable
                  message="自动识别不可用或未识别出内容，请手动填写要素" />
              )}
            </>
          )}
          <div className="grid grid-cols-2 gap-x-3">
            <Form.Item name="certificate_name" label="证件名称">
              <Input placeholder="如：低压电工证" maxLength={128} />
            </Form.Item>
            <Form.Item name="certificate_no" label="证件号码（展示时脱敏）">
              <Input placeholder="选填" maxLength={64} />
            </Form.Item>
            <Form.Item name="issue_date" label="发证日期">
              <DatePicker className="w-full" />
            </Form.Item>
            <Form.Item name="expiry_date" label="有效期至">
              <DatePicker className="w-full" disabled={!!form.getFieldValue('is_permanent')} />
            </Form.Item>
          </div>
          <Form.Item name="is_permanent" label="长期有效" valuePropName="checked">
            <Switch onChange={(checked: boolean) => {
              if (checked) form.setFieldValue('expiry_date', undefined)
            }} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={512} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={previewInfo?.name || '证件原件'}
        size={620}
        open={!!previewInfo}
        onClose={() => setPreviewInfo(null)}
        extra={previewInfo && (
          <Button size="small" onClick={() => {
            const a = document.createElement('a')
            a.href = previewInfo.url
            a.download = previewInfo.name
            a.click()
          }}>另存为</Button>
        )}
      >
        {previewInfo && (
          previewInfo.type === 'application/pdf' ? (
            <iframe src={previewInfo.url} title="证件预览" className="w-full h-full border-0" />
          ) : previewInfo.type.startsWith('image/') ? (
            <img src={previewInfo.url} alt={previewInfo.name} className="w-full" />
          ) : (
            <Empty description="该文件类型不支持在线预览，请下载后查看" />
          )
        )}
      </Drawer>
    </div>
  )
}
