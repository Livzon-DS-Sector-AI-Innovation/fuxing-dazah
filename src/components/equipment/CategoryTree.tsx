'use client'

import { useRouter } from 'next/navigation'
import { App, Tree, Button, Space, Popconfirm, Empty } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { EquipmentCategory } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteCategory } from '@/actions/equipment'

interface CategoryTreeProps {
  categories: EquipmentCategory[]
}

function NodeActions({ category }: { category: EquipmentCategory }) {
  const router = useRouter()
  const { message } = App.useApp()
  const { openCategoryDrawer } = useEquipmentStore()

  const handleDelete = async () => {
    try {
      await deleteCategory(category.id)
      message.success('删除分类成功')
      router.refresh()
    } catch (error: any) {
      message.error(error?.message || '删除分类失败')
    }
  }

  return (
    <div className="flex justify-between items-center group">
      <span style={{ color: '#1a1a1a', fontSize: 14 }}>{category.name}</span>
      <Space size={4} className="opacity-0 group-hover:opacity-100 transition-opacity">
        <Button
          type="text"
          size="small"
          icon={<EditOutlined style={{ fontSize: 12 }} />}
          onClick={(e) => {
            e.stopPropagation()
            openCategoryDrawer(category)
          }}
          style={{ color: '#5d5b54' }}
        />
        <Popconfirm
          title="确定删除此分类？"
          onConfirm={handleDelete}
          okText="确认"
          cancelText="取消"
        >
          <Button
            type="text"
            size="small"
            icon={<DeleteOutlined style={{ fontSize: 12 }} />}
            onClick={(e) => e.stopPropagation()}
            style={{ color: '#e03131' }}
          />
        </Popconfirm>
      </Space>
    </div>
  )
}

function buildTreeNodes(categories: EquipmentCategory[]): any[] {
  return categories.map((cat) => ({
    key: cat.id,
    title: <NodeActions category={cat} />,
    children: cat.children?.length ? buildTreeNodes(cat.children) : undefined,
  }))
}

export function CategoryTree({ categories }: CategoryTreeProps) {
  const {
    selectedCategory,
    setSelectedCategory,
    openCategoryDrawer
  } = useEquipmentStore()

  const treeData = buildTreeNodes(categories)

  if (!categories.length) {
    return (
      <div>
        <div style={{ marginBottom: 12 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={() => openCategoryDrawer()}
          >
            新增分类
          </Button>
        </div>
        <Empty
          description="暂无分类"
          styles={{ description: { color: '#787671' } }}
        />
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={() => openCategoryDrawer()}
        >
          新增分类
        </Button>
      </div>
      <Tree
        treeData={treeData}
        selectedKeys={selectedCategory ? [selectedCategory] : []}
        onSelect={(keys) => setSelectedCategory((keys[0] as string | undefined) ?? null)}
        defaultExpandAll
        style={{ background: 'transparent' }}
      />
    </div>
  )
}
