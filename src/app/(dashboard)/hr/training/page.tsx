'use client'

import { Card, Row, Col } from 'antd'
import {
  FileTextOutlined,
  FormOutlined,
  BellOutlined,
  BookOutlined,
  RobotOutlined,
  CalendarOutlined,
} from '@ant-design/icons'
import Link from 'next/link'

const modules = [
  {
    key: 'annual-plan',
    title: '年度培训计划',
    desc: '按部门管理年度培训计划，支持新建、编辑与导出',
    icon: <CalendarOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/annual-plan',
  },
  {
    key: 'onboarding',
    title: '新员工入职培训',
    desc: '选择员工同时生成入职培训记录(Word)、岗前培训计划(Excel)和员工上岗评估表，支持打印',
    icon: <FileTextOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/onboarding',
  },
  {
    key: 'notification',
    title: '培训通知',
    desc: '填写培训信息，自动生成培训通知、签到表和效果评估表',
    icon: <BellOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/notification',
  },
  {
    key: 'sign-in',
    title: '培训签到表',
    desc: '填写培训信息，选择受训部门和人员，生成培训签到表',
    icon: <FormOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/sign-in',
  },
  {
    key: 'ledger',
    title: '培训台账',
    desc: '查看员工培训台账，预填员工基本信息，支持导出',
    icon: <BookOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/ledger',
  },
  {
    key: 'ai-exam',
    title: 'AI 出题',
    desc: '上传培训文件，AI 自动识别内容并生成试卷，支持导出 Word',
    icon: <RobotOutlined className="text-2xl text-[var(--color-primary)]" />,
    path: '/hr/training/ai-exam',
  },
]

export default function TrainingPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)] mb-2">
          培训管理
        </h1>
        <p className="text-[14px] text-[var(--color-steel)]">
          员工培训相关业务管理
        </p>
      </div>

      <Row gutter={[16, 16]}>
        {modules.map((mod) => (
          <Col xs={24} sm={12} lg={8} key={mod.key}>
            <Link href={mod.path}>
              <Card
                hoverable
                className="h-full cursor-pointer transition-shadow hover:shadow-md"
              >
                <div className="flex items-start gap-4">
                  <div className="mt-1">{mod.icon}</div>
                  <div>
                    <h3 className="text-[16px] font-semibold text-[var(--color-charcoal)] mb-1">
                      {mod.title}
                    </h3>
                    <p className="text-[14px] text-[var(--color-steel)] leading-relaxed">
                      {mod.desc}
                    </p>
                  </div>
                </div>
              </Card>
            </Link>
          </Col>
        ))}
      </Row>
    </div>
  )
}
