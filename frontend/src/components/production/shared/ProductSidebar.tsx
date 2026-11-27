'use client'

import { useEffect, useRef, useState } from 'react'
import { Button, Empty, Input, Skeleton, Tooltip, Typography } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { fetchProductsClient } from '@/lib/api/production-client'
import type { Product } from '@/types/production'

const { Text } = Typography

// 生产模块统一的立体面板：顶部 1px 高光 + 145deg 渐变底 + 紫调柔和投影。
// CARD_STYLE 被批次管理/数据汇总/通知配置页共用，改动会一并生效。
export const CARD_STYLE: React.CSSProperties = {
  background: 'linear-gradient(145deg, #ffffff 0%, #fbfaf9 74%, #f6f4fb 100%)',
  border: '1px solid rgba(200, 196, 190, 0.72)',
  borderRadius: 18,
  boxShadow:
    'inset 0 1px 0 rgba(255, 255, 255, 0.96), 0 10px 25px -23px rgba(40, 33, 91, 0.48)',
}

interface Props {
  selectedId: string | null
  onSelect: (product: Product) => void
  onCreate?: () => void
  onEdit?: (product: Product) => void
  onDelete?: (product: Product) => void
}

export function ProductSidebar({ selectedId, onSelect, onCreate, onEdit, onDelete }: Props) {
  const [keyword, setKeyword] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const { data: products, isLoading } = useQuery({
    queryKey: ['production-products', keyword],
    queryFn: () => fetchProductsClient(keyword || undefined),
  })

  const hasAutoSelected = useRef(false)
  useEffect(() => {
    if (!hasAutoSelected.current && products && products.length > 0 && !selectedId) {
      hasAutoSelected.current = true
      onSelect(products[0])
    }
  }, [products, selectedId, onSelect])

  if (collapsed) {
    return (
      <div
        style={{
          ...CARD_STYLE,
          width: 48,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '10px 0',
          gap: 8,
        }}
      >
        <Tooltip title="展开产品列表" placement="right">
          <Button
            type="text"
            size="small"
            icon={<MenuUnfoldOutlined />}
            onClick={() => setCollapsed(false)}
          />
        </Tooltip>
        {selectedId && (
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: '#5645d4',
            }}
          />
        )}
      </div>
    )
  }

  return (
    <div
      style={{
        ...CARD_STYLE,
        width: 260,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          padding: '14px 14px 10px',
          borderBottom: '1px solid #ede9e4',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Text strong style={{ fontSize: 14, fontWeight: 650, flex: 1 }}>
          产品列表
        </Text>
        {products && products.length > 0 && (
          <span
            style={{
              padding: '1px 7px',
              borderRadius: 999,
              background: '#f6f5f4',
              boxShadow: 'inset 0 1px 0 #fff, inset 0 -1px 0 rgba(55,53,47,.05)',
              color: '#a4a097',
              fontSize: 11,
              fontVariantNumeric: 'tabular-nums',
              lineHeight: '16px',
            }}
          >
            {products.length}
          </span>
        )}
        {onCreate && (
          <Tooltip title="新建产品">
            <Button
              size="small"
              type="text"
              icon={<PlusOutlined />}
              onClick={onCreate}
              style={{ color: '#5645d4' }}
            />
          </Tooltip>
        )}
        <Tooltip title="收起">
          <Button
            size="small"
            type="text"
            icon={<MenuFoldOutlined />}
            onClick={() => setCollapsed(true)}
            style={{ color: '#787671' }}
          />
        </Tooltip>
      </div>

      {/* ── Search ── */}
      <div style={{ padding: '8px 14px' }}>
        <Input
          allowClear
          size="small"
          prefix={<SearchOutlined style={{ color: '#a4a097' }} />}
          placeholder="搜索产品名称或编码"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{ borderRadius: 8 }}
        />
      </div>

      {/* ── List ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 8px' }}>
        {isLoading ? (
          <div style={{ padding: '12px 6px' }}>
            <Skeleton active paragraph={{ rows: 6 }} />
          </div>
        ) : !products?.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={keyword ? '未找到匹配产品' : '暂无产品'}
            style={{ marginTop: 40 }}
          />
        ) : (
          products.map(p => {
            const isSelected = p.id === selectedId
            return (
              <div
                key={p.id}
                onClick={() => onSelect(p)}
                className={isSelected ? undefined : 'product-sidebar-item'}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '9px 10px',
                  marginBottom: 2,
                  borderRadius: 10,
                  cursor: 'pointer',
                  background: isSelected
                    ? 'linear-gradient(145deg, #f4f1fd 0%, #eae5f9 100%)'
                    : 'transparent',
                  border: isSelected
                    ? '1px solid rgba(86, 69, 212, 0.22)'
                    : '1px solid transparent',
                  boxShadow: isSelected
                    ? 'inset 0 1px 0 rgba(255,255,255,.9), 0 3px 8px -6px rgba(40,33,91,.6)'
                    : undefined,
                  transition: 'background 0.15s, border-color 0.15s, box-shadow 0.15s',
                  position: 'relative',
                }}
              >
                {/* Left accent bar when selected */}
                {isSelected && (
                  <div
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 7,
                      bottom: 7,
                      width: 3,
                      borderRadius: '0 3px 3px 0',
                      background: 'linear-gradient(180deg, #6b5ddb, #5645d4)',
                      boxShadow: '0 0 6px rgba(86,69,212,.45)',
                    }}
                  />
                )}
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 10,
                    background: isSelected
                      ? 'linear-gradient(145deg, #7b68e0, #5645d4)'
                      : 'linear-gradient(145deg, #fbfaf9, #f1f0ee)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 14,
                    fontWeight: 600,
                    color: isSelected ? '#ffffff' : '#787671',
                    flexShrink: 0,
                    boxShadow: isSelected
                      ? 'inset 0 1px 0 rgba(255,255,255,.34), 0 4px 8px -4px rgba(40,33,91,.7)'
                      : 'inset 0 1px 0 #ffffff, inset 0 -1px 0 rgba(55,53,47,.05)',
                    transition: 'background 0.15s, color 0.15s, box-shadow 0.15s',
                  }}
                >
                  {p.product_name.charAt(0)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: isSelected ? 600 : 500,
                      fontSize: 13,
                      color: '#1a1a1a',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {p.product_name}
                  </div>
                  {p.product_code && (
                    <div
                      style={{
                        fontSize: 11,
                        color: '#a4a097',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {p.product_code}
                    </div>
                  )}
                </div>
                {onEdit && (
                  <Tooltip title="编辑">
                    <Button
                      size="small"
                      type="text"
                      icon={<EditOutlined />}
                      onClick={e => {
                        e.stopPropagation()
                        onEdit(p)
                      }}
                      style={{ color: '#a4a097', flexShrink: 0 }}
                    />
                  </Tooltip>
                )}
                {onDelete && (
                  <Tooltip title="删除">
                    <Button
                      size="small"
                      type="text"
                      icon={<DeleteOutlined />}
                      onClick={e => {
                        e.stopPropagation()
                        onDelete(p)
                      }}
                      style={{ color: '#a4a097', flexShrink: 0 }}
                    />
                  </Tooltip>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
