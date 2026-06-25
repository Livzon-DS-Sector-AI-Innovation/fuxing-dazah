'use client'

import { useState } from 'react'
import { App, Button, Modal, Select, Tabs } from 'antd'
import { PlusOutlined, SyncOutlined, TeamOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchRoles } from '@/lib/api/equipment-personnel'
import { refreshFeishu, assignRoles as assignRolesAction } from '@/actions/equipment-personnel'
import { PersonnelTable } from './PersonnelTable'
import { RoleManagePanel } from './RoleManagePanel'
import { PersonnelDrawer } from './PersonnelDrawer'
import { PersonnelCategoryDrawer } from './PersonnelCategoryDrawer'
import type { EquipmentRole, Personnel } from '@/types/equipment-personnel'

export function PersonnelPage() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'personnel' | 'roles'>('personnel')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const [rolePersonnel, setRolePersonnel] = useState<Personnel | null>(null)
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
  const [roleSaving, setRoleSaving] = useState(false)

  const [categoryPersonnel, setCategoryPersonnel] = useState<Personnel | null>(null)

  const { data: roles = [] } = useQuery({
    queryKey: ['equipment-roles'],
    queryFn: fetchRoles,
  })

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshFeishu()
      message.success('飞书信息刷新完成')
      queryClient.invalidateQueries({ queryKey: ['equipment-personnel'] })
    } catch {
      message.error('飞书信息刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  const openRoleModal = (personnel: Personnel) => {
    setRolePersonnel(personnel)
    setSelectedRoleIds(personnel.roles.map(r => r.id))
  }

  const handleRoleSave = async () => {
    if (!rolePersonnel) return
    setRoleSaving(true)
    try {
      await assignRolesAction(rolePersonnel.id, { role_ids: selectedRoleIds })
      message.success('角色已更新')
      queryClient.invalidateQueries({ queryKey: ['equipment-personnel'] })
      setRolePersonnel(null)
    } catch {
      message.error('保存失败')
    } finally {
      setRoleSaving(false)
    }
  }

  const tabItems = [
    {
      key: 'personnel',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <TeamOutlined style={{ fontSize: 15 }} />
          人员管理
        </span>
      ),
      children: (
        <div>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 20,
          }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setDrawerOpen(true)}
                style={{
                  borderRadius: 8, height: 36,
                  background: '#5645d4', borderColor: '#5645d4',
                  fontWeight: 600, fontSize: 13,
                  boxShadow: 'none',
                }}
              >
                添加人员
              </Button>
              <Button
                icon={<SyncOutlined spin={refreshing} />}
                onClick={handleRefresh}
                loading={refreshing}
                style={{
                  borderRadius: 8, height: 36, fontWeight: 500,
                }}
              >
                刷新飞书
              </Button>
            </div>
          </div>
          <PersonnelTable
            roles={roles}
            onAddClick={() => setDrawerOpen(true)}
            onRoleClick={openRoleModal}
            onCategoryClick={setCategoryPersonnel}
          />
        </div>
      ),
    },
    {
      key: 'roles',
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <SafetyCertificateOutlined style={{ fontSize: 15 }} />
          角色管理
        </span>
      ),
      children: <RoleManagePanel roles={roles} />,
    },
  ]

  return (
    <div style={{ paddingBottom: 40 }}>
      {/* 页面头部 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{
          fontSize: 22, fontWeight: 600, color: '#1a1a1a',
          margin: 0, marginBottom: 4, lineHeight: 1.3,
        }}>
          人员配置
        </h2>
        <p style={{ fontSize: 14, color: '#787671', margin: 0, lineHeight: 1.5 }}>
          角色权限管理 · 人员分配 · 分类约束 · 飞书同步
        </p>
      </div>

      {/* Tab 内容包进白色卡片 */}
      <div style={{
        background: '#ffffff',
        borderRadius: 12,
        border: '1px solid #e5e3df',
        padding: '4px 24px 24px',
      }}>
        <Tabs
          activeKey={activeTab}
          onChange={key => setActiveTab(key as 'personnel' | 'roles')}
          items={tabItems}
          tabBarStyle={{
            borderBottom: '1px solid #ede9e4',
            marginBottom: 20,
            paddingLeft: 0,
          }}
          tabBarGutter={32}
        />
      </div>

      <PersonnelDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        roles={roles}
      />

      <Modal
        open={!!rolePersonnel}
        onOk={handleRoleSave}
        onCancel={() => setRolePersonnel(null)}
        confirmLoading={roleSaving}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ style: { borderRadius: 8, fontWeight: 600 } }}
        title={`分配角色 — ${rolePersonnel?.name ?? ''}`}
      >
        <Select
          mode="multiple"
          value={selectedRoleIds}
          onChange={(v) => setSelectedRoleIds(v)}
          style={{ width: '100%' }}
          placeholder="选择角色"
          options={roles.filter(r => r.is_active).map(r => ({
            label: r.name,
            value: r.id,
          }))}
        />
      </Modal>

      <PersonnelCategoryDrawer
        open={!!categoryPersonnel}
        onClose={() => setCategoryPersonnel(null)}
        personnelId={categoryPersonnel?.id ?? ''}
        personnelName={categoryPersonnel?.name ?? ''}
        roles={roles}
        existingCategories={categoryPersonnel?.categories ?? []}
      />
    </div>
  )
}
