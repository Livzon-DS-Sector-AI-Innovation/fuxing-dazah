'use client'

import { Avatar, Select, Typography } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import type { Personnel } from '@/types/equipment-personnel'
import type { SelectProps } from 'antd'

const { Text } = Typography

const AV = ['#5645d4', '#7b3ff2', '#dd5b00', '#0075de', '#1aae39', '#2a9d99']

function avColor(name: string) {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return AV[Math.abs(h) % AV.length]
}

interface Props extends Omit<SelectProps, 'options' | 'optionRender' | 'children'> {
  personnel: Personnel[]
}

export function PersonnelSelect({ personnel, ...rest }: Props) {
  return (
    <Select
      {...rest}
      showSearch={{ optionFilterProp: 'label' }}
      popupMatchSelectWidth={false}
      options={personnel.map(p => ({
        label: `${p.name}${p.department ? ' · ' + p.department : ''}`,
        value: p.user_id || p.id,
      }))}
      optionRender={o => {
        const p = personnel.find(pe => (pe.user_id || pe.id) === o.value)
        if (!p) return <Text>{o.label}</Text>
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Avatar
              size={28}
              src={p.avatar_url || undefined}
              style={{
                backgroundColor: p.avatar_url ? 'transparent' : avColor(p.name),
                flexShrink: 0,
                fontSize: 11,
                fontWeight: 700,
              }}
              icon={!p.avatar_url ? <UserOutlined /> : undefined}
            >
              {!p.avatar_url ? p.name.charAt(0) : undefined}
            </Avatar>
            <div style={{ lineHeight: 1.3 }}>
              <Text style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</Text>
              {p.department && (
                <Text type="secondary" style={{ fontSize: 11, display: 'block' }}>
                  {p.department}{p.employee_no ? ` · ${p.employee_no}` : ''}
                </Text>
              )}
            </div>
          </div>
        )
      }}
    />
  )
}
