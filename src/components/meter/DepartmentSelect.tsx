'use client'

import { useEffect, useState } from 'react'
import { App, Button, Input, Select, Space } from 'antd'
import { PlusOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { getDepartments } from '@/actions/meter'

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

  const handleAdd = () => {
    const name = newName.trim()
    if (!name) { message.warning('请输入部门名称'); return }
    if (departments.includes(name)) { message.warning('该部门已存在'); return }
    setDepartments(prev => [...prev, name])
    onChange?.(name)
    setNewName('')
    setAdding(false)
    message.success(`已添加部门: ${name}`)
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
      showSearch
      options={departments.map(d => ({ label: d, value: d }))}
      filterOption={(input, option) =>
        (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
      }
      popupRender={dropdownRender}
    />
  )
}
