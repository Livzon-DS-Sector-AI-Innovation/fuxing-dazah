import { Descriptions, Typography } from 'antd'

/** 员工信息档案分组（员工信息表自动带出），组内按此顺序展示 */
const PROFILE_GROUPS: { label: string; keys: string[] }[] = [
  { label: '个人信息', keys: ['性别', '学历', '毕业院校', '专业', '入职日期', '司龄'] },
  { label: '岗位信息', keys: ['职务', '岗位职级', '目前职级'] },
  {
    label: '历年职称评审结果',
    keys: ['2021年评定职级', '2022年评定职级', '2023年评定职级', '2024年评定职级', '2025年评定职级'],
  },
  {
    label: '评定参考',
    keys: ['近5年年终绩效考评结果', '2026年最高可申报（根据年限）'],
  },
]

/** 多行文本值（绩效结果可能含换行年份列表），整行展示并保留换行 */
const MULTILINE_KEYS = new Set(['近5年年终绩效考评结果'])

interface Props {
  profile?: Record<string, string> | null
}

export default function TitleReviewProfile({ profile }: Props) {
  if (!profile || Object.keys(profile).length === 0) return null
  const groups = PROFILE_GROUPS.map((g) => ({
    label: g.label,
    items: g.keys.filter((k) => profile[k] !== undefined),
  })).filter((g) => g.items.length > 0)
  if (groups.length === 0) return null

  return (
    <div>
      <Typography.Text strong>员工信息（自动补充自员工信息表）</Typography.Text>
      <div className="mt-2 space-y-3">
        {groups.map((g) => (
          <div key={g.label}>
            <Typography.Text type="secondary" className="text-[12px]">
              {g.label}
            </Typography.Text>
            <Descriptions column={2} size="small" bordered className="mt-1">
              {g.items.map((k) => {
                const multiline = MULTILINE_KEYS.has(k)
                return (
                  <Descriptions.Item key={k} label={k} span={multiline ? 2 : 1}>
                    <span className={multiline ? 'whitespace-pre-line' : undefined}>
                      {profile[k]}
                    </span>
                  </Descriptions.Item>
                )
              })}
            </Descriptions>
          </div>
        ))}
      </div>
    </div>
  )
}
