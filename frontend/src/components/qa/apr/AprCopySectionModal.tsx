'use client'

import { useState } from 'react'
import { Alert, App, Input, Modal, Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { actionError } from '@/components/qa/deviation/shared'
import { copyAprSection } from '@/actions/qa'
import { fetchAprSections } from '@/lib/api/qa'
import type { AprProduct, AprSection } from '@/types/qa'

interface AprCopySectionModalProps {
  products: AprProduct[]
  targetProduct: AprProduct
  defaultSource: AprSection
  onClose: () => void
  onCopied: (sectionId: string) => void
}

/**
 * 复制模板段：把一个段的列定义（含标准限与标记）复制到当前产品，
 * 跨产品复用同一张检验/工艺表时不用逐列重建。后端单请求原子完成
 * （建段+建列同事务），失败不会留半截段。
 */
export function AprCopySectionModal({
  products,
  targetProduct,
  defaultSource,
  onClose,
  onCopied,
}: AprCopySectionModalProps) {
  const { message } = App.useApp()
  const [sourceProductId, setSourceProductId] = useState(targetProduct.id)
  const [sourceSectionId, setSourceSectionId] = useState<string | null>(defaultSource.id)
  const [name, setName] = useState(`${defaultSource.name}（副本）`)
  const [saving, setSaving] = useState(false)

  const sourceSectionsQuery = useQuery({
    queryKey: ['qa', 'apr', 'sections', sourceProductId],
    queryFn: () => fetchAprSections(sourceProductId),
    enabled: !!sourceProductId,
  })
  const sourceSections = sourceSectionsQuery.data ?? []
  const sourceSection = sourceSections.find((section) => section.id === sourceSectionId) ?? null

  const handleSourceSectionChange = (sectionId: string) => {
    setSourceSectionId(sectionId)
    const found = sourceSections.find((section) => section.id === sectionId)
    if (found) {
      setName(sourceProductId === targetProduct.id ? `${found.name}（副本）` : found.name)
    }
  }

  const handleSubmit = async () => {
    if (!sourceSection) {
      message.warning('请选择要复制的模板段')
      return
    }
    const sectionName = name.trim()
    if (!sectionName) {
      message.warning('请填写新段名')
      return
    }
    setSaving(true)
    try {
      const result = await copyAprSection(sourceSection.id, {
        product_id: targetProduct.id,
        name: sectionName,
      })
      if (!result.success || !result.data) {
        message.error(result.success ? '复制模板段失败' : actionError(result))
        return
      }
      message.success(
        `已复制 ${result.data.items} 个列定义${
          result.data.skipped > 0 ? `，跳过 ${result.data.skipped} 个停用列` : ''
        }`,
      )
      onCopied(result.data.section.id)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={
        <div>
          <div className="text-[16px]">复制模板段</div>
          <div className="mt-0.5 text-[12px] font-normal text-[var(--color-steel)]">
            复制到「{targetProduct.code} {targetProduct.name}」
          </div>
        </div>
      }
      open
      width={560}
      onOk={handleSubmit}
      onCancel={onClose}
      okText="复制"
      cancelText="取消"
      confirmLoading={saving}
      mask={{ closable: false }}
    >
      <Alert
        type="info"
        showIcon
        className="mb-4"
        title="只复制模板结构"
        description="列定义、标准限与 OOT/趋势标记会一起复制；批次数据不会被复制，停用的列会跳过。"
      />
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="mb-1 text-[12px] text-[var(--color-steel)]">源产品</div>
          <Select
            style={{ width: '100%' }}
            showSearch
            optionFilterProp="label"
            value={sourceProductId}
            onChange={(value) => {
              setSourceProductId(value)
              setSourceSectionId(null)
              setName('')
            }}
            options={products.map((product) => ({
              value: product.id,
              label: `${product.code} ${product.name}`,
            }))}
          />
        </div>
        <div>
          <div className="mb-1 text-[12px] text-[var(--color-steel)]">源模板段</div>
          <Select
            style={{ width: '100%' }}
            placeholder="选择要复制的段"
            loading={sourceSectionsQuery.isLoading}
            value={sourceSectionId}
            onChange={handleSourceSectionChange}
            options={sourceSections.map((section) => ({
              value: section.id,
              label: `${section.name}（${section.items?.length ?? 0} 列）`,
            }))}
          />
        </div>
      </div>
      <div className="mt-3">
        <div className="mb-1 text-[12px] text-[var(--color-steel)]">新段名</div>
        <Input
          value={name}
          maxLength={100}
          placeholder="复制后的段名"
          onChange={(event) => setName(event.target.value)}
        />
      </div>
    </Modal>
  )
}
