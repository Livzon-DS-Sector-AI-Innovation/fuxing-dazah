'use client'

import type { ColumnsType } from 'antd/es/table'
import { Button, Popconfirm, Table } from 'antd'

import type { SopCatalogItem } from '@/types/hr'
import { NO_POSITION } from './sopGroups'
import styles from './sop-catalog.module.css'

/** 把命中的片段标出来：搜索词可能落在不显眼的 SOP 编号上，不标的话看不出这行为什么被搜到 */
function Highlight({ text, keyword }: { text: string; keyword: string }) {
  const index = text.toLowerCase().indexOf(keyword)
  // 个别字符转小写后长度会变（如 İ），此时按不命中处理，免得截错位置
  if (!keyword || index === -1 || text.toLowerCase().length !== text.length) return <>{text}</>
  return (
    <>
      {text.slice(0, index)}
      <mark className={styles.mark}>{text.slice(index, index + keyword.length)}</mark>
      {text.slice(index + keyword.length)}
    </>
  )
}

interface SopSearchTableProps {
  items: SopCatalogItem[]
  /** 已 trim 并转小写的关键词 */
  keyword: string
  /** 「全部部门」视图下要显示部门列 */
  showDepartment: boolean
  canManage: boolean
  deletingIds: string[]
  onDelete: (item: SopCatalogItem) => void
}

/** 搜索态：命中的条目平铺成一张表，一行一条，部门 / 岗位 / 培训类别一眼可比 */
export default function SopSearchTable({
  items,
  keyword,
  showDepartment,
  canManage,
  deletingIds,
  onDelete,
}: SopSearchTableProps) {
  const columns: ColumnsType<SopCatalogItem> = []
  if (showDepartment) {
    columns.push({
      title: '部门',
      dataIndex: 'department',
      width: 170,
      render: (department: string | null) => department || '—',
    })
  }
  columns.push(
    {
      title: '岗位',
      dataIndex: 'position_name',
      width: 220,
      render: (position: string | null) => (position
        ? <Highlight text={position} keyword={keyword} />
        : <span className={styles.cellMuted}>{NO_POSITION}</span>),
    },
    {
      title: '培训类别',
      dataIndex: 'category',
      width: 220,
      render: (category: string | null) => (category
        ? <Highlight text={category} keyword={keyword} />
        : <span className={styles.cellPlaceholder}>—</span>),
    },
    {
      title: '文件名称',
      dataIndex: 'file_name',
      render: (fileName: string) => (
        <span className="font-medium text-[var(--color-ink)]">
          <Highlight text={fileName} keyword={keyword} />
        </span>
      ),
    },
    {
      title: 'SOP 编号',
      dataIndex: 'sop_number',
      width: 150,
      render: (sopNumber: string | null) => (sopNumber
        ? <span className="whitespace-nowrap tabular-nums"><Highlight text={sopNumber} keyword={keyword} /></span>
        : <span className={styles.cellPlaceholder}>—</span>),
    },
  )
  if (canManage) {
    columns.push({
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, item) => (
        <Popconfirm
          title={`删除「${item.file_name}」？`}
          description={item.position_name
            ? '删除后不可恢复，该岗位的入职培训里不再包含这条内容。'
            : '删除后不可恢复。'}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => onDelete(item)}
        >
          <Button
            type="text"
            size="small"
            danger
            loading={deletingIds.includes(item.id)}
            aria-label={`删除「${item.file_name}」`}
          >
            删除
          </Button>
        </Popconfirm>
      ),
    })
  }

  return (
    <Table<SopCatalogItem>
      className={styles.table}
      rowKey="id"
      size="middle"
      columns={columns}
      dataSource={items}
      pagination={{
        defaultPageSize: 20,
        showSizeChanger: false,
        showTotal: (total) => `共 ${total} 条`,
      }}
    />
  )
}
