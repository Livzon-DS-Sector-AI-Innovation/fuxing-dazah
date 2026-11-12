'use client'

import { useMemo, useState } from 'react'
import {
  Button,
  Dropdown,
  Empty,
  Input,
  Skeleton,
} from 'antd'
import type { MenuProps } from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import clsx from 'clsx'
import type { AprProduct, AprSection } from '@/types/qa'
import { AprChromeStyles, AprMeta, AprSheet } from './AprChrome'
import {
  DATA_KIND_DOT,
  DATA_KIND_LABEL,
} from './AprConfigShared'

interface AprConfigTreeProps {
  products: AprProduct[]
  loading: boolean
  selectedProductId: string | null
  sections: AprSection[]
  sectionsLoading: boolean
  selectedSectionId: string | null
  onSelectProduct: (productId: string) => void
  onSelectSection: (sectionId: string) => void
  onCreateProduct: () => void
  onEditProduct: (product: AprProduct) => void
  onCopyTemplate: (product: AprProduct) => void
  onDeleteProduct: (product: AprProduct) => void
  onCreateSection: () => void
  onEditSection: (section: AprSection) => void
  onCopySection: (section: AprSection) => void
  onDeleteSection: (section: AprSection) => void
}

/**
 * 左侧「产品 → 模板段」目录。
 *
 * 版式按书的目录页来：层级用缩进和组间规则线表达，整块底色只有一处——
 * 右栏正在编辑的那一段。产品行选中不填底色（避免和段的选中抢注意力），
 * 只给一道 2px 书脊并把名称加重。
 */
