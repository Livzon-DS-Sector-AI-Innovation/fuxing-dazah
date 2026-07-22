'use client'

import { Select, Avatar } from 'antd'
import type { SelectProps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { fetchIdentityPersonnel } from '@/lib/api/identity'
import type { IdentityPersonnel } from '@/lib/api/identity'

interface Props {
  value?: string | string[]
  onChange?: (value: string | string[]) => void
  onSelect?: (userId: string) => void
  onDeselect?: (userId: string) => void
  placeholder?: string
  mode?: 'single' | 'multiple'
  size?: SelectProps['size']
  style?: React.CSSProperties
  excludeIds?: string[]
}

export function UserSelect({
  value,
  onChange,
  onSelect,
  onDeselect,
  placeholder = '搜索人员…',
  mode = 'single',
  size = 'middle',
  style,
  excludeIds = [],
}: Props) {
  const { data } = useQuery({
    queryKey: ['identity-personnel'],
    queryFn: () => fetchIdentityPersonnel({ limit: 9999 }),
    staleTime: 5 * 60 * 1000,
  })

  const personnel: IdentityPersonnel[] = (data?.items ?? [])
    .filter(p => !excludeIds.includes(p.id))

  const options = personnel.map(p => ({
    value: p.id,
    label: `${p.name}${p.department ? ` · ${p.department}` : ''}${p.employee_no ? ` (${p.employee_no})` : ''}`,
    user: p,
  }))

  return (
    <Select
      mode={mode === 'multiple' ? 'multiple' : undefined}
      value={value as any}
      onChange={onChange as any}
      onSelect={onSelect as any}
      onDeselect={onDeselect as any}
      placeholder={placeholder}
      size={size}
      style={style}
      showSearch
      filterOption={(input, option) =>
        (option?.label ?? '' as string).toLowerCase().includes(input.toLowerCase())
      }
      options={options}
      optionRender={({ data: opt }) => {
        const u = (opt as any).user as IdentityPersonnel | undefined
        if (!u) return <span>{opt.label}</span>
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Avatar
              src={u.avatar_url}
              size={28}
              style={{ flexShrink: 0, backgroundColor: 'var(--color-primary)', fontSize: 13 }}
            >
              {u.name.charAt(0)}
            </Avatar>
            <div>
              <div style={{ fontSize: 14, lineHeight: 1.4 }}>{u.name}</div>
              <div style={{ fontSize: 11, color: 'var(--color-steel)', lineHeight: 1.3 }}>
                {u.department || '—'}{u.employee_no ? ` · ${u.employee_no}` : ''}
              </div>
            </div>
          </div>
        )
      }}
    />
  )
}
