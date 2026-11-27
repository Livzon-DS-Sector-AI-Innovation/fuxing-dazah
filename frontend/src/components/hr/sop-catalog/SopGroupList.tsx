'use client'

import { Button, Collapse, Popconfirm, Popover } from 'antd'
import { ClearOutlined } from '@ant-design/icons'

import type { SopCatalogItem } from '@/types/hr'
import { groupLabel, type DeptSection, type SopGroup } from './sopGroups'
import styles from './sop-catalog.module.css'

/** 分组头里最多直接显示几个培训类别，其余折叠成「+N」 */
const CHIP_LIMIT = 3

/** 培训类别预览：折叠显示是为了让分组头保持单行 */
function CategoryChips({ categories }: { categories: string[] }) {
  const rest = categories.length - CHIP_LIMIT
  return (
    <>
      {categories.slice(0, CHIP_LIMIT).map((category) => (
        <span key={category} className={styles.chip}>{category}</span>
      ))}
      {rest > 0 && (
        <Popover
          title="培训类别"
          placement="topRight"
          content={(
            <span className="flex max-w-xs flex-wrap gap-1">
              {categories.map((category) => <span key={category} className={styles.chip}>{category}</span>)}
            </span>
          )}
        >
          <span className={`${styles.chip} ${styles.chipMore} cursor-default`}>+{rest}</span>
        </Popover>
      )}
    </>
  )
}

interface GroupItemsProps {
  group: SopGroup
  canManage: boolean
  deletingIds: string[]
  clearing: boolean
  highlightItemId: string | null
  onDelete: (item: SopCatalogItem) => void
  onClear: (group: SopGroup) => void
}

/** 展开后的条目表。清空按钮放在表内而不是分组头上：删整组之前先看到要删的是什么 */
function GroupItems({ group, canManage, deletingIds, clearing, highlightItemId, onDelete, onClear }: GroupItemsProps) {
  const label = groupLabel(group.position)
  return (
    <div>
      <div className={styles.itemsBar}>
        <span className={styles.itemsMeta}>共 {group.items.length} 条 SOP</span>
        {canManage && (
          <Popconfirm
            title={`清空「${label}」的培训内容？`}
            description={group.position
              ? `将删除该岗位下的 ${group.items.length} 条 SOP，入职培训里不再可选。岗位本身不会被删除。`
              : `将删除未指定岗位的 ${group.items.length} 条 SOP，入职培训里不再可选。`}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onClear(group)}
          >
            <Button type="text" size="small" danger icon={<ClearOutlined />} loading={clearing}>
              清空培训内容
            </Button>
          </Popconfirm>
        )}
      </div>

      <table className={styles.itemsTable}>
        <colgroup>
          <col className={styles.colCategory} />
          <col />
          <col className={styles.colSop} />
          {canManage && <col className={styles.colAction} />}
        </colgroup>
        <thead>
          <tr>
            <th scope="col">培训类别</th>
            <th scope="col">文件名称</th>
            <th scope="col" className={styles.cellSop}>SOP 编号</th>
            {canManage && <th scope="col" className={styles.cellAction}>操作</th>}
          </tr>
        </thead>
        <tbody>
          {group.items.map((item) => (
            <tr
              key={item.id}
              data-sop-item={item.id}
              className={item.id === highlightItemId ? styles.itemNew : undefined}
            >
              <td>{item.category || <span className={styles.cellPlaceholder}>—</span>}</td>
              <td>{item.file_name}</td>
              <td className={styles.cellSop}>{item.sop_number || <span className={styles.cellPlaceholder}>—</span>}</td>
              {canManage && (
                <td className={styles.cellAction}>
                  <Popconfirm
                    title={`删除「${item.file_name}」？`}
                    description={group.position
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
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface SopGroupListProps {
  sections: DeptSection[]
  expandedKeys: string[]
  onExpandedChange: (keys: string[]) => void
  canManage: boolean
  deletingIds: string[]
  clearingKey: string | null
  highlightItemId: string | null
  onDelete: (item: SopCatalogItem) => void
  onClear: (group: SopGroup) => void
}

/** 浏览态：按部门分节，节内一个岗位一行，点行展开该岗位的培训条目 */
export default function SopGroupList({
  sections,
  expandedKeys,
  onExpandedChange,
  canManage,
  deletingIds,
  clearingKey,
  highlightItemId,
  onDelete,
  onClear,
}: SopGroupListProps) {
  // 只看一个部门时右栏标题已经是部门名，不必再重复一节标题
  const showSectionHead = sections.length > 1
  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <section key={section.department} aria-label={section.department}>
          {showSectionHead && (
            <div className={styles.sectionHead}>
              <h3 className={styles.sectionTitle}>{section.department}</h3>
              <span className={styles.sectionMeta}>
                {section.groups.length} 个岗位 · {section.count} 条 SOP
              </span>
            </div>
          )}
          <Collapse
            className={styles.collapse}
            bordered={false}
            destroyOnHidden
            activeKey={expandedKeys}
            onChange={onExpandedChange}
            items={section.groups.map((group) => ({
              key: group.key,
              label: (
                // 分组头里不放任何按钮：整行都是展开/收起的点击区
                <div className={styles.groupHead}>
                  <span className={styles.groupName} title={groupLabel(group.position)}>
                    {groupLabel(group.position)}
                  </span>
                  {group.position === null && (
                    <span className={styles.groupHint}>目录文档导入的条目未关联岗位</span>
                  )}
                  <span className={styles.groupChips}>
                    <CategoryChips categories={group.categories} />
                  </span>
                  <span className={styles.groupCount}>{group.items.length} 条</span>
                </div>
              ),
              children: (
                <GroupItems
                  group={group}
                  canManage={canManage}
                  deletingIds={deletingIds}
                  clearing={clearingKey === group.key}
                  highlightItemId={highlightItemId}
                  onDelete={onDelete}
                  onClear={onClear}
                />
              ),
            }))}
          />
        </section>
      ))}
    </div>
  )
}