export function AprConfigTree(props: AprConfigTreeProps) {
  const {
    products,
    loading,
    selectedProductId,
    sections,
    sectionsLoading,
    selectedSectionId,
    onSelectProduct,
    onSelectSection,
    onCreateProduct,
    onEditProduct,
    onCopyTemplate,
    onDeleteProduct,
    onCreateSection,
    onEditSection,
    onCopySection,
    onDeleteSection,
  } = props
  const [keyword, setKeyword] = useState('')

  const filteredProducts = useMemo(() => {
    const text = keyword.trim().toLowerCase()
    if (!text) return products
    return products.filter((product) =>
      [product.code, product.name, product.name_en ?? '']
        .join(' ')
        .toLowerCase()
        .includes(text),
    )
  }, [products, keyword])

  const unconfigured = products.filter((product) => (product.section_count ?? 0) === 0).length

  return (
    <AprSheet
      title="产品目录"
      meta={
        <AprMeta
          items={[
            `${products.length} 个产品`,
            unconfigured > 0 ? (
              <span style={{ color: 'var(--color-warning)' }}>{unconfigured} 个待配置</span>
            ) : null,
          ]}
        />
      }
      toolbar={
        <Input
          size="small"
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          prefix={<SearchOutlined style={{ color: 'var(--color-stone)' }} />}
          placeholder="搜索产品名称或短码"
    />
      }
      className="mt-0 flex max-h-[380px] flex-col xl:max-h-[calc(100vh-170px)]"
      bodyClassName="flex min-h-0 flex-1 flex-col overflow-hidden"
      footer={sections.length > 0 ? <span>数据录入按这里的段与列生成表单。</span> : undefined}
    >
      <div className={clsx(AprChromeStyles.railBody, 'min-h-0 flex-1 overflow-y-auto')}>
        {loading ? (
          <div className="px-1 py-2">
            <Skeleton active title={false} paragraph={{ rows: 5 }} />
          </div>
        ) : filteredProducts.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={keyword ? '没有匹配的产品' : '还没有产品'}
            style={{ margin: '24px 0' }}
          >
            {!keyword && (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={onCreateProduct}>
                新增产品
              </Button>
            )}
          </Empty>
        ) : (
          filteredProducts.map((product) => {
            const selected = product.id === selectedProductId
            const sectionCount = product.section_count ?? 0
            const itemCount = product.item_count ?? 0
            const productMenu: MenuProps = {
              items: [
                { key: 'edit', label: '编辑产品', icon: <EditOutlined /> },
                { key: 'copy', label: '从已有产品复制模板', icon: <CopyOutlined /> },
                { type: 'divider' },
                { key: 'delete', label: '删除产品', icon: <DeleteOutlined />, danger: true },
              ],
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation()
                if (key === 'edit') onEditProduct(product)
                if (key === 'copy') onCopyTemplate(product)
                if (key === 'delete') onDeleteProduct(product)
              },
            }
            return (
              <div key={product.id} className={AprChromeStyles.railGroup}>
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={selected}
                  onClick={() => onSelectProduct(product.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      // 空格默认会滚动页面，选中语义下要吞掉
                      event.preventDefault()
                      onSelectProduct(product.id)
                    }
                  }}
                  className={clsx(
                    AprChromeStyles.railProduct,
                    selected && AprChromeStyles.railProductActive,
                  )}
                >
                  <span className={AprChromeStyles.railCode}>{product.code}</span>
                  <span
                    className={clsx(
                      AprChromeStyles.railName,
                      selected && AprChromeStyles.railNameActive,
                      !product.is_active && AprChromeStyles.railNameOff,
                    )}
                    title={`${product.name}${product.name_en ? `（${product.name_en}）` : ''}`}
                  >
                    {product.name}
                  </span>
                  {!product.is_active && <span className={AprChromeStyles.railFlag}>停用</span>}
                  <span className={AprChromeStyles.railCount}>
                    {sectionCount === 0 ? (
                      <span style={{ color: 'var(--color-warning)' }}>未配置</span>
                    ) : (
                      `${sectionCount} 段 / ${itemCount} 列`
                    )}
                  </span>
                  <Dropdown menu={productMenu} trigger={['click']} placement="bottomRight">
                    <button
                      type="button"
                      aria-label={`${product.name} 的操作`}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                      className={AprChromeStyles.railMore}
                    >
                      <MoreOutlined />
                    </button>
                  </Dropdown>
                </div>

                {selected && (
                  <div className={AprChromeStyles.railSections}>
                    {sectionsLoading ? (
                      <div className="px-1 py-2">
                        <Skeleton active title={false} paragraph={{ rows: 2 }} />
                      </div>
                    ) : sections.length === 0 ? (
                      <div className={AprChromeStyles.railEmpty}>这本册还没有模板段</div>
                    ) : (
                      sections.map((section) => {
                        const active = section.id === selectedSectionId
                        const itemTotal = section.items?.length ?? 0
                        const sectionMenu: MenuProps = {
                          items: [
                            { key: 'edit', label: '编辑段', icon: <EditOutlined /> },
                            { key: 'copy', label: '复制此段', icon: <CopyOutlined /> },
                            { type: 'divider' },
                            { key: 'delete', label: '删除段', icon: <DeleteOutlined />, danger: true },
                          ],
                          onClick: ({ key, domEvent }) => {
                            domEvent.stopPropagation()
                            if (key === 'edit') onEditSection(section)
                            if (key === 'copy') onCopySection(section)
                            if (key === 'delete') onDeleteSection(section)
                          },
                        }
                        return (
                          <div
                            key={section.id}
                            role="button"
                            tabIndex={0}
                            aria-current={active ? 'true' : undefined}
                            onClick={() => onSelectSection(section.id)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                onSelectSection(section.id)
                              }
                            }}
                            className={clsx(
                              AprChromeStyles.railSection,
                              active && AprChromeStyles.railSectionActive,
                            )}
                          >
                            <span
                              className={AprChromeStyles.railDot}
                              style={{ background: DATA_KIND_DOT[section.data_kind] }}
                              title={DATA_KIND_LABEL[section.data_kind]}
                            />
                            <span
                              className={clsx(
                                AprChromeStyles.railSectionName,
                                active && AprChromeStyles.railSectionNameActive,
                              )}
                              title={section.name}
                            >
                              {section.name}
                            </span>
                            {section.market && (
                              <span className={AprChromeStyles.railTag} title="药典 / 市场">
                                {section.market}
                              </span>
                            )}
                            <span
                              className={AprChromeStyles.railCount}
                              title={`${itemTotal} 个列定义`}
                            >
                              {itemTotal} 列
                            </span>
                            <Dropdown menu={sectionMenu} trigger={['click']} placement="bottomRight">
                              <button
                                type="button"
                                aria-label={`${section.name} 的操作`}
                                onClick={(event) => event.stopPropagation()}
                                onKeyDown={(event) => event.stopPropagation()}
                                className={AprChromeStyles.railMore}
                              >
                                <MoreOutlined />
                              </button>
                            </Dropdown>
                          </div>
                        )
                      })
                    )}
                    <button type="button" onClick={onCreateSection} className={AprChromeStyles.railAdd}>
                      <PlusOutlined style={{ fontSize: 10 }} />
                      新建模板段
                    </button>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </AprSheet>
  )
}
