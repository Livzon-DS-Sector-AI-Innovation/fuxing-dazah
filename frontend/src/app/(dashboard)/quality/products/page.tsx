'use client'

import { useState, useEffect } from 'react'
import { Table, Typography, Button, Input, Space, Tag, message, Card, Popconfirm, Row, Col } from 'antd'
import { PlusOutlined, DeleteOutlined, SaveOutlined, ReloadOutlined, ExperimentOutlined } from '@ant-design/icons'

const { Title, Text } = Typography
const API = 'http://localhost:8000/api/v1/quality/products'

interface Product {
  name: string
  codes: string
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const r = await fetch(API)
      if (r.ok) setProducts(await r.json())
    } catch { message.error('加载失败') }
    setLoading(false)
  }

  async function save() {
    const cleaned = products.filter(p => p.name.trim())
    const r = await fetch(API, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cleaned),
    })
    if (r.ok) { message.success('已保存'); load() }
    else message.error('保存失败')
  }

  function add() {
    setProducts([...products, { name: '', codes: '' }])
  }

  function update(idx: number, field: keyof Product, val: string) {
    const next = [...products]
    next[idx] = { ...next[idx], [field]: val }
    setProducts(next)
  }

  function del(idx: number) {
    setProducts(products.filter((_, i) => i !== idx))
  }

  // 初始化默认数据
  function initDefaults() {
    setProducts([
      { name: '盐酸万古霉素', codes: 'HAF HAA HAPG HAP' },
      { name: '万古霉素', codes: 'HAF' },
      { name: '替考拉宁', codes: 'TAF TAG TAA TE' },
      { name: '达托霉素', codes: 'DAG DA' },
      { name: '米尔贝肟', codes: 'MO MAB' },
    ])
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <ExperimentOutlined style={{ fontSize: 20, color: '#1a73e8' }} />
          <Title level={4} style={{ margin: 0 }}>产品代码管理</Title>
        </Space>
        <Space>
          {!products.length && <Button onClick={initDefaults}>加载默认数据</Button>}
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={save}>保存</Button>
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          产品名用于结果汇总的分类筛选。代码用空格分隔（如 HAF HAA），系统自动按批号前缀匹配分类。
        </Text>
      </Card>

      <Card size="small">
        <Row gutter={[12, 8]}>
          {products.map((p, i) => (
            <Col span={8} key={i}>
              <Card size="small" title={
                <Input value={p.name} onChange={e => update(i, 'name', e.target.value)}
                  placeholder="产品名" style={{ fontWeight: 600, width: '100%' }} bordered={false} />
              } extra={
                <Popconfirm title="删除？" onConfirm={() => del(i)}>
                  <Button type="link" danger size="small" icon={<DeleteOutlined />} />
                </Popconfirm>
              }>
                <Input value={p.codes} onChange={e => update(i, 'codes', e.target.value)}
                  placeholder="代码，空格分隔" style={{ fontSize: 12, fontFamily: 'monospace' }} />
              </Card>
            </Col>
          ))}
          <Col span={8}>
            <Card size="small" style={{ borderStyle: 'dashed', cursor: 'pointer', textAlign: 'center', minHeight: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              onClick={add}>
              <Text type="secondary"><PlusOutlined /> 添加产品</Text>
            </Card>
          </Col>
        </Row>
      </Card>
    </div>
  )
}
