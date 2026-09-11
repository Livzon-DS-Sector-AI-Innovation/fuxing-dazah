'use client'

import { Select, Avatar } from 'antd'
import type { DefaultOptionType, SelectProps } from 'antd/es/select'
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
  allowClear?: boolean
  maxTagCount?: SelectProps['maxTagCount']
  maxTagPlaceholder?: SelectProps['maxTagPlaceholder']
  groupSelectedFirst?: boolean
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
  allowClear = false,
  maxTagCount,
  maxTagPlaceholder,
  groupSelectedFirst = false,
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

  // 已选人员置顶分组，长名单中可直接点选取消，无需翻找
  let dropdownOptions: DefaultOptionType[] = options
  if (
    groupSelectedFirst &&
    mode === 'multiple' &&
    Array.isArray(value) &&
    value.length > 0
  ) {
    const byId = new Map<string, DefaultOptionType>(
      options.map(o => [o.value, o] as [string, DefaultOptionType]),
    )
    const selected = value
      .map(id => byId.get(id))
      .filter((o): o is DefaultOptionType => Boolean(o))
    const rest = options.filter(o => !value.includes(o.value))
    dropdownOptions = [
      ...(selected.length > 0
        ? [{ label: `已选（${selected.length}）`, options: selected }]
        : []),
      ...(rest.length > 0 ? [{ label: '全部人员', options: rest }] : []),
    ]
  }

  return (
    <Select
      mode={mode === 'multiple' ? 'multiple' : undefined}
      value={
        mode === 'multiple' ? (value as string[]) : (value as string | undefined)
      }
      onChange={v => onChange?.(v as string | string[])}
      onSelect={userId => onSelect?.(String(userId))}
      onDeselect={userId => onDeselect?.(String(userId))}
      placeholder={placeholder}
      size={size}
      style={style}
      allowClear={allowClear}
      maxTagCount={maxTagCount}
      maxTagPlaceholder={maxTagPlaceholder}
      showSearch
      filterOption={(input, option) =>
        String(option?.label ?? '')
          .toLowerCase()
          .includes(input.toLowerCase())
      }
      options={dropdownOptions}
      optionRender={({ data: opt }) => {
        const u = (opt as { user?: IdentityPersonnel }).user
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
