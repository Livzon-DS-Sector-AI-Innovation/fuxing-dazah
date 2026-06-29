'use client'

import { Card, Input, Typography, Tag, Descriptions, Empty } from 'antd'
import type { NodeResultEntry } from '@/types/safety'

const { TextArea } = Input
const { Text, Title } = Typography

interface Props {
  runInputs: string
  setRunInputs: (v: string) => void
  runResult: Record<string, unknown> | null
  running: boolean
}

export function WorkflowRunPanel({
  runInputs,
  setRunInputs,
  runResult,
  running,
}: Props) {
  const outputs = runResult?.outputs as Record<string, unknown> | undefined
  const nodeResults = runResult?.node_results as Record<string, NodeResultEntry> | undefined
  const totalTokens = runResult?.total_tokens as number | undefined
  const totalSteps = runResult?.total_steps as number | undefined
  const elapsedTime = runResult?.elapsed_time as number | undefined
  const status = runResult?.status as string | undefined
  const errorMsg: string | null = (runResult?.error_message as string) || (runResult?.error != null ? String(runResult.error) : null)

  return (
    <Card
      title="运行面板"
      size="small"
      extra={
        runResult ? (
          <Tag color={status === 'succeeded' ? 'green' : 'red'}>
            {status || 'completed'}
          </Tag>
        ) : null
      }
    >
      <div style={{ marginBottom: 12 }}>
        <Text strong>输入变量 (JSON)</Text>
        <TextArea
          value={runInputs}
          onChange={(e) => setRunInputs(e.target.value)}
          rows={4}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
          placeholder='{"department": "生产部", "position": "操作工"}'
        />
      </div>

      {runResult && !errorMsg && (
        <div style={{ marginTop: 12 }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="状态">
              <Tag color={status === 'succeeded' ? 'green' : 'orange'}>
                {status || '-'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="耗时">
              {elapsedTime != null ? `${elapsedTime}s` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Tokens">{totalTokens ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="步骤">{totalSteps ?? '-'}</Descriptions.Item>
          </Descriptions>

          {nodeResults && Object.keys(nodeResults).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Text strong>节点执行详情</Text>
              {Object.entries(nodeResults).map(([nodeId, result]) => (
                <Card
                  key={nodeId}
                  size="small"
                  style={{ marginTop: 8 }}
                  title={
                    <span>
                      {nodeId}{' '}
                      <Tag
                        color={
                          result.status === 'succeeded'
                            ? 'green'
                            : result.status === 'failed'
                              ? 'red'
                              : 'default'
                        }
                      >
                        {result.status}
                      </Tag>
                    </span>
                  }
                  extra={
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {result.elapsed || result.tokens} tokens
                    </Text>
                  }
                >
                  {result.output && Object.keys(result.output).length > 0 && (
                    <pre
                      style={{
                        fontSize: 11,
                        maxHeight: 150,
                        overflow: 'auto',
                        background: '#f5f5f5',
                        padding: 8,
                        borderRadius: 4,
                      }}
                    >
                      {JSON.stringify(result.output, null, 2)}
                    </pre>
                  )}
                  {result.error && (
                    <Text type="danger" style={{ fontSize: 12 }}>
                      错误: {result.error}
                    </Text>
                  )}
                </Card>
              ))}
            </div>
          )}

          {outputs && Object.keys(outputs).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Text strong>最终输出</Text>
              <pre
                style={{
                  fontSize: 11,
                  maxHeight: 200,
                  overflow: 'auto',
                  background: '#f0f5ff',
                  padding: 8,
                  borderRadius: 4,
                  marginTop: 4,
                }}
              >
                {JSON.stringify(outputs, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {errorMsg && (
        <div style={{ marginTop: 12 }}>
          <Text type="danger" strong>
            执行失败
          </Text>
          <pre
            style={{
              fontSize: 12,
              color: '#ff4d4f',
              background: '#fff2f0',
              padding: 8,
              borderRadius: 4,
              marginTop: 4,
            }}
          >
            {errorMsg}
          </pre>
        </div>
      )}

      {!runResult && !running && (
        <Empty description="输入测试数据后点击「运行」按钮执行工作流" />
      )}
    </Card>
  )
}
