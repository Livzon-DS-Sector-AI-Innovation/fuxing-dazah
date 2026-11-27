'use client'

import { useEffect, useState } from 'react'
import { App, Button, Input, Select, Space } from 'antd'
import { PlusOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { createDepartment, getDepartments } from '@/actions/meter'

interface Props {
  value?: string
  onChange?: (value: string) => void
  placeholder?: string
  source: 'instrument' | 'gas_detector'
  allowAdd?: boolean
}

export function DepartmentSelect({ value, onChange, placeholder = '选择部门', source, allowAdd = true }: Props) {
  const { message } = App.useApp()
  const [departments, setDepartments] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')

  useEffect(() => {
    getDepartments(source).then(data => {
      setDepartments(data.map(d => d.name))
    }).catch(() => {})
  }, [source])

  // 真新增：落库到 departments 表（部门筛选下拉/部门管理页/自动提醒配置都读它），
  // 仅改本地 state 会在刷新后消失且提示误导成功
  const handleAdd = async () => {
    const name = newName.trim()
    if (!name) { message.warning('请输入部门名称'); return }
    if (departments.includes(name)) { message.warning('该部门已存在'); return }
    try {
      await createDepartment({ source, name, heads: [] })
      setDepartments(prev => [...prev, name])
      onChange?.(name)
      setNewName('')
      setAdding(false)
      message.success(`已添加部门: ${name}`)
    } catch (e) {
      // 没有部门管理权限时仍把名称填入表单（记录可保存），但不承诺已加入部门列表，
      // 否则普通编辑者遇到新部门会被完全卡住
      onChange?.(name)
      setNewName('')
      setAdding(false)
      message.warning(
        e instanceof Error && e.message
          ? `未加入部门列表：${e.message}`
          : '已填入部门名，但未加入部门列表（需要部门管理权限）'
      )
    }
  }

  const dropdownRender = (menu: React.ReactNode) => (
    <>
      {menu}
      {allowAdd && (
        <div style={{ borderTop: '1px solid #f0f0f0', padding: 4 }}>
          {adding ? (
            <Space style={{ padding: '4px 8px', width: '100%' }}>
              <Input
                size="small"
                placeholder="输入新部门名称"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onPressEnter={handleAdd}
                autoFocus
                style={{ flex: 1 }}
              />
              <Button size="small" type="text" icon={<CheckOutlined />} onClick={handleAdd} />
              <Button size="small" type="text" icon={<CloseOutlined />} onClick={() => { setAdding(false); setNewName('') }} />
            </Space>
          ) : (
            <Button
              type="link"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setAdding(true)}
              style={{ width: '100%', textAlign: 'left' }}
            >
              新增部门
            </Button>
          )}
        </div>
      )}
    </>
  )

  return (
    <Select
      value={value || undefined}
      onChange={onChange}
      placeholder={placeholder}
      allowClear
      showSearch={{
        filterOption: (input, option) =>
          (option?.label as string)?.toLowerCase().includes(input.toLowerCase()),
      }}
      options={departments.map(d => ({ label: d, value: d }))}
      popupRender={dropdownRender}
    />
  )
}
