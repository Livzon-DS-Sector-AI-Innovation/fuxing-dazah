'use client'

import { useState } from 'react'
import { usePermission } from '@/hooks/usePermission'
import { Typography, Divider, Empty, Button, Space, Table, Tag } from 'antd'
import { ExperimentOutlined, FileTextOutlined, HistoryOutlined } from '@ant-design/icons'
import Link from 'next/link'
import { LcUploader, LcReportView } from '@/components/quality'
import type { UploadLcResponse } from '@/types/quality'

const { Title, Paragraph } = Typography

export default function QualityPage() {
  const { hasPermission } = usePermission()
  const canUpload = hasPermission('quality:lc:upload')
  const [result, setResult] = useState<UploadLcResponse | null>(null)

  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>
        <ExperimentOutlined /> 液相计算表解析
      </Title>
      <Paragraph type="secondary" style={{ marginBottom: 24 }}>
        上传液相计算表 Excel，自动解析峰面积、计算结果和质量标准，执行合格/超趋势判定。
      </Paragraph>

      {canUpload ? (
        <LcUploader onResult={setResult} />
      ) : (
        <Paragraph type="secondary">没有上传液相计算表的权限</Paragraph>
      )}

      {result && result.record_id && result.task_link?.task_id && (
        <Space style={{ marginTop: 12 }}>
          <Link href={`/quality/task/${result.task_link.task_id}`}>
            <Button type="primary" icon={<FileTextOutlined />}>
              去任务确认归入（已自动填入待确认）
            </Button>
          </Link>
          <Link href="/quality/history">
            <Button icon={<HistoryOutlined />}>历史记录</Button>
          </Link>
        </Space>
      )}
      {result && result.record_id && !result.task_link?.task_id && (
        <Space style={{ marginTop: 12 }}>
          <Link href="/quality/task">
            <Button type="primary" icon={<FileTextOutlined />}>
              去检验填报建任务归入
            </Button>
          </Link>
          <Link href="/quality/history">
            <Button icon={<HistoryOutlined />}>历史记录</Button>
          </Link>
        </Space>
      )}
      {result && result.record_id && !result.task_link?.task_id && (
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          未找到同批号任务：建任务后重新上传计算表（或在任务详情上传）即可自动归入；报告单在任务填报完成并复核通过后生成。
        </Paragraph>
      )}

      {result && (
        <>
          <Divider />
          {result.components ? (
            <div>
              <Paragraph strong>解析组分结果（模板配置驱动）</Paragraph>
              <Table
                rowKey="name"
                size="small"
                pagination={false}
                dataSource={(result.components || []).map((c) => ({ ...c, key: c.name }))}
                columns={[
                  { title: '组分', dataIndex: 'name', key: 'name' },
                  {
                    title: '报告值', dataIndex: 'report_value', key: 'report_value',
                    render: (v: number | null) => v != null ? `${v}%` : <Tag color="orange">未检出/未填</Tag>,
                  },
                ]}
              />
            </div>
          ) : (
            <LcReportView report={result.report} />
          )}
        </>
      )}

      {!result && (
        <div style={{ marginTop: 48, textAlign: 'center' }}>
          <Empty description="请上传液相计算表 Excel 文件开始解析" />
        </div>
      )}

    </div>
  )
}
