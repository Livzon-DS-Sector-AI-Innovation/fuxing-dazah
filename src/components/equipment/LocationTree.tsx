'use client'

import { useRouter } from 'next/navigation'
import { App, Tree, Button, Space, Popconfirm, Empty } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { Location } from '@/types/equipment'
import { useEquipmentStore } from '@/stores/equipment'
import { deleteLocation } from '@/actions/equipment'

interface LocationTreeProps {
  locations: Location[]
}

function NodeActions({ location }: { location: Location }) {
  const router = useRouter()
  const { message } = App.useApp()
  const { openLocationDrawer } = useEquipmentStore()

  const handleDelete = async () => {
    try {
      await deleteLocation(location.id)
      message.success('删除位置成功')
      router.refresh()
    } catch (error: any) {
      message.error(error?.message || '删除位置失败')
    }
  }

  return (
    <div className="flex justify-between items-center">
      <span>{location.name}</span>
      <Space>
        <Button
          type="text"
          size="small"
          icon={<EditOutlined />}
          onClick={(e) => {
            e.stopPropagation()
            openLocationDrawer(location)
          }}
        />
        <Popconfirm
          title="确定删除此位置？"
          onConfirm={handleDelete}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>
      </Space>
    </div>
  )
}

function buildTreeNodes(locations: Location[]): any[] {
  return locations.map((loc) => ({
    key: loc.id,
    title: <NodeActions location={loc} />,
    children: loc.children?.length ? buildTreeNodes(loc.children) : undefined,
  }))
}

export function LocationTree({ locations }: LocationTreeProps) {
  const {
    selectedLocation,
    setSelectedLocation,
    openLocationDrawer
  } = useEquipmentStore()

  const treeData = buildTreeNodes(locations)

  if (!locations.length) {
    return (
      <div>
        <div className="mb-2">
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={() => openLocationDrawer()}
          >
            新增位置
          </Button>
        </div>
        <Empty description="暂无位置" />
      </div>
    )
  }

  return (
    <div>
      <div className="mb-2">
        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={() => openLocationDrawer()}
        >
          新增位置
        </Button>
      </div>
      <Tree
        treeData={treeData}
        selectedKeys={selectedLocation ? [selectedLocation] : []}
        onSelect={(keys) => setSelectedLocation((keys[0] as string | undefined) ?? null)}
        defaultExpandAll
      />
    </div>
  )
}
