'use client'

import PageHeader from '@/components/hr/PageHeader'
import { Card, Row, Col } from 'antd'
import {
  FileTextOutlined,
  BellOutlined,
  BookOutlined,
  RobotOutlined,
  CalendarOutlined,
  TeamOutlined,
  HistoryOutlined,
  DatabaseOutlined,
  FileProtectOutlined,
  TableOutlined,
  UserSwitchOutlined,
  FolderOpenOutlined,
} from '@ant-design/icons'
import Link from 'next/link'

// 五区与侧边栏菜单对齐（menu-config 培训管理）：计划 → 执行 → 记录 → 资源 → 配置
const zones = [
  {
    key: 'plan',
    title: '培训计划',
    hint: '定全年安排',
    items: [
      {
        key: 'annual-plan',
        title: '年度培训计划',
        desc: '按部门管理年度培训计划，支持新建、编辑与导出',
        icon: <CalendarOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/annual-plan',
      },
    ],
  },
  {
    key: 'execution',
    title: '培训执行',
    hint: '发通知、组织培训',
    items: [
      {
        key: 'notification',
        title: '培训通知',
        desc: '填写培训信息，自动生成全套培训材料（培训通知、签到表、效果评估表），可发起问答考核',
        icon: <BellOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/notification',
      },
      {
        key: 'onboarding',
        title: '新员工入职培训',
        desc: '选择员工同时生成入职培训记录(Word)、岗前培训计划(Excel)和员工上岗评估表，支持打印',
        icon: <FileTextOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/onboarding',
      },
    ],
  },
  {
    key: 'records',
    title: '培训记录',
    hint: '查台账与成绩',
    items: [
      {
        key: 'ledger',
        title: '培训台账',
        desc: '按部门与培训内容管理总台账、录入考核成绩，可查/导出个人纸质台账',
        icon: <BookOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/ledger',
      },
      {
        key: 'qa-assessments',
        title: '考核历史',
        desc: '问答考核场次与成绩的历史查询',
        icon: <HistoryOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/qa-assessments',
      },
    ],
  },
  {
    key: 'resources',
    title: '培训资源',
    hint: '题库与 SOP 材料',
    items: [
      {
        key: 'question-bank',
        title: '题库',
        desc: '各岗位共享题库，按部门/岗位筛选题目',
        icon: <DatabaseOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/question-bank',
      },
      {
        key: 'ai-exam',
        title: 'AI 出题',
        desc: '上传培训文件，AI 自动识别内容并生成试卷，支持导出 Word',
        icon: <RobotOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/ai-exam',
      },
      {
        key: 'sop-master',
        title: 'SOP培训登记表',
        desc: 'SOP 培训登记与转培训管理',
        icon: <FileProtectOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/sop-master',
      },
      {
        key: 'sop-secondary',
        title: 'SOP培训二级表',
        desc: '二级表批量转培训、合并生成培训材料',
        icon: <TableOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/sop-secondary',
      },
    ],
  },
  {
    key: 'config',
    title: '培训配置',
    hint: '人员与目录维护',
    items: [
      {
        key: 'trainers',
        title: '内训师',
        desc: '内训师台账与部门培训人员管理',
        icon: <UserSwitchOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/trainers',
      },
      {
        key: 'personnel',
        title: '培训人员名单',
        desc: '脱敏版员工名册（不含身份证/学校/专业/联系方式等个人信息），供培训组织使用',
        icon: <TeamOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/personnel',
      },
      {
        key: 'sop-catalog',
        title: 'SOP目录',
        desc: 'SOP 培训大类与岗位分类的目录维护',
        icon: <FolderOpenOutlined className="text-2xl text-[var(--color-primary)]" />,
        path: '/hr/training/sop-catalog',
      },
    ],
  },
]

export default function TrainingPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="培训管理" description="计划 → 执行 → 记录 → 资源 → 配置，与左侧菜单五区一致" />

      {zones.map((zone) => (
        <section key={zone.key} className="space-y-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[16px] font-semibold text-[var(--color-charcoal)]">
              {zone.title}
            </h2>
            <span className="text-[13px] text-[var(--color-stone)]">{zone.hint}</span>
          </div>
          <Row gutter={[16, 16]}>
            {zone.items.map((mod) => (
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
        </section>
      ))}
    </div>
  )
}
