'use client'

import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Space,
  Select,
  Card,
  Row,
  Col,
  Typography,
  Statistic,
  Progress,
  InputNumber,
  message,
  Alert,
  Switch,
  Divider,
} from 'antd'
import {
  CalculatorOutlined,
  ReloadOutlined,
  EditOutlined,
} from '@ant-design/icons'
import { useProductionStore } from '@/stores/production'
import { getBatches, getMaterialBalance, calculateMaterialBalance } from '@/actions/production'
import type { Batch, MaterialBalance } from '@/types/production'

const { Text, Title } = Typography

export default function BalancePage() {
  const [loading, setLoading] = useState(false)
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>()
  const [minBalanceRate, setMinBalanceRate] = useState<number>(95)
  const [batches, setBatches] = useState<Batch[]>([])
  const [editMode, setEditMode] = useState(false)
  const [manualInput, setManualInput] = useState({ input_qty: 0, output_qty: 0 })

  const {
    materialBalance,
    materialBalanceLoading,
    setMaterialBalance,
    setMaterialBalanceLoading,
  } = useProductionStore()

  const loadBatches = async () => {
    try {
      const response = await getBatches({ page: 1, page_size: 100 })
      if (response.code === 200) {
        setBatches(response.data)
      }
    } catch {
      message.error('加载批次列表失败')
    }
  }

  const loadBalance = async () => {
    if (!selectedBatchId) {
      setMaterialBalance(null)
      return
    }
    setMaterialBalanceLoading(true)
    try {
      const response = await getMaterialBalance(selectedBatchId)
      if (response.code === 200) {
        setMaterialBalance(response.data)
        if (response.data) {
          setManualInput({
            input_qty: response.data.input_qty || 0,
            output_qty: response.data.output_qty || 0,
          })
        }
      } else if (response.code === 404) {
        setMaterialBalance(null)
        setManualInput({ input_qty: 0, output_qty: 0 })
      }
    } catch {
      message.error('加载物料平衡数据失败')
    } finally {
      setMaterialBalanceLoading(false)
    }
  }

  useEffect(() => {
    loadBatches()
  }, [])

  useEffect(() => {
    loadBalance()
  }, [selectedBatchId])

  const handleCalculate = async () => {
    if (!selectedBatchId) {
      message.warning('请先选择批次')
      return
    }
    setLoading(true)
    try {
      const response = await calculateMaterialBalance(selectedBatchId, minBalanceRate)
      if (response.code === 200) {
        message.success('计算成功')
        setMaterialBalance(response.data)
        if (response.data) {
          setManualInput({
            input_qty: response.data.input_qty || 0,
            output_qty: response.data.output_qty || 0,
          })
        }
      } else {
        message.error(response.message || '计算失败')
      }
    } catch {
      message.error('计算失败')
    } finally {
      setLoading(false)
    }
  }

  // 手动计算平衡（基于用户输入的值）
  const calculateManualBalance = () => {
    if (!materialBalance) return

    const input = manualInput.input_qty
    const output = manualInput.output_qty
    const loss = input - output
    const balanceRate = input > 0 ? (output / input * 100) : 0
    const isBalanced = balanceRate >= minBalanceRate
    const deviationRate = Math.abs(balanceRate - 100)

    setMaterialBalance({
      ...materialBalance,
      input_qty: input,
      output_qty: output,
      loss_qty: loss,
      balance_rate: Math.round(balanceRate * 100) / 100,
      is_balanced: isBalanced,
      deviation_rate: Math.round(deviationRate * 100) / 100,
      calculated_at: new Date().toISOString(),
    })
    setEditMode(false)
    message.success('已更新物料平衡数据')
  }

  return (
    <div className="p-6">
      <Card
        title="物料平衡"
        extra={
          <Space>
            <Text type="secondary">手动输入</Text>
            <Switch size="small" checked={editMode} onChange={setEditMode} />
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => setEditMode(!editMode)}
            >
              {editMode ? '取消编辑' : '编辑'}
            </Button>
          </Space>
        }
      >
        <Row gutter={16} className="mb-4">
          <Col span={8}>
            <Select
              placeholder="选择批次"
              value={selectedBatchId}
              onChange={(value) => setSelectedBatchId(value)}
              style={{ width: '100%' }}
              showSearch
              optionFilterProp="children"
              options={batches.map((b) => ({
                value: b.id,
                label: `${b.batch_no} - ${b.product_name || b.product_code}`,
              }))}
            />
          </Col>
          <Col span={4}>
            <Space.Compact style={{ width: '100%' }}>
              <InputNumber
                min={0}
                max={100}
                value={minBalanceRate}
                onChange={(value) => setMinBalanceRate(value || 95)}
                style={{ flex: 1 }}
              />
              <span style={{ padding: '0 12px', background: '#fafafa', border: '1px solid #d9d9d9', borderLeft: 0, display: 'flex', alignItems: 'center' }}>%</span>
            </Space.Compact>
          </Col>
          <Col span={4}>
            <Button
              type="primary"
              icon={<CalculatorOutlined />}
              onClick={handleCalculate}
              loading={loading}
              disabled={!selectedBatchId}
            >
              自动计算
            </Button>
          </Col>
          <Col span={4}>
            <Button
              icon={<ReloadOutlined />}
              onClick={loadBalance}
              disabled={!selectedBatchId}
            >
              刷新
            </Button>
          </Col>
        </Row>

        {materialBalance ? (
          <>
            <Alert
              variant="filled"
              type={materialBalance.is_balanced ? 'success' : 'warning'}
              title={materialBalance.is_balanced ? '物料平衡合格' : '物料平衡不合格'}
              description={`平衡率 ${materialBalance.balance_rate?.toFixed(2)}% ${
                materialBalance.is_balanced
                  ? '满足最低要求'
                  : `低于最低要求 ${materialBalance.min_balance_rate}%`
              }`}
              showIcon
              className="mb-4"
              style={{ borderRadius: 8 }}
            />

            {/* 投入产出编辑区域 */}
            {editMode && (
              <Card className="mb-4" style={{ background: '#fafafa' }}>
                <Row gutter={24} align="middle">
                  <Col span={8}>
                    <Text strong>投入总量 (kg)：</Text>
                    <InputNumber
                      min={0}
                      value={manualInput.input_qty}
                      onChange={(v) => setManualInput({ ...manualInput, input_qty: v || 0 })}
                      style={{ width: '100%', marginTop: 8 }}
                      size="large"
                      precision={2}
                    />
                  </Col>
                  <Col span={8}>
                    <Text strong>产出总量 (kg)：</Text>
                    <InputNumber
                      min={0}
                      value={manualInput.output_qty}
                      onChange={(v) => setManualInput({ ...manualInput, output_qty: v || 0 })}
                      style={{ width: '100%', marginTop: 8 }}
                      size="large"
                      precision={2}
                    />
                  </Col>
                  <Col span={8}>
                    <Button type="primary" onClick={calculateManualBalance} size="large">
                      应用并计算
                    </Button>
                  </Col>
                </Row>
              </Card>
            )}

            <Row gutter={16} className="mb-6">
              <Col span={6}>
                <Card>
                  {editMode ? (
                    <>
                      <Text type="secondary">投入总量</Text>
                      <InputNumber
                        min={0}
                        value={manualInput.input_qty}
                        onChange={(v) => setManualInput({ ...manualInput, input_qty: v || 0 })}
                        style={{ width: '100%', marginTop: 4 }}
                        size="large"
                        precision={2}
                        prefix="≈"
                        suffix="kg"
                      />
                    </>
                  ) : (
                    <Statistic
                      title="投入总量"
                      value={materialBalance.input_qty || 0}
                      precision={2}
                      suffix="kg"
                    />
                  )}
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  {editMode ? (
                    <>
                      <Text type="secondary">产出总量</Text>
                      <InputNumber
                        min={0}
                        value={manualInput.output_qty}
                        onChange={(v) => setManualInput({ ...manualInput, output_qty: v || 0 })}
                        style={{ width: '100%', marginTop: 4 }}
                        size="large"
                        precision={2}
                        prefix="≈"
                        suffix="kg"
                      />
                    </>
                  ) : (
                    <Statistic
                      title="产出总量"
                      value={materialBalance.output_qty || 0}
                      precision={2}
                      suffix="kg"
                    />
                  )}
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="损耗总量"
                    value={materialBalance.loss_qty || 0}
                    precision={2}
                    suffix="kg"
                  />
                </Card>
              </Col>
              <Col span={6}>
                <Card>
                  <Statistic
                    title="平衡率"
                    value={materialBalance.balance_rate || 0}
                    precision={2}
                    suffix="%"
                  />
                  <Progress
                    percent={materialBalance.balance_rate || 0}
                    strokeColor={materialBalance.is_balanced ? '#52c41a' : '#faad14'}
                    showInfo={false}
                    className="mt-2"
                  />
                </Card>
              </Col>
            </Row>

            <Card title="平衡详情" className="mb-4">
              <Row gutter={16}>
                <Col span={8}>
                  <Text type="secondary">最低平衡率要求：</Text>
                  <Text strong>{materialBalance.min_balance_rate}%</Text>
                </Col>
                <Col span={8}>
                  <Text type="secondary">偏差率：</Text>
                  <Text strong>{materialBalance.deviation_rate?.toFixed(2) || 0}%</Text>
                </Col>
                <Col span={8}>
                  <Text type="secondary">计算时间：</Text>
                  <Text>
                    {materialBalance.calculated_at
                      ? new Date(materialBalance.calculated_at).toLocaleString('zh-CN')
                      : '-'}
                  </Text>
                </Col>
              </Row>
              {materialBalance.notes && (
                <Row className="mt-4">
                  <Col span={24}>
                    <Text type="secondary">备注：</Text>
                    <Text>{materialBalance.notes}</Text>
                  </Col>
                </Row>
              )}
            </Card>
          </>
        ) : (
          <div className="text-center py-12">
            <Text type="secondary">
              {selectedBatchId
                ? '暂无物料平衡数据，请点击"自动计算"按钮进行计算'
                : '请选择批次查看物料平衡数据'}
            </Text>
          </div>
        )}
      </Card>

      <Card title="使用说明" className="mt-4">
        <Text type="secondary">
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            <li style={{ marginBottom: 8 }}>
              <strong>自动计算：</strong>根据批次关联的物料数据和批次产量自动计算投入产出平衡
            </li>
            <li style={{ marginBottom: 8 }}>
              <strong>手动输入：</strong>开启编辑模式后，可直接输入投入总量和产出总量进行计算
            </li>
            <li>
              <strong>平衡率标准：</strong>默认要求平衡率 ≥ 最低平衡率（默认95%），低于此值会触发预警
            </li>
          </ul>
        </Text>
      </Card>
    </div>
  )
}
