'use client'

import { Dropdown, Button } from 'antd'
import type { MenuProps } from 'antd'
import {
  RobotOutlined,
  FilePptOutlined,
  FileTextOutlined,
  EyeOutlined,
  EditOutlined,
  EllipsisOutlined,
} from '@ant-design/icons'

interface Props {
  hasCard: boolean
  hasContent: boolean
  onGenerateCard: () => void
  onGeneratePpt: () => void
  onGenerateSummary: () => void
  onViewDetail: () => void
  onEdit: () => void
}

export default function DocumentProcessingMenu({
  hasCard,
  hasContent,
  onGenerateCard,
  onGeneratePpt,
  onGenerateSummary,
  onViewDetail,
  onEdit,
}: Props) {
  const items: MenuProps['items'] = [
    {
      key: 'view',
      label: '查看详情',
      icon: <EyeOutlined />,
      onClick: onViewDetail,
    },
    {
      key: 'edit',
      label: '编辑元数据',
      icon: <EditOutlined />,
      onClick: onEdit,
    },
    { type: 'divider' },
    {
      key: 'generate-card',
      label: hasCard ? '重新生成卡片' : '生成知识卡片',
      icon: <RobotOutlined />,
      disabled: !hasContent,
      onClick: onGenerateCard,
    },
    {
      key: 'generate-ppt',
      label: '生成 PPT',
      icon: <FilePptOutlined />,
      disabled: !hasContent,
      onClick: onGeneratePpt,
    },
    {
      key: 'generate-summary',
      label: '生成摘要',
      icon: <FileTextOutlined />,
      disabled: !hasContent,
      onClick: onGenerateSummary,
    },
  ]

  return (
    <Dropdown menu={{ items }} trigger={['click']} placement="bottomRight">
      <Button size="small" icon={<EllipsisOutlined />}>
        处理
      </Button>
    </Dropdown>
  )
}
